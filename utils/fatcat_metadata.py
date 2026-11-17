"""Shared Lumina-to-FatCat metadata adapter.

Lumina owns geometry, thumbnails, and layer modifiers; Fat Cat composes the
selected target's project and package metadata.
"""

from __future__ import annotations

from functools import lru_cache
from dataclasses import dataclass
import importlib
import json
import math
import os
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, NotRequired, Protocol, Sequence, TypedDict, cast

import numpy as np

if TYPE_CHECKING:
    import trimesh


class MeshMetadataEntry(Protocol):
    """The geometry facts consumed by the model request builder.

    模型请求构建器消费的几何事实；不依赖具体 writer 的私有条目类。
    """

    @property
    def mesh(self) -> trimesh.Trimesh:
        """Geometry with readable bounds. / 可读取边界的几何。"""
        ...

    @property
    def object_name(self) -> str:
        """Stable exported object name. / 稳定的导出对象名。"""
        ...


class ProjectLayout(TypedDict):
    """Layout facts and native tower styles returned by FatCat's reader.

    FatCat 返回的布局事实和原生塔形状，不包含原生配置的任意扩展字段。
    """

    printable_area: list[list[float]]
    bed_exclusions: list[list[list[float]]]
    extruder_printable_areas: list[list[list[float]]]
    nozzle_diameters: list[float]
    layer_height: float
    initial_layer_height: float | None
    min_layer_height: float | None
    max_layer_height: float | None
    model_brim: float
    purge_volume: float
    tower_x: float
    tower_y: float
    tower_width: float
    tower_rotation: float
    tower_brim_auto: bool
    tower_brim_width: float
    tower_infill_spacing_ratio: float
    uses_rib_wall: bool
    tower_rib_width: float
    nozzle_change_volume: NotRequired[float]
    tower_extra_rib_length: float
    extruder_count: int
    filament_change_volume: float
    printer_settings_id: str
    bed_type: str | None
    tower_cyclic_toolchanges: NotRequired[bool]
    tower_square_rib_body: NotRequired[bool | None]
    tower_wall_types: NotRequired[list[str]]
    tower_preview_x_guard_enabled: NotRequired[bool]
    tower_preview_x_guard_margin: NotRequired[float]


class MetadataDefaults(TypedDict):
    """FatCat's fixed decisions used by the geometry writer.

    几何写入器使用的 FatCat 固定策略字段。
    """

    identify_id: int | str
    plate_value: str
    sidecar_bed_value: str
    plate_summary: bool
    geometry_layout: NotRequired[str]
    slice_uuid_seed_prefix: NotRequired[str]


class SourceSlotProjection(TypedDict):
    """Source-to-output slot indexes. / 来源到输出的槽位索引。"""

    source_slot_index: int
    output_slot_index: int


class SourceSlotMapping(TypedDict):
    """The slot projection for one source. / 一份来源的槽位投影。"""

    source_id: str
    slots: list[SourceSlotProjection]


class MergedSlotDescription(TypedDict):
    """Logical material identity in a merge. / 合并中的逻辑材料身份。"""

    slot_id: int
    slot_name: str
    preview_color: str
    material_id: str


class ProjectComposition(TypedDict):
    """Fixed composer envelope around an opaque native project.

    原生项目保持开放字典；合成结果外层的固定字段提供类型约束。
    """

    project_settings_json: str
    effective_settings: dict[str, Any]
    metadata_defaults: MetadataDefaults
    wipe_tower_dialect: dict[str, Any]
    build_item_properties: dict[str, str]
    source_slot_mappings: NotRequired[list[SourceSlotMapping]]
    merged_slots: NotRequired[list[MergedSlotDescription]]


class PlateSummaryObject(TypedDict):
    """One final object footprint. / 一个最终对象的平面边界。"""

    model_index: int
    name: str
    bbox: list[float]


class PlateSummaryInput(TypedDict):
    """Caller-owned geometry for a native plate summary. / 原生盘面摘要的几何输入。"""

    bbox_all: list[float]
    filament_colors: list[str]
    layer_height: float
    nozzle_diameter: float
    bed_type: str
    name: NotRequired[str]
    objects: NotRequired[list[PlateSummaryObject]]


class ComponentInputs(TypedDict, total=False):
    """Optional Lumina geometry sidecars. / 可选的 Lumina 几何附属描述。"""

    wipe_tower_placement: dict[str, Any]
    plate_summary: PlateSummaryInput
    layer_config_ranges: dict[str, Any]


class MergedPartReference(TypedDict):
    """Paired source and output mesh IDs. / 成对的来源及输出网格 ID。"""

    part_id: int
    source_part_id: int


class ModelPartInput(TypedDict):
    """Geometry and material identity for one queued mesh. / 一个入队网格的几何与材料身份。"""

    part_id: int
    name: str
    material_index: int
    source_object_id: int
    source_volume_id: int
    matrix: str
    source_offset_x: str
    source_offset_y: str
    source_offset_z: str


