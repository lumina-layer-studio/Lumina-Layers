"""
Lumina Studio - Converter UI Helpers

UI-facing helpers moved from core/converter.py.
"""

import os
from typing import List, Optional

import gradio as gr
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from config import (
    PrinterConfig,
    ColorSystem,
    ModelingMode,
    PREVIEW_SCALE,
    PREVIEW_MARGIN,
    ColorMode,
)
from core.converter import ConversionRequest
from core.image_processing import LuminaImageProcessor
from utils.i18n_help import make_status_tag
from ui.palette_extension import generate_palette_html, generate_lut_color_grid_html

# Keep in sync with ui/tabs/converter_tab.py::_scale_preview_image defaults.
PREVIEW_UI_MAX_W = 900
PREVIEW_UI_MAX_H = 560


def _preview_click_to_original_coords(
    click_x: float, click_y: float, target_w: int, target_h: int
) -> tuple[float, float]:
    """Convert preview click coords to original image coords.

    The preview shown in UI may be additionally downscaled by
    `ui/tabs/converter_tab.py::_scale_preview_image`. We support both
    coordinate semantics seen across Gradio versions:
    1) click in scaled preview data coords
    2) click in render-canvas coords
    """
    canvas_w = target_w * PREVIEW_SCALE + PREVIEW_MARGIN * 2
    canvas_h = target_h * PREVIEW_SCALE + PREVIEW_MARGIN * 2
    ui_scale = min(1.0, PREVIEW_UI_MAX_W / canvas_w, PREVIEW_UI_MAX_H / canvas_h)

    canvas_click_x = click_x
    canvas_click_y = click_y

    # If click is within scaled preview bounds, treat it as scaled coords.
    # This avoids systematic bias when preview array is downscaled before UI render.
    if ui_scale < 0.999:
        scaled_w = canvas_w * ui_scale
        scaled_h = canvas_h * ui_scale
        if 0 <= click_x <= scaled_w + 1 and 0 <= click_y <= scaled_h + 1:
            canvas_click_x = click_x / ui_scale
            canvas_click_y = click_y / ui_scale

    orig_x = (canvas_click_x - PREVIEW_MARGIN) / PREVIEW_SCALE
    orig_y = (canvas_click_y - PREVIEW_MARGIN) / PREVIEW_SCALE
    return orig_x, orig_y


def extract_lut_available_colors(lut_path: str) -> List[dict]:
    """
    Extract all available colors from a LUT file.

    This function loads a LUT .npy file and extracts all unique colors
    that the printer can produce. These colors can be used as replacement
    options in the color replacement feature.

    Args:
        lut_path: Path to the LUT .npy file

    Returns:
        List of dicts, each containing:
        - 'color': (R, G, B) tuple
        - 'hex': '#RRGGBB' string

        Returns empty list if LUT cannot be loaded.
    """
    if not lut_path:
        return []

    try:
        # Load LUT data
        lut_grid = np.load(lut_path)
        measured_colors = lut_grid.reshape(-1, 3)

        # Get unique colors
        unique_colors = np.unique(measured_colors, axis=0)

        # Build color list
        colors = []
        for color in unique_colors:
            r, g, b = int(color[0]), int(color[1]), int(color[2])
            colors.append({"color": (r, g, b), "hex": f"#{r:02x}{g:02x}{b:02x}"})

        # Sort by brightness (dark to light) for better UX
        colors.sort(key=lambda x: sum(x["color"]))

        print(f"[LUT_COLORS] Extracted {len(colors)} unique colors from LUT")
        return colors

    except Exception as e:
        print(f"[LUT_COLORS] Error extracting colors from LUT: {e}")
        return []


def get_lut_color_choices(lut_path: str) -> List[tuple]:
    """
    Get LUT colors formatted for Gradio Dropdown.

    Args:
        lut_path: Path to the LUT .npy file

    Returns:
        List of (display_label, hex_value) tuples for Dropdown choices.
        Display label includes a colored square emoji approximation.
    """
    colors = extract_lut_available_colors(lut_path)

    if not colors:
        return []

    choices = []
    for entry in colors:
        hex_color = entry["hex"]
        r, g, b = entry["color"]
        # Create a display label with RGB values
        label = f"■ {hex_color} (R:{r} G:{g} B:{b})"
        choices.append((label, hex_color))

    return choices


