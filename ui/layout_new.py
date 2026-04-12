# -*- coding: utf-8 -*-
"""
Lumina Studio - UI Layout (Refactored with i18n)
UI layout definition - Refactored version with language switching support
"""

import json
import os
import re
import shutil
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import gradio as gr
import numpy as np
from PIL import Image as PILImage

from core.i18n import I18n
from config import ColorSystem, ModelingMode, BedManager
from utils import Stats, LUTManager
from core.calibration import generate_calibration_board, generate_smart_board, generate_8color_batch_zip, generate_5color1444_board
from core.naming import generate_batch_filename
from core.extractor import (
    rotate_image,
    draw_corner_points,
    run_extraction,
    probe_lut_cell,
    manual_fix_cell,
)
from core.converter import (
    generate_preview_cached,
    generate_realtime_glb,
    generate_empty_bed_glb,
    render_preview,
    update_preview_with_loop,
    on_remove_loop,
    generate_final_model,
    on_preview_click_select_color,
    generate_lut_grid_html,
    generate_lut_card_grid_html,
    detect_lut_color_mode,
    detect_image_type,
    generate_auto_height_map,
    _build_dual_recommendations,
    _resolve_click_selection_hexes,
    get_lut_color_choices,
)
from core.heightmap_loader import HeightmapLoader
from .styles import CUSTOM_CSS
from .callbacks import (
    get_first_hint,
    get_next_hint,
    on_extractor_upload,
    on_extractor_mode_change,
    on_extractor_rotate,
    on_extractor_click,
    on_extractor_clear,
    on_extractor_page_change,
    on_lut_select,
    on_lut_upload_save,
    on_apply_color_replacement,
    on_clear_color_replacements,
    on_undo_color_replacement,
    on_preview_generated_update_palette,
    on_delete_selected_user_replacement,
    on_highlight_color_change,
    on_clear_highlight,
    run_extraction_wrapper,
    merge_8color_data,
    merge_5color_extended_data,
    on_merge_lut_select,
    on_merge_execute,
    on_merge_primary_select,
    on_merge_secondary_change,
    on_merge_preview,
    on_merge_apply,
    on_merge_revert,
)

# Supported image file types for Gradio upload components.
# Centralized list so that adding a new format only requires one change.
SUPPORTED_IMAGE_FILE_TYPES: list[str] = [
    ".jpg", ".jpeg", ".png", ".bmp",
    ".gif", ".webp", ".heic", ".heif",
]

# Runtime-injected i18n keys (avoids editing core/i18n.py).
if hasattr(I18n, 'TEXTS'):
    I18n.TEXTS.update({
        'conv_advanced': {'zh': '🛠️ 高级设置', 'en': '🛠️ Advanced Settings'},
        'conv_stop':     {'zh': '🛑 停止生成', 'en': '🛑 Stop Generation'},
        'conv_batch_mode':      {'zh': '📦 批量模式', 'en': '📦 Batch Mode'},
        'conv_batch_mode_info': {'zh': '一次生成多个模型 (参数共享)', 'en': 'Generate multiple models (Shared Settings)'},
        'conv_batch_input':     {'zh': '📤 批量上传图片', 'en': '📤 Batch Upload Images'},
        'conv_lut_status': {'zh': '💡 拖放.npy文件自动添加', 'en': '💡 Drop .npy file to load'},
    })

DEBOUNCE_JS = """
<script>
(function () {
  if (window.__luminaBlurTriggerInit) return;
  window.__luminaBlurTriggerInit = true;

  function setupBlurTrigger() {
    var sliders = document.querySelectorAll('.compact-row input[type="number"]');
    if (!sliders.length) return 0;
    var boundCount = 0;
    sliders.forEach(function (input) {
      if (input.__blur_bound) return;
      input.__blur_bound = true;
      boundCount += 1;
      var lastValue = input.value;
      // Programmatic updates (e.g. selecting another image) may change value
      // without touching this closure; refresh baseline on user focus.
      input.addEventListener('focus', function () {
        lastValue = input.value;
      });
      // 捕获阶段拦截所有 input 事件，阻止 Gradio 立即处理
      input.addEventListener('input', function (e) {
        if (input.__dispatching) return;
        e.stopImmediatePropagation();
      }, true);
      // 失焦时，如果值有变化且在合法范围内，才触发一次 input 事件
      input.addEventListener('blur', function () {
        var val = parseFloat(input.value);
        if (input.value !== lastValue && !isNaN(val)) {
          var min = parseFloat(input.min);
          var max = parseFloat(input.max);
          if (!isNaN(min) && val < min) { input.value = min; val = min; }
          if (!isNaN(max) && val > max) { input.value = max; val = max; }
          lastValue = input.value;
          input.__dispatching = true;
          input.dispatchEvent(new Event('input', { bubbles: true }));
          input.__dispatching = false;
        }
        lastValue = input.value;
      });
      // Enter 键也触发
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          input.blur();
        }
      });
    });
    return boundCount;
  }

  function init() {
    setupBlurTrigger();
    var observer = new MutationObserver(function () {
      setupBlurTrigger();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      setTimeout(init, 1000);
    });
  } else {
    setTimeout(init, 1000);
  }
})();
</script>
"""

CONFIG_FILE = "user_settings.json"


def load_last_lut_setting():
    """Load the last selected LUT name from the user settings file.

    Returns:
        str | None: LUT name if found, else None.
    """
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("last_lut", None)
        except Exception as e:
            print(f"Failed to load settings: {e}")
    return None


def save_last_lut_setting(lut_name):
    """Persist the current LUT selection to the user settings file.

    Args:
        lut_name: Display name of the selected LUT (or None to clear).
    """
    data = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            pass

    data["last_lut"] = lut_name

    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed to save settings: {e}")


def _load_user_settings():
    """Load all user settings from the settings file."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_user_setting(key, value):
    """Save a single key-value pair to the user settings file."""
    data = _load_user_settings()
    data[key] = value
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Failed to save setting {key}: {e}")


def save_color_mode(color_mode):
    """Persist the selected color mode."""
    _save_user_setting("last_color_mode", color_mode)


def save_modeling_mode(modeling_mode):
    """Persist the selected modeling mode."""
    val = modeling_mode.value if hasattr(modeling_mode, 'value') else str(modeling_mode)
    _save_user_setting("last_modeling_mode", val)


def resolve_height_mode(radio_value: str) -> str:
    """Map the UI radio selection to the backend ``height_mode`` parameter.

    Args:
        radio_value: Current value of the height-mode radio button
                     (e.g. "深色凸起", "浅色凸起", "根据高度图").

    Returns:
        ``"heightmap"`` when the user selected heightmap mode,
        ``"color"`` for all colour-based modes.
    """
    if radio_value == "根据高度图":
        return "heightmap"
    return "color"


# ---------- Slicer Integration ----------

import subprocess
import platform

if platform.system() == "Windows":
    import winreg

# Known slicer identifiers for registry matching
_SLICER_KEYWORDS = {
    "bambu_studio":  {"match": ["bambu studio"], "name": "Bambu Studio"},
    "orca_slicer":   {"match": ["orcaslicer"],   "name": "OrcaSlicer"},
    "elegoo_slicer": {"match": ["elegooslicer", "elegoo slicer", "elegoo satellit"], "name": "ElegooSlicer"},
    "prusa_slicer":  {"match": ["prusaslicer"],  "name": "PrusaSlicer"},
    "cura":          {"match": ["ultimaker cura", "ultimaker-cura"], "name": "Ultimaker Cura"},
}


def _scan_registry_for_slicers():
    """Scan Windows registry Uninstall keys to find slicer executables.
    
    Returns dict: {slicer_id: {"name": display_name, "exe": exe_path}}
    Non-Windows platforms return empty dict.
    """
    if platform.system() != "Windows":
        return {}

    found = {}
    reg_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    
    for hive, base_path in reg_paths:
        try:
            key = winreg.OpenKey(hive, base_path)
        except OSError:
            continue
        
        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(key, i)
                i += 1
            except OSError:
                break
            
            try:
                subkey = winreg.OpenKey(key, subkey_name)
                try:
                    display_name = winreg.QueryValueEx(subkey, "DisplayName")[0]
                except OSError:
                    subkey.Close()
                    continue
                
                # Try DisplayIcon first (most reliable for exe path)
                exe_path = None
                try:
                    icon = winreg.QueryValueEx(subkey, "DisplayIcon")[0]
                    # DisplayIcon can be "path.exe" or "path.exe,0"
                    # Also handle doubled paths like "F:\...\F:\...\exe"
                    icon = icon.split(",")[0].strip().strip('"')
                    # Handle doubled path: if path appears twice, take the second half
                    parts = icon.split("\\")
                    for idx in range(1, len(parts)):
                        candidate = "\\".join(parts[idx:])
                        if os.path.isfile(candidate):
                            exe_path = candidate
                            break
                    if not exe_path and os.path.isfile(icon):
                        exe_path = icon
                except OSError:
                    pass
                
                # Fallback: try InstallLocation
                if not exe_path:
                    try:
                        install_loc = winreg.QueryValueEx(subkey, "InstallLocation")[0]
                        if install_loc and os.path.isdir(install_loc):
                            for f in os.listdir(install_loc):
                                if f.lower().endswith(".exe") and "unins" not in f.lower():
                                    candidate = os.path.join(install_loc, f)
                                    if os.path.isfile(candidate):
                                        exe_path = candidate
                                        break
                    except OSError:
                        pass
                
                subkey.Close()
                
                if not exe_path or not exe_path.lower().endswith(".exe"):
                    continue
                
                # Match against known slicers
                dn_lower = display_name.lower()
                for sid, info in _SLICER_KEYWORDS.items():
                    if sid in found:
                        continue
                    for kw in info["match"]:
                        if kw in dn_lower:
                            # Skip CUDA-related entries that match "cura"
                            if sid == "cura" and ("cuda" in dn_lower or "nvidia" in dn_lower):
                                break
                            found[sid] = {"name": display_name.strip(), "exe": exe_path}
                            break
            except OSError:
                pass
        
        key.Close()
    
    return found


def detect_installed_slicers():
    """Detect installed slicers via registry + user saved paths.
    
    Returns list of (id, name, exe_path).
    """
    found = []
    
    # 1. Registry scan
    reg_slicers = _scan_registry_for_slicers()
    for sid, info in reg_slicers.items():
        found.append((sid, info["name"], info["exe"]))
        print(f"[SLICER] Registry: {info['name']} → {info['exe']}")
    
    # 2. User-saved custom paths
    prefs = _load_user_settings()
    custom_slicers = prefs.get("custom_slicers", {})
    for sid, exe in custom_slicers.items():
        if os.path.isfile(exe) and sid not in [s[0] for s in found]:
            name = _SLICER_KEYWORDS.get(sid, {}).get("name", sid)
            found.append((sid, name, exe))
            print(f"[SLICER] Custom: {name} → {exe}")
    
    if not found:
        print("[SLICER] No slicers detected")
    return found


def open_in_slicer(file_path, slicer_id):
    """Open a 3MF file in the specified slicer."""
    if not file_path:
        return "[ERROR] 没有可打开的文件 / No file to open"
    
    actual_path = file_path
    if hasattr(file_path, 'name'):
        actual_path = file_path.name
    
    if not os.path.isfile(actual_path):
        return f"[ERROR] 文件不存在: {actual_path}"
    
    # Find exe from detected slicers
    for sid, name, exe in _INSTALLED_SLICERS:
        if sid == slicer_id:
            try:
                subprocess.Popen([exe, actual_path])
                return f"[OK] 已在 {name} 中打开"
            except Exception as e:
                return f"[ERROR] 启动 {name} 失败: {e}"
    
    return f"[ERROR] 未找到切片软件: {slicer_id}"


# Detect slicers at startup
_INSTALLED_SLICERS = detect_installed_slicers()


def _get_slicer_choices(lang="zh"):
    """Build dropdown choices: installed slicers + download option."""
    choices = []
    for sid, name, exe in _INSTALLED_SLICERS:
        label_zh = f"在 {name} 中打开"
        label_en = f"Open in {name}"
        choices.append((label_zh if lang == "zh" else label_en, sid))
    
    dl_label = "📥 下载 3MF" if lang == "zh" else "📥 Download 3MF"
    choices.append((dl_label, "download"))
    return choices


def _get_default_slicer():
    """Get the saved or first available slicer id."""
    prefs = _load_user_settings()
    saved = prefs.get("last_slicer", None)
    installed_ids = [s[0] for s in _INSTALLED_SLICERS]
    if saved and saved in installed_ids:
        return saved
    if installed_ids:
        return installed_ids[0]
    return "download"


def _slicer_css_class(slicer_id):
    """Map slicer_id to CSS class for button color."""
    if "bambu" in slicer_id:
        return "slicer-bambu"
    if "orca" in slicer_id:
        return "slicer-orca"
    if "elegoo" in slicer_id:
        return "slicer-elegoo"
    return "slicer-download"


# ---------- Header and layout CSS ----------
HEADER_CSS = """
/* Full-width container */
.gradio-container {
    max-width: 100% !important;
    width: 100% !important;
    padding-left: 20px !important;
    padding-right: 20px !important;
}

/* Header row with rounded corners */
.header-row {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 15px 20px;
    margin-left: 0 !important;
    margin-right: 0 !important;
    width: 100% !important;
    border-radius: 16px !important;
    overflow: hidden !important;
    margin-bottom: 15px !important;
    align-items: center;
    box-shadow: 0 4px 15px rgba(102, 126, 234, 0.2) !important;
}

.header-row h1 {
    color: white !important;
    margin: 0 !important;
    font-size: 24px;
    display: flex;
    align-items: center;
    gap: 10px;
}

.header-row p {
    color: rgba(255,255,255,0.8) !important;
    margin: 0 !important;
    font-size: 14px;
}

.header-controls {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    justify-content: flex-start;
    gap: 8px;
    margin-top: -4px;
}

/* 2D Preview: keep fixed box, scale image to fit (no cropping) */
#conv-preview .image-container {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    overflow: hidden !important;
    height: 100% !important;
}
#conv-preview canvas,
#conv-preview img {
    max-width: 100% !important;
    max-height: 100% !important;
    width: auto !important;
    height: auto !important;
}

/* Left sidebar */
.left-sidebar {
    padding: 10px 15px 10px 0;
    height: 100%;
}

.compact-row {
    margin-top: -10px !important;
    margin-bottom: -10px !important;
    gap: 10px;
}

.micro-upload {
    min-height: 40px !important;
}

/* Workspace area */
.workspace-area {
    padding: 0 !important;
}

/* Action buttons */
.action-buttons {
    margin-top: 15px;
    margin-bottom: 15px;
}

/* Upload box height aligned with dropdown row */
.tall-upload {
    height: 84px !important;
    min-height: 84px !important;
    max-height: 84px !important;
    background-color: var(--background-fill-primary, #ffffff) !important;
    border-radius: 8px !important;
    border: 1px dashed var(--border-color-primary, #e5e7eb) !important;
    overflow: hidden !important;
    padding: 0 !important;
}

/* Inner layout for upload area */
.tall-upload .wrap {
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
    align-items: center !important;
    padding: 2px !important;
    height: 100% !important;
}

/* Smaller font in upload area */
.tall-upload .icon-wrap { display: none !important; }
.tall-upload span,
.tall-upload div {
    font-size: 12px !important;
    line-height: 1.3 !important;
    color: var(--body-text-color-subdued, #6b7280) !important;
    text-align: center !important;
    margin: 0 !important;
}

/* LUT status card style */
.lut-status {
    margin-top: 10px !important;
    padding: 8px 12px !important;
    background: var(--background-fill-primary, #ffffff) !important;
    border: 1px solid var(--border-color-primary, #e5e7eb) !important;
    border-radius: 8px !important;
    color: var(--body-text-color, #4b5563) !important;
    font-size: 13px !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.05);
    min-height: 36px !important;
    display: flex !important;
    align-items: center !important;
}
.lut-status p {
    margin: 0 !important;
}

/* Transparent group (no box) */
.clean-group {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
}

/* Modeling mode radio text color (avoid theme override) */
.vertical-radio label span {
    color: #374151 !important;
    font-weight: 500 !important;
}

/* Selected state text color */
.vertical-radio input:checked + span,
.vertical-radio label.selected span {
    color: #1f2937 !important;
}

/* Bed size dropdown overlay on preview */
#conv-bed-size-overlay {
    display: flex !important;
    justify-content: flex-end !important;
    align-items: center !important;
    margin-bottom: -8px !important;
    padding: 0 4px !important;
    z-index: 10 !important;
    position: relative !important;
    gap: 0 !important;
}
#conv-bed-size-overlay > .column:first-child {
    display: none !important;
}
#conv-bed-size-dropdown {
    max-width: 160px !important;
    min-width: 130px !important;
}
#conv-bed-size-dropdown input {
    font-size: 12px !important;
    padding: 4px 8px !important;
    height: 28px !important;
    border-radius: 6px !important;
    background: var(--background-fill-secondary, rgba(240,240,245,0.9)) !important;
    border: 1px solid var(--border-color-primary, #ddd) !important;
    cursor: pointer !important;
}
#conv-bed-size-dropdown .wrap {
    min-height: unset !important;
    padding: 0 !important;
}
#conv-bed-size-dropdown ul {
    font-size: 12px !important;
}

