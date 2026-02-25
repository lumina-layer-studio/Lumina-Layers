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
from config import ColorSystem, ModelingMode
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
    render_preview,
    update_preview_with_loop,
    on_remove_loop,
    generate_final_model,
    on_preview_click_select_color,
    generate_lut_grid_html,
    detect_lut_color_mode,
    detect_image_type
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
    background-color: var(--background-fill-secondary, #f9fafb);
    padding: 15px;
    border-radius: 8px;
    border: 1px solid var(--border-color-primary, #e5e7eb);
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
    padding: 0 10px;
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
    overflow: auto !important;
}
#conv-preview .image-container,
#conv-preview .wrap,
#conv-preview .container {
    overflow: auto !important;
}
#conv-preview canvas,
#conv-preview img {
    display: block !important;
    max-width: none !important;
    height: auto !important;
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

# Preview zoom JS (wheel to zoom, double-click to fit)
PREVIEW_ZOOM_JS = """
<script>
(function() {
    function getRootFromEvent(event) {
        const target = event && event.target;
        if (!target || !target.closest) return null;
        return target.closest("#conv-preview");
    }

    function getRoot() {
        return document.getElementById("conv-preview");
    }

    function getViewport(root) {
        return root.querySelector(".image-container") || root;
    }

    function getMedia(root) {
        return root.querySelector("canvas, img");
    }

    function ensureBase(media) {
        const baseW = media.naturalWidth || media.width;
        const baseH = media.naturalHeight || media.height;
        if (!baseW || !baseH) return false;
        const sizeKey = `${baseW}x${baseH}`;
        if (media.dataset.baseSize !== sizeKey) {
            media.dataset.baseSize = sizeKey;
            media.dataset.baseW = baseW;
            media.dataset.baseH = baseH;
        }
        return true;
    }

    function setZoom(media, zoom) {
        const bw = parseFloat(media.dataset.baseW || media.width);
        const bh = parseFloat(media.dataset.baseH || media.height);
        const z = Math.max(0.2, Math.min(4, zoom));
        media.style.width = `${bw * z}px`;
        media.style.height = `${bh * z}px`;
        media.dataset.zoom = z.toFixed(3);
    }

    function fitToView(root, media) {
        const viewport = getViewport(root);
        const bw = parseFloat(media.dataset.baseW || media.width);
        const bh = parseFloat(media.dataset.baseH || media.height);
        const vw = viewport.clientWidth || root.clientWidth;
        const vh = viewport.clientHeight || root.clientHeight;
        if (!vw || !vh) {
            setZoom(media, 1);
            return;
        }
        const fitZoom = Math.min(vw / bw, vh / bh, 1);
        setZoom(media, fitZoom);
    }

    function handleWheel(e) {
        const root = getRootFromEvent(e);
        if (!root) return;
        const media = getMedia(root);
        if (!media) return;
        if (!ensureBase(media)) return;
        e.preventDefault();
        const current = parseFloat(media.dataset.zoom || "1");
        const delta = e.deltaY < 0 ? 0.1 : -0.1;
        setZoom(media, current + delta);
    }

    function handleDoubleClick(e) {
        const root = getRootFromEvent(e);
        if (!root) return;
        const media = getMedia(root);
        if (!media) return;
        if (!ensureBase(media)) return;
        e.preventDefault();
        fitToView(root, media);
    }

    function bindGlobalHandlers() {
        if (document.body && !document.body.dataset.previewZoomBound) {
            document.body.dataset.previewZoomBound = "1";
            document.addEventListener("wheel", handleWheel, { passive: false });
            document.addEventListener("dblclick", handleDoubleClick);
        }
    }

    function observeRoot() {
        const root = getRoot();
        if (!root) return false;
        if (root.dataset.zoomObserver) return true;
        root.dataset.zoomObserver = "1";
        const observer = new MutationObserver(() => {
            const media = getMedia(root);
            if (!media) return;
            if (!ensureBase(media)) return;
            const sizeKey = media.dataset.baseSize || "";
            const currentZoom = parseFloat(media.dataset.zoom || "0");
            if (currentZoom === 0 || media.dataset.lastFitSize !== sizeKey) {
                media.dataset.lastFitSize = sizeKey;
                setTimeout(() => fitToView(root, media), 0);
            }
        });
        observer.observe(root, { childList: true, subtree: true });
        return true;
    }

    function waitForRoot() {
        if (observeRoot()) return;
        const bodyObserver = new MutationObserver(() => {
            if (observeRoot()) {
                bodyObserver.disconnect();
            }
        });
        bodyObserver.observe(document.body, { childList: true, subtree: true });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", () => {
            bindGlobalHandlers();
            waitForRoot();
        });
    } else {
        bindGlobalHandlers();
        waitForRoot();
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


def _scale_preview_image(img, max_w: int = 900, max_h: int = 560):
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
        pil = pil.resize((new_w, new_h), PILImage.Resampling.NEAREST)
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
                             separate_backing=False, progress=gr.Progress()):
    """Dispatch to single-image or batch generation; batch writes a ZIP of 3MFs.

    Args:
        separate_backing: Boolean flag to separate backing as individual object (default: False)

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
    args = (lut_path, target_width_mm, spacer_thick, structure_mode, auto_bg, bg_tol,
            color_mode, add_loop, loop_width, loop_length, loop_hole, loop_pos,
            modeling_mode, quantize_colors, color_replacements, backing_color_name,
            separate_backing)

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


