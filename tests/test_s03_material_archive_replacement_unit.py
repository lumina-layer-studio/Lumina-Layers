"""Regression tests for S03 global color replacements in material-archive mode.

Historically, when ``ctx["material_source"] == "material_archive"`` (no LUT
processor) every queued color replacement was dropped with a warning, which
made the picker silently ignore replacements for material-archive workflows.
This module locks in the new behavior: the S03 step re-solves every
``(orig_hex → repl_hex)`` pair against the saved ``MaterialParams`` palette
and writes both ``matched_rgb`` and ``material_matrix`` atomically.
"""

from __future__ import annotations

import os
import pickle
from unittest.mock import patch

import numpy as np
import pytest

from core.material_color_solver import MaterialParams
from core.material_dynamic_solver import DynamicMaterialSolverError
from core.pipeline.s03_color_replacement import (
    _apply_dynamic_material_archive_color_replacements,
    _apply_material_archive_color_replacements,
    run,
)


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


_SMALL_PALETTE = [
    _mat("Red", E=(0.6, 0.05, 0.05), k=(4.0, 4.0, 4.0)),
    _mat("Blue", E=(0.05, 0.1, 0.6), k=(4.0, 4.0, 4.0)),
    _mat("White", E=(0.95, 0.95, 0.95), k=(0.5, 0.5, 0.5)),
]


def test_dynamic_replacement_resolves_complete_current_target_set() -> None:
    matched = np.asarray([[[100, 0, 0], [0, 100, 0]]], dtype=np.uint8)
    matrix = np.zeros((1, 2, 7), dtype=np.int32)
    solid = np.ones((1, 2), dtype=bool)
    seen_entry = {
        "target_srgb": [10, 20, 30],
        "matched_srgb": [11, 22, 33],
        "actual_layer_count": 5,
        "padding_layer_count": 2,
        "actual_recipe_top_to_bottom": [0, 1, 2, 1, 0],
        "print_recipe_top_to_bottom": [0, 1, 2, 1, 0, 2, 2],
        "layer_cap_options": [
            {"max_effective_layer_count": 5, "delta_e00": 1.0},
            {"max_effective_layer_count": 6, "delta_e00": 0.8},
            {"max_effective_layer_count": 7, "delta_e00": 0.7},
        ],
    }
    unseen_entry = {
        "target_srgb": [40, 50, 60],
        "matched_srgb": [44, 55, 66],
        "actual_layer_count": 6,
        "padding_layer_count": 1,
        "actual_recipe_top_to_bottom": [1, 2, 1, 0, 1, 2],
        "print_recipe_top_to_bottom": [1, 2, 1, 0, 1, 2, 2],
        "layer_cap_options": [
            {"max_effective_layer_count": 5, "delta_e00": 2.0},
            {"max_effective_layer_count": 6, "delta_e00": 1.5},
            {"max_effective_layer_count": 7, "delta_e00": 1.0},
        ],
    }
    existing_info = {
        "enabled": True,
        "min_layer_count": 5,
        "max_layer_count": 7,
        "delta_e00_tolerance": 0.5,
        "engine": "numba",
        "colors": [seen_entry],
        "benefit_curve": [],
    }
    new_info = {
        **existing_info,
        "colors": [seen_entry, unseen_entry],
    }

    with patch(
        "core.pipeline.s03_color_replacement._solve_dynamic_material_targets",
        return_value=(
            np.asarray([[11, 22, 33], [44, 55, 66]], dtype=np.uint8),
            np.asarray(
                [
                    seen_entry["print_recipe_top_to_bottom"],
                    unseen_entry["print_recipe_top_to_bottom"],
                ],
                dtype=np.int32,
            ),
            np.asarray([0.7, 1.0], dtype=np.float64),
            new_info,
            {"dynamic_engine": "numba"},
        ),
    ) as exact_solve:
        (
            out_rgb,
            out_matrix,
            applied,
            merged_info,
            solver_info,
            updated_target_map,
        ) = (
            _apply_dynamic_material_archive_color_replacements(
                matched,
                matrix,
                solid,
                matched.copy(),
                {
                    "#640000": "#0a141e",
                    "#006400": "#28323c",
                },
                _SMALL_PALETTE,
                backing_material_index=2,
                min_layer_count=5,
                max_layer_count=7,
                delta_e00_tolerance=0.5,
                layer_height_mm=0.08,
                substrate="white",
                dynamic_layer_info=existing_info,
                material_solver_info={"path": "dynamic_exact"},
            )
        )

    np.testing.assert_array_equal(
        exact_solve.call_args.kwargs["unique_colors"],
        np.asarray([[10, 20, 30], [40, 50, 60]], dtype=np.uint8),
    )
    assert applied == 2
    assert out_matrix.shape == (1, 2, 7)
    np.testing.assert_array_equal(out_rgb[0, 0], [11, 22, 33])
    np.testing.assert_array_equal(out_rgb[0, 1], [44, 55, 66])
    np.testing.assert_array_equal(
        updated_target_map,
        np.asarray([[[10, 20, 30], [40, 50, 60]]], dtype=np.uint8),
    )
    assert [entry["target_srgb"] for entry in merged_info["colors"]] == [
        [10, 20, 30],
        [40, 50, 60],
    ]
    assert solver_info["dynamic_engine"] == "numba"


