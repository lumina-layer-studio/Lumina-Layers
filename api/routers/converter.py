"""Converter domain API router.
Converter 领域 API 路由模块。
"""

from __future__ import annotations

import os
import tempfile
import zipfile

import cv2
import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image
from pydantic import BaseModel

from api.dependencies import get_file_registry, get_session_store
from api.file_bridge import ndarray_to_png_bytes, pil_to_png_bytes, upload_to_tempfile
from api.file_registry import FileRegistry
from api.schemas.converter import (
    BedSizeItem,
    BedSizeListResponse,
    ColorMergePreviewRequest,
    ColorReplaceRequest,
    ConvertGenerateRequest,
)
from api.schemas.responses import (
    BatchItemResult,
    BatchResponse,
    ColorReplaceResponse,
    CropResponse,
    GenerateResponse,
    HeightmapUploadResponse,
    MergePreviewResponse,
    PreviewResponse,
)
from api.session_store import SessionStore
from core.color_merger import ColorMerger
from core.image_preprocessor import ImagePreprocessor
from core.color_replacement import ColorReplacementManager
from core.converter import convert_image_to_3d, extract_color_palette, generate_empty_bed_glb, generate_final_model, generate_preview_cached, generate_segmented_glb
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
        raise HTTPException(
            status_code=409, detail="No preview cache. Call POST /api/convert/preview first."
        )
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
    """Return all available printer bed sizes.
    返回所有可用的打印热床尺寸列表。
    """
    beds = [
        BedSizeItem(
            label=label,
            width_mm=w,
            height_mm=h,
            is_default=(label == BedManager.DEFAULT_BED),
        )
        for label, w, h in BedManager.BEDS
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
    temp_path = await upload_to_tempfile(image)

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
    color_mode: str = Form("4-Color", description="颜色模式"),
    modeling_mode: str = Form("high-fidelity", description="建模模式"),
    quantize_colors: int = Form(48, description="K-Means 色彩细节"),
    enable_cleanup: bool = Form(True, description="孤立像素清理"),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> PreviewResponse:
    """Generate a 2D color-matched preview image.
    生成 2D 颜色匹配预览图。
    """
    # Resolve LUT path
    lut_path = LUTManager.get_lut_path(lut_name)
    if lut_path is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}")

    # Save uploaded image to temp file
    temp_path = await upload_to_tempfile(image)

    # Call core preview generation
    try:
        preview_img, cache_data, status_msg = generate_preview_cached(
            image_path=temp_path,
            lut_path=lut_path,
            target_width_mm=target_width_mm,
            auto_bg=auto_bg,
            bg_tol=bg_tol,
            color_mode=color_mode,
            modeling_mode=modeling_mode,
            quantize_colors=quantize_colors,
            enable_cleanup=enable_cleanup,
        )
    except Exception as e:
        _handle_core_error(e, "Preview generation")

    if preview_img is None:
        raise HTTPException(status_code=500, detail=status_msg or "Preview generation failed")

    # Create session and store state
    session_id = store.create()
    store.put(session_id, "preview_cache", cache_data)
    store.put(session_id, "image_path", temp_path)
    store.put(session_id, "lut_path", lut_path)
    store.put(session_id, "lut_name", lut_name)
    store.put(session_id, "replacement_regions", [])
    store.put(session_id, "replacement_history", [])
    store.put(session_id, "free_color_set", set())
    store.register_temp_file(session_id, temp_path)

    # Register preview image
    preview_bytes = _image_to_png_bytes(preview_img)
    preview_id = registry.register_bytes(session_id, preview_bytes, "preview.png")

    # Generate segmented GLB (one Mesh per color)
    preview_glb_url: str | None = None
    try:
        glb_path = generate_segmented_glb(cache_data)
        if glb_path and os.path.exists(glb_path):
            glb_id = registry.register_path(session_id, glb_path)
            preview_glb_url = f"/api/files/{glb_id}"
    except Exception as e:
        # Non-fatal: log and continue without GLB
        print(f"[API] Segmented GLB generation failed (non-fatal): {e}")

    # Build palette with quantized_hex, matched_hex, pixel_count, percentage
    raw_palette: list[dict] = cache_data.get("color_palette", []) if cache_data else []
    quantized_image = cache_data.get("quantized_image") if cache_data else None
    matched_rgb_arr = cache_data.get("matched_rgb") if cache_data else None
    mask_solid_arr = cache_data.get("mask_solid") if cache_data else None

    palette: list[dict] = []
    if raw_palette and matched_rgb_arr is not None and mask_solid_arr is not None:
        # Build a matched_hex -> quantized_hex lookup from pixel data
        matched_to_quantized: dict[str, str] = {}
        if quantized_image is not None:
            solid_mask = mask_solid_arr
            q_pixels = quantized_image[solid_mask]   # (N, 3)
            m_pixels = matched_rgb_arr[solid_mask]    # (N, 3)
            # For each matched color, find the most common quantized color
            for entry in raw_palette:
                m_hex = entry["hex"]  # '#rrggbb'
                m_rgb = entry["color"]  # (R, G, B)
                color_mask = np.all(m_pixels == np.array(m_rgb, dtype=np.uint8), axis=1)
                if np.any(color_mask):
                    q_subset = q_pixels[color_mask]
                    unique_q, q_counts = np.unique(q_subset, axis=0, return_counts=True)
                    dominant_q = unique_q[np.argmax(q_counts)]
                    r, g, b = int(dominant_q[0]), int(dominant_q[1]), int(dominant_q[2])
                    matched_to_quantized[m_hex] = f"#{r:02x}{g:02x}{b:02x}"

        for entry in raw_palette:
            m_hex = entry["hex"]  # '#rrggbb'
            q_hex = matched_to_quantized.get(m_hex, m_hex)
            palette.append({
                "quantized_hex": q_hex,
                "matched_hex": m_hex,
                "pixel_count": entry["count"],
                "percentage": entry["percentage"],
            })

    dimensions = {}
    if cache_data:
        dimensions = {
            "width": cache_data.get("target_w", 0),
            "height": cache_data.get("target_h", 0),
        }

    return PreviewResponse(
        session_id=session_id,
        status="ok",
        message=status_msg or "Preview generated",
        preview_url=f"/api/files/{preview_id}",
        preview_glb_url=preview_glb_url,
        palette=palette,
        dimensions=dimensions,
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
    cache = _require_preview_cache(session_data)

    # 3. Read uploaded file and save to temp
    temp_path = await upload_to_tempfile(heightmap)
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
def convert_generate(
    body: _GenerateBody,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> GenerateResponse:
    """Generate a printable 3MF model from the input image.
    从输入图像生成可打印的 3MF 模型。
    """
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

    try:
        result = generate_final_model(
            image_path=image_path,
            lut_path=lut_path,
            target_width_mm=request.target_width_mm,
            spacer_thick=request.spacer_thick,
            structure_mode=request.structure_mode.value,
            auto_bg=request.auto_bg,
            bg_tol=request.bg_tol,
            color_mode=request.color_mode.value,
            add_loop=request.add_loop,
            loop_width=request.loop_width,
            loop_length=request.loop_length,
            loop_hole=request.loop_hole,
            loop_pos=request.loop_pos,
            modeling_mode=core_modeling_mode,
            quantize_colors=request.quantize_colors,
            replacement_regions=replacement_regions,
            separate_backing=request.separate_backing,
            enable_relief=request.enable_relief,
            color_height_map=request.color_height_map,
            heightmap_max_height=request.heightmap_max_height,
            enable_cleanup=request.enable_cleanup,
            enable_outline=request.enable_outline,
            outline_width=request.outline_width,
            enable_cloisonne=request.enable_cloisonne,
            wire_width_mm=request.wire_width_mm,
            wire_height_mm=request.wire_height_mm,
            free_color_set=free_color_set,
            enable_coating=request.enable_coating,
            coating_height_mm=request.coating_height_mm,
        )
    except Exception as e:
        _handle_core_error(e, "3MF generation")
        return  # unreachable, keeps type checker happy

    # Unpack result: (3mf_path, glb_path, preview_img, status_msg, color_recipe_path)
    threemf_path, glb_path, _preview_img, status_msg, _recipe_path = result

    if not threemf_path or not os.path.exists(threemf_path):
        raise HTTPException(status_code=500, detail=status_msg or "3MF generation failed")

    # Register output files via FileRegistry
    sid = body.session_id
    download_id = registry.register_path(sid, threemf_path)

    preview_3d_url: str | None = None
    if glb_path and os.path.exists(glb_path):
        glb_id = registry.register_path(sid, glb_path)
        preview_3d_url = f"/api/files/{glb_id}"

    return GenerateResponse(
        status="ok",
        message=status_msg or "Model generated",
        download_url=f"/api/files/{download_id}",
        preview_3d_url=preview_3d_url,
        threemf_disk_path=threemf_path,
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
    color_mode: str = Form("4-Color", description="颜色模式"),
    modeling_mode: str = Form("high-fidelity", description="建模模式"),
    quantize_colors: int = Form(48, description="K-Means 色彩细节"),
    enable_cleanup: bool = Form(True, description="孤立像素清理"),
    registry: FileRegistry = Depends(get_file_registry),
) -> BatchResponse:
    """Batch-convert multiple images with shared parameters.
    使用共享参数批量转换多张图像。
    """
    # Resolve LUT path
    lut_path = LUTManager.get_lut_path(lut_name)
    if lut_path is None:
        raise HTTPException(status_code=404, detail=f"LUT not found: {lut_name}")

    # Convert modeling_mode string to core enum
    try:
        core_modeling_mode = CoreModelingMode(modeling_mode)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid modeling_mode: {modeling_mode}",
        )

    results: list[BatchItemResult] = []
    successful_paths: list[str] = []

    for upload_file in images:
        filename = upload_file.filename or "unknown"
        try:
            temp_path = await upload_to_tempfile(upload_file)
            threemf_path, _glb_path, _preview_img, status_msg = convert_image_to_3d(
                image_path=temp_path,
                lut_path=lut_path,
                target_width_mm=target_width_mm,
                spacer_thick=spacer_thick,
                structure_mode=structure_mode,
                auto_bg=auto_bg,
                bg_tol=bg_tol,
                color_mode=color_mode,
                add_loop=False,
                loop_width=4.0,
                loop_length=8.0,
                loop_hole=2.5,
                loop_pos=None,
                modeling_mode=core_modeling_mode,
                quantize_colors=quantize_colors,
                enable_cleanup=enable_cleanup,
            )
            if threemf_path and os.path.exists(threemf_path):
                successful_paths.append(threemf_path)
                results.append(BatchItemResult(
                    filename=filename,
                    status="success",
                ))
            else:
                results.append(BatchItemResult(
                    filename=filename,
                    status="failed",
                    error=status_msg or "3MF generation returned no output",
                ))
        except Exception as e:
            results.append(BatchItemResult(
                filename=filename,
                status="failed",
                error=str(e),
            ))

    # Package successful 3MF files into a ZIP
    fd, zip_path = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path_3mf in successful_paths:
            zf.write(path_3mf, os.path.basename(path_3mf))

    # Register ZIP via FileRegistry
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
    """Replace a single color in the current session preview.
    替换当前 session 预览中的单个颜色。
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

        # Generate preview PNG from replaced image
        preview_bytes = _image_to_png_bytes(replaced_rgb)
        preview_id = registry.register_bytes(
            request.session_id, preview_bytes, "preview_replaced.png"
        )

        # Save history snapshot (deep copy of regions before this change) for undo
        current_regions = session_data.get("replacement_regions", [])
        snapshot = [dict(r) for r in current_regions]
        history = list(session_data.get("replacement_history", []))
        history.append(snapshot)
        store.put(request.session_id, "replacement_history", history)

        # Append new replacement record
        current_regions.append({
            "selected_color": request.selected_color,
            "replacement_color": request.replacement_color,
        })
        store.put(request.session_id, "replacement_regions", current_regions)

    except HTTPException:
        raise
    except Exception as e:
        _handle_core_error(e, "Color replacement")

    return ColorReplaceResponse(
        status="ok",
        message="Color replaced successfully",
        preview_url=f"/api/files/{preview_id}",
        replacement_count=len(current_regions),
    )


def _rgb_to_lab(rgb_array: np.ndarray) -> np.ndarray:
    """Convert RGB array (N, 3) uint8 to LAB array (N, 3) float."""
    rgb_2d = rgb_array.reshape(1, -1, 3).astype(np.uint8)
    lab_2d = cv2.cvtColor(rgb_2d, cv2.COLOR_RGB2LAB)
    return lab_2d.reshape(-1, 3).astype(np.float64)


@router.post("/merge-colors")
def merge_colors(
    request: ColorMergePreviewRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> MergePreviewResponse:
    """Preview the effect of merging similar colors.
    预览合并相似颜色的效果。
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
            preview_id = registry.register_bytes(
                request.session_id, preview_bytes, "preview_merged.png"
            )
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
        merged_palette = extract_color_palette({
            "matched_rgb": merged_rgb,
            "mask_solid": cache["mask_solid"],
        })
        quality = merger.calculate_quality_metric(palette, merged_palette, merge_map)
        colors_after = len(merged_palette)

        # Generate preview PNG
        preview_bytes = _image_to_png_bytes(merged_rgb)
        preview_id = registry.register_bytes(
            request.session_id, preview_bytes, "preview_merged.png"
        )

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
