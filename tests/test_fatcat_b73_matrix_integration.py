"""Exact installed metadata for the finite existing P1P/X1-family matrix."""

from copy import deepcopy
from io import BytesIO
import json
import re
from zipfile import ZipFile

import pytest
import trimesh

from core import custom_3mf_templates
from core.errors import NativeMaterialSelectionError
from core.wipe_tower_placement import Rect
from fatcat_material_assertions import (
    assert_native_materials, native_materials_support_plate,
    native_material_profile_gap, native_plate_binding,
)
from fatcat_native_source_fixtures import complete_native_project, assert_source_material_snapshot
from test_fatcat_b73_routing_unit import PRINTERS, new_devices
import utils.bambu_3mf_writer as writer_module
from utils.fatcat_metadata import (
    compose_builtin_project_settings,
    compose_project_settings,
    read_project_layout,
)

DEVICES = new_devices()
MATRIX = [(device, plate) for device in DEVICES for plate in device.build_plates]


def make_writer(tmp_path, device, *, plate=None, policy=False, **kwargs):
    machine = device.machine_profile_id.split(":bbl:bambu-lab-")[1]
    return writer_module.BambuStudio3MFWriter(
        str(tmp_path / "matrix.3mf"), printer_id=PRINTERS[machine],
        slicer=device.slicer_id, nozzle_size=device.nozzle_size,
        device_profile_id=device.device_profile_id,
        build_plate_id=plate.id if plate else device.default_build_plate_id,
        preserve_template_filament_slots=policy,
        enable_wipe_tower_auto_placement=False, **kwargs,
    )


def seed_selected_materials(writer, palette):
    writer._set_project_palette([name for name, _ in palette], dict(palette))
    for index, (name, colour) in enumerate(palette):
        mesh = trimesh.creation.box(extents=(6.0, 5.0, 1.2))
        mesh.apply_translation((index * 8.0, 0.0, 0.6))
        writer.add_mesh(mesh, name, colour)


def compose(writer, palette, source=None):
    if not writer.objects:
        seed_selected_materials(writer, palette)
    explicit_source = source is not None
    request = writer._build_fatcat_project_request(palette, writer._select_metadata_target())
    if explicit_source:
        request.pop("project_source", None)
        result = compose_project_settings(source, request)
    elif request.get("project_source") == "fatcat_native":
        result = compose_builtin_project_settings(request)
    else:
        source = writer._get_base_config_template()
        result = compose_project_settings(source, request)
    return json.loads(result["project_settings_json"]), request, result


@pytest.mark.parametrize("device", [d for d in DEVICES if d.nozzle_size == "0.6" and d.machine_profile_id.endswith(":bambu-lab-x1")], ids=lambda d: d.device_profile_id)
def test_registry_only_x1_effective_native_tower_defaults_reach_layout(tmp_path, device):
    writer = make_writer(tmp_path, device)
    final, _, _ = compose(writer, [("Red", (220, 20, 30)), ("White", (240, 245, 250))])
    request = writer_module._build_wipe_tower_placement_request(
        read_project_layout(final, slicer_id=writer.slicer),
        model_bounds=Rect(0, 0, 18.6, 13.2), model_height=1.2,
        material_count=2, printer_id=writer.printer_id, slicer=writer.slicer,
        nozzle_size=writer.nozzle_size,
    )
    assert request.tower_rib_width == 8.0
    assert request.tower_square_rib_body is True
    assert request.tower_infill_spacing_ratio == 1.5
    assert request.purge_volume == (45.0 if writer.slicer == "BambuStudio" else 30.0)
    assert request.tower_extra_rib_length == 0.0
    assert request.tower_brim == 3.0