class ModelPlateInput(TypedDict):
    """One selected plate and its optional display fields. / 所选打印板及可选显示字段。"""

    bed_type: str
    plater_id: NotRequired[str]
    plater_name: NotRequired[str]
    locked: NotRequired[bool]
    filament_maps: NotRequired[list[int]]


class MergedModelInput(TypedDict):
    """One source assembly's metadata handoff after geometry is queued.

    几何入队后，一份来源装配传给元数据合成器的固定字段。
    """

    model_index: int
    assembly_id: int
    instance_id: str
    identify_id: str
    source_assembly_id: int
    source_model_index: int
    source_model_settings_xml: str
    face_count: int
    parts: list[MergedPartReference]
    source_slot_output_indexes: list[int]
    output_slot_count: int
    default_slot_output_index: int
    source_slots: list[MergedSlotDescription]
    source_root_metadata: dict[str, str]
    transform: list[float]
    offset_mm: list[float]
    source_layer_config_ranges_xml: NotRequired[str]


class ModelMetadataRequest(TypedDict):
    """Fixed model request fields shared by single and merged composition.

    单件与合并模型合成请求共用的固定字段。
    """

    slicer_id: str
    application_version: str
    plate: ModelPlateInput
    assembly_id: NotRequired[int]
    instance_id: NotRequired[str]
    identify_id: NotRequired[int | str]
    source_file: NotRequired[str]
    parts: NotRequired[list[ModelPartInput]]
    objects: NotRequired[list[MergedModelInput]]
    active_material_count: NotRequired[int]
    slice_uuid: NotRequired[str]
    component_inputs: NotRequired[ComponentInputs]
    resource_roles: NotRequired[list[str]]
    source_slice_info_xml: NotRequired[str]
    output_options: NotRequired[dict[str, bool]]


class ComposedBuildItem(TypedDict):
    """FatCat's final build transform and properties. / FatCat 的最终构建变换及属性。"""

    model_index: int
    transform: str
    properties: dict[str, str]


class ModelComposition(TypedDict):
    """Composer output; vendor parts remain owned by the SDK adapter.

    合成结果；厂商部件的具体结构继续归 SDK 适配器所有。
    """

    root_model: dict[str, Any]
    parts: list[dict[str, Any]]
    content_types: list[dict[str, str]]
    relationships: list[dict[str, str]]
    build_items: NotRequired[list[ComposedBuildItem]]


@dataclass(frozen=True)
class MetadataTarget:
    """An explicit output target shared by both composers.

    两个合成入口共用的明确输出目标。
    """

    slicer_id: str
    application_version: str
    machine_uid: str
    nozzle_uid: str
    build_plate_uid: str


@dataclass(frozen=True)
class SourceMaterialTarget:
    """Slicer identity needed to read source material slots.

    读取源耗材槽所需的切片软件身份。
    """

    slicer_id: str
    application_version: str


_PLATE_UIDS = {
    "cool-plate": "plate:cool",
    "smooth-cool-plate": "plate:cool",
    "engineering-plate": "plate:engineering",
    "smooth-pei-plate": "plate:smooth-pei",
    "smooth-high-temp-plate": "plate:smooth-pei",
    "textured-pei-plate": "plate:textured-pei",
    "textured-cool-plate": "plate:textured-cool",
    "supertack-plate": "plate:supertack",
}


def external_spool_filament_map(
    material: str, slot_names: Sequence[str], *, slicer_id: str, machine_uid: str,
    source_slot_indices: Mapping[str, int] | None = None,
) -> list[int]:
    """Assign X2D heads by exact exported material name and final slot order.

    独立背板会裁剪槽位，已在全局调色板确认的外置材料可以不出现在该盘。
    """
    from core.errors import ExternalSpoolSelectionError

    if (slicer_id, machine_uid) != ("BambuStudio", "bambu-lab:x2d"):
        raise ExternalSpoolSelectionError("External spool selection requires the built-in Bambu Studio X2D profile.")
    matches = slot_names.count(material)
    if matches > 1:
        raise ExternalSpoolSelectionError(f"External spool material {material!r} matches multiple exported slots.")
    if not matches and material not in (source_slot_indices or {}):
        raise ExternalSpoolSelectionError(f"External spool material {material!r} is missing from the exported palette.")
    return [2 if name == material else 1 for name in slot_names]


def native_build_plate_uid(build_plate_id: str) -> str:
    """Return the SDK identity for an existing Lumina plate choice.

    将已有 Lumina 打印板标识转换为 SDK 身份，不改变所选板型。
    """
    return build_plate_id if build_plate_id.startswith("prusa-sheet:") else _PLATE_UIDS.get(build_plate_id, "")

