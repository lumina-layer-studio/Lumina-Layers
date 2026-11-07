"""
Pipeline vector branch — SVG \u539f\u751f\u77e2\u91cf\u8f6c\u6362\u5206\u652f\u3002
SVG-native vector conversion branch for the staged pipeline.

\u672c\u6a21\u5757\u4ece ``core/pipeline/coordinator.py`` \u4e2d\u62bd\u51fa\u539f\u6709\u7684\u77e2\u91cf\u5206\u652f\u5b9e\u73b0\uff0c\u4f7f
``coordinator.py`` \u91cd\u65b0\u62e5\u6709\u5355\u4e00\u804c\u8d23\uff08\u53ea\u5145\u5f53raster/preview \u8868\u9a71\u52a8
\u8c03\u5ea6\u5668\uff09\u3002\u51fd\u6570\u4e0e\u4e8b\u4ef6\u540d\u7167\u539f\u6837\u4fdd\u7559\uff0c\u91cd\u6784\u4e3a\u7eaf\u6587\u4ef6\u643c\u8fc1\u3002

This module hosts the SVG-native conversion branch that used to live inline
inside ``core.pipeline.coordinator``. The extraction restores
``coordinator.py``'s single responsibility (table-driven raster + preview
orchestration) without changing any public behavior, function signatures, or
structured-logging event names.

Public callables (re-exported by ``coordinator`` for backward compatibility):
\u516c\u5171\u8c03\u7528\u70b9\uff08``coordinator`` \u91cd\u5bfc\u51fa\u4ee5\u4fdd\u8bc1\u5411\u540e\u517c\u5bb9\uff09\uff1a

- ``_run_vector_branch(ctx) -> dict``: SVG \u2192 3MF/2D + reusable lightweight GLB reference.
- ``_run_vector_preview_branch(ctx) -> dict``: SVG \u9884\u89c8\u7f13\u5b58\u6784\u5efa\u3002
- ``_update_bambu_base_layer_ctx_for_vector(...)``: Bambu \u5e95\u677f\u53ec\u552e\u5c01\u88c5\u3002
- ``_log_vector_timings(...)``: \u8ba1\u65f6\u660e\u7ec6\u8f93\u51fa\u3002
"""

from __future__ import annotations

import inspect
import math
import os
import time
from copy import deepcopy
from typing import Any

import cv2  # noqa: F401  -- imported for side-effect parity with coordinator
import numpy as np
import trimesh

from api.structured_logging import get_logger
from config import BedManager, PrinterConfig, normalize_nozzle_size
from core.errors import (
    CachedPreviewAnalysisError,
)
from core.geometry_utils import (
    create_keychain_loop,
    keychain_loop_hole_clearance,
    resolve_keychain_contact_anchor_y,
)
from core.pipeline import p06_bed_rendering, s09_export_3mf
from core.pipeline.pipeline_utils import extract_color_palette
from core.pipeline.processing_ops.svg_rasterizer import rasterize_svg
from core.pipeline.s08_auxiliary_meshes import (
    _coerce_preview_rgba,
)
from core.vector_structure import resolve_structure_plan
from core.preview_analysis_cache import preview_analysis_reuse_is_required
from core.vector_layer_geometry import (
    VectorLayerGeometryPolicy,
    build_vector_layered_volume,
    resolve_vector_writer_grid_mm,
)
from core.svg_coordinate_domain import SvgCoordinateDomain, prepare_print_slabs

# ---------------------------------------------------------------------------
# Cycle-safe re-import of small helpers that originate in coordinator.
# Defined ABOVE the ``coordinator -> vector_branch`` import in coordinator.py
# so this lookup succeeds during partial module initialisation.
#
# coordinator.py \u5728\u5bfc\u5165\u672c\u6a21\u5757\u4e4b\u524d\u5148\u5b9a\u4e49\u4e86 ``COORDINATOR_HANDLED_ERRORS``
# \u4e0e ``_report_progress``\uff0c\u56e0\u6b64\u4e0b\u9762\u8fd9\u6b65\u5728\u5faa\u73af\u5bfc\u5165\u4e0a\u4e0b\u6587\u4e2d\u4ecd\u80fd\u62ff\u5230\u5b8c\u6574\u5b9a\u4e49\u3002
# ---------------------------------------------------------------------------
try:
    from core.pipeline.coordinator import (  # noqa: E402  -- intentional cycle break
        COORDINATOR_HANDLED_ERRORS,
        _report_progress,
    )
except ImportError as exc:
    if "core.pipeline.vector_branch" not in str(exc):
        raise
    COORDINATOR_HANDLED_ERRORS = (
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        OSError,
        RuntimeError,
        ModuleNotFoundError,
        cv2.error,
    )

    def _report_progress(ctx: dict, value: float, desc: str = "") -> None:
        from core.pipeline import coordinator

        coordinator._report_progress(ctx, value, desc)

# Logger namespace is intentionally pinned to the coordinator's name so the
# extraction does not change observable log records (pre-existing tests +
# log audits attach handlers to ``lumina.core.pipeline.coordinator``).
# 日志命名空间故意继续沿用 coordinator，保证抽离后日志可观察性零变更。
log = get_logger("core.pipeline.coordinator")

# ---------------------------------------------------------------------------
# Layer-0 (appearance face) diagnostics
# 外观面层（layer 0）诊断埋点
#
# Detailed diagnostic events use DEBUG so ordinary runs stay readable.
# To consume them, run with
# ``LUMINA_LOG_LEVEL=DEBUG`` and grep the log file for ``vector_diag_*``.
#
# Coverage (8 instrumentation points spread across the vector pipeline):
#   1. ``vector_diag_solver_cache_layer_order`` — solver cache reindex /
#      Bottom2Top→Top2Bottom reversal, sample stacks
#   2. ``vector_diag_match_colors_summary`` — per-unique-color KDTree
#      lookup → ref_stack[0..2] mapping
#   3. ``vector_diag_preview_material_matrix_layer0`` — preview cache
#      material_matrix layer 0 channel histogram + shape recipe[0] hist
#   4. ``vector_diag_generate_loaded_material_matrix_layer0`` — /generate
#      loaded material_matrix layer 0 (post pad)
#   5. ``vector_diag_apply_matched_rgb_per_shape`` — per-shape majority
#      stack vote details (first N shapes)
#   6. ``vector_diag_after_matched_rgb_overrides_recipe0`` — shape
#      recipe[0] hist after apply_matched_rgb_overrides
#   7. ``vector_diag_after_recipe_overrides_recipe0`` — shape recipe[0]
#      hist after apply_recipe_overrides (final state before build_mesh)
#   8. ``vector_diag_build_mesh_input_recipes`` — sample of recipes that
#      build_mesh actually consumes
#
# Comparing 1..8 pinpoints which exact stage corrupts the appearance face.
# 全部 DEBUG 级别，零治理代价。用 ``LUMINA_LOG_LEVEL=DEBUG`` 启用并 grep
# ``vector_diag_*`` 即可对比 8 个阶段的 layer 0 通道分布，逐段定位"外观面
# 缺色"的注入点。
# ---------------------------------------------------------------------------


def _layer0_channel_histogram(material_matrix: object, mask_solid: object | None) -> dict:
    """Return a (channel_id -> pixel_count) histogram of ``material_matrix[..., 0]``.

    Only counts mask_solid pixels when provided; transparent (mask_solid=False)
    is reported separately. Channel ids are clamped to a reasonable display
    range to keep the log payload small.

    返回 ``material_matrix[..., 0]``（外观面层）的通道直方图。仅统计实体像素，
    透明像素单独报告。
    """
    arr = np.asarray(material_matrix)
    if arr.ndim != 3 or arr.shape[2] == 0:
        return {"_invalid_shape": list(arr.shape)}
    layer0 = arr[..., 0]
    mask = None
    if mask_solid is not None:
        mask_arr = np.asarray(mask_solid, dtype=bool)
        if mask_arr.shape == layer0.shape:
            mask = mask_arr
    if mask is not None:
        solid_pixels = layer0[mask]
        transparent_pixels = layer0[~mask]
    else:
        solid_pixels = layer0.ravel()
        transparent_pixels = np.empty(0, dtype=layer0.dtype)
    uniq, counts = np.unique(solid_pixels, return_counts=True)
    histogram = {int(ch): int(cnt) for ch, cnt in zip(uniq.tolist(), counts.tolist())}
    return {
        "shape": list(arr.shape),
        "solid_pixel_count": int(solid_pixels.size),
        "transparent_pixel_count": int(transparent_pixels.size),
        "layer0_channel_histogram": histogram,
    }


def _shape_recipe0_histogram(matched_shapes: list) -> dict:
    """Return a (channel_id -> shape_count, channel_id -> total_area) histogram of shape.recipe[0].

    Reports both shape count and approximate area weight so downstream analysis
    can distinguish "many small shapes have channel X" from "a few large shapes
    have channel X".

    返回 shape.recipe[0] 的两个直方图：按形状数 + 按面积，便于区分"零碎小形状"
    和"少量大色块"两种分布。
    """
    by_shape: dict[int, int] = {}
    by_area: dict[int, float] = {}
    no_recipe = 0
    for shape in matched_shapes or []:
        recipe = shape.get("recipe") if isinstance(shape, dict) else None
        if not recipe:
            no_recipe += 1
            continue
        ch = int(recipe[0])
        by_shape[ch] = by_shape.get(ch, 0) + 1
        geom = shape.get("geometry") if isinstance(shape, dict) else None
        try:
            area = float(geom.area) if geom is not None else 0.0
        except (AttributeError, TypeError, ValueError):
            area = 0.0
        by_area[ch] = by_area.get(ch, 0.0) + area
    by_area_rounded = {ch: round(area, 3) for ch, area in by_area.items()}
    return {
        "shape_count": int(sum(by_shape.values())),
        "shapes_without_recipe": int(no_recipe),
        "recipe0_by_shape_count": by_shape,
        "recipe0_by_area": by_area_rounded,
    }


def _per_layer_channel_histogram(material_matrix: object, mask_solid: object | None) -> dict:
    """Return per-layer per-channel pixel histograms over ``material_matrix``.

    返回 ``material_matrix`` 每一层的 (channel -> pixel_count) 直方图。透明
    像素由 ``mask_solid=False`` 标识，统一不计入任何层的分母。这是阶段 A
    诊断的核心数据：每层每通道有多少像素。

    Args:
        material_matrix: ``(H, W, num_layers)`` int array. (材料矩阵)
        mask_solid: Optional ``(H, W)`` bool mask of solid pixels. (实体掩膜)

    Returns:
        dict: ``{"shape": [...], "solid_pixel_count": int,
        "per_layer_channel_histogram": {layer_idx: {channel: pixel_count}}}``.
    """
    arr = np.asarray(material_matrix)
    if arr.ndim != 3 or arr.shape[2] == 0:
        return {"_invalid_shape": list(arr.shape)}
    h, w, num_layers = arr.shape
    mask = None
    if mask_solid is not None:
        mask_arr = np.asarray(mask_solid, dtype=bool)
        if mask_arr.shape == (h, w):
            mask = mask_arr
    per_layer: dict[int, dict[int, int]] = {}
    if mask is not None:
        flat_mask = mask.ravel()
        for layer_idx in range(num_layers):
            layer = arr[..., layer_idx].ravel()[flat_mask]
            uniq, counts = np.unique(layer, return_counts=True)
            per_layer[int(layer_idx)] = {
                int(ch): int(cnt) for ch, cnt in zip(uniq.tolist(), counts.tolist())
            }
        solid_count = int(flat_mask.sum())
    else:
        for layer_idx in range(num_layers):
            layer = arr[..., layer_idx].ravel()
            uniq, counts = np.unique(layer, return_counts=True)
            per_layer[int(layer_idx)] = {
                int(ch): int(cnt) for ch, cnt in zip(uniq.tolist(), counts.tolist())
            }
        solid_count = int(arr.shape[0] * arr.shape[1])
    return {
        "shape": list(arr.shape),
        "solid_pixel_count": solid_count,
        "per_layer_channel_histogram": per_layer,
    }


def _shape_per_layer_channel_histogram(matched_shapes: list) -> dict:
    """Return per-layer per-channel shape-count and total-area histograms.

    返回每个 (layer_idx, channel) 上"有多少 shape 在该层是该通道"以及总面积。
    用于阶段 B 诊断：与阶段 A（按像素）和阶段 C（按 run）逐层逐通道对比，
    找出"色块从哪一阶段开始丢失"。

    Args:
        matched_shapes: List of shape dicts with ``recipe`` (list of channel
            ids, Top2Bottom) and ``geometry`` (shapely). (匹配 shape 列表)

    Returns:
        dict with ``per_layer_shape_count`` and ``per_layer_area`` nested
        dicts keyed by ``layer_idx -> channel -> count/area``.
    """
    by_count: dict[int, dict[int, int]] = {}
    by_area: dict[int, dict[int, float]] = {}
    max_layers = 0
    for shape in matched_shapes or []:
        recipe = shape.get("recipe") if isinstance(shape, dict) else None
        if not recipe:
            continue
        max_layers = max(max_layers, len(recipe))
        geom = shape.get("geometry") if isinstance(shape, dict) else None
        try:
            area = float(geom.area) if geom is not None else 0.0
        except (AttributeError, TypeError, ValueError):
            area = 0.0
        for layer_idx, ch_raw in enumerate(recipe):
            ch = int(ch_raw)
            by_count.setdefault(layer_idx, {})
            by_area.setdefault(layer_idx, {})
            by_count[layer_idx][ch] = by_count[layer_idx].get(ch, 0) + 1
            by_area[layer_idx][ch] = by_area[layer_idx].get(ch, 0.0) + area
    by_area_rounded = {
        layer_idx: {ch: round(area, 3) for ch, area in inner.items()}
        for layer_idx, inner in by_area.items()
    }
    return {
        "shape_max_layer_count": int(max_layers),
        "per_layer_shape_count": by_count,
        "per_layer_area": by_area_rounded,
    }


def _emit_vector_diag(*, extra: dict) -> None:
    """Emit a vector diagnostic event at DEBUG level.

    The ``extra`` argument MUST be passed as a keyword named ``extra`` and
    contain a string literal under the ``event`` key. Both constraints are
    needed so the structured-logging governance scanner (which walks the
    AST looking for ``extra={"event": "<literal>", ...}``) detects every
    diagnostic event.

    DEBUG 级别诊断埋点。``extra`` 必须以关键字参数形式传入，且 ``event``
    字段为字符串字面量，否则日志治理扫描无法识别。
    """
    message = str(extra.get("event") or "vector_diag")
    log.debug(message, extra=extra)


