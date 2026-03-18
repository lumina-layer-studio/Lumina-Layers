# -*- coding: utf-8 -*-
"""预览渲染模块

在物理热床网格上渲染模型预览图，支持挂件环叠加。
"""

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from config import PrinterConfig
from config import BedManager


def render_preview(preview_rgba, loop_pos, loop_width, loop_length,
                   loop_hole, loop_angle, loop_enabled, color_conf,
                   bed_label=None, target_width_mm=None, is_dark=True):
    """Render preview with physical bed grid and optional keychain loop.

    Args:
        preview_rgba: (H, W, 4) RGBA numpy array
        loop_pos: (x, y) loop position in image pixels
        loop_width: loop width in mm
        loop_length: loop length in mm
        loop_hole: loop hole diameter in mm
        loop_angle: loop rotation angle
        loop_enabled: whether loop is enabled
        color_conf: color configuration dict
        bed_label: BedManager label. Falls back to default.
        target_width_mm: Physical width of the model in mm.
        is_dark: True for dark PEI theme, False for light marble theme.

    Returns:
        (H, W, 4) RGBA numpy array of the rendered canvas
    """
    if bed_label is None:
        bed_label = BedManager.DEFAULT_BED
    bed_w_mm, bed_h_mm = BedManager.get_bed_size(bed_label)
    ppm = BedManager.compute_scale(bed_w_mm, bed_h_mm)

    canvas_w = int(bed_w_mm * ppm)
    canvas_h = int(bed_h_mm * ppm)
    margin = int(30 * ppm / 3)

    total_w = canvas_w + margin
    total_h = canvas_h + margin

    # Theme colors
    if is_dark:
        canvas_bg = (38, 38, 44, 255)
        bed_bg = (58, 58, 66, 255)
        grid_fine = (52, 52, 58, 255)
        grid_bold = (72, 72, 80, 255)
        border_color = (45, 45, 52, 255)
        axis_color = (90, 90, 110, 255)
        label_color = (140, 140, 170, 255)
    else:
        canvas_bg = (215, 215, 220, 255)
        bed_bg = (242, 242, 245, 255)
        grid_fine = (225, 225, 230, 255)
        grid_bold = (180, 180, 190, 255)
        border_color = (195, 195, 205, 255)
        axis_color = (100, 100, 120, 255)
        label_color = (80, 80, 100, 255)

    canvas = Image.new('RGBA', (total_w, total_h), canvas_bg)
    draw = ImageDraw.Draw(canvas)

    # Rounded bed area
    corner_r = 12
    draw.rounded_rectangle(
        [margin, 0, total_w - 1, canvas_h - 1],
        radius=corner_r, fill=bed_bg
    )

    # --- grid lines ---
    step_10 = max(1, int(10 * ppm))
    step_50 = max(1, int(50 * ppm))

    for x in range(margin, total_w, step_10):
        draw.line([(x, 0), (x, canvas_h)], fill=grid_fine, width=1)
    for y in range(0, canvas_h, step_10):
        draw.line([(margin, y), (total_w, y)], fill=grid_fine, width=1)

    for x in range(margin, total_w, step_50):
        draw.line([(x, 0), (x, canvas_h)], fill=grid_bold, width=2)
    for y in range(0, canvas_h, step_50):
        draw.line([(margin, y), (total_w, y)], fill=grid_bold, width=2)

    # Rounded border on top of grid
    draw.rounded_rectangle(
        [margin, 0, total_w - 1, canvas_h - 1],
        radius=corner_r, outline=border_color, width=2
    )

    # axes
    draw.line([(margin, 0), (margin, canvas_h)], fill=axis_color, width=2)
    draw.line([(margin, canvas_h - 1), (total_w, canvas_h - 1)], fill=axis_color, width=2)

    # labels (mm)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    for mm in range(0, bed_w_mm + 1, 50):
        px = margin + int(mm * ppm)
        if px < total_w and font:
            draw.text((px - 5, canvas_h + 2), f"{mm}", fill=label_color, font=font)

    for mm in range(0, bed_h_mm + 1, 50):
        px = canvas_h - int(mm * ppm)
        if px >= 0 and font:
            draw.text((2, px - 5), f"{mm}", fill=label_color, font=font)

    # --- paste model centred on bed ---
    if preview_rgba is not None:
        h, w = preview_rgba.shape[:2]
        if target_width_mm is not None and target_width_mm > 0:
            model_w_mm = target_width_mm
            model_h_mm = target_width_mm * h / w
        else:
            model_w_mm = w * PrinterConfig.NOZZLE_WIDTH
            model_h_mm = h * PrinterConfig.NOZZLE_WIDTH

        new_w = max(1, int(model_w_mm * ppm))
        new_h = max(1, int(model_h_mm * ppm))

        pil_img = Image.fromarray(preview_rgba, mode='RGBA')
        pil_img = pil_img.resize((new_w, new_h), Image.Resampling.NEAREST)

        offset_x = margin + (canvas_w - new_w) // 2
        offset_y = (canvas_h - new_h) // 2
        canvas.paste(pil_img, (offset_x, offset_y), pil_img)

        # --- loop overlay ---
        if loop_enabled and loop_pos is not None:
            mm_per_px = model_w_mm / w if w > 0 else PrinterConfig.NOZZLE_WIDTH
            canvas = _draw_loop_on_canvas(
                canvas, loop_pos, loop_width, loop_length,
                loop_hole, loop_angle, color_conf, margin,
                ppm=ppm, img_offset=(offset_x, offset_y),
                mm_per_px=mm_per_px
            )

    return np.array(canvas)


