"""Shared structural coverage and material partition for vector models.

矢量模型共用的结构覆盖范围与材料分区；不依赖配色或磁铁挖孔网格。
"""

from dataclasses import dataclass
import math

from core import geos_buffer_fast
from core.vector_layer_geometry import resolve_vector_writer_grid_mm
from core.svg_coordinate_domain import SvgCoordinateDomain

from shapely import affinity, difference
import shapely
from shapely.errors import ShapelyError
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid


def _finish_normalized_contour(geom, inflated, deflated):
    """Apply scalar _normalize_contours post-buffer fallback semantics."""

    if inflated is None or inflated.is_empty:
        return geom
    if deflated is None or deflated.is_empty:
        return geom
    if deflated.is_valid and deflated.geom_type in ("Polygon", "MultiPolygon"):
        result = deflated
    else:
        result = make_valid(deflated)
        if result is not None and result.geom_type == "GeometryCollection":
            polys = [
                part
                for part in result.geoms
                if part.geom_type in ("Polygon", "MultiPolygon")
            ]
            if polys:
                result = MultiPolygon(polys) if len(polys) > 1 else polys[0]
            else:
                result = deflated

    # A morphological close is extensive by definition: it may bridge a
    # narrow gap, but it must not remove valid source area. GEOS can violate
    # that invariant for a valid MultiPolygon whose components nearly touch,
    # returning only one component after the inward buffer. Compare source
    # coverage, not net area: area added elsewhere must never compensate for
    # a deleted printable component.
    if (
        geom.is_valid
        and geom.geom_type in ("Polygon", "MultiPolygon")
        and result is not None
        and not result.is_empty
        and result.geom_type in ("Polygon", "MultiPolygon")
    ):
        # DE-9IM cell ``IE`` asks whether any source interior lies in the
        # result exterior.  Unlike ``covers()``, this deliberately ignores
        # harmless boundary-only round-off, and unlike ``difference()`` it
        # does not allocate another full overlay geometry on this hot path.
        relate_pattern = getattr(geom, "relate_pattern", None)
        if callable(relate_pattern) and not relate_pattern(
            result,
            "**F******",
        ):
            source_parts = (
                tuple(geom.geoms)
                if isinstance(geom, MultiPolygon)
                else (geom,)
            )
            uncovered_parts = [
                part
                for part in source_parts
                if not part.relate_pattern(result, "**F******")
            ]
            if uncovered_parts:
                restored = unary_union([result, *uncovered_parts])
                if (
                    restored is not None
                    and not restored.is_empty
                    and restored.is_valid
                    and restored.geom_type in ("Polygon", "MultiPolygon")
                    # GEOS may report a spurious interior/exterior DE-9IM
                    # contact immediately after union even when the exact
                    # source difference is empty.  This overlay runs only on
                    # the rare local-recovery branch, never on the normal hot
                    # path.
                    and geom.difference(restored).is_empty
                ):
                    return restored
            return geom
    return result


def _is_dense_normalization_geometry(geom, close_delta_mm):
    """Return whether one geometry qualifies for the proven dense path."""

    return (
        float(close_delta_mm) == 0.03
        and isinstance(geom, MultiPolygon)
        and len(geom.geoms) >= geos_buffer_fast.MIN_DENSE_COMPONENTS
    )


def _normalize_contours(
    geom: BaseGeometry | None, close_delta_mm: float = 0.03,
) -> BaseGeometry | None:
    if geom is None or geom.is_empty:
        return geom
    try:
        positive_settings = geos_buffer_fast.BufferSettings(
            distance=close_delta_mm
        )
        inflated = None
        inflated_already_validated = False
        if _is_dense_normalization_geometry(geom, close_delta_mm):
            inflated = geos_buffer_fast.try_dense_positive_buffer(
                geom,
                positive_settings,
            )
            inflated_already_validated = inflated is not None
        if inflated is None:
            inflated = geom.buffer(
                close_delta_mm,
                quad_segs=1,
                join_style="mitre",
                mitre_limit=2.0,
            )

        negative_settings = geos_buffer_fast.BufferSettings(
            distance=-close_delta_mm
        )
        deflated = None
        if _is_dense_normalization_geometry(inflated, close_delta_mm):
            deflated = geos_buffer_fast.try_disconnected_inward_buffer(
                inflated,
                negative_settings,
                _input_already_validated=inflated_already_validated,
            )
        if deflated is None:
            deflated = inflated.buffer(
                -close_delta_mm,
                quad_segs=1,
                join_style="mitre",
                mitre_limit=2.0,
            )
        return _finish_normalized_contour(geom, inflated, deflated)
    except (ShapelyError, ValueError, TypeError):
        return geom


def _filter_backing_holes(
    geom: BaseGeometry | None, min_hole_area_mm2: float = 1.0,
) -> BaseGeometry | None:
    if geom is None or geom.is_empty:
        return geom
    if isinstance(geom, Polygon):
        holes = [hole for hole in geom.interiors if Polygon(hole).area >= min_hole_area_mm2]
        return Polygon(geom.exterior, holes)
    if isinstance(geom, MultiPolygon):
        return MultiPolygon([_filter_backing_holes(part, min_hole_area_mm2) for part in geom.geoms])
    return geom