/* Custom tab bar that matches the original Gradio tab styling */
.custom-tab-bar {
    gap: 0 !important;
    align-items: flex-end !important;
    border-bottom: 1px solid var(--border-color-primary, #d1d5db) !important;
    margin-bottom: 10px !important;
}

.custom-tab-bar .custom-tab-btn {
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    margin-bottom: -1px !important;
    border-radius: 10px !important;
    padding: 8px 16px !important;
    transition: background 0.2s, color 0.2s !important;
}

.custom-tab-bar .custom-tab-btn:hover {
    background: var(--background-fill-secondary, rgba(240,240,245,0.6)) !important;
}

.custom-tab-bar .custom-tab-btn.selected {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    color: #fff !important;
    box-shadow: 0 2px 6px rgba(102, 126, 234, 0.3) !important;
}

.custom-tab-bar .custom-tab-btn:not(.selected) {
    color: var(--body-text-color, #374151) !important;
}

#tab-content-calibration,
#tab-content-extractor,
#tab-content-advanced,
#tab-content-merge,
#tab-content-5color,
#tab-content-about {
    display: none;
}

#tab-content-converter {
    display: block;
}
"""

# [新增/修改] LUT 色块网格样式
LUT_GRID_CSS = """
.lut-swatch,
.lut-color-swatch {
    width: 24px;
    height: 24px;
    border-radius: 4px;
    cursor: pointer;
    border: 1px solid rgba(0,0,0,0.1);
    transition: transform 0.1s, border-color 0.1s;
}
.lut-swatch:hover,
.lut-color-swatch:hover {
    transform: scale(1.2);
    border-color: #333;
    z-index: 10;
    box-shadow: 0 2px 5px rgba(0,0,0,0.2);
}
"""

# Preview zoom/scroll styles
PREVIEW_ZOOM_CSS = """
#conv-preview {
    overflow: hidden !important;
    position: relative !important;
}
"""

# [新增] JavaScript 注入：点击 LUT 色块写入隐藏 Textbox 并触发按钮
LUT_GRID_JS = """
<script>
function selectLutColor(hexColor) {
    const container = document.getElementById("conv-lut-color-selected-hidden");
    if (!container) return;
    const input = container.querySelector("textarea, input");
    if (!input) return;

    input.value = hexColor;
    input.dispatchEvent(new Event("input", { bubbles: true }));

    const btn = document.getElementById("conv-lut-color-trigger-btn");
    if (btn) btn.click();
}
</script>
"""

# Preview zoom JS (wheel to zoom, drag to pan, double-click to reset)
PREVIEW_ZOOM_JS = """
<script>
(function() {
    var _z = 1, _px = 0, _py = 0, _drag = false, _sx = 0, _sy = 0;

    function root() { return document.querySelector('#conv-preview'); }
    function img(r) { return r ? (r.querySelector('img') || r.querySelector('canvas')) : null; }

    function apply(el) {
        if (!el) return;
        el.style.transformOrigin = '0 0';
        el.style.transform = 'translate(' + _px + 'px,' + _py + 'px) scale(' + _z + ')';
        el.style.cursor = _z > 1.01 ? (_drag ? 'grabbing' : 'grab') : 'default';
    }

    function reset() {
        _z = 1; _px = 0; _py = 0;
        var el = img(root());
        if (el) { el.style.transform = ''; el.style.cursor = ''; }
    }

    function bind() {
        var r = root();
        if (!r || r.dataset.zb) return false;
        r.dataset.zb = '1';

        r.addEventListener('wheel', function(e) {
            var el = img(r);
            if (!el) return;
            e.preventDefault();
            e.stopPropagation();

            var rect = r.getBoundingClientRect();
            var mx = e.clientX - rect.left;
            var my = e.clientY - rect.top;

            var oz = _z;
            var f = e.deltaY < 0 ? 1.15 : 1/1.15;
            _z = Math.max(0.5, Math.min(10, _z * f));

            _px = mx - (_z / oz) * (mx - _px);
            _py = my - (_z / oz) * (my - _py);
            apply(el);
        }, { passive: false });

        r.addEventListener('mousedown', function(e) {
            if (_z <= 1.01 || e.button !== 0) return;
            _drag = true;
            _sx = e.clientX - _px;
            _sy = e.clientY - _py;
            var el = img(r);
            if (el) el.style.cursor = 'grabbing';
            e.preventDefault();
        });

        window.addEventListener('mousemove', function(e) {
            if (!_drag) return;
            _px = e.clientX - _sx;
            _py = e.clientY - _sy;
            apply(img(r));
        });

        window.addEventListener('mouseup', function() {
            if (!_drag) return;
            _drag = false;
            var el = img(r);
            if (el) el.style.cursor = _z > 1.01 ? 'grab' : 'default';
        });

        r.addEventListener('dblclick', function(e) {
            e.preventDefault();
            reset();
        });

        // Reset zoom when image src changes
        new MutationObserver(function() { reset(); }).observe(r, {
            childList: true, subtree: true, attributes: true, attributeFilter: ['src']
        });

        return true;
    }

    function init() {
        if (bind()) return;
        new MutationObserver(function(m, o) {
            if (bind()) o.disconnect();
        }).observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function() { setTimeout(init, 1500); });
    } else {
        setTimeout(init, 1500);
    }
})();
</script>
"""

# 5-Color Combination click handler JS
FIVECOLOR_CLICK_JS = """
<style>
.hidden-5color-btn {
    position: absolute !important;
    left: -9999px !important;
    top: -9999px !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
    opacity: 0 !important;
    visibility: hidden !important;
    pointer-events: none !important;
}
</style>
<script>
(function() {
    // 防止重复注入
    if (window._5colorClickHandlerInjected) return;
    window._5colorClickHandlerInjected = true;
    
    console.log('[5-Color] Injecting global click handler');
    
    // 使用事件委托监听所有颜色块点击
    document.addEventListener('click', function(e) {
        const colorBox = e.target.closest('.color-box-v2');
        if (!colorBox) return;
        
        const idx = colorBox.getAttribute('data-color-idx');
        if (idx === null) return;
        
        console.log('[5-Color] Color box clicked:', idx);
        
        // 查找并点击对应的隐藏按钮
        const btn = document.getElementById('color-btn-' + idx + '-5color');
        if (btn) {
            console.log('[5-Color] Triggering button:', btn.id);
            btn.click();
        } else {
            console.error('[5-Color] Button not found:', 'color-btn-' + idx + '-5color');
        }
    });
    
    console.log('[5-Color] Global click handler installed');
})();
</script>
"""

CUSTOM_TAB_HEAD_JS = """
<script>
(function() {
    if (window.__luminaCustomTabInit) return;
    window.__luminaCustomTabInit = true;

    const tabs = [
        { key: "converter", buttonId: "tab-btn-converter", contentId: "tab-content-converter" },
        { key: "calibration", buttonId: "tab-btn-calibration", contentId: "tab-content-calibration" },
        { key: "extractor", buttonId: "tab-btn-extractor", contentId: "tab-content-extractor" },
        { key: "advanced", buttonId: "tab-btn-advanced", contentId: "tab-content-advanced" },
        { key: "merge", buttonId: "tab-btn-merge", contentId: "tab-content-merge" },
        { key: "5color", buttonId: "tab-btn-5color", contentId: "tab-content-5color" },
        { key: "about", buttonId: "tab-btn-about", contentId: "tab-content-about" }
    ];

    window.luminaSwitchTab = function(activeKey) {
        tabs.forEach(function(tab) {
            var button = document.getElementById(tab.buttonId);
            var content = document.getElementById(tab.contentId);
            var isActive = tab.key === activeKey;
            if (button) {
                button.classList.toggle("selected", isActive);
            }
            if (content) {
                content.style.display = isActive ? "block" : "none";
            }
        });
    };

    function initTabs(attempt) {
        var mounted = tabs.every(function(tab) {
            return document.getElementById(tab.buttonId) && document.getElementById(tab.contentId);
        });
        if (!mounted && (attempt || 0) < 60) {
            window.requestAnimationFrame(function() {
                initTabs((attempt || 0) + 1);
            });
            return;
        }
        window.luminaSwitchTab("converter");
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initTabs, { once: true });
    } else {
        setTimeout(initTabs, 0);
    }
})();
</script>
"""

# ---------- Image size and aspect-ratio helpers ----------

def _get_image_size(img):
    """Get image dimensions (width, height). Supports file path or numpy array.

    Args:
        img: File path (str) or numpy array (H, W, C).

    Returns:
        tuple[int, int] | None: (width, height) in pixels, or None.
    """
    if img is None:
        return None

    try:
        if isinstance(img, str):
            if img.lower().endswith('.svg'):
                try:
                    from svglib.svglib import svg2rlg
                    drawing = svg2rlg(img)
                    return (drawing.width, drawing.height)
                except ImportError:
                    print("⚠️ svglib not installed, cannot read SVG size")
                    return None
                except Exception as e:
                    print(f"⚠️ Error reading SVG size: {e}")
                    return None
            
            with PILImage.open(img) as i:
                return i.size

        elif hasattr(img, 'shape'):
            return (img.shape[1], img.shape[0])
    except Exception as e:
        print(f"Error getting image size: {e}")
        return None
    
    return None


def calc_height_from_width(width, img):
    """Compute height (mm) from width (mm) preserving aspect ratio.

    Args:
        width: Target width in mm.
        img: Image path or array for dimensions.

    Returns:
        float | gr.update: Height in mm, or gr.update() if unknown.
    """
    size = _get_image_size(img)
    if size is None or width is None:
        return gr.update()
    
    w_px, h_px = size
    if w_px == 0:
        return 0
    
    ratio = h_px / w_px
    return int(round(width * ratio))


def calc_width_from_height(height, img):
    """Compute width (mm) from height (mm) preserving aspect ratio.

    Args:
        height: Target height in mm.
        img: Image path or array for dimensions.

    Returns:
        float | gr.update: Width in mm, or gr.update() if unknown.
    """
    size = _get_image_size(img)
    if size is None or height is None:
        return gr.update()
    
    w_px, h_px = size
    if h_px == 0:
        return 0
    
    ratio = w_px / h_px
    return int(round(height * ratio))


def init_dims(img):
    """Compute default width/height (mm) from image aspect ratio.

    Args:
        img: Image path or array.

    Returns:
        tuple[float, float]: (default_width_mm, default_height_mm).
    """
    size = _get_image_size(img)
    if size is None:
        return 60, 60
    
    w_px, h_px = size
    default_w = 60
    default_h = int(round(default_w * (h_px / w_px)))
    return default_w, default_h


def _scale_preview_image(img, max_w: int = 1200, max_h: int = 750):
    """Scale preview image to fit within a fixed box without changing container size."""
    if img is None:
        return None

    if isinstance(img, PILImage.Image):
        arr = np.array(img)
    elif hasattr(img, "shape"):
        arr = img
    else:
        return img

    try:
        h, w = arr.shape[:2]
        if h <= 0 or w <= 0:
            return arr
        scale = min(1.0, max_w / w, max_h / h)
        if scale >= 0.999:
            return arr
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        pil = PILImage.fromarray(arr)
        pil = pil.resize((new_w, new_h), PILImage.Resampling.LANCZOS)
        return np.array(pil)
    except Exception:
        return img


def _preview_update(img):
    """Return a Gradio update for the preview image without resizing the container."""
    if isinstance(img, dict) and img.get("__type__") == "update":
        return img
    return gr.update(value=_scale_preview_image(img))


def process_batch_generation(batch_files, is_batch, single_image, lut_path, target_width_mm,
                             spacer_thick, structure_mode, auto_bg, bg_tol, color_mode,
                             add_loop, loop_width, loop_length, loop_hole, loop_pos,
                             modeling_mode, quantize_colors, replacement_regions=None,
                             separate_backing=False, enable_relief=False, color_height_map=None,
                             height_mode: str = "color",
                             heightmap_path=None, heightmap_max_height=None,
                             enable_cleanup=True,
                             enable_outline=False, outline_width=2.0,
                             enable_cloisonne=False, wire_width_mm=0.4,
                             wire_height_mm=0.4,
                             free_color_set=None,
                             enable_coating=False, coating_height_mm=0.08,
                             hue_weight: float = 0.0,
                             progress=gr.Progress()):
    """Dispatch to single-image or batch generation; batch writes a ZIP of 3MFs.

    Args:
        separate_backing: Boolean flag to separate backing as individual object (default: False)
        enable_relief: Boolean flag to enable 2.5D relief mode (default: False)
        color_height_map: Dict mapping hex colors to heights in mm (default: None)
        height_mode: "color" or "heightmap", determines relief branch selection (default: "color")
        heightmap_path: Optional path to heightmap image file (default: None)
        heightmap_max_height: Optional max height for heightmap mode in mm (default: None)

    Returns:
        tuple: (file_or_zip_path, model3d_value, preview_image, status_text).
    """
    # Handle None modeling_mode (use default)
    if modeling_mode is None or modeling_mode == "none":
        modeling_mode = ModelingMode.HIGH_FIDELITY
    else:
        modeling_mode = ModelingMode(modeling_mode)
    # Use default white color for backing (fixed, not user-selectable)
    backing_color_name = "White"
    
    # Prepare relief mode parameters
    if color_height_map is None:
        color_height_map = {}
    
    args = (lut_path, target_width_mm, spacer_thick, structure_mode, auto_bg, bg_tol,
            color_mode, add_loop, loop_width, loop_length, loop_hole, loop_pos,
            modeling_mode, quantize_colors, replacement_regions, backing_color_name,
            separate_backing, enable_relief, color_height_map,
            height_mode,
            heightmap_path, heightmap_max_height,
            enable_cleanup,
            enable_outline, outline_width,
            enable_cloisonne, wire_width_mm, wire_height_mm,
            free_color_set,
            enable_coating, coating_height_mm)

    if not is_batch:
        out_path, glb_path, preview_img, status, color_recipe_path = generate_final_model(
            image_path=single_image,
            lut_path=lut_path,
            target_width_mm=target_width_mm,
            spacer_thick=spacer_thick,
            structure_mode=structure_mode,
            auto_bg=auto_bg,
            bg_tol=bg_tol,
            progress=progress,
            color_mode=color_mode,
            add_loop=add_loop,
            loop_width=loop_width,
            loop_length=loop_length,
            loop_hole=loop_hole,
            loop_pos=loop_pos,
            modeling_mode=modeling_mode,
            quantize_colors=quantize_colors,
            replacement_regions=replacement_regions,
            backing_color_name=backing_color_name,
            separate_backing=separate_backing,
            enable_relief=enable_relief,
            color_height_map=color_height_map,
            height_mode=height_mode,
            heightmap_path=heightmap_path,
            heightmap_max_height=heightmap_max_height,
            enable_cleanup=enable_cleanup,
            enable_outline=enable_outline,
            outline_width=outline_width,
            enable_cloisonne=enable_cloisonne,
            wire_width_mm=wire_width_mm,
            wire_height_mm=wire_height_mm,
            free_color_set=free_color_set,
            enable_coating=enable_coating,
            coating_height_mm=coating_height_mm,
            hue_weight=float(hue_weight) if hue_weight else 0.0,
        )
        return out_path, glb_path, _preview_update(preview_img), status, color_recipe_path

    if not batch_files:
        return None, None, None, "[ERROR] 请先上传图片 / Please upload images first"

    generated_files = []
    total_files = len(batch_files)
    logs = []

    output_dir = os.path.join("outputs", f"batch_{int(time.time())}")
    os.makedirs(output_dir, exist_ok=True)

    logs.append(f"🚀 开始批量处理 {total_files} 张图片...")

    for i, file_obj in enumerate(batch_files):
        path = getattr(file_obj, 'name', file_obj) if file_obj else None
        if not path or not os.path.isfile(path):
            continue
        filename = os.path.basename(path)
        progress(i / total_files, desc=f"Processing {filename}...")
        logs.append(f"[{i+1}/{total_files}] 正在生成: {filename}")

        try:
            result_3mf, _, _, _ = generate_final_model(path, *args, hue_weight=float(hue_weight) if hue_weight else 0.0)

            if result_3mf and os.path.exists(result_3mf):
                new_name = os.path.splitext(filename)[0] + ".3mf"
                dest_path = os.path.join(output_dir, new_name)
                shutil.copy2(result_3mf, dest_path)
                generated_files.append(dest_path)
        except Exception as e:
            logs.append(f"❌ 失败 {filename}: {str(e)}")
            print(f"Batch error on {filename}: {e}")

    if generated_files:
        zip_path = os.path.join("outputs", generate_batch_filename())
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for f in generated_files:
                zipf.write(f, os.path.basename(f))
        logs.append(f"✅ Batch done: {len(generated_files)} model(s).")
        return zip_path, None, _preview_update(None), "\n".join(logs), None
    return None, None, _preview_update(None), "[ERROR] Batch failed: no valid models.\n" + "\n".join(logs), None


# ========== Advanced Tab Callbacks ==========


def _update_lut_grid(lut_path, lang, palette_mode="swatch"):
    """Wrapper that picks swatch or card grid based on palette_mode setting.
    
    For merged LUTs (.npz), always uses swatch mode since card mode
    requires stack data in a format incompatible with merged LUTs.
    """
    # Force swatch mode for merged LUTs
    if lut_path and lut_path.endswith('.npz'):
        palette_mode = "swatch"
    if palette_mode == "card":
        return generate_lut_card_grid_html(lut_path, lang)
    return generate_lut_grid_html(lut_path, lang)


def _structure_relief_for_5color_extended(enable_coating):
    """5C: 2.5D always off. Double-sided only when COATING is on."""
    relief = gr.update(value=False, interactive=False)
    if enable_coating:
        return gr.update(interactive=True), relief
    return gr.update(
        value=I18n.get('conv_structure_single', 'en'),
        interactive=False,
    ), relief


def _detect_and_enforce_structure(lut_path, enable_coating=False):
    """Detect color mode from LUT, and enforce structure constraints for 5-Color Extended.

    Returns (color_mode_update, structure_update, relief_update) for three component outputs.
    """
    mode = detect_lut_color_mode(lut_path)
    if mode and "5-Color Extended" in mode:
        if enable_coating:
            gr.Info("5-Color Extended：已启用 COATING 时可选择双面；2.5D 浮雕不可用")
        else:
            gr.Info("5-Color Extended：未启用 COATING 时仅支持单面；2.5D 浮雕不可用")
        struct_u, rel_u = _structure_relief_for_5color_extended(enable_coating)
        return mode, struct_u, rel_u
    if mode:
        return mode, gr.update(interactive=True), gr.update(interactive=True)
    return gr.update(), gr.update(interactive=True), gr.update(interactive=True)


def create_app():
    """Build the Gradio app (tabs, i18n, events) and return the Blocks instance."""
    with gr.Blocks(title="Lumina Studio") as app:
        # Inject CSS styles via HTML component (for Gradio 4.20.0 compatibility)
        from ui.styles import CUSTOM_CSS
        gr.HTML(f"<style>{CUSTOM_CSS + HEADER_CSS + LUT_GRID_CSS}</style>")
        
        lang_state = gr.State(value="zh")
        theme_state = gr.State(value=False)  # False=light, True=dark

        # Header + Stats merged into one row
        with gr.Row(elem_classes=["header-row"], equal_height=True):
            with gr.Column(scale=6):
                app_title_html = gr.HTML(
                    value=f"<h1>✨ Lumina Studio</h1><p>{I18n.get('app_subtitle', 'zh')}</p>",
                    elem_id="app-header"
                )
            with gr.Column(scale=4):
                stats = Stats.get_all()
                stats_html = gr.HTML(
                    value=_get_stats_html("zh", stats),
                    elem_classes=["stats-bar-inline"]
                )
            with gr.Column(scale=1, min_width=140, elem_classes=["header-controls"]):
                lang_btn = gr.Button(
                    value="🌐 English",
                    size="sm",
                    elem_id="lang-btn"
                )
                theme_btn = gr.Button(
                    value=I18n.get('theme_toggle_night', "zh"),
                    size="sm",
                    elem_id="theme-btn"
                )
        
        components = {}

        tab_components = {}
        with gr.Row(elem_classes=["custom-tab-bar", "tab-nav"]):
            tab_components['tab_converter'] = gr.Button(
                value=I18n.get('tab_converter', "zh"),
                elem_id="tab-btn-converter",
                elem_classes=["custom-tab-btn", "selected"],
            )
            tab_components['tab_calibration'] = gr.Button(
                value=I18n.get('tab_calibration', "zh"),
                elem_id="tab-btn-calibration",
                elem_classes=["custom-tab-btn"],
            )
            tab_components['tab_extractor'] = gr.Button(
                value=I18n.get('tab_extractor', "zh"),
                elem_id="tab-btn-extractor",
                elem_classes=["custom-tab-btn"],
            )
            tab_components['tab_advanced'] = gr.Button(
                value="🔬 高级",
                elem_id="tab-btn-advanced",
                elem_classes=["custom-tab-btn"],
            )
            tab_components['tab_merge'] = gr.Button(
                value=I18n.get('tab_merge', "zh"),
                elem_id="tab-btn-merge",
                elem_classes=["custom-tab-btn"],
            )
            tab_components['tab_5color'] = gr.Button(
                value="🎨 配色查询",
                elem_id="tab-btn-5color",
                elem_classes=["custom-tab-btn"],
            )
            tab_components['tab_about'] = gr.Button(
                value=I18n.get('tab_about', "zh"),
                elem_id="tab-btn-about",
                elem_classes=["custom-tab-btn"],
            )

        with gr.Column(visible=True, elem_id="tab-content-converter"):
            conv_components = create_converter_tab_content("zh", lang_state, theme_state)
            components.update(conv_components)

        with gr.Column(visible=True, elem_id="tab-content-calibration"):
            cal_components = create_calibration_tab_content("zh")
            components.update(cal_components)

        with gr.Column(visible=True, elem_id="tab-content-extractor"):
            ext_components = create_extractor_tab_content("zh")
            components.update(ext_components)

        with gr.Column(visible=True, elem_id="tab-content-advanced"):
            advanced_components = create_advanced_tab_content("zh")
            components.update(advanced_components)

        with gr.Column(visible=True, elem_id="tab-content-merge"):
            merge_components = create_merge_tab_content("zh")
            components.update(merge_components)

        with gr.Column(visible=True, elem_id="tab-content-5color"):
            from ui.fivecolor_tab_v2 import create_5color_tab_v2
            create_5color_tab_v2("zh")

        with gr.Column(visible=True, elem_id="tab-content-about"):
            about_components = create_about_tab_content("zh")
            components.update(about_components)

        tab_components['tab_converter'].click(
            fn=None,
            inputs=None,
            outputs=None,
            js="() => { window.luminaSwitchTab && window.luminaSwitchTab('converter'); }",
        )
        tab_components['tab_calibration'].click(
            fn=None,
            inputs=None,
            outputs=None,
            js="() => { window.luminaSwitchTab && window.luminaSwitchTab('calibration'); }",
        )
        tab_components['tab_extractor'].click(
            fn=None,
            inputs=None,
            outputs=None,
            js="() => { window.luminaSwitchTab && window.luminaSwitchTab('extractor'); }",
        )
        tab_components['tab_advanced'].click(
            fn=None,
            inputs=None,
            outputs=None,
            js="() => { window.luminaSwitchTab && window.luminaSwitchTab('advanced'); }",
        )
        tab_components['tab_merge'].click(
            fn=None,
            inputs=None,
            outputs=None,
            js="() => { window.luminaSwitchTab && window.luminaSwitchTab('merge'); }",
        )
        tab_components['tab_5color'].click(
            fn=None,
            inputs=None,
            outputs=None,
            js="() => { window.luminaSwitchTab && window.luminaSwitchTab('5color'); }",
        )
        tab_components['tab_about'].click(
            fn=None,
            inputs=None,
            outputs=None,
            js="() => { window.luminaSwitchTab && window.luminaSwitchTab('about'); }",
        )

        footer_html = gr.HTML(
            value=_get_footer_html("zh"),
            elem_id="footer"
        )
        
        def change_language(current_lang, is_dark):
            """Switch UI language and return updates for all i18n components."""
            new_lang = "en" if current_lang == "zh" else "zh"
            updates = []
            updates.append(gr.update(value=I18n.get('lang_btn_zh' if new_lang == "zh" else 'lang_btn_en', new_lang)))
            theme_label = I18n.get('theme_toggle_day', new_lang) if is_dark else I18n.get('theme_toggle_night', new_lang)
            updates.append(gr.update(value=theme_label))
            updates.append(gr.update(value=_get_header_html(new_lang)))
            stats = Stats.get_all()
            updates.append(gr.update(value=_get_stats_html(new_lang, stats)))
            updates.append(gr.update(value=I18n.get('tab_converter', new_lang)))
            updates.append(gr.update(value=I18n.get('tab_calibration', new_lang)))
            updates.append(gr.update(value=I18n.get('tab_extractor', new_lang)))
            updates.append(gr.update(value="🔬 高级" if new_lang == "zh" else "🔬 Advanced"))
            updates.append(gr.update(value=I18n.get('tab_merge', new_lang)))
            updates.append(gr.update(value="🎨 配色查询" if new_lang == "zh" else "🎨 Color Query"))
            updates.append(gr.update(value=I18n.get('tab_about', new_lang)))
            updates.extend(_get_all_component_updates(new_lang, components))
            updates.append(gr.update(value=_get_footer_html(new_lang)))
            updates.append(new_lang)
            return updates

        output_list = [
            lang_btn,
            theme_btn,
            app_title_html,
            stats_html,
            tab_components['tab_converter'],
            tab_components['tab_calibration'],
            tab_components['tab_extractor'],
            tab_components['tab_advanced'],
            tab_components['tab_merge'],
            tab_components['tab_5color'],
            tab_components['tab_about'],
        ]
        output_list.extend(_get_component_list(components))
        output_list.extend([footer_html, lang_state])

        lang_btn.click(
            change_language,
            inputs=[lang_state, theme_state],
            outputs=output_list
        )

        def _on_theme_toggle(current_is_dark, current_lang, cache):
            """Toggle theme state and re-render preview with new bed colors."""
            new_is_dark = not current_is_dark
            label = I18n.get('theme_toggle_day', current_lang) if new_is_dark else I18n.get('theme_toggle_night', current_lang)

            # Re-render 2D preview with new theme
            new_preview = gr.update()
            if cache is not None:
                cache['is_dark'] = new_is_dark
                preview_rgba = cache.get('preview_rgba')
                if preview_rgba is not None:
                    color_conf = cache.get('color_conf')
                    display = render_preview(
                        preview_rgba, None, 0, 0, 0, 0, False, color_conf,
                        bed_label=cache.get('bed_label'),
                        target_width_mm=cache.get('target_width_mm'),
                        is_dark=new_is_dark
                    )
                    new_preview = _preview_update(display)

            # Re-render 3D preview with new bed theme
            new_glb = gr.update()
            if cache is not None:
                glb_path = generate_realtime_glb(cache)
                if glb_path:
                    new_glb = glb_path

            return new_is_dark, gr.update(value=label), new_preview, new_glb

        theme_btn.click(
            fn=None,
            inputs=None,
            outputs=None,
            js="""() => {
                const body = document.querySelector('body');
                const isDark = body.classList.contains('dark');
                if (isDark) {
                    body.classList.remove('dark');
                } else {
                    body.classList.add('dark');
                }
                // Update URL param without reload
                const url = new URL(window.location.href);
                url.searchParams.set('__theme', isDark ? 'light' : 'dark');
                window.history.replaceState({}, '', url.toString());
                return [];
            }"""
        ).then(
            fn=_on_theme_toggle,
            inputs=[theme_state, lang_state, components['_conv_preview_cache']],
            outputs=[theme_state, theme_btn, components['_conv_preview'], components['_conv_3d_preview']]
        )

        def init_theme(current_lang, request: gr.Request = None):
            theme = None
            try:
                if request is not None:
                    theme = request.query_params.get("__theme")
            except Exception:
                theme = None

            is_dark = theme == "dark"
            label = I18n.get('theme_toggle_day', current_lang) if is_dark else I18n.get('theme_toggle_night', current_lang)
            return is_dark, gr.update(value=label)

        app.load(
            fn=init_theme,
            inputs=[lang_state],
            outputs=[theme_state, theme_btn]
        )

        app.load(
            fn=on_lut_select,
            inputs=[components['dropdown_conv_lut_dropdown']],
            outputs=[components['state_conv_lut_path'], components['md_conv_lut_status']]
        ).then(
            fn=_update_lut_grid,
            inputs=[components['state_conv_lut_path'], lang_state, components['state_conv_palette_mode']],
            outputs=[components['conv_lut_grid_view']]
        ).then(
            fn=_detect_and_enforce_structure,
            inputs=[components['state_conv_lut_path'], components['checkbox_conv_coating_enable']],
            outputs=[components['radio_conv_color_mode'], components['radio_conv_structure'], components['checkbox_conv_relief_mode']]
        )

        # Settings: cache clearing and counter reset
        def on_clear_cache(lang):
            cache_size_before = Stats.get_cache_size()
            _, _ = Stats.clear_cache()
            cache_size_after = Stats.get_cache_size()
            freed_size = max(cache_size_before - cache_size_after, 0)

            status_msg = I18n.get('settings_cache_cleared', lang).format(_format_bytes(freed_size))
            new_cache_size = I18n.get('settings_cache_size', lang).format(_format_bytes(cache_size_after))
            return status_msg, new_cache_size

        def on_clear_output(lang):
            output_size_before = Stats.get_output_size()
            _, _ = Stats.clear_output()
            output_size_after = Stats.get_output_size()
            freed_size = max(output_size_before - output_size_after, 0)

            status_msg = I18n.get('settings_output_cleared', lang).format(_format_bytes(freed_size))
            new_output_size = I18n.get('settings_output_size', lang).format(_format_bytes(output_size_after))
            return status_msg, new_output_size

        def on_reset_counters(lang):
            Stats.reset_all()
            new_stats = Stats.get_all()

            status_msg = I18n.get('settings_counters_reset', lang).format(
                new_stats.get('calibrations', 0),
                new_stats.get('extractions', 0),
                new_stats.get('conversions', 0)
            )
            return status_msg, _get_stats_html(lang, new_stats)

        # ========== Advanced Tab Events ==========
        def on_unlock_max_size(unlock: bool):
            """Toggle max size limit for width/height sliders."""
            new_max = 9999 if unlock else 400
            return gr.update(maximum=new_max), gr.update(maximum=new_max)

        components['checkbox_unlock_max_size'].change(
            on_unlock_max_size,
            inputs=[components['checkbox_unlock_max_size']],
            outputs=[components['slider_conv_width'], components['slider_conv_height']]
        )

        # ========== About Tab Events ==========
        components['btn_clear_cache'].click(
            fn=on_clear_cache,
            inputs=[lang_state],
            outputs=[components['md_settings_status'], components['md_cache_size']]
        )

        components['btn_clear_output'].click(
            fn=on_clear_output,
            inputs=[lang_state],
            outputs=[components['md_settings_status'], components['md_output_size']]
        )

        components['btn_reset_counters'].click(
            fn=on_reset_counters,
            inputs=[lang_state],
            outputs=[components['md_settings_status'], stats_html]
        )

        # ═══════ LUT Merge Tab Events ═══════
        components['dd_merge_primary'].change(
            fn=on_merge_primary_select,
            inputs=[components['dd_merge_primary'], lang_state],
            outputs=[
                components['md_merge_mode_primary'],
                components['dd_merge_secondary'],
            ],
        )
        components['dd_merge_secondary'].change(
            fn=on_merge_secondary_change,
            inputs=[components['dd_merge_secondary'], lang_state],
            outputs=[components['md_merge_secondary_info']],
        )
        components['btn_merge'].click(
            fn=on_merge_execute,
            inputs=[
                components['dd_merge_primary'],
                components['dd_merge_secondary'],
                components['slider_dedup_threshold'],
                lang_state,
            ],
            outputs=[
                components['md_merge_status'],
                components['dd_merge_primary'],
                components['dd_merge_secondary'],
            ],
        )

        def update_stats_bar(lang):
            stats = Stats.get_all()
            return _get_stats_html(lang, stats)

        if 'cal_event' in components:
            components['cal_event'].then(
                fn=update_stats_bar,
                inputs=[lang_state],
                outputs=[stats_html]
            )

        if 'ext_event' in components:
            components['ext_event'].then(
                fn=update_stats_bar,
                inputs=[lang_state],
                outputs=[stats_html]
            )

        if 'conv_event' in components:
            components['conv_event'].then(
                fn=update_stats_bar,
                inputs=[lang_state],
                outputs=[stats_html]
            )

        # Palette mode switch (Advanced tab)
        if 'radio_palette_mode' in components:
            def on_palette_mode_change(mode, lut_path, lang):
                _save_user_setting("palette_mode", mode)
                return mode, _update_lut_grid(lut_path, lang, mode)

            components['radio_palette_mode'].change(
                fn=on_palette_mode_change,
                inputs=[components['radio_palette_mode'],
                        components['state_conv_lut_path'], lang_state],
                outputs=[components['state_conv_palette_mode'],
                         components['conv_lut_grid_view']]
            )

    return app


# ---------- Helpers for i18n updates ----------

def _get_header_html(lang: str) -> str:
    """Return header HTML (title + subtitle) for the given language."""
    return f"<h1>✨ Lumina Studio</h1><p>{I18n.get('app_subtitle', lang)}</p>"


def _get_stats_html(lang: str, stats: dict) -> str:
    """Return stats bar HTML (calibrations / extractions / conversions)."""
    return f"""
    <div class="stats-bar">
        {I18n.get('stats_total', lang)}: 
        <strong>{stats.get('calibrations', 0)}</strong> {I18n.get('stats_calibrations', lang)} | 
        <strong>{stats.get('extractions', 0)}</strong> {I18n.get('stats_extractions', lang)} | 
        <strong>{stats.get('conversions', 0)}</strong> {I18n.get('stats_conversions', lang)}
    </div>
    """


def _get_footer_html(lang: str) -> str:
    """Return footer HTML for the given language."""
    return f"""
    <div class="footer">
        <p>{I18n.get('footer_tip', lang)}</p>
    </div>
    """


def _get_all_component_updates(lang: str, components: dict) -> list:
    """Build a list of gr.update() for all components to apply i18n.

    Skips dynamic status components (md_conv_lut_status, textbox_conv_status)
    so their runtime text is not overwritten.
    Also skips event objects (Dependency) which are not valid components.

    Args:
        lang: Target language code ('zh' or 'en').
        components: Dict of component key -> Gradio component.

    Returns:
        list: One gr.update() per component, in dict iteration order.
    """
    from gradio.blocks import Block
    updates = []
    for key, component in components.items():
        # Skip event objects (Dependency)
        if not isinstance(component, Block):
            continue

        if key == 'md_conv_lut_status' or key == 'textbox_conv_status':
            updates.append(gr.update())
            continue
        if key == 'md_settings_title':
            updates.append(gr.update(value=I18n.get('settings_title', lang)))
            continue
        if key == 'md_cache_size':
            cache_size = Stats.get_cache_size()
            updates.append(gr.update(value=I18n.get('settings_cache_size', lang).format(_format_bytes(cache_size))))
            continue
        if key == 'btn_clear_cache':
            updates.append(gr.update(value=I18n.get('settings_clear_cache', lang)))
            continue
        if key == 'md_output_size':
            output_size = Stats.get_output_size()
            updates.append(gr.update(value=I18n.get('settings_output_size', lang).format(_format_bytes(output_size))))
            continue
        if key == 'btn_clear_output':
            updates.append(gr.update(value=I18n.get('settings_clear_output', lang)))
            continue
        if key == 'btn_reset_counters':
            updates.append(gr.update(value=I18n.get('settings_reset_counters', lang)))
            continue
        if key == 'md_settings_status':
            updates.append(gr.update())
            continue
        # Merge tab: skip dynamic status
        if key == 'md_merge_status':
            updates.append(gr.update())
            continue
        if key == 'md_merge_title':
            updates.append(gr.update(value=I18n.get('merge_title', lang)))
            continue
        if key == 'md_merge_desc':
            updates.append(gr.update(value=I18n.get('merge_desc', lang)))
            continue
        if key == 'md_merge_mode_primary':
            updates.append(gr.update())  # dynamic, don't overwrite
            continue
        if key == 'md_merge_secondary_info':
            updates.append(gr.update())  # dynamic, don't overwrite
            continue
        if key == 'dd_merge_primary':
            updates.append(gr.update(label=I18n.get('merge_lut_primary_label', lang)))
            continue
        if key == 'dd_merge_secondary':
            updates.append(gr.update(label=I18n.get('merge_lut_secondary_label', lang)))
            continue
        if key == 'slider_dedup_threshold':
            updates.append(gr.update(
                label=I18n.get('merge_dedup_label', lang),
                info=I18n.get('merge_dedup_info', lang),
            ))
            continue
        if key == 'btn_merge':
            updates.append(gr.update(value=I18n.get('merge_btn', lang)))
            continue

        if key.startswith('md_'):
            updates.append(gr.update(value=I18n.get(key[3:], lang)))
        elif key.startswith('lbl_'):
            updates.append(gr.update(label=I18n.get(key[4:], lang)))
        elif key.startswith('btn_'):
            updates.append(gr.update(value=I18n.get(key[4:], lang)))
        elif key.startswith('radio_'):
            choice_key = key[6:]
            if choice_key == 'conv_color_mode' or choice_key == 'cal_color_mode' or choice_key == 'ext_color_mode':
                choices = [
                    ("BW (Black & White)", "BW (Black & White)"),
                    ("4-Color (1024 colors)", "4-Color"),
                    ("5-Color Extended (2468)", "5-Color Extended"),
                    ("6-Color (Smart 1296)", "6-Color (Smart 1296)"),
                    ("8-Color Max", "8-Color Max"),
                ]
                # Only the converter tab needs the Merged option
                if choice_key == 'conv_color_mode':
                    choices.append(("🔀 Merged", "Merged"))
                updates.append(gr.update(
                    label=I18n.get(choice_key, lang),
                    choices=choices,
                ))
            elif choice_key == 'conv_structure':
                updates.append(gr.update(
                    label=I18n.get(choice_key, lang),
                    choices=[
                        (I18n.get('conv_structure_double', lang), I18n.get('conv_structure_double', 'en')),
                        (I18n.get('conv_structure_single', lang), I18n.get('conv_structure_single', 'en'))
                    ]
                ))
            elif choice_key == 'conv_modeling_mode':
                updates.append(gr.update(
                    label=I18n.get(choice_key, lang),
                    info=I18n.get('conv_modeling_mode_info', lang),
                    choices=[
                        (I18n.get('conv_modeling_mode_hifi', lang), ModelingMode.HIGH_FIDELITY),
                        (I18n.get('conv_modeling_mode_pixel', lang), ModelingMode.PIXEL),
                        (I18n.get('conv_modeling_mode_vector', lang), ModelingMode.VECTOR)
                    ]
                ))
            else:
                # Fallback for radios without i18n mapping (e.g., ext_page)
                updates.append(gr.update())
        elif key.startswith('slider_'):
            slider_key = key[7:]
            updates.append(gr.update(label=I18n.get(slider_key, lang)))
        elif key.startswith('color_'):
            color_key = key[6:]
            updates.append(gr.update(label=I18n.get(color_key, lang)))
        elif key.startswith('checkbox_'):
            checkbox_key = key[9:]
            info_key = checkbox_key + '_info'
            if info_key in I18n.TEXTS:
                updates.append(gr.update(
                    label=I18n.get(checkbox_key, lang),
                    info=I18n.get(info_key, lang)
                ))
            else:
                updates.append(gr.update(label=I18n.get(checkbox_key, lang)))
        elif key.startswith('dropdown_'):
            dropdown_key = key[9:]
            info_key = dropdown_key + '_info'
            if info_key in I18n.TEXTS:
                updates.append(gr.update(
                    label=I18n.get(dropdown_key, lang),
                    info=I18n.get(info_key, lang)
                ))
            else:
                updates.append(gr.update(label=I18n.get(dropdown_key, lang)))
        elif key.startswith('image_'):
            image_key = key[6:]
            updates.append(gr.update(label=I18n.get(image_key, lang)))
        elif key.startswith('file_'):
            file_key = key[5:]
            updates.append(gr.update(label=I18n.get(file_key, lang)))
        elif key.startswith('textbox_'):
            textbox_key = key[8:]
            updates.append(gr.update(label=I18n.get(textbox_key, lang)))
        elif key.startswith('num_'):
            num_key = key[4:]
            updates.append(gr.update(label=I18n.get(num_key, lang)))
        elif key == 'html_crop_modal':
            from ui.crop_extension import get_crop_modal_html
            updates.append(gr.update(value=get_crop_modal_html(lang)))
        elif key.startswith('html_'):
            html_key = key[5:]
            updates.append(gr.update(value=I18n.get(html_key, lang)))
        elif key.startswith('accordion_'):
            acc_key = key[10:]
            updates.append(gr.update(label=I18n.get(acc_key, lang)))
        else:
            updates.append(gr.update())
    
    return updates


def _get_component_list(components: dict) -> list:
    """Return component values in dict order (for Gradio outputs).

    Filters out event objects (Dependency) which are not valid outputs.
    """
    from gradio.blocks import Block
    result = []
    for v in components.values():
        if isinstance(v, Block):
            result.append(v)
    return result


def get_extractor_reference_image(mode_str, page_choice="Page 1"):
    """Load or generate reference image for color extractor (disk-cached).

    Uses assets/ with filenames ref_bw_standard.png, ref_cmyw_standard.png,
    ref_rybw_standard.png, ref_5color_ext_page1.png, ref_5color_ext_page2.png,
    ref_6color_smart.png, or ref_8color_smart.png.
    Generates via calibration board logic if missing.

    Args:
        mode_str: Color mode label (e.g. "BW", "CMYW", "RYBW", "6-Color", "8-Color").

    Returns:
        PIL.Image.Image | None: Reference image or None on error.
    """
    import sys
    
    # Handle both dev and frozen modes
    if getattr(sys, 'frozen', False):
        # In frozen mode, check both _MEIPASS (bundled) and cwd (user data)
        cache_dir = os.path.join(os.getcwd(), "assets")
        bundled_assets = os.path.join(sys._MEIPASS, "assets")
    else:
        cache_dir = "assets"
        bundled_assets = None
    
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir, exist_ok=True)

    # Determine filename and generation mode based on color system
    gen_page_idx = 0
    if "8-Color" in mode_str:
        filename = "ref_8color_smart.png"
        gen_mode = "8-Color"
    elif "5-Color Extended" in mode_str:
        is_page2 = page_choice is not None and "2" in str(page_choice)
        filename = "ref_5color_ext_page2.png" if is_page2 else "ref_5color_ext_page1.png"
        gen_mode = "5-Color Extended"
        gen_page_idx = 1 if is_page2 else 0
    elif "6-Color" in mode_str or "1296" in mode_str:
        filename = "ref_6color_smart.png"
        gen_mode = "6-Color"
    elif "4-Color" in mode_str:
        # Unified 4-Color mode defaults to RYBW
        filename = "ref_rybw_standard.png"
        gen_mode = "RYBW"
    elif "CMYW" in mode_str:
        filename = "ref_cmyw_standard.png"
        gen_mode = "CMYW"
    elif "RYBW" in mode_str:
        filename = "ref_rybw_standard.png"
        gen_mode = "RYBW"
    elif mode_str == "BW (Black & White)" or mode_str == "BW":
        filename = "ref_bw_standard.png"
        gen_mode = "BW"
    else:
        # Default to RYBW
        filename = "ref_rybw_standard.png"
        gen_mode = "RYBW"

    filepath = os.path.join(cache_dir, filename)
    
    # In frozen mode, also check bundled assets
    if bundled_assets:
        bundled_filepath = os.path.join(bundled_assets, filename)
        if os.path.exists(bundled_filepath):
            try:
                print(f"[UI] Loading reference from bundle: {bundled_filepath}")
                return PILImage.open(bundled_filepath)
            except Exception as e:
                print(f"Error loading bundled asset: {e}")

    if os.path.exists(filepath):
        try:
            print(f"[UI] Loading reference from cache: {filepath}")
            return PILImage.open(filepath)
        except Exception as e:
            print(f"Error loading cache, regenerating: {e}")

    print(f"[UI] Generating new reference for {gen_mode}...")
    try:
        block_size = 10
        gap = 0
        backing = "White"

        if gen_mode == "8-Color":
            from core.calibration import generate_8color_board
            _, img, _ = generate_8color_board(0)  # Page 1
        elif gen_mode == "5-Color Extended":
            from core.calibration import generate_5color_extended_board
            _, img, _ = generate_5color_extended_board(block_size, gap, page_index=gen_page_idx)
        elif gen_mode == "6-Color":
            from core.calibration import generate_smart_board
            _, img, _ = generate_smart_board(block_size, gap)
        elif gen_mode == "BW":
            from core.calibration import generate_bw_calibration_board
            _, img, _ = generate_bw_calibration_board(block_size, gap, backing)
        else:
            from core.calibration import generate_calibration_board
            _, img, _ = generate_calibration_board(gen_mode, block_size, gap, backing)

        if img:
            if not isinstance(img, PILImage.Image):
                import numpy as np
                img = PILImage.fromarray(img.astype('uint8'), 'RGB')

            img.save(filepath)
            print(f"[UI] Cached reference saved to {filepath}")

        return img

    except Exception as e:
        print(f"Error generating reference: {e}")
        return None


# ---------- Tab builders ----------

def create_converter_tab_content(lang: str, lang_state=None, theme_state=None) -> dict:
    """Build converter tab UI and events. Returns component dict for i18n.

    Args:
        lang: Initial language code ('zh' or 'en').
        lang_state: Gradio State for language.
        theme_state: Gradio State for theme (False=light, True=dark).

    Returns:
        dict: Mapping from component key to Gradio component (and state refs).
    """
    components = {}
    if lang_state is None:
        lang_state = gr.State(value=lang)
    conv_loop_pos = gr.State(None)
    conv_preview_cache = gr.State(None)

    with gr.Row():
        with gr.Column(scale=1, min_width=320, elem_classes=["left-sidebar"]):
            components['md_conv_input_section'] = gr.Markdown(I18n.get('conv_input_section', lang))

            saved_lut = load_last_lut_setting()
            current_choices = LUTManager.get_lut_choices()
            default_lut_value = saved_lut if saved_lut in current_choices else None

            # Load saved preferences
            _user_prefs = _load_user_settings()
            saved_color_mode = _user_prefs.get("last_color_mode", "4-Color")
            saved_modeling_mode_str = _user_prefs.get("last_modeling_mode", ModelingMode.HIGH_FIDELITY.value)
            try:
                saved_modeling_mode = ModelingMode(saved_modeling_mode_str)
            except (ValueError, KeyError):
                saved_modeling_mode = ModelingMode.HIGH_FIDELITY

            with gr.Row():
                components['dropdown_conv_lut_dropdown'] = gr.Dropdown(
                    choices=current_choices,
                    label="校准数据 (.npy) / Calibration Data",
                    value=default_lut_value,
                    interactive=True,
                    scale=2
                )
                conv_lut_upload = gr.File(
                    label="",
                    show_label=False,
                    file_types=['.npy'],
                    height=84,
                    min_width=100,
                    scale=1,
                    elem_classes=["tall-upload"]
                )
            
            components['md_conv_lut_status'] = gr.Markdown(
                value=I18n.get('conv_lut_status_default', lang),
                visible=True,
                elem_classes=["lut-status"]
            )
            conv_lut_path = gr.State(None)
            conv_palette_mode = gr.State(value=_load_user_settings().get("palette_mode", "swatch"))
            components['state_conv_palette_mode'] = conv_palette_mode

            with gr.Row():
                components['checkbox_conv_batch_mode'] = gr.Checkbox(
                    label=I18n.get('conv_batch_mode', lang),
                    value=False,
                    info=I18n.get('conv_batch_mode_info', lang)
                )
            
            # ========== Image Crop Extension (Non-invasive) ==========
            # Hidden state for preprocessing
            preprocess_img_width = gr.State(0)
            preprocess_img_height = gr.State(0)
            preprocess_processed_path = gr.State(None)
            
            # Crop data states (used by JavaScript via hidden inputs)
            crop_data_state = gr.State({"x": 0, "y": 0, "w": 100, "h": 100})
            
            # Hidden textbox for JavaScript to pass crop data to Python (use CSS to hide)
            crop_data_json = gr.Textbox(
                value='{"x":0,"y":0,"w":100,"h":100,"autoColor":true}',
                elem_id="crop-data-json",
                visible=True,
                elem_classes=["hidden-crop-component"]
            )
            
            # Hidden buttons for JavaScript to trigger Python callbacks (use CSS to hide)
            use_original_btn = gr.Button("use_original", elem_id="use-original-hidden-btn", elem_classes=["hidden-crop-component"])
            confirm_crop_btn = gr.Button("confirm_crop", elem_id="confirm-crop-hidden-btn", elem_classes=["hidden-crop-component"])
            
            # Cropper.js Modal HTML (JS is loaded via head parameter in main.py)
            from ui.crop_extension import get_crop_modal_html
            cropper_modal_html = gr.HTML(
                get_crop_modal_html(lang),
                elem_classes=["crop-modal-container"]
            )
            components['html_crop_modal'] = cropper_modal_html
            
            # Hidden HTML element to store dimensions for JavaScript
            preprocess_dimensions_html = gr.HTML(
                value='<div id="preprocess-dimensions-data" data-width="0" data-height="0" style="display:none;"></div>',
                visible=True,
                elem_classes=["hidden-crop-component"]
            )
            # ========== END Image Crop Extension ==========
            
            components['image_conv_image_label'] = gr.Image(
                label=I18n.get('conv_image_label', lang),
                type="filepath",
                image_mode=None,  # Auto-detect mode to support both JPEG and PNG
                height=400,
                visible=True,
                elem_id="conv-image-input",
            )
            components['file_conv_batch_input'] = gr.File(
                label=I18n.get('conv_batch_input', lang),
                file_count="multiple",
                file_types=SUPPORTED_IMAGE_FILE_TYPES,
                visible=False
            )
            components['md_conv_params_section'] = gr.Markdown(I18n.get('conv_params_section', lang))

            with gr.Row(elem_classes=["compact-row"]):
                components['slider_conv_width'] = gr.Slider(
                    minimum=10, maximum=400, value=60, step=1,
                    label=I18n.get('conv_width', lang),
                    interactive=True
                )
                components['slider_conv_height'] = gr.Slider(
                    minimum=10, maximum=400, value=60, step=1,
                    label=I18n.get('conv_height', lang),
                    interactive=True
                )
                components['slider_conv_thickness'] = gr.Slider(
                    0.2, 3.5, 1.2, step=0.08,
                    label=I18n.get('conv_thickness', lang)
                )
            
            
            # Bed size selector removed from sidebar — now overlaid on preview
            
            # ========== 2.5D Relief Mode Controls ==========
            components['checkbox_conv_relief_mode'] = gr.Checkbox(
                label="开启 2.5D 浮雕模式 | Enable Relief Mode",
                value=False,
                info="为不同颜色设置独立的Z轴高度，保留顶部5层光学叠色（强制单面，观赏面朝上）"
            )
            
            # Relief height slider (only visible when relief mode is enabled and a color is selected)
            components['slider_conv_relief_height'] = gr.Slider(
                minimum=0.08,
                maximum=20.0,
                value=1.2,
                step=0.1,
                label="当前选中颜色的独立高度 | Selected Color Z-Height (mm)",
                visible=False,
                info="调整当前选中颜色的总高度（包含光学层）"
            )
            
            # Max relief height slider - extracted outside Accordion so it remains visible
            # when heightmap mode hides the Accordion (shared by both auto-height and heightmap modes)
            components['slider_conv_auto_height_max'] = gr.Slider(
                minimum=0.08,
                maximum=15.0,
                value=2.4,
                step=0.08,
                label="最大浮雕高度 | Max Relief Height (mm)",
                info="所有颜色的最大高度（相对于底板）",
                visible=False
            )
            
            # Auto Height Generator (only visible when relief mode is enabled)
            with gr.Accordion(label="⚡ 高度生成器 | Height Generator", open=True, visible=False) as conv_auto_height_accordion:
                components['radio_conv_auto_height_mode'] = gr.Radio(
                    choices=[
                        ("深色凸起 | Darker Higher", "深色凸起"),
                        ("浅色凸起 | Lighter Higher", "浅色凸起"),
                        ("根据高度图 | Use Heightmap", "根据高度图")
                    ],
                    value="深色凸起",
                    label="排列规则 | Sorting Rule",
                    info="选择高度分配方式：按颜色明度或使用自定义高度图"
                )
                
                components['btn_conv_auto_height_apply'] = gr.Button(
                    "✨ 一键生成高度 | Apply Auto Heights",
                    variant="primary"
                )
                
                # ========== Heightmap Upload Components (inside accordion) ==========
                with gr.Row(visible=False) as conv_heightmap_row:
                    components['image_conv_heightmap'] = gr.Image(
                        type="filepath",
                        label="上传高度图 | Upload Heightmap (PNG/JPG/BMP/HEIC)",
                        visible=True,
                        height=200,
                        sources=["upload"],
                        interactive=True,
                    )
                    components['image_conv_heightmap_preview'] = gr.Image(
                        label="高度图预览 | Heightmap Preview",
                        visible=False,
                        interactive=False,
                        height=200
                    )
                components['row_conv_heightmap'] = conv_heightmap_row
                # ========== END Heightmap Upload Components ==========
            
            components['accordion_conv_auto_height'] = conv_auto_height_accordion
            
            # State to store per-color height mapping: {hex_color: height_mm}
            conv_color_height_map = gr.State({})
            
            # State to track currently selected color for height adjustment
            conv_relief_selected_color = gr.State(None)
            # ========== END 2.5D Relief Mode Controls ==========
            
            conv_target_height_mm = components['slider_conv_height']

            with gr.Row(elem_classes=["compact-row"]):
                components['radio_conv_color_mode'] = gr.Radio(
                    choices=[
                        ("BW (Black & White)", "BW (Black & White)"),
                        ("4-Color (1024 colors)", "4-Color"),
                        ("5-Color Extended (2468)", "5-Color Extended"),
                        ("6-Color (Smart 1296)", "6-Color (Smart 1296)"),
                        ("8-Color Max", "8-Color Max"),
                        ("🔀 Merged", "Merged"),
                    ],
                    value=saved_color_mode,
                    label=I18n.get('conv_color_mode', lang),
                    interactive=False,
                    visible=False,
                )
                
                components['radio_conv_structure'] = gr.Radio(
                    choices=[
                        (I18n.get('conv_structure_double', lang), I18n.get('conv_structure_double', 'en')),
                        (I18n.get('conv_structure_single', lang), I18n.get('conv_structure_single', 'en'))
                    ],
                    value=I18n.get('conv_structure_double', 'en'),
                    label=I18n.get('conv_structure', lang)
                )

            with gr.Row(elem_classes=["compact-row"]):
                components['radio_conv_modeling_mode'] = gr.Radio(
                    choices=[
                        (I18n.get('conv_modeling_mode_hifi', lang), ModelingMode.HIGH_FIDELITY),
                        (I18n.get('conv_modeling_mode_pixel', lang), ModelingMode.PIXEL),
                        (I18n.get('conv_modeling_mode_vector', lang), ModelingMode.VECTOR)
                    ],
                    value=saved_modeling_mode,
                    label=I18n.get('conv_modeling_mode', lang),
                    info=I18n.get('conv_modeling_mode_info', lang),
                    elem_classes=["vertical-radio"],
                    scale=2
                )
                
            with gr.Accordion(label=I18n.get('conv_advanced', lang), open=False) as conv_advanced_acc:
                components['accordion_conv_advanced'] = conv_advanced_acc
                with gr.Row():
                    components['slider_conv_quantize_colors'] = gr.Slider(
                        minimum=8, maximum=256, step=8, value=48,
                        label=I18n.get('conv_quantize_colors', lang),
                        info=I18n.get('conv_quantize_info', lang)
                    )
                with gr.Row():
                    components['btn_conv_auto_color'] = gr.Button(
                        I18n.get('conv_auto_color_btn', lang),
                        variant="secondary",
                        size="sm"
                    )
                with gr.Row():
                    components['slider_conv_tolerance'] = gr.Slider(
                        0, 150, 40,
                        label=I18n.get('conv_tolerance', lang),
                        info=I18n.get('conv_tolerance_info', lang)
                    )
                with gr.Row():
                    components['checkbox_conv_auto_bg'] = gr.Checkbox(
                        label=I18n.get('conv_auto_bg', lang),
                        value=False,
                        info=I18n.get('conv_auto_bg_info', lang)
                    )
                with gr.Row():
                    components['checkbox_conv_cleanup'] = gr.Checkbox(
                        label="孤立像素清理 | Isolated Pixel Cleanup",
                        value=True,
                        info="清理 LUT 匹配后的孤立像素，提升打印成功率"
                    )
                with gr.Row():
                    components['checkbox_conv_separate_backing'] = gr.Checkbox(
                        label="底板单独一个对象 | Separate Backing",
                        value=False,
                        info="勾选后，底板将作为独立对象导出到3MF文件"
                    )
                with gr.Row():
                    components['slider_conv_hue_weight'] = gr.Slider(
                        minimum=0.0, maximum=1.0, step=0.1, value=0.0,
                        label="🎨 色相保护 | Hue Protection",
                        info="0=纯色差匹配(默认), 0.3=明显保护, 0.5=强保护(推荐), 1.0=最强。避免浅色匹配到错误色系"
                    )
            
            # Crop interface toggle - outside Accordion for immediate DOM availability
            with gr.Row():
                # Load saved crop modal preference
                saved_enable_crop = _load_user_settings().get("enable_crop_modal", True)
                print(f"[CROP_SETTING] Loading crop modal preference: {saved_enable_crop}")
                components['checkbox_conv_enable_crop'] = gr.Checkbox(
                    label="🖼️ 启用裁剪界面 | Enable Crop Interface",
                    value=saved_enable_crop,
                    info="上传图片时显示裁剪界面 | Show crop interface when uploading images",
                    elem_id="conv-enable-crop-checkbox"
                )
            
            gr.Markdown("---")
            
        with gr.Column(scale=4, elem_classes=["workspace-area"]):
            with gr.Row():
                with gr.Column(scale=3):
                    components['md_conv_preview_section'] = gr.Markdown(
                        I18n.get('conv_preview_section', lang)
                    )

                    # Bed size dropdown overlaid on preview top-right
                    with gr.Row(elem_id="conv-bed-size-overlay"):
                        components['radio_conv_bed_size'] = gr.Dropdown(
                            choices=[b[0] for b in BedManager.BEDS],
                            value=BedManager.DEFAULT_BED,
                            label=None,
                            show_label=False,
                            container=False,
                            min_width=140,
                            elem_id="conv-bed-size-dropdown"
                        )

                    conv_preview = gr.Image(
                        label="",
                        type="numpy",
                        value=render_preview(None, None, 0, 0, 0, 0, False, None, is_dark=False),
                        height=750,
                        interactive=False,
                        show_label=False,
                        elem_id="conv-preview"
                    )
                    
                    # ========== Color Palette & Replacement ==========
                    with gr.Accordion(I18n.get('conv_palette', lang), open=False) as conv_palette_acc:
                        components['accordion_conv_palette'] = conv_palette_acc
                        # 状态变量
                        conv_selected_color = gr.State(None)  # 原图中被点击的颜色
                        conv_replacement_regions = gr.State([])  # 区域替换列表
                        conv_replacement_history = gr.State([])
                        conv_replacement_color_state = gr.State(None)  # 最终确定的 LUT 颜色
                        conv_selected_user_row_id = gr.State(None)
                        conv_selected_auto_row_id = gr.State(None)
                        conv_free_color_set = gr.State(set())  # 自由色集合

                        # 隐藏的交互组件
                        conv_color_selected_hidden = gr.Textbox(
                            value="",
                            visible=True,
                            interactive=True,
                            elem_id="conv-color-selected-hidden",
                            elem_classes=["hidden-textbox-trigger"],
                            label="",
                            show_label=False,
                            container=False
                        )
                        conv_highlight_color_hidden = gr.Textbox(
                            value="",
                            visible=True,
                            interactive=True,
                            elem_id="conv-highlight-color-hidden",
                            elem_classes=["hidden-textbox-trigger"],
                            label="",
                            show_label=False,
                            container=False
                        )
                        conv_highlight_trigger_btn = gr.Button(
                            "trigger_highlight",
                            visible=True,
                            elem_id="conv-highlight-trigger-btn",
                            elem_classes=["hidden-textbox-trigger"]
                        )
                        conv_color_trigger_btn = gr.Button(
                            "trigger_color",
                            visible=True,
                            elem_id="conv-color-trigger-btn",
                            elem_classes=["hidden-textbox-trigger"]
                        )

                        # LUT 选色隐藏组件（与 JS 绑定）
                        conv_lut_color_selected_hidden = gr.Textbox(
                            value="",
                            visible=True,
                            interactive=True,
                            elem_id="conv-lut-color-selected-hidden",
                            elem_classes=["hidden-textbox-trigger"],
                            label="",
                            show_label=False,
                            container=False
                        )
                        conv_lut_color_trigger_btn = gr.Button(
                            "trigger_lut_color",
                            elem_id="conv-lut-color-trigger-btn",
                            elem_classes=["hidden-textbox-trigger"],
                            visible=True
                        )
                        conv_palette_row_select_hidden = gr.Textbox(
                            value="",
                            visible=True,
                            interactive=True,
                            elem_id="conv-palette-row-select-hidden",
                            elem_classes=["hidden-textbox-trigger"],
                            label="",
                            show_label=False,
                            container=False
                        )
                        conv_palette_row_select_trigger_btn = gr.Button(
                            "trigger_palette_row_select",
                            visible=True,
                            elem_id="conv-palette-row-select-trigger-btn",
                            elem_classes=["hidden-textbox-trigger"]
                        )
                        conv_palette_delete_trigger_btn = gr.Button(
                            "trigger_palette_delete",
                            visible=True,
                            elem_id="conv-palette-delete-trigger-btn",
                            elem_classes=["hidden-textbox-trigger"]
                        )

                        # --- 新 UI 布局 ---
                        from ui.palette_extension import build_selected_dual_color_html

                        with gr.Row():
                            # 左侧：当前选中的原图颜色
                            with gr.Column(scale=1):
                                components['md_conv_palette_step1'] = gr.Markdown(
                                    I18n.get('conv_palette_step1', lang)
                                )
                                conv_selected_display = gr.HTML(
                                    value=build_selected_dual_color_html("#000000", "#000000", lang=lang),
                                    label=I18n.get('conv_palette_selected_label', lang),
                                    show_label=True
                                )
                                components['color_conv_palette_selected_label'] = conv_selected_display

                            # 右侧：LUT 真实色盘
                            with gr.Column(scale=2):
                                components['md_conv_palette_step2'] = gr.Markdown(
                                    I18n.get('conv_palette_step2', lang)
                                )

                                # 以色找色 ColorPicker
                                with gr.Row():
                                    conv_color_picker_search = gr.ColorPicker(
                                        label=I18n.get('lut_grid_picker_label', lang),
                                        value="#ff0000",
                                        interactive=True,
                                        info=I18n.get('lut_grid_picker_hint', lang)
                                    )
                                    conv_color_picker_btn = gr.Button(
                                        I18n.get('lut_grid_picker_btn', lang),
                                        variant="secondary",
                                        size="sm"
                                    )
                                components['color_conv_picker_search'] = conv_color_picker_search
                                components['btn_conv_picker_search'] = conv_color_picker_btn


                                conv_dual_recommend_html = gr.HTML(
                                    value="",
                                    label="",
                                    show_label=False
                                )

                                # LUT 网格 HTML
                                conv_lut_grid_view = gr.HTML(
                                    value=f"<div style='color:#888; padding:10px;'>{I18n.get('conv_palette_lut_loading', lang)}</div>",
                                    label="",
                                    show_label=False
                                )
                                components['conv_lut_grid_view'] = conv_lut_grid_view

                                # 显示用户选中的替换色
                                conv_replacement_display = gr.ColorPicker(
                                    label=I18n.get('conv_palette_replace_label', lang),
                                    interactive=False
                                )
                                components['color_conv_palette_replace_label'] = conv_replacement_display

                        # 操作按钮区
                        with gr.Row():
                            conv_apply_replacement = gr.Button(I18n.get('conv_palette_apply_btn', lang), variant="primary")
                            conv_undo_replacement = gr.Button(I18n.get('conv_palette_undo_btn', lang))
                            conv_clear_replacements = gr.Button(I18n.get('conv_palette_clear_btn', lang))
                            components['btn_conv_palette_apply_btn'] = conv_apply_replacement
                            components['btn_conv_palette_undo_btn'] = conv_undo_replacement
                            components['btn_conv_palette_clear_btn'] = conv_clear_replacements

                        # 自由色功能
                        with gr.Row():
                            conv_free_color_btn = gr.Button(
                                I18n.get('conv_free_color_btn', lang),
                                variant="secondary", size="sm"
                            )
                            conv_free_color_clear_btn = gr.Button(
                                I18n.get('conv_free_color_clear_btn', lang),
                                size="sm"
                            )
                            components['btn_conv_free_color'] = conv_free_color_btn
                            components['btn_conv_free_color_clear'] = conv_free_color_clear_btn
                        conv_free_color_html = gr.HTML(
                            value="",
                            show_label=False
                        )
                        components['html_conv_free_color_list'] = conv_free_color_html

                        # 调色板预览 HTML (保持原有逻辑，用于显示已替换列表)
                        components['md_conv_palette_replacements_label'] = gr.Markdown(
                            I18n.get('conv_palette_replacements_label', lang)
                        )
                        conv_palette_html = gr.HTML(
                            value=f"<p style='color:#888;'>{I18n.get('conv_palette_replacements_placeholder', lang)}</p>",
                            label="",
                            show_label=False
                        )
                    # ========== END Color Palette ==========
                    
                    # ========== Color Merging ==========
                    with gr.Accordion(I18n.get('merge_accordion_title', lang), open=False) as conv_merge_acc:
                        components['accordion_conv_merge'] = conv_merge_acc
                        
                        # 状态变量
                        conv_merge_map = gr.State({})  # 合并映射表
                        conv_merge_stats = gr.State({})  # 合并统计信息
                        
                        # 启用/禁用复选框
                        conv_merge_enable = gr.Checkbox(
                            label=I18n.get('merge_enable_label', lang),
                            value=True,  # 默认启用以便测试
                            info=I18n.get('merge_enable_info', lang)
                        )
                        components['checkbox_conv_merge_enable'] = conv_merge_enable
                        
                        # 参数滑块
                        with gr.Row():
                            conv_merge_threshold = gr.Slider(
                                minimum=0.1,
                                maximum=5.0,
                                value=0.5,
                                step=0.1,
                                label=I18n.get('merge_threshold_label', lang),
                                info=I18n.get('merge_threshold_info', lang)
                            )
                            components['slider_conv_merge_threshold'] = conv_merge_threshold
                            
                            conv_merge_max_distance = gr.Slider(
                                minimum=5,
                                maximum=50,
                                value=20,
                                step=1,
                                label=I18n.get('merge_max_distance_label', lang),
                                info=I18n.get('merge_max_distance_info', lang)
                            )
                            components['slider_conv_merge_max_distance'] = conv_merge_max_distance
                        
                        # 操作按钮
                        with gr.Row():
                            conv_merge_preview_btn = gr.Button(
                                I18n.get('merge_preview_btn', lang),
                                variant="primary"
                            )
                            conv_merge_apply_btn = gr.Button(
                                I18n.get('merge_apply_btn', lang),
                                variant="secondary"
                            )
                            conv_merge_revert_btn = gr.Button(
                                I18n.get('merge_revert_btn', lang)
                            )
                            components['btn_conv_merge_preview'] = conv_merge_preview_btn
                            components['btn_conv_merge_apply'] = conv_merge_apply_btn
                            components['btn_conv_merge_revert'] = conv_merge_revert_btn
                        
                        # 状态显示
                        conv_merge_status = gr.Markdown(
                            value=I18n.get('merge_status_empty', lang)
                        )
                        components['md_conv_merge_status'] = conv_merge_status
                    # ========== END Color Merging ==========
                    
                    with gr.Group(visible=False):
                        components['md_conv_loop_section'] = gr.Markdown(
                            I18n.get('conv_loop_section', lang)
                        )
                            
                        with gr.Row():
                            components['checkbox_conv_loop_enable'] = gr.Checkbox(
                                label=I18n.get('conv_loop_enable', lang),
                                value=False
                            )
                            components['btn_conv_loop_remove'] = gr.Button(
                                I18n.get('conv_loop_remove', lang),
                                size="sm"
                            )
                            
                        with gr.Row():
                            components['slider_conv_loop_width'] = gr.Slider(
                                2, 10, 4, step=0.5,
                                label=I18n.get('conv_loop_width', lang)
                            )
                            components['slider_conv_loop_length'] = gr.Slider(
                                4, 15, 8, step=0.5,
                                label=I18n.get('conv_loop_length', lang)
                            )
                            components['slider_conv_loop_hole'] = gr.Slider(
                                1, 5, 2.5, step=0.25,
                                label=I18n.get('conv_loop_hole', lang)
                            )
                            
                        with gr.Row():
                            components['slider_conv_loop_angle'] = gr.Slider(
                                -180, 180, 0, step=5,
                                label=I18n.get('conv_loop_angle', lang)
                            )
                            components['textbox_conv_loop_info'] = gr.Textbox(
                                label=I18n.get('conv_loop_info', lang),
                                interactive=False,
                                scale=2
                            )
                    # ========== Outline Settings (moved to right column) ==========

                    components['textbox_conv_status'] = gr.Textbox(
                        label=I18n.get('conv_status', lang),
                        lines=3,
                        interactive=False,
                        max_lines=10,
                        show_label=True
                    )
                with gr.Column(scale=1):
                    # ========== Outline Settings ==========
                    components['md_conv_outline_section'] = gr.Markdown(
                        I18n.get('conv_outline_section', lang)
                    )
                    with gr.Row():
                        components['checkbox_conv_outline_enable'] = gr.Checkbox(
                            label=I18n.get('conv_outline_enable', lang),
                            value=False
                        )
                    components['slider_conv_outline_width'] = gr.Slider(
                        0.5, 10, 2, step=0.5,
                        label=I18n.get('conv_outline_width', lang)
                    )
                    # ========== END Outline Settings ==========

                    # ========== Cloisonné Settings ==========
                    components['md_conv_cloisonne_section'] = gr.Markdown(
                        I18n.get('conv_cloisonne_section', lang)
                    )
                    with gr.Row():
                        components['checkbox_conv_cloisonne_enable'] = gr.Checkbox(
                            label=I18n.get('conv_cloisonne_enable', lang),
                            value=False
                        )
                    components['slider_conv_wire_width'] = gr.Slider(
                        0.2, 1.2, 0.4, step=0.1,
                        label=I18n.get('conv_cloisonne_wire_width', lang)
                    )
                    components['slider_conv_wire_height'] = gr.Slider(
                        0.04, 1.0, 0.4, step=0.04,
                        label=I18n.get('conv_cloisonne_wire_height', lang)
                    )
                    # ========== END Cloisonné Settings ==========

                    # ========== Coating Settings ==========
                    components['md_conv_coating_section'] = gr.Markdown(
                        I18n.get('conv_coating_section', lang)
                    )
                    with gr.Row():
                        components['checkbox_conv_coating_enable'] = gr.Checkbox(
                            label=I18n.get('conv_coating_enable', lang),
                            value=False
                        )
                    components['slider_conv_coating_height'] = gr.Slider(
                        0.08, 0.16, 0.08, step=0.08,
                        label=I18n.get('conv_coating_height', lang)
                    )
                    # ========== END Coating Settings ==========

                    # Action buttons (preview + generate)
                    with gr.Row(elem_classes=["action-buttons"]):
                        components['btn_conv_preview_btn'] = gr.Button(
                            I18n.get('conv_preview_btn', lang),
                            variant="secondary",
                            size="lg"
                        )
                        components['btn_conv_generate_btn'] = gr.Button(
                            I18n.get('conv_generate_btn', lang),
                            variant="primary",
                            size="lg"
                        )

                    # Split button: [Open in Slicer] [▼]
                    default_slicer = _get_default_slicer()
                    slicer_choices = _get_slicer_choices(lang)
                    default_slicer_label = ""
                    for label, sid in slicer_choices:
                        if sid == default_slicer:
                            default_slicer_label = label
                            break

                    with gr.Row(elem_id="conv-slicer-split-btn"):
                        components['btn_conv_open_slicer'] = gr.Button(
                            value=default_slicer_label or "📥 下载 3MF",
                            variant="secondary",
                            size="lg",
                            elem_id="conv-open-slicer-btn",
                            elem_classes=[_slicer_css_class(default_slicer)],
                            scale=5
                        )
                        components['btn_conv_slicer_arrow'] = gr.Button(
                            value="▾",
                            variant="secondary",
                            size="lg",
                            elem_id="conv-slicer-arrow-btn",
                            elem_classes=[_slicer_css_class(default_slicer)],
                            scale=1,
                            min_width=40
                        )
                    # Hidden dropdown (shown/hidden by arrow button)
                    components['dropdown_conv_slicer'] = gr.Dropdown(
                        choices=slicer_choices,
                        value=default_slicer,
                        label="",
                        show_label=False,
                        elem_id="conv-slicer-dropdown",
                        visible=False
                    )

                    # Hidden file component for download fallback
                    _show_file = (default_slicer == "download")
                    components['file_conv_download_file'] = gr.File(
                        label=I18n.get('conv_download_file', lang),
                        visible=_show_file
                    )
                    
                    # Color recipe log download
                    components['file_conv_color_recipe'] = gr.File(
                        label="颜色配方日志 / Color Recipe Log",
                        visible=_show_file
                    )
                    
                    components['btn_conv_stop'] = gr.Button(
                        value=I18n.get('conv_stop', lang),
                        variant="stop",
                        size="lg"
                    )

        # ========== Floating 3D Thumbnail (bottom-right corner) ==========
        with gr.Column(elem_id="conv-3d-thumbnail-container", visible=True) as conv_3d_thumb_col:
            conv_3d_preview = gr.Model3D(
                value=generate_empty_bed_glb(),
                label="3D",
                clear_color=[0.15, 0.15, 0.18, 1.0],
                height=180,
                elem_id="conv-3d-thumbnail"
            )
            components['btn_conv_3d_fullscreen'] = gr.Button(
                "⛶",
                variant="secondary",
                size="sm",
                elem_id="conv-3d-fullscreen-btn"
            )
        components['col_conv_3d_thumbnail'] = conv_3d_thumb_col

        # ========== Fullscreen 3D Preview Overlay ==========
        with gr.Column(visible=False, elem_id="conv-3d-fullscreen-container") as conv_3d_fullscreen_col:
            components['btn_conv_3d_back'] = gr.Button(
                "✕ 返回",
                variant="secondary",
                size="sm",
                elem_id="conv-3d-back-btn"
            )
            conv_3d_fullscreen = gr.Model3D(
                label="3D Fullscreen",
                clear_color=[0.12, 0.12, 0.15, 1.0],
                height=900,
                elem_id="conv-3d-fullscreen"
            )
        components['col_conv_3d_fullscreen'] = conv_3d_fullscreen_col

        # ========== 2D Thumbnail in fullscreen 3D mode (bottom-right) ==========
        with gr.Column(visible=False, elem_id="conv-2d-thumbnail-container") as conv_2d_thumb_col:
            conv_2d_thumb_preview = gr.Image(
                label="2D",
                type="numpy",
                interactive=False,
                height=160,
                elem_id="conv-2d-thumbnail"
            )
            components['btn_conv_2d_back'] = gr.Button(
                "⛶",
                variant="secondary",
                size="sm",
                elem_id="conv-2d-back-btn"
            )
        components['col_conv_2d_thumbnail'] = conv_2d_thumb_col
    
    # Event binding
    def toggle_batch_mode(is_batch):
        return [
            gr.update(visible=not is_batch),
            gr.update(visible=is_batch)
        ]

    components['checkbox_conv_batch_mode'].change(
        fn=toggle_batch_mode,
        inputs=[components['checkbox_conv_batch_mode']],
        outputs=[components['image_conv_image_label'], components['file_conv_batch_input']]
    )

    # Save crop modal preference when checkbox changes
    def on_crop_checkbox_change(enable_crop):
        print(f"[CROP_SETTING] Saving crop modal preference: {enable_crop}")
        _save_user_setting("enable_crop_modal", enable_crop)
        # Verify it was saved
        saved_value = _load_user_settings().get("enable_crop_modal")
        print(f"[CROP_SETTING] Verified saved value: {saved_value}")
        return None
    
    components['checkbox_conv_enable_crop'].change(
        fn=on_crop_checkbox_change,
        inputs=[components['checkbox_conv_enable_crop']],
        outputs=None
    )

    # ========== Image Crop Extension Events (Non-invasive) ==========
    from core.image_preprocessor import ImagePreprocessor
    
    def _parse_svg_dimensions(svg_path):
        """Parse SVG width/height with viewBox fallback."""
        try:
            root = ET.parse(svg_path).getroot()
        except Exception:
            return 0, 0

        def _parse_len(raw):
            if not raw:
                return None
            m = re.search(r"([0-9]+(?:\.[0-9]+)?)", str(raw))
            if not m:
                return None
            try:
                return int(float(m.group(1)))
            except Exception:
                return None

        w = _parse_len(root.get("width"))
        h = _parse_len(root.get("height"))

        if w and h and w > 0 and h > 0:
            return w, h

        view_box = root.get("viewBox") or root.get("viewbox")
        if view_box:
            try:
                parts = [float(v) for v in re.split(r"[,\s]+", view_box.strip()) if v]
                if len(parts) == 4:
                    vb_w = int(abs(parts[2]))
                    vb_h = int(abs(parts[3]))
                    if vb_w > 0 and vb_h > 0:
                        return vb_w, vb_h
            except Exception:
                pass

        return 0, 0

    def on_image_upload_process_with_html(image_path):
        """When image is uploaded, process and prepare for crop modal (不分析颜色).
        For HEIC/HEIF files, returns the converted PNG path back to the Image
        component so the browser can render it (browsers cannot display HEIC).
        """
        if image_path is None:
            return (
                0, 0, None,
                '<div id="preprocess-dimensions-data" data-width="0" data-height="0" data-is-svg="0" style="display:none;"></div>',
                None,
            )
        
        try:
            # SVG: Gradio's gr.Image stores SVG as base64 data-URL internally, but the
            # base64 decode fails on subsequent events (binascii.Error: Incorrect padding).
            # Fix: render the SVG to a temp PNG for display in gr.Image, while keeping the
            # original SVG path in preprocess_processed_path for the vector converter.
            if isinstance(image_path, str) and image_path.lower().endswith(".svg"):
                width, height = _parse_svg_dimensions(image_path)
                dimensions_html = (
                    f'<div id="preprocess-dimensions-data" data-width="{width}" '
                    f'data-height="{height}" data-is-svg="1" style="display:none;"></div>'
                )
                # Try to render SVG → PNG so gr.Image gets a safe raster file
                display_path = gr.update()
                try:
                    from svglib.svglib import svg2rlg
                    from reportlab.graphics import renderPM
                    import tempfile, os as _os
                    drawing = svg2rlg(image_path)
                    if drawing is not None:
                        tmp_png = tempfile.NamedTemporaryFile(
                            suffix=".png", delete=False,
                            dir=_os.path.dirname(image_path)
                        )
                        tmp_png.close()
                        renderPM.drawToFile(drawing, tmp_png.name, fmt="PNG")
                        display_path = tmp_png.name
                        print(f"[SVG_UPLOAD] Rendered SVG preview → {tmp_png.name}")
                except Exception as render_err:
                    print(f"[SVG_UPLOAD] Could not render SVG preview: {render_err}")
                # preprocess_processed_path keeps the original SVG for the converter;
                # image_conv_image_label gets the PNG (or unchanged) to avoid base64 errors.
                return (width, height, image_path, dimensions_html, display_path)

            info = ImagePreprocessor.process_upload(image_path)
            # 不在这里分析颜色，等用户确认裁剪后再分析
            dimensions_html = (
                f'<div id="preprocess-dimensions-data" data-width="{info.width}" '
                f'data-height="{info.height}" data-is-svg="0" style="display:none;"></div>'
            )
            # If the image was converted (e.g. HEIC→PNG), feed the PNG back to
            # the Image component so the browser can actually render it.
            display_path = info.processed_path if info.was_converted else gr.update()
            return (info.width, info.height, info.processed_path, dimensions_html, display_path)
        except Exception as e:
            print(f"Image upload error: {e}")
            return (0, 0, None, '<div id="preprocess-dimensions-data" data-width="0" data-height="0" data-is-svg="0" style="display:none;"></div>', gr.update())
    
    # JavaScript to open crop modal (不传递颜色推荐，弹窗中不显示)
    # Check if crop modal is enabled before opening
    open_crop_modal_js = """
    () => {
        console.log('[CROP] Trigger fired, checking if crop modal is enabled...');
        
        // Wait for checkbox to be available and check its state
        function checkCropEnabled() {
            // Try multiple selectors to find the checkbox
            let cropCheckbox = document.querySelector('#conv-enable-crop-checkbox input[type="checkbox"]');
            
            if (!cropCheckbox) {
                // Fallback 1: Search by label text (supports both languages)
                const labels = Array.from(document.querySelectorAll('label'));
                const cropLabel = labels.find(l => 
                    l.textContent.includes('启用裁剪界面') || 
                    l.textContent.includes('Enable Crop Interface') ||
                    l.textContent.includes('🖼️')
                );
                if (cropLabel) {
                    cropCheckbox = cropLabel.querySelector('input[type="checkbox"]');
                }
            }
            
            if (!cropCheckbox) {
                // Fallback 2: Search all checkboxes near "裁剪" text
                const allCheckboxes = document.querySelectorAll('input[type="checkbox"]');
                for (let cb of allCheckboxes) {
                    const parent = cb.closest('.wrap') || cb.closest('label') || cb.parentElement;
                    if (parent && (parent.textContent.includes('裁剪') || parent.textContent.includes('Crop'))) {
                        cropCheckbox = cb;
                        break;
                    }
                }
            }
            
            if (!cropCheckbox) {
                console.warn('[CROP] Checkbox not found yet, will retry...');
                return null; // Not found yet
            }
            
            const isCropEnabled = cropCheckbox.checked;
            console.log('[CROP] ✓ Crop checkbox found! Enabled:', isCropEnabled);
            return isCropEnabled;
        }
        
        // Retry mechanism to wait for checkbox to be available
        function waitForCheckboxAndDecide(retries = 10, delay = 300) {
            const enabled = checkCropEnabled();
            
            if (enabled === null && retries > 0) {
                // Checkbox not found yet, retry
                console.log('[CROP] Retrying checkbox check... (' + retries + ' attempts left)');
                setTimeout(() => waitForCheckboxAndDecide(retries - 1, delay), delay);
                return;
            }
            
            if (enabled === false) {
                console.log('[CROP] ✗ Crop modal disabled by user, skipping...');
                return;
            }
            
            // Checkbox is enabled or not found after all retries (default to enabled)
            if (enabled === null) {
                console.warn('[CROP] ⚠ Checkbox not found after retries, defaulting to enabled');
            } else {
                console.log('[CROP] ✓ Crop modal enabled, proceeding...');
            }
            
            // Proceed to open crop modal
            openCropModalIfReady();
        }
        
        function openCropModalIfReady() {
            console.log('[CROP] Checking for openCropModal function:', typeof window.openCropModal);
            const dimElement = document.querySelector('#preprocess-dimensions-data');
            console.log('[CROP] dimElement found:', !!dimElement);
            if (dimElement) {
                const isSvgUpload = dimElement.dataset.isSvg === '1';
                if (isSvgUpload) {
                    console.log('[CROP] SVG upload detected, skipping crop modal.');
                    return;
                }
                const width = parseInt(dimElement.dataset.width) || 0;
                const height = parseInt(dimElement.dataset.height) || 0;
                console.log('[CROP] Dimensions:', width, 'x', height);
                if (width > 0 && height > 0) {
                    const imgContainer = document.querySelector('#conv-image-input');
                    console.log('[CROP] imgContainer found:', !!imgContainer);
                    if (imgContainer) {
                        const img = imgContainer.querySelector('img');
                        console.log('[CROP] img found:', !!img, 'src:', img ? img.src.substring(0, 50) : 'none');
                        if (img && img.src && typeof window.openCropModal === 'function') {
                            console.log('[CROP] Calling openCropModal...');
                            window.openCropModal(img.src, width, height, 0, 0);
                        } else {
                            console.error('[CROP] Cannot open modal - missing requirements');
                        }
                    }
                }
            }
        }
        
        // Start the check with retry mechanism
        waitForCheckboxAndDecide();
    }
    """
    
    components['image_conv_image_label'].upload(
        on_image_upload_process_with_html,
        inputs=[components['image_conv_image_label']],
        outputs=[preprocess_img_width, preprocess_img_height, preprocess_processed_path, preprocess_dimensions_html, components['image_conv_image_label']]
    ).then(
        fn=None,
        inputs=None,
        outputs=None,
        js=open_crop_modal_js
    )
    
    def use_original_image_simple(processed_path, w, h, crop_json):
        """Use original image without cropping"""
        print(f"[DEBUG] use_original_image_simple called: {processed_path}")
        if processed_path is None:
            return None
        try:
            if isinstance(processed_path, str) and processed_path.lower().endswith(".svg"):
                return processed_path
            result_path = ImagePreprocessor.convert_to_png(processed_path)
            return result_path
        except Exception as e:
            print(f"Use original error: {e}")
            return None
    
    use_original_btn.click(
        use_original_image_simple,
        inputs=[preprocess_processed_path, preprocess_img_width, preprocess_img_height, crop_data_json],
        outputs=[components['image_conv_image_label']]
    )
    
    def confirm_crop_image_simple(processed_path, crop_json):
        """Crop image with specified region"""
        print(f"[DEBUG] confirm_crop_image_simple called: {processed_path}, {crop_json}")
        if processed_path is None:
            return None
        try:
            if isinstance(processed_path, str) and processed_path.lower().endswith(".svg"):
                print("[DEBUG] SVG uploaded, skipping raster crop and keeping original path")
                return processed_path
            import json
            data = json.loads(crop_json) if crop_json else {"x": 0, "y": 0, "w": 100, "h": 100}
            x = int(data.get("x", 0))
            y = int(data.get("y", 0))
            w = int(data.get("w", 100))
            h = int(data.get("h", 100))
            
            result_path = ImagePreprocessor.crop_image(processed_path, x, y, w, h)
            return result_path
        except Exception as e:
            print(f"Crop error: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    confirm_crop_btn.click(
        confirm_crop_image_simple,
        inputs=[preprocess_processed_path, crop_data_json],
        outputs=[components['image_conv_image_label']]
    )
    
    # ========== Auto Color Detection Button ==========
    # 用于触发 toast 的隐藏 HTML 组件
    color_toast_trigger = gr.HTML(value="", visible=True, elem_classes=["hidden-crop-component"])
    
    # JavaScript to show color recommendation toast
    show_toast_js = """
    () => {
        setTimeout(() => {
            const trigger = document.querySelector('#color-rec-trigger');
            if (trigger) {
                const recommended = parseInt(trigger.dataset.recommended) || 0;
                const maxSafe = parseInt(trigger.dataset.maxsafe) || 0;
                if (recommended > 0 && typeof window.showColorRecommendationToast === 'function') {
                    const lang = document.documentElement.lang || 'zh';
                    let msg;
                    if (lang === 'en') {
                        msg = '💡 Color detail set to <b>' + recommended + '</b> (max safe: ' + maxSafe + ')';
                    } else {
                        msg = '💡 色彩细节已设置为 <b>' + recommended + '</b>（最大安全值: ' + maxSafe + '）';
                    }
                    window.showColorRecommendationToast(msg);
                }
                trigger.remove();
            }
        }, 100);
    }
    """
    
    def auto_detect_colors(image_path, target_width_mm):
        """自动检测推荐的色彩细节值"""
        if image_path is None:
            return gr.update(), ""
        try:
            import time
            print(f"[AutoColor] 开始分析: {image_path}, 目标宽度: {target_width_mm}mm")
            color_analysis = ImagePreprocessor.analyze_recommended_colors(image_path, target_width_mm)
            recommended = color_analysis.get('recommended', 24)
            max_safe = color_analysis.get('max_safe', 32)
            print(f"[AutoColor] 分析完成: recommended={recommended}, max_safe={max_safe}")
            # 添加时间戳确保每次返回值不同，触发 .then() 中的 JavaScript
            timestamp = int(time.time() * 1000)
            toast_html = f'<div id="color-rec-trigger" data-recommended="{recommended}" data-maxsafe="{max_safe}" data-ts="{timestamp}" style="display:none;"></div>'
            return gr.update(value=recommended), toast_html
        except Exception as e:
            print(f"[AutoColor] 分析失败: {e}")
            import traceback
            traceback.print_exc()
            return gr.update(), ""
    
    components['btn_conv_auto_color'].click(
        auto_detect_colors,
        inputs=[components['image_conv_image_label'], components['slider_conv_width']],
        outputs=[components['slider_conv_quantize_colors'], color_toast_trigger]
    ).then(
        fn=None,
        inputs=None,
        outputs=None,
        js=show_toast_js
    )
    # ========== END Image Crop Extension Events ==========

    components['dropdown_conv_lut_dropdown'].change(
            on_lut_select,
            inputs=[components['dropdown_conv_lut_dropdown']],
            outputs=[conv_lut_path, components['md_conv_lut_status']]
    ).then(
            fn=save_last_lut_setting,
            inputs=[components['dropdown_conv_lut_dropdown']],
            outputs=None
    ).then(
            fn=_update_lut_grid,
            inputs=[conv_lut_path, lang_state, conv_palette_mode],
            outputs=[conv_lut_grid_view]
    ).then(
            fn=_detect_and_enforce_structure,
            inputs=[conv_lut_path, components['checkbox_conv_coating_enable']],
            outputs=[components['radio_conv_color_mode'], components['radio_conv_structure'], components['checkbox_conv_relief_mode']]
    )


    


    conv_lut_upload.upload(
            on_lut_upload_save,
            inputs=[conv_lut_upload],
            outputs=[components['dropdown_conv_lut_dropdown'], components['md_conv_lut_status']]
    ).then(
            fn=lambda: gr.update(),
            outputs=[components['dropdown_conv_lut_dropdown']]
    ).then(
            fn=lambda lut_file, enable_coating: _detect_and_enforce_structure(
                lut_file.name if lut_file else None, enable_coating
            ),
            inputs=[conv_lut_upload, components['checkbox_conv_coating_enable']],
            outputs=[components['radio_conv_color_mode'], components['radio_conv_structure'], components['checkbox_conv_relief_mode']]
    )
    
    components['image_conv_image_label'].change(
            fn=init_dims,
            inputs=[components['image_conv_image_label']],
            outputs=[components['slider_conv_width'], conv_target_height_mm]
    ).then(
            # 自动检测图像类型并切换建模模式
            # 使用 preprocess_processed_path 而非 image_conv_image_label，
            # 因为 SVG 上传后 image_conv_image_label 存的是 PNG 缩略图，
            # 只有 preprocess_processed_path 保留原始 SVG 路径。
            fn=detect_image_type,
            inputs=[preprocess_processed_path],
            outputs=[components['radio_conv_modeling_mode']]
    ).then(
            # 清空已生成的 3MF 文件，强制下次点击切片按钮时重新生成
            fn=lambda: None,
            inputs=None,
            outputs=[components['file_conv_download_file']]
    )
    components['slider_conv_width'].input(
            fn=calc_height_from_width,
            inputs=[components['slider_conv_width'], components['image_conv_image_label']],
            outputs=[conv_target_height_mm]
    )
    conv_target_height_mm.input(
            fn=calc_width_from_height,
            inputs=[conv_target_height_mm, components['image_conv_image_label']],
            outputs=[components['slider_conv_width']]
    )
    def generate_preview_cached_with_fit(image_path, lut_path, target_width_mm,
                                         auto_bg, bg_tol, color_mode,
                                         modeling_mode, quantize_colors, enable_cleanup,
                                         is_dark_theme=False, processed_path=None,
                                         hue_weight=0.0):
        # When SVG was uploaded, image_conv_image_label holds a PNG thumbnail while
        # preprocess_processed_path holds the original SVG. Use SVG for the converter.
        if processed_path and isinstance(processed_path, str) and processed_path.lower().endswith('.svg'):
            image_path = processed_path
        display, cache, status = generate_preview_cached(
            image_path, lut_path, target_width_mm,
            auto_bg, bg_tol, color_mode,
            modeling_mode, quantize_colors,
            enable_cleanup=enable_cleanup,
            is_dark=is_dark_theme,
            hue_weight=float(hue_weight) if hue_weight else 0.0
        )
        # Generate realtime 3D preview GLB
        glb_path = generate_realtime_glb(cache) if cache is not None else None
        return _preview_update(display), cache, status, glb_path

    # 建模模式切换：统一处理可用参数提示与禁用逻辑
    def on_modeling_mode_change_controls(mode):
        is_pixel = mode == ModelingMode.PIXEL
        is_vector = mode == ModelingMode.VECTOR

        # Cleanup: Pixel 模式禁用，其它模式可用
        if is_pixel:
            cleanup_update = gr.update(
                interactive=False,
                value=False,
                info="像素模式下不支持孤立像素清理 | Not available in Pixel Art mode",
            )
        else:
            cleanup_update = gr.update(
                interactive=True,
                info="清理 LUT 匹配后的孤立像素，提升打印成功率",
            )

        # Outline / Cloisonné: 当前仅在 Raster 路径生效，Vector 模式禁用并提示
        if is_vector:
            outline_checkbox_update = gr.update(
                interactive=False,
                value=False,
                info="Vector(SVG) 模式暂不支持描边；该选项仅在 Raster 路径生效",
            )
            outline_width_update = gr.update(
                interactive=False,
                info="Vector(SVG) 模式下已禁用",
            )
            cloisonne_checkbox_update = gr.update(
                interactive=False,
                value=False,
                info="Vector(SVG) 模式暂不支持掐丝珐琅；该选项仅在 Raster 路径生效",
            )
            wire_width_update = gr.update(
                interactive=False,
                info="Vector(SVG) 模式下已禁用",
            )
            wire_height_update = gr.update(
                interactive=False,
                info="Vector(SVG) 模式下已禁用",
            )
        else:
            outline_checkbox_update = gr.update(
                interactive=True,
                info="描边仅在生成阶段生效",
            )
            outline_width_update = gr.update(
                interactive=True,
                info=None,
            )
            cloisonne_checkbox_update = gr.update(
                interactive=True,
                info="掐丝珐琅仅在生成阶段生效（与 2.5D 浮雕互斥）",
            )
            wire_width_update = gr.update(
                interactive=True,
                info=None,
            )
            wire_height_update = gr.update(
                interactive=True,
                info=None,
            )

        return (
            cleanup_update,
            outline_checkbox_update,
            outline_width_update,
            cloisonne_checkbox_update,
            wire_width_update,
            wire_height_update,
        )

    components['radio_conv_modeling_mode'].change(
        on_modeling_mode_change_controls,
        inputs=[components['radio_conv_modeling_mode']],
        outputs=[
            components['checkbox_conv_cleanup'],
            components['checkbox_conv_outline_enable'],
            components['slider_conv_outline_width'],
            components['checkbox_conv_cloisonne_enable'],
            components['slider_conv_wire_width'],
            components['slider_conv_wire_height'],
        ]
    ).then(
        fn=save_modeling_mode,
        inputs=[components['radio_conv_modeling_mode']],
        outputs=None
    )

    # Save color mode when changed
    components['radio_conv_color_mode'].change(
        fn=save_color_mode,
        inputs=[components['radio_conv_color_mode']],
        outputs=None
    )

    def _on_color_mode_update_structure(color_mode, enable_coating):
        """5C: 2.5D off always; single-sided enforced unless COATING is on."""
        if color_mode and "5-Color Extended" in color_mode:
            return _structure_relief_for_5color_extended(enable_coating)
        return gr.update(interactive=True), gr.update(interactive=True)

    def _on_coating_change_for_5c(enable_coating, color_mode):
        if color_mode and "5-Color Extended" in color_mode:
            return _structure_relief_for_5color_extended(enable_coating)
        return gr.update(), gr.update()

    components['radio_conv_color_mode'].change(
        fn=_on_color_mode_update_structure,
        inputs=[components['radio_conv_color_mode'], components['checkbox_conv_coating_enable']],
        outputs=[components['radio_conv_structure'], components['checkbox_conv_relief_mode']],
    )

    components['checkbox_conv_coating_enable'].change(
        fn=_on_coating_change_for_5c,
        inputs=[components['checkbox_conv_coating_enable'], components['radio_conv_color_mode']],
        outputs=[components['radio_conv_structure'], components['checkbox_conv_relief_mode']],
    )

    preview_event = components['btn_conv_preview_btn'].click(
            generate_preview_cached_with_fit,
            inputs=[
                components['image_conv_image_label'],
                conv_lut_path,
                components['slider_conv_width'],
                components['checkbox_conv_auto_bg'],
                components['slider_conv_tolerance'],
                components['radio_conv_color_mode'],
                components['radio_conv_modeling_mode'],
                components['slider_conv_quantize_colors'],
                components['checkbox_conv_cleanup'],
                theme_state,
                preprocess_processed_path,
                components['slider_conv_hue_weight'],
            ],
            outputs=[conv_preview, conv_preview_cache, components['textbox_conv_status'], conv_3d_preview]
    ).then(
            on_preview_generated_update_palette,
            inputs=[conv_preview_cache, lang_state],
            outputs=[conv_palette_html, conv_selected_color]
    ).then(
            fn=lambda: (None, None),
            inputs=[],
            outputs=[conv_selected_user_row_id, conv_selected_auto_row_id]
    )

    # Hidden textbox receives highlight color from JavaScript click (triggers preview highlight)
    # Use button click instead of textbox change for more reliable triggering
    def on_highlight_color_change_with_fit(highlight_hex, cache, loop_pos, add_loop,
                                           loop_width, loop_length, loop_hole, loop_angle):
        display, status = on_highlight_color_change(
            highlight_hex, cache, loop_pos, add_loop,
            loop_width, loop_length, loop_hole, loop_angle
        )
        return _preview_update(display), status

    conv_highlight_trigger_btn.click(
            on_highlight_color_change_with_fit,
            inputs=[
                conv_highlight_color_hidden, conv_preview_cache, conv_loop_pos,
                components['checkbox_conv_loop_enable'],
                components['slider_conv_loop_width'], components['slider_conv_loop_length'],
                components['slider_conv_loop_hole'], components['slider_conv_loop_angle']
            ],
            outputs=[conv_preview, components['textbox_conv_status']]
    )

    # [新增] 处理 LUT 色块点击事件 (JS -> Hidden Textbox -> Python)
    def on_lut_color_click(hex_color):
        return hex_color, hex_color

    def build_palette_html_with_selection(cache, replacement_regions,
                                          selected_user_row_id, selected_auto_row_id,
                                          lang_state_val):
        from ui.palette_extension import generate_palette_html

        if cache is None:
            placeholder = I18n.get('conv_palette_replacements_placeholder', lang_state_val)
            return f"<p style='color:#888;'>{placeholder}</p>"

        palette = cache.get('color_palette', [])
        auto_pairs = []
        q_img = cache.get('quantized_image')
        m_img = cache.get('matched_rgb')
        mask = cache.get('mask_solid')
        if q_img is not None and m_img is not None and mask is not None:
            h, w = m_img.shape[:2]
            for y in range(h):
                for x in range(w):
                    if not mask[y, x]:
                        continue
                    qh = f"#{int(q_img[y,x,0]):02x}{int(q_img[y,x,1]):02x}{int(q_img[y,x,2]):02x}"
                    mh = f"#{int(m_img[y,x,0]):02x}{int(m_img[y,x,1]):02x}{int(m_img[y,x,2]):02x}"
                    auto_pairs.append({"quantized_hex": qh, "matched_hex": mh})

        return generate_palette_html(
            palette,
            replacements={},
            selected_color=None,
            lang=lang_state_val,
            replacement_regions=replacement_regions or [],
            auto_pairs=auto_pairs,
            selected_user_row_id=selected_user_row_id,
            selected_auto_row_id=selected_auto_row_id,
        )

    def on_palette_row_select(row_id, selected_user_row_id, selected_auto_row_id, cache):
        row_id = (row_id or '').strip()

        new_cache = cache.copy() if isinstance(cache, dict) else cache
        if isinstance(new_cache, dict):
            new_cache['selection_scope'] = 'global'
            new_cache['selected_region_mask'] = None

        if not row_id:
            return selected_user_row_id, selected_auto_row_id, new_cache
        if row_id.startswith('user::'):
            return row_id, None, new_cache
        if row_id.startswith('auto::'):
            return None, row_id, new_cache
        return selected_user_row_id, selected_auto_row_id, new_cache

    conv_lut_color_trigger_btn.click(
            fn=on_lut_color_click,
            inputs=[conv_lut_color_selected_hidden],
            outputs=[conv_replacement_color_state, conv_replacement_display]
    )

    conv_palette_row_select_trigger_btn.click(
            fn=on_palette_row_select,
            inputs=[conv_palette_row_select_hidden, conv_selected_user_row_id, conv_selected_auto_row_id, conv_preview_cache],
            outputs=[conv_selected_user_row_id, conv_selected_auto_row_id, conv_preview_cache]
    ).then(
            fn=build_palette_html_with_selection,
            inputs=[
                conv_preview_cache, conv_replacement_regions,
                conv_selected_user_row_id, conv_selected_auto_row_id, lang_state
            ],
            outputs=[conv_palette_html]
    )

    def on_delete_selected_user_replacement_regions_only(
        cache, replacement_regions, replacement_history,
        selected_user_row_id,
        loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle,
        lang_state_val
    ):
        display, updated_cache, palette_html, new_regions, new_history, status, selected_user = on_delete_selected_user_replacement(
            cache, replacement_regions, replacement_history,
            selected_user_row_id,
            loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle,
            lang_state_val
        )
        return display, updated_cache, palette_html, new_regions, new_history, status, selected_user

    conv_palette_delete_trigger_btn.click(
            fn=on_delete_selected_user_replacement_regions_only,
            inputs=[
                conv_preview_cache, conv_replacement_regions, conv_replacement_history,
                conv_selected_user_row_id,
                conv_loop_pos, components['checkbox_conv_loop_enable'],
                components['slider_conv_loop_width'], components['slider_conv_loop_length'],
                components['slider_conv_loop_hole'], components['slider_conv_loop_angle'],
                lang_state
            ],
            outputs=[
                conv_preview, conv_preview_cache, conv_palette_html,
                conv_replacement_regions, conv_replacement_history,
                components['textbox_conv_status'], conv_selected_user_row_id
            ]
    ).then(
            fn=lambda: None,
            inputs=[],
            outputs=[conv_selected_auto_row_id]
    )

    # 以色找色: ColorPicker nearest match via KDTree
    def on_color_picker_find_nearest(picker_hex, lut_path):
        """Find the nearest LUT color to the picked color using KDTree."""
        if not picker_hex or not lut_path:
            return gr.update(), gr.update()
        try:
            from core.converter import extract_lut_available_colors
            from core.image_processing import LuminaImageProcessor
            import numpy as np
            from scipy.spatial import KDTree

            colors = extract_lut_available_colors(lut_path)
            if not colors:
                return gr.update(), gr.update()

            # Build KDTree from LUT colors
            rgb_array = np.array([c['color'] for c in colors], dtype=np.float64)
            tree = KDTree(rgb_array)

            # Parse picker hex
            h = picker_hex.lstrip('#')
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

            dist, idx = tree.query([[r, g, b]])
            nearest = colors[idx[0]]
            nearest_hex = nearest['hex']

            print(f"[COLOR_PICKER] {picker_hex} → nearest LUT: {nearest_hex} (dist={dist[0]:.1f})")

            # Return JS call to scroll to the matched swatch + update replacement display
            gr.Info(f"✅ 最接近: {nearest_hex} (距离: {dist[0]:.1f})")
            return nearest_hex, nearest_hex
        except Exception as e:
            print(f"[COLOR_PICKER] Error: {e}")
            return gr.update(), gr.update()

    components['btn_conv_picker_search'].click(
        fn=on_color_picker_find_nearest,
        inputs=[components['color_conv_picker_search'], conv_lut_path],
        outputs=[conv_replacement_color_state, conv_replacement_display]
    ).then(
        fn=None,
        inputs=[conv_replacement_color_state],
        outputs=[],
        js="(hex) => { if (hex) { setTimeout(() => window.lutScrollToColor && window.lutScrollToColor(hex), 200); } }"
    )
    
    # Color replacement: Apply replacement
    def on_apply_color_replacement_with_fit(cache, selected_color, replacement_color,
                                            replacement_regions, replacement_history,
                                            loop_pos, add_loop, loop_width, loop_length,
                                            loop_hole, loop_angle, lang_state_val):
        display, updated_cache, palette_html, new_regions, new_history, status = on_apply_color_replacement(
            cache, selected_color, replacement_color,
            replacement_regions, replacement_history,
            loop_pos, add_loop, loop_width, loop_length,
            loop_hole, loop_angle, lang_state_val
        )
        return _preview_update(display), updated_cache, palette_html, new_regions, new_history, status

    conv_apply_replacement.click(
            on_apply_color_replacement_with_fit,
            inputs=[
                conv_preview_cache, conv_selected_color, conv_replacement_color_state,
                conv_replacement_regions, conv_replacement_history, conv_loop_pos, components['checkbox_conv_loop_enable'],
                components['slider_conv_loop_width'], components['slider_conv_loop_length'],
                components['slider_conv_loop_hole'], components['slider_conv_loop_angle'],
                lang_state
            ],
            outputs=[conv_preview, conv_preview_cache, conv_palette_html, conv_replacement_regions, conv_replacement_history, components['textbox_conv_status']]
    ).then(
            fn=lambda: (None, None),
            inputs=[],
            outputs=[conv_selected_user_row_id, conv_selected_auto_row_id]
    )

    
    # Color replacement: Undo last replacement
    def on_undo_color_replacement_with_fit(cache, replacement_regions, replacement_history,
                                           loop_pos, add_loop, loop_width, loop_length,
                                           loop_hole, loop_angle, lang_state_val):
        display, updated_cache, palette_html, new_regions, new_history, status = on_undo_color_replacement(
            cache, replacement_regions, replacement_history,
            loop_pos, add_loop, loop_width, loop_length,
            loop_hole, loop_angle, lang_state_val
        )
        return _preview_update(display), updated_cache, palette_html, new_regions, new_history, status

    conv_undo_replacement.click(
            on_undo_color_replacement_with_fit,
            inputs=[
                conv_preview_cache, conv_replacement_regions, conv_replacement_history,
                conv_loop_pos, components['checkbox_conv_loop_enable'],
                components['slider_conv_loop_width'], components['slider_conv_loop_length'],
                components['slider_conv_loop_hole'], components['slider_conv_loop_angle'],
                lang_state
            ],
            outputs=[conv_preview, conv_preview_cache, conv_palette_html, conv_replacement_regions, conv_replacement_history, components['textbox_conv_status']]
    ).then(
            fn=lambda: (None, None),
            inputs=[],
            outputs=[conv_selected_user_row_id, conv_selected_auto_row_id]
    )

    
    # Color replacement: Clear all replacements
    def on_clear_color_replacements_with_fit(cache, replacement_regions, replacement_history,
                                             loop_pos, add_loop, loop_width, loop_length,
                                             loop_hole, loop_angle, lang_state_val):
        display, updated_cache, palette_html, new_regions, new_history, status = on_clear_color_replacements(
            cache, replacement_regions, replacement_history,
            loop_pos, add_loop, loop_width, loop_length,
            loop_hole, loop_angle, lang_state_val
        )
        return _preview_update(display), updated_cache, palette_html, new_regions, new_history, status

    conv_clear_replacements.click(
            on_clear_color_replacements_with_fit,
            inputs=[
                conv_preview_cache, conv_replacement_regions, conv_replacement_history,
                conv_loop_pos, components['checkbox_conv_loop_enable'],
                components['slider_conv_loop_width'], components['slider_conv_loop_length'],
                components['slider_conv_loop_hole'], components['slider_conv_loop_angle'],
                lang_state
            ],
            outputs=[conv_preview, conv_preview_cache, conv_palette_html, conv_replacement_regions, conv_replacement_history, components['textbox_conv_status']]
    )


    # ========== Free Color (自由色) Event Handlers ==========
    def _render_free_color_html(free_set):
        if not free_set:
            return ""
        parts = ["<div style='display:flex; flex-wrap:wrap; gap:6px; padding:4px; align-items:center;'>",
                 "<span style='font-size:11px; color:#666;'>🎯 自由色:</span>"]
        for hex_c in sorted(free_set):
            parts.append(
                f"<div style='width:24px;height:24px;background:{hex_c};border:2px solid #ff6b6b;"
                f"border-radius:4px;' title='{hex_c}'></div>"
            )
        parts.append("</div>")
        return "".join(parts)

    def on_mark_free_color(selected_color, free_set):
        if not selected_color:
            return free_set, gr.update(), "[ERROR] 请先点击预览图选择一个颜色"
        new_set = set(free_set) if free_set else set()
        hex_c = selected_color.lower()
        if hex_c in new_set:
            new_set.discard(hex_c)
            msg = f"↩️ 已取消自由色: {hex_c}"
        else:
            new_set.add(hex_c)
            msg = f"🎯 已标记为自由色: {hex_c} (生成时将作为独立对象)"
        return new_set, _render_free_color_html(new_set), msg

    def on_clear_free_colors(free_set):
        return set(), "", "[OK] 已清除所有自由色标记"

    conv_free_color_btn.click(
        on_mark_free_color,
        inputs=[conv_selected_color, conv_free_color_set],
        outputs=[conv_free_color_set, conv_free_color_html, components['textbox_conv_status']]
    )
    conv_free_color_clear_btn.click(
        on_clear_free_colors,
        inputs=[conv_free_color_set],
        outputs=[conv_free_color_set, conv_free_color_html, components['textbox_conv_status']]
    )
    # ========== END Free Color ==========

    # ========== Color Merging Event Handlers ==========
    
    # Preview merge effect
    def on_merge_preview_with_fit(cache, merge_enable, merge_threshold, merge_max_distance,
                                  loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle,
                                  lang_state_val):
        display, updated_cache, palette_html, merge_map, merge_stats, status = on_merge_preview(
            cache, merge_enable, merge_threshold, merge_max_distance,
            loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle,
            lang_state_val
        )
        return _preview_update(display), updated_cache, palette_html, merge_map, merge_stats, status

    components['btn_conv_merge_preview'].click(
        on_merge_preview_with_fit,
        inputs=[
            conv_preview_cache,
            components['checkbox_conv_merge_enable'],
            components['slider_conv_merge_threshold'],
            components['slider_conv_merge_max_distance'],
            conv_loop_pos,
            components['checkbox_conv_loop_enable'],
            components['slider_conv_loop_width'],
            components['slider_conv_loop_length'],
            components['slider_conv_loop_hole'],
            components['slider_conv_loop_angle'],
            lang_state
        ],
        outputs=[
            conv_preview,
            conv_preview_cache,
            conv_palette_html,
            conv_merge_map,
            conv_merge_stats,
            components['md_conv_merge_status']
        ]
    )

    # Apply merge
    def on_merge_apply_with_fit(cache, merge_map, merge_stats,
                                loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle,
                                lang_state_val):
        display, updated_cache, palette_html, status = on_merge_apply(
            cache, merge_map, merge_stats,
            loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle,
            lang_state_val
        )
        return _preview_update(display), updated_cache, palette_html, status

    components['btn_conv_merge_apply'].click(
        on_merge_apply_with_fit,
        inputs=[
            conv_preview_cache,
            conv_merge_map,
            conv_merge_stats,
            conv_loop_pos,
            components['checkbox_conv_loop_enable'],
            components['slider_conv_loop_width'],
            components['slider_conv_loop_length'],
            components['slider_conv_loop_hole'],
            components['slider_conv_loop_angle'],
            lang_state
        ],
        outputs=[
            conv_preview,
            conv_preview_cache,
            conv_palette_html,
            components['md_conv_merge_status']
        ]
    )

    # Revert merge
    def on_merge_revert_with_fit(cache, loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle,
                                 lang_state_val):
        display, updated_cache, palette_html, empty_map, empty_stats, status = on_merge_revert(
            cache, loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle,
            lang_state_val
        )
        return _preview_update(display), updated_cache, palette_html, empty_map, empty_stats, status

    components['btn_conv_merge_revert'].click(
        on_merge_revert_with_fit,
        inputs=[
            conv_preview_cache,
            conv_loop_pos,
            components['checkbox_conv_loop_enable'],
            components['slider_conv_loop_width'],
            components['slider_conv_loop_length'],
            components['slider_conv_loop_hole'],
            components['slider_conv_loop_angle'],
            lang_state
        ],
        outputs=[
            conv_preview,
            conv_preview_cache,
            conv_palette_html,
            conv_merge_map,
            conv_merge_stats,
            components['md_conv_merge_status']
        ]
    )
    
    # ========== END Color Merging ==========

    # [修改] 预览图点击事件同步到 UI
    def on_preview_click_sync_ui(cache, evt: gr.SelectData, lut_path):
        from ui.palette_extension import generate_dual_recommendations_html, build_selected_dual_color_html

        img, display_text, hex_val, msg = on_preview_click_select_color(cache, evt)
        if hex_val is None or not isinstance(hex_val, str):
            return _preview_update(img), gr.update(), gr.update(), gr.update(), msg

        rec_html = ""
        try:
            if lut_path and cache is not None:
                q_hex = cache.get('selected_quantized_hex')
                m_hex = cache.get('selected_matched_hex')
                if q_hex and m_hex:
                    lut_colors = get_lut_color_choices(lut_path)
                    rec = _build_dual_recommendations(
                        tuple(int(q_hex[i:i+2], 16) for i in (1, 3, 5)),
                        tuple(int(m_hex[i:i+2], 16) for i in (1, 3, 5)),
                        lut_colors,
                        top_k=10
                    )
                    rec_html = generate_dual_recommendations_html(rec, lang=lang)
        except Exception as e:
            print(f"[DUAL_RECOMMEND] Failed: {e}")

        display_hex, state_hex = _resolve_click_selection_hexes(cache, hex_val)
        selected_html = build_selected_dual_color_html(state_hex, display_hex, lang=lang)
        return _preview_update(img), selected_html, state_hex, rec_html, msg

    # Relief mode: update slider when color is selected
    def on_color_selected_for_relief(hex_color, enable_relief, height_map, base_thickness, cache):
        """When user clicks a color in preview, update relief slider.
        用户点击预览图选色后，更新浮雕高度 slider。

        Args:
            hex_color (str | None): Quantized hex from click selection. (点击选中的量化色 hex)
            enable_relief (bool): Whether relief mode is enabled. (浮雕模式是否开启)
            height_map (dict): Color-to-height mapping keyed by matched hex. (matched hex 为 key 的颜色高度映射)
            base_thickness (float): Base thickness fallback in mm. (底板厚度回退值，单位 mm)
            cache (dict | None): Preview cache containing selected_matched_hex. (预览缓存，包含 selected_matched_hex)

        Returns:
            tuple: (slider update, relief_selected_color, selected_color). (slider 更新, 浮雕选中色, 选中色)
        """
        if not enable_relief or not hex_color:
            return gr.update(visible=False), hex_color, hex_color

        # Use matched hex (same key space as color_height_map) for lookup
        matched_hex = (cache or {}).get('selected_matched_hex', hex_color) if cache else hex_color
        current_height = height_map.get(matched_hex, base_thickness)

        # Store matched_hex in conv_relief_selected_color so slider edits
        # write back with the correct key
        return gr.update(visible=True, value=current_height), matched_hex, hex_color

    conv_preview.select(
            fn=on_preview_click_sync_ui,
            inputs=[conv_preview_cache, conv_lut_path],
            outputs=[
                conv_preview,
                conv_selected_display,
                conv_selected_color,
                conv_dual_recommend_html,
                components['textbox_conv_status']
            ]
    ).then(
        # Also update relief slider when clicking preview image
        fn=on_color_selected_for_relief,
        inputs=[
            conv_selected_color,
            components['checkbox_conv_relief_mode'],
            conv_color_height_map,
            components['slider_conv_thickness'],
            conv_preview_cache
        ],
        outputs=[
            components['slider_conv_relief_height'],
            conv_relief_selected_color,
            conv_selected_color
        ]
    )
    def update_preview_with_loop_with_fit(cache, loop_pos, add_loop,
                                          loop_width, loop_length, loop_hole, loop_angle):
        display = update_preview_with_loop(
            cache, loop_pos, add_loop,
            loop_width, loop_length, loop_hole, loop_angle
        )
        return _preview_update(display)

    components['btn_conv_loop_remove'].click(
            on_remove_loop,
            outputs=[conv_loop_pos, components['checkbox_conv_loop_enable'], 
                    components['slider_conv_loop_angle'], components['textbox_conv_loop_info']]
    ).then(
            update_preview_with_loop_with_fit,
            inputs=[
                conv_preview_cache, conv_loop_pos, components['checkbox_conv_loop_enable'],
                components['slider_conv_loop_width'], components['slider_conv_loop_length'],
                components['slider_conv_loop_hole'], components['slider_conv_loop_angle']
            ],
            outputs=[conv_preview]
    )
    loop_params = [
            components['slider_conv_loop_width'],
            components['slider_conv_loop_length'],
            components['slider_conv_loop_hole'],
            components['slider_conv_loop_angle']
    ]
    for param in loop_params:
            param.change(
                update_preview_with_loop_with_fit,
                inputs=[
                    conv_preview_cache, conv_loop_pos, components['checkbox_conv_loop_enable'],
                    components['slider_conv_loop_width'], components['slider_conv_loop_length'],
                    components['slider_conv_loop_hole'], components['slider_conv_loop_angle']
                ],
                outputs=[conv_preview]
            )
    # ========== Relief / Cloisonné Mutual Exclusion ==========
    def on_relief_mode_toggle(enable_relief, selected_color, height_map, base_thickness):
        """Toggle relief mode visibility and reset state; auto-disable cloisonné.
        
        Returns updates for:
        - slider_conv_relief_height
        - accordion_conv_auto_height
        - slider_conv_auto_height_max
        - row_conv_heightmap
        - image_conv_heightmap_preview
        - conv_color_height_map
        - conv_relief_selected_color
        - radio_conv_auto_height_mode (reset to default)
        - checkbox_conv_cloisonne_enable (auto-disable)
        - image_conv_heightmap (clear on disable)
        """
        if not enable_relief:
            # 关闭浮雕模式 - 隐藏所有浮雕相关控件，清除 heightmap 残留值
            return (
                gr.update(visible=False),   # slider_conv_relief_height
                gr.update(visible=False),   # accordion_conv_auto_height
                gr.update(visible=False),   # slider_conv_auto_height_max
                gr.update(visible=False),   # row_conv_heightmap
                gr.update(visible=False),   # image_conv_heightmap_preview
                {},                         # conv_color_height_map
                None,                       # conv_relief_selected_color
                gr.update(value="深色凸起"), # radio_conv_auto_height_mode reset
                gr.update(),                # checkbox_conv_cloisonne_enable (no change)
                gr.update(value=None),      # image_conv_heightmap（清除）
            )
        else:
            # 开启浮雕模式 - 默认「深色凸起」，隐藏高度图上传区，自动关闭掐丝珐琅
            gr.Info("⚠️ 2.5D浮雕模式与掐丝珐琅模式互斥，已自动关闭掐丝珐琅 | Relief and Cloisonné are mutually exclusive, Cloisonné disabled")
            if selected_color:
                current_height = height_map.get(selected_color, base_thickness)
                return (
                    gr.update(visible=True, value=current_height),  # slider_conv_relief_height
                    gr.update(visible=True),    # accordion_conv_auto_height
                    gr.update(visible=True),    # slider_conv_auto_height_max
                    gr.update(visible=False),   # row_conv_heightmap (hidden for luminance mode)
                    gr.update(visible=False),   # image_conv_heightmap_preview
                    height_map,                 # conv_color_height_map
                    selected_color,             # conv_relief_selected_color
                    gr.update(value="深色凸起"), # radio_conv_auto_height_mode reset
                    gr.update(value=False),     # checkbox_conv_cloisonne_enable (disable)
                    gr.update(),                # image_conv_heightmap（不变）
                )
            else:
                return (
                    gr.update(visible=False),   # slider_conv_relief_height
                    gr.update(visible=True),    # accordion_conv_auto_height
                    gr.update(visible=True),    # slider_conv_auto_height_max
                    gr.update(visible=False),   # row_conv_heightmap (hidden for luminance mode)
                    gr.update(visible=False),   # image_conv_heightmap_preview
                    height_map,                 # conv_color_height_map
                    selected_color,             # conv_relief_selected_color
                    gr.update(value="深色凸起"), # radio_conv_auto_height_mode reset
                    gr.update(value=False),     # checkbox_conv_cloisonne_enable (disable)
                    gr.update(),                # image_conv_heightmap（不变）
                )

    def on_cloisonne_mode_toggle(enable_cloisonne):
        """When cloisonné is enabled, auto-disable relief mode"""
        if enable_cloisonne:
            gr.Info("⚠️ 掐丝珐琅模式与2.5D浮雕模式互斥，已自动关闭浮雕 | Cloisonné and Relief are mutually exclusive, Relief disabled")
            return gr.update(value=False), gr.update(visible=False), gr.update(visible=False)
        return gr.update(), gr.update(), gr.update()

    components['checkbox_conv_relief_mode'].change(
        on_relief_mode_toggle,
        inputs=[
            components['checkbox_conv_relief_mode'],
            conv_relief_selected_color,
            conv_color_height_map,
            components['slider_conv_thickness']
        ],
        outputs=[
            components['slider_conv_relief_height'],
            components['accordion_conv_auto_height'],
            components['slider_conv_auto_height_max'],
            components['row_conv_heightmap'],
            components['image_conv_heightmap_preview'],
            conv_color_height_map,
            conv_relief_selected_color,
            components['radio_conv_auto_height_mode'],
            components['checkbox_conv_cloisonne_enable'],
            components['image_conv_heightmap'],
        ]
    )

    components['checkbox_conv_cloisonne_enable'].change(
        on_cloisonne_mode_toggle,
        inputs=[components['checkbox_conv_cloisonne_enable']],
        outputs=[
            components['checkbox_conv_relief_mode'],
            components['slider_conv_relief_height'],
            components['accordion_conv_auto_height']
        ]
    )

    # ========== Sorting Rule Radio Change Handler ==========
    def on_height_mode_change(mode: str):
        """切换排列规则时，控制高度图上传区和一键生成按钮的显隐，并清除残留值。"""
        if mode == "根据高度图":
            return (
                gr.update(visible=True),    # row_conv_heightmap - 显示高度图上传区
                gr.update(visible=False),   # btn_conv_auto_height_apply - 隐藏一键生成按钮
                gr.update(visible=False),   # image_conv_heightmap_preview
                gr.update(),                # image_conv_heightmap（不变）
            )
        else:
            return (
                gr.update(visible=False),   # row_conv_heightmap - 隐藏高度图上传区
                gr.update(visible=True),    # btn_conv_auto_height_apply - 显示一键生成按钮
                gr.update(visible=False),   # image_conv_heightmap_preview
                gr.update(value=None),      # image_conv_heightmap（清除）
            )
    
    components['radio_conv_auto_height_mode'].change(
        on_height_mode_change,
        inputs=[components['radio_conv_auto_height_mode']],
        outputs=[
            components['row_conv_heightmap'],
            components['btn_conv_auto_height_apply'],
            components['image_conv_heightmap_preview'],
            components['image_conv_heightmap'],
        ]
    )

    # ========== Heightmap Upload/Clear Handlers ==========
    def on_heightmap_upload(heightmap_path):
        """高度图上传回调 - 验证并显示预览。
        For HEIC/HEIF files, converts to PNG and returns the converted path
        back to the component so the browser can render it.
        """
        if not heightmap_path:
            return on_heightmap_clear()

        # Convert HEIC/HEIF to PNG so the browser can display it
        display_update = gr.update()
        if isinstance(heightmap_path, str):
            ext = os.path.splitext(heightmap_path)[1].lower()
            if ext in ('.heic', '.heif'):
                try:
                    converted = ImagePreprocessor.convert_to_png(heightmap_path)
                    heightmap_path = converted
                    display_update = converted
                except Exception as e:
                    print(f"[HEIC] Heightmap conversion failed: {e}")

        result = HeightmapLoader.load_and_validate(heightmap_path)
        
        if result['success']:
            status_parts = ["✅ 高度图加载成功"]
            if result['original_size']:
                w, h = result['original_size']
                status_parts.append(f"尺寸: {w}x{h}")
            for warn in result['warnings']:
                status_parts.append(warn)
            status_msg = " | ".join(status_parts)
            return (
                gr.update(visible=True, value=result['thumbnail']),
                status_msg,
                display_update,
            )
        else:
            return (
                gr.update(visible=False),
                result['error'],
                display_update,
            )
    
    def on_heightmap_clear():
        """高度图移除回调 - 清除预览。"""
        return (
            gr.update(visible=False, value=None),
            "",
            gr.update(),
        )
    
    components['image_conv_heightmap'].change(
        on_heightmap_upload,
        inputs=[components['image_conv_heightmap']],
        outputs=[
            components['image_conv_heightmap_preview'],
            components['textbox_conv_status'],
            components['image_conv_heightmap'],
        ]
    )
    # ========== END Heightmap Upload/Clear Handlers ==========
    
    def on_color_trigger_sync_ui(selected_hex, highlight_hex, cache, lut_path,
                                 replacement_regions, selected_user_row_id, selected_auto_row_id,
                                 loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle,
                                 enable_relief, height_map, base_thickness):
        from ui.palette_extension import generate_dual_recommendations_html, build_selected_dual_color_html

        if not selected_hex:
            return gr.update(), gr.update(), gr.update(), gr.update(), cache, gr.update(), gr.update(), gr.update()

        q_hex = selected_hex.strip().lower()
        m_hex = (highlight_hex or selected_hex).strip().lower()

        new_cache = cache.copy() if isinstance(cache, dict) else {}
        new_cache['selection_scope'] = 'global'
        new_cache['selected_region_mask'] = None
        new_cache['selected_quantized_hex'] = q_hex
        new_cache['selected_matched_hex'] = m_hex

        if (selected_user_row_id or '').startswith('user::') and replacement_regions:
            rows = []
            for item in replacement_regions or []:
                qv = (item.get('quantized') or item.get('source') or '').lower()
                mv = (item.get('matched') or item.get('source') or '').lower()
                rv = (item.get('replacement') or '').lower()
                if not qv or not rv:
                    continue
                rows.append({'quantized': qv, 'matched': mv, 'replacement': rv, 'mask': item.get('mask')})

            indexed = []
            for idx, row in enumerate(rows):
                rr = dict(row)
                rr['row_id'] = f"user::{rr['quantized']}|{rr['matched']}|{rr['replacement']}|{idx}"
                indexed.append(rr)

            hit = next((r for r in indexed if r.get('row_id') == selected_user_row_id), None)
            mask = hit.get('mask') if isinstance(hit, dict) else None
            if mask is not None:
                new_cache['selection_scope'] = 'region'
                new_cache['selected_region_mask'] = mask

        display, _ = on_highlight_color_change(
            m_hex, new_cache, loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle
        )

        rec_html = ""
        try:
            if lut_path and q_hex and m_hex:
                lut_colors = get_lut_color_choices(lut_path)
                rec = _build_dual_recommendations(
                    tuple(int(q_hex[i:i+2], 16) for i in (1, 3, 5)),
                    tuple(int(m_hex[i:i+2], 16) for i in (1, 3, 5)),
                    lut_colors,
                    top_k=10
                )
                rec_html = generate_dual_recommendations_html(rec, lang=lang)
        except Exception as e:
            print(f"[DUAL_RECOMMEND] Failed: {e}")

        display_hex, state_hex = _resolve_click_selection_hexes(new_cache, q_hex)
        selected_html = build_selected_dual_color_html(state_hex, display_hex, lang=lang)
        relief_slider, relief_selected_color, _ = on_color_selected_for_relief(
            state_hex, enable_relief, height_map, base_thickness, new_cache
        )
        return _preview_update(display), selected_html, state_hex, rec_html, new_cache, gr.update(), relief_slider, relief_selected_color

    # Hook into existing color selection event (when user clicks palette swatch or uses color trigger button)
    conv_color_trigger_btn.click(
        fn=on_color_trigger_sync_ui,
        inputs=[
            conv_color_selected_hidden,
            conv_highlight_color_hidden,
            conv_preview_cache,
            conv_lut_path,
            conv_replacement_regions,
            conv_selected_user_row_id,
            conv_selected_auto_row_id,
            conv_loop_pos,
            components['checkbox_conv_loop_enable'],
            components['slider_conv_loop_width'],
            components['slider_conv_loop_length'],
            components['slider_conv_loop_hole'],
            components['slider_conv_loop_angle'],
            components['checkbox_conv_relief_mode'],
            conv_color_height_map,
            components['slider_conv_thickness'],
        ],
        outputs=[
            conv_preview,
            conv_selected_display,
            conv_selected_color,
            conv_dual_recommend_html,
            conv_preview_cache,
            components['textbox_conv_status'],
            components['slider_conv_relief_height'],
            conv_relief_selected_color,
        ]
    )
    
    def on_relief_height_change(new_height, selected_color, height_map):
        """Update height map when slider changes"""
        if selected_color:
            height_map[selected_color] = new_height
            print(f"[Relief] Updated {selected_color} -> {new_height}mm")
        return height_map
    
    components['slider_conv_relief_height'].change(
        on_relief_height_change,
        inputs=[
            components['slider_conv_relief_height'],
            conv_relief_selected_color,
            conv_color_height_map
        ],
        outputs=[conv_color_height_map]
    )
    
    # Auto Height Generator Event Handler
    def on_auto_height_apply(cache, mode, max_relief_height, base_thickness):
        """Generate automatic height mapping based on color luminance using normalization.
        Skip if mode is '根据高度图' (heightmap mode uses uploaded image instead).
        """
        if mode == "根据高度图":
            gr.Info("ℹ️ 当前为高度图模式，请上传高度图后直接点击生成按钮 | Heightmap mode: upload a heightmap and click Generate")
            return gr.update()
        if cache is None:
            gr.Warning("⚠️ 请先生成预览图 | Please generate preview first")
            return {}
        
        # Extract unique colors from the preview cache
        # cache structure: {'preview': img_array, 'matched_rgb': rgb_array, ...}
        if 'matched_rgb' not in cache:
            gr.Warning("⚠️ 预览数据不完整 | Preview data incomplete")
            return {}
        
        matched_rgb = cache['matched_rgb']
        
        # Extract unique colors using mask_solid for background detection
        # instead of hardcoded (0,0,0) skip
        mask_solid: np.ndarray | None = cache.get('mask_solid')
        unique_colors: set[str] = set()
        
        if mask_solid is not None:
            # Vectorized: select only solid (non-background) pixels
            solid_pixels = matched_rgb[mask_solid]  # shape: (N, 3)
            if solid_pixels.size > 0:
                unique_rgb = np.unique(solid_pixels, axis=0)
                for r, g, b in unique_rgb:
                    unique_colors.add(f'#{r:02x}{g:02x}{b:02x}')
        else:
            # Fallback: no mask_solid available, collect all colors (no black skip)
            h, w = matched_rgb.shape[:2]
            flat_pixels = matched_rgb.reshape(-1, 3)
            unique_rgb = np.unique(flat_pixels, axis=0)
            for r, g, b in unique_rgb:
                unique_colors.add(f'#{r:02x}{g:02x}{b:02x}')
        
        if not unique_colors:
            gr.Warning("⚠️ 未找到有效颜色 | No valid colors found")
            return {}
        
        color_list = list(unique_colors)
        
        # Generate height map using the normalized algorithm
        new_height_map = generate_auto_height_map(color_list, mode, base_thickness, max_relief_height)
        
        gr.Info(f"✅ 已根据颜色明度自动生成 {len(new_height_map)} 个颜色的归一化高度！您可以继续点击单个颜色进行微调。")
        
        return new_height_map
    
    components['btn_conv_auto_height_apply'].click(
        on_auto_height_apply,
        inputs=[
            conv_preview_cache,
            components['radio_conv_auto_height_mode'],
            components['slider_conv_auto_height_max'],
            components['slider_conv_thickness']
        ],
        outputs=[conv_color_height_map]
    )
    # ========== END Relief Mode Event Handlers ==========
    
    # Wrapper function for 3MF generation
    def generate_with_auto_preview(batch_files, is_batch, single_image, lut_path, target_width_mm,
                                   spacer_thick, structure_mode, auto_bg, bg_tol, color_mode,
                                   add_loop, loop_width, loop_length, loop_hole, loop_pos,
                                   modeling_mode, quantize_colors, color_replacements,
                                   separate_backing, enable_relief, color_height_map,
                                   heightmap_path, heightmap_max_height,
                                   enable_cleanup, enable_outline, outline_width,
                                   enable_cloisonne, wire_width_mm, wire_height_mm,
                                   free_color_set, enable_coating, coating_height_mm,
                                   radio_height_mode: str,
                                   preview_cache, theme_is_dark, processed_path=None,
                                   hue_weight: float = 0.0,
                                   progress=gr.Progress()):
        """Generate 3MF directly; preview is generated internally by convert_image_to_3d.
        
        Auto-preview pre-run is intentionally removed: it caused a full duplicate
        image-processing pass (4-35s) with no cache reuse, since preview_cache was
        never forwarded into process_batch_generation. Lower-level caches (O-3
        parse+clip, O-4 SVG raster) already prevent redundant work when the user
        runs preview before clicking this button.
        """
        # When SVG was uploaded, image_conv_image_label holds a PNG thumbnail while
        # preprocess_processed_path holds the original SVG. Use SVG for the converter.
        if processed_path and isinstance(processed_path, str) and processed_path.lower().endswith('.svg'):
            single_image = processed_path
        # Resolve UI radio value to backend height_mode parameter
        height_mode = resolve_height_mode(radio_height_mode)

        progress(0.0, desc="开始生成... | Starting...")
        return process_batch_generation(
            batch_files, is_batch, single_image, lut_path, target_width_mm,
            spacer_thick, structure_mode, auto_bg, bg_tol, color_mode,
            add_loop, loop_width, loop_length, loop_hole, loop_pos,
            modeling_mode, quantize_colors, color_replacements,
            separate_backing, enable_relief, color_height_map,
            height_mode,
            heightmap_path, heightmap_max_height,
            enable_cleanup, enable_outline, outline_width,
            enable_cloisonne, wire_width_mm, wire_height_mm,
            free_color_set, enable_coating, coating_height_mm,
            hue_weight=float(hue_weight) if hue_weight else 0.0,
            progress=progress,
        )
    
    generate_event = components['btn_conv_generate_btn'].click(
            fn=generate_with_auto_preview,
            inputs=[
                components['file_conv_batch_input'],
                components['checkbox_conv_batch_mode'],
                components['image_conv_image_label'],
                conv_lut_path,
                components['slider_conv_width'],
                components['slider_conv_thickness'],
                components['radio_conv_structure'],
                components['checkbox_conv_auto_bg'],
                components['slider_conv_tolerance'],
                components['radio_conv_color_mode'],
                components['checkbox_conv_loop_enable'],
                components['slider_conv_loop_width'],
                components['slider_conv_loop_length'],
                components['slider_conv_loop_hole'],
                conv_loop_pos,
                components['radio_conv_modeling_mode'],
                components['slider_conv_quantize_colors'],
                conv_replacement_regions,
                components['checkbox_conv_separate_backing'],
                components['checkbox_conv_relief_mode'],
                conv_color_height_map,
                components['image_conv_heightmap'],
                components['slider_conv_auto_height_max'],
                components['checkbox_conv_cleanup'],
                components['checkbox_conv_outline_enable'],
                components['slider_conv_outline_width'],
                components['checkbox_conv_cloisonne_enable'],
                components['slider_conv_wire_width'],
                components['slider_conv_wire_height'],
                conv_free_color_set,
                components['checkbox_conv_coating_enable'],
                components['slider_conv_coating_height'],
                components['radio_conv_auto_height_mode'],
                conv_preview_cache,
                theme_state,
                preprocess_processed_path,
                components['slider_conv_hue_weight'],
            ],
            outputs=[
                components['file_conv_download_file'],
                conv_3d_preview,
                conv_preview,
                components['textbox_conv_status'],
                components['file_conv_color_recipe']
            ]
    )
    components['conv_event'] = generate_event
    components['btn_conv_stop'].click(
        fn=None,
        inputs=None,
        outputs=None,
        cancels=[generate_event, preview_event]
    )
    components['state_conv_lut_path'] = conv_lut_path

    # ========== Slicer Integration Events ==========
    conv_slicer_dropdown_vis = gr.State(value=False)

    def on_slicer_dropdown_change(slicer_id):
        """Update both buttons' label/color and save preference."""
        _save_user_setting("last_slicer", slicer_id)
        show_file = (slicer_id == "download")
        css_cls = _slicer_css_class(slicer_id)
        for label, sid in _get_slicer_choices(lang):
            if sid == slicer_id:
                return (
                    gr.update(value=label, elem_classes=[css_cls]),
                    gr.update(elem_classes=[css_cls]),
                    gr.update(visible=show_file),
                    gr.update(visible=show_file),
                )
        return (
            gr.update(value="📥 下载 3MF", elem_classes=["slicer-download"]),
            gr.update(elem_classes=["slicer-download"]),
            gr.update(visible=True),
            gr.update(visible=True),
        )

    components['dropdown_conv_slicer'].change(
        fn=on_slicer_dropdown_change,
        inputs=[components['dropdown_conv_slicer']],
        outputs=[
            components['btn_conv_open_slicer'],
            components['btn_conv_slicer_arrow'],
            components['file_conv_download_file'],
            components['file_conv_color_recipe'],
        ]
    )

    # Arrow button toggles dropdown visibility
    def on_slicer_arrow_click(vis):
        """Toggle dropdown visibility."""
        new_vis = not vis
        return gr.update(visible=new_vis), new_vis

    components['btn_conv_slicer_arrow'].click(
        fn=on_slicer_arrow_click,
        inputs=[conv_slicer_dropdown_vis],
        outputs=[components['dropdown_conv_slicer'], conv_slicer_dropdown_vis]
    )

    # ========== Invalidate cached 3MF when any generation parameter changes ==========
    # When user changes image, dimensions, color mode, modeling mode, or any other
    # parameter that affects the output, clear the cached 3MF file so the slicer
    # button will trigger a fresh generation instead of opening the stale model.
    _invalidate_fn = lambda: None  # Returns None to clear file component

    _param_components_change = [
        components['slider_conv_width'],
        components['slider_conv_thickness'],
        components['radio_conv_structure'],
        components['checkbox_conv_auto_bg'],
        components['slider_conv_tolerance'],
        components['radio_conv_color_mode'],
        components['radio_conv_modeling_mode'],
        components['slider_conv_quantize_colors'],
        components['checkbox_conv_loop_enable'],
        components['slider_conv_loop_width'],
        components['slider_conv_loop_length'],
        components['slider_conv_loop_hole'],
        components['checkbox_conv_separate_backing'],
        components['checkbox_conv_relief_mode'],
        components['checkbox_conv_cleanup'],
        components['checkbox_conv_outline_enable'],
        components['slider_conv_outline_width'],
        components['checkbox_conv_cloisonne_enable'],
        components['slider_conv_wire_width'],
        components['slider_conv_wire_height'],
        components['checkbox_conv_coating_enable'],
        components['slider_conv_coating_height'],
        components['slider_conv_auto_height_max'],
        components['radio_conv_auto_height_mode'],
    ]

    for comp in _param_components_change:
        comp.change(
            fn=_invalidate_fn,
            inputs=None,
            outputs=[components['file_conv_download_file']]
        )

    def on_open_slicer_click(file_obj, slicer_id, batch_files, is_batch, single_image, lut_path, 
                            target_width_mm, spacer_thick, structure_mode, auto_bg, bg_tol, color_mode,
                            add_loop, loop_width, loop_length, loop_hole, loop_pos,
                            modeling_mode, quantize_colors, color_replacements,
                            separate_backing, enable_relief, color_height_map,
                            heightmap_path, heightmap_max_height,
                            enable_cleanup, enable_outline, outline_width,
                            enable_cloisonne, wire_width_mm, wire_height_mm,
                            free_color_set, enable_coating, coating_height_mm,
                            radio_height_mode: str,
                            preview_cache, theme_is_dark, processed_path=None,
                            hue_weight: float = 0.0):
        """Open file in slicer with auto-generation if needed."""
        
        # When SVG was uploaded, image_conv_image_label holds a PNG thumbnail while
        # preprocess_processed_path holds the original SVG. Use SVG for the converter.
        if processed_path and isinstance(processed_path, str) and processed_path.lower().endswith('.svg'):
            single_image = processed_path

        # Initialize color_recipe_path to avoid UnboundLocalError
        color_recipe_path = None
        
        # Resolve UI radio value to backend height_mode parameter
        height_mode = resolve_height_mode(radio_height_mode)
        
        # If no file exists, auto-generate the complete workflow
        if file_obj is None:
            print("[AUTO-SLICER] No 3MF file found, starting auto-generation workflow...")
            
            # Step 1: Generate preview if needed
            if preview_cache is None or not preview_cache:
                print("[AUTO-SLICER] Step 1/2: Generating preview...")
                try:
                    preview_img, cache, status, glb = generate_preview_cached_with_fit(
                        single_image, lut_path, target_width_mm, auto_bg, bg_tol,
                        color_mode, modeling_mode, quantize_colors, enable_cleanup, theme_is_dark
                    )
                    preview_cache = cache
                    print(f"[AUTO-SLICER] Preview generated: {status}")
                except Exception as e:
                    print(f"[AUTO-SLICER] Failed to generate preview: {e}")
                    return gr.update(), gr.update(), gr.update(), gr.update(), f"[ERROR] 预览生成失败: {e}"
            
            # Step 2: Generate 3MF model
            print("[AUTO-SLICER] Step 2/2: Generating 3MF model...")
            try:
                file_obj, glb, preview_img, status, color_recipe_path = process_batch_generation(
                    batch_files, is_batch, single_image, lut_path, target_width_mm,
                    spacer_thick, structure_mode, auto_bg, bg_tol, color_mode,
                    add_loop, loop_width, loop_length, loop_hole, loop_pos,
                    modeling_mode, quantize_colors, color_replacements,
                    separate_backing, enable_relief, color_height_map,
                    height_mode,
                    heightmap_path, heightmap_max_height,
                    enable_cleanup, enable_outline, outline_width,
                    enable_cloisonne, wire_width_mm, wire_height_mm,
                    free_color_set, enable_coating, coating_height_mm,
                    hue_weight=float(hue_weight) if hue_weight else 0.0,
                )
                print(f"[AUTO-SLICER] 3MF generated: {status}")
            except Exception as e:
                print(f"[AUTO-SLICER] Failed to generate 3MF: {e}")
                return gr.update(), gr.update(), gr.update(), gr.update(), f"[ERROR] 3MF生成失败: {e}"
        
        # Now open in slicer or download
        if slicer_id == "download":
            # Make file component visible so user can download
            if file_obj is not None:
                return file_obj, gr.update(visible=True), color_recipe_path, gr.update(visible=True), "📥 请点击下方文件下载"
            return None, gr.update(), gr.update(), gr.update(), "[ERROR] 没有可下载的文件"
        
        # Get actual file path from Gradio File object
        actual_path = None
        if file_obj is not None:
            if hasattr(file_obj, 'name'):
                actual_path = file_obj.name
            elif isinstance(file_obj, str):
                actual_path = file_obj
        
        if not actual_path:
            return None, gr.update(), gr.update(), gr.update(), "[ERROR] 生成失败，无法打开"
        
        status = open_in_slicer(actual_path, slicer_id)
        return file_obj, gr.update(), color_recipe_path, gr.update(), status

    components['btn_conv_open_slicer'].click(
        fn=on_open_slicer_click,
        inputs=[
            components['file_conv_download_file'], 
            components['dropdown_conv_slicer'],
            # All generation parameters
            components['file_conv_batch_input'],
            components['checkbox_conv_batch_mode'],
            components['image_conv_image_label'],
            conv_lut_path,
            components['slider_conv_width'],
            components['slider_conv_thickness'],
            components['radio_conv_structure'],
            components['checkbox_conv_auto_bg'],
            components['slider_conv_tolerance'],
            components['radio_conv_color_mode'],
            components['checkbox_conv_loop_enable'],
            components['slider_conv_loop_width'],
            components['slider_conv_loop_length'],
            components['slider_conv_loop_hole'],
            conv_loop_pos,
            components['radio_conv_modeling_mode'],
            components['slider_conv_quantize_colors'],
            conv_replacement_regions,
            components['checkbox_conv_separate_backing'],
            components['checkbox_conv_relief_mode'],
            conv_color_height_map,
            components['image_conv_heightmap'],
            components['slider_conv_auto_height_max'],
            components['checkbox_conv_cleanup'],
            components['checkbox_conv_outline_enable'],
            components['slider_conv_outline_width'],
            components['checkbox_conv_cloisonne_enable'],
            components['slider_conv_wire_width'],
            components['slider_conv_wire_height'],
            conv_free_color_set,
            components['checkbox_conv_coating_enable'],
            components['slider_conv_coating_height'],
            components['radio_conv_auto_height_mode'],
            conv_preview_cache,
            theme_state,
            preprocess_processed_path,
            components['slider_conv_hue_weight'],
        ],
        outputs=[
            components['file_conv_download_file'],
            components['file_conv_download_file'],
            components['file_conv_color_recipe'],
            conv_3d_preview,
            components['textbox_conv_status']
        ]
    )

    # ========== Fullscreen 3D Toggle Events ==========
    components['btn_conv_3d_fullscreen'].click(
        fn=lambda glb, preview_img: (
            gr.update(visible=True),   # show fullscreen 3D
            glb,                        # load GLB into fullscreen
            gr.update(visible=True),   # show 2D thumbnail
            preview_img                 # load 2D preview into thumbnail
        ),
        inputs=[conv_3d_preview, conv_preview],
        outputs=[
            components['col_conv_3d_fullscreen'],
            conv_3d_fullscreen,
            components['col_conv_2d_thumbnail'],
            conv_2d_thumb_preview
        ]
    )

    components['btn_conv_2d_back'].click(
        fn=lambda: (gr.update(visible=False), gr.update(visible=False)),
        inputs=[],
        outputs=[components['col_conv_3d_fullscreen'], components['col_conv_2d_thumbnail']]
    )

    components['btn_conv_3d_back'].click(
        fn=lambda: (gr.update(visible=False), gr.update(visible=False)),
        inputs=[],
        outputs=[components['col_conv_3d_fullscreen'], components['col_conv_2d_thumbnail']]
    )

    # ========== Bed Size Change → Re-render Preview ==========
    def on_bed_size_change(cache, bed_label, loop_pos, add_loop,
                           loop_width, loop_length, loop_hole, loop_angle):
        if cache is None:
            return gr.update(), cache
        preview_rgba = cache.get('preview_rgba')
        if preview_rgba is None:
            return gr.update(), cache
        # Store bed_label in cache so click handler can use it
        cache['bed_label'] = bed_label
        color_conf = cache['color_conf']
        is_dark = cache.get('is_dark', True)
        display = render_preview(
            preview_rgba,
            loop_pos if add_loop else None,
            loop_width, loop_length, loop_hole, loop_angle,
            add_loop, color_conf,
            bed_label=bed_label,
            target_width_mm=cache.get('target_width_mm'),
            is_dark=is_dark
        )
        return _preview_update(display), cache

    components['radio_conv_bed_size'].change(
        fn=on_bed_size_change,
        inputs=[
            conv_preview_cache,
            components['radio_conv_bed_size'],
            conv_loop_pos,
            components['checkbox_conv_loop_enable'],
            components['slider_conv_loop_width'],
            components['slider_conv_loop_length'],
            components['slider_conv_loop_hole'],
            components['slider_conv_loop_angle']
        ],
        outputs=[conv_preview, conv_preview_cache]
    )

    # Expose internal state refs for theme toggle in create_app
    components['_conv_preview'] = conv_preview
    components['_conv_preview_cache'] = conv_preview_cache
    components['_conv_3d_preview'] = conv_3d_preview

    return components



