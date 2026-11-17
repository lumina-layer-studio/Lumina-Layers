"""Merge source geometry with Fat Cat metadata and one neroued package write.

复用源几何，由 Fat Cat 合成元数据，再由 neroued 一次写出批量或拼图 3MF。
"""

from __future__ import annotations

import json
import math
import uuid
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, Mapping, Sequence

import numpy as np
from utils.fatcat_metadata import (
    MetadataTarget,
    MergedModelInput,
    ModelComposition,
    ModelMetadataRequest,
    PlateSummaryObject,
    ProjectComposition,
    ProjectLayout,
    build_merged_model_metadata_request,
    build_merged_project_settings_request,
    compose_model_metadata,
    external_spool_filament_map,
    compose_project_settings,
    metadata_resource_specs,
    patch_wipe_tower,
    read_project_layout,
)
from utils.slicer_3mf_support import (
    DEFAULT_EXPORT_SETTINGS,
    build_wipe_tower_placement_metadata_payload,
    build_wipe_tower_placement_request,
    build_wipe_tower_patch_settings,
    resolve_export_device,
)

if TYPE_CHECKING:
    from core.wipe_tower_placement import WipeTowerPlacementResult
    import neroued_3mf as n3mf


class MergedWriteError(Exception):
    """Domain error raised by the merged 3MF writer.
    合并 3MF writer 抛出的领域异常。

    Raised exclusively by :class:`MergedBambu3MFWriter` when an object
    cannot be composed, an OPC archive cannot be packed, or disk I/O
    fails. The route layer (``convert_batch``) wraps the underlying cause
    with a ``stage`` label (currently ``"merge_3mf"``) and maps the
    exception to ``HTTP 500`` via
    :func:`api.errors.to_http_exception`. Callers SHOULD include the
    original exception as ``__cause__`` (``raise MergedWriteError(...) from exc``)
    to keep root-cause traceability in structured logs.

    本异常仅由 :class:`MergedBambu3MFWriter` 抛出，覆盖对象组合失败、
    OPC 打包失败、磁盘 I/O 失败等写出阶段错误。路由层
    (``convert_batch``) 在 ``except`` 边界给底层 cause 附加
    ``stage`` 标签（当前为 ``"merge_3mf"``）并通过
    :func:`api.errors.to_http_exception` 映射为 ``HTTP 500``。调用方应当用
    ``raise MergedWriteError(...) from exc`` 保留原始异常以便结构化日志
    追溯根因。
    """


@dataclass(frozen=True)
class MaterialSlot:
    """Material slot identity inside :class:`MergedItem`.
    :class:`MergedItem` 中的材料 slot 身份描述。

    The batch worker writes the first four fields to its JSON sidecar.
    The parent process constructs these slots before merged export.
    批量 worker 把前四个字段写入 JSON sidecar，父进程据此构建合并导出
    所需的材料槽位。

    Attributes:
        slot_id: 0-based slot index in the slicer. Uniqueness within a
            single :class:`MergedItem` is enforced by the writer's
            ``slots`` validation, not by this dataclass.
            切片软件中的 0-based slot 索引。单个 :class:`MergedItem`
            内的唯一性由 writer 的 ``slots`` 校验保证，本 dataclass
            不强制。
        slot_name: Slot display name shown by the slicer
            (e.g. ``"Bambu PLA Black"``).
            切片软件中显示的 slot 名（例如 ``"Bambu PLA Black"``）。
        preview_color: Six-digit hex color used for frontend preview
            (e.g. ``"#101010"``).
            前端预览用六位十六进制颜色（例如 ``"#101010"``）。
        material_id: Stable material-archive identity used to detect conflicting
            assignments to the same logical slot. The output preserves the
            source's native filament identity in the slicer's project arrays.
            材料库的稳定标识，用于检查同一逻辑槽位的材料是否冲突。
            输出通过切片软件的原生耗材数组保留源项目的材料身份。
        source_slot_index: Optional index in the source project's filament
            arrays. It differs from slot_id when puzzle palette order selects
            or reorders source slots.
            源项目耗材数组中的索引。拼图调色板选择或重排槽位时，它与 slot_id 不同。
    """

    slot_id: int
    slot_name: str
    preview_color: str
    material_id: str
    source_slot_index: int | None = None


@dataclass(frozen=True)
class MergedItem:
    """One object input for :class:`MergedBambu3MFWriter`.
    :class:`MergedBambu3MFWriter` 的单个对象输入。

    The geometry source is the per-image export-grade 3MF produced by
    ``worker_batch_convert_item`` (see ``threemf_path`` in the worker
    return value). The merge stage reuses meshes and material
    definitions directly from that file so the full Bambu metadata
    (auxiliary meshes, slot bindings, slicer config) is preserved.

    几何源是 ``worker_batch_convert_item`` 产出的 per-image 导出级
    3MF（worker 返回值中的 ``threemf_path``）。合并阶段直接复用该
    文件中的 mesh 与材料定义，从而保留完整的 Bambu 元数据（辅助
    网格、slot 绑定、切片配置等）。

    NOT accepted as a geometry source:

    - :class:`trimesh.Scene` instances. Scene objects routinely lose
      vendor metadata when round-tripped through ``to_dict`` /
      ``dump_to_bytes`` and cannot be passed across the worker
      boundary anyway (workers communicate via file paths + scalars).
    - GLB-derived scenes (e.g. anything loaded from the per-image
      ``preview_glb_path``). Preview GLB is a frontend-only artifact
      and routinely strips slot bindings, auxiliary meshes, and
      slicer-side config; using it here is the canonical "preview model
      mistaken for export model" bug we explicitly forbid.

    禁止作为几何源使用：

    - :class:`trimesh.Scene` 实例。Scene 在跨函数 / 跨进程传递时常常
      丢失 vendor metadata（``to_dict`` / ``dump_to_bytes`` 之类的
      pickle hack 都不可靠），而且 worker 边界本身就只允许传文件路径
      + 标量。
    - GLB-derived scene（比如从 per-image ``preview_glb_path`` load
      回来的 Scene）。预览 GLB 仅服务前端 3D 显示，会丢 slot 绑定、
      辅助网格、切片配置；把它当成合并 3MF 的几何源是典型的"预览
      模型误当导出模型"bug，本模块明确禁止。

    Attributes:
        source_filename: Original upload filename (e.g. ``"kitten.png"``);
            kept for diagnostics and for object naming inside the
            merged 3MF.
            原始上传文件名（例如 ``"kitten.png"``）；用于诊断信息以及
            合并 3MF 内部对象命名。
        source_3mf_path: Path to the per-image export-grade 3MF that
            serves as the sole authoritative geometry / material
            source for this object in the merged 3MF.
            per-image 导出级 3MF 的路径；该对象在合并 3MF 中的几何
            与材料定义的唯一权威来源。
        slots: Full identity list of material slots used by this
            object. Order does not have to be contiguous in
            ``slot_id`` (the writer may remap to a contiguous range
            internally for slicer compatibility); round-trip tests
            still compare the four-tuple identity.
            该对象使用的全部材料 slot 身份列表。``slot_id`` 不要求
            连续（writer 内部可能为切片软件兼容性 remap 到连续区间），
            round-trip 测试仍按四元组身份比较。
        tx_mm: X translation in the merged-3MF world coordinate system.
            Specifies where the object's XY bbox **min corner** should
            land; the writer is responsible for compensating any
            non-zero local origin in ``source_3mf_path``.
            合并 3MF 世界坐标系下的 X 平移；指定该对象 XY 包围盒
            **左下角**应当落到的位置。``source_3mf_path`` 内部如有
            非零本地原点，由 writer 负责补偿。
        ty_mm: Y translation in the merged-3MF world coordinate system,
            with the same "bbox min corner" semantics as ``tx_mm``.
            合并 3MF 世界坐标系下的 Y 平移，``tx_mm`` 同款语义。
    """

    source_filename: str
    source_3mf_path: Path
    slots: tuple[MaterialSlot, ...]
    tx_mm: float
    ty_mm: float


