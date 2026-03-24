"""Converter domain API router.
Converter 领域 API 路由模块。
"""

from __future__ import annotations

import asyncio
import os
import pickle
import tempfile
import time
import uuid
import zipfile

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image
from pydantic import BaseModel

from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_bridge import ensure_png_tempfile, ndarray_to_png_bytes, pil_to_png_bytes, upload_to_tempfile
from api.file_registry import FileRegistry
from api.schemas.converter import (
    BedSizeItem,
    BedSizeListResponse,
    ColorMergePreviewRequest,
    ColorReplaceRequest,
    ConvertGenerateRequest,
    LargeFormatGenerateRequest,
    RegionDetectRequest,
    RegionDetectResponse,
    RegionReplaceRequest,
    RegionReplaceResponse,
    ResetReplacementsRequest,
)
from api.schemas.responses import (
    AutoDetectColorsResponse,
    BatchItemResult,
    BatchResponse,
    ColorReplaceResponse,
    CropResponse,
    GenerateResponse,
    HeightmapUploadResponse,
    LargeFormatGenerateResponse,
    MergePreviewResponse,
    PreviewResponse,
    ResetReplacementsResponse,
)
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager
from api.workers.converter_workers import (
    worker_batch_convert_item,
    worker_generate_model,
    worker_generate_preview,
)
from core.color_merger import ColorMerger
from core.image_preprocessor import ImagePreprocessor
from core.color_replacement import ColorReplacementManager
from core.converter import (
    convert_image_to_3d,
    extract_color_palette,
    generate_empty_bed_glb,
    generate_segmented_glb,
    _compute_connected_region_mask_4n,
)
from config import BedManager, ModelingMode as CoreModelingMode, PrinterConfig
from core.heightmap_loader import HeightmapLoader
from utils.lut_manager import LUTManager

router = APIRouter(prefix="/api/convert", tags=["Converter"])

_STUB_RESPONSE: dict[str, str] = {
    "status": "not_implemented",
    "message": "Phase 2 will integrate core logic",
}


def _handle_core_error(e: Exception, context: str) -> None:
    """将 core 模块异常转换为 HTTP 500 错误。"""
    print(f"[API] {context} error: {e}")
    raise HTTPException(status_code=500, detail=f"{context} failed: {str(e)}")


def _require_session(store: SessionStore, session_id: str) -> dict:
    """获取 session 数据，不存在时抛出 404。"""
    data = store.get(session_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return data


def _require_preview_cache(session_data: dict) -> dict:
    """获取 preview_cache，不存在时抛出 409。"""
    cache = session_data.get("preview_cache")
    if cache is None:
        raise HTTPException(status_code=409, detail="No preview cache. Call POST /api/convert/preview first.")
    return cache


def _image_to_png_bytes(img: object) -> bytes:
    """将 ndarray 或 PIL Image 转换为 PNG 字节流。"""
    if isinstance(img, np.ndarray):
        return ndarray_to_png_bytes(img)
    if isinstance(img, Image.Image):
        return pil_to_png_bytes(img)
    raise TypeError(f"Unsupported image type: {type(img)}")


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
    except Exception as e:
        _handle_core_error(e, "Bed preview generation")

    if glb_path is None:
        raise HTTPException(status_code=500, detail="Failed to generate bed preview")

    glb_id = registry.register_path("bed-preview", glb_path)
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
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"颜色分析失败: {e}")
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
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
    file_id = registry.register_path("crop", cropped_path)
    return CropResponse(
        status="ok",
        message="Image cropped successfully",
        cropped_url=f"/api/files/{file_id}",
        width=w,
        height=h,
    )


