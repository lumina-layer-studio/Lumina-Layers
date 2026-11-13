"""Converter puzzle routes.
图像转换拼图模式路由。

This module implements puzzle-layout overlay preview and puzzle piece export
for the converter workspace.
本模块实现图像转换工作区的拼图叠线预览与拼图导出。
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import pickle
import tempfile
import uuid
from collections.abc import AsyncIterator
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from PIL import Image

from api.project_export import embed_generated_project, revision_bytes
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.errors import to_http_exception
from api.export_device_validation import validate_export_device_selection
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import (
    get_preview_cache_metadata,
    hydrate_preview_cache,
    is_preview_cache_artifact_ref,
)
from api.schemas.converter import (
    ConvertGenerateRequest,
    ModelingMode,
    PuzzleGenerateRequest,
    PuzzleLayoutPreviewRequest,
)
from api.schemas.responses import PuzzleGenerateResponse, PuzzleLayoutPreviewResponse
from api.selection_state import unpack_applied_region_mask
from api.session_store import SessionStore
from api.structured_logging import get_logger
from api.worker_pool import WorkerPoolManager
from api.workers.converter_workers import (
    _batch_extract_slots_from_3mf,
    worker_generate_model,
)
from config import ModelingMode as CoreModelingMode
from config import TEMP_DIR
from core.errors import ExternalSpoolSelectionError, NativeMaterialSelectionError, TemplateSlotCapacityError, WipeTowerLayoutError
from core.preview_analysis_cache import REQUIRED_PREVIEW_ANALYSIS_REUSE
from .export_materials import require_material_selection
from core.puzzle import (
    PuzzleLayout,
    PuzzleLayoutConfig,
    PuzzlePiece,
    build_puzzle_layout,
    export_piece_boundary_geometry,
    rasterize_piece_mask,
    render_assembly_overview,
    render_puzzle_overlay,
    resolve_puzzle_mask_geometry,
)
from core.puzzle_3mf import (
    PuzzlePiece3MFSource,
    assemble_puzzle_3mf,
)
from core.material_dynamic_solver import (
    DynamicMaterialCandidateError,
    DynamicMaterialSolverError,
)
from utils.bambu_3mf_writer import read_wipe_tower_placement_warnings
from utils.fatcat_metadata import select_metadata_target
from utils.merged_bambu_3mf_writer import MaterialSlot as WriterMaterialSlot
from .generation_params import build_common_generation_params

from .common import (
    BATCH_DOWNLOAD_TTL_SECONDS,
    LUT_DATA_UNAVAILABLE_DETAIL,
    PREVIEW_CACHE_INVALID_DETAIL,
    PREVIEW_CACHE_UNAVAILABLE_DETAIL,
    RECIPE_OVERRIDE_APPLIED_MASKS_KEY,
    ROUTER_HANDLED_ERRORS,
    SOURCE_IMAGE_UNAVAILABLE_DETAIL,
    _handle_core_error,
    _require_session,
    _resolve_session_dynamic_material_settings,
    _resolve_material_backing_index,
    _validate_unique_dynamic_material_selection,
    _validate_material_archive_relief_minimum_height,
)
from .generate import (
    _assert_editor_snapshot_current,
    _capture_generation_snapshot,
    _preview_analysis_params_match,
    _resolve_recipe_overrides,
    _serialize_recipe_override_for_worker,
)

router = APIRouter()
log = get_logger(__name__)
_PUZZLE_WORKER_PIXELS_PER_MM = 10.0
_PUZZLE_TOTAL_CUT_CLEARANCE_MM = 0.1
_PUZZLE_BOUNDARY_INSET_MM = _PUZZLE_TOTAL_CUT_CLEARANCE_MM / 2.0
_PUZZLE_ASSEMBLY_FAILED_DETAIL = (
    "Puzzle 3MF assembly failed. The generated pieces could not be "
    "combined into a downloadable file. Try generating the puzzle again."
)
_PUZZLE_PIECE_GENERATION_FAILED_DETAIL = (
    "Puzzle generation failed for one or more pieces. Re-run preview and "
    "try generating the puzzle again."
)
_MATERIAL_PUZZLE_ANALYSIS_UNAVAILABLE_DETAIL = (
    "Material puzzle preview analysis is incomplete or inconsistent. "
    "Re-run preview before generating puzzle pieces."
)


@dataclass(frozen=True)
class PuzzlePieceWorkerAssets:
    """Raster inputs for one puzzle worker, kept in one typed container.
    单个拼图 worker 的栅格输入，统一放在强类型容器中。

    Material generation additionally carries the cropped authority
    arrays from the confirmed preview. Keeping these fields together avoids
    positional tuple mistakes that could pair a matrix with another piece.
    耗材生成还携带来自已确认预览的裁切权威数组。将这些字段放在一起可避免
    位置元组错配，例如把一个拼图块的矩阵配给另一个拼图块。
    """

    bbox_px: tuple[int, int, int, int]
    rgba: np.ndarray
    matched_rgb: np.ndarray
    boundary_payload: dict[str, Any]
    mask_solid: np.ndarray | None = None
    quantized_image: np.ndarray | None = None
    material_matrix: np.ndarray | None = None
    backing_mask: np.ndarray | None = None


class _PuzzleLayoutPreviewBody(BaseModel):
    """Wrapper combining session_id with puzzle preview parameters.
    将 ``session_id`` 与拼图预览参数组合在一起的请求模型。
    """

    session_id: str
    params: PuzzleLayoutPreviewRequest


class _PuzzleGenerateBody(BaseModel):
    """Wrapper combining session_id with puzzle generate parameters.
    将 ``session_id`` 与拼图生成参数组合在一起的请求模型。
    """

    session_id: str
    params: PuzzleGenerateRequest


@dataclass(frozen=True)
class _PuzzlePieceJob:
    """Detached inputs; constructing a job does not start a coroutine."""

    piece: PuzzlePiece
    image_path: str
    lut_path: str
    params: dict[str, Any]


def _require_puzzle_cache(
    session_data: dict[str, Any],
    *,
    fields: set[str],
) -> dict[str, Any]:
    """Load only the preview-cache fields needed by puzzle routes.

    只加载拼图路由实际需要的 preview-cache 字段。
    """
    cache = session_data.get("preview_cache")
    if cache is None:
        raise HTTPException(
            status_code=409,
            detail=PREVIEW_CACHE_UNAVAILABLE_DETAIL,
        )
    if not isinstance(cache, dict):
        raise HTTPException(
            status_code=409,
            detail=PREVIEW_CACHE_INVALID_DETAIL,
        )
    if not is_preview_cache_artifact_ref(cache):
        return cache

    loaded = get_preview_cache_metadata(cache)
    try:
        loaded.update(
            hydrate_preview_cache(
                cache,
                fields=fields,
                mmap_mode="r",
            )
        )
    except (OSError, ValueError, TypeError, KeyError, EOFError) as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Puzzle preview cache is unavailable. "
                "Re-run preview before using puzzle mode."
            ),
        ) from exc
    return loaded


def _require_material_puzzle_analysis(
    cache: dict[str, Any],
    *,
    layer_count: int | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return validated preview recipes for fixed and dynamic material puzzles.
    返回已校验的固定层数及动态层数耗材拼图预览配方。

    Piece generation must not fall back to solving from RGB. The
    preview matrix can encode accepted manual recipes and virtual materials,
    so every source array has to be present, aligned, and at the preview's
    physical layer depth before any worker is scheduled.
    拼图生成不能退回为根据 RGB 重算。预览矩阵可能编码已确认的手工配方和
    虚拟耗材，因此在调度 worker 前，所有源数组必须存在、对齐，并且具有预览的
    物理层深。
    """

    matched_rgb = cache.get("matched_rgb")
    mask_solid = cache.get("mask_solid")
    quantized_image = cache.get("quantized_image")
    material_matrix = cache.get("material_matrix")
    if not all(
        isinstance(value, np.ndarray)
        for value in (matched_rgb, mask_solid, quantized_image, material_matrix)
    ):
        raise HTTPException(
            status_code=409,
            detail=_MATERIAL_PUZZLE_ANALYSIS_UNAVAILABLE_DETAIL,
        )
    if (
        matched_rgb.dtype != np.uint8
        or matched_rgb.ndim != 3
        or matched_rgb.shape[2] != 3
    ):
        raise HTTPException(status_code=409, detail=_MATERIAL_PUZZLE_ANALYSIS_UNAVAILABLE_DETAIL)
    image_shape = matched_rgb.shape[:2]
    if (
        mask_solid.dtype != np.bool_
        or mask_solid.shape != image_shape
        or quantized_image.dtype != np.uint8
        or quantized_image.shape != matched_rgb.shape
        or not np.issubdtype(material_matrix.dtype, np.signedinteger)
        or material_matrix.ndim != 3
        or material_matrix.shape[:2] != image_shape
        or material_matrix.shape[2] <= 0
        or (layer_count is not None and material_matrix.shape[2] != layer_count)
    ):
        raise HTTPException(status_code=409, detail=_MATERIAL_PUZZLE_ANALYSIS_UNAVAILABLE_DETAIL)
    return matched_rgb, mask_solid, quantized_image, material_matrix


