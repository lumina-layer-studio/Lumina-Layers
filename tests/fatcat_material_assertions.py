"""Compare composed materials with exact installed native profile sources."""

import json
from pathlib import Path


_STRUCTURAL_KEYS = {
    "type", "instantiation", "inherits", "include", "setting_id", "name",
    "from", "compatible_printers", "compatible_prints",
    "compatible_printers_condition", "compatible_prints_condition",
    "default_print_profile", "default_filament_profile", "printer_settings_id",
    "print_settings_id", "filament_settings_id", "filament_id",
    "filament_notes", "description", "version", "filament_self_index",
    "is_custom_defined",
}


def _resolved_profile(data_root: Path, index: dict, relative_path: str) -> dict:
    ancestry: set[str] = set()

    def resolve(path: str) -> dict:
        if path in ancestry:
            raise AssertionError(f"cyclic native profile source: {path}")
        ancestry.add(path)
        profile = json.loads((data_root / path).read_text(encoding="utf-8"))
        merged: dict = {}
        edges = index["references"].get(path, {})
        inherited = profile.get("inherits")
        if inherited:
            merged.update(resolve(edges[f"inherits:{inherited}"]))
        includes = profile.get("include", [])
        if isinstance(includes, str):
            includes = [includes]
        for name in includes:
            merged.update(resolve(edges[f"include:{name}"]))
        merged.update(profile)
        ancestry.remove(path)
        return merged

    return resolve(relative_path)


def _material_family(value: str) -> str:
    text = " ".join(value.upper().replace("_", " ").split())
    for family in ("PLA", "PETG", "ABS", "ASA", "TPU", "PA", "PC"):
        if text == family or text.startswith(f"{family} "):
            return family
    return text


def _native_profile_names(
    source: dict,
    data_root: Path,
    index: dict,
    material_types: list[str],
    plate_temperature_key: str | None = None,
) -> list[str] | None:
    options = source["filament_profile_options"]
    profiles = {
        item["name"]: _resolved_profile(data_root, index, item["path"])
        for item in options
        if "path" in item and "unavailable_reason" not in item
    }
    default_names = source.get("default_filament_profile_names") or [
        source.get("default_filament_profile_name", "")
    ]
    selected = []
    for slot, requested_type in enumerate(material_types):
        family = _material_family(requested_type)
        matching = []
        for name, profile in profiles.items():
            compatible = profile.get("compatible_printers")
            if compatible and source["source_machine_profile_name"] not in compatible:
                continue
            if plate_temperature_key is not None:
                temperatures = profile.get(plate_temperature_key)
                if temperatures and all(float(value) <= 0 for value in temperatures):
                    continue
            native_type = profile.get("filament_type", [])
            if not isinstance(native_type, list):
                native_type = [native_type]
            if any(_material_family(str(value)) == family for value in native_type):
                matching.append(name)
        default_name = default_names[slot] if slot < len(default_names) else default_names[0]
        if default_name in matching:
            selected.append(default_name)
        else:
            requested = " ".join(requested_type.upper().replace("_", " ").split())
            preferred = [name for name in matching if f"{family} BASIC" in name.upper()]
            generic = [name for name in matching if name.split("@")[0].strip().upper() == f"GENERIC {family}"]
            if requested in {family, f"{family} BASIC"} and len(preferred) == 1:
                selected.append(preferred[0])
            elif requested in {family, f"{family} BASIC"} and len(generic) == 1:
                selected.append(generic[0])
            elif len(matching) == 1:
                selected.append(matching[0])
            else:
                return None
    return selected


def assert_native_materials(
    project,
    *,
    slicer_id,
    machine_uid,
    nozzle_uid,
    material_types,
    skip_material_keys=(),
):
    """Assert native profile identity and every resolved material setting.

    The expected values come from the wheel's native profile files and their
    recorded inheritance graph. The legacy translation ``material_bindings``
    API is intentionally not used here.
    """

    import fatcat_metadata

    data_root = Path(fatcat_metadata.__file__).parent / "fatcat_metadata_data" / "native_project_sources"
    index = json.loads((data_root / "source-index.json").read_text(encoding="utf-8"))
    matches = [
        source for source in index["sources"]
        if source["slicer_id"] == slicer_id
        and source["machine_uid"] == machine_uid
        and source["nozzle_uid"] == nozzle_uid
    ]
    assert len(matches) == 1, (slicer_id, machine_uid, nozzle_uid)
    source = matches[0]
    target = _native_target(slicer_id)
    plate = next(
        row for row in target["build_plate_bindings"]
        if row["project_value"] == project["curr_bed_type"]
    )
    names = _native_profile_names(
        source, data_root, index, list(material_types),
        f"{plate['sidecar_value']}_temp",
    )
    assert names is not None, "selected plate needs an explicit native material preset"
    profiles_by_name = {
        item["name"]: _resolved_profile(data_root, index, item["path"])
        for item in source["filament_profile_options"]
        if "path" in item and "unavailable_reason" not in item
    }
    profiles = [profiles_by_name[name] for name in names]

    assert project["filament_settings_id"] == names
    assert project["filament_type"] == [
        profile["filament_type"][0] if isinstance(profile["filament_type"], list)
        else profile["filament_type"]
        for profile in profiles
    ]

    snapshot = target["package_dialect"]["filament_snapshot"]
    defaults = snapshot.get("native_schema_defaults", {}).get("values", {})
    if defaults:
        assert snapshot["native_schema_defaults"].get("source"), "schema defaults need provenance"
    material_keys = {
        key
        for rule in snapshot["array_rules"]
        if rule.get("material_source_override", False)
        for key in rule["keys"]
    }
    material_keys.update(
        key for profile in profiles for key in profile
        if key.startswith("filament_")
    )
    material_keys.update(defaults)
    field_roles = {
        key: rule.get("material_source_override", False)
        for rule in snapshot["array_rules"] if not rule.get("merged_only", False)
        for key in rule["keys"]
    }
    for key in sorted(
        material_keys - _STRUCTURAL_KEYS - {"filament_colour", "filament_multi_colour"}
        - set(skip_material_keys) - set(snapshot.get("ignored_native_profile_keys", ()))
    ):
        provided = [profile.get(key) for profile in profiles]
        if all(value is None for value in provided) and key not in defaults:
            # This exclusion depends solely on the native sources: no preset
            # provides the field and this target records no schema default.
            continue
        assert key in project, f"missing native material setting: {key}"
        values = []
        for slot, profile in enumerate(profiles):
            value = profile.get(key, defaults.get(key))
            if value == []:
                value = defaults.get(key)
            assert value is not None, (
                f"native source {names[slot]!r} omits {key} without a schema default"
            )
            values.append(value)
        if field_roles.get(key, key.startswith("filament_")):
            expected = [item for value in values
                        for item in (value if isinstance(value, list) else [value])]
        else:
            # Non-material schema fields retain one global value. Native
            # presets must agree on it, including any source-backed default.
            assert all(value == values[0] for value in values), key
            expected = values[0]
        assert project[key] == expected, key
    return profiles


