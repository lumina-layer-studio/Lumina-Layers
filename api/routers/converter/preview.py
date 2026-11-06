"""Converter router preview module."""

from __future__ import annotations

import asyncio
import copy
from concurrent.futures.process import BrokenProcessPool
import json
import os
import pickle
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Annotated

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image
from pydantic import ValidationError

from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.dynamic_material_response import dynamic_material_result_from_cache
from api.file_bridge import ensure_png_tempfile, ndarray_to_png_bytes
from api.file_registry import FileRegistry
from api.preview_response_payload import build_preview_response_palette
from api.preview_cache_artifacts import (
    estimate_preview_cache_bytes,
    externalize_preview_cache,
    get_preview_cache_max_bytes,
    get_preview_cache_metadata,
    hydrate_preview_cache,
    is_preview_cache_artifact_ref,
)
from api.preview_cache_memory import (
    build_preview_cache_memory_profile,
    get_process_rss_bytes,
    should_log_preview_cache_memory_profile_at_info,
)
from api.replacement_history import clear_replacement_history
from api.schemas.converter import (
    BedSizeItem,
    BedSizeListResponse,
    ColorReplacementItem,
    VectorPreviewRendererRequest,
    VectorPreviewRendererResponse,
)
from api.schemas.lut import LutSourceSelection
from api.schemas.responses import (
    AutoDetectColorsResponse,
    CropResponse,
    HeightmapUploadResponse,
    PreviewResponse,
)
from api.session_store import SessionStore
from api.structured_logging import bind_session_id, get_logger
from api.visible_region_cache import schedule_visible_region_cache_prewarm
from api.worker_pool import WorkerPoolManager
from api.workers.converter_workers import worker_generate_preview
from config import (
    SVG_PIXELS_PER_MM_DEFAULT,
    SVG_PIXELS_PER_MM_MAX,
    SVG_PIXELS_PER_MM_MIN,
    BedManager,
    OUTPUT_DIR,
    PrinterConfig,
    TEMP_DIR,
    normalize_svg_pixels_per_mm,
)
from core.converter import generate_empty_bed_glb, generate_segmented_glb
from core.naming import generate_segmented_glb_filename
from core.heightmap_loader import HeightmapLoader
from core.image_preprocessor import ImagePreprocessor
from core.material_dynamic_solver import (
    DynamicMaterialCandidateError,
    DynamicMaterialSolverError,
)
from core.vector_large_format import inspect_svg_large_format_support, normalize_large_format_source_basename
from utils.lut_manager import LUTManager

from .async_glb import get_glb_status, schedule_glb_build
from .common import (
    EPHEMERAL_PREVIEW_TTL_SECONDS,
    LUT_SOURCE_SELECTION_INVALID_DETAIL,
    NON_FATAL_GLB_ERRORS,
    PREVIEW_CACHE_UNAVAILABLE_DETAIL,
    ROUTER_HANDLED_ERRORS,
    _handle_core_error,
    _image_to_png_bytes,
    _public_pipeline_validation_detail,
    _require_preview_cache,
    _require_session,
    _resolve_material_backing_index,
    _validate_dynamic_material_settings,
    _validate_unique_dynamic_material_selection,
    _validate_material_source,
    _validate_svg_hole_compensation,
    recompute_gradient_groups_into_session,
)
from .model_surface import resolve_surface_preview_config
from .source_validation import (
    ConverterSourceValidationError,
    validate_converter_source,
)

router = APIRouter()
log = get_logger(__name__)
_PREVIEW_GENERATION_FAILED_DETAIL = (
    "Preview generation failed. Re-run preview and try again."
)
_CROP_FAILED_DETAIL = (
    "Image crop failed. Please retry or choose a different image."
)
AUTO_DETECT_COLORS_FAILED_DETAIL = (
    "颜色分析失败，请重新上传图片，或手动设置颜色数后继续。"
)
LARGE_FORMAT_SVG_PREVIEW_CACHE_MAX_BYTES_ENV = (
    "LUMINA_LARGE_FORMAT_SVG_PREVIEW_CACHE_MAX_BYTES"
)
LAYER_IMAGES_PREVIEW_CACHE_UNAVAILABLE_DETAIL = (
    "Layer image preview cache is unavailable. "
    "Re-run preview before viewing layer images."
)
VECTOR_PARSE_CLIP_CACHE_MAX_BYTES_ENV = "LUMINA_VECTOR_PARSE_CLIP_CACHE_MAX_BYTES"
DEFAULT_VECTOR_PARSE_CLIP_CACHE_MAX_BYTES = 64 * 1024 * 1024
# Keep this aligned with VectorProcessor.build_preview_cache's default width cap.
VECTOR_PREVIEW_CACHE_MAX_WIDTH_PX = 1600
PREVIEW_RESPONSE_CACHE_FIELDS = {
    "matched_rgb",
    "mask_solid",
    "preview_rgba",
    "quantized_image",
}


def _get_large_format_svg_preview_cache_max_bytes() -> int | None:
    """Return the optional cache guardrail for full-resolution SVG previews.

    返回大画幅 SVG 预览的可选缓存上限；未显式配置时关闭。
    """

    raw = os.getenv(LARGE_FORMAT_SVG_PREVIEW_CACHE_MAX_BYTES_ENV)
    if raw is None or raw.strip() == "":
        return None
    try:
        parsed = int(raw)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _get_vector_parse_clip_cache_max_bytes() -> int:
    """Return the session temp-file guardrail for SVG parse/clip artifacts."""

    raw = os.getenv(VECTOR_PARSE_CLIP_CACHE_MAX_BYTES_ENV)
    if raw is None or raw.strip() == "":
        return DEFAULT_VECTOR_PARSE_CLIP_CACHE_MAX_BYTES
    try:
        parsed = int(raw)
    except ValueError:
        return DEFAULT_VECTOR_PARSE_CLIP_CACHE_MAX_BYTES
    return max(1, parsed)


def _preview_cache_artifact_paths(ref: dict | None) -> list[str]:
    if not is_preview_cache_artifact_ref(ref):
        return []
    paths: list[str] = []
    seen: set[str] = set()
    for field_ref in ref.get("fields", {}).values():
        path = field_ref.get("path") if isinstance(field_ref, dict) else None
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def _with_original_preview_cache_refs(ref: dict) -> dict:
    updated = {
        "schema": ref["schema"],
        "manifest_revision": int(ref.get("manifest_revision", 0)),
        "fields": {
            field_name: dict(field_ref)
            for field_name, field_ref in ref.get("fields", {}).items()
        },
        "metadata": copy.deepcopy(ref.get("metadata", {})),
    }
    fields = updated["fields"]
    if "matched_rgb" in fields:
        fields.setdefault("original_matched_rgb", dict(fields["matched_rgb"]))
        fields.setdefault(
            "height_identity_rgb",
            dict(fields["original_matched_rgb"]),
        )
    if "material_matrix" in fields:
        fields.setdefault(
            "original_material_matrix",
            dict(fields["material_matrix"]),
        )
    if "quantized_image" in fields:
        fields.setdefault(
            "original_quantized_image",
            dict(fields["quantized_image"]),
        )
    metadata = updated["metadata"]
    if "material_dynamic_layer_info" in metadata:
        metadata.setdefault(
            "original_material_dynamic_layer_info",
            copy.deepcopy(metadata["material_dynamic_layer_info"]),
        )
    if "material_solver_info" in metadata:
        metadata.setdefault(
            "original_material_solver_info",
            copy.deepcopy(metadata["material_solver_info"]),
        )
    return updated
_DEFAULT_GENERATE_SEGMENTED_GLB = generate_segmented_glb


def _schedule_or_run_preview_glb_build(
    session_id: str,
    store: SessionStore,
    registry: FileRegistry,
    cache: dict,
) -> str | None:
    """Schedule preview GLB generation, preserving inline test overrides.

    Production uses the shared async scheduler so the preview request can
    return once the PNG/cache payload is ready. Unit tests in this module
    historically monkeypatch ``generate_segmented_glb``; when that override
    is present, run it inline to preserve those narrow test contracts without
    starting real background mesh work.
    """

    if generate_segmented_glb is _DEFAULT_GENERATE_SEGMENTED_GLB:
        schedule_glb_build(session_id, store, registry, cache)
        return None

    target_path = os.path.join(
        OUTPUT_DIR,
        generate_segmented_glb_filename(session_id),
    )
    glb_path = generate_segmented_glb(cache, output_path=target_path)
    if glb_path and os.path.exists(glb_path):
        glb_id = registry.register_path(session_id, glb_path)
        return f"/api/files/{glb_id}"
    return None


def _resolve_upload_source_basename(filename: str | None, temp_path: str) -> str:
    """Resolve a stable source basename from upload metadata across path styles."""

    candidate = str(filename or "").strip()
    if candidate:
        normalized_filename = candidate.replace("\\", "/")
        source_basename = normalize_large_format_source_basename(
            os.path.splitext(os.path.basename(normalized_filename))[0]
        )
        if source_basename:
            return source_basename
    fallback_basename = os.path.splitext(os.path.basename(temp_path))[0]
    return normalize_large_format_source_basename(fallback_basename) or fallback_basename


def _estimate_preview_layers(
    *,
    color_layers: int | None,
    material_layer_count: int | None,
    material_dynamic_layer_count_enabled: bool = False,
    material_max_layer_count: int = 10,
    material_source: str,
) -> int:
    """Return a conservative layer count for preview-cache size estimates.

    返回用于 preview-cache 大小估算的保守叠色层数。
    """
    if material_source == "material_archive":
        if material_dynamic_layer_count_enabled:
            return max(1, int(material_max_layer_count))
        if material_layer_count:
            return max(1, int(material_layer_count))
    if color_layers:
        return max(1, int(color_layers))
    return 5


def _preview_material_matrix_dtype_for_range(
    min_value: int,
    max_value: int,
) -> np.dtype:
    """Return the smallest signed preview-cache dtype for material indices."""

    for dtype in (np.int8, np.int16, np.int32, np.int64):
        info = np.iinfo(dtype)
        if min_value >= info.min and max_value <= info.max:
            return np.dtype(dtype)
    return np.dtype(np.int64)


def _estimate_material_matrix_itemsize(
    *,
    material_source: str,
    selected_material_count: int | None,
) -> int | None:
    """Estimate persisted material-matrix item size for preview-cache guardrails."""

    if material_source == "material_archive":
        if selected_material_count is None:
            return np.dtype(np.int16).itemsize
        max_material_index = max(0, int(selected_material_count) - 1)
    else:
        # Legacy/native LUT stacks use supported color-channel indices, currently
        # bounded by the 8-color modes, and are compacted before persistence.
        max_material_index = 7
    return _preview_material_matrix_dtype_for_range(-1, max_material_index).itemsize


