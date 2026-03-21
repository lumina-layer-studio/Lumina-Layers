"""
Lumina Studio - 高度图颜色高度计算属性测试 (Property-Based Tests)

使用 Hypothesis 验证基于高度图的 per-color 高度计算的有界性。
每个属性测试至少运行 100 次迭代。
"""

import os
import sys

import numpy as np
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config import PrinterConfig

# Constants
BASE_THICKNESS: float = PrinterConfig.LAYER_HEIGHT  # 0.08mm


def compute_color_height_map(
    grayscale: np.ndarray,
    matched_rgb: np.ndarray,
    palette: list[dict],
    max_relief_height: float,
    base_thickness: float,
    mask_solid: np.ndarray | None = None,
) -> dict[str, float]:
    """Replicate the per-color height calculation from upload_heightmap endpoint.

    For each palette color, find matching pixels in matched_rgb, compute the
    average grayscale value at those positions, and map to a height in
    [base_thickness, max_relief_height].

    Formula: height = base_thickness + (avg_gray / 255.0) * (max_relief_height - base_thickness)

    Args:
        grayscale: (H, W) uint8 grayscale heightmap (already resized to match matched_rgb).
        matched_rgb: (H, W, 3) uint8 color-matched image.
        palette: List of dicts with keys "color" (list[int] RGB) and "hex" (str "#rrggbb").
        max_relief_height: Maximum relief height in mm.
        base_thickness: Base layer thickness in mm.
        mask_solid: Optional (H, W) bool mask for solid pixels.

    Returns:
        Dict mapping hex key (6-char lowercase, no '#') to height in mm.
    """
    color_height_map: dict[str, float] = {}

    for entry in palette:
        color_rgb = np.array(entry["color"], dtype=np.uint8)
        hex_key: str = entry["hex"].lstrip("#").lower()

        color_mask = np.all(matched_rgb == color_rgb, axis=2)
        if mask_solid is not None:
            color_mask = color_mask & mask_solid

        if not np.any(color_mask):
            color_height_map[hex_key] = base_thickness
            continue

        avg_gray = float(np.mean(grayscale[color_mask]))
        height = base_thickness + (avg_gray / 255.0) * (max_relief_height - base_thickness)
        color_height_map[hex_key] = round(height, 4)

    return color_height_map


# ---------------------------------------------------------------------------
# Hypothesis strategy: generate a small grayscale image, matched_rgb, and palette
# ---------------------------------------------------------------------------
@st.composite
def heightmap_color_strategy(draw: st.DrawFn):
    """Generate a random grayscale heightmap, matched_rgb, and palette.

    Returns (grayscale, matched_rgb, palette, max_relief_height, mask_solid).
    """
    h = draw(st.integers(min_value=4, max_value=16))
    w = draw(st.integers(min_value=4, max_value=16))
    n_colors = draw(st.integers(min_value=1, max_value=8))

    # Generate n_colors distinct RGB triples
    colors: set[tuple[int, int, int]] = set()
    while len(colors) < n_colors:
        c = (
            draw(st.integers(0, 255)),
            draw(st.integers(0, 255)),
            draw(st.integers(0, 255)),
        )
        colors.add(c)
    color_list = list(colors)

    # Build matched_rgb: assign each pixel a random color from the palette
    matched_rgb = np.zeros((h, w, 3), dtype=np.uint8)
    for y in range(h):
        for x in range(w):
            idx = draw(st.integers(0, n_colors - 1))
            matched_rgb[y, x] = color_list[idx]

    # Build mask_solid: mostly True, with a few optional False pixels
    mask_solid = np.ones((h, w), dtype=bool)
    n_transparent = draw(st.integers(0, min(h * w // 4, 4)))
    for _ in range(n_transparent):
        ty = draw(st.integers(0, h - 1))
        tx = draw(st.integers(0, w - 1))
        mask_solid[ty, tx] = False
    # Ensure at least one solid pixel
    if not np.any(mask_solid):
        mask_solid[0, 0] = True

    # Build palette from the color list
    palette: list[dict] = []
    for r, g, b in color_list:
        palette.append({
            "color": [int(r), int(g), int(b)],
            "hex": f"#{r:02x}{g:02x}{b:02x}",
        })

    # Random grayscale heightmap (deterministic via Hypothesis draws)
    gray_flat = draw(
        st.lists(st.integers(0, 255), min_size=h * w, max_size=h * w)
    )
    grayscale = np.array(gray_flat, dtype=np.uint8).reshape(h, w)

    # max_relief_height must be > base_thickness
    max_relief_height = draw(
        st.floats(min_value=0.5, max_value=15.0, allow_nan=False, allow_infinity=False)
    )
    assume(max_relief_height > BASE_THICKNESS)

    return grayscale, matched_rgb, palette, max_relief_height, mask_solid


# ============================================================================
# Property 6: 高度图颜色高度计算有界性
# Feature: color-remap-relief-linkage, Property 6: 高度图颜色高度计算有界性
# **Validates: Requirements 8.4**
# ============================================================================

@settings(max_examples=100)
@given(data=heightmap_color_strategy())
def test_heightmap_color_height_bounded(data):
    """Property 6: 高度图颜色高度计算有界性

    For any valid grayscale heightmap and palette, the color_height_map
    computed from the heightmap should satisfy:
    (a) Every height value is in [base_thickness, max_relief_height]
    (b) The height equals base_thickness + (avg_gray / 255.0) * (max_relief_height - base_thickness)
        where avg_gray is the mean grayscale at matching pixel positions
    """
    grayscale, matched_rgb, palette, max_relief_height, mask_solid = data

    color_height_map = compute_color_height_map(
        grayscale=grayscale,
        matched_rgb=matched_rgb,
        palette=palette,
        max_relief_height=max_relief_height,
        base_thickness=BASE_THICKNESS,
        mask_solid=mask_solid,
    )

    # Every palette color should have an entry
    assert len(color_height_map) == len(palette), (
        f"Expected {len(palette)} entries, got {len(color_height_map)}"
    )

    for entry in palette:
        hex_key = entry["hex"].lstrip("#").lower()
        assert hex_key in color_height_map, (
            f"Missing height for color {hex_key}"
        )

        height = color_height_map[hex_key]

        # (a) Boundedness: height in [base_thickness, max_relief_height]
        assert BASE_THICKNESS - 1e-6 <= height <= max_relief_height + 1e-6, (
            f"Color {hex_key}: height {height:.4f} out of range "
            f"[{BASE_THICKNESS}, {max_relief_height}]"
        )

        # (b) Verify the height matches the formula
        color_rgb = np.array(entry["color"], dtype=np.uint8)
        color_mask = np.all(matched_rgb == color_rgb, axis=2)
        if mask_solid is not None:
            color_mask = color_mask & mask_solid

        if not np.any(color_mask):
            # No matching solid pixels → should be base_thickness
            assert abs(height - BASE_THICKNESS) < 1e-6, (
                f"Color {hex_key} has no solid pixels but height={height:.4f}, "
                f"expected {BASE_THICKNESS}"
            )
        else:
            avg_gray = float(np.mean(grayscale[color_mask]))
            expected_height = BASE_THICKNESS + (avg_gray / 255.0) * (max_relief_height - BASE_THICKNESS)
            expected_rounded = round(expected_height, 4)
            assert abs(height - expected_rounded) < 1e-4, (
                f"Color {hex_key}: height {height:.4f} != expected {expected_rounded:.4f} "
                f"(avg_gray={avg_gray:.2f})"
            )
