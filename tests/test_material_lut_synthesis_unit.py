"""Unit tests for core.material_lut_synthesis beam-search solver."""

from __future__ import annotations

import json
import os
import tempfile

import numpy as np
import pytest

from core.material_lut_synthesis import (
    ALLOWED_LAYER_HEIGHTS_MM,
    DEFAULT_BEAM_WIDTH,
    DEFAULT_LAYER_HEIGHT_MM,
    MAX_LAYER_COUNT,
    MIN_LAYER_COUNT,
    MaterialParams,
    _beer_lambert_layer,
    _linear_to_srgb_uint8,
    _srgb_to_linear,
    build_material_preview_colors,
    build_material_slot_names,
    forward_model,
    load_material_params,
    load_multiple_materials,
    map_pixels_to_materials,
    solve_image_colors,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_material(
    name: str = "TestMat",
    E: tuple = (0.5, 0.1, 0.1),
    k: tuple = (3.0, 3.0, 3.0),
    C0_white: tuple = (1.0, 1.0, 1.0),
    estimated_rgb: tuple = (180, 50, 50),
) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower().replace(" ", "-"),
        E=np.asarray(E, dtype=np.float64),
        k=np.asarray(k, dtype=np.float64),
        C0_white=np.asarray(C0_white, dtype=np.float64),
        estimated_rgb=np.asarray(estimated_rgb, dtype=np.uint8),
    )


RED_MAT = _make_material("Red", E=(0.6, 0.05, 0.05), k=(4.0, 4.0, 4.0))
BLUE_MAT = _make_material("Blue", E=(0.05, 0.1, 0.6), k=(4.0, 4.0, 4.0))
WHITE_MAT = _make_material(
    "White",
    E=(0.95, 0.95, 0.95),
    k=(0.5, 0.5, 0.5),
    estimated_rgb=(245, 245, 245),
)


# ---------------------------------------------------------------------------
# Beer-Lambert forward model tests
# ---------------------------------------------------------------------------


class TestBeerLambertLayer:
    def test_zero_thickness_returns_input(self):
        C_prev = np.array([1.0, 1.0, 1.0])
        result = _beer_lambert_layer(C_prev, RED_MAT.E, RED_MAT.k, 0.0)
        np.testing.assert_allclose(result, C_prev)

    def test_large_thickness_approaches_equilibrium(self):
        C_prev = np.array([1.0, 1.0, 1.0])
        result = _beer_lambert_layer(C_prev, RED_MAT.E, RED_MAT.k, 100.0)
        np.testing.assert_allclose(result, RED_MAT.E, atol=1e-6)

    def test_positive_thickness_moves_toward_E(self):
        C_prev = np.array([1.0, 1.0, 1.0])
        result = _beer_lambert_layer(C_prev, RED_MAT.E, RED_MAT.k, 0.08)
        # Result should be between C_prev and E
        for ch in range(3):
            low, high = sorted([C_prev[ch], RED_MAT.E[ch]])
            assert low <= result[ch] <= high


class TestForwardModel:
    def test_empty_recipe_returns_substrate(self):
        recipe = np.array([], dtype=np.int32)
        substrate = np.ones(3, dtype=np.float64)
        result = forward_model(recipe, [RED_MAT], 0.08, substrate)
        np.testing.assert_array_equal(result, substrate)

    def test_single_layer(self):
        recipe = np.array([0], dtype=np.int32)
        substrate = np.ones(3, dtype=np.float64)
        result = forward_model(recipe, [RED_MAT], 0.08, substrate)
        expected = _beer_lambert_layer(substrate, RED_MAT.E, RED_MAT.k, 0.08)
        np.testing.assert_allclose(result, expected)

    def test_multi_material_recipe(self):
        recipe = np.array([0, 1, 0], dtype=np.int32)
        substrate = np.ones(3, dtype=np.float64)
        materials = [RED_MAT, BLUE_MAT]
        C = substrate.copy()
        C = _beer_lambert_layer(C, RED_MAT.E, RED_MAT.k, 0.08)
        C = _beer_lambert_layer(C, BLUE_MAT.E, BLUE_MAT.k, 0.08)
        C = _beer_lambert_layer(C, RED_MAT.E, RED_MAT.k, 0.08)
        result = forward_model(recipe, materials, 0.08, substrate)
        np.testing.assert_allclose(result, C)


# ---------------------------------------------------------------------------
# Solver tests
# ---------------------------------------------------------------------------


