"""Extractor domain API router.
Extractor 领域 API 路由模块。
"""

from __future__ import annotations

import json
import os
from typing import List, Tuple

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image

from api.dependencies import get_file_registry, get_session_store
from api.file_bridge import ndarray_to_png_bytes, pil_to_png_bytes, upload_to_ndarray
from api.file_registry import FileRegistry
from api.schemas.extractor import ConfirmPaletteRequest, ExtractorManualFixRequest
from api.schemas.responses import ExtractResponse, ManualFixResponse
from api.session_store import SessionStore
from config import ColorSystem, LUTMetadata, PaletteEntry
from core.extractor import manual_fix_cell, run_extraction
from utils.lut_manager import LUTManager

router = APIRouter(prefix="/api/extractor", tags=["Extractor"])


def _handle_core_error(e: Exception, context: str) -> None:
    """将 core 模块异常转换为 HTTP 500 错误。"""
    print(f"[API] {context} error: {e}")
    raise HTTPException(status_code=500, detail=f"{context} failed: {str(e)}")


def _image_to_png_bytes(img: object) -> bytes:
    """将 ndarray 或 PIL Image 转换为 PNG 字节流。"""
    if isinstance(img, np.ndarray):
        return ndarray_to_png_bytes(img)
    if isinstance(img, Image.Image):
        return pil_to_png_bytes(img)
    raise TypeError(f"Unsupported image type: {type(img)}")