def select_user_template_metadata_target(
    *,
    slicer: str,
    build_plate_id: str | None,
) -> MetadataTarget:
    """Resolve slicer identity for a saved project with its own settings.

    为自带切片设置的用户项目解析软件版本身份。
    """

    from config import normalize_slicer_software_id

    slicer_id = normalize_slicer_software_id(slicer)
    identity = _metadata_target_identity(slicer_id)
    return MetadataTarget(
        slicer_id=slicer_id,
        application_version=str(identity["application_version"]),
        machine_uid="",
        nozzle_uid="",
        build_plate_uid=native_build_plate_uid(build_plate_id or ""),
    )


@lru_cache(maxsize=None)
def native_project_source_catalog(slicer_id: str) -> dict[str, Any]:
    """Read Fat Cat's public machine identity catalog for one target.

    从 Fat Cat 公共目录读取一个目标软件的原生机器身份。
    """

    target_slicer_id = _canonical_slicer_id(slicer_id)
    raw = _load_fatcat().native_project_source_catalog(target_slicer_id)
    catalog = _parse_native_json(raw)
    if catalog.get("slicer_id") != target_slicer_id:
        raise RuntimeError("Fat Cat source catalog returned a different slicer identity")
    return catalog


@lru_cache(maxsize=None)
def process_setting_aliases(slicer_id: str) -> dict[str, str]:
    """Read input aliases from FatCat's public process contract.

    从 FatCat 公共工艺合同读取输入别名，本体不复制切片器映射表。

    Args:
        slicer_id: Selected slicer identity. 所选切片软件身份。

    Returns:
        Input names mapped to the target's native process field names.
        输入名称到目标原生工艺字段名称的映射。
    """
    slicer_id = _canonical_slicer_id(slicer_id)
    version = _metadata_target_identity(slicer_id)["application_version"]
    fields = _load_fatcat().list_native_fields(slicer_id, version)
    return fields["process_settings_contract"]["aliases"]


def native_source_for_target(target: MetadataTarget) -> dict[str, Any]:
    """Return one exact public source record for a stable Fat Cat target.

    按 Fat Cat 稳定身份返回唯一来源记录，不读取安装包内部目录。
    """

    return _load_fatcat().native_project_source({
        "slicer_id": target.slicer_id,
        "application_version": target.application_version,
        "machine_uid": target.machine_uid,
        "nozzle_uid": target.nozzle_uid,
    })


def select_metadata_target(
    *,
    slicer: str,
    printer_id: str,
    nozzle_size: object,
    device_profile_id: str | None,
    build_plate_id: str | None,
) -> MetadataTarget:
    """Resolve a Lumina registry selection to Fat Cat's stable identity.

    将 Lumina 已选设备映射到 Fat Cat 稳定身份；只按注册表来源名和喷嘴精确匹配。
    """

    from config import (
        format_native_nozzle_size,
        get_printer_profile,
        normalize_slicer_software_id,
    )
    from core.machine_registry import (
        MachineRegistrySelectionError,
        load_machine_registry,
        resolve_machine_registry_root,
        validate_device_profile_selection,
    )

    target_slicer_id = _canonical_slicer_id(normalize_slicer_software_id(slicer))
    nozzle = format_native_nozzle_size(nozzle_size)
    if nozzle is None:
        raise ValueError(f"Unsupported native nozzle selection: {nozzle_size!r}")

    registry_path = resolve_machine_registry_root() / "registry.json"
    if not registry_path.is_file():
        raise FileNotFoundError(f"Machine registry not found: {registry_path}")
    registry = load_machine_registry(registry_path)
    profile = None
    if device_profile_id:
        try:
            profile, _ = validate_device_profile_selection(
                registry,
                device_profile_id=device_profile_id,
                printer_id=printer_id,
                slicer=target_slicer_id,
                nozzle_size=nozzle,
                build_plate_id=build_plate_id,
            )
        except MachineRegistrySelectionError as exc:
            raise ValueError(str(exc)) from exc
    else:
        configured = get_printer_profile(printer_id)
        matches = [
            item for item in registry.devices_by_id.values()
            if item.supported
            and item.slicer_id == target_slicer_id
            and item.nozzle_size == nozzle
            and item.display_name.casefold() == configured.display_name.casefold()
            and item.brand.casefold() == configured.brand.casefold()
        ]
        if len(matches) != 1:
            raise ValueError(
                "Fat Cat built-in export requires one exact Lumina registry device; "
                f"found {len(matches)} for {target_slicer_id}/{configured.display_name}/{nozzle}"
            )
        profile = matches[0]

    selected_plate_id = str(build_plate_id or profile.default_build_plate_id or "").strip()
    if selected_plate_id:
        try:
            registry.resolve_build_plate(profile.device_profile_id, selected_plate_id)
        except KeyError as exc:
            raise ValueError(str(exc).strip("'")) from exc
        plate_uid = native_build_plate_uid(selected_plate_id)
        if not plate_uid:
            raise ValueError(
                f"Fat Cat has no build-plate identity for Lumina selection {selected_plate_id!r}"
            )
    else:
        plate_uid = ""

    target_identity = _metadata_target_identity(target_slicer_id)
    nozzle_uid = f"nozzle:{nozzle}mm"
    source = _load_fatcat().native_project_source({
        "slicer_id": target_slicer_id,
        "application_version": target_identity["application_version"],
        "source_machine_profile_name": profile.source_profile_name,
        "nozzle_uid": nozzle_uid,
    })
    availability = source.get("availability") or {}
    if availability.get("machine") != "available":
        raise ValueError(
            "Fat Cat native machine source is unavailable for "
            f"{profile.source_profile_name} {nozzle_uid}"
        )
    return MetadataTarget(
        slicer_id=target_slicer_id,
        application_version=str(target_identity["application_version"]),
        machine_uid=str(source["machine_uid"]),
        nozzle_uid=nozzle_uid,
        build_plate_uid=plate_uid,
    )


