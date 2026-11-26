"""Native template mapping caches must not replace material identities."""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
from unittest.mock import AsyncMock
import xml.etree.ElementTree as ET
from zipfile import ZipFile

import pytest
import trimesh

from core import custom_3mf_templates
from utils.bambu_3mf_writer import BambuStudio3MFWriter
from utils.fatcat_metadata import (
    build_builtin_project_settings_request,
    compose_builtin_project_settings,
    select_metadata_target,
)


DEVICE = {
    "printer_id": "bambu-h3c", "slicer": "BambuStudio", "nozzle_size": "0.4",
    "device_profile_id": "BambuStudio:bbl:bambu-lab-h3c:0.4",
}
SOURCE = Path(__file__).parent / "fixtures/fatcat/bambu-p1s-02-user-tuned-native-template.3mf"


@pytest.fixture
def native_project() -> dict:
    """Use public presets with the ticket's 8 materials / 7 cached maps shape."""
    target = select_metadata_target(**DEVICE, build_plate_id="textured-pei-plate")
    request = build_builtin_project_settings_request({}, [
        {"name": f"PETG {slot}", "colour": f"#{slot + 1:02X}2233", "material_type": "PETG"}
        for slot in range(8)
    ], target=target)
    project = json.loads(compose_builtin_project_settings(request)["project_settings_json"])
    project["filament_settings_id"] = [f"Edited PETG {slot}" for slot in range(8)]
    project["nozzle_temperature"] = [str(225 + slot + variant) for slot in range(8) for variant in range(2)]
    project["filament_flow_ratio"] = [str(0.9 + slot / 100) for slot in range(8) for _ in range(2)]
    project["filament_nozzle_map"] = ["1", "0", "0", "0", "0", "0", "0"]
    project["filament_volume_map"] = ["0"] * 7
    project["filament_map_mode"] = "Auto For Flush"
    return project


def _store_template(project: dict, tmp_path: Path, monkeypatch) -> str:
    monkeypatch.setattr(custom_3mf_templates, "_root", lambda: tmp_path / "templates")
    payload = BytesIO()
    with ZipFile(SOURCE) as original, ZipFile(payload, "w") as output:
        for part in original.namelist():
            output.writestr(part, json.dumps(project) if part == "Metadata/project_settings.config" else original.read(part))
    return custom_3mf_templates.import_template(payload.getvalue(), "Edited native template")["id"]


def _writer(
    template_id: str, output: Path, slots: list[int], project: dict, *, compact: bool = False,
) -> BambuStudio3MFWriter:
    writer = BambuStudio3MFWriter(
        str(output), **DEVICE, custom_3mf_template_id=template_id,
        enable_base_layer_height_modifier=False, enable_wipe_tower_auto_placement=False,
        preserve_template_filament_slots=False if compact else None,
    )
    writer._set_project_palette(
        [f"PETG {slot}" for slot in slots],
        {f"PETG {slot}": tuple(bytes.fromhex(project["filament_colour"][slot][1:])) for slot in slots},
        source_slot_indices={f"PETG {slot}": slot for slot in slots},
    )
    for index, slot in enumerate(slots):
        mesh = trimesh.creation.box(extents=(5, 5, 0.6))
        mesh.apply_translation((index * 6, 0, 0.3))
        writer.add_mesh(mesh, f"PETG {slot}", tuple(bytes.fromhex(project["filament_colour"][slot][1:])))
    return writer


@pytest.mark.parametrize("mode", ["Auto For Flush", "Auto For Match"])
def test_automatic_stale_maps_export_without_changing_saved_template(native_project, tmp_path, monkeypatch, mode):
    native_project["filament_map_mode"] = mode
    template_id = _store_template(native_project, tmp_path, monkeypatch)
    original = custom_3mf_templates.load_template(template_id)
    output = tmp_path / "seven-colours.3mf"
    _writer(template_id, output, list(range(7)), native_project).export()

    assert custom_3mf_templates.load_template(template_id) == original
    with ZipFile(output) as package:
        project = json.loads(package.read("Metadata/project_settings.config"))
        model = ET.fromstring(package.read("Metadata/model_settings.config"))
    for key in ("filament_settings_id", "filament_ids", "filament_type", "filament_flow_ratio",
                "nozzle_temperature", "nozzle_temperature_initial_layer", "filament_extruder_variant"):
        assert project[key] == original[key], key
    assert "filament_nozzle_map" not in project
    assert "filament_volume_map" not in project
    assert set(node.attrib["value"] for node in model.findall(".//metadata[@key='extruder']")) == {str(i) for i in range(1, 8)}


