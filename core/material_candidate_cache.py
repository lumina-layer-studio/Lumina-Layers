"""Bounded material candidate runtime.

候选缓存运行时：用有限候选覆盖大耗材空间，避免生产路径穷举 ``M ** N``。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from scipy.spatial import cKDTree

from core.material_cache import (
    _hue_aware_rerank,
    _neighbor_coherence_refine,
    canonical_palette_order,
    describe_palette,
    default_cache_directory,
    _find_cache_record,
)
from core.material_candidate_sampling import (
    CandidateRecipeBatch,
    _low_discrepancy_recipes,
    _pair_ramp_recipes,
    _recipe_space_chunk,
    _safe_total_count,
    _uniform_recipes,
    _unique_rows_preserve_order,
)
from core.material_color_solver import (
    ColorSuggestion,
    MaterialParams,
    _greedy_lab_spacing_dedup,
    _compute_material_affines,
    linear_to_srgb_uint8,
    rgb_to_lab,
)
from core.material_inverse_refinement import (
    MaterialInverseRefinementConfig,
    refine_material_matches,
)
from core.material_layer_dp import (
    DEFAULT_STATE_CELL_LAB as _LAYER_DP_DEFAULT_CELL,
    generate_layer_dp_recipes_cached,
)


PREVIEW_SAFE_CANDIDATE_BUDGET = 1_048_576
LEGACY_PERSISTED_CANDIDATE_BUDGET = 4_194_304
QUALITY_8M_CANDIDATE_BUDGET = 8_388_608
RECOMMENDED_PERSISTED_CANDIDATE_BUDGET = 33_554_432
MAX_PERSISTED_CANDIDATE_BUDGET = 67_108_864
DEFAULT_PERSISTED_CANDIDATE_BUDGET = RECOMMENDED_PERSISTED_CANDIDATE_BUDGET
DEFAULT_CANDIDATE_BUILD_WORKERS = max(1, min(16, os.cpu_count() or 1))
HYBRID_CANDIDATE_SCHEMA_VERSION = "3.0"
HYBRID_CANDIDATE_ALGORITHM_VERSION = "hybrid-v3"


def _candidate_pool_multiplier_for_budget(candidate_budget: int) -> int:
    budget = int(candidate_budget)
    if budget <= LEGACY_PERSISTED_CANDIDATE_BUDGET:
        return 8
    if budget <= QUALITY_8M_CANDIDATE_BUDGET:
        return 4
    if budget <= RECOMMENDED_PERSISTED_CANDIDATE_BUDGET:
        return 2
    return 1


@dataclass(frozen=True)
class MaterialCandidateCacheConfig:
    """Configuration for bounded material candidate runtime builds.
    耗材候选运行时构建配置。

    Attributes:
        candidate_budget: Final candidate row budget. (最终候选行数预算)
        candidate_pool_multiplier: Optional evaluated-candidate multiplier.
            ``None`` derives a budget-aware value. (可选评估候选倍数；
            ``None`` 时按预算自动推导)
        batch_recipe_count: Forward-model batch size. (正向预测批大小)
        build_worker_count: Parallel chunk worker count. (并行分块 worker 数)
        lab_grid_resolution: Diagnostic Lab resolution label. (诊断用 Lab 分辨率)
        seed: Deterministic sampling seed. (确定性采样种子)
        enable_inverse_refinement: Reserved inverse-refinement flag.
            (预留的反向精修开关)
        max_refine_materials: Reserved material cap for inverse refinement.
            (反向精修耗材数量上限)
        max_refine_top_suffixes: Reserved top suffix cap. (顶部后缀数量上限)
        max_refine_bottom_prefixes: Reserved bottom prefix cap. (底部前缀数量上限)
        refine_bottom_neighbors: Bottom-prefix neighbors per inverse target.
            (每个反推目标使用的底部前缀邻居数)
        layer_dp_min_layer_count: Layer counts at or above this use the
            layer-wise DP generator (see :mod:`core.material_layer_dp`)
            instead of random sampling when ``M ** N`` exceeds the budget.
            ``0`` disables it. (达到该层数且无法穷举时改用逐层 DP；0 关闭)
        layer_dp_state_cell_lab: Initial Lab merge cell for the DP.
            (逐层 DP 初始 Lab 合并格)
    """

    candidate_budget: int
    candidate_pool_multiplier: int | None = None
    batch_recipe_count: int = 524_288
    build_worker_count: int | None = None
    lab_grid_resolution: int = 64
    seed: int = 0
    enable_inverse_refinement: bool = True
    max_refine_materials: int = 12
    max_refine_top_suffixes: int = 4096
    max_refine_bottom_prefixes: int = 64
    refine_bottom_neighbors: int = 2
    layer_dp_min_layer_count: int = 11
    layer_dp_state_cell_lab: float = _LAYER_DP_DEFAULT_CELL

    def uses_layer_dp(self, layer_count: int) -> bool:
        threshold = int(self.layer_dp_min_layer_count)
        return threshold > 0 and int(layer_count) >= threshold

    def __post_init__(self) -> None:
        if self.candidate_pool_multiplier is None:
            multiplier = _candidate_pool_multiplier_for_budget(
                int(self.candidate_budget)
            )
        else:
            multiplier = max(1, int(self.candidate_pool_multiplier))
        object.__setattr__(self, "candidate_pool_multiplier", multiplier)

    @classmethod
    def preview_safe(cls) -> "MaterialCandidateCacheConfig":
        return cls(
            candidate_budget=PREVIEW_SAFE_CANDIDATE_BUDGET,
            candidate_pool_multiplier=1,
            max_refine_materials=8,
            max_refine_top_suffixes=4096,
            max_refine_bottom_prefixes=4096,
            refine_bottom_neighbors=2,
        )

    @classmethod
    def default_persisted(cls) -> "MaterialCandidateCacheConfig":
        return cls(
            candidate_budget=DEFAULT_PERSISTED_CANDIDATE_BUDGET,
            candidate_pool_multiplier=_candidate_pool_multiplier_for_budget(
                DEFAULT_PERSISTED_CANDIDATE_BUDGET
            ),
            max_refine_materials=8,
            max_refine_top_suffixes=32_768,
            max_refine_bottom_prefixes=65_536,
            refine_bottom_neighbors=2,
        )

    @classmethod
    def quality_8m(cls) -> "MaterialCandidateCacheConfig":
        return cls(
            candidate_budget=QUALITY_8M_CANDIDATE_BUDGET,
            candidate_pool_multiplier=_candidate_pool_multiplier_for_budget(
                QUALITY_8M_CANDIDATE_BUDGET
            ),
            max_refine_materials=8,
            max_refine_top_suffixes=32_768,
            max_refine_bottom_prefixes=65_536,
            refine_bottom_neighbors=2,
        )

    @classmethod
    def recommended_persisted(cls) -> "MaterialCandidateCacheConfig":
        return cls.default_persisted()

    @classmethod
    def max_persisted(cls) -> "MaterialCandidateCacheConfig":
        return cls(
            candidate_budget=MAX_PERSISTED_CANDIDATE_BUDGET,
            candidate_pool_multiplier=_candidate_pool_multiplier_for_budget(
                MAX_PERSISTED_CANDIDATE_BUDGET
            ),
            max_refine_materials=8,
            max_refine_top_suffixes=32_768,
            max_refine_bottom_prefixes=65_536,
            refine_bottom_neighbors=2,
        )

    @classmethod
    def persisted_for_budget(
        cls,
        candidate_budget: int,
    ) -> "MaterialCandidateCacheConfig":
        return cls(
            candidate_budget=int(candidate_budget),
            candidate_pool_multiplier=_candidate_pool_multiplier_for_budget(
                int(candidate_budget)
            ),
            max_refine_materials=8,
            max_refine_top_suffixes=32_768,
            max_refine_bottom_prefixes=65_536,
            refine_bottom_neighbors=2,
        )


@dataclass(frozen=True)
class CandidatePredictionBatch:
    recipes: np.ndarray
    achieved_srgb: np.ndarray
    achieved_lab: np.ndarray


@dataclass(frozen=True)
class CandidateSelection:
    recipes: np.ndarray
    achieved_srgb: np.ndarray
    achieved_lab: np.ndarray
    pinned_mask: np.ndarray
    worker_count: int
    build_info: dict[str, Any] | None = None


def _recipe_dtype_for_material_count(material_count: int) -> np.dtype:
    if int(material_count) <= np.iinfo(np.uint8).max + 1:
        return np.dtype(np.uint8)
    return np.dtype(np.uint16)


def _resolve_candidate_build_worker_count(worker_count: int | None = None) -> int:
    if worker_count is None:
        return DEFAULT_CANDIDATE_BUILD_WORKERS
    return max(1, int(worker_count))


def _candidate_cache_meta_path_for(npz_path: Path) -> Path:
    return npz_path.with_name(npz_path.stem + ".meta.json")


def _candidate_configuration(config: MaterialCandidateCacheConfig) -> dict[str, Any]:
    return {
        "grid_resolution": int(config.lab_grid_resolution),
        "candidate_pool_multiplier": int(config.candidate_pool_multiplier),
        "batch_recipe_count": int(config.batch_recipe_count),
        "seed": int(config.seed),
        "inverse_refinement": {
            "enabled": bool(config.enable_inverse_refinement),
            "max_refine_materials": int(config.max_refine_materials),
            "max_refine_top_suffixes": int(config.max_refine_top_suffixes),
            "max_refine_bottom_prefixes": int(config.max_refine_bottom_prefixes),
            "refine_bottom_neighbors": int(config.refine_bottom_neighbors),
        },
    }


def _candidate_cache_parameters(
    materials: list[MaterialParams], layer_count: int, layer_height_mm: float,
    substrate: str, candidate_budget: int,
    config: MaterialCandidateCacheConfig | None = None,
) -> dict[str, Any]:
    effective_config = config or MaterialCandidateCacheConfig.persisted_for_budget(
        candidate_budget
    )
    return {
        "schema_version": HYBRID_CANDIDATE_SCHEMA_VERSION,
        "algorithm_version": HYBRID_CANDIDATE_ALGORITHM_VERSION,
        "mode": "candidate_hybrid",
        "canonical_materials": describe_palette(materials),
        "layer_count": int(layer_count),
        "layer_height_mm": float(layer_height_mm),
        "substrate": str(substrate),
        "candidate_budget": int(candidate_budget),
        **_candidate_configuration(effective_config),
        # Only deep stacks carry this key so existing <=10-layer cache paths
        # (and their on-disk files) stay byte-identical.
        # 仅深叠层写入该键，保持 <=10 层既有缓存路径不变。
        **(
            {
                "layer_dp": {
                    "state_cell_lab": float(effective_config.layer_dp_state_cell_lab),
                }
            }
            if effective_config.uses_layer_dp(int(layer_count))
            else {}
        ),
    }


def candidate_cache_file_path(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    *,
    candidate_budget: int,
    cache_root: str | Path | None = None,
    config: MaterialCandidateCacheConfig | None = None,
) -> Path:
    """Resolve the canonical ``.npz`` path for a hybrid candidate runtime.
    返回 hybrid candidate runtime 的规范 ``.npz`` 路径。

    Args:
        materials: Material palette. (耗材调色板)
        layer_count: Recipe layer count. (配方层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"`` substrate. (基底)
        candidate_budget: Requested candidate budget. 请求的候选预算。
        cache_root: Optional cache directory override. (可选缓存目录)
        config: Effective candidate settings; defaults to the persisted settings
            for this budget. 有效候选配置；默认使用该预算的持久配置。

    Returns:
        Path: Canonical candidate runtime file path. (规范候选运行时路径)
    """
    directory = default_cache_directory(cache_root)
    expected = _candidate_cache_parameters(
        materials, layer_count, layer_height_mm, substrate, candidate_budget, config
    )
    existing = _find_cache_record(directory, expected)
    return existing or directory / f"candidate-{uuid.uuid4().hex}.npz"


def _substrate_linear(substrate: str) -> np.ndarray:
    normalized = str(substrate).lower()
    if normalized == "white":
        return np.ones(3, dtype=np.float64)
    if normalized == "black":
        return np.zeros(3, dtype=np.float64)
    raise ValueError("substrate must be 'white' or 'black'")


def _predict_candidate_linear(
    *,
    recipes: np.ndarray,
    materials: list[MaterialParams],
    layer_height_mm: float,
    substrate: str,
    batch_recipe_count: int,
) -> np.ndarray:
    affines = _compute_material_affines(materials, float(layer_height_mm))
    output = np.empty((recipes.shape[0], 3), dtype=np.float64)
    substrate_rgb = _substrate_linear(substrate)

    start = 0
    while start < recipes.shape[0]:
        end = min(start + int(batch_recipe_count), recipes.shape[0])
        batch = recipes[start:end].astype(np.int64, copy=False)
        colors = np.repeat(substrate_rgb[None, :], batch.shape[0], axis=0)
        for layer_index in range(batch.shape[1]):
            material_indices = batch[:, layer_index]
            colors = (
                affines.a[material_indices] * colors
                + affines.b[material_indices]
            )
        output[start:end] = colors
        start = end

    return np.clip(output, 0.0, 1.0)


def _predict_candidate_srgb_lab(
    *,
    recipes: np.ndarray,
    materials: list[MaterialParams],
    layer_height_mm: float,
    substrate: str,
) -> tuple[np.ndarray, np.ndarray]:
    affines = _compute_material_affines(materials, float(layer_height_mm))
    substrate_rgb = _substrate_linear(substrate)
    recipe_arr = np.asarray(recipes)
    colors = np.empty((recipe_arr.shape[0], 3), dtype=np.float64)
    colors[:] = substrate_rgb

    for layer_index in range(recipe_arr.shape[1]):
        material_indices = recipe_arr[:, layer_index]
        colors = (
            affines.a[material_indices] * colors
            + affines.b[material_indices]
        )

    achieved_srgb = linear_to_srgb_uint8(np.clip(colors, 0.0, 1.0))
    achieved_lab = rgb_to_lab(achieved_srgb).astype(np.float32, copy=False)
    return achieved_srgb, achieved_lab


def _predict_recipe_batch(
    *,
    recipes: np.ndarray,
    materials: list[MaterialParams],
    layer_height_mm: float,
    substrate: str,
    recipe_dtype_name: str,
) -> CandidatePredictionBatch:
    recipe_dtype = np.dtype(recipe_dtype_name)
    recipe_arr = np.asarray(recipes, dtype=recipe_dtype)
    achieved_srgb, achieved_lab = _predict_candidate_srgb_lab(
        recipes=recipe_arr,
        materials=materials,
        layer_height_mm=float(layer_height_mm),
        substrate=substrate,
    )
    return CandidatePredictionBatch(
        recipes=recipe_arr,
        achieved_srgb=achieved_srgb,
        achieved_lab=achieved_lab,
    )


def _predict_recipe_space_batch(
    *,
    material_count: int,
    layer_count: int,
    start: int,
    count: int,
    materials: list[MaterialParams],
    layer_height_mm: float,
    substrate: str,
    recipe_dtype_name: str,
) -> CandidatePredictionBatch:
    recipe_dtype = np.dtype(recipe_dtype_name)
    recipes = _recipe_space_chunk(
        material_count,
        layer_count,
        start=int(start),
        count=int(count),
        dtype=recipe_dtype,
    )
    achieved_srgb, achieved_lab = _predict_candidate_srgb_lab(
        recipes=recipes,
        materials=materials,
        layer_height_mm=float(layer_height_mm),
        substrate=substrate,
    )
    return CandidatePredictionBatch(
        recipes=recipes,
        achieved_srgb=achieved_srgb,
        achieved_lab=achieved_lab,
    )


def _predict_low_discrepancy_recipe_batch(
    *,
    material_count: int,
    layer_count: int,
    count: int,
    seed: int,
    materials: list[MaterialParams],
    layer_height_mm: float,
    substrate: str,
    recipe_dtype_name: str,
) -> CandidatePredictionBatch:
    recipe_dtype = np.dtype(recipe_dtype_name)
    recipes = _low_discrepancy_recipes(
        material_count=int(material_count),
        layer_count=int(layer_count),
        count=int(count),
        seed=int(seed),
    ).astype(recipe_dtype, copy=False)
    achieved_srgb, achieved_lab = _predict_candidate_srgb_lab(
        recipes=recipes,
        materials=materials,
        layer_height_mm=float(layer_height_mm),
        substrate=substrate,
    )
    return CandidatePredictionBatch(
        recipes=recipes,
        achieved_srgb=achieved_srgb,
        achieved_lab=achieved_lab,
    )


def _anchor_candidate_recipes(
    *,
    material_count: int,
    layer_count: int,
    budget: int,
    recipe_dtype: np.dtype,
) -> np.ndarray:
    pinned = _uniform_recipes(int(material_count), int(layer_count))[: int(budget)]
    ramps = _pair_ramp_recipes(
        material_count=int(material_count),
        layer_count=int(layer_count),
        limit=max(0, int(budget) - pinned.shape[0]),
    )
    anchors = _unique_rows_preserve_order(np.vstack([pinned, ramps]))[: int(budget)]
    return anchors.astype(recipe_dtype, copy=False)


def _chunk_counts(total_count: int, chunk_size: int) -> list[int]:
    remaining = int(total_count)
    counts: list[int] = []
    while remaining > 0:
        count = min(int(chunk_size), remaining)
        counts.append(count)
        remaining -= count
    return counts


def _lab_cell_keys(lab: np.ndarray, grid_resolution: int) -> np.ndarray:
    grid = max(1, int(grid_resolution))
    lab_arr = np.asarray(lab, dtype=np.float64)
    l_idx = np.clip(np.floor(lab_arr[:, 0] / 100.0 * grid), 0, grid - 1)
    a_idx = np.clip(np.floor((lab_arr[:, 1] + 128.0) / 255.0 * grid), 0, grid - 1)
    b_idx = np.clip(np.floor((lab_arr[:, 2] + 128.0) / 255.0 * grid), 0, grid - 1)
    return (
        l_idx.astype(np.int64) * grid * grid
        + a_idx.astype(np.int64) * grid
        + b_idx.astype(np.int64)
    )


def _coverage_selected_recipes(
    *,
    initial: CandidateRecipeBatch,
    materials: list[MaterialParams],
    layer_height_mm: float,
    substrate: str,
    config: MaterialCandidateCacheConfig,
) -> CandidateRecipeBatch:
    budget = int(config.candidate_budget)
    multiplier = max(1, int(config.candidate_pool_multiplier))
    if (
        multiplier <= 1
        or initial.recipes.shape[0] == 0
        or initial.recipes.shape[0] < budget
    ):
        return initial

    selected = np.asarray(initial.recipes, dtype=np.uint16).copy()
    pinned = np.asarray(initial.pinned_mask, dtype=bool).copy()
    selected_linear = _predict_candidate_linear(
        recipes=selected,
        materials=materials,
        layer_height_mm=float(layer_height_mm),
        substrate=substrate,
        batch_recipe_count=int(config.batch_recipe_count),
    )
    selected_lab = rgb_to_lab(linear_to_srgb_uint8(selected_linear)).astype(np.float32)
    cell_keys = _lab_cell_keys(selected_lab, int(config.lab_grid_resolution))
    cell_counts: dict[int, int] = {}
    for key in cell_keys:
        cell_counts[int(key)] = cell_counts.get(int(key), 0) + 1
    seen_cells = set(cell_counts)
    replace_cursor = selected.shape[0] - 1

    def _replaceable_index() -> int | None:
        nonlocal replace_cursor
        count = selected.shape[0]
        for _ in range(count):
            idx = replace_cursor
            replace_cursor = (replace_cursor - 1) % count
            if pinned[idx]:
                continue
            old_key = int(cell_keys[idx])
            if cell_counts.get(old_key, 0) > 1:
                return idx
        for _ in range(count):
            idx = replace_cursor
            replace_cursor = (replace_cursor - 1) % count
            if not pinned[idx]:
                return idx
        return None

    extra_total = max(0, budget * (multiplier - 1))
    scanned = 0
    chunk_size = max(1, min(int(config.batch_recipe_count), budget))
    chunk_index = 0
    while scanned < extra_total:
        count = min(chunk_size, extra_total - scanned)
        chunk = _low_discrepancy_recipes(
            material_count=len(materials),
            layer_count=int(selected.shape[1]),
            count=count,
            seed=int(config.seed) + 10_000 + chunk_index,
        )
        chunk_linear = _predict_candidate_linear(
            recipes=chunk,
            materials=materials,
            layer_height_mm=float(layer_height_mm),
            substrate=substrate,
            batch_recipe_count=int(config.batch_recipe_count),
        )
        chunk_lab = rgb_to_lab(linear_to_srgb_uint8(chunk_linear)).astype(np.float32)
        chunk_cells = _lab_cell_keys(chunk_lab, int(config.lab_grid_resolution))
        for row, key in zip(chunk, chunk_cells, strict=False):
            key_int = int(key)
            if key_int in seen_cells:
                continue
            idx = _replaceable_index()
            if idx is None:
                return CandidateRecipeBatch(recipes=selected, pinned_mask=pinned)
            old_key = int(cell_keys[idx])
            cell_counts[old_key] = max(0, cell_counts.get(old_key, 0) - 1)
            if cell_counts[old_key] == 0:
                seen_cells.discard(old_key)
            selected[idx] = row
            cell_keys[idx] = key_int
            cell_counts[key_int] = cell_counts.get(key_int, 0) + 1
            seen_cells.add(key_int)
        scanned += count
        chunk_index += 1

    return CandidateRecipeBatch(recipes=selected, pinned_mask=pinned)


def _streaming_candidate_selection(
    *,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    config: MaterialCandidateCacheConfig,
    recipe_dtype: np.dtype,
) -> CandidateSelection:
    material_count = len(materials)
    requested_budget = int(config.candidate_budget)
    total_count = _safe_total_count(
        material_count=material_count,
        layer_count=int(layer_count),
        limit=requested_budget + 1,
    )
    budget = min(requested_budget, total_count)
    worker_count = _resolve_candidate_build_worker_count(config.build_worker_count)
    chunk_size = max(1, int(config.batch_recipe_count))
    if total_count <= budget:
        exact_count = int(total_count)
        exact_recipes = np.empty((exact_count, int(layer_count)), dtype=recipe_dtype)
        achieved_srgb = np.empty((exact_count, 3), dtype=np.uint8)
        achieved_lab = np.empty((exact_count, 3), dtype=np.float32)
        pinned_mask = np.zeros(exact_count, dtype=bool)
        counts = _chunk_counts(exact_count, chunk_size)
        starts: list[int] = []
        offset = 0
        for count in counts:
            starts.append(offset)
            offset += int(count)

        if counts:
            max_workers = min(worker_count, len(counts))
            next_chunk_index = 0
            pending: deque[tuple[int, Future[CandidatePredictionBatch]]] = deque()

            def _submit_next(
                executor: ThreadPoolExecutor,
            ) -> None:
                nonlocal next_chunk_index
                if next_chunk_index >= len(counts):
                    return
                chunk_index = next_chunk_index
                next_chunk_index += 1
                start = starts[chunk_index]
                pending.append(
                    (
                        start,
                        executor.submit(
                            _predict_recipe_space_batch,
                            material_count=material_count,
                            layer_count=int(layer_count),
                            start=start,
                            count=counts[chunk_index],
                            materials=materials,
                            layer_height_mm=float(layer_height_mm),
                            substrate=substrate,
                            recipe_dtype_name=recipe_dtype.name,
                        ),
                    )
                )

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                for _ in range(max_workers):
                    _submit_next(executor)
                while pending:
                    start, future = pending.popleft()
                    batch = future.result()
                    end = start + batch.recipes.shape[0]
                    dest = slice(start, end)
                    exact_recipes[dest] = batch.recipes
                    achieved_srgb[dest] = batch.achieved_srgb
                    achieved_lab[dest] = batch.achieved_lab
                    pinned_mask[dest] = np.all(
                        batch.recipes == batch.recipes[:, :1],
                        axis=1,
                    )
                    _submit_next(executor)

        return CandidateSelection(
            recipes=exact_recipes,
            achieved_srgb=achieved_srgb,
            achieved_lab=achieved_lab,
            pinned_mask=pinned_mask,
            worker_count=worker_count,
        )

    selected = np.empty((budget, int(layer_count)), dtype=recipe_dtype)
    selected_srgb = np.empty((budget, 3), dtype=np.uint8)
    selected_lab = np.empty((budget, 3), dtype=np.float32)
    pinned_mask = np.zeros(budget, dtype=bool)
    cell_keys = np.full(budget, -1, dtype=np.int32)
    cell_counts: dict[int, int] = {}
    seen_cells: set[int] = set()
    selected_count = 0
    replace_cursor = budget - 1

    def _record_cell(index: int, key: int) -> None:
        key_int = int(key)
        cell_keys[index] = key_int
        cell_counts[key_int] = cell_counts.get(key_int, 0) + 1
        seen_cells.add(key_int)

    def _replaceable_index() -> int | None:
        nonlocal replace_cursor
        for _ in range(budget):
            idx = replace_cursor
            replace_cursor = (replace_cursor - 1) % budget
            if pinned_mask[idx]:
                continue
            old_key = int(cell_keys[idx])
            if cell_counts.get(old_key, 0) > 1:
                return idx
        for _ in range(budget):
            idx = replace_cursor
            replace_cursor = (replace_cursor - 1) % budget
            if not pinned_mask[idx]:
                return idx
        return None

    def _consume_batch(batch: CandidatePredictionBatch, *, pinned: bool) -> None:
        nonlocal selected_count
        if batch.recipes.shape[0] == 0:
            return
        keys = _lab_cell_keys(batch.achieved_lab, int(config.lab_grid_resolution)).astype(
            np.int32,
            copy=False,
        )
        offset = 0
        if selected_count < budget:
            take = min(budget - selected_count, batch.recipes.shape[0])
            dest = slice(selected_count, selected_count + take)
            selected[dest] = batch.recipes[:take]
            selected_srgb[dest] = batch.achieved_srgb[:take]
            selected_lab[dest] = batch.achieved_lab[:take]
            pinned_mask[dest] = bool(pinned)
            for local_index, key in enumerate(keys[:take]):
                _record_cell(selected_count + local_index, int(key))
            selected_count += take
            offset = take

        if selected_count < budget:
            return
        for local_index in range(offset, batch.recipes.shape[0]):
            key = int(keys[local_index])
            if key in seen_cells:
                continue
            idx = _replaceable_index()
            if idx is None:
                return
            old_key = int(cell_keys[idx])
            cell_counts[old_key] = max(0, cell_counts.get(old_key, 0) - 1)
            if cell_counts[old_key] == 0:
                seen_cells.discard(old_key)
            selected[idx] = batch.recipes[local_index]
            selected_srgb[idx] = batch.achieved_srgb[local_index]
            selected_lab[idx] = batch.achieved_lab[local_index]
            pinned_mask[idx] = False
            _record_cell(idx, key)

    anchors = _anchor_candidate_recipes(
        material_count=material_count,
        layer_count=int(layer_count),
        budget=budget,
        recipe_dtype=recipe_dtype,
    )
    if anchors.shape[0] > 0:
        _consume_batch(
            _predict_recipe_batch(
                recipes=anchors,
                materials=materials,
                layer_height_mm=float(layer_height_mm),
                substrate=substrate,
                recipe_dtype_name=recipe_dtype.name,
            ),
            pinned=True,
        )

    build_info: dict[str, Any] | None = None
    use_layer_dp = config.uses_layer_dp(int(layer_count))
    if use_layer_dp:
        dp_t0 = time.perf_counter()
        dp_result = generate_layer_dp_recipes_cached(
            materials,
            int(layer_count),
            float(layer_height_mm),
            substrate,
            state_cell_lab=float(config.layer_dp_state_cell_lab),
            max_states=max(material_count, budget - selected_count),
            recipe_dtype=recipe_dtype,
        )
        dp_srgb = linear_to_srgb_uint8(dp_result.linear_rgb)
        _consume_batch(
            CandidatePredictionBatch(
                recipes=dp_result.recipes,
                achieved_srgb=dp_srgb,
                achieved_lab=rgb_to_lab(dp_srgb).astype(np.float32, copy=False),
            ),
            pinned=False,
        )
        build_info = {
            **dp_result.metadata(),
            "elapsed_seconds": time.perf_counter() - dp_t0,
        }

    total_stream_count = max(0, budget - selected_count)
    multiplier = max(1, int(config.candidate_pool_multiplier))
    if multiplier > 1 and not use_layer_dp:
        # The DP output already covers the reachable gamut; random
        # oversampling of a deep recipe space would only cost time.
        # DP 已覆盖可达色域，深叠层随机过采样只会浪费时间。
        total_stream_count += budget * (multiplier - 1)

    counts = _chunk_counts(total_stream_count, chunk_size)
    if counts:
        max_workers = min(worker_count, len(counts))
        next_chunk_index = 0
        pending: deque[Future[CandidatePredictionBatch]] = deque()

        def _submit_next(
            executor: ThreadPoolExecutor,
        ) -> None:
            nonlocal next_chunk_index
            if next_chunk_index >= len(counts):
                return
            chunk_index = next_chunk_index
            next_chunk_index += 1
            pending.append(
                executor.submit(
                    _predict_low_discrepancy_recipe_batch,
                    material_count=material_count,
                    layer_count=int(layer_count),
                    count=counts[chunk_index],
                    seed=int(config.seed) + chunk_index,
                    materials=materials,
                    layer_height_mm=float(layer_height_mm),
                    substrate=substrate,
                    recipe_dtype_name=recipe_dtype.name,
                )
            )

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for _ in range(max_workers):
                _submit_next(executor)
            while pending:
                future = pending.popleft()
                _consume_batch(future.result(), pinned=False)
                _submit_next(executor)

    return CandidateSelection(
        recipes=selected[:selected_count].copy(),
        achieved_srgb=selected_srgb[:selected_count].copy(),
        achieved_lab=selected_lab[:selected_count].copy(),
        pinned_mask=pinned_mask[:selected_count].copy(),
        worker_count=worker_count,
        build_info=build_info,
    )


@dataclass
class MaterialCandidateRuntime:
    """Lookup-compatible bounded material runtime.
    与旧求解缓存 ``lookup`` 兼容的有界耗材运行时。

    Attributes:
        candidate_recipes: ``(K, N)`` canonical bottom-to-top recipes.
            (规范耗材顺序下、自底向上的候选配方)
        achieved_srgb: ``(K, 3)`` predicted sRGB colors. (预测 sRGB 颜色)
        achieved_lab: ``(K, 3)`` predicted Lab colors. (预测 Lab 颜色)
        pinned_mask: Rows from deterministic anchors. (确定性锚点行)
        metadata: Runtime metadata and compatibility fields. (运行时元数据)
    """

    candidate_recipes: np.ndarray
    achieved_srgb: np.ndarray
    achieved_lab: np.ndarray
    pinned_mask: np.ndarray
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        self._tree: cKDTree | None = None

    @property
    def mode(self) -> str:
        return "candidate_hybrid"

    @property
    def layer_count(self) -> int:
        return int(self.metadata["layer_count"])

    @property
    def layer_height_mm(self) -> float:
        return float(self.metadata["layer_height_mm"])

    @property
    def substrate(self) -> str:
        return str(self.metadata["substrate"])

    @property
    def cache_id(self) -> str:
        """Return this opaque cache record ID.
        返回不透明缓存记录 ID。
        """
        return str(self.metadata["cache_id"])

    @property
    def palette_hash(self) -> str:
        """Expose the record ID through the historic public API name.
        通过历史公开 API 名返回记录 ID。
        """
        return self.cache_id

    @property
    def grid_resolution(self) -> int:
        return int(self.metadata["grid_resolution"])

    @property
    def valid_cell_count(self) -> int:
        return int(self.candidate_recipes.shape[0])

    def _refinement_config(self) -> MaterialInverseRefinementConfig:
        inverse = self.metadata.get("inverse_refinement") or {}
        return MaterialInverseRefinementConfig(
            enabled=bool(inverse.get("enabled", False)),
            max_refine_materials=int(inverse.get("max_refine_materials", 8)),
            max_refine_top_suffixes=int(
                inverse.get("max_refine_top_suffixes", 32_768)
            ),
            max_refine_bottom_prefixes=int(
                inverse.get("max_refine_bottom_prefixes", 65_536)
            ),
            refine_bottom_neighbors=int(inverse.get("refine_bottom_neighbors", 2)),
            seed=int(self.metadata.get("seed", 0)),
        )

    def _ensure_tree(self) -> cKDTree:
        if self._tree is None:
            self._tree = cKDTree(self.achieved_lab.astype(np.float64, copy=False))
        return self._tree

    def lookup(
        self,
        target_srgb: np.ndarray,
        user_materials: list[MaterialParams],
        *,
        hue_weight: float = 0.0,
        neighbor_coherence: float = 0.5,
        parallelism: int = 1,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Return nearest candidate recipes using the solver-cache tuple shape.
        按旧求解缓存的返回形状返回最近候选配方。

        Args:
            target_srgb: ``(C, 3)`` uint8 target colors. (目标色)
            user_materials: Materials in caller-visible order. (调用方耗材顺序)
            hue_weight: Accepted for API compatibility. (兼容旧接口)
            neighbor_coherence: Accepted for API compatibility. (兼容旧接口)
            parallelism: Maximum independent refinement workers.
                (独立精修 worker 上限)

        Returns:
            tuple[np.ndarray, np.ndarray, np.ndarray]: matched RGB, recipes in
            user order, and CIE76 delta-E. (匹配色、用户顺序配方、Delta-E)
        """
        targets = np.asarray(target_srgb, dtype=np.uint8)
        if targets.ndim != 2 or targets.shape[1] != 3:
            raise ValueError("target_srgb must have shape (C, 3)")
        if targets.shape[0] == 0:
            return (
                np.zeros((0, 3), dtype=np.uint8),
                np.zeros((0, self.layer_count), dtype=np.int32),
                np.zeros((0,), dtype=np.float64),
            )
        if describe_palette(user_materials) != self.metadata["canonical_materials"]:
            raise ValueError("MaterialCandidateRuntime material descriptors mismatch")
        if self.valid_cell_count <= 0:
            raise ValueError("MaterialCandidateRuntime has no candidates")

        target_lab = rgb_to_lab(targets).astype(np.float64, copy=False)
        neighbor_count = min(64, self.valid_cell_count)
        _distances, indices = self._ensure_tree().query(target_lab, k=neighbor_count)
        if neighbor_count == 1:
            indices = indices[:, None]

        candidate_lab = self.achieved_lab[indices].astype(np.float64, copy=False)
        delta = np.linalg.norm(candidate_lab - target_lab[:, None, :], axis=2)
        if hue_weight > 0.0:
            best_offsets = _hue_aware_rerank(
                target_lab,
                candidate_lab,
                delta,
                hue_weight,
            )
        else:
            best_offsets = np.argmin(delta, axis=1)
        best_indices = indices[np.arange(targets.shape[0]), best_offsets]

        matched_rgb = self.achieved_srgb[best_indices].astype(np.uint8, copy=True)
        recipes_canonical = self.candidate_recipes[best_indices].astype(
            np.int32,
            copy=True,
        )
        best_delta = delta[np.arange(targets.shape[0]), best_offsets].astype(
            np.float64,
            copy=False,
        )

        refinement_config = self._refinement_config()
        if refinement_config.enabled:
            canonical_order = canonical_palette_order(user_materials)
            canonical_materials = [user_materials[index] for index in canonical_order]
            refined = refine_material_matches(
                target_srgb=targets,
                baseline_matched_srgb=matched_rgb,
                baseline_recipes=recipes_canonical,
                baseline_delta_e=best_delta,
                materials=canonical_materials,
                layer_count=self.layer_count,
                layer_height_mm=self.layer_height_mm,
                substrate=self.substrate,
                config=refinement_config,
                parallelism=parallelism,
            )
            matched_rgb = refined.matched_srgb
            recipes_canonical = refined.recipes
            best_delta = refined.delta_e

        canonical_to_user = np.asarray(
            canonical_palette_order(user_materials),
            dtype=np.int32,
        )
        recipes_user = canonical_to_user[recipes_canonical].astype(
            np.int32,
            copy=False,
        )
        if neighbor_coherence > 0.0 and targets.shape[0] >= 2:
            coherence_candidate_indices = np.unique(indices.reshape(-1))
            matched_rgb, recipes_user, best_delta = _neighbor_coherence_refine(
                target_lab=target_lab,
                matched_rgb=matched_rgb,
                recipes_user_order=recipes_user,
                delta_e=best_delta,
                all_lab=self.achieved_lab[coherence_candidate_indices].astype(
                    np.float64,
                    copy=False,
                ),
                all_srgb=self.achieved_srgb[coherence_candidate_indices],
                all_recipes=self.candidate_recipes[coherence_candidate_indices],
                user_mapping=canonical_to_user,
                coherence_weight=neighbor_coherence,
                layer_count=self.layer_count,
                uniform_lab=None,
                uniform_srgb=None,
                uniform_recipes=None,
                parallelism=parallelism,
            )
        return matched_rgb, recipes_user, best_delta

    def lookup_top_k(
        self,
        target_srgb: np.ndarray,
        user_materials: list[MaterialParams],
        *,
        top_k: int,
        min_spacing: float,
    ) -> list[ColorSuggestion]:
        """Return distinct candidate-runtime colors closest to one target.
        返回 hybrid runtime 中最接近单一目标色的去重候选。

        Recipes are converted from canonical runtime order back into the
        caller's material order, matching :meth:`lookup` and the legacy
        solver-cache ``lookup_top_k`` contract.
        """
        target_srgb = np.asarray(target_srgb, dtype=np.uint8)
        if target_srgb.shape != (3,):
            raise ValueError(
                f"target_srgb must be shaped (3,), got {target_srgb.shape}"
            )
        if top_k <= 0:
            raise ValueError(f"top_k must be positive, got {top_k}")
        if min_spacing < 0.0:
            raise ValueError(
                f"min_spacing must be non-negative, got {min_spacing}"
            )
        if describe_palette(user_materials) != self.metadata["canonical_materials"]:
            raise ValueError("MaterialCandidateRuntime material descriptors mismatch")
        if self.valid_cell_count <= 0:
            return []

        target_lab = rgb_to_lab(target_srgb.reshape(1, 3))[0].astype(np.float64)
        query_k = min(max(int(top_k) * 8, 64), self.valid_cell_count)
        _distances, nearest_idx = self._ensure_tree().query(target_lab, k=query_k)
        nearest_idx = np.atleast_1d(nearest_idx).astype(np.int64)

        candidate_lab = self.achieved_lab[nearest_idx].astype(np.float64)
        candidate_srgb = self.achieved_srgb[nearest_idx]
        candidate_delta = np.linalg.norm(candidate_lab - target_lab, axis=1)
        order = np.argsort(candidate_delta, kind="stable")

        sorted_lab = candidate_lab[order]
        sorted_srgb = candidate_srgb[order]
        sorted_delta = candidate_delta[order]
        sorted_recipes = self.candidate_recipes[nearest_idx[order]]

        kept_idx = _greedy_lab_spacing_dedup(
            sorted_lab,
            min_spacing=min_spacing,
            limit=int(top_k),
        )
        if kept_idx.size == 0:
            return []

        canonical_to_user = np.asarray(
            canonical_palette_order(user_materials),
            dtype=np.int32,
        )
        suggestions: list[ColorSuggestion] = []
        for i in kept_idx:
            recipe = canonical_to_user[
                sorted_recipes[i].astype(np.int64, copy=False)
            ].astype(np.int32, copy=True)
            suggestions.append(
                ColorSuggestion(
                    matched_rgb=sorted_srgb[i].copy(),
                    recipe=recipe,
                    delta_e=float(sorted_delta[i]),
                )
            )
        return suggestions


@dataclass(frozen=True)
class MaterialCandidateRuntimeMetadata:
    """Metadata-only persisted runtime entry.
    只包含元数据的持久化 runtime 条目。

    This is for lightweight status checks; it must not open the large ``.npz``
    array payload.
    """

    metadata: dict[str, Any]
    cache_file_path: Path
    cache_file_size_bytes: int


def build_material_candidate_runtime(
    *,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    config: MaterialCandidateCacheConfig | None = None,
) -> MaterialCandidateRuntime:
    """Build an in-memory bounded candidate runtime for material matching.
    构建内存中的有界耗材候选匹配运行时。

    Args:
        materials: Material parameters in user order. (用户选择顺序的耗材参数)
        layer_count: Recipe layer count. (配方层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"`` substrate. (基底颜色)
        config: Optional build configuration. (可选构建配置)

    Returns:
        MaterialCandidateRuntime: Lookup-compatible candidate runtime.
            (与 ``lookup`` 契约兼容的候选运行时)
    """
    if not materials:
        raise ValueError("materials must not be empty")
    cfg = config or MaterialCandidateCacheConfig.preview_safe()
    order = canonical_palette_order(materials)
    canonical_materials = [materials[index] for index in order]
    recipe_dtype = _recipe_dtype_for_material_count(len(canonical_materials))
    selection = _streaming_candidate_selection(
        materials=canonical_materials,
        layer_count=int(layer_count),
        layer_height_mm=float(layer_height_mm),
        substrate=str(substrate),
        config=cfg,
        recipe_dtype=recipe_dtype,
    )
    metadata = {
        "mode": "candidate_hybrid",
        "cache_id": uuid.uuid4().hex,
        "layer_count": int(layer_count),
        "layer_height_mm": float(layer_height_mm),
        "substrate": str(substrate),
        "lab_grid_resolution": int(cfg.lab_grid_resolution),
        "candidate_budget": int(cfg.candidate_budget),
        "build_worker_count": int(selection.worker_count),
        "build_mode": "streaming_parallel",
        "recipe_dtype": recipe_dtype.name,
        **_candidate_configuration(cfg),
        "canonical_material_directory_names": [
            str(material.directory_name) for material in canonical_materials
        ],
        "canonical_materials": describe_palette(canonical_materials),
    }
    if cfg.uses_layer_dp(int(layer_count)):
        # ``layer_dp`` must equal the cache-key entry from
        # ``_candidate_cache_parameters`` even when the recipe space was small
        # enough to enumerate exactly; otherwise the saved runtime is never
        # found again. Build stats live separately and only exist for DP runs.
        metadata["layer_dp"] = {"state_cell_lab": float(cfg.layer_dp_state_cell_lab)}
    if selection.build_info is not None:
        metadata["layer_dp_build"] = selection.build_info
    return MaterialCandidateRuntime(
        candidate_recipes=selection.recipes,
        achieved_srgb=selection.achieved_srgb,
        achieved_lab=selection.achieved_lab,
        pinned_mask=selection.pinned_mask,
        metadata=metadata,
    )


def save_material_candidate_runtime(
    runtime: MaterialCandidateRuntime,
    *,
    cache_root: str | Path | None = None,
) -> Path:
    """Persist a hybrid candidate runtime to its canonical file pair.
    将 hybrid candidate runtime 保存到规范 ``.npz`` 与 ``.meta.json`` 文件。

    Args:
        runtime: Runtime to save. (要保存的运行时)
        cache_root: Optional cache directory override. (可选缓存目录)

    Returns:
        Path: Written ``.npz`` path. (写入的 ``.npz`` 路径)
    """
    directory = default_cache_directory(cache_root)
    directory.mkdir(parents=True, exist_ok=True)
    recipes = np.asarray(runtime.candidate_recipes)
    recipe_dtype = "uint8" if int(recipes.max(initial=0)) <= 255 else "uint16"
    recipes_to_save = recipes.astype(recipe_dtype, copy=False)
    metadata = dict(runtime.metadata)
    metadata.update(
        {
            "schema_version": HYBRID_CANDIDATE_SCHEMA_VERSION,
            "algorithm_version": HYBRID_CANDIDATE_ALGORITHM_VERSION,
            "candidate_count": int(runtime.valid_cell_count),
            "recipe_dtype": str(recipes_to_save.dtype),
            "built_at": metadata.get("built_at") or time.strftime(
                "%Y-%m-%dT%H:%M:%SZ",
                time.gmtime(),
            ),
        }
    )

    expected = {key: metadata[key] for key in (
        "schema_version", "algorithm_version", "mode", "canonical_materials",
        "layer_count", "layer_height_mm", "substrate", "candidate_budget",
        "grid_resolution", "candidate_pool_multiplier", "batch_recipe_count",
        "seed", "inverse_refinement",
    )}
    if "layer_dp" in metadata:
        expected["layer_dp"] = metadata["layer_dp"]
    npz_path = _find_cache_record(directory, expected)
    if npz_path is None:
        npz_path = directory / f"candidate-{runtime.cache_id}.npz"
    else:
        stored = json.loads(_candidate_cache_meta_path_for(npz_path).read_text(encoding="utf-8"))
        metadata["cache_id"] = stored["cache_id"]
    meta_path = _candidate_cache_meta_path_for(npz_path)

    tmp_suffix = f".tmp-{os.getpid()}-{uuid.uuid4().hex}"
    tmp_npz = npz_path.with_name(npz_path.name + tmp_suffix)
    tmp_meta = meta_path.with_name(meta_path.name + tmp_suffix)
    try:
        with tmp_npz.open("wb") as handle:
            np.savez_compressed(
                handle,
                candidate_recipes=recipes_to_save,
                achieved_srgb=runtime.achieved_srgb,
                achieved_lab=runtime.achieved_lab,
                pinned_mask=runtime.pinned_mask,
            )
        tmp_meta.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_npz.replace(npz_path)
        tmp_meta.replace(meta_path)
    finally:
        for tmp_path in (tmp_npz, tmp_meta):
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass
    runtime.metadata.update(metadata)
    return npz_path


def _validated_candidate_runtime_metadata(
    metadata: dict[str, Any],
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str,
    candidate_budget: int,
    config: MaterialCandidateCacheConfig | None = None,
) -> dict[str, Any] | None:
    try:
        expected = _candidate_cache_parameters(
            materials, layer_count, layer_height_mm, substrate, candidate_budget, config
        )
        if any(metadata.get(key) != value for key, value in expected.items()):
            return None
    except (TypeError, ValueError):
        return None
    return dict(metadata)


def load_material_candidate_runtime_metadata(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    candidate_budget: int,
    cache_root: str | Path | None = None,
    config: MaterialCandidateCacheConfig | None = None,
) -> MaterialCandidateRuntimeMetadata | None:
    """Load persisted hybrid runtime metadata without opening array payloads.
    只加载持久化 hybrid runtime 元数据，不打开大型数组载荷。

    Args:
        materials: Material palette used to compare effective descriptors. (耗材调色板)
        layer_count: Recipe layer count. (配方层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"`` substrate. (基底)
        candidate_budget: Requested candidate budget. 请求的候选预算。
        cache_root: Optional cache directory override. (可选缓存目录)
        config: Effective candidate settings; defaults to the persisted settings
            for this budget. 有效候选配置；默认使用该预算的持久配置。

    Returns:
        MaterialCandidateRuntimeMetadata | None: Valid metadata entry or
        ``None`` when missing/invalid. (有效元数据条目，或 ``None``)
    """
    npz_path = candidate_cache_file_path(
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        candidate_budget=int(candidate_budget),
        cache_root=cache_root,
        config=config,
    )
    meta_path = _candidate_cache_meta_path_for(npz_path)
    if not npz_path.exists() or not meta_path.exists():
        return None

    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        file_size = npz_path.stat().st_size
    except (OSError, ValueError, json.JSONDecodeError):
        return None

    validated = _validated_candidate_runtime_metadata(
        metadata,
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        candidate_budget,
        config,
    )
    if validated is None:
        return None
    return MaterialCandidateRuntimeMetadata(
        metadata=validated,
        cache_file_path=npz_path,
        cache_file_size_bytes=int(file_size),
    )


def load_material_candidate_runtime(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    candidate_budget: int,
    cache_root: str | Path | None = None,
    config: MaterialCandidateCacheConfig | None = None,
) -> MaterialCandidateRuntime | None:
    """Load a persisted hybrid candidate runtime, returning ``None`` on miss.
    加载持久化 hybrid candidate runtime；不存在或校验失败时返回 ``None``。

    Args:
        materials: Material palette used to compare effective descriptors. (耗材调色板)
        layer_count: Recipe layer count. (配方层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"`` substrate. (基底)
        candidate_budget: Requested candidate budget. 请求的候选预算。
        cache_root: Optional cache directory override. (可选缓存目录)
        config: Effective candidate settings; defaults to the persisted settings
            for this budget. 有效候选配置；默认使用该预算的持久配置。

    Returns:
        MaterialCandidateRuntime | None: Loaded runtime or ``None``.
            (加载的运行时，或 ``None``)
    """
    npz_path = candidate_cache_file_path(
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        candidate_budget=int(candidate_budget),
        cache_root=cache_root,
        config=config,
    )
    meta_path = _candidate_cache_meta_path_for(npz_path)
    if not npz_path.exists() or not meta_path.exists():
        return None

    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None

    metadata = _validated_candidate_runtime_metadata(
        metadata,
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        candidate_budget,
        config,
    )
    if metadata is None:
        return None
    try:
        with np.load(npz_path) as loaded:
            candidate_recipes = loaded["candidate_recipes"]
            if candidate_recipes.dtype not in (np.uint8, np.uint16):
                candidate_recipes = candidate_recipes.astype(np.uint16)
            achieved_srgb = loaded["achieved_srgb"].astype(np.uint8)
            achieved_lab = loaded["achieved_lab"].astype(np.float32)
            pinned_mask = loaded["pinned_mask"].astype(bool)
    except (OSError, ValueError, KeyError):
        return None
    if (
        candidate_recipes.ndim != 2
        or candidate_recipes.shape[1] != int(layer_count)
        or achieved_srgb.shape != (candidate_recipes.shape[0], 3)
        or achieved_lab.shape != (candidate_recipes.shape[0], 3)
        or pinned_mask.shape != (candidate_recipes.shape[0],)
    ):
        return None

    metadata["candidate_count"] = int(candidate_recipes.shape[0])
    return MaterialCandidateRuntime(
        candidate_recipes=candidate_recipes,
        achieved_srgb=achieved_srgb,
        achieved_lab=achieved_lab,
        pinned_mask=pinned_mask,
        metadata=metadata,
    )


def delete_material_candidate_runtime(
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate: str = "white",
    *,
    candidate_budget: int,
    cache_root: str | Path | None = None,
    config: MaterialCandidateCacheConfig | None = None,
) -> bool:
    """Delete one persisted hybrid candidate runtime file pair.
    删除一组持久化 hybrid candidate runtime 文件。

    Args:
        materials: Material palette used to resolve the file path. (耗材调色板)
        layer_count: Recipe layer count. (配方层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"`` substrate. (基底)
        candidate_budget: Requested candidate budget. 请求的候选预算。
        cache_root: Optional cache directory override. (可选缓存目录)
        config: Effective candidate settings; defaults to the persisted settings
            for this budget. 有效候选配置；默认使用该预算的持久配置。

    Returns:
        bool: ``True`` if at least one file was removed. (是否删除了文件)
    """
    npz_path = candidate_cache_file_path(
        materials,
        layer_count,
        layer_height_mm,
        substrate,
        candidate_budget=int(candidate_budget),
        cache_root=cache_root,
        config=config,
    )
    targets = [npz_path, _candidate_cache_meta_path_for(npz_path)]
    deleted = False
    for path in targets:
        try:
            path.unlink()
            deleted = True
        except FileNotFoundError:
            continue
    return deleted
