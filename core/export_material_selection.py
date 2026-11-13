"""Transfer source material facts to FatCat's native selection policy.

将来源材料事实交给 FatCat，并把选择结果绑定到 Lumina 设备界面身份。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from config import ColorSystem
from core.errors import NativeMaterialSelectionError
from core.export_materials import resolve_coating_material
from core.machine_registry import load_machine_registry, resolve_machine_registry_root
from core.material_lut_provider import load_materials
from core.material_lut_synthesis import build_material_preview_colors, build_material_slot_names
from core.recipe_virtual_materials import build_virtual_material_registry
from core.pipeline.preview_color_utils import build_lut_material_types, build_palette_preview_colors
from utils.fatcat_metadata import (
    build_builtin_project_settings_request,
    external_spool_filament_map,
    native_build_plate_uid,
    MetadataTarget,
    native_source_for_target,
    resolve_project_materials,
    select_metadata_target,
    select_user_template_metadata_target,
)
from utils.lut_manager import LUTManager


def present_material_selection(
    selection: Mapping[str, Any], *, device_profile_id: str | None = None,
    target: MetadataTarget | None = None,
) -> dict[str, Any]:
    """Bind SDK identities to the existing device and plate settings.

    为 SDK 结果附加现有设备与打印板界面标识，保留全部原生身份和规则。
    """
    result = dict(selection)
    registry = load_machine_registry(resolve_machine_registry_root() / "registry.json")
    source = native_source_for_target(target or MetadataTarget(
        slicer_id=str(selection["slicer_id"]),
        application_version=select_user_template_metadata_target(
            slicer=str(selection["slicer_id"]), build_plate_id=None,
        ).application_version,
        machine_uid=str(selection["machine_uid"]),
        nozzle_uid=str(selection["nozzle_uid"]),
        build_plate_uid=str(selection["build_plate_uid"]),
    ))
    profiles = [profile for profile in registry.devices_by_id.values()
                if profile.slicer_id == selection["slicer_id"]
                and profile.source_profile_name == source["source_machine_profile_name"]
                and f"nozzle:{profile.nozzle_size}mm" == selection["nozzle_uid"]]
    profile = next((item for item in profiles if item.device_profile_id == device_profile_id), None)
    if profile is None:
        if not profiles:
            raise ValueError("No Lumina device identity for the selected native material target")
        profile = profiles[0]
    result["device_profile_id"] = profile.device_profile_id
    result["machine_profile_id"] = profile.machine_profile_id
    native_plates = {plate["build_plate_uid"]: plate for plate in selection["build_plates"]}
    result["build_plates"] = [
        {**native_plates[uid], "id": plate.id, "name": plate.display_name}
        for plate in profile.build_plates
        if (uid := native_build_plate_uid(plate.id)) in native_plates
    ]
    return result


def _source_materials(
    params: Mapping[str, Any], source_context: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    source = source_context if source_context is not None else params
    is_material_archive = source.get("material_source") == "material_archive"
    if is_material_archive:
        root = source.get("materials_dir") or source.get("project_materials_dir")
        materials = load_materials(list(source.get("selected_materials") or []), **({"materials_dir": root} if root else {}))
        names = build_material_slot_names(materials)
        colours = build_material_preview_colors(materials)
        types = {name: material.material_type for name, material in zip(names, materials)}
    else:
        metadata = source.get("lut_metadata")
        if metadata is None:
            path = source.get("lut_path")
            owns_path = False
            if not path:
                path, _ = LUTManager.resolve_source_selection(
                    source_kind=str(params.get("source_kind") or "legacy_single"),
                    lut_name=params.get("lut_name"), lut_names=params.get("lut_names"),
                    material_type=params.get("material_type"), vendor=params.get("vendor"),
                    db_names=params.get("db_names"),
                )
                owns_path = params.get("source_kind") in {"legacy_multi", "native_bundle"}
            try:
                _, _, metadata = LUTManager.load_lut_with_metadata(path)
            finally:
                if owns_path:
                    from config import TEMP_DIR

                    owned = Path(path).resolve()
                    if owned.parent == Path(TEMP_DIR).resolve():
                        owned.unlink(missing_ok=True)
        colour_config = ColorSystem.get(str(params.get("color_mode") or "4-Color (RYBW)"))
        palette = getattr(metadata, "palette", None) or []
        if palette:
            names, colours = build_palette_preview_colors(palette, colour_config)
        else:
            names = list(colour_config["slots"])
            colours = colour_config["preview"]
    # Use a complete or expanded canonical palette from the preview, while
    # retaining the full source palette for older caches of used slots only.
    cached_names = source.get("slot_names") if source_context is not None else None
    if isinstance(cached_names, (list, tuple)) and cached_names and len(cached_names) >= len(names):
        names = list(cached_names)
        cached_colours = source.get("preview_colors")
        if isinstance(cached_colours, Mapping):
            colours = dict(cached_colours)
        if not is_material_archive:
            # Use the same explicit metadata (or its absence) as generation,
            # rather than a reloaded LUT's inferred, potentially smaller palette.
            metadata = source.get("lut_metadata", metadata)
    if not is_material_archive:
        types = build_lut_material_types(metadata, names)
    choices = params.get("native_filament_profiles") or {}
    coating = resolve_coating_material(
        params.get("coating_material"), slot_names=names,
        preview_colors=colours, material_types=types,
    ) if params.get("enable_coating") else None
    if coating and coating.name not in names:
        names = [*names, coating.name]
        colours = {**colours, coating.name: [*coating.rgb, 255]}
        types = {**types, coating.name: coating.material_type}
    records = []
    for index, name in enumerate(names):
        rgb = colours.get(name, colours.get(index, colours.get(str(index), (128, 128, 128))))
        record: dict[str, Any] = {
            "name": name, "colour": "#{:02X}{:02X}{:02X}".format(*rgb[:3]),
            "material_type": types.get(name),
        }
        if choice := choices.get(name):
            record["native_filament_profile_name"] = choice
        records.append(record)
    virtuals, _ = build_virtual_material_registry(
        (source.get("recipe_overrides") or [] if source_context is not None
         else params.get("recipe_overrides") or []), len(records),
    )
    seen = {(record["name"].lower(), record["colour"].lower()) for record in records}
    for material in virtuals:
        key = (material["name"].lower(), material["hex"].lower())
        if key in seen:
            continue
        seen.add(key)
        record = {"name": material["name"], "colour": material["hex"]}
        if choice := choices.get(material["name"]):
            record["native_filament_profile_name"] = choice
        records.append(record)
    return records


def resolve_export_material_selection(
    params: Mapping[str, Any], *, source_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Preflight native material choices without changing any process settings.

    在生成前预检原生材料选择，保留工艺参数；导入调校模板继续采用自身设置。
    """
    if params.get("custom_3mf_template_id"):
        from core.custom_3mf_templates import load_template, require_template_slot_capacity

        template = load_template(str(params["custom_3mf_template_id"]))
        target = select_user_template_metadata_target(
            slicer=str(params.get("slicer") or template["_lumina_template_slicer"]),
            build_plate_id=params.get("build_plate_id"),
        )
        require_template_slot_capacity(
            template, len(_source_materials(params, source_context)), target=target,
        )
        return {"ready": True, "materials": [], "issues": [], "build_plates": [],
                "slicer_id": str(params.get("slicer") or ""), "machine_uid": "",
                "nozzle_uid": "", "build_plate_uid": "",
                "device_profile_id": str(params.get("device_profile_id") or ""),
                "machine_profile_id": ""}
    target = select_metadata_target(
        slicer=str(params.get("slicer") or "BambuStudio"),
        printer_id=str(params.get("printer_id") or "bambu-h2d"),
        nozzle_size=params.get("nozzle_size") or "0.4",
        device_profile_id=params.get("device_profile_id"),
        build_plate_id=params.get("build_plate_id"),
    )
    request = build_builtin_project_settings_request({}, _source_materials(params, source_context),
                                                      target=target)
    return present_material_selection(resolve_project_materials(request),
                                      device_profile_id=params.get("device_profile_id"), target=target)


def require_export_material_selection(
    params: Mapping[str, Any], *, source_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reject unresolved choices before geometry generation.

    在计算几何之前拒绝尚未解决的耗材预设或板型选择。
    """
    selection = resolve_export_material_selection(params, source_context=source_context)
    if (material := params.get("external_spool_material")) is not None:
        external_spool_filament_map(
            material, [slot["name"] for slot in selection["materials"]],
            slicer_id=selection["slicer_id"], machine_uid=selection["machine_uid"],
        )
    if not selection["ready"]:
        raise NativeMaterialSelectionError(selection)
    return selection
