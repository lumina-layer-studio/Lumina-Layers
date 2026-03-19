"""
Lumina Studio - LUT Merger Engine

Core module for merging LUT color cards from different color modes.
Supports BW(2-color), 4-Color, 6-Color, and 8-Color LUT merging
with Delta-E (CIE2000) based deduplication.
"""

import os
import sys
import itertools
import numpy as np

from colormath.color_objects import sRGBColor, LabColor
from colormath.color_conversions import convert_color
from colormath.color_diff import delta_e_cie2000

# Try to import color selection for 5-Color Extended mode reconstruction
try:
    from .calibration import select_extended_1444_colors
except ImportError:
    try:
        from core.calibration import select_extended_1444_colors
    except ImportError:
        select_extended_1444_colors = None

# Try to import ColorSystem for layer_count
try:
    from .config import ColorSystem
except ImportError:
    try:
        from config import ColorSystem
    except ImportError:
        ColorSystem = None

# Try to import LUTMetadata and PaletteEntry for palette merging
try:
    from config import LUTMetadata, PaletteEntry
except ImportError:
    LUTMetadata = None
    PaletteEntry = None


# Color mode size mapping
_SIZE_TO_MODE = {
    32: "BW",
    1024: "4-Color",
    1296: "6-Color",
    2468: "5-Color Extended",
    2738: "8-Color",
}


def _detect_mode_by_size(count):
    """Detect color mode by LUT size, with tolerance for near-standard sizes."""
    # Exact match first
    if count in _SIZE_TO_MODE:
        return _SIZE_TO_MODE[count]
    # BW tolerance: 30-36 (some BW LUTs have slightly non-standard sizes)
    if 30 <= count <= 36:
        return "BW"
    return None

# Color mode priority (higher = keep during dedup)
# Merged gets lowest priority: its stacks may be unreliable (e.g. dummy zeros
# from non-standard sizes), so we always prefer entries from known modes.
_MODE_PRIORITY = {
    "Merged": -1,
    "BW": 0,
    "4-Color": 1,
    "5-Color Extended": 1,
    "6-Color": 2,
    "8-Color": 3,
}

# Max material ID per mode
_MODE_MAX_MATERIAL = {
    "BW": 1,
    "4-Color": 3,
    "6-Color": 5,
    "5-Color Extended": 4,
    "8-Color": 7,
    "Merged": 7,
}

# Standard 8-Color slot order for merged palette sorting
_STANDARD_SLOT_ORDER = ["White", "Cyan", "Magenta", "Yellow", "Black", "Red", "Deep Blue", "Green"]

# Material ID remapping tables: source mode → 8-Color material IDs
# 8-Color slots: 0=White, 1=Cyan, 2=Magenta, 3=Yellow, 4=Black, 5=Red, 6=DeepBlue, 7=Green
_REMAP_TO_8COLOR = {
    "BW": {0: 0, 1: 4},           # White→White, Black→Black
    "4-Color-RYBW": {0: 0, 1: 5, 2: 3, 3: 6},  # White→White, Red→Red, Yellow→Yellow, Blue→DeepBlue
    "4-Color-CMYW": {0: 0, 1: 1, 2: 2, 3: 3},   # White→White, Cyan→Cyan, Magenta→Magenta, Yellow→Yellow
    "6-Color-CMYWGK": {0: 0, 1: 1, 2: 2, 3: 7, 4: 3, 5: 4},  # White→White, Cyan→Cyan, Magenta→Magenta, Green→Green, Yellow→Yellow, Black→Black
    "6-Color-RYBWGK": {0: 0, 1: 5, 2: 6, 3: 7, 4: 3, 5: 4},  # White→White, Red→Red, Blue→DeepBlue, Green→Green, Yellow→Yellow, Black→Black
    "5-Color Extended": {0: 0, 1: 5, 2: 3, 3: 6, 4: 4},  # White→White, Red→Red, Yellow→Yellow, Blue→DeepBlue, Black→Black
}


def _detect_4color_subtype(lut_path, metadata=None):
    """Detect 4-Color subtype (RYBW or CMYW) from metadata or filename.
    从 metadata 或文件名检测 4 色子类型（RYBW 或 CMYW）。

    Priority: metadata.color_mode > filename keyword.
    优先级：metadata.color_mode > 文件名关键词。

    Args:
        lut_path (str): LUT file path. (LUT 文件路径)
        metadata (LUTMetadata | None): Optional metadata with color_mode. (可选的含 color_mode 的元数据)

    Returns:
        str: "4-Color-RYBW" or "4-Color-CMYW". (4 色子类型字符串)
    """
    if metadata and metadata.color_mode:
        if "RYBW" in metadata.color_mode:
            return "4-Color-RYBW"
        if "CMYW" in metadata.color_mode:
            return "4-Color-CMYW"
    # 回退到文件名检测
    basename = os.path.basename(lut_path).upper()
    if "CMYW" in basename:
        return "4-Color-CMYW"
    return "4-Color-RYBW"


