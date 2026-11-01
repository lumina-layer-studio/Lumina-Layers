"""Canonical physical-grid geometry for native Vector layer runs.

Native SVG coordinates are converted to millimetres and noded on one shared
integer grid before any 3D allocation.  This makes shared boundaries identical
by construction and keeps independent printable islands explicit.

原生 SVG 坐标在分配三维网格前统一转换为毫米，并在共享整数网格上节点化；
因此共享边天然一致，独立可打印小岛也不会被静默丢弃。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Sequence

import numpy as np
import shapely
import trimesh
from mapbox_earcut import triangulate_float64
from shapely import STRtree, affinity, set_precision
from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient
from shapely.validation import make_valid

from core.vector_mesh_spill import AdaptiveMeshAccumulator
from core.svg_coordinate_domain import PRINT_GRID_KEY


@dataclass(frozen=True)
class VectorLayerGeometryPolicy:
    """Physical-grid and fidelity policy for one Vector run group.
    单个 Vector 走层组的物理网格与保真策略。
    """

    grid_mm: float = 0.0001


def resolve_vector_writer_grid_mm(
    maximum_abs_coordinate_mm: float,
    *,
    minimum_mm: float = VectorLayerGeometryPolicy().grid_mm,
) -> float:
    """Resolve a binary grid whose coordinates are exact in float32 output.

    Distinct decimal-grid points can still become collinear after independent
    float32 rounding. A power-of-two grid avoids that second projection.
    Four ULPs also bound integer coordinates below the float32 significand limit.

    Args:
        maximum_abs_coordinate_mm: Largest absolute XY coordinate in mm.
            XY 坐标绝对值的毫米上限。
        minimum_mm: Minimum canonical grid size in mm.
            规范网格的最小毫米尺寸。

    Returns:
        Writer-safe canonical grid size in mm.
        写出安全的规范网格尺寸（毫米）。
    """

    maximum_coordinate = float(maximum_abs_coordinate_mm)
    minimum_grid = float(minimum_mm)
    if (
        not math.isfinite(maximum_coordinate)
        or maximum_coordinate < 0.0
        or not math.isfinite(minimum_grid)
        or minimum_grid <= 0.0
    ):
        raise ValueError("Vector writer grid inputs must be finite and positive")
    writer_value = np.float32(maximum_coordinate)
    writer_ulp = abs(float(np.spacing(writer_value)))
    if not math.isfinite(writer_ulp):
        raise ValueError("Vector physical coordinates exceed float32 writer range")
    required_grid = max(minimum_grid, writer_ulp * 4.0)
    significand, exponent = math.frexp(required_grid)
    return math.ldexp(1.0, exponent - 1 if significand == 0.5 else exponent)


def snap_vector_writer_coordinate_mm(
    coordinate_mm: float,
    *,
    grid_mm: float,
) -> float:
    """Snap one coordinate with the same half-grid rule as GEOS.
    使用与 GEOS 相同的半网格规则对单个坐标取整。

    Args:
        coordinate_mm: Coordinate in physical millimetres.
            物理毫米坐标。
        grid_mm: Canonical writer grid size in millimetres.
            规范写出网格尺寸（毫米）。

    Returns:
        Coordinate snapped to the canonical writer grid.
        吸附到规范写出网格后的坐标。
    """

    coordinate = float(coordinate_mm)
    grid = float(grid_mm)
    if (
        not math.isfinite(coordinate)
        or not math.isfinite(grid)
        or grid <= 0.0
    ):
        raise ValueError("Vector writer coordinate inputs must be finite")
    scaled_coordinate = coordinate / grid
    if not math.isfinite(scaled_coordinate):
        raise ValueError("Vector writer coordinate exceeds canonical grid range")
    return float(math.floor(scaled_coordinate + 0.5) * grid)


@dataclass(frozen=True)
class _IndexedPolygon:
    """One canonical polygon stored only as compact integer rings."""

    exterior_units: np.ndarray
    hole_units: tuple[np.ndarray, ...]
    coordinate_alias_count: int = 0


@dataclass(frozen=True)
class _IndexedRunGroup:
    """Compact indexed rings for one fixed-Z printable footprint."""

    polygons: tuple[_IndexedPolygon, ...]
    grid_mm: float
    area_mm2: float
    coordinate_count: int
    hole_count: int


@dataclass(frozen=True)
class _ValidatedCap:
    """One checked cap and its reusable directed boundary edges."""

    faces: np.ndarray
    boundary_edges: np.ndarray


@dataclass(frozen=True)
class _PhysicalLayerSlab:
    geometry: BaseGeometry
    z_start_mm: float
    z_end_mm: float


def _ring_with_contact_nodes(
    ring: np.ndarray,
    contact_coordinates: set[tuple[int, int]],
) -> np.ndarray:
    """Insert exact point contacts into every ring segment they lie on."""

    if not contact_coordinates:
        return ring
    output: list[tuple[int, int]] = []
    ring_size = len(ring)
    for index in range(ring_size):
        start = ring[index]
        end = ring[(index + 1) % ring_size]
        output.append((int(start[0]), int(start[1])))
        delta_x = int(end[0]) - int(start[0])
        delta_y = int(end[1]) - int(start[1])
        squared_length = delta_x * delta_x + delta_y * delta_y
        interior: list[tuple[int, tuple[int, int]]] = []
        for coordinate in contact_coordinates:
            relative_x = int(coordinate[0]) - int(start[0])
            relative_y = int(coordinate[1]) - int(start[1])
            projection = relative_x * delta_x + relative_y * delta_y
            if (
                relative_x * delta_y - relative_y * delta_x == 0
                and 0 < projection < squared_length
            ):
                interior.append((projection, coordinate))
        output.extend(coordinate for _projection, coordinate in sorted(interior))
    return np.asarray(output, dtype=np.int64)


def _node_indexed_polygon_ring_contacts(
    polygon: _IndexedPolygon,
) -> _IndexedPolygon:
    """Represent every cross-ring point contact as an explicit ring vertex."""

    rings = [polygon.exterior_units, *polygon.hole_units]
    if len(rings) <= 1:
        return polygon
    ring_lines = [
        LineString(np.vstack((ring, ring[:1])).astype(np.float64))
        for ring in rings
    ]
    tree = STRtree(ring_lines)
    pairs = np.asarray(
        tree.query(ring_lines, predicate="intersects"),
        dtype=np.int64,
    )
    contacts: list[set[tuple[int, int]]] = [set() for _ring in rings]
    if pairs.size:
        for first_raw, second_raw in pairs.T:
            first = int(first_raw)
            second = int(second_raw)
            if first >= second:
                continue
            intersection = ring_lines[first].intersection(ring_lines[second])
            for part in shapely.get_parts(intersection):
                if part.geom_type != "Point":
                    raise ValueError("Vector polygon rings overlap on the writer grid")
                coordinate = np.asarray(part.coords[0], dtype=np.float64)
                integer_coordinate = np.rint(coordinate).astype(np.int64)
                if not np.array_equal(coordinate, integer_coordinate.astype(np.float64)):
                    raise ValueError(
                        "Vector polygon ring contact left the canonical grid"
                    )
                key = (int(integer_coordinate[0]), int(integer_coordinate[1]))
                contacts[first].add(key)
                contacts[second].add(key)

    contact_occurrence_count = sum(len(items) for items in contacts)
    unique_contacts = set().union(*contacts)
    coordinate_alias_count = contact_occurrence_count - len(unique_contacts)
    if coordinate_alias_count == 0:
        return polygon

    noded_rings = [
        _ring_with_contact_nodes(ring, ring_contacts)
        for ring, ring_contacts in zip(rings, contacts)
    ]
    return _IndexedPolygon(
        exterior_units=noded_rings[0],
        hole_units=tuple(noded_rings[1:]),
        coordinate_alias_count=int(coordinate_alias_count),
    )


def _printable_polygon_parts(geometry: BaseGeometry) -> tuple[Polygon, ...]:
    """Extract positive-area polygons while discarding dimensional residue."""

    if isinstance(geometry, GeometryCollection):
        return tuple(
            polygon
            for item in geometry.geoms
            for polygon in _printable_polygon_parts(item)
        )
    if not isinstance(geometry, (Polygon, MultiPolygon)):
        return ()
    if geometry.is_empty or float(geometry.area) <= 0.0:
        return ()
    if not geometry.is_valid:
        return _printable_polygon_parts(make_valid(geometry))
    if isinstance(geometry, Polygon):
        return (geometry,)
    return tuple(
        polygon
        for item in geometry.geoms
        for polygon in _printable_polygon_parts(item)
    )


def _polygon_parts(geometry: BaseGeometry) -> tuple[Polygon, ...]:
    """Return printable polygon parts, ignoring zero-area collection residue."""

    parts = _printable_polygon_parts(geometry)
    if not parts:
        raise ValueError("Vector run group requires polygonal geometry")
    return parts


def _signed_twice_ring_area(coordinates: np.ndarray) -> float:
    values = np.asarray(coordinates, dtype=np.float64)
    return float(
        np.sum(
            values[:, 0] * np.roll(values[:, 1], -1)
            - values[:, 1] * np.roll(values[:, 0], -1),
            dtype=np.float64,
        )
    )


def _indexed_polygon_area_mm2(
    polygon: _IndexedPolygon,
    *,
    grid_mm: float,
) -> float:
    twice_area_units = abs(_signed_twice_ring_area(polygon.exterior_units))
    twice_area_units -= math.fsum(
        abs(_signed_twice_ring_area(ring))
        for ring in polygon.hole_units
    )
    if not math.isfinite(twice_area_units) or twice_area_units <= 0.0:
        raise ValueError("Vector canonical polygon has non-positive area")
    return twice_area_units * float(grid_mm) * float(grid_mm) * 0.5


def _canonicalize_ring_start(coordinates: np.ndarray) -> np.ndarray:
    """Give an open ring one start independent of its SVG serialization."""

    values = np.asarray(coordinates)
    start_index = int(np.lexsort((values[:, 0], values[:, 1]))[0])
    if start_index == 0:
        return values
    return np.ascontiguousarray(
        np.concatenate((values[start_index:], values[:start_index]), axis=0)
    )


def _oriented_polygon_rings(polygon: _IndexedPolygon) -> list[np.ndarray]:
    rings = [polygon.exterior_units, *polygon.hole_units]
    oriented_rings: list[np.ndarray] = []
    for index, ring in enumerate(rings):
        signed_area = _signed_twice_ring_area(ring)
        if signed_area == 0.0 or not math.isfinite(signed_area):
            raise ValueError("Vector canonical ring has zero signed area")
        should_be_positive = index == 0
        if (signed_area > 0.0) != should_be_positive:
            oriented_ring = np.ascontiguousarray(ring[::-1])
        else:
            oriented_ring = ring
        oriented_rings.append(_canonicalize_ring_start(oriented_ring))
    return oriented_rings


def _canonical_cap_face_count(
    rings: Sequence[np.ndarray],
    *,
    coordinate_alias_count: int,
) -> int:
    """Return the planar-triangulation face count for possibly touching rings."""

    vertex_count = sum(len(ring) for ring in rings)
    coordinate_aliases = int(coordinate_alias_count)
    if coordinate_aliases < 0:
        raise ValueError("Vector canonical cap has invalid coordinate aliases")
    face_count = (
        vertex_count
        + 2 * (len(rings) - 1)
        - 2
        - 2 * coordinate_aliases
    )
    if face_count <= 0:
        raise ValueError("Vector canonical cap has no printable faces")
    return int(face_count)


def _cap_expected_boundary_edges(ring_ends: np.ndarray) -> np.ndarray:
    ring_starts = np.concatenate((np.asarray([0]), ring_ends[:-1])).astype(np.int64)
    boundary_chunks = []
    for ring_start, ring_end in zip(ring_starts, ring_ends.astype(np.int64)):
        indices = np.arange(int(ring_start), int(ring_end), dtype=np.int64)
        boundary_chunks.append(
            np.sort(np.column_stack((indices, np.roll(indices, -1))), axis=1)
        )
    return np.vstack(boundary_chunks)


def _canonical_coordinate_edges(
    vertices_2d: np.ndarray,
    edges: np.ndarray,
    *,
    grid_mm: float,
) -> np.ndarray:
    """Return undirected boundary segments as canonical integer coordinates."""

    integer_vertices = np.rint(
        np.asarray(vertices_2d, dtype=np.float64) / float(grid_mm)
    ).astype(np.int64)
    pairs = integer_vertices[np.asarray(edges, dtype=np.int64).reshape((-1, 2))]
    swap = (pairs[:, 0, 0] > pairs[:, 1, 0]) | (
        (pairs[:, 0, 0] == pairs[:, 1, 0])
        & (pairs[:, 0, 1] > pairs[:, 1, 1])
    )
    if bool(np.any(swap)):
        pairs = pairs.copy()
        pairs[swap] = pairs[swap, ::-1]
    return pairs.reshape((-1, 4))


def _sorted_coordinate_edges(edges: np.ndarray) -> np.ndarray:
    """Sort canonical coordinate-edge rows deterministically."""

    values = np.asarray(edges, dtype=np.int64).reshape((-1, 4))
    if len(values) <= 1:
        return values
    order = np.lexsort(
        (values[:, 3], values[:, 2], values[:, 1], values[:, 0])
    )
    return values[order]


def _straight_ring_chain(
    vertices_2d: np.ndarray,
    ring_ends: np.ndarray,
    start_index: int,
    end_index: int,
    *,
    grid_mm: float,
) -> np.ndarray | None:
    """Return the noded ring arc represented by one triangulator edge."""

    integer_vertices = np.rint(
        np.asarray(vertices_2d, dtype=np.float64) / float(grid_mm)
    ).astype(np.int64)
    ring_starts = np.concatenate((np.asarray([0]), ring_ends[:-1])).astype(np.int64)
    start_coordinate = integer_vertices[start_index]
    end_coordinate = integer_vertices[end_index]
    for ring_start, ring_end in zip(ring_starts, ring_ends.astype(np.int64)):
        ring = np.arange(int(ring_start), int(ring_end), dtype=np.int64)
        ring_coordinates = integer_vertices[ring]
        start_positions = np.flatnonzero(
            np.all(ring_coordinates == start_coordinate, axis=1)
        )
        end_positions = np.flatnonzero(
            np.all(ring_coordinates == end_coordinate, axis=1)
        )
        for start_position in start_positions:
            for end_position in end_positions:
                if int(start_position) == int(end_position):
                    continue
                ring_size = len(ring)
                forward_length = (
                    (int(end_position) - int(start_position)) % ring_size
                ) + 1
                backward_length = (
                    (int(start_position) - int(end_position)) % ring_size
                ) + 1
                forward = ring[
                    (int(start_position) + np.arange(forward_length)) % ring_size
                ]
                backward = ring[
                    (int(start_position) - np.arange(backward_length)) % ring_size
                ]

                delta = end_coordinate - start_coordinate
                squared_length = int(np.dot(delta, delta))
                for candidate in (forward, backward):
                    if len(candidate) <= 2:
                        continue
                    coordinates = integer_vertices[candidate]
                    relative = coordinates - start_coordinate
                    cross = relative[:, 0] * delta[1] - relative[:, 1] * delta[0]
                    projection = relative @ delta
                    if (
                        np.all(cross == 0.0)
                        and np.all(projection >= 0.0)
                        and np.all(projection <= squared_length)
                        and np.all(projection[1:] > projection[:-1])
                    ):
                        return candidate
    return None


def _restore_noded_cap_boundary(
    vertices_2d: np.ndarray,
    cap_faces: np.ndarray,
    ring_ends: np.ndarray,
    *,
    grid_mm: float,
) -> np.ndarray:
    """Split cap triangles at collinear ring nodes omitted by triangulators."""

    faces = _expand_writer_degenerate_cap_faces(
        vertices_2d,
        np.asarray(cap_faces, dtype=np.int64).reshape((-1, 3)),
        grid_mm=grid_mm,
    )
    expected_boundary = _cap_expected_boundary_edges(ring_ends)
    expected_keys = {
        tuple(int(value) for value in edge)
        for edge in _canonical_coordinate_edges(
            vertices_2d,
            expected_boundary,
            grid_mm=grid_mm,
        )
    }
    for _split_index in range(len(vertices_2d)):
        cap_edges = np.sort(
            faces[:, [[0, 1], [1, 2], [2, 0]]].reshape((-1, 2)),
            axis=1,
        )
        unique_edges, counts = np.unique(cap_edges, axis=0, return_counts=True)
        boundary_edges = unique_edges[counts == 1]
        boundary_coordinate_edges = _canonical_coordinate_edges(
            vertices_2d,
            boundary_edges,
            grid_mm=grid_mm,
        )
        unexpected = next(
            (
                edge
                for edge, coordinate_edge in zip(
                    boundary_edges,
                    boundary_coordinate_edges,
                )
                if tuple(int(value) for value in coordinate_edge)
                not in expected_keys
            ),
            None,
        )
        if unexpected is None:
            return faces

        first = int(unexpected[0])
        second = int(unexpected[1])
        chain = _straight_ring_chain(
            vertices_2d,
            ring_ends,
            first,
            second,
            grid_mm=grid_mm,
        )
        if chain is None:
            raise ValueError(
                "Vector canonical cap introduced a non-ring boundary edge"
            )
        owning_faces = np.flatnonzero(
            np.sum(np.isin(faces, [first, second]), axis=1) == 2
        )
        if len(owning_faces) != 1:
            raise ValueError(
                "Vector canonical cap boundary edge has ambiguous ownership"
            )
        face_index = int(owning_faces[0])
        opposite = next(
            int(index)
            for index in faces[face_index]
            if int(index) not in {first, second}
        )
        replacement = np.column_stack(
            (
                chain[:-1],
                chain[1:],
                np.full(len(chain) - 1, opposite, dtype=np.int64),
            )
        )
        faces = np.concatenate(
            (faces[:face_index], replacement, faces[face_index + 1 :]),
            axis=0,
        )
    raise ValueError("Vector canonical cap could not restore all ring nodes")


def _split_coincident_cap_fans(
    vertices_2d: np.ndarray,
    cap_faces: np.ndarray,
    *,
    grid_mm: float,
    expected_coordinate_alias_count: int,
) -> np.ndarray:
    """Give every material fan at a point contact its own vertex index.

    OGC-valid polygon rings may meet at one coordinate. Constrained
    triangulators collapse those coordinate aliases to one index, which makes
    the future vertical edge non-manifold. The printable cap already contains
    one edge-connected triangle fan per boundary occurrence, so reuse the
    existing coincident ring indices to separate those fans without moving a
    coordinate or changing coverage.
    """

    faces = np.asarray(cap_faces, dtype=np.int64).reshape((-1, 3)).copy()
    integer_vertices = np.rint(
        np.asarray(vertices_2d, dtype=np.float64) / float(grid_mm)
    ).astype(np.int64)
    _coordinates, inverse, counts = np.unique(
        integer_vertices,
        axis=0,
        return_inverse=True,
        return_counts=True,
    )
    actual_coordinate_alias_count = int(np.sum(counts - 1, dtype=np.int64))
    if actual_coordinate_alias_count != int(expected_coordinate_alias_count):
        raise ValueError("Vector cap coordinate aliases differ from its rings")
    for coordinate_group in np.flatnonzero(counts > 1):
        aliases = np.flatnonzero(inverse == coordinate_group).astype(np.int64)
        representative = int(aliases[0])
        for alias in aliases[1:]:
            faces[faces == int(alias)] = representative

        incident_faces = np.flatnonzero(
            np.any(faces == representative, axis=1)
        ).astype(np.int64)
        if len(incident_faces) == 0:
            raise ValueError("Vector cap omitted a coincident boundary vertex")

        neighbor_faces: dict[int, list[int]] = {}
        face_neighbors: dict[int, tuple[int, ...]] = {}
        for raw_face_index in incident_faces:
            face_index = int(raw_face_index)
            neighbors = tuple(
                int(index)
                for index in faces[face_index]
                if int(index) != representative
            )
            if len(neighbors) != 2:
                raise ValueError("Vector cap has a degenerate contact fan")
            face_neighbors[face_index] = neighbors
            for neighbor in neighbors:
                neighbor_faces.setdefault(neighbor, []).append(face_index)

        remaining = {int(index) for index in incident_faces}
        components: list[list[int]] = []
        while remaining:
            pending = [min(remaining)]
            remaining.remove(pending[0])
            component: list[int] = []
            while pending:
                face_index = pending.pop()
                component.append(face_index)
                for neighbor in face_neighbors[face_index]:
                    for adjacent in neighbor_faces[neighbor]:
                        if adjacent in remaining:
                            remaining.remove(adjacent)
                            pending.append(adjacent)
            components.append(sorted(component))

        components.sort(key=lambda component: component[0])
        if len(components) != len(aliases):
            raise ValueError(
                "Vector cap contact fans do not match boundary occurrences"
            )
        for alias, component in zip(aliases, components):
            component_faces = faces[component].copy()
            component_faces[component_faces == representative] = int(alias)
            faces[component] = component_faces
    return faces


def _oriented_cap_boundary_edges(cap_faces: np.ndarray) -> np.ndarray:
    """Return cap boundary edges in the owning CCW triangle direction."""

    faces = np.asarray(cap_faces, dtype=np.int64).reshape((-1, 3))
    directed_edges = faces[:, [[0, 1], [1, 2], [2, 0]]].reshape((-1, 2))
    undirected_edges = np.sort(directed_edges, axis=1)
    _unique_edges, first_indices, counts = np.unique(
        undirected_edges,
        axis=0,
        return_index=True,
        return_counts=True,
    )
    if np.any((counts != 1) & (counts != 2)):
        raise ValueError("Vector canonical cap has non-manifold edge incidence")
    return directed_edges[first_indices[counts == 1]]


def _validate_cap_indices(
    vertices_2d: np.ndarray,
    cap_faces: np.ndarray,
    ring_ends: np.ndarray,
    *,
    expected_area_mm2: float,
    grid_mm: float,
    coordinate_alias_count: int = 0,
) -> _ValidatedCap:
    """Orient and validate one Earcut cap without building a 3D fallback."""

    faces = np.asarray(cap_faces, dtype=np.int64).reshape((-1, 3))
    if len(faces) == 0 or np.any(faces < 0) or np.any(faces >= len(vertices_2d)):
        raise ValueError("Vector canonical cap triangulation has invalid indices")
    if np.any(
        (faces[:, 0] == faces[:, 1])
        | (faces[:, 1] == faces[:, 2])
        | (faces[:, 2] == faces[:, 0])
    ):
        raise ValueError("Vector canonical cap triangulation is index-degenerate")

    signed_twice_area_units = _integer_triangle_signed_twice_area(
        vertices_2d,
        faces,
        grid_mm=grid_mm,
    )
    if np.any(signed_twice_area_units == 0):
        raise ValueError("Vector canonical cap triangulation is coordinate-degenerate")
    reversed_faces = signed_twice_area_units < 0
    if bool(np.any(reversed_faces)):
        faces[reversed_faces] = faces[reversed_faces][:, [0, 2, 1]]
        signed_twice_area_units[reversed_faces] *= -1

    cap_area = (
        math.fsum(float(value) for value in signed_twice_area_units)
        * float(grid_mm)
        * float(grid_mm)
        * 0.5
    )
    area_tolerance = max(1e-9, expected_area_mm2 * 1e-9)
    if abs(cap_area - expected_area_mm2) > area_tolerance:
        raise ValueError("Vector canonical cap triangulation changed coverage")

    if coordinate_alias_count:
        faces = _split_coincident_cap_fans(
            vertices_2d,
            faces,
            grid_mm=grid_mm,
            expected_coordinate_alias_count=int(coordinate_alias_count),
        )
    cap_boundary = _oriented_cap_boundary_edges(faces)
    boundary_degrees = np.bincount(
        cap_boundary.reshape(-1),
        minlength=len(vertices_2d),
    )
    used_boundary_vertices = np.unique(cap_boundary)
    if np.any(boundary_degrees[used_boundary_vertices] != 2):
        raise ValueError("Vector canonical cap retains a pinched boundary vertex")

    expected_boundary = _cap_expected_boundary_edges(ring_ends)
    if not np.array_equal(
        _sorted_coordinate_edges(
            _canonical_coordinate_edges(
                vertices_2d,
                cap_boundary,
                grid_mm=grid_mm,
            )
        ),
        _sorted_coordinate_edges(
            _canonical_coordinate_edges(
                vertices_2d,
                expected_boundary,
                grid_mm=grid_mm,
            )
        ),
    ):
        raise ValueError("Vector canonical cap boundary differs from its rings")
    return _ValidatedCap(faces=faces, boundary_edges=cap_boundary)


def _triangle_signed_twice_area(triangles: np.ndarray) -> np.ndarray:
    """Return signed doubled XY area for a ``(n, 3, 2)`` triangle batch."""

    return (
        (triangles[:, 1, 0] - triangles[:, 0, 0])
        * (triangles[:, 2, 1] - triangles[:, 0, 1])
        - (triangles[:, 1, 1] - triangles[:, 0, 1])
        * (triangles[:, 2, 0] - triangles[:, 0, 0])
    )


def _integer_triangle_signed_twice_area(
    vertices_2d: np.ndarray,
    faces: np.ndarray,
    *,
    grid_mm: float,
) -> np.ndarray:
    """Return exact signed doubled areas in canonical integer-grid units."""

    units = np.rint(
        np.asarray(vertices_2d, dtype=np.float64) / float(grid_mm)
    ).astype(np.int64)
    triangles = units[np.asarray(faces, dtype=np.int64)]
    return (
        (triangles[:, 1, 0] - triangles[:, 0, 0])
        * (triangles[:, 2, 1] - triangles[:, 0, 1])
        - (triangles[:, 1, 1] - triangles[:, 0, 1])
        * (triangles[:, 2, 0] - triangles[:, 0, 0])
    )


def _expand_writer_degenerate_cap_faces(
    vertices_2d: np.ndarray,
    faces: np.ndarray,
    *,
    grid_mm: float,
) -> np.ndarray:
    """Flip a cap ear diagonal until every triangle survives float32 output.

    A triangulator can retain a zero-area ear to keep a collinear boundary
    vertex, or emit an extremely thin positive-area ear that becomes collinear
    in float32. In both cases the ear and its positive neighbour form a local
    quadrilateral. Flipping their shared diagonal preserves the exact integer
    boundary and total area while producing two writer-representable faces.
    """

    output = np.asarray(faces, dtype=np.int64).reshape((-1, 3)).copy()
    units = np.rint(
        np.asarray(vertices_2d, dtype=np.float64) / float(grid_mm)
    ).astype(np.int64)
    # Test the geometry the writer actually stores. Doing the determinant in
    # float32 can cancel a nonzero area even when every coordinate is exact.
    writer_vertices = np.asarray(vertices_2d, dtype=np.float32).astype(np.float64)
    maximum_repairs = max(1, len(output))
    for _repair_index in range(maximum_repairs):
        areas = _integer_triangle_signed_twice_area(
            vertices_2d,
            output,
            grid_mm=grid_mm,
        )
        writer_triangles = writer_vertices[output]
        writer_areas = _triangle_signed_twice_area(writer_triangles)
        degenerate = (areas == 0) | (writer_areas == 0.0)
        degenerate_indices = np.flatnonzero(degenerate)
        if len(degenerate_indices) == 0:
            return output
        split = None
        split_zero_index = None
        # Earcut can encode a straight boundary chain as several consecutive
        # zero-area ears. Start at the end of that chain, where a positive-area
        # neighbour exists, then work inward. Deleting the first ear eagerly
        # would remove a real boundary segment.
        for raw_zero_index in degenerate_indices[::-1]:
            zero_index = int(raw_zero_index)
            zero_face = output[zero_index]
            if len(set(int(index) for index in zero_face)) != 3:
                raise ValueError("Vector canonical cap has an index-degenerate ear")

            for middle_position in range(3):
                middle = int(zero_face[middle_position])
                endpoints = [
                    int(zero_face[position])
                    for position in range(3)
                    if position != middle_position
                ]
                first, second = endpoints
                first_to_middle = units[middle] - units[first]
                second_to_middle = units[middle] - units[second]
                if int(np.dot(first_to_middle, second_to_middle)) > 0:
                    continue
                candidate_faces = np.flatnonzero(
                    np.sum(np.isin(output, endpoints), axis=1) == 2
                )
                candidate_faces = candidate_faces[
                    (candidate_faces != zero_index)
                    & (~degenerate[candidate_faces])
                ]
                for adjacent_index in candidate_faces:
                    adjacent = output[int(adjacent_index)]
                    opposite = next(
                        int(index)
                        for index in adjacent
                        if int(index) not in {first, second}
                    )
                    replacement = np.asarray(
                        [
                            (first, middle, opposite),
                            (middle, second, opposite),
                        ],
                        dtype=np.int64,
                    )
                    replacement_areas = _integer_triangle_signed_twice_area(
                        vertices_2d,
                        replacement,
                        grid_mm=grid_mm,
                    )
                    replacement_writer_areas = _triangle_signed_twice_area(
                        writer_vertices[replacement]
                    )
                    expected_twice_area = (
                        abs(int(areas[int(adjacent_index)]))
                        + abs(int(areas[zero_index]))
                    )
                    if (
                        np.any(replacement_areas == 0)
                        or np.any(replacement_writer_areas == 0.0)
                        or int(np.sum(np.abs(replacement_areas), dtype=np.int64))
                        != expected_twice_area
                    ):
                        continue
                    split = (int(adjacent_index), replacement)
                    split_zero_index = zero_index
                    break
                if split is not None:
                    break
            if split is not None:
                break
        if split is None:
            zero_index = int(degenerate_indices[0])
            if int(areas[zero_index]) != 0:
                raise ValueError(
                    "Vector cap contains an unrepresentable float32 ear"
                )
            output = np.delete(output, zero_index, axis=0)
            if len(output) == 0:
                raise ValueError(
                    "Vector canonical cap contains no positive-area triangles"
                )
            continue
        adjacent_index, replacement = split
        assert split_zero_index is not None
        output[split_zero_index] = replacement[0]
        output[adjacent_index] = replacement[1]
    raise ValueError("Vector canonical cap has too many degenerate ears")


def _canonical_cap_faces(
    polygon: _IndexedPolygon,
    vertices_2d: np.ndarray,
    ring_ends: np.ndarray,
    *,
    grid_mm: float,
) -> np.ndarray:
    """Triangulate canonical rings without changing their printable boundary."""

    if not polygon.hole_units:
        faces = np.asarray(
            triangulate_float64(vertices_2d, ring_ends),
            dtype=np.int64,
        ).reshape((-1, 3))
        if (
            len(faces) == 0
            or np.any(faces < 0)
            or np.any(faces >= len(vertices_2d))
        ):
            raise ValueError("Vector canonical cap triangulation has invalid indices")
        return faces

    ring_starts = np.concatenate(
        (np.asarray([0], dtype=np.int64), ring_ends[:-1].astype(np.int64))
    )
    ring_stops = ring_ends.astype(np.int64)
    polygon_geometry = Polygon(
        vertices_2d[ring_starts[0] : ring_stops[0]],
        [
            vertices_2d[start:stop]
            for start, stop in zip(ring_starts[1:], ring_stops[1:])
        ],
    )
    try:
        triangles = shapely.constrained_delaunay_triangles(polygon_geometry)
    except shapely.errors.GEOSException:
        # GEOS's ear scan can stall on valid, point-touching rings depending on
        # their traversal. Rebuild that traversal once with a zero-distance
        # buffer, accepting only the exact same polygon. Original ring indices
        # below still own the caps/walls, including collinear/contact vertices.
        if not polygon_geometry.is_valid:
            raise
        reordered = polygon_geometry.buffer(0)
        if not isinstance(reordered, Polygon) or not reordered.equals(polygon_geometry):
            raise
        triangles = shapely.constrained_delaunay_triangles(reordered)
    triangle_parts = shapely.get_parts(triangles)
    coordinate_counts = np.asarray(
        shapely.get_num_coordinates(triangle_parts),
        dtype=np.int64,
    )
    if len(coordinate_counts) == 0 or np.any(coordinate_counts != 4):
        raise ValueError("Vector holed cap triangulation did not produce triangles")
    triangle_coordinates = np.asarray(
        shapely.get_coordinates(triangle_parts),
        dtype=np.float64,
    ).reshape((-1, 4, 2))[:, :3, :]

    canonical_units = np.rint(vertices_2d / float(grid_mm)).astype(np.int64)
    triangle_units = np.rint(
        triangle_coordinates.reshape((-1, 2)) / float(grid_mm)
    ).astype(np.int64)
    key_dtype = np.dtype([("x", np.int64), ("y", np.int64)])
    canonical_keys = np.ascontiguousarray(canonical_units).view(key_dtype).reshape(-1)
    triangle_keys = np.ascontiguousarray(triangle_units).view(key_dtype).reshape(-1)
    order = np.argsort(canonical_keys, kind="quicksort")
    sorted_keys = canonical_keys[order]
    positions = np.searchsorted(sorted_keys, triangle_keys)
    if (
        np.any(positions >= len(sorted_keys))
        or not np.array_equal(sorted_keys[positions], triangle_keys)
    ):
        raise ValueError("Vector holed cap introduced a non-ring vertex")
    return order[positions].reshape((-1, 3))


def _extrude_indexed_run_group(
    prepared: _IndexedRunGroup,
    *,
    height_mm: float,
    z_offset_mm: float,
) -> trimesh.Trimesh:
    """Build one closed indexed prism mesh from canonical physical rings.
    从规范物理坐标环直接构建一个闭合索引棱柱网格。

    Caps and walls share the exact same ring indices. No geometric repair or
    alternate 3D fallback is attempted after this point. / 顶底面与侧壁复用
    完全相同的环索引；进入本步骤后不再尝试几何修补或备用三维路径。
    """

    height = float(height_mm)
    z_offset = float(z_offset_mm)
    if not math.isfinite(height) or height <= 0.0:
        raise ValueError("Vector prism height must be positive finite")
    if not math.isfinite(z_offset):
        raise ValueError("Vector prism Z offset must be finite")
    if not prepared.polygons:
        raise ValueError("Vector prism requires canonical polygons")
    if np.float32(z_offset) == np.float32(z_offset + height):
        raise ValueError("Vector prism height collapses in float32 writer space")

    polygon_rings = [_oriented_polygon_rings(polygon) for polygon in prepared.polygons]
    ring_vertex_counts = [
        sum(len(ring) for ring in rings) for rings in polygon_rings
    ]
    cap_face_counts = [
        _canonical_cap_face_count(
            rings,
            coordinate_alias_count=int(polygon.coordinate_alias_count),
        )
        for polygon, rings in zip(prepared.polygons, polygon_rings)
    ]
    vertex_count = 2 * sum(ring_vertex_counts)
    face_count = sum(
        2 * cap_face_count + 2 * ring_vertex_count
        for cap_face_count, ring_vertex_count in zip(
            cap_face_counts,
            ring_vertex_counts,
        )
    )
    if vertex_count > np.iinfo(np.uint32).max:
        raise ValueError("Vector canonical mesh exceeds uint32 vertex indices")

    vertices = np.empty((vertex_count, 3), dtype=np.float64)
    faces = np.empty((face_count, 3), dtype=np.int64)
    vertex_cursor = 0
    face_cursor = 0

    for polygon, rings, local_vertex_count, expected_cap_face_count in zip(
        prepared.polygons,
        polygon_rings,
        ring_vertex_counts,
        cap_face_counts,
    ):
        vertices_2d = np.vstack(rings).astype(np.float64)
        ring_ends = np.cumsum([len(ring) for ring in rings], dtype=np.uint32)
        raw_cap_faces = _canonical_cap_faces(
            polygon,
            vertices_2d,
            ring_ends,
            grid_mm=1.0,
        )
        # Keep topology in print-grid units through triangulation. The physical
        # coordinates below are only for writer-representability checks/output.
        vertices_2d *= float(prepared.grid_mm)
        expected_area = _indexed_polygon_area_mm2(
            polygon,
            grid_mm=float(prepared.grid_mm),
        )
        validated_cap = _validate_cap_indices(
            vertices_2d,
            _restore_noded_cap_boundary(
                vertices_2d,
                raw_cap_faces,
                ring_ends,
                grid_mm=float(prepared.grid_mm),
            ),
            ring_ends,
            expected_area_mm2=expected_area,
            grid_mm=float(prepared.grid_mm),
            coordinate_alias_count=int(polygon.coordinate_alias_count),
        )
        cap_faces = validated_cap.faces
        if len(cap_faces) != expected_cap_face_count:
            raise ValueError("Vector canonical cap triangle count is inconsistent")

        bottom_start = vertex_cursor
        top_start = vertex_cursor + local_vertex_count
        vertices[bottom_start:top_start, :2] = vertices_2d
        vertices[bottom_start:top_start, 2] = z_offset
        vertices[top_start : top_start + local_vertex_count, :2] = vertices_2d
        vertices[top_start : top_start + local_vertex_count, 2] = z_offset + height

        cap_count = len(cap_faces)
        faces[face_cursor : face_cursor + cap_count] = (
            cap_faces[:, ::-1] + bottom_start
        )
        face_cursor += cap_count
        faces[face_cursor : face_cursor + cap_count] = cap_faces + top_start
        face_cursor += cap_count

        boundary_edges = validated_cap.boundary_edges
        if len(boundary_edges) != local_vertex_count:
            raise ValueError("Vector canonical cap boundary edge count is inconsistent")
        side_count = len(boundary_edges) * 2
        faces[face_cursor : face_cursor + side_count : 2] = np.column_stack(
            (
                bottom_start + boundary_edges[:, 0],
                bottom_start + boundary_edges[:, 1],
                top_start + boundary_edges[:, 1],
            )
        )
        faces[face_cursor + 1 : face_cursor + side_count : 2] = np.column_stack(
            (
                bottom_start + boundary_edges[:, 0],
                top_start + boundary_edges[:, 1],
                top_start + boundary_edges[:, 0],
            )
        )
        face_cursor += side_count
        vertex_cursor += local_vertex_count * 2

    if vertex_cursor != vertex_count or face_cursor != face_count:
        raise ValueError("Vector canonical mesh allocation count mismatch")

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    mesh.metadata["vector_layer_geometry"] = {
        "output_component_count": int(len(prepared.polygons)),
        "output_hole_count": int(prepared.hole_count),
        "output_area_mm2": float(prepared.area_mm2),
        "output_coordinate_count": int(prepared.coordinate_count),
        "grid_mm": float(prepared.grid_mm),
        "mesh_vertex_count": int(vertex_count),
        "mesh_face_count": int(face_count),
        "mesh_array_bytes": int(vertices.nbytes + faces.nbytes),
    }
    return mesh


def _remove_redundant_ring_units(units: np.ndarray) -> np.ndarray:
    """Remove exact collinear interior nodes without changing a ring boundary."""

    output = np.asarray(units, dtype=np.int64)
    while len(output) > 3:
        previous = np.roll(output, 1, axis=0)
        following = np.roll(output, -1, axis=0)
        incoming = output - previous
        outgoing = following - output
        cross = incoming[:, 0] * outgoing[:, 1]
        cross -= incoming[:, 1] * outgoing[:, 0]
        between = np.sum(
            (output - previous) * (output - following),
            axis=1,
            dtype=np.int64,
        ) <= 0
        removable = (cross == 0) & between
        if not np.any(removable) or int(np.count_nonzero(~removable)) < 3:
            break
        output = output[~removable]
    return output


def _indexed_ring_units(coordinates, *, grid_mm: float) -> np.ndarray:
    """Convert one ring to a compact exact physical-grid representation."""

    values = np.asarray(coordinates, dtype=np.float64)
    if len(values) > 1 and np.array_equal(values[0], values[-1]):
        values = values[:-1]
    units = np.rint(values / float(grid_mm)).astype(np.int64)
    if len(units) > 1:
        keep = np.ones(len(units), dtype=bool)
        keep[1:] = np.any(units[1:] != units[:-1], axis=1)
        units = units[keep]
    if len(units) > 1 and np.array_equal(units[0], units[-1]):
        units = units[:-1]
    units = _remove_redundant_ring_units(units)
    if len(units) < 3:
        raise ValueError("Vector layered-volume ring collapsed below three points")
    return np.ascontiguousarray(units)


def _indexed_polygon(
    polygon: Polygon,
    *,
    grid_mm: float,
) -> tuple[_IndexedPolygon, list[np.ndarray]]:
    """Convert one arrangement cell without discarding shared line nodes."""

    oriented = orient(polygon, sign=1.0)
    prepared = _IndexedPolygon(
        exterior_units=_indexed_ring_units(
            oriented.exterior.coords,
            grid_mm=grid_mm,
        ),
        hole_units=tuple(
            _indexed_ring_units(ring.coords, grid_mm=grid_mm)
            for ring in oriented.interiors
        ),
    )
    prepared = _node_indexed_polygon_ring_contacts(prepared)
    canonical_rings = _oriented_polygon_rings(prepared)
    canonical = _IndexedPolygon(
        exterior_units=canonical_rings[0],
        hole_units=tuple(canonical_rings[1:]),
        coordinate_alias_count=int(prepared.coordinate_alias_count),
    )
    return canonical, canonical_rings


def _physical_layer_slabs(
    slabs: Sequence[dict],
    *,
    scale_mm_per_svg_unit: float,
    policy: VectorLayerGeometryPolicy,
) -> tuple[list[_PhysicalLayerSlab], float]:
    """Validate, scale, and snap all stepped slabs on one writer-safe grid."""

    scale = float(scale_mm_per_svg_unit)
    if not math.isfinite(scale) or scale <= 0.0:
        raise ValueError("Vector layered-volume scale must be positive finite")

    maximum_abs_coordinate = 0.0
    raw_slabs: list[_PhysicalLayerSlab] = []
    for slab in slabs:
        if not isinstance(slab, dict):
            raise ValueError("Vector layered-volume slabs must be mappings")
        geometry = slab.get("geometry")
        try:
            z_start = float(slab.get("z_offset", 0.0))
            height = float(slab.get("height", 0.0))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("Vector layered-volume slab has invalid height") from exc
        if geometry is None or getattr(geometry, "is_empty", True) or height <= 1e-9:
            continue
        z_end = z_start + height
        if not all(math.isfinite(value) for value in (z_start, z_end)):
            raise ValueError("Vector layered-volume Z range must be finite")
        source_parts = _polygon_parts(geometry)
        polygonal_source: BaseGeometry = (
            source_parts[0]
            if len(source_parts) == 1
            else GeometryCollection(source_parts)
        )
        physical_geometry = affinity.scale(
            polygonal_source,
            xfact=scale,
            yfact=scale,
            origin=(0.0, 0.0),
        )
        for physical in _polygon_parts(physical_geometry):
            maximum_abs_coordinate = max(
                maximum_abs_coordinate,
                *(abs(float(value)) for value in physical.bounds),
            )
        raw_slabs.append(
            _PhysicalLayerSlab(
                geometry=physical_geometry,
                z_start_mm=round(z_start, 9),
                z_end_mm=round(z_end, 9),
            )
        )
    if not raw_slabs:
        return [], float(policy.grid_mm)

    grid_mm = resolve_vector_writer_grid_mm(
        maximum_abs_coordinate,
        minimum_mm=float(policy.grid_mm),
    )
    snapped_slabs: list[_PhysicalLayerSlab] = []
    for slab in raw_slabs:
        polygon_parts: list[Polygon] = []
        for source_part in _polygon_parts(slab.geometry):
            snapped_part = set_precision(
                source_part,
                grid_size=grid_mm,
                mode="valid_output",
            )
            if snapped_part is None or snapped_part.is_empty:
                continue
            polygon_parts.extend(_polygon_parts(snapped_part))
        if not polygon_parts:
            continue
        snapped_slabs.append(
            _PhysicalLayerSlab(
                geometry=(
                    polygon_parts[0]
                    if len(polygon_parts) == 1
                    else GeometryCollection(polygon_parts)
                ),
                z_start_mm=slab.z_start_mm,
                z_end_mm=slab.z_end_mm,
            )
        )
    return snapped_slabs, grid_mm


def _coalesced_layer_slabs(
    slabs: Sequence[_PhysicalLayerSlab],
) -> list[_PhysicalLayerSlab]:
    """Coalesce only byte-identical footprints with contiguous Z ranges.

    SVG draw-order clipping has already removed area overlaps before material
    recipes are assigned.  Meshing therefore keeps different footprints as
    independent closed shells instead of repeating a material-wide Boolean
    union for every atomic Z band.  Exact duplicates are cheap to recognize
    and safe to fold vertically, which avoids coincident internal caps without
    changing any XY boundary.
    """

    grouped: dict[bytes, tuple[BaseGeometry, list[tuple[float, float]]]] = {}
    for slab in slabs:
        geometry_key = shapely.to_wkb(
            shapely.normalize(slab.geometry),
            output_dimension=2,
            byte_order=1,
        )
        if geometry_key not in grouped:
            grouped[geometry_key] = (slab.geometry, [])
        grouped[geometry_key][1].append(
            (float(slab.z_start_mm), float(slab.z_end_mm))
        )

    result: list[_PhysicalLayerSlab] = []
    for geometry, intervals in grouped.values():
        current_start = None
        current_end = None
        for z_start, z_end in sorted(intervals):
            if current_start is None:
                current_start = float(z_start)
                current_end = float(z_end)
                continue
            assert current_end is not None
            if float(z_start) <= current_end + 1e-9:
                current_end = max(current_end, float(z_end))
                continue
            result.append(
                _PhysicalLayerSlab(
                    geometry=geometry,
                    z_start_mm=current_start,
                    z_end_mm=current_end,
                )
            )
            current_start = float(z_start)
            current_end = float(z_end)
        if current_start is not None and current_end is not None:
            result.append(
                _PhysicalLayerSlab(
                    geometry=geometry,
                    z_start_mm=current_start,
                    z_end_mm=current_end,
                )
            )
    return result


def _prepared_interval_group(
    footprints: Sequence[Polygon],
    *,
    grid_mm: float,
) -> _IndexedRunGroup:
    """Prepare every shell of one fixed-Z footprint for indexed extrusion."""

    prepared_polygons: list[_IndexedPolygon] = []
    coordinate_count = 0
    hole_count = 0
    area_mm2 = 0.0

    for raw_polygon in footprints:
        for simple_polygon in _polygon_parts(raw_polygon):
            prepared, rings = _indexed_polygon(
                simple_polygon,
                grid_mm=float(grid_mm),
            )
            prepared_polygons.append(prepared)
            coordinate_count += sum(len(ring) for ring in rings)
            hole_count += len(prepared.hole_units)
            area_mm2 += float(simple_polygon.area)

    if not prepared_polygons:
        raise ValueError("Vector interval footprint contains no printable shell")
    return _IndexedRunGroup(
        polygons=tuple(prepared_polygons),
        grid_mm=float(grid_mm),
        area_mm2=float(area_mm2),
        coordinate_count=int(coordinate_count),
        hole_count=int(hole_count),
    )


def _integer_layer_slabs(slabs: Sequence[dict], grid_mm: float) -> list[_PhysicalLayerSlab]:
    if {float(slab[PRINT_GRID_KEY]) for slab in slabs} != {grid_mm}:
        raise ValueError("Material slabs do not share the declared print grid")
    prepared = []
    for slab in slabs:
        geometry = slab["geometry"]
        if geometry.is_empty:
            continue
        coordinates = shapely.get_coordinates(geometry)
        if not geometry.is_valid or not np.array_equal(coordinates, np.rint(coordinates)):
            raise ValueError("Prepared print slab must contain valid integer topology")
        z_start = float(slab.get("z_offset", 0.0))
        z_end = z_start + float(slab.get("height", 0.0))
        if not math.isfinite(z_start) or not math.isfinite(z_end) or z_end <= z_start:
            raise ValueError("Prepared print slab has an invalid layer interval")
        prepared.append(_PhysicalLayerSlab(geometry, z_start, z_end))
    return prepared


def build_vector_layered_volume(
    slabs: Sequence[dict],
    *,
    scale_mm_per_svg_unit: float,
    policy: VectorLayerGeometryPolicy | None = None,
) -> trimesh.Trimesh | None:
    """Build one material object from independently closed layer slabs.
    由相互独立闭合的片层构建一个材料对象。

    SVG draw-order clipping owns area-overlap resolution. This builder only
    snaps each prepared slab to a writer-safe grid, coalesces byte-identical
    contiguous slabs, and extrudes every remaining polygon with shared
    cap/wall indices. Shell coordinates are never welded or displaced during
    concatenation; disconnected islands remain internal shells of the same
    material object.

    SVG 绘制顺序裁剪负责消除有面积的重叠。本构建器只把已准备好的片层吸附
    到写出安全网格、纵向合并完全相同且连续的片层，再用顶面与侧壁共享索引
    的方式逐片封口。合并对象时既不焊接也不挪动壳体坐标；离散小岛仍属于同
    一个耗材对象内部的独立闭合壳体。
    """

    effective_policy = policy or VectorLayerGeometryPolicy()
    slabs = tuple(slabs)
    canonical_slabs = [slab for slab in slabs if PRINT_GRID_KEY in slab]
    source_slabs = [slab for slab in slabs if PRINT_GRID_KEY not in slab]
    snapped_slabs, grid_mm = _physical_layer_slabs(
        source_slabs,
        scale_mm_per_svg_unit=scale_mm_per_svg_unit,
        policy=effective_policy,
    )
    if not snapped_slabs and not canonical_slabs:
        return None
    if canonical_slabs and snapped_slabs and grid_mm != effective_policy.grid_mm:
        raise ValueError("Mixed slab domains require the same declared print grid")
    coalesced_slabs = _coalesced_layer_slabs(snapped_slabs)
    with AdaptiveMeshAccumulator() as accumulator:
        if canonical_slabs:
            grid_mm = float(effective_policy.grid_mm)
            integer_slabs = _integer_layer_slabs(canonical_slabs, grid_mm)
            for slab in _coalesced_layer_slabs(integer_slabs):
                prepared = _prepared_interval_group(_polygon_parts(slab.geometry), grid_mm=1.0)
                prepared = replace(prepared, grid_mm=grid_mm, area_mm2=prepared.area_mm2 * grid_mm**2)
                accumulator.add(_extrude_indexed_run_group(
                    prepared, height_mm=slab.z_end_mm-slab.z_start_mm,
                    z_offset_mm=slab.z_start_mm,
                ))
        for slab in coalesced_slabs:
            prepared = _prepared_interval_group(
                _polygon_parts(slab.geometry),
                grid_mm=float(grid_mm),
            )
            accumulator.add(_extrude_indexed_run_group(
                prepared,
                height_mm=float(slab.z_end_mm) - float(slab.z_start_mm),
                z_offset_mm=float(slab.z_start_mm),
            ))
        if not accumulator.component_count:
            return None
        snapped_slabs.clear()
        coalesced_slabs.clear()
        mesh = accumulator.finish()
        component_count = accumulator.component_count
    mesh.metadata["vector_layer_geometry"] = {
        "grid_mm": float(grid_mm),
        "component_count": int(component_count),
        "mesh_vertex_count": int(len(mesh.vertices)),
        "mesh_face_count": int(len(mesh.faces)),
    }
    return mesh


__all__ = [
    "resolve_vector_writer_grid_mm",
    "snap_vector_writer_coordinate_mm",
    "VectorLayerGeometryPolicy",
    "build_vector_layered_volume",
]
