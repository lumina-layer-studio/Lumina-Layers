"""Exact dynamic-layer material candidate search.

动态层数耗材候选的精确搜索。
"""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np

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

from core.colorchecker.color_metrics import delta_e_2000
from core.material_cache import MaterialSolverCache, canonical_palette_order
from core.material_candidate_cache import (
    PREVIEW_SAFE_CANDIDATE_BUDGET,
    MaterialCandidateRuntime,
)
from core.material_color_solver import (
    MaterialParams,
    forward_batch_model,
    linear_to_srgb_uint8,
    rgb_to_lab,
)
from core.material_lut_provider import load_dynamic_candidate_runtime
from core.task_parallelism import (
    resolve_task_parallelism_plan,
    task_parallelism_worker_scope,
)


MIN_DYNAMIC_LAYER_COUNT = 5
MAX_DYNAMIC_LAYER_COUNT = 10
_NUMPY_CANDIDATE_CHUNK_SIZE = 65_536
_MIN_PARALLEL_SEARCH_COMPARISONS = 10_000


class DynamicMaterialSolverError(RuntimeError):
    """Raised when every exact dynamic search engine fails.

    当所有动态精确搜索引擎均失败时抛出。
    """


class DynamicMaterialCandidateError(RuntimeError):
    """Report a failed dynamic candidate construction stage.

    报告动态候选构建阶段失败。

    Attributes:
        target_srgb: Optional target color associated with the failure. 与失败
            关联的可选目标色。
        layer_count: Effective layer count being processed. 正在处理的有效层数。
        phase: Stable construction phase label. 稳定的候选构建阶段标识。
    """

    def __init__(
        self,
        message: str,
        *,
        layer_count: int,
        phase: str,
        target_srgb: tuple[int, int, int] | None = None,
    ) -> None:
        self.message = str(message)
        self.layer_count = int(layer_count)
        self.phase = str(phase)
        self.target_srgb = (
            tuple(int(value) for value in target_srgb)
            if target_srgb is not None
            else None
        )
        if self.target_srgb is not None and len(self.target_srgb) != 3:
            raise ValueError("target_srgb must contain exactly three channels")
        target_text = (
            f" target_srgb={self.target_srgb}"
            if self.target_srgb is not None
            else ""
        )
        super().__init__(
            f"dynamic material candidate failed: layer_count={self.layer_count} "
            f"phase={self.phase}{target_text}: {self.message}"
        )

    def __reduce__(self) -> tuple:
        return (
            _restore_dynamic_material_candidate_error,
            (self.message, self.layer_count, self.phase, self.target_srgb),
        )


def _restore_dynamic_material_candidate_error(
    message: str,
    layer_count: int,
    phase: str,
    target_srgb: tuple[int, int, int] | None,
) -> DynamicMaterialCandidateError:
    return DynamicMaterialCandidateError(
        message,
        layer_count=layer_count,
        phase=phase,
        target_srgb=target_srgb,
    )


@dataclass(frozen=True)
class DynamicMaterialSolveConfig:
    """Configure exact dynamic material-layer selection.

    配置精确动态耗材层数选择。

    Attributes:
        min_layer_count: Smallest allowed effective layer count. 最小有效层数。
        max_layer_count: Largest allowed effective layer count. 最大有效层数。
        delta_e00_tolerance: Allowed CIEDE2000 loss when selecting a shorter
            recipe. 选择更短配方时允许的 CIEDE2000 损失。
    """

    min_layer_count: int
    max_layer_count: int
    delta_e00_tolerance: float

    def __post_init__(self) -> None:
        minimum = _validate_layer_bound(self.min_layer_count, "min_layer_count")
        maximum = _validate_layer_bound(self.max_layer_count, "max_layer_count")
        if minimum > maximum:
            raise ValueError("min_layer_count must not exceed max_layer_count")
        tolerance = self.delta_e00_tolerance
        if isinstance(tolerance, (bool, np.bool_)) or not isinstance(
            tolerance,
            (int, float, np.integer, np.floating),
        ):
            raise TypeError("delta_e00_tolerance must be a real number")
        normalized_tolerance = float(tolerance)
        if not math.isfinite(normalized_tolerance):
            raise ValueError("delta_e00_tolerance must be finite")
        if not 0.0 <= normalized_tolerance <= 5.0:
            raise ValueError("delta_e00_tolerance must be between 0 and 5")
        object.__setattr__(self, "min_layer_count", minimum)
        object.__setattr__(self, "max_layer_count", maximum)
        object.__setattr__(self, "delta_e00_tolerance", normalized_tolerance)


@dataclass(frozen=True)
class DynamicMaterialLayerOption:
    """Describe the exact match available at one effective-layer cap.

    描述某个有效层数上限对应的精确匹配结果。

    Attributes:
        max_effective_layer_count: Effective-layer cap represented by this
            option. 此选项对应的有效层数上限。
        actual_layer_count: Actual color-recipe length. 实际颜色配方层数。
        matched_srgb: Simulated printed sRGB color. 模拟打印后的 sRGB 颜色。
        actual_recipe_bottom_to_top: Unpadded Bottom-to-Top recipe. 未补位的
            自底向上实际配方。
        print_recipe_bottom_to_top: Maximum-width Bottom-to-Top print recipe.
            最大宽度的自底向上打印配方。
        delta_e00: Exact CIEDE2000 distance to the target. 与目标色的精确
            CIEDE2000 色差。
    """

    max_effective_layer_count: int
    actual_layer_count: int
    matched_srgb: tuple[int, int, int]
    actual_recipe_bottom_to_top: tuple[int, ...]
    print_recipe_bottom_to_top: tuple[int, ...]
    delta_e00: float


@dataclass(frozen=True)
class DynamicMaterialColorMatch:
    """Collect dynamic-layer choices for one target color.

    汇总单个目标颜色的动态层数选择。

    Attributes:
        target_srgb: Requested target sRGB color. 请求的目标 sRGB 颜色。
        selected: Earliest option within tolerance. 容差内最短的选项。
        best_range: Exact best option across the full range. 整个范围内的精确
            最佳选项。
        fixed_max_delta_e00: Exact fixed-maximum-layer baseline. 固定最大层数的
            精确基线色差。
        delta_e00_sacrifice: Selected distance minus range-best distance.
            所选方案相对范围最佳方案的色差损失。
        layer_cap_options: Exact cumulative option for every allowed cap.
            每个允许层数上限的精确累计选项。
    """

    target_srgb: tuple[int, int, int]
    selected: DynamicMaterialLayerOption
    best_range: DynamicMaterialLayerOption
    fixed_max_delta_e00: float
    delta_e00_sacrifice: float
    layer_cap_options: tuple[DynamicMaterialLayerOption, ...]


@dataclass(frozen=True)
class DynamicMaterialSolveResult:
    """Return all exact dynamic material matches and diagnostics.

    返回全部精确动态耗材匹配结果及诊断信息。

    Attributes:
        matches: One match per input target. 每个输入目标对应一个匹配结果。
        engine: Exact search engine used. 使用的精确搜索引擎。
        candidate_count_before_dedup: Candidate rows before RGB deduplication.
            RGB 去重前的候选行数。
        candidate_count_after_dedup: Candidate rows after RGB deduplication.
            RGB 去重后的候选行数。
        layer_counts: Inclusive effective-layer range. 有效层数范围（含边界）。
    """

    matches: tuple[DynamicMaterialColorMatch, ...]
    engine: str
    candidate_count_before_dedup: int
    candidate_count_after_dedup: int
    layer_counts: tuple[int, ...]