def _scalar_text(value: object) -> str:
    if isinstance(value, (list, tuple)):
        if not value:
            return ""
        value = value[0]
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def _rgb_hex(value: object) -> str:
    if isinstance(value, str):
        text = value.strip().upper()
        if text.startswith("#") and len(text) in {7, 9}:
            return text[:7]
    try:
        red, green, blue = (int(channel) for channel in value[:3])  # type: ignore[index]
    except (TypeError, ValueError, IndexError, AttributeError) as exc:
        raise ValueError(f"invalid Fat Cat material colour: {value!r}") from exc
    if any(channel < 0 or channel > 255 for channel in (red, green, blue)):
        raise ValueError(f"invalid Fat Cat material colour: {value!r}")
    return f"#{red:02X}{green:02X}{blue:02X}"


def _canonical_slicer_id(slicer_id: str) -> str:
    from config import normalize_slicer_software_id

    return normalize_slicer_software_id(str(slicer_id or ""))


def build_project_settings_request(
    settings: Mapping[str, object],
    material_colours: Sequence[object],
    *,
    target: MetadataTarget,
    material_mode: str = "preserve_template",
    material_uids: Sequence[str] | None = None,
    filament_slot_mode: str = "preserve",
    default_filament_source_slot: int | None = None,
    filament_source_slots: Sequence[int | None] | None = None,
    disable_cut_retraction: bool = False,
) -> dict[str, Any]:
    """Build explicit material and process selections for Fat Cat C++.

    Pass explicit process, colour and source selections; C++ owns array shaping.
    只传递工艺、颜色、材料模式及逐槽材料选择；原生参数查询和数组
    合成由 C++ 完成，不在适配器中制造一套通用耗材参数。
    """

    if not material_colours:
        raise ValueError("Fat Cat metadata requires at least one material colour")
    colours = [_rgb_hex(value) for value in material_colours]
    request: dict[str, Any] = {
        "slicer_id": target.slicer_id,
        "application_version": target.application_version,
        "machine_uid": target.machine_uid,
        "nozzle_uid": target.nozzle_uid,
        "build_plate_uid": target.build_plate_uid,
        "material_mode": material_mode,
        "filament_slot_mode": filament_slot_mode,
        "enable_prime_tower": "1",
        "filament_colour": colours,
        "filament_multi_colour": list(colours),
    }
    if material_uids is not None:
        request["material_uids"] = list(material_uids)
    if default_filament_source_slot is not None:
        request["default_filament_source_slot"] = default_filament_source_slot
    if filament_source_slots is not None:
        request["filament_source_slots"] = list(filament_source_slots)
    if disable_cut_retraction:
        request["disable_cut_retraction"] = True
    request["process_settings"] = {
        str(key): _scalar_text(value)
        for key, value in settings.items()
        if value is not None
    }
    return request


