"""
P06 — Bed grid rendering and final preview output.
P06 — 热床网格渲染与最终预览输出。

从 converter.py 搬入的函数：
- render_preview: 在热床网格上渲染预览图像（含挂件环叠加）
- _draw_loop_on_canvas: 在画布上绘制挂件环标记
- _create_bed_mesh: 创建圆角打印热床 3D 网格（带 UV 贴图纹理）
"""

import time
import cv2
import numpy as np
import trimesh
from PIL import Image, ImageDraw

from core.preview_sizing import preview_dimensions
from api.structured_logging import get_logger
from config import PrinterConfig, BedManager, PREVIEW_SCALE

_log = get_logger(__name__)


def compute_bed_model_rect(
    raw_h: int,
    raw_w: int,
    target_width_mm: float | None = None,
    bed_label: str | None = None,
) -> dict[str, int]:
    """Compute the model's pixel bounding box within a bed-rendered canvas.
    计算模型在热床渲染画布中的像素边界框。

    Returns the same placement that ``render_preview`` would use, so the
    frontend can map between raw-image pixel coordinates and bed-canvas
    pixel coordinates for contour overlays and click handling.

    Args:
        raw_h: Raw image height in pixels (matched_rgb rows).
        raw_w: Raw image width in pixels (matched_rgb cols).
        target_width_mm: Physical model width in mm.
        bed_label: BedManager label; defaults to DEFAULT_BED.

    Returns:
        Dict with keys bed_total_w, bed_total_h, model_x, model_y,
        model_w, model_h (all int, pixels).
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

    if target_width_mm is not None and target_width_mm > 0:
        model_w_mm = target_width_mm
        model_h_mm = target_width_mm * raw_h / raw_w
    else:
        model_w_mm = raw_w * PrinterConfig.NOZZLE_WIDTH
        model_h_mm = raw_h * PrinterConfig.NOZZLE_WIDTH

    new_w = max(1, int(model_w_mm * ppm))
    new_h = max(1, int(model_h_mm * ppm))

    offset_x = margin + (canvas_w - new_w) // 2
    offset_y = (canvas_h - new_h) // 2

    return {
        "bed_total_w": total_w,
        "bed_total_h": total_h,
        "model_x": offset_x,
        "model_y": offset_y,
        "model_w": new_w,
        "model_h": new_h,
    }


def render_preview(preview_rgba, loop_pos, loop_width, loop_length,
                   loop_hole, loop_angle, loop_enabled, color_conf,
                   bed_label=None, target_width_mm=None, is_dark=True):
    """Return a bounded display image with optional keychain loop overlay.
    返回有尺寸上限的显示图像，可选叠加挂件环标记。

    The bed canvas / grid / rulers were intentionally dropped per UX
    request — the 2D preview now contains only the model image itself.
    Screen dimensions use the shared preview budget; the caller retains
    the full ``preview_rgba`` grid for model generation and pixel editing.

    按 UX 要求移除了热床底板 / 网格 / 标尺，2D 预览仅输出模型本身；
    显示图像使用统一尺寸上限，调用方保留完整 ``preview_rgba`` 网格用于
    建模与像素编辑。

    Args:
        preview_rgba (np.ndarray | None): RGBA 预览图像 (H, W, 4)
        loop_pos (tuple | None): 挂件环位置 (x, y)，原始图像像素坐标
        loop_width (float): 挂件环宽度（mm）
        loop_length (float): 挂件环长度（mm）
        loop_hole (float): 挂件环孔径（mm）
        loop_angle (float): 挂件环旋转角度（度）
        loop_enabled (bool): 是否启用挂件环
        color_conf (dict): 颜色系统配置（保留以兼容现有调用方）
        bed_label (str | None): 保留参数，仅用于计算物理尺寸回退
        target_width_mm (float | None): 模型物理宽度（mm），None 时按喷嘴宽度估算
        is_dark (bool): 保留参数，当前无效果

    Returns:
        np.ndarray: RGBA 预览图像数组；无输入时返回 1x1 透明占位
    """
    del color_conf, bed_label, is_dark  # kept for backward-compat signatures

    if preview_rgba is None:
        return np.zeros((1, 1, 4), dtype=np.uint8)

    h, w = preview_rgba.shape[:2]

    if target_width_mm is not None and target_width_mm > 0 and w > 0:
        model_w_mm = float(target_width_mm)
    else:
        model_w_mm = w * PrinterConfig.NOZZLE_WIDTH

    display_w, display_h = preview_dimensions(w, h)
    display_rgba = preview_rgba
    if (display_w, display_h) != (w, h):
        # Resize before creating a display copy of the modeling grid. Nearest
        # keeps palette colors and alpha exact, including pixel-art previews.
        display_rgba = cv2.resize(
            preview_rgba, (display_w, display_h), interpolation=cv2.INTER_NEAREST,
        )
    pil_img = Image.fromarray(display_rgba, mode='RGBA').copy()

    if loop_enabled and loop_pos is not None and w > 0 and model_w_mm > 0:
        mm_per_px = model_w_mm / display_w
        ppm_display = 1.0 / mm_per_px
        display_loop_pos = (
            loop_pos[0] * display_w / w,
            loop_pos[1] * display_h / h,
        )
        pil_img = _draw_loop_on_canvas(
            pil_img, display_loop_pos, loop_width, loop_length,
            loop_hole, loop_angle, None, 0,
            ppm=ppm_display, img_offset=(0, 0),
            mm_per_px=mm_per_px,
        )

    return np.array(pil_img)


def _draw_loop_on_canvas(pil_img, loop_pos, loop_width, loop_length,
                         loop_hole, loop_angle, color_conf, margin,
                         ppm=None, img_offset=None, mm_per_px=None):
    """Draw keychain loop marker on canvas.
    在画布上绘制挂件环标记。

    Args:
        pil_img (Image): PIL RGBA 画布图像
        loop_pos (tuple): 挂件环位置 (x, y)，原始图像像素坐标
        loop_width (float): 挂件环宽度（mm）
        loop_length (float): 挂件环长度（mm）
        loop_hole (float): 挂件环孔径（mm）
        loop_angle (float): 挂件环旋转角度（度）
        color_conf (dict): 颜色系统配置
        margin (int): 画布左侧边距（像素）
        ppm (float | None): pixels-per-mm，None 时回退到 legacy PREVIEW_SCALE
        img_offset (tuple | None): (x, y) 模型图像粘贴偏移量（像素）
        mm_per_px (float | None): 每原始图像像素对应的毫米数

    Returns:
        Image: 绘制了挂件环标记的 PIL 画布图像
    """
    if ppm is None:
        ppm = PREVIEW_SCALE / PrinterConfig.NOZZLE_WIDTH
    if img_offset is None:
        img_offset = (margin, 0)
    if mm_per_px is None:
        mm_per_px = PrinterConfig.NOZZLE_WIDTH

    loop_w_px = int(loop_width * ppm)
    loop_h_px = int(loop_length * ppm)
    hole_r_px = int(loop_hole / 2 * ppm)
    circle_r_px = loop_w_px // 2

    # loop_pos is in original image pixel coords
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
        [lc - loop_w_px // 2, lc, lc + loop_w_px // 2, lc + rect_h],
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


def _create_bed_mesh(bed_w_mm, bed_h_mm, is_dark=True):
    """Create a rounded-corner print bed mesh with UV-mapped texture.
    创建圆角打印热床网格，带 UV 贴图纹理。

    The geometry outline matches the texture's rounded rectangle so that
    no sharp-corner artifacts remain visible in the 3D preview.
    几何轮廓与纹理的圆角矩形一致，避免 3D 预览中出现直角残留。

    Args:
        bed_w_mm (int): Bed width in mm. (热床宽度 mm)
        bed_h_mm (int): Bed height in mm. (热床高度 mm)
        is_dark (bool): Use dark PEI theme. (使用深色 PEI 主题)

    Returns:
        trimesh.Trimesh: Textured bed mesh, or None on error. (带纹理的热床网格)
    """
    try:
        from PIL import Image as PILImage, ImageDraw as PILDraw
        from mapbox_earcut import triangulate_float64

        tex_scale = 4  # pixels per mm
        tex_w = int(bed_w_mm * tex_scale)
        tex_h = int(bed_h_mm * tex_scale)
        corner_r = int(8 * tex_scale)
        margin = max(2, corner_r // 4)

        # Corner radius in world mm (matches texture margin/radius ratio)
        r_mm = margin / tex_scale + corner_r / tex_scale

        if is_dark:
            base_color = (58, 58, 66)
            fine_color = (42, 42, 48)
            bold_color = (90, 90, 100)
            border_color = (45, 45, 52)
        else:
            base_color = (242, 242, 245)
            fine_color = (225, 225, 230)
            bold_color = (180, 180, 190)
            border_color = (195, 195, 205)

        # --- Texture (fill entire image with base_color, no edge_color needed) ---
        img = PILImage.new('RGB', (tex_w, tex_h), base_color)
        draw = PILDraw.Draw(img)

        step_10 = int(10 * tex_scale)
        for x in range(0, tex_w, step_10):
            draw.line([(x, 0), (x, tex_h)], fill=fine_color, width=1)
        for y in range(0, tex_h, step_10):
            draw.line([(0, y), (tex_w, y)], fill=fine_color, width=1)

        step_50 = int(50 * tex_scale)
        for x in range(0, tex_w, step_50):
            draw.line([(x, 0), (x, tex_h)], fill=bold_color, width=3)
        for y in range(0, tex_h, step_50):
            draw.line([(0, y), (tex_w, y)], fill=bold_color, width=3)

        draw.rounded_rectangle(
            [margin, margin, tex_w - margin, tex_h - margin],
            radius=corner_r, outline=border_color, width=3
        )

        # --- Rounded-rectangle geometry outline (world coords, mm) ---
        arc_segs = 16
        angles = np.linspace(0, np.pi / 2, arc_segs + 1)
        cos_a = np.cos(angles)
        sin_a = np.sin(angles)

        outline_pts = []
        # Bottom-left corner (origin side)
        for i in range(arc_segs + 1):
            outline_pts.append([r_mm - r_mm * cos_a[i], r_mm - r_mm * sin_a[i]])
        # Bottom-right corner
        for i in range(arc_segs + 1):
            outline_pts.append([bed_w_mm - r_mm + r_mm * sin_a[i], r_mm - r_mm * cos_a[i]])
        # Top-right corner
        for i in range(arc_segs + 1):
            outline_pts.append([bed_w_mm - r_mm + r_mm * cos_a[i], bed_h_mm - r_mm + r_mm * sin_a[i]])
        # Top-left corner
        for i in range(arc_segs + 1):
            outline_pts.append([r_mm - r_mm * sin_a[i], bed_h_mm - r_mm + r_mm * cos_a[i]])

        outline_pts = np.array(outline_pts, dtype=np.float64)

        # Triangulate the rounded-rect polygon via mapbox-earcut
        rings = np.array([len(outline_pts)], dtype=np.int32)
        tri_flat = triangulate_float64(outline_pts, rings)
        tri_indices = np.array(tri_flat, dtype=np.int64).reshape(-1, 3)

        # Build 3D vertices (Z=0) and UV coords
        n_pts = len(outline_pts)
        verts_3d = np.zeros((n_pts, 3), dtype=np.float64)
        verts_3d[:, 0] = outline_pts[:, 0]
        verts_3d[:, 1] = outline_pts[:, 1]

        uv = np.zeros((n_pts, 2), dtype=np.float64)
        uv[:, 0] = outline_pts[:, 0] / bed_w_mm
        uv[:, 1] = 1.0 - outline_pts[:, 1] / bed_h_mm

        from trimesh.visual.material import SimpleMaterial
        from trimesh.visual import TextureVisuals

        mesh = trimesh.Trimesh(vertices=verts_3d, faces=tri_indices, process=False)
        mesh.visual = TextureVisuals(uv=uv, material=SimpleMaterial(image=img))

        theme_name = "dark" if is_dark else "light"
        _log.debug(
            "Created %s %sx%smm rounded bed (%s verts)",
            theme_name,
            bed_w_mm,
            bed_h_mm,
            n_pts,
            extra={
                "event": "bed_mesh_created",
                "width_mm": float(bed_w_mm),
                "height_mm": float(bed_h_mm),
                "theme": theme_name,
                "vertex_count": int(n_pts),
            },
        )
        return mesh

    except Exception as e:
        _log.exception(
            "Failed to create bed mesh: %s",
            e,
            extra={
                "event": "bed_mesh_create_failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
                "width_mm": float(bed_w_mm),
                "height_mm": float(bed_h_mm),
            },
        )
        return None


def run(ctx: dict) -> dict:
    """Render preview on bed grid and produce final display image.
    在热床网格上渲染预览并生成最终显示图像。

    PipelineContext 输入键 / Input keys:
        - preview_rgba (np.ndarray): RGBA 预览图像 (H, W, 4)
        - cache (dict): 预览缓存字典（包含 color_palette）
        - color_conf (dict): 颜色系统配置
        - target_width_mm (float): 目标宽度（毫米）
        - is_dark (bool): 是否深色主题

    PipelineContext 输出键 / Output keys:
        - display_image (np.ndarray): 最终显示图像数组
        - status_msg (str): 状态消息

    Raises:
        KeyError: 缺少必需的输入键时抛出
    """
    # ---- 读取必需输入 ----
    _t0 = time.perf_counter()
    preview_rgba = ctx['preview_rgba']
    cache = ctx['cache']
    color_conf = ctx['color_conf']
    target_width_mm = ctx['target_width_mm']
    is_dark = ctx.get('is_dark', True)

    # ---- 渲染预览 ----
    display = render_preview(
        preview_rgba, None, 0, 0, 0, 0, False, color_conf,
        target_width_mm=target_width_mm, is_dark=is_dark
    )

    # ---- 构建状态消息 ----
    target_w = cache.get('target_w', 0)
    target_h = cache.get('target_h', 0)
    color_palette = cache.get('color_palette', [])
    num_colors = len(color_palette)
    status_msg = f"[OK] Preview ({target_w}x{target_h}px, {num_colors} colors) | Click image to place loop"

    # ---- 写入输出 ----
    ctx['display_image'] = display
    ctx['status_msg'] = status_msg
    _elapsed = time.perf_counter() - _t0
    ctx.setdefault('_preview_timings', {})['p06_s'] = _elapsed
    _log.debug(
        "bed_rendering done: %.3fs",
        _elapsed,
        extra={
            "event": "p06_bed_rendering_done",
            "duration_ms": round(_elapsed * 1000, 3),
            "width": int(target_w),
            "height": int(target_h),
            "count": int(num_colors),
        },
    )
    return ctx