def generate_lut_color_dropdown_html(
    lut_path: str,
    selected_color: Optional[str] = None,
    used_colors: Optional[set] = None,
) -> str:
    """
    Generate HTML for displaying LUT available colors as a clickable visual grid.

    Colors are grouped into two sections:
    1. Colors used in current image (if any)
    2. Other available colors

    This provides a visual preview of all available colors from the LUT,
    allowing users to click directly to select a replacement color.

    Args:
        lut_path: Path to the LUT .npy file
        selected_color: Currently selected replacement color hex
        used_colors: Set of hex colors currently used in the image (for grouping)

    Returns:
        HTML string showing available colors as a clickable grid
    """
    colors = extract_lut_available_colors(lut_path)
    # Delegate HTML generation to palette_extension (non-invasive)
    return generate_lut_color_grid_html(
        colors,
        selected_color or "",
        used_colors or set(),
    )


def extract_color_palette(preview_cache: dict) -> List[dict]:
    """
    Extract unique colors from preview cache.

    Args:
        preview_cache: Cache data from generate_preview_cached containing:
            - matched_rgb: (H, W, 3) uint8 array of matched colors
            - mask_solid: (H, W) bool array indicating solid pixels

    Returns:
        List of dicts sorted by pixel count (descending), each containing:
        - 'color': (R, G, B) tuple
        - 'hex': '#RRGGBB' string
        - 'count': pixel count
        - 'percentage': percentage of total solid pixels (0.0-100.0)
    """
    if preview_cache is None:
        return []

    matched_rgb = preview_cache.get("matched_rgb")
    mask_solid = preview_cache.get("mask_solid")

    if matched_rgb is None or mask_solid is None:
        return []

    # Get only solid pixels
    solid_pixels = matched_rgb[mask_solid]

    if len(solid_pixels) == 0:
        return []

    total_solid = len(solid_pixels)

    # Find unique colors and their counts
    # Reshape to (N, 3) and find unique rows
    unique_colors, counts = np.unique(solid_pixels, axis=0, return_counts=True)

    # Build palette entries
    palette = []
    for color, count in zip(unique_colors, counts):
        r, g, b = int(color[0]), int(color[1]), int(color[2])
        palette.append(
            {
                "color": (r, g, b),
                "hex": f"#{r:02x}{g:02x}{b:02x}",
                "count": int(count),
                "percentage": round(count / total_solid * 100, 2),
            }
        )

    # Sort by count descending
    palette.sort(key=lambda x: x["count"], reverse=True)

    return palette