def build_builtin_project_settings_request(
    settings: Mapping[str, object],
    materials: Sequence[Mapping[str, object]],
    *,
    target: MetadataTarget,
    filament_slot_mode: str = "preserve",
    native_print_profile_name: str | None = None,
    native_filament_profile_names: Sequence[str] | None = None,
    source_slot_colours: Mapping[str, object] | None = None,
    merge_sources: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, Any]:
    """Build a Fat Cat bundled-source request from explicit Lumina facts.

    用 Lumina 明确的机器、材料和工艺事实构造 Fat Cat 内置源请求。
    """

    from core.machine_process_overlay import LUMINA_PROJECT_PRESET_NAME

    if not materials:
        raise ValueError("Fat Cat built-in metadata requires at least one material")
    colours = [material.get("colour", "#808080") for material in materials]
    request = build_project_settings_request(
        settings,
        colours,
        target=target,
        material_mode="preserve_template",
        filament_slot_mode=filament_slot_mode,
    )
    if not target.build_plate_uid:
        request.pop("build_plate_uid", None)
    request.update({
        "project_source": "fatcat_native",
        "project_preset_name": LUMINA_PROJECT_PRESET_NAME,
        "hardware_mode": "preserve_source",
        "machine_uid": target.machine_uid,
        "nozzle_uid": target.nozzle_uid,
        "source_materials": [
            {
                "name": str(material.get("name") or ""),
                "colour": _rgb_hex(material.get("colour", "#808080")),
                **(
                    {"material_type": str(material["material_type"])}
                    if material.get("material_type") is not None
                    else {}
                ),
                **(
                    {"native_filament_profile_name": str(material["native_filament_profile_name"])}
                    if material.get("native_filament_profile_name")
                    else {}
                ),
            }
            for material in materials
        ],
    })
    if target.build_plate_uid:
        request["build_plate_uid"] = target.build_plate_uid
    if native_print_profile_name:
        request["native_print_profile_name"] = native_print_profile_name
    if native_filament_profile_names is not None:
        request["native_filament_profile_names"] = list(native_filament_profile_names)
    if source_slot_colours:
        request["source_slot_colours"] = {
            str(key): _rgb_hex(value)
            for key, value in source_slot_colours.items()
        }
    if merge_sources is not None:
        request["merge_sources"] = [dict(source) for source in merge_sources]
    return request


def build_merged_project_settings_request(
    *,
    target: MetadataTarget,
    sources: Sequence[tuple[str, Mapping[str, object], Sequence[object]]],
) -> dict[str, Any]:
    """Pass source projects and slot identities for C++ batch composition.

    将源项目设置和槽位身份传给 C++，由 Fat Cat 合成批量项目设置。
    """

    from core.machine_process_overlay import LUMINA_PROJECT_PRESET_NAME

    merge_sources: list[dict[str, Any]] = []
    for source_index, (source_id, project, slots) in enumerate(sources):
        source: dict[str, Any] = {
            "source_id": source_id,
            "slots": [
                {
                    "source_slot_id": int(getattr(slot, "slot_id")),
                    "slot_name": str(getattr(slot, "slot_name")),
                    "preview_color": str(getattr(slot, "preview_color")),
                    "material_id": str(getattr(slot, "material_id")),
                    **(
                        {"source_slot_index": int(source_slot_index)}
                        if (source_slot_index := getattr(slot, "source_slot_index", None))
                        is not None
                        else {}
                    ),
                }
                for slot in slots
            ],
        }
        if source_index:
            source["project_settings"] = dict(project)
        merge_sources.append(source)
    request = {
        "slicer_id": target.slicer_id,
        "application_version": target.application_version,
        "hardware_mode": "preserve_source",
        "material_mode": "preserve_template",
        "enable_prime_tower": "1",
        "merge_sources": merge_sources,
        "project_preset_name": LUMINA_PROJECT_PRESET_NAME,
    }
    if target.build_plate_uid:
        request["build_plate_uid"] = target.build_plate_uid
    return request


def build_merged_model_metadata_request(
    *,
    target: MetadataTarget,
    objects: Sequence[MergedModelInput],
    bed_type: str,
    wipe_tower_placement: Mapping[str, object],
    source_slice_info_xml: str | None = None,
) -> ModelMetadataRequest:
    """Describe final merged objects and caller-computed placement to Fat Cat.

    将最终对象及调用方计算的布局位置传给 Fat Cat。
    """

    request: ModelMetadataRequest = {
        "slicer_id": target.slicer_id,
        "application_version": target.application_version,
        "plate": {"bed_type": bed_type},
        "objects": [cast(MergedModelInput, dict(model)) for model in objects],
        "component_inputs": {
            "wipe_tower_placement": dict(wipe_tower_placement),
        },
    }
    if source_slice_info_xml is not None:
        request["source_slice_info_xml"] = source_slice_info_xml
    return request


def _format_number(value: float) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Fat Cat model metadata requires finite geometry values")
    return format(number, ".15g")


