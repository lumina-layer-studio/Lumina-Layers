"""
Lumina Studio - Color Extractor Module

Extracts color data from printed calibration boards.
"""

import os
import logging
import itertools
import re
from functools import lru_cache
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
from core.lut_card_layout import (
    EIGHT_COLOR_FULL_TOTAL_RECIPES,
    EIGHT_COLOR_PAGE_CAPACITY,
    LutCardLayout,
    LutCardPage,
    cell_for_row_index,
    localize_page_layout,
    resolve_extraction_page_layout,
    resolve_lut_layout,
    row_index_for_cell,
)
from utils import Stats
from utils.lut_manager import LUTManager
from core.errors import CoreProcessingError

log = logging.getLogger(__name__)
EXTRACTOR_HANDLED_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    AttributeError,
    OSError,
    RuntimeError,
)
EIGHT_COLOR_FULL_TOTAL_PAGES = int(np.ceil(EIGHT_COLOR_FULL_TOTAL_RECIPES / EIGHT_COLOR_PAGE_CAPACITY))


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


_ROI_FRAC = 0.4
_MIN_HALF_ROI = 4


def _compute_sampling_geometry(
    grid_size: int,
    physical_grid: int,
    zoom: float,
    barrel: float,
    offset_x: float,
    offset_y: float,
    roi_frac: float = _ROI_FRAC,
    min_half_roi: int = _MIN_HALF_ROI,
    padding: int | float = 1,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Pre-compute corrected cell centers and per-cell adaptive ROI sizes.
    预计算校正后的色块中心坐标和逐色块自适应 ROI 尺寸。

    The ROI for each cell is bounded by both a fraction of the nominal grid
    pitch and the local post-warp center-to-center spacing, preventing
    overlap under zoom / barrel-distortion extremes.

    Args:
        grid_size: Data cells per side (e.g. 32 for 4-color).
            (每边数据色块数)
        physical_grid: Physical grid dimension including borders.
            (包含边框的物理网格维度)
        zoom: Zoom correction factor. (缩放校正因子)
        barrel: Barrel distortion coefficient. (桶形畸变系数)
        offset_x: Global X pixel offset. (全局 X 像素偏移)
        offset_y: Global Y pixel offset. (全局 Y 像素偏移)
        roi_frac: Fraction of nominal cell size to sample (default 0.6).
            (采样区域占名义色块尺寸的比例)
        min_half_roi: Desired minimum half-ROI in pixels for nominal
            sizing (default 4).  The actual per-cell value may be smaller
            when local spacing requires it; the absolute floor is 1 px.
            (名义半 ROI 期望下限；实际值受局部间距约束，绝对下限为 1px)
        padding: Physical padding cells before the data grid.
            (数据区前的物理 padding 格数)

    Returns:
        Tuple of (centers_x, centers_y, half_roi_map), each shaped
        (grid_size, grid_size).
        (中心 X 坐标、中心 Y 坐标、逐色块半 ROI 尺寸)
    """
    cell_px = DST_SIZE / physical_grid
    nominal_half_roi = max(min_half_roi, int(cell_px * roi_frac / 2))

    rs = np.arange(grid_size)
    cs = np.arange(grid_size)
    rr, cc = np.meshgrid(rs, cs, indexing="ij")

    physical_padding = max(0.0, float(padding))
    phys_r = rr + physical_padding
    phys_c = cc + physical_padding
    nx = (phys_c + 0.5) / physical_grid * 2 - 1
    ny = (phys_r + 0.5) / physical_grid * 2 - 1

    rad = np.sqrt(nx**2 + ny**2)
    k = 1 + barrel * (rad**2)
    dx = nx * k * zoom
    dy = ny * k * zoom

    centers_x = (dx + 1) / 2 * DST_SIZE + offset_x
    centers_y = (dy + 1) / 2 * DST_SIZE + offset_y

    half_roi_map = np.full((grid_size, grid_size), float(nominal_half_roi))

    if grid_size > 1:
        h_gaps = np.abs(np.diff(centers_x, axis=1))
        half_roi_map[:, 1:] = np.minimum(half_roi_map[:, 1:], h_gaps / 2)
        half_roi_map[:, :-1] = np.minimum(half_roi_map[:, :-1], h_gaps / 2)

        v_gaps = np.abs(np.diff(centers_y, axis=0))
        half_roi_map[1:, :] = np.minimum(half_roi_map[1:, :], v_gaps / 2)
        half_roi_map[:-1, :] = np.minimum(half_roi_map[:-1, :], v_gaps / 2)

    # Gap bound is the hard physical constraint; absolute floor is 1px
    # to guarantee a valid (≥2×2) ROI even under extreme compression.
    half_roi_map = np.maximum(half_roi_map, 1).astype(int)

    return centers_x, centers_y, half_roi_map


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


def _normalize_6color_mode(color_mode: str) -> str:
    """Normalize six-color variants to unified CMYW recipe mode.
    将 6 色变体统一归一到 CMYW 配方模式。

    Args:
        color_mode (str): Input color mode string. (输入颜色模式)

    Returns:
        str: Normalized color mode string. (归一化后的颜色模式)
    """
    if "6-Color" in str(color_mode):
        return "6-Color (CMYWGK 1296)"
    return color_mode


def _parse_page_number(page_choice: str, default: int = 1) -> int:
    match = re.search(r"(\d+)", str(page_choice))
    if match is None:
        return default
    page_number = int(match.group(1))
    return page_number if page_number >= 1 else default


@lru_cache(maxsize=1)
def _load_selected_8color_stacks() -> np.ndarray:
    path = get_asset_path("smart_8color_stacks.npy")
    all_stacks = np.load(path)
    return np.array([s[::-1] for s in all_stacks], dtype=np.int32)


@lru_cache(maxsize=1)
def _build_full_8color_stacks() -> np.ndarray:
    return np.array(list(itertools.product(range(8), repeat=5)), dtype=np.int32)


def _get_8color_page_cell_count(page_choice: str, eight_color_full_export: bool) -> int:
    page_layout = resolve_extraction_page_layout(
        "8-Color Max",
        page=page_choice,
        eight_color_full_export=eight_color_full_export,
    )
    return page_layout.item_count


def _get_8color_page_stacks(page_choice: str, eight_color_full_export: bool) -> np.ndarray:
    all_stacks = _build_full_8color_stacks() if eight_color_full_export else _load_selected_8color_stacks()
    total_pages = EIGHT_COLOR_FULL_TOTAL_PAGES if eight_color_full_export else 2
    page_number = min(max(_parse_page_number(page_choice), 1), total_pages)
    start = (page_number - 1) * EIGHT_COLOR_PAGE_CAPACITY
    return all_stacks[start : start + EIGHT_COLOR_PAGE_CAPACITY]


def _generate_recipes(
    color_mode: str,
    total_cells: int,
    page_choice: str = "Page 1",
    eight_color_full_export: bool = False,
) -> np.ndarray:
    """Generate recipe (stacking) arrays for each cell based on color mode.
    根据颜色模式为每个色块生成配方（堆叠）数组。

    Args:
        color_mode (str): Color system mode. (颜色模式)
        total_cells (int): Number of color cells. (色块数量)
        page_choice (str): Page selection for paged modes. (分页模式的页面选择)
        eight_color_full_export (bool): Whether 8-color mode should use the
            exhaustive full-page recipe set instead of the compact two-page set.
            8 色模式是否使用全量分页配方，而非精简双页配方。

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
        try:
            stacks = _get_8color_page_stacks(page_choice, eight_color_full_export)
            return stacks[:total_cells].astype(np.int32)
        except (OSError, ValueError, ImportError) as exc:
            log.warning(
                "Failed to load 8-color stacks, using zeros fallback",
                extra={
                    "event": "core_extractor_generate_recipes_8color_fallback",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            return np.zeros((total_cells, 5), dtype=np.int32)

    if "6-Color" in color_mode:
        try:
            from core.calibration import get_top_1296_colors

            top_stacks = get_top_1296_colors()
            # get_top_1296_colors 返回底到顶约定，需反转为顶到底（与校色板生成一致）
            stacks = [list(reversed(s)) for s in top_stacks[:total_cells]]
            return np.array(stacks, dtype=np.int32)
        except (OSError, ValueError, ImportError) as exc:
            log.warning(
                "Failed to generate 6-color stacks, using zeros fallback",
                extra={
                    "event": "core_extractor_generate_recipes_6color_fallback",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
            return np.zeros((total_cells, 5), dtype=np.int32)

    if "5-Color Extended" in color_mode:
        if "2" in str(page_choice):
            # Page 2 must use the same 6-layer recipe order as the generated
            # calibration board; otherwise JSON export stores the wrong
            # material decisions even when the sampled RGB colors are correct.
            try:
                from core.calibration import select_extended_1444_colors

                base_stacks = []
                for i in range(1024):
                    digits = []
                    temp = i
                    for _ in range(5):
                        digits.append(temp % 4)
                        temp //= 4
                    base_stacks.append(tuple(reversed(digits)))
                top_stacks = select_extended_1444_colors(base_stacks)
                stacks = [list(s) for s in top_stacks[:total_cells]]
                return np.array(stacks, dtype=np.int32)
            except (OSError, ValueError, ImportError) as exc:
                log.warning(
                    "Failed to generate 5-color-extended stacks, using zeros fallback",
                    extra={
                        "event": "core_extractor_generate_recipes_5c_fallback",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
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

    # Default: 4-Color (RYBW/CMYW), 4^5 = 1024 combinations, 5 layers
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
        3: np.array([0, 100, 240]),
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
    labels = color_conf["corner_labels"]

    if color_mode == "BW (Black & White)" or color_mode == "BW":
        draw_colors = [
            (255, 255, 255),  # White (TL)
            (0, 0, 0),  # Black (TR)
            (0, 0, 0),  # Black (BR)
            (0, 0, 0),  # Black (BL)
        ]
    elif "8-Color" in color_mode:
        draw_colors = [
            (255, 255, 255),  # White (TL)
            (255, 255, 0),  # Cyan/Magenta (TR)
            (0, 0, 0),  # Black (BR)
            (0, 255, 255),  # Yellow (BL)
        ]
    elif "6-Color" in color_mode:
        labels = ColorSystem.SIX_COLOR["corner_labels"]
        draw_colors = [
            (255, 255, 255),  # White
            (214, 134, 0),  # Cyan (BGR)
            (140, 0, 236),  # Magenta (BGR)
            (42, 238, 244),  # Yellow (BGR)
        ]
    elif "5-Color Extended" in color_mode:
        if page_choice is not None and "2" in str(page_choice):
            labels = ["蓝色 (左上)", "红色 (右上)", "黑色 (右下)", "黄色 (左下)"]
            draw_colors = [
                (240, 100, 0),  # Blue (BGR)
                (60, 20, 220),  # Red (BGR)
                (0, 0, 0),  # Black (BGR)
                (0, 230, 255),  # Yellow (BGR)
            ]
        else:
            draw_colors = [
                (255, 255, 255),  # White
                (60, 20, 220),  # Red (BGR)
                (240, 100, 0),  # Blue (BGR)
                (0, 230, 255),  # Yellow (BGR)
            ]
    elif "CMYW" in color_mode:
        draw_colors = [
            (255, 255, 255),  # White
            (214, 134, 0),  # Cyan (BGR)
            (140, 0, 236),  # Magenta (BGR)
            (42, 238, 244),  # Yellow (BGR)
        ]
    else:  # RYBW
        draw_colors = [
            (255, 255, 255),  # White
            (60, 20, 220),  # Red (BGR)
            (240, 100, 0),  # Blue (BGR)
            (0, 230, 255),  # Yellow (BGR)
        ]

    for i, pt in enumerate(points):
        color = draw_colors[i] if i < 4 else (0, 255, 0)

        cv2.circle(vis, (int(pt[0]), int(pt[1])), 15, color, -1)
        cv2.circle(vis, (int(pt[0]), int(pt[1])), 15, (0, 0, 0), 2)
        cv2.putText(vis, str(i + 1), (int(pt[0]) + 20, int(pt[1]) + 20), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 255), 3)

        if i < 4:
            cv2.putText(vis, labels[i], (int(pt[0]) + 20, int(pt[1]) + 60), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    return vis


def apply_brightness_correction(img):
    """Apply vignette/brightness correction."""
    h, w, _ = img.shape
    img_lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB)
    l, a, b = cv2.split(img_lab)

    m = 50
    tl, tr = l[0:m, 0:m].mean(), l[0:m, w - m : w].mean()
    bl, br = l[h - m : h, 0:m].mean(), l[h - m : h, w - m : w].mean()

    top = np.linspace(tl, tr, w)
    bot = np.linspace(bl, br, w)
    mask = np.array([top * (1 - y / h) + bot * (y / h) for y in range(h)])

    target = (tl + tr + bl + br) / 4.0
    l_new = np.clip(l.astype(float) * (target / (mask + 1e-5)), 0, 255).astype(np.uint8)

    return cv2.cvtColor(cv2.merge([l_new, a, b]), cv2.COLOR_LAB2RGB)


def apply_auto_white_balance(img: np.ndarray) -> np.ndarray:
    """Apply automatic white balance using bright near-neutral pixel detection.
    使用高亮近中性色像素检测进行自动白平衡。

    Strategy:
    1. Find bright pixels (top 15% luminance).
    2. Among those, select near-neutral ones (low chroma in LAB space).
    3. Use their average RGB as the white reference.
    4. Scale each channel so the reference becomes pure white (255).
    Falls back to top-percentile method if no neutral pixels are found.

    Args:
        img (np.ndarray): Input RGB image, dtype uint8. (RGB 输入图像)

    Returns:
        np.ndarray: White-balanced RGB image, dtype uint8. (白平衡后的 RGB 图像)
    """
    h, w = img.shape[:2]
    img_f = img.astype(np.float64)

    # Step 1: find bright pixels (top 15% by luminance)
    lum = 0.299 * img_f[:, :, 0] + 0.587 * img_f[:, :, 1] + 0.114 * img_f[:, :, 2]
    bright_thresh = np.percentile(lum, 85)
    bright_mask = lum >= bright_thresh

    # Step 2: among bright pixels, find near-neutral ones (low chroma)
    # Convert to LAB to measure chroma = sqrt(a^2 + b^2)
    img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB).astype(np.float64)
    a_ch = lab[:, :, 1] - 128.0
    b_ch = lab[:, :, 2] - 128.0
    chroma = np.sqrt(a_ch**2 + b_ch**2)

    # Near-neutral: chroma < 15 (fairly desaturated)
    neutral_mask = bright_mask & (chroma < 15)
    count = neutral_mask.sum()

    if count < 50:
        # Fallback: relax chroma constraint
        neutral_mask = bright_mask & (chroma < 30)
        count = neutral_mask.sum()

    if count < 50:
        # Final fallback: just use top 2% brightest
        top_thresh = np.percentile(lum, 98)
        neutral_mask = lum >= top_thresh
        count = neutral_mask.sum()

    if count < 10:
        return img

    white_ref = img_f[neutral_mask].mean(axis=0)
    if white_ref.min() < 10:
        return img

    gains = 255.0 / white_ref
    log.info(
        f"white_ref=[{white_ref[0]:.1f}, {white_ref[1]:.1f}, {white_ref[2]:.1f}], "
        f"gains=[{gains[0]:.3f}, {gains[1]:.3f}, {gains[2]:.3f}], neutral_pixels={count}"
    )
    balanced = np.clip(img_f * gains, 0, 255).astype(np.uint8)
    return balanced


def run_extraction(
    img,
    points,
    offset_x,
    offset_y,
    zoom,
    barrel,
    bright,
    color_mode="CMYW",
    page_choice="Page 1",
    auto_wb=False,
    eight_color_full_export=False,
):
    """
    Main extraction pipeline with dynamic grid size support.

    Args:
        img: Input image
        points: Four corner points
        offset_x: X offset correction
        offset_y: Y offset correction
        zoom: Zoom correction
        barrel: Barrel distortion correction
        bright: Enable brightness correction
        color_mode: Color system mode
        page_choice: Page selection for paged modes
        auto_wb: Enable automatic white balance
        eight_color_full_export: Whether 8-color mode uses the exhaustive
            full-page calibration set

    Returns:
        Tuple of (visualization, preview, lut_path, status_message)
    """
    if img is None:
        return None, None, None, "[ERROR] 请先上传图片"
    if len(points) != 4:
        return None, None, None, "[ERROR] Please select 4 corner points"

    page_layout = resolve_extraction_page_layout(
        color_mode,
        page=page_choice,
        eight_color_full_export=eight_color_full_export,
    )
    grid_rows = page_layout.data_rows
    grid_cols = page_layout.data_cols
    if grid_rows != grid_cols or page_layout.physical_rows != page_layout.physical_cols:
        raise ValueError("Only square calibration layouts are supported by extractor sampling")
    grid_size = grid_rows
    physical_grid = page_layout.physical_rows
    total_cells = page_layout.item_count

    log.info(
        f"Mode: {color_mode}, Logic: {grid_size}x{grid_size} inside {physical_grid}x{physical_grid}, auto_wb={auto_wb}, bright={bright}, eight_color_full_export={eight_color_full_export}"
    )

    # Perspective transform
    half = DST_SIZE / physical_grid / 2.0
    src = np.float32(points)
    dst = np.float32(
        [[half, half], [DST_SIZE - half, half], [DST_SIZE - half, DST_SIZE - half], [half, DST_SIZE - half]]
    )

    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(img, M, (DST_SIZE, DST_SIZE))

    if auto_wb:
        warped = apply_auto_white_balance(warped)

    if bright:
        warped = apply_brightness_correction(warped)

    # Sampling — pre-compute corrected centers and per-cell adaptive ROI
    extracted = np.zeros((grid_rows, grid_cols, 3), dtype=np.uint8)
    vis = warped.copy()

    centers_x, centers_y, half_roi_map = _compute_sampling_geometry(
        grid_size,
        physical_grid,
        zoom,
        barrel,
        offset_x,
        offset_y,
        padding=page_layout.padding,
    )
    cell_px = DST_SIZE / physical_grid
    marker_size = max(8, int(cell_px * 0.3))

    cells_to_extract = total_cells

    extracted_count = 0
    for r in range(grid_rows):
        for c in range(grid_cols):
            if extracted_count >= cells_to_extract:
                break

            cx = float(centers_x[r, c])
            cy = float(centers_y[r, c])
            hr = int(half_roi_map[r, c])

            # Clamp ROI to image; sample whenever the clamped region has area
            x0 = int(max(0, cx - hr))
            y0 = int(max(0, cy - hr))
            x1 = int(min(DST_SIZE, cx + hr))
            y1 = int(min(DST_SIZE, cy + hr))

            if x1 > x0 and y1 > y0:
                reg = warped[y0:y1, x0:x1]
                if reg.size > 0:
                    avg = _linear_to_srgb(_srgb_to_linear(reg).mean(axis=(0, 1)))
                else:
                    avg = [0, 0, 0]
                draw_cx = int(np.clip(cx, 0, DST_SIZE - 1))
                draw_cy = int(np.clip(cy, 0, DST_SIZE - 1))
                cv2.drawMarker(vis, (draw_cx, draw_cy), (0, 255, 0), cv2.MARKER_CROSS, marker_size, 1)
                cv2.rectangle(vis, (x0, y0), (x1, y1), (0, 255, 0), 1)
            else:
                avg = [0, 0, 0]
            extracted[r, c] = avg
            extracted_count += 1

        if extracted_count >= cells_to_extract:
            break

    # 保存为 Keyed JSON 格式
    rgb_flat = extracted.reshape(-1, 3)[:total_cells]
    metadata_mode = LUTManager._canonicalize_legacy_color_mode(color_mode) or color_mode
    metadata = LUTManager.infer_default_metadata(
        "lumina_lut",
        LUT_FILE_PATH,
        len(rgb_flat),
        color_mode=metadata_mode,
    )
    # 根据颜色模式生成配方
    stacks = _generate_recipes(
        color_mode,
        total_cells,
        page_choice,
        eight_color_full_export=eight_color_full_export,
    )
    if isinstance(stacks, np.ndarray) and stacks.ndim == 2 and stacks.shape[1] > 0:
        metadata.max_color_layers = int(stacks.shape[1])
    LUTManager.save_keyed_json(LUT_FILE_PATH, rgb_flat, stacks, metadata)
    prev = cv2.resize(extracted, (512, 512), interpolation=cv2.INTER_NEAREST)

    Stats.increment("extractions")

    return (
        vis,
        prev,
        LUT_FILE_PATH,
        f"[OK] Extraction complete: {grid_size}x{grid_size}, {total_cells} colors, LUT saved",
    )


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
        return "[WARNING] No LUT data", None, None
    try:
        rgb, _stacks, _metadata = LUTManager.load_lut_with_metadata(actual_path)
    except (OSError, ValueError, KeyError):
        return "[WARNING] 数据损坏", None, None

    if len(rgb) == 0:
        return "[WARNING] No LUT data", None, None

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
    hex_c = "#{:02x}{:02x}{:02x}".format(*cell_rgb)

    html = f"""
    <div style='background:#1a1a2e; padding:10px; border-radius:8px; color:white;'>
        <b>行 {r+1} / 列 {c+1}</b><br>
        <div style='background:{hex_c}; width:60px; height:30px; border:2px solid white; 
             display:inline-block; vertical-align:middle; border-radius:4px;'></div>
        <span style='margin-left:10px; font-family:monospace;'>{hex_c}</span>
    </div>
    """
    return html, hex_c, (r, c)


def manual_fix_cell(
    coord=None,
    color_input=None,
    lut_path=None,
    *,
    row_index: int | None = None,
    page_layout: LutCardPage | None = None,
):
    """Manually fix a specific cell color in the LUT."""
    actual_path = LUT_FILE_PATH
    if isinstance(lut_path, str) and lut_path:
        actual_path = lut_path
    elif hasattr(lut_path, "name"):
        actual_path = lut_path.name

    if (coord is None and row_index is None) or not actual_path or not os.path.exists(actual_path):
        log.info(
            f"Error: coord={coord}, row_index={row_index}, actual_path={actual_path}, exists={os.path.exists(actual_path) if actual_path else False}"
        )
        return None, "[WARNING] 错误"

    try:
        log.info(f"Loading LUT from: {actual_path}")
        rgb, stacks, metadata = LUTManager.load_lut_with_metadata(actual_path)
        log.info(f"RGB shape: {rgb.shape}")
        n = len(rgb)
        local_layout = None
        if page_layout is not None:
            if n <= page_layout.capacity:
                local_layout = localize_page_layout(page_layout, item_count=n)
            else:
                local_layout = LutCardLayout(
                    color_mode=getattr(metadata, "color_mode", "") or "",
                    total_count=n,
                    pages=(page_layout,),
                )

        if row_index is not None:
            idx = int(row_index)
            if idx < 0:
                return None, "[WARNING] 索引超出范围"
            if local_layout is not None:
                try:
                    cell = cell_for_row_index(local_layout, idx)
                except ValueError:
                    return None, "[WARNING] 索引超出范围"
                r, c = cell.data_row, cell.data_col
            else:
                side = int(np.ceil(np.sqrt(max(n, 1))))
                r, c = divmod(idx, side)
        else:
            if not coord:
                return None, "[WARNING] 错误"
            r, c = coord
            if local_layout is not None:
                idx_value = row_index_for_cell(local_layout, 0, int(r), int(c))
                if idx_value is None:
                    return None, "[WARNING] 索引超出范围"
                idx = idx_value
            else:
                layout = resolve_lut_layout(getattr(metadata, "color_mode", "") or "", n)
                idx_value = row_index_for_cell(layout, 0, int(r), int(c))
                if idx_value is None:
                    return None, "[WARNING] 索引超出范围"
                idx = idx_value
        if idx >= n:
            return None, "[WARNING] 索引超出范围"

        log.info(f"Fixing cell ({r}, {c}), idx={idx}")
        new_color = [0, 0, 0]

        color_str = str(color_input)
        if color_str.startswith("rgb"):
            clean = color_str.replace("rgb", "").replace("a", "").replace("(", "").replace(")", "")
            parts = clean.split(",")
            if len(parts) >= 3:
                new_color = [int(float(p.strip())) for p in parts[:3]]
        elif color_str.startswith("#"):
            hex_s = color_str.lstrip("#")
            new_color = [int(hex_s[i : i + 2], 16) for i in (0, 2, 4)]
        else:
            new_color = [int(color_str[i : i + 2], 16) for i in (0, 2, 4)]

        log.info(f"Old color: {rgb[idx]}, New color: {new_color}")
        rgb[idx] = new_color

        # 通过 save_keyed_json 保存修改后的 LUT
        if stacks is None:
            stacks = np.zeros((n, 0), dtype=np.int32)
        LUTManager.save_keyed_json(actual_path, rgb, stacks, metadata)
        log.info(f"Saved to: {actual_path}")

        # For 8-color mode: also ensure we save to the correct assets path
        # Check if the path is a temp_8c_page file
        if "temp_8c_page_" in actual_path:
            import re
            import sys as _sys

            match = re.search(r"temp_8c_page_(\d+)\.(npy|json)", actual_path)
            if match:
                page_num = match.group(1)
                if getattr(_sys, "frozen", False):
                    assets_dir = os.path.join(os.getcwd(), "assets")
                else:
                    assets_dir = "assets"

                os.makedirs(assets_dir, exist_ok=True)
                assets_path = os.path.join(assets_dir, f"temp_8c_page_{page_num}.json")

                if os.path.abspath(actual_path) != os.path.abspath(assets_path):
                    LUTManager.save_keyed_json(assets_path, rgb, stacks, metadata)
                    log.info(f"Also saved to assets: {assets_path}")

        # 将 1D rgb reshape 回 2D grid 用于预览
        if local_layout is not None:
            page = local_layout.pages[0]
            lut_2d = np.zeros((page.data_rows, page.data_cols, 3), dtype=np.uint8)
            page_rgb = rgb[page.start_index:page.start_index + page.item_count]
            lut_2d.reshape(-1, 3)[:len(page_rgb)] = page_rgb
        else:
            layout = resolve_lut_layout(getattr(metadata, "color_mode", "") or "", n)
            page = layout.pages[0]
            if n <= page.capacity:
                lut_2d = np.zeros((page.data_rows, page.data_cols, 3), dtype=np.uint8)
                lut_2d.reshape(-1, 3)[:n] = rgb[:n]
            else:
                side = int(np.ceil(np.sqrt(max(n, 1))))
                lut_2d = rgb[: side * side].reshape(side, side, 3) if n >= side * side else rgb.reshape(-1, 1, 3)
        preview = cv2.resize(lut_2d, (512, 512), interpolation=cv2.INTER_NEAREST)
        log.info(f"Preview shape: {preview.shape}")
        return preview, "[OK] Cell updated"
    except (TypeError, ValueError) as exc:
        log.warning(
            "Manual fix failed due to invalid input",
            extra={
                "event": "core_extractor_manual_fix_validation_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return None, f"[ERROR] 格式错误: {color_input}"
    except EXTRACTOR_HANDLED_ERRORS as exc:
        raise CoreProcessingError(f"manual_fix_cell failed for path={actual_path}, coord={coord}: {exc}") from exc
