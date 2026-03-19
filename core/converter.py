"""
Lumina Studio - Image Converter Coordinator (Refactored)

Thin wrapper layer + re-exports + Gradio UI functions.
薄包装层 + re-export + Gradio UI 函数。

converter.py 从 4500+ 行的巨型文件重构为：
1. convert_image_to_3d / generate_preview_cached 薄包装（委托给 coordinator）
2. re-export 所有被外部引用的函数（保持 from core.converter import XXX 兼容）
3. Gradio UI 函数保留不动
"""

import os
import time
from collections import deque
import numpy as np
import cv2
import trimesh
from PIL import Image, ImageDraw, ImageFont
import gradio as gr
from typing import List, Dict, Tuple, Optional

from config import PrinterConfig, ColorSystem, ModelingMode, PREVIEW_SCALE, PREVIEW_MARGIN, OUTPUT_DIR, BedManager
from utils import Stats

# ========== Re-exports from pipeline modules ==========
# 保持 `from core.converter import XXX` 对所有现有调用方仍然有效

# --- pipeline_utils ---
from core.pipeline.pipeline_utils import (
    extract_color_palette,
    _rgb_to_hex,
    _hex_to_rgb_tuple,
    calculate_luminance,
    extract_lut_available_colors,
    get_lut_color_choices,
    generate_lut_color_dropdown_html,
    detect_lut_color_mode,
    detect_image_type,
    _ensure_quantized_image_in_cache,
    generate_auto_height_map,
    _recommend_lut_colors_by_rgb,
    _build_selection_meta,
    _resolve_highlight_mask,
    _build_dual_recommendations,
    _resolve_click_selection_hexes,
    generate_lut_grid_html,
    generate_lut_card_grid_html,
)

# --- s03_color_replacement ---
from core.pipeline.s03_color_replacement import (
    _normalize_color_replacements_input,
    _apply_region_replacement,
    _apply_regions_to_raster_outputs,
    _compute_connected_region_mask_4n,
)

# --- s11_glb_preview ---
from core.pipeline.s11_glb_preview import (
    generate_segmented_glb,
    generate_realtime_glb,
    generate_empty_bed_glb,
    _create_preview_mesh,
    _merge_low_frequency_colors,
    _build_color_voxel_mesh,
)

# --- s06_voxel_building ---
from core.pipeline.s06_voxel_building import (
    _build_voxel_matrix,
    _build_voxel_matrix_faceup,
    _build_relief_voxel_matrix,
    _build_cloisonne_voxel_matrix,
    _normalize_color_height_map,
)

# --- s05_preview_generation ---
from core.pipeline.s05_preview_generation import (
    _calculate_loop_position,
    _calculate_loop_info,
    _draw_loop_on_preview,
)

# --- s08_auxiliary_meshes ---
from core.pipeline.s08_auxiliary_meshes import (
    _generate_outline_mesh,
    _parse_outline_slot,
)

# --- s04_debug_preview ---
from core.pipeline.s04_debug_preview import _save_debug_preview

# --- p06_bed_rendering ---
from core.pipeline.p06_bed_rendering import (
    render_preview,
    _draw_loop_on_canvas,
    _create_bed_mesh,
)

# --- coordinator ---
from core.pipeline.coordinator import run_raster_pipeline, run_preview_pipeline

# Try to import LUTManager for metadata loading
try:
    from utils.lut_manager import LUTManager
except ImportError:
    LUTManager = None


# ========== Main Conversion Function (Thin Wrapper) ==========

def convert_image_to_3d(image_path, lut_path, target_width_mm, spacer_thick,
                         structure_mode, auto_bg, bg_tol, color_mode,
                         add_loop, loop_width, loop_length, loop_hole, loop_pos,
                         modeling_mode=ModelingMode.VECTOR, quantize_colors=32,
                         blur_kernel=0, smooth_sigma=10,
                         color_replacements=None, replacement_regions=None, backing_color_id=0, separate_backing=False,
                         enable_relief=False, color_height_map=None,
                         height_mode: str = "color",
                         heightmap_path=None, heightmap_max_height=None,
                         enable_cleanup=True,
                         enable_outline=False, outline_width=2.0,
                         enable_cloisonne=False, wire_width_mm=0.4,
                         wire_height_mm=0.4,
                         free_color_set=None,
                         enable_coating=False, coating_height_mm=0.08,
                         hue_weight: float = 0.0,
                         chroma_gate: float = 15.0,
                         matched_rgb_path: Optional[str] = None,
                         loop_angle: float = 0.0,
                         loop_offset_x: float = 0.0,
                         loop_offset_y: float = 0.0,
                         loop_position_preset: Optional[str] = "top-center",
                         printer_id: str = 'bambu-h2d',
                         slicer: str = 'BambuStudio',
                         progress=None):
    """Main conversion function: Convert image to 3D model.
    主转换函数：将图像转换为 3D 模型。薄包装层，委托给 coordinator。

    Returns:
        Tuple of (3mf_path, glb_path, preview_image, status_message, recipe_path)
    """
    ctx = {k: v for k, v in locals().items() if k != 'progress'}
    ctx['progress'] = progress
    ctx = run_raster_pipeline(ctx)
    if ctx.get('error'):
        return None, None, None, ctx['error'], None
    return ctx.get('result_tuple', (None, None, None, '[ERROR] No result', None))


# ========== Preview Function (Thin Wrapper) ==========

