"""Shared product palette lookup for scene and puzzle exports.

场景与拼图导出共用的产品调色板查找；不选择原生耗材配置。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class ExportMaterial:
    """Resolved source identity shared by auxiliary geometry and native metadata."""

    name: str
    material_type: str | None
    rgb: RGB


def resolve_coating_material(
    reference: Mapping[str, str] | None,
    *,
    slot_names: Sequence[str],
    preview_colors: Mapping[object, object],
    material_types: Mapping[str, str | None],
) -> ExportMaterial:
    """Follow a uniform source material type; mixed or unknown types use PLA.

    ``reference`` and ``preview_colors`` remain accepted for older callers.
    Historical coating choices do not affect the automatic material policy.
    """
    source_types: set[str | None] = set()
    for name in slot_names:
        value = material_types.get(name)
        explicit_type = value.strip().upper() if isinstance(value, str) else ""
        # Older archives may only record PLA/PETG in the material name.
        label = explicit_type or name.upper()
        polymer = re.search(r"(?<![A-Z0-9])(?:PLA|PETG)(?![A-Z0-9])", label)
        source_types.add(polymer.group() if polymer else explicit_type or None)
    material_type = next(iter(source_types)) if len(source_types) == 1 else None
    return ExportMaterial("Coating", material_type or "PLA", (200, 200, 200))


def configure_coating_material(ctx: MutableMapping[str, Any]) -> ExportMaterial | None:
    """Bind automatic coating facts without adding an optical solver channel.

    Args:
        ctx: Resolved source and conversion settings. 已解析来源及转换设置。

    Returns:
        Resolved material when coating is enabled. 启用涂层时返回解析后的材料。
    """
    if not ctx.get("enable_coating"):
        return None
    material = resolve_coating_material(
        ctx.get("coating_material"), slot_names=ctx["slot_names"],
        preview_colors=ctx["preview_colors"], material_types=ctx.get("material_types") or {},
    )
    ctx["resolved_coating_material"] = material
    ctx["material_types"] = {**(ctx.get("material_types") or {}), material.name: material.material_type}
    ctx["preview_colors"] = {**ctx["preview_colors"], material.name: [*material.rgb, 255]}
    return material


def coerce_preview_rgb(value: object) -> RGB:
    """Read the first three channels of a pipeline preview colour.

    读取流水线预览颜色的前三个通道。

    Args:
        value: Array, list or tuple of colour channels. 颜色数组、列表或元组。

    Returns:
        Integer RGB channels. 整数 RGB 通道。

    Raises:
        ValueError: Unsupported value or fewer than three channels.
            输入类型不支持或不足三个通道。
    """
    if isinstance(value, np.ndarray):
        channels = value.tolist()
    elif isinstance(value, (list, tuple)):
        channels = list(value)
    else:
        raise ValueError(f"Unsupported preview color value: {type(value)!r}")
    if len(channels) < 3:
        raise ValueError("Preview color value must have at least 3 channels.")
    return int(channels[0]), int(channels[1]), int(channels[2])


def resolve_preview_color_for_slot(
    slot_name: str,
    slot_index: int,
    preview_colors: Mapping[object, object],
    *,
    palette_index_is_authoritative: bool = False,
) -> tuple[RGB, str]:
    """Resolve a colour using material identity before legacy display labels.

    Args:
        slot_name: Display material or slot name. 材料或槽位显示名。
        slot_index: Zero-based palette index. 从零开始的调色板索引。
        preview_colors: Name or numeric key to preview channels.
            名称或数值键到预览颜色通道的映射。
        palette_index_is_authoritative: The index comes from the complete
            source palette, rather than enumeration of a sparse mesh list.
            In that case, ignore any old slot number in the display name.

    Returns:
        RGB and the resolution source used for existing diagnostics.
        RGB 与现有诊断使用的解析来源。
    """
    if slot_name in preview_colors:
        return coerce_preview_rgb(preview_colors[slot_name]), "by name"
    match = None if palette_index_is_authoritative else re.match(r"Slot\s+(\d+)\b", slot_name)
    if match is not None:
        slot_key = int(match.group(1)) - 1
        for key in (slot_key, str(slot_key)):
            if key in preview_colors:
                return coerce_preview_rgb(preview_colors[key]), "by slot"
    for key in (slot_index, str(slot_index)):
        if key in preview_colors:
            return coerce_preview_rgb(preview_colors[key]), "by index"
    return (200, 200, 200), "fallback"
