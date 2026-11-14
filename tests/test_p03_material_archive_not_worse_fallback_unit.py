"""Regression tests for the P03 bounded runtime fallback.
P03 有界运行时回退路径的回归测试。

When no persisted ``MaterialSolverCache`` is found on disk, P03 now resolves a
lookup-compatible bounded runtime via :func:`core.material_lut_provider.load_solver_runtime`.
The old temporary 64-grid exhaustive builder must not be called.

没有持久化求解缓存时，P03 现在通过 ``load_solver_runtime`` 解析一个查找兼容
的有界运行时，不能再调用旧的 64-grid 临时穷举构建器。

Locks in:
    * ``solver_path == "cache"`` with ``cache_mode == "candidate_hybrid"``;
    * ``load_solver_runtime`` is invoked exactly once;
    * the old ``build_material_solver_cache`` fallback is not invoked;
    * the cross-N fallback helper is invoked only for fully-covered small
      runtimes, not approximate bounded runtimes;
    * ``material_matrix`` still carries correct Top2Bottom recipes after reversal.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import numpy as np
import pytest
from PIL import Image

from config import ModelingMode
from core.material_color_solver import (
    DEFAULT_LAYER_HEIGHT_MM,
    MaterialParams,
)
from core.pipeline.p03_core_processing import _run_material_archive_branch


# ---------------------------------------------------------------------------
# Fixtures — tiny palette with a well-defined white entry.
# ---------------------------------------------------------------------------


def _mat(name: str, E: tuple, k: tuple) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(E, dtype=np.float64),
        k=np.asarray(k, dtype=np.float64),
        C0_white=np.asarray((1.0, 1.0, 1.0), dtype=np.float64),
        estimated_rgb=np.asarray(
            [int(round(255 * c)) for c in E], dtype=np.uint8
        ),
    )


RED = _mat("Red", E=(0.6, 0.05, 0.05), k=(4.0, 4.0, 4.0))
BLUE = _mat("Blue", E=(0.05, 0.1, 0.6), k=(4.0, 4.0, 4.0))
WHITE = _mat("White", E=(0.95, 0.95, 0.95), k=(0.5, 0.5, 0.5))
PALETTE_WITH_WHITE = [RED, BLUE, WHITE]


def _write_solid_color_png(path: Path, rgb: tuple[int, int, int], size: int = 4) -> Path:
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    arr[..., 0] = rgb[0]
    arr[..., 1] = rgb[1]
    arr[..., 2] = rgb[2]
    arr[..., 3] = 255
    Image.fromarray(arr, mode="RGBA").save(path)
    return path


def _write_transparent_png(path: Path, size: int = 4) -> Path:
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    Image.fromarray(arr, mode="RGBA").save(path)
    return path


def _make_ctx(image_path: Path, *, layer_count: int = 6) -> dict:
    return {
        "image_path": str(image_path),
        "target_width_mm": 2.0,
        "modeling_mode": ModelingMode.PIXEL,
        "quantize_colors": 2,
        "_material_params": PALETTE_WITH_WHITE,
        "color_layers": layer_count,
        "layer_height_mm": DEFAULT_LAYER_HEIGHT_MM,
        "material_substrate": "white",
        "material_source": "material_archive",
    }


# ---------------------------------------------------------------------------
# Fake cache stub
# ---------------------------------------------------------------------------


class _FakeCache:
    """Minimal stub that mimics MaterialSolverCache for P03 on-the-fly path."""

    def __init__(self, matched_rgb, recipes, delta_e, layer_count, *, valid_cell_count=1):
        self._matched_rgb = matched_rgb
        self._recipes = recipes
        self._delta_e = delta_e
        self._layer_count = layer_count
        self.valid_cell_count = int(valid_cell_count)
        self.mode = "candidate_hybrid"
        self.metadata = {
            "palette_hash": "test",
            "grid_resolution": 64,
            "layer_count": layer_count,
            "mean_delta_e": 0.0,
            "max_delta_e": 0.0,
            "build_time_seconds": 0.01,
            "built_at": "2026-01-01T00:00:00Z",
        }

    @property
    def palette_hash(self):
        return self.metadata["palette_hash"]

    @property
    def grid_resolution(self):
        return int(self.metadata["grid_resolution"])

    @property
    def layer_count(self):
        return self._layer_count

    def lookup(self, target_srgb, user_materials):
        n = target_srgb.shape[0]
        return (
            np.broadcast_to(self._matched_rgb, (n, 3)).copy(),
            np.broadcast_to(self._recipes, (n, self._layer_count)).copy(),
            np.broadcast_to(self._delta_e, (n,)).copy(),
        )


# ---------------------------------------------------------------------------
# On-the-fly cache build tests
# ---------------------------------------------------------------------------


class TestP03BoundedRuntimeFallback:
    def test_solver_meta_reports_candidate_runtime(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When no persisted cache exists, P03 must report bounded runtime metadata."""
        image_path = _write_solid_color_png(tmp_path / "red.png", (220, 40, 30))
        ctx = _make_ctx(image_path, layer_count=6)

        red_idx = PALETTE_WITH_WHITE.index(RED)
        recipe = np.full((1, 6), red_idx, dtype=np.int32)
        matched_rgb = np.asarray([[220, 40, 30]], dtype=np.uint8)
        delta_e = np.asarray([1.5], dtype=np.float64)
        fake_cache = _FakeCache(matched_rgb, recipe, delta_e, 6)

        monkeypatch.setattr(
            "core.material_cache.build_material_solver_cache",
            lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("old temporary exhaustive cache must not build")
            ),
            raising=False,
        )
        monkeypatch.setattr(
            "core.material_lut_provider.load_solver_runtime",
            lambda **kwargs: (fake_cache, 64),
        )

        result = _run_material_archive_branch(ctx)
        solver_info = result["material_solver_info"]

        assert solver_info["path"] == "cache"
        assert solver_info["cache_mode"] == "candidate_hybrid"
        assert solver_info["grid_resolution"] == 64
        assert solver_info["grid_fallback_used"] is False
        assert solver_info["mean_delta_e"] == pytest.approx(1.5)
        assert solver_info["max_delta_e"] == pytest.approx(1.5)

    def test_recipe_reaches_material_matrix_after_reversal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bottom2Top recipe from on-the-fly cache must be reversed to
        Top2Bottom in ``material_matrix``."""
        image_path = _write_solid_color_png(tmp_path / "red.png", (220, 40, 30))
        ctx = _make_ctx(image_path, layer_count=6)

        red_idx = PALETTE_WITH_WHITE.index(RED)
        white_idx = PALETTE_WITH_WHITE.index(WHITE)
        blue_idx = PALETTE_WITH_WHITE.index(BLUE)
        # Bottom2Top recipe: [W, W, W, B, B, R]
        recipe_b2t = np.asarray(
            [[white_idx, white_idx, white_idx, blue_idx, blue_idx, red_idx]],
            dtype=np.int32,
        )
        fake_cache = _FakeCache(
            np.asarray([[200, 60, 50]], dtype=np.uint8),
            recipe_b2t,
            np.asarray([0.5], dtype=np.float64),
            6,
        )

        monkeypatch.setattr(
            "core.material_cache.build_material_solver_cache",
            lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("old temporary exhaustive cache must not build")
            ),
            raising=False,
        )
        monkeypatch.setattr(
            "core.material_lut_provider.load_solver_runtime",
            lambda **kwargs: (fake_cache, 64),
        )

        result = _run_material_archive_branch(ctx)
        material_matrix = result["material_matrix"]
        mask_solid = result["mask_solid"]

        # Pipeline stores Top2Bottom; the reversal turns [W,W,W,B,B,R] into
        # [R,B,B,W,W,W] along the last axis.
        expected_top_to_bottom = [red_idx, blue_idx, blue_idx, white_idx, white_idx, white_idx]
        assert material_matrix.shape[-1] == 6
        for y, x in np.argwhere(mask_solid):
            actual = material_matrix[y, x].tolist()
            assert actual == expected_top_to_bottom, (
                f"pixel ({y},{x}) got {actual}, expected {expected_top_to_bottom}"
            )


class TestP03BoundedRuntimeGuards:
    def test_cross_n_fallback_is_not_invoked_for_partial_runtime(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Approximate runtimes must not call the expensive cross-N fallback."""
        image_path = _write_solid_color_png(tmp_path / "red.png", (220, 40, 30))
        ctx = _make_ctx(image_path, layer_count=6)

        red_idx = PALETTE_WITH_WHITE.index(RED)
        recipe = np.full((1, 6), red_idx, dtype=np.int32)
        fake_cache = _FakeCache(
            np.asarray([[220, 40, 30]], dtype=np.uint8),
            recipe,
            np.asarray([0.0], dtype=np.float64),
            6,
        )

        monkeypatch.setattr(
            "core.material_cache.build_material_solver_cache",
            lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("old temporary exhaustive cache must not build")
            ),
            raising=False,
        )
        monkeypatch.setattr(
            "core.material_lut_provider.load_solver_runtime",
            lambda **kwargs: (fake_cache, 64),
        )

        call_counter = {"n": 0}

        def _mock_fallback(*args, **kwargs):
            call_counter["n"] += 1
            raise AssertionError("cross-N fallback should not be called")

        monkeypatch.setattr(
            "core.material_lut_synthesis.ensure_not_worse_than_smaller_N",
            _mock_fallback,
        )

        result = _run_material_archive_branch(ctx)
        assert call_counter["n"] == 0
        assert "not_worse_fallback" not in result["material_solver_info"]

    def test_cross_n_fallback_runs_for_full_coverage_runtime(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Small runtimes that cover every recipe keep the not-worse guard."""
        image_path = _write_solid_color_png(tmp_path / "red.png", (220, 40, 30))
        ctx = _make_ctx(image_path, layer_count=6)

        red_idx = PALETTE_WITH_WHITE.index(RED)
        blue_idx = PALETTE_WITH_WHITE.index(BLUE)
        white_idx = PALETTE_WITH_WHITE.index(WHITE)
        baseline_recipe = np.full((1, 6), red_idx, dtype=np.int32)
        improved_recipe_b2t = np.asarray(
            [[white_idx, white_idx, blue_idx, blue_idx, red_idx, red_idx]],
            dtype=np.int32,
        )
        fake_cache = _FakeCache(
            np.asarray([[180, 30, 25]], dtype=np.uint8),
            baseline_recipe,
            np.asarray([12.0], dtype=np.float64),
            6,
            valid_cell_count=len(PALETTE_WITH_WHITE) ** 6,
        )

        monkeypatch.setattr(
            "core.material_cache.build_material_solver_cache",
            lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("old temporary exhaustive cache must not build")
            ),
            raising=False,
        )
        monkeypatch.setattr(
            "core.material_lut_provider.load_solver_runtime",
            lambda **kwargs: (fake_cache, 64),
        )

        call_counter = {"n": 0}

        def _mock_fallback(
            unique_colors,
            materials,
            baseline_matched_rgb,
            baseline_recipes,
            baseline_delta_e,
            **kwargs,
        ):
            call_counter["n"] += 1
            assert kwargs["target_layer_count"] == 6
            assert unique_colors.shape == (1, 3)
            assert baseline_recipes.shape == (1, 6)
            return (
                np.asarray([[220, 40, 30]], dtype=np.uint8),
                improved_recipe_b2t,
                np.asarray([0.25], dtype=np.float64),
                {
                    "white_material_index": white_idx,
                    "applied": True,
                    "improved_pixels": 1,
                    "per_k_improved": {5: 1},
                    "mean_delta_e_before": 12.0,
                    "max_delta_e_before": 12.0,
                    "mean_delta_e_after": 0.25,
                    "max_delta_e_after": 0.25,
                },
            )

        monkeypatch.setattr(
            "core.material_lut_synthesis.ensure_not_worse_than_smaller_N",
            _mock_fallback,
        )

        result = _run_material_archive_branch(ctx)

        assert call_counter["n"] == 1
        assert result["material_solver_info"]["not_worse_fallback"][
            "improved_pixels"
        ] == 1
        material_matrix = result["material_matrix"]
        mask_solid = result["mask_solid"]
        expected_top_to_bottom = [
            red_idx,
            red_idx,
            blue_idx,
            blue_idx,
            white_idx,
            white_idx,
        ]
        for y, x in np.argwhere(mask_solid):
            assert material_matrix[y, x].tolist() == expected_top_to_bottom

    def test_load_solver_runtime_is_invoked_exactly_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pipeline must resolve the bounded runtime exactly once."""
        image_path = _write_solid_color_png(tmp_path / "red.png", (220, 40, 30))
        ctx = _make_ctx(image_path, layer_count=6)

        red_idx = PALETTE_WITH_WHITE.index(RED)
        recipe = np.full((1, 6), red_idx, dtype=np.int32)
        fake_cache = _FakeCache(
            np.asarray([[220, 40, 30]], dtype=np.uint8),
            recipe,
            np.asarray([0.0], dtype=np.float64),
            6,
        )

        call_counter = {"n": 0}

        def _mock_load_runtime(**kwargs):
            call_counter["n"] += 1
            assert kwargs["grid_resolution"] == 64
            return fake_cache, 64

        monkeypatch.setattr(
            "core.material_cache.build_material_solver_cache",
            lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("old temporary exhaustive cache must not build")
            ),
            raising=False,
        )
        monkeypatch.setattr(
            "core.material_lut_provider.load_solver_runtime",
            _mock_load_runtime,
        )

        _run_material_archive_branch(ctx)
        assert call_counter["n"] == 1

    def test_transparent_image_does_not_build_candidate_runtime(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fully transparent inputs have no visible colours to solve."""
        image_path = _write_transparent_png(tmp_path / "transparent.png")
        ctx = _make_ctx(image_path, layer_count=6)

        monkeypatch.setattr(
            "core.material_lut_provider.load_solver_cache",
            lambda **kwargs: (None, None),
        )
        monkeypatch.setattr(
            "core.material_lut_provider.load_solver_runtime",
            lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("transparent image must not build candidate runtime")
            ),
        )

        result = _run_material_archive_branch(ctx)

        assert result["material_solver_info"]["unique_color_count"] == 0
        assert result["material_solver_info"]["cache_mode"] == "none"
        assert np.all(result["material_matrix"] == -1)


class TestP03DeepStackCrossNBound:
    """Two materials with white at 12 layers stay inside the MITM bound."""

    def test_two_material_twelve_layer_preview_runs_cross_n_guard(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        palette = [RED, WHITE]
        layer_count = 12
        image_path = _write_solid_color_png(tmp_path / "pink.png", (230, 150, 150))
        ctx = _make_ctx(image_path, layer_count=layer_count)
        ctx["_material_params"] = palette

        red_idx = palette.index(RED)
        # Full coverage (2 ** 12 recipes) keeps the real cross-N guard enabled.
        fake_cache = _FakeCache(
            np.asarray([[180, 30, 25]], dtype=np.uint8),
            np.full((1, layer_count), red_idx, dtype=np.int32),
            np.asarray([40.0], dtype=np.float64),
            layer_count,
            valid_cell_count=len(palette) ** layer_count,
        )
        monkeypatch.setattr(
            "core.material_lut_provider.load_solver_runtime",
            lambda **kwargs: (fake_cache, 64),
        )

        result = _run_material_archive_branch(ctx)

        fallback = result["material_solver_info"]["not_worse_fallback"]
        assert fallback["applied"] is True
        assert all(5 <= int(k) <= 10 for k in fallback["per_k_improved"])
        assert result["material_matrix"].shape[-1] == layer_count


def test_cross_n_guard_skips_layer_counts_beyond_mitm() -> None:
    from core.material_color_solver import MITM_MAX_LAYER_COUNT
    from core.material_lut_synthesis import ensure_not_worse_than_smaller_N

    palette = [RED, WHITE]
    targets = np.asarray([[230, 150, 150], [250, 250, 250]], dtype=np.uint8)
    baseline = np.zeros((2, 12), dtype=np.int32)
    _matched, recipes, delta_e, stats = ensure_not_worse_than_smaller_N(
        targets,
        palette,
        np.asarray([[180, 30, 25], [180, 30, 25]], dtype=np.uint8),
        baseline,
        np.asarray([40.0, 60.0], dtype=np.float64),
        target_layer_count=12,
        layer_height_mm=DEFAULT_LAYER_HEIGHT_MM,
        substrate="white",
    )

    assert stats["applied"] is True
    assert stats["improved_pixels"] > 0
    assert all(int(k) <= MITM_MAX_LAYER_COUNT for k in stats["per_k_improved"])
    assert recipes.shape == (2, 12)
    assert np.all(delta_e <= np.asarray([40.0, 60.0]))
