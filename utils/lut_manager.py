"""
Lumina Studio - LUT Preset Manager
LUT preset management module
"""

import os
import re
import sys
import shutil
import glob
from pathlib import Path


class LUTManager:
    """LUT preset manager"""
    
    # LUT preset folder path - handle both dev and frozen modes
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        # Check multiple possible locations
        exe_dir = os.path.dirname(sys.executable)
        
        # Try exe directory first (where we copy it in the spec file)
        if os.path.exists(os.path.join(exe_dir, "lut-npy预设")):
            LUT_PRESET_DIR = os.path.join(exe_dir, "lut-npy预设")
        # Then try _internal directory (fallback)
        elif os.path.exists(os.path.join(exe_dir, "_internal", "lut-npy预设")):
            LUT_PRESET_DIR = os.path.join(exe_dir, "_internal", "lut-npy预设")
        # Finally try _MEIPASS (bundled resources)
        elif hasattr(sys, '_MEIPASS') and os.path.exists(os.path.join(sys._MEIPASS, "lut-npy预设")):
            LUT_PRESET_DIR = os.path.join(sys._MEIPASS, "lut-npy预设")
        else:
            # Fallback to exe directory (will be created if needed)
            LUT_PRESET_DIR = os.path.join(exe_dir, "lut-npy预设")
    else:
        # Running as script
        _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        LUT_PRESET_DIR = os.path.join(_BASE_DIR, "lut-npy预设")
    
    @classmethod
    def get_all_lut_files(cls) -> dict[str, str]:
        """Scan and return all available LUT files.
        扫描并返回所有可用的 LUT 文件。

        Returns:
            dict[str, str]: 映射 {显示名称: 文件路径}。
        """
        lut_files = {}
        
        if not os.path.exists(cls.LUT_PRESET_DIR):
            print(f"[LUT_MANAGER] Warning: LUT preset directory not found: {cls.LUT_PRESET_DIR}")
            return lut_files
        
        # Recursively search for all .npy and .npz files
        npy_pattern = os.path.join(cls.LUT_PRESET_DIR, "**", "*.npy")
        npz_pattern = os.path.join(cls.LUT_PRESET_DIR, "**", "*.npz")
        
        all_files = glob.glob(npy_pattern, recursive=True) + glob.glob(npz_pattern, recursive=True)
        
        for file_path in all_files:
            # Generate friendly display name
            rel_path = os.path.relpath(file_path, cls.LUT_PRESET_DIR)
            
            # Extract brand/folder name
            parts = Path(rel_path).parts
            if len(parts) > 1:
                # Has subfolder, format: Brand - Filename
                brand = parts[0]
                filename = Path(parts[-1]).stem  # Remove .npy/.npz extension
                display_name = f"{brand} - {filename}"
            else:
                # Root directory file, use filename directly
                filename = Path(rel_path).stem
                display_name = filename
            
            lut_files[display_name] = file_path
        
        # Sort by name
        lut_files = dict(sorted(lut_files.items()))
        
        print(f"[LUT_MANAGER] Found {len(lut_files)} LUT presets")
        return lut_files
    
    @classmethod
    def get_lut_choices(cls):
        """
        Get LUT choice list (for Dropdown).
        获取 LUT 选择列表（用于下拉菜单）。

        Returns:
            list: Display name list / 显示名称列表
        """
        lut_files = cls.get_all_lut_files()
        return list(lut_files.keys())

    @staticmethod
    def infer_color_mode(display_name: str, file_path: str) -> str:
        """Infer color mode from LUT display name or file path.
        根据 LUT 显示名称或文件路径推断颜色模式。

        Args:
            display_name: LUT 显示名称。
            file_path: LUT 文件路径。

        Returns:
            str: 推断出的颜色模式字符串，与前端 ColorMode 枚举对应。
        """
        combined = (display_name + " " + file_path).upper()

        # .npz 文件通常是合并 LUT
        if file_path.lower().endswith(".npz"):
            return "Merged"

        # ── 第一优先：明确数字关键词（不存在跨模式歧义）──────────────────
        if "8色" in combined or "8-COLOR" in combined or "8COLOR" in combined:
            return "8-Color Max"
        if "6色" in combined or "6-COLOR" in combined or "6COLOR" in combined:
            return "6-Color (Smart 1296)"
        if "4色" in combined or "4-COLOR" in combined or "4COLOR" in combined:
            return "4-Color"
        if "黑白" in combined or "B&W" in combined:
            return "BW (Black & White)"
        if re.search(r"(?<![A-Z])BW(?![A-Z])", combined):
            return "BW (Black & White)"

        # ── 第二优先：文件大小（比颜色系关键词更可靠）──────────────────
        # RYBW / CMYW 同时出现在 4-色（RYBW/CMYW）和 6-色（RYBWGK/CMYWGK）文件名中，
        # 必须先用文件大小消歧，再用颜色系关键词。
        if file_path and os.path.exists(file_path) and file_path.lower().endswith(".npy"):
            try:
                import numpy as np
                total_colors = np.load(file_path).reshape(-1, 3).shape[0]
                if total_colors >= 2600:
                    return "8-Color Max"
                if total_colors >= 1200:
                    return "6-Color (Smart 1296)"
                if total_colors <= 36:
                    return "BW (Black & White)"
                # total_colors in 37..1199 → 4-Color，继续往下用关键词区分子类型
            except Exception:
                pass

        # ── 第三优先：颜色系关键词（仅在确认为 4-色时区分子类型）────────
        if "CMYW" in combined or "青品黄" in combined:
            return "4-Color"
        if "RYBW" in combined or "红黄蓝" in combined:
            return "4-Color"

        # 默认回退为 4-Color
        return "4-Color"
    
    @classmethod
    def get_lut_path(cls, display_name: str) -> str | None:
        """Get LUT file path by display name.
        根据显示名称获取 LUT 文件路径。

        Args:
            display_name: LUT 显示名称。

        Returns:
            str | None: 文件路径，未找到时返回 None。
        """
        lut_files = cls.get_all_lut_files()
        return lut_files.get(display_name)
    
    @classmethod
    def save_uploaded_lut(cls, uploaded_file, custom_name=None):
        """
        Save user-uploaded LUT file to preset folder
        
        Args:
            uploaded_file: Gradio uploaded file object
            custom_name: Custom filename (optional)
        
        Returns:
            tuple: (success_flag, message, new_choice_list)
        """
        if uploaded_file is None:
            return False, "[ERROR] No file selected", cls.get_lut_choices()
        
        try:
            # Ensure preset folder exists
            custom_dir = os.path.join(cls.LUT_PRESET_DIR, "Custom")
            os.makedirs(custom_dir, exist_ok=True)
            
            # Get original filename and extension
            original_path = Path(uploaded_file.name)
            original_name = original_path.stem
            file_extension = original_path.suffix  # .npy
            
            # Validate file extension
            if file_extension not in ('.npy', '.npz'):
                return False, f"[ERROR] Invalid file type: {file_extension}. Only .npy and .npz are supported.", cls.get_lut_choices()
            
            # Use custom name or original name
            if custom_name and custom_name.strip():
                final_name = custom_name.strip()
            else:
                final_name = original_name
            
            # Ensure filename is safe
            final_name = "".join(c for c in final_name if c.isalnum() or c in (' ', '-', '_', '中', '文'))
            final_name = final_name.strip()
            
            if not final_name:
                final_name = "custom_lut"
            
            # Build target path with correct extension
            dest_path = os.path.join(custom_dir, f"{final_name}{file_extension}")
            
            # If file exists, add numeric suffix
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(custom_dir, f"{final_name}_{counter}{file_extension}")
                counter += 1
            
            # Copy file
            shutil.copy2(uploaded_file.name, dest_path)
            
            # Build display name
            display_name = f"Custom - {Path(dest_path).stem}"
            
            print(f"[LUT_MANAGER] Saved uploaded LUT: {dest_path}")
            
            return True, f"[OK] LUT saved: {display_name}\nPlease select from dropdown to use", cls.get_lut_choices()
            
        except Exception as e:
            print(f"[LUT_MANAGER] Error saving LUT: {e}")
            return False, f"[ERROR] Save failed: {e}", cls.get_lut_choices()
    
    @classmethod
    def delete_lut(cls, display_name):
        """
        Delete specified LUT preset
        
        Args:
            display_name: Display name
        
        Returns:
            tuple: (success_flag, message, new_choice_list)
        """
        file_path = cls.get_lut_path(display_name)
        
        if not file_path:
            return False, "[ERROR] File not found", cls.get_lut_choices()
        
        # Only allow deleting files in Custom folder
        if "Custom" not in file_path:
            return False, "[ERROR] Can only delete custom LUTs", cls.get_lut_choices()
        
        try:
            os.remove(file_path)
            print(f"[LUT_MANAGER] Deleted LUT: {file_path}")
            return True, f"[OK] Deleted: {display_name}", cls.get_lut_choices()
        except Exception as e:
            print(f"[LUT_MANAGER] Error deleting LUT: {e}")
            return False, f"[ERROR] Delete failed: {e}", cls.get_lut_choices()