def generate_preview_cached(image_path, lut_path, target_width_mm,
                            auto_bg, bg_tol, color_mode,
                            modeling_mode: ModelingMode = ModelingMode.HIGH_FIDELITY,
                            quantize_colors: int = 64,
                            backing_color_id: int = 0,
                            enable_cleanup: bool = True,
                            is_dark: bool = True,
                            hue_weight: float = 0.0,
                            chroma_gate: float = 15.0):
    """Generate preview and cache data. Thin wrapper, delegates to coordinator.
    生成预览和缓存数据。薄包装层，委托给 coordinator。

    Returns:
        tuple: (display_image, cache_data, status_message)
    """
    ctx = {k: v for k, v in locals().items()}
    ctx = run_preview_pipeline(ctx)
    if ctx.get('error'):
        return None, None, ctx['error']
    return ctx.get('display_image'), ctx.get('cache'), ctx.get('status_msg', '[OK]')


# ========== Gradio UI Functions (Unchanged) ==========


def on_preview_click(cache, loop_pos, evt: gr.SelectData, bed_label=None):
    """Handle preview image click event."""
    if evt is None or cache is None:
        return loop_pos, False, "Invalid click - please generate preview first"
    
    if bed_label is None:
        bed_label = BedManager.DEFAULT_BED

    click_x, click_y = evt.index
    
    target_w = cache['target_w']
    target_h = cache['target_h']
    target_width_mm = cache.get('target_width_mm')
    
    bed_w_mm, bed_h_mm = BedManager.get_bed_size(bed_label)
    ppm = BedManager.compute_scale(bed_w_mm, bed_h_mm)
    margin = int(30 * ppm / 3)

    canvas_w = int(bed_w_mm * ppm) + margin
    canvas_h = int(bed_h_mm * ppm) + margin

    # Use target_width_mm from cache for accurate physical size
    if target_width_mm is not None and target_width_mm > 0:
        model_w_mm = target_width_mm
        model_h_mm = target_width_mm * target_h / target_w
    else:
        model_w_mm = target_w * PrinterConfig.NOZZLE_WIDTH
        model_h_mm = target_h * PrinterConfig.NOZZLE_WIDTH
    new_w = max(1, int(model_w_mm * ppm))
    new_h = max(1, int(model_h_mm * ppm))

    offset_x = margin + (int(bed_w_mm * ppm) - new_w) // 2
    offset_y = (int(bed_h_mm * ppm) - new_h) // 2

    # Gradio may scale the displayed image
    gradio_display_height = 600
    gradio_display_width = 900
    scale_by_height = gradio_display_height / canvas_h
    scale_by_width = gradio_display_width / canvas_w
    gradio_scale = min(1.0, scale_by_height, scale_by_width)
    
    canvas_click_x = click_x / gradio_scale
    canvas_click_y = click_y / gradio_scale
    
    # Convert from canvas coords to original image pixel coords
    # Each pixel in original image = (model_w_mm / target_w) mm
    mm_per_px = model_w_mm / target_w
    img_click_x = (canvas_click_x - offset_x) / (mm_per_px * ppm)
    img_click_y = (canvas_click_y - offset_y) / (mm_per_px * ppm)
    
    orig_x = max(0, min(target_w - 1, img_click_x))
    orig_y = max(0, min(target_h - 1, img_click_y))
    
    pos_info = f"Position: ({orig_x:.1f}, {orig_y:.1f}) px"
    return (orig_x, orig_y), True, pos_info


def update_preview_with_loop(cache, loop_pos, add_loop,
                            loop_width, loop_length, loop_hole, loop_angle):
    """Update preview image with keychain loop."""
    if cache is None:
        return None
    
    preview_rgba = cache['preview_rgba'].copy()
    color_conf = cache['color_conf']
    target_width_mm = cache.get('target_width_mm')
    is_dark = cache.get('is_dark', True)
    
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width, loop_length, loop_hole, loop_angle,
        add_loop, color_conf,
        bed_label=cache.get('bed_label'),
        target_width_mm=target_width_mm, is_dark=is_dark
    )
    return display


def on_remove_loop():
    """Remove keychain loop."""
    return None, False, 0, "Loop removed"


