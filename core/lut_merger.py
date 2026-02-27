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


# Color mode size mapping
_SIZE_TO_MODE = {
    32: "BW",
    1024: "4-Color",
    1296: "6-Color",
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
    "6-Color": 2,
    "8-Color": 3,
}

# Max material ID per mode
_MODE_MAX_MATERIAL = {
    "BW": 1,
    "4-Color": 3,
    "6-Color": 5,
    "8-Color": 7,
    "Merged": 7,
}

# Material ID remapping tables: source mode → 8-Color material IDs
# 8-Color slots: 0=White, 1=Cyan, 2=Magenta, 3=Yellow, 4=Black, 5=Red, 6=DeepBlue, 7=Green
_REMAP_TO_8COLOR = {
    "BW": {0: 0, 1: 4},           # White→White, Black→Black
    "4-Color-RYBW": {0: 0, 1: 5, 2: 3, 3: 6},  # White→White, Red→Red, Yellow→Yellow, Blue→DeepBlue
    "4-Color-CMYW": {0: 0, 1: 1, 2: 2, 3: 3},   # White→White, Cyan→Cyan, Magenta→Magenta, Yellow→Yellow
    "6-Color": {0: 0, 1: 1, 2: 2, 3: 7, 4: 3, 5: 4},  # White→White, Cyan→Cyan, Magenta→Magenta, Green→Green, Yellow→Yellow, Black→Black
}


def _detect_4color_subtype(lut_path):
    """Detect 4-Color subtype (RYBW or CMYW) from filename.

    Naming convention: filename containing 'RYBW' → RYBW, 'CMYW' → CMYW.
    Default: RYBW (most common).
    """
    basename = os.path.basename(lut_path).upper()
    if "CMYW" in basename:
        return "4-Color-CMYW"
    return "4-Color-RYBW"


def _remap_stacks(stacks, color_mode, lut_path=None):
    """Remap material IDs in stacks from source mode to 8-Color space.

    When merging LUTs from different color modes, each mode uses its own
    material ID numbering. This function translates them all into the
    unified 8-Color numbering so the merged LUT produces correct meshes.

    Args:
        stacks: numpy array (N, 5) of material IDs
        color_mode: source color mode string
        lut_path: optional file path, used to detect 4-Color subtype

    Returns:
        numpy array (N, 5) with remapped material IDs
    """
    if color_mode == "8-Color" or color_mode == "Merged":
        return stacks  # Already in 8-Color space

    remap_key = color_mode
    if color_mode == "4-Color" and lut_path:
        remap_key = _detect_4color_subtype(lut_path)

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

        if lut_path.endswith('.npz'):
            data = np.load(lut_path)
            if 'rgb' in data and 'stacks' in data:
                count = data['rgb'].shape[0]
                return ("Merged", count)
            raise ValueError("Invalid .npz: missing 'rgb' or 'stacks' key")

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
            (rgb_array[N,3], stacks_array[N,5])
        """
        # .npz 格式直接读取
        if lut_path.endswith('.npz'):
            data = np.load(lut_path)
            return (data['rgb'], data['stacks'])

        # .npy 格式：加载 RGB，根据模式重建堆叠
        lut_data = np.load(lut_path)
        rgb = lut_data.reshape(-1, 3)
        count = rgb.shape[0]

        if color_mode == "BW":
            stacks = []
            for i in range(count):
                digits = []
                temp = i
                for _ in range(5):
                    digits.append(temp % 2)
                    temp //= 2
                stacks.append(tuple(reversed(digits)))
            # For non-standard BW sizes (e.g. 36), extra entries beyond 32
            # get stacks from modular arithmetic which may wrap, but RGB data is valid
            stacks_arr = np.array(stacks)
            return (rgb, _remap_stacks(stacks_arr, color_mode, lut_path))

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
            return (rgb, _remap_stacks(stacks_arr, color_mode, lut_path))

        elif color_mode == "6-Color":
            from core.calibration import get_top_1296_colors
            raw_stacks = get_top_1296_colors()
            # 约定转换：底到顶 → 顶到底
            stacks = [tuple(reversed(s)) for s in raw_stacks]
            min_len = min(len(stacks), count)
            stacks_arr = np.array(stacks[:min_len])
            return (rgb[:min_len], _remap_stacks(stacks_arr, color_mode, lut_path))

        elif color_mode == "8-Color":
            if getattr(sys, 'frozen', False):
                stacks_path = os.path.join(sys._MEIPASS, 'assets', 'smart_8color_stacks.npy')
            else:
                stacks_path = 'assets/smart_8color_stacks.npy'
            raw_stacks = np.load(stacks_path).tolist()
            # 约定转换：底到顶 → 顶到底
            stacks = [tuple(reversed(s)) for s in raw_stacks]
            min_len = min(len(stacks), count)
            return (rgb[:min_len], np.array(stacks[:min_len]))

        else:
            # Non-standard mode (e.g. "Merged" from non-standard .npy sizes)
            # Generate dummy stacks: all zeros (white-only base)
            # The RGB data is still valid for merging
            stacks = np.zeros((count, 5), dtype=np.int32)
            return (rgb, stacks)

    @staticmethod
    def merge_luts(lut_entries, dedup_threshold=3.0):
        """执行LUT合并

        Args:
            lut_entries: [(rgb_array, stacks_array, color_mode), ...]
            dedup_threshold: Delta-E阈值，0表示仅精确去重

        Returns:
            (merged_rgb[M,3], merged_stacks[M,5], stats_dict)
        """
        if not lut_entries:
            raise ValueError("No LUT entries to merge")

        total_before = sum(rgb.shape[0] for rgb, _, _ in lut_entries)

        # 1. 按色彩模式优先级排序（高优先级在前）
        sorted_entries = sorted(
            lut_entries,
            key=lambda e: _MODE_PRIORITY.get(e[2], 0),
            reverse=True
        )

        # 2. 拼接所有数据，同时记录每个颜色的来源模式
        all_rgb = []
        all_stacks = []
        all_modes = []
        for rgb, stacks, mode in sorted_entries:
            for i in range(rgb.shape[0]):
                all_rgb.append(tuple(rgb[i]))
                all_stacks.append(tuple(stacks[i]))
                all_modes.append(mode)

        # 3. 精确去重（相同RGB值，保留优先级高的，即排在前面的）
        seen_rgb = {}
        unique_rgb = []
        unique_stacks = []
        unique_modes = []
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

        merged_rgb = np.array(unique_rgb, dtype=np.uint8)
        merged_stacks = np.array(unique_stacks, dtype=np.int32)

        stats = {
            'total_before': total_before,
            'total_after': len(unique_rgb),
            'exact_dupes': exact_dupes,
            'similar_removed': similar_removed,
        }

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
