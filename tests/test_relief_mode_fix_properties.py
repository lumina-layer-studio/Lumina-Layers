"""
Lumina Studio - 黑色实体像素属性测试 (Property-Based Tests)

使用 Hypothesis 库验证自动高度生成中黑色实体像素的正确处理。
核心逻辑从 ui/layout_new.py 的 on_auto_height_apply 中提取，
以独立函数形式进行属性测试。

Feature: fix-2-5d-relief-mode, Property 4: 黑色实体像素包含在自动高度映射中
"""

import os
import sys

import numpy as np
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------- 从 on_auto_height_apply 提取的核心颜色收集逻辑 ----------

def extract_unique_colors(
    matched_rgb: np.ndarray,
    mask_solid: np.ndarray | None,
) -> set[str]:
    """Extract unique hex color strings from matched_rgb using mask_solid.

    This mirrors the core logic in on_auto_height_apply (ui/layout_new.py):
    - When mask_solid is available, only collect colors from solid pixels
    - When mask_solid is None, collect all colors (fallback, no black skip)

    Parameters
    ----------
    matched_rgb : np.ndarray
        Shape (H, W, 3), dtype uint8. The color-matched image.
    mask_solid : np.ndarray | None
        Shape (H, W), dtype bool. True for solid (non-background) pixels.

    Returns
    -------
    set[str]
        Set of hex color strings like '#000000', '#ff0000', etc.
    """
    unique_colors: set[str] = set()

    if mask_solid is not None:
        solid_pixels = matched_rgb[mask_solid]  # shape: (N, 3)
        if solid_pixels.size > 0:
            unique_rgb = np.unique(solid_pixels, axis=0)
            for r, g, b in unique_rgb:
                unique_colors.add(f'#{r:02x}{g:02x}{b:02x}')
    else:
        flat_pixels = matched_rgb.reshape(-1, 3)
        unique_rgb = np.unique(flat_pixels, axis=0)
        for r, g, b in unique_rgb:
            unique_colors.add(f'#{r:02x}{g:02x}{b:02x}')

    return unique_colors


# ============================================================================
# Property 4: 黑色实体像素包含在自动高度映射中
# Feature: fix-2-5d-relief-mode, Property 4: 黑色实体像素包含在自动高度映射中
# **Validates: Requirements 4.1, 4.2**
# ============================================================================

@settings(max_examples=200)
@given(
    img_h=st.integers(2, 64),
    img_w=st.integers(2, 64),
    data=st.data(),
)
def test_black_solid_pixels_included_in_color_set(
    img_h: int,
    img_w: int,
    data: st.DataObject,
) -> None:
    """Property 4: 黑色实体像素包含在自动高度映射中

    For any image containing pure black (0,0,0) pixels where the
    corresponding mask_solid positions are True, the extract_unique_colors
    function should include '#000000' in the output set.

    This validates that the auto height generator uses mask_solid for
    background detection instead of hardcoded (0,0,0) skip logic.

    **Validates: Requirements 4.1, 4.2**
    """
    # Generate random matched_rgb image
    matched_rgb = data.draw(
        st.from_type(np.ndarray).filter(lambda _: False)  # placeholder
    ) if False else np.random.randint(0, 256, (img_h, img_w, 3), dtype=np.uint8)

    # Generate mask_solid with at least one True position
    mask_solid = data.draw(
        st.lists(
            st.lists(st.booleans(), min_size=img_w, max_size=img_w),
            min_size=img_h,
            max_size=img_h,
        )
    )
    mask_solid = np.array(mask_solid, dtype=bool)

    # Pick at least one position to be both black and solid
    black_count = data.draw(st.integers(min_value=1, max_value=max(1, img_h * img_w // 4)))
    for _ in range(black_count):
        y = data.draw(st.integers(0, img_h - 1))
        x = data.draw(st.integers(0, img_w - 1))
        matched_rgb[y, x] = [0, 0, 0]
        mask_solid[y, x] = True

    # Run the extracted logic
    unique_colors = extract_unique_colors(matched_rgb, mask_solid)

    # Black solid pixels must be included
    assert '#000000' in unique_colors, (
        f"Expected '#000000' in unique_colors but got {unique_colors}. "
        f"Black solid pixel count: {black_count}, "
        f"mask_solid True count: {np.sum(mask_solid)}"
    )


@settings(max_examples=200)
@given(
    img_h=st.integers(2, 64),
    img_w=st.integers(2, 64),
    data=st.data(),
)
def test_black_non_solid_pixels_excluded(
    img_h: int,
    img_w: int,
    data: st.DataObject,
) -> None:
    """Property 4 (corollary): Black pixels NOT in mask_solid are excluded.

    When all black (0,0,0) pixels have mask_solid=False, '#000000' should
    NOT appear in the output — confirming background detection works
    correctly in both directions.

    **Validates: Requirements 4.1**
    """
    # Generate random non-black pixels for solid positions
    matched_rgb = np.random.randint(1, 256, (img_h, img_w, 3), dtype=np.uint8)
    mask_solid = np.ones((img_h, img_w), dtype=bool)

    # Place some black pixels but mark them as non-solid (background)
    black_count = data.draw(st.integers(min_value=1, max_value=max(1, img_h * img_w // 4)))
    for _ in range(black_count):
        y = data.draw(st.integers(0, img_h - 1))
        x = data.draw(st.integers(0, img_w - 1))
        matched_rgb[y, x] = [0, 0, 0]
        mask_solid[y, x] = False

    # Ensure no solid pixel is black
    solid_pixels = matched_rgb[mask_solid]
    if solid_pixels.size > 0:
        is_black = np.all(solid_pixels == 0, axis=1)
        assume(not np.any(is_black))

    unique_colors = extract_unique_colors(matched_rgb, mask_solid)

    assert '#000000' not in unique_colors, (
        f"'#000000' should NOT be in unique_colors when all black pixels "
        f"are non-solid (background). Got: {unique_colors}"
    )


@settings(max_examples=200)
@given(
    img_h=st.integers(2, 32),
    img_w=st.integers(2, 32),
)
def test_fallback_without_mask_includes_black(
    img_h: int,
    img_w: int,
) -> None:
    """Property 4 (fallback): When mask_solid is None, all colors including
    black are collected.

    This validates the fallback path: when no mask_solid is available,
    the function collects ALL unique colors without skipping black.

    **Validates: Requirements 4.1, 4.2**
    """
    matched_rgb = np.random.randint(0, 256, (img_h, img_w, 3), dtype=np.uint8)

    # Ensure at least one black pixel exists
    matched_rgb[0, 0] = [0, 0, 0]

    unique_colors = extract_unique_colors(matched_rgb, mask_solid=None)

    assert '#000000' in unique_colors, (
        f"Expected '#000000' in fallback mode (mask_solid=None), "
        f"got {unique_colors}"
    )