def generate_final_model(image_path, lut_path, target_width_mm, spacer_thick,
                        structure_mode, auto_bg, bg_tol, color_mode,
                        add_loop, loop_width, loop_length, loop_hole, loop_pos,
                        modeling_mode=ModelingMode.VECTOR, quantize_colors=64,
                        color_replacements=None, replacement_regions=None, backing_color_name="White",
                        separate_backing=False, enable_relief=False, color_height_map=None,
                        height_mode: str = "color",
                        heightmap_path=None, heightmap_max_height=None,
                        enable_cleanup=True,
                        enable_outline=False, outline_width=2.0,
                        enable_cloisonne=False, wire_width_mm=0.4,
                        wire_height_mm=0.4,
                        free_color_set=None,
                        enable_coating=False, coating_height_mm=0.08,
                        hue_weight: float = 0.0,
                        chroma_gate: float = 15.0,
                        matched_rgb_path: Optional[str] = None,
                        loop_angle: float = 0.0,
                        loop_offset_x: float = 0.0,
                        loop_offset_y: float = 0.0,
                        loop_position_preset: Optional[str] = "top-center",
                        printer_id: str = 'bambu-h2d',
                        slicer: str = 'BambuStudio',
                        progress=None):
    """Wrapper function for generating final model.
    生成最终模型的包装函数。
    
    Directly calls main conversion function with smart defaults:
    - blur_kernel=0 (disable median filter, preserve details)
    - smooth_sigma=10 (gentle bilateral filter, preserve edges)
    """
    # Convert backing color name to ID or use special marker for separate backing
    try:
        separate_backing = bool(separate_backing) if separate_backing is not None else False
    except Exception as e:
        print(f"[CONVERTER] Error reading separate_backing parameter: {e}, using default (False)")
        separate_backing = False
    
    if separate_backing:
        backing_color_id = -2  # Special marker for separate backing
        print(f"[CONVERTER] Backing will be separated as individual object (white)")
    else:
        color_conf = ColorSystem.get(color_mode)
        backing_color_id = color_conf['map'].get(backing_color_name, 0)
        print(f"[CONVERTER] Backing color: {backing_color_name} (ID={backing_color_id})")
    
    # Handle relief mode parameters
    if color_height_map is None:
        color_height_map = {}
    
    return convert_image_to_3d(
        image_path, lut_path, target_width_mm, spacer_thick,
        structure_mode, auto_bg, bg_tol, color_mode,
        add_loop, loop_width, loop_length, loop_hole, loop_pos,
        modeling_mode, quantize_colors,
        blur_kernel=0,
        smooth_sigma=10,
        color_replacements=color_replacements,
        replacement_regions=replacement_regions,
        backing_color_id=backing_color_id,
        separate_backing=separate_backing,
        enable_relief=enable_relief,
        color_height_map=color_height_map,
        height_mode=height_mode,
        heightmap_path=heightmap_path,
        heightmap_max_height=heightmap_max_height,
        enable_cleanup=enable_cleanup,
        enable_outline=enable_outline,
        outline_width=outline_width,
        enable_cloisonne=enable_cloisonne,
        wire_width_mm=wire_width_mm,
        wire_height_mm=wire_height_mm,
        free_color_set=free_color_set,
        enable_coating=enable_coating,
        coating_height_mm=coating_height_mm,
        hue_weight=hue_weight,
        chroma_gate=chroma_gate,
        matched_rgb_path=matched_rgb_path,
        loop_angle=loop_angle,
        loop_offset_x=loop_offset_x,
        loop_offset_y=loop_offset_y,
        loop_position_preset=loop_position_preset,
        printer_id=printer_id,
        slicer=slicer,
        progress=progress,
    )


# ========== Color Replacement Functions ==========

def update_preview_with_backing_color(cache, backing_color_id: int):
    """
    Update preview image with new backing color without re-processing the entire image.
    """
    if cache is None:
        return None, "[WARNING] Error: Cache cannot be None"
    
    try:
        # Validate backing_color_id
        color_conf = cache['color_conf']
        num_materials = len(color_conf['slots'])
        if backing_color_id < 0 or backing_color_id >= num_materials:
            print(f"[CONVERTER] Warning: Invalid backing_color_id={backing_color_id}, using default (0)")
            backing_color_id = 0
        
        # Get data from cache
        material_matrix = cache['material_matrix']
        mask_solid = cache['mask_solid']
        preview_rgba = cache['preview_rgba'].copy()
        
        target_h, target_w = material_matrix.shape[:2]
        
        # Get backing color from color system
        backing_color_rgba = color_conf['preview'][backing_color_id]
        backing_color_rgb = backing_color_rgba[:3]
        
        # Check for backing-only pixels: solid pixels where all material layers are -1
        all_layers_transparent = np.all(material_matrix == -1, axis=2)
        backing_only_mask = mask_solid & all_layers_transparent
        
        # Update backing-only areas with new backing color
        if np.any(backing_only_mask):
            preview_rgba[backing_only_mask, :3] = backing_color_rgb
            preview_rgba[backing_only_mask, 3] = 255
            print(f"[CONVERTER] Updated {np.sum(backing_only_mask)} backing-only pixels with color {color_conf['slots'][backing_color_id]}")
        else:
            print(f"[CONVERTER] No backing-only pixels found in preview")
        
        # Update cache with new backing_color_id
        cache['backing_color_id'] = backing_color_id
        cache['preview_rgba'] = preview_rgba.copy()
        
        return preview_rgba, f"✓ Preview updated with backing color: {color_conf['slots'][backing_color_id]}"
    
    except Exception as e:
        print(f"[CONVERTER] Error updating preview with backing color: {e}")
        # Return original preview from cache if available
        original_preview = cache.get('preview_rgba') if cache else None
        return original_preview, f"[WARNING] Preview update failed: {str(e)}. Showing original preview."


