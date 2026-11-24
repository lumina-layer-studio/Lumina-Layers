"""Unit tests for pipeline-level Bambu base-layer modifier context propagation."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
import trimesh
from PIL import Image

from config import ModelingMode
from core.pipeline import coordinator, s06_voxel_building
from utils.bambu_3mf_writer import build_layer_config_ranges_xml


_EXPECTED_CASES = [
    ("4-Color", "单面", 10, 0.8, 0.8, 0.8, "down"),
    ("4-Color", "双面", 10, 0.8, 0.8, 0.8, "double"),
    ("5-Color Extended", "单面", 15, 1.6, 1.6, 1.2, "up"),
    ("BW", "单面", 5, 0.4, 0.4, 0.4, "down"),
    ("4-Color", "单面", 0, 0.8, 0.8, 0.0, "down"),
    ("4-Color", "单面", 5, 0.0, 0.08, 0.4, "down"),
]


@pytest.mark.parametrize(
    ("color_mode", "structure_mode", "num_layers", "thickness_mm", "expected_base", "expected_color", "expected_face"),
    _EXPECTED_CASES,
)
def test_vector_pipeline_ctx_formula_matches_expected_mapping(
    color_mode: str,
    structure_mode: str,
    num_layers: int,
    thickness_mm: float,
    expected_base: float,
    expected_color: float,
    expected_face: str,
) -> None:
    ctx: dict[str, object] = {}

    coordinator._update_bambu_base_layer_ctx_for_vector(
        ctx,
        color_mode=color_mode,
        structure_mode=structure_mode,
        num_layers=num_layers,
        thickness_mm=thickness_mm,
    )

    assert ctx["bambu_base_height_mm"] == expected_base
    assert ctx["bambu_color_height_mm"] == expected_color
    assert ctx["bambu_face_orientation"] == expected_face
    assert ctx["enable_base_layer_height_modifier"] is True


def test_vector_pipeline_ctx_includes_transparent_coating_height() -> None:
    ctx: dict[str, object] = {
        "enable_coating": True,
        "coating_height_mm": 0.08,
    }

    coordinator._update_bambu_base_layer_ctx_for_vector(
        ctx,
        color_mode="8-Color Max",
        structure_mode="Double-sided",
        num_layers=5,
        thickness_mm=1.2,
    )

    assert ctx["bambu_color_height_mm"] == pytest.approx(0.48)
    assert ctx["bambu_face_orientation"] == "double"


def test_voxel_pipeline_ctx_includes_transparent_coating_height() -> None:
    ctx: dict[str, object] = {
        "enable_coating": True,
        "coating_height_mm": 0.08,
    }

    s06_voxel_building._update_bambu_base_layer_ctx_from_voxels(
        ctx,
        color_mode="8-Color Max",
        structure_mode="Double-sided",
        num_layers=5,
        thickness_mm=1.2,
    )

    assert ctx["bambu_color_height_mm"] == pytest.approx(0.48)
    assert ctx["bambu_face_orientation"] == "double"


def test_voxel_pipeline_marks_relief_exports_face_up() -> None:
    material_matrix = np.zeros((3, 3, 5), dtype=int)
    mask_solid = np.ones((3, 3), dtype=bool)
    matched_rgb = np.zeros((3, 3, 3), dtype=np.uint8)
    ctx = {
        "material_matrix": material_matrix,
        "mask_solid": mask_solid,
        "spacer_thick": 0.8,
        "structure_mode": "单面",
        "backing_color_id": 0,
        "color_mode": "4-Color",
        "enable_cloisonne": False,
        "enable_relief": True,
        "color_height_map": {"#000000": 1.2},
        "height_mode": "color",
        "heightmap_path": None,
        "heightmap_max_height": None,
        "matched_rgb": matched_rgb,
        "pixel_scale": 0.1,
    }

    result = s06_voxel_building.run(ctx)

    assert result["backing_metadata"]["is_relief"] is True
    assert result["bambu_face_orientation"] == "up"


def test_material_archive_seven_layer_color_relief_disables_base_modifier() -> None:
    material_matrix = np.broadcast_to(
        np.arange(7, dtype=int),
        (12, 20, 7),
    ).copy()
    matched_rgb = np.zeros((12, 20, 3), dtype=np.uint8)
    matched_rgb[:, :10] = [255, 0, 0]
    matched_rgb[:, 10:] = [0, 255, 0]
    ctx = {
        "material_source": "material_archive",
        "material_matrix": material_matrix,
        "mask_solid": np.ones((12, 20), dtype=bool),
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "backing_color_id": 4,
        "color_mode": "Material Archive",
        "enable_cloisonne": False,
        "enable_relief": True,
        "color_height_map": {"#ff0000": 1.28, "#00ff00": 1.52},
        "height_mode": "color",
        "heightmap_path": None,
        "heightmap_max_height": None,
        "matched_rgb": matched_rgb,
        "pixel_scale": 0.4,
    }

    result = s06_voxel_building.run(ctx)

    assert result["full_matrix"].shape == (19, 12, 20)
    assert result["backing_metadata"]["backing_z_max_map"][0, 0] == 8
    assert result["backing_metadata"]["backing_z_max_map"][0, -1] == 11
    assert result["bambu_face_orientation"] == "up"
    assert result["enable_base_layer_height_modifier"] is False


def test_material_archive_seven_layer_heightmap_relief_disables_base_modifier(
    tmp_path,
) -> None:
    heightmap = np.full((12, 20), 255, dtype=np.uint8)
    heightmap[:, 10:] = 0
    heightmap_path = tmp_path / "relief-heightmap.png"
    Image.fromarray(heightmap).save(heightmap_path)
    ctx = {
        "material_source": "material_archive",
        "material_matrix": np.zeros((12, 20, 7), dtype=int),
        "mask_solid": np.ones((12, 20), dtype=bool),
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "backing_color_id": 4,
        "color_mode": "Material Archive",
        "enable_cloisonne": False,
        "enable_relief": True,
        "color_height_map": {},
        "height_mode": "heightmap",
        "heightmap_path": str(heightmap_path),
        "heightmap_max_height": 1.52,
        "matched_rgb": np.zeros((12, 20, 3), dtype=np.uint8),
        "target_w": 20,
        "target_h": 12,
        "pixel_scale": 0.4,
    }

    result = s06_voxel_building.run(ctx)

    assert result["full_matrix"].shape == (19, 12, 20)
    assert result["backing_metadata"]["is_relief"] is True
    assert result["bambu_face_orientation"] == "up"
    assert result["enable_base_layer_height_modifier"] is False


def test_material_archive_seven_layer_flat_down_keeps_base_modifier() -> None:
    ctx = {
        "material_source": "material_archive",
        "material_matrix": np.zeros((3, 3, 7), dtype=int),
        "mask_solid": np.ones((3, 3), dtype=bool),
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "backing_color_id": 0,
        "color_mode": "Material Archive",
        "enable_cloisonne": False,
        "enable_relief": False,
        "color_height_map": None,
        "height_mode": "color",
        "heightmap_path": None,
        "heightmap_max_height": None,
        "matched_rgb": np.zeros((3, 3, 3), dtype=np.uint8),
        "pixel_scale": 0.1,
    }

    result = s06_voxel_building.run(ctx)

    assert result["bambu_base_height_mm"] == pytest.approx(1.2)
    assert result["bambu_color_height_mm"] == pytest.approx(0.56)
    assert result["bambu_face_orientation"] == "down"
    assert result["enable_base_layer_height_modifier"] is True

    xml_bytes = build_layer_config_ranges_xml(
        base_height_mm=result["bambu_base_height_mm"],
        color_height_mm=result["bambu_color_height_mm"],
        nozzle_mm=0.4,
        face=result["bambu_face_orientation"],
    )
    assert xml_bytes is not None
    range_element = ET.fromstring(xml_bytes).find("./object/range")
    assert range_element is not None
    assert float(range_element.attrib["min_z"]) == pytest.approx(0.56)
    assert float(range_element.attrib["max_z"]) == pytest.approx(1.76)


def test_vector_pipeline_ctx_disables_base_modifier_for_relief() -> None:
    ctx: dict[str, object] = {"enable_relief": True}

    coordinator._update_bambu_base_layer_ctx_for_vector(
        ctx,
        color_mode="Material Archive",
        structure_mode="Single-sided",
        num_layers=7,
        thickness_mm=1.2,
    )

    assert ctx["bambu_face_orientation"] == "up"
    assert ctx["enable_base_layer_height_modifier"] is False


@pytest.mark.parametrize(
    ("color_mode", "structure_mode", "num_layers", "thickness_mm", "expected_base", "expected_color", "expected_face"),
    _EXPECTED_CASES,
)
def test_voxel_pipeline_sets_bambu_ctx_values(
    color_mode: str,
    structure_mode: str,
    num_layers: int,
    thickness_mm: float,
    expected_base: float,
    expected_color: float,
    expected_face: str,
) -> None:
    material_matrix = np.zeros((3, 3, num_layers), dtype=int)
    mask_solid = np.ones((3, 3), dtype=bool)
    matched_rgb = np.zeros((3, 3, 3), dtype=np.uint8)
    ctx = {
        "material_matrix": material_matrix,
        "mask_solid": mask_solid,
        "spacer_thick": thickness_mm,
        "structure_mode": structure_mode,
        "backing_color_id": 0,
        "color_mode": color_mode,
        "enable_cloisonne": False,
        "enable_relief": False,
        "color_height_map": None,
        "height_mode": "color",
        "heightmap_path": None,
        "heightmap_max_height": None,
        "matched_rgb": matched_rgb,
        "pixel_scale": 0.1,
    }

    result = s06_voxel_building.run(ctx)

    assert result["bambu_base_height_mm"] == expected_base
    assert result["bambu_color_height_mm"] == expected_color
    assert result["bambu_face_orientation"] == expected_face
    assert result["enable_base_layer_height_modifier"] is True


def test_vector_branch_passes_bambu_modifier_kwargs_to_exporter(tmp_path) -> None:
    captured: dict[str, object] = {}

    class _FakeVectorProcessor:
        parse_warnings: list[str] = []
        last_stage_timings: dict[str, float] = {}

        def __init__(self, _lut_path: str, color_mode: str, *, img_processor=None) -> None:
            self.color_mode = color_mode
            self.enable_fridge_magnet = False
            self.fridge_magnets = []

        def analyze_svg(self, *, svg_path: str, target_width_mm: float, color_replacements=None):
            del svg_path, target_width_mm, color_replacements
            return SimpleNamespace(
                num_layers=15,
                preview_colors={0: [255, 0, 0, 255]},
                slot_names=["Slot 1"],
            )

        def build_mesh(self, *, analysis, thickness_mm: float, structure_mode: str):
            del analysis, thickness_mm, structure_mode
            scene = trimesh.Scene()
            scene.add_geometry(trimesh.creation.box(extents=(1, 1, 1)), geom_name="Slot 1")
            return scene

        @staticmethod
        def render_preview(analysis, pixels_per_mm: float):
            del analysis, pixels_per_mm
            return None

    def _fake_export_scene_with_bambu_metadata(**kwargs):
        captured.update(kwargs)
        return kwargs["output_path"]

    with patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor), patch(
        "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
        side_effect=_fake_export_scene_with_bambu_metadata,
    ), patch("core.naming.generate_model_filename", lambda *_args: "vector-out.3mf"), patch(
        "core.naming.generate_preview_filename",
        lambda *_args: "vector-preview.glb",
    ), patch("config.MODELS_DIR", str(tmp_path)), patch(
        "config.OUTPUT_DIR",
        str(tmp_path),
    ), patch("utils.Stats.increment", lambda *_args, **_kwargs: None), patch.object(
        coordinator,
        "_report_progress",
        lambda *_args, **_kwargs: None,
    ):
        ctx = {
            "image_path": str(tmp_path / "vector.svg"),
            "actual_lut_path": str(tmp_path / "fake.json"),
            "color_mode": "5-Color Extended",
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
            "target_width_mm": 40.0,
            "spacer_thick": 1.6,
            "structure_mode": "单面",
            "need_2d_preview": False,
            "printer_id": "bambu-h2d",
            "slicer": "BambuStudio",
            "nozzle_size": "0.4",
            "layer_height_mm": 0.12,
            "enable_coating": True,
            "coating_height_mm": 0.08,
            "backing_infill_density_percent": 35,
        }

        result = coordinator._run_vector_branch(ctx)

    assert "error" not in result
    assert captured["enable_base_layer_height_modifier"] is True
    assert captured["base_height_mm"] == pytest.approx(1.56)
    assert captured["color_height_mm"] == pytest.approx(1.88)
    assert captured["face_orientation"] == "up"
    assert captured["backing_infill_density_percent"] == 35


def test_vector_relief_does_not_forward_enabled_base_modifier(tmp_path) -> None:
    captured: dict[str, object] = {}

    class _FakeVectorProcessor:
        parse_warnings: list[str] = []
        last_stage_timings: dict[str, float] = {}

        def __init__(self, _lut_path: str, color_mode: str, *, img_processor=None) -> None:
            self.color_mode = color_mode
            self.enable_fridge_magnet = False
            self.fridge_magnets = []

        def analyze_svg(self, *, svg_path: str, target_width_mm: float, color_replacements=None):
            del svg_path, target_width_mm, color_replacements
            return SimpleNamespace(
                num_layers=7,
                preview_colors={0: [255, 0, 0, 255]},
                slot_names=["Slot 1"],
            )

        def build_mesh(
            self,
            *,
            analysis,
            thickness_mm: float,
            structure_mode: str,
            enable_relief: bool = False,
            height_mode: str = "color",
            color_height_map=None,
            heightmap_path=None,
            heightmap_max_height=None,
        ):
            del (
                analysis,
                thickness_mm,
                structure_mode,
                height_mode,
                color_height_map,
                heightmap_path,
                heightmap_max_height,
            )
            assert enable_relief is True
            scene = trimesh.Scene()
            scene.add_geometry(
                trimesh.creation.box(extents=(1, 1, 1)),
                geom_name="Slot 1",
            )
            return scene

        @staticmethod
        def render_preview(analysis, pixels_per_mm: float):
            del analysis, pixels_per_mm
            return None

    def _fake_export_scene_with_bambu_metadata(**kwargs):
        captured.update(kwargs)
        return kwargs["output_path"]

    with patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor), patch(
        "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
        side_effect=_fake_export_scene_with_bambu_metadata,
    ), patch("core.naming.generate_model_filename", lambda *_args: "vector-relief.3mf"), patch(
        "core.naming.generate_preview_filename",
        lambda *_args: "vector-relief-preview.glb",
    ), patch("config.MODELS_DIR", str(tmp_path)), patch(
        "config.OUTPUT_DIR",
        str(tmp_path),
    ), patch("utils.Stats.increment", lambda *_args, **_kwargs: None), patch.object(
        coordinator,
        "_report_progress",
        lambda *_args, **_kwargs: None,
    ):
        ctx = {
            "image_path": str(tmp_path / "vector.svg"),
            "actual_lut_path": str(tmp_path / "fake.json"),
            "color_mode": "4-Color",
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
            "target_width_mm": 40.0,
            "spacer_thick": 1.2,
            "structure_mode": "Single-sided",
            "need_2d_preview": False,
            "printer_id": "bambu-h2d",
            "slicer": "BambuStudio",
            "nozzle_size": "0.4",
            "enable_relief": True,
            "height_mode": "color",
            "color_height_map": {"#ff0000": 1.28},
        }

        result = coordinator._run_vector_branch(ctx)

    assert "error" not in result
    assert captured["enable_relief"] is True
    assert captured["enable_base_layer_height_modifier"] is False