def _log_vector_preview_timings(
    timings: dict,
    ctx: dict,
    analysis: object,
    raster_cache: dict,
) -> None:
    if not timings:
        return
    mask_solid = raster_cache.get("mask_solid")
    material_matrix = raster_cache.get("material_matrix")
    material_matrix_shape = (
        list(np.asarray(material_matrix).shape)
        if material_matrix is not None
        else None
    )
    solid_pixel_count = (
        int(np.asarray(mask_solid, dtype=bool).sum())
        if mask_solid is not None
        else None
    )
    unique_fills = set()
    for shape in getattr(analysis, "clipped_shapes", []) or []:
        if not isinstance(shape, dict):
            continue
        color = shape.get("color")
        try:
            unique_fills.add(tuple(int(channel) for channel in color[:3]))
        except (TypeError, ValueError, IndexError):
            continue
    material_source = (
        "material_archive"
        if str(ctx.get("material_source") or "lut") == "material_archive"
        else "lut"
    )
    log.info(
        "Vector preview timing breakdown",
        extra={
            "event": "vector_preview_timings",
            "duration_ms": round(float(timings.get("vector_preview_total_s", 0.0)) * 1000, 3),
            "timings": _structured_timing_payload(timings),
            "modeling_mode": str(ctx.get("modeling_mode") or "vector"),
            "material_source": material_source,
            "color_mode": str(ctx.get("color_mode") or ""),
            "target_width_mm": float(ctx.get("target_width_mm") or 0.0),
            "is_material_archive": material_source == "material_archive",
            "grid_resolution": int(ctx.get("grid_resolution") or 0),
            "material_count": int(getattr(analysis, "num_channels", 0) or 0),
            "layer_count": int(getattr(analysis, "num_layers", 0) or 0),
            "unique_fill_count": len(unique_fills),
            "shape_count": len(getattr(analysis, "shape_data", []) or []),
            "clipped_shape_count": len(getattr(analysis, "clipped_shapes", []) or []),
            "matched_shape_count": len(getattr(analysis, "matched_shapes", []) or []),
            "preview_width_px": int(raster_cache.get("target_w") or 0),
            "preview_height_px": int(raster_cache.get("target_h") or 0),
            "solid_pixel_count": solid_pixel_count,
            "material_matrix_shape": material_matrix_shape,
        },
    )


def _resolve_vector_line_width_mm(nozzle_size: object) -> str:
    normalized = normalize_nozzle_size(nozzle_size) or "0.4"
    try:
        nozzle_mm = float(normalized)
    except (TypeError, ValueError):
        nozzle_mm = 0.4
    line_width = 0.22 if nozzle_mm <= 0.25 else 0.42
    return f"{line_width:.2f}"


