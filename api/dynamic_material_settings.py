"""Shared normalization for dynamic material layer settings.

动态耗材层数设置的共享归一化逻辑。
"""

from __future__ import annotations

import math
from typing import Any


MIN_DYNAMIC_MATERIAL_LAYER_COUNT = 5
# Must match core.material_dynamic_solver.MAX_DYNAMIC_LAYER_COUNT (kept as a
# literal so this lightweight wire-contract module does not import the solver;
# a unit test keeps the two in sync). The UI limits users to 10 unless the
# advanced "unlock 30 layers" switch is on.
# 必须与 core.material_dynamic_solver.MAX_DYNAMIC_LAYER_COUNT 一致（用字面量避免
# 引入求解器，由单测保证同步）。界面在未打开“解锁 30 层”时仍限制为 10。
MAX_DYNAMIC_MATERIAL_LAYER_COUNT = 30
DEFAULT_DYNAMIC_MATERIAL_DELTA_E00_TOLERANCE = 0.5
_HUE_WEIGHT_EPSILON = 1e-12


def _normalize_integral_layer_count(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be an integer")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{field_name} must be an integer") from exc
    if not math.isfinite(numeric) or numeric != math.floor(numeric):
        raise ValueError(f"{field_name} must be a finite integer")
    normalized = int(numeric)
    if not MIN_DYNAMIC_MATERIAL_LAYER_COUNT <= normalized <= MAX_DYNAMIC_MATERIAL_LAYER_COUNT:
        raise ValueError(
            f"{field_name} must be between "
            f"{MIN_DYNAMIC_MATERIAL_LAYER_COUNT} and "
            f"{MAX_DYNAMIC_MATERIAL_LAYER_COUNT}"
        )
    return normalized


def normalize_dynamic_material_settings(
    *,
    material_source: str,
    enabled: Any,
    min_layer_count: Any,
    max_layer_count: Any,
    delta_e00_tolerance: Any,
    hue_weight: Any,
    native_svg_vector: bool = False,
) -> tuple[bool, int, int, float]:
    """Normalize and validate the dynamic material wire contract.

    归一化并校验动态耗材的传输层契约。

    Args:
        material_source: Converter material source selector. 转换器耗材来源。
        enabled: Whether dynamic effective layers are enabled. 是否启用动态
            有效层数。
        min_layer_count: Minimum effective layer count. 最小有效层数。
        max_layer_count: Maximum effective layer count. 最大有效层数。
        delta_e00_tolerance: Allowed CIEDE2000 sacrifice. 允许的 CIEDE2000
            损失。
        hue_weight: Effective hue-protection weight. 实际色相保护权重。
        native_svg_vector: Whether native SVG vector processing would be used.
            Retained for wire compatibility; native SVG now uses the same
            dynamic material contract. 是否将使用原生 SVG 矢量处理；仅保留
            传输层兼容性，原生 SVG 现在使用相同的动态耗材契约。

    Returns:
        tuple[bool, int, int, float]: Normalized enabled flag, minimum,
            maximum, and tolerance. 归一化后的开关、最小值、最大值与容差。

    Raises:
        TypeError: If a numeric field has an incompatible type. 数值字段类型
            不兼容时抛出。
        ValueError: If bounds, mode compatibility, or hue rules fail. 层数、
            模式兼容性或色相规则不合法时抛出。
    """
    normalized_enabled = bool(enabled)
    minimum = _normalize_integral_layer_count(min_layer_count, "material_min_layer_count")
    maximum = _normalize_integral_layer_count(max_layer_count, "material_max_layer_count")
    if minimum > maximum:
        raise ValueError(
            "material_min_layer_count must not exceed material_max_layer_count"
        )
    if isinstance(delta_e00_tolerance, bool):
        raise TypeError("material_delta_e00_tolerance must be a real number")
    try:
        tolerance = float(delta_e00_tolerance)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            "material_delta_e00_tolerance must be a real number"
        ) from exc
    if not math.isfinite(tolerance) or not 0.0 <= tolerance <= 5.0:
        raise ValueError("material_delta_e00_tolerance must be between 0 and 5")

    if normalized_enabled:
        if material_source != "material_archive":
            raise ValueError(
                "dynamic material layer count requires material_archive mode"
            )
        try:
            normalized_hue_weight = float(hue_weight)
        except (TypeError, ValueError) as exc:
            raise TypeError("hue_weight must be a real number") from exc
        if (
            not math.isfinite(normalized_hue_weight)
            or abs(normalized_hue_weight) > _HUE_WEIGHT_EPSILON
        ):
            raise ValueError(
                "dynamic material layer count requires hue_weight to be 0"
            )
    return normalized_enabled, minimum, maximum, tolerance
