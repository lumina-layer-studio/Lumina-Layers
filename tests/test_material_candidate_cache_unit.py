"""Unit tests for bounded material candidate runtime."""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace

import numpy as np
import pytest

from core.material_candidate_cache import (
    LEGACY_PERSISTED_CANDIDATE_BUDGET,
    MAX_PERSISTED_CANDIDATE_BUDGET,
    MaterialCandidateCacheConfig,
    QUALITY_8M_CANDIDATE_BUDGET,
    RECOMMENDED_PERSISTED_CANDIDATE_BUDGET,
    build_material_candidate_runtime,
)
from core.material_candidate_sampling import generate_candidate_recipes
from core.material_color_solver import (
    MaterialParams,
    forward_model,
    linear_to_srgb_uint8,
)


def _mat(
    name: str,
    E: tuple[float, float, float],
    k: tuple[float, float, float],
) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(E, dtype=np.float64),
        k=np.asarray(k, dtype=np.float64),
        C0_white=np.asarray((1.0, 1.0, 1.0), dtype=np.float64),
        estimated_rgb=np.asarray([int(round(255 * c)) for c in E], dtype=np.uint8),
    )


def _palette(size: int) -> list[MaterialParams]:
    return [
        _mat(
            f"Mat{i:02d}",
            E=(
                0.05 + 0.9 * ((i * 37) % 255) / 255.0,
                0.05 + 0.9 * ((i * 67) % 255) / 255.0,
                0.05 + 0.9 * ((i * 97) % 255) / 255.0,
            ),
            k=(
                0.5 + ((i * 11) % 30) / 5.0,
                0.5 + ((i * 13) % 30) / 5.0,
                0.5 + ((i * 17) % 30) / 5.0,
            ),
        )
        for i in range(size)
    ]


RED = _mat("Red", E=(0.6, 0.05, 0.05), k=(4.0, 4.0, 4.0))
BLUE = _mat("Blue", E=(0.05, 0.1, 0.6), k=(4.0, 4.0, 4.0))
WHITE = _mat("White", E=(0.95, 0.95, 0.95), k=(0.5, 0.5, 0.5))
GREEN = _mat("Green", E=(0.1, 0.6, 0.1), k=(4.0, 4.0, 4.0))
BLACK = _mat("Black", E=(0.05, 0.05, 0.05), k=(6.0, 6.0, 6.0))
SMALL_PALETTE = [RED, BLUE, WHITE]
MEDIUM_PALETTE = [RED, BLUE, WHITE, GREEN, BLACK]


def test_persisted_candidate_identity_change_is_a_miss(tmp_path):
    from core.material_candidate_cache import (
        load_material_candidate_runtime, save_material_candidate_runtime,
    )

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
        config=MaterialCandidateCacheConfig.persisted_for_budget(32),
    )
    path = save_material_candidate_runtime(runtime, cache_root=tmp_path)
    changed = [replace(RED, directory_name="another-red"), BLUE, WHITE]
    assert load_material_candidate_runtime(changed, 5, 0.08, candidate_budget=32,
                                            cache_root=tmp_path) is None
    assert path.exists()


@pytest.mark.parametrize("changes", [
    {"lab_grid_resolution": 128}, {"seed": 19},
    {"candidate_pool_multiplier": 1},
])
def test_candidate_configuration_is_compared_before_reuse(tmp_path, changes):
    from core.material_candidate_cache import (
        load_material_candidate_runtime, save_material_candidate_runtime,
    )

    config = replace(MaterialCandidateCacheConfig.persisted_for_budget(32), **changes)
    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE, layer_count=5, layer_height_mm=0.08, config=config,
    )
    path = save_material_candidate_runtime(runtime, cache_root=tmp_path)
    assert load_material_candidate_runtime(SMALL_PALETTE, 5, 0.08,
                                            candidate_budget=32, cache_root=tmp_path) is None
    loaded = load_material_candidate_runtime(
        SMALL_PALETTE, 5, 0.08, candidate_budget=32,
        cache_root=tmp_path, config=config,
    )
    assert loaded is not None and loaded.cache_id == runtime.cache_id
    np.testing.assert_array_equal(loaded.candidate_recipes, runtime.candidate_recipes)
    baseline = build_material_candidate_runtime(
        materials=SMALL_PALETTE, layer_count=5, layer_height_mm=0.08,
        config=MaterialCandidateCacheConfig.persisted_for_budget(32),
    )
    baseline_path = save_material_candidate_runtime(baseline, cache_root=tmp_path)
    assert baseline_path != path
    default = load_material_candidate_runtime(
        SMALL_PALETTE, 5, 0.08, candidate_budget=32, cache_root=tmp_path,
    )
    assert default is not None and default.cache_id == baseline.cache_id
    assert path.exists()


