"""Exactness tests for bounded material-neighbor coherence helpers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any
from weakref import ReferenceType, ref

import numpy as np
import pytest
from scipy.spatial.distance import cdist

import core.material_cache as material_cache_module
from core.material_cache import (
    _find_neighbor_pairs,
    _neighbor_coherence_refine,
    _top_k_candidate_rows_blockwise,
)
from core.material_color_solver import rgb_to_lab


def test_real_vector_norm_matches_numpy_bitwise() -> None:
    rng = np.random.default_rng(20260801)
    random_vectors = rng.normal(size=(512, 3)).astype(np.float64)
    edge_vectors = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, -2.0, 3.5],
            [-0.0, 0.0, -0.0],
            [1.0e-150, -2.0e-150, 3.0e-150],
            [1.0e150, -2.0e150, 3.0e150],
        ],
        dtype=np.float64,
    )
    vectors = np.concatenate((edge_vectors, random_vectors), axis=0)

    expected_bits = np.asarray(
        [np.linalg.norm(vector) for vector in vectors],
        dtype=np.float64,
    ).view(np.uint64)
    actual_bits = np.asarray(
        [
            material_cache_module._real_vector_norm(vector)
            for vector in vectors
        ],
        dtype=np.float64,
    ).view(np.uint64)

    np.testing.assert_array_equal(actual_bits, expected_bits)


def test_neighbor_pair_distances_match_source_norm_bitwise() -> None:
    rng = np.random.default_rng(20260801)
    lab_like_targets = rng.normal(
        loc=np.asarray([50.0, 0.0, 0.0]),
        scale=np.asarray([18.0, 35.0, 35.0]),
        size=(41, 3),
    ).astype(np.float64)
    edge_targets = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [-0.0, 0.0, -0.0],
            [1.0e-150, -2.0e-150, 3.0e-150],
            [-1.0e-150, 2.0e-150, -3.0e-150],
            [1.0e150, -2.0e150, 3.0e150],
            [-1.0e150, 2.0e150, -3.0e150],
        ],
        dtype=np.float64,
    )

    for targets, threshold in (
        (lab_like_targets, 20.0),
        (edge_targets, 1.0e151),
    ):
        yielded = list(
            material_cache_module._iter_neighbor_pairs_with_distances(
                targets,
                threshold=threshold,
            )
        )
        actual_pairs = np.asarray(
            [(row, column) for row, column, _distance in yielded],
            dtype=np.intp,
        ).reshape(-1, 2)
        expected_pairs = _legacy_neighbor_pairs(targets, threshold)
        actual_bits = np.asarray(
            [distance for _row, _column, distance in yielded],
            dtype=np.float64,
        ).view(np.uint64)
        expected_bits = np.asarray(
            [
                material_cache_module._real_vector_norm(
                    targets[column] - targets[row]
                )
                for row, column in expected_pairs
            ],
            dtype=np.float64,
        ).view(np.uint64)

        np.testing.assert_array_equal(actual_pairs, expected_pairs)
        np.testing.assert_array_equal(actual_bits, expected_bits)


def test_neighbor_coherence_reuses_source_norm_for_reverse_direction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_lab = np.asarray(
        [[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]],
        dtype=np.float64,
    )
    matched_lab = np.asarray(
        [[0.0, 0.0, 0.0], [-10.0, 0.0, 0.0]],
        dtype=np.float64,
    )
    all_lab = np.asarray([[-20.0, 0.0, 0.0]], dtype=np.float64)

    monkeypatch.setattr(
        material_cache_module,
        "rgb_to_lab",
        lambda _rgb: matched_lab.copy(),
    )
    monkeypatch.setattr(
        material_cache_module,
        "_iter_neighbor_pairs_with_distances",
        lambda *_args, **_kwargs: iter(((0, 1, np.float64(10.0)),)),
    )
    monkeypatch.setattr(
        material_cache_module,
        "_top_k_candidate_block",
        lambda _target_block, _candidate_lab, _top_k: (
            np.zeros((1, 1), dtype=np.intp),
            np.asarray([[1.0]], dtype=np.float64),
        ),
    )

    real_norm = material_cache_module._real_vector_norm
    observed_vectors: list[np.ndarray] = []

    def _recording_norm(vector: np.ndarray) -> np.floating:
        observed_vectors.append(vector.copy())
        return real_norm(vector)

    monkeypatch.setattr(
        material_cache_module,
        "_real_vector_norm",
        _recording_norm,
    )
    monkeypatch.setattr(
        material_cache_module.np.linalg,
        "norm",
        lambda *_args, **_kwargs: pytest.fail(
            "coherence hot loop must not call generic norm"
        ),
    )

    matched_rgb, _recipes, _delta_e = _neighbor_coherence_refine(
        target_lab=target_lab,
        matched_rgb=np.zeros((2, 3), dtype=np.uint8),
        recipes_user_order=np.zeros((2, 1), dtype=np.int32),
        delta_e=np.asarray([1.0, 0.0], dtype=np.float64),
        all_lab=all_lab,
        all_srgb=np.asarray([[1, 2, 3]], dtype=np.uint8),
        all_recipes=np.zeros((1, 1), dtype=np.int32),
        user_mapping=np.asarray([0], dtype=np.int32),
        coherence_weight=0.8,
        layer_count=1,
        uniform_lab=None,
        uniform_srgb=None,
        uniform_recipes=None,
    )

    assert len(observed_vectors) == 2
    np.testing.assert_array_equal(matched_rgb[0], np.asarray([1, 2, 3]))


def _legacy_neighbor_pairs(
    target_lab: np.ndarray,
    threshold: float,
) -> np.ndarray:
    distances = cdist(target_lab, target_lab, metric="euclidean")
    pairs = [
        (row_index, column_index)
        for row_index in range(target_lab.shape[0])
        for column_index in range(row_index + 1, target_lab.shape[0])
        if distances[row_index, column_index] < threshold
    ]
    return np.asarray(pairs, dtype=np.intp).reshape(-1, 2)


def _legacy_top_k(
    target_lab: np.ndarray,
    candidate_lab: np.ndarray,
    top_k: int,
) -> tuple[np.ndarray, np.ndarray]:
    full_distances = cdist(target_lab, candidate_lab, metric="euclidean")
    candidate_count = candidate_lab.shape[0]
    effective_top_k = min(int(top_k), candidate_count)
    if effective_top_k >= candidate_count:
        indices = np.broadcast_to(
            np.arange(candidate_count, dtype=np.intp)[None, :],
            (target_lab.shape[0], candidate_count),
        ).copy()
    else:
        indices = np.argpartition(
            full_distances,
            effective_top_k,
            axis=1,
        )[:, :effective_top_k]
    distances = np.take_along_axis(full_distances, indices, axis=1)
    return indices, distances


@pytest.mark.parametrize("seed", [0, 7, 2026])
def test_neighbor_pairs_match_legacy_full_distance_matrix(seed: int) -> None:
    rng = np.random.default_rng(seed)
    target_lab = rng.normal(
        loc=np.asarray([50.0, 0.0, 0.0]),
        scale=np.asarray([18.0, 35.0, 35.0]),
        size=(41, 3),
    )

    expected = _legacy_neighbor_pairs(target_lab, threshold=20.0)
    actual = _find_neighbor_pairs(target_lab, threshold=20.0)

    np.testing.assert_array_equal(actual, expected)


def test_neighbor_pairs_use_strict_threshold_and_lexicographic_order() -> None:
    target_lab = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [20.0, 0.0, 0.0],
            [19.999999, 0.0, 0.0],
            [0.0, 19.0, 0.0],
            [0.0, 0.0, 19.0],
        ],
        dtype=np.float64,
    )

    expected = _legacy_neighbor_pairs(target_lab, threshold=20.0)
    actual = _find_neighbor_pairs(target_lab, threshold=20.0)

    np.testing.assert_array_equal(actual, expected)
    assert (0, 1) not in [tuple(pair) for pair in actual]
    assert [tuple(pair) for pair in actual] == sorted(
        tuple(pair) for pair in actual
    )


def test_dense_neighbor_pairs_do_not_use_quadratic_query_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_tree = material_cache_module.cKDTree

    class _RowQueryTree:
        def __init__(self, data: np.ndarray) -> None:
            self._tree = real_tree(data)

        def query_ball_point(
            self,
            point: np.ndarray,
            radius: float,
        ) -> list[int]:
            return self._tree.query_ball_point(point, radius)

        def query_pairs(self, *_args: object, **_kwargs: object) -> None:
            pytest.fail("dense neighbor discovery must not materialize query_pairs")

    monkeypatch.setattr(material_cache_module, "cKDTree", _RowQueryTree)
    target_lab = np.zeros((128, 3), dtype=np.float64)

    pairs = _find_neighbor_pairs(target_lab, threshold=20.0)

    assert pairs.shape == (128 * 127 // 2, 2)
    np.testing.assert_array_equal(pairs[0], np.asarray([0, 1]))
    np.testing.assert_array_equal(pairs[-1], np.asarray([126, 127]))


@pytest.mark.parametrize(
    ("target_count", "candidate_count", "top_k", "block_size"),
    [
        (7, 13, 8, 1),
        (7, 13, 8, 3),
        (7, 13, 8, 4),
        (5, 5, 8, 2),
        (5, 3, 3, 4),
    ],
)
@pytest.mark.parametrize("parallelism", [1, 2, 4])
def test_blockwise_top_k_matches_legacy_full_matrix(
    target_count: int,
    candidate_count: int,
    top_k: int,
    block_size: int,
    parallelism: int,
) -> None:
    rng = np.random.default_rng(
        target_count * 10_000
        + candidate_count * 100
        + top_k * 10
        + block_size,
    )
    target_lab = rng.normal(size=(target_count, 3))
    candidate_lab = rng.normal(size=(candidate_count, 3))
    expected_indices, expected_distances = _legacy_top_k(
        target_lab,
        candidate_lab,
        top_k,
    )

    actual_indices, actual_distances = _top_k_candidate_rows_blockwise(
        target_lab=target_lab,
        candidate_lab=candidate_lab,
        top_k=top_k,
        block_size=block_size,
        parallelism=parallelism,
    )

    np.testing.assert_array_equal(actual_indices, expected_indices)
    np.testing.assert_array_equal(actual_distances, expected_distances)


@pytest.mark.parametrize("parallelism", [1, 2, 4])
def test_blockwise_top_k_preserves_duplicate_ties_across_k_boundary(
    parallelism: int,
) -> None:
    """Exact ties must retain NumPy's legacy argpartition row semantics."""

    target_lab = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [0.0, 2.0, 0.0],
        ],
        dtype=np.float64,
    )
    candidate_lab = np.asarray(
        [
            [1.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, -1.0, 0.0],
            [1.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
        ],
        dtype=np.float64,
    )
    expected_indices, expected_distances = _legacy_top_k(
        target_lab,
        candidate_lab,
        top_k=3,
    )

    actual_indices, actual_distances = _top_k_candidate_rows_blockwise(
        target_lab=target_lab,
        candidate_lab=candidate_lab,
        top_k=3,
        block_size=1,
        parallelism=parallelism,
    )

    np.testing.assert_array_equal(actual_indices, expected_indices)
    np.testing.assert_array_equal(actual_distances, expected_distances)


@pytest.mark.parametrize(
    ("block_size", "parallelism", "expected_workers"),
    [(1, 4, [4]), (2, 4, [2]), (1, 2, [2]), (None, 4, [])],
)
def test_blockwise_top_k_uses_requested_workers_for_available_blocks(
    monkeypatch: pytest.MonkeyPatch,
    block_size: int | None,
    parallelism: int,
    expected_workers: list[int],
) -> None:
    observed_workers: list[int] = []

    class _RecordingExecutor(ThreadPoolExecutor):
        def __init__(self, max_workers: int) -> None:
            observed_workers.append(max_workers)
            super().__init__(max_workers=max_workers)

    monkeypatch.setattr(
        material_cache_module,
        "ThreadPoolExecutor",
        _RecordingExecutor,
    )
    rng = np.random.default_rng(20260728)
    target_lab = rng.normal(size=(4, 3))
    candidate_lab = rng.normal(size=(32, 3))
    expected_indices, expected_distances = _legacy_top_k(
        target_lab,
        candidate_lab,
        top_k=8,
    )

    actual_indices, actual_distances = _top_k_candidate_rows_blockwise(
        target_lab=target_lab,
        candidate_lab=candidate_lab,
        top_k=8,
        block_size=block_size,
        parallelism=parallelism,
    )

    # Only multiple available blocks need a pool; one block stays serial.
    assert observed_workers == expected_workers
    np.testing.assert_array_equal(actual_indices, expected_indices)
    np.testing.assert_array_equal(actual_distances, expected_distances)


def test_top_k_candidate_block_retains_only_selected_indices() -> None:
    rng = np.random.default_rng(20261118)
    targets = rng.normal(size=(2, 3))
    candidates = rng.normal(size=(61_014, 3))

    indices, distances = material_cache_module._top_k_candidate_block(
        targets, candidates, 8,
    )

    assert indices.shape == distances.shape == (2, 8)
    storage = indices
    while isinstance(storage.base, np.ndarray):
        storage = storage.base
    assert storage.nbytes == indices.nbytes


def test_blockwise_top_k_shares_matrix_workspace_across_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rng = np.random.default_rng(20261118)
    targets = rng.normal(size=(29, 3))
    candidates = rng.normal(size=(128, 3))
    bytes_per_row = candidates.shape[0] * (
        np.dtype(np.float64).itemsize + np.dtype(np.intp).itemsize
    )
    workspace_bytes = 12 * bytes_per_row
    observed_workers: list[int] = []
    observed_block_rows: list[int] = []
    real_block = material_cache_module._top_k_candidate_block

    class _RecordingExecutor(ThreadPoolExecutor):
        def __init__(self, max_workers: int) -> None:
            observed_workers.append(max_workers)
            super().__init__(max_workers=max_workers)

    def record_block(
        target_block: np.ndarray,
        candidate_lab: np.ndarray,
        top_k: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        observed_block_rows.append(target_block.shape[0])
        return real_block(target_block, candidate_lab, top_k)

    monkeypatch.setattr(
        material_cache_module,
        "_NEIGHBOR_COHERENCE_WORKSPACE_BYTES",
        workspace_bytes,
        raising=False,
    )
    monkeypatch.setattr(material_cache_module, "ThreadPoolExecutor", _RecordingExecutor)
    monkeypatch.setattr(material_cache_module, "_top_k_candidate_block", record_block)

    actual = _top_k_candidate_rows_blockwise(
        target_lab=targets,
        candidate_lab=candidates,
        top_k=8,
        block_size=8,
        parallelism=4,
    )

    assert observed_workers == [4]
    assert max(observed_block_rows) * bytes_per_row * 4 <= workspace_bytes
    for actual_array, expected_array in zip(
        actual, _legacy_top_k(targets, candidates, 8), strict=True,
    ):
        np.testing.assert_array_equal(actual_array, expected_array)


@pytest.mark.parametrize("parallelism", [1, 4])
def test_blockwise_top_k_releases_completed_block_arrays(
    monkeypatch: pytest.MonkeyPatch,
    parallelism: int,
) -> None:
    rng = np.random.default_rng(20261118)
    targets = rng.normal(size=(24, 3))
    candidates = rng.normal(size=(128, 3))
    real_block = material_cache_module._top_k_candidate_block
    lock = Lock()
    live_indices: list[ReferenceType[np.ndarray]] = []
    peak_live = 0

    def track_block(
        target_block: np.ndarray,
        candidate_lab: np.ndarray,
        top_k: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        nonlocal peak_live
        indices, distances = real_block(target_block, candidate_lab, top_k)
        with lock:
            live_indices[:] = [
                reference for reference in live_indices if reference() is not None
            ]
            live_indices.append(ref(indices))
            peak_live = max(peak_live, len(live_indices))
        return indices, distances

    monkeypatch.setattr(material_cache_module, "_top_k_candidate_block", track_block)

    _top_k_candidate_rows_blockwise(
        target_lab=targets,
        candidate_lab=candidates,
        top_k=8,
        block_size=2,
        parallelism=parallelism,
    )

    assert peak_live <= parallelism


def _coherence_fixture() -> dict[str, np.ndarray | float | int | None]:
    target_srgb = np.asarray(
        [
            [72, 92, 118],
            [78, 96, 122],
            [84, 100, 126],
            [90, 104, 130],
            [96, 108, 134],
            [102, 112, 138],
            [108, 116, 142],
        ],
        dtype=np.uint8,
    )
    all_srgb = np.asarray(
        [
            [70 + red_offset, 88 + green_offset, 112 + blue_offset]
            for red_offset in range(0, 49, 8)
            for green_offset, blue_offset in ((0, 0), (5, 9), (10, 3))
        ],
        dtype=np.uint8,
    )
    target_lab = rgb_to_lab(target_srgb).astype(np.float64)
    all_lab = rgb_to_lab(all_srgb).astype(np.float64)
    matched_rows = np.asarray([0, 5, 2, 11, 8, 17, 14], dtype=np.intp)
    matched_rgb = all_srgb[matched_rows]
    matched_lab = all_lab[matched_rows]
    delta_e = np.linalg.norm(matched_lab - target_lab, axis=1)
    layer_count = 4
    material_count = 4
    all_recipes = (
        np.arange(all_srgb.shape[0] * layer_count, dtype=np.int32)
        .reshape(all_srgb.shape[0], layer_count)
        % material_count
    )
    return {
        "target_lab": target_lab,
        "matched_rgb": matched_rgb,
        "recipes_user_order": all_recipes[matched_rows],
        "delta_e": delta_e,
        "all_lab": all_lab,
        "all_srgb": all_srgb,
        "all_recipes": all_recipes,
        "user_mapping": np.arange(material_count, dtype=np.int32),
        "coherence_weight": 0.8,
        "layer_count": layer_count,
        "uniform_lab": None,
        "uniform_srgb": None,
        "uniform_recipes": None,
    }


def test_serial_coherence_computes_only_demanded_top_k_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _coherence_fixture()
    expected = _neighbor_coherence_refine(**fixture, parallelism=4)
    real_block = material_cache_module._top_k_candidate_block
    observed_targets: list[bytes] = []

    def _recording_block(
        target_block: np.ndarray,
        candidate_lab: np.ndarray,
        top_k: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        assert target_block.shape == (1, 3)
        observed_targets.append(target_block.tobytes())
        return real_block(target_block, candidate_lab, top_k)

    monkeypatch.setattr(
        material_cache_module,
        "_top_k_candidate_rows_blockwise",
        lambda **_kwargs: pytest.fail("serial path must not compute every row"),
    )
    monkeypatch.setattr(
        material_cache_module,
        "_top_k_candidate_block",
        _recording_block,
    )

    actual = _neighbor_coherence_refine(**fixture, parallelism=1)

    assert len(observed_targets) == 6
    assert len(observed_targets) < np.asarray(fixture["target_lab"]).shape[0]
    assert len(set(observed_targets)) == len(observed_targets)
    for actual_array, expected_array in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(actual_array, expected_array)


def test_exact_top_k_row_cache_computes_same_row_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_lab = np.asarray(
        [[0.0, 0.0, 0.0], [4.0, 1.0, -2.0]],
        dtype=np.float64,
    )
    candidate_lab = np.asarray(
        [[0.0, 0.0, 0.0], [3.0, 1.0, -2.0], [8.0, 2.0, -4.0]],
        dtype=np.float64,
    )
    real_block = material_cache_module._top_k_candidate_block
    observed_targets: list[bytes] = []

    def _recording_block(
        target_block: np.ndarray,
        candidates: np.ndarray,
        top_k: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        observed_targets.append(target_block.tobytes())
        return real_block(target_block, candidates, top_k)

    monkeypatch.setattr(
        material_cache_module,
        "_top_k_candidate_block",
        _recording_block,
    )
    cache = material_cache_module._ExactTopKRowCache.create(
        target_lab=target_lab,
        candidate_lab=candidate_lab,
        top_k=2,
    )

    first_indices, first_distances = cache.get(1)
    second_indices, second_distances = cache.get(1)

    assert observed_targets == [target_lab[1:2].tobytes()]
    np.testing.assert_array_equal(second_indices, first_indices)
    np.testing.assert_array_equal(second_distances, first_distances)


def test_exact_top_k_row_cache_preserves_k_boundary_tie_order() -> None:
    target_lab = np.asarray(
        [[20.0, 0.0, 0.0], [0.0, 0.0, 0.0], [-20.0, 0.0, 0.0]],
        dtype=np.float64,
    )
    candidate_lab = np.asarray(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
            [3.0, 0.0, 0.0],
            [4.0, 0.0, 0.0],
            [5.0, 0.0, 0.0],
            [6.0, 0.0, 0.0],
            [7.0, 0.0, 0.0],
            [-7.0, 0.0, 0.0],
            [30.0, 0.0, 0.0],
        ],
        dtype=np.float64,
    )
    top_k = 8
    eager_indices, eager_distances = _top_k_candidate_rows_blockwise(
        target_lab=target_lab,
        candidate_lab=candidate_lab,
        top_k=top_k,
        block_size=target_lab.shape[0],
        parallelism=1,
    )
    cache = material_cache_module._ExactTopKRowCache.create(
        target_lab=target_lab,
        candidate_lab=candidate_lab,
        top_k=top_k,
    )

    cached_indices, cached_distances = cache.get(1)

    all_distances = cdist(target_lab[1:2], candidate_lab)[0]
    assert np.count_nonzero(all_distances == 7.0) == 2
    assert np.count_nonzero(cached_distances == 7.0) == 1
    np.testing.assert_array_equal(cached_indices, eager_indices[1])
    np.testing.assert_array_equal(cached_distances, eager_distances[1])


def test_exact_top_k_row_cache_matches_eager_negative_index() -> None:
    target_lab = np.asarray(
        [[0.0, 0.0, 0.0], [4.0, 1.0, -2.0]],
        dtype=np.float64,
    )
    candidate_lab = np.asarray(
        [[0.0, 0.0, 0.0], [3.0, 1.0, -2.0], [8.0, 2.0, -4.0]],
        dtype=np.float64,
    )
    eager_indices, eager_distances = _top_k_candidate_rows_blockwise(
        target_lab=target_lab,
        candidate_lab=candidate_lab,
        top_k=2,
        parallelism=1,
    )
    cache = material_cache_module._ExactTopKRowCache.create(
        target_lab=target_lab,
        candidate_lab=candidate_lab,
        top_k=2,
    )

    cached_indices, cached_distances = cache.get(-1)

    np.testing.assert_array_equal(cached_indices, eager_indices[-1])
    np.testing.assert_array_equal(cached_distances, eager_distances[-1])


def test_parallel_coherence_keeps_eager_blockwise_top_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fixture = _coherence_fixture()
    expected = _neighbor_coherence_refine(**fixture, parallelism=1)
    real_blockwise = material_cache_module._top_k_candidate_rows_blockwise
    observed_parallelism: list[int] = []

    def _recording_blockwise(
        **kwargs: Any,
    ) -> tuple[np.ndarray, np.ndarray]:
        observed_parallelism.append(int(kwargs["parallelism"]))
        return real_blockwise(**kwargs)

    monkeypatch.setattr(
        material_cache_module,
        "_top_k_candidate_rows_blockwise",
        _recording_blockwise,
    )

    actual = _neighbor_coherence_refine(**fixture, parallelism=4)

    assert observed_parallelism == [4]
    for actual_array, expected_array in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(actual_array, expected_array)


def test_serial_coherence_preserves_duplicate_candidate_ties() -> None:
    fixture = _coherence_fixture()
    duplicated = dict(fixture)
    for key in ("all_lab", "all_srgb", "all_recipes"):
        values = np.asarray(fixture[key])
        duplicated[key] = np.concatenate((values, values[:9]), axis=0)

    expected = _neighbor_coherence_refine(**duplicated, parallelism=4)
    actual = _neighbor_coherence_refine(**duplicated, parallelism=1)

    for actual_array, expected_array in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(actual_array, expected_array)


@pytest.mark.parametrize(
    ("block_size", "parallelism"),
    [(1, 1), (2, 2), (5, 4), (100, 4)],
)
def test_complete_coherence_output_is_stable_across_blocks_and_workers(
    block_size: int,
    parallelism: int,
) -> None:
    fixture = _coherence_fixture()
    expected = _neighbor_coherence_refine(
        **fixture,
        candidate_block_size=3,
        parallelism=1,
    )

    actual = _neighbor_coherence_refine(
        **fixture,
        candidate_block_size=block_size,
        parallelism=parallelism,
    )

    for actual_array, expected_array in zip(actual, expected, strict=True):
        np.testing.assert_array_equal(actual_array, expected_array)
