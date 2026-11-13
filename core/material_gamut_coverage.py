"""sRGB gamut coverage of a material combination.
耗材组合的 sRGB 色域覆盖率。

Coverage is measured as the share of sRGB color cells reached by at least one
printable layer stack. CIELAB space is split into cubes ``cell_size`` ΔE wide;
the reference set is every cube that contains at least one of the 16.7 million
sRGB colors. A combination's colors are the same predicted colors the
converter matches against, so the number answers "which part of sRGB can this
combination print", not a theoretical hull volume that would hide gaps.

覆盖率定义为至少被一种可打印叠层触达的 sRGB 色彩单元占比。CIELAB 空间按
``cell_size`` ΔE 边长切分为立方单元；参考集为包含任一 sRGB 颜色（共 1677 万）
的全部单元。组合颜色与转换器匹配时使用的预测颜色完全一致，因此该数值回答
"此组合能打印 sRGB 的哪一部分"，而非会掩盖空洞的理论凸包体积。

Coverage only measures range. Match accuracy estimates the nearest printable
color error using eight Lab neighbors per evenly spaced sRGB target (greys and
black, dark colors, skin tones, vivid colors), so fine differences inside one
coverage cell and the darkest printable color still count.

覆盖率只衡量范围。匹配精度通过每个均匀分布 sRGB 目标色的八个 Lab 近邻估计
色差，并按颜色组（灰与黑、暗色、肤色、鲜艳色）统计，因此同一覆盖单元
内的细微差异和可打印的最暗颜色也会被计入。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree

from core import material_lut_provider
from core.colorchecker.color_metrics import delta_e_2000
from core.material_cache_overview import (
    describe_dynamic_layer_caches,
    prepare_dynamic_layer_cache,
)
from core.material_cache_visualization import (
    MaterialSolverCacheDetails,
    build_color_set_chart_details,
)
from core.material_candidate_cache import (
    PREVIEW_SAFE_CANDIDATE_BUDGET,
    MaterialCandidateCacheConfig,
    MaterialCandidateRuntime,
    build_material_candidate_runtime,
    load_material_candidate_runtime,
)
from core.material_color_solver import MaterialParams, rgb_to_lab
from core.material_dynamic_solver import (
    DynamicMaterialSolveConfig,
    load_or_build_persistent_dynamic_catalog,
)

SRGB_COVERAGE_CELL_SIZE: float = 5.0
"""Edge length (ΔE76) of one Lab coverage cell. 单个 Lab 覆盖单元边长（ΔE76）。"""

MIN_COVERAGE_CELL_SIZE: float = 0.5
"""Smallest cell edge whose indices still fit the packed key. 键可容纳的最小单元边长。"""

# Lab spans L 0..100 and a/b about -128..128, so at MIN_COVERAGE_CELL_SIZE every
# axis index stays inside [-_CELL_INDEX_OFFSET, _CELL_INDEX_OFFSET) and packed
# keys never collide.
_CELL_INDEX_OFFSET = 1 << 9
_CELL_AXIS_SPAN = 1 << 10

ACCURACY_TARGET_STEP: int = 8
"""sRGB channel step of the accuracy targets (33³ colors). 精度目标色的 sRGB 通道步长（33³ 色）。"""


class ColorGroup:
    """Stable labels for the color groups accuracy is reported for.
    匹配精度所统计颜色组的稳定标签。
    """

    ALL = "all"
    NEUTRAL = "neutral"
    DARK = "dark"
    SKIN = "skin"
    VIVID = "vivid"


COLOR_GROUPS: tuple[str, ...] = (
    ColorGroup.ALL,
    ColorGroup.NEUTRAL,
    ColorGroup.DARK,
    ColorGroup.SKIN,
    ColorGroup.VIVID,
)
"""Report order of the color groups. 颜色组的输出顺序。"""

_LOSS_GROUPS: tuple[str, ...] = tuple(group for group in COLOR_GROUPS if group != ColorGroup.ALL)
_ACCURACY_NEIGHBOR_COUNT = 8


class ColorSourceKind:
    """Stable labels for where the evaluated colors came from.
    被评估颜色来源的稳定标签。
    """

    EXHAUSTIVE_CACHE = "exhaustive_cache"
    SAVED_SMART_CACHE = "saved_smart_cache"
    QUICK_SAMPLE = "quick_sample"
    DYNAMIC_CATALOG = "dynamic_catalog"


@dataclass(frozen=True)
class SrgbCoverage:
    """Reached and total sRGB reference cells.
    已触达与总 sRGB 参考单元数。

    Attributes:
        reached_cell_count: Reference cells holding at least one color.
            至少包含一种颜色的参考单元数。
        reference_cell_count: All cells holding at least one sRGB color.
            包含任一 sRGB 颜色的全部单元数。
    """

    reached_cell_count: int
    reference_cell_count: int

    @property
    def percent(self) -> float:
        """Coverage in percent, rounded to 0.01. 覆盖率百分比（保留两位小数）。"""
        if self.reference_cell_count <= 0:
            return 0.0
        return round(100.0 * self.reached_cell_count / self.reference_cell_count, 2)


@dataclass(frozen=True)
class ColorGroupAccuracy:
    """Average error of the closest printable color for one color group.
    单个颜色组中最接近的可打印颜色的平均色差。

    Attributes:
        group: One of :class:`ColorGroup`. 颜色组。
        target_count: sRGB targets in the group. 该组的 sRGB 目标色数量。
        mean_delta_e: Mean CIEDE2000 to the closest printable color, ``None``
            when there are no printable colors. 到最接近可打印颜色的平均 CIEDE2000；
            没有可打印颜色时为 ``None``。
    """

    group: str
    target_count: int
    mean_delta_e: float | None


@dataclass(frozen=True)
class MatchAccuracy:
    """How closely a color set can reproduce sRGB, per color group.
    颜色集按颜色组复现 sRGB 的接近程度。

    Attributes:
        groups: One entry per :data:`COLOR_GROUPS` item, in that order.
            按 :data:`COLOR_GROUPS` 顺序的逐组结果。
        darkest_lightness: Lowest L* that can be printed. 可打印的最低 L*。
        lightest_lightness: Highest L* that can be printed. 可打印的最高 L*。
    """

    groups: tuple[ColorGroupAccuracy, ...]
    darkest_lightness: float | None
    lightest_lightness: float | None

    def mean_for(self, group: str) -> float | None:
        """Return the mean error of ``group``. 返回 ``group`` 的平均色差。"""
        for entry in self.groups:
            if entry.group == group:
                return entry.mean_delta_e
        raise KeyError(group)


@dataclass(frozen=True)
class GamutColorSource:
    """Describe the candidate colors behind a coverage figure.
    描述覆盖率数值所依据的候选颜色。

    Attributes:
        kind: One of :class:`ColorSourceKind`. 来源类型。
        candidate_budget: Candidate cap per layer count, ``None`` when the
            source is not budget-bound. 每个层数的候选上限；不受预算约束时为 ``None``。
        is_complete: Every possible layer stack was evaluated, so the figure
            is exact rather than a sampled lower bound. 是否评估了全部叠层（精确值
            而非采样下界）。
        was_cached: Loaded from disk instead of computed for this request.
            是否直接从磁盘加载而非本次计算。
    """

    kind: str
    candidate_budget: int | None
    is_complete: bool
    was_cached: bool


@dataclass(frozen=True)
class LayerCapCoverage:
    """Coverage when recipes may use at most ``layer_count`` color layers.
    配方最多使用 ``layer_count`` 层颜色时的覆盖率。
    """

    layer_count: int
    coverage: SrgbCoverage


@dataclass(frozen=True)
class GamutCoverageResult:
    """Coverage, provenance, and chart data for one combination.
    单个组合的覆盖率、来源与图表数据。

    Attributes:
        coverage: Headline sRGB coverage. 主覆盖率。
        accuracy: Per-group match accuracy of the same colors. 同一颜色集的逐组匹配精度。
        color_count: Distinct predicted sRGB colors evaluated. 被评估的不同颜色数。
        source: Where the colors came from. 颜色来源。
        layer_cap_coverage: Dynamic mode only, coverage per maximum layer cap.
            仅动态模式：各层数上限的覆盖率。
        chart_details: LUT-details-shaped chart payload. 与 LUT 详情同构的图表数据。
    """

    coverage: SrgbCoverage
    accuracy: MatchAccuracy
    color_count: int
    source: GamutColorSource
    layer_cap_coverage: tuple[LayerCapCoverage, ...]
    chart_details: MaterialSolverCacheDetails


@dataclass(frozen=True)
class MaterialContribution:
    """What is lost when one material is removed.
    移除单个耗材时的损失。

    Attributes:
        material_index: Index in the caller's palette order. 调用方顺序中的索引。
        coverage_without: Coverage of the palette without this material.
            去掉此耗材后的覆盖率。
        drop_percent: Baseline percent minus ``coverage_without`` percent.
            基线百分比减去去掉后的百分比。
        accuracy_without: Match accuracy without this material.
            去掉此耗材后的匹配精度。
        largest_loss_group: Color group whose mean error rises most, ``None``
            when nothing can be printed without the material.
            平均色差上升最多的颜色组；去掉后无法打印任何颜色时为 ``None``。
        largest_loss_delta_e: That rise in mean CIEDE2000, ``None`` alongside
            ``largest_loss_group``. 该组平均 CIEDE2000 的上升量。
    """

    material_index: int
    coverage_without: SrgbCoverage
    drop_percent: float
    accuracy_without: MatchAccuracy
    largest_loss_group: str | None
    largest_loss_delta_e: float | None


@dataclass(frozen=True)
class GamutContributionResult:
    """Per-material contributions measured with one consistent method.
    以同一方法测得的逐耗材贡献。

    Attributes:
        layer_count: Layer count the comparison ran at. 对比所用层数。
        baseline: Full-palette coverage under the same method. 同方法下的完整组合覆盖率。
        baseline_accuracy: Full-palette match accuracy under the same method.
            同方法下的完整组合匹配精度。
        is_complete: Every comparison evaluated all layer stacks.
            每次对比是否都评估了全部叠层。
        contributions: One entry per material, in palette order. 按调色板顺序的逐耗材结果。
    """

    layer_count: int
    baseline: SrgbCoverage
    baseline_accuracy: MatchAccuracy
    is_complete: bool
    contributions: tuple[MaterialContribution, ...]


def _cell_keys(lab: np.ndarray, cell_size: float) -> np.ndarray:
    indices = np.floor(np.asarray(lab, dtype=np.float64) / cell_size).astype(np.int64)
    indices += _CELL_INDEX_OFFSET
    return (indices[:, 0] * _CELL_AXIS_SPAN + indices[:, 1]) * _CELL_AXIS_SPAN + indices[:, 2]


@lru_cache(maxsize=4)
def srgb_reference_cell_keys(cell_size: float = SRGB_COVERAGE_CELL_SIZE) -> np.ndarray:
    """Return sorted keys of every Lab cell that holds an sRGB color.
    返回包含 sRGB 颜色的全部 Lab 单元键（已排序）。

    All 256³ sRGB colors are converted in 256 slices to bound memory.
    全部 256³ 个 sRGB 颜色分 256 片转换以控制内存。

    Args:
        cell_size: Cell edge length in ΔE76. 单元边长（ΔE76）。

    Returns:
        np.ndarray: Sorted unique ``int64`` cell keys (read-only).
            已排序的唯一 ``int64`` 单元键（只读）。
    """
    if not np.isfinite(cell_size) or cell_size < MIN_COVERAGE_CELL_SIZE:
        raise ValueError(f"cell_size must be finite and at least {MIN_COVERAGE_CELL_SIZE}")
    channel = np.arange(256, dtype=np.uint8)
    green, blue = np.meshgrid(channel, channel, indexing="ij")
    slice_gb = np.stack([green.ravel(), blue.ravel()], axis=1)
    keys: list[np.ndarray] = []
    for red in range(256):
        rgb = np.empty((slice_gb.shape[0], 3), dtype=np.uint8)
        rgb[:, 0] = red
        rgb[:, 1:] = slice_gb
        keys.append(np.unique(_cell_keys(rgb_to_lab(rgb), cell_size)))
    reference = np.unique(np.concatenate(keys))
    reference.setflags(write=False)
    return reference


def measure_srgb_coverage(
    srgb: np.ndarray,
    *,
    cell_size: float = SRGB_COVERAGE_CELL_SIZE,
) -> SrgbCoverage:
    """Measure how many sRGB reference cells the given colors reach.
    统计给定颜色触达的 sRGB 参考单元数。

    Args:
        srgb: ``(N, 3)`` uint8 predicted print colors. 预测打印颜色。
        cell_size: Cell edge length in ΔE76. 单元边长（ΔE76）。

    Returns:
        SrgbCoverage: Reached and total reference cells. 已触达与总参考单元数。
    """
    reference = srgb_reference_cell_keys(cell_size)
    colors = np.asarray(srgb, dtype=np.uint8).reshape(-1, 3)
    if colors.shape[0] == 0:
        return SrgbCoverage(0, int(reference.shape[0]))
    reached = np.intersect1d(
        np.unique(_cell_keys(rgb_to_lab(colors), cell_size)),
        reference,
        assume_unique=True,
    )
    return SrgbCoverage(int(reached.shape[0]), int(reference.shape[0]))


def color_group_masks(lab: np.ndarray) -> dict[str, np.ndarray]:
    """Assign Lab colors to the accuracy color groups (groups may overlap).
    将 Lab 颜色划入各精度颜色组（组之间可重叠）。

    - neutral: greys, black and white, C* < 8. 灰、黑、白。
    - dark: L* < 30. 暗色。
    - skin: L* 35–85, hue 25°–65°, C* 10–40. 肤色。
    - vivid: C* > 60. 鲜艳色。

    Args:
        lab: ``(N, 3)`` CIELAB colors. CIELAB 颜色。

    Returns:
        dict[str, np.ndarray]: Boolean mask per :data:`COLOR_GROUPS` item.
            每个颜色组的布尔掩码。
    """
    values = np.asarray(lab, dtype=np.float64).reshape(-1, 3)
    lightness, a_axis, b_axis = values[:, 0], values[:, 1], values[:, 2]
    chroma = np.hypot(a_axis, b_axis)
    hue = np.degrees(np.arctan2(b_axis, a_axis)) % 360.0
    return {
        ColorGroup.ALL: np.ones(values.shape[0], dtype=bool),
        ColorGroup.NEUTRAL: chroma < 8.0,
        ColorGroup.DARK: lightness < 30.0,
        ColorGroup.SKIN: (
            (lightness > 35.0) & (lightness < 85.0)
            & (hue > 25.0) & (hue < 65.0)
            & (chroma > 10.0) & (chroma < 40.0)
        ),
        ColorGroup.VIVID: chroma > 60.0,
    }


@lru_cache(maxsize=1)
def _accuracy_targets() -> tuple[np.ndarray, dict[str, np.ndarray]]:
    steps = np.unique(np.append(np.arange(0, 256, ACCURACY_TARGET_STEP), 255)).astype(np.uint8)
    grid = np.stack(np.meshgrid(steps, steps, steps, indexing="ij"), axis=-1).reshape(-1, 3)
    lab = rgb_to_lab(grid)
    lab.setflags(write=False)
    return lab, color_group_masks(lab)


def measure_match_accuracy(srgb: np.ndarray) -> MatchAccuracy:
    """Measure how closely the given colors reproduce evenly spaced sRGB targets.
    测量给定颜色复现均匀分布 sRGB 目标色的接近程度。

    Each target is scored with the smallest CIEDE2000 among its nearest
    printable colors in Lab; the mean is reported per color group, together
    with the darkest and lightest printable L*.

    每个目标色取其 Lab 近邻可打印颜色中最小的 CIEDE2000 计分；按颜色组输出
    平均值，并给出可打印的最暗与最亮 L*。

    Args:
        srgb: ``(N, 3)`` uint8 predicted print colors. 预测打印颜色。

    Returns:
        MatchAccuracy: Per-group mean error and the printable L* range.
            逐组平均色差与可打印 L* 范围。
    """
    target_lab, masks = _accuracy_targets()
    colors = _unique_colors(srgb)
    if colors.shape[0] == 0:
        groups = tuple(
            ColorGroupAccuracy(group, int(masks[group].sum()), None) for group in COLOR_GROUPS
        )
        return MatchAccuracy(groups, None, None)
    color_lab = rgb_to_lab(colors)
    neighbor_count = min(_ACCURACY_NEIGHBOR_COUNT, color_lab.shape[0])
    _distance, nearest = cKDTree(color_lab).query(target_lab, k=neighbor_count)
    nearest = np.asarray(nearest).reshape(target_lab.shape[0], neighbor_count)
    delta_e = delta_e_2000(target_lab[:, None, :], color_lab[nearest]).min(axis=1)
    groups = tuple(
        ColorGroupAccuracy(
            group,
            int(masks[group].sum()),
            round(float(delta_e[masks[group]].mean()), 2) if masks[group].any() else None,
        )
        for group in COLOR_GROUPS
    )
    return MatchAccuracy(
        groups,
        round(float(color_lab[:, 0].min()), 1),
        round(float(color_lab[:, 0].max()), 1),
    )


def _largest_loss(
    baseline: MatchAccuracy,
    without: MatchAccuracy,
) -> tuple[str | None, float | None]:
    losses = [
        (round(after - before, 2), group)
        for group in _LOSS_GROUPS
        if (before := baseline.mean_for(group)) is not None
        and (after := without.mean_for(group)) is not None
    ]
    if not losses:
        return None, None
    loss, group = max(losses, key=lambda item: item[0])
    return group, loss


def _stack_space_size(material_count: int, layer_count: int) -> int:
    return int(material_count) ** int(layer_count)


def _runtime_is_complete(runtime: MaterialCandidateRuntime, material_count: int) -> bool:
    layer_count = int(np.asarray(runtime.candidate_recipes).shape[1])
    return runtime.valid_cell_count >= _stack_space_size(material_count, layer_count)


def _quick_sample_runtime(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
) -> MaterialCandidateRuntime:
    return build_material_candidate_runtime(
        materials=materials,
        layer_count=int(layer_count),
        layer_height_mm=float(layer_height_mm),
        substrate=str(substrate),
        config=MaterialCandidateCacheConfig.preview_safe(),
    )


def _load_fixed_layer_colors(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    cache_root: str | Path | None,
) -> tuple[np.ndarray, GamutColorSource]:
    """Resolve colors in the same order fixed-layer conversion does."""
    solver_cache, _grid = material_lut_provider.load_solver_cache(
        materials, layer_count, layer_height_mm, substrate, cache_root=cache_root
    )
    if solver_cache is not None:
        colors = np.concatenate((
            np.asarray(solver_cache.achieved_srgb).reshape(-1, 3),
            np.asarray(solver_cache.uniform_achieved_srgb).reshape(-1, 3),
        ))
        return colors, GamutColorSource(
            ColorSourceKind.EXHAUSTIVE_CACHE, None, solver_cache.is_exact, True
        )
    for budget in material_lut_provider.PERSISTED_RUNTIME_PROBE_BUDGETS:
        runtime = load_material_candidate_runtime(
            materials, layer_count, layer_height_mm, substrate,
            candidate_budget=int(budget), cache_root=cache_root,
        )
        if runtime is not None:
            return np.asarray(runtime.achieved_srgb), GamutColorSource(
                ColorSourceKind.SAVED_SMART_CACHE,
                int(budget),
                _runtime_is_complete(runtime, len(materials)),
                True,
            )
    runtime = _quick_sample_runtime(materials, layer_count, layer_height_mm, substrate)
    return np.asarray(runtime.achieved_srgb), GamutColorSource(
        ColorSourceKind.QUICK_SAMPLE,
        PREVIEW_SAFE_CANDIDATE_BUDGET,
        _runtime_is_complete(runtime, len(materials)),
        False,
    )


def _unique_colors(srgb: np.ndarray) -> np.ndarray:
    colors = np.asarray(srgb, dtype=np.uint8).reshape(-1, 3)
    return np.unique(colors, axis=0) if colors.shape[0] else colors


def _chart_details(
    srgb: np.ndarray,
    *,
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    max_points: int,
) -> MaterialSolverCacheDetails:
    return build_color_set_chart_details(
        srgb,
        rgb_to_lab(srgb) if srgb.shape[0] else np.zeros((0, 3), dtype=np.float32),
        metadata={
            "layer_count": int(layer_count),
            "layer_height_mm": float(layer_height_mm),
            "substrate": str(substrate),
        },
        max_points=max_points,
    )


def compute_fixed_layer_gamut(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    max_points: int = 8000,
    cache_root: str | Path | None = None,
) -> GamutCoverageResult:
    """Coverage of a fixed-layer combination, using the best saved colors.
    固定层数组合的覆盖率，优先使用已保存的最佳颜色集。

    The color source follows fixed-layer conversion: exhaustive cache, then
    the largest saved smart cache, then a quick 1M-candidate sample that is
    not saved.

    颜色来源与固定层数转换一致：穷举缓存 → 最大的已保存智能缓存 → 不落盘的
    1M 候选快速采样。

    Args:
        materials: Palette in user order. 用户顺序耗材。
        layer_count: Color layers per stack. 每个叠层的颜色层数。
        layer_height_mm: Physical layer height. 物理层高。
        substrate: ``white`` or ``black``. 基底。
        max_points: Chart point cap. 图表点数上限。
        cache_root: Optional cache root override. 可选缓存根目录。

    Returns:
        GamutCoverageResult: Coverage, provenance, and chart data.
            覆盖率、来源与图表数据。
    """
    srgb, source = _load_fixed_layer_colors(
        materials, layer_count, layer_height_mm, substrate, cache_root
    )
    colors = _unique_colors(srgb)
    return GamutCoverageResult(
        coverage=measure_srgb_coverage(colors),
        accuracy=measure_match_accuracy(colors),
        color_count=int(colors.shape[0]),
        source=source,
        layer_cap_coverage=(),
        chart_details=_chart_details(
            colors,
            layer_count=layer_count,
            layer_height_mm=layer_height_mm,
            substrate=substrate,
            max_points=max_points,
        ),
    )


def compute_dynamic_layer_gamut(
    materials: list[MaterialParams],
    backing_index: int,
    layer_height_mm: float,
    substrate: str,
    min_layer_count: int,
    max_layer_count: int,
    *,
    max_points: int = 8000,
    cache_root: str | Path | None = None,
) -> GamutCoverageResult:
    """Coverage of a dynamic layer range from the conversion catalog.
    基于转换所用目录计算动态层数范围的覆盖率。

    Uses the exact padded catalog dynamic conversion uses (building and
    saving it when missing), and reports coverage for every layer cap.

    使用动态转换完全相同的补位目录（缺失时构建并保存），并给出每个层数上限
    的覆盖率。

    Args:
        materials: Palette in user order. 用户顺序耗材。
        backing_index: Backing material used for padding. 用于补位的基板耗材。
        layer_height_mm: Physical layer height. 物理层高。
        substrate: ``white`` or ``black``. 基底。
        min_layer_count: Smallest effective layer count. 最小有效层数。
        max_layer_count: Largest effective layer count. 最大有效层数。
        max_points: Chart point cap. 图表点数上限。
        cache_root: Optional cache root override. 可选缓存根目录。

    Returns:
        GamutCoverageResult: Coverage, provenance, per-cap coverage, and charts.
            覆盖率、来源、逐上限覆盖率与图表数据。
    """
    config = DynamicMaterialSolveConfig(int(min_layer_count), int(max_layer_count), 0.0)
    overview = describe_dynamic_layer_caches(
        materials, backing_index, layer_height_mm, substrate,
        config.min_layer_count, config.max_layer_count, cache_root=cache_root,
    )
    if not overview.is_ready:
        # Build expensive per-layer candidates before acquiring the catalog lock.
        # The final merge and conversion then reuse those isolated prepared files.
        prepare_dynamic_layer_cache(
            materials, backing_index, layer_height_mm, substrate,
            config.min_layer_count, config.max_layer_count, cache_root=cache_root,
        )
    loaded = load_or_build_persistent_dynamic_catalog(
        materials,
        int(backing_index),
        float(layer_height_mm),
        str(substrate),
        config,
        cache_root=cache_root,
    )
    catalog = loaded.catalog
    colors = np.asarray(catalog.score_srgb, dtype=np.uint8)
    minimum_counts = np.asarray(catalog.minimum_actual_layer_counts)
    layer_caps = tuple(
        LayerCapCoverage(cap, measure_srgb_coverage(colors[minimum_counts <= cap]))
        for cap in range(config.min_layer_count, config.max_layer_count + 1)
    )
    full_space = sum(
        _stack_space_size(len(materials), layers)
        for layers in range(config.min_layer_count, config.max_layer_count + 1)
    )
    source = GamutColorSource(
        ColorSourceKind.DYNAMIC_CATALOG,
        PREVIEW_SAFE_CANDIDATE_BUDGET,
        loaded.candidate_count_before_dedup >= full_space,
        overview.is_ready and loaded.cache_hit,
    )
    return GamutCoverageResult(
        coverage=layer_caps[-1].coverage,
        accuracy=measure_match_accuracy(colors),
        color_count=int(colors.shape[0]),
        source=source,
        layer_cap_coverage=layer_caps,
        chart_details=_chart_details(
            colors,
            layer_count=config.max_layer_count,
            layer_height_mm=layer_height_mm,
            substrate=substrate,
            max_points=max_points,
        ),
    )


def compute_material_contributions(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
) -> GamutContributionResult:
    """Measure what each material adds by removing it in turn.
    逐个移除耗材，测量每个耗材带来的贡献。

    Every comparison, including the baseline, uses the same quick 1M sample
    so the results are comparable even when the headline figure came from a
    larger saved cache. Small palettes are enumerated completely. Each
    material reports its coverage drop and its per-group accuracy loss; the
    group with the largest rise in mean error is named, so a material that
    adds little range but all of the dark or skin tones still stands out.

    包括基线在内的每次对比都使用同一 1M 快速采样，即使主覆盖率来自更大的
    已保存缓存，结果之间仍可比较。小组合会被完整枚举。每个耗材给出覆盖率降幅
    与逐组精度损失，并标出平均色差上升最多的颜色组，因此范围贡献小、但承担
    暗色或肤色的耗材依然会被突出。

    Args:
        materials: Palette in user order. 用户顺序耗材。
        layer_count: Color layers per stack. 每个叠层的颜色层数。
        layer_height_mm: Physical layer height. 物理层高。
        substrate: ``white`` or ``black``. 基底。

    Returns:
        GamutContributionResult: Baseline and per-material losses.
            基线与逐耗材损失。
    """
    baseline_runtime = _quick_sample_runtime(
        materials, layer_count, layer_height_mm, substrate
    )
    baseline = measure_srgb_coverage(baseline_runtime.achieved_srgb)
    baseline_accuracy = measure_match_accuracy(baseline_runtime.achieved_srgb)
    is_complete = _runtime_is_complete(baseline_runtime, len(materials))

    contributions: list[MaterialContribution] = []
    for index in range(len(materials)):
        remaining = [material for position, material in enumerate(materials) if position != index]
        if remaining:
            runtime = _quick_sample_runtime(remaining, layer_count, layer_height_mm, substrate)
            colors_without = np.asarray(runtime.achieved_srgb)
            is_complete = is_complete and _runtime_is_complete(runtime, len(remaining))
        else:
            colors_without = np.zeros((0, 3), dtype=np.uint8)
        without = measure_srgb_coverage(colors_without)
        accuracy_without = measure_match_accuracy(colors_without)
        loss_group, loss_delta_e = _largest_loss(baseline_accuracy, accuracy_without)
        contributions.append(
            MaterialContribution(
                material_index=index,
                coverage_without=without,
                drop_percent=round(baseline.percent - without.percent, 2),
                accuracy_without=accuracy_without,
                largest_loss_group=loss_group,
                largest_loss_delta_e=loss_delta_e,
            )
        )

    return GamutContributionResult(
        layer_count=int(layer_count),
        baseline=baseline,
        baseline_accuracy=baseline_accuracy,
        is_complete=is_complete,
        contributions=tuple(contributions),
    )