def test_default_candidate_config_keeps_8gib_build_guard() -> None:
    import core.material_candidate_cache as candidate_cache

    config = MaterialCandidateCacheConfig.default_persisted()
    preview_config = MaterialCandidateCacheConfig.preview_safe()

    assert config.candidate_budget == RECOMMENDED_PERSISTED_CANDIDATE_BUDGET
    assert config.candidate_pool_multiplier == 2
    assert config.batch_recipe_count == 524_288
    assert getattr(candidate_cache, "MAX_PERSISTED_CANDIDATE_BUDGET", 0) == (
        MAX_PERSISTED_CANDIDATE_BUDGET
    )
    assert preview_config.candidate_budget == 1_048_576
    assert preview_config.candidate_pool_multiplier == 1


def test_persisted_candidate_multiplier_scales_down_with_large_budgets() -> None:
    assert (
        MaterialCandidateCacheConfig.persisted_for_budget(
            LEGACY_PERSISTED_CANDIDATE_BUDGET
        ).candidate_pool_multiplier
        == 8
    )
    assert (
        MaterialCandidateCacheConfig.persisted_for_budget(
            QUALITY_8M_CANDIDATE_BUDGET
        ).candidate_pool_multiplier
        == 4
    )
    assert (
        MaterialCandidateCacheConfig.persisted_for_budget(
            RECOMMENDED_PERSISTED_CANDIDATE_BUDGET
        ).candidate_pool_multiplier
        == 2
    )
    assert (
        MaterialCandidateCacheConfig.persisted_for_budget(
            MAX_PERSISTED_CANDIDATE_BUDGET
        ).candidate_pool_multiplier
        == 1
    )
    assert (
        MaterialCandidateCacheConfig(
            candidate_budget=RECOMMENDED_PERSISTED_CANDIDATE_BUDGET
        ).candidate_pool_multiplier
        == 2
    )
    assert (
        MaterialCandidateCacheConfig(
            candidate_budget=MAX_PERSISTED_CANDIDATE_BUDGET
        ).candidate_pool_multiplier
        == 1
    )










def test_sobol_candidate_generation_is_deterministic_and_bounded() -> None:
    first = generate_candidate_recipes(
        material_count=5,
        layer_count=8,
        candidate_budget=128,
        seed=1234,
    )
    second = generate_candidate_recipes(
        material_count=5,
        layer_count=8,
        candidate_budget=128,
        seed=1234,
    )

    np.testing.assert_array_equal(first.recipes, second.recipes)
    assert first.recipes.shape == (128, 8)
    assert first.recipes.dtype == np.uint16
    assert int(first.recipes.min()) >= 0
    assert int(first.recipes.max()) < 5
    assert first.pinned_mask.shape == (128,)


