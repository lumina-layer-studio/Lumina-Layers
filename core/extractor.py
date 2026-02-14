"""
Lumina Studio - Color Extractor Module

Extracts color data from printed calibration boards.
"""

import os
import numpy as np
import cv2
import gradio as gr

from config import (
    ColorMode,
    ColorSystem,
    PHYSICAL_GRID_SIZE,
    DATA_GRID_SIZE,
    DST_SIZE,
    CELL_SIZE,
    LUT_FILE_PATH,
)
from utils import Stats
from .ui_status import make_status_tag


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


def draw_corner_points(img, points, color_mode: ColorMode):
    """Draw corner points with mode-specific colors and labels."""
    if img is None:
        return None

    vis = img.copy()
    mode_enum = color_mode
    color_conf = ColorSystem.get(mode_enum)
    labels = color_conf["corner_labels"]

    if mode_enum == ColorMode.EIGHT_COLOR_MAX:
        draw_colors = [
            (255, 255, 255),  # White (TL)
            (255, 255, 0),  # Cyan/Magenta (TR)
            (0, 0, 0),  # Black (BR)
            (0, 255, 255),  # Yellow (BL)
        ]
    elif mode_enum == ColorMode.SIX_COLOR:
        draw_colors = [
            (255, 255, 255),  # White
            (214, 134, 0),  # Cyan (BGR)
            (140, 0, 236),  # Magenta (BGR)
            (42, 238, 244),  # Yellow (BGR)
        ]
    elif mode_enum == ColorMode.CMYW:
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
        cv2.putText(
            vis,
            str(i + 1),
            (int(pt[0]) + 20, int(pt[1]) + 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.2,
            (0, 0, 255),
            3,
        )

        if i < 4:
            cv2.putText(
                vis,
                labels[i],
                (int(pt[0]) + 20, int(pt[1]) + 60),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 0),
                2,
            )
    return vis


def apply_auto_white_balance(img):
    """Apply automatic white balance correction."""
    h, w, _ = img.shape
    m = 50
    corners = [
        img[0:m, 0:m],
        img[0:m, w - m : w],
        img[h - m : h, 0:m],
        img[h - m : h, w - m : w],
    ]
    avg_white = sum(c.mean(axis=(0, 1)) for c in corners) / 4.0
    gain = np.array([255, 255, 255]) / (avg_white + 1e-5)
    return np.clip(img.astype(float) * gain, 0, 255).astype(np.uint8)


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