def update_preview_with_replacements(cache, replacement_regions=None,
                                     loop_pos=None, add_loop=False,
                                     loop_width=4, loop_length=8,
                                     loop_hole=2.5, loop_angle=0,
                                     lang: str = "zh",
                                     merge_map: dict = None):
    """
    Update preview image with color replacements and optional color merging applied.
    """
    if cache is None:
        return None, None, ""
    
    # Get original matched_rgb (use stored original if available)
    original_rgb = cache.get('original_matched_rgb', cache['matched_rgb'])
    mask_solid = cache['mask_solid']
    color_conf = cache['color_conf']
    backing_color_id = cache.get('backing_color_id', 0)
    target_h, target_w = original_rgb.shape[:2]
    # Start with original RGB
    matched_rgb = original_rgb.copy()

    # Apply merge map first (if provided)
    if merge_map:
        from core.color_merger import ColorMerger
        from core.image_processing import LuminaImageProcessor

        merger = ColorMerger(LuminaImageProcessor._rgb_to_lab)
        matched_rgb = merger.apply_color_merging(matched_rgb, merge_map)

    # Apply region replacements in-order (later items override earlier items)
    for item in (replacement_regions or []):
        region_mask = item.get('mask')
        replacement_hex = item.get('replacement')
        if region_mask is None or not replacement_hex:
            continue
        replacement_rgb = _hex_to_rgb_tuple(replacement_hex)
        effective_mask = region_mask & mask_solid
        if np.any(effective_mask):
            matched_rgb[effective_mask] = np.array(replacement_rgb, dtype=np.uint8)
    
    # Build new preview RGBA
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    preview_rgba[mask_solid, 3] = 255
    
    # Update cache with new data
    updated_cache = cache.copy()
    updated_cache['matched_rgb'] = matched_rgb
    updated_cache['preview_rgba'] = preview_rgba.copy()
    updated_cache['backing_color_id'] = backing_color_id
    
    # Store original if not already stored
    if 'original_matched_rgb' not in updated_cache:
        updated_cache['original_matched_rgb'] = original_rgb
    
    # Re-extract palette with new colors
    color_palette = extract_color_palette(updated_cache)
    updated_cache['color_palette'] = color_palette
    
    # Render display with loop if enabled
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width, loop_length, loop_hole, loop_angle,
        add_loop, color_conf,
        bed_label=cache.get('bed_label'),
        target_width_mm=cache.get('target_width_mm'),
        is_dark=cache.get('is_dark', True)
    )
    
    # Build auto pairs (quantized -> matched) for right table display
    auto_pairs = []
    q_img = updated_cache.get('quantized_image')
    if q_img is not None:
        h, w = matched_rgb.shape[:2]
        for y in range(h):
            for x in range(w):
                if not mask_solid[y, x]:
                    continue
                qh = _rgb_to_hex(q_img[y, x])
                mh = _rgb_to_hex(matched_rgb[y, x])
                auto_pairs.append({"quantized_hex": qh, "matched_hex": mh})

    # Generate palette HTML for display
    from ui.palette_extension import generate_palette_html
    palette_html = generate_palette_html(
        color_palette,
        replacements={},
        lang=lang,
        replacement_regions=replacement_regions or [],
        auto_pairs=auto_pairs,
    )
    
    return display, updated_cache, palette_html


# ========== Color Highlight Functions ==========

def generate_highlight_preview(cache, highlight_color: str, 
                               loop_pos=None, add_loop=False,
                               loop_width=4, loop_length=8, 
                               loop_hole=2.5, loop_angle=0):
    """
    Generate preview image with a specific color highlighted.
    """
    if cache is None:
        return None, "[ERROR] 请先生成预览 | Generate preview first"
    
    if not highlight_color:
        # No highlight - return normal preview
        preview_rgba = cache.get('preview_rgba')
        if preview_rgba is None:
            return None, "[ERROR] 缓存数据无效 | Invalid cache"
        
        color_conf = cache['color_conf']
        display = render_preview(
            preview_rgba,
            loop_pos if add_loop else None,
            loop_width, loop_length, loop_hole, loop_angle,
            add_loop, color_conf,
            bed_label=cache.get('bed_label'),
            target_width_mm=cache.get('target_width_mm'),
            is_dark=cache.get('is_dark', True)
        )
        return display, "[OK] 预览已恢复 | Preview restored"
    # Parse highlight color
    highlight_hex = highlight_color.strip().lower()
    if not highlight_hex.startswith('#'):
        highlight_hex = '#' + highlight_hex
    
    # Convert hex to RGB
    try:
        r = int(highlight_hex[1:3], 16)
        g = int(highlight_hex[3:5], 16)
        b = int(highlight_hex[5:7], 16)
        highlight_rgb = np.array([r, g, b], dtype=np.uint8)
    except (ValueError, IndexError):
        return None, f"[ERROR] 无效的颜色值 | Invalid color: {highlight_color}"
    
    # Get data from cache
    matched_rgb = cache.get('matched_rgb')
    mask_solid = cache.get('mask_solid')
    color_conf = cache.get('color_conf')
    
    if matched_rgb is None or mask_solid is None:
        return None, "[ERROR] 缓存数据不完整 | Incomplete cache"
    
    target_h, target_w = matched_rgb.shape[:2]
    
    # Create highlight mask - pixels matching the highlight color
    color_match = np.all(matched_rgb == highlight_rgb, axis=2)

    scope = cache.get('selection_scope', 'global')
    region_mask = cache.get('selected_region_mask')
    highlight_mask = _resolve_highlight_mask(
        color_match,
        mask_solid,
        region_mask=region_mask,
        scope=scope,
    )
    
    # Count highlighted pixels
    highlight_count = np.sum(highlight_mask)
    total_solid = np.sum(mask_solid)
    
    if highlight_count == 0:
        return None, f"[WARNING] 未找到颜色 {highlight_hex} | Color not found"
    
    highlight_percentage = round(highlight_count / total_solid * 100, 2)
    
    # Create highlighted preview
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    
    # For non-highlighted solid pixels: convert to grayscale and dim
    non_highlight_mask = mask_solid & ~highlight_mask
    if np.any(non_highlight_mask):
        gray_values = np.mean(matched_rgb[non_highlight_mask], axis=1).astype(np.uint8)
        dimmed_gray = (gray_values * 0.4 + 80).astype(np.uint8)
        preview_rgba[non_highlight_mask, 0] = dimmed_gray
        preview_rgba[non_highlight_mask, 1] = dimmed_gray
        preview_rgba[non_highlight_mask, 2] = dimmed_gray
        preview_rgba[non_highlight_mask, 3] = 180
    
    # For highlighted pixels: show original color with full opacity
    preview_rgba[highlight_mask, :3] = matched_rgb[highlight_mask]
    preview_rgba[highlight_mask, 3] = 255
    
    # Add a subtle colored border/glow effect around highlighted regions
    try:
        kernel = np.ones((5, 5), np.uint8)
        dilated = cv2.dilate(highlight_mask.astype(np.uint8), kernel, iterations=2)
        border_mask = (dilated > 0) & ~highlight_mask & mask_solid
        
        if np.any(border_mask):
            preview_rgba[border_mask, 0] = 0
            preview_rgba[border_mask, 1] = 255
            preview_rgba[border_mask, 2] = 255
            preview_rgba[border_mask, 3] = 200
    except Exception as e:
        print(f"[HIGHLIGHT] Border effect skipped: {e}")
    
    # Render display
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width, loop_length, loop_hole, loop_angle,
        add_loop, color_conf,
        bed_label=cache.get('bed_label'),
        target_width_mm=cache.get('target_width_mm'),
        is_dark=cache.get('is_dark', True)
    )
    
    return display, f"🔍 高亮 {highlight_hex} ({highlight_percentage}%, {highlight_count:,} 像素)"