def test_candidate_generation_does_not_request_double_sized_sobol_pool(
    monkeypatch,
) -> None:
    import core.material_candidate_sampling as sampling

    requested_counts: list[int] = []
    original = sampling._low_discrepancy_recipes

    def _recording_low_discrepancy(*args, **kwargs):
        requested_counts.append(int(kwargs["count"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(sampling, "_low_discrepancy_recipes", _recording_low_discrepancy)

    generated = sampling.generate_candidate_recipes(
        material_count=12,
        layer_count=8,
        candidate_budget=4096,
        seed=123,
    )

    assert generated.recipes.shape[0] == 4096
    assert requested_counts
    assert max(requested_counts) <= 4096


def test_uniform_recipes_are_pinned_before_sobol_candidates() -> None:
    generated = generate_candidate_recipes(
        material_count=5,
        layer_count=6,
        candidate_budget=32,
        seed=9,
    )

    expected_uniforms = np.asarray([[i] * 6 for i in range(5)], dtype=np.uint16)
    np.testing.assert_array_equal(generated.recipes[:5], expected_uniforms)
    np.testing.assert_array_equal(generated.pinned_mask[:5], np.ones(5, dtype=bool))


def test_candidate_generation_covers_entire_space_when_budget_allows() -> None:
    generated = generate_candidate_recipes(
        material_count=3,
        layer_count=3,
        candidate_budget=27,
        seed=42,
    )

    all_expected = {
        tuple(recipe)
        for recipe in np.asarray(
            np.meshgrid(
                np.arange(3, dtype=np.uint16),
                np.arange(3, dtype=np.uint16),
                np.arange(3, dtype=np.uint16),
                indexing="ij",
            )
        )
        .reshape(3, -1)
        .T
    }

    assert generated.recipes.shape == (27, 3)
    assert {tuple(recipe) for recipe in generated.recipes} == all_expected


def test_candidate_generation_pins_pair_ramp_and_top_heavy_recipes() -> None:
    generated = generate_candidate_recipes(
        material_count=2,
        layer_count=4,
        candidate_budget=10,
        seed=5,
    )

    recipes = {tuple(recipe) for recipe in generated.recipes}
    assert (0, 0, 0, 1) in recipes
    assert (0, 0, 1, 1) in recipes
    assert (0, 1, 0, 1) in recipes
    assert (1, 1, 1, 0) in recipes
    assert (1, 1, 0, 0) in recipes
    assert (1, 0, 1, 0) in recipes


def test_candidate_generation_pins_multiple_top_heavy_depths() -> None:
    generated = generate_candidate_recipes(
        material_count=2,
        layer_count=6,
        candidate_budget=16,
        seed=5,
    )

    recipes = {tuple(recipe) for recipe in generated.recipes}
    assert (0, 0, 0, 0, 0, 1) in recipes
    assert (0, 0, 0, 0, 1, 1) in recipes
    assert (0, 0, 0, 1, 1, 1) in recipes
    assert (1, 1, 1, 1, 1, 0) in recipes
    assert (1, 1, 1, 1, 0, 0) in recipes
    assert (1, 1, 1, 0, 0, 0) in recipes


def test_candidate_runtime_lookup_returns_solver_cache_shaped_values() -> None:
    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=64, seed=77),
    )

    targets = np.asarray([[180, 80, 60], [40, 70, 180]], dtype=np.uint8)
    matched_rgb, recipes, delta_e = runtime.lookup(targets, SMALL_PALETTE)

    assert runtime.mode == "candidate_hybrid"
    assert runtime.layer_count == 5
    assert runtime.valid_cell_count == 64
    assert matched_rgb.shape == (2, 3)
    assert matched_rgb.dtype == np.uint8
    assert recipes.shape == (2, 5)
    assert recipes.dtype == np.int32
    assert delta_e.shape == (2,)
    assert delta_e.dtype == np.float64


def test_candidate_runtime_lookup_top_k_returns_ranked_suggestions() -> None:
    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=64, seed=77),
    )

    suggestions = runtime.lookup_top_k(
        np.asarray([180, 80, 60], dtype=np.uint8),
        SMALL_PALETTE,
        top_k=5,
        min_spacing=0.0,
    )

    assert 1 <= len(suggestions) <= 5
    assert [item.delta_e for item in suggestions] == sorted(
        item.delta_e for item in suggestions
    )
    for item in suggestions:
        assert item.matched_rgb.shape == (3,)
        assert item.matched_rgb.dtype == np.uint8
        assert item.recipe.shape == (5,)
        assert item.recipe.dtype == np.int32
        assert np.all(item.recipe >= 0)
        assert np.all(item.recipe < len(SMALL_PALETTE))


def test_candidate_runtime_lookup_honors_hue_reranking(monkeypatch) -> None:
    import core.material_candidate_cache as candidate_cache

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=64, seed=77),
    )
    calls = {"count": 0}

    def _rerank_stub(target_lab, candidate_lab, candidate_delta_e, hue_weight):
        calls["count"] += 1
        return np.zeros(target_lab.shape[0], dtype=np.int64)

    monkeypatch.setattr(
        candidate_cache,
        "_hue_aware_rerank",
        _rerank_stub,
        raising=False,
    )

    runtime.lookup(
        np.asarray([[180, 80, 60], [40, 70, 180]], dtype=np.uint8),
        SMALL_PALETTE,
        hue_weight=0.75,
    )

    assert calls["count"] == 1


