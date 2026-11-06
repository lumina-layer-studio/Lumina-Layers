"""Exercise the published November SDK through Lumina's device/export paths."""

import json
from pathlib import Path
import zipfile

import pytest
import trimesh

from core.machine_registry import load_machine_registry
from utils.bambu_3mf_writer import BambuStudio3MFWriter


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("nozzle", ["0.2", "0.4", "0.6", "0.8"])
def test_h3c_picker_selection_resolves_native_target(nozzle):
    writer = BambuStudio3MFWriter(
        "h3c.3mf", settings={}, slicer="BambuStudio", printer_id="bambu-h3c",
        nozzle_size=nozzle, device_profile_id=f"BambuStudio:bbl:bambu-lab-h3c:{nozzle}",
        build_plate_id="textured-pei-plate",
    )
    target = writer._select_metadata_target()
    assert target.machine_uid == "bambu-lab:h3c"
    assert target.nozzle_uid == f"nozzle:{nozzle}mm"
    assert target.application_version == "02.09.01.70"
    writer.add_mesh(trimesh.creation.box(), "PLA", (150, 150, 150))
    assert writer._get_base_config_template()["printer_settings_id"] == (
        f"Bambu Lab H3C {nozzle} nozzle"
    )


def test_h3c_mixed_material_export_preserves_native_groups_and_process(tmp_path):
    path = tmp_path / "h3c-mixed.3mf"
    names = ["PLA left", "TPU", "PLA right"]
    writer = BambuStudio3MFWriter(
        str(path), settings={"layer_height": "0.2", "wall_loops": "3"},
        slicer="BambuStudio", printer_id="bambu-h3c", nozzle_size="0.4",
        device_profile_id="BambuStudio:bbl:bambu-lab-h3c:0.4",
        build_plate_id="textured-pei-plate",
        preserve_template_filament_slots=False,
        material_types={names[0]: "PLA Basic", names[1]: "TPU for AMS", names[2]: "PLA Basic"},
        native_filament_profiles={
            names[0]: "Bambu PLA Basic @BBL H3C",
            names[1]: "Bambu TPU for AMS @BBL H3C",
            names[2]: "Bambu PLA Basic @BBL H3C",
        },
    )
    for index, name in enumerate(names):
        mesh = trimesh.creation.box(extents=[5, 5, 1])
        mesh.apply_translation([index * 8, 0, 0.5])
        writer.add_mesh(mesh, name, (40 + index * 80, 100, 150))
    writer.export()
    with zipfile.ZipFile(path) as archive:
        project = json.loads(archive.read("Metadata/project_settings.config"))
    assert project["printer_settings_id"] == "Bambu Lab H3C 0.4 nozzle"
    assert project["filament_settings_id"] == [
        "Bambu PLA Basic @BBL H3C", "Bambu TPU for AMS @BBL H3C",
        "Bambu PLA Basic @BBL H3C",
    ]
    assert project["nozzle_temperature"] == ["220", "220", "230", "230", "220", "220"]
    assert project["layer_height"] == "0.2"
    assert project["wall_loops"] == "3"


def test_current_prusa_picker_has_artwork_for_every_native_machine():
    registry = load_machine_registry(ROOT / "machine_registry" / "registry.json")
    devices = [device for device in registry.devices_by_id.values()
               if device.slicer_id == "PrusaSlicer"]
    assert devices
    for device in devices:
        assert device.source_version == "3.0.0-alpha13"
        assert device.thumbnail
        assert (ROOT / "machine_registry" / device.thumbnail).is_file()
