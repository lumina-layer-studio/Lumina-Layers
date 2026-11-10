"""Tests for replaying preview-time spatial edits on a fresh-size analysis."""

from __future__ import annotations

import numpy as np
import pytest

from core.edit_projection import EditProjectionGrid
from core.recipe_order import pad_material_matrix_layers


@pytest.mark.parametrize("layer_order", ["Top2Bottom", "Bottom2Top"])
@pytest.mark.parametrize("output_layers", [2, 4])
def test_material_replay_aligns_backing_without_overwriting_fresh_analysis(layer_order: str, output_layers: int) -> None:
    grid = EditProjectionGrid((2, 2), (4, 4))
    source_solid = np.array([[True, True], [True, False]])
    target_solid = source_solid.repeat(2, axis=0).repeat(2, axis=1)
    pristine = np.ones((2, 2, 2), dtype=np.int16)
    pristine[~source_solid] = -1
    edited = pad_material_matrix_layers(pristine, 3, 2, layer_order, source_solid)
    edited[0, 0] = [3, 0, 1] if layer_order == "Top2Bottom" else [1, 0, 3]
    fresh = np.full((4, 4, 2), 4, dtype=np.int16)
    fresh[~target_solid] = -1

    result, changed = grid.replay_materials(
        edited, pristine, fresh, source_solid=source_solid, target_solid=target_solid,
        base_channel_idx=2, layer_order=layer_order, target_layers=output_layers,
    )

    expected = pad_material_matrix_layers(fresh, output_layers, 2, layer_order, target_solid)
    recipe = [3, 0] if output_layers == 2 else [3, 0, 1, 2]
    expected[:2, :2] = recipe if layer_order == "Top2Bottom" else recipe[::-1]
    np.testing.assert_array_equal(result, expected)
    expected_mask = np.zeros((4, 4), dtype=bool)
    expected_mask[:2, :2] = True
    np.testing.assert_array_equal(changed, expected_mask)


def test_equal_grid_projection_is_identity() -> None:
    values = np.arange(12, dtype=np.int16).reshape(3, 4)

    projected = EditProjectionGrid((3, 4), (3, 4)).project(values)

    np.testing.assert_array_equal(projected, values)


def test_growing_grid_uses_pixel_center_nearest_sampling() -> None:
    values = np.array([[1, 2], [3, 4]], dtype=np.uint8)

    projected = EditProjectionGrid((2, 2), (4, 4)).project(values)

    np.testing.assert_array_equal(
        projected,
        np.array(
            [
                [1, 1, 2, 2],
                [1, 1, 2, 2],
                [3, 3, 4, 4],
                [3, 3, 4, 4],
            ],
            dtype=np.uint8,
        ),
    )


def test_shrinking_grid_uses_pixel_center_nearest_sampling() -> None:
    values = np.arange(16, dtype=np.uint8).reshape(4, 4)

    projected = EditProjectionGrid((4, 4), (2, 2)).project(values)

    np.testing.assert_array_equal(projected, values[np.ix_([1, 3], [1, 3])])


def test_projection_preserves_trailing_value_axes() -> None:
    values = np.arange(3 * 5 * 4, dtype=np.int16).reshape(3, 5, 4)
    grid = EditProjectionGrid((3, 5), (5, 8))

    projected = grid.project(values)

    assert projected.shape == (5, 8, 4)
    np.testing.assert_array_equal(projected[0, 0], values[0, 0])
    np.testing.assert_array_equal(projected[-1, -1], values[-1, -1])


def test_r4c1_capped_grid_projection_stays_bounded() -> None:
    source_shape = (2407, 1110)
    target_width = 1600
    target_shape = (
        round(source_shape[0] * target_width / source_shape[1]),
        target_width,
    )
    source_mask = np.zeros(source_shape, dtype=bool)
    source_mask[1200, 555] = True

    projected = EditProjectionGrid(source_shape, target_shape).project_mask(
        source_mask
    )

    assert projected.shape == target_shape
    assert projected.dtype == np.bool_
    assert np.any(projected)


def test_projected_change_mask_excludes_untouched_and_non_solid_pixels() -> None:
    pristine = np.zeros((2, 2, 3), dtype=np.uint8)
    edited = pristine.copy()
    edited[0, 0] = [255, 0, 0]
    edited[1, 1] = [0, 255, 0]
    source_solid = np.array([[True, True], [True, False]], dtype=bool)
    target_solid = np.ones((4, 4), dtype=bool)
    grid = EditProjectionGrid((2, 2), (4, 4))

    changed = grid.project_change_mask(
        edited,
        pristine,
        source_solid=source_solid,
        target_solid=target_solid,
    )

    expected = np.zeros((4, 4), dtype=bool)
    expected[:2, :2] = True
    np.testing.assert_array_equal(changed, expected)


def test_sampling_only_changed_targets_avoids_full_value_projection() -> None:
    values = np.arange(2 * 3 * 2, dtype=np.int16).reshape(2, 3, 2)
    grid = EditProjectionGrid((2, 3), (4, 6))
    target_mask = np.zeros((4, 6), dtype=bool)
    target_mask[0, 0] = True
    target_mask[3, 5] = True

    sampled = grid.sample_target_mask(values, target_mask)

    np.testing.assert_array_equal(sampled, np.stack([values[0, 0], values[1, 2]]))


@pytest.mark.parametrize(
    ("source_shape", "target_shape"),
    [((0, 2), (2, 2)), ((2, -1), (2, 2)), ((2, 2), (0, 2))],
)
def test_empty_or_negative_grids_fail_closed(
    source_shape: tuple[int, int],
    target_shape: tuple[int, int],
) -> None:
    with pytest.raises(ValueError, match="positive"):
        EditProjectionGrid(source_shape, target_shape)


def test_projection_rejects_a_different_source_grid() -> None:
    grid = EditProjectionGrid((2, 3), (4, 6))

    with pytest.raises(ValueError, match="source grid"):
        grid.project(np.zeros((3, 2), dtype=bool))
