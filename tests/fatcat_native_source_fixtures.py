"""Build complete custom-source fixtures from Fat Cat's installed native data."""

import json
from pathlib import Path


def complete_native_project(writer, material_types, colours=None, *, material_plate_uid=None):
    """Compose a full native slot set and give it the imported-3MF list shape.

    The native source API emits one global difference-registration string.
    Imported Bambu/Orca 3MFs use a global entry, one entry per filament slot,
    and one trailing machine entry; that layout is grounded in the checked-in
    native-saved 3MF fixtures.
    """

    from utils.fatcat_metadata import (
        build_builtin_project_settings_request,
        compose_builtin_project_settings,
    )

    target = writer._select_metadata_target()
    materials = [
        {
            "name": f"Native slot {index + 1}",
            "colour": (
                f"#{colours[index][0]:02X}{colours[index][1]:02X}{colours[index][2]:02X}"
                if colours is not None else f"#{index + 1:02X}4050"
            ),
            "material_type": material_type,
        }
        for index, material_type in enumerate(material_types)
    ]
    request = build_builtin_project_settings_request(
        {}, materials, target=target, filament_slot_mode="preserve",
    )
    if material_plate_uid is not None:
        request["build_plate_uid"] = material_plate_uid
    composed = compose_builtin_project_settings(request)
    project = json.loads(composed["project_settings_json"])
    slot_count = len(project["filament_settings_id"])
    if slot_count != len(material_types):
        raise AssertionError(
            f"native source returned {slot_count} slots for {len(material_types)} materials"
        )
    registrations = project["different_settings_to_system"]
    if len(registrations) != 1:
        raise AssertionError("built-in source must have one global difference entry")
    project["different_settings_to_system"] = [
        registrations[0], *([""] * slot_count), "",
    ]
    return project


def assert_source_material_snapshot(final, source, *, slicer, output_slots):
    """Compare custom-source material fields using their declared slot roles."""
    import fatcat_metadata

    target_name = {
        "BambuStudio": "bambu-studio-02.09.01.70.json",
        "OrcaSlicer": "orca-slicer-2.4.2.json",
    }[slicer]
    target = json.loads((Path(fatcat_metadata.__file__).parent / "fatcat_metadata_data"
                         / "translations" / "targets" / target_name).read_text(encoding="utf-8"))
    rules = target["package_dialect"]["filament_snapshot"]["array_rules"]
    material_keys = {key for rule in rules
                     if rule.get("material_source_override") or rule.get("selection") == "slot_index"
                     for key in rule["keys"]}
    material_keys.update(key for key in source if key.startswith("filament_"))
    source_slots = len(source["filament_settings_id"])
    for key in material_keys - {"filament_colour", "filament_multi_colour"}:
        if key not in source:
            continue
        value = source[key]
        expected = value
        if isinstance(value, list) and len(value) % source_slots == 0:
            expected = value[:output_slots * (len(value) // source_slots)]
        assert key in final, key
        assert final[key] == expected, key
