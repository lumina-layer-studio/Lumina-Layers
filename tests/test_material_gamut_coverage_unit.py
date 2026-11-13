"""Unit tests for sRGB gamut coverage of material combinations.

耗材组合 sRGB 色域覆盖率的单元测试。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import core.material_gamut_coverage as gamut
from core.material_cache_overview import describe_fixed_layer_caches
from core.material_candidate_cache import (
    MaterialCandidateCacheConfig,
    build_material_candidate_runtime,
    save_material_candidate_runtime,
)
from core.material_color_solver import MaterialParams
from core.material_cache import build_material_solver_cache, save_material_solver_cache


def _mat(name: str, e: tuple[float, float, float], k: float) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(e, dtype=np.float64),
        k=np.asarray((k, k, k), dtype=np.float64),
        C0_white=np.ones(3, dtype=np.float64),
        estimated_rgb=np.asarray([int(round(255 * c)) for c in e], dtype=np.uint8),
    )


def _palette() -> list[MaterialParams]:
    return [
        _mat("White", (0.95, 0.95, 0.95), 0.5),
        _mat("Red", (0.70, 0.05, 0.05), 4.0),
        _mat("Blue", (0.05, 0.10, 0.70), 4.0),
    ]


def _all_srgb_corners_and_grays() -> np.ndarray:
    values = np.arange(0, 256, 17, dtype=np.uint8)
    grid = np.stack(np.meshgrid(values, values, values, indexing="ij"), axis=-1)
    return grid.reshape(-1, 3)


def test_reference_cells_cover_every_srgb_color() -> None:
    reference = gamut.srgb_reference_cell_keys()

    assert reference.flags.writeable is False
    assert np.all(np.diff(reference) > 0)
    sample_keys = gamut._cell_keys(
        gamut.rgb_to_lab(_all_srgb_corners_and_grays()), gamut.SRGB_COVERAGE_CELL_SIZE
    )
    assert np.all(np.isin(sample_keys, reference))


def test_coverage_of_empty_single_and_full_color_sets() -> None:
    reference_count = int(gamut.srgb_reference_cell_keys().shape[0])

    empty = gamut.measure_srgb_coverage(np.zeros((0, 3), dtype=np.uint8))
    single = gamut.measure_srgb_coverage(np.asarray([[200, 30, 30]] * 5, dtype=np.uint8))

    assert (empty.reached_cell_count, empty.percent) == (0, 0.0)
    assert single.reached_cell_count == 1
    assert single.reference_cell_count == reference_count


def test_full_srgb_cube_reaches_one_hundred_percent() -> None:
    channel = np.arange(256, dtype=np.uint8)
    green, blue = np.meshgrid(channel, channel, indexing="ij")
    slices = []
    for red in range(0, 256):
        block = np.empty((green.size, 3), dtype=np.uint8)
        block[:, 0] = red
        block[:, 1] = green.ravel()
        block[:, 2] = blue.ravel()
        slices.append(np.unique(gamut._cell_keys(gamut.rgb_to_lab(block), 5.0)))
    reached = np.unique(np.concatenate(slices))

    assert reached.shape[0] == gamut.srgb_reference_cell_keys().shape[0]


def test_smallest_cell_size_keeps_keys_collision_free() -> None:
    corners = np.asarray(
        [[0, 0, 0], [255, 255, 255], [255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 0, 255]],
        dtype=np.uint8,
    )
    lab = gamut.rgb_to_lab(corners)
    indices = np.floor(lab / gamut.MIN_COVERAGE_CELL_SIZE).astype(np.int64)

    assert np.all(np.abs(indices) < gamut._CELL_INDEX_OFFSET)
    assert np.unique(gamut._cell_keys(lab, gamut.MIN_COVERAGE_CELL_SIZE)).shape[0] == len(corners)


def test_coverage_is_monotonic_under_color_set_inclusion() -> None:
    rng = np.random.default_rng(7)
    colors = rng.integers(0, 256, (4000, 3)).astype(np.uint8)

    smaller = gamut.measure_srgb_coverage(colors[:1000])
    larger = gamut.measure_srgb_coverage(colors)

    assert smaller.reached_cell_count <= larger.reached_cell_count


@pytest.mark.parametrize("cell_size", [0.0, -1.0, 0.1, float("nan")])
def test_reference_rejects_invalid_cell_size(cell_size: float) -> None:
    with pytest.raises(ValueError):
        gamut.srgb_reference_cell_keys(cell_size)


def test_fixed_gamut_prefers_saved_smart_cache(tmp_path: Path) -> None:
    materials = _palette()
    quick = gamut.compute_fixed_layer_gamut(materials, 5, 0.08, "white", cache_root=tmp_path)
    assert quick.source.kind == gamut.ColorSourceKind.QUICK_SAMPLE
    assert quick.source.is_complete is True

    runtime = build_material_candidate_runtime(
        materials=materials,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig.persisted_for_budget(4_194_304),
    )
    save_material_candidate_runtime(runtime, cache_root=tmp_path)

    saved = gamut.compute_fixed_layer_gamut(materials, 5, 0.08, "white", cache_root=tmp_path)
    assert saved.source.kind == gamut.ColorSourceKind.SAVED_SMART_CACHE
    assert saved.source.candidate_budget == 4_194_304
    assert saved.source.was_cached is True
    assert describe_fixed_layer_caches(
        materials, 5, 0.08, "white", cache_root=tmp_path
    ).saved_runtime_budgets == (4_194_304,)


def test_dynamic_layer_caps_are_cumulative(tmp_path: Path) -> None:
    result = gamut.compute_dynamic_layer_gamut(
        _palette(), 0, 0.08, "white", 5, 7, cache_root=tmp_path
    )

    assert [cap.layer_count for cap in result.layer_cap_coverage] == [5, 6, 7]
    reached = [cap.coverage.reached_cell_count for cap in result.layer_cap_coverage]
    assert reached == sorted(reached)
    assert result.coverage == result.layer_cap_coverage[-1].coverage
    assert result.source.kind == gamut.ColorSourceKind.DYNAMIC_CATALOG
    assert result.source.was_cached is False
    overview = gamut.describe_dynamic_layer_caches(
        _palette(), 0, 0.08, "white", 5, 7, cache_root=tmp_path,
    )
    assert overview.saved_layer_counts == (5, 6, 7)
    assert gamut.compute_dynamic_layer_gamut(
        _palette(), 0, 0.08, "white", 5, 7, cache_root=tmp_path,
    ).source.was_cached is True


@pytest.mark.parametrize("layer_count,complete", [(5, True), (6, False)])
def test_exhaustive_gamut_preserves_pure_stacks_and_reports_bucketed_approximation(
    tmp_path: Path, layer_count: int, complete: bool,
) -> None:
    materials = _palette()
    cache = build_material_solver_cache(
        materials=materials, layer_count=layer_count, layer_height_mm=0.08,
        substrate="white", grid_resolution=64,
    )
    save_material_solver_cache(cache, cache_root=tmp_path)

    result = gamut.compute_fixed_layer_gamut(materials, layer_count, 0.08, cache_root=tmp_path)
    expected_colors = np.unique(np.concatenate((cache.achieved_srgb, cache.uniform_achieved_srgb)), axis=0)
    assert result.source.is_complete is complete
    assert result.source.kind == gamut.ColorSourceKind.EXHAUSTIVE_CACHE
    assert result.color_count == len(expected_colors)
    assert result.accuracy == gamut.measure_match_accuracy(expected_colors)


def test_contributions_single_material_palette_drops_to_zero() -> None:
    result = gamut.compute_material_contributions([_palette()[1]], 5, 0.08, "white")

    assert len(result.contributions) == 1
    only = result.contributions[0]
    assert only.coverage_without.reached_cell_count == 0
    assert only.drop_percent == result.baseline.percent
    assert only.accuracy_without.darkest_lightness is None
    assert (only.largest_loss_group, only.largest_loss_delta_e) == (None, None)


def test_contributions_exact_palette_never_increase_coverage() -> None:
    result = gamut.compute_material_contributions(_palette(), 5, 0.08, "white")

    assert result.is_complete is True
    assert all(item.drop_percent >= 0 for item in result.contributions)
    assert [item.material_index for item in result.contributions] == [0, 1, 2]


def test_color_groups_classify_reference_colors() -> None:
    colors = np.asarray(
        [[0, 0, 0], [255, 255, 255], [128, 128, 128], [224, 172, 140], [255, 0, 0]],
        dtype=np.uint8,
    )
    masks = gamut.color_group_masks(gamut.rgb_to_lab(colors))

    assert set(masks) == set(gamut.COLOR_GROUPS)
    assert masks[gamut.ColorGroup.NEUTRAL].tolist() == [True, True, True, False, False]
    assert masks[gamut.ColorGroup.DARK].tolist() == [True, False, False, False, False]
    assert masks[gamut.ColorGroup.SKIN].tolist() == [False, False, False, True, False]
    assert masks[gamut.ColorGroup.VIVID].tolist() == [False, False, False, False, True]
    assert masks[gamut.ColorGroup.ALL].all()


def test_match_accuracy_is_zero_when_every_target_is_printable() -> None:
    steps = np.unique(np.append(np.arange(0, 256, gamut.ACCURACY_TARGET_STEP), 255))
    targets = np.stack(np.meshgrid(steps, steps, steps, indexing="ij"), -1).reshape(-1, 3)

    accuracy = gamut.measure_match_accuracy(targets.astype(np.uint8))

    assert [entry.group for entry in accuracy.groups] == list(gamut.COLOR_GROUPS)
    assert all(entry.mean_delta_e == pytest.approx(0.0, abs=1e-6) for entry in accuracy.groups)
    assert accuracy.groups[0].target_count == targets.shape[0]
    assert accuracy.darkest_lightness == pytest.approx(0.0, abs=0.1)
    assert accuracy.lightest_lightness == pytest.approx(100.0, abs=0.1)


def test_match_accuracy_of_empty_set_reports_no_values() -> None:
    accuracy = gamut.measure_match_accuracy(np.zeros((0, 3), dtype=np.uint8))

    assert all(entry.mean_delta_e is None for entry in accuracy.groups)
    assert all(entry.target_count > 0 for entry in accuracy.groups)
    assert (accuracy.darkest_lightness, accuracy.lightest_lightness) == (None, None)


def test_match_accuracy_penalizes_missing_dark_colors() -> None:
    light_only = np.asarray([[255, 255, 255], [200, 60, 60], [60, 60, 200], [190, 190, 190]], np.uint8)
    with_black = np.vstack([light_only, [[10, 10, 10], [60, 60, 60]]]).astype(np.uint8)

    without = gamut.measure_match_accuracy(light_only)
    with_dark = gamut.measure_match_accuracy(with_black)

    assert with_dark.mean_for(gamut.ColorGroup.DARK) < without.mean_for(gamut.ColorGroup.DARK)
    assert with_dark.mean_for(gamut.ColorGroup.NEUTRAL) < without.mean_for(gamut.ColorGroup.NEUTRAL)
    assert with_dark.darkest_lightness < without.darkest_lightness


def test_contributions_flag_black_by_dark_and_neutral_loss() -> None:
    materials = [*_palette(), _mat("Black", (0.03, 0.03, 0.03), 6.0)]

    result = gamut.compute_material_contributions(materials, 5, 0.08, "white")

    black = result.contributions[3]
    assert black.largest_loss_group in {gamut.ColorGroup.DARK, gamut.ColorGroup.NEUTRAL}
    assert black.largest_loss_delta_e is not None and black.largest_loss_delta_e > 3.0
    assert black.accuracy_without.darkest_lightness > result.baseline_accuracy.darkest_lightness + 10