def create_app():
    """Build the Gradio app (tabs, i18n, events) and return the Blocks instance."""
    with gr.Blocks(title="Lumina Studio") as app:
        # Inject CSS styles via HTML component (for Gradio 4.20.0 compatibility)
        from ui.styles import CUSTOM_CSS
        gr.HTML(f"<style>{CUSTOM_CSS + HEADER_CSS + LUT_GRID_CSS}</style>")
        
        lang_state = gr.State(value="zh")
        theme_state = gr.State(value=False)  # False=light, True=dark

        # Header
        with gr.Row(elem_classes=["header-row"], equal_height=True):
            with gr.Column(scale=10):
                app_title_html = gr.HTML(
                    value=f"<h1>✨ Lumina Studio</h1><p>{I18n.get('app_subtitle', 'zh')}</p>",
                    elem_id="app-header"
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
        
        stats = Stats.get_all()
        stats_html = gr.HTML(
            value=_get_stats_html("zh", stats),
            elem_classes=["stats-bar"]
        )
        
        tab_components = {}
        with gr.Tabs() as tabs:
            components = {}

            # Converter tab
            with gr.TabItem(label=I18n.get('tab_converter', "zh"), id=0) as tab_conv:
                conv_components = create_converter_tab_content("zh", lang_state)
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

        theme_btn.click(
            fn=None,
            inputs=None,
            outputs=None,
            js="() => { const url = new URL(window.location.href); const current = url.searchParams.get('__theme'); const next = current === 'dark' ? 'light' : 'dark'; url.searchParams.set('__theme', next); url.searchParams.delete('view'); window.location.href = url.toString(); return []; }"
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
            fn=generate_lut_grid_html,
            inputs=[components['state_conv_lut_path'], lang_state],
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

def create_converter_tab_content(lang: str, lang_state=None) -> dict:
    """Build converter tab UI and events. Returns component dict for i18n.

    Args:
        lang: Initial language code ('zh' or 'en').

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
            
            # Separate backing checkbox
            components['checkbox_conv_separate_backing'] = gr.Checkbox(
                label="底板单独一个对象 | Separate Backing as Individual Object",
                value=False,
                info="勾选后，底板将作为独立对象导出到3MF文件"
            )
            
            conv_target_height_mm = components['slider_conv_height']

            with gr.Row(elem_classes=["compact-row"]):
                components['radio_conv_color_mode'] = gr.Radio(
                    choices=[
                        ("BW (Black & White)", "BW (Black & White)"),
                        ("4-Color (1024 colors)", "4-Color"),
                        ("6-Color (Smart 1296)", "6-Color (Smart 1296)"),
                        ("8-Color Max", "8-Color Max")
                    ],
                    value="4-Color",
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
                    value=ModelingMode.HIGH_FIDELITY,
                    label=I18n.get('conv_modeling_mode', lang),
                    info=I18n.get('conv_modeling_mode_info', lang),
                    elem_classes=["vertical-radio"],
                    scale=2
                )
                
                components['checkbox_conv_auto_bg'] = gr.Checkbox(
                    label=I18n.get('conv_auto_bg', lang),
                    value=False,  # Changed from True to False - disable auto background removal by default
                    info=I18n.get('conv_auto_bg_info', lang),
                    scale=1
                )
            with gr.Accordion(label=I18n.get('conv_advanced', lang), open=False) as conv_advanced_acc:
                components['accordion_conv_advanced'] = conv_advanced_acc
                with gr.Row():
                    components['slider_conv_quantize_colors'] = gr.Slider(
                        minimum=8, maximum=256, step=8, value=64,
                        label=I18n.get('conv_quantize_colors', lang),
                        info=I18n.get('conv_quantize_info', lang),
                        scale=3
                    )
                    components['btn_conv_auto_color'] = gr.Button(
                        I18n.get('conv_auto_color_btn', lang),
                        variant="secondary",
                        size="sm",
                        scale=1
                    )
                with gr.Row():
                    components['slider_conv_tolerance'] = gr.Slider(
                        0, 150, 40,
                        label=I18n.get('conv_tolerance', lang),
                        info=I18n.get('conv_tolerance_info', lang)
                    )
            gr.Markdown("---")
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
            
        with gr.Column(scale=3, elem_classes=["workspace-area"]):
            with gr.Row():
                with gr.Column(scale=1):
                    components['md_conv_preview_section'] = gr.Markdown(
                        I18n.get('conv_preview_section', lang)
                    )

                    conv_preview = gr.Image(
                        label="",
                        type="numpy",
                        height=600,
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

                        # [关键] 注入 JS 脚本
                        gr.HTML(LUT_GRID_JS)

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
                    components['textbox_conv_status'] = gr.Textbox(
                        label=I18n.get('conv_status', lang),
                        lines=3,
                        interactive=False,
                        max_lines=10,
                        show_label=True
                    )
                with gr.Column(scale=1):
                    components['md_conv_3d_preview'] = gr.Markdown(
                        I18n.get('conv_3d_preview', lang)
                    )
                        
                    conv_3d_preview = gr.Model3D(
                        label="3D",
                        clear_color=[0.9, 0.9, 0.9, 1.0],
                        height=600
                    )
                        
                    components['md_conv_download_section'] = gr.Markdown(
                        I18n.get('conv_download_section', lang)
                    )
                        
                    components['file_conv_download_file'] = gr.File(
                        label=I18n.get('conv_download_file', lang)
                    )
                    components['btn_conv_stop'] = gr.Button(
                        value=I18n.get('conv_stop', lang),
                        variant="stop",
                        size="lg"
                    )
    
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
            fn=generate_lut_grid_html,
            inputs=[conv_lut_path, lang_state],
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
                                         modeling_mode, quantize_colors):
        display, cache, status = generate_preview_cached(
            image_path, lut_path, target_width_mm,
            auto_bg, bg_tol, color_mode,
            modeling_mode, quantize_colors
        )
        return _preview_update(display), cache, status

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
                components['slider_conv_quantize_colors']
            ],
            outputs=[conv_preview, conv_preview_cache, components['textbox_conv_status']]
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

    # [修改] 预览图点击事件同步到 UI
    def on_preview_click_sync_ui(cache, evt: gr.SelectData):
        img, display_text, hex_val, msg = on_preview_click_select_color(cache, evt)
        if hex_val is None:
            return _preview_update(img), gr.update(), gr.update(), msg
        return _preview_update(img), hex_val, hex_val, msg

    conv_preview.select(
            fn=on_preview_click_sync_ui,
            inputs=[conv_preview_cache],
            outputs=[
                conv_preview,
                conv_selected_display,
                conv_selected_color,
                components['textbox_conv_status']
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
                components['checkbox_conv_separate_backing']
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
                    ("8-Color Max", "8-Color Max"),
                    ("单耗材阶梯卡 (K/S Calibration)", "K/S Step Card")
                ],
                value="4-Color",
                label=I18n.get('cal_color_mode', lang)
            )
            
            # Standard calibration parameters (visible for regular modes)
            with gr.Group(visible=True) as standard_params_group:
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
            
            # K/S step card parameters (hidden by default)
            with gr.Group(visible=False) as ks_params_group:
                components['slider_ks_layer_height'] = gr.Slider(
                    minimum=0.04,
                    maximum=0.20,
                    value=0.08,
                    step=0.01,
                    label="层高 | Layer Height (mm)",
                    info="必须与实际打印设置一致 | Must match your print settings"
                )
                
                components['slider_ks_num_steps'] = gr.Slider(
                    minimum=3,
                    maximum=10,
                    value=5,
                    step=1,
                    label="阶梯数量 | Number of Steps",
                    info="测试 1 到 N 层 | Test 1 to N layers"
                )
                
                components['slider_ks_base_thickness'] = gr.Slider(
                    minimum=0.4,
                    maximum=1.2,
                    value=0.6,
                    step=0.1,
                    label="底座厚度 | Base Thickness (mm)",
                    info="黑白底座厚度 | Black/White backing thickness"
                )
            
            components['group_standard_params'] = standard_params_group
            components['group_ks_params'] = ks_params_group
                
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
    def generate_board_wrapper(color_mode, block_size, gap, backing, ks_layer_height, ks_num_steps, ks_base_thickness):
        """Wrapper function to call appropriate generator based on mode"""
        if color_mode == "K/S Step Card":
            # Call K/S step card generator (3MF unified output)
            from core.calibration import generate_ks_step_card_3mf
            return generate_ks_step_card_3mf(ks_layer_height, int(ks_num_steps), ks_base_thickness)
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
    
    # Toggle parameter visibility based on mode selection
    def toggle_cal_params(color_mode):
        """Show/hide parameters based on selected mode"""
        is_ks_mode = (color_mode == "K/S Step Card")
        return [
            gr.update(visible=not is_ks_mode),  # standard_params_group
            gr.update(visible=is_ks_mode)       # ks_params_group
        ]
    
    components['radio_cal_color_mode'].change(
        fn=toggle_cal_params,
        inputs=[components['radio_cal_color_mode']],
        outputs=[
            components['group_standard_params'],
            components['group_ks_params']
        ]
    )
    
    cal_event = components['btn_cal_generate_btn'].click(
            generate_board_wrapper,
            inputs=[
                components['radio_cal_color_mode'],
                components['slider_cal_block_size'],
                components['slider_cal_gap'],
                components['dropdown_cal_backing'],
                components['slider_ks_layer_height'],
                components['slider_ks_num_steps'],
                components['slider_ks_base_thickness']
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
    ext_state_original_img = gr.State(None)  # Store original image for K/S extraction
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
                    ("8-Color Max", "8-Color Max"),
                    ("K/S 参数提取 (K/S Parameter)", "K/S Parameter")
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
                
            # Standard extraction parameters (visible for regular modes)
            with gr.Group(visible=True) as standard_ext_params_group:
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
            
            # K/S extraction parameters (hidden by default)
            with gr.Group(visible=False) as ks_ext_params_group:
                gr.Markdown("### 📸 K/S 参数提取设置")
                
                components['slider_ks_ext_layer_height'] = gr.Slider(
                    minimum=0.04,
                    maximum=0.20,
                    value=0.08,
                    step=0.01,
                    label="层高 | Layer Height (mm)",
                    info="必须与打印设置一致 | Must match print settings"
                )
                
                components['slider_ks_ext_num_steps'] = gr.Slider(
                    minimum=3,
                    maximum=10,
                    value=5,
                    step=1,
                    label="阶梯数量 | Number of Steps",
                    info="与打印的阶梯卡一致 | Match your printed card"
                )
                
                components['checkbox_ks_white_balance'] = gr.Checkbox(
                    label="🎨 启用白平衡 | Enable White Balance",
                    value=False,
                    info="⚠️ 如果颜色失真，请关闭此选项 | Turn off if colors are distorted"
                )
                
                gr.Markdown(
                    """
                    **📋 操作步骤：**
                    1. 上传打印好的阶梯卡照片
                    2. 点击 4 个角点选择 <span title="推荐使用白色校色背景板（MakerWorld 搜索 2192593）。背景板比 A4 纸更白更均匀，校色更准确。" style="border-bottom:1px dashed #888;cursor:help;">A4纸/校色背景板</span> 边界（绿色）
                    3. 点击 4 个角点选择阶梯卡边界（红色）
                    4. 调整层高和阶梯数
                    5. ⚠️ 如果检测结果颜色失真，关闭白平衡
                    6. 点击提取按钮计算 K/S 参数
                    """
                )
            
            components['group_standard_ext_params'] = standard_ext_params_group
            components['group_ks_ext_params'] = ks_ext_params_group
                
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
            
            # Standard extraction results (visible for regular modes)
            with gr.Group(visible=True) as standard_ext_results_group:
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
            
            # K/S extraction results (hidden by default)
            with gr.Group(visible=False) as ks_ext_results_group:
                gr.Markdown("### 📊 K/S 参数计算结果")
                
                with gr.Row():
                    components['img_ks_fitting_plot'] = gr.Image(
                        label="拟合曲线 | Fitting Curves",
                        show_label=True,
                        height=400
                    )
                    
                    components['img_ks_detection'] = gr.Image(
                        label="检测结果 | Detection Result",
                        show_label=True,
                        height=400
                    )
                
                components['json_ks_results'] = gr.JSON(
                    label="📋 K/S 参数 | K/S Parameters"
                )
                
                with gr.Row():
                    components['textbox_ks_filament_name'] = gr.Textbox(
                        label="耗材名称 | Filament Name",
                        placeholder="例如: Bambu Lab PLA Cyan"
                    )
                    
                    components['colorpicker_ks_filament_color'] = gr.ColorPicker(
                        label="显示颜色 | Display Color",
                        value="#00FFFF"
                    )
                    
                    components['btn_ks_save_to_db'] = gr.Button(
                        "💾 保存到数据库 | Save to Database",
                        variant="secondary"
                    )
            
            components['group_standard_ext_results'] = standard_ext_results_group
            components['group_ks_ext_results'] = ks_ext_results_group
    
    # Toggle parameter visibility based on mode selection
    def toggle_ext_params(color_mode):
        """Show/hide parameters based on selected mode"""
        is_ks_mode = (color_mode == "K/S Parameter")
        return [
            gr.update(visible=not is_ks_mode),  # standard_ext_params_group
            gr.update(visible=is_ks_mode),      # ks_ext_params_group
            gr.update(visible=not is_ks_mode),  # standard_ext_results_group
            gr.update(visible=is_ks_mode)       # ks_ext_results_group
        ]
    
    components['radio_ext_color_mode'].change(
        fn=toggle_ext_params,
        inputs=[components['radio_ext_color_mode']],
        outputs=[
            components['group_standard_ext_params'],
            components['group_ks_ext_params'],
            components['group_standard_ext_results'],
            components['group_ks_ext_results']
        ]
    )
    
    ext_img_in.upload(
            on_extractor_upload,
            [ext_img_in, components['radio_ext_color_mode']],
            [ext_state_img, ext_state_original_img, ext_state_pts, ext_curr_coord, ext_hint]
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
            [ext_state_img, ext_state_original_img, ext_state_pts, components['radio_ext_color_mode']],
            [ext_state_img, ext_state_original_img, ext_work_img, ext_state_pts, ext_hint]
    )
    
    components['btn_ext_reset_btn'].click(
            on_extractor_clear,
            [ext_state_img, components['radio_ext_color_mode']],
            [ext_work_img, ext_state_pts, ext_hint]
    )
    
    # K/S extraction wrapper
    def run_ks_extraction_wrapper(original_img, pts, layer_height, num_steps, enable_white_balance):
        """Wrapper for K/S parameter extraction using ChromaStack's original code"""
        if original_img is None:
            return None, None, {}, "❌ 请先上传照片"
        
        if not pts or len(pts) < 8:
            return None, None, {}, "❌ 请先选择 A4纸/校色背景板 和阶梯卡的角点（共需要 8 个点）"
        
        # Split points: first 4 for A4, last 4 for chip
        a4_corners = pts[:4]
        chip_corners = pts[4:8]
        
        try:
            import cv2
            import numpy as np
            import pandas as pd
            from scipy.optimize import minimize
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import os
            import sys
            
            # Import from local ks_engine module (uses gentle white balance)
            from core.ks_engine.calibration_ks import (
                apply_perspective_transform,
                auto_white_balance_by_paper,
                km_reflectance,
                fit_km_parameters
            )
            
            # Constants from ChromaStack
            A4_WIDTH = 1414
            A4_HEIGHT = 1000
            CHIP_W, CHIP_H = 400, 500
            BACKING_REFLECTANCE_WHITE = 0.94
            BACKING_REFLECTANCE_BLACK = 0.00
            
            # Read original image
            # Gradio Image (type="numpy") provides RGB, OpenCV needs BGR
            if isinstance(original_img, str):
                raw_img = cv2.imread(original_img)
            else:
                raw_img = cv2.cvtColor(original_img, cv2.COLOR_RGB2BGR)
            
            print(f"[K/S] Using ChromaStack's original algorithm")
            print(f"[K/S] A4 corners: {a4_corners}")
            print(f"[K/S] Chip corners (relative to corrected A4): {chip_corners}")
            
            # Step 1: A4 correction (using ChromaStack's function)
            pts_a4 = np.float32(a4_corners)
            img_a4 = apply_perspective_transform(raw_img, pts_a4, A4_WIDTH, A4_HEIGHT)
            
            # K/S calibration requires STRONG white balance:
            # A4 paper edges must be normalized to ~240 (white), not just color-balanced.
            # Without this, all reflectance values are too low and K gets overestimated.
            h_a4, w_a4 = img_a4.shape[:2]
            margin_h = int(h_a4 * 0.1)
            margin_w = int(w_a4 * 0.1)
            wb_mask = np.zeros((h_a4, w_a4), dtype=np.uint8)
            cv2.rectangle(wb_mask, (0, 0), (w_a4, margin_h), 255, -1)
            cv2.rectangle(wb_mask, (0, h_a4 - margin_h), (w_a4, h_a4), 255, -1)
            cv2.rectangle(wb_mask, (0, 0), (margin_w, h_a4), 255, -1)
            cv2.rectangle(wb_mask, (w_a4 - margin_w, 0), (w_a4, h_a4), 255, -1)
            mean_bg = cv2.mean(img_a4, mask=wb_mask)[:3]  # BGR
            
            # Target: normalize paper white to 240
            target_white = 240.0
            wb_gains = target_white / (np.array(mean_bg) + 1e-5)
            wb_gains = np.clip(wb_gains, 0.5, 3.0)
            
            if enable_white_balance:
                img_calibrated = np.clip(cv2.multiply(img_a4.astype(float), wb_gains), 0, 255).astype(np.uint8)
                print(f"[K/S WB] Paper BGR: {np.array(mean_bg).astype(int)}, Target: {target_white}, Gains: {wb_gains.round(3)}")
            else:
                img_calibrated = img_a4
                print(f"[K/S WB] Disabled. Paper BGR: {np.array(mean_bg).astype(int)}")
            
            print(f"[K/S DEBUG] img_calibrated pixel[0,0] BGR: {img_calibrated[0,0]}")
            
            # Step 2: Chip extraction (using ChromaStack's function)
            # IMPORTANT: chip_corners are relative to img_calibrated, not raw_img
            pts_chip = np.float32(chip_corners)
            img_chip = apply_perspective_transform(img_calibrated, pts_chip, CHIP_W, CHIP_H)
            
            # Step 3: Sample colors (ChromaStack's logic)
            rows = int(num_steps)
            cols = 2
            dy = CHIP_H // rows
            dx = CHIP_W // cols
            
            data = []
            debug_view = img_chip.copy()
            
            print(f"[K/S DEBUG] img_chip shape: {img_chip.shape}, dtype: {img_chip.dtype}")
            print(f"[K/S DEBUG] img_chip pixel[0,0] (BGR): {img_chip[0,0]}")
            print(f"[K/S DEBUG] Sampling grid: {rows} rows x {cols} cols, dy={dy}, dx={dx}")
            
            for r in range(rows):
                x_left = int(0.5 * dx)
                x_right = int(1.5 * dx)
                y_center = int((r + 0.5) * dy)
                
                patch_size = 20
                
                roi_0 = img_chip[y_center-patch_size:y_center+patch_size, x_left-patch_size:x_left+patch_size]
                bgr_0_mean = np.mean(roi_0, axis=(0,1))
                rgb_0 = bgr_0_mean[::-1]  # BGR -> RGB
                
                roi_w = img_chip[y_center-patch_size:y_center+patch_size, x_right-patch_size:x_right+patch_size]
                bgr_w_mean = np.mean(roi_w, axis=(0,1))
                rgb_w = bgr_w_mean[::-1]  # BGR -> RGB
                
                R0_linear = (rgb_0 / 255.0) ** 2.2
                Rw_linear = (rgb_w / 255.0) ** 2.2
                
                layer_idx = rows - r
                
                print(f"[K/S DEBUG] Layer {layer_idx}: "
                      f"BlackBase BGR={bgr_0_mean.astype(int)} RGB={rgb_0.astype(int)} -> linear={R0_linear.round(4)}, "
                      f"WhiteBase BGR={bgr_w_mean.astype(int)} RGB={rgb_w.astype(int)} -> linear={Rw_linear.round(4)}")
                
                data.append({
                    'Layer_Index': layer_idx,
                    'R0_r': R0_linear[0], 'R0_g': R0_linear[1], 'R0_b': R0_linear[2],
                    'Rw_r': Rw_linear[0], 'Rw_g': Rw_linear[1], 'Rw_b': Rw_linear[2]
                })
                
                cv2.circle(debug_view, (x_left, y_center), 5, (0,255,0), -1)
                cv2.circle(debug_view, (x_right, y_center), 5, (0,0,255), -1)
            
            os.makedirs("output/ks_engine/debug", exist_ok=True)
            cv2.imwrite("output/ks_engine/debug/sampling_points.jpg", debug_view)
            
            df = pd.DataFrame(data).sort_values('Layer_Index')
            
            # Step 4: Calculate K-M parameters (using ChromaStack's function)
            thicknesses = df['Layer_Index'].values * layer_height
            
            results = {}
            channels = ['r', 'g', 'b']
            
            fig, axes = plt.subplots(1, 3, figsize=(15, 5))
            
            status_lines = []
            status_lines.append("🚀 Kubelka-Munk 参数拟合 (ChromaStack 算法)")
            status_lines.append(f"   厚度范围: {thicknesses[0]:.2f}mm - {thicknesses[-1]:.2f}mm")
            status_lines.append("")
            
            for i, ch in enumerate(channels):
                R0_meas = df[f'R0_{ch}'].values
                Rw_meas = df[f'Rw_{ch}'].values
                
                print(f"[K/S DEBUG] Channel {ch.upper()}: R0_meas={R0_meas.round(4)}, Rw_meas={Rw_meas.round(4)}")
                
                (best_K, best_S), error = fit_km_parameters(thicknesses, R0_meas, Rw_meas)
                results[ch] = {'K': best_K, 'S': best_S}
                
                print(f"[K/S DEBUG] Channel {ch.upper()}: K={best_K:.4f}, S={best_S:.4f}, error={error:.6f}")
                status_lines.append(f"🎨 {ch.upper()} 通道: K={best_K:.4f}, S={best_S:.4f} (误差: {error:.5f})")
                
                ax = axes[i]
                ax.scatter(thicknesses, R0_meas, color='black', label='Measured (Black Base)', s=50)
                ax.scatter(thicknesses, Rw_meas, color='gray', marker='s', label='Measured (White Base)', s=50)
                
                h_smooth = np.linspace(0, thicknesses[-1] + 0.2, 50)
                R0_smooth = km_reflectance(best_K, best_S, h_smooth, BACKING_REFLECTANCE_BLACK)
                Rw_smooth = km_reflectance(best_K, best_S, h_smooth, BACKING_REFLECTANCE_WHITE)
                
                plot_color = 'red' if ch=='r' else 'green' if ch=='g' else 'blue'
                ax.plot(h_smooth, R0_smooth, linestyle='--', color=plot_color, label='K-M Model (Black)', linewidth=2)
                ax.plot(h_smooth, Rw_smooth, linestyle='-', color=plot_color, alpha=0.5, label='K-M Model (White)', linewidth=2)
                
                ax.set_title(f"Channel {ch.upper()}\nK={best_K:.3f}, S={best_S:.3f}", fontsize=12, fontweight='bold')
                ax.set_xlabel("Thickness (mm)", fontsize=10)
                ax.set_ylabel("Reflectance", fontsize=10)
                ax.grid(True, alpha=0.3)
                if i == 0:
                    ax.legend(fontsize=8)
            
            plt.tight_layout()
            plot_path = "output/ks_engine/km_fitting_result.png"
            plt.savefig(plot_path, dpi=150)
            plt.close()
            
            # Build K/S params dict
            ks_params = {
                'K': [results['r']['K'], results['g']['K'], results['b']['K']],
                'S': [results['r']['S'], results['g']['S'], results['b']['S']]
            }
            
            status_lines.append("")
            status_lines.append("📋 JSON 参数 (可直接填入 my_filament.json):")
            status_lines.append(f'  "FILAMENT_K": [{ks_params["K"][0]:.4f}, {ks_params["K"][1]:.4f}, {ks_params["K"][2]:.4f}]')
            status_lines.append(f'  "FILAMENT_S": [{ks_params["S"][0]:.4f}, {ks_params["S"][1]:.4f}, {ks_params["S"][2]:.4f}]')
            
            avg_S = np.mean(ks_params['S'])
            avg_K = np.mean(ks_params['K'])
            
            status_lines.append("")
            status_lines.append("💡 材料特性:")
            if avg_S > 10:
                status_lines.append("   [高遮盖力] 类似牛奶或浓缩颜料")
            elif avg_S < 1:
                status_lines.append("   [低遮盖力] 类似清漆或彩色玻璃")
            else:
                status_lines.append("   [半透明] 类似玉石或雾状塑料")
            
            if avg_K > 2:
                status_lines.append("   [深色] 吸光能力强")
            elif avg_K < 0.1:
                status_lines.append("   [浅色/透明] 吸光能力弱")
            
            status_message = "\n".join(status_lines)
            
            # Create detection image (original photo with A4 corners marked)
            detection_img = raw_img.copy()
            cv2.polylines(detection_img, [pts_a4.astype(int)], True, (0, 255, 0), 3)
            detection_path = "output/ks_engine/debug/detection_result.jpg"
            cv2.imwrite(detection_path, detection_img)
            
            # Calculate display color from K/S parameters
            # Use ChromaStack's multi-layer composition on BLACK backing
            # This matches the physical reality: stack N layers of filament on black base
            try:
                K_rgb = np.array(ks_params['K'])
                S_rgb = np.array(ks_params['S'])
                
                # Compute single-layer optical properties (R_layer, T_layer)
                S_safe = np.maximum(S_rgb, 1e-6)
                K_safe = np.maximum(K_rgb, 1e-9)
                a = 1 + (K_safe / S_safe)
                b = np.sqrt(a**2 - 1)
                bSh = b * S_safe * layer_height
                sinh_bSh = np.sinh(bSh)
                cosh_bSh = np.cosh(bSh)
                R_layer = sinh_bSh / (a * sinh_bSh + b * cosh_bSh)
                T_layer = b / (a * sinh_bSh + b * cosh_bSh)
                
                # Multi-layer composition on black backing (same as ChromaStack cali_verify)
                current_R = np.array([0.0, 0.0, 0.0])  # black base
                total_layers = int(num_steps)  # stack same number of layers as step card max
                for _ in range(total_layers):
                    denom = np.maximum(1.0 - R_layer * current_R, 1e-6)
                    current_R = R_layer + (T_layer**2 * current_R) / denom
                
                current_R = np.clip(current_R, 0, 1)
                
                # Linear reflectance -> sRGB gamma (simple 1/2.2, same as ChromaStack)
                srgb = current_R ** (1.0 / 2.2)
                r8 = int(np.clip(srgb[0] * 255, 0, 255))
                g8 = int(np.clip(srgb[1] * 255, 0, 255))
                b8 = int(np.clip(srgb[2] * 255, 0, 255))
                display_color = f"#{r8:02x}{g8:02x}{b8:02x}"
                print(f"[K/S] Display Color: {display_color} (R_layer={R_layer}, T_layer={T_layer}, final_R={current_R}, {total_layers} layers on black)")
            except Exception as e:
                print(f"[K/S] Display Color calculation error: {e}")
                display_color = "#888888"
            
            return plot_path, detection_path, ks_params, status_message, display_color
            
        except Exception as e:
            import traceback
            error_msg = f"❌ K/S 参数提取失败: {str(e)}\n\n"
            error_msg += traceback.format_exc()
            return None, None, {}, error_msg, "#888888"
    
    # K/S save to database
    def save_ks_to_db_wrapper(name, color, ks_params):
        """Save K/S parameters to filament database"""
        try:
            if not name:
                return "❌ 请输入耗材名称"
            
            if not ks_params or 'K' not in ks_params or 'S' not in ks_params:
                return "❌ 请先计算 K/S 参数"
            
            import json
            
            # Read existing database
            db_path = "my_filament.json"
            if os.path.exists(db_path):
                with open(db_path, 'r', encoding='utf-8') as f:
                    db = json.load(f)
            else:
                db = {"filaments": []}
            
            # Add new filament
            new_filament = {
                "name": name,
                "color": color,
                "K": ks_params['K'],
                "S": ks_params['S']
            }
            
            # Check if exists
            existing_idx = None
            for i, fil in enumerate(db.get("filaments", [])):
                if fil.get("name") == name:
                    existing_idx = i
                    break
            
            if existing_idx is not None:
                db["filaments"][existing_idx] = new_filament
                action = "更新"
            else:
                if "filaments" not in db:
                    db["filaments"] = []
                db["filaments"].append(new_filament)
                action = "添加"
            
            # Save database
            with open(db_path, 'w', encoding='utf-8') as f:
                json.dump(db, f, indent=2, ensure_ascii=False)
            
            return f"✅ 成功{action}耗材: {name}\n💾 已保存到 {db_path}"
            
        except Exception as e:
            import traceback
            error_msg = f"❌ 保存失败: {str(e)}\n\n"
            error_msg += traceback.format_exc()
            return error_msg
    
    extract_inputs = [
            ext_state_original_img, ext_state_pts,
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
    
    # Conditional extraction based on mode
    def extract_wrapper(img, pts, offset_x, offset_y, zoom, distortion, wb, vignette, color_mode, page):
        """Wrapper to route to correct extraction function"""
        if color_mode == "K/S Parameter":
            # K/S extraction - needs different output routing
            # We'll handle this separately with a dedicated button click
            return None, None, None, "⚠️ K/S 模式请使用专用的提取按钮"
        else:
            # Standard LUT extraction
            return run_extraction_wrapper(
                img, pts, offset_x, offset_y, zoom, distortion, wb, vignette, color_mode, page
            )
    
    # Extraction button - routes to different handlers based on mode
    def unified_extract_handler(img, pts, offset_x, offset_y, zoom, distortion, wb, vignette, color_mode, page, layer_height, num_steps, enable_white_balance):
        """Unified extraction handler that routes based on mode"""
        if color_mode == "K/S Parameter":
            # K/S extraction
            fitting, detection, ks_params, status, display_color = run_ks_extraction_wrapper(
                img, pts, layer_height, num_steps, enable_white_balance
            )
            # Return tuple: (warp_view, lut_view, download_file, status, fitting_plot, detection_img, ks_json, display_color)
            return None, None, None, status, fitting, detection, ks_params, display_color
        else:
            # Standard LUT extraction
            warp, lut, download, status = run_extraction_wrapper(
                img, pts, offset_x, offset_y, zoom, distortion, wb, vignette, color_mode, page
            )
            # Return tuple with None for K/S outputs, gr.update() to keep color unchanged
            return warp, lut, download, status, None, None, {}, gr.update()
    
    ext_event = components['btn_ext_extract_btn'].click(
        fn=unified_extract_handler,
        inputs=extract_inputs + [
            components['slider_ks_ext_layer_height'],
            components['slider_ks_ext_num_steps'],
            components['checkbox_ks_white_balance']
        ],
        outputs=extract_outputs + [
            components['img_ks_fitting_plot'],
            components['img_ks_detection'],
            components['json_ks_results'],
            components['colorpicker_ks_filament_color']
        ]
    )
    components['ext_event'] = ext_event
    
    # K/S save to database button
    components['btn_ks_save_to_db'].click(
        fn=save_ks_to_db_wrapper,
        inputs=[
            components['textbox_ks_filament_name'],
            components['colorpicker_ks_filament_color'],
            components['json_ks_results']
        ],
        outputs=[components['textbox_ext_status']]
    )

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