def test_dynamic_replacement_benefit_uses_target_map_on_matched_collision() -> None:
    source_a = [100, 0, 0]
    source_b = [0, 100, 0]
    target_a = [10, 20, 30]
    target_b = [40, 50, 60]
    matched = [9, 9, 9]
    input_rgb = np.asarray([[source_a, source_b, source_b, source_b]], dtype=np.uint8)
    target_map = input_rgb.copy()

    def entry(target, delta, recipe):
        return {
            "target_srgb": target,
            "matched_srgb": matched,
            "actual_layer_count": 5,
            "padding_layer_count": 2,
            "actual_recipe_top_to_bottom": recipe[:5],
            "print_recipe_top_to_bottom": recipe,
            "layer_cap_options": [
                {"max_effective_layer_count": cap, "delta_e00": delta}
                for cap in (5, 6, 7)
            ],
        }

    info = {
        "enabled": True,
        "min_layer_count": 5,
        "max_layer_count": 7,
        "delta_e00_tolerance": 0.5,
        "colors": [
            entry(target_a, 1.0, [0, 1, 0, 1, 0, 2, 2]),
            entry(target_b, 3.0, [1, 0, 1, 0, 1, 2, 2]),
        ],
        "benefit_curve": [],
    }

    info["benefit_curve"] = [
        {
            "max_effective_layer_count": 5,
            "weighted_mean_delta_e00": 2.5,
            "marginal_delta_e00_reduction": 0.0,
        }
    ]
    with patch(
        "core.pipeline.s03_color_replacement._solve_dynamic_material_targets",
        return_value=(
            np.asarray([matched, matched], dtype=np.uint8),
            np.asarray(
                [
                    info["colors"][0]["print_recipe_top_to_bottom"],
                    info["colors"][1]["print_recipe_top_to_bottom"],
                ],
                dtype=np.int32,
            ),
            np.asarray([1.0, 3.0], dtype=np.float64),
            info,
            {"dynamic_engine": "numba"},
        ),
    ) as exact_solve:
        (
            _out_rgb,
            _out_matrix,
            applied,
            merged_info,
            _solver_info,
            updated_target_map,
        ) = _apply_dynamic_material_archive_color_replacements(
            input_rgb,
            np.zeros((1, 4, 7), dtype=np.int32),
            np.ones((1, 4), dtype=bool),
            target_map,
            {"#640000": "#0a141e", "#006400": "#28323c"},
            _SMALL_PALETTE,
            backing_material_index=2,
            min_layer_count=5,
            max_layer_count=7,
            delta_e00_tolerance=0.5,
            layer_height_mm=0.08,
            substrate="white",
            dynamic_layer_info=info,
            material_solver_info={"path": "dynamic_exact"},
        )

    assert applied == 2
    np.testing.assert_array_equal(
        exact_solve.call_args.kwargs["pixel_counts"],
        np.asarray([1, 3], dtype=np.int64),
    )
    assert merged_info["benefit_curve"][0]["weighted_mean_delta_e00"] == 2.5
    np.testing.assert_array_equal(
        updated_target_map,
        np.asarray([[target_a, target_b, target_b, target_b]], dtype=np.uint8),
    )


def _make_material_archive_ctx(
    color_replacements: dict[str, str] | None = None,
) -> dict:
    """Mirror ``s01_input_validation`` outputs for material-archive mode."""
    h, w = 3, 4
    matched_rgb = np.full((h, w, 3), [200, 100, 50], dtype=np.uint8)
    # First column stays "Blue-ish" so we can exercise selective replacement.
    matched_rgb[:, 0] = [50, 70, 200]
    material_matrix = np.zeros((h, w, 5), dtype=np.int32)
    mask_solid = np.ones((h, w), dtype=bool)

    return {
        "matched_rgb": matched_rgb,
        "material_matrix": material_matrix,
        "mask_solid": mask_solid,
        "processor": None,  # material-archive has no LUT processor
        "color_replacements": color_replacements,
        "replacement_regions": None,
        "matched_rgb_path": None,
        "material_matrix_path": None,
        "material_source": "material_archive",
        "_material_params": _SMALL_PALETTE,
        "color_layers": 5,
        "layer_height_mm": 0.08,
        "material_substrate": "white",
    }


