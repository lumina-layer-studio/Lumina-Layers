"""Free colors own their SVG optical volume instead of duplicating material meshes."""
from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import box

from core.vector_engine import VectorAnalysis, VectorProcessor
from core.pipeline import vector_branch


def analysis_fixture() -> VectorAnalysis:
    return VectorAnalysis(
        shape_data=[], clipped_shapes=[],
        matched_shapes=[
            {"geometry": box(0, 0, 1, 1), "recipe": [0, 1], "matched_rgb": (255, 0, 0)},
            {"geometry": box(1, 0, 2, 1), "recipe": [1, 0], "matched_rgb": (0, 255, 0)},
        ], silhouette=box(0, 0, 2, 1), scale_factor=1.0, bbox=(0, 0, 2, 1), color_conf={},
        slot_names=["White", "Black"], num_channels=2, num_layers=2,
        preview_colors={0: [255, 255, 255, 255], 1: [0, 0, 0, 255]},
    )


@pytest.mark.parametrize("marked", [{"ff0000"}, {"#FF0000"}])
@pytest.mark.parametrize("structure", ["Single-sided", "Double-sided"])
def test_free_color_is_a_nonoverlapping_optical_mesh(marked: set[str], structure: str) -> None:
    original = analysis_fixture()
    prepared = vector_branch._prepare_vector_free_colors(original, marked)
    processor = VectorProcessor.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    processor.layer_height_mm = 0.08
    scene = processor.build_mesh(prepared, thickness_mm=0.8, structure_mode=structure)
    factor = 2 if structure == "Double-sided" else 1
    assert "Free_ff0000" in scene.geometry
    mesh = scene.geometry["Free_ff0000"]
    assert mesh.is_watertight
    assert abs(mesh.volume) == pytest.approx(0.16 * factor)
    assert sum(abs(m.volume) for name, m in scene.geometry.items() if name != "Board") == pytest.approx(0.32 * factor)
    baseline = processor.build_mesh(original, thickness_mm=0.8, structure_mode=structure)
    assert sum(abs(m.volume) for m in scene.geometry.values()) == pytest.approx(
        sum(abs(m.volume) for m in baseline.geometry.values()))
    assert prepared.slot_names == ["White", "Black", "Free_ff0000"]
    np.testing.assert_array_equal(prepared.preview_colors["Free_ff0000"], [255, 0, 0, 255])
    assert original.matched_shapes[0]["recipe"] == [0, 1]
    assert original.slot_names == ["White", "Black"]


def test_no_free_color_keeps_the_existing_analysis() -> None:
    original = analysis_fixture()
    assert vector_branch._prepare_vector_free_colors(original, None) is original


def test_free_colors_preserve_air_and_other_solved_recipes() -> None:
    original = analysis_fixture()
    original.matched_shapes[0]["recipe"] = [0, -1]
    prepared = vector_branch._prepare_vector_free_colors(original, {"ff0000"})
    assert prepared.matched_shapes[0]["recipe"] == [2, -1]
    assert prepared.matched_shapes[1] is original.matched_shapes[1]
    assert prepared.preview_colors is not original.preview_colors
    assert len(original.preview_colors) == 2


def test_relief_keeps_its_height_identity_with_a_free_color() -> None:
    original = analysis_fixture()
    for shape in original.matched_shapes:
        shape["height_identity_rgb"] = shape["matched_rgb"]
    prepared = vector_branch._prepare_vector_free_colors(original, {"ff0000"})
    processor = VectorProcessor.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    processor.layer_height_mm = 0.08
    scene = processor.build_mesh(prepared, thickness_mm=0.8, enable_relief=True,
        color_height_map={"#ff0000": 1.6, "#00ff00": 0.8})
    assert scene.geometry["Free_ff0000"].is_watertight
    assert abs(scene.geometry["Free_ff0000"].volume) == pytest.approx(0.16)
    assert prepared.matched_shapes[0]["height_identity_rgb"] == (255, 0, 0)


def test_production_vector_branch_consumes_free_color_markers(monkeypatch) -> None:
    original = analysis_fixture()
    processor = VectorProcessor.__new__(VectorProcessor)
    processor.color_mode = "4-Color (RYBW)"
    processor.layer_height_mm = 0.08
    processor.analyze_svg = lambda **kwargs: original
    monkeypatch.setattr(vector_branch, "_build_vector_processor", lambda *a, **k: processor)
    result = vector_branch._run_vector_branch({
        "image_path": "two-colors.svg", "color_mode": "4-Color (RYBW)",
        "modeling_mode": "vector", "target_width_mm": 2,
        "spacer_thick": 0.8, "structure_mode": "Single-sided",
        "free_color_set": {"ff0000"}, "stop_after_step": "S08",
    })
    assert "error" not in result, result.get("error")
    assert "Free_ff0000" in result["scene"].geometry
    assert "Free_ff0000" in result["valid_slot_names"]
    assert original.slot_names == ["White", "Black"]
