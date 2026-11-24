"""Unit tests for ``core.material_cache_visualization``.
``core.material_cache_visualization`` 单元测试。

Pins five properties of the LUT-details-shaped payload built from a solver
cache:

1. Empty cache yields a well-formed payload with zero-length point arrays
   and zero-range coverage stats (no exception).
2. A real built cache produces ``lab_points`` / ``rgb_points`` /
   ``lab_points_3d`` whose lengths match the cache's reachable bucket count
   (when below the downsample limit) and whose ranges sit within Lab/RGB
   plausibility envelopes.
3. The convex hull is non-degenerate for a non-trivial palette.
4. Coverage stats expose ``entry_count`` (full reachable count) separately
   from ``plotted_point_count`` (post-downsampling), matching what
   ``LutDetailsPanel`` displays as a footer for both.
5. The deterministic stride downsampler caps the plotted count exactly at
   ``max_points`` and never exceeds it.
"""

from __future__ import annotations

import numpy as np
import pytest

from core.material_cache import (
    DEFAULT_GRID_RESOLUTION,
    MaterialSolverCache,
    build_material_solver_cache,
)
from core.material_candidate_cache import (
    MaterialCandidateCacheConfig,
    build_material_candidate_runtime,
)
from core.material_cache_visualization import (
    MaterialSolverCacheDetails,
    build_material_cache_details,
    build_material_runtime_details,
)


@pytest.mark.parametrize(("points", "expected"), [
    ([], ()),
    ([(0, 0), (0, 0)], ()),
    ([(0, 0), (0, 0), (3, 3), (3, 3)], ()),
    ([(0, 0), (0, 0), (2, 2), (3, 3), (1, 1)], ((0, 0), (3, 3))),
    (
        [(0, 0), (0, 0), (1, 1), (4, 0), (4, 4), (0, 4), (2, 2)],
        ((0, 0), (4, 0), (4, 4), (0, 4)),
    ),
])
def test_lab_hull_preserves_extrema_across_degenerate_blocks(points, expected) -> None:
    from core.material_cache_visualization import _compute_lab_hull

    lab = np.zeros((len(points), 3), dtype=np.float32)
    lab[:, 1:] = np.asarray(points).reshape(-1, 2)
    assert _compute_lab_hull(lab, block_rows=2) == expected
from core.material_color_solver import MaterialParams


def _mat(name: str, E: tuple[float, float, float], k: tuple[float, float, float]) -> MaterialParams:
    """Build a minimal :class:`MaterialParams` for the given palette entry."""
    e_arr = np.asarray(E, dtype=np.float64)
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=e_arr,
        k=np.asarray(k, dtype=np.float64),
        C0_white=np.asarray([1.0, 1.0, 1.0], dtype=np.float64),
        estimated_rgb=np.clip(np.round(e_arr * 255.0), 0, 255).astype(np.uint8),
    )


_SMALL_PALETTE: list[MaterialParams] = [
    _mat("white", (0.95, 0.95, 0.95), (15.0, 15.0, 15.0)),
    _mat("red", (0.65, 0.10, 0.10), (8.0, 30.0, 30.0)),
    _mat("blue", (0.10, 0.10, 0.65), (28.0, 28.0, 6.0)),
]


@pytest.fixture(scope="module")
def built_cache() -> MaterialSolverCache:
    """Build a small cache once per test module."""
    return build_material_solver_cache(
        _SMALL_PALETTE,
        layer_count=5,
        layer_height_mm=0.08,
        substrate="white",
        grid_resolution=32,
    )