class TestApplyMaterialArchiveColorReplacements:
    """Unit tests for the helper that performs the actual solve + write."""

    def test_empty_replacements_returns_inputs(self):
        matched = np.full((2, 2, 3), 100, dtype=np.uint8)
        mat = np.zeros((2, 2, 5), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)
        out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
            matched, mat, mask, {}, _SMALL_PALETTE, 5, 0.08, "white",
        )
        assert applied == 0
        assert out_rgb is matched
        assert out_mat is mat

    def test_empty_materials_returns_inputs(self):
        matched = np.full((2, 2, 3), 100, dtype=np.uint8)
        mat = np.zeros((2, 2, 5), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)
        out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
            matched, mat, mask, {"#646464": "#c80000"}, [], 5, 0.08, "white",
        )
        assert applied == 0
        assert out_rgb is matched
        assert out_mat is mat

    def test_skips_orig_not_present(self):
        matched = np.full((2, 2, 3), [200, 100, 50], dtype=np.uint8)
        mat = np.zeros((2, 2, 5), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)
        out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
            # orig=rgb(10,20,30) never appears in matched
            matched, mat, mask, {"#0a141e": "#ff0000"},
            _SMALL_PALETTE, 5, 0.08, "white",
        )
        assert applied == 0
        np.testing.assert_array_equal(out_rgb, matched)
        np.testing.assert_array_equal(out_mat, mat)

    def test_replaces_matching_pixels_and_updates_material_matrix(self):
        matched = np.full((3, 4, 3), [200, 100, 50], dtype=np.uint8)
        # One column of a different color to check selectivity.
        matched[:, 0] = [50, 70, 200]
        mat = np.zeros((3, 4, 5), dtype=np.int32)
        mask = np.ones((3, 4), dtype=bool)
        out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
            matched, mat, mask, {"#c86432": "#14c814"},
            _SMALL_PALETTE, 5, 0.08, "white",
        )
        assert applied == 1
        # Non-matching pixel (col 0) stays untouched.
        np.testing.assert_array_equal(out_rgb[:, 0], matched[:, 0])
        np.testing.assert_array_equal(out_mat[:, 0], mat[:, 0])
        # Matching pixels (cols 1..3) have been updated to the solver result.
        updated_rgb = out_rgb[:, 1:]
        updated_mat = out_mat[:, 1:]
        # All updated pixels have the same achieved color (single solve per target).
        assert np.all(updated_rgb == updated_rgb[0, 0])
        # Material indices must be valid.
        assert np.all(updated_mat >= 0)
        assert np.all(updated_mat < len(_SMALL_PALETTE))
        # And the recipe should not be entirely zeros (implying an actual solve).
        assert np.any(updated_mat != 0)

    def test_resolved_source_mask_does_not_replace_same_match_outside_region(self):
        matched = np.full((1, 3, 3), [200, 100, 50], dtype=np.uint8)
        matrix = np.zeros((1, 3, 5), dtype=np.int32)
        selected = np.array([[True, True, False]])
        out_rgb, out_matrix, applied = _apply_material_archive_color_replacements(
            matched,
            matrix,
            np.ones((1, 3), dtype=bool),
            [("#14c814", selected)],
            _SMALL_PALETTE,
            5,
            0.08,
            "white",
        )
        assert applied == 1
        assert np.any(out_matrix[selected] != matrix[selected])
        np.testing.assert_array_equal(out_rgb[~selected], matched[~selected])
        np.testing.assert_array_equal(out_matrix[~selected], matrix[~selected])

    def test_short_solver_recipe_trims_long_material_matrix(self):
        matched = np.full((2, 2, 3), [200, 100, 50], dtype=np.uint8)
        mat = np.zeros((2, 2, 7), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)

        class _StubCache:
            def lookup(self, unique_srgb, user_materials):
                n = unique_srgb.shape[0]
                return (
                    np.full((n, 3), [10, 200, 20], dtype=np.uint8),
                    np.asarray([[0, 1, 2, 3, 4]] * n, dtype=np.int32),
                    np.full(n, 0.5, dtype=np.float32),
                )

        with patch(
            "core.material_cache.load_material_solver_cache",
            return_value=_StubCache(),
        ), patch(
            "core.material_lut_synthesis.solve_image_colors_optimal",
            side_effect=AssertionError(
                "MITM should not run when cache is available"
            ),
        ):
            out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
                matched, mat, mask, {"#c86432": "#14c814"},
                _SMALL_PALETTE, 5, 0.08, "white",
            )

        assert applied == 1
        assert out_mat.shape == (2, 2, 5)
        np.testing.assert_array_equal(out_rgb[0, 0], [10, 200, 20])
        np.testing.assert_array_equal(out_mat[0, 0], [4, 3, 2, 1, 0])

    def test_ignores_invalid_hex_pairs(self):
        matched = np.full((2, 2, 3), [200, 100, 50], dtype=np.uint8)
        mat = np.zeros((2, 2, 5), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)
        out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
            matched, mat, mask,
            {"not-a-hex": "#ff0000", "#c86432": "also-bad"},
            _SMALL_PALETTE, 5, 0.08, "white",
        )
        # Both pairs rejected → no change.
        assert applied == 0
        np.testing.assert_array_equal(out_rgb, matched)
        np.testing.assert_array_equal(out_mat, mat)

    def test_solver_failure_does_not_crash(self):
        matched = np.full((2, 2, 3), [200, 100, 50], dtype=np.uint8)
        mat = np.zeros((2, 2, 5), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)
        with patch(
            "core.material_lut_synthesis.solve_image_colors_optimal",
            side_effect=RuntimeError("fake solver failure"),
        ), patch(
            "core.material_cache.load_material_solver_cache",
            return_value=None,
        ):
            out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
                matched, mat, mask, {"#c86432": "#14c814"},
                _SMALL_PALETTE, 5, 0.08, "white",
            )
        assert applied == 0
        np.testing.assert_array_equal(out_rgb, matched)
        np.testing.assert_array_equal(out_mat, mat)

    def test_respects_mask_solid(self):
        matched = np.full((3, 4, 3), [200, 100, 50], dtype=np.uint8)
        mat = np.zeros((3, 4, 5), dtype=np.int32)
        # Only row 0 is solid.
        mask = np.zeros((3, 4), dtype=bool)
        mask[0, :] = True
        out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
            matched, mat, mask, {"#c86432": "#14c814"},
            _SMALL_PALETTE, 5, 0.08, "white",
        )
        assert applied == 1
        # Row 0 updated
        assert np.all(out_rgb[0] != matched[0])
        # Row 1+ untouched (outside mask_solid)
        np.testing.assert_array_equal(out_rgb[1:], matched[1:])
        np.testing.assert_array_equal(out_mat[1:], mat[1:])

    def test_uses_cache_when_available(self):
        """When a cache exists it should be used instead of MITM."""
        matched = np.full((2, 2, 3), [200, 100, 50], dtype=np.uint8)
        mat = np.zeros((2, 2, 5), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)

        class _StubCache:
            def lookup(self, unique_srgb, user_materials):
                n = unique_srgb.shape[0]
                return (
                    # Return a deterministic achieved color.
                    np.full((n, 3), [10, 200, 20], dtype=np.uint8),
                    np.zeros((n, 5), dtype=np.int32),
                    np.full(n, 0.5, dtype=np.float32),
                )

        with patch(
            "core.material_cache.load_material_solver_cache",
            return_value=_StubCache(),
        ), patch(
            "core.material_lut_synthesis.solve_image_colors_optimal",
            side_effect=AssertionError(
                "MITM should not run when cache is available"
            ),
        ):
            out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
                matched, mat, mask, {"#c86432": "#14c814"},
                _SMALL_PALETTE, 5, 0.08, "white",
            )
        assert applied == 1
        # All originally matching pixels now carry the stubbed achieved color.
        np.testing.assert_array_equal(out_rgb[0, 0], [10, 200, 20])


