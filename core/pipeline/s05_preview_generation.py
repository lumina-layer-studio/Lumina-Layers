"""
S05 — 2D preview image generation with keychain loop drawing.
S05 — 2D 预览图生成与挂件环绘制。

从 converter.py 搬入的预览生成逻辑和挂件环辅助函数：
- _calculate_loop_position: 根据预设计算挂件环位置
- _calculate_loop_info: 计算挂件环完整信息
- _draw_loop_on_preview: 在预览图上绘制挂件环
"""

import time
import numpy as np
from PIL import Image
from typing import Optional, Dict, Tuple

from api.structured_logging import get_logger
from core.geometry_utils import (
    keychain_loop_hole_clearance,
    keychain_loop_footprint,
    resolve_keychain_attachment,
)
from core.pipeline.p06_bed_rendering import draw_keychain_footprint
from core.pipeline.preview_color_utils import (
    build_material_preview_warning_extra,
    resolve_material_preview,
)

_log = get_logger(__name__)


def _top_edge_range_for_contact_band(
    mask_solid: np.ndarray,
    center_x_mm: float,
    contact_width_mm: float,
    target_h: int,
    pixel_scale: float,
) -> tuple[float, float] | None:
    """Return the lowest and highest solid top edge under a loop contact band.
    返回挂环水平接触带下方实体上边缘的最低点和最高点。
    """
    if pixel_scale <= 0 or contact_width_mm <= 0:
        return None

    half_width = contact_width_mm / 2.0
    min_col = max(0, int(np.floor((center_x_mm - half_width) / pixel_scale)))
    max_col = min(
        mask_solid.shape[1] - 1,
        int(np.ceil((center_x_mm + half_width) / pixel_scale) - 1),
    )
    if min_col > max_col:
        return None

    band = mask_solid[:, min_col:max_col + 1]
    solid_columns = np.any(band, axis=0)
    if not np.any(solid_columns):
        return None

    top_rows = np.argmax(band, axis=0)[solid_columns]
    # A solid pixel row occupies one full cell, so the outward cell edge is
    # one pixel above the row's lower Y coordinate.
    lowest_top = (target_h - int(np.max(top_rows))) * pixel_scale
    highest_top = (target_h - int(np.min(top_rows))) * pixel_scale
    return lowest_top, highest_top


