"""Recipe-preserving, bounded cleanup and its structured logging contract."""

from __future__ import annotations

import logging

import numpy as np
import pytest


def _reference_cleanup(materials, rgb, target):
    """Compare complete recipes and choose the first neighbour in a mode tie."""
    from collections import Counter

    outputs = [array.copy() for array in (materials, rgb, target)]
    height, width = materials.shape[:2]
    for y in range(height):
        for x in range(width):
            neighbours = [
                (ny, nx)
                for ny in range(max(0, y - 1), min(height, y + 2))
                for nx in range(max(0, x - 1), min(width, x + 2))
                if (ny, nx) != (y, x)
            ]
            recipes = [tuple(materials[ny, nx]) for ny, nx in neighbours]
            if not recipes or tuple(materials[y, x]) in recipes:
                continue
            chosen = Counter(recipes).most_common(1)[0][0]
            ny, nx = neighbours[recipes.index(chosen)]
            for source, output in zip((materials, rgb, target), outputs):
                output[y, x] = source[ny, nx]
    return outputs[1], outputs[0], outputs[2]


@pytest.mark.parametrize("shape", [(1, 1), (1, 13), (13, 1), (11, 13)])
@pytest.mark.parametrize("layers", [3, 24])
def test_cleanup_matches_recipe_oracle_across_tile_edges(monkeypatch, shape, layers):
    from core import isolated_pixel_cleanup as cleanup

    monkeypatch.setattr(cleanup, "_CLEANUP_TILE_EDGE", 4, raising=False)
    rng = np.random.default_rng(251113)
    palette = rng.integers(-1, 4, (5, layers), dtype=np.int32)
    # Reversed views also exercise non-contiguous material and RGB arrays.
    materials = palette[rng.integers(0, 5, shape)][:, ::-1]
    rgb = rng.integers(0, 256, (*shape, 3), dtype=np.uint8)[:, ::-1]
    target = rng.integers(0, 256, (*shape, 3), dtype=np.uint8)
    originals = [array.copy() for array in (materials, rgb, target)]
    expected = _reference_cleanup(materials, rgb, target)

    actual = cleanup.cleanup_isolated_pixels_with_target_map(materials, rgb, target)

    for got, want in zip(actual, expected):
        np.testing.assert_array_equal(got, want)
    for source, original in zip((materials, rgb, target), originals):
        np.testing.assert_array_equal(source, original)


def test_large_uniform_image_uses_bounded_scratch_without_copying_outputs(monkeypatch):
    from core import isolated_pixel_cleanup as cleanup

    monkeypatch.setattr(cleanup, "_CLEANUP_TILE_EDGE", 8, raising=False)
    encode = cleanup._encode_stacks
    seen = []

    def bounded_encode(matrix, base):
        seen.append(matrix.shape[:2])
        assert matrix.shape[0] <= 10 and matrix.shape[1] <= 10
        return encode(matrix, base)

    monkeypatch.setattr(cleanup, "_encode_stacks", bounded_encode)
    materials = np.zeros((31, 47, 10), dtype=np.int32)
    rgb = np.zeros((31, 47, 3), dtype=np.uint8)
    target = np.full_like(rgb, 19)
    got_rgb, got_materials, got_target = cleanup.cleanup_isolated_pixels_with_target_map(
        materials, rgb, target
    )

    assert len(seen) > 1
    assert got_rgb is rgb
    assert got_materials is materials
    assert got_target is target


def test_deep_recipes_do_not_collide_when_integer_encoding_overflows():
    from core import isolated_pixel_cleanup as cleanup

    materials = np.zeros((3, 3, 65), dtype=np.int32)
    materials[1, 1, 0] = 1  # Differs by 2**64 in the former base-2 encoding.
    rgb = np.zeros((3, 3, 3), dtype=np.uint8)
    rgb[1, 1] = 255
    got_rgb, got_materials = cleanup.cleanup_isolated_pixels(materials, rgb)
    assert not got_materials.any()
    assert not got_rgb.any()


def _build_minimal_inputs():
    """Build a 3x3 RGB image with a single isolated pixel surrounded by uniform color."""
    rgb_arr = np.full((3, 3, 3), 200, dtype=np.uint8)
    rgb_arr[1, 1] = (50, 50, 50)
    material_matrix = np.zeros((3, 3, 1), dtype=np.int32)
    material_matrix[1, 1, 0] = 1
    lut_rgb = np.array([[200, 200, 200], [50, 50, 50]], dtype=np.uint8)
    ref_stacks = np.array([[0], [1]], dtype=np.int32)
    return rgb_arr, material_matrix, lut_rgb, ref_stacks


def test_isolated_pixels_cleaned_omits_merged_count_when_all_merged(caplog, monkeypatch):
    """When every isolated pixel is merged, merged_count must not be present."""
    from core import isolated_pixel_cleanup

    rgb_arr, material_matrix, lut_rgb, ref_stacks = _build_minimal_inputs()
    target_logger = isolated_pixel_cleanup._log
    monkeypatch.setattr(target_logger, "propagate", False)
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=target_logger.name)
    try:
        isolated_pixel_cleanup.cleanup_isolated_pixels(material_matrix, rgb_arr, lut_rgb, ref_stacks)
    finally:
        target_logger.removeHandler(caplog.handler)

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "isolated_pixels_cleaned"
    ]
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "isolated_count") >= 1
    assert getattr(record, "isolated_count") == record.__dict__.get(
        "merged_count", getattr(record, "isolated_count")
    )
    assert "merged_count" not in record.__dict__