@router.post("/preview")
async def convert_preview(
    image: UploadFile = File(..., description="输入图像"),
    lut_name: str = Form(..., description="LUT 名称"),
    target_width_mm: float = Form(60.0, description="目标宽度 (mm)"),
    auto_bg: bool = Form(False, description="自动去背景"),
    bg_tol: int = Form(40, description="背景容差"),
    color_mode: str = Form("4-Color (RYBW)", description="颜色模式"),
    modeling_mode: str = Form("high-fidelity", description="建模模式"),
    quantize_colors: int = Form(48, description="K-Means 色彩细节"),
    enable_cleanup: bool = Form(True, description="孤立像素清理"),
    hue_weight: float = Form(0.0, description="色相保护权重"),
    chroma_gate: float = Form(15.0, description="暗色彩度门槛"),
    is_dark: bool = Form(True, description="深色主题"),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
    pool: WorkerPoolManager = Depends(get_worker_pool),
) -> PreviewResponse:
    """Generate a 2D color-matched preview via process pool.
    通过进程池生成 2D 颜色匹配预览图。

    File upload and session/registry operations run on the main thread.
    CPU-intensive preview generation is offloaded to the worker pool.
    文件上传和 session/registry 操作在主线程完成。
    CPU 密集型预览生成卸载到工作进程池。
    """
    _api_t0 = time.perf_counter()

    # Resolve LUT path
    lut_path = LUTManager.get_lut_path(lut_name)
    if lut_path is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}")

    # 1. File upload (I/O, main thread)
    _t = time.perf_counter()
    temp_path = await ensure_png_tempfile(image)
    _t_upload = time.perf_counter() - _t

    # 2. CPU computation offloaded to process pool (only paths and scalars)
    try:
        print(f"[API convert_preview] hue_weight={hue_weight}, lut_name={lut_name}, color_mode={color_mode}")
        _t = time.perf_counter()
        result = await pool.submit(
            worker_generate_preview,
            temp_path,
            lut_path,
            target_width_mm,
            auto_bg,
            bg_tol,
            color_mode,
            modeling_mode,
            quantize_colors,
            enable_cleanup,
            is_dark,
            hue_weight,
            chroma_gate,
        )
        _t_worker = time.perf_counter() - _t
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Preview generation timed out")
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Preview generation failed: {str(e)}")

    # 3. Result processing (I/O + Session, main thread)
    if result["preview_png_path"] is None:
        raise HTTPException(status_code=500, detail=result["status_msg"] or "Preview generation failed")

    # Load cache_data from disk (worker serialized to .pkl)
    _t = time.perf_counter()
    with open(result["cache_data_path"], "rb") as f:
        cache_data = pickle.load(f)
    _t_pickle_load = time.perf_counter() - _t

    # Load preview image from disk (worker saved as .png)
    preview_img = Image.open(result["preview_png_path"])

    status_msg: str = result["status_msg"]

    # Create session and store state
    session_id = store.create()
    store.put(session_id, "preview_cache", cache_data)
    store.put(session_id, "image_path", temp_path)
    store.put(session_id, "lut_path", lut_path)
    store.put(session_id, "lut_name", lut_name)
    store.put(session_id, "replacement_regions", [])
    store.put(session_id, "replacement_history", [])
    store.put(session_id, "free_color_set", set())
    # Save a pristine copy of matched_rgb for reset-replacements
    if cache_data and "matched_rgb" in cache_data:
        store.put(session_id, "original_matched_rgb", cache_data["matched_rgb"].copy())
    store.register_temp_file(session_id, temp_path)
    # Register worker temp files for cleanup
    store.register_temp_file(session_id, result["preview_png_path"])
    store.register_temp_file(session_id, result["cache_data_path"])

    # Register preview image
    preview_bytes = _image_to_png_bytes(preview_img)
    preview_id = registry.register_bytes(session_id, preview_bytes, "preview.png")

    # Generate segmented GLB (one Mesh per color)
    _t = time.perf_counter()
    preview_glb_url: str | None = None
    try:
        glb_path = generate_segmented_glb(cache_data)
        if glb_path and os.path.exists(glb_path):
            glb_id = registry.register_path(session_id, glb_path)
            preview_glb_url = f"/api/files/{glb_id}"
    except Exception as e:
        # Non-fatal: log and continue without GLB
        print(f"[API] Segmented GLB generation failed (non-fatal): {e}")
    _t_glb = time.perf_counter() - _t

    # Build palette with quantized_hex, matched_hex, pixel_count, percentage
    _t = time.perf_counter()
    raw_palette: list[dict] = cache_data.get("color_palette", []) if cache_data else []
    quantized_image = cache_data.get("quantized_image") if cache_data else None
    matched_rgb_arr = cache_data.get("matched_rgb") if cache_data else None
    mask_solid_arr = cache_data.get("mask_solid") if cache_data else None

    palette: list[dict] = []
    if raw_palette and matched_rgb_arr is not None and mask_solid_arr is not None:
        matched_to_quantized: dict[str, str] = {}
        if quantized_image is not None:
            solid_mask = mask_solid_arr
            q_pixels = quantized_image[solid_mask]  # (N, 3)
            m_pixels = matched_rgb_arr[solid_mask]  # (N, 3)

            # Vectorized: encode RGB triplets as uint32 scalars, find dominant
            # quantized color per matched color in a single np.unique pass.
            m_enc = (m_pixels[:, 0].astype(np.uint32) << 16) | \
                    (m_pixels[:, 1].astype(np.uint32) << 8) | \
                    m_pixels[:, 2].astype(np.uint32)
            q_enc = (q_pixels[:, 0].astype(np.uint32) << 16) | \
                    (q_pixels[:, 1].astype(np.uint32) << 8) | \
                    q_pixels[:, 2].astype(np.uint32)

            pair_key = m_enc.astype(np.uint64) * (1 << 24) + q_enc.astype(np.uint64)
            unique_keys, counts = np.unique(pair_key, return_counts=True)

            u_m = (unique_keys >> 24).astype(np.uint32)
            u_q = (unique_keys & 0xFFFFFF).astype(np.uint32)

            order = np.lexsort((-counts, u_m))
            sorted_m = u_m[order]
            sorted_q = u_q[order]
            _, first_idx = np.unique(sorted_m, return_index=True)

            for mk, qk in zip(sorted_m[first_idx], sorted_q[first_idx]):
                m_hex = f"#{(mk >> 16) & 0xFF:02x}{(mk >> 8) & 0xFF:02x}{mk & 0xFF:02x}"
                q_hex = f"#{(qk >> 16) & 0xFF:02x}{(qk >> 8) & 0xFF:02x}{qk & 0xFF:02x}"
                matched_to_quantized[m_hex] = q_hex

        for entry in raw_palette:
            m_hex = entry["hex"]  # '#rrggbb'
            q_hex = matched_to_quantized.get(m_hex, m_hex)
            palette.append(
                {
                    "quantized_hex": q_hex,
                    "matched_hex": m_hex,
                    "pixel_count": entry["count"],
                    "percentage": entry["percentage"],
                }
            )

    dimensions = {}
    if cache_data:
        dimensions = {
            "width": cache_data.get("target_w", 0),
            "height": cache_data.get("target_h", 0),
        }

    _t_palette = time.perf_counter() - _t

    # Extract color contours from cache (generated by generate_segmented_glb)
    contours_data: dict[str, list[list[list[float]]]] | None = None
    if cache_data and "color_contours" in cache_data:
        contours_data = cache_data["color_contours"]

    _t_api_total = time.perf_counter() - _api_t0
    print(f"\n{'=' * 60}")
    print(f"[API PREVIEW] Total endpoint time: {_t_api_total:.2f}s")
    print(f"  upload={_t_upload:.2f}s, worker={_t_worker:.2f}s, "
          f"pickle_load={_t_pickle_load:.2f}s")
    print(f"  segmented_glb={_t_glb:.2f}s, palette={_t_palette:.2f}s")
    print(f"{'=' * 60}")

    return PreviewResponse(
        session_id=session_id,
        status="ok",
        message=status_msg or "Preview generated",
        preview_url=f"/api/files/{preview_id}",
        preview_glb_url=preview_glb_url,
        palette=palette,
        dimensions=dimensions,
        contours=contours_data,
    )


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
    cache = _require_preview_cache(session_data)

    material_matrix = cache.get("material_matrix")
    mask_solid = cache.get("mask_solid")
    color_conf = cache.get("color_conf")
    if material_matrix is None or mask_solid is None or color_conf is None:
        raise HTTPException(status_code=400, detail="Preview cache missing required data")

    h, w = material_matrix.shape[:2]
    n_layers = material_matrix.shape[2]
    
    # For Merged LUTs, use the corrected preview_colors and slot_names from cache
    # (constructed in P01 from LUT palette), otherwise fall back to color_conf
    preview_colors = cache.get("preview_colors")
    slots = cache.get("slot_names")
    
    if preview_colors is None or slots is None:
        # Fallback to color_conf for standard color modes
        preview_colors = color_conf.get("preview", {})
        slots = color_conf.get("slots", [])

    # Build material_id -> rgba mapping
    # preview_colors can be either dict[str, rgba] (Merged LUT) or dict[int, rgba] (standard)
    mat_id_to_rgba = {}
    if slots and preview_colors:
        for mat_id, slot_name in enumerate(slots):
            # Try to get color by name first (Merged LUT), then by ID (standard)
            if slot_name in preview_colors:
                mat_id_to_rgba[mat_id] = preview_colors[slot_name]
            elif mat_id in preview_colors:
                mat_id_to_rgba[mat_id] = preview_colors[mat_id]

    layers = []
    for layer_idx in range(n_layers):
        layer = material_matrix[:, :, layer_idx]
        # 浅灰背景
        layer_img = np.ones((h, w, 3), dtype=np.uint8) * 220

        for mat_id, rgba in mat_id_to_rgba.items():
            mat_mask = (layer == mat_id) & mask_solid
            if np.any(mat_mask):
                layer_img[mat_mask] = rgba[:3]

        # 非实体区域用更浅的灰
        layer_img[~mask_solid] = [240, 240, 240]

        png_bytes = _image_to_png_bytes(Image.fromarray(layer_img))
        file_id = registry.register_bytes(session_id, png_bytes, f"layer_{layer_idx}.png")

        slot_name = slots[layer_idx] if layer_idx < len(slots) else f"Layer {layer_idx}"
        layers.append(
            {
                "layer_index": layer_idx,
                "name": slot_name,
                "url": f"/api/files/{file_id}",
            }
        )

    return {"session_id": session_id, "layers": layers}


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
    cache = _require_preview_cache(session_data)

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

        # Average grayscale value at matching pixel positions
        avg_gray = float(np.mean(grayscale_resized[color_mask]))

        # Map to height range [base_thickness, max_relief_height]
        height = base_thickness + (avg_gray / 255.0) * (max_relief_height - base_thickness)
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