@dataclass(frozen=True)
class MaterialLayerBenefitPoint:
    """Describe weighted color-error benefit at one layer cap.

    描述某一层数上限对应的加权色差收益。

    Attributes:
        max_effective_layer_count: Effective-layer cap. 有效层数上限。
        weighted_mean_delta_e00: Pixel-weighted mean exact CIEDE2000.
            按像素加权的精确 CIEDE2000 均值。
        marginal_delta_e00_reduction: Reduction from the preceding cap, or
            zero for the first point. 相对前一层数上限的色差降低量；首点为零。
    """

    max_effective_layer_count: int
    weighted_mean_delta_e00: float
    marginal_delta_e00_reduction: float


@dataclass(frozen=True)
class DynamicCandidateCatalog:
    """Lossless catalog of scored material candidates.

    已评分耗材候选的无损目录。

    Attributes:
        score_srgb: Unique scored sRGB rows as ``uint8`` with shape ``(U, 3)``.
            唯一的已评分 sRGB 行，类型为 ``uint8``，形状为 ``(U, 3)``。
        score_lab: Repository-standard Lab rows as ``float64`` with shape
            ``(U, 3)``. 使用项目标准转换得到的 ``float64`` Lab 行，形状为
            ``(U, 3)``。
        print_recipes: Fixed-width Bottom-to-Top material recipes with shape
            ``(U, max_layer_count)``. 固定宽度的自底向上材料配方，形状为
            ``(U, max_layer_count)``。
        minimum_actual_layer_counts: Shortest actual recipe length retained for
            each scored color. 每个评分颜色保留的最短实际配方层数。
        max_layer_reachable: Whether any source row for a scored color was built
            at the catalog maximum. 对应评分颜色是否存在达到目录最大层数的源行。
        source_indices: Retained source-row indices in stable catalog order.
            按稳定目录顺序保留的源行索引。
    """

    score_srgb: np.ndarray
    score_lab: np.ndarray
    print_recipes: np.ndarray
    minimum_actual_layer_counts: np.ndarray
    max_layer_reachable: np.ndarray
    source_indices: np.ndarray

    def __post_init__(self) -> None:
        arrays = (
            ("score_srgb", self.score_srgb, np.uint8),
            ("score_lab", self.score_lab, np.float64),
            ("print_recipes", self.print_recipes, np.int32),
            (
                "minimum_actual_layer_counts",
                self.minimum_actual_layer_counts,
                np.int16,
            ),
            ("max_layer_reachable", self.max_layer_reachable, np.bool_),
            ("source_indices", self.source_indices, np.int64),
        )
        for name, value, dtype in arrays:
            frozen = np.array(value, dtype=dtype, order="C", copy=True)
            frozen.setflags(write=False)
            object.__setattr__(self, name, frozen)

        row_count = self.score_srgb.shape[0]
        if self.score_srgb.ndim != 2 or self.score_srgb.shape[1] != 3:
            raise ValueError("score_srgb must have shape (U, 3)")
        if self.score_lab.shape != (row_count, 3):
            raise ValueError("score_lab must have shape (U, 3)")
        if self.print_recipes.ndim != 2 or self.print_recipes.shape[0] != row_count:
            raise ValueError("print_recipes must have shape (U, max_layer_count)")
        for name in (
            "minimum_actual_layer_counts",
            "max_layer_reachable",
            "source_indices",
        ):
            if getattr(self, name).shape != (row_count,):
                raise ValueError(f"{name} must have shape (U,)")

    @property
    def stable_source_indices(self) -> np.ndarray:
        """Return retained source rows in stable catalog order.

        返回按稳定目录顺序保留的源行索引。
        """
        return self.source_indices


@dataclass(frozen=True)
class ExactDynamicSearchResult:
    """Exact per-layer-cap search results.

    每个层数上限对应的精确搜索结果。

    Attributes:
        cumulative_best_candidate_indices: Best catalog index for every target
            and allowed layer cap. 每个目标颜色、每个允许层数上限对应的最佳目录索引。
        cumulative_best_delta_e00: Exact CIEDE2000 value paired with every best
            candidate index. 与每个最佳候选索引对应的精确 CIEDE2000 值。
        fixed_max_delta_e00: Exact fixed-maximum baseline for every target.
            每个目标颜色对应的精确固定最大层数基线。
        engine: Engine that produced the result, either ``"numba"`` or
            ``"numpy"``. 生成结果的引擎，为 ``"numba"`` 或 ``"numpy"``。
    """

    cumulative_best_candidate_indices: np.ndarray
    cumulative_best_delta_e00: np.ndarray
    fixed_max_delta_e00: np.ndarray
    engine: str

    def __post_init__(self) -> None:
        indices = np.array(
            self.cumulative_best_candidate_indices,
            dtype=np.int64,
            order="C",
            copy=True,
        )
        values = np.array(
            self.cumulative_best_delta_e00,
            dtype=np.float64,
            order="C",
            copy=True,
        )
        fixed = np.array(
            self.fixed_max_delta_e00,
            dtype=np.float64,
            order="C",
            copy=True,
        )
        if indices.ndim != 2:
            raise ValueError("cumulative_best_candidate_indices must be two-dimensional")
        if values.shape != indices.shape:
            raise ValueError("cumulative Delta-E00 values must match candidate indices")
        if fixed.shape != (indices.shape[0],):
            raise ValueError("fixed_max_delta_e00 must have shape (T,)")
        if self.engine not in {"numba", "numpy"}:
            raise ValueError("engine must be 'numba' or 'numpy'")
        for array in (indices, values, fixed):
            array.setflags(write=False)
        object.__setattr__(self, "cumulative_best_candidate_indices", indices)
        object.__setattr__(self, "cumulative_best_delta_e00", values)
        object.__setattr__(self, "fixed_max_delta_e00", fixed)

    @property
    def best_candidate_indices(self) -> np.ndarray:
        """Return exact cumulative candidate indices by layer cap.

        返回按层数上限排列的精确累计候选索引。
        """
        return self.cumulative_best_candidate_indices

    @property
    def best_delta_e00(self) -> np.ndarray:
        """Return exact cumulative Delta-E00 values by layer cap.

        返回按层数上限排列的精确累计 Delta-E00 值。
        """
        return self.cumulative_best_delta_e00

    @property
    def fixed_max_delta_e00_values(self) -> np.ndarray:
        """Return exact fixed-maximum baseline values.

        返回精确的固定最大层数基线值。
        """
        return self.fixed_max_delta_e00

    @property
    def engine_name(self) -> str:
        """Return the engine that produced the result.

        返回生成结果的引擎名称。
        """
        return self.engine


