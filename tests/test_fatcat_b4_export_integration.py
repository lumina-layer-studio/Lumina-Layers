from __future__ import annotations

import importlib
import json
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

import pytest
import trimesh

from utils.bambu_3mf_writer import BambuStudio3MFWriter




def _target_writer(path: Path, slicer: str = "BambuStudio") -> BambuStudio3MFWriter:
    writer = BambuStudio3MFWriter(
        str(path),
        settings={
            "layer_height": "0.12",
            "initial_layer_print_height": "0.20",
            "line_width": "0.42",
        },
        printer_id="bambu-a1-mini",
        slicer=slicer,
        nozzle_size="0.4",
        device_profile_id=f"{slicer}:bbl:bambu-lab-a1-mini:0.4",
        build_plate_id="textured-pei-plate",
        enable_base_layer_height_modifier=True,
        enable_wipe_tower_auto_placement=True,
        base_height_mm=0.8,
        color_height_mm=1.2,
        face_orientation="down",
        watermark="",
        preserve_template_filament_slots=True,
    )
    writer._set_project_palette(
        ["PLA A", "PLA B", "PLA C", "PLA D", "PLA E", "PLA F", "PLA G", "PLA H"],
        {
            "PLA A": (255, 0, 0, 255),
            "PLA B": (0, 255, 0, 255),
            "PLA C": (255, 0, 255, 255),
            "PLA D": (255, 255, 0, 255),
            "PLA E": (0, 0, 0, 255),
            "PLA F": (255, 64, 64, 255),
            "PLA G": (64, 64, 255, 255),
            "PLA H": (64, 255, 64, 255),
        },
    )
    writer.add_mesh(
        trimesh.creation.box(extents=(10.0, 10.0, 2.0)),
        "PLA A",
        (255, 0, 0),
    )
    return writer