class TestS03RunMaterialArchiveBranch:
    """Integration checks: the S03 run() step dispatches to the helper."""

    def test_recipe_matrix_authority_is_scoped_after_global_replacement(
        self,
        tmp_path,
    ) -> None:
        """Real prepare keeps archive global stacks outside recipe coverage."""

        from api.routers.converter.generate import (
            _prepare_recipe_override_worker_inputs,
        )
        from api.schemas.converter import ConvertGenerateRequest
        from api.session_store import SessionStore

        ctx = _make_material_archive_ctx({"#c86432": "#14c814"})
        recipe_mask = np.zeros(ctx["mask_solid"].shape, dtype=bool)
        recipe_mask[0, 1] = True
        recipe_overrides = [
            {
                "region_id": "region-1",
                "recipe": [2, 2, 2, 2, 2],
                "layer_order": "Top2Bottom",
            }
        ]
        store = SessionStore(ttl=1800)
        sid = store.create()
        session_data = {
            "material_source": "material_archive",
            "selected_region_masks": {"region-1": recipe_mask},
        }
        request = ConvertGenerateRequest(
            lut_name="__material_archive__",
            color_layers=5,
            recipe_overrides=recipe_overrides,
        )
        matrix_path, masks_path = _prepare_recipe_override_worker_inputs(
            cache={
                "material_matrix": ctx["material_matrix"].copy(),
                "mask_solid": ctx["mask_solid"].copy(),
                "lut_metadata": None,
            },
            session_data=session_data,
            recipe_overrides=recipe_overrides,
            request=request,
            sid=sid,
            store=store,
        )
        assert matrix_path is not None
        assert masks_path is not None
        prepared_matrix = np.load(matrix_path)
        assert np.all(prepared_matrix[recipe_mask] == 2)
        assert np.all(prepared_matrix[~recipe_mask] == 0)

        authority_mask_path = tmp_path / "archive-recipe-authority.npy"
        np.save(authority_mask_path, recipe_mask)
        ctx.update(
            {
                "material_matrix_path": matrix_path,
                "final_material_matrix_is_authoritative": True,
                "final_material_matrix_authority_mask_path": os.fspath(
                    authority_mask_path
                ),
                "recipe_overrides": recipe_overrides,
                # Large-format tiles consume the prepared matrix and do not
                # re-run the whole-image recipe mask artifact in the worker.
                "recipe_override_masks_path": None,
            }
        )

        solved_recipe = np.asarray([0, 1, 2, 1, 0], dtype=np.int32)

        class _StubCache:
            @staticmethod
            def lookup(targets, _materials):
                count = targets.shape[0]
                return (
                    np.tile(
                        np.asarray([[10, 200, 20]], dtype=np.uint8),
                        (count, 1),
                    ),
                    np.tile(solved_recipe, (count, 1)),
                    np.full(count, 0.5, dtype=np.float32),
                )

        def _keep_baseline(
            _targets,
            _materials,
            matched_rgb_unique,
            recipes_unique,
            delta_e,
            **_kwargs,
        ):
            return matched_rgb_unique, recipes_unique, delta_e, {
                "applied": False,
                "improved_pixels": 0,
            }

        try:
            with patch(
                "core.material_lut_provider.load_solver_cache",
                return_value=(_StubCache(), 64),
            ), patch(
                "core.material_lut_synthesis.ensure_not_worse_than_smaller_N",
                side_effect=_keep_baseline,
            ):
                result = run(ctx)

            # Solver recipes are Bottom2Top; S03 stores Top2Bottom.
            expected_global_recipe = solved_recipe[::-1]
            global_only_mask = np.zeros(recipe_mask.shape, dtype=bool)
            global_only_mask[:, 1:] = True
            global_only_mask &= ~recipe_mask
            assert np.all(
                result["material_matrix"][global_only_mask]
                == expected_global_recipe
            )
            assert np.all(result["material_matrix"][recipe_mask] == 2)
            assert np.all(result["material_matrix"][:, 0] == 0)
            assert np.all(result["matched_rgb"][:, 1:] == [10, 200, 20])
        finally:
            store.clear_all()

    def test_recipe_override_virtual_material_extends_export_palette(self, tmp_path):
        """Material-archive generation must register virtual recipe channels.

        The apply endpoint can write a recipe such as ``[N, N, ...]`` where
        ``N`` is the first virtual material after the selected archive
        materials. During real generation, S03 receives that material matrix
        from disk and must also extend ``slot_names`` / ``preview_colors`` so
        S07 can emit a mesh for channel ``N`` instead of leaving the region as
        unmapped air.
        """
        ctx = _make_material_archive_ctx(None)
        native_count = len(_SMALL_PALETTE)
        mask = np.zeros(ctx["mask_solid"].shape, dtype=bool)
        mask[1:, 1:3] = True

        override_matrix = ctx["material_matrix"].copy()
        override_matrix[mask] = native_count
        matrix_path = tmp_path / "material_matrix.npy"
        np.save(matrix_path, override_matrix)

        masks_path = tmp_path / "recipe_masks.pkl"
        with open(masks_path, "wb") as f:
            pickle.dump({"region-1": mask}, f)

        ctx.update(
            {
                "slot_names": ["Red", "Blue", "White"],
                "preview_colors": {
                    0: [153, 13, 13, 255],
                    1: [13, 26, 153, 255],
                    2: [242, 242, 242, 255],
                },
                "color_conf": {
                    "slots": ["Red", "Blue", "White"],
                    "preview": {
                        0: [153, 13, 13, 255],
                        1: [13, 26, 153, 255],
                        2: [242, 242, 242, 255],
                    },
                },
                "material_matrix_path": os.fspath(matrix_path),
                "recipe_override_masks_path": os.fspath(masks_path),
                "recipe_overrides": [
                    {
                        "region_id": "region-1",
                        "recipe": [native_count] * ctx["material_matrix"].shape[2],
                        "layer_order": "Top2Bottom",
                        "virtual_materials": [
                            {"name": "Black", "hex": "#111111"}
                        ],
                    }
                ],
            }
        )

        result = run(ctx)

        assert result["slot_names"][native_count] == "Black"
        assert result["preview_colors"][native_count] == [17, 17, 17, 255]
        assert result["color_conf"]["slots"][native_count] == "Black"
        assert result["color_conf"]["preview"][native_count] == [17, 17, 17, 255]
        assert np.all(result["material_matrix"][mask] == native_count)

    def test_dynamic_recipe_override_uses_saved_full_print_recipe(self, tmp_path):
        ctx = _make_material_archive_ctx(None)
        mask = np.zeros(ctx["mask_solid"].shape, dtype=bool)
        mask[1:, 1:3] = True
        masks_path = tmp_path / "dynamic_recipe_masks.pkl"
        with open(masks_path, "wb") as file_obj:
            pickle.dump({"region-1": mask}, file_obj)

        actual = [2, 1, 0, 1, 1]
        print_recipe = [2, 1, 0, 1, 1, 2, 2]
        ctx.update(
            {
                "material_dynamic_layer_count_enabled": True,
                "material_min_layer_count": 5,
                "material_max_layer_count": 7,
                "material_backing_material_index": 2,
                "color_layers": 7,
                "material_matrix": np.zeros((3, 4, 7), dtype=np.int32),
                "quantized_image": ctx["matched_rgb"].copy(),
                "recipe_override_masks_path": os.fspath(masks_path),
                "recipe_overrides": [
                    {
                        "region_id": "region-1",
                        "recipe": actual,
                        "layer_order": "Top2Bottom",
                        "color_layers": 5,
                        "actual_recipe_top_to_bottom": actual,
                        "print_recipe_top_to_bottom": print_recipe,
                        "actual_layer_count": 5,
                        "padding_layer_count": 2,
                    }
                ],
            }
        )

        result = run(ctx)

        np.testing.assert_array_equal(
            result["material_matrix"][mask],
            np.broadcast_to(print_recipe, (int(np.sum(mask)), 7)),
        )

    def test_dynamic_recipe_overrides_remap_distinct_virtuals_globally(
        self,
        tmp_path,
    ):
        ctx = _make_material_archive_ctx(None)
        native_count = len(_SMALL_PALETTE)
        first_mask = np.zeros(ctx["mask_solid"].shape, dtype=bool)
        second_mask = np.zeros(ctx["mask_solid"].shape, dtype=bool)
        first_mask[0, 0] = True
        second_mask[0, 1] = True
        masks_path = tmp_path / "dynamic_virtual_masks.pkl"
        with open(masks_path, "wb") as file_obj:
            pickle.dump(
                {"region-a": first_mask, "region-b": second_mask},
                file_obj,
            )

        local_virtual = native_count
        actual = [local_virtual] * 5
        print_recipe = actual + [2, 2]
        ctx.update(
            {
                "material_dynamic_layer_count_enabled": True,
                "material_min_layer_count": 5,
                "material_max_layer_count": 7,
                "material_backing_material_index": 2,
                "color_layers": 7,
                "material_matrix": np.zeros((3, 4, 7), dtype=np.int32),
                "recipe_override_masks_path": os.fspath(masks_path),
                "recipe_overrides": [
                    {
                        "region_id": "region-a",
                        "recipe": actual,
                        "layer_order": "Top2Bottom",
                        "actual_recipe_top_to_bottom": actual,
                        "print_recipe_top_to_bottom": print_recipe,
                        "actual_layer_count": 5,
                        "padding_layer_count": 2,
                        "virtual_materials": [
                            {"name": "Virtual A", "hex": "#111111"}
                        ],
                    },
                    {
                        "region_id": "region-b",
                        "recipe": actual,
                        "layer_order": "Top2Bottom",
                        "actual_recipe_top_to_bottom": actual,
                        "print_recipe_top_to_bottom": print_recipe,
                        "actual_layer_count": 5,
                        "padding_layer_count": 2,
                        "virtual_materials": [
                            {"name": "Virtual B", "hex": "#222222"}
                        ],
                    },
                ],
            }
        )

        result = run(ctx)

        np.testing.assert_array_equal(
            result["material_matrix"][first_mask][0],
            [native_count] * 5 + [2, 2],
        )
        np.testing.assert_array_equal(
            result["material_matrix"][second_mask][0],
            [native_count + 1] * 5 + [2, 2],
        )

    def test_applies_replacement_without_processor(self):
        ctx = _make_material_archive_ctx({"#c86432": "#14c814"})
        original_col0 = ctx["matched_rgb"][:, 0].copy()
        result = run(ctx)
        # Rest of the image has been rewritten to the solver's achieved color.
        rewritten = result["matched_rgb"][:, 1:]
        assert not np.array_equal(rewritten[0, 0], [200, 100, 50])
        # Col 0 (blue-ish) was NOT targeted by the replacement, so it's intact.
        np.testing.assert_array_equal(result["matched_rgb"][:, 0], original_col0)
        # Material matrix on rewritten region is no longer all-zeros.
        assert np.any(result["material_matrix"][:, 1:] != 0)

    def test_dynamic_mode_dispatches_to_exact_replacement_helper(self):
        ctx = _make_material_archive_ctx({"#c86432": "#14c814"})
        ctx.update(
            {
                "material_dynamic_layer_count_enabled": True,
                "material_min_layer_count": 5,
                "material_max_layer_count": 7,
                "material_delta_e00_tolerance": 0.5,
                "material_backing_material_index": 2,
                "color_layers": 7,
                "material_matrix": np.zeros((3, 4, 7), dtype=np.int32),
                "quantized_image": ctx["matched_rgb"].copy(),
                "material_dynamic_layer_info": {"colors": []},
                "material_solver_info": {"path": "dynamic_exact"},
            }
        )
        exact_rgb = ctx["matched_rgb"].copy()
        exact_rgb[:, 1:] = [10, 200, 20]
        exact_matrix = ctx["material_matrix"].copy()
        exact_matrix[:, 1:] = [0, 1, 2, 1, 0, 2, 2]
        exact_info = {"enabled": True, "colors": [{"target_srgb": [20, 200, 20]}]}

        with patch(
            "core.pipeline.s03_color_replacement._apply_dynamic_material_archive_color_replacements",
            return_value=(
                exact_rgb,
                exact_matrix,
                1,
                exact_info,
                {"path": "dynamic_exact", "dynamic_engine": "numba"},
                ctx["quantized_image"].copy(),
            ),
        ) as dynamic_apply, patch(
            "core.pipeline.s03_color_replacement._apply_material_archive_color_replacements",
            side_effect=AssertionError("fixed replacement helper must not run"),
        ):
            result = run(ctx)

        dynamic_apply.assert_called_once()
        np.testing.assert_array_equal(result["matched_rgb"], exact_rgb)
        np.testing.assert_array_equal(result["material_matrix"], exact_matrix)
        assert result["material_dynamic_layer_info"] == exact_info
        assert result["material_solver_info"]["dynamic_engine"] == "numba"

    def test_dynamic_generation_failure_records_typed_pipeline_envelope(self):
        from core import converter

        ctx = _make_material_archive_ctx({"#c86432": "#14c814"})
        ctx.update(
            {
                "material_dynamic_layer_count_enabled": True,
                "material_min_layer_count": 5,
                "material_max_layer_count": 7,
                "material_delta_e00_tolerance": 0.5,
                "material_backing_material_index": 2,
                "color_layers": 7,
                "material_matrix": np.zeros((3, 4, 7), dtype=np.int32),
                "quantized_image": ctx["matched_rgb"].copy(),
                "material_dynamic_layer_info": {
                    "enabled": True,
                    "min_layer_count": 5,
                    "max_layer_count": 7,
                    "delta_e00_tolerance": 0.5,
                    "colors": [],
                    "benefit_curve": [],
                },
            }
        )
        failure = DynamicMaterialSolverError("both exact engines failed")

        with patch(
            "core.pipeline.s03_color_replacement._solve_dynamic_material_targets",
            side_effect=failure,
        ):
            result = run(ctx)

        envelope = result["material_dynamic_layer_error"]
        assert envelope["exception"] is failure
        assert envelope["error_type"] == "DynamicMaterialSolverError"
        with pytest.raises(DynamicMaterialSolverError) as exc_info:
            converter._raise_dynamic_material_pipeline_error(result)
        assert exc_info.value is failure

    def test_applies_api_format_replacement_regions_without_processor(self):
        """Preview replay sends API-format replacement_regions, not a dict."""
        ctx = _make_material_archive_ctx(None)
        ctx["replacement_regions"] = [
            {
                "quantized_hex": "#c86432",
                "matched_hex": "#c86432",
                "replacement_hex": "#14c814",
            }
        ]
        original_col0 = ctx["matched_rgb"][:, 0].copy()

        result = run(ctx)

        rewritten = result["matched_rgb"][:, 1:]
        assert not np.array_equal(rewritten[0, 0], [200, 100, 50])
        np.testing.assert_array_equal(result["matched_rgb"][:, 0], original_col0)
        assert np.any(result["material_matrix"][:, 1:] != 0)

    def test_no_warning_when_material_archive_handles_replacement(self, caplog):
        import logging
        ctx = _make_material_archive_ctx({"#c86432": "#14c814"})
        with caplog.at_level(logging.WARNING, logger="core.pipeline.s03_color_replacement"):
            run(ctx)
        skipped_warnings = [
            r for r in caplog.records
            if "skipped" in r.getMessage() and "material-archive" in r.getMessage()
        ]
        assert skipped_warnings == [], (
            "Material-archive color replacements should no longer be silently dropped"
        )

    def test_empty_replacements_in_material_archive_does_not_solve(self):
        """No replacement → no solver call, matched_rgb/material_matrix intact."""
        ctx = _make_material_archive_ctx(None)
        original_rgb = ctx["matched_rgb"].copy()
        original_mat = ctx["material_matrix"].copy()
        with patch(
            "core.pipeline.s03_color_replacement._apply_material_archive_color_replacements"
        ) as mock_apply:
            result = run(ctx)
        mock_apply.assert_not_called()
        np.testing.assert_array_equal(result["matched_rgb"], original_rgb)
        np.testing.assert_array_equal(result["material_matrix"], original_mat)

    def test_lut_mode_path_untouched(self, caplog):
        """When a processor exists, the material-archive branch is NOT used."""
        from unittest.mock import MagicMock

        ctx = _make_material_archive_ctx({"#c86432": "#14c814"})
        # Upgrade to LUT mode by attaching a processor and removing the flag.
        ctx["material_source"] = "lut"
        ctx.pop("_material_params")
        processor = MagicMock()
        processor._rgb_to_lab = MagicMock(
            return_value=np.array([[50.0, 0.0, 0.0]])
        )
        processor.kdtree = MagicMock()
        processor.kdtree.query = MagicMock(
            return_value=(np.array([0.0]), np.array([0]))
        )
        processor.ref_stacks = np.zeros((10, 5), dtype=int)
        processor.lut_rgb = np.zeros((10, 3), dtype=np.uint8)
        ctx["processor"] = processor

        with patch(
            "core.pipeline.s03_color_replacement._apply_material_archive_color_replacements"
        ) as mock_apply:
            run(ctx)
        mock_apply.assert_not_called()


