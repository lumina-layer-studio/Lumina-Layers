"""Unit tests for the layer-wise DP recipe generator and deep-stack wiring."""

from __future__ import annotations

import itertools

import numpy as np
import pytest

from core.material_candidate_cache import (
    MaterialCandidateCacheConfig,
    _candidate_cache_parameters,
    build_material_candidate_runtime,
)
from core.material_color_solver import (
    MAX_LAYER_COUNT,
    MITM_MAX_LAYER_COUNT,
    MaterialParams,
    forward_batch_model,
    linear_to_srgb_uint8,
    solve_image_colors_optimal,
    suggest_colors_for_target,
)
from core.material_layer_dp import (
    clear_layer_dp_memo,
    generate_layer_dp_recipes,
    generate_layer_dp_recipes_cached,
)


def _mat(name: str, E, k) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(E, dtype=np.float64),
        k=np.asarray(k, dtype=np.float64),
        C0_white=np.ones(3, dtype=np.float64),
        estimated_rgb=linear_to_srgb_uint8(np.asarray([E], dtype=np.float64))[0],
    )


# A translucent CMYW+K palette (absorption in 1/mm) similar to real PLA.
PALETTE = [
    _mat("White", (0.99, 0.99, 0.98), (2.3, 2.7, 3.5)),
    _mat("Cyan", (0.01, 0.40, 0.95), (14.0, 5.2, 3.2)),
    _mat("Magenta", (0.98, 0.04, 0.36), (5.2, 20.0, 11.7)),
    _mat("Yellow", (0.99, 0.98, 0.01), (3.3, 4.0, 19.3)),
    _mat("Black", (0.05, 0.05, 0.05), (67.0, 66.0, 61.0)),
]


def _brute_force_linear(materials, layer_count, height):
    recipes = np.asarray(
        list(itertools.product(range(len(materials)), repeat=layer_count)),
        dtype=np.int64,
    )
    return recipes, forward_batch_model(recipes, materials, height)


def _lab(linear):
    # Float Lab (no uint8 rounding) so the test measures merge error only.
    from core.material_layer_dp import _linear_to_lab

    return _linear_to_lab(np.clip(linear, 0.0, 1.0)).astype(np.float64)


def test_reported_colours_are_exact_forward_model_colours():
    result = generate_layer_dp_recipes(PALETTE, 9, 0.04)
    assert result.recipes.shape[1] == 9
    expected = np.clip(
        forward_batch_model(result.recipes.astype(np.int64), PALETTE, 0.04), 0.0, 1.0
    )
    np.testing.assert_allclose(result.linear_rgb, expected, atol=1e-12)


@pytest.mark.parametrize("substrate", ["white", "black"])
def test_dp_covers_the_exhaustive_gamut(substrate):
    """Every exhaustively reachable colour has a DP recipe within 1 ΔE76."""
    from scipy.spatial import cKDTree

    layers, height = 7, 0.08
    _recipes, brute = _brute_force_linear(PALETTE, layers, height)
    if substrate == "black":
        brute_recipes = _recipes
        brute = forward_batch_model(brute_recipes, PALETTE, height, np.zeros(3))
    result = generate_layer_dp_recipes(PALETTE, layers, height, substrate)
    assert result.recipes.shape[0] < brute.shape[0]  # actually merged
    distance, _ = cKDTree(_lab(result.linear_rgb)).query(_lab(brute))
    assert distance.max() <= 1.0
    assert distance.mean() <= 0.25


def test_switch_counts_match_recipes_and_prefer_fewer_changes():
    result = generate_layer_dp_recipes(PALETTE, 8, 0.04)
    recipes = result.recipes.astype(np.int64)
    recount = np.count_nonzero(recipes[:, 1:] != recipes[:, :-1], axis=1)
    np.testing.assert_array_equal(result.switch_counts, recount)
    # Pure single-material stacks need zero switches and must survive.
    for index in range(len(PALETTE)):
        uniform = np.full(8, index)
        assert np.any(np.all(recipes == uniform, axis=1))


def test_max_states_coarsens_cell_and_respects_bound():
    fine = generate_layer_dp_recipes(PALETTE, 10, 0.04)
    capped = generate_layer_dp_recipes(PALETTE, 10, 0.04, max_states=5_000)
    assert max(capped.states_per_layer) <= 5_000
    assert capped.state_cell_lab > fine.state_cell_lab
    assert capped.recipes.shape[0] < fine.recipes.shape[0]


def test_thirty_layers_is_tractable():
    result = generate_layer_dp_recipes(PALETTE, 30, 0.04, max_states=200_000)
    assert result.recipes.shape == (result.recipes.shape[0], 30)
    assert 1_000 < result.recipes.shape[0] <= 200_000
    assert len(result.states_per_layer) == 30


def test_memo_returns_same_object():
    clear_layer_dp_memo()
    first = generate_layer_dp_recipes_cached(PALETTE, 12, 0.04, max_states=50_000)
    second = generate_layer_dp_recipes_cached(PALETTE, 12, 0.04, max_states=50_000)
    assert first is second
    clear_layer_dp_memo()


def test_candidate_runtime_uses_layer_dp_for_deep_stacks():
    config = MaterialCandidateCacheConfig(
        candidate_budget=60_000, candidate_pool_multiplier=1
    )
    runtime = build_material_candidate_runtime(
        materials=PALETTE, layer_count=20, layer_height_mm=0.04, config=config
    )
    assert runtime.metadata["layer_dp"] == {"state_cell_lab": 0.5}
    assert runtime.metadata["layer_dp_build"]["algorithm"] == "layer_dp"
    assert runtime.candidate_recipes.shape[1] == 20
    targets = np.asarray([[230, 190, 160], [40, 90, 160], [250, 250, 250]], np.uint8)
    matched, recipes, delta_e = runtime.lookup(targets, PALETTE)
    assert recipes.shape == (3, 20)
    predicted = linear_to_srgb_uint8(
        np.clip(forward_batch_model(recipes, PALETTE, 0.04), 0.0, 1.0)
    )
    np.testing.assert_array_equal(predicted, matched)
    assert np.all(np.isfinite(delta_e))


def test_shallow_stacks_keep_their_cache_identity():
    """<=10 layers must not change persisted candidate cache keys."""
    config = MaterialCandidateCacheConfig.persisted_for_budget(1_048_576)
    shallow = _candidate_cache_parameters(PALETTE, 10, 0.08, "white", 1_048_576, config)
    deep = _candidate_cache_parameters(PALETTE, 11, 0.08, "white", 1_048_576, config)
    assert "layer_dp" not in shallow
    assert deep["layer_dp"] == {"state_cell_lab": 0.5}


def test_layer_caps():
    assert MAX_LAYER_COUNT == 30
    assert MITM_MAX_LAYER_COUNT == 10
    target = np.asarray([[120, 120, 120]], np.uint8)
    with pytest.raises(ValueError, match="candidate runtime"):
        solve_image_colors_optimal(target, PALETTE, layer_count=11, layer_height_mm=0.04)
    with pytest.raises(ValueError, match="candidate runtime"):
        suggest_colors_for_target(target[0], PALETTE, layer_count=11, layer_height_mm=0.04)