def generate_preview_cached(
    image_path,
    request: ConversionRequest,
):
    """
    Generate preview and cache data
    For 2D preview interface

    Args:
        image_path: Path to input image
        lut_path: LUT file path (string) or Gradio File object
        target_width_mm: Target width in millimeters
        auto_bg: Enable automatic background removal
        bg_tol: Background tolerance value
        color_mode: Color system mode (CMYW/RYBW)
        modeling_mode: Modeling mode (HIGH_FIDELITY/PIXEL_ART)
        quantize_colors: K-Means quantization color count (8-256)

    Returns:
        tuple: (preview_image, cache_data, status_message)
    """
    if image_path is None:
        return None, None, make_status_tag("msg_no_image")
    if request.lut_path is None:
        return None, None, make_status_tag("msg_no_lut")

    if isinstance(request.lut_path, str):
        actual_lut_path = request.lut_path
    else:
        return None, None, make_status_tag("conv_err_invalid_lut_file")

    modeling_mode = ModelingMode(request.modeling_mode)
    target_width_mm = request.target_width_mm
    auto_bg = request.auto_bg
    bg_tol = request.bg_tol
    color_mode = request.color_mode
    quantize_colors = request.quantize_colors
    match_strategy = request.match_strategy

    # Clamp quantize_colors to valid range
    quantize_colors = max(8, min(256, quantize_colors))

    color_conf = ColorSystem.get(color_mode)

    try:
        processor = LuminaImageProcessor(actual_lut_path, color_mode)
        result = processor.process_image(
            image_path=image_path,
            target_width_mm=target_width_mm,
            modeling_mode=modeling_mode,
            quantize_colors=quantize_colors,  # Use user-specified value
            auto_bg=auto_bg,
            bg_tol=int(bg_tol),
            blur_kernel=0,
            smooth_sigma=10,
            match_strategy=match_strategy,
        )
    except Exception as e:
        return (
            None,
            None,
            make_status_tag("conv_preview_generation_failed", error=str(e)),
        )

    matched_rgb = result["matched_rgb"]
    material_matrix = result["material_matrix"]
    mask_solid = result["mask_solid"]
    target_w, target_h = result["dimensions"]

    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    preview_rgba[mask_solid, 3] = 255

    cache = {
        "target_w": target_w,
        "target_h": target_h,
        "mask_solid": mask_solid,
        "material_matrix": material_matrix,
        "matched_rgb": matched_rgb,
        "preview_rgba": preview_rgba.copy(),
        "color_conf": color_conf,
        "quantize_colors": quantize_colors,
    }

    # Extract color palette from cache
    color_palette = extract_color_palette(cache)
    cache["color_palette"] = color_palette
    cache["original_color_palette"] = color_palette

    display = render_preview(preview_rgba, None, 0, 0, 0, 0, False, color_conf)

    num_colors = len(color_palette)
    return (
        display,
        cache,
        make_status_tag(
            "conv_preview_generated",
            target_w=target_w,
            target_h=target_h,
            num_colors=num_colors,
        ),
    )


def render_preview(
    preview_rgba,
    loop_pos,
    loop_width,
    loop_length,
    loop_hole,
    loop_angle,
    loop_enabled,
    color_conf,
):
    """Render preview with keychain loop and coordinate grid."""
    h, w = preview_rgba.shape[:2]
    new_w, new_h = w * PREVIEW_SCALE, h * PREVIEW_SCALE

    margin = PREVIEW_MARGIN
    canvas_w = new_w + margin + margin  # Left + right margins
    canvas_h = new_h + margin + margin  # Top + bottom margins

    canvas = Image.new("RGBA", (canvas_w, canvas_h), (240, 240, 245, 255))
    draw = ImageDraw.Draw(canvas)

    grid_color = (220, 220, 225, 255)
    grid_color_main = (200, 200, 210, 255)

    grid_step = 10 * PREVIEW_SCALE
    main_step = 50 * PREVIEW_SCALE

    for x in range(margin, canvas_w, grid_step):
        draw.line([(x, margin), (x, canvas_h)], fill=grid_color, width=1)
    for y in range(margin, canvas_h, grid_step):
        draw.line([(margin, y), (canvas_w, y)], fill=grid_color, width=1)

    for x in range(margin, canvas_w, main_step):
        draw.line([(x, margin), (x, canvas_h)], fill=grid_color_main, width=1)
    for y in range(margin, canvas_h, main_step):
        draw.line([(margin, y), (canvas_w, y)], fill=grid_color_main, width=1)

    axis_color = (100, 100, 120, 255)
    draw.line([(margin, margin), (margin, canvas_h)], fill=axis_color, width=2)
    draw.line(
        [(margin, canvas_h - 1), (canvas_w, canvas_h - 1)], fill=axis_color, width=2
    )

    label_color = (80, 80, 100, 255)
    try:
        font = ImageFont.load_default()
    except:
        font = None

    for i, x in enumerate(range(margin, canvas_w, main_step)):
        px_value = i * 50
        if font:
            draw.text(
                (x - 5, canvas_h - margin + 5),
                str(px_value),
                fill=label_color,
                font=font,
            )

    for i, y in enumerate(range(margin, canvas_h, main_step)):
        px_value = i * 50
        if font:
            draw.text((5, y - 5), str(px_value), fill=label_color, font=font)

    pil_img = Image.fromarray(preview_rgba, mode="RGBA")
    pil_img = pil_img.resize((new_w, new_h), Image.Resampling.NEAREST)
    canvas.paste(
        pil_img, (margin, margin), pil_img
    )  # Paste at (margin, margin) not (margin, 0)

    if loop_enabled and loop_pos is not None:
        canvas = _draw_loop_on_canvas(
            canvas,
            loop_pos,
            loop_width,
            loop_length,
            loop_hole,
            loop_angle,
            color_conf,
            margin,
        )

    return np.array(canvas)


