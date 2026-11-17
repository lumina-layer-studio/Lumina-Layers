"""Existing P1P/X1 registry identities enter the shared route without guessing."""

import json

import pytest
import trimesh

from core.machine_registry import load_machine_registry, resolve_machine_registry_root
from utils.bambu_3mf_writer import BambuStudio3MFWriter
from utils.fatcat_metadata import compose_builtin_project_settings, select_metadata_target


PRINTERS = {"p1p": "bambu-p1p", "x1": "bambu-lab-x1",
            "x1-carbon": "bambu-x1c", "x1e": "bambu-x1e"}


def new_devices():
    registry = load_machine_registry(resolve_machine_registry_root() / "registry.json")
    selected = {f"{s}:bbl:bambu-lab-{m}" for s in ("BambuStudio", "OrcaSlicer") for m in PRINTERS}
    return [device for device in registry.devices_by_id.values() if device.machine_profile_id in selected]


def test_scope_is_only_existing_supported_32_devices_and_176_plates():
    devices = new_devices()
    assert len(devices) == len({d.device_profile_id for d in devices}) == 32
    assert all(d.supported for d in devices)
    assert sum(len(d.build_plates) for d in devices) == 176


@pytest.mark.parametrize("device", new_devices(), ids=lambda d: d.device_profile_id)
def test_each_real_alias_nozzle_and_valid_plate_delegates_hardware_selection(device):
    machine = device.machine_profile_id.split(":bbl:bambu-lab-")[1]
    for plate in device.build_plates:
        target = select_metadata_target(
            slicer=device.slicer_id, printer_id=PRINTERS[machine],
            nozzle_size=device.nozzle_size, device_profile_id=device.device_profile_id,
            build_plate_id=plate.id,
        )
        assert target is not None
        assert target.machine_uid == f"bambu-lab:{machine}"
        assert target.nozzle_uid == f"nozzle:{device.nozzle_size}mm"
        assert target.application_version == {"BambuStudio": "02.09.01.70", "OrcaSlicer": "2.4.2"}[device.slicer_id]


@pytest.mark.parametrize("printer_id", ["bambu-x1-carbon", "bambu-x1", "bambu-p1s"])
def test_registry_profile_rejects_mismatched_printer_alias(printer_id):
    with pytest.raises(ValueError, match="does not match requested printer"):
        select_metadata_target(
            slicer="BambuStudio", printer_id=printer_id, nozzle_size="0.4",
            device_profile_id="BambuStudio:bbl:bambu-lab-x1-carbon:0.4",
            build_plate_id="textured-pei-plate",
        )


def test_exact_registry_profile_pins_source_hardware():
    target = select_metadata_target(
        slicer="BambuStudio", printer_id="bambu-x1c", nozzle_size="0.4",
        device_profile_id="BambuStudio:bbl:bambu-lab-x1-carbon:0.4",
        build_plate_id="textured-pei-plate",
    )
    assert target.machine_uid == "bambu-lab:x1-carbon"
    assert target.nozzle_uid == "nozzle:0.4mm"


@pytest.mark.parametrize("slicer", ["BambuStudio", "OrcaSlicer"])
def test_x1_native_source_uses_exact_binding_for_selected_material(tmp_path, slicer):
    writer = BambuStudio3MFWriter(
        str(tmp_path / "x1.3mf"), printer_id="bambu-lab-x1", slicer=slicer,
        nozzle_size="0.6", device_profile_id=f"{slicer}:bbl:bambu-lab-x1:0.6",
    )
    writer.add_mesh(trimesh.creation.box(extents=(4, 4, 1.2)), "Red", (200, 20, 30))
    target = writer._select_metadata_target()
    request = writer._build_fatcat_project_request([("Red", (200, 20, 30))], target)
    assert request["project_source"] == "fatcat_native"
    assert request["machine_uid"] == "bambu-lab:x1"
    assert request["nozzle_uid"] == "nozzle:0.6mm"
    final = json.loads(compose_builtin_project_settings(request)["project_settings_json"])
    assert final["filament_type"] == ["PLA"]
    assert final["filament_settings_id"] == ["Bambu PLA Basic @BBL X1"]
    assert final["filament_colour"] == ["#C8141E"]


def test_x1_builtin_uses_selected_display_colour_for_native_slot(tmp_path):
    writer = BambuStudio3MFWriter(
        str(tmp_path / "x1-full.3mf"), printer_id="bambu-lab-x1", slicer="OrcaSlicer",
        nozzle_size="0.6", device_profile_id="OrcaSlicer:bbl:bambu-lab-x1:0.6",
        preserve_template_filament_slots=True,
    )
    writer.add_mesh(trimesh.creation.box(extents=(4, 4, 1.2)), "Red", (200, 20, 30))
    request = writer._build_fatcat_project_request(
        [("Red", (200, 20, 30))], writer._select_metadata_target(),
    )
    final = json.loads(compose_builtin_project_settings(request)["project_settings_json"])
    assert final["filament_colour"] == ["#C8141E"]
    assert final["filament_multi_colour"] == final["filament_colour"]
    assert "nozzle_temperature" not in request