def _detect_6color_subtype(lut_path, metadata=None):
    """Detect 6-Color subtype (CMYWGK or RYBWGK) from metadata or filename.
    从 metadata 或文件名检测 6 色子类型（CMYWGK 或 RYBWGK）。

    Priority: metadata.color_mode > filename keyword.
    优先级：metadata.color_mode > 文件名关键词。

    Args:
        lut_path (str): LUT file path. (LUT 文件路径)
        metadata (LUTMetadata | None): Optional metadata with color_mode. (可选的含 color_mode 的元数据)

    Returns:
        str: "6-Color-RYBWGK" or "6-Color-CMYWGK". (6 色子类型字符串)
    """
    if metadata and metadata.color_mode:
        if "RYBW" in metadata.color_mode:
            return "6-Color-RYBWGK"
    # 回退到文件名检测
    basename = os.path.basename(lut_path).upper()
    if "RYBW" in basename:
        return "6-Color-RYBWGK"
    return "6-Color-CMYWGK"


def _remap_stacks(stacks, color_mode, lut_path=None, metadata=None):
    """Remap material IDs in stacks from source mode to 8-Color space.
    将堆叠中的材料 ID 从源模式重映射到 8-Color 空间。

    When merging LUTs from different color modes, each mode uses its own
    material ID numbering. This function translates them all into the
    unified 8-Color numbering so the merged LUT produces correct meshes.

    Args:
        stacks: numpy array (N, 5) of material IDs. (材料 ID 数组)
        color_mode: source color mode string. (源颜色模式字符串)
        lut_path: optional file path, used to detect 4-Color/6-Color subtype.
            (可选文件路径，用于检测子类型)
        metadata (LUTMetadata | None): optional metadata with color_mode for
            subtype detection priority. (可选元数据，用于子类型检测优先级)

    Returns:
        numpy array (N, 5) with remapped material IDs. (重映射后的材料 ID 数组)
    """
    if color_mode == "8-Color" or color_mode == "Merged":
        return stacks  # Already in 8-Color space

    remap_key = color_mode
    if color_mode == "4-Color" and lut_path:
        remap_key = _detect_4color_subtype(lut_path, metadata=metadata)
    elif color_mode == "6-Color" and lut_path:
        remap_key = _detect_6color_subtype(lut_path, metadata=metadata)

    remap = _REMAP_TO_8COLOR.get(remap_key)
    if remap is None:
        return stacks  # Unknown mode, return as-is

    remapped = stacks.copy()
    for src_id, dst_id in remap.items():
        remapped[stacks == src_id] = dst_id
    return remapped