def test_candidate_runtime_lookup_honors_neighbor_coherence(monkeypatch) -> None:
    import core.material_candidate_cache as candidate_cache

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=64, seed=77),
    )
    calls = {"count": 0}

    def _coherence_stub(**kwargs):
        calls["count"] += 1
        return kwargs["matched_rgb"], kwargs["recipes_user_order"], kwargs["delta_e"]

    monkeypatch.setattr(
        candidate_cache,
        "_neighbor_coherence_refine",
        _coherence_stub,
        raising=False,
    )

    runtime.lookup(
        np.asarray([[180, 80, 60], [185, 82, 62]], dtype=np.uint8),
        SMALL_PALETTE,
        neighbor_coherence=0.8,
    )

    assert calls["count"] == 1


def test_candidate_runtime_neighbor_coherence_uses_local_candidate_pool(
    monkeypatch,
) -> None:
    import core.material_candidate_cache as candidate_cache

    runtime = build_material_candidate_runtime(
        materials=MEDIUM_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(
            candidate_budget=256,
            seed=77,
            enable_inverse_refinement=False,
        ),
    )
    observed_pool_sizes: list[int] = []

    def _coherence_stub(**kwargs):
        observed_pool_sizes.append(int(kwargs["all_lab"].shape[0]))
        return kwargs["matched_rgb"], kwargs["recipes_user_order"], kwargs["delta_e"]

    monkeypatch.setattr(
        candidate_cache,
        "_neighbor_coherence_refine",
        _coherence_stub,
        raising=False,
    )

    runtime.lookup(
        np.asarray([[180, 80, 60], [185, 82, 62]], dtype=np.uint8),
        MEDIUM_PALETTE,
        neighbor_coherence=0.8,
    )

    assert observed_pool_sizes
    assert max(observed_pool_sizes) <= 2 * 64
    assert max(observed_pool_sizes) < runtime.valid_cell_count


def test_candidate_runtime_forwards_parallelism_to_both_refinement_phases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.material_candidate_cache as candidate_cache
    from core.material_inverse_refinement import (
        MaterialInverseRefinementResult,
    )

    runtime = build_material_candidate_runtime(
        materials=MEDIUM_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(
            candidate_budget=128,
            seed=77,
            enable_inverse_refinement=True,
        ),
    )
    observed: dict[str, int] = {}

    def _refinement_stub(**kwargs):
        observed["inverse"] = int(kwargs["parallelism"])
        row_count = kwargs["target_srgb"].shape[0]
        return MaterialInverseRefinementResult(
            matched_srgb=kwargs["baseline_matched_srgb"],
            recipes=kwargs["baseline_recipes"],
            delta_e=kwargs["baseline_delta_e"],
            improved_mask=np.zeros(row_count, dtype=bool),
        )

    def _coherence_stub(**kwargs):
        observed["coherence"] = int(kwargs["parallelism"])
        return (
            kwargs["matched_rgb"],
            kwargs["recipes_user_order"],
            kwargs["delta_e"],
        )

    monkeypatch.setattr(
        candidate_cache,
        "refine_material_matches",
        _refinement_stub,
    )
    monkeypatch.setattr(
        candidate_cache,
        "_neighbor_coherence_refine",
        _coherence_stub,
    )

    runtime.lookup(
        np.asarray([[180, 80, 60], [185, 82, 62]], dtype=np.uint8),
        MEDIUM_PALETTE,
        neighbor_coherence=0.8,
        parallelism=3,
    )

    assert observed == {"inverse": 3, "coherence": 3}