def _prepare_footprint(
    source: BaseGeometry, scale: float, source_units_per_unit: float = 1.0,
    *, return_working: bool = False,
) -> BaseGeometry:
    # Preserve the established structural cleanup in SVG units. Converting
    # these legacy constants directly to mm would silently change the model.
    prepared = _normalize_contours(source, 0.4 / source_units_per_unit)
    prepared = _filter_backing_holes(prepared, 0.3 / source_units_per_unit**2)
    try:
        prepared = prepared.buffer(0.15 / source_units_per_unit, join_style="mitre", mitre_limit=2.0)
    except (ShapelyError, ValueError):
        pass
    if return_working:
        grid = float(shapely.get_precision(source))
        return shapely.set_precision(prepared, grid) if grid > 0 else prepared
    return affinity.scale(prepared, xfact=scale, yfact=scale, origin=(0, 0))


@dataclass(frozen=True)
class VectorStructurePlan:
    """Structural footprints with an explicit physical coordinate scale.

    主体、描边与镀层轮廓；显式比例描述每个计算单位对应的毫米数。
    """

    body: BaseGeometry
    envelope: BaseGeometry
    outline: BaseGeometry
    outline_width_mm: float
    mm_per_unit: float = 1.0
    precision_grid: float = 0.0

    def in_units(self, geometry: BaseGeometry, mm_per_unit: float) -> BaseGeometry:
        """Reuse matching working coordinates, or project a legacy mm view.

        计算坐标相同时直接复用；旧毫米轮廓按目标单位投影。
        """
        if self.mm_per_unit == mm_per_unit:
            return geometry
        factor = self.mm_per_unit / mm_per_unit
        return affinity.scale(geometry, xfact=factor, yfact=factor, origin=(0, 0))

    def __setstate__(self, state: dict) -> None:
        """Restore the structural grid across cache copies. 恢复结构缓存的精度模型。"""
        grid = float(state.get("precision_grid", 0.0))
        for key, value in state.items():
            if grid > 0 and key in {"body", "envelope", "outline"}:
                value = shapely.set_precision(value, grid, mode="pointwise")
            object.__setattr__(self, key, value)


def resolve_structure_plan(
    analysis: object, outline_width_mm: float = 0.0,
) -> VectorStructurePlan:
    """Resolve structure independently of color partition and mesh mutations.

    独立于色块分割和网格挖孔计算结构；分块后的计划直接复用。

    Args:
        analysis: SVG analysis with a source silhouette. SVG 解析结果。
        outline_width_mm: Requested expansion in mm. 描边宽度，单位毫米。

    Returns:
        Shared structural footprints in mm. 共用的毫米结构范围。
    """
    existing = getattr(analysis, "structure_plan", None)
    if isinstance(existing, VectorStructurePlan):
        if existing.outline_width_mm == outline_width_mm:
            return existing
        if outline_width_mm == 0:
            return VectorStructurePlan(
                existing.body, existing.body, GeometryCollection(), 0.0,
                existing.mm_per_unit, existing.precision_grid,
            )
        raise ValueError("Rebuild the global vector structure before changing a tiled outline width.")
    source = None
    for name in ("silhouette",):
        candidate = getattr(analysis, name, None)
        if isinstance(candidate, BaseGeometry) and not candidate.is_empty:
            source = candidate
            break
    if source is None:
        # Older cached analyses may have no silhouette. Prefer pre-match
        # geometry; never derive structural coverage from modified meshes.
        records = getattr(analysis, "clipped_shapes", None)
        if not isinstance(records, (list, tuple)) or not records:
            records = getattr(analysis, "matched_shapes", [])
        geometries = [
            item["geometry"] for item in records or []
            if isinstance(item, dict)
            and isinstance(item.get("geometry"), BaseGeometry)
        ]
        source = unary_union(geometries)
    scale = float(getattr(analysis, "scale_factor", 1.0))
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Vector structural scale must be positive and finite.")
    if not math.isfinite(outline_width_mm) or outline_width_mm < 0:
        raise ValueError("Vector outline width must be non-negative and finite.")
    svg_domain = getattr(analysis, "svg_coordinate_domain", None)
    if not isinstance(svg_domain, SvgCoordinateDomain):
        svg_domain = None
    plan_scale = scale if svg_domain is not None else 1.0
    width = outline_width_mm / plan_scale
    body = _prepare_footprint(
        source, scale,
        float(svg_domain.source_units_per_unit) if svg_domain is not None else 1.0,
        return_working=svg_domain is not None,
    )
    envelope = (
        body.buffer(width, join_style="mitre", mitre_limit=2.0)
        if outline_width_mm > 0 else body
    )
    if outline_width_mm > 0 and not body.is_empty:
        # Bound acute miter tips by the same requested expansion on each axis.
        x0, y0, x1, y1 = body.bounds
        envelope = shapely.intersection(
            envelope, box(x0 - width, y0 - width, x1 + width, y1 + width),
            grid_size=svg_domain.grid_size if svg_domain is not None else 0.0,
        )
    outline = GeometryCollection()
    if outline_width_mm > 0 and not envelope.is_empty:
        writer_grid_mm = resolve_vector_writer_grid_mm(
            max(abs(value) for value in envelope.bounds) * plan_scale
        )
        if svg_domain is None:
            # Legacy millimetre analyses must put all three footprints on
            # the same grid. Snapping only the subtraction leaves fine seams.
            body = shapely.set_precision(body, writer_grid_mm)
            envelope = shapely.set_precision(envelope, writer_grid_mm)
        outline = difference(
            envelope, body,
            grid_size=svg_domain.grid_size if svg_domain is not None else writer_grid_mm,
        )
    return VectorStructurePlan(
        body, envelope, outline, outline_width_mm, plan_scale,
        svg_domain.grid_size if svg_domain is not None else 0.0,
    )