def _compact_material_matrix_array(array: np.ndarray) -> np.ndarray:
    """Compact a preview material matrix while preserving signed ``-1`` air."""

    if not np.issubdtype(array.dtype, np.integer):
        return array
    if array.size:
        min_value = int(array.min())
        max_value = int(array.max())
    else:
        min_value = -1
        max_value = 0
    target_dtype = _preview_material_matrix_dtype_for_range(min_value, max_value)
    if array.dtype == target_dtype:
        return array
    return array.astype(target_dtype, copy=False)


def _compact_preview_cache_material_matrices(cache: dict) -> dict:
    """Compact fixed matrices but retain dynamic authority matrices as int32.

    动态耗材矩阵是拼图/生成复用的权威分析资产，不能在预览缓存外置前降级为
    int8/int16；P03 会严格校验其 ``int32`` 协议。普通固定层数矩阵仍按原有
    规则压缩以控制缓存体积。
    """

    compacted = dict(cache)
    dynamic_info = compacted.get("material_dynamic_layer_info")
    preserve_dynamic_int32 = isinstance(dynamic_info, dict) and bool(
        dynamic_info.get("enabled")
    )
    for field_name in ("material_matrix", "original_material_matrix"):
        value = compacted.get(field_name)
        if isinstance(value, np.ndarray):
            compacted[field_name] = (
                value.astype(np.int32, copy=False)
                if preserve_dynamic_int32
                else _compact_material_matrix_array(value)
            )
    return compacted


def _parse_svg_length(raw: str | None) -> float | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value or value.endswith("%"):
        return None
    number_chars: list[str] = []
    for char in value:
        if char.isdigit() or char in {".", "+", "-", "e", "E"}:
            number_chars.append(char)
        else:
            break
    if not number_chars:
        return None
    try:
        return float("".join(number_chars))
    except ValueError:
        return None


def _parse_svg_aspect_ratio(svg_path: str) -> float | None:
    """Return SVG height/width ratio when simple metadata is available.

    在 SVG 简单尺寸元数据可用时返回 height/width 比例。
    """
    try:
        root = ET.parse(svg_path).getroot()
    except (ET.ParseError, OSError):
        return None

    view_box = root.attrib.get("viewBox") or root.attrib.get("viewbox")
    if view_box:
        parts = view_box.replace(",", " ").split()
        if len(parts) == 4:
            try:
                width = float(parts[2])
                height = float(parts[3])
            except ValueError:
                return None
            if width > 0 and height > 0:
                return height / width

    width = _parse_svg_length(root.attrib.get("width"))
    height = _parse_svg_length(root.attrib.get("height"))
    if width is None or height is None or width <= 0 or height <= 0:
        return None
    return height / width


def _estimate_preview_target_dimensions(
    image_path: str,
    *,
    target_width_mm: float,
    modeling_mode: str,
    svg_pixels_per_mm: float,
) -> tuple[int, int] | None:
    """Estimate preview cache dimensions before the worker runs.

    在 worker 执行前估算 preview cache 像素尺寸。
    """
    if image_path.lower().endswith(".svg"):
        pixels_per_mm = (
            svg_pixels_per_mm
            if modeling_mode == "high-fidelity"
            else SVG_PIXELS_PER_MM_DEFAULT
        )
        width = max(1, int(float(target_width_mm) * float(pixels_per_mm)))
        aspect_ratio = _parse_svg_aspect_ratio(image_path)
        if aspect_ratio is None:
            return None
        height = max(1, int(width * aspect_ratio))
        if modeling_mode == "vector" and width > VECTOR_PREVIEW_CACHE_MAX_WIDTH_PX:
            ratio = VECTOR_PREVIEW_CACHE_MAX_WIDTH_PX / width
            width = VECTOR_PREVIEW_CACHE_MAX_WIDTH_PX
            height = max(1, int(round(height * ratio)))
        return width, height

    try:
        with Image.open(image_path) as img:
            source_width, source_height = img.size
    except (OSError, ValueError):
        return None
    if source_width <= 0 or source_height <= 0:
        return None

    if modeling_mode == "high-fidelity":
        width = int(float(target_width_mm) * 10)
    else:
        width = int(float(target_width_mm) / PrinterConfig.NOZZLE_WIDTH)
    width = max(1, width)
    height = max(1, int(width * source_height / source_width))
    return width, height


def _enforce_preview_cache_size_limit(
    *,
    image_path: str,
    target_width_mm: float,
    modeling_mode: str,
    svg_pixels_per_mm: float,
    color_layers: int | None,
    material_layer_count: int | None,
    material_dynamic_layer_count_enabled: bool = False,
    material_max_layer_count: int = 10,
    material_source: str,
    selected_material_count: int | None = None,
    max_bytes: int | None = None,
) -> None:
    """Reject previews whose estimated cache arrays exceed the guardrail.

    拒绝预计 preview cache 大数组超过上限的预览请求。
    """
    if max_bytes is None:
        return

    dimensions = _estimate_preview_target_dimensions(
        image_path,
        target_width_mm=target_width_mm,
        modeling_mode=modeling_mode,
        svg_pixels_per_mm=svg_pixels_per_mm,
    )
    if dimensions is None:
        return

    width, height = dimensions
    layers = _estimate_preview_layers(
        color_layers=color_layers,
        material_layer_count=material_layer_count,
        material_dynamic_layer_count_enabled=material_dynamic_layer_count_enabled,
        material_max_layer_count=material_max_layer_count,
        material_source=material_source,
    )
    estimate_bytes = estimate_preview_cache_bytes(
        width,
        height,
        layers,
        include_original=True,
        matrix_itemsize=_estimate_material_matrix_itemsize(
            material_source=material_source,
            selected_material_count=selected_material_count,
        ),
    )
    if estimate_bytes <= max_bytes:
        return

    raise HTTPException(
        status_code=422,
        detail={
            "error": "preview_cache_size_limit_exceeded",
            "message": (
                "Estimated preview cache arrays exceed the configured limit."
            ),
            "estimate_bytes": estimate_bytes,
            "max_bytes": max_bytes,
            "estimated_width": width,
            "estimated_height": height,
            "estimated_layers": layers,
        },
    )


def _cleanup_pre_session_temp_paths(*paths: str | None) -> None:
    """Best-effort cleanup for temp files created before a session exists."""

    seen: set[str] = set()
    for path in paths:
        if not path or path in seen:
            continue
        seen.add(path)
        try:
            if os.path.exists(path):
                os.unlink(path)
        except OSError as exc:
            log.warning(
                "Failed to clean pre-session temp file",
                extra={
                    "event": "converter_preview_temp_cleanup_failed",
                    "temp_path": path,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )


def _cleanup_auto_detect_tempfile(temp_path: str) -> None:
    """Best-effort cleanup for sessionless auto-detect uploads."""

    try:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    except OSError as exc:
        log.warning(
            "Failed to clean auto-detect temp file",
            extra={
                "event": "converter_auto_detect_temp_cleanup_failed",
                "path": temp_path,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )


def _rollback_preview_session_after_failure(
    *,
    session_id: str,
    store: SessionStore,
    registry: FileRegistry,
    extra_temp_paths: tuple[str | None, ...] = (),
) -> None:
    """Best-effort rollback for preview sessions that never reach the client."""

    for cleanup_target, cleanup in (
        # Invalidate GLB ownership before cleanup; a late background result
        # must fail its session/revision checks instead of registering anew.
        ("session_store", lambda: store.close(session_id)),
        ("file_registry", lambda: registry.cleanup_session(session_id)),
    ):
        try:
            cleanup()
        except ROUTER_HANDLED_ERRORS as exc:
            log.warning(
                "Failed to roll back preview session after response assembly error",
                extra={
                    "event": "converter_preview_session_rollback_failed",
                    "session_id": session_id,
                    "cleanup_target": cleanup_target,
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
    _cleanup_pre_session_temp_paths(*extra_temp_paths)


def _normalize_db_names(db_names: list[str] | str | None) -> list[str]:
    """Normalize native DB names from form inputs.

    Accepts repeated form fields, JSON-stringified arrays, and plain strings.
    """
    if db_names is None:
        return []

    if isinstance(db_names, str):
        value = db_names.strip()
        if not value:
            return []
        if value.startswith("[") and value.endswith("]"):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return [db_names]
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, str)]
        return [db_names]

    try:
        normalized = list(db_names)
    except TypeError:
        return []
    if len(normalized) == 1 and isinstance(normalized[0], str):
        value = normalized[0].strip()
        if value.startswith("[") and value.endswith("]"):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return normalized
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, str)]
    return normalized