@pytest.mark.parametrize("device,plate", MATRIX, ids=[f"{d.device_profile_id}/{p.id}" for d, p in MATRIX])
@pytest.mark.parametrize("names", [("Red", "White"), ("PETG Red", "PETG White"), ("Red", "PETG White")], ids=["pla", "petg", "mixed"])
def test_device_plate_material_binding_or_incomplete_native_profile_error(tmp_path, device, plate, names):
    writer = make_writer(tmp_path, device, plate=plate)
    palette = [(names[0], (220, 20, 30)), (names[1], (240, 245, 250))]
    seed_selected_materials(writer, palette)
    binding = native_plate_binding(
        slicer_id=device.slicer_id, build_plate_id=plate.id,
    )
    assert writer._select_metadata_target().build_plate_uid == binding["build_plate_uid"]
    plate_value = binding["project_value"]
    machine = device.machine_profile_id.split(":bbl:bambu-lab-")[1]
    types = ["PETG" if name.startswith("PETG") else "PLA" for name in names]
    if not native_materials_support_plate(slicer_id=device.slicer_id,
            machine_uid=f"bambu-lab:{machine}", nozzle_uid=f"nozzle:{device.nozzle_size}mm",
            material_types=types, plate_value=plate_value):
        # Unsupported plates and ambiguous presets require an explicit user choice.
        with pytest.raises(NativeMaterialSelectionError) as error:
            compose(writer, palette)
        selection = error.value.material_selection
        assert selection["ready"] is False
        assert selection["machine_uid"] == f"bambu-lab:{machine}"
        assert selection["issues"]
        assert all(issue["code"] in {
            "native_material_plate_incompatible", "native_material_ambiguous",
            "native_material_unavailable",
        } for issue in selection["issues"])
        return
    gap = native_material_profile_gap(
        slicer_id=device.slicer_id, machine_uid=f"bambu-lab:{machine}",
        nozzle_uid=f"nozzle:{device.nozzle_size}mm", material_types=types,
        plate_value=plate_value,
    )
    if gap is not None:
        profile_name, key = gap
        # Some third-party presets support this plate but lack settings needed
        # to combine them with another material. Require the exact source error.
        message = (
            f"native material profile '{profile_name}' omits slice setting '{key}' "
            "and the exact target has no recorded native schema default"
        )
        with pytest.raises(NativeMaterialSelectionError, match=re.escape(message)) as error:
            compose(writer, palette)
        assert error.value.material_selection["issues"][0]["code"] == (
            "native_material_settings_incompatible"
        )
        return
    source = writer._get_base_config_template()
    final, request, result = compose(writer, palette)
    assert_native_materials(final, slicer_id=device.slicer_id, machine_uid=f"bambu-lab:{machine}",
                            nozzle_uid=f"nozzle:{device.nozzle_size}mm",
                            material_types=["PETG" if name.startswith("PETG") else "PLA" for name in names])
    assert final["filament_colour"] == ["#DC141E", "#F0F5FA"]
    assert final["curr_bed_type"] == plate_value
    assert final["printer_settings_id"] == source["printer_settings_id"]
    assert final["print_compatible_printers"] == [source["printer_settings_id"]]
    for key in ("printer_model", "nozzle_diameter", "printable_area", "printable_height"):
        assert final[key] == source[key], key
    assert len(final["different_settings_to_system"]) == 1
    for key in ("layer_height", "initial_layer_print_height", "enable_prime_tower"):
        assert result["effective_settings"][key] == final[key]
    assert final["filament_type"] == ["PETG" if name.startswith("PETG") else "PLA" for name in names]


