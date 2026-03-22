"""
SVG 双通道光栅化模块（SVG Rasterizer）

从 image_processing.py 的 _load_svg 方法搬入。
使用白底/黑底差分法检测透明度，保证内容零损伤。

SVG dual-pass rasterization using white/black background differencing.
Extracted from LuminaImageProcessor._load_svg.
"""

import os
import numpy as np
import cv2

# SVG support (optional dependency)
try:
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPM

    HAS_SVG = True
except ImportError:
    HAS_SVG = False

_SVG_RASTER_CACHE = {}
_SVG_RASTER_CACHE_MAX = 4


def _get_svg_pixel_dims(svg_path: str):
    """Parse SVG width/height in original pixel units from XML.
    解析 SVG 文件的原始像素尺寸。

    svglib converts px to pt (x0.75) internally, but path coordinates stay
    in original SVG user units. This helper reads the true pixel dimensions
    so we can correct the coordinate mismatch.

    Args:
        svg_path (str): Path to SVG file. (SVG 文件路径)

    Returns:
        tuple[float, float]: (width_px, height_px), or (0, 0) on failure.
            (原始像素尺寸，失败返回 (0, 0))
    """
    try:
        import xml.etree.ElementTree as ET

        tree = ET.parse(svg_path)
        root = tree.getroot()
        ns = root.tag.split("}")[0] + "}" if "}" in root.tag else ""
        actual_root = root if root.tag.endswith("svg") else root.find(f"{ns}svg") or root

        def strip_unit(s):
            if not s:
                return 0.0
            s = s.strip()
            for unit in ("px", "pt", "mm", "cm", "in"):
                if s.endswith(unit):
                    s = s[: -len(unit)].strip()
                    break
            try:
                return float(s)
            except (ValueError, TypeError):
                return 0.0

        w = strip_unit(actual_root.get("width", ""))
        h = strip_unit(actual_root.get("height", ""))
        if w > 0 and h > 0:
            return w, h
        vb = actual_root.get("viewBox", "")
        if vb:
            parts = vb.replace(",", " ").split()
            if len(parts) == 4:
                return float(parts[2]), float(parts[3])
    except Exception:
        pass
    return 0.0, 0.0


