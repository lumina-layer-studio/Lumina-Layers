"""
Lumina Studio - Color Extractor Module

Extracts color data from printed calibration boards.
"""

import os
import numpy as np
import cv2
from config import (
    ColorSystem,
    PHYSICAL_GRID_SIZE,
    DATA_GRID_SIZE,
    DST_SIZE,
    CELL_SIZE,
    LUT_FILE_PATH,
    get_asset_path,
)
from utils import Stats
from utils.lut_manager import LUTManager


def _srgb_to_linear(arr: np.ndarray) -> np.ndarray:
    """Convert sRGB uint8 values to linear-light float64 (IEC 61966-2-1).
    将 sRGB uint8 值转换为线性光 float64。

    Args:
        arr (np.ndarray): Input array in sRGB space, dtype uint8. (sRGB 输入)

    Returns:
        np.ndarray: Linear-light values in [0, 1], dtype float64. (线性光值)
    """
    c = arr.astype(np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _linear_to_srgb(arr: np.ndarray) -> np.ndarray:
    """Convert linear-light float values back to sRGB uint8.
    将线性光 float 值转换回 sRGB uint8。

    Args:
        arr (np.ndarray): Linear-light values in [0, 1]. (线性光值)

    Returns:
        np.ndarray: sRGB values, dtype uint8. (sRGB 值)
    """
    c = np.clip(arr, 0.0, 1.0)
    srgb = np.where(c <= 0.0031308, 12.92 * c, 1.055 * c ** (1.0 / 2.4) - 0.055)
    return np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)


def _draw_dashed_rect(
    img: np.ndarray,
    pt1: tuple[int, int],
    pt2: tuple[int, int],
    color: tuple[int, int, int] = (0, 255, 0),
    thickness: int = 1,
    dash_len: int = 4,
) -> None:
    """Draw a dashed rectangle on *img* in-place.
    在图像上原地绘制虚线矩形。

    Args:
        img (np.ndarray): Target image (modified in-place). (目标图像，原地修改)
        pt1 (tuple[int, int]): Top-left corner (x0, y0). (左上角)
        pt2 (tuple[int, int]): Bottom-right corner (x1, y1). (右下角)
        color (tuple[int, int, int]): BGR color. (BGR 颜色)
        thickness (int): Line thickness in pixels. (线宽)
        dash_len (int): Dash segment length in pixels. (虚线段长度)
    """
    x0, y0 = pt1
    x1, y1 = pt2
    edges = [
        ((x0, y0), (x1, y0)),  # top
        ((x1, y0), (x1, y1)),  # right
        ((x1, y1), (x0, y1)),  # bottom
        ((x0, y1), (x0, y0)),  # left
    ]
    for (ex0, ey0), (ex1, ey1) in edges:
        dx = ex1 - ex0
        dy = ey1 - ey0
        length = max(abs(dx), abs(dy))
        if length == 0:
            continue
        step = 2 * dash_len
        for start in range(0, length, step):
            end = min(start + dash_len, length)
            sx = ex0 + dx * start // length
            sy = ey0 + dy * start // length
            ex = ex0 + dx * end // length
            ey = ey0 + dy * end // length
            cv2.line(img, (sx, sy), (ex, ey), color, thickness)


