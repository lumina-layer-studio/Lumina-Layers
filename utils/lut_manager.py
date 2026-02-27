"""
Lumina Studio - LUT Preset Manager
LUT preset management module
"""

import os
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
    
    @staticmethod
    def _build_stacks_path(lut_path: str) -> str:
        """根据 LUT 文件路径构建对应的 stacks 文件路径
        
        命名约定: {base}_stacks.npy
        与 core/image_processing.py 中 _load_lut 的 companion stacks 查找逻辑一致:
            base_path, ext = os.path.splitext(lut_path)
            companion_stacks_path = base_path + "_stacks.npy"
        """
        base, ext = os.path.splitext(lut_path)
        return f"{base}_stacks{ext}"

    @classmethod
    def validate_stacks_file(cls, stacks_path, lut_path=None):
        """验证 stacks 文件的有效性
        
        Args:
            stacks_path: stacks 文件路径
            lut_path: 对应的 LUT 文件路径（用于数量匹配检查，可选）
        
        Returns:
            tuple: (is_valid, message)
        """
        import numpy as np
        
        try:
            stacks_data = np.load(stacks_path)
        except Exception as e:
            return False, f"Stacks 文件格式无效：{e}"
        
        # 检查数组维度（至少 1 维）
        if stacks_data.ndim < 1:
            return False, "Stacks 文件不是有效的数组"
        
        # 如果提供了 lut_path，比较 stacks 行数与 LUT 颜色数是否匹配
        if lut_path and os.path.exists(lut_path):
            try:
                lut_data = np.load(lut_path)
                lut_colors = lut_data.reshape(-1, 3).shape[0] if lut_data.ndim >= 1 else 0
                if len(stacks_data) != lut_colors:
                    return False, f"Stacks 行数 ({len(stacks_data)}) 与 LUT 颜色数 ({lut_colors}) 不匹配"
            except Exception:
                pass  # LUT 验证失败不阻止 stacks 保存
        
        return True, "验证通过"

    @classmethod
    def get_all_lut_files(cls):
        """
        Scan and return all available LUT files
        
        Returns:
            dict: {display_name: file_path}
        """
        lut_files = {}
        
        if not os.path.exists(cls.LUT_PRESET_DIR):
            print(f"[LUT_MANAGER] Warning: LUT preset directory not found: {cls.LUT_PRESET_DIR}")
            return lut_files
        
        # Recursively search for all .npy files
        npy_pattern = os.path.join(cls.LUT_PRESET_DIR, "**", "*.npy")
        
        all_files = glob.glob(npy_pattern, recursive=True)
        
        for file_path in all_files:
            # 过滤 _stacks.npy 文件，不在 LUT 列表中显示
            if file_path.endswith("_stacks.npy"):
                continue
            
            # Generate friendly display name
            rel_path = os.path.relpath(file_path, cls.LUT_PRESET_DIR)
            
            # Extract brand/folder name
            parts = Path(rel_path).parts
            if len(parts) > 1:
                # Has subfolder, format: Brand - Filename
                brand = parts[0]
                filename = Path(parts[-1]).stem  # Remove .npy extension
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
        Get LUT choice list (for Dropdown)
        
        Returns:
            list: Display name list
        """
        lut_files = cls.get_all_lut_files()
        return list(lut_files.keys())
    
    @classmethod
    def get_lut_path(cls, display_name):
        """
        Get LUT file path by display name
        
        Args:
            display_name: Display name
        
        Returns:
            str: File path, returns None if not found
        """
        lut_files = cls.get_all_lut_files()
        return lut_files.get(display_name)
    
    @classmethod
    def save_uploaded_lut(cls, uploaded_file, stacks_file=None, meta_file=None, custom_name=None):
        """
        Save user-uploaded LUT file to preset folder
        
        Args:
            uploaded_file: Gradio uploaded file object
            stacks_file: Gradio uploaded stacks file object (optional)
            meta_file: Gradio uploaded meta.json file object (optional)
            custom_name: Custom filename (optional)
        
        Returns:
            tuple: (success_flag, message, new_choice_list)
        """
        if uploaded_file is None:
            if stacks_file is not None:
                return False, "❌ 请先上传 LUT 文件", cls.get_lut_choices(), None
            return False, "❌ No file selected", cls.get_lut_choices(), None
        
        try:
            # Ensure preset folder exists
            custom_dir = os.path.join(cls.LUT_PRESET_DIR, "Custom")
            os.makedirs(custom_dir, exist_ok=True)
            
            # Get original filename and extension
            original_path = Path(uploaded_file.name)
            original_name = original_path.stem
            file_extension = original_path.suffix  # .npy
            
            # Validate file extension
            if file_extension != '.npy':
                return False, f"❌ Invalid file type: {file_extension}. Only .npy is supported.", cls.get_lut_choices(), None
            
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
            
            message = f"✅ LUT saved: {display_name}"
            
            # 保存 stacks 文件（如果提供）
            if stacks_file is not None:
                try:
                    stacks_dest = cls._build_stacks_path(dest_path)
                    is_valid, validation_msg = cls.validate_stacks_file(
                        stacks_file.name, dest_path
                    )
                    if is_valid:
                        shutil.copy2(stacks_file.name, stacks_dest)
                        message += f"\n✅ Stacks 文件已保存"
                        print(f"[LUT_MANAGER] Saved stacks file: {stacks_dest}")
                    else:
                        message += f"\n⚠️ {validation_msg}（Stacks 文件未保存，不影响 LUT）"
                except Exception as e:
                    print(f"[LUT_MANAGER] Error saving stacks file: {e}")
                    message += f"\n⚠️ Stacks 保存失败：{e}（LUT 已正常保存）"
            
            # 保存 meta.json 文件（如果提供）
            if meta_file is not None:
                try:
                    base, _ext = os.path.splitext(dest_path)
                    meta_dest = base + "_meta.json"
                    shutil.copy2(meta_file.name, meta_dest)
                    message += f"\n✅ 耗材元数据已保存"
                    print(f"[LUT_MANAGER] Saved meta file: {meta_dest}")
                except Exception as e:
                    print(f"[LUT_MANAGER] Error saving meta file: {e}")
                    message += f"\n⚠️ Meta 保存失败：{e}（LUT 已正常保存）"
            
            return True, message, cls.get_lut_choices(), display_name
            
        except Exception as e:
            print(f"[LUT_MANAGER] Error saving LUT: {e}")
            return False, f"❌ Save failed: {e}", cls.get_lut_choices(), None
    
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
            return False, "❌ File not found", cls.get_lut_choices()
        
        # Only allow deleting files in Custom folder
        if "Custom" not in file_path:
            return False, "❌ Can only delete custom LUTs", cls.get_lut_choices()
        
        try:
            os.remove(file_path)
            
            # 联动删除 companion stacks 文件
            try:
                stacks_path = cls._build_stacks_path(file_path)
                if os.path.exists(stacks_path):
                    os.remove(stacks_path)
                    print(f"[LUT_MANAGER] Deleted companion stacks: {stacks_path}")
            except Exception as e:
                print(f"[LUT_MANAGER] Warning: Failed to delete companion stacks: {e}")
            
            # 联动删除 companion _meta.json 文件
            try:
                base, _ext = os.path.splitext(file_path)
                meta_path = base + "_meta.json"
                if os.path.exists(meta_path):
                    os.remove(meta_path)
                    print(f"[LUT_MANAGER] Deleted companion metadata: {meta_path}")
            except Exception as e:
                print(f"[LUT_MANAGER] Warning: Failed to delete companion metadata: {e}")
            
            print(f"[LUT_MANAGER] Deleted LUT: {file_path}")
            return True, f"✅ Deleted: {display_name}", cls.get_lut_choices()
        except Exception as e:
            print(f"[LUT_MANAGER] Error deleting LUT: {e}")
            return False, f"❌ Delete failed: {e}", cls.get_lut_choices()