class TestSolveImageColors:
    def test_single_color_single_material(self):
        materials = [RED_MAT]
        # With only 1 material, all layers must be material 0
        target_srgb = np.array([[200, 80, 80]], dtype=np.uint8)
        matched, recipes, delta_e = solve_image_colors(
            target_srgb, materials, layer_count=5, layer_height_mm=0.08,
        )
        assert matched.shape == (1, 3)
        assert recipes.shape == (1, 5)
        np.testing.assert_array_equal(recipes[0], np.zeros(5, dtype=np.int32))

    def test_thick_stack_approaches_equilibrium(self):
        materials = [RED_MAT]
        # Use max layers at thickest height to approach equilibrium
        target_srgb = _linear_to_srgb_uint8(RED_MAT.E.reshape(1, 3))
        matched, recipes, delta_e = solve_image_colors(
            target_srgb, materials, layer_count=10, layer_height_mm=0.1,
        )
        assert recipes.shape == (1, 10)
        # 10 layers × 0.1mm = 1mm total — should get fairly close
        assert delta_e[0] < 20.0

    def test_white_target_prefers_white_material(self):
        materials = [RED_MAT, WHITE_MAT]
        target_srgb = np.array([[255, 255, 255]], dtype=np.uint8)
        matched, recipes, delta_e = solve_image_colors(
            target_srgb, materials, layer_count=5, layer_height_mm=0.08,
        )
        # On white substrate, to stay white, the solver should prefer white material
        assert np.all(recipes[0] == 1), f"Expected all White (1), got {recipes[0]}"

    def test_empty_input(self):
        materials = [RED_MAT]
        empty = np.zeros((0, 3), dtype=np.uint8)
        matched, recipes, delta_e = solve_image_colors(
            empty, materials, layer_count=5,
        )
        assert matched.shape == (0, 3)
        assert recipes.shape == (0, 5)
        assert delta_e.shape == (0,)

    def test_multiple_colors(self):
        materials = [RED_MAT, BLUE_MAT, WHITE_MAT]
        targets = np.array([
            [200, 50, 50],   # reddish
            [50, 50, 200],   # bluish
            [240, 240, 240], # whitish
        ], dtype=np.uint8)
        matched, recipes, delta_e = solve_image_colors(
            targets, materials, layer_count=5, layer_height_mm=0.08,
        )
        assert matched.shape == (3, 3)
        assert recipes.shape == (3, 5)
        assert delta_e.shape == (3,)

    def test_invalid_layer_count_raises(self):
        with pytest.raises(ValueError, match="layer_count"):
            solve_image_colors(
                np.array([[128, 128, 128]], dtype=np.uint8),
                [RED_MAT],
                layer_count=3,
            )

    def test_invalid_layer_height_raises(self):
        with pytest.raises(ValueError, match="layer_height_mm"):
            solve_image_colors(
                np.array([[128, 128, 128]], dtype=np.uint8),
                [RED_MAT],
                layer_count=5,
                layer_height_mm=0.05,
            )

    def test_no_materials_raises(self):
        with pytest.raises(ValueError, match="material"):
            solve_image_colors(
                np.array([[128, 128, 128]], dtype=np.uint8),
                [],
                layer_count=5,
            )


# ---------------------------------------------------------------------------
# Pixel mapping tests
# ---------------------------------------------------------------------------


class TestMapPixelsToMaterials:
    def test_large_recipe_lookup_keeps_pixel_indices_bounded(self, monkeypatch):
        palette = np.array([[8, 4, 2], [1, 2, 3]], dtype=np.uint8)
        recipes = np.array([[0, 1, -1], [1, 0, 1]], dtype=np.int32)
        labels = np.indices((640, 641)).sum(axis=0) % 2
        image = palette[labels]
        search = np.searchsorted
        search_sizes = []

        def measure(sorted_codes, query_codes, *args, **kwargs):
            search_sizes.append(query_codes.size)
            return search(sorted_codes, query_codes, *args, **kwargs)

        with monkeypatch.context() as patching:
            patching.setattr(np, "searchsorted", measure)
            matched, matrix = map_pixels_to_materials(image, palette, palette, recipes, 640, 641)

        assert max(search_sizes, default=0) <= 256 * 1024
        assert matrix.dtype == np.int32
        np.testing.assert_array_equal(matched, image)
        np.testing.assert_array_equal(matrix, recipes[labels])

    def test_basic_mapping(self):
        unique_colors = np.array([[255, 0, 0], [0, 0, 255]], dtype=np.uint8)
        matched_rgb = np.array([[200, 50, 50], [50, 50, 200]], dtype=np.uint8)
        recipes = np.array([[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]], dtype=np.int32)

        # 2x2 image: top-left=red, rest=blue
        quantized = np.array([
            [[255, 0, 0], [0, 0, 255]],
            [[0, 0, 255], [255, 0, 0]],
        ], dtype=np.uint8)

        out_rgb, out_mat = map_pixels_to_materials(
            quantized, unique_colors, matched_rgb, recipes, 2, 2,
        )
        assert out_rgb.shape == (2, 2, 3)
        assert out_mat.shape == (2, 2, 5)
        # top-left is red → recipe [0,0,0,0,0]
        np.testing.assert_array_equal(out_mat[0, 0], [0, 0, 0, 0, 0])
        # top-right is blue → recipe [1,1,1,1,1]
        np.testing.assert_array_equal(out_mat[0, 1], [1, 1, 1, 1, 1])