def _generate_recipes(color_mode: str, total_cells: int, page_choice: str = "Page 1") -> np.ndarray:
    """Generate recipe (stacking) arrays for each cell based on color mode.
    根据颜色模式为每个色块生成配方（堆叠）数组。

    Args:
        color_mode (str): Color system mode. (颜色模式)
        total_cells (int): Number of color cells. (色块数量)
        page_choice (str): Page selection for dual-page modes. (双页模式的页面选择)

    Returns:
        np.ndarray: Stacks array (N, L) int32. (堆叠配方数组)
    """
    if color_mode == "BW (Black & White)" or color_mode == "BW":
        # 2^5 = 32 combinations, 5 layers
        stacks = []
        for i in range(total_cells):
            digits = []
            temp = i
            for _ in range(5):
                digits.append(temp % 2)
                temp //= 2
            stacks.append(digits[::-1])
        return np.array(stacks, dtype=np.int32)

    if "8-Color" in color_mode:
        # Load from pre-computed asset, reverse to top-to-bottom convention
        try:
            path = get_asset_path("smart_8color_stacks.npy")
            all_stacks = np.load(path)
            all_stacks = np.array([s[::-1] for s in all_stacks])
            per_page = 1369
            page_idx = 1 if "2" in str(page_choice) else 0
            start = page_idx * per_page
            stacks = all_stacks[start:start + per_page]
            return stacks[:total_cells].astype(np.int32)
        except Exception as e:
            print(f"[EXTRACTOR] Failed to load 8-color stacks: {e}")
            return np.zeros((total_cells, 5), dtype=np.int32)

    if "6-Color" in color_mode:
        # Use get_top_1296_colors() from calibration module
        try:
            if "RYBW" in color_mode:
                from core.calibration import get_top_1296_colors_rybw
                top_stacks = get_top_1296_colors_rybw()
            else:
                from core.calibration import get_top_1296_colors
                top_stacks = get_top_1296_colors()
            stacks = [list(s) for s in top_stacks[:total_cells]]
            return np.array(stacks, dtype=np.int32)
        except Exception as e:
            print(f"[EXTRACTOR] Failed to generate 6-color stacks: {e}")
            return np.zeros((total_cells, 5), dtype=np.int32)

    if "5-Color Extended" in color_mode:
        if "2" in str(page_choice):
            # Page 2: 1444 colors from get_top_1444_colors()
            try:
                from core.calibration import get_top_1444_colors
                top_stacks = get_top_1444_colors()
                stacks = [list(s) for s in top_stacks[:total_cells]]
                return np.array(stacks, dtype=np.int32)
            except Exception as e:
                print(f"[EXTRACTOR] Failed to generate 5-color ext stacks: {e}")
                return np.zeros((total_cells, 6), dtype=np.int32)
        else:
            # Page 1: 4^5 = 1024 combinations (same as 4-color)
            stacks = []
            for i in range(total_cells):
                digits = []
                temp = i
                for _ in range(5):
                    digits.append(temp % 4)
                    temp //= 4
                stacks.append(digits[::-1])
            return np.array(stacks, dtype=np.int32)

    # Default: 4-Color (RYBW/CMYW) — 4^5 = 1024 combinations, 5 layers
    stacks = []
    for i in range(total_cells):
        digits = []
        temp = i
        for _ in range(5):
            digits.append(temp % 4)
            temp //= 4
        stacks.append(digits[::-1])
    return np.array(stacks, dtype=np.int32)