def _get_source_rgba(cache: dict[str, Any]) -> np.ndarray:
    """Return the canonical raster source for puzzle cropping.
    返回用于拼图裁切的标准栅格源图。

    Args:
        cache: Preview cache stored in session. (Session 中保存的预览缓存)

    Returns:
        np.ndarray: RGBA image in preview pixel space. (预览像素空间中的 RGBA 图像)

    Raises:
        ValueError: If required preview cache keys are missing. (缺少所需预览缓存键时抛出)
    """

    preview_rgba = cache.get("preview_rgba")
    if isinstance(preview_rgba, np.ndarray) and preview_rgba.ndim == 3 and preview_rgba.shape[2] == 4:
        return preview_rgba.astype(np.uint8, copy=False)

    matched_rgb = cache.get("matched_rgb")
    mask_solid = cache.get("mask_solid")
    if matched_rgb is None or mask_solid is None:
        raise ValueError("Preview cache missing matched_rgb or mask_solid for puzzle mode.")

    h_px, w_px = matched_rgb.shape[:2]
    source_rgba = np.zeros((h_px, w_px, 4), dtype=np.uint8)
    source_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    source_rgba[mask_solid, 3] = 255
    return source_rgba


def _get_layout_dimensions(
    cache: dict[str, Any],
    request: PuzzleLayoutPreviewRequest,
) -> tuple[int, int, float, float]:
    """Resolve preview and physical dimensions for puzzle layout.
    解析拼图布局所需的预览尺寸与物理尺寸。
    """

    matched_rgb = cache.get("matched_rgb")
    if matched_rgb is None or matched_rgb.ndim != 3:
        raise ValueError("Preview cache missing matched_rgb for puzzle layout.")

    height_px, width_px = matched_rgb.shape[:2]
    if height_px <= 0 or width_px <= 0:
        raise ValueError("Preview cache dimensions are invalid for puzzle layout.")

    total_height_mm = float(request.target_height_mm)
    total_width_mm = total_height_mm * (width_px / max(height_px, 1))
    return width_px, height_px, total_width_mm, total_height_mm


def _get_mask_identity(mask_solid: np.ndarray | None) -> str | bytes:
    """Compare the exact packed solid mask.
    直接比较当前实体蒙版的完整压缩数据。
    """

    if mask_solid is None:
        return "none"
    solid_mask = np.asarray(mask_solid, dtype=bool)
    if solid_mask.size == 0 or np.all(solid_mask):
        return "full-rect"
    packed = np.packbits(solid_mask, axis=None)
    return packed.tobytes()


def _puzzle_footprint(cache: dict[str, Any]) -> np.ndarray | None:
    """The structural footprint can include backing where no color was deposited."""
    footprint = cache.get("backing_mask")
    if footprint is None:
        footprint = cache.get("mask_solid")
    return footprint


def _build_layout_cache_key(
    config: PuzzleLayoutConfig,
    boundary_key: tuple[Any, ...],
) -> tuple[Any, ...]:
    """Build a stable cache key for puzzle layout geometry.
    为拼图布局几何生成稳定缓存键。
    """

    return boundary_key + (
        round(config.total_width_mm, 6),
        round(config.total_height_mm, 6),
        config.style,
        config.sizing_mode,
        round(config.piece_width_mm, 6),
        round(config.piece_height_mm, 6),
        config.rows,
        config.cols,
        config.target_piece_count,
        config.seed,
        config.connector_style,
        round(config.irregularity_strength, 6),
        round(config.min_neck_width_mm, 6),
    )


def _build_overlay_cache_key(
    layout_cache_key: tuple[Any, ...],
    request: PuzzleLayoutPreviewRequest,
) -> tuple[Any, ...]:
    """Build a stable cache key for preview overlay images.
    为预览叠线图生成稳定缓存键。
    """

    return layout_cache_key + (bool(request.labels_enabled),)


def _build_layout_config(
    cache: dict[str, Any],
    request: PuzzleLayoutPreviewRequest,
) -> PuzzleLayoutConfig:
    """Build the authoritative core layout configuration.
    构建唯一权威的核心拼图布局配置。
    """

    width_px, height_px, total_width_mm, total_height_mm = _get_layout_dimensions(cache, request)
    footprint = _puzzle_footprint(cache)
    if footprint is not None and (
        not isinstance(footprint, np.ndarray) or footprint.shape != (height_px, width_px)
    ):
        raise ValueError("Puzzle footprint must match the preview dimensions.")

    return PuzzleLayoutConfig(
        width_px=width_px,
        height_px=height_px,
        total_width_mm=total_width_mm,
        total_height_mm=total_height_mm,
        style=request.puzzle_style.value,
        sizing_mode=request.sizing_mode.value,
        piece_width_mm=request.piece_width_mm,
        piece_height_mm=request.piece_height_mm,
        rows=request.rows,
        cols=request.cols,
        target_piece_count=request.target_piece_count,
        seed=request.seed,
        connector_style=request.connector_style.value,
        irregularity_strength=request.irregularity_strength,
        min_neck_width_mm=request.min_neck_width_mm,
        solid_mask=footprint,
    )


