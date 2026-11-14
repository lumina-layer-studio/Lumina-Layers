"""Explicit, lossless working coordinates for native SVG topology.

原生 SVG 拓扑的显式、无损计算坐标；源单位仅用于投影与物理尺度。
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np
import shapely
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon


PRINT_GRID_KEY = "svg_print_grid_mm"


def should_mirror_vector_export(
    structure_mode: str,
    color_mode: str,
    *,
    enable_relief: bool = False,
) -> bool:
    """Mirror only face-down artwork, consistently for body and auxiliaries."""
    is_single_sided = "单面" in structure_mode or "Single" in structure_mode
    return is_single_sided and "5-Color Extended" not in color_mode and not enable_relief


def _area_geometry(geometry: Any) -> Any:
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    polygons = []
    if isinstance(geometry, GeometryCollection):
        for part in geometry.geoms:
            area = _area_geometry(part)
            if isinstance(area, Polygon) and not area.is_empty:
                polygons.append(area)
            elif isinstance(area, MultiPolygon):
                polygons.extend(area.geoms)
    return MultiPolygon(polygons) if polygons else GeometryCollection()


SVG_COORDINATE_CONTRACT_VERSION = 1


@dataclass(frozen=True)
class SvgCoordinateDomain:
    """Carry the native grid and source-unit mapping through serialization.

    携带原生格距与源单位映射，供缓存和跨进程恢复使用。
    """

    source_grid_size: float
    source_mm_per_unit: float
    source_bbox: tuple[float, float, float, float]
    version: int = SVG_COORDINATE_CONTRACT_VERSION
    frame_origin_mm: tuple[float, float] = (0.0, 0.0)
    frame_extent_mm: tuple[float, float] | None = None
    source_viewport_bounds: tuple[float, float, float, float] | None = None

    def __post_init__(self) -> None:
        if self.version != SVG_COORDINATE_CONTRACT_VERSION:
            raise ValueError("Unsupported SVG coordinate contract")
        if any(not math.isfinite(v) or v <= 0 for v in (
            self.source_grid_size, self.source_mm_per_unit,
        )):
            raise ValueError("SVG coordinate scales must be positive and finite")
        if len(self.source_bbox) != 4 or not all(
            math.isfinite(v) for v in self.source_bbox
        ):
            raise ValueError("SVG source bounds must be finite")
        if len(self.frame_origin_mm) != 2 or not all(math.isfinite(v) for v in self.frame_origin_mm):
            raise ValueError("SVG frame origin must be finite")
        if self.frame_extent_mm is not None and (
            len(self.frame_extent_mm) != 2
            or not all(math.isfinite(v) and v > 0 for v in self.frame_extent_mm)
        ):
            raise ValueError("SVG frame extent must be positive and finite")

    @property
    def grid_size(self) -> float:
        """Return a binary-power grid encoding native integer coordinates.

        返回无损承载原生整数的二进制幂格距。
        """
        return math.ldexp(1.0, math.frexp(self.source_grid_size)[1] - 1)

    @property
    def source_units_per_unit(self) -> float:
        """Return source SVG units per working unit. 返回每计算单位的源单位数。"""
        return self.source_grid_size / self.grid_size

    @property
    def mm_per_unit(self) -> float:
        """Return physical millimetres per working unit. 返回计算单位对应毫米数。"""
        return self.source_mm_per_unit * self.source_units_per_unit

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """Return viewport bounds in working units. 返回计算坐标中的画布边界。"""
        if self.frame_extent_mm is not None:
            return (0.0, 0.0, *(value / self.mm_per_unit for value in self.frame_extent_mm))
        return tuple(value / self.source_units_per_unit for value in self.source_bbox)

    def restore_precision(self, geometry: Any) -> Any:
        """Restore a known grid after pickle/WKB, without repairing geometry.

        在 pickle/WKB 往返后恢复已知精度模型，不做几何修复。
        """
        if geometry is None or shapely.get_precision(geometry) == self.grid_size:
            return geometry
        coordinates = shapely.get_coordinates(geometry)
        units = coordinates / self.grid_size
        if not np.all(np.isfinite(units)) or not np.array_equal(units, np.rint(units)):
            raise ValueError("SVG topology is not on its declared coordinate grid")
        return shapely.set_precision(geometry, self.grid_size, mode="pointwise")

    def restore_records(self, records: list[dict], key: str = "geometry") -> list[dict]:
        """Restore precision on detached records. 在独立记录上恢复几何精度。"""
        restored = []
        for record in records:
            copy = {**record, key: self.restore_precision(record.get(key))}
            if PRINT_GRID_KEY in copy and "print_geometry" in copy:
                coordinates = shapely.get_coordinates(copy["print_geometry"])
                if not np.array_equal(coordinates, np.rint(coordinates)):
                    raise ValueError("Cached print geometry is not on its integer grid")
                copy["print_geometry"] = shapely.set_precision(copy["print_geometry"], 1.0, mode="pointwise")
            restored.append(copy)
        return restored


def _native_grid_regions(geometries: list[Any], units_per_coordinate: float) -> list[Any]:
    from lumina_svg_core import project_regions_to_grid

    rings_by_region = []
    for geometry in geometries:
        rings = []
        if geometry is not None and not geometry.is_empty:
            oriented = _area_geometry(shapely.orient_polygons(geometry))
            parts = (oriented,) if isinstance(oriented, Polygon) else oriented.geoms
            for part in parts:
                if isinstance(part, Polygon):
                    rings.append(np.asarray(part.exterior.coords))
                    rings.extend(np.asarray(hole.coords) for hole in part.interiors)
        rings_by_region.append(rings)
    projected = project_regions_to_grid(rings_by_region, units_per_coordinate)
    output = []
    for region in projected:
        parts = [Polygon(shell, holes) for shell, holes in region]
        geometry = (
            parts[0] if len(parts) == 1 else MultiPolygon(parts)
        ) if parts else GeometryCollection()
        if not geometry.is_valid:
            raise ValueError("Native print-grid projection returned invalid topology")
        output.append(shapely.set_precision(geometry, 1.0, mode="pointwise"))
    return output


def _native_canonical_grid_regions(regions: list[list[Any]]) -> list[Any]:
    """Re-express owned integer-grid cells without a second boolean cleanup."""
    from lumina_svg_core import canonicalize_grid_regions

    rings_by_region: list[list[np.ndarray]] = []
    for cells in regions:
        rings = []
        for cell in cells:
            area = _area_geometry(cell)
            if not area.is_valid:
                raise ValueError("Owned print-grid cells must be valid polygons")
            oriented = shapely.orient_polygons(area)
            coordinates = shapely.get_coordinates(oriented)
            if not np.all(np.isfinite(coordinates)) or not np.array_equal(
                coordinates, np.rint(coordinates),
            ):
                raise ValueError("Owned print-grid cells must use integer coordinates")
            if np.any(np.abs(coordinates) > 2**52):
                raise ValueError("Owned print-grid coordinates exceed the exact integer range")
            parts = (oriented,) if isinstance(oriented, Polygon) else oriented.geoms
            for part in parts:
                if isinstance(part, Polygon):
                    rings.append(np.asarray(part.exterior.coords))
                    rings.extend(np.asarray(hole.coords) for hole in part.interiors)
        rings_by_region.append(rings)

    canonical = canonicalize_grid_regions(rings_by_region)
    output = []
    for region in canonical:
        parts = [Polygon(shell, holes) for shell, holes in region]
        geometry = (
            parts[0] if len(parts) == 1 else MultiPolygon(parts)
        ) if parts else GeometryCollection()
        if not geometry.is_valid:
            raise ValueError("Native integer-grid canonicalization returned invalid topology")
        output.append(shapely.set_precision(geometry, 1.0, mode="pointwise"))
    return output


def project_print_regions(
    geometries: list[Any], *, mm_per_unit: float, grid_mm: float,
    metrics: dict | None = None,
    resolve_ownership: bool = True,
) -> list[Any]:
    """Project labelled regions through one shared native target grid.

    全部带归属的区域经同一次平面分区进入统一打印网格，返回整数坐标。

    Args:
        geometries: Working-domain regions in draw order. 按绘制顺序排列的区域。
        mm_per_unit: Millimetres per working unit. 每计算单位对应的毫米数。
        grid_mm: Shared writer-grid spacing. 共用写出格距（毫米）。
        metrics: Optional timing-record statistics. 可选的既有计时记录统计。
        resolve_ownership: Assign optical overlaps by paint order; auxiliary
            slabs retain intentional overlap. 光学区域按绘制顺序分配，辅助片层可重叠。

    Returns:
        One integer-grid geometry per input region. 每个输入对应的整数网格区域。
    """
    if not all(math.isfinite(v) and v > 0 for v in (mm_per_unit, grid_mm)):
        raise ValueError("Print coordinate scales must be positive and finite")
    output = _native_grid_regions(geometries, mm_per_unit / grid_mm)
    if not resolve_ownership:
        return output
    # Quantization can create a narrow overlap between previously disjoint
    # paints. Resolve it in the declared integer domain, retaining draw order.
    values = np.asarray(output, dtype=object)
    ownership_tree = shapely.STRtree(values)
    overlap_pair_count = 0
    overlap_area_mm2 = 0.0
    if metrics is not None:
        pairs = ownership_tree.query(values, predicate="intersects")
        pairs = pairs[:, pairs[0] < pairs[1]]
        overlaps = shapely.area(shapely.intersection(
            values[pairs[0]], values[pairs[1]], grid_size=1.0,
        ))
        conflicts = pairs[:, overlaps > 0.0]
        overlap_pair_count = int(conflicts.shape[1])
        overlap_area_mm2 = float(overlaps.sum() * grid_mm**2)
    # Build the planar cells once. Sequential rounded differences can move an
    # intersection again and reintroduce overlap with an earlier neighbour.
    linework = shapely.union_all(shapely.boundary(values), grid_size=1.0)
    cells = shapely.get_parts(shapely.polygonize(shapely.get_parts(linework)))
    # Keep the ownership probe off the integer print grid. Fixed-precision
    # point_on_surface can snap a valid interior point onto a cell boundary.
    query_cells = _ownership_query_view(cells)
    centres = shapely.point_on_surface(query_cells)
    owners = np.full(len(cells), -1, dtype=np.int64)
    matches = ownership_tree.query(centres, predicate="within")
    np.maximum.at(owners, matches[0], matches[1])
    # A cell between independently quantized boundaries may have no projected
    # owner. Classify it against the authoritative source, leaving real holes
    # empty. This is a point query; source float polygon views are never built.
    missing = np.flatnonzero(owners < 0)
    if len(missing):
        source_points = shapely.points(
            shapely.get_coordinates(centres[missing]) / (mm_per_unit / grid_mm)
        )
        source_matches = shapely.STRtree(geometries).query(source_points, predicate="within")
        np.maximum.at(owners, missing[source_matches[0]], source_matches[1])
    grouped: dict[int, list[Any]] = {}
    for owner, cell in zip(owners, cells, strict=True):
        if owner >= 0:
            grouped.setdefault(int(owner), []).append(cell)
    # Rebuild each owner's coverage directly from its non-overlapping cells.
    # This avoids making a pinched GEOS union, then re-running projection-time
    # boolean cleanup on boundaries that already represent adopted coverage.
    owned_cells = [grouped.get(index, []) for index in range(len(geometries))]
    output = _native_canonical_grid_regions(owned_cells)
    if metrics is not None:
        metrics.update({
            "print_projection_region_count": len(output),
            "print_projection_overlap_pairs": overlap_pair_count,
            "print_projection_overlap_area_mm2": overlap_area_mm2,
            "print_projection_collapsed_regions": sum(g.is_empty for g in output),
            "print_projection_cell_count": len(cells),
        })
    return output


def _ownership_query_view(cells: Any) -> Any:
    """Remove inherited precision from a read-only view without moving vertices."""
    return shapely.set_precision(cells, 0.0, mode="pointwise")


def prepare_print_slabs(slabs: list[dict], *, mm_per_unit: float, grid_mm: float) -> None:
    """Prepare auxiliary slabs once without removing intentional Z overlaps.

    一次准备辅助片层，保留不同高度片层之间有意重复的覆盖范围。
    """
    pending = [slab for slab in slabs if PRINT_GRID_KEY not in slab]
    unique = {id(slab["geometry"]): slab["geometry"] for slab in pending}
    if not unique:
        return
    projected = project_print_regions(
        list(unique.values()), mm_per_unit=mm_per_unit, grid_mm=grid_mm,
        resolve_ownership=False,
    )
    by_id = dict(zip(unique, projected, strict=True))
    for slab in pending:
        slab["geometry"] = by_id[id(slab["geometry"])]
        slab[PRINT_GRID_KEY] = grid_mm
