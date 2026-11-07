"""Puzzle layout generation utilities for converter puzzle mode.
拼图模式的布局生成与渲染工具。

This module owns all reusable puzzle business logic used by both the
preview-overlay flow and the final piece-export flow.
本模块负责拼图模式的核心业务逻辑，供预览叠线和正式导出共同复用。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import math
import random
from typing import Literal

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from shapely import box, contains_xy, union_all
from shapely.affinity import affine_transform
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

PuzzleStyle = Literal["regular", "irregular"]
PuzzleSizingMode = Literal["piece_size", "grid", "piece_count"]
PuzzleConnectorStyle = Literal["classic", "easy_cut"]

_Point = tuple[float, float]
_BBox = tuple[int, int, int, int]


@dataclass(frozen=True)
class _BezierConnectorPreset:
    """Fixed cubic-Bezier connector preset for a shared puzzle edge."""

    tab_size_ratio: float
    jitter_ratio: float
    head_multiplier: float
    samples_per_segment: int
    min_neck_multiplier: float
    min_head_multiplier: float


# Adapted from the CC0 geometry template in Draradech/jigsaw:jigsaw.html.
_BEZIER_CONNECTOR_PRESETS: dict[PuzzleConnectorStyle, _BezierConnectorPreset] = {
    "classic": _BezierConnectorPreset(
        tab_size_ratio=0.18,
        jitter_ratio=0.04,
        head_multiplier=3.0,
        samples_per_segment=12,
        min_neck_multiplier=1.5,
        min_head_multiplier=2.6,
    ),
    "easy_cut": _BezierConnectorPreset(
        tab_size_ratio=0.12,
        jitter_ratio=0.02,
        head_multiplier=2.2,
        samples_per_segment=12,
        min_neck_multiplier=1.35,
        min_head_multiplier=2.1,
    ),
}


@dataclass
class _PieceGeometryRecord:
    """Intermediate mutable piece geometry.
    中间阶段使用的可变拼图块几何记录。
    """

    geometry: Polygon
    centroid_px: _Point


@dataclass(frozen=True)
class PuzzleLayoutConfig:
    """Configuration for building a puzzle layout.
    构建拼图布局所需的配置。

    Attributes:
        width_px: Full layout width in preview pixel space. (布局在预览像素空间中的总宽度)
        height_px: Full layout height in preview pixel space. (布局在预览像素空间中的总高度)
        total_width_mm: Physical output width in millimeters. (物理输出总宽度，单位毫米)
        total_height_mm: Physical output height in millimeters. (物理输出总高度，单位毫米)
        style: Puzzle style identifier. (拼图风格标识)
        sizing_mode: Active sizing mode. (当前尺寸控制模式)
        piece_width_mm: Requested average piece width. (请求的平均拼图块宽度)
        piece_height_mm: Requested average piece height. (请求的平均拼图块高度)
        rows: Requested row count when grid mode is used. (grid 模式下的目标行数)
        cols: Requested column count when grid mode is used. (grid 模式下的目标列数)
        target_piece_count: Requested target piece count. (目标片数)
        seed: Deterministic random seed. (确定性的随机种子)
        connector_style: Connector shape preset. (连接器轮廓预设)
        irregularity_strength: Irregular perturbation strength. (不规则扰动强度)
        min_neck_width_mm: Minimum neck width constraint. (最小脖颈宽度约束)
    """

    width_px: int
    height_px: int
    total_width_mm: float
    total_height_mm: float
    style: PuzzleStyle = "regular"
    sizing_mode: PuzzleSizingMode = "piece_size"
    piece_width_mm: float = 20.0
    piece_height_mm: float = 20.0
    rows: int = 0
    cols: int = 0
    target_piece_count: int = 0
    seed: int = 0
    connector_style: PuzzleConnectorStyle = "classic"
    irregularity_strength: float = 0.35
    min_neck_width_mm: float = 1.2
    solid_mask: np.ndarray | None = None
    mask_geometry: BaseGeometry | None = None


@dataclass(frozen=True)
class PuzzlePiece:
    """Single puzzle piece metadata.
    单个拼图块的元数据。

    Attributes:
        row: One-based row index. (从 1 开始的行号)
        col: One-based column index. (从 1 开始的列号)
        label: Stable label such as ``A1``. (稳定编号，例如 ``A1``)
        polygon_px: Piece polygon in preview pixel space. (预览像素空间中的拼图块轮廓)
        bbox_px: Inclusive-exclusive bounding box in preview pixels. (预览像素坐标系中的包围盒)
        bbox_mm: Bounding box in millimeters using top-left origin.
            (使用左上角原点的毫米包围盒)
        centroid_mm: Piece centroid in millimeters using top-left origin.
            (使用左上角原点的毫米质心)
    """

    row: int
    col: int
    label: str
    polygon_px: tuple[_Point, ...]
    bbox_px: _BBox
    bbox_mm: tuple[float, float, float, float]
    centroid_mm: tuple[float, float]
    holes_px: tuple[tuple[_Point, ...], ...] = ()
    # Only edges between two pieces receive cutter clearance.
    cut_edges_px: BaseGeometry | None = None


@dataclass(frozen=True)
class PuzzleLayout:
    """Resolved puzzle layout result.
    解析完成后的拼图布局结果。

    Attributes:
        width_px: Layout width in preview pixels. (预览像素空间总宽度)
        height_px: Layout height in preview pixels. (预览像素空间总高度)
        total_width_mm: Physical total width. (物理总宽度)
        total_height_mm: Physical total height. (物理总高度)
        rows: Resolved row count. (最终行数)
        cols: Resolved column count. (最终列数)
        derived_piece_width_mm: Average resolved piece width. (推导出的平均块宽度)
        derived_piece_height_mm: Average resolved piece height. (推导出的平均块高度)
        warnings: Non-fatal layout warnings. (非致命布局警告)
        pieces: All puzzle pieces in row-major order. (按行优先顺序排列的所有拼图块)
    """

    width_px: int
    height_px: int
    total_width_mm: float
    total_height_mm: float
    rows: int
    cols: int
    derived_piece_width_mm: float
    derived_piece_height_mm: float
    actual_piece_count: int
    layout_mode: str
    warnings: tuple[str, ...]
    pieces: tuple[PuzzlePiece, ...]


def build_puzzle_layout(config: PuzzleLayoutConfig) -> PuzzleLayout:
    """Build a deterministic puzzle layout from configuration.
    根据配置构建确定性的拼图布局。

    Args:
        config: Puzzle layout configuration. (拼图布局配置)

    Returns:
        PuzzleLayout: Resolved layout with piece polygons and metadata.
            (包含拼图块轮廓与元数据的最终布局)

    Raises:
        ValueError: If dimensions or parameters are invalid. (尺寸或参数非法时抛出)
    """

    if config.width_px <= 0 or config.height_px <= 0:
        raise ValueError("Puzzle layout requires positive preview dimensions.")
    if config.total_width_mm <= 0 or config.total_height_mm <= 0:
        raise ValueError("Puzzle layout requires positive physical dimensions.")

    rows, cols = _resolve_grid(config)
    rng = random.Random(config.seed)
    warnings: list[str] = []
    min_neck_px = _min_neck_pixels(config)

    vertices = _build_vertices(config, rows, cols, rng)
    horizontal_edges: dict[tuple[int, int], tuple[_Point, ...]] = {}
    vertical_edges: dict[tuple[int, int], tuple[_Point, ...]] = {}

    straightened_edges = 0
    for row in range(1, rows):
        for col in range(cols):
            start = vertices[row][col]
            end = vertices[row][col + 1]
            edge_points, used_connector = _build_connector_points(
                start,
                end,
                1,
                config.connector_style,
                min_neck_px,
                edge_key=_build_edge_key(
                    orientation="horizontal",
                    row=row,
                    col=col,
                    rows=rows,
                    cols=cols,
                    connector_style=config.connector_style,
                ),
            )
            if not used_connector:
                straightened_edges += 1
            horizontal_edges[(row, col)] = edge_points

    for row in range(rows):
        for col in range(1, cols):
            start = vertices[row][col]
            end = vertices[row + 1][col]
            edge_points, used_connector = _build_connector_points(
                start,
                end,
                1,
                config.connector_style,
                min_neck_px,
                edge_key=_build_edge_key(
                    orientation="vertical",
                    row=row,
                    col=col,
                    rows=rows,
                    cols=cols,
                    connector_style=config.connector_style,
                ),
            )
            if not used_connector:
                straightened_edges += 1
            vertical_edges[(row, col)] = edge_points

    straightened_edges += _stabilize_shared_edges(
        rows=rows,
        cols=cols,
        vertices=vertices,
        horizontal_edges=horizontal_edges,
        vertical_edges=vertical_edges,
    )

    if straightened_edges > 0:
        warnings.append(
            f"{straightened_edges} internal edges were left straight because they were too small for interlocking tabs."
        )

    mm_per_px_x = config.total_width_mm / config.width_px
    mm_per_px_y = config.total_height_mm / config.height_px

    base_piece_polygons: list[tuple[int, int, list[_Point]]] = []
    for row in range(rows):
        for col in range(cols):
            polygon = _build_piece_polygon(
                row,
                col,
                rows,
                cols,
                vertices,
                horizontal_edges,
                vertical_edges,
            )
            base_piece_polygons.append((row, col, polygon))

    mask_geometry = _build_mask_geometry(config)
    layout_mode = "mask_aware" if mask_geometry is not None else "rectangular"
    pieces: list[PuzzlePiece]
    if mask_geometry is None:
        pieces = [
            _piece_from_polygon_points(
                polygon=polygon,
                row=row + 1,
                col=col + 1,
                width_px=config.width_px,
                height_px=config.height_px,
                mm_per_px_x=mm_per_px_x,
                mm_per_px_y=mm_per_px_y,
            )
            for row, col, polygon in base_piece_polygons
        ]
    else:
        target_piece_area_px = max(
            1.0,
            float(mask_geometry.area) / max(rows * cols, 1),
        )
        piece_records = _build_mask_aware_piece_records(
            base_piece_polygons=base_piece_polygons,
            mask_geometry=mask_geometry,
            target_piece_area_px=target_piece_area_px,
            min_neck_px=min_neck_px,
        )
        pieces = _build_mask_aware_pieces(
            piece_records=piece_records,
            width_px=config.width_px,
            height_px=config.height_px,
            mm_per_px_x=mm_per_px_x,
            mm_per_px_y=mm_per_px_y,
            derived_piece_height_px=config.height_px / max(rows, 1),
        )
        expected_piece_count = rows * cols
        if len(pieces) != expected_piece_count:
            warnings.append(
                "Actual piece count differs from the requested grid after transparent-boundary cleanup."
            )

    footprint = mask_geometry if mask_geometry is not None else box(0, 0, config.width_px, config.height_px)
    source_edges = footprint.boundary
    pieces = [
        replace(piece, cut_edges_px=Polygon(piece.polygon_px, piece.holes_px).boundary.difference(source_edges))
        for piece in pieces
    ]
    return PuzzleLayout(
        width_px=config.width_px,
        height_px=config.height_px,
        total_width_mm=config.total_width_mm,
        total_height_mm=config.total_height_mm,
        rows=rows,
        cols=cols,
        derived_piece_width_mm=round(config.total_width_mm / cols, 4),
        derived_piece_height_mm=round(config.total_height_mm / rows, 4),
        actual_piece_count=len(pieces),
        layout_mode=layout_mode,
        warnings=tuple(warnings),
        pieces=tuple(pieces),
    )


def resolve_puzzle_mask_geometry(config: PuzzleLayoutConfig) -> BaseGeometry | None:
    """Resolve polygonal mask geometry for puzzle layout reuse.
    解析可复用的拼图实体蒙版几何。

    Args:
        config: Puzzle layout configuration carrying mask metadata.
            (携带蒙版信息的拼图布局配置)

    Returns:
        BaseGeometry | None: Polygonal mask geometry or ``None`` for full-rect masks.
            (多边形实体蒙版几何；若为整矩形则返回 ``None``)
    """

    return _build_mask_geometry(config)


def _piece_from_polygon_points(
    *,
    polygon: list[_Point],
    row: int,
    col: int,
    width_px: int,
    height_px: int,
    mm_per_px_x: float,
    mm_per_px_y: float,
) -> PuzzlePiece:
    """Convert polygon points into a serializable puzzle piece.
    将多边形点集转换为可序列化的拼图块。
    """

    bbox_px = _polygon_bbox(polygon, width_px, height_px)
    centroid_px = _polygon_centroid(polygon)
    bbox_mm = (
        round(bbox_px[0] * mm_per_px_x, 4),
        round(bbox_px[1] * mm_per_px_y, 4),
        round(bbox_px[2] * mm_per_px_x, 4),
        round(bbox_px[3] * mm_per_px_y, 4),
    )
    centroid_mm = (
        round(centroid_px[0] * mm_per_px_x, 4),
        round(centroid_px[1] * mm_per_px_y, 4),
    )
    return PuzzlePiece(
        row=row,
        col=col,
        label=_format_piece_label(row - 1, col - 1),
        polygon_px=tuple(polygon),
        bbox_px=bbox_px,
        bbox_mm=bbox_mm,
        centroid_mm=centroid_mm,
    )


def _build_mask_geometry(config: PuzzleLayoutConfig) -> BaseGeometry | None:
    """Resolve cached or mask-derived geometry for transparent-aware layouts.
    解析缓存或由实体蒙版生成的透明约束几何。
    """

    if config.mask_geometry is not None:
        return _normalize_polygonal_geometry(config.mask_geometry)

    if config.solid_mask is None:
        return None

    solid_mask = np.asarray(config.solid_mask, dtype=bool)
    if solid_mask.shape != (config.height_px, config.width_px):
        raise ValueError("Puzzle solid mask shape does not match preview dimensions.")
    if not np.any(solid_mask) or _mask_is_full_rect(solid_mask):
        return None

    # Preserve the whole area of each occupied pixel. Tracing pixel centres
    # instead shrinks the body and widens every genuine hole by one pixel.
    transitions = np.diff(solid_mask.view(np.int8), axis=1, prepend=np.int8(0), append=np.int8(0))
    rows, starts = np.nonzero(transitions == 1)
    _, stops = np.nonzero(transitions == -1)
    return union_all(box(starts, rows, stops, rows + 1)).simplify(0)


def _mask_is_full_rect(solid_mask: np.ndarray) -> bool:
    """Return whether a solid mask covers the full preview rectangle.
    判断实体蒙版是否覆盖整个预览矩形。
    """

    return bool(np.all(solid_mask))


def _normalize_polygonal_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    """Normalize polygonal geometry and drop non-polygon parts.
    规范化多边形几何并丢弃非多边形部分。
    """

    if geometry is None or geometry.is_empty:
        return None

    candidate = geometry.buffer(0) if not geometry.is_valid else geometry
    if candidate.is_empty:
        return None
    if isinstance(candidate, Polygon):
        return candidate
    if isinstance(candidate, MultiPolygon):
        return candidate
    if isinstance(candidate, GeometryCollection):
        polygons = [part for part in candidate.geoms if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty]
        if not polygons:
            return None
        return _normalize_polygonal_geometry(unary_union(polygons))
    return None


def _build_mask_aware_piece_records(
    *,
    base_piece_polygons: list[tuple[int, int, list[_Point]]],
    mask_geometry: BaseGeometry,
    target_piece_area_px: float,
    min_neck_px: float,
) -> list[_PieceGeometryRecord]:
    """Clip base puzzle cells to the solid mask and merge tiny fragments.
    将基础拼图网格裁切到实体蒙版内，并合并细碎小块。
    """

    records: list[_PieceGeometryRecord] = []
    for _row, _col, polygon_points in base_piece_polygons:
        base_polygon = _normalize_polygonal_geometry(Polygon(polygon_points))
        if base_polygon is None:
            continue
        clipped = _normalize_polygonal_geometry(base_polygon.intersection(mask_geometry))
        for polygon_part in _iter_polygon_parts(clipped):
            if polygon_part.area < 1.0:
                continue
            centroid = polygon_part.centroid
            records.append(
                _PieceGeometryRecord(
                    geometry=polygon_part,
                    centroid_px=(float(centroid.x), float(centroid.y)),
                )
            )

    if not records:
        fallback_records: list[_PieceGeometryRecord] = []
        for polygon_part in _iter_polygon_parts(mask_geometry):
            centroid = polygon_part.centroid
            fallback_records.append(
                _PieceGeometryRecord(
                    geometry=polygon_part,
                    centroid_px=(float(centroid.x), float(centroid.y)),
                )
            )
        records = fallback_records

    return _merge_small_piece_records(
        records=records,
        mask_geometry=mask_geometry,
        target_piece_area_px=target_piece_area_px,
        min_neck_px=min_neck_px,
    )


def _iter_polygon_parts(geometry: BaseGeometry | None) -> tuple[Polygon, ...]:
    """Flatten polygonal geometry into individual polygon parts.
    将多边形几何拍平为独立 Polygon 序列。
    """

    normalized = _normalize_polygonal_geometry(geometry)
    if normalized is None:
        return ()
    if isinstance(normalized, Polygon):
        return (normalized,)
    if isinstance(normalized, MultiPolygon):
        return tuple(polygon for polygon in normalized.geoms if not polygon.is_empty)
    return ()


def _merge_small_piece_records(
    *,
    records: list[_PieceGeometryRecord],
    mask_geometry: BaseGeometry,
    target_piece_area_px: float,
    min_neck_px: float,
) -> list[_PieceGeometryRecord]:
    """Merge tiny boundary fragments into adjacent printable pieces.
    将过小的边界碎块合并到相邻且更可打印的拼图块。
    """

    mutable_records = list(records)
    while len(mutable_records) > 1:
        merge_index = _find_record_to_merge(
            records=mutable_records,
            mask_geometry=mask_geometry,
            target_piece_area_px=target_piece_area_px,
            min_neck_px=min_neck_px,
        )
        if merge_index is None:
            break

        target_index = _choose_merge_neighbor(
            source_index=merge_index,
            records=mutable_records,
            mask_geometry=mask_geometry,
            target_piece_area_px=target_piece_area_px,
        )
        if target_index is None:
            break

        source_record = mutable_records[merge_index]
        target_record = mutable_records[target_index]
        merged_geometry = _normalize_polygonal_geometry(
            source_record.geometry.union(target_record.geometry)
        )
        if not isinstance(merged_geometry, Polygon):
            break
        centroid = merged_geometry.centroid
        mutable_records[target_index] = _PieceGeometryRecord(
            geometry=merged_geometry,
            centroid_px=(float(centroid.x), float(centroid.y)),
        )
        del mutable_records[merge_index]

    return mutable_records


def _find_record_to_merge(
    *,
    records: list[_PieceGeometryRecord],
    mask_geometry: BaseGeometry,
    target_piece_area_px: float,
    min_neck_px: float,
) -> int | None:
    """Pick the next fragile record that should be merged away.
    选择下一个需要被合并掉的脆弱拼图块。
    """

    boundary_candidates: list[int] = []
    interior_candidates: list[int] = []
    for index, record in enumerate(records):
        touches_boundary = _touches_mask_boundary(record.geometry, mask_geometry)
        min_span = _geometry_min_span(record.geometry)
        area_limit = target_piece_area_px * (0.45 if touches_boundary else 0.18)
        span_limit = max(min_neck_px * (0.95 if touches_boundary else 0.7), 4.0)
        if record.geometry.area < area_limit or min_span < span_limit:
            if touches_boundary:
                boundary_candidates.append(index)
            else:
                interior_candidates.append(index)

    if boundary_candidates:
        return min(boundary_candidates, key=lambda idx: records[idx].geometry.area)
    if interior_candidates:
        return min(interior_candidates, key=lambda idx: records[idx].geometry.area)
    return None


def _choose_merge_neighbor(
    *,
    source_index: int,
    records: list[_PieceGeometryRecord],
    mask_geometry: BaseGeometry,
    target_piece_area_px: float,
) -> int | None:
    """Choose the best adjacent record to absorb a fragile piece.
    为脆弱拼图块选择最佳相邻吸收目标。
    """

    source_record = records[source_index]
    source_is_boundary = _touches_mask_boundary(source_record.geometry, mask_geometry)
    best_index: int | None = None
    best_score: tuple[int, float, float] | None = None

    for index, candidate in enumerate(records):
        if index == source_index:
            continue
        shared_boundary = source_record.geometry.boundary.intersection(candidate.geometry.boundary).length
        if shared_boundary <= 0.5:
            continue
        candidate_is_boundary = _touches_mask_boundary(candidate.geometry, mask_geometry)
        merged_area = source_record.geometry.area + candidate.geometry.area
        area_penalty = abs(merged_area - target_piece_area_px)
        score = (
            1 if source_is_boundary and candidate_is_boundary else 0,
            shared_boundary,
            -area_penalty,
        )
        if best_score is None or score > best_score:
            best_score = score
            best_index = index

    return best_index


def _touches_mask_boundary(geometry: BaseGeometry, mask_geometry: BaseGeometry) -> bool:
    """Return whether geometry touches the outer boundary of the solid mask.
    判断几何是否触及实体蒙版外边界。
    """

    return geometry.boundary.intersection(mask_geometry.boundary).length > 0.5


def _geometry_min_span(geometry: BaseGeometry) -> float:
    """Return the smaller span of a geometry bounding box.
    返回几何外接包围盒的较小边长。
    """

    min_x, min_y, max_x, max_y = geometry.bounds
    return min(max_x - min_x, max_y - min_y)


def _build_mask_aware_pieces(
    *,
    piece_records: list[_PieceGeometryRecord],
    width_px: int,
    height_px: int,
    mm_per_px_x: float,
    mm_per_px_y: float,
    derived_piece_height_px: float,
) -> list[PuzzlePiece]:
    """Convert merged mask-aware records into stable puzzle pieces.
    将合并后的透明约束拼图块转换为稳定排序的 PuzzlePiece。
    """

    if not piece_records:
        return []

    grouped_rows = _group_records_by_row(
        piece_records=piece_records,
        row_tolerance_px=max(derived_piece_height_px * 0.5, 8.0),
    )
    pieces: list[PuzzlePiece] = []
    for row_index, row_group in enumerate(grouped_rows):
        sorted_group = sorted(row_group, key=lambda record: record.centroid_px[0])
        for col_index, record in enumerate(sorted_group):
            pieces.append(
                _piece_from_geometry(
                    geometry=record.geometry,
                    row=row_index + 1,
                    col=col_index + 1,
                    width_px=width_px,
                    height_px=height_px,
                    mm_per_px_x=mm_per_px_x,
                    mm_per_px_y=mm_per_px_y,
                )
            )
    return pieces


def _group_records_by_row(
    *,
    piece_records: list[_PieceGeometryRecord],
    row_tolerance_px: float,
) -> list[list[_PieceGeometryRecord]]:
    """Group piece records into stable visual rows using centroid Y.
    使用质心 Y 将拼图块分组为稳定的视觉行。
    """

    groups: list[list[_PieceGeometryRecord]] = []
    for record in sorted(piece_records, key=lambda item: (item.centroid_px[1], item.centroid_px[0])):
        for group in groups:
            average_y = sum(item.centroid_px[1] for item in group) / len(group)
            if abs(record.centroid_px[1] - average_y) <= row_tolerance_px:
                group.append(record)
                break
        else:
            groups.append([record])
    return groups


def _piece_from_geometry(
    *,
    geometry: Polygon,
    row: int,
    col: int,
    width_px: int,
    height_px: int,
    mm_per_px_x: float,
    mm_per_px_y: float,
) -> PuzzlePiece:
    """Convert polygon geometry into the final puzzle piece representation.
    将 Polygon 几何转换为最终拼图块表示。
    """

    exterior = tuple((float(x), float(y)) for x, y in list(geometry.exterior.coords)[:-1])
    bbox_px = _geometry_bbox(geometry, width_px, height_px)
    centroid = geometry.centroid
    centroid_mm = (
        round(float(centroid.x) * mm_per_px_x, 4),
        round(float(centroid.y) * mm_per_px_y, 4),
    )
    bbox_mm = (
        round(bbox_px[0] * mm_per_px_x, 4),
        round(bbox_px[1] * mm_per_px_y, 4),
        round(bbox_px[2] * mm_per_px_x, 4),
        round(bbox_px[3] * mm_per_px_y, 4),
    )
    holes_px = tuple(
        tuple((float(x), float(y)) for x, y in list(interior.coords)[:-1])
        for interior in geometry.interiors
        if len(interior.coords) >= 4
    )
    return PuzzlePiece(
        row=row,
        col=col,
        label=_format_piece_label(row - 1, col - 1),
        polygon_px=exterior,
        bbox_px=bbox_px,
        bbox_mm=bbox_mm,
        centroid_mm=centroid_mm,
        holes_px=holes_px,
    )


def _geometry_bbox(geometry: Polygon, width_px: int, height_px: int) -> _BBox:
    """Clamp polygon bounds into an inclusive-exclusive preview bbox.
    将 Polygon 外接框钳制为预览空间中的包围盒。
    """

    min_x, min_y, max_x, max_y = geometry.bounds
    x0 = max(0, int(math.floor(min_x)) - 1)
    y0 = max(0, int(math.floor(min_y)) - 1)
    x1 = min(width_px, int(math.ceil(max_x)) + 2)
    y1 = min(height_px, int(math.ceil(max_y)) + 2)
    return (x0, y0, max(x0 + 1, x1), max(y0 + 1, y1))


def render_puzzle_overlay(
    layout: PuzzleLayout,
    labels_enabled: bool = False,
    visibility_mask: np.ndarray | None = None,
) -> Image.Image:
    """Render a transparent overlay PNG for a puzzle layout.
    渲染用于预览的透明拼图叠线图。

    Args:
        layout: Resolved puzzle layout. (解析后的拼图布局)
        labels_enabled: Whether to draw stable piece labels. (是否绘制稳定编号)

    Returns:
        Image.Image: RGBA overlay image aligned to preview pixel space.
            (与预览像素空间对齐的 RGBA 叠线图)
    """

    overlay = Image.new("RGBA", (layout.width_px, layout.height_px), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default()
    line_width = max(1, layout.width_px // 320)

    for piece in layout.pieces:
        points = _clamp_overlay_points(piece.polygon_px, layout.width_px, layout.height_px)
        if len(points) < 2:
            continue
        draw.line(points + [points[0]], fill=(20, 184, 166, 255), width=line_width)
        for hole in piece.holes_px:
            hole_points = _clamp_overlay_points(hole, layout.width_px, layout.height_px)
            if len(hole_points) >= 2:
                draw.line(
                    hole_points + [hole_points[0]],
                    fill=(20, 184, 166, 255),
                    width=line_width,
                )
        if labels_enabled:
            cx = piece.centroid_mm[0] * layout.width_px / max(layout.total_width_mm, 1e-6)
            cy = piece.centroid_mm[1] * layout.height_px / max(layout.total_height_mm, 1e-6)
            text = piece.label
            text_bbox = draw.textbbox((0, 0), text, font=font)
            text_w = text_bbox[2] - text_bbox[0]
            text_h = text_bbox[3] - text_bbox[1]
            pad = 2
            rect = (
                int(round(cx - text_w / 2 - pad)),
                int(round(cy - text_h / 2 - pad)),
                int(round(cx + text_w / 2 + pad)),
                int(round(cy + text_h / 2 + pad)),
            )
            draw.rounded_rectangle(rect, radius=4, fill=(15, 23, 42, 176))
            draw.text(
                (int(round(cx - text_w / 2)), int(round(cy - text_h / 2))),
                text,
                font=font,
                fill=(255, 255, 255, 255),
            )

    if visibility_mask is not None:
        mask_array = np.asarray(visibility_mask)
        if mask_array.shape != (layout.height_px, layout.width_px):
            raise ValueError("Puzzle overlay visibility mask shape does not match layout dimensions.")
        overlay_array = np.array(overlay, copy=True)
        visible_mask = mask_array.astype(bool, copy=False)
        if layout.layout_mode == "mask_aware":
            radius_px = max(1, int(math.ceil(line_width / 2)))
            mask_u8 = np.where(visible_mask, 255, 0).astype(np.uint8, copy=False)
            visible_mask = cv2.dilate(
                mask_u8,
                np.ones((3, 3), dtype=np.uint8),
                iterations=radius_px,
            ).astype(bool)
        solid_alpha = np.where(visible_mask, 255, 0).astype(np.uint8, copy=False)
        overlay_array[..., 3] = np.minimum(overlay_array[..., 3], solid_alpha)
        overlay = Image.fromarray(overlay_array, mode="RGBA")

    return overlay


def _clamp_overlay_points(points: tuple[_Point, ...] | list[_Point], width_px: int, height_px: int) -> list[_Point]:
    """Clamp preview overlay coordinates into the drawable pixel canvas."""

    max_x = max(0.0, float(width_px - 1))
    max_y = max(0.0, float(height_px - 1))
    return [
        (
            min(max(float(x), 0.0), max_x),
            min(max(float(y), 0.0), max_y),
        )
        for x, y in points
    ]


def _format_piece_label(row_index: int, col_index: int) -> str:
    """Format a stable spreadsheet-style piece label.
    生成稳定的表格式拼图编号。

    Args:
        row_index: Zero-based row index. (从 0 开始的行索引)
        col_index: Zero-based column index. (从 0 开始的列索引)

    Returns:
        str: Label such as ``A1`` or ``AA12``. (例如 ``A1`` 或 ``AA12`` 的编号)
    """

    row_value = row_index + 1
    letters: list[str] = []
    while row_value > 0:
        row_value, remainder = divmod(row_value - 1, 26)
        letters.append(chr(ord("A") + remainder))
    return f"{''.join(reversed(letters))}{col_index + 1}"


def render_assembly_overview(
    source_rgba: np.ndarray,
    layout: PuzzleLayout,
    labels_enabled: bool = False,
    *,
    visibility_mask: np.ndarray | None = None,
) -> Image.Image:
    """Render an assembly overview image from source RGBA and puzzle layout.
    根据源 RGBA 图与拼图布局渲染拼装总览图。

    Args:
        source_rgba: Full source RGBA image in preview pixel space.
            (预览像素空间中的整图 RGBA)
        layout: Resolved puzzle layout. (解析后的拼图布局)
        labels_enabled: Whether to draw piece labels. (是否绘制拼图块编号)

    Returns:
        Image.Image: Assembly overview image. (拼装总览图)
    """

    base = Image.fromarray(source_rgba.astype(np.uint8), mode="RGBA")
    overlay = render_puzzle_overlay(
        layout,
        labels_enabled=labels_enabled,
        visibility_mask=visibility_mask if visibility_mask is not None else source_rgba[..., 3] > 0,
    )
    return Image.alpha_composite(base, overlay)


def export_piece_boundary_geometry(
    piece: PuzzlePiece,
    *,
    raster_size: tuple[int, int] | None = None,
    inset_px: float = 0.0,
) -> dict[str, object]:
    """Export the piece on the crop-local worker grid, with clearance only at cuts."""
    x0, y0, x1, y1 = piece.bbox_px
    sx, sy = (1.0, 1.0) if raster_size is None else (
        raster_size[0] / (x1 - x0), raster_size[1] / (y1 - y0),
    )
    if inset_px <= 0:
        def local(ring: tuple[_Point, ...]) -> list[list[float]]:
            return [[(x - x0) * sx, (y - y0) * sy] for x, y in ring]

        return {
            "bbox_px": list(piece.bbox_px), "polygon_px": local(piece.polygon_px),
            "holes_px": [local(ring) for ring in piece.holes_px],
        }
    transform = (sx, 0.0, 0.0, sy, -x0 * sx, -y0 * sy)
    polygon = affine_transform(Polygon(piece.polygon_px, piece.holes_px), transform)
    cuts = piece.cut_edges_px
    if cuts is None:
        # A standalone piece has no layout to distinguish shared and outer edges.
        printable = polygon.buffer(-inset_px, join_style="mitre")
    else:
        cuts = affine_transform(cuts, transform)
        printable = polygon.difference(cuts.buffer(inset_px, cap_style="flat", join_style="mitre"))
    if isinstance(printable, Polygon) and not printable.is_empty:
        polygon = printable
    return {
        "bbox_px": list(piece.bbox_px),
        "polygon_px": _geometry_ring_to_json(polygon.exterior.coords),
        "holes_px": [_geometry_ring_to_json(ring.coords) for ring in polygon.interiors],
    }


def inset_boundary_geometry_payload(
    payload: dict[str, object],
    inset_px: float,
) -> dict[str, object]:
    """Inset a crop-local puzzle boundary payload by a cutter clearance.
    按切刀间隙向内收缩局部拼图边界载荷。

    Args:
        payload: Boundary payload produced by ``export_piece_boundary_geometry``.
            (由 ``export_piece_boundary_geometry`` 生成的边界载荷)
        inset_px: Inset distance in the payload's local pixel grid.
            (在载荷局部像素网格中的向内收缩距离)

    Returns:
        dict[str, object]: JSON-serializable inset boundary payload. If the
            inset would destroy a fragile polygon, the original payload is
            returned unchanged so generation remains deterministic.
            (可 JSON 序列化的收缩后边界；若收缩会破坏脆弱多边形，则返回原载荷，
            保证生成流程稳定)
    """

    cloned_payload = _clone_boundary_payload(payload)
    if inset_px <= 0.0:
        return cloned_payload

    polygon_points = cloned_payload["polygon_px"]
    if len(polygon_points) < 3:
        return cloned_payload

    polygon = Polygon(
        polygon_points,
        holes=cloned_payload["holes_px"],
    )
    normalized_polygon = _normalize_polygonal_geometry(polygon)
    if not isinstance(normalized_polygon, Polygon):
        return cloned_payload

    inset_geometry = _normalize_polygonal_geometry(
        normalized_polygon.buffer(-float(inset_px), join_style=2)
    )
    if not isinstance(inset_geometry, Polygon):
        return cloned_payload

    return {
        "bbox_px": cloned_payload["bbox_px"],
        "polygon_px": _geometry_ring_to_json(inset_geometry.exterior.coords),
        "holes_px": [
            _geometry_ring_to_json(interior.coords)
            for interior in inset_geometry.interiors
            if len(interior.coords) >= 4
        ],
    }


def _clone_boundary_payload(payload: dict[str, object]) -> dict[str, object]:
    """Return a normalized JSON-compatible boundary payload copy."""

    return {
        "bbox_px": [int(value) for value in payload.get("bbox_px") or []],
        "polygon_px": _coerce_payload_ring(payload.get("polygon_px") or []),
        "holes_px": [
            _coerce_payload_ring(hole)
            for hole in payload.get("holes_px") or []
        ],
    }


def _coerce_payload_ring(points: object) -> list[list[float]]:
    """Coerce an arbitrary payload point ring to ``[[x, y], ...]`` floats."""

    ring: list[list[float]] = []
    if not isinstance(points, (list, tuple)):
        return ring
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        ring.append([float(point[0]), float(point[1])])
    return ring


def _geometry_ring_to_json(coords: object) -> list[list[float]]:
    """Convert a Shapely coordinate sequence to a JSON point ring."""

    return [[float(x), float(y)] for x, y in list(coords)[:-1]]


def rasterize_piece_mask(piece: PuzzlePiece) -> tuple[_BBox, np.ndarray]:
    """Rasterize a piece polygon into a local alpha mask.
    将拼图块轮廓栅格化为局部 alpha 蒙版。

    Args:
        piece: Piece metadata containing polygon and bounding box.
            (包含轮廓与包围盒的拼图块元数据)

    Returns:
        tuple[_BBox, np.ndarray]: Bounding box and uint8 mask within that box.
            (包围盒以及该局部区域内的 uint8 蒙版)
    """

    x0, y0, x1, y1 = piece.bbox_px
    inside = contains_xy(
        Polygon(piece.polygon_px, piece.holes_px),
        np.arange(x0, x1)[None, :] + 0.5,
        np.arange(y0, y1)[:, None] + 0.5,
    )
    return piece.bbox_px, inside.astype(np.uint8) * 255


def _resolve_grid(config: PuzzleLayoutConfig) -> tuple[int, int]:
    if config.sizing_mode == "grid":
        return max(1, int(config.rows or 1)), max(1, int(config.cols or 1))

    if config.sizing_mode == "piece_count":
        target = max(1, int(config.target_piece_count or 1))
        aspect = config.total_width_mm / max(config.total_height_mm, 1e-6)
        best_rows = 1
        best_cols = target
        best_score = float("inf")
        search_limit = max(1, int(math.ceil(math.sqrt(target) * 3)))
        for rows in range(1, max(target, search_limit) + 1):
            cols = max(1, round(target / rows))
            piece_count = rows * cols
            grid_aspect = cols / max(rows, 1e-6)
            score = abs(piece_count - target) * 1000 + abs(grid_aspect - aspect) * 100
            if score < best_score:
                best_rows = rows
                best_cols = cols
                best_score = score
        return best_rows, best_cols

    piece_width = max(config.piece_width_mm, 1e-6)
    piece_height = max(config.piece_height_mm, 1e-6)
    cols = max(1, round(config.total_width_mm / piece_width))
    rows = max(1, round(config.total_height_mm / piece_height))
    return rows, cols


def _build_vertices(
    config: PuzzleLayoutConfig,
    rows: int,
    cols: int,
    rng: random.Random,
) -> list[list[_Point]]:
    x_coords = [config.width_px * col / cols for col in range(cols + 1)]
    y_coords = [config.height_px * row / rows for row in range(rows + 1)]
    vertices: list[list[_Point]] = [
        [(x_coords[col], y_coords[row]) for col in range(cols + 1)]
        for row in range(rows + 1)
    ]

    if config.style != "irregular":
        return vertices

    cell_w = config.width_px / cols
    cell_h = config.height_px / rows
    min_neck_px = _min_neck_pixels(config)
    max_shift_x = max(0.0, min(cell_w * 0.32 * config.irregularity_strength, max((cell_w - min_neck_px) * 0.25, 0.0)))
    max_shift_y = max(0.0, min(cell_h * 0.32 * config.irregularity_strength, max((cell_h - min_neck_px) * 0.25, 0.0)))

    for row in range(1, rows):
        for col in range(1, cols):
            base_x = x_coords[col]
            base_y = y_coords[row]
            left_bound = x_coords[col - 1] + min_neck_px * 0.5
            right_bound = x_coords[col + 1] - min_neck_px * 0.5
            top_bound = y_coords[row - 1] + min_neck_px * 0.5
            bottom_bound = y_coords[row + 1] - min_neck_px * 0.5

            shifted_x = base_x + rng.uniform(-max_shift_x, max_shift_x)
            shifted_y = base_y + rng.uniform(-max_shift_y, max_shift_y)
            clamped_x = min(max(shifted_x, left_bound), right_bound)
            clamped_y = min(max(shifted_y, top_bound), bottom_bound)
            vertices[row][col] = (clamped_x, clamped_y)

    return vertices


def _build_connector_points(
    start: _Point,
    end: _Point,
    sign: int,
    connector_style: PuzzleConnectorStyle,
    min_neck_px: float,
    *,
    edge_key: str | None = None,
) -> tuple[tuple[_Point, ...], bool]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 1e-6:
        return (start, end), False

    preset = _BEZIER_CONNECTOR_PRESETS[connector_style]
    neck_span_px = 2.0 * preset.tab_size_ratio * length
    head_span_px = 4.0 * preset.tab_size_ratio * length
    required_neck_span_px = max(min_neck_px * preset.min_neck_multiplier, 8.0)
    required_head_span_px = max(min_neck_px * preset.min_head_multiplier, 12.0)
    if neck_span_px < required_neck_span_px or head_span_px < required_head_span_px:
        return (start, end), False

    tangent = (dx / length, dy / length)
    normal = (-tangent[1], tangent[0])
    params = _resolve_connector_params(
        edge_key
        or f"{connector_style}:{start[0]:.4f}:{start[1]:.4f}:{end[0]:.4f}:{end[1]:.4f}:{sign}",
        preset,
    )
    normal_sign = params.flip * (1 if sign >= 0 else -1)
    control_points = _build_connector_control_points(params)
    cubic_points: list[_Point] = []
    segments = (
        (control_points[0], control_points[1], control_points[2], control_points[3], False),
        (control_points[3], control_points[4], control_points[5], control_points[6], False),
        (control_points[6], control_points[7], control_points[8], control_points[9], True),
    )
    for p0, p1, p2, p3, include_endpoint in segments:
        cubic_points.extend(
            _sample_cubic_connector_segment(
                start=start,
                tangent=tangent,
                normal=normal,
                length=length,
                normal_sign=normal_sign,
                p0=p0,
                p1=p1,
                p2=p2,
                p3=p3,
                samples=preset.samples_per_segment,
                include_endpoint=include_endpoint,
            )
        )

    return tuple(cubic_points), True


@dataclass(frozen=True)
class _ConnectorParams:
    """Deterministic normalized control-point parameters for one shared edge."""

    flip: int
    a: float
    b: float
    c: float
    d: float
    e: float
    tab_size_ratio: float
    head_multiplier: float


def _build_edge_key(
    *,
    orientation: str,
    row: int,
    col: int,
    rows: int,
    cols: int,
    connector_style: PuzzleConnectorStyle,
) -> str:
    """Build a stable edge identity for deterministic connector geometry."""

    return f"{orientation}:{row}:{col}:{rows}:{cols}:{connector_style}"


def _resolve_connector_params(
    edge_key: str,
    preset: _BezierConnectorPreset,
) -> _ConnectorParams:
    """Resolve deterministic tab parameters from a stable edge hash."""

    digest = hashlib.sha256(edge_key.encode("utf-8")).digest()
    values = [
        int.from_bytes(digest[index * 4 : (index + 1) * 4], "big") / 0xFFFFFFFF
        for index in range(6)
    ]
    jitter = preset.jitter_ratio
    return _ConnectorParams(
        flip=-1 if values[0] < 0.5 else 1,
        a=(values[1] * 2.0 - 1.0) * jitter,
        b=(values[2] * 2.0 - 1.0) * jitter,
        c=(values[3] * 2.0 - 1.0) * jitter,
        d=(values[4] * 2.0 - 1.0) * jitter,
        e=(values[5] * 2.0 - 1.0) * jitter,
        tab_size_ratio=preset.tab_size_ratio,
        head_multiplier=preset.head_multiplier,
    )


def _build_connector_control_points(params: _ConnectorParams) -> tuple[_Point, ...]:
    """Build normalized Draradech-style control points for one connector edge."""

    t = params.tab_size_ratio
    head_height = params.head_multiplier * t
    return (
        (0.0, 0.0),
        (0.2, params.a),
        (0.5 + params.b + params.d, -t + params.c),
        (0.5 - t + params.b, t + params.c),
        (0.5 - 2.0 * t + params.b - params.d, head_height + params.c),
        (0.5 + 2.0 * t + params.b - params.d, head_height + params.c),
        (0.5 + t + params.b, t + params.c),
        (0.5 + params.b + params.d, -t + params.c),
        (0.8, params.e),
        (1.0, 0.0),
    )


def _sample_cubic_connector_segment(
    *,
    start: _Point,
    tangent: _Point,
    normal: _Point,
    length: float,
    normal_sign: int,
    p0: _Point,
    p1: _Point,
    p2: _Point,
    p3: _Point,
    samples: int,
    include_endpoint: bool,
) -> list[_Point]:
    """Sample one cubic Bezier segment into projected edge-space points."""

    if include_endpoint:
        t_values = [index / max(samples - 1, 1) for index in range(samples)]
    else:
        t_values = [index / max(samples, 1) for index in range(samples)]

    return [
        _project_connector_point(
            start=start,
            tangent=tangent,
            normal=normal,
            length=length,
            normal_sign=normal_sign,
            local_point=_sample_cubic_bezier(p0, p1, p2, p3, t_value),
        )
        for t_value in t_values
    ]


def _sample_cubic_bezier(
    p0: _Point,
    p1: _Point,
    p2: _Point,
    p3: _Point,
    t_value: float,
) -> _Point:
    """Sample a cubic Bezier in normalized edge space."""

    inv_t = 1.0 - t_value
    x_value = (
        inv_t**3 * p0[0]
        + 3.0 * inv_t * inv_t * t_value * p1[0]
        + 3.0 * inv_t * t_value * t_value * p2[0]
        + t_value**3 * p3[0]
    )
    y_value = (
        inv_t**3 * p0[1]
        + 3.0 * inv_t * inv_t * t_value * p1[1]
        + 3.0 * inv_t * t_value * t_value * p2[1]
        + t_value**3 * p3[1]
    )
    return (x_value, y_value)


def _project_connector_point(
    *,
    start: _Point,
    tangent: _Point,
    normal: _Point,
    length: float,
    normal_sign: int,
    local_point: _Point,
) -> _Point:
    """Project a normalized connector point onto an actual edge segment."""

    along = local_point[0] * length
    off = local_point[1] * length * normal_sign
    return (
        start[0] + tangent[0] * along + normal[0] * off,
        start[1] + tangent[1] * along + normal[1] * off,
    )


def _stabilize_shared_edges(
    *,
    rows: int,
    cols: int,
    vertices: list[list[_Point]],
    horizontal_edges: dict[tuple[int, int], tuple[_Point, ...]],
    vertical_edges: dict[tuple[int, int], tuple[_Point, ...]],
) -> int:
    """Straighten only the shared edges required to keep pieces valid."""

    straightened = 0
    while True:
        progress = False
        for row in range(rows):
            for col in range(cols):
                if _is_piece_geometry_valid(
                    row=row,
                    col=col,
                    rows=rows,
                    cols=cols,
                    vertices=vertices,
                    horizontal_edges=horizontal_edges,
                    vertical_edges=vertical_edges,
                ):
                    continue

                candidates = _candidate_shared_edges_for_piece(
                    row=row,
                    col=col,
                    rows=rows,
                    cols=cols,
                    vertices=vertices,
                )
                if not candidates:
                    continue

                best_combo = _choose_straightening_combo(
                    row=row,
                    col=col,
                    rows=rows,
                    cols=cols,
                    vertices=vertices,
                    horizontal_edges=horizontal_edges,
                    vertical_edges=vertical_edges,
                    candidates=candidates,
                )
                if best_combo is None:
                    continue

                for candidate in best_combo:
                    edge_map = horizontal_edges if candidate["kind"] == "horizontal" else vertical_edges
                    edge_map[candidate["key"]] = (candidate["start"], candidate["end"])
                straightened += len(best_combo)
                progress = True

        if not progress:
            break

    return straightened


def _is_piece_geometry_valid(
    *,
    row: int,
    col: int,
    rows: int,
    cols: int,
    vertices: list[list[_Point]],
    horizontal_edges: dict[tuple[int, int], tuple[_Point, ...]],
    vertical_edges: dict[tuple[int, int], tuple[_Point, ...]],
) -> bool:
    """Return whether a piece polygon is valid and free of self-overlap."""

    polygon_points = _build_piece_polygon(
        row=row,
        col=col,
        rows=rows,
        cols=cols,
        vertices=vertices,
        horizontal_edges=horizontal_edges,
        vertical_edges=vertical_edges,
    )
    polygon = Polygon(polygon_points)
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 1.0:
        return False
    normalized = _normalize_polygonal_geometry(polygon)
    return isinstance(normalized, Polygon)


def _candidate_shared_edges_for_piece(
    *,
    row: int,
    col: int,
    rows: int,
    cols: int,
    vertices: list[list[_Point]],
) -> list[dict[str, object]]:
    """Collect internal shared edges incident to one piece."""

    candidates: list[dict[str, object]] = []
    if row > 0:
        candidates.append(
            {
                "kind": "horizontal",
                "key": (row, col),
                "start": vertices[row][col],
                "end": vertices[row][col + 1],
                "affected": ((row - 1, col), (row, col)),
            }
        )
    if col < cols - 1:
        candidates.append(
            {
                "kind": "vertical",
                "key": (row, col + 1),
                "start": vertices[row][col + 1],
                "end": vertices[row + 1][col + 1],
                "affected": ((row, col), (row, col + 1)),
            }
        )
    if row < rows - 1:
        candidates.append(
            {
                "kind": "horizontal",
                "key": (row + 1, col),
                "start": vertices[row + 1][col],
                "end": vertices[row + 1][col + 1],
                "affected": ((row, col), (row + 1, col)),
            }
        )
    if col > 0:
        candidates.append(
            {
                "kind": "vertical",
                "key": (row, col),
                "start": vertices[row][col],
                "end": vertices[row + 1][col],
                "affected": ((row, col - 1), (row, col)),
            }
        )
    return candidates


def _choose_straightening_combo(
    *,
    row: int,
    col: int,
    rows: int,
    cols: int,
    vertices: list[list[_Point]],
    horizontal_edges: dict[tuple[int, int], tuple[_Point, ...]],
    vertical_edges: dict[tuple[int, int], tuple[_Point, ...]],
    candidates: list[dict[str, object]],
) -> tuple[dict[str, object], ...] | None:
    """Choose the smallest edge set that resolves a piece self-overlap."""

    baseline_coords = {
        tuple(coord)
        for candidate in candidates
        for coord in candidate["affected"]  # type: ignore[index]
    }
    baseline_score = _piece_invalid_score(
        coords=baseline_coords,
        rows=rows,
        cols=cols,
        vertices=vertices,
        horizontal_edges=horizontal_edges,
        vertical_edges=vertical_edges,
        focus=(row, col),
    )

    candidate_combos: list[tuple[dict[str, object], ...]] = [
        (candidate,) for candidate in candidates
    ]
    if len(candidates) >= 2:
        for first_index in range(len(candidates)):
            for second_index in range(first_index + 1, len(candidates)):
                candidate_combos.append((candidates[first_index], candidates[second_index]))

    best_combo: tuple[dict[str, object], ...] | None = None
    best_score: tuple[int, int, int] | None = None
    original_edges: dict[tuple[str, tuple[int, int]], tuple[_Point, ...]] = {}
    for candidate in candidates:
        map_key = (candidate["kind"], candidate["key"])  # type: ignore[index]
        edge_map = horizontal_edges if candidate["kind"] == "horizontal" else vertical_edges
        original_edges[map_key] = edge_map[candidate["key"]]  # type: ignore[index]

    for combo in candidate_combos:
        affected_coords = set(baseline_coords)
        for candidate in combo:
            edge_map = horizontal_edges if candidate["kind"] == "horizontal" else vertical_edges
            edge_map[candidate["key"]] = (candidate["start"], candidate["end"])  # type: ignore[index]
            for coord in candidate["affected"]:  # type: ignore[index]
                affected_coords.add(tuple(coord))

        score = _piece_invalid_score(
            coords=affected_coords,
            rows=rows,
            cols=cols,
            vertices=vertices,
            horizontal_edges=horizontal_edges,
            vertical_edges=vertical_edges,
            focus=(row, col),
        )
        for candidate in combo:
            edge_map = horizontal_edges if candidate["kind"] == "horizontal" else vertical_edges
            map_key = (candidate["kind"], candidate["key"])  # type: ignore[index]
            edge_map[candidate["key"]] = original_edges[map_key]  # type: ignore[index]

        if best_score is None or score < best_score:
            best_score = score
            best_combo = combo

    if best_combo is None or best_score is None:
        return None
    if best_score >= baseline_score:
        return None
    return best_combo


def _piece_invalid_score(
    *,
    coords: set[tuple[int, int]],
    rows: int,
    cols: int,
    vertices: list[list[_Point]],
    horizontal_edges: dict[tuple[int, int], tuple[_Point, ...]],
    vertical_edges: dict[tuple[int, int], tuple[_Point, ...]],
    focus: tuple[int, int],
) -> tuple[int, int, int]:
    """Score a local edge configuration; lower is better."""

    focus_invalid = 1
    invalid_count = 0
    for candidate_row, candidate_col in coords:
        if candidate_row < 0 or candidate_col < 0 or candidate_row >= rows or candidate_col >= cols:
            continue
        is_valid = _is_piece_geometry_valid(
            row=candidate_row,
            col=candidate_col,
            rows=rows,
            cols=cols,
            vertices=vertices,
            horizontal_edges=horizontal_edges,
            vertical_edges=vertical_edges,
        )
        if (candidate_row, candidate_col) == focus:
            focus_invalid = 0 if is_valid else 1
        if not is_valid:
            invalid_count += 1
    return (focus_invalid, invalid_count, len(coords))


def _build_piece_polygon(
    row: int,
    col: int,
    rows: int,
    cols: int,
    vertices: list[list[_Point]],
    horizontal_edges: dict[tuple[int, int], tuple[_Point, ...]],
    vertical_edges: dict[tuple[int, int], tuple[_Point, ...]],
) -> list[_Point]:
    top_left = vertices[row][col]
    top_right = vertices[row][col + 1]
    bottom_right = vertices[row + 1][col + 1]
    bottom_left = vertices[row + 1][col]

    if row == 0:
        top = (top_left, top_right)
    else:
        top = horizontal_edges[(row, col)]

    if col == cols - 1:
        right = (top_right, bottom_right)
    else:
        right = vertical_edges[(row, col + 1)]

    if row == rows - 1:
        bottom = (bottom_left, bottom_right)
    else:
        bottom = horizontal_edges[(row + 1, col)]

    if col == 0:
        left = (top_left, bottom_left)
    else:
        left = vertical_edges[(row, col)]

    polygon: list[_Point] = list(top)
    polygon.extend(right[1:])
    polygon.extend(reversed(bottom[:-1]))
    polygon.extend(reversed(left[:-1]))
    return polygon


def _polygon_bbox(points: list[_Point], width_px: int, height_px: int) -> _BBox:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    x0 = max(0, int(math.floor(min(xs))) - 1)
    y0 = max(0, int(math.floor(min(ys))) - 1)
    x1 = min(width_px, int(math.ceil(max(xs))) + 2)
    y1 = min(height_px, int(math.ceil(max(ys))) + 2)
    return (x0, y0, max(x0 + 1, x1), max(y0 + 1, y1))


def _polygon_centroid(points: list[_Point]) -> _Point:
    if len(points) < 3:
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return (sum(xs) / max(len(xs), 1), sum(ys) / max(len(ys), 1))

    area_acc = 0.0
    cx_acc = 0.0
    cy_acc = 0.0
    for index, point in enumerate(points):
        next_point = points[(index + 1) % len(points)]
        cross = point[0] * next_point[1] - next_point[0] * point[1]
        area_acc += cross
        cx_acc += (point[0] + next_point[0]) * cross
        cy_acc += (point[1] + next_point[1]) * cross

    if abs(area_acc) < 1e-6:
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        return ((min(xs) + max(xs)) / 2.0, (min(ys) + max(ys)) / 2.0)

    area = area_acc * 0.5
    return (cx_acc / (6.0 * area), cy_acc / (6.0 * area))


def _min_neck_pixels(config: PuzzleLayoutConfig) -> float:
    px_per_mm_x = config.width_px / max(config.total_width_mm, 1e-6)
    px_per_mm_y = config.height_px / max(config.total_height_mm, 1e-6)
    px_per_mm = min(px_per_mm_x, px_per_mm_y)
    return max(1.0, config.min_neck_width_mm * px_per_mm)