def _native_target(slicer_id):
    import fatcat_metadata

    target_name = {
        "BambuStudio": "bambu-studio-02.09.01.70.json",
        "OrcaSlicer": "orca-slicer-2.4.2.json",
    }[slicer_id]
    path = Path(fatcat_metadata.__file__).parent / "fatcat_metadata_data" / "translations/targets" / target_name
    return json.loads(path.read_text(encoding="utf-8"))


def native_plate_binding(*, slicer_id, build_plate_id):
    """Check the picker ID contract independently of the writer's selected UID."""
    expected_uid = {
        "cool-plate": "plate:cool",
        "smooth-cool-plate": "plate:cool",
        "engineering-plate": "plate:engineering",
        "smooth-pei-plate": "plate:smooth-pei",
        "smooth-high-temp-plate": "plate:smooth-pei",
        "textured-pei-plate": "plate:textured-pei",
        "textured-cool-plate": "plate:textured-cool",
        "supertack-plate": "plate:supertack",
    }[build_plate_id]
    return next(
        row for row in _native_target(slicer_id)["build_plate_bindings"]
        if row["build_plate_uid"] == expected_uid
    )


def native_materials_support_plate(*, slicer_id, machine_uid, nozzle_uid, material_types, plate_value):
    """Check the selected native presets, rather than any preset in their family."""
    import fatcat_metadata

    package_root = Path(fatcat_metadata.__file__).parent / "fatcat_metadata_data"
    data_root = package_root / "native_project_sources"
    index = json.loads((data_root / "source-index.json").read_text(encoding="utf-8"))
    source = next(row for row in index["sources"] if row["slicer_id"] == slicer_id
                  and row["machine_uid"] == machine_uid and row["nozzle_uid"] == nozzle_uid)
    target = _native_target(slicer_id)
    binding = next(row for row in target["build_plate_bindings"] if row["project_value"] == plate_value)
    key = binding["sidecar_value"] + "_temp"
    return _native_profile_names(
        source, data_root, index, list(material_types), key,
    ) is not None


def native_material_profile_gap(
    *, slicer_id: str, machine_uid: str, nozzle_uid: str,
    material_types: list[str], plate_value: str,
) -> tuple[str, str] | None:
    """Find a source field that cannot be completed from recorded native data.

    找出原生预设中缺失且没有已记录默认值可补齐的字段。
    """
    import fatcat_metadata

    data_root = Path(fatcat_metadata.__file__).parent / "fatcat_metadata_data" / "native_project_sources"
    index = json.loads((data_root / "source-index.json").read_text(encoding="utf-8"))
    source = next(row for row in index["sources"] if row["slicer_id"] == slicer_id
                  and row["machine_uid"] == machine_uid and row["nozzle_uid"] == nozzle_uid)
    target = _native_target(slicer_id)
    binding = next(row for row in target["build_plate_bindings"] if row["project_value"] == plate_value)
    names = _native_profile_names(
        source, data_root, index, list(material_types), binding["sidecar_value"] + "_temp",
    )
    assert names is not None, "check material/plate availability first"
    paths = {row["name"]: row["path"] for row in source["filament_profile_options"] if "path" in row}
    profiles = [_resolved_profile(data_root, index, paths[name]) for name in names]
    snapshot = target["package_dialect"]["filament_snapshot"]
    defaults = snapshot.get("native_schema_defaults", {}).get("values", {})
    keys = set().union(*(set(profile) for profile in profiles))
    keys -= _STRUCTURAL_KEYS | set(snapshot.get("ignored_native_profile_keys", ())) | set(defaults)
    for key in sorted(keys):
        for name, profile in zip(names, profiles):
            if key not in profile:
                return name, key
    return None