class TestS03NotWorseFallbackWiring:
    """S03 must invoke the cross-N not-worse fallback on the baseline solve,
    and must degrade gracefully when the fallback itself raises.
    S03 必须在基线求解之后调用跨 N 不劣回退；回退自身抛错时必须安全降级。
    """

    def test_fallback_is_called_after_cache_lookup(self):
        matched = np.full((2, 2, 3), [200, 100, 50], dtype=np.uint8)
        mat = np.zeros((2, 2, 5), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)

        class _StubCache:
            def lookup(self, unique_srgb, user_materials):
                n = unique_srgb.shape[0]
                return (
                    np.full((n, 3), [10, 200, 20], dtype=np.uint8),
                    np.zeros((n, 5), dtype=np.int32),
                    np.full(n, 2.0, dtype=np.float32),
                )

        fallback_calls: list[dict] = []

        def _mock_fallback(
            targets, materials, matched_rgb_unique, recipes_unique, delta_e,
            **kwargs,
        ):
            fallback_calls.append({
                "target_layer_count": kwargs["target_layer_count"],
                "substrate": kwargs["substrate"],
                "targets_shape": targets.shape,
            })
            return matched_rgb_unique, recipes_unique, delta_e, {
                "white_material_index": 2,
                "applied": True,
                "improved_pixels": 0,
                "per_k_improved": {},
                "mean_delta_e_before": 2.0,
                "max_delta_e_before": 2.0,
                "mean_delta_e_after": 2.0,
                "max_delta_e_after": 2.0,
            }

        with patch(
            "core.material_cache.load_material_solver_cache",
            return_value=_StubCache(),
        ), patch(
            "core.material_lut_synthesis.ensure_not_worse_than_smaller_N",
            side_effect=_mock_fallback,
        ):
            out_rgb, out_mat, applied = _apply_material_archive_color_replacements(
                matched, mat, mask, {"#c86432": "#14c814"},
                _SMALL_PALETTE, 5, 0.08, "white",
            )

        assert applied == 1
        assert len(fallback_calls) == 1
        assert fallback_calls[0]["target_layer_count"] == 5
        assert fallback_calls[0]["substrate"] == "white"
        # Exactly one unique replacement target (#14c814) was solved.
        assert fallback_calls[0]["targets_shape"] == (1, 3)

    def test_fallback_exception_keeps_baseline(self, caplog):
        """If the fallback helper raises, S03 must log a warning and keep
        the baseline recipe/achieved color from the solver unchanged."""
        import logging
        from api.structured_logging import get_logger

        matched = np.full((2, 2, 3), [200, 100, 50], dtype=np.uint8)
        mat = np.zeros((2, 2, 5), dtype=np.int32)
        mask = np.ones((2, 2), dtype=bool)

        class _StubCache:
            def lookup(self, unique_srgb, user_materials):
                n = unique_srgb.shape[0]
                return (
                    np.full((n, 3), [10, 200, 20], dtype=np.uint8),
                    # A recognisable non-zero recipe so we can verify it survives.
                    np.full((n, 5), 1, dtype=np.int32),
                    np.full(n, 1.2, dtype=np.float32),
                )

        target_logger = get_logger("core.pipeline.s03_color_replacement")
        caplog.set_level(
            logging.WARNING,
            logger="lumina.core.pipeline.s03_color_replacement",
        )
        target_logger.addHandler(caplog.handler)
        try:
            with patch(
                "core.material_cache.load_material_solver_cache",
                return_value=_StubCache(),
            ), patch(
                "core.material_lut_synthesis.ensure_not_worse_than_smaller_N",
                side_effect=RuntimeError("synthetic fallback failure"),
            ):
                out_rgb, out_mat, applied = (
                    _apply_material_archive_color_replacements(
                        matched, mat, mask, {"#c86432": "#14c814"},
                        _SMALL_PALETTE, 5, 0.08, "white",
                    )
                )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert applied == 1
        # Baseline achieved color still reached every matching pixel.
        assert np.all(out_rgb[:, 1:] == np.asarray([10, 200, 20], dtype=np.uint8))
        # Baseline recipe (all 1s) reached the matrix, reversed Top2Bottom
        # (reversing a constant vector is a no-op).
        assert np.all(out_mat[:, 1:] == 1)
        # A warning mentioning the fallback failure was recorded.
        failure_warnings = [
            r for r in caplog.records
            if "Not-worse fallback failed" in r.getMessage()
        ]
        assert failure_warnings, (
            "Expected a warning entry when the not-worse fallback raises"
        )