__all__ = [
    "MergedWriteError",
    "MaterialSlot",
    "MergedItem",
    "MergedBambu3MFWriter",
    "MergedSlicer3MFWriter",
]


# ---------------------------------------------------------------------------
# Internal helpers (zip / XML parsing of source 3MFs)
# ---------------------------------------------------------------------------

# 3MF / OPC namespaces.
_NS_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_NS_PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"


@dataclass(frozen=True)
class _SourceMesh:
    """One mesh entry parsed from a source 3MF's per-item ``object_*.model``.

    Attributes:
        original_id: Original ``<object id>`` inside the source per-item
            ``.model`` file. Kept only for diagnostics; the writer
            renumbers to globally-unique IDs.
        element: Object attributes and metadata, with vertex and triangle
            rows omitted. Geometry is loaded only while queuing this mesh.
        metadata: Fat Cat decoded metadata attached to this model object.
            Fat Cat 读取的模型对象元数据。
    """

    original_id: int
    element: ET.Element
    metadata: tuple[dict[str, str], ...]


@dataclass(frozen=True)
class _SourceAssembly:
    """The aggregate of one ``MergedItem`` after parsing its source 3MF.

    Attributes:
        meshes: Lightweight mesh descriptions in source component order.
        source_mesh_path: Archive member containing the referenced geometry.
        source_assembly_id: Source build object's id in the source 3MF.
        min_x: Minimum X vertex coordinate across all ``meshes`` (mm),
            after applying source component transforms.
        min_y: Minimum Y vertex coordinate across all ``meshes`` (mm),
            after applying source component transforms.
    component_transforms: Per-component transform strings from source.
    component_uuids: Per-component p:UUID strings from source.
    metadata_parts: Raw Bambu metadata parts copied from the source 3MF.
    project_settings: Parsed source project settings, if present.
    root_metadata: Top-level ``3D/3dmodel.model`` metadata from source.
    """

    meshes: tuple[_SourceMesh, ...]
    source_mesh_path: str
    source_assembly_id: int
    source_assembly_uuid: str
    source_build_item_uuid: str
    min_x: float
    min_y: float
    max_x: float
    max_y: float
    min_z: float
    max_z: float
    component_transforms: tuple[str, ...]
    component_uuids: tuple[str, ...]
    base_material_groups: tuple[ET.Element, ...]
    metadata_parts: dict[str, bytes]
    project_settings: dict[str, Any]
    root_metadata: dict[str, str]
    source_metadata: dict[str, Any]
    source_build_transform: tuple[float, ...]
    source_model_index: int = 1


def _qname_core(tag: str) -> str:
    return f"{{{_NS_CORE}}}{tag}"


def _qname_prod(attr: str) -> str:
    return f"{{{_NS_PROD}}}{attr}"