class _GenerateBody(BaseModel):
    """Wrapper combining session_id with generate parameters."""

    session_id: str
    params: ConvertGenerateRequest


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

    # 1. Session validation (main thread)
    session_data = _require_session(store, body.session_id)
    cache = _require_preview_cache(session_data)

    request = body.params

    # Retrieve paths stored during preview
    image_path: str | None = session_data.get("image_path")
    lut_path: str | None = session_data.get("lut_path")
    if not image_path or not os.path.exists(image_path):
        raise HTTPException(status_code=409, detail="Image file missing. Call POST /api/convert/preview first.")
    if not lut_path or not os.path.exists(lut_path):
        raise HTTPException(status_code=409, detail="LUT file missing. Call POST /api/convert/preview first.")

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

    free_color_set = session_data.get("free_color_set") or None
    if request.free_color_set is not None:
        free_color_set = request.free_color_set

    # Convert API ModelingMode enum to core ModelingMode enum
    core_modeling_mode = CoreModelingMode(request.modeling_mode.value)

    # Resolve height_mode for relief branching
    # 解析 height_mode 用于浮雕分支选择
    height_mode = request.height_mode or "color"

    # If heightmap mode, save session heightmap to temp file for worker process
    # 高度图模式时，将 session 中的高度图保存为临时文件供工作进程使用
    heightmap_path: str | None = None
    if request.enable_relief and height_mode == "heightmap":
        heightmap_grayscale = session_data.get("heightmap_grayscale")
        if heightmap_grayscale is not None:
            fd, hm_temp_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            Image.fromarray(heightmap_grayscale).save(hm_temp_path)
            heightmap_path = hm_temp_path
            store.register_temp_file(body.session_id, hm_temp_path)

    # 2a. Serialize cached matched_rgb to temp file if requested
    # 当存在区域替换时，将缓存的 matched_rgb 序列化为临时文件供 Worker 使用
    matched_rgb_path: str | None = None
    if request.use_cached_matched_rgb:
        cached_matched_rgb = cache.get("matched_rgb")
        if cached_matched_rgb is not None:
            fd, mr_temp_path = tempfile.mkstemp(suffix=".npy")
            os.close(fd)
            np.save(mr_temp_path, cached_matched_rgb)
            matched_rgb_path = mr_temp_path
            store.register_temp_file(body.session_id, mr_temp_path)

    # 2b. Collect scalar parameters into a dict for the worker
    params: dict = {
        "target_width_mm": request.target_width_mm,
        "spacer_thick": request.spacer_thick,
        "structure_mode": request.structure_mode.value,
        "auto_bg": request.auto_bg,
        "bg_tol": request.bg_tol,
        "color_mode": request.color_mode.value,
        "add_loop": request.add_loop,
        "loop_width": request.loop_width,
        "loop_length": request.loop_length,
        "loop_hole": request.loop_hole,
        "loop_pos": request.loop_pos,
        "loop_angle": request.loop_angle,
        "loop_offset_x": request.loop_offset_x,
        "loop_offset_y": request.loop_offset_y,
        "loop_position_preset": request.loop_position_preset,
        "modeling_mode": core_modeling_mode,
        "quantize_colors": request.quantize_colors,
        "replacement_regions": replacement_regions,
        "separate_backing": request.separate_backing,
        "enable_relief": request.enable_relief,
        "height_mode": height_mode,
        "heightmap_path": heightmap_path,
        "color_height_map": request.color_height_map,
        "heightmap_max_height": request.heightmap_max_height,
        "enable_cleanup": request.enable_cleanup,
        "enable_outline": request.enable_outline,
        "outline_width": request.outline_width,
        "enable_cloisonne": request.enable_cloisonne,
        "wire_width_mm": request.wire_width_mm,
        "wire_height_mm": request.wire_height_mm,
        "free_color_set": free_color_set,
        "enable_coating": request.enable_coating,
        "coating_height_mm": request.coating_height_mm,
        "hue_weight": request.hue_weight,
        "chroma_gate": request.chroma_gate,
        "matched_rgb_path": matched_rgb_path,
        "printer_id": request.printer_id,
        "slicer": request.slicer,
    }

    # 3. CPU computation offloaded to process pool (only paths and scalars)
    worker_t0 = time.perf_counter()
    try:
        result = await pool.submit(
            worker_generate_model,
            image_path,
            lut_path,
            params,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="3MF generation timed out")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"3MF generation failed: {str(e)}")
    worker_elapsed = time.perf_counter() - worker_t0

    # 4. Result processing (I/O + FileRegistry, main thread)
    threemf_path: str | None = result.get("threemf_path")
    glb_path: str | None = result.get("glb_path")
    status_msg: str = result.get("status_msg", "")

    if not threemf_path or not os.path.exists(threemf_path):
        raise HTTPException(status_code=500, detail=status_msg or "3MF generation failed")

    # Register output files via FileRegistry
    sid = body.session_id
    download_id = registry.register_path(sid, threemf_path)

    preview_3d_url: str | None = None
    if glb_path and os.path.exists(glb_path):
        glb_id = registry.register_path(sid, glb_path)
        preview_3d_url = f"/api/files/{glb_id}"

    api_total = time.perf_counter() - api_t0
    print(
        f"\n[API] /api/convert/generate total: {api_total:.2f}s "
        f"(worker: {worker_elapsed:.2f}s, overhead: {api_total - worker_elapsed:.2f}s)"
    )

    return GenerateResponse(
        status="ok",
        message=status_msg or "Model generated",
        download_url=f"/api/files/{download_id}",
        preview_3d_url=preview_3d_url,
        threemf_disk_path=threemf_path,
    )


