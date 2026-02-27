# -*- coding: utf-8 -*-
"""
Lumina Studio - UI Layout (Refactored with i18n)
UI layout definition - Refactored version with language switching support
"""

import json
import os
import shutil
import time
import zipfile
from pathlib import Path

import gradio as gr
import numpy as np
from PIL import Image as PILImage

from core.i18n import I18n
from config import ColorSystem, ModelingMode, BedManager
from utils import Stats, LUTManager
from core.calibration import generate_calibration_board, generate_smart_board, generate_8color_batch_zip
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
    generate_auto_height_map
)
from .styles import CUSTOM_CSS
from .callbacks import (
    get_first_hint,
    get_next_hint,
    on_extractor_upload,
    on_extractor_mode_change,
    on_extractor_rotate,
    on_extractor_click,
    on_extractor_clear,
    on_lut_select,
    on_lut_upload_save,
    on_apply_color_replacement,
    on_clear_color_replacements,
    on_undo_color_replacement,
    on_preview_generated_update_palette,
    on_highlight_color_change,
    on_clear_highlight,
    run_extraction_wrapper,
    merge_8color_data
)

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
  function setupBlurTrigger() {
    var sliders = document.querySelectorAll('.compact-row input[type="number"]');
    if (!sliders.length) return false;
    sliders.forEach(function (input) {
      if (input.__blur_bound) return;
      input.__blur_bound = true;
      var lastValue = input.value;
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
    return true;
  }

  function init() {
    if (setupBlurTrigger()) return;
    var observer = new MutationObserver(function () {
      if (setupBlurTrigger()) observer.disconnect();
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


# ---------- Slicer Integration ----------

import subprocess
import platform
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
    """
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
        return "❌ 没有可打开的文件 / No file to open"
    
    actual_path = file_path
    if hasattr(file_path, 'name'):
        actual_path = file_path.name
    
    if not os.path.isfile(actual_path):
        return f"❌ 文件不存在: {actual_path}"
    
    # Find exe from detected slicers
    for sid, name, exe in _INSTALLED_SLICERS:
        if sid == slicer_id:
            try:
                subprocess.Popen([exe, actual_path])
                return f"✅ 已在 {name} 中打开"
            except Exception as e:
                return f"❌ 启动 {name} 失败: {e}"
    
    return f"❌ 未找到切片软件: {slicer_id}"


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
    return round(width * ratio, 1)


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
    return round(height * ratio, 1)


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
    default_h = round(default_w * (h_px / w_px), 1)
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
                             modeling_mode, quantize_colors, color_replacements=None,
                             separate_backing=False, enable_relief=False, color_height_map=None,
                             enable_cleanup=True,
                             enable_outline=False, outline_width=2.0,
                             enable_cloisonne=False, wire_width_mm=0.4,
                             wire_height_mm=0.4,
                             free_color_set=None,
                             enable_coating=False, coating_height_mm=0.08,
                             progress=gr.Progress()):
    """Dispatch to single-image or batch generation; batch writes a ZIP of 3MFs.

    Args:
        separate_backing: Boolean flag to separate backing as individual object (default: False)
        enable_relief: Boolean flag to enable 2.5D relief mode (default: False)
        color_height_map: Dict mapping hex colors to heights in mm (default: None)

    Returns:
        tuple: (file_or_zip_path, model3d_value, preview_image, status_text).
    """
    # Handle None modeling_mode (use default)
    if modeling_mode is None:
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
            modeling_mode, quantize_colors, color_replacements, backing_color_name,
            separate_backing, enable_relief, color_height_map, enable_cleanup,
            enable_outline, outline_width,
            enable_cloisonne, wire_width_mm, wire_height_mm,
            free_color_set,
            enable_coating, coating_height_mm)

    if not is_batch:
        out_path, glb_path, preview_img, status = generate_final_model(single_image, *args)
        return out_path, glb_path, _preview_update(preview_img), status

    if not batch_files:
        return None, None, None, "❌ 请先上传图片 / Please upload images first"

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
            result_3mf, _, _, _ = generate_final_model(path, *args)

            if result_3mf and os.path.exists(result_3mf):
                new_name = os.path.splitext(filename)[0] + ".3mf"
                dest_path = os.path.join(output_dir, new_name)
                shutil.copy2(result_3mf, dest_path)
                generated_files.append(dest_path)
        except Exception as e:
            logs.append(f"❌ 失败 {filename}: {str(e)}")
            print(f"Batch error on {filename}: {e}")

    if generated_files:
        zip_path = os.path.join("outputs", f"Lumina_Batch_{int(time.time())}.zip")
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for f in generated_files:
                zipf.write(f, os.path.basename(f))
        logs.append(f"✅ Batch done: {len(generated_files)} model(s).")
        return zip_path, None, _preview_update(None), "\n".join(logs)
    return None, None, _preview_update(None), "❌ Batch failed: no valid models.\n" + "\n".join(logs)


# ========== Advanced Tab Callbacks ==========


def _update_lut_grid(lut_path, lang, palette_mode="swatch"):
    """Wrapper that picks swatch or card grid based on palette_mode setting."""
    if palette_mode == "card":
        return generate_lut_card_grid_html(lut_path, lang)
    return generate_lut_grid_html(lut_path, lang)


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
        
        # Global scripts for crop modal - using a different approach for Gradio 4.20.0
        # Store script in a hidden element and execute it
        gr.HTML("""
<div id="crop-scripts-loader" style="display:none;">
<textarea id="crop-script-content" style="display:none;">
window.cropper = null;
window.originalImageData = null;

function hideCropHelperComponents() {
    ['crop-data-json', 'use-original-hidden-btn', 'confirm-crop-hidden-btn'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) {
            el.style.cssText = 'position:absolute!important;left:-9999px!important;top:-9999px!important;width:1px!important;height:1px!important;overflow:hidden!important;opacity:0!important;visibility:hidden!important;';
        }
    });
}
document.addEventListener('DOMContentLoaded', function() { setTimeout(hideCropHelperComponents, 500); });
setInterval(hideCropHelperComponents, 2000);

window.updateCropDataJson = function(x, y, w, h) {
    var jsonData = JSON.stringify({x: x, y: y, w: w, h: h});
    var container = document.getElementById('crop-data-json');
    if (!container) {
        console.error('crop-data-json element not found');
        return;
    }
    var textarea = container.querySelector('textarea');
    if (textarea) {
        textarea.value = jsonData;
        textarea.dispatchEvent(new Event('input', { bubbles: true }));
        textarea.dispatchEvent(new Event('change', { bubbles: true }));
        console.log('Updated crop data JSON:', jsonData);
    } else {
        console.error('textarea not found in crop-data-json');
    }
};

window.clickGradioButton = function(elemId) {
    var elem = document.getElementById(elemId);
    if (!elem) {
        console.error('clickGradioButton: element not found:', elemId);
        return;
    }
    var btn = elem.querySelector('button') || elem;
    if (btn && btn.tagName === 'BUTTON') {
        btn.click();
        console.log('Clicked button:', elemId);
    } else {
        console.error('Button element not found for:', elemId);
    }
};

window.openCropModal = function(imageSrc, width, height) {
    console.log('openCropModal called:', imageSrc ? imageSrc.substring(0, 50) + '...' : 'null', width, height);
    window.originalImageData = { src: imageSrc, width: width, height: height };
    
    var origSizeEl = document.getElementById('crop-original-size');
    if (origSizeEl) {
        var prefix = origSizeEl.dataset.prefix || 'Size';
        origSizeEl.textContent = prefix + ': ' + width + ' × ' + height + ' px';
    }
    
    var img = document.getElementById('crop-image');
    if (!img) { console.error('crop-image element not found'); return; }
    img.src = imageSrc;
    
    var overlay = document.getElementById('crop-modal-overlay');
    if (overlay) overlay.style.display = 'flex';
    
    img.onload = function() {
        if (window.cropper) window.cropper.destroy();
        window.cropper = new Cropper(img, {
            viewMode: 1, dragMode: 'crop', autoCropArea: 1, responsive: true,
            crop: function(event) {
                var data = event.detail;
                var cropX = document.getElementById('crop-x');
                var cropY = document.getElementById('crop-y');
                var cropW = document.getElementById('crop-width');
                var cropH = document.getElementById('crop-height');
                var selSize = document.getElementById('crop-selection-size');
                if (cropX) cropX.value = Math.round(data.x);
                if (cropY) cropY.value = Math.round(data.y);
                if (cropW) cropW.value = Math.round(data.width);
                if (cropH) cropH.value = Math.round(data.height);
                if (selSize) {
                    var prefix = selSize.dataset.prefix || 'Selection';
                    selSize.textContent = prefix + ': ' + Math.round(data.width) + ' × ' + Math.round(data.height) + ' px';
                }
            }
        });
    };
};

window.closeCropModal = function() {
    var overlay = document.getElementById('crop-modal-overlay');
    if (overlay) overlay.style.display = 'none';
    if (window.cropper) { window.cropper.destroy(); window.cropper = null; }
};

window.updateCropperFromInputs = function() {
    if (!window.cropper) return;
    window.cropper.setData({
        x: parseInt(document.getElementById('crop-x').value) || 0,
        y: parseInt(document.getElementById('crop-y').value) || 0,
        width: parseInt(document.getElementById('crop-width').value) || 100,
        height: parseInt(document.getElementById('crop-height').value) || 100
    });
};

window.useOriginalImage = function() {
    if (!window.originalImageData) return;
    window.updateCropDataJson(0, 0, window.originalImageData.width, window.originalImageData.height);
    window.closeCropModal();
    setTimeout(function() { window.clickGradioButton('use-original-hidden-btn'); }, 100);
};

window.confirmCrop = function() {
    if (!window.cropper) return;
    var data = window.cropper.getData(true);
    console.log('confirmCrop data:', data);
    window.updateCropDataJson(Math.round(data.x), Math.round(data.y), Math.round(data.width), Math.round(data.height));
    window.closeCropModal();
    setTimeout(function() { window.clickGradioButton('confirm-crop-hidden-btn'); }, 100);
};

window.setCropRatio = function(ratio, btn) {
    if (!window.cropper) return;
    document.querySelectorAll('.crop-ratio-btn').forEach(function(b) { b.classList.remove('active'); });
    if (btn) btn.classList.add('active');
    window.cropper.setAspectRatio(ratio);
};

console.log('[CROP] Global scripts loaded, openCropModal:', typeof window.openCropModal);
</textarea>
</div>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.1/cropper.min.css">
<img src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js" onerror="
  var s1 = document.createElement('script');
  s1.src = 'https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js';
  s1.onload = function() {
    var s2 = document.createElement('script');
    s2.src = 'https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.1/cropper.min.js';
    s2.onload = function() {
      var content = document.getElementById('crop-script-content');
      if (content) {
        var s3 = document.createElement('script');
        s3.textContent = content.value;
        document.head.appendChild(s3);
      }
    };
    document.head.appendChild(s2);
  };
  document.head.appendChild(s1);
" style="display:none;">
""")
        
        tab_components = {}
        with gr.Tabs() as tabs:
            components = {}

            # Converter tab
            with gr.TabItem(label=I18n.get('tab_converter', "zh"), id=0) as tab_conv:
                conv_components = create_converter_tab_content("zh", lang_state, theme_state)
                components.update(conv_components)
            tab_components['tab_converter'] = tab_conv
            
            with gr.TabItem(label=I18n.get('tab_calibration', "zh"), id=1) as tab_cal:
                cal_components = create_calibration_tab_content("zh")
                components.update(cal_components)
            tab_components['tab_calibration'] = tab_cal
            
            with gr.TabItem(label=I18n.get('tab_extractor', "zh"), id=2) as tab_ext:
                ext_components = create_extractor_tab_content("zh")
                components.update(ext_components)
            tab_components['tab_extractor'] = tab_ext
            
            with gr.TabItem(label="🔬 高级 | Advanced", id=3) as tab_advanced:
                advanced_components = create_advanced_tab_content("zh")
                components.update(advanced_components)
            tab_components['tab_advanced'] = tab_advanced
            
            with gr.TabItem(label=I18n.get('tab_about', "zh"), id=4) as tab_about:
                about_components = create_about_tab_content("zh")
                components.update(about_components)
            tab_components['tab_about'] = tab_about
        
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
            updates.append(gr.update(label=I18n.get('tab_converter', new_lang)))
            updates.append(gr.update(label=I18n.get('tab_calibration', new_lang)))
            updates.append(gr.update(label=I18n.get('tab_extractor', new_lang)))
            updates.append(gr.update(label="🔬 高级 | Advanced" if new_lang == "zh" else "🔬 Advanced"))
            updates.append(gr.update(label=I18n.get('tab_about', new_lang)))
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
        # (No events currently)

        # ========== About Tab Events ==========
        components['btn_clear_cache'].click(
            fn=on_clear_cache,
            inputs=[lang_state],
            outputs=[components['md_settings_status'], components['md_cache_size']]
        )

        components['btn_reset_counters'].click(
            fn=on_reset_counters,
            inputs=[lang_state],
            outputs=[components['md_settings_status'], stats_html]
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
        if key == 'btn_reset_counters':
            updates.append(gr.update(value=I18n.get('settings_reset_counters', lang)))
            continue
        if key == 'md_settings_status':
            updates.append(gr.update())
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
                updates.append(gr.update(
                    label=I18n.get(choice_key, lang),
                    choices=[
                        ("BW (Black & White)", "BW (Black & White)"),
                        ("4-Color (1024 colors)", "4-Color"),
                        ("6-Color (Smart 1296)", "6-Color (Smart 1296)"),
                        ("8-Color Max", "8-Color Max")
                    ]
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


def get_extractor_reference_image(mode_str):
    """Load or generate reference image for color extractor (disk-cached).

    Uses assets/ with filenames ref_bw_standard.png, ref_cmyw_standard.png,
    ref_rybw_standard.png, ref_6color_smart.png, or ref_8color_smart.png.
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
    if "8-Color" in mode_str:
        filename = "ref_8color_smart.png"
        gen_mode = "8-Color"
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
                elem_id="conv-image-input"
            )
            components['file_conv_batch_input'] = gr.File(
                label=I18n.get('conv_batch_input', lang),
                file_count="multiple",
                file_types=["image"],
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
                minimum=1.0,
                maximum=20.0,
                value=1.2,
                step=0.1,
                label="当前选中颜色的独立高度 | Selected Color Z-Height (mm)",
                visible=False,
                info="调整当前选中颜色的总高度（包含光学层）"
            )
            
            # Auto Height Generator (only visible when relief mode is enabled)
            with gr.Accordion(label="⚡ 自动高度生成器 | Auto Height Generator", open=False, visible=False) as conv_auto_height_accordion:
                gr.Markdown("根据颜色明度自动生成归一化高度映射 | Automatically generate normalized heights based on color luminance")
                
                components['radio_conv_auto_height_mode'] = gr.Radio(
                    choices=[
                        ("深色凸起 | Darker Higher", "深色凸起"),
                        ("浅色凸起 | Lighter Higher", "浅色凸起")
                    ],
                    value="深色凸起",
                    label="排列规则 | Sorting Rule",
                    info="选择哪种颜色应该更高"
                )
                
                components['slider_conv_auto_height_max'] = gr.Slider(
                    minimum=2.0,
                    maximum=15.0,
                    value=5.0,
                    step=0.1,
                    label="最大浮雕高度 | Max Relief Height (mm)",
                    info="所有颜色的最大高度（相对于底板）"
                )
                
                components['btn_conv_auto_height_apply'] = gr.Button(
                    "✨ 一键生成高度 | Apply Auto Heights",
                    variant="primary"
                )
            
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
                        ("6-Color (Smart 1296)", "6-Color (Smart 1296)"),
                        ("8-Color Max", "8-Color Max")
                    ],
                    value=saved_color_mode,
                    label=I18n.get('conv_color_mode', lang)
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
                        conv_replacement_map = gr.State({})   # 替换映射表
                        conv_replacement_history = gr.State([])
                        conv_replacement_color_state = gr.State(None)  # 最终确定的 LUT 颜色
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

                        # --- 新 UI 布局 ---
                        with gr.Row():
                            # 左侧：当前选中的原图颜色
                            with gr.Column(scale=1):
                                components['md_conv_palette_step1'] = gr.Markdown(
                                    I18n.get('conv_palette_step1', lang)
                                )
                                conv_selected_display = gr.ColorPicker(
                                    label=I18n.get('conv_palette_selected_label', lang),
                                    value="#000000",
                                    interactive=False
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
                        0.04, 0.12, 0.08, step=0.04,
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

    # ========== Image Crop Extension Events (Non-invasive) ==========
    from core.image_preprocessor import ImagePreprocessor
    
    def on_image_upload_process_with_html(image_path):
        """When image is uploaded, process and prepare for crop modal (不分析颜色)"""
        if image_path is None:
            return (
                0, 0, None,
                '<div id="preprocess-dimensions-data" data-width="0" data-height="0" style="display:none;"></div>'
            )
        
        try:
            info = ImagePreprocessor.process_upload(image_path)
            # 不在这里分析颜色，等用户确认裁剪后再分析
            dimensions_html = f'<div id="preprocess-dimensions-data" data-width="{info.width}" data-height="{info.height}" style="display:none;"></div>'
            return (info.width, info.height, info.processed_path, dimensions_html)
        except Exception as e:
            print(f"Image upload error: {e}")
            return (0, 0, None, '<div id="preprocess-dimensions-data" data-width="0" data-height="0" style="display:none;"></div>')
    
    # JavaScript to open crop modal (不传递颜色推荐，弹窗中不显示)
    open_crop_modal_js = """
    () => {
        console.log('[CROP] Trigger fired, waiting for elements...');
        setTimeout(() => {
            console.log('[CROP] Checking for openCropModal function:', typeof window.openCropModal);
            const dimElement = document.querySelector('#preprocess-dimensions-data');
            console.log('[CROP] dimElement found:', !!dimElement);
            if (dimElement) {
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
        }, 800);
    }
    """
    
    components['image_conv_image_label'].upload(
        on_image_upload_process_with_html,
        inputs=[components['image_conv_image_label']],
        outputs=[preprocess_img_width, preprocess_img_height, preprocess_processed_path, preprocess_dimensions_html]
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
            # 自动检测并切换颜色模式
            fn=detect_lut_color_mode,
            inputs=[conv_lut_path],
            outputs=[components['radio_conv_color_mode']]
    )
    

    


    conv_lut_upload.upload(
            on_lut_upload_save,
            inputs=[conv_lut_upload],
            outputs=[components['dropdown_conv_lut_dropdown'], components['md_conv_lut_status']]
    ).then(
            fn=lambda: gr.update(),
            outputs=[components['dropdown_conv_lut_dropdown']]
    ).then(
            # 自动检测并切换颜色模式
            fn=lambda lut_file: detect_lut_color_mode(lut_file.name if lut_file else None) or gr.update(),
            inputs=[conv_lut_upload],
            outputs=[components['radio_conv_color_mode']]
    )
    
    components['image_conv_image_label'].change(
            fn=init_dims,
            inputs=[components['image_conv_image_label']],
            outputs=[components['slider_conv_width'], conv_target_height_mm]
    ).then(
            # 自动检测图像类型并切换建模模式
            fn=detect_image_type,
            inputs=[components['image_conv_image_label']],
            outputs=[components['radio_conv_modeling_mode']]
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
                                         is_dark_theme=False):
        display, cache, status = generate_preview_cached(
            image_path, lut_path, target_width_mm,
            auto_bg, bg_tol, color_mode,
            modeling_mode, quantize_colors,
            enable_cleanup=enable_cleanup,
            is_dark=is_dark_theme
        )
        # Generate realtime 3D preview GLB
        glb_path = generate_realtime_glb(cache) if cache is not None else None
        return _preview_update(display), cache, status, glb_path

    # 像素模式下禁用孤立像素清理 Checkbox
    def on_modeling_mode_change_cleanup(mode):
        if mode == ModelingMode.PIXEL:
            return gr.update(interactive=False, value=False, info="像素模式下不支持孤立像素清理 | Not available in Pixel Art mode")
        else:
            return gr.update(interactive=True, info="清理 LUT 匹配后的孤立像素，提升打印成功率")

    components['radio_conv_modeling_mode'].change(
        on_modeling_mode_change_cleanup,
        inputs=[components['radio_conv_modeling_mode']],
        outputs=[components['checkbox_conv_cleanup']]
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
                theme_state
            ],
            outputs=[conv_preview, conv_preview_cache, components['textbox_conv_status'], conv_3d_preview]
    ).then(
            on_preview_generated_update_palette,
            inputs=[conv_preview_cache, lang_state],
            outputs=[conv_palette_html, conv_selected_color]
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

    conv_lut_color_trigger_btn.click(
            fn=on_lut_color_click,
            inputs=[conv_lut_color_selected_hidden],
            outputs=[conv_replacement_color_state, conv_replacement_display]
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
                                            replacement_map, replacement_history,
                                            loop_pos, add_loop, loop_width, loop_length,
                                            loop_hole, loop_angle, lang_state_val):
        display, updated_cache, palette_html, new_map, new_history, status = on_apply_color_replacement(
            cache, selected_color, replacement_color,
            replacement_map, replacement_history,
            loop_pos, add_loop, loop_width, loop_length,
            loop_hole, loop_angle, lang_state_val
        )
        return _preview_update(display), updated_cache, palette_html, new_map, new_history, status

    conv_apply_replacement.click(
            on_apply_color_replacement_with_fit,
            inputs=[
                conv_preview_cache, conv_selected_color, conv_replacement_color_state,
                conv_replacement_map, conv_replacement_history, conv_loop_pos, components['checkbox_conv_loop_enable'],
                components['slider_conv_loop_width'], components['slider_conv_loop_length'],
                components['slider_conv_loop_hole'], components['slider_conv_loop_angle'],
                lang_state
            ],
            outputs=[conv_preview, conv_preview_cache, conv_palette_html, conv_replacement_map, conv_replacement_history, components['textbox_conv_status']]
    )
    
    # Color replacement: Undo last replacement
    def on_undo_color_replacement_with_fit(cache, replacement_map, replacement_history,
                                           loop_pos, add_loop, loop_width, loop_length,
                                           loop_hole, loop_angle, lang_state_val):
        display, updated_cache, palette_html, new_map, new_history, status = on_undo_color_replacement(
            cache, replacement_map, replacement_history,
            loop_pos, add_loop, loop_width, loop_length,
            loop_hole, loop_angle, lang_state_val
        )
        return _preview_update(display), updated_cache, palette_html, new_map, new_history, status

    conv_undo_replacement.click(
            on_undo_color_replacement_with_fit,
            inputs=[
                conv_preview_cache, conv_replacement_map, conv_replacement_history,
                conv_loop_pos, components['checkbox_conv_loop_enable'],
                components['slider_conv_loop_width'], components['slider_conv_loop_length'],
                components['slider_conv_loop_hole'], components['slider_conv_loop_angle'],
                lang_state
            ],
            outputs=[conv_preview, conv_preview_cache, conv_palette_html, conv_replacement_map, conv_replacement_history, components['textbox_conv_status']]
    )
    
    # Color replacement: Clear all replacements
    def on_clear_color_replacements_with_fit(cache, replacement_map, replacement_history,
                                             loop_pos, add_loop, loop_width, loop_length,
                                             loop_hole, loop_angle, lang_state_val):
        display, updated_cache, palette_html, new_map, new_history, status = on_clear_color_replacements(
            cache, replacement_map, replacement_history,
            loop_pos, add_loop, loop_width, loop_length,
            loop_hole, loop_angle, lang_state_val
        )
        return _preview_update(display), updated_cache, palette_html, new_map, new_history, status

    conv_clear_replacements.click(
            on_clear_color_replacements_with_fit,
            inputs=[
                conv_preview_cache, conv_replacement_map, conv_replacement_history,
                conv_loop_pos, components['checkbox_conv_loop_enable'],
                components['slider_conv_loop_width'], components['slider_conv_loop_length'],
                components['slider_conv_loop_hole'], components['slider_conv_loop_angle'],
                lang_state
            ],
            outputs=[conv_preview, conv_preview_cache, conv_palette_html, conv_replacement_map, conv_replacement_history, components['textbox_conv_status']]
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
            return free_set, gr.update(), "❌ 请先点击预览图选择一个颜色"
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
        return set(), "", "✅ 已清除所有自由色标记"

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

    # [修改] 预览图点击事件同步到 UI
    def on_preview_click_sync_ui(cache, evt: gr.SelectData):
        img, display_text, hex_val, msg = on_preview_click_select_color(cache, evt)
        if hex_val is None:
            return _preview_update(img), gr.update(), gr.update(), msg
        return _preview_update(img), hex_val, hex_val, msg

    # Relief mode: update slider when color is selected
    def on_color_selected_for_relief(hex_color, enable_relief, height_map, base_thickness):
        """When user clicks a color in preview, update relief slider"""
        if not enable_relief or not hex_color:
            return gr.update(visible=False), hex_color
        
        # Get current height for this color (default to base thickness)
        current_height = height_map.get(hex_color, base_thickness)
        
        return gr.update(visible=True, value=current_height), hex_color

    conv_preview.select(
            fn=on_preview_click_sync_ui,
            inputs=[conv_preview_cache],
            outputs=[
                conv_preview,
                conv_selected_display,
                conv_selected_color,
                components['textbox_conv_status']
            ]
    ).then(
        # Also update relief slider when clicking preview image
        fn=on_color_selected_for_relief,
        inputs=[
            conv_selected_color,
            components['checkbox_conv_relief_mode'],
            conv_color_height_map,
            components['slider_conv_thickness']
        ],
        outputs=[
            components['slider_conv_relief_height'],
            conv_relief_selected_color
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
        """Toggle relief mode visibility and reset state; auto-disable cloisonné"""
        if not enable_relief:
            # Disable relief mode - hide slider, accordion, and clear state
            return gr.update(visible=False), gr.update(visible=False), {}, None, gr.update()
        else:
            # Enable relief → disable cloisonné
            gr.Info("⚠️ 2.5D浮雕模式与掐丝珐琅模式互斥，已自动关闭掐丝珐琅 | Relief and Cloisonné are mutually exclusive, Cloisonné disabled")
            if selected_color:
                current_height = height_map.get(selected_color, base_thickness)
                return gr.update(visible=True, value=current_height), gr.update(visible=True), height_map, selected_color, gr.update(value=False)
            else:
                return gr.update(visible=False), gr.update(visible=True), height_map, selected_color, gr.update(value=False)

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
            conv_color_height_map,
            conv_relief_selected_color,
            components['checkbox_conv_cloisonne_enable']
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
    
    # Hook into existing color selection event (when user clicks palette swatch or uses color trigger button)
    conv_color_trigger_btn.click(
        on_color_selected_for_relief,
        inputs=[
            conv_color_selected_hidden,
            components['checkbox_conv_relief_mode'],
            conv_color_height_map,
            components['slider_conv_thickness']
        ],
        outputs=[
            components['slider_conv_relief_height'],
            conv_relief_selected_color
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
        """Generate automatic height mapping based on color luminance using normalization"""
        if cache is None:
            gr.Warning("⚠️ 请先生成预览图 | Please generate preview first")
            return {}
        
        # Extract unique colors from the preview cache
        # cache structure: {'preview': img_array, 'matched_rgb': rgb_array, ...}
        if 'matched_rgb' not in cache:
            gr.Warning("⚠️ 预览数据不完整 | Preview data incomplete")
            return {}
        
        matched_rgb = cache['matched_rgb']
        
        # Extract unique colors (convert to hex)
        unique_colors = set()
        h, w = matched_rgb.shape[:2]
        for y in range(h):
            for x in range(w):
                r, g, b = matched_rgb[y, x]
                # Skip transparent/background pixels (assuming black is background)
                if r == 0 and g == 0 and b == 0:
                    continue
                hex_color = f'#{r:02x}{g:02x}{b:02x}'
                unique_colors.add(hex_color)
        
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
    
    generate_event = components['btn_conv_generate_btn'].click(
            fn=process_batch_generation,
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
                conv_replacement_map,
                components['checkbox_conv_separate_backing'],
                components['checkbox_conv_relief_mode'],
                conv_color_height_map,
                components['checkbox_conv_cleanup'],
                components['checkbox_conv_outline_enable'],
                components['slider_conv_outline_width'],
                components['checkbox_conv_cloisonne_enable'],
                components['slider_conv_wire_width'],
                components['slider_conv_wire_height'],
                conv_free_color_set,
                components['checkbox_conv_coating_enable'],
                components['slider_conv_coating_height']
            ],
            outputs=[
                components['file_conv_download_file'],
                conv_3d_preview,
                conv_preview,
                components['textbox_conv_status']
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
                )
        return (
            gr.update(value="📥 下载 3MF", elem_classes=["slicer-download"]),
            gr.update(elem_classes=["slicer-download"]),
            gr.update(visible=True),
        )

    components['dropdown_conv_slicer'].change(
        fn=on_slicer_dropdown_change,
        inputs=[components['dropdown_conv_slicer']],
        outputs=[
            components['btn_conv_open_slicer'],
            components['btn_conv_slicer_arrow'],
            components['file_conv_download_file'],
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

    def on_open_slicer_click(file_obj, slicer_id):
        """Open file in slicer or trigger download."""
        if slicer_id == "download":
            # Make file component visible so user can download
            if file_obj is not None:
                return gr.update(visible=True), "📥 请点击下方文件下载"
            return gr.update(), "❌ 没有可下载的文件"
        
        # Get actual file path from Gradio File object
        actual_path = None
        if file_obj is not None:
            if hasattr(file_obj, 'name'):
                actual_path = file_obj.name
            elif isinstance(file_obj, str):
                actual_path = file_obj
        
        if not actual_path:
            return gr.update(), "❌ 请先生成模型"
        
        status = open_in_slicer(actual_path, slicer_id)
        return gr.update(), status

    components['btn_conv_open_slicer'].click(
        fn=on_open_slicer_click,
        inputs=[components['file_conv_download_file'], components['dropdown_conv_slicer']],
        outputs=[components['file_conv_download_file'], components['textbox_conv_status']]
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
                    ("6-Color (Smart 1296)", "6-Color (Smart 1296)"),
                    ("8-Color Max", "8-Color Max")
                ],
                value="4-Color",
                label=I18n.get('ext_color_mode', lang)
            )
                
            ext_img_in = gr.Image(
                label=I18n.get('ext_photo', lang),
                type="numpy",
                interactive=True
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
            
            components['radio_ext_page'] = gr.Radio(
                choices=["Page 1", "Page 2"],
                value="Page 1",
                label="8-Color Page"
            )
                
            components['btn_ext_extract_btn'] = gr.Button(
                I18n.get('ext_extract_btn', lang),
                variant="primary",
                elem_classes=["primary-btn"]
            )
            
            components['btn_ext_merge_btn'] = gr.Button(
                "Merge 8-Color",
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
            [ext_img_in, components['radio_ext_color_mode']],
            [ext_state_img, ext_work_img, ext_state_pts, ext_curr_coord, ext_hint]
    )
    
    components['radio_ext_color_mode'].change(
            on_extractor_mode_change,
            [ext_state_img, components['radio_ext_color_mode']],
            [ext_state_pts, ext_hint, ext_work_img]
    )

    components['radio_ext_color_mode'].change(
        fn=get_extractor_reference_image,
        inputs=[components['radio_ext_color_mode']],
        outputs=[ext_ref_view]
    )

    components['btn_ext_rotate_btn'].click(
            on_extractor_rotate,
            [ext_state_img, components['radio_ext_color_mode']],
            [ext_state_img, ext_work_img, ext_state_pts, ext_hint]
    )
    
    ext_work_img.select(
            on_extractor_click,
            [ext_state_img, ext_state_pts, components['radio_ext_color_mode']],
            [ext_work_img, ext_state_pts, ext_hint]
    )
    
    components['btn_ext_reset_btn'].click(
            on_extractor_clear,
            [ext_state_img, components['radio_ext_color_mode']],
            [ext_work_img, ext_state_pts, ext_hint]
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

    components['btn_ext_merge_btn'].click(
            merge_8color_data,
            inputs=[],
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



def create_advanced_tab_content(lang: str) -> dict:
    """Build Advanced tab content for LUT merging. Returns component dict."""
    components = {}
    
    # Title and description
    components['md_advanced_title'] = gr.Markdown("### 🔬 高级功能 | Advanced Features" if lang == 'zh' else "### 🔬 Advanced Features")

    # Palette display mode
    palette_label = "调色板样式" if lang == "zh" else "Palette Style"
    palette_swatch = "色块模式" if lang == "zh" else "Swatch Grid"
    palette_card = "色卡模式" if lang == "zh" else "Card Layout"
    saved_mode = _load_user_settings().get("palette_mode", "swatch")
    components['radio_palette_mode'] = gr.Radio(
        choices=[(palette_swatch, "swatch"), (palette_card, "card")],
        value=saved_mode,
        label=palette_label,
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