def _parse_transform_matrix(transform_str: str) -> list[float]:
    """Parse the first three columns of a 3MF row-vector affine matrix.

    3MF transform format: m00 m01 m02 m10 m11 m12 m20 m21 m22 tx ty tz
    An absent or blank transform means identity; malformed values cannot
    describe a reliable source footprint.
    """
    if not transform_str or not transform_str.strip():
        return [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
    parts = transform_str.strip().split()
    if len(parts) != 12:
        raise MergedWriteError("Source component transform must contain 12 numbers")
    try:
        values = [float(p) for p in parts]
    except ValueError as exc:
        raise MergedWriteError("Source component transform contains a non-numeric value") from exc
    if not all(math.isfinite(value) for value in values):
        raise MergedWriteError("Source component transform must contain finite values")
    return values


def _validate_slots(slots: Sequence[MaterialSlot]) -> None:
    """Require a nonempty sequence of MaterialSlot values with unique IDs."""

    if len(slots) < 1:
        raise MergedWriteError("MergedItem.slots must contain at least one slot")
    seen_ids: set[int] = set()
    for slot in slots:
        if not isinstance(slot, MaterialSlot):
            raise MergedWriteError(
                f"MergedItem.slots entries must be MaterialSlot; got {type(slot).__name__}"
            )
        if slot.slot_id in seen_ids:
            raise MergedWriteError(
                f"duplicate MaterialSlot.slot_id={slot.slot_id} within a single MergedItem"
            )
        seen_ids.add(slot.slot_id)


def _read_model_structure(
    package: zipfile.ZipFile,
    path: str,
    transforms: Mapping[str, Sequence[Sequence[float]]] | None = None,
) -> tuple[ET.Element, list[float]]:
    """Keep object metadata while streaming geometry into transformed bounds."""
    bounds = [math.inf, math.inf, math.inf, -math.inf, -math.inf, -math.inf]
    stack: list[ET.Element] = []
    # Transform a small vertex block in NumPy without retaining the full mesh.
    coordinates = np.empty((4096, 3), dtype=np.float64)
    coordinate_count = 0
    matrices: list[np.ndarray] = []

    def flush_coordinates() -> None:
        nonlocal coordinate_count
        if coordinate_count == 0:
            return
        points = coordinates[:coordinate_count]
        if not np.isfinite(points).all():
            raise MergedWriteError("Source model has non-finite vertex coordinates")
        for matrix in matrices:
            transformed = points @ matrix[:9].reshape((3, 3)) + matrix[9:]
            lower, upper = transformed.min(axis=0), transformed.max(axis=0)
            for axis in range(3):
                bounds[axis] = min(bounds[axis], float(lower[axis]))
                bounds[axis + 3] = max(bounds[axis + 3], float(upper[axis]))
        coordinate_count = 0

    with package.open(path) as stream:
        parser = ET.iterparse(stream, events=("start", "end"))
        for event, element in parser:
            if event == "start":
                stack.append(element)
                if element.tag == _qname_core("object"):
                    matrices = [
                        np.asarray(matrix, dtype=np.float64)
                        for matrix in (transforms or {}).get(element.get("id", ""), ())
                    ]
                continue
            if element.tag == _qname_core("vertex"):
                if matrices and element.get("x") is not None and element.get("y") is not None:
                    coordinates[coordinate_count] = [
                        float(element.get(axis, "0")) for axis in ("x", "y", "z")
                    ]
                    coordinate_count += 1
                    if coordinate_count == len(coordinates):
                        flush_coordinates()
                stack[-2].remove(element)
            elif element.tag == _qname_core("triangle"):
                stack[-2].remove(element)
            elif element.tag == _qname_core("object"):
                flush_coordinates()
                matrices = []
            stack.pop()
        return parser.root, bounds


def _parse_source_assembly(
    item_idx: int, item: MergedItem, *, metadata_target: MetadataTarget | None = None,
) -> _SourceAssembly:
    """Read source bounds and metadata without retaining mesh XML rows.

    Preserve source component order, transforms, UUIDs and material identity.
    """

    from utils.fatcat_metadata import _read_source_metadata_parts, read_model_object_metadata

    src_path = item.source_3mf_path
    if not isinstance(src_path, Path):
        src_path = Path(src_path)
    if not src_path.exists():
        raise MergedWriteError(
            f"MergedItem[{item_idx}].source_3mf_path does not exist: {src_path}"
        )

    try:
        with zipfile.ZipFile(src_path, "r") as zf:
            if "3D/3dmodel.model" not in zf.namelist():
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path missing 3D/3dmodel.model"
                )
            main_root, _ = _read_model_structure(zf, "3D/3dmodel.model")
            source_metadata, source_parts = _read_source_metadata_parts(
                zf, target=metadata_target,
                source_model_xml=ET.tostring(main_root, encoding="unicode"),
            )
            root_metadata = source_metadata["source_root_metadata"]

            # Identify the build target object id.
            build_elem = main_root.find(_qname_core("build"))
            if build_elem is None:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path missing <build>"
                )
            build_items = list(build_elem.findall(_qname_core("item")))
            if len(build_items) != 1:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}] must contain exactly one build assembly; "
                    f"found {len(build_items)}. Export each source as a single object project."
                )
            source_build_transform = _parse_transform_matrix(build_items[0].get("transform", ""))
            if not np.allclose(source_build_transform[:9], [1, 0, 0, 0, 1, 0, 0, 0, 1], atol=1e-9, rtol=0):
                raise MergedWriteError(
                    f"MergedItem[{item_idx}] has a rotated or scaled build assembly; "
                    "apply its rotation and scale to the source geometry before merging."
                )
            target_objectid = build_items[0].get("objectid")
            if target_objectid is None:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path build item missing objectid"
                )

            # Find the assembly object element with that id.
            resources_elem = main_root.find(_qname_core("resources"))
            if resources_elem is None:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path missing <resources>"
                )
            assembly_elem = None
            for obj in resources_elem.findall(_qname_core("object")):
                if obj.get("id") == target_objectid:
                    assembly_elem = obj
                    break
            if assembly_elem is None:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path has no <object id={target_objectid!r}>"
                )
            source_assembly_uuid = assembly_elem.get(_qname_prod("UUID")) or ""
            source_build_item_uuid = (
                build_items[0].get(_qname_prod("UUID")) or ""
            )

            # Walk <components> to learn which per-item .model file holds
            # the actual mesh objects, plus the referenced objectids.
            components = assembly_elem.find(_qname_core("components"))
            if components is None:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path build object lacks <components>; "
                    "merge writer requires component-style assembly objects"
                )
            # (p:path, objectid, transform, p:UUID)
            referenced: list[tuple[str, str, str, str]] = []
            for comp in components.findall(_qname_core("component")):
                p_path = comp.get(_qname_prod("path")) or "/3D/3dmodel.model"
                obj_id = comp.get("objectid")
                if not obj_id:
                    raise MergedWriteError(
                        f"MergedItem[{item_idx}].source_3mf_path has <component> without "
                        "objectid"
                    )
                # Preserve transform and UUID from source component
                comp_transform = comp.get("transform") or ""
                comp_uuid = comp.get(_qname_prod("UUID")) or ""
                referenced.append((p_path, obj_id, comp_transform, comp_uuid))

            # All components must point to the same per-item .model file
            # (this is the shape produced by BambuStudio3MFWriter and by
            # the reference 多项目参考.3mf).
            distinct_paths = {p for p, _, _, _ in referenced}
            if len(distinct_paths) != 1:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path components reference multiple "
                    f"per-item .model files: {sorted(distinct_paths)!r}; merge writer "
                    "requires a single per-item .model file"
                )
            per_item_path = next(iter(distinct_paths))
            # Strip leading slash for zip path.
            per_item_zip_path = per_item_path.lstrip("/")
            transforms: dict[str, list[list[float]]] = {}
            for _, object_id, transform, _ in referenced:
                transforms.setdefault(object_id, []).append(_parse_transform_matrix(transform))
            try:
                per_item_root, bounds = _read_model_structure(zf, per_item_zip_path, transforms)
            except KeyError as exc:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path missing per-item model "
                    f"{per_item_zip_path!r}"
                ) from exc

            object_metadata = {
                item["id"]: tuple(item["metadata"])
                for item in read_model_object_metadata(ET.tostring(per_item_root, encoding="unicode"))
            }
            per_item_resources = per_item_root.find(_qname_core("resources"))
            if per_item_resources is None:
                raise MergedWriteError(
                    f"MergedItem[{item_idx}] per-item model {per_item_zip_path!r} "
                    "missing <resources>"
                )

            # Collect referenced mesh objects in the order they appear in
            # <components> (preserves slot order in the merged output).
            id_to_obj: dict[str, ET.Element] = {}
            for obj in per_item_resources.findall(_qname_core("object")):
                obj_id = obj.get("id")
                if obj_id is not None:
                    id_to_obj[obj_id] = obj

            ordered_mesh_objs: list[tuple[str, ET.Element]] = []
            component_transforms: list[str] = []
            component_uuids: list[str] = []
            for _, ref_id, comp_transform, comp_uuid in referenced:
                if ref_id not in id_to_obj:
                    raise MergedWriteError(
                        f"MergedItem[{item_idx}] per-item model {per_item_zip_path!r} "
                        f"missing <object id={ref_id!r}> referenced by 3D/3dmodel.model"
                    )
                ordered_mesh_objs.append((ref_id, id_to_obj[ref_id]))
                component_transforms.append(comp_transform)
                component_uuids.append(comp_uuid)

            min_x, min_y, min_z, max_x, max_y, max_z = bounds
            if (
                not all(math.isfinite(value) for value in (
                    min_x, min_y, max_x, max_y, min_z, max_z,
                ))
                or max_x <= min_x
                or max_y <= min_y
                or not math.isfinite(max_x - min_x)
                or not math.isfinite(max_y - min_y)
            ):
                raise MergedWriteError(
                    f"MergedItem[{item_idx}].source_3mf_path has no finite positive XY footprint"
                )

            metadata_parts = {
                "Metadata/model_settings.config": source_parts["model_settings"],
            }
            if "slice_info" in source_parts:
                metadata_parts["Metadata/slice_info.config"] = source_parts["slice_info"]
            layer_ranges_path = "Metadata/layer_config_ranges.xml"
            if layer_ranges_path in zf.namelist():
                metadata_parts[layer_ranges_path] = zf.read(layer_ranges_path)
            project_settings = source_metadata["project_settings"]

            meshes: list[_SourceMesh] = []
            for orig_id, obj_elem in ordered_mesh_objs:
                meshes.append(
                    _SourceMesh(
                        original_id=int(orig_id) if orig_id.isdigit() else 0,
                        element=obj_elem,
                        metadata=object_metadata.get(orig_id, ()),
                    )
                )

            return _SourceAssembly(
                meshes=tuple(meshes),
                source_mesh_path=per_item_zip_path,
                source_assembly_id=int(target_objectid),
                source_model_index=1,
                source_build_transform=tuple(source_build_transform),
                source_assembly_uuid=source_assembly_uuid,
                source_build_item_uuid=source_build_item_uuid,
                min_x=min_x,
                min_y=min_y,
                max_x=max_x,
                max_y=max_y,
                min_z=min_z,
                max_z=max_z,
                component_transforms=tuple(component_transforms),
                component_uuids=tuple(component_uuids),
                base_material_groups=tuple(
                    per_item_resources.findall(_qname_core("basematerials"))
                ),
                metadata_parts=metadata_parts,
                project_settings=project_settings,
                root_metadata=root_metadata,
                source_metadata=source_metadata,
            )
    except MergedWriteError:
        raise
    except (zipfile.BadZipFile, OSError) as exc:
        raise MergedWriteError(
            f"MergedItem[{item_idx}].source_3mf_path could not be opened as zip: {exc}"
        ) from exc
    except ET.ParseError as exc:
        raise MergedWriteError(
            f"MergedItem[{item_idx}].source_3mf_path has invalid XML: {exc}"
        ) from exc
    except ValueError as exc:
        raise MergedWriteError(
            f"MergedItem[{item_idx}].source_3mf_path has invalid geometry: {exc}"
        ) from exc


def _iter_source_meshes(
    item: MergedItem, assembly: _SourceAssembly,
) -> Iterator[tuple[int, _SourceMesh, ET.Element]]:
    """Load one referenced mesh at a time and release it after native copying."""
    by_id: dict[str, list[tuple[int, _SourceMesh]]] = {}
    for index, mesh in enumerate(assembly.meshes):
        by_id.setdefault(mesh.element.get("id", ""), []).append((index, mesh))
    stack: list[ET.Element] = []
    selected = False
    seen: set[str] = set()
    with zipfile.ZipFile(item.source_3mf_path) as package:
        with package.open(assembly.source_mesh_path) as stream:
            for event, element in ET.iterparse(stream, events=("start", "end")):
                if event == "start":
                    stack.append(element)
                    if element.tag == _qname_core("object"):
                        selected = element.get("id") in by_id
                    continue
                if element.tag == _qname_core("object"):
                    object_id = element.get("id", "")
                    for index, mesh in by_id.get(object_id, ()):
                        yield index, mesh, element
                    seen.add(object_id)
                    stack[-2].remove(element)
                    element.clear()
                    selected = False
                elif not selected and element.tag in (_qname_core("vertex"), _qname_core("triangle")):
                    stack[-2].remove(element)
                stack.pop()
    if by_id.keys() - seen:
        raise MergedWriteError("Source model changed while merging; referenced mesh is missing")