# ---------------------------------------------------------------------------
# Large-format tiled generation
# ---------------------------------------------------------------------------


class _LargeFormatBody(BaseModel):
    """Wrapper combining session_id with large-format parameters."""

    session_id: str
    params: LargeFormatGenerateRequest


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
    import math

    # 1. Session validation
    session_data = _require_session(store, body.session_id)
    _require_preview_cache(session_data)

    lf = body.params
    request = lf.params

    image_path: str | None = session_data.get("image_path")
    lut_path: str | None = session_data.get("lut_path")
    if not image_path or not os.path.exists(image_path):
        raise HTTPException(status_code=409, detail="Image file missing. Call POST /api/convert/preview first.")
    if not lut_path or not os.path.exists(lut_path):
        raise HTTPException(status_code=409, detail="LUT file missing. Call POST /api/convert/preview first.")

    # 2. Compute tile grid
    with Image.open(image_path) as img:
        px_w, px_h = img.size

    total_w_mm = request.target_width_mm
    total_h_mm = lf.target_height_mm
    tile_w_mm = lf.tile_width_mm
    tile_h_mm = lf.tile_height_mm

    cols = max(1, math.ceil(total_w_mm / tile_w_mm))
    rows = max(1, math.ceil(total_h_mm / tile_h_mm))

    px_per_mm_x = px_w / total_w_mm
    px_per_mm_y = px_h / total_h_mm

    # 3. Pre-compute global relief max height for 2.5D consistency
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

    # 4. Build shared worker params (same as /generate, minus per-tile fields)
    core_modeling_mode = CoreModelingMode(request.modeling_mode.value)
    height_mode = request.height_mode or "color"

    replacement_regions = session_data.get("replacement_regions") or None
    if request.replacement_regions is not None:
        replacement_regions = [
            {"quantized_hex": r.quantized_hex, "matched_hex": r.matched_hex, "replacement_hex": r.replacement_hex}
            for r in request.replacement_regions
        ]
    free_color_set = session_data.get("free_color_set") or None
    if request.free_color_set is not None:
        free_color_set = request.free_color_set

    base_params: dict = {
        "spacer_thick": request.spacer_thick,
        "structure_mode": request.structure_mode.value,
        "auto_bg": request.auto_bg,
        "bg_tol": request.bg_tol,
        "color_mode": request.color_mode.value,
        "add_loop": request.add_loop,
        "loop_width": request.loop_width,
        "loop_length": request.loop_length,
        "loop_hole": request.loop_hole,
        "loop_pos": request.loop_pos,
        "loop_angle": request.loop_angle,
        "loop_offset_x": request.loop_offset_x,
        "loop_offset_y": request.loop_offset_y,
        "loop_position_preset": request.loop_position_preset,
        "modeling_mode": core_modeling_mode,
        "quantize_colors": request.quantize_colors,
        "replacement_regions": replacement_regions,
        "separate_backing": request.separate_backing,
        "enable_relief": request.enable_relief,
        "height_mode": height_mode,
        "color_height_map": request.color_height_map,
        "heightmap_max_height": request.heightmap_max_height,
        "enable_cleanup": request.enable_cleanup,
        "enable_outline": request.enable_outline,
        "outline_width": request.outline_width,
        "enable_cloisonne": request.enable_cloisonne,
        "wire_width_mm": request.wire_width_mm,
        "wire_height_mm": request.wire_height_mm,
        "free_color_set": free_color_set,
        "enable_coating": request.enable_coating,
        "coating_height_mm": request.coating_height_mm,
        "hue_weight": request.hue_weight,
        "chroma_gate": request.chroma_gate,
        "printer_id": request.printer_id,
        "slicer": request.slicer,
        "relief_global_max_height": relief_global_max_height,
    }

    # 5. Crop tiles and submit workers
    sid = body.session_id
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    full_img = Image.open(image_path)
    hm_gray = (
        session_data.get("heightmap_grayscale") if (request.enable_relief and height_mode == "heightmap") else None
    )

    futures = []
    tile_labels: list[str] = []

    for r in range(rows):
        for c in range(cols):
            # mm bounds
            x0_mm = c * tile_w_mm
            y0_mm = r * tile_h_mm
            x1_mm = min(x0_mm + tile_w_mm, total_w_mm)
            y1_mm = min(y0_mm + tile_h_mm, total_h_mm)
            cur_tile_w = x1_mm - x0_mm
            cur_tile_h = y1_mm - y0_mm

            # pixel bounds
            px_x0 = int(round(x0_mm * px_per_mm_x))
            px_y0 = int(round(y0_mm * px_per_mm_y))
            px_x1 = int(round(x1_mm * px_per_mm_x))
            px_y1 = int(round(y1_mm * px_per_mm_y))
            px_x1 = min(px_x1, px_w)
            px_y1 = min(px_y1, px_h)

            tile_img = full_img.crop((px_x0, px_y0, px_x1, px_y1))
            fd, tile_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            tile_img.save(tile_path)
            store.register_temp_file(sid, tile_path)

            tile_params = dict(base_params, target_width_mm=cur_tile_w)

            # Tile-specific heightmap
            if hm_gray is not None:
                hm_tile = hm_gray[px_y0:px_y1, px_x0:px_x1]
                fd2, hm_tile_path = tempfile.mkstemp(suffix=".png")
                os.close(fd2)
                Image.fromarray(hm_tile).save(hm_tile_path)
                store.register_temp_file(sid, hm_tile_path)
                tile_params["heightmap_path"] = hm_tile_path

            label = f"{base_name}_R{r + 1}C{c + 1}"
            tile_labels.append(label)
            futures.append(pool.submit(worker_generate_model, tile_path, lut_path, tile_params))

    full_img.close()

    # 6. Collect results
    successful_paths: list[tuple[str, str]] = []
    errors: list[str] = []
    for label, fut in zip(tile_labels, futures):
        try:
            result = await fut
            tp = result.get("threemf_path")
            if tp and os.path.exists(tp):
                successful_paths.append((label, tp))
            else:
                errors.append(f"{label}: generation failed — {result.get('status_msg', 'unknown')}")
        except Exception as e:
            errors.append(f"{label}: {e}")

    if not successful_paths:
        detail = "All tiles failed"
        if errors:
            detail += ": " + "; ".join(errors[:5])
        raise HTTPException(status_code=500, detail=detail)

    # 7. Package into ZIP
    fd, zip_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for label, tp in successful_paths:
            zf.write(tp, f"{label}.3mf")

    download_id = registry.register_path(sid, zip_path)

    total_tiles = cols * rows
    ok_count = len(successful_paths)
    msg = f"Generated {ok_count}/{total_tiles} tiles ({cols}×{rows})"
    if errors:
        msg += f" — {len(errors)} failed"

    return LargeFormatGenerateResponse(
        status="ok",
        message=msg,
        download_url=f"/api/files/{download_id}",
        tile_count=ok_count,
        grid_cols=cols,
        grid_rows=rows,
    )