def create_calibration_tab_content(lang: str) -> dict:
    """Build calibration board tab UI and events. Returns component dict."""
    components = {}
    
    with gr.Row():
        with gr.Column(scale=1):
            components['md_cal_params'] = gr.Markdown(I18n.get('cal_params', lang))
                
            components['radio_cal_color_mode'] = gr.Radio(
                choices=[
                    ("BW (Black & White)", "BW (Black & White)"),
                    ("4-Color (1024 colors)", "4-Color"),
                    ("5-Color Extended (Dual Page)", "5-Color Extended (Dual Page)"),
                    ("6-Color (Smart 1296)", "6-Color (Smart 1296)"),
                    ("8-Color Max", "8-Color Max")
                ],
                value="4-Color",
                label=I18n.get('cal_color_mode', lang)
            )
                
            components['slider_cal_block_size'] = gr.Slider(
                3, 10, 5, step=1,
                label=I18n.get('cal_block_size', lang)
            )
                
            components['slider_cal_gap'] = gr.Slider(
                0.4, 2.0, 0.82, step=0.02,
                label=I18n.get('cal_gap', lang)
            )
                
            components['dropdown_cal_backing'] = gr.Dropdown(
                choices=["White", "Cyan", "Magenta", "Yellow", "Red", "Blue"],
                value="White",
                label=I18n.get('cal_backing', lang)
            )
                
            components['btn_cal_generate_btn'] = gr.Button(
                I18n.get('cal_generate_btn', lang),
                variant="primary",
                elem_classes=["primary-btn"]
            )
                
            components['textbox_cal_status'] = gr.Textbox(
                label=I18n.get('cal_status', lang),
                interactive=False
            )
            
        with gr.Column(scale=1):
            components['md_cal_preview'] = gr.Markdown(I18n.get('cal_preview', lang))
                
            cal_preview = gr.Image(
                label="Calibration Preview",
                show_label=False
            )
                
            components['file_cal_download'] = gr.File(
                label=I18n.get('cal_download', lang)
            )
    
    # Event binding - Call different generator based on mode
    def generate_board_wrapper(color_mode, block_size, gap, backing):
        """Wrapper function to call appropriate generator based on mode"""
        if color_mode == "8-Color Max":
            return generate_8color_batch_zip()
        if color_mode == "5-Color Extended (Dual Page)":
            from core.calibration import generate_5color_extended_batch_zip
            return generate_5color_extended_batch_zip(block_size, gap)
        if "5-Color Extended" in color_mode:
            from core.calibration import generate_5color_extended_board
            return generate_5color_extended_board(block_size, gap)
        if "6-Color" in color_mode:
            # Call Smart 1296 generator
            return generate_smart_board(block_size, gap)
        if color_mode == "BW (Black & White)":
            # Call BW generator (exact match to avoid matching RYBW)
            from core.calibration import generate_bw_calibration_board
            return generate_bw_calibration_board(block_size, gap, backing)
        else:
            # Call traditional 4-color generator (unified for all 4-color modes)
            # Default to RYBW palette
            return generate_calibration_board("RYBW", block_size, gap, backing)
    
    cal_event = components['btn_cal_generate_btn'].click(
            generate_board_wrapper,
            inputs=[
                components['radio_cal_color_mode'],
                components['slider_cal_block_size'],
                components['slider_cal_gap'],
                components['dropdown_cal_backing']
            ],
            outputs=[
                components['file_cal_download'],
                cal_preview,
                components['textbox_cal_status']
            ]
    )

    components['cal_event'] = cal_event
    
    return components


