"""Material color solver — Beer-Lambert beam-search for per-pixel layer recipes.
耗材颜色求解器 — 基于 Beer-Lambert 模型的波束搜索，求解每像素叠层配方。

Given a set of materials (each with fitted E, k, C0 parameters) and a target
layer count, this module solves for the optimal per-pixel layer recipe that
best reproduces a target color.

The solver uses a beam-search strategy: for each unique quantized color, it
explores layer-by-layer expansions of partial recipes, pruning to the top-B
candidates at each step.  This avoids the M^N combinatorial explosion of
exhaustive enumeration while still finding near-optimal solutions.

Public API
----------
- ``MaterialParams``   — dataclass holding Beer-Lambert parameters for one material
- ``forward_model``    — predict linear RGB for a full N-layer recipe
- ``predict_material_recipe_srgb`` — predict canonical rounded sRGB for a recipe
- ``forward_batch_model`` — vectorised per-recipe forward simulation
- ``solve_image_colors`` — solve optimal recipes for a batch of unique colors
- ``solve_image_colors_optimal`` — strict-optimal MITM B&B solver
- ``map_pixels_to_materials`` — map every image pixel to its solved recipe
- ``ColorSuggestion``  — dataclass describing one achievable-color candidate
- ``suggest_colors_for_target`` — rank achievable colors near a target sRGB
- ``find_white_material_index`` — locate the palette's white filament, if any
- ``ensure_not_worse_than_smaller_N`` — guarantee N-layer recipes are not
  worse (in model-ΔE terms) than any smaller-N solution padded with white
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_LAYER_HEIGHTS_MM: tuple[float, ...] = (0.04, 0.08, 0.1)
DEFAULT_LAYER_HEIGHT_MM: float = 0.08
DEFAULT_LAYER_COUNT: int = 5
MIN_LAYER_COUNT: int = 5
MAX_LAYER_COUNT: int = 30
"""Upper bound for printed colour layers. Deep stacks (>10) are served by the
layer-wise DP in :mod:`core.material_layer_dp` through the candidate runtime.
打印叠色层数上限；>10 层由候选运行时内的逐层 DP 求解。"""
MITM_MAX_LAYER_COUNT: int = 10
"""Upper bound for the exhaustive meet-in-the-middle helpers below, whose
cost grows as ``M ** (N / 2)``. 下方 MITM 穷举函数的层数上限（代价随 M**(N/2) 增长）。"""
DEFAULT_BEAM_WIDTH: int = 32


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MaterialParams:
    """Loaded Beer-Lambert parameters for one material.
    单种耗材的 Beer-Lambert 参数。

    Attributes:
        name: Human-readable material name (e.g. "PLA Red"). (耗材名称)
        directory_name: On-disk directory name under ``materials/``. (目录名)
        E: (3,) equilibrium color in linear RGB. (平衡色 linear RGB)
        k: (3,) absorption coefficient per channel. (吸收系数)
        C0_white: (3,) zero-thickness color on white substrate in linear RGB.
            (白底零厚度颜色 linear RGB)
        estimated_rgb: (3,) sRGB uint8 estimated material color for preview.
            (预览用 sRGB uint8 预估耗材颜色)
        material_type: Explicit archive material type, or None when absent.
            (档案明确记录的材料类型，缺失时为 None)
    """

    name: str
    directory_name: str
    E: np.ndarray       # (3,) float64, linear
    k: np.ndarray       # (3,) float64
    C0_white: np.ndarray  # (3,) float64, linear
    estimated_rgb: np.ndarray  # (3,) uint8
    material_type: str | None = None


# ---------------------------------------------------------------------------
# sRGB ↔ linear helpers
# ---------------------------------------------------------------------------


def srgb_to_linear(arr: np.ndarray) -> np.ndarray:
    """Convert sRGB uint8 to linear float64 in [0, 1].
    将 sRGB uint8 转换为 [0, 1] 范围的线性 float64。
    """
    c = arr.astype(np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb_float(arr: np.ndarray) -> np.ndarray:
    """Convert linear float64 to sRGB float64 in [0, 1].
    将线性 float64 转换为 [0, 1] 范围的 sRGB float64。
    """
    c = np.clip(arr.astype(np.float64), 0.0, 1.0)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * np.power(c, 1.0 / 2.4) - 0.055)


def linear_to_srgb_uint8(arr: np.ndarray) -> np.ndarray:
    """Convert linear float64 to sRGB uint8.
    将线性 float64 转换为 sRGB uint8。
    """
    srgb = linear_to_srgb_float(arr)
    return np.clip(np.round(srgb * 255.0), 0, 255).astype(np.uint8)


def rgb_to_lab(srgb_uint8: np.ndarray) -> np.ndarray:
    """Convert sRGB uint8 array (N, 3) to CIE Lab float64 (N, 3).
    将 sRGB uint8 (N, 3) 转换为 CIE Lab float64 (N, 3)。
    """
    srgb_f32 = srgb_uint8.astype(np.float32) / 255.0
    lab = cv2.cvtColor(srgb_f32.reshape(-1, 1, 3), cv2.COLOR_RGB2LAB)
    return lab.reshape(-1, 3).astype(np.float64)


# ---------------------------------------------------------------------------
# Beer-Lambert forward model
# ---------------------------------------------------------------------------


def beer_lambert_layer(
    C_prev: np.ndarray,
    E: np.ndarray,
    k: np.ndarray,
    thickness_mm: float,
) -> np.ndarray:
    """Apply one Beer-Lambert layer on top of the current color.
    在当前颜色上叠加一层 Beer-Lambert 耗材。

    C(t) = E + (C_prev − E) × exp(−k × t)

    Args:
        C_prev: (..., 3) current color in linear RGB. (当前线性 RGB 颜色)
        E: (3,) equilibrium color. (平衡色)
        k: (3,) absorption coefficient. (吸收系数)
        thickness_mm: Layer thickness in mm. (层厚度 mm)

    Returns:
        (..., 3) new color after the layer. (叠层后的新颜色)
    """
    return E + (C_prev - E) * np.exp(-k * thickness_mm)


def forward_model(
    recipe: np.ndarray,
    materials: list[MaterialParams],
    layer_height_mm: float,
    substrate_linear: np.ndarray | None = None,
) -> np.ndarray:
    """Compute the predicted linear RGB for a full N-layer recipe.
    正向计算 N 层配方的预测线性 RGB。

    Args:
        recipe: (N,) int array of material indices (0-based). (材料索引数组)
        materials: List of available materials. (耗材列表)
        layer_height_mm: Thickness of each layer in mm. (每层厚度 mm)
        substrate_linear: (3,) substrate color in linear RGB; defaults to white.
            (基底颜色 linear RGB，默认白)

    Returns:
        (3,) predicted color in linear RGB. (预测颜色 linear RGB)
    """
    if substrate_linear is None:
        substrate_linear = np.ones(3, dtype=np.float64)
    C = substrate_linear.copy()
    for layer_idx in range(len(recipe)):
        mat_id = int(recipe[layer_idx])
        mat = materials[mat_id]
        C = beer_lambert_layer(C, mat.E, mat.k, layer_height_mm)
    return C


def predict_material_recipe_srgb(
    recipe: np.ndarray,
    materials: list[MaterialParams],
    layer_height_mm: float,
    substrate: str = "white",
) -> np.ndarray:
    """Predict the canonical rounded sRGB colour for a material recipe.
    预测耗材配方的统一取整 sRGB 颜色。

    Args:
        recipe: Material indices in bottom-to-top print order.
            (按从基底到观赏面的打印顺序排列的耗材索引)
        materials: Available material parameters. (可用耗材参数)
        layer_height_mm: Thickness of each layer in millimetres. (每层厚度，毫米)
        substrate: Physical substrate colour, ``"white"`` or ``"black"``.
            (物理基底颜色，仅支持 ``"white"`` 或 ``"black"``)

    Returns:
        A ``(3,)`` uint8 array containing rounded sRGB values.
        (包含取整后 sRGB 值的 ``(3,)`` uint8 数组)

    Raises:
        ValueError: If ``substrate`` is unsupported. (基底类型不受支持)
    """
    if substrate == "white":
        substrate_linear = np.ones(3, dtype=np.float64)
    elif substrate == "black":
        substrate_linear = np.zeros(3, dtype=np.float64)
    else:
        raise ValueError(f"Unsupported substrate: {substrate}")

    predicted_linear = forward_model(
        np.asarray(recipe, dtype=np.int32),
        materials,
        layer_height_mm,
        substrate_linear,
    )
    return linear_to_srgb_uint8(predicted_linear).reshape(3)


# ---------------------------------------------------------------------------
# Beam-search solver
# ---------------------------------------------------------------------------


def _solve_single_color_beam(
    target_lab: np.ndarray,
    target_linear: np.ndarray,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float,
    substrate_linear: np.ndarray,
    beam_width: int,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Beam-search solver for one target color.
    单色波束搜索求解器。

    对一个目标颜色，逐层展开候选配方，每步保留 ΔE 最小的 beam_width 个候选。

    Args:
        target_lab: (3,) target color in CIE Lab. (目标 Lab 颜色)
        target_linear: (3,) target color in linear RGB. (目标线性 RGB)
        materials: Available materials. (可用耗材列表)
        layer_count: Number of layers. (层数)
        layer_height_mm: Thickness per layer in mm. (每层厚度 mm)
        substrate_linear: (3,) substrate color in linear RGB. (基底颜色)
        beam_width: Max candidates to keep per step. (每步最大候选数)

    Returns:
        (recipe, predicted_linear, delta_e): Best recipe found.
            recipe: (N,) int32 material indices.
            predicted_linear: (3,) predicted linear RGB.
            delta_e: float ΔE (CIE76) between target and prediction.
    """
    M = len(materials)

    # Pre-extract E and k arrays for vectorized computation: (M, 3) each
    all_E = np.stack([m.E for m in materials], axis=0)     # (M, 3)
    all_k = np.stack([m.k for m in materials], axis=0)     # (M, 3)

    # Initialize beam: one candidate starting from substrate
    # Each candidate: (current_linear (3,), partial_recipe list[int])
    beam_colors = substrate_linear.reshape(1, 3).copy()  # (B, 3)
    beam_recipes: list[list[int]] = [[]]

    for _layer in range(layer_count):
        B = beam_colors.shape[0]
        # Expand: each of B candidates × M materials → B*M candidates
        # beam_colors: (B, 3) → repeat for M → (B*M, 3)
        expanded_colors = np.repeat(beam_colors, M, axis=0)  # (B*M, 3)

        # Tile E and k for each beam entry
        tiled_E = np.tile(all_E, (B, 1))  # (B*M, 3)
        tiled_k = np.tile(all_k, (B, 1))  # (B*M, 3)

        # Vectorized Beer-Lambert
        new_colors = tiled_E + (expanded_colors - tiled_E) * np.exp(-tiled_k * layer_height_mm)

        # Compute ΔE in Lab space for scoring
        new_srgb = linear_to_srgb_uint8(new_colors)
        new_lab = rgb_to_lab(new_srgb)
        delta_e = np.linalg.norm(new_lab - target_lab.reshape(1, 3), axis=1)  # (B*M,)

        # Build expanded recipe lists
        mat_ids = np.tile(np.arange(M), B)  # (B*M,)
        expanded_recipes = []
        for b_idx in range(B):
            for m_idx in range(M):
                expanded_recipes.append(beam_recipes[b_idx] + [m_idx])

        # Prune to top beam_width
        if len(delta_e) <= beam_width:
            keep = np.arange(len(delta_e))
        else:
            keep = np.argpartition(delta_e, beam_width)[:beam_width]
            # Sort the kept indices for deterministic ordering
            keep = keep[np.argsort(delta_e[keep])]

        beam_colors = new_colors[keep]
        beam_recipes = [expanded_recipes[i] for i in keep]

    # Final selection: best ΔE
    final_srgb = linear_to_srgb_uint8(beam_colors)
    final_lab = rgb_to_lab(final_srgb)
    final_delta_e = np.linalg.norm(final_lab - target_lab.reshape(1, 3), axis=1)
    best_idx = int(np.argmin(final_delta_e))

    best_recipe = np.asarray(beam_recipes[best_idx], dtype=np.int32)
    best_color = beam_colors[best_idx]
    best_de = float(final_delta_e[best_idx])
    return best_recipe, best_color, best_de