@router.post("/batch")
async def convert_batch(
    images: list[UploadFile] = File(..., description="批量图像"),
    lut_name: str = Form(..., description="LUT 名称"),
    target_width_mm: float = Form(60.0, description="目标宽度 (mm)"),
    spacer_thick: float = Form(1.2, description="底板厚度 (mm)"),
    structure_mode: str = Form("Double-sided", description="打印结构模式"),
    auto_bg: bool = Form(False, description="自动去背景"),
    bg_tol: int = Form(40, description="背景容差"),
    color_mode: str = Form("4-Color (RYBW)", description="颜色模式"),
    modeling_mode: str = Form("high-fidelity", description="建模模式"),
    quantize_colors: int = Form(48, description="K-Means 色彩细节"),
    enable_cleanup: bool = Form(True, description="孤立像素清理"),
    hue_weight: float = Form(0.0, description="色相保护权重"),
    chroma_gate: float = Form(15.0, description="暗色彩度门槛"),
    registry: FileRegistry = Depends(get_file_registry),
    pool: WorkerPoolManager = Depends(get_worker_pool),
) -> BatchResponse:
    """Batch-convert multiple images via process pool.
    通过进程池批量转换多张图像。

    File uploads and FileRegistry operations run on the main thread.
    Each batch item's CPU-intensive conversion is submitted sequentially
    to the worker pool, one at a time.
    文件上传和 FileRegistry 操作在主线程完成。
    每个批量项的 CPU 密集型转换逐个提交到工作进程池。
    """
    # Resolve LUT path (main thread)
    lut_path = LUTManager.get_lut_path(lut_name)
    if lut_path is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}")

    # Validate modeling_mode string (main thread)
    try:
        CoreModelingMode(modeling_mode)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid modeling_mode: {modeling_mode}",
        )

    results: list[BatchItemResult] = []
    successful_paths: list[str] = []

    # Submit each batch item sequentially to the process pool
    for upload_file in images:
        filename = upload_file.filename or "unknown"
        try:
            # 1. File upload (I/O, main thread)
            temp_path = await ensure_png_tempfile(upload_file)

            # 2. CPU computation offloaded to process pool (only paths and scalars)
            result = await pool.submit(
                worker_batch_convert_item,
                temp_path,
                lut_path,
                target_width_mm,
                spacer_thick,
                structure_mode,
                auto_bg,
                bg_tol,
                color_mode,
                modeling_mode,
                quantize_colors,
                enable_cleanup,
                hue_weight,
                chroma_gate,
            )

            # 3. Result processing (main thread)
            threemf_path: str | None = result.get("threemf_path")
            status_msg: str = result.get("status_msg", "")

            if threemf_path and os.path.exists(threemf_path):
                successful_paths.append(threemf_path)
                results.append(
                    BatchItemResult(
                        filename=filename,
                        status="success",
                    )
                )
            else:
                results.append(
                    BatchItemResult(
                        filename=filename,
                        status="failed",
                        error=status_msg or "3MF generation returned no output",
                    )
                )
        except asyncio.TimeoutError:
            results.append(
                BatchItemResult(
                    filename=filename,
                    status="failed",
                    error="Batch item conversion timed out",
                )
            )
        except Exception as e:
            results.append(
                BatchItemResult(
                    filename=filename,
                    status="failed",
                    error=str(e),
                )
            )

    # Package successful 3MF files into a ZIP (main thread)
    fd, zip_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path_3mf in successful_paths:
            zf.write(path_3mf, os.path.basename(path_3mf))

    # Register ZIP via FileRegistry (main thread)
    session_id = "batch"
    download_id = registry.register_path(session_id, zip_path)

    success_count = sum(1 for r in results if r.status == "success")
    total_count = len(results)

    return BatchResponse(
        status="ok" if success_count > 0 else "failed",
        message=f"Batch complete: {success_count}/{total_count} succeeded",
        download_url=f"/api/files/{download_id}",
        results=results,
    )


