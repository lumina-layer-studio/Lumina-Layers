"""
Lumina Studio - LUT Preset Manager
LUT preset management module
"""

import os
import re
import sys
import json
import shutil
import glob
from pathlib import Path

import numpy as np

from config import LUTMetadata, PaletteEntry, ColorSystem, PrinterConfig


class LUTManager:
    """LUT preset manager"""
    
    # LUT preset folder path - handle both dev and frozen modes
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        # Check multiple possible locations
        exe_dir = os.path.dirname(sys.executable)
        
        # Try exe directory first (where we copy it in the spec file)
        if os.path.exists(os.path.join(exe_dir, "lut-preset")):
            LUT_PRESET_DIR = os.path.join(exe_dir, "lut-preset")
        # Then try _internal directory (fallback)
        elif os.path.exists(os.path.join(exe_dir, "_internal", "lut-preset")):
            LUT_PRESET_DIR = os.path.join(exe_dir, "_internal", "lut-preset")
        # Finally try _MEIPASS (bundled resources)
        elif hasattr(sys, '_MEIPASS') and os.path.exists(os.path.join(sys._MEIPASS, "lut-preset")):
            LUT_PRESET_DIR = os.path.join(sys._MEIPASS, "lut-preset")
        else:
            # Fallback to exe directory (will be created if needed)
            LUT_PRESET_DIR = os.path.join(exe_dir, "lut-preset")
    else:
        # Running as script
        _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        LUT_PRESET_DIR = os.path.join(_BASE_DIR, "lut-preset")
    
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
        
        # Recursively search for all .npy, .json and .npz files
        npy_pattern = os.path.join(cls.LUT_PRESET_DIR, "**", "*.npy")
        json_pattern = os.path.join(cls.LUT_PRESET_DIR, "**", "*.json")
        npz_pattern = os.path.join(cls.LUT_PRESET_DIR, "**", "*.npz")
        
        all_files = glob.glob(npy_pattern, recursive=True) + \
                    glob.glob(json_pattern, recursive=True) + \
                    glob.glob(npz_pattern, recursive=True)
        
        # Priority: .json > .npz > .npy (higher priority overwrites lower)
        _EXT_PRIORITY = {".npy": 0, ".npz": 1, ".json": 2}
        # Track priority of each display_name to avoid lower-priority overwrite
        _name_priority: dict[str, int] = {}
        
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
            
            ext = Path(file_path).suffix.lower()
            priority = _EXT_PRIORITY.get(ext, -1)
            
            if display_name not in lut_files or priority > _name_priority.get(display_name, -1):
                lut_files[display_name] = file_path
                _name_priority[display_name] = priority
        
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

    # JSON LUT 颜色数量 → 模式映射（与 lut_merger._SIZE_TO_MODE 对齐）
    # 1024 和 1296 已移除：多个变体共享相同数量（CMYW/RYBW 均为 1024，
    # 6-Color CMYW/RYBW 均为 1296），通过 _detect_variant_from_palette 处理
    _JSON_SIZE_TO_MODE: dict[int, str] = {
        32: "BW (Black & White)",
        2468: "5-Color Extended",
        2738: "8-Color Max",
    }

    @staticmethod
    def _detect_variant_from_palette(data: dict, base_mode: str) -> str:
        """Detect RYBW/CMYW variant from palette color names.
        从 palette 颜色名称推断 RYBW/CMYW 变体。

        For ambiguous entry counts (1024 for 4-Color, 1296 for 6-Color),
        inspect palette keys/color fields to distinguish RYBW from CMYW.
        对于有歧义的 entries 数量（4-Color 的 1024、6-Color 的 1296），
        通过检查 palette 的键名或 color 字段区分 RYBW 和 CMYW 变体。

        Args:
            data (dict): Parsed JSON data containing a "palette" field.
                         (包含 "palette" 字段的已解析 JSON 数据)
            base_mode (str): Base color mode without variant, e.g. "4-Color" or "6-Color".
                             (不含变体的基础颜色模式，如 "4-Color" 或 "6-Color")

        Returns:
            str: Full color mode string with variant, e.g. "4-Color (RYBW)".
                 (含变体的完整颜色模式字符串)
        """
        palette_raw = data.get("palette", {})
        color_names: set[str] = set()
        if isinstance(palette_raw, dict):
            color_names = {k.lower() for k in palette_raw.keys()}
        elif isinstance(palette_raw, list):
            color_names = {
                item.get("color", "").lower()
                for item in palette_raw
                if isinstance(item, dict)
            }

        rybw_indicators = {"red", "blue"}
        cmyw_indicators = {"cyan", "magenta"}

        if base_mode == "4-Color":
            if rybw_indicators & color_names:
                return "4-Color (RYBW)"
            if cmyw_indicators & color_names:
                return "4-Color (CMYW)"
            return "4-Color (CMYW)"  # default fallback

        if base_mode == "6-Color":
            if rybw_indicators & color_names:
                return "6-Color (RYBWGK 1296)"
            return "6-Color (CMYWGK 1296)"  # default fallback

        return f"{base_mode}"

    @staticmethod
    def infer_color_mode(display_name: str, file_path: str) -> str:
        """Infer color mode from LUT display name or file path.
        根据 LUT 显示名称或文件路径推断颜色模式。

        - .npz → 直接返回 "Merged"
        - .json → 轻量读取 JSON，按 entries 数量精确判断模式（自描述，不依赖文件名）
        - .npy → 按文件名关键词匹配

        Args:
            display_name: LUT 显示名称。
            file_path: LUT 文件路径。

        Returns:
            str: 推断出的颜色模式字符串，与前端 ColorMode 枚举对应。
        """
        ext = os.path.splitext(file_path)[1].lower()

        # .npz 文件通常是合并 LUT
        if ext == ".npz":
            return "Merged"

        # .json (Keyed JSON) — 自描述格式，从内容判断模式
        if ext == ".json":
            return LUTManager._infer_color_mode_from_json(file_path)

        # .npy — 无元数据，按文件名关键词匹配
        return LUTManager._infer_color_mode_by_name(display_name, file_path)

    @staticmethod
    def _infer_color_mode_from_json(file_path: str) -> str:
        """Infer color mode from JSON file content (lightweight read, no numpy).
        从 JSON 文件内容推断颜色模式（轻量读取，不做 numpy 运算）。

        Priority: stored color_mode > palette-based variant detection > size mapping.
        优先级：存储的 color_mode > 基于 palette 的变体检测 > 数量映射。

        支持两种 JSON 格式：
        - flat-list: 顶层为数组，len(data) 即 entries 数量
        - keyed: 顶层为对象，len(data["entries"]) 即 entries 数量
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[LUT_MANAGER] Failed to read JSON for mode detection: {e}")
            return "4-Color (CMYW)"

        # 计算 entries 数量
        if isinstance(data, list):
            count = len(data)
        elif isinstance(data, dict):
            # 优先使用存储的 color_mode
            stored_mode = data.get("color_mode")
            if stored_mode and isinstance(stored_mode, str):
                return stored_mode
            entries = data.get("entries", [])
            count = len(entries)
        else:
            count = 0

        # 对于有歧义的数量，通过 palette 名称区分变体
        if count == 1024 and isinstance(data, dict):
            return LUTManager._detect_variant_from_palette(data, "4-Color")
        if count == 1296 and isinstance(data, dict):
            return LUTManager._detect_variant_from_palette(data, "6-Color")

        # 无歧义的数量直接映射
        mode = LUTManager._JSON_SIZE_TO_MODE.get(count)
        if mode:
            return mode

        # BW 容差：30-36
        if 30 <= count <= 36:
            return "BW (Black & White)"

        # 非标准尺寸 → Merged
        if count > 0:
            return "Merged"

        # 空文件回退
        return "4-Color (CMYW)"

    @staticmethod
    def _infer_color_mode_by_name(display_name: str, file_path: str) -> str:
        """按文件名关键词匹配颜色模式（用于 .npy 等无元数据格式）。"""
        combined = (display_name + " " + file_path).upper()

        if "8色" in combined or "8-COLOR" in combined or "8COLOR" in combined:
            return "8-Color Max"
        if "6色" in combined or "6-COLOR" in combined or "6COLOR" in combined:
            if "RYBW" in combined or "红黄蓝" in combined:
                return "6-Color (RYBWGK 1296)"
            return "6-Color (CMYWGK 1296)"
        # 5-Color Extended 必须在 4-Color 之前检测
        if "5色" in combined or "5-COLOR" in combined or "5COLOR" in combined:
            return "5-Color Extended"
        # CMYW/RYBW 必须在 BW 之前检测，避免 "RYBW" 中的 "BW" 误匹配
        if "CMYW" in combined or "青品黄" in combined:
            return "4-Color (CMYW)"
        if "RYBW" in combined or "红黄蓝" in combined:
            return "4-Color (RYBW)"
        if "4色" in combined or "4-COLOR" in combined or "4COLOR" in combined:
            return "4-Color (CMYW)"
        # BW 单独检测
        if "黑白" in combined or "B&W" in combined:
            return "BW (Black & White)"
        if re.search(r"(?<![A-Z])BW(?![A-Z])", combined):
            return "BW (Black & White)"

        # 默认回退
        return "4-Color (CMYW)"
    
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
            if file_extension not in ('.npy', '.json', '.npz'):
                return False, f"[ERROR] Invalid file type: {file_extension}. Only .npy, .json and .npz are supported.", cls.get_lut_choices()
            
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
            
            # Auto-convert .npy to Keyed JSON
            if file_extension == '.npy':
                dest_extension = '.json'
            else:
                dest_extension = file_extension
            
            # Build target path with correct extension
            dest_path = os.path.join(custom_dir, f"{final_name}{dest_extension}")
            
            # If file exists, add numeric suffix
            counter = 1
            while os.path.exists(dest_path):
                dest_path = os.path.join(custom_dir, f"{final_name}_{counter}{dest_extension}")
                counter += 1
            
            if file_extension == '.npy':
                # Convert .npy to Keyed JSON
                try:
                    rgb = np.load(uploaded_file.name)
                    if rgb.ndim == 3:
                        rgb = rgb.reshape(-1, 3)
                    elif rgb.ndim == 1:
                        rgb = rgb.reshape(-1, 3)
                    metadata = cls.infer_default_metadata(final_name, uploaded_file.name, len(rgb))
                    stacks = np.zeros((len(rgb), 0), dtype=np.int32)
                    cls.save_keyed_json(dest_path, rgb, stacks, metadata)
                except Exception as e:
                    return False, f"[ERROR] Failed to convert .npy to JSON: {e}", cls.get_lut_choices()
            else:
                # Copy file directly for .json and .npz
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

    # ------------------------------------------------------------------
    # Metadata-aware loading / saving (Task 4)
    # ------------------------------------------------------------------

    @classmethod
    def infer_default_metadata(cls, display_name: str, file_path: str,
                               color_count: int,
                               color_mode: str | None = None) -> LUTMetadata:
        """Infer default LUTMetadata from filename and color count.
        根据文件名和颜色数量推断默认元数据。

        Args:
            display_name (str): LUT display name. (LUT 显示名称)
            file_path (str): LUT file path. (LUT 文件路径)
            color_count (int): Number of colors in the LUT. (LUT 中的颜色数量)
            color_mode (str | None): Optional color mode override; when provided,
                takes priority over inference. (可选颜色模式覆盖；传入时优先使用)

        Returns:
            LUTMetadata: Inferred default metadata. (推断的默认元数据)
        """
        mode = color_mode or cls.infer_color_mode(display_name, file_path)
        color_conf = ColorSystem.get(mode)
        slots = color_conf.get("slots", [])

        palette = [
            PaletteEntry(color=name, material="PLA Basic")
            for name in slots
        ]

        return LUTMetadata(
            palette=palette,
            color_mode=mode,
            max_color_layers=PrinterConfig.COLOR_LAYERS,
            layer_height_mm=PrinterConfig.LAYER_HEIGHT,
            line_width_mm=PrinterConfig.NOZZLE_WIDTH,
            base_layers=10,
            base_channel_idx=0,
            layer_order="Top2Bottom",
        )

    @classmethod
    def load_lut_with_metadata(cls, file_path: str) -> tuple[np.ndarray, np.ndarray | None, LUTMetadata]:
        """Load LUT file and return (rgb, stacks_or_None, metadata).
        统一加载 LUT 文件，返回 (rgb, stacks_or_None, metadata)。

        Supports .npy, .json (Keyed JSON), and .npz formats.
        支持 .npy、.json（Keyed JSON）和 .npz 三种格式。

        Args:
            file_path (str): Path to the LUT file. (LUT 文件路径)

        Returns:
            tuple: (rgb ndarray, stacks ndarray or None, LUTMetadata).
        """
        ext = os.path.splitext(file_path)[1].lower()
        display_name = Path(file_path).stem

        # ---- .npy format ----
        if ext == ".npy":
            try:
                rgb = np.load(file_path)
            except Exception as e:
                print(f"[WARNING] Failed to load .npy file {file_path}: {e}")
                rgb = np.zeros((0, 3), dtype=np.uint8)
            metadata = cls.infer_default_metadata(display_name, file_path, len(rgb))
            return rgb, None, metadata

        # ---- .json (Keyed JSON) format ----
        if ext == ".json":
            return cls._load_keyed_json(file_path, display_name)

        # ---- .npz format ----
        if ext == ".npz":
            return cls._load_npz(file_path, display_name)

        # Unsupported format – return empty defaults
        print(f"[WARNING] Unsupported LUT format: {ext}")
        rgb = np.zeros((0, 3), dtype=np.uint8)
        metadata = cls.infer_default_metadata(display_name, file_path, 0)
        return rgb, None, metadata

    # ---- private helpers ----

    @classmethod
    def _load_keyed_json(cls, file_path: str, display_name: str) -> tuple[np.ndarray, np.ndarray | None, LUTMetadata]:
        """Load a Keyed JSON LUT file.
        加载 Keyed JSON 格式的 LUT 文件。支持新对象格式和旧数组格式的 palette/recipe。
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"[WARNING] Failed to parse JSON file {file_path}: {e}")
            rgb = np.zeros((0, 3), dtype=np.uint8)
            metadata = cls.infer_default_metadata(display_name, file_path, 0)
            return rgb, None, metadata

        # ── 兼容顶层为数组的旧格式 ──────────────────────────────────
        # 格式: [{recipe: [...], rgb: [r,g,b], hex: "#...", source: "..."}, ...]
        if isinstance(data, list):
            return cls._load_keyed_json_flat_list(data, display_name, file_path)

        metadata = LUTMetadata.from_dict(data)

        # If palette is empty, infer defaults
        if not metadata.palette:
            print(f"[WARNING] No valid palette in {file_path}, inferring defaults")
            default_meta = cls.infer_default_metadata(display_name, file_path, 0)
            metadata.palette = default_meta.palette

        # Build name→index mapping for recipe resolution
        name_to_idx: dict[str, int] = {
            e.color: i for i, e in enumerate(metadata.palette)
        }

        # Parse entries → rgb + stacks
        entries = data.get("entries", [])
        rgb_list: list[list[int]] = []
        stacks_list: list[list[int]] = []

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            # Prefer stored RGB for exact roundtrip; fall back to Lab→RGB
            rgb_val = entry.get("rgb")
            hex_val = entry.get("hex")
            lab = entry.get("lab")
            
            if rgb_val and len(rgb_val) == 3:
                r = max(0, min(255, int(rgb_val[0])))
                g = max(0, min(255, int(rgb_val[1])))
                b = max(0, min(255, int(rgb_val[2])))
                rgb_list.append([r, g, b])
                
                # Optional: Validate hex consistency with RGB
                if hex_val:
                    expected_hex = f"#{r:02X}{g:02X}{b:02X}"
                    if hex_val.upper() != expected_hex:
                        print(f"[WARNING] Hex mismatch: RGB {rgb_val} → {expected_hex}, but stored as {hex_val}")
                        
            elif lab and len(lab) == 3:
                try:
                    from colormath.color_objects import LabColor, sRGBColor
                    from colormath.color_conversions import convert_color
                    lab_color = LabColor(float(lab[0]), float(lab[1]), float(lab[2]))
                    srgb = convert_color(lab_color, sRGBColor)
                    r = max(0, min(255, int(round(srgb.clamped_rgb_r * 255))))
                    g = max(0, min(255, int(round(srgb.clamped_rgb_g * 255))))
                    b = max(0, min(255, int(round(srgb.clamped_rgb_b * 255))))
                    rgb_list.append([r, g, b])
                except Exception as e:
                    print(f"[WARNING] Lab→RGB conversion failed for {lab}: {e}")
                    rgb_list.append([0, 0, 0])
            else:
                rgb_list.append([0, 0, 0])

            # Recipe: resolve color names to indices, support both formats
            recipe_raw = entry.get("recipe", [])
            recipe_indices: list[int] = []
            for v in recipe_raw:
                if isinstance(v, str):
                    # 新格式: 颜色名 → 索引
                    if v == "Air":
                        recipe_indices.append(-1)
                    elif v in name_to_idx:
                        recipe_indices.append(name_to_idx[v])
                    else:
                        print(f"[WARNING] Unknown color name in recipe: {v}")
                        recipe_indices.append(0)
                else:
                    # 旧格式兼容: 直接是数字索引
                    recipe_indices.append(int(v))
            stacks_list.append(recipe_indices)

        if rgb_list:
            rgb = np.array(rgb_list, dtype=np.uint8)
        else:
            rgb = np.zeros((0, 3), dtype=np.uint8)

        if stacks_list:
            stacks = np.array(stacks_list, dtype=np.int32)
        else:
            stacks = None

        return rgb, stacks, metadata

    @classmethod
    def _load_keyed_json_flat_list(
        cls,
        data: list,
        display_name: str,
        file_path: str,
    ) -> tuple[np.ndarray, np.ndarray | None, 'LUTMetadata']:
        """Load a flat-list JSON LUT: [{recipe, rgb, hex, source}, ...].
        加载顶层为数组的旧格式 JSON LUT 文件。
        """
        # 1. 收集所有出现的颜色名，构建 palette
        color_names_ordered: list[str] = []
        color_name_set: set[str] = set()
        for entry in data:
            if not isinstance(entry, dict):
                continue
            for v in entry.get("recipe", []):
                if isinstance(v, str) and v != "Air" and v not in color_name_set:
                    color_names_ordered.append(v)
                    color_name_set.add(v)

        palette = [
            PaletteEntry(color=name, material="PLA Basic", hex_color=None)
            for name in color_names_ordered
        ]
        name_to_idx: dict[str, int] = {name: i for i, name in enumerate(color_names_ordered)}

        # 2. 解析 rgb + stacks
        rgb_list: list[list[int]] = []
        stacks_list: list[list[int]] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            rgb_val = entry.get("rgb")
            if rgb_val and len(rgb_val) == 3:
                rgb_list.append([max(0, min(255, int(v))) for v in rgb_val])
            else:
                rgb_list.append([0, 0, 0])

            recipe_raw = entry.get("recipe", [])
            recipe_indices: list[int] = []
            for v in recipe_raw:
                if isinstance(v, str):
                    if v == "Air":
                        recipe_indices.append(-1)
                    elif v in name_to_idx:
                        recipe_indices.append(name_to_idx[v])
                    else:
                        recipe_indices.append(0)
                else:
                    recipe_indices.append(int(v))
            stacks_list.append(recipe_indices)

        rgb = np.array(rgb_list, dtype=np.uint8) if rgb_list else np.zeros((0, 3), dtype=np.uint8)
        stacks = np.array(stacks_list, dtype=np.int32) if stacks_list else None

        metadata = LUTMetadata(
            palette=palette,
            max_color_layers=PrinterConfig.COLOR_LAYERS,
            layer_height_mm=PrinterConfig.LAYER_HEIGHT,
            line_width_mm=PrinterConfig.NOZZLE_WIDTH,
            base_layers=10,
            base_channel_idx=0,
            layer_order="Top2Bottom",
        )
        print(f"[LUT_MANAGER] Loaded flat-list JSON: {len(rgb_list)} entries, {len(palette)} colors from {file_path}")
        if stacks is not None:
            print(f"[LUT_MANAGER] Generated stacks array: shape={stacks.shape}, dtype={stacks.dtype}")
        else:
            print(f"[LUT_MANAGER] WARNING: stacks is None!")
        return rgb, stacks, metadata

    @classmethod
    def _load_npz(cls, file_path: str, display_name: str) -> tuple[np.ndarray, np.ndarray | None, LUTMetadata]:
        """Load a .npz LUT file with optional metadata_json.
        加载 .npz 格式的 LUT 文件，解析可选的 metadata_json 键。
        """
        try:
            npz = np.load(file_path, allow_pickle=False)
        except Exception as e:
            print(f"[WARNING] Failed to load .npz file {file_path}: {e}")
            rgb = np.zeros((0, 3), dtype=np.uint8)
            metadata = cls.infer_default_metadata(display_name, file_path, 0)
            return rgb, None, metadata

        rgb = npz.get("rgb", np.zeros((0, 3), dtype=np.uint8))
        stacks = npz.get("stacks", None)

        # Parse metadata_json if present
        metadata_json_str = None
        if "metadata_json" in npz:
            try:
                metadata_json_str = str(npz["metadata_json"])
            except Exception:
                pass

        if metadata_json_str:
            try:
                meta_dict = json.loads(metadata_json_str)
                metadata = LUTMetadata.from_dict(meta_dict)
            except Exception as e:
                print(f"[WARNING] Failed to parse metadata_json in {file_path}: {e}")
                metadata = cls.infer_default_metadata(display_name, file_path, len(rgb))
        else:
            metadata = cls.infer_default_metadata(display_name, file_path, len(rgb))

        return rgb, stacks, metadata

    @classmethod
    def save_keyed_json(cls, path: str, rgb: np.ndarray, stacks: np.ndarray,
                        metadata: LUTMetadata, lab: np.ndarray | None = None,
                        sources: list[str] | None = None) -> None:
        """Save LUT data as Keyed JSON format.
        将 LUT 数据保存为 Keyed JSON 格式。

        Args:
            path (str): Output file path. (输出文件路径)
            rgb (np.ndarray): RGB array (N, 3) uint8. (RGB 数组)
            stacks (np.ndarray): Stacks array (N, L) int32. (堆叠配方数组)
            metadata (LUTMetadata): LUT metadata. (LUT 元数据)
            lab (np.ndarray | None): Optional Lab array (N, 3). If None, convert from RGB.
                                     (可选 Lab 数组，为 None 时从 RGB 转换)
            sources (list[str] | None): Optional per-entry source labels (e.g. origin LUT name).
                                        (可选的每条记录来源标识)
        """
        meta_dict = metadata.to_dict()

        # Build name from filename
        meta_dict["name"] = Path(path).stem

        # Build palette name list for recipe index → name mapping
        palette_names = [e.color for e in metadata.palette]

        # Build entries
        entries = []
        n = len(rgb)

        # Batch RGB → Lab conversion using OpenCV (much faster than per-entry colormath)
        if lab is None:
            import cv2
            rgb_arr = np.array(rgb[:n], dtype=np.uint8).reshape(1, n, 3)
            lab_arr = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2Lab).reshape(n, 3).astype(float)
            # OpenCV Lab range: L [0,255], a [0,255], b [0,255] → standard L [0,100], a [-128,127], b [-128,127]
            lab_arr[:, 0] = lab_arr[:, 0] * 100.0 / 255.0
            lab_arr[:, 1] = lab_arr[:, 1] - 128.0
            lab_arr[:, 2] = lab_arr[:, 2] - 128.0
        else:
            lab_arr = np.array(lab[:n], dtype=float)

        for i in range(n):
            entry: dict = {}
            # Store original RGB for exact roundtrip
            r, g, b = int(rgb[i][0]), int(rgb[i][1]), int(rgb[i][2])
            entry["rgb"] = [r, g, b]
            
            # Hex color representation (RGB → #RRGGBB)
            entry["hex"] = f"#{r:02X}{g:02X}{b:02X}"
            
            # Lab values (pre-computed batch)
            entry["lab"] = [
                round(float(lab_arr[i][0]), 6),
                round(float(lab_arr[i][1]), 6),
                round(float(lab_arr[i][2]), 6),
            ]

            # Recipe: use palette color names instead of numeric indices
            if stacks is not None and i < len(stacks):
                recipe_names = []
                for v in stacks[i]:
                    idx = int(v)
                    if idx == -1:
                        recipe_names.append("Air")
                    elif 0 <= idx < len(palette_names):
                        recipe_names.append(palette_names[idx])
                    else:
                        recipe_names.append(f"Unknown({idx})")
                entry["recipe"] = recipe_names
            else:
                entry["recipe"] = []

            # Source label (origin LUT name for merged entries)
            if sources and i < len(sources):
                entry["source"] = sources[i]

            entries.append(entry)

        meta_dict["entries"] = entries

        with open(path, "w", encoding="utf-8") as f:
            json.dump(meta_dict, f, ensure_ascii=False, indent=4)

    @classmethod
    def save_npz_with_metadata(cls, path: str, rgb: np.ndarray, stacks: np.ndarray,
                               metadata: LUTMetadata) -> None:
        """Save LUT data as .npz with metadata_json key.
        将 LUT 数据保存为 .npz 格式，含 metadata_json 键。

        Args:
            path (str): Output file path. (输出文件路径)
            rgb (np.ndarray): RGB array (N, 3) uint8. (RGB 数组)
            stacks (np.ndarray): Stacks array (N, L) int32. (堆叠配方数组)
            metadata (LUTMetadata): LUT metadata. (LUT 元数据)
        """
        metadata_json_str = json.dumps(metadata.to_dict(), ensure_ascii=False)
        np.savez(
            path,
            rgb=rgb,
            stacks=stacks,
            metadata_json=np.array(metadata_json_str),
        )