class LUTMerger:
    """LUT色卡合并引擎"""

    @staticmethod
    def detect_color_mode(lut_path: str):
        """检测LUT文件的色彩模式和颜色数量

        Args:
            lut_path: LUT文件路径

        Returns:
            (color_mode, color_count) 例如 ("6-Color", 1296)
        """
        if not lut_path or not os.path.exists(lut_path):
            raise FileNotFoundError(f"LUT file not found: {lut_path}")

        ext = os.path.splitext(lut_path)[1].lower()

        if ext == '.npz':
            data = np.load(lut_path)
            if 'rgb' in data and 'stacks' in data:
                count = data['rgb'].shape[0]
                return ("Merged", count)
            raise ValueError("Invalid .npz: missing 'rgb' or 'stacks' key")

        if ext == '.json':
            from utils.lut_manager import LUTManager
            rgb, stacks, metadata = LUTManager.load_lut_with_metadata(lut_path)
            count = len(rgb)
            mode = _detect_mode_by_size(count)
            return (mode or "Merged", count)

        # .npy file
        lut_data = np.load(lut_path)
        colors = lut_data.reshape(-1, 3)
        count = colors.shape[0]

        mode = _detect_mode_by_size(count)
        if mode is None:
            return ("Merged", count)

        return (mode, count)

    @staticmethod
    def validate_compatibility(modes):
        """校验LUT组合的兼容性

        规则：
        - 至少两个LUT
        - 必须包含至少一个6色或8色LUT
        - 6色最高时：仅允许 BW + 4色 + 6色
        - 8色最高时：允许任意组合

        Args:
            modes: 色彩模式字符串列表

        Returns:
            (is_valid, error_message)
        """
        if len(modes) < 2:
            return (False, "至少需要选择两个LUT文件进行合并")

        has_6 = "6-Color" in modes
        has_8 = "8-Color" in modes

        if not has_6 and not has_8:
            return (False, "合并组合必须包含至少一个6色或8色LUT")

        if has_8:
            # 8色最高时允许 BW / 4-Color / 6-Color（不允许 Merged）
            invalid = [m for m in modes if m not in {"BW", "4-Color", "6-Color", "8-Color"}]
            if invalid:
                return (False, f"不允许包含已合并的LUT: {', '.join(invalid)}")
            return (True, "")

        # 6色最高时：仅允许 BW / 4-Color / 6-Color
        allowed = {"BW", "4-Color", "6-Color"}
        invalid = [m for m in modes if m not in allowed]
        if invalid:
            return (False, f"6色模式下不允许包含: {', '.join(invalid)}")

        return (True, "")

    @staticmethod
    def load_lut_with_stacks(lut_path: str, color_mode: str):
        """加载LUT的RGB数组和对应的堆叠数组

        Args:
            lut_path: LUT文件路径
            color_mode: 色彩模式字符串

        Returns:
            (rgb_array[N,3], stacks_array[N,L]) where L is layer_count (5 or 6)
        """
        # .npz 格式直接读取
        if lut_path.endswith('.npz'):
            data = np.load(lut_path)
            return (data['rgb'], data['stacks'])

        # .json 格式：通过 LUTManager 加载
        if lut_path.endswith('.json'):
            from utils.lut_manager import LUTManager
            rgb, stacks, metadata = LUTManager.load_lut_with_metadata(lut_path)
            if stacks is not None and stacks.ndim >= 2 and stacks.shape[0] > 0 and stacks.shape[1] > 0:
                return (rgb, stacks)
            # 回退到索引重建：stacks 为 None 或 shape[1]==0
            count = len(rgb)
            return LUTMerger._rebuild_stacks_from_index(rgb, count, color_mode, lut_path, metadata=metadata)

        # .npy 格式：加载 RGB，根据模式重建堆叠
        lut_data = np.load(lut_path)
        rgb = lut_data.reshape(-1, 3)
        count = rgb.shape[0]

        return LUTMerger._rebuild_stacks_from_index(rgb, count, color_mode, lut_path)

    @staticmethod
    def _rebuild_stacks_from_index(rgb, count, color_mode, lut_path, metadata=None):
        """根据索引重建堆叠数组（从 .npy 或 .json 无 stacks 时回退使用）
        Rebuild stacks array from index when loading .npy or .json without stacks.

        Args:
            rgb: RGB 数组 [N, 3]. (RGB array)
            count: 颜色数量. (color count)
            color_mode: 色彩模式字符串. (color mode string)
            lut_path: LUT 文件路径（用于检测子类型）. (LUT file path for subtype detection)
            metadata (LUTMetadata | None): 可选元数据，用于子类型检测优先级.
                (optional metadata for subtype detection priority)

        Returns:
            (rgb_array[N,3], stacks_array[N,L]). (RGB 和堆叠数组)
        """
        if color_mode == "BW":
            stacks = []
            for i in range(count):
                digits = []
                temp = i
                for _ in range(5):
                    digits.append(temp % 2)
                    temp //= 2
                stacks.append(tuple(reversed(digits)))
            stacks_arr = np.array(stacks)
            return (rgb, _remap_stacks(stacks_arr, color_mode, lut_path, metadata=metadata))

        elif color_mode == "4-Color":
            stacks = []
            for i in range(count):
                digits = []
                temp = i
                for _ in range(5):
                    digits.append(temp % 4)
                    temp //= 4
                stacks.append(tuple(reversed(digits)))
            stacks_arr = np.array(stacks)
            return (rgb, _remap_stacks(stacks_arr, color_mode, lut_path, metadata=metadata))

        elif color_mode == "6-Color":
            subtype = _detect_6color_subtype(lut_path, metadata=metadata) if lut_path else "6-Color"
            if "RYBW" in subtype:
                from core.calibration import get_top_1296_colors_rybw
                raw_stacks = get_top_1296_colors_rybw()
            else:
                from core.calibration import get_top_1296_colors
                raw_stacks = get_top_1296_colors()
            stacks = [tuple(reversed(s)) for s in raw_stacks]
            min_len = min(len(stacks), count)
            stacks_arr = np.array(stacks[:min_len])
            return (rgb[:min_len], _remap_stacks(stacks_arr, color_mode, lut_path, metadata=metadata))

        elif color_mode == "8-Color":
            from config import get_asset_path
            stacks_path = get_asset_path('smart_8color_stacks.npy')
            raw_stacks = np.load(stacks_path).tolist()
            stacks = [tuple(reversed(s)) for s in raw_stacks]
            min_len = min(len(stacks), count)
            return (rgb[:min_len], np.array(stacks[:min_len]))

        elif color_mode == "5-Color Extended":
            if lut_path.endswith('.npz'):
                data = np.load(lut_path)
                stacks = data['stacks']
                return (rgb, _remap_stacks(stacks, color_mode, lut_path, metadata=metadata))

            base_stacks = []
            for i in range(1024):
                digits = []
                temp = i
                for _ in range(5):
                    digits.append(temp % 4)
                    temp //= 4
                base_stacks.append(tuple(reversed(digits)))

            if select_extended_1444_colors:
                ext_stacks = select_extended_1444_colors(base_stacks)
            else:
                print("⚠️ [LUT_MERGER] Warning: select_extended_1444_colors not found. Using linear fallback for 5C-EXT.")
                ext_stacks = []
                for ext_idx in range(1444):
                    if ext_idx == 0:
                        stack = (4, 0, 0, 0, 0, 0)
                    else:
                        b_idx = (ext_idx - 1) % 1024
                        l6 = ((ext_idx - 1) // 1024) + 1
                        digits = []
                        temp = b_idx
                        for _ in range(5):
                            digits.append(temp % 4)
                            temp //= 4
                        stack = (l6,) + tuple(reversed(digits))
                    ext_stacks.append(stack)

            padded_base = [(-1,) + s for s in base_stacks]
            stacks = padded_base + ext_stacks

            stacks_arr = np.array(stacks[:count])
            return (rgb, _remap_stacks(stacks_arr, color_mode, lut_path, metadata=metadata))

        else:
            layer_count = 5
            if ColorSystem:
                layer_count = ColorSystem.get(color_mode).get('layer_count', 5)
            stacks = np.zeros((count, layer_count), dtype=np.int32)
            return (rgb, stacks)

    @staticmethod
    def validate_print_params(metadata_list: list) -> tuple:
        """Validate print parameter consistency across multiple LUTMetadata.
        校验多个 LUTMetadata 的打印参数一致性。

        Args:
            metadata_list (list[LUTMetadata]): List of metadata to validate.
                (待校验的元数据列表)

        Returns:
            tuple[bool, list[str]]: (all_compatible, warning_messages).
                (全部兼容, 警告信息列表)
        """
        if not metadata_list or len(metadata_list) < 2:
            return (True, [])

        warnings = []

        # Collect unique layer_height_mm values (rounded to avoid float issues)
        heights = set()
        for m in metadata_list:
            heights.add(round(m.layer_height_mm, 4))

        if len(heights) > 1:
            vals = ", ".join(f"{h:.4f}" for h in sorted(heights))
            warnings.append(
                f"layer_height_mm 不一致: {vals}"
            )

        # Collect unique line_width_mm values
        widths = set()
        for m in metadata_list:
            widths.add(round(m.line_width_mm, 4))

        if len(widths) > 1:
            vals = ", ".join(f"{w:.4f}" for w in sorted(widths))
            warnings.append(
                f"line_width_mm 不一致: {vals}"
            )

        all_compatible = len(warnings) == 0
        return (all_compatible, warnings)

    @staticmethod
    def merge_palettes(metadata_list: list, mode_priorities: list) -> list:
        """Merge palettes from multiple LUTMetadata using Color_Name as key.
        以 Color_Name 为匹配键合并多组调色板，按 8-Color 槽位排序。

        Priority resolution: higher priority value wins for hex_color/material.
        优先级解决：更高优先级的 LUT 的 hex_color/material 值被保留。

        Args:
            metadata_list (list[LUTMetadata]): List of metadata to merge.
                (待合并的元数据列表)
            mode_priorities (list[int]): Priority for each metadata (higher = more priority).
                (每个元数据的优先级，越高越优先)

        Returns:
            list[PaletteEntry]: Merged palette sorted by 8-Color slot order.
                (按 8-Color 槽位排序的合并调色板)
        """
        # Dict keyed by color name → (PaletteEntry, priority)
        merged: dict[str, tuple] = {}

        for meta, priority in zip(metadata_list, mode_priorities):
            for entry in meta.palette:
                name = entry.color
                if name not in merged or priority > merged[name][1]:
                    merged[name] = (entry, priority)
                elif priority == merged[name][1]:
                    # Same priority — keep existing (first encountered)
                    pass

        # Build result sorted by standard slot order, then custom colors
        standard_entries = []
        custom_entries = []

        for slot_name in _STANDARD_SLOT_ORDER:
            if slot_name in merged:
                standard_entries.append(merged.pop(slot_name)[0])

        # Remaining are custom colors — sort alphabetically
        for name in sorted(merged.keys()):
            custom_entries.append(merged[name][0])

        return standard_entries + custom_entries

    @staticmethod
    def build_channel_remap_by_name(source_palette: list, target_palette: list) -> dict:
        """Build channel remap table from source to target palette by color name.
        根据颜色名称构建源调色板到目标调色板的通道重映射表。

        Args:
            source_palette (list[PaletteEntry]): Source palette entries.
                (源调色板条目)
            target_palette (list[PaletteEntry]): Target palette entries.
                (目标调色板条目)

        Returns:
            dict[int, int]: Mapping source index → target index.
                (源索引 → 目标索引的映射)
        """
        # Build target name → index lookup
        target_lookup: dict[str, int] = {}
        for idx, entry in enumerate(target_palette):
            target_lookup[entry.color] = idx

        remap: dict[int, int] = {}
        for src_idx, entry in enumerate(source_palette):
            if entry.color in target_lookup:
                remap[src_idx] = target_lookup[entry.color]

        return remap

    @staticmethod
    def merge_luts(lut_entries, dedup_threshold=3.0, metadata_list=None, output_path=None, source_names=None):
        """执行LUT合并，支持可选的元数据集成。
        Execute LUT merge with optional metadata integration.

        Args:
            lut_entries: [(rgb_array, stacks_array, color_mode), ...]
            dedup_threshold: Delta-E阈值，0表示仅精确去重
            metadata_list (list[LUTMetadata] | None): Optional metadata for each LUT entry.
                (每个 LUT 条目的可选元数据)
            output_path (str | None): Optional output path; if provided, saves merged .npz
                with metadata. (可选输出路径；若提供则保存含元数据的 .npz)
            source_names (list[str] | None): Optional display names for each LUT entry,
                used to tag every merged entry with its origin LUT.
                (每个 LUT 条目的显示名称，用于标记合并后每条记录的来源)

        Returns:
            (merged_rgb[M,3], merged_stacks[M,L], stats_dict) where L is layer_count.
            stats_dict includes 'warnings', 'merged_metadata', and 'entry_sources' keys.
        """
        if not lut_entries:
            raise ValueError("No LUT entries to merge")

        total_before = sum(rgb.shape[0] for rgb, _, _ in lut_entries)

        # --- Metadata integration ---
        warnings_list = []
        merged_metadata = None
        merged_palette = []

        if metadata_list and LUTMetadata and PaletteEntry:
            # Auto-infer default palette for LUTs with empty palette
            # 使用副本避免修改调用方持有的原始对象
            import copy
            metadata_list = [copy.copy(m) for m in metadata_list]
            for i, meta in enumerate(metadata_list):
                if not meta.palette:
                    mode = lut_entries[i][2]
                    if ColorSystem:
                        color_conf = ColorSystem.get(mode)
                        slots = color_conf.get("slots", [])
                        meta.palette = [
                            PaletteEntry(color=name, material="PLA Basic")
                            for name in slots
                        ]

            # Validate print params
            _, warnings_list = LUTMerger.validate_print_params(metadata_list)

            # Build mode priorities from lut_entries color_mode
            mode_priorities = [
                _MODE_PRIORITY.get(entry[2], 0)
                for entry in lut_entries
            ]

            # Merge palettes
            merged_palette = LUTMerger.merge_palettes(metadata_list, mode_priorities)

            # Merged print params: use highest priority LUT's values
            best_idx = 0
            best_priority = -999
            for i, entry in enumerate(lut_entries):
                p = _MODE_PRIORITY.get(entry[2], 0)
                if p > best_priority:
                    best_priority = p
                    best_idx = i

            best_meta = metadata_list[best_idx]
            merged_metadata = LUTMetadata(
                palette=merged_palette,
                max_color_layers=best_meta.max_color_layers,
                layer_height_mm=best_meta.layer_height_mm,
                line_width_mm=best_meta.line_width_mm,
                base_layers=best_meta.base_layers,
                base_channel_idx=best_meta.base_channel_idx,
                layer_order=best_meta.layer_order,
            )

        # 1. 按色彩模式优先级排序（高优先级在前）
        # 同时保持 source_names 的对应关系
        indexed_entries = list(enumerate(lut_entries))
        indexed_entries.sort(
            key=lambda ie: _MODE_PRIORITY.get(ie[1][2], 0),
            reverse=True
        )
        sorted_entries = [ie[1] for ie in indexed_entries]
        sorted_source_names = (
            [source_names[ie[0]] for ie in indexed_entries]
            if source_names
            else [f"LUT-{ie[0]}" for ie in indexed_entries]
        )

        # 2. 拼接所有数据，同时记录每个颜色的来源模式和来源名称
        all_rgb = []
        all_stacks = []
        all_modes = []
        all_sources = []
        for entry_idx, (rgb, stacks, mode) in enumerate(sorted_entries):
            src_name = sorted_source_names[entry_idx]
            for i in range(rgb.shape[0]):
                all_rgb.append(tuple(rgb[i]))
                all_stacks.append(tuple(stacks[i]))
                all_modes.append(mode)
                all_sources.append(src_name)

        # 3. 精确去重（相同RGB值，保留优先级高的，即排在前面的）
        seen_rgb = {}
        unique_rgb = []
        unique_stacks = []
        unique_modes = []
        unique_sources = []
        exact_dupes = 0

        for i in range(len(all_rgb)):
            rgb_key = all_rgb[i]
            if rgb_key in seen_rgb:
                exact_dupes += 1
            else:
                seen_rgb[rgb_key] = True
                unique_rgb.append(all_rgb[i])
                unique_stacks.append(all_stacks[i])
                unique_modes.append(all_modes[i])
                unique_sources.append(all_sources[i])

        # 4. Delta-E 相近色去除
        similar_removed = 0
        if dedup_threshold > 0 and len(unique_rgb) > 1:
            # 转换为 Lab 色彩空间
            lab_colors = []
            for r, g, b in unique_rgb:
                srgb = sRGBColor(r / 255.0, g / 255.0, b / 255.0)
                lab = convert_color(srgb, LabColor)
                lab_colors.append(lab)

            kept_indices = []
            for i in range(len(unique_rgb)):
                is_similar = False
                for j in kept_indices:
                    try:
                        de = delta_e_cie2000(lab_colors[i], lab_colors[j])
                        if de < dedup_threshold:
                            is_similar = True
                            break
                    except Exception:
                        continue
                if not is_similar:
                    kept_indices.append(i)
                else:
                    similar_removed += 1

            unique_rgb = [unique_rgb[i] for i in kept_indices]
            unique_stacks = [unique_stacks[i] for i in kept_indices]
            unique_modes = [unique_modes[i] for i in kept_indices]
            unique_sources = [unique_sources[i] for i in kept_indices]

        merged_rgb = np.array(unique_rgb, dtype=np.uint8)
        merged_stacks = np.array(unique_stacks, dtype=np.int32)

        stats = {
            'total_before': total_before,
            'total_after': len(unique_rgb),
            'exact_dupes': exact_dupes,
            'similar_removed': similar_removed,
            'warnings': warnings_list,
            'merged_metadata': merged_metadata,
            'entry_sources': unique_sources,
        }

        # Save with metadata if output_path provided
        if output_path and merged_metadata:
            try:
                from utils.lut_manager import LUTManager
                LUTManager.save_npz_with_metadata(
                    output_path, merged_rgb, merged_stacks, merged_metadata
                )
            except Exception as e:
                print(f"[WARNING] Failed to save merged LUT with metadata: {e}")

        return (merged_rgb, merged_stacks, stats)

    @staticmethod
    def save_merged_lut(rgb, stacks, output_path):
        """保存合并后的LUT为.npz格式

        Args:
            rgb: RGB数组 [M,3]
            stacks: 堆叠数组 [M,5]
            output_path: 输出路径（.npz后缀）

        Returns:
            保存的文件路径
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # 确保后缀为 .npz
        if not output_path.endswith('.npz'):
            output_path = output_path.rsplit('.', 1)[0] + '.npz'

        np.savez(
            output_path,
            rgb=np.asarray(rgb, dtype=np.uint8),
            stacks=np.asarray(stacks, dtype=np.int32),
        )

        return output_path