@pytest.mark.parametrize("mode", ["Manual", "Nozzle Manual"])
def test_generate_rejects_incomplete_manual_mapping_before_worker(native_project, tmp_path, monkeypatch, mode):
    from fastapi.testclient import TestClient
    from api.app import app
    from api.dependencies import get_file_registry, get_session_store, get_worker_pool
    from api.file_registry import FileRegistry
    from api.session_store import SessionStore
    from api.worker_pool import WorkerPoolManager
    from tests.test_converter_generate_error_language_unit import _seed_generate_session

    native_project["filament_map_mode"] = mode
    template_id = _store_template(native_project, tmp_path, monkeypatch)
    original = custom_3mf_templates.load_template(template_id)
    store = SessionStore()
    registry = FileRegistry()
    pool = AsyncMock(spec=WorkerPoolManager)
    pool.submit_timed.side_effect = RuntimeError("must be rejected before geometry generation")
    session_id = _seed_generate_session(store, tmp_path)
    monkeypatch.setitem(app.dependency_overrides, get_session_store, lambda: store)
    monkeypatch.setitem(app.dependency_overrides, get_file_registry, lambda: registry)
    monkeypatch.setitem(app.dependency_overrides, get_worker_pool, lambda: pool)
    try:
        response = TestClient(app, raise_server_exceptions=False).post("/api/convert/generate", json={
            "session_id": session_id,
            "params": {**DEVICE, "custom_3mf_template_id": template_id, "lut_name": "test_lut"},
        })
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "template_material_mapping"
        assert detail["field"] == "filament_nozzle_map"
        assert detail["material_count"] == 8
        assert detail["value_count"] == 7
        assert "Bambu Studio" in detail["message"]
        assert "import" in detail["message"]
        pool.submit_timed.assert_not_awaited()
        assert custom_3mf_templates.load_template(template_id) == original
    finally:
        registry.clear_all()
        store.clear_all()


def test_compact_reordering_keeps_whole_material_variant_groups(native_project, tmp_path, monkeypatch):
    template_id = _store_template(native_project, tmp_path, monkeypatch)
    output = tmp_path / "reordered.3mf"
    slots = [6, 1, 0]
    _writer(template_id, output, slots, native_project, compact=True).export()
    with ZipFile(output) as package:
        project = json.loads(package.read("Metadata/project_settings.config"))
    for key in ("filament_settings_id", "filament_ids", "filament_flow_ratio", "nozzle_temperature",
                "filament_extruder_variant", "filament_dev_ams_drying_temperature"):
        source = native_project[key]
        width = len(source) // 8
        assert project[key] == [value for slot in slots for value in source[slot * width:(slot + 1) * width]], key


@pytest.mark.parametrize("size", [0, 1, 8, 16])
def test_manual_mapping_keeps_native_empty_broadcast_and_group_shapes(native_project, tmp_path, monkeypatch, size):
    native_project["filament_map_mode"] = "Nozzle Manual"
    for field in ("filament_nozzle_map", "filament_volume_map"):
        native_project[field] = ["0"] * size
    template_id = _store_template(native_project, tmp_path, monkeypatch)
    writer = _writer(template_id, tmp_path / "complete-manual.3mf", list(range(7)), native_project)
    assert writer._custom_template["filament_nozzle_map"] == native_project["filament_nozzle_map"]
    assert writer._custom_template["filament_volume_map"] == native_project["filament_volume_map"]
    writer.export()


def test_other_incomplete_material_arrays_remain_strict(native_project, tmp_path, monkeypatch):
    native_project["filament_change_length"] = ["1", "2", "3"]
    template_id = _store_template(native_project, tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="filament_change_length.*unresolved slot shape"):
        _writer(template_id, tmp_path / "invalid-material.3mf", list(range(7)), native_project).export()


def test_template_material_preflight_uses_the_same_mapping_validation(native_project, tmp_path, monkeypatch):
    from core.errors import TemplateMaterialMappingError
    from core.export_material_selection import resolve_export_material_selection

    native_project["filament_map_mode"] = "Manual"
    native_project["filament_nozzle_map"] = ["1"] * 8
    template_id = _store_template(native_project, tmp_path, monkeypatch)
    with pytest.raises(TemplateMaterialMappingError) as failure:
        resolve_export_material_selection({**DEVICE, "custom_3mf_template_id": template_id})
    assert failure.value.field == "filament_volume_map"


def test_non_bambu_template_routing_is_untouched(native_project):
    from core.template_material_mapping import prepare_template_for_export
    from utils.fatcat_metadata import select_user_template_metadata_target

    target = select_user_template_metadata_target(slicer="OrcaSlicer", build_plate_id=None)
    prepared = prepare_template_for_export(native_project, target=target)
    assert prepared == native_project
    prepared["filament_nozzle_map"].append("2")
    assert len(native_project["filament_nozzle_map"]) == 7