def test_candidate_runtime_uses_candidate_pool_multiplier_for_coverage_selection(
    monkeypatch,
) -> None:
    import core.material_candidate_cache as candidate_cache

    requested_counts: list[int] = []
    original = candidate_cache._low_discrepancy_recipes

    def _recording_low_discrepancy(*args, **kwargs):
        requested_counts.append(int(kwargs["count"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(
        candidate_cache,
        "_low_discrepancy_recipes",
        _recording_low_discrepancy,
    )

    runtime = build_material_candidate_runtime(
        materials=MEDIUM_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(
            candidate_budget=128,
            candidate_pool_multiplier=3,
            batch_recipe_count=16,
            seed=77,
        ),
    )

    assert runtime.valid_cell_count == 128
    assert sum(requested_counts) >= 64
    assert max(requested_counts) <= 16


def test_candidate_runtime_build_uses_streaming_parallel_prediction(
    monkeypatch,
) -> None:
    import core.material_candidate_cache as candidate_cache

    def _forbidden_full_predict(*args, **kwargs):
        raise AssertionError("streaming builder must not use full-array prediction")

    monkeypatch.setattr(
        candidate_cache,
        "_predict_candidate_linear",
        _forbidden_full_predict,
    )

    runtime = build_material_candidate_runtime(
        materials=MEDIUM_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(
            candidate_budget=128,
            candidate_pool_multiplier=2,
            batch_recipe_count=16,
            seed=77,
            enable_inverse_refinement=False,
        ),
    )

    assert runtime.valid_cell_count == 128
    assert runtime.metadata["build_mode"] == "streaming_parallel"
    assert runtime.metadata["build_worker_count"] >= 1


def test_candidate_runtime_exact_space_uses_chunked_prediction(
    monkeypatch,
) -> None:
    import core.material_candidate_cache as candidate_cache

    requested_counts: list[int] = []
    original = candidate_cache._recipe_space_chunk

    def _recording_recipe_space_chunk(*args, **kwargs):
        requested_counts.append(int(kwargs["count"]))
        return original(*args, **kwargs)

    monkeypatch.setattr(
        candidate_cache,
        "_recipe_space_chunk",
        _recording_recipe_space_chunk,
    )

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=4,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(
            candidate_budget=100,
            batch_recipe_count=10,
            build_worker_count=3,
            enable_inverse_refinement=False,
        ),
    )

    assert runtime.valid_cell_count == 81
    assert len(requested_counts) > 1
    assert max(requested_counts) <= 10
    pinned_recipes = runtime.candidate_recipes[runtime.pinned_mask]
    assert pinned_recipes.shape[0] == len(SMALL_PALETTE)
    assert np.all(pinned_recipes == pinned_recipes[:, :1])


def test_candidate_runtime_multi_worker_matches_single_worker() -> None:
    base_config = {
        "candidate_budget": 128,
        "candidate_pool_multiplier": 2,
        "batch_recipe_count": 16,
        "seed": 77,
        "enable_inverse_refinement": False,
    }
    single = build_material_candidate_runtime(
        materials=MEDIUM_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(
            **base_config,
            build_worker_count=1,
        ),
    )
    parallel = build_material_candidate_runtime(
        materials=MEDIUM_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(
            **base_config,
            build_worker_count=4,
        ),
    )

    np.testing.assert_array_equal(parallel.candidate_recipes, single.candidate_recipes)
    np.testing.assert_array_equal(parallel.achieved_srgb, single.achieved_srgb)
    np.testing.assert_allclose(parallel.achieved_lab, single.achieved_lab)
    np.testing.assert_array_equal(parallel.pinned_mask, single.pinned_mask)


def test_candidate_runtime_exact_space_multi_worker_matches_single_worker() -> None:
    base_config = {
        "candidate_budget": 100,
        "batch_recipe_count": 10,
        "seed": 77,
        "enable_inverse_refinement": False,
    }
    single = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=4,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(
            **base_config,
            build_worker_count=1,
        ),
    )
    parallel = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=4,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(
            **base_config,
            build_worker_count=4,
        ),
    )

    np.testing.assert_array_equal(parallel.candidate_recipes, single.candidate_recipes)
    np.testing.assert_array_equal(parallel.achieved_srgb, single.achieved_srgb)
    np.testing.assert_allclose(parallel.achieved_lab, single.achieved_lab)
    np.testing.assert_array_equal(parallel.pinned_mask, single.pinned_mask)


def test_candidate_runtime_rebinds_recipes_to_user_material_order() -> None:
    from core.material_candidate_cache import build_material_candidate_runtime

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=64, seed=88),
    )

    target = np.asarray([[180, 80, 60]], dtype=np.uint8)
    _, original_recipes, _ = runtime.lookup(target, SMALL_PALETTE)
    original_names = [SMALL_PALETTE[index].name for index in original_recipes[0]]

    shuffled = [SMALL_PALETTE[2], SMALL_PALETTE[0], SMALL_PALETTE[1]]
    _, shuffled_recipes, _ = runtime.lookup(target, shuffled)
    shuffled_names = [shuffled[index].name for index in shuffled_recipes[0]]

    assert original_names == shuffled_names


