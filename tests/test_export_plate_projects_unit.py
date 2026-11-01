from pathlib import Path
import zipfile

import numpy as np
import pytest
import trimesh

from utils.slicer_3mf_writer import export_scene_with_slicer_metadata


def _scene():
    scene = trimesh.Scene()
    color = trimesh.creation.box(extents=(20, 30, 0.8))
    color.metadata["bambu_material_name"] = "White"
    scene.add_geometry(color, geom_name="Color")
    backing = trimesh.creation.box(extents=(20, 30, 1.2))
    backing.apply_translation((0, 0, 1))
    backing.metadata.update({"bambu_material_name": "White", "lumina_print_role": "backing"})
    scene.add_geometry(backing, geom_name="Backing")
    return scene


def test_independent_projects_keep_original_geometry_and_each_native_package(tmp_path):
    scene = _scene()
    before = {name: mesh.vertices.copy() for name, mesh in scene.geometry.items()}
    output = export_scene_with_slicer_metadata(
        scene, str(tmp_path / "scene.3mf"), list(scene.geometry),
        {"White": [249, 249, 249, 255]}, project_slot_names=["White"],
        backing_output="separate_project", base_height_mm=1.2, color_height_mm=0.8,
    )
    assert Path(output).suffix == ".zip"
    with zipfile.ZipFile(output) as archive:
        assert archive.namelist() == ["plate_1_model.3mf", "plate_2_backing.3mf"]
        from io import BytesIO
        import xml.etree.ElementTree as ET

        for name, thickness in [("plate_1_model.3mf", 0.8), ("plate_2_backing.3mf", 1.2)]:
            with zipfile.ZipFile(BytesIO(archive.read(name))) as project:
                assert "Metadata/project_settings.config" in project.namelist()
                vertices = []
                for part in project.namelist():
                    if part.endswith(".model"):
                        root = ET.fromstring(project.read(part))
                        vertices.extend([[float(node.get(axis)) for axis in ("x", "y", "z")]
                                         for node in root.findall(".//{*}vertex")])
                assert np.ptp(np.array(vertices), axis=0) == pytest.approx([20, 30, thickness])
    for name, mesh in scene.geometry.items():
        np.testing.assert_array_equal(mesh.vertices, before[name])
    assert sorted(path.name for path in tmp_path.iterdir()) == ["scene.zip"]


def test_independent_projects_require_a_real_backing_part(tmp_path):
    scene = _scene()
    del scene.geometry["Backing"].metadata["lumina_print_role"]
    with pytest.raises(ValueError, match="backing"):
        export_scene_with_slicer_metadata(
            scene, str(tmp_path / "scene.3mf"), list(scene.geometry), {},
            backing_output="separate_project",
        )
    assert not list(tmp_path.iterdir())


def test_independent_projects_keep_colours_when_compacting_numbered_palette(tmp_path):
    from io import BytesIO
    import json

    scene = _scene()
    names = ["Slot 2 (White)", "Slot 1 (Red)"]
    scene.geometry["Color"].metadata["bambu_material_name"] = names[1]
    scene.geometry["Backing"].metadata["bambu_material_name"] = names[0]
    output = export_scene_with_slicer_metadata(
        scene, str(tmp_path / "scene.3mf"), list(scene.geometry),
        {0: [249, 249, 249, 255], 1: [193, 46, 31, 255]}, project_slot_names=names,
        backing_output="separate_project", base_height_mm=1.2, color_height_mm=0.8,
    )
    with zipfile.ZipFile(output) as archive:
        for name, colour in [("plate_1_model.3mf", "#C12E1F"), ("plate_2_backing.3mf", "#F9F9F9")]:
            with zipfile.ZipFile(BytesIO(archive.read(name))) as project:
                settings = json.loads(project.read("Metadata/project_settings.config"))
            assert settings["filament_colour"] == [colour]


def test_second_plate_failure_leaves_no_partial_download(tmp_path):
    from core.export_plates import export_separate_backing_projects

    def export(**options):
        if Path(options["output_path"]).name == "plate_2_backing.3mf":
            raise OSError("backing writer failed")
        Path(options["output_path"]).write_bytes(b"temporary first plate")
        return options["output_path"]

    with pytest.raises(OSError, match="backing writer failed"):
        export_separate_backing_projects(
            _scene(), str(tmp_path / "scene.3mf"), project_slot_names=["White"],
            exporter=export, base_height_mm=1.2, color_height_mm=0.8,
        )
    assert not list(tmp_path.iterdir())


def test_independent_zip_reports_each_project_layout_warning(tmp_path):
    from io import BytesIO
    import json
    from utils.slicer_3mf_writer import read_wipe_tower_placement_warnings

    scene = _scene()
    for mesh in scene.geometry.values():
        mesh.apply_scale([12.0, 10.0, 1.0])
    output = export_scene_with_slicer_metadata(
        scene, str(tmp_path / "manual-layout.3mf"), list(scene.geometry),
        {"White": [249, 249, 249, 255]}, project_slot_names=["White"],
        backing_output="separate_project", printer_id="bambu-a1-mini",
        base_height_mm=1.2, color_height_mm=0.8,
    )
    assert read_wipe_tower_placement_warnings(output) == ["wipe_tower_manual_adjustment_required"]
    with zipfile.ZipFile(output) as archive:
        for name in archive.namelist():
            with zipfile.ZipFile(BytesIO(archive.read(name))) as project:
                placement = json.loads(project.read("Metadata/lumina_wipe_tower_placement.json"))
                assert placement["requires_manual_adjustment"] is True
                assert placement["placement_applied"] is False


def test_api_validates_independent_project_geometry_before_worker_dispatch():
    from api.schemas.converter import ConvertGenerateRequest, LargeFormatConvertGenerateRequest
    from pydantic import ValidationError

    params = {"lut_name": "colors", "target_width_mm": 188, "structure_mode": "Single-sided",
              "separate_backing": True, "backing_output": "separate_project"}
    assert ConvertGenerateRequest(**params).backing_output == "separate_project"
    for unsupported in [{"separate_backing": False}, {"structure_mode": "Double-sided"}, {"enable_relief": True}]:
        with pytest.raises(ValidationError, match="Independent backing projects"):
            ConvertGenerateRequest(**{**params, **unsupported})
    with pytest.raises(ValidationError, match="single-model generation"):
        LargeFormatConvertGenerateRequest(**params)
