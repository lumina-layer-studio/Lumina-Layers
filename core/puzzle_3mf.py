"""Puzzle 3MF assembly helpers.
拼图模式 3MF 组装辅助工具。

This module converts multiple per-piece 3MF files into a single combined 3MF
that preserves per-piece placement and groups each puzzle piece as a distinct
object in the final package.
本模块用于将多个单块 3MF 组合为一个统一的 3MF，并保留每块拼图的全局位置，
同时让最终文件中的每个拼图块都作为独立对象出现。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import re
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from core.export_materials import resolve_preview_color_for_slot

if TYPE_CHECKING:
    from utils.fatcat_metadata import MetadataTarget


@dataclass(frozen=True)
class PuzzlePiece3MFSource:
    """Per-piece source metadata for combined 3MF export.
    组合导出时每个拼图块的源文件元数据。

    Attributes:
        label: Stable piece label such as ``A1``.
            稳定的拼图块编号，例如 ``A1``。
        threemf_path: Path to the generated per-piece 3MF file.
            单块 3MF 文件路径。
        offset_x_mm: Global X offset in millimeters.
            拼图块在总装配中的全局 X 偏移，单位毫米。
        offset_y_mm: Global Y offset in millimeters.
            拼图块在总装配中的全局 Y 偏移，单位毫米。
    """

    label: str
    threemf_path: str
    offset_x_mm: float
    offset_y_mm: float


def assemble_puzzle_3mf(
    piece_sources: list[PuzzlePiece3MFSource],
    piece_slots: Sequence[Sequence[Any]],
    output_path: str,
    slot_names: list[str] | None,
    preview_colors: dict[object, object] | None,
    slot_index_by_name: Mapping[str, int] | None,
    printer_id: str,
    nozzle_size: str,
    device_profile_id: str | None,
    build_plate_id: str | None,
    overview_png_bytes: bytes | None,
    metadata_target: MetadataTarget,
    enable_wipe_tower_auto_placement: bool = True,
    material_types: Mapping[str, str | None] | None = None,
    native_filament_profiles: Mapping[str, str] | None = None,
) -> str:
    """Write puzzle metadata through Fat Cat while retaining Lumina placement.

    拼图位置仍由 Lumina 计算；最终元数据由 Fat Cat 合成并交给 neroued 写包。

    Args:
        piece_sources: Generated piece 3MFs with Lumina-computed offsets.
            Lumina 已计算偏移量的拼图单块 3MF。
        piece_slots: Source material identities for each piece 3MF.
            每个拼图单块 3MF 的源材料槽位身份。
        output_path: Destination 3MF path. (输出 3MF 路径)
        slot_names: Ordered global puzzle palette. (全局拼图调色板顺序)
        preview_colors: Product colors for the ordered palette.
            全局调色板对应的产品颜色。
        slot_index_by_name: Business palette slot to source-array index.
            业务调色板槽位到源数组索引的映射。
        printer_id: Selected Lumina printer profile. (所选 Lumina 打印机配置)
        nozzle_size: Selected nozzle size. (所选喷嘴尺寸)
        device_profile_id: Explicit slicer device profile. (明确的切片器设备配置)
        build_plate_id: Explicit native build plate. (明确的原生打印板)
        overview_png_bytes: Combined puzzle overview image. (拼图总览图字节)
        metadata_target: Explicit Fat Cat target selected by the API route.
            API 路由明确选择的 Fat Cat 目标。
        enable_wipe_tower_auto_placement: Whether to solve one final layout.
            是否求解一次最终擦料塔布局。
        material_types: Known types for the full palette. 全局调色板已知材料类型。
        native_filament_profiles: Resolved native presets for sparse slots.
            补齐稀疏槽位时沿用已明确选择的原生预设。

    Returns:
        str: Written 3MF path. (写出的 3MF 路径)

    Raises:
        ValueError: If the source count and material-slot count differ or no
            source pieces are supplied. (源文件与材料槽位数量不匹配或没有源块时抛出)
    """
    if not piece_sources:
        raise ValueError("Puzzle 3MF assembly received no piece sources.")
    if len(piece_sources) != len(piece_slots):
        raise ValueError("Puzzle piece sources and material slots must have equal length.")

    from utils.slicer_3mf_writer import MergedSlicer3MFWriter, MergedItem

    selected_piece_slots = _select_puzzle_palette_slots(
        piece_slots=piece_slots,
        slot_names=slot_names,
        preview_colors=preview_colors,
        slot_index_by_name=slot_index_by_name,
    )

    # MergedItem translations are bbox minima; puzzle offsets use build_transforms below.
    items = [
        MergedItem(
            source_filename=piece_source.label,
            source_3mf_path=Path(piece_source.threemf_path),
            slots=tuple(slots),
            tx_mm=0.0,
            ty_mm=0.0,
        )
        for piece_source, slots in zip(piece_sources, selected_piece_slots)
    ]
    build_transforms = [
        [
            1.0, 0.0, 0.0,
            0.0, 1.0, 0.0,
            0.0, 0.0, 1.0,
            piece_source.offset_x_mm,
            piece_source.offset_y_mm,
            0.0,
        ]
        for piece_source in piece_sources
    ]
    MergedSlicer3MFWriter().write_puzzle(
        items,
        Path(output_path),
        build_transforms=build_transforms,
        overview_png_bytes=overview_png_bytes,
        metadata_target=metadata_target,
        printer_id=printer_id,
        nozzle_size=nozzle_size,
        device_profile_id=device_profile_id,
        build_plate_id=build_plate_id,
        enable_wipe_tower_auto_placement=enable_wipe_tower_auto_placement,
        source_materials=[
            {"name": name, "colour": _rgb_to_hex(_resolve_preview_rgb_for_material_name(
                name, index, preview_colors, "#C8C8C8")),
             "material_type": (material_types or {}).get(name),
             **({"native_filament_profile_name": native_filament_profiles[name]}
                if native_filament_profiles and name in native_filament_profiles else {})}
            for index, name in enumerate(slot_names or [])
        ],
    )
    return output_path


def _select_puzzle_palette_slots(
    *,
    piece_slots: Sequence[Sequence[Any]],
    slot_names: list[str] | None,
    preview_colors: dict[object, object] | None,
    slot_index_by_name: Mapping[str, int] | None,
) -> list[tuple[Any, ...]]:
    """Select each source's slots in the final global puzzle palette order.

    按最终全局拼图调色板顺序，为每份源项目选出并重排对应槽位。
    """

    palette = [str(name) for name in (slot_names or []) if str(name)]
    if not palette:
        return [
            tuple(
                slot
                if getattr(slot, "source_slot_index", None) is not None
                else replace(slot, source_slot_index=int(slot.slot_id))
                for slot in source_slots
            )
            for source_slots in piece_slots
        ]

    source_indexes = slot_index_by_name or {
        name: index for index, name in enumerate(palette)
    }
    selected_by_piece: list[tuple[Any, ...]] = []
    for source_slots in piece_slots:
        slots_by_index = {int(slot.slot_id): slot for slot in source_slots}
        selected: list[Any] = []
        for output_index, name in enumerate(palette):
            source_index = int(source_indexes.get(name, output_index))
            source_slot = next((slot for slot in source_slots if slot.slot_name == name), None)
            if source_slot is None and len(source_slots) >= len(palette):
                source_slot = slots_by_index.get(source_index)
            if source_slot is None:
                # A sparse piece contributes only its real source slots.
                # The library completes genuinely absent global selections.
                continue
            source_index = int(source_slot.slot_id)
            preview_color = _rgb_to_hex(
                _resolve_preview_rgb_for_material_name(
                    material_name=name,
                    material_index=output_index,
                    preview_colors=preview_colors,
                    fallback_hex=source_slot.preview_color,
                )
            )
            selected.append(
                replace(
                    source_slot,
                    slot_id=output_index,
                    slot_name=name,
                    preview_color=preview_color,
                    source_slot_index=source_index,
                )
            )
        selected_by_piece.append(tuple(selected))
    return selected_by_piece


def _resolve_preview_rgb_for_material_name(
    material_name: str,
    material_index: int,
    preview_colors: dict[object, object] | None,
    fallback_hex: str,
) -> tuple[int, int, int]:
    """Resolve the RGB color for one global material name.

    为全局材料名称解析 RGB 颜色。
    """

    color_rgb, source = resolve_preview_color_for_slot(
        material_name, material_index, preview_colors or {},
        palette_index_is_authoritative=True,
    )
    if source != "fallback":
        return color_rgb
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", fallback_hex):
        return (
            int(fallback_hex[1:3], 16),
            int(fallback_hex[3:5], 16),
            int(fallback_hex[5:7], 16),
        )

    return color_rgb


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    """Convert RGB channels to a stable hex color string.

    将 RGB 通道转换为稳定的十六进制颜色字符串。
    """

    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
