"""
UI Auto-Detection Functions

自动检测功能，用于 UI 自动切换模式和选项。
"""

import os
import numpy as np

from config import ColorMode, ColorSystem


def detect_lut_color_mode(lut_path):
    """
    自动检测LUT文件的颜色模式

    Args:
        lut_path: LUT文件路径

    Returns:
        str: 颜色模式枚举值（用于 UI Radio 的 value）
    """
    if not lut_path or not os.path.exists(lut_path):
        return None

    try:
        lut_data = np.load(lut_path)
        total_colors = (
            lut_data.shape[0] * lut_data.shape[1]
            if lut_data.ndim >= 2
            else len(lut_data)
        )

        print(
            f"[AUTO_DETECT] LUT shape: {lut_data.shape}, total colors: {total_colors}"
        )

        # 8色模式：2738色 (8^5 = 32768)，但实际智能选择2738)
        if total_colors >= 2600 and total_colors <= 2800:
            print(f"[AUTO_DETECT] Detected 8-Color mode (2738 colors)")
            return ColorMode.EIGHT_COLOR_MAX.value

        # 6色模式：1296色 (6^5 = 7776)，但实际选择1296)
        elif total_colors >= 1200 and total_colors <= 1400:
            print(f"[AUTO_DETECT] Detected 6-Color mode (1296 colors)")
            return ColorMode.SIX_COLOR.value

        # 4色模式：1024色 (4^5 = 1024)
        elif total_colors >= 900 and total_colors <= 1100:
            print(f"[AUTO_DETECT] Detected 4-Color mode (1024 colors)")
            # 尝试从文件名推断CMYW或RYBW
            filename = os.path.basename(lut_path)
            name_lower = filename.lower()
            if "cmyw" in name_lower:
                print(f"[AUTO_DETECT] Filename suggests CMYW mode")
                return ColorMode.CMYW.value
            if "rybw" in name_lower:
                print(f"[AUTO_DETECT] Filename suggests RYBW mode")
                return ColorMode.RYBW.value
            # 无法推断时返回None，保持当前选择
            print(f"[AUTO_DETECT] Cannot infer 4-Color subtype from filename")
            return None

        else:
            print(f"[AUTO_DETECT] Unknown LUT format with {total_colors} colors")
            return None

    except Exception as e:
        print(f"[AUTO_DETECT] Error detecting LUT mode: {e}")
        return None


def detect_image_type(image_path):
    """
    自动检测图像类型并返回推荐的建模模式

    Args:
        image_path: 图像文件路径

    Returns:
        str: 建模模式 ("🎨 High-Fidelity (Smooth)", "📐 SVG Mode") 或 None
    """
    if not image_path:
        return None

    try:
        # 检查文件扩展名
        ext = os.path.splitext(image_path)[1].lower()

        if ext == ".svg":
            print(f"[AUTO_DETECT] SVG file detected, recommending SVG Mode")
            return "📐 SVG Mode"
        else:
            print(f"[AUTO_DETECT] Raster image detected ({ext}), keeping current mode")
            return None  # 不自动切换光栅图像模式

    except Exception as e:
        print(f"[AUTO_DETECT] Error detecting image type: {e}")
        return None
