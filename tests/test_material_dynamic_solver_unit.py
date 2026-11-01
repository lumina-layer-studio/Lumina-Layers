"""Unit tests for the exact dynamic material candidate engine."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import subprocess
import sys
from functools import partial
from pathlib import Path

import numpy as np
import pytest

import core.material_dynamic_solver as dynamic_solver
from core.material_cache import MaterialSolverCache
from core.material_candidate_cache import MaterialCandidateRuntime
from core.material_dynamic_solver import (
    DynamicCandidateCatalog,
    _delta_e00_numba_scalar,
    _delta_e00_numpy,
    _delta_e00_scalar,
    _search_exact_numpy,
    build_dynamic_candidate_catalog,
    search_dynamic_catalog_exact,
)
from core.material_color_solver import (
    MaterialParams,
    forward_batch_model,
    linear_to_srgb_uint8,
    rgb_to_lab,
)


SHARMA_CIEDE2000_PAIRS = (
    ((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
    ((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
    ((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
    ((50.0000, -1.3802, -84.2814), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -1.1848, -84.8006), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, -0.9009, -85.5211), (50.0000, 0.0000, -82.7485), 1.0000),
    ((50.0000, 0.0000, 0.0000), (50.0000, -1.0000, 2.0000), 2.3669),
    ((50.0000, -1.0000, 2.0000), (50.0000, 0.0000, 0.0000), 2.3669),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0009), 7.1792),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0010), 7.1792),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0011), 7.2195),
    ((50.0000, 2.4900, -0.0010), (50.0000, -2.4900, 0.0012), 7.2195),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0009, -2.4900), 4.8045),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0010, -2.4900), 4.8045),
    ((50.0000, -0.0010, 2.4900), (50.0000, 0.0011, -2.4900), 4.7461),
    ((50.0000, 2.5000, 0.0000), (50.0000, 0.0000, -2.5000), 4.3065),
    ((50.0000, 2.5000, 0.0000), (73.0000, 25.0000, -18.0000), 27.1492),
    ((50.0000, 2.5000, 0.0000), (61.0000, -5.0000, 29.0000), 22.8977),
    ((50.0000, 2.5000, 0.0000), (56.0000, -27.0000, -3.0000), 31.9030),
    ((50.0000, 2.5000, 0.0000), (58.0000, 24.0000, 15.0000), 19.4535),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.1736, 0.5854), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2972, 0.0000), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 1.8634, 0.5757), 1.0000),
    ((50.0000, 2.5000, 0.0000), (50.0000, 3.2592, 0.3350), 1.0000),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
    ((61.2901, 3.7196, -5.3901), (61.4292, 2.2480, -4.9620), 1.8731),
    ((35.0831, -44.1164, 3.7933), (35.0232, -40.0716, 1.5901), 1.8645),
    ((22.7233, 20.0904, -46.6940), (23.0331, 14.9730, -42.5619), 2.0373),
    ((36.4612, 47.8580, 18.3852), (36.2715, 50.5065, 21.2231), 1.4146),
    ((90.8027, -2.0831, 1.4410), (91.1528, -1.6435, 0.0447), 1.4441),
    ((90.9257, -0.5406, -0.9208), (88.6381, -0.8985, -0.7239), 1.5381),
    ((6.7747, -0.2908, -2.4247), (5.8714, -0.0985, -2.2286), 0.6377),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
)


def test_solver_imports_without_numba() -> None:
    script = """
import builtins
real_import = builtins.__import__
def blocked_import(name, *args, **kwargs):
    if name == 'numba' or name.startswith('numba.'):
        raise ImportError('numba intentionally unavailable')
    return real_import(name, *args, **kwargs)
builtins.__import__ = blocked_import
import core.material_dynamic_solver as solver
assert solver._NUMBA_AVAILABLE is False
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_dynamic_solver_module_and_public_api_exist() -> None:
    spec = importlib.util.find_spec("core.material_dynamic_solver")

    assert spec is not None
    module = importlib.import_module("core.material_dynamic_solver")
    for name in (
        "DynamicCandidateCatalog",
        "ExactDynamicSearchResult",
        "build_dynamic_candidate_catalog",
        "search_dynamic_catalog_exact",
        "_delta_e00_scalar",
        "_delta_e00_numpy",
        "_delta_e00_numba_scalar",
        "DynamicMaterialSolverError",
        "DynamicMaterialCandidateError",
        "DynamicMaterialSolveConfig",
        "DynamicMaterialLayerOption",
        "DynamicMaterialColorMatch",
        "DynamicMaterialSolveResult",
        "MaterialLayerBenefitPoint",
        "solve_dynamic_material_colors",
        "build_material_layer_benefit_curve",
        "_search_exact_numpy",
        "_search_exact_numba_kernel",
    ):
        assert hasattr(module, name), name


@pytest.mark.parametrize(("lab1", "lab2", "expected"), SHARMA_CIEDE2000_PAIRS)
def test_delta_e00_implementations_match_sharma_reference_pairs(
    lab1: tuple[float, float, float],
    lab2: tuple[float, float, float],
    expected: float,
) -> None:
    first = np.asarray(lab1, dtype=np.float64)
    second = np.asarray(lab2, dtype=np.float64)

    scalar = _delta_e00_scalar(first, second)
    numpy_value = np.asarray(
        _delta_e00_numpy(first.reshape(1, 3), second.reshape(1, 3))
    ).reshape(-1)[0]
    numba_value = _delta_e00_numba_scalar(first, second)

    assert scalar == pytest.approx(expected, abs=5e-5)
    assert float(numpy_value) == pytest.approx(expected, abs=5e-5)
    assert numba_value == pytest.approx(expected, abs=5e-5)