def read_merge_source_info(
    source_3mf_path: str | Path, *, metadata_target: MetadataTarget | None = None,
    use_base_material_names: bool = False,
) -> tuple[tuple[float, float], list[dict[str, Any]]]:
    """Read batch footprint and material identities from the merge source.

    Include every exported component under its component transform, matching
    the merger's minimum-corner placement. The original build placement is
    replaced during merge and therefore does not affect this footprint.
    """
    path = Path(source_3mf_path)
    assembly = _parse_source_assembly(
        0, MergedItem(path.name, path, (), 0.0, 0.0), metadata_target=metadata_target,
    )
    slots = assembly.source_metadata["slots"]
    if use_base_material_names:
        # Lumina single exports register one full palette, even when some slots
        # have no mesh. Native part names can instead identify backing or outlines.
        groups = assembly.base_material_groups
        if len(groups) != 1:
            raise MergedWriteError("The generated 3MF must have one material palette for external spool assignment.")
        palette = groups[0].findall(_qname_core("base"))
        if len(palette) != len(slots) or any(not row.get("name") for row in palette):
            raise MergedWriteError("The generated material palette does not match the filament slots.")
        slots = [{**slot, "slot_name": palette[slot["slot_id"]].get("name")} for slot in slots]
    return (assembly.max_x - assembly.min_x, assembly.max_y - assembly.min_y), slots