def create_extractor_tab_content(lang: str) -> dict:
    """Build color extractor tab UI and events. Returns component dict."""
    components = {}
    ext_state_img = gr.State(None)
    ext_state_pts = gr.State([])
    ext_curr_coord = gr.State(None)
    default_mode = "4-Color"
    ref_img = get_extractor_reference_image(default_mode)

    with gr.Row():
        with gr.Column(scale=1):
            components['md_ext_upload_section'] = gr.Markdown(
                I18n.get('ext_upload_section', lang)
            )
                
            components['radio_ext_color_mode'] = gr.Radio(
                choices=[
                    ("BW (Black & White)", "BW (Black & White)"),
                    ("4-Color (1024 colors)", "4-Color"),
                    ("5-Color Extended (2468)", "5-Color Extended"),
                    ("6-Color (Smart 1296)", "6-Color (Smart 1296)"),
                    ("8-Color Max", "8-Color Max")
                ],
                value="4-Color",
                label=I18n.get('ext_color_mode', lang)
            )
            
            # Page selection for dual-page modes (8-Color and 5-Color Extended)
            components['radio_ext_page'] = gr.Radio(
                choices=["Page 1", "Page 2"],
                value="Page 1",
                label="Page Selection",
                visible=False
            )
                
            ext_img_in = gr.Image(
                label=I18n.get('ext_photo', lang),
                type="numpy",
                interactive=True,
            )
                
            with gr.Row():
                components['btn_ext_rotate_btn'] = gr.Button(
                    I18n.get('ext_rotate_btn', lang)
                )
                components['btn_ext_reset_btn'] = gr.Button(
                    I18n.get('ext_reset_btn', lang)
                )
                
            components['md_ext_correction_section'] = gr.Markdown(
                I18n.get('ext_correction_section', lang)
            )
                
            with gr.Row():
                components['checkbox_ext_wb'] = gr.Checkbox(
                    label=I18n.get('ext_wb', lang),
                    value=False
                )
                components['checkbox_ext_vignette'] = gr.Checkbox(
                    label=I18n.get('ext_vignette', lang),
                    value=False
                )
                
            components['slider_ext_zoom'] = gr.Slider(
                0.8, 1.2, 1.0, step=0.005,
                label=I18n.get('ext_zoom', lang)
            )
                
            components['slider_ext_distortion'] = gr.Slider(
                -0.2, 0.2, 0.0, step=0.01,
                label=I18n.get('ext_distortion', lang)
            )
                
            components['slider_ext_offset_x'] = gr.Slider(
                -30, 30, 0, step=1,
                label=I18n.get('ext_offset_x', lang)
            )
                
            components['slider_ext_offset_y'] = gr.Slider(
                -30, 30, 0, step=1,
                label=I18n.get('ext_offset_y', lang)
            )
            
            # Page selection moved above, controlled by color mode
                
            components['btn_ext_extract_btn'] = gr.Button(
                I18n.get('ext_extract_btn', lang),
                variant="primary",
                elem_classes=["primary-btn"]
            )
            
            components['btn_ext_merge_btn'] = gr.Button(
                "Merge Dual Pages",
                visible=False  # Hidden by default, shown when dual-page mode selected
            )
                
            components['textbox_ext_status'] = gr.Textbox(
                label=I18n.get('ext_status', lang),
                interactive=False
            )
            
        with gr.Column(scale=1):
            ext_hint = gr.Markdown(I18n.get('ext_hint_white', lang))
                
            ext_work_img = gr.Image(
                label=I18n.get('ext_marked', lang),
                show_label=False,
                interactive=True
            )
                
            with gr.Row():
                with gr.Column():
                    components['md_ext_sampling'] = gr.Markdown(
                        I18n.get('ext_sampling', lang)
                    )
                    ext_warp_view = gr.Image(show_label=False)
                    
                with gr.Column():
                    components['md_ext_reference'] = gr.Markdown(
                        I18n.get('ext_reference', lang)
                    )
                    ext_ref_view = gr.Image(
                        show_label=False,
                        value=ref_img,
                        interactive=False
                    )
                
            with gr.Row():
                with gr.Column():
                    components['md_ext_result'] = gr.Markdown(
                        I18n.get('ext_result', lang)
                    )
                    ext_lut_view = gr.Image(
                        show_label=False,
                        interactive=True
                    )
                    
                with gr.Column():
                    components['md_ext_manual_fix'] = gr.Markdown(
                        I18n.get('ext_manual_fix', lang)
                    )
                    ext_probe_html = gr.HTML(I18n.get('ext_click_cell', lang))
                        
                    ext_picker = gr.ColorPicker(
                        label=I18n.get('ext_override', lang),
                        value="#FF0000"
                    )
                        
                    components['btn_ext_apply_btn'] = gr.Button(
                        I18n.get('ext_apply_btn', lang)
                    )
                        
                    components['file_ext_download_npy'] = gr.File(
                        label=I18n.get('ext_download_npy', lang)
                    )
    
    ext_img_in.upload(
            on_extractor_upload,
            [ext_img_in, components['radio_ext_color_mode'], components['radio_ext_page']],
            [ext_state_img, ext_work_img, ext_state_pts, ext_curr_coord, ext_hint]
    )
    
    components['radio_ext_color_mode'].change(
            on_extractor_mode_change,
            [ext_state_img, components['radio_ext_color_mode'], components['radio_ext_page']],
            [ext_state_pts, ext_hint, ext_work_img, components['radio_ext_page'], components['btn_ext_merge_btn']]
    )

    components['radio_ext_color_mode'].change(
        fn=get_extractor_reference_image,
        inputs=[components['radio_ext_color_mode'], components['radio_ext_page']],
        outputs=[ext_ref_view]
    )

    components['btn_ext_rotate_btn'].click(
            on_extractor_rotate,
            [ext_state_img, components['radio_ext_color_mode'], components['radio_ext_page']],
            [ext_state_img, ext_work_img, ext_state_pts, ext_hint]
    )
    
    ext_work_img.select(
            on_extractor_click,
            [ext_state_img, ext_state_pts, components['radio_ext_color_mode'], components['radio_ext_page']],
            [ext_work_img, ext_state_pts, ext_hint]
    )
    
    components['btn_ext_reset_btn'].click(
            on_extractor_clear,
            [ext_state_img, components['radio_ext_color_mode'], components['radio_ext_page']],
            [ext_work_img, ext_state_pts, ext_hint]
    )

    components['radio_ext_page'].change(
            on_extractor_page_change,
            [ext_state_img, components['radio_ext_color_mode'], components['radio_ext_page']],
            [ext_state_pts, ext_hint, ext_work_img]
    ).then(
        fn=get_extractor_reference_image,
        inputs=[components['radio_ext_color_mode'], components['radio_ext_page']],
        outputs=[ext_ref_view]
    )
    
    extract_inputs = [
            ext_state_img, ext_state_pts,
            components['slider_ext_offset_x'], components['slider_ext_offset_y'],
            components['slider_ext_zoom'], components['slider_ext_distortion'],
            components['checkbox_ext_wb'], components['checkbox_ext_vignette'],
            components['radio_ext_color_mode'],
            components['radio_ext_page']
    ]
    extract_outputs = [
            ext_warp_view, ext_lut_view,
            components['file_ext_download_npy'], components['textbox_ext_status']
    ]
    
    ext_event = components['btn_ext_extract_btn'].click(run_extraction_wrapper, extract_inputs, extract_outputs)
    components['ext_event'] = ext_event

    # Dynamic merge button handler based on color mode
    def merge_dual_pages_wrapper(color_mode):
        """Route to correct merge function based on color mode."""
        if "5-Color Extended" in color_mode:
            return merge_5color_extended_data()
        else:
            return merge_8color_data()

    components['btn_ext_merge_btn'].click(
            merge_dual_pages_wrapper,
            inputs=[components['radio_ext_color_mode']],
            outputs=[components['file_ext_download_npy'], components['textbox_ext_status']]
    )
    
    for s in [components['slider_ext_offset_x'], components['slider_ext_offset_y'],
                  components['slider_ext_zoom'], components['slider_ext_distortion']]:
            s.release(run_extraction_wrapper, extract_inputs, extract_outputs)
    
    ext_lut_view.select(
            probe_lut_cell,
            [components['file_ext_download_npy']],
            [ext_probe_html, ext_picker, ext_curr_coord]
    )
    components['btn_ext_apply_btn'].click(
            manual_fix_cell,
            [ext_curr_coord, ext_picker, components['file_ext_download_npy']],
            [ext_lut_view, components['textbox_ext_status']]
    )
    
    return components