def test_candidate_runtime_inverse_refinement_improves_sparse_baseline() -> None:
    from core.material_candidate_cache import build_material_candidate_runtime

    target_recipe = np.asarray([0, 1, 1, 2], dtype=np.int32)
    target_linear = forward_model(
        target_recipe,
        MEDIUM_PALETTE,
        0.08,
        substrate_linear=np.ones(3, dtype=np.float64),
    )
    target_srgb = linear_to_srgb_uint8(target_linear.reshape(1, 3))

    baseline_runtime = build_material_candidate_runtime(
        materials=MEDIUM_PALETTE,
        layer_count=4,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(
            candidate_budget=5,
            seed=11,
            enable_inverse_refinement=False,
        ),
    )
    refined_runtime = build_material_candidate_runtime(
        materials=MEDIUM_PALETTE,
        layer_count=4,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(
            candidate_budget=5,
            seed=11,
            enable_inverse_refinement=True,
            max_refine_materials=5,
            max_refine_bottom_prefixes=25,
            max_refine_top_suffixes=25,
            refine_bottom_neighbors=2,
        ),
    )

    _, _baseline_recipe, baseline_delta = baseline_runtime.lookup(
        target_srgb,
        MEDIUM_PALETTE,
    )
    refined_rgb, refined_recipe, refined_delta = refined_runtime.lookup(
        target_srgb,
        MEDIUM_PALETTE,
    )

    assert refined_delta[0] < baseline_delta[0]
    np.testing.assert_array_equal(refined_rgb, target_srgb)
    assert refined_recipe.shape == (1, 4)


def test_candidate_cache_file_path_uses_hybrid_budget_stem(tmp_path: Path) -> None:
    from core.material_candidate_cache import candidate_cache_file_path

    path = candidate_cache_file_path(
        SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        candidate_budget=64,
        cache_root=tmp_path,
    )

    assert path.name.startswith("candidate-") and path.suffix == ".npz"
    assert "-g" not in path.stem


def test_candidate_runtime_save_load_roundtrip(tmp_path: Path) -> None:
    from core.material_candidate_cache import load_material_candidate_runtime, save_material_candidate_runtime

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=32, seed=44),
    )

    npz_path = save_material_candidate_runtime(runtime, cache_root=tmp_path)
    loaded = load_material_candidate_runtime(
        SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        candidate_budget=32,
        cache_root=tmp_path,
        config=MaterialCandidateCacheConfig(candidate_budget=32, seed=44),
    )

    assert npz_path.exists()
    assert loaded is not None
    np.testing.assert_array_equal(loaded.candidate_recipes, runtime.candidate_recipes)
    np.testing.assert_array_equal(loaded.achieved_srgb, runtime.achieved_srgb)
    np.testing.assert_array_equal(loaded.achieved_lab, runtime.achieved_lab)
    np.testing.assert_array_equal(loaded.pinned_mask, runtime.pinned_mask)
    assert loaded.metadata["schema_version"] == "3.0"
    assert loaded.metadata["mode"] == "candidate_hybrid"
    assert loaded.metadata["candidate_budget"] == 32
    assert loaded.metadata["candidate_count"] == runtime.valid_cell_count
    assert loaded.metadata["canonical_material_directory_names"] == [
        item["directory_name"] for item in loaded.metadata["canonical_materials"]
    ]
    assert loaded.metadata["candidate_pool_multiplier"] == 8
    assert loaded.metadata["batch_recipe_count"] == 524_288


def test_candidate_runtime_metadata_load_does_not_open_npz_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.material_candidate_cache import (
        load_material_candidate_runtime_metadata,
        save_material_candidate_runtime,
    )

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=32, seed=44),
    )
    npz_path = save_material_candidate_runtime(runtime, cache_root=tmp_path)

    def _fail_np_load(*args, **kwargs):
        raise AssertionError("status metadata path must not load runtime arrays")

    monkeypatch.setattr("core.material_candidate_cache.np.load", _fail_np_load)

    entry = load_material_candidate_runtime_metadata(
        SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        candidate_budget=32,
        cache_root=tmp_path,
        config=MaterialCandidateCacheConfig(candidate_budget=32, seed=44),
    )

    assert entry is not None
    assert entry.metadata["schema_version"] == "3.0"
    assert entry.metadata["mode"] == "candidate_hybrid"
    assert entry.metadata["candidate_count"] == runtime.valid_cell_count
    assert entry.cache_file_size_bytes == npz_path.stat().st_size
    assert entry.cache_file_path == npz_path


