"""Converter router generate module."""

from __future__ import annotations

from typing import Annotated, Literal, NamedTuple
from api.project_resources import stage_project_resources, discard_project_resources

import asyncio
from concurrent.futures.process import BrokenProcessPool
from contextlib import suppress
from copy import deepcopy
import json
import math
import os
import pickle
import re
import shutil
import tempfile
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image
from pydantic import BaseModel, StrictBool, TypeAdapter, ValidationError

from api.project_export import embed_generated_project, revision_bytes
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.editor_commit import get_editor_content_revision
from api.errors import to_http_exception
from api.export_device_validation import validate_export_device_selection
from api.file_bridge import ensure_png_tempfile
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import (
    get_preview_cache_field_path,
    get_preview_cache_metadata,
    hydrate_preview_cache,
    is_preview_cache_artifact_ref,
)
from api.replacement_history import replacement_history_lock
from api.schemas.converter import (
    CoatingMaterialReference,
    ColorMode,
    ConvertGenerateRequest,
    LargeFormatConvertGenerateRequest,
    LargeFormatGenerateRequest,
    ModelingMode,
    StructureMode,
)
from api.schemas.lut import LutSourceSelection
from api.schemas.responses import (
    BatchItemResult,
    BatchPreviewItem,
    BatchResponse,
    GenerateResponse,
    LargeFormatGenerateResponse,
    WarningEntry,
)
from api.selection_state import (
    get_selection_revision,
    resolve_recipe_override_masks,
    selection_lock,
)
from api.session_store import SessionStore
from api.structured_logging import get_logger
from api.worker_pool import WorkerPoolManager
from api.workers.converter_workers import (
    LargeFormatCachedAnalysisError,
    worker_batch_convert_item,
    worker_generate_large_format_svg_native,
    worker_generate_model,
    worker_generate_model_surface_overlay,
)
from core.batch_layout import LayoutResult, XYBBox, layout_shelf_by_row
from core.errors import (
    CachedPreviewAnalysisError, ExternalSpoolSelectionError, NativeMaterialSelectionError, TemplateSlotCapacityError, WipeTowerLayoutError,
)
from .export_materials import require_material_selection
from core.model_surface.types import ModelSurfaceError
from core.naming import generate_preserved_upload_3mf_filename
from core.preview_analysis_cache import REQUIRED_PREVIEW_ANALYSIS_REUSE
from core.wipe_tower_placement import WIPE_TOWER_MANUAL_WARNING_CODE
from utils.merged_bambu_3mf_writer import (
    MergedBambu3MFWriter,
    MergedItem,
    MaterialSlot as WriterMaterialSlot,
)
from utils.fatcat_metadata import MetadataTarget, select_metadata_target
from config import (
    PrinterConfig,
    SVG_PIXELS_PER_MM_DEFAULT,
    SVG_PIXELS_PER_MM_MAX,
    SVG_PIXELS_PER_MM_MIN,
    TEMP_DIR,
    ModelingMode as CoreModelingMode,
    normalize_svg_pixels_per_mm,
)
from core.pipeline.processing_ops.svg_rasterizer import (
    _parse_svg_length_to_px,
    rasterize_svg,
)
from core.recipe_order import convert_recipe_between_orders
from core.vector_large_format import (
    SVG_LARGE_FORMAT_FALLBACK_NATIVE_FAILURE,
    SVG_LARGE_FORMAT_FALLBACK_UNSUPPORTED_FEATURE,
    SVG_LARGE_FORMAT_GENERATE_FALLBACK_WARNING,
    SVG_LARGE_FORMAT_NATIVE_FAILURE_FALLBACK_WARNING,
    format_large_format_tile_label,
    inspect_svg_large_format_support,
    normalize_large_format_source_basename,
    resolve_large_format_axis_count,
    resolve_large_format_grid_shape,
)
from core.material_lut_synthesis import infer_material_archive_base_channel_idx
from core.material_dynamic_solver import (
    DynamicMaterialCandidateError,
    DynamicMaterialSolverError,
)
from core.single_stage import record_material_usage
from utils.bambu_3mf_writer import read_wipe_tower_placement_warnings
from utils.lut_manager import LUTManager
from .generation_params import build_generation_worker_params
from api.recipe_override_resolution import (
    _backfill_recipe_override_virtual_materials,
    _native_palette_length_for_virtual_recovery,
    _normalize_recipe_overrides,
    _recover_virtual_materials_from_preview_cache,
    _rgba_to_hex,
    resolve_recipe_overrides as _resolve_recipe_overrides,
)


def _assert_editor_snapshot_current(
    store: SessionStore,
    session_id: str,
    expected_revision: int,
    *,
    expected_selection_revision: int | None = None,
    allow_missing_session: bool = False,
) -> None:
    """Reject a generation snapshot that changed while it was assembled.

    在生成输入快照组装期间若编辑版本发生变化，拒绝提交该混合快照。
    """
    with replacement_history_lock(session_id):
        with selection_lock(session_id):
            latest_session = store.get(session_id)
            if latest_session is None:
                if allow_missing_session:
                    return
                raise HTTPException(status_code=404, detail="Session not found")
            actual_revision = get_editor_content_revision(latest_session)
            if actual_revision != expected_revision:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Editor content changed while the generation snapshot was "
                        "being assembled; refresh the editor state and try again."
                    ),
                )
            if (
                expected_selection_revision is not None
                and get_selection_revision(latest_session)
                != expected_selection_revision
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Editor selection changed while the generation snapshot was "
                        "being assembled; refresh the selection and try again."
                    ),
                )


def _snapshot_generation_session(session_data: dict) -> dict:
    """Deep-copy the session inputs used by a generation request.

    复制生成请求使用的会话输入，确保 worker 只读取本次生成绑定的快照。

    Preview-cache artifact references remain cheap path metadata; legacy
    in-memory preview arrays are copied here so a later edit cannot mutate the
    arrays while a standard, large-format, or puzzle request is assembling its
    worker inputs.
    """
    try:
        return deepcopy(session_data)
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Generation inputs could not be snapshotted safely; "
                "refresh preview and try again."
            ),
        ) from exc


def _capture_generation_snapshot(
    store: SessionStore,
    session_id: str,
    *,
    requested_revision: int | None = None,
    requested_selection_revision: int | None = None,
    revision_mismatch_detail: str,
) -> tuple[dict, int, int]:
    """Capture a complete generation snapshot under the editor locks.

    在编辑锁内同时校验作品版本并复制生成输入，避免校验后到复制前
    发生编辑，导致 worker 看到半新半旧的会话状态。
    """
    # Content routes use replacement_history_lock; selection mutations use
    # selection_lock. Acquire them in this one order for the short snapshot
    # boundary, then release both before any expensive worker work begins.
    with replacement_history_lock(session_id):
        with selection_lock(session_id):
            live_session_data = _require_session(store, session_id)
            committed_revision = get_editor_content_revision(live_session_data)
            selection_revision = get_selection_revision(live_session_data)
            if (
                requested_revision is not None
                and int(requested_revision) != committed_revision
            ):
                raise HTTPException(
                    status_code=409,
                    detail=revision_mismatch_detail,
                )
            if (
                requested_selection_revision is not None
                and int(requested_selection_revision) != selection_revision
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Editor selection changed before generation started; "
                        "refresh the selection and try again."
                    ),
                )
            return (
                _snapshot_generation_session(live_session_data),
                committed_revision,
                selection_revision,
            )


from .common import (
    BATCH_DOWNLOAD_TTL_SECONDS,
    LUT_DATA_UNAVAILABLE_DETAIL,
    LUT_SOURCE_SELECTION_INVALID_DETAIL,
    PREVIEW_CACHE_INVALID_DETAIL,
    PREVIEW_CACHE_UNAVAILABLE_DETAIL,
    PREVIEW_COLOR_PALETTE_UNAVAILABLE_DETAIL,
    RECIPE_OVERRIDE_APPLIED_MASKS_KEY,
    ROUTER_HANDLED_ERRORS,
    SOURCE_IMAGE_UNAVAILABLE_DETAIL,
    _ensure_material_matrix_signed_capacity,
    _public_pipeline_validation_detail,
    public_model_surface_error_detail,
    _require_session,
    _resolve_session_dynamic_material_settings,
    _resolve_material_backing_index,
    _handle_core_error,
    _validate_dynamic_material_settings,
    _validate_unique_dynamic_material_selection,
    _validate_material_source,
    _validate_svg_hole_compensation,
    _validate_material_archive_relief_minimum_height,
)

router = APIRouter()
log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Batch merge constants (not exposed via API / UI / settings)
# ---------------------------------------------------------------------------
_BATCH_PREVIEW_BROWSER_SAFE_LIMIT: int = 96
BATCH_PLATE_OVERFLOW_FALLBACK_MESSAGE: str = (
    "部分模型可能超出热床范围，请在切片软件中调整 / "
    "Some models may extend beyond the print bed; please adjust them in the slicer."
)
BATCH_PREVIEW_LIMIT_FALLBACK_MESSAGE: str = (
    "批量 3MF 已包含全部成功模型；3D 预览会按当前热床尺寸自动显示可容纳"
    "的前若干个模型 / The batch 3MF includes every successful model; the "
    "3D preview automatically shows the first models that fit on the current "
    "print bed."
)
BATCH_PREVIEW_UNAVAILABLE_MESSAGE: str = (
    "批量 3MF 下载已生成；网页 3D 预览暂不可用 / The batch 3MF download "
    "is ready; the browser 3D preview is temporarily unavailable."
)
BATCH_WIPE_TOWER_MANUAL_ADJUSTMENT_MESSAGE: str = (
    "文件已继续生成，但当前模型和擦料塔无法在所选热床上同时安全摆放。"
    "请务必在切片软件中手动移动模型，或调整擦料塔的宽度和位置后再打印。"
)
LARGE_FORMAT_GENERATION_FAILED_DETAIL: str = (
    "Large-format generation failed. Try again or check the server log for details."
)
LARGE_FORMAT_RECIPE_OVERRIDE_LOAD_FAILED_DETAIL: str = (
    "Large-format recipe override data could not be loaded. Re-run preview and try again."
)
LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL: str = (
    "Large-format cached preview data is unavailable or invalid. "
    "Re-run preview and try again."
)
STANDARD_CACHED_ANALYSIS_INVALID_DETAIL: str = (
    "Cached preview data is unavailable or invalid. "
    "Re-run preview and try again."
)
BATCH_ITEM_FAILED_DETAIL: str = (
    "This file could not be converted. Re-upload it or check the server log for details."
)
BATCH_GENERATION_FAILED_DETAIL: str = (
    "Batch generation worker became unavailable. Try the batch again."
)
MODEL_GENERATION_FAILED_DETAIL: str = (
    "3MF generation failed. Re-run preview and try generating the model again."
)


MODEL_SURFACE_SOURCE_UNAVAILABLE_DETAIL: str = (
    "Surface model is unavailable. Re-upload the model, run preview, and try again."
)
MODEL_SURFACE_CONFIG_UNAVAILABLE_DETAIL: str = (
    "Surface overlay configuration is unavailable. Select a model surface, run preview, and try again."
)
LARGE_FORMAT_MODEL_SURFACE_UNSUPPORTED_DETAIL: str = (
    "Large-format tiled generation does not support model surface overlay. "
    "Turn off large-format mode or model surface overlay, then generate again."
)
_MODEL_SURFACE_DEFAULT_POCKET_DEPTH_MM: float = 0.4
_SELECT_ALL_COLOR_REGION_PREFIX = "__select_all_color__:"


def _model_generation_failure_exception(
    status_msg: object,
    *,
    source_is_user_upload: bool = False,
    modeling_mode: object = None,
    source_path: object = None,
    surface_overlay: bool = False,
) -> HTTPException:
    """Map known public validation failures without exposing internal errors.
    映射已知且可公开的校验错误，同时避免泄露内部错误信息。
    """
    public_detail = _public_pipeline_validation_detail(
        status_msg,
        source_is_user_upload=source_is_user_upload,
        modeling_mode=modeling_mode,
        source_path=source_path,
        surface_overlay=surface_overlay,
    )
    if public_detail is not None:
        return HTTPException(
            status_code=422,
            detail=public_detail,
        )
    return HTTPException(status_code=500, detail=MODEL_GENERATION_FAILED_DETAIL)


class _GenerateBody(BaseModel):
    """Wrapper combining session_id with generate parameters."""

    session_id: str
    params: ConvertGenerateRequest
    preserve_upload_filename_for_3mf: StrictBool = False


def _should_use_model_surface_overlay(session_data: dict) -> bool:
    """Return whether this generate request should use model-surface assembly."""

    return bool(session_data.get("surface_overlay_enabled"))


def _prepare_model_surface_overlay_worker_params(
    session_data: dict,
    params: dict,
) -> dict:
    """Build picklable worker params for model-surface final generation."""

    model_path = session_data.get("surface_model_path")
    if not isinstance(model_path, str) or not model_path or not os.path.exists(model_path):
        raise HTTPException(status_code=409, detail=MODEL_SURFACE_SOURCE_UNAVAILABLE_DETAIL)

    footprint = session_data.get("surface_footprint")
    if not isinstance(footprint, dict):
        raise HTTPException(status_code=409, detail=MODEL_SURFACE_CONFIG_UNAVAILABLE_DETAIL)

    worker_params = dict(params)
    worker_params["surface_model_path"] = model_path
    worker_params["surface_footprint"] = footprint
    model_transform = session_data.get("surface_model_transform")
    if isinstance(model_transform, dict):
        worker_params["surface_model_transform"] = model_transform
    try:
        pocket_depth_mm = float(
            session_data.get(
                "surface_pocket_depth_mm",
                _MODEL_SURFACE_DEFAULT_POCKET_DEPTH_MM,
            )
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail=MODEL_SURFACE_CONFIG_UNAVAILABLE_DETAIL,
        ) from exc
    if pocket_depth_mm <= 0.0:
        raise HTTPException(status_code=409, detail=MODEL_SURFACE_CONFIG_UNAVAILABLE_DETAIL)
    worker_params["surface_pocket_depth_mm"] = pocket_depth_mm
    worker_params["converter_params"] = _prepare_model_surface_converter_params(
        session_data,
        params,
    )
    return worker_params


def _prepare_model_surface_converter_params(
    session_data: dict,
    params: dict,
) -> dict:
    """Prepare converter params that build the printable surface artwork only."""

    converter_params = dict(params)
    # A surface overlay has exactly one viewing side. Reusing the regular
    # double-sided voxel layout would add a second colour stack behind the
    # uploaded model and make it reappear in later slicer layers.
    converter_params["structure_mode"] = StructureMode.SINGLE_SIDED.value
    target_width_mm = session_data.get("surface_target_width_mm")
    if target_width_mm is not None:
        try:
            converter_params["target_width_mm"] = float(target_width_mm)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail=MODEL_SURFACE_CONFIG_UNAVAILABLE_DETAIL,
            ) from exc

    # Surface overlay uses the uploaded model as the final body. Disable
    # feature add-ons that would append standalone geometry to the artwork
    # before it is embedded into the selected face.
    converter_params["add_loop"] = False
    converter_params["loop_pos"] = None
    converter_params["enable_fridge_magnet"] = False
    converter_params["fridge_magnets"] = []
    converter_params["enable_relief"] = False
    converter_params["enable_cloisonne"] = False
    converter_params["enable_coating"] = False
    converter_params["enable_base_layer_height_modifier"] = False
    converter_params["backing_infill_density_percent"] = (
        PrinterConfig.BACKING_INFILL_DENSITY_DEFAULT_PERCENT
    )
    return converter_params


def _remove_temp_path(path: str | None) -> None:
    """Best-effort delete for route-owned temporary files."""
    if not path:
        return
    try:
        os.unlink(path)
    except OSError:
        pass


def _record_material_archive_usage_safe(
    *,
    selected_materials: object,
    color_mode: object,
    request_id: str | None = None,
) -> None:
    """Best-effort: record per-material usage for a successful build.
    尽力记录一次生成中各耗材的使用次数。

    Failures here are intentionally swallowed and logged at WARNING — usage
    tracking is auxiliary diagnostics and must never break a successful
    generation response.
    本函数失败会被吞掉并记录 WARNING 日志；usage 仅是辅助诊断，不能影响生成返回。

    Args:
        selected_materials: Iterable of material directory_name strings used
            in the build. (本次生成使用的耗材 directory_name 列表)
        color_mode: Color mode the build was generated under. (颜色模式)
        request_id: Optional request id for log correlation. (用于日志关联的请求 id)
    """
    if not selected_materials:
        return
    if not isinstance(selected_materials, (list, tuple)):
        return
    directory_names = [str(name) for name in selected_materials if isinstance(name, str) and name.strip()]
    if not directory_names:
        return
    try:
        record_material_usage(directory_names=directory_names, color_mode=color_mode)
    except (OSError, ValueError, TypeError) as exc:
        log.warning(
            "Failed to record material usage stats",
            extra={
                "event": "material_usage_record_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "request_id": request_id,
            },
        )


def _remove_temp_paths(paths: list[str] | None) -> None:
    if not paths:
        return
    for path in paths:
        _remove_temp_path(path)