def create_merge_tab_content(lang: str) -> dict:
    """Build LUT Merge tab content. Returns component dict.

    Layout: Primary LUT dropdown (single) + Secondary LUTs dropdown (multi-select)
    Primary must be 6-Color or 8-Color. Secondary options are filtered based on primary mode.
    """
    components = {}

    components['md_merge_title'] = gr.Markdown(I18n.get('merge_title', lang))
    components['md_merge_desc'] = gr.Markdown(I18n.get('merge_desc', lang))

    with gr.Row():
        with gr.Column():
            components['dd_merge_primary'] = gr.Dropdown(
                choices=LUTManager.get_lut_choices(),
                label=I18n.get('merge_lut_primary_label', lang),
                interactive=True,
            )
            components['md_merge_mode_primary'] = gr.Markdown(
                I18n.get('merge_primary_hint', lang)
            )
        with gr.Column():
            components['dd_merge_secondary'] = gr.Dropdown(
                choices=[],
                label=I18n.get('merge_lut_secondary_label', lang),
                multiselect=True,
                interactive=True,
            )
            components['md_merge_secondary_info'] = gr.Markdown(
                I18n.get('merge_secondary_none', lang)
            )

    components['slider_dedup_threshold'] = gr.Slider(
        minimum=0, maximum=20, value=3, step=0.5,
        label=I18n.get('merge_dedup_label', lang),
        info=I18n.get('merge_dedup_info', lang),
    )

    components['btn_merge'] = gr.Button(
        I18n.get('merge_btn', lang),
        variant="primary",
    )

    components['md_merge_status'] = gr.Markdown(I18n.get('merge_status_ready', lang))

    return components