def _coerce_finite_float(value: object, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(result):
        return default
    return result


def _coerce_positive_float(value: object, default: float) -> float:
    result = _coerce_finite_float(value, default)
    return result if result > 0 else default


def _finite_scene_bounds(scene: trimesh.Scene) -> np.ndarray | None:
    try:
        bounds = np.asarray(scene.bounds, dtype=np.float64)
    except (AttributeError, TypeError, ValueError):
        return None
    if bounds.shape != (2, 3) or not np.all(np.isfinite(bounds)):
        return None
    if np.any(bounds[1] <= bounds[0]):
        return None
    return bounds


_TOP_PROFILE_CHUNK_CELLS = 2_000_000


def _scene_band_edges(
    scene: trimesh.Scene,
    band_min: float,
    band_max: float,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Collect transformed XY mesh edges whose X span touches a band."""
    starts_parts: list[np.ndarray] = []
    ends_parts: list[np.ndarray] = []
    for node_name in scene.graph.nodes_geometry:
        try:
            transform, geometry_name = scene.graph[node_name]
            geometry = scene.geometry[geometry_name]
            vertices = trimesh.transform_points(
                np.asarray(geometry.vertices, dtype=np.float64),
                transform,
            )[:, :2]
            edges = np.asarray(geometry.edges_unique, dtype=np.int64)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if vertices.ndim != 2 or vertices.shape[1] != 2 or edges.ndim != 2:
            continue
        if edges.shape[1] != 2 or len(edges) == 0:
            continue

        starts = vertices[edges[:, 0]]
        ends = vertices[edges[:, 1]]
        keep = np.all(np.isfinite(starts), axis=1) & np.all(
            np.isfinite(ends), axis=1
        )
        keep &= np.minimum(starts[:, 0], ends[:, 0]) <= band_max
        keep &= np.maximum(starts[:, 0], ends[:, 0]) >= band_min
        if np.any(keep):
            starts_parts.append(starts[keep])
            ends_parts.append(ends[keep])

    if not starts_parts:
        return None
    return np.concatenate(starts_parts), np.concatenate(ends_parts)


def _top_profile_at(
    sample_x: np.ndarray,
    starts: np.ndarray,
    ends: np.ndarray,
) -> np.ndarray:
    """Return the highest edge Y crossing each sample X (``-inf`` if none)."""
    delta_x = ends[:, 0] - starts[:, 0]
    non_vertical = np.abs(delta_x) > 1e-12
    safe_delta_x = np.where(non_vertical, delta_x, 1.0)
    edge_min_x = np.minimum(starts[:, 0], ends[:, 0]) - 1e-9
    edge_max_x = np.maximum(starts[:, 0], ends[:, 0]) + 1e-9
    vertical_top = np.maximum(starts[:, 1], ends[:, 1])

    tops = np.full(len(sample_x), -np.inf)
    chunk = max(1, _TOP_PROFILE_CHUNK_CELLS // max(1, len(starts)))
    for offset in range(0, len(sample_x), chunk):
        xs = sample_x[offset:offset + chunk, None]
        covers = (xs >= edge_min_x) & (xs <= edge_max_x)
        ratios = np.clip((xs - starts[:, 0]) / safe_delta_x, 0.0, 1.0)
        edge_y = np.where(
            non_vertical,
            starts[:, 1] + ratios * (ends[:, 1] - starts[:, 1]),
            vertical_top,
        )
        tops[offset:offset + chunk] = np.max(
            np.where(covers, edge_y, -np.inf), axis=1
        )
    return tops


def _scene_top_edge_range_for_contact_band(
    scene: trimesh.Scene,
    center_x: float,
    contact_width: float,
) -> tuple[float, float] | None:
    """Return the lowest and highest scene top edge inside a horizontal band.

    The top profile is piecewise linear between edge endpoints, so sampling
    the band ends plus every endpoint inside the band finds both extremes.
    """
    if contact_width <= 0:
        return None

    band_min = center_x - contact_width / 2.0
    band_max = center_x + contact_width / 2.0
    band_edges = _scene_band_edges(scene, band_min, band_max)
    if band_edges is None:
        return None
    starts, ends = band_edges

    endpoint_x = np.concatenate((starts[:, 0], ends[:, 0]))
    inside_x = endpoint_x[(endpoint_x >= band_min) & (endpoint_x <= band_max)]
    sample_x = np.unique(np.concatenate(([band_min, band_max], inside_x)))
    tops = _top_profile_at(sample_x, starts, ends)
    tops = tops[np.isfinite(tops)]
    if len(tops) == 0:
        return None
    return float(np.min(tops)), float(np.max(tops))


def _vector_loop_attach_point(
    ctx: dict,
    scene_bounds: np.ndarray,
    scene: trimesh.Scene | None = None,
) -> tuple[float, float]:
    min_x, min_y = float(scene_bounds[0, 0]), float(scene_bounds[0, 1])
    max_x, max_y = float(scene_bounds[1, 0]), float(scene_bounds[1, 1])
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0

    loop_pos = ctx.get("loop_pos")
    if isinstance(loop_pos, (list, tuple)) and len(loop_pos) >= 2:
        attach_x = _coerce_finite_float(loop_pos[0], center_x)
        attach_y = _coerce_finite_float(loop_pos[1], max_y)
    else:
        preset = str(ctx.get("loop_position_preset") or "top-center")
        offset_x = _coerce_finite_float(ctx.get("loop_offset_x"), 0.0)
        offset_y = _coerce_finite_float(ctx.get("loop_offset_y"), 0.0)
        if (
            preset == "top-center"
            and scene is not None
            and abs(_coerce_finite_float(ctx.get("loop_angle"), 0.0)) <= 1e-9
        ):
            requested_x = center_x + offset_x
            loop_width = _coerce_positive_float(ctx.get("loop_width"), 4.0)
            top_range = _scene_top_edge_range_for_contact_band(
                scene, requested_x, loop_width
            )
            if top_range is not None:
                hole_clearance = keychain_loop_hole_clearance(
                    loop_width,
                    _coerce_positive_float(ctx.get("loop_length"), 8.0),
                    _coerce_positive_float(ctx.get("loop_hole"), 2.5),
                )
                anchor_y = resolve_keychain_contact_anchor_y(
                    *top_range, hole_clearance
                )
                return requested_x, anchor_y + max(0.0, offset_y)
        if preset == "top-left":
            attach_x, attach_y = min_x, max_y
        elif preset == "top-right":
            attach_x, attach_y = max_x, max_y
        elif preset == "left-center":
            attach_x, attach_y = min_x, center_y
        elif preset == "right-center":
            attach_x, attach_y = max_x, center_y
        elif preset == "bottom-center":
            attach_x, attach_y = center_x, min_y
        else:
            attach_x, attach_y = center_x, max_y

    attach_x += _coerce_finite_float(ctx.get("loop_offset_x"), 0.0)
    attach_y += _coerce_finite_float(ctx.get("loop_offset_y"), 0.0)
    return attach_x, attach_y


def _geometry_xy_distance(bounds: np.ndarray, x: float, y: float) -> tuple[float, float]:
    min_x, min_y = float(bounds[0, 0]), float(bounds[0, 1])
    max_x, max_y = float(bounds[1, 0]), float(bounds[1, 1])
    if min_x <= x <= max_x:
        dx = 0.0
    else:
        dx = min(abs(x - min_x), abs(x - max_x))
    if min_y <= y <= max_y:
        dy = 0.0
    else:
        dy = min(abs(y - min_y), abs(y - max_y))
    return dx, dy


def _resolve_vector_loop_style(
    ctx: dict,
    scene: trimesh.Scene,
    attach_x: float,
    attach_y: float,
    preview_colors: dict,
    slot_names: list,
) -> tuple[int, list[int], str | None]:
    fallback_idx = 0
    try:
        candidate = int(ctx.get("backing_color_id", 0) or 0)
    except (TypeError, ValueError):
        candidate = 0
    if 0 <= candidate < len(slot_names):
        fallback_idx = candidate

    candidates: list[tuple[float, float, int, str]] = []
    for geom_order, (geom_name, geom) in enumerate(scene.geometry.items()):
        name = str(geom_name)
        if name not in slot_names:
            continue
        try:
            bounds = np.asarray(geom.bounds, dtype=np.float64)
        except (AttributeError, TypeError, ValueError):
            continue
        if bounds.shape != (2, 3) or not np.all(np.isfinite(bounds)):
            continue
        dx, dy = _geometry_xy_distance(bounds, attach_x, attach_y)
        candidates.append((dx, dy, geom_order, name))

    material_name: str | None = None
    color_idx = fallback_idx
    if candidates:
        _, _, _, material_name = min(candidates)
        color_idx = slot_names.index(material_name)
    elif 0 <= fallback_idx < len(slot_names):
        material_name = str(slot_names[fallback_idx])

    color = preview_colors.get(material_name) if material_name else None
    if color is None:
        color = preview_colors.get(color_idx)
    if color is None:
        color = preview_colors.get(str(color_idx))
    rgba = _coerce_preview_rgba(color)
    return color_idx, rgba, material_name


def _inject_vector_keychain_loop(
    ctx: dict,
    scene: trimesh.Scene,
    preview_colors: dict,
    slot_names: list,
) -> bool:
    """Add vector keychain-loop geometry to the export scene when requested."""
    if not bool(ctx.get("add_loop", False)):
        return False

    bounds = _finite_scene_bounds(scene)
    if bounds is None:
        return False

    attach_x, attach_y = _vector_loop_attach_point(ctx, bounds, scene)
    _color_idx, rgba, material_name = _resolve_vector_loop_style(
        ctx,
        scene,
        attach_x,
        attach_y,
        preview_colors,
        list(slot_names),
    )

    thickness_mm = max(
        PrinterConfig.LAYER_HEIGHT,
        float(bounds[1, 2] - bounds[0, 2]),
    )
    loop_mesh = create_keychain_loop(
        width_mm=_coerce_positive_float(ctx.get("loop_width"), 4.0),
        length_mm=_coerce_positive_float(ctx.get("loop_length"), 8.0),
        hole_dia_mm=_coerce_positive_float(ctx.get("loop_hole"), 2.5),
        thickness_mm=thickness_mm,
        attach_x_mm=attach_x,
        attach_y_mm=attach_y,
        angle_deg=_coerce_finite_float(ctx.get("loop_angle"), 0.0),
    )
    if loop_mesh is None or len(loop_mesh.vertices) == 0 or len(loop_mesh.faces) == 0:
        return False

    z_offset = float(bounds[0, 2])
    if z_offset != 0.0:
        loop_mesh.vertices[:, 2] += z_offset
    loop_mesh.visual.face_colors = rgba
    loop_mesh.metadata["name"] = "Keychain_Loop"
    if material_name:
        loop_mesh.metadata["bambu_material_name"] = material_name

    if "Keychain_Loop" in scene.geometry:
        del scene.geometry["Keychain_Loop"]
    scene.add_geometry(loop_mesh, node_name="Keychain_Loop", geom_name="Keychain_Loop")
    preview_colors["Keychain_Loop"] = rgba
    ctx["loop_added"] = True
    return True


# ===================================================================
# Vector outline mesh generation (see progress/svg-vector-outline-fix-verification.md)
# 矢量分支描边 mesh 生成 —— 工单 LUM-20260527-001 的核心修复点。
# ===================================================================


def _resolve_vector_outline_base_aux_style(
    ctx: dict,
    preview_colors: dict,
    slot_names: list,
) -> tuple[list[int], str | None]:
    """Resolve the (color, material name) used for the vector outline mesh.
    解析矢量描边使用的底色 / 材质名。

    Mirrors ``s08_auxiliary_meshes._resolve_material_archive_base_aux_style``
    but consumes the vector branch's own ``preview_colors`` / ``slot_names``
    so we never assume ``base_channel_idx == 0`` (per Converter Regression
    Checklist). For LUT-backed flows ``ctx['backing_color_id']`` selects the
    slot; for material-archive ``ctx['material_base_channel_idx']`` overrides.

    Args:
        ctx: Pipeline context.
        preview_colors: Vector-branch preview colour table keyed by slot
            index and slot name.
        slot_names: Ordered slot name list as resolved by ``analysis``.

    Returns:
        ``(rgba, material_name)`` tuple. ``rgba`` is always populated; the
        material name may be ``None`` when the resolved slot is missing
        from ``slot_names`` (caller treats that as "skip metadata").
    """
    material_source = str(ctx.get("material_source") or "lut")
    if material_source == "material_archive":
        try:
            base_idx = int(ctx.get("material_base_channel_idx", 0) or 0)
        except (TypeError, ValueError):
            base_idx = 0
    else:
        try:
            base_idx = int(ctx.get("backing_color_id", 0) or 0)
        except (TypeError, ValueError):
            base_idx = 0
        # ``backing_color_id`` is set to ``-2`` when separate_backing is
        # active (sentinel used by raster meshers); fall back to the
        # explicit ``separate_backing_color_id`` so vector outline still
        # picks a real slot colour rather than a sentinel.
        # separate_backing 时 backing_color_id 会被置为 -2，需要回退到
        # separate_backing_color_id 才能拿到真正的底色。
        if base_idx < 0:
            try:
                base_idx = int(
                    ctx.get("separate_backing_color_id", 0) or 0
                )
            except (TypeError, ValueError):
                base_idx = 0

    if not slot_names:
        clamped_idx = 0
    else:
        clamped_idx = max(0, min(base_idx, len(slot_names) - 1))

    color = preview_colors.get(clamped_idx)
    if color is None:
        color = preview_colors.get(str(clamped_idx))
    if color is None and slot_names:
        color = preview_colors.get(slot_names[clamped_idx])
    rgba = _coerce_preview_rgba(color)

    material_name: str | None = None
    if 0 <= clamped_idx < len(slot_names):
        material_name = str(slot_names[clamped_idx])

    return rgba, material_name


def _resolve_vector_outline_z_span(
    ctx: dict,
    analysis,
    *,
    export_color_mode: object | None = None,
    layer_height_mm: float | None = None,
) -> tuple[float, float]:
    """Return the Z span that a vector outline must cover.
    返回矢量 Outline 应覆盖的 Z 向范围。

    The vector branch does not run S08, so it cannot reuse
    ``ctx["total_layers"]``. Instead, mirror ``VectorProcessor.build_mesh``:
    non-5-color double-sided models have colour layers below and above the
    backing; 5-Color Extended keeps the optical stack above the backing. If
    coating is enabled, it exclusively owns the interval below zero;
    the outline starts at the coating upper surface, as raster S08 does.

    矢量分支不经过 S08，没有 ``total_layers`` 可用；这里按
    ``VectorProcessor.build_mesh`` 的 Z 轴布局计算外轮廓高度。
    """
    layer_h = (
        _resolve_vector_layer_height_mm(ctx)
        if layer_height_mm is None
        else float(layer_height_mm)
    )
    try:
        spacer_thick = float(ctx.get("spacer_thick", 1.6) or 1.6)
    except (TypeError, ValueError):
        spacer_thick = 1.6
    backing_layers = max(1, int(round(spacer_thick / layer_h)))
    backing_height_mm = backing_layers * layer_h

    try:
        num_layers = max(0, int(getattr(analysis, "num_layers", 0) or 0))
    except (TypeError, ValueError):
        num_layers = 0
    color_height_mm = num_layers * layer_h

    structure_mode_text = str(ctx.get("structure_mode", "") or "")
    color_mode_text = str(
        export_color_mode
        if export_color_mode is not None
        else ctx.get("color_mode", "")
    )
    is_double = "双面" in structure_mode_text or "Double" in structure_mode_text
    is_5color = "5-Color Extended" in color_mode_text

    # build_mesh places 5-Color optical layers above the backing even when
    # structure_mode says double; the current double helper overlaps that
    # same span instead of making the object taller. Preserve that geometry.
    # build_mesh 里 5 色扩展模式的彩色层位于底板上方；即使 structure_mode 是
    # double，现有双面 helper 也落在同一段 Z 空间，不增加总高度。
    color_passes = 1 if is_5color else (2 if is_double else 1)
    z_min = 0.0
    z_max = backing_height_mm + color_passes * color_height_mm

    if not np.isfinite(z_max) or z_max <= z_min:
        z_max = z_min + backing_height_mm
    return float(z_min), float(z_max)


def _resolve_vector_outline_export_size_mm(
    analysis,
    scale_factor: float,
) -> tuple[float, float] | None:
    """Return the vector export width/height in millimetres, if available.
    返回 vector 导出宽高（毫米），不可可靠解析时返回 ``None``。

    ``VectorProcessor.build_mesh`` requires the same finite canvas dimensions
    before it can construct body geometry.  The outline helper keeps this
    guard so auxiliary geometry never applies an export transform to an
    incomplete analysis object.

    ``VectorProcessor.build_mesh`` 同样要求 ``analysis.bbox[2:4] *
    analysis.scale_factor`` 是有限画布尺寸；Outline 保留这一门禁，避免对
    不完整分析对象应用导出变换。
    """
    bbox_raw = getattr(analysis, "bbox", None)
    if not isinstance(bbox_raw, (list, tuple, np.ndarray)) or len(bbox_raw) < 4:
        return None
    try:
        width_mm = float(bbox_raw[2]) * float(scale_factor)
        height_mm = float(bbox_raw[3]) * float(scale_factor)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(width_mm) or not np.isfinite(height_mm):
        return None
    if width_mm <= 0 or height_mm <= 0:
        return None
    return width_mm, height_mm


def _apply_vector_outline_export_transform(
    outline_mesh: trimesh.Trimesh,
    *,
    analysis,
    ctx: dict,
    scale_factor: float,
    export_color_mode: object | None = None,
) -> None:
    """Apply the same XY export transform used by vector body meshes.
    对 Outline 应用与 vector 主体网格一致的 XY 导出变换。

    Body meshes are normalised in ``VectorProcessor.build_mesh`` after
    extrusion: SVG's Y-down coordinates are flipped into printer Y-up space,
    and non-5-colour single-sided exports are mirrored on X. The Outline mesh
    is generated outside ``build_mesh``, so it must repeat those two transforms
    explicitly.

    主体网格在 ``VectorProcessor.build_mesh`` 里完成坐标归一：先把 SVG 的
    Y-down 坐标翻到打印坐标，再对非 5 色单面导出做 X 镜像。Outline 是在
    ``build_mesh`` 外部生成的，因此这里显式复用同一组变换。
    """
    if _resolve_vector_outline_export_size_mm(analysis, scale_factor) is None:
        return
    y_flip = np.eye(4)
    y_flip[1, 1] = -1.0
    outline_mesh.apply_transform(y_flip)

    structure_mode_text = str(ctx.get("structure_mode", "") or "")
    # Match VectorProcessor.build_mesh(), which uses the processor's
    # color_mode for the single-sided X mirror decision. In material-archive
    # mode that value is "Material Archive", not the UI color_mode stored in
    # ctx.
    color_mode_source = (
        export_color_mode
        if export_color_mode is not None
        else ctx.get("color_mode", "")
    )
    color_mode_text = str(color_mode_source or "")
    is_single_sided = "单面" in structure_mode_text or "Single" in structure_mode_text
    is_5color = "5-Color Extended" in color_mode_text
    if is_single_sided and not is_5color:
        mirror_x = np.eye(4)
        mirror_x[0, 0] = -1.0
        outline_mesh.apply_transform(mirror_x)


def _generate_vector_outline_mesh(
    analysis,
    outline_width_mm: float,
    base_aux_color: list[int],
    base_aux_material_name: str | None,
    ctx: dict,
    export_color_mode: object | None = None,
) -> "trimesh.Trimesh | None":
    """Extrude the shared structural ring above the coating surface.

    从共用结构计划生成描边；描边不进入透明镀层的高度区间。

    Args:
        analysis: Source SVG analysis. 源 SVG 解析结果。
        outline_width_mm: Outline width in mm. 毫米描边宽度。
        base_aux_color: Outline RGBA. 描边颜色。
        base_aux_material_name: Material identity. 描边材料标识。
        ctx: Generation parameters. 生成参数。
        export_color_mode: Export orientation mode. 导出朝向模式。

    Returns:
        Outline mesh or None for an empty ring. 描边网格，空描边返回 None。
    """
    structure = resolve_structure_plan(analysis, float(outline_width_mm))
    ring = structure.outline
    if ring.is_empty:
        log.warning(
            "Vector outline rejected: structural ring is empty",
            extra={
                "event": "vector_outline_rejected_unsupported",
                "error_type": "unsupported_subset",
                "unsupported_reason": "D6_ring_empty",
                "outline_width_mm": float(outline_width_mm),
            },
        )
        return None
    scale_factor = float(getattr(analysis, "scale_factor", 1.0))
    layer_h = _resolve_vector_layer_height_mm(ctx)
    z_min_mm, z_max_mm = _resolve_vector_outline_z_span(
        ctx,
        analysis,
        export_color_mode=export_color_mode,
        layer_height_mm=layer_h,
    )
    thickness_mm = max(layer_h, z_max_mm - z_min_mm)
    outline_layers = max(1, int(round(thickness_mm / layer_h)))
    outline_height_mm = float(outline_layers) * layer_h

    outline_slabs = [
            {
                "geometry": ring,
                "height": outline_height_mm,
                "z_offset": z_min_mm,
            }
        ]
    outline_policy = None
    if isinstance(getattr(analysis, "svg_coordinate_domain", None), SvgCoordinateDomain):
        coordinate_domain = getattr(analysis, "coordinate_domain", None)
        grid_mm = (
            coordinate_domain.xy_grid_mm if coordinate_domain is not None
            else resolve_vector_writer_grid_mm(
                max(abs(v) for v in structure.envelope.bounds) * structure.mm_per_unit
            )
        )
        outline_policy = VectorLayerGeometryPolicy(grid_mm=grid_mm)
        prepare_print_slabs(outline_slabs, mm_per_unit=structure.mm_per_unit, grid_mm=grid_mm)
    outline_mesh = build_vector_layered_volume(
        outline_slabs,
        scale_mm_per_svg_unit=structure.mm_per_unit,
        policy=outline_policy,
    )
    if outline_mesh is None:
        return None

    # The new builder already emits millimetres and independent component
    # ranges. Release the source geometry before applying only the historical
    # final orientation transform.
    del ring
    _apply_vector_outline_export_transform(
        outline_mesh,
        analysis=analysis,
        ctx=ctx,
        scale_factor=scale_factor,
        export_color_mode=export_color_mode,
    )

    rgba = list(base_aux_color)
    if len(rgba) < 4:
        rgba = [int(rgba[0]), int(rgba[1]), int(rgba[2]), 255]
    outline_mesh.visual.face_colors = np.tile(
        np.asarray(rgba[:4], dtype=np.uint8),
        (len(outline_mesh.faces), 1),
    )
    outline_mesh.metadata["name"] = "Outline"
    if base_aux_material_name:
        outline_mesh.metadata["bambu_material_name"] = base_aux_material_name

    return outline_mesh


def _update_bambu_base_layer_ctx_for_vector(
    ctx: dict,
    *,
    color_mode: str,
    structure_mode: str,
    num_layers: int,
    thickness_mm: float,
    layer_height_mm: float | None = None,
) -> None:
    """Populate Bambu base-layer modifier values for the vector export branch.
    \u4e3a\u77e2\u91cf\u5bfc\u51fa\u5206\u652f\u586b\u5145 Bambu \u5e95\u677f\u7c97\u5c42\u9ad8\u76f8\u5173\u4e0a\u4e0b\u6587\u503c\u3002

    Args:
        ctx (dict): Pipeline context updated in place.
            \uff08\u5c31\u5730\u66f4\u65b0\u7684\u6d41\u6c34\u7ebf\u4e0a\u4e0b\u6587\u5b57\u5178\uff09
        color_mode (str): Effective color mode resolved by the vector branch.
            \uff08\u77e2\u91cf\u5206\u652f\u89e3\u6790\u540e\u7684\u989c\u8272\u6a21\u5f0f\uff09
        structure_mode (str): Effective structure mode used for mesh extrusion.
            \uff08\u7528\u4e8e\u7f51\u683c\u62c9\u4f38\u7684\u5b9e\u9645\u7ed3\u6784\u6a21\u5f0f\uff09
        num_layers (int): Optical color-layer count reported by vector analysis.
            \uff08\u77e2\u91cf\u5206\u6790\u5f97\u5230\u7684\u5f69\u8272\u5149\u5b66\u5c42\u5c42\u6570\uff09
        thickness_mm (float): Requested backing thickness in millimetres.
            \uff08\u8bf7\u6c42\u7684\u5e95\u677f\u539a\u5ea6\uff0c\u5355\u4f4d\u6beb\u7c73\uff09
        layer_height_mm (float | None): Effective vector layer height. ``None``
            preserves the historical printer default.\uff08\u5b9e\u9645\u77e2\u91cf\u5c42\u9ad8\uff1b``None``
            \u65f6\u6cbf\u7528\u5386\u53f2\u6253\u5370\u673a\u9ed8\u8ba4\u503c\u3002\uff09
    """
    from config import PrinterConfig

    try:
        layer_h = float(
            PrinterConfig.LAYER_HEIGHT
            if layer_height_mm is None
            else layer_height_mm
        )
    except (TypeError, ValueError):
        layer_h = float(PrinterConfig.LAYER_HEIGHT)
    if not np.isfinite(layer_h) or layer_h <= 0:
        layer_h = float(PrinterConfig.LAYER_HEIGHT)
    backing_layer_count = max(1, int(round(float(thickness_mm) / layer_h)))
    base_height_mm = backing_layer_count * layer_h
    coating_layers = 0
    if bool(ctx.get("enable_coating", False)):
        try:
            coating_height_mm = float(ctx.get("coating_height_mm", layer_h))
        except (TypeError, ValueError):
            coating_height_mm = layer_h
        if np.isfinite(coating_height_mm) and coating_height_mm > 0:
            coating_layers = max(1, int(round(coating_height_mm / layer_h)))
    color_height_mm = (max(0, int(num_layers)) + coating_layers) * layer_h

    structure_mode_text = str(structure_mode or "")
    color_mode_text = str(color_mode or "")
    is_double = "\u53cc\u9762" in structure_mode_text or "Double" in structure_mode_text
    is_5color = "5-Color Extended" in color_mode_text

    if is_double:
        face_orientation = "double"
    elif is_5color or bool(ctx.get("enable_relief", False)):
        face_orientation = "up"
    else:
        face_orientation = "down"

    ctx["bambu_base_height_mm"] = float(base_height_mm)
    ctx["bambu_color_height_mm"] = float(color_height_mm)
    ctx["bambu_face_orientation"] = face_orientation
    ctx["enable_base_layer_height_modifier"] = bool(
        ctx.get("enable_base_layer_height_modifier", True)
    ) and not bool(ctx.get("enable_relief", False))


# ===================================================================
# Vector preview branch (SVG native preview processing)
# ===================================================================


def _log_vector_color_drift_diagnostics(analysis, raster_cache) -> None:
    """Emit DEBUG + INFO diagnostics summarising per-unique-fill color drift.

    For material-archive + SVG + vector mode, users occasionally see
    "grey speckles" inside a shape that should be solidly coloured.
    This helper aggregates ``analysis.matched_shapes`` by unique
    (source fill RGB, matched RGB) pair and logs:

    - DEBUG per pair: shape count, total polygon area, Top2Bottom
      recipe, approximate Lab ΔE between source and matched.
    - One INFO line per preview run: worst offender's drift distance
      so visible color drift can be diagnosed from ordinary logs.

    汇总每个唯一 (源填充色 -> matched RGB) 对，输出 DEBUG 明细和
    一条 INFO 汇总，帮助定位 "应该是橙色的地方冒出灰色像素" 这
    类偏色问题。

    Args:
        analysis: ``VectorAnalysis`` from ``VectorProcessor.analyze_svg``.
        raster_cache: Dict returned by ``build_preview_cache``.
    """
    shapes = list(getattr(analysis, "matched_shapes", []) or [])
    if not shapes:
        return

    # Aggregate by (src, matched)
    buckets: dict = {}
    for s in shapes:
        src = tuple(int(c) for c in (s.get("color") or (0, 0, 0)))
        matched = tuple(int(c) for c in (s.get("matched_rgb") or src))
        recipe = tuple(int(x) for x in (s.get("recipe") or ()))
        key = (src, matched, recipe)
        b = buckets.setdefault(
            key,
            {"count": 0, "area": 0.0, "recipe": recipe, "src": src, "matched": matched},
        )
        b["count"] += 1
        geom = s.get("geometry")
        try:
            if geom is not None and not geom.is_empty:
                b["area"] += float(geom.area)
        except Exception:
            pass

    # Compute Lab ΔE for src vs matched so grey-drift is quantifiable.
    src_arr = np.array([b["src"] for b in buckets.values()], dtype=np.uint8)
    matched_arr = np.array([b["matched"] for b in buckets.values()], dtype=np.uint8)
    try:
        lab_src = cv2.cvtColor(src_arr.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float64)
        lab_m = cv2.cvtColor(matched_arr.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB).reshape(-1, 3).astype(np.float64)
        delta_e = np.linalg.norm(lab_src - lab_m, axis=1)
    except Exception:
        delta_e = np.zeros((len(buckets),), dtype=np.float64)

    # Attach delta-e and chroma metrics back onto buckets
    for i, b in enumerate(buckets.values()):
        b["delta_e_lab"] = float(delta_e[i])
        # Neutrality = how grey-ish the matched colour is compared to
        # the source. A grey-ish matched RGB inside a saturated source
        # is the visible artefact; flag when matched chroma is much
        # lower than source chroma.
        src_range = float(max(b["src"]) - min(b["src"]))
        mat_range = float(max(b["matched"]) - min(b["matched"]))
        b["src_chroma_range"] = src_range
        b["matched_chroma_range"] = mat_range
        b["chroma_drop"] = src_range - mat_range  # >0 = more grey

    # DEBUG per-bucket
    for b in buckets.values():
        src = b["src"]; m = b["matched"]
        log.debug(
            "vector material fill: src=#%02X%02X%02X -> matched=#%02X%02X%02X "
            "shapes=%d area=%.3f dE=%.2f chroma_drop=%.1f recipe=%s",
            src[0], src[1], src[2], m[0], m[1], m[2],
            b["count"], b["area"], b["delta_e_lab"], b["chroma_drop"], list(b["recipe"]),
            extra={
                "event": "vector_material_fill_mapping",
                "src_rgb": list(src),
                "matched_rgb": list(m),
                "shape_count": int(b["count"]),
                "total_area": float(b["area"]),
                "delta_e_lab": float(b["delta_e_lab"]),
                "src_chroma_range": float(b["src_chroma_range"]),
                "matched_chroma_range": float(b["matched_chroma_range"]),
                "chroma_drop": float(b["chroma_drop"]),
                "recipe_top2btm": list(b["recipe"]),
            },
        )

    # Preview-space pixel scan: count "greyish" opaque pixels in the
    # hard-edged matched_rgb map so we can distinguish anti-aliasing
    # artefacts (which live only in preview_rgba) from real drift
    # (which shows up in matched_rgb too). If the two counts diverge,
    # the issue is rasterisation/AA; if they agree, it's solver drift.
    # 同时扫硬边 matched_rgb 和抗锯齿 preview_rgba 两张图的灰度比例，
    # 如果前者不灰后者灰 → 抗锯齿边缘问题；如果前者就灰 → 求解器偏色。
    mrgb = raster_cache.get("matched_rgb")
    prgba = raster_cache.get("preview_rgba")
    grey_hard = grey_preview = opaque_hard = opaque_preview = 0
    if mrgb is not None and prgba is not None:
        m_int = mrgb.astype(np.int16)
        nonzero = (m_int.sum(axis=-1) > 0)
        gh = (
            nonzero
            & (np.abs(m_int[..., 0] - m_int[..., 1]) < 20)
            & (np.abs(m_int[..., 1] - m_int[..., 2]) < 20)
            & (m_int[..., 0] > 100)
            & (m_int[..., 0] < 220)
        )
        grey_hard = int(gh.sum())
        opaque_hard = int(nonzero.sum())

        p_int = prgba[..., :3].astype(np.int16)
        opaque = prgba[..., 3] > 50
        gp = (
            opaque
            & (np.abs(p_int[..., 0] - p_int[..., 1]) < 20)
            & (np.abs(p_int[..., 1] - p_int[..., 2]) < 20)
            & (p_int[..., 0] > 100)
            & (p_int[..., 0] < 220)
        )
        grey_preview = int(gp.sum())
        opaque_preview = int(opaque.sum())

    # INFO summary: one line per preview covers most triage needs.
    worst = max(buckets.values(), key=lambda b: b["delta_e_lab"]) if buckets else None
    worst_chroma = max(buckets.values(), key=lambda b: b["chroma_drop"]) if buckets else None
    log.info(
        "vector material preview drift: unique_fills=%d worst_dE=%.2f "
        "worst_chroma_drop=%.1f grey_hard=%d/%d grey_preview=%d/%d",
        len(buckets),
        (worst["delta_e_lab"] if worst else 0.0),
        (worst_chroma["chroma_drop"] if worst_chroma else 0.0),
        grey_hard, opaque_hard, grey_preview, opaque_preview,
        extra={
            "event": "vector_material_preview_drift_summary",
            "unique_fill_count": len(buckets),
            "total_shape_count": sum(b["count"] for b in buckets.values()),
            "worst_src_rgb": list(worst["src"]) if worst else None,
            "worst_matched_rgb": list(worst["matched"]) if worst else None,
            "worst_delta_e_lab": float(worst["delta_e_lab"]) if worst else 0.0,
            "worst_chroma_src_rgb": list(worst_chroma["src"]) if worst_chroma else None,
            "worst_chroma_matched_rgb": list(worst_chroma["matched"]) if worst_chroma else None,
            "worst_chroma_drop": float(worst_chroma["chroma_drop"]) if worst_chroma else 0.0,
            "grey_pixels_hard": grey_hard,
            "opaque_pixels_hard": opaque_hard,
            "grey_pixels_preview": grey_preview,
            "opaque_pixels_preview": opaque_preview,
        },
    )


def _resolve_vector_layer_height_mm(ctx: dict) -> float:
    """Return the validated effective layer height for native vector flows.

    普通矢量生成、预览与大画幅切片必须共享同一有效层高；缺失或非法值
    回退到打印机配置默认值，保持历史 0.08 mm 行为。
    """
    fallback = float(PrinterConfig.LAYER_HEIGHT)
    try:
        layer_height_mm = float(ctx.get("layer_height_mm") or fallback)
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(layer_height_mm) or layer_height_mm <= 0:
        return fallback
    return layer_height_mm


def _build_vector_processor(ctx: dict, *, fallback_color_mode: str):
    """Build a ``VectorProcessor`` for the current ctx.

    Routes to the LUT-backed constructor for the historical path and to
    :class:`core.vector_matchers.MaterialVectorMatcher` for
    ``material_source == "material_archive"``. Both paths return a
    fully-configured ``VectorProcessor`` that shares the rest of the
    pipeline (parse / clip / extrude / preview) verbatim.

    根据 ``material_source`` 选择 LUT 或耗材档案匹配器，把构造细节
    封装在此处，调用方不再分支两条 import 路径。

    Args:
        ctx: Pipeline context. Must contain ``actual_lut_path`` for the
            LUT path or ``_material_params`` (plus the canonical
            material-archive metadata) for the material-archive path.
        fallback_color_mode: Color mode string used when the LUT path
            is taken (already resolved by the caller).

    Returns:
        ``VectorProcessor`` instance ready for ``analyze_svg``.
    """
    from core.vector_engine import VectorProcessor

    layer_height_mm = _resolve_vector_layer_height_mm(ctx)
    has_hue_settings = "hue_weight" in ctx or "chroma_gate" in ctx
    try:
        hue_weight = float(ctx.get("hue_weight") or 0.0)
    except (TypeError, ValueError):
        hue_weight = 0.0
    try:
        chroma_gate = float(
            ctx.get("chroma_gate") if ctx.get("chroma_gate") is not None else 15.0
        )
    except (TypeError, ValueError):
        chroma_gate = 15.0

    material_source = str(ctx.get("material_source") or "lut")
    if material_source == "material_archive":
        from core.material_cache import DEFAULT_GRID_RESOLUTION
        from core.vector_matchers import MaterialVectorMatcher

        materials = ctx.get("_material_params") or []
        if not materials:
            raise ValueError(
                "material_archive vector branch requires non-empty "
                "_material_params; did P01 / S01 validation run?"
            )
        dynamic_layer_count_enabled = bool(
            ctx.get("material_dynamic_layer_count_enabled", False)
        )
        try:
            dynamic_max_layer_count = int(
                ctx.get("material_max_layer_count") or ctx.get("color_layers") or 5
            )
        except (TypeError, ValueError):
            dynamic_max_layer_count = int(ctx.get("color_layers") or 5)
        try:
            dynamic_min_layer_count = int(
                ctx.get("material_min_layer_count") or 5
            )
        except (TypeError, ValueError):
            dynamic_min_layer_count = 5
        try:
            dynamic_delta_e00_tolerance = float(
                ctx.get("material_delta_e00_tolerance")
                if ctx.get("material_delta_e00_tolerance") is not None
                else 0.5
            )
        except (TypeError, ValueError):
            dynamic_delta_e00_tolerance = 0.5
        raw_backing_material_index = ctx.get("material_backing_material_index")
        if raw_backing_material_index is None:
            raw_backing_material_index = ctx.get("material_base_channel_idx", 0)
        try:
            backing_material_index = int(raw_backing_material_index or 0)
        except (TypeError, ValueError):
            backing_material_index = 0
        layer_count = (
            dynamic_max_layer_count
            if dynamic_layer_count_enabled
            else int(ctx.get("color_layers") or 5)
        )
        substrate = str(ctx.get("material_substrate") or "white")
        slot_names = list(ctx.get("slot_names") or [])
        preview_colors = dict(ctx.get("preview_colors") or {})
        color_conf = dict(ctx.get("color_conf") or {})
        grid_resolution = int(
            ctx.get("grid_resolution") or DEFAULT_GRID_RESOLUTION
        )

        matcher = MaterialVectorMatcher.from_materials(
            materials=materials,
            layer_count=layer_count,
            layer_height_mm=layer_height_mm,
            substrate=substrate,
            slot_names=slot_names,
            preview_colors=preview_colors,
            color_conf=color_conf,
            grid_resolution=grid_resolution,
            hue_weight=hue_weight,
            dynamic_layer_count_enabled=dynamic_layer_count_enabled,
            dynamic_min_layer_count=dynamic_min_layer_count,
            dynamic_max_layer_count=dynamic_max_layer_count,
            dynamic_delta_e00_tolerance=dynamic_delta_e00_tolerance,
            backing_material_index=backing_material_index,
        )
        _emit_vector_diag(
            extra={
                "event": "vector_diag_solver_cache_layer_order",
                "stage": "material_vector_matcher_init",
                "layer_count": int(layer_count),
                "grid_resolution": int(getattr(matcher, "actual_grid_resolution", grid_resolution)),
                "slot_count": len(slot_names),
                "material_count": len(materials),
                "recipe_order": "top_to_bottom",
                "dynamic_layer_count_enabled": dynamic_layer_count_enabled,
            },
        )
        processor = VectorProcessor.from_img_processor(matcher, "Material Archive")
        try:
            processor.gradient_color_bands = max(
                16,
                min(32, int(ctx.get("quantize_colors") or 16)),
            )
        except (TypeError, ValueError):
            processor.gradient_color_bands = 16
        processor.layer_height_mm = layer_height_mm
        _configure_svg_hole_compensation(processor, ctx)
        return processor

    actual_lut_path = ctx.get("actual_lut_path")
    processor_kwargs = {}
    if has_hue_settings:
        processor_kwargs = {
            "hue_weight": hue_weight,
            "chroma_gate": chroma_gate,
        }
    processor = VectorProcessor(
        actual_lut_path,
        fallback_color_mode,
        **processor_kwargs,
    )
    processor.layer_height_mm = layer_height_mm
    _configure_svg_hole_compensation(processor, ctx)
    return processor


def _build_vector_parse_cache_artifacts(
    image_path: str, target_width_mm: float, processor: Any, analysis: Any,
) -> dict[str, Any] | None:
    """Serialize source geometry and its provenance, never compensated geometry.
    仅序列化原始解析几何及其来源，不把补偿后的几何存入解析缓存。
    """
    from core.vector_engine import (
        _VECTOR_PARSE_CLIP_CACHE,
        _serialize_vector_parse_clip_cache,
        _vector_parse_clip_cache_key,
        _vector_parse_clip_cache_provenance,
    )

    key = _vector_parse_clip_cache_key(
        image_path,
        target_width_mm=target_width_mm,
        sampling_precision=processor.sampling_precision,
        expand_stroke_to_fill=bool(getattr(processor, "expand_stroke_to_fill", False)),
        gradient_color_bands=getattr(processor, "gradient_color_bands", None),
    )
    entry = _VECTOR_PARSE_CLIP_CACHE.get(key)
    if entry is None:
        if getattr(processor, "svg_hole_compensation_enabled", False):
            return None
        entry = {
            "shape_data": analysis.shape_data,
            "clipped_shapes": analysis.clipped_shapes,
            "silhouette": analysis.silhouette,
            "image_vectorizer_bounds": analysis.image_vectorizer_bounds,
            "scale_factor": analysis.scale_factor,
            "bbox": analysis.bbox,
            "svg_coordinate_domain": analysis.svg_coordinate_domain,
            "parse_warnings": list(getattr(processor, "parse_warnings", None) or []),
            "geometry_stage_timings": dict(analysis.stage_timings or {}),
        }
    return {
        "vector_parse_clip_cache_blob": _serialize_vector_parse_clip_cache(key, entry),
        "vector_parse_clip_cache_provenance": _vector_parse_clip_cache_provenance(key),
    }


def _configure_svg_hole_compensation(processor: Any, ctx: dict) -> None:
    processor.svg_hole_compensation_enabled = bool(
        ctx.get("svg_hole_compensation_enabled", False)
    )
    processor.svg_hole_max_area_mm2 = float(ctx.get("svg_hole_max_area_mm2", 0.5))
    processor.svg_hole_max_width_mm = float(ctx.get("svg_hole_max_width_mm", 0.1))


def _record_material_parallelism(
    timings: dict,
    vector_processor: object,
) -> None:
    """Attach bounded material-matching scheduling diagnostics when available."""

    matcher = getattr(vector_processor, "img_processor", None)
    worker_count = getattr(
        matcher,
        "effective_parallelism_workers",
        None,
    )
    if worker_count is None:
        return
    try:
        timings["material_parallelism_workers"] = float(
            max(1, int(worker_count)),
        )
    except (TypeError, ValueError):
        return
    plan = getattr(matcher, "effective_parallelism_plan", None)
    if plan is None:
        return
    try:
        plan_fields = {
            "material_parallelism_limit": str(
                plan.limiting_reason,
            )[:64],
            "material_parallelism_effective_cpu": float(
                max(1, int(plan.effective_cpu_capacity)),
            ),
            "material_parallelism_cpu_topology": str(
                plan.cpu_topology,
            )[:64],
            "material_parallelism_cpu_scheduling_policy": str(
                plan.cpu_scheduling_policy,
            )[:64],
            "material_parallelism_outer_demand": float(
                max(1, int(plan.outer_demand)),
            ),
            "material_parallelism_cpu_fair_share": float(
                max(1, int(plan.cpu_fair_share_ceiling)),
            ),
            "material_parallelism_demand_fallback": bool(
                plan.demand_snapshot_fallback,
            ),
        }
    except (AttributeError, TypeError, ValueError):
        return
    if plan.performance_cpu_capacity is not None:
        plan_fields["material_parallelism_performance_cpu"] = float(
            max(1, int(plan.performance_cpu_capacity)),
        )
    timings.update(plan_fields)


def _run_vector_preview_branch(ctx: dict) -> dict:
    """Execute SVG native preview processing for vector mode.
    \u4e3a SVG + vector \u6a21\u5f0f\u6784\u5efa\u4e0e native vector \u751f\u6210\u4e00\u81f4\u7684\u9884\u89c8\u7f13\u5b58\u3002

    Routes through :func:`_build_vector_processor` so both LUT and
    material-archive sources share a single preview implementation.
    LUT \u4e0e\u8017\u6750\u6863\u6848\u4e24\u79cd\u6765\u6e90\u5728\u8fd9\u91cc\u5171\u4eab\u540c\u4e00\u4efd\u9884\u89c8\u5b9e\u73b0\uff0c\u53ea\u662f\u989c\u8272\u5339\u914d\u5668\u4e0d\u540c\u3002
    """
    image_path = ctx["image_path"]
    color_mode = ctx["color_mode"]
    target_width_mm = ctx["target_width_mm"]
    is_dark = ctx.get("is_dark", True)
    quantize_colors = ctx.get("quantize_colors", 64)
    backing_color_id = ctx.get("backing_color_id", 0)
    lut_metadata = ctx.get("lut_metadata")
    preview_timing: dict[str, float | str | bool] = {}
    vector_preview_total_t0 = time.perf_counter()
    # Native dynamic-material matching needs the structured replacement records
    # so VectorProcessor can resolve all source fills behind one matched palette
    # colour before its final exact solve. Legacy dict inputs remain supported.
    vector_replacements = ctx.get("replacement_regions")
    if not vector_replacements:
        vector_replacements = ctx.get("color_replacements")

    try:
        from core.vector_engine import VectorProcessor  # noqa: F401  -- re-imported for typing parity

        t0 = time.perf_counter()
        vec_processor = _build_vector_processor(ctx, fallback_color_mode=color_mode)
        preview_timing["processor_init_s"] = time.perf_counter() - t0
        t0 = time.perf_counter()
        analysis = vec_processor.analyze_svg(
            svg_path=image_path,
            target_width_mm=target_width_mm,
            color_replacements=vector_replacements,
        )
        preview_timing.update(
            _structured_timing_payload(
                getattr(analysis, "stage_timings", {})
            )
        )
        _record_material_parallelism(preview_timing, vec_processor)
        preview_timing["analyze_svg_s"] = time.perf_counter() - t0

        t0 = time.perf_counter()
        raster_cache = VectorProcessor.build_preview_cache(
            analysis,
            pixels_per_mm=10.0,
        )
        preview_timing["build_preview_cache_s"] = time.perf_counter() - t0
        _emit_vector_diag(
            extra={
                "event": "vector_diag_preview_material_matrix_layer0",
                "stage": "preview_material_matrix",
                "material_matrix": _layer0_channel_histogram(
                    raster_cache.get("material_matrix"),
                    raster_cache.get("mask_solid"),
                ),
                "shape_recipe0": _shape_recipe0_histogram(
                    getattr(analysis, "matched_shapes", []) or []
                ),
            },
        )
        _emit_vector_diag(
            extra={
                "event": "vector_diag_stage_a_preview_per_layer_channel",
                "stage": "preview_material_matrix",
                "material_matrix": _per_layer_channel_histogram(
                    raster_cache.get("material_matrix"),
                    raster_cache.get("mask_solid"),
                ),
            },
        )

        # Diagnostic: material-archive vector + preview-colour-drift
        # triage helper. Logs, per unique (source fill -> matched RGB)
        # pair, the shape count / total area / recipe / Lab delta-E so
        # "why do I see grey pixels inside an orange shape" can be
        # answered from a single preview run.
        # 矢量 + 耗材档案模式下按唯一 (源色 -> matched RGB) 聚合
        # 形状数、总面积、配方和 Lab ΔE，方便一次预览就能定位偏色。
        if str(ctx.get("material_source") or "lut") == "material_archive":
            _log_vector_color_drift_diagnostics(analysis, raster_cache)

        pristine_matched_rgb = raster_cache.get(
            "original_matched_rgb",
            raster_cache.get("height_identity_rgb", raster_cache["matched_rgb"]),
        )
        height_identity_rgb = raster_cache.get(
            "height_identity_rgb",
            pristine_matched_rgb,
        )
        pristine_material_matrix = raster_cache.get(
            "original_material_matrix",
            raster_cache["material_matrix"],
        )

        dynamic_layer_info = getattr(analysis, "material_dynamic_layer_info", None)
        material_solver_info = getattr(analysis, "material_solver_info", None)
        dynamic_layer_active = isinstance(dynamic_layer_info, dict) and bool(
            dynamic_layer_info.get("enabled")
        )
        effective_color_layers = (
            int(getattr(analysis, "num_layers", 0) or 0)
            if dynamic_layer_active
            else ctx.get("color_layers")
        )
        cache = {
            "target_w": raster_cache["target_w"],
            "target_h": raster_cache["target_h"],
            "target_width_mm": target_width_mm,
            "pixel_scale": raster_cache["pixel_scale"],
            "mask_solid": raster_cache["mask_solid"],
            "backing_mask": raster_cache.get("backing_mask"),
            "material_matrix": raster_cache["material_matrix"],
            "matched_rgb": raster_cache["matched_rgb"],
            "original_matched_rgb": pristine_matched_rgb,
            "height_identity_rgb": height_identity_rgb,
            "original_material_matrix": pristine_material_matrix,
            "preview_rgba": raster_cache["preview_rgba"].copy(),
            "color_conf": analysis.color_conf,
            "color_mode": color_mode,
            "color_layers": effective_color_layers or ctx.get("color_layers"),
            "layer_height_mm": ctx.get("layer_height_mm"),
            "model_enable": bool(ctx.get("model_enable", False)),
            "model_only": bool(ctx.get("model_only", False)),
            "model_threshold": ctx.get("model_threshold"),
            "model_margin": ctx.get("model_margin"),
            "material_source": ctx.get("material_source", "lut"),
            "modeling_mode": ctx.get("modeling_mode"),
            "quantize_colors": quantize_colors,
            "enable_cleanup": bool(ctx.get("enable_cleanup", True)),
            "svg_pixels_per_mm": ctx.get("svg_pixels_per_mm"),
            "svg_hole_compensation_enabled": bool(ctx.get("svg_hole_compensation_enabled", False)),
            "svg_hole_max_area_mm2": ctx.get("svg_hole_max_area_mm2", 0.5),
            "svg_hole_max_width_mm": ctx.get("svg_hole_max_width_mm", 0.1),
            "hue_weight": ctx.get("hue_weight", 0.0),
            "chroma_gate": ctx.get("chroma_gate", 15.0),
            "use_lut_constrained": bool(
                ctx.get("use_lut_constrained", False)
            ),
            "auto_dynamic_range": bool(ctx.get("auto_dynamic_range", False)),
            "backing_color_id": backing_color_id,
            "spacer_thick": ctx.get("spacer_thick", 1.6),
            "is_dark": is_dark,
            "bed_label": BedManager.DEFAULT_BED,
            "lut_metadata": lut_metadata,
            "preview_colors": dict(analysis.preview_colors),
            "slot_names": list(analysis.slot_names),
            "debug_data": None,
            "quantized_image": raster_cache["quantized_image"],
        }
        if dynamic_layer_active:
            cache["material_dynamic_layer_info"] = deepcopy(dynamic_layer_info)
            cache["original_material_dynamic_layer_info"] = deepcopy(
                dynamic_layer_info
            )
        if isinstance(material_solver_info, dict):
            cache["material_solver_info"] = deepcopy(material_solver_info)
            if dynamic_layer_active:
                cache["original_material_solver_info"] = deepcopy(
                    material_solver_info
                )
        try:
            source_cache = _build_vector_parse_cache_artifacts(
                image_path, target_width_mm, vec_processor, analysis,
            )
            if source_cache is not None:
                cache.update(source_cache)
        except COORDINATOR_HANDLED_ERRORS as exc:
            log.debug(
                "Vector parse/clip cache artifact build skipped",
                extra={
                    "event": "vector_parse_clip_cache_artifact_skipped",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
        cache["color_palette"] = extract_color_palette(cache)

        ctx["matched_rgb"] = raster_cache["matched_rgb"]
        ctx["original_matched_rgb"] = pristine_matched_rgb
        ctx["height_identity_rgb"] = height_identity_rgb
        ctx["material_matrix"] = raster_cache["material_matrix"]
        ctx["original_material_matrix"] = pristine_material_matrix
        ctx["mask_solid"] = raster_cache["mask_solid"]
        ctx["backing_mask"] = raster_cache.get("backing_mask")
        ctx["target_w"] = raster_cache["target_w"]
        ctx["target_h"] = raster_cache["target_h"]
        ctx["quantized_image"] = raster_cache["quantized_image"]
        ctx["preview_rgba"] = raster_cache["preview_rgba"]
        ctx["cache"] = cache
        ctx["color_conf"] = analysis.color_conf
        ctx["preview_colors"] = dict(analysis.preview_colors)
        ctx["slot_names"] = list(analysis.slot_names)
        if dynamic_layer_active and effective_color_layers:
            ctx["color_layers"] = effective_color_layers
        if "material_dynamic_layer_info" in cache:
            ctx["material_dynamic_layer_info"] = cache[
                "material_dynamic_layer_info"
            ]
            ctx["original_material_dynamic_layer_info"] = cache[
                "original_material_dynamic_layer_info"
            ]
        if "material_solver_info" in cache:
            ctx["material_solver_info"] = cache["material_solver_info"]
        if "original_material_solver_info" in cache:
            ctx["original_material_solver_info"] = cache[
                "original_material_solver_info"
            ]

        # Quick-preview GLBs contain only static colour/backing geometry.
        # The UI owns the live Outline overlay so spacer, structure mode, and
        # layer-height changes remain immediate. Physical export Outline meshes
        # stay in the generate branch's 3MF writer-local coordinate domain.
        # 快速预览仅携带静态色块和底板；实时描边由 UI 单一负责。用于最终导出的
        # Outline 继续留在 generate 分支的 3MF writer-local 坐标域中。

        t0 = time.perf_counter()
        ctx = p06_bed_rendering.run(ctx)
        preview_timing["bed_rendering_s"] = time.perf_counter() - t0
        preview_timing["vector_preview_total_s"] = time.perf_counter() - vector_preview_total_t0
        ctx["vector_timing"] = dict(preview_timing)
        _log_vector_preview_timings(preview_timing, ctx, analysis, raster_cache)
        return ctx
    except MemoryError:
        raise
    except Exception as exc:
        ctx["error"] = f"[VECTOR_PREVIEW] {exc}"
        log.exception("Vector preview branch failed: %s", exc)
        return ctx


# ===================================================================
# Vector branch (SVG native processing)
# ===================================================================


def _run_vector_branch(ctx: dict) -> dict:
    """Execute SVG native vector processing branch.
    \u6267\u884c SVG \u539f\u751f\u77e2\u91cf\u5904\u7406\u5206\u652f\u3002

    \u5f53 S01 \u68c0\u6d4b\u5230 ``is_svg_vector=True`` \u65f6\u7531 ``run_raster_pipeline``
    \u8c03\u7528\u3002\u4f7f\u7528 ``core.vector_engine.VectorProcessor`` \u5b8c\u6210 SVG \u2192 3D
    \u8f6c\u6362\uff0c\u5305\u62ec 3MF \u5bfc\u51fa\u3001\u8f7b\u91cf GLB \u5f15\u7528\u590d\u7528\u548c 2D \u9884\u89c8\u751f\u6210\u3002

    Args:
        ctx: \u7ecf\u8fc7 S01 \u9a8c\u8bc1\u540e\u7684 PipelineContext \u5b57\u5178

    Returns:
        \u66f4\u65b0\u540e\u7684 PipelineContext \u5b57\u5178\uff08\u5305\u542b result_tuple\uff09
    """
    from config import (  # noqa: F401  -- ColorSystem kept for parity
        ColorSystem,
        MODELS_DIR,
    )
    from core.naming import generate_model_filename
    from utils.bambu_3mf_writer import export_scene_with_bambu_metadata
    from utils import Stats

    image_path = ctx["image_path"]
    color_mode = ctx["color_mode"]
    modeling_mode = ctx["modeling_mode"]
    target_width_mm = ctx["target_width_mm"]
    spacer_thick = ctx["spacer_thick"]
    structure_mode = ctx["structure_mode"]
    color_replacements = ctx.get("color_replacements")
    replacement_regions = ctx.get("replacement_regions")
    enable_fridge_magnet = ctx.get("enable_fridge_magnet", False)
    fridge_magnets = ctx.get("fridge_magnets") or []
    recipe_overrides = ctx.get("recipe_overrides") or []
    recipe_override_masks_path = ctx.get("recipe_override_masks_path")
    requested_color_layers = ctx.get("color_layers")
    lut_metadata = ctx.get("lut_metadata")
    matched_rgb_path = ctx.get("matched_rgb_path")
    original_matched_rgb_path = ctx.get("original_matched_rgb_path")
    height_identity_rgb_path = ctx.get("height_identity_rgb_path")
    mask_solid_path = ctx.get("mask_solid_path")
    material_matrix_path = ctx.get("material_matrix_path")
    original_material_matrix_path = ctx.get("original_material_matrix_path")
    edit_projection = ctx.get("edit_projection")
    edit_projection_source_shape = None
    edit_projection_mode = None
    if isinstance(edit_projection, dict):
        edit_projection_mode = str(edit_projection.get("mode") or "")
        source_shape = edit_projection.get("source_shape")
        if isinstance(source_shape, (list, tuple)) and len(source_shape) == 2:
            edit_projection_source_shape = (
                int(source_shape[0]),
                int(source_shape[1]),
            )
    vector_preview_pixels_per_mm = 10.0
    try:
        backing_color_id = int(ctx.get("backing_color_id", 0) or 0)
    except (TypeError, ValueError):
        backing_color_id = 0
    separate_backing = ctx.get("separate_backing", False)
    try:
        separate_backing_color_id = int(
            ctx.get("separate_backing_color_id", backing_color_id) or 0
        )
    except (TypeError, ValueError):
        separate_backing_color_id = 0
    try:
        backing_channel_idx = max(0, int(backing_color_id))
    except (TypeError, ValueError):
        backing_channel_idx = 0

    vector_timing = {
        "matched_rgb_override_s": 0.0,
        "recipe_override_s": 0.0,
        "build_mesh_s": 0.0,
    }
    vector_total_t0 = time.perf_counter()
    log.info(
        "Vector branch started",
        extra={
            "event": "vector_branch_init",
            "image_name": os.path.basename(str(image_path)),
            "color_mode": str(color_mode),
            "modeling_mode": str(modeling_mode),
            "target_width_mm": float(target_width_mm),
            "structure_mode": str(structure_mode),
            "has_replacement_regions": bool(replacement_regions),
            "has_color_replacements": bool(color_replacements),
            "has_recipe_overrides": bool(recipe_overrides),
        },
    )

    # Retain structured replacement records for dynamic native SVG matching.
    # VectorProcessor normalizes legacy dict inputs internally.
    vector_replacements = replacement_regions
    if not vector_replacements:
        vector_replacements = color_replacements

    try:
        from core.vector_engine import (
            VectorProcessor,
            _concatenate_meshes_fast,
            apply_matched_rgb_overrides_to_analysis,
            apply_recipe_overrides_to_analysis,
        )

        vec_processor = _build_vector_processor(
            ctx, fallback_color_mode=color_mode
        )
        vec_processor.enable_fridge_magnet = bool(enable_fridge_magnet)
        vec_processor.fridge_magnets = list(fridge_magnets)
        vec_processor.enable_coating = bool(ctx.get("enable_coating", False))
        vec_processor.coating_height_mm = float(ctx.get("coating_height_mm", 0.08))
        vec_processor.coating_material = ctx.get("resolved_coating_material")
        vec_processor.enable_outline = bool(ctx.get("enable_outline", False))
        try:
            vec_processor.outline_width_mm = float(ctx.get("outline_width", 2.0) or 2.0)
        except (TypeError, ValueError):
            vec_processor.outline_width_mm = 2.0
        vec_processor.auto_dynamic_range = bool(ctx.get("auto_dynamic_range", False))
        if hasattr(vec_processor, "backing_color_id"):
            vec_processor.backing_color_id = backing_channel_idx
        parse_clip_cache_path = ctx.get("vector_parse_clip_cache_path")
        if parse_clip_cache_path:
            vec_processor._parse_clip_cache_path = str(parse_clip_cache_path)

        # 1. Unified analysis: parse \u2192 clip \u2192 match (shared by preview + mesh)
        _report_progress(ctx, 0.05, "SVG \u89e3\u6790\u4e0e\u51e0\u4f55\u5904\u7406\u4e2d... | Parsing & extruding SVG...")
        mesh_t0 = time.perf_counter()
        analysis = vec_processor.analyze_svg(
            svg_path=image_path,
            target_width_mm=target_width_mm,
            color_replacements=vector_replacements,
        )
        vector_timing["analyze_svg_s"] = time.perf_counter() - mesh_t0
        _record_material_parallelism(vector_timing, vec_processor)

        # 1.1 Project ColorWorkstation region edits (``/region-replace``,
        # ``/region-replace-batch``) back into ``analysis.matched_shapes``.
        # The 2D preview / GLB previews route through ``cache.matched_rgb``,
        # so without this step the SVG-native 3MF would silently drop every
        # spatial colour edit the user made.
        # \u628a ColorWorkstation \u7684\u533a\u57df\u6539\u8272\uff08/region-replace \u7b49\u7aef\u70b9\uff09\u56de\u5199\u5230
        # analysis.matched_shapes\uff0c\u5426\u5219\u77e2\u91cf 3MF \u4f1a\u4e22\u5931\u6240\u6709\u7a7a\u95f4\u66ff\u6362\uff0c\u9020\u6210
        # "2D \u9884\u89c8\u53d8\u4e86\u3001\u6700\u7ec8\u6a21\u578b\u6ca1\u53d8" \u7684\u73b0\u8c61\u3002
        cached_analysis_required = preview_analysis_reuse_is_required(
            ctx.get("reuse_preview_analysis")
        ) or (
            edit_projection_mode == "delta"
            and edit_projection_source_shape is not None
        )
        if cached_analysis_required and not (
            matched_rgb_path and mask_solid_path and material_matrix_path
        ):
            raise CachedPreviewAnalysisError(
                "Required vector preview analysis artifacts are incomplete"
            )
        if (
            matched_rgb_path
            and mask_solid_path
            and edit_projection_mode != "recipe_masks"
        ):
            matched_rgb_override_t0 = time.perf_counter()
            cached_matched_rgb = None
            raw_mask_solid = None
            cached_mask_solid = None
            cached_material_matrix = None
            cached_height_identity_rgb = None
            cached_original_matched_rgb = None
            cached_original_material_matrix = None
            try:
                cached_matched_rgb = np.load(
                    matched_rgb_path,
                    allow_pickle=False,
                    mmap_mode="r",
                )
                raw_mask_solid = np.load(
                    mask_solid_path,
                    allow_pickle=False,
                    mmap_mode="r",
                )
                cached_mask_solid = (
                    raw_mask_solid
                    if cached_analysis_required
                    else raw_mask_solid.astype(bool)
                )
                cached_material_matrix = None
                if material_matrix_path:
                    cached_material_matrix = np.load(
                        material_matrix_path,
                        allow_pickle=False,
                        mmap_mode="r",
                    )
                cached_height_identity_rgb = None
                if height_identity_rgb_path:
                    cached_height_identity_rgb = np.load(
                        height_identity_rgb_path,
                        allow_pickle=False,
                        mmap_mode="r",
                    )
                if original_matched_rgb_path:
                    cached_original_matched_rgb = np.load(
                        original_matched_rgb_path,
                        allow_pickle=False,
                        mmap_mode="r",
                    )
                if original_material_matrix_path:
                    cached_original_material_matrix = np.load(
                        original_material_matrix_path,
                        allow_pickle=False,
                        mmap_mode="r",
                    )
                if edit_projection_source_shape is not None and (
                    cached_original_matched_rgb is None
                    or cached_original_material_matrix is None
                ):
                    raise CachedPreviewAnalysisError(
                        "Required vector pristine edit artifacts are incomplete"
                    )

                # Diagnostic 2/4: material_matrix loaded from disk (post pad).
                if cached_material_matrix is not None:
                    _emit_vector_diag(
                        extra={
                            "event": "vector_diag_generate_loaded_material_matrix_layer0",
                            "stage": "generate_material_matrix_loaded",
                            "material_source": str(ctx.get("material_source") or "lut"),
                            "material_matrix_path": str(material_matrix_path),
                            "matched_rgb_shape": list(cached_matched_rgb.shape),
                            "mask_solid_solid_pixel_count": int(np.count_nonzero(cached_mask_solid)),
                            "material_base_channel_idx": int(ctx.get("material_base_channel_idx", -1)),
                            **_layer0_channel_histogram(
                                cached_material_matrix, cached_mask_solid
                            ),
                        }
                    )

                rewritten = apply_matched_rgb_overrides_to_analysis(
                    analysis,
                    matched_rgb=cached_matched_rgb,
                    original_matched_rgb=cached_original_matched_rgb,
                    height_identity_rgb=cached_height_identity_rgb,
                    material_matrix=cached_material_matrix,
                    original_material_matrix=cached_original_material_matrix,
                    mask_solid=cached_mask_solid,
                    img_processor=vec_processor.img_processor,
                    pixels_per_mm=vector_preview_pixels_per_mm,
                    source_grid_shape=edit_projection_source_shape,
                    strict=cached_analysis_required,
                    prefer_cached_material_state=bool(
                        ctx.get("material_dynamic_layer_count_enabled", False)
                        and str(ctx.get("material_source") or "lut")
                        == "material_archive"
                    ),
                )
                matched_override_metrics = getattr(
                    analysis,
                    "matched_rgb_override_metrics",
                    None,
                )
                if isinstance(matched_override_metrics, dict):
                    ctx["matched_rgb_override_metrics"] = dict(
                        matched_override_metrics
                    )
                    metric_types = {
                        "component_count": int,
                        "full_canvas_pixel_work": int,
                        "roi_pixel_work": int,
                        "max_roi_pixels": int,
                        "effective_pixel_count": int,
                        "pixel_work_reduction_ratio": float,
                    }
                    for metric_name, metric_type in metric_types.items():
                        metric_value = matched_override_metrics.get(metric_name)
                        if metric_value is None:
                            continue
                        vector_timing[
                            f"matched_rgb_override_{metric_name}"
                        ] = metric_type(metric_value)
                # Diagnostic 3/4: shape recipe[0] distribution after
                # apply_matched_rgb_overrides_to_analysis.
                _emit_vector_diag(
                    extra={
                        "event": "vector_diag_after_matched_rgb_overrides_recipe0",
                        "stage": "after_apply_matched_rgb_overrides",
                        "shapes_rewritten": int(rewritten),
                        "analysis_num_layers": int(getattr(analysis, "num_layers", 0) or 0),
                        "material_base_channel_idx": int(ctx.get("material_base_channel_idx", -1)),
                        **_shape_recipe0_histogram(
                            getattr(analysis, "matched_shapes", []) or []
                        ),
                    }
                )

                if rewritten:
                    log.info(
                        "Vector matched RGB overrides applied",
                        extra={
                            "event": "vector_matched_rgb_overrides_applied",
                            "shapes_rewritten": int(rewritten),
                            "matched_rgb_path": str(matched_rgb_path),
                            "height_identity_rgb_path": str(
                                height_identity_rgb_path or ""
                            ),
                            "mask_solid_path": str(mask_solid_path),
                        },
                    )
            except COORDINATOR_HANDLED_ERRORS as exc:
                if cached_analysis_required:
                    raise CachedPreviewAnalysisError(
                        "Required vector preview analysis could not be projected"
                    ) from exc
                log.warning(
                    "Failed to apply vector matched RGB overrides",
                    extra={
                        "event": "vector_matched_rgb_overrides_failed",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "matched_rgb_path": str(matched_rgb_path),
                        "height_identity_rgb_path": str(
                            height_identity_rgb_path or ""
                        ),
                        "mask_solid_path": str(mask_solid_path),
                    },
                )
            finally:
                vector_timing["matched_rgb_override_s"] = (
                    time.perf_counter() - matched_rgb_override_t0
                )
                # These cache arrays are only an input to the projection pass.
                # Drop the references before mesh construction so a fast ROI
                # pass does not overlap the preview-cache footprint with the
                # mesh builder's own temporary allocations.
                # 缓存数组只服务于覆盖投影；进入建模前释放，避免两段峰值叠加。
                del (
                    cached_matched_rgb,
                    raw_mask_solid,
                    cached_mask_solid,
                    cached_material_matrix,
                    cached_height_identity_rgb,
                    cached_original_matched_rgb,
                    cached_original_material_matrix,
                )

        # 1a. Apply per-region recipe overrides (custom recipe dialog +
        # appended layers) before meshing. Without this the 3MF is built
        # from the LUT's default match and silently ignores every edit
        # the user made in the "\u81ea\u5b9a\u4e49\u914d\u65b9" dialog \u2014 the 2D preview +
        # segmented GLB would reflect the override (they read the
        # material_matrix updated by ``/convert/apply-recipe-override``)
        # but the vector 3MF would not.
        # \u751f\u6210\u7f51\u683c\u524d\u5148\u628a\u81ea\u5b9a\u4e49\u914d\u65b9\u5bf9\u8bdd\u6846\u91cc\u7684 per-region \u914d\u65b9 / \u8ffd\u52a0\u7684\u5c42
        # \u56de\u5199\u5230 ``matched_shapes``\uff1b\u5426\u5219 3MF \u4ec5\u57fa\u4e8e LUT \u9ed8\u8ba4\u5339\u914d\uff0c\u7528\u6237
        # \u5728 "\u81ea\u5b9a\u4e49\u914d\u65b9" \u91cc\u505a\u7684\u7f16\u8f91\uff08\u5305\u62ec\u52a0\u5c42\uff09\u4f1a\u88ab\u6084\u6084\u4e22\u5f03\uff0c\u53ea\u6709 2D
        # \u9884\u89c8\u548c\u5206\u6bb5 GLB \u80fd\u770b\u5230\u3002
        if recipe_overrides and recipe_override_masks_path:
            recipe_override_t0 = time.perf_counter()
            import pickle as _pickle

            try:
                with open(recipe_override_masks_path, "rb") as f:
                    vector_region_masks = _pickle.load(f)
            except (OSError, EOFError, ValueError, TypeError, _pickle.PickleError) as exc:
                log.warning(
                    "Failed to load vector recipe override masks",
                    extra={
                        "event": "vector_recipe_overrides_load_failed",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                        "path": str(recipe_override_masks_path),
                    },
                )
                vector_region_masks = None

            if isinstance(vector_region_masks, dict) and vector_region_masks:
                # In material-archive mode there is no LUT metadata, so the
                # backing/white channel index lives on ctx (written by S01
                # input validation via ``infer_material_archive_base_channel_idx``).
                # Without this fallback the previous ``getattr(lut_metadata,
                # "base_channel_idx", 0) or 0`` quietly defaulted to channel 0,
                # which filled user-added layers with the first material in the
                # palette instead of the white backing slot — matching the
                # equivalent fix already applied to ``s03_color_replacement``.
                # 耗材档案模式下 ``lut_metadata`` 为 None，白色/底色通道索引由 S01
                # 写入 ``ctx["material_base_channel_idx"]``；没有这个 fallback 会
                # 退回 0 号通道，与 s03_color_replacement 中已有的修复保持一致。
                if lut_metadata is not None:
                    base_channel_idx = int(getattr(lut_metadata, "base_channel_idx", 0) or 0)
                else:
                    base_channel_idx = int(ctx.get("material_base_channel_idx", 0) or 0)
                try:
                    apply_recipe_overrides_to_analysis(
                        analysis,
                        recipe_overrides=recipe_overrides,
                        region_masks=vector_region_masks,
                        target_layers=requested_color_layers,
                        base_channel_idx=base_channel_idx,
                        img_processor=vec_processor.img_processor,
                        pixels_per_mm=vector_preview_pixels_per_mm,
                        source_grid_shape=edit_projection_source_shape,
                    )

                    # Diagnostic 4/4: shape recipe[0] distribution after
                    # apply_recipe_overrides_to_analysis.
                    _emit_vector_diag(
                        extra={
                            "event": "vector_diag_after_recipe_overrides_recipe0",
                            "stage": "after_apply_recipe_overrides",
                            "analysis_num_layers": int(getattr(analysis, "num_layers", 0) or 0),
                            "base_channel_idx": int(base_channel_idx),
                            "override_region_count": len(vector_region_masks),
                            "override_count": len(recipe_overrides),
                            **_shape_recipe0_histogram(
                                getattr(analysis, "matched_shapes", []) or []
                            ),
                        }
                    )
                except COORDINATOR_HANDLED_ERRORS as exc:
                    log.warning(
                        "Vector recipe override application failed",
                        extra={
                            "event": "vector_recipe_overrides_apply_failed",
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                            "region_count": len(vector_region_masks),
                            "override_count": len(recipe_overrides),
                        },
                    )
            vector_timing["recipe_override_s"] = (
                time.perf_counter() - recipe_override_t0
            )

        # 1b. Build 3D mesh from analysis
        build_mesh_kwargs = {
            "analysis": analysis,
            "thickness_mm": spacer_thick,
            "structure_mode": structure_mode,
        }
        # S08 consumers (notably model-surface embedding) intentionally take
        # only the optical material meshes and discard ``Board``.  Keep the
        # backing distinct until those consumers have extracted their display
        # stack; final 3MF generation still folds it into the selected material.
        vec_processor._merge_backing_into_material = (
            not bool(separate_backing)
            and ctx.get("stop_after_step") != "S08"
        )
        try:
            build_mesh_signature = inspect.signature(vec_processor.build_mesh)
        except (TypeError, ValueError):
            build_mesh_signature = None
        if build_mesh_signature is not None:
            parameters = build_mesh_signature.parameters
            accepts_var_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values())
            if accepts_var_kwargs or "enable_fridge_magnet" in parameters:
                build_mesh_kwargs["enable_fridge_magnet"] = enable_fridge_magnet
            if accepts_var_kwargs or "fridge_magnets" in parameters:
                build_mesh_kwargs["fridge_magnets"] = fridge_magnets
            if accepts_var_kwargs or "backing_color_id" in parameters:
                build_mesh_kwargs["backing_color_id"] = (
                    separate_backing_color_id
                    if separate_backing
                    else backing_channel_idx
                )
            for relief_key in (
                "enable_relief",
                "height_mode",
                "color_height_map",
                "heightmap_path",
                "heightmap_max_height",
            ):
                if accepts_var_kwargs or relief_key in parameters:
                    build_mesh_kwargs[relief_key] = ctx.get(relief_key)

        # Diagnostic 8/8: sample recipes about to enter build_mesh.
        recipe_samples = []
        for sample_idx, sample_shape in enumerate(
            getattr(analysis, "matched_shapes", []) or []
        ):
            if len(recipe_samples) >= 24:
                break
            sample_geom = sample_shape.get("geometry") if isinstance(sample_shape, dict) else None
            if sample_geom is None or getattr(sample_geom, "is_empty", False):
                continue
            try:
                sample_area = float(sample_geom.area)
            except (AttributeError, TypeError, ValueError):
                sample_area = 0.0
            sample_recipe = sample_shape.get("recipe") if isinstance(sample_shape, dict) else None
            recipe_samples.append(
                {
                    "shape_idx": int(sample_idx),
                    "area": round(sample_area, 3),
                    "recipe": [int(v) for v in sample_recipe] if sample_recipe else None,
                }
            )
        _emit_vector_diag(
            extra={
                "event": "vector_diag_build_mesh_input_recipes",
                "stage": "before_build_mesh",
                "sample_count": len(recipe_samples),
                "recipe_sample_first24": recipe_samples,
            },
        )
        _emit_vector_diag(
            extra={
                "event": "vector_diag_stage_b_before_build_mesh_per_layer_channel",
                "stage": "before_build_mesh",
                "shape_histogram": _shape_per_layer_channel_histogram(
                    getattr(analysis, "matched_shapes", []) or []
                ),
            },
        )

        build_mesh_t0 = time.perf_counter()
        scene = vec_processor.build_mesh(**build_mesh_kwargs)
        del build_mesh_kwargs
        build_mesh_s = time.perf_counter() - build_mesh_t0
        vector_timing["mesh_total_s"] = time.perf_counter() - mesh_t0
        if isinstance(getattr(vec_processor, "last_stage_timings", None), dict):
            vector_timing.update(vec_processor.last_stage_timings)
        vector_timing["build_mesh_s"] = build_mesh_s

        _update_bambu_base_layer_ctx_for_vector(
            ctx,
            color_mode=vec_processor.color_mode,
            structure_mode=structure_mode,
            num_layers=analysis.num_layers,
            thickness_mm=spacer_thick,
            layer_height_mm=_resolve_vector_layer_height_mm(ctx),
        )

        if len(scene.geometry) == 0:
            ctx["error"] = "[ERROR] Vector mesh generation failed: no valid geometry generated"
            log.error(
                "Vector branch failed",
                extra={
                    "event": "vector_branch_failed",
                    "error_type": "ValueError",
                    "error_message": ctx["error"],
                    "stage": "build_mesh",
                },
            )
            return ctx

        # 1.5a Use color config from analysis (already resolved)
        vec_color_mode = vec_processor.color_mode
        vec_preview_colors = dict(analysis.preview_colors)
        if coating_material := ctx.get("resolved_coating_material"):
            vec_preview_colors[coating_material.name] = [*coating_material.rgb, 255]
        vec_slot_list = analysis.slot_names
        vector_parse_warnings = list(
            getattr(vec_processor, "parse_warnings", None) or []
        )

        for _mid, _rgba in list(vec_preview_colors.items()):
            if isinstance(_mid, int) and _mid < len(vec_slot_list):
                vec_preview_colors[vec_slot_list[_mid]] = _rgba

        if ctx.get("stop_after_step") == "S08":
            ctx["scene"] = scene
            ctx["valid_slot_names"] = [
                str(name)
                for name in vec_slot_list
                if scene.geometry.get(str(name)) is not None
            ]
            ctx["preview_colors"] = vec_preview_colors
            ctx["vector_analysis"] = analysis
            ctx["_pipeline_stopped_after"] = "S08"
            ctx["vector_timing"] = dict(vector_timing)
            return ctx

        # 1.5b separate_backing handling
        separate_backing = ctx.get("separate_backing", False)
        board_geom = scene.geometry.get("Board")
        # Resolve the target backing slot from backing_color_id, falling back
        # to slot 0 when the index is out of range. This keeps the preview
        # colour, exported material id, and merged geometry consistent with
        # the user-selected backing material (耗材档案模式的底板选择).
        backing_slot_index = 0
        effective_backing_color_id = (
            separate_backing_color_id if separate_backing else backing_color_id
        )
        if vec_slot_list:
            try:
                candidate_backing_idx = int(effective_backing_color_id)
            except (TypeError, ValueError):
                candidate_backing_idx = 0
            if 0 <= candidate_backing_idx < len(vec_slot_list):
                backing_slot_index = candidate_backing_idx
        target_slot = vec_slot_list[backing_slot_index] if vec_slot_list else None
        if board_geom is not None and not separate_backing:
            target_geom = scene.geometry.get(target_slot) if target_slot else None
            if target_geom is not None:
                merged = _concatenate_meshes_fast(
                    [target_geom, board_geom],
                )
                target_color = vec_preview_colors.get(target_slot)
                if target_color is None:
                    existing_colors = np.asarray(
                        target_geom.visual.face_colors,
                    )
                    if existing_colors.ndim == 2 and len(existing_colors):
                        target_color = existing_colors[0]
                merged.visual.face_colors = _coerce_preview_rgba(target_color)
                merged.metadata["name"] = target_slot
                scene.geometry[target_slot] = merged
                del scene.geometry["Board"]
                # The scene now owns only the bounded concatenation result;
                # release both original mesh arrays before outline/export.
                del target_geom, board_geom, merged
                log.debug(
                    "Vector board merged into backing material slot",
                    extra={
                        "event": "vector_board_merged",
                        "slot_name": str(target_slot),
                        "backing_slot_index": backing_slot_index,
                        "separate_backing": False,
                    },
                )
            else:
                log.debug(
                    "Vector board kept because backing material slot was not found",
                    extra={
                        "event": "vector_board_kept",
                        "backing_slot_index": backing_slot_index,
                        "separate_backing": False,
                    },
                )
        elif board_geom is not None and separate_backing:
            board_geom.metadata["lumina_print_role"] = "backing"
            vec_preview_colors["Board"] = vec_preview_colors.get(
                separate_backing_color_id, [255, 255, 255, 255]
            )
            if target_slot:
                board_geom.metadata["bambu_material_name"] = target_slot
            log.debug(
                "Vector board kept as separate backing",
                extra={
                    "event": "vector_board_separate",
                    "backing_slot_index": separate_backing_color_id,
                    "material_name": str(target_slot or ""),
                    "separate_backing": True,
                },
            )

        _inject_vector_keychain_loop(
            ctx,
            scene,
            vec_preview_colors,
            list(vec_slot_list),
        )

        # 1.6 Inject vector Outline mesh.
        # Use the shared structure plan, never the post-match color partition.
        if bool(ctx.get("enable_outline", False)):
            try:
                outline_width_mm = float(ctx.get("outline_width", 2.0) or 2.0)
            except (TypeError, ValueError):
                outline_width_mm = 2.0
            outline_color, outline_material_name = (
                _resolve_vector_outline_base_aux_style(
                    ctx, vec_preview_colors, list(vec_slot_list)
                )
            )
            log.info(
                "Vector outline generation started",
                extra={
                    "event": "vector_outline_init",
                    "outline_width_mm": float(outline_width_mm),
                    "shape_count": len(getattr(analysis, "matched_shapes", []) or []),
                    "material_name": str(outline_material_name or ""),
                    "color_mode": str(vec_color_mode),
                },
            )
            outline_mesh = _generate_vector_outline_mesh(
                analysis=analysis,
                outline_width_mm=outline_width_mm,
                base_aux_color=outline_color,
                base_aux_material_name=outline_material_name,
                ctx=ctx,
                export_color_mode=vec_processor.color_mode,
            )
            if outline_mesh is not None:
                outline_name = "Outline"
                if outline_name in scene.geometry:
                    # Defensive: never silently overwrite an existing
                    # ``Outline`` geometry (e.g. if a future code path also
                    # produced one). Drop the previous entry first.
                    # 防御：避免静默覆盖既有 Outline 节点。
                    del scene.geometry[outline_name]
                scene.add_geometry(
                    outline_mesh,
                    node_name=outline_name,
                    geom_name=outline_name,
                )
                vec_preview_colors[outline_name] = outline_color
                # NOTE: do NOT append "Outline" to ``vec_slot_list``.
                # ``vec_slot_list`` is forwarded as ``project_slot_names`` to
                # ``export_scene_with_bambu_metadata``, which sizes the
                # project-level ``filament_*`` arrays from its length. Adding
                # ``Outline`` here would inflate an 8-color vector export
                # into a 9-filament 3MF, breaking material identity.
                # The raster outline path mirrors this exact split: outline
                # lives in ``valid_slot_names`` (so the writer exports the
                # object) but never in ``slot_names`` (the project palette).
                # 不要把 "Outline" 加进 ``vec_slot_list``：它会作为
                # ``project_slot_names`` 传给 writer，writer 据此 resize 项目级
                # ``filament_*`` 数组，导致 8 色 vector 导出变成 9-filament 3MF。
                # raster outline 也是同样切分：``valid_slot_names`` 含 Outline
                # 用于对象导出，``slot_names``（项目调色板）不含 Outline。
                log.info(
                    "Vector outline generation completed",
                    extra={
                        "event": "vector_outline_done",
                        "outline_width_mm": float(outline_width_mm),
                        "vertex_count": int(len(outline_mesh.vertices)),
                        "face_count": int(len(outline_mesh.faces)),
                        "material_name": str(outline_material_name or ""),
                    },
                )
            else:
                # Helper already emitted WARNING with the unsupported_reason;
                # force ctx flag to false so downstream stages cannot pick up
                # a stale "outline requested" signal after the rejection.
                # helper 已发 WARNING，这里把 enable_outline 规整成 False
                # 防止下游误用。
                ctx["enable_outline"] = False

        need_2d_preview = bool(ctx.get("need_2d_preview", True))
        skip_heavy_preview = (
            os.getenv("LUMINA_VECTOR_SKIP_2D_PREVIEW", "0") == "1"
        )
        if skip_heavy_preview or not need_2d_preview:
            # Generate no longer builds a print-scene GLB. Release the parse
            # graph as soon as neither caller nor the 2D preview needs it.
            # generate 不再构建打印 scene GLB；不需要 2D 预览时立即释放分析图。
            analysis = None
        vec_processor = None

        # 2. Export 3MF
        _report_progress(ctx, 0.72, "\u5bfc\u51fa 3MF \u4e2d... | Exporting 3MF...")
        base_name = os.path.splitext(os.path.basename(image_path))[0]
        out_path = os.path.join(MODELS_DIR, generate_model_filename(base_name, modeling_mode, color_mode))

        vec_slot_names = []
        for geom_name, geom in scene.geometry.items():
            vertices = getattr(geom, "vertices", None)
            faces = getattr(geom, "faces", None)
            v_count = len(vertices) if vertices is not None else 0
            f_count = len(faces) if faces is not None else 0
            if v_count == 0 or f_count == 0:
                log.debug(
                    "Skipping empty vector geometry",
                    extra={
                        "event": "vector_geometry_skipped",
                        "geometry_name": str(geom_name),
                        "vertex_count": int(v_count),
                        "face_count": int(f_count),
                    },
                )
                continue
            vec_slot_names.append(geom_name)

        if not vec_slot_names:
            ctx["error"] = "[ERROR] Vector export aborted: all generated geometries are empty"
            log.error(
                "Vector branch failed",
                extra={
                    "event": "vector_branch_failed",
                    "error_type": "ValueError",
                    "error_message": ctx["error"],
                    "stage": "export_3mf",
                    "geometry_count": len(scene.geometry),
                },
            )
            return ctx

        _lw = _resolve_vector_line_width_mm(ctx.get("nozzle_size", "0.4"))
        layer_height_setting = f"{_resolve_vector_layer_height_mm(ctx):g}"
        vec_print_settings = {
            "layer_height": layer_height_setting,
            "initial_layer_height": layer_height_setting,
            "line_width": _lw,
            "initial_layer_line_width": _lw,
        }

        # ------------------------------------------------------------------
        # Vector cover thumbnail: rasterize the source SVG itself and
        # PNG-encode it in-memory. File managers and slicers should show
        # the original artwork appearance, not the material-layer preview.
        # The encoded PNG still avoids forwarding the raw .svg path because
        # Pillow cannot decode SVG in CoverThumbnailBuilder.
        # 矢量分支封面：直接光栅化源 SVG 并写成内存 PNG。文件管理器和切片
        # 软件里的封面应展示原图外观，而不是匹配后的耗材分层预览。仍然不把
        # raw .svg 传给 CoverThumbnailBuilder，因为 Pillow 不能解码 SVG。
        if not ctx.get("svg_raster_preview_bytes"):
            cover_render_t0 = time.perf_counter()
            try:
                cover_rgba = rasterize_svg(
                    image_path,
                    target_width_mm,
                    pixels_per_mm=2.0,
                    crop_to_content=False,
                    _min_quality_px=1,
                    _max_longest_px=512,
                    _cache_result=False,
                )
                from io import BytesIO as _CoverBytesIO
                from PIL import Image as _CoverImage

                cover_pil = _CoverImage.fromarray(cover_rgba, mode="RGBA")
                cover_buffer = _CoverBytesIO()
                cover_pil.save(cover_buffer, format="PNG", optimize=False)
                ctx["svg_raster_preview_bytes"] = cover_buffer.getvalue()
                log.debug(
                    "Vector cover thumbnail rendered from source SVG",
                    extra={
                        "event": "vector_cover_render_done",
                        "duration_ms": round(
                            (time.perf_counter() - cover_render_t0) * 1000, 3
                        ),
                        "bytes": len(ctx["svg_raster_preview_bytes"]),
                        "rgba_shape": [int(s) for s in cover_rgba.shape],
                    },
                )
                del cover_buffer, cover_pil, cover_rgba
            except (*COORDINATOR_HANDLED_ERRORS, ImportError) as cover_exc:
                log.warning(
                    "Vector cover thumbnail render failed; will fall back to "
                    "cover_source_path or image_path",
                    extra={
                        "event": "vector_cover_render_failed",
                        "error_type": type(cover_exc).__name__,
                        "error_message": str(cover_exc),
                    },
                )

        export_t0 = time.perf_counter()
        # Cover thumbnail source resolution priority:
        # 1. ``ctx['svg_raster_preview_bytes']`` (rasterized SVG preview bytes
        #    produced just above; primary path for SVG inputs);
        # 2. ``ctx['cover_source_path']`` (explicit override mirrored from
        #    convert_image_to_3d / generate_final_model);
        # 3. ``ctx['image_path']`` (the original SVG path; only useful for
        #    non-SVG callers since PIL cannot decode SVG).
        # Each entry is checked separately so a falsy intermediate (e.g. an
        # empty bytes buffer) does not poison the fallback chain.
        # 封面图源按优先级选择，缺省回退到 image_path 保持安全。
        vector_cover_source = (
            ctx.get("svg_raster_preview_bytes")
            or ctx.get("cover_source_path")
            or ctx.get("image_path")
        )
        exported_path = export_scene_with_bambu_metadata(
            scene=scene,
            output_path=out_path,
            slot_names=vec_slot_names,
            preview_colors=vec_preview_colors,
            settings=vec_print_settings,
            color_mode=vec_color_mode,
            printer_id=ctx.get("printer_id", "bambu-h2d"),
            slicer=ctx.get("slicer", "BambuStudio"),
            nozzle_size=ctx.get("nozzle_size", "0.4"),
            project_slot_names=vec_slot_list,
            material_types=ctx.get("material_types"),
            backing_output=ctx.get("backing_output", "same_project"),
            external_spool_material=ctx.get("external_spool_material"),
            native_filament_profiles=ctx.get("native_filament_profiles"),
            enable_base_layer_height_modifier=(
                bool(ctx.get("enable_base_layer_height_modifier", True))
                and not bool(ctx.get("enable_relief", False))
            ),
            enable_wipe_tower_auto_placement=bool(
                ctx.get("enable_wipe_tower_auto_placement", True)
            ),
            enable_relief=bool(ctx.get("enable_relief", False)),
            base_height_mm=float(ctx.get("bambu_base_height_mm", 0.0)),
            color_height_mm=float(ctx.get("bambu_color_height_mm", 0.0)),
            face_orientation=str(ctx.get("bambu_face_orientation", "down")),
            backing_infill_density_percent=int(
                ctx.get("backing_infill_density_percent", 100)
            ),
            cover_source=vector_cover_source,
            device_profile_id=ctx.get("device_profile_id") or None,
            custom_3mf_template_id=ctx.get("custom_3mf_template_id") or None,
            build_plate_id=ctx.get("build_plate_id") or None,
            preserve_template_filament_slots=(
                False
                if str(ctx.get("material_source") or "lut") == "material_archive"
                else None
            ),
        )
        if ctx.get("backing_output") == "separate_project":
            out_path = exported_path
        vector_timing["export_3mf_s"] = time.perf_counter() - export_t0
        log.info(
            "Vector 3MF exported with Bambu metadata",
            extra={
                "event": "vector_3mf_exported",
                "path": str(out_path),
                "slot_count": len(vec_slot_names),
                "geometry_count": len(scene.geometry),
                "duration_ms": round(vector_timing["export_3mf_s"] * 1000, 3),
            },
        )

        # Keep placement translations out of serialized mesh vertices.  The
        # 3MF writer already centres the unmodified local mesh with the
        # standard build-item transform.  Centre the retained scene only after
        # the package is complete so the GLB preview keeps its historical bed
        # coordinates without changing float32 topology in the 3MF.
        if bool(ctx.get("center_on_bed", True)):
            s09_export_3mf._center_scene_on_printer_bed(
                scene,
                ctx.get("printer_id", "bambu-h2d"),
            )

        # 3. Reuse an already validated lightweight GLB when available.
        # Generate must never turn the exact print scene into a browser asset.
        _report_progress(ctx, 0.82, "\u5b8c\u6210\u751f\u6210\u4e2d... | Finalizing generation...")
        glb_path = None
        glb_t0 = time.perf_counter()
        reusable_glb_path = ctx.get("preview_glb_path")
        if (
            isinstance(reusable_glb_path, str)
            and os.path.isfile(reusable_glb_path)
        ):
            glb_path = reusable_glb_path
            log.debug(
                "Vector preview GLB reused",
                extra={
                    "event": "vector_glb_reused",
                    "path": str(glb_path),
                },
            )
        vector_timing["export_glb_s"] = time.perf_counter() - glb_t0

        # 4. 2D preview from analyzed geometry (same data as 3MF)
        _report_progress(ctx, 0.90, "\u751f\u6210 2D \u9884\u89c8\u4e2d... | Generating 2D preview...")
        preview_img = None
        preview_t0 = time.perf_counter()
        if skip_heavy_preview or not need_2d_preview:
            reason = "env flag" if skip_heavy_preview else "caller does not need it"
            log.debug(
                "Skipping SVG 2D preview",
                extra={
                    "event": "vector_2d_preview_skipped",
                    "reason": reason,
                },
            )
        else:
            try:
                preview_img = VectorProcessor.render_preview(analysis, pixels_per_mm=10.0)
                log.debug(
                    "Generated 2D vector preview from analyzed geometry",
                    extra={"event": "vector_2d_preview_done"},
                )
            except COORDINATOR_HANDLED_ERRORS as e:
                log.warning(
                    "Failed to render vector preview",
                    extra={
                        "event": "vector_2d_preview_failed",
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                    },
                )
        vector_timing["preview_2d_s"] = time.perf_counter() - preview_t0

        # 5. Stats & timing
        Stats.increment("conversions")
        vector_timing["vector_branch_total_s"] = time.perf_counter() - vector_total_t0
        ctx["vector_timing"] = dict(vector_timing)
        if bool(ctx.get("retain_scene_for_profile", False)):
            ctx["scene"] = scene
        _log_vector_timings(vector_timing)

        msg = "Vector conversion complete! Objects merged by material."
        if vector_parse_warnings:
            msg += " \u26a0 " + "; ".join(vector_parse_warnings)
        ctx["result_tuple"] = (out_path, glb_path, preview_img, msg, None)
        log.info(
            "Vector branch completed",
            extra={
                "event": "vector_branch_done",
                "duration_ms": round(vector_timing["vector_branch_total_s"] * 1000, 3),
                "path": str(out_path),
                "glb_path": str(glb_path) if glb_path else None,
                "slot_count": len(vec_slot_names),
                "geometry_count": len(scene.geometry),
                "preview_2d_generated": preview_img is not None,
                "parse_warning_count": len(vector_parse_warnings),
            },
        )
        return ctx

    except CachedPreviewAnalysisError:
        raise

    except ModuleNotFoundError as e:
        error_msg = f"Vector processing failed: {e}"
        log.exception(
            "Vector branch failed",
            extra={
                "event": "vector_branch_failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
                "dependency": getattr(e, "name", None),
            },
        )
        ctx["error"] = error_msg
        return ctx

    except COORDINATOR_HANDLED_ERRORS as e:
        error_msg = (
            f"Vector processing failed: {e}\n\n"
            "Suggestions:\n"
            "- Ensure SVG has filled paths (not just strokes)\n"
            "- Try opening in Inkscape and re-saving as 'Plain SVG'\n"
            "- Convert text to paths (Path -> Object to Path)\n"
            "- Or switch to 'High-Fidelity' mode for rasterization"
        )
        log.exception(
            "Vector branch failed",
            extra={
                "event": "vector_branch_failed",
                "error_type": type(e).__name__,
                "error_message": str(e),
                "stage": "vector_processing",
            },
        )
        ctx["error"] = error_msg
        return ctx


def _structured_timing_payload(timings: dict) -> dict[str, float | str | bool]:
    """Keep timing diagnostics JSON-safe without forcing labels to floats."""

    payload: dict[str, float | str | bool] = {}
    for key, value in timings.items():
        if isinstance(value, bool):
            payload[str(key)] = value
        elif isinstance(value, str):
            payload[str(key)] = value[:64]
        else:
            try:
                payload[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
    return payload


def _log_vector_timings(timings: dict) -> None:
    """Log vector branch timing breakdown.
    \u8f93\u51fa\u77e2\u91cf\u5206\u652f\u8ba1\u65f6\u660e\u7ec6\u3002

    Args:
        timings: \u8ba1\u65f6\u5b57\u5178
    """
    if not timings:
        return
    timing_payload = _structured_timing_payload(timings)
    log.debug(
        "Vector timings (s): "
        f"parse={timings.get('parse_s', 0.0):.3f}, "
        f"clip={timings.get('occlusion_s', 0.0):.3f}, "
        f"match={timings.get('color_match_s', 0.0):.3f}, "
        f"matched_rgb_override={timings.get('matched_rgb_override_s', 0.0):.3f}, "
        f"recipe_override={timings.get('recipe_override_s', 0.0):.3f}, "
        f"build_mesh={timings.get('build_mesh_s', 0.0):.3f}, "
        f"extrude_bottom={timings.get('extrude_bottom_s', 0.0):.3f}, "
        f"backing={timings.get('backing_s', 0.0):.3f}, "
        f"extrude_top={timings.get('extrude_top_s', 0.0):.3f}, "
        f"assemble={timings.get('assemble_s', 0.0):.3f}, "
        f"mesh_total={timings.get('mesh_total_s', 0.0):.3f}, "
        f"export_3mf={timings.get('export_3mf_s', 0.0):.3f}, "
        f"export_glb={timings.get('export_glb_s', 0.0):.3f}, "
        f"preview_2d={timings.get('preview_2d_s', 0.0):.3f}, "
        f"total={timings.get('vector_branch_total_s', 0.0):.3f}",
        extra={
            "event": "vector_timings",
            "timings": timing_payload,
        },
    )
    log.info(
        "Vector generate timing breakdown",
        extra={
            "event": "vector_generate_timings",
            "duration_ms": round(float(timings.get("vector_branch_total_s", 0.0)) * 1000, 3),
            "timings": timing_payload,
        },
    )
