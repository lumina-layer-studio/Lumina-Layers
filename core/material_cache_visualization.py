"""Build LUT-details-shaped visualization payloads from a solver cache.
基于求解器穷举缓存生成与 LUT 详情同构的可视化载荷。

The exhaustive material-solver cache (:class:`core.material_cache.
MaterialSolverCache`) stores, per occupied Lab bucket, the best recipe and
its predicted ``achieved_srgb`` / ``achieved_lab``. That is exactly the
shape :mod:`core.lut_details.service` needs to build the four scatter charts
(Lab a*/b* projection, RGB isometric projection, Hue × Lightness, Hue ×
Saturation) shown by ``LutDetailsPanel``. This module reuses those visual
primitives so the UI for "view the cache's color distribution" can render
verbatim.

穷举缓存里每个被占用的 Lab 桶都存了最优配方与对应的 ``achieved_srgb``/
``achieved_lab``，这正是 :mod:`core.lut_details.service` 用来生成四张
散点图（Lab a*/b*、RGB 等距投影、色相×亮度、色相×饱和度）的输入形状。
本模块把缓存数据按相同形式组织，让前端能直接复用 LUT 详情的可视化组件。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from core.lut_details.service import (
    AxisRange,
    LutCoverageStats,
    LutPlotPoint,
    LutPlotPoint3D,
)
from core.material_cache import MaterialSolverCache
from core.material_candidate_cache import MaterialCandidateRuntime


@dataclass(frozen=True)
class MaterialSolverCacheDetails:
    """Aggregated visualization payload for one solver cache.
    单份求解器缓存的聚合可视化载荷。

    Mirrors the subset of :class:`core.lut_details.service.LutDetails` fields
    that the four scatter charts consume; metadata fields irrelevant to the
    cache (manufacturer / supported_modes / ...) are intentionally omitted.
    仅镜像 ``LutDetails`` 中四张散点图所需的字段；与缓存无关的元数据字段（厂商、
    支持模式等）刻意省略。
    """

    palette_hash: str
    layer_count: int
    layer_height_mm: float
    substrate: str
    grid_resolution: int
    valid_cell_count: int
    total_cell_count: int
    coverage_stats: LutCoverageStats
    lab_points: tuple[LutPlotPoint, ...]
    lab_points_3d: tuple[LutPlotPoint3D, ...]
    lab_hull: tuple[tuple[float, float], ...]
    rgb_points: tuple[LutPlotPoint, ...]


@dataclass(frozen=True)
class MaterialSolverRuntimeDetails:
    """Aggregated visualization payload for one hybrid candidate runtime.
    单份 hybrid candidate runtime 的聚合可视化载荷。

    The chart fields mirror :class:`MaterialSolverCacheDetails`; candidate
    metadata is kept separately so API/UI callers can distinguish bounded
    runtime coverage from exhaustive Lab-grid cache coverage.
    图表字段与 :class:`MaterialSolverCacheDetails` 同构；候选元数据单独保留，
    便于 API/UI 区分有界 runtime 覆盖与穷举 Lab-grid 缓存覆盖。
    """

    palette_hash: str
    layer_count: int
    layer_height_mm: float
    substrate: str
    grid_resolution: int
    valid_cell_count: int
    total_cell_count: int
    candidate_budget: int
    candidate_count: int
    coverage_stats: LutCoverageStats
    lab_points: tuple[LutPlotPoint, ...]
    lab_points_3d: tuple[LutPlotPoint3D, ...]
    lab_hull: tuple[tuple[float, float], ...]
    rgb_points: tuple[LutPlotPoint, ...]


@dataclass(frozen=True)
class _MaterialDetailsArrayView:
    """Minimal array view consumed by :func:`build_material_cache_details`."""

    achieved_srgb: np.ndarray
    achieved_lab: np.ndarray
    metadata: dict[str, Any]


def _axis_range(values: np.ndarray) -> AxisRange:
    if values.size == 0:
        return AxisRange(min=0.0, max=0.0)
    return AxisRange(
        min=round(float(np.min(values)), 6),
        max=round(float(np.max(values)), 6),
    )


def _project_rgb_points(rgb: np.ndarray) -> np.ndarray:
    """Isometric 2-D projection of RGB cubes used by the RGB scatter chart.
    RGB 等距投影，与 LUT 详情面板使用的投影方式保持一致。
    """
    if rgb.size == 0:
        return np.zeros((0, 2), dtype=np.float32)
    rgb_norm = rgb.astype(np.float32) / 255.0
    x = (rgb_norm[:, 0] - rgb_norm[:, 2]) * 0.8660254
    y = rgb_norm[:, 1] - (rgb_norm[:, 0] + rgb_norm[:, 2]) * 0.5
    return np.stack([x, y], axis=1)


def _compute_lab_hull(lab: np.ndarray) -> tuple[tuple[float, float], ...]:
    """Convex hull of unique Lab a*/b* points (Andrew's monotone chain).
    Lab a*/b* 唯一点的凸包（Andrew 单调链）。
    """
    if lab.size == 0:
        return ()
    points = np.unique(np.round(lab[:, 1:3].astype(np.float64), 6), axis=0)
    if points.shape[0] < 3:
        return ()
    sorted_points = sorted(
        (float(point[0]), float(point[1])) for point in points.tolist()
    )

    def cross(
        o: tuple[float, float],
        a: tuple[float, float],
        b: tuple[float, float],
    ) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for point in sorted_points:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)

    upper: list[tuple[float, float]] = []
    for point in reversed(sorted_points):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)

    hull = lower[:-1] + upper[:-1]
    return tuple((round(point[0], 6), round(point[1], 6)) for point in hull)


def _rgb_to_hex(color: np.ndarray) -> str:
    return "#{:02X}{:02X}{:02X}".format(int(color[0]), int(color[1]), int(color[2]))


def _coerce_total_cells(metadata: dict[str, Any], grid_resolution: int) -> int:
    """Best-effort total cell count from cache metadata, with a safe fallback.
    从缓存元数据尽力解析总桶数；失败时按 grid^3 兜底。
    """
    raw = metadata.get("total_cell_count")
    if isinstance(raw, (int, float)) and raw > 0:
        return int(raw)
    if grid_resolution > 0:
        return int(grid_resolution) ** 3
    return 0


def _downsample_points(
    rgb: np.ndarray,
    lab: np.ndarray,
    *,
    max_points: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Cap the number of plotted points so the API payload stays bounded.
    限制散点数量，使 API 载荷大小可控。

    Caches at very high grid tiers (1024+) can contain hundreds of thousands
    of unique buckets; sending all of them would balloon JSON size and slow
    the chart rendering. We take a deterministic uniform stride sample.
    超高档（1024+）缓存可能有数十万独立桶；全量传输会让 JSON 体积失控、图表
    渲染变慢。这里取确定性等距下采样。
    """
    count = rgb.shape[0]
    if max_points <= 0 or count <= max_points:
        return rgb, lab
    stride = max(1, count // max_points)
    indices = np.arange(0, count, stride)
    if indices.shape[0] > max_points:
        indices = indices[:max_points]
    return rgb[indices], lab[indices]


def build_material_cache_details(
    cache: MaterialSolverCache | _MaterialDetailsArrayView,
    *,
    palette_hash: str,
    grid_resolution: int,
    max_points: int = 8000,
) -> MaterialSolverCacheDetails:
    """Build a LUT-details-shaped visualization payload from a solver cache.
    从求解器缓存生成与 LUT 详情同构的可视化载荷。

    Args:
        cache: Loaded solver cache. (已加载的求解器缓存)
        palette_hash: Opaque cache record ID (historic API field name).
            (调色板规范指纹，用于可追溯性)
        grid_resolution: Effective Lab grid resolution that produced this
            cache; used both for total-cell-count fallback and the response
            metadata. (该缓存对应的 Lab 网格分辨率)
        max_points: Upper bound on plotted scatter points; values above are
            uniformly downsampled. (散点上限，超出时等距下采样)

    Returns:
        :class:`MaterialSolverCacheDetails` ready for API serialization.
        可直接用于 API 序列化的 :class:`MaterialSolverCacheDetails`。
    """
    rgb_full = np.asarray(cache.achieved_srgb, dtype=np.float32)
    lab_full = np.asarray(cache.achieved_lab, dtype=np.float32)
    if rgb_full.size == 0 or lab_full.size == 0:
        # Empty cache: still emit a well-formed payload so the frontend can
        # show a "no points" empty state instead of crashing.
        # 空缓存：仍返回结构正确的载荷，前端按"无数据"空态渲染。
        rgb_full = np.zeros((0, 3), dtype=np.float32)
        lab_full = np.zeros((0, 3), dtype=np.float32)

    rgb, lab = _downsample_points(rgb_full, lab_full, max_points=max_points)

    coverage_stats = LutCoverageStats(
        entry_count=int(rgb_full.shape[0]),
        plotted_point_count=int(rgb.shape[0]),
        l_range=_axis_range(lab_full[:, 0] if lab_full.size else np.empty(0, dtype=np.float32)),
        a_range=_axis_range(lab_full[:, 1] if lab_full.size else np.empty(0, dtype=np.float32)),
        b_range=_axis_range(lab_full[:, 2] if lab_full.size else np.empty(0, dtype=np.float32)),
        r_range=_axis_range(rgb_full[:, 0] if rgb_full.size else np.empty(0, dtype=np.float32)),
        g_range=_axis_range(rgb_full[:, 1] if rgb_full.size else np.empty(0, dtype=np.float32)),
        b_rgb_range=_axis_range(rgb_full[:, 2] if rgb_full.size else np.empty(0, dtype=np.float32)),
    )

    lab_points = tuple(
        LutPlotPoint(
            x=round(float(lab_value[1]), 6),
            y=round(float(lab_value[2]), 6),
            hex_color=_rgb_to_hex(color),
            rgb=(int(color[0]), int(color[1]), int(color[2])),
            label=f"{index + 1}",
        )
        for index, (lab_value, color) in enumerate(zip(lab, rgb, strict=False))
    )
    lab_points_3d = tuple(
        LutPlotPoint3D(
            l=round(float(lab_value[0]), 6),
            a=round(float(lab_value[1]), 6),
            b=round(float(lab_value[2]), 6),
            hex_color=_rgb_to_hex(color),
            rgb=(int(color[0]), int(color[1]), int(color[2])),
            label=f"{index + 1}",
        )
        for index, (lab_value, color) in enumerate(zip(lab, rgb, strict=False))
    )
    rgb_points = tuple(
        LutPlotPoint(
            x=round(float(projected[0]), 6),
            y=round(float(projected[1]), 6),
            hex_color=_rgb_to_hex(color),
            rgb=(int(color[0]), int(color[1]), int(color[2])),
            label=f"{index + 1}",
        )
        for index, (color, projected) in enumerate(
            zip(rgb, _project_rgb_points(rgb), strict=False)
        )
    )

    metadata = cache.metadata if isinstance(cache.metadata, dict) else {}
    layer_count_raw = metadata.get("layer_count")
    layer_count = (
        int(layer_count_raw) if isinstance(layer_count_raw, (int, float)) else 0
    )
    layer_height_raw = metadata.get("layer_height_mm")
    layer_height_mm = (
        float(layer_height_raw)
        if isinstance(layer_height_raw, (int, float))
        else 0.0
    )
    substrate_raw = metadata.get("substrate")
    substrate = str(substrate_raw) if isinstance(substrate_raw, str) else "white"
    total_cells = _coerce_total_cells(metadata, grid_resolution)

    return MaterialSolverCacheDetails(
        palette_hash=palette_hash,
        layer_count=layer_count,
        layer_height_mm=layer_height_mm,
        substrate=substrate,
        grid_resolution=int(grid_resolution),
        valid_cell_count=int(rgb_full.shape[0]),
        total_cell_count=total_cells,
        coverage_stats=coverage_stats,
        lab_points=lab_points,
        lab_points_3d=lab_points_3d,
        lab_hull=_compute_lab_hull(lab_full),
        rgb_points=rgb_points,
    )


def build_color_set_chart_details(
    srgb: np.ndarray,
    lab: np.ndarray,
    *,
    metadata: dict[str, Any],
    max_points: int = 8000,
    grid_resolution: int = 64,
) -> MaterialSolverCacheDetails:
    """Build the LUT-details chart payload for an arbitrary color set.
    为任意颜色集生成与 LUT 详情同构的图表载荷。

    Args:
        srgb: ``(N, 3)`` uint8 colors. 颜色。
        lab: ``(N, 3)`` Lab values matching ``srgb``. 与 ``srgb`` 对应的 Lab 值。
        metadata: ``layer_count`` / ``layer_height_mm`` / ``substrate`` labels.
            层数、层厚、基底标签。
        max_points: Upper bound on plotted scatter points. 散点上限。
        grid_resolution: Diagnostic grid label. 诊断网格标签。

    Returns:
        MaterialSolverCacheDetails: Chart-ready payload. 可直接渲染的图表载荷。
    """
    return build_material_cache_details(
        _MaterialDetailsArrayView(
            achieved_srgb=np.asarray(srgb),
            achieved_lab=np.asarray(lab),
            metadata=dict(metadata),
        ),
        palette_hash="",
        grid_resolution=int(grid_resolution),
        max_points=int(max_points),
    )


def build_material_runtime_details(
    runtime: MaterialCandidateRuntime,
    *,
    max_points: int = 8000,
) -> MaterialSolverRuntimeDetails:
    """Build a LUT-details-shaped payload from a hybrid candidate runtime.
    从 hybrid candidate runtime 生成与 LUT 详情同构的可视化载荷。

    Args:
        runtime: Loaded or newly built candidate runtime. (候选运行时)
        max_points: Upper bound on plotted scatter points; values above are
            uniformly downsampled. (散点数上限)

    Returns:
        MaterialSolverRuntimeDetails: Chart-ready visualization payload.
            (可直接用于图表渲染的可视化载荷)
    """
    metadata = dict(runtime.metadata if isinstance(runtime.metadata, dict) else {})
    candidate_budget = int(
        metadata.get("candidate_budget", runtime.valid_cell_count)
    )
    candidate_count = int(
        metadata.get("candidate_count", runtime.valid_cell_count)
    )
    metadata["total_cell_count"] = candidate_budget
    grid_resolution = int(
        metadata.get("lab_grid_resolution", metadata.get("grid_resolution", 64))
    )
    details = build_material_cache_details(
        _MaterialDetailsArrayView(
            achieved_srgb=np.asarray(runtime.achieved_srgb),
            achieved_lab=np.asarray(runtime.achieved_lab),
            metadata=metadata,
        ),
        palette_hash=runtime.palette_hash,
        grid_resolution=grid_resolution,
        max_points=max_points,
    )
    return MaterialSolverRuntimeDetails(
        palette_hash=details.palette_hash,
        layer_count=details.layer_count,
        layer_height_mm=details.layer_height_mm,
        substrate=details.substrate,
        grid_resolution=details.grid_resolution,
        valid_cell_count=details.valid_cell_count,
        total_cell_count=details.total_cell_count,
        candidate_budget=candidate_budget,
        candidate_count=candidate_count,
        coverage_stats=details.coverage_stats,
        lab_points=details.lab_points,
        lab_points_3d=details.lab_points_3d,
        lab_hull=details.lab_hull,
        rgb_points=details.rgb_points,
    )
