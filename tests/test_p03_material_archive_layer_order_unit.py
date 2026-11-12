"""Regression tests for the p03 material-archive layer-order convention.

The solver and on-disk cache use ``Bottom2Top`` (index 0 = substrate-adjacent),
but S06 voxel builders and the rest of the pipeline consume ``material_matrix``
as ``Top2Bottom`` (index 0 = viewing surface). The conversion happens exactly
once inside :func:`core.pipeline.p03_core_processing._run_material_archive_branch`.

These tests lock in that invariant so a future refactor cannot silently
re-introduce the inverted-stack bug.

求解器与缓存使用 ``Bottom2Top`` 约定（索引 0 贴基底），但 S06 体素构建器
以及 3MF 管道下游假设 ``material_matrix`` 为 ``Top2Bottom`` 约定（索引 0 =
观赏面）。``_run_material_archive_branch`` 中一次性反转列序完成转换，本文件
锁定该不变量。
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
    forward_model,
    linear_to_srgb_uint8,
)
from core.pipeline.p03_core_processing import _run_material_archive_branch


class _FakeCache:
    """Minimal stub that mimics MaterialSolverCache for P03 on-the-fly path."""

    def __init__(self, matched_rgb, recipes, delta_e, layer_count):
        self._matched_rgb = matched_rgb
        self._recipes = recipes
        self._delta_e = delta_e
        self._layer_count = layer_count
        self.valid_cell_count = 1
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


def _patch_solver_runtime(
    monkeypatch: pytest.MonkeyPatch,
    fake_cache: _FakeCache,
    calls: dict[str, int],
) -> None:
    import core.material_lut_provider as provider

    def fake_load_solver_runtime(*args, **kwargs):
        calls["runtime"] += 1
        return fake_cache, 64

    monkeypatch.setattr(provider, "load_solver_runtime", fake_load_solver_runtime)
    monkeypatch.setattr(
        "core.material_cache.build_material_solver_cache",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("P03 fallback must not call old bucketed builder")
        ),
    )


# ---------------------------------------------------------------------------
# Fixtures
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


# Five distinct materials so an asymmetric recipe [0, 1, 2, 3, 4] clearly
# differs from its reverse [4, 3, 2, 1, 0].
MAT_0 = _mat("M0", E=(0.9, 0.1, 0.1), k=(4.0, 4.0, 4.0))
MAT_1 = _mat("M1", E=(0.1, 0.9, 0.1), k=(4.0, 4.0, 4.0))
MAT_2 = _mat("M2", E=(0.1, 0.1, 0.9), k=(4.0, 4.0, 4.0))
MAT_3 = _mat("M3", E=(0.8, 0.8, 0.1), k=(4.0, 4.0, 4.0))
MAT_4 = _mat("M4", E=(0.1, 0.8, 0.8), k=(4.0, 4.0, 4.0))
PALETTE = [MAT_0, MAT_1, MAT_2, MAT_3, MAT_4]


def _write_solid_color_png(path: Path, rgb: tuple[int, int, int], size: int = 4) -> Path:
    arr = np.zeros((size, size, 4), dtype=np.uint8)
    arr[..., 0] = rgb[0]
    arr[..., 1] = rgb[1]
    arr[..., 2] = rgb[2]
    arr[..., 3] = 255
    Image.fromarray(arr, mode="RGBA").save(path)
    return path


def _make_ctx(image_path: Path) -> dict:
    return {
        "image_path": str(image_path),
        "target_width_mm": 2.0,  # -> 20 px wide at PIXELS_PER_MM=10
        "modeling_mode": ModelingMode.PIXEL,
        "quantize_colors": 2,
        "_material_params": PALETTE,
        "color_layers": 5,
        "layer_height_mm": DEFAULT_LAYER_HEIGHT_MM,
        "material_substrate": "white",
        "material_source": "material_archive",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestLayerOrderConversion:
    """``material_matrix`` must carry Top2Bottom, reversed relative to solver."""

    def test_asymmetric_recipe_is_reversed_into_material_matrix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A deterministic asymmetric solver recipe [0,1,2,3,4] must surface
        as [4,3,2,1,0] along the last axis of ``material_matrix``.
        """
        image_path = _write_solid_color_png(tmp_path / "red.png", (220, 40, 30))
        ctx = _make_ctx(image_path)

        # Mock the on-the-fly cache to return a known asymmetric recipe.
        recipe_bottom_to_top = np.asarray([[0, 1, 2, 3, 4]], dtype=np.int32)
        mocked_matched_rgb = np.asarray([[220, 40, 30]], dtype=np.uint8)
        mocked_delta_e = np.asarray([0.0], dtype=np.float64)
        fake_cache = _FakeCache(mocked_matched_rgb, recipe_bottom_to_top, mocked_delta_e, 5)

        calls = {"runtime": 0}
        _patch_solver_runtime(monkeypatch, fake_cache, calls)

        result = _run_material_archive_branch(ctx)
        assert calls["runtime"] == 1
        assert result["original_matched_rgb"] is result["matched_rgb"]
        assert result["height_identity_rgb"] is result["matched_rgb"]
        assert result["original_material_matrix"] is result["material_matrix"]

        material_matrix = result["material_matrix"]
        assert material_matrix.ndim == 3
        H, W, N = material_matrix.shape
        assert N == 5

        # Every non-transparent pixel in a solid-color image should carry the
        # reversed recipe: [4, 3, 2, 1, 0].
        expected_top_to_bottom = np.asarray([4, 3, 2, 1, 0], dtype=np.int32)
        mask_solid = result["mask_solid"]
        assert mask_solid.any()
        for y, x in np.argwhere(mask_solid):
            np.testing.assert_array_equal(
                material_matrix[y, x, :].astype(np.int32),
                expected_top_to_bottom,
                err_msg=(
                    "material_matrix[y,x,:] should be solver-recipe reversed "
                    "(Top2Bottom ordering)."
                ),
            )

    @pytest.mark.parametrize("generation", [False, True], ids=["preview", "generation"])
    def test_preview_replacements_keep_pristine_rgb_recipe_and_height_identity(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, generation: bool,
    ) -> None:
        """Initial/re-preview replacements must not become reset/height identity."""

        image_path = _write_solid_color_png(
            tmp_path / "replacement.png",
            (220, 40, 30),
        )
        ctx = _make_ctx(image_path)
        ctx["enable_cleanup"] = False
        ctx["replacement_regions"] = [
            {
                "quantized_hex": "#dc281e",
                "matched_hex": "#dc281e",
                "replacement_hex": "#0c2238",
            }
        ]

        pristine_rgb = np.asarray([[220, 40, 30]], dtype=np.uint8)
        pristine_recipe_bottom_to_top = np.asarray(
            [[0, 1, 2, 3, 4]],
            dtype=np.int32,
        )
        fake_cache = _FakeCache(
            pristine_rgb,
            pristine_recipe_bottom_to_top,
            np.asarray([0.0], dtype=np.float64),
            5,
        )
        _patch_solver_runtime(monkeypatch, fake_cache, {"runtime": 0})

        achieved_rgb = np.asarray([12, 34, 56], dtype=np.uint8)
        replacement_calls = []

        def fake_apply(
            matched_rgb,
            material_matrix,
            *_args,
            **_kwargs,
        ):
            replacement_calls.append(True)
            replaced_rgb = np.full_like(matched_rgb, achieved_rgb)
            replaced_matrix = np.full_like(material_matrix, 4)
            return replaced_rgb, replaced_matrix, 1

        monkeypatch.setattr(
            "core.pipeline.s03_color_replacement._apply_material_archive_color_replacements",
            fake_apply,
        )

        if generation:
            from core.pipeline import s02_image_processing, s03_color_replacement

            ctx["material_source"] = "material_archive"
            result = s03_color_replacement.run(s02_image_processing.run(ctx))
        else:
            result = _run_material_archive_branch(ctx)

        assert len(replacement_calls) == 1
        assert np.all(result["matched_rgb"][result["mask_solid"]] == achieved_rgb)
        assert np.all(result["material_matrix"][result["mask_solid"]] == 4)
        assert np.all(
            result["original_matched_rgb"][result["mask_solid"]]
            == pristine_rgb[0]
        )
        assert np.all(
            result["height_identity_rgb"][result["mask_solid"]]
            == pristine_rgb[0]
        )
        np.testing.assert_array_equal(
            result["original_material_matrix"][result["mask_solid"]][0],
            np.asarray([4, 3, 2, 1, 0], dtype=np.int32),
        )

    def test_forward_model_on_reversed_material_matrix_matches_matched_rgb(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Feeding ``material_matrix[y,x,::-1]`` back through ``forward_model``
        (which consumes Bottom2Top recipes) must reproduce the achieved color
        for each solid pixel, closing the loop on the convention.
        """
        image_path = _write_solid_color_png(tmp_path / "mix.png", (130, 90, 180))
        ctx = _make_ctx(image_path)

        recipe_bottom_to_top = np.asarray([[2, 0, 4, 1, 3]], dtype=np.int32)
        # Compute the ground-truth achieved color by running the forward
        # model on the (Bottom2Top) recipe ourselves.
        predicted_linear = forward_model(
            recipe_bottom_to_top[0],
            PALETTE,
            DEFAULT_LAYER_HEIGHT_MM,
            substrate_linear=np.ones(3, dtype=np.float64),
        )
        predicted_srgb = linear_to_srgb_uint8(predicted_linear.reshape(1, 3))[0]
        fake_cache = _FakeCache(
            predicted_srgb.reshape(1, 3), recipe_bottom_to_top,
            np.asarray([0.0], dtype=np.float64), 5,
        )

        calls = {"runtime": 0}
        _patch_solver_runtime(monkeypatch, fake_cache, calls)

        result = _run_material_archive_branch(ctx)
        assert calls["runtime"] == 1

        material_matrix = result["material_matrix"]
        mask_solid = result["mask_solid"]
        assert mask_solid.any()

        # Pick any solid pixel; reverse material_matrix back into Bottom2Top
        # and feed it through forward_model. The predicted color must match
        # the solver's matched_rgb for that pixel.
        y, x = map(int, np.argwhere(mask_solid)[0])
        recipe_recovered = material_matrix[y, x, ::-1].astype(np.int32)
        np.testing.assert_array_equal(recipe_recovered, recipe_bottom_to_top[0])

        recovered_linear = forward_model(
            recipe_recovered,
            PALETTE,
            DEFAULT_LAYER_HEIGHT_MM,
            substrate_linear=np.ones(3, dtype=np.float64),
        )
        recovered_srgb = linear_to_srgb_uint8(recovered_linear.reshape(1, 3))[0]
        matched_rgb = result["matched_rgb"][y, x]

        # Forward-model reproduction should be exact up to sRGB rounding.
        assert np.max(np.abs(recovered_srgb.astype(int) - matched_rgb.astype(int))) <= 1

    def test_single_layer_recipe_is_identity_under_reversal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """For ``layer_count == 1`` the reversal is a no-op and the pipeline
        must still emit a coherent ``material_matrix``.
        """
        image_path = _write_solid_color_png(tmp_path / "green.png", (30, 200, 60))
        ctx = _make_ctx(image_path)
        ctx["color_layers"] = 1

        recipe = np.asarray([[2]], dtype=np.int32)
        mocked_matched_rgb = np.asarray([[30, 200, 60]], dtype=np.uint8)
        mocked_delta_e = np.asarray([0.0], dtype=np.float64)
        fake_cache = _FakeCache(mocked_matched_rgb, recipe, mocked_delta_e, 1)

        calls = {"runtime": 0}
        _patch_solver_runtime(monkeypatch, fake_cache, calls)

        result = _run_material_archive_branch(ctx)
        assert calls["runtime"] == 1
        material_matrix = result["material_matrix"]
        assert material_matrix.shape[-1] == 1
        mask_solid = result["mask_solid"]
        assert mask_solid.any()
        for y, x in np.argwhere(mask_solid):
            assert int(material_matrix[y, x, 0]) == 2

    def test_api_replacement_regions_are_replayed_for_preview(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Refreshing a material-archive preview must replay global replaces."""
        image_path = _write_solid_color_png(tmp_path / "orange.png", (200, 100, 50))
        ctx = _make_ctx(image_path)
        ctx["enable_cleanup"] = False
        ctx["replacement_regions"] = [
            {
                "matched": "#c86432",
                "replacement": "#14c814",
            }
        ]

        initial_cache = _FakeCache(
            np.asarray([[200, 100, 50]], dtype=np.uint8),
            np.asarray([[0, 1, 2, 3, 4]], dtype=np.int32),
            np.asarray([0.0], dtype=np.float64),
            5,
        )
        replacement_cache = _FakeCache(
            np.asarray([[10, 200, 20]], dtype=np.uint8),
            np.asarray([[0, 1, 2, 3, 4]], dtype=np.int32),
            np.asarray([0.0], dtype=np.float64),
            5,
        )

        import core.material_lut_provider as provider

        calls = {"cache": 0, "runtime": 0}

        def fake_load_solver_cache(*args, **kwargs):
            calls["cache"] += 1
            if calls["cache"] == 1:
                return None, 64
            return replacement_cache, 64

        def fake_load_solver_runtime(*args, **kwargs):
            calls["runtime"] += 1
            return initial_cache, 64

        def fake_not_worse(
            unique_colors,
            materials,
            matched_rgb,
            recipes,
            delta_e,
            **kwargs,
        ):
            return matched_rgb, recipes, delta_e, {
                "applied": False,
                "improved_pixels": 0,
            }

        monkeypatch.setattr(provider, "load_solver_cache", fake_load_solver_cache)
        monkeypatch.setattr(provider, "load_solver_runtime", fake_load_solver_runtime)
        monkeypatch.setattr(
            "core.material_lut_synthesis.ensure_not_worse_than_smaller_N",
            fake_not_worse,
        )
        monkeypatch.setattr(
            "core.material_cache.build_material_solver_cache",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("P03 fallback must not call old bucketed builder")
            ),
        )

        result = _run_material_archive_branch(ctx)

        assert calls["runtime"] == 1
        assert calls["cache"] >= 2
        mask_solid = result["mask_solid"]
        assert mask_solid.any()
        np.testing.assert_array_equal(
            result["matched_rgb"][mask_solid][0],
            np.asarray([10, 200, 20], dtype=np.uint8),
        )
        assert np.all(result["matched_rgb"][mask_solid] == [10, 200, 20])
        expected_top_to_bottom = np.asarray([4, 3, 2, 1, 0], dtype=np.int32)
        for y, x in np.argwhere(mask_solid):
            np.testing.assert_array_equal(
                result["material_matrix"][y, x, :].astype(np.int32),
                expected_top_to_bottom,
            )
