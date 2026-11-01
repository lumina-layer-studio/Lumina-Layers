"""Extractor domain API router.
Extractor 领域 API 路由模块。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import Any, List, Tuple

import cv2
import numpy as np
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from PIL import Image

from api.colorchecker_artifacts import (
    COLORCHECKER_FULL_PENDING_PURPOSE,
    cleanup_colorchecker_private_file,
    confirm_colorchecker_full_file,
    load_colorchecker_full_rgb,
    resolve_colorchecker_source_file,
    scale_corner_points,
    touch_colorchecker_private_file,
)
from api.dependencies import get_file_registry, get_session_store
from api.errors import to_http_exception
from api.file_bridge import (
    ndarray_to_png_bytes,
    pil_to_png_bytes,
    upload_to_ndarray,
    upload_to_tempfile,
)
from api.file_registry import FileRegistry
from api.preview_resources import (
    PREVIEW_CONTEXT_COLORCHECKER,
    cleanup_previews_for_owner,
    preview_dimensions,
    register_preview_bytes,
    register_preview_resource_upload,
    snapshot_public_preview_file,
    validate_public_preview_file,
)
from api.schemas.extractor import (
    ConfirmPaletteRequest,
    ExtractorManualFixRequest,
    ExtractorMergeEightColorRequest,
    ExtractorResolveCellRequest,
)
from api.schemas.responses import ExtractResponse, LutPreviewResolvedCell, ManualFixResponse
from api.session_store import SessionStore
from api.structured_logging import bind_session_id, get_logger
from config import (
    COLORCHECKER_TEMP_TTL_SECONDS,
    IMAGE_PREVIEW_JPEG_QUALITY,
    IMAGE_PREVIEW_MAX_EDGE,
    TEMP_DIR,
    ColorSystem,
    LUTMetadata,
    PaletteEntry,
)
from core.extractor import (
    EIGHT_COLOR_FULL_TOTAL_PAGES,
    apply_auto_white_balance,
    manual_fix_cell,
    rotate_image,
    run_extraction,
)
from core.lut_card_layout import (
    LutCardLayout,
    LutCardPage,
    cell_from_normalized_point,
    localize_page_layout,
    overlay_bbox_for_cell,
    resolve_extraction_page_layout,
    resolve_lut_layout,
    rgb_to_hex,
)
from core.lut_details.identity import canonicalize_lut_manufacturer
from utils.lut_manager import LUTManager

router = APIRouter(prefix="/api/extractor", tags=["Extractor"])
EPHEMERAL_PREVIEW_TTL_SECONDS = 600
EXTRACTOR_LUT_DOWNLOAD_TTL_SECONDS = 8 * 60 * 60
log = get_logger(__name__)

EXTRACTOR_HANDLED_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    AttributeError,
    OSError,
    RuntimeError,
    json.JSONDecodeError,
)
COLORCHECKER_PROCESSING_FAILED_DETAIL = (
    "ColorChecker processing failed. Recheck the source image or chart corners "
    "and try again."
)
COLORCHECKER_SERVICE_UNAVAILABLE_DETAIL = (
    "ColorChecker processing service is unavailable. "
    "Check the server ColorChecker dependencies and try again."
)
EXTRACTOR_LUT_DOWNLOAD_REGISTRATION_FAILED_DETAIL = (
    "Extractor LUT download could not be prepared. Try the extraction again."
)
EXTRACTOR_EXTRACT_FAILED_DETAIL = (
    "Color extraction failed. Recheck the source image or calibration corners "
    "and try again."
)
MANUAL_FIX_TARGET_OUT_OF_RANGE_DETAIL = (
    "Manual correction target is outside the current LUT. "
    "Refresh the preview and try again."
)
MANUAL_FIX_INVALID_COLOR_DETAIL = (
    "Manual correction color is invalid. Use a valid hex or RGB color."
)
MANUAL_FIX_FAILED_DETAIL = "Manual fix failed"
INVALID_JSON_FORM_DETAIL_TEMPLATE = (
    "Invalid {field_name} JSON. Check the form value and try again."
)


def _invalid_json_form_detail(field_name: str) -> str:
    return INVALID_JSON_FORM_DETAIL_TEMPLATE.format(field_name=field_name)


def _parse_json_form_value(raw_value: str, *, field_name: str) -> Any:
    try:
        return json.loads(raw_value)
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail=_invalid_json_form_detail(field_name),
        ) from exc


@dataclass(frozen=True)
class _DecodedColorCheckerSource:
    """Decoded ColorChecker source plus its private file identity."""

    image_bgr: np.ndarray
    source_type: str
    path: str
    filename: str
    mime_type: str


LUT_PERSIST_WARNING_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    OSError,
    RuntimeError,
    json.JSONDecodeError,
)


def _handle_core_error(e: Exception, context: str) -> None:
    """Translate core exceptions to HTTP 500 errors."""
    log.exception(
        "Extractor operation failed",
        extra={
            "event": "extractor_error",
            "error_type": type(e).__name__,
            "error_message": str(e),
            "context": context,
        },
    )
    raise to_http_exception(e, context)


def _manual_fix_validation_detail(status_msg: str | None) -> str | None:
    """Map legacy manual-fix sentinel messages to safe client errors."""
    if not isinstance(status_msg, str):
        return None
    if "索引超出范围" in status_msg:
        return MANUAL_FIX_TARGET_OUT_OF_RANGE_DETAIL
    if "格式错误" in status_msg:
        return MANUAL_FIX_INVALID_COLOR_DETAIL
    return None


def _register_final_lut_download(
    *,
    registry: FileRegistry,
    lut_path: str,
) -> tuple[str, str]:
    """Create a stable TTL-managed copy for user-facing LUT downloads."""
    suffix = os.path.splitext(lut_path)[1] or ".json"
    fd, download_path = tempfile.mkstemp(
        prefix="extractor_lut_",
        suffix=suffix,
        dir=TEMP_DIR,
    )
    os.close(fd)
    try:
        shutil.copy2(lut_path, download_path)
    except OSError:
        try:
            os.remove(download_path)
        except OSError:
            pass
        raise

    filename = os.path.basename(lut_path) or "lumina_lut.json"
    try:
        download_id = registry.register_path(
            f"extractor-lut:{uuid.uuid4().hex}",
            download_path,
            filename=filename,
            ttl_seconds=EXTRACTOR_LUT_DOWNLOAD_TTL_SECONDS,
        )
    except Exception as exc:
        try:
            os.remove(download_path)
        except OSError:
            pass
        log.error(
            "Extractor LUT download registration failed",
            extra={
                "event": "extractor_lut_download_registration_failed",
                "status_code": 500,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "lut_filename": filename,
                "suffix": suffix,
                "ttl_seconds": EXTRACTOR_LUT_DOWNLOAD_TTL_SECONDS,
            },
        )
        raise HTTPException(
            status_code=500,
            detail=EXTRACTOR_LUT_DOWNLOAD_REGISTRATION_FAILED_DETAIL,
        ) from exc
    return download_id, download_path


def _resolve_session_lut_path_or_error(
    store: SessionStore,
    session_id: str,
) -> tuple[dict[str, Any], str]:
    """Resolve a session-bound LUT path or raise a deterministic API error."""
    bind_session_id(session_id)
    session_data = store.get(session_id)
    if session_data is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "Manual correction session not found or expired. "
                "Re-run extraction before editing the LUT."
            ),
        )
    raw_lut_path = session_data.get("lut_path")
    if not isinstance(raw_lut_path, str) or not raw_lut_path.strip():
        raise HTTPException(
            status_code=409,
            detail=(
                "Manual correction LUT is missing from the session. "
                "Re-run extraction before editing the LUT."
            ),
        )
    lut_path = raw_lut_path.strip()
    if not os.path.exists(lut_path):
        raise HTTPException(
            status_code=409,
            detail=(
                "Manual correction LUT file is missing. "
                "Re-run extraction before editing the LUT."
            ),
        )
    return session_data, lut_path


def _resize_bgr_for_colorchecker_preview(image_bgr: np.ndarray) -> np.ndarray:
    """Return a display copy constrained by bounded preview config.
    按小预览配置返回受限尺寸的显示图。
    """
    from core.colorchecker.image_io import image_to_uint8_display

    display = image_to_uint8_display(image_bgr)
    h, w = display.shape[:2]
    max_edge = int(IMAGE_PREVIEW_MAX_EDGE)
    if max_edge <= 0 or max(h, w) <= max_edge:
        return display
    scale = max_edge / float(max(h, w))
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    return cv2.resize(display, (new_w, new_h), interpolation=cv2.INTER_AREA)


def _encode_colorchecker_preview_jpeg(image_bgr: np.ndarray) -> tuple[bytes, int, int]:
    """Encode a bounded ColorChecker preview JPEG.
    编码受尺寸限制的 ColorChecker JPEG 预览。
    """
    from core.colorchecker.image_io import encode_jpeg_bytes

    preview = _resize_bgr_for_colorchecker_preview(image_bgr)
    h, w = preview.shape[:2]
    return (
        encode_jpeg_bytes(preview, quality=int(IMAGE_PREVIEW_JPEG_QUALITY)),
        int(w),
        int(h),
    )


def _colorchecker_preview_dimensions(width: int, height: int) -> tuple[int, int]:
    """Return bounded preview dimensions for a full-size image.
    返回完整图片对应的小预览尺寸。
    """
    return preview_dimensions(width, height)


def _scale_colorchecker_points(
    points: list[dict[str, object]],
    *,
    source_width: float,
    source_height: float,
    target_width: float,
    target_height: float,
) -> list[dict[str, object]]:
    """Scale ColorChecker point dictionaries between coordinate spaces.
    在不同坐标空间之间缩放 ColorChecker 点字典。
    """
    if source_width <= 0 or source_height <= 0:
        return points
    scale_x = float(target_width) / float(source_width)
    scale_y = float(target_height) / float(source_height)
    scaled: list[dict[str, object]] = []
    for point in points:
        if "x" not in point or "y" not in point:
            continue
        scaled.append(
            {
                **point,
                "x": float(point["x"]) * scale_x,
                "y": float(point["y"]) * scale_y,
            }
        )
    return scaled


def _colorchecker_reference_source_response(source: object) -> dict[str, object | None]:
    raw = source if isinstance(source, dict) else {}
    return {
        "sourceType": raw.get("source_type"),
        "sourceName": raw.get("source_name"),
        "serialNumber": raw.get("serial_number"),
        "patchCount": raw.get("patch_count"),
        "labWhitePoint": raw.get("lab_white_point"),
    }


def _colorchecker_reference_summary_response(summary: dict[str, object]) -> dict[str, object | None]:
    source = summary.get("source")
    source_payload = _colorchecker_reference_source_response(source)
    return {
        "id": summary.get("id"),
        "name": summary.get("name"),
        "description": summary.get("description"),
        "source": source_payload,
        "patchCount": summary.get("patchCount"),
        "labWhitePoint": summary.get("labWhitePoint") or source_payload.get("labWhitePoint"),
        "serialNumber": summary.get("serialNumber") or source_payload.get("serialNumber"),
    }


def _parse_colorchecker_reference_form(
    reference_id: str | None,
    reference_patches: str | None,
    reference_source: str | None,
) -> dict[str, object | None]:
    has_reference_id = bool(reference_id and reference_id.strip())
    has_reference_patches = bool(reference_patches and reference_patches.strip())
    if has_reference_id and has_reference_patches:
        raise HTTPException(
            status_code=422,
            detail="reference_id and reference_patches are mutually exclusive.",
        )
    if not has_reference_patches:
        return {
            "reference_id": reference_id.strip() if has_reference_id else "dafan",
            "reference_patches": None,
            "reference_source": None,
        }
    patches = _parse_json_form_value(
        reference_patches or "[]",
        field_name="reference_patches",
    )
    if not isinstance(patches, list):
        raise HTTPException(status_code=422, detail="reference_patches must be a JSON list.")

    source: dict[str, object] | None = None
    if reference_source and reference_source.strip():
        raw_source = _parse_json_form_value(
            reference_source,
            field_name="reference_source",
        )
        if not isinstance(raw_source, dict):
            raise HTTPException(status_code=422, detail="reference_source must be a JSON object.")
        source = raw_source
    return {
        "reference_id": None,
        "reference_patches": patches,
        "reference_source": source,
    }


def _parse_colorchecker_patch_points(raw_patch_points: str | None) -> list[object] | None:
    if raw_patch_points is None:
        return None
    parsed = _parse_json_form_value(
        raw_patch_points,
        field_name="patch_points",
    )
    if parsed is None:
        return None
    if not isinstance(parsed, list):
        raise HTTPException(status_code=422, detail="patch_points must be a JSON array.")
    if len(parsed) == 0:
        return None
    if len(parsed) != 24:
        raise HTTPException(
            status_code=422,
            detail=f"patch_points must contain exactly 24 points, got {len(parsed)}.",
        )
    for point in parsed:
        if isinstance(point, dict):
            x_value = point.get("x")
            y_value = point.get("y")
        elif isinstance(point, list) and len(point) >= 2:
            x_value = point[0]
            y_value = point[1]
        else:
            raise HTTPException(
                status_code=422,
                detail="patch_points items must contain x and y coordinates.",
            )
        try:
            x_coordinate = float(x_value)
            y_coordinate = float(y_value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail="patch_points items must contain finite numeric x and y values.",
            ) from exc
        if not np.isfinite(x_coordinate) or not np.isfinite(y_coordinate):
            raise HTTPException(
                status_code=422,
                detail="patch_points items must contain finite numeric x and y values.",
            )
    return parsed


def _decode_colorchecker_source(
    registry: FileRegistry,
    source_file_id: str,
):
    """Load a private ColorChecker source artifact as decoded BGR image.
    将内部 ColorChecker 源图产物读取为 BGR 图像。
    """
    from core.colorchecker_adapter import decode_colorchecker_file

    path, filename = resolve_colorchecker_source_file(registry, source_file_id)
    mime_type = "application/octet-stream"
    decoded = decode_colorchecker_file(
        path,
        file_name=filename,
        mime_type=mime_type,
    )
    return _DecodedColorCheckerSource(
        image_bgr=decoded.image_bgr,
        source_type=str(getattr(decoded, "source_type", "") or "standard"),
        path=path,
        filename=filename,
        mime_type=mime_type,
    )


def _write_colorchecker_full_png(image_bgr: np.ndarray) -> str:
    """Write a full-size ColorChecker calibration image directly to disk.
    将完整 ColorChecker 校色图直接写入磁盘。
    """
    from core.colorchecker.image_io import image_to_uint8_display, write_png_file

    fd, path = tempfile.mkstemp(suffix=".png", dir=TEMP_DIR)
    os.close(fd)
    try:
        write_png_file(path, image_to_uint8_display(image_bgr))
    except (cv2.error, OSError, TypeError, ValueError):
        try:
            os.remove(path)
        except OSError:
            pass
        raise
    return path


def _image_to_png_bytes(img: object) -> bytes:
    """Convert ndarray/PIL image to PNG bytes."""
    if isinstance(img, np.ndarray):
        return ndarray_to_png_bytes(img)
    if isinstance(img, Image.Image):
        return pil_to_png_bytes(img)
    raise TypeError(f"Unsupported image type: {type(img)}")


def _normalize_6color_mode(color_mode: str) -> str:
    """Normalize six-color variants to the unified CMYW mode.
    将 6 色变体统一归一到 CMYW 模式。

    Args:
        color_mode (str): Raw color mode from request. (请求中的原始颜色模式)

    Returns:
        str: Normalized color mode. (归一化后的颜色模式)
    """
    if "6-Color" in str(color_mode):
        return "6-Color (CMYWGK 1296)"
    return color_mode


def _build_default_palette(color_mode: str) -> list[dict]:
    """Build default palette array based on color mode.
    根据颜色模式构建默认调色板数组。

    The raw ``color_mode`` (not the CMYW-normalized variant used by the
    extraction pipeline) must be used here so each 6-Color subtype keeps its
    own slot names — RYBWGK resolves to White/Red/Yellow/Blue/Green/Black,
    CMYWGK resolves to White/Cyan/Magenta/Green/Yellow/Black. Normalizing
    first would silently collapse RYBWGK into CMYW names in the UI.

    这里必须使用原始 ``color_mode``，而不是提取管线为共享处理路径使用的
    CMYW 归一模式。这样每个 6 色子类型都能保留自己的槽位名：RYBWGK →
    白/红/黄/蓝/绿/黑，CMYWGK → 白/青/品红/绿/黄/黑。若先归一会让 RYBWGK 在
    UI 上被静默展示成 CMYW 名字。

    Args:
        color_mode (str): Raw color mode string from the request. (请求中的
            原始颜色模式字符串，不做 6 色归一化)

    Returns:
        list[dict]: Default palette entries. (默认调色板条目列表)
    """
    color_conf = ColorSystem.get(color_mode)
    slots = color_conf.get("slots", [])
    preview = color_conf.get("preview", {})
    palette = []
    for i, slot_name in enumerate(slots):
        hex_color = None
        if i in preview:
            r, g, b = preview[i][:3]
            hex_color = f"#{r:02x}{g:02x}{b:02x}"
        palette.append(
            {
                "color": slot_name,
                "material": "PLA Basic",
                "hex_color": hex_color,
                "color_name": slot_name,
            }
        )
    return palette


def _build_merged_metadata(
    primary: LUTMetadata,
    secondary: LUTMetadata,
    color_mode: str,
    output_path: str,
    color_count: int,
) -> LUTMetadata:
    """Build merged metadata while preserving user-entered fields when available.
    构建合并后的元数据，尽量保留用户填写过的字段。
    """
    source = primary if primary.palette else secondary
    manufacturer = primary.manufacturer or secondary.manufacturer
    lut_type = primary.type or secondary.type

    if source.palette:
        return LUTMetadata(
            palette=[
                PaletteEntry(
                    color=entry.color,
                    material=entry.material,
                    hex_color=entry.hex_color,
                    color_name=entry.color_name,
                )
                for entry in source.palette
            ],
            manufacturer=manufacturer,
            type=lut_type,
            color_mode=color_mode,
            max_color_layers=source.max_color_layers,
            layer_height_mm=source.layer_height_mm,
            line_width_mm=source.line_width_mm,
            base_layers=source.base_layers,
            base_channel_idx=source.base_channel_idx,
            layer_order=source.layer_order,
        )

    metadata = LUTManager.infer_default_metadata("lumina_lut", output_path, color_count, color_mode=color_mode)
    metadata.manufacturer = manufacturer
    metadata.type = lut_type
    return metadata


def _pad_stacks_to_width(
    stacks: np.ndarray,
    target_width: int,
    *,
    pad_value: int = -1,
    prepend: bool = True,
) -> np.ndarray:
    """Pad stack rows to a common layer count."""
    rows = np.asarray(stacks, dtype=np.int32)
    if rows.ndim != 2:
        return rows.reshape(rows.shape[0], -1)
    if rows.shape[1] >= target_width:
        return rows
    padding = np.full((rows.shape[0], target_width - rows.shape[1]), pad_value, dtype=np.int32)
    if prepend:
        return np.hstack([padding, rows])
    return np.hstack([rows, padding])


def _basic_material_type(material: str | None) -> str:
    """Build the default LUT type from a selected material family.
    根据选择的耗材大类生成默认 LUT 类型。
    """
    normalized = (material or "PLA").strip() or "PLA"
    if normalized.lower().endswith(" basic"):
        return normalized
    return f"{normalized} Basic"


def _get_assets_dir() -> str:
    import sys

    if getattr(sys, "frozen", False):
        return os.path.join(os.getcwd(), "assets")
    return "assets"


def _resolve_session_lut_layout(
    *,
    color_mode: str,
    total_count: int,
    page: str = "Page 1",
    eight_color_full_export: bool = False,
    current_page: bool = False,
) -> LutCardLayout:
    if current_page:
        page_layout = resolve_extraction_page_layout(
            color_mode,
            page=page,
            eight_color_full_export=eight_color_full_export,
        )
        if total_count <= page_layout.capacity:
            return localize_page_layout(page_layout, item_count=total_count)
    return resolve_lut_layout(color_mode, total_count)


def _resolve_session_page_layout(session_data: dict | None, rgb_count: int) -> LutCardPage | None:
    if not session_data:
        return None
    color_mode = str(session_data.get("color_mode") or "")
    if not color_mode:
        return None
    layout = _resolve_session_lut_layout(
        color_mode=color_mode,
        total_count=rgb_count,
        page=str(session_data.get("page") or "Page 1"),
        eight_color_full_export=bool(session_data.get("eight_color_full_export")),
        current_page=True,
    )
    return layout.pages[0] if layout.pages else None


def _parse_page_number(page: str, default: int = 1) -> int:
    digits = "".join(ch for ch in str(page) if ch.isdigit())
    if not digits:
        return default
    page_number = int(digits)
    return page_number if page_number >= 1 else default


def _get_8color_temp_path(assets_dir: str, page_number: int, eight_color_full_export: bool) -> str:
    if eight_color_full_export:
        return os.path.join(assets_dir, f"temp_8c_full_page_{page_number}.json")
    return os.path.join(assets_dir, f"temp_8c_page_{page_number}.json")


_ROTATE_DIRECTION_TO_LABEL: dict[str, str] = {
    "ccw": "Rotate Left 90°",
    "cw": "Rotate Right 90°",
}


@router.post("/rotate")
async def extractor_rotate(
    image: UploadFile = File(..., description="待旋转的图片"),
    direction: str = "ccw",
    registry: FileRegistry = Depends(get_file_registry),
):
    """Rotate an image 90 degrees and return the rotated PNG.
    将图像旋转 90 度并返回旋转后的 PNG。

    Args:
        image: Uploaded image to rotate. (待旋转图片)
        direction: ``"ccw"`` for counter-clockwise (default, backwards
            compatible) or ``"cw"`` for clockwise. (``"ccw"`` 逆时针，默认；
            ``"cw"`` 顺时针)
    """
    direction_key = direction.strip().lower()
    rotation_label = _ROTATE_DIRECTION_TO_LABEL.get(direction_key)
    if rotation_label is None:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid rotation direction {direction!r}; expected 'cw' or 'ccw'.",
        )
    try:
        img_arr = await upload_to_ndarray(image)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    rotate_start = time.perf_counter()
    rotated = rotate_image(img_arr, rotation_label)
    if rotated is None:
        raise HTTPException(status_code=500, detail="Image rotation failed")

    rotated_bytes = ndarray_to_png_bytes(rotated)
    # Release intermediate arrays early
    # 尽早释放中间数组
    del img_arr
    h, w = rotated.shape[:2]
    file_id = registry.register_bytes(
        str(uuid.uuid4()),
        rotated_bytes,
        "rotated.png",
        ttl_seconds=EPHEMERAL_PREVIEW_TTL_SECONDS,
    )
    rotate_ms = (time.perf_counter() - rotate_start) * 1000.0
    del rotated, rotated_bytes

    log.info(
        "Extractor rotate completed",
        extra={
            "event": "extractor_rotate_done",
            "direction": str(direction_key),
            "output_width": int(w),
            "output_height": int(h),
            "rotate_ms": round(rotate_ms, 2),
        },
    )

    return {
        "preview_url": f"/api/files/{file_id}",
        "width": w,
        "height": h,
    }


@router.post("/preview-wb")
async def extractor_preview_wb(
    image: UploadFile = File(..., description="待处理的图片"),
    registry: FileRegistry = Depends(get_file_registry),
):
    """Apply auto white balance to an image and return the preview PNG.
    对图像应用自动白平衡并返回预览 PNG。
    """
    try:
        img_arr = await upload_to_ndarray(image)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    wb_start = time.perf_counter()
    balanced = apply_auto_white_balance(img_arr)
    del img_arr
    balanced_bytes = ndarray_to_png_bytes(balanced)
    h, w = balanced.shape[:2]
    file_id = registry.register_bytes(
        str(uuid.uuid4()),
        balanced_bytes,
        "wb_preview.png",
        ttl_seconds=EPHEMERAL_PREVIEW_TTL_SECONDS,
    )
    wb_ms = (time.perf_counter() - wb_start) * 1000.0
    del balanced, balanced_bytes

    log.info(
        "Extractor white-balance preview completed",
        extra={
            "event": "extractor_preview_wb_done",
            "output_width": int(w),
            "output_height": int(h),
            "wb_ms": round(wb_ms, 2),
        },
    )

    return {
        "preview_url": f"/api/files/{file_id}",
        "width": w,
        "height": h,
    }


@router.post("/colorchecker-source")
async def extractor_colorchecker_source(
    image: UploadFile = File(..., description="Image containing a ColorChecker card"),
    registry: FileRegistry = Depends(get_file_registry),
):
    """Register a private ColorChecker source image and return a bounded preview.

    注册 ColorChecker 专用私有源图，并只向前端返回受配置限制的小预览。
    """
    result = await register_preview_resource_upload(
        registry,
        image,
        context=PREVIEW_CONTEXT_COLORCHECKER,
    )

    log.info(
        "ColorChecker source image registered",
        extra={
            "event": "extractor_colorchecker_source_done",
            "full_width": result.full_width,
            "full_height": result.full_height,
            "preview_width": result.preview_width,
            "preview_height": result.preview_height,
        },
    )
    return {
        "colorchecker_source_file_id": result.resource_id,
        "source_preview_file_id": result.preview_id,
        "source_preview_url": result.preview_url,
        "full_width": result.full_width,
        "full_height": result.full_height,
        "preview_width": result.preview_width,
        "preview_height": result.preview_height,
        "source_type": result.source_type,
    }


@router.get("/colorchecker-references")
async def extractor_colorchecker_references():
    """Return available server-side ColorChecker reference summaries."""
    from core.colorchecker.reference import DEFAULT_REFERENCE_ID, list_brand_summaries

    return {
        "defaultReferenceId": DEFAULT_REFERENCE_ID,
        "references": [
            _colorchecker_reference_summary_response(summary)
            for summary in list_brand_summaries()
        ],
    }


@router.post("/colorchecker-reference-normalize")
async def extractor_colorchecker_reference_normalize(
    payload: dict[str, Any] = Body(...),
):
    """Normalize browser-parsed ColorChecker reference color patches."""
    from core.colorchecker.reference import ReferenceValidationError, normalize_reference

    patches = payload.get("patches")
    source = payload.get("source")
    if not isinstance(patches, list):
        raise HTTPException(status_code=422, detail="patches must be a list.")
    if source is not None and not isinstance(source, dict):
        raise HTTPException(status_code=422, detail="source must be an object.")
    try:
        normalized = normalize_reference(
            patches,
            source,
            source_type="user_upload",
            source_name="自定义校色基准",
        )
    except ReferenceValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "patches": normalized["patches"],
        "source": _colorchecker_reference_source_response(normalized["source"]),
        "warnings": normalized["warnings"],
    }


@router.post("/colorchecker-warp-preview")
async def extractor_colorchecker_warp_preview(
    colorchecker_source_file_id: str = Form(..., description="Private ColorChecker source file id"),
    corner_points: str = Form(..., description="4 corner points JSON [[x,y],...]"),
    corner_points_width: float | None = Form(None, description="Width of the coordinate space used by corner_points"),
    corner_points_height: float | None = Form(None, description="Height of the coordinate space used by corner_points"),
    patch_layout: str = Form("4x6", description="Patch layout: 4x6 or 3x8"),
    patch_orientation: str = Form("normal", description="Detected patch orientation"),
    registry: FileRegistry = Depends(get_file_registry),
):
    """Warp the ColorChecker region and return preview + auto 24 patch points.

    Step 1 of the two-step ColorChecker calibration flow. The user marks 4
    corners on the bounded source preview. The backend scales them to the
    private full source image, perspective-warps the region, and auto-generates
    24 sampling points for user review / adjustment.
    """
    from core.colorchecker_adapter import (
        ColorCheckerCalibrationError,
        ColorCheckerUnavailableError,
        warp_colorchecker_preview,
    )

    points = _parse_json_form_value(corner_points, field_name="corner_points")
    if not isinstance(points, list) or len(points) != 4:
        raise HTTPException(
            status_code=422,
            detail=f"corner_points must contain exactly 4 points, got {len(points) if isinstance(points, list) else 'non-list'}",
        )

    try:
        decoded = _decode_colorchecker_source(registry, colorchecker_source_file_id)
        h, w = decoded.image_bgr.shape[:2]
        scaled_points = scale_corner_points(
            points,
            source_width=corner_points_width,
            source_height=corner_points_height,
            target_width=w,
            target_height=h,
        )
        result = warp_colorchecker_preview(
            decoded.image_bgr,
            scaled_points,
            patch_layout=patch_layout,
            patch_orientation=patch_orientation,
        )
    except ColorCheckerUnavailableError as exc:
        raise HTTPException(
            status_code=500,
            detail=COLORCHECKER_SERVICE_UNAVAILABLE_DETAIL,
        ) from exc
    except ColorCheckerCalibrationError as exc:
        raise HTTPException(
            status_code=422,
            detail=COLORCHECKER_PROCESSING_FAILED_DETAIL,
        ) from exc

    del decoded
    file_id = register_preview_bytes(
        registry,
        result.preview_png,
        "colorchecker_warp_preview.png",
        ttl_seconds=COLORCHECKER_TEMP_TTL_SECONDS,
        owner_file_id=colorchecker_source_file_id,
        preview_role="warp",
    )

    log.info(
        "ColorChecker warp preview endpoint completed",
        extra={
            "event": "extractor_colorchecker_warp_preview_done",
            "preview_width": result.preview_width,
            "preview_height": result.preview_height,
            "source_width": int(w),
            "source_height": int(h),
            "patch_orientation": patch_orientation,
        },
    )

    return {
        "preview_url": f"/api/files/{file_id}",
        "preview_width": result.preview_width,
        "preview_height": result.preview_height,
        "auto_patch_points": result.auto_patch_points,
    }


@router.post("/colorchecker-detect-chart")
async def extractor_colorchecker_detect_chart(
    colorchecker_source_file_id: str = Form(..., description="Private ColorChecker source file id"),
    patch_layout: str = Form("4x6", description="Patch layout: 4x6 or 3x8"),
    assist_point: str | None = Form(None, description="Optional assist point JSON {x,y}"),
    reference_id: str | None = Form(None, description="Server reference id"),
    reference_patches: str | None = Form(None, description="Custom reference patches JSON"),
    reference_source: str | None = Form(None, description="Custom reference source JSON"),
    registry: FileRegistry = Depends(get_file_registry),
):
    """Automatically detect ColorChecker chart corners.

    自动定位图片中的 24 色卡四角；失败时返回原因，前端仍可手动调整。
    """
    from core.colorchecker_adapter import (
        ColorCheckerCalibrationError,
        ColorCheckerUnavailableError,
        detect_colorchecker_chart,
    )

    assist = None
    if assist_point:
        assist = _parse_json_form_value(assist_point, field_name="assist_point")
    reference_kwargs = _parse_colorchecker_reference_form(
        reference_id,
        reference_patches,
        reference_source,
    )

    try:
        decoded = _decode_colorchecker_source(registry, colorchecker_source_file_id)
        h, w = decoded.image_bgr.shape[:2]
        preview_w, preview_h = _colorchecker_preview_dimensions(w, h)
        scaled_assist = None
        if assist is not None:
            scaled_assist_points = _scale_colorchecker_points(
                [assist],
                source_width=preview_w,
                source_height=preview_h,
                target_width=w,
                target_height=h,
            )
            scaled_assist = scaled_assist_points[0] if scaled_assist_points else None
        result = detect_colorchecker_chart(
            decoded.image_bgr,
            patch_layout=patch_layout,
            assist_point=scaled_assist,
            **reference_kwargs,
        )
    except ColorCheckerUnavailableError as exc:
        raise HTTPException(
            status_code=500,
            detail=COLORCHECKER_SERVICE_UNAVAILABLE_DETAIL,
        ) from exc
    except ColorCheckerCalibrationError as exc:
        raise HTTPException(
            status_code=422,
            detail=COLORCHECKER_PROCESSING_FAILED_DETAIL,
        ) from exc

    del decoded
    log.info(
        "ColorChecker chart detection completed",
        extra={
            "event": "extractor_colorchecker_detect_chart_done",
            "detected": result.detected,
            "confidence": round(float(result.confidence), 4),
            "candidate_count": result.candidate_count,
            "source_width": int(w),
            "source_height": int(h),
            "preview_width": int(preview_w),
            "preview_height": int(preview_h),
        },
    )

    response = result.to_response()
    response["corners"] = _scale_colorchecker_points(
        response["corners"],  # type: ignore[arg-type]
        source_width=w,
        source_height=h,
        target_width=preview_w,
        target_height=preview_h,
    )
    response["full_width"] = int(w)
    response["full_height"] = int(h)
    response["preview_width"] = int(preview_w)
    response["preview_height"] = int(preview_h)
    return response


@router.post("/colorchecker-calibrate")
async def extractor_colorchecker_calibrate(
    colorchecker_source_file_id: str = Form(..., description="Private ColorChecker source file id"),
    corner_points: str = Form(..., description="4 corner points JSON [[x,y],...]"),
    corner_points_width: float | None = Form(None, description="Width of the coordinate space used by corner_points"),
    corner_points_height: float | None = Form(None, description="Height of the coordinate space used by corner_points"),
    patch_points: str | None = Form(None, description="24 patch points JSON [{x,y},...] or null for auto"),
    patch_layout: str = Form("4x6", description="Patch layout: 4x6 or 3x8"),
    patch_orientation: str = Form("normal", description="Detected patch orientation"),
    sample_radius: int = Form(12, description="Patch sampling radius in warped preview pixels"),
    method: str = Form("mean", description="Patch sampling method: mean or median"),
    calibration_mode: str = Form("matrix_3x3", description="Calibration model"),
    gray_affine_mode: str = Form("auto", description="Neutral gray normalization mode"),
    blur_radius: float = Form(0.0, description="Optional output blur sigma"),
    reference_id: str | None = Form(None, description="Server reference id"),
    reference_patches: str | None = Form(None, description="Custom reference patches JSON"),
    reference_source: str | None = Form(None, description="Custom reference source JSON"),
    registry: FileRegistry = Depends(get_file_registry),
):
    """Compute CCM and return private full image id + preview images.

    Step 2 of the two-step ColorChecker calibration flow. Accepts the 4
    corners and (optionally user-adjusted) 24 patch sampling points,
    computes the CCM, stores the calibrated full image as a private temporary
    file, and returns bounded previews for the browser.
    """
    from core.colorchecker_adapter import (
        ColorCheckerCalibrationError,
        ColorCheckerUnavailableError,
        apply_colorchecker_calibration,
    )

    corners = _parse_json_form_value(corner_points, field_name="corner_points")
    if not isinstance(corners, list) or len(corners) != 4:
        raise HTTPException(
            status_code=422,
            detail=f"corner_points must contain exactly 4 points, got {len(corners) if isinstance(corners, list) else 'non-list'}",
        )

    pp = _parse_colorchecker_patch_points(patch_points)
    reference_kwargs = _parse_colorchecker_reference_form(
        reference_id,
        reference_patches,
        reference_source,
    )

    cal_start = time.perf_counter()
    full_png_path: str | None = None
    full_file_id: str | None = None
    try:
        decoded = _decode_colorchecker_source(registry, colorchecker_source_file_id)
        source_h, source_w = decoded.image_bgr.shape[:2]
        scaled_corners = scale_corner_points(
            corners,
            source_width=corner_points_width,
            source_height=corner_points_height,
            target_width=source_w,
            target_height=source_h,
        )
        calibration_image: object = decoded.image_bgr
        calibration_file_name = ""
        calibration_mime_type = "application/octet-stream"
        if decoded.source_type == "raw":
            calibration_image = decoded.path
            calibration_file_name = decoded.filename
            calibration_mime_type = decoded.mime_type
            del decoded
        result = apply_colorchecker_calibration(
            calibration_image,
            scaled_corners,
            patch_points=pp,
            file_name=calibration_file_name,
            mime_type=calibration_mime_type,
            patch_layout=patch_layout,
            patch_orientation=patch_orientation,
            sample_radius=sample_radius,
            method=method,
            calibration_mode=calibration_mode,
            gray_affine_mode=gray_affine_mode,
            blur_radius=blur_radius,
            **reference_kwargs,
        )
        try:
            del decoded
        except UnboundLocalError:
            pass
        del calibration_image

        h, w = result.calibrated_image.shape[:2]
        full_png_path = _write_colorchecker_full_png(result.calibrated_image)
        full_file_id = registry.register_path(
            f"colorchecker:{uuid.uuid4()}",
            full_png_path,
            "colorchecker_calibrated.png",
            ttl_seconds=COLORCHECKER_TEMP_TTL_SECONDS,
            is_public=False,
            purpose=COLORCHECKER_FULL_PENDING_PURPOSE,
        )
        full_png_path = None

        preview_bytes, preview_w, preview_h = _encode_colorchecker_preview_jpeg(
            result.calibrated_image
        )
        overlay_bytes, _overlay_w, _overlay_h = _encode_colorchecker_preview_jpeg(
            result.overlay_image
        )
        patch_points_out = result.patch_points
        display_summary = result.display_summary
    except ColorCheckerUnavailableError as exc:
        if full_png_path is not None:
            try:
                os.remove(full_png_path)
            except OSError:
                pass
        log.warning(
            "ColorChecker calibration failed because the service is unavailable",
            extra={
                "event": "extractor_colorchecker_calibrate_failed",
                "status_code": 500,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise HTTPException(
            status_code=500,
            detail=COLORCHECKER_SERVICE_UNAVAILABLE_DETAIL,
        ) from exc
    except ColorCheckerCalibrationError as exc:
        if full_png_path is not None:
            try:
                os.remove(full_png_path)
            except OSError:
                pass
        log.warning(
            "ColorChecker calibration failed",
            extra={
                "event": "extractor_colorchecker_calibrate_failed",
                "status_code": 422,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise HTTPException(
            status_code=422,
            detail=COLORCHECKER_PROCESSING_FAILED_DETAIL,
        ) from exc
    except (cv2.error, OSError, RuntimeError, TypeError, ValueError):
        if full_file_id:
            registry.cleanup_file(full_file_id)
        if full_png_path is not None:
            try:
                os.remove(full_png_path)
            except OSError:
                pass
        raise
    finally:
        try:
            del decoded
        except UnboundLocalError:
            pass
        try:
            del result
        except UnboundLocalError:
            pass

    preview_id: str | None = None
    try:
        preview_id = register_preview_bytes(
            registry,
            preview_bytes,
            "colorchecker_calibrated_preview.jpg",
            ttl_seconds=COLORCHECKER_TEMP_TTL_SECONDS,
            owner_file_id=full_file_id,
            preview_role="calibrated",
        )
        overlay_id = register_preview_bytes(
            registry,
            overlay_bytes,
            "colorchecker_overlay_preview.jpg",
            ttl_seconds=COLORCHECKER_TEMP_TTL_SECONDS,
            owner_file_id=full_file_id,
            preview_role="overlay",
        )
    except (cv2.error, OSError, RuntimeError, TypeError, ValueError):
        if full_file_id:
            registry.cleanup_file(full_file_id)
        if preview_id:
            registry.cleanup_file(preview_id)
        raise
    finally:
        del preview_bytes, overlay_bytes

    cal_ms = (time.perf_counter() - cal_start) * 1000.0

    log.info(
        "ColorChecker calibration completed",
        extra={
            "event": "extractor_colorchecker_calibrate_done",
            "output_width": int(w),
            "output_height": int(h),
            "calibrate_ms": round(cal_ms, 2),
        },
    )

    return {
        "calibrated_preview_url": f"/api/files/{preview_id}",
        "calibrated_preview_file_id": preview_id,
        "calibrated_full_file_id": full_file_id,
        "overlay_url": f"/api/files/{overlay_id}",
        "overlay_preview_file_id": overlay_id,
        "full_width": w,
        "full_height": h,
        "preview_width": preview_w,
        "preview_height": preview_h,
        "patch_points": patch_points_out,
        "display_summary": display_summary,
    }


@router.post("/colorchecker-release")
async def extractor_colorchecker_release(
    file_id: str = Form(..., description="Private ColorChecker full-image file id"),
    registry: FileRegistry = Depends(get_file_registry),
):
    """Release one private ColorChecker source or full-image artifact."""
    released = cleanup_colorchecker_private_file(registry, file_id)
    released_previews = cleanup_previews_for_owner(registry, file_id) if released else 0
    log.info(
        "ColorChecker artifact released",
        extra={
            "event": "extractor_colorchecker_release_done",
            "released": released,
            "released_previews": released_previews,
        },
    )
    return {"status": "ok", "released": released}


@router.post("/colorchecker-confirm")
async def extractor_colorchecker_confirm(
    file_id: str = Form(..., description="Private ColorChecker full-image file id"),
    preview_file_id: str | None = Form(None, description="Existing bounded preview file id"),
    source_file_id: str | None = Form(None, description="Private ColorChecker source file id"),
    source_preview_file_id: str | None = Form(
        None,
        description="Existing bounded source preview file id",
    ),
    registry: FileRegistry = Depends(get_file_registry),
):
    """Mark one private ColorChecker full-image artifact as user-confirmed."""
    existing_preview = None
    if preview_file_id:
        existing_preview = validate_public_preview_file(
            registry,
            preview_file_id,
            owner_file_id=file_id,
            preview_role="calibrated",
        )
        if existing_preview is None:
            raise HTTPException(
                status_code=422,
                detail="ColorChecker preview does not match calibrated image",
            )
    source_preview_snapshot = None
    if source_file_id or source_preview_file_id:
        if not source_file_id or not source_preview_file_id:
            raise HTTPException(
                status_code=422,
                detail="Both source_file_id and source_preview_file_id are required",
            )
        source_preview_snapshot = snapshot_public_preview_file(
            registry,
            source_preview_file_id,
            owner_file_id=source_file_id,
            preview_role="source",
        )
        if source_preview_snapshot is None:
            raise HTTPException(
                status_code=422,
                detail="ColorChecker source preview does not match source image",
            )
    confirmed = confirm_colorchecker_full_file(registry, file_id)
    source_preview_id: str | None = None
    source_preview_url: str | None = None
    source_preview_w: int | None = None
    source_preview_h: int | None = None
    if source_preview_snapshot is not None:
        source_preview_id = register_preview_bytes(
            registry,
            source_preview_snapshot.data,
            "colorchecker_source_preview.jpg",
            ttl_seconds=COLORCHECKER_TEMP_TTL_SECONDS,
        )
        source_preview_url = f"/api/files/{source_preview_id}"
        source_preview_w = source_preview_snapshot.preview_width
        source_preview_h = source_preview_snapshot.preview_height
    if existing_preview is not None:
        preview_url, preview_w, preview_h = existing_preview
        log.info(
            "ColorChecker artifact confirmed",
            extra={
                "event": "extractor_colorchecker_confirm_done",
                "confirmed": confirmed,
                "preview_width": preview_w,
                "preview_height": preview_h,
                "preview_reused": True,
                "source_preview_preserved": source_preview_id is not None,
            },
        )
        return {
            "status": "ok",
            "confirmed": confirmed,
            "calibrated_preview_url": preview_url,
            "preview_width": preview_w,
            "preview_height": preview_h,
            "source_preview_url": source_preview_url,
            "source_preview_width": source_preview_w,
            "source_preview_height": source_preview_h,
        }
    full_rgb = load_colorchecker_full_rgb(registry, file_id)
    full_bgr = cv2.cvtColor(full_rgb, cv2.COLOR_RGB2BGR)
    preview_bytes, preview_w, preview_h = _encode_colorchecker_preview_jpeg(full_bgr)
    preview_id = register_preview_bytes(
        registry,
        preview_bytes,
        "colorchecker_confirmed_preview.jpg",
        ttl_seconds=COLORCHECKER_TEMP_TTL_SECONDS,
        owner_file_id=file_id,
        preview_role="calibrated",
    )
    log.info(
        "ColorChecker artifact confirmed",
        extra={
            "event": "extractor_colorchecker_confirm_done",
            "confirmed": confirmed,
            "preview_width": preview_w,
            "preview_height": preview_h,
            "source_preview_preserved": source_preview_id is not None,
        },
    )
    return {
        "status": "ok",
        "confirmed": confirmed,
        "calibrated_preview_url": f"/api/files/{preview_id}",
        "preview_width": preview_w,
        "preview_height": preview_h,
        "source_preview_url": source_preview_url,
        "source_preview_width": source_preview_w,
        "source_preview_height": source_preview_h,
    }


@router.post("/colorchecker-touch")
async def extractor_colorchecker_touch(
    file_id: str = Form(..., description="Private ColorChecker full-image file id"),
    registry: FileRegistry = Depends(get_file_registry),
):
    """Renew one private ColorChecker source or full-image artifact without loading it."""
    renewed = touch_colorchecker_private_file(registry, file_id)
    log.info(
        "ColorChecker artifact renewed",
        extra={
            "event": "extractor_colorchecker_touch_done",
            "renewed": renewed,
        },
    )
    return {"status": "ok", "renewed": renewed}


@router.post("/extract")
async def extractor_extract(
    image: UploadFile | None = File(None, description="Calibration board image"),
    corner_points: str = Form(..., description="4 个角点坐标 JSON 数组 [[x,y],...]"),
    color_mode: str = Form("4-Color (RYBW)", description="标准颜色模式"),
    page: str = Form("Page 1", description="8-Color 页码"),
    eight_color_full_export: bool = Form(False, description="8 色是否来自全量分页导出"),
    offset_x: int = Form(0, description="水平采样偏移"),
    offset_y: int = Form(0, description="垂直采样偏移"),
    zoom: float = Form(1.0, description="透视校正缩放"),
    distortion: float = Form(0.0, description="畸变校正"),
    vignette_correction: bool = Form(False, description="暗角校正"),
    auto_wb: bool = Form(False, description="Enable auto white balance"),
    colorchecker_calibrated_file_id: str | None = Form(
        None,
        description="Private ColorChecker full-image id to use instead of uploaded image",
    ),
    corner_points_width: float | None = Form(
        None,
        description="Width of the coordinate space used by corner_points",
    ),
    corner_points_height: float | None = Form(
        None,
        description="Height of the coordinate space used by corner_points",
    ),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ExtractResponse:
    """Extract colors from a photographed calibration board.
    从拍摄的标定板图像中提取颜色。
    """
    # Parse corner_points from JSON string
    points_raw = _parse_json_form_value(corner_points, field_name="corner_points")

    if not isinstance(points_raw, list) or len(points_raw) != 4:
        raise HTTPException(
            status_code=422,
            detail=f"corner_points must contain exactly 4 points, got {len(points_raw) if isinstance(points_raw, list) else 'non-list'}",
        )
    try:
        points: List[List[int]] = [
            [int(round(float(point[0]))), int(round(float(point[1])))]
            for point in points_raw
        ]
    except (IndexError, KeyError, TypeError, ValueError) as e:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid corner_points coordinates: {e}",
        ) from e

    requested_color_mode = LUTManager._canonicalize_legacy_color_mode(color_mode) or color_mode
    effective_color_mode = _normalize_6color_mode(requested_color_mode)

    if colorchecker_calibrated_file_id:
        if auto_wb:
            raise HTTPException(
                status_code=422,
                detail="auto_wb cannot be used with a ColorChecker calibrated image",
            )
        img_arr = load_colorchecker_full_rgb(registry, colorchecker_calibrated_file_id)
        points = scale_corner_points(
            points,
            source_width=corner_points_width,
            source_height=corner_points_height,
            target_width=int(img_arr.shape[1]),
            target_height=int(img_arr.shape[0]),
        )
    else:
        if image is None:
            raise HTTPException(status_code=422, detail="image is required")
        try:
            img_arr = await upload_to_ndarray(image)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))

    # Call core extraction (field name mapping: distortion->barrel, vignette_correction->bright)
    extract_start = time.perf_counter()
    try:
        vis_img, preview_img, lut_path, status_msg = run_extraction(
            img=img_arr,
            points=points,
            offset_x=offset_x,
            offset_y=offset_y,
            zoom=zoom,
            barrel=distortion,
            bright=vignette_correction,
            color_mode=requested_color_mode,
            page_choice=page,
            auto_wb=auto_wb,
            eight_color_full_export=eight_color_full_export,
        )
        extract_ms = (time.perf_counter() - extract_start) * 1000.0
    except EXTRACTOR_HANDLED_ERRORS as e:
        _handle_core_error(e, "Color extraction")

    if lut_path is None:
        error_message = (
            status_msg.strip()
            if isinstance(status_msg, str) and status_msg.strip()
            else "run_extraction returned no LUT path"
        )
        log.error(
            "Extractor extraction returned no LUT path",
            extra={
                "event": "extractor_extract_failed",
                "status_code": 500,
                "error_type": "ExtractorMissingLutPath",
                "error_message": error_message,
                "color_mode": requested_color_mode,
                "page": page,
                "eight_color_full_export": bool(eight_color_full_export),
                "extract_ms": round(extract_ms, 1),
            },
        )
        raise HTTPException(
            status_code=500,
            detail=EXTRACTOR_EXTRACT_FAILED_DETAIL,
        )

    # Create session and store state
    session_id = store.create()
    store.put(session_id, "lut_path", lut_path)
    store.put(session_id, "color_mode", requested_color_mode)
    store.put(session_id, "page", page)
    store.put(session_id, "eight_color_full_export", bool(eight_color_full_export))

    # For 8-Color mode: save page-specific temp file
    if "8-Color" in effective_color_mode and lut_path:
        assets_dir = _get_assets_dir()
        os.makedirs(assets_dir, exist_ok=True)
        max_page = EIGHT_COLOR_FULL_TOTAL_PAGES if eight_color_full_export else 2
        page_idx = min(max(_parse_page_number(page), 1), max_page)
        temp_path = _get_8color_temp_path(assets_dir, page_idx, eight_color_full_export)
        try:
            rgb, stacks, metadata = LUTManager.load_lut_with_metadata(lut_path)
            if stacks is None:
                stacks = np.zeros((len(rgb), 0), dtype=np.int32)
            LUTManager.save_keyed_json(temp_path, rgb, stacks, metadata)
            store.put(session_id, "lut_path", temp_path)
            lut_path = temp_path
        except LUT_PERSIST_WARNING_ERRORS as e:
            log.warning(
                "Failed to save 8-color temp LUT page",
                extra={
                    "event": "extractor_temp_lut_save_failed",
                    "page_idx": page_idx,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )

    # For 5-Color Extended mode: save page-specific temp file
    if "5-Color" in effective_color_mode and lut_path:
        import sys

        if getattr(sys, "frozen", False):
            assets_dir = os.path.join(os.getcwd(), "assets")
        else:
            assets_dir = "assets"
        os.makedirs(assets_dir, exist_ok=True)
        page_idx: int = 1 if "1" in str(page) else 2
        temp_path = os.path.join(assets_dir, f"temp_5c_ext_page_{page_idx}.json")
        try:
            rgb, stacks, metadata = LUTManager.load_lut_with_metadata(lut_path)
            if stacks is None:
                stacks = np.zeros((len(rgb), 0), dtype=np.int32)
            LUTManager.save_keyed_json(temp_path, rgb, stacks, metadata)
            store.put(session_id, "lut_path", temp_path)
            lut_path = temp_path
        except LUT_PERSIST_WARNING_ERRORS as e:
            log.warning(
                "Failed to save 5-color-ext temp LUT page",
                extra={
                    "event": "extractor_temp_lut_save_failed",
                    "page_idx": page_idx,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )

    # Register a stable final LUT download separately from the editable
    # session LUT. Paged manual-fix flows must keep editing the temp page that
    # merge endpoints consume.
    try:
        lut_download_id, _lut_download_path = _register_final_lut_download(
            registry=registry,
            lut_path=lut_path,
        )
    except OSError as e:
        _handle_core_error(e, "Extractor LUT download registration")
    try:
        layout_rgb, _layout_stacks, _layout_metadata = LUTManager.load_lut_with_metadata(lut_path)
        lut_layout = _resolve_session_lut_layout(
            color_mode=requested_color_mode,
            total_count=len(layout_rgb),
            page=page,
            eight_color_full_export=bool(eight_color_full_export),
            current_page=True,
        )
    except LUT_PERSIST_WARNING_ERRORS:
        lut_layout = None

    # Register warp view (visualization)
    warp_view_id = ""
    if vis_img is not None:
        vis_bytes = _image_to_png_bytes(vis_img)
        warp_view_id = registry.register_bytes(session_id, vis_bytes, "warp_view.png")

    # Register LUT preview
    lut_preview_id = ""
    if preview_img is not None:
        preview_bytes = _image_to_png_bytes(preview_img)
        lut_preview_id = registry.register_bytes(session_id, preview_bytes, "lut_preview.png")

    log.info(
        "Extractor extract completed",
        extra={
            "event": "extractor_extract_done",
            "color_mode": requested_color_mode,
            "page": page,
            "eight_color_full_export": bool(eight_color_full_export),
            "lut_path": str(lut_path),
            "extract_ms": round(extract_ms, 1),
        },
    )

    return ExtractResponse(
        session_id=session_id,
        status="ok",
        message=status_msg or "Extraction complete",
        lut_download_url=f"/api/files/{lut_download_id}",
        warp_view_url=f"/api/files/{warp_view_id}" if warp_view_id else "",
        lut_preview_url=f"/api/files/{lut_preview_id}" if lut_preview_id else "",
        default_palette=_build_default_palette(requested_color_mode),
        lut_layout=lut_layout.to_dict() if lut_layout is not None else None,
    )


@router.post("/manual-fix")
def extractor_manual_fix(
    request: ExtractorManualFixRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ManualFixResponse:
    """Manually override a single LUT cell color value.
    手动覆盖单个 LUT 格点的颜色值。
    """
    # Resolve lut_path: prefer session lookup, fallback to direct path
    lut_path = request.lut_path.strip()
    session_data = None
    if request.session_id:
        session_data, lut_path = _resolve_session_lut_path_or_error(
            store,
            request.session_id,
        )
    elif not lut_path:
        raise HTTPException(
            status_code=422,
            detail="manual fix requires session_id or lut_path",
        )

    if not os.path.exists(lut_path):
        raise HTTPException(
            status_code=404,
            detail="Manual correction LUT file not found.",
        )

    manual_fix_start = time.perf_counter()
    try:
        page_layout = None
        if lut_path:
            rgb_for_layout, _stacks_for_layout, _metadata_for_layout = LUTManager.load_lut_with_metadata(lut_path)
            page_layout = _resolve_session_page_layout(session_data, len(rgb_for_layout))
        preview_result, status_msg = manual_fix_cell(
            coord=request.cell_coord,
            row_index=request.row_index,
            color_input=request.override_color,
            lut_path=lut_path,
            page_layout=page_layout,
        )
    except EXTRACTOR_HANDLED_ERRORS as e:
        _handle_core_error(e, "Manual fix")
    manual_fix_ms = (time.perf_counter() - manual_fix_start) * 1000.0

    if preview_result is None:
        validation_detail = _manual_fix_validation_detail(status_msg)
        if validation_detail:
            raise HTTPException(status_code=422, detail=validation_detail)
        raise HTTPException(status_code=500, detail=MANUAL_FIX_FAILED_DETAIL)

    # Register updated preview
    preview_bytes = _image_to_png_bytes(preview_result)
    has_valid_session = bool(request.session_id and store.exists(request.session_id))
    sid_for_registry = request.session_id if has_valid_session else str(uuid.uuid4())
    preview_id = registry.register_bytes(
        sid_for_registry,
        preview_bytes,
        "lut_preview.png",
        ttl_seconds=None if has_valid_session else EPHEMERAL_PREVIEW_TTL_SECONDS,
    )
    cell_coord_row = int(request.cell_coord[0]) if request.cell_coord is not None else None
    cell_coord_col = int(request.cell_coord[1]) if request.cell_coord is not None else None

    log.info(
        "Extractor manual fix completed",
        extra={
            "event": "extractor_manual_fix_done",
            "cell_coord_row": cell_coord_row,
            "cell_coord_col": cell_coord_col,
            "row_index": int(request.row_index) if request.row_index is not None else None,
            "override_color": str(request.override_color),
            "has_session": bool(has_valid_session),
            "manual_fix_ms": round(manual_fix_ms, 2),
        },
    )

    return ManualFixResponse(
        status="ok",
        message=status_msg or "Cell updated",
        lut_preview_url=f"/api/files/{preview_id}",
        lut_layout=(
            localize_page_layout(page_layout, len(rgb_for_layout)).to_dict()
            if page_layout is not None
            else None
        ),
    )


@router.post("/resolve-cell", response_model=LutPreviewResolvedCell)
def extractor_resolve_cell(
    request: ExtractorResolveCellRequest,
    store: SessionStore = Depends(get_session_store),
) -> LutPreviewResolvedCell:
    """Resolve a LUT preview click using the backend LUT card layout."""
    session_data, lut_path = _resolve_session_lut_path_or_error(
        store,
        request.session_id,
    )

    try:
        rgb, _stacks, _metadata = LUTManager.load_lut_with_metadata(lut_path)
    except EXTRACTOR_HANDLED_ERRORS as e:
        _handle_core_error(e, "Resolve LUT preview cell")

    color_mode = str(session_data.get("color_mode") or "")
    layout = _resolve_session_lut_layout(
        color_mode=color_mode,
        total_count=len(rgb),
        page=str(session_data.get("page") or "Page 1"),
        eight_color_full_export=bool(session_data.get("eight_color_full_export")),
        current_page=True,
    )
    try:
        cell = cell_from_normalized_point(
            layout,
            card_index=request.card_index,
            x=request.x,
            y=request.y,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid card_index: {exc}") from exc
    if cell is None:
        raise HTTPException(status_code=404, detail="Clicked cell is outside the valid LUT area")

    cell_rgb = tuple(int(v) for v in rgb[cell.row_index])
    return LutPreviewResolvedCell(
        cell=cell.to_dict(),
        rgb=cell_rgb,
        hex=rgb_to_hex(cell_rgb),
        overlay_bbox=overlay_bbox_for_cell(cell),
    )


@router.post("/merge-5color-extended")
def extractor_merge_5color_extended(
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ExtractResponse:
    """Merge two 5-Color Extended pages into a single LUT.
    将两页 5-Color Extended 合并为单个 LUT。
    """
    import sys
    from config import LUT_FILE_PATH

    if getattr(sys, "frozen", False):
        assets_dir = os.path.join(os.getcwd(), "assets")
    else:
        assets_dir = "assets"

    path1 = os.path.join(assets_dir, "temp_5c_ext_page_1.json")
    path2 = os.path.join(assets_dir, "temp_5c_ext_page_2.json")

    if not os.path.exists(path1) or not os.path.exists(path2):
        raise HTTPException(
            status_code=400,
            detail="Missing temp pages. Please extract Page 1 and Page 2 first.",
        )

    merge_start = time.perf_counter()
    try:
        rgb1, stacks1, meta1 = LUTManager.load_lut_with_metadata(path1)
        rgb2, stacks2, meta2 = LUTManager.load_lut_with_metadata(path2)
        rgb1 = rgb1.reshape(-1, 3)
        rgb2 = rgb2.reshape(-1, 3)
        merged_rgb = np.vstack([rgb1, rgb2])

        # Merge stacks if available. Page 1 is the 5-layer base page while
        # Page 2 is the 6-layer extended page; pad Page 1 with a viewing-side
        # Air layer so the merged JSON carries one canonical 6-layer recipe set.
        stacks_compatible = stacks1 is not None and stacks2 is not None
        if stacks_compatible:
            target_stack_width = max(int(stacks1.shape[1]), int(stacks2.shape[1]), 6)
            merged_stacks = np.vstack(
                [
                    _pad_stacks_to_width(stacks1, target_stack_width, prepend=True),
                    _pad_stacks_to_width(stacks2, target_stack_width, prepend=True),
                ]
            )
        else:
            merged_stacks = np.zeros((len(merged_rgb), 0), dtype=np.int32)

        metadata = _build_merged_metadata(meta1, meta2, "5-Color Extended", LUT_FILE_PATH, len(merged_rgb))
        if merged_stacks.ndim == 2 and merged_stacks.shape[1] > 0:
            metadata.max_color_layers = int(merged_stacks.shape[1])
        LUTManager.save_keyed_json(LUT_FILE_PATH, merged_rgb, merged_stacks, metadata)
    except EXTRACTOR_HANDLED_ERRORS as e:
        _handle_core_error(e, "5-Color Extended merge")
    merge_ms = (time.perf_counter() - merge_start) * 1000.0

    # Create session for merged result
    session_id = store.create()
    try:
        lut_download_id, lut_download_path = _register_final_lut_download(
            registry=registry,
            lut_path=LUT_FILE_PATH,
        )
    except OSError as e:
        _handle_core_error(e, "5-Color Extended LUT download registration")
    store.put(session_id, "lut_path", lut_download_path)
    store.put(session_id, "color_mode", "5-Color Extended")

    log.info(
        "Extractor 5-Color Extended merge completed",
        extra={
            "event": "extractor_merge_5color_extended_done",
            "merged_rgb_count": int(merged_rgb.shape[0]),
            "stacks_compatible": bool(stacks_compatible),
            "merge_ms": round(merge_ms, 2),
        },
    )

    return ExtractResponse(
        session_id=session_id,
        status="ok",
        message=f"5-Color Extended LUT merged ({merged_rgb.shape[0]}x{merged_rgb.shape[1]})",
        lut_download_url=f"/api/files/{lut_download_id}",
        warp_view_url="",
        lut_preview_url="",
        default_palette=_build_default_palette("5-Color Extended"),
    )


@router.post("/merge-8color")
def extractor_merge_8color(
    request: ExtractorMergeEightColorRequest | None = None,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ExtractResponse:
    """Merge extracted 8-Color pages into a single LUT.
    将提取得到的 8 色分页结果合并为单个 LUT。
    """
    from config import LUT_FILE_PATH

    eight_color_full_export = bool(request.eight_color_full_export) if request is not None else False
    assets_dir = _get_assets_dir()
    total_pages = EIGHT_COLOR_FULL_TOTAL_PAGES if eight_color_full_export else 2
    page_paths = [
        _get_8color_temp_path(assets_dir, page_number, eight_color_full_export)
        for page_number in range(1, total_pages + 1)
    ]
    missing_pages = [
        str(page_number)
        for page_number, page_path in enumerate(page_paths, start=1)
        if not os.path.exists(page_path)
    ]

    if missing_pages:
        missing_hint = ", ".join(missing_pages[:8])
        if len(missing_pages) > 8:
            missing_hint += ", ..."
        raise HTTPException(
            status_code=400,
            detail=(
                f"Missing temp pages. Please extract all required pages first. Missing: {missing_hint}"
            ),
        )

    merge_start = time.perf_counter()
    try:
        rgb_parts = []
        stack_parts = []
        metadata_parts = []
        stacks_compatible = True
        expected_stack_width = None

        for page_path in page_paths:
            rgb, stacks, metadata = LUTManager.load_lut_with_metadata(page_path)
            rgb_parts.append(rgb.reshape(-1, 3))
            metadata_parts.append(metadata)
            if stacks is None:
                stacks_compatible = False
                continue
            stacks = stacks.reshape(stacks.shape[0], -1)
            if expected_stack_width is None:
                expected_stack_width = stacks.shape[1]
            elif stacks.shape[1] != expected_stack_width:
                stacks_compatible = False
            stack_parts.append(stacks)

        merged_rgb = np.vstack(rgb_parts)

        if stacks_compatible and stack_parts and len(stack_parts) == len(page_paths):
            merged_stacks = np.vstack(stack_parts)
        else:
            merged_stacks = np.zeros((len(merged_rgb), 0), dtype=np.int32)

        metadata = _build_merged_metadata(
            metadata_parts[0],
            metadata_parts[-1],
            "8-Color Max",
            LUT_FILE_PATH,
            len(merged_rgb),
        )
        LUTManager.save_keyed_json(LUT_FILE_PATH, merged_rgb, merged_stacks, metadata)
    except EXTRACTOR_HANDLED_ERRORS as e:
        _handle_core_error(e, "8-Color merge")
    merge_ms = (time.perf_counter() - merge_start) * 1000.0

    # Create session for merged result
    session_id = store.create()
    try:
        lut_download_id, lut_download_path = _register_final_lut_download(
            registry=registry,
            lut_path=LUT_FILE_PATH,
        )
    except OSError as e:
        _handle_core_error(e, "8-Color LUT download registration")
    store.put(session_id, "lut_path", lut_download_path)
    store.put(session_id, "color_mode", "8-Color Max")

    log.info(
        "Extractor 8-Color merge completed",
        extra={
            "event": "extractor_merge_8color_done",
            "eight_color_full_export": bool(eight_color_full_export),
            "total_pages": int(total_pages),
            "merged_rgb_count": int(merged_rgb.shape[0]),
            "stacks_compatible": bool(stacks_compatible),
            "merge_ms": round(merge_ms, 2),
        },
    )

    return ExtractResponse(
        session_id=session_id,
        status="ok",
        message=(
            f"8-Color{' Full' if eight_color_full_export else ''} LUT merged "
            f"({merged_rgb.shape[0]}x{merged_rgb.shape[1]})"
        ),
        lut_download_url=f"/api/files/{lut_download_id}",
        warp_view_url="",
        lut_preview_url="",
        default_palette=_build_default_palette("8-Color Max"),
    )


@router.post("/confirm-palette")
def confirm_palette(
    request: ConfirmPaletteRequest,
    store: SessionStore = Depends(get_session_store),
) -> dict:
    """Accept user-confirmed palette and save to session.
    接受用户确认的调色板并写入会话。

    Args:
        request (ConfirmPaletteRequest): Palette confirmation request. (调色板确认请求)
        store (SessionStore): Session store dependency. (会话存储)

    Returns:
        dict: Confirmation status. (确认状态)

    Raises:
        HTTPException: 422 if color name is blank, 404 if session not found.
            (颜色名称为空返回 422，session 不存在返回 404)
    """
    for entry in request.palette:
        if not entry.color or not entry.color.strip():
            raise HTTPException(status_code=422, detail="Color name cannot be blank")

    confirm_start = time.perf_counter()
    bind_session_id(request.session_id)
    session_data = store.get(request.session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session {request.session_id} not found")

    manufacturer = canonicalize_lut_manufacturer(request.manufacturer)
    palette_entries = [
        PaletteEntry(
            color=e.color.strip(),
            material=e.material.strip() if e.material else "PLA Basic",
            hex_color=e.hex_color,
            color_name=e.color_name.strip() if e.color_name and e.color_name.strip() else None,
        )
        for e in request.palette
    ]
    lut_type = request.type.strip() or _basic_material_type(
        palette_entries[0].material if palette_entries else None
    )

    metadata = LUTMetadata(
        palette=palette_entries,
        manufacturer=manufacturer,
        type=lut_type,
        color_mode=session_data.get("color_mode"),
    )

    # Persist palette to the LUT JSON file on disk
    lut_path = session_data.get("lut_path")
    persist_warning = None
    if lut_path and os.path.exists(lut_path):
        try:
            rgb, stacks, existing_metadata = LUTManager.load_lut_with_metadata(lut_path)
            existing_metadata.palette = palette_entries
            existing_metadata.manufacturer = manufacturer
            existing_metadata.type = lut_type
            if not existing_metadata.color_mode and session_data.get("color_mode"):
                existing_metadata.color_mode = session_data["color_mode"]
            if stacks is None:
                stacks = np.zeros((len(rgb), 0), dtype=np.int32)
            LUTManager.save_keyed_json(lut_path, rgb, stacks, existing_metadata)
            metadata = existing_metadata
        except LUT_PERSIST_WARNING_ERRORS as e:
            persist_warning = f"调色板已确认，但持久化到磁盘失败: {e}"
            log.warning(
                "Failed to persist confirmed palette",
                extra={
                    "event": "extractor_persist_palette_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )

    store.put(request.session_id, "lut_metadata", metadata)
    confirm_ms = (time.perf_counter() - confirm_start) * 1000.0

    log.info(
        "Extractor palette confirmation completed",
        extra={
            "event": "extractor_confirm_palette_done",
            "palette_size": int(len(request.palette)),
            "manufacturer": str(manufacturer),
            "lut_type": str(lut_type),
            "persisted_to_disk": bool(
                lut_path is not None and os.path.exists(lut_path) and persist_warning is None
            ),
            "confirm_ms": round(confirm_ms, 2),
        },
    )

    if persist_warning:
        return {"status": "warning", "message": persist_warning}
    return {"status": "ok", "message": "调色板已确认"}