def clear_highlight_preview(cache, loop_pos=None, add_loop=False,
                            loop_width=4, loop_length=8, 
                            loop_hole=2.5, loop_angle=0):
    """
    Clear highlight and restore normal preview.
    """
    print(f"[CLEAR_HIGHLIGHT] Called with cache={cache is not None}, loop_pos={loop_pos}, add_loop={add_loop}")
    
    if cache is None:
        print("[CLEAR_HIGHLIGHT] Cache is None!")
        return None, "[ERROR] 请先生成预览 | Generate preview first"
    
    preview_rgba = cache.get('preview_rgba')
    if preview_rgba is None:
        print("[CLEAR_HIGHLIGHT] preview_rgba is None!")
        return None, "[ERROR] 缓存数据无效 | Invalid cache"
    
    print(f"[CLEAR_HIGHLIGHT] preview_rgba shape: {preview_rgba.shape}")
    
    color_conf = cache['color_conf']
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width, loop_length, loop_hole, loop_angle,
        add_loop, color_conf,
        bed_label=cache.get('bed_label'),
        target_width_mm=cache.get('target_width_mm'),
        is_dark=cache.get('is_dark', True)
    )
    
    print(f"[CLEAR_HIGHLIGHT] display shape: {display.shape if display is not None else None}")
    
    return display, "[OK] 预览已恢复 | Preview restored"


# [新增] 预览图点击吸取颜色并高亮
def on_preview_click_select_color(cache, evt: gr.SelectData, bed_label=None):
    """
    预览图点击事件处理：吸取颜色并高亮显示
    1. 识别点击位置的颜色
    2. 生成该颜色的高亮预览图
    3. 返回颜色信息给 UI
    """
    if cache is None:
        return None, "未选择", None, "[ERROR] 请先生成预览"

    if evt is None or evt.index is None:
        return gr.update(), "未选择", None, "[WARNING] 无效点击"

    if bed_label is None:
        bed_label = cache.get('bed_label', BedManager.DEFAULT_BED)

    display_click_x, display_click_y = evt.index

    target_w = cache.get('target_w')
    target_h = cache.get('target_h')
    target_width_mm = cache.get('target_width_mm')

    if target_w is None or target_h is None:
        return gr.update(), "未选择", None, "[ERROR] 缓存数据不完整"

    bed_w_mm, bed_h_mm = BedManager.get_bed_size(bed_label)
    ppm = BedManager.compute_scale(bed_w_mm, bed_h_mm)
    margin = int(30 * ppm / 3)

    canvas_w = int(bed_w_mm * ppm) + margin
    canvas_h = int(bed_h_mm * ppm) + margin

    # Use target_width_mm from cache for accurate physical size
    if target_width_mm is not None and target_width_mm > 0:
        model_w_mm = target_width_mm
        model_h_mm = target_width_mm * target_h / target_w
    else:
        model_w_mm = target_w * PrinterConfig.NOZZLE_WIDTH
        model_h_mm = target_h * PrinterConfig.NOZZLE_WIDTH
    new_w = max(1, int(model_w_mm * ppm))
    new_h = max(1, int(model_h_mm * ppm))

    offset_x = margin + (int(bed_w_mm * ppm) - new_w) // 2
    offset_y = (int(bed_h_mm * ppm) - new_h) // 2

    # _scale_preview_image fits canvas into 1200x750 box
    gradio_scale = min(1.0, 1200 / canvas_w, 750 / canvas_h)

    canvas_click_x = display_click_x / gradio_scale
    canvas_click_y = display_click_y / gradio_scale

    # Convert canvas coords -> original image pixel coords
    mm_per_px = model_w_mm / target_w
    img_px_x = (canvas_click_x - offset_x) / (mm_per_px * ppm)
    img_px_y = (canvas_click_y - offset_y) / (mm_per_px * ppm)

    orig_x = int(img_px_x)
    orig_y = int(img_px_y)

    matched_rgb = cache.get('original_matched_rgb', cache.get('matched_rgb'))
    quantized_image = cache.get('quantized_image')
    mask_solid = cache.get('mask_solid')

    if quantized_image is None:
        _ensure_quantized_image_in_cache(cache)
        quantized_image = cache.get('quantized_image')

    if matched_rgb is None or mask_solid is None or quantized_image is None:
        return None, "未选择", None, "[ERROR] 缓存无效"

    h, w = matched_rgb.shape[:2]

    if not (0 <= orig_x < w and 0 <= orig_y < h):
        return gr.update(), "未选择", None, f"[WARNING] 点击了无效区域 ({orig_x}, {orig_y})"

    if not mask_solid[orig_y, orig_x]:
        return gr.update(), "未选择", None, "[WARNING] 点击了背景区域"

    q_rgb = tuple(int(v) for v in quantized_image[orig_y, orig_x])
    m_rgb = tuple(int(v) for v in matched_rgb[orig_y, orig_x])

    region_mask = _compute_connected_region_mask_4n(quantized_image, mask_solid, orig_x, orig_y)
    cache['selected_region_mask'] = region_mask
    cache.update(_build_selection_meta(q_rgb, m_rgb, scope="region"))

    q_hex = cache['selected_quantized_hex']
    m_hex = cache['selected_matched_hex']

    print(f"[CLICK] Coords: ({orig_x}, {orig_y}), Quantized: {q_hex}, Matched: {m_hex}")

    display_img, status_msg = generate_highlight_preview(
        cache,
        highlight_color=q_hex,
        add_loop=False
    )

    display_text = f"量化色 {q_hex} | 原配准色 {m_hex}"
    if display_img is None:
        return gr.update(), display_text, q_hex, status_msg

    return display_img, display_text, q_hex, status_msg