def _draw_loop_on_canvas(
    pil_img,
    loop_pos,
    loop_width,
    loop_length,
    loop_hole,
    loop_angle,
    color_conf,
    margin,
):
    """Draw keychain loop marker on canvas."""
    loop_w_px = int(loop_width / PrinterConfig.NOZZLE_WIDTH * PREVIEW_SCALE)
    loop_h_px = int(loop_length / PrinterConfig.NOZZLE_WIDTH * PREVIEW_SCALE)
    hole_r_px = int(loop_hole / 2 / PrinterConfig.NOZZLE_WIDTH * PREVIEW_SCALE)
    circle_r_px = loop_w_px // 2

    cx = int(loop_pos[0] * PREVIEW_SCALE) + margin
    cy = int(loop_pos[1] * PREVIEW_SCALE)

    loop_size = max(loop_w_px, loop_h_px) * 2 + 20
    loop_layer = Image.new("RGBA", (loop_size, loop_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(loop_layer)

    lc = loop_size // 2
    rect_h = max(1, loop_h_px - circle_r_px)

    loop_color = (220, 60, 60, 200)
    outline_color = (255, 255, 255, 255)

    draw.rectangle(
        [lc - loop_w_px // 2, lc, lc + loop_w_px // 2, lc + rect_h],
        fill=loop_color,
        outline=outline_color,
        width=2,
    )

    draw.ellipse(
        [lc - circle_r_px, lc - circle_r_px, lc + circle_r_px, lc + circle_r_px],
        fill=loop_color,
        outline=outline_color,
        width=2,
    )

    draw.ellipse(
        [lc - hole_r_px, lc - hole_r_px, lc + hole_r_px, lc + hole_r_px],
        fill=(0, 0, 0, 0),
    )

    if loop_angle != 0:
        loop_layer = loop_layer.rotate(
            -loop_angle,
            center=(lc, lc),
            expand=False,
            resample=Image.Resampling.BICUBIC,
        )

    paste_x = cx - lc
    paste_y = cy - lc - rect_h // 2
    pil_img.paste(loop_layer, (paste_x, paste_y), loop_layer)

    return pil_img


def on_preview_click(cache, loop_pos, evt: gr.SelectData):
    """Handle preview image click event."""
    if evt is None or cache is None:
        return (
            loop_pos,
            False,
            make_status_tag("conv_invalid_click_generate_preview_first"),
        )

    click_x, click_y = evt.index
    target_w = cache["target_w"]
    target_h = cache["target_h"]

    orig_x, orig_y = _preview_click_to_original_coords(
        click_x, click_y, target_w, target_h
    )

    orig_x = max(0, min(target_w - 1, orig_x))
    orig_y = max(0, min(target_h - 1, orig_y))

    pos_info = make_status_tag(
        "conv_loop_position", x=f"{orig_x:.1f}", y=f"{orig_y:.1f}"
    )
    return (orig_x, orig_y), True, pos_info


def update_preview_with_loop(
    cache, loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle
):
    """Update preview image with keychain loop."""
    if cache is None:
        return None

    preview_rgba = cache["preview_rgba"].copy()
    color_conf = cache["color_conf"]

    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        add_loop,
        color_conf,
    )
    return display


def on_remove_loop():
    """Remove keychain loop."""
    return None, False, 0, make_status_tag("conv_loop_removed")


def update_preview_with_replacements(
    cache,
    color_replacements: dict,
    loop_pos=None,
    add_loop=False,
    loop_width=4,
    loop_length=8,
    loop_hole=2.5,
    loop_angle=0,
    lang: str = "zh",
):
    """
    Update preview image with color replacements applied.

    This function applies color replacements to the cached preview data
    without re-processing the entire image. It's designed for fast
    interactive updates when users change color mappings.

    Args:
        cache: Preview cache from generate_preview_cached
        color_replacements: Dict mapping original hex colors to replacement hex colors
                           e.g., {'#ff0000': '#00ff00'}
        loop_pos: Optional loop position tuple (x, y)
        add_loop: Whether to show keychain loop
        loop_width: Loop width in mm
        loop_length: Loop length in mm
        loop_hole: Loop hole diameter in mm
        loop_angle: Loop rotation angle in degrees

    Returns:
        tuple: (display_image, updated_cache, palette_html)
    """
    if cache is None:
        return None, None, ""

    from core.color_replacement import ColorReplacementManager

    # Get original matched_rgb (use stored original if available)
    original_rgb = cache.get("original_matched_rgb", cache["matched_rgb"])
    mask_solid = cache["mask_solid"]
    color_conf = cache["color_conf"]
    target_h, target_w = original_rgb.shape[:2]

    # Apply color replacements if any
    if color_replacements:
        manager = ColorReplacementManager.from_dict(color_replacements)
        matched_rgb = manager.apply_to_image(original_rgb)
    else:
        matched_rgb = original_rgb.copy()

    # Build new preview RGBA
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    preview_rgba[mask_solid, 3] = 255

    # Update cache with new data
    updated_cache = cache.copy()
    updated_cache["matched_rgb"] = matched_rgb
    updated_cache["preview_rgba"] = preview_rgba.copy()

    # Store original if not already stored
    if "original_matched_rgb" not in updated_cache:
        updated_cache["original_matched_rgb"] = original_rgb

    # Re-extract palette with new colors
    color_palette = extract_color_palette(updated_cache)
    updated_cache["color_palette"] = color_palette
    if "original_color_palette" not in updated_cache:
        original_cache = {"matched_rgb": original_rgb, "mask_solid": mask_solid}
        updated_cache["original_color_palette"] = extract_color_palette(original_cache)

    # Render display with loop if enabled
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        add_loop,
        color_conf,
    )

    # Generate palette HTML for display
    palette_html = generate_palette_html(
        color_palette,
        color_replacements,
        original_palette=updated_cache.get("original_color_palette", color_palette),
        lang=lang,
    )

    return display, updated_cache, palette_html


def generate_highlight_preview(
    cache,
    highlight_color: str,
    loop_pos=None,
    add_loop=False,
    loop_width=4,
    loop_length=8,
    loop_hole=2.5,
    loop_angle=0,
):
    """
    Generate preview image with a specific color highlighted.

    This function creates a preview where the selected color is shown normally
    while all other colors are dimmed/grayed out, making it easy to see
    where a specific color is used in the image.

    Args:
        cache: Preview cache from generate_preview_cached
        highlight_color: Hex color to highlight (e.g., '#ff0000')
        loop_pos: Optional loop position tuple (x, y)
        add_loop: Whether to show keychain loop
        loop_width: Loop width in mm
        loop_length: Loop length in mm
        loop_hole: Loop hole diameter in mm
        loop_angle: Loop rotation angle in degrees

    Returns:
        tuple: (display_image, status_message)
    """
    if cache is None:
        return None, make_status_tag("palette_need_preview")

    if not highlight_color:
        # No highlight - return normal preview
        preview_rgba = cache.get("preview_rgba")
        if preview_rgba is None:
            return None, make_status_tag("conv_err_invalid_cache")

        color_conf = cache["color_conf"]
        display = render_preview(
            preview_rgba,
            loop_pos if add_loop else None,
            loop_width,
            loop_length,
            loop_hole,
            loop_angle,
            add_loop,
            color_conf,
        )
        return display, make_status_tag("conv_preview_restored")

    # Parse highlight color
    highlight_hex = highlight_color.strip().lower()
    if not highlight_hex.startswith("#"):
        highlight_hex = "#" + highlight_hex

    # Convert hex to RGB
    try:
        r = int(highlight_hex[1:3], 16)
        g = int(highlight_hex[3:5], 16)
        b = int(highlight_hex[5:7], 16)
        highlight_rgb = np.array([r, g, b], dtype=np.uint8)
    except (ValueError, IndexError):
        return None, make_status_tag("conv_err_invalid_color", color=highlight_color)

    # Get data from cache
    matched_rgb = cache.get("matched_rgb")
    mask_solid = cache.get("mask_solid")
    color_conf = cache.get("color_conf")

    if matched_rgb is None or mask_solid is None:
        return None, make_status_tag("conv_err_incomplete_cache")

    target_h, target_w = matched_rgb.shape[:2]

    # Create highlight mask - pixels matching the highlight color
    color_match = np.all(matched_rgb == highlight_rgb, axis=2)
    highlight_mask = color_match & mask_solid

    # Count highlighted pixels
    highlight_count = np.sum(highlight_mask)
    total_solid = np.sum(mask_solid)

    if highlight_count == 0:
        return None, make_status_tag("conv_color_not_found", color=highlight_hex)

    highlight_percentage = round(highlight_count / total_solid * 100, 2)

    # Create highlighted preview
    # Option 1: Dim non-highlighted areas (grayscale + reduced opacity)
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)

    # For non-highlighted solid pixels: convert to grayscale and dim
    non_highlight_mask = mask_solid & ~highlight_mask
    if np.any(non_highlight_mask):
        # Convert to grayscale
        gray_values = np.mean(matched_rgb[non_highlight_mask], axis=1).astype(np.uint8)
        # Apply dimming (mix with darker gray)
        dimmed_gray = (gray_values * 0.4 + 80).astype(np.uint8)
        preview_rgba[non_highlight_mask, 0] = dimmed_gray
        preview_rgba[non_highlight_mask, 1] = dimmed_gray
        preview_rgba[non_highlight_mask, 2] = dimmed_gray
        preview_rgba[non_highlight_mask, 3] = 180  # Semi-transparent

    # For highlighted pixels: show original color with full opacity
    preview_rgba[highlight_mask, :3] = matched_rgb[highlight_mask]
    preview_rgba[highlight_mask, 3] = 255

    # Add a subtle colored border/glow effect around highlighted regions
    # by dilating the highlight mask and drawing a border
    try:
        import cv2

        kernel = np.ones((5, 5), np.uint8)
        dilated = cv2.dilate(highlight_mask.astype(np.uint8), kernel, iterations=2)
        border_mask = (dilated > 0) & ~highlight_mask & mask_solid

        # Draw border in a contrasting color (cyan for visibility)
        if np.any(border_mask):
            preview_rgba[border_mask, 0] = 0  # R
            preview_rgba[border_mask, 1] = 255  # G
            preview_rgba[border_mask, 2] = 255  # B
            preview_rgba[border_mask, 3] = 200  # Alpha
    except Exception as e:
        print(f"[HIGHLIGHT] Border effect skipped: {e}")

    # Render display
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        add_loop,
        color_conf,
    )

    return (
        display,
        make_status_tag(
            "conv_highlight_result",
            color=highlight_hex,
            percent=highlight_percentage,
            pixels=f"{highlight_count:,}",
        ),
    )