def rasterize_svg(svg_path: str, target_width_mm: float, pixels_per_mm: float = 20.0) -> np.ndarray:
    """SVG 双通道光栅化。
    Safe Padding + Dual-Pass Transparency Detection.

    Method: Render twice (White BG / Black BG).
    - If pixel changes color -> It's background (Transparent) -> Remove it.
    - If pixel stays same -> It's content (Opaque) -> Keep it 100% intact.

    This guarantees NO internal image damage.

    Args:
        svg_path: SVG 文件路径
        target_width_mm: 目标宽度（毫米）
        pixels_per_mm: 光栅化密度，20.0 用于最终输出，10.0 用于预览

    Returns:
        (H, W, 4) uint8 RGBA numpy 数组
    """
    if not HAS_SVG:
        raise ImportError("Please install 'svglib' and 'reportlab'.")

    cache_key = None
    try:
        svg_abs = os.path.abspath(svg_path)
        svg_mtime = os.path.getmtime(svg_abs)
        cache_key = (svg_abs, round(float(target_width_mm), 4), round(float(pixels_per_mm), 2), svg_mtime)
        cached = _SVG_RASTER_CACHE.get(cache_key)
        if cached is not None:
            print(f"[SVG] Cache hit: {os.path.basename(svg_abs)} @ {pixels_per_mm}px/mm")
            return cached.copy()
    except Exception:
        cache_key = None

    print(f"[SVG] Rasterizing: {svg_path}")

    # 1. 读取 SVG
    drawing = svg2rlg(svg_path)

    # --- Fix svglib px→pt coordinate mismatch ---
    # svglib converts SVG width/height from px to pt (×0.75) but keeps
    # path coordinates in original SVG user units. The internal Y-flip
    # transform also uses pt height. Fix both to use original px dims.
    svg_w, svg_h = _get_svg_pixel_dims(svg_path)
    if svg_w > 0 and svg_h > 0:
        main_group = drawing.contents[0]
        if hasattr(main_group, "transform") and main_group.transform:
            t = list(main_group.transform)
            if len(t) >= 6 and t[3] == -1:
                t[5] = svg_h
                main_group.transform = tuple(t)
        drawing.width = svg_w
        drawing.height = svg_h
        raw_w, raw_h = svg_w, svg_h
    else:
        raw_w, raw_h = float(drawing.width), float(drawing.height)
    if raw_w <= 0 or raw_h <= 0:
        raise ValueError(f"SVG has zero-size dimensions: {raw_w}x{raw_h}")
    print(f"[SVG] Canvas: {raw_w:.1f}x{raw_h:.1f}")

    # 2. 缩放到目标像素宽度（强制最低渲染质量保证 Dual-Pass 效果）
    target_width_px = int(target_width_mm * pixels_per_mm)
    MIN_QUALITY_PX = 800
    render_width_px = max(target_width_px, MIN_QUALITY_PX)

    if raw_w > 0:
        scale_factor = render_width_px / raw_w
    else:
        scale_factor = 1.0

    drawing.scale(scale_factor, scale_factor)
    render_w = max(1, int(raw_w * scale_factor))
    render_h = max(1, int(raw_h * scale_factor))
    drawing.width = render_w
    drawing.height = render_h

    # ================== 【终极方案】双重渲染差分法 ==================
    try:
        # Pass 1: 白底渲染 (0xFFFFFF)
        # 强制不使用透明通道，完全模拟打印在白纸上的效果
        pil_white = renderPM.drawToPIL(drawing, bg=0xFFFFFF, configPIL={"transparent": False})
        arr_white = np.array(pil_white.convert("RGB"))  # 丢弃 Alpha，只看颜色

        # Pass 2: 黑底渲染 (0x000000)
        # 强制不使用透明通道，完全模拟打印在黑纸上的效果
        pil_black = renderPM.drawToPIL(drawing, bg=0x000000, configPIL={"transparent": False})
        arr_black = np.array(pil_black.convert("RGB"))

        # 计算差异 (Difference)
        # diff = |白底图 - 黑底图|
        # 如果像素是实心的，它挡住了背景，所以在白底和黑底上颜色一样 -> diff 为 0
        # 如果像素是透明的，它透出了背景，所以在白底是白，黑底是黑 -> diff 很大
        diff = np.abs(arr_white.astype(int) - arr_black.astype(int))
        diff_sum = np.sum(diff, axis=2)

        # 生成 Alpha 掩膜（严格阈值，保证下游色彩精度）
        alpha_mask = np.where(diff_sum < 10, 255, 0).astype(np.uint8)

        # 合成最终图像
        r, g, b = cv2.split(arr_white)
        img_final = cv2.merge([r, g, b, alpha_mask])

        # ── Content-aware pixel crop ──────────────────────────────────
        # Use alpha mask to detect actual content bounds — more reliable
        # than getBounds() for strokes, nested transforms, and text.
        BORDER = 2
        h_arr, w_arr = img_final.shape[:2]
        content_rows = np.any(alpha_mask > 0, axis=1)
        content_cols = np.any(alpha_mask > 0, axis=0)
        if np.any(content_rows) and np.any(content_cols):
            row_idx = np.where(content_rows)[0]
            col_idx = np.where(content_cols)[0]
            y_min = max(0, row_idx[0] - BORDER)
            x_min = max(0, col_idx[0] - BORDER)
            y_max = min(h_arr - 1, row_idx[-1] + BORDER)
            x_max = min(w_arr - 1, col_idx[-1] + BORDER)
            img_final = img_final[y_min : y_max + 1, x_min : x_max + 1]
        print(f"[SVG] Content-aware crop: {img_final.shape[1]}x{img_final.shape[0]} px")

        # 若渲染时为保证质量而放大，缩回目标像素宽度
        if render_width_px > target_width_px and target_width_px > 0:
            scale_back = target_width_px / render_width_px
            out_w = max(1, round(img_final.shape[1] * scale_back))
            out_h = max(1, round(img_final.shape[0] * scale_back))
            img_final = cv2.resize(img_final, (out_w, out_h), interpolation=cv2.INTER_AREA)
            print(f"[SVG] Scaled to target: {out_w}x{out_h} px")

        print(f"[SVG] Final resolution: {img_final.shape[1]}x{img_final.shape[0]} px")
        if cache_key is not None:
            _SVG_RASTER_CACHE[cache_key] = img_final.copy()
            while len(_SVG_RASTER_CACHE) > _SVG_RASTER_CACHE_MAX:
                _SVG_RASTER_CACHE.pop(next(iter(_SVG_RASTER_CACHE)))
        return img_final

    except Exception as e:
        print(f"[SVG] Dual-Pass failed: {e}")
        import traceback

        traceback.print_exc()

        # 最后的保底：如果双重渲染失败，回退到普通渲染
        pil_img = renderPM.drawToPIL(drawing, bg=None, configPIL={"transparent": True})
        img_fallback = np.array(pil_img.convert("RGBA"))
        if cache_key is not None:
            _SVG_RASTER_CACHE[cache_key] = img_fallback.copy()
            while len(_SVG_RASTER_CACHE) > _SVG_RASTER_CACHE_MAX:
                _SVG_RASTER_CACHE.pop(next(iter(_SVG_RASTER_CACHE)))
        return img_fallback