def _draw_loop_on_canvas(pil_img, loop_pos, loop_width, loop_length,
                         loop_hole, loop_angle, color_conf, margin,
                         ppm=None, img_offset=None, mm_per_px=None):
    """Draw keychain loop marker on canvas.

    Args:
        pil_img: PIL Image canvas
        loop_pos: (x, y) loop position
        loop_width/loop_length/loop_hole: loop dimensions in mm
        loop_angle: rotation angle
        color_conf: color configuration
        margin: left margin pixels
        ppm: pixels-per-mm
        img_offset: (x, y) pixel offset where model was pasted
        mm_per_px: mm per original image pixel
    """
    if ppm is None:
        ppm = 3.0
    if img_offset is None:
        img_offset = (margin, 0)
    if mm_per_px is None:
        mm_per_px = PrinterConfig.NOZZLE_WIDTH

    loop_w_px = int(loop_width * ppm)
    loop_h_px = int(loop_length * ppm)
    hole_r_px = int(loop_hole / 2 * ppm)
    circle_r_px = loop_w_px // 2

    cx = img_offset[0] + int(loop_pos[0] * mm_per_px * ppm)
    cy = img_offset[1] + int(loop_pos[1] * mm_per_px * ppm)

    loop_size = max(loop_w_px, loop_h_px) * 2 + 20
    loop_layer = Image.new('RGBA', (loop_size, loop_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(loop_layer)

    lc = loop_size // 2
    rect_h = max(1, loop_h_px - circle_r_px)

    loop_color = (220, 60, 60, 200)
    outline_color = (255, 255, 255, 255)

    draw.rectangle(
        [lc - loop_w_px//2, lc, lc + loop_w_px//2, lc + rect_h],
        fill=loop_color, outline=outline_color, width=2
    )

    draw.ellipse(
        [lc - circle_r_px, lc - circle_r_px,
         lc + circle_r_px, lc + circle_r_px],
        fill=loop_color, outline=outline_color, width=2
    )

    draw.ellipse(
        [lc - hole_r_px, lc - hole_r_px,
         lc + hole_r_px, lc + hole_r_px],
        fill=(0, 0, 0, 0)
    )

    if loop_angle != 0:
        loop_layer = loop_layer.rotate(
            -loop_angle, center=(lc, lc),
            expand=False, resample=Image.BICUBIC
        )

    paste_x = cx - lc
    paste_y = cy - lc - rect_h // 2
    pil_img.paste(loop_layer, (paste_x, paste_y), loop_layer)

    return pil_img