def _extract_mesh_arrays(
    mesh_element: ET.Element,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract vertices and faces from a source 3MF mesh <object> element.

    从源 3MF 的 mesh <object> 元素中提取顶点和面数组。

    Returns:
        (vertices, faces) as compact native numpy arrays (float32, uint32).
    """
    mesh_elem = mesh_element.find(_qname_core("mesh"))
    if mesh_elem is None:
        return np.zeros((0, 3), dtype=np.float32), np.zeros((0, 3), dtype=np.uint32)

    vertices_elem = mesh_elem.find(_qname_core("vertices"))
    triangles_elem = mesh_elem.find(_qname_core("triangles"))

    vertices = np.empty((0, 3), dtype=np.float32)
    if vertices_elem is not None:
        vertices = np.fromiter(
            (float(v.get(axis, "0")) for v in vertices_elem for axis in ("x", "y", "z")),
            dtype=np.float32, count=len(vertices_elem) * 3,
        ).reshape((-1, 3))
    faces = np.empty((0, 3), dtype=np.uint32)
    if triangles_elem is not None:
        faces = np.fromiter(
            (int(t.get(axis, "0")) for t in triangles_elem for axis in ("v1", "v2", "v3")),
            dtype=np.uint32, count=len(triangles_elem) * 3,
        ).reshape((-1, 3))
    return vertices, faces


def _n3mf_transform(n3mf: Any, values: Sequence[float]) -> Any:
    transform = n3mf.Transform()
    transform.m = [float(value) for value in values]
    return transform


def _map_base_material_id(
    source_id: str | None, ids_by_source: dict[str, int]
) -> int | None:
    if source_id is None:
        return None
    mapped_id = ids_by_source.get(source_id)
    if mapped_id is None:
        raise MergedWriteError(f"Source material resource {source_id} is missing")
    return mapped_id


def _transformed_assembly_bbox(
    assembly: _SourceAssembly, transform: Sequence[float],
) -> list[float]:
    corners = np.asarray([
        (x, y, z)
        for x in (assembly.min_x, assembly.max_x)
        for y in (assembly.min_y, assembly.max_y)
        for z in (assembly.min_z, assembly.max_z)
    ], dtype=np.float64)
    # 3MF stores the 3x3 linear transform followed by its translation row.
    matrix = np.asarray(transform, dtype=np.float64)
    corners = corners @ matrix[:9].reshape(3, 3) + matrix[9:12]
    return [
        float(corners[:, 0].min()), float(corners[:, 1].min()),
        float(corners[:, 0].max()), float(corners[:, 1].max()),
    ]


def _infer_printer_id_from_settings(
    settings: dict[str, Any], *, slicer: str, nozzle_size: object,
) -> str:
    """Resolve a Lumina printer only from exact registry source identity."""

    from config import format_native_nozzle_size, get_printer_profile, list_printer_profiles
    from core.machine_registry import (
        _registry_printer_slug, load_machine_registry, resolve_machine_registry_root,
    )

    source_name = str(settings.get("printer_settings_id") or "").strip()
    nozzle = format_native_nozzle_size(nozzle_size)
    if not source_name or not nozzle:
        raise MergedWriteError(
            "Merged export needs an explicit printer selection because its source "
            "project has no exact machine/nozzle identity"
        )
    registry_path = resolve_machine_registry_root() / "registry.json"
    registry = load_machine_registry(registry_path)
    devices = [
        profile for profile in registry.devices_by_id.values()
        if profile.supported
        and profile.slicer_id == slicer
        and profile.nozzle_size == nozzle
        and profile.source_profile_name == source_name
    ]
    identities = {
        (profile.display_name.casefold(), profile.brand.casefold())
        for profile in devices
    }
    # The config resolver also knows SDK catalog devices absent from the static
    # product list. Resolve only exact registry identities, never a name guess.
    candidates = list_printer_profiles() + [
        get_printer_profile(_registry_printer_slug(device.display_name))
        for device in devices
    ]
    matches = {
        profile.id: profile for profile in candidates
        if (profile.display_name.casefold(), profile.brand.casefold()) in identities
        and nozzle in profile.supported_nozzle_sizes
    }
    if len(matches) != 1:
        raise MergedWriteError(
            "Merged export could not map native machine identity exactly: "
            f"{slicer}/{source_name}/{nozzle} (Lumina matches: {len(matches)})"
        )
    return next(iter(matches))


def _resolve_merged_wipe_tower_placement(
    items: Sequence[MergedItem],
    assemblies: Sequence[_SourceAssembly],
    layout: Mapping[str, Any],
    *,
    enable_wipe_tower_auto_placement: bool,
    printer_id: str,
    slicer: str,
    nozzle_size: str,
    build_transforms: Sequence[Sequence[float]] | None = None,
) -> tuple[WipeTowerPlacementResult | None, tuple[float, float]]:
    """Solve one tower layout around the complete merged model group."""

    from core.wipe_tower_placement import Rect, solve_wipe_tower_placement

    if not enable_wipe_tower_auto_placement:
        return None, (0.0, 0.0)
    if build_transforms is None:
        model_bounds = Rect(
            min(item.tx_mm for item in items),
            min(item.ty_mm for item in items),
            max(
                item.tx_mm + assembly.max_x - assembly.min_x
                for item, assembly in zip(items, assemblies)
            ),
            max(
                item.ty_mm + assembly.max_y - assembly.min_y
                for item, assembly in zip(items, assemblies)
            ),
        )
        model_height = max(
            assembly.max_z - assembly.min_z for assembly in assemblies
        )
        model_translation_locked = True
    else:
        model_bounds = Rect(
            min(
                assembly.min_x + float(transform[9])
                for assembly, transform in zip(assemblies, build_transforms)
            ),
            min(
                assembly.min_y + float(transform[10])
                for assembly, transform in zip(assemblies, build_transforms)
            ),
            max(
                assembly.max_x + float(transform[9])
                for assembly, transform in zip(assemblies, build_transforms)
            ),
            max(
                assembly.max_y + float(transform[10])
                for assembly, transform in zip(assemblies, build_transforms)
            ),
        )
        model_height = max(assembly.max_z for assembly in assemblies) - min(
            assembly.min_z for assembly in assemblies
        )
        model_translation_locked = False
    request = build_wipe_tower_placement_request(
        layout,
        model_bounds=model_bounds,
        model_height=model_height,
        material_count=len({
            slot.slot_id
            for item, assembly in zip(items, assemblies)
            for index, slot in enumerate(item.slots)
            if "used_slot_indices" not in assembly.source_metadata
            or (slot.source_slot_index if slot.source_slot_index is not None else index)
            in assembly.source_metadata["used_slot_indices"]
        }),
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size=nozzle_size,
    )
    if request is None:
        placement = None
        translation = (0.0, 0.0)
    else:
        request = replace(request, model_translation_locked=model_translation_locked)
        placement = solve_wipe_tower_placement(request)
        translation = (
            placement.model_translation if placement.placement_available
            else (0.0, 0.0)
        )
    return placement, translation


# ---------------------------------------------------------------------------
# MergedBambu3MFWriter — multi-object merged 3MF writer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _MergedExportProject:
    """The composed project and final, possibly translated, source placements."""

    settings: dict[str, Any]
    composition: ProjectComposition
    layout: ProjectLayout
    items: Sequence[MergedItem]
    build_transforms: Sequence[Sequence[float]] | None
    placement: WipeTowerPlacementResult | None
    printer_id: str
    slicer: str
    source_slot_mappings: dict[str, dict[int, int]]

    @property
    def core_layout(self) -> bool:
        return self.composition["metadata_defaults"].get("geometry_layout") == "core"


@dataclass(frozen=True)
class _BaseMaterialMapping:
    """One source's base-material group and optional palette-index projection."""

    group_ids: dict[str, int]
    indexes: dict[str, dict[int, int]] | None

    def property_index(self, group_id: str | None, value: str | int) -> int:
        index = int(value)
        if self.indexes is None:
            return index
        try:
            if group_id is None:
                raise KeyError(group_id)
            return self.indexes[group_id][index]
        except KeyError as exc:
            raise MergedWriteError(
                "Source base material is absent from the selected palette"
            ) from exc


@dataclass(frozen=True)
class _MergedGeometry:
    """Queued source assemblies and the matching FatCat model descriptions."""

    models: list[MergedModelInput]
    summary_objects: list[PlateSummaryObject]
    assembly_ids: dict[int, int]


class MergedSlicer3MFWriter:
    """Merge source geometry and tuning into one native slicer project.

    将各源工程的几何和工艺合并为一个目标切片软件原生工程。

    FatCat merges metadata, material identities and object settings. This writer
    reuses source meshes/transforms and follows FatCat's core/Production layout
    policy, then asks Neroued to write one archive. ``MergedBambu3MFWriter`` is
    an alias of this class; public calls remain compatible.
    FatCat 合并元数据、耗材身份和局部设置；此 writer 复用源网格及变换，
    按 FatCat 的布局规则调用 Neroued 单次写包，保留现有类名和公开签名。
    """

    def write(
        self,
        items: Sequence[MergedItem],
        output_path: Path,
        *,
        plate_width_mm: float,
        plate_depth_mm: float,
        enable_wipe_tower_auto_placement: bool = True,
        metadata_target: MetadataTarget | None = None,
        printer_id: str | None = None,
        nozzle_size: str | None = None,
        device_profile_id: str | None = None,
        build_plate_id: str | None = None,
        external_spool_material: str | None = None,
    ) -> None:
        """Write merged 3MF to ``output_path``.

        Args:
            items: Sequence of MergedItem objects to merge.
            output_path: Destination path for the merged 3MF file.
            plate_width_mm: Plate X dimension (mm); compatibility input.
                Native hardware comes from the source project.
                兼容输入；原生硬件来自源项目。
            plate_depth_mm: Plate Y dimension (mm); compatibility input.
                打印板 Y 尺寸（毫米），保留为兼容输入。
            enable_wipe_tower_auto_placement: Whether to solve and apply one
                wipe-tower layout for the full merged group. (是否为整个合并模型组
                求解并应用擦料塔自动布局。)
            metadata_target: Explicit Fat Cat target for the selected slicer.
                所选切片软件的明确 Fat Cat 目标。
            printer_id: Explicit Lumina printer profile used for layout.
                (布局使用的 Lumina 打印机配置。)
            nozzle_size: Explicit target nozzle size used for layout.
                (布局使用的目标喷嘴尺寸。)
            device_profile_id: Explicit slicer device profile used for layout.
                (布局使用的明确切片器设备配置。)
            build_plate_id: Explicit native build plate used for layout.
                (布局使用的明确原生打印板。)

        Raises:
            MergedWriteError: items is empty, source_3mf_path parse fails,
                OPC packaging fails, slots validation fails, disk IO fails.
        """
        if not items:
            raise MergedWriteError("items must not be empty")

        # Validate all items' slots upfront.
        for idx, item in enumerate(items):
            try:
                _validate_slots(item.slots)
            except MergedWriteError as exc:
                raise MergedWriteError(
                    f"MergedItem[{idx}] slots validation failed: {exc}"
                ) from exc

        # Parse all source 3MFs.
        assemblies: list[_SourceAssembly] = []
        for idx, item in enumerate(items):
            assemblies.append(_parse_source_assembly(
                idx, item, metadata_target=metadata_target,
            ))

        if metadata_target is None:
            from utils.fatcat_metadata import select_metadata_target

            source_layout = assemblies[0].source_metadata["layout"]
            source_nozzles = source_layout["nozzle_diameters"]
            source_nozzle = nozzle_size or (source_nozzles[0] if source_nozzles else None)
            source_slicer = assemblies[0].source_metadata["source_slicer"] or "BambuStudio"
            source_printer = printer_id or _infer_printer_id_from_settings(
                source_layout, slicer=source_slicer, nozzle_size=source_nozzle,
            )
            metadata_target = select_metadata_target(
                slicer=source_slicer, printer_id=source_printer, nozzle_size=source_nozzle,
                device_profile_id=device_profile_id, build_plate_id=build_plate_id,
            )
            if build_plate_id is None:
                metadata_target = replace(metadata_target, build_plate_uid="")
        try:
            self._write_fatcat_opc(
                items, assemblies, output_path,
                enable_wipe_tower_auto_placement, metadata_target=metadata_target,
                external_spool_material=external_spool_material,
                printer_id=printer_id, nozzle_size=nozzle_size,
                device_profile_id=device_profile_id, build_plate_id=build_plate_id,
            )
        except MergedWriteError:
            raise
        except (OSError, ET.ParseError) as exc:
            raise MergedWriteError(
                f"Failed to write merged 3MF to {output_path}: {exc}"
            ) from exc

    def write_puzzle(
        self,
        items: Sequence[MergedItem],
        output_path: Path,
        *,
        build_transforms: Sequence[Sequence[float]],
        overview_png_bytes: bytes | None,
        metadata_target: MetadataTarget,
        printer_id: str,
        nozzle_size: str,
        device_profile_id: str | None,
        build_plate_id: str | None,
        enable_wipe_tower_auto_placement: bool,
        source_materials: Sequence[Mapping[str, object]] | None = None,
        external_spool_material: str | None = None,
    ) -> None:
        """Write puzzle pieces through Fat Cat and one neroued package build.

        通过 Fat Cat 和一次 neroued 写包输出拼图块。

        Args:
            items: Source piece 3MFs and their material slots.
                拼图源 3MF 和对应材料槽位。
            output_path: Destination 3MF path. (输出 3MF 路径)
            build_transforms: Lumina-computed root transforms per piece.
                Lumina 为每块计算的根变换。
            overview_png_bytes: Combined puzzle overview image. (拼图总览图字节)
            metadata_target: Explicit Fat Cat target. (明确的 Fat Cat 目标)
            printer_id: Selected printer profile. (所选打印机配置)
            nozzle_size: Selected nozzle size. (所选喷嘴尺寸)
            device_profile_id: Explicit slicer device profile.
                明确的切片器设备配置。
            build_plate_id: Explicit native build plate. (明确的原生打印板)
            enable_wipe_tower_auto_placement: Whether tower placement is enabled.
                是否启用擦料塔布局。
            source_materials: Optional ordered full palette for sparse sources.
                稀疏源项目可选的完整有序调色板。

        Raises:
            MergedWriteError: If the input count differs or a source cannot be parsed.
                输入数量不匹配或源文件无法解析时抛出。
        """
        if not items:
            raise MergedWriteError("items must not be empty")
        if len(items) != len(build_transforms):
            raise MergedWriteError(
                "Puzzle items and build transforms must have equal length"
            )

        assemblies = []
        for index, item in enumerate(items):
            _validate_slots(item.slots)
            assemblies.append(_parse_source_assembly(
                index, item, metadata_target=metadata_target,
            ))

        self._write_fatcat_opc(
            items,
            assemblies,
            output_path,
            enable_wipe_tower_auto_placement,
            metadata_target=metadata_target,
            printer_id=printer_id,
            nozzle_size=nozzle_size,
            device_profile_id=device_profile_id,
            build_plate_id=build_plate_id,
            build_transforms=build_transforms,
            external_spool_material=external_spool_material,
            source_materials=source_materials,
            resource_overrides={
                "plate_main": overview_png_bytes,
                "plate_no_light": overview_png_bytes,
                "top_preview": overview_png_bytes,
                "pick_preview": overview_png_bytes,
            } if overview_png_bytes is not None else None,
        )

    def _write_fatcat_opc(
        self,
        items: Sequence[MergedItem],
        assemblies: list[_SourceAssembly],
        output_path: Path,
        enable_wipe_tower_auto_placement: bool,
        *,
        metadata_target: MetadataTarget,
        printer_id: str | None,
        nozzle_size: str | None,
        device_profile_id: str | None,
        build_plate_id: str | None,
        build_transforms: Sequence[Sequence[float]] | None = None,
        resource_overrides: Mapping[str, bytes] | None = None,
        source_materials: Sequence[Mapping[str, object]] | None = None,
        external_spool_material: str | None = None,
    ) -> None:
        from fatcat_metadata_neroued import apply_metadata_components, apply_root_model_metadata

        project = self._prepare_export_project(
            items, assemblies, metadata_target, source_materials,
            printer_id=printer_id, nozzle_size=nozzle_size,
            device_profile_id=device_profile_id, build_plate_id=build_plate_id,
            enable_wipe_tower_auto_placement=enable_wipe_tower_auto_placement,
            build_transforms=build_transforms,
        )
        builder = self._create_document_builder(core_layout=project.core_layout)
        geometry = self._queue_merged_geometry(builder, assemblies, project, source_materials)
        metadata_request = self._build_merged_metadata_request(
            metadata_target, assemblies, output_path, project, geometry,
            enable_wipe_tower_auto_placement=enable_wipe_tower_auto_placement,
        )
        if external_spool_material is not None:
            slots = project.composition["merged_slots"]
            metadata_request["plate"]["filament_maps"] = external_spool_filament_map(
                external_spool_material, [slot["slot_name"] for slot in slots],
                slicer_id=metadata_target.slicer_id, machine_uid=metadata_target.machine_uid,
            )
        resource_bytes = self._build_resource_bytes(metadata_target, resource_overrides)
        metadata_request["resource_roles"] = list(resource_bytes)
        metadata_result = compose_model_metadata(project.settings, metadata_request)
        apply_root_model_metadata(builder, metadata_result["root_model"])
        apply_metadata_components(builder, metadata_result, resource_bytes)
        self._add_build_items(builder, metadata_result, geometry, assemblies, project.core_layout)
        self._write_document(builder, output_path)

    @staticmethod
    def _compose_project(
        items: Sequence[MergedItem], assemblies: Sequence[_SourceAssembly],
        metadata_target: MetadataTarget, source_materials: Sequence[Mapping[str, object]] | None,
    ) -> ProjectComposition:
        """Compose actual source projects and their material selections once."""
        project_request = build_merged_project_settings_request(
            target=metadata_target,
            sources=[
                (str(index), assembly.project_settings, item.slots)
                for index, (assembly, item) in enumerate(zip(assemblies, items))
            ],
        )
        if source_materials:
            project_request.update({
                "source_materials": [dict(material) for material in source_materials],
                "machine_uid": metadata_target.machine_uid,
                "nozzle_uid": metadata_target.nozzle_uid,
            })
        return compose_project_settings(assemblies[0].project_settings, project_request)

    def _prepare_export_project(
        self, items: Sequence[MergedItem], assemblies: Sequence[_SourceAssembly],
        metadata_target: MetadataTarget, source_materials: Sequence[Mapping[str, object]] | None,
        *, printer_id: str | None, nozzle_size: str | None,
        device_profile_id: str | None, build_plate_id: str | None,
        enable_wipe_tower_auto_placement: bool,
        build_transforms: Sequence[Sequence[float]] | None,
    ) -> _MergedExportProject:
        """Resolve hardware and apply one layout to the composed source project."""
        from config import normalize_slicer_software_id

        project_result = self._compose_project(items, assemblies, metadata_target, source_materials)
        final_project = json.loads(project_result["project_settings_json"])
        resolved_slicer = normalize_slicer_software_id(metadata_target.slicer_id)
        layout = read_project_layout(
            {**DEFAULT_EXPORT_SETTINGS, **final_project},
            slicer_id=resolved_slicer,
        )
        source_layout = assemblies[0].source_metadata["layout"]
        source_nozzles = source_layout["nozzle_diameters"]
        source_nozzle = nozzle_size or (source_nozzles[0] if source_nozzles else None)
        resolved_printer_id = printer_id or _infer_printer_id_from_settings(
            source_layout,
            slicer=resolved_slicer,
            nozzle_size=source_nozzle,
        )
        resolved_nozzle_size, _, _ = resolve_export_device(
            printer_id=resolved_printer_id,
            slicer=resolved_slicer,
            nozzle_size=source_nozzle,
            device_profile_id=str(device_profile_id or "").strip() or None,
            build_plate_id=str(build_plate_id or "").strip() or None,
        )
        placement, group_translation = _resolve_merged_wipe_tower_placement(
            items,
            assemblies,
            layout,
            enable_wipe_tower_auto_placement=enable_wipe_tower_auto_placement,
            printer_id=resolved_printer_id,
            slicer=resolved_slicer,
            nozzle_size=resolved_nozzle_size,
            build_transforms=build_transforms,
        )
        items, build_transforms = self._translate_sources(items, build_transforms, group_translation)
        tower_changes = (
            build_wipe_tower_patch_settings(placement)
            if enable_wipe_tower_auto_placement else {}
        )
        if tower_changes:
            final_project = patch_wipe_tower(
                final_project, tower_changes,
                project_result["wipe_tower_dialect"],
            )

        source_mappings = {
            mapping["source_id"]: {
                slot["source_slot_index"]: slot["output_slot_index"]
                for slot in mapping["slots"]
            }
            for mapping in project_result["source_slot_mappings"]
        }
        return _MergedExportProject(
            final_project, project_result, layout, items, build_transforms, placement,
            resolved_printer_id, resolved_slicer, source_mappings,
        )

    @staticmethod
    def _translate_sources(
        items: Sequence[MergedItem], build_transforms: Sequence[Sequence[float]] | None,
        group_translation: tuple[float, float],
    ) -> tuple[Sequence[MergedItem], Sequence[Sequence[float]] | None]:
        """Translate either batch minima or explicit puzzle transforms, preserving inputs."""
        if build_transforms is None and group_translation != (0.0, 0.0):
            items = tuple(
                replace(
                    item,
                    tx_mm=item.tx_mm + group_translation[0],
                    ty_mm=item.ty_mm + group_translation[1],
                )
                for item in items
            )
        elif build_transforms is not None and group_translation != (0.0, 0.0):
            translated_transforms = []
            for transform in build_transforms:
                values = [float(value) for value in transform]
                values[9] += group_translation[0]
                values[10] += group_translation[1]
                translated_transforms.append(values)
            build_transforms = translated_transforms
        return items, build_transforms

    @staticmethod
    def _create_document_builder(*, core_layout: bool) -> n3mf.DocumentBuilder:
        """Create the geometry builder for the selected layout dialect."""
        import neroued_3mf as n3mf

        builder = n3mf.DocumentBuilder()
        builder.set_unit(n3mf.Unit.Millimeter)
        builder.set_language("en-US")
        if not core_layout:
            builder.enable_production()
            builder.set_production_build_uuid(str(uuid.uuid4()))

        return builder

    def _queue_merged_geometry(
        self, builder: n3mf.DocumentBuilder, assemblies: Sequence[_SourceAssembly],
        project: _MergedExportProject, source_materials: Sequence[Mapping[str, object]] | None,
    ) -> _MergedGeometry:
        """Queue source geometry and keep its IDs paired with model descriptions."""
        material_mappings = self._queue_material_groups(builder, assemblies, source_materials)
        metadata_models: list[MergedModelInput] = []
        summary_objects: list[PlateSummaryObject] = []
        assembly_ids: dict[int, int] = {}
        for model_index, (item, assembly) in enumerate(zip(project.items, assemblies), start=1):
            mesh_ids, face_count = self._queue_source_meshes(
                builder, item, assembly, material_mappings[model_index - 1], project.core_layout,
            )
            source_transform = (
                project.build_transforms[model_index - 1]
                if project.build_transforms is not None else None
            )
            build_transform = self._source_build_transform(item, assembly, source_transform)
            group_id = self._add_source_group(
                builder, item, assembly, mesh_ids, model_index, project.core_layout,
            )
            assembly_ids[model_index] = group_id
            metadata_models.append(self._build_source_model_input(
                item, assembly, model_index, group_id, mesh_ids, face_count, build_transform,
                project.source_slot_mappings[str(model_index - 1)],
                len(project.composition["merged_slots"]),
            ))
            summary_objects.append({
                "model_index": model_index,
                "name": item.source_filename or f"object_{model_index}",
                "bbox": _transformed_assembly_bbox(assembly, build_transform),
            })
        return _MergedGeometry(metadata_models, summary_objects, assembly_ids)

    @staticmethod
    def _queue_material_groups(
        builder: n3mf.DocumentBuilder, assemblies: Sequence[_SourceAssembly],
        source_materials: Sequence[Mapping[str, object]] | None,
    ) -> list[_BaseMaterialMapping]:
        """Map each source base-material group onto the selected output palette."""
        import neroued_3mf as n3mf

        mappings: list[_BaseMaterialMapping] = []
        global_material_group = None
        palette_index = {}
        if source_materials:
            palette_index = {str(material["name"]): index for index, material in enumerate(source_materials)}
            global_material_group = builder.add_base_material_group([
                n3mf.BaseMaterial(str(material["name"]), n3mf.Color.from_hex(str(material["colour"])))
                for material in source_materials
            ])
        for assembly in assemblies:
            ids_by_source: dict[str, int] = {}
            indexes_by_source: dict[str, dict[int, int]] = {}
            for group in assembly.base_material_groups:
                source_group_id = group.get("id")
                materials = [
                    n3mf.BaseMaterial(
                        material.get("name") or "",
                        n3mf.Color.from_hex(
                            material.get("displaycolor") or "#FFFFFFFF"
                        ),
                    )
                    for material in group.findall(_qname_core("base"))
                ]
                target_group_id = (global_material_group if global_material_group is not None
                                   else builder.add_base_material_group(materials))
                if source_group_id is not None:
                    ids_by_source[source_group_id] = target_group_id
                    if global_material_group is not None:
                        indexes_by_source[source_group_id] = {
                            index: palette_index[material.get("name") or ""]
                            for index, material in enumerate(group.findall(_qname_core("base")))
                            if (material.get("name") or "") in palette_index
                        }
            mappings.append(_BaseMaterialMapping(
                ids_by_source, indexes_by_source if global_material_group is not None else None,
            ))

        return mappings

    @staticmethod
    def _queue_source_meshes(
        builder: n3mf.DocumentBuilder, item: MergedItem, assembly: _SourceAssembly,
        material_mapping: _BaseMaterialMapping, core_layout: bool,
    ) -> tuple[list[int], int]:
        """Preserve one source's meshes, material properties and component identity."""
        import neroued_3mf as n3mf

        mesh_ids: list[int] = [0] * len(assembly.meshes)
        face_count = 0
        for mesh_index, source_mesh, source_object in _iter_source_meshes(item, assembly):
            vertices, faces = _extract_mesh_arrays(source_object)
            face_count += int(faces.shape[0])
            mesh = n3mf.Mesh.from_arrays(vertices, faces)
            source_pid = source_object.get("pid")
            source_pindex = source_object.get("pindex")
            target_pid = _map_base_material_id(
                source_pid, material_mapping.group_ids
            )
            triangle_elements = source_object.findall(
                f"{_qname_core('mesh')}/{_qname_core('triangles')}/"
                f"{_qname_core('triangle')}"
            )
            if any(
                any(name in triangle.attrib for name in ("pid", "p1", "p2", "p3"))
                for triangle in triangle_elements
            ):
                default_index = int(source_pindex or "0")
                mesh.triangle_properties = [
                    n3mf.TriangleProperty(
                        _map_base_material_id(
                            triangle.get("pid") or source_pid,
                            material_mapping.group_ids,
                        )
                        or 0,
                        material_mapping.property_index(
                            triangle.get("pid") or source_pid,
                            triangle.get("p1") or default_index,
                        ),
                        material_mapping.property_index(
                            triangle.get("pid") or source_pid,
                            triangle.get("p2") or default_index,
                        ),
                        material_mapping.property_index(
                            triangle.get("pid") or source_pid,
                            triangle.get("p3") or default_index,
                        ),
                    )
                    for triangle in triangle_elements
                ]

            source_name = source_object.get("name")
            if not source_name and mesh_index < len(item.slots):
                source_name = item.slots[mesh_index].slot_name
            mesh_id = builder.add_mesh_object(
                source_name or f"mesh_{mesh_index}",
                mesh,
                pid=target_pid,
                pindex=(
                    material_mapping.property_index(source_pid, source_pindex)
                    if source_pindex is not None else None
                ),
            )
            mesh_ids[mesh_index] = mesh_id
            if source_object.get("partnumber"):
                builder.set_part_number(mesh_id, source_object.get("partnumber"))
            for metadata in source_mesh.metadata:
                builder.add_object_metadata(
                    mesh_id, metadata["name"], metadata["value"], metadata["type"],
                )
            object_uuid = source_object.get(_qname_prod("UUID"))
            if object_uuid and not core_layout:
                builder.set_object_uuid(mesh_id, object_uuid)
            if not core_layout and mesh_index < len(assembly.component_transforms):
                builder.set_component_transform(
                    mesh_id,
                    _n3mf_transform(
                        n3mf,
                        _parse_transform_matrix(
                            assembly.component_transforms[mesh_index]
                        ),
                    ),
                )
            if not core_layout and mesh_index < len(assembly.component_uuids):
                component_uuid = assembly.component_uuids[mesh_index]
                builder.set_component_uuid(
                    mesh_id, component_uuid or str(uuid.uuid4())
                )
            # add_mesh_object owns its native copy. Release Python buffers
            # before the iterator begins parsing the next source mesh.
            del vertices, faces, triangle_elements, mesh
        return mesh_ids, face_count

    @staticmethod
    def _source_build_transform(
        item: MergedItem, assembly: _SourceAssembly, source_transform: Sequence[float] | None,
    ) -> list[float]:
        """Select the computed batch placement or the explicit puzzle transform."""
        if source_transform is None:
            dx = item.tx_mm - assembly.min_x
            dy = item.ty_mm - assembly.min_y
            dz = assembly.source_build_transform[11]
            build_transform = [
                1.0, 0.0, 0.0,
                0.0, 1.0, 0.0,
                0.0, 0.0, 1.0,
                dx, dy, dz,
            ]
        else:
            build_transform = [
                float(value)
                for value in source_transform
            ]
            dx, dy, dz = build_transform[9:12]
        return build_transform

    @staticmethod
    def _add_source_group(
        builder: n3mf.DocumentBuilder, item: MergedItem, assembly: _SourceAssembly,
        mesh_ids: list[int], model_index: int, core_layout: bool,
    ) -> int:
        """Preserve source components in a core assembly or a Production group."""
        import neroued_3mf as n3mf

        group_name = item.source_filename or f"object_{model_index}"
        if core_layout:
            group_id = builder.add_component_object(group_name, [
                n3mf.Component(mesh_id, _n3mf_transform(
                    n3mf, _parse_transform_matrix(assembly.component_transforms[index]),
                ))
                for index, mesh_id in enumerate(mesh_ids)
            ])
        else:
            group_id = builder.add_production_group(
                group_name, mesh_ids, assembly.source_assembly_uuid or str(uuid.uuid4()),
            )
        return group_id

    @staticmethod
    def _build_source_model_input(
        item: MergedItem, assembly: _SourceAssembly, model_index: int, group_id: int,
        mesh_ids: list[int], face_count: int, build_transform: list[float],
        source_mapping: dict[int, int], output_slot_count: int,
    ) -> MergedModelInput:
        """Describe source identities, slot projection and local Z ranges for FatCat."""
        dx, dy, dz = build_transform[9:12]
        source_slot_count = assembly.source_metadata["project_filament_count"]
        source_slot_output_indexes = [
            source_mapping.get(index, output_slot_count)
            for index in range(source_slot_count)
        ]
        source_model_settings = assembly.metadata_parts[
            "Metadata/model_settings.config"
        ].decode("utf-8")
        model_request: MergedModelInput = {
            "model_index": model_index,
            "assembly_id": group_id,
            "instance_id": "0",
            "identify_id": str(model_index),
            "source_assembly_id": assembly.source_assembly_id,
            "source_model_index": assembly.source_model_index,
            "source_model_settings_xml": source_model_settings,
            "face_count": face_count,
            "parts": [
                {
                    "part_id": mesh_id,
                    "source_part_id": source_mesh.original_id,
                }
                for mesh_id, source_mesh in zip(mesh_ids, assembly.meshes)
            ],
            "source_slot_output_indexes": source_slot_output_indexes,
            "output_slot_count": output_slot_count,
            "default_slot_output_index": source_mapping.get(0, min(source_mapping.values())),
            "source_slots": [
                {
                    "slot_id": slot.slot_id,
                    "slot_name": slot.slot_name,
                    "preview_color": slot.preview_color,
                    "material_id": slot.material_id,
                }
                for slot in item.slots
            ],
            "source_root_metadata": assembly.root_metadata,
            "transform": build_transform,
            "offset_mm": [dx, dy, dz],
        }
        layer_ranges = assembly.metadata_parts.get(
            "Metadata/layer_config_ranges.xml"
        )
        if layer_ranges is not None:
            model_request["source_layer_config_ranges_xml"] = (
                layer_ranges.decode("utf-8")
            )
        return model_request

    @staticmethod
    def _build_merged_metadata_request(
        metadata_target: MetadataTarget, assemblies: Sequence[_SourceAssembly],
        output_path: Path, project: _MergedExportProject, geometry: _MergedGeometry,
        *, enable_wipe_tower_auto_placement: bool,
    ) -> ModelMetadataRequest:
        """Provide the final assembly and placement facts to the metadata composer."""
        placement_payload = build_wipe_tower_placement_metadata_payload(
            project.placement,
            enabled=enable_wipe_tower_auto_placement,
            output_path=str(output_path),
            printer_id=project.printer_id,
            slicer=project.slicer,
        )
        metadata_request = build_merged_model_metadata_request(
            target=metadata_target,
            objects=geometry.models,
            bed_type=project.composition["metadata_defaults"]["plate_value"],
            wipe_tower_placement=placement_payload,
            source_slice_info_xml=(
                assemblies[0].metadata_parts["Metadata/slice_info.config"].decode(
                    "utf-8"
                )
                if "Metadata/slice_info.config" in assemblies[0].metadata_parts
                else None
            ),
        )
        metadata_request["output_options"] = {
            "emit_lumina_merged_slots_json": True,
        }
        if project.composition["metadata_defaults"]["plate_summary"]:
            metadata_request["component_inputs"]["plate_summary"] = {
                "bbox_all": [
                    min(obj["bbox"][0] for obj in geometry.summary_objects),
                    min(obj["bbox"][1] for obj in geometry.summary_objects),
                    max(obj["bbox"][2] for obj in geometry.summary_objects),
                    max(obj["bbox"][3] for obj in geometry.summary_objects),
                ],
                "objects": geometry.summary_objects,
                "filament_colors": [slot["preview_color"] for slot in project.composition["merged_slots"]],
                "layer_height": project.layout["layer_height"],
                "nozzle_diameter": project.layout["nozzle_diameters"][0],
                "bed_type": project.composition["metadata_defaults"]["sidecar_bed_value"],
            }

        return metadata_request

    @staticmethod
    def _build_resource_bytes(
        metadata_target: MetadataTarget, resource_overrides: Mapping[str, bytes] | None,
    ) -> dict[str, bytes]:
        """Build previews from the final combined geometry rather than old sources."""
        from utils.bambu_3mf_cover import CoverThumbnailBuilder, build_plate_small_preview

        # Source previews describe their old geometry/layout, even for one input.
        resource_bytes: dict[str, bytes] = {}
        if resource_overrides:
            resource_bytes.update(resource_overrides)
        if "plate_main" in resource_bytes:
            cover = CoverThumbnailBuilder().build(resource_bytes["plate_main"])
            resource_bytes.update({
                "thumbnail_package": cover.thumbnail_3mf,
                "thumbnail_middle": cover.thumbnail_middle,
                "thumbnail_small": cover.thumbnail_small,
            })
            if "plate_small" in metadata_resource_specs(metadata_target.slicer_id):
                resource_bytes["plate_small"] = build_plate_small_preview(
                    resource_bytes["plate_main"]
                )
        return resource_bytes

    @staticmethod
    def _add_build_items(
        builder: n3mf.DocumentBuilder, metadata_result: ModelComposition,
        geometry: _MergedGeometry, assemblies: Sequence[_SourceAssembly], core_layout: bool,
    ) -> None:
        """Apply FatCat's final build transforms to the queued assemblies."""
        import neroued_3mf as n3mf

        for build_item in metadata_result["build_items"]:
            model_index = build_item["model_index"]
            properties = build_item["properties"]
            builder.add_build_item(
                geometry.assembly_ids[model_index],
                _n3mf_transform(
                    n3mf,
                    [float(value) for value in build_item["transform"].split()],
                ),
                uuid=(
                    "" if core_layout else (
                        assemblies[model_index - 1].source_build_item_uuid
                        or str(uuid.uuid4())
                    )
                ),
                attributes=properties,
            )

    @staticmethod
    def _write_document(builder: n3mf.DocumentBuilder, output_path: Path) -> None:
        """Write the assembled document once at the existing precision."""
        import neroued_3mf as n3mf

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        document = builder.build()
        options = n3mf.WriteOptions()
        options.vertex_precision = 9
        options.compact_xml = True
        from utils.threemf_io import write_3mf_document

        write_3mf_document(output_path, document, options)


MergedBambu3MFWriter = MergedSlicer3MFWriter