def solve_image_colors(
    unique_colors_srgb: np.ndarray,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float = DEFAULT_LAYER_HEIGHT_MM,
    substrate: str = "white",
    beam_width: int = DEFAULT_BEAM_WIDTH,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Solve optimal recipes for a set of unique quantized colors.
    对一组量化后的唯一颜色求解最优配方。

    For each unique color, runs a beam-search through the space of possible
    N-layer recipes and returns the best match (lowest CIE76 ΔE).

    Args:
        unique_colors_srgb: (C, 3) uint8 unique colors. (唯一颜色 sRGB)
        materials: List of selected materials. (已选耗材列表)
        layer_count: Number of layers per pixel (5-10). (每像素层数)
        layer_height_mm: Thickness of each layer in mm. (每层厚度 mm)
        substrate: Substrate type, "white" or "black". (基底类型)
        beam_width: Beam search width. (波束宽度)

    Returns:
        matched_rgb: (C, 3) uint8 — predicted sRGB for each unique color.
            (每个唯一色的预测 sRGB)
        recipes: (C, N) int32 — material index per layer for each color.
            (每个唯一色的配方)
        delta_e: (C,) float64 — ΔE for each color. (每个唯一色的 ΔE)
    """
    if layer_count < MIN_LAYER_COUNT or layer_count > MAX_LAYER_COUNT:
        raise ValueError(
            f"layer_count must be {MIN_LAYER_COUNT}-{MAX_LAYER_COUNT}, got {layer_count}"
        )
    if not materials:
        raise ValueError("At least one material must be provided")
    if layer_height_mm not in ALLOWED_LAYER_HEIGHTS_MM:
        raise ValueError(
            f"layer_height_mm must be one of {ALLOWED_LAYER_HEIGHTS_MM}, got {layer_height_mm}"
        )

    C_count = unique_colors_srgb.shape[0]
    if C_count == 0:
        return (
            np.zeros((0, 3), dtype=np.uint8),
            np.zeros((0, layer_count), dtype=np.int32),
            np.zeros((0,), dtype=np.float64),
        )

    # Substrate color in linear RGB
    if substrate == "white":
        substrate_linear = np.ones(3, dtype=np.float64)
    elif substrate == "black":
        substrate_linear = np.zeros(3, dtype=np.float64)
    else:
        substrate_linear = np.ones(3, dtype=np.float64)

    # Pre-compute Lab for all target colors
    target_labs = rgb_to_lab(unique_colors_srgb)
    target_linears = srgb_to_linear(unique_colors_srgb)

    matched_rgb = np.zeros((C_count, 3), dtype=np.uint8)
    recipes = np.zeros((C_count, layer_count), dtype=np.int32)
    delta_e_arr = np.zeros(C_count, dtype=np.float64)

    _log.info(
        "Solving %d unique colors with %d materials, %d layers, "
        "%.2f mm/layer, beam=%d",
        C_count,
        len(materials),
        layer_count,
        layer_height_mm,
        beam_width,
        extra={
            "event": "material_solver_started",
            "unique_color_count": C_count,
            "material_count": len(materials),
            "layer_count": layer_count,
            "layer_height_mm": layer_height_mm,
            "beam_width": beam_width,
        },
    )

    for i in range(C_count):
        recipe, pred_linear, de = _solve_single_color_beam(
            target_lab=target_labs[i],
            target_linear=target_linears[i],
            materials=materials,
            layer_count=layer_count,
            layer_height_mm=layer_height_mm,
            substrate_linear=substrate_linear,
            beam_width=beam_width,
        )
        matched_rgb[i] = linear_to_srgb_uint8(pred_linear.reshape(1, 3))[0]
        recipes[i] = recipe
        delta_e_arr[i] = de

    mean_de = float(np.mean(delta_e_arr)) if C_count > 0 else 0.0
    max_de = float(np.max(delta_e_arr)) if C_count > 0 else 0.0
    _log.info(
        "Material solver completed: mean_ΔE=%.2f, max_ΔE=%.2f",
        mean_de,
        max_de,
        extra={
            "event": "material_solver_done",
            "mean_delta_e": mean_de,
            "max_delta_e": max_de,
        },
    )
    return matched_rgb, recipes, delta_e_arr


# ---------------------------------------------------------------------------
# Pixel mapping (replicates the role of map_pixels_to_lut for material mode)
# ---------------------------------------------------------------------------


def map_pixels_to_materials(
    quantized_image: np.ndarray,
    unique_colors: np.ndarray,
    matched_rgb_unique: np.ndarray,
    recipes_unique: np.ndarray,
    target_h: int,
    target_w: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Map all image pixels to their solved recipes.
    将图像所有像素映射到求解的配方。

    Uses integer-code lookup (R*65536 + G*256 + B) for fast matching between
    the quantized image and the unique-color solution table.

    Args:
        quantized_image: (H, W, 3) uint8 quantized image. (量化图像)
        unique_colors: (C, 3) uint8 unique colors. (唯一颜色)
        matched_rgb_unique: (C, 3) uint8 matched colors from solver. (求解匹配色)
        recipes_unique: (C, N) int32 recipes from solver. (求解配方)
        target_h: Image height. (图像高度)
        target_w: Image width. (图像宽度)

    Returns:
        matched_rgb: (H, W, 3) uint8 matched RGB image. (匹配 RGB 图像)
        material_matrix: (H, W, N) int32 material matrix. (材料矩阵)
    """
    layer_count = recipes_unique.shape[1]

    unique_codes = (
        unique_colors[:, 0].astype(np.int32) * 65536
        + unique_colors[:, 1].astype(np.int32) * 256
        + unique_colors[:, 2].astype(np.int32)
    )
    sort_idx = np.argsort(unique_codes)
    sorted_codes = unique_codes[sort_idx]
    sorted_matched = matched_rgb_unique[sort_idx]
    sorted_recipes = recipes_unique[sort_idx]

    flat_quantized = quantized_image.reshape(-1, 3)
    pixel_codes = (
        flat_quantized[:, 0].astype(np.int32) * 65536
        + flat_quantized[:, 1].astype(np.int32) * 256
        + flat_quantized[:, 2].astype(np.int32)
    )
    insert_positions = np.searchsorted(sorted_codes, pixel_codes)
    matched_rgb = sorted_matched[insert_positions].reshape(target_h, target_w, 3)
    material_matrix = sorted_recipes[insert_positions].reshape(target_h, target_w, layer_count)

    return matched_rgb, material_matrix


# ---------------------------------------------------------------------------
# Optimal MITM B&B solver — guaranteed-optimal replacement for beam search
# 最优 MITM 分支定界求解器 —— 波束搜索的全局最优替代方案
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _MaterialAffineSet:
    """Per-material affine parameters for a fixed layer height.
    在给定层厚下每种耗材的仿射参数。

    A single Beer-Lambert layer applied on top of a color ``C_prev`` is:
        ``C_new = a * C_prev + b`` where ``a = exp(-k * t)`` and ``b = E * (1 - a)``.

    Composing layers bottom-to-top keeps the map affine: any recipe of length N
    is a single 3-channel affine ``C_final = α_total * C_0 + β_total`` applied
    to the substrate ``C_0``. This factorization is what makes meet-in-the-middle
    enumeration tractable for large N.

    Attributes:
        a: (M, 3) per-channel transmittance factor. (每通道透光系数)
        b: (M, 3) per-channel emission contribution. (每通道发色贡献)
    """

    a: np.ndarray  # (M, 3) float64
    b: np.ndarray  # (M, 3) float64


def _compute_material_affines(
    materials: list[MaterialParams],
    layer_height_mm: float,
) -> _MaterialAffineSet:
    """Pre-compute per-material affine parameters ``(a, b)`` for a layer height.
    预计算每种耗材在给定层厚下的 Beer-Lambert 仿射参数 ``(a, b)``。

    Args:
        materials: Available materials. (可用耗材列表)
        layer_height_mm: Thickness of one layer in mm. (单层厚度 mm)

    Returns:
        _MaterialAffineSet with (M, 3) ``a`` and ``b`` arrays.
    """
    k_stack = np.stack([m.k for m in materials], axis=0).astype(np.float64)
    e_stack = np.stack([m.E for m in materials], axis=0).astype(np.float64)
    a = np.exp(-k_stack * float(layer_height_mm))
    b = e_stack * (1.0 - a)
    return _MaterialAffineSet(a=a, b=b)


def _enumerate_cumulative_affines(
    affines: _MaterialAffineSet,
    depth: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Enumerate every ``M**depth`` ordered layer sequence and its cumulative affine.
    枚举所有 ``M**depth`` 种有序层序列及其累积仿射参数。

    The layer sequence is applied bottom-to-top: the cumulative affine after
    adding layer ``i`` on top of a partial ``(α, β)`` is:
        ``α_new = a_i * α``
        ``β_new = a_i * β + b_i``

    Args:
        affines: Per-material affines. (每耗材仿射参数)
        depth: Number of layers to enumerate. ``0`` yields the identity row.
            (枚举层数，0 表示恒等映射)

    Returns:
        alpha: (M**depth, 3) cumulative transmittance. (累积透光系数)
        beta: (M**depth, 3) cumulative emission. (累积发色量)
        recipes: (M**depth, depth) int8 material indices. ``recipes[:, 0]``
            is the bottom layer (applied first); ``recipes[:, -1]`` is the top.
            (层序配方：第 0 列为底层、最后一列为顶层)
    """
    if depth < 0:
        raise ValueError(f"depth must be non-negative, got {depth}")
    M = affines.a.shape[0]
    # Identity row: one empty recipe with α=1, β=0.
    alpha = np.ones((1, 3), dtype=np.float64)
    beta = np.zeros((1, 3), dtype=np.float64)
    recipes = np.empty((1, 0), dtype=np.int8)

    for layer_pos in range(depth):
        K = alpha.shape[0]
        # Each of K current states expands into M new states (one per material).
        # Broadcasting pattern: state[k] repeated M times, material[m] tiled K times.
        state_alpha = np.repeat(alpha, M, axis=0)            # (K*M, 3)
        state_beta = np.repeat(beta, M, axis=0)              # (K*M, 3)
        mat_a = np.tile(affines.a, (K, 1))                   # (K*M, 3)
        mat_b = np.tile(affines.b, (K, 1))                   # (K*M, 3)

        alpha = mat_a * state_alpha                           # (K*M, 3)
        beta = mat_a * state_beta + mat_b                     # (K*M, 3)

        # Extend recipes: append layer index as the new top-most column.
        old_recipes = np.repeat(recipes, M, axis=0)           # (K*M, layer_pos)
        new_col = np.tile(np.arange(M, dtype=np.int8), K).reshape(-1, 1)
        recipes = np.concatenate([old_recipes, new_col], axis=1)

    return alpha, beta, recipes


def _pick_mitm_split(layer_count: int, num_materials: int) -> tuple[int, int]:
    """Choose ``(bottom_depth, top_depth)`` for MITM enumeration.
    选择 MITM 分裂比例 ``(底层深度, 顶层深度)``。

    Goal: keep both halves' enumeration count (M**depth) close to sqrt(M**N),
    while deliberately putting the larger half on the TOP side so that the
    transmittance-cutoff pruning (which lives on top suffixes) is more effective.
    When ``layer_count`` is odd the extra layer goes to the top half.

    For very small palettes / layer counts the split may be unbalanced
    (``bottom_depth == 0``); the solver handles that case naturally.
    """
    if layer_count <= 0:
        return (0, 0)
    top_depth = (layer_count + 1) // 2
    bottom_depth = layer_count - top_depth
    # Cap bottom_depth so the bottom prefix table stays modest even for very
    # opaque palettes (rare here since both halves are already balanced).
    return (bottom_depth, top_depth)


# Physical noise floor in linear RGB: the maximum perturbation that a
# saturated-top recipe's canonical-bottom approximation can introduce. At this
# level, the amplified Lab ΔE stays well below 1 for typical gamuts, so the
# overall solver remains "optimal within sub-ΔE noise".
_LINEAR_RGB_NOISE_FLOOR: float = 0.004


def _resolve_alpha_cutoff(
    affines: _MaterialAffineSet,
    alpha_cutoff: float | None,
    buffer_layers: int,
) -> float:
    """Resolve the numerical transmittance cutoff.
    计算数值透光度阈值。

    The cutoff is the max α (top-half transmittance product, per channel) at
    which the solver treats the bottom half as "don't-care" (canonical fill).
    Swapping bottoms can perturb the final linear RGB by up to ``α_top × 1``,
    so an α_top below ``cutoff`` bounds the perturbation to ``cutoff``.

    Precedence:
      1. Explicit ``alpha_cutoff`` always wins (including ``0.0`` for strict).
      2. ``buffer_layers <= 0``: cutoff is ``0`` — strict exhaustive search.
      3. ``buffer_layers >= 1``: cutoff = ``NOISE_FLOOR * buffer_layers``.
         The noise floor is a fixed linear-RGB tolerance (~0.004, sub-ΔE);
         each extra buffer layer linearly relaxes the tolerance, trading a
         small ΔE drift for faster enumeration.

    Note: The default is ``buffer_layers=0`` (strict); callers who explicitly
    ask for slack can pass higher values to prune aggressively.
    """
    if alpha_cutoff is not None:
        if alpha_cutoff < 0.0:
            raise ValueError(f"alpha_cutoff must be >= 0, got {alpha_cutoff}")
        return float(alpha_cutoff)
    if buffer_layers <= 0:
        return 0.0
    return _LINEAR_RGB_NOISE_FLOOR * int(buffer_layers)


def solve_image_colors_optimal(
    unique_colors_srgb: np.ndarray,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float = DEFAULT_LAYER_HEIGHT_MM,
    substrate: str = "white",
    *,
    alpha_cutoff: float | None = None,
    buffer_layers: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Guaranteed-optimal MITM B&B solver for a batch of unique target colors.
    批量唯一色的保证最优 MITM 分支定界求解器。

    Splits the N-layer recipe into a bottom prefix and top suffix, enumerates
    both halves into cumulative-affine tables, and evaluates every composition
    ``final = α_top * (α_bot * C_0 + β_bot) + β_top``.  Optionally applies a
    transmittance cutoff on the top suffix's α product to skip the full
    bottom-sweep for "saturated" tops whose bottom contribution is provably
    below ``alpha_cutoff`` in linear RGB.

    With the default ``buffer_layers=0`` the cutoff is ``0``: the search is a
    strict exhaustive MITM enumeration and the result is globally optimal.
    Callers who need to trade a small ΔE for speed can set ``buffer_layers>=1``
    (each unit relaxes the cutoff by one linear-RGB noise floor ≈ 0.004, so
    ``buffer_layers=1`` keeps the ΔE regression typically under 1).

    Args:
        unique_colors_srgb: (C, 3) uint8 unique target colors. (目标唯一色)
        materials: Selected materials. (已选耗材)
        layer_count: Number of layers per pixel (5-10). (每像素层数)
        layer_height_mm: Thickness of each layer in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"``. (基底类型)
        alpha_cutoff: Optional explicit numeric cutoff on ``max(α_top)``.
            When ``None`` the cutoff is derived from ``buffer_layers``.
            (透光度数值阈值，默认由 buffer_layers 推导)
        buffer_layers: Approximation slack expressed in "invisible layer count".
            ``0`` (default) gives strict exhaustive — globally optimal.
            ``>=1`` relaxes the cutoff for faster solves; every unit allows
            ~one noise-floor (~0.004 linear RGB) of bottom-swap drift.
            (允许的"不可见层"数量；0 表示严格穷举并保证最优)

    Returns:
        matched_rgb: (C, 3) uint8 predicted sRGB for each target. (预测 sRGB)
        recipes: (C, N) int32 material index per layer; column 0 is bottom,
            column ``N-1`` is top. (配方：第 0 列为底层、最后一列为顶层)
        delta_e: (C,) float64 CIE76 ΔE between target and prediction.
            (CIE76 ΔE)
    """
    if layer_count < MIN_LAYER_COUNT or layer_count > MITM_MAX_LAYER_COUNT:
        raise ValueError(
            f"layer_count must be {MIN_LAYER_COUNT}-{MITM_MAX_LAYER_COUNT}, got {layer_count} "
            "(deeper stacks: use the material candidate runtime)"
        )
    if not materials:
        raise ValueError("At least one material must be provided (materials is empty)")
    if layer_height_mm not in ALLOWED_LAYER_HEIGHTS_MM:
        raise ValueError(
            f"layer_height_mm must be one of {ALLOWED_LAYER_HEIGHTS_MM}, got {layer_height_mm}"
        )

    C_count = unique_colors_srgb.shape[0]
    if C_count == 0:
        return (
            np.zeros((0, 3), dtype=np.uint8),
            np.zeros((0, layer_count), dtype=np.int32),
            np.zeros((0,), dtype=np.float64),
        )

    # ---- Memory feasibility guard ----
    # The MITM inner loop allocates a ``delta_e`` array of shape
    # ``(C, chunk, K_bot)`` float64.  For large palettes at high layer
    # counts (e.g. M=8, N=10 → K_bot=32768) the array can exceed
    # available RAM (≈ 2.75 GiB for C=256) and freeze the worker.
    # Fail fast with a clear message so callers can fall back to the
    # pre-built cache instead of silently hanging.
    M = len(materials)
    _bot_d, _top_d = _pick_mitm_split(layer_count, M)
    _k_bot_est = M ** _bot_d
    _k_top_est = M ** _top_d
    _chunk_est = min(_k_top_est, max(1, (32 * 1024 * 1024) // max(1, _k_bot_est * 24)))
    _peak_est = C_count * _chunk_est * _k_bot_est * 8
    _SOLVER_MEM_LIMIT = 1024 * 1024 * 1024  # 1 GiB
    if _peak_est > _SOLVER_MEM_LIMIT:
        raise MemoryError(
            f"MITM solver would allocate ~{_peak_est // (1024**2)} MiB for "
            f"delta_e (M={M}, N={layer_count}, C={C_count}, "
            f"K_bot={_k_bot_est}, chunk={_chunk_est}). "
            f"Use a pre-built MaterialSolverCache instead of the on-the-fly "
            f"solver for this palette size."
        )

    substrate_linear = (
        np.zeros(3, dtype=np.float64)
        if substrate == "black"
        else np.ones(3, dtype=np.float64)
    )

    target_labs = rgb_to_lab(unique_colors_srgb)                     # (C, 3) float64
    affines = _compute_material_affines(materials, layer_height_mm)
    cutoff = _resolve_alpha_cutoff(affines, alpha_cutoff, buffer_layers)

    bottom_depth, top_depth = _pick_mitm_split(layer_count, M)

    # Bottom half: enumerate prefixes and convert to colors applied on substrate.
    bot_alpha, bot_beta, bot_recipes = _enumerate_cumulative_affines(
        affines, bottom_depth
    )
    bot_colors = bot_alpha * substrate_linear + bot_beta             # (K_bot, 3)

    # Top half: enumerate suffixes; they act on the bottom color via affine.
    top_alpha, top_beta, top_recipes = _enumerate_cumulative_affines(
        affines, top_depth
    )

    # Partition top suffixes by transmittance cutoff.
    top_alpha_max = top_alpha.max(axis=1)                            # (K_top,)
    saturated_mask = top_alpha_max < cutoff
    sat_alpha = top_alpha[saturated_mask]
    sat_beta = top_beta[saturated_mask]
    sat_recipes_top = top_recipes[saturated_mask]
    act_alpha = top_alpha[~saturated_mask]
    act_beta = top_beta[~saturated_mask]
    act_recipes_top = top_recipes[~saturated_mask]

    # Canonical bottom used for saturated tops (any bottom within noise tolerance).
    canonical_bot_color = bot_colors[0]                              # (3,)
    canonical_bot_recipe = bot_recipes[0]                            # (bottom_depth,)

    best_de = np.full(C_count, np.inf, dtype=np.float64)
    best_pred_linear = np.zeros((C_count, 3), dtype=np.float64)
    best_recipes = np.zeros((C_count, layer_count), dtype=np.int32)

    # -- Saturated tops pass: bottom is irrelevant within cutoff noise. --------
    if sat_alpha.shape[0] > 0:
        sat_final_linear = sat_alpha * canonical_bot_color + sat_beta   # (K_sat, 3)
        sat_final_srgb = linear_to_srgb_uint8(sat_final_linear)
        sat_final_lab = rgb_to_lab(sat_final_srgb)                      # (K_sat, 3)
        # Per-target ΔE: (C, K_sat).
        sat_delta_e = np.linalg.norm(
            sat_final_lab[None, :, :] - target_labs[:, None, :], axis=2
        )
        sat_best_idx = np.argmin(sat_delta_e, axis=1)                   # (C,)
        sat_best_de = sat_delta_e[np.arange(C_count), sat_best_idx]     # (C,)
        update_mask = sat_best_de < best_de
        best_de[update_mask] = sat_best_de[update_mask]
        # Update predicted and recipe for improved targets.
        for i in np.where(update_mask)[0]:
            j = int(sat_best_idx[i])
            best_pred_linear[i] = sat_final_linear[j]
            if bottom_depth > 0:
                best_recipes[i, :bottom_depth] = canonical_bot_recipe
            best_recipes[i, bottom_depth:] = sat_recipes_top[j]

    # -- Active tops pass: chunked full sweep over every bottom. ---------------
    K_bot = bot_colors.shape[0]
    K_act = act_alpha.shape[0]
    if K_act > 0 and K_bot > 0:
        # Chunk size balances memory vs. call overhead. Per-chunk memory is
        # roughly chunk * K_bot * 24 bytes for the linear RGB block; 32 MiB target.
        max_chunk_bytes = 32 * 1024 * 1024
        chunk = max(1, min(K_act, max_chunk_bytes // max(1, K_bot * 24)))
        for chunk_start in range(0, K_act, chunk):
            chunk_end = min(chunk_start + chunk, K_act)
            sub = chunk_end - chunk_start
            chunk_alpha = act_alpha[chunk_start:chunk_end]               # (sub, 3)
            chunk_beta = act_beta[chunk_start:chunk_end]                 # (sub, 3)
            chunk_recipes = act_recipes_top[chunk_start:chunk_end]       # (sub, top_depth)
            # final_linear: (sub, K_bot, 3) = α*bot + β broadcast.
            final_linear = (
                chunk_alpha[:, None, :] * bot_colors[None, :, :]
                + chunk_beta[:, None, :]
            )
            flat_linear = final_linear.reshape(-1, 3)                    # (sub*K_bot, 3)
            flat_srgb = linear_to_srgb_uint8(flat_linear)
            flat_lab = rgb_to_lab(flat_srgb)                             # (sub*K_bot, 3)
            final_lab = flat_lab.reshape(sub, K_bot, 3)
            # ΔE to every target: (C, sub, K_bot).
            delta_e = np.linalg.norm(
                final_lab[None, :, :, :] - target_labs[:, None, None, :],
                axis=3,
            )
            # Flatten (sub, K_bot) → L, pick argmin per target.
            L = sub * K_bot
            delta_flat = delta_e.reshape(C_count, L)
            local_best_idx = np.argmin(delta_flat, axis=1)               # (C,)
            local_best_de = delta_flat[np.arange(C_count), local_best_idx]
            update_mask = local_best_de < best_de
            if not np.any(update_mask):
                continue
            top_idx = local_best_idx // K_bot
            bot_idx = local_best_idx % K_bot
            best_de[update_mask] = local_best_de[update_mask]
            for i in np.where(update_mask)[0]:
                t_i = int(top_idx[i])
                b_i = int(bot_idx[i])
                best_pred_linear[i] = final_linear[t_i, b_i]
                if bottom_depth > 0:
                    best_recipes[i, :bottom_depth] = bot_recipes[b_i]
                best_recipes[i, bottom_depth:] = chunk_recipes[t_i]

    matched_rgb = linear_to_srgb_uint8(best_pred_linear)
    return matched_rgb, best_recipes, best_de


# ---------------------------------------------------------------------------
# Near-target color suggestion — MITM-based top-K achievable colors
# 近目标色建议 —— 基于 MITM 的可达色 Top-K 搜索
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColorSuggestion:
    """One achievable-color candidate produced by the suggester.
    颜色建议器产出的一个可达色候选。

    Attributes:
        matched_rgb: (3,) uint8 predicted sRGB for the candidate. (候选色 sRGB)
        recipe: (N,) int32 per-layer material indices; column 0 is the bottom
            layer (substrate-adjacent), column ``N-1`` is the top (viewing
            surface). Matches the canonical solver layer order.
            (配方：第 0 列为底层、最后一列为顶层)
        delta_e: CIE76 ΔE between the candidate and the target color.
            (候选色相对目标色的 CIE76 ΔE)
    """

    matched_rgb: np.ndarray
    recipe: np.ndarray
    delta_e: float


# Suggester tuning knobs.
# 建议器调参常量。
DEFAULT_SUGGEST_TOP_K: int = 20
"""Number of candidates returned by default. (默认返回候选数)"""

DEFAULT_SUGGEST_MIN_SPACING: float = 1.5
"""Minimum Lab ΔE between returned candidates to avoid near-duplicates.
保证返回候选之间的最小 Lab ΔE 距离，避免视觉上的重复。"""

_SUGGEST_OVERSAMPLE_FACTOR: int = 8
"""Heap size = ``top_k * oversample``; keeps a generous buffer for the
post-pass greedy-spacing dedup. (过采样倍数，便于去重后仍有足够候选)"""


def _greedy_lab_spacing_dedup(
    sorted_labs: np.ndarray,
    min_spacing: float,
    limit: int,
) -> np.ndarray:
    """Keep entries whose Lab is ``>= min_spacing`` away from every earlier kept.
    贪心保留与之前保留项 Lab 距离 ``>= min_spacing`` 的条目。

    Assumes ``sorted_labs`` is already ordered by desirability (best first).
    Returns the kept row indices (into ``sorted_labs``) in input order. The
    result length is ``<= limit``; callers pass ``limit=top_k`` to bound it.
    前提 ``sorted_labs`` 已按优先级排序；返回保留行的索引数组，长度 ``<= limit``。
    """
    if sorted_labs.shape[0] == 0 or limit <= 0:
        return np.zeros(0, dtype=np.int64)
    spacing_sq = float(min_spacing) ** 2
    kept_idx: list[int] = [0]
    kept_labs = [sorted_labs[0]]
    for i in range(1, sorted_labs.shape[0]):
        if len(kept_idx) >= limit:
            break
        candidate = sorted_labs[i]
        diffs = np.asarray(kept_labs, dtype=np.float64) - candidate
        if np.all(np.sum(diffs * diffs, axis=1) >= spacing_sq):
            kept_idx.append(i)
            kept_labs.append(candidate)
    return np.asarray(kept_idx, dtype=np.int64)


# Shared MITM chunk target. This controls one temporary array, not task
# admission or the total recipe space.
# MITM 分块目标只控制单个临时数组，不是任务准入或配方总量额度。
_CHUNK_TARGET_BYTES: int = 32 * 1024 * 1024


def _mitm_chunk_size_for(k_bot: int, chunk_budget_bytes: int | None = None) -> int:
    """Pick a top-chunk size from the local temporary-array target.
    按单个临时数组目标选择 top 分块大小。

    The 24 bytes/row figure reflects the three float64 linear-RGB channels we
    instantiate per (top, bottom) pair during MITM evaluation. Callers pass an
    explicit budget only in tests.
    """
    budget = int(chunk_budget_bytes or _CHUNK_TARGET_BYTES)
    per_row_bytes = max(1, int(k_bot) * 24)
    return max(1, budget // per_row_bytes)


def suggest_colors_for_target(
    target_srgb: np.ndarray,
    materials: list[MaterialParams],
    layer_count: int,
    layer_height_mm: float = DEFAULT_LAYER_HEIGHT_MM,
    substrate: str = "white",
    *,
    top_k: int = DEFAULT_SUGGEST_TOP_K,
    min_spacing: float = DEFAULT_SUGGEST_MIN_SPACING,
) -> list[ColorSuggestion]:
    """Suggest up to ``top_k`` achievable colors near ``target_srgb``.
    为 ``target_srgb`` 返回至多 ``top_k`` 个可达的近似色建议。

    Uses the same MITM enumeration as :func:`solve_image_colors_optimal` but
    scores every final color against a single target, keeps a heap of the
    best ``top_k * oversample`` candidates across chunks, and finally applies
    a greedy Lab-ΔE spacing filter so returned suggestions are perceptually
    distinct.

    Args:
        target_srgb: (3,) uint8 target color in sRGB. (目标 sRGB 颜色)
        materials: Selected material palette. (已选耗材列表)
        layer_count: Layers per pixel (5-10). (每像素层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"``. (基底类型)
        top_k: Maximum number of candidates to return. (返回候选数上限)
        min_spacing: Minimum Lab ΔE between candidates. (候选间最小 Lab ΔE)

    Returns:
        List of up to ``top_k`` :class:`ColorSuggestion` ordered by ΔE
        ascending. Empty list only when the palette produces zero enumerated
        rows (should not happen for ``layer_count >= 1``).
        (按 ΔE 升序的 :class:`ColorSuggestion` 列表，最多 ``top_k`` 项)

    Raises:
        ValueError: ``layer_count``, ``layer_height_mm``, ``substrate`` or
            ``target_srgb`` out of range; or empty ``materials``.
    """
    target_srgb = np.asarray(target_srgb, dtype=np.uint8)
    if target_srgb.shape != (3,):
        raise ValueError(f"target_srgb must be shaped (3,), got {target_srgb.shape}")
    if layer_count < MIN_LAYER_COUNT or layer_count > MITM_MAX_LAYER_COUNT:
        raise ValueError(
            f"layer_count must be {MIN_LAYER_COUNT}-{MITM_MAX_LAYER_COUNT}, got {layer_count} "
            "(deeper stacks: use the material candidate runtime)"
        )
    if not materials:
        raise ValueError("At least one material must be provided (materials is empty)")
    if layer_height_mm not in ALLOWED_LAYER_HEIGHTS_MM:
        raise ValueError(
            f"layer_height_mm must be one of {ALLOWED_LAYER_HEIGHTS_MM}, got {layer_height_mm}"
        )
    if substrate not in ("white", "black"):
        raise ValueError(f"substrate must be 'white' or 'black', got {substrate!r}")
    if top_k <= 0:
        raise ValueError(f"top_k must be positive, got {top_k}")
    if min_spacing < 0.0:
        raise ValueError(f"min_spacing must be non-negative, got {min_spacing}")

    substrate_linear = (
        np.zeros(3, dtype=np.float64)
        if substrate == "black"
        else np.ones(3, dtype=np.float64)
    )
    target_lab = rgb_to_lab(target_srgb.reshape(1, 3))[0]

    affines = _compute_material_affines(materials, layer_height_mm)
    bottom_depth, top_depth = _pick_mitm_split(layer_count, len(materials))
    bot_alpha, bot_beta, bot_recipes = _enumerate_cumulative_affines(
        affines, bottom_depth
    )
    top_alpha, top_beta, top_recipes = _enumerate_cumulative_affines(
        affines, top_depth
    )
    bot_colors = bot_alpha * substrate_linear + bot_beta  # (K_bot, 3)
    k_bot = bot_colors.shape[0]
    k_top = top_alpha.shape[0]
    heap_size = max(int(top_k), int(top_k) * _SUGGEST_OVERSAMPLE_FACTOR)
    chunk_size = _mitm_chunk_size_for(k_bot)

    best_de = np.full(heap_size, np.inf, dtype=np.float64)
    best_lab = np.zeros((heap_size, 3), dtype=np.float64)
    best_srgb = np.zeros((heap_size, 3), dtype=np.uint8)
    best_recipes = np.zeros((heap_size, layer_count), dtype=np.int32)
    # ``heap_size`` is treated as an unordered priority queue keyed on ΔE; the
    # worst (largest) element's slot is tracked so we can replace it directly
    # without re-sorting every chunk.
    # heap_size 被当作无序优先队列，跟踪当前最差元素位置方便替换。
    worst_heap_idx = int(np.argmax(best_de))

    for chunk_start in range(0, k_top, chunk_size):
        chunk_end = min(chunk_start + chunk_size, k_top)
        sub = chunk_end - chunk_start
        chunk_alpha = top_alpha[chunk_start:chunk_end]  # (sub, 3)
        chunk_beta = top_beta[chunk_start:chunk_end]    # (sub, 3)
        chunk_top_recipes = top_recipes[chunk_start:chunk_end]  # (sub, top_depth)

        # final_linear: (sub, K_bot, 3) = α_top * bot_color + β_top.
        final_linear = (
            chunk_alpha[:, None, :] * bot_colors[None, :, :]
            + chunk_beta[:, None, :]
        )
        flat_linear = final_linear.reshape(-1, 3)               # (sub*K_bot, 3)
        flat_srgb = linear_to_srgb_uint8(flat_linear)
        flat_lab = rgb_to_lab(flat_srgb)                        # (sub*K_bot, 3)
        flat_de = np.linalg.norm(flat_lab - target_lab.reshape(1, 3), axis=1)

        # Fast pre-filter: only rows that beat the current worst heap entry.
        threshold = float(best_de[worst_heap_idx])
        if not np.isfinite(threshold):
            promote_mask = np.ones_like(flat_de, dtype=bool)
        else:
            promote_mask = flat_de < threshold
        promote_idx = np.where(promote_mask)[0]
        if promote_idx.size == 0:
            continue

        # Promote candidates one by one; each insertion updates the worst slot.
        promote_idx_sorted = promote_idx[np.argsort(flat_de[promote_idx])]
        for flat_idx in promote_idx_sorted:
            candidate_de = float(flat_de[flat_idx])
            if candidate_de >= best_de[worst_heap_idx]:
                break
            top_i = int(flat_idx // k_bot)
            bot_i = int(flat_idx % k_bot)
            best_de[worst_heap_idx] = candidate_de
            best_lab[worst_heap_idx] = flat_lab[flat_idx]
            best_srgb[worst_heap_idx] = flat_srgb[flat_idx]
            recipe_slot = best_recipes[worst_heap_idx]
            if bottom_depth > 0:
                recipe_slot[:bottom_depth] = bot_recipes[bot_i]
            recipe_slot[bottom_depth:] = chunk_top_recipes[top_i]
            worst_heap_idx = int(np.argmax(best_de))

    # Sort the heap by ΔE ascending (infinity entries sink to the tail).
    order = np.argsort(best_de, kind="stable")
    ordered_de = best_de[order]
    ordered_lab = best_lab[order]
    ordered_srgb = best_srgb[order]
    ordered_recipes = best_recipes[order]

    finite_mask = np.isfinite(ordered_de)
    ordered_de = ordered_de[finite_mask]
    ordered_lab = ordered_lab[finite_mask]
    ordered_srgb = ordered_srgb[finite_mask]
    ordered_recipes = ordered_recipes[finite_mask]

    if ordered_de.size == 0:
        return []

    kept_idx = _greedy_lab_spacing_dedup(
        ordered_lab, min_spacing=min_spacing, limit=int(top_k)
    )
    return [
        ColorSuggestion(
            matched_rgb=ordered_srgb[i].copy(),
            recipe=ordered_recipes[i].astype(np.int32, copy=True),
            delta_e=float(ordered_de[i]),
        )
        for i in kept_idx
    ]


# ---------------------------------------------------------------------------
# Cross-N not-worse-than-smaller-N fallback
# 跨 N 不劣于更小 N 的回退
# ---------------------------------------------------------------------------


WHITE_MATERIAL_MAX_LINEAR_DISTANCE: float = 0.35
"""Max linear-RGB distance between a palette material's equilibrium colour
:attr:`MaterialParams.E` and pure white ``(1, 1, 1)`` for
:func:`find_white_material_index` to accept it as the palette's "white".

The value is calibrated against the shipped material database: real white
PLA/PETG filaments cluster around ``‖E − 1‖ < 0.20`` in linear RGB, while the
next-whitest colours (cream/ivory/light-grey) already sit at ``≥ 0.40``. A
0.35 threshold therefore keeps genuine whites and rejects off-whites; tighter
calibrations belong in callers that care about specific subpalettes.

调色板中判定材料是否为 "白色" 所允许的线性 RGB 距离上限。对项目内置耗材库
的校准显示，真实白色 PLA/PETG 的 ``‖E − 1‖`` 小于 0.20，而次白（米色/象牙
色/浅灰）已经 ≥ 0.40；0.35 的阈值能接纳真白并排除次白，更严格的阈值留给
关心特定子调色板的调用方。
"""


def find_white_material_index(
    materials: list[MaterialParams],
    *,
    max_linear_distance: float = WHITE_MATERIAL_MAX_LINEAR_DISTANCE,
) -> int | None:
    """Return the palette index of the "whitest" material, or ``None``.
    返回调色板中最接近白色的材料索引；无足够白材料时返回 ``None``。

    The candidate is chosen by minimising the Euclidean distance from each
    material's :attr:`MaterialParams.E` (linear-RGB equilibrium colour) to
    pure white ``(1, 1, 1)``. The match is accepted only when the minimum
    distance is below :data:`WHITE_MATERIAL_MAX_LINEAR_DISTANCE`, so a palette
    without any sufficiently-white material yields ``None`` rather than a
    misleading "best non-white" pick.

    以每种材料的 :attr:`MaterialParams.E`（线性 RGB 平衡色）到纯白 ``(1,1,1)``
    的欧氏距离最小者作为候选；仅当距离低于
    :data:`WHITE_MATERIAL_MAX_LINEAR_DISTANCE` 时接受。若调色板没有足够白的
    材料，则返回 ``None``，避免错误地把次白当作 "白底填充" 来源。

    Args:
        materials: Palette to search. (待查询的调色板)
        max_linear_distance: Acceptance threshold, expressed as Euclidean
            distance in linear RGB. Callers can tighten it for strict
            fingerprint matching. (接受阈值，线性 RGB 欧氏距离)

    Returns:
        Index into ``materials`` of the whitest entry, or ``None`` if no
        entry qualifies. (调色板中最白材料的索引，未命中返回 ``None``)
    """
    if not materials:
        return None
    white_linear = np.ones(3, dtype=np.float64)
    best_idx: int | None = None
    best_distance = float("inf")
    for idx, mat in enumerate(materials):
        distance = float(np.linalg.norm(mat.E.astype(np.float64) - white_linear))
        if distance < best_distance:
            best_distance = distance
            best_idx = idx
    if best_idx is None or best_distance > float(max_linear_distance):
        return None
    return best_idx


def forward_batch_model(
    recipes: np.ndarray,
    materials: list[MaterialParams],
    layer_height_mm: float,
    substrate_linear: np.ndarray | None = None,
) -> np.ndarray:
    """Vectorised forward simulation for a batch of N-layer recipes.
    批量正向仿真 N 层配方的最终颜色。

    Functionally equivalent to calling :func:`forward_model` per row, but
    expressed as a single O(C · N) NumPy traversal so callers can evaluate
    thousands of recipes in milliseconds.

    Args:
        recipes: (C, N) int array of material indices; ``recipes[:, 0]`` is
            the bottom (substrate-adjacent) layer, ``recipes[:, N - 1]`` is
            the top. (配方矩阵；第 0 列贴基底、最后一列为顶层)
        materials: Available materials referenced by ``recipes``. (材料列表)
        layer_height_mm: Thickness of each layer in mm. (每层厚度 mm)
        substrate_linear: (3,) substrate colour in linear RGB; defaults to
            white. (基底线性 RGB，默认白)

    Returns:
        (C, 3) float64 predicted linear RGB per recipe. (每条配方的预测线性 RGB)
    """
    recipes_arr = np.asarray(recipes)
    if recipes_arr.ndim != 2:
        raise ValueError(f"recipes must be shaped (C, N), got {recipes_arr.shape}")
    if not materials:
        raise ValueError("At least one material must be provided")
    if substrate_linear is None:
        substrate_linear = np.ones(3, dtype=np.float64)
    substrate_linear = np.asarray(substrate_linear, dtype=np.float64).reshape(3)

    C_count, N = recipes_arr.shape
    if C_count == 0:
        return np.zeros((0, 3), dtype=np.float64)
    if N == 0:
        return np.broadcast_to(substrate_linear, (C_count, 3)).copy()

    all_E = np.stack([m.E for m in materials], axis=0).astype(np.float64)  # (M, 3)
    all_k = np.stack([m.k for m in materials], axis=0).astype(np.float64)  # (M, 3)
    attenuation = np.exp(-all_k * float(layer_height_mm))                  # (M, 3)

    C = np.broadcast_to(substrate_linear, (C_count, 3)).copy()
    for layer_idx in range(N):
        mat_ids = recipes_arr[:, layer_idx].astype(np.int64)
        E = all_E[mat_ids]                  # (C, 3)
        a = attenuation[mat_ids]            # (C, 3)
        C = E + (C - E) * a
    return C


def _pad_with_white_bottom(
    recipes_short: np.ndarray,
    target_layer_count: int,
    white_material_index: int,
) -> np.ndarray:
    """Prepend ``white_material_index`` layers at the bottom to reach ``target_layer_count``.
    在配方底部前缀填充白色层，使总长度达到 ``target_layer_count``。
    """
    recipes_short = np.asarray(recipes_short)
    if recipes_short.ndim != 2:
        raise ValueError(
            f"recipes_short must be shaped (C, k), got {recipes_short.shape}"
        )
    C_count, k = recipes_short.shape
    pad_count = int(target_layer_count) - int(k)
    if pad_count < 0:
        raise ValueError(
            f"target_layer_count ({target_layer_count}) must be >= k ({k})"
        )
    if pad_count == 0:
        return recipes_short.astype(np.int32, copy=True)
    padded = np.empty((C_count, int(target_layer_count)), dtype=np.int32)
    padded[:, :pad_count] = int(white_material_index)
    padded[:, pad_count:] = recipes_short.astype(np.int32, copy=False)
    return padded


def ensure_not_worse_than_smaller_N(
    unique_colors_srgb: np.ndarray,
    materials: list[MaterialParams],
    baseline_matched_rgb: np.ndarray,
    baseline_recipes: np.ndarray,
    baseline_delta_e: np.ndarray,
    *,
    target_layer_count: int,
    layer_height_mm: float = DEFAULT_LAYER_HEIGHT_MM,
    substrate: str = "white",
    min_layer_count: int = MIN_LAYER_COUNT,
    white_material_index: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Replace baseline recipes with a smaller-N solution padded with white when it scores better.
    当更小 N 的最优解 + 白色填底能取得更小 ΔE 时，用它替换 baseline 配方。

    For each target color, the function enumerates every
    ``k ∈ [min_layer_count, target_layer_count)``, runs the strict MITM
    solver at ``N = k`` on the same substrate, prepends
    ``target_layer_count - k`` white layers to the ``k``-layer recipe, and
    re-evaluates the predicted sRGB through the Beer-Lambert forward model.
    Targets whose padded ΔE is strictly smaller than ``baseline_delta_e`` are
    replaced in-place; all others keep the baseline.

    This keeps the ``target_layer_count`` output **lossless on the preview
    side**: within the solver's colour model the returned recipes cannot
    score worse than any ``k < target_layer_count`` solution padded with
    white, so "10 layers can't be worse than 5 layers" holds by construction
    (subject to the usual material-model assumptions).

    对每个目标色，依次枚举 ``k ∈ [min_layer_count, target_layer_count)``，在
    同一基底下跑严格 MITM 求解，然后在 ``k`` 层配方底部填充
    ``target_layer_count - k`` 层白色，通过 Beer-Lambert 正向模型重新评估
    预测 sRGB；若 padded ΔE 严格小于 baseline_delta_e，则原地替换。由此
    保证 ``target_layer_count`` 的输出在颜色模型下不劣于任何 ``k`` 层 + 白色
    填底的解。

    Args:
        unique_colors_srgb: (C, 3) uint8 target sRGB colours. (目标唯一色)
        materials: Palette used by both baseline and fallback. (调色板)
        baseline_matched_rgb: (C, 3) uint8 baseline achieved sRGB. (baseline 预测色)
        baseline_recipes: (C, target_layer_count) int baseline recipes.
            (baseline 配方，列 0 为底层)
        baseline_delta_e: (C,) float64 baseline CIE76 ΔE to target. (baseline ΔE)
        target_layer_count: Recipe length of the baseline. (baseline 层数)
        layer_height_mm: Layer thickness in mm. (层厚 mm)
        substrate: ``"white"`` or ``"black"``. (基底)
        min_layer_count: Lower bound of ``k`` to evaluate. Defaults to
            :data:`MIN_LAYER_COUNT`. (参与回退的最小 k，默认 :data:`MIN_LAYER_COUNT`)
        white_material_index: Caller-supplied white material index. When
            ``None`` the function auto-detects via
            :func:`find_white_material_index`; returning unchanged if no
            entry is whites enough.
            (调用方指定的白色材料索引；``None`` 时自动识别，若未识别到则原样返回)

    Returns:
        ``(matched_rgb, recipes, delta_e, stats)`` where the first three
        arrays are shaped like the baseline inputs (same dtypes) and
        ``stats`` is a JSON-serialisable dict with:

        - ``white_material_index``: resolved white index or ``None``
        - ``applied``: whether any fallback was evaluated
        - ``improved_pixels``: total number of targets overwritten
        - ``per_k_improved``: ``{k: count}`` mapping showing which ``k``
          wins and how often
        - ``mean_delta_e_before`` / ``mean_delta_e_after``
        - ``max_delta_e_before`` / ``max_delta_e_after``

        Only ``k <= MITM_MAX_LAYER_COUNT`` is evaluated: the strict MITM
        solver cannot enumerate deeper stacks. For ``target_layer_count``
        above ``MITM_MAX_LAYER_COUNT + 1`` the guarantee therefore covers
        ``k`` up to ``MITM_MAX_LAYER_COUNT`` only.
    """
    if target_layer_count > MAX_LAYER_COUNT:
        raise ValueError(
            f"target_layer_count must be <= {MAX_LAYER_COUNT}, "
            f"got {target_layer_count}"
        )
    if min_layer_count < MIN_LAYER_COUNT:
        raise ValueError(
            f"min_layer_count must be >= {MIN_LAYER_COUNT}, got {min_layer_count}"
        )
    # target_layer_count < MIN_LAYER_COUNT is a no-op rather than an error:
    # there are no smaller ks to compare against, so the baseline is already
    # the only admissible solution. This keeps trivial callers (tests,
    # single-layer debug pipelines) from needing an extra guard.
    # (target_layer_count < MIN_LAYER_COUNT 没有更小 k 可对比，直接以 baseline
    # 返回，便于单层调试等简单调用方。)
    if layer_height_mm not in ALLOWED_LAYER_HEIGHTS_MM:
        raise ValueError(
            f"layer_height_mm must be one of {ALLOWED_LAYER_HEIGHTS_MM}, "
            f"got {layer_height_mm}"
        )
    if substrate not in ("white", "black"):
        raise ValueError(f"substrate must be 'white' or 'black', got {substrate!r}")

    unique_colors_srgb = np.asarray(unique_colors_srgb)
    baseline_matched_rgb = np.asarray(baseline_matched_rgb)
    baseline_recipes = np.asarray(baseline_recipes)
    baseline_delta_e = np.asarray(baseline_delta_e, dtype=np.float64)

    C_count = int(unique_colors_srgb.shape[0])
    if (
        baseline_matched_rgb.shape != (C_count, 3)
        or baseline_recipes.shape != (C_count, int(target_layer_count))
        or baseline_delta_e.shape != (C_count,)
    ):
        raise ValueError(
            "baseline arrays must match shapes "
            f"(C=3)={baseline_matched_rgb.shape!r}, "
            f"(C=N)={baseline_recipes.shape!r}, "
            f"(C,)={baseline_delta_e.shape!r} "
            f"for C={C_count}, N={target_layer_count}"
        )

    # Defensive copies so we can freely mutate without surprising callers.
    result_matched = baseline_matched_rgb.astype(np.uint8, copy=True)
    result_recipes = baseline_recipes.astype(np.int32, copy=True)
    result_delta_e = baseline_delta_e.astype(np.float64, copy=True)

    stats: dict[str, Any] = {
        "white_material_index": None,
        "applied": False,
        "improved_pixels": 0,
        "per_k_improved": {},
        "mean_delta_e_before": float(result_delta_e.mean()) if C_count else 0.0,
        "max_delta_e_before": float(result_delta_e.max()) if C_count else 0.0,
        "mean_delta_e_after": float(result_delta_e.mean()) if C_count else 0.0,
        "max_delta_e_after": float(result_delta_e.max()) if C_count else 0.0,
    }

    # Nothing to do: no targets, no palette, or N already at the lower bound.
    if C_count == 0 or not materials or target_layer_count <= min_layer_count:
        return result_matched, result_recipes, result_delta_e, stats

    if white_material_index is None:
        white_material_index = find_white_material_index(materials)
    if white_material_index is None:
        # No sufficiently-white material: the padded-fallback construction is
        # undefined, so keep the baseline untouched rather than faking a
        # "white" via some off-white material.
        return result_matched, result_recipes, result_delta_e, stats
    if not (0 <= int(white_material_index) < len(materials)):
        raise ValueError(
            f"white_material_index {white_material_index} outside palette "
            f"length {len(materials)}"
        )
    stats["white_material_index"] = int(white_material_index)
    stats["applied"] = True

    substrate_linear = (
        np.ones(3, dtype=np.float64)
        if substrate == "white"
        else np.zeros(3, dtype=np.float64)
    )
    target_labs = rgb_to_lab(unique_colors_srgb.astype(np.uint8)).astype(np.float64)

    M = len(materials)
    # MITM is exact only up to MITM_MAX_LAYER_COUNT; deeper k would raise.
    k_stop = min(int(target_layer_count), MITM_MAX_LAYER_COUNT + 1)
    for k in range(int(min_layer_count), k_stop):
        # Guard: estimate peak memory of the MITM delta_e broadcast.
        # The solver's inner loop allocates ``delta_e`` of shape
        # ``(C, chunk, K_bot)`` float64.  ``chunk`` is derived from a
        # 32 MiB cap on the ``final_linear`` array:
        #   chunk ≈ min(K_top, 32 MiB / (K_bot * 24))
        # so the peak ``delta_e`` size is approximately
        #   C × chunk × K_bot × 8 bytes.
        # When this exceeds a safe threshold the solver will OOM the
        # worker process.  Skip the offending ``k`` gracefully.
        _top_d = (k + 1) // 2
        _bot_d = k - _top_d
        _k_bot = M ** _bot_d
        _k_top = M ** _top_d
        _chunk = min(_k_top, max(1, (32 * 1024 * 1024) // max(1, _k_bot * 24)))
        _peak_bytes = C_count * _chunk * _k_bot * 8
        _MEMORY_LIMIT = 1024 * 1024 * 1024  # 1 GiB
        if _peak_bytes > _MEMORY_LIMIT:
            _log.warning(
                "ensure_not_worse: skipping k=%d (M=%d, K_bot=%d, C=%d) "
                "— estimated delta_e row size %d MiB exceeds limit",
                k, M, _k_bot, C_count,
                _peak_bytes // (1024 * 1024),
            )
            continue
        # Strict MITM optimum at N=k on the same substrate; column 0 bottom.
        _matched_short, recipes_short, _delta_e_short = solve_image_colors_optimal(
            unique_colors_srgb.astype(np.uint8),
            materials,
            layer_count=k,
            layer_height_mm=layer_height_mm,
            substrate=substrate,
        )
        padded_recipes = _pad_with_white_bottom(
            recipes_short, int(target_layer_count), int(white_material_index)
        )
        padded_linear = forward_batch_model(
            padded_recipes, materials, layer_height_mm, substrate_linear
        )
        padded_srgb = linear_to_srgb_uint8(padded_linear)
        padded_lab = rgb_to_lab(padded_srgb).astype(np.float64)
        padded_delta_e = np.linalg.norm(padded_lab - target_labs, axis=1)

        improved = padded_delta_e < result_delta_e
        improved_count = int(np.count_nonzero(improved))
        if improved_count == 0:
            continue
        stats["per_k_improved"][int(k)] = improved_count
        stats["improved_pixels"] += improved_count
        result_matched[improved] = padded_srgb[improved]
        result_recipes[improved] = padded_recipes[improved]
        result_delta_e[improved] = padded_delta_e[improved]

    if C_count:
        stats["mean_delta_e_after"] = float(result_delta_e.mean())
        stats["max_delta_e_after"] = float(result_delta_e.max())
    return result_matched, result_recipes, result_delta_e, stats