def build_model_metadata_request(
    *,
    target: MetadataTarget,
    assembly_id: int,
    object_ids: Sequence[int],
    entries: Sequence[MeshMetadataEntry],
    material_index_by_object: Sequence[int],
    output_path: str | os.PathLike[str],
    bed_type: str,
) -> ModelMetadataRequest:
    """Translate Lumina's queued mesh entries into Fat Cat model metadata input.

    将 Lumina 已排队的网格条目转换为 Fat Cat 模型元数据输入；ID 和几何
    描述来自当前 writer，不重新探测或序列化模型。
    """

    if len(object_ids) != len(entries) or len(entries) != len(material_index_by_object):
        raise ValueError("Fat Cat model metadata inputs have inconsistent object lengths")
    parts: list[ModelPartInput] = []
    for volume_id, (object_id, entry, material_index) in enumerate(
        zip(object_ids, entries, material_index_by_object)
    ):
        bounds = np.asarray(entry.mesh.bounds, dtype=np.float64)
        if bounds.shape != (2, 3) or not np.isfinite(bounds).all():
            raise ValueError("Fat Cat model metadata requires finite 2x3 mesh bounds")
        object_name = entry.object_name
        if not isinstance(object_name, str) or not object_name:
            raise ValueError("Fat Cat model metadata requires a non-empty object name")
        minimum, maximum = bounds
        center = (minimum + maximum) / 2.0
        matrix = (
            "1 0 0 "
            f"{_format_number(maximum[0])} "
            "0 1 0 "
            f"{_format_number(maximum[1])} "
            "0 0 1 "
            f"{_format_number(maximum[2])} "
            "0 0 0 1"
        )
        parts.append(
            {
                "part_id": int(object_id),
                "name": object_name,
                "material_index": int(material_index),
                "source_object_id": 0,
                "source_volume_id": volume_id,
                "matrix": matrix,
                "source_offset_x": _format_number(center[0]),
                "source_offset_y": _format_number(center[1]),
                "source_offset_z": _format_number(center[2]),
            }
        )
    return {
        "slicer_id": target.slicer_id,
        "application_version": target.application_version,
        "assembly_id": int(assembly_id),
        "instance_id": "0",
        "identify_id": "1",
        "source_file": Path(output_path).name,
        "parts": parts,
        "plate": {
            "plater_id": "1",
            "plater_name": "",
            "locked": False,
            "bed_type": str(bed_type),
        },
    }