def generate_lut_grid_html(lut_path, lang: str = "zh"):
    """
    生成 LUT 可用颜色的 HTML 网格 (with hue filter + smart search)
    """
    from core.i18n import I18n
    import colorsys
    colors = extract_lut_available_colors(lut_path)

    if not colors:
        return f"<div style='color:orange'>LUT 文件无效或为空</div>"

    count = len(colors)

    def _classify_hue(r, g, b):
        rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
        h, s, v = colorsys.rgb_to_hsv(rf, gf, bf)
        h360 = h * 360
        if s < 0.15 or v < 0.10:
            return 'neutral'
        if h360 < 15 or h360 >= 345:
            return 'red'
        elif h360 < 40:
            return 'orange'
        elif h360 < 70:
            return 'yellow'
        elif h360 < 160:
            return 'green'
        elif h360 < 195:
            return 'cyan'
        elif h360 < 260:
            return 'blue'
        elif h360 < 345:
            return 'purple'
        return 'neutral'

    from ui.palette_extension import build_search_bar_html, build_hue_filter_bar_html

    # Derive LUT key for favorites persistence
    _lut_key = os.path.splitext(os.path.basename(lut_path))[0] if lut_path else ''

    html = f"""
    <div class="lut-grid-container">
        <div style="margin-bottom: 8px; font-size: 12px; color: #666;">
            {I18n.get('lut_grid_count', lang).format(count=count)}: <span id="lut-color-visible-count">{count}</span>
        </div>
        {build_search_bar_html(lang)}
        {build_hue_filter_bar_html(lang)}
        <div id="lut-color-grid-container" data-lut-key="{_lut_key}" style="
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            max-height: 300px;
            overflow-y: auto;
            padding: 5px;
            border: 1px solid #eee;
            border-radius: 8px;
            background: #f9f9f9;">
    """

    for entry in colors:
        hex_val = entry['hex']
        r, g, b = entry['color']
        rgb_val = f"R:{r} G:{g} B:{b}"
        hue_cat = _classify_hue(r, g, b)

        html += f"""
        <div class="lut-color-swatch-container" data-hue="{hue_cat}" style="display:flex;">
        <div class="lut-swatch lut-color-swatch"
             data-color="{hex_val}"
             style="background-color: {hex_val}; width:24px; height:24px; cursor:pointer; border:1px solid #ddd; border-radius:3px;"
             title="{hex_val} ({rgb_val})">
        </div>
        </div>
        """

    html += "</div></div>"
    return html