def clear_highlight_preview(
    cache,
    loop_pos=None,
    add_loop=False,
    loop_width=4,
    loop_length=8,
    loop_hole=2.5,
    loop_angle=0,
):
    """
    Clear highlight and restore normal preview.

    Args:
        cache: Preview cache from generate_preview_cached
        loop_pos: Optional loop position tuple (x, y)
        add_loop: Whether to show keychain loop
        loop_width: Loop width in mm
        loop_length: Loop length in mm
        loop_hole: Loop hole diameter in mm
        loop_angle: Loop rotation angle in degrees

    Returns:
        tuple: (display_image, status_message)
    """
    print(
        f"[CLEAR_HIGHLIGHT] Called with cache={cache is not None}, loop_pos={loop_pos}, add_loop={add_loop}"
    )

    if cache is None:
        print("[CLEAR_HIGHLIGHT] Cache is None!")
        return None, make_status_tag("palette_need_preview")

    preview_rgba = cache.get("preview_rgba")
    if preview_rgba is None:
        print("[CLEAR_HIGHLIGHT] preview_rgba is None!")
        return None, make_status_tag("conv_err_invalid_cache")

    print(f"[CLEAR_HIGHLIGHT] preview_rgba shape: {preview_rgba.shape}")

    color_conf = cache["color_conf"]
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        add_loop,
        color_conf,
    )

    print(
        f"[CLEAR_HIGHLIGHT] display shape: {display.shape if display is not None else None}"
    )

    return display, make_status_tag("conv_preview_restored")


