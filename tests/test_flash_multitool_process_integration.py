"""Flash multi-tool exports retain the selected native heating policy."""

import json
import zipfile

import pytest
import trimesh

from utils.slicer_3mf_writer import Slicer3MFWriter


@pytest.mark.parametrize(("machine", "nozzle", "native_process"), [
    ("creator-5-pro", "0.4", "0.20mm Standard @FF C5"),
    ("creator-5", "0.4", "0.20mm Standard @FF C5"),
    ("creator-5", "0.25", "0.12mm Standard @FF C5 0.25 nozzle"),
])
def test_export_preserves_multitool_heating_and_requested_process(
    tmp_path, machine, nozzle, native_process,
):
    output = tmp_path / "four-colour.3mf"
    names = ["White", "Red", "Yellow", "Blue"]
    colours = [(255, 255, 255), (220, 20, 60), (255, 230, 0), (0, 100, 240)]
    writer = Slicer3MFWriter(
        str(output),
        settings={"layer_height": "0.08", "wall_loops": "2", "travel_speed": "140"},
        slicer="FlashStudio", printer_id=f"flashforge-{machine}", nozzle_size=nozzle,
        device_profile_id=f"FlashStudio:flashforge:flashforge-{machine}:{nozzle}",
        build_plate_id="textured-pei-plate", preserve_template_filament_slots=False,
        material_types=dict.fromkeys(names, "PLA"),
    )
    for index, (name, colour) in enumerate(zip(names, colours)):
        mesh = trimesh.creation.box(extents=[6, 6, 0.24])
        mesh.apply_translation([index * 7, 0, 0.12])
        writer.add_mesh(mesh, name, colour)
    writer.export()
    with zipfile.ZipFile(output) as archive:
        project = json.loads(archive.read("Metadata/project_settings.config"))
    assert project["default_print_profile"] == native_process
    assert project["ooze_prevention"] == "1"
    assert project["standby_temperature_delta"] == "-100"
    assert project["enable_tower_interface_features"] == "1"
    assert project["wipe_tower_wall_type"] == "rib"
    assert project["layer_height"] == "0.08"
    assert project["initial_layer_print_height"] == "0.08"
    assert project["wall_loops"] == "2"
    assert project["travel_speed"] == "140"
    assert project["filament_colour"] == ["#FFFFFF", "#DC143C", "#FFE600", "#0064F0"]
    assert len(project["filament_settings_id"]) == 4
    assert project["filament_change_length"] == ["0"] * 4