def test_candidate_runtime_save_uses_unique_temp_path_per_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.material_candidate_cache import save_material_candidate_runtime

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=32, seed=44),
    )
    original_savez_compressed = np.savez_compressed
    temp_names: list[str] = []

    def _spy_savez_compressed(handle, *args, **kwargs):
        temp_names.append(Path(handle.name).name)
        return original_savez_compressed(handle, *args, **kwargs)

    monkeypatch.setattr(
        "core.material_candidate_cache.np.savez_compressed",
        _spy_savez_compressed,
    )

    save_material_candidate_runtime(runtime, cache_root=tmp_path)
    save_material_candidate_runtime(runtime, cache_root=tmp_path)

    assert len(temp_names) == 2
    assert len(set(temp_names)) == 2


def test_candidate_runtime_keeps_uint8_recipes_for_82_materials(
    tmp_path: Path,
) -> None:
    from core.material_candidate_cache import (
        load_material_candidate_runtime,
        save_material_candidate_runtime,
    )

    palette = _palette(82)
    runtime = build_material_candidate_runtime(
        materials=palette,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(
            candidate_budget=256,
            candidate_pool_multiplier=1,
            batch_recipe_count=32,
            seed=44,
            enable_inverse_refinement=False,
        ),
    )
    assert runtime.candidate_recipes.dtype == np.uint8

    save_material_candidate_runtime(runtime, cache_root=tmp_path)
    loaded = load_material_candidate_runtime(
        palette,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        candidate_budget=256,
        cache_root=tmp_path,
        config=MaterialCandidateCacheConfig(candidate_budget=256, candidate_pool_multiplier=1,
            batch_recipe_count=32, seed=44, enable_inverse_refinement=False),
    )

    assert loaded is not None
    assert loaded.candidate_recipes.dtype == np.uint8
    assert loaded.metadata["recipe_dtype"] == "uint8"


def test_load_candidate_runtime_returns_none_when_absent_or_palette_mismatch(
    tmp_path: Path,
) -> None:
    from core.material_candidate_cache import (
        build_material_candidate_runtime,
        load_material_candidate_runtime,
        save_material_candidate_runtime,
    )

    assert (
        load_material_candidate_runtime(
            SMALL_PALETTE,
            layer_count=5,
            layer_height_mm=0.08,
            substrate="white",
            candidate_budget=32,
            cache_root=tmp_path,
        )
        is None
    )

    runtime = build_material_candidate_runtime(
        materials=SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        config=MaterialCandidateCacheConfig(candidate_budget=32, seed=44),
    )
    save_material_candidate_runtime(runtime, cache_root=tmp_path)
    red_alt = _mat("RedAlt", E=(0.7, 0.05, 0.05), k=(4.0, 4.0, 4.0))
    mismatched_palette = [red_alt, BLUE, WHITE]

    assert (
        load_material_candidate_runtime(
            mismatched_palette,
            layer_count=5,
            layer_height_mm=0.08,
            substrate="white",
            candidate_budget=32,
            cache_root=tmp_path,
        )
        is None
    )


@pytest.mark.parametrize("layer_count", [10, 11])
def test_exact_enumeration_runtime_reloads_after_save(
    tmp_path: Path, layer_count: int
) -> None:
    """Two materials fit the 8192 budget exactly at 10 and 11 layers.

    The 11-layer key carries the layer-wise DP identity even though the
    recipe space is enumerated exactly; save, load and status must agree.
    """
    from core.material_candidate_cache import (
        load_material_candidate_runtime,
        load_material_candidate_runtime_metadata,
        save_material_candidate_runtime,
    )

    palette = _palette(2)
    budget = 8192
    config = MaterialCandidateCacheConfig.persisted_for_budget(budget)
    runtime = build_material_candidate_runtime(
        materials=palette,
        layer_count=layer_count,
        layer_height_mm=0.08,
        substrate="white",
        config=config,
    )
    assert runtime.valid_cell_count == 2 ** layer_count
    assert "layer_dp_build" not in runtime.metadata

    npz_path = save_material_candidate_runtime(runtime, cache_root=tmp_path)
    lookup = dict(
        layer_count=layer_count,
        layer_height_mm=0.08,
        substrate="white",
        candidate_budget=budget,
        cache_root=tmp_path,
    )
    loaded = load_material_candidate_runtime(palette, **lookup)
    entry = load_material_candidate_runtime_metadata(palette, **lookup)

    assert npz_path.exists()
    assert loaded is not None
    np.testing.assert_array_equal(loaded.candidate_recipes, runtime.candidate_recipes)
    assert entry is not None
    assert entry.cache_file_path == npz_path
    assert save_material_candidate_runtime(runtime, cache_root=tmp_path) == npz_path