def run_extraction(
    img,
    points,
    offset_x,
    offset_y,
    zoom,
    barrel,
    wb,
    bright,
    color_mode=ColorMode.CMYW,
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
        wb: Enable white balance
        bright: Enable brightness correction
        color_mode: Color system mode

    Returns:
        Tuple of (visualization, preview, lut_path, status_message)
    """
    if img is None:
        return None, None, None, make_status_tag("msg_no_image")
    if len(points) != 4:
        return None, None, None, make_status_tag("ext_err_need_four_points")

    # 动态确定网格大小
    mode_enum = color_mode

    if mode_enum == ColorMode.EIGHT_COLOR_MAX:
        grid_size = 37  # Data: 37x37 (1369色)
        physical_grid = 39  # Physical: 39x39
        total_cells = 1369
    elif mode_enum == ColorMode.SIX_COLOR:
        grid_size = 36  # 核心数据还是 36x36 (1296色)
        physical_grid = 38  # 物理上有 38x38 (含边框)
        total_cells = 1296
    else:
        grid_size = DATA_GRID_SIZE  # 32
        physical_grid = PHYSICAL_GRID_SIZE  # 34
        total_cells = 1024

    print(
        f"[EXTRACTOR] Mode: {mode_enum.value}, Logic: {grid_size}x{grid_size} inside {physical_grid}x{physical_grid}"
    )

    # Perspective transform
    half = DST_SIZE / physical_grid / 2.0
    src = np.float32(points)
    dst = np.float32(
        [
            [half, half],
            [DST_SIZE - half, half],
            [DST_SIZE - half, DST_SIZE - half],
            [half, DST_SIZE - half],
        ]
    )

    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(img, M, (DST_SIZE, DST_SIZE))

    if wb:
        warped = apply_auto_white_balance(warped)
    if bright:
        warped = apply_brightness_correction(warped)

    # Sampling
    extracted = np.zeros((grid_size, grid_size, 3), dtype=np.uint8)
    vis = warped.copy()

    for r in range(grid_size):
        for c in range(grid_size):
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
                avg = reg.mean(axis=(0, 1)).astype(int) if reg.size > 0 else [0, 0, 0]
                cv2.drawMarker(
                    vis, (int(cx), int(cy)), (0, 255, 0), cv2.MARKER_CROSS, 8, 1
                )
            else:
                avg = [0, 0, 0]
            extracted[r, c] = avg

    np.save(LUT_FILE_PATH, extracted)
    prev = cv2.resize(extracted, (512, 512), interpolation=cv2.INTER_NEAREST)

    Stats.increment("extractions")

    return (
        vis,
        prev,
        LUT_FILE_PATH,
        make_status_tag(
            "ext_extract_complete", grid_size=grid_size, total_cells=total_cells
        ),
    )


def probe_lut_cell(lut_path, evt: gr.SelectData):
    """Probe a specific cell in the LUT for manual inspection."""
    actual_path = LUT_FILE_PATH
    if isinstance(lut_path, str) and lut_path:
        actual_path = lut_path
    elif hasattr(lut_path, "name"):
        actual_path = lut_path.name

    if not actual_path or not os.path.exists(actual_path):
        return make_status_tag("ext_probe_no_data"), None, None
    try:
        lut = np.load(actual_path)
    except Exception:
        return make_status_tag("ext_probe_corrupted"), None, None

    x, y = evt.index
    scale = 512 / DATA_GRID_SIZE
    c = min(max(int(x / scale), 0), DATA_GRID_SIZE - 1)
    r = min(max(int(y / scale), 0), DATA_GRID_SIZE - 1)

    rgb = lut[r, c]
    hex_c = "#{:02x}{:02x}{:02x}".format(*rgb)

    html = make_status_tag("ext_probe_cell_html", row=r + 1, col=c + 1, color=hex_c)
    return html, hex_c, (r, c)


def manual_fix_cell(coord, color_input, lut_path=None):
    """Manually fix a specific cell color in the LUT."""
    actual_path = LUT_FILE_PATH
    if isinstance(lut_path, str) and lut_path:
        actual_path = lut_path
    elif hasattr(lut_path, "name"):
        actual_path = lut_path.name

    if not coord or not actual_path or not os.path.exists(actual_path):
        return None, make_status_tag("ext_manual_fix_error")

    try:
        lut = np.load(actual_path)
        r, c = coord
        new_color = [0, 0, 0]

        color_str = str(color_input)
        if color_str.startswith("rgb"):
            clean = (
                color_str.replace("rgb", "")
                .replace("a", "")
                .replace("(", "")
                .replace(")", "")
            )
            parts = clean.split(",")
            if len(parts) >= 3:
                new_color = [int(float(p.strip())) for p in parts[:3]]
        elif color_str.startswith("#"):
            hex_s = color_str.lstrip("#")
            new_color = [int(hex_s[i : i + 2], 16) for i in (0, 2, 4)]
        else:
            new_color = [int(color_str[i : i + 2], 16) for i in (0, 2, 4)]

        lut[r, c] = new_color
        np.save(actual_path, lut)
        return cv2.resize(
            lut, (512, 512), interpolation=cv2.INTER_NEAREST
        ), make_status_tag("ext_manual_fix_done")
    except Exception as e:
        return None, make_status_tag(
            "ext_manual_fix_invalid_color", color_input=color_input
        )
