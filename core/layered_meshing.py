"""Exact indexed surfaces for labeled Z/Y/X voxel volumes.

This module deliberately keeps topology on an integer lattice until the final
Trimesh materialization.  It emits only exposed material faces, while retaining
separate index domains for volumes that merely touch at an edge or a point.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from functools import lru_cache

import numpy as np
import trimesh
from scipy import ndimage, sparse

try:
    from numba import njit

    _NUMBA_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised through import isolation
    _NUMBA_AVAILABLE = False

    def njit(*args, **_kwargs):
        """Return a no-op decorator when Numba is not installed."""

        if args and callable(args[0]):
            return args[0]
        return lambda function: function

from core.mesh_export_parts import MeshExportPartRange, set_mesh_export_part_ranges
from core.layered_z import map_doubled_layer_z, validate_layer_z_edges


_CUBOID_FACE_TEMPLATE = np.asarray(
    [
        [0, 2, 1],
        [0, 3, 2],
        [4, 5, 6],
        [4, 6, 7],
        [0, 1, 5],
        [0, 5, 4],
        [1, 2, 6],
        [1, 6, 5],
        [2, 3, 7],
        [2, 7, 6],
        [3, 0, 4],
        [3, 4, 7],
    ],
    dtype=np.uint32,
)
_COMPONENT_SIGNATURE_MAX_WORKING_BYTES = 8 * 1024 * 1024
_COMPONENT_COUNT_BLOCK_VOXELS = 1_048_576


@dataclass(frozen=True)
class LayeredMeshPolicy:
    """Validation policy for labeled surface construction.
    标签表面构建的验证策略。
    """

    validate_output: bool = False


@dataclass(frozen=True)
class LayeredMeshStats:
    """Observable size counters for one material mesh.
    单个材料网格的可观测规模统计。
    """

    source_voxel_count: int
    component_count: int
    exposed_unit_face_count: int
    merged_patch_count: int
    component_chunk_count: int
    peak_component_patch_count: int
    vertex_count: int
    face_count: int
    lattice_float32_bytes: int
    materialized_bytes: int
    source_contact_edge_pair_count: int
    source_contact_point_pair_count: int
    source_contact_normalized_edge_count: int


@dataclass(frozen=True)
class _CompactPatches:
    shell_ids: np.ndarray
    normals: np.ndarray
    corners: np.ndarray

    def __len__(self) -> int:
        return int(len(self.shell_ids))


def _pack_grid_key(
    fields: tuple[np.ndarray, ...],
    *,
    coordinate_base: int,
) -> np.ndarray:
    """Pack small non-negative grid fields into one sortable uint64 key."""

    if coordinate_base <= 0:
        raise ValueError("Layered mesh coordinate base must be positive")
    maximum_key = 3 * (coordinate_base ** (len(fields) - 1))
    if maximum_key > np.iinfo(np.uint64).max:
        raise ValueError("Layered mesh grid is too large for compact topology keys")
    packed = np.asarray(fields[0], dtype=np.uint64)
    base = np.uint64(coordinate_base)
    for field in fields[1:]:
        values = np.asarray(field)
        if bool(np.any(values < 0)) or bool(np.any(values >= coordinate_base)):
            raise ValueError("Layered mesh compact topology key is out of range")
        packed = packed * base + values.astype(np.uint64, copy=False)
    return packed


def _rank_packed_keys(
    keys: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Sort compact keys with explicit, bounded intermediate arrays."""

    order = np.argsort(keys, kind="quicksort")
    sorted_keys = keys[order]
    change = np.empty(len(keys), dtype=bool)
    change[0] = True
    change[1:] = sorted_keys[1:] != sorted_keys[:-1]
    sorted_rank = np.cumsum(change, dtype=np.uint32) - np.uint32(1)
    inverse = np.empty(len(keys), dtype=np.uint32)
    inverse[order] = sorted_rank
    group_counts = np.bincount(sorted_rank).astype(np.int32, copy=False)
    unique_keys = sorted_keys[change]
    return unique_keys, inverse, group_counts, order


def _component_membership(
    component_labels: np.ndarray,
    shell_id: int,
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
) -> np.ndarray:
    """Sample one component without allocating a full per-component volume."""

    inside = (
        (x >= 0)
        & (x < component_labels.shape[2])
        & (y >= 0)
        & (y < component_labels.shape[1])
        & (z >= 0)
        & (z < component_labels.shape[0])
    )
    occupied = np.zeros(len(x), dtype=bool)
    if bool(np.any(inside)):
        occupied[inside] = (
            component_labels[z[inside], y[inside], x[inside]] == shell_id
        )
    return occupied


def _diagonal_edge_contact_mask(
    starts: np.ndarray,
    ends: np.ndarray,
    *,
    component_labels: np.ndarray,
    shell_id: int,
) -> np.ndarray:
    """Locate voxel-diagonal boundary edges within one six-connected shell."""

    low = np.minimum(starts, ends)
    axis = np.argmax(starts != ends, axis=1)
    result = np.zeros(len(starts), dtype=bool)
    for current_axis in range(3):
        selected = np.flatnonzero(axis == current_axis)
        if len(selected) == 0:
            continue
        x = low[selected, 0]
        y = low[selected, 1]
        z = low[selected, 2]
        if current_axis == 0:
            samples = (
                (x, y - 1, z - 1),
                (x, y, z - 1),
                (x, y - 1, z),
                (x, y, z),
            )
        elif current_axis == 1:
            samples = (
                (x - 1, y, z - 1),
                (x, y, z - 1),
                (x - 1, y, z),
                (x, y, z),
            )
        else:
            samples = (
                (x - 1, y - 1, z),
                (x, y - 1, z),
                (x - 1, y, z),
                (x, y, z),
            )
        first, second, third, fourth = (
            _component_membership(
                component_labels,
                shell_id,
                sample_x,
                sample_y,
                sample_z,
            )
            for sample_x, sample_y, sample_z in samples
        )
        result[selected] = (
            (first & fourth & ~second & ~third)
            | (second & third & ~first & ~fourth)
        )
    return result


def _packed_segment_keys(
    token_coordinates: np.ndarray,
    segment_start: np.ndarray,
    segment_end: np.ndarray,
    *,
    coordinate_base: int,
) -> np.ndarray:
    """Pack boundary segments without full advanced-index coordinate copies."""

    keys = np.empty(len(segment_start), dtype=np.uint64)
    for block_start in range(0, len(keys), 65_536):
        block_end = min(block_start + 65_536, len(keys))
        first = token_coordinates[segment_start[block_start:block_end]]
        second = token_coordinates[segment_end[block_start:block_end]]
        axis = np.argmax(first != second, axis=1).astype(np.int32)
        low = np.minimum(first, second)
        high = np.maximum(first, second)
        rows = np.arange(len(first))
        fixed_first = np.where(axis == 0, low[:, 1], low[:, 0])
        fixed_second = np.where(axis == 2, low[:, 1], low[:, 2])
        keys[block_start:block_end] = _pack_grid_key(
            (
                axis,
                fixed_first,
                fixed_second,
                low[rows, axis],
                high[rows, axis],
            ),
            coordinate_base=coordinate_base,
        )
    return keys


class _LatticeFloat32Audit:
    """Audit the pre-transform lattice float32 materialization.

    This is not the final 3MF writer-domain audit.  The writer must separately
    validate coordinates after S07 scale and object translation are applied.
    """

    _MAX_EXACT_DOUBLED_COORDINATE = 1 << 24

    def __init__(self) -> None:
        self._unsafe_float32_coordinates: dict[
            tuple[int, int, int], tuple[int, int, int]
        ] = {}
        self.source_contact_normalized_edge_count = 0

    def observe(
        self,
        exact_world_doubled: np.ndarray,
        float32_vertices: np.ndarray,
    ) -> None:
        unsafe = np.any(
            np.abs(exact_world_doubled)
            >= self._MAX_EXACT_DOUBLED_COORDINATE,
            axis=1,
        )
        if not bool(np.any(unsafe)):
            return

        float32_bits = np.ascontiguousarray(float32_vertices).view(np.uint32)
        for index in np.flatnonzero(unsafe):
            float32_key = tuple(int(value) for value in float32_bits[index])
            exact_key = tuple(int(value) for value in exact_world_doubled[index])
            previous = self._unsafe_float32_coordinates.get(float32_key)
            if previous is not None and previous != exact_key:
                raise ValueError(
                    "Distinct exact lattice vertices collide in the float32 "
                    "lattice float32 collision audit"
                )
            self._unsafe_float32_coordinates[float32_key] = exact_key

    def merge(self, other: "_LatticeFloat32Audit") -> None:
        """Merge an accepted component audit into the mesh-wide audit."""

        for float32_key, exact_key in other._unsafe_float32_coordinates.items():
            previous = self._unsafe_float32_coordinates.get(float32_key)
            if previous is not None and previous != exact_key:
                raise ValueError(
                    "Distinct exact lattice vertices collide in the float32 "
                    "lattice float32 collision audit"
                )
            self._unsafe_float32_coordinates[float32_key] = exact_key
        self.source_contact_normalized_edge_count += (
            other.source_contact_normalized_edge_count
        )

    def exact_coordinates(self, vertices: np.ndarray) -> np.ndarray:
        """Recover audited compact coordinates before mapping a physical Z schedule."""
        exact = np.rint(vertices.astype(np.float64) * 2).astype(np.int64)
        if self._unsafe_float32_coordinates:
            bits = np.ascontiguousarray(vertices).view(np.uint32)
            unsafe = np.any(np.abs(exact) >= self._MAX_EXACT_DOUBLED_COORDINATE, axis=1)
            for index in np.flatnonzero(unsafe):
                key = tuple(int(value) for value in bits[index])
                exact[index] = self._unsafe_float32_coordinates.get(key, tuple(exact[index]))
        return exact