def on_preview_click_select_color(cache, evt: gr.SelectData):
    """
    预览图点击事件处理：吸取颜色并高亮显示
    1. 识别点击位置的颜色
    2. 生成该颜色的高亮预览图
    3. 返回颜色信息给 UI
    """
    if cache is None:
        return (
            None,
            make_status_tag("palette_not_selected"),
            None,
            make_status_tag("palette_need_preview"),
        )

    if evt is None or evt.index is None:
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            make_status_tag("conv_invalid_click"),
        )

    # 1. 获取点击坐标（Gradio返回的是显示图像上的像素坐标）
    display_click_x, display_click_y = evt.index

    # 2. 获取原始图像尺寸和canvas尺寸
    target_w = cache.get("target_w")
    target_h = cache.get("target_h")

    if target_w is None or target_h is None:
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            make_status_tag("conv_err_incomplete_cache"),
        )

    # 3. 转换显示坐标 -> 原图坐标
    orig_x_f, orig_y_f = _preview_click_to_original_coords(
        display_click_x, display_click_y, target_w, target_h
    )
    orig_x = int(orig_x_f)
    orig_y = int(orig_y_f)

    matched_rgb = cache.get("matched_rgb")
    mask_solid = cache.get("mask_solid")
    if matched_rgb is None or mask_solid is None:
        return (
            None,
            make_status_tag("palette_not_selected"),
            None,
            make_status_tag("conv_err_invalid_cache"),
        )

    h, w = matched_rgb.shape[:2]

    # 检查坐标是否越界
    if not (0 <= orig_x < w and 0 <= orig_y < h):
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            make_status_tag("conv_click_invalid_area", x=orig_x, y=orig_y),
        )

    # 检查是否点击了透明/背景区域
    if not mask_solid[orig_y, orig_x]:
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            make_status_tag("conv_click_background"),
        )

    # 2. 获取像素颜色
    rgb = matched_rgb[orig_y, orig_x]
    hex_color = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

    print(f"[CLICK] Coords: ({orig_x}, {orig_y}), Color: {hex_color}")

    # 3. 立即生成高亮预览（强制关闭挂孔显示）
    display_img, status_msg = generate_highlight_preview(
        cache, highlight_color=hex_color, add_loop=False
    )

    # 返回:
    # 1. 更新后的预览图 (高亮模式)
    # 2. "已选颜色"显示文本
    # 3. "已选颜色"内部状态变量
    # 4. 状态栏消息
    if display_img is None:
        return (
            gr.update(),
            make_status_tag("conv_selected_color_at_click", color=hex_color),
            hex_color,
            status_msg,
        )
    return (
        display_img,
        make_status_tag("conv_selected_color_at_click", color=hex_color),
        hex_color,
        status_msg,
    )