@pytest.mark.parametrize("device", DEVICES, ids=lambda d: d.device_profile_id)
def test_full_native_tail_preserves_declared_kind_and_untouched_process(tmp_path, device):
    material_types = ["PLA"] * 7 + ["PETG"]
    names = [f"Native slot {slot + 1}" for slot in range(8)]
    colours = [(12 + slot * 25, 60 + slot * 8, 90 + slot * 5) for slot in range(8)]
    palette = [("Selected Red", (220, 20, 30)), ("Selected White", (240, 245, 250))]
    writer = make_writer(
        tmp_path, device, policy=True,
        material_types=dict(zip(names, material_types)),
    )
    writer._set_project_palette([name for name, _ in palette], dict(palette))
    for slot, (name, colour) in enumerate(palette):
        mesh = trimesh.creation.box(extents=(6.0, 5.0, 1.2))
        mesh.apply_translation((slot * 8.0, 0.0, 0.6))
        writer.add_mesh(mesh, name, colour)
    source = complete_native_project(writer, material_types, colours=colours)
    source["outer_wall_speed"] = "47"
    source["unmanaged_vendor_array"] = ["opaque3", "opaque1"]
    source["unknown_compact_values"] = [f"opaque{slot}" for slot in range(16)]
    source["filament_retraction_length"][-1] = "0.73"
    source["different_settings_to_system"][8] = "filament_retraction_length"
    writer._custom_template = deepcopy(source)
    request = writer._build_fatcat_project_request(palette, writer._select_metadata_target())
    assert len(request["source_materials"]) == 2
    writer.export()
    with ZipFile(writer.output_path) as package:
        final = json.loads(package.read("Metadata/project_settings.config"))
    assert_source_material_snapshot(final, source, slicer=device.slicer_id, output_slots=8)
    assert len(final["filament_settings_id"]) == 8
    assert final["filament_type"][2:] == ["PLA"] * 5 + ["PETG"]
    assert final["filament_colour"] == ["#DC141E", "#F0F5FA"] + source["filament_colour"][2:]
    assert final["filament_multi_colour"][2:] == source["filament_multi_colour"][2:]
    assert final["filament_retraction_length"][-1] == "0.73"
    assert final["outer_wall_speed"] == "47"
    assert final["unmanaged_vendor_array"] == ["opaque3", "opaque1"]
    assert final["unknown_compact_values"] == source["unknown_compact_values"]
    assert "filament_retraction_length" in final["different_settings_to_system"][8].split(";")


@pytest.mark.parametrize("device", [d for d in DEVICES if d.nozzle_size == "0.4"], ids=lambda d: d.device_profile_id)
@pytest.mark.parametrize("policy,count", [(None, 2), (None, 8), (True, 2), (True, 8), (False, 2), (False, 8)])
def test_slot_policy_is_independent_of_machine_alias(tmp_path, device, policy, count):
    writer = make_writer(tmp_path, device, policy=policy)
    palette = [(f"Slot {index}", (10 + index, 20, 30)) for index in range(count)]
    final, request, _ = compose(writer, palette)
    assert request["filament_slot_mode"] == ("auto" if policy is None else "preserve" if policy else "compact")
    # Native project sources supply per-material presets; export slots match the selected palette.
    assert len(final["filament_settings_id"]) == count
    machine = device.machine_profile_id.split(":bbl:bambu-lab-")[1]
    assert_native_materials(final, slicer_id=device.slicer_id, machine_uid=f"bambu-lab:{machine}",
                            nozzle_uid=f"nozzle:{device.nozzle_size}mm",
                            material_types=["PLA"] * count)