class _DiagonalContactNormalizationRequired(ValueError):
    """Signal that a compact first pass left an open edge or T-junction."""


def _greedy_rectangles_python(
    mask: np.ndarray,
) -> list[tuple[int, int, int, int]]:
    """Cover a boolean plane with non-overlapping axis-aligned rectangles."""

    rows, _columns = mask.shape
    used = np.zeros_like(mask, dtype=bool)
    rectangles: list[tuple[int, int, int, int]] = []
    for row in range(rows):
        available = mask[row] & ~used[row]
        if not bool(np.any(available)):
            continue
        padded = np.pad(available, (1, 1), constant_values=False)
        transitions = np.diff(padded.astype(np.int8))
        starts = np.flatnonzero(transitions == 1)
        ends = np.flatnonzero(transitions == -1)
        for column, column_end in zip(starts, ends):
            if used[row, column]:
                continue
            row_end = row + 1
            while row_end < rows:
                candidate = mask[row_end, column:column_end]
                already_used = used[row_end, column:column_end]
                if not bool(np.all(candidate)) or bool(np.any(already_used)):
                    break
                row_end += 1
            used[row:row_end, column:column_end] = True
            rectangles.append(
                (int(column), row, int(column_end), row_end)
            )
    return rectangles


@njit(cache=True, fastmath=False, nogil=True)
def _greedy_rectangles_numba(mask: np.ndarray) -> np.ndarray:
    """Run the exact greedy partition without per-cell Python dispatch."""

    rows, columns = mask.shape
    true_count = 0
    for row in range(rows):
        for column in range(columns):
            if mask[row, column]:
                true_count += 1

    rectangles = np.empty((true_count, 4), dtype=np.int32)
    used = np.zeros(mask.shape, dtype=np.uint8)
    rectangle_count = 0

    for row in range(rows):
        column = 0
        while column < columns:
            if not mask[row, column] or used[row, column] != 0:
                column += 1
                continue

            column_end = column + 1
            while (
                column_end < columns
                and mask[row, column_end]
                and used[row, column_end] == 0
            ):
                column_end += 1

            row_end = row + 1
            while row_end < rows:
                complete = True
                for candidate_column in range(column, column_end):
                    if (
                        not mask[row_end, candidate_column]
                        or used[row_end, candidate_column] != 0
                    ):
                        complete = False
                        break
                if not complete:
                    break
                row_end += 1

            for mark_row in range(row, row_end):
                for mark_column in range(column, column_end):
                    used[mark_row, mark_column] = 1

            rectangles[rectangle_count, 0] = column
            rectangles[rectangle_count, 1] = row
            rectangles[rectangle_count, 2] = column_end
            rectangles[rectangle_count, 3] = row_end
            rectangle_count += 1
            column = column_end

    return rectangles[:rectangle_count]


def merge_boolean_rectangles(mask: np.ndarray) -> np.ndarray:
    """Merge a 2D boolean mask into exact non-overlapping rectangles.
    将二维布尔掩码精确合并为互不重叠的矩形。
    """

    candidate = np.ascontiguousarray(mask, dtype=bool)
    if candidate.ndim != 2:
        raise ValueError("rectangle merging expects a 2D boolean mask")
    if not bool(np.any(candidate)):
        return np.empty((0, 4), dtype=np.int32)
    if _NUMBA_AVAILABLE:
        return _greedy_rectangles_numba(candidate)
    rectangles = _greedy_rectangles_python(candidate)
    return np.asarray(rectangles, dtype=np.int32).reshape((-1, 4))


def group_identical_material_layers(
    voxel_matrix: np.ndarray,
    material_id: int,
) -> list[tuple[int, int, np.ndarray]]:
    """Group consecutive equal material masks without changing XY coverage.
    合并连续且相同的材料掩码层，不改变 XY 覆盖。
    """

    volume = np.asarray(voxel_matrix)
    if volume.ndim != 3:
        raise ValueError("material layer grouping expects a 3D voxel matrix")
    groups: list[tuple[int, int, np.ndarray]] = []
    previous_mask: np.ndarray | None = None
    start_z = 0
    for z_index in range(volume.shape[0]):
        current_mask = volume[z_index] == int(material_id)
        if not bool(np.any(current_mask)):
            if previous_mask is not None:
                groups.append((start_z, z_index - 1, previous_mask))
                previous_mask = None
            continue
        if previous_mask is None:
            start_z = z_index
            previous_mask = current_mask
        elif not np.array_equal(current_mask, previous_mask):
            groups.append((start_z, z_index - 1, previous_mask))
            start_z = z_index
            previous_mask = current_mask
    if previous_mask is not None:
        groups.append((start_z, volume.shape[0] - 1, previous_mask))
    return groups


def _append_plane_patch_arrays(
    shell_chunks: list[np.ndarray],
    normal_chunks: list[np.ndarray],
    corner_chunks: list[np.ndarray],
    *,
    shell_id: int,
    direction: str,
    plane: int,
    mask: np.ndarray,
    origin: tuple[int, int, int],
) -> None:
    """Append one plane as compact arrays, bounding Python objects per plane."""

    normal_by_direction = {
        "-x": (-1, 0, 0),
        "+x": (1, 0, 0),
        "-y": (0, -1, 0),
        "+y": (0, 1, 0),
        "-z": (0, 0, -1),
        "+z": (0, 0, 1),
    }
    rectangle_array = merge_boolean_rectangles(mask)
    if len(rectangle_array) == 0:
        return
    u0, v0, u1, v1 = rectangle_array.T
    count = len(rectangle_array)
    corners = np.empty((count, 4, 3), dtype=np.int32)

    if direction in {"-x", "+x"}:
        corners[:, :, 0] = plane
        corners[:, :, 1] = np.column_stack((u0, u1, u1, u0))
        corners[:, :, 2] = np.column_stack((v0, v0, v1, v1))
        reverse = direction == "-x"
    elif direction in {"-y", "+y"}:
        corners[:, :, 0] = np.column_stack((u0, u1, u1, u0))
        corners[:, :, 1] = plane
        corners[:, :, 2] = np.column_stack((v0, v0, v1, v1))
        reverse = direction == "+y"
    elif direction in {"-z", "+z"}:
        corners[:, :, 0] = np.column_stack((u0, u1, u1, u0))
        corners[:, :, 1] = np.column_stack((v0, v0, v1, v1))
        corners[:, :, 2] = plane
        reverse = direction == "-z"
    else:
        raise ValueError(f"Unsupported face direction: {direction}")

    if reverse:
        corners = np.ascontiguousarray(corners[:, ::-1])
    corners += np.asarray(origin, dtype=np.int32)
    shell_chunks.append(np.full(count, shell_id, dtype=np.int32))
    normal_chunks.append(
        np.tile(np.asarray(normal_by_direction[direction], dtype=np.int8), (count, 1))
    )
    corner_chunks.append(corners)


def _component_patches(
    component: np.ndarray,
    *,
    shell_id: int,
    origin: tuple[int, int, int] = (0, 0, 0),
) -> tuple[_CompactPatches, int]:
    """Extract and merge the six exposed face families of one component."""

    shell_chunks: list[np.ndarray] = []
    normal_chunks: list[np.ndarray] = []
    corner_chunks: list[np.ndarray] = []
    exposed_count = 0

    negative_x = np.empty_like(component)
    negative_x[:, :, 0] = component[:, :, 0]
    negative_x[:, :, 1:] = component[:, :, 1:] & ~component[:, :, :-1]
    negative_x_counts = np.count_nonzero(negative_x, axis=(0, 1))
    exposed_count += int(negative_x_counts.sum())
    for x_value in np.flatnonzero(negative_x_counts):
        x = int(x_value)
        _append_plane_patch_arrays(
            shell_chunks,
            normal_chunks,
            corner_chunks,
            shell_id=shell_id,
            direction="-x",
            plane=x,
            mask=negative_x[:, :, x],
            origin=origin,
        )
    del negative_x

    positive_x = np.empty_like(component)
    positive_x[:, :, -1] = component[:, :, -1]
    positive_x[:, :, :-1] = component[:, :, :-1] & ~component[:, :, 1:]
    positive_x_counts = np.count_nonzero(positive_x, axis=(0, 1))
    exposed_count += int(positive_x_counts.sum())
    for x_value in np.flatnonzero(positive_x_counts):
        x = int(x_value)
        _append_plane_patch_arrays(
            shell_chunks,
            normal_chunks,
            corner_chunks,
            shell_id=shell_id,
            direction="+x",
            plane=x + 1,
            mask=positive_x[:, :, x],
            origin=origin,
        )
    del positive_x

    negative_y = np.empty_like(component)
    negative_y[:, 0, :] = component[:, 0, :]
    negative_y[:, 1:, :] = component[:, 1:, :] & ~component[:, :-1, :]
    negative_y_counts = np.count_nonzero(negative_y, axis=(0, 2))
    exposed_count += int(negative_y_counts.sum())
    for y_value in np.flatnonzero(negative_y_counts):
        y = int(y_value)
        _append_plane_patch_arrays(
            shell_chunks,
            normal_chunks,
            corner_chunks,
            shell_id=shell_id,
            direction="-y",
            plane=y,
            mask=negative_y[:, y, :],
            origin=origin,
        )
    del negative_y

    positive_y = np.empty_like(component)
    positive_y[:, -1, :] = component[:, -1, :]
    positive_y[:, :-1, :] = component[:, :-1, :] & ~component[:, 1:, :]
    positive_y_counts = np.count_nonzero(positive_y, axis=(0, 2))
    exposed_count += int(positive_y_counts.sum())
    for y_value in np.flatnonzero(positive_y_counts):
        y = int(y_value)
        _append_plane_patch_arrays(
            shell_chunks,
            normal_chunks,
            corner_chunks,
            shell_id=shell_id,
            direction="+y",
            plane=y + 1,
            mask=positive_y[:, y, :],
            origin=origin,
        )
    del positive_y

    negative_z = np.empty_like(component)
    negative_z[0, :, :] = component[0, :, :]
    negative_z[1:, :, :] = component[1:, :, :] & ~component[:-1, :, :]
    negative_z_counts = np.count_nonzero(negative_z, axis=(1, 2))
    exposed_count += int(negative_z_counts.sum())
    for z_value in np.flatnonzero(negative_z_counts):
        z = int(z_value)
        _append_plane_patch_arrays(
            shell_chunks,
            normal_chunks,
            corner_chunks,
            shell_id=shell_id,
            direction="-z",
            plane=z,
            mask=negative_z[z, :, :],
            origin=origin,
        )
    del negative_z

    positive_z = np.empty_like(component)
    positive_z[-1, :, :] = component[-1, :, :]
    positive_z[:-1, :, :] = component[:-1, :, :] & ~component[1:, :, :]
    positive_z_counts = np.count_nonzero(positive_z, axis=(1, 2))
    exposed_count += int(positive_z_counts.sum())
    for z_value in np.flatnonzero(positive_z_counts):
        z = int(z_value)
        _append_plane_patch_arrays(
            shell_chunks,
            normal_chunks,
            corner_chunks,
            shell_id=shell_id,
            direction="+z",
            plane=z + 1,
            mask=positive_z[z, :, :],
            origin=origin,
        )
    if not shell_chunks:
        raise ValueError("Layered surface component produced no exposed patches")
    return (
        _CompactPatches(
            shell_ids=np.concatenate(shell_chunks),
            normals=np.concatenate(normal_chunks, axis=0),
            corners=np.concatenate(corner_chunks, axis=0),
        ),
        exposed_count,
    )