def _delta_e00_scalar_components(
    lightness1: float,
    a1: float,
    b1: float,
    lightness2: float,
    a2: float,
    b2: float,
) -> float:
    chroma1 = math.sqrt(a1 * a1 + b1 * b1)
    chroma2 = math.sqrt(a2 * a2 + b2 * b2)
    mean_chroma = (chroma1 + chroma2) / 2.0
    mean_chroma_seventh = mean_chroma**7
    compensation = 0.5 * (
        1.0
        - math.sqrt(
            mean_chroma_seventh / (mean_chroma_seventh + 25.0**7)
        )
    )

    adjusted_a1 = a1 * (1.0 + compensation)
    adjusted_a2 = a2 * (1.0 + compensation)
    adjusted_chroma1 = math.sqrt(adjusted_a1**2 + b1**2)
    adjusted_chroma2 = math.sqrt(adjusted_a2**2 + b2**2)
    hue1 = math.degrees(math.atan2(b1, adjusted_a1)) % 360.0
    hue2 = math.degrees(math.atan2(b2, adjusted_a2)) % 360.0

    delta_lightness = lightness2 - lightness1
    delta_chroma = adjusted_chroma2 - adjusted_chroma1
    if adjusted_chroma1 * adjusted_chroma2 == 0.0:
        delta_hue_degrees = 0.0
    elif abs(hue2 - hue1) <= 180.0:
        delta_hue_degrees = hue2 - hue1
    elif hue2 - hue1 > 180.0:
        delta_hue_degrees = hue2 - hue1 - 360.0
    else:
        delta_hue_degrees = hue2 - hue1 + 360.0
    delta_hue = (
        2.0
        * math.sqrt(adjusted_chroma1 * adjusted_chroma2)
        * math.sin(math.radians(delta_hue_degrees / 2.0))
    )

    mean_lightness = (lightness1 + lightness2) / 2.0
    mean_adjusted_chroma = (adjusted_chroma1 + adjusted_chroma2) / 2.0
    if adjusted_chroma1 * adjusted_chroma2 == 0.0:
        mean_hue = hue1 + hue2
    elif abs(hue1 - hue2) <= 180.0:
        mean_hue = (hue1 + hue2) / 2.0
    elif hue1 + hue2 < 360.0:
        mean_hue = (hue1 + hue2 + 360.0) / 2.0
    else:
        mean_hue = (hue1 + hue2 - 360.0) / 2.0

    hue_rotation = (
        1.0
        - 0.17 * math.cos(math.radians(mean_hue - 30.0))
        + 0.24 * math.cos(math.radians(2.0 * mean_hue))
        + 0.32 * math.cos(math.radians(3.0 * mean_hue + 6.0))
        - 0.20 * math.cos(math.radians(4.0 * mean_hue - 63.0))
    )
    lightness_scale = 1.0 + (
        0.015 * (mean_lightness - 50.0) ** 2
        / math.sqrt(20.0 + (mean_lightness - 50.0) ** 2)
    )
    chroma_scale = 1.0 + 0.045 * mean_adjusted_chroma
    hue_scale = 1.0 + 0.015 * mean_adjusted_chroma * hue_rotation

    mean_adjusted_chroma_seventh = mean_adjusted_chroma**7
    rotation_chroma = 2.0 * math.sqrt(
        mean_adjusted_chroma_seventh
        / (mean_adjusted_chroma_seventh + 25.0**7)
    )
    rotation_angle = 30.0 * math.exp(-((mean_hue - 275.0) / 25.0) ** 2)
    rotation_term = -math.sin(math.radians(2.0 * rotation_angle)) * rotation_chroma

    lightness_term = delta_lightness / lightness_scale
    chroma_term = delta_chroma / chroma_scale
    hue_term = delta_hue / hue_scale
    return math.sqrt(
        lightness_term**2
        + chroma_term**2
        + hue_term**2
        + rotation_term * chroma_term * hue_term
    )


_delta_e00_numba_components = njit(cache=True, fastmath=False)(
    _delta_e00_scalar_components
)


def _delta_e00_scalar(lab1: np.ndarray, lab2: np.ndarray) -> float:
    first = np.asarray(lab1, dtype=np.float64)
    second = np.asarray(lab2, dtype=np.float64)
    return _delta_e00_scalar_components(
        float(first[0]),
        float(first[1]),
        float(first[2]),
        float(second[0]),
        float(second[1]),
        float(second[2]),
    )