def _calculate_loop_position(
    position_preset: str,
    offset_x: float,
    offset_y: float,
    mask_solid: np.ndarray,
    target_w: int,
    target_h: int,
    pixel_scale: float,
    contact_width_mm: float = 0.0,
    hole_clearance_mm: float = float("inf"),
) -> tuple:
    """Calculate keychain loop attach position based on preset and offset.
    根据位置预设和偏移量计算钥匙扣挂孔的吸附位置。

    Use the outside edges of occupied cells in artwork millimetres. The
    selected contour and joint inset are independent of the rotation angle.

    Args:
        position_preset (str): Preset name for snap position.
            (预设位置名称，如 'top-center', 'top-left' 等)
        offset_x (float): X offset in mm to add to the base position.
            (叠加到基准位置的 X 偏移量，单位 mm)
        offset_y (float): Y offset in mm. Inward movement is constrained when
            local contact anchoring is active. (Y 偏移量；局部接触锚定启用时限制向内移动)
        mask_solid (np.ndarray): Boolean 2D array (H, W) indicating solid pixels.
            (布尔二维数组，标识实体像素)
        target_w (int): Image width in pixels. (图像宽度，像素)
        target_h (int): Image height in pixels. (图像高度，像素)
        pixel_scale (float): mm per pixel conversion factor. (像素到 mm 的缩放因子)
        contact_width_mm (float): Width of the contact band. Zero uses the
            preset on the bounds directly. (接触带宽度；0 时使用包围盒位置)
        hole_clearance_mm (float): Maximum depth the loop may sink below the
            highest contour point before its hole meets the body.
            (挂孔压入本体前，挂环相对轮廓最高点可下沉的最大深度)

    Returns:
        tuple[float, float]: (attach_x_mm, attach_y_mm) position in mm.
            (吸附点坐标，单位 mm)
    """
    # Extract model bounds from mask_solid
    solid_rows = np.any(mask_solid, axis=1)
    solid_cols = np.any(mask_solid, axis=0)

    if not np.any(solid_rows) or not np.any(solid_cols):
        # No solid pixels — return model center as fallback
        center_x_mm = (target_w / 2.0) * pixel_scale
        center_y_mm = (target_h / 2.0) * pixel_scale
        return (center_x_mm + offset_x, center_y_mm + offset_y)

    row_indices = np.where(solid_rows)[0]
    col_indices = np.where(solid_cols)[0]

    min_row = int(row_indices[0])
    max_row = int(row_indices[-1])
    min_col = int(col_indices[0])
    max_col = int(col_indices[-1])

    bounds = (
        min_col * pixel_scale,
        (target_h - 1 - max_row) * pixel_scale,
        (max_col + 1) * pixel_scale,
        (target_h - min_row) * pixel_scale,
    )

    def contact_range(axis: int, sign: int, tangent: float, width: float) -> tuple[float, float] | None:
        # In this view, columns grow along the contact band and rows start at
        # the outward edge. A reversed normal has a negative world origin.
        cells = mask_solid[::-1]
        if axis == 1:
            cells = cells.T
        if sign > 0:
            cells = cells[::-1]
        top = _top_edge_range_for_contact_band(cells, tangent, width, cells.shape[0], pixel_scale)
        if top is None or sign > 0:
            return top
        origin = -cells.shape[0] * pixel_scale
        return top[0] + origin, top[1] + origin

    return resolve_keychain_attachment(
        bounds, position_preset or "top-center", offset_x, offset_y,
        contact_width_mm, hole_clearance_mm, contact_range,
    )


def _calculate_loop_info(
    loop_pos: Optional[Tuple[float, float]],
    loop_width: float,
    loop_length: float,
    loop_hole: float,
    mask_solid: np.ndarray,
    material_matrix: np.ndarray,
    target_w: int,
    target_h: int,
    pixel_scale: float,
    angle_deg: float = 0.0,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    position_preset: str = "top-center",
) -> Optional[Dict]:
    """Calculate keychain loop information including position and angle.
    计算钥匙扣挂孔信息，包括位置和旋转角度。

    When loop_pos is provided, snaps to the nearest solid pixel from the
    click point. When loop_pos is None, delegates to _calculate_loop_position()
    to compute a default position based on the preset and offset.
    当 loop_pos 有值时，吸附到点击点最近的实体像素；当 loop_pos 为 None 时，
    委托 _calculate_loop_position() 根据预设和偏移计算默认位置。

    Args:
        loop_pos (Optional[Tuple[float, float]]): Click position (x, y) in pixels,
            or None to use preset-based calculation. (点击位置像素坐标，None 则使用预设计算)
        loop_width (float): Loop width in mm. (环宽度，mm)
        loop_length (float): Loop length in mm. (环长度，mm)
        loop_hole (float): Hole diameter in mm. (孔径，mm)
        mask_solid (np.ndarray): Boolean 2D array (H, W) of solid pixels. (实体像素掩码)
        material_matrix (np.ndarray): Material assignment matrix. (材料分配矩阵)
        target_w (int): Image width in pixels. (图像宽度，像素)
        target_h (int): Image height in pixels. (图像高度，像素)
        pixel_scale (float): mm per pixel. (像素到 mm 缩放因子)
        angle_deg (float): Rotation angle in degrees, default 0. (旋转角度，度，默认 0)
        offset_x (float): X offset in mm, default 0. (X 偏移量，mm，默认 0)
        offset_y (float): Y offset in mm, default 0. (Y 偏移量，mm，默认 0)
        position_preset (str): Position preset name, default "top-center".
            (位置预设名称，默认 "top-center")

    Returns:
        Optional[Dict]: Loop info dict with keys attach_x_mm, attach_y_mm,
            width_mm, length_mm, hole_dia_mm, color_id, angle_deg; or None
            if no solid pixels exist. (挂孔信息字典，或 None)
    """
    solid_rows = np.any(mask_solid, axis=1)
    if not np.any(solid_rows):
        return None

    if loop_pos is not None:
        # Original click-based position logic
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

        attach_x_mm = attach_col * pixel_scale
        attach_y_mm = (target_h - 1 - top_row) * pixel_scale
    else:
        # Preset-based position calculation
        attach_x_mm, attach_y_mm = _calculate_loop_position(
            position_preset=position_preset,
            offset_x=offset_x,
            offset_y=offset_y,
            mask_solid=mask_solid,
            target_w=target_w,
            target_h=target_h,
            pixel_scale=pixel_scale,
            contact_width_mm=loop_width,
            hole_clearance_mm=keychain_loop_hole_clearance(
                loop_width, loop_length, loop_hole
            ),
        )
        # Convert mm back to pixel coords for color sampling
        attach_col = int(attach_x_mm / pixel_scale) if pixel_scale > 0 else target_w // 2
        attach_col = max(0, min(target_w - 1, attach_col))
        top_row_mm = attach_y_mm / pixel_scale if pixel_scale > 0 else 0
        top_row = int(target_h - 1 - top_row_mm)
        top_row = max(0, min(target_h - 1, top_row))

    # Determine loop color from nearby material
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
        'attach_x_mm': attach_x_mm,
        'attach_y_mm': attach_y_mm,
        'width_mm': loop_width,
        'length_mm': loop_length,
        'hole_dia_mm': loop_hole,
        'color_id': loop_color_id,
        'angle_deg': angle_deg,
    }