def _require_preview_cache_for_generate(
    session_data: dict,
) -> tuple[dict[str, object], dict[str, object] | None]:
    """Return metadata view and optional artifact ref for generate routes.

    返回生成路由使用的 metadata 视图和可选 artifact 引用。
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
    if is_preview_cache_artifact_ref(cache):
        return get_preview_cache_metadata(cache), cache
    return cache, None


def _resolve_registered_preview_glb(
    *,
    cache: dict,
    sid: str,
    registry: FileRegistry,
) -> tuple[str, str] | None:
    """Return the current session-owned preview GLB URL and disk path."""

    glb_url = cache.get("glb_url")
    if not isinstance(glb_url, str) or not glb_url.strip():
        return None
    url_path = glb_url.split("?", 1)[0].rstrip("/")
    file_id = url_path.rsplit("/", 1)[-1] if "/api/files/" in url_path else ""
    if not file_id:
        return None

    entry = registry.get_entry(file_id)
    if entry is None or entry.get("session_id") != sid:
        return None

    resolved = registry.resolve(file_id)
    if resolved is None:
        return None
    preview_glb_path, _filename = resolved
    if not os.path.isfile(preview_glb_path):
        return None
    return glb_url, preview_glb_path


def _resolve_reusable_preview_glb_path(
    *,
    cache: dict,
    request: ConvertGenerateRequest,
    sid: str,
    registry: FileRegistry,
    reuse_preview_glb: bool,
) -> str | None:
    """Return a ready preview GLB path when generate can reuse that asset.

    仅在预览参数已确认可复用、GLB 文件仍由同一 session 注册且高精度
    预览开关一致时，才把现有预览 GLB 传给 worker。
    """
    if not reuse_preview_glb:
        return None

    preview_high_precision = bool(cache.get("high_precision_3d_preview", False))
    if preview_high_precision is not bool(request.high_precision_3d_preview):
        return None

    resolved = _resolve_registered_preview_glb(
        cache=cache,
        sid=sid,
        registry=registry,
    )
    return resolved[1] if resolved is not None else None


def _paths_refer_to_same_file(left: str | None, right: str | None) -> bool:
    """Return whether two non-empty paths identify the same filesystem path."""

    if not left or not right:
        return False
    try:
        return os.path.samefile(left, right)
    except (FileNotFoundError, OSError, ValueError, TypeError):
        try:
            return os.path.realpath(left) == os.path.realpath(right)
        except (OSError, ValueError, TypeError):
            return False


def _cache_field_path_or_tempfile(
    *,
    cache: dict,
    cache_ref: dict | None,
    field_name: str,
    sid: str,
    store: SessionStore,
) -> str | None:
    """Return an existing artifact field path or serialize a legacy array.

    返回已有 artifact 字段路径；旧缓存数组则序列化为临时文件。
    """
    if cache_ref is not None:
        field_path = get_preview_cache_field_path(cache_ref, field_name)
        if field_path:
            return field_path

    value = cache.get(field_name)
    if value is None:
        return None
    array = np.asarray(value)
    fd, temp_path = tempfile.mkstemp(suffix=".npy", dir=TEMP_DIR)
    os.close(fd)
    np.save(temp_path, array)
    store.register_temp_file(sid, temp_path)
    return temp_path


def _close_numpy_load_result(loaded: object) -> None:
    """Close resources held by ``np.load(..., mmap_mode='r')``."""

    close = getattr(loaded, "close", None)
    if callable(close):
        close()
    mmap_obj = getattr(loaded, "_mmap", None)
    if mmap_obj is not None and not getattr(mmap_obj, "closed", False):
        mmap_obj.close()


def _load_large_format_cache_array_spec(path: str) -> tuple[tuple[int, ...], np.dtype]:
    """Read only shape/dtype metadata from one private preview artifact."""

    loaded = np.load(path, mmap_mode="r", allow_pickle=False)
    try:
        if not isinstance(loaded, np.ndarray):
            raise ValueError("preview cache field is not a NumPy array")
        return tuple(int(size) for size in loaded.shape), loaded.dtype
    finally:
        _close_numpy_load_result(loaded)


def _cache_grid_dimension_matches(value: object, expected: int) -> bool:
    """Return whether required cache metadata is exactly one integer size."""

    if value is None:
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return numeric.is_integer() and int(numeric) == expected


def _resolve_validated_large_format_cached_analysis_paths(
    *,
    cache: dict,
    cache_ref: dict | None,
    sid: str,
    store: SessionStore,
    require_quantized_image: bool = False,
    dynamic_max_layer_count: int | None = None,
    invalid_detail: str = LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL,
) -> tuple[str, str, str, str | None]:
    """Resolve and validate the spatial preview-cache arrays together.

    一次性解析并严格校验空间编辑所需的三个预览缓存数组；动态 P03
    复用时还会校验量化 RGB，避免把半套缓存转发给 worker。
    """

    try:
        matched_rgb_path = _cache_field_path_or_tempfile(
            cache=cache,
            cache_ref=cache_ref,
            field_name="matched_rgb",
            sid=sid,
            store=store,
        )
        mask_solid_path = _cache_field_path_or_tempfile(
            cache=cache,
            cache_ref=cache_ref,
            field_name="mask_solid",
            sid=sid,
            store=store,
        )
        material_matrix_path = _cache_field_path_or_tempfile(
            cache=cache,
            cache_ref=cache_ref,
            field_name="material_matrix",
            sid=sid,
            store=store,
        )
        quantized_image_path: str | None = None
        if require_quantized_image:
            quantized_image_path = _cache_field_path_or_tempfile(
                cache=cache,
                cache_ref=cache_ref,
                field_name="quantized_image",
                sid=sid,
                store=store,
            )
        if not matched_rgb_path or not mask_solid_path or not material_matrix_path:
            raise ValueError("preview cache analysis fields are incomplete")
        if require_quantized_image and not quantized_image_path:
            raise ValueError("preview cache quantized_image is missing")

        matched_shape, matched_dtype = _load_large_format_cache_array_spec(
            matched_rgb_path
        )
        mask_shape, mask_dtype = _load_large_format_cache_array_spec(mask_solid_path)
        material_shape, material_dtype = _load_large_format_cache_array_spec(
            material_matrix_path
        )
        quantized_shape: tuple[int, ...] | None = None
        quantized_dtype: np.dtype | None = None
        if quantized_image_path is not None:
            quantized_shape, quantized_dtype = _load_large_format_cache_array_spec(
                quantized_image_path
            )

        if len(matched_shape) != 3 or matched_shape[2] != 3:
            raise ValueError("matched_rgb must have shape (H, W, 3)")
        if matched_dtype != np.dtype(np.uint8):
            raise ValueError("matched_rgb must use uint8")
        if len(mask_shape) != 2 or mask_dtype != np.dtype(np.bool_):
            raise ValueError("mask_solid must have shape (H, W) and bool dtype")
        if (
            len(material_shape) != 3
            or material_shape[2] <= 0
            or not np.issubdtype(material_dtype, np.integer)
        ):
            raise ValueError(
                "material_matrix must have shape (H, W, N) and integer dtype"
            )
        if (
            quantized_shape is not None
            and (
                len(quantized_shape) != 3
                or quantized_shape[2] != 3
                or quantized_dtype != np.dtype(np.uint8)
            )
        ):
            raise ValueError(
                "quantized_image must have shape (H, W, 3) and uint8 dtype"
            )
        if dynamic_max_layer_count is not None and material_dtype != np.dtype(np.int32):
            raise ValueError("dynamic material_matrix must use int32")
        if (
            dynamic_max_layer_count is not None
            and material_shape[2] != dynamic_max_layer_count
        ):
            raise ValueError(
                "dynamic material_matrix depth does not match maximum layer count"
            )

        spatial_shape = matched_shape[:2]
        if mask_shape != spatial_shape or material_shape[:2] != spatial_shape:
            raise ValueError("preview cache analysis fields use different grids")
        if (
            quantized_shape is not None
            and quantized_shape[:2] != spatial_shape
        ):
            raise ValueError("preview cache quantized_image uses a different grid")
        target_h, target_w = spatial_shape
        if not _cache_grid_dimension_matches(cache.get("target_h"), target_h):
            raise ValueError("preview cache target_h does not match array grid")
        if not _cache_grid_dimension_matches(cache.get("target_w"), target_w):
            raise ValueError("preview cache target_w does not match array grid")
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        EOFError,
        zipfile.BadZipFile,
    ) as exc:
        raise HTTPException(
            status_code=409,
            detail=invalid_detail,
        ) from exc

    return (
        matched_rgb_path,
        mask_solid_path,
        material_matrix_path,
        quantized_image_path,
    )


def _resolve_validated_edit_projection_paths(
    *,
    cache: dict,
    cache_ref: dict | None,
    sid: str,
    store: SessionStore,
    matched_rgb_path: str,
    material_matrix_path: str,
    invalid_detail: str,
) -> tuple[str, str, tuple[int, int]]:
    """Resolve pristine baselines needed to replay edits after resizing.

    尺寸变化时，当前缓存值本身不足以区分“用户编辑”和“旧尺寸分析”。
    因此必须同时拥有同一 session 的 pristine RGB / 材料矩阵，缺失或网格
    不一致时 fail closed，绝不把整张旧模型状态串到新尺寸。
    """

    try:
        original_matched_rgb_path = _cache_field_path_or_tempfile(
            cache=cache,
            cache_ref=cache_ref,
            field_name="original_matched_rgb",
            sid=sid,
            store=store,
        )
        original_material_matrix_path = _cache_field_path_or_tempfile(
            cache=cache,
            cache_ref=cache_ref,
            field_name="original_material_matrix",
            sid=sid,
            store=store,
        )
        if not original_matched_rgb_path or not original_material_matrix_path:
            raise ValueError("pristine preview edit artifacts are incomplete")

        matched_shape, matched_dtype = _load_large_format_cache_array_spec(
            matched_rgb_path
        )
        material_shape, material_dtype = _load_large_format_cache_array_spec(
            material_matrix_path
        )
        original_rgb_shape, original_rgb_dtype = (
            _load_large_format_cache_array_spec(original_matched_rgb_path)
        )
        original_material_shape, original_material_dtype = (
            _load_large_format_cache_array_spec(original_material_matrix_path)
        )
        if (
            len(matched_shape) != 3
            or matched_shape[2] != 3
            or matched_dtype != np.dtype(np.uint8)
            or original_rgb_shape != matched_shape
            or original_rgb_dtype != np.dtype(np.uint8)
        ):
            raise ValueError("pristine RGB does not match the edited RGB grid")
        source_shape = (int(matched_shape[0]), int(matched_shape[1]))
        if (
            len(material_shape) != 3
            or material_shape[:2] != source_shape
            or material_shape[2] <= 0
            or not np.issubdtype(material_dtype, np.integer)
            or len(original_material_shape) != 3
            or original_material_shape[:2] != source_shape
            or original_material_shape[2] <= 0
            or not np.issubdtype(original_material_dtype, np.integer)
        ):
            raise ValueError(
                "pristine material matrix does not match the edited grid"
            )
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        EOFError,
        zipfile.BadZipFile,
    ) as exc:
        raise HTTPException(status_code=409, detail=invalid_detail) from exc

    return (
        original_matched_rgb_path,
        original_material_matrix_path,
        source_shape,
    )


def _build_edit_projection_metadata(
    *,
    cache: dict,
    source_shape: tuple[int, int] | None,
    mode: str,
    invalid_detail: str,
) -> dict[str, object]:
    """Build validated, worker-safe normalized edit-grid metadata."""

    try:
        if source_shape is None:
            source_shape = (
                int(cache["target_h"]),
                int(cache["target_w"]),
            )
        source_h, source_w = (int(source_shape[0]), int(source_shape[1]))
    except (KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
        raise HTTPException(status_code=409, detail=invalid_detail) from exc
    if (
        source_h <= 0
        or source_w <= 0
        or mode not in {"delta", "recipe_masks"}
    ):
        raise HTTPException(status_code=409, detail=invalid_detail)
    return {
        "mode": mode,
        "source_shape": [source_h, source_w],
    }


def _require_loadable_material_archive_cache_path(
    path: str | None,
    field_name: str,
) -> str:
    if path is None:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Preview cache missing {field_name}. Re-run preview before "
                "generating material-archive models."
            ),
        )

    try:
        loaded = np.load(path, mmap_mode="r", allow_pickle=False)
        try:
            if not isinstance(loaded, np.ndarray):
                raise ValueError(f"{field_name} artifact is not a numpy array")
            _ = loaded.shape
        finally:
            close = getattr(loaded, "close", None)
            if callable(close):
                close()
            mmap_obj = getattr(loaded, "_mmap", None)
            if mmap_obj is not None:
                mmap_obj.close()
    except (OSError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Preview cache {field_name} artifact is unavailable or "
                "unreadable. Re-run preview before generating "
                "material-archive models."
            ),
        ) from exc

    return path


_MISSING = object()
_PREVIEW_ANALYSIS_ARRAY_FIELDS = {"matched_rgb", "mask_solid", "material_matrix"}


def _cache_has_preview_analysis_fields(
    cache: dict,
    cache_ref: dict | None,
) -> bool:
    """Return whether cache can provide the arrays needed to skip S02."""

    for field_name in _PREVIEW_ANALYSIS_ARRAY_FIELDS:
        if cache_ref is not None:
            path = get_preview_cache_field_path(cache_ref, field_name)
            if not path or not os.path.exists(path):
                return False
        elif cache.get(field_name) is None:
            return False
    return True


def _enum_value(value: object) -> object:
    return getattr(value, "value", value)


def _nullable_float_equal(left: object, right: object) -> bool:
    if left is None or right is None:
        return left is None and right is None
    try:
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-9)
    except (TypeError, ValueError):
        return False


def _preview_analysis_param_matches(
    cache: dict,
    key: str,
    expected: object,
    *,
    kind: str,
) -> bool:
    value = cache.get(key, _MISSING)
    if value is _MISSING:
        return False
    if kind == "float":
        return _nullable_float_equal(value, expected)
    if kind == "int":
        if value is None or expected is None:
            return value is None and expected is None
        try:
            return int(value) == int(expected)
        except (TypeError, ValueError):
            return False
    if kind == "bool":
        return bool(value) is bool(expected)
    if kind == "enum":
        return str(_enum_value(value)) == str(_enum_value(expected))
    return value == expected


def _resolve_optional_preview_default_match(
    cache: dict,
    key: str,
    request_value: object,
    preview_request_value: object,
    *,
    kind: str,
) -> tuple[object, str]:
    """Resolve an omitted generate option against preview provenance."""

    if request_value is not None:
        return request_value, kind
    if preview_request_value is not _MISSING:
        if preview_request_value is not None:
            return preview_request_value, kind
        cached_value = cache.get(key, _MISSING)
        if cached_value is not _MISSING:
            return cached_value, kind
    return request_value, "raw"


def _resolve_effective_cached_layer_settings(
    *,
    cache: dict,
    request: ConvertGenerateRequest,
    preview_color_layers: object = _MISSING,
    preview_layer_height_mm: object = _MISSING,
) -> tuple[int | None, float | None]:
    """Return the layer settings represented by validated cached analysis."""

    color_layers, _color_layers_kind = _resolve_optional_preview_default_match(
        cache,
        "color_layers",
        request.color_layers,
        preview_color_layers,
        kind="int",
    )
    layer_height_mm, _layer_height_kind = _resolve_optional_preview_default_match(
        cache,
        "layer_height_mm",
        request.layer_height_mm,
        preview_layer_height_mm,
        kind="float",
    )
    return (
        int(color_layers) if color_layers is not None else None,
        float(layer_height_mm) if layer_height_mm is not None else None,
    )


def _preview_analysis_params_match(
    *,
    cache: dict,
    request: ConvertGenerateRequest,
    core_modeling_mode: CoreModelingMode,
    session_material_source: str,
    target_width_mm: float | None,
    preview_color_layers: object = _MISSING,
    preview_layer_height_mm: object = _MISSING,
    compare_target_width: bool = True,
) -> tuple[bool, str]:
    """Compare request semantics with the analysis stored by preview.

    比较生成请求与预览缓存中的分析语义，并统一处理可选层数/层高默认值。
    """

    color_layers_expected, color_layers_kind = _resolve_optional_preview_default_match(
        cache,
        "color_layers",
        request.color_layers,
        preview_color_layers,
        kind="int",
    )
    layer_height_expected, layer_height_kind = _resolve_optional_preview_default_match(
        cache,
        "layer_height_mm",
        request.layer_height_mm,
        preview_layer_height_mm,
        kind="float",
    )

    checks = (
        ("color_mode", request.color_mode, "enum"),
        ("modeling_mode", core_modeling_mode, "enum"),
        ("color_layers", color_layers_expected, color_layers_kind),
        ("layer_height_mm", layer_height_expected, layer_height_kind),
        ("quantize_colors", request.quantize_colors, "int"),
        ("enable_cleanup", request.enable_cleanup, "bool"),
        ("hue_weight", request.hue_weight, "float"),
        ("chroma_gate", request.chroma_gate, "float"),
        ("use_lut_constrained", request.use_lut_constrained, "bool"),
        ("auto_dynamic_range", request.auto_dynamic_range, "bool"),
        ("model_enable", request.model_enable, "bool"),
        ("model_only", request.model_only, "bool"),
        ("model_threshold", request.model_threshold, "float"),
        ("model_margin", request.model_margin, "float"),
        ("svg_pixels_per_mm", request.svg_pixels_per_mm, "float"),
        ("material_source", str(session_material_source or "lut"), "raw"),
    )
    # Hole selection is physical-size dependent: unlike ordinary pixel edits,
    # compensated regions cannot be reprojected to a new size without reanalysis.
    compensation_active = bool(
        request.svg_hole_compensation_enabled
        or cache.get("svg_hole_compensation_enabled", False)
    )
    if (compare_target_width or compensation_active) and not _preview_analysis_param_matches(
        cache,
        "target_width_mm",
        target_width_mm,
        kind="float",
    ):
        return False, "param_mismatch:target_width_mm"
    for key, expected, kind in checks:
        if kind == "raw":
            if cache.get(key, _MISSING) != expected:
                return False, f"param_mismatch:{key}"
            continue
        if not _preview_analysis_param_matches(
            cache,
            key,
            expected,
            kind=kind,
        ):
            return False, f"param_mismatch:{key}"
    enabled = bool(request.svg_hole_compensation_enabled)
    if bool(cache.get("svg_hole_compensation_enabled", False)) != enabled:
        return False, "param_mismatch:svg_hole_compensation_enabled"
    if enabled:
        for key in ("svg_hole_max_area_mm2", "svg_hole_max_width_mm"):
            if not _preview_analysis_param_matches(
                cache, key, getattr(request, key), kind="float",
            ):
                return False, f"param_mismatch:{key}"
    return True, "params_match"


def _require_large_format_cached_analysis_semantics(
    *,
    cache: dict,
    request: LargeFormatConvertGenerateRequest,
    total_width_mm: float,
    session_material_source: str,
    preview_color_layers: object = _MISSING,
    preview_layer_height_mm: object = _MISSING,
) -> None:
    """Reject a structurally valid cache produced with different semantics."""

    matches, _reason = _preview_analysis_params_match(
        cache=cache,
        request=request,
        core_modeling_mode=CoreModelingMode(request.modeling_mode.value),
        session_material_source=session_material_source,
        target_width_mm=total_width_mm,
        preview_color_layers=preview_color_layers,
        preview_layer_height_mm=preview_layer_height_mm,
    )
    if not matches:
        raise HTTPException(
            status_code=409,
            detail=LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL,
        )


def _require_standard_cached_analysis_semantics(
    *,
    cache: dict,
    request: ConvertGenerateRequest,
    core_modeling_mode: CoreModelingMode,
    session_material_source: str,
    preview_color_layers: object = _MISSING,
    preview_layer_height_mm: object = _MISSING,
    analysis_target_width_mm: float | None = None,
) -> None:
    """Reject explicit standard cache reuse with mismatched semantics.

    普通生成显式要求复用空间编辑缓存时，若分析参数与当前请求不同则拒绝生成。
    """

    matches, _reason = _preview_analysis_params_match(
        cache=cache,
        request=request,
        core_modeling_mode=core_modeling_mode,
        session_material_source=session_material_source,
        target_width_mm=(
            request.target_width_mm
            if analysis_target_width_mm is None else analysis_target_width_mm
        ),
        preview_color_layers=preview_color_layers,
        preview_layer_height_mm=preview_layer_height_mm,
        compare_target_width=False,
    )
    if not matches:
        raise HTTPException(
            status_code=409,
            detail=STANDARD_CACHED_ANALYSIS_INVALID_DETAIL,
        )


def _can_reuse_preview_analysis(
    *,
    cache: dict,
    cache_ref: dict | None,
    request: ConvertGenerateRequest,
    core_modeling_mode: CoreModelingMode,
    session_material_source: str,
    replacement_regions: list[dict] | None,
    recipe_overrides: list[dict] | None,
    free_color_set: set[str] | list[str] | None,
    preview_color_layers: object = _MISSING,
    preview_layer_height_mm: object = _MISSING,
) -> tuple[bool, str]:
    """Decide whether generate can skip S02 and load preview analysis arrays.

    只在普通 LUT + raster 默认路径启用。任一分析参数不一致，或遇到
    会重写颜色/高度/几何语义的高级功能，就回退到完整图像处理。
    """

    if session_material_source != "lut":
        return False, "material_source_not_lut"
    if core_modeling_mode not in {
        CoreModelingMode.HIGH_FIDELITY,
        CoreModelingMode.PIXEL,
    }:
        return False, "modeling_mode_not_raster"
    if not _cache_has_preview_analysis_fields(cache, cache_ref):
        return False, "missing_preview_analysis_fields"
    if replacement_regions:
        return False, "replacement_regions_present"
    if recipe_overrides:
        return False, "recipe_overrides_present"
    if free_color_set:
        return False, "free_color_set_present"
    if request.enable_relief:
        return False, "relief_enabled"
    if request.enable_cloisonne:
        return False, "cloisonne_enabled"
    if request.enable_fridge_magnet:
        return False, "fridge_magnet_enabled"
    if request.enable_outline:
        return False, "outline_enabled"
    if request.enable_coating:
        return False, "coating_enabled"
    if request.add_loop:
        return False, "keychain_loop_enabled"

    return _preview_analysis_params_match(
        cache=cache,
        request=request,
        core_modeling_mode=core_modeling_mode,
        session_material_source=session_material_source,
        target_width_mm=request.target_width_mm,
        preview_color_layers=preview_color_layers,
        preview_layer_height_mm=preview_layer_height_mm,
    )


def _can_reuse_planar_vector_preview_glb(
    *,
    cache: dict,
    request: ConvertGenerateRequest,
    core_modeling_mode: CoreModelingMode,
    session_material_source: str,
    is_native_svg: bool,
    uses_model_surface_overlay: bool,
    preview_edit_state_matches: bool,
    preview_edit_state_reason: str,
    preview_color_layers: object = _MISSING,
    preview_layer_height_mm: object = _MISSING,
) -> tuple[bool, str]:
    """Decide whether a native Vector generate may reuse its quick GLB.

    The segmented asset owns browser geometry while relief, coating,
    attachments, outlines, and cloisonne remain live viewer state. Reuse still
    fails closed for a different source, preview provenance/edit identity, or
    model-surface workflow.

    分段资产负责浏览器几何；浮雕、涂层、附件、描边和景泰蓝继续由前端
    实时表达。源文件、预览来源/编辑身份不一致或模型覆面流程仍安全拒绝。
    """

    if core_modeling_mode != CoreModelingMode.VECTOR:
        return False, "modeling_mode_not_vector"
    if not is_native_svg:
        return False, "source_not_native_svg"
    if uses_model_surface_overlay:
        return False, "model_surface_overlay_enabled"
    if not preview_edit_state_matches:
        return False, preview_edit_state_reason

    return _preview_analysis_params_match(
        cache=cache,
        request=request,
        core_modeling_mode=core_modeling_mode,
        session_material_source=session_material_source,
        target_width_mm=request.target_width_mm,
        preview_color_layers=preview_color_layers,
        preview_layer_height_mm=preview_layer_height_mm,
    )


def _normalize_hex_edit_value(value: object) -> str | None:
    """Return one canonical six-digit edit colour or fail closed."""

    if not isinstance(value, str):
        return None
    normalized = value.strip().removeprefix("#").lower()
    if len(normalized) != 6:
        return None
    try:
        int(normalized, 16)
    except ValueError:
        return None
    return normalized


def _normalize_replacement_edit_records(
    value: object,
) -> list[tuple[str, str]] | None:
    """Normalize legacy and public replacement records to ordered mappings."""

    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        return None

    normalized_records: list[tuple[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        source = item.get("matched_hex")
        if source is None:
            source = item.get("selected_color")
        if source is None:
            source = item.get("quantized_hex")
        target = item.get("replacement_hex")
        if target is None:
            target = item.get("replacement_color")
        normalized_source = _normalize_hex_edit_value(source)
        normalized_target = _normalize_hex_edit_value(target)
        if normalized_source is None or normalized_target is None:
            return None
        normalized_records.append((normalized_source, normalized_target))
    return normalized_records


def _normalize_recipe_edit_records(value: object) -> list[object] | None:
    """Normalize recipe edits without weakening their ordered semantics."""

    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        return None
    return [deepcopy(item) for item in value]


def _normalize_free_color_edit_set(value: object) -> frozenset[str] | None:
    """Normalize free-colour values for request/session provenance checks."""

    if value is None:
        return frozenset()
    if isinstance(value, str) or not isinstance(
        value,
        (set, frozenset, list, tuple),
    ):
        return None
    normalized_values: set[str] = set()
    for item in value:
        normalized_item = _normalize_hex_edit_value(item)
        if normalized_item is None:
            return None
        normalized_values.add(normalized_item)
    return frozenset(normalized_values)


def _preview_edit_state_matches(
    *,
    preview_replacement_regions: object,
    generated_replacement_regions: object,
    preview_recipe_overrides: object,
    generated_recipe_overrides: object,
    preview_free_color_set: object,
    generated_free_color_set: object,
) -> tuple[bool, str]:
    """Compare edits represented by the current GLB with generate-time edits."""

    comparisons = (
        (
            "replacement_regions",
            _normalize_replacement_edit_records(preview_replacement_regions),
            _normalize_replacement_edit_records(generated_replacement_regions),
        ),
        (
            "recipe_overrides",
            _normalize_recipe_edit_records(preview_recipe_overrides),
            _normalize_recipe_edit_records(generated_recipe_overrides),
        ),
        (
            "free_color_set",
            _normalize_free_color_edit_set(preview_free_color_set),
            _normalize_free_color_edit_set(generated_free_color_set),
        ),
    )
    for field_name, preview_value, generated_value in comparisons:
        if preview_value is None or generated_value is None:
            return False, f"preview_edit_state_invalid:{field_name}"
        if preview_value != generated_value:
            return False, f"preview_edit_state_mismatch:{field_name}"
    return True, "preview_edit_state_match"


def _cache_field_array(
    *,
    cache: dict,
    cache_ref: dict | None,
    field_name: str,
    mmap_mode: str | None = None,
) -> object | None:
    """Load one cache field when a main-process mutation requires it.

    主进程确实需要修改时，只加载一个缓存字段。
    """
    if field_name in cache:
        return cache.get(field_name)
    if cache_ref is None:
        return None
    try:
        hydrated = hydrate_preview_cache(
            cache_ref,
            fields={field_name},
            mmap_mode=mmap_mode,
        )
    except (OSError, ValueError, TypeError, KeyError, EOFError) as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Preview cache {field_name} artifact is unavailable or "
                "unreadable. Re-run preview before generating with "
                "recipe overrides."
            ),
        ) from exc
    return hydrated.get(field_name)


def _recover_select_all_color_region_mask(
    *,
    cache: dict,
    cache_ref: dict | None,
    region_id: object,
) -> np.ndarray | None:
    """Recover a select-all pseudo-region mask from cached preview colors."""

    if not isinstance(region_id, str):
        return None
    if not region_id.startswith(_SELECT_ALL_COLOR_REGION_PREFIX):
        return None

    color_hex = region_id[len(_SELECT_ALL_COLOR_REGION_PREFIX):].strip().lstrip("#")
    if len(color_hex) != 6:
        return None
    try:
        target_rgb = np.asarray(
            [
                int(color_hex[0:2], 16),
                int(color_hex[2:4], 16),
                int(color_hex[4:6], 16),
            ],
            dtype=np.uint8,
        )
    except ValueError:
        return None

    matched_rgb = _cache_field_array(
        cache=cache,
        cache_ref=cache_ref,
        field_name="matched_rgb",
        mmap_mode="r",
    )
    mask_solid = _cache_field_array(
        cache=cache,
        cache_ref=cache_ref,
        field_name="mask_solid",
        mmap_mode="r",
    )
    if matched_rgb is None or mask_solid is None:
        return None

    matched_arr = np.asarray(matched_rgb)
    if matched_arr.ndim != 3 or matched_arr.shape[2] < 3:
        return None
    mask_solid_arr = np.asarray(mask_solid, dtype=bool)
    if mask_solid_arr.shape != matched_arr.shape[:2]:
        return None

    color_mask = np.all(matched_arr[..., :3] == target_rgb, axis=-1) & mask_solid_arr
    if not np.any(color_mask):
        return None
    return np.asarray(color_mask, dtype=bool)


def _resolve_applied_override_mask_snapshot(
    *,
    session_data: dict,
    sid: str,
    region_id: object,
    shape: tuple[int, int],
) -> np.ndarray | None:
    """Return the mask snapshotted when this override was applied, if usable.

    The live selection state prunes synthetic ``__editor_selection__:<rev>``
    region ids on every selection gesture, so an override applied earlier can
    no longer be resolved from ``selected_region_masks``. The apply endpoint
    snapshots the exact masks it used; this helper validates one snapshot
    entry against the current material-matrix shape before handing it back.

    实时选区状态会在每次选区手势时清理 __editor_selection__:<rev> 合成
    条目，导致更早应用的覆盖无法再从 selected_region_masks 解析。apply
    端点会快照当时使用的掩码；本函数取出对应条目并校验其与当前
    material_matrix 的形状一致后才返回。

    Args:
        session_data (dict): Session data holding the applied-mask snapshot.
            (携带已应用掩码快照的会话数据)
        sid (str): Session id used for structured-log correlation. (用于结构化
            日志关联的会话 id)
        region_id (object): Override region id to resolve. (待解析的覆盖区域 id)
        shape (tuple[int, int]): Expected ``(height, width)`` of the mask.
            (掩码应有的 (高, 宽) 形状)

    Returns:
        np.ndarray | None: Boolean mask copy matching ``shape``, or ``None``
        when no usable snapshot exists. (与 shape 匹配的布尔掩码副本；无可用
        快照时为 None)
    """
    if not isinstance(region_id, str):
        return None
    try:
        resolved = resolve_recipe_override_masks(
            session_data,
            [{"region_id": region_id}],
            shape,
        )
    except ValueError:
        resolved = {}
    mask = resolved.get(region_id)
    if mask is None:
        log.warning(
            "Applied recipe-override snapshot is invalid; rejecting generation",
            extra={
                "event": "recipe_override_snapshot_invalid",
                "error_type": "RecipeOverrideSnapshotInvalid",
                "error_message": (
                    "The stored override mask snapshot failed validation "
                    "(shape, dtype, or content); generation will be rejected "
                    "to preserve the committed footprint."
                ),
                "recovery_action": "reapply_color_replacement",
                "session_id": sid,
                "region_id": str(region_id),
            },
        )
        return None
    return mask


def _parse_batch_color_height_map(value: str | None) -> dict[str, float] | None:
    if not value:
        return None
    try:
        raw_map = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="Invalid color_height_map JSON") from exc
    if not isinstance(raw_map, dict):
        raise HTTPException(status_code=422, detail="color_height_map must be a JSON object")
    parsed: dict[str, float] = {}
    for key, raw_height in raw_map.items():
        try:
            height = float(raw_height)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="color_height_map heights must be numbers") from exc
        if not math.isfinite(height):
            raise HTTPException(status_code=422, detail="color_height_map heights must be finite")
        parsed[str(key)] = height
    return parsed or None


def _normalize_batch_string_list(value: list[str] | str | None) -> list[str]:
    """Normalize repeated/JSON/comma-separated form list values.

    规范化 multipart/form-data 中的列表字段，兼容重复字段、JSON 数组和
    逗号分隔字符串。
    """
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [item.strip() for item in stripped.split(",") if item.strip()]

    try:
        normalized = [str(item).strip() for item in value if str(item).strip()]
    except TypeError:
        return []
    if len(normalized) == 1:
        stripped = normalized[0]
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
    return normalized




def _serialize_recipe_override_for_worker(
    item: dict[str, object],
) -> dict[str, object]:
    """Serialize one normalized override without dropping dynamic metadata.

    序列化单个归一化覆盖项，并保留动态实际/打印配方元数据。
    """

    payload: dict[str, object] = {
        "region_id": item["region_id"],
        "recipe": list(item["recipe"]),
        "layer_order": item["layer_order"],
    }
    for count_field in (
        "color_layers",
        "actual_layer_count",
        "padding_layer_count",
    ):
        if item.get(count_field) is not None:
            payload[count_field] = int(item[count_field])
    for recipe_field in (
        "actual_recipe_top_to_bottom",
        "print_recipe_top_to_bottom",
    ):
        if item.get(recipe_field) is not None:
            payload[recipe_field] = list(item[recipe_field])
    if item.get("virtual_materials"):
        payload["virtual_materials"] = [
            dict(vm) for vm in item["virtual_materials"]
        ]
    return payload










def _resolve_session_material_backing_index(
    session_data: dict,
    request: ConvertGenerateRequest,
) -> int:
    selected_materials = session_data.get("selected_materials") or []
    requested_index = (
        request.material_backing_material_index
        if request.material_backing_material_index is not None
        else session_data.get("material_backing_material_index")
    )
    return _resolve_material_backing_index(selected_materials, requested_index)




def _prepare_recipe_override_worker_inputs(
    *,
    cache: dict,
    cache_ref: dict | None = None,
    session_data: dict,
    recipe_overrides: list[dict[str, object]] | None,
    request: ConvertGenerateRequest,
    sid: str,
    store: SessionStore,
) -> tuple[str | None, str | None]:
    """Serialize recipe-override artifacts required by the worker pipeline."""

    if not recipe_overrides:
        return None, None

    cached_material_matrix = _cache_field_array(
        cache=cache,
        cache_ref=cache_ref,
        field_name="material_matrix",
        mmap_mode="r",
    )
    region_masks = session_data.get("selected_region_masks") or {}
    lut_metadata = cache.get("lut_metadata")
    if cached_material_matrix is None:
        raise HTTPException(status_code=409, detail="Preview cache missing material_matrix")
    if not isinstance(region_masks, dict):
        region_masks = {}
    session_data["selected_region_masks"] = region_masks

    material_matrix_override = np.asarray(cached_material_matrix).copy()
    current_layers = int(material_matrix_override.shape[2]) if material_matrix_override.ndim == 3 else 0
    target_layers = int(request.color_layers or current_layers)
    metadata_order = getattr(lut_metadata, "layer_order", "Top2Bottom")
    # Material-archive sessions never carry an ``lut_metadata`` (p02 sets it
    # to None and ``cache["lut_metadata"]`` is also None). Falling back to
    # ``base_channel_idx = 0`` would silently pad the grown layers with the
    # first user material (e.g. a coloured slot like blue) instead of the
    # genuine backing channel (typically white). Detect material-archive
    # mode via the session and infer the backing channel from the selected
    # materials so the padded slab matches the user's backing colour.
    # 耗材档案会话不会带 LUTMetadata，回退到 0 会用第一种用户耗材（往往是
    # 某个彩色槽）当作背板色填补加层，外观面/底板逻辑会错乱。检测耗材档案
    # 会话并按 selected_materials 推断真实背板通道。
    if (
        lut_metadata is None
        and str(session_data.get("material_source") or "lut") == "material_archive"
    ):
        selected_materials = session_data.get("selected_materials") or []
        if isinstance(selected_materials, (list, tuple)) and selected_materials:
            slot_names_src = cache.get("slot_names") or (cache.get("color_conf") or {}).get("slots") or []
            slot_names = list(slot_names_src) if isinstance(slot_names_src, (list, tuple)) else []
            preview_colors = cache.get("preview_colors")
            if not isinstance(preview_colors, dict):
                preview_colors = (cache.get("color_conf") or {}).get("preview") or {}
            base_channel_idx = int(
                infer_material_archive_base_channel_idx(
                    list(selected_materials),
                    slot_names,
                    preview_colors,
                )
            )
        else:
            base_channel_idx = int(getattr(lut_metadata, "base_channel_idx", 0))
    else:
        base_channel_idx = int(getattr(lut_metadata, "base_channel_idx", 0))

    if target_layers > current_layers and material_matrix_override.ndim == 3:
        # Pad the grown layers so that:
        #   (a) ``~mask_solid`` (transparent background — p03 has already
        #       marked it as ``-1``) stays as ``-1`` air, otherwise S07
        #       emits a ring-shaped White mesh around the model ("透明通道
        #       失效 / 整块白矩形包裹" regression).
        #   (b) ``mask_solid`` non-override pixels keep the LUT base channel
        #       so the extended column stays continuous with the backing
        #       slab; padding them with ``-1`` leaves the user's 6th layer
        #       visually empty ("第 6 层空层" regression).
        # The override region is overwritten below with ``recipe_full``.
        # 扩展层要同时兼顾两件事：(a) mask_solid 外的透明背景保持 -1 空气，
        # 避免 S07 围着模型生成一圈白色 mesh；(b) mask_solid 内非 override
        # 像素保留 base channel，避免第 6 层塌成空层。
        cached_mask_solid = _cache_field_array(
            cache=cache,
            cache_ref=cache_ref,
            field_name="mask_solid",
            mmap_mode="r",
        )
        if cached_mask_solid is None:
            raise HTTPException(
                status_code=409,
                detail="Preview cache missing mask_solid; re-run preview before generating with recipe overrides.",
            )
        mask_solid_arr = np.asarray(cached_mask_solid, dtype=bool)
        if mask_solid_arr.shape != material_matrix_override.shape[:2]:
            raise HTTPException(
                status_code=409,
                detail=(
                    "mask_solid shape does not match material_matrix; "
                    "re-run preview before generating with recipe overrides."
                ),
            )
        material_matrix_override = _ensure_material_matrix_signed_capacity(
            material_matrix_override,
            -1,
            base_channel_idx,
        )
        pad_slab = np.full(
            (
                material_matrix_override.shape[0],
                material_matrix_override.shape[1],
                target_layers - current_layers,
            ),
            -1,
            dtype=material_matrix_override.dtype,
        )
        pad_slab[mask_solid_arr] = base_channel_idx
        if metadata_order == "Top2Bottom":
            material_matrix_override = np.concatenate([material_matrix_override, pad_slab], axis=2)
        else:
            material_matrix_override = np.concatenate([pad_slab, material_matrix_override], axis=2)
    elif target_layers < current_layers:
        raise HTTPException(
            status_code=422,
            detail="Recipe overrides cannot reduce the current optical layer count",
        )

    # Masks resolved for this request, kept request-local so unpacked
    # snapshots never re-inflate into the aliased in-memory session dict
    # (a packed ~H*W/8-byte entry would otherwise persist back as a raw
    # H*W boolean array on first generate).
    # 本次请求解析出的掩码，严格请求局部：解包后的快照绝不写回与内存版
    # 会话共享的字典，否则打包的 ~H*W/8 字节条目会在首次生成时以裸
    # H*W 布尔数组的形式重新膨胀并驻留。
    resolved_override_masks: dict[str, np.ndarray] = {}
    # Snapshot capability separates two eras. Sessions without the key
    # predate applied-mask snapshots and keep the legacy mutable-source chain.
    # Sessions WITH the key have committed footprints, even if the stored
    # container is empty or invalid:
    # an id that is missing or fails validation there means committed state
    # is unreadable, and silently re-resolving it from live selection state
    # or a recomputed select-all region would drift the footprint — that is
    # a deterministic 422 instead.
    # 快照能力区分两个时代。只有完全没有该键的会话才是旧会话并保留可变
    # 来源回退链。只要键存在，即使容器为空或损坏，也表示会话拥有已提交足
    # 迹；此时若从实时选区或重算 select-all 静默回退会让足迹漂移——必须
    # 返回确定性 422。
    has_snapshot_capability = (
        RECIPE_OVERRIDE_APPLIED_MASKS_KEY in session_data
    )

    legacy_recovered_masks: dict[str, np.ndarray] = {}

    def recover_legacy_mask(region_id: str) -> np.ndarray | None:
        mask = _recover_select_all_color_region_mask(
            cache=cache,
            cache_ref=cache_ref,
            region_id=region_id,
        )
        if mask is not None:
            legacy_recovered_masks[region_id] = np.asarray(mask, dtype=bool)
        return mask

    try:
        resolved_override_masks = resolve_recipe_override_masks(
            session_data,
            recipe_overrides,
            tuple(material_matrix_override.shape[:2]),
            legacy_fallback=(
                None if has_snapshot_capability else recover_legacy_mask
            ),
        )
    except ValueError as exc:
        if has_snapshot_capability:
            log.warning(
                "Applied recipe-override snapshots are invalid; rejecting generation",
                extra={
                    "event": "recipe_override_snapshot_invalid",
                    "session_id": sid,
                    "error_type": "invalid_applied_mask_snapshot",
                    "error_message": str(exc),
                    "recovery_action": "reapply_color_replacement",
                    "region_ids": [
                        str(item.get("region_id")) for item in recipe_overrides
                    ],
                },
            )
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{exc}. "
                    "Re-apply the color replacement, then generate again."
                ),
            ) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if legacy_recovered_masks:
        region_masks.update(legacy_recovered_masks)
        store.put(sid, "selected_region_masks", region_masks)

    for item in recipe_overrides:
        region_id = item["region_id"]
        item_recipe = item["recipe"]
        item_layer_order = item["layer_order"]
        if has_snapshot_capability:
            region_mask = resolved_override_masks[str(region_id)]
            log.debug(
                "Recipe override mask resolved from applied-time snapshot",
                extra={
                    "event": "recipe_override_mask_snapshot_resolved",
                    "session_id": sid,
                    "region_id": str(region_id),
                },
            )
        else:
            region_mask = resolved_override_masks[str(region_id)]
        recipe = convert_recipe_between_orders(
            list(item_recipe),
            item_layer_order,
            metadata_order,
        )
        if len(recipe) < target_layers:
            pad_count = target_layers - len(recipe)
            if metadata_order == "Top2Bottom":
                recipe = recipe + [base_channel_idx] * pad_count
            else:
                recipe = [base_channel_idx] * pad_count + recipe
        elif len(recipe) > target_layers:
            raise HTTPException(
                status_code=422,
                detail=f"Recipe override has {len(recipe)} layers but target mode is {target_layers}",
            )
        material_matrix_override = _ensure_material_matrix_signed_capacity(
            material_matrix_override,
            recipe,
            base_channel_idx,
        )
        material_matrix_override[np.asarray(region_mask, dtype=bool)] = np.asarray(
            recipe,
            dtype=material_matrix_override.dtype,
        )

    fd, mm_temp_path = tempfile.mkstemp(suffix=".npy", dir=TEMP_DIR)
    os.close(fd)
    np.save(mm_temp_path, material_matrix_override)
    store.register_temp_file(sid, mm_temp_path)

    recipe_override_masks_path: str | None = None
    if resolved_override_masks:
        fd, masks_temp_path = tempfile.mkstemp(suffix=".pkl", dir=TEMP_DIR)
        os.close(fd)
        with open(masks_temp_path, "wb") as f:
            pickle.dump(resolved_override_masks, f)
        recipe_override_masks_path = masks_temp_path
        store.register_temp_file(sid, masks_temp_path)

    return mm_temp_path, recipe_override_masks_path


def _has_requested_fridge_magnet_cavities(request: ConvertGenerateRequest) -> bool:
    """Return whether fridge-magnet cavities are explicitly requested."""

    return bool(request.enable_fridge_magnet)


def _validate_native_vector_relief_compatibility(
    request: ConvertGenerateRequest,
) -> None:
    """Reject native SVG relief branches that would otherwise export flat.

    拒绝会静默退回平面模型的原生 SVG 浮雕组合。
    """

    if not request.enable_relief or request.modeling_mode != ModelingMode.VECTOR:
        return
    if (
        request.structure_mode != StructureMode.SINGLE_SIDED
        or request.color_mode == ColorMode.FIVE_COLOR_EXT
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "Native SVG relief supports only single-sided, "
                "non-5-Color Extended models."
            ),
        )


@router.post("/generate")
async def convert_generate(
    body: _GenerateBody,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
    pool: WorkerPoolManager = Depends(get_worker_pool),
) -> GenerateResponse:
    """Generate a printable 3MF model via process pool.
    通过进程池生成可打印的 3MF 模型。

    Session and FileRegistry operations run on the main thread.
    CPU-intensive model generation is offloaded to the worker pool.
    Session 和 FileRegistry 操作在主线程完成。
    CPU 密集型模型生成卸载到工作进程池。
    """
    api_t0 = time.perf_counter()

    # 1. Session validation and immutable input snapshot (main thread).
    request = body.params
    revision_bytes(request.project_revision_file_id, registry)
    (
        session_data,
        committed_content_revision,
        committed_selection_revision,
    ) = _capture_generation_snapshot(
        store,
        body.session_id,
        requested_revision=request.editor_content_revision,
        requested_selection_revision=request.selection_revision,
        revision_mismatch_detail=(
            "Visible content changed before generation started "
            "(editor content revision mismatch); "
            "refresh the editor state and try again."
        ),
    )
    cache, cache_ref = _require_preview_cache_for_generate(session_data)
    validate_export_device_selection(
        printer_id=request.printer_id,
        slicer=request.slicer,
        nozzle_size=request.nozzle_size,
        device_profile_id=request.device_profile_id,
        build_plate_id=request.build_plate_id,
        custom_3mf_template_id=request.custom_3mf_template_id,
        supports_custom_template=True,
    )
    _validate_native_vector_relief_compatibility(request)
    require_material_selection(request, session_data)

    # Retrieve paths stored during preview
    image_path: str | None = session_data.get("image_path")
    lut_path: str | None = session_data.get("lut_path")
    session_material_source = session_data.get("material_source", "lut")
    if not image_path or not os.path.exists(image_path):
        raise HTTPException(status_code=409, detail=SOURCE_IMAGE_UNAVAILABLE_DETAIL)
    _validate_svg_hole_compensation(
        enabled=request.svg_hole_compensation_enabled,
        image_path=image_path,
        modeling_mode=request.modeling_mode,
    )
    if session_material_source != "material_archive":
        if not lut_path or not os.path.exists(lut_path):
            raise HTTPException(status_code=409, detail=LUT_DATA_UNAVAILABLE_DETAIL)
    else:
        lut_path = "__material_archive__"

    # Resolve the preview-session contract before any generated SVG or temp
    # artifact is created. Native source SVGs retain their geometry and now
    # use the dynamic material contract directly.
    core_modeling_mode = CoreModelingMode(request.modeling_mode.value)
    dynamic_material_settings = _resolve_session_dynamic_material_settings(
        session_data=session_data,
        request=request,
        material_source=str(session_material_source or "lut"),
        native_svg_vector=(
            core_modeling_mode == CoreModelingMode.COLOR_CARD
            or (
                core_modeling_mode == CoreModelingMode.VECTOR
                and str(image_path).lower().endswith(".svg")
            )
        ),
    )
    if core_modeling_mode == CoreModelingMode.COLOR_CARD and dynamic_material_settings[0]:
        raise HTTPException(
            status_code=422,
            detail=(
                "Dynamic material layer count does not support generated "
                "color-card SVGs. Use a native uploaded SVG instead."
            ),
        )
    if (
        session_material_source == "material_archive"
        and dynamic_material_settings[0]
    ):
        # Preview normally rejects this already. Keep generation defensive so
        # a restored or legacy session cannot let an ambiguous catalog cache
        # identity reach the exact solver.
        _validate_unique_dynamic_material_selection(
            session_data.get("selected_materials") or []
        )

    # Merge replacement_regions: prefer session state, fall back to request body
    replacement_regions = session_data.get("replacement_regions") or None
    if request.replacement_regions is not None:
        replacement_regions = [
            {
                "quantized_hex": r.quantized_hex,
                "matched_hex": r.matched_hex,
                "replacement_hex": r.replacement_hex,
            }
            for r in request.replacement_regions
        ]
    recipe_overrides = _resolve_recipe_overrides(session_data, request)
    preview_recipe_overrides = _backfill_recipe_override_virtual_materials(
        session_data,
        _normalize_recipe_overrides(
            session_data.get("recipe_overrides") or None
        ),
    )

    free_color_set = session_data.get("free_color_set") or None
    if request.free_color_set is not None:
        free_color_set = request.free_color_set
    preview_edit_state_matches, preview_edit_state_reason = (
        _preview_edit_state_matches(
            preview_replacement_regions=session_data.get("replacement_regions"),
            generated_replacement_regions=replacement_regions,
            preview_recipe_overrides=preview_recipe_overrides,
            generated_recipe_overrides=recipe_overrides,
            preview_free_color_set=session_data.get("free_color_set"),
            generated_free_color_set=free_color_set,
        )
    )

    # Color-card mode: generate SVG from cached palette, swap image_path,
    # and force VECTOR mode so the existing vector branch produces the 3MF.
    # 色卡模式：从缓存调色板生成 SVG，替换 image_path 并强制走矢量分支。
    generated_color_card_svg = False
    if core_modeling_mode == CoreModelingMode.COLOR_CARD:
        color_palette = cache.get("color_card_source_palette") or cache.get(
            "color_palette",
        )
        if not color_palette:
            raise HTTPException(
                status_code=409,
                detail=PREVIEW_COLOR_PALETTE_UNAVAILABLE_DETAIL,
            )
        hex_colors = [e["hex"] for e in color_palette if "hex" in e]
        if not hex_colors:
            raise HTTPException(status_code=409, detail="color_palette has no hex entries.")
        from core.color_card import generate_color_card_svg
        svg_path = generate_color_card_svg(hex_colors, show_labels=True, output_dir=TEMP_DIR)
        store.register_temp_file(body.session_id, svg_path)
        image_path = svg_path
        core_modeling_mode = CoreModelingMode.VECTOR
        generated_color_card_svg = True

    vector_parse_clip_cache_path: str | None = None
    if core_modeling_mode == CoreModelingMode.VECTOR and not generated_color_card_svg:
        candidate_vector_cache_path = cache.get("vector_parse_clip_cache_path")
        if (
            isinstance(candidate_vector_cache_path, str)
            and os.path.exists(candidate_vector_cache_path)
        ):
            vector_parse_clip_cache_path = candidate_vector_cache_path

    # Resolve height_mode for relief branching
    # 解析 height_mode 用于浮雕分支选择
    height_mode = request.height_mode or "color"
    _require_heightmap_for_relief(session_data, request)
    _validate_material_archive_relief_minimum_height(
        enable_relief=request.enable_relief,
        material_source=str(session_material_source or "lut"),
        height_mode=height_mode,
        color_height_map=request.color_height_map,
        heightmap_max_height=request.heightmap_max_height,
        session_data=session_data,
        cache=cache,
        cache_ref=cache_ref,
        requested_color_layers=request.color_layers,
        recipe_overrides=recipe_overrides,
    )

    # If heightmap mode, save session heightmap to temp file for worker process
    # 高度图模式时，将 session 中的高度图保存为临时文件供工作进程使用
    heightmap_path: str | None = None
    if request.enable_relief and height_mode == "heightmap":
        heightmap_grayscale = session_data.get("heightmap_grayscale")
        if heightmap_grayscale is not None:
            fd, hm_temp_path = tempfile.mkstemp(suffix=".png", dir=TEMP_DIR)
            os.close(fd)
            Image.fromarray(heightmap_grayscale).save(hm_temp_path)
            heightmap_path = hm_temp_path
            store.register_temp_file(body.session_id, hm_temp_path)

    # 2a. Serialize cached matched_rgb to temp file if requested
    # 当存在区域替换时，将缓存的 matched_rgb 序列化为临时文件供 Worker 使用
    matched_rgb_path: str | None = None
    original_matched_rgb_path: str | None = None
    height_identity_rgb_path: str | None = None
    mask_solid_path: str | None = None
    material_matrix_path: str | None = None
    original_material_matrix_path: str | None = None
    quantized_image_path: str | None = None
    generation_analysis_target_width_mm = request.target_width_mm
    if _should_use_model_surface_overlay(session_data):
        surface_target_width_mm = session_data.get("surface_target_width_mm")
        if surface_target_width_mm is not None:
            try:
                generation_analysis_target_width_mm = float(
                    surface_target_width_mm
                )
            except (TypeError, ValueError, OverflowError) as exc:
                raise HTTPException(
                    status_code=409,
                    detail=MODEL_SURFACE_CONFIG_UNAVAILABLE_DETAIL,
                ) from exc
            if (
                not math.isfinite(generation_analysis_target_width_mm)
                or generation_analysis_target_width_mm <= 0
            ):
                raise HTTPException(
                    status_code=409,
                    detail=MODEL_SURFACE_CONFIG_UNAVAILABLE_DETAIL,
                )
    preview_target_width_matches = _preview_analysis_param_matches(
        cache,
        "target_width_mm",
        generation_analysis_target_width_mm,
        kind="float",
    )
    cached_edit_projection_required = bool(
        not preview_target_width_matches and request.use_cached_matched_rgb
    )
    recipe_mask_projection_required = bool(
        not preview_target_width_matches
        and recipe_overrides
        and not request.use_cached_matched_rgb
    )
    edit_projection_required = (
        cached_edit_projection_required or recipe_mask_projection_required
    )
    requires_dynamic_quantized_analysis = bool(
        dynamic_material_settings[0]
        and not edit_projection_required
        and core_modeling_mode
        in {
            CoreModelingMode.HIGH_FIDELITY,
            CoreModelingMode.PIXEL,
        }
    )
    reuse_preview_analysis, reuse_preview_analysis_reason = _can_reuse_preview_analysis(
        cache=cache,
        cache_ref=cache_ref,
        request=request,
        core_modeling_mode=core_modeling_mode,
        session_material_source=session_material_source,
        replacement_regions=replacement_regions,
        recipe_overrides=recipe_overrides,
        free_color_set=free_color_set,
        preview_color_layers=session_data.get("color_layers", _MISSING),
        preview_layer_height_mm=session_data.get("layer_height_mm", _MISSING),
    )
    (
        reuse_planar_vector_preview_glb,
        reuse_planar_vector_preview_glb_reason,
    ) = _can_reuse_planar_vector_preview_glb(
        cache=cache,
        request=request,
        core_modeling_mode=core_modeling_mode,
        session_material_source=str(session_material_source or "lut"),
        is_native_svg=(
            not generated_color_card_svg
            and str(image_path).lower().endswith(".svg")
        ),
        uses_model_surface_overlay=_should_use_model_surface_overlay(session_data),
        preview_edit_state_matches=preview_edit_state_matches,
        preview_edit_state_reason=preview_edit_state_reason,
        preview_color_layers=session_data.get("color_layers", _MISSING),
        preview_layer_height_mm=session_data.get("layer_height_mm", _MISSING),
    )
    if request.use_cached_matched_rgb:
        (
            matched_rgb_path,
            mask_solid_path,
            material_matrix_path,
            quantized_image_path,
        ) = _resolve_validated_large_format_cached_analysis_paths(
            cache=cache,
            cache_ref=cache_ref,
            sid=body.session_id,
            store=store,
            require_quantized_image=requires_dynamic_quantized_analysis,
            dynamic_max_layer_count=(
                dynamic_material_settings[2]
                if dynamic_material_settings[0]
                else None
            ),
            invalid_detail=STANDARD_CACHED_ANALYSIS_INVALID_DETAIL,
        )
        _require_standard_cached_analysis_semantics(
            cache=cache,
            request=request,
            core_modeling_mode=core_modeling_mode,
            session_material_source=str(session_material_source or "lut"),
            analysis_target_width_mm=generation_analysis_target_width_mm,
            preview_color_layers=session_data.get("color_layers", _MISSING),
            preview_layer_height_mm=session_data.get(
                "layer_height_mm",
                _MISSING,
            ),
        )
        if cached_edit_projection_required:
            (
                original_matched_rgb_path,
                original_material_matrix_path,
                edit_projection_source_shape,
            ) = _resolve_validated_edit_projection_paths(
                cache=cache,
                cache_ref=cache_ref,
                sid=body.session_id,
                store=store,
                matched_rgb_path=matched_rgb_path,
                material_matrix_path=material_matrix_path,
                invalid_detail=STANDARD_CACHED_ANALYSIS_INVALID_DETAIL,
            )
            edit_projection = _build_edit_projection_metadata(
                cache=cache,
                source_shape=edit_projection_source_shape,
                mode="delta",
                invalid_detail=STANDARD_CACHED_ANALYSIS_INVALID_DETAIL,
            )
        else:
            edit_projection = None
    elif recipe_mask_projection_required:
        edit_projection = _build_edit_projection_metadata(
            cache=cache,
            source_shape=None,
            mode="recipe_masks",
            invalid_detail=STANDARD_CACHED_ANALYSIS_INVALID_DETAIL,
        )
    else:
        edit_projection = None
    if reuse_preview_analysis or request.use_cached_matched_rgb:
        effective_color_layers, effective_layer_height_mm = (
            _resolve_effective_cached_layer_settings(
                cache=cache,
                request=request,
                preview_color_layers=session_data.get("color_layers", _MISSING),
                preview_layer_height_mm=session_data.get(
                    "layer_height_mm",
                    _MISSING,
                ),
            )
        )
        request = request.model_copy(
            update={
                "color_layers": effective_color_layers,
                "layer_height_mm": effective_layer_height_mm,
            }
        )
    if (
        reuse_preview_analysis
        and requires_dynamic_quantized_analysis
        and not request.use_cached_matched_rgb
    ):
        (
            matched_rgb_path,
            mask_solid_path,
            material_matrix_path,
            quantized_image_path,
        ) = _resolve_validated_large_format_cached_analysis_paths(
            cache=cache,
            cache_ref=cache_ref,
            sid=body.session_id,
            store=store,
            require_quantized_image=True,
            dynamic_max_layer_count=dynamic_material_settings[2],
            invalid_detail=STANDARD_CACHED_ANALYSIS_INVALID_DETAIL,
        )
    should_forward_cached_analysis = (
        reuse_preview_analysis
        or request.use_cached_matched_rgb
        or session_material_source == "material_archive"
    )
    if (should_forward_cached_analysis or recipe_overrides) and (
        request.svg_hole_compensation_enabled
        or cache.get("svg_hole_compensation_enabled", False)
    ):
        # Material archives and recipe region masks consume preview geometry
        # even without explicit cache reuse. They must describe the same SVG.
        _require_standard_cached_analysis_semantics(
            cache=cache,
            request=request,
            core_modeling_mode=core_modeling_mode,
            session_material_source=str(session_material_source or "lut"),
            analysis_target_width_mm=generation_analysis_target_width_mm,
            preview_color_layers=session_data.get("color_layers", _MISSING),
            preview_layer_height_mm=session_data.get("layer_height_mm", _MISSING),
        )
    require_cached_material_analysis = session_material_source == "material_archive"
    log.debug(
        "Cached matched RGB input state resolved: use_cached_matched_rgb=%s, has_replacement_regions=%s",
        request.use_cached_matched_rgb,
        bool(replacement_regions),
        extra={
            "event": "converter_generate_cached_input_state",
            "use_cached_matched_rgb": request.use_cached_matched_rgb,
            "has_replacement_regions": bool(replacement_regions),
            "reuse_preview_analysis": reuse_preview_analysis,
            "reuse_preview_analysis_reason": reuse_preview_analysis_reason,
            "reuse_planar_vector_preview_glb": (
                reuse_planar_vector_preview_glb
            ),
            "reuse_planar_vector_preview_glb_reason": (
                reuse_planar_vector_preview_glb_reason
            ),
        },
    )
    if should_forward_cached_analysis:
        if matched_rgb_path is None:
            matched_rgb_path = _cache_field_path_or_tempfile(
                cache=cache,
                cache_ref=cache_ref,
                field_name="matched_rgb",
                sid=body.session_id,
                store=store,
            )
        if require_cached_material_analysis:
            matched_rgb_path = _require_loadable_material_archive_cache_path(
                matched_rgb_path,
                "matched_rgb",
            )
        height_identity_rgb_path = _cache_field_path_or_tempfile(
            cache=cache,
            cache_ref=cache_ref,
            field_name="height_identity_rgb",
            sid=body.session_id,
            store=store,
        )
        if height_identity_rgb_path is None:
            height_identity_rgb_path = _cache_field_path_or_tempfile(
                cache=cache,
                cache_ref=cache_ref,
                field_name="original_matched_rgb",
                sid=body.session_id,
                store=store,
            )
        if height_identity_rgb_path is None:
            height_identity_rgb_path = matched_rgb_path
        if matched_rgb_path is not None:
            cached_matched_rgb = cache.get("matched_rgb")
            field_ref = (
                (cache_ref or {}).get("fields", {}).get("matched_rgb", {})
                if cache_ref is not None
                else {}
            )
            log.debug(
                "Cached matched RGB prepared for worker",
                extra={
                    "event": "converter_generate_cached_matched_rgb_prepared",
                    "matched_rgb_shape": (
                        list(cached_matched_rgb.shape)
                        if hasattr(cached_matched_rgb, "shape")
                        else field_ref.get("shape")
                    ),
                    "matched_rgb_dtype": (
                        str(cached_matched_rgb.dtype)
                        if hasattr(cached_matched_rgb, "dtype")
                        else field_ref.get("dtype")
                    ),
                    "artifact_backed": cache_ref is not None,
                },
            )

            # Forward mask_solid alongside matched_rgb so the SVG-native
            # vector branch can intersect each shape mask with the solid
            # area when projecting region edits back into matched_shapes.
            # Without this the vector 3MF stays on the SVG fill colour and
            # silently drops every /region-replace mutation.
            # 把 mask_solid 与 matched_rgb 一起透传给 worker，让矢量分支
            # 可以在求交后回写颜色；不传就会丢掉用户的区域替换。
            if mask_solid_path is None:
                mask_solid_path = _cache_field_path_or_tempfile(
                    cache=cache,
                    cache_ref=cache_ref,
                    field_name="mask_solid",
                    sid=body.session_id,
                    store=store,
                )
            if require_cached_material_analysis:
                mask_solid_path = _require_loadable_material_archive_cache_path(
                    mask_solid_path,
                    "mask_solid",
                )

            if material_matrix_path is None:
                material_matrix_path = _cache_field_path_or_tempfile(
                    cache=cache,
                    cache_ref=cache_ref,
                    field_name="material_matrix",
                    sid=body.session_id,
                    store=store,
                )
            if require_cached_material_analysis:
                material_matrix_path = _require_loadable_material_archive_cache_path(
                    material_matrix_path,
                    "material_matrix",
                )

    if reuse_preview_analysis and not (
        matched_rgb_path and mask_solid_path and material_matrix_path
    ):
        reuse_preview_analysis = False
        reuse_preview_analysis_reason = "analysis_paths_unavailable"

    reuse_preview_glb = (
        reuse_preview_analysis or reuse_planar_vector_preview_glb
    )
    preview_glb_path = _resolve_reusable_preview_glb_path(
        cache=cache,
        request=request,
        sid=body.session_id,
        registry=registry,
        reuse_preview_glb=reuse_preview_glb,
    )

    override_material_matrix_path, recipe_override_masks_path = _prepare_recipe_override_worker_inputs(
        cache=cache,
        cache_ref=cache_ref,
        session_data=session_data,
        recipe_overrides=recipe_overrides,
        request=request,
        sid=body.session_id,
        store=store,
    )
    if override_material_matrix_path is not None:
        material_matrix_path = override_material_matrix_path

    # 2b. Collect scalar parameters into a dict for the worker
    params: dict = {
        **build_generation_worker_params(request),
        "target_width_mm": request.target_width_mm,
        "modeling_mode": core_modeling_mode,
        # Dynamic cache reuse already contains every confirmed RGB, recipe,
        # and solver-metadata edit. Replaying its mappings in S03 would solve
        # the same edits twice and require a target map outside S02's final-
        # generation cache contract. Keep legacy fixed-layer replay unchanged.
        # 动态缓存已包含确认后的最终编辑，不再重放全局替色；固定层路径保持原语义。
        "replacement_regions": (
            None
            if request.use_cached_matched_rgb and dynamic_material_settings[0]
            else replacement_regions
        ),
        "recipe_overrides": (
            [
                _serialize_recipe_override_for_worker(item)
                for item in recipe_overrides
            ]
            if recipe_overrides is not None
            else None
        ),
        "recipe_override_masks_path": recipe_override_masks_path,
        "height_mode": height_mode,
        "heightmap_path": heightmap_path,
        "free_color_set": free_color_set,
        "matched_rgb_path": matched_rgb_path,
        "original_matched_rgb_path": original_matched_rgb_path,
        "height_identity_rgb_path": height_identity_rgb_path,
        "mask_solid_path": mask_solid_path,
        "material_matrix_path": material_matrix_path,
        "original_material_matrix_path": original_material_matrix_path,
        "quantized_image_path": quantized_image_path,
        "reuse_preview_analysis": (
            REQUIRED_PREVIEW_ANALYSIS_REUSE
            if request.use_cached_matched_rgb and not edit_projection_required
            else reuse_preview_analysis
        ),
        "edit_projection": edit_projection,
        "preview_glb_path": preview_glb_path,
        "vector_parse_clip_cache_path": vector_parse_clip_cache_path,
        "material_source": session_material_source,
        "materials_dir": session_data.get("project_materials_dir"),
        "material_dynamic_layer_count_enabled": dynamic_material_settings[0],
        "material_min_layer_count": dynamic_material_settings[1],
        "material_max_layer_count": dynamic_material_settings[2],
        "material_delta_e00_tolerance": dynamic_material_settings[3],
    }
    if session_material_source == "material_archive":
        selected_materials = session_data.get("selected_materials") or []
        params["selected_materials"] = selected_materials
        params["material_layer_count"] = session_data.get("material_layer_count")
        params["material_layer_height_mm"] = session_data.get("material_layer_height_mm")
        # Plumb the opt-in exhaustive-cache grid_resolution from preview time
        # so the 3MF generation path hits the same cache file the user built
        # in the dialog. ``None`` keeps the backend's low-tier default.
        # 把预览阶段确定的穷举缓存网格分辨率透传过来，让 3MF 生成命中用户
        # 在弹窗里实际构建的那份缓存文件。``None`` 表示走低档默认。
        params["material_grid_resolution"] = session_data.get(
            "material_grid_resolution"
        )
        params["material_backing_material_index"] = _resolve_session_material_backing_index(
            session_data,
            request,
        )

    worker_fn = worker_generate_model
    worker_params = params
    if _should_use_model_surface_overlay(session_data):
        if request.backing_output != "same_project":
            raise HTTPException(status_code=422, detail="Independent backing projects are not supported for model surface generation.")
        if request.backing_infill_density_percent < 100:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Sparse backing infill is not supported for model surface "
                    "generation; use 100% backing infill."
                ),
            )
        worker_fn = worker_generate_model_surface_overlay
        worker_params = _prepare_model_surface_overlay_worker_params(
            session_data,
            params,
        )

    # Detach worker scalars and nested edit metadata from the live SessionStore
    # object. Cache arrays are already represented by immutable artifact/temp
    # paths at this point; this copy prevents later free-colour, recipe, or
    # material-list mutations from changing an enqueued generation request.
    worker_params = deepcopy(worker_params)

    # Re-read the authoritative editor revision after all scalar fields and
    # immutable worker paths have been assembled. If an edit landed during
    # assembly, reject the mixed snapshot before enqueueing the worker.
    _assert_editor_snapshot_current(
        store,
        body.session_id,
        committed_content_revision,
        expected_selection_revision=committed_selection_revision,
    )

    # 3. CPU computation offloaded to process pool (only paths and scalars)
    worker_t0 = time.perf_counter()
    try:
        result, worker_pool_timing = await pool.submit_timed(
            worker_fn,
            image_path,
            lut_path,
            worker_params,
        )
    except (WipeTowerLayoutError, NativeMaterialSelectionError, ExternalSpoolSelectionError, TemplateSlotCapacityError) as exc:
        raise to_http_exception(exc, "3MF layout") from exc
    except ModelSurfaceError as exc:
        detail = public_model_surface_error_detail(exc)
        if detail is None:
            raise HTTPException(
                status_code=500,
                detail=MODEL_GENERATION_FAILED_DETAIL,
            ) from exc
        raise HTTPException(status_code=422, detail=detail) from exc
    except (DynamicMaterialCandidateError, DynamicMaterialSolverError) as exc:
        _handle_core_error(exc, "3MF generation")
    except CachedPreviewAnalysisError as exc:
        raise HTTPException(
            status_code=409,
            detail=STANDARD_CACHED_ANALYSIS_INVALID_DETAIL,
        ) from exc
    except BrokenProcessPool as exc:
        raise HTTPException(
            status_code=503,
            detail=MODEL_GENERATION_FAILED_DETAIL,
        ) from exc
    except ROUTER_HANDLED_ERRORS as exc:
        raise HTTPException(
            status_code=500,
            detail=MODEL_GENERATION_FAILED_DETAIL,
        ) from exc
    worker_elapsed = time.perf_counter() - worker_t0

    # 4. Result processing (I/O + FileRegistry, main thread)
    threemf_path: str | None = result.get("threemf_path")
    glb_path: str | None = result.get("glb_path")
    status_msg: str = result.get("status_msg", "")
    glb_reuses_preview_path = _paths_refer_to_same_file(
        glb_path,
        preview_glb_path,
    )

    if not threemf_path or not os.path.exists(threemf_path):
        if glb_path and not glb_reuses_preview_path:
            _remove_temp_path(glb_path)
            glb_path = None
        uses_surface_overlay = _should_use_model_surface_overlay(session_data)
        raise _model_generation_failure_exception(
            status_msg,
            source_is_user_upload=(
                not uses_surface_overlay and not generated_color_card_svg
            ),
            modeling_mode=request.modeling_mode.value,
            source_path=image_path,
            surface_overlay=uses_surface_overlay,
        )

    try:
        _assert_editor_snapshot_current(
            store,
            body.session_id,
            committed_content_revision,
            expected_selection_revision=committed_selection_revision,
            allow_missing_session=True,
        )
    except HTTPException:
        _remove_temp_path(threemf_path)
        if glb_path and not glb_reuses_preview_path:
            _remove_temp_path(glb_path)
        raise

    placement_warnings = read_wipe_tower_placement_warnings(threemf_path)

    # Register output files via FileRegistry
    sid = body.session_id
    preview_3d_url: str | None = None
    download_id: str | None = None
    registration_complete = False
    try:
        try:
            download_filename = None
            if (
                body.preserve_upload_filename_for_3mf
                and not generated_color_card_svg
            ):
                download_filename = generate_preserved_upload_3mf_filename(
                    session_data.get("source_basename")
                )
                download_filename = str(Path(download_filename).with_suffix(Path(threemf_path).suffix))
            embed_generated_project(threemf_path, request.project_revision_file_id, registry)
            download_id = registry.register_path(
                str(uuid.uuid4()),
                threemf_path,
                filename=download_filename,
                ttl_seconds=BATCH_DOWNLOAD_TTL_SECONDS,
            )
        except ROUTER_HANDLED_ERRORS as exc:
            _safe_log(
                "error",
                "converter_generate_download_registration_failed",
                session_id=sid,
                artifact_role="threemf_download",
                error_type=type(exc).__name__,
                error_message=str(exc),
                path=threemf_path,
            )
            raise HTTPException(
                status_code=500,
                detail=MODEL_GENERATION_FAILED_DETAIL,
            ) from exc

        if glb_reuses_preview_path:
            latest_session_data = store.get(sid)
            latest_cache_value = (
                latest_session_data.get("preview_cache")
                if isinstance(latest_session_data, dict)
                else None
            )
            if isinstance(latest_cache_value, dict):
                latest_cache = (
                    get_preview_cache_metadata(latest_cache_value)
                    if is_preview_cache_artifact_ref(latest_cache_value)
                    else latest_cache_value
                )
                current_preview = _resolve_registered_preview_glb(
                    cache=latest_cache,
                    sid=sid,
                    registry=registry,
                )
                if current_preview is not None and _paths_refer_to_same_file(
                    current_preview[1],
                    glb_path,
                ):
                    preview_3d_url = current_preview[0]
            log.debug(
                "Generated model reused the registered preview GLB",
                extra={
                    "event": "converter_generate_glb_reused",
                    "session_id": sid,
                    "preview_url_current": preview_3d_url is not None,
                },
            )
        registration_complete = True
    finally:
        if download_id is None:
            _remove_temp_path(threemf_path)
        elif not registration_complete:
            with suppress(Exception):
                registry.cleanup_file(download_id)
        if glb_path and not glb_reuses_preview_path:
            _remove_temp_path(glb_path)

    api_total = time.perf_counter() - api_t0
    endpoint_to_enqueue_ms = round((worker_t0 - api_t0) * 1000, 3)
    performance_timing = {
        "total_ms": round(api_total * 1000, 3),
        "worker_ms": round(worker_elapsed * 1000, 3),
        "endpoint_to_enqueue_ms": endpoint_to_enqueue_ms,
        "queue_wait_ms": round(
            float(worker_pool_timing.get("queue_wait_s", 0.0)) * 1000,
            3,
        ),
        "worker_execution_ms": round(
            float(worker_pool_timing.get("worker_execution_s", 0.0)) * 1000,
            3,
        ),
        "result_delivery_ms": round(
            float(worker_pool_timing.get("result_delivery_s", 0.0)) * 1000,
            3,
        ),
        "endpoint_post_worker_ms": round(
            max(
                0.0,
                api_total - (worker_t0 - api_t0) - worker_elapsed,
            )
            * 1000,
            3,
        ),
        "overhead_ms": round((api_total - worker_elapsed) * 1000, 3),
    }
    log.info(
        "Generate endpoint timing",
        extra={
            "event": "converter_generate_timing",
            "duration_ms": performance_timing["total_ms"],
            "worker_ms": performance_timing["worker_ms"],
            "endpoint_to_enqueue_ms": performance_timing[
                "endpoint_to_enqueue_ms"
            ],
            "queue_wait_ms": performance_timing["queue_wait_ms"],
            "worker_execution_ms": performance_timing[
                "worker_execution_ms"
            ],
            "result_delivery_ms": performance_timing[
                "result_delivery_ms"
            ],
            "endpoint_post_worker_ms": performance_timing[
                "endpoint_post_worker_ms"
            ],
            "overhead_ms": performance_timing["overhead_ms"],
        },
    )

    if session_material_source == "material_archive":
        _record_material_archive_usage_safe(
            selected_materials=session_data.get("selected_materials"),
            color_mode=request.color_mode,
        )

    return GenerateResponse(
        status="ok",
        message=status_msg or "Model generated",
        download_url=f"/api/files/{download_id}",
        preview_3d_url=preview_3d_url,
        threemf_disk_path=None,
        warnings=placement_warnings,
        performance_timing=performance_timing,
        editor_content_revision=committed_content_revision,
        selection_revision=committed_selection_revision,
    )


# ---------------------------------------------------------------------------
# Large-format tiled generation
# ---------------------------------------------------------------------------


class _LargeFormatBody(BaseModel):
    """Wrapper combining session_id with large-format parameters."""

    session_id: str
    params: LargeFormatGenerateRequest


def _resolve_large_format_dimensions(
    cache: dict,
    request,
    target_height_mm: float | None,
) -> tuple[float, float]:
    ratio_w = float(cache.get("target_w") or 0.0)
    ratio_h = float(cache.get("target_h") or 0.0)
    if (
        not math.isfinite(ratio_w)
        or not math.isfinite(ratio_h)
        or ratio_w <= 0
        or ratio_h <= 0
    ):
        raise HTTPException(status_code=409, detail="Preview cache is missing valid aspect ratio data.")

    aspect_ratio = ratio_w / ratio_h
    requested_width = request.target_width_mm
    requested_height = target_height_mm

    if requested_width is None and requested_height is None:
        raise HTTPException(
            status_code=422,
            detail="Large-format generation requires width or height. Provide at least one dimension.",
        )

    if requested_width is None:
        requested_width = round(float(requested_height) * aspect_ratio, 4)
    elif requested_height is None:
        requested_height = round(float(requested_width) / aspect_ratio, 4)
    else:
        expected_height = float(requested_width) / aspect_ratio
        if abs(float(requested_height) - expected_height) > 1.0:
            raise HTTPException(
                status_code=422,
                detail="Provided width and height do not match the preview aspect ratio.",
            )

    resolved_width = float(requested_width)
    resolved_height = float(requested_height)
    for name, value in (
        ("width", resolved_width),
        ("height", resolved_height),
    ):
        if (
            not math.isfinite(value)
            or value <= 0
        ):
            raise HTTPException(
                status_code=422,
                detail=f"Large-format {name} must be finite and positive.",
            )

    return resolved_width, resolved_height


def _resolve_relief_global_max_height(session_data: dict, request) -> float | None:
    relief_global_max_height: float | None = None
    if request.enable_relief:
        height_mode = request.height_mode or "color"
        if height_mode == "color" and request.color_height_map:
            relief_global_max_height = max(request.color_height_map.values())
        elif height_mode == "heightmap":
            hm_gray = session_data.get("heightmap_grayscale")
            if hm_gray is not None:
                hm_max_cfg = request.heightmap_max_height if request.heightmap_max_height else 5.0
                relief_global_max_height = float(hm_max_cfg)
    return relief_global_max_height


def _require_heightmap_for_relief(session_data: dict, request) -> None:
    """Reject heightmap relief generation when the session heightmap cache is gone.

    拒绝缺少 session 高度图缓存的高度图浮雕生成，避免静默退回平面模型。
    """
    if not request.enable_relief:
        return
    if (request.height_mode or "color") != "heightmap":
        return
    if session_data.get("heightmap_grayscale") is None:
        raise HTTPException(
            status_code=409,
            detail="Heightmap missing. Upload heightmap before generating relief models.",
        )


def _resolve_large_format_shared_params(
    session_data: dict,
    request,
    relief_global_max_height: float | None,
    *,
    dynamic_material_settings: tuple[bool, int, int, float] = (
        False,
        5,
        10,
        0.5,
    ),
    recipe_overrides: list[dict[str, object]] | None = None,
    recipe_override_masks_path: str | None = None,
    matched_rgb_path: str | None = None,
    mask_solid_path: str | None = None,
    material_matrix_path: str | None = None,
    quantized_image_path: str | None = None,
    cached_analysis_is_final: bool = False,
    final_material_matrix_is_authoritative: bool = False,
    final_material_matrix_authority_mask_path: str | None = None,
) -> dict:
    replacement_regions = session_data.get("replacement_regions") or None
    if request.replacement_regions is not None:
        replacement_regions = [
            {"quantized_hex": r.quantized_hex, "matched_hex": r.matched_hex, "replacement_hex": r.replacement_hex}
            for r in request.replacement_regions
        ]
    if cached_analysis_is_final:
        replacement_regions = None
    free_color_set = session_data.get("free_color_set") or None
    if request.free_color_set is not None:
        free_color_set = request.free_color_set

    params = {
        **build_generation_worker_params(request),
        "modeling_mode": CoreModelingMode(request.modeling_mode.value),
        "replacement_regions": replacement_regions,
        "recipe_overrides": (
            [
                _serialize_recipe_override_for_worker(item)
                for item in recipe_overrides
            ]
            if recipe_overrides is not None
            else None
        ),
        "recipe_override_masks_path": recipe_override_masks_path,
        "height_mode": request.height_mode or "color",
        "free_color_set": free_color_set,
        "matched_rgb_path": matched_rgb_path,
        "mask_solid_path": mask_solid_path,
        "material_matrix_path": material_matrix_path,
        "quantized_image_path": quantized_image_path,
        "final_material_matrix_is_authoritative": (
            final_material_matrix_is_authoritative
        ),
        "final_material_matrix_authority_mask_path": (
            final_material_matrix_authority_mask_path
        ),
        "relief_global_max_height": relief_global_max_height,
        "material_dynamic_layer_count_enabled": dynamic_material_settings[0],
        "material_min_layer_count": dynamic_material_settings[1],
        "material_max_layer_count": dynamic_material_settings[2],
        "material_delta_e00_tolerance": dynamic_material_settings[3],
    }
    if str(session_data.get("material_source") or "lut") == "material_archive":
        params["materials_dir"] = session_data.get("project_materials_dir")
        params["material_source"] = "material_archive"
        params["selected_materials"] = session_data.get("selected_materials") or []
        params["material_layer_count"] = session_data.get("material_layer_count")
        params["material_layer_height_mm"] = session_data.get("material_layer_height_mm")
        params["material_grid_resolution"] = session_data.get(
            "material_grid_resolution"
        )
        resolved_backing_idx = _resolve_session_material_backing_index(
            session_data,
            request,
        )
        params["material_backing_material_index"] = resolved_backing_idx
    return params


def _resolve_large_format_source_basename(session_data: dict, image_path: str) -> str:
    source_basename = normalize_large_format_source_basename(session_data.get("source_basename"))
    if source_basename:
        return source_basename
    return normalize_large_format_source_basename(os.path.splitext(os.path.basename(image_path))[0])


def _validated_large_format_axis_boundaries(
    *,
    total_mm: float,
    tile_mm: float,
    source_pixels: int,
    cache_pixels: int,
) -> tuple[list[int], list[int]]:
    """Project every physical tile boundary onto source and cache grids."""

    tile_count = resolve_large_format_axis_count(total_mm, tile_mm)
    physical_boundaries_mm = [
        min(index * tile_mm, total_mm)
        for index in range(tile_count + 1)
    ]

    def _project(pixel_extent: int) -> list[int]:
        return [
            min(int(round(boundary_mm * pixel_extent / total_mm)), pixel_extent)
            for boundary_mm in physical_boundaries_mm
        ]

    source_boundaries = _project(source_pixels)
    cache_boundaries = _project(cache_pixels)
    if any(
        current <= previous
        for boundaries in (source_boundaries, cache_boundaries)
        for previous, current in zip(boundaries, boundaries[1:])
    ):
        raise HTTPException(
            status_code=409,
            detail=LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL,
        )
    return source_boundaries, cache_boundaries


async def _generate_large_format_svg_native(
    *,
    image_path: str,
    lut_path: str,
    source_basename: str,
    recipe_overrides: list[dict[str, object]] | None,
    recipe_override_masks_path: str | None,
    material_matrix_path: str | None,
    matched_rgb_path: str | None = None,
    mask_solid_path: str | None = None,
    total_width_mm: float,
    total_height_mm: float,
    tile_width_mm: float,
    tile_height_mm: float,
    request,
    session_data: dict,
    sid: str,
    store: SessionStore,
    registry: FileRegistry,
    pool: WorkerPoolManager,
    dynamic_material_settings: tuple[bool, int, int, float] = (
        False,
        5,
        10,
        0.5,
    ),
    warnings: list[str] | None = None,
    base_channel_idx: int = 0,
) -> dict:
    shared_params = _resolve_large_format_shared_params(
        session_data,
        request,
        _resolve_relief_global_max_height(session_data, request),
        dynamic_material_settings=dynamic_material_settings,
        recipe_overrides=recipe_overrides,
        recipe_override_masks_path=recipe_override_masks_path,
        matched_rgb_path=matched_rgb_path,
        mask_solid_path=mask_solid_path,
        material_matrix_path=material_matrix_path,
        cached_analysis_is_final=all(
            path is not None
            for path in (
                matched_rgb_path,
                mask_solid_path,
                material_matrix_path,
            )
        ),
    )
    shared_params["base_channel_idx"] = int(base_channel_idx)
    native_heightmap_path: str | None = None
    if request.enable_relief and (request.height_mode or "color") == "heightmap":
        heightmap_grayscale = session_data.get("heightmap_grayscale")
        if heightmap_grayscale is None:
            raise HTTPException(
                status_code=422,
                detail="Heightmap is required when heightmap relief is enabled.",
            )
        fd, native_heightmap_path = tempfile.mkstemp(suffix=".png", dir=TEMP_DIR)
        os.close(fd)
        try:
            Image.fromarray(heightmap_grayscale).save(native_heightmap_path)
        except (OSError, ValueError, TypeError):
            _remove_temp_path(native_heightmap_path)
            raise
        shared_params["heightmap_path"] = native_heightmap_path
    try:
        try:
            result = await pool.submit(
                worker_generate_large_format_svg_native,
                image_path,
                lut_path,
                {
                    **shared_params,
                    "tile_name_prefix": source_basename,
                    "total_width_mm": total_width_mm,
                    "total_height_mm": total_height_mm,
                    "tile_width_mm": tile_width_mm,
                    "tile_height_mm": tile_height_mm,
                },
            )
        finally:
            _remove_temp_path(native_heightmap_path)
    except (WipeTowerLayoutError, NativeMaterialSelectionError, ExternalSpoolSelectionError, TemplateSlotCapacityError) as exc:
        raise to_http_exception(exc, "large-format 3MF layout") from exc
    except LargeFormatCachedAnalysisError as e:
        _log_large_format_failure(
            session_id=sid,
            failure_kind="cached_analysis",
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise HTTPException(
            status_code=409,
            detail=LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL,
        ) from e
    except (DynamicMaterialCandidateError, DynamicMaterialSolverError) as e:
        _handle_core_error(e, "large-format SVG generation")
    except BrokenProcessPool as e:
        _log_large_format_failure(
            session_id=sid,
            failure_kind="svg_native_worker_pool_broken",
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise HTTPException(
            status_code=503,
            detail=LARGE_FORMAT_GENERATION_FAILED_DETAIL,
        ) from e
    except ROUTER_HANDLED_ERRORS as e:
        _log_large_format_failure(
            session_id=sid,
            failure_kind="svg_native_worker",
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise HTTPException(status_code=500, detail=LARGE_FORMAT_GENERATION_FAILED_DETAIL)
    zip_path = result["zip_path"]
    zip_registered = False
    try:
        try:
            embed_generated_project(zip_path, getattr(request, "project_revision_file_id", None), registry)
            download_id = registry.register_path(
                str(uuid.uuid4()),
                zip_path,
                ttl_seconds=BATCH_DOWNLOAD_TTL_SECONDS,
            )
        except ROUTER_HANDLED_ERRORS as exc:
            _log_large_format_failure(
                session_id=sid,
                failure_kind="zip_registration",
                error_type=type(exc).__name__,
                error_message=str(exc),
                artifact_role="download_zip",
                path=zip_path,
            )
            raise HTTPException(
                status_code=500,
                detail=LARGE_FORMAT_GENERATION_FAILED_DETAIL,
            ) from exc
        zip_registered = True
    finally:
        if not zip_registered:
            _remove_temp_path(zip_path)
    return {
        "status": "ok",
        "message": f"Generated {result['tile_count']}/{result['grid_cols'] * result['grid_rows']} tiles ({result['grid_cols']}×{result['grid_rows']})",
        "download_url": f"/api/files/{download_id}",
        "tile_count": result["tile_count"],
        "grid_cols": result["grid_cols"],
        "grid_rows": result["grid_rows"],
        "warnings": list(warnings or []) + list(result.get("warnings", [])),
    }


def _discard_pending_awaitables(awaitables: list, start_index: int) -> None:
    """Cancel or close unconsumed tile submissions after a fatal failure."""

    for pending in awaitables[max(0, int(start_index)) :]:
        cancel = getattr(pending, "cancel", None)
        if callable(cancel):
            cancel()
            continue
        close = getattr(pending, "close", None)
        if callable(close):
            close()


def _rasterize_svg_fallback_tile(
    *,
    svg_path: str,
    total_width_mm: float,
    total_height_mm: float,
    x0_mm: float,
    y0_mm: float,
    x1_mm: float,
    y1_mm: float,
    pixels_per_mm: float,
) -> str:
    """Rasterize one SVG fallback tile without allocating a full canvas.

    将 SVG fallback 直接按全局毫米坐标裁成一个 tile，避免先创建整幅
    大画幅位图；原 SVG 作为嵌套 viewport 保留完整 viewBox 和百分比布局，
    外层 viewport 只负责裁切输出窗口。
    """

    tree = ET.parse(svg_path)
    source_root = tree.getroot()

    viewport_width = _parse_svg_length_to_px(source_root.attrib.get("width"))
    viewport_height = _parse_svg_length_to_px(source_root.attrib.get("height"))
    raw_view_box = source_root.attrib.get("viewBox") or source_root.attrib.get("viewbox")
    if not raw_view_box:
        if viewport_width is None or viewport_height is None:
            raise ValueError("SVG fallback requires a viewBox or finite canvas dimensions")
        raw_view_box = f"0 0 {viewport_width:g} {viewport_height:g}"
    try:
        view_box = [float(value) for value in raw_view_box.replace(",", " ").split()]
    except (TypeError, ValueError):
        view_box = []
    if len(view_box) != 4 or view_box[2] <= 0 or view_box[3] <= 0:
        raise ValueError("SVG fallback viewBox must contain positive dimensions")
    view_x, view_y, view_w, view_h = view_box
    viewport_width = viewport_width or view_w
    viewport_height = viewport_height or view_h
    scale_x = viewport_width / float(total_width_mm)
    scale_y = viewport_height / float(total_height_mm)
    tile_view_box = (
        x0_mm * scale_x,
        y0_mm * scale_y,
        max((x1_mm - x0_mm) * scale_x, 1e-9),
        max((y1_mm - y0_mm) * scale_y, 1e-9),
    )

    # Keep the original document as a nested viewport. Changing the original
    # root's viewBox would make percentage geometry resolve against the tile
    # and would change the actual SVG layout (for example, a 50% blue panel
    # would become 100% of the right tile). The outer viewport clips the full
    # document to the requested global window instead.
    nested_root = ET.Element(source_root.tag, dict(source_root.attrib))
    nested_root.attrib["x"] = "0"
    nested_root.attrib["y"] = "0"
    nested_root.attrib["width"] = f"{viewport_width:.12g}"
    nested_root.attrib["height"] = f"{viewport_height:.12g}"
    nested_root.attrib["viewBox"] = " ".join(
        f"{value:.12g}" for value in (view_x, view_y, view_w, view_h)
    )
    nested_root.attrib.pop("viewbox", None)
    for child in list(source_root):
        nested_root.append(child)

    ET.register_namespace("", "http://www.w3.org/2000/svg")
    outer_root = ET.Element(
        source_root.tag,
        {
            "width": f"{max(x1_mm - x0_mm, 1e-9):.12g}mm",
            "height": f"{max(y1_mm - y0_mm, 1e-9):.12g}mm",
            "viewBox": " ".join(f"{value:.12g}" for value in tile_view_box),
            "overflow": "hidden",
        },
    )
    outer_root.append(nested_root)
    tree._setroot(outer_root)

    svg_fd, tile_svg_path = tempfile.mkstemp(suffix=".svg", dir=TEMP_DIR)
    os.close(svg_fd)
    png_path: str | None = None
    try:
        tree.write(tile_svg_path, encoding="utf-8", xml_declaration=True)
        rgba = rasterize_svg(
            tile_svg_path,
            max(x1_mm - x0_mm, 1e-9),
            pixels_per_mm=float(pixels_per_mm),
            crop_to_content=False,
            _min_quality_px=1,
            _cache_result=False,
        )
        png_fd, png_path = tempfile.mkstemp(suffix=".png", dir=TEMP_DIR)
        os.close(png_fd)
        Image.fromarray(rgba).save(png_path)
        return png_path
    except BaseException:
        if png_path is not None:
            _remove_temp_path(png_path)
        raise
    finally:
        _remove_temp_path(tile_svg_path)


async def _generate_large_format_raster(
    *,
    image_path: str | None,
    svg_fallback_path: str | None = None,
    lut_path: str,
    source_basename: str,
    recipe_overrides: list[dict[str, object]] | None,
    recipe_override_masks_path: str | None,
    material_matrix_path: str | None,
    matched_rgb_path: str | None = None,
    mask_solid_path: str | None = None,
    quantized_image_path: str | None = None,
    final_material_matrix_is_authoritative: bool = False,
    total_width_mm: float,
    total_height_mm: float,
    tile_width_mm: float,
    tile_height_mm: float,
    request,
    session_data: dict,
    sid: str,
    store: SessionStore,
    registry: FileRegistry,
    pool: WorkerPoolManager,
    dynamic_material_settings: tuple[bool, int, int, float] = (
        False,
        5,
        10,
        0.5,
    ),
    warnings: list[str] | None = None,
    log_tile_failures: bool = True,
) -> dict:
    full_img: Image.Image | None = None
    px_w = px_h = 0
    if image_path is not None:
        with Image.open(image_path) as img:
            px_w, px_h = img.size
            full_img = img.copy()
    elif svg_fallback_path is None:
        raise ValueError("Large-format raster generation requires an image or SVG source")

    successful_paths: list[tuple[str, str]] = []
    tile_warnings: list[str] = []
    route_local_cleanup_paths: set[str] = set()
    cleanup_paths: set[str] = set()
    errors: list[str] = []
    failed_tiles: list[str] = []
    zip_path: str | None = None
    zip_ready = False
    full_matched_rgb: np.ndarray | None = None
    full_mask_solid: np.ndarray | None = None
    full_material_matrix: np.ndarray | None = None
    full_quantized_image: np.ndarray | None = None
    full_authoritative_material_mask: np.ndarray | None = None
    spatial_target_w = 0
    spatial_target_h = 0
    cached_analysis_requested = any(
        path is not None
        for path in (
            matched_rgb_path,
            mask_solid_path,
            quantized_image_path,
        )
    )
    dynamic_cached_analysis_requested = (
        cached_analysis_requested and dynamic_material_settings[0]
    )
    if cached_analysis_requested and not (
        matched_rgb_path is not None
        and mask_solid_path is not None
        and material_matrix_path is not None
    ):
        raise HTTPException(
            status_code=409,
            detail=LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL,
        )
    if dynamic_cached_analysis_requested and quantized_image_path is None:
        raise HTTPException(
            status_code=409,
            detail=LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL,
        )

    if material_matrix_path is not None:
        loading_role = "material_matrix"
        loading_path = material_matrix_path
        try:
            if cached_analysis_requested:
                loading_role = "matched_rgb"
                loading_path = matched_rgb_path
                full_matched_rgb = np.load(matched_rgb_path, allow_pickle=False)
                loading_role = "mask_solid"
                loading_path = mask_solid_path
                full_mask_solid = np.load(mask_solid_path, allow_pickle=False)
                if dynamic_cached_analysis_requested:
                    loading_role = "quantized_image"
                    loading_path = quantized_image_path
                    full_quantized_image = np.load(
                        quantized_image_path,
                        allow_pickle=False,
                    )
            loading_role = "material_matrix"
            loading_path = material_matrix_path
            full_material_matrix = np.load(material_matrix_path, allow_pickle=False)
        except (OSError, ValueError, TypeError) as exc:
            _log_large_format_failure(
                session_id=sid,
                failure_kind=(
                    "cached_analysis"
                    if cached_analysis_requested
                    else "recipe_override_matrix"
                ),
                error_type=type(exc).__name__,
                error_message=str(exc),
                artifact_role=loading_role,
                path=loading_path,
            )
            raise HTTPException(
                status_code=409 if cached_analysis_requested else 500,
                detail=(
                    LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL
                    if cached_analysis_requested
                    else LARGE_FORMAT_RECIPE_OVERRIDE_LOAD_FAILED_DETAIL
                ),
            ) from exc

        if cached_analysis_requested:
            cached_analysis_valid = (
                isinstance(full_matched_rgb, np.ndarray)
                and full_matched_rgb.ndim == 3
                and full_matched_rgb.shape[2] == 3
                and full_matched_rgb.dtype == np.uint8
                and isinstance(full_mask_solid, np.ndarray)
                and full_mask_solid.ndim == 2
                and full_mask_solid.dtype == np.bool_
                and isinstance(full_material_matrix, np.ndarray)
                and full_material_matrix.ndim == 3
                and full_material_matrix.shape[2] > 0
                and np.issubdtype(full_material_matrix.dtype, np.integer)
                and full_matched_rgb.shape[:2] == full_mask_solid.shape
                and full_material_matrix.shape[:2] == full_mask_solid.shape
                and (
                    not dynamic_cached_analysis_requested
                    or (
                        isinstance(full_quantized_image, np.ndarray)
                        and full_quantized_image.ndim == 3
                        and full_quantized_image.shape[2] == 3
                        and full_quantized_image.dtype == np.uint8
                        and full_quantized_image.shape[:2]
                        == full_mask_solid.shape
                    )
                )
                and (
                    not dynamic_cached_analysis_requested
                    or (
                        full_material_matrix.dtype == np.int32
                        and full_material_matrix.shape[2]
                        == dynamic_material_settings[2]
                    )
                )
            )
            if not cached_analysis_valid:
                raise HTTPException(
                    status_code=409,
                    detail=LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL,
                )
        elif not isinstance(full_material_matrix, np.ndarray) or full_material_matrix.ndim != 3:
            raise HTTPException(
                status_code=500,
                detail="Large-format recipe override matrix must be 3-dimensional",
            )

        spatial_target_h, spatial_target_w = full_material_matrix.shape[:2]

    # The final material matrix already contains every recipe override, but a
    # recipe-only artifact does not necessarily contain imported global color
    # mappings outside those regions. Merge the original masks into one
    # authority mask; each tile worker will restore only those recipe pixels
    # after applying global/scoped mappings. We still do not pass the legacy
    # per-region mask pickle, so recipes are not recomputed a second time.
    if recipe_overrides and recipe_override_masks_path is not None:
        try:
            with open(recipe_override_masks_path, "rb") as f:
                loaded_masks = pickle.load(f)
            if cached_analysis_requested:
                # A complete cached trio owns the whole matrix, so preserve
                # the legacy contract: deserialize masks only as a corruption
                # check and do not make their shape a new prerequisite.
                if isinstance(loaded_masks, dict):
                    for mask in loaded_masks.values():
                        np.asarray(mask, dtype=bool)
            else:
                if not isinstance(loaded_masks, dict) or not loaded_masks:
                    raise ValueError(
                        "Recipe override masks must be a non-empty mapping"
                    )
                if full_material_matrix is None:
                    raise ValueError("Recipe override material matrix is missing")
                full_authoritative_material_mask = np.zeros(
                    full_material_matrix.shape[:2],
                    dtype=bool,
                )
                for mask in loaded_masks.values():
                    mask_array = np.asarray(mask, dtype=bool)
                    if mask_array.shape != full_material_matrix.shape[:2]:
                        raise ValueError(
                            "Recipe override mask shape does not match material matrix"
                        )
                    full_authoritative_material_mask |= mask_array
        except (OSError, ValueError, TypeError, pickle.PickleError) as exc:
            _log_large_format_failure(
                session_id=sid,
                failure_kind="recipe_override_masks",
                error_type=type(exc).__name__,
                error_message=str(exc),
                artifact_role="recipe_override_masks",
                path=recipe_override_masks_path,
            )
            raise HTTPException(
                status_code=500,
                detail=LARGE_FORMAT_RECIPE_OVERRIDE_LOAD_FAILED_DETAIL,
            ) from exc

    px_per_mm_x = px_w / total_width_mm if px_w else 0.0
    px_per_mm_y = px_h / total_height_mm if px_h else 0.0
    cols, rows = resolve_large_format_grid_shape(
        total_width_mm=total_width_mm,
        total_height_mm=total_height_mm,
        tile_width_mm=tile_width_mm,
        tile_height_mm=tile_height_mm,
    )
    source_x_boundaries: list[int] | None = None
    source_y_boundaries: list[int] | None = None
    cache_x_boundaries: list[int] | None = None
    cache_y_boundaries: list[int] | None = None
    if cached_analysis_requested:
        source_x_boundaries, cache_x_boundaries = (
            _validated_large_format_axis_boundaries(
                total_mm=total_width_mm,
                tile_mm=tile_width_mm,
                source_pixels=px_w,
                cache_pixels=spatial_target_w,
            )
        )
        source_y_boundaries, cache_y_boundaries = (
            _validated_large_format_axis_boundaries(
                total_mm=total_height_mm,
                tile_mm=tile_height_mm,
                source_pixels=px_h,
                cache_pixels=spatial_target_h,
            )
        )
    shared_params = _resolve_large_format_shared_params(
        session_data,
        request,
        _resolve_relief_global_max_height(session_data, request),
        dynamic_material_settings=dynamic_material_settings,
        recipe_overrides=recipe_overrides,
        recipe_override_masks_path=None,
        matched_rgb_path=None,
        mask_solid_path=None,
        material_matrix_path=None,
        quantized_image_path=None,
        cached_analysis_is_final=cached_analysis_requested,
        final_material_matrix_is_authoritative=(
            final_material_matrix_is_authoritative
            or cached_analysis_requested
        ),
        final_material_matrix_authority_mask_path=None,
    )
    shared_params["reuse_preview_analysis"] = False
    if (
        (
            svg_fallback_path is not None
            or (image_path is not None and str(image_path).lower().endswith(".png"))
        )
        and shared_params["modeling_mode"] == CoreModelingMode.VECTOR
    ):
        shared_params["modeling_mode"] = CoreModelingMode.HIGH_FIDELITY
    hm_gray = (
        session_data.get("heightmap_grayscale")
        if (request.enable_relief and (request.height_mode or "color") == "heightmap")
        else None
    )

    try:
        futures = []
        tile_labels: list[str] = []
        tile_ids: list[str] = []
        for r in range(rows):
            for c in range(cols):
                x0_mm = c * tile_width_mm
                y0_mm = r * tile_height_mm
                x1_mm = min(x0_mm + tile_width_mm, total_width_mm)
                y1_mm = min(y0_mm + tile_height_mm, total_height_mm)
                cur_tile_w = x1_mm - x0_mm

                source_px_x0 = source_px_x1 = source_px_y0 = source_px_y1 = 0
                if svg_fallback_path is not None:
                    tile_path = _rasterize_svg_fallback_tile(
                        svg_path=svg_fallback_path,
                        total_width_mm=total_width_mm,
                        total_height_mm=total_height_mm,
                        x0_mm=x0_mm,
                        y0_mm=y0_mm,
                        x1_mm=x1_mm,
                        y1_mm=y1_mm,
                        pixels_per_mm=float(
                            getattr(request, "svg_pixels_per_mm", SVG_PIXELS_PER_MM_DEFAULT)
                        ),
                    )
                    route_local_cleanup_paths.add(tile_path)
                elif source_x_boundaries is not None:
                    source_px_x0 = source_x_boundaries[c]
                    source_px_x1 = source_x_boundaries[c + 1]
                else:
                    source_px_x0 = int(round(x0_mm * px_per_mm_x))
                    source_px_x1 = min(int(round(x1_mm * px_per_mm_x)), px_w)
                if source_y_boundaries is not None:
                    source_px_y0 = source_y_boundaries[r]
                    source_px_y1 = source_y_boundaries[r + 1]
                else:
                    source_px_y0 = int(round(y0_mm * px_per_mm_y))
                    source_px_y1 = min(int(round(y1_mm * px_per_mm_y)), px_h)

                heightmap_px_x0 = heightmap_px_x1 = heightmap_px_y0 = heightmap_px_y1 = 0
                if hm_gray is not None:
                    hm_height, hm_width = hm_gray.shape[:2]
                    heightmap_px_x0 = max(
                        0, min(hm_width, int(round(x0_mm * hm_width / total_width_mm)))
                    )
                    heightmap_px_x1 = max(
                        heightmap_px_x0,
                        min(hm_width, int(round(x1_mm * hm_width / total_width_mm))),
                    )
                    heightmap_px_y0 = max(
                        0, min(hm_height, int(round(y0_mm * hm_height / total_height_mm)))
                    )
                    heightmap_px_y1 = max(
                        heightmap_px_y0,
                        min(hm_height, int(round(y1_mm * hm_height / total_height_mm))),
                    )

                if svg_fallback_path is None:
                    if full_img is None:
                        raise RuntimeError("Large-format raster source image is unavailable")
                    tile_img = full_img.crop(
                        (source_px_x0, source_px_y0, source_px_x1, source_px_y1)
                    )
                    fd, tile_path = tempfile.mkstemp(suffix=".png", dir=TEMP_DIR)
                    os.close(fd)
                    tile_img.save(tile_path)
                    route_local_cleanup_paths.add(tile_path)

                tile_params = dict(shared_params, target_width_mm=cur_tile_w)
                if hm_gray is not None:
                    hm_tile = hm_gray[
                        heightmap_px_y0:heightmap_px_y1,
                        heightmap_px_x0:heightmap_px_x1,
                    ]
                    fd2, hm_tile_path = tempfile.mkstemp(suffix=".png", dir=TEMP_DIR)
                    os.close(fd2)
                    Image.fromarray(hm_tile).save(hm_tile_path)
                    route_local_cleanup_paths.add(hm_tile_path)
                    tile_params["heightmap_path"] = hm_tile_path
                if full_material_matrix is not None and spatial_target_w > 0 and spatial_target_h > 0:
                    if cache_x_boundaries is not None:
                        spatial_x0 = cache_x_boundaries[c]
                        spatial_x1 = cache_x_boundaries[c + 1]
                    else:
                        spatial_x0 = int(
                            round(x0_mm * (spatial_target_w / total_width_mm))
                        )
                        spatial_x1 = min(
                            int(
                                round(
                                    x1_mm
                                    * (spatial_target_w / total_width_mm)
                                )
                            ),
                            spatial_target_w,
                        )
                    if cache_y_boundaries is not None:
                        spatial_y0 = cache_y_boundaries[r]
                        spatial_y1 = cache_y_boundaries[r + 1]
                    else:
                        spatial_y0 = int(
                            round(y0_mm * (spatial_target_h / total_height_mm))
                        )
                        spatial_y1 = min(
                            int(
                                round(
                                    y1_mm
                                    * (spatial_target_h / total_height_mm)
                                )
                            ),
                            spatial_target_h,
                        )
                    material_matrix_tile = full_material_matrix[
                        spatial_y0:spatial_y1,
                        spatial_x0:spatial_x1,
                        :,
                    ]
                    fd_mm, mm_tile_path = tempfile.mkstemp(suffix=".npy", dir=TEMP_DIR)
                    os.close(fd_mm)
                    route_local_cleanup_paths.add(mm_tile_path)
                    np.save(mm_tile_path, material_matrix_tile)
                    tile_params["material_matrix_path"] = mm_tile_path
                    tile_params["recipe_override_masks_path"] = None
                    if (
                        final_material_matrix_is_authoritative
                        and not cached_analysis_requested
                        and full_authoritative_material_mask is not None
                    ):
                        authority_mask_tile = full_authoritative_material_mask[
                            spatial_y0:spatial_y1,
                            spatial_x0:spatial_x1,
                        ]
                        fd_authority, authority_mask_tile_path = tempfile.mkstemp(
                            suffix=".npy",
                            dir=TEMP_DIR,
                        )
                        os.close(fd_authority)
                        route_local_cleanup_paths.add(authority_mask_tile_path)
                        np.save(authority_mask_tile_path, authority_mask_tile)
                        tile_params[
                            "final_material_matrix_authority_mask_path"
                        ] = authority_mask_tile_path
                    if full_matched_rgb is not None and full_mask_solid is not None:
                        matched_rgb_tile = full_matched_rgb[
                            spatial_y0:spatial_y1,
                            spatial_x0:spatial_x1,
                            :,
                        ]
                        mask_solid_tile = full_mask_solid[
                            spatial_y0:spatial_y1,
                            spatial_x0:spatial_x1,
                        ]
                        fd_rgb, rgb_tile_path = tempfile.mkstemp(
                            suffix=".npy",
                            dir=TEMP_DIR,
                        )
                        os.close(fd_rgb)
                        route_local_cleanup_paths.add(rgb_tile_path)
                        np.save(rgb_tile_path, matched_rgb_tile)
                        fd_mask, mask_tile_path = tempfile.mkstemp(
                            suffix=".npy",
                            dir=TEMP_DIR,
                        )
                        os.close(fd_mask)
                        route_local_cleanup_paths.add(mask_tile_path)
                        np.save(mask_tile_path, mask_solid_tile)
                        tile_params["matched_rgb_path"] = rgb_tile_path
                        tile_params["mask_solid_path"] = mask_tile_path
                        if full_quantized_image is not None:
                            quantized_image_tile = full_quantized_image[
                                spatial_y0:spatial_y1,
                                spatial_x0:spatial_x1,
                                :,
                            ]
                            fd_quantized, quantized_tile_path = tempfile.mkstemp(
                                suffix=".npy",
                                dir=TEMP_DIR,
                            )
                            os.close(fd_quantized)
                            route_local_cleanup_paths.add(quantized_tile_path)
                            np.save(quantized_tile_path, quantized_image_tile)
                            tile_params["quantized_image_path"] = (
                                quantized_tile_path
                            )
                        tile_params["reuse_preview_analysis"] = True

                label = format_large_format_tile_label(
                    source_basename=source_basename,
                    tile_label=f"R{r + 1}C{c + 1}",
                )
                tile_labels.append(label)
                tile_ids.append(f"R{r + 1}C{c + 1}")
                futures.append(
                    pool.submit(
                        worker_generate_model,
                        tile_path,
                        lut_path,
                        tile_params,
                    )
                )

        for future_index, (label, fut) in enumerate(zip(tile_labels, futures)):
            try:
                result = await fut
                glb_path = result.get("glb_path")
                if glb_path and os.path.exists(glb_path):
                    cleanup_paths.add(glb_path)

                tp = result.get("threemf_path")
                if tp and os.path.exists(tp):
                    successful_paths.append((label, tp))
                    cleanup_paths.add(tp)
                    for warning_code in read_wipe_tower_placement_warnings(tp):
                        if warning_code not in tile_warnings:
                            tile_warnings.append(warning_code)
                else:
                    failed_tiles.append(tile_ids[future_index])
                    errors.append(f"{label}: generation failed — {result.get('status_msg', 'unknown')}")
            except MemoryError:
                _discard_pending_awaitables(futures, future_index + 1)
                raise
            except BrokenProcessPool as e:
                _discard_pending_awaitables(futures, future_index + 1)
                raise HTTPException(
                    status_code=503,
                    detail=LARGE_FORMAT_GENERATION_FAILED_DETAIL,
                ) from e
            except (DynamicMaterialCandidateError, DynamicMaterialSolverError) as e:
                _discard_pending_awaitables(futures, future_index + 1)
                _handle_core_error(e, "large-format tile generation")
            except (WipeTowerLayoutError, NativeMaterialSelectionError, ExternalSpoolSelectionError, TemplateSlotCapacityError) as exc:
                _discard_pending_awaitables(futures, future_index + 1)
                raise to_http_exception(exc, "large-format tile layout") from exc
            except ROUTER_HANDLED_ERRORS as e:
                failed_tiles.append(tile_ids[future_index])
                errors.append(f"{label}: {e}")

        if not successful_paths:
            if log_tile_failures:
                for raw_error in errors[:5]:
                    _log_large_format_failure(
                        session_id=sid,
                        failure_kind="tile_failed",
                        error_type="LargeFormatTileFailure",
                        error_message=raw_error,
                    )
            raise HTTPException(status_code=500, detail=LARGE_FORMAT_GENERATION_FAILED_DETAIL)

        fd, zip_path = tempfile.mkstemp(suffix=".zip", dir=TEMP_DIR)
        os.close(fd)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for label, tp in successful_paths:
                zf.write(tp, f"{label}.3mf")
        try:
            embed_generated_project(zip_path, getattr(request, "project_revision_file_id", None), registry)
            download_id = registry.register_path(
                str(uuid.uuid4()),
                zip_path,
                ttl_seconds=BATCH_DOWNLOAD_TTL_SECONDS,
            )
        except ROUTER_HANDLED_ERRORS as exc:
            _log_large_format_failure(
                session_id=sid,
                failure_kind="zip_registration",
                error_type=type(exc).__name__,
                error_message=str(exc),
                artifact_role="download_zip",
                path=zip_path,
            )
            raise HTTPException(
                status_code=500,
                detail=LARGE_FORMAT_GENERATION_FAILED_DETAIL,
            ) from exc
        zip_ready = True

        msg = f"Generated {len(successful_paths)}/{cols * rows} tiles ({cols}×{rows})"
        if errors:
            msg += f" — {len(errors)} failed"
        return {
            "status": "partial" if failed_tiles else "ok",
            "message": msg,
            "failed_tiles": failed_tiles,
            "download_url": f"/api/files/{download_id}",
            "tile_count": len(successful_paths),
            "grid_cols": cols,
            "grid_rows": rows,
            "warnings": list(dict.fromkeys([*(warnings or []), *tile_warnings])),
        }
    finally:
        _remove_temp_paths(route_local_cleanup_paths)
        _remove_temp_paths(cleanup_paths)
        if zip_path is not None and not zip_ready:
            _remove_temp_path(zip_path)


@router.post("/generate-large-format")
async def convert_generate_large_format(
    body: _LargeFormatBody,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
    pool: WorkerPoolManager = Depends(get_worker_pool),
) -> LargeFormatGenerateResponse:
    """Split image into tiles, generate a 3MF per tile, and package into ZIP.
    将图片切割为网格切片，每片生成 3MF，打包为 ZIP。
    """
    lf = body.params
    request = lf.params
    revision_bytes(request.project_revision_file_id, registry)
    # 1. Session validation and immutable input snapshot
    (
        session_data,
        committed_content_revision,
        committed_selection_revision,
    ) = _capture_generation_snapshot(
        store,
        body.session_id,
        requested_revision=request.editor_content_revision,
        requested_selection_revision=request.selection_revision,
        revision_mismatch_detail=(
            "Visible content changed before large-format generation started; "
            "refresh the editor state and try again."
        ),
    )
    if _should_use_model_surface_overlay(session_data):
        # Tiles are cut from flat artwork, so the uploaded model would be lost.
        raise HTTPException(
            status_code=422,
            detail=LARGE_FORMAT_MODEL_SURFACE_UNSUPPORTED_DETAIL,
        )
    cache, cache_ref = _require_preview_cache_for_generate(session_data)
    validate_export_device_selection(
        printer_id=request.printer_id,
        slicer=request.slicer,
        nozzle_size=request.nozzle_size,
        device_profile_id=request.device_profile_id,
        build_plate_id=request.build_plate_id,
        custom_3mf_template_id=request.custom_3mf_template_id,
        supports_custom_template=True,
    )
    _validate_native_vector_relief_compatibility(request)
    require_material_selection(request, session_data)

    if _has_requested_fridge_magnet_cavities(request):
        raise HTTPException(
            status_code=422,
            detail="Large-format tiled generation does not support fridge magnet cavities.",
        )

    image_path: str | None = session_data.get("image_path")
    lut_path: str | None = session_data.get("lut_path")
    session_material_source = session_data.get("material_source", "lut")
    if not image_path or not os.path.exists(image_path):
        raise HTTPException(status_code=409, detail=SOURCE_IMAGE_UNAVAILABLE_DETAIL)
    if session_material_source == "material_archive":
        lut_path = "__material_archive__"
    elif not lut_path or not os.path.exists(lut_path):
        raise HTTPException(status_code=409, detail=LUT_DATA_UNAVAILABLE_DETAIL)
    is_svg_vector = (
        str(image_path).lower().endswith(".svg")
        and request.modeling_mode.value == "vector"
    )
    _validate_svg_hole_compensation(
        enabled=request.svg_hole_compensation_enabled,
        image_path=image_path,
        modeling_mode=request.modeling_mode,
    )
    dynamic_material_settings = _resolve_session_dynamic_material_settings(
        session_data=session_data,
        request=request,
        material_source=str(session_material_source or "lut"),
        native_svg_vector=is_svg_vector,
    )
    if (
        session_material_source == "material_archive"
        and dynamic_material_settings[0]
    ):
        _validate_unique_dynamic_material_selection(
            session_data.get("selected_materials") or []
        )
    _require_heightmap_for_relief(session_data, request)
    recipe_overrides = _resolve_recipe_overrides(session_data, request)
    _validate_material_archive_relief_minimum_height(
        enable_relief=request.enable_relief,
        material_source=str(session_material_source or "lut"),
        height_mode=request.height_mode or "color",
        color_height_map=request.color_height_map,
        heightmap_max_height=request.heightmap_max_height,
        session_data=session_data,
        cache=cache,
        cache_ref=cache_ref,
        requested_color_layers=request.color_layers,
        recipe_overrides=recipe_overrides,
    )

    sid = body.session_id
    matched_rgb_path: str | None = None
    mask_solid_path: str | None = None
    cached_material_matrix_path: str | None = None
    quantized_image_path: str | None = None
    requires_dynamic_quantized_analysis = bool(
        request.use_cached_matched_rgb
        and dynamic_material_settings[0]
        and not is_svg_vector
    )
    if request.use_cached_matched_rgb is True:
        (
            matched_rgb_path,
            mask_solid_path,
            cached_material_matrix_path,
            quantized_image_path,
        ) = _resolve_validated_large_format_cached_analysis_paths(
            cache=cache,
            cache_ref=cache_ref,
            sid=sid,
            store=store,
            require_quantized_image=requires_dynamic_quantized_analysis,
            dynamic_max_layer_count=(
                dynamic_material_settings[2]
                if dynamic_material_settings[0]
                else None
            ),
        )
    total_w_mm, total_h_mm = _resolve_large_format_dimensions(
        cache,
        request,
        lf.target_height_mm,
    )
    try:
        resolve_large_format_grid_shape(
            total_width_mm=total_w_mm,
            total_height_mm=total_h_mm,
            tile_width_mm=float(lf.tile_width_mm),
            tile_height_mm=float(lf.tile_height_mm),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if request.use_cached_matched_rgb is True or (
        recipe_overrides
        and (
            request.svg_hole_compensation_enabled
            or cache.get("svg_hole_compensation_enabled", False)
        )
    ):
        _require_large_format_cached_analysis_semantics(
            cache=cache,
            request=request,
            total_width_mm=total_w_mm,
            session_material_source=str(session_material_source or "lut"),
            preview_color_layers=session_data.get("color_layers"),
            preview_layer_height_mm=session_data.get("layer_height_mm"),
        )
    if request.use_cached_matched_rgb is True:
        effective_color_layers, effective_layer_height_mm = (
            _resolve_effective_cached_layer_settings(
                cache=cache,
                request=request,
                preview_color_layers=session_data.get("color_layers"),
                preview_layer_height_mm=session_data.get("layer_height_mm"),
            )
        )
        request = request.model_copy(
            update={
                "color_layers": effective_color_layers,
                "layer_height_mm": effective_layer_height_mm,
            }
        )
    source_basename = _resolve_large_format_source_basename(session_data, image_path)

    override_material_matrix_path, recipe_override_masks_path = _prepare_recipe_override_worker_inputs(
        cache=cache,
        cache_ref=cache_ref,
        session_data=session_data,
        recipe_overrides=recipe_overrides,
        request=request,
        sid=sid,
        store=store,
    )
    material_matrix_path = (
        override_material_matrix_path
        if override_material_matrix_path is not None
        else cached_material_matrix_path
    )
    final_material_matrix_is_authoritative = (
        override_material_matrix_path is not None
    )
    tile_w_mm = lf.tile_width_mm
    tile_h_mm = lf.tile_height_mm

    # The helpers below may spend substantial time materialising tile inputs.
    # The session object is already detached, so this check only decides
    # whether that immutable snapshot is still current before any worker is
    # submitted.
    _assert_editor_snapshot_current(
        store,
        body.session_id,
        committed_content_revision,
        expected_selection_revision=committed_selection_revision,
    )

    warnings: list[str] = []
    fallback_reason: str | None = None
    native_fallback_error: HTTPException | None = None
    native_fallback_cause: Exception | None = None
    if is_svg_vector:
        policy = session_data.get("svg_large_format_policy")
        if not isinstance(policy, dict) or policy.get("inspection_source") not in {
            "preview-vector-svg",
            "generate-large-format",
        }:
            policy = {
                **inspect_svg_large_format_support(image_path),
                "inspection_source": "generate-large-format",
            }
            session_data["svg_large_format_policy"] = policy
            store.put(sid, "svg_large_format_policy", policy)
        warnings.extend(list(policy.get("warnings", [])))

        if (
            dynamic_material_settings[0]
            and not bool(policy.get("native_tiling_supported", False))
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Dynamic material layers require native SVG large-format "
                    "tiling. This SVG cannot be tiled natively; simplify or "
                    "re-export the SVG and preview it again."
                ),
            )

        result: dict | None = None
        if bool(policy.get("native_tiling_supported", False)):
            try:
                result = await _generate_large_format_svg_native(
                    image_path=image_path,
                    lut_path=lut_path,
                    source_basename=source_basename,
                    recipe_overrides=recipe_overrides,
                    recipe_override_masks_path=recipe_override_masks_path,
                    matched_rgb_path=matched_rgb_path,
                    mask_solid_path=mask_solid_path,
                    material_matrix_path=material_matrix_path,
                    total_width_mm=total_w_mm,
                    total_height_mm=total_h_mm,
                    tile_width_mm=tile_w_mm,
                    tile_height_mm=tile_h_mm,
                    request=request,
                    session_data=session_data,
                    sid=sid,
                    store=store,
                    registry=registry,
                    pool=pool,
                    dynamic_material_settings=dynamic_material_settings,
                    warnings=warnings,
                    base_channel_idx=int(
                        getattr(cache.get("lut_metadata"), "base_channel_idx", 0)
                        or 0
                    ),
                )
            except MemoryError:
                # Starting a second, rasterized build after allocator failure
                # only increases pressure and can kill the worker host.
                raise
            except BrokenProcessPool as exc:
                raise HTTPException(
                    status_code=503,
                    detail=LARGE_FORMAT_GENERATION_FAILED_DETAIL,
                ) from exc
            except HTTPException as exc:
                if exc.status_code not in {500, 504}:
                    raise
                if dynamic_material_settings[0]:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "Dynamic material layers require native SVG large-format "
                            "tiling, but native vector generation could not complete. "
                            "Re-preview the SVG or simplify unsupported geometry."
                        ),
                    ) from exc
                native_fallback_error = exc
                native_fallback_cause = exc
            except Exception as exc:  # noqa: BLE001 - endpoint recovery boundary
                if dynamic_material_settings[0]:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "Dynamic material layers require native SVG large-format "
                            "tiling, but native vector generation could not complete. "
                            "Re-preview the SVG or simplify unsupported geometry."
                        ),
                    ) from exc
                native_fallback_error = HTTPException(
                    status_code=500,
                    detail=LARGE_FORMAT_GENERATION_FAILED_DETAIL,
                )
                native_fallback_cause = exc

            if native_fallback_error is not None:
                fallback_reason = SVG_LARGE_FORMAT_FALLBACK_NATIVE_FAILURE
                warnings.append(
                    SVG_LARGE_FORMAT_NATIVE_FAILURE_FALLBACK_WARNING
                )
                fallback_cause = native_fallback_cause or native_fallback_error
                error_message = (
                    str(fallback_cause.detail)
                    if isinstance(fallback_cause, HTTPException)
                    else str(fallback_cause)
                )
                log.warning(
                    "Native large-format SVG generation failed; using raster fallback",
                    extra={
                        "event": "converter_large_format_svg_fallback",
                        "session_id": sid,
                        "fallback_reason": fallback_reason,
                        "error_type": type(fallback_cause).__name__,
                        "error_message": error_message[:2048],
                    },
                )
        else:
            fallback_reason = SVG_LARGE_FORMAT_FALLBACK_UNSUPPORTED_FEATURE

        if result is None:
            if request.svg_hole_compensation_enabled:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "SVG hole compensation requires vector tiling; raster fallback "
                        "would lose the filled holes. Disable compensation to use that "
                        "fallback. / SVG 补洞需要矢量分块；位图回退无法保留补洞结果。"
                        "如需回退，请关闭补洞。"
                    ),
                )
            try:
                fallback_warnings = warnings + [
                    SVG_LARGE_FORMAT_GENERATE_FALLBACK_WARNING
                ]
                result = await _generate_large_format_raster(
                    image_path=None,
                    svg_fallback_path=image_path,
                    lut_path=lut_path,
                    source_basename=source_basename,
                    recipe_overrides=recipe_overrides,
                    recipe_override_masks_path=recipe_override_masks_path,
                    matched_rgb_path=matched_rgb_path,
                    mask_solid_path=mask_solid_path,
                    material_matrix_path=material_matrix_path,
                    quantized_image_path=quantized_image_path,
                    final_material_matrix_is_authoritative=(
                        final_material_matrix_is_authoritative
                    ),
                    total_width_mm=total_w_mm,
                    total_height_mm=total_h_mm,
                    tile_width_mm=tile_w_mm,
                    tile_height_mm=tile_h_mm,
                    request=request,
                    session_data=session_data,
                    sid=sid,
                    store=store,
                    registry=registry,
                    pool=pool,
                    dynamic_material_settings=dynamic_material_settings,
                    warnings=fallback_warnings,
                    log_tile_failures=native_fallback_error is None,
                )
            except MemoryError:
                raise
            except BrokenProcessPool as fallback_exc:
                raise HTTPException(
                    status_code=503,
                    detail=LARGE_FORMAT_GENERATION_FAILED_DETAIL,
                ) from fallback_exc
            except Exception as fallback_exc:  # noqa: BLE001 - recovery boundary
                if native_fallback_error is None or (
                    isinstance(fallback_exc, HTTPException)
                    and 400 <= fallback_exc.status_code < 500
                ):
                    raise
                fallback_error_message = (
                    str(fallback_exc.detail)
                    if isinstance(fallback_exc, HTTPException)
                    else str(fallback_exc)
                )
                _log_large_format_failure(
                    session_id=sid,
                    failure_kind="raster_fallback_failed",
                    error_type=type(fallback_exc).__name__,
                    error_message=fallback_error_message[:2048],
                )
                raise native_fallback_error from fallback_exc
    else:
        result = await _generate_large_format_raster(
            image_path=image_path,
            lut_path=lut_path,
            source_basename=source_basename,
            recipe_overrides=recipe_overrides,
            recipe_override_masks_path=recipe_override_masks_path,
            matched_rgb_path=matched_rgb_path,
            mask_solid_path=mask_solid_path,
            material_matrix_path=material_matrix_path,
            quantized_image_path=quantized_image_path,
            final_material_matrix_is_authoritative=(
                final_material_matrix_is_authoritative
            ),
            total_width_mm=total_w_mm,
            total_height_mm=total_h_mm,
            tile_width_mm=tile_w_mm,
            tile_height_mm=tile_h_mm,
            request=request,
            session_data=session_data,
            sid=sid,
            store=store,
            registry=registry,
            pool=pool,
            dynamic_material_settings=dynamic_material_settings,
            warnings=warnings,
        )

    log.info(
        "Large-format conversion generated",
        extra={
            "event": "converter_generate_large_format_done",
            "session_id": body.session_id,
            "total_width_mm": total_w_mm,
            "total_height_mm": total_h_mm,
            "tile_width_mm": lf.tile_width_mm,
            "tile_height_mm": lf.tile_height_mm,
            "is_svg_vector": is_svg_vector,
            "prefer_raster_svg": fallback_reason is not None,
            "fallback_reason": fallback_reason,
            "recipe_override_count": len(recipe_overrides or []),
            "warning_count": len(result.get("warnings", [])),
        },
    )

    if str(session_data.get("material_source") or "lut") == "material_archive":
        _record_material_archive_usage_safe(
            selected_materials=session_data.get("selected_materials"),
            color_mode=request.color_mode,
        )

    _assert_editor_snapshot_current(
        store,
        body.session_id,
        committed_content_revision,
        expected_selection_revision=committed_selection_revision,
        allow_missing_session=True,
    )
    result["editor_content_revision"] = committed_content_revision
    result["selection_revision"] = committed_selection_revision
    return LargeFormatGenerateResponse(**result)


# ---------------------------------------------------------------------------
# Batch-mode structured logging helper (R7 §5: log failures must not propagate)
# ---------------------------------------------------------------------------

def _batch_intermediate_paths(worker_results: list[dict | BaseException]) -> list[Path]:
    """Collect every returned artifact, including outputs of failed items."""
    paths: list[Path] = []
    for result in worker_results:
        if isinstance(result, dict):
            for key in ("threemf_path", "preview_glb_path", "metadata_sidecar_path"):
                path = result.get(key)
                if path:
                    paths.append(Path(path))
    return paths


async def _run_batch_uploads(
    uploads: list[UploadFile],
    *,
    pool: WorkerPoolManager,
    worker_args: tuple[object, ...],
    batch_run_id: str,
) -> list[dict | BaseException]:
    """Run one bounded group, keeping inputs alive until its workers finish.
    并行处理一组上传文件，保留输入直到工作进程完成，并清理取消后的输出。
    """

    async def convert_upload(upload: UploadFile) -> dict:
        temp_path: str | None = None
        try:
            temp_path = await ensure_png_tempfile(upload)
            return await pool.submit(worker_batch_convert_item, temp_path, *worker_args)
        finally:
            _remove_temp_path(temp_path)

    pending = asyncio.gather(
        *(convert_upload(upload) for upload in uploads),
        return_exceptions=True,
    )
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        # Cancelling the request cannot stop running process-pool work.
        # Drain this group before deleting inputs, outputs, or the shared LUT.
        finished = await pending
        _cleanup_intermediates(_batch_intermediate_paths(finished), batch_run_id)
        raise


def _cleanup_intermediates(paths: list[Path], batch_run_id: str) -> None:
    """Best-effort delete intermediate per-image files after successful merge.

    Failures are logged as WARNING but never propagate to the response
    (Requirement 7 §4).
    """
    for p in paths:
        try:
            if p.exists():
                p.unlink(missing_ok=True)
        except Exception as exc:
            _safe_log(
                "warning",
                "batch_merge_intermediate_cleanup_failed",
                session_id=batch_run_id,
                error_type=type(exc).__name__,
                error_message=str(exc),
                path=str(p),
            )


def _safe_log(level: str, event: str, **fields: object) -> None:
    """Emit a structured log entry; swallow any exception silently.

    Ensures that a logging subsystem failure never propagates to the
    download / preview response path (Requirement 7 §5).

    Args:
        level: One of "debug", "info", "warning", "error".
        event: Structured event name (snake_case).
        **fields: Extra structured fields forwarded to the logger.
    """
    try:
        log_fn = getattr(log, level, log.info)
        log_fn(event, extra={"event": event, **fields})
    except Exception:
        pass


def _log_large_format_failure(
    *,
    session_id: str,
    failure_kind: str,
    error_type: str,
    error_message: str,
    tile_label: str | None = None,
    artifact_role: str | None = None,
    path: str | None = None,
) -> None:
    fields: dict[str, object] = {
        "session_id": session_id,
        "failure_kind": failure_kind,
        "error_type": error_type,
        "error_message": error_message,
    }
    if tile_label:
        fields["tile_label"] = tile_label
    if artifact_role:
        fields["artifact_role"] = artifact_role
    if path:
        fields["path"] = path
    _safe_log("error", "converter_large_format_failed", **fields)


def _log_batch_item_failure(
    *,
    batch_run_id: str,
    filename: str,
    failure_kind: str,
    error_type: str,
    error_message: str,
) -> None:
    """Log raw per-item batch diagnostics without exposing them in responses."""
    _safe_log(
        "warning",
        "converter_batch_item_failed",
        session_id=batch_run_id,
        filename=filename,
        failure_kind=failure_kind,
        error_type=error_type,
        error_message=error_message,
    )


def _resolve_batch_plate_dimensions(
    source_3mf_path: str, *, metadata_target: MetadataTarget,
) -> tuple[float, float]:
    """Return the batch layout plate dimensions for the selected printer.

    根据当前打印机配置返回批量排布使用的热床尺寸。
    """
    from utils.fatcat_metadata import read_source_metadata

    source = read_source_metadata(source_3mf_path, target=metadata_target)
    points = source["layout"]["printable_area"]
    if len(points) < 3:
        raise ValueError("Selected native printer has no printable area")
    width_mm = max(point[0] for point in points) - min(point[0] for point in points)
    depth_mm = max(point[1] for point in points) - min(point[1] for point in points)
    if not (math.isfinite(width_mm) and math.isfinite(depth_mm) and width_mm > 0 and depth_mm > 0):
        raise ValueError("Selected native printer has an invalid printable area")
    return float(width_mm), float(depth_mm)


def _xy_bbox_from_worker_result(worker_result: dict) -> XYBBox:
    """Convert a worker result's scalar bbox tuple into ``XYBBox``.

    将 worker 返回的标量 bbox 转成 ``XYBBox``，供批量排布复用。
    """
    xy = worker_result["xy_bbox_mm"]
    return XYBBox(width_mm=float(xy[0]), depth_mm=float(xy[1]))


def _select_batch_preview_subset(
    successes: list[dict],
    *,
    plate_width_mm: float,
    plate_depth_mm: float,
) -> tuple[list[dict], LayoutResult]:
    """Select the largest preview prefix that fits on the selected plate.

    The merged 3MF still receives every successful model. This helper only
    decides how many per-image GLBs the browser preview should render:
    first cap by a high browser-safety ceiling, then choose the largest
    upload-order prefix whose layout stays within the selected printer bed.
    If even one item is oversized, return that first item so the user still
    gets a visible preview with the existing plate-overflow warning.

    合并 3MF 仍包含全部成功模型；这里只决定网页 3D 预览渲染多少个。
    先受浏览器保护上限约束，再取按上传顺序能完整放进当前热床的最长前缀。
    若单个模型本身就超出热床，仍返回第一个模型用于预览。
    """
    if not successes:
        return ([], layout_shelf_by_row([], plate_width_mm, plate_depth_mm))

    candidate_successes = successes[:_BATCH_PREVIEW_BROWSER_SAFE_LIMIT]
    candidate_bboxes = [
        _xy_bbox_from_worker_result(wr)
        for wr in candidate_successes
    ]

    best_count = 0
    best_layout = None
    for count in range(1, len(candidate_bboxes) + 1):
        candidate_layout = layout_shelf_by_row(
            candidate_bboxes[:count],
            plate_width_mm=plate_width_mm,
            plate_depth_mm=plate_depth_mm,
        )
        if candidate_layout.exceeds_plate:
            break
        best_count = count
        best_layout = candidate_layout

    if best_count == 0:
        best_count = 1
        best_layout = layout_shelf_by_row(
            candidate_bboxes[:1],
            plate_width_mm=plate_width_mm,
            plate_depth_mm=plate_depth_mm,
        )

    return (candidate_successes[:best_count], best_layout)


@router.post("/batch")
async def convert_batch(
    images: list[UploadFile] = File(..., description="批量图像"),
    project_revision_file_id: Annotated[str | None, Form(max_length=128)] = None,
    project_lut: Annotated[UploadFile | None, File()] = None,
    project_materials: Annotated[UploadFile | None, File()] = None,
    source_kind: str = Form("legacy_single", description="源类型: legacy_single | legacy_multi | native_bundle"),
    lut_name: str | None = Form(None, description="LUT 名称"),
    lut_names: list[str] | str | None = Form(None, description="经典 LUT 名称列表"),
    material_type: str | None = Form(None, description="原生材料类型"),
    vendor: str | None = Form(None, description="原生厂商"),
    db_names: list[str] | str | None = Form(None, description="原生 DB 名称列表"),
    material_source: str = Form("lut", description="颜色来源: lut | material_archive"),
    selected_materials: list[str] | str | None = Form(None, description="已选耗材目录名列表"),
    material_layer_count: int | None = Form(None, ge=1, le=20, description="耗材模式叠色层数"),
    material_dynamic_layer_count_enabled: bool = Form(
        False,
        description="启用耗材模式动态有效叠层数",
    ),
    material_min_layer_count: int = Form(5, description="最小有效叠层数 (5-10)"),
    material_max_layer_count: int = Form(10, description="最大有效叠层数 (5-10)"),
    material_delta_e00_tolerance: float = Form(
        0.5,
        description="短配方允许的 CIEDE2000 色差损失 (0-5)",
    ),
    material_layer_height_mm: float | None = Form(None, gt=0.0, le=1.0, description="耗材模式层高 (mm)"),
    material_grid_resolution: int | None = Form(None, description="耗材穷举缓存网格分辨率"),
    material_backing_material_index: int | None = Form(None, ge=0, description="耗材档案底板耗材索引"),
    target_width_mm: float = Form(60.0, description="目标宽度 (mm)"),
    spacer_thick: float = Form(
        1.2,
        ge=0.2,
        le=PrinterConfig.MAX_BACKING_THICKNESS_MM,
        description="底板厚度 (mm)",
    ),
    backing_infill_density_percent: int = Form(
        PrinterConfig.BACKING_INFILL_DENSITY_DEFAULT_PERCENT,
        ge=PrinterConfig.BACKING_INFILL_DENSITY_MIN_PERCENT,
        le=PrinterConfig.BACKING_INFILL_DENSITY_MAX_PERCENT,
        description="深层底板填充率 (%)",
    ),
    separate_backing: bool = Form(
        False,
        description="Emit backing as a separate object / 将底板作为独立对象输出",
    ),
    structure_mode: str = Form("Double-sided", description="打印结构模式"),
    color_mode: str = Form("4-Color (RYBW)", description="颜色模式"),
    modeling_mode: str = Form("high-fidelity", description="建模模式"),
    color_layers: int | None = Form(None, ge=1, le=20, description="叠色层数"),
    layer_height_mm: float | None = Form(None, gt=0.0, le=1.0, description="叠色层高 (mm)"),
    quantize_colors: int = Form(48, description="K-Means 色彩细节（仅高保真模式生效）"),
    enable_cleanup: bool = Form(True, description="孤立像素清理"),
    svg_pixels_per_mm: float = Form(
        SVG_PIXELS_PER_MM_DEFAULT,
        ge=SVG_PIXELS_PER_MM_MIN,
        le=SVG_PIXELS_PER_MM_MAX,
        description=(
            "高保真 SVG 采样密度（px/mm）；仅高保真模式处理 SVG 时生效，"
            "直接矢量模式不使用此参数"
        ),
    ),
    svg_hole_compensation_enabled: Annotated[bool, Form(description="SVG 小洞补偿")] = False,
    svg_hole_max_area_mm2: Annotated[float, Form(ge=0.0, allow_inf_nan=False, description="补孔面积上限 (mm²)")] = 0.5,
    svg_hole_max_width_mm: Annotated[float, Form(ge=0.0, allow_inf_nan=False, description="细缝宽度上限 (mm)")] = 0.1,
    hue_weight: float = Form(0.0, description="色相保护权重"),
    chroma_gate: float = Form(15.0, description="暗色彩度门槛"),
    model_enable: bool = Form(False, description="启用模型辅助匹配"),
    model_only: bool = Form(False, description="仅使用模型匹配"),
    model_threshold: float | None = Form(None, description="模型回退阈值"),
    model_margin: float | None = Form(None, description="模型回退边距"),
    use_lut_constrained: bool = Form(False, description="高精度 LUT 约束匹配"),
    auto_dynamic_range: bool = Form(False, description="自动动态范围压缩"),
    high_precision_3d_preview: bool = Form(False, description="3D 高精度颜色预览"),
    enable_relief: bool = Form(False, description="启用 2.5D 浮雕模式"),
    height_mode: str = Form("color", description="浮雕高度模式"),
    color_height_map: str | None = Form(None, description="颜色高度映射 JSON"),
    heightmap_max_height: float = Form(5.0, description="最大浮雕模型总高度 (mm)"),
    printer_id: str = Form("bambu-h2d", description="打印机配置 ID"),
    slicer: str = Form("BambuStudio", description="切片器"),
    nozzle_size: str = Form("0.4", description="喷嘴直径"),
    device_profile_id: str | None = Form(None, description="机器注册表设备配置 ID"),
    build_plate_id: str | None = Form(None, description="切片软件原生打印板 ID"),
    custom_3mf_template_id: str | None = Form(None),
    external_spool_material: str | None = Form(None, min_length=1),
    native_filament_profiles: str | None = Form(None),
    enable_base_layer_height_modifier: bool = Form(
        True,
        description="启用底板粗层高优化",
    ),
    enable_wipe_tower_auto_placement: bool = Form(
        True,
        description="自动调整擦料塔位置和尺寸",
    ),
    registry: FileRegistry = Depends(get_file_registry),
    pool: WorkerPoolManager = Depends(get_worker_pool),
    enable_coating: bool = Form(False, description="启用透明镀层"),
    coating_height_mm: float = Form(0.08, ge=0.04, le=0.12, description="透明镀层厚度 (mm)"),
    coating_material: str | None = Form(None),
    backing_output: Literal["same_project", "separate_project"] = Form("same_project"),
    enable_outline: bool = Form(False, description="启用外边框"),
    outline_width: float = Form(2.0, ge=0.5, le=10.0, allow_inf_nan=False, description="外边框宽度 (mm)"),
) -> BatchResponse:
    """Batch-convert multiple images via process pool.
    通过进程池批量转换多张图像。

    File uploads and FileRegistry operations run on the main thread.
    Each batch item's CPU-intensive conversion is submitted sequentially
    to the worker pool, one at a time.
    文件上传和 FileRegistry 操作在主线程完成。
    每个批量项的 CPU 密集型转换逐个提交到工作进程池。

    Coating settings apply to every item, using single-image thickness limits.
    镀层设置应用于每个批量项，厚度范围与单图生成一致。

    Args:
        separate_backing: Emit the backing as a separate mesh object when true.
            (为 true 时将底板作为独立网格对象输出。)
    """
    revision_bytes(project_revision_file_id, registry)
    if backing_output != "same_project":
        raise HTTPException(status_code=422, detail="Independent backing projects are available for single-model generation, not batch merging.")
    validate_export_device_selection(
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size=nozzle_size,
        device_profile_id=device_profile_id,
        build_plate_id=build_plate_id,
        custom_3mf_template_id=custom_3mf_template_id,
    )
    merged_metadata_target = select_metadata_target(
        slicer=slicer,
        printer_id=printer_id,
        nozzle_size=nozzle_size,
        device_profile_id=device_profile_id,
        build_plate_id=build_plate_id,
    )
    # Resolve color source (main thread). Batch must mirror the single-image
    # preview/generate source selection contract: classic LUT, native
    # reverse-LUT bundle, or material archives.
    # 解析颜色来源；批量模式应与单图预览/生成一致支持经典 LUT、反推 LUT
    # 和耗材档案。
    material_source = _validate_material_source(material_source)
    image_count = len(images)
    selected_material_names: list[str] = []
    resolved_material_backing_index = 0
    temp_native_bundle_path: str | None = None
    if material_source == "material_archive":
        selected_material_names = _normalize_batch_string_list(selected_materials)
        if not selected_material_names:
            raise HTTPException(
                status_code=422,
                detail="Batch material archive mode requires selected_materials",
            )
        resolved_material_backing_index = _resolve_material_backing_index(
            selected_material_names,
            material_backing_material_index,
        )
        lut_path = "__material_archive__"
        resolved_lut_name = "__material_archive__"
        resolved_source_kind = "legacy_single"
    else:
        normalized_db_names = _normalize_batch_string_list(db_names)
        normalized_lut_names = _normalize_batch_string_list(lut_names)
        try:
            source_selection = LutSourceSelection.model_validate(
                {
                    "source_kind": source_kind,
                    "lut_name": lut_name,
                    "lut_names": normalized_lut_names,
                    "material_type": material_type,
                    "vendor": vendor,
                    "db_names": normalized_db_names,
                }
            )
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=LUT_SOURCE_SELECTION_INVALID_DETAIL,
            ) from exc
        try:
            source_kwargs = {
                "source_kind": source_selection.source_kind,
                "lut_name": source_selection.lut_name,
                "material_type": source_selection.material_type,
                "vendor": source_selection.vendor,
                "db_names": source_selection.db_names,
            }
            if source_selection.source_kind == "legacy_multi":
                source_kwargs["lut_names"] = source_selection.lut_names
            if project_lut is not None:
                lut_path, resolved_lut_name = "", source_selection.lut_name or "Project source"
            else:
                lut_path, resolved_lut_name = LUTManager.resolve_source_selection(
                    **source_kwargs
                )
        except ValueError as exc:
            detail = str(exc)
            status_code = 404 if detail.startswith("LUT not found:") else 422
            raise HTTPException(status_code=status_code, detail=detail) from exc
        resolved_source_kind = source_selection.source_kind
        if project_lut is None and resolved_source_kind in ("native_bundle", "legacy_multi"):
            resolved_lut_path = os.path.abspath(lut_path)
            try:
                Path(resolved_lut_path).resolve().relative_to(Path(TEMP_DIR).resolve())
            except ValueError:
                temp_native_bundle_path = None
            else:
                temp_native_bundle_path = resolved_lut_path

    project_resources = None
    try:
        if (project_lut is not None and material_source == "material_archive") or (project_materials is not None and material_source != "material_archive"):
            raise HTTPException(422, "Project resources do not match the selected color source")
        project_resources = await stage_project_resources(project_lut, project_materials, selected_material_names)
        if project_resources and project_resources.lut_path:
            lut_path = project_resources.lut_path
        try:
            selected_native_profiles = TypeAdapter(dict[str, str]).validate_json(
                native_filament_profiles or "{}",
            )
            selected_coating_material = (
                CoatingMaterialReference.model_validate_json(coating_material).model_dump()
                if coating_material else None
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail="Native filament or coating material selections are invalid.") from exc
        require_material_selection({
            "source_kind": resolved_source_kind,
            "lut_name": resolved_lut_name, "lut_names": _normalize_batch_string_list(lut_names),
            "material_type": material_type, "vendor": vendor,
            "db_names": _normalize_batch_string_list(db_names),
            "material_source": material_source, "selected_materials": selected_material_names,
            "materials_dir": project_resources.materials_dir if project_resources else None,
            "printer_id": printer_id, "slicer": slicer, "nozzle_size": nozzle_size,
            "device_profile_id": device_profile_id, "build_plate_id": build_plate_id,
            "custom_3mf_template_id": custom_3mf_template_id, "color_mode": color_mode,
            "external_spool_material": external_spool_material,
            "native_filament_profiles": selected_native_profiles,
            "enable_coating": enable_coating, "coating_material": selected_coating_material,
            "lut_path": lut_path,
        })
        # Validate modeling_mode string (main thread)
        for upload in images:
            _validate_svg_hole_compensation(
                enabled=svg_hole_compensation_enabled,
                image_path=upload.filename or "",
                modeling_mode=modeling_mode,
            )
        try:
            resolved_modeling_mode = CoreModelingMode(modeling_mode)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid modeling_mode: {modeling_mode}",
            )
        (
            material_dynamic_layer_count_enabled,
            material_min_layer_count,
            material_max_layer_count,
            material_delta_e00_tolerance,
        ) = _validate_dynamic_material_settings(
            material_source=material_source,
            enabled=material_dynamic_layer_count_enabled,
            min_layer_count=material_min_layer_count,
            max_layer_count=material_max_layer_count,
            delta_e00_tolerance=material_delta_e00_tolerance,
            hue_weight=hue_weight,
            native_svg_vector=(
                resolved_modeling_mode == CoreModelingMode.VECTOR
                and any(
                    str(upload.filename or "").lower().endswith(".svg")
                    for upload in images
                )
            ),
        )
        if (
            material_source == "material_archive"
            and material_dynamic_layer_count_enabled
        ):
            _validate_unique_dynamic_material_selection(selected_material_names)
        if resolved_modeling_mode == CoreModelingMode.COLOR_CARD:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Batch conversion does not support color-card mode. "
                    "Use single-image preview and generate instead."
                ),
            )
        try:
            svg_pixels_per_mm = normalize_svg_pixels_per_mm(svg_pixels_per_mm)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        resolved_height_mode = height_mode or "color"
        parsed_color_height_map = (
            _parse_batch_color_height_map(color_height_map)
            if enable_relief
            else None
        )
        if enable_relief and resolved_height_mode == "heightmap":
            raise HTTPException(
                status_code=422,
                detail=(
                    "Batch heightmap relief is not supported. "
                    "Use color relief or single-image generation."
                ),
            )
        if enable_relief and resolved_height_mode != "color":
            raise HTTPException(
                status_code=422,
                detail=f"Invalid height_mode: {resolved_height_mode}",
            )
        if enable_relief and not parsed_color_height_map:
            raise HTTPException(
                status_code=422,
                detail="Batch relief requires color_height_map",
            )
        if enable_relief and backing_infill_density_percent < 100:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Sparse backing infill is not supported with relief mode; "
                    "use 100% backing infill."
                ),
            )
        if enable_relief and resolved_modeling_mode == CoreModelingMode.VECTOR:
            if (
                structure_mode != StructureMode.SINGLE_SIDED.value
                or color_mode == ColorMode.FIVE_COLOR_EXT.value
            ):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Native SVG relief supports only single-sided, "
                        "non-5-Color Extended models."
                    ),
                )
        _validate_material_archive_relief_minimum_height(
            enable_relief=enable_relief,
            material_source=material_source,
            height_mode=resolved_height_mode,
            color_height_map=parsed_color_height_map,
            heightmap_max_height=heightmap_max_height,
            material_layer_count=(
                material_max_layer_count
                if material_dynamic_layer_count_enabled
                else material_layer_count
            ),
            requested_color_layers=color_layers,
        )
    except BaseException:
        discard_project_resources(project_resources)
        _remove_temp_path(temp_native_bundle_path)
        raise

    # --- batch_run_id: unique per-request identifier for structured logging
    # and artifact naming. Independent of request.state.request_id (R9 §1).
    batch_run_id = uuid.uuid4().hex
    artifact_prefix = f"batch-{batch_run_id}-"

    results: list[BatchItemResult] = []
    successful_entries: list[dict] = []

    intermediates: list[Path] = []
    worker_args: tuple[object, ...] = (
        lut_path,
        target_width_mm,
        spacer_thick,
        structure_mode,
        color_mode,
        modeling_mode,
        color_layers,
        layer_height_mm,
        quantize_colors,
        enable_cleanup,
        artifact_prefix,
        hue_weight,
        chroma_gate,
        enable_relief,
        resolved_height_mode,
        parsed_color_height_map,
        heightmap_max_height,
        svg_pixels_per_mm,
        printer_id,
        slicer,
        nozzle_size,
        enable_base_layer_height_modifier,
        model_enable,
        model_only,
        model_threshold,
        model_margin,
        material_source,
        selected_material_names,
        material_layer_count,
        material_layer_height_mm,
        material_grid_resolution,
        resolved_material_backing_index,
        use_lut_constrained,
        auto_dynamic_range,
        high_precision_3d_preview,
        device_profile_id,
        build_plate_id,
        backing_infill_density_percent,
        material_dynamic_layer_count_enabled,
        material_min_layer_count,
        material_max_layer_count,
        material_delta_e00_tolerance,
        separate_backing,
        enable_wipe_tower_auto_placement,
        svg_hole_compensation_enabled,
        svg_hole_max_area_mm2,
        svg_hole_max_width_mm,
        enable_coating,
        coating_height_mm,
        selected_native_profiles,
        selected_coating_material,
        enable_outline,
        outline_width,
        external_spool_material,
        project_resources.materials_dir if project_resources else None,
    )
    batch_size = max(1, int(pool.max_workers))
    workers_completed = False
    try:
        for start in range(0, len(images), batch_size):
            batch_uploads = images[start : start + batch_size]
            outcomes = await _run_batch_uploads(
                batch_uploads, pool=pool, worker_args=worker_args, batch_run_id=batch_run_id,
            )
            # Own all sibling outputs before propagating any fatal error.
            intermediates.extend(_batch_intermediate_paths(outcomes))
            for upload_file, result in zip(batch_uploads, outcomes):
                filename = upload_file.filename or "unknown"
                try:
                    if isinstance(result, BaseException):
                        raise result
                    threemf_path: str | None = result.get("threemf_path")
                    status_msg = str(result.get("status_msg") or "")
                    if threemf_path and os.path.exists(threemf_path):
                        successful_entries.append(result)
                        results.append(BatchItemResult(filename=filename, status="success"))
                        if material_source == "material_archive":
                            _record_material_archive_usage_safe(
                                selected_materials=selected_material_names,
                                color_mode=color_mode,
                            )
                    else:
                        _log_batch_item_failure(
                            batch_run_id=batch_run_id,
                            filename=filename,
                            failure_kind="missing_output",
                            error_type="MissingBatchOutput",
                            error_message=(
                                status_msg.strip()
                                or "Worker result did not include a generated 3MF path"
                            ),
                        )
                        results.append(BatchItemResult(
                            filename=filename, status="failed", error=BATCH_ITEM_FAILED_DETAIL,
                        ))
                except (
                    BrokenProcessPool, DynamicMaterialCandidateError,
                    DynamicMaterialSolverError, WipeTowerLayoutError, NativeMaterialSelectionError,
                    ExternalSpoolSelectionError, TemplateSlotCapacityError,
                ):
                    raise
                except ROUTER_HANDLED_ERRORS as exc:
                    _log_batch_item_failure(
                        batch_run_id=batch_run_id,
                        filename=filename,
                        failure_kind="worker_exception",
                        error_type=type(exc).__name__,
                        error_message=str(exc),
                    )
                    results.append(BatchItemResult(
                        filename=filename, status="failed", error=BATCH_ITEM_FAILED_DETAIL,
                    ))
        workers_completed = True
    except BrokenProcessPool as exc:
        raise HTTPException(status_code=503, detail=BATCH_GENERATION_FAILED_DETAIL) from exc
    except (DynamicMaterialCandidateError, DynamicMaterialSolverError) as exc:
        _handle_core_error(exc, "batch material generation")
    except (WipeTowerLayoutError, NativeMaterialSelectionError, ExternalSpoolSelectionError, TemplateSlotCapacityError) as exc:
        raise to_http_exception(exc, "batch 3MF layout") from exc
    finally:
        # Release returned artifacts on cancellation or any fatal failure.
        if not workers_completed:
            _cleanup_intermediates(intermediates, batch_run_id)
        discard_project_resources(project_resources)
        _remove_temp_path(temp_native_bundle_path)

    # --- Merge phase: layout -> writers -> FileRegistry -> cleanup ---
    successes = successful_entries

    # Zero successes → return immediately with null URLs
    if len(successes) == 0:
        _cleanup_intermediates(intermediates, batch_run_id)
        _remove_temp_path(temp_native_bundle_path)
        return BatchResponse(
            status="failed",
            message=f"Batch complete: 0/{len(results)} succeeded",
            download_url=None,
            threemf_disk_path=None,
            preview_3d_url=None,
            warnings=[],
            results=results,
        )

    warnings: list[WarningEntry] = []
    merged_outputs: list[Path] = []
    stage = "layout"

    try:
        # Step 1: Layout
        stage = "layout"
        plate_width_mm, plate_depth_mm = _resolve_batch_plate_dimensions(
            successes[0]["threemf_path"], metadata_target=merged_metadata_target,
        )
        _safe_log(
            "info", "batch_merge_3mf_init", session_id=batch_run_id,
            model_count=len(successes), plate_width_mm=plate_width_mm,
            plate_depth_mm=plate_depth_mm,
        )
        bboxes = [_xy_bbox_from_worker_result(wr) for wr in successes]

        layout_result = layout_shelf_by_row(
            bboxes,
            plate_width_mm=plate_width_mm,
            plate_depth_mm=plate_depth_mm,
        )

        # Step 2: Check plate overflow
        if layout_result.exceeds_plate:
            warnings.append(
                WarningEntry(
                    code="plate-overflow",
                    message=BATCH_PLATE_OVERFLOW_FALLBACK_MESSAGE,
                )
            )
            _safe_log(
                "warning",
                "batch_merge_plate_overflow_warning",
                session_id=batch_run_id,
                model_count=len(successes),
                plate_width_mm=plate_width_mm,
                plate_depth_mm=plate_depth_mm,
                error_message=BATCH_PLATE_OVERFLOW_FALLBACK_MESSAGE,
                fallback_action=(
                    "merged_3mf_returned_with_plate_overflow_warning"
                ),
            )

        # Step 3: Merged 3MF
        stage = "merge_3mf"
        merged_items: list[MergedItem] = []
        for idx, wr in enumerate(successes):
            # Read sidecar for slots
            sidecar_path = wr["metadata_sidecar_path"]
            with open(sidecar_path, "r", encoding="utf-8") as f:
                sidecar_data = json.load(f)

            slots_raw = sidecar_data.get("slots", [])
            writer_slots = tuple(
                WriterMaterialSlot(
                    slot_id=s["slot_id"],
                    slot_name=s["slot_name"],
                    preview_color=s["preview_color"],
                    material_id=s["material_id"],
                )
                for s in slots_raw
            )

            placement = layout_result.placements[idx]
            merged_items.append(
                MergedItem(
                    source_filename=sidecar_data.get("source_filename", f"item_{idx}"),
                    source_3mf_path=Path(wr["threemf_path"]),
                    slots=writer_slots,
                    tx_mm=placement.tx_mm,
                    ty_mm=placement.ty_mm,
                )
            )

        fd, merged_3mf_path_str = tempfile.mkstemp(
            suffix=".3mf", dir=TEMP_DIR, prefix=artifact_prefix
        )
        os.close(fd)
        merged_3mf_path = Path(merged_3mf_path_str)
        merged_outputs.append(merged_3mf_path)

        MergedBambu3MFWriter().write(
            merged_items,
            merged_3mf_path,
            plate_width_mm=plate_width_mm,
            plate_depth_mm=plate_depth_mm,
            enable_wipe_tower_auto_placement=(
                enable_wipe_tower_auto_placement
            ),
            metadata_target=merged_metadata_target,
            external_spool_material=external_spool_material,
            printer_id=printer_id,
            nozzle_size=nozzle_size,
            device_profile_id=device_profile_id,
            build_plate_id=build_plate_id,
        )

        for warning_code in read_wipe_tower_placement_warnings(merged_3mf_path):
            if warning_code != WIPE_TOWER_MANUAL_WARNING_CODE:
                continue
            warnings.append(
                WarningEntry(
                    code=warning_code,
                    message=BATCH_WIPE_TOWER_MANUAL_ADJUSTMENT_MESSAGE,
                )
            )

        embed_generated_project(str(merged_3mf_path), project_revision_file_id, registry)
        # Step 4: FileRegistry registration
        stage = "file_registry"
        download_id = registry.register_path(
            session_id=f"batch-merge:{batch_run_id}",
            path=str(merged_3mf_path),
            filename="batch.3mf",
            ttl_seconds=BATCH_DOWNLOAD_TTL_SECONDS,
        )
        download_url = f"/api/files/{download_id}"

    except Exception as exc:
        # Keep cleanup shared by layout validation and unexpected failures.
        _safe_log(
            "error",
            "batch_merge_3mf_failed",
            session_id=batch_run_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
            stage=stage,
        )
        if isinstance(exc, (WipeTowerLayoutError, NativeMaterialSelectionError, ExternalSpoolSelectionError, TemplateSlotCapacityError)):
            _cleanup_intermediates(intermediates + merged_outputs, batch_run_id)
            _remove_temp_path(temp_native_bundle_path)
            raise to_http_exception(exc, "batch 3MF layout") from exc
        # Completed single exports already exist. Register them without copying
        # or repacking so a failed write cannot consume their remaining space.
        retained_paths: set[Path] = set()
        completed_results = [result for result in results if result.status == "success"]
        for index, (result, worker_result) in enumerate(zip(completed_results, successes), start=1):
            path = Path(worker_result["threemf_path"])
            filename = generate_preserved_upload_3mf_filename(Path(result.filename).stem) or "model.3mf"
            file_id = registry.register_path(
                session_id=f"batch-item:{batch_run_id}", path=str(path),
                filename=f"{index}_{filename}",
                ttl_seconds=BATCH_DOWNLOAD_TTL_SECONDS,
            )
            result.download_url = f"/api/files/{file_id}"
            retained_paths.add(path)
        _cleanup_intermediates(
            [path for path in intermediates + merged_outputs if path not in retained_paths],
            batch_run_id,
        )
        _remove_temp_path(temp_native_bundle_path)
        return BatchResponse(
            status="partial",
            message=f"Generated {len(successes)}/{len(results)} models; download completed items separately.",
            results=results,
            warnings=[WarningEntry(
                code="merge-unavailable",
                message="The merged project could not be written. Completed models are available individually.",
            )],
        )

    preview_items: list[BatchPreviewItem] = []
    preview_3d_url: str | None = None
    preview_unavailable_reported = False

    def _record_preview_unavailable(exc: Exception, *, preview_stage: str) -> None:
        nonlocal preview_unavailable_reported
        _safe_log(
            "warning",
            "batch_merge_preview_unavailable",
            session_id=batch_run_id,
            error_type=type(exc).__name__,
            error_message=str(exc),
            stage=preview_stage,
        )
        if not preview_unavailable_reported:
            warnings.append(
                WarningEntry(
                    code="preview-unavailable",
                    message=BATCH_PREVIEW_UNAVAILABLE_MESSAGE,
                )
            )
            preview_unavailable_reported = True

    preview_stage = "preview_layout"
    try:
        preview_successes, preview_layout_result = _select_batch_preview_subset(
            successes,
            plate_width_mm=plate_width_mm,
            plate_depth_mm=plate_depth_mm,
        )
        if len(preview_successes) < len(successes):
            warnings.append(
                WarningEntry(
                    code="preview-limited",
                    message=BATCH_PREVIEW_LIMIT_FALLBACK_MESSAGE,
                )
            )

        for idx, wr in enumerate(preview_successes):
            preview_id: str | None = None
            preview_copy_path: Path | None = None
            try:
                preview_stage = "preview_source"
                source_glb = wr.get("preview_glb_path")
                if not source_glb:
                    continue
                source_glb_path = Path(source_glb)
                if not source_glb_path.exists():
                    continue

                preview_stage = "preview_copy"
                fd, preview_copy_str = tempfile.mkstemp(
                    suffix=".glb", dir=TEMP_DIR, prefix=artifact_prefix
                )
                os.close(fd)
                preview_copy_path = Path(preview_copy_str)
                shutil.copy2(source_glb_path, preview_copy_path)

                preview_stage = "preview_file_registry"
                preview_id = registry.register_path(
                    session_id=f"batch-preview:{batch_run_id}",
                    path=str(preview_copy_path),
                    filename=f"batch_preview_{idx + 1}.glb",
                    ttl_seconds=BATCH_DOWNLOAD_TTL_SECONDS,
                )
                preview_url = f"/api/files/{preview_id}"

                placement = preview_layout_result.placements[idx]
                xy = wr["xy_bbox_mm"]
                preview_filename = f"item_{idx}"
                try:
                    with open(wr["metadata_sidecar_path"], "r", encoding="utf-8") as f:
                        preview_sidecar = json.load(f)
                    preview_filename = str(
                        preview_sidecar.get("source_filename") or preview_filename
                    )
                except (OSError, json.JSONDecodeError, TypeError, ValueError):
                    pass

                preview_items.append(
                    BatchPreviewItem(
                        url=preview_url,
                        filename=preview_filename,
                        tx_mm=placement.tx_mm,
                        ty_mm=placement.ty_mm,
                        width_mm=float(xy[0]),
                        depth_mm=float(xy[1]),
                    )
                )
                if preview_3d_url is None:
                    preview_3d_url = preview_url
            except (*ROUTER_HANDLED_ERRORS, IndexError, ValidationError) as exc:
                if preview_id is not None:
                    with suppress(Exception):
                        registry.cleanup_file(preview_id)
                elif preview_copy_path is not None:
                    with suppress(OSError):
                        preview_copy_path.unlink(missing_ok=True)
                _record_preview_unavailable(exc, preview_stage=preview_stage)
    except (*ROUTER_HANDLED_ERRORS, IndexError, ValidationError) as exc:
        preview_items = []
        preview_3d_url = None
        _record_preview_unavailable(exc, preview_stage=preview_stage)

    # Success path: cleanup intermediate files
    _cleanup_intermediates(intermediates, batch_run_id)
    _remove_temp_path(temp_native_bundle_path)

    success_count = sum(1 for r in results if r.status == "success")
    failure_count = len(results) - success_count

    _safe_log(
        "info",
        "batch_merge_3mf_done",
        session_id=batch_run_id,
        model_count=len(successes),
        success_count=success_count,
        failure_count=failure_count,
        exceeds_plate=layout_result.exceeds_plate,
    )

    return BatchResponse(
        status="ok",
        message=f"Batch complete: {success_count}/{len(results)} succeeded",
        download_url=download_url,
        threemf_disk_path=None,
        preview_3d_url=preview_3d_url,
        preview_items=preview_items,
        warnings=warnings,
        results=results,
    )