@pytest.mark.parametrize("device", [d for d in DEVICES if d.nozzle_size == "0.4"], ids=lambda d: d.device_profile_id)
def test_real_stored_user_tuning_is_preserved_between_native_exports(tmp_path, monkeypatch, device):
    monkeypatch.setattr(custom_3mf_templates, "_root", lambda: tmp_path / "stored-templates")
    writer = make_writer(tmp_path, device)
    palette = [("Red", (220, 20, 30)), ("PETG White", (240, 245, 250))]
    writer._material_types.update({"Red": "PLA", "PETG White": "PETG"})
    native_before, _, _ = compose(writer, palette)
    tuned = deepcopy(native_before)
    variant_count = len(tuned["filament_flow_ratio"]) // 2
    tuned["nozzle_temperature_initial_layer"] = ["217"] * (2 * variant_count)
    tuned["nozzle_temperature"] = ["213"] * (2 * variant_count)
    tuned["filament_flow_ratio"] = ["0.93"] * (2 * variant_count)
    tuned["filament_retraction_length"] = ["0.61", "0.72"] * variant_count
    tuned["outer_wall_speed"] = "47"
    registrations = tuned["different_settings_to_system"]
    tuned["different_settings_to_system"] = [registrations[0], *([""] * len(tuned["filament_settings_id"])), ""]
    tuned["different_settings_to_system"][1] = "filament_retraction_length;filament_flow_ratio"
    payload = BytesIO()
    with ZipFile(payload, "w") as package:
        package.writestr("Metadata/project_settings.config", json.dumps(tuned))
        package.writestr("3D/3dmodel.model", f'<model><metadata name="Application">{device.slicer_id}-{device.source_version}</metadata></model>')
    record = custom_3mf_templates.import_template(payload.getvalue(), "Real stored tuning")
    custom = make_writer(tmp_path, device, policy=None, custom_3mf_template_id=record["id"])
    custom._material_types.update({"Red": "PLA", "PETG White": "PETG"})
    custom.add_mesh(trimesh.creation.box(extents=(6, 5, 1.2)), "Red", (220, 20, 30))
    custom.add_mesh(trimesh.creation.box(extents=(4, 3, 1.2)), "PETG White", (240, 245, 250))
    custom._set_project_palette([name for name, _ in palette], {index: colour for index, (_, colour) in enumerate(palette)})


    custom.export()
    with ZipFile(custom.output_path) as package:
        preserved = json.loads(package.read("Metadata/project_settings.config"))
    for key in ("nozzle_temperature_initial_layer", "nozzle_temperature", "filament_flow_ratio", "filament_retraction_length", "filament_settings_id", "filament_type", "outer_wall_speed", "curr_bed_type"):
        assert preserved[key] == tuned[key], key
    assert {"filament_retraction_length", "filament_flow_ratio"} <= set(preserved["different_settings_to_system"][1].split(";"))
    native_after, _, _ = compose(make_writer(tmp_path, device), palette)
    assert native_after == native_before


def test_new_machine_composer_failure_does_not_retry_legacy(tmp_path, monkeypatch):
    writer = make_writer(tmp_path, DEVICES[0])
    writer.add_mesh(trimesh.creation.box(extents=(6, 5, 1.2)), "Red", (220, 20, 30))

    def failed(*_args, **_kwargs):
        raise RuntimeError("exact new-machine binding failed")


    monkeypatch.setattr(writer_module, "compose_builtin_project_settings", failed)
    with pytest.raises(RuntimeError, match="exact new-machine binding failed"):
        writer.export()


@pytest.mark.parametrize("device", [d for d in DEVICES if d.nozzle_size == "0.6" and d.machine_profile_id.endswith(":bambu-lab-x1")], ids=lambda d: d.device_profile_id)
@pytest.mark.parametrize("policy", [None, False])
def test_registry_only_x1_native_writer_uses_exact_source_material_profile(tmp_path, monkeypatch, device, policy):
    writer = make_writer(tmp_path, device, policy=policy)
    seed_selected_materials(writer, [("Red", (220, 20, 30))])
    source = writer._get_base_config_template()
    assert len(source["filament_settings_id"]) == 1


    writer.export()
    with ZipFile(writer.output_path) as package:
        final = json.loads(package.read("Metadata/project_settings.config"))
    assert len(final["filament_settings_id"]) == 1
    assert final["filament_settings_id"] == source["filament_settings_id"]
    assert final["name"] == "project_settings" and final["from"] == "project"
    assert not {"type", "inherits", "instantiation", "setting_id"} & final.keys()
    assert final["filament_colour"][0] == "#DC141E"
    assert final["filament_colour"] == ["#DC141E"]