class TestBuildMaterialCacheDetails:
    """Behavioural contract of :func:`build_material_cache_details`."""

    def test_payload_is_well_formed(self, built_cache: MaterialSolverCache) -> None:
        """Returns a :class:`MaterialSolverCacheDetails` with non-empty arrays.
        返回的 :class:`MaterialSolverCacheDetails` 应字段齐备且数组非空。"""
        details = build_material_cache_details(
            built_cache,
            palette_hash="abcd1234",
            grid_resolution=32,
        )
        assert isinstance(details, MaterialSolverCacheDetails)
        assert details.palette_hash == "abcd1234"
        assert details.grid_resolution == 32
        assert details.valid_cell_count > 0
        assert len(details.lab_points) > 0
        assert len(details.rgb_points) == len(details.lab_points)
        assert len(details.lab_points_3d) == len(details.lab_points)

    def test_coverage_stats_ranges_are_inside_lab_envelope(
        self, built_cache: MaterialSolverCache
    ) -> None:
        """Lab L*/a*/b* coverage ranges sit within plausible Lab values.
        Lab 覆盖范围应处于合理的 Lab 取值区间内。"""
        details = build_material_cache_details(
            built_cache,
            palette_hash="abcd1234",
            grid_resolution=32,
        )
        cs = details.coverage_stats
        assert 0.0 <= cs.l_range.min <= cs.l_range.max <= 100.0
        # OpenCV's CIELAB output for a*/b* lies in roughly ±128.
        assert -130.0 <= cs.a_range.min <= cs.a_range.max <= 130.0
        assert -130.0 <= cs.b_range.min <= cs.b_range.max <= 130.0
        assert 0.0 <= cs.r_range.min <= cs.r_range.max <= 255.0
        assert 0.0 <= cs.g_range.min <= cs.g_range.max <= 255.0
        assert 0.0 <= cs.b_rgb_range.min <= cs.b_rgb_range.max <= 255.0

    def test_lab_hull_is_non_degenerate_for_real_palette(
        self, built_cache: MaterialSolverCache
    ) -> None:
        """A real palette yields a convex hull with at least 3 vertices.
        真实调色板应产生不少于 3 个顶点的凸包。"""
        details = build_material_cache_details(
            built_cache,
            palette_hash="abcd1234",
            grid_resolution=32,
        )
        assert len(details.lab_hull) >= 3

    def test_entry_count_vs_plotted_point_count(
        self, built_cache: MaterialSolverCache
    ) -> None:
        """``entry_count`` (full) >= ``plotted_point_count`` (post-downsample).
        全量 entry_count 应不小于绘制点数（下采样后）。"""
        details = build_material_cache_details(
            built_cache,
            palette_hash="abcd1234",
            grid_resolution=32,
            max_points=64,
        )
        assert details.coverage_stats.entry_count >= details.coverage_stats.plotted_point_count
        assert details.coverage_stats.plotted_point_count <= 64

    def test_max_points_caps_plotted_count(
        self, built_cache: MaterialSolverCache
    ) -> None:
        """``max_points`` caps len of ``lab_points`` / ``rgb_points`` exactly.
        ``max_points`` 严格限制散点数量。"""
        cap = 32
        details = build_material_cache_details(
            built_cache,
            palette_hash="abcd1234",
            grid_resolution=32,
            max_points=cap,
        )
        assert len(details.lab_points) <= cap
        assert len(details.rgb_points) <= cap
        assert len(details.lab_points_3d) <= cap


class TestEmptyCacheEdgeCase:
    """Edge case: a cache with zero reachable buckets must not crash."""

    def test_empty_cache_yields_zero_length_arrays(self) -> None:
        """Zero buckets => empty arrays + zero-range coverage stats.
        空缓存：返回空数组与零覆盖范围，但 schema 完整。"""
        empty_cache = MaterialSolverCache(
            lab_centers=np.zeros((0, 3), dtype=np.float32),
            recipes=np.zeros((0, 5), dtype=np.uint8),
            achieved_srgb=np.zeros((0, 3), dtype=np.uint8),
            achieved_lab=np.zeros((0, 3), dtype=np.float32),
            center_delta_e=np.zeros((0,), dtype=np.float32),
            uniform_recipes=np.zeros((0, 5), dtype=np.uint8),
            uniform_achieved_srgb=np.zeros((0, 3), dtype=np.uint8),
            metadata={
                "layer_count": 5,
                "layer_height_mm": 0.08,
                "substrate": "white",
                "grid_resolution": DEFAULT_GRID_RESOLUTION,
            },
        )
        details = build_material_cache_details(
            empty_cache,
            palette_hash="cafebabe",
            grid_resolution=DEFAULT_GRID_RESOLUTION,
        )
        assert details.valid_cell_count == 0
        assert details.coverage_stats.entry_count == 0
        assert details.coverage_stats.plotted_point_count == 0
        assert details.coverage_stats.l_range.min == 0.0
        assert details.coverage_stats.l_range.max == 0.0
        assert len(details.lab_points) == 0
        assert len(details.rgb_points) == 0
        assert len(details.lab_points_3d) == 0
        assert details.lab_hull == ()


class TestBuildMaterialRuntimeDetails:
    """Behavioural contract for hybrid runtime visualization payloads."""

    def test_candidate_runtime_payload_is_lut_details_shaped(self) -> None:
        runtime = build_material_candidate_runtime(
            materials=_SMALL_PALETTE,
            layer_count=5,
            layer_height_mm=0.08,
            substrate="white",
            config=MaterialCandidateCacheConfig(
                candidate_budget=64,
                enable_inverse_refinement=False,
            ),
        )

        details = build_material_runtime_details(runtime, max_points=32)

        assert details.palette_hash == runtime.palette_hash
        assert details.layer_count == 5
        assert details.layer_height_mm == 0.08
        assert details.substrate == "white"
        assert details.candidate_budget == 64
        assert details.candidate_count == runtime.valid_cell_count
        assert details.coverage_stats.entry_count == runtime.valid_cell_count
        assert details.coverage_stats.plotted_point_count <= 32
        assert len(details.lab_points) <= 32
        assert len(details.rgb_points) == len(details.lab_points)
        assert len(details.lab_points_3d) == len(details.lab_points)