def create_advanced_tab_content(lang: str) -> dict:
    """Build Advanced tab content with independent setting groups.
    独立分组构建高级设置标签页内容。

    Args:
        lang (str): Language code, 'zh' or 'en'. (语言代码)

    Returns:
        dict: Gradio component dictionary. (组件字典)
    """
    components = {}

    # --- Group 1: Palette display mode ---
    with gr.Group():
        palette_label = "调色板样式" if lang == "zh" else "Palette Style"
        palette_swatch = "色块模式" if lang == "zh" else "Swatch Grid"
        palette_card = "色卡模式" if lang == "zh" else "Card Layout"
        saved_mode = _load_user_settings().get("palette_mode", "swatch")
        components['radio_palette_mode'] = gr.Radio(
            choices=[(palette_swatch, "swatch"), (palette_card, "card")],
            value=saved_mode,
            label=palette_label,
        )

    # --- Group 2: Unlock max size limit ---
    with gr.Group():
        unlock_label = "解除最大尺寸限制" if lang == "zh" else "Unlock Max Size Limit"
        unlock_info = "开启后，图像转换的宽度/高度滑块将不再限制最大值（默认上限 400mm）" if lang == "zh" else "When enabled, width/height sliders in Image Converter will have no upper limit (default max 400mm)"
        components['checkbox_unlock_max_size'] = gr.Checkbox(
            label=unlock_label,
            value=False,
            info=unlock_info,
        )

    return components


