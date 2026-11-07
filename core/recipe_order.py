"""Recipe order and layer-height normalization helpers.
配方层序与层高归一化辅助函数。
"""

from __future__ import annotations

from typing import Sequence

import numpy as np


def normalize_layer_order(value: str | None, default: str = "Top2Bottom") -> str:
    """Normalize layer order string.
    规范化层序字符串。
    """
    if value in ("Top2Bottom", "Bottom2Top"):
        return str(value)
    return default


def convert_recipe_between_orders(
    recipe: Sequence[int],
    source_order: str,
    target_order: str,
) -> list[int]:
    """Convert a recipe between layer-order conventions.
    在不同层序约定之间转换配方。
    """
    normalized_source = normalize_layer_order(source_order)
    normalized_target = normalize_layer_order(target_order)
    recipe_list = [int(v) for v in recipe]
    if normalized_source == normalized_target:
        return recipe_list
    return list(reversed(recipe_list))


def normalize_recipe_to_internal_order(
    recipe: Sequence[int],
    layer_order: str,
    internal_order: str = "Bottom2Top",
) -> list[int]:
    """Normalize recipe to the chosen internal order.
    将配方归一化到指定内部层序。
    """
    return convert_recipe_between_orders(recipe, layer_order, internal_order)


def expand_recipe_by_layer_height(
    recipe: Sequence[int],
    source_layer_height_mm: float,
    target_layer_height_mm: float,
    source_order: str = "Top2Bottom",
    target_order: str | None = None,
    eps: float = 1e-3,
) -> list[int]:
    """Expand or collapse a recipe to match a target layer height.
    将配方扩展或折叠到目标层高。
    """
    if target_layer_order := target_order:
        ordered = convert_recipe_between_orders(recipe, source_order, target_layer_order)
    else:
        ordered = [int(v) for v in recipe]

    if abs(float(source_layer_height_mm) - float(target_layer_height_mm)) <= eps:
        return ordered

    if source_layer_height_mm <= 0 or target_layer_height_mm <= 0:
        raise ValueError("layer height must be positive")

    if source_layer_height_mm > target_layer_height_mm:
        ratio_f = float(source_layer_height_mm) / float(target_layer_height_mm)
        ratio = int(round(ratio_f))
        if ratio <= 0 or abs(ratio_f - ratio) > eps:
            raise ValueError("source/target layer height ratio is not integral")
        expanded: list[int] = []
        for value in ordered:
            expanded.extend([int(value)] * ratio)
        return expanded

    ratio_f = float(target_layer_height_mm) / float(source_layer_height_mm)
    ratio = int(round(ratio_f))
    if ratio <= 0 or abs(ratio_f - ratio) > eps:
        raise ValueError("target/source layer height ratio is not integral")

    if len(ordered) % ratio != 0:
        raise ValueError("recipe length is not divisible by collapse ratio")

    collapsed: list[int] = []
    for begin in range(0, len(ordered), ratio):
        chunk = ordered[begin : begin + ratio]
        ref = int(chunk[0])
        if any(int(v) != ref for v in chunk[1:]):
            raise ValueError("cannot collapse recipe with mixed channels in one target layer")
        collapsed.append(ref)
    return collapsed


def build_mode_key(layer_height_mm: float, color_layers: int) -> str:
    """Build normalized predictive runtime mode key such as ``0.08x5``.
    构建规范化的预测运行时模式键，例如 ``0.08x5``。
    """
    return f"{float(layer_height_mm):.2f}x{int(color_layers)}"


def pad_recipe_to_layer_count(
    recipe: Sequence[int],
    target_layers: int,
    base_channel_idx: int,
    layer_order: str = "Top2Bottom",
) -> list[int]:
    """Pad a recipe to a target layer count using the base channel.
    使用底材通道把配方补齐到目标层数。
    """
    recipe_list = [int(v) for v in recipe]
    if len(recipe_list) >= target_layers:
        return recipe_list[:target_layers]
    pad_count = int(target_layers) - len(recipe_list)
    filler = [int(base_channel_idx)] * pad_count
    if normalize_layer_order(layer_order) == "Top2Bottom":
        return recipe_list + filler
    return filler + recipe_list


def pad_material_matrix_layers(
    material_matrix: np.ndarray,
    target_layers: int,
    base_channel_idx: int,
    layer_order: str,
    mask_solid: np.ndarray | None = None,
) -> np.ndarray:
    """Extend backing-side layers with base inside the silhouette and Air outside."""
    if material_matrix.shape[2] >= target_layers:
        return material_matrix
    if np.issubdtype(material_matrix.dtype, np.unsignedinteger):
        material_matrix = material_matrix.astype(np.int32)
    pad_shape = (*material_matrix.shape[:2], target_layers - material_matrix.shape[2])
    pad = np.full(pad_shape, int(base_channel_idx), dtype=material_matrix.dtype)
    if mask_solid is not None:
        solid = np.asarray(mask_solid, dtype=bool)
        if solid.shape != material_matrix.shape[:2]:
            raise ValueError("mask_solid shape does not match material_matrix spatial shape")
        pad[~solid] = -1
    parts = (pad, material_matrix) if layer_order == "Bottom2Top" else (material_matrix, pad)
    return np.concatenate(parts, axis=2)