def generate_lut_grid_html(lut_path, lang: str = "zh"):
    """
    生成 LUT 可用颜色的 HTML 网格
    """

    colors = extract_lut_available_colors(lut_path)

    if not colors:
        return f"<div style='color:orange'>LUT 文件无效或为空</div>"

    count = len(colors)

    html = f"""
    <div class="lut-grid-container">
        <div style="margin-bottom: 8px; font-size: 12px; color: #666;">
            可用颜色: {count} 种
        </div>
        <div style="
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
        hex_val = entry["hex"]
        r, g, b = entry["color"]
        rgb_val = f"R:{r} G:{g} B:{b}"

        html += f"""
        <div class="lut-swatch lut-color-swatch"
             data-color="{hex_val}"
             style="background-color: {hex_val}; width:24px; height:24px; cursor:pointer; border:1px solid #ddd; border-radius:3px;"
             title="{hex_val} ({rgb_val})">
        </div>
        """

    html += "</div></div>"
    return html


def detect_lut_color_mode(lut_path):
    """
    自动检测LUT文件的颜色模式

    Args:
        lut_path: LUT文件路径

    Returns:
        str: 颜色模式枚举值（用于 UI Radio 的 value）
    """
    if not lut_path or not os.path.exists(lut_path):
        return None

    try:
        lut_data = np.load(lut_path)
        total_colors = (
            lut_data.shape[0] * lut_data.shape[1]
            if lut_data.ndim >= 2
            else len(lut_data)
        )

        print(
            f"[AUTO_DETECT] LUT shape: {lut_data.shape}, total colors: {total_colors}"
        )

        # 8色模式：2738色 (8^5 = 32768)，但实际智能选择2738)
        if total_colors >= 2600 and total_colors <= 2800:
            print(f"[AUTO_DETECT] Detected 8-Color mode (2738 colors)")
            return ColorMode.EIGHT_COLOR_MAX.value

        # BW 模式：32色 (2^5 = 32)
        elif total_colors >= 30 and total_colors <= 36:
            print(f"[AUTO_DETECT] Detected BW mode (32 colors)")
            return ColorMode.BW.value

        # 6色模式：1296色 (6^5 = 7776)，但实际选择1296)
        elif total_colors >= 1200 and total_colors <= 1400:
            print(f"[AUTO_DETECT] Detected 6-Color mode (1296 colors)")
            return ColorMode.SIX_COLOR.value

        # 4色模式：1024色 (4^5 = 1024)
        elif total_colors >= 900 and total_colors <= 1100:
            print(f"[AUTO_DETECT] Detected 4-Color mode (1024 colors)")
            # 尝试从文件名推断CMYW或RYBW
            filename = os.path.basename(lut_path)
            name_lower = filename.lower()
            if "cmyw" in name_lower:
                print(f"[AUTO_DETECT] Filename suggests CMYW mode")
                return ColorMode.CMYW.value
            if "rybw" in name_lower:
                print(f"[AUTO_DETECT] Filename suggests RYBW mode")
                return ColorMode.RYBW.value
            # 无法推断时返回None，保持当前选择
            print(f"[AUTO_DETECT] Cannot infer 4-Color subtype from filename")
            return None

        else:
            print(f"[AUTO_DETECT] Unknown LUT format with {total_colors} colors")
            return None

    except Exception as e:
        print(f"[AUTO_DETECT] Error detecting LUT mode: {e}")
        return None


def detect_image_type(image_path):
    """
    自动检测图像类型并返回推荐的建模模式

    Args:
        image_path: 图像文件路径

    Returns:
        str: 建模模式 ("🎨 High-Fidelity (Smooth)", "📐 SVG Mode") 或 None
    """
    if not image_path:
        return None

    try:
        # 检查文件扩展名
        ext = os.path.splitext(image_path)[1].lower()

        if ext == ".svg":
            print(f"[AUTO_DETECT] SVG file detected, recommending SVG Mode")
            return "📐 SVG Mode"
        else:
            print(f"[AUTO_DETECT] Raster image detected ({ext}), keeping current mode")
            return None  # 不自动切换光栅图像模式

    except Exception as e:
        print(f"[AUTO_DETECT] Error detecting image type: {e}")
        return None