# ---------------------------------------------------------------------------
# Material loading tests
# ---------------------------------------------------------------------------


class TestLoadMaterialParams:
    def test_load_from_disk(self, tmp_path):
        mat_dir = tmp_path / "test-red"
        mat_dir.mkdir()

        stage_a = {
            "param_type": "stage_A",
            "parameters": {
                "channels": [{"channel_index": 0, "color_name": "Red", "E": [0.6, 0.05, 0.05], "k": [4.0, 4.0, 4.0]}],
                "substrates": [
                    {"substrate_idx": 0, "substrate_id": "white", "C0": [0.99, 0.98, 0.97]},
                    {"substrate_idx": 1, "substrate_id": "black", "C0": [0.01, 0.01, 0.01]},
                ],
            },
        }
        (mat_dir / "stage_A_parameters.json").write_text(json.dumps(stage_a), encoding="utf-8")

        archive = {
            "material_name": "PLA Red",
            "stage_a_params_file": "stage_A_parameters.json",
            "material_summary": {"estimated_rgb": [220, 30, 30]},
        }
        (mat_dir / "material.json").write_text(json.dumps(archive), encoding="utf-8")

        result = load_material_params("test-red", materials_dir=str(tmp_path))
        assert result.name == "PLA Red"
        assert result.directory_name == "test-red"
        np.testing.assert_allclose(result.E, [0.6, 0.05, 0.05])
        np.testing.assert_allclose(result.k, [4.0, 4.0, 4.0])
        np.testing.assert_allclose(result.C0_white, [0.99, 0.98, 0.97])
        np.testing.assert_array_equal(result.estimated_rgb, [220, 30, 30])

    def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_material_params("nonexistent", materials_dir=str(tmp_path))

    def test_invalid_stage_a_missing_solver_vectors_raises_value_error(self, tmp_path):
        mat_dir = tmp_path / "broken-pla"
        mat_dir.mkdir()
        (mat_dir / "stage_A_parameters.json").write_text(
            json.dumps(
                {
                    "parameters": {
                        "channels": [{"color_name": "Broken PLA"}],
                        "substrates": [
                            {"substrate_id": "white", "C0": [1.0, 1.0, 1.0]}
                        ],
                    }
                }
            ),
            encoding="utf-8",
        )
        (mat_dir / "material.json").write_text(
            json.dumps(
                {
                    "material_name": "Broken PLA",
                    "stage_a_params_file": "stage_A_parameters.json",
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(ValueError) as exc_info:
            load_material_params("broken-pla", materials_dir=str(tmp_path))

        message = str(exc_info.value)
        assert "broken-pla" in message
        assert "parameters.channels[0].E" in message
        assert "cannot be used by the material solver" in message
        assert str(tmp_path) not in message

    def test_load_multiple(self, tmp_path):
        for name, E_val in [("mat-a", 0.3), ("mat-b", 0.7)]:
            d = tmp_path / name
            d.mkdir()
            stage_a = {
                "parameters": {
                    "channels": [{"E": [E_val, E_val, E_val], "k": [2.0, 2.0, 2.0]}],
                    "substrates": [{"substrate_id": "white", "C0": [1.0, 1.0, 1.0]}],
                },
            }
            (d / "stage_A_parameters.json").write_text(json.dumps(stage_a), encoding="utf-8")
            (d / "material.json").write_text(json.dumps({
                "material_name": name,
                "stage_a_params_file": "stage_A_parameters.json",
                "material_summary": {},
            }), encoding="utf-8")

        materials = load_multiple_materials(["mat-a", "mat-b"], materials_dir=str(tmp_path))
        assert len(materials) == 2
        assert materials[0].name == "mat-a"
        assert materials[1].name == "mat-b"


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class TestBuildHelpers:
    def test_slot_names(self):
        materials = [RED_MAT, BLUE_MAT, WHITE_MAT]
        names = build_material_slot_names(materials)
        assert names == ["Red", "Blue", "White"]

    def test_preview_colors(self):
        materials = [RED_MAT, BLUE_MAT]
        colors = build_material_preview_colors(materials)
        assert 0 in colors
        assert 1 in colors
        assert len(colors[0]) == 4
        assert colors[0][3] == 255  # alpha