def generate_simulated_reference():
    """Generate reference image for visual comparison."""
    colors = {
        0: np.array([250, 250, 250]),
        1: np.array([220, 20, 60]),
        2: np.array([255, 230, 0]),
        3: np.array([0, 100, 240])
    }

    ref_img = np.zeros((DATA_GRID_SIZE, DATA_GRID_SIZE, 3), dtype=np.uint8)
    for i in range(1024):
        digits = []
        temp = i
        for _ in range(5):
            digits.append(temp % 4)
            temp //= 4
        stack = digits[::-1]

        mixed = sum(colors[mid] for mid in stack) / 5.0
        ref_img[i // DATA_GRID_SIZE, i % DATA_GRID_SIZE] = mixed.astype(np.uint8)

    return cv2.resize(ref_img, (512, 512), interpolation=cv2.INTER_NEAREST)


def rotate_image(img, direction):
    """Rotate image 90 degrees left or right."""
    if img is None:
        return None
    if direction in ("左旋 90°", "Rotate Left 90°"):
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif direction in ("右旋 90°", "Rotate Right 90°"):
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    return img


def draw_corner_points(img, points, color_mode: str, page_choice: str | None = None):
    """Draw corner points with mode-specific colors and labels."""
    if img is None:
        return None

    vis = img.copy()
    color_conf = ColorSystem.get(color_mode)
    labels = color_conf['corner_labels']

    if color_mode == "BW (Black & White)" or color_mode == "BW":
        draw_colors = [
            (255, 255, 255),  # White (TL)
            (0, 0, 0),        # Black (TR)
            (0, 0, 0),        # Black (BR)
            (0, 0, 0)         # Black (BL)
        ]
    elif "8-Color" in color_mode:
        draw_colors = [
            (255, 255, 255),  # White (TL)
            (255, 255, 0),    # Cyan/Magenta (TR)
            (0, 0, 0),        # Black (BR)
            (0, 255, 255)     # Yellow (BL)
        ]
    elif "6-Color" in color_mode:
        draw_colors = [
            (255, 255, 255),  # White
            (214, 134, 0),    # Cyan (BGR)
            (140, 0, 236),    # Magenta (BGR)
            (42, 238, 244)    # Yellow (BGR)
        ]
    elif "5-Color Extended" in color_mode:
        if page_choice is not None and "2" in str(page_choice):
            labels = ["蓝色 (左上)", "红色 (右上)", "黑色 (右下)", "黄色 (左下)"]
            draw_colors = [
                (240, 100, 0),    # Blue (BGR)
                (60, 20, 220),    # Red (BGR)
                (0, 0, 0),        # Black (BGR)
                (0, 230, 255)     # Yellow (BGR)
            ]
        else:
            draw_colors = [
                (255, 255, 255),  # White
                (60, 20, 220),    # Red (BGR)
                (240, 100, 0),    # Blue (BGR)
                (0, 230, 255)     # Yellow (BGR)
            ]
    elif "CMYW" in color_mode:
        draw_colors = [
            (255, 255, 255),  # White
            (214, 134, 0),    # Cyan (BGR)
            (140, 0, 236),    # Magenta (BGR)
            (42, 238, 244)    # Yellow (BGR)
        ]
    else:  # RYBW
        draw_colors = [
            (255, 255, 255),  # White
            (60, 20, 220),    # Red (BGR)
            (240, 100, 0),    # Blue (BGR)
            (0, 230, 255)     # Yellow (BGR)
        ]

    for i, pt in enumerate(points):
        color = draw_colors[i] if i < 4 else (0, 255, 0)

        cv2.circle(vis, (int(pt[0]), int(pt[1])), 15, color, -1)
        cv2.circle(vis, (int(pt[0]), int(pt[1])), 15, (0, 0, 0), 2)
        cv2.putText(vis, str(i + 1), (int(pt[0]) + 20, int(pt[1]) + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)

        if i < 4:
            cv2.putText(vis, labels[i], (int(pt[0]) + 20, int(pt[1]) + 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    return vis


def apply_auto_white_balance(img):
    """Apply automatic white balance correction."""
    h, w, _ = img.shape
    m = 50
    corners = [img[0:m, 0:m], img[0:m, w-m:w], img[h-m:h, 0:m], img[h-m:h, w-m:w]]
    avg_white = sum(_srgb_to_linear(c).mean(axis=(0, 1)) for c in corners) / 4.0
    gain = np.array([1.0, 1.0, 1.0]) / (avg_white + 1e-5)
    linear_img = _srgb_to_linear(img)
    return _linear_to_srgb(np.clip(linear_img * gain, 0.0, 1.0))


def apply_brightness_correction(img):
    """Apply vignette/brightness correction."""
    h, w, _ = img.shape
    img_lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(img_lab)

    m = 50
    tl, tr = l[0:m, 0:m].mean(), l[0:m, w-m:w].mean()
    bl, br = l[h-m:h, 0:m].mean(), l[h-m:h, w-m:w].mean()

    top = np.linspace(tl, tr, w)
    bot = np.linspace(bl, br, w)
    mask = np.array([top * (1 - y/h) + bot * (y/h) for y in range(h)])

    target = (tl + tr + bl + br) / 4.0
    l_new = np.clip(l.astype(float) * (target / (mask + 1e-5)), 0, 255).astype(np.uint8)

    return cv2.cvtColor(cv2.merge([l_new, a, b]), cv2.COLOR_LAB2RGB)


def run_extraction(img, points, offset_x, offset_y, zoom, barrel, wb, bright, color_mode="CMYW", page_choice="Page 1"):
    """
    Main extraction pipeline with dynamic grid size support.
    
    Args:
        img: Input image
        points: Four corner points
        offset_x: X offset correction
        offset_y: Y offset correction
        zoom: Zoom correction
        barrel: Barrel distortion correction
        wb: Enable white balance
        bright: Enable brightness correction
        color_mode: Color system mode
    
    Returns:
        Tuple of (visualization, preview, lut_path, status_message)
    """
    if img is None:
        return None, None, None, "[ERROR] 请先上传图片"
    if len(points) != 4:
        return None, None, None, "[ERROR] 请点击4个角点"
    
    # 动态确定网格大小
    if color_mode == "BW (Black & White)" or color_mode == "BW":
        grid_size = 6           # Data: 6x6 (32色，只用前32个)
        physical_grid = 8       # Physical: 8x8 (含边框)
        total_cells = 32
    elif "8-Color" in color_mode:
        grid_size = 37          # Data: 37x37 (1369色)
        physical_grid = 39      # Physical: 39x39
        total_cells = 1369
    elif "6-Color" in color_mode:
        grid_size = 36          # 核心数据还是 36x36 (1296色)
        physical_grid = 38      # 物理上有 38x38 (含边框)
        total_cells = 1296
    elif "5-Color Extended" in color_mode:
        # 5-Color Extended dual-page mode
        # Page 1: 32x32 = 1024 colors (5-layer)
        # Page 2: 38x38 = 1444 colors (6-layer)
        if "2" in str(page_choice):
            grid_size = 38          # Page 2: 38x38 data
            physical_grid = 40      # Physical: 40x40
            total_cells = 1444
        else:
            grid_size = 32          # Page 1: 32x32 data
            physical_grid = 34      # Physical: 34x34
            total_cells = 1024
    else:
        grid_size = DATA_GRID_SIZE  # 32
        physical_grid = PHYSICAL_GRID_SIZE  # 34
        total_cells = 1024
    
    print(f"[EXTRACTOR] Mode: {color_mode}, Logic: {grid_size}x{grid_size} inside {physical_grid}x{physical_grid}")

    # Perspective transform
    half = DST_SIZE / physical_grid / 2.0
    src = np.float32(points)
    dst = np.float32([
        [half, half], [DST_SIZE - half, half],
        [DST_SIZE - half, DST_SIZE - half], [half, DST_SIZE - half]
    ])

    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(img, M, (DST_SIZE, DST_SIZE))

    if wb:
        warped = apply_auto_white_balance(warped)
    if bright:
        warped = apply_brightness_correction(warped)

    # Sampling
    extracted = np.zeros((grid_size, grid_size, 3), dtype=np.uint8)
    vis = warped.copy()

    # BW模式特殊处理：只提取前32个色块
    if color_mode == "BW (Black & White)" or color_mode == "BW":
        cells_to_extract = 32
    else:
        cells_to_extract = grid_size * grid_size

    extracted_count = 0
    for r in range(grid_size):
        for c in range(grid_size):
            # BW模式：只提取前32个
            if extracted_count >= cells_to_extract:
                break
            
            # 【关键】计算物理位置时的偏移
            # 无论是 4色 还是 6色，因为都有 1 格边框，所以都需要 +1
            phys_r = r + 1
            phys_c = c + 1
            
            # 归一化坐标 [-1, 1] (基于 physical_grid)
            nx = (phys_c + 0.5) / physical_grid * 2 - 1
            ny = (phys_r + 0.5) / physical_grid * 2 - 1

            rad = np.sqrt(nx**2 + ny**2)
            k = 1 + barrel * (rad**2)
            dx, dy = nx * k * zoom, ny * k * zoom

            cx = (dx + 1) / 2 * DST_SIZE + offset_x
            cy = (dy + 1) / 2 * DST_SIZE + offset_y

            if 0 <= cx < DST_SIZE and 0 <= cy < DST_SIZE:
                x0, y0 = int(max(0, cx - 4)), int(max(0, cy - 4))
                x1, y1 = int(min(DST_SIZE, cx + 4)), int(min(DST_SIZE, cy + 4))
                reg = warped[y0:y1, x0:x1]
                if reg.size > 0:
                    avg = _linear_to_srgb(_srgb_to_linear(reg).mean(axis=(0, 1)))
                else:
                    avg = [0, 0, 0]
                cv2.drawMarker(vis, (int(cx), int(cy)), (0, 255, 0), cv2.MARKER_CROSS, 8, 1)
                _draw_dashed_rect(vis, (x0, y0), (x1, y1), (0, 255, 0), 1, 4)
            else:
                avg = [0, 0, 0]
            extracted[r, c] = avg
            extracted_count += 1
        
        # BW模式：提取够32个就退出外层循环
        if extracted_count >= cells_to_extract:
            break

    # 保存为 Keyed JSON 格式
    rgb_flat = extracted.reshape(-1, 3)[:total_cells]
    metadata = LUTManager.infer_default_metadata("lumina_lut", LUT_FILE_PATH, len(rgb_flat), color_mode=color_mode)
    # 根据颜色模式生成配方
    stacks = _generate_recipes(color_mode, total_cells, page_choice)
    LUTManager.save_keyed_json(LUT_FILE_PATH, rgb_flat, stacks, metadata)
    prev = cv2.resize(extracted, (512, 512), interpolation=cv2.INTER_NEAREST)

    Stats.increment("extractions")

    return vis, prev, LUT_FILE_PATH, f"[OK] 提取完成！({grid_size}x{grid_size}, {total_cells}色) LUT已保存"


def probe_lut_cell(
    lut_path: str | None,
    click_coords: tuple[int, int],
) -> tuple[str, str | None, tuple[int, int] | None]:
    """Probe a specific cell in the LUT for manual inspection.
    探测 LUT 中指定单元格的颜色信息，用于手动检查。

    Args:
        lut_path (str | None): Path to the LUT file. (LUT 文件路径)
        click_coords (tuple[int, int]): (x, y) pixel coordinates of the click. (点击的像素坐标)

    Returns:
        tuple[str, str | None, tuple[int, int] | None]:
            HTML info string, hex color string, and (row, col) grid coordinates.
            (HTML 信息字符串、十六进制颜色字符串、网格坐标)
    """
    actual_path = LUT_FILE_PATH
    if isinstance(lut_path, str) and lut_path:
        actual_path = lut_path
    elif hasattr(lut_path, "name"):
        actual_path = lut_path.name

    if not actual_path or not os.path.exists(actual_path):
        return "[WARNING] 无数据", None, None
    try:
        rgb, _stacks, _metadata = LUTManager.load_lut_with_metadata(actual_path)
    except Exception:
        return "[WARNING] 数据损坏", None, None

    if len(rgb) == 0:
        return "[WARNING] 无数据", None, None

    # 从 1D rgb 数组推断 2D 网格尺寸
    n = len(rgb)
    side = int(np.sqrt(n))
    if side * side != n:
        # 非正方形，尝试最接近的正方形
        side = int(np.ceil(np.sqrt(n)))
    lut_width = side
    lut_height = side

    x, y = click_coords
    scale = 512 / lut_width  # 使用实际宽度计算缩放比例
    c = min(max(int(x / scale), 0), lut_width - 1)
    r = min(max(int(y / scale), 0), lut_height - 1)

    # 将 2D 坐标映射回 1D 索引
    idx = r * lut_width + c
    if idx >= n:
        return "[WARNING] 索引超出范围", None, None

    cell_rgb = rgb[idx]
    hex_c = '#{:02x}{:02x}{:02x}'.format(*cell_rgb)

    html = f"""
    <div style='background:#1a1a2e; padding:10px; border-radius:8px; color:white;'>
        <b>行 {r+1} / 列 {c+1}</b><br>
        <div style='background:{hex_c}; width:60px; height:30px; border:2px solid white; 
             display:inline-block; vertical-align:middle; border-radius:4px;'></div>
        <span style='margin-left:10px; font-family:monospace;'>{hex_c}</span>
    </div>
    """
    return html, hex_c, (r, c)


def manual_fix_cell(coord, color_input, lut_path=None):
    """Manually fix a specific cell color in the LUT."""
    actual_path = LUT_FILE_PATH
    if isinstance(lut_path, str) and lut_path:
        actual_path = lut_path
    elif hasattr(lut_path, "name"):
        actual_path = lut_path.name

    if not coord or not actual_path or not os.path.exists(actual_path):
        print(f"[MANUAL_FIX] Error: coord={coord}, actual_path={actual_path}, exists={os.path.exists(actual_path) if actual_path else False}")
        return None, "[WARNING] 错误"

    try:
        print(f"[MANUAL_FIX] Loading LUT from: {actual_path}")
        rgb, stacks, metadata = LUTManager.load_lut_with_metadata(actual_path)
        print(f"[MANUAL_FIX] RGB shape: {rgb.shape}")
        r, c = coord

        # 从 1D rgb 数组推断 2D 网格尺寸
        n = len(rgb)
        side = int(np.sqrt(n))
        if side * side != n:
            side = int(np.ceil(np.sqrt(n)))

        # 将 2D 坐标映射为 1D 索引
        idx = r * side + c
        if idx >= n:
            return None, "[WARNING] 索引超出范围"

        print(f"[MANUAL_FIX] Fixing cell ({r}, {c}), idx={idx}")
        new_color = [0, 0, 0]

        color_str = str(color_input)
        if color_str.startswith('rgb'):
            clean = color_str.replace('rgb', '').replace('a', '').replace('(', '').replace(')', '')
            parts = clean.split(',')
            if len(parts) >= 3:
                new_color = [int(float(p.strip())) for p in parts[:3]]
        elif color_str.startswith('#'):
            hex_s = color_str.lstrip('#')
            new_color = [int(hex_s[i:i+2], 16) for i in (0, 2, 4)]
        else:
            new_color = [int(color_str[i:i+2], 16) for i in (0, 2, 4)]

        print(f"[MANUAL_FIX] Old color: {rgb[idx]}, New color: {new_color}")
        rgb[idx] = new_color

        # 通过 save_keyed_json 保存修改后的 LUT
        if stacks is None:
            stacks = np.zeros((n, 0), dtype=np.int32)
        LUTManager.save_keyed_json(actual_path, rgb, stacks, metadata)
        print(f"[MANUAL_FIX] Saved to: {actual_path}")

        # For 8-color mode: also ensure we save to the correct assets path
        # Check if the path is a temp_8c_page file
        if "temp_8c_page_" in actual_path:
            import re
            import sys as _sys
            match = re.search(r'temp_8c_page_(\d+)\.(npy|json)', actual_path)
            if match:
                page_num = match.group(1)
                if getattr(_sys, 'frozen', False):
                    assets_dir = os.path.join(os.getcwd(), "assets")
                else:
                    assets_dir = "assets"

                os.makedirs(assets_dir, exist_ok=True)
                assets_path = os.path.join(assets_dir, f"temp_8c_page_{page_num}.json")

                if os.path.abspath(actual_path) != os.path.abspath(assets_path):
                    LUTManager.save_keyed_json(assets_path, rgb, stacks, metadata)
                    print(f"[MANUAL_FIX] Also saved to assets: {assets_path}")

        # 将 1D rgb reshape 回 2D grid 用于预览
        lut_2d = rgb[:side*side].reshape(side, side, 3) if n >= side * side else rgb.reshape(-1, 1, 3)
        preview = cv2.resize(lut_2d, (512, 512), interpolation=cv2.INTER_NEAREST)
        print(f"[MANUAL_FIX] Preview shape: {preview.shape}")
        return preview, "[OK] 已修正"
    except Exception as e:
        print(f"[MANUAL_FIX] Exception: {e}")
        import traceback
        traceback.print_exc()
        return None, f"[ERROR] 格式错误: {color_input}"