@router.post("/replace-color")
def replace_color(
    request: ColorReplaceRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ColorReplaceResponse:
    """Replace a single color in the current session preview (synchronous).
    替换当前 session 预览中的单个颜色（同步执行）。

    This endpoint is intentionally kept synchronous (no process pool offload)
    because the computation is lightweight: it operates on the cached
    matched_rgb array (small preview image) with simple NumPy mask operations
    over a small number of user-driven color replacements (typically 1-10).
    The heavy image processing was already completed in the /preview step.
    此端点有意保持同步执行（不卸载到进程池），因为计算量很小：
    仅对缓存的 matched_rgb 数组（小尺寸预览图）执行简单的 NumPy 掩码操作，
    颜色替换数量由用户驱动（通常 1-10 个）。
    繁重的图像处理已在 /preview 步骤中完成。

    Args:
        request (ColorReplaceRequest): Color replacement parameters. (颜色替换参数)
        store (SessionStore): Session store dependency. (会话存储依赖)
        registry (FileRegistry): File registry dependency. (文件注册表依赖)

    Returns:
        ColorReplaceResponse: Replacement result with preview URL. (替换结果及预览 URL)

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache available. (无预览缓存)
        HTTPException(500): Internal processing error. (内部处理错误)
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    try:
        # Parse hex colors to RGB tuples
        selected_rgb = ColorReplacementManager._hex_to_color(request.selected_color)
        replacement_rgb = ColorReplacementManager._hex_to_color(request.replacement_color)

        # Build manager from all existing replacement_regions
        manager = ColorReplacementManager()
        for record in session_data.get("replacement_regions", []):
            orig = ColorReplacementManager._hex_to_color(record["selected_color"])
            repl = ColorReplacementManager._hex_to_color(record["replacement_color"])
            manager.add_replacement(orig, repl)

        # Add the new replacement
        manager.add_replacement(selected_rgb, replacement_rgb)

        # Apply all replacements to the original matched_rgb
        matched_rgb: np.ndarray = cache["matched_rgb"]
        replaced_rgb = manager.apply_to_image(matched_rgb)

        # Update cache so 3D preview reflects replacements
        cache["matched_rgb"] = replaced_rgb
        store.put(request.session_id, "preview_cache", cache)

        # Generate preview PNG from replaced image
        preview_bytes = _image_to_png_bytes(replaced_rgb)
        preview_id = registry.register_bytes(request.session_id, preview_bytes, "preview_replaced.png")

        # Regenerate segmented GLB from updated matched_rgb
        glb_url: str | None = None
        try:
            glb_path = generate_segmented_glb(cache)
            if glb_path and os.path.exists(glb_path):
                glb_id = registry.register_path(request.session_id, glb_path)
                glb_url = f"/api/files/{glb_id}"
        except Exception as glb_err:
            print(f"[API] Color-replace GLB regeneration failed (non-fatal): {glb_err}")

        # Save history snapshot (deep copy of regions before this change) for undo
        current_regions = session_data.get("replacement_regions", [])
        snapshot = [dict(r) for r in current_regions]
        history = list(session_data.get("replacement_history", []))
        history.append(snapshot)
        store.put(request.session_id, "replacement_history", history)

        # Append new replacement record
        current_regions.append(
            {
                "selected_color": request.selected_color,
                "replacement_color": request.replacement_color,
            }
        )
        store.put(request.session_id, "replacement_regions", current_regions)

    except HTTPException:
        raise
    except Exception as e:
        _handle_core_error(e, "Color replacement")

    return ColorReplaceResponse(
        status="ok",
        message="Color replaced successfully",
        preview_url=f"/api/files/{preview_id}",
        preview_3d_url=glb_url,
        replacement_count=len(current_regions),
    )


@router.post("/reset-replacements", response_model=ResetReplacementsResponse)
def reset_replacements(
    request: ResetReplacementsRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ResetReplacementsResponse:
    """Reset all color replacements and restore original preview.
    重置所有颜色替换并恢复原始预览。

    Clears replacement_regions and replacement_history from the session,
    then regenerates the preview from the original matched_rgb cache.
    清空 session 中的 replacement_regions 和 replacement_history，
    然后从原始 matched_rgb 缓存重新生成预览。

    Args:
        request (ResetReplacementsRequest): Reset request with session_id. (重置请求)
        store (SessionStore): Session store dependency. (会话存储依赖)
        registry (FileRegistry): File registry dependency. (文件注册表依赖)

    Returns:
        ResetReplacementsResponse: Reset result with original preview URL. (重置结果及原始预览 URL)

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache available. (无预览缓存)
        HTTPException(500): Internal processing error. (内部处理错误)
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    try:
        # Clear replacement state
        store.put(request.session_id, "replacement_regions", [])
        store.put(request.session_id, "replacement_history", [])

        # Restore matched_rgb from the pristine original saved at preview time.
        # region-replace mutates cache["matched_rgb"] in-place, so we must
        # use the untouched copy to truly reset.
        original_rgb: np.ndarray | None = session_data.get("original_matched_rgb")
        if original_rgb is not None:
            # Restore cache to original state
            cache["matched_rgb"] = original_rgb.copy()
            store.put(request.session_id, "preview_cache", cache)
            source_rgb = original_rgb
        else:
            # Fallback: no original saved (legacy session), use current cache
            source_rgb = cache["matched_rgb"]

        # Regenerate preview from original matched_rgb (no replacements applied)
        preview_bytes = _image_to_png_bytes(source_rgb)
        preview_id = registry.register_bytes(request.session_id, preview_bytes, "preview_reset.png")

        # Regenerate segmented GLB from restored matched_rgb
        glb_url: str | None = None
        try:
            glb_path = generate_segmented_glb(cache)
            if glb_path and os.path.exists(glb_path):
                glb_id = registry.register_path(request.session_id, glb_path)
                glb_url = f"/api/files/{glb_id}"
        except Exception as glb_err:
            print(f"[API] Reset-replacements GLB regeneration failed (non-fatal): {glb_err}")
    except HTTPException:
        raise
    except Exception as e:
        _handle_core_error(e, "Reset replacements")

    return ResetReplacementsResponse(
        status="ok",
        message="All replacements cleared",
        preview_url=f"/api/files/{preview_id}",
        preview_glb_url=glb_url,
    )


@router.post("/region-detect", response_model=RegionDetectResponse)
def region_detect(
    request: RegionDetectRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> RegionDetectResponse:
    """Detect a connected region of same-colored pixels at the click position.
    检测点击位置处同色像素的连通区域。

    This endpoint is synchronous because the BFS flood-fill on a small
    quantized preview image is lightweight. The heavy image processing
    was already completed in the /preview step.
    此端点同步执行，因为在小尺寸量化预览图上的 BFS 洪水填充计算量很小。
    繁重的图像处理已在 /preview 步骤中完成。

    Args:
        request (RegionDetectRequest): Region detection parameters. (区域检测参数)
        store (SessionStore): Session store dependency. (会话存储依赖)
        registry (FileRegistry): File registry dependency. (文件注册表依赖)

    Returns:
        RegionDetectResponse: Detected region metadata with preview URL. (检测到的区域元数据及预览 URL)

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache available. (无预览缓存)
        HTTPException(400): Click coordinates out of bounds or on background. (点击坐标越界或在背景上)
        HTTPException(500): Internal processing error. (内部处理错误)
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    try:
        quantized_image: np.ndarray | None = cache.get("quantized_image")
        mask_solid: np.ndarray | None = cache.get("mask_solid")
        matched_rgb: np.ndarray | None = cache.get("matched_rgb")

        if quantized_image is None or mask_solid is None or matched_rgb is None:
            raise HTTPException(
                status_code=409,
                detail="Preview cache missing quantized_image, mask_solid, or matched_rgb.",
            )

        h, w = quantized_image.shape[:2]
        x, y = request.x, request.y

        if not (0 <= x < w and 0 <= y < h):
            raise HTTPException(
                status_code=400,
                detail=f"Coordinates ({x}, {y}) out of bounds for image {w}x{h}.",
            )

        if not mask_solid[y, x]:
            raise HTTPException(
                status_code=400,
                detail="Clicked on background area.",
            )

        # Compute connected region mask via 4-neighbor BFS
        region_mask: np.ndarray = _compute_connected_region_mask_4n(quantized_image, mask_solid, x, y)

        pixel_count: int = int(np.count_nonzero(region_mask))
        if pixel_count == 0:
            raise HTTPException(
                status_code=400,
                detail="No connected region found at the click position.",
            )

        # Extract region color from matched_rgb at click position
        r, g, b = int(matched_rgb[y, x, 0]), int(matched_rgb[y, x, 1]), int(matched_rgb[y, x, 2])
        color_hex: str = f"#{r:02x}{g:02x}{b:02x}"

        # Store region_mask in session for subsequent region-replace
        region_id: str = str(uuid.uuid4())
        store.put(request.session_id, "selected_region_mask", region_mask)
        store.put(request.session_id, "selected_region_id", region_id)

        # Generate highlighted preview: overlay region with semi-transparent highlight
        highlight_color = np.array([0, 200, 255], dtype=np.uint8)  # cyan highlight
        alpha = 0.45
        preview_img: np.ndarray = matched_rgb.copy()
        preview_img[region_mask] = (
            preview_img[region_mask].astype(np.float32) * (1 - alpha) + highlight_color.astype(np.float32) * alpha
        ).astype(np.uint8)

        preview_bytes: bytes = _image_to_png_bytes(preview_img)
        preview_id: str = registry.register_bytes(request.session_id, preview_bytes, "region_highlight.png")

        # Extract 2D contours from region_mask for frontend RGB outline rendering
        region_contours: list[list[list[float]]] | None = None
        target_w = cache.get("target_w")
        target_width_mm = cache.get("target_width_mm")
        if target_w and target_width_mm and target_w > 0:
            pixel_scale = target_width_mm / target_w
            mask_u8 = region_mask.astype(np.uint8) * 255
            cv_contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            region_contours = []
            for cnt in cv_contours:
                if len(cnt) < 3:
                    continue
                pts = cnt.squeeze(1).astype(float)
                world_pts: list[list[float]] = []
                for px, py in pts:
                    x_mm = float(px * pixel_scale)
                    y_mm = float((h - py) * pixel_scale)
                    world_pts.append([x_mm, y_mm])
                region_contours.append(world_pts)

    except HTTPException:
        raise
    except Exception as e:
        _handle_core_error(e, "Region detection")

    return RegionDetectResponse(
        region_id=region_id,
        color_hex=color_hex,
        pixel_count=pixel_count,
        preview_url=f"/api/files/{preview_id}",
        contours=region_contours,
    )


@router.post("/region-replace", response_model=RegionReplaceResponse)
def region_replace(
    request: RegionReplaceRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> RegionReplaceResponse:
    """Replace color only within the previously detected connected region.
    仅替换先前检测到的连通区域内的颜色。

    This endpoint is synchronous because it performs a simple masked
    pixel assignment on the cached matched_rgb array (small preview image).
    此端点同步执行，因为仅对缓存的 matched_rgb 数组执行简单的掩码像素赋值。

    Args:
        request (RegionReplaceRequest): Region replacement parameters. (区域替换参数)
        store (SessionStore): Session store dependency. (会话存储依赖)
        registry (FileRegistry): File registry dependency. (文件注册表依赖)

    Returns:
        RegionReplaceResponse: Replacement result with preview URL. (替换结果及预览 URL)

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache or no region selected. (无预览缓存或未选中区域)
        HTTPException(500): Internal processing error. (内部处理错误)
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    try:
        matched_rgb: np.ndarray | None = cache.get("matched_rgb")
        if matched_rgb is None:
            raise HTTPException(
                status_code=409,
                detail="Preview cache missing matched_rgb.",
            )

        region_mask: np.ndarray | None = session_data.get("selected_region_mask")
        if region_mask is None:
            raise HTTPException(
                status_code=409,
                detail="No region selected. Call POST /api/convert/region-detect first.",
            )

        # Parse replacement hex to RGB tuple
        replacement_rgb = np.array(
            ColorReplacementManager._hex_to_color(request.replacement_color),
            dtype=np.uint8,
        )

        # Apply region replacement: only modify pixels within the mask
        replaced_rgb: np.ndarray = matched_rgb.copy()
        replaced_rgb[region_mask] = replacement_rgb

        # Update matched_rgb in session cache
        cache["matched_rgb"] = replaced_rgb
        store.put(request.session_id, "preview_cache", cache)

        # Generate preview PNG
        preview_bytes: bytes = _image_to_png_bytes(replaced_rgb)
        preview_id: str = registry.register_bytes(request.session_id, preview_bytes, "preview_region_replaced.png")

        # Regenerate segmented GLB from updated matched_rgb
        glb_url: str | None = None
        try:
            glb_path = generate_segmented_glb(cache)
            if glb_path and os.path.exists(glb_path):
                glb_id = registry.register_path(request.session_id, glb_path)
                glb_url = f"/api/files/{glb_id}"
        except Exception as glb_err:
            print(f"[API] Region-replace GLB regeneration failed (non-fatal): {glb_err}")

        # Extract updated color_contours from cache
        contours_data: dict | None = cache.get("color_contours")

        # Clear region mask after replacement
        store.put(request.session_id, "selected_region_mask", None)
        store.put(request.session_id, "selected_region_id", None)

    except HTTPException:
        raise
    except Exception as e:
        _handle_core_error(e, "Region replacement")

    return RegionReplaceResponse(
        preview_url=f"/api/files/{preview_id}",
        preview_glb_url=glb_url,
        color_contours=contours_data,
        message="Region color replaced successfully",
    )


def _rgb_to_lab(rgb_array: np.ndarray) -> np.ndarray:
    """Convert RGB array to CIELAB color space via OpenCV.
    通过 OpenCV 将 RGB 数组转换为 CIELAB 色彩空间。

    Args:
        rgb_array (np.ndarray): RGB values of shape (N, 3), dtype uint8. (RGB 值，形状 (N, 3))

    Returns:
        np.ndarray: LAB values of shape (N, 3), dtype float64. (LAB 值，形状 (N, 3))
    """
    rgb_2d = rgb_array.reshape(1, -1, 3).astype(np.uint8)
    lab_2d = cv2.cvtColor(rgb_2d, cv2.COLOR_RGB2LAB)
    return lab_2d.reshape(-1, 3).astype(np.float64)


@router.post("/merge-colors")
def merge_colors(
    request: ColorMergePreviewRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> MergePreviewResponse:
    """Preview the effect of merging similar colors (synchronous).
    预览合并相似颜色的效果（同步执行）。

    This endpoint is intentionally kept synchronous (no process pool offload)
    because the computation is lightweight: it operates on the cached palette
    (typically 3-64 colors) and the cached matched_rgb array from the /preview
    step. Delta-E calculations involve small NumPy arrays (palette-sized, not
    image-sized), and pixel replacement uses simple mask operations.
    The heavy image processing was already completed in the /preview step.
    此端点有意保持同步执行（不卸载到进程池），因为计算量很小：
    仅对缓存的调色板（通常 3-64 色）和 /preview 步骤缓存的 matched_rgb 数组操作。
    Delta-E 计算涉及小型 NumPy 数组（调色板级别，非图像级别），
    像素替换使用简单的掩码操作。
    繁重的图像处理已在 /preview 步骤中完成。

    Args:
        request (ColorMergePreviewRequest): Merge parameters. (合并参数)
        store (SessionStore): Session store dependency. (会话存储依赖)
        registry (FileRegistry): File registry dependency. (文件注册表依赖)

    Returns:
        MergePreviewResponse: Merge result with preview URL and quality metric.
                              (合并结果及预览 URL 和质量指标)

    Raises:
        HTTPException(404): Session not found. (会话不存在)
        HTTPException(409): No preview cache available. (无预览缓存)
        HTTPException(500): Internal processing error. (内部处理错误)
    """
    session_data = _require_session(store, request.session_id)
    cache = _require_preview_cache(session_data)

    try:
        # Extract palette from preview cache
        palette = extract_color_palette(cache)
        colors_before = len(palette)

        # If merge disabled, return empty merge with perfect quality
        if not request.merge_enable:
            preview_bytes = _image_to_png_bytes(cache["matched_rgb"])
            preview_id = registry.register_bytes(request.session_id, preview_bytes, "preview_merged.png")
            store.put(request.session_id, "merge_map", {})
            return MergePreviewResponse(
                status="ok",
                message="Color merging disabled",
                preview_url=f"/api/files/{preview_id}",
                merge_map={},
                quality_metric=100.0,
                colors_before=colors_before,
                colors_after=colors_before,
            )

        # Build merge map using ColorMerger
        merger = ColorMerger(rgb_to_lab_func=_rgb_to_lab)
        merge_map = merger.build_merge_map(
            palette,
            threshold_percent=request.merge_threshold,
            max_distance=float(request.merge_max_distance),
        )

        # Apply merging to matched_rgb
        matched_rgb: np.ndarray = cache["matched_rgb"]
        merged_rgb = merger.apply_color_merging(matched_rgb, merge_map)

        # Calculate quality metric
        merged_palette = extract_color_palette(
            {
                "matched_rgb": merged_rgb,
                "mask_solid": cache["mask_solid"],
            }
        )
        quality = merger.calculate_quality_metric(palette, merged_palette, merge_map)
        colors_after = len(merged_palette)

        # Generate preview PNG
        preview_bytes = _image_to_png_bytes(merged_rgb)
        preview_id = registry.register_bytes(request.session_id, preview_bytes, "preview_merged.png")

        # Store merge_map in session
        store.put(request.session_id, "merge_map", merge_map)

    except HTTPException:
        raise
    except Exception as e:
        _handle_core_error(e, "Color merging")

    return MergePreviewResponse(
        status="ok",
        message=f"Merged {len(merge_map)} colors",
        preview_url=f"/api/files/{preview_id}",
        merge_map=merge_map,
        quality_metric=round(quality, 2),
        colors_before=colors_before,
        colors_after=colors_after,
    )