def test_catalog_deduplicates_exact_rgb_by_shortest_stable_recipe() -> None:
    score_srgb = np.asarray(
        [
            [12, 34, 56],
            [12, 34, 56],
            [12, 34, 56],
            [12, 34, 56],
            [12, 34, 57],
            [12, 34, 57],
        ],
        dtype=np.int64,
    )
    recipes = np.asarray(
        [np.arange(7, dtype=np.int32) + row * 10 for row in range(6)]
    )
    actual_layer_counts = np.asarray([6, 5, 5, 7, 6, 7], dtype=np.int64)

    catalog = build_dynamic_candidate_catalog(
        score_srgb,
        recipes,
        actual_layer_counts,
        max_layer_count=7,
    )

    np.testing.assert_array_equal(
        catalog.score_srgb,
        np.asarray([[12, 34, 56], [12, 34, 57]], dtype=np.uint8),
    )
    assert catalog.score_srgb.dtype == np.uint8
    assert catalog.score_lab.dtype == np.float64
    np.testing.assert_allclose(catalog.score_lab, rgb_to_lab(catalog.score_srgb))
    np.testing.assert_array_equal(catalog.print_recipes, recipes[[1, 4]])
    np.testing.assert_array_equal(catalog.minimum_actual_layer_counts, [5, 6])
    np.testing.assert_array_equal(catalog.max_layer_reachable, [True, True])
    np.testing.assert_array_equal(catalog.source_indices, [1, 4])


def test_catalog_owns_read_only_array_storage() -> None:
    score_srgb = np.asarray([[1, 2, 3]], dtype=np.uint8)
    recipes = np.asarray([[0, 1, 2, 3, 4]], dtype=np.int32)
    catalog = build_dynamic_candidate_catalog(score_srgb, recipes, [5], 5)

    score_srgb[0, 0] = 99
    recipes[0, 0] = 99

    assert catalog.score_srgb[0, 0] == 1
    assert catalog.print_recipes[0, 0] == 0
    for value in (
        catalog.score_srgb,
        catalog.score_lab,
        catalog.print_recipes,
        catalog.minimum_actual_layer_counts,
        catalog.max_layer_reachable,
        catalog.source_indices,
    ):
        assert not value.flags.writeable


@pytest.mark.parametrize(
    ("score_srgb", "recipes", "counts", "max_layers"),
    (
        (np.asarray([1, 2, 3]), np.zeros((1, 5)), [5], 5),
        (np.zeros((1, 4)), np.zeros((1, 5)), [5], 5),
        (np.asarray([[256, 0, 0]]), np.zeros((1, 5)), [5], 5),
        (np.asarray([[1.5, 0, 0]]), np.zeros((1, 5)), [5], 5),
        (np.zeros((1, 3)), np.zeros((2, 5)), [5], 5),
        (np.zeros((1, 3)), np.zeros((1, 4)), [5], 5),
        (np.zeros((1, 3)), np.asarray([[0, 1, 2, 3, 4.5]]), [5], 5),
        (np.zeros((1, 3)), np.asarray([[0, 1, 2, 3, -1]]), [5], 5),
        (np.zeros((1, 3)), np.zeros((1, 5)), [[5]], 5),
        (np.zeros((1, 3)), np.zeros((1, 5)), [4], 5),
        (np.zeros((1, 3)), np.zeros((1, 5)), [6], 5),
        (np.zeros((1, 3)), np.zeros((1, 5)), [5], 4),
        (np.zeros((1, 3)), np.zeros((1, 5)), [5], 11),
    ),
)
def test_catalog_rejects_invalid_rows_and_layer_bounds(
    score_srgb: np.ndarray,
    recipes: np.ndarray,
    counts: object,
    max_layers: int,
) -> None:
    with pytest.raises((TypeError, ValueError)):
        build_dynamic_candidate_catalog(
            score_srgb,
            recipes,
            counts,
            max_layers,
        )


def _make_random_search_fixture() -> tuple[np.ndarray, DynamicCandidateCatalog]:
    rng = np.random.default_rng(20260711)
    random_candidates = rng.integers(0, 256, size=(80, 3), dtype=np.uint8)
    candidates = np.vstack(
        [
            np.asarray(
                [
                    [0, 0, 0],
                    [255, 255, 255],
                    [255, 0, 0],
                    [0, 255, 0],
                    [0, 0, 255],
                    [255, 255, 0],
                ],
                dtype=np.uint8,
            ),
            random_candidates,
        ]
    )
    counts = rng.integers(5, 11, size=candidates.shape[0], dtype=np.int16)
    counts[:6] = np.arange(5, 11, dtype=np.int16)
    recipes = np.broadcast_to(
        np.arange(10, dtype=np.int32),
        (candidates.shape[0], 10),
    ).copy()
    catalog = build_dynamic_candidate_catalog(candidates, recipes, counts, 10)

    targets = np.vstack(
        [
            np.asarray(
                [[0, 0, 0], [255, 255, 255], [255, 0, 255]],
                dtype=np.uint8,
            ),
            rng.integers(0, 256, size=(29, 3), dtype=np.uint8),
        ]
    )
    return targets, catalog