@njit(cache=True, fastmath=False, nogil=True)
def _split_patch_edges_numba(
    edge_first: np.ndarray,
    edge_second: np.ndarray,
    edge_axis: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split edges at every collinear endpoint on the exact integer lattice."""

    edge_count = len(edge_first)
    coordinate_minimum = edge_first[0].copy()
    coordinate_maximum = edge_first[0].copy()
    for edge_index in range(edge_count):
        zero_length = True
        for dimension in range(3):
            first_value = edge_first[edge_index, dimension]
            second_value = edge_second[edge_index, dimension]
            if first_value != second_value:
                zero_length = False
            if first_value < coordinate_minimum[dimension]:
                coordinate_minimum[dimension] = first_value
            if second_value < coordinate_minimum[dimension]:
                coordinate_minimum[dimension] = second_value
            if first_value > coordinate_maximum[dimension]:
                coordinate_maximum[dimension] = first_value
            if second_value > coordinate_maximum[dimension]:
                coordinate_maximum[dimension] = second_value
        if zero_length:
            raise ValueError("Layered mesh patch contains a zero-length edge")

    x_size = int(coordinate_maximum[0] - coordinate_minimum[0] + 1)
    y_size = int(coordinate_maximum[1] - coordinate_minimum[1] + 1)
    z_size = int(coordinate_maximum[2] - coordinate_minimum[2] + 1)
    events = np.zeros((z_size, y_size, x_size), dtype=np.uint8)
    base_counts_by_edge = np.empty(edge_count, dtype=np.int32)

    for axis in range(3):
        events.fill(0)
        for edge_index in range(edge_count):
            if edge_axis[edge_index] != axis:
                continue
            events[
                edge_first[edge_index, 2] - coordinate_minimum[2],
                edge_first[edge_index, 1] - coordinate_minimum[1],
                edge_first[edge_index, 0] - coordinate_minimum[0],
            ] = 1
            events[
                edge_second[edge_index, 2] - coordinate_minimum[2],
                edge_second[edge_index, 1] - coordinate_minimum[1],
                edge_second[edge_index, 0] - coordinate_minimum[0],
            ] = 1

        for edge_index in range(edge_count):
            if edge_axis[edge_index] != axis:
                continue
            start_value = edge_first[edge_index, axis]
            end_value = edge_second[edge_index, axis]
            step = 1 if end_value > start_value else -1
            value = start_value + step
            segment_count = 0
            while True:
                x = edge_first[edge_index, 0]
                y = edge_first[edge_index, 1]
                z = edge_first[edge_index, 2]
                if axis == 0:
                    x = value
                elif axis == 1:
                    y = value
                else:
                    z = value
                if events[
                    z - coordinate_minimum[2],
                    y - coordinate_minimum[1],
                    x - coordinate_minimum[0],
                ] != 0:
                    segment_count += 1
                if value == end_value:
                    break
                value += step
            if segment_count <= 0:
                raise ValueError("Layered mesh patch contains a zero-length edge")
            base_counts_by_edge[edge_index] = segment_count

    base_offsets_by_edge = np.empty(len(edge_first) + 1, dtype=np.int64)
    base_offsets_by_edge[0] = 0
    for edge_index in range(edge_count):
        base_offsets_by_edge[edge_index + 1] = (
            base_offsets_by_edge[edge_index]
            + base_counts_by_edge[edge_index]
        )
    base_start = np.empty((int(base_offsets_by_edge[-1]), 3), dtype=np.int32)
    base_end = np.empty_like(base_start)

    for axis in range(3):
        events.fill(0)
        for edge_index in range(edge_count):
            if edge_axis[edge_index] != axis:
                continue
            events[
                edge_first[edge_index, 2] - coordinate_minimum[2],
                edge_first[edge_index, 1] - coordinate_minimum[1],
                edge_first[edge_index, 0] - coordinate_minimum[0],
            ] = 1
            events[
                edge_second[edge_index, 2] - coordinate_minimum[2],
                edge_second[edge_index, 1] - coordinate_minimum[1],
                edge_second[edge_index, 0] - coordinate_minimum[0],
            ] = 1

        for edge_index in range(edge_count):
            if edge_axis[edge_index] != axis:
                continue
            previous_value = edge_first[edge_index, axis]
            end_value = edge_second[edge_index, axis]
            step = 1 if end_value > previous_value else -1
            value = previous_value + step
            output_index = base_offsets_by_edge[edge_index]
            while True:
                x = edge_first[edge_index, 0]
                y = edge_first[edge_index, 1]
                z = edge_first[edge_index, 2]
                if axis == 0:
                    x = value
                elif axis == 1:
                    y = value
                else:
                    z = value
                if events[
                    z - coordinate_minimum[2],
                    y - coordinate_minimum[1],
                    x - coordinate_minimum[0],
                ] != 0:
                    base_start[output_index] = edge_first[edge_index]
                    base_end[output_index] = edge_first[edge_index]
                    base_start[output_index, axis] = previous_value
                    base_end[output_index, axis] = value
                    output_index += 1
                    previous_value = value
                if value == end_value:
                    break
                value += step
            if output_index != base_offsets_by_edge[edge_index + 1]:
                raise ValueError("Layered mesh patch split count changed")

    return base_start, base_end, base_counts_by_edge


def _split_patch_edges(
    edge_first: np.ndarray,
    edge_second: np.ndarray,
    edge_axis: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Split patch edges with one exact native-compiled lattice kernel."""

    first = np.ascontiguousarray(edge_first, dtype=np.int32)
    second = np.ascontiguousarray(edge_second, dtype=np.int32)
    axis = np.ascontiguousarray(edge_axis, dtype=np.int32)
    if (
        first.ndim != 2
        or first.shape[1:] != (3,)
        or second.shape != first.shape
        or axis.shape != (len(first),)
        or len(first) == 0
    ):
        raise ValueError("Layered mesh patch edges have invalid shape")
    if bool(np.any(np.all(first == second, axis=1))):
        raise ValueError("Layered mesh patch contains a zero-length edge")
    return _split_patch_edges_numba(first, second, axis)


def _make_rectangle_ring_triangle_offsets(
    edge_lengths: tuple[int, int, int, int],
) -> np.ndarray:
    """Create local triangle indices for one split rectangle ring.

    A diagonal between opposite rectangle corners creates two right-triangle
    halves. Each half is filled as a zipper between its two subdivided legs.
    This preserves every boundary segment, adds no center vertex, and emits the
    minimum ``ring_length - 2`` non-degenerate triangles in linear time.
    """

    counts = tuple(int(value) for value in edge_lengths)
    if any(value <= 0 for value in counts):
        raise ValueError("Layered mesh rectangle ring has invalid edge lengths")
    ring_length = sum(counts)
    triangles: list[tuple[int, int, int]] = []

    def ring_token(offset: int) -> int:
        return offset % ring_length

    def write_half(
        *,
        apex_offset: int,
        backward_count: int,
        forward_count: int,
    ) -> None:
        apex = ring_token(apex_offset)
        backward_first = ring_token(apex_offset - 1)
        forward_first = ring_token(apex_offset + 1)
        triangles.append((apex, backward_first, forward_first))

        for step in range(2, backward_count + 1):
            triangles.append(
                (
                    ring_token(apex_offset - step + 1),
                    ring_token(apex_offset - step),
                    forward_first,
                )
            )

        backward_end = ring_token(apex_offset - backward_count)
        for step in range(2, forward_count + 1):
            triangles.append(
                (
                    backward_end,
                    ring_token(apex_offset + step),
                    ring_token(apex_offset + step - 1),
                )
            )

    first, second, third, fourth = counts
    write_half(
        apex_offset=first,
        backward_count=first,
        forward_count=second,
    )
    write_half(
        apex_offset=first + second + third,
        backward_count=third,
        forward_count=fourth,
    )
    result = np.asarray(triangles, dtype=np.uint32)
    if len(result) != ring_length - 2:
        raise ValueError("Layered mesh rectangle triangle count mismatch")
    result.setflags(write=False)
    return result


@lru_cache(maxsize=64)
def _cached_rectangle_ring_triangle_offsets(
    edge_lengths: tuple[int, int, int, int],
) -> np.ndarray:
    return _make_rectangle_ring_triangle_offsets(edge_lengths)


def _rectangle_ring_triangle_offsets(
    edge_lengths: np.ndarray,
) -> np.ndarray:
    """Return bounded-cache local triangles for one split rectangle.
    返回带有有界缓存的分割矩形局部三角面。
    """

    counts = tuple(int(value) for value in edge_lengths)
    if len(counts) != 4:
        raise ValueError("Layered mesh rectangle ring must have four edges")
    if sum(counts) <= 64:
        return _cached_rectangle_ring_triangle_offsets(counts)
    return _make_rectangle_ring_triangle_offsets(counts)


def _segment_pairs_have_material(
    first_segments: np.ndarray,
    second_segments: np.ndarray,
    *,
    segment_start: np.ndarray,
    segment_end: np.ndarray,
    segment_normal: np.ndarray,
    token_coordinates: np.ndarray,
    component_labels: np.ndarray,
    shell_id: int,
) -> np.ndarray:
    """Classify candidate pairings along four-incidence boundary segments."""

    first_normals = segment_normal[first_segments].astype(np.int64)
    second_normals = segment_normal[second_segments].astype(np.int64)
    orthogonal = np.einsum("ij,ij->i", first_normals, second_normals) == 0
    first_tokens = segment_start[first_segments]
    second_tokens = segment_end[first_segments]
    low = np.minimum(
        token_coordinates[first_tokens],
        token_coordinates[second_tokens],
    )
    high = np.maximum(
        token_coordinates[first_tokens],
        token_coordinates[second_tokens],
    )
    sample = np.floor_divide(
        low + (high - first_normals) - second_normals,
        4,
    )
    x, y, z = sample.T
    inside = (
        (x >= 0)
        & (x < component_labels.shape[2])
        & (y >= 0)
        & (y < component_labels.shape[1])
        & (z >= 0)
        & (z < component_labels.shape[0])
    )
    occupied = np.zeros(len(first_segments), dtype=bool)
    if bool(np.any(inside)):
        occupied[inside] = (
            component_labels[z[inside], y[inside], x[inside]] == shell_id
        )
    return orthogonal & occupied


def _segment_pair_token_relations(
    first_segments: np.ndarray,
    second_segments: np.ndarray,
    *,
    segment_start: np.ndarray,
    segment_end: np.ndarray,
    token_coordinates: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return exact endpoint-equivalence relations for segment pairs."""

    first_start = segment_start[first_segments]
    first_end = segment_end[first_segments]
    second_start = segment_start[second_segments]
    second_end = segment_end[second_segments]
    same_direction = np.all(
        token_coordinates[first_start] == token_coordinates[second_start],
        axis=1,
    )
    reverse_direction = np.all(
        token_coordinates[first_start] == token_coordinates[second_end],
        axis=1,
    )
    if not bool(np.all(same_direction ^ reverse_direction)):
        raise ValueError("Layered mesh boundary segments do not match")
    related_start = np.where(same_direction, second_start, second_end)
    related_end = np.where(same_direction, second_end, second_start)
    return (
        np.concatenate((first_start, first_end)).astype(np.int64, copy=False),
        np.concatenate((related_start, related_end)).astype(np.int64, copy=False),
    )


def _token_components_from_segment_pairs(
    *,
    token_count: int,
    token_coordinates: np.ndarray,
    segment_start: np.ndarray,
    segment_end: np.ndarray,
    segment_normal: np.ndarray,
    segment_order: np.ndarray,
    segment_group_starts: np.ndarray,
    segment_group_counts: np.ndarray,
    component_labels: np.ndarray,
    shell_id: int,
) -> np.ndarray:
    """Resolve shared token identities with vectorized sparse connectivity."""

    paired_first: list[np.ndarray] = []
    paired_second: list[np.ndarray] = []
    four_surface_segments: np.ndarray | None = None

    two_groups = np.flatnonzero(segment_group_counts == 2)
    if len(two_groups) > 0:
        two_starts = segment_group_starts[two_groups]
        paired_first.append(segment_order[two_starts])
        paired_second.append(segment_order[two_starts + 1])

    four_groups = np.flatnonzero(segment_group_counts == 4)
    if len(four_groups) > 0:
        four_starts = segment_group_starts[four_groups]
        instances = segment_order[four_starts[:, None] + np.arange(4)]
        pair_01 = _segment_pairs_have_material(
            instances[:, 0],
            instances[:, 1],
            segment_start=segment_start,
            segment_end=segment_end,
            segment_normal=segment_normal,
            token_coordinates=token_coordinates,
            component_labels=component_labels,
            shell_id=shell_id,
        )
        pair_02 = _segment_pairs_have_material(
            instances[:, 0],
            instances[:, 2],
            segment_start=segment_start,
            segment_end=segment_end,
            segment_normal=segment_normal,
            token_coordinates=token_coordinates,
            component_labels=component_labels,
            shell_id=shell_id,
        )
        pair_03 = _segment_pairs_have_material(
            instances[:, 0],
            instances[:, 3],
            segment_start=segment_start,
            segment_end=segment_end,
            segment_normal=segment_normal,
            token_coordinates=token_coordinates,
            component_labels=component_labels,
            shell_id=shell_id,
        )
        pair_12 = _segment_pairs_have_material(
            instances[:, 1],
            instances[:, 2],
            segment_start=segment_start,
            segment_end=segment_end,
            segment_normal=segment_normal,
            token_coordinates=token_coordinates,
            component_labels=component_labels,
            shell_id=shell_id,
        )
        pair_13 = _segment_pairs_have_material(
            instances[:, 1],
            instances[:, 3],
            segment_start=segment_start,
            segment_end=segment_end,
            segment_normal=segment_normal,
            token_coordinates=token_coordinates,
            component_labels=component_labels,
            shell_id=shell_id,
        )
        pair_23 = _segment_pairs_have_material(
            instances[:, 2],
            instances[:, 3],
            segment_start=segment_start,
            segment_end=segment_end,
            segment_normal=segment_normal,
            token_coordinates=token_coordinates,
            component_labels=component_labels,
            shell_id=shell_id,
        )
        matching = np.column_stack(
            (
                pair_01 & pair_23,
                pair_02 & pair_13,
                pair_03 & pair_12,
            )
        )
        if not bool(np.all(np.count_nonzero(matching, axis=1) == 1)):
            raise ValueError("Layered mesh could not separate a diagonal edge contact")
        matching_index = np.argmax(matching, axis=1)
        first_lookup = np.asarray([[0, 2], [0, 1], [0, 1]], dtype=np.int64)
        second_lookup = np.asarray([[1, 3], [2, 3], [3, 2]], dtype=np.int64)
        rows = np.arange(len(instances))[:, None]
        selected_first = instances[rows, first_lookup[matching_index]]
        selected_second = instances[rows, second_lookup[matching_index]]
        four_surface_segments = selected_first
        paired_first.append(selected_first.reshape(-1))
        paired_second.append(selected_second.reshape(-1))

    if not paired_first:
        raise ValueError("Layered mesh boundary has no paired segments")
    first_segments = np.concatenate(paired_first)
    second_segments = np.concatenate(paired_second)
    relation_first, relation_second = _segment_pair_token_relations(
        first_segments,
        second_segments,
        segment_start=segment_start,
        segment_end=segment_end,
        token_coordinates=token_coordinates,
    )
    graph = sparse.csr_matrix(
        (
            np.ones(len(relation_first), dtype=np.uint8),
            (relation_first, relation_second),
        ),
        shape=(token_count, token_count),
    )
    _component_count, token_to_vertex = sparse.csgraph.connected_components(
        graph,
        directed=False,
        return_labels=True,
    )
    if four_surface_segments is not None:
        surface_start = token_to_vertex[segment_start[four_surface_segments]]
        surface_end = token_to_vertex[segment_end[four_surface_segments]]
        surface_low = np.minimum(surface_start, surface_end)
        surface_high = np.maximum(surface_start, surface_end)
        collapsed = (
            (surface_low[:, 0] == surface_low[:, 1])
            & (surface_high[:, 0] == surface_high[:, 1])
        )
        if bool(np.any(collapsed)):
            raise _DiagonalContactNormalizationRequired(
                "Layered surface contact needs one local edge subdivision"
            )
    return token_to_vertex.astype(np.uint32, copy=False)


def _mesh_arrays_from_patches(
    patches: _CompactPatches,
    *,
    height_px: int,
    component_labels: np.ndarray,
    shell_id: int,
    lattice_audit: _LatticeFloat32Audit | None = None,
    normalize_diagonal_contacts: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    patch_count = len(patches)
    if patch_count == 0:
        raise ValueError("Layered surface meshing received no patches")

    edge_first = patches.corners.reshape((-1, 3))
    edge_second = np.roll(patches.corners, -1, axis=1).reshape((-1, 3))
    edge_delta = edge_second - edge_first
    edge_axis = np.argmax(edge_delta != 0, axis=1).astype(np.int32)
    if not bool(np.all(patches.shell_ids == patches.shell_ids[0])):
        raise ValueError("Compact meshing accepts one six-connected component")
    base_start, base_end, base_counts_by_edge = _split_patch_edges(
        edge_first,
        edge_second,
        edge_axis,
    )

    patch_base_counts = base_counts_by_edge.reshape((patch_count, 4)).sum(axis=1)
    patch_base_offsets = np.empty(patch_count + 1, dtype=np.int64)
    patch_base_offsets[0] = 0
    np.cumsum(patch_base_counts, out=patch_base_offsets[1:])
    if normalize_diagonal_contacts:
        base_nonmanifold = _diagonal_edge_contact_mask(
            base_start,
            base_end,
            component_labels=component_labels,
            shell_id=shell_id,
        )
    else:
        base_nonmanifold = np.zeros(len(base_start), dtype=bool)
    if lattice_audit is not None:
        lattice_audit.source_contact_normalized_edge_count += int(
            np.count_nonzero(base_nonmanifold) // 4
        )
    del (
        edge_delta,
        edge_axis,
    )

    edge_base_offsets = np.empty(len(base_counts_by_edge) + 1, dtype=np.int64)
    edge_base_offsets[0] = 0
    np.cumsum(base_counts_by_edge, out=edge_base_offsets[1:])
    extra_by_edge = np.add.reduceat(
        base_nonmanifold.astype(np.int32),
        edge_base_offsets[:-1],
    )
    ring_counts_by_edge = base_counts_by_edge + extra_by_edge
    ring_lengths = ring_counts_by_edge.reshape((patch_count, 4)).sum(axis=1)
    boundary_token_count = int(ring_lengths.sum())
    token_count = boundary_token_count
    face_count = int((ring_lengths - 2).sum())
    if token_count > np.iinfo(np.uint32).max:
        raise ValueError("Layered surface component exceeds uint32 lattice indices")

    # Coordinates are doubled exact integers. Most raster grids fit int32;
    # retain int64 for the larger domain, including the final Y-axis flip.
    coordinate_dtype = (
        np.int32
        if 2 * max(int(patches.corners.max()), int(height_px)) <= np.iinfo(np.int32).max
        else np.int64
    )
    token_coordinates = np.empty((token_count, 3), dtype=coordinate_dtype)
    faces_by_token = np.empty((face_count, 3), dtype=np.uint32)
    segment_start = np.empty(boundary_token_count, dtype=np.uint32)
    segment_end = np.empty(boundary_token_count, dtype=np.uint32)
    segment_normal = np.empty((boundary_token_count, 3), dtype=np.int8)
    patch_token_offsets = np.empty(patch_count + 1, dtype=np.int64)
    patch_token_offsets[0] = 0
    np.cumsum(ring_lengths, out=patch_token_offsets[1:])
    patch_face_offsets = np.empty(patch_count + 1, dtype=np.int64)
    patch_face_offsets[0] = 0
    np.cumsum(ring_lengths - 2, out=patch_face_offsets[1:])

    if not bool(np.any(base_nonmanifold)):
        np.multiply(base_start, 2, out=token_coordinates, dtype=coordinate_dtype)
        segment_start[:] = np.arange(boundary_token_count, dtype=np.uint32)
        segment_end[:] = segment_start + np.uint32(1)
        segment_end[patch_token_offsets[1:] - 1] = patch_token_offsets[
            :-1
        ].astype(np.uint32)
        segment_normal[:] = np.repeat(
            patches.normals,
            ring_lengths,
            axis=0,
        )

        four_patch_indices = np.flatnonzero(ring_lengths == 4)
        if len(four_patch_indices) > 0:
            ring_begins = patch_token_offsets[four_patch_indices].astype(np.uint32)
            face_begins = patch_face_offsets[four_patch_indices]
            faces_by_token[face_begins] = np.column_stack(
                (ring_begins, ring_begins + 2, ring_begins + 1)
            )
            faces_by_token[face_begins + 1] = np.column_stack(
                (ring_begins, ring_begins + 3, ring_begins + 2)
            )
        non_four_patch_indices = np.flatnonzero(ring_lengths != 4)
        for patch_index in non_four_patch_indices:
            ring_begin = int(patch_token_offsets[patch_index])
            face_begin = int(patch_face_offsets[patch_index])
            triangle_offsets = _rectangle_ring_triangle_offsets(
                ring_counts_by_edge[patch_index * 4 : (patch_index + 1) * 4]
            )
            np.add(
                triangle_offsets,
                np.uint32(ring_begin),
                out=faces_by_token[
                    face_begin : face_begin + len(triangle_offsets)
                ],
            )
    else:
        token_cursor = 0
        for patch_index in range(patch_count):
            base_begin = int(patch_base_offsets[patch_index])
            base_finish = int(patch_base_offsets[patch_index + 1])
            ring_length = int(ring_lengths[patch_index])
            ring_begin = token_cursor
            ring_position = 0
            for base_index in range(base_begin, base_finish):
                np.multiply(
                    base_start[base_index],
                    2,
                    out=token_coordinates[ring_begin + ring_position],
                    dtype=coordinate_dtype,
                )
                ring_position += 1
                if base_nonmanifold[base_index]:
                    np.add(
                        base_start[base_index],
                        base_end[base_index],
                        out=token_coordinates[ring_begin + ring_position],
                        dtype=coordinate_dtype,
                    )
                    ring_position += 1
            if ring_position != ring_length:
                raise ValueError("Layered mesh compact ring count mismatch")

            ring_indices = np.arange(
                ring_begin,
                ring_begin + ring_length,
                dtype=np.uint32,
            )
            segment_start[ring_begin : ring_begin + ring_length] = ring_indices
            segment_end[ring_begin : ring_begin + ring_length] = np.roll(
                ring_indices,
                -1,
            )
            segment_normal[ring_begin : ring_begin + ring_length] = (
                patches.normals[patch_index]
            )

            face_begin = int(patch_face_offsets[patch_index])
            if ring_length == 4:
                faces_by_token[face_begin] = (
                    ring_indices[0],
                    ring_indices[2],
                    ring_indices[1],
                )
                faces_by_token[face_begin + 1] = (
                    ring_indices[0],
                    ring_indices[3],
                    ring_indices[2],
                )
            else:
                triangle_offsets = _rectangle_ring_triangle_offsets(
                    ring_counts_by_edge[patch_index * 4 : (patch_index + 1) * 4]
                )
                np.add(
                    triangle_offsets,
                    np.uint32(ring_begin),
                    out=faces_by_token[
                        face_begin : face_begin + len(triangle_offsets)
                    ],
                )
            token_cursor += ring_length

        if token_cursor != token_count:
            raise ValueError("Layered mesh compact allocation count mismatch")
    del (
        edge_first,
        edge_second,
        base_counts_by_edge,
        base_start,
        base_end,
        patch_base_counts,
        patch_base_offsets,
        base_nonmanifold,
        edge_base_offsets,
        extra_by_edge,
        ring_counts_by_edge,
        ring_lengths,
        patch_token_offsets,
        patch_face_offsets,
    )

    doubled_coordinate_base = max(3, int(token_coordinates.max()) + 1)
    segment_keys = _packed_segment_keys(
        token_coordinates,
        segment_start,
        segment_end,
        coordinate_base=doubled_coordinate_base,
    )
    (
        _unique_segment_keys,
        segment_inverse,
        segment_group_counts,
        segment_order,
    ) = _rank_packed_keys(segment_keys)
    segment_group_starts = np.empty(len(segment_group_counts), dtype=np.int64)
    segment_group_starts[0] = 0
    if len(segment_group_counts) > 1:
        np.cumsum(
            segment_group_counts[:-1],
            out=segment_group_starts[1:],
        )
    if bool(np.any((segment_group_counts != 2) & (segment_group_counts != 4))):
        raise ValueError("Layered mesh boundary segment has unsupported incidence")
    del (
        segment_keys,
        _unique_segment_keys,
        segment_inverse,
    )

    token_to_vertex = _token_components_from_segment_pairs(
        token_count=token_count,
        token_coordinates=token_coordinates,
        segment_start=segment_start,
        segment_end=segment_end,
        segment_normal=segment_normal,
        segment_order=segment_order,
        segment_group_starts=segment_group_starts,
        segment_group_counts=segment_group_counts,
        component_labels=component_labels,
        shell_id=shell_id,
    )

    del (
        segment_start,
        segment_end,
        segment_normal,
        segment_order,
        segment_group_starts,
        segment_group_counts,
    )

    _vertex_labels, representative_tokens = np.unique(
        token_to_vertex,
        return_index=True,
    )
    exact_world_doubled = token_coordinates[representative_tokens]
    faces = token_to_vertex[faces_by_token].astype(np.uint32, copy=False)
    del (
        _vertex_labels,
        representative_tokens,
        token_coordinates,
        token_to_vertex,
        faces_by_token,
    )

    exact_world_doubled[:, 1] = int(height_px) * 2 - exact_world_doubled[:, 1]
    vertices = exact_world_doubled.astype(np.float32) * np.float32(0.5)
    if lattice_audit is not None:
        lattice_audit.observe(exact_world_doubled, vertices)
    return vertices, faces


def _cuboid_component_arrays(
    origins: np.ndarray,
    ends: np.ndarray,
    *,
    height_px: int,
    lattice_audit: _LatticeFloat32Audit,
) -> tuple[np.ndarray, np.ndarray]:
    """Materialize many independent integer cuboids in one bounded batch."""

    component_count = len(origins)
    if component_count == 0 or origins.shape != ends.shape or origins.shape[1:] != (3,):
        raise ValueError("Layered mesh cuboid batch has invalid bounds")
    if bool(np.any(ends <= origins)):
        raise ValueError("Layered mesh cuboid batch has empty bounds")
    if component_count * 8 > np.iinfo(np.uint32).max:
        raise ValueError("Layered mesh cuboid batch exceeds uint32 lattice indices")

    x0, y0, z0 = origins.T.astype(np.int64, copy=False)
    x1, y1, z1 = ends.T.astype(np.int64, copy=False)
    world_y0 = np.int64(height_px) - y1
    world_y1 = np.int64(height_px) - y0
    exact_world_doubled = np.empty((component_count, 8, 3), dtype=np.int64)
    exact_world_doubled[:, [0, 3, 4, 7], 0] = (x0 * 2)[:, None]
    exact_world_doubled[:, [1, 2, 5, 6], 0] = (x1 * 2)[:, None]
    exact_world_doubled[:, [0, 1, 4, 5], 1] = (world_y0 * 2)[:, None]
    exact_world_doubled[:, [2, 3, 6, 7], 1] = (world_y1 * 2)[:, None]
    exact_world_doubled[:, :4, 2] = (z0 * 2)[:, None]
    exact_world_doubled[:, 4:, 2] = (z1 * 2)[:, None]

    vertices = exact_world_doubled.reshape((-1, 3)).astype(np.float32)
    vertices *= np.float32(0.5)
    lattice_audit.observe(exact_world_doubled.reshape((-1, 3)), vertices)
    offsets = (np.arange(component_count, dtype=np.uint32) * np.uint32(8)).reshape(
        (-1, 1, 1)
    )
    faces = (_CUBOID_FACE_TEMPLATE[None, :, :] + offsets).reshape((-1, 3))
    return vertices, faces


def _translated_component_template_arrays(
    template_vertices: np.ndarray,
    template_faces: np.ndarray,
    translations: np.ndarray,
    *,
    lattice_audit: _LatticeFloat32Audit,
) -> tuple[np.ndarray, np.ndarray]:
    """Replicate one exact small-component topology at integer translations."""

    instance_count = len(translations)
    vertices_per_instance = len(template_vertices)
    if instance_count == 0 or vertices_per_instance == 0 or len(template_faces) == 0:
        raise ValueError("Layered mesh component template batch is empty")
    total_vertices = instance_count * vertices_per_instance
    if total_vertices > np.iinfo(np.uint32).max:
        raise ValueError("Layered mesh component template exceeds uint32 indices")

    exact_template_doubled = np.rint(
        np.asarray(template_vertices, dtype=np.float64) * 2.0
    ).astype(np.int64)
    if not np.array_equal(
        exact_template_doubled.astype(np.float64) * 0.5,
        np.asarray(template_vertices, dtype=np.float64),
    ):
        raise ValueError("Layered mesh component template left the half-grid")

    vertices = np.empty((total_vertices, 3), dtype=np.float32)
    block_instances = max(1, 65_536 // vertices_per_instance)
    for block_start in range(0, instance_count, block_instances):
        block_end = min(block_start + block_instances, instance_count)
        exact_block = (
            exact_template_doubled[None, :, :]
            + translations[block_start:block_end, None, :].astype(np.int64) * 2
        ).reshape((-1, 3))
        float32_block = exact_block.astype(np.float32) * np.float32(0.5)
        lattice_audit.observe(exact_block, float32_block)
        output_start = block_start * vertices_per_instance
        output_end = block_end * vertices_per_instance
        vertices[output_start:output_end] = float32_block

    offsets = (
        np.arange(instance_count, dtype=np.uint32) * np.uint32(vertices_per_instance)
    ).reshape((-1, 1, 1))
    faces = (
        np.asarray(template_faces, dtype=np.uint32)[None, :, :] + offsets
    ).reshape((-1, 3))
    return vertices, faces


def _component_bound_arrays(
    component_bounds: list[tuple[slice, slice, slice] | None],
) -> tuple[np.ndarray, np.ndarray]:
    """Convert SciPy Z/Y/X component slices into compact X/Y/Z arrays."""

    origins = np.empty((len(component_bounds), 3), dtype=np.int32)
    ends = np.empty_like(origins)
    for index, bounds in enumerate(component_bounds):
        if bounds is None:
            raise ValueError("Layered mesh component labels are not contiguous")
        z_bounds, y_bounds, x_bounds = bounds
        origins[index] = (x_bounds.start, y_bounds.start, z_bounds.start)
        ends[index] = (x_bounds.stop, y_bounds.stop, z_bounds.stop)
    return origins, ends


def _indexed_face_edges_are_paired(faces: np.ndarray) -> bool:
    """Check indexed edge closure without scanning coordinates or volume.
    仅检查索引边闭合，不扫描坐标或体积。
    """

    if faces.ndim != 2 or faces.shape[1] != 3 or len(faces) == 0:
        return False
    edge_keys = np.empty(len(faces) * 3, dtype=np.uint64)
    output_offset = 0
    for first_column, second_column in ((0, 1), (1, 2), (2, 0)):
        for start in range(0, len(faces), 65_536):
            face_block = faces[start : start + 65_536]
            first = face_block[:, first_column]
            second = face_block[:, second_column]
            low = np.minimum(first, second).astype(np.uint64)
            high = np.maximum(first, second).astype(np.uint64)
            block_length = len(face_block)
            edge_keys[output_offset : output_offset + block_length] = (
                (low << np.uint64(32)) | high
            )
            output_offset += block_length
    edge_keys.sort(kind="quicksort")
    return bool(
        len(edge_keys) % 2 == 0
        and np.all(edge_keys[0::2] == edge_keys[1::2])
        and np.all(edge_keys[1:-1:2] != edge_keys[2::2])
    )


def _validate_component_arrays(
    vertices: np.ndarray,
    faces: np.ndarray,
    *,
    expected_volume: int,
) -> None:
    """Validate one bounded component before its compact arrays are retained."""

    if faces.ndim != 2 or faces.shape[1] != 3 or len(faces) == 0:
        raise ValueError("Layered surface meshing produced no triangles")
    if int(faces.min()) < 0 or int(faces.max()) >= len(vertices):
        raise ValueError("Layered surface meshing produced an invalid index")
    if np.any(
        (faces[:, 0] == faces[:, 1])
        | (faces[:, 1] == faces[:, 2])
        | (faces[:, 2] == faces[:, 0])
    ):
        raise ValueError("Layered surface meshing produced an index-degenerate triangle")

    signed_six_volume_terms: list[float] = []
    for start in range(0, len(faces), 65_536):
        face_block = faces[start : start + 65_536]
        triangles = vertices[face_block].astype(np.float64, copy=False)
        twice_area = np.linalg.norm(
            np.cross(
                triangles[:, 1] - triangles[:, 0],
                triangles[:, 2] - triangles[:, 0],
            ),
            axis=1,
        )
        if np.any(twice_area == 0.0):
            raise ValueError(
                "Layered surface meshing produced a coordinate-degenerate triangle"
            )
        signed_six_volume_terms.append(
            float(
                np.einsum(
                    "ij,ij->i",
                    triangles[:, 0],
                    np.cross(triangles[:, 1], triangles[:, 2]),
                ).sum()
            )
        )

    if not _indexed_face_edges_are_paired(faces):
        raise _DiagonalContactNormalizationRequired(
            "Layered surface meshing produced an open edge or T-junction"
        )
    signed_volume = math.fsum(signed_six_volume_terms) / 6.0
    volume_tolerance = max(
        1e-9,
        abs(float(expected_volume)) * np.finfo(np.float64).eps * 64.0,
    )
    if not np.isclose(
        signed_volume,
        float(expected_volume),
        rtol=0.0,
        atol=volume_tolerance,
    ):
        raise ValueError("Layered surface meshing changed occupied volume")


def _validated_component_arrays(
    patches: _CompactPatches,
    *,
    height_px: int,
    component_labels: np.ndarray,
    shell_id: int,
    expected_volume: int,
    validate_output: bool,
    lattice_audit: _LatticeFloat32Audit,
) -> tuple[np.ndarray, np.ndarray]:
    """Build one component directly; reserve full audits for development."""

    if not validate_output:
        try:
            return _mesh_arrays_from_patches(
                patches,
                height_px=height_px,
                component_labels=component_labels,
                shell_id=shell_id,
                lattice_audit=lattice_audit,
                normalize_diagonal_contacts=False,
            )
        except _DiagonalContactNormalizationRequired:
            return _mesh_arrays_from_patches(
                patches,
                height_px=height_px,
                component_labels=component_labels,
                shell_id=shell_id,
                lattice_audit=lattice_audit,
                normalize_diagonal_contacts=True,
            )

    first_audit = _LatticeFloat32Audit()
    try:
        vertices, faces = _mesh_arrays_from_patches(
            patches,
            height_px=height_px,
            component_labels=component_labels,
            shell_id=shell_id,
            lattice_audit=first_audit,
            normalize_diagonal_contacts=False,
        )
        _validate_component_arrays(
            vertices,
            faces,
            expected_volume=expected_volume,
        )
    except _DiagonalContactNormalizationRequired:
        del vertices, faces
        retry_audit = _LatticeFloat32Audit()
        vertices, faces = _mesh_arrays_from_patches(
            patches,
            height_px=height_px,
            component_labels=component_labels,
            shell_id=shell_id,
            lattice_audit=retry_audit,
            normalize_diagonal_contacts=True,
        )
        _validate_component_arrays(
            vertices,
            faces,
            expected_volume=expected_volume,
        )
        lattice_audit.merge(retry_audit)
        return vertices, faces

    lattice_audit.merge(first_audit)
    return vertices, faces


def _shifted_slices(
    shape: tuple[int, int, int],
    offset: tuple[int, int, int],
) -> tuple[tuple[slice, ...], tuple[slice, ...]]:
    source: list[slice] = []
    target: list[slice] = []
    for length, delta in zip(shape, offset):
        if delta >= 0:
            source.append(slice(0, length - delta))
            target.append(slice(delta, length))
        else:
            source.append(slice(-delta, length))
            target.append(slice(0, length + delta))
    return tuple(source), tuple(target)


def _count_source_contacts(
    selected: np.ndarray,
    component_labels: np.ndarray,
    layer_widths: np.ndarray | None = None,
) -> tuple[int, int]:
    """Count edge/point contacts between distinct six-connected components."""

    edge_pairs = 0
    point_pairs = 0
    for dz in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                offset = (dz, dy, dx)
                if offset <= (0, 0, 0):
                    continue
                nonzero_axes = int(dz != 0) + int(dy != 0) + int(dx != 0)
                if nonzero_axes not in {2, 3}:
                    continue
                if any(abs(delta) >= length for delta, length in zip(offset, selected.shape)):
                    continue
                source, target = _shifted_slices(selected.shape, offset)
                touching = selected[source] & selected[target]
                touching &= component_labels[source] != component_labels[target]
                if layer_widths is not None and dz == 0:
                    counts = np.count_nonzero(touching, axis=(1, 2))
                    pair_count = sum(int(count) * int(width) for count, width in zip(counts, layer_widths))
                else:
                    pair_count = int(np.count_nonzero(touching))
                if nonzero_axes == 2:
                    edge_pairs += pair_count
                else:
                    point_pairs += pair_count
    if layer_widths is not None:
        # Consecutive physical layers inside a repeated plane are absent from
        # the compact array. Their diagonal contacts still belong to the source.
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                nonzero_axes = 1 + int(dy != 0) + int(dx != 0)
                if nonzero_axes not in {2, 3}:
                    continue
                if abs(dy) >= selected.shape[1] or abs(dx) >= selected.shape[2]:
                    continue
                source, target = _shifted_slices(selected.shape, (0, dy, dx))
                touching = selected[source] & selected[target]
                touching &= component_labels[source] != component_labels[target]
                counts = np.count_nonzero(touching, axis=(1, 2))
                pairs = sum(int(count) * (int(width) - 1) for count, width in zip(counts, layer_widths))
                if nonzero_axes == 2:
                    edge_pairs += pairs
                else:
                    point_pairs += pairs
    return edge_pairs, point_pairs


def _weighted_exposed_face_count(selected: np.ndarray, widths: np.ndarray) -> int:
    """Count physical unit faces without expanding repeated planes."""
    xy_counts = (
        np.count_nonzero(selected[:, :, 0], axis=1)
        + np.count_nonzero(selected[:, :, -1], axis=1)
        + np.count_nonzero(selected[:, 0, :], axis=1)
        + np.count_nonzero(selected[:, -1, :], axis=1)
        + np.count_nonzero(selected[:, :, 1:] != selected[:, :, :-1], axis=(1, 2))
        + np.count_nonzero(selected[:, 1:, :] != selected[:, :-1, :], axis=(1, 2))
    )
    return (
        sum(int(count) * int(width) for count, width in zip(xy_counts, widths))
        + int(np.count_nonzero(selected[0]))
        + int(np.count_nonzero(selected[-1]))
        + int(np.count_nonzero(selected[1:] != selected[:-1]))
    )


def build_labeled_surface_mesh(
    labels: np.ndarray,
    *,
    material_id: int,
    height_px: int,
    policy: LayeredMeshPolicy | None = None,
    z_edges: np.ndarray | None = None,
) -> trimesh.Trimesh | None:
    """Build one exact closed material surface from a Z/Y/X label volume.
    从 Z/Y/X 标签体构建一个精确闭合的材料表面。

    Args:
        labels: Integer-like material labels in ``(Z, Y, X)`` order.
            按 ``(Z, Y, X)`` 排列的材料标签。
        material_id: Label to extract. 要提取的材料编号。
        height_px: Source image height used for the Y-axis flip.
            用于翻转 Y 轴的源图高度。
        policy: Optional validation policy. 可选的验证策略。
        z_edges: Optional Z+1 strictly increasing integer layer boundaries,
            starting at zero. Each label plane fills its complete interval;
            omitted boundaries give the original dense unit-layer behavior.

    Returns:
        A closed indexed mesh, or ``None`` when the material is absent.
        闭合索引网格；材料不存在时返回 ``None``。
    """

    volume = np.asarray(labels)
    if volume.ndim != 3:
        raise ValueError("labels must have shape (Z, Y, X)")
    physical_z_edges = (
        validate_layer_z_edges(z_edges, volume.shape[0]) if z_edges is not None else None
    )
    layer_widths = np.diff(physical_z_edges) if physical_z_edges is not None else None
    if int(height_px) != height_px or int(height_px) < volume.shape[1]:
        raise ValueError("height_px must be an integer covering the label rows")
    selected = volume == material_id
    voxel_count = int(np.count_nonzero(selected))
    if voxel_count == 0:
        return None
    logical_voxel_count = (
        sum(int(count) * int(width) for count, width in zip(
            np.count_nonzero(selected, axis=(1, 2)), layer_widths,
        )) if layer_widths is not None else voxel_count
    )
    logical_exposed_count = (
        _weighted_exposed_face_count(selected, layer_widths) if layer_widths is not None else None
    )
    component_labels, component_count = ndimage.label(
        selected,
        structure=ndimage.generate_binary_structure(3, 1),
    )
    source_edge_contacts, source_point_contacts = _count_source_contacts(
        selected,
        component_labels,
        layer_widths,
    )
    effective_policy = policy or LayeredMeshPolicy()
    lattice_audit = _LatticeFloat32Audit()
    vertex_chunks: list[np.ndarray] = []
    face_chunks: list[np.ndarray] = []
    exposed_count = 0
    merged_patch_count = 0
    peak_component_patch_count = 0
    component_voxel_total = 0
    processed_component_count = 0
    component_chunk_count = 0
    vertex_offset = 0
    face_offset = 0
    export_part_ranges: list[MeshExportPartRange] = []
    component_bounds = ndimage.find_objects(component_labels)
    component_origins, component_ends = _component_bound_arrays(component_bounds)
    component_sizes = np.zeros(int(component_count) + 1, dtype=np.int64)
    flat_component_labels = component_labels.reshape(-1)
    # bincount promotes its input to native intp. Bound that hidden copy rather
    # than duplicating the complete int32 component volume for every material.
    for start in range(0, flat_component_labels.size, _COMPONENT_COUNT_BLOCK_VOXELS):
        label_block = flat_component_labels[start : start + _COMPONENT_COUNT_BLOCK_VOXELS]
        if len(component_sizes) <= _COMPONENT_COUNT_BLOCK_VOXELS:
            component_sizes += np.bincount(label_block, minlength=len(component_sizes))
        else:
            # A sparse component field can have more shells than block voxels.
            # Avoid re-allocating a global-sized histogram for every block.
            block_labels, block_counts = np.unique(label_block, return_counts=True)
            component_sizes[block_labels] += block_counts
            del block_labels, block_counts
    del label_block
    component_sizes = component_sizes[1:]
    del flat_component_labels
    component_dimensions = component_ends.astype(np.int64) - component_origins
    component_bbox_volumes = np.prod(component_dimensions, axis=1)
    cuboid_components = component_sizes == component_bbox_volumes

    cuboid_indices = np.flatnonzero(cuboid_components)
    if len(cuboid_indices) > 0:
        cuboid_origins = component_origins[cuboid_indices]
        cuboid_ends = component_ends[cuboid_indices]
        cuboid_vertices, cuboid_faces = _cuboid_component_arrays(
            cuboid_origins,
            cuboid_ends,
            height_px=int(height_px),
            lattice_audit=lattice_audit,
        )
        if vertex_offset + len(cuboid_vertices) > np.iinfo(np.uint32).max:
            raise ValueError("Layered surface mesh exceeds uint32 lattice indices")
        vertex_chunks.append(cuboid_vertices)
        face_chunks.append(cuboid_faces + np.uint32(vertex_offset))
        cuboid_count = len(cuboid_indices)
        if (
            len(cuboid_vertices) != cuboid_count * 8
            or len(cuboid_faces) != cuboid_count * len(_CUBOID_FACE_TEMPLATE)
        ):
            raise ValueError("Layered cuboid component ranges are inconsistent")
        for component_index in range(cuboid_count):
            export_part_ranges.append(
                MeshExportPartRange(
                    vertex_start=vertex_offset + component_index * 8,
                    vertex_stop=vertex_offset + (component_index + 1) * 8,
                    face_start=(
                        face_offset
                        + component_index * len(_CUBOID_FACE_TEMPLATE)
                    ),
                    face_stop=(
                        face_offset
                        + (component_index + 1) * len(_CUBOID_FACE_TEMPLATE)
                    ),
                )
            )
        vertex_offset += len(cuboid_vertices)
        face_offset += len(cuboid_faces)

        cuboid_dimensions = component_dimensions[cuboid_indices]
        x_size, y_size, z_size = cuboid_dimensions.T
        exposed_count += int(
            np.sum(
                2
                * (
                    x_size * y_size
                    + x_size * z_size
                    + y_size * z_size
                )
            )
        )
        cuboid_voxel_count = int(component_sizes[cuboid_indices].sum())
        merged_patch_count += cuboid_count * 6
        peak_component_patch_count = max(peak_component_patch_count, 6)
        component_voxel_total += cuboid_voxel_count
        processed_component_count += cuboid_count
        component_chunk_count += 1
        del (
            cuboid_origins,
            cuboid_ends,
            cuboid_vertices,
            cuboid_faces,
            cuboid_dimensions,
        )

    non_cuboid_indices = np.flatnonzero(~cuboid_components)
    signature_candidate_indices = non_cuboid_indices[
        component_bbox_volumes[non_cuboid_indices]
        <= _COMPONENT_SIGNATURE_MAX_WORKING_BYTES
    ]
    exact_groups: dict[tuple[tuple[int, ...], bytes], list[int]] = {}
    for component_index in signature_candidate_indices:
        bounds = component_bounds[component_index]
        if bounds is None:
            raise ValueError("Layered mesh component labels are not contiguous")
        local_component = component_labels[bounds] == int(component_index) + 1
        signature_key = (
            tuple(int(value) for value in local_component.shape),
            np.packbits(local_component.reshape(-1)).tobytes(),
        )
        exact_groups.setdefault(signature_key, []).append(int(component_index))

    template_groups: list[list[int]] = []
    individual_component_indices = list(
        int(index)
        for index in non_cuboid_indices[
            component_bbox_volumes[non_cuboid_indices]
            > _COMPONENT_SIGNATURE_MAX_WORKING_BYTES
        ]
    )
    for collision_group in exact_groups.values():
        if len(collision_group) > 1:
            template_groups.append(collision_group)
        else:
            individual_component_indices.extend(collision_group)

    for component_indices in template_groups:
        first_component_index = component_indices[0]
        first_shell_id = first_component_index + 1
        first_bounds = component_bounds[first_component_index]
        if first_bounds is None:
            raise ValueError("Layered mesh component labels are not contiguous")
        local_component = component_labels[first_bounds] == first_shell_id
        local_component_labels = local_component.astype(np.int32)
        template_patches, template_exposed_count = _component_patches(
            local_component,
            shell_id=1,
        )
        template_patch_count = len(template_patches)
        template_audit = _LatticeFloat32Audit()
        component_voxel_count = int(component_sizes[first_component_index])
        template_vertices, template_faces = _validated_component_arrays(
            template_patches,
            height_px=local_component.shape[1],
            component_labels=local_component_labels,
            shell_id=1,
            expected_volume=component_voxel_count,
            validate_output=effective_policy.validate_output,
            lattice_audit=template_audit,
        )

        group_indices = np.asarray(component_indices, dtype=np.int64)
        group_origins = component_origins[group_indices].astype(np.int64)
        group_ends = component_ends[group_indices].astype(np.int64)
        translations = np.column_stack(
            (
                group_origins[:, 0],
                np.int64(height_px) - group_ends[:, 1],
                group_origins[:, 2],
            )
        )
        group_vertices, group_faces = _translated_component_template_arrays(
            template_vertices,
            template_faces,
            translations,
            lattice_audit=lattice_audit,
        )
        group_count = len(component_indices)
        lattice_audit.source_contact_normalized_edge_count += (
            template_audit.source_contact_normalized_edge_count * group_count
        )
        if vertex_offset + len(group_vertices) > np.iinfo(np.uint32).max:
            raise ValueError("Layered surface mesh exceeds uint32 lattice indices")
        vertex_chunks.append(group_vertices)
        face_chunks.append(group_faces + np.uint32(vertex_offset))
        vertices_per_component = len(template_vertices)
        faces_per_component = len(template_faces)
        if (
            len(group_vertices) != group_count * vertices_per_component
            or len(group_faces) != group_count * faces_per_component
        ):
            raise ValueError("Layered template component ranges are inconsistent")
        for group_index in range(group_count):
            export_part_ranges.append(
                MeshExportPartRange(
                    vertex_start=(
                        vertex_offset + group_index * vertices_per_component
                    ),
                    vertex_stop=(
                        vertex_offset + (group_index + 1) * vertices_per_component
                    ),
                    face_start=face_offset + group_index * faces_per_component,
                    face_stop=face_offset + (group_index + 1) * faces_per_component,
                )
            )
        vertex_offset += len(group_vertices)
        face_offset += len(group_faces)
        exposed_count += template_exposed_count * group_count
        merged_patch_count += template_patch_count * group_count
        peak_component_patch_count = max(
            peak_component_patch_count,
            template_patch_count,
        )
        component_voxel_total += component_voxel_count * group_count
        processed_component_count += group_count
        component_chunk_count += 1
        del (
            local_component,
            local_component_labels,
            template_patches,
            template_vertices,
            template_faces,
            template_audit,
            group_indices,
            group_origins,
            group_ends,
            translations,
            group_vertices,
            group_faces,
        )

    for component_index in individual_component_indices:
        shell_id = int(component_index) + 1
        bounds = component_bounds[component_index]
        if bounds is None:
            raise ValueError("Layered mesh component labels are not contiguous")
        local_labels = component_labels[bounds]
        local_component = local_labels == shell_id
        component_voxel_count = int(component_sizes[component_index])
        z_origin = int(bounds[0].start or 0)
        y_origin = int(bounds[1].start or 0)
        x_origin = int(bounds[2].start or 0)
        compact_patches, component_exposed = _component_patches(
            local_component,
            shell_id=shell_id,
            origin=(x_origin, y_origin, z_origin),
        )
        component_patch_count = len(compact_patches)
        component_vertices, component_faces = _validated_component_arrays(
            compact_patches,
            height_px=int(height_px),
            component_labels=component_labels,
            shell_id=shell_id,
            expected_volume=component_voxel_count,
            validate_output=effective_policy.validate_output,
            lattice_audit=lattice_audit,
        )
        del compact_patches

        if vertex_offset + len(component_vertices) > np.iinfo(np.uint32).max:
            raise ValueError("Layered surface mesh exceeds uint32 lattice indices")
        vertex_chunks.append(component_vertices)
        face_chunks.append(component_faces + np.uint32(vertex_offset))
        export_part_ranges.append(
            MeshExportPartRange(
                vertex_start=vertex_offset,
                vertex_stop=vertex_offset + len(component_vertices),
                face_start=face_offset,
                face_stop=face_offset + len(component_faces),
            )
        )
        vertex_offset += len(component_vertices)
        face_offset += len(component_faces)
        exposed_count += component_exposed
        merged_patch_count += component_patch_count
        peak_component_patch_count = max(
            peak_component_patch_count,
            component_patch_count,
        )
        component_voxel_total += component_voxel_count
        processed_component_count += 1
        component_chunk_count += 1
        del component_vertices, component_faces, local_component

    if (
        processed_component_count != int(component_count)
        or component_voxel_total != voxel_count
    ):
        raise ValueError("Layered surface component assembly is incomplete")
    del (
        component_labels,
        component_bounds,
        component_origins,
        component_ends,
        component_sizes,
        component_dimensions,
        component_bbox_volumes,
        cuboid_components,
        cuboid_indices,
        non_cuboid_indices,
        signature_candidate_indices,
        exact_groups,
        template_groups,
        individual_component_indices,
        selected,
    )

    if len(vertex_chunks) == 1:
        lattice_vertices = vertex_chunks[0]
        lattice_faces = face_chunks[0]
    else:
        lattice_vertices = np.concatenate(vertex_chunks, axis=0)
        lattice_faces = np.concatenate(face_chunks, axis=0)
    vertex_chunks.clear()
    face_chunks.clear()

    if physical_z_edges is not None:
        # Component templates and all connectivity operations stay in the same
        # compact index domain. Map only after their global positions are known.
        exact_coordinates = lattice_audit.exact_coordinates(lattice_vertices)
        exact_coordinates[:, 2] = map_doubled_layer_z(exact_coordinates[:, 2], physical_z_edges)
        lattice_vertices = exact_coordinates.astype(np.float32) * np.float32(0.5)
        _LatticeFloat32Audit().observe(exact_coordinates, lattice_vertices)
        del exact_coordinates
        if effective_policy.validate_output:
            _validate_component_arrays(lattice_vertices, lattice_faces, expected_volume=logical_voxel_count)

    lattice_float32_bytes = int(lattice_vertices.nbytes + lattice_faces.nbytes)
    lattice_vertex_count = len(lattice_vertices)
    lattice_face_count = len(lattice_faces)
    mesh = trimesh.Trimesh(
        vertices=lattice_vertices,
        faces=lattice_faces,
        process=False,
    )
    del lattice_vertices, lattice_faces

    materialized_bytes = int(mesh.vertices.nbytes + mesh.faces.nbytes)

    stats = LayeredMeshStats(
        source_voxel_count=logical_voxel_count,
        component_count=int(component_count),
        exposed_unit_face_count=(logical_exposed_count if logical_exposed_count is not None else exposed_count),
        merged_patch_count=merged_patch_count,
        component_chunk_count=component_chunk_count,
        peak_component_patch_count=peak_component_patch_count,
        vertex_count=lattice_vertex_count,
        face_count=lattice_face_count,
        lattice_float32_bytes=lattice_float32_bytes,
        materialized_bytes=materialized_bytes,
        source_contact_edge_pair_count=source_edge_contacts,
        source_contact_point_pair_count=source_point_contacts,
        source_contact_normalized_edge_count=(
            lattice_audit.source_contact_normalized_edge_count
        ),
    )
    mesh.metadata["layered_mesh_stats"] = asdict(stats)
    mesh.metadata["integer_topology_scale"] = 2
    set_mesh_export_part_ranges(
        mesh,
        export_part_ranges,
        only_when_combined_unsafe=True,
    )

    return mesh


__all__ = [
    "LayeredMeshPolicy",
    "LayeredMeshStats",
    "build_labeled_surface_mesh",
    "group_identical_material_layers",
    "merge_boolean_rectangles",
]