def _resolve_layout(
    *,
    session_data: dict[str, Any],
    cache: dict[str, Any],
    request: PuzzleLayoutPreviewRequest,
    store: SessionStore,
    session_id: str,
) -> tuple[PuzzleLayout, tuple[Any, ...]]:
    """Resolve and cache the authoritative puzzle layout.
    解析并缓存权威拼图布局。
    """

    config = _build_layout_config(cache, request)
    boundary_key = (config.width_px, config.height_px, _get_mask_identity(config.solid_mask))
    layout_cache_key = _build_layout_cache_key(config, boundary_key)
    cached_key = session_data.get("puzzle_layout_cache_key")
    cached_layout = session_data.get("puzzle_layout_cache")
    if cached_key == layout_cache_key and isinstance(cached_layout, PuzzleLayout):
        return cached_layout, layout_cache_key

    if session_data.get("puzzle_boundary_geometry_key") == boundary_key:
        geometry = session_data.get("puzzle_boundary_geometry")
    else:
        geometry = resolve_puzzle_mask_geometry(config)
        store.put(session_id, "puzzle_boundary_geometry_key", boundary_key)
        store.put(session_id, "puzzle_boundary_geometry", geometry)
    layout = build_puzzle_layout(replace(config, mask_geometry=geometry))
    store.put(session_id, "puzzle_layout_cache_key", layout_cache_key)
    store.put(session_id, "puzzle_layout_cache", layout)
    return layout, layout_cache_key