def _draw_loop_on_preview(preview_rgba, loop_info, color_conf, pixel_scale):
    """Draw keychain loop on preview image.
    在预览图上绘制挂件环。

    Args:
        preview_rgba (np.ndarray): (H, W, 4) uint8 RGBA 预览图
        loop_info (dict): 挂件环信息字典
        color_conf (dict): 颜色系统配置
        pixel_scale (float): mm/px 缩放因子

    Returns:
        np.ndarray: 绘制挂件环后的 RGBA 预览图
    """
    preview_pil = Image.fromarray(preview_rgba, mode='RGBA')

    resolved_rgba = loop_info.get("color_rgba")
    if resolved_rgba is None:
        compatibility_resolution = resolve_material_preview(
            material_id=loop_info["color_id"],
            slot_names=color_conf.get("slots"),
            preview_colors=color_conf.get("preview"),
            color_conf=color_conf,
        )
        if not compatibility_resolution.is_resolved:
            raise ValueError(
                "Loop material preview color is unavailable for drawing"
            )
        resolved_rgba = compatibility_resolution.rgba
    loop_color_rgba = tuple(resolved_rgba)

    profile = keychain_loop_footprint(
        loop_info["width_mm"], loop_info["length_mm"], loop_info["hole_dia_mm"],
        loop_info["attach_x_mm"], loop_info["attach_y_mm"], loop_info.get("angle_deg", 0.0),
    )
    draw_keychain_footprint(preview_pil, profile, (0, preview_pil.height), 1 / pixel_scale, loop_color_rgba)

    return np.array(preview_pil)


