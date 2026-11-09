"""Real configuration provenance selects native defaults or user tuning."""

from io import BytesIO
import json
from zipfile import ZipFile

import pytest
import trimesh

from core.errors import NativeMaterialSelectionError
from utils.bambu_3mf_writer import BambuStudio3MFWriter
from utils.fatcat_metadata import (
    build_project_settings_request,
    compose_builtin_project_settings,
    compose_project_settings,
)


def _writer(tmp_path, *, policy=False, **kwargs):
    writer = BambuStudio3MFWriter(
        str(tmp_path / "policy.3mf"), printer_id="bambu-p1s",
        slicer="BambuStudio", nozzle_size="0.2",
        device_profile_id="BambuStudio:bbl:bambu-lab-p1s:0.2",
        build_plate_id="textured-pei-plate",
        preserve_template_filament_slots=policy,
        enable_wipe_tower_auto_placement=False, **kwargs,
    )
    writer.add_mesh(trimesh.creation.box(extents=(4, 4, 1.2)), "White", (240, 240, 240))
    return writer


def _compose(source, request):
    if request.get("project_source") == "fatcat_native":
        return compose_builtin_project_settings(request)
    return compose_project_settings(source, request)


def _request(writer, palette):
    source = writer._get_base_config_template()
    target = writer._select_metadata_target()
    assert target is not None
    return source, writer._build_fatcat_project_request(palette, target)


@pytest.mark.parametrize("policy", [False, True])
def test_builtin_selects_native_material_for_every_output_slot(tmp_path, policy):
    writer = _writer(tmp_path, policy=policy)
    source, request = _request(writer, [("White", (240, 240, 240)), ("PETG Black", (10, 10, 10))])
    assert source["filament_type"] == ["PLA"]
    assert request["project_source"] == "fatcat_native"
    assert "preserve_source_material_settings" not in request
    final = json.loads(_compose(source, request)["project_settings_json"])
    assert final["filament_type"] == ["PLA", "PETG"]
    assert "filament_source_slots" not in request
    # Compactness alone is not a user request to disable native retraction.
    assert not request.get("disable_cut_retraction", False)


def test_full_slot_native_tail_keeps_its_declared_material_kind(tmp_path):
    writer = _writer(tmp_path, policy=True)
    slot_names = [f"Slot {index + 1}" for index in range(8)]
    writer._set_project_palette(
        slot_names,
        {name: (20 + index, 40, 60) for index, name in enumerate(slot_names)},
    )
    source = writer._get_base_config_template()
    assert len(source["filament_type"]) == 9
    source["filament_type"][-1] = "PETG"
    source["filament_settings_id"][-1] = source["filament_settings_id"][0]
    target = writer._select_metadata_target()
    request = writer._build_fatcat_project_request([("Red", (200, 20, 30))], target)
    request.pop("project_source", None)
    final = json.loads(_compose(source, request)["project_settings_json"])
    assert final["filament_type"] == ["PLA"] * 8 + ["PETG"]


@pytest.mark.parametrize(
    ("name", "profile_name", "error_pattern"),
    [
        (
            "PETG HF Red", "Bambu PETG HF @BBL X1C 0.2 nozzle",
            "matches multiple native profiles",
        ),
        ("PETG-CF Black", None, "no available native filament profile"),
        ("PETG Translucent", "Bambu PETG Translucent @BBL X1C 0.2 nozzle", None),
    ],
)
def test_special_petg_is_not_silently_relabelled_as_basic(
    tmp_path, name, profile_name, error_pattern,
):
    writer = _writer(tmp_path)
    source, request = _request(writer, [(name, (10, 10, 10))])
    if error_pattern is not None:
        with pytest.raises(NativeMaterialSelectionError, match=error_pattern) as error:
            _compose(source, request)
        assert error.value.material_selection["ready"] is False
        assert error.value.material_selection["issues"][0]["code"] == (
            "native_material_ambiguous" if profile_name else "native_material_unavailable"
        )
        if profile_name is None:
            return
        request["native_filament_profile_names"] = [profile_name]
    final = json.loads(_compose(source, request)["project_settings_json"])
    assert final["filament_settings_id"] == [profile_name]
    assert final["filament_type"] == ["PETG"]


def test_adapter_passes_selections_not_native_parameter_arrays(tmp_path):
    writer = _writer(tmp_path)
    source = writer._get_base_config_template()
    target = writer._select_metadata_target()
    request = build_project_settings_request(
        writer.settings, ["#FFFFFF", "#000000"], target=target,
        material_mode="target_native_preset", material_uids=["material:pla", "material:petg"],
        filament_slot_mode="compact", default_filament_source_slot=0,
    )
    assert request["material_uids"] == ["material:pla", "material:petg"]
    for key in ("nozzle_temperature", "filament_flow_ratio", "filament_retraction_length", "filament_settings_id"):
        assert key not in request