def create_about_tab_content(lang: str) -> dict:
    """Build About tab content from i18n. Returns component dict."""
    components = {}

    # Settings section
    components['md_settings_title'] = gr.Markdown(I18n.get('settings_title', lang))
    cache_size = Stats.get_cache_size()
    cache_size_str = _format_bytes(cache_size)
    components['md_cache_size'] = gr.Markdown(
        I18n.get('settings_cache_size', lang).format(cache_size_str)
    )
    with gr.Row():
        components['btn_clear_cache'] = gr.Button(
            I18n.get('settings_clear_cache', lang),
            variant="secondary",
            size="sm"
        )
        components['btn_reset_counters'] = gr.Button(
            I18n.get('settings_reset_counters', lang),
            variant="secondary",
            size="sm"
        )
    
    output_size = Stats.get_output_size()
    output_size_str = _format_bytes(output_size)
    components['md_output_size'] = gr.Markdown(
        I18n.get('settings_output_size', lang).format(output_size_str)
    )
    components['btn_clear_output'] = gr.Button(
        I18n.get('settings_clear_output', lang),
        variant="secondary",
        size="sm"
    )
    
    components['md_settings_status'] = gr.Markdown("")
    
    # About page content (from i18n)
    components['md_about_content'] = gr.Markdown(I18n.get('about_content', lang))
    
    return components


def _format_bytes(size_bytes: int) -> str:
    """Format bytes to human readable string."""
    if size_bytes == 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"