def _parse_native_json(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("Fat Cat C++ returned invalid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Fat Cat C++ returned a non-object result")
    return value


@lru_cache(maxsize=1)
def _load_fatcat() -> Any:
    """Load the installed Fat Cat binding used by the target route.

    加载目标路径使用的已安装 Fat Cat 绑定；wheel 自己负责读取随包数据。
    """

    try:
        fatcat = importlib.import_module("fatcat_metadata")
    except ImportError as exc:
        raise RuntimeError(
            "Fat Cat requires the installed Fat Cat C++ metadata package"
        ) from exc
    missing = [
        name
        for name in (
            "compose_project_settings",
            "native_project_source_catalog",
            "native_project_source",
            "list_native_fields",
            "compose_model_metadata",
            "patch_wipe_tower",
            "template_import_parts",
            "detect_template_source",
            "import_template_metadata",
        )
        if not callable(getattr(fatcat, name, None))
    ]
    if missing:
        raise RuntimeError(f"Fat Cat C++ package is missing entry points: {missing}")
    return fatcat


def _target_selection_json(target: MetadataTarget | SourceMaterialTarget) -> str:
    return json.dumps(
        {
            "slicer_id": target.slicer_id,
            "application_version": target.application_version,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


@lru_cache(maxsize=None)
def _metadata_target_identity(slicer_id: str) -> dict[str, Any]:
    return _parse_native_json(_load_fatcat().metadata_target(slicer_id))


def _template_selection_json(slicer_id: str) -> str:
    return json.dumps(
        {"slicer_id": slicer_id, "application_version": _metadata_target_identity(slicer_id)["application_version"]},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def template_import_parts(slicer_id: str) -> dict[str, Any]:
    """Read template text member paths from the selected Fat Cat target.

    从已选 Fat Cat 目标读取模板文本成员路径。
    """

    raw = _load_fatcat().template_import_parts(_template_selection_json(slicer_id))
    return _parse_native_json(raw)


def resolve_template_build_plate(
    *,
    slicer_id: str,
    default_build_plate_uid: str,
    model_plate_value: str | None,
    sidecar_bed_value: str | None,
    project_bed_value: str | None,
) -> dict[str, str]:
    """Select the effective imported plate from Fat Cat target bindings.

    由 Fat Cat 目标打印板映射确定导入模板的有效打印板。
    """

    raw = _load_fatcat().resolve_template_build_plate(
        _template_selection_json(slicer_id),
        default_build_plate_uid,
        model_plate_value,
        sidecar_bed_value,
        project_bed_value,
    )
    return _parse_native_json(raw)


def detect_template_source(
    source_model_xml: str | None, slice_info_xml: str | None
) -> dict[str, Any]:
    """Identify a migrated source and its declared version in Fat Cat.

    在 Fat Cat 中识别已迁移来源及其文件声明版本。

    Raises:
        ValueError: Invalid template source. 模板来源无效。
    """

    sdk = _load_fatcat()
    try:
        raw = sdk.detect_template_source(source_model_xml, slice_info_xml)
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc
    return _parse_native_json(raw)


def import_template_metadata(
    project_settings_json: str,
    source_model_xml: str | None,
    slice_info_xml: str | None,
    model_settings_xml: str | None,
    plate_sidecar_json: str | None,
    *,
    slicer_id: str,
    explicit_slicer_hint: bool,
) -> dict[str, Any]:
    """Interpret a user project template through the Fat Cat C++ binding.

    通过 Fat Cat C++ binding 解释用户项目模板。

    Raises:
        ValueError: Invalid or unsupported project input. 项目输入无效或不支持。
    """

    sdk = _load_fatcat()
    selection_json = _template_selection_json(slicer_id)
    try:
        raw = sdk.import_template_metadata(
            project_settings_json,
            source_model_xml,
            slice_info_xml,
            model_settings_xml,
            plate_sidecar_json,
            selection_json,
            explicit_slicer_hint,
        )
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc
    return _parse_native_json(raw)


@lru_cache(maxsize=None)
def metadata_resource_specs(slicer_id: str) -> dict[str, dict[str, Any]]:
    """Read resource roles, paths and relationships from Fat Cat.

    从 Fat Cat 读取资源角色、包内路径和关系。
    """
    resources = json.loads(_load_fatcat().metadata_resource_specs(slicer_id))
    return {resource["role"]: resource for resource in resources}


def read_project_layout(
    project: Mapping[str, object], *, slicer_id: str,
) -> ProjectLayout:
    """Read numeric layout facts through Fat Cat.

    通过 Fat Cat 读取数值化布局事实，布局计算仍由调用方完成。
    """
    raw = _load_fatcat().read_project_layout(
        json.dumps(dict(project), ensure_ascii=False), _template_selection_json(slicer_id),
    )
    return cast(ProjectLayout, _parse_native_json(raw))


def read_placement_warnings(payload: str | None) -> list[str]:
    """Read warning codes from an optional placement part.

    从可选布局部件读取警告代码。
    """
    return json.loads(_load_fatcat().read_placement_warnings(payload))


def read_project_material_slots(
    project: Mapping[str, object], *, target: MetadataTarget,
) -> list[dict[str, Any]]:
    """Read a template's native material capacity without guessing its array shape.

    由 FatCat 读取模板材料槽容量，不在调用方猜测原生数组结构。
    """
    return json.loads(_load_fatcat().extract_source_material_slots(
        json.dumps(dict(project), ensure_ascii=False), "<config/>", _target_selection_json(target),
    ))


def read_model_object_metadata(model_xml: str) -> list[dict[str, Any]]:
    """Read object metadata without interpreting mesh geometry.

    读取对象元数据，不解释网格几何。
    """
    return json.loads(_load_fatcat().read_model_object_metadata(model_xml))


def serialize_layer_config_ranges(
    data: Mapping[str, object], fine_layer_height_mm: float,
) -> str:
    """Serialize caller-computed layer ranges through Fat Cat.

    由 Fat Cat 序列化调用方计算的层高区间。
    """
    return _load_fatcat().serialize_layer_config_ranges(
        json.dumps(dict(data), ensure_ascii=False), fine_layer_height_mm,
    )


def validate_template_hardware(
    template: Mapping[str, object], expected: Mapping[str, object],
    source_slicer: str, selected_slicer: str,
) -> None:
    """Check imported hardware against the selected source in Fat Cat.

    由 Fat Cat 比对导入模板与所选来源的硬件配置。

    Raises:
        ValueError: Template hardware or slicer mismatch. 模板硬件或软件不匹配。
    """
    sdk = _load_fatcat()
    try:
        sdk.validate_template_hardware(
            json.dumps(dict(template), ensure_ascii=False),
            json.dumps(dict(expected), ensure_ascii=False), source_slicer, selected_slicer,
        )
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc


def decode_source_metadata(
    project_json: str, model_settings_xml: str, *,
    target: MetadataTarget | SourceMaterialTarget | None = None,
    source_model_xml: str | None = None,
    slice_info_xml: str | None = None,
    placement_json: str | None = None,
) -> dict[str, Any]:
    """Interpret source metadata text in C++.

    由 C++ 解释源元数据文本。
    """
    if target is None:
        source = detect_template_source(source_model_xml, slice_info_xml)
        slicer_id = source["source_slicer"] or "BambuStudio"
        target = SourceMaterialTarget(slicer_id, _metadata_target_identity(slicer_id)["application_version"])
    return _parse_native_json(_load_fatcat().read_source_metadata(
        project_json, model_settings_xml, _target_selection_json(target),
        source_model_xml, slice_info_xml, placement_json,
    ))


def read_source_metadata(
    source_3mf_path: str | os.PathLike[str], *,
    target: MetadataTarget | SourceMaterialTarget | None = None,
) -> dict[str, Any]:
    """Load metadata members and pass their text to Fat Cat.

    读取包内元数据部件，将文本交给 Fat Cat 解释。
    """
    with zipfile.ZipFile(source_3mf_path) as package:
        metadata, _ = _read_source_metadata_parts(package, target=target)
        return metadata


def _read_source_metadata_parts(
    package: zipfile.ZipFile,
    *,
    target: MetadataTarget | SourceMaterialTarget | None = None,
    source_model_xml: str | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Decode source metadata once and retain its bytes for geometry assembly."""
    members = set(package.namelist())
    if target is None:
        common_paths = template_import_parts("BambuStudio")
        source = detect_template_source(
            source_model_xml if source_model_xml is not None else
            package.read(common_paths["source_model"]).decode("utf-8")
            if common_paths["source_model"] in members else None,
            package.read(common_paths["slice_info"]).decode("utf-8")
            if common_paths["slice_info"] in members else None,
        )
        slicer_id = source["source_slicer"] or "BambuStudio"
        target = SourceMaterialTarget(
            slicer_id, _metadata_target_identity(slicer_id)["application_version"],
        )
    paths = template_import_parts(target.slicer_id)
    parts = {
        role: (source_model_xml.encode("utf-8")
               if role == "source_model" and source_model_xml is not None
               else package.read(paths[role]))
        for role in (
            "project_settings", "model_settings", "source_model",
            "slice_info", "wipe_tower_placement",
        )
        if role in {"project_settings", "model_settings"} or paths[role] in members
    }

    def optional_text(role: str) -> str | None:
        payload = parts.get(role)
        return payload.decode("utf-8") if payload is not None else None

    metadata = decode_source_metadata(
        parts["project_settings"].decode("utf-8"),
        parts["model_settings"].decode("utf-8"),
        target=target,
        source_model_xml=optional_text("source_model"),
        slice_info_xml=optional_text("slice_info"),
        placement_json=optional_text("wipe_tower_placement"),
    )
    return metadata, parts


def compose_project_settings(
    base_project: Mapping[str, Any],
    request: Mapping[str, Any],
) -> ProjectComposition:
    """Compose project settings through C++.

    通过已安装的 C++ 入口合成项目设置。
    """

    fatcat = _load_fatcat()
    project_json = json.dumps(
        dict(base_project), ensure_ascii=False, separators=(",", ":")
    )
    request_json = json.dumps(
        dict(request), ensure_ascii=False, separators=(",", ":")
    )
    try:
        raw = fatcat.compose_project_settings(project_json, request_json)
    except fatcat.ProjectValidationError as exc:
        from core.errors import NativeMaterialSelectionError

        raise NativeMaterialSelectionError(exc.detail) from exc
    return cast(ProjectComposition, _parse_native_json(raw))


def compose_builtin_project_settings(
    request: Mapping[str, Any],
) -> ProjectComposition:
    """Compose a project from Fat Cat's installed native profile source.

    通过 Fat Cat 已安装的原生来源配置合成项目设置。
    """

    fatcat = _load_fatcat()
    request_json = json.dumps(
        dict(request), ensure_ascii=False, separators=(",", ":")
    )
    try:
        raw = fatcat.compose_project_settings(request_json)
    except fatcat.ProjectValidationError as exc:
        from core.errors import NativeMaterialSelectionError

        raise NativeMaterialSelectionError(exc.detail) from exc
    return cast(ProjectComposition, _parse_native_json(raw))


def resolve_project_materials(request: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve native presets and compatible plates through the composition policy.

    使用组装器的同一规则预检原生耗材、候选预设和共同兼容板型。
    """
    return dict(_load_fatcat().resolve_project_materials(dict(request)))


def compose_model_metadata(
    project: Mapping[str, Any] | str,
    request: Mapping[str, Any],
) -> ModelComposition:
    """Compose model/slice XML through C++.

    通过已安装的 C++ 入口合成模型和切片元数据。
    """

    fatcat = _load_fatcat()
    project_json = (
        project
        if isinstance(project, str)
        else json.dumps(dict(project), ensure_ascii=False, separators=(",", ":"))
    )
    request_json = json.dumps(
        dict(request), ensure_ascii=False, separators=(",", ":")
    )
    raw = fatcat.compose_model_metadata(project_json, request_json)
    return cast(ModelComposition, _parse_native_json(raw))


def patch_wipe_tower(
    project: Mapping[str, Any],
    settings: Mapping[str, Any],
    dialect: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply computed tower placement and native style through FatCat's API.

    通过 FatCat 擦料塔接口写回计算出的坐标、宽度、旋转和可选原生塔形状，
    不重新合成整份项目设置。
    """

    fatcat = _load_fatcat()
    raw = fatcat.patch_wipe_tower(
        json.dumps(dict(project), ensure_ascii=False, separators=(",", ":")),
        json.dumps(dict(settings), ensure_ascii=False, separators=(",", ":")),
        json.dumps(dict(dialect), ensure_ascii=False, separators=(",", ":")),
    )
    return _parse_native_json(raw)
