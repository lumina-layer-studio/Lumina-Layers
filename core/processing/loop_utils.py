# -*- coding: utf-8 -*-
"""挂件环工具模块

计算挂件环位置信息，以及在预览图上绘制挂件环。
"""

import numpy as np
from PIL import Image, ImageDraw


def calculate_loop_info(loop_pos, loop_width, loop_length, loop_hole,
                        mask_solid, material_matrix, target_w, target_h, pixel_scale):
    """Calculate keychain loop information.
    计算挂件环的位置和尺寸信息。

    Args:
        loop_pos: (x, y) click position
        loop_width: loop width in mm
        loop_length: loop length in mm
        loop_hole: loop hole diameter in mm
        mask_solid: (H, W) boolean mask
        material_matrix: (H, W, N) material matrix
        target_w: image width in pixels
        target_h: image height in pixels
        pixel_scale: mm per pixel

    Returns:
        dict with loop info or None
    """
    solid_rows = np.any(mask_solid, axis=1)
    if not np.any(solid_rows):
        return None

    click_x, click_y = loop_pos
    attach_col = int(click_x)
    attach_row = int(click_y)
    attach_col = max(0, min(target_w - 1, attach_col))
    attach_row = max(0, min(target_h - 1, attach_row))

    col_mask = mask_solid[:, attach_col]
    if np.any(col_mask):
        solid_rows_in_col = np.where(col_mask)[0]
        distances = np.abs(solid_rows_in_col - attach_row)
        nearest_idx = np.argmin(distances)
        top_row = solid_rows_in_col[nearest_idx]
    else:
        top_row = np.argmax(solid_rows)
        solid_cols_in_top = np.where(mask_solid[top_row])[0]
        if len(solid_cols_in_top) > 0:
            distances = np.abs(solid_cols_in_top - attach_col)
            nearest_idx = np.argmin(distances)
            attach_col = solid_cols_in_top[nearest_idx]
        else:
            attach_col = target_w // 2

    attach_col = max(0, min(target_w - 1, attach_col))

    loop_color_id = 0
    search_area = material_matrix[
        max(0, top_row-2):top_row+3,
        max(0, attach_col-3):attach_col+4
    ]
    search_area = search_area[search_area >= 0]
    if len(search_area) > 0:
        unique, counts = np.unique(search_area, return_counts=True)
        for mat_id in unique[np.argsort(-counts)]:
            if mat_id != 0:
                loop_color_id = int(mat_id)
                break

    return {
        'attach_x_mm': attach_col * pixel_scale,
        'attach_y_mm': (target_h - 1 - top_row) * pixel_scale,
        'width_mm': loop_width,
        'length_mm': loop_length,
        'hole_dia_mm': loop_hole,
        'color_id': loop_color_id
    }


def draw_loop_on_preview(preview_rgba, loop_info, color_conf, pixel_scale):
    """Draw keychain loop on preview image.
    在预览图上绘制挂件环。

    Args:
        preview_rgba: (H, W, 4) RGBA numpy array
        loop_info: dict from calculate_loop_info
        color_conf: color configuration with 'preview' key
        pixel_scale: mm per pixel

    Returns:
        (H, W, 4) RGBA numpy array with loop drawn
    """
    preview_pil = Image.fromarray(preview_rgba, mode='RGBA')
    draw = ImageDraw.Draw(preview_pil)

    loop_color_rgba = tuple(color_conf['preview'][loop_info['color_id']][:3]) + (255,)

    attach_col = int(loop_info['attach_x_mm'] / pixel_scale)
    attach_row = int((preview_rgba.shape[0] - 1) - loop_info['attach_y_mm'] / pixel_scale)

    loop_w_px = int(loop_info['width_mm'] / pixel_scale)
    loop_h_px = int(loop_info['length_mm'] / pixel_scale)
    hole_r_px = int(loop_info['hole_dia_mm'] / 2 / pixel_scale)
    circle_r_px = loop_w_px // 2

    loop_bottom = attach_row
    loop_left = attach_col - loop_w_px // 2
    loop_right = attach_col + loop_w_px // 2

    rect_h_px = loop_h_px - circle_r_px
    rect_bottom = loop_bottom
    rect_top = loop_bottom - rect_h_px

    circle_center_y = rect_top
    circle_center_x = attach_col

    if rect_h_px > 0:
        draw.rectangle(
            [loop_left, rect_top, loop_right, rect_bottom],
            fill=loop_color_rgba
        )

    draw.ellipse(
        [circle_center_x - circle_r_px, circle_center_y - circle_r_px,
         circle_center_x + circle_r_px, circle_center_y + circle_r_px],
        fill=loop_color_rgba
    )

    draw.ellipse(
        [circle_center_x - hole_r_px, circle_center_y - hole_r_px,
         circle_center_x + hole_r_px, circle_center_y + hole_r_px],
        fill=(0, 0, 0, 0)
    )

    return np.array(preview_pil)