def generate_lut_card_grid_html(lut_path, lang: str = "zh"):
    """
    Generate a calibration-card-style (色卡) HTML grid for the LUT.

    Colors are displayed in their original LUT order arranged in a square grid,
    matching the physical calibration board layout.  For 8-color LUTs the two
    halves are shown side-by-side horizontally.

    Includes search bar (highlight-in-place, no hiding) and hue filter
    (dims non-matching swatches instead of hiding to preserve grid layout).

    Each swatch is clickable (same data-color / class as the swatch grid) so
    the existing event-delegation click handler picks it up automatically.
    """
    if not lut_path:
        return "<div style='color:orange'>LUT 文件无效或为空</div>"

    try:
        lut_grid = np.load(lut_path)
        measured_colors = lut_grid.reshape(-1, 3)
    except Exception as e:
        return f"<div style='color:orange'>LUT 加载失败: {e}</div>"

    total = len(measured_colors)

    from core.i18n import I18n
    import colorsys

    def _classify_hue(r, g, b):
        rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
        h, s, v = colorsys.rgb_to_hsv(rf, gf, bf)
        h360 = h * 360
        if s < 0.15 or v < 0.10:
            return 'neutral'
        if h360 < 15 or h360 >= 345:
            return 'red'
        elif h360 < 40:
            return 'orange'
        elif h360 < 70:
            return 'yellow'
        elif h360 < 160:
            return 'green'
        elif h360 < 195:
            return 'cyan'
        elif h360 < 260:
            return 'blue'
        elif h360 < 345:
            return 'purple'
        return 'neutral'

    import math
    if total == 2738:
        half = total // 2
        remainder = total - half
        dim1 = int(math.ceil(math.sqrt(half)))
        dim2 = int(math.ceil(math.sqrt(remainder)))
        grids = [
            (measured_colors[:half], dim1, "色卡 A" if lang == "zh" else "Card A"),
            (measured_colors[half:], dim2, "色卡 B" if lang == "zh" else "Card B"),
        ]
    else:
        dim = int(math.ceil(math.sqrt(total)))
        label = f"{total} 色色卡" if lang == "zh" else f"{total}-color Card"
        grids = [(measured_colors, dim, label)]

    cell = 18
    gap = 1

    from ui.palette_extension import build_search_bar_html, build_hue_filter_bar_html

    html_parts = [
        f'<div style="margin-bottom:8px; font-size:12px; color:#666;">{I18n.get("lut_grid_count", lang).format(count=total)}: <span id="lut-color-visible-count">{total}</span></div>',
        build_search_bar_html(lang),
        build_hue_filter_bar_html(lang),
    ]

    # Derive LUT key for favorites persistence
    _lut_key = os.path.splitext(os.path.basename(lut_path))[0] if lut_path else ''

    # Grid
    html_parts.append(
        f"<div id='lut-color-grid-container' data-lut-key='{_lut_key}' style='display:flex; gap:12px; align-items:flex-start; "
        "overflow-x:auto; padding:4px;'>"
    )

    for colors_arr, dim, title in grids:
        html_parts.append(
            f"<div style='flex-shrink:0;'>"
            f"<div style='font-size:11px; color:#666; margin-bottom:4px;'>{title} ({len(colors_arr)})</div>"
            f"<div style='display:grid; grid-template-columns:repeat({dim}, {cell}px); gap:{gap}px; "
            f"border:1px solid #eee; border-radius:6px; padding:4px; background:#f9f9f9;'>"
        )
        for c in colors_arr:
            r, g, b = int(c[0]), int(c[1]), int(c[2])
            hex_val = f"#{r:02x}{g:02x}{b:02x}"
            hue_cat = _classify_hue(r, g, b)
            html_parts.append(
                f"<div class='lut-swatch lut-color-swatch' data-color='{hex_val}' data-hue='{hue_cat}' "
                f"style='width:{cell}px;height:{cell}px;background:{hex_val};"
                f"cursor:pointer;border-radius:2px;' "
                f"title='{hex_val} (R:{r} G:{g} B:{b})'></div>"
            )
        html_parts.append("</div></div>")

    html_parts.append("</div>")
    return "".join(html_parts)


# ========== Auto-detection Functions ==========

