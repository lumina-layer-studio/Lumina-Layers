"""SVG/vector GLB preview exporters.

This module keeps vector GLB preview export separate from the large
``vector_branch`` orchestration file. V2 is the default exporter and V1
remains an explicit fallback selected by ``LUMINA_VECTOR_GLB_KERNEL=v1``.

SVG/vector GLB 预览导出模块。V2 是默认导出器；需要锁定旧路径时可通过
``LUMINA_VECTOR_GLB_KERNEL=v1`` 显式回退 V1。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import gc
import json
import os
import time
import traceback
from typing import Literal

import numpy as np
import trimesh
from shapely.affinity import scale as shapely_scale
from shapely.affinity import translate as shapely_translate
from shapely.geometry import MultiPolygon, Polygon, shape as shapely_shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid
from trimesh.visual.material import PBRMaterial

from api.structured_logging import get_logger
from config import PrinterConfig
from core.vector_engine import (
    _load_vector_parse_clip_cache_artifact_by_provenance,
    _rasterize_geometry_roi_mask,
)
from core.pipeline.s11_glb_preview import (
    PREVIEW_CANVAS_BOUNDS_NODE_NAME,
    _build_color_extruded_mesh_v2,
    _build_preview_canvas_bounds_mesh,
)
from core.vector_structure import resolve_structure_plan, _prepare_footprint


log = get_logger(__name__)

_VECTOR_GLB_KERNEL_ENV_VAR = "LUMINA_VECTOR_GLB_KERNEL"
_GLTF_UINT16_COMPONENT_TYPE = 5123
_GLTF_UINT32_COMPONENT_TYPE = 5125
_GLTF_FLOAT_COMPONENT_TYPE = 5126
_GLTF_UINT16_MAX_INDEX = 65535
_GLTF_QUANTIZATION_EXTENSION = "KHR_mesh_quantization"
_V2_UINT16_CHUNK_VERTEX_LIMIT = _GLTF_UINT16_MAX_INDEX + 1
_V2_VECTOR_COMPONENT_COMPOSE_CHUNK_SIZE = 64
_VECTOR_QUICK_PREVIEW_MAX_BYTES = 64 * 1024 * 1024
_VECTOR_QUICK_PREVIEW_MAX_SHAPES = 10_000
_VECTOR_QUICK_PREVIEW_MAX_COORDINATES = 4_000_000
_VECTOR_QUICK_PREVIEW_MAX_SIMPLIFY_MM = 0.05
_ANALYTIC_MIN_AREA_MM2 = 1e-12
_ANALYTIC_TOPOLOGY_FALLBACK_PIXELS_PER_MM = 10.0
_ANALYTIC_EXTRUSION_FALLBACK_ERRORS = (
    AttributeError,
    ImportError,
    IndexError,
    OverflowError,
    RuntimeError,
    TypeError,
    ValueError,
)

VectorPreviewRole = Literal["color", "backing", "outline", "auxiliary"]


@dataclass(frozen=True)
class VectorQuickPreviewSourceV1:
    """Validated session-owned geometry for rebuilding a lightweight preview.

    用于重建轻量预览、已经过 provenance 与资源上限校验的会话几何。
    """

    provenance: str
    shape_data: tuple[dict, ...]
    clipped_shapes: tuple[dict, ...]
    silhouette: BaseGeometry
    image_vectorizer_bounds: BaseGeometry | None
    scale_factor: float
    bbox: tuple[float, float, float, float]
    svg_coordinate_domain: object | None = None


def _quick_preview_geometry_coordinate_count(geometry: BaseGeometry) -> int | None:
    if isinstance(geometry, Polygon):
        return len(geometry.exterior.coords) + sum(
            len(ring.coords) for ring in geometry.interiors
        )
    if isinstance(geometry, MultiPolygon):
        total = 0
        for polygon in geometry.geoms:
            count = _quick_preview_geometry_coordinate_count(polygon)
            if count is None:
                return None
            total += count
        return total
    return None


def _validate_quick_preview_geometry(
    geometry: object,
) -> tuple[BaseGeometry, int] | None:
    if not isinstance(geometry, (Polygon, MultiPolygon)):
        return None
    if geometry.is_empty or not geometry.is_valid:
        return None
    try:
        bounds = np.asarray(geometry.bounds, dtype=np.float64)
    except (TypeError, ValueError):
        return None
    if bounds.shape != (4,) or not np.isfinite(bounds).all():
        return None
    coordinate_count = _quick_preview_geometry_coordinate_count(geometry)
    if coordinate_count is None or coordinate_count <= 0:
        return None
    return geometry, coordinate_count


def load_vector_quick_preview_source(
    path: str,
    *,
    expected_provenance: str,
    max_bytes: int = _VECTOR_QUICK_PREVIEW_MAX_BYTES,
    max_shapes: int = _VECTOR_QUICK_PREVIEW_MAX_SHAPES,
    max_coordinates: int = _VECTOR_QUICK_PREVIEW_MAX_COORDINATES,
) -> VectorQuickPreviewSourceV1 | None:
    """Load one bounded Vector preview source with an external identity check.

    ``expected_provenance`` must come from the owning session metadata; the
    artifact's self-declared identity is never accepted on its own.

    从会话持有的 provenance 校验并加载有资源上限的 Vector 预览源；不会仅凭
    工件自报身份接受复用。
    """

    if not path or max_bytes <= 0 or max_shapes <= 0 or max_coordinates <= 0:
        return None
    try:
        if os.path.getsize(path) > int(max_bytes):
            return None
    except OSError:
        return None
    entry = _load_vector_parse_clip_cache_artifact_by_provenance(
        path,
        expected_provenance,
    )
    if entry is None:
        return None

    shape_data = entry.get("shape_data")
    clipped_shapes = entry.get("clipped_shapes")
    if not isinstance(shape_data, list) or not isinstance(clipped_shapes, list):
        return None
    if len(shape_data) + len(clipped_shapes) > int(max_shapes):
        return None

    coordinate_count = 0
    for items, geometry_key in (
        (shape_data, "poly"),
        (clipped_shapes, "geometry"),
    ):
        for item in items:
            if not isinstance(item, dict):
                return None
            validated = _validate_quick_preview_geometry(item.get(geometry_key))
            if validated is None:
                return None
            coordinate_count += validated[1]
            if coordinate_count > int(max_coordinates):
                return None

    silhouette_result = _validate_quick_preview_geometry(entry.get("silhouette"))
    if silhouette_result is None:
        return None
    silhouette, silhouette_coordinates = silhouette_result
    coordinate_count += silhouette_coordinates

    image_bounds = entry.get("image_vectorizer_bounds")
    if image_bounds is not None:
        bounds_result = _validate_quick_preview_geometry(image_bounds)
        if bounds_result is None:
            return None
        image_bounds, bounds_coordinates = bounds_result
        coordinate_count += bounds_coordinates
    if coordinate_count > int(max_coordinates):
        return None

    try:
        scale_factor = float(entry.get("scale_factor"))
        bbox = tuple(float(value) for value in entry.get("bbox"))
    except (TypeError, ValueError):
        return None
    if (
        not np.isfinite(scale_factor)
        or scale_factor <= 0
        or len(bbox) != 4
        or not np.isfinite(np.asarray(bbox, dtype=np.float64)).all()
        or bbox[2] <= 0
        or bbox[3] <= 0
    ):
        return None

    return VectorQuickPreviewSourceV1(
        provenance=expected_provenance,
        shape_data=tuple(dict(item) for item in shape_data),
        clipped_shapes=tuple(dict(item) for item in clipped_shapes),
        silhouette=silhouette,
        image_vectorizer_bounds=image_bounds,
        scale_factor=scale_factor,
        bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
        svg_coordinate_domain=entry.get("svg_coordinate_domain"),
    )


@dataclass(frozen=True)
class VectorPreviewExtrusion:
    """One 2D footprint extrusion in display-space millimetres.

    一段显示坐标系中的 2D footprint + Z 范围挤出描述。
    """

    footprint: BaseGeometry
    z_min: float
    z_max: float
    footprints: tuple[BaseGeometry, ...] = field(default_factory=tuple)
    footprints_validated: bool = False

    def __post_init__(self) -> None:
        if self.footprints:
            object.__setattr__(self, "footprints", tuple(self.footprints))
        else:
            object.__setattr__(self, "footprints", (self.footprint,))


@dataclass(frozen=True)
class VectorPreviewPart:
    """One named GLB preview part consumed by V1 and V2 exporters.

    V1 可以使用 ``fallback_mesh``；V2 优先使用 ``extrusions``。
    """

    source_name: str
    export_name: str
    role: VectorPreviewRole
    rgba: tuple[int, int, int, int]
    is_recolorable: bool
    height_key: str | None = None
    extrusions: tuple[VectorPreviewExtrusion, ...] = field(default_factory=tuple)
    fallback_mesh: trimesh.Trimesh | None = None


def resolve_vector_glb_kernel_choice() -> str:
    """Return the requested SVG GLB kernel.

    Returns:
        ``"rasterio_manifold3d"`` for the default V2 path, or
        ``"trimesh_v1"`` for the explicit V1 fallback path.

    返回当前 SVG GLB kernel 选择：默认 ``rasterio_manifold3d``；显式
    配置 V1 时返回 ``trimesh_v1``。
    """

    raw = (os.environ.get(_VECTOR_GLB_KERNEL_ENV_VAR) or "").strip().lower()
    if raw in {"v1", "trimesh", "trimesh_v1"}:
        return "trimesh_v1"
    if raw in {"", "v2", "rasterio_manifold3d", "rasterio+manifold3d"}:
        return "rasterio_manifold3d"
    log.warning(
        "Unknown LUMINA_VECTOR_GLB_KERNEL value, falling back to V1",
        extra={
            "event": "vector_glb_kernel_unknown_value",
            "value": raw,
            "error_type": "ValueError",
            "fallback_kernel": "trimesh_v1",
        },
    )
    return "trimesh_v1"


def coerce_preview_rgba(value: object) -> tuple[int, int, int, int] | None:
    """Return a safe RGBA tuple, accepting 0-1 or 0-255 input."""

    if value is None:
        return None
    try:
        rgba = np.asarray(value, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return None
    if rgba.size < 3:
        return None
    if rgba.max(initial=0.0) <= 1.0:
        rgba = rgba * 255.0
    if rgba.size < 4:
        rgba = np.concatenate([rgba[:3], np.array([255.0])])
    safe = np.clip(rgba[:4], 0, 255).astype(np.uint8)
    return (int(safe[0]), int(safe[1]), int(safe[2]), int(safe[3]))


def make_vector_glb_export_name(
    *,
    source_name: str,
    role: VectorPreviewRole,
    rgba: tuple[int, int, int, int],
    seen_names: set[str],
) -> str:
    """Return a frontend-compatible GLB geometry name and reserve it."""

    if role == "color":
        base = f"color_{rgba[0]:02x}{rgba[1]:02x}{rgba[2]:02x}"
    elif role == "backing":
        base = "backing_plate"
    elif role == "outline":
        base = "Outline"
    else:
        base = str(source_name or "auxiliary")

    candidate = base
    suffix = 0
    while candidate in seen_names:
        suffix += 1
        candidate = f"{base}_{suffix}"
    seen_names.add(candidate)
    return candidate


def _role_for_geometry(geom_name: object, slot_list: list[str]) -> VectorPreviewRole:
    name = str(geom_name)
    if name == "Board":
        return "backing"
    if name == "Outline":
        return "outline"
    if name in {str(item) for item in slot_list}:
        return "color"
    return "auxiliary"


def _color_for_geometry(
    geom_name: object,
    *,
    preview_colors: dict,
    slot_list: list,
) -> tuple[int, int, int, int]:
    for key in (geom_name, str(geom_name)):
        if key in preview_colors:
            rgba = coerce_preview_rgba(preview_colors.get(key))
            if rgba is not None:
                return rgba

    try:
        slot_index = list(slot_list).index(str(geom_name))
    except ValueError:
        slot_index = -1
    if slot_index >= 0:
        rgba = coerce_preview_rgba(preview_colors.get(slot_index))
        if rgba is not None:
            return rgba

    return (200, 200, 200, 255)


def _mesh_with_rgba(
    mesh: trimesh.Trimesh,
    rgba: tuple[int, int, int, int],
) -> trimesh.Trimesh:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    geom = trimesh.Trimesh(vertices=vertices.copy(), faces=faces.copy(), process=False)
    rgba_arr = np.asarray(rgba, dtype=np.uint8)
    geom.visual = trimesh.visual.ColorVisuals(
        mesh=geom,
        face_colors=np.tile(rgba_arr, (len(faces), 1)),
    )
    return geom


def _mesh_geometry_only_copy(mesh: trimesh.Trimesh) -> trimesh.Trimesh:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    return trimesh.Trimesh(vertices=vertices.copy(), faces=faces.copy(), process=False)


def _mesh_with_material_rgba(
    mesh: trimesh.Trimesh,
    rgba: tuple[int, int, int, int],
    *,
    material_name: str,
) -> trimesh.Trimesh:
    rgba_list = [int(value) for value in rgba]
    mesh.visual = trimesh.visual.TextureVisuals(
        material=PBRMaterial(
            name=material_name,
            baseColorFactor=rgba_list,
        )
    )
    return mesh


def _split_mesh_for_uint16_indices(
    mesh: trimesh.Trimesh,
    *,
    max_vertices: int = _V2_UINT16_CHUNK_VERTEX_LIMIT,
) -> list[trimesh.Trimesh]:
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if len(vertices) <= max_vertices or len(faces) == 0:
        return [_mesh_geometry_only_copy(mesh)]

    chunks: list[trimesh.Trimesh] = []
    faces_per_vertex = max(1.0, len(faces) / max(1, len(vertices)))
    start = 0
    while start < len(faces):
        end = _find_uint16_chunk_end(
            faces,
            start,
            max_vertices=max_vertices,
            faces_per_vertex=faces_per_vertex,
        )
        chunks.append(_build_mesh_chunk(vertices, faces[start:end]))
        start = end
    return chunks


def _find_uint16_chunk_end(
    faces: np.ndarray,
    start: int,
    *,
    max_vertices: int,
    faces_per_vertex: float,
) -> int:
    face_count = len(faces)
    safe_face_count = max(1, max_vertices // 3)
    estimated_face_count = max(
        safe_face_count,
        int(max_vertices * max(1.0, faces_per_vertex) * 0.95),
    )
    candidate = min(face_count, start + estimated_face_count)
    if candidate >= face_count:
        if _count_unique_face_vertices(faces[start:face_count]) <= max_vertices:
            return face_count
    elif _count_unique_face_vertices(faces[start:candidate]) <= max_vertices:
        return candidate

    best = min(face_count, start + safe_face_count)
    if _count_unique_face_vertices(faces[start:best]) <= max_vertices and best >= face_count:
        return face_count

    high = candidate
    low = best + 1
    upper = high - 1
    while low <= upper:
        midpoint = (low + upper) // 2
        if _count_unique_face_vertices(faces[start:midpoint]) <= max_vertices:
            best = midpoint
            low = midpoint + 1
        else:
            upper = midpoint - 1
    return max(best, start + 1)


def _count_unique_face_vertices(faces: np.ndarray) -> int:
    return int(np.unique(faces).size)


def _build_mesh_chunk(
    source_vertices: np.ndarray,
    source_faces: np.ndarray,
) -> trimesh.Trimesh:
    unique_indices, inverse = np.unique(source_faces.reshape(-1), return_inverse=True)
    chunk_vertices = source_vertices[unique_indices]
    chunk_faces = inverse.reshape((-1, 3)).astype(np.int64, copy=False)
    return trimesh.Trimesh(
        vertices=chunk_vertices.copy(),
        faces=chunk_faces.copy(),
        process=False,
    )


def _pack_meshes_for_uint16_indices(
    meshes: list[trimesh.Trimesh],
    *,
    max_vertices: int = _V2_UINT16_CHUNK_VERTEX_LIMIT,
) -> list[trimesh.Trimesh]:
    chunks: list[trimesh.Trimesh] = []
    vertex_batches: list[np.ndarray] = []
    face_batches: list[np.ndarray] = []
    vertex_count = 0

    def flush() -> None:
        nonlocal vertex_batches, face_batches, vertex_count
        if not vertex_batches:
            return
        chunks.append(
            trimesh.Trimesh(
                vertices=np.concatenate(vertex_batches, axis=0),
                faces=np.concatenate(face_batches, axis=0),
                process=False,
            )
        )
        vertex_batches = []
        face_batches = []
        vertex_count = 0

    for mesh in meshes:
        source_chunks: list[tuple[np.ndarray, np.ndarray]]
        mesh_vertices = np.asarray(mesh.vertices, dtype=np.float64)
        mesh_faces = np.asarray(mesh.faces, dtype=np.int64)
        if len(mesh_vertices) <= max_vertices:
            source_chunks = [(mesh_vertices, mesh_faces)]
        else:
            source_chunks = [
                (
                    np.asarray(source_chunk.vertices, dtype=np.float64),
                    np.asarray(source_chunk.faces, dtype=np.int64),
                )
                for source_chunk in _split_mesh_for_uint16_indices(
                    mesh,
                    max_vertices=max_vertices,
                )
            ]
        for vertices, faces in source_chunks:
            if len(vertices) == 0 or len(faces) == 0:
                continue
            if vertex_batches and vertex_count + len(vertices) > max_vertices:
                flush()
            vertex_batches.append(vertices)
            face_batches.append(faces + vertex_count)
            vertex_count += len(vertices)
    flush()
    return chunks


def _scene_reuse_chunks_for_uint16_indices(
    mesh: trimesh.Trimesh,
    *,
    max_vertices: int = _V2_UINT16_CHUNK_VERTEX_LIMIT,
) -> list[trimesh.Trimesh]:
    vertices = getattr(mesh, "vertices", None)
    if vertices is None or len(vertices) <= max_vertices:
        return [mesh]
    return _split_mesh_for_uint16_indices(mesh, max_vertices=max_vertices)


def _ordered_key_at(mapping: dict, index: object) -> object | None:
    try:
        return list(mapping.keys())[int(index)]
    except (IndexError, TypeError, ValueError):
        return None


def _downcast_v2_index_buffers_to_uint16(buffer_items: dict, tree: dict) -> None:
    accessors = tree.get("accessors")
    if not isinstance(accessors, dict):
        return

    converted_views: dict[int, tuple[list[int], list[int]]] = {}
    for mesh in tree.get("meshes", []) or []:
        for primitive in mesh.get("primitives", []) or []:
            accessor_index = primitive.get("indices")
            if accessor_index is None:
                continue
            accessor_key = _ordered_key_at(accessors, accessor_index)
            if accessor_key is None:
                continue
            accessor = accessors.get(accessor_key)
            if not isinstance(accessor, dict):
                continue
            if accessor.get("componentType") != _GLTF_UINT32_COMPONENT_TYPE:
                continue
            try:
                min_index = int(accessor.get("min", [0])[0])
                max_index = int(accessor.get("max", [0])[0])
                buffer_view = int(accessor["bufferView"])
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            if buffer_view in converted_views:
                accessor["componentType"] = _GLTF_UINT16_COMPONENT_TYPE
                accessor["min"], accessor["max"] = converted_views[buffer_view]
                continue
            if min_index < 0 or max_index > _GLTF_UINT16_MAX_INDEX:
                continue
            buffer_key = _ordered_key_at(buffer_items, buffer_view)
            if buffer_key is None:
                continue
            raw = buffer_items.get(buffer_key)
            if raw is None:
                continue
            try:
                data = np.frombuffer(raw, dtype="<u4", count=int(accessor.get("count", 0)))
            except ValueError:
                continue
            if data.size == 0 or int(data.max(initial=0)) > _GLTF_UINT16_MAX_INDEX:
                continue
            downcast = data.astype("<u2").tobytes()
            if len(downcast) % 4:
                downcast += b"\x00" * (4 - (len(downcast) % 4))
            min_values = [int(data.min(initial=0))]
            max_values = [int(data.max(initial=0))]
            buffer_items[buffer_key] = downcast
            accessor["componentType"] = _GLTF_UINT16_COMPONENT_TYPE
            accessor["min"] = min_values
            accessor["max"] = max_values
            converted_views[buffer_view] = (min_values, max_values)


def _sort_v2_triangle_index_buffers_for_gzip(buffer_items: dict, tree: dict) -> None:
    accessors = tree.get("accessors")
    if not isinstance(accessors, dict):
        return

    sorted_views: set[tuple[object, int, int, str]] = set()
    for mesh in tree.get("meshes", []) or []:
        if not isinstance(mesh, dict):
            continue
        for primitive in mesh.get("primitives", []) or []:
            if not isinstance(primitive, dict):
                continue
            if int(primitive.get("mode", 4) or 4) != 4:
                continue
            accessor_index = primitive.get("indices")
            if accessor_index is None:
                continue
            accessor_key = _ordered_key_at(accessors, accessor_index)
            if accessor_key is None:
                continue
            accessor = accessors.get(accessor_key)
            if not isinstance(accessor, dict) or accessor.get("type") != "SCALAR":
                continue
            component_type = accessor.get("componentType")
            if component_type == _GLTF_UINT16_COMPONENT_TYPE:
                dtype = "<u2"
            elif component_type == _GLTF_UINT32_COMPONENT_TYPE:
                dtype = "<u4"
            else:
                continue
            try:
                count = int(accessor.get("count", 0) or 0)
                buffer_view = int(accessor["bufferView"])
                byte_offset = int(accessor.get("byteOffset", 0) or 0)
            except (KeyError, TypeError, ValueError):
                continue
            if count <= 0 or count % 3 != 0:
                continue
            buffer_key = _ordered_key_at(buffer_items, buffer_view)
            if buffer_key is None:
                continue
            raw = buffer_items.get(buffer_key)
            if not isinstance(raw, (bytes, bytearray)):
                continue
            view_key = (buffer_key, byte_offset, count, dtype)
            if view_key in sorted_views:
                continue
            itemsize = np.dtype(dtype).itemsize
            byte_length = count * itemsize
            if byte_offset < 0 or byte_offset + byte_length > len(raw):
                continue
            try:
                indices = np.frombuffer(
                    raw[byte_offset : byte_offset + byte_length],
                    dtype=dtype,
                ).reshape((-1, 3))
            except ValueError:
                continue
            if len(indices) <= 1:
                continue
            order = np.lexsort((indices[:, 1], indices[:, 0]))
            sorted_indices = indices[order].reshape(-1).astype(dtype, copy=False)
            updated = bytearray(raw)
            updated[byte_offset : byte_offset + byte_length] = sorted_indices.tobytes()
            buffer_items[buffer_key] = bytes(updated)
            sorted_views.add(view_key)


def _quantize_v2_position_buffers_to_uint16(buffer_items: dict, tree: dict) -> None:
    accessors = tree.get("accessors")
    if not isinstance(accessors, dict):
        return
    meshes = tree.get("meshes") or []
    nodes = tree.get("nodes") or []
    converted_any = False

    for mesh_index, mesh in enumerate(meshes):
        if not isinstance(mesh, dict):
            continue
        # Keep the zero-depth coordinate anchor in float form. Some CPU-side
        # GLB readers do not apply normalized integer accessor transforms when
        # calculating bounds, which would corrupt puzzle-overlay placement.
        if mesh.get("name") == PREVIEW_CANVAS_BOUNDS_NODE_NAME:
            continue
        primitives = mesh.get("primitives") or []
        if len(primitives) != 1:
            continue
        primitive = primitives[0]
        if not isinstance(primitive, dict):
            continue
        position_accessor_index = (primitive.get("attributes") or {}).get("POSITION")
        position_accessor_key = _ordered_key_at(accessors, position_accessor_index)
        if position_accessor_key is None:
            continue
        accessor = accessors.get(position_accessor_key)
        if not _is_quantizable_position_accessor(accessor):
            continue
        mesh_nodes = [
            node
            for node in nodes
            if isinstance(node, dict) and node.get("mesh") == mesh_index
        ]
        if not mesh_nodes or any(_node_has_transform(node) for node in mesh_nodes):
            continue
        quantized = _quantized_position_buffer(buffer_items, accessor)
        if quantized is None:
            continue
        buffer_key, quantized_bytes, quantized_min, quantized_max, translation, scale = quantized
        buffer_items[buffer_key] = quantized_bytes
        accessor["componentType"] = _GLTF_UINT16_COMPONENT_TYPE
        accessor["normalized"] = True
        accessor["byteOffset"] = 0
        accessor["min"] = quantized_min
        accessor["max"] = quantized_max
        for node in mesh_nodes:
            node["translation"] = translation
            node["scale"] = scale
        converted_any = True

    if converted_any:
        extensions = set(tree.get("extensionsUsed") or [])
        extensions.add(_GLTF_QUANTIZATION_EXTENSION)
        tree["extensionsUsed"] = sorted(extensions)


def _sort_quantized_position_buffers_for_gzip(buffer_items: dict, tree: dict) -> None:
    accessors = tree.get("accessors")
    if not isinstance(accessors, dict):
        return

    position_orders: dict[tuple[object, int, int], tuple[np.ndarray, np.ndarray]] = {}
    remapped_index_views: set[tuple[object, int, int, str]] = set()
    sorted_attribute_views: set[tuple[object, int, int, str, int]] = set()
    for mesh in tree.get("meshes") or []:
        if not isinstance(mesh, dict):
            continue
        for primitive in mesh.get("primitives", []) or []:
            if not isinstance(primitive, dict):
                continue
            if int(primitive.get("mode", 4) or 4) != 4:
                continue
            position_accessor = _quantized_position_accessor_for_primitive(
                primitive,
                accessors,
            )
            if position_accessor is None:
                continue
            index_accessor = _index_accessor_for_primitive(primitive, accessors)
            if index_accessor is None:
                continue
            sort_result = _sort_quantized_position_accessor(
                buffer_items,
                position_accessor,
                position_orders,
            )
            if sort_result is None:
                continue
            order, remap = sort_result
            _sort_vertex_attribute_accessors_for_position_order(
                buffer_items,
                primitive,
                accessors,
                order,
                sorted_attribute_views,
            )
            _remap_index_accessor_for_sorted_positions(
                buffer_items,
                index_accessor,
                remap,
                remapped_index_views,
            )


def _quantized_position_accessor_for_primitive(
    primitive: dict,
    accessors: dict,
) -> dict | None:
    position_accessor_index = (primitive.get("attributes") or {}).get("POSITION")
    position_accessor_key = _ordered_key_at(accessors, position_accessor_index)
    if position_accessor_key is None:
        return None
    accessor = accessors.get(position_accessor_key)
    if not isinstance(accessor, dict):
        return None
    if (
        accessor.get("componentType") != _GLTF_UINT16_COMPONENT_TYPE
        or accessor.get("normalized") is not True
        or accessor.get("type") != "VEC3"
    ):
        return None
    return accessor


def _index_accessor_for_primitive(primitive: dict, accessors: dict) -> dict | None:
    accessor_index = primitive.get("indices")
    if accessor_index is None:
        return None
    accessor_key = _ordered_key_at(accessors, accessor_index)
    if accessor_key is None:
        return None
    accessor = accessors.get(accessor_key)
    if not isinstance(accessor, dict) or accessor.get("type") != "SCALAR":
        return None
    return accessor


def _sort_quantized_position_accessor(
    buffer_items: dict,
    accessor: dict,
    position_orders: dict[tuple[object, int, int], tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray] | None:
    try:
        count = int(accessor.get("count", 0) or 0)
        buffer_view = int(accessor["bufferView"])
        byte_offset = int(accessor.get("byteOffset", 0) or 0)
    except (KeyError, TypeError, ValueError):
        return None
    if count <= 0 or byte_offset < 0:
        return None
    buffer_key = _ordered_key_at(buffer_items, buffer_view)
    if buffer_key is None:
        return None
    view_key = (buffer_key, byte_offset, count)
    if view_key in position_orders:
        return position_orders[view_key]
    raw = buffer_items.get(buffer_key)
    if not isinstance(raw, (bytes, bytearray)):
        return None
    byte_length = count * 3 * np.dtype("<u2").itemsize
    if byte_offset + byte_length > len(raw):
        return None
    try:
        positions = np.frombuffer(
            raw[byte_offset : byte_offset + byte_length],
            dtype="<u2",
        ).reshape((count, 3))
    except ValueError:
        return None
    order = np.lexsort((positions[:, 2], positions[:, 1], positions[:, 0]))
    inverse = np.empty(len(order), dtype=np.int64)
    inverse[order] = np.arange(len(order), dtype=np.int64)
    if not np.array_equal(order, np.arange(len(order), dtype=np.int64)):
        sorted_positions = positions[order].astype("<u2", copy=False)
        updated = bytearray(raw)
        updated[byte_offset : byte_offset + byte_length] = sorted_positions.tobytes()
        buffer_items[buffer_key] = bytes(updated)
    result = (order, inverse)
    position_orders[view_key] = result
    return result


def _sort_vertex_attribute_accessors_for_position_order(
    buffer_items: dict,
    primitive: dict,
    accessors: dict,
    order: np.ndarray,
    sorted_attribute_views: set[tuple[object, int, int, str, int]],
) -> None:
    attributes = primitive.get("attributes")
    if not isinstance(attributes, dict):
        return
    for attribute_name, accessor_index in attributes.items():
        if attribute_name == "POSITION":
            continue
        accessor_key = _ordered_key_at(accessors, accessor_index)
        if accessor_key is None:
            continue
        accessor = accessors.get(accessor_key)
        if not isinstance(accessor, dict):
            continue
        _sort_vertex_attribute_accessor_for_position_order(
            buffer_items,
            accessor,
            order,
            sorted_attribute_views,
        )


def _sort_vertex_attribute_accessor_for_position_order(
    buffer_items: dict,
    accessor: dict,
    order: np.ndarray,
    sorted_attribute_views: set[tuple[object, int, int, str, int]],
) -> None:
    if accessor.get("sparse") is not None:
        return
    dtype, component_count = _vertex_attribute_accessor_layout(accessor)
    if dtype is None or component_count <= 0:
        return
    try:
        count = int(accessor.get("count", 0) or 0)
        buffer_view = int(accessor["bufferView"])
        byte_offset = int(accessor.get("byteOffset", 0) or 0)
    except (KeyError, TypeError, ValueError):
        return
    if count != len(order) or count <= 0 or byte_offset < 0:
        return
    buffer_key = _ordered_key_at(buffer_items, buffer_view)
    if buffer_key is None:
        return
    raw = buffer_items.get(buffer_key)
    if not isinstance(raw, (bytes, bytearray)):
        return
    itemsize = np.dtype(dtype).itemsize
    byte_length = count * component_count * itemsize
    if byte_offset + byte_length > len(raw):
        return
    view_key = (buffer_key, byte_offset, count, dtype, component_count)
    if view_key in sorted_attribute_views:
        return
    try:
        data = np.frombuffer(
            raw[byte_offset : byte_offset + byte_length],
            dtype=dtype,
        ).reshape((count, component_count))
    except ValueError:
        return
    sorted_data = data[order].astype(dtype, copy=False)
    updated = bytearray(raw)
    updated[byte_offset : byte_offset + byte_length] = sorted_data.tobytes()
    buffer_items[buffer_key] = bytes(updated)
    sorted_attribute_views.add(view_key)


def _vertex_attribute_accessor_layout(accessor: dict) -> tuple[str | None, int]:
    component_type_to_dtype = {
        5120: "<i1",
        5121: "<u1",
        5122: "<i2",
        _GLTF_UINT16_COMPONENT_TYPE: "<u2",
        _GLTF_UINT32_COMPONENT_TYPE: "<u4",
        _GLTF_FLOAT_COMPONENT_TYPE: "<f4",
    }
    type_to_component_count = {
        "SCALAR": 1,
        "VEC2": 2,
        "VEC3": 3,
        "VEC4": 4,
    }
    dtype = component_type_to_dtype.get(accessor.get("componentType"))
    component_count = type_to_component_count.get(accessor.get("type"), 0)
    return dtype, component_count


def _remap_index_accessor_for_sorted_positions(
    buffer_items: dict,
    accessor: dict,
    remap: np.ndarray,
    remapped_index_views: set[tuple[object, int, int, str]],
) -> None:
    component_type = accessor.get("componentType")
    if component_type == _GLTF_UINT16_COMPONENT_TYPE:
        dtype = "<u2"
    elif component_type == _GLTF_UINT32_COMPONENT_TYPE:
        dtype = "<u4"
    else:
        return
    try:
        count = int(accessor.get("count", 0) or 0)
        buffer_view = int(accessor["bufferView"])
        byte_offset = int(accessor.get("byteOffset", 0) or 0)
    except (KeyError, TypeError, ValueError):
        return
    if count <= 0 or byte_offset < 0:
        return
    buffer_key = _ordered_key_at(buffer_items, buffer_view)
    if buffer_key is None:
        return
    view_key = (buffer_key, byte_offset, count, dtype)
    if view_key in remapped_index_views:
        return
    raw = buffer_items.get(buffer_key)
    if not isinstance(raw, (bytes, bytearray)):
        return
    itemsize = np.dtype(dtype).itemsize
    byte_length = count * itemsize
    if byte_offset + byte_length > len(raw):
        return
    try:
        indices = np.frombuffer(
            raw[byte_offset : byte_offset + byte_length],
            dtype=dtype,
        )
    except ValueError:
        return
    if indices.size == 0 or int(indices.max(initial=0)) >= len(remap):
        return
    remapped = remap[indices].astype(dtype, copy=False)
    updated = bytearray(raw)
    updated[byte_offset : byte_offset + byte_length] = remapped.tobytes()
    buffer_items[buffer_key] = bytes(updated)
    accessor["min"] = [int(remapped.min(initial=0))]
    accessor["max"] = [int(remapped.max(initial=0))]
    remapped_index_views.add(view_key)


def _is_quantizable_position_accessor(accessor: object) -> bool:
    return (
        isinstance(accessor, dict)
        and accessor.get("componentType") == _GLTF_FLOAT_COMPONENT_TYPE
        and accessor.get("type") == "VEC3"
        and int(accessor.get("count", 0) or 0) > 0
        and "bufferView" in accessor
    )


def _node_has_transform(node: dict) -> bool:
    return any(key in node for key in ("matrix", "translation", "rotation", "scale"))


def _quantized_position_buffer(
    buffer_items: dict,
    accessor: dict,
) -> tuple[object, bytes, list[int], list[int], list[float], list[float]] | None:
    try:
        count = int(accessor["count"])
        buffer_view = int(accessor["bufferView"])
        byte_offset = int(accessor.get("byteOffset", 0) or 0)
    except (KeyError, TypeError, ValueError):
        return None
    if count <= 0 or byte_offset != 0:
        return None
    buffer_key = _ordered_key_at(buffer_items, buffer_view)
    if buffer_key is None:
        return None
    raw = buffer_items.get(buffer_key)
    if not isinstance(raw, (bytes, bytearray)):
        return None
    byte_length = count * 3 * np.dtype("<f4").itemsize
    if len(raw) < byte_length:
        return None
    try:
        positions = np.frombuffer(raw[:byte_length], dtype="<f4").reshape((count, 3))
    except ValueError:
        return None
    if positions.size == 0 or not np.isfinite(positions).all():
        return None
    mins = positions.min(axis=0).astype(np.float64)
    maxs = positions.max(axis=0).astype(np.float64)
    scale = maxs - mins
    safe_scale = np.where(scale > 0.0, scale, 1.0)
    normalized = np.clip((positions.astype(np.float64) - mins) / safe_scale, 0.0, 1.0)
    quantized = np.rint(normalized * _GLTF_UINT16_MAX_INDEX).astype("<u2")
    for axis in np.where(scale <= 0.0)[0]:
        quantized[:, axis] = 0
    quantized_bytes = quantized.tobytes()
    if len(quantized_bytes) % 4:
        quantized_bytes += b"\x00" * (4 - (len(quantized_bytes) % 4))
    return (
        buffer_key,
        quantized_bytes,
        quantized.min(axis=0).astype(int).tolist(),
        quantized.max(axis=0).astype(int).tolist(),
        mins.tolist(),
        scale.tolist(),
    )


def _optimize_v2_glb_buffers(buffer_items: dict, tree: dict) -> None:
    _downcast_v2_index_buffers_to_uint16(buffer_items, tree)
    _quantize_v2_position_buffers_to_uint16(buffer_items, tree)
    _sort_quantized_position_buffers_for_gzip(buffer_items, tree)
    _sort_v2_triangle_index_buffers_for_gzip(buffer_items, tree)
    _deduplicate_v2_materials(tree)


def _deduplicate_v2_materials(tree: dict) -> None:
    materials = tree.get("materials")
    if not isinstance(materials, list) or len(materials) < 2:
        return

    seen: dict[str, int] = {}
    old_to_new: dict[int, int] = {}
    deduplicated: list[object] = []
    for index, material in enumerate(materials):
        key = _material_dedup_key(material)
        if key is None or key not in seen:
            old_to_new[index] = len(deduplicated)
            if key is not None:
                seen[key] = old_to_new[index]
            deduplicated.append(material)
            continue
        old_to_new[index] = seen[key]

    if len(deduplicated) == len(materials):
        return

    for mesh in tree.get("meshes") or []:
        if not isinstance(mesh, dict):
            continue
        for primitive in mesh.get("primitives") or []:
            if not isinstance(primitive, dict) or "material" not in primitive:
                continue
            try:
                old_material = int(primitive["material"])
            except (TypeError, ValueError):
                continue
            if old_material in old_to_new:
                primitive["material"] = old_to_new[old_material]
    tree["materials"] = deduplicated


def _material_dedup_key(material: object) -> str | None:
    if not isinstance(material, dict):
        return None
    canonical = {
        key: value
        for key, value in material.items()
        if key != "name"
    }
    return json.dumps(canonical, sort_keys=True, separators=(",", ":"))


def _write_glb_scene(
    glb_scene: trimesh.Scene,
    output_path: str,
    *,
    optimize_v2_buffers: bool = False,
) -> str:
    export_kwargs = {"file_type": "glb"}
    if optimize_v2_buffers:
        export_kwargs["buffer_postprocessor"] = _optimize_v2_glb_buffers
    exported = glb_scene.export(output_path, **export_kwargs)
    if isinstance(exported, (bytes, bytearray)):
        with open(output_path, "wb") as glb_file:
            glb_file.write(exported)
    if not os.path.exists(output_path):
        raise RuntimeError(f"Vector GLB export did not create file: {output_path}")
    return output_path


def build_vector_preview_parts_from_scene(
    *,
    scene: trimesh.Scene,
    preview_colors: dict,
    slot_list: list,
    copy_fallback_mesh: bool = True,
) -> list[VectorPreviewPart]:
    """Build fallback descriptors from an already display-oriented scene."""

    seen_names: set[str] = set()
    parts: list[VectorPreviewPart] = []
    for geom_name, source_geom in scene.geometry.items():
        vertices = getattr(source_geom, "vertices", None)
        faces = getattr(source_geom, "faces", None)
        if vertices is None or faces is None or len(vertices) == 0 or len(faces) == 0:
            continue
        role = _role_for_geometry(geom_name, list(slot_list))
        rgba = _color_for_geometry(
            geom_name,
            preview_colors=preview_colors,
            slot_list=list(slot_list),
        )
        export_name = make_vector_glb_export_name(
            source_name=str(geom_name),
            role=role,
            rgba=rgba,
            seen_names=seen_names,
        )
        parts.append(
            VectorPreviewPart(
                source_name=str(geom_name),
                export_name=export_name,
                role=role,
                rgba=rgba,
                is_recolorable=(role == "color"),
                fallback_mesh=(
                    _mesh_geometry_only_copy(source_geom)
                    if copy_fallback_mesh
                    else source_geom
                ),
            )
        )
    return parts


def _build_preview_canvas_anchor_part(
    analysis: object | None,
    *,
    screen_to_world_canvas_height_mm: float | None = None,
) -> VectorPreviewPart | None:
    """Build coordinate-only canvas geometry for frontend overlay placement.
    构建仅用于前端叠线定位的画布坐标几何。
    """

    if analysis is None:
        return None
    canvas = _valid_geometry(getattr(analysis, "image_vectorizer_bounds", None))
    if canvas is None:
        return None
    try:
        scale_factor = float(getattr(analysis, "scale_factor", 1.0) or 1.0)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(scale_factor) or scale_factor <= 0:
        return None

    min_x, min_y, max_x, max_y = (float(value) for value in canvas.bounds)
    width = max_x - min_x
    height = max_y - min_y
    mesh = _build_preview_canvas_bounds_mesh(width, height, scale_factor)
    if mesh is None:
        return None
    anchor_y_mm = min_y * scale_factor
    if screen_to_world_canvas_height_mm is not None:
        if (
            not np.isfinite(screen_to_world_canvas_height_mm)
            or screen_to_world_canvas_height_mm <= 0
        ):
            return None
        anchor_y_mm = (
            float(screen_to_world_canvas_height_mm)
            - max_y * scale_factor
        )
    mesh.apply_translation((min_x * scale_factor, anchor_y_mm, 0.0))
    return VectorPreviewPart(
        source_name=PREVIEW_CANVAS_BOUNDS_NODE_NAME,
        export_name=PREVIEW_CANVAS_BOUNDS_NODE_NAME,
        role="auxiliary",
        rgba=(0, 0, 0, 0),
        is_recolorable=False,
        fallback_mesh=mesh,
    )


def export_vector_glb_preview_v1(
    parts: list[VectorPreviewPart],
    *,
    output_path: str,
) -> str:
    """Export a GLB by copying descriptor fallback meshes.

    复制 descriptor 中的 V1 fallback mesh，保持现有 GLB 行为。
    """

    glb_scene = trimesh.Scene()
    for part in parts:
        mesh = part.fallback_mesh
        if mesh is None:
            raise RuntimeError(f"V1 export requires fallback mesh for {part.source_name}")
        vertices = getattr(mesh, "vertices", None)
        faces = getattr(mesh, "faces", None)
        if vertices is None or faces is None or len(vertices) == 0 or len(faces) == 0:
            continue
        glb_scene.add_geometry(
            _mesh_with_rgba(mesh, part.rgba),
            geom_name=part.export_name,
        )

    if not glb_scene.geometry:
        raise RuntimeError("Vector GLB export has no non-empty geometries")
    return _write_glb_scene(glb_scene, output_path)


def export_vector_glb_preview_v2_scene_reuse(
    parts: list[VectorPreviewPart],
    *,
    output_path: str,
) -> str:
    """Export GLB by reusing the already-built V1 preview scene meshes.

    The geometry comes from the compatibility-proven scene path; V2 only
    changes GLB serialization details such as material colors and buffer
    post-processing.
    """

    t0 = time.perf_counter()
    glb_scene = trimesh.Scene()
    for part in parts:
        mesh = part.fallback_mesh
        if mesh is None:
            raise RuntimeError(f"V2 scene-reuse export requires mesh for {part.source_name}")
        vertices = getattr(mesh, "vertices", None)
        faces = getattr(mesh, "faces", None)
        if vertices is None or faces is None or len(vertices) == 0 or len(faces) == 0:
            continue
        chunks = _scene_reuse_chunks_for_uint16_indices(mesh)
        for index, chunk in enumerate(chunks):
            export_name = (
                part.export_name
                if len(chunks) == 1
                else f"{part.export_name}_chunk{index + 1:03d}"
            )
            glb_scene.add_geometry(
                _mesh_with_material_rgba(
                    chunk,
                    part.rgba,
                    material_name=f"{part.export_name}_material",
                ),
                geom_name=export_name,
            )

    if not glb_scene.geometry:
        raise RuntimeError("V2 scene-reuse GLB export has no non-empty geometries")
    result = _write_glb_scene(
        glb_scene,
        output_path,
        optimize_v2_buffers=True,
    )
    log.info(
        "Vector GLB V2 scene-reuse exported",
        extra={
            "event": "vector_glb_v2_scene_reuse_exported",
            "path": str(output_path),
            "part_count": len(parts),
            "geometry_count": len(glb_scene.geometry),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
        },
    )
    return result


@lru_cache(maxsize=1)
def _get_vector_v2_rasterizer_modules():
    """Return cached rasterio helpers for vector V2 footprint rasterization."""
    from rasterio.features import rasterize
    from rasterio.transform import from_origin

    return rasterize, from_origin


def _valid_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or getattr(geometry, "is_empty", True):
        return None
    try:
        if not geometry.is_valid:
            geometry = make_valid(geometry)
    except (AttributeError, ValueError, TypeError):
        return None
    if geometry is None or getattr(geometry, "is_empty", True):
        return None
    return geometry


def _scaled_geometry_mm(geometry: BaseGeometry, scale_factor: float) -> BaseGeometry | None:
    try:
        return _valid_geometry(
            shapely_scale(
                geometry,
                xfact=scale_factor,
                yfact=scale_factor,
                origin=(0.0, 0.0),
            )
        )
    except (ValueError, TypeError, AttributeError):
        return None


def _screen_geometry_to_preview_world_y(
    geometry: BaseGeometry | None,
    canvas_height_mm: float,
) -> BaseGeometry | None:
    """Map SVG screen-down Y coordinates to preview world-up coordinates."""

    prepared = _valid_geometry(geometry)
    if (
        prepared is None
        or not np.isfinite(canvas_height_mm)
        or canvas_height_mm <= 0
    ):
        return None
    try:
        flipped = shapely_scale(
            prepared,
            xfact=1.0,
            yfact=-1.0,
            origin=(0.0, 0.0),
        )
        return _valid_geometry(
            shapely_translate(flipped, yoff=float(canvas_height_mm))
        )
    except (ValueError, TypeError, AttributeError):
        return None


def _prepare_backing_footprint(
    geometry: BaseGeometry,
    scale_factor: float,
    source_units_per_unit: float = 1.0,
) -> BaseGeometry | None:
    prepared = _valid_geometry(geometry)
    return (_prepare_footprint(prepared, scale_factor, source_units_per_unit)
            if prepared is not None else None)


def _visible_backing_footprint(
    silhouette: BaseGeometry | None,
    scale_factor: float,
    source_units_per_unit: float = 1.0,
) -> BaseGeometry | None:
    if silhouette is not None:
        return _prepare_backing_footprint(silhouette, scale_factor, source_units_per_unit)
    return None


def _preview_rgb_codes(pixels: np.ndarray) -> np.ndarray:
    values = np.asarray(pixels, dtype=np.uint64)
    return values[..., 0] << 16 | values[..., 1] << 8 | values[..., 2]


def _preview_rgb_from_code(code: int) -> tuple[int, int, int]:
    return ((code >> 16) & 0xFF, (code >> 8) & 0xFF, code & 0xFF)


def _interior_preview_mask(mask: np.ndarray) -> np.ndarray:
    """Remove the one-pixel raster edge where adjacent SVG shapes may vote."""

    values = np.asarray(mask, dtype=bool)
    if values.ndim != 2 or values.shape[0] < 3 or values.shape[1] < 3:
        return np.zeros_like(values, dtype=bool)
    padded = np.pad(values, 1, mode="constant", constant_values=False)
    return (
        padded[1:-1, 1:-1]
        & padded[:-2, 1:-1]
        & padded[2:, 1:-1]
        & padded[1:-1, :-2]
        & padded[1:-1, 2:]
    )


def _dominant_preview_code(codes: np.ndarray) -> np.uint64 | None:
    values, counts = np.unique(codes, return_counts=True)
    if len(values) == 0:
        return None
    return values[int(np.argmax(counts))]


@lru_cache(maxsize=1)
def _get_preview_mask_polygonizer():
    from rasterio.features import shapes

    return shapes


@lru_cache(maxsize=1)
def _get_preview_distance_transform():
    from scipy.ndimage import distance_transform_edt

    return distance_transform_edt


def _propagate_preview_codes(
    codes: np.ndarray,
    *,
    seed_mask: np.ndarray,
    target_mask: np.ndarray,
) -> np.ndarray | None:
    """Assign every target pixel the nearest trusted interior classification."""

    if not np.any(seed_mask):
        return None
    try:
        distance_transform = _get_preview_distance_transform()
        nearest_indices = distance_transform(
            ~np.asarray(seed_mask, dtype=bool),
            return_distances=False,
            return_indices=True,
        )
        propagated = np.asarray(codes)[tuple(nearest_indices)]
    except (ImportError, RuntimeError, TypeError, ValueError, MemoryError):
        return None
    if propagated.shape != target_mask.shape:
        return None
    return propagated


def _polygonize_preview_classification(
    mask: np.ndarray,
    *,
    component: Polygon,
    x_offset: int,
    y_offset: int,
    coord_scale: float,
) -> tuple[Polygon, ...] | None:
    """Clip pixel-class boundaries to the original smooth SVG footprint."""

    if not np.any(mask):
        return ()
    try:
        rio_shapes = _get_preview_mask_polygonizer()
        pixel_geometries = [
            shapely_shape(mapping)
            for mapping, value in rio_shapes(
                np.asarray(mask, dtype=np.uint8),
                mask=np.asarray(mask, dtype=bool),
                connectivity=4,
            )
            if int(value) == 1
        ]
    except (ImportError, RuntimeError, TypeError, ValueError, AttributeError):
        return None
    if not pixel_geometries:
        return None

    try:
        pixel_geometry = _valid_geometry(unary_union(pixel_geometries))
        if pixel_geometry is None:
            return None
        source_geometry = shapely_translate(
            shapely_scale(
                pixel_geometry,
                xfact=1.0 / coord_scale,
                yfact=1.0 / coord_scale,
                origin=(0.0, 0.0),
            ),
            xoff=float(x_offset) / coord_scale,
            yoff=float(y_offset) / coord_scale,
        )
        clipped = _valid_geometry(source_geometry.intersection(component))
    except (ValueError, TypeError, AttributeError):
        return None
    return _polygon_components(clipped)


def _polygon_components(geometry: BaseGeometry | None) -> tuple[Polygon, ...]:
    if isinstance(geometry, Polygon):
        return (geometry,)
    components: list[Polygon] = []
    for child in getattr(geometry, "geoms", ()):  # MultiPolygon / repaired collection
        components.extend(_polygon_components(child))
    return tuple(components)


def _is_subpixel_geometry(geometry: BaseGeometry, coord_scale: float) -> bool:
    """Return whether a footprint covers at most one preview raster pixel."""

    try:
        pixel_area = abs(float(geometry.area)) * float(coord_scale) ** 2
    except (TypeError, ValueError, AttributeError, OverflowError):
        return False
    return bool(np.isfinite(pixel_area) and pixel_area <= 1.0)


def _simplify_quick_preview_polygons(
    polygons: tuple[Polygon, ...],
    tolerance_mm: float,
) -> tuple[Polygon, ...]:
    """Simplify preview-only footprints without exceeding a display bound."""

    if not np.isfinite(tolerance_mm) or tolerance_mm <= 0:
        return polygons
    simplified_polygons: list[Polygon] = []
    for polygon in polygons:
        try:
            simplified = _valid_geometry(
                polygon.simplify(tolerance_mm, preserve_topology=True)
            )
        except (ValueError, TypeError, AttributeError):
            simplified = None
        components = _polygon_components(simplified)
        simplified_polygons.extend(components or (polygon,))
    return tuple(simplified_polygons)


def build_vector_quick_preview_parts(
    *,
    source: VectorQuickPreviewSourceV1,
    matched_rgb: np.ndarray,
    height_identity_rgb: np.ndarray | None,
    mask_solid: np.ndarray,
    backing_rgba: tuple[int, int, int, int],
    backing_thickness_mm: float,
    max_color_groups: int = 128,
) -> list[VectorPreviewPart] | None:
    """Classify smooth Vector footprints by current colour and height identity.

    Original SVG boundaries stay analytic. When a spatial edit introduces
    multiple classifications inside one SVG shape, only the new internal
    boundary comes from the preview grid and is clipped to the smooth source
    footprint.

    SVG 原始外轮廓始终保持解析几何；空间编辑在单个形状内部产生多种
    分类时，仅新增的内部边界来自预览网格，并裁剪在平滑的源轮廓内。
    """

    display = np.asarray(matched_rgb)
    identity = (
        np.asarray(height_identity_rgb)
        if height_identity_rgb is not None
        else None
    )
    solid = np.asarray(mask_solid)
    if (
        identity is None
        or display.ndim != 3
        or display.shape[2] != 3
        or display.dtype != np.uint8
        or identity.shape != display.shape
        or identity.dtype != np.uint8
        or solid.shape != display.shape[:2]
        or not np.issubdtype(solid.dtype, np.bool_)
        or max_color_groups <= 0
    ):
        return None

    real_width = float(source.bbox[2])
    real_height = float(source.bbox[3])
    if real_width <= 0 or real_height <= 0:
        return None
    height, width = display.shape[:2]
    coord_scale = float(width) / real_width
    pixels_per_mm = coord_scale / float(source.scale_factor)
    canvas_height_mm = real_height * float(source.scale_factor)
    if not np.isfinite(pixels_per_mm) or pixels_per_mm <= 0:
        return None
    simplify_tolerance_mm = min(
        _VECTOR_QUICK_PREVIEW_MAX_SIMPLIFY_MM,
        0.5 / pixels_per_mm,
    )
    expected_height = max(1, int(round(real_height * coord_scale)))
    if abs(expected_height - height) > 1:
        return None

    grouped: dict[
        tuple[tuple[int, int, int], tuple[int, int, int]],
        list[Polygon],
    ] = {}
    solid_bool = solid.astype(bool, copy=False)
    for item in source.clipped_shapes:
        geometry = item.get("geometry") if isinstance(item, dict) else None
        if not isinstance(geometry, (Polygon, MultiPolygon)):
            return None
        for component in _polygon_components(geometry):
            rasterized = _rasterize_geometry_roi_mask(
                component,
                canvas_shape=(height, width),
                coord_scale=coord_scale,
            )
            if rasterized is None:
                if _is_subpixel_geometry(component, coord_scale):
                    continue
                return None
            y_slice, x_slice, component_mask = rasterized
            effective_mask = component_mask & solid_bool[y_slice, x_slice]
            if not np.any(effective_mask):
                if _is_subpixel_geometry(component, coord_scale):
                    continue
                return None
            display_codes = _preview_rgb_codes(display[y_slice, x_slice])
            height_codes = _preview_rgb_codes(identity[y_slice, x_slice])
            component_interior_mask = _interior_preview_mask(component_mask)
            interior_mask = effective_mask & component_interior_mask
            identity_sample_mask = (
                interior_mask if np.any(interior_mask) else effective_mask
            )
            dominant_height_code = _dominant_preview_code(
                height_codes[identity_sample_mask]
            )
            if dominant_height_code is None:
                return None
            owned_effective_mask = effective_mask & (
                height_codes == dominant_height_code
            )
            owned_interior_mask = interior_mask & (
                height_codes == dominant_height_code
            )
            display_sample_mask = (
                owned_interior_mask
                if np.any(owned_interior_mask)
                else owned_effective_mask
            )
            if not np.any(display_sample_mask):
                return None
            has_interior_solid_hole = bool(
                np.any(
                    component_interior_mask
                    & ~solid_bool[y_slice, x_slice]
                )
            )
            if np.any(owned_interior_mask):
                unique_display_codes = np.unique(display_codes[display_sample_mask])
            else:
                dominant_display_code = _dominant_preview_code(
                    display_codes[display_sample_mask]
                )
                if dominant_display_code is None:
                    return None
                unique_display_codes = np.asarray(
                    [dominant_display_code],
                    dtype=np.uint64,
                )
            preserve_entire_component = (
                len(unique_display_codes) == 1
                and not has_interior_solid_hole
            )
            classification_target_mask = (
                effective_mask
                if has_interior_solid_hole
                else component_mask
            )
            propagated_display_codes = None
            if not preserve_entire_component:
                propagated_display_codes = _propagate_preview_codes(
                    display_codes,
                    seed_mask=display_sample_mask,
                    target_mask=classification_target_mask,
                )
                if propagated_display_codes is None:
                    return None
            component_grouped = False
            classified_source_components: list[Polygon] = []
            for raw_display_code in unique_display_codes:
                display_code = int(raw_display_code)
                if preserve_entire_component:
                    source_components = (component,)
                else:
                    source_components = _polygonize_preview_classification(
                        classification_target_mask
                        & (propagated_display_codes == raw_display_code),
                        component=component,
                        x_offset=int(x_slice.start or 0),
                        y_offset=int(y_slice.start or 0),
                        coord_scale=coord_scale,
                    )
                    if source_components is None:
                        return None
                    if not source_components:
                        continue
                    classified_source_components.extend(source_components)
                scaled_components: list[Polygon] = []
                for source_component in source_components:
                    scaled = _screen_geometry_to_preview_world_y(
                        _scaled_geometry_mm(
                            source_component,
                            source.scale_factor,
                        ),
                        canvas_height_mm,
                    )
                    scaled_components.extend(
                        _simplify_quick_preview_polygons(
                            _polygon_components(scaled),
                            simplify_tolerance_mm,
                        )
                    )
                if not scaled_components:
                    continue
                display_rgb = _preview_rgb_from_code(display_code)
                height_rgb = _preview_rgb_from_code(int(dominant_height_code))
                grouped.setdefault((display_rgb, height_rgb), []).extend(
                    scaled_components
                )
                component_grouped = True
                if len(grouped) > int(max_color_groups):
                    return None
            if not component_grouped:
                return None
            if not has_interior_solid_hole and not preserve_entire_component:
                try:
                    classified_coverage = _valid_geometry(
                        unary_union(classified_source_components)
                    )
                    missing_area = (
                        float(component.difference(classified_coverage).area)
                        if classified_coverage is not None
                        else float(component.area)
                    )
                except (ValueError, TypeError, AttributeError):
                    return None
                coverage_tolerance = max(1e-12, float(component.area) * 1e-9)
                if missing_area > coverage_tolerance:
                    return None

    if not grouped or len(grouped) > int(max_color_groups):
        return None

    try:
        color_shell_height = float(PrinterConfig.LAYER_HEIGHT)
    except (TypeError, ValueError):
        color_shell_height = 0.08
    if not np.isfinite(color_shell_height) or color_shell_height <= 0:
        color_shell_height = 0.08

    seen_names: set[str] = set()
    parts: list[VectorPreviewPart] = []
    for (display_rgb, height_rgb), footprints in grouped.items():
        rgba = (*display_rgb, 255)
        export_name = make_vector_glb_export_name(
            source_name=f"{display_rgb[0]:02x}{display_rgb[1]:02x}{display_rgb[2]:02x}",
            role="color",
            rgba=rgba,
            seen_names=seen_names,
        )
        parts.append(
            VectorPreviewPart(
                source_name=export_name,
                export_name=export_name,
                role="color",
                rgba=rgba,
                is_recolorable=True,
                height_key=(
                    f"{height_rgb[0]:02x}{height_rgb[1]:02x}{height_rgb[2]:02x}"
                ),
                extrusions=tuple(
                    VectorPreviewExtrusion(
                        footprint=footprint,
                        z_min=0.0,
                        z_max=color_shell_height,
                    )
                    for footprint in footprints
                ),
            )
        )

    backing = _visible_backing_footprint(
        source.silhouette,
        source.scale_factor,
        (source.svg_coordinate_domain.source_units_per_unit
         if source.svg_coordinate_domain is not None else 1.0),
    )
    backing = _screen_geometry_to_preview_world_y(backing, canvas_height_mm)
    if backing is not None:
        try:
            backing_height = max(
                float(backing_thickness_mm),
                color_shell_height,
            )
        except (TypeError, ValueError):
            backing_height = color_shell_height
        parts.append(
            VectorPreviewPart(
                source_name="Board",
                export_name=make_vector_glb_export_name(
                    source_name="Board",
                    role="backing",
                    rgba=backing_rgba,
                    seen_names=seen_names,
                ),
                role="backing",
                rgba=backing_rgba,
                is_recolorable=False,
                extrusions=(
                    VectorPreviewExtrusion(
                        footprint=backing,
                        z_min=0.0,
                        z_max=backing_height,
                    ),
                ),
            )
        )

    canvas_anchor = _build_preview_canvas_anchor_part(
        source,
        screen_to_world_canvas_height_mm=canvas_height_mm,
    )
    if canvas_anchor is None:
        canvas_anchor = _build_full_canvas_anchor_part(
            real_width,
            real_height,
            float(source.scale_factor),
        )
    if canvas_anchor is not None:
        parts.append(canvas_anchor)
    return parts


def _build_full_canvas_anchor_part(
    canvas_width: float,
    canvas_height: float,
    scale_factor: float,
) -> VectorPreviewPart | None:
    """Anchor the whole SVG canvas when no image-vectorizer bounds exist.

    Plain SVG uploads have no ``image_vectorizer_bounds``; the preview raster
    and its colour contours still span the full SVG canvas from the world
    origin, so the frontend needs that rectangle to align contour overlays.
    普通 SVG 上传没有图片矢量化边界；预览栅格与颜色轮廓仍从世界原点覆盖
    整张 SVG 画布，前端需要该矩形来对齐轮廓叠加。
    """

    mesh = _build_preview_canvas_bounds_mesh(canvas_width, canvas_height, scale_factor)
    if mesh is None:
        return None
    return VectorPreviewPart(
        source_name=PREVIEW_CANVAS_BOUNDS_NODE_NAME,
        export_name=PREVIEW_CANVAS_BOUNDS_NODE_NAME,
        role="auxiliary",
        rgba=(0, 0, 0, 0),
        is_recolorable=False,
        fallback_mesh=mesh,
    )


def _recipe_channel_runs(recipe: list[int]) -> list[tuple[int, int, int]]:
    runs: list[tuple[int, int, int]] = []
    start = 0
    while start < len(recipe):
        channel = int(recipe[start])
        end = start + 1
        while end < len(recipe) and int(recipe[end]) == channel:
            end += 1
        runs.append((channel, start, end))
        start = end
    return runs


def _slot_name_for_channel(channel: int, slot_list: list) -> str:
    if 0 <= channel < len(slot_list):
        return str(slot_list[channel])
    return f"channel_{channel}"


def build_vector_preview_parts_from_analysis(
    *,
    analysis: object,
    preview_colors: dict,
    slot_list: list,
    structure_mode: object,
    color_mode: object,
    thickness_mm: float,
    separate_backing: bool,
    include_backing: bool,
    include_outline: bool,
    outline_width_mm: float,
) -> list[VectorPreviewPart]:
    """Build V2 footprint descriptors from vector analysis geometry.

    从 vector analysis 的 2D 几何构建 V2 footprint 描述。第一版只描述普通
    颜色层、普通底板和普通 Outline。
    """

    del color_mode
    try:
        scale_factor = float(getattr(analysis, "scale_factor", 1.0) or 1.0)
    except (TypeError, ValueError):
        scale_factor = 1.0
    if scale_factor <= 0:
        scale_factor = 1.0

    try:
        layer_h = float(getattr(PrinterConfig, "LAYER_HEIGHT", 0.08) or 0.08)
    except (TypeError, ValueError):
        layer_h = 0.08

    seen_names: set[str] = set()
    grouped: dict[int, list[VectorPreviewExtrusion]] = {}
    for shape in getattr(analysis, "matched_shapes", []) or []:
        if not isinstance(shape, dict):
            continue
        geom = _valid_geometry(shape.get("geometry"))
        recipe_raw = shape.get("recipe") or []
        if geom is None or not recipe_raw:
            continue
        geom_mm = _scaled_geometry_mm(geom, scale_factor)
        if geom_mm is None:
            continue
        try:
            recipe = [int(channel) for channel in recipe_raw]
        except (TypeError, ValueError):
            continue
        for channel, start_layer, end_layer in _recipe_channel_runs(recipe):
            grouped.setdefault(channel, []).append(
                VectorPreviewExtrusion(
                    footprint=geom_mm,
                    z_min=float(start_layer) * layer_h,
                    z_max=float(end_layer) * layer_h,
                )
            )

    parts: list[VectorPreviewPart] = []
    for channel in sorted(grouped):
        source_name = _slot_name_for_channel(channel, list(slot_list))
        rgba = _color_for_geometry(
            source_name,
            preview_colors=preview_colors,
            slot_list=list(slot_list),
        )
        export_name = make_vector_glb_export_name(
            source_name=source_name,
            role="color",
            rgba=rgba,
            seen_names=seen_names,
        )
        parts.append(
            VectorPreviewPart(
                source_name=source_name,
                export_name=export_name,
                role="color",
                rgba=rgba,
                is_recolorable=True,
                extrusions=tuple(grouped[channel]),
            )
        )

    structure = resolve_structure_plan(
        analysis, float(outline_width_mm) if include_outline else 0.0,
    )
    backing_footprint = (
        _scaled_geometry_mm(structure.body, structure.mm_per_unit)
        if not structure.body.is_empty else None
    )
    if include_backing and backing_footprint is not None:
        backing_height = max(float(thickness_mm or 0.0), layer_h)
        is_double = "双面" in str(structure_mode or "") or "Double" in str(structure_mode or "")
        z_min = -backing_height if separate_backing or not is_double else 0.0
        z_max = 0.0 if separate_backing or not is_double else backing_height
        rgba = _color_for_geometry(
            "Board",
            preview_colors=preview_colors,
            slot_list=list(slot_list),
        )
        parts.append(
            VectorPreviewPart(
                source_name="Board",
                export_name=make_vector_glb_export_name(
                    source_name="Board",
                    role="backing",
                    rgba=rgba,
                    seen_names=seen_names,
                ),
                role="backing",
                rgba=rgba,
                is_recolorable=False,
                extrusions=(
                    VectorPreviewExtrusion(
                        footprint=backing_footprint,
                        z_min=float(z_min),
                        z_max=float(z_max),
                    ),
                ),
            )
        )

    if include_outline:
        outline = (
            _scaled_geometry_mm(structure.outline, structure.mm_per_unit)
            if not structure.outline.is_empty else None
        )
        if outline is not None:
            max_z = max(
                (extrusion.z_max for part in parts for extrusion in part.extrusions),
                default=layer_h,
            )
            rgba = _color_for_geometry(
                "Outline",
                preview_colors=preview_colors,
                slot_list=list(slot_list),
            )
            parts.append(
                VectorPreviewPart(
                    source_name="Outline",
                    export_name=make_vector_glb_export_name(
                        source_name="Outline",
                        role="outline",
                        rgba=rgba,
                        seen_names=seen_names,
                    ),
                    role="outline",
                    rgba=rgba,
                    is_recolorable=False,
                    extrusions=(
                        VectorPreviewExtrusion(
                            footprint=outline,
                            z_min=0.0,
                            z_max=float(max_z),
                        ),
                    ),
                )
            )

    return parts


def _mesh_from_extrusion_v2(
    extrusion: VectorPreviewExtrusion,
    *,
    rgba: tuple[int, int, int, int],
    pixels_per_mm: float,
) -> trimesh.Trimesh:
    if extrusion.footprints_validated:
        footprints = tuple(extrusion.footprints or (extrusion.footprint,))
    else:
        footprints = _valid_footprints_for_v2(
            extrusion.footprints or (extrusion.footprint,)
        )
    if not footprints:
        raise RuntimeError("V2 vector GLB extrusion has no valid footprints")
    minx, miny, maxx, maxy = _bounds_for_footprints(footprints)
    width = max(1, int(np.ceil((maxx - minx) * pixels_per_mm)))
    height = max(1, int(np.ceil((maxy - miny) * pixels_per_mm)))

    try:
        rasterize, from_origin = _get_vector_v2_rasterizer_modules()
    except MemoryError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"V2 vector GLB rasterizer unavailable: {exc}") from exc

    transform = from_origin(minx, maxy, 1.0 / pixels_per_mm, 1.0 / pixels_per_mm)
    mask = rasterize(
        [(footprint, 1) for footprint in footprints],
        out_shape=(height, width),
        transform=transform,
        fill=0,
        all_touched=True,
        dtype=np.uint8,
    ).astype(bool)
    if not np.any(mask):
        raise RuntimeError("V2 vector GLB footprint rasterized to an empty mask")

    z_height = extrusion.z_max - extrusion.z_min
    if z_height <= 0:
        raise RuntimeError("V2 vector GLB extrusion has non-positive height")
    total_layers = max(1, int(round(z_height * pixels_per_mm)))
    mesh = _build_color_extruded_mesh_v2(
        mask=mask,
        height=height,
        total_layers=total_layers,
        rgba=np.asarray(rgba, dtype=np.uint8),
        assign_face_colors=False,
        component_compose_chunk_size=_V2_VECTOR_COMPONENT_COMPOSE_CHUNK_SIZE,
    )
    if mesh is None:
        raise RuntimeError("V2 vector GLB mesh kernel returned no mesh")

    transform_mm = np.eye(4)
    transform_mm[0, 0] = 1.0 / pixels_per_mm
    transform_mm[1, 1] = 1.0 / pixels_per_mm
    transform_mm[2, 2] = z_height / float(total_layers)
    transform_mm[0, 3] = minx
    transform_mm[1, 3] = miny
    transform_mm[2, 3] = extrusion.z_min
    mesh.apply_transform(transform_mm)
    return mesh


def _mesh_from_analytic_extrusion(
    extrusion: VectorPreviewExtrusion,
) -> trimesh.Trimesh:
    """Extrude parsed Polygon footprints directly without a pixel grid."""

    footprints = (
        tuple(extrusion.footprints or (extrusion.footprint,))
        if extrusion.footprints_validated
        else _valid_footprints_for_v2(
            extrusion.footprints or (extrusion.footprint,)
        )
    )
    polygons: list[Polygon] = []
    for footprint in footprints:
        for polygon in _polygon_components(footprint):
            try:
                area = float(polygon.area)
            except (TypeError, ValueError, AttributeError, OverflowError):
                continue
            if (
                not polygon.is_empty
                and np.isfinite(area)
                and area > _ANALYTIC_MIN_AREA_MM2
            ):
                polygons.append(polygon)
    if not polygons:
        raise RuntimeError("Analytic Vector GLB extrusion has no Polygon footprints")
    z_height = float(extrusion.z_max) - float(extrusion.z_min)
    if not np.isfinite(z_height) or z_height <= 0:
        raise RuntimeError("Analytic Vector GLB extrusion has non-positive height")

    meshes: list[trimesh.Trimesh] = []
    for polygon in polygons:
        try:
            piece = trimesh.creation.extrude_polygon(
                polygon,
                height=1.0,
                engine="earcut",
            )
            vertices = np.asarray(piece.vertices)
            faces = np.asarray(piece.faces)
            if (
                vertices.ndim != 2
                or vertices.shape[1:] != (3,)
                or faces.ndim != 2
                or faces.shape[1:] != (3,)
                or len(vertices) == 0
                or len(faces) == 0
                or not np.isfinite(vertices).all()
                or not bool(piece.is_watertight)
            ):
                raise ValueError("Analytic Vector GLB extrusion is not usable")
        except _ANALYTIC_EXTRUSION_FALLBACK_ERRORS:
            meshes.append(
                _mesh_from_extrusion_v2(
                    VectorPreviewExtrusion(
                        footprint=polygon,
                        z_min=extrusion.z_min,
                        z_max=extrusion.z_max,
                    ),
                    rgba=(255, 255, 255, 255),
                    pixels_per_mm=_ANALYTIC_TOPOLOGY_FALLBACK_PIXELS_PER_MM,
                )
            )
            continue
        vertices = np.asarray(piece.vertices, dtype=np.float64).copy()
        vertices[:, 2] = (
            vertices[:, 2] * z_height + float(extrusion.z_min)
        )
        meshes.append(
            trimesh.Trimesh(
                vertices=vertices,
                faces=np.asarray(piece.faces, dtype=np.int64).copy(),
                process=False,
            )
        )
    if not meshes:
        raise RuntimeError("Analytic Vector GLB extrusion returned no mesh")
    return (
        meshes[0]
        if len(meshes) == 1
        else trimesh.util.concatenate(meshes)
    )


def _valid_footprints_for_v2(
    footprints: tuple[BaseGeometry, ...] | list[BaseGeometry],
) -> tuple[BaseGeometry, ...]:
    return tuple(
        valid
        for footprint in footprints
        if (valid := _valid_geometry(footprint)) is not None
    )


def _bounds_for_footprints(
    footprints: tuple[BaseGeometry, ...] | list[BaseGeometry],
) -> tuple[float, float, float, float]:
    bounds = np.asarray([footprint.bounds for footprint in footprints], dtype=float)
    return (
        float(np.min(bounds[:, 0])),
        float(np.min(bounds[:, 1])),
        float(np.max(bounds[:, 2])),
        float(np.max(bounds[:, 3])),
    )


def _batch_part_extrusions_for_v2(
    part: VectorPreviewPart,
) -> list[VectorPreviewExtrusion]:
    grouped: dict[tuple[float, float], list[BaseGeometry]] = {}
    for extrusion in part.extrusions:
        key = (float(extrusion.z_min), float(extrusion.z_max))
        grouped.setdefault(key, []).extend(extrusion.footprints or (extrusion.footprint,))

    batched: list[VectorPreviewExtrusion] = []
    for (z_min, z_max), footprints in grouped.items():
        valid_footprints = _valid_footprints_for_v2(footprints)
        if not valid_footprints:
            continue
        batched.append(
            VectorPreviewExtrusion(
                footprint=valid_footprints[0],
                z_min=z_min,
                z_max=z_max,
                footprints=valid_footprints,
                footprints_validated=True,
            )
        )
    return batched


def export_vector_glb_preview_v2(
    parts: list[VectorPreviewPart],
    *,
    output_path: str,
    pixels_per_mm: float = 10.0,
) -> str:
    """Export GLB by generating meshes from descriptor footprints."""

    t0 = time.perf_counter()
    glb_scene = trimesh.Scene()
    for part in parts:
        if not part.extrusions:
            raise RuntimeError(f"V2 export requires footprints for {part.source_name}")
        batched_extrusions = _batch_part_extrusions_for_v2(part)
        if not batched_extrusions:
            raise RuntimeError(f"V2 export has no valid footprints for {part.source_name}")
        meshes = [
            _mesh_from_extrusion_v2(
                extrusion,
                rgba=part.rgba,
                pixels_per_mm=pixels_per_mm,
            )
            for extrusion in batched_extrusions
        ]
        if part.role == "color":
            chunks = _pack_meshes_for_uint16_indices(meshes)
        else:
            combined = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
            chunks = [_mesh_geometry_only_copy(combined)]
        if not chunks:
            raise RuntimeError(f"V2 export has no mesh chunks for {part.source_name}")
        for index, chunk in enumerate(chunks):
            export_name = (
                part.export_name
                if len(chunks) == 1
                else f"{part.export_name}_chunk{index + 1:03d}"
            )
            glb_scene.add_geometry(
                _mesh_with_material_rgba(
                    chunk,
                    part.rgba,
                    material_name=f"{export_name}_material",
                ),
                geom_name=export_name,
            )
    if not glb_scene.geometry:
        raise RuntimeError("V2 vector GLB export has no geometry")
    result = _write_glb_scene(
        glb_scene,
        output_path,
        optimize_v2_buffers=True,
    )
    log.info(
        "Vector GLB V2 exported",
        extra={
            "event": "vector_glb_v2_exported",
            "path": str(output_path),
            "part_count": len(parts),
            "geometry_count": len(glb_scene.geometry),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
        },
    )
    return result


def export_vector_quick_preview_glb(
    parts: list[VectorPreviewPart],
    *,
    output_path: str,
) -> str:
    """Export a display-only GLB from analytic Vector footprints."""

    t0 = time.perf_counter()
    glb_scene = trimesh.Scene()
    for part in parts:
        if part.extrusions:
            meshes = [
                _mesh_from_analytic_extrusion(extrusion)
                for extrusion in _batch_part_extrusions_for_v2(part)
            ]
        elif part.fallback_mesh is not None:
            meshes = [_mesh_geometry_only_copy(part.fallback_mesh)]
        else:
            raise RuntimeError(
                f"Analytic Vector GLB part has no geometry: {part.source_name}"
            )
        if not meshes:
            raise RuntimeError(
                f"Analytic Vector GLB part is empty: {part.source_name}"
            )
        if part.role == "color":
            chunks = _pack_meshes_for_uint16_indices(meshes)
        else:
            combined = (
                meshes[0]
                if len(meshes) == 1
                else trimesh.util.concatenate(meshes)
            )
            chunks = _scene_reuse_chunks_for_uint16_indices(combined)
        for index, chunk in enumerate(chunks):
            export_name = (
                part.export_name
                if len(chunks) == 1
                else f"{part.export_name}_chunk{index + 1:03d}"
            )
            exported_mesh = _mesh_with_material_rgba(
                chunk,
                part.rgba,
                material_name=f"{part.export_name}_material",
            )
            if part.height_key is not None:
                exported_mesh.metadata["height_key"] = part.height_key
            glb_scene.add_geometry(
                exported_mesh,
                geom_name=export_name,
            )

    if not glb_scene.geometry:
        raise RuntimeError("Analytic Vector GLB export has no geometry")
    result = _write_glb_scene(
        glb_scene,
        output_path,
        optimize_v2_buffers=True,
    )
    log.info(
        "Analytic Vector GLB exported",
        extra={
            "event": "vector_glb_analytic_exported",
            "path": str(output_path),
            "part_count": len(parts),
            "geometry_count": len(glb_scene.geometry),
            "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
        },
    )
    return result


def export_vector_glb_preview(
    *,
    scene: trimesh.Scene,
    output_path: str,
    structure_mode: object,
    color_mode: object,
    preview_colors: dict,
    slot_list: list,
    analysis: object | None,
    ctx: dict | None,
) -> str:
    """Dispatch SVG GLB preview export with whole-export V1 fallback."""

    kernel = resolve_vector_glb_kernel_choice()
    fallback_parts = build_vector_preview_parts_from_scene(
        scene=scene,
        preview_colors=preview_colors,
        slot_list=list(slot_list),
        copy_fallback_mesh=(kernel == "trimesh_v1"),
    )
    canvas_anchor = _build_preview_canvas_anchor_part(analysis)
    if (
        canvas_anchor is not None
        and all(
            part.export_name != PREVIEW_CANVAS_BOUNDS_NODE_NAME
            for part in fallback_parts
        )
    ):
        fallback_parts.append(canvas_anchor)
    if kernel == "trimesh_v1":
        return export_vector_glb_preview_v1(fallback_parts, output_path=output_path)

    try:
        return export_vector_glb_preview_v2_scene_reuse(
            fallback_parts,
            output_path=output_path,
        )
    except MemoryError:
        raise
    except Exception as exc:
        log.warning(
            "Vector GLB V2 failed; falling back to V1",
            extra={
                "event": "vector_glb_v2_runtime_fallback",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "fallback_kernel": "trimesh_v1",
            },
        )
        failure_traceback = exc.__traceback__
        if failure_traceback is not None:
            traceback.clear_frames(failure_traceback)
        del failure_traceback

    # Leave the exception handler before retrying so Python releases its
    # traceback and any completed V2 chunks/GLB buffers.
    gc.collect()
    return export_vector_glb_preview_v1(fallback_parts, output_path=output_path)