def run(ctx: dict) -> dict:
    """Generate 2D preview image and optionally draw keychain loop.
    生成 2D 预览图，可选绘制挂件环。

    PipelineContext 输入键 / Input keys:
        - matched_rgb (np.ndarray): (H, W, 3) uint8 匹配后的 RGB
        - mask_solid (np.ndarray): (H, W) bool 实体掩码
        - target_w (int): 目标宽度 (像素)
        - target_h (int): 目标高度 (像素)
        - pixel_scale (float): mm/px 缩放因子
        - add_loop (bool): 是否添加挂件环
        - loop_pos (tuple | None): 挂件环点击位置
        - loop_width (float): 环宽度 (mm)
        - loop_length (float): 环长度 (mm)
        - loop_hole (float): 孔径 (mm)
        - loop_angle (float): 旋转角度 (度)
        - loop_offset_x (float): X 偏移 (mm)
        - loop_offset_y (float): Y 偏移 (mm)
        - loop_position_preset (str | None): 位置预设
        - material_matrix (np.ndarray): 材料矩阵
        - color_conf (dict): 颜色系统配置
        - slot_names (list[str]): 与材料 ID 对齐的权威材料名称
        - preview_colors (dict): 与材料 ID 对齐的权威预览颜色

    PipelineContext 输出键 / Output keys:
        - preview_rgba (np.ndarray): (H, W, 4) uint8 RGBA 预览图
        - preview_img (PIL.Image): PIL RGBA 预览图像
        - loop_info (dict | None): 挂件环信息
    """
    _t0 = time.perf_counter()

    matched_rgb = ctx['matched_rgb']
    mask_solid = ctx['mask_solid']
    target_w = ctx['target_w']
    target_h = ctx['target_h']
    pixel_scale = ctx['pixel_scale']
    color_conf = ctx['color_conf']

    # Build preview RGBA
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    preview_rgba[mask_solid, 3] = 255

    # Handle keychain loop
    loop_info = None
    add_loop = ctx.get('add_loop', False)
    if add_loop:
        loop_info = _calculate_loop_info(
            ctx.get('loop_pos'),
            ctx.get('loop_width', 5.0),
            ctx.get('loop_length', 10.0),
            ctx.get('loop_hole', 3.0),
            mask_solid,
            ctx['material_matrix'],
            target_w, target_h, pixel_scale,
            angle_deg=ctx.get('loop_angle', 0.0),
            offset_x=ctx.get('loop_offset_x', 0.0),
            offset_y=ctx.get('loop_offset_y', 0.0),
            position_preset=ctx.get('loop_position_preset') or "top-center",
        )

        if loop_info:
            slot_names = ctx.get("slot_names")
            preview_colors = ctx.get("preview_colors")
            resolution = resolve_material_preview(
                material_id=loop_info["color_id"],
                slot_names=slot_names,
                preview_colors=preview_colors,
                color_conf=color_conf,
            )
            if not resolution.is_resolved:
                _log.warning(
                    "Loop material preview metadata is unresolved",
                    extra=build_material_preview_warning_extra(
                        resolution,
                        slot_names=slot_names,
                        preview_colors=preview_colors,
                        color_conf=color_conf,
                        material_source=ctx.get("material_source", "lut"),
                    ),
                )
                raise ValueError(
                    "Loop material identity or preview color is unavailable"
                )
            loop_info["material_name"] = resolution.material_name
            loop_info["color_rgba"] = list(resolution.rgba)
            loop_info["color_source"] = resolution.source
            preview_rgba = _draw_loop_on_preview(
                preview_rgba, loop_info, color_conf, pixel_scale
            )

    preview_img = Image.fromarray(preview_rgba, mode='RGBA')

    ctx['preview_rgba'] = preview_rgba
    ctx['preview_img'] = preview_img
    ctx['loop_info'] = loop_info

    _elapsed = time.perf_counter() - _t0
    _hifi_timings = ctx.get('_hifi_timings', {})
    _hifi_timings['preview_gen_s'] = _elapsed
    ctx['_hifi_timings'] = _hifi_timings
    _log.debug(
        "preview_gen done: %.3fs",
        _elapsed,
        extra={
            "event": "s05_preview_gen_done",
            "duration_ms": round(_elapsed * 1000, 3),
            "width": int(target_w),
            "height": int(target_h),
            "loop_enabled": bool(add_loop),
            "loop_added": loop_info is not None,
        },
    )
    return ctx
