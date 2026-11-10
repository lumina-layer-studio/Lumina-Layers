"""Native-saved user tuning crosses the real persistent-template boundary."""

from io import BytesIO
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pytest
import trimesh

from core import custom_3mf_templates
import utils.bambu_3mf_writer as writer_module

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "fatcat"
SOURCE = FIXTURES / "bambu-p1s-02-user-tuned-native-template.3mf"


def test_material_preflight_rejects_palette_larger_than_imported_template(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api.app import app

    monkeypatch.setattr(custom_3mf_templates, "_root", lambda: tmp_path / "templates")
    record = custom_3mf_templates.import_template(SOURCE.read_bytes(), "Two slots")
    with TestClient(app) as client:
        response = client.post("/api/convert/export-materials", json={"params": {
            "printer_id": "bambu-p1s", "slicer": "BambuStudio", "nozzle_size": "0.2",
            "device_profile_id": "BambuStudio:bbl:bambu-lab-p1s:0.2",
            "custom_3mf_template_id": record["id"],
            "lut_name": "bambulab - bambulab_pla_basic_rybw", "color_mode": "4-Color (RYBW)",
        }})
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "template_slot_capacity"
    assert detail["required_slots"] == 4
    assert detail["available_slots"] == 2


def test_direct_template_export_reports_capacity_before_queuing_meshes(tmp_path, monkeypatch):
    from core.errors import CoreValidationError

    monkeypatch.setattr(custom_3mf_templates, "_root", lambda: tmp_path / "templates")
    record = custom_3mf_templates.import_template(SOURCE.read_bytes(), "Two slots")
    writer = writer_module.BambuStudio3MFWriter(
        str(tmp_path / "output.3mf"), printer_id="bambu-p1s", slicer="BambuStudio",
        nozzle_size="0.2", custom_3mf_template_id=record["id"],
        enable_wipe_tower_auto_placement=False,
    )
    for name, colour in (("White", (255, 255, 255)), ("Black", (0, 0, 0)), ("Blue", (0, 0, 255))):
        writer.add_mesh(trimesh.creation.box(), name, colour)
    monkeypatch.setattr(
        writer, "_queue_meshes",
        lambda *args: pytest.fail("Template capacity must be checked before queuing meshes"),
    )
    with pytest.raises(CoreValidationError) as error:
        writer.export()
    assert error.value.required_slots == 3
    assert error.value.available_slots == 2
    assert not (tmp_path / "output.3mf").exists()


def test_material_preflight_counts_actual_preview_slots_instead_of_ui_color_mode(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api.app import app
    from api.dependencies import get_session_store
    from api.session_store import SessionStore
    from config import ColorSystem
    from utils.lut_manager import LUTManager

    monkeypatch.setattr(custom_3mf_templates, "_root", lambda: tmp_path / "templates")
    record = custom_3mf_templates.import_template(SOURCE.read_bytes(), "Two slots")
    store = SessionStore()
    session_id = store.create()
    store.put(session_id, "lut_path", LUTManager.get_lut_path("bambulab - bambulab_pla_basic_rybw"))
    colour_config = ColorSystem.get("6-Color")
    store.put(session_id, "preview_cache", {
        "slot_names": colour_config["slots"],
        "preview_colors": colour_config["preview"],
        "color_conf": colour_config,
    })
    monkeypatch.setitem(app.dependency_overrides, get_session_store, lambda: store)

    try:
        with TestClient(app) as client:
            response = client.post("/api/convert/export-materials", json={
                "session_id": session_id,
                "params": {
                    "printer_id": "bambu-p1s", "slicer": "BambuStudio", "nozzle_size": "0.2",
                    "device_profile_id": "BambuStudio:bbl:bambu-lab-p1s:0.2",
                    "custom_3mf_template_id": record["id"],
                    "lut_name": "bambulab - bambulab_pla_basic_rybw",
                    "color_mode": "4-Color (RYBW)",
                },
            })
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "template_slot_capacity"
        assert detail["required_slots"] == 6
        assert detail["available_slots"] == 2
    finally:
        store.clear_all()


def test_material_facts_keep_cached_order_before_coating_and_virtual_materials():
    from core.export_material_selection import _source_materials
    from utils.lut_manager import LUTManager

    materials = _source_materials(
        {"color_mode": "4-Color (RYBW)", "enable_coating": True},
        {
            "lut_path": LUTManager.get_lut_path("bambulab - bambulab_pla_basic_rybw"),
            "slot_names": ["Blue", "White", "Red", "Yellow"],
            "preview_colors": {
                0: [10, 20, 30, 255], 1: [240, 241, 242, 255],
                2: [210, 20, 30, 255], 3: [230, 220, 20, 255],
            },
            "recipe_overrides": [{
                "region_id": "custom",
                "virtual_materials": [{"name": "Silver", "hex": "#8899AA"}],
            }],
        },
    )

    assert [material["name"] for material in materials] == [
        "Blue", "White", "Red", "Yellow", "Coating", "Silver",
    ]
    assert [material["colour"] for material in materials] == [
        "#0A141E", "#F0F1F2", "#D2141E", "#E6DC14", "#C8C8C8", "#8899AA",
    ]


def test_cached_six_colour_slots_keep_generation_material_types():
    from config import ColorSystem
    from core.export_material_selection import _source_materials
    from utils.lut_manager import LUTManager

    colours = ColorSystem.get("6-Color")
    materials = _source_materials(
        {"color_mode": "4-Color (RYBW)"},
        {
            "lut_path": LUTManager.get_lut_path("bambulab - bambulab_pla_basic_rybw"),
            "lut_metadata": None,
            "slot_names": colours["slots"],
            "preview_colors": colours["preview"],
            "color_conf": colours,
        },
    )

    assert [material["name"] for material in materials] == colours["slots"]
    assert [material["material_type"] for material in materials] == ["PLA Basic"] * 6


def test_used_slot_subset_does_not_drop_the_full_source_palette():
    from config import LUTMetadata, PaletteEntry
    from core.export_material_selection import _source_materials

    materials = _source_materials(
        {"color_mode": "4-Color (CMYW)"},
        {
            "lut_metadata": LUTMetadata(palette=[
                PaletteEntry(color=name, material="PLA Basic")
                for name in ("White", "Cyan", "Magenta", "Yellow")
            ]),
            "slot_names": ["White"],
            "preview_colors": {"White": [255, 255, 255, 255]},
        },
    )

    assert [material["name"] for material in materials] == ["White", "Cyan", "Magenta", "Yellow"]
    assert [material["material_type"] for material in materials] == ["PLA Basic"] * 4
    assert [material["colour"] for material in materials] == ["#FFFFFF", "#0086D6", "#EC008C", "#F4EE2A"]


def test_cached_lut_material_types_and_coating_follow_final_slot_names():
    from config import LUTMetadata, PaletteEntry
    from core.export_material_selection import _source_materials

    materials = _source_materials(
        {"enable_coating": True},
        {
            "lut_metadata": LUTMetadata(palette=[
                PaletteEntry(color="White", material="PETG"),
                PaletteEntry(color="Blue", material="PETG"),
            ]),
            "slot_names": ["Blue", "White"],
            "preview_colors": {0: [10, 20, 30, 255], 1: [240, 241, 242, 255]},
            "recipe_overrides": [{
                "region_id": "custom", "virtual_materials": [{"name": "Silver", "hex": "#8899AA"}],
            }],
        },
    )

    assert [(material["name"], material.get("material_type")) for material in materials] == [
        ("Blue", "PETG"), ("White", "PETG"), ("Coating", "PETG"), ("Silver", None),
    ]


def test_cached_archive_material_types_follow_names_after_reordering(monkeypatch):
    import numpy as np
    from core.export_material_selection import _source_materials
    from core.material_color_solver import MaterialParams

    archive_materials = [
        MaterialParams(
            name=name, directory_name=name, E=np.ones(3), k=np.ones(3),
            C0_white=np.ones(3), estimated_rgb=np.asarray(colour, dtype=np.uint8),
            material_type=kind,
        )
        for name, colour, kind in (
            ("White", (240, 241, 242), "PLA"), ("Blue", (10, 20, 30), "PETG"),
        )
    ]
    monkeypatch.setattr("core.export_material_selection.load_materials", lambda *args, **kwargs: archive_materials)

    materials = _source_materials(
        {"enable_coating": True},
        {
            "material_source": "material_archive", "selected_materials": ["White", "Blue"],
            "slot_names": ["Blue", "White"],
            "preview_colors": {0: [10, 20, 30, 255], 1: [240, 241, 242, 255]},
        },
    )

    assert [(material["name"], material["material_type"]) for material in materials] == [
        ("Blue", "PETG"), ("White", "PLA"), ("Coating", "PLA"),
    ]


@pytest.mark.parametrize("policy,count", [(None, 2), (False, 2), (False, 1)])
def test_native_saved_template_keeps_real_tuning_and_routes_new_geometry(tmp_path, monkeypatch, policy, count):
    monkeypatch.setattr(custom_3mf_templates, "_root", lambda: tmp_path / "stored-templates")
    template = custom_3mf_templates.import_template(SOURCE.read_bytes(), "Bambu GUI tuned material")
    with ZipFile(SOURCE) as package:
        original = json.loads(package.read("Metadata/project_settings.config"))
    assert original["nozzle_temperature_initial_layer"][:2] == ["217", "220"]
    assert original["nozzle_temperature"][:2] == ["213", "220"]
    assert original["filament_flow_ratio"][:2] == ["0.93", "0.95"]
    assert original["filament_retraction_length"][:2] == ["0.61", "0.72"]

    output = tmp_path / "new-geometry.3mf"
    writer = writer_module.BambuStudio3MFWriter(
        str(output), printer_id="bambu-p1s", slicer="BambuStudio", nozzle_size="0.2",
        device_profile_id="BambuStudio:bbl:bambu-lab-p1s:0.2", build_plate_id="textured-pei-plate",
        custom_3mf_template_id=template["id"], preserve_template_filament_slots=policy,
        settings={"layer_height": "0.12", "initial_layer_print_height": "0.20"},
        enable_base_layer_height_modifier=False, enable_wipe_tower_auto_placement=False,
    )
    palette = [("White", (230, 240, 250)), ("PETG Black", (10, 20, 30))][:count]
    for name, colour in palette:
        writer.add_mesh(trimesh.creation.box(extents=(6, 5, 1.2)), name, colour)


    composer = writer_module.compose_project_settings
    requests = []

    def capture(source, request):
        requests.append(request)
        return composer(source, request)

    monkeypatch.setattr(writer_module, "compose_project_settings", capture)
    writer.export()
    assert len(requests) == 1
    assert requests[0]["material_mode"] == "preserve_template"
    assert requests[0]["preserve_source_material_settings"] is True
    assert "material_uids" not in requests[0]
    with ZipFile(output) as package:
        final = json.loads(package.read("Metadata/project_settings.config"))
        model = package.read("Metadata/model_settings.config").decode("utf-8")
    slots = 2 if policy is None else count
    for key in ("nozzle_temperature", "nozzle_temperature_initial_layer", "filament_flow_ratio", "filament_retraction_length"):
        assert final[key] == original[key][:slots * 2], key
    for key in ("filament_type", "filament_settings_id"):
        assert final[key] == original[key][:slots], key
    assert final["filament_self_index"] == [str(i + 1) for i in range(slots) for _ in range(2)]
    assert final["print_settings_id"] == original["print_settings_id"]
    assert final["outer_wall_speed"] == original["outer_wall_speed"]
    assert final["filament_colour"][:count] == ["#E6F0FA", "#0A141E"][:count]
    assert len(final["different_settings_to_system"]) == slots + 2
    assert "filament_retraction_length" in final["different_settings_to_system"][1].split(";")
    assert model.count('key="extruder"') >= count
    assert not any(key.startswith("_lumina_template_") for key in final)


@pytest.mark.parametrize("selected_plate,expected,sidecar", [
    (None, "High Temp Plate", "hot_plate"),
    ("smooth-pei-plate", "High Temp Plate", "hot_plate"),
    ("textured-pei-plate", "Textured PEI Plate", "textured_plate"),
])
def test_imported_native_plate_override_survives_unless_explicitly_reselected(
    tmp_path, monkeypatch, selected_plate, expected, sidecar,
):
    source = FIXTURES / "bambu-a1mini-02-smooth-native-sliced.3mf"
    monkeypatch.setattr(custom_3mf_templates, "_root", lambda: tmp_path / "stored-templates")
    record = custom_3mf_templates.import_template(source.read_bytes(), "Native smooth plate")
    loaded = custom_3mf_templates.load_template(record["id"])
    assert loaded["curr_bed_type"] == "Textured PEI Plate"
    assert loaded["_lumina_template_plate_value"] == "High Temp Plate"
    assert loaded["_lumina_template_sidecar_bed"] == "hot_plate"
    output = tmp_path / "native-plate.3mf"
    writer = writer_module.BambuStudio3MFWriter(
        str(output), printer_id="bambu-a1-mini", slicer="BambuStudio", nozzle_size="0.2",
        device_profile_id="BambuStudio:bbl:bambu-lab-a1-mini:0.2",
        build_plate_id=selected_plate, custom_3mf_template_id=record["id"],
        enable_base_layer_height_modifier=False, enable_wipe_tower_auto_placement=False,
    )
    writer.add_mesh(trimesh.creation.box(extents=(6, 5, 1.2)), "White", (230, 240, 250))
    writer.export()
    with ZipFile(output) as package:
        project = json.loads(package.read("Metadata/project_settings.config"))
        model = ET.fromstring(package.read("Metadata/model_settings.config"))
    assert project["curr_bed_type"] == expected
    assert model.find("./plate/metadata[@key='bed_type']").get("value") == expected
    if selected_plate is None:
        assert writer._template_build_plate["sidecar_value"] == sidecar
    for key in ("hot_plate_temp", "textured_plate_temp"):
        assert project[key] == loaded[key]


@pytest.mark.parametrize("policy", [None, True, False])
def test_orca_imported_process_tuning_is_not_an_ordinary_export_default(tmp_path, monkeypatch, policy):
    monkeypatch.setattr(custom_3mf_templates, "_root", lambda: tmp_path / "stored-templates")
    options = dict(
        printer_id="bambu-p1s", slicer="OrcaSlicer", nozzle_size="0.6",
        device_profile_id="OrcaSlicer:bbl:bambu-lab-p1s:0.6",
        build_plate_id="textured-pei-plate", enable_wipe_tower_auto_placement=False,
        enable_base_layer_height_modifier=False,
    )
    source_writer = writer_module.BambuStudio3MFWriter(
        str(tmp_path / "unused.3mf"), **options,
    )
    source_writer.add_mesh(
        trimesh.creation.box(extents=(6, 5, 1.2)), "White", (230, 240, 250)
    )
    source = source_writer._get_base_config_template()
    tuning = {"precise_outer_wall": "1", "outer_wall_speed": "47", "normal_acceleration": "1234"}
    source.update(tuning)
    tokens = set(source["different_settings_to_system"][0].split(";")) | tuning.keys()
    source["different_settings_to_system"][0] = ";".join(sorted(tokens - {""}))
    payload = BytesIO()
    with ZipFile(payload, "w") as package:
        package.writestr("Metadata/project_settings.config", json.dumps(source))
        package.writestr("3D/3dmodel.model", '<model><metadata name="OrcaSlicer">2.4.2</metadata></model>')
    record = custom_3mf_templates.import_template(payload.getvalue(), "Orca process tuning")
    output = tmp_path / "custom-orca.3mf"
    writer = writer_module.BambuStudio3MFWriter(
        str(output), **options, custom_3mf_template_id=record["id"],
        preserve_template_filament_slots=policy,
    )
    writer.add_mesh(trimesh.creation.box(extents=(6, 5, 1.2)), "White", (230, 240, 250))
    writer.export()
    with ZipFile(output) as package:
        final = json.loads(package.read("Metadata/project_settings.config"))
    assert {key: final[key] for key in tuning} == tuning
    assert set(tuning) <= set(final["different_settings_to_system"][0].split(";"))
    slots = 1 if policy is False else len(source["filament_settings_id"])
    assert final["filament_flow_ratio"] == source["filament_flow_ratio"][:slots * 2]