def _brute_force_frontiers(
    targets: np.ndarray,
    catalog: DynamicCandidateCatalog,
    min_layers: int,
    max_layers: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    target_lab = rgb_to_lab(targets).astype(np.float64)
    distances = _delta_e00_numpy(
        target_lab[:, None, :],
        catalog.score_lab[None, :, :],
    )
    cap_count = max_layers - min_layers + 1
    indices = np.full((targets.shape[0], cap_count), -1, dtype=np.int64)
    values = np.full((targets.shape[0], cap_count), np.inf, dtype=np.float64)
    for cap_offset, layer_cap in enumerate(range(min_layers, max_layers + 1)):
        feasible = np.flatnonzero(
            catalog.minimum_actual_layer_counts <= layer_cap
        )
        local = np.argmin(distances[:, feasible], axis=1)
        indices[:, cap_offset] = feasible[local]
        values[:, cap_offset] = distances[
            np.arange(targets.shape[0]),
            indices[:, cap_offset],
        ]
    fixed_indices = np.flatnonzero(catalog.max_layer_reachable)
    fixed_local = np.argmin(distances[:, fixed_indices], axis=1)
    fixed = distances[
        np.arange(targets.shape[0]),
        fixed_indices[fixed_local],
    ]
    return indices, values, fixed


def test_exact_numpy_and_numba_match_exhaustive_random_frontiers() -> None:
    targets, catalog = _make_random_search_fixture()
    expected_indices, expected_values, expected_fixed = _brute_force_frontiers(
        targets,
        catalog,
        5,
        10,
    )

    numpy_result = search_dynamic_catalog_exact(
        targets,
        catalog,
        5,
        10,
        prefer_numba=False,
    )
    numba_result = search_dynamic_catalog_exact(
        targets,
        catalog,
        5,
        10,
        prefer_numba=True,
    )

    assert numpy_result.engine == "numpy"
    assert numba_result.engine == "numba"
    np.testing.assert_array_equal(
        numpy_result.cumulative_best_candidate_indices,
        expected_indices,
    )
    np.testing.assert_array_equal(
        numba_result.cumulative_best_candidate_indices,
        expected_indices,
    )
    np.testing.assert_allclose(
        numpy_result.cumulative_best_delta_e00,
        expected_values,
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        numba_result.cumulative_best_delta_e00,
        expected_values,
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        numpy_result.fixed_max_delta_e00,
        expected_fixed,
        rtol=0.0,
        atol=1e-12,
    )
    np.testing.assert_allclose(
        numba_result.fixed_max_delta_e00,
        expected_fixed,
        rtol=0.0,
        atol=1e-12,
    )


def test_numpy_chunks_keep_global_indices_ties_and_fixed_max_reduction() -> None:
    target_lab = np.asarray(
        [[50.0, 0.0, 0.0], [60.0, 0.0, 0.0]],
        dtype=np.float64,
    )
    candidate_lab = np.asarray(
        [
            [50.0, 10.0, 0.0],
            [50.0, 1.0, 0.0],
            [50.0, 1.0, 0.0],
            [60.0, 0.0, 0.0],
        ],
        dtype=np.float64,
    )

    indices, values, fixed = _search_exact_numpy(
        target_lab,
        candidate_lab,
        np.asarray([5, 5, 5, 6], dtype=np.int16),
        np.asarray([False, False, True, True]),
        5,
        6,
        candidate_chunk_size=2,
    )

    # Candidates 1 and 2 straddle a chunk boundary and are exact ties.
    np.testing.assert_array_equal(indices[0], [1, 1])
    assert values[0, 0] == pytest.approx(
        _delta_e00_scalar(target_lab[0], candidate_lab[1])
    )
    # Candidate 3 is local offset 1 in the second chunk but global index 3.
    assert indices[1, 1] == 3
    assert values[1, 1] == 0.0
    # Fixed-max reduction independently selects global indices 2 and 3.
    np.testing.assert_allclose(
        fixed,
        [
            _delta_e00_scalar(target_lab[0], candidate_lab[2]),
            _delta_e00_scalar(target_lab[1], candidate_lab[3]),
        ],
        rtol=0.0,
        atol=1e-12,
    )


@pytest.mark.parametrize("prefer_numba", [False, True])
def test_exact_search_uses_stable_candidate_index_ties(prefer_numba: bool) -> None:
    target = np.asarray([[10, 10, 10]], dtype=np.uint8)
    tied_lab = np.broadcast_to(rgb_to_lab(target), (2, 3))
    catalog = DynamicCandidateCatalog(
        score_srgb=np.asarray([[10, 10, 10], [11, 11, 11]], dtype=np.uint8),
        score_lab=tied_lab,
        print_recipes=np.zeros((2, 6), dtype=np.int32),
        minimum_actual_layer_counts=np.asarray([6, 5]),
        max_layer_reachable=np.asarray([True, True]),
        source_indices=np.asarray([0, 1]),
    )

    result = search_dynamic_catalog_exact(
        target,
        catalog,
        5,
        6,
        prefer_numba=prefer_numba,
    )

    np.testing.assert_array_equal(
        result.cumulative_best_candidate_indices,
        [[1, 0]],
    )
    np.testing.assert_array_equal(result.cumulative_best_delta_e00, [[0.0, 0.0]])


def test_exact_search_uses_ciede2000_not_cie76_ordering() -> None:
    target = np.asarray([[223, 149, 167]], dtype=np.uint8)
    candidates = np.asarray([[184, 137, 148], [187, 141, 147]], dtype=np.uint8)
    catalog = build_dynamic_candidate_catalog(
        candidates,
        np.zeros((2, 5), dtype=np.int32),
        [5, 5],
        5,
    )
    target_lab = rgb_to_lab(target)[0]
    cie76 = np.linalg.norm(catalog.score_lab - target_lab, axis=1)
    ciede2000 = _delta_e00_numpy(
        np.broadcast_to(target_lab, catalog.score_lab.shape),
        catalog.score_lab,
    )
    assert int(np.argmin(cie76)) == 0
    assert int(np.argmin(ciede2000)) == 1

    result = search_dynamic_catalog_exact(target, catalog, 5, 5, prefer_numba=False)

    assert result.cumulative_best_candidate_indices[0, 0] == 1
    assert result.cumulative_best_delta_e00[0, 0] == pytest.approx(ciede2000[1])


def test_exact_search_does_not_drop_ciede2000_winner_after_cie76_top_4096() -> None:
    """Keep a ΔE00 optimum even when CIE76 would exclude it from Top-4096.

    防止先用 CIE76 取 Top-4096 时丢失真正的 ΔE00 最优候选。
    """
    target = np.asarray([[223, 149, 167]], dtype=np.uint8)
    cie76_decoy = np.asarray([[184, 137, 148]], dtype=np.uint8)
    ciede2000_winner = np.asarray([[187, 141, 147]], dtype=np.uint8)
    target_lab = rgb_to_lab(target)[0]
    decoy_lab = rgb_to_lab(cie76_decoy)[0]
    winner_lab = rgb_to_lab(ciede2000_winner)[0]

    # The catalog is the exact-search seam: use 4,096 distinct source rows
    # that share the CIE76-favoured score, then place the ΔE00 winner just
    # beyond their legacy prefilter boundary.
    source_rows = np.arange(4_097, dtype=np.int64)
    score_srgb = np.column_stack(
        (
            (source_rows >> 8) & 0xFF,
            source_rows & 0xFF,
            np.full(source_rows.size, 1, dtype=np.int64),
        )
    ).astype(np.uint8)
    score_lab = np.repeat(decoy_lab.reshape(1, 3), 4_097, axis=0)
    score_lab[-1] = winner_lab
    catalog = DynamicCandidateCatalog(
        score_srgb=score_srgb,
        score_lab=score_lab,
        print_recipes=np.zeros((4_097, 5), dtype=np.int32),
        minimum_actual_layer_counts=np.full(4_097, 5, dtype=np.int16),
        max_layer_reachable=np.ones(4_097, dtype=bool),
        source_indices=source_rows,
    )

    cie76 = np.linalg.norm(catalog.score_lab - target_lab, axis=1)
    ciede2000 = _delta_e00_numpy(
        np.broadcast_to(target_lab, catalog.score_lab.shape),
        catalog.score_lab,
    )
    legacy_top_4096 = np.argsort(cie76, kind="stable")[:4_096]
    assert 4_096 not in legacy_top_4096
    assert int(np.argmin(ciede2000)) == 4_096

    result = search_dynamic_catalog_exact(target, catalog, 5, 5, prefer_numba=False)

    assert result.cumulative_best_candidate_indices[0, 0] == 4_096
    assert result.fixed_max_delta_e00[0] == pytest.approx(ciede2000[4_096])


def test_search_has_exact_frontier_interface_without_tolerance() -> None:
    signature = inspect.signature(search_dynamic_catalog_exact)

    assert list(signature.parameters) == [
        "target_srgb",
        "catalog",
        "min_layer_count",
        "max_layer_count",
        "prefer_numba",
    ]
    assert signature.parameters["prefer_numba"].default is True
    assert "tolerance" not in signature.parameters


@pytest.mark.parametrize("workers", [1, 3])
def test_exact_search_preserves_target_order_across_worker_counts(
    monkeypatch: pytest.MonkeyPatch,
    workers: int,
) -> None:
    from core.task_parallelism import resolve_task_parallelism_plan

    monkeypatch.setenv("LUMINA_MATERIAL_PARALLELISM", str(workers))
    monkeypatch.setattr(
        dynamic_solver,
        "resolve_task_parallelism_plan",
        partial(resolve_task_parallelism_plan, effective_cpu_capacity=4, outer_demand=1),
    )
    targets, catalog = _make_random_search_fixture()
    # Uneven block lengths and repeated targets catch lost/reordered rows.
    targets = np.tile(targets, (8, 1))[:-5]
    expected = _brute_force_frontiers(targets, catalog, 5, 10)
    result = search_dynamic_catalog_exact(targets, catalog, 5, 10)

    assert result.engine == "numba"
    np.testing.assert_array_equal(result.cumulative_best_candidate_indices, expected[0])
    np.testing.assert_allclose(result.cumulative_best_delta_e00, expected[1], rtol=0, atol=1e-12)
    np.testing.assert_allclose(result.fixed_max_delta_e00, expected[2], rtol=0, atol=1e-12)


@pytest.mark.parametrize(("context", "expected_workers"), [("pool", 2), ("missing", 1), ("nested", 1)])
def test_exact_search_retains_worker_demand_and_nested_limits(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, context: str, expected_workers: int,
) -> None:
    from contextlib import ExitStack
    from core.task_parallelism import resolve_task_parallelism_plan, task_parallelism_worker_scope
    from core.task_parallelism_runtime import OuterDemandPublisher, task_parallelism_runtime_scope

    monkeypatch.delenv("LUMINA_MATERIAL_PARALLELISM", raising=False)
    monkeypatch.setenv("LUMINA_MAX_WORKERS", "4")
    plans = []

    def capture_plan(workload, **kwargs):
        plan = resolve_task_parallelism_plan(workload, **kwargs, effective_cpu_capacity=4)
        plans.append(plan)
        return plan

    monkeypatch.setattr(dynamic_solver, "resolve_task_parallelism_plan", capture_plan)
    targets, catalog = _make_random_search_fixture()
    targets = np.tile(targets, (8, 1))
    with ExitStack() as scopes:
        if context == "pool":
            publisher = OuterDemandPublisher(max_workers=4, parent_dir=tmp_path)
            scopes.callback(publisher.cleanup)
            publisher.increment()
            publisher.increment()
            scopes.enter_context(task_parallelism_runtime_scope(publisher.snapshot_path))
        elif context == "missing":
            scopes.enter_context(task_parallelism_runtime_scope(tmp_path / "missing.json"))
        else:
            scopes.enter_context(task_parallelism_worker_scope())
        result = search_dynamic_catalog_exact(targets, catalog, 5, 10)
    assert result.engine == "numba"
    assert len(plans) == 1 and plans[0].workers == expected_workers
    expected = _brute_force_frontiers(targets, catalog, 5, 10)
    np.testing.assert_array_equal(result.cumulative_best_candidate_indices, expected[0])


def test_concurrent_material_searches_do_not_abort_the_process() -> None:
    script = """
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import numpy as np
from core.material_dynamic_solver import build_dynamic_candidate_catalog, search_dynamic_catalog_exact

rng = np.random.default_rng(90210)
colors = rng.integers(0, 256, size=(20000, 3), dtype=np.uint8)
recipes = rng.integers(0, 4, size=(20000, 10), dtype=np.int32)
counts = rng.integers(5, 11, size=20000, dtype=np.int16)
catalog = build_dynamic_candidate_catalog(colors, recipes, counts, 10)
targets = rng.integers(0, 256, size=(32, 3), dtype=np.uint8)
expected = search_dynamic_catalog_exact(targets, catalog, 5, 10)
assert expected.engine == 'numba'
barrier = Barrier(2)
def search():
    barrier.wait(timeout=10)
    return search_dynamic_catalog_exact(targets, catalog, 5, 10)
with ThreadPoolExecutor(max_workers=2) as pool:
    results = [future.result() for future in [pool.submit(search), pool.submit(search)]]
for result in results:
    assert result.engine == 'numba'
    np.testing.assert_array_equal(result.cumulative_best_candidate_indices, expected.cumulative_best_candidate_indices)
    np.testing.assert_array_equal(result.cumulative_best_delta_e00, expected.cumulative_best_delta_e00)
    np.testing.assert_array_equal(result.fixed_max_delta_e00, expected.fixed_max_delta_e00)
print('concurrent searches complete')
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "NUMBA_THREADING_LAYER": "workqueue", "NUMBA_NUM_THREADS": "2"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "concurrent searches complete" in result.stdout


def test_numba_call_failure_falls_back_to_exact_numpy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets, catalog = _make_random_search_fixture()

    def fail_numba(*_args: object) -> object:
        raise RuntimeError("numba call failed")

    monkeypatch.setattr(dynamic_solver, "_search_exact_numba_kernel", fail_numba)

    fallback = search_dynamic_catalog_exact(
        targets[:2],
        catalog,
        5,
        10,
        prefer_numba=True,
    )
    expected = search_dynamic_catalog_exact(
        targets[:2],
        catalog,
        5,
        10,
        prefer_numba=False,
    )

    assert fallback.engine == "numpy"
    np.testing.assert_array_equal(
        fallback.cumulative_best_candidate_indices,
        expected.cumulative_best_candidate_indices,
    )
    np.testing.assert_allclose(
        fallback.cumulative_best_delta_e00,
        expected.cumulative_best_delta_e00,
    )
    np.testing.assert_allclose(
        fallback.fixed_max_delta_e00,
        expected.fixed_max_delta_e00,
    )


def test_both_engine_failures_raise_typed_core_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets, catalog = _make_random_search_fixture()

    def fail_engine(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("engine failed")

    monkeypatch.setattr(dynamic_solver, "_search_exact_numba_kernel", fail_engine)
    monkeypatch.setattr(dynamic_solver, "_search_exact_numpy", fail_engine)

    with pytest.raises(dynamic_solver.DynamicMaterialSolverError):
        search_dynamic_catalog_exact(
            targets[:1],
            catalog,
            5,
            10,
            prefer_numba=True,
        )


@pytest.mark.parametrize(
    ("target_srgb", "min_layers", "max_layers"),
    (
        (np.asarray([0, 0, 0]), 5, 10),
        (np.zeros((1, 4)), 5, 10),
        (np.asarray([[0, 0, 256]]), 5, 10),
        (np.asarray([[0, 0, 0.5]]), 5, 10),
        (np.zeros((1, 3)), 4, 10),
        (np.zeros((1, 3)), 5, 11),
        (np.zeros((1, 3)), 8, 7),
    ),
)
def test_search_rejects_invalid_targets_and_bounds(
    target_srgb: np.ndarray,
    min_layers: int,
    max_layers: int,
) -> None:
    _, catalog = _make_random_search_fixture()

    with pytest.raises((TypeError, ValueError)):
        search_dynamic_catalog_exact(
            target_srgb,
            catalog,
            min_layers,
            max_layers,
        )


def _task1b_material(name: str, equilibrium: tuple[float, float, float]) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(equilibrium, dtype=np.float64),
        k=np.asarray([8.0, 8.0, 8.0], dtype=np.float64),
        C0_white=np.ones(3, dtype=np.float64),
        estimated_rgb=np.asarray(np.round(np.asarray(equilibrium) * 255), dtype=np.uint8),
    )


def _task1b_runtime(recipes: np.ndarray, layer_count: int) -> MaterialCandidateRuntime:
    rows = int(recipes.shape[0])
    return MaterialCandidateRuntime(
        candidate_recipes=np.asarray(recipes, dtype=np.uint8),
        achieved_srgb=np.full((rows, 3), 255, dtype=np.uint8),
        achieved_lab=np.zeros((rows, 3), dtype=np.float64),
        pinned_mask=np.zeros(rows, dtype=np.bool_),
        metadata={
            "layer_count": layer_count,
            "layer_height_mm": 0.08,
            "substrate": "white",
            "palette_hash": "test",
            "grid_resolution": 8,
        },
    )


@pytest.mark.parametrize(
    "kwargs",
    (
        {"min_layer_count": 4, "max_layer_count": 10, "delta_e00_tolerance": 0.5},
        {"min_layer_count": 8, "max_layer_count": 7, "delta_e00_tolerance": 0.5},
        {"min_layer_count": 5, "max_layer_count": 10, "delta_e00_tolerance": 5.1},
        {"min_layer_count": 5, "max_layer_count": 10, "delta_e00_tolerance": np.nan},
    ),
)
def test_dynamic_solve_config_rejects_invalid_bounds_and_tolerance(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises((TypeError, ValueError)):
        dynamic_solver.DynamicMaterialSolveConfig(**kwargs)


def test_dynamic_solve_prefixes_backing_and_resimulates_full_print_recipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = [
        _task1b_material("Backing", (0.95, 0.95, 0.95)),
        _task1b_material("Blue", (0.05, 0.10, 0.85)),
    ]
    runtimes = {
        5: _task1b_runtime(np.asarray([[1, 1, 1, 1, 1]]), 5),
        6: _task1b_runtime(np.asarray([[0, 0, 0, 0, 0, 0]]), 6),
    }
    monkeypatch.setattr(dynamic_solver, "canonical_palette_order", lambda _m: [0, 1])
    expected_print = np.asarray([[0, 1, 1, 1, 1, 1]], dtype=np.int32)
    target = linear_to_srgb_uint8(
        forward_batch_model(expected_print, materials, 0.08, np.ones(3))
    )

    result = dynamic_solver.solve_dynamic_material_colors(
        target,
        materials,
        backing_material_index=0,
        layer_height_mm=0.08,
        substrate="white",
        config=dynamic_solver.DynamicMaterialSolveConfig(5, 6, 0.0),
        runtime_loader=lambda _m, k, _h, _s: (runtimes[k], k),
    )

    match = result.matches[0]
    assert match.selected.actual_layer_count == 5
    assert match.selected.actual_recipe_bottom_to_top == (1, 1, 1, 1, 1)
    assert match.selected.print_recipe_bottom_to_top == (0, 1, 1, 1, 1, 1)
    assert match.selected.matched_srgb == tuple(int(value) for value in target[0])


def test_dynamic_solve_selects_shortest_cap_on_tolerance_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = [_task1b_material("Only", (0.3, 0.4, 0.5))]
    runtimes = {
        5: _task1b_runtime(np.zeros((1, 5), dtype=np.uint8), 5),
        6: _task1b_runtime(np.zeros((1, 6), dtype=np.uint8), 6),
    }
    monkeypatch.setattr(dynamic_solver, "canonical_palette_order", lambda _m: [0])

    def fake_search(*_args: object, **_kwargs: object) -> dynamic_solver.ExactDynamicSearchResult:
        return dynamic_solver.ExactDynamicSearchResult(
            cumulative_best_candidate_indices=np.asarray([[0, 0]]),
            cumulative_best_delta_e00=np.asarray([[1.5, 1.0]]),
            fixed_max_delta_e00=np.asarray([1.0]),
            engine="numpy",
        )

    monkeypatch.setattr(dynamic_solver, "search_dynamic_catalog_exact", fake_search)
    result = dynamic_solver.solve_dynamic_material_colors(
        np.asarray([[100, 110, 120]], dtype=np.uint8),
        materials,
        backing_material_index=0,
        layer_height_mm=0.08,
        substrate="white",
        config=dynamic_solver.DynamicMaterialSolveConfig(5, 6, 0.5),
        runtime_loader=lambda _m, k, _h, _s: (runtimes[k], None),
    )

    match = result.matches[0]
    assert match.selected.max_effective_layer_count == 5
    assert match.best_range.max_effective_layer_count == 6
    assert match.delta_e00_sacrifice == pytest.approx(0.5)
    assert tuple(option.max_effective_layer_count for option in match.layer_cap_options) == (5, 6)


def test_material_layer_benefit_curve_is_pixel_weighted() -> None:
    option_a5 = dynamic_solver.DynamicMaterialLayerOption(5, 5, (0, 0, 0), (0,) * 5, (0,) * 6, 4.0)
    option_a6 = dynamic_solver.DynamicMaterialLayerOption(6, 6, (0, 0, 0), (0,) * 6, (0,) * 6, 2.0)
    option_b5 = dynamic_solver.DynamicMaterialLayerOption(5, 5, (0, 0, 0), (0,) * 5, (0,) * 6, 1.0)
    option_b6 = dynamic_solver.DynamicMaterialLayerOption(6, 6, (0, 0, 0), (0,) * 6, (0,) * 6, 0.5)
    matches = (
        dynamic_solver.DynamicMaterialColorMatch(
            (1, 2, 3),
            option_a5,
            option_a6,
            2.0,
            2.0,
            (option_a5, option_a6),
        ),
        dynamic_solver.DynamicMaterialColorMatch(
            (4, 5, 6),
            option_b5,
            option_b6,
            0.5,
            0.5,
            (option_b5, option_b6),
        ),
    )

    curve = dynamic_solver.build_material_layer_benefit_curve(matches, [1, 3])

    assert [point.weighted_mean_delta_e00 for point in curve] == pytest.approx([1.75, 0.875])
    assert [point.marginal_delta_e00_reduction for point in curve] == pytest.approx([0.0, 0.875])


def _task1b_legacy_cache(
    recipes: np.ndarray,
    uniform_recipes: np.ndarray,
    layer_count: int,
) -> MaterialSolverCache:
    row_count = int(recipes.shape[0])
    uniform_count = int(uniform_recipes.shape[0])
    return MaterialSolverCache(
        lab_centers=np.zeros((row_count, 3), dtype=np.float32),
        recipes=np.asarray(recipes, dtype=np.uint8),
        achieved_srgb=np.full((row_count, 3), 250, dtype=np.uint8),
        achieved_lab=np.zeros((row_count, 3), dtype=np.float32),
        center_delta_e=np.zeros(row_count, dtype=np.float32),
        uniform_recipes=np.asarray(uniform_recipes, dtype=np.uint8),
        uniform_achieved_srgb=np.full((uniform_count, 3), 251, dtype=np.uint8),
        metadata={
            "layer_count": layer_count,
            "layer_height_mm": 0.08,
            "substrate": "white",
            "palette_hash": "test",
            "grid_resolution": 8,
        },
    )


def test_dynamic_solve_validates_backing_index_before_loading() -> None:
    calls: list[int] = []
    materials = [_task1b_material("Only", (0.2, 0.3, 0.4))]

    with pytest.raises(ValueError, match="backing_material_index"):
        dynamic_solver.solve_dynamic_material_colors(
            np.asarray([[1, 2, 3]], dtype=np.uint8),
            materials,
            backing_material_index=1,
            layer_height_mm=0.08,
            substrate="white",
            config=dynamic_solver.DynamicMaterialSolveConfig(5, 5, 0.5),
            runtime_loader=lambda _m, k, _h, _s: (calls.append(k), None),
        )

    assert calls == []


def test_dynamic_solve_adapts_both_runtime_shapes_maps_canonical_order_and_calls_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = [
        _task1b_material("UserZero", (0.8, 0.1, 0.1)),
        _task1b_material("UserOne", (0.1, 0.1, 0.8)),
    ]
    runtimes = {
        5: _task1b_runtime(np.asarray([[0, 0, 0, 0, 0]]), 5),
        6: _task1b_legacy_cache(
            np.asarray([[0, 0, 0, 0, 0, 0]]),
            np.asarray([[1, 1, 1, 1, 1, 1]]),
            6,
        ),
    }
    load_calls: list[int] = []
    simulated_recipes: list[np.ndarray] = []
    exact_calls = 0
    original_search = dynamic_solver.search_dynamic_catalog_exact
    monkeypatch.setattr(dynamic_solver, "canonical_palette_order", lambda _m: [1, 0])

    def loader(_m: list[MaterialParams], k: int, _h: float, _s: str) -> tuple[object, int]:
        load_calls.append(k)
        return runtimes[k], 8

    def capture_forward(
        recipes: np.ndarray,
        mats: list[MaterialParams],
        height: float,
        substrate_linear: np.ndarray,
    ) -> np.ndarray:
        simulated_recipes.append(np.asarray(recipes).copy())
        return forward_batch_model(recipes, mats, height, substrate_linear)

    def count_search(*args: object, **kwargs: object) -> dynamic_solver.ExactDynamicSearchResult:
        nonlocal exact_calls
        exact_calls += 1
        return original_search(*args, **kwargs)

    monkeypatch.setattr(dynamic_solver, "forward_batch_model", capture_forward)
    monkeypatch.setattr(dynamic_solver, "search_dynamic_catalog_exact", count_search)
    result = dynamic_solver.solve_dynamic_material_colors(
        np.asarray([[20, 20, 180]], dtype=np.uint8),
        materials,
        backing_material_index=0,
        layer_height_mm=0.08,
        substrate="white",
        config=dynamic_solver.DynamicMaterialSolveConfig(5, 6, 0.5),
        runtime_loader=loader,
    )

    assert load_calls == [5, 6]
    assert exact_calls == 1
    assert result.candidate_count_before_dedup == 3
    np.testing.assert_array_equal(simulated_recipes[0], [[0, 1, 1, 1, 1, 1]])
    np.testing.assert_array_equal(
        simulated_recipes[1],
        [[1, 1, 1, 1, 1, 1], [0, 0, 0, 0, 0, 0]],
    )


@pytest.mark.parametrize(
    ("runtime", "expected_phase"),
    (
        (None, "runtime_load"),
        (_task1b_runtime(np.empty((0, 5), dtype=np.uint8), 5), "candidate_recipes"),
        (_task1b_runtime(np.zeros((1, 4), dtype=np.uint8), 5), "candidate_recipes"),
        (_task1b_runtime(np.zeros((1, 5), dtype=np.uint8), 6), "runtime_metadata"),
    ),
)
def test_dynamic_solve_reports_layer_and_phase_for_invalid_runtime(
    runtime: object,
    expected_phase: str,
) -> None:
    materials = [_task1b_material("Only", (0.2, 0.3, 0.4))]

    with pytest.raises(dynamic_solver.DynamicMaterialCandidateError) as caught:
        dynamic_solver.solve_dynamic_material_colors(
            np.asarray([[1, 2, 3]], dtype=np.uint8),
            materials,
            backing_material_index=0,
            layer_height_mm=0.08,
            substrate="white",
            config=dynamic_solver.DynamicMaterialSolveConfig(5, 5, 0.5),
            runtime_loader=lambda _m, _k, _h, _s: (runtime, None),
        )

    assert caught.value.layer_count == 5
    assert caught.value.phase == expected_phase


def test_dynamic_solve_translates_ragged_runtime_recipes_to_candidate_error() -> None:
    materials = [_task1b_material("Only", (0.2, 0.3, 0.4))]
    runtime = MaterialCandidateRuntime(
        candidate_recipes=[[0, 0, 0, 0, 0], [0, 0, 0, 0]],
        achieved_srgb=np.zeros((2, 3), dtype=np.uint8),
        achieved_lab=np.zeros((2, 3), dtype=np.float64),
        pinned_mask=np.zeros(2, dtype=np.bool_),
        metadata={
            "layer_count": 5,
            "layer_height_mm": 0.08,
            "substrate": "white",
            "palette_hash": "test",
            "grid_resolution": 8,
        },
    )

    with pytest.raises(dynamic_solver.DynamicMaterialCandidateError) as caught:
        dynamic_solver.solve_dynamic_material_colors(
            np.asarray([[1, 2, 3]], dtype=np.uint8),
            materials,
            0,
            0.08,
            "white",
            dynamic_solver.DynamicMaterialSolveConfig(5, 5, 0.5),
            runtime_loader=lambda _m, _k, _h, _s: (runtime, None),
        )

    assert caught.value.layer_count == 5
    assert caught.value.phase == "candidate_recipes"


@pytest.mark.parametrize(
    "runtime_layer_count",
    [float("inf"), float("nan"), 5.5, True],
)
def test_dynamic_solve_rejects_invalid_runtime_layer_count_metadata(
    runtime_layer_count: object,
) -> None:
    materials = [_task1b_material("Only", (0.2, 0.3, 0.4))]
    runtime = _task1b_runtime(np.zeros((1, 5), dtype=np.uint8), 5)
    runtime.metadata["layer_count"] = runtime_layer_count

    with pytest.raises(dynamic_solver.DynamicMaterialCandidateError) as caught:
        dynamic_solver.solve_dynamic_material_colors(
            np.asarray([[1, 2, 3]], dtype=np.uint8),
            materials,
            0,
            0.08,
            "white",
            dynamic_solver.DynamicMaterialSolveConfig(5, 5, 0.5),
            runtime_loader=lambda _m, _k, _h, _s: (runtime, None),
        )

    assert caught.value.layer_count == 5
    assert caught.value.phase == "runtime_metadata"


def test_dynamic_solve_reports_full_stack_simulation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = [_task1b_material("Only", (0.2, 0.3, 0.4))]
    runtime = _task1b_runtime(np.zeros((1, 5), dtype=np.uint8), 5)
    monkeypatch.setattr(
        dynamic_solver,
        "forward_batch_model",
        lambda *_args, **_kwargs: np.full((1, 3), np.nan),
    )

    with pytest.raises(dynamic_solver.DynamicMaterialCandidateError) as caught:
        dynamic_solver.solve_dynamic_material_colors(
            np.asarray([[1, 2, 3]], dtype=np.uint8),
            materials,
            0,
            0.08,
            "white",
            dynamic_solver.DynamicMaterialSolveConfig(5, 5, 0.5),
            runtime_loader=lambda _m, _k, _h, _s: (runtime, None),
        )

    assert caught.value.layer_count == 5
    assert caught.value.phase == "full_stack_simulation"


def test_dynamic_solve_tolerance_zero_selects_strict_range_best(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = [
        _task1b_material("Backing", (0.9, 0.9, 0.9)),
        _task1b_material("Color", (0.1, 0.2, 0.8)),
    ]
    runtimes = {
        5: _task1b_runtime(np.ones((1, 5), dtype=np.uint8), 5),
        6: _task1b_runtime(np.ones((1, 6), dtype=np.uint8), 6),
    }
    monkeypatch.setattr(dynamic_solver, "canonical_palette_order", lambda _m: [0, 1])

    def fake_search(*_args: object, **_kwargs: object) -> dynamic_solver.ExactDynamicSearchResult:
        return dynamic_solver.ExactDynamicSearchResult(
            cumulative_best_candidate_indices=np.asarray([[0, 1]]),
            cumulative_best_delta_e00=np.asarray([[1.0000001, 1.0]]),
            fixed_max_delta_e00=np.asarray([1.0]),
            engine="numpy",
        )

    monkeypatch.setattr(dynamic_solver, "search_dynamic_catalog_exact", fake_search)
    result = dynamic_solver.solve_dynamic_material_colors(
        np.asarray([[20, 30, 180]], dtype=np.uint8),
        materials,
        0,
        0.08,
        "white",
        dynamic_solver.DynamicMaterialSolveConfig(5, 6, 0.0),
        runtime_loader=lambda _m, k, _h, _s: (runtimes[k], None),
    )

    assert result.matches[0].selected.max_effective_layer_count == 6
    assert result.matches[0].delta_e00_sacrifice == 0.0


def test_dynamic_solve_rejects_nonfinite_fixed_max_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = [_task1b_material("Only", (0.2, 0.3, 0.4))]
    runtime = _task1b_runtime(np.zeros((1, 5), dtype=np.uint8), 5)

    def fake_search(*_args: object, **_kwargs: object) -> dynamic_solver.ExactDynamicSearchResult:
        return dynamic_solver.ExactDynamicSearchResult(
            cumulative_best_candidate_indices=np.asarray([[0]]),
            cumulative_best_delta_e00=np.asarray([[1.0]]),
            fixed_max_delta_e00=np.asarray([np.inf]),
            engine="numpy",
        )

    monkeypatch.setattr(dynamic_solver, "search_dynamic_catalog_exact", fake_search)
    with pytest.raises(dynamic_solver.DynamicMaterialCandidateError) as caught:
        dynamic_solver.solve_dynamic_material_colors(
            np.asarray([[20, 30, 40]], dtype=np.uint8),
            materials,
            0,
            0.08,
            "white",
            dynamic_solver.DynamicMaterialSolveConfig(5, 5, 0.0),
            runtime_loader=lambda _m, _k, _h, _s: (runtime, None),
        )

    assert caught.value.layer_count == 5
    assert caught.value.phase == "fixed_max_baseline"


@pytest.mark.parametrize("pixel_counts", ([1], [1, 0], [1, -1], [1, 1.5], [1, True]))
def test_material_layer_benefit_curve_rejects_invalid_pixel_counts(
    pixel_counts: list[object],
) -> None:
    option = dynamic_solver.DynamicMaterialLayerOption(5, 5, (0, 0, 0), (0,) * 5, (0,) * 5, 1.0)
    match = dynamic_solver.DynamicMaterialColorMatch(
        (0, 0, 0), option, option, 1.0, 0.0, (option,)
    )

    with pytest.raises((TypeError, ValueError)):
        dynamic_solver.build_material_layer_benefit_curve((match, match), pixel_counts)