def _crop_piece_arrays(
    source_rgba: np.ndarray,
    matched_rgb: np.ndarray,
    bbox_px: tuple[int, int, int, int],
    local_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Preserve the source alpha and clear artwork outside the piece."""
    x0, y0, x1, y1 = bbox_px
    rgba = source_rgba[y0:y1, x0:x1].copy()
    colors = matched_rgb[y0:y1, x0:x1].copy()
    outside = local_mask == 0
    rgba[outside] = 0
    colors[outside] = 0
    return rgba, colors


def _resolve_piece_worker_raster_size(piece: PuzzlePiece) -> tuple[int, int]:
    """Resolve the exact raster size the worker will rebuild for one piece.
    解析 worker 最终会为单个拼图块重建的精确光栅尺寸。

    The downstream worker always rasterizes high-fidelity puzzle pieces at
    ``10 px/mm`` based on the physical bbox dimensions. Puzzle-mode helper
    assets must match that raster grid exactly, otherwise ``matched_rgb`` and
    polygon boundaries drift out of sync for SVG/vector preview caches.
    下游 worker 会基于物理包围盒尺寸按 ``10 px/mm`` 重新光栅化高保真拼图块。
    若辅助资产不与该栅格完全一致，则 ``matched_rgb`` 和 polygon 边界会在
    SVG/矢量预览缓存下发生错位。
    """

    width_mm = max(0.0, float(piece.bbox_mm[2] - piece.bbox_mm[0]))
    height_mm = max(0.0, float(piece.bbox_mm[3] - piece.bbox_mm[1]))
    # Mirror the worker's rounded 10 px/mm rebuild rule so preview-cropped
    # helper assets stay aligned for SVG-derived piece dimensions.
    target_w = max(1, int(round(width_mm * _PUZZLE_WORKER_PIXELS_PER_MM)))
    target_h = max(1, int(round(height_mm * _PUZZLE_WORKER_PIXELS_PER_MM)))
    return target_w, target_h


def _resize_piece_array_nearest(array: np.ndarray, target_size: tuple[int, int]) -> np.ndarray:
    """Use one Pillow nearest-neighbor grid for RGB, masks, and recipe stacks."""

    target_w, target_h = (max(1, int(target_size[0])), max(1, int(target_size[1])))
    if array.ndim not in {2, 3}:
        raise ValueError("Puzzle worker asset must be a 2D or 3D array.")
    if array.shape[1] == target_w and array.shape[0] == target_h:
        return np.array(array, copy=True)

    # Resize coordinate indices instead of values: Pillow cannot represent
    # every recipe dtype, and all layers must use exactly the RGB sampling grid.
    x_indices = np.asarray(Image.fromarray(
        np.arange(array.shape[1], dtype=np.int32)[None, :],
    ).resize((target_w, 1), Image.Resampling.NEAREST))[0]
    y_indices = np.asarray(Image.fromarray(
        np.arange(array.shape[0], dtype=np.int32)[:, None],
    ).resize((1, target_h), Image.Resampling.NEAREST))[:, 0]
    return array[y_indices[:, None], x_indices[None, :]]


def _prepare_piece_worker_assets(
    source_rgba: np.ndarray,
    matched_rgb: np.ndarray,
    piece: PuzzlePiece,
    *,
    backing_mask: np.ndarray | None = None,
    mask_solid: np.ndarray | None = None,
    quantized_image: np.ndarray | None = None,
    material_matrix: np.ndarray | None = None,
) -> PuzzlePieceWorkerAssets:
    """Prepare raster and boundary assets aligned to the worker grid.
    准备与 worker 栅格严格对齐的拼图块图像与边界资产。
    """

    bbox_px, local_mask = rasterize_piece_mask(piece)
    piece_rgba, piece_matched = _crop_piece_arrays(source_rgba, matched_rgb, bbox_px, local_mask)
    x0, y0, x1, y1 = bbox_px
    crop = np.s_[y0:y1, x0:x1]
    inside = local_mask.astype(bool, copy=False)
    target_size = _resolve_piece_worker_raster_size(piece)
    boundary_payload = export_piece_boundary_geometry(
        piece,
        raster_size=target_size,
        inset_px=_PUZZLE_BOUNDARY_INSET_MM * _PUZZLE_WORKER_PIXELS_PER_MM,
    )
    analysis_assets = (mask_solid, quantized_image, material_matrix)
    if any(asset is not None for asset in analysis_assets) and not all(
        asset is not None for asset in analysis_assets
    ):
        raise ValueError("Material puzzle assets must be supplied together.")

    piece_mask: np.ndarray | None = None
    piece_quantized: np.ndarray | None = None
    piece_matrix: np.ndarray | None = None
    if all(asset is not None for asset in analysis_assets):
        piece_mask = mask_solid[crop] & inside
        piece_quantized = quantized_image[crop].copy()
        piece_matrix = material_matrix[crop].copy()
        piece_quantized[~piece_mask] = 0
        piece_matrix[~piece_mask] = -1
        piece_matched[~piece_mask] = 0

    return PuzzlePieceWorkerAssets(
        bbox_px=bbox_px,
        rgba=_resize_piece_array_nearest(piece_rgba, target_size),
        matched_rgb=_resize_piece_array_nearest(piece_matched, target_size),
        boundary_payload=boundary_payload,
        backing_mask=(
            _resize_piece_array_nearest(backing_mask[crop].astype(bool, copy=False) & inside, target_size)
            if backing_mask is not None else None
        ),
        mask_solid=(
            _resize_piece_array_nearest(piece_mask, target_size)
            if piece_mask is not None
            else None
        ),
        quantized_image=(
            _resize_piece_array_nearest(piece_quantized, target_size)
            if piece_quantized is not None
            else None
        ),
        material_matrix=(
            _resize_piece_array_nearest(piece_matrix, target_size)
            if piece_matrix is not None
            else None
        ),
    )


def _prepare_piece_recipe_override_masks(
    *,
    region_masks: object,
    recipe_overrides: list[dict[str, object]] | None,
    piece: PuzzlePiece,
    source_shape: tuple[int, int],
    target_size: tuple[int, int],
    piece_solid_mask: np.ndarray,
) -> dict[str, np.ndarray]:
    """Crop persisted override masks onto one dynamic puzzle worker grid.
    将持久化的配方覆盖掩码裁切到一个动态拼图 worker 栅格。

    The copied material matrix is authoritative for the selected stacks, but
    S03 still needs these masks to rebuild the matching virtual-material
    palette in the isolated worker process. Every declared override therefore
    needs a source-sized mask; silently omitting one can leave an out-of-range
    material index in the matrix without its colour definition.
    已复制的材料矩阵是所选堆栈的权威数据，但隔离 worker 内的 S03 仍需这些
    掩码来重建对应的虚拟耗材调色板。因此每个已声明覆盖都必须有与源图同尺寸的
    掩码；静默漏掉一个会让矩阵出现没有颜色定义的越界材料索引。
    """
    if not recipe_overrides:
        return {}
    if not isinstance(region_masks, dict):
        raise ValueError("material puzzle recipe override masks are unavailable")

    bbox_px, local_piece_mask = rasterize_piece_mask(piece)
    x0, y0, x1, y1 = bbox_px
    cropped_masks: dict[str, np.ndarray] = {}
    for item in recipe_overrides:
        region_id = str(item.get("region_id") or "").strip()
        if not region_id:
            raise ValueError("material puzzle recipe override is missing region_id")
        raw_mask = region_masks.get(region_id)
        if raw_mask is None:
            raise ValueError(
                f"material puzzle recipe override mask is missing for {region_id}"
            )
        mask = np.asarray(raw_mask, dtype=bool)
        if mask.shape != source_shape:
            raise ValueError(
                f"material puzzle recipe override mask for {region_id} has "
                f"shape {mask.shape}, expected {source_shape}"
            )
        piece_mask = np.array(mask[y0:y1, x0:x1], copy=True)
        piece_mask &= local_piece_mask.astype(bool, copy=False)
        piece_mask = _resize_piece_array_nearest(piece_mask, target_size)
        if piece_mask.shape != piece_solid_mask.shape:
            raise ValueError("dynamic puzzle override mask does not match worker grid")
        piece_mask &= np.asarray(piece_solid_mask, dtype=bool)
        if np.any(piece_mask):
            cropped_masks[region_id] = piece_mask
    return cropped_masks


def _save_png_array(session_id: str, store: SessionStore, array: np.ndarray, prefix: str) -> str:
    """Persist a numpy image array as a temp PNG registered to the session.
    将 NumPy 图像数组保存为已注册到 Session 的临时 PNG。

    Args:
        session_id: Active session identifier. (当前 Session ID)
        store: Session store used for temp-file cleanup. (用于清理临时文件的 SessionStore)
        array: Image array to save. (待保存的图像数组)
        prefix: Temp-file prefix. (临时文件前缀)

    Returns:
        str: Temp PNG path. (临时 PNG 路径)
    """

    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".png", dir=TEMP_DIR)
    os.close(fd)
    Image.fromarray(array).save(path)
    store.register_temp_file(session_id, path)
    return path


def _save_npy_array(session_id: str, store: SessionStore, array: np.ndarray, prefix: str) -> str:
    """Persist a numpy array as a temp ``.npy`` file registered to the session.
    将 NumPy 数组保存为已注册到 Session 的临时 ``.npy`` 文件。

    Args:
        session_id: Active session identifier. (当前 Session ID)
        store: Session store used for temp-file cleanup. (用于清理临时文件的 SessionStore)
        array: Array to persist. (待保存的数组)
        prefix: Temp-file prefix. (临时文件前缀)

    Returns:
        str: Temp NPY path. (临时 NPY 路径)
    """

    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".npy", dir=TEMP_DIR)
    os.close(fd)
    np.save(path, array)
    store.register_temp_file(session_id, path)
    return path


def _save_pickle_payload(
    session_id: str,
    store: SessionStore,
    payload: object,
    prefix: str,
) -> str:
    """Persist a trusted intra-process payload for a worker and register it.
    持久化可信的进程内 worker 载荷并注册清理。
    """
    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".pkl", dir=TEMP_DIR)
    os.close(fd)
    with open(path, "wb") as handle:
        pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    store.register_temp_file(session_id, path)
    return path


def _save_json_payload(session_id: str, store: SessionStore, payload: dict[str, Any], prefix: str) -> str:
    """Persist a JSON payload as a temp file registered to the session.
    将 JSON 载荷保存为已注册到 Session 的临时文件。

    Args:
        session_id: Active session identifier. (当前 Session ID)
        store: Session store used for temp-file cleanup. (用于清理临时文件的 SessionStore)
        payload: JSON-serializable payload. (可序列化为 JSON 的载荷)
        prefix: Temp-file prefix. (临时文件前缀)

    Returns:
        str: Temp JSON path. (临时 JSON 路径)
    """

    fd, path = tempfile.mkstemp(prefix=prefix, suffix=".json", dir=TEMP_DIR)
    os.close(fd)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    store.register_temp_file(session_id, path)
    return path


def _remove_temp_path(path: str | None) -> None:
    """Best-effort removal for route-local temp files not owned by a session."""

    if not path:
        return
    try:
        os.remove(path)
    except (FileNotFoundError, OSError):
        return


def _resolve_free_color_set(session_data: dict[str, Any], request: ConvertGenerateRequest) -> set[str] | None:
    free_color_set = session_data.get("free_color_set") or None
    if request.free_color_set is not None:
        free_color_set = set(request.free_color_set)
    return free_color_set


def _resolve_relief_global_max_height(
    session_data: dict[str, Any],
    request: ConvertGenerateRequest,
) -> float | None:
    if not request.enable_relief:
        return None

    height_mode = request.height_mode or "color"
    if height_mode == "color" and request.color_height_map:
        return max(request.color_height_map.values())

    if height_mode == "heightmap":
        heightmap_grayscale = session_data.get("heightmap_grayscale")
        if heightmap_grayscale is None:
            raise HTTPException(status_code=409, detail="Heightmap missing. Upload heightmap before puzzle generation.")
        return float(request.heightmap_max_height or 5.0)

    return None


def _submit_puzzle_worker(
    image_path: str,
    lut_path: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    """Submit a puzzle piece to the existing model worker with forward-compatible params.
    使用现有模型 worker 提交拼图块，并透传拼图边界参数。
    """
    return worker_generate_model(image_path, lut_path, params)


async def _iter_puzzle_piece_results(
    jobs: list[_PuzzlePieceJob],
    *,
    pool: WorkerPoolManager,
    store: SessionStore,
    session_id: str,
) -> AsyncIterator[tuple[PuzzlePiece, dict[str, Any] | BaseException]]:
    """Run bounded batches and retain output ownership before reporting errors.
    分批并行生成拼图，并在返回错误前登记同批任务的输出文件。
    """

    batch_size = max(1, int(pool.max_workers))
    for start in range(0, len(jobs), batch_size):
        batch_jobs = jobs[start : start + batch_size]
        pending = asyncio.gather(
            *(
                pool.submit(_submit_puzzle_worker, job.image_path, job.lut_path, job.params)
                for job in batch_jobs
            ),
            return_exceptions=True,
        )
        results: list[dict[str, Any] | BaseException] = []
        try:
            try:
                results = await asyncio.shield(pending)
            except asyncio.CancelledError:
                # Process-pool cancellation cannot stop running CPU work.
                # Drain only this batch so its output paths remain owned.
                results = await pending
                raise
        finally:
            for result in results:
                if isinstance(result, dict):
                    for key in ("threemf_path", "glb_path"):
                        path = result.get(key)
                        if path and os.path.exists(path):
                            store.register_temp_file(session_id, path)

        # gather keeps input order even when workers finish out of order.
        for job, result in zip(batch_jobs, results):
            yield job.piece, result


@router.post("/puzzle-layout-preview", response_model=PuzzleLayoutPreviewResponse)
async def puzzle_layout_preview(
    body: _PuzzleLayoutPreviewBody,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> PuzzleLayoutPreviewResponse:
    """Generate a transparent puzzle overlay aligned to the current preview.
    生成与当前预览对齐的透明拼图叠线。

    Args:
        body: Wrapper containing session ID and puzzle parameters.
            (包含 Session ID 与拼图参数的请求体)
        store: Session store dependency. (SessionStore 依赖)
        registry: File registry dependency. (FileRegistry 依赖)

    Returns:
        PuzzleLayoutPreviewResponse: Overlay resource and resolved layout summary.
            (包含叠线资源和解析结果摘要的响应)
    """

    session_data = _require_session(store, body.session_id)
    cache = _require_puzzle_cache(
        session_data,
        fields={"matched_rgb", "mask_solid", "backing_mask"},
    )

    try:
        layout, layout_cache_key = _resolve_layout(
            session_data=session_data,
            cache=cache,
            request=body.params,
            store=store,
            session_id=body.session_id,
        )
        overlay_cache_key = _build_overlay_cache_key(layout_cache_key, body.params)
        cached_overlay_key = session_data.get("puzzle_overlay_cache_key")
        cached_overlay_id = session_data.get("puzzle_overlay_file_id")
        overlay_id: str
        if (
            cached_overlay_key == overlay_cache_key
            and isinstance(cached_overlay_id, str)
            and registry.resolve(cached_overlay_id) is not None
        ):
            overlay_id = cached_overlay_id
        else:
            overlay = render_puzzle_overlay(
                layout,
                labels_enabled=body.params.labels_enabled,
                visibility_mask=_puzzle_footprint(cache),
            )
            overlay_buffer = io.BytesIO()
            overlay.save(overlay_buffer, format="PNG")
            overlay_id = registry.register_bytes(body.session_id, overlay_buffer.getvalue(), "puzzle_overlay.png")
            store.put(body.session_id, "puzzle_overlay_cache_key", overlay_cache_key)
            store.put(body.session_id, "puzzle_overlay_file_id", overlay_id)
    except ROUTER_HANDLED_ERRORS as exc:
        _handle_core_error(exc, "Puzzle layout preview")

    warnings = list(layout.warnings)
    log.info(
        "Puzzle layout preview generated",
        extra={
            "event": "converter_puzzle_layout_preview_done",
            "session_id": body.session_id,
            "piece_count": layout.actual_piece_count,
            "grid_cols": layout.cols,
            "grid_rows": layout.rows,
            "derived_piece_width_mm": layout.derived_piece_width_mm,
            "derived_piece_height_mm": layout.derived_piece_height_mm,
            "warning_count": len(warnings),
            "labels_enabled": body.params.labels_enabled,
        },
    )
    return PuzzleLayoutPreviewResponse(
        status="ok",
        message="Puzzle layout preview generated",
        overlay_url=f"/api/files/{overlay_id}",
        piece_count=layout.actual_piece_count,
        grid_cols=layout.cols,
        grid_rows=layout.rows,
        derived_piece_width_mm=layout.derived_piece_width_mm,
        derived_piece_height_mm=layout.derived_piece_height_mm,
        warnings=warnings,
    )


@router.post("/generate-puzzle", response_model=PuzzleGenerateResponse)
async def generate_puzzle(
    body: _PuzzleGenerateBody,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
    pool: WorkerPoolManager = Depends(get_worker_pool),
) -> PuzzleGenerateResponse:
    """Generate per-piece puzzle models and assemble them into one 3MF.
    逐块生成拼图模型，并组装为一个 3MF 文件。

    Args:
        body: Wrapper containing session ID and puzzle generate params.
            (包含 Session ID 与拼图生成参数的请求体)
        store: Session store dependency. (SessionStore 依赖)
        registry: File registry dependency. (FileRegistry 依赖)
        pool: Worker-pool dependency. (WorkerPoolManager 依赖)

    Returns:
        PuzzleGenerateResponse: Download URL and resolved grid summary.
            (包含下载地址与网格摘要的响应)
    """

    request = body.params
    generate_params = request.params
    revision_bytes(generate_params.project_revision_file_id, registry)
    (
        session_data,
        committed_content_revision,
        committed_selection_revision,
    ) = _capture_generation_snapshot(
        store,
        body.session_id,
        requested_revision=generate_params.editor_content_revision,
        requested_selection_revision=generate_params.selection_revision,
        revision_mismatch_detail=(
            "Visible content changed before puzzle generation started "
            "(editor content revision mismatch); "
            "refresh the editor state and try again."
        ),
    )
    preview_cache_ref = session_data.get("preview_cache")
    material_selection = require_material_selection(generate_params, session_data)
    validate_export_device_selection(
        printer_id=generate_params.printer_id,
        slicer=generate_params.slicer,
        nozzle_size=generate_params.nozzle_size,
        device_profile_id=generate_params.device_profile_id,
        build_plate_id=generate_params.build_plate_id,
        custom_3mf_template_id=generate_params.custom_3mf_template_id,
    )
    metadata_target = select_metadata_target(
        slicer=generate_params.slicer,
        printer_id=generate_params.printer_id,
        nozzle_size=generate_params.nozzle_size,
        device_profile_id=generate_params.device_profile_id,
        build_plate_id=generate_params.build_plate_id,
    )
    if generate_params.enable_fridge_magnet:
        raise HTTPException(status_code=422, detail="Puzzle mode does not support fridge magnet cavities.")
    if generate_params.add_loop:
        raise HTTPException(status_code=422, detail="Puzzle mode does not support keychain loop generation.")
    if request.engrave_back_labels:
        raise HTTPException(
            status_code=422,
            detail="Puzzle back-label engraving is not implemented yet. Disable it before generating puzzle pieces.",
        )

    session_material_source = session_data.get("material_source", "lut")
    dynamic_material_settings = _resolve_session_dynamic_material_settings(
        session_data=session_data,
        request=generate_params,
        material_source=str(session_material_source or "lut"),
        # Puzzle vector requests are deliberately rasterized to high fidelity.
        native_svg_vector=False,
    )
    if (
        session_material_source == "material_archive"
        and dynamic_material_settings[0]
    ):
        _validate_unique_dynamic_material_selection(
            session_data.get("selected_materials") or []
        )

    cache_fields = {"matched_rgb", "mask_solid", "backing_mask", "preview_rgba"}
    if session_material_source == "material_archive":
        cache_fields.update({"quantized_image", "material_matrix"})
    cache = _require_puzzle_cache(session_data, fields=cache_fields)
    height_mode = generate_params.height_mode or "color"
    _validate_material_archive_relief_minimum_height(
        enable_relief=generate_params.enable_relief,
        material_source=str(session_material_source or "lut"),
        height_mode=height_mode,
        color_height_map=generate_params.color_height_map,
        heightmap_max_height=generate_params.heightmap_max_height,
        session_data=session_data,
        cache=cache,
        cache_ref=preview_cache_ref if isinstance(preview_cache_ref, dict) else None,
    )
    compensation_active = bool(
        generate_params.svg_hole_compensation_enabled
        or cache.get("svg_hole_compensation_enabled", False)
    )
    if session_material_source == "material_archive" or compensation_active:
        matches, _ = _preview_analysis_params_match(
            cache=cache,
            request=generate_params,
            core_modeling_mode=CoreModelingMode(generate_params.modeling_mode.value),
            session_material_source=str(session_material_source or "lut"),
            target_width_mm=generate_params.target_width_mm,
            # Recipe edits update the committed cache without rewriting the
            # original preview request kept on the session.
            preview_color_layers=cache.get("color_layers"),
            preview_layer_height_mm=cache.get("layer_height_mm"),
            compare_target_width=compensation_active,
        )
        if not matches:
            raise HTTPException(
                status_code=409,
                detail=(
                    "SVG hole compensation settings changed. Re-run preview before generating the puzzle."
                    if compensation_active else
                    "Puzzle image-analysis settings changed. Re-run preview before generating the puzzle."
                ),
            )
    material_puzzle_analysis: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray] | None = None
    material_recipe_overrides: list[dict[str, object]] | None = None
    if session_material_source == "material_archive":
        preview_layer_count = (
            dynamic_material_settings[2]
            if dynamic_material_settings[0]
            else None
        )
        material_puzzle_analysis = _require_material_puzzle_analysis(
            cache,
            layer_count=preview_layer_count,
        )
        material_recipe_overrides = _resolve_recipe_overrides(
            session_data,
            generate_params,
        )

    image_path: str | None = session_data.get("image_path")
    lut_path: str | None = session_data.get("lut_path")
    if not image_path or not os.path.exists(image_path):
        raise HTTPException(status_code=409, detail=SOURCE_IMAGE_UNAVAILABLE_DETAIL)
    if session_material_source == "material_archive":
        lut_path = "__material_archive__"
    elif not lut_path or not os.path.exists(lut_path):
        raise HTTPException(status_code=409, detail=LUT_DATA_UNAVAILABLE_DETAIL)

    try:
        layout, _layout_cache_key = _resolve_layout(
            session_data=session_data,
            cache=cache,
            request=request,
            store=store,
            session_id=body.session_id,
        )
        source_rgba = _get_source_rgba(cache)
        matched_rgb = cache.get("matched_rgb")
        if matched_rgb is None:
            raise ValueError("Preview cache missing matched_rgb for puzzle generation.")
    except ROUTER_HANDLED_ERRORS as exc:
        _handle_core_error(exc, "Puzzle generation setup")

    if (
        material_puzzle_analysis is not None
        and source_rgba.shape[:2] != material_puzzle_analysis[0].shape[:2]
    ):
        raise HTTPException(
            status_code=409,
            detail=_MATERIAL_PUZZLE_ANALYSIS_UNAVAILABLE_DETAIL,
        )

    free_color_set = _resolve_free_color_set(session_data, generate_params)
    relief_global_max_height = _resolve_relief_global_max_height(session_data, generate_params)

    core_modeling_mode = (
        CoreModelingMode.HIGH_FIDELITY
        if generate_params.modeling_mode == ModelingMode.VECTOR
        else CoreModelingMode(generate_params.modeling_mode.value)
    )
    heightmap_grayscale = session_data.get("heightmap_grayscale")

    warnings = list(layout.warnings)

    sid = body.session_id
    base_name = os.path.splitext(os.path.basename(image_path))[0] or "puzzle"
    selected_materials = (
        list(session_data.get("selected_materials") or [])
        if session_material_source == "material_archive"
        else []
    )
    # All piece inputs below come from the detached session/cache snapshot.
    # Reject a generation that became stale while layout and asset inputs were
    # being assembled, before the first worker is submitted.
    _assert_editor_snapshot_current(
        store,
        body.session_id,
        committed_content_revision,
        expected_selection_revision=committed_selection_revision,
    )
    piece_jobs: list[_PuzzlePieceJob] = []
    skipped_transparent_labels: list[str] = []

    log.info(
        "Puzzle generation started",
        extra={
            "event": "converter_puzzle_generate_init",
            "session_id": sid,
            "piece_count": layout.actual_piece_count,
            "grid_cols": layout.cols,
            "grid_rows": layout.rows,
            "max_workers": int(pool.max_workers),
            "material_source": session_material_source,
        },
    )

    for piece in layout.pieces:
        analysis_asset_kwargs: dict[str, np.ndarray] = {}
        if material_puzzle_analysis is not None:
            (
                _preview_matched_rgb,
                preview_mask_solid,
                preview_quantized_image,
                preview_material_matrix,
            ) = material_puzzle_analysis
            analysis_asset_kwargs = {
                "mask_solid": preview_mask_solid,
                "quantized_image": preview_quantized_image,
                "material_matrix": preview_material_matrix,
            }
        assets = _prepare_piece_worker_assets(
            source_rgba,
            matched_rgb,
            piece,
            backing_mask=cache.get("backing_mask"),
            **analysis_asset_kwargs,
        )
        has_backing = assets.backing_mask is not None and assets.backing_mask.any()
        if not has_backing and not np.any(assets.rgba[..., 3] >= 10):
            skipped_transparent_labels.append(piece.label)
            continue
        piece_prefix = f"puzzle_{piece.label}_"
        piece_image_path = _save_png_array(sid, store, assets.rgba, piece_prefix)
        piece_matched_path = _save_npy_array(sid, store, assets.matched_rgb, piece_prefix)
        piece_boundary_path = _save_json_payload(
            sid,
            store,
            assets.boundary_payload,
            piece_prefix,
        )

        worker_params: dict[str, Any] = {
            **build_common_generation_params(generate_params),
            # Each piece is temporary. Assign printheads once against the combined palette.
            "external_spool_material": None,
            "target_width_mm": piece.bbox_mm[2] - piece.bbox_mm[0],
            "add_loop": False,
            "loop_pos": None,
            "loop_angle": 0.0,
            "loop_offset_x": 0.0,
            "loop_offset_y": 0.0,
            "loop_position_preset": None,
            "modeling_mode": core_modeling_mode,
            # Piece PNGs already contain the confirmed SVG compensation.
            "svg_hole_compensation_enabled": False,
            "replacement_regions": None,
            "height_mode": height_mode,
            "free_color_set": free_color_set,
            "matched_rgb_path": piece_matched_path,
            "piece_boundary_geometry_path": piece_boundary_path,
            "disable_material_dilation": True,
            "center_on_bed": False,
            "relief_global_max_height": relief_global_max_height,
            "material_dynamic_layer_count_enabled": dynamic_material_settings[0],
            "material_min_layer_count": dynamic_material_settings[1],
            "material_max_layer_count": dynamic_material_settings[2],
            "material_delta_e00_tolerance": dynamic_material_settings[3],
        }
        if assets.backing_mask is not None:
            worker_params["backing_mask_path"] = _save_npy_array(sid, store, assets.backing_mask, piece_prefix)
        if material_puzzle_analysis is not None:
            if (
                assets.mask_solid is None
                or assets.quantized_image is None
                or assets.material_matrix is None
            ):
                raise RuntimeError("Material puzzle worker assets were not prepared.")
            worker_params.update(
                {
                    "mask_solid_path": _save_npy_array(
                        sid, store, assets.mask_solid, piece_prefix
                    ),
                    "quantized_image_path": _save_npy_array(
                        sid, store, assets.quantized_image, piece_prefix
                    ),
                    "material_matrix_path": _save_npy_array(
                        sid, store, assets.material_matrix, piece_prefix
                    ),
                    "reuse_preview_analysis": REQUIRED_PREVIEW_ANALYSIS_REUSE,
                }
            )
            if material_recipe_overrides:
                try:
                    # Committed overrides resolve ONLY to their applied-time
                    # snapshot when the session carries snapshot capability;
                    # a missing/invalid entry is an integrity failure and
                    # must not silently re-resolve from mutable live state.
                    # Live masks serve only legacy sessions without the
                    # snapshot key. _prepare_piece_recipe_override_masks keeps
                    # validating shape/source-grid compatibility per entry.
                    # 会话具备快照能力时，已提交覆盖只解析为 apply 时的快照；
                    # 缺失或校验失败属于完整性失败，绝不能从可变的实时选区
                    # 静默重解析。实时掩码仅服务没有快照键的旧会话。每个条目
                    # 的形状/栅格兼容性仍由
                    # _prepare_piece_recipe_override_masks 校验。
                    live_region_masks = session_data.get("selected_region_masks")
                    live_region_dict = (
                        dict(live_region_masks)
                        if isinstance(live_region_masks, dict)
                        else {}
                    )
                    applied_mask_snapshot = session_data.get(
                        RECIPE_OVERRIDE_APPLIED_MASKS_KEY
                    )
                    applied_snapshot_dict = (
                        applied_mask_snapshot
                        if isinstance(applied_mask_snapshot, dict)
                        else {}
                    )
                    has_snapshot_capability = (
                        RECIPE_OVERRIDE_APPLIED_MASKS_KEY in session_data
                    )
                    merged_region_masks: dict[str, np.ndarray] = {}
                    for override_item in material_recipe_overrides:
                        override_region_id = str(
                            override_item.get("region_id") or ""
                        ).strip()
                        if not override_region_id:
                            raise ValueError(
                                "material puzzle recipe override is missing region_id"
                            )
                        if override_region_id in merged_region_masks:
                            continue
                        if has_snapshot_capability:
                            snapshot_entry = unpack_applied_region_mask(
                                applied_snapshot_dict.get(override_region_id)
                            )
                            if snapshot_entry is None:
                                raise ValueError(
                                    f"material puzzle committed recipe override "
                                    f"mask is missing or invalid: {override_region_id}"
                                )
                            merged_region_masks[override_region_id] = snapshot_entry
                        elif isinstance(
                            live_region_dict.get(override_region_id), np.ndarray
                        ):
                            merged_region_masks[override_region_id] = live_region_dict[
                                override_region_id
                            ]
                    piece_override_masks = _prepare_piece_recipe_override_masks(
                        region_masks=merged_region_masks,
                        recipe_overrides=material_recipe_overrides,
                        piece=piece,
                        source_shape=material_puzzle_analysis[1].shape,
                        target_size=(assets.mask_solid.shape[1], assets.mask_solid.shape[0]),
                        piece_solid_mask=assets.mask_solid,
                    )
                except (TypeError, ValueError) as exc:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Material puzzle recipe-override analysis is incomplete. "
                            "Re-run preview before generating puzzle pieces."
                        ),
                    ) from exc
                worker_params["recipe_overrides"] = [
                    _serialize_recipe_override_for_worker(item)
                    for item in material_recipe_overrides
                ]
                if piece_override_masks:
                    worker_params["recipe_override_masks_path"] = (
                        _save_pickle_payload(
                            sid,
                            store,
                            piece_override_masks,
                            piece_prefix,
                        )
                    )
                elif np.any(
                    assets.material_matrix[np.asarray(assets.mask_solid, dtype=bool)]
                    >= len(selected_materials)
                ):
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            "Material puzzle virtual-material metadata is incomplete. "
                            "Re-run preview before generating puzzle pieces."
                        ),
                    )
            elif np.any(
                assets.material_matrix[np.asarray(assets.mask_solid, dtype=bool)]
                >= len(selected_materials)
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Material puzzle virtual-material metadata is unavailable. "
                        "Re-run preview before generating puzzle pieces."
                    ),
                )
        if session_material_source == "material_archive":
            worker_params["materials_dir"] = session_data.get("project_materials_dir")
            worker_params["material_source"] = "material_archive"
            worker_params["selected_materials"] = selected_materials
            # A committed manual recipe can extend the matrix beyond the
            # original preview request's fixed layer count.
            worker_params["material_layer_count"] = assets.material_matrix.shape[2]
            worker_params["material_layer_height_mm"] = cache.get("layer_height_mm")
            worker_params["material_grid_resolution"] = session_data.get(
                "material_grid_resolution"
            )
            requested_backing_index = (
                generate_params.material_backing_material_index
                if generate_params.material_backing_material_index is not None
                else session_data.get("material_backing_material_index")
            )
            worker_params["material_backing_material_index"] = _resolve_material_backing_index(
                selected_materials,
                requested_backing_index,
            )
        log.debug(
            "Puzzle hybrid boundary enabled",
            extra={
                "event": "converter_puzzle_hybrid_boundary_enabled",
                "session_id": sid,
                "piece_label": piece.label,
            },
        )

        if generate_params.enable_relief and height_mode == "heightmap":
            if heightmap_grayscale is None:
                raise HTTPException(status_code=409, detail="Heightmap missing. Upload heightmap before puzzle generation.")
            x0, y0, x1, y1 = assets.bbox_px
            piece_heightmap = np.array(heightmap_grayscale[y0:y1, x0:x1], copy=True)
            piece_heightmap = _resize_piece_array_nearest(
                piece_heightmap,
                _resolve_piece_worker_raster_size(piece),
            )
            piece_heightmap_path = _save_png_array(sid, store, piece_heightmap, piece_prefix)
            worker_params["heightmap_path"] = piece_heightmap_path

        # All worker arguments are paths, scalars, and per-piece dicts. Copy
        # the dict before enqueueing so a later session edit cannot mutate an
        # already-bound puzzle piece request.
        piece_jobs.append(
            _PuzzlePieceJob(
                piece=piece,
                image_path=piece_image_path,
                lut_path=lut_path,
                params=deepcopy(worker_params),
            )
        )

    if skipped_transparent_labels:
        warnings.append(
            f"Skipped {len(skipped_transparent_labels)} fully transparent puzzle pieces."
        )

    successful_entries: list[tuple[PuzzlePiece, str, bool, float]] = []
    errors: list[str] = []
    async for piece, result in _iter_puzzle_piece_results(
        piece_jobs, pool=pool, store=store, session_id=sid,
    ):
        try:
            if isinstance(result, BaseException):
                raise result
            threemf_path = result.get("threemf_path")
            if threemf_path and os.path.exists(threemf_path):
                x_mirrored = result.get("x_mirrored")
                mirror_span_mm = result.get("mirror_span_mm")
                if (
                    not isinstance(x_mirrored, bool)
                    or not isinstance(mirror_span_mm, (int, float))
                    or not np.isfinite(float(mirror_span_mm))
                    or float(mirror_span_mm) <= 0.0
                ):
                    errors.append(
                        f"{piece.label}: export transform metadata unavailable"
                    )
                else:
                    successful_entries.append(
                        (
                            piece,
                            threemf_path,
                            x_mirrored,
                            float(mirror_span_mm),
                        )
                    )
            else:
                status_msg = result.get("status_msg", "unknown")
                errors.append(f"{piece.label}: {status_msg}")
        except asyncio.TimeoutError:
            errors.append(f"{piece.label}: generation failed")
        except (DynamicMaterialCandidateError, DynamicMaterialSolverError) as exc:
            _handle_core_error(exc, "puzzle piece generation")
        except (WipeTowerLayoutError, NativeMaterialSelectionError, ExternalSpoolSelectionError, TemplateSlotCapacityError) as exc:
            raise to_http_exception(exc, "puzzle piece layout") from exc
        except ROUTER_HANDLED_ERRORS as exc:
            errors.append(f"{piece.label}: {exc}")

    if errors:
        log.error(
            "Puzzle piece generation failed",
            extra={
                "event": "converter_puzzle_generate_failed",
                "session_id": sid,
                "error_type": "puzzle_piece_generation_failed",
                "error_message": "; ".join(errors[:5]),
            },
        )
        raise HTTPException(
            status_code=500,
            detail=_PUZZLE_PIECE_GENERATION_FAILED_DETAIL,
        )

    if not successful_entries:
        raise HTTPException(
            status_code=422,
            detail="Puzzle generation produced no non-transparent pieces.",
        )

    _assert_editor_snapshot_current(
        store,
        body.session_id,
        committed_content_revision,
        expected_selection_revision=committed_selection_revision,
        allow_missing_session=True,
    )

    piece_sources = [
        PuzzlePiece3MFSource(
            label=piece.label,
            threemf_path=threemf_path,
            offset_x_mm=(
                layout.total_width_mm - piece.bbox_mm[0] - mirror_span_mm
                if x_mirrored
                else piece.bbox_mm[0]
            ),
            offset_y_mm=layout.total_height_mm - piece.bbox_mm[3],
        )
        for piece, threemf_path, x_mirrored, mirror_span_mm in successful_entries
    ]

    fd, combined_3mf_path = tempfile.mkstemp(prefix="puzzle_", suffix=".3mf", dir=TEMP_DIR)
    os.close(fd)
    combined_registered = False

    preview_colors = cache.get("preview_colors")
    slot_names = cache.get("slot_names")
    color_conf = cache.get("color_conf") or {}
    if preview_colors is None or slot_names is None:
        preview_colors = color_conf.get("preview")
        slot_names = color_conf.get("slots")
    slot_index_by_name = color_conf.get("map") or {
        name: index for index, name in enumerate(slot_names or [])
    }

    overview_buffer = io.BytesIO()
    render_assembly_overview(
        source_rgba,
        layout,
        labels_enabled=request.labels_enabled,
        visibility_mask=cache.get("backing_mask"),
    ).save(overview_buffer, format="PNG")
    overview_png_bytes = overview_buffer.getvalue()

    try:
        piece_slots = [
            tuple(
                WriterMaterialSlot(**slot)
                for slot in _batch_extract_slots_from_3mf(
                    piece_source.threemf_path,
                    target=metadata_target,
                )
            )
            for piece_source in piece_sources
        ]
        assemble_puzzle_3mf(
            piece_sources=piece_sources,
            piece_slots=piece_slots,
            output_path=combined_3mf_path,
            slot_names=slot_names,
            preview_colors=preview_colors,
            slot_index_by_name=slot_index_by_name,
            printer_id=generate_params.printer_id,
            nozzle_size=generate_params.nozzle_size,
            device_profile_id=generate_params.device_profile_id,
            build_plate_id=generate_params.build_plate_id,
            overview_png_bytes=overview_png_bytes,
            metadata_target=metadata_target,
            material_types={material["name"]: material["material_type"]
                            for material in material_selection["materials"]},
            external_spool_material=generate_params.external_spool_material,
            native_filament_profiles={material["name"]: material["selected_profile_name"]
                                      for material in material_selection["materials"]
                                      if material["selected_profile_name"]},
            enable_wipe_tower_auto_placement=(
                generate_params.enable_wipe_tower_auto_placement
            ),
        )
        _assert_editor_snapshot_current(
            store,
            body.session_id,
            committed_content_revision,
            expected_selection_revision=committed_selection_revision,
            allow_missing_session=True,
        )
        for warning_code in read_wipe_tower_placement_warnings(
            combined_3mf_path
        ):
            if warning_code not in warnings:
                warnings.append(warning_code)
        embed_generated_project(combined_3mf_path, generate_params.project_revision_file_id, registry)
        download_id = registry.register_path(
            str(uuid.uuid4()),
            combined_3mf_path,
            filename=f"{base_name}_puzzle.3mf",
            ttl_seconds=BATCH_DOWNLOAD_TTL_SECONDS,
        )
        combined_registered = True
    except (WipeTowerLayoutError, NativeMaterialSelectionError, ExternalSpoolSelectionError, TemplateSlotCapacityError) as exc:
        raise to_http_exception(exc, "puzzle 3MF layout") from exc
    except ROUTER_HANDLED_ERRORS as exc:
        log.error(
            "Puzzle 3MF assembly failed",
            extra={
                "event": "converter_puzzle_assembly_failed",
                "session_id": sid,
                "error_type": type(exc).__name__,
                "error_message": _PUZZLE_ASSEMBLY_FAILED_DETAIL,
            },
        )
        raise HTTPException(status_code=500, detail=_PUZZLE_ASSEMBLY_FAILED_DETAIL)
    finally:
        if not combined_registered:
            _remove_temp_path(combined_3mf_path)

    log.info(
        "Puzzle 3MF generated",
        extra={
            "event": "converter_puzzle_generate_done",
            "session_id": sid,
            "piece_count": len(successful_entries),
            "grid_cols": layout.cols,
            "grid_rows": layout.rows,
            "warning_count": len(warnings),
            "skipped_transparent_count": len(skipped_transparent_labels),
            "download_id": download_id,
        },
    )
    return PuzzleGenerateResponse(
        status="ok",
        message=f"Generated {len(successful_entries)} puzzle pieces into a single 3MF",
        download_url=f"/api/files/{download_id}",
        threemf_disk_path=None,
        piece_count=len(successful_entries),
        grid_cols=layout.cols,
        grid_rows=layout.rows,
        warnings=warnings,
        editor_content_revision=committed_content_revision,
        selection_revision=committed_selection_revision,
    )