@pytest.mark.parametrize("slicer", ["BambuStudio", "OrcaSlicer"])
@pytest.mark.parametrize("slot_policy,active_count", [(True, 8), (False, 4), (None, 8)])
def test_target_calls_cpp_metadata_and_writer_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    slicer: str,
    slot_policy: bool | None,
    active_count: int,
) -> None:
    import utils.bambu_3mf_writer as writer_module

    output = tmp_path / "b4-target.3mf"
    writer = _target_writer(output, slicer)
    writer.preserve_template_filament_slots = slot_policy
    if active_count < 8:
        palette, _ = writer._build_material_palette()
        writer._set_project_palette(
            [name for name, _ in palette[:active_count]], dict(palette[:active_count])
        )
    n3mf = writer_module._get_n3mf()
    calls = {
        "select_target": 0,
        "build": 0,
        "write_to_file": 0,
        "write_to_buffer": 0,
        "compose_builtin_project_settings": 0,
        "compose_model_metadata": 0,
        "patch_wipe_tower": 0,
        "get_wipe_tower_placement": 0,
    }
    helper_inputs: dict[str, object] = {}
    original_select_target = writer._select_metadata_target

    def spy_select_target(*args):
        calls["select_target"] += 1
        return original_select_target(*args)

    monkeypatch.setattr(writer, "_select_metadata_target", spy_select_target)
    original_write_to_file = n3mf.write_to_file

    def spy_write_to_file(*args, **kwargs):
        calls["write_to_file"] += 1
        return original_write_to_file(*args, **kwargs)

    monkeypatch.setattr(n3mf, "write_to_file", spy_write_to_file)
    original_build = n3mf.DocumentBuilder.build

    def spy_build(builder, *args, **kwargs):
        calls["build"] += 1
        return original_build(builder, *args, **kwargs)

    monkeypatch.setattr(n3mf.DocumentBuilder, "build", spy_build)
    if hasattr(n3mf, "write_to_buffer"):
        original_write_to_buffer = n3mf.write_to_buffer

        def spy_write_to_buffer(*args, **kwargs):
            calls["write_to_buffer"] += 1
            return original_write_to_buffer(*args, **kwargs)

        monkeypatch.setattr(n3mf, "write_to_buffer", spy_write_to_buffer)

    original_compose_builtin_project_settings = writer_module.compose_builtin_project_settings
    original_compose_model_metadata = writer_module.compose_model_metadata

    def spy_compose_builtin_project_settings(*args, **kwargs):
        calls["compose_builtin_project_settings"] += 1
        return original_compose_builtin_project_settings(*args, **kwargs)

    def spy_compose_model_metadata(*args, **kwargs):
        calls["compose_model_metadata"] += 1
        helper_inputs["model_request"] = dict(args[1])
        return original_compose_model_metadata(*args, **kwargs)

    original_patch_wipe_tower = writer_module.patch_wipe_tower

    def spy_patch_wipe_tower(*args, **kwargs):
        calls["patch_wipe_tower"] += 1
        return original_patch_wipe_tower(*args, **kwargs)

    monkeypatch.setattr(
        writer_module,
        "compose_builtin_project_settings",
        spy_compose_builtin_project_settings,
    )
    monkeypatch.setattr(
        writer_module, "compose_model_metadata", spy_compose_model_metadata
    )
    monkeypatch.setattr(writer_module, "patch_wipe_tower", spy_patch_wipe_tower)


    original_get_wipe_tower_placement = writer._get_wipe_tower_placement

    def spy_get_wipe_tower_placement(*args, **kwargs):
        calls["get_wipe_tower_placement"] += 1
        effective_settings = kwargs.get("effective_settings")
        if effective_settings is not None:
            helper_inputs["placement_project"] = dict(effective_settings)
        placement = original_get_wipe_tower_placement(*args, **kwargs)
        helper_inputs["placement"] = placement
        return placement

    monkeypatch.setattr(
        writer,
        "_get_wipe_tower_placement",
        spy_get_wipe_tower_placement,
    )
    def old_path_must_not_run(*_args, **_kwargs):
        raise AssertionError("export must pass layer range data to FatCat directly")

    monkeypatch.setattr(
        writer_module,
        "build_layer_config_ranges_xml",
        old_path_must_not_run,
    )
    original_get_build_item_translation = writer._get_build_item_translation

    def spy_get_build_item_translation(*args, **kwargs):
        translation = original_get_build_item_translation(*args, **kwargs)
        helper_inputs["build_translation"] = translation
        return translation

    monkeypatch.setattr(
        writer,
        "_get_build_item_translation",
        spy_get_build_item_translation,
    )

    assert writer.export() == str(output)
    assert calls == {
        "select_target": 1,
        "build": 1,
        "write_to_file": 1,
        "write_to_buffer": 0,
        "compose_builtin_project_settings": 1,
        "compose_model_metadata": 1,
        "patch_wipe_tower": 1,
        "get_wipe_tower_placement": 1,
    }
    assert helper_inputs["placement_project"]["initial_layer_print_height"] == "0.20"
    translation = helper_inputs["build_translation"]
    assert translation[2] == pytest.approx(1.0)
    assert 0.0 <= translation[0] <= 180.0
    assert 0.0 <= translation[1] <= 180.0
    component_inputs = helper_inputs["model_request"]["component_inputs"]
    assert component_inputs["wipe_tower_placement"]["enabled"] is True
    layer_ranges = component_inputs["layer_config_ranges"]
    assert layer_ranges["model_index"] == 1
    assert layer_ranges["ranges"]
    assert all("options" not in item for item in layer_ranges["ranges"])
    assert any(
        item.get("use_default_extruder") is True
        and isinstance(item.get("layer_height_mm"), (int, float))
        for item in layer_ranges["ranges"]
    )

    core_namespace = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    with zipfile.ZipFile(output) as package:
        project = json.loads(package.read("Metadata/project_settings.config"))
        assert len(project["filament_settings_id"]) == active_count
        assert len(project["different_settings_to_system"]) == 1
        assert project["print_compatible_printers"] == [project["printer_settings_id"]]
        assert project["filament_colour"][:2] == ["#FF0000", "#00FF00"]
        assert project["filament_colour"][2] == "#FF00FF"
        assert project["line_width"] == "0.42"
        assert project["initial_layer_print_height"] == "0.20"
        placement = helper_inputs["placement"]
        assert placement is not None
        assert float(project["wipe_tower_x"][0]) == pytest.approx(placement.tower_x)
        assert float(project["wipe_tower_y"][0]) == pytest.approx(placement.tower_y)
        assert project["nozzle_temperature"][:2] == ["220", "220"]

        root_rels = ET.fromstring(package.read("_rels/.rels"))
        assert {
            relationship.attrib["Target"]
            for relationship in root_rels
            if relationship.attrib["Id"].startswith("cover-rel-")
        } == {
            "/Auxiliaries/.thumbnails/thumbnail_3mf.png",
            "/Auxiliaries/.thumbnails/thumbnail_middle.png",
            "/Auxiliaries/.thumbnails/thumbnail_small.png",
        }

        slice_root = ET.fromstring(package.read("Metadata/slice_info.config"))
        headers = slice_root.findall("header/header_item")
        client_version = "02.06.00.51" if slicer == "OrcaSlicer" else "02.09.01.70"
        expected_headers = [
            ("X-BBL-Client-Type", "slicer"),
            ("X-BBL-Client-Version", client_version),
        ]
        if slicer == "OrcaSlicer":
            expected_headers.append(("OrcaSlicer-Version", "2.4.2"))
            assert project["precise_outer_wall"] == "0"
            assert "precise_outer_wall" in project["different_settings_to_system"][0].split(";")
            assert len(project["filament_flow_ratio"]) == active_count
            assert len(project["filament_retraction_length"]) == active_count
        assert [(item.attrib["key"], item.attrib["value"]) for item in headers] == expected_headers

        model_root = ET.fromstring(package.read("3D/3dmodel.model"))
        build_item = model_root.find(
            f"{{{core_namespace}}}build/{{{core_namespace}}}item"
        )
        assert build_item is not None
        metadata = {
            item.attrib["name"]: item.text
            for item in model_root.findall(f"{{{core_namespace}}}metadata")
        }
        expected_metadata = {
            "Application": f"BambuStudio-{client_version}",
            "BambuStudio:3mfVersion": "1",
        }
        if slicer == "OrcaSlicer":
            expected_metadata["OrcaSlicer"] = "2.4.2"
        assert metadata == expected_metadata
        model_settings = ET.fromstring(
            package.read("Metadata/model_settings.config")
        )
        assert model_settings.find("object/part/metadata[@key='extruder']") is not None
        layer_ranges = ET.fromstring(package.read("Metadata/layer_config_ranges.xml"))
        assert layer_ranges.find("object").attrib["id"] == "1"
        assert json.loads(package.read("Metadata/lumina_wipe_tower_placement.json"))["enabled"]
        assert package.read("Metadata/plate_1.png") == writer.cover_bundle.plate_main
        assert package.read("Metadata/plate_no_light_1.png") == writer.cover_bundle.plate_no_light
        assert package.read("Metadata/top_1.png") == writer._build_preview_placeholder_png_bytes()
        assert package.read("Metadata/pick_1.png") == writer._build_preview_placeholder_png_bytes()
        assert package.read("Auxiliaries/.thumbnails/thumbnail_3mf.png") == writer.cover_bundle.thumbnail_3mf
        if slicer == "BambuStudio":
            assert json.loads(package.read("Metadata/filament_sequence.json")) == {
                "plate_1": {"sequence": []}
            }
            cut_root = ET.fromstring(package.read("Metadata/cut_information.xml"))
            cut_object = cut_root.find("./object")
            assert cut_object is not None
            assert cut_object.attrib["id"] == build_item.attrib["objectid"]
            assert cut_root.find("./object/cut_id") is not None
        else:
            assert "Metadata/filament_sequence.json" not in package.namelist()
            assert "Metadata/cut_information.xml" not in package.namelist()

        expected_metadata_parts = {
            "Metadata/model_settings.config",
            "Metadata/project_settings.config",
            "Metadata/slice_info.config",
            "Metadata/lumina_wipe_tower_placement.json",
            "Metadata/layer_config_ranges.xml",
            "Metadata/plate_1.png",
            "Metadata/plate_no_light_1.png",
            "Metadata/top_1.png",
            "Metadata/pick_1.png",
            "Auxiliaries/.thumbnails/thumbnail_3mf.png",
            "Auxiliaries/.thumbnails/thumbnail_middle.png",
            "Auxiliaries/.thumbnails/thumbnail_small.png",
        }
        if slicer == "BambuStudio":
            expected_metadata_parts.update(
                {"Metadata/filament_sequence.json", "Metadata/cut_information.xml"}
            )
        package_metadata_parts = {
            name
            for name in package.namelist()
            if name.startswith(("Metadata/", "Auxiliaries/.thumbnails/"))
        }
        assert package_metadata_parts == expected_metadata_parts

        model_relationships_root = ET.fromstring(
            package.read("3D/_rels/3dmodel.model.rels")
        )
        model_relationships = [
            item
            for item in model_relationships_root
            if item.attrib.get("Type")
            == "http://schemas.bambulab.com/package/2021/settings"
        ]
        model_targets = [item.attrib["Target"] for item in model_relationships]
        expected_model_targets = (
            [
                "/Metadata/model_settings.config",
                "/Metadata/project_settings.config",
                "/Metadata/slice_info.config",
                "/Metadata/lumina_wipe_tower_placement.json",
                "/Metadata/filament_sequence.json",
                "/Metadata/cut_information.xml",
                "/Metadata/layer_config_ranges.xml",
            ]
            if slicer == "BambuStudio"
            else ["/Metadata/layer_config_ranges.xml"]
        )
        assert model_targets == expected_model_targets
        assert [item.attrib["Id"] for item in model_relationships] == [
            f"bambuRel{index}" for index in range(len(expected_model_targets))
        ]
        content_types = ET.fromstring(package.read("[Content_Types].xml"))
        defaults = {
            item.attrib["Extension"]: item.attrib["ContentType"]
            for item in content_types
            if item.tag.endswith("Default")
        }
        assert defaults["config"] == "text/xml"
        assert defaults["json"] == "application/json"
        assert defaults["xml"] == "text/xml"
        assert defaults["png"] == "image/png"

        placement = json.loads(
            package.read("Metadata/lumina_wipe_tower_placement.json")
        )
        assert placement == component_inputs["wipe_tower_placement"]
        assert writer_module.read_wipe_tower_placement_warnings(output) == []

        range_data = component_inputs["layer_config_ranges"]
        range_root = ET.fromstring(package.read("Metadata/layer_config_ranges.xml"))
        actual_ranges = range_root.findall("./object/range")
        assert len(actual_ranges) == len(range_data["ranges"])
        for actual, expected in zip(actual_ranges, range_data["ranges"]):
            assert float(actual.attrib["min_z"]) == pytest.approx(expected["min_z"])
            assert float(actual.attrib["max_z"]) == pytest.approx(expected["max_z"])
            target_filename = (
                "bambu-studio-02.09.01.70.json"
                if slicer == "BambuStudio"
                else "orca-slicer-2.4.2.json"
            )
            fatcat_module = importlib.import_module("fatcat_metadata")
            target_path = (
                Path(fatcat_module.__file__).resolve().parent
                / "fatcat_metadata_data"
                / "translations"
                / "targets"
                / target_filename
            )
            target_data = json.loads(target_path.read_text(encoding="utf-8"))
            option_fields = target_data["package_dialect"]["metadata_components"][
                "layer_config_ranges"
            ]["option_fields"]
            expected_options = []
            if expected.get("use_default_extruder"):
                expected_options.append(
                    (
                        option_fields["default_extruder_key"],
                        option_fields["default_extruder_value"],
                    )
                )
            layer_height = expected.get("layer_height_mm", float(project["layer_height"]))
            expected_options.append(
                (
                    option_fields["layer_height_key"],
                    format(float(layer_height), ".17g"),
                )
            )
            if "infill_density_percent" in expected:
                expected_options.append(
                    (
                        option_fields["infill_density_key"],
                        format(float(expected["infill_density_percent"]), ".17g")
                        + option_fields["infill_density_suffix"],
                    )
                )
            assert [
                (item.attrib["opt_key"], item.text or "")
                for item in actual.findall("./option")
            ] == expected_options

        assert [float(value) for value in build_item.attrib["transform"].split()[-3:]] == pytest.approx(
            helper_inputs["build_translation"]
        )
        if slicer == "OrcaSlicer":
            assert build_item.attrib["auto_drop"] == "1"
        else:
            assert "auto_drop" not in build_item.attrib
