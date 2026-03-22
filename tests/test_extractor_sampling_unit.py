"""Unit tests for extractor sampling helpers.

Validates:
- sRGB <-> linear round-trip accuracy (Change 1)
- Linear-light mean correctness vs gamma-space mean (Change 2)
- Dashed rectangle drawing behaviour (Change 4)
"""

from __future__ import annotations

import numpy as np

from core.extractor import _srgb_to_linear, _linear_to_srgb, _draw_dashed_rect


# =========================================================================
# 1. sRGB <-> linear round-trip
# =========================================================================


class TestSrgbLinearRoundTrip:
    """Verify round-trip conversion stays within +/-1 for all uint8 values."""

    def test_full_range_round_trip(self) -> None:
        values = np.arange(256, dtype=np.uint8)
        result = _linear_to_srgb(_srgb_to_linear(values))
        assert np.all(np.abs(result.astype(int) - values.astype(int)) <= 1)

    def test_black_and_white_exact(self) -> None:
        arr = np.array([0, 255], dtype=np.uint8)
        linear = _srgb_to_linear(arr)
        assert linear[0] == 0.0
        assert abs(linear[1] - 1.0) < 1e-9
        back = _linear_to_srgb(linear)
        assert back[0] == 0
        assert back[1] == 255

    def test_mid_gray_linearizes_lower(self) -> None:
        """sRGB 128 should linearize to ~0.216, not 0.5."""
        arr = np.array([128], dtype=np.uint8)
        linear = _srgb_to_linear(arr)
        assert 0.2 < float(linear[0]) < 0.25


# =========================================================================
# 2. Linear-light mean vs gamma-space mean
# =========================================================================


class TestLinearLightMean:
    """Verify linear-light averaging differs from naive RGB mean."""

    def test_half_black_half_white(self) -> None:
        """50% black + 50% white: linear mean ~sRGB 188, not 128."""
        patch = np.zeros((2, 1, 3), dtype=np.uint8)
        patch[0, 0] = [0, 0, 0]
        patch[1, 0] = [255, 255, 255]

        gamma_mean = patch.mean(axis=(0, 1))
        linear_mean = _linear_to_srgb(_srgb_to_linear(patch).mean(axis=(0, 1)))

        assert abs(gamma_mean[0] - 127.5) < 1
        assert linear_mean[0] > 170, f"Expected >170 but got {linear_mean[0]}"

    def test_uniform_patch_unchanged(self) -> None:
        """Uniform color should yield the same value regardless of method."""
        patch = np.full((4, 4, 3), 100, dtype=np.uint8)
        result = _linear_to_srgb(_srgb_to_linear(patch).mean(axis=(0, 1)))
        assert np.all(np.abs(result.astype(int) - 100) <= 1)


# =========================================================================
# 3. _draw_dashed_rect
# =========================================================================


class TestDrawDashedRect:
    """Verify dashed rectangle drawing on images."""

    def test_modifies_image_in_place(self) -> None:
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        original = img.copy()
        _draw_dashed_rect(img, (5, 5), (40, 40), (0, 255, 0), 1, 4)
        assert not np.array_equal(img, original)

    def test_custom_color_is_used(self) -> None:
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        _draw_dashed_rect(img, (5, 5), (40, 40), (0, 0, 255), 1, 4)
        red_pixels = img[:, :, 2] > 0
        assert np.any(red_pixels)
        blue_green = img[:, :, 0] | img[:, :, 1]
        assert not np.any(blue_green[red_pixels])

    def test_degenerate_zero_size_rect_no_crash(self) -> None:
        img = np.zeros((50, 50, 3), dtype=np.uint8)
        _draw_dashed_rect(img, (10, 10), (10, 10), (0, 255, 0), 1, 4)