def _parse_selected_materials(value: list[str] | str | None) -> list[str]:
    """Normalize selected-materials field from multipart/form-data inputs.
    规范化 multipart/form-data 中的 selected_materials 字段。

    Accepts repeated form fields, JSON-stringified arrays (the typical
    frontend shape: ``'["mat1","mat2"]'``), or comma-separated strings.
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
        return [s.strip() for s in stripped.split(",") if s.strip()]

    normalized = [str(item) for item in value if str(item).strip()]
    if len(normalized) == 1:
        stripped = normalized[0].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
    return [s.strip() for s in normalized if s.strip()]


def _parse_preview_replacement_regions(
    value: str | None,
) -> list[dict[str, str]] | None:
    """Parse preview replay replacement regions from form JSON.
    解析预览重放用的颜色替换 JSON。
    """
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail="replacement_regions must be a JSON array",
        ) from exc
    if not isinstance(parsed, list):
        raise HTTPException(
            status_code=422,
            detail="replacement_regions must be a JSON array",
        )
    try:
        return [
            ColorReplacementItem.model_validate(item).model_dump()
            for item in parsed
        ]
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail="replacement_regions contains invalid items",
        ) from exc


@router.get("/bed-sizes", response_model=BedSizeListResponse)
def get_bed_sizes() -> BedSizeListResponse:
    """Return all available printer bed sizes including printer models and custom sizes.
    返回所有可用的打印热床尺寸列表，包括打印机型号和自定义尺寸。
    """
    beds = [
        BedSizeItem(
            label=label,
            width_mm=w,
            height_mm=h,
            is_default=(label == BedManager.DEFAULT_BED),
            printer_id=printer_id,
        )
        for label, w, h, printer_id in BedManager.get_all_bed_options()
    ]
    return BedSizeListResponse(beds=beds)


@router.get("/bed-preview")
def get_bed_preview(
    bed_label: str = BedManager.DEFAULT_BED,
    registry: FileRegistry = Depends(get_file_registry),
) -> dict:
    """Generate a GLB preview of the empty print bed.
    生成空热床的 GLB 3D 预览。

    Args:
        bed_label: Bed size label (e.g. "256×256 mm"). (热床尺寸标签)

    Returns:
        dict: Contains preview_3d_url pointing to the GLB file. (包含 GLB 文件 URL)
    """
    bed_w, bed_h = BedManager.get_bed_size(bed_label)
    try:
        glb_path = generate_empty_bed_glb(bed_w, bed_h)
    except ROUTER_HANDLED_ERRORS as e:
        _handle_core_error(e, "Bed preview generation")

    if glb_path is None:
        raise HTTPException(status_code=500, detail="Failed to generate bed preview")

    try:
        glb_id = registry.register_path(
            str(uuid.uuid4()),
            glb_path,
            ttl_seconds=EPHEMERAL_PREVIEW_TTL_SECONDS,
        )
    except Exception:
        try:
            if os.path.isfile(glb_path):
                os.remove(glb_path)
        except OSError as cleanup_exc:
            log.warning(
                "Failed to clean unregistered bed preview GLB",
                extra={
                    "event": "converter_bed_preview_cleanup_failed",
                    "path": glb_path,
                    "error_type": type(cleanup_exc).__name__,
                    "error_message": str(cleanup_exc),
                },
            )
        raise
    return {"preview_3d_url": f"/api/files/{glb_id}"}


@router.post("/auto-detect-colors", response_model=AutoDetectColorsResponse)
async def auto_detect_colors(
    image: UploadFile = File(..., description="输入图像"),
    target_width_mm: float = Form(60.0, description="目标打印宽度（毫米）"),
) -> AutoDetectColorsResponse:
    """Analyze an image and recommend the optimal quantization color count.
    分析图片，自动推荐最佳量化颜色数。

    This endpoint is session-less: the uploaded temp file is deleted in a
    ``finally`` block because no session exists to register it for later
    cleanup.
    此端点无会话：上传的临时文件在 finally 块中删除，因为没有会话来注册它
    以便后续清理。
    """
    temp_path = await ensure_png_tempfile(image)
    try:
        result = ImagePreprocessor.analyze_recommended_colors(temp_path, target_width_mm)
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        log.warning(
            "Auto-detect color count failed",
            extra={
                "event": "converter_auto_detect_colors_failed",
                "image_filename": image.filename or "",
                "target_width_mm": target_width_mm,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise HTTPException(
            status_code=422,
            detail=AUTO_DETECT_COLORS_FAILED_DETAIL,
        ) from exc
    finally:
        _cleanup_auto_detect_tempfile(temp_path)
    log.info(
        "Auto-detected color count",
        extra={
            "event": "converter_auto_detect_colors_done",
            "image_filename": image.filename or "",
            "target_width_mm": target_width_mm,
            "recommended": result.get("recommended", 48),
            "max_safe": result.get("max_safe", 64),
            "unique_colors": result.get("unique_colors", 0),
            "complexity_score": result.get("complexity_score", 0),
        },
    )
    return AutoDetectColorsResponse(
        recommended=result.get("recommended", 48),
        max_safe=result.get("max_safe", 64),
        unique_colors=result.get("unique_colors", 0),
        complexity_score=result.get("complexity_score", 0),
    )


@router.post("/crop", response_model=CropResponse)
async def crop_image(
    image: UploadFile = File(..., description="输入图像"),
    x: int = Form(0, description="裁剪起点 X"),
    y: int = Form(0, description="裁剪起点 Y"),
    width: int = Form(100, ge=1, description="裁剪宽度"),
    height: int = Form(100, ge=1, description="裁剪高度"),
    registry: FileRegistry = Depends(get_file_registry),
) -> CropResponse:
    """Crop an uploaded image and return the cropped result URL.
    裁剪上传的图片并返回裁剪后的文件 URL。

    Args:
        image: 上传的图片文件
        x: 裁剪起点 X 坐标
        y: 裁剪起点 Y 坐标
        width: 裁剪宽度（像素）
        height: 裁剪高度（像素）
        registry: FileRegistry 依赖

    Returns:
        CropResponse: 包含裁剪后图片 URL 和尺寸
    """
    temp_path: str | None = None
    cropped_path: str | None = None
    registered_result = False
    try:
        # 1. Save uploaded file to temp path
        temp_path = await ensure_png_tempfile(image)

        # 2. Validate that the file is a readable image
        try:
            ImagePreprocessor.get_image_dimensions(temp_path)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid image file")

        # 3. Crop image (CropRegion.clamp is called internally)
        try:
            cropped_path = ImagePreprocessor.crop_image(temp_path, x, y, width, height)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

        # 4. Get cropped image dimensions
        w, h = ImagePreprocessor.get_image_dimensions(cropped_path)

        # 5. Register cropped file and return response
        try:
            file_id = registry.register_path(
                str(uuid.uuid4()),
                cropped_path,
                ttl_seconds=EPHEMERAL_PREVIEW_TTL_SECONDS,
            )
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            log.error(
                "Crop result registration failed",
                extra={
                    "event": "converter_crop_registration_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            raise HTTPException(status_code=500, detail=_CROP_FAILED_DETAIL) from exc
        registered_result = True
        return CropResponse(
            status="ok",
            message="Image cropped successfully",
            cropped_url=f"/api/files/{file_id}",
            width=w,
            height=h,
        )
    finally:
        if registered_result:
            if temp_path != cropped_path:
                _cleanup_pre_session_temp_paths(temp_path)
        else:
            _cleanup_pre_session_temp_paths(temp_path, cropped_path)


@router.post("/preview")
async def convert_preview(
    image: UploadFile = File(..., description="输入图像"),
    source_kind: str = Form("legacy_single", description="源类型: legacy_single | legacy_multi | native_bundle"),
    lut_name: str | None = Form(None, description="LUT 名称"),
    lut_names: list[str] | str | None = Form(None, description="经典 LUT 名称列表"),
    material_type: str | None = Form(None, description="原生材料类型"),
    vendor: str | None = Form(None, description="原生厂商"),
    db_names: list[str] | str | None = Form(None, description="原生 DB 名称列表"),
    target_width_mm: float = Form(60.0, description="目标宽度 (mm)"),
    color_mode: str = Form("4-Color (RYBW)", description="颜色模式"),
    modeling_mode: str = Form("high-fidelity", description="建模模式"),
    color_layers: int | None = Form(None, description="叠色层数"),
    layer_height_mm: float | None = Form(None, description="叠色层高 (mm)"),
    model_enable: bool = Form(False, description="启用模型辅助匹配"),
    model_only: bool = Form(False, description="仅使用模型匹配"),
    model_threshold: float | None = Form(None, description="模型回退阈值"),
    model_margin: float | None = Form(None, description="模型回退边距"),
    quantize_colors: int = Form(48, description="K-Means 色彩细节（仅高保真模式生效）"),
    enable_cleanup: bool = Form(True, description="孤立像素清理"),
    svg_hole_compensation_enabled: Annotated[bool, Form(description="SVG 小洞补偿")] = False,
    svg_hole_max_area_mm2: Annotated[float, Form(ge=0.0, allow_inf_nan=False, description="补孔面积上限 (mm²)")] = 0.5,
    svg_hole_max_width_mm: Annotated[float, Form(ge=0.0, allow_inf_nan=False, description="细缝宽度上限 (mm)")] = 0.1,
    enable_outline: bool = Form(False, description="启用描边"),
    outline_width: float = Form(2.0, ge=0.5, le=10.0, description="描边宽度 (mm)"),
    svg_pixels_per_mm: float = Form(
        SVG_PIXELS_PER_MM_DEFAULT,
        ge=SVG_PIXELS_PER_MM_MIN,
        le=SVG_PIXELS_PER_MM_MAX,
        description=(
            "高保真 SVG 采样密度（px/mm）；仅高保真模式处理 SVG 时生效，"
            "直接矢量模式不使用此参数"
        ),
    ),
    hue_weight: float = Form(0.0, description="色相保护权重"),
    chroma_gate: float = Form(15.0, description="暗色彩度门槛"),
    use_lut_constrained: bool = Form(False, description="高精度LUT约束匹配"),
    auto_dynamic_range: bool = Form(False, description="自动动态范围压缩（实验性）"),
    high_precision_3d_preview: bool = Form(False, description="3D高精度颜色预览"),
    enable_smooth_vector_preview: bool = Form(
        True,
        description="原生 SVG 使用解析式平滑轻量 3D 预览",
    ),
    is_dark: bool = Form(True, description="深色主题"),
    material_source: str = Form("lut", description="颜色来源: lut | material_archive"),
    selected_materials: list[str] | str | None = Form(None, description="已选耗材目录名列表"),
    material_layer_count: int | None = Form(None, description="耗材模式叠色层数 (5-10)"),
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
    material_layer_height_mm: float | None = Form(None, description="耗材模式层高 (mm)"),
    material_grid_resolution: int | None = Form(
        None,
        description=(
            "Opt-in exhaustive-cache Lab grid resolution (64/128/256); "
            "forwarded to the solver cache lookup. ``None`` uses the backend "
            "default so low-tier caches keep working unchanged. "
            "穷举缓存 Lab 网格分辨率，None 时走后端默认。"
        ),
    ),
    material_backing_material_index: int | None = Form(
        None,
        description="耗材档案模式底板耗材索引（基于 selected_materials 的 0-based 索引）",
    ),
    large_format_enabled: bool = Form(False, description="是否处于大画幅模式"),
    replacement_regions: str | None = Form(None, description="颜色替换列表 JSON"),
    surface_model_file_id: str | None = Form(None, description="Uploaded model file id for surface overlay"),
    surface_selection_json: str | None = Form(None, description="JSON surface selection payload"),
    surface_footprint_json: str | None = Form(None, description="JSON surface footprint payload"),
    surface_placement_json: str | None = Form(None, description="JSON surface placement payload"),
    surface_model_transform_json: str | None = Form(None, description="JSON surface model transform payload"),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
    pool: WorkerPoolManager = Depends(get_worker_pool),
) -> PreviewResponse:
    """Generate a 2D color-matched preview via process pool.
    通过进程池生成 2D 颜色匹配预览图。

    CPU-intensive conversion runs in the process pool. Synchronous result
    publication runs in a thread so health and other API requests can proceed.
    CPU 密集型转换在工作进程池执行；同步结果发布在线程中完成，
    保持健康检查和其他 API 请求可响应。
    """
    _api_t0 = time.perf_counter()
    temp_path: str | None = None
    surface_original_image_path: str | None = None
    surface_config: dict | None = None
    temp_native_bundle_path: str | None = None
    svg_large_format_policy = None
    material_source = _validate_material_source(material_source)
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
            modeling_mode == "vector"
            and str(image.filename or "").lower().endswith(".svg")
        ),
    )
    try:
        svg_pixels_per_mm = normalize_svg_pixels_per_mm(svg_pixels_per_mm)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    parsed_replacement_regions = _parse_preview_replacement_regions(
        replacement_regions,
    )

    _selected_mats: list[str] | None = None
    _material_backing_index = 0
    if material_source == "material_archive":
        _selected_mats = (
            _parse_selected_materials(selected_materials)
            if selected_materials is not None
            else []
        )
        _material_backing_index = _resolve_material_backing_index(
            _selected_mats,
            material_backing_material_index,
        )
        if material_dynamic_layer_count_enabled:
            _validate_unique_dynamic_material_selection(_selected_mats)

    # Material-archive mode: skip LUT resolution entirely
    if material_source == "material_archive":
        request = LutSourceSelection.model_validate(
            {
                "source_kind": "legacy_single",
                "lut_name": "__material_archive__",
                "lut_names": [],
                "material_type": None,
                "vendor": None,
                "db_names": [],
            }
        )
        lut_path = "__material_archive__"
        resolved_lut_name = "__material_archive__"
        resolved_lut_path = "__material_archive__"
    else:
        try:
            normalized_db_names = _normalize_db_names(db_names)
            normalized_lut_names = _normalize_db_names(lut_names)
            request = LutSourceSelection.model_validate(
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
                "source_kind": request.source_kind,
                "lut_name": request.lut_name,
                "material_type": request.material_type,
                "vendor": request.vendor,
                "db_names": request.db_names,
            }
            if request.source_kind == "legacy_multi":
                source_kwargs["lut_names"] = request.lut_names
            lut_path, resolved_lut_name = LUTManager.resolve_source_selection(
                **source_kwargs
            )
        except ValueError as exc:
            detail = str(exc)
            status_code = 404 if detail.startswith("LUT not found:") else 422
            raise HTTPException(status_code=status_code, detail=detail) from exc

        resolved_lut_path = os.path.abspath(lut_path)
    if request.source_kind in ("native_bundle", "legacy_multi"):
        try:
            Path(resolved_lut_path).resolve().relative_to(Path(TEMP_DIR).resolve())
        except ValueError:
            temp_native_bundle_path = None
        else:
            temp_native_bundle_path = resolved_lut_path

    # Mint session_id at endpoint entry and bind to contextvar so worker-emitted
    # log records (image_processor_init/done, isolated_pixels_cleaned, ...) carry
    # the same id that will be returned in the preview response.
    # 在端点入口生成 session_id 并写入 contextvar，使 worker 内日志事件能溯源到最终返回的会话。
    preview_session_id = str(uuid.uuid4())
    bind_session_id(preview_session_id)

    worker_completed = False
    try:
        # 1. File upload (I/O, main thread)
        _t = time.perf_counter()
        temp_path = await ensure_png_tempfile(image)
        try:
            await asyncio.to_thread(validate_converter_source, temp_path)
        except ConverterSourceValidationError as exc:
            log.warning(
                "Converter source upload rejected",
                extra={
                    "event": "converter_source_upload_rejected",
                    "error_type": type(exc).__name__,
                    "error_message": exc.public_message,
                    "reason": exc.error_code,
                    "status_code": exc.status_code,
                },
            )
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.detail,
            ) from exc
        surface_config = resolve_surface_preview_config(
            registry=registry,
            model_file_id=surface_model_file_id,
            selection_json=surface_selection_json,
            footprint_json=surface_footprint_json,
            placement_json=surface_placement_json,
            source_path=temp_path,
            transform_json=surface_model_transform_json,
        )
        if surface_config is not None:
            surface_original_image_path = temp_path
            temp_path = surface_config["surface_artwork_path"]
            target_width_mm = float(surface_config["target_width_mm"])
        _t_upload = time.perf_counter() - _t
        is_svg_upload = str(temp_path).lower().endswith(".svg")
        _validate_svg_hole_compensation(
            enabled=svg_hole_compensation_enabled,
            image_path=temp_path,
            modeling_mode=modeling_mode,
        )
        use_large_format_svg_guard = (
            large_format_enabled
            and modeling_mode == "vector"
            and is_svg_upload
        )
        preview_cache_max_bytes = (
            _get_large_format_svg_preview_cache_max_bytes()
            if use_large_format_svg_guard
            else get_preview_cache_max_bytes()
        )
        _enforce_preview_cache_size_limit(
            image_path=temp_path,
            target_width_mm=target_width_mm,
            modeling_mode=modeling_mode,
            svg_pixels_per_mm=svg_pixels_per_mm,
            color_layers=color_layers,
            material_layer_count=material_layer_count,
            material_dynamic_layer_count_enabled=(
                material_dynamic_layer_count_enabled
            ),
            material_max_layer_count=material_max_layer_count,
            material_source=material_source,
            selected_material_count=len(_selected_mats or []),
            max_bytes=preview_cache_max_bytes,
        )
        if modeling_mode == "vector" and is_svg_upload:
            svg_large_format_policy = {
                **inspect_svg_large_format_support(temp_path),
                "inspection_source": "preview-vector-svg",
            }

        # 2. CPU computation offloaded to process pool (only paths and scalars)
        log.debug(
            "Submitting preview worker task",
            extra={
                "event": "converter_preview_submit",
                "hue_weight": hue_weight,
                "lut_name": resolved_lut_name,
                "source_kind": request.source_kind,
                "color_mode": color_mode,
                "color_layers": color_layers,
                "layer_height_mm": layer_height_mm,
                "model_enable": model_enable,
                "model_only": model_only,
                "model_threshold": model_threshold,
                "model_margin": model_margin,
                "enable_outline": enable_outline,
                "outline_width": outline_width,
                "svg_pixels_per_mm": svg_pixels_per_mm,
                "replacement_count": len(parsed_replacement_regions or []),
            },
        )
        if material_source == "material_archive":
            log.debug(
                "Material mode parsed: count=%d names=%s",
                len(_selected_mats or []),
                _selected_mats,
                extra={
                    "event": "converter_preview_material_mode_parsed",
                    "selected_material_count": len(_selected_mats or []),
                },
            )

        _worker_t0 = time.perf_counter()
        result, worker_pool_timing = await pool.submit_timed(
            worker_generate_preview,
            temp_path,
            lut_path if material_source != "material_archive" else "__material_archive__",
            target_width_mm,
            color_mode,
            modeling_mode,
            color_layers,
            layer_height_mm,
            quantize_colors,
            enable_cleanup,
            enable_outline,
            outline_width,
            is_dark,
            model_enable,
            model_only,
            model_threshold,
            model_margin,
            hue_weight,
            chroma_gate,
            use_lut_constrained,
            material_source,
            _selected_mats,
            material_layer_count,
            material_layer_height_mm,
            material_grid_resolution,
            auto_dynamic_range,
            high_precision_3d_preview,
            svg_pixels_per_mm,
            parsed_replacement_regions,
            _material_backing_index,
            material_dynamic_layer_count_enabled,
            material_min_layer_count,
            material_max_layer_count,
            material_delta_e00_tolerance,
            svg_hole_compensation_enabled,
            svg_hole_max_area_mm2,
            svg_hole_max_width_mm,
        )
        _t_worker = time.perf_counter() - _worker_t0
        worker_completed = True
    except (DynamicMaterialCandidateError, DynamicMaterialSolverError) as e:
        _handle_core_error(e, "preview generation")
    except BrokenProcessPool as e:
        raise HTTPException(
            status_code=503,
            detail=_PREVIEW_GENERATION_FAILED_DETAIL,
        ) from e
    except ROUTER_HANDLED_ERRORS as e:
        public_detail = _public_pipeline_validation_detail(
            e,
            source_is_user_upload=surface_config is None,
            modeling_mode=modeling_mode,
            source_path=surface_original_image_path or temp_path,
            surface_overlay=surface_config is not None,
        )
        if public_detail is not None:
            log.warning(
                "Converter preview input rejected",
                extra={
                    "event": "converter_preview_input_rejected",
                    "error_type": type(e).__name__,
                    "error_message": public_detail["message"],
                    "reason": public_detail["error"],
                },
            )
            raise HTTPException(status_code=422, detail=public_detail) from e
        log.exception(
            "Preview generation failed",
            extra={
                "event": "converter_preview_worker_error",
                "error_type": type(e).__name__,
                "error_message": _PREVIEW_GENERATION_FAILED_DETAIL,
            },
        )
        raise HTTPException(status_code=500, detail=_PREVIEW_GENERATION_FAILED_DETAIL)
    finally:
        if not worker_completed:
            _cleanup_pre_session_temp_paths(
                temp_path,
                surface_original_image_path,
                temp_native_bundle_path,
            )

    source_filename = image.filename

    def publish_preview_result() -> PreviewResponse:
        """Adopt worker artifacts and assemble the response off the event loop."""
        session_id: str | None = None
        publication_succeeded = False
        worker_preview_png_path: str | None = None
        worker_raw_preview_png_path: str | None = None
        worker_cache_data_path: str | None = None
        worker_cache_artifact_ref: dict | None = None
        worker_vector_parse_clip_cache_path: str | None = None
        worker_response_palette: list[dict] | None = None
        worker_gradient_groups: list[dict] | None = None
        worker_gradient_region_id_map_path: str | None = None
        worker_gradient_region_id_map: np.ndarray | None = None
        worker_result_paths: tuple[str, ...] = ()
        worker_artifact_paths: list[str] = []
        try:
            # Collect returned paths before hydration so even malformed
            # artifacts and pre-session failures have the same cleanup owner.
            worker_result_paths = tuple(
                path
                for key in (
                    "preview_png_path", "raw_preview_png_path", "cache_data_path",
                    "vector_parse_clip_cache_path", "gradient_region_id_map_path",
                )
                if isinstance(path := result.get(key), str)
            )
            worker_artifact_paths = _preview_cache_artifact_paths(
                result.get("cache_artifact_ref"),
            )
            worker_preview_png_path = result["preview_png_path"]
            candidate_raw_preview_path = result.get("raw_preview_png_path")
            if isinstance(candidate_raw_preview_path, str):
                worker_raw_preview_png_path = candidate_raw_preview_path
            worker_cache_data_path = result.get("cache_data_path")
            candidate_cache_artifact_ref = result.get("cache_artifact_ref")
            if is_preview_cache_artifact_ref(candidate_cache_artifact_ref):
                worker_cache_artifact_ref = candidate_cache_artifact_ref
            candidate_vector_cache_path = result.get("vector_parse_clip_cache_path")
            if isinstance(candidate_vector_cache_path, str):
                worker_vector_parse_clip_cache_path = candidate_vector_cache_path
            candidate_response_palette = result.get("response_palette")
            if isinstance(candidate_response_palette, list):
                worker_response_palette = candidate_response_palette
            candidate_gradient_groups = result.get("gradient_groups")
            candidate_region_map_path = result.get("gradient_region_id_map_path")
            if (
                isinstance(candidate_gradient_groups, list)
                and isinstance(candidate_region_map_path, str)
                and os.path.exists(candidate_region_map_path)
            ):
                try:
                    worker_gradient_region_id_map = np.ascontiguousarray(
                        np.load(candidate_region_map_path, allow_pickle=False),
                        dtype=np.uint32,
                    )
                    worker_gradient_groups = candidate_gradient_groups
                    worker_gradient_region_id_map_path = candidate_region_map_path
                except (OSError, ValueError, TypeError) as exc:
                    log.warning(
                        "Worker gradient-group artifact load failed",
                        extra={
                            "event": "worker_gradient_groups_adopt_failed",
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                            "path": candidate_region_map_path,
                        },
                    )
            if worker_preview_png_path is None:
                raise HTTPException(status_code=500, detail=_PREVIEW_GENERATION_FAILED_DETAIL)

            _t = time.perf_counter()
            if worker_cache_artifact_ref is not None:
                response_cache_fields = set(PREVIEW_RESPONSE_CACHE_FIELDS)
                if worker_raw_preview_png_path and os.path.exists(worker_raw_preview_png_path):
                    response_cache_fields.discard("preview_rgba")
                if (
                    worker_response_palette is not None
                    and worker_gradient_region_id_map is not None
                ):
                    response_cache_fields.difference_update(
                        {"matched_rgb", "mask_solid", "quantized_image"}
                    )
                cache_data = hydrate_preview_cache(
                    worker_cache_artifact_ref,
                    fields=response_cache_fields,
                    mmap_mode="r",
                )
            else:
                if worker_cache_data_path is None:
                    raise HTTPException(status_code=500, detail="Preview worker returned no cache data")
                # Load cache_data from disk (worker serialized to .pkl)
                with open(worker_cache_data_path, "rb") as f:
                    cache_data = pickle.load(f)
            _t_pickle_load = time.perf_counter() - _t

            # Load preview image from disk (worker saved as .png). Copy it so the
            # file handle is closed before rollback cleanup can run on Windows.
            with Image.open(worker_preview_png_path) as worker_preview_img:
                preview_img = worker_preview_img.copy()

            status_msg: str = result["status_msg"]

            # ---- Color-card mode: wholesale cache replacement (main process) ----
            # 色卡模式：用色卡渲染图整体替换 cache 中的图像/矩阵数据，使
            # GLB、分层图、调色板等所有下游自然展示色卡而非原图。
            if modeling_mode == "color-card" and cache_data is not None:
                _cc_palette = cache_data.get("color_palette") or []
                _cc_hex_list = [e["hex"] for e in _cc_palette if "hex" in e]
                if _cc_hex_list:
                    from core.color_card import render_color_card_image

                    _old_matched = cache_data.get("matched_rgb")
                    _old_mm = cache_data.get("material_matrix")

                    _card_rgba = render_color_card_image(_cc_hex_list)
                    _card_rgb = _card_rgba[:, :, :3].copy()
                    _card_h, _card_w = _card_rgba.shape[:2]

                    cache_data["matched_rgb"] = _card_rgb
                    cache_data["mask_solid"] = np.ones((_card_h, _card_w), dtype=bool)
                    cache_data["preview_rgba"] = _card_rgba
                    if "quantized_image" in cache_data:
                        cache_data["quantized_image"] = _card_rgb
                    cache_data["target_w"] = _card_w
                    cache_data["target_h"] = _card_h
                    cache_data["target_width_mm"] = target_width_mm

                    # Rebuild material_matrix: sample each colour's per-layer
                    # material assignment from the original image, then map onto
                    # the card pixels of that colour.
                    if _old_mm is not None and _old_matched is not None:
                        _n_layers = _old_mm.shape[2]
                        _new_mm = np.zeros(
                            (_card_h, _card_w, _n_layers), dtype=_old_mm.dtype,
                        )
                        for _hx in _cc_hex_list:
                            _h = _hx.lstrip("#")
                            _r, _g, _b = int(_h[0:2], 16), int(_h[2:4], 16), int(_h[4:6], 16)
                            _om = (
                                (_old_matched[:, :, 0] == _r)
                                & (_old_matched[:, :, 1] == _g)
                                & (_old_matched[:, :, 2] == _b)
                            )
                            if not _om.any():
                                continue
                            _yx = np.argwhere(_om)[0]
                            _ma = _old_mm[_yx[0], _yx[1], :]
                            _cm = (
                                (_card_rgb[:, :, 0] == _r)
                                & (_card_rgb[:, :, 1] == _g)
                                & (_card_rgb[:, :, 2] == _b)
                            )
                            _new_mm[_cm] = _ma
                        cache_data["material_matrix"] = _new_mm

                    cache_data["color_card_source_palette"] = [dict(e) for e in _cc_palette]
                    cache_data["color_palette"] = [dict(e) for e in _cc_palette]

                    log.info(
                        "Color card cache replaced in main process",
                        extra={
                            "event": "color_card_cache_replaced",
                            "color_count": len(_cc_hex_list),
                            "card_size": [_card_w, _card_h],
                        },
                    )

            vector_parse_clip_cache_blob = None
            if isinstance(cache_data, dict):
                vector_parse_clip_cache_blob = cache_data.pop(
                    "vector_parse_clip_cache_blob",
                    None,
                )

            # Reuse the session_id minted before worker submit so worker logs and the
            # returned session use the same id; SessionStore.create() will fall back to
            # a fresh UUID if the pre-minted id ever collides.
            # 复用 worker submit 前生成的 session_id，确保 worker 日志与返回会话同 id；
            # 若 id 与现有会话冲突，SessionStore.create() 会自动改用新 UUID。
            session_id = store.create(session_id=preview_session_id)
            cache_session_value: dict | None = None
            if worker_cache_artifact_ref is not None:
                cache_session_value = _with_original_preview_cache_refs(
                    worker_cache_artifact_ref,
                )
                for artifact_path in _preview_cache_artifact_paths(cache_session_value):
                    store.register_temp_file(session_id, artifact_path)

            vector_cache_max_bytes = _get_vector_parse_clip_cache_max_bytes()
            if worker_vector_parse_clip_cache_path and os.path.exists(
                worker_vector_parse_clip_cache_path,
            ):
                try:
                    vector_cache_bytes = os.path.getsize(worker_vector_parse_clip_cache_path)
                    if vector_cache_bytes <= vector_cache_max_bytes:
                        store.register_temp_file(session_id, worker_vector_parse_clip_cache_path)
                        if cache_session_value is not None:
                            cache_session_value["metadata"]["vector_parse_clip_cache_path"] = (
                                worker_vector_parse_clip_cache_path
                            )
                        cache_data["vector_parse_clip_cache_path"] = worker_vector_parse_clip_cache_path
                    else:
                        _cleanup_pre_session_temp_paths(worker_vector_parse_clip_cache_path)
                        log.debug(
                            "Vector parse/clip cache artifact persist skipped",
                            extra={
                                "event": "vector_parse_clip_cache_persist_skipped",
                                "reason": "cache_artifact_too_large",
                                "cache_bytes": int(vector_cache_bytes),
                                "max_bytes": int(vector_cache_max_bytes),
                            },
                        )
                        worker_vector_parse_clip_cache_path = None
                except ROUTER_HANDLED_ERRORS as exc:
                    log.debug(
                        "Vector parse/clip cache artifact persist skipped",
                        extra={
                            "event": "vector_parse_clip_cache_persist_skipped",
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                            "max_bytes": int(vector_cache_max_bytes),
                        },
                    )
                    _cleanup_pre_session_temp_paths(worker_vector_parse_clip_cache_path)
                    worker_vector_parse_clip_cache_path = None
            elif isinstance(vector_parse_clip_cache_blob, (bytes, bytearray)):
                vector_cache_bytes = len(vector_parse_clip_cache_blob)
                if vector_cache_bytes <= vector_cache_max_bytes:
                    vector_cache_path = None
                    try:
                        fd, vector_cache_path = tempfile.mkstemp(
                            prefix="vector_parse_clip_cache_",
                            suffix=".pkl",
                            dir=TEMP_DIR,
                        )
                        with os.fdopen(fd, "wb") as handle:
                            handle.write(vector_parse_clip_cache_blob)
                        store.register_temp_file(session_id, vector_cache_path)
                        if cache_session_value is not None:
                            cache_session_value["metadata"]["vector_parse_clip_cache_path"] = (
                                vector_cache_path
                            )
                        cache_data["vector_parse_clip_cache_path"] = vector_cache_path
                    except ROUTER_HANDLED_ERRORS as exc:
                        log.debug(
                            "Vector parse/clip cache artifact persist skipped",
                            extra={
                                "event": "vector_parse_clip_cache_persist_skipped",
                                "error_type": type(exc).__name__,
                                "error_message": str(exc),
                                "cache_bytes": int(vector_cache_bytes),
                                "max_bytes": int(vector_cache_max_bytes),
                            },
                        )
                        _cleanup_pre_session_temp_paths(vector_cache_path)
                else:
                    log.debug(
                        "Vector parse/clip cache artifact persist skipped",
                        extra={
                            "event": "vector_parse_clip_cache_persist_skipped",
                            "reason": "cache_artifact_too_large",
                            "cache_bytes": int(vector_cache_bytes),
                            "max_bytes": int(vector_cache_max_bytes),
                        },
                    )
            memory_profile = build_preview_cache_memory_profile(
                cache_data,
                session_id=session_id,
                modeling_mode=modeling_mode,
                cache_data_bytes=(
                    os.path.getsize(worker_cache_data_path)
                    if worker_cache_data_path and os.path.exists(worker_cache_data_path)
                    else None
                ),
                process_rss_bytes=get_process_rss_bytes(),
            )
            if should_log_preview_cache_memory_profile_at_info():
                log.info("Preview cache memory profile", extra=memory_profile)
            else:
                log.debug("Preview cache memory profile", extra=memory_profile)
            if cache_session_value is None and cache_data is not None:
                cache_with_originals = dict(cache_data)
                if "matched_rgb" in cache_data:
                    cache_with_originals.setdefault(
                        "original_matched_rgb",
                        cache_data["matched_rgb"],
                    )
                    cache_with_originals.setdefault(
                        "height_identity_rgb",
                        cache_with_originals["original_matched_rgb"],
                    )
                if "material_matrix" in cache_data:
                    cache_with_originals.setdefault(
                        "original_material_matrix",
                        cache_data["material_matrix"],
                    )
                if "quantized_image" in cache_data:
                    cache_with_originals.setdefault(
                        "original_quantized_image",
                        cache_data["quantized_image"],
                    )
                if "material_dynamic_layer_info" in cache_data:
                    cache_with_originals.setdefault(
                        "original_material_dynamic_layer_info",
                        copy.deepcopy(cache_data["material_dynamic_layer_info"]),
                    )
                if "material_solver_info" in cache_data:
                    cache_with_originals.setdefault(
                        "original_material_solver_info",
                        copy.deepcopy(cache_data["material_solver_info"]),
                    )
                cache_with_originals = _compact_preview_cache_material_matrices(
                    cache_with_originals,
                )
                cache_session_value = _with_original_preview_cache_refs(
                    externalize_preview_cache(
                        session_id,
                        store,
                        cache_with_originals,
                    )
                )
            if cache_session_value is not None:
                renderer_metadata = (
                    cache_session_value.get("metadata")
                    if is_preview_cache_artifact_ref(cache_session_value)
                    else cache_session_value
                )
                if isinstance(renderer_metadata, dict):
                    renderer_metadata["enable_smooth_vector_preview"] = bool(
                        enable_smooth_vector_preview
                    )
            store.put(session_id, "preview_cache", cache_session_value)
            schedule_visible_region_cache_prewarm(
                session_id,
                store,
                cache_data,
                generation=0,
            )
            if worker_gradient_groups is not None and worker_gradient_region_id_map is not None:
                store.put(session_id, "gradient_groups", worker_gradient_groups)
                store.put(
                    session_id,
                    "gradient_region_id_map",
                    worker_gradient_region_id_map,
                )
                log.debug(
                    "Gradient groups adopted from worker",
                    extra={
                        "event": "gradient_groups_adopted_from_worker",
                        "group_count": len(worker_gradient_groups),
                        "region_id_map_shape": list(worker_gradient_region_id_map.shape),
                    },
                )
            else:
                # Synchronously compute gradient-banding groups so the Color Workstation
                # can surface them (group-level multi-select + optional auto-replace)
                # without a second round-trip. Best-effort: failures are logged and do
                # not block the preview response.
                # 同步计算渐变海带纹分组，便于颜色工作站的分组多选与自动换色。
                recompute_gradient_groups_into_session(cache_data, session_id, store)
            store.put(session_id, "image_path", temp_path)
            source_basename = _resolve_upload_source_basename(source_filename, temp_path)
            store.put(session_id, "source_basename", source_basename)
            if surface_config is not None:
                store.put(session_id, "surface_overlay_enabled", True)
                store.put(session_id, "surface_model_file_id", surface_config["surface_model_file_id"])
                store.put(session_id, "surface_model_path", surface_config["surface_model_path"])
                store.put(session_id, "surface_selection", surface_config["surface_selection"])
                store.put(session_id, "surface_footprint", surface_config["surface_footprint"])
                store.put(session_id, "surface_placement", surface_config["surface_placement"])
                store.put(session_id, "surface_model_transform", surface_config["surface_model_transform"])
                store.put(session_id, "surface_artwork_path", surface_config["surface_artwork_path"])
                store.put(session_id, "surface_target_width_mm", surface_config["target_width_mm"])
                store.put(session_id, "surface_target_height_mm", surface_config["target_height_mm"])
                if surface_original_image_path is not None:
                    store.put(session_id, "surface_source_image_path", surface_original_image_path)
            store.put(session_id, "lut_path", lut_path)
            store.put(session_id, "lut_name", resolved_lut_name)
            store.put(session_id, "lut_source_kind", request.source_kind)
            store.put(session_id, "lut_names", list(request.lut_names))
            store.put(session_id, "lut_material_type", request.material_type)
            store.put(session_id, "lut_vendor", request.vendor)
            store.put(session_id, "lut_db_names", list(request.db_names))
            store.put(session_id, "color_mode", color_mode)
            store.put(session_id, "modeling_mode", modeling_mode)
            store.put(session_id, "color_layers", color_layers)
            store.put(session_id, "layer_height_mm", layer_height_mm)
            store.put(session_id, "model_enable", model_enable)
            store.put(session_id, "model_only", model_only)
            store.put(session_id, "model_threshold", model_threshold)
            store.put(session_id, "model_margin", model_margin)
            store.put(session_id, "material_source", material_source)
            store.put(
                session_id,
                "material_dynamic_layer_count_enabled",
                material_dynamic_layer_count_enabled,
            )
            store.put(session_id, "material_min_layer_count", material_min_layer_count)
            store.put(session_id, "material_max_layer_count", material_max_layer_count)
            store.put(
                session_id,
                "material_delta_e00_tolerance",
                material_delta_e00_tolerance,
            )
            if material_source == "material_archive":
                store.put(session_id, "selected_materials", _selected_mats or [])
                store.put(session_id, "material_layer_count", material_layer_count)
                store.put(session_id, "material_layer_height_mm", material_layer_height_mm)
                store.put(
                    session_id,
                    "material_grid_resolution",
                    material_grid_resolution,
                )
                store.put(
                    session_id,
                    "material_backing_material_index",
                    _material_backing_index,
                )
            store.put(session_id, "replacement_regions", parsed_replacement_regions or [])
            clear_replacement_history(session_id, store)
            store.put(session_id, "free_color_set", set())
            if svg_large_format_policy is not None:
                store.put(session_id, "svg_large_format_policy", svg_large_format_policy)
            store.register_temp_file(session_id, temp_path)
            if surface_original_image_path is not None:
                store.register_temp_file(session_id, surface_original_image_path)
            if temp_native_bundle_path is not None:
                store.register_temp_file(session_id, temp_native_bundle_path)
            # Register worker temp files for cleanup
            store.register_temp_file(session_id, worker_preview_png_path)
            if worker_raw_preview_png_path is not None:
                store.register_temp_file(session_id, worker_raw_preview_png_path)
            if worker_cache_data_path is not None:
                store.register_temp_file(session_id, worker_cache_data_path)
            if worker_gradient_region_id_map_path is not None:
                store.register_temp_file(session_id, worker_gradient_region_id_map_path)

            # Register preview image (bed-rendered, for general display)
            preview_bytes = _image_to_png_bytes(preview_img)
            preview_id = registry.register_bytes(session_id, preview_bytes, "preview.png")

            # Register raw RGBA preview (no bed, pixel-aligned with previewPixelWidth/Height)
            # Used by ColorPreview2D so SVG contour overlays and click coords align.
            preview_raw_url: str | None = None
            if worker_raw_preview_png_path and os.path.exists(worker_raw_preview_png_path):
                raw_id = registry.register_path(
                    session_id,
                    worker_raw_preview_png_path,
                    filename="preview_raw.png",
                )
                preview_raw_url = f"/api/files/{raw_id}"
            elif cache_data and "preview_rgba" in cache_data:
                raw_rgba = cache_data["preview_rgba"]
                raw_bytes = ndarray_to_png_bytes(raw_rgba)
                raw_id = registry.register_bytes(session_id, raw_bytes, "preview_raw.png")
                preview_raw_url = f"/api/files/{raw_id}"

            # Schedule segmented GLB (one Mesh per color) without blocking preview.
            _t = time.perf_counter()
            preview_glb_url: str | None = None
            try:
                preview_glb_url = _schedule_or_run_preview_glb_build(
                    session_id,
                    store,
                    registry,
                    cache_session_value if cache_session_value is not None else cache_data,
                )
            except NON_FATAL_GLB_ERRORS as e:
                # Non-fatal: log and continue without GLB
                log.warning(
                    "Segmented GLB scheduling failed",
                    extra={
                        "event": "converter_segmented_glb_failed",
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                )
            _t_glb = time.perf_counter() - _t

            _t = time.perf_counter()
            palette = (
                worker_response_palette
                if worker_response_palette is not None
                else build_preview_response_palette(cache_data)
            )

            dimensions: dict = {}
            if cache_data:
                dimensions = {
                    "width": cache_data.get("target_w", 0),
                    "height": cache_data.get("target_h", 0),
                }
            if preview_raw_url:
                dimensions["preview_raw_url"] = preview_raw_url

            _t_palette = time.perf_counter() - _t

            # Extract color contours from cache (generated by generate_segmented_glb)
            contours_data: dict[str, list[list[list[float]]]] | None = None
            if cache_data and "color_contours" in cache_data:
                contours_data = cache_data["color_contours"]
            dynamic_result = dynamic_material_result_from_cache(cache_data)

            _t_api_total = time.perf_counter() - _api_t0
            endpoint_to_enqueue_ms = round((_worker_t0 - _api_t0) * 1000, 3)
            performance_timing = {
                "total_ms": round(_t_api_total * 1000, 3),
                "upload_ms": round(_t_upload * 1000, 3),
                "worker_ms": round(_t_worker * 1000, 3),
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
                        _t_api_total - (_worker_t0 - _api_t0) - _t_worker,
                    )
                    * 1000,
                    3,
                ),
                "pickle_load_ms": round(_t_pickle_load * 1000, 3),
                "segmented_glb_ms": round(_t_glb * 1000, 3),
                "palette_ms": round(_t_palette * 1000, 3),
            }
            log.info(
                "Preview endpoint timing",
                extra={
                    "event": "converter_preview_timing",
                    "duration_ms": performance_timing["total_ms"],
                    "upload_ms": performance_timing["upload_ms"],
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
                    "pickle_load_ms": performance_timing["pickle_load_ms"],
                    "segmented_glb_ms": performance_timing["segmented_glb_ms"],
                    "palette_ms": performance_timing["palette_ms"],
                },
            )

            response = PreviewResponse(
                session_id=session_id,
                status="ok",
                message=status_msg or "Preview generated",
                preview_url=f"/api/files/{preview_id}",
                preview_glb_url=preview_glb_url,
                lut_match_mode=(cache_data.get("lut_match_info", {}) or {}).get("match_mode"),
                lut_match_info=cache_data.get("lut_match_info"),
                palette=palette,
                dimensions=dimensions,
                contours=contours_data,
                warnings=list((svg_large_format_policy or {}).get("warnings", [])),
                performance_timing=performance_timing,
                **dynamic_result.model_dump(),
            )
            publication_succeeded = True
            return response
        finally:
            if not publication_succeeded:
                extra_temp_paths = (
                    temp_path,
                    surface_original_image_path,
                    temp_native_bundle_path,
                    *worker_result_paths,
                    *worker_artifact_paths,
                )
                if session_id is None:
                    _cleanup_pre_session_temp_paths(*extra_temp_paths)
                else:
                    _rollback_preview_session_after_failure(
                        session_id=session_id,
                        store=store,
                        registry=registry,
                        extra_temp_paths=extra_temp_paths,
                    )

    # to_thread preserves the request/session logging context. Shielding keeps
    # cancellation from abandoning an active publisher that still owns files.
    publication = asyncio.create_task(asyncio.to_thread(publish_preview_result))
    try:
        return await asyncio.shield(publication)
    except asyncio.CancelledError:
        # A running thread cannot be cancelled. Drain it through repeated
        # request cancellations before reclaiming any input or output paths.
        while not publication.done():
            try:
                await asyncio.shield(publication)
            except asyncio.CancelledError:
                continue
            except Exception:
                break  # The publisher's finally has already rolled back.
        if not publication.cancelled() and publication.exception() is None:
            unpublished_response = publication.result()
            rollback = asyncio.create_task(asyncio.to_thread(
                _rollback_preview_session_after_failure,
                session_id=unpublished_response.session_id,
                store=store,
                registry=registry,
            ))
            while not rollback.done():
                try:
                    await asyncio.shield(rollback)
                except asyncio.CancelledError:
                    continue
            rollback.result()
        raise



def _compute_layer_images_cache_key(
    material_matrix: np.ndarray | None,
    preview_colors_src: object,
    slots_src: object,
    *,
    material_matrix_ref: dict | None = None,
) -> tuple:
    """Compare field revision and rendering parameters directly.
    直接比较字段代次与渲染参数；旧内存会话使用完整数据，避免覆盖误命中。
    """
    if material_matrix_ref is not None:
        source = (
            material_matrix_ref.get("path"),
            tuple(material_matrix_ref.get("shape") or ()),
            material_matrix_ref.get("dtype"),
            material_matrix_ref.get("revision"),
        )
    else:
        if material_matrix is None:
            raise ValueError("material_matrix is required for legacy layer cache keys")
        source = (material_matrix.shape, material_matrix.dtype.str, material_matrix.tobytes())
    return (source, repr(preview_colors_src), repr(slots_src))


def _require_preview_cache_for_layer_images(
    session_data: dict,
) -> tuple[dict, dict | None]:
    cache = session_data.get("preview_cache")
    if cache is None:
        raise HTTPException(
            status_code=409,
            detail=PREVIEW_CACHE_UNAVAILABLE_DETAIL,
        )
    if not isinstance(cache, dict):
        raise HTTPException(status_code=400, detail="Invalid preview cache")
    if is_preview_cache_artifact_ref(cache):
        return get_preview_cache_metadata(cache), cache
    return cache, None


def _require_preview_cache_for_heightmap(session_data: dict) -> dict:
    cache, cache_ref = _require_preview_cache_for_layer_images(session_data)
    if cache_ref is None:
        return cache
    try:
        hydrated = hydrate_preview_cache(
            cache_ref,
            fields={"matched_rgb", "mask_solid"},
            mmap_mode="r",
        )
    except (OSError, ValueError, TypeError, KeyError, EOFError) as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "Preview cache is unavailable. "
                "Re-run preview before uploading a heightmap."
            ),
        ) from exc
    cache.update(hydrated)
    return cache


def _register_cached_layer_path(
    *,
    session_id: str,
    registry: FileRegistry,
    layer_idx: int,
    path: str,
) -> str:
    file_id = registry.register_path(
        session_id,
        path,
        filename=f"layer_{layer_idx}.png",
        purpose="layer_image",
    )
    return f"/api/files/{file_id}"


def _write_private_layer_png(
    *,
    session_id: str,
    store: SessionStore,
    png_bytes: bytes,
) -> str:
    fd, path = tempfile.mkstemp(suffix=".png", dir=TEMP_DIR)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(png_bytes)
    except BaseException:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        raise
    store.register_temp_file(session_id, path)
    return path


@router.get("/layer-images/{session_id}")
def get_layer_images(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
):
    """Generate per-layer material preview images from cached preview data.
    从缓存的预览数据生成每层材料预览图。

    Returns a list of layer image URLs with material names.
    返回每层图片 URL 和材料名称列表。
    """
    session_data = _require_session(store, session_id)
    cache, cache_ref = _require_preview_cache_for_layer_images(session_data)

    color_conf = cache.get("color_conf")
    if color_conf is None:
        raise HTTPException(status_code=400, detail="Preview cache missing required data")

    # For Merged LUTs, use the corrected preview_colors and slot_names from cache
    # (constructed in P01 from LUT palette), otherwise fall back to color_conf
    preview_colors = cache.get("preview_colors")
    slots = cache.get("slot_names")

    if preview_colors is None or slots is None:
        # Fallback to color_conf for standard color modes
        preview_colors = color_conf.get("preview", {})
        slots = color_conf.get("slots", [])

    # Cache lookup: /layer-images was the single biggest latency contributor
    # after a replace (~6s for 6 layers at ~500x500) because every request
    # re-encoded every layer as PNG. Reuse cached PNG bytes when the inputs
    # that drive pixel content (material_matrix + palette) haven't changed.
    # 缓存命中：matched_rgb/调色板没改就复用已编码的 PNG bytes，免去 6 秒重算。
    material_matrix_ref = (
        cache_ref.get("fields", {}).get("material_matrix")
        if cache_ref is not None
        else None
    )
    material_matrix = None if cache_ref is not None else cache.get("material_matrix")
    cache_key = _compute_layer_images_cache_key(
        material_matrix,
        preview_colors,
        slots,
        material_matrix_ref=material_matrix_ref,
    )
    cached_entry = session_data.get("layer_images_cache")
    if (
        isinstance(cached_entry, dict)
        and cached_entry.get("key") == cache_key
        and isinstance(cached_entry.get("layers"), list)
    ):
        t_hit = time.perf_counter()
        layers_out: list[dict] = []
        for idx, item in enumerate(cached_entry["layers"]):
            png_bytes = item.get("png_bytes")
            png_path = item.get("path")
            slot_name = item.get("name", f"Layer {idx}")
            if isinstance(png_path, str) and os.path.exists(png_path):
                layer_url = _register_cached_layer_path(
                    session_id=session_id,
                    registry=registry,
                    layer_idx=idx,
                    path=png_path,
                )
            elif isinstance(png_bytes, (bytes, bytearray)):
                file_id = registry.register_bytes(
                    session_id,
                    bytes(png_bytes),
                    f"layer_{idx}.png",
                    purpose="layer_image",
                )
                layer_url = f"/api/files/{file_id}"
            else:
                # Defensive: if somehow malformed, fall through to full recompute
                # 防御性：cache 坏了就走 miss 路径全量重算，不让端点崩掉。
                cached_entry = None
                layers_out = []
                break
            layers_out.append(
                {
                    "layer_index": idx,
                    "name": slot_name,
                    "url": layer_url,
                }
            )
        if cached_entry is not None and layers_out:
            log.debug(
                "layer-images cache hit",
                extra={
                    "event": "converter_layer_images_cache_hit",
                    "n_layers": len(layers_out),
                    "duration_ms": round((time.perf_counter() - t_hit) * 1000, 1),
                },
            )
            return {"session_id": session_id, "layers": layers_out}

    if cache_ref is not None:
        try:
            hydrated = hydrate_preview_cache(
                cache_ref,
                fields={"material_matrix", "mask_solid"},
                mmap_mode="r",
            )
        except (OSError, ValueError, TypeError, KeyError, EOFError) as exc:
            raise HTTPException(
                status_code=409,
                detail=LAYER_IMAGES_PREVIEW_CACHE_UNAVAILABLE_DETAIL,
            ) from exc
        material_matrix = hydrated.get("material_matrix")
        mask_solid = hydrated.get("mask_solid")
    else:
        material_matrix = cache.get("material_matrix")
        mask_solid = cache.get("mask_solid")
    if material_matrix is None or mask_solid is None:
        raise HTTPException(status_code=400, detail="Preview cache missing required data")

    material_matrix = np.asarray(material_matrix)
    mask_solid = np.asarray(mask_solid, dtype=bool)
    h, w = material_matrix.shape[:2]
    n_layers = material_matrix.shape[2]

    # Build material_id -> rgba mapping
    # preview_colors can be either dict[str, rgba] (Merged LUT) or dict[int, rgba] (standard)
    mat_id_to_rgba: dict[int, object] = {}
    if slots and preview_colors:
        for mat_id, slot_name in enumerate(slots):
            # Try to get color by name first (Merged LUT), then by ID (standard)
            if slot_name in preview_colors:
                mat_id_to_rgba[mat_id] = preview_colors[slot_name]
            elif mat_id in preview_colors:
                mat_id_to_rgba[mat_id] = preview_colors[mat_id]

    t_miss = time.perf_counter()

    # Vectorised palette build: instead of looping over each material and
    # running ``(layer == mat_id) & mask_solid`` (O(materials * h*w) per layer
    # plus a boolean mask allocation per material), look up every pixel's RGB
    # via fancy indexing. Palette slot 0 defaults to the body-grey background
    # (220,220,220) so any pixel whose material id is not in mat_id_to_rgba
    # keeps the old visual.
    # 向量化调色板：把 N_materials×N_layers 的嵌套 mask 计算替换成单次
    # fancy indexing，层生成耗时从秒级降到几十毫秒。
    max_mat_id = (
        max(0, int(material_matrix.max())) if material_matrix.size > 0 else 0
    )
    palette_arr = np.full((max_mat_id + 1, 3), 220, dtype=np.uint8)
    for mat_id, rgba in mat_id_to_rgba.items():
        if 0 <= mat_id <= max_mat_id:
            palette_arr[mat_id] = np.asarray(rgba[:3], dtype=np.uint8)

    non_solid_mask = ~mask_solid

    # PNG encode tuned for near-flat layer previews. Default PIL compress_level
    # is 6; dropping to 1 is ~3-5x faster on these images with a negligible
    # size increase (layers are 2 colours + transparent background so entropy
    # is tiny regardless of level).
    # 层图几乎是纯色，编码级别从 6 降到 1，速度提升 3-5×，体积几乎无差。
    def _encode_fast(arr: np.ndarray) -> bytes:
        import io as _io

        buf = _io.BytesIO()
        Image.fromarray(arr).save(buf, format="PNG", compress_level=1)
        return buf.getvalue()

    def _build_layer_array(layer_idx: int) -> np.ndarray:
        layer = material_matrix[:, :, layer_idx]
        # np.clip + fancy indexing: out-of-range ids fall back to slot 0 (body grey).
        layer_clipped = np.clip(layer, 0, max_mat_id)
        layer_rgb = palette_arr[layer_clipped]
        # Build RGBA: solid shapes get alpha=255, non-solid (background) gets alpha=0.
        # This lets the frontend render a checkerboard under transparent areas.
        # RGB for non-solid is kept at (240, 240, 240) for backward compat with
        # tests that convert("RGB") and assert on the non-solid marker value.
        # 构建 RGBA：有形状区域 alpha=255，非形状区域 alpha=0（真正透明）。
        # 非形状区域 RGB 保持 (240,240,240) 兼容直接取 RGB 的下游。
        layer_img = np.zeros((h, w, 4), dtype=np.uint8)
        layer_img[..., :3] = layer_rgb
        layer_img[..., 3] = 255
        # Non-solid pixels: keep a light-grey RGB (backward compat) but set alpha=0
        layer_img[non_solid_mask, 0] = 240
        layer_img[non_solid_mask, 1] = 240
        layer_img[non_solid_mask, 2] = 240
        layer_img[non_solid_mask, 3] = 0
        return layer_img

    # Parallel PNG encoding: PIL/libpng releases the GIL during compression so
    # a ThreadPool scales well on multicore. ``min(n_layers, 4)`` keeps the
    # pool small enough to avoid thrashing on 2-core machines.
    # PNG 编码并发：libpng 释放 GIL，线程池在多核上近线性扩展。
    from concurrent.futures import ThreadPoolExecutor

    def _encode_one(layer_idx: int) -> bytes:
        return _encode_fast(_build_layer_array(layer_idx))

    max_workers = max(1, min(n_layers, 4))
    if n_layers > 1 and max_workers > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            encoded_bytes: list[bytes] = list(pool.map(_encode_one, range(n_layers)))
    else:
        encoded_bytes = [_encode_one(0)] if n_layers == 1 else []

    layers: list[dict] = []
    cached_layers: list[dict] = []
    for layer_idx, png_bytes in enumerate(encoded_bytes):
        png_path = _write_private_layer_png(
            session_id=session_id,
            store=store,
            png_bytes=png_bytes,
        )
        slot_name = (
            slots[layer_idx] if layer_idx < len(slots) else f"Layer {layer_idx}"
        )
        layers.append(
            {
                "layer_index": layer_idx,
                "name": slot_name,
                "url": _register_cached_layer_path(
                    session_id=session_id,
                    registry=registry,
                    layer_idx=layer_idx,
                    path=png_path,
                ),
            }
        )
        cached_layers.append({"name": slot_name, "path": png_path})

    # Persist the newly built PNGs so the next call with the same inputs
    # hits the fast path above.
    # 写回缓存，下一次相同 matrix 直接命中。
    store.put(
        session_id,
        "layer_images_cache",
        {"key": cache_key, "layers": cached_layers},
    )
    log.debug(
        "layer-images cache miss",
        extra={
            "event": "converter_layer_images_cache_miss",
            "n_layers": n_layers,
            "duration_ms": round((time.perf_counter() - t_miss) * 1000, 1),
            "matrix_shape": list(material_matrix.shape),
        },
    )

    return {"session_id": session_id, "layers": layers}


@router.get("/glb-status/{session_id}")
def get_segmented_glb_status(
    session_id: str,
    store: SessionStore = Depends(get_session_store),
):
    """Return the async segmented-GLB build status for *session_id*.

    The replace endpoints (``/replace-color``, ``/region-replace``, batch
    variants, ``/apply-recipe-override``) no longer wait for
    ``generate_segmented_glb`` — on a 3k-pixel-wide image that one step
    alone was responsible for ~35 s (≥75 %) of their total HTTP latency.
    They now return as soon as the PNG is ready and hand GLB regeneration
    off to a background thread (see :mod:`api.routers.converter.async_glb`).
    The frontend polls this endpoint until it sees ``status == "ready"``
    and then swaps its 3D preview to the newly produced GLB URL.
    replace 端点不再等 GLB：PNG 一就绪就响应，GLB 在后台线程跑。前端轮询
    本端点，看到 ``status == "ready"`` 后再用新 GLB URL 刷新 3D 预览。

    Status values / 状态取值：
        - ``idle``    — 该会话从未调度过 GLB 构建（通常只在预览之前出现）。
        - ``pending`` — GLB 正在后台生成；``job_token`` 标识当前任务。
        - ``ready``   — 新 GLB 已写入 FileRegistry，URL 在 ``glb_url`` 中。
        - ``error``   — 后台构建失败；安全公开文案在 ``error`` 中。

    The payload is ``{ status, glb_url, job_token, error, color_contours }``.
    ``glb_url`` is the same ``/api/files/<id>`` form the synchronous code
    used to return, so the frontend can feed it straight into
    ``previewGlbUrl`` without any rewriting. ``color_contours`` is included
    when ready so async preview keeps the same highlight data the synchronous
    response used to expose.
    返回体字段：``status`` / ``glb_url`` / ``job_token`` / ``error`` /
    ``color_contours``；``glb_url`` 与原同步路径返回的格式一致，前端无需
    额外处理即可直接写入 ``previewGlbUrl``。ready 时附带
    ``color_contours``，保证异步 preview 仍能拿到原同步响应提供的高亮轮廓。
    """

    session_data = _require_session(store, session_id)
    cache = session_data.get("preview_cache")
    # No preview cache at all: treat as idle rather than erroring so the
    # frontend can poll through the brief window between session create
    # and first /preview completion without getting spurious 409s.
    # 尚无 preview_cache：视为 idle，避免新会话短暂窗口期 polling 报 409。
    if not isinstance(cache, dict):
        return {
            "session_id": session_id,
            "status": "idle",
            "glb_url": None,
            "job_token": None,
            "error": None,
        }

    snapshot = get_glb_status(cache)
    cache_state = cache.get("metadata", {}) if is_preview_cache_artifact_ref(cache) else cache
    return {
        "session_id": session_id,
        "status": snapshot.get("status", "idle"),
        "glb_url": snapshot.get("glb_url"),
        "job_token": snapshot.get("job_token"),
        "error": snapshot.get("error"),
        "color_contours": (
            cache_state.get("color_contours")
            if snapshot.get("status") == "ready"
            else None
        ),
    }


@router.post(
    "/vector-preview-renderer",
    response_model=VectorPreviewRendererResponse,
)
def rebuild_vector_preview_renderer(
    request: VectorPreviewRendererRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> VectorPreviewRendererResponse:
    """Rebuild only the browser GLB renderer for one native Vector session.

    只为原生 Vector session 重建浏览器 GLB，不重跑 2D 预览或打印分析。
    """

    session_data = _require_session(store, request.session_id)
    cache = session_data.get("preview_cache")
    if not isinstance(cache, dict):
        raise HTTPException(status_code=409, detail=PREVIEW_CACHE_UNAVAILABLE_DETAIL)
    metadata = get_preview_cache_metadata(cache)
    modeling_mode = metadata.get("modeling_mode")
    modeling_mode_value = str(
        getattr(modeling_mode, "value", modeling_mode) or ""
    ).strip().lower()
    if modeling_mode_value != "vector":
        raise HTTPException(
            status_code=409,
            detail="The active session is not a native Vector preview.",
        )

    requested_renderer = (
        "vector_analytic"
        if request.enable_smooth_vector_preview
        else "segmented"
    )
    renderer_metadata = {
        "enable_smooth_vector_preview": bool(
            request.enable_smooth_vector_preview
        ),
        "vector_preview_renderer": requested_renderer,
    }
    job_token = schedule_glb_build(
        request.session_id,
        store,
        registry,
        cache,
        metadata_updates=renderer_metadata,
    )
    log.info(
        "Vector preview renderer rebuild scheduled",
        extra={
            "event": "converter_vector_preview_renderer_done",
            "session_id": request.session_id,
            "renderer": requested_renderer,
            "job_token": job_token,
        },
    )
    return VectorPreviewRendererResponse(
        session_id=request.session_id,
        job_token=job_token,
        renderer=requested_renderer,
    )


@router.post("/upload-heightmap")
async def upload_heightmap(
    heightmap: UploadFile = File(..., description="高度图文件"),
    session_id: str = Form(..., description="Session ID"),
    max_relief_height: float = Form(2.0, description="最大浮雕高度 (mm)"),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> HeightmapUploadResponse:
    """上传高度图并计算基于高度图的 color_height_map。

    根据高度图灰度值和 preview_cache 中的颜色匹配数据，
    计算每个调色板颜色对应区域的平均高度。

    Args:
        heightmap: 高度图图像文件
        session_id: 会话 ID
        max_relief_height: 最大浮雕高度 (mm)
        store: SessionStore 依赖
        registry: FileRegistry 依赖

    Returns:
        HeightmapUploadResponse: 包含 color_height_map 和缩略图 URL
    """
    # 1. Validate session
    session_data = _require_session(store, session_id)

    # 2. Validate preview_cache exists
    cache = _require_preview_cache_for_heightmap(session_data)

    # 3. Read uploaded file and save to temp
    temp_path = await ensure_png_tempfile(heightmap)
    store.register_temp_file(session_id, temp_path)

    # 4. Load and validate heightmap using HeightmapLoader
    result = HeightmapLoader.load_and_validate(temp_path)
    if not result["success"]:
        raise HTTPException(
            status_code=422,
            detail=result["error"] or "Invalid heightmap file",
        )

    grayscale: np.ndarray = result["grayscale"]
    original_size: tuple[int, int] = result["original_size"]  # (w, h)
    thumbnail: np.ndarray | None = result["thumbnail"]
    warnings: list[str] = list(result["warnings"])

    # 5. Check aspect ratio vs original image
    matched_rgb: np.ndarray = cache["matched_rgb"]
    target_h, target_w = matched_rgb.shape[:2]
    hm_w, hm_h = original_size

    ar_warning = HeightmapLoader._check_aspect_ratio(hm_w, hm_h, target_w, target_h)
    if ar_warning:
        warnings.append(ar_warning)

    # 6. Resize heightmap to match target dimensions
    grayscale_resized = HeightmapLoader._resize_to_target(grayscale, target_w, target_h)

    # 7. Compute per-color average height from heightmap
    base_thickness: float = PrinterConfig.LAYER_HEIGHT  # 0.08mm
    mask_solid: np.ndarray | None = cache.get("mask_solid")
    height_matrix = HeightmapLoader._map_grayscale_to_height(
        grayscale_resized,
        max_relief_height,
        base_thickness,
    )

    color_height_map: dict[str, float] = {}
    palette_data: list[dict] = cache.get("color_palette", [])

    for entry in palette_data:
        color_rgb = np.array(entry["color"], dtype=np.uint8)  # (3,)
        hex_val: str = entry["hex"]  # '#rrggbb'
        hex_key = hex_val.lstrip("#").lower()

        # Find pixels matching this color in matched_rgb
        color_mask = np.all(matched_rgb == color_rgb, axis=2)  # (H, W) bool
        if mask_solid is not None:
            color_mask = color_mask & mask_solid

        if not np.any(color_mask):
            # No pixels for this color, assign base thickness
            color_height_map[hex_key] = base_thickness
            continue

        height = float(np.mean(height_matrix[color_mask]))
        color_height_map[hex_key] = round(height, 4)

    # 8. Store heightmap data in session
    store.put(session_id, "heightmap_grayscale", grayscale_resized)
    store.put(session_id, "heightmap_original_size", original_size)
    store.put(session_id, "heightmap_max_relief_height", max_relief_height)
    store.put(session_id, "heightmap_color_height_map", color_height_map)

    # 9. Register thumbnail in FileRegistry
    thumbnail_url = ""
    if thumbnail is not None:
        thumb_bytes = ndarray_to_png_bytes(thumbnail)
        thumb_id = registry.register_bytes(session_id, thumb_bytes, "heightmap_thumb.png")
        thumbnail_url = f"/api/files/{thumb_id}"

    return HeightmapUploadResponse(
        status="ok",
        message="Heightmap uploaded and processed",
        thumbnail_url=thumbnail_url,
        original_size=original_size,
        color_height_map=color_height_map,
        warnings=warnings,
    )
