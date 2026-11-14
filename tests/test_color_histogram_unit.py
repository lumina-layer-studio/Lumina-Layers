"""Exact palette/count equivalence, including transparency and tile edges."""

import numpy as np
import pytest

from core.pipeline.processing_ops import color_histogram


@pytest.mark.parametrize("shape", [(0, 0), (1, 7), (9, 1), (7, 11)])
@pytest.mark.parametrize("visible", [False, True])
@pytest.mark.parametrize("sparse_limit", [3, 65_536])
def test_visible_counts_match_full_rgb_sort(monkeypatch, shape, visible, sparse_limit):
    monkeypatch.setattr(color_histogram, "_COUNT_TILE_EDGE", 4)
    monkeypatch.setattr(color_histogram, "_MAX_SPARSE_COLORS", sparse_limit)
    rng = np.random.default_rng(251113)
    rgb = rng.integers(0, 256, (*shape, 3), dtype=np.uint8)[:, ::-1]
    mask = (rng.random(shape) > 0.3) if visible else np.zeros(shape, dtype=bool)
    expected = np.unique(rgb[mask], axis=0, return_counts=True)
    actual = color_histogram.count_visible_rgb(rgb, mask)
    for got, want in zip(actual, expected):
        np.testing.assert_array_equal(got, want)


def test_palette_weights_accumulate_across_tiles_without_full_canvas_sort(monkeypatch):
    monkeypatch.setattr(color_histogram, "_COUNT_TILE_EDGE", 4)
    rgb = np.full((11, 13, 3), (255, 0, 128), dtype=np.uint8)
    rgb[:, 5:] = (0, 255, 255)
    mask = np.ones(rgb.shape[:2], dtype=bool)
    mask[0] = False
    unique = np.unique

    def bounded_unique(values, **kwargs):
        assert values.ndim == 1
        assert values.size <= 16
        return unique(values, **kwargs)

    monkeypatch.setattr(color_histogram.np, "unique", bounded_unique)
    colors, counts = color_histogram.count_visible_rgb(rgb, mask)
    np.testing.assert_array_equal(colors, [(0, 255, 255), (255, 0, 128)])
    np.testing.assert_array_equal(counts, [80, 50])


def test_preview_palette_keeps_counts_and_tie_order_with_bounded_sort(monkeypatch):
    from core.pipeline.pipeline_utils import extract_color_palette

    monkeypatch.setattr(color_histogram, "_COUNT_TILE_EDGE", 4)
    rgb = np.zeros((12, 12, 3), dtype=np.uint8)
    rgb[:, :6] = (255, 0, 0)
    rgb[:, 6:] = (0, 0, 255)
    mask = np.ones((12, 12), dtype=bool)
    mask[0] = False
    unique = np.unique

    def bounded_unique(values, **kwargs):
        assert values.size <= 16
        return unique(values, **kwargs)

    monkeypatch.setattr(color_histogram.np, "unique", bounded_unique)
    assert extract_color_palette({"matched_rgb": rgb, "mask_solid": mask}) == [
        {"color": (0, 0, 255), "hex": "#0000ff", "count": 66, "percentage": 50.0},
        {"color": (255, 0, 0), "hex": "#ff0000", "count": 66, "percentage": 50.0},
    ]