def _delta_e00_numpy(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    return np.asarray(delta_e_2000(lab1, lab2), dtype=np.float64)


@njit(cache=True, fastmath=False)
def _delta_e00_numba_scalar(lab1: np.ndarray, lab2: np.ndarray) -> float:
    return _delta_e00_numba_components(
        lab1[0],
        lab1[1],
        lab1[2],
        lab2[0],
        lab2[1],
        lab2[2],
    )


def _search_exact_numpy(
    target_lab: np.ndarray,
    candidate_lab: np.ndarray,
    minimum_actual_layer_counts: np.ndarray,
    max_layer_reachable: np.ndarray,
    min_layer_count: int,
    max_layer_count: int,
    candidate_chunk_size: int = _NUMPY_CANDIDATE_CHUNK_SIZE,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    target_count = target_lab.shape[0]
    candidate_count = candidate_lab.shape[0]
    cap_count = max_layer_count - min_layer_count + 1
    best_indices = np.full((target_count, cap_count), -1, dtype=np.int64)
    best_values = np.full((target_count, cap_count), np.inf, dtype=np.float64)
    fixed_max_values = np.full(target_count, np.inf, dtype=np.float64)

    if candidate_chunk_size <= 0:
        raise ValueError("candidate_chunk_size must be positive")

    layer_caps = np.arange(
        min_layer_count,
        max_layer_count + 1,
        dtype=np.int16,
    )
    for target_index in range(target_count):
        target = target_lab[target_index]
        for chunk_start in range(0, candidate_count, candidate_chunk_size):
            chunk_end = min(chunk_start + candidate_chunk_size, candidate_count)
            chunk_lab = candidate_lab[chunk_start:chunk_end]
            distances = _delta_e00_numpy(
                np.broadcast_to(target, chunk_lab.shape),
                chunk_lab,
            )
            chunk_counts = minimum_actual_layer_counts[chunk_start:chunk_end]

            for cap_index, layer_cap in enumerate(layer_caps):
                feasible = np.flatnonzero(chunk_counts <= layer_cap)
                if feasible.size == 0:
                    continue
                local_offset = int(np.argmin(distances[feasible]))
                local_index = int(feasible[local_offset])
                candidate_index = chunk_start + local_index
                candidate_value = float(distances[local_index])
                current_value = best_values[target_index, cap_index]
                current_index = best_indices[target_index, cap_index]
                if candidate_value < current_value or (
                    candidate_value == current_value
                    and (current_index < 0 or candidate_index < current_index)
                ):
                    best_values[target_index, cap_index] = candidate_value
                    best_indices[target_index, cap_index] = candidate_index

            fixed_feasible = np.flatnonzero(
                max_layer_reachable[chunk_start:chunk_end]
            )
            if fixed_feasible.size:
                local_offset = int(np.argmin(distances[fixed_feasible]))
                local_index = int(fixed_feasible[local_offset])
                candidate_value = float(distances[local_index])
                if candidate_value < fixed_max_values[target_index]:
                    fixed_max_values[target_index] = candidate_value

    return best_indices, best_values, fixed_max_values


@njit(nogil=True, fastmath=False, cache=True)
def _search_exact_numba_kernel(
    target_lab: np.ndarray,
    candidate_lab: np.ndarray,
    minimum_actual_layer_counts: np.ndarray,
    max_layer_reachable: np.ndarray,
    min_layer_count: int,
    max_layer_count: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    target_count = target_lab.shape[0]
    candidate_count = candidate_lab.shape[0]
    cap_count = max_layer_count - min_layer_count + 1
    best_indices = np.full((target_count, cap_count), -1, dtype=np.int64)
    best_values = np.full((target_count, cap_count), np.inf, dtype=np.float64)
    fixed_max_values = np.full(target_count, np.inf, dtype=np.float64)

    for target_index in range(target_count):
        target_lightness = target_lab[target_index, 0]
        target_a = target_lab[target_index, 1]
        target_b = target_lab[target_index, 2]
        for candidate_index in range(candidate_count):
            candidate_value = _delta_e00_numba_components(
                target_lightness,
                target_a,
                target_b,
                candidate_lab[candidate_index, 0],
                candidate_lab[candidate_index, 1],
                candidate_lab[candidate_index, 2],
            )
            first_cap = minimum_actual_layer_counts[candidate_index]
            if first_cap < min_layer_count:
                first_cap = min_layer_count
            first_cap_offset = first_cap - min_layer_count
            for cap_index in range(first_cap_offset, cap_count):
                current_value = best_values[target_index, cap_index]
                current_index = best_indices[target_index, cap_index]
                if candidate_value < current_value or (
                    candidate_value == current_value
                    and (current_index < 0 or candidate_index < current_index)
                ):
                    best_values[target_index, cap_index] = candidate_value
                    best_indices[target_index, cap_index] = candidate_index

            if (
                max_layer_reachable[candidate_index]
                and candidate_value < fixed_max_values[target_index]
            ):
                fixed_max_values[target_index] = candidate_value

    return best_indices, best_values, fixed_max_values


def _search_exact_numba_block(
    target_lab: np.ndarray,
    candidate_lab: np.ndarray,
    minimum_actual_layer_counts: np.ndarray,
    max_layer_reachable: np.ndarray,
    min_layer_count: int,
    max_layer_count: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with task_parallelism_worker_scope():
        return _search_exact_numba_kernel(
            target_lab, candidate_lab, minimum_actual_layer_counts,
            max_layer_reachable, min_layer_count, max_layer_count,
        )


def _search_exact_numba(
    target_lab: np.ndarray,
    candidate_lab: np.ndarray,
    minimum_actual_layer_counts: np.ndarray,
    max_layer_reachable: np.ndarray,
    min_layer_count: int,
    max_layer_count: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parallelize independent target rows without Numba's process-wide runtime.

    OpenMP can conflict with the native 3MF writer, while Numba's workqueue
    aborts on concurrent requests. GIL-free blocks use Lumina's bounded thread
    scheduling and keep candidate order and exact per-target reductions intact.
    """
    plan = resolve_task_parallelism_plan(
        "material",
        work_items=len(target_lab),
        work_units=len(target_lab) * len(candidate_lab),
        min_parallel_work_units=_MIN_PARALLEL_SEARCH_COMPARISONS,
        hard_max_workers=None,
    )
    shared_args = (
        candidate_lab, minimum_actual_layer_counts, max_layer_reachable,
        min_layer_count, max_layer_count,
    )
    if plan.workers == 1:
        return _search_exact_numba_block(target_lab, *shared_args)

    blocks = np.array_split(target_lab, plan.workers)
    with ThreadPoolExecutor(max_workers=plan.workers) as executor:
        futures = [executor.submit(_search_exact_numba_block, block, *shared_args) for block in blocks]
        results = [future.result() for future in futures]
    return (
        np.concatenate([result[0] for result in results]),
        np.concatenate([result[1] for result in results]),
        np.concatenate([result[2] for result in results]),
    )


def _validate_layer_bound(value: Any, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise TypeError(f"{name} must be an integer")
    normalized = int(value)
    if not MIN_DYNAMIC_LAYER_COUNT <= normalized <= MAX_DYNAMIC_LAYER_COUNT:
        raise ValueError(
            f"{name} must be between {MIN_DYNAMIC_LAYER_COUNT} and "
            f"{MAX_DYNAMIC_LAYER_COUNT}"
        )
    return normalized


def _coerce_integral_array(
    value: Any,
    *,
    name: str,
    dtype: np.dtype[Any] | type[np.generic],
    minimum: int,
    maximum: int,
) -> np.ndarray:
    array = np.asarray(value)
    if not (
        np.issubdtype(array.dtype, np.integer)
        or np.issubdtype(array.dtype, np.floating)
    ):
        raise TypeError(f"{name} must contain numeric integer-compatible values")
    numeric = array.astype(np.float64, copy=False)
    if not np.all(np.isfinite(numeric)):
        raise ValueError(f"{name} must contain finite values")
    if np.any(numeric != np.floor(numeric)):
        raise ValueError(f"{name} must contain integer-compatible values")
    if np.any(numeric < minimum) or np.any(numeric > maximum):
        raise ValueError(f"{name} values must be between {minimum} and {maximum}")
    return np.asarray(numeric, dtype=dtype)


def build_dynamic_candidate_catalog(
    score_srgb: np.ndarray,
    print_recipes_bottom_to_top: np.ndarray,
    actual_layer_counts: np.ndarray,
    max_layer_count: int,
) -> DynamicCandidateCatalog:
    """Build a losslessly deduplicated candidate catalog.

    构建无损去重的候选目录。

    Args:
        score_srgb: Source scored sRGB rows with shape ``(N, 3)`` and values
            losslessly convertible to ``uint8``. 源评分 sRGB 行，形状为
            ``(N, 3)``，数值必须可无损转换为 ``uint8``。
        print_recipes_bottom_to_top: Fixed-width Bottom-to-Top source recipes
            with shape ``(N, max_layer_count)``. 固定宽度的自底向上源配方，
            形状为 ``(N, max_layer_count)``。
        actual_layer_counts: Actual recipe length for every source row.
            每个源行对应的实际配方层数。
        max_layer_count: Catalog maximum layer count in the inclusive range
            ``5..10``. 目录最大层数，取值范围为 ``5..10``（含边界）。

    Returns:
        DynamicCandidateCatalog: Immutable catalog containing exact-RGB unique
            colors and their deterministic retained recipes. 包含精确 RGB 唯一
            颜色及其确定性保留配方的不可变目录。

    Raises:
        TypeError: If a bound is not an integer or an input contains values with
            an incompatible dtype. 当层数边界不是整数，或输入值类型不兼容时抛出。
        ValueError: If shapes, values, row counts, recipe widths, or layer counts
            are invalid. 当形状、数值、行数、配方宽度或层数无效时抛出。
    """
    normalized_max = _validate_layer_bound(max_layer_count, "max_layer_count")

    rgb_input = np.asarray(score_srgb)
    if rgb_input.ndim != 2 or rgb_input.shape[1] != 3:
        raise ValueError("score_srgb must have shape (N, 3)")
    if rgb_input.shape[0] == 0:
        raise ValueError("score_srgb must contain at least one row")
    rgb = _coerce_integral_array(
        rgb_input,
        name="score_srgb",
        dtype=np.uint8,
        minimum=0,
        maximum=255,
    )

    recipe_input = np.asarray(print_recipes_bottom_to_top)
    expected_recipe_shape = (rgb.shape[0], normalized_max)
    if recipe_input.shape != expected_recipe_shape:
        raise ValueError(
            "print_recipes_bottom_to_top must have shape "
            f"{expected_recipe_shape}"
        )
    recipes = _coerce_integral_array(
        recipe_input,
        name="print_recipes_bottom_to_top",
        dtype=np.int32,
        minimum=0,
        maximum=np.iinfo(np.int32).max,
    )

    count_input = np.asarray(actual_layer_counts)
    if count_input.shape != (rgb.shape[0],):
        raise ValueError("actual_layer_counts must have shape (N,)")
    counts = _coerce_integral_array(
        count_input,
        name="actual_layer_counts",
        dtype=np.int16,
        minimum=MIN_DYNAMIC_LAYER_COUNT,
        maximum=normalized_max,
    )

    packed = (
        (rgb[:, 0].astype(np.uint32) << 16)
        | (rgb[:, 1].astype(np.uint32) << 8)
        | rgb[:, 2].astype(np.uint32)
    )
    catalog_positions: dict[int, int] = {}
    retained_sources: list[int] = []
    minimum_counts: list[int] = []
    max_reachable: list[bool] = []
    for source_index, packed_rgb in enumerate(packed):
        key = int(packed_rgb)
        catalog_index = catalog_positions.get(key)
        actual_count = int(counts[source_index])
        if catalog_index is None:
            catalog_positions[key] = len(retained_sources)
            retained_sources.append(source_index)
            minimum_counts.append(actual_count)
            max_reachable.append(actual_count == normalized_max)
            continue

        if actual_count == normalized_max:
            max_reachable[catalog_index] = True
        if actual_count < minimum_counts[catalog_index]:
            retained_sources[catalog_index] = source_index
            minimum_counts[catalog_index] = actual_count

    source_indices = np.asarray(retained_sources, dtype=np.int64)
    retained_rgb = np.asarray(rgb[source_indices], dtype=np.uint8)
    return DynamicCandidateCatalog(
        score_srgb=retained_rgb,
        score_lab=np.asarray(rgb_to_lab(retained_rgb), dtype=np.float64),
        print_recipes=np.asarray(recipes[source_indices], dtype=np.int32),
        minimum_actual_layer_counts=np.asarray(minimum_counts, dtype=np.int16),
        max_layer_reachable=np.asarray(max_reachable, dtype=np.bool_),
        source_indices=source_indices,
    )


def search_dynamic_catalog_exact(
    target_srgb: np.ndarray,
    catalog: DynamicCandidateCatalog,
    min_layer_count: int,
    max_layer_count: int,
    prefer_numba: bool = True,
) -> ExactDynamicSearchResult:
    """Search a candidate catalog with exhaustive CIEDE2000 scoring.

    使用穷举 CIEDE2000 评分搜索候选目录。

    Args:
        target_srgb: Target sRGB rows with shape ``(T, 3)`` and values losslessly
            convertible to ``uint8``. 目标 sRGB 行，形状为 ``(T, 3)``，数值必须
            可无损转换为 ``uint8``。
        catalog: Losslessly deduplicated dynamic candidate catalog.
            无损去重后的动态候选目录。
        min_layer_count: First allowed layer cap in the inclusive range
            ``5..10``. 最小允许层数上限，取值范围为 ``5..10``（含边界）。
        max_layer_count: Last allowed layer cap in the inclusive range ``5..10``;
            it must not be less than ``min_layer_count`` or exceed the catalog
            recipe width. 最大允许层数上限，取值范围为 ``5..10``（含边界），
            不得小于 ``min_layer_count`` 或超过目录配方宽度。
        prefer_numba: Try the exact parallel Numba engine before the exact
            chunked NumPy engine. 是否优先尝试精确并行 Numba 引擎，再回退到
            精确分块 NumPy 引擎。

    Returns:
        ExactDynamicSearchResult: Exact cumulative frontiers, fixed-maximum
            baselines, and the engine name. 精确累计前沿、固定最大层数基线和
            引擎名称。

    Raises:
        TypeError: If ``catalog`` has the wrong type, a bound is not an integer,
            or target values have an incompatible dtype. 当 ``catalog`` 类型错误、
            层数边界不是整数或目标值类型不兼容时抛出。
        ValueError: If target/catalog shapes, values, population, layer counts,
            or bounds are invalid. 当目标或目录的形状、数值、候选数量、层数或
            边界无效时抛出。
        DynamicMaterialSolverError: If every selected exact engine fails at call
            time. 当所有选定的精确引擎均在调用时失败时抛出。
    """
    normalized_min = _validate_layer_bound(min_layer_count, "min_layer_count")
    normalized_max = _validate_layer_bound(max_layer_count, "max_layer_count")
    if normalized_min > normalized_max:
        raise ValueError("min_layer_count must not exceed max_layer_count")
    if not isinstance(catalog, DynamicCandidateCatalog):
        raise TypeError("catalog must be a DynamicCandidateCatalog")
    if catalog.score_srgb.shape[0] == 0:
        raise ValueError("catalog must contain at least one candidate")
    catalog_max_layer_count = catalog.print_recipes.shape[1]
    if normalized_max > catalog_max_layer_count:
        raise ValueError("max_layer_count exceeds the catalog recipe width")
    if np.any(catalog.minimum_actual_layer_counts < MIN_DYNAMIC_LAYER_COUNT) or np.any(
        catalog.minimum_actual_layer_counts > catalog_max_layer_count
    ):
        raise ValueError("catalog minimum layer counts are outside its recipe bounds")

    target_input = np.asarray(target_srgb)
    if target_input.ndim != 2 or target_input.shape[1] != 3:
        raise ValueError("target_srgb must have shape (T, 3)")
    targets = _coerce_integral_array(
        target_input,
        name="target_srgb",
        dtype=np.uint8,
        minimum=0,
        maximum=255,
    )
    if targets.shape[0] == 0:
        target_lab = np.empty((0, 3), dtype=np.float64)
    else:
        target_lab = np.asarray(rgb_to_lab(targets), dtype=np.float64)

    kernel_arguments = (
        target_lab,
        catalog.score_lab,
        catalog.minimum_actual_layer_counts,
        catalog.max_layer_reachable,
        normalized_min,
        normalized_max,
    )
    numba_error: Exception | None = None
    if prefer_numba and _NUMBA_AVAILABLE:
        try:
            indices, values, fixed = _search_exact_numba(*kernel_arguments)
            return ExactDynamicSearchResult(
                cumulative_best_candidate_indices=indices,
                cumulative_best_delta_e00=values,
                fixed_max_delta_e00=fixed,
                engine="numba",
            )
        except Exception as exc:
            numba_error = exc

    try:
        indices, values, fixed = _search_exact_numpy(*kernel_arguments)
        return ExactDynamicSearchResult(
            cumulative_best_candidate_indices=indices,
            cumulative_best_delta_e00=values,
            fixed_max_delta_e00=fixed,
            engine="numpy",
        )
    except Exception as exc:
        if numba_error is not None:
            message = "exact dynamic search failed in both numba and numpy engines"
        else:
            message = "exact dynamic search failed in the numpy engine"
        raise DynamicMaterialSolverError(message) from exc


MaterialRuntimeLoader = Callable[
    [list[MaterialParams], int, float, str],
    tuple[MaterialSolverCache | MaterialCandidateRuntime | None, int | None],
]


def _candidate_failure(
    message: str,
    *,
    layer_count: int,
    phase: str,
    target_srgb: tuple[int, int, int] | None = None,
    cause: Exception | None = None,
) -> DynamicMaterialCandidateError:
    error = DynamicMaterialCandidateError(
        message,
        layer_count=layer_count,
        phase=phase,
        target_srgb=target_srgb,
    )
    if cause is not None:
        error.__cause__ = cause
    return error


def _normalize_runtime_recipe_table(
    value: Any,
    *,
    layer_count: int,
    material_count: int,
    phase: str,
) -> np.ndarray:
    try:
        recipes = np.asarray(value)
    except Exception as exc:
        raise _candidate_failure(
            f"recipe table cannot be converted to an array: {exc}",
            layer_count=layer_count,
            phase=phase,
            cause=exc,
        )
    if recipes.ndim != 2:
        raise _candidate_failure(
            f"recipe table must be two-dimensional, got {recipes.shape}",
            layer_count=layer_count,
            phase=phase,
        )
    if recipes.shape[1] != layer_count:
        raise _candidate_failure(
            f"recipe width {recipes.shape[1]} does not match layer count",
            layer_count=layer_count,
            phase=phase,
        )
    if recipes.shape[0] == 0:
        return np.empty((0, layer_count), dtype=np.int32)
    try:
        return _coerce_integral_array(
            recipes,
            name="runtime recipes",
            dtype=np.int32,
            minimum=0,
            maximum=material_count - 1,
        )
    except Exception as exc:
        raise _candidate_failure(
            str(exc),
            layer_count=layer_count,
            phase=phase,
            cause=exc,
        )


def _runtime_recipes_canonical(
    runtime: MaterialSolverCache | MaterialCandidateRuntime,
    *,
    layer_count: int,
    material_count: int,
) -> np.ndarray:
    try:
        raw_layer_count = runtime.metadata["layer_count"]
        if isinstance(raw_layer_count, (bool, np.bool_)) or not isinstance(
            raw_layer_count,
            (int, float, np.integer, np.floating),
        ):
            raise TypeError("runtime layer count must be an integer")
        numeric_layer_count = float(raw_layer_count)
        if not math.isfinite(numeric_layer_count):
            raise ValueError("runtime layer count must be finite")
        if numeric_layer_count != math.floor(numeric_layer_count):
            raise ValueError("runtime layer count must be integral")
        runtime_layer_count = int(numeric_layer_count)
    except Exception as exc:
        raise _candidate_failure(
            "runtime does not expose a valid layer count",
            layer_count=layer_count,
            phase="runtime_metadata",
            cause=exc,
        )
    if runtime_layer_count != layer_count:
        raise _candidate_failure(
            f"runtime layer count is {runtime_layer_count}",
            layer_count=layer_count,
            phase="runtime_metadata",
        )

    if isinstance(runtime, MaterialCandidateRuntime):
        recipes = _normalize_runtime_recipe_table(
            runtime.candidate_recipes,
            layer_count=layer_count,
            material_count=material_count,
            phase="candidate_recipes",
        )
    elif isinstance(runtime, MaterialSolverCache):
        recipes = _normalize_runtime_recipe_table(
            runtime.recipes,
            layer_count=layer_count,
            material_count=material_count,
            phase="cache_recipes",
        )
        try:
            uniform_input = np.asarray(runtime.uniform_recipes)
        except Exception as exc:
            raise _candidate_failure(
                f"uniform recipe table cannot be converted to an array: {exc}",
                layer_count=layer_count,
                phase="cache_uniform_recipes",
                cause=exc,
            )
        if uniform_input.size:
            uniform = _normalize_runtime_recipe_table(
                uniform_input,
                layer_count=layer_count,
                material_count=material_count,
                phase="cache_uniform_recipes",
            )
            recipes = np.concatenate((recipes, uniform), axis=0)
    else:
        raise _candidate_failure(
            f"unsupported runtime type {type(runtime).__name__}",
            layer_count=layer_count,
            phase="runtime_type",
        )

    if recipes.shape[0] == 0:
        raise _candidate_failure(
            "runtime contains no candidate recipes",
            layer_count=layer_count,
            phase="candidate_recipes",
        )
    return recipes


def _layer_option_from_catalog(
    catalog: DynamicCandidateCatalog,
    candidate_index: int,
    layer_cap: int,
    delta_e00: float,
) -> DynamicMaterialLayerOption:
    actual_count = int(catalog.minimum_actual_layer_counts[candidate_index])
    print_recipe_array = catalog.print_recipes[candidate_index]
    actual_recipe_array = print_recipe_array[-actual_count:]
    return DynamicMaterialLayerOption(
        max_effective_layer_count=int(layer_cap),
        actual_layer_count=actual_count,
        matched_srgb=tuple(int(value) for value in catalog.score_srgb[candidate_index]),
        actual_recipe_bottom_to_top=tuple(int(value) for value in actual_recipe_array),
        print_recipe_bottom_to_top=tuple(int(value) for value in print_recipe_array),
        delta_e00=float(delta_e00),
    )


def _build_dynamic_candidate_catalog_from_runtimes(
    materials: list[MaterialParams],
    backing_index: int,
    layer_height_mm: float,
    substrate: str,
    config: DynamicMaterialSolveConfig,
    runtime_loader: MaterialRuntimeLoader,
) -> tuple[DynamicCandidateCatalog, int, tuple[int, ...]]:
    canonical_to_user = np.asarray(
        canonical_palette_order(materials),
        dtype=np.int32,
    )
    if canonical_to_user.shape != (len(materials),):
        raise ValueError("canonical palette mapping has an invalid shape")
    substrate_linear = (
        np.ones(3, dtype=np.float64)
        if substrate == "white"
        else np.zeros(3, dtype=np.float64)
    )
    layer_counts = tuple(range(config.min_layer_count, config.max_layer_count + 1))
    all_print_recipes: list[np.ndarray] = []
    all_score_srgb: list[np.ndarray] = []
    all_actual_counts: list[np.ndarray] = []

    for layer_count in layer_counts:
        try:
            loaded = runtime_loader(
                materials,
                layer_count,
                layer_height_mm,
                substrate,
            )
        except Exception as exc:
            raise _candidate_failure(
                str(exc),
                layer_count=layer_count,
                phase="runtime_load",
                cause=exc,
            )
        if not isinstance(loaded, tuple) or len(loaded) != 2:
            raise _candidate_failure(
                "runtime loader must return a two-item tuple",
                layer_count=layer_count,
                phase="runtime_load",
            )
        runtime, _diagnostic_resolution = loaded
        if runtime is None:
            raise _candidate_failure(
                "runtime loader returned no runtime",
                layer_count=layer_count,
                phase="runtime_load",
            )
        canonical_recipes = _runtime_recipes_canonical(
            runtime,
            layer_count=layer_count,
            material_count=len(materials),
        )
        user_recipes = canonical_to_user[canonical_recipes]
        padding_count = config.max_layer_count - layer_count
        if padding_count:
            padding = np.full(
                (user_recipes.shape[0], padding_count),
                backing_index,
                dtype=np.int32,
            )
            print_recipes = np.concatenate((padding, user_recipes), axis=1)
        else:
            print_recipes = np.asarray(user_recipes, dtype=np.int32)
        try:
            simulated_linear = forward_batch_model(
                print_recipes,
                materials,
                layer_height_mm,
                substrate_linear,
            )
            if simulated_linear.shape != (print_recipes.shape[0], 3):
                raise ValueError(
                    f"simulation returned shape {simulated_linear.shape}"
                )
            if not np.all(np.isfinite(simulated_linear)):
                raise ValueError("simulation returned non-finite colors")
            simulated_srgb = linear_to_srgb_uint8(simulated_linear)
        except Exception as exc:
            raise _candidate_failure(
                str(exc),
                layer_count=layer_count,
                phase="full_stack_simulation",
                cause=exc,
            )
        if simulated_srgb.shape != (print_recipes.shape[0], 3):
            raise _candidate_failure(
                f"simulation returned shape {simulated_srgb.shape}",
                layer_count=layer_count,
                phase="full_stack_simulation",
            )
        all_print_recipes.append(print_recipes)
        all_score_srgb.append(simulated_srgb)
        all_actual_counts.append(
            np.full(print_recipes.shape[0], layer_count, dtype=np.int16)
        )

    print_recipes = np.concatenate(all_print_recipes, axis=0)
    scored_srgb = np.concatenate(all_score_srgb, axis=0)
    actual_counts = np.concatenate(all_actual_counts, axis=0)
    catalog = build_dynamic_candidate_catalog(
        scored_srgb,
        print_recipes,
        actual_counts,
        config.max_layer_count,
    )
    return catalog, int(print_recipes.shape[0]), layer_counts


def _build_dynamic_color_matches(
    targets: np.ndarray,
    catalog: DynamicCandidateCatalog,
    search: ExactDynamicSearchResult,
    layer_counts: tuple[int, ...],
    tolerance: float,
) -> tuple[DynamicMaterialColorMatch, ...]:
    matches: list[DynamicMaterialColorMatch] = []
    for target_index, target in enumerate(targets):
        options: list[DynamicMaterialLayerOption] = []
        for cap_offset, layer_cap in enumerate(layer_counts):
            candidate_index = int(
                search.cumulative_best_candidate_indices[target_index, cap_offset]
            )
            delta_e00 = float(
                search.cumulative_best_delta_e00[target_index, cap_offset]
            )
            if (
                candidate_index < 0
                or candidate_index >= catalog.score_srgb.shape[0]
                or not math.isfinite(delta_e00)
            ):
                raise _candidate_failure(
                    "no candidate is available for this layer cap",
                    layer_count=layer_cap,
                    phase="exact_search",
                    target_srgb=tuple(int(value) for value in target),
                )
            options.append(
                _layer_option_from_catalog(
                    catalog,
                    candidate_index,
                    layer_cap,
                    delta_e00,
                )
            )
        fixed_max_delta_e00 = float(search.fixed_max_delta_e00[target_index])
        if not math.isfinite(fixed_max_delta_e00):
            raise _candidate_failure(
                "fixed maximum-layer baseline is unavailable",
                layer_count=layer_counts[-1],
                phase="fixed_max_baseline",
                target_srgb=tuple(int(value) for value in target),
            )
        best_range = options[-1]
        threshold = best_range.delta_e00 + tolerance
        selected = next(option for option in options if option.delta_e00 <= threshold)
        sacrifice = selected.delta_e00 - best_range.delta_e00
        if sacrifice < 0.0 and abs(sacrifice) < 1e-12:
            sacrifice = 0.0
        matches.append(
            DynamicMaterialColorMatch(
                target_srgb=tuple(int(value) for value in target),
                selected=selected,
                best_range=best_range,
                fixed_max_delta_e00=fixed_max_delta_e00,
                delta_e00_sacrifice=float(sacrifice),
                layer_cap_options=tuple(options),
            )
        )
    return tuple(matches)


def solve_dynamic_material_colors(
    target_srgb: np.ndarray,
    materials: list[MaterialParams],
    backing_material_index: int,
    layer_height_mm: float,
    substrate: str,
    config: DynamicMaterialSolveConfig,
    runtime_loader: MaterialRuntimeLoader | None = None,
    *,
    material_candidate_budget: int = PREVIEW_SAFE_CANDIDATE_BUDGET,
    catalog_cache_root: str | Path | None = None,
) -> DynamicMaterialSolveResult:
    """Build padded candidates and solve every target with exact CIEDE2000.

    构建补位后的候选，并以精确 CIEDE2000 求解每个目标颜色。

    Args:
        target_srgb: Target sRGB rows shaped ``(T, 3)``. 形状为 ``(T, 3)`` 的
            目标 sRGB 行。
        materials: Material parameters in caller/user order. 按调用方或用户顺序
            排列的耗材参数。
        backing_material_index: Caller-order material used to pad the
            substrate-adjacent side. 用于非观赏面补位的调用方顺序耗材索引。
        layer_height_mm: Physical thickness of every printed layer. 每一打印层的
            物理厚度（毫米）。
        substrate: Substrate color, ``"white"`` or ``"black"``. 基底颜色，
            为 ``"white"`` 或 ``"black"``。
        config: Validated dynamic solve range and tolerance. 已验证的动态求解范围
            与容差。
        runtime_loader: Optional custom candidate runtime loader called once per
            allowed layer count. Supplying one bypasses persistent catalog
            caching. 可选自定义候选运行时加载器；每个允许层数调用一次，传入时
            绕过持久目录缓存。
        material_candidate_budget: Explicit production candidate budget pinned
            identically for every allowed layer. 生产路径在所有层数统一固定使用的
            显式候选预算。
        catalog_cache_root: Optional persistent catalog/candidate cache root.
            可选持久目录及候选缓存根目录。

    Returns:
        DynamicMaterialSolveResult: Exact per-target choices and candidate
            diagnostics. 每个目标的精确选项和候选诊断信息。

    Raises:
        TypeError: If configuration, materials, indices, targets, or loader
            values have incompatible types. 当配置、耗材、索引、目标或加载器
            返回值类型不兼容时抛出。
        ValueError: If target values, backing index, thickness, or substrate are
            invalid. 当目标值、基板耗材索引、层厚或基底无效时抛出。
        DynamicMaterialCandidateError: If any layer runtime/candidate table is
            missing or malformed, simulation fails, a cap has no candidate, or
            the fixed-max baseline is unavailable. 当任一层运行时或候选表缺失、
            格式错误、模拟失败、某层数上限无候选或固定最大层数基线不可用时抛出。
        DynamicMaterialSolverError: If both exact search engines fail. 当两个
            精确搜索引擎均失败时抛出。
    """
    if not isinstance(config, DynamicMaterialSolveConfig):
        raise TypeError("config must be a DynamicMaterialSolveConfig")
    if not isinstance(materials, list) or not materials:
        raise ValueError("materials must be a non-empty list")
    if not all(isinstance(material, MaterialParams) for material in materials):
        raise TypeError("materials must contain MaterialParams values")
    if isinstance(backing_material_index, (bool, np.bool_)) or not isinstance(
        backing_material_index,
        (int, np.integer),
    ):
        raise TypeError("backing_material_index must be an integer")
    backing_index = int(backing_material_index)
    if not 0 <= backing_index < len(materials):
        raise ValueError("backing_material_index is outside the material palette")
    if isinstance(layer_height_mm, (bool, np.bool_)) or not isinstance(
        layer_height_mm,
        (int, float, np.integer, np.floating),
    ):
        raise TypeError("layer_height_mm must be a real number")
    normalized_height = float(layer_height_mm)
    if not math.isfinite(normalized_height) or normalized_height <= 0.0:
        raise ValueError("layer_height_mm must be finite and positive")
    normalized_substrate = str(substrate).lower()
    if normalized_substrate not in {"white", "black"}:
        raise ValueError("substrate must be 'white' or 'black'")
    if isinstance(material_candidate_budget, (bool, np.bool_)) or not isinstance(
        material_candidate_budget,
        (int, np.integer),
    ):
        raise TypeError("material_candidate_budget must be an integer")
    candidate_budget = int(material_candidate_budget)
    if candidate_budget <= 0:
        raise ValueError("material_candidate_budget must be positive")

    target_input = np.asarray(target_srgb)
    if target_input.ndim != 2 or target_input.shape[1] != 3:
        raise ValueError("target_srgb must have shape (T, 3)")
    targets = _coerce_integral_array(
        target_input,
        name="target_srgb",
        dtype=np.uint8,
        minimum=0,
        maximum=255,
    )

    layer_counts = tuple(range(config.min_layer_count, config.max_layer_count + 1))
    if runtime_loader is not None:
        catalog, candidate_count_before_dedup, layer_counts = (
            _build_dynamic_candidate_catalog_from_runtimes(
                materials,
                backing_index,
                normalized_height,
                normalized_substrate,
                config,
                runtime_loader,
            )
        )
    else:
        from core.material_dynamic_catalog_cache import (
            build_dynamic_catalog_cache_key,
            dynamic_material_canonical_order,
            load_or_build_dynamic_candidate_catalog,
        )

        canonical_to_user = np.asarray(
            dynamic_material_canonical_order(materials),
            dtype=np.int32,
        )
        user_to_canonical = np.empty(len(materials), dtype=np.int32)
        user_to_canonical[canonical_to_user] = np.arange(
            len(materials), dtype=np.int32
        )
        canonical_materials = [materials[int(index)] for index in canonical_to_user]
        canonical_backing_index = int(user_to_canonical[backing_index])

        def production_runtime_loader(
            loader_materials: list[MaterialParams],
            layer_count: int,
            loader_height: float,
            loader_substrate: str,
        ) -> tuple[MaterialCandidateRuntime | None, int | None]:
            return load_dynamic_candidate_runtime(
                loader_materials,
                layer_count,
                loader_height,
                loader_substrate,
                candidate_budget=candidate_budget,
                cache_root=catalog_cache_root,
            )

        cache_key = build_dynamic_catalog_cache_key(
            materials,
            backing_material_index=backing_index,
            layer_height_mm=normalized_height,
            substrate=normalized_substrate,
            min_layer_count=config.min_layer_count,
            max_layer_count=config.max_layer_count,
            candidate_budget=candidate_budget,
        )

        def build_catalog() -> tuple[DynamicCandidateCatalog, int]:
            canonical_catalog, before_count, _built_layer_counts = (
                _build_dynamic_candidate_catalog_from_runtimes(
                    canonical_materials,
                    canonical_backing_index,
                    normalized_height,
                    normalized_substrate,
                    config,
                    production_runtime_loader,
                )
            )
            built_catalog = DynamicCandidateCatalog(
                score_srgb=canonical_catalog.score_srgb,
                score_lab=canonical_catalog.score_lab,
                print_recipes=canonical_to_user[canonical_catalog.print_recipes],
                minimum_actual_layer_counts=(
                    canonical_catalog.minimum_actual_layer_counts
                ),
                max_layer_reachable=canonical_catalog.max_layer_reachable,
                source_indices=canonical_catalog.source_indices,
            )
            return built_catalog, before_count

        cached_catalog = load_or_build_dynamic_candidate_catalog(
            materials=materials,
            key=cache_key,
            builder=build_catalog,
            cache_root=catalog_cache_root,
        )
        catalog = cached_catalog.catalog
        candidate_count_before_dedup = (
            cached_catalog.candidate_count_before_dedup
        )
    search = search_dynamic_catalog_exact(
        targets,
        catalog,
        config.min_layer_count,
        config.max_layer_count,
    )
    matches = _build_dynamic_color_matches(
        targets,
        catalog,
        search,
        layer_counts,
        config.delta_e00_tolerance,
    )

    return DynamicMaterialSolveResult(
        matches=matches,
        engine=search.engine,
        candidate_count_before_dedup=candidate_count_before_dedup,
        candidate_count_after_dedup=int(catalog.score_srgb.shape[0]),
        layer_counts=layer_counts,
    )


def build_material_layer_benefit_curve(
    matches: Sequence[DynamicMaterialColorMatch],
    pixel_counts: Sequence[int],
) -> tuple[MaterialLayerBenefitPoint, ...]:
    """Build the pixel-weighted exact CIEDE2000 layer-benefit curve.

    构建按像素加权的精确 CIEDE2000 层数收益曲线。

    Args:
        matches: Dynamic matches in target-color order. 按目标颜色顺序排列的
            动态匹配结果。
        pixel_counts: One positive pixel count per match. 每个匹配结果对应一个
            正像素数。

    Returns:
        tuple[MaterialLayerBenefitPoint, ...]: One weighted point per effective
            layer cap. 每个有效层数上限对应一个加权收益点。

    Raises:
        TypeError: If matches or pixel counts have incompatible value types.
            当匹配结果或像素数类型不兼容时抛出。
        ValueError: If lengths, counts, or layer-cap layouts are invalid.
            当长度、像素数或层数上限布局无效时抛出。
    """
    normalized_matches = tuple(matches)
    normalized_counts = tuple(pixel_counts)
    if len(normalized_matches) != len(normalized_counts):
        raise ValueError("pixel_counts must contain one value per match")
    if not normalized_matches:
        return ()
    if not all(
        isinstance(match, DynamicMaterialColorMatch)
        for match in normalized_matches
    ):
        raise TypeError("matches must contain DynamicMaterialColorMatch values")
    counts: list[int] = []
    for value in normalized_counts:
        if isinstance(value, (bool, np.bool_)) or not isinstance(
            value,
            (int, np.integer),
        ):
            raise TypeError("pixel counts must be integers")
        count = int(value)
        if count <= 0:
            raise ValueError("pixel counts must be positive")
        counts.append(count)

    expected_caps = tuple(
        option.max_effective_layer_count
        for option in normalized_matches[0].layer_cap_options
    )
    if not expected_caps:
        raise ValueError("matches must contain at least one layer-cap option")
    for match in normalized_matches:
        caps = tuple(
            option.max_effective_layer_count
            for option in match.layer_cap_options
        )
        if caps != expected_caps:
            raise ValueError("all matches must use identical layer caps")

    weights = np.asarray(counts, dtype=np.float64)
    means: list[float] = []
    for cap_offset in range(len(expected_caps)):
        values = np.asarray(
            [
                match.layer_cap_options[cap_offset].delta_e00
                for match in normalized_matches
            ],
            dtype=np.float64,
        )
        if not np.all(np.isfinite(values)):
            raise ValueError("layer-cap Delta-E00 values must be finite")
        means.append(float(np.average(values, weights=weights)))

    points: list[MaterialLayerBenefitPoint] = []
    for index, (layer_cap, mean) in enumerate(zip(expected_caps, means)):
        marginal = 0.0 if index == 0 else means[index - 1] - mean
        points.append(
            MaterialLayerBenefitPoint(
                max_effective_layer_count=int(layer_cap),
                weighted_mean_delta_e00=mean,
                marginal_delta_e00_reduction=float(marginal),
            )
        )
    return tuple(points)