def detect_lut_color_mode(lut_path):
    """
    自动检测LUT文件的颜色模式
    
    Args:
        lut_path: LUT文件路径
    
    Returns:
        str: 颜色模式 ("BW (Black & White)", "Merged", "6-Color (Smart 1296)", "8-Color Max", etc.)
    """
    if not lut_path or not os.path.exists(lut_path):
        return None
    
    try:
        if lut_path.endswith('.npz'):
            data = np.load(lut_path)
            if 'rgb' in data:
                rgb = data['rgb']
                total_colors = int(rgb.reshape(-1, 3).shape[0])
                stacks = data['stacks'] if 'stacks' in data else None
                layer_count = int(stacks.shape[1]) if isinstance(stacks, np.ndarray) and stacks.ndim == 2 else None
                max_mat = int(np.max(stacks)) if isinstance(stacks, np.ndarray) and stacks.size > 0 else None
                if total_colors >= 2400 and total_colors < 2600 and layer_count == 6 and (max_mat is None or max_mat <= 4):
                    print(f"[AUTO_DETECT] Detected 5-Color Extended mode from .npz ({total_colors} colors)")
                    return "5-Color Extended"
                if total_colors >= 2600 and total_colors <= 2800:
                    print(f"[AUTO_DETECT] Detected 8-Color mode from .npz ({total_colors} colors)")
                    return "8-Color Max"
                if total_colors >= 1200 and total_colors < 1400:
                    print(f"[AUTO_DETECT] Detected 6-Color mode from .npz ({total_colors} colors)")
                    return "6-Color (Smart 1296)"
                if total_colors >= 900 and total_colors < 1200:
                    print(f"[AUTO_DETECT] Detected 4-Color mode from .npz ({total_colors} colors)")
                    return "4-Color"
                if total_colors >= 30 and total_colors <= 35:
                    print(f"[AUTO_DETECT] Detected 2-Color BW mode from .npz ({total_colors} colors)")
                    return "BW (Black & White)"
            print(f"[AUTO_DETECT] Detected Merged LUT (.npz format)")
            return "Merged"
        
        # .json (Keyed JSON) format
        if lut_path.endswith('.json'):
            from utils.lut_manager import LUTManager
            rgb, stacks, _meta = LUTManager.load_lut_with_metadata(lut_path)
            # 优先使用存储的 color_mode
            if _meta and _meta.color_mode:
                print(f"[AUTO_DETECT] Using stored color_mode from metadata: {_meta.color_mode}")
                return _meta.color_mode
            # 回退到基于数量的推断
            total_colors = len(rgb) if rgb is not None else 0
            layer_count = int(stacks.shape[1]) if isinstance(stacks, np.ndarray) and stacks.ndim == 2 else None
            max_mat = int(np.max(stacks)) if isinstance(stacks, np.ndarray) and stacks.size > 0 else None
            print(f"[AUTO_DETECT] JSON LUT: {total_colors} colors, layer_count={layer_count}, max_mat={max_mat}")
            if total_colors >= 2400 and total_colors < 2600 and layer_count == 6 and (max_mat is None or max_mat <= 4):
                print(f"[AUTO_DETECT] Detected 5-Color Extended mode from .json ({total_colors} colors)")
                return "5-Color Extended"
            if total_colors >= 2600 and total_colors <= 2800:
                print(f"[AUTO_DETECT] Detected 8-Color mode from .json ({total_colors} colors)")
                return "8-Color Max"
            if total_colors >= 1200 and total_colors < 1400:
                print(f"[AUTO_DETECT] Detected 6-Color mode from .json ({total_colors} colors)")
                return "6-Color (Smart 1296)"
            if total_colors >= 900 and total_colors < 1200:
                print(f"[AUTO_DETECT] Detected 4-Color mode from .json ({total_colors} colors)")
                return "4-Color"
            if total_colors >= 30 and total_colors <= 35:
                print(f"[AUTO_DETECT] Detected 2-Color BW mode from .json ({total_colors} colors)")
                return "BW (Black & White)"
            print(f"[AUTO_DETECT] Non-standard JSON LUT size ({total_colors} colors), detected as Merged")
            return "Merged"
        
        # Standard .npy format
        lut_data = np.load(lut_path)
        
        # 确保是2D数组
        if lut_data.ndim == 1:
            # 如果是1D数组，假设是 (N*3,) 格式，重塑为 (N, 3)
            if len(lut_data) % 3 == 0:
                lut_data = lut_data.reshape(-1, 3)
            else:
                print(f"[AUTO_DETECT] Invalid LUT format: cannot reshape to (N, 3)")
                return None
        
        # 计算颜色数量
        if lut_data.ndim == 2:
            total_colors = lut_data.shape[0]
        else:
            total_colors = lut_data.shape[0] * lut_data.shape[1]
        
        print(f"[AUTO_DETECT] LUT shape: {lut_data.shape}, total colors: {total_colors}")
        
        # 2色模式：32色 (2^5 = 32)
        if total_colors >= 30 and total_colors <= 35:
            print(f"[AUTO_DETECT] Detected 2-Color BW mode (32 colors)")
            return "BW (Black & White)"
        
        # 5-Color Extended模式：~2468色 (1024 base + 1444 extended)
        elif total_colors >= 2400 and total_colors < 2600:
            print(f"[AUTO_DETECT] Detected 5-Color Extended mode ({total_colors} colors)")
            return "5-Color Extended"
        
        # 8色模式：2600-2800色
        elif total_colors >= 2600 and total_colors <= 2800:
            print(f"[AUTO_DETECT] Detected 8-Color mode ({total_colors} colors)")
            return "8-Color Max"
        
        # 6色模式：1200-1400色
        elif total_colors >= 1200 and total_colors < 1400:
            print(f"[AUTO_DETECT] Detected 6-Color mode ({total_colors} colors)")
            return "6-Color (Smart 1296)"
        
        # 4色模式：900-1200色
        elif total_colors >= 900 and total_colors < 1200:
            print(f"[AUTO_DETECT] Detected 4-Color mode ({total_colors} colors)")
            return "4-Color"
        
        else:
            # 非标准尺寸：识别为合并色卡
            print(f"[AUTO_DETECT] Non-standard LUT size ({total_colors} colors), detected as Merged")
            return "Merged"
            
    except Exception as e:
        print(f"[AUTO_DETECT] Error detecting LUT mode: {e}")
        import traceback
        traceback.print_exc()
        return None


def detect_image_type(image_path):
    """
    Detect image type and return recommended modeling mode.
    自动检测图像类型并返回推荐的建模模式。

    Args:
        image_path (str): Image file path. (图像文件路径)

    Returns:
        gr.update: Gradio update object with new mode, or no-op update. (Gradio 更新对象)
    """
    import gradio as gr
    if not image_path:
        return gr.update()
    
    try:
        ext = os.path.splitext(image_path)[1].lower()
        
        if ext == '.svg':
            print(f"[AUTO_DETECT] SVG file detected, recommending SVG Mode")
            return gr.update(value=ModelingMode.VECTOR)
        else:
            print(f"[AUTO_DETECT] Raster image detected ({ext}), keeping current mode")
            return gr.update()  # 不改变当前选择
            
    except Exception as e:
        print(f"[AUTO_DETECT] Error detecting image type: {e}")
        return None