@pytest.fixture
def imported_template(tmp_path, monkeypatch):
    from core import custom_3mf_templates

    monkeypatch.setattr(custom_3mf_templates, "_root", lambda: tmp_path / "user-templates")
    source = _writer(tmp_path)._get_base_config_template()
    count = len(source["filament_type"])
    source["nozzle_temperature"] = ["217", "213"] * count
    source["filament_flow_ratio"] = ["0.93", "0.94"] * count
    source["filament_retraction_length"] = ["0.61", "0.72"] * count
    source["outer_wall_speed"] = "47"
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("Metadata/project_settings.config", json.dumps(source))
        archive.writestr("3D/3dmodel.model", '<model><metadata name="Application">BambuStudio-02.08.02.61</metadata></model>')
    record = custom_3mf_templates.import_template(buffer.getvalue(), "Tuned material")
    return record["id"], source


@pytest.mark.parametrize("policy", [None, False])
def test_successfully_loaded_user_template_enters_preserve_mode(tmp_path, imported_template, policy):
    template_id, original = imported_template
    writer = _writer(tmp_path, policy=policy, custom_3mf_template_id=template_id)
    source, request = _request(writer, [("White", (240, 240, 240))])
    assert source["nozzle_temperature"] == original["nozzle_temperature"]
    assert request["material_mode"] == "preserve_template"
    assert request["preserve_source_material_settings"] is True
    assert "material_uid" not in request and "material_uids" not in request
    assert not request.get("disable_cut_retraction", False)
    assert request["filament_slot_mode"] == ("compact" if policy is False else "auto")
    if policy is False:
        final = json.loads(_compose(source, request)["project_settings_json"])
        assert len(final["filament_settings_id"]) == len(request["source_materials"])
        assert final["filament_settings_id"][:len(original["filament_settings_id"])] == original[
            "filament_settings_id"
        ]


def test_failed_user_template_load_cannot_become_builtin(tmp_path):
    with pytest.raises(FileNotFoundError):
        _writer(tmp_path, custom_3mf_template_id="0123456789abcdef0123456789abcdef")


def test_mismatched_user_template_cannot_become_builtin(tmp_path, imported_template):
    template_id, _ = imported_template
    with pytest.raises(ValueError, match="nozzle"):
        BambuStudio3MFWriter(
            str(tmp_path / "wrong.3mf"), printer_id="bambu-p1s", slicer="BambuStudio",
            nozzle_size="0.4", device_profile_id="BambuStudio:bbl:bambu-lab-p1s:0.4",
            custom_3mf_template_id=template_id,
        )


def test_orca_user_template_keeps_precision_while_builtin_uses_exact_native_process(tmp_path, monkeypatch):
    from core import custom_3mf_templates

    monkeypatch.setattr(custom_3mf_templates, "_root", lambda: tmp_path / "user-templates")
    options = dict(
        printer_id="bambu-p1s", slicer="OrcaSlicer", nozzle_size="0.6",
        device_profile_id="OrcaSlicer:bbl:bambu-lab-p1s:0.6",
        build_plate_id="textured-pei-plate", enable_wipe_tower_auto_placement=False,
    )
    builtin = BambuStudio3MFWriter(str(tmp_path / "builtin.3mf"), **options)
    builtin.add_mesh(trimesh.creation.box(extents=(4, 4, 1.2)), "Red", (200, 20, 30))
    source, native_request = _request(builtin, [("Red", (200, 20, 30))])
    native = json.loads(_compose(source, native_request)["project_settings_json"])
    assert native["precise_outer_wall"] == "0"
    assert "precise_outer_wall" in native["different_settings_to_system"][0].split(";")
    source["precise_outer_wall"] = "1"
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("Metadata/project_settings.config", json.dumps(source))
        archive.writestr("3D/3dmodel.model", '<model><metadata name="Application">OrcaSlicer-2.4.2</metadata></model>')
    record = custom_3mf_templates.import_template(buffer.getvalue(), "User precision")
    custom = BambuStudio3MFWriter(
        str(tmp_path / "custom.3mf"), **options, custom_3mf_template_id=record["id"],
    )
    loaded, request = _request(custom, [("Red", (200, 20, 30))])
    assert loaded["precise_outer_wall"] == "1"
    assert "precise_outer_wall" not in request["process_settings"]
    final = json.loads(_compose(loaded, request)["project_settings_json"])
    assert final["precise_outer_wall"] == "1"
