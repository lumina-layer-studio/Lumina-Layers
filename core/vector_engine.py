"""
Lumina Studio - Native Vector Engine (v2 - Chroma-aligned)

SVG to 3D mesh conversion using vector geometry operations.
Aligned with ChromaPrint3D's processing philosophy:

Pipeline:
    SVG → Parse Paths → Occlusion Clip → Match Colors → Run-Length Extrude
        → Silhouette Backing → (optional Double-sided) → Assemble Scene

Key changes from v1:
    - Per-shape reverse-order occlusion clipping (no "small feature" exemptions)
    - Per-unique-color recipe caching via LUT KDTree
    - Run-length layer extrusion (consecutive same-channel layers merged)
    - No micro Z-offset between overlapping colors on the same material
    - Output objects sorted by material ID for stable slicer ordering
"""

import os
import re
import json
import io
import pickle
import warnings
import math
import tempfile
from contextlib import contextmanager
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from typing import Any
import numpy as np
import time
import xml.etree.ElementTree as ET
import trimesh
import cv2
from dataclasses import dataclass, field
from svgelements import (
    SVG,
    Path,
    Shape,
    Move,
    Line,
    Close,
    CubicBezier,
    QuadraticBezier,
    Arc,
    Color,
    Length,
)
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
)
from shapely import affinity
try:
    from shapely import get_num_coordinates
except ImportError:  # Shapely < 2.0; fall back to coordinate iteration.
    get_num_coordinates = None
try:
    from shapely import buffer as shapely_buffer
except ImportError:  # Shapely < 2.0; scalar geometry.buffer remains available.
    shapely_buffer = None
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree
from shapely.validation import make_valid
from shapely import (
    difference as grid_difference,
    get_precision,
    intersection as grid_intersection,
    set_precision,
    union_all,
)
from shapely.errors import ShapelyError
try:
    from shapely.prepared import prep
except ImportError:  # Keep evenodd merging available if prepared geometries are absent.
    prep = None
try:
    from shapely import symmetric_difference_all
except ImportError:  # Shapely < 2.0; keep sequential evenodd merge available.
    symmetric_difference_all = None
try:
    from shapely import disjoint_subset_union_all
except ImportError:  # Shapely < 2.1; keep the old union path available.
    disjoint_subset_union_all = None

from api.structured_logging import get_logger
from config import PrinterConfig, ColorSystem, VectorConfig
from core import geos_buffer_fast
from core import native_svg_adapter
from core.svg_arc_geometry import parse_svg_document, parse_svg_path
from core.svg_coordinate_domain import (
    PRINT_GRID_KEY,
    SVG_COORDINATE_CONTRACT_VERSION,
    SvgCoordinateDomain,
    project_print_regions,
    prepare_print_slabs,
)
from core.errors import CoreDependencyError
from core.layered_coordinate_domain import (
    LAYERED_COORDINATE_DOMAIN_KEY,
    LayeredCoordinateDomain,
)
from core.task_parallelism import (
    resolve_task_parallelism_plan,
    task_parallelism_worker_scope,
)
from core.vector_mesh_memory import get_process_rss_bytes
from core.vector_layer_geometry import (
    VectorLayerGeometryPolicy,
    build_vector_layered_volume,
    resolve_vector_writer_grid_mm,
)
from core.vector_material_meshing import materialize_material_meshes
from core.vector_mesh_spill import transform_layered_mesh
from core.vector_structure import (
    VectorStructurePlan,
    _finish_normalized_contour,
    _is_dense_normalization_geometry,
    _normalize_contours as _structure_normalize_contours,
    resolve_structure_plan,
    _filter_backing_holes as _structure_filter_backing_holes,
)

_log = get_logger(__name__)

BASE_COLOR_GAP_MM = 0.005
_MAX_BEZIER_DEPTH = 16

# Supersample factor for the hard membership masks (mask_solid / matched_rgb /
# quantized_image / material_matrix) built in ``build_preview_cache``. Plain
# ``cv2.fillPoly`` truncates float vertices to int at base resolution and can
# drop geometry-covered pixels along edges / thin interior-hole borders,
# producing the 1px seams users saw as "holes" in the hair (clickable as
# background, exported as air). Filling on an N× sub-grid restricted to each
# shape's bbox and center-sampling decides membership by "pixel center inside
# geometry", eliminating those seams. 4 reduces the reported seam from 208 to
# only sub-pixel boundary jitter (<1px) while keeping cost ~shape_area*16.
# 外观面归属掩膜的超采样倍率：修复 fillPoly 整数截断导致的 1px 缝。
_MASK_SUPERSAMPLE = 4
_ARC_SAMPLE_POSITIONS_10 = np.linspace(0.1, 1.0, 10)
_ARC_SAMPLE_POSITIONS_10.setflags(write=False)
_ARC_SAMPLE_POSITIONS_10_TUPLE = tuple(float(value) for value in _ARC_SAMPLE_POSITIONS_10)
# Additional cubic approximation uses 1% of the existing legacy flatten
# tolerance, before later viewport/clip mappings. It does not change that
# pipeline's existing sampling or promise a total physical-error bound.
_SVG_ARC_APPROXIMATION_BUDGET_RATIO = 0.01
_VECTOR_LARGE_DISTANCE_WARN_LIMIT = 8
_VECTOR_SPATIAL_GROUP_CHUNK_BYTES = 64 * 1024 * 1024


def _estimate_relief_backing_run_count(
    matched_shapes,
    *,
    num_layers: int,
    layer_height_mm: float,
    default_height_mm: float,
    height_mode: str,
    color_height_map: dict | None,
    heightmap_max_height: float | None,
) -> int:
    """Estimate the worst-case atomic-prism multiplicity for relief.

    估算浮雕底板按高度分层后可能产生的原子棱柱倍数。

    Distinct backing heights node each other's boundaries. With ``n`` height
    levels, the exact Python fallback can retain up to ``n * (n + 1) / 2``
    cell/interval combinations. This scalar estimate deliberately avoids a
    preflight union or any additional coordinate buffers.
    """

    valid_shapes = [
        item
        for item in (matched_shapes or ())
        if isinstance(item, dict)
        and item.get("geometry") is not None
        and not getattr(item.get("geometry"), "is_empty", True)
        and item.get("recipe")
    ]
    shape_count = len(valid_shapes)
    if shape_count <= 0:
        return 0

    layer_height = max(float(layer_height_mm), np.finfo(np.float64).eps)
    optical_layers = max(1, int(num_layers))
    minimum_total_layers = optical_layers + 1
    default_backing_layers = max(
        1,
        int(round(max(float(default_height_mm), layer_height) / layer_height)),
    )
    default_total_layers = max(
        minimum_total_layers,
        default_backing_layers + optical_layers,
    )

    resolved_mode = str(height_mode or "color").lower()
    if resolved_mode == "heightmap":
        try:
            maximum_height = float(heightmap_max_height or default_height_mm)
        except (TypeError, ValueError, OverflowError):
            maximum_height = float(default_height_mm)
        if not math.isfinite(maximum_height) or maximum_height <= 0:
            maximum_height = float(default_height_mm)
        maximum_total_layers = max(
            minimum_total_layers,
            int(math.ceil(maximum_height / layer_height)),
        )
        distinct_level_count = min(
            shape_count,
            max(1, maximum_total_layers - minimum_total_layers + 1),
        )
    else:
        normalized_heights: dict[str, float] = {}
        for raw_key, raw_height in (color_height_map or {}).items():
            key = str(raw_key).strip().lower()
            if not key.startswith("#"):
                key = f"#{key}"
            try:
                height = float(raw_height)
            except (TypeError, ValueError, OverflowError):
                continue
            if math.isfinite(height) and height > 0:
                normalized_heights[key] = height

        total_layer_levels: set[int] = set()
        for item in valid_shapes:
            rgb = (
                item.get("height_identity_rgb")
                or item.get("matched_rgb")
                or item.get("color")
                or ()
            )
            try:
                color_key = (
                    f"#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}"
                )
            except (TypeError, ValueError, IndexError, OverflowError):
                color_key = ""
            requested_height = normalized_heights.get(color_key)
            total_layers = (
                default_total_layers
                if requested_height is None
                else max(
                    minimum_total_layers,
                    int(math.ceil(requested_height / layer_height)),
                )
            )
            total_layer_levels.add(total_layers)
        distinct_level_count = max(1, len(total_layer_levels))

    return distinct_level_count * (distinct_level_count + 1) // 2


def _union_run_group_geometries(geometries):
    """Union run-group geometries using Shapely's sparse-geometry fast path."""

    geometries = tuple(geometries)
    precisions = {float(get_precision(geometry)) for geometry in geometries}
    if len(precisions) == 1 and next(iter(precisions), 0.0) > 0:
        return union_all(geometries, grid_size=next(iter(precisions)))
    if disjoint_subset_union_all is not None:
        try:
            return disjoint_subset_union_all(geometries)
        except VECTOR_HANDLED_ERRORS:
            pass
    return unary_union(geometries)


def _union_occluder_geometries(geometries):
    """Union occluder geometries using Shapely's disjoint-subset fast path."""

    if disjoint_subset_union_all is not None:
        try:
            return disjoint_subset_union_all(geometries)
        except VECTOR_HANDLED_ERRORS:
            pass
    return unary_union(geometries)


def _geometries_have_pairwise_intersections(items):
    """Return True if any geometry pair intersects; fail closed on errors."""

    try:
        tree = STRtree(items)
        geom_id_to_indices = {}
        for idx, geom in enumerate(items):
            geom_id_to_indices.setdefault(id(geom), []).append(idx)
        for i, geom in enumerate(items):
            try:
                candidate_refs = tree.query(geom, predicate="intersects")
                predicate_filtered = True
            except TypeError:
                candidate_refs = tree.query(geom)
                predicate_filtered = False

            for ref in candidate_refs:
                if isinstance(ref, (int, np.integer)):
                    candidate_idx = int(ref)
                    candidate_indices = [candidate_idx]
                    candidate = (
                        items[candidate_idx]
                        if 0 <= candidate_idx < len(items)
                        else None
                    )
                else:
                    candidate_indices = geom_id_to_indices.get(id(ref), [])
                    candidate = ref
                if not candidate_indices:
                    return True
                for idx in candidate_indices:
                    if idx <= i:
                        continue
                    if predicate_filtered:
                        return True
                    if candidate is None:
                        return True
                    try:
                        if geom.intersects(candidate):
                            return True
                    except VECTOR_HANDLED_ERRORS:
                        return True
        return False
    except VECTOR_HANDLED_ERRORS:
        return True


def _polygonal_union_for_disjoint_items(items):
    """Build polygonal output for already-verified disjoint geometries."""

    polygons = []
    for geom in items:
        geom_type = getattr(geom, "geom_type", "")
        if geom_type == "Polygon":
            polygons.append(geom)
        elif geom_type == "MultiPolygon":
            polygons.extend(part for part in geom.geoms if not part.is_empty)
        else:
            return unary_union(items)
    if not polygons:
        return None
    if len(polygons) == 1:
        return polygons[0]
    return MultiPolygon(polygons)


def _combine_evenodd_contained_disjoint_holes(items):
    """Fast path for one outer evenodd contour containing disjoint holes."""

    if len(items) <= 2:
        return None

    try:
        container_index, container = max(
            enumerate(items),
            key=lambda indexed: float(getattr(indexed[1], "area", 0.0) or 0.0),
        )
        children = [geom for idx, geom in enumerate(items) if idx != container_index]
        if not children:
            return None
        prepared_container = prep(container) if prep is not None else container
        if not all(prepared_container.contains(child) for child in children):
            return None
        if _geometries_have_pairwise_intersections(children):
            return None

        hole_collection = _polygonal_union_for_disjoint_items(children)
        if hole_collection is None or hole_collection.is_empty:
            return None
        result = container.difference(hole_collection)
        if result is None or result.is_empty:
            return None
        return result
    except ET.ParseError:
        return None
    except VECTOR_HANDLED_ERRORS:
        return None


def _combine_evenodd_polygons(polygons):
    """Combine subpath polygons with SVG evenodd semantics."""

    items = [poly for poly in polygons if poly is not None and not poly.is_empty]
    if not items:
        return None
    if len(items) == 1:
        return items[0]

    if not _geometries_have_pairwise_intersections(items):
        return _polygonal_union_for_disjoint_items(items)

    if len(items) == 2:
        first, second = items
        try:
            if first.contains(second):
                result = first.difference(second)
                if result is not None and not result.is_empty:
                    return result
            if second.contains(first):
                result = second.difference(first)
                if result is not None and not result.is_empty:
                    return result
        except VECTOR_HANDLED_ERRORS:
            pass

    contained_disjoint = _combine_evenodd_contained_disjoint_holes(items)
    if contained_disjoint is not None and not contained_disjoint.is_empty:
        return contained_disjoint

    if symmetric_difference_all is not None:
        try:
            result = symmetric_difference_all(items)
            if result is not None:
                return result
        except VECTOR_HANDLED_ERRORS:
            pass

    combined = items[0]
    for sp in items[1:]:
        try:
            combined = combined.symmetric_difference(sp)
        except VECTOR_HANDLED_ERRORS:
            pass
    return combined


def _color_object_to_hex(color_obj):
    """Return a lowercase hex string for svgelements Color objects."""
    if color_obj is None:
        return None
    try:
        value = getattr(color_obj, "value", None)
        if value is None or str(value).lower() == "none":
            return None
        return f"#{int(color_obj.red) & 255:02x}{int(color_obj.green) & 255:02x}{int(color_obj.blue) & 255:02x}"
    except (AttributeError, TypeError, ValueError):
        value = getattr(color_obj, "value", None)
        return None if value is None else str(value)


def _rgb_to_hex(rgb):
    """Return a stable lowercase hex string for RGB tuples."""
    try:
        return f"#{int(rgb[0]) & 255:02x}{int(rgb[1]) & 255:02x}{int(rgb[2]) & 255:02x}"
    except (IndexError, TypeError, ValueError):
        return None


def _replacement_hex_to_rgb(value: object) -> tuple[int, int, int] | None:
    """Parse one API replacement hex value without importing pipeline code."""

    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized.startswith("#"):
        normalized = normalized[1:]
    if len(normalized) != 6:
        return None
    try:
        return (
            int(normalized[0:2], 16),
            int(normalized[2:4], 16),
            int(normalized[4:6], 16),
        )
    except ValueError:
        return None


def _normalise_vector_replacement_input(
    color_replacements: object,
) -> tuple[
    dict[tuple[int, int, int], tuple[int, int, int]],
    dict[tuple[int, int, int], tuple[int, int, int]],
    dict[str, str],
]:
    """Split structured replacement records from the legacy replacement map.

    Structured records retain both the material-matched palette identity and
    the stable source-SVG identity.  Dynamic material matching can therefore
    project edits after preflight, while static matching can refresh the
    matched identity before using the historical replacement map.

    Returns:
        Targets keyed by matched RGB, targets keyed by source RGB, and the
        historical ``{matched_hex: replacement_hex}`` map.
    """

    if isinstance(color_replacements, dict):
        legacy_map: dict[str, str] = {}
        for source, target in color_replacements.items():
            if not isinstance(source, str) or not isinstance(target, str):
                continue
            source_value = source.strip().lower()
            target_value = target.strip().lower()
            if source_value and target_value:
                legacy_map[source_value] = target_value
        return {}, {}, legacy_map

    if not isinstance(color_replacements, list):
        return {}, {}, {}

    targets_by_matched: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    targets_by_source: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    legacy_map: dict[str, str] = {}
    for item in color_replacements:
        if not isinstance(item, dict):
            continue
        source = (
            item.get("matched")
            or item.get("matched_hex")
            or item.get("source")
            or item.get("quantized")
            or item.get("quantized_hex")
            or item.get("selected_color")
        )
        target = (
            item.get("replacement_hex")
            or item.get("replacement")
            or item.get("replacement_color")
        )
        if not isinstance(source, str) or not isinstance(target, str):
            continue
        source_value = source.strip().lower()
        target_value = target.strip().lower()
        if not source_value or not target_value:
            continue
        legacy_map[source_value] = target_value
        source_rgb = _replacement_hex_to_rgb(source_value)
        target_rgb = _replacement_hex_to_rgb(target_value)
        if source_rgb is not None and target_rgb is not None:
            # Assignment intentionally retains the historic last-record-wins
            # behaviour of ``_normalize_color_replacements_input``.
            targets_by_matched[source_rgb] = target_rgb
        quantized = item.get("quantized") or item.get("quantized_hex")
        quantized_rgb = (
            _replacement_hex_to_rgb(quantized)
            if isinstance(quantized, str)
            else None
        )
        if quantized_rgb is not None and target_rgb is not None:
            targets_by_source[quantized_rgb] = target_rgb
    return targets_by_matched, targets_by_source, legacy_map


def _rematch_static_vector_replacement_records(
    replacement_records: object,
    vector_processor: object,
) -> object:
    """Update structured replacement identities for a static vector palette.

    Dynamic material matching intentionally keeps source records untouched:
    its geometry-weighted preflight consumes ``quantized_hex`` directly.
    """
    if not isinstance(replacement_records, list):
        return replacement_records
    matcher = getattr(vector_processor, "img_processor", None)
    if bool(getattr(matcher, "dynamic_layer_count_enabled", False)):
        return replacement_records

    parsed: list[tuple[dict, tuple[int, int, int] | None]] = []
    source_colors: set[tuple[int, int, int]] = set()
    for item in replacement_records:
        if not isinstance(item, dict):
            continue
        quantized = item.get("quantized") or item.get("quantized_hex")
        source_rgb = (
            _replacement_hex_to_rgb(quantized)
            if isinstance(quantized, str)
            else None
        )
        parsed.append((dict(item), source_rgb))
        if source_rgb is not None:
            source_colors.add(source_rgb)

    solve_for_fills = getattr(matcher, "solve_for_fills", None)
    if callable(solve_for_fills) and source_colors:
        solve_for_fills(sorted(source_colors))

    rematched: list[dict] = []
    for item, source_rgb in parsed:
        if source_rgb is None:
            rematched.append(item)
            continue
        try:
            lut_index, _ = vector_processor._match_lut_index_for_rgb(source_rgb)
            current_rgb = matcher.lut_rgb[int(lut_index)]
            item["matched_hex"] = "#{:02x}{:02x}{:02x}".format(
                int(current_rgb[0]),
                int(current_rgb[1]),
                int(current_rgb[2]),
            )
        except (AttributeError, IndexError, TypeError, ValueError):
            pass
        rematched.append(item)
    return rematched


def _normalise_rgb_tuple(value: object) -> tuple[int, int, int] | None:
    """Return one bounded RGB tuple, or ``None`` for malformed metadata."""

    try:
        return (
            max(0, min(255, int(value[0]))),
            max(0, min(255, int(value[1]))),
            max(0, min(255, int(value[2]))),
        )
    except (TypeError, IndexError, ValueError):
        return None


def _project_dynamic_replacement_targets(
    match_input_shapes: list[dict],
    preflight_matched_shapes: list[dict],
    targets_by_matched: dict[tuple[int, int, int], tuple[int, int, int]],
    targets_by_source: dict[tuple[int, int, int], tuple[int, int, int]],
) -> tuple[list[dict], int]:
    """Project palette replacements onto per-run SVG match inputs.

    The preflight result tells us which visible palette colour each source
    shape currently maps to.  A shallow copy is made only for affected shapes
    so parse/clip cache entries retain original source colours and geometry.
    """

    projected_shapes: list[dict] = []
    projected_count = 0
    for index, item in enumerate(match_input_shapes):
        matched_shape = (
            preflight_matched_shapes[index]
            if index < len(preflight_matched_shapes)
            else None
        )
        matched_rgb = (
            _normalise_rgb_tuple(matched_shape.get("matched_rgb"))
            if isinstance(matched_shape, dict)
            else None
        )
        source_rgb = _normalise_rgb_tuple(item.get("color"))
        replacement = targets_by_source.get(source_rgb)
        if replacement is None:
            replacement = targets_by_matched.get(matched_rgb)
        if replacement is None:
            projected_shapes.append(item)
            continue
        projected = dict(item)
        projected["match_color"] = replacement
        projected_shapes.append(projected)
        projected_count += 1
    return projected_shapes, projected_count


def _flatten_cubic(
    x0,
    y0,
    x1,
    y1,
    x2,
    y2,
    x3,
    y3,
    tolerance,
    out,
    depth,
):
    """Adaptive de Casteljau subdivision for cubic Bézier curves.

    Appends flattened points to *out*.  Mirrors the algorithm used
    by ``ChromaPrint3D::FlattenCubicBezier``.
    """
    bx = x3 - x0
    by = y3 - y0
    d1 = abs((x1 - x3) * by - (y1 - y3) * bx)
    d2 = abs((x2 - x3) * by - (y2 - y3) * bx)
    len_sq = bx * bx + by * by
    tol_sq = tolerance * tolerance * len_sq
    if (d1 + d2) * (d1 + d2) <= tol_sq or depth >= _MAX_BEZIER_DEPTH:
        out.append((x3, y3))
        return
    m01x = (x0 + x1) * 0.5
    m01y = (y0 + y1) * 0.5
    m12x = (x1 + x2) * 0.5
    m12y = (y1 + y2) * 0.5
    m23x = (x2 + x3) * 0.5
    m23y = (y2 + y3) * 0.5
    m012x = (m01x + m12x) * 0.5
    m012y = (m01y + m12y) * 0.5
    m123x = (m12x + m23x) * 0.5
    m123y = (m12y + m23y) * 0.5
    mx = (m012x + m123x) * 0.5
    my = (m012y + m123y) * 0.5
    _flatten_cubic(x0, y0, m01x, m01y, m012x, m012y, mx, my, tolerance, out, depth + 1)
    _flatten_cubic(mx, my, m123x, m123y, m23x, m23y, x3, y3, tolerance, out, depth + 1)


def _flatten_quadratic(
    x0,
    y0,
    x1,
    y1,
    x2,
    y2,
    tolerance,
    out,
    depth,
):
    """Adaptive de Casteljau subdivision for quadratic Bézier curves."""
    bx = x2 - x0
    by = y2 - y0
    d = abs((x1 - x2) * by - (y1 - y2) * bx)
    len_sq = bx * bx + by * by
    if d * d <= tolerance * tolerance * len_sq or depth >= _MAX_BEZIER_DEPTH:
        out.append((x2, y2))
        return
    m01x = (x0 + x1) * 0.5
    m01y = (y0 + y1) * 0.5
    m12x = (x1 + x2) * 0.5
    m12y = (y1 + y2) * 0.5
    mx = (m01x + m12x) * 0.5
    my = (m01y + m12y) * 0.5
    _flatten_quadratic(x0, y0, m01x, m01y, mx, my, tolerance, out, depth + 1)
    _flatten_quadratic(mx, my, m12x, m12y, x2, y2, tolerance, out, depth + 1)


def _sample_gradient_stops(stops, t):
    """Interpolate colour at parameter *t* along a gradient stop list."""
    if not stops:
        return (128, 128, 128)
    if t <= stops[0][0]:
        return stops[0][1]
    if t >= stops[-1][0]:
        return stops[-1][1]
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t0 <= t <= t1:
            if t1 - t0 < 1e-9:
                return c0
            f = (t - t0) / (t1 - t0)
            return (
                int(c0[0] + (c1[0] - c0[0]) * f),
                int(c0[1] + (c1[1] - c0[1]) * f),
                int(c0[2] + (c1[2] - c0[2]) * f),
            )
    return stops[-1][1]


def _parse_svg_transform(transform_str):
    """Parse an SVG ``transform`` attribute into a 3x3 affine matrix.

    Supports ``translate``, ``scale``, ``rotate``, ``matrix``,
    ``skewX`` and ``skewY``, including concatenated transforms.

    解析 SVG transform 属性字符串为 3×3 仿射矩阵，
    支持 translate/scale/rotate/matrix/skewX/skewY 及其组合。
    """
    if not transform_str:
        return np.eye(3, dtype=np.float64)

    result = np.eye(3, dtype=np.float64)
    _tf_re = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")

    for match in _tf_re.finditer(transform_str):
        func = match.group(1)
        args = [float(v) for v in re.split(r"[\s,]+", match.group(2).strip()) if v]
        m = np.eye(3, dtype=np.float64)

        if func == "translate":
            m[0, 2] = args[0] if len(args) >= 1 else 0.0
            m[1, 2] = args[1] if len(args) >= 2 else 0.0
        elif func == "scale":
            sx = args[0] if len(args) >= 1 else 1.0
            m[0, 0] = sx
            m[1, 1] = args[1] if len(args) >= 2 else sx
        elif func == "rotate":
            angle = np.radians(args[0]) if args else 0.0
            cos_a, sin_a = np.cos(angle), np.sin(angle)
            if len(args) >= 3:
                cx, cy = args[1], args[2]
                m[0, 0] = cos_a
                m[0, 1] = -sin_a
                m[0, 2] = cx - cos_a * cx + sin_a * cy
                m[1, 0] = sin_a
                m[1, 1] = cos_a
                m[1, 2] = cy - sin_a * cx - cos_a * cy
            else:
                m[0, 0] = cos_a
                m[0, 1] = -sin_a
                m[1, 0] = sin_a
                m[1, 1] = cos_a
        elif func == "matrix" and len(args) >= 6:
            m[0, 0] = args[0]
            m[1, 0] = args[1]
            m[0, 1] = args[2]
            m[1, 1] = args[3]
            m[0, 2] = args[4]
            m[1, 2] = args[5]
        elif func == "skewX" and args:
            m[0, 1] = np.tan(np.radians(args[0]))
        elif func == "skewY" and args:
            m[1, 0] = np.tan(np.radians(args[0]))

        result = result @ m

    return result


def _parse_gradient_length(val, default=0.0):
    """Parse an SVG gradient coordinate value, handling ``%`` suffix.

    解析 SVG 渐变坐标值，支持百分比后缀。
    """
    if val is None:
        return default
    s = str(val).strip()
    if not s:
        return default
    try:
        if s.endswith("%"):
            return float(s[:-1]) / 100.0
        return float(s)
    except (ValueError, TypeError):
        return default


VECTOR_HANDLED_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    IndexError,
    AttributeError,
    OSError,
    RuntimeError,
    ImportError,
    ModuleNotFoundError,
    ArithmeticError,
    ShapelyError,
)
VECTOR_FATAL_ERRORS = (MemoryError,)

_OCCLUSION_PARALLEL_MIN_SHAPES = 64
_OCCLUSION_QUERY_CHUNKS_PER_WORKER = 8
_OCCLUSION_WORK_UNITS_PER_WORKER = 512


def _clip_occlusion_result_item(item, index, geom, occluders):
    """Build one clipped shape while retaining the serial fallback semantics."""

    geometry_normalized = False
    if not occluders:
        clipped = geom
        geometry_normalized = bool(item.get("geometry_normalized"))
    else:
        occ = (
            occluders[0]
            if len(occluders) == 1
            else _union_occluder_geometries(occluders)
        )
        try:
            clipped = geom.difference(occ)
        except VECTOR_HANDLED_ERRORS:
            try:
                fixed_geom = geom if geom.is_valid else geom.buffer(0)
                fixed_occ = occ if occ.is_valid else occ.buffer(0)
                clipped = fixed_geom.difference(fixed_occ)
            except VECTOR_HANDLED_ERRORS:
                clipped = None

    if clipped is None or clipped.is_empty:
        return None
    if not clipped.is_valid:
        clipped = make_valid(clipped)
    if clipped.is_empty:
        return None
    return {
        "geometry": clipped,
        "color": item["color"],
        "draw_order": index,
        "geometry_normalized": geometry_normalized,
    }


def _occlusion_parallel_worker_count(shape_count: int) -> int:
    """Resolve the shared CPU worker count for one occlusion pass."""

    parallelism_plan = resolve_task_parallelism_plan(
        "vector",
        work_items=shape_count,
        min_parallel_items=_OCCLUSION_PARALLEL_MIN_SHAPES,
        hard_max_workers=8,
        work_units=shape_count,
        min_parallel_work_units=_OCCLUSION_PARALLEL_MIN_SHAPES,
        work_units_per_worker=_OCCLUSION_WORK_UNITS_PER_WORKER,
    )
    return max(1, int(parallelism_plan.workers))


def _try_parallel_clip_occlusion(
    shape_data,
    orders,
    geoms,
    tree,
    *,
    reserved_workers: int = 0,
):
    """Return exact independently clipped results, or ``None`` for serial use."""

    worker_count = max(
        1,
        _occlusion_parallel_worker_count(len(orders)) - max(0, reserved_workers),
    )
    if worker_count <= 1:
        return None

    geom_array = np.asarray(geoms, dtype=object)
    candidate_indices = [[] for _item in shape_data]
    chunk_count = min(len(geoms), worker_count * _OCCLUSION_QUERY_CHUNKS_PER_WORKER)
    chunk_size = max(1, (len(geoms) + chunk_count - 1) // chunk_count)
    chunk_bounds = [
        (start, min(len(geoms), start + chunk_size))
        for start in range(0, len(geoms), chunk_size)
    ]

    def query_chunk(bounds):
        start, end = bounds
        with task_parallelism_worker_scope():
            pairs = tree.query(
                geom_array[start:end],
                predicate="intersects",
            )
        if (
            not isinstance(pairs, np.ndarray)
            or pairs.ndim != 2
            or pairs.shape[0] != 2
        ):
            raise TypeError("vector STRtree query returned an unexpected result")
        return start, pairs

    def clip_one(index):
        item = shape_data[index]
        geom = item["poly"]
        if geom is None or geom.is_empty:
            return None
        occluders = [geoms[candidate] for candidate in candidate_indices[index]]
        with task_parallelism_worker_scope():
            return _clip_occlusion_result_item(item, index, geom, occluders)

    try:
        with ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="lumina-vector-occlusion",
        ) as executor:
            for start, query_pairs in executor.map(query_chunk, chunk_bounds):
                for input_index, tree_index in zip(query_pairs[0], query_pairs[1]):
                    shape_index = orders[start + int(input_index)]
                    candidate_index = int(tree_index)
                    if orders[candidate_index] > shape_index:
                        candidate_indices[shape_index].append(candidate_index)
            possible_results = list(executor.map(clip_one, range(len(shape_data))))
    except VECTOR_HANDLED_ERRORS as exc:
        _log.warning(
            "Parallel vector occlusion unavailable; using serial clipping",
            extra={
                "event": "vector_occlusion_parallel_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "shape_count": len(shape_data),
                "worker_count": worker_count,
            },
        )
        return None

    return [item for item in possible_results if item is not None]


def _tag_local_name(elem):
    """Return an XML element's local tag name without its namespace."""

    return str(getattr(elem, "tag", "")).split("}")[-1]


_SVG_FAST_FILTER_REFERENCE_TAG_RE = re.compile(
    rb"<\s*(?:[A-Za-z_][\w.-]*:)?"
    rb"(?:defs|clipPath|mask|pattern|linearGradient|radialGradient|symbol|style|use)\b",
    re.IGNORECASE,
)
_SVG_DIRECT_UNSUPPORTED_OPEN_TAG_RE = re.compile(
    rb"<\s*(?:(?:[A-Za-z_][\w.-]*):)?"
    rb"(?!svg\b|path\b)[A-Za-z_][\w.-]*\b",
    re.IGNORECASE,
)
_SVG_FAST_FILTER_SELF_CLOSING_PATH_RE = re.compile(
    rb"<(?:[A-Za-z_][\w.-]*:)?path\b[^<>]*/\s*>",
    re.IGNORECASE | re.DOTALL,
)
_SVG_FAST_FILTER_PATH_TAG_PREFIX_RE = re.compile(
    rb"<(?:[A-Za-z_][\w.-]*:)?path\b",
    re.IGNORECASE,
)
_SVG_FAST_FILTER_GAP_FILLER_CLASS_RE = re.compile(
    rb"\bclass\s*=\s*(['\"])[^'\"]*\bqq3d-gap-filler\b[^'\"]*\1",
    re.IGNORECASE | re.DOTALL,
)
_SVG_FAST_FILTER_FILL_NONE_RE = re.compile(
    rb"\bfill\s*=\s*(['\"])\s*none\s*\1",
    re.IGNORECASE | re.DOTALL,
)
_SVG_FAST_FILTER_ID_ATTR_RE = re.compile(
    rb"\bid\s*=",
    re.IGNORECASE,
)
_SVG_FAST_FILTER_COMMON_GAP_FILLER_PREFIX = b'<path class="qq3d-gap-filler" d="'
_SVG_FAST_FILTER_COMMON_GAP_FILLER_FILL_STROKE = b'" fill="none" stroke="'
_SVG_FAST_FILTER_COMMON_GAP_FILLER_SUFFIX = (
    b'" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" '
    b'vector-effect="non-scaling-stroke"/>'
)
_SVG_FAST_FILTER_COMMON_GAP_FILLER_QUOTE_COUNT = 16


def _is_common_generated_gap_filler_path_tag(tag, stripped_tag=None):
    """Return True for Lumina's exact generated gap-filler path layout."""

    if stripped_tag is None:
        stripped_tag = tag.rstrip()
    if not tag.startswith(_SVG_FAST_FILTER_COMMON_GAP_FILLER_PREFIX):
        return False
    if not stripped_tag.endswith(_SVG_FAST_FILTER_COMMON_GAP_FILLER_SUFFIX):
        return False
    if _SVG_FAST_FILTER_COMMON_GAP_FILLER_FILL_STROKE not in stripped_tag[-256:]:
        return False
    # The fast path intentionally accepts only the exact generated attribute
    # layout. Extra attributes such as id="..." add quotes and fall back to
    # the legacy regex validator, which preserves the old "do not remove ids"
    # behavior.
    return stripped_tag.count(b'"') == _SVG_FAST_FILTER_COMMON_GAP_FILLER_QUOTE_COUNT


def _fast_filtered_gap_filler_svg_payload(payload):
    """Return bytes with generated gap-filler paths removed when safe."""

    if b"qq3d-gap-filler" not in payload or b"fill" not in payload:
        return None
    if b"data-lumina-origin" in payload or b"url(#" in payload:
        return None
    if _SVG_FAST_FILTER_REFERENCE_TAG_RE.search(payload):
        return None

    marker = b"qq3d-gap-filler"
    removed_count = 0
    chunks = []
    last_end = 0
    search_from = 0

    while True:
        marker_at = payload.find(marker, search_from)
        if marker_at < 0:
            break
        tag_start = payload.rfind(b"<", 0, marker_at)
        tag_end = payload.find(b">", marker_at)
        if tag_start < 0 or tag_end < 0:
            search_from = marker_at + len(marker)
            continue

        tag = payload[tag_start : tag_end + 1]
        stripped_tag = tag.rstrip()
        if (
            _is_common_generated_gap_filler_path_tag(tag, stripped_tag)
            or (
                _SVG_FAST_FILTER_PATH_TAG_PREFIX_RE.match(tag)
                and stripped_tag.endswith(b"/>")
                and _SVG_FAST_FILTER_GAP_FILLER_CLASS_RE.search(tag)
                and _SVG_FAST_FILTER_FILL_NONE_RE.search(tag)
                and not _SVG_FAST_FILTER_ID_ATTR_RE.search(tag)
            )
        ):
            removed_count += 1
            chunks.append(payload[last_end:tag_start])
            last_end = tag_end + 1
        search_from = tag_end + 1

    if removed_count <= 0:
        return None
    chunks.append(payload[last_end:])
    return b"".join(chunks)


def _fast_filtered_gap_filler_svg_source(svg_path):
    """Byte-filter generated gap-filler paths when no XML references exist."""

    try:
        with open(svg_path, "rb") as handle:
            payload = handle.read()
    except VECTOR_HANDLED_ERRORS:
        return None

    filtered = _fast_filtered_gap_filler_svg_payload(payload)
    if filtered is None:
        return None
    return io.BytesIO(filtered)


def _filtered_svg_source_for_vector_parse(svg_path, parse_expand_stroke_to_fill):
    """Return a filtered SVG source that omits stroke-only paths when safe."""

    if not parse_expand_stroke_to_fill:
        fast_source = _fast_filtered_gap_filler_svg_source(svg_path)
        if fast_source is not None:
            return None, fast_source

    try:
        tree = ET.parse(svg_path)
        root = tree.getroot()
    except VECTOR_HANDLED_ERRORS:
        return None, None

    def _view_box_user_size(element, fallback_size):
        raw_view_box = str(element.get("viewBox", "") or "").strip()
        try:
            values = [
                float(token)
                for token in re.split(r"[\s,]+", raw_view_box)
                if token
            ]
        except (TypeError, ValueError):
            values = []
        if (
            len(values) == 4
            and all(math.isfinite(value) for value in values)
            and values[2] > 0.0
            and values[3] > 0.0
        ):
            return values[2], values[3]
        return fallback_size

    def _resolved_length(raw_value, reference, default):
        if raw_value is None:
            return default
        try:
            value = Length(str(raw_value).strip()).value(
                ppi=96.0,
                relative_length=reference,
            )
            parsed = float(value)
        except (TypeError, ValueError, AttributeError):
            return default
        return parsed if math.isfinite(parsed) else default

    resolved_use_percentage_count = 0

    def _resolve_use_percentages(element, current_user_size):
        nonlocal resolved_use_percentage_count
        tag = _tag_local_name(element)
        if tag == "clipPath":
            return

        if tag == "svg" and element is not root:
            parent_width, parent_height = current_user_size
            for attribute_name, reference in (
                ("x", parent_width),
                ("width", parent_width),
                ("y", parent_height),
                ("height", parent_height),
            ):
                raw_value = str(element.get(attribute_name, "") or "").strip()
                if not raw_value.endswith("%"):
                    continue
                resolved = _resolved_length(raw_value, reference, None)
                if resolved is None:
                    continue
                element.set(attribute_name, format(resolved, ".12g"))
                resolved_use_percentage_count += 1

        child_user_size = current_user_size
        if tag in {"svg", "symbol"}:
            child_user_size = _view_box_user_size(element, None)
            if child_user_size is None:
                parent_width, parent_height = current_user_size
                child_user_size = (
                    _resolved_length(
                        element.get("width"),
                        parent_width,
                        parent_width,
                    ),
                    _resolved_length(
                        element.get("height"),
                        parent_height,
                        parent_height,
                    ),
                )

        if tag == "use":
            width, height = current_user_size
            for attribute_name, reference in (
                ("x", width),
                ("width", width),
                ("y", height),
                ("height", height),
            ):
                raw_value = str(element.get(attribute_name, "") or "").strip()
                if not raw_value.endswith("%"):
                    continue
                resolved = _resolved_length(raw_value, reference, None)
                if resolved is None:
                    continue
                element.set(attribute_name, format(resolved, ".12g"))
                resolved_use_percentage_count += 1

        for child in list(element):
            _resolve_use_percentages(child, child_user_size)

    root_size = _view_box_user_size(root, None)
    if root_size is None:
        root_size = (
            _resolved_length(root.get("width"), 100.0, 100.0),
            _resolved_length(root.get("height"), 100.0, 100.0),
        )
    _resolve_use_percentages(root, root_size)
    resolved_use_source = (
        io.BytesIO(ET.tostring(root, encoding="utf-8"))
        if resolved_use_percentage_count
        else None
    )

    if parse_expand_stroke_to_fill:
        return root, resolved_use_source

    reference_tags = {
        "defs",
        "clipPath",
        "mask",
        "pattern",
        "linearGradient",
        "radialGradient",
        "symbol",
        "style",
        "use",
    }
    if any(_tag_local_name(elem) in reference_tags for elem in root.iter()):
        return root, resolved_use_source

    removed_count = 0

    def _remove_ignored_paths(parent):
        nonlocal removed_count
        for child in list(parent):
            tag = _tag_local_name(child)
            if tag == "path":
                fill_value = str(child.get("fill", "")).strip().lower()
                has_id = child.get("id") is not None
                if fill_value == "none" and not has_id:
                    parent.remove(child)
                    removed_count += 1
                    continue
            _remove_ignored_paths(child)

    _remove_ignored_paths(root)
    if removed_count <= 0:
        return root, resolved_use_source

    return root, io.BytesIO(ET.tostring(root, encoding="utf-8"))


def _sample_arc_segment_points(segment, sample_count=10):
    """Sample an SVG Arc segment using svgelements' vectorized path."""

    try:
        count = int(sample_count)
        if count == 10:
            if segment.start == segment.end and segment.sweep == 0:
                point = (float(segment.start.x), float(segment.start.y))
                return [point] * len(_ARC_SAMPLE_POSITIONS_10_TUPLE)

            start_t = segment.get_start_t()
            sweep = segment.sweep
            center_x = segment.center.x
            center_y = segment.center.y
            prx_x = segment.prx.x
            prx_y = segment.prx.y
            pry_x = segment.pry.x
            pry_y = segment.pry.y
            radius_x = math.sqrt(
                (center_x - prx_x) * (center_x - prx_x)
                + (center_y - prx_y) * (center_y - prx_y)
            )
            radius_y = math.sqrt(
                (center_x - pry_x) * (center_x - pry_x)
                + (center_y - pry_y) * (center_y - pry_y)
            )
            rotation = math.atan2(prx_y - center_y, prx_x - center_x)
            cos_rotation = math.cos(rotation)
            sin_rotation = math.sin(rotation)
            end_point = (float(segment.end.x), float(segment.end.y))
            sampled_points = []
            for position in _ARC_SAMPLE_POSITIONS_10_TUPLE:
                if position == 1.0:
                    sampled_points.append(end_point)
                    continue
                t_value = start_t + (sweep * position)
                cos_t = math.cos(t_value)
                sin_t = math.sin(t_value)
                sampled_points.append(
                    (
                        float(center_x + radius_x * cos_t * cos_rotation - radius_y * sin_t * sin_rotation),
                        float(center_y + radius_x * cos_t * sin_rotation + radius_y * sin_t * cos_rotation),
                    )
                )
            return sampled_points

        positions = np.linspace(0.1, 1.0, count)
        points = segment.npoint(positions)
        arr = np.asarray(points, dtype=float)
        if arr.ndim == 2 and arr.shape[1] >= 2:
            return [(float(x), float(y)) for x, y in arr[:, :2]]
    except VECTOR_HANDLED_ERRORS:
        pass
    try:
        return [(float(segment.end.x), float(segment.end.y))]
    except VECTOR_HANDLED_ERRORS:
        return []


def _concatenate_meshes_fast(meshes):
    """Concatenate meshes as one object without retaining legacy leaf ranges."""

    items = [mesh for mesh in meshes if mesh is not None]
    if not items:
        return trimesh.Trimesh(process=False)

    def _vertices_faces(item):
        if isinstance(item, tuple) and len(item) == 2:
            vertices, faces = item
        else:
            vertices, faces = item.vertices, item.faces
        return (
            np.asarray(vertices, dtype=np.float64),
            np.asarray(faces, dtype=np.int64),
        )

    if len(items) == 1:
        if isinstance(items[0], tuple):
            vertices, faces = _vertices_faces(items[0])
            if vertices.size == 0 or faces.size == 0:
                return trimesh.Trimesh(process=False)
            return trimesh.Trimesh(
                vertices=vertices,
                faces=faces,
                process=False,
            )
        return items[0].copy()

    array_parts = []
    total_vertices = 0
    total_faces = 0
    for item in items:
        vertices, faces = _vertices_faces(item)
        if vertices.size == 0 or faces.size == 0:
            continue
        array_parts.append((vertices, faces))
        total_vertices += len(vertices)
        total_faces += len(faces)

    if not array_parts:
        return trimesh.Trimesh(process=False)
    # Allocate each final array once. The previous ``faces + offset`` list and
    # subsequent ``vstack`` kept a second full face set alive beside the final
    # output, which materially raised the assembly peak for complex SVGs.
    vertices = np.empty((total_vertices, 3), dtype=np.float64)
    faces = np.empty((total_faces, 3), dtype=np.int64)
    vertex_cursor = 0
    face_cursor = 0
    for source_vertices, source_faces in array_parts:
        next_vertex = vertex_cursor + len(source_vertices)
        next_face = face_cursor + len(source_faces)
        vertices[vertex_cursor:next_vertex] = source_vertices
        np.add(
            source_faces,
            vertex_cursor,
            out=faces[face_cursor:next_face],
            casting="unsafe",
        )
        vertex_cursor = next_vertex
        face_cursor = next_face
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def _normalize_contours_cached(cache, geom, close_delta_mm=0.03):
    """Normalize contours with a per-call-site identity cache."""

    if cache is None or geom is None:
        return VectorProcessor._normalize_contours(geom, close_delta_mm=close_delta_mm)
    key = (id(geom), round(float(close_delta_mm), 8))
    cached = cache.get(key)
    if isinstance(cached, tuple) and len(cached) == 2:
        cached_geom, cached_result = cached
        if cached_geom is geom:
            return cached_result
    result = VectorProcessor._normalize_contours(
        geom,
        close_delta_mm=close_delta_mm,
    )
    cache[key] = (geom, result)
    return result


def _stock_buffer_many(geometries, distance):
    """Run the existing Shapely vector-buffer operation for one subset."""

    if not geometries:
        return []
    geom_array = np.asarray(geometries, dtype=object)
    return list(
        shapely_buffer(
            geom_array,
            distance,
            quad_segs=1,
            join_style="mitre",
            mitre_limit=2.0,
        )
    )


def _normalize_contours_many(geometries, close_delta_mm=0.03):
    """Normalize a batch of contours with scalar-compatible semantics."""

    items = list(geometries)
    if not items:
        return []
    if shapely_buffer is None:
        cache = {}
        return [
            _normalize_contours_cached(cache, geom, close_delta_mm=close_delta_mm)
            for geom in items
        ]

    results = [None] * len(items)
    active_indices = []
    active_geoms = []
    for idx, geom in enumerate(items):
        if geom is None or geom.is_empty:
            results[idx] = geom
            continue
        active_indices.append(idx)
        active_geoms.append(geom)

    if not active_geoms:
        return results

    positive_settings = geos_buffer_fast.BufferSettings(distance=close_delta_mm)
    negative_settings = geos_buffer_fast.BufferSettings(distance=-close_delta_mm)
    try:
        inflated = [None] * len(active_geoms)
        inflated_already_validated = [False] * len(active_geoms)
        stock_positive_indices = []
        stock_positive_geometries = []
        for local_idx, geom in enumerate(active_geoms):
            candidate = None
            if _is_dense_normalization_geometry(geom, close_delta_mm):
                candidate = geos_buffer_fast.try_dense_positive_buffer(
                    geom,
                    positive_settings,
                )
            if candidate is None:
                stock_positive_indices.append(local_idx)
                stock_positive_geometries.append(geom)
            else:
                inflated[local_idx] = candidate
                inflated_already_validated[local_idx] = True

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            stock_inflated = _stock_buffer_many(
                stock_positive_geometries,
                close_delta_mm,
            )
        if len(stock_inflated) != len(stock_positive_indices):
            raise ValueError("stock positive buffer returned an unexpected result count")
        for local_idx, candidate in zip(stock_positive_indices, stock_inflated):
            inflated[local_idx] = candidate

        deflated = [None] * len(active_geoms)
        stock_negative_indices = []
        stock_negative_geometries = []
        for local_idx, candidate in enumerate(inflated):
            inward = None
            if _is_dense_normalization_geometry(candidate, close_delta_mm):
                inward = geos_buffer_fast.try_disconnected_inward_buffer(
                    candidate,
                    negative_settings,
                    _input_already_validated=inflated_already_validated[local_idx],
                )
            if inward is None:
                stock_negative_indices.append(local_idx)
                stock_negative_geometries.append(candidate)
            else:
                deflated[local_idx] = inward

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            stock_deflated = _stock_buffer_many(
                stock_negative_geometries,
                -close_delta_mm,
            )
        if len(stock_deflated) != len(stock_negative_indices):
            raise ValueError("stock negative buffer returned an unexpected result count")
        for local_idx, candidate in zip(stock_negative_indices, stock_deflated):
            deflated[local_idx] = candidate
    except VECTOR_HANDLED_ERRORS:
        cache = {}
        return [
            _normalize_contours_cached(cache, geom, close_delta_mm=close_delta_mm)
            for geom in items
        ]

    for idx, geom, inflated_geom, deflated_geom in zip(
        active_indices,
        active_geoms,
        inflated,
        deflated,
    ):
        try:
            results[idx] = _finish_normalized_contour(geom, inflated_geom, deflated_geom)
        except VECTOR_HANDLED_ERRORS:
            results[idx] = VectorProcessor._normalize_contours(
                geom,
                close_delta_mm=close_delta_mm,
            )
    return results


def _direct_top_level_path_viewbox(root):
    """Return a numeric viewBox tuple for strict generated SVGs."""

    raw = str(root.get("viewBox", "") or "").replace(",", " ").split()
    if len(raw) != 4:
        return None
    try:
        x, y, width, height = (float(value) for value in raw)
    except (TypeError, ValueError):
        return None
    if width <= 0.0 or height <= 0.0:
        return None
    return x, y, width, height


def _is_strict_top_level_path_svg(root):
    """Return True when a generated SVG is safe for the direct path parser."""

    if root is None:
        return False
    if root.get("data-lumina-origin") is not None or root.get("transform") is not None:
        return False
    if _direct_path_visibility_requires_full_svg_parse(root):
        return False

    reference_tags = {
        "defs",
        "clipPath",
        "mask",
        "pattern",
        "linearGradient",
        "radialGradient",
        "symbol",
        "style",
        "use",
    }
    for elem in root.iter():
        if elem is root:
            continue
        tag = _tag_local_name(elem)
        if tag in reference_tags:
            return False
        if tag != "path":
            return False
        if elem.get("transform") is not None:
            return False
        if _direct_path_visibility_requires_full_svg_parse(elem):
            return False

    return all(_tag_local_name(child) == "path" for child in list(root))


def _direct_path_visibility_requires_full_svg_parse(elem):
    """Return True when visibility or opacity semantics exceed the direct parser."""

    opacity_attrs = ("opacity", "fill-opacity", "stroke-opacity")
    for attr in opacity_attrs:
        if elem.get(attr) is not None:
            return True

    display = _normalize_svg_css_token(elem.get("display", ""))
    if display == "none":
        return True
    visibility = _normalize_svg_css_token(elem.get("visibility", ""))
    if visibility in {"hidden", "collapse"}:
        return True

    style = str(elem.get("style", "") or "")
    for declaration in style.split(";"):
        name, sep, value = declaration.partition(":")
        if not sep:
            continue
        prop = name.strip().lower()
        css_value = _normalize_svg_css_token(value)
        if prop in opacity_attrs:
            return True
        if prop == "display" and css_value == "none":
            return True
        if prop == "visibility" and css_value in {"hidden", "collapse"}:
            return True
    return False


def _parse_svg_opacity_scalar(raw_value):
    """Parse an SVG opacity scalar, returning None when it is absent or invalid."""

    if raw_value is None:
        return None
    value = str(raw_value).strip()
    if not value:
        return None
    try:
        if value.endswith("%"):
            parsed = float(value[:-1].strip()) / 100.0
        else:
            parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    return min(max(parsed, 0.0), 1.0)


def _svg_element_opacity(element):
    """Return inherited SVG element opacity as a normalized 0..1 scalar."""

    values = getattr(element, "values", None)
    raw_values = []
    if isinstance(values, dict):
        raw_values.append(values.get("opacity"))
        attrs = values.get("attributes")
        if isinstance(attrs, dict):
            raw_values.append(attrs.get("opacity"))
    raw_values.append(getattr(element, "opacity", None))

    for raw_value in raw_values:
        opacity = _parse_svg_opacity_scalar(raw_value)
        if opacity is not None:
            return opacity
    return 1.0


def _normalize_svg_css_token(raw_value):
    value = str(raw_value or "").strip().lower()
    if value.endswith("!important"):
        value = value[: -len("!important")].strip()
    return value


def _svg_element_hidden_by_visibility(element):
    """Return True when SVG display/visibility semantics hide an element."""

    values = getattr(element, "values", None)
    raw_display_values = []
    raw_visibility_values = []
    raw_style_values = []
    if isinstance(values, dict):
        raw_display_values.append(values.get("display"))
        raw_visibility_values.append(values.get("visibility"))
        raw_style_values.append(values.get("style"))
        attrs = values.get("attributes")
        if isinstance(attrs, dict):
            raw_display_values.append(attrs.get("display"))
            raw_visibility_values.append(attrs.get("visibility"))
            raw_style_values.append(attrs.get("style"))
    raw_display_values.append(getattr(element, "display", None))
    raw_visibility_values.append(getattr(element, "visibility", None))
    raw_style_values.append(getattr(element, "style", None))

    if any(_normalize_svg_css_token(value) == "none" for value in raw_display_values):
        return True
    if any(
        _normalize_svg_css_token(value) in {"hidden", "collapse"}
        for value in raw_visibility_values
    ):
        return True

    for raw_style in raw_style_values:
        style = str(raw_style or "")
        for declaration in style.split(";"):
            name, sep, value = declaration.partition(":")
            if not sep:
                continue
            prop = name.strip().lower()
            css_value = _normalize_svg_css_token(value)
            if prop == "display" and css_value == "none":
                return True
            if prop == "visibility" and css_value in {"hidden", "collapse"}:
                return True
    return False


def _direct_path_fill_rgb(fill_value):
    """Parse a direct path fill color into an RGB tuple."""

    value = str(fill_value or "").strip()
    if not value or value.lower() == "none":
        return None
    try:
        color = Color(value)
        alpha = getattr(color, "alpha", None)
        if alpha is not None and float(alpha) < 0.01:
            return None
        return (int(color.red), int(color.green), int(color.blue))
    except VECTOR_HANDLED_ERRORS:
        return None


def _direct_flatten_segments(segments, tolerance):
    """Flatten path segments for the strict top-level direct SVG parser."""

    coords = []
    for seg in segments:
        if isinstance(seg, Move):
            continue
        if isinstance(seg, (Line, Close)):
            coords.append((seg.start.x, seg.start.y))
        elif isinstance(seg, CubicBezier):
            start_pt = (seg.start.x, seg.start.y)
            if not coords or coords[-1] != start_pt:
                coords.append(start_pt)
            _flatten_cubic(
                seg.start.x,
                seg.start.y,
                seg.control1.x,
                seg.control1.y,
                seg.control2.x,
                seg.control2.y,
                seg.end.x,
                seg.end.y,
                tolerance,
                coords,
                0,
            )
        elif isinstance(seg, QuadraticBezier):
            start_pt = (seg.start.x, seg.start.y)
            if not coords or coords[-1] != start_pt:
                coords.append(start_pt)
            _flatten_quadratic(
                seg.start.x,
                seg.start.y,
                seg.control.x,
                seg.control.y,
                seg.end.x,
                seg.end.y,
                tolerance,
                coords,
                0,
            )
        elif isinstance(seg, Arc):
            start_pt = (seg.start.x, seg.start.y)
            if not coords or coords[-1] != start_pt:
                coords.append(start_pt)
            coords.extend(_sample_arc_segment_points(seg, sample_count=10))
        else:
            coords.append((seg.start.x, seg.start.y))
            try:
                for tv in np.linspace(0.1, 1.0, 10):
                    pt = seg.point(tv)
                    coords.append((pt.x, pt.y))
            except VECTOR_HANDLED_ERRORS:
                coords.append((seg.end.x, seg.end.y))
    return coords


def _direct_flatten_segments_fallback(path_obj, tolerance):
    """Fallback point sampling for paths that cannot expose segments."""

    try:
        path_len = path_obj.length()
    except VECTOR_HANDLED_ERRORS:
        return []
    if path_len == 0:
        return []
    count = max(10, min(int(path_len / max(tolerance, 0.01)), 8000))
    points = [path_obj.point(t) for t in np.linspace(0, 1, count)]
    return [(point.x, point.y) for point in points]


def _direct_sample_segments_coords(path_obj, segments, tolerance):
    """Sample path coordinates with scalar-compatible endpoint handling."""

    if segments and len(segments) > 1:
        coords = _direct_flatten_segments(segments, tolerance)
    else:
        coords = _direct_flatten_segments_fallback(path_obj, tolerance)

    if segments:
        try:
            last_end = segments[-1].end
            last_pt = (last_end.x, last_end.y)
            if coords and coords[-1] != last_pt:
                coords.append(last_pt)
        except VECTOR_HANDLED_ERRORS:
            pass
    return coords


def _direct_signed_ring_area(coords):
    """Return signed ring area for direct parser subpath fill handling."""

    if len(coords) < 3:
        return 0.0
    area = 0.0
    for (x1, y1), (x2, y2) in zip(coords, coords[1:] + coords[:1]):
        area += (float(x1) * float(y2)) - (float(x2) * float(y1))
    return area * 0.5


def _direct_polygon_from_coords(coords):
    """Build a polygonal geometry from direct parser coordinates."""

    if len(coords) < 3:
        return None
    poly = Polygon(coords)
    if not poly.is_valid:
        poly = make_valid(poly)
    poly = VectorProcessor._extract_polygonal_geometry(poly)
    if poly is not None and not poly.is_empty:
        return poly
    return None


def _direct_single_subpath_item(path_obj, tolerance):
    """Sample one strict top-level path when it contains a single subpath."""

    try:
        segments = list(path_obj.segments())
    except VECTOR_HANDLED_ERRORS:
        return None
    if not segments:
        return None

    move_count = 0
    for seg in segments:
        if isinstance(seg, Move):
            move_count += 1
            if move_count > 1:
                return None

    coords = _direct_sample_segments_coords(path_obj, segments, tolerance)
    poly = _direct_polygon_from_coords(coords)
    if poly is None:
        return None
    return {"poly": poly, "signed_area": _direct_signed_ring_area(coords)}


def _direct_subpath_items_for_path(path_obj, tolerance):
    """Return sampled subpath items for a direct parser path."""

    single = _direct_single_subpath_item(path_obj, tolerance)
    if single is not None:
        return [single]

    try:
        subpaths = list(path_obj.as_subpaths())
    except VECTOR_HANDLED_ERRORS:
        subpaths = []

    items = []
    for subpath in subpaths:
        try:
            sub_path = subpath if isinstance(subpath, Path) else Path(subpath)
            segments = list(sub_path.segments())
            coords = _direct_sample_segments_coords(sub_path, segments, tolerance)
            poly = _direct_polygon_from_coords(coords)
        except VECTOR_HANDLED_ERRORS:
            continue
        if poly is None:
            continue
        items.append({"poly": poly, "signed_area": _direct_signed_ring_area(coords)})
    return items


def _try_parse_strict_top_level_path_svg(processor, svg_path, target_width_mm):
    """Parse simple generated SVGs without constructing a full SVG document."""

    try:
        with open(svg_path, "rb") as handle:
            payload = handle.read()
        if _SVG_DIRECT_UNSUPPORTED_OPEN_TAG_RE.search(payload):
            return None
        filtered_payload = _fast_filtered_gap_filler_svg_payload(payload)
        if filtered_payload is not None:
            payload = filtered_payload
        root = ET.fromstring(payload)
    except VECTOR_HANDLED_ERRORS:
        return None
    if not _is_strict_top_level_path_svg(root):
        return None
    svg_viewport_bounds = _direct_top_level_path_viewbox(root)
    if svg_viewport_bounds is None:
        return None

    tolerance = processor.sampling_precision / max(target_width_mm / 100.0, 0.01)
    raw_shapes = []
    needs_normalize_key = "_needs_contour_normalize"
    skipped_polygon_count = 0

    for elem in list(root):
        rgb = _direct_path_fill_rgb(elem.get("fill"))
        if rgb is None:
            continue

        stroke_value = str(elem.get("stroke", "") or "").strip().lower()
        if stroke_value and stroke_value != "none":
            return None

        path_data = elem.get("d")
        if not path_data:
            continue
        try:
            path_obj = parse_svg_path(
                path_data, tolerance * _SVG_ARC_APPROXIMATION_BUDGET_RATIO,
            )
        except VECTOR_HANDLED_ERRORS:
            return None

        raw_fill_rule = elem.get("fill-rule")
        if raw_fill_rule is None:
            return None
        fill_rule = str(raw_fill_rule or "nonzero").strip().lower()
        if fill_rule not in ("nonzero", "evenodd"):
            fill_rule = "nonzero"

        subpath_items = _direct_subpath_items_for_path(path_obj, tolerance)
        subpath_polys = [item["poly"] for item in subpath_items]
        if len(subpath_items) == 1:
            result_poly = subpath_items[0]["poly"]
        elif len(subpath_polys) > 1 and fill_rule == "evenodd":
            result_poly = _combine_evenodd_polygons(subpath_polys)
            if result_poly is not None and not result_poly.is_empty and not result_poly.is_valid:
                result_poly = make_valid(result_poly)
        elif len(subpath_polys) > 1:
            return None
        else:
            result_poly = None

        if result_poly is None or result_poly.is_empty:
            skipped_polygon_count += 1
            continue

        raw_shapes.append(
            {
                "poly": result_poly,
                "color": rgb,
                "source_kind": "fill",
                "same_color_stroke": False,
                "same_color_stroke_double_buffer": False,
                "stroke_width_svg": 0.0,
                needs_normalize_key: True,
            }
        )

    if not raw_shapes:
        return None

    pending_positions = []
    pending_geometries = []
    for idx, item in enumerate(raw_shapes):
        if item.get(needs_normalize_key) is True:
            pending_positions.append(idx)
            pending_geometries.append(item["poly"])

    if pending_geometries:
        normalized_geometries = _normalize_contours_many(pending_geometries)
        dropped_positions = set()
        for idx, normalized in zip(pending_positions, normalized_geometries):
            if normalized is None or normalized.is_empty:
                dropped_positions.add(idx)
                skipped_polygon_count += 1
                continue
            raw_shapes[idx]["poly"] = normalized
            raw_shapes[idx]["geometry_normalized"] = True

        normalized_shapes = []
        for idx, item in enumerate(raw_shapes):
            if idx in dropped_positions:
                continue
            if needs_normalize_key in item:
                item = dict(item)
                item.pop(needs_normalize_key, None)
            normalized_shapes.append(item)
        raw_shapes = normalized_shapes

    if not raw_shapes:
        return None

    min_xs, min_ys, max_xs, max_ys = [], [], [], []
    for item in raw_shapes:
        bx0, by0, bx1, by1 = item["poly"].bounds
        min_xs.append(bx0)
        min_ys.append(by0)
        max_xs.append(bx1)
        max_ys.append(by1)

    gx0, gy0 = min(min_xs), min(min_ys)
    gx1, gy1 = max(max_xs), max(max_ys)
    vb_x, vb_y, vb_w, vb_h = svg_viewport_bounds
    gx0 = min(gx0, vb_x)
    gy0 = min(gy0, vb_y)
    gx1 = max(gx1, vb_x + vb_w)
    gy1 = max(gy1, vb_y + vb_h)

    real_w = gx1 - gx0
    real_h = gy1 - gy0
    if real_w == 0:
        raise ValueError("Invalid geometry width (0)")

    scale_factor = target_width_mm / real_w
    min_area_svg = max(0.0, (processor.sampling_precision**2) / max(scale_factor**2, 1e-12) * 0.25)
    simplify_tol_svg = max(0.0, (processor.sampling_precision / max(scale_factor, 1e-9)) * 0.5)

    final_shapes = []
    for item in raw_shapes:
        shifted = affinity.translate(item["poly"], xoff=-gx0, yoff=-gy0)
        geometry_normalized = bool(item.get("geometry_normalized"))
        if simplify_tol_svg > 0.0:
            before_simplify = shifted
            try:
                shifted = shifted.simplify(simplify_tol_svg, preserve_topology=True)
                if geometry_normalized and not shifted.equals_exact(before_simplify, tolerance=0.0):
                    geometry_normalized = False
            except VECTOR_HANDLED_ERRORS:
                geometry_normalized = False

        if not shifted.is_valid:
            shifted = make_valid(shifted)
            geometry_normalized = False

        if shifted.is_empty or shifted.area <= min_area_svg:
            continue

        final_item = {"poly": shifted, "color": item["color"]}
        for key in (
            "source_kind",
            "same_color_stroke",
            "same_color_stroke_double_buffer",
            "stroke_width_svg",
        ):
            if key in item:
                final_item[key] = item[key]
        if geometry_normalized:
            final_item["geometry_normalized"] = True
        final_shapes.append(final_item)

    if not final_shapes:
        return None

    processor.parse_warnings = (
        [f"{skipped_polygon_count} elements produced invalid geometry and were skipped"]
        if skipped_polygon_count > 0
        else []
    )
    processor._last_image_vectorizer_bounds = None
    return final_shapes, scale_factor, (gx0, gy0, real_w, real_h)


# Lazy import to avoid circular dependency at module load time
_LuminaImageProcessor = None
_VECTOR_PARSE_CLIP_CACHE = {}
_VECTOR_PARSE_CLIP_CACHE_MAX = 8
_VECTOR_PARSE_CLIP_ARTIFACT_SCHEMA = "lumina_vector_parse_clip_cache_v6"


def _vector_parse_clip_cache_key(
    svg_path,
    *,
    target_width_mm,
    sampling_precision,
    expand_stroke_to_fill,
    gradient_color_bands,
):
    """Build the parse/clip cache key shared by memory and artifact caches."""

    svg_abs = os.path.abspath(svg_path)
    # External overwrites and restored backups can preserve both mtime and size.
    with open(svg_abs, "rb") as source:
        svg_source = source.read().hex()
    try:
        gradient_key = None if gradient_color_bands is None else int(gradient_color_bands)
    except (TypeError, ValueError):
        gradient_key = str(gradient_color_bands)
    return (
        svg_abs,
        round(float(target_width_mm), 4),
        round(float(sampling_precision), 4),
        bool(expand_stroke_to_fill),
        gradient_key,
        svg_source,
        native_svg_adapter.native_build_identity(),
        SVG_COORDINATE_CONTRACT_VERSION,
        *native_svg_adapter.native_runtime_identity(),
    )


def _serialize_vector_parse_clip_cache(cache_key, cache_entry):
    """Serialize a verified parse/clip cache entry for session-bound reuse."""

    provenance = _vector_parse_clip_cache_provenance(cache_key)
    return pickle.dumps(
        {
            "schema": _VECTOR_PARSE_CLIP_ARTIFACT_SCHEMA,
            "cache_key": tuple(cache_key),
            "provenance": provenance,
            "entry": _copy_vector_parse_clip_cache_entry(cache_entry),
        },
        protocol=pickle.HIGHEST_PROTOCOL,
    )


def _vector_parse_clip_cache_provenance(cache_key):
    """Return the exact serialized parse/clip identity. 返回完整解析缓存标识。"""

    canonical_key = json.dumps(
        list(cache_key),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    return canonical_key


def _copy_vector_parse_clip_cache_entry(cache_entry):
    """Return a mutation-isolated shallow copy of a parse/clip cache entry."""

    copied = {
        "shape_data": [
            dict(item)
            for item in (cache_entry.get("shape_data") or [])
        ],
        "clipped_shapes": [
            dict(item)
            for item in (cache_entry.get("clipped_shapes") or [])
        ],
        "silhouette": cache_entry.get("silhouette"),
        "image_vectorizer_bounds": cache_entry.get("image_vectorizer_bounds"),
        "scale_factor": cache_entry.get("scale_factor"),
        "bbox": cache_entry.get("bbox"),
        "parse_warnings": list(cache_entry.get("parse_warnings") or []),
        "geometry_stage_timings": dict(
            cache_entry.get("geometry_stage_timings") or {}
        ),
        "svg_coordinate_domain": cache_entry.get("svg_coordinate_domain"),
    }
    domain = copied["svg_coordinate_domain"]
    if isinstance(domain, SvgCoordinateDomain):
        copied["shape_data"] = domain.restore_records(copied["shape_data"], "poly")
        copied["clipped_shapes"] = domain.restore_records(copied["clipped_shapes"])
        copied["silhouette"] = domain.restore_precision(copied["silhouette"])
    return copied


def _read_vector_parse_clip_cache_artifact(path):
    """Read and structurally validate one server-owned parse/clip artifact."""

    if not path:
        return None
    try:
        with open(path, "rb") as handle:
            payload = pickle.load(handle)
    except (*VECTOR_HANDLED_ERRORS, pickle.PickleError, EOFError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema") != _VECTOR_PARSE_CLIP_ARTIFACT_SCHEMA:
        return None
    cache_key = tuple(payload.get("cache_key") or ())
    if not cache_key:
        return None
    try:
        actual_provenance = _vector_parse_clip_cache_provenance(cache_key)
    except (TypeError, ValueError):
        return None
    if payload.get("provenance") != actual_provenance:
        return None
    if len(cache_key) >= 11 and cache_key[-3] in {"native", "legacy"}:
        runtime_identity = (
            native_svg_adapter.native_build_identity(),
            SVG_COORDINATE_CONTRACT_VERSION,
            *native_svg_adapter.native_runtime_identity(),
        )
        if cache_key[-5:] != runtime_identity:
            return None
    entry = payload.get("entry")
    if not isinstance(entry, dict):
        return None
    required = {
        "shape_data",
        "clipped_shapes",
        "silhouette",
        "scale_factor",
        "bbox",
    }
    if not required.issubset(entry):
        return None
    return payload


def _load_vector_parse_clip_cache_artifact(path, expected_cache_key):
    """Load a parse/clip artifact only when its key exactly matches."""

    payload = _read_vector_parse_clip_cache_artifact(path)
    if payload is None:
        return None
    if tuple(payload["cache_key"]) != tuple(expected_cache_key):
        return None
    return _copy_vector_parse_clip_cache_entry(payload["entry"])


def _load_vector_parse_clip_cache_artifact_by_provenance(
    path,
    expected_provenance,
):
    """Load a parse/clip artifact matching server-held provenance."""

    if not isinstance(expected_provenance, str) or not expected_provenance:
        return None
    payload = _read_vector_parse_clip_cache_artifact(path)
    if payload is None or payload.get("provenance") != expected_provenance:
        return None
    return _copy_vector_parse_clip_cache_entry(payload["entry"])


def _get_image_processor_class():
    global _LuminaImageProcessor
    if _LuminaImageProcessor is None:
        from core.image_processing import LuminaImageProcessor

        _LuminaImageProcessor = LuminaImageProcessor
    return _LuminaImageProcessor


@dataclass
class VectorAnalysis:
    """Intermediate result of SVG parsing, clipping, and color matching.
    SVG 解析、裁剪、配色的中间结果 — 预览与 3D 构建共享。

    Produced by ``VectorProcessor.analyze_svg`` and consumed by both
    ``build_mesh`` (3D extrusion) and ``render_preview`` (2D raster).
    """

    shape_data: list
    clipped_shapes: list
    matched_shapes: list
    silhouette: object  # Polygon | MultiPolygon | None
    scale_factor: float
    bbox: tuple  # (gx0, gy0, real_w, real_h) in SVG user units
    color_conf: dict
    slot_names: list
    num_channels: int
    num_layers: int
    preview_colors: dict
    stage_timings: dict = field(default_factory=dict)
    image_vectorizer_bounds: object | None = None
    structure_plan: VectorStructurePlan | None = None
    matched_rgb_override_metrics: dict = field(default_factory=dict)
    material_dynamic_layer_info: dict | None = None
    material_solver_info: dict | None = None
    coordinate_domain: LayeredCoordinateDomain | None = None
    svg_coordinate_domain: SvgCoordinateDomain | None = None

    def __setstate__(self, state: dict) -> None:
        """Restore explicit topology precision after a cache/spawn round trip.

        在缓存或工作进程往返后恢复显式拓扑精度模型。
        """
        self.__dict__.update(state)
        domain = state.get("svg_coordinate_domain")
        if isinstance(domain, SvgCoordinateDomain):
            self.shape_data = domain.restore_records(self.shape_data, "poly")
            self.clipped_shapes = domain.restore_records(self.clipped_shapes)
            self.matched_shapes = domain.restore_records(self.matched_shapes)
            self.silhouette = domain.restore_precision(self.silhouette)


def _physical_backing_geometry(analysis: object) -> object | None:
    """Return visible geometry without coordinate-only canvas bounds.
    返回可打印的可见几何，不包含仅用于坐标定位的完整画布边界。
    """

    silhouette = getattr(analysis, "silhouette", None)
    if silhouette is not None and not getattr(silhouette, "is_empty", True):
        return silhouette

    clipped_geometries = [
        item.get("geometry")
        for item in (getattr(analysis, "clipped_shapes", None) or [])
        if isinstance(item, dict)
        and item.get("geometry") is not None
        and not item.get("geometry").is_empty
    ]
    return unary_union(clipped_geometries) if clipped_geometries else None


def _signed_dtype_for_int_range(min_value: int, max_value: int) -> np.dtype:
    """Return the smallest signed dtype that can hold the integer range."""

    for dtype in (np.int8, np.int16, np.int32, np.int64):
        info = np.iinfo(dtype)
        if min_value >= info.min and max_value <= info.max:
            return np.dtype(dtype)
    return np.dtype(np.int64)


def _material_matrix_dtype_for_vector_analysis(analysis: "VectorAnalysis") -> np.dtype:
    """Return the compact material-matrix dtype needed by an analysis."""

    dynamic_info = getattr(analysis, "material_dynamic_layer_info", None)
    if isinstance(dynamic_info, dict) and bool(dynamic_info.get("enabled")):
        # Dynamic material matrices are a P03 authority artifact. Keep their
        # explicit int32 contract even when the selected material indices
        # would fit in a smaller signed type.
        return np.dtype(np.int32)

    min_value = -1
    max_value = max(0, int(getattr(analysis, "num_channels", 0) or 0) - 1)
    num_layers = max(0, int(getattr(analysis, "num_layers", 0) or 0))
    for shape in getattr(analysis, "matched_shapes", []) or []:
        for raw_value in (shape.get("recipe") or [])[:num_layers]:
            value = int(raw_value)
            min_value = min(min_value, value)
            max_value = max(max_value, value)
    return _signed_dtype_for_int_range(min_value, max_value)


def apply_recipe_overrides_to_analysis(
    analysis: "VectorAnalysis",
    *,
    recipe_overrides,
    region_masks,
    target_layers=None,
    base_channel_idx: int = 0,
    pixels_per_mm: float = 10.0,
    max_width_px: int = 1600,
    min_overlap_ratio: float = 0.5,
    img_processor=None,
    source_grid_shape: tuple[int, int] | None = None,
) -> None:
    """Apply user-declared per-region recipe overrides to a ``VectorAnalysis``.
    将用户通过自定义配方对话框声明的 per-region 覆盖回写到 ``VectorAnalysis``。

    The raster pipeline mutates ``preview_cache["material_matrix"]`` inside
    ``/convert/apply-recipe-override`` so the 2D preview + segmented GLB echo
    the user's picks and any extra layers they appended. The SVG-native
    branch used to skip this entirely — it re-ran ``analyze_svg`` and built
    the 3MF from the LUT's default match, so "custom recipe + added layers"
    applied on a vector input never made it into the generated 3MF even
    though the preview showed them. This helper mirrors
    ``s03_color_replacement`` for the vector branch:

    - Rasterises each ``analysis.matched_shapes`` entry onto the same grid
      used by :meth:`VectorProcessor.build_preview_cache` so the preview-time
      region masks line up pixel-for-pixel.
    - Resolves overlapping edits in chronological order, then picks the
      dominant remaining region for each connected polygon component.
      Compound SVG paths are split only when their disconnected components
      resolve to different recipes, preserving source metadata.
    - Translates each override recipe into the vector internal order
      (``Top2Bottom`` — recipe[0] is the visible face at z=0) and pads it
      up to the effective layer count with the base backing channel.
    - Non-overridden shapes keep their LUT recipe but are also padded so
      the extended layers stay continuous with the backing slab.
    - Virtual (non-native) materials declared per-region are deduped into a
      global registry and appended to ``slot_names`` / ``preview_colors``
      so ``build_mesh`` can emit one geometry per extra material.

    Args:
        analysis: Analysis result from ``analyze_svg``. Mutated in place.
        recipe_overrides: Sequence of ``{"region_id", "recipe", "layer_order",
            "virtual_materials"?}`` dicts coming from the generate request.
        region_masks: Mapping of ``region_id`` to a boolean mask that was
            computed at preview time and lives on the preview grid.
        target_layers: Requested ``color_layers`` from the generate request;
            used to extend ``analysis.num_layers`` when the user appended
            layers. ``None`` falls back to the max length found in
            ``recipe_overrides``.
        base_channel_idx: LUT base channel id used when padding non-override
            recipes; typically 0 (white / backing).
        pixels_per_mm: Preview-grid rasterisation density. Must match the
            value passed to :meth:`VectorProcessor.build_preview_cache`.
        max_width_px: Preview-grid width cap. Must match
            :meth:`VectorProcessor.build_preview_cache`.
        min_overlap_ratio: Minimum ratio of a shape's pixels that must fall
            inside a region mask before that region "claims" the shape.
            0.5 matches the "majority wins" rule used by the raster path.
        source_grid_shape: Optional preview edit-grid ``(height, width)``.
            When provided, SVG coordinates map directly to this immutable
            grid instead of being re-rasterised at the new physical size.
            （可选的预览编辑网格；提供后直接把 SVG 坐标映射到该网格，
            不按变化后的物理尺寸重新栅格化。）
    """
    from core.recipe_order import convert_recipe_between_orders, pad_recipe_to_layer_count
    from core.pipeline.pipeline_utils import _hex_to_rgb_tuple

    if not recipe_overrides or not region_masks:
        return

    # --- Reproduce build_preview_cache grid so region masks line up exactly ---
    real_w = float(analysis.bbox[2])
    real_h = float(analysis.bbox[3])
    sf = float(analysis.scale_factor)
    w_mm = real_w * sf
    h_mm = real_h * sf
    if w_mm <= 0 or h_mm <= 0:
        return
    if source_grid_shape is not None:
        try:
            h_px, w_px = (
                int(source_grid_shape[0]),
                int(source_grid_shape[1]),
            )
        except (TypeError, ValueError, IndexError, OverflowError) as exc:
            raise ValueError("source recipe grid must contain two dimensions") from exc
        if h_px <= 0 or w_px <= 0:
            raise ValueError("source recipe grid dimensions must be positive")
        # Geometry remains in source SVG coordinates. Mapping those coordinates
        # directly to the edit grid preserves smooth paths across physical-size
        # changes and avoids rasterising the newly scaled model first.
        coord_scale: float | tuple[float, float] = (
            w_px / real_w,
            h_px / real_h,
        )
    else:
        ppm = float(pixels_per_mm)
        w_px = max(1, int(round(w_mm * ppm)))
        h_px = max(1, int(round(h_mm * ppm)))
        if w_px > max_width_px:
            ratio = max_width_px / w_px
            w_px = max_width_px
            h_px = max(1, int(round(h_px * ratio)))
            ppm = w_px / w_mm
        coord_scale = sf * ppm

    # --- Normalise region masks to the preview grid ---
    normalised_masks: dict[str, np.ndarray] = {}
    for rid, mask in (region_masks or {}).items():
        arr = np.asarray(mask, dtype=bool)
        if arr.ndim != 2 or arr.shape != (h_px, w_px):
            error_message = (
                f"Region mask {rid} shape {arr.shape} does not match "
                f"preview grid {(h_px, w_px)}"
            )
            _log.warning(
                "Region mask does not match preview grid; skipped",
                extra={
                    "event": "vector_recipe_region_mask_skipped",
                    "error_type": "ValueError",
                    "error_message": error_message,
                    "region_id": str(rid),
                    "mask_shape": list(arr.shape),
                    "expected_shape": [int(h_px), int(w_px)],
                },
            )
            continue
        normalised_masks[str(rid)] = arr

    if not normalised_masks:
        _log.warning(
            "No region masks matched preview grid; recipe overrides ignored",
            extra={
                "event": "vector_recipe_region_masks_missing",
                "error_type": "ValueError",
                "error_message": "No recipe override region masks matched the preview grid",
                "region_count": len(region_masks or {}),
                "expected_shape": [int(h_px), int(w_px)],
            },
        )
        return

    # --- Build a global virtual-material registry (dedupe by name+hex) ---
    lut_palette_length = int(analysis.num_channels)
    from core.recipe_virtual_materials import build_virtual_material_registry

    virtual_registry, per_region_virtual_maps = build_virtual_material_registry(
        recipe_overrides, lut_palette_length,
    )

    # --- Compute effective target layer count ---
    recipe_max_len = max(
        (len(item.get("recipe", [])) for item in recipe_overrides if isinstance(item, dict)),
        default=0,
    )
    effective_target = max(int(analysis.num_layers), recipe_max_len)
    if target_layers is not None:
        try:
            effective_target = max(effective_target, int(target_layers))
        except (TypeError, ValueError):
            pass
    effective_target = max(1, effective_target)

    # --- Extend slot_names / preview_colors / color_conf with virtuals ---
    if virtual_registry:
        new_slot_names = list(analysis.slot_names)
        new_preview_colors = dict(analysis.preview_colors)
        new_color_conf = dict(analysis.color_conf)
        conf_preview = dict(new_color_conf.get("preview") or {})
        conf_slots = list(new_color_conf.get("slots") or [])
        new_color_conf["preview"] = conf_preview
        new_color_conf["slots"] = conf_slots
        for offset, material in enumerate(virtual_registry):
            cache_index = lut_palette_length + offset
            try:
                r, g, b = _hex_to_rgb_tuple(material["hex"])
            except (ValueError, TypeError, KeyError):
                continue
            rgba = [int(r), int(g), int(b), 255]
            name = str(material.get("name") or f"Virtual_{offset}")
            while len(new_slot_names) < cache_index:
                new_slot_names.append(f"Slot_{len(new_slot_names)}")
            if len(new_slot_names) == cache_index:
                new_slot_names.append(name)
            else:
                new_slot_names[cache_index] = name
            while len(conf_slots) < cache_index:
                conf_slots.append(f"Slot_{len(conf_slots)}")
            if len(conf_slots) == cache_index:
                conf_slots.append(name)
            else:
                conf_slots[cache_index] = name
            new_preview_colors[cache_index] = rgba
            conf_preview[cache_index] = rgba
        analysis.slot_names = new_slot_names
        analysis.preview_colors = new_preview_colors
        analysis.color_conf = new_color_conf
        analysis.num_channels = max(
            int(analysis.num_channels),
            lut_palette_length + len(virtual_registry),
        )

    # --- Rasterise every shape onto the preview grid ---
    def _iter_polygon_components(geom):
        if geom is None or geom.is_empty:
            return []
        if geom.geom_type == "Polygon":
            return [geom]
        if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
            components = []
            for child in geom.geoms:
                components.extend(_iter_polygon_components(child))
            return components
        return []

    def _coords_to_pts(coords):
        if isinstance(coord_scale, tuple):
            scale_x, scale_y = coord_scale
        else:
            scale_x = scale_y = coord_scale
        pts = np.column_stack(
            [
                coords[:, 0] * scale_x,
                coords[:, 1] * scale_y,
            ]
        ).astype(np.int32)
        if len(pts) < 3:
            return None
        return pts

    def _shape_mask(geom):
        region = np.zeros((h_px, w_px), dtype=np.uint8)
        painted = False
        for poly in _iter_polygon_components(geom):
            if poly.is_empty:
                continue
            ext_pts = _coords_to_pts(np.array(poly.exterior.coords))
            if ext_pts is None:
                continue
            cv2.fillPoly(region, [ext_pts], 255)
            painted = True
            for interior in poly.interiors:
                hole_pts = _coords_to_pts(np.array(interior.coords))
                if hole_pts is not None:
                    cv2.fillPoly(region, [hole_pts], 0)
        if not painted:
            return None
        return region.astype(bool)

    # --- Pick the dominant region for every connected component ---
    override_by_region: dict[str, dict] = {}
    for item in recipe_overrides:
        if not isinstance(item, dict):
            continue
        rid = str(item.get("region_id", "")).strip()
        if rid:
            # Reusing an earlier selection ID is still a new edit. Keep the
            # order of each region's last occurrence, not its first insertion.
            override_by_region.pop(rid, None)
            override_by_region[rid] = item

    # The raster edit path applies later recipes over earlier pixels. Resolve
    # that ownership once here too: independently scoring overlapping masks
    # lets an old selection reclaim pixels after the user selects them again.
    # Keep the saved masks immutable; only this local label grid is rewritten.
    pixel_owners = np.zeros((h_px, w_px), dtype=np.int32)
    ordered_overrides: list[dict] = []
    for rid, override in override_by_region.items():
        region_mask = normalised_masks.get(rid)
        if region_mask is None:
            continue
        ordered_overrides.append(override)
        pixel_owners[region_mask] = len(ordered_overrides)

    def _select_override(geometry) -> dict | None:
        mask = _shape_mask(geometry)
        if mask is None:
            return None
        shape_px = int(mask.sum())
        if shape_px == 0:
            return None
        overlaps = np.bincount(
            pixel_owners[mask], minlength=len(ordered_overrides) + 1,
        )[1:]
        if not overlaps.size or not overlaps.any():
            return None
        # Equal coverage favors the most recent edit, independent of how the
        # mask mapping was serialized or restored from an editor snapshot.
        best_index = len(overlaps) - 1 - int(np.argmax(overlaps[::-1]))
        best_overlap = int(overlaps[best_index])
        if best_overlap / shape_px < min_overlap_ratio:
            return None
        return ordered_overrides[best_index]

    def _resolve_recipe(shape: dict, override: dict | None) -> tuple[list[int], bool]:
        if override is not None:
            raw_recipe = [int(v) for v in override.get("recipe", [])]
            rid = str(override.get("region_id", "")).strip()
            local_map = per_region_virtual_maps.get(rid) or {}
            if local_map:
                raw_recipe = [int(local_map.get(int(v), int(v))) for v in raw_recipe]
            source_order = str(override.get("layer_order") or "Top2Bottom")
            # Vector runs recipe[0] at z=0 (the visible face for face-down
            # prints), i.e. Top2Bottom by convention. Normalise user recipes
            # into that order before padding.
            # 矢量管道约定 recipe[0] 在 z=0（面朝下打印时的可视面），即
            # Top2Bottom；用户 recipe 先归一到该序再补齐。
            normalised = convert_recipe_between_orders(raw_recipe, source_order, "Top2Bottom")
            padded = pad_recipe_to_layer_count(
                normalised,
                effective_target,
                int(base_channel_idx),
                "Top2Bottom",
            )
            return padded, True

        existing = [int(v) for v in shape.get("recipe") or []]
        if len(existing) < effective_target:
            existing = pad_recipe_to_layer_count(
                existing,
                effective_target,
                int(base_channel_idx),
                "Top2Bottom",
            )
        elif len(existing) > effective_target:
            existing = existing[:effective_target]
        return existing, False

    # --- Apply recipes per connected component and split only on divergence ---
    overridden_count = 0
    projected_shapes: list[dict] = []
    for shape in analysis.matched_shapes:
        geometry = shape.get("geometry")
        components = _iter_polygon_components(geometry)
        if len(components) <= 1:
            override = _select_override(components[0] if components else geometry)
            shape["recipe"], was_overridden = _resolve_recipe(shape, override)
            overridden_count += int(was_overridden)
            projected_shapes.append(shape)
            continue

        component_records: list[dict] = []
        for component in components:
            component_record = dict(shape)
            component_record["geometry"] = component
            override = _select_override(component)
            component_record["recipe"], was_overridden = _resolve_recipe(
                component_record,
                override,
            )
            overridden_count += int(was_overridden)
            component_records.append(component_record)

        component_recipes = {
            tuple(int(value) for value in record.get("recipe") or [])
            for record in component_records
        }
        if len(component_recipes) <= 1:
            shape["recipe"] = list(component_records[0].get("recipe") or [])
            projected_shapes.append(shape)
        else:
            projected_shapes.extend(component_records)

    analysis.matched_shapes = projected_shapes

    analysis.num_layers = int(effective_target)

    new_preview_colors = dict(analysis.preview_colors)
    new_slot_names = list(analysis.slot_names)
    changed_preview = False
    for shape in analysis.matched_shapes:
        recipe = shape.get("recipe") or []
        if not recipe:
            continue
        top_ch = int(recipe[0])
        if top_ch in new_preview_colors:
            continue
        if top_ch < lut_palette_length and img_processor is not None and hasattr(img_processor, "lut_rgb"):
            try:
                lut_color = img_processor.lut_rgb[top_ch]
                new_preview_colors[top_ch] = [int(c) for c in lut_color] + [255]
                changed_preview = True
            except (IndexError, TypeError, ValueError):
                pass
        elif top_ch >= lut_palette_length:
            vidx = top_ch - lut_palette_length
            if 0 <= vidx < len(virtual_registry):
                try:
                    r, g, b = _hex_to_rgb_tuple(virtual_registry[vidx]["hex"])
                    new_preview_colors[top_ch] = [int(r), int(g), int(b), 255]
                    changed_preview = True
                except (ValueError, TypeError, KeyError):
                    pass
        while len(new_slot_names) <= top_ch:
            new_slot_names.append("Slot_" + str(len(new_slot_names)))
    if changed_preview:
        analysis.preview_colors = new_preview_colors
        analysis.slot_names = new_slot_names

    _log.debug(
        "Applied recipe overrides: shapes=%s, overridden=%s, regions=%s, "
        "virtuals=%s, target_layers=%s",
        len(analysis.matched_shapes),
        overridden_count,
        len(normalised_masks),
        len(virtual_registry),
        effective_target,
    )


def _iter_raster_polygon_components(geom) -> list:
    """Return polygon leaves in stable geometry order.

    按原始 geometry 顺序返回所有 Polygon 叶节点。
    """
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        components = []
        for child in geom.geoms:
            components.extend(_iter_raster_polygon_components(child))
        return components
    return []


def _coords_to_raster_points(
    coords: np.ndarray,
    *,
    coord_scale: float | tuple[float, float],
) -> np.ndarray | None:
    """Convert geometry coordinates exactly like the legacy raster path."""
    if isinstance(coord_scale, tuple):
        scale_x, scale_y = coord_scale
    else:
        scale_x = scale_y = coord_scale
    pts = np.column_stack(
        [
            coords[:, 0] * scale_x,
            coords[:, 1] * scale_y,
        ]
    ).astype(np.int32)
    if len(pts) < 3:
        return None
    return pts


def _geometry_raster_contours(
    geom,
    *,
    coord_scale: float | tuple[float, float],
) -> list[tuple[np.ndarray, list[np.ndarray]]]:
    """Build integer exterior/hole contours once for OpenCV rasterization."""
    contours: list[tuple[np.ndarray, list[np.ndarray]]] = []
    for poly in _iter_raster_polygon_components(geom):
        if poly.is_empty:
            continue
        exterior = _coords_to_raster_points(
            np.asarray(poly.exterior.coords),
            coord_scale=coord_scale,
        )
        if exterior is None:
            continue
        holes: list[np.ndarray] = []
        for interior in poly.interiors:
            hole = _coords_to_raster_points(
                np.asarray(interior.coords),
                coord_scale=coord_scale,
            )
            if hole is not None:
                holes.append(hole)
        contours.append((exterior, holes))
    return contours


def _paint_raster_contours(
    contours: list[tuple[np.ndarray, list[np.ndarray]]],
    *,
    canvas_shape: tuple[int, int],
    origin_xy: tuple[int, int] = (0, 0),
) -> np.ndarray | None:
    """Paint contours with the legacy exterior-then-holes OpenCV sequence."""
    if not contours:
        return None
    height, width = (int(canvas_shape[0]), int(canvas_shape[1]))
    region = np.zeros((height, width), dtype=np.uint8)
    origin = np.asarray(origin_xy, dtype=np.int32)
    for exterior, holes in contours:
        cv2.fillPoly(region, [exterior - origin], 255)
        for hole in holes:
            cv2.fillPoly(region, [hole - origin], 0)
    return region.astype(bool)


def _rasterize_geometry_roi_mask(
    geom,
    *,
    canvas_shape: tuple[int, int],
    coord_scale: float | tuple[float, float],
) -> tuple[slice, slice, np.ndarray] | None:
    """Rasterize inside a conservative pixel ROI.

    The integer contours are identical to the legacy path. The one-pixel
    padding is deliberately conservative so OpenCV edge coverage remains
    unchanged after translating contours into local coordinates.

    整数轮廓与旧实现完全一致，只把画布裁到带一像素余量的包围盒。
    """
    contours = _geometry_raster_contours(
        geom,
        coord_scale=coord_scale,
    )
    if not contours:
        return None

    height, width = (int(canvas_shape[0]), int(canvas_shape[1]))
    exterior_points = [exterior for exterior, _holes in contours]
    min_x = min(int(points[:, 0].min()) for points in exterior_points)
    min_y = min(int(points[:, 1].min()) for points in exterior_points)
    max_x = max(int(points[:, 0].max()) for points in exterior_points)
    max_y = max(int(points[:, 1].max()) for points in exterior_points)

    x_start = max(0, min_x - 1)
    y_start = max(0, min_y - 1)
    x_stop = min(width, max_x + 2)
    y_stop = min(height, max_y + 2)
    if x_start >= x_stop or y_start >= y_stop:
        empty = np.zeros((0, 0), dtype=bool)
        return slice(0, 0), slice(0, 0), empty

    roi_mask = _paint_raster_contours(
        contours,
        canvas_shape=(y_stop - y_start, x_stop - x_start),
        origin_xy=(x_start, y_start),
    )
    if roi_mask is None:
        return None
    return (
        slice(y_start, y_stop),
        slice(x_start, x_stop),
        roi_mask,
    )


def _material_stack_rows_for_legacy_vote(stacks: np.ndarray) -> np.ndarray:
    """Keep compact rows only when conversion to legacy int32 is value-exact."""
    rows = np.asarray(stacks)
    if rows.size == 0 or not np.issubdtype(rows.dtype, np.integer):
        return np.asarray(rows, dtype=np.int32)

    dtype = rows.dtype
    if np.issubdtype(dtype, np.signedinteger) and dtype.itemsize <= 4:
        return rows
    if np.issubdtype(dtype, np.unsignedinteger) and dtype.itemsize < 4:
        return rows

    int32_info = np.iinfo(np.int32)
    min_value = int(rows.min())
    max_value = int(rows.max())
    if int32_info.min <= min_value and max_value <= int32_info.max:
        return rows
    return np.asarray(rows, dtype=np.int32)


def _pack_material_stacks_uint64(
    stacks: np.ndarray,
    *,
    min_value: int,
    radix: int,
) -> np.ndarray:
    """Encode fixed-width signed rows without an ``N x columns`` temporary."""
    rows = np.asarray(stacks)
    if rows.ndim != 2:
        raise ValueError("material stacks must be a two-dimensional array")

    codes = np.zeros((rows.shape[0],), dtype=np.uint64)
    column_digits = np.empty((rows.shape[0],), dtype=np.uint64)
    radix_u64 = np.uint64(radix)
    for column_index in range(rows.shape[1]):
        np.multiply(codes, radix_u64, out=codes)
        column_values = rows[:, column_index].astype(np.int64, copy=False)
        np.subtract(
            column_values,
            np.int64(min_value),
            out=column_digits,
            casting="unsafe",
        )
        np.add(codes, column_digits, out=codes)
    return codes


def _unique_material_stacks_exact(
    stacks: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, bool]:
    """Return exact unique rows/counts with a compact uint64 fast path.

    Fixed-width rows are encoded as one uint64 value per effective pixel only
    when the entire code space fits in uint64. Keeping aggregation in NumPy
    avoids retaining Python ``dict`` arenas across thousands of components.
    The encoding preserves signed lexicographic row order, so
    ``np.argmax(counts)`` keeps the legacy sorted-first tie break.
    固定长度配方在无溢出时压成每像素一个 uint64，并保持旧版排序和平票规则。
    """
    # The pre-ROI implementation coerced every voted row to int32. Compact
    # inputs may stay compact only when that conversion is provably value-
    # preserving; wide/out-of-range inputs are wrapped before radix analysis.
    rows = _material_stack_rows_for_legacy_vote(stacks)
    if rows.ndim != 2:
        raise ValueError("material stacks must be a two-dimensional array")
    if rows.shape[0] == 0 or rows.shape[1] == 0:
        unique_rows, counts = np.unique(
            np.asarray(rows, dtype=np.int32),
            axis=0,
            return_counts=True,
        )
        return unique_rows, counts, False

    min_value = int(rows.min())
    max_value = int(rows.max())
    radix = max_value - min_value + 1
    if pow(radix, int(rows.shape[1])) > (1 << 64):
        unique_rows, counts = np.unique(
            np.asarray(rows, dtype=np.int32),
            axis=0,
            return_counts=True,
        )
        return unique_rows, counts, False

    codes = _pack_material_stacks_uint64(
        rows,
        min_value=min_value,
        radix=radix,
    )
    sorted_codes, counts = np.unique(
        codes,
        return_counts=True,
    )
    unique_rows = np.empty(
        (len(sorted_codes), rows.shape[1]),
        dtype=np.int32,
    )
    remaining = sorted_codes.copy()
    radix_u64 = np.uint64(radix)
    for column_index in range(rows.shape[1] - 1, -1, -1):
        digit = np.remainder(remaining, radix_u64)
        unique_rows[:, column_index] = (
            digit.astype(np.int64) + min_value
        )
        np.floor_divide(remaining, radix_u64, out=remaining)
    return unique_rows, counts, True


def _apply_matched_rgb_overrides_to_analysis_impl(
    analysis: "VectorAnalysis",
    *,
    matched_rgb: np.ndarray,
    original_matched_rgb: np.ndarray | None = None,
    height_identity_rgb: np.ndarray | None = None,
    material_matrix: np.ndarray | None = None,
    original_material_matrix: np.ndarray | None = None,
    mask_solid: np.ndarray,
    img_processor,
    pixels_per_mm: float = 10.0,
    max_width_px: int = 1600,
    source_grid_shape: tuple[int, int] | None = None,
    strict: bool = False,
    metrics_out: dict[str, Any],
    prefer_cached_material_state: bool = False,
) -> int:
    """Propagate region-level ``matched_rgb`` edits into ``matched_shapes``.
    把 ``cache.matched_rgb`` 上的像素级改色回写到 ``analysis.matched_shapes``。

    The 2D preview / GLB previews route through ``cache.matched_rgb``:
    ``/region-replace`` and ``/region-replace-batch`` mutate that array
    by mask, so the preview reflects the user's edit immediately. The
    SVG-native ``_run_vector_branch`` previously re-derived per-shape
    colours from the SVG fill alone, silently dropping every spatial
    edit. This helper closes that gap by:

    1. Reproducing the same preview grid ``build_preview_cache`` uses
       so the ``matched_rgb`` / ``mask_solid`` arrays line up pixel-for-
       pixel with the analysis geometry.
    2. Rasterising every connected polygon component in
       ``analysis.matched_shapes`` into its own boolean mask and
       intersecting it with ``mask_solid`` (background pixels are ignored
       so a "carved out" hole cannot poison the component colour vote).
    3. Picking the dominant RGB and recipe inside each effective mask. If
       disconnected components of one compound SVG shape resolve to
       different assignments, that source record is split while preserving
       its non-geometry metadata and source order. Uniform/no-op compound
       shapes retain their original geometry.
    4. Re-running the same KDTree lookup ``_match_colors`` uses so every new
       ``matched_rgb`` / ``recipe`` stays inside the user's calibrated
       material set.

    The helper preserves every public surface (the module exports it,
    nothing else changes) and is therefore opt-in for callers that have
    a fresh ``cache.matched_rgb`` to forward.

    2D 预览 / GLB 走 ``cache.matched_rgb``，``/region-replace`` 之类
    端点会按 mask 改写它，但生成阶段的矢量分支以前只从 SVG fill 复算
    颜色，用户的空间改色被静默丢弃。本 helper 复现 ``build_preview_cache``
    网格，按连通 polygon component 求 mask，与 ``mask_solid`` 求交后取
    dominant RGB/recipe。复合路径的各断开分量若结果不同才拆成独立记录，
    再把新颜色和配方回写到 ``matched_shapes``，让 3MF 与 2D 预览保持一致。

    Args:
        analysis: ``VectorAnalysis`` from ``analyze_svg``; mutated in place.
            （``analyze_svg`` 返回的分析结果，就地修改）
        matched_rgb: ``(H, W, 3) uint8`` array taken from ``cache["matched_rgb"]``.
            （取自 ``cache["matched_rgb"]`` 的预览栅格）
        height_identity_rgb: Optional pristine ``(H, W, 3) uint8`` height
            identity grid. Display replacements never mutate this grid.
            （可选的 pristine 高度身份栅格；显示替色不会修改它）
        material_matrix: Optional ``(H, W, N)`` integer recipe grid.
            （可选的 ``(H, W, N)`` 整数配方网格）
        mask_solid: ``(H, W) bool`` array taken from ``cache["mask_solid"]``.
            （取自 ``cache["mask_solid"]`` 的实体像素掩码）
        img_processor: Object exposing ``_rgb_to_lab``, ``kdtree``,
            ``lut_rgb`` and ``ref_stacks`` — the same interface
            ``VectorProcessor._match_colors`` consumes.
            （提供 LUT KDTree / 调色板 / 配方 stack 的处理器对象）
        pixels_per_mm: Preview-grid density. Must match the value used
            by :meth:`VectorProcessor.build_preview_cache`.
            （预览网格密度，需与 ``build_preview_cache`` 一致）
        max_width_px: Preview-grid width cap. Same constraint.
            （预览网格宽度上限，同上）
        strict: Raise ``ValueError`` for invalid cache inputs or grid
            mismatches instead of logging and returning zero. A valid cache
            that changes no shapes still returns zero normally.
            （缓存输入或网格无效时抛出 ``ValueError``；合法但无修改仍返回零）
        prefer_cached_material_state: Treat the cache RGB and recipe matrix as
            authoritative instead of re-deriving the display RGB from the
            current matcher. Dynamic material sessions use this so edited
            vector 3MF stays on the same recipe contract as 2D/GLB.

    Returns:
        int: Number of connected components whose material assignment changed.
            （材质分配被改写的连通分量数量）
    """
    metrics_out.clear()
    metrics_out.update(
        {
            "raster_strategy": "roi",
            "component_count": 0,
            "full_canvas_pixel_work": 0,
            "roi_pixel_work": 0,
            "max_roi_pixels": 0,
            "effective_pixel_count": 0,
            "pixel_work_reduction_ratio": 0.0,
            "packed_material_vote_count": 0,
            "fallback_material_vote_count": 0,
            "rewritten_component_count": 0,
            "output_shape_count": len(
                getattr(analysis, "matched_shapes", None) or []
            ),
        }
    )
    if matched_rgb is None or mask_solid is None:
        if strict:
            raise ValueError("matched_rgb and mask_solid are required")
        return 0
    if not analysis.matched_shapes and not strict:
        return 0
    real_w = float(analysis.bbox[2])
    real_h = float(analysis.bbox[3])
    sf = float(analysis.scale_factor)
    w_mm = real_w * sf
    h_mm = real_h * sf
    if w_mm <= 0 or h_mm <= 0:
        return 0

    if source_grid_shape is not None:
        try:
            h_px, w_px = (
                int(source_grid_shape[0]),
                int(source_grid_shape[1]),
            )
        except (TypeError, ValueError, IndexError, OverflowError) as exc:
            raise ValueError("source edit grid must contain two dimensions") from exc
        if h_px <= 0 or w_px <= 0:
            raise ValueError("source edit grid dimensions must be positive")
        coord_scale: float | tuple[float, float] = (
            w_px / real_w,
            h_px / real_h,
        )
    else:
        ppm = float(pixels_per_mm)
        w_px = max(1, int(round(w_mm * ppm)))
        h_px = max(1, int(round(h_mm * ppm)))
        if w_px > max_width_px:
            ratio = max_width_px / w_px
            w_px = max_width_px
            h_px = max(1, int(round(h_px * ratio)))
            ppm = w_px / w_mm
        coord_scale = sf * ppm

    matched_arr = np.asarray(matched_rgb)
    raw_mask_arr = np.asarray(mask_solid)
    mask_arr = np.asarray(mask_solid, dtype=bool)
    if matched_arr.ndim != 3 or matched_arr.shape[2] != 3 or matched_arr.dtype != np.uint8:
        error_message = (
            f"matched_rgb shape/dtype {matched_arr.shape}/{matched_arr.dtype} "
            "is not (H,W,3) uint8"
        )
        _log.warning(
            "Vector matched RGB overrides skipped because input array is invalid",
            extra={
                "event": "vector_overrides_input_invalid",
                "error_type": "ValueError",
                "error_message": error_message,
                "matched_rgb_shape": list(matched_arr.shape),
                "matched_rgb_dtype": str(matched_arr.dtype),
            },
        )
        if strict:
            raise ValueError(error_message)
        return 0

    identity_arr = None
    if height_identity_rgb is not None:
        candidate_identity = np.asarray(height_identity_rgb)
        identity_is_valid = (
            candidate_identity.ndim == 3
            and candidate_identity.shape == matched_arr.shape
            and candidate_identity.dtype == np.uint8
        )
        if not identity_is_valid:
            error_message = (
                f"height_identity_rgb shape/dtype "
                f"{candidate_identity.shape}/{candidate_identity.dtype} "
                f"does not match matched_rgb {matched_arr.shape}/uint8"
            )
            _log.warning(
                "Vector height identity projection skipped because input is invalid",
                extra={
                    "event": "vector_height_identity_input_invalid",
                    "error_type": "ValueError",
                    "error_message": error_message,
                    "height_identity_rgb_shape": list(candidate_identity.shape),
                    "height_identity_rgb_dtype": str(candidate_identity.dtype),
                    "matched_rgb_shape": list(matched_arr.shape),
                },
            )
            if strict:
                raise ValueError(error_message)
        else:
            identity_arr = candidate_identity
    if strict and raw_mask_arr.dtype != np.dtype(np.bool_):
        error_message = (
            f"mask_solid dtype {raw_mask_arr.dtype} is not bool"
        )
        _log.warning(
            "Vector matched RGB overrides skipped because mask dtype is invalid",
            extra={
                "event": "vector_overrides_input_invalid",
                "error_type": "ValueError",
                "error_message": error_message,
                "mask_solid_shape": list(raw_mask_arr.shape),
                "mask_solid_dtype": str(raw_mask_arr.dtype),
            },
        )
        raise ValueError(error_message)
    if matched_arr.shape[:2] != (h_px, w_px) or mask_arr.shape != (h_px, w_px):
        error_message = (
            f"matched_rgb/mask_solid shape {matched_arr.shape[:2]}/{mask_arr.shape} "
            f"does not match preview grid {(h_px, w_px)}"
        )
        _log.warning(
            "Vector matched RGB overrides skipped because cache grid mismatched analysis",
            extra={
                "event": "vector_overrides_grid_mismatch",
                "error_type": "ValueError",
                "error_message": error_message,
                "matched_rgb_shape": list(matched_arr.shape[:2]),
                "mask_solid_shape": list(mask_arr.shape),
                "expected_shape": [int(h_px), int(w_px)],
            },
        )
        if strict:
            raise ValueError(error_message)
        return 0

    num_channels = int(getattr(analysis, "num_channels", 0) or 0)
    num_layers = int(getattr(analysis, "num_layers", 0) or 0)
    if (num_channels <= 0 or num_layers <= 0) and not strict:
        return 0

    matrix_arr = None
    if material_matrix is not None:
        candidate_matrix = np.asarray(material_matrix)
        matrix_grid_is_valid = (
            candidate_matrix.ndim == 3
            and candidate_matrix.shape[:2] == (h_px, w_px)
        )
        matrix_dtype_is_valid = np.issubdtype(candidate_matrix.dtype, np.integer)
        matrix_channels_are_valid = (
            candidate_matrix.ndim == 3 and candidate_matrix.shape[2] > 0
        )
        if matrix_grid_is_valid and (
            not strict or (matrix_dtype_is_valid and matrix_channels_are_valid)
        ):
            matrix_arr = candidate_matrix
        else:
            if strict:
                error_message = (
                    f"material_matrix shape/dtype "
                    f"{candidate_matrix.shape}/{candidate_matrix.dtype} "
                    f"does not match non-empty integer preview grid "
                    f"{(h_px, w_px)}"
                )
            else:
                error_message = (
                    f"material_matrix shape {candidate_matrix.shape} "
                    f"does not match preview grid {(h_px, w_px)}"
                )
            _log.warning(
                "Vector material matrix overrides skipped because cache grid mismatched analysis",
                extra={
                    "event": "vector_material_matrix_grid_mismatch",
                    "error_type": "ValueError",
                    "error_message": error_message,
                    "material_matrix_shape": list(candidate_matrix.shape),
                    **(
                        {"material_matrix_dtype": str(candidate_matrix.dtype)}
                        if strict
                        else {}
                    ),
                    "expected_shape": [int(h_px), int(w_px)],
                },
            )
            if strict:
                raise ValueError(error_message)

    edit_mask_arr = None
    if original_matched_rgb is not None or original_material_matrix is not None:
        edit_mask_arr = np.zeros((h_px, w_px), dtype=bool)
        if original_matched_rgb is not None:
            pristine_rgb = np.asarray(original_matched_rgb)
            if pristine_rgb.shape != matched_arr.shape or pristine_rgb.dtype != np.uint8:
                error_message = (
                    "original_matched_rgb must match cached matched_rgb shape/dtype"
                )
                if strict:
                    raise ValueError(error_message)
                _log.warning(
                    "Vector pristine RGB artifact is invalid; edit projection skipped",
                    extra={
                        "event": "vector_original_matched_rgb_invalid",
                        "error_type": "ValueError",
                        "error_message": error_message,
                    },
                )
                return 0
            edit_mask_arr |= np.any(matched_arr != pristine_rgb, axis=-1)
        if original_material_matrix is not None:
            pristine_matrix = np.asarray(original_material_matrix)
            if (
                matrix_arr is None
                or pristine_matrix.ndim != 3
                or pristine_matrix.shape[:2] != (h_px, w_px)
                or not np.issubdtype(pristine_matrix.dtype, np.integer)
            ):
                error_message = (
                    "original_material_matrix must match the cached material grid"
                )
                if strict:
                    raise ValueError(error_message)
                _log.warning(
                    "Vector pristine material artifact is invalid; edit projection skipped",
                    extra={
                        "event": "vector_original_material_matrix_invalid",
                        "error_type": "ValueError",
                        "error_message": error_message,
                    },
                )
                return 0
            common_layers = min(
                int(matrix_arr.shape[2]),
                int(pristine_matrix.shape[2]),
            )
            if common_layers > 0:
                edit_mask_arr |= np.any(
                    matrix_arr[..., :common_layers]
                    != pristine_matrix[..., :common_layers],
                    axis=-1,
                )
        edit_mask_arr &= mask_arr

    if not analysis.matched_shapes:
        return 0

    if num_channels <= 0 or num_layers <= 0:
        return 0

    lut_rgb = img_processor.lut_rgb
    ref_stacks = img_processor.ref_stacks

    changed = 0
    per_shape_diag: list[dict] = []
    lut_index_cache: dict[tuple[int, int, int], int] = {}

    def _query_lut_index(rgb: tuple[int, int, int]) -> int:
        cached_index = lut_index_cache.get(rgb)
        if cached_index is not None:
            return cached_index
        query_lab = img_processor._rgb_to_lab(
            np.array([rgb], dtype=np.uint8)
        )
        _, index = img_processor.kdtree.query(query_lab)
        lut_index = int(np.atleast_1d(index)[0])
        lut_index_cache[rgb] = lut_index
        return lut_index

    def _material_state(
        shape: dict,
    ) -> tuple[tuple[int, ...] | None, tuple[int, ...]]:
        rgb = shape.get("matched_rgb")
        try:
            rgb_state = tuple(int(c) for c in rgb)
        except (TypeError, ValueError):
            rgb_state = None
        recipe_state = tuple(int(v) for v in (shape.get("recipe") or []))
        return rgb_state, recipe_state

    def _height_identity_state(shape: dict) -> tuple[int, ...] | None:
        rgb = shape.get("height_identity_rgb")
        if rgb is None:
            rgb = shape.get("matched_rgb") or shape.get("color")
        try:
            return tuple(int(c) for c in rgb)
        except (TypeError, ValueError):
            return None

    def _dynamic_metadata_for_cached_assignment(
        shape: dict,
        *,
        matched_color: tuple[int, int, int],
        recipe: list[int],
    ) -> dict | None:
        dynamic_info = getattr(analysis, "material_dynamic_layer_info", None)
        if not isinstance(dynamic_info, dict) or not dynamic_info.get("enabled"):
            return None
        recipe_list = [int(value) for value in recipe]
        for entry in dynamic_info.get("colors", []):
            if not isinstance(entry, dict):
                continue
            try:
                entry_matched = tuple(int(value) for value in entry["matched_srgb"])
                entry_recipe = [
                    int(value)
                    for value in entry["print_recipe_top_to_bottom"]
                ]
            except (KeyError, TypeError, ValueError):
                continue
            if entry_matched == matched_color and entry_recipe == recipe_list:
                return deepcopy(entry)
        existing = shape.get("material_dynamic_recipe")
        if isinstance(existing, dict):
            try:
                if [
                    int(value)
                    for value in existing.get("print_recipe_top_to_bottom", [])
                ] == recipe_list:
                    result = deepcopy(existing)
                    result["matched_srgb"] = list(matched_color)
                    return result
            except (TypeError, ValueError):
                pass
        # Custom recipe edits may intentionally no longer correspond to an
        # exact-solver candidate. Preserve their full physical stack without
        # inventing a shorter effective depth.
        return {
            "matched_srgb": list(matched_color),
            "actual_layer_count": len(recipe_list),
            "padding_layer_count": 0,
            "actual_recipe_top_to_bottom": recipe_list,
            "print_recipe_top_to_bottom": recipe_list,
            "source": "cached_material_matrix",
        }

    def _dominant_rgb(pixels: np.ndarray) -> tuple[int, int, int]:
        codes = (
            pixels[:, 0].astype(np.uint32) * np.uint32(65536)
            + pixels[:, 1].astype(np.uint32) * np.uint32(256)
            + pixels[:, 2].astype(np.uint32)
        )
        uniq, counts = np.unique(codes, return_counts=True)
        dominant_code = int(uniq[int(np.argmax(counts))])
        return (
            (dominant_code >> 16) & 0xFF,
            (dominant_code >> 8) & 0xFF,
            dominant_code & 0xFF,
        )

    def _project_component(
        *,
        shape_idx: int,
        component_idx: int,
        shape: dict,
        geom,
    ) -> dict | None:
        metrics_out["component_count"] += 1
        metrics_out["full_canvas_pixel_work"] += h_px * w_px
        roi_result = _rasterize_geometry_roi_mask(
            geom,
            canvas_shape=(h_px, w_px),
            coord_scale=coord_scale,
        )
        if roi_result is None:
            return None
        y_slice, x_slice, shape_mask = roi_result

        raster_pixel_work = int(shape_mask.size)
        metrics_out["roi_pixel_work"] += raster_pixel_work
        metrics_out["max_roi_pixels"] = max(
            int(metrics_out["max_roi_pixels"]),
            raster_pixel_work,
        )
        local_mask_solid = mask_arr[y_slice, x_slice]
        effective_mask = np.logical_and(shape_mask, local_mask_solid)
        if edit_mask_arr is not None:
            effective_mask &= edit_mask_arr[y_slice, x_slice]
        if not np.any(effective_mask):
            return None
        metrics_out["effective_pixel_count"] += int(
            np.count_nonzero(effective_mask)
        )

        local_matched_rgb = matched_arr[y_slice, x_slice]
        dominant_rgb = _dominant_rgb(local_matched_rgb[effective_mask])
        if identity_arr is not None:
            local_identity_rgb = identity_arr[y_slice, x_slice]
            dominant_height_identity = _dominant_rgb(
                local_identity_rgb[effective_mask]
            )
        else:
            dominant_height_identity = _height_identity_state(shape)
            if dominant_height_identity is None:
                dominant_height_identity = dominant_rgb

        try:
            lut_idx = _query_lut_index(dominant_rgb)
        except (TypeError, ValueError, IndexError):
            return None
        new_matched_rgb = (
            dominant_rgb
            if prefer_cached_material_state and matrix_arr is not None
            else tuple(int(c) for c in lut_rgb[lut_idx])
        )

        stack_source = "ref_stacks_fallback"
        stack_top_alternatives: list[list[int]] = []
        if matrix_arr is not None:
            local_material_matrix = matrix_arr[y_slice, x_slice]
            stacks = np.asarray(local_material_matrix[effective_mask])
            if stacks.ndim == 2 and stacks.shape[1] > 0:
                (
                    uniq_stacks,
                    stack_counts,
                    used_packed_vote,
                ) = _unique_material_stacks_exact(stacks)
                metric_name = (
                    "packed_material_vote_count"
                    if used_packed_vote
                    else "fallback_material_vote_count"
                )
                metrics_out[metric_name] += 1
                stack = uniq_stacks[int(np.argmax(stack_counts))]
                stack_source = "material_matrix_majority"
                top_n = min(3, len(stack_counts))
                top_indices = np.argsort(-stack_counts)[:top_n]
                for ti in top_indices:
                    stack_top_alternatives.append(
                        [int(c) for c in uniq_stacks[ti].tolist()[:6]]
                        + [int(stack_counts[ti])]
                    )
            else:
                stack = ref_stacks[lut_idx]
        else:
            stack = ref_stacks[lut_idx]
        new_recipe = _normalise_cached_stack_for_vector_recipe(
            stack,
            target_layers=num_layers,
            num_channels=num_channels,
        )
        dynamic_recipe = _dynamic_metadata_for_cached_assignment(
            shape,
            matched_color=new_matched_rgb,
            recipe=new_recipe,
        )

        prev_recipe = [int(v) for v in shape.get("recipe", [])]

        if len(per_shape_diag) < 24:
            try:
                area = float(geom.area) if geom is not None else 0.0
            except (AttributeError, TypeError, ValueError):
                area = 0.0
            per_shape_diag.append(
                {
                    "shape_idx": int(shape_idx),
                    "component_idx": int(component_idx),
                    "area": round(area, 3),
                    "effective_pixels": int(np.count_nonzero(effective_mask)),
                    "dominant_rgb": list(dominant_rgb),
                    "lut_idx": int(lut_idx),
                    "matched_rgb": list(new_matched_rgb),
                    "stack_source": stack_source,
                    "stack_first6": (
                        [int(c) for c in stack[:6].tolist()]
                        if hasattr(stack, "tolist")
                        else list(stack[:6])
                    ),
                    "stack_top_alternatives_first6_with_count": stack_top_alternatives,
                    "new_recipe_first6": new_recipe[:6],
                    "prev_recipe_first6": prev_recipe[:6],
                }
            )

        assignment_changed = _material_state(shape) != (
            new_matched_rgb,
            tuple(new_recipe),
        )

        identity_lut_idx = _query_lut_index(dominant_height_identity)
        original_recipe = _normalise_cached_stack_for_vector_recipe(
            ref_stacks[identity_lut_idx],
            target_layers=num_layers,
            num_channels=num_channels,
        )
        return {
            "matched_rgb": new_matched_rgb,
            "lut_idx": lut_idx,
            "recipe": new_recipe,
            "height_identity_rgb": dominant_height_identity,
            "original_recipe": original_recipe,
            "material_dynamic_recipe": dynamic_recipe,
            "changed": assignment_changed,
        }

    projected_shapes: list[dict] = []
    for shape_idx, shape in enumerate(analysis.matched_shapes):
        geom = shape.get("geometry")
        if geom is None or getattr(geom, "is_empty", False):
            projected_shapes.append(shape)
            continue

        components = _iter_raster_polygon_components(geom)
        if not components:
            projected_shapes.append(shape)
            continue

        component_records: list[dict] = []
        changed_components = 0
        for component_idx, component in enumerate(components):
            component_record = dict(shape)
            component_record["geometry"] = component
            projection = _project_component(
                shape_idx=shape_idx,
                component_idx=component_idx,
                shape=shape,
                geom=component,
            )
            if projection is not None:
                component_record["matched_rgb"] = projection["matched_rgb"]
                component_record["lut_idx"] = projection["lut_idx"]
                component_record["recipe"] = projection["recipe"]
                component_record["height_identity_rgb"] = projection[
                    "height_identity_rgb"
                ]
                component_record["original_recipe"] = projection[
                    "original_recipe"
                ]
                if projection["material_dynamic_recipe"] is not None:
                    component_record["material_dynamic_recipe"] = projection[
                        "material_dynamic_recipe"
                    ]
                if projection["changed"]:
                    changed_components += 1
            component_records.append(component_record)

        component_states = [
            (_material_state(record), _height_identity_state(record))
            for record in component_records
        ]
        if len(set(component_states)) <= 1:
            # Preserve the original compound geometry whenever every connected
            # component resolves to the same material assignment. This keeps
            # zero-change and global-replacement exports structurally stable.
            if component_records:
                uniform_record = component_records[0]
                if changed_components:
                    shape["matched_rgb"] = uniform_record.get("matched_rgb")
                    shape["lut_idx"] = uniform_record.get("lut_idx")
                    shape["recipe"] = list(uniform_record.get("recipe") or [])
                shape["height_identity_rgb"] = uniform_record.get(
                    "height_identity_rgb"
                )
                shape["original_recipe"] = list(
                    uniform_record.get("original_recipe") or []
                )
                if uniform_record.get("material_dynamic_recipe") is not None:
                    shape["material_dynamic_recipe"] = uniform_record[
                        "material_dynamic_recipe"
                    ]
            projected_shapes.append(shape)
        else:
            # Downstream tiling and mesh construction consume records by value,
            # not by list index. Shallow copies retain source identity, draw
            # order, slot metadata, and any future non-geometry fields.
            projected_shapes.extend(component_records)
        changed += changed_components

    analysis.matched_shapes = projected_shapes
    metrics_out["rewritten_component_count"] = int(changed)
    metrics_out["output_shape_count"] = len(projected_shapes)
    roi_pixel_work = int(metrics_out["roi_pixel_work"])
    if roi_pixel_work > 0:
        metrics_out["pixel_work_reduction_ratio"] = (
            int(metrics_out["full_canvas_pixel_work"]) / roi_pixel_work
        )

    # Diagnostic: emit per-shape majority vote details.
    if per_shape_diag:
        _log.debug(
            "Vector per-shape majority vote diagnostics",
            extra={
                "event": "vector_diag_apply_matched_rgb_per_shape",
                "stage": "apply_matched_rgb_overrides_per_shape",
                "per_shape_diag": per_shape_diag,
            },
        )

    if changed:
        _log.debug(
            "Vector matched RGB overrides applied",
            extra={
                "event": "vector_overrides_applied",
                "shape_count": len(analysis.matched_shapes),
                "rewritten_count": int(changed),
            },
        )
    return changed


def apply_matched_rgb_overrides_to_analysis(
    analysis: "VectorAnalysis",
    *,
    matched_rgb: np.ndarray,
    original_matched_rgb: np.ndarray | None = None,
    height_identity_rgb: np.ndarray | None = None,
    material_matrix: np.ndarray | None = None,
    original_material_matrix: np.ndarray | None = None,
    mask_solid: np.ndarray,
    img_processor,
    pixels_per_mm: float = 10.0,
    max_width_px: int = 1600,
    source_grid_shape: tuple[int, int] | None = None,
    strict: bool = False,
    prefer_cached_material_state: bool = False,
) -> int:
    """Project cached pixel edits into vector shapes with an exact local ROI.

    Without pristine artifacts this preserves the legacy full-cache replay.
    When pristine RGB/material artifacts and ``source_grid_shape`` are given,
    only explicit edit deltas claim fresh vector components after dimensions
    change. Each connected component still uses a tightly cropped raster ROI.

    不提供原始基线时保持旧的整份缓存回写；提供原始 RGB、材料矩阵和源网格
    后，只让明确编辑过的区域覆盖新尺寸矢量分析，且每个连通分量仍使用局部 ROI。
    """
    metrics: dict[str, Any] = {}
    try:
        return _apply_matched_rgb_overrides_to_analysis_impl(
            analysis,
            matched_rgb=matched_rgb,
            original_matched_rgb=original_matched_rgb,
            height_identity_rgb=height_identity_rgb,
            material_matrix=material_matrix,
            original_material_matrix=original_material_matrix,
            mask_solid=mask_solid,
            img_processor=img_processor,
            pixels_per_mm=pixels_per_mm,
            max_width_px=max_width_px,
            source_grid_shape=source_grid_shape,
            strict=strict,
            metrics_out=metrics,
            prefer_cached_material_state=prefer_cached_material_state,
        )
    finally:
        analysis.matched_rgb_override_metrics = dict(metrics)


def _normalise_cached_stack_for_vector_recipe(
    stack: np.ndarray,
    *,
    target_layers: int,
    num_channels: int,
) -> list[int]:
    """Return a full-length vector recipe from a cached material stack."""
    if target_layers <= 0 or num_channels <= 0:
        return []

    flat = np.asarray(stack, dtype=np.int32).reshape(-1)
    clamped_printable_values = [
        min(int(value), int(num_channels) - 1)
        for value in flat[:target_layers].tolist()
        if int(value) >= 0
    ]
    filler = int(clamped_printable_values[-1]) if clamped_printable_values else 0
    unique_printable_values = set(clamped_printable_values)
    fill_air_padding = len(unique_printable_values) == 1

    recipe: list[int] = []
    for raw_value in flat[:target_layers]:
        value = int(raw_value)
        if value < 0:
            recipe.append(filler if fill_air_padding else value)
        else:
            recipe.append(min(value, int(num_channels) - 1))

    if len(recipe) < target_layers:
        recipe.extend([filler] * (target_layers - len(recipe)))
    return recipe


class VectorProcessor:
    """
    Native vector processing engine for SVG files.

    Converts SVG directly to 3D meshes without rasterization,
    preserving vector precision.  Uses ChromaPrint3D-style
    occlusion clipping and run-length layer extrusion.

    Attributes:
        color_mode: Color system mode string forwarded to ColorSystem.
        img_processor: LuminaImageProcessor instance for LUT / KDTree access.
        sampling_precision: Curve approximation precision in mm.
    """

    def __init__(
        self,
        lut_path: str,
        color_mode: str,
        *,
        hue_weight: float = 0.0,
        chroma_gate: float = 15.0,
    ):
        """Initialize the LUT-backed SVG vector processor.

        初始化基于 LUT 的 SVG 矢量处理器。

        Args:
            lut_path: LUT file path used for color-to-recipe matching.
                用于颜色匹配到配方的 LUT 文件路径。
            color_mode: Canonical color mode label for this conversion.
                本次转换使用的标准颜色模式名称。
            hue_weight: Hue-protection strength forwarded to the shared
                image processor. 色相保护强度，传给共用图像处理器。
            chroma_gate: Chroma threshold for dark-color protection.
                暗色保护的彩度门槛。
        """
        self.color_mode = color_mode
        _log.debug("Initializing Native Vector Engine (%s)...", color_mode)

        ImageProcessor = _get_image_processor_class()
        self.img_processor = ImageProcessor(
            lut_path,
            color_mode,
            hue_weight=hue_weight,
            chroma_gate=chroma_gate,
        )
        self._init_runtime_defaults()

        _log.debug("Initialized with %s LUT colors", len(self.img_processor.ref_stacks))

    def _init_runtime_defaults(self) -> None:
        """Set the non-color-matching runtime fields shared by both
        constructors (LUT path and material-archive path).

        Centralised so :meth:`from_img_processor` does not drift if new
        runtime defaults are added later. ``__init__`` and the factory
        both call this immediately after wiring ``img_processor``.

        集中初始化与匹配器无关的运行时默认值，避免 LUT/耗材两条
        构造路径走偏。
        """
        self.sampling_precision = 0.02  # mm
        self.last_stage_timings = {}
        self.parse_warnings: list[str] = []
        self.enable_fridge_magnet = False
        self.fridge_magnets: list = []
        self.enable_coating = False
        self.coating_height_mm = 0.08
        self.coating_material = None
        self.enable_outline = False
        self.outline_width_mm = 0.0
        self.expand_stroke_to_fill = False
        self.svg_hole_compensation_enabled = False
        self.svg_hole_max_area_mm2 = 0.5
        self.svg_hole_max_width_mm = 0.1
        self.layer_height_mm = float(PrinterConfig.LAYER_HEIGHT)

    @classmethod
    def from_img_processor(
        cls, img_processor, color_mode: str
    ) -> "VectorProcessor":
        """Build a ``VectorProcessor`` around a pre-built color matcher.

        Used by the material-archive branch which constructs a
        :class:`core.vector_matchers.MaterialVectorMatcher` instead of
        loading a LUT from disk. The matcher must duck-type the small
        slice of :class:`core.image_processing.LuminaImageProcessor`
        that ``analyze_svg`` / ``_match_colors`` consume (see
        :mod:`core.vector_matchers` module docstring for the full
        contract).

        从已构造的颜色匹配器构造 VectorProcessor；耗材档案分支用
        此入口，避免触发 LUT 文件解析。

        Args:
            img_processor: Object exposing the LuminaImageProcessor
                duck surface required by the vector pipeline.
            color_mode: Display string forwarded to logs and exports.

        Returns:
            A configured ``VectorProcessor`` ready for ``analyze_svg``.
        """
        instance = cls.__new__(cls)
        instance.color_mode = color_mode
        instance.img_processor = img_processor
        instance._init_runtime_defaults()
        _log.debug(
            "Initialized Vector Engine via injected matcher (%s)",
            color_mode,
        )
        return instance

    def _build_small_shape_match_overrides(self, clipped_shapes, scale_factor):
        max_area_ratio = float(
            getattr(VectorConfig, "MATERIAL_VECTOR_SMALL_SHAPE_SNAP_MAX_AREA_RATIO", 0.0)
        )
        min_anchor_ratio = float(
            getattr(VectorConfig, "MATERIAL_VECTOR_SMALL_SHAPE_SNAP_MIN_ANCHOR_AREA_RATIO", 0.0)
        )
        delta_e_threshold = float(
            getattr(VectorConfig, "MATERIAL_VECTOR_SMALL_SHAPE_SNAP_DELTA_E", 0.0)
        )
        if not clipped_shapes or max_area_ratio <= 0.0 or delta_e_threshold <= 0.0:
            return {}

        area_by_color = {}
        total_area_mm2 = 0.0
        mm2_scale = float(scale_factor) * float(scale_factor)
        for item in clipped_shapes:
            color = item.get("color")
            geom = item.get("geometry")
            if color is None or geom is None or geom.is_empty:
                continue
            try:
                key = (int(color[0]), int(color[1]), int(color[2]))
            except (TypeError, IndexError, ValueError):
                continue
            area_mm2 = max(0.0, float(geom.area) * mm2_scale)
            total_area_mm2 += area_mm2
            area_by_color[key] = area_by_color.get(key, 0.0) + area_mm2

        if total_area_mm2 <= 0.0 or len(area_by_color) < 2:
            return {}

        source_colors = sorted(area_by_color)
        src_rgb = np.array(source_colors, dtype=np.uint8)
        src_lab = self.img_processor._rgb_to_lab(src_rgb).reshape(-1, 3).astype(np.float64)
        _, lut_indices = self.img_processor.kdtree.query(src_lab)
        lut_indices = np.asarray(lut_indices).reshape(-1)
        matched_rgb = self.img_processor.lut_rgb[lut_indices].astype(np.uint8, copy=False)
        matched_lab = self.img_processor._rgb_to_lab(matched_rgb).reshape(-1, 3).astype(np.float64)
        delta_e = np.linalg.norm(src_lab - matched_lab, axis=1)

        area_ratio_by_color = {
            rgb: (float(area_by_color[rgb]) / total_area_mm2)
            for rgb in source_colors
        }
        anchor_colors = [
            rgb for rgb in source_colors
            if area_ratio_by_color[rgb] >= min_anchor_ratio
        ]
        if not anchor_colors:
            anchor_colors = [max(source_colors, key=lambda rgb: area_by_color[rgb])]

        lab_by_color = {
            rgb: src_lab[idx]
            for idx, rgb in enumerate(source_colors)
        }
        matched_by_color = {
            rgb: tuple(int(c) for c in matched_rgb[idx])
            for idx, rgb in enumerate(source_colors)
        }

        overrides = {}
        snapped_shape_count = 0
        snapped_source_colors = set()
        delta_e_by_color = {
            rgb: float(delta_e[idx])
            for idx, rgb in enumerate(source_colors)
        }
        for shape_idx, item in enumerate(clipped_shapes):
            color = item.get("color")
            geom = item.get("geometry")
            if color is None or geom is None or geom.is_empty:
                continue
            try:
                rgb = (int(color[0]), int(color[1]), int(color[2]))
            except (TypeError, IndexError, ValueError):
                continue
            shape_area_ratio = (max(0.0, float(geom.area) * mm2_scale) / total_area_mm2)
            if shape_area_ratio > max_area_ratio or delta_e_by_color[rgb] <= delta_e_threshold:
                continue
            candidate_anchors = [anchor for anchor in anchor_colors if anchor != rgb]
            if not candidate_anchors:
                continue
            src_vec = lab_by_color[rgb]
            chosen_anchor = min(
                candidate_anchors,
                key=lambda anchor: float(np.linalg.norm(src_vec - lab_by_color[anchor])),
            )
            if chosen_anchor == rgb:
                continue
            overrides[shape_idx] = chosen_anchor
            snapped_shape_count += 1
            snapped_source_colors.add(rgb)
            _log.debug(
                "Vector small-shape snap: %s -> %s shape_area_ratio=%.4f color_area_ratio=%.4f dE=%.2f matched=%s anchor_matched=%s",
                _rgb_to_hex(rgb),
                _rgb_to_hex(chosen_anchor),
                shape_area_ratio,
                area_ratio_by_color[rgb],
                delta_e_by_color[rgb],
                _rgb_to_hex(matched_by_color[rgb]),
                _rgb_to_hex(matched_by_color[chosen_anchor]),
            )

        if overrides:
            _log.info(
                "Vector small-shape snap applied: colors=%d shapes=%d max_area_ratio=%.4f min_anchor_ratio=%.4f delta_e=%.1f",
                len(snapped_source_colors),
                snapped_shape_count,
                max_area_ratio,
                min_anchor_ratio,
                delta_e_threshold,
                extra={
                    "event": "vector_material_small_shape_snap_applied",
                    "snapped_color_count": len(snapped_source_colors),
                    "snapped_shape_count": snapped_shape_count,
                    "max_area_ratio": max_area_ratio,
                    "min_anchor_area_ratio": min_anchor_ratio,
                    "delta_e_threshold": delta_e_threshold,
                },
            )

        return overrides

    # ── Geometry pre-processing helpers ─────────────────────────────────

    @staticmethod
    def _normalize_contours(geom, close_delta_mm=0.03):
        """Morphological close: inflate -> deflate to fill micro-gaps.

        Mirrors ``ChromaPrint3D::NormalizeContours`` (Clipper2 inflate/deflate).
        Uses Shapely ``buffer`` as an equivalent operation.
        """
        return _structure_normalize_contours(geom, close_delta_mm)

    @staticmethod
    def _filter_backing_holes(geom, min_hole_area_mm2=1.0):
        """Remove small holes from the backing plate polygon.

        Mirrors ``ChromaPrint3D``'s ``base_min_hole_area_mm2`` filtering.
        """
        return _structure_filter_backing_holes(geom, min_hole_area_mm2)

    @staticmethod
    def _filter_slits(geom, min_slit_width_mm=0.1):
        """Filter sub-threshold slit-like features from polygonal geometry."""
        if geom is None or geom.is_empty:
            return geom

        try:
            distance = float(min_slit_width_mm) / 2.0 + 1e-9
        except (TypeError, ValueError):
            distance = 0.05 + 1e-9
        if distance <= 0:
            return geom

        try:
            expanded = geom.buffer(distance)
            closed = expanded.buffer(-distance)
            if closed.is_empty:
                return geom

            opened = geom.buffer(-distance).buffer(distance)
            result = closed
            if (
                not opened.is_empty
                and VectorProcessor._polygon_component_count(opened)
                > VectorProcessor._polygon_component_count(closed)
            ):
                result = opened

            result = VectorProcessor._extract_polygonal_geometry(make_valid(result))
            return result if result is not None and not result.is_empty else geom
        except VECTOR_HANDLED_ERRORS:
            return geom

    @staticmethod
    def _polygon_component_count(geom) -> int:
        if geom is None or geom.is_empty:
            return 0
        if geom.geom_type == "Polygon":
            return 1
        if geom.geom_type == "MultiPolygon":
            return len(geom.geoms)
        return 0

    @staticmethod
    def _centered_mm_to_vector_coords(center_x_mm, center_y_mm, bbox, scale_factor):
        """Convert centered preview-space mm into normalized vector coordinates."""
        if scale_factor <= 0:
            raise ValueError("scale_factor must be positive")

        min_x = float(bbox[0])
        min_y = float(bbox[1])
        width = float(bbox[2])
        height = float(bbox[3])
        center_x_svg = min_x + (width / 2.0) + (float(center_x_mm) / float(scale_factor))
        center_y_svg = min_y + (height / 2.0) - (float(center_y_mm) / float(scale_factor))
        return (center_x_svg, center_y_svg)

    @staticmethod
    def _build_vector_fridge_magnet_outline(magnet, bbox, scale_factor):
        """Build one fridge-magnet footprint in normalized vector polygon space."""
        center_x, center_y = VectorProcessor._centered_mm_to_vector_coords(
            magnet.get("center_x_mm", 0.0),
            magnet.get("center_y_mm", 0.0),
            bbox,
            scale_factor,
        )

        shape = str(magnet.get("shape", "") or "").lower()
        if shape == "round":
            diameter_mm = float(magnet.get("diameter_mm") or 0.0)
            if diameter_mm <= 0:
                return None
            radius_svg = (diameter_mm / 2.0) / float(scale_factor)
            return Point(center_x, center_y).buffer(radius_svg, resolution=32)

        if shape == "rect":
            width_mm = float(magnet.get("width_mm") or 0.0)
            height_mm = float(magnet.get("height_mm") or 0.0)
            if width_mm <= 0 or height_mm <= 0:
                return None
            half_width_svg = (width_mm / 2.0) / float(scale_factor)
            half_height_svg = (height_mm / 2.0) / float(scale_factor)
            return box(
                center_x - half_width_svg,
                center_y - half_height_svg,
                center_x + half_width_svg,
                center_y + half_height_svg,
            )

        return None

    @staticmethod
    def _build_vector_fridge_cavity_specs(
        backing_sil,
        fridge_magnets,
        bbox,
        scale_factor,
        backing_height,
        shell_thickness_mm=0.4,
    ):
        """Build clipped cavity footprint geometries with per-magnet depths."""
        if not fridge_magnets or backing_sil is None or backing_sil.is_empty:
            return []

        specs = []
        backing_bounds = backing_sil.bounds
        backing_bbox = (
            float(backing_bounds[0]),
            float(backing_bounds[1]),
            float(backing_bounds[2] - backing_bounds[0]),
            float(backing_bounds[3] - backing_bounds[1]),
        )
        for magnet in fridge_magnets:
            depth_mm = float(magnet.get("thickness_mm") or 0.0)
            if depth_mm <= 0 or depth_mm + shell_thickness_mm > backing_height + 1e-9:
                continue

            footprint = VectorProcessor._build_vector_fridge_magnet_outline(magnet, backing_bbox, scale_factor)
            if footprint is None or footprint.is_empty:
                continue

            try:
                clipped = grid_intersection(
                    backing_sil, footprint, grid_size=float(get_precision(backing_sil)),
                )
            except VECTOR_HANDLED_ERRORS:
                clipped = footprint

            clipped = VectorProcessor._extract_polygonal_geometry(make_valid(clipped))
            if clipped is None or clipped.is_empty:
                continue
            specs.append({"geometry": clipped, "depth_mm": depth_mm})

        return specs

    @staticmethod
    def _build_backing_cavity_slabs(
        backing_sil,
        backing_z_start,
        backing_height,
        cavity_specs,
        outer_side="high",
        shell_thickness_mm=0.4,
    ):
        """Split backing into full-shell, cavity, and inner slabs without mesh booleans."""
        if backing_sil is None or backing_sil.is_empty or backing_height <= 0:
            return []

        if shell_thickness_mm <= 0 or shell_thickness_mm >= backing_height:
            return [{"geometry": backing_sil, "z_offset": backing_z_start, "height": backing_height, "kind": "full"}]

        valid_specs = [
            spec
            for spec in (cavity_specs or [])
            if spec.get("geometry") is not None
            and not spec["geometry"].is_empty
            and float(spec.get("depth_mm", 0.0) or 0.0) > 0.0
            and float(spec.get("depth_mm", 0.0) or 0.0) + shell_thickness_mm <= backing_height + 1e-9
        ]
        if not valid_specs:
            return [{"geometry": backing_sil, "z_offset": backing_z_start, "height": backing_height, "kind": "full"}]

        cut_positions = [0.0, shell_thickness_mm, backing_height]
        for spec in valid_specs:
            cut_positions.append(min(backing_height, shell_thickness_mm + float(spec["depth_mm"])))
        cut_positions = sorted({round(pos, 6) for pos in cut_positions})

        slabs = []
        for inward_start, inward_end in zip(cut_positions, cut_positions[1:]):
            band_height = inward_end - inward_start
            if band_height <= 1e-9:
                continue

            if inward_start < shell_thickness_mm - 1e-9:
                band_geom = backing_sil
                band_kind = "outer_shell"
            else:
                active_geoms = [
                    spec["geometry"]
                    for spec in valid_specs
                    if shell_thickness_mm + float(spec["depth_mm"]) > inward_start + 1e-9
                ]
                if active_geoms:
                    cavity_union = unary_union(active_geoms)
                    cavity_union = VectorProcessor._extract_polygonal_geometry(make_valid(cavity_union))
                    band_geom = (grid_difference(
                        backing_sil, cavity_union, grid_size=float(get_precision(backing_sil)),
                    ) if cavity_union is not None else backing_sil)
                    band_kind = "cavity_band"
                else:
                    band_geom = backing_sil
                    band_kind = "inner_backing"

                band_geom = VectorProcessor._extract_polygonal_geometry(make_valid(band_geom))
                if band_geom is None or band_geom.is_empty:
                    continue

            if outer_side == "high":
                z_offset = backing_z_start + (backing_height - inward_end)
            else:
                z_offset = backing_z_start + inward_start

            slabs.append({"geometry": band_geom, "z_offset": z_offset, "height": band_height, "kind": band_kind})

        slabs.sort(key=lambda slab: slab["z_offset"])
        return slabs

    @staticmethod
    def _split_disconnected_shapes(shape_data):
        """Split MultiPolygon / GeometryCollection shapes into individual Polygons.

        Physical-size filtering already happens in the parser with the resolved
        SVG-to-mm scale.  This helper intentionally performs no second area
        threshold because its inputs are still expressed in SVG user units.
        Shapely already distinguishes exterior rings from holes inside
        ``Polygon`` objects, so no containment-depth analysis is needed.
        """

        def polygon_parts(geometry):
            if geometry is None or geometry.is_empty:
                return
            if geometry.geom_type == "Polygon":
                if float(geometry.area) > 0.0:
                    yield geometry
                return
            if geometry.geom_type in {"MultiPolygon", "GeometryCollection"}:
                for child in geometry.geoms:
                    yield from polygon_parts(child)

        result = []
        for item in shape_data:
            parts = tuple(polygon_parts(item.get("poly")))
            if len(parts) == 1 and parts[0] is item.get("poly"):
                result.append(item)
                continue
            result.extend({**item, "poly": polygon} for polygon in parts)
        return result

    @staticmethod
    def _extract_polygonal_geometry(geom):
        """Return only polygonal parts from arbitrary Shapely geometry.

        ``make_valid()`` can turn self-intersecting filled SVG paths into a
        ``GeometryCollection`` containing a ``MultiPolygon`` plus stray line
        segments.  The vector parser must preserve those polygonal parts
        instead of dropping the whole element.
        """
        if geom is None or geom.is_empty:
            return None
        if geom.geom_type in ("Polygon", "MultiPolygon"):
            return geom
        if geom.geom_type != "GeometryCollection":
            return None

        polygon_parts = []
        for child in geom.geoms:
            extracted = VectorProcessor._extract_polygonal_geometry(child)
            if extracted is None or extracted.is_empty:
                continue
            if extracted.geom_type == "Polygon":
                polygon_parts.append(extracted)
            elif extracted.geom_type == "MultiPolygon":
                polygon_parts.extend([poly for poly in extracted.geoms if not poly.is_empty])

        if not polygon_parts:
            return None
        if len(polygon_parts) == 1:
            return polygon_parts[0]

        try:
            merged = unary_union(polygon_parts)
            return merged if merged is not None and not merged.is_empty else MultiPolygon(polygon_parts)
        except VECTOR_FATAL_ERRORS:
            raise
        except Exception:
            return MultiPolygon(polygon_parts)

    @staticmethod
    def _parse_gradient_defs(svg_path, *, root=None):
        """Pre-parse SVG XML to extract gradient definitions.

        Returns ``{gradient_id: {type, stops, units, transform, ...}}``
        for linear and radial gradients.

        Handles ``gradientUnits``, ``gradientTransform``,
        ``xlink:href`` / ``href`` inheritance, percentage coordinate
        values, and ``stop-color`` defined via the ``style`` attribute.

        解析 SVG XML 提取渐变定义，支持坐标变换、单位、继承、
        百分比值和 style 属性中的 stop-color。
        """
        _SVG_NS = {"svg": "http://www.w3.org/2000/svg"}
        _XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
        gradients = {}
        if root is None:
            try:
                tree = ET.parse(svg_path)
                root = tree.getroot()
            except VECTOR_FATAL_ERRORS:
                raise
            except Exception:
                return gradients

        def _parse_stops(parent):
            stops = []
            for s in parent.findall("svg:stop", _SVG_NS):
                raw_off = s.get("offset", "0")
                offset = float(raw_off.rstrip("%")) / (100.0 if "%" in raw_off else 1.0)
                raw_c = s.get("stop-color")
                if not raw_c:
                    style = s.get("style", "")
                    m = re.search(r"stop-color\s*:\s*([^;]+)", style)
                    if m:
                        raw_c = m.group(1).strip()
                if not raw_c:
                    raw_c = "black"
                try:
                    c = Color(raw_c)
                    rgb = (int(c.red), int(c.green), int(c.blue))
                except VECTOR_FATAL_ERRORS:
                    raise
                except Exception:
                    rgb = (0, 0, 0)
                stops.append((offset, rgb))
            return stops

        elem_map = {}
        for tag in ("linearGradient", "radialGradient"):
            for elem in root.iter(f"{{http://www.w3.org/2000/svg}}{tag}"):
                gid = elem.get("id")
                if gid:
                    elem_map[gid] = elem

        def _resolve(gid, visited=None):
            if visited is None:
                visited = set()
            if gid in gradients:
                return gradients[gid]
            if gid not in elem_map or gid in visited:
                return None
            visited.add(gid)

            elem = elem_map[gid]
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

            href = elem.get(_XLINK_HREF) or elem.get("href")
            href_id = href.lstrip("#") if href else None
            parent = _resolve(href_id, visited) if href_id else None

            stops = _parse_stops(elem)
            if not stops and parent:
                stops = parent.get("stops", [])

            raw_units = elem.get("gradientUnits")
            if raw_units is None and parent:
                raw_units = parent.get("units")
            units = raw_units if raw_units in ("userSpaceOnUse", "objectBoundingBox") else "objectBoundingBox"

            raw_tf = elem.get("gradientTransform")
            if raw_tf is not None:
                transform = _parse_svg_transform(raw_tf)
            elif parent is not None:
                transform = parent.get("transform", np.eye(3, dtype=np.float64))
            else:
                transform = np.eye(3, dtype=np.float64)

            def _coord(attr, default):
                val = elem.get(attr)
                if val is not None:
                    return _parse_gradient_length(val, default)
                if parent is not None:
                    return parent.get(attr, default)
                return default

            if tag == "linearGradient":
                info = {
                    "type": "linear",
                    "x1": _coord("x1", 0.0),
                    "y1": _coord("y1", 0.0),
                    "x2": _coord("x2", 1.0),
                    "y2": _coord("y2", 0.0),
                    "stops": stops,
                    "units": units,
                    "transform": transform,
                }
            elif tag == "radialGradient":
                info = {
                    "type": "radial",
                    "cx": _coord("cx", 0.5),
                    "cy": _coord("cy", 0.5),
                    "r": _coord("r", 0.5),
                    "stops": stops,
                    "units": units,
                    "transform": transform,
                }
            else:
                return None

            gradients[gid] = info
            return info

        for gid in elem_map:
            _resolve(gid)

        return gradients

    @staticmethod
    def _flatten_gradient_shape(grad_info, subpath_polys, color_bands=None):
        """Convert a gradient-filled SVG element into multiple solid-color shapes.

        Algorithm (mirrors ``ChromaPrint3D::FlattenGradientShape``):
        1. Rasterise the gradient inside the element's bounding box
        2. Quantise each pixel to the nearest gradient stop colour
        3. Extract contours per stop colour via OpenCV ``findContours``
        4. Convert pixel contours back to SVG coordinate polygons

        Correctly handles ``gradientUnits`` (``objectBoundingBox`` vs
        ``userSpaceOnUse``) and ``gradientTransform``.

        Args:
            grad_info: Gradient definition dict from ``_parse_gradient_defs``.
            subpath_polys: List of Shapely Polygon objects for the element.

        Returns list of ``{poly: Polygon, color: (r,g,b)}`` dicts.
        Falls back to sampling the gradient centre colour if extraction fails.
        """
        stops = grad_info.get("stops", [])
        if not stops:
            return []

        union_poly = unary_union(subpath_polys) if subpath_polys else None
        if union_poly is None or union_poly.is_empty:
            return []

        bx0, by0, bx1, by1 = union_poly.bounds
        bw = bx1 - bx0
        bh = by1 - by0
        if bw <= 0 or bh <= 0:
            return []

        units = grad_info.get("units", "objectBoundingBox")
        transform = grad_info.get("transform", np.eye(3, dtype=np.float64))

        def _map_point(x, y):
            """Map gradient-space coords to SVG user-space coords."""
            if units == "objectBoundingBox":
                x = bx0 + x * bw
                y = by0 + y * bh
            pt = transform @ np.array([x, y, 1.0], dtype=np.float64)
            return float(pt[0]), float(pt[1])

        def _map_radius(r):
            if units == "objectBoundingBox":
                r = r * (bw + bh) * 0.5
            sx = np.sqrt(transform[0, 0] ** 2 + transform[1, 0] ** 2)
            sy = np.sqrt(transform[0, 1] ** 2 + transform[1, 1] ** 2)
            return r * (sx + sy) * 0.5

        _MAX_GRAD_PX = 2048
        px_per_unit = min(10.0, _MAX_GRAD_PX / max(bw, bh))
        img_w = max(4, int(bw * px_per_unit))
        img_h = max(4, int(bh * px_per_unit))

        ys = np.arange(img_h)[:, None]
        xs = np.arange(img_w)[None, :]
        wx = bx0 + (xs + 0.5) / px_per_unit
        wy = by0 + (ys + 0.5) / px_per_unit

        grad_type = grad_info["type"]
        if grad_type == "linear":
            gx1, gy1 = _map_point(grad_info["x1"], grad_info["y1"])
            gx2, gy2 = _map_point(grad_info["x2"], grad_info["y2"])
            dx = gx2 - gx1
            dy = gy2 - gy1
            length_sq = dx * dx + dy * dy
            if length_sq < 1e-12:
                t_map = np.zeros((img_h, img_w), dtype=np.float32)
            else:
                t_map = ((wx - gx1) * dx + (wy - gy1) * dy) / length_sq
        elif grad_type == "radial":
            cx, cy = _map_point(grad_info["cx"], grad_info["cy"])
            r_grad = _map_radius(grad_info["r"])
            if r_grad < 1e-12:
                r_grad = max(bw, bh) / 2
            t_map = np.sqrt((wx - cx) ** 2 + (wy - cy) ** 2) / r_grad
        else:
            mid_color = _sample_gradient_stops(stops, 0.5)
            return [{"poly": union_poly, "color": mid_color}]

        t_map = np.clip(t_map, 0.0, 1.0).astype(np.float32)

        canvas = np.zeros((img_h, img_w, 3), dtype=np.uint8)
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            mask = (t_map >= t0) & (t_map <= t1)
            if not np.any(mask):
                continue
            if t1 - t0 < 1e-9:
                f = np.zeros_like(t_map)
            else:
                f = (t_map - t0) / (t1 - t0)
            for ch in range(3):
                canvas[:, :, ch] = np.where(
                    mask,
                    (c0[ch] + (c1[ch] - c0[ch]) * f).astype(np.uint8),
                    canvas[:, :, ch],
                )
        below = t_map < stops[0][0]
        above = t_map > stops[-1][0]
        for ch in range(3):
            canvas[:, :, ch] = np.where(below, stops[0][1][ch], canvas[:, :, ch])
            canvas[:, :, ch] = np.where(above, stops[-1][1][ch], canvas[:, :, ch])

        try:
            band_count = int(color_bands or 0)
        except (TypeError, ValueError):
            band_count = 0
        if band_count > len(stops):
            sample_t = np.linspace(0.0, 1.0, max(2, band_count))
            stop_t = np.array([float(s[0]) for s in stops], dtype=np.float64)
            sample_t = np.unique(np.concatenate([sample_t, np.clip(stop_t, 0.0, 1.0)]))
            sampled_colors = [_sample_gradient_stops(stops, float(t)) for t in sample_t]
            stop_colors = np.unique(np.array(sampled_colors, dtype=np.int16), axis=0)
        else:
            stop_colors = np.array([s[1] for s in stops], dtype=np.int16)
        flat = canvas.reshape(-1, 3).astype(np.int32)
        best_dist = np.full((flat.shape[0],), np.iinfo(np.int32).max, dtype=np.int32)
        best_idx = np.zeros((flat.shape[0],), dtype=np.int32)
        for si, scolor in enumerate(stop_colors.astype(np.int32, copy=False)):
            diff = flat - scolor
            dist = np.sum(diff * diff, axis=1, dtype=np.int32)
            better = dist < best_dist
            best_dist[better] = dist[better]
            best_idx[better] = si
        quantized_idx = best_idx.reshape(img_h, img_w)

        result_shapes = []
        for si, scolor_arr in enumerate(stop_colors):
            scolor = tuple(int(c) for c in scolor_arr)
            mask = (quantized_idx == si).astype(np.uint8) * 255
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                if cv2.contourArea(cnt) < 4:
                    continue
                approx = cv2.approxPolyDP(cnt, 1.0, True)
                if len(approx) < 3:
                    continue
                svg_coords = [(bx0 + pt[0] / px_per_unit, by0 + pt[1] / px_per_unit) for pt in approx[:, 0, :]]
                poly = Polygon(svg_coords)
                if poly.is_valid and not poly.is_empty and poly.area > 0:
                    try:
                        clipped = poly.intersection(union_poly)
                    except Exception:
                        clipped = poly
                    if not clipped.is_empty:
                        result_shapes.append({"poly": clipped, "color": scolor})

        if not result_shapes:
            mid_color = _sample_gradient_stops(stops, 0.5)
            return [{"poly": union_poly, "color": mid_color}]

        return result_shapes

    # ── Public entry points ─────────────────────────────────────────────

    def analyze_svg(
        self,
        svg_path: str,
        target_width_mm: float,
        color_replacements: dict | list[dict] | None = None,
        progress_fn=None,
    ) -> VectorAnalysis:
        """Parse, clip, and color-match an SVG — shared by preview and mesh.
        解析、裁剪、配色 SVG — 预览与 3D 构建共享此结果。

        Args:
            svg_path:         Path to SVG file.
            target_width_mm:  Physical width in mm for the output model.
            color_replacements: Optional legacy ``{hex: hex}`` map or API
                ``ColorReplacementItem`` records. Structured records retain
                their ``matched_hex`` identity for native dynamic materials.
            progress_fn:      Optional progress callback.

        Returns:
            A ``VectorAnalysis`` containing all intermediate data needed
            by ``build_mesh`` and ``render_preview``.
        """
        _log.debug("Analyzing: %s", svg_path)
        stage_timings = {}
        svg_coordinate_domain = None
        expand_stroke_to_fill = bool(getattr(self, "expand_stroke_to_fill", False))

        # === Stage 1+2: Parse & Occlusion clip (with cache) ===
        cache_key = None
        cached_entry = None
        try:
            cache_key = _vector_parse_clip_cache_key(
                svg_path,
                target_width_mm=target_width_mm,
                sampling_precision=self.sampling_precision,
                expand_stroke_to_fill=expand_stroke_to_fill,
                gradient_color_bands=getattr(self, "gradient_color_bands", None),
            )
            cached_entry = _VECTOR_PARSE_CLIP_CACHE.get(cache_key)
            if cached_entry is not None:
                _VECTOR_PARSE_CLIP_CACHE.pop(cache_key, None)
                _VECTOR_PARSE_CLIP_CACHE[cache_key] = cached_entry
        except VECTOR_HANDLED_ERRORS:
            cache_key = None

        if cached_entry is None and cache_key is not None:
            artifact_path = getattr(self, "_parse_clip_cache_path", None)
            cached_entry = _load_vector_parse_clip_cache_artifact(
                artifact_path,
                cache_key,
            )
            if cached_entry is not None:
                _VECTOR_PARSE_CLIP_CACHE[cache_key] = cached_entry
                while len(_VECTOR_PARSE_CLIP_CACHE) > _VECTOR_PARSE_CLIP_CACHE_MAX:
                    _VECTOR_PARSE_CLIP_CACHE.pop(next(iter(_VECTOR_PARSE_CLIP_CACHE)))

        if cached_entry is not None:
            working_entry = _copy_vector_parse_clip_cache_entry(cached_entry)
            shape_data = working_entry["shape_data"]
            clipped_shapes = working_entry["clipped_shapes"]
            silhouette = cached_entry["silhouette"]
            image_vectorizer_bounds = cached_entry.get("image_vectorizer_bounds")
            scale_factor = cached_entry["scale_factor"]
            bbox = cached_entry["bbox"]
            svg_coordinate_domain = working_entry.get("svg_coordinate_domain")
            self.parse_warnings = list(
                working_entry.get("parse_warnings") or []
            )
            stage_timings.update(
                working_entry.get("geometry_stage_timings") or {}
            )
            stage_timings["parse_s"] = 0.0
            stage_timings["occlusion_s"] = 0.0
            stage_timings["contour_normalize_s"] = 0.0
            stage_timings["native_svg_s"] = 0.0
            stage_timings["native_result_conversion_s"] = 0.0
            stage_timings["native_recorder_s"] = 0.0
            stage_timings["native_kernel_s"] = 0.0
            stage_timings["native_bounds_s"] = 0.0
            stage_timings["native_replay_s"] = 0.0
            stage_timings["native_topology_s"] = 0.0
            stage_timings["native_normalize_raw_s"] = 0.0
            stage_timings["native_composite_s"] = 0.0
            stage_timings["native_normalize_visible_s"] = 0.0
            stage_timings["native_export_s"] = 0.0
            stage_timings["native_binding_conversion_s"] = 0.0
            stage_timings["native_adapter_s"] = 0.0
            stage_timings["native_cache_hit"] = (
                stage_timings.get("geometry_backend") == "native"
            )
            stage_timings.setdefault("geometry_backend", "legacy")
            stage_timings.setdefault("native_fallback_reason", "")
            _log.debug("Parse/clip cache hit: %s", os.path.basename(svg_path))
            _log.debug("Parsed %s shapes. Scale: %.4f", len(shape_data), scale_factor)
            _log.debug("After occlusion clip: %s non-overlapping shapes", len(clipped_shapes))
        else:
            native_attempt_started = time.perf_counter()
            native_outcome = native_svg_adapter.analyze_native_svg(
                svg_path,
                target_width_mm,
                self.sampling_precision,
                expand_stroke_to_fill=expand_stroke_to_fill,
            )
            native_attempt_seconds = time.perf_counter() - native_attempt_started
            if isinstance(native_outcome, native_svg_adapter.NativeSvgGeometry):
                shape_data = native_outcome.shape_data
                clipped_shapes = native_outcome.clipped_shapes
                silhouette = native_outcome.silhouette
                image_vectorizer_bounds = native_outcome.image_vectorizer_bounds
                scale_factor = native_outcome.scale_factor
                bbox = native_outcome.bbox
                svg_coordinate_domain = native_outcome.svg_coordinate_domain
                self.parse_warnings = []
                stage_timings.update(native_outcome.stage_timings)
                stage_timings["native_svg_s"] = native_attempt_seconds
                stage_timings["parse_s"] = stage_timings.get(
                    "native_recorder_s", 0.0
                )
                stage_timings["occlusion_s"] = stage_timings.get(
                    "native_kernel_s", 0.0
                )
                stage_timings["contour_normalize_s"] = 0.0
                stage_timings["native_cache_hit"] = False
                _log.debug(
                    "Native SVG geometry selected",
                    extra={
                        "event": "vector_native_svg_done",
                        "path": os.path.basename(svg_path),
                        "native_version": native_outcome.native_version,
                        "native_schema_version": (
                            native_outcome.native_schema_version
                        ),
                        "shape_count": len(clipped_shapes),
                        "duration_s": round(native_attempt_seconds, 6),
                    },
                )
            else:
                stage_timings.update(
                    {
                        "geometry_backend": "legacy",
                        "native_svg_s": native_attempt_seconds,
                        "native_result_conversion_s": 0.0,
                        "native_fallback_reason": native_outcome.reason_code,
                        "native_version": native_outcome.native_version,
                        "native_cache_hit": False,
                    }
                )
                _log.debug(
                    "Native SVG requested whole-document fallback",
                    extra={
                        "event": "vector_native_svg_fallback",
                        "path": os.path.basename(svg_path),
                        "reason_code": native_outcome.reason_code,
                        "native_version": native_outcome.native_version,
                        "duration_s": round(native_attempt_seconds, 6),
                    },
                )

                t0 = time.perf_counter()
                had_parse_policy = hasattr(self, "_parse_expand_stroke_to_fill")
                previous_parse_policy = getattr(
                    self, "_parse_expand_stroke_to_fill", None
                )
                self._parse_expand_stroke_to_fill = expand_stroke_to_fill
                try:
                    shape_data, scale_factor, bbox = self._parse_svg(
                        svg_path, target_width_mm
                    )
                    image_vectorizer_bounds = getattr(
                        self, "_last_image_vectorizer_bounds", None
                    )
                finally:
                    if had_parse_policy:
                        self._parse_expand_stroke_to_fill = previous_parse_policy
                    else:
                        delattr(self, "_parse_expand_stroke_to_fill")
                if not shape_data:
                    raise ValueError("No valid filled shapes found in SVG.")
                stage_timings["parse_s"] = time.perf_counter() - t0
                _log.debug(
                    "Parsed %s shapes. Scale: %.4f",
                    len(shape_data),
                    scale_factor,
                )

                t0 = time.perf_counter()
                _pre_area = sum(
                    item["poly"].area
                    for item in shape_data
                    if item["poly"] is not None
                )
                clipped_shapes, silhouette = self._clip_occlusion(
                    shape_data, return_silhouette=True
                )
                _clip_area = sum(
                    item["geometry"].area
                    for item in clipped_shapes
                    if item["geometry"] is not None
                )
                _log.debug(
                    "_clip_occlusion: %s -> %s shapes, area %.1f -> %.1f "
                    "(%.1f%%)",
                    len(shape_data),
                    len(clipped_shapes),
                    _pre_area,
                    _clip_area,
                    (_clip_area / _pre_area * 100) if _pre_area > 0 else 0.0,
                )

                normalize_started = time.perf_counter()
                post_clip = VectorProcessor._postprocess_clipped_shapes(
                    clipped_shapes
                )
                stage_timings["contour_normalize_s"] = (
                    time.perf_counter() - normalize_started
                )
                _norm_area = sum(
                    item["geometry"].area
                    for item in post_clip
                    if item["geometry"] is not None
                )
                _log.debug(
                    "post-clip normalize: %s -> %s shapes, area %.1f -> %.1f",
                    len(clipped_shapes),
                    len(post_clip),
                    _clip_area,
                    _norm_area,
                )
                clipped_shapes = post_clip

                split_input = [
                    {"poly": item["geometry"], "color": item["color"]}
                    for item in clipped_shapes
                ]
                split_output = VectorProcessor._split_disconnected_shapes(
                    split_input
                )
                clipped_shapes = [
                    {
                        "geometry": item["poly"],
                        "color": item["color"],
                        "draw_order": index,
                    }
                    for index, item in enumerate(split_output)
                ]
                _split_area = sum(
                    item["geometry"].area
                    for item in clipped_shapes
                    if item["geometry"] is not None
                )
                _log.debug(
                    "split disconnected: %s -> %s shapes, area %.1f -> %.1f",
                    len(post_clip),
                    len(clipped_shapes),
                    _norm_area,
                    _split_area,
                )
                stage_timings["occlusion_s"] = time.perf_counter() - t0
                _log.debug(
                    "After occlusion clip: %s non-overlapping shapes",
                    len(clipped_shapes),
                )

            if cache_key is not None:
                cache_entry = {
                    "shape_data": shape_data,
                    "clipped_shapes": clipped_shapes,
                    "silhouette": silhouette,
                    "image_vectorizer_bounds": image_vectorizer_bounds,
                    "scale_factor": scale_factor,
                    "bbox": bbox,
                    "svg_coordinate_domain": svg_coordinate_domain,
                    "parse_warnings": list(
                        getattr(self, "parse_warnings", None) or []
                    ),
                    "geometry_stage_timings": dict(stage_timings),
                }
                _VECTOR_PARSE_CLIP_CACHE[cache_key] = _copy_vector_parse_clip_cache_entry(cache_entry)
                while len(_VECTOR_PARSE_CLIP_CACHE) > _VECTOR_PARSE_CLIP_CACHE_MAX:
                    _VECTOR_PARSE_CLIP_CACHE.pop(next(iter(_VECTOR_PARSE_CLIP_CACHE)))

        # Keep pure parse caches independent of compensation settings. Apply the
        # optional edit once, before both material mapping and 2D preview output.
        if bool(getattr(self, "svg_hole_compensation_enabled", False)):
            from core.svg_hole_compensation import (
                compensate_svg_regions, compensate_svg_regions_in_domain,
            )

            try:
                compensate = (compensate_svg_regions_in_domain
                              if svg_coordinate_domain is not None else compensate_svg_regions)
                coordinate_options = ({"domain": svg_coordinate_domain}
                                      if svg_coordinate_domain is not None
                                      else {"scale_factor": scale_factor})
                compensated = compensate(
                    clipped_shapes,
                    silhouette=silhouette,
                    **coordinate_options,
                    max_hole_area_mm2=self.svg_hole_max_area_mm2,
                    max_hole_width_mm=self.svg_hole_max_width_mm,
                )
            except ImportError as exc:
                raise CoreDependencyError(str(exc)) from exc
            clipped_shapes = compensated.regions
            silhouette = compensated.silhouette
            stage_timings["svg_hole_compensation_s"] = compensated.elapsed_seconds
            stage_timings["svg_holes_filled"] = compensated.filled_holes
            stage_timings["svg_hole_added_area_mm2"] = compensated.added_area_mm2

        # === Stage 3: Resolve color system config ===
        # --- Diagnostic: geometry fingerprint for 5-vs-7 layer comparison ---
        _unique_colors_in_shapes = set()
        _total_geom_area = 0.0
        for _item in clipped_shapes:
            _c = _item.get("color")
            if _c:
                try:
                    _unique_colors_in_shapes.add((int(_c[0]), int(_c[1]), int(_c[2])))
                except (TypeError, IndexError, ValueError):
                    pass
            _g = _item.get("geometry")
            if _g is not None and not _g.is_empty:
                _total_geom_area += float(_g.area)
        _log.debug(
            "analyze_svg geometry fingerprint: shapes=%d unique_colors=%d total_area=%.2f "
            "gradient_bands=%s layer_count=%s cache_hit=%s",
            len(clipped_shapes),
            len(_unique_colors_in_shapes),
            _total_geom_area,
            getattr(self, "gradient_color_bands", None),
            getattr(self.img_processor, "layer_count", "?"),
            cached_entry is not None,
            extra={
                "event": "vector_diag_geometry_fingerprint",
                "shape_count": len(clipped_shapes),
                "unique_color_count": len(_unique_colors_in_shapes),
                "total_area": round(_total_geom_area, 2),
                "gradient_color_bands": getattr(self, "gradient_color_bands", None),
                "layer_count": getattr(self.img_processor, "layer_count", None),
                "cache_hit": cached_entry is not None,
            },
        )
        # In material-archive mode the matcher carries a pre-built
        # ``color_conf`` derived from the materials list. The LUT path
        # (``LuminaImageProcessor``) does not expose this attribute, so
        # we fall back to the historical ``ColorSystem.get`` lookup
        # there. ``num_layers`` from material mode is taken from the
        # matcher so the recipe length matches the user's configured
        # layer_count instead of the printer-config default.
        # 耗材档案 matcher 自带 color_conf；LUT 路径维持原行为。
        material_color_conf = getattr(self.img_processor, "color_conf", None)
        if material_color_conf is not None:
            color_conf = dict(material_color_conf)
            preview_colors = dict(getattr(self.img_processor, "preview_colors", color_conf.get("preview") or {}))
            slot_names = list(getattr(self.img_processor, "slot_names", color_conf.get("slots") or []))
            num_channels = len(slot_names)
            num_layers = int(
                getattr(self.img_processor, "layer_count", PrinterConfig.COLOR_LAYERS)
            )
        else:
            is_six_color = len(self.img_processor.lut_rgb) == 1296
            if is_six_color:
                _log.debug("Auto-detected 6-Color LUT. Forcing 6-Color mode.")
                color_conf = ColorSystem.SIX_COLOR
                self.color_mode = "6-Color"
            else:
                color_conf = ColorSystem.get(self.color_mode)

            slot_names = color_conf["slots"]
            preview_colors = dict(color_conf["preview"])
            num_channels = len(slot_names)
            num_layers = color_conf.get("layer_count", PrinterConfig.COLOR_LAYERS)

        # For any LUT that carries explicit palette metadata (Merged JSON,
        # reverse-inferred native_bundle .json / .msgpack, etc.), override
        # slot_names and preview_colors from the LUT palette so the vector
        # engine uses the LUT's own color system instead of the stale UI
        # ``color_mode`` preset. Mirrors the raster pipeline logic in S01.
        #
        # 当 LUT 自带调色板元数据（Merged JSON/NPZ、反推 LUT 的 .json/.msgpack 等）
        # 时，用调色板真实条目覆盖 slot_names / preview_colors，避免继承上一次
        # UI 颜色模式（例如 4-Color CMYW）的预设槽位导致串色；同时沿用
        # ``build_palette_preview_colors`` 的规范颜色名兜底，保证 hex_color 缺省
        # 的 ColorDB 条目也能拿到正确 RGBA。
        lut_path = self.img_processor.lut_path
        if lut_path.endswith((".json", ".msgpack", ".npz")):
            try:
                from utils.lut_manager import LUTManager
                from core.pipeline.preview_color_utils import build_palette_preview_colors

                _, _, lut_meta = LUTManager.load_lut_with_metadata(lut_path)
                if lut_meta.palette:
                    palette_slot_names, palette_preview_colors = build_palette_preview_colors(
                        lut_meta.palette, color_conf
                    )
                    slot_names = palette_slot_names
                    preview_colors = dict(palette_preview_colors)
                    num_channels = len(slot_names)
                    color_conf = dict(color_conf)
                    color_conf["slots"] = slot_names
                    color_conf["preview"] = preview_colors
                    _log.debug("LUT palette override: %s", slot_names)
            except Exception as e:
                _log.warning(
                    "Failed to extract vector LUT palette",
                    extra={
                        "event": "vector_lut_palette_extract_failed",
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "path": str(lut_path),
                    },
                )

        # Material-archive matcher needs to pre-solve every unique fill
        # colour before ``_match_colors`` runs its KDTree query, so the
        # KDTree is populated and ``lut_rgb`` / ``ref_stacks`` carry the
        # solver-derived rows. The hook is opt-in (``solve_for_fills``
        # is only present on :class:`MaterialVectorMatcher`); the LUT
        # path skips it transparently.
        # 耗材档案 matcher 在 _match_colors 之前批量求解填充色，保证
        # KDTree / lut_rgb / ref_stacks 已就绪；LUT 模式没有该方法，
        # 透明跳过。
        solve_for_clipped_shapes = getattr(
            self.img_processor,
            "solve_for_clipped_shapes",
            None,
        )
        solve_for_fills = getattr(self.img_processor, "solve_for_fills", None)
        stage_timings["fill_dedup_s"] = 0.0
        stage_timings["material_solve_s"] = 0.0
        t0 = time.perf_counter()
        color_replacements = _rematch_static_vector_replacement_records(
            color_replacements,
            self,
        )
        (
            targets_by_matched,
            targets_by_source,
            legacy_replacements,
        ) = _normalise_vector_replacement_input(color_replacements)
        dynamic_replacement_projection = bool(
            (targets_by_matched or targets_by_source)
            and callable(solve_for_clipped_shapes)
            and bool(
                getattr(self.img_processor, "dynamic_layer_count_enabled", False)
            )
        )

        # ``replacement_regions`` identifies a palette match, not always a
        # single source SVG fill.  In dynamic material mode, first establish
        # that palette identity from the original geometry, then project every
        # matching shape to its user-selected target and solve the final table.
        # The second solve therefore owns the metadata/KDTree consumed by
        # preview, GLB and 3MF generation.
        if dynamic_replacement_projection and clipped_shapes:
            material_solve_t0 = time.perf_counter()
            solve_for_clipped_shapes(clipped_shapes, scale_factor=scale_factor)
            stage_timings["material_solve_s"] += (
                time.perf_counter() - material_solve_t0
            )
            preflight_input_shapes = self._with_near_fill_match_queries(
                clipped_shapes
            )
            preflight_matched_shapes = self._match_colors(
                preflight_input_shapes,
                None,
                num_channels,
                num_layers=num_layers,
            )
            match_input_shapes, projected_count = _project_dynamic_replacement_targets(
                preflight_input_shapes,
                preflight_matched_shapes,
                targets_by_matched,
                targets_by_source,
            )
            if projected_count:
                material_solve_t0 = time.perf_counter()
                solve_for_clipped_shapes(
                    match_input_shapes,
                    scale_factor=scale_factor,
                )
                stage_timings["material_solve_s"] += (
                    time.perf_counter() - material_solve_t0
                )
                # Do not apply the same palette remap after the final KDTree
                # lookup: final ``match_color`` already is the exact target.
                matched_shapes = self._match_colors(
                    match_input_shapes,
                    None,
                    num_channels,
                    num_layers=num_layers,
                )
            else:
                matched_shapes = preflight_matched_shapes
        else:
            replacement_manager = None
            if legacy_replacements:
                try:
                    from core.color_replacement import ColorReplacementManager

                    replacement_manager = ColorReplacementManager.from_dict(
                        legacy_replacements
                    )
                except VECTOR_HANDLED_ERRORS as e:
                    _log.warning(
                        "Failed to load vector color replacements",
                        extra={
                            "event": "vector_color_replacements_load_failed",
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                            "replacement_count": len(color_replacements or []),
                        },
                    )

            if callable(solve_for_clipped_shapes) and clipped_shapes:
                material_solve_t0 = time.perf_counter()
                solve_for_clipped_shapes(
                    clipped_shapes,
                    scale_factor=scale_factor,
                )
                stage_timings["material_solve_s"] += (
                    time.perf_counter() - material_solve_t0
                )
            elif solve_for_fills is not None and clipped_shapes:
                fill_dedup_t0 = time.perf_counter()
                unique_fills_set: set = set()
                for item in clipped_shapes:
                    color = item.get("color")
                    if color is None:
                        continue
                    try:
                        unique_fills_set.add(
                            (int(color[0]), int(color[1]), int(color[2]))
                        )
                    except (TypeError, IndexError, ValueError):
                        continue
                stage_timings["fill_dedup_s"] += (
                    time.perf_counter() - fill_dedup_t0
                )
                if unique_fills_set:
                    material_solve_t0 = time.perf_counter()
                    solve_for_fills(sorted(unique_fills_set))
                    stage_timings["material_solve_s"] += (
                        time.perf_counter() - material_solve_t0
                    )
                    # NOTE: small-shape snap is disabled for material-archive mode.
                    # The delta_e heuristic incorrectly triggers when the material
                    # set cannot physically reproduce dark colours, causing
                    # unrelated small shapes to be snapped to the dominant anchor
                    # colour (e.g. black → skin tone). See PR #177 regression.
                    # 耗材档案模式禁用小 shape 吸附：材料集缺少深色时 delta_e
                    # 判断会误触发，把深色小碎片全部吸附到大面积锚点色。

            match_input_shapes = self._with_near_fill_match_queries(clipped_shapes)
            matched_shapes = self._match_colors(
                match_input_shapes,
                replacement_manager,
                num_channels,
                num_layers=num_layers,
            )
        if (
            stage_timings.get("geometry_backend") != "native"
            and not getattr(self, "svg_hole_compensation_enabled", False)
        ):
            min_hole_area_mm2 = float(
                getattr(VectorConfig, "MIN_COLOR_HOLE_AREA_MM2", 1.0)
            )
            for idx, item in enumerate(clipped_shapes):
                filtered_geometry = VectorProcessor._filter_backing_holes(
                    item["geometry"],
                    min_hole_area_mm2=min_hole_area_mm2,
                )
                item["geometry"] = filtered_geometry
                if idx < len(matched_shapes):
                    matched_shapes[idx]["geometry"] = filtered_geometry
        stage_timings["color_match_s"] = max(
            0.0,
            time.perf_counter()
            - t0
            - stage_timings["fill_dedup_s"]
            - stage_timings["material_solve_s"],
        )
        _log.debug("Matched %s shapes to LUT recipes", len(matched_shapes))
        legacy_stroke_only_shapes = sum(
            1 for item in shape_data if item.get("source_kind") == "stroke_only"
        )
        fill_eq_stroke_double_buffer = sum(
            1 for item in shape_data if item.get("same_color_stroke_double_buffer")
        )
        stroke_policy_message = (
            "Stroke policy: "
            f"expand={expand_stroke_to_fill} "
            f"legacy_stroke_only_shapes={legacy_stroke_only_shapes} "
            f"fill_eq_stroke_double_buffer={fill_eq_stroke_double_buffer}"
        )
        stroke_policy_extra = {
            "event": "vector_stroke_policy",
            "expand": expand_stroke_to_fill,
            "legacy_stroke_only_shapes": legacy_stroke_only_shapes,
            "fill_eq_stroke_double_buffer": fill_eq_stroke_double_buffer,
        }
        _log.debug(stroke_policy_message, extra=stroke_policy_extra)

        return VectorAnalysis(
            shape_data=shape_data,
            clipped_shapes=clipped_shapes,
            matched_shapes=matched_shapes,
            silhouette=silhouette,
            scale_factor=scale_factor,
            bbox=bbox,
            color_conf=color_conf,
            slot_names=slot_names,
            num_channels=num_channels,
            num_layers=num_layers,
            preview_colors=preview_colors,
            stage_timings=stage_timings,
            image_vectorizer_bounds=image_vectorizer_bounds,
            svg_coordinate_domain=svg_coordinate_domain,
            material_dynamic_layer_info=getattr(
                self.img_processor,
                "dynamic_layer_info",
                None,
            ),
            material_solver_info=getattr(
                self.img_processor,
                "material_solver_info",
                None,
            ),
        )

    def build_mesh(
        self,
        analysis: VectorAnalysis,
        thickness_mm: float,
        structure_mode: str = "Single-sided",
        progress_fn=None,
        backing_color_id: int = 0,
        enable_relief: bool = False,
        height_mode: str = "color",
        color_height_map: dict[str, float] | None = None,
        heightmap_path: str | None = None,
        heightmap_max_height: float | None = None,
    ) -> trimesh.Scene:
        """Extrude analyzed vector shapes into a trimesh Scene.
        将分析后的矢量形状挤出为 trimesh Scene。

        Args:
            analysis:       Result from ``analyze_svg``.
            thickness_mm:   Backing (spacer) thickness in mm.
            structure_mode: "Single-sided" or "Double-sided".
            progress_fn:    Optional progress callback.
            backing_color_id: Material slot index to assign to the ``Board``
                backing geometry. Defaults to ``0`` to preserve historical
                behaviour; callers driving material-archive or separate-
                backing flows pass the user-selected backing slot so the
                preview/export actually reflects the chosen material.
                （底板几何体使用的材质槽索引，默认 0 以保持历史行为；
                耗材档案或分离底板流程会传入用户选择的底板槽位，
                预览/导出才能反映实际选中的耗材颜色。）
            enable_relief: Build variable-height backing from existing SVG
                regions.（是否按现有 SVG 色块生成可变高度底板。）
            height_mode: ``color`` or ``heightmap`` height source.
                （高度来源：按颜色或高度图。）
            color_height_map: Matched RGB hex to absolute model height in mm.
                （匹配色十六进制值到模型绝对高度的映射。）
            heightmap_path: Optional grayscale heightmap path.
                （可选灰度高度图路径。）
            heightmap_max_height: Maximum heightmap model height in mm.
                （高度图模型最大高度，单位毫米。）

        Returns:
            A ``trimesh.Scene`` with one geometry per material slot.
        """
        _log.debug("Building mesh: structure_mode=%s", structure_mode)
        stage_timings = dict(analysis.stage_timings)
        t_total_start = time.perf_counter()

        matched_shapes = analysis.matched_shapes
        scale_factor = analysis.scale_factor
        bbox = analysis.bbox
        slot_names = analysis.slot_names
        num_channels = analysis.num_channels
        num_layers = analysis.num_layers
        preview_colors = analysis.preview_colors
        enable_fridge_magnet = bool(getattr(self, "enable_fridge_magnet", False))
        fridge_magnets = list(getattr(self, "fridge_magnets", []) or [])
        enable_coating = bool(getattr(self, "enable_coating", False))
        coating_height_mm = getattr(self, "coating_height_mm", 0.08)
        enable_outline = bool(getattr(self, "enable_outline", False))
        outline_width_mm = getattr(self, "outline_width_mm", 0.0)
        merge_backing_into_material = bool(
            getattr(self, "_merge_backing_into_material", False)
        )
        structure_mode_value = str(getattr(structure_mode, "value", structure_mode))
        is_double_sided = (
            "双面" in structure_mode_value or "Double" in structure_mode_value
        )
        is_5color = "5-Color Extended" in self.color_mode
        is_single_sided = (
            "单面" in structure_mode_value or "Single" in structure_mode_value
        )
        try:
            layer_h = float(
                getattr(self, "layer_height_mm", PrinterConfig.LAYER_HEIGHT)
            )
        except (TypeError, ValueError):
            layer_h = float(PrinterConfig.LAYER_HEIGHT)
        if not math.isfinite(layer_h) or layer_h <= 0:
            layer_h = float(PrinterConfig.LAYER_HEIGHT)

        display_layer_count = int(num_layers)
        if display_layer_count <= 0:
            raise ValueError("Vector display layer count must be positive")
        canvas_width_mm = float(bbox[2]) * float(scale_factor)
        canvas_height_mm = float(bbox[3]) * float(scale_factor)
        geometry_grid_mm = resolve_vector_writer_grid_mm(
            max(abs(canvas_width_mm), abs(canvas_height_mm))
        )
        prepared_grids = {float(item[PRINT_GRID_KEY]) for item in matched_shapes if PRINT_GRID_KEY in item}
        if prepared_grids:
            if len(prepared_grids) != 1 or any("print_geometry" not in item for item in matched_shapes):
                raise ValueError("Vector analysis contains mixed print coordinate domains")
            geometry_grid_mm = next(iter(prepared_grids))
        coordinate_domain = LayeredCoordinateDomain.from_canvas_and_layers(
            width_mm=canvas_width_mm,
            height_mm=canvas_height_mm,
            xy_grid_mm=geometry_grid_mm,
            layer_heights_mm=(layer_h,) * display_layer_count,
        )
        geometry_policy = VectorLayerGeometryPolicy(
            grid_mm=coordinate_domain.xy_grid_mm
        )
        analysis.coordinate_domain = coordinate_domain
        if isinstance(getattr(analysis, "svg_coordinate_domain", None), SvgCoordinateDomain) and not prepared_grids:
            projection_started = time.perf_counter()
            projected = project_print_regions(
                [item["geometry"] for item in matched_shapes],
                mm_per_unit=scale_factor,
                grid_mm=geometry_grid_mm,
                metrics=stage_timings,
            )
            stage_timings["print_projection_s"] = time.perf_counter() - projection_started
            matched_shapes = [
                {**item, "print_geometry": geometry, PRINT_GRID_KEY: geometry_grid_mm}
                for item, geometry in zip(matched_shapes, projected, strict=True)
            ]

        raw_silhouette = getattr(analysis, "silhouette", None)
        if raw_silhouette is not None and not getattr(
            raw_silhouette,
            "is_empty",
            True,
        ):
            auxiliary_geometries = (raw_silhouette,)
        else:
            auxiliary_geometries = tuple(
                item.get("geometry")
                for item in (getattr(analysis, "clipped_shapes", None) or ())
                if isinstance(item, dict)
                and item.get("geometry") is not None
                and not getattr(item.get("geometry"), "is_empty", True)
            )
        try:
            has_backing = float(thickness_mm) > 0.0
        except (TypeError, ValueError, OverflowError):
            has_backing = False
        relief_replaces_uniform_backing = (
            enable_relief and is_single_sided and not is_5color
        )
        auxiliary_run_count = 0
        if has_backing:
            if relief_replaces_uniform_backing:
                auxiliary_run_count += _estimate_relief_backing_run_count(
                    matched_shapes,
                    num_layers=num_layers,
                    layer_height_mm=layer_h,
                    default_height_mm=thickness_mm,
                    height_mode=height_mode,
                    color_height_map=color_height_map,
                    heightmap_max_height=heightmap_max_height,
                )
            else:
                auxiliary_run_count += 1
            if enable_fridge_magnet:
                auxiliary_run_count += 2 * len(fridge_magnets)
        if enable_coating:
            auxiliary_run_count += (
                2 if is_double_sided and not is_5color else 1
            )

        rss_preflight = get_process_rss_bytes()
        current_rss_bytes = int(rss_preflight or 0)
        shape_count = sum(
            1
            for item in (matched_shapes or ())
            if isinstance(item, dict)
            and item.get("geometry") is not None
            and not getattr(item.get("geometry"), "is_empty", True)
        )
        coordinate_count = 0
        if get_num_coordinates is not None:
            for item in matched_shapes or ():
                geometry = item.get("geometry") if isinstance(item, dict) else None
                if geometry is None:
                    continue
                try:
                    coordinate_count += int(get_num_coordinates(geometry))
                except (TypeError, ValueError, OverflowError):
                    continue
        self.last_vector_mesh_memory_profile = {
            "stage": "preflight",
            "shape_count": int(shape_count),
            "coordinate_count": int(coordinate_count),
            "current_rss_bytes": current_rss_bytes,
        }
        stage_timings.update(
            {
                "vector_mesh_shape_count": int(shape_count),
                "vector_mesh_coordinate_count": int(coordinate_count),
                "vector_mesh_rss_preflight_bytes": current_rss_bytes,
            }
        )
        silhouette = _physical_backing_geometry(analysis)

        # === Stage 5: Run-length extrude per channel ===
        if enable_relief and (is_5color or not is_single_sided):
            raise ValueError(
                "Native SVG relief supports only single-sided, non-5-Color "
                "Extended models."
            )
        mirror_transform = None
        if is_single_sided and not is_5color and not enable_relief:
            mirror_transform = np.array(
                [
                    [-1.0, 0.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                    [0.0, 0.0, 0.0, 1.0],
                ]
            )
        backing_layer_count = max(1, int(round(thickness_mm / layer_h)))
        backing_height = backing_layer_count * layer_h
        deferred_vector_slabs = False

        t0 = time.perf_counter()
        if enable_relief and is_single_sided and not is_5color:
            meshes_by_slot = self._build_relief_meshes(
                matched_shapes=matched_shapes,
                num_layers=num_layers,
                layer_h=layer_h,
                num_channels=num_channels,
                slot_names=slot_names,
                scale_factor=scale_factor,
                backing_color_id=backing_color_id,
                default_height_mm=thickness_mm,
                height_mode=height_mode,
                color_height_map=color_height_map,
                heightmap_path=heightmap_path,
                heightmap_max_height=heightmap_max_height,
                bbox=bbox,
                enable_fridge_magnet=enable_fridge_magnet,
                fridge_magnets=fridge_magnets,
                merge_backing_into_material=merge_backing_into_material,
                geometry_policy=geometry_policy,
            )
        elif is_5color:
            meshes_by_slot = self._run_length_extrude(
                matched_shapes=matched_shapes,
                num_layers=num_layers,
                layer_h=layer_h,
                num_channels=num_channels,
                slot_names=slot_names,
                scale_factor=scale_factor,
                face_up=True,
                optical_z_base=backing_height,
                defer_materialization=True,
                geometry_policy=geometry_policy,
            )
            deferred_vector_slabs = True
            _log.debug(
                "5-Color face-up: %s optical layers above %.2fmm backing",
                num_layers,
                backing_height,
            )
        else:
            meshes_by_slot = self._run_length_extrude(
                matched_shapes=matched_shapes,
                num_layers=num_layers,
                layer_h=layer_h,
                num_channels=num_channels,
                slot_names=slot_names,
                scale_factor=scale_factor,
                defer_materialization=True,
                geometry_policy=geometry_policy,
            )
            deferred_vector_slabs = True
        stage_timings["extrude_bottom_s"] = time.perf_counter() - t0
        stage_timings["vector_mesh_rss_after_extrude_bottom_bytes"] = int(
            get_process_rss_bytes() or 0
        )

        # === Stage 6: Backing layer from silhouette ===
        t0 = time.perf_counter()
        structure = resolve_structure_plan(
            analysis, float(outline_width_mm) if enable_outline else 0.0,
        )
        # Extrusion and cavity helpers still consume SVG units.
        silhouette = structure.in_units(structure.body, scale_factor)

        if is_5color:
            backing_z_start = 0
        else:
            backing_z_start = num_layers * layer_h

        backing_sil = None
        if (
            not (enable_relief and is_single_sided and not is_5color)
            and thickness_mm > 0
            and silhouette is not None
            and not silhouette.is_empty
        ):
            _log.debug("Generating backing: %s layers (%smm)", backing_layer_count, thickness_mm)
            backing_sil = silhouette
            backing_height = backing_layer_count * layer_h
            gap_offset = BASE_COLOR_GAP_MM if not is_5color else 0.0
            outer_side = "low" if is_5color else "high"
            cavity_specs = []
            if enable_fridge_magnet:
                cavity_specs = self._build_vector_fridge_cavity_specs(
                    backing_sil=backing_sil,
                    fridge_magnets=fridge_magnets or [],
                    bbox=bbox,
                    scale_factor=scale_factor,
                    backing_height=backing_height,
                )
            backing_slabs = self._build_backing_cavity_slabs(
                backing_sil=backing_sil,
                backing_z_start=backing_z_start,
                backing_height=backing_height,
                cavity_specs=cavity_specs,
                outer_side=outer_side,
            )
            # Clamp the backing material slot to a valid index; fall back to 0
            # when slot_names is empty (legacy defensive path).
            slot_count = len(slot_names) if slot_names else 0
            resolved_backing_mat_id = 0
            if slot_count > 0:
                try:
                    candidate = int(backing_color_id)
                except (TypeError, ValueError):
                    candidate = 0
                if 0 <= candidate < slot_count:
                    resolved_backing_mat_id = candidate

            backing_name = "Board"
            if merge_backing_into_material and slot_count > 0:
                backing_name = slot_names[resolved_backing_mat_id]

            if deferred_vector_slabs:
                backing_entry = meshes_by_slot.setdefault(
                    backing_name,
                    {"slabs": [], "mat_id": resolved_backing_mat_id},
                )
                backing_entry["slabs"].extend(
                    {
                        "geometry": slab["geometry"],
                        "height": float(slab["height"]),
                        "z_offset": float(slab["z_offset"]) + gap_offset,
                    }
                    for slab in backing_slabs
                )
            else:
                backing_meshes = [
                    self._extrude_spatial_geometry_group(
                        slab["geometry"],
                        height=slab["height"],
                        z_offset=slab["z_offset"] + gap_offset,
                        scale=scale_factor,
                        stage="backing",
                        geometry_policy=geometry_policy,
                    )
                    for slab in backing_slabs
                ]
                if backing_meshes:
                    backing_entry = meshes_by_slot.setdefault(
                        backing_name,
                        {"meshes": [], "mat_id": resolved_backing_mat_id},
                    )
                    backing_entry["meshes"].extend(backing_meshes)
        stage_timings["backing_s"] = time.perf_counter() - t0
        stage_timings["vector_mesh_rss_after_backing_bytes"] = int(
            get_process_rss_bytes() or 0
        )

        t0 = time.perf_counter()
        if enable_coating and silhouette is not None and not silhouette.is_empty:
            coating_sil = structure.in_units(structure.envelope, scale_factor)
            try:
                requested_coating_height = float(coating_height_mm)
            except (TypeError, ValueError):
                requested_coating_height = layer_h
            if not np.isfinite(requested_coating_height) or requested_coating_height <= 0:
                requested_coating_height = layer_h
            coating_layers = max(1, int(round(requested_coating_height / layer_h)))
            coating_height = coating_layers * layer_h
            coating_name = "Coating"
            coating_z_offsets = [-coating_height]
            if is_double_sided and not is_5color:
                coating_z_offsets.append(
                    (2 * num_layers + backing_layer_count) * layer_h
                )
            if deferred_vector_slabs:
                meshes_by_slot[coating_name] = {
                    "slabs": [
                        {
                            "geometry": coating_sil,
                            "height": coating_height,
                            "z_offset": z_offset,
                        }
                        for z_offset in coating_z_offsets
                    ],
                    "mat_id": max(num_channels, len(slot_names)),
                }
            else:
                coating_meshes = [
                    self._extrude_spatial_geometry_group(
                        coating_sil,
                        height=coating_height,
                        z_offset=z_offset,
                        scale=scale_factor,
                        stage="coating",
                        geometry_policy=geometry_policy,
                    )
                    for z_offset in coating_z_offsets
                ]
                meshes_by_slot[coating_name] = {
                    "meshes": coating_meshes,
                    "mat_id": max(num_channels, len(slot_names)),
                }
            meshes_by_slot[coating_name]["export_material"] = self.coating_material
            preview_colors[coating_name] = ([*self.coating_material.rgb, 255]
                                            if self.coating_material else [200, 200, 200, 80])
        stage_timings["coating_s"] = time.perf_counter() - t0
        stage_timings["vector_mesh_rss_after_coating_bytes"] = int(
            get_process_rss_bytes() or 0
        )

        # === Stage 7: Double-sided structure ===
        t0 = time.perf_counter()
        if is_double_sided:
            _log.debug("Adding mirrored color layers (double-sided mode)...")
            top_z_start = backing_z_start + backing_layer_count * layer_h
            self._add_double_sided_layers(
                matched_shapes,
                num_layers,
                layer_h,
                num_channels,
                slot_names,
                scale_factor,
                top_z_start,
                meshes_by_slot,
                defer_materialization=deferred_vector_slabs,
                geometry_policy=geometry_policy,
            )
        stage_timings["extrude_top_s"] = time.perf_counter() - t0
        stage_timings["vector_mesh_rss_after_extrude_top_bytes"] = int(
            get_process_rss_bytes() or 0
        )

        if deferred_vector_slabs:
            materialize_t0 = time.perf_counter()
            if isinstance(getattr(analysis, "svg_coordinate_domain", None), SvgCoordinateDomain):
                prepare_print_slabs(
                    [slab for data in meshes_by_slot.values() for slab in data["slabs"]],
                    mm_per_unit=scale_factor, grid_mm=geometry_grid_mm,
                )
            meshes_by_slot = self._materialize_vector_slabs(
                meshes_by_slot,
                scale_factor=scale_factor,
                geometry_policy=geometry_policy,
                timings=stage_timings,
            )
            stage_timings["materialize_s"] = (
                time.perf_counter() - materialize_t0
            )

        # === Stage 8: Assemble scene (sorted by material ID) ===
        t0 = time.perf_counter()
        scene = trimesh.Scene()
        svg_height_mm = bbox[3] * scale_factor

        sorted_items = sorted(meshes_by_slot.items(), key=lambda x: x[1]["mat_id"])

        for name, data in sorted_items:
            mesh_list = data["meshes"]
            mat_id = data["mat_id"]
            if not mesh_list:
                continue

            _log.debug("Merging %s parts for %s...", len(mesh_list), name)
            if len(mesh_list) == 1:
                combined = mesh_list[0]
            else:
                combined = _concatenate_meshes_fast(
                    mesh_list,
                )
            if hasattr(mesh_list, "clear"):
                mesh_list.clear()
            # Independent prisms must remain independently indexed closed
            # shells. Blindly welding coincident coordinates preserves their
            # internal walls and creates edges used by more than two faces.
            self._fix_coordinates(combined, svg_height_mm)
            if mirror_transform is not None:
                transform_layered_mesh(combined, mirror_transform)

            export_material = data.get("export_material")
            color_val = ([*export_material.rgb, 255] if export_material else
                         preview_colors.get(mat_id, preview_colors.get(name, [255, 255, 255, 255])))
            combined.visual.face_colors = color_val
            combined.metadata["name"] = name
            if export_material:
                combined.metadata["bambu_material_name"] = export_material.name
            scene.add_geometry(combined, geom_name=name)

        stage_timings["assemble_s"] = time.perf_counter() - t0
        scene.metadata[LAYERED_COORDINATE_DOMAIN_KEY] = (
            coordinate_domain.to_metadata()
        )
        stage_timings["vector_mesh_rss_after_assemble_bytes"] = int(
            get_process_rss_bytes() or 0
        )
        stage_timings["total_s"] = time.perf_counter() - t_total_start
        self.last_stage_timings = stage_timings

        rss_stage_keys = (
            "vector_mesh_rss_preflight_bytes",
            "vector_mesh_rss_after_extrude_bottom_bytes",
            "vector_mesh_rss_after_backing_bytes",
            "vector_mesh_rss_after_coating_bytes",
            "vector_mesh_rss_after_extrude_top_bytes",
            "vector_mesh_rss_after_assemble_bytes",
        )
        _log.debug(
            "Stage timings (s): parse=%.3f, clip=%.3f, match=%.3f, "
            "extrude_bottom=%.3f, backing=%.3f, extrude_top=%.3f, assemble=%.3f, total=%.3f",
            stage_timings.get("parse_s", 0),
            stage_timings.get("occlusion_s", 0),
            stage_timings.get("color_match_s", 0),
            stage_timings["extrude_bottom_s"],
            stage_timings["backing_s"],
            stage_timings["extrude_top_s"],
            stage_timings["assemble_s"],
            stage_timings["total_s"],
        )
        _log.debug("Scene complete: %s objects", len(scene.geometry))
        return scene

    @staticmethod
    def _build_relief_meshes(
        *,
        matched_shapes,
        num_layers,
        layer_h,
        num_channels,
        slot_names,
        scale_factor,
        backing_color_id,
        default_height_mm,
        height_mode,
        color_height_map,
        heightmap_path,
        heightmap_max_height,
        bbox,
        enable_fridge_magnet=False,
        fridge_magnets=None,
        merge_backing_into_material=False,
        geometry_policy: VectorLayerGeometryPolicy | None = None,
    ):
        """Extrude existing SVG regions at configured heights.

        This deliberately reuses ``matched_shapes``. Relief changes only each
        region's backing depth and optical Z offset; it never rasterizes SVG
        colour geometry into voxels.

        直接复用 ``matched_shapes``：浮雕只改变各色块的底板深度和光学层
        Z 偏移，不把 SVG 色块重新栅格化成体素。
        """
        matched_shapes = tuple(matched_shapes)
        print_grid_mm = next((item[PRINT_GRID_KEY] for item in matched_shapes
                              if PRINT_GRID_KEY in item), None)
        geometry_scale = float(print_grid_mm) if print_grid_mm is not None else scale_factor
        geometry_bbox = tuple(value * scale_factor / geometry_scale for value in bbox)
        normalized_heights: dict[str, float] = {}
        for raw_key, raw_height in (color_height_map or {}).items():
            key = str(raw_key).strip().lower()
            if not key.startswith("#"):
                key = f"#{key}"
            try:
                height = float(raw_height)
            except (TypeError, ValueError):
                continue
            if np.isfinite(height) and height > 0:
                normalized_heights[key] = height

        resolved_height_mode = str(height_mode or "color").lower()
        sampled_height_matrix = None
        if resolved_height_mode == "heightmap":
            if not heightmap_path:
                raise ValueError("Native SVG heightmap relief requires heightmap_path")
            from core.heightmap_loader import HeightmapLoader

            bbox_width = float(bbox[2])
            bbox_height = float(bbox[3])
            if bbox_width <= 0 or bbox_height <= 0:
                raise ValueError("Native SVG relief requires a positive SVG bounding box")
            sample_width = max(
                2,
                min(1600, int(round(bbox_width * float(scale_factor) * 4.0))),
            )
            sample_height = max(
                2,
                min(
                    1600,
                    int(round(sample_width * bbox_height / bbox_width)),
                ),
            )
            heightmap_result = HeightmapLoader.load_and_process(
                heightmap_path=str(heightmap_path),
                target_w=sample_width,
                target_h=sample_height,
                max_relief_height=float(heightmap_max_height or default_height_mm),
                base_thickness=float(default_height_mm),
            )
            if not heightmap_result.get("success"):
                raise ValueError(
                    str(heightmap_result.get("error") or "Heightmap processing failed")
                )
            sampled_height_matrix = np.asarray(
                heightmap_result["height_matrix"], dtype=np.float32
            )
        elif resolved_height_mode != "color":
            raise ValueError(f"Unsupported native SVG relief height mode: {height_mode}")

        minimum_total_layers = max(1, int(num_layers)) + 1
        default_backing_layers = max(
            1,
            int(round(max(float(default_height_mm), layer_h) / layer_h)),
        )
        default_total_layers = max(
            minimum_total_layers,
            default_backing_layers + int(num_layers),
        )
        optical_groups: dict[tuple[int, int, int, int], list] = {}
        backing_groups: dict[int, list] = {}

        for item in matched_shapes:
            source_geometry = item.get("geometry")
            geometry = item.get("print_geometry", source_geometry)
            recipe = [int(value) for value in (item.get("recipe") or [])]
            if geometry is None or geometry.is_empty or not recipe:
                continue
            rgb = (
                item.get("height_identity_rgb")
                or item.get("matched_rgb")
                or item.get("color")
                or ()
            )
            try:
                color_key = f"#{int(rgb[0]):02x}{int(rgb[1]):02x}{int(rgb[2]):02x}"
            except (TypeError, ValueError, IndexError):
                color_key = ""
            if sampled_height_matrix is not None:
                sample_point = source_geometry.representative_point()
                x_ratio = (float(sample_point.x) - float(bbox[0])) / float(bbox[2])
                y_ratio = (float(sample_point.y) - float(bbox[1])) / float(bbox[3])
                sample_x = int(
                    np.clip(
                        round(x_ratio * (sampled_height_matrix.shape[1] - 1)),
                        0,
                        sampled_height_matrix.shape[1] - 1,
                    )
                )
                sample_y = int(
                    np.clip(
                        round(y_ratio * (sampled_height_matrix.shape[0] - 1)),
                        0,
                        sampled_height_matrix.shape[0] - 1,
                    )
                )
                requested_height = float(sampled_height_matrix[sample_y, sample_x])
            else:
                requested_height = normalized_heights.get(color_key)
            if requested_height is None:
                total_layers = default_total_layers
            else:
                total_layers = max(
                    minimum_total_layers,
                    int(np.ceil(requested_height / layer_h)),
                )

            backing_layers = total_layers - int(num_layers)
            backing_groups.setdefault(backing_layers, []).append(geometry)
            layers_to_use = min(int(num_layers), len(recipe))
            for channel, runs in VectorProcessor._build_channel_runs(
                recipe,
                layers_to_use,
                int(num_channels),
            ).items():
                if channel >= len(slot_names):
                    continue
                for run_start, run_end in runs:
                    optical_groups.setdefault(
                        (total_layers, channel, run_start, run_end), []
                    ).append(geometry)

        slabs_by_slot: dict[str, dict] = {}
        for (total_layers, channel, run_start, run_end), geometries in optical_groups.items():
            inverted_start = (int(num_layers) - 1) - run_end
            inverted_end = (int(num_layers) - 1) - run_start
            z_offset = (total_layers - int(num_layers) + inverted_start) * layer_h
            height = (inverted_end - inverted_start + 1) * layer_h
            slot_name = slot_names[channel]
            entry = slabs_by_slot.setdefault(
                slot_name,
                {"slabs": [], "mat_id": channel},
            )
            merged = _union_run_group_geometries(geometries)
            if merged is None or merged.is_empty:
                continue
            entry["slabs"].append(
                {
                    "geometry": merged,
                    "height": float(height),
                    "z_offset": float(z_offset),
                    **({PRINT_GRID_KEY: float(print_grid_mm)}
                       if print_grid_mm is not None else {}),
                }
            )

        resolved_backing_mat_id = 0
        try:
            backing_candidate = int(backing_color_id)
        except (TypeError, ValueError):
            backing_candidate = 0
        if 0 <= backing_candidate < len(slot_names):
            resolved_backing_mat_id = backing_candidate
        backing_name = "Board"
        if merge_backing_into_material and slot_names:
            backing_name = slot_names[resolved_backing_mat_id]
        backing_volume_slabs = []
        full_backing_sil = _union_run_group_geometries(
            [
                geometry
                for geometries in backing_groups.values()
                for geometry in geometries
            ]
        )
        cavity_specs = []
        if enable_fridge_magnet and not full_backing_sil.is_empty:
            maximum_backing_height = max(backing_groups, default=0) * layer_h
            cavity_specs = VectorProcessor._build_vector_fridge_cavity_specs(
                backing_sil=full_backing_sil,
                fridge_magnets=fridge_magnets or [],
                bbox=geometry_bbox,
                scale_factor=geometry_scale,
                backing_height=maximum_backing_height,
            )
        for backing_layers, geometries in backing_groups.items():
            merged = _union_run_group_geometries(geometries)
            backing_height = backing_layers * layer_h
            group_cavity_specs = []
            for spec in cavity_specs:
                overlap = grid_intersection(
                    merged, spec["geometry"], grid_size=float(get_precision(merged)),
                )
                clipped = VectorProcessor._extract_polygonal_geometry(
                    overlap if get_precision(merged) > 0 else make_valid(overlap)
                )
                if clipped is not None and not clipped.is_empty:
                    group_cavity_specs.append(
                        {
                            "geometry": clipped,
                            "depth_mm": spec["depth_mm"],
                        }
                    )
            backing_slabs = VectorProcessor._build_backing_cavity_slabs(
                backing_sil=merged,
                backing_z_start=0.0,
                backing_height=backing_height,
                cavity_specs=group_cavity_specs,
                outer_side="low",
            )
            for slab in backing_slabs:
                backing_volume_slabs.append(slab)
        if print_grid_mm is not None:
            prepare_print_slabs(
                backing_volume_slabs, mm_per_unit=geometry_scale,
                grid_mm=float(print_grid_mm),
            )
        meshes_by_slot = VectorProcessor._materialize_vector_slabs(
            slabs_by_slot,
            scale_factor=scale_factor,
            geometry_policy=geometry_policy,
        )
        board_mesh = build_vector_layered_volume(
            backing_volume_slabs,
            scale_mm_per_svg_unit=geometry_scale,
            policy=geometry_policy,
        )
        if board_mesh is not None and len(board_mesh.faces) > 0:
            board_entry = meshes_by_slot.setdefault(
                backing_name,
                {"meshes": [], "mat_id": resolved_backing_mat_id},
            )
            board_entry["meshes"].append(board_mesh)
            if len(board_entry["meshes"]) > 1:
                board_entry["meshes"] = [
                    _concatenate_meshes_fast(board_entry["meshes"])
                ]
        return meshes_by_slot

    def svg_to_mesh(
        self,
        svg_path: str,
        target_width_mm: float,
        thickness_mm: float,
        structure_mode: str = "Single-sided",
        color_replacements: dict | list[dict] | None = None,
        progress_fn=None,
    ) -> trimesh.Scene:
        """Convert an SVG file to a trimesh Scene ready for 3MF export.
        将 SVG 文件转换为可用于 3MF 导出的 trimesh Scene。

        Convenience wrapper combining ``analyze_svg`` and ``build_mesh``.

        Args:
            svg_path:         Path to SVG file.
            target_width_mm:  Physical width in mm for the output model.
            thickness_mm:     Backing (spacer) thickness in mm.
            structure_mode:   "Single-sided" or "Double-sided".
            color_replacements: Optional legacy replacement map or API
                ``ColorReplacementItem`` records.
            progress_fn:      Optional progress callback.

        Returns:
            A ``trimesh.Scene`` with one geometry per material slot, sorted
            by material ID.  Geometry names match slot names from the active
            ``ColorSystem`` configuration.
        """
        analysis = self.analyze_svg(svg_path, target_width_mm, color_replacements, progress_fn)
        return self.build_mesh(
            analysis,
            thickness_mm,
            structure_mode,
            progress_fn=progress_fn,
        )

    # ── 2D preview from analyzed geometry ─────────────────────────────────

    @staticmethod
    def render_preview(
        analysis: "VectorAnalysis",
        pixels_per_mm: float = 10.0,
        max_width_px: int = 1600,
    ) -> np.ndarray:
        """Render a 2D RGBA preview from analyzed vector geometry.
        从已分析的矢量几何渲染 2D RGBA 预览，与 3MF 使用同一组几何数据。

        Args:
            analysis:      Result from ``analyze_svg``.
            pixels_per_mm: Rasterization density (pixels per mm).
            max_width_px:  Maximum output width in pixels.

        Returns:
            (H, W, 4) uint8 RGBA numpy array with white background.
        """
        real_w = analysis.bbox[2]
        real_h = analysis.bbox[3]
        sf = analysis.scale_factor

        w_mm = real_w * sf
        h_mm = real_h * sf
        ppm = pixels_per_mm

        w_px = max(1, int(round(w_mm * ppm)))
        h_px = max(1, int(round(h_mm * ppm)))

        if w_px > max_width_px:
            ratio = max_width_px / w_px
            w_px = max_width_px
            h_px = max(1, int(round(h_px * ratio)))
            ppm = w_px / w_mm

        canvas = np.full((h_px, w_px, 4), 255, dtype=np.uint8)

        coord_scale = sf * ppm

        slot_names = analysis.slot_names
        preview_colors = analysis.preview_colors

        for shape in analysis.matched_shapes:
            geom = shape["geometry"]
            recipe = shape["recipe"]
            if geom is None or geom.is_empty:
                continue

            slot_idx = recipe[0] if recipe else 0
            rgba = preview_colors.get(
                slot_idx,
                preview_colors.get(slot_names[slot_idx] if slot_idx < len(slot_names) else 0, [128, 128, 128, 255]),
            )
            rgb_color = (int(rgba[0]), int(rgba[1]), int(rgba[2]))

            polys = []
            if geom.geom_type == "Polygon":
                polys = [geom]
            elif geom.geom_type == "MultiPolygon":
                polys = list(geom.geoms)
            else:
                continue

            for poly in polys:
                if poly.is_empty:
                    continue
                ext_coords = np.array(poly.exterior.coords)
                pts = np.column_stack(
                    [
                        ext_coords[:, 0] * coord_scale,
                        ext_coords[:, 1] * coord_scale,
                    ]
                ).astype(np.int32)
                cv2.fillPoly(canvas, [pts], (*rgb_color, int(rgba[3])))

                for interior in poly.interiors:
                    hole_coords = np.array(interior.coords)
                    hole_pts = np.column_stack(
                        [
                            hole_coords[:, 0] * coord_scale,
                            hole_coords[:, 1] * coord_scale,
                        ]
                    ).astype(np.int32)
                    cv2.fillPoly(canvas, [hole_pts], (255, 255, 255, 255))

        return canvas

    @staticmethod
    def build_preview_cache(
        analysis: "VectorAnalysis",
        pixels_per_mm: float = 10.0,
        max_width_px: int = 1600,
        supersample_preview: int = 2,
    ) -> dict:
        """Rasterise vector analysis into preview-cache arrays.
        将矢量分析结果光栅化为预览缓存数组，供预览/调色板/GLB 复用。

        Unlike ``render_preview()``, this method preserves separate
        ``matched_rgb`` / ``quantized_image`` / ``mask_solid`` data so the
        frontend preview cache stays aligned with the native vector pipeline.

        ``matched_rgb`` / ``mask_solid`` / ``material_matrix`` /
        ``quantized_image`` are always rasterised at ``pixels_per_mm`` with
        hard-edged ``cv2.fillPoly`` because several downstream APIs
        (color-highlight bbox, region id map, color recipe logger) rely on
        exact pixel-indexed membership.

        ``preview_rgba`` — the display-facing RGBA image read by the frontend
        preview canvas — is rasterised at ``pixels_per_mm * supersample_preview``
        and box-filter downsampled with ``cv2.INTER_AREA`` so shape boundaries
        carry an anti-aliased alpha gradient. Without this the hard-edged
        pixels composited on the page's white background produced the
        stair-stepped jaggies users saw at stroke-heavy borders. Passing
        ``supersample_preview=1`` reverts to the legacy hard-edged behaviour.

        ``preview_rgba`` 使用 supersample + INTER_AREA 降采样做边缘抗锯齿；其
        他掩膜数组保持硬边，保证下游像素索引 API 语义不变。
        """
        real_w = analysis.bbox[2]
        real_h = analysis.bbox[3]
        sf = analysis.scale_factor

        w_mm = real_w * sf
        h_mm = real_h * sf
        ppm = pixels_per_mm

        w_px = max(1, int(round(w_mm * ppm)))
        h_px = max(1, int(round(h_mm * ppm)))

        if w_px > max_width_px:
            ratio = max_width_px / w_px
            w_px = max_width_px
            h_px = max(1, int(round(h_px * ratio)))
            ppm = w_px / w_mm

        coord_scale = sf * ppm
        # Keep transparent SVG background visually white in raw matched-RGB
        # consumers. ``mask_solid`` / ``material_matrix`` still mark those
        # pixels as air, so this does not turn the exterior canvas into print
        # geometry. It only prevents unpainted SVG negative space from being
        # displayed as default black when a caller previews ``matched_rgb``
        # without compositing alpha.
        matched_rgb = np.full((h_px, w_px, 3), 255, dtype=np.uint8)
        height_identity_rgb = np.full((h_px, w_px, 3), 255, dtype=np.uint8)
        quantized_image = np.full((h_px, w_px, 3), 255, dtype=np.uint8)
        mask_solid = np.zeros((h_px, w_px), dtype=bool)
        material_matrix_dtype = _material_matrix_dtype_for_vector_analysis(analysis)
        material_matrix = np.full(
            (h_px, w_px, analysis.num_layers),
            -1,
            dtype=material_matrix_dtype,
        )
        original_material_matrix = np.full_like(material_matrix, -1)

        ss = max(1, int(supersample_preview))
        ss_h = h_px * ss
        ss_w = w_px * ss
        ss_coord_scale = coord_scale * ss
        preview_rgba_ss = np.zeros((ss_h, ss_w, 4), dtype=np.uint8) if ss > 1 else None

        def _iter_polygons(geom):
            if geom is None or geom.is_empty:
                return []
            if geom.geom_type == "Polygon":
                return [geom]
            if geom.geom_type == "MultiPolygon":
                return list(geom.geoms)
            return []

        def _coords_to_pts(coords, scale):
            pts = np.column_stack(
                [
                    coords[:, 0] * scale,
                    coords[:, 1] * scale,
                ]
            ).astype(np.int32)
            if len(pts) < 3:
                return None
            return pts

        def _local_mask_any(mask_ref):
            if mask_ref is None:
                return False
            return bool(np.any(mask_ref[2]))

        def _apply_local_mask_or(target, mask_ref):
            y_slice, x_slice, local = mask_ref
            target[y_slice, x_slice] |= local

        def _assign_local_mask(target, mask_ref, value):
            y_slice, x_slice, local = mask_ref
            view = target[y_slice, x_slice]
            view[local] = value

        def _polygon_mask_plain(poly, height, width, scale):
            """Original int-truncated single-resolution fill as a local mask.
            原始的整数截断、单分辨率填充。

            Retained for the ``preview_rgba`` path, which already rasterises
            on a supersampled grid and then box-filter downsamples, so its
            edges are anti-aliased and the 1px seam averages out visually.
            Re-supersampling there would multiply cost for no membership-mask
            gain (``preview_rgba`` is display-only, not a membership mask).

            保留给 ``preview_rgba`` 路径：它本身已在超采样网格上栅格化并做
            INTER_AREA 降采样，边缘已抗锯齿、缝会被视觉平均掉，无需再次
            超采样（``preview_rgba`` 仅用于显示，不作为归属掩膜）。
            """
            ext_pts = _coords_to_pts(np.array(poly.exterior.coords), scale)
            if ext_pts is None:
                return None
            x0 = max(0, int(ext_pts[:, 0].min()))
            y0 = max(0, int(ext_pts[:, 1].min()))
            x1 = min(width, int(ext_pts[:, 0].max()) + 1)
            y1 = min(height, int(ext_pts[:, 1].max()) + 1)
            if x1 <= x0 or y1 <= y0:
                return None

            region = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
            local_ext = ext_pts - np.array([x0, y0], dtype=np.int32)
            cv2.fillPoly(region, [local_ext], 255)
            for interior in poly.interiors:
                hole_pts = _coords_to_pts(np.array(interior.coords), scale)
                if hole_pts is not None:
                    local_hole = hole_pts - np.array([x0, y0], dtype=np.int32)
                    cv2.fillPoly(region, [local_hole], 0)
            local = region.astype(bool)
            if not np.any(local):
                return None
            return slice(y0, y1), slice(x0, x1), local

        def _polygon_mask(poly, height, width, scale):
            """Rasterise one polygon footprint into a local membership mask.
            将单个多边形栅格化为布尔归属掩膜。

            Sub-pixel-accurate: the polygon (exterior minus interior holes)
            is filled on a supersampled sub-grid restricted to the polygon's
            pixel bounding box, then downsampled by sampling each output
            pixel's *center* sub-cell. This decides ``mask_solid`` membership
            by "is the pixel center inside the geometry", which fixes the 1px
            seams that plain ``cv2.fillPoly`` left when float vertex
            coordinates were truncated to ``int32`` at the base resolution
            (a geometry-covered pixel whose center sat just inside the shape
            could be dropped, surfacing as a "background area" hole in the
            colour-adjust click flow and as air in the generated 3MF).

            Boundary safety: the supersampled fill also subtracts interior
            holes, and only the polygon's own bbox is touched, so the
            transparent SVG background outside the silhouette can never be
            over-filled. The sub-grid is confined to the bbox so cost stays
            proportional to ``shape_area * ss^2`` instead of
            ``full_grid * ss^2``.

            亚像素精度栅格化：在多边形像素 bbox 内的超采样子网格上填充
            （外环减去内洞），再按每个输出像素的"中心"子格降采样，使
            ``mask_solid`` 的判据变为"像素中心是否落在几何内"。这修复了
            原先把浮点顶点直接 ``int32`` 截断导致的 1px 缝（几何覆盖、
            但被漏填，表现为颜色调整里点击破洞被判背景、3MF 里成空气）。
            边界安全：填充同样扣除内洞，且只触碰多边形自身 bbox，绝不会
            把轮廓外的透明背景误填实。
            """
            ext_coords = np.array(poly.exterior.coords)
            if len(ext_coords) < 3:
                return None

            ss = _MASK_SUPERSAMPLE
            if ss <= 1:
                return _polygon_mask_plain(poly, height, width, scale)

            # Pixel-space bbox of the polygon, clamped to the grid. The +1
            # margin guards against boundary rounding at the bbox edge.
            # 多边形的像素 bbox（夹到网格内）；+1 余量防止 bbox 边缘取整丢边。
            xs = ext_coords[:, 0] * scale
            ys = ext_coords[:, 1] * scale
            x0 = max(0, int(np.floor(xs.min())) - 1)
            y0 = max(0, int(np.floor(ys.min())) - 1)
            x1 = min(width, int(np.ceil(xs.max())) + 1)
            y1 = min(height, int(np.ceil(ys.max())) + 1)
            if x1 <= x0 or y1 <= y0:
                return None

            bw = x1 - x0
            bh = y1 - y0
            sub = np.zeros((bh * ss, bw * ss), dtype=np.uint8)

            def _sub_pts(coords):
                # Map into the supersampled, bbox-local sub-grid.
                # 映射到 bbox 局部的超采样子网格坐标。
                p = np.column_stack(
                    [
                        (coords[:, 0] * scale - x0) * ss,
                        (coords[:, 1] * scale - y0) * ss,
                    ]
                )
                if len(p) < 3:
                    return None
                return np.round(p).astype(np.int32)

            ext_sub = _sub_pts(ext_coords)
            if ext_sub is None:
                return None
            cv2.fillPoly(sub, [ext_sub], 255)
            for interior in poly.interiors:
                hole_sub = _sub_pts(np.array(interior.coords))
                if hole_sub is not None:
                    cv2.fillPoly(sub, [hole_sub], 0)

            # Center sub-cell of each output pixel decides membership.
            # 取每个输出像素的中心子格判定归属。
            off = ss // 2
            local = sub[off::ss, off::ss][:bh, :bw].astype(bool)
            if not np.any(local):
                return None
            return slice(y0, y1), slice(x0, x1), local

        structure = resolve_structure_plan(analysis)
        backing_geom = structure.in_units(structure.body, sf)
        backing_mask = np.zeros((h_px, w_px), dtype=bool)
        for poly in _iter_polygons(backing_geom):
            region_mask = _polygon_mask(poly, h_px, w_px, coord_scale)
            if _local_mask_any(region_mask):
                _apply_local_mask_or(backing_mask, region_mask)

        for shape in analysis.matched_shapes:
            geom = shape.get("geometry")
            if geom is None or geom.is_empty:
                continue

            matched_color = np.array(
                shape.get("matched_rgb") or shape.get("color") or (0, 0, 0),
                dtype=np.uint8,
            )
            source_color = np.array(
                shape.get("color") or shape.get("matched_rgb") or (0, 0, 0),
                dtype=np.uint8,
            )
            height_identity_color = np.array(
                shape.get("height_identity_rgb")
                or shape.get("matched_rgb")
                or shape.get("color")
                or (0, 0, 0),
                dtype=np.uint8,
            )

            recipe = shape.get("recipe") or []
            recipe_full = np.full(
                (analysis.num_layers,),
                -1,
                dtype=material_matrix_dtype,
            )
            for idx, value in enumerate(recipe[: analysis.num_layers]):
                recipe_full[idx] = int(value)
            original_recipe = shape.get("original_recipe") or recipe
            original_recipe_full = np.full(
                (analysis.num_layers,),
                -1,
                dtype=material_matrix_dtype,
            )
            for idx, value in enumerate(original_recipe[: analysis.num_layers]):
                original_recipe_full[idx] = int(value)

            for poly in _iter_polygons(geom):
                if poly.is_empty:
                    continue
                region_mask = _polygon_mask(poly, h_px, w_px, coord_scale)
                if not _local_mask_any(region_mask):
                    continue

                _assign_local_mask(matched_rgb, region_mask, matched_color)
                _assign_local_mask(
                    height_identity_rgb,
                    region_mask,
                    height_identity_color,
                )
                _assign_local_mask(quantized_image, region_mask, source_color)
                _assign_local_mask(mask_solid, region_mask, True)
                _assign_local_mask(material_matrix, region_mask, recipe_full)
                _assign_local_mask(
                    original_material_matrix,
                    region_mask,
                    original_recipe_full,
                )

                if preview_rgba_ss is not None:
                    # preview_rgba is display-only and already supersampled +
                    # INTER_AREA downsampled, so use the plain fill here and
                    # avoid nesting another supersample pass.
                    # preview_rgba 仅用于显示且已超采样 + INTER_AREA 降采样，
                    # 这里用普通填充，避免再嵌套一层超采样。
                    ss_mask = _polygon_mask_plain(poly, ss_h, ss_w, ss_coord_scale)
                    if _local_mask_any(ss_mask):
                        _assign_local_mask(preview_rgba_ss[:, :, :3], ss_mask, matched_color)
                        _assign_local_mask(preview_rgba_ss[:, :, 3], ss_mask, 255)

        if preview_rgba_ss is not None:
            preview_rgba = cv2.resize(
                preview_rgba_ss, (w_px, h_px), interpolation=cv2.INTER_AREA,
            )
            # The supersampled alpha is filled per shape, so the thin seams
            # between adjacent shapes (and the borders of occlusion-carved
            # interior holes) land on partially-covered output pixels and
            # downsample to alpha ~128 — a semi-transparent gap that shows the
            # page background through solid artwork (the "透明破洞" users saw in
            # the hair). ``mask_solid`` is the seam-free sub-pixel membership
            # mask, so force full opacity (and the seam-free colour) wherever a
            # pixel is solid. Exterior anti-aliasing is preserved because
            # ``mask_solid`` is False in the outer AA band, leaving its blended
            # alpha untouched. Boundary safety: pixels outside the silhouette
            # keep ``mask_solid == False`` and are never forced opaque.
            # 超采样 alpha 逐 shape 填充，相邻 shape 之间的细缝与遮挡洞边界落在
            # 部分覆盖的输出像素上，降采样后 alpha≈128，合成时透出页面底色，
            # 即用户看到的头发"透明破洞"。``mask_solid`` 是无缝的亚像素归属掩膜，
            # 因此在其为实体处强制不透明并取无缝颜色；轮廓外 ``mask_solid`` 为
            # False，外缘抗锯齿保留、背景不会被误填。
            seam = mask_solid & (preview_rgba[:, :, 3] < 255)
            if np.any(seam):
                preview_rgba[seam, :3] = matched_rgb[seam]
                preview_rgba[seam, 3] = 255
        else:
            preview_rgba = np.zeros((h_px, w_px, 4), dtype=np.uint8)
            preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
            preview_rgba[mask_solid, 3] = 255

        # Preserve object identity for pristine snapshots. The artifact
        # externalizer deduplicates by ndarray identity, so an unmodified
        # vector preview writes one RGB and one recipe grid rather than
        # redundant current/original/height copies. Replaced outputs remain
        # distinct while original_matched_rgb and height_identity_rgb alias.
        if np.array_equal(matched_rgb, height_identity_rgb):
            matched_rgb = height_identity_rgb
        if np.array_equal(material_matrix, original_material_matrix):
            material_matrix = original_material_matrix

        return {
            "target_w": w_px,
            "target_h": h_px,
            "target_width_mm": w_mm,
            "pixel_scale": (w_mm / w_px) if w_px > 0 else 0.0,
            "matched_rgb": matched_rgb,
            "original_matched_rgb": height_identity_rgb,
            "height_identity_rgb": height_identity_rgb,
            "quantized_image": quantized_image,
            "mask_solid": mask_solid,
            "backing_mask": backing_mask if np.any(backing_mask) else mask_solid.copy(),
            "material_matrix": material_matrix,
            "original_material_matrix": original_material_matrix,
            "preview_rgba": preview_rgba,
        }

    # ── Stage 2: Occlusion clipping (Chroma-style) ───────────────────────

    @staticmethod
    def _clip_occlusion(shape_data, return_silhouette=False):
        """Clip shapes so no two overlap in XY.

        Iterates in reverse draw order (topmost first).  Each shape is
        subtracted from the accumulated union so that lower shapes only
        retain geometry not already covered by higher shapes.

        This mirrors ``ChromaPrint3D::detail::ClipOcclusion``.
        """
        n = len(shape_data)
        if n == 0:
            return ([], None) if return_silhouette else []

        valid = []
        for i, item in enumerate(shape_data):
            geom = item["poly"]
            if geom is None or geom.is_empty:
                continue
            valid.append((i, geom))

        if not valid:
            return ([], None) if return_silhouette else []

        orders = [v[0] for v in valid]
        geoms = [v[1] for v in valid]
        tree = STRtree(geoms)
        geom_id_to_idx = {id(g): idx for idx, g in enumerate(geoms)}
        silhouette = None
        silhouette_computed = False
        build_silhouette_concurrently = (
            return_silhouette
            and len(geoms) >= _OCCLUSION_PARALLEL_MIN_SHAPES
            and _occlusion_parallel_worker_count(len(orders)) >= 3
        )
        if build_silhouette_concurrently:
            with ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="lumina-vector-silhouette",
            ) as executor:
                silhouette_future = executor.submit(unary_union, geoms)
                result = _try_parallel_clip_occlusion(
                    shape_data,
                    orders,
                    geoms,
                    tree,
                    reserved_workers=1,
                )
                try:
                    silhouette = silhouette_future.result()
                except VECTOR_HANDLED_ERRORS:
                    silhouette = None
                silhouette_computed = True
        else:
            result = _try_parallel_clip_occlusion(
                shape_data,
                orders,
                geoms,
                tree,
            )

        if result is None:
            result = []
            for i in range(n - 1, -1, -1):
                item = shape_data[i]
                geom = item["poly"]
                if geom is None or geom.is_empty:
                    continue

                occluders = []
                predicate_filtered = False
                try:
                    candidate_refs = tree.query(geom, predicate="intersects")
                    predicate_filtered = True
                except TypeError:
                    try:
                        candidate_refs = tree.query(geom)
                    except VECTOR_HANDLED_ERRORS:
                        candidate_refs = []
                except VECTOR_HANDLED_ERRORS:
                    try:
                        candidate_refs = tree.query(geom)
                    except VECTOR_HANDLED_ERRORS:
                        candidate_refs = []

                for ref in candidate_refs:
                    if isinstance(ref, (int, np.integer)):
                        idx = int(ref)
                    else:
                        idx = geom_id_to_idx.get(id(ref), -1)
                    if idx < 0:
                        continue
                    if orders[idx] <= i:
                        continue
                    cand = geoms[idx]
                    if predicate_filtered:
                        occluders.append(cand)
                        continue
                    try:
                        if cand.intersects(geom):
                            occluders.append(cand)
                    except VECTOR_HANDLED_ERRORS:
                        continue

                clipped_item = _clip_occlusion_result_item(
                    item,
                    i,
                    geom,
                    occluders,
                )
                if clipped_item is not None:
                    result.append(clipped_item)

            result.reverse()
        if return_silhouette and not silhouette_computed:
            try:
                silhouette = unary_union(geoms)
            except VECTOR_HANDLED_ERRORS:
                silhouette = None
        if return_silhouette:
            return result, silhouette
        return result

    @staticmethod
    def _postprocess_clipped_shapes(clipped_shapes):
        post_clip = [None] * len(clipped_shapes)
        pending_positions = []
        pending_items = []
        pending_geometries = []

        for idx, item in enumerate(clipped_shapes):
            g = item["geometry"]
            if item.get("geometry_normalized") is not True:
                pending_positions.append(idx)
                pending_items.append(item)
                pending_geometries.append(g)
                continue
            if g is not None and not g.is_empty:
                updated = dict(item)
                updated["geometry"] = g
                updated["geometry_normalized"] = True
                post_clip[idx] = updated

        if pending_geometries:
            normalized_geometries = _normalize_contours_many(pending_geometries)
            for idx, item, g in zip(pending_positions, pending_items, normalized_geometries):
                if g is not None and not g.is_empty:
                    updated = dict(item)
                    updated["geometry"] = g
                    updated["geometry_normalized"] = True
                    post_clip[idx] = updated

        return [item for item in post_clip if item is not None]

    # ── Stage 4: Color matching with per-color cache ─────────────────────

    def _with_near_fill_match_queries(self, clipped_shapes):
        """Return shallow-copied shapes with near-identical fills sharing a query."""
        if getattr(self.img_processor, "solve_for_fills", None) is not None:
            return clipped_shapes

        threshold = float(
            getattr(VectorConfig, "VECTOR_NEAR_FILL_QUERY_DELTA_E", 0.0)
        )
        if not clipped_shapes or threshold <= 0.0:
            return clipped_shapes

        stats_by_color = {}
        for idx, item in enumerate(clipped_shapes):
            if item.get("match_color") is not None:
                continue
            color = item.get("color")
            try:
                rgb = (int(color[0]), int(color[1]), int(color[2]))
            except (TypeError, IndexError, ValueError):
                continue
            geom = item.get("geometry")
            try:
                area = max(0.0, float(geom.area)) if geom is not None else 0.0
            except (AttributeError, TypeError, ValueError):
                area = 0.0
            stats = stats_by_color.setdefault(
                rgb,
                {"area": 0.0, "first_index": idx},
            )
            stats["area"] += area

        if len(stats_by_color) < 2:
            return clipped_shapes

        source_colors = list(stats_by_color)
        try:
            source_lab = self.img_processor._rgb_to_lab(
                np.array(source_colors, dtype=np.uint8)
            ).reshape(-1, 3).astype(np.float64)
        except VECTOR_HANDLED_ERRORS:
            return clipped_shapes

        lab_by_color = {
            rgb: source_lab[idx]
            for idx, rgb in enumerate(source_colors)
        }
        ordered_colors = sorted(
            source_colors,
            key=lambda rgb: (
                -float(stats_by_color[rgb]["area"]),
                int(stats_by_color[rgb]["first_index"]),
                rgb,
            ),
        )

        representatives = []
        representative_members = []
        representative_by_color = {}
        representative_groups_by_bucket = {}

        def spatial_bucket(lab):
            if not bool(np.isfinite(lab).all()):
                return None
            return tuple(math.floor(float(value) / threshold) for value in lab)

        for rgb in ordered_colors:
            rgb_lab = lab_by_color[rgb]
            chosen = None
            bucket = spatial_bucket(rgb_lab)
            if bucket is None:
                candidate_group_indices = range(len(representatives))
            else:
                nearby_groups = set()
                for red_offset in range(-2, 3):
                    for green_offset in range(-2, 3):
                        for blue_offset in range(-2, 3):
                            nearby_groups.update(
                                representative_groups_by_bucket.get(
                                    (
                                        bucket[0] + red_offset,
                                        bucket[1] + green_offset,
                                        bucket[2] + blue_offset,
                                    ),
                                    (),
                                )
                            )
                candidate_group_indices = sorted(nearby_groups)

            for group_idx in candidate_group_indices:
                representative = representatives[group_idx]
                if all(
                    float(np.linalg.norm(rgb_lab - lab_by_color[member]))
                    <= threshold
                    for member in representative_members[group_idx]
                ):
                    chosen = representative
                    representative_members[group_idx].append(rgb)
                    break
            if chosen is None:
                representatives.append(rgb)
                representative_members.append([rgb])
                chosen = rgb
                group_idx = len(representatives) - 1
                if bucket is not None:
                    representative_groups_by_bucket.setdefault(bucket, []).append(
                        group_idx
                    )
            representative_by_color[rgb] = chosen

        # Native integer-grid reconstruction can introduce area noise several
        # orders of magnitude below the physical error budget. Do not let that
        # noise choose a later SVG fill as a near-colour group's canonical
        # query; for numerically tied dominant areas, preserve source order.
        for group_members in representative_members:
            max_area = max(
                float(stats_by_color[member]["area"])
                for member in group_members
            )
            dominant_members = [
                member
                for member in group_members
                if math.isclose(
                    float(stats_by_color[member]["area"]),
                    max_area,
                    rel_tol=1e-9,
                    abs_tol=1e-12,
                )
            ]
            canonical = min(
                dominant_members,
                key=lambda member: (
                    int(stats_by_color[member]["first_index"]),
                    member,
                ),
            )
            for member in group_members:
                representative_by_color[member] = canonical

        if all(
            representative_by_color.get(rgb, rgb) == rgb
            for rgb in representative_by_color
        ):
            return clipped_shapes

        updated_shapes = []
        changed = False
        for item in clipped_shapes:
            color = item.get("color")
            try:
                rgb = (int(color[0]), int(color[1]), int(color[2]))
            except (TypeError, IndexError, ValueError):
                updated_shapes.append(item)
                continue
            representative = representative_by_color.get(rgb, rgb)
            if representative != rgb and item.get("match_color") is None:
                updated = dict(item)
                updated["match_color"] = representative
                updated_shapes.append(updated)
                changed = True
            else:
                updated_shapes.append(item)
        return updated_shapes if changed else clipped_shapes

    def _match_lut_index_for_rgb(self, query_rgb):
        """Return the LUT index and Lab distance for one RGB query.

        Uses the shared hue-aware matcher when it is enabled on the
        image processor, keeping SVG-native matching aligned with the
        raster/high-fidelity paths.

        使用图像处理器已启用的色相保护匹配器，让 SVG 原生矢量路径与
        栅格/高保真路径保持一致。
        """
        exact_index_for_rgb = getattr(
            self.img_processor,
            "exact_lut_index_for_rgb",
            None,
        )
        if callable(exact_index_for_rgb):
            exact_index = exact_index_for_rgb(query_rgb)
            if exact_index is not None:
                return int(exact_index), 0.0

        query_lab = self.img_processor._rgb_to_lab(
            np.array([query_rgb], dtype=np.uint8)
        )
        hue_matcher = getattr(self.img_processor, "hue_matcher", None)
        if hue_matcher is not None:
            matched_indices = hue_matcher.match_colors_batch(
                np.array([query_rgb], dtype=np.uint8)
            )
            lut_idx = int(np.asarray(matched_indices).reshape(-1)[0])
            matched_lab = np.asarray(
                self.img_processor.lut_lab[lut_idx],
                dtype=np.float64,
            )
            lab_dist = float(
                np.linalg.norm(query_lab.reshape(-1) - matched_lab.reshape(-1))
            )
            return lut_idx, lab_dist

        dist, index = self.img_processor.kdtree.query(query_lab)
        lut_idx = int(index[0])
        lab_dist = float(dist[0]) if hasattr(dist, "__len__") else float(dist)
        return lut_idx, lab_dist

    def _match_colors(self, clipped_shapes, replacement_manager, num_channels, num_layers=None):
        """Match each shape's fill colour to a LUT recipe.

        Identical fill colours share a single KDTree lookup via a cache,
        mirroring ``ChromaPrint3D::VectorRecipeMap::Match`` behaviour.

        Returns a list of dicts: ``{geometry, recipe, color}``.
        """
        if num_layers is None:
            num_layers = PrinterConfig.COLOR_LAYERS
        recipe_log_mode = os.getenv("LUMINA_VECTOR_RECIPE_LOG", "summary").strip().lower()
        color_cache = {}
        dynamic_metadata_for_fill = getattr(
            self.img_processor,
            "dynamic_metadata_for_fill",
            None,
        )
        matched = []
        sample_logs = []
        large_distance_count = 0
        large_distance_warning_count = 0

        for item in clipped_shapes:
            rgb = item["color"]
            query_rgb = item.get("match_color", rgb)
            try:
                query_rgb = (int(query_rgb[0]), int(query_rgb[1]), int(query_rgb[2]))
            except (TypeError, IndexError, ValueError):
                query_rgb = rgb

            if query_rgb in color_cache:
                cached = color_cache[query_rgb]
                recipe = cached["recipe"]
                matched_rgb = cached["matched_rgb"]
                lut_idx = cached["lut_idx"]
                height_identity_rgb = cached["height_identity_rgb"]
                original_recipe = cached["original_recipe"]
            else:
                identity_lut_idx, lab_dist = self._match_lut_index_for_rgb(query_rgb)
                height_identity_rgb = tuple(
                    int(c) for c in self.img_processor.lut_rgb[identity_lut_idx]
                )
                original_stack = self.img_processor.ref_stacks[identity_lut_idx]
                original_recipe = _normalise_cached_stack_for_vector_recipe(
                    original_stack,
                    target_layers=min(int(num_layers), len(original_stack)),
                    num_channels=num_channels,
                )
                lut_idx = identity_lut_idx
                matched_rgb = height_identity_rgb

                if replacement_manager is not None:
                    replacement = replacement_manager.get_replacement(matched_rgb)
                    if replacement is not None:
                        lut_idx, _ = self._match_lut_index_for_rgb(replacement)
                        matched_rgb = tuple(int(c) for c in self.img_processor.lut_rgb[lut_idx])

                stack = self.img_processor.ref_stacks[lut_idx]
                recipe = _normalise_cached_stack_for_vector_recipe(
                    stack,
                    target_layers=min(int(num_layers), len(stack)),
                    num_channels=num_channels,
                )
                color_cache[query_rgb] = {
                    "recipe": recipe,
                    "matched_rgb": matched_rgb,
                    "lut_idx": lut_idx,
                    "height_identity_rgb": height_identity_rgb,
                    "original_recipe": original_recipe,
                    "lab_dist": lab_dist,
                }

                hex_c = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"
                query_hex = f"#{query_rgb[0]:02x}{query_rgb[1]:02x}{query_rgb[2]:02x}"
                matched_hex = f"#{matched_rgb[0]:02x}{matched_rgb[1]:02x}{matched_rgb[2]:02x}"

                # Flag suspiciously large Lab distance (>25 is visually very different)
                if lab_dist > 25.0:
                    large_distance_count += 1
                    if large_distance_warning_count < _VECTOR_LARGE_DISTANCE_WARN_LIMIT:
                        large_distance_warning_count += 1
                        _log.warning(
                            "Large color distance in match: %s -> %s (Lab dist=%.1f)",
                            query_hex, matched_hex, lab_dist,
                            extra={
                                "event": "vector_match_color_large_distance",
                                "query_rgb": list(query_rgb),
                                "matched_rgb": list(matched_rgb),
                                "lab_distance": round(lab_dist, 2),
                                "lut_idx": lut_idx,
                                "kdtree_size": self.img_processor.kdtree.n if hasattr(self.img_processor.kdtree, 'n') else len(self.img_processor.lut_rgb),
                            },
                        )

                if recipe_log_mode == "full":
                    if query_rgb != rgb:
                        _log.debug("  %s => %s -> %s -> recipe %s (dist=%.2f)", hex_c, query_hex, matched_hex, recipe, lab_dist)
                    else:
                        _log.debug("  %s -> %s -> recipe %s (dist=%.2f)", hex_c, matched_hex, recipe, lab_dist)
                elif recipe_log_mode == "summary" and len(sample_logs) < 8:
                    if query_rgb != rgb:
                        sample_logs.append(f"{hex_c} => {query_hex} -> {matched_hex} -> {recipe} (dist={lab_dist:.1f})")
                    else:
                        sample_logs.append(f"{hex_c} -> {matched_hex} -> {recipe} (dist={lab_dist:.1f})")

            matched_shape = {
                **item,
                "geometry": item["geometry"],
                "recipe": recipe,
                "color": rgb,
                "match_color": query_rgb,
                "matched_rgb": matched_rgb,
                "lut_idx": int(lut_idx),
                "height_identity_rgb": height_identity_rgb,
                "original_recipe": list(original_recipe),
            }
            if callable(dynamic_metadata_for_fill):
                dynamic_recipe = dynamic_metadata_for_fill(query_rgb)
                if isinstance(dynamic_recipe, dict):
                    # Retain each colour's effective-depth recipe next to the
                    # padded physical recipe used by mesh extrusion.
                    matched_shape["material_dynamic_recipe"] = dynamic_recipe
            matched.append(matched_shape)

        if recipe_log_mode == "summary":
            _log.debug(
                "Recipe cache summary: unique_colors=%s, shapes=%s",
                len(color_cache),
                len(clipped_shapes),
            )
            if sample_logs:
                _log.debug("Recipe samples: %s", "; ".join(sample_logs))

        match_samples = []
        for item in matched[:8]:
            match_samples.append(
                {
                    "color": [int(c) for c in item.get("color", ())],
                    "match_color": [int(c) for c in item.get("match_color", ())],
                    "matched_rgb": [int(c) for c in item.get("matched_rgb", ())],
                    "recipe": [int(v) for v in item.get("recipe", ())],
                    "lut_idx": int(item.get("lut_idx", -1)),
                }
            )
        _log.debug(
            "Vector color match summary",
            extra={
                "event": "vector_diag_match_colors_summary",
                "shape_count": len(clipped_shapes),
                "matched_shape_count": len(matched),
                "unique_query_color_count": len(color_cache),
                "large_distance_count": large_distance_count,
                "large_distance_warning_count": large_distance_warning_count,
                "large_distance_suppressed_count": max(
                    0,
                    large_distance_count - large_distance_warning_count,
                ),
                "sample_first8": match_samples,
            },
        )
        return matched

    # ── Stage 5: Run-length extrusion ────────────────────────────────────

    @staticmethod
    def _build_channel_runs(recipe, layers_to_use, num_channels):
        """Build contiguous layer runs grouped by channel.

        Returns:
            dict[channel_id] -> list of (start_layer, end_layer)
        """
        runs_by_channel = {}
        if layers_to_use <= 0:
            return runs_by_channel

        run_start = 0
        run_channel = int(recipe[0])
        for z in range(1, layers_to_use + 1):
            current_channel = int(recipe[z]) if z < layers_to_use else None
            if current_channel != run_channel:
                if 0 <= run_channel < num_channels:
                    runs_by_channel.setdefault(run_channel, []).append((run_start, z - 1))
                run_start = z
                run_channel = current_channel

        return runs_by_channel

    @staticmethod
    def _extrude_spatial_geometry_group(
        geometry,
        *,
        height: float,
        z_offset: float,
        scale: float,
        stage: str,
        geometry_policy: VectorLayerGeometryPolicy | None = None,
    ) -> trimesh.Trimesh:
        """Build one auxiliary mesh leaf through canonical spatial groups.

        用统一规范空间组生成一个辅助网格叶子。
        """

        mesh = build_vector_layered_volume(
            [
                {
                    "geometry": geometry,
                    "height": float(height),
                    "z_offset": float(z_offset),
                }
            ],
            scale_mm_per_svg_unit=float(scale),
            policy=geometry_policy,
        )
        if mesh is None:
            raise ValueError("Vector auxiliary geometry produced no printable group")
        return mesh

    @staticmethod
    def _run_length_extrude(
        matched_shapes,
        num_layers,
        layer_h,
        num_channels,
        slot_names,
        scale_factor,
        face_up=False,
        optical_z_base=0.0,
        defer_materialization=False,
        geometry_policy: VectorLayerGeometryPolicy | None = None,
    ):
        """Collect each material's runs and build one stepped solid.

        Shapes sharing the same material and Z run are unioned in 2D.  All of
        one material's runs are then sent to the stepped-surface builder once,
        so internal Z contacts never become extra 3MF parts.  Callers that also
        need to add backing or coating slabs can defer that final materialization.

        When *face_up* is True the layer order is reversed so that
        recipe[N-1] sits at the lowest Z (just above *optical_z_base*)
        and recipe[0] at the highest Z — matching ``_build_voxel_matrix_faceup``
        semantics used by the raster path for 5-Color Extended.
        """
        # Group shapes by (channel, run) before canonical preparation.
        # Key: (channel_id, run_start, run_end)  Value: list of geometries
        matched_shapes = tuple(matched_shapes)
        run_groups: dict[tuple, list] = {}
        print_grid_mm = next((item[PRINT_GRID_KEY] for item in matched_shapes
                              if PRINT_GRID_KEY in item), None)
        skipped_empty = 0
        invalid_channel_runs = 0
        invalid_slot_runs = 0
        short_recipe_shapes = 0

        for item in matched_shapes:
            geom = item.get("print_geometry", item["geometry"])
            recipe = item["recipe"]
            if geom is None or geom.is_empty:
                skipped_empty += 1
                continue

            layers_to_use = min(num_layers, len(recipe))
            if len(recipe) < num_layers:
                short_recipe_shapes += 1
            runs_by_channel = VectorProcessor._build_channel_runs(recipe, layers_to_use, num_channels)
            invalid_channels = [
                int(ch_raw)
                for ch_raw in recipe[:layers_to_use]
                if int(ch_raw) < 0 or int(ch_raw) >= num_channels
            ]
            if invalid_channels:
                invalid_channel_runs += len(invalid_channels)
                _log.debug(
                    "Vector run dropped by channel guard",
                    extra={
                        "event": "vector_appearance_diag_run_dropped_by_channel_guard",
                        "invalid_channels": invalid_channels[:16],
                        "num_channels": int(num_channels),
                        "recipe": [int(v) for v in recipe],
                    },
                )

            for ch, runs in runs_by_channel.items():
                if ch >= len(slot_names):
                    invalid_slot_runs += len(runs)
                    _log.debug(
                        "Vector run dropped by slot guard",
                        extra={
                            "event": "vector_appearance_diag_run_dropped_by_slot_guard",
                            "channel": int(ch),
                            "run_count": len(runs),
                            "slot_count": len(slot_names),
                        },
                    )
                    continue
                for run_start, run_end in runs:
                    key = (ch, run_start, run_end)
                    run_groups.setdefault(key, []).append(geom)

        if skipped_empty:
            _log.debug(
                "Vector empty geometry skipped before extrusion",
                extra={
                    "event": "vector_diag_extrude_skipped_empty",
                    "skipped_count": int(skipped_empty),
                    "stage": "run_group_build",
                },
            )
        if short_recipe_shapes:
            _log.debug(
                "Vector shape recipe shorter than requested layers",
                extra={
                    "event": "vector_appearance_diag_shape_recipe_short",
                    "shape_count": int(short_recipe_shapes),
                    "num_layers": int(num_layers),
                },
            )
        run_summary = {
            "run_group_count": len(run_groups),
            "skipped_empty": int(skipped_empty),
            "invalid_channel_runs": int(invalid_channel_runs),
            "invalid_slot_runs": int(invalid_slot_runs),
        }
        _log.debug(
            "Vector run summary",
            extra={
                "event": "vector_appearance_diag_run_summary",
                **run_summary,
            },
        )
        stage_c_hist: dict[int, dict[int, int]] = {}
        for (ch, run_start, run_end), geoms in run_groups.items():
            for layer_idx in range(int(run_start), int(run_end) + 1):
                layer_hist = stage_c_hist.setdefault(int(layer_idx), {})
                layer_hist[int(ch)] = layer_hist.get(int(ch), 0) + len(geoms)
        _log.debug(
            "Vector run groups per layer/channel",
            extra={
                "event": "vector_diag_stage_c_run_groups_per_layer_channel",
                "per_layer_channel_shape_count": stage_c_hist,
                **run_summary,
            },
        )

        slabs_by_slot: dict[str, dict[str, object]] = {}
        stage_d_hist: dict[int, dict[int, int]] = {}
        for (ch, run_start, run_end), geoms in run_groups.items():
            slot_name = slot_names[ch]
            if slot_name not in slabs_by_slot:
                slabs_by_slot[slot_name] = {"slabs": [], "mat_id": ch}

            source_geoms = tuple(
                geom for geom in geoms if geom is not None and not geom.is_empty
            )
            run_geometry = _union_run_group_geometries(source_geoms)
            if run_geometry is None or run_geometry.is_empty:
                continue

            if face_up:
                inv_start = (num_layers - 1) - run_end
                inv_end = (num_layers - 1) - run_start
                z_bot = optical_z_base + inv_start * layer_h
                height = (inv_end - inv_start + 1) * layer_h
            else:
                z_bot = run_start * layer_h
                height = (run_end - run_start + 1) * layer_h

            slabs = slabs_by_slot[slot_name]["slabs"]
            assert isinstance(slabs, list)
            slabs.append(
                {
                    "geometry": run_geometry,
                    "z_offset": float(z_bot),
                    "height": float(height),
                    **({PRINT_GRID_KEY: float(print_grid_mm)}
                       if print_grid_mm is not None else {}),
                }
            )
            for layer_idx in range(int(run_start), int(run_end) + 1):
                layer_hist = stage_d_hist.setdefault(int(layer_idx), {})
                layer_hist[int(ch)] = layer_hist.get(int(ch), 0) + 1

        if defer_materialization:
            result_by_slot = slabs_by_slot
        else:
            result_by_slot = VectorProcessor._materialize_vector_slabs(
                slabs_by_slot,
                scale_factor=scale_factor,
                geometry_policy=geometry_policy,
            )

        _log.debug(
            "Vector built meshes per layer/channel",
            extra={
                "event": "vector_diag_stage_d_built_meshes_per_layer_channel",
                "per_layer_channel_mesh_count": stage_d_hist,
                "slot_count": len(result_by_slot),
            },
        )
        _log.debug(
            "Vector diagnostic debug dump",
            extra={
                "event": "vector_diag_debug_dump",
                "run_summary": run_summary,
                "slot_count": len(result_by_slot),
                "face_up": bool(face_up),
                "optical_z_base": float(optical_z_base),
            },
        )
        return result_by_slot

    @staticmethod
    def _materialize_vector_slabs(
        slabs_by_slot,
        *,
        scale_factor,
        geometry_policy: VectorLayerGeometryPolicy | None = None,
        timings: dict | None = None,
    ):
        """Build independent material volumes with bounded parallelism."""
        return materialize_material_meshes(
            slabs_by_slot, scale_factor=scale_factor,
            geometry_policy=geometry_policy,
            serial_builder=build_vector_layered_volume, timings=timings,
        )

    # ── Stage 7: Double-sided helper ─────────────────────────────────────

    @staticmethod
    def _add_double_sided_layers(
        matched_shapes,
        num_layers,
        layer_h,
        num_channels,
        slot_names,
        scale_factor,
        top_z_start,
        meshes_by_slot,
        defer_materialization=False,
        geometry_policy: VectorLayerGeometryPolicy | None = None,
    ):
        """Mirror colour layers above the backing for double-sided mode.

        Layer Z order is inverted so the viewing surface faces upward on
        the top side. Shapes sharing one material/layer run are canonicalized
        together, keeping the final 3MF part count independent of SVG shape
        count.
        """
        top_meshes_by_slot = VectorProcessor._run_length_extrude(
            matched_shapes=matched_shapes,
            num_layers=num_layers,
            layer_h=layer_h,
            num_channels=num_channels,
            slot_names=slot_names,
            scale_factor=scale_factor,
            face_up=True,
            optical_z_base=top_z_start,
            defer_materialization=defer_materialization,
            geometry_policy=geometry_policy,
        )
        payload_key = "slabs" if defer_materialization else "meshes"
        for slot_name, data in top_meshes_by_slot.items():
            target = meshes_by_slot.setdefault(
                slot_name,
                {payload_key: [], "mat_id": data["mat_id"]},
            )
            target[payload_key].extend(data[payload_key])

    # ── SVG parsing ──────────────────────────────────────────────────────

    def _parse_svg(self, svg_path: str, target_width_mm: float):
        """Parse SVG and return shapes in draw order with normalised coords.

        Returns:
            ``(shape_list, scale_factor, bbox_tuple)``
            where each shape item is ``{'poly': Polygon, 'color': (r,g,b)}``.
        """
        parse_expand_stroke_to_fill = bool(getattr(self, "_parse_expand_stroke_to_fill", True))
        parse_single_subpath_fast_path = bool(
            getattr(self, "_parse_single_subpath_fast_path", True)
        )
        parse_direct_top_level_paths_fast_path = bool(
            getattr(self, "_parse_direct_top_level_paths_fast_path", True)
        )
        if (
            parse_direct_top_level_paths_fast_path
            and not parse_expand_stroke_to_fill
        ):
            try:
                direct_result = _try_parse_strict_top_level_path_svg(
                    self,
                    svg_path,
                    target_width_mm,
                )
            except VECTOR_HANDLED_ERRORS:
                direct_result = None
            if direct_result is not None:
                return direct_result

        parsed_root, svg_parse_source = _filtered_svg_source_for_vector_parse(
            svg_path,
            parse_expand_stroke_to_fill=parse_expand_stroke_to_fill,
        )
        if svg_parse_source is None:
            svg_parse_source = svg_path
        arc_tolerance = (
            self.sampling_precision / max(target_width_mm / 100.0, 0.01)
            * _SVG_ARC_APPROXIMATION_BUDGET_RATIO
        )
        try:
            svg = parse_svg_document(svg_parse_source, arc_tolerance)
        except VECTOR_HANDLED_ERRORS as e:
            if svg_parse_source is not svg_path:
                try:
                    svg = parse_svg_document(svg_path, arc_tolerance)
                    parsed_root = None
                except VECTOR_HANDLED_ERRORS as fallback_error:
                    raise ValueError(f"Failed to parse SVG: {fallback_error}") from fallback_error
            else:
                raise ValueError(f"Failed to parse SVG: {e}") from e
        if svg is None:
            raise ValueError("No valid shapes found in SVG")

        image_vectorizer_origin = False
        root = parsed_root
        filtered_without_xml_root = root is None and svg_parse_source is not svg_path
        try:
            if root is None and not filtered_without_xml_root:
                root = ET.parse(svg_path).getroot()
            image_vectorizer_origin = root.get("data-lumina-origin") == "image-vectorizer"
        except VECTOR_HANDLED_ERRORS:
            root = None
            image_vectorizer_origin = False
        self._last_image_vectorizer_bounds = None
        gradient_defs = (
            {}
            if filtered_without_xml_root
            else VectorProcessor._parse_gradient_defs(svg_path, root=root)
        )
        clip_path_defs = {}
        document_elements_by_id = {}
        if root is not None:
            def _index_document_element(candidate):
                candidate_tag = _tag_local_name(candidate)
                clip_id = str(candidate.get("id", "") or "").strip()
                if clip_id:
                    document_elements_by_id.setdefault(clip_id, candidate)
                if clip_id and candidate_tag == "clipPath":
                    clip_path_defs[clip_id] = candidate
                for child in list(candidate):
                    _index_document_element(child)

            _index_document_element(root)
        _url_re = re.compile(r"url\(#([^)]+)\)")

        tol_svg = self.sampling_precision / max(target_width_mm / 100.0, 0.01)

        def _sample_segments_coords(path_obj, segments):
            if segments and len(segments) > 1:
                coords = _flatten_segments(segments, tol_svg)
            else:
                coords = _flatten_segments_fallback(path_obj, tol_svg)

            if segments:
                try:
                    last_end = segments[-1].end
                    last_pt = (last_end.x, last_end.y)
                    if coords and coords[-1] != last_pt:
                        coords.append(last_pt)
                except VECTOR_HANDLED_ERRORS:
                    pass
            return coords

        def _sample_path_coords(path_obj):
            try:
                segments = list(path_obj.segments())
            except VECTOR_FATAL_ERRORS:
                raise
            except Exception:
                segments = None
            return _sample_segments_coords(path_obj, segments)

        def _signed_ring_area(coords):
            if len(coords) < 3:
                return 0.0
            area = 0.0
            for (x1, y1), (x2, y2) in zip(coords, coords[1:] + coords[:1]):
                area += (float(x1) * float(y2)) - (float(x2) * float(y1))
            return area * 0.5

        def _polygon_from_coords(coords):
            if len(coords) < 3:
                return None

            poly = Polygon(coords)
            if not poly.is_valid:
                poly = make_valid(poly)
            poly = VectorProcessor._extract_polygonal_geometry(poly)

            if poly is not None and not poly.is_empty:
                return poly
            return None

        def _sample_path_to_polygon(path_obj):
            return _polygon_from_coords(_sample_path_coords(path_obj))

        def _single_subpath_item(path_obj):
            try:
                segments = list(path_obj.segments())
            except VECTOR_FATAL_ERRORS:
                raise
            except Exception:
                return None
            if not segments:
                return None

            move_count = 0
            for seg in segments:
                if isinstance(seg, Move):
                    move_count += 1
                    if move_count > 1:
                        return None

            coords = _sample_segments_coords(path_obj, segments)
            poly = _polygon_from_coords(coords)
            if poly is None:
                return None
            return {
                "poly": poly,
                "signed_area": _signed_ring_area(coords),
            }

        def _combine_nonzero_subpaths(subpath_items):
            """Merge subpaths using SVG nonzero winding orientation.

            SVG's default ``nonzero`` fill rule uses opposite winding
            direction for holes. A plain union turns those holes into solid
            paint, which is exactly what Vector Magic output does around
            small white foot / eye details.

            按 SVG 默认 nonzero 规则合并复合路径：反向子路径是洞，不能
            简单 union，否则白色细节会被深色路径填实。
            """
            if not subpath_items:
                return None
            if len(subpath_items) == 1:
                return subpath_items[0]["poly"]

            polygon_items = [
                item["poly"]
                for item in subpath_items
                if item.get("poly") is not None and not item["poly"].is_empty
            ]
            if (
                polygon_items
                and not _geometries_have_pairwise_intersections(polygon_items)
            ):
                return _polygonal_union_for_disjoint_items(polygon_items)
            try:
                boundaries = [
                    item["poly"].boundary
                    for item in subpath_items
                    if item.get("poly") is not None and not item["poly"].is_empty
                ]
                faces = list(polygonize(unary_union(boundaries))) if boundaries else []
                filled_faces = []
                for face in faces:
                    probe = face.representative_point()
                    winding = 0
                    for item in subpath_items:
                        poly = item["poly"]
                        if poly is None or poly.is_empty:
                            continue
                        if poly.contains(probe):
                            winding += 1 if item.get("signed_area", 0.0) >= 0 else -1
                    if winding != 0:
                        filled_faces.append(face)
                if filled_faces:
                    result = unary_union(filled_faces)
                    result = VectorProcessor._extract_polygonal_geometry(make_valid(result))
                    if result is not None and not result.is_empty:
                        return result
            except VECTOR_HANDLED_ERRORS:
                pass

            # Use the largest ring's orientation as the main paint
            # direction. Opposite-orientation rings inside it become holes;
            # disjoint opposite rings are still valid filled islands under
            # nonzero winding and are kept.
            dominant_sign = 1 if subpath_items[0]["signed_area"] >= 0 else -1
            try:
                dominant = max(
                    subpath_items,
                    key=lambda item: abs(float(item.get("signed_area", 0.0))),
                )
                dominant_sign = 1 if dominant["signed_area"] >= 0 else -1
            except (TypeError, ValueError):
                pass

            fill_polys = []
            opposite_polys = []
            for item in subpath_items:
                poly = item["poly"]
                if poly is None or poly.is_empty:
                    continue
                sign = 1 if item.get("signed_area", 0.0) >= 0 else -1
                if sign == dominant_sign:
                    fill_polys.append(poly)
                else:
                    opposite_polys.append(poly)

            if fill_polys:
                try:
                    combined = unary_union(fill_polys)
                except VECTOR_HANDLED_ERRORS:
                    combined = fill_polys[0]
            else:
                combined = None

            disjoint_opposite = []
            for hole in opposite_polys:
                if hole is None or hole.is_empty:
                    continue
                if combined is None or combined.is_empty:
                    disjoint_opposite.append(hole)
                    continue
                try:
                    if combined.intersects(hole) or combined.contains(hole):
                        combined = combined.difference(hole)
                    else:
                        disjoint_opposite.append(hole)
                except VECTOR_HANDLED_ERRORS:
                    disjoint_opposite.append(hole)

            pieces = []
            if combined is not None and not combined.is_empty:
                pieces.append(combined)
            pieces.extend(
                poly for poly in disjoint_opposite
                if poly is not None and not poly.is_empty
            )
            if not pieces:
                return None
            try:
                result = unary_union(pieces)
            except VECTOR_HANDLED_ERRORS:
                result = pieces[0]
            result = VectorProcessor._extract_polygonal_geometry(make_valid(result))
            return result if result is not None and not result.is_empty else None

        def _sample_path_to_stroke_geometry(
            path_obj, stroke_width_svg, cap_style_name="round", join_style_name="round"
        ):
            try:
                segments = list(path_obj.segments())
            except VECTOR_FATAL_ERRORS:
                raise
            except Exception:
                segments = None

            if segments and len(segments) > 1:
                coords = _flatten_segments(segments, tol_svg)
            else:
                coords = _flatten_segments_fallback(path_obj, tol_svg)

            if segments:
                try:
                    last_end = segments[-1].end
                    last_pt = (last_end.x, last_end.y)
                    if not coords or coords[-1] != last_pt:
                        coords.append(last_pt)
                except VECTOR_FATAL_ERRORS:
                    raise
                except Exception:
                    pass

            if len(coords) < 2:
                return None

            try:
                stroke_geom = LineString(coords).buffer(
                    max(float(stroke_width_svg) * 0.5, 1e-6),
                    cap_style=cap_style_name,
                    join_style=join_style_name,
                    mitre_limit=2.0,
                )
            except VECTOR_FATAL_ERRORS:
                raise
            except Exception:
                return None

            stroke_geom = VectorProcessor._extract_polygonal_geometry(make_valid(stroke_geom))
            if stroke_geom is not None and not stroke_geom.is_empty:
                return stroke_geom
            return None

        def _flatten_segments(segments, tolerance):
            """Adaptive de Casteljau flattening for each segment."""
            coords = []
            for seg in segments:
                if isinstance(seg, Move):
                    continue
                if isinstance(seg, (Line, Close)):
                    coords.append((seg.start.x, seg.start.y))
                elif isinstance(seg, CubicBezier):
                    start_pt = (seg.start.x, seg.start.y)
                    if not coords or coords[-1] != start_pt:
                        coords.append(start_pt)
                    _flatten_cubic(
                        seg.start.x,
                        seg.start.y,
                        seg.control1.x,
                        seg.control1.y,
                        seg.control2.x,
                        seg.control2.y,
                        seg.end.x,
                        seg.end.y,
                        tolerance,
                        coords,
                        0,
                    )
                elif isinstance(seg, QuadraticBezier):
                    start_pt = (seg.start.x, seg.start.y)
                    if not coords or coords[-1] != start_pt:
                        coords.append(start_pt)
                    _flatten_quadratic(
                        seg.start.x,
                        seg.start.y,
                        seg.control.x,
                        seg.control.y,
                        seg.end.x,
                        seg.end.y,
                        tolerance,
                        coords,
                        0,
                    )
                elif isinstance(seg, Arc):
                    start_pt = (seg.start.x, seg.start.y)
                    if not coords or coords[-1] != start_pt:
                        coords.append(start_pt)
                    coords.extend(_sample_arc_segment_points(seg, sample_count=10))
                else:
                    coords.append((seg.start.x, seg.start.y))
                    try:
                        for tv in np.linspace(0.1, 1.0, 10):
                            pt = seg.point(tv)
                            coords.append((pt.x, pt.y))
                    except VECTOR_FATAL_ERRORS:
                        raise
                    except Exception:
                        coords.append((seg.end.x, seg.end.y))
            return coords

        def _flatten_segments_fallback(path_obj, tolerance):
            """Fallback for paths that can't be decomposed into segments."""
            try:
                path_len = path_obj.length()
            except VECTOR_FATAL_ERRORS:
                raise
            except Exception:
                return []
            if path_len == 0:
                return []
            n = max(10, min(int(path_len / max(tolerance, 0.01)), 8000))
            t_vals = np.linspace(0, 1, n)
            pts = [path_obj.point(t) for t in t_vals]
            return [(p.x, p.y) for p in pts]

        clip_path_geometry_cache = {}

        def _matrix_to_shapely_params(matrix):
            return [
                matrix[0, 0],
                matrix[0, 1],
                matrix[1, 0],
                matrix[1, 1],
                matrix[0, 2],
                matrix[1, 2],
            ]

        def _style_property(style_value, property_name):
            resolved = None
            for declaration in str(style_value or "").split(";"):
                name, separator, value = declaration.partition(":")
                if separator and name.strip().lower() == property_name:
                    resolved = _normalize_svg_css_token(value)
            return resolved

        def _clip_rule_from_definition(definition):
            clip_rule = _normalize_svg_css_token(
                definition.get("clip-rule", "nonzero")
            )
            style_clip_rule = _style_property(
                definition.get("style", ""),
                "clip-rule",
            )
            if style_clip_rule is not None:
                clip_rule = style_clip_rule
            return clip_rule if clip_rule in {"evenodd", "nonzero"} else "nonzero"

        def _clip_rule_from_element_values(values, inherited_rule):
            if not isinstance(values, dict):
                return inherited_rule
            clip_rule = values.get("clip-rule")
            attributes = values.get("attributes")
            if isinstance(attributes, dict):
                if attributes.get("clip-rule") is not None:
                    clip_rule = attributes.get("clip-rule")
                style_clip_rule = _style_property(
                    attributes.get("style", ""),
                    "clip-rule",
                )
                if style_clip_rule is not None:
                    clip_rule = style_clip_rule
            normalized = _normalize_svg_css_token(clip_rule)
            return (
                normalized
                if normalized in {"evenodd", "nonzero"}
                else inherited_rule
            )

        def _referenced_document_ids(element):
            references = []
            href_keys = (
                "href",
                "{http://www.w3.org/1999/xlink}href",
            )
            for candidate in element.iter():
                for key in href_keys:
                    raw_reference = str(candidate.get(key, "") or "").strip()
                    if raw_reference.startswith("#") and len(raw_reference) > 1:
                        references.append(raw_reference[1:])
            return references

        def _append_clip_reference_definitions(fragment, definition):
            ordered_dependencies = []
            seen_ids = {str(definition.get("id", "") or "").strip()}

            def _collect_dependency(reference_id):
                if not reference_id or reference_id in seen_ids:
                    return
                seen_ids.add(reference_id)
                dependency = document_elements_by_id.get(reference_id)
                if dependency is None:
                    return
                for nested_id in _referenced_document_ids(dependency):
                    _collect_dependency(nested_id)
                ordered_dependencies.append(dependency)

            for reference_id in _referenced_document_ids(definition):
                _collect_dependency(reference_id)
            if not ordered_dependencies:
                return

            svg_ns = "http://www.w3.org/2000/svg"
            dependency_defs = ET.SubElement(fragment, f"{{{svg_ns}}}defs")
            for dependency in ordered_dependencies:
                dependency_defs.append(deepcopy(dependency))

        def _resolve_clip_fragment_percentages(fragment, viewport):
            viewport_width, viewport_height = viewport
            diagonal = math.hypot(viewport_width, viewport_height) / math.sqrt(2.0)
            references = {
                "x": viewport_width,
                "x1": viewport_width,
                "x2": viewport_width,
                "cx": viewport_width,
                "rx": viewport_width,
                "width": viewport_width,
                "y": viewport_height,
                "y1": viewport_height,
                "y2": viewport_height,
                "cy": viewport_height,
                "ry": viewport_height,
                "height": viewport_height,
                "r": diagonal,
            }
            for candidate in fragment.iter():
                for attribute_name, reference in references.items():
                    raw_value = str(
                        candidate.get(attribute_name, "") or ""
                    ).strip()
                    if not raw_value.endswith("%"):
                        continue
                    try:
                        resolved = Length(raw_value).value(
                            ppi=96.0,
                            relative_length=reference,
                        )
                        parsed = float(resolved)
                    except (TypeError, ValueError, AttributeError):
                        continue
                    if math.isfinite(parsed):
                        candidate.set(attribute_name, format(parsed, ".12g"))

        def _clip_path_base_geometry(clip_id, reference_viewport=None):
            definition = clip_path_defs.get(clip_id)
            if definition is None:
                return None

            clip_units = str(
                definition.get("clipPathUnits", "userSpaceOnUse")
                or "userSpaceOnUse"
            ).strip()
            resolved_viewport = reference_viewport or (
                root_user_width,
                root_user_height,
            )
            cache_key = (
                clip_id,
                float(resolved_viewport[0]),
                float(resolved_viewport[1]),
            )
            if cache_key in clip_path_geometry_cache:
                return clip_path_geometry_cache[cache_key]

            svg_ns = "http://www.w3.org/2000/svg"
            fragment = ET.Element(f"{{{svg_ns}}}svg")
            fragment.set("width", str(resolved_viewport[0]))
            fragment.set("height", str(resolved_viewport[1]))
            _append_clip_reference_definitions(fragment, definition)
            for child in list(definition):
                fragment.append(deepcopy(child))
            _resolve_clip_fragment_percentages(fragment, resolved_viewport)

            try:
                clip_svg = parse_svg_document(
                    io.BytesIO(ET.tostring(fragment, encoding="utf-8")),
                    arc_tolerance,
                )
            except VECTOR_HANDLED_ERRORS as exc:
                raise ValueError("Failed to resolve SVG clip path") from exc
            clip_polys = []
            definition_clip_rule = _clip_rule_from_definition(definition)
            for clip_element in clip_svg.elements():
                if not isinstance(clip_element, (Path, Shape)):
                    continue
                if _svg_element_hidden_by_visibility(clip_element):
                    continue
                if isinstance(clip_element, Shape) and not isinstance(clip_element, Path):
                    try:
                        clip_element = Path(clip_element)
                    except VECTOR_HANDLED_ERRORS:
                        continue

                subpath_items = []
                try:
                    subpaths = list(clip_element.as_subpaths())
                except VECTOR_HANDLED_ERRORS:
                    subpaths = []
                for subpath in subpaths:
                    try:
                        sub_path = subpath if isinstance(subpath, Path) else Path(subpath)
                        coords = _sample_path_coords(sub_path)
                        poly = _polygon_from_coords(coords)
                    except VECTOR_HANDLED_ERRORS:
                        continue
                    if poly is not None and not poly.is_empty:
                        subpath_items.append(
                            {
                                "poly": poly,
                                "signed_area": _signed_ring_area(coords),
                            }
                        )

                if not subpath_items:
                    fallback_poly = _sample_path_to_polygon(clip_element)
                    if fallback_poly is not None and not fallback_poly.is_empty:
                        clip_polys.append(fallback_poly)
                    continue

                values = getattr(clip_element, "values", None)
                clip_rule = _clip_rule_from_element_values(
                    values,
                    definition_clip_rule,
                )
                subpath_polys = [item["poly"] for item in subpath_items]
                if len(subpath_items) == 1:
                    combined = subpath_items[0]["poly"]
                elif clip_rule == "evenodd":
                    combined = _combine_evenodd_polygons(subpath_polys)
                else:
                    combined = _combine_nonzero_subpaths(subpath_items)
                if combined is not None and not combined.is_empty:
                    clip_polys.append(combined)

            if clip_polys:
                geometry = VectorProcessor._extract_polygonal_geometry(
                    make_valid(unary_union(clip_polys))
                )
            else:
                geometry = Polygon()
            clip_path_geometry_cache[cache_key] = geometry
            return geometry

        group_clip_contexts_by_element = {}
        element_geometry_corrections = {}
        element_geometry_viewport_clips = {}
        element_clip_reference_viewports = {}
        clip_target_transform_overrides = {}

        def _finite_float(value, default=None):
            try:
                parsed = float(value)
            except (TypeError, ValueError):
                return default
            return parsed if math.isfinite(parsed) else default

        def _element_value(element, name, default=None):
            if element is None:
                return default
            if isinstance(element, dict):
                value = element.get(name)
                attributes = element.get("attributes")
                if value is None and isinstance(attributes, dict):
                    value = attributes.get(name)
                return default if value is None else value
            getter = getattr(element, "get", None)
            if callable(getter):
                value = getter(name)
                return default if value is None else value
            values = getattr(element, "values", None)
            return _element_value(values, name, default)

        def _view_box_values(element):
            if element is None:
                return None
            values = [
                _finite_float(token)
                for token in re.split(
                    r"[\s,]+",
                    str(_element_value(element, "viewBox", "") or "").strip(),
                )
                if token
            ]
            if len(values) != 4 or any(value is None for value in values):
                return None
            min_x, min_y, width, height = values
            if width <= 0.0 or height <= 0.0:
                return None
            return min_x, min_y, width, height

        def _viewport_length(value, reference, default):
            if value is None:
                return default
            raw_value = str(value).strip()
            try:
                resolved = Length(raw_value).value(
                    ppi=96.0,
                    relative_length=reference,
                )
            except (TypeError, ValueError, AttributeError):
                return default
            return _finite_float(resolved, default)

        def _view_box_viewport_matrix(
            view_box,
            viewport_x,
            viewport_y,
            viewport_width,
            viewport_height,
            preserve_aspect_ratio,
        ):
            if view_box is None:
                return np.array(
                    [
                        [1.0, 0.0, viewport_x],
                        [0.0, 1.0, viewport_y],
                        [0.0, 0.0, 1.0],
                    ],
                    dtype=np.float64,
                )
            min_x, min_y, view_width, view_height = view_box
            if viewport_width <= 0.0 or viewport_height <= 0.0:
                return None

            aspect_tokens = [
                token
                for token in str(
                    preserve_aspect_ratio or "xMidYMid meet"
                ).replace(",", " ").split()
                if token.lower() != "defer"
            ]
            alignment = aspect_tokens[0] if aspect_tokens else "xMidYMid"
            meet_or_slice = (
                aspect_tokens[1].lower()
                if len(aspect_tokens) > 1
                else "meet"
            )

            scale_x = viewport_width / view_width
            scale_y = viewport_height / view_height
            if alignment.lower() == "none":
                return np.array(
                    [
                        [scale_x, 0.0, viewport_x - min_x * scale_x],
                        [0.0, scale_y, viewport_y - min_y * scale_y],
                        [0.0, 0.0, 1.0],
                    ],
                    dtype=np.float64,
                )

            scale = (
                max(scale_x, scale_y)
                if meet_or_slice == "slice"
                else min(scale_x, scale_y)
            )
            normalized_alignment = alignment.lower()
            x_factor = (
                0.0
                if normalized_alignment.startswith("xmin")
                else 1.0
                if normalized_alignment.startswith("xmax")
                else 0.5
            )
            y_factor = (
                0.0
                if normalized_alignment.endswith("ymin")
                else 1.0
                if normalized_alignment.endswith("ymax")
                else 0.5
            )
            offset_x = viewport_x + (viewport_width - view_width * scale) * x_factor
            offset_y = viewport_y + (viewport_height - view_height * scale) * y_factor
            return np.array(
                [
                    [scale, 0.0, offset_x - min_x * scale],
                    [0.0, scale, offset_y - min_y * scale],
                    [0.0, 0.0, 1.0],
                ],
                dtype=np.float64,
            )

        root_view_box = _view_box_values(root)
        root_user_width = (
            root_view_box[2]
            if root_view_box is not None
            else _finite_float(getattr(svg, "width", None), 100.0)
        )
        root_user_height = (
            root_view_box[3]
            if root_view_box is not None
            else _finite_float(getattr(svg, "height", None), 100.0)
        )
        root_output_width = _finite_float(getattr(svg, "width", None), root_user_width)
        root_output_height = _finite_float(getattr(svg, "height", None), root_user_height)
        root_output_viewport_clip = (
            box(0.0, 0.0, root_output_width, root_output_height)
            if root_output_width > 0.0 and root_output_height > 0.0
            else None
        )

        def _symbol_use_viewport_matrix(container, parent_user_size):
            values = getattr(container, "values", None)
            if not isinstance(values, dict) or values.get("tag") != "use":
                return None
            attributes = values.get("attributes")
            attributes = attributes if isinstance(attributes, dict) else {}
            href = str(
                attributes.get("href")
                or attributes.get("{http://www.w3.org/1999/xlink}href")
                or values.get("href", "")
                or ""
            ).strip()
            if not href.startswith("#"):
                return None
            symbol = document_elements_by_id.get(href[1:])
            if symbol is None or _tag_local_name(symbol) != "symbol":
                return None

            view_box = _view_box_values(symbol)
            if view_box is None:
                return None

            parent_user_width, parent_user_height = parent_user_size
            viewport_x = _viewport_length(
                attributes.get("x"),
                parent_user_width,
                0.0,
            )
            viewport_y = _viewport_length(
                attributes.get("y"),
                parent_user_height,
                0.0,
            )
            viewport_width = _viewport_length(
                attributes.get("width"),
                parent_user_width,
                parent_user_width,
            )
            viewport_height = _viewport_length(
                attributes.get("height"),
                parent_user_height,
                parent_user_height,
            )
            if viewport_width <= 0.0 or viewport_height <= 0.0:
                return None

            raw_aspect_ratio = str(
                symbol.get("preserveAspectRatio")
                or "xMidYMid meet"
            ).strip()
            viewport_matrix = _view_box_viewport_matrix(
                view_box,
                viewport_x,
                viewport_y,
                viewport_width,
                viewport_height,
                raw_aspect_ratio,
            )
            if viewport_matrix is None:
                return None
            overflow = _normalize_svg_css_token(symbol.get("overflow", ""))
            style_overflow = _style_property(symbol.get("style", ""), "overflow")
            if style_overflow is not None:
                overflow = style_overflow
            return viewport_matrix, (
                viewport_x,
                viewport_y,
                viewport_width,
                viewport_height,
            ), overflow != "visible", (view_box[2], view_box[3])

        def _use_viewport_context(container, parent_user_size):
            viewport = _symbol_use_viewport_matrix(
                container,
                parent_user_size,
            )
            if viewport is None:
                return None
            (
                viewport_matrix,
                viewport_bounds,
                clips_to_viewport,
                child_user_size,
            ) = viewport
            values = getattr(container, "values", None)
            current_transform = _parse_svg_transform(values.get("transform", ""))
            parsed_position = np.eye(3, dtype=np.float64)
            parsed_position[0, 2] = _viewport_length(
                values.get("x"),
                parent_user_size[0],
                0.0,
            )
            parsed_position[1, 2] = _viewport_length(
                values.get("y"),
                parent_user_size[1],
                0.0,
            )
            try:
                target_transform = current_transform @ np.linalg.inv(parsed_position)
                mapped_viewport_transform = target_transform @ viewport_matrix
                correction = (
                    mapped_viewport_transform @ np.linalg.inv(current_transform)
                )
            except np.linalg.LinAlgError:
                return None
            viewport_x, viewport_y, viewport_width, viewport_height = viewport_bounds
            viewport_clip = (
                affinity.affine_transform(
                    box(
                        viewport_x,
                        viewport_y,
                        viewport_x + viewport_width,
                        viewport_y + viewport_height,
                    ),
                    _matrix_to_shapely_params(target_transform),
                )
                if clips_to_viewport
                else None
            )
            return correction, target_transform, viewport_clip, child_user_size

        def _nested_svg_viewport_context(container, parent_user_size):
            values = getattr(container, "values", None)
            if (
                container is svg
                or not isinstance(values, dict)
                or values.get("tag") != "svg"
            ):
                return None

            parent_user_width, parent_user_height = parent_user_size
            attributes = values.get("attributes")
            attributes = attributes if isinstance(attributes, dict) else {}
            view_box = _view_box_values(attributes)
            viewport_x = _viewport_length(
                attributes.get("x"),
                parent_user_width,
                0.0,
            )
            viewport_y = _viewport_length(
                attributes.get("y"),
                parent_user_height,
                0.0,
            )
            viewport_width = _viewport_length(
                attributes.get("width"),
                parent_user_width,
                parent_user_width,
            )
            viewport_height = _viewport_length(
                attributes.get("height"),
                parent_user_height,
                parent_user_height,
            )
            if viewport_width <= 0.0 or viewport_height <= 0.0:
                return None

            viewport_matrix = _view_box_viewport_matrix(
                view_box,
                viewport_x,
                viewport_y,
                viewport_width,
                viewport_height,
                attributes.get("preserveAspectRatio"),
            )
            if viewport_matrix is None:
                return None
            parent_transform = _parse_svg_transform(values.get("transform", ""))
            target_transform = parent_transform @ viewport_matrix
            geometry_correction = None
            if view_box is None:
                try:
                    geometry_correction = (
                        parent_transform
                        @ viewport_matrix
                        @ np.linalg.inv(parent_transform)
                    )
                except np.linalg.LinAlgError:
                    return None

            overflow = _normalize_svg_css_token(
                attributes.get("overflow", "")
            )
            style_overflow = _style_property(
                attributes.get("style", ""),
                "overflow",
            )
            if style_overflow is not None:
                overflow = style_overflow
            viewport_clip = (
                affinity.affine_transform(
                    box(
                        viewport_x,
                        viewport_y,
                        viewport_x + viewport_width,
                        viewport_y + viewport_height,
                    ),
                    _matrix_to_shapely_params(parent_transform),
                )
                if overflow != "visible"
                else None
            )
            child_user_size = (
                (view_box[2], view_box[3])
                if view_box is not None
                else (viewport_width, viewport_height)
            )
            inherited_coordinate_offset = (
                _viewport_length(
                    attributes.get("x"),
                    child_user_size[0],
                    0.0,
                ),
                _viewport_length(
                    attributes.get("y"),
                    child_user_size[1],
                    0.0,
                ),
            )
            return (
                target_transform,
                viewport_clip,
                inherited_coordinate_offset,
                child_user_size,
                geometry_correction,
            )

        def _coordinate_offsets_for_use_children(
            container,
            coordinate_offsets,
            position_resolved_by_viewport=False,
        ):
            if not coordinate_offsets:
                return coordinate_offsets
            values = getattr(container, "values", None)
            if not isinstance(values, dict) or values.get("tag") != "use":
                return coordinate_offsets
            attributes = values.get("attributes")
            attributes = attributes if isinstance(attributes, dict) else {}
            if (
                not position_resolved_by_viewport
                and "x" not in attributes
                and "y" not in attributes
            ):
                return coordinate_offsets
            offset_x, offset_y = coordinate_offsets[-1]
            return (
                *coordinate_offsets[:-1],
                (
                    0.0
                    if position_resolved_by_viewport or "x" in attributes
                    else offset_x,
                    0.0
                    if position_resolved_by_viewport or "y" in attributes
                    else offset_y,
                ),
            )

        def _geometry_correction_for_element(
            element,
            fixed_correction,
            coordinate_offsets,
        ):
            correction = fixed_correction
            if not coordinate_offsets:
                return correction
            values = getattr(element, "values", None)
            if not isinstance(values, dict):
                return correction
            element_tag = str(values.get("tag", "") or "").strip()
            if element_tag not in {"rect", "image", "use", "svg"}:
                return correction
            attributes = values.get("attributes")
            attributes = attributes if isinstance(attributes, dict) else {}
            current_transform = _parse_svg_transform(
                values.get("transform", "")
            )
            try:
                inverse = np.linalg.inv(current_transform)
            except np.linalg.LinAlgError:
                return correction
            offset_x, offset_y = coordinate_offsets[-1]
            resolved_offset_x = offset_x if "x" not in attributes else 0.0
            resolved_offset_y = offset_y if "y" not in attributes else 0.0
            if resolved_offset_x == 0.0 and resolved_offset_y == 0.0:
                return correction
            local_offset = np.eye(3, dtype=np.float64)
            local_offset[0, 2] = -resolved_offset_x
            local_offset[1, 2] = -resolved_offset_y
            offset_correction = current_transform @ local_offset @ inverse
            correction = (
                offset_correction
                if correction is None
                else correction @ offset_correction
            )
            return correction

        def _index_group_clip_contexts(
            container,
            inherited_contexts=(),
            inherited_geometry_correction=None,
            inherited_viewport_clip=None,
            inherited_coordinate_offsets=(),
            parent_user_size=None,
        ):
            if isinstance(container, (Path, Shape)):
                return
            contexts = inherited_contexts
            values = getattr(container, "values", None)
            raw_reference = (
                str(values.get("clip-path", "") or "").strip()
                if isinstance(values, dict)
                else ""
            )
            match = _url_re.fullmatch(raw_reference)
            if match is not None:
                contexts = (*contexts, (match.group(1), container))

            geometry_correction = inherited_geometry_correction
            viewport_clip = inherited_viewport_clip
            coordinate_offsets = inherited_coordinate_offsets
            child_user_size = parent_user_size or (
                root_user_width,
                root_user_height,
            )
            if geometry_correction is not None and isinstance(values, dict):
                clip_target_transform_overrides[id(container)] = (
                    geometry_correction
                    @ _parse_svg_transform(values.get("transform", ""))
                )
            viewport_context = _use_viewport_context(
                container,
                child_user_size,
            )
            if viewport_context is not None:
                (
                    viewport_correction,
                    target_transform,
                    own_viewport_clip,
                    child_user_size,
                ) = viewport_context
                clip_target_transform_overrides[id(container)] = (
                    target_transform
                    if inherited_geometry_correction is None
                    else inherited_geometry_correction @ target_transform
                )
                if (
                    own_viewport_clip is not None
                    and inherited_geometry_correction is not None
                ):
                    own_viewport_clip = affinity.affine_transform(
                        own_viewport_clip,
                        _matrix_to_shapely_params(inherited_geometry_correction),
                    )
                geometry_correction = (
                    viewport_correction
                    if geometry_correction is None
                    else geometry_correction @ viewport_correction
                )
                if own_viewport_clip is not None:
                    viewport_clip = (
                        own_viewport_clip
                        if viewport_clip is None
                        else viewport_clip.intersection(own_viewport_clip)
                    )
                if root_output_viewport_clip is not None:
                    viewport_clip = (
                        root_output_viewport_clip
                        if viewport_clip is None
                        else viewport_clip.intersection(root_output_viewport_clip)
                    )

            nested_viewport_context = _nested_svg_viewport_context(
                container,
                child_user_size,
            )
            if nested_viewport_context is not None:
                (
                    nested_target_transform,
                    own_viewport_clip,
                    coordinate_offset,
                    child_user_size,
                    nested_geometry_correction,
                ) = nested_viewport_context
                element_clip_reference_viewports[id(container)] = child_user_size
                clip_target_transform_overrides[id(container)] = (
                    nested_target_transform
                    if geometry_correction is None
                    else geometry_correction @ nested_target_transform
                )
                if (
                    own_viewport_clip is not None
                    and geometry_correction is not None
                ):
                    own_viewport_clip = affinity.affine_transform(
                        own_viewport_clip,
                        _matrix_to_shapely_params(geometry_correction),
                    )
                if own_viewport_clip is not None:
                    viewport_clip = (
                        own_viewport_clip
                        if viewport_clip is None
                        else viewport_clip.intersection(own_viewport_clip)
                    )
                if root_output_viewport_clip is not None:
                    viewport_clip = (
                        root_output_viewport_clip
                        if viewport_clip is None
                        else viewport_clip.intersection(root_output_viewport_clip)
                    )
                if nested_geometry_correction is not None:
                    geometry_correction = (
                        nested_geometry_correction
                        if geometry_correction is None
                        else geometry_correction @ nested_geometry_correction
                    )
                coordinate_offsets = (*coordinate_offsets, coordinate_offset)

            coordinate_offsets = _coordinate_offsets_for_use_children(
                container,
                coordinate_offsets,
                position_resolved_by_viewport=viewport_context is not None,
            )

            try:
                for child in container:
                    group_clip_contexts_by_element[id(child)] = contexts
                    element_clip_reference_viewports[id(child)] = child_user_size
                    child_correction = _geometry_correction_for_element(
                        child,
                        geometry_correction,
                        coordinate_offsets,
                    )
                    if child_correction is not None:
                        element_geometry_corrections[id(child)] = child_correction
                    child_values = getattr(child, "values", None)
                    if (
                        geometry_correction is not None
                        and isinstance(child_values, dict)
                    ):
                        clip_target_transform_overrides[id(child)] = (
                            geometry_correction
                            @ _parse_svg_transform(
                                child_values.get("transform", "")
                            )
                        )
                    if viewport_clip is not None:
                        element_geometry_viewport_clips[id(child)] = viewport_clip
                    if not isinstance(child, (Path, Shape)):
                        _index_group_clip_contexts(
                            child,
                            contexts,
                            geometry_correction,
                            viewport_clip,
                            coordinate_offsets,
                            child_user_size,
                        )
            except TypeError:
                return

        _index_group_clip_contexts(svg)
        clip_target_local_bounds_cache = {}

        def _iter_clip_target_shapes(target):
            if isinstance(target, (Path, Shape)):
                yield target
                return
            try:
                for child in target:
                    yield from _iter_clip_target_shapes(child)
            except TypeError:
                return

        def _clip_bbox_shape_is_display_none(element):
            values = getattr(element, "values", None)
            display_values = []
            style_values = []
            if isinstance(values, dict):
                display_values.append(values.get("display"))
                style_values.append(values.get("style"))
                attributes = values.get("attributes")
                if isinstance(attributes, dict):
                    display_values.append(attributes.get("display"))
                    style_values.append(attributes.get("style"))
            display_values.append(getattr(element, "display", None))
            style_values.append(getattr(element, "style", None))
            if any(
                _normalize_svg_css_token(value) == "none"
                for value in display_values
            ):
                return True
            return any(
                _style_property(style, "display") == "none"
                for style in style_values
            )

        def _clip_target_local_bounds(target):
            cache_key = id(target)
            if cache_key in clip_target_local_bounds_cache:
                return clip_target_local_bounds_cache[cache_key]

            values = getattr(target, "values", None)
            transform = clip_target_transform_overrides.get(
                id(target),
                _parse_svg_transform(
                    values.get("transform", "") if isinstance(values, dict) else ""
                ),
            )
            try:
                inverse = np.linalg.inv(transform)
            except np.linalg.LinAlgError as exc:
                raise ValueError("Invalid transform for SVG clip target") from exc

            local_points = []
            for target_shape in _iter_clip_target_shapes(target):
                if _clip_bbox_shape_is_display_none(target_shape):
                    continue
                try:
                    target_path = (
                        target_shape
                        if isinstance(target_shape, Path)
                        else Path(target_shape)
                    )
                    subpaths = list(target_path.as_subpaths())
                except VECTOR_HANDLED_ERRORS:
                    continue
                for subpath in subpaths:
                    try:
                        path = subpath if isinstance(subpath, Path) else Path(subpath)
                        coords = _sample_path_coords(path)
                    except VECTOR_HANDLED_ERRORS:
                        continue
                    if not coords:
                        continue
                    points = np.asarray(coords, dtype=np.float64)
                    homogeneous = np.column_stack(
                        (points, np.ones(points.shape[0], dtype=np.float64))
                    )
                    correction = element_geometry_corrections.get(id(target_shape))
                    if correction is not None:
                        homogeneous = (correction @ homogeneous.T).T
                    local_points.append((inverse @ homogeneous.T).T[:, :2])

            if not local_points:
                raise ValueError("Failed to resolve SVG clip target bounds")
            all_points = np.concatenate(local_points, axis=0)
            bounds = (
                float(np.min(all_points[:, 0])),
                float(np.min(all_points[:, 1])),
                float(np.max(all_points[:, 0])),
                float(np.max(all_points[:, 1])),
            )
            clip_target_local_bounds_cache[cache_key] = bounds
            return bounds

        def _apply_clip_reference(geometry, clip_id, target):
            definition = clip_path_defs.get(clip_id)
            if definition is None:
                return geometry
            units = str(
                definition.get("clipPathUnits", "userSpaceOnUse")
                or "userSpaceOnUse"
            ).strip()
            reference_viewport = element_clip_reference_viewports.get(
                id(target),
                (root_user_width, root_user_height),
            )
            clip_geometry = _clip_path_base_geometry(
                clip_id,
                reference_viewport,
            )
            if clip_geometry is None:
                return geometry
            if clip_geometry.is_empty:
                return clip_geometry

            target_values = getattr(target, "values", None)
            target_transform = clip_target_transform_overrides.get(
                id(target),
                _parse_svg_transform(
                    target_values.get("transform", "")
                    if isinstance(target_values, dict)
                    else ""
                ),
            )
            definition_transform = _parse_svg_transform(
                definition.get("transform", "")
            )
            if units == "objectBoundingBox":
                min_x, min_y, max_x, max_y = _clip_target_local_bounds(target)
                bbox_transform = np.array(
                    [
                        [max_x - min_x, 0.0, min_x],
                        [0.0, max_y - min_y, min_y],
                        [0.0, 0.0, 1.0],
                    ],
                    dtype=np.float64,
                )
                clip_transform = (
                    target_transform @ definition_transform @ bbox_transform
                )
            else:
                clip_transform = target_transform @ definition_transform
            resolved_clip = affinity.affine_transform(
                clip_geometry,
                _matrix_to_shapely_params(clip_transform),
            )

            clipped = geometry.intersection(resolved_clip)
            if clipped.is_empty:
                return clipped
            return VectorProcessor._extract_polygonal_geometry(make_valid(clipped))

        def _apply_element_geometry_correction(geometry, source_element):
            if geometry is None or geometry.is_empty:
                return geometry
            correction = element_geometry_corrections.get(id(source_element))
            if correction is not None:
                geometry = affinity.affine_transform(
                    geometry,
                    _matrix_to_shapely_params(correction),
                )
            viewport_clip = element_geometry_viewport_clips.get(id(source_element))
            if viewport_clip is None:
                return geometry
            clipped = geometry.intersection(viewport_clip)
            if clipped.is_empty:
                return clipped
            return VectorProcessor._extract_polygonal_geometry(make_valid(clipped))

        def _apply_element_clip_path(
            geometry,
            element,
            group_clip_contexts=(),
        ):
            if geometry is None or geometry.is_empty:
                return geometry
            for clip_id, clip_target in group_clip_contexts:
                geometry = _apply_clip_reference(geometry, clip_id, clip_target)
                if geometry is None or geometry.is_empty:
                    return geometry

            values = getattr(element, "values", None)
            if not isinstance(values, dict):
                return geometry
            raw_reference = str(values.get("clip-path", "") or "").strip()
            match = _url_re.fullmatch(raw_reference)
            if match is None:
                return geometry

            return _apply_clip_reference(geometry, match.group(1), element)

        raw_shapes = []
        needs_normalize_key = "_needs_contour_normalize"
        skipped_types = {}
        skipped_gradient_count = 0
        skipped_polygon_count = 0
        _log.debug("Parsing SVG geometry...")

        def _sample_stroke_geometry(path_obj, stroke_width_svg, cap_style_name="round", join_style_name="round"):
            try:
                segments = list(path_obj.segments())
            except VECTOR_FATAL_ERRORS:
                raise
            except Exception:
                segments = None

            if segments and len(segments) > 1:
                coords = _flatten_segments(segments, tol_svg)
            else:
                coords = _flatten_segments_fallback(path_obj, tol_svg)

            if len(coords) < 2:
                return None

            try:
                stroke_geom = LineString(coords).buffer(
                    max(float(stroke_width_svg) * 0.5, 1e-6),
                    cap_style=cap_style_name,
                    join_style=join_style_name,
                    mitre_limit=2.0,
                )
                stroke_geom = VectorProcessor._extract_polygonal_geometry(make_valid(stroke_geom))
                return stroke_geom if stroke_geom is not None and not stroke_geom.is_empty else None
            except VECTOR_FATAL_ERRORS:
                raise
            except Exception:
                return None

        for element in svg.elements():
            if not isinstance(element, (Path, Shape)):
                type_name = type(element).__name__
                skipped_types[type_name] = skipped_types.get(type_name, 0) + 1
                continue

            clip_source_element = element
            group_clip_contexts = group_clip_contexts_by_element.get(
                id(element),
                (),
            )

            if (
                _svg_element_hidden_by_visibility(element)
                or _svg_element_opacity(element) < 0.01
            ):
                continue

            has_fill = (
                element.fill is not None
                and element.fill.value is not None
                and str(element.fill.value).lower() != "none"
            )
            has_stroke = (
                getattr(element, "stroke", None) is not None
                and getattr(element.stroke, "value", None) is not None
                and str(element.stroke.value).lower() != "none"
            )
            stroke_rgb = None
            stroke_hex = None
            stroke_width = 0.0
            if has_stroke and parse_expand_stroke_to_fill:
                stroke_hex = _color_object_to_hex(getattr(element, "stroke", None))
                try:
                    stroke_rgb = (element.stroke.red, element.stroke.green, element.stroke.blue)
                except (AttributeError, TypeError, ValueError):
                    stroke_rgb = None
                try:
                    stroke_width = float(getattr(element, "stroke_width", 0.0) or 0.0)
                except VECTOR_FATAL_ERRORS:
                    raise
                except Exception:
                    stroke_width = 0.0
            if not has_fill:
                if has_stroke and parse_expand_stroke_to_fill:
                    stroke_modeled = False
                    if isinstance(element, Shape) and not isinstance(element, Path):
                        try:
                            element = Path(element)
                        except VECTOR_FATAL_ERRORS:
                            raise
                        except Exception:
                            continue

                    if stroke_rgb is not None and stroke_width > 0.0:
                        try:
                            linecap = str(getattr(element, "stroke_linecap", None) or "round").strip().lower()
                        except VECTOR_FATAL_ERRORS:
                            raise
                        except Exception:
                            linecap = "round"
                        try:
                            linejoin = str(getattr(element, "stroke_linejoin", None) or "round").strip().lower()
                        except VECTOR_FATAL_ERRORS:
                            raise
                        except Exception:
                            linejoin = "round"
                        cap_style = "flat" if linecap == "butt" else ("square" if linecap == "square" else "round")
                        join_style = "mitre" if linejoin == "miter" else linejoin
                        stroke_geom = _sample_path_to_stroke_geometry(
                            element,
                            stroke_width,
                            cap_style_name=cap_style,
                            join_style_name=join_style,
                        )
                        stroke_geom = _apply_element_geometry_correction(
                            stroke_geom,
                            clip_source_element,
                        )
                        stroke_geom = _apply_element_clip_path(
                            stroke_geom,
                            clip_source_element,
                            group_clip_contexts,
                        )
                        if stroke_geom is not None and not stroke_geom.is_empty:
                            raw_shapes.append(
                                {
                                    "poly": stroke_geom,
                                    "color": stroke_rgb,
                                    "source_kind": "stroke_only",
                                    "stroke_width_svg": float(stroke_width),
                                }
                            )
                            stroke_modeled = True
                continue

            if isinstance(element, Shape) and not isinstance(element, Path):
                try:
                    element = Path(element)
                except VECTOR_FATAL_ERRORS:
                    raise
                except Exception:
                    continue

            grad_info = None
            raw_fill = None
            vals = getattr(element, "values", None)
            if isinstance(vals, dict):
                raw_fill = vals.get("fill", "")
            if raw_fill and gradient_defs:
                m = _url_re.match(str(raw_fill))
                if m:
                    grad_info = gradient_defs.get(m.group(1))
            is_gradient = grad_info is not None

            rgb = None
            if has_fill and not is_gradient:
                try:
                    rgb = (element.fill.red, element.fill.green, element.fill.blue)
                    # Skip fully transparent fills (e.g. rgba(0,0,0,0)) — they
                    # represent "no fill" / transparent background, not a black shape.
                    # If the element also has a visible stroke, fall through to the
                    # stroke-expansion path instead of discarding the element entirely.
                    # 跳过完全透明的填色（如 rgba(0,0,0,0)），它们代表"无填色"
                    # 而非黑色形状。若元素同时有可见描边，则走描边扩展路径。
                    fill_alpha = getattr(element.fill, "alpha", None)
                    if fill_alpha is not None and float(fill_alpha) < 0.01:
                        rgb = None
                        has_fill = False  # let stroke-only path handle it
                except (AttributeError, TypeError, ValueError):
                    rgb = None
            if rgb is None and not is_gradient:
                # Transparent fill with visible stroke: model as stroke-only geometry
                # 透明填色 + 可见描边：按仅描边几何处理
                if has_stroke and parse_expand_stroke_to_fill and stroke_rgb is not None and stroke_width > 0.0:
                    if isinstance(element, Shape) and not isinstance(element, Path):
                        try:
                            element = Path(element)
                        except (AttributeError, TypeError, ValueError, NotImplementedError):
                            continue
                    try:
                        linecap = str(getattr(element, "stroke_linecap", None) or "round").strip().lower()
                    except (AttributeError, TypeError, ValueError):
                        linecap = "round"
                    try:
                        linejoin = str(getattr(element, "stroke_linejoin", None) or "round").strip().lower()
                    except (AttributeError, TypeError, ValueError):
                        linejoin = "round"
                    cap_style = "flat" if linecap == "butt" else ("square" if linecap == "square" else "round")
                    join_style = "mitre" if linejoin == "miter" else linejoin
                    stroke_geom = _sample_path_to_stroke_geometry(
                        element,
                        stroke_width,
                        cap_style_name=cap_style,
                        join_style_name=join_style,
                    )
                    stroke_geom = _apply_element_geometry_correction(
                        stroke_geom,
                        clip_source_element,
                    )
                    stroke_geom = _apply_element_clip_path(
                        stroke_geom,
                        clip_source_element,
                        group_clip_contexts,
                    )
                    if stroke_geom is not None and not stroke_geom.is_empty:
                        raw_shapes.append(
                            {
                                "poly": stroke_geom,
                                "color": stroke_rgb,
                                "source_kind": "stroke_only",
                                "stroke_width_svg": float(stroke_width),
                            }
                        )
                fill_val = getattr(element.fill, "value", None) if element.fill else None
                eid = getattr(element, "id", None) or f"element#{skipped_gradient_count}"
                _log.debug(f"Skipping '{eid}' — unresolvable fill: {fill_val}")
                skipped_gradient_count += 1
                continue

            fill_hex = _rgb_to_hex(rgb)

            single_subpath_item = (
                _single_subpath_item(element)
                if parse_single_subpath_fast_path
                else None
            )
            if single_subpath_item is not None:
                subpath_items = [single_subpath_item]
            else:
                try:
                    subpaths = list(element.as_subpaths())
                except VECTOR_FATAL_ERRORS:
                    raise
                except Exception:
                    subpaths = []

                subpath_items = []
                for subpath in subpaths:
                    try:
                        sub_path = subpath if isinstance(subpath, Path) else Path(subpath)
                        coords = _sample_path_coords(sub_path)
                        poly = _polygon_from_coords(coords)
                    except VECTOR_FATAL_ERRORS:
                        raise
                    except Exception:
                        continue
                    if poly is None:
                        continue
                    subpath_items.append(
                        {
                            "poly": poly,
                            "signed_area": _signed_ring_area(coords),
                        }
                    )
            subpath_polys = [item["poly"] for item in subpath_items]

            # --- Fix 4: gradient flattening ---
            if is_gradient:
                grad_shapes = VectorProcessor._flatten_gradient_shape(
                    grad_info,
                    subpath_polys,
                    color_bands=getattr(self, "gradient_color_bands", None),
                )
                for gs in grad_shapes:
                    p = gs["poly"]
                    if p is not None and not p.is_empty:
                        p = _apply_element_geometry_correction(
                            p,
                            clip_source_element,
                        )
                        p = VectorProcessor._normalize_contours(p)
                        p = _apply_element_clip_path(
                            p,
                            clip_source_element,
                            group_clip_contexts,
                        )
                        if p is not None and not p.is_empty:
                            raw_shapes.append(
                                {
                                    "poly": p,
                                    "color": gs["color"],
                                    "geometry_normalized": True,
                                }
                            )
                if not grad_shapes:
                    skipped_gradient_count += 1
                continue

            # --- Fix 2: fill-rule aware subpath merging ---
            fill_rule = "nonzero"
            try:
                fr = getattr(element, "fill_rule", None)
                if fr is not None:
                    fill_rule = str(fr).strip().lower()
                if fill_rule not in ("nonzero", "evenodd") or fr is None:
                    vals = getattr(element, "values", None)
                    if isinstance(vals, dict):
                        vfr = vals.get("fill-rule", "").strip().lower()
                        if vfr in ("nonzero", "evenodd"):
                            fill_rule = vfr
                    elif hasattr(vals, "__getitem__"):
                        try:
                            vfr = str(vals["fill-rule"]).strip().lower()
                            if vfr in ("nonzero", "evenodd"):
                                fill_rule = vfr
                        except (KeyError, TypeError):
                            pass
            except VECTOR_FATAL_ERRORS:
                raise
            except Exception:
                fill_rule = "nonzero"
            if fill_rule not in ("nonzero", "evenodd"):
                fill_rule = "nonzero"

            if len(subpath_items) == 1:
                result_poly = subpath_items[0]["poly"]
            elif len(subpath_polys) > 1:
                if fill_rule == "evenodd":
                    combined = _combine_evenodd_polygons(subpath_polys)
                else:
                    combined = _combine_nonzero_subpaths(subpath_items)

                if combined is not None and not combined.is_empty:
                    if not combined.is_valid:
                        combined = make_valid(combined)
                    result_poly = combined if not combined.is_empty else None
                else:
                    result_poly = None
            else:
                result_poly = None

            if result_poly is None:
                try:
                    result_poly = _sample_path_to_polygon(element)
                except VECTOR_FATAL_ERRORS:
                    raise
                except Exception:
                    pass

            if result_poly is None:
                skipped_polygon_count += 1
                continue

            # --- Fix 3: morphological closing ---
            same_color_stroke_double_buffer = False
            if (
                parse_expand_stroke_to_fill
                and has_stroke
                and fill_hex is not None
            ):
                stroke_hex = _color_object_to_hex(getattr(element, "stroke", None))
                try:
                    stroke_width = float(getattr(element, "stroke_width", 0.0) or 0.0)
                except VECTOR_FATAL_ERRORS:
                    raise
                except Exception:
                    stroke_width = 0.0
                if stroke_hex == fill_hex and stroke_width > 0.0:
                    try:
                        # SVG renders same-color stroke as additional visible area.
                        # Preserve that paint so native vector output does not leave
                        # pinholes between neighboring filled paths.
                        expanded = result_poly.buffer(
                            stroke_width * 0.5,
                            join_style="mitre",
                            mitre_limit=2.0,
                        )
                        expanded = VectorProcessor._extract_polygonal_geometry(make_valid(expanded))
                        if expanded is not None and not expanded.is_empty:
                            result_poly = expanded
                            same_color_stroke_double_buffer = True
                    except VECTOR_HANDLED_ERRORS:
                        pass

            result_poly = _apply_element_geometry_correction(
                result_poly,
                clip_source_element,
            )
            result_poly = _apply_element_clip_path(
                result_poly,
                clip_source_element,
                group_clip_contexts,
            )
            if result_poly is None or result_poly.is_empty:
                skipped_polygon_count += 1
                continue

            raw_shapes.append(
                {
                    "poly": result_poly,
                    "color": rgb,
                    "source_kind": "fill",
                    "same_color_stroke": bool(has_stroke and stroke_hex == fill_hex and stroke_width > 0.0),
                    "same_color_stroke_double_buffer": same_color_stroke_double_buffer,
                    "stroke_width_svg": float(stroke_width) if has_stroke else 0.0,
                    needs_normalize_key: True,
                }
            )

        pending_positions = []
        pending_geometries = []
        for idx, item in enumerate(raw_shapes):
            if item.get(needs_normalize_key) is True:
                pending_positions.append(idx)
                pending_geometries.append(item["poly"])

        if pending_geometries:
            normalized_geometries = _normalize_contours_many(pending_geometries)
            dropped_positions = set()
            for idx, normalized in zip(pending_positions, normalized_geometries):
                if normalized is None or normalized.is_empty:
                    dropped_positions.add(idx)
                    skipped_polygon_count += 1
                    continue
                raw_shapes[idx]["poly"] = normalized
                raw_shapes[idx]["geometry_normalized"] = True

            normalized_shapes = []
            for idx, item in enumerate(raw_shapes):
                if idx in dropped_positions:
                    continue
                if needs_normalize_key in item:
                    item = dict(item)
                    item.pop(needs_normalize_key, None)
                normalized_shapes.append(item)
            raw_shapes = normalized_shapes

        if skipped_types:
            _log.debug(f"Skipped non-path elements: {skipped_types}")
        if skipped_gradient_count > 0:
            _log.debug(f"{skipped_gradient_count} gradient fills could not be fully resolved")
        if skipped_polygon_count > 0:
            _log.debug(f"Skipped {skipped_polygon_count} elements (invalid polygon after sampling)")
        _log.debug(f"Successfully parsed {len(raw_shapes)} shapes from SVG")

        parse_warnings = []
        if skipped_gradient_count > 0:
            parse_warnings.append(f"{skipped_gradient_count} gradient/pattern fills could not be fully resolved")
        if skipped_polygon_count > 0:
            parse_warnings.append(f"{skipped_polygon_count} elements produced invalid geometry and were skipped")
        self.parse_warnings = parse_warnings

        if not raw_shapes:
            raise ValueError("No valid shapes found in SVG")

        # Global bounding box — union of parsed shapes and SVG viewport
        min_xs, min_ys, max_xs, max_ys = [], [], [], []
        for item in raw_shapes:
            bx0, by0, bx1, by1 = item["poly"].bounds
            min_xs.append(bx0)
            min_ys.append(by0)
            max_xs.append(bx1)
            max_ys.append(by1)

        gx0, gy0 = min(min_xs), min(min_ys)
        gx1, gy1 = max(max_xs), max(max_ys)

        svg_viewport_bounds = None
        try:
            vb = getattr(svg, "viewbox", None)
            if vb is not None:
                vb_x = float(getattr(vb, "x", 0) or 0)
                vb_y = float(getattr(vb, "y", 0) or 0)
                vb_w = float(getattr(vb, "width", 0) or 0)
                vb_h = float(getattr(vb, "height", 0) or 0)
                if vb_w > 0 and vb_h > 0:
                    svg_viewport_bounds = (vb_x, vb_y, vb_w, vb_h)
                    gx0 = min(gx0, vb_x)
                    gy0 = min(gy0, vb_y)
                    gx1 = max(gx1, vb_x + vb_w)
                    gy1 = max(gy1, vb_y + vb_h)
                    _log.debug("SVG viewBox: (%s, %s, %s, %s)", vb_x, vb_y, vb_w, vb_h)
        except VECTOR_HANDLED_ERRORS:
            pass

        real_w = gx1 - gx0
        real_h = gy1 - gy0

        _log.debug("Global bounds: x=%.1f, y=%.1f, w=%.1f, h=%.1f", gx0, gy0, real_w, real_h)
        if real_w == 0:
            raise ValueError("Invalid geometry width (0)")

        if image_vectorizer_origin and svg_viewport_bounds is not None:
            vb_x, vb_y, vb_w, vb_h = svg_viewport_bounds
            self._last_image_vectorizer_bounds = box(
                vb_x - gx0,
                vb_y - gy0,
                vb_x + vb_w - gx0,
                vb_y + vb_h - gy0,
            )

        scale_factor = target_width_mm / real_w
        min_area_svg = max(0.0, (self.sampling_precision**2) / max(scale_factor**2, 1e-12) * 0.25)
        simplify_tol_svg = max(0.0, (self.sampling_precision / max(scale_factor, 1e-9)) * 0.5)
        # NOTE: a silent 'widen thin stroke to nozzle width' step (added in
        # PR #24 overhaul, 34a22dc) used to outward-buffer every sub-nozzle
        # stroke shape by ``0.5*(nozzle-stroke)`` with ``join_style='mitre',
        # mitre_limit=2.0``. On illustrated SVGs this made every fine contour
        # chunky and produced mitre spikes at sharp corners. Removed here
        # because sub-nozzle stroke handling belongs to the slicer/export
        # boundary, not the shared preview/mesh geometry stage.
        # 曾经的 "按 nozzle 宽度外扩细描边" 步骤（PR #24 overhaul 引入）会让细
        # 笔触整体变粗、尖角产生毛刺；这类打印兼容处理应放在切片/导出边界层
        # 而非预览/mesh 几何共用阶段，此处不再做。
        final_shapes = []
        for item in raw_shapes:
            shifted = affinity.translate(item["poly"], xoff=-gx0, yoff=-gy0)
            geometry_normalized = bool(item.get("geometry_normalized"))
            if simplify_tol_svg > 0.0:
                before_simplify = shifted
                try:
                    shifted = shifted.simplify(simplify_tol_svg, preserve_topology=True)
                    if geometry_normalized and not shifted.equals_exact(before_simplify, tolerance=0.0):
                        geometry_normalized = False
                except VECTOR_HANDLED_ERRORS:
                    geometry_normalized = False
                    pass

            if not shifted.is_valid:
                shifted = make_valid(shifted)
                geometry_normalized = False

            if shifted.is_empty or shifted.area <= min_area_svg:
                continue
            final_item = {"poly": shifted, "color": item["color"]}
            for key in (
                "source_kind",
                "same_color_stroke",
                "same_color_stroke_double_buffer",
                "stroke_width_svg",
            ):
                if key in item:
                    final_item[key] = item[key]
            if geometry_normalized:
                final_item["geometry_normalized"] = True
            final_shapes.append(final_item)

        return final_shapes, scale_factor, (gx0, gy0, real_w, real_h)

    @staticmethod
    def _fix_coordinates(mesh, svg_height_mm):
        """Flip SVG's Y axis without translating writer-domain vertices.

        Keep the existing ``svg_height_mm`` argument for caller compatibility.
        Bed placement is emitted later as a 3MF build-item transform; adding
        canvas or bed offsets to vertices here can collapse distinct points
        when the writer converts them to float32.
        """
        del svg_height_mm
        transform = np.eye(4)
        transform[1, 1] = -1
        transform_layered_mesh(mesh, transform)


@contextmanager
def _surface_svg_source(svg_path: str | os.PathLike) -> Iterator[str]:
    """Omit generated display-only gap lines without discarding author strokes."""
    try:
        root = ET.parse(svg_path).getroot()
    except ET.ParseError as exc:
        raise ValueError("Invalid surface artwork SVG.") from exc
    removed = False
    for parent in root.iter():
        for child in list(parent):
            if (
                _tag_local_name(child) == "path"
                and "qq3d-gap-filler" in child.get("class", "").split()
                and child.get("fill", "").strip().lower() == "none"
                and child.get("id") is None
            ):
                parent.remove(child)
                removed = True
    if not removed:
        yield str(svg_path)
        return

    with tempfile.TemporaryDirectory(prefix="lumina-surface-svg-") as directory:
        filtered_path = os.path.join(directory, "artwork.svg")
        ET.ElementTree(root).write(filtered_path, encoding="utf-8", xml_declaration=True)
        yield filtered_path


def parse_svg_geometry(
    svg_path: str | os.PathLike,
    *,
    target_width_mm: float,
) -> tuple[list[dict[str, Any]], float, tuple[float, float, float, float]]:
    """Parse visible SVG paint without constructing a LUT-backed processor.

    在不构造 LUT 匹配器的情况下解析原生 SVG 几何。

    Args:
        svg_path: Source SVG path.
            源 SVG 路径。
        target_width_mm: Physical width used for parser precision.
            用于确定解析精度的物理宽度。

    Returns:
        Shape data, parser scale factor, and source bounds.
        图形数据、解析比例和源边界。
    """

    if not math.isfinite(float(target_width_mm)) or float(target_width_mm) <= 0.0:
        raise ValueError("target_width_mm must be positive and finite.")
    processor = VectorProcessor.__new__(VectorProcessor)
    processor._init_runtime_defaults()
    with _surface_svg_source(svg_path) as source:
        outcome = native_svg_adapter.analyze_native_svg(
            source,
            float(target_width_mm),
            processor.sampling_precision,
            expand_stroke_to_fill=True,
        )
        if isinstance(outcome, native_svg_adapter.NativeSvgGeometry):
            return (
                [{"poly": item["geometry"], "color": item["color"]}
                 for item in outcome.clipped_shapes],
                outcome.scale_factor,
                outcome.bbox,
            )
        # Only explicit whole-document fallback may select the legacy parser.
        processor._parse_expand_stroke_to_fill = True
        return processor._parse_svg(source, float(target_width_mm))