def _build_default_palette(color_mode: str) -> list[dict]:
    """Build default palette array based on color mode.
    根据颜色模式构建默认调色板数组。

    Args:
        color_mode (str): Color mode string. (颜色模式字符串)

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

    metadata = LUTManager.infer_default_metadata(
        "lumina_lut", output_path, color_count, color_mode=color_mode
    )
    metadata.manufacturer = manufacturer
    metadata.type = lut_type
    return metadata


@router.post("/extract")
async def extractor_extract(
    image: UploadFile = File(..., description="校准板照片"),
    corner_points: str = Form(..., description="4 个角点坐标 JSON 数组 [[x,y],...]"),
    color_mode: str = Form("4-Color (RYBW)", description="校准颜色模式"),
    page: str = Form("Page 1", description="8-Color 页码"),
    offset_x: int = Form(0, description="水平采样偏移"),
    offset_y: int = Form(0, description="垂直采样偏移"),
    zoom: float = Form(1.0, description="透视校正缩放"),
    distortion: float = Form(0.0, description="畸变校正"),
    vignette_correction: bool = Form(False, description="暗角校正"),
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ExtractResponse:
    """Extract colors from a photographed calibration board.
    从拍摄的校准板照片中提取颜色。
    """
    # Parse corner_points from JSON string
    try:
        points: List[List[int]] = json.loads(corner_points)
    except (json.JSONDecodeError, TypeError) as e:
        raise HTTPException(status_code=422, detail=f"Invalid corner_points JSON: {e}")

    if len(points) != 4:
        raise HTTPException(
            status_code=422,
            detail=f"corner_points must contain exactly 4 points, got {len(points)}",
        )

    # Convert UploadFile to ndarray
    try:
        img_arr = await upload_to_ndarray(image)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Call core extraction (field name mapping: distortion->barrel, vignette_correction->bright)
    try:
        vis_img, preview_img, lut_path, status_msg = run_extraction(
            img=img_arr,
            points=points,
            offset_x=offset_x,
            offset_y=offset_y,
            zoom=zoom,
            barrel=distortion,
            bright=vignette_correction,
            color_mode=color_mode,
            page_choice=page,
        )
    except Exception as e:
        _handle_core_error(e, "Color extraction")

    if lut_path is None:
        raise HTTPException(status_code=500, detail=status_msg or "Extraction failed")

    # Create session and store state
    session_id = store.create()
    store.put(session_id, "lut_path", lut_path)
    store.put(session_id, "color_mode", color_mode)

    # For 8-Color mode: save page-specific temp file
    if "8-Color" in color_mode and lut_path:
        import sys

        if getattr(sys, "frozen", False):
            assets_dir = os.path.join(os.getcwd(), "assets")
        else:
            assets_dir = "assets"
        os.makedirs(assets_dir, exist_ok=True)
        page_idx = 1 if "1" in str(page) else 2
        temp_path = os.path.join(assets_dir, f"temp_8c_page_{page_idx}.json")
        try:
            rgb, stacks, metadata = LUTManager.load_lut_with_metadata(lut_path)
            if stacks is None:
                stacks = np.zeros((len(rgb), 0), dtype=np.int32)
            LUTManager.save_keyed_json(temp_path, rgb, stacks, metadata)
            store.put(session_id, "lut_path", temp_path)
            lut_path = temp_path
        except Exception as e:
            print(f"[8-COLOR] Error saving page {page_idx}: {e}")

    # For 5-Color Extended mode: save page-specific temp file
    if "5-Color" in color_mode and lut_path:
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
        except Exception as e:
            print(f"[5-COLOR-EXT] Error saving page {page_idx}: {e}")

    # Register LUT file (already in Keyed JSON format from run_extraction)
    lut_download_id = registry.register_path(session_id, lut_path)

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

    return ExtractResponse(
        session_id=session_id,
        status="ok",
        message=status_msg or "Extraction complete",
        lut_download_url=f"/api/files/{lut_download_id}",
        warp_view_url=f"/api/files/{warp_view_id}" if warp_view_id else "",
        lut_preview_url=f"/api/files/{lut_preview_id}" if lut_preview_id else "",
        default_palette=_build_default_palette(color_mode),
    )


@router.post("/manual-fix")
def extractor_manual_fix(
    request: ExtractorManualFixRequest,
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ManualFixResponse:
    """Manually override a single LUT cell color value.
    手动覆盖单个 LUT 单元格的颜色值。
    """
    # Resolve lut_path: prefer session lookup, fallback to direct path
    lut_path = request.lut_path
    if request.session_id:
        session_data = store.get(request.session_id)
        if session_data and "lut_path" in session_data:
            lut_path = session_data["lut_path"]

    try:
        preview_result, status_msg = manual_fix_cell(
            coord=request.cell_coord,
            color_input=request.override_color,
            lut_path=lut_path,
        )
    except Exception as e:
        _handle_core_error(e, "Manual fix")

    if preview_result is None:
        raise HTTPException(status_code=500, detail=status_msg or "Manual fix failed")

    # Register updated preview
    preview_bytes = _image_to_png_bytes(preview_result)
    sid = "extractor-fix"
    preview_id = registry.register_bytes(sid, preview_bytes, "lut_preview.png")

    return ManualFixResponse(
        status="ok",
        message=status_msg or "Cell updated",
        lut_preview_url=f"/api/files/{preview_id}",
    )


@router.post("/merge-5color-extended")
def extractor_merge_5color_extended(
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ExtractResponse:
    """Merge two 5-Color Extended pages into a single LUT.
    合并两页 5 色扩展 LUT 为一个完整 LUT。
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

    try:
        rgb1, stacks1, meta1 = LUTManager.load_lut_with_metadata(path1)
        rgb2, stacks2, meta2 = LUTManager.load_lut_with_metadata(path2)
        rgb1 = rgb1.reshape(-1, 3)
        rgb2 = rgb2.reshape(-1, 3)
        merged_rgb = np.vstack([rgb1, rgb2])

        # Merge stacks if available
        if stacks1 is not None and stacks2 is not None and stacks1.shape[1] == stacks2.shape[1]:
            merged_stacks = np.vstack([stacks1, stacks2])
        else:
            merged_stacks = np.zeros((len(merged_rgb), 0), dtype=np.int32)

        metadata = _build_merged_metadata(
            meta1, meta2, "5-Color Extended", LUT_FILE_PATH, len(merged_rgb)
        )
        LUTManager.save_keyed_json(LUT_FILE_PATH, merged_rgb, merged_stacks, metadata)
    except Exception as e:
        _handle_core_error(e, "5-Color Extended merge")

    # Create session for merged result
    session_id = store.create()
    store.put(session_id, "lut_path", LUT_FILE_PATH)
    store.put(session_id, "color_mode", "5-Color Extended")

    lut_download_id = registry.register_path(session_id, LUT_FILE_PATH)

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
    store: SessionStore = Depends(get_session_store),
    registry: FileRegistry = Depends(get_file_registry),
) -> ExtractResponse:
    """Merge two 8-Color pages into a single LUT.
    合并两页 8 色 LUT 为一个完整 LUT。
    """
    import sys
    from config import LUT_FILE_PATH

    if getattr(sys, "frozen", False):
        assets_dir = os.path.join(os.getcwd(), "assets")
    else:
        assets_dir = "assets"

    path1 = os.path.join(assets_dir, "temp_8c_page_1.json")
    path2 = os.path.join(assets_dir, "temp_8c_page_2.json")

    if not os.path.exists(path1) or not os.path.exists(path2):
        raise HTTPException(
            status_code=400,
            detail="Missing temp pages. Please extract Page 1 and Page 2 first.",
        )

    try:
        rgb1, stacks1, meta1 = LUTManager.load_lut_with_metadata(path1)
        rgb2, stacks2, meta2 = LUTManager.load_lut_with_metadata(path2)
        merged_rgb = np.concatenate([rgb1, rgb2], axis=0)

        # Merge stacks if available
        if stacks1 is not None and stacks2 is not None and stacks1.shape[1] == stacks2.shape[1]:
            merged_stacks = np.concatenate([stacks1, stacks2], axis=0)
        else:
            merged_stacks = np.zeros((len(merged_rgb), 0), dtype=np.int32)

        metadata = _build_merged_metadata(
            meta1, meta2, "8-Color Max", LUT_FILE_PATH, len(merged_rgb)
        )
        LUTManager.save_keyed_json(LUT_FILE_PATH, merged_rgb, merged_stacks, metadata)
    except Exception as e:
        _handle_core_error(e, "8-Color merge")

    # Create session for merged result
    session_id = store.create()
    store.put(session_id, "lut_path", LUT_FILE_PATH)
    store.put(session_id, "color_mode", "8-Color Max")

    lut_download_id = registry.register_path(session_id, LUT_FILE_PATH)

    return ExtractResponse(
        session_id=session_id,
        status="ok",
        message=f"8-Color LUT merged ({merged_rgb.shape[0]}x{merged_rgb.shape[1]})",
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
    接收用户确认的调色板，保存到 session。

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
            raise HTTPException(status_code=422, detail="颜色名称不允许为空")

    session_data = store.get(request.session_id)
    if session_data is None:
        raise HTTPException(status_code=404, detail=f"Session {request.session_id} not found")

    manufacturer = request.manufacturer.strip()
    lut_type = request.type.strip()
    palette_entries = [
        PaletteEntry(
            color=e.color.strip(),
            material=e.material.strip() if e.material else "PLA Basic",
            hex_color=e.hex_color,
            color_name=e.color_name.strip() if e.color_name and e.color_name.strip() else None,
        )
        for e in request.palette
    ]

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
        except Exception as e:
            persist_warning = f"调色板已确认，但持久化到磁盘失败: {e}"
            print(f"[CONFIRM_PALETTE] Failed to persist palette to {lut_path}: {e}")

    store.put(request.session_id, "lut_metadata", metadata)

    if persist_warning:
        return {"status": "warning", "message": persist_warning}
    return {"status": "ok", "message": "调色板已确认"}
