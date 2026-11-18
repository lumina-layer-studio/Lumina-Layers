from __future__ import annotations

import numpy as np
import pytest
from scipy.spatial import KDTree

from core.pipeline.processing_ops.lut_color_matcher import (
    _lab_to_lch,
    _rgb_to_lab,
    match_colors_to_lut,
)
from core.pipeline.processing_ops.lut_loader import load_lut


def test_legacy_lut_matching_breaks_equal_lab_ties_by_rgb_distance() -> None:
    unique_colors = np.array([[246, 255, 128]], dtype=np.uint8)
    lut_rgb = np.array(
        [
            [251, 242, 118],
            [253, 243, 120],
        ],
        dtype=np.uint8,
    )
    lut_lab = _rgb_to_lab(lut_rgb)
    unique_lab = _rgb_to_lab(unique_colors)

    lab_distances = np.linalg.norm(lut_lab - unique_lab[0], axis=1)
    assert lab_distances[0] == pytest.approx(lab_distances[1])

    rgb_sq_distances = np.sum(
        (lut_rgb.astype(np.int32) - unique_colors[0].astype(np.int32)) ** 2,
        axis=1,
    )
    assert int(rgb_sq_distances[1]) < int(rgb_sq_distances[0])

    result = match_colors_to_lut(unique_colors, lut_rgb, lut_lab, KDTree(lut_lab))

    assert result.tolist() == [1]


def test_neutral_lut_matching_prefers_achromatic_dark_candidate() -> None:
    unique_colors = np.array([[36, 36, 36]], dtype=np.uint8)
    lut_rgb = np.array(
        [
            [20, 28, 40],
            [24, 24, 24],
        ],
        dtype=np.uint8,
    )
    lut_lab = _rgb_to_lab(lut_rgb)

    result = match_colors_to_lut(unique_colors, lut_rgb, lut_lab, KDTree(lut_lab))

    assert result.tolist() == [1]


def test_chromatic_dark_lut_matching_keeps_colored_candidate() -> None:
    unique_colors = np.array([[20, 28, 40]], dtype=np.uint8)
    lut_rgb = np.array(
        [
            [20, 28, 40],
            [24, 24, 24],
        ],
        dtype=np.uint8,
    )
    lut_lab = _rgb_to_lab(lut_rgb)

    result = match_colors_to_lut(unique_colors, lut_rgb, lut_lab, KDTree(lut_lab))

    assert result.tolist() == [0]


def test_legacy_rybw_lut_keeps_deep_gray_achromatic() -> None:
    lut = load_lut("tests/fixtures/lut_regression/bambulab_pla_basic_rybw.npy", "4-Color (RYBW)")
    unique_colors = np.array([[32, 32, 32]], dtype=np.uint8)

    result = match_colors_to_lut(unique_colors, lut["lut_rgb"], lut["lut_lab"], lut["kdtree"])

    matched_chroma = _lab_to_lch(lut["lut_lab"][result])[:, 1]
    assert matched_chroma[0] <= 8.0
