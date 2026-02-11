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
from config import ColorSystem, ModelingMode, MatchStrategy
from utils import Stats, LUTManager
from core.calibration import (
    generate_calibration_board,
    generate_smart_board,
    generate_8color_batch_zip,
)
from core.extractor import (
    rotate_image,
    draw_corner_points,
    run_extraction,
    probe_lut_cell,
    manual_fix_cell,
)
from core.converter import (
    ConversionRequest,
    generate_preview_cached,
    render_preview,
    update_preview_with_loop,
    on_remove_loop,
    generate_final_model,
    on_preview_click_select_color,
    generate_lut_grid_html,
    detect_lut_color_mode,
    detect_image_type,
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
    merge_8color_data,
)

# Runtime-injected i18n keys (avoids editing core/i18n.py).
if hasattr(I18n, "TEXTS"):
    I18n.TEXTS.update(
        {
            "conv_advanced": {"zh": "🛠️ 高级设置", "en": "🛠️ Advanced Settings"},
            "conv_stop": {"zh": "🛑 停止生成", "en": "🛑 Stop Generation"},
            "conv_batch_mode": {"zh": "📦 批量模式", "en": "📦 Batch Mode"},
            "conv_batch_mode_info": {
                "zh": "一次生成多个模型 (参数共享)",
                "en": "Generate multiple models (Shared Settings)",
            },
            "conv_batch_input": {
                "zh": "📤 批量上传图片",
                "en": "📤 Batch Upload Images",
            },
            "conv_lut_status": {
                "zh": "💡 拖放.npy文件自动添加",
                "en": "💡 Drop .npy file to load",
            },
        }
    )

# ============================================================================
# LUT Settings Helper Functions
# ============================================================================

CONFIG_FILE = "user_settings.json"


def load_last_lut_setting():
    """Load the last selected LUT name from the user settings file.

    Returns:
        str | None: LUT name if found, else None.
    """
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
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
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass

    data["last_lut"] = lut_name

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
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

# ============================================================================
# Image Dimension Helper Functions
# ============================================================================


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
            if img.lower().endswith(".svg"):
                try:
                    from svglib.svglib import svg2rlg

                    drawing = svg2rlg(img)
                    if drawing is None:
                        return None
                    return (drawing.width, drawing.height)
                except ImportError:
                    print("⚠️ svglib not installed, cannot read SVG size")
                    return None
                except Exception as e:
                    print(f"⚠️ Error reading SVG size: {e}")
                    return None

            with PILImage.open(img) as i:
                return i.size

        elif hasattr(img, "shape"):
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


def process_batch_generation(
    batch_files,
    is_batch,
    single_image,
    lut_path,
    target_width_mm,
    spacer_thick,
    structure_mode,
    auto_bg,
    bg_tol,
    color_mode,
    add_loop,
    loop_width,
    loop_length,
    loop_hole,
    loop_pos,
    modeling_mode,
    quantize_colors,
    color_replacements=None,
    match_strategy=MatchStrategy.RGB_EUCLIDEAN,
    progress=gr.Progress(),
):
    """Dispatch to single-image or batch generation; batch writes a ZIP of 3MFs.

    Returns:
        tuple: (file_or_zip_path, model3d_value, preview_image, status_text).
    """
    modeling_mode = ModelingMode(modeling_mode)
    match_strategy = MatchStrategy(match_strategy)
    request = ConversionRequest(
        lut_path=lut_path,
        target_width_mm=target_width_mm,
        spacer_thick=spacer_thick,
        structure_mode=structure_mode,
        auto_bg=auto_bg,
        bg_tol=bg_tol,
        color_mode=color_mode,
        add_loop=add_loop,
        loop_width=loop_width,
        loop_length=loop_length,
        loop_hole=loop_hole,
        loop_pos=loop_pos,
        modeling_mode=modeling_mode,
        quantize_colors=quantize_colors,
        color_replacements=color_replacements,
        match_strategy=match_strategy,
    )

    if not is_batch:
        out_path, glb_path, preview_img, status = generate_final_model(
            single_image, request
        )
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
        path = getattr(file_obj, "name", file_obj) if file_obj else None
        if not path or not os.path.isfile(path):
            continue
        filename = os.path.basename(path)
        progress(i / total_files, desc=f"Processing {filename}...")
        logs.append(f"[{i + 1}/{total_files}] 正在生成: {filename}")

        try:
            result_3mf, _, _, _ = generate_final_model(path, request)

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
        with zipfile.ZipFile(zip_path, "w") as zipf:
            for f in generated_files:
                zipf.write(f, os.path.basename(f))
        logs.append(f"✅ Batch done: {len(generated_files)} model(s).")
        return zip_path, None, _preview_update(None), "\n".join(logs)
    return (
        None,
        None,
        _preview_update(None),
        "❌ Batch failed: no valid models.\n" + "\n".join(logs),
    )


def create_app():
    """Build the Gradio app (tabs, i18n, events) and return the Blocks instance."""
    with gr.Blocks(title="Lumina Studio", css=HEADER_CSS + LUT_GRID_CSS) as app:
        lang_state = gr.State(value="zh")
        theme_state = gr.State(value=False)  # False=light, True=dark

        # Header
        with gr.Row(elem_classes=["header-row"], equal_height=True):
            with gr.Column(scale=10):
                app_title_html = gr.HTML(
                    value=f"<h1>✨ Lumina Studio</h1><p>{I18n.get('app_subtitle', 'zh')}</p>",
                    elem_id="app-header",
                )
            with gr.Column(scale=1, min_width=140, elem_classes=["header-controls"]):
                lang_btn = gr.Button(value="🌐 English", size="sm", elem_id="lang-btn")
                theme_btn = gr.Button(
                    value=I18n.get("theme_toggle_night", "zh"),
                    size="sm",
                    elem_id="theme-btn",
                )

        stats = Stats.get_all()
        stats_html = gr.HTML(value=_get_stats_html("zh", stats), elem_id="stats-bar")

        tab_components = {}
        with gr.Tabs() as tabs:
            components = {}

            # ============================================================================
            # Tab 1: Image Converter (图像转换)
            # ============================================================================
            with gr.TabItem(label=I18n.get("tab_converter", "zh"), id=0) as tab_conv:
                conv_components = create_converter_tab_content("zh", lang_state)
                components.update(conv_components)
            tab_components["tab_converter"] = tab_conv

            # ============================================================================
            # Tab 2: Calibration Board (校准板生成)
            # ============================================================================
            with gr.TabItem(label=I18n.get("tab_calibration", "zh"), id=1) as tab_cal:
                cal_components = create_calibration_tab_content("zh")
                components.update(cal_components)
            tab_components["tab_calibration"] = tab_cal

            # ============================================================================
            # Tab 3: Color Extractor (色彩提取)
            # ============================================================================
            with gr.TabItem(label=I18n.get("tab_extractor", "zh"), id=2) as tab_ext:
                ext_components = create_extractor_tab_content("zh")
                components.update(ext_components)
            tab_components["tab_extractor"] = tab_ext

            # ============================================================================
            # Tab 4: About (关于)
            # ============================================================================
            with gr.TabItem(label=I18n.get("tab_about", "zh"), id=3) as tab_about:
                about_components = create_about_tab_content("zh")
                components.update(about_components)
            tab_components["tab_about"] = tab_about

        footer_html = gr.HTML(value=_get_footer_html("zh"), elem_id="footer")

        # ============================================================================
        # Internal Callback Functions - Language & Theme
        # ============================================================================
        def change_language(current_lang, is_dark):
            """Switch UI language and return updates for all i18n components."""
            new_lang = "en" if current_lang == "zh" else "zh"
            updates = []
            updates.append(
                gr.update(
                    value=I18n.get(
                        "lang_btn_zh" if new_lang == "zh" else "lang_btn_en", new_lang
                    )
                )
            )
            theme_label = (
                I18n.get("theme_toggle_day", new_lang)
                if is_dark
                else I18n.get("theme_toggle_night", new_lang)
            )
            updates.append(gr.update(value=theme_label))
            updates.append(gr.update(value=_get_header_html(new_lang)))
            stats = Stats.get_all()
            updates.append(gr.update(value=_get_stats_html(new_lang, stats)))
            updates.append(gr.update(label=I18n.get("tab_converter", new_lang)))
            updates.append(gr.update(label=I18n.get("tab_calibration", new_lang)))
            updates.append(gr.update(label=I18n.get("tab_extractor", new_lang)))
            updates.append(gr.update(label=I18n.get("tab_about", new_lang)))
            updates.extend(_get_all_component_updates(new_lang, components))
            updates.append(gr.update(value=_get_footer_html(new_lang)))
            updates.append(new_lang)
            return updates

        # ============================================================================
        # Global Event Bindings (全局事件绑定)
        # ============================================================================
        output_list = [
            lang_btn,
            theme_btn,
            app_title_html,
            stats_html,
            tab_components["tab_converter"],
            tab_components["tab_calibration"],
            tab_components["tab_extractor"],
            tab_components["tab_about"],
        ]
        output_list.extend(_get_component_list(components))
        output_list.extend([footer_html, lang_state])

        lang_btn.click(
            change_language, inputs=[lang_state, theme_state], outputs=output_list
        )

        theme_btn.click(
            fn=None,
            inputs=None,
            outputs=None,
            js="() => { const url = new URL(window.location.href); const current = url.searchParams.get('__theme'); const next = current === 'dark' ? 'light' : 'dark'; url.searchParams.set('__theme', next); url.searchParams.delete('view'); window.location.href = url.toString(); return []; }",
        )

        def init_theme(current_lang, request: gr.Request | None = None):
            theme = None
            try:
                if request is not None:
                    theme = request.query_params.get("__theme")
            except Exception:
                theme = None

            is_dark = theme == "dark"
            label = (
                I18n.get("theme_toggle_day", current_lang)
                if is_dark
                else I18n.get("theme_toggle_night", current_lang)
            )
            return is_dark, gr.update(value=label)

        app.load(fn=init_theme, inputs=[lang_state], outputs=[theme_state, theme_btn])

        app.load(
            fn=on_lut_select,
            inputs=[components["dropdown_conv_lut_dropdown"]],
            outputs=[
                components["state_conv_lut_path"],
                components["md_conv_lut_status"],
            ],
        ).then(
            fn=generate_lut_grid_html,
            inputs=[components["state_conv_lut_path"], lang_state],
            outputs=[components["conv_lut_grid_view"]],
        )

        # ============================================================================
        # Internal Callback Functions - Settings & Stats
        # ============================================================================
        # Settings: cache clearing and counter reset
        def on_clear_cache(lang):
            cache_size_before = Stats.get_cache_size()
            _, _ = Stats.clear_cache()
            cache_size_after = Stats.get_cache_size()
            freed_size = max(cache_size_before - cache_size_after, 0)

            status_msg = I18n.get("settings_cache_cleared", lang).format(
                _format_bytes(freed_size)
            )
            new_cache_size = I18n.get("settings_cache_size", lang).format(
                _format_bytes(cache_size_after)
            )
            return status_msg, new_cache_size

        def on_reset_counters(lang):
            Stats.reset_all()
            new_stats = Stats.get_all()

            status_msg = I18n.get("settings_counters_reset", lang).format(
                new_stats.get("calibrations", 0),
                new_stats.get("extractions", 0),
                new_stats.get("conversions", 0),
            )
            return status_msg, _get_stats_html(lang, new_stats)

        components["btn_clear_cache"].click(
            fn=on_clear_cache,
            inputs=[lang_state],
            outputs=[components["md_settings_status"], components["md_cache_size"]],
        )

        components["btn_reset_counters"].click(
            fn=on_reset_counters,
            inputs=[lang_state],
            outputs=[components["md_settings_status"], stats_html],
        )

        def update_stats_bar(lang):
            stats = Stats.get_all()
            return _get_stats_html(lang, stats)

        if "cal_event" in components:
            components["cal_event"].then(
                fn=update_stats_bar, inputs=[lang_state], outputs=[stats_html]
            )

        if "ext_event" in components:
            components["ext_event"].then(
                fn=update_stats_bar, inputs=[lang_state], outputs=[stats_html]
            )

        if "conv_event" in components:
            components["conv_event"].then(
                fn=update_stats_bar, inputs=[lang_state], outputs=[stats_html]
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
        {I18n.get("stats_total", lang)}: 
        <strong>{stats.get("calibrations", 0)}</strong> {I18n.get("stats_calibrations", lang)} | 
        <strong>{stats.get("extractions", 0)}</strong> {I18n.get("stats_extractions", lang)} | 
        <strong>{stats.get("conversions", 0)}</strong> {I18n.get("stats_conversions", lang)}
    </div>
    """


def _get_footer_html(lang: str) -> str:
    """Return footer HTML for the given language."""
    return f"""
    <div class="footer">
        <p>{I18n.get("footer_tip", lang)}</p>
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

        if key == "md_conv_lut_status" or key == "textbox_conv_status":
            updates.append(gr.update())
            continue
        if key == "md_settings_title":
            updates.append(gr.update(value=I18n.get("settings_title", lang)))
            continue
        if key == "md_cache_size":
            cache_size = Stats.get_cache_size()
            updates.append(
                gr.update(
                    value=I18n.get("settings_cache_size", lang).format(
                        _format_bytes(cache_size)
                    )
                )
            )
            continue
        if key == "btn_clear_cache":
            updates.append(gr.update(value=I18n.get("settings_clear_cache", lang)))
            continue
        if key == "btn_reset_counters":
            updates.append(gr.update(value=I18n.get("settings_reset_counters", lang)))
            continue
        if key == "md_settings_status":
            updates.append(gr.update())
            continue

        if key.startswith("md_"):
            updates.append(gr.update(value=I18n.get(key[3:], lang)))
        elif key.startswith("lbl_"):
            updates.append(gr.update(label=I18n.get(key[4:], lang)))
        elif key.startswith("btn_"):
            updates.append(gr.update(value=I18n.get(key[4:], lang)))
        elif key.startswith("radio_"):
            choice_key = key[6:]
            if (
                choice_key == "conv_color_mode"
                or choice_key == "cal_color_mode"
                or choice_key == "ext_color_mode"
            ):
                updates.append(
                    gr.update(
                        label=I18n.get(choice_key, lang),
                        choices=[
                            (
                                I18n.get("conv_color_mode_cmyw", lang),
                                I18n.get("conv_color_mode_cmyw", "en"),
                            ),
                            (
                                I18n.get("conv_color_mode_rybw", lang),
                                I18n.get("conv_color_mode_rybw", "en"),
                            ),
                            ("6-Color (Smart 1296)", "6-Color (Smart 1296)"),
                        ],
                    )
                )
            elif choice_key == "conv_structure":
                updates.append(
                    gr.update(
                        label=I18n.get(choice_key, lang),
                        choices=[
                            (
                                I18n.get("conv_structure_double", lang),
                                I18n.get("conv_structure_double", "en"),
                            ),
                            (
                                I18n.get("conv_structure_single", lang),
                                I18n.get("conv_structure_single", "en"),
                            ),
                        ],
                    )
                )
            elif choice_key == "conv_modeling_mode":
                updates.append(
                    gr.update(
                        label=I18n.get(choice_key, lang),
                        info=I18n.get("conv_modeling_mode_info", lang),
                        choices=[
                            (
                                I18n.get("conv_modeling_mode_hifi", lang),
                                ModelingMode.HIGH_FIDELITY,
                            ),
                            (
                                I18n.get("conv_modeling_mode_pixel", lang),
                                ModelingMode.PIXEL,
                            ),
                            (
                                I18n.get("conv_modeling_mode_vector", lang),
                                ModelingMode.VECTOR,
                            ),
                        ],
                    )
                )
            else:
                # Fallback for radios without i18n mapping (e.g., ext_page)
                updates.append(gr.update())
        elif key.startswith("slider_"):
            slider_key = key[7:]
            updates.append(gr.update(label=I18n.get(slider_key, lang)))
        elif key.startswith("color_"):
            color_key = key[6:]
            updates.append(gr.update(label=I18n.get(color_key, lang)))
        elif key.startswith("checkbox_"):
            checkbox_key = key[9:]
            info_key = checkbox_key + "_info"
            if info_key in I18n.TEXTS:
                updates.append(
                    gr.update(
                        label=I18n.get(checkbox_key, lang),
                        info=I18n.get(info_key, lang),
                    )
                )
            else:
                updates.append(gr.update(label=I18n.get(checkbox_key, lang)))
        elif key.startswith("dropdown_"):
            dropdown_key = key[9:]
            info_key = dropdown_key + "_info"
            if info_key in I18n.TEXTS:
                updates.append(
                    gr.update(
                        label=I18n.get(dropdown_key, lang),
                        info=I18n.get(info_key, lang),
                    )
                )
            else:
                updates.append(gr.update(label=I18n.get(dropdown_key, lang)))
        elif key.startswith("image_"):
            image_key = key[6:]
            updates.append(gr.update(label=I18n.get(image_key, lang)))
        elif key.startswith("file_"):
            file_key = key[5:]
            updates.append(gr.update(label=I18n.get(file_key, lang)))
        elif key.startswith("textbox_"):
            textbox_key = key[8:]
            updates.append(gr.update(label=I18n.get(textbox_key, lang)))
        elif key.startswith("num_"):
            num_key = key[4:]
            updates.append(gr.update(label=I18n.get(num_key, lang)))
        elif key == "html_crop_modal":
            from ui.crop_extension import get_crop_modal_html

            updates.append(gr.update(value=get_crop_modal_html(lang)))
        elif key.startswith("html_"):
            html_key = key[5:]
            updates.append(gr.update(value=I18n.get(html_key, lang)))
        elif key.startswith("accordion_"):
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

    Uses assets/ with filenames ref_6color_smart.png, ref_cmyw_standard.png,
    or ref_rybw_standard.png. Generates via calibration board logic if missing.

    Args:
        mode_str: Color mode label (e.g. "6-Color", "CMYW", "RYBW").

    Returns:
        PIL.Image.Image | None: Reference image or None on error.
    """
    cache_dir = "assets"
    if not os.path.exists(cache_dir):
        os.makedirs(cache_dir, exist_ok=True)

    if "6-Color" in mode_str or "1296" in mode_str:
        filename = "ref_6color_smart.png"
        gen_mode = "6-Color"
    elif "CMYW" in mode_str:
        filename = "ref_cmyw_standard.png"
        gen_mode = "CMYW"
    else:
        filename = "ref_rybw_standard.png"
        gen_mode = "RYBW"

    filepath = os.path.join(cache_dir, filename)

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

        if gen_mode == "6-Color":
            from core.calibration import generate_smart_board

            _, img, _ = generate_smart_board(block_size, gap)
        else:
            from core.calibration import generate_calibration_board

            _, img, _ = generate_calibration_board(gen_mode, block_size, gap, backing)

        if img:
            if not isinstance(img, PILImage.Image):
                import numpy as np

                img = PILImage.fromarray(img.astype("uint8"), "RGB")

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
            components["md_conv_input_section"] = gr.Markdown(
                I18n.get("conv_input_section", lang)
            )

            saved_lut = load_last_lut_setting()
            current_choices = LUTManager.get_lut_choices()
            default_lut_value = saved_lut if saved_lut in current_choices else None

            with gr.Row():
                components["dropdown_conv_lut_dropdown"] = gr.Dropdown(
                    choices=current_choices,
                    label="校准数据 (.npy) / Calibration Data",
                    value=default_lut_value,
                    interactive=True,
                    scale=2,
                )
                conv_lut_upload = gr.File(
                    label="",
                    show_label=False,
                    file_types=[".npy"],
                    height=84,
                    min_width=100,
                    scale=1,
                    elem_classes=["tall-upload"],
                )

            components["md_conv_lut_status"] = gr.Markdown(
                value=I18n.get("conv_lut_status_default", lang),
                visible=True,
                elem_classes=["lut-status"],
            )
            conv_lut_path = gr.State(None)

            with gr.Row():
                components["checkbox_conv_batch_mode"] = gr.Checkbox(
                    label=I18n.get("conv_batch_mode", lang),
                    value=False,
                    info=I18n.get("conv_batch_mode_info", lang),
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
                elem_classes=["hidden-crop-component"],
            )

            # Hidden buttons for JavaScript to trigger Python callbacks (use CSS to hide)
            use_original_btn = gr.Button(
                "use_original",
                elem_id="use-original-hidden-btn",
                elem_classes=["hidden-crop-component"],
            )
            confirm_crop_btn = gr.Button(
                "confirm_crop",
                elem_id="confirm-crop-hidden-btn",
                elem_classes=["hidden-crop-component"],
            )

            # Cropper.js Modal HTML (JS is loaded via head parameter in main.py)
            from ui.crop_extension import get_crop_modal_html

            cropper_modal_html = gr.HTML(
                get_crop_modal_html(lang), elem_classes=["crop-modal-container"]
            )
            components["html_crop_modal"] = cropper_modal_html

            # Hidden HTML element to store dimensions for JavaScript
            preprocess_dimensions_html = gr.HTML(
                value='<div id="preprocess-dimensions-data" data-width="0" data-height="0" style="display:none;"></div>',
                visible=True,
                elem_classes=["hidden-crop-component"],
            )
            # ========== END Image Crop Extension ==========

            components["image_conv_image_label"] = gr.Image(
                label=I18n.get("conv_image_label", lang),
                type="filepath",
                image_mode=None,  # Auto-detect mode to support both JPEG and PNG
                height=240,
                visible=True,
                elem_id="conv-image-input",
            )
            components["file_conv_batch_input"] = gr.File(
                label=I18n.get("conv_batch_input", lang),
                file_count="multiple",
                file_types=["image"],
                visible=False,
            )
            components["md_conv_params_section"] = gr.Markdown(
                I18n.get("conv_params_section", lang)
            )

            with gr.Row(elem_classes=["compact-row"]):
                components["slider_conv_width"] = gr.Slider(
                    minimum=10,
                    maximum=400,
                    value=60,
                    step=1,
                    label=I18n.get("conv_width", lang),
                    interactive=True,
                )
                components["slider_conv_height"] = gr.Slider(
                    minimum=10,
                    maximum=400,
                    value=60,
                    step=1,
                    label=I18n.get("conv_height", lang),
                    interactive=True,
                )
                components["slider_conv_thickness"] = gr.Slider(
                    0.2, 3.5, 1.2, step=0.08, label=I18n.get("conv_thickness", lang)
                )
            conv_target_height_mm = components["slider_conv_height"]

            with gr.Row(elem_classes=["compact-row"]):
                components["radio_conv_color_mode"] = gr.Radio(
                    choices=[
                        (
                            I18n.get("conv_color_mode_cmyw", lang),
                            I18n.get("conv_color_mode_cmyw", "en"),
                        ),
                        (
                            I18n.get("conv_color_mode_rybw", lang),
                            I18n.get("conv_color_mode_rybw", "en"),
                        ),
                        ("6-Color (Smart 1296)", "6-Color (Smart 1296)"),
                        ("8-Color Max", "8-Color Max"),
                    ],
                    value=I18n.get("conv_color_mode_rybw", "en"),
                    label=I18n.get("conv_color_mode", lang),
                )

                components["radio_conv_structure"] = gr.Radio(
                    choices=[
                        (
                            I18n.get("conv_structure_double", lang),
                            I18n.get("conv_structure_double", "en"),
                        ),
                        (
                            I18n.get("conv_structure_single", lang),
                            I18n.get("conv_structure_single", "en"),
                        ),
                    ],
                    value=I18n.get("conv_structure_double", "en"),
                    label=I18n.get("conv_structure", lang),
                )

            with gr.Row(elem_classes=["compact-row"]):
                components["radio_conv_modeling_mode"] = gr.Radio(
                    choices=[
                        (
                            I18n.get("conv_modeling_mode_hifi", lang),
                            ModelingMode.HIGH_FIDELITY,
                        ),
                        (
                            I18n.get("conv_modeling_mode_pixel", lang),
                            ModelingMode.PIXEL,
                        ),
                        (
                            I18n.get("conv_modeling_mode_vector", lang),
                            ModelingMode.VECTOR,
                        ),
                    ],
                    value=ModelingMode.HIGH_FIDELITY,
                    label=I18n.get("conv_modeling_mode", lang),
                    info=I18n.get("conv_modeling_mode_info", lang),
                    elem_classes=["vertical-radio"],
                    scale=2,
                )

                components["checkbox_conv_auto_bg"] = gr.Checkbox(
                    label=I18n.get("conv_auto_bg", lang),
                    value=False,  # Changed from True to False - disable auto background removal by default
                    info=I18n.get("conv_auto_bg_info", lang),
                    scale=1,
                )
            with gr.Accordion(
                label=I18n.get("conv_advanced", lang), open=False
            ) as conv_advanced_acc:
                components["accordion_conv_advanced"] = conv_advanced_acc
                with gr.Row():
                    components["slider_conv_quantize_colors"] = gr.Slider(
                        minimum=8,
                        maximum=256,
                        step=8,
                        value=64,
                        label=I18n.get("conv_quantize_colors", lang),
                        info=I18n.get("conv_quantize_info", lang),
                        scale=3,
                    )
                    components["btn_conv_auto_color"] = gr.Button(
                        I18n.get("conv_auto_color_btn", lang),
                        variant="secondary",
                        size="sm",
                        scale=1,
                    )
                with gr.Row():
                    components["slider_conv_tolerance"] = gr.Slider(
                        0,
                        150,
                        40,
                        label=I18n.get("conv_tolerance", lang),
                        info=I18n.get("conv_tolerance_info", lang),
                    )
                with gr.Row():
                    components["radio_conv_match_strategy"] = gr.Radio(
                        choices=[
                            ("RGB Euclidean", MatchStrategy.RGB_EUCLIDEAN),
                            ("CIEDE2000", MatchStrategy.DELTAE2000),
                        ],
                        value=MatchStrategy.RGB_EUCLIDEAN,
                        label="匹配策略 / Match Strategy",
                        info="仅 High-Fidelity 模式可用 | High-Fidelity mode only",
                        interactive=True,
                    )
            gr.Markdown("---")
            with gr.Row(elem_classes=["action-buttons"]):
                components["btn_conv_preview_btn"] = gr.Button(
                    I18n.get("conv_preview_btn", lang), variant="secondary", size="lg"
                )
                components["btn_conv_generate_btn"] = gr.Button(
                    I18n.get("conv_generate_btn", lang), variant="primary", size="lg"
                )

        with gr.Column(scale=3, elem_classes=["workspace-area"]):
            with gr.Row():
                with gr.Column(scale=1):
                    components["md_conv_preview_section"] = gr.Markdown(
                        I18n.get("conv_preview_section", lang)
                    )

                    conv_preview = gr.Image(
                        label="",
                        type="numpy",
                        height=600,
                        interactive=False,
                        show_label=False,
                        elem_id="conv-preview",
                    )

                    # ========== Color Palette & Replacement ==========
                    with gr.Accordion(
                        I18n.get("conv_palette", lang), open=False
                    ) as conv_palette_acc:
                        components["accordion_conv_palette"] = conv_palette_acc
                        # 状态变量
                        conv_selected_color = gr.State(None)  # 原图中被点击的颜色
                        conv_replacement_map = gr.State({})  # 替换映射表
                        conv_replacement_history = gr.State([])
                        conv_replacement_color_state = gr.State(
                            None
                        )  # 最终确定的 LUT 颜色

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
                            container=False,
                        )
                        conv_highlight_color_hidden = gr.Textbox(
                            value="",
                            visible=True,
                            interactive=True,
                            elem_id="conv-highlight-color-hidden",
                            elem_classes=["hidden-textbox-trigger"],
                            label="",
                            show_label=False,
                            container=False,
                        )
                        conv_highlight_trigger_btn = gr.Button(
                            "trigger_highlight",
                            visible=True,
                            elem_id="conv-highlight-trigger-btn",
                            elem_classes=["hidden-textbox-trigger"],
                        )
                        conv_color_trigger_btn = gr.Button(
                            "trigger_color",
                            visible=True,
                            elem_id="conv-color-trigger-btn",
                            elem_classes=["hidden-textbox-trigger"],
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
                            container=False,
                        )
                        conv_lut_color_trigger_btn = gr.Button(
                            "trigger_lut_color",
                            elem_id="conv-lut-color-trigger-btn",
                            elem_classes=["hidden-textbox-trigger"],
                            visible=True,
                        )

                        # --- 新 UI 布局 ---
                        with gr.Row():
                            # 左侧：当前选中的原图颜色
                            with gr.Column(scale=1):
                                components["md_conv_palette_step1"] = gr.Markdown(
                                    I18n.get("conv_palette_step1", lang)
                                )
                                conv_selected_display = gr.ColorPicker(
                                    label=I18n.get("conv_palette_selected_label", lang),
                                    value="#000000",
                                    interactive=False,
                                )
                                components["color_conv_palette_selected_label"] = (
                                    conv_selected_display
                                )

                            # 右侧：LUT 真实色盘
                            with gr.Column(scale=2):
                                components["md_conv_palette_step2"] = gr.Markdown(
                                    I18n.get("conv_palette_step2", lang)
                                )

                                # LUT 网格 HTML
                                conv_lut_grid_view = gr.HTML(
                                    value=f"<div style='color:#888; padding:10px;'>{I18n.get('conv_palette_lut_loading', lang)}</div>",
                                    label="",
                                    show_label=False,
                                )
                                components["conv_lut_grid_view"] = conv_lut_grid_view

                                # 显示用户选中的替换色
                                conv_replacement_display = gr.ColorPicker(
                                    label=I18n.get("conv_palette_replace_label", lang),
                                    interactive=False,
                                )
                                components["color_conv_palette_replace_label"] = (
                                    conv_replacement_display
                                )

                        # 操作按钮区
                        with gr.Row():
                            conv_apply_replacement = gr.Button(
                                I18n.get("conv_palette_apply_btn", lang),
                                variant="primary",
                            )
                            conv_undo_replacement = gr.Button(
                                I18n.get("conv_palette_undo_btn", lang)
                            )
                            conv_clear_replacements = gr.Button(
                                I18n.get("conv_palette_clear_btn", lang)
                            )
                            components["btn_conv_palette_apply_btn"] = (
                                conv_apply_replacement
                            )
                            components["btn_conv_palette_undo_btn"] = (
                                conv_undo_replacement
                            )
                            components["btn_conv_palette_clear_btn"] = (
                                conv_clear_replacements
                            )

                        # 调色板预览 HTML (保持原有逻辑，用于显示已替换列表)
                        components["md_conv_palette_replacements_label"] = gr.Markdown(
                            I18n.get("conv_palette_replacements_label", lang)
                        )
                        conv_palette_html = gr.HTML(
                            value=f"<p style='color:#888;'>{I18n.get('conv_palette_replacements_placeholder', lang)}</p>",
                            label="",
                            show_label=False,
                        )
                    # ========== END Color Palette ==========

                    with gr.Group(visible=False):
                        components["md_conv_loop_section"] = gr.Markdown(
                            I18n.get("conv_loop_section", lang)
                        )

                        with gr.Row():
                            components["checkbox_conv_loop_enable"] = gr.Checkbox(
                                label=I18n.get("conv_loop_enable", lang), value=False
                            )
                            components["btn_conv_loop_remove"] = gr.Button(
                                I18n.get("conv_loop_remove", lang), size="sm"
                            )

                        with gr.Row():
                            components["slider_conv_loop_width"] = gr.Slider(
                                2,
                                10,
                                4,
                                step=0.5,
                                label=I18n.get("conv_loop_width", lang),
                            )
                            components["slider_conv_loop_length"] = gr.Slider(
                                4,
                                15,
                                8,
                                step=0.5,
                                label=I18n.get("conv_loop_length", lang),
                            )
                            components["slider_conv_loop_hole"] = gr.Slider(
                                1,
                                5,
                                2.5,
                                step=0.25,
                                label=I18n.get("conv_loop_hole", lang),
                            )

                        with gr.Row():
                            components["slider_conv_loop_angle"] = gr.Slider(
                                -180,
                                180,
                                0,
                                step=5,
                                label=I18n.get("conv_loop_angle", lang),
                            )
                            components["textbox_conv_loop_info"] = gr.Textbox(
                                label=I18n.get("conv_loop_info", lang),
                                interactive=False,
                                scale=2,
                            )
                    components["textbox_conv_status"] = gr.Textbox(
                        label=I18n.get("conv_status", lang),
                        lines=3,
                        interactive=False,
                        max_lines=10,
                        show_label=True,
                    )
                with gr.Column(scale=1):
                    components["md_conv_3d_preview"] = gr.Markdown(
                        I18n.get("conv_3d_preview", lang)
                    )

                    conv_3d_preview = gr.Model3D(
                        label="3D", clear_color=(0.9, 0.9, 0.9, 1.0), height=600
                    )

                    components["md_conv_download_section"] = gr.Markdown(
                        I18n.get("conv_download_section", lang)
                    )

                    components["file_conv_download_file"] = gr.File(
                        label=I18n.get("conv_download_file", lang)
                    )
                    components["btn_conv_stop"] = gr.Button(
                        value=I18n.get("conv_stop", lang), variant="stop", size="lg"
                    )

    # Event binding
    def toggle_batch_mode(is_batch):
        return [gr.update(visible=not is_batch), gr.update(visible=is_batch)]

    components["checkbox_conv_batch_mode"].change(
        fn=toggle_batch_mode,
        inputs=[components["checkbox_conv_batch_mode"]],
        outputs=[
            components["image_conv_image_label"],
            components["file_conv_batch_input"],
        ],
    )

    # ========== Image Crop Extension Events (Non-invasive) ==========
    from core.image_preprocessor import ImagePreprocessor

    def on_image_upload_process_with_html(image_path):
        """When image is uploaded, process and prepare for crop modal (不分析颜色)"""
        if image_path is None:
            return (
                0,
                0,
                None,
                '<div id="preprocess-dimensions-data" data-width="0" data-height="0" style="display:none;"></div>',
            )

        try:
            info = ImagePreprocessor.process_upload(image_path)
            # 不在这里分析颜色，等用户确认裁剪后再分析
            dimensions_html = f'<div id="preprocess-dimensions-data" data-width="{info.width}" data-height="{info.height}" style="display:none;"></div>'
            return (info.width, info.height, info.processed_path, dimensions_html)
        except Exception as e:
            print(f"Image upload error: {e}")
            return (
                0,
                0,
                None,
                '<div id="preprocess-dimensions-data" data-width="0" data-height="0" style="display:none;"></div>',
            )

    # JavaScript to open crop modal (不传递颜色推荐，弹窗中不显示)
    open_crop_modal_js = """
    () => {
        setTimeout(() => {
            const dimElement = document.querySelector('#preprocess-dimensions-data');
            if (dimElement) {
                const width = parseInt(dimElement.dataset.width) || 0;
                const height = parseInt(dimElement.dataset.height) || 0;
                if (width > 0 && height > 0) {
                    const imgContainer = document.querySelector('#conv-image-input');
                    if (imgContainer) {
                        const img = imgContainer.querySelector('img');
                        if (img && img.src && typeof window.openCropModal === 'function') {
                            window.openCropModal(img.src, width, height, 0, 0);
                        }
                    }
                }
            }
        }, 300);
    }
    """

    components["image_conv_image_label"].upload(
        on_image_upload_process_with_html,
        inputs=[components["image_conv_image_label"]],
        outputs=[
            preprocess_img_width,
            preprocess_img_height,
            preprocess_processed_path,
            preprocess_dimensions_html,
        ],
    ).then(fn=None, inputs=None, outputs=None, js=open_crop_modal_js)

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
        inputs=[
            preprocess_processed_path,
            preprocess_img_width,
            preprocess_img_height,
            crop_data_json,
        ],
        outputs=[components["image_conv_image_label"]],
    )

    def confirm_crop_image_simple(processed_path, crop_json):
        """Crop image with specified region"""
        print(
            f"[DEBUG] confirm_crop_image_simple called: {processed_path}, {crop_json}"
        )
        if processed_path is None:
            return None
        try:
            import json

            data = (
                json.loads(crop_json)
                if crop_json
                else {"x": 0, "y": 0, "w": 100, "h": 100}
            )
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
        outputs=[components["image_conv_image_label"]],
    )

    # ========== Auto Color Detection Button ==========
    # 用于触发 toast 的隐藏 HTML 组件
    color_toast_trigger = gr.HTML(
        value="", visible=True, elem_classes=["hidden-crop-component"]
    )

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
            color_analysis = ImagePreprocessor.analyze_recommended_colors(
                image_path, target_width_mm
            )
            recommended = color_analysis.get("recommended", 24)
            max_safe = color_analysis.get("max_safe", 32)
            print(
                f"[AutoColor] 分析完成: recommended={recommended}, max_safe={max_safe}"
            )
            # 添加时间戳确保每次返回值不同，触发 .then() 中的 JavaScript
            timestamp = int(time.time() * 1000)
            toast_html = f'<div id="color-rec-trigger" data-recommended="{recommended}" data-maxsafe="{max_safe}" data-ts="{timestamp}" style="display:none;"></div>'
            return gr.update(value=recommended), toast_html
        except Exception as e:
            print(f"[AutoColor] 分析失败: {e}")
            import traceback

            traceback.print_exc()
            return gr.update(), ""

    components["btn_conv_auto_color"].click(
        auto_detect_colors,
        inputs=[components["image_conv_image_label"], components["slider_conv_width"]],
        outputs=[components["slider_conv_quantize_colors"], color_toast_trigger],
    ).then(fn=None, inputs=None, outputs=None, js=show_toast_js)
    # ========== END Image Crop Extension Events ==========

    components["dropdown_conv_lut_dropdown"].change(
        on_lut_select,
        inputs=[components["dropdown_conv_lut_dropdown"]],
        outputs=[conv_lut_path, components["md_conv_lut_status"]],
    ).then(
        fn=save_last_lut_setting,
        inputs=[components["dropdown_conv_lut_dropdown"]],
        outputs=None,
    ).then(
        fn=generate_lut_grid_html,
        inputs=[conv_lut_path, lang_state],
        outputs=[conv_lut_grid_view],
    ).then(
        # 自动检测并切换颜色模式
        fn=detect_lut_color_mode,
        inputs=[conv_lut_path],
        outputs=[components["radio_conv_color_mode"]],
    )

    conv_lut_upload.upload(
        on_lut_upload_save,
        inputs=[conv_lut_upload],
        outputs=[
            components["dropdown_conv_lut_dropdown"],
            components["md_conv_lut_status"],
        ],
    ).then(
        fn=lambda: gr.update(), outputs=[components["dropdown_conv_lut_dropdown"]]
    ).then(
        # 自动检测并切换颜色模式
        fn=lambda lut_file: (
            detect_lut_color_mode(lut_file.name if lut_file else None) or gr.update()
        ),
        inputs=[conv_lut_upload],
        outputs=[components["radio_conv_color_mode"]],
    )

    components["image_conv_image_label"].change(
        fn=init_dims,
        inputs=[components["image_conv_image_label"]],
        outputs=[components["slider_conv_width"], conv_target_height_mm],
    ).then(
        # 自动检测图像类型并切换建模模式
        fn=detect_image_type,
        inputs=[components["image_conv_image_label"]],
        outputs=[components["radio_conv_modeling_mode"]],
    )
    components["slider_conv_width"].input(
        fn=calc_height_from_width,
        inputs=[components["slider_conv_width"], components["image_conv_image_label"]],
        outputs=[conv_target_height_mm],
    )
    conv_target_height_mm.input(
        fn=calc_width_from_height,
        inputs=[conv_target_height_mm, components["image_conv_image_label"]],
        outputs=[components["slider_conv_width"]],
    )

    def generate_preview_cached_with_fit(
        image_path,
        lut_path,
        target_width_mm,
        auto_bg,
        bg_tol,
        color_mode,
        modeling_mode,
        quantize_colors,
        match_strategy,
    ):
        request = ConversionRequest(
            lut_path=lut_path,
            target_width_mm=target_width_mm,
            auto_bg=auto_bg,
            bg_tol=bg_tol,
            color_mode=color_mode,
            modeling_mode=modeling_mode,
            quantize_colors=quantize_colors,
            match_strategy=match_strategy,
        )
        display, cache, status = generate_preview_cached(image_path, request)
        return _preview_update(display), cache, status

    preview_event = (
        components["btn_conv_preview_btn"]
        .click(
            generate_preview_cached_with_fit,
            inputs=[
                components["image_conv_image_label"],
                conv_lut_path,
                components["slider_conv_width"],
                components["checkbox_conv_auto_bg"],
                components["slider_conv_tolerance"],
                components["radio_conv_color_mode"],
                components["radio_conv_modeling_mode"],
                components["slider_conv_quantize_colors"],
                components["radio_conv_match_strategy"],
            ],
            outputs=[
                conv_preview,
                conv_preview_cache,
                components["textbox_conv_status"],
            ],
        )
        .then(
            on_preview_generated_update_palette,
            inputs=[conv_preview_cache, lang_state],
            outputs=[conv_palette_html, conv_selected_color],
        )
    )

    # Hidden textbox receives highlight color from JavaScript click (triggers preview highlight)
    # Use button click instead of textbox change for more reliable triggering
    def on_highlight_color_change_with_fit(
        highlight_hex,
        cache,
        loop_pos,
        add_loop,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
    ):
        display, status = on_highlight_color_change(
            highlight_hex,
            cache,
            loop_pos,
            add_loop,
            loop_width,
            loop_length,
            loop_hole,
            loop_angle,
        )
        return _preview_update(display), status

    conv_highlight_trigger_btn.click(
        on_highlight_color_change_with_fit,
        inputs=[
            conv_highlight_color_hidden,
            conv_preview_cache,
            conv_loop_pos,
            components["checkbox_conv_loop_enable"],
            components["slider_conv_loop_width"],
            components["slider_conv_loop_length"],
            components["slider_conv_loop_hole"],
            components["slider_conv_loop_angle"],
        ],
        outputs=[conv_preview, components["textbox_conv_status"]],
    )

    # [新增] 处理 LUT 色块点击事件 (JS -> Hidden Textbox -> Python)
    def on_lut_color_click(hex_color):
        return hex_color, hex_color

    conv_lut_color_trigger_btn.click(
        fn=on_lut_color_click,
        inputs=[conv_lut_color_selected_hidden],
        outputs=[conv_replacement_color_state, conv_replacement_display],
    )

    # Color replacement: Apply replacement
    def on_apply_color_replacement_with_fit(
        cache,
        selected_color,
        replacement_color,
        replacement_map,
        replacement_history,
        loop_pos,
        add_loop,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        lang_state_val,
    ):
        display, updated_cache, palette_html, new_map, new_history, status = (
            on_apply_color_replacement(
                cache,
                selected_color,
                replacement_color,
                replacement_map,
                replacement_history,
                loop_pos,
                add_loop,
                loop_width,
                loop_length,
                loop_hole,
                loop_angle,
                lang_state_val,
            )
        )
        return (
            _preview_update(display),
            updated_cache,
            palette_html,
            new_map,
            new_history,
            status,
        )

    conv_apply_replacement.click(
        on_apply_color_replacement_with_fit,
        inputs=[
            conv_preview_cache,
            conv_selected_color,
            conv_replacement_color_state,
            conv_replacement_map,
            conv_replacement_history,
            conv_loop_pos,
            components["checkbox_conv_loop_enable"],
            components["slider_conv_loop_width"],
            components["slider_conv_loop_length"],
            components["slider_conv_loop_hole"],
            components["slider_conv_loop_angle"],
            lang_state,
        ],
        outputs=[
            conv_preview,
            conv_preview_cache,
            conv_palette_html,
            conv_replacement_map,
            conv_replacement_history,
            components["textbox_conv_status"],
        ],
    )

    # Color replacement: Undo last replacement
    def on_undo_color_replacement_with_fit(
        cache,
        replacement_map,
        replacement_history,
        loop_pos,
        add_loop,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        lang_state_val,
    ):
        display, updated_cache, palette_html, new_map, new_history, status = (
            on_undo_color_replacement(
                cache,
                replacement_map,
                replacement_history,
                loop_pos,
                add_loop,
                loop_width,
                loop_length,
                loop_hole,
                loop_angle,
                lang_state_val,
            )
        )
        return (
            _preview_update(display),
            updated_cache,
            palette_html,
            new_map,
            new_history,
            status,
        )

    conv_undo_replacement.click(
        on_undo_color_replacement_with_fit,
        inputs=[
            conv_preview_cache,
            conv_replacement_map,
            conv_replacement_history,
            conv_loop_pos,
            components["checkbox_conv_loop_enable"],
            components["slider_conv_loop_width"],
            components["slider_conv_loop_length"],
            components["slider_conv_loop_hole"],
            components["slider_conv_loop_angle"],
            lang_state,
        ],
        outputs=[
            conv_preview,
            conv_preview_cache,
            conv_palette_html,
            conv_replacement_map,
            conv_replacement_history,
            components["textbox_conv_status"],
        ],
    )

    # Color replacement: Clear all replacements
    def on_clear_color_replacements_with_fit(
        cache,
        replacement_map,
        replacement_history,
        loop_pos,
        add_loop,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        lang_state_val,
    ):
        display, updated_cache, palette_html, new_map, new_history, status = (
            on_clear_color_replacements(
                cache,
                replacement_map,
                replacement_history,
                loop_pos,
                add_loop,
                loop_width,
                loop_length,
                loop_hole,
                loop_angle,
                lang_state_val,
            )
        )
        return (
            _preview_update(display),
            updated_cache,
            palette_html,
            new_map,
            new_history,
            status,
        )

    conv_clear_replacements.click(
        on_clear_color_replacements_with_fit,
        inputs=[
            conv_preview_cache,
            conv_replacement_map,
            conv_replacement_history,
            conv_loop_pos,
            components["checkbox_conv_loop_enable"],
            components["slider_conv_loop_width"],
            components["slider_conv_loop_length"],
            components["slider_conv_loop_hole"],
            components["slider_conv_loop_angle"],
            lang_state,
        ],
        outputs=[
            conv_preview,
            conv_preview_cache,
            conv_palette_html,
            conv_replacement_map,
            conv_replacement_history,
            components["textbox_conv_status"],
        ],
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
            components["textbox_conv_status"],
        ],
    )

    def update_preview_with_loop_with_fit(
        cache, loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle
    ):
        display = update_preview_with_loop(
            cache, loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle
        )
        return _preview_update(display)

    components["btn_conv_loop_remove"].click(
        on_remove_loop,
        outputs=[
            conv_loop_pos,
            components["checkbox_conv_loop_enable"],
            components["slider_conv_loop_angle"],
            components["textbox_conv_loop_info"],
        ],
    ).then(
        update_preview_with_loop_with_fit,
        inputs=[
            conv_preview_cache,
            conv_loop_pos,
            components["checkbox_conv_loop_enable"],
            components["slider_conv_loop_width"],
            components["slider_conv_loop_length"],
            components["slider_conv_loop_hole"],
            components["slider_conv_loop_angle"],
        ],
        outputs=[conv_preview],
    )
    loop_params = [
        components["slider_conv_loop_width"],
        components["slider_conv_loop_length"],
        components["slider_conv_loop_hole"],
        components["slider_conv_loop_angle"],
    ]
    for param in loop_params:
        param.change(
            update_preview_with_loop_with_fit,
            inputs=[
                conv_preview_cache,
                conv_loop_pos,
                components["checkbox_conv_loop_enable"],
                components["slider_conv_loop_width"],
                components["slider_conv_loop_length"],
                components["slider_conv_loop_hole"],
                components["slider_conv_loop_angle"],
            ],
            outputs=[conv_preview],
        )
    generate_event = components["btn_conv_generate_btn"].click(
        fn=process_batch_generation,
        inputs=[
            components["file_conv_batch_input"],
            components["checkbox_conv_batch_mode"],
            components["image_conv_image_label"],
            conv_lut_path,
            components["slider_conv_width"],
            components["slider_conv_thickness"],
            components["radio_conv_structure"],
            components["checkbox_conv_auto_bg"],
            components["slider_conv_tolerance"],
            components["radio_conv_color_mode"],
            components["checkbox_conv_loop_enable"],
            components["slider_conv_loop_width"],
            components["slider_conv_loop_length"],
            components["slider_conv_loop_hole"],
            conv_loop_pos,
            components["radio_conv_modeling_mode"],
            components["slider_conv_quantize_colors"],
            conv_replacement_map,
            components["radio_conv_match_strategy"],
        ],
        outputs=[
            components["file_conv_download_file"],
            conv_3d_preview,
            conv_preview,
            components["textbox_conv_status"],
        ],
    )
    components["conv_event"] = generate_event
    components["btn_conv_stop"].click(
        fn=None, inputs=None, outputs=None, cancels=[generate_event, preview_event]
    )
    components["state_conv_lut_path"] = conv_lut_path

    # Match strategy visibility control (only enabled in High-Fidelity mode)
    def update_match_strategy_visibility(modeling_mode):
        """Enable match strategy radio only in High-Fidelity mode."""
        is_hifi = modeling_mode == ModelingMode.HIGH_FIDELITY
        return gr.update(interactive=is_hifi)

    components["radio_conv_modeling_mode"].change(
        fn=update_match_strategy_visibility,
        inputs=[components["radio_conv_modeling_mode"]],
        outputs=[components["radio_conv_match_strategy"]],
    )

    return components


def create_calibration_tab_content(lang: str) -> dict:
    """Build calibration board tab UI and events. Returns component dict."""
    components = {}

    with gr.Row():
        with gr.Column(scale=1):
            components["md_cal_params"] = gr.Markdown(I18n.get("cal_params", lang))

            components["radio_cal_color_mode"] = gr.Radio(
                choices=[
                    (
                        I18n.get("conv_color_mode_cmyw", lang),
                        I18n.get("conv_color_mode_cmyw", "en"),
                    ),
                    (
                        I18n.get("conv_color_mode_rybw", lang),
                        I18n.get("conv_color_mode_rybw", "en"),
                    ),
                    ("6-Color (Smart 1296)", "6-Color (Smart 1296)"),
                    ("8-Color Max", "8-Color Max"),
                ],
                value=I18n.get("conv_color_mode_rybw", "en"),
                label=I18n.get("cal_color_mode", lang),
            )

            components["slider_cal_block_size"] = gr.Slider(
                3, 10, 5, step=1, label=I18n.get("cal_block_size", lang)
            )

            components["slider_cal_gap"] = gr.Slider(
                0.4, 2.0, 0.82, step=0.02, label=I18n.get("cal_gap", lang)
            )

            components["dropdown_cal_backing"] = gr.Dropdown(
                choices=["White", "Cyan", "Magenta", "Yellow", "Red", "Blue"],
                value="White",
                label=I18n.get("cal_backing", lang),
            )

            components["btn_cal_generate_btn"] = gr.Button(
                I18n.get("cal_generate_btn", lang),
                variant="primary",
                elem_classes=["primary-btn"],
            )

            components["textbox_cal_status"] = gr.Textbox(
                label=I18n.get("cal_status", lang), interactive=False
            )

        with gr.Column(scale=1):
            components["md_cal_preview"] = gr.Markdown(I18n.get("cal_preview", lang))

            cal_preview = gr.Image(label="Calibration Preview", show_label=False)

            components["file_cal_download"] = gr.File(
                label=I18n.get("cal_download", lang)
            )

    # Event binding - Call different generator based on mode
    def generate_board_wrapper(color_mode, block_size, gap, backing):
        """Wrapper function to call appropriate generator based on mode"""
        if color_mode == "8-Color Max":
            return generate_8color_batch_zip()
        if "6-Color" in color_mode:
            # Call Smart 1296 generator
            return generate_smart_board(block_size, gap)
        else:
            # Call traditional 4-color generator
            return generate_calibration_board(color_mode, block_size, gap, backing)

    cal_event = components["btn_cal_generate_btn"].click(
        generate_board_wrapper,
        inputs=[
            components["radio_cal_color_mode"],
            components["slider_cal_block_size"],
            components["slider_cal_gap"],
            components["dropdown_cal_backing"],
        ],
        outputs=[
            components["file_cal_download"],
            cal_preview,
            components["textbox_cal_status"],
        ],
    )

    components["cal_event"] = cal_event

    return components


def create_extractor_tab_content(lang: str) -> dict:
    """Build color extractor tab UI and events. Returns component dict."""
    components = {}
    ext_state_img = gr.State(None)
    ext_state_pts = gr.State([])
    ext_curr_coord = gr.State(None)
    default_mode = I18n.get("conv_color_mode_rybw", "en")
    ref_img = get_extractor_reference_image(default_mode)

    with gr.Row():
        with gr.Column(scale=1):
            components["md_ext_upload_section"] = gr.Markdown(
                I18n.get("ext_upload_section", lang)
            )

            components["radio_ext_color_mode"] = gr.Radio(
                choices=[
                    (
                        I18n.get("conv_color_mode_cmyw", lang),
                        I18n.get("conv_color_mode_cmyw", "en"),
                    ),
                    (
                        I18n.get("conv_color_mode_rybw", lang),
                        I18n.get("conv_color_mode_rybw", "en"),
                    ),
                    ("6-Color (Smart 1296)", "6-Color (Smart 1296)"),
                    ("8-Color Max", "8-Color Max"),
                ],
                value=I18n.get("conv_color_mode_rybw", "en"),
                label=I18n.get("ext_color_mode", lang),
            )

            ext_img_in = gr.Image(
                label=I18n.get("ext_photo", lang), type="numpy", interactive=True
            )

            with gr.Row():
                components["btn_ext_rotate_btn"] = gr.Button(
                    I18n.get("ext_rotate_btn", lang)
                )
                components["btn_ext_reset_btn"] = gr.Button(
                    I18n.get("ext_reset_btn", lang)
                )

            components["md_ext_correction_section"] = gr.Markdown(
                I18n.get("ext_correction_section", lang)
            )

            with gr.Row():
                components["checkbox_ext_wb"] = gr.Checkbox(
                    label=I18n.get("ext_wb", lang), value=True
                )
                components["checkbox_ext_vignette"] = gr.Checkbox(
                    label=I18n.get("ext_vignette", lang), value=False
                )

            components["slider_ext_zoom"] = gr.Slider(
                0.8, 1.2, 1.0, step=0.005, label=I18n.get("ext_zoom", lang)
            )

            components["slider_ext_distortion"] = gr.Slider(
                -0.2, 0.2, 0.0, step=0.01, label=I18n.get("ext_distortion", lang)
            )

            components["slider_ext_offset_x"] = gr.Slider(
                -30, 30, 0, step=1, label=I18n.get("ext_offset_x", lang)
            )

            components["slider_ext_offset_y"] = gr.Slider(
                -30, 30, 0, step=1, label=I18n.get("ext_offset_y", lang)
            )

            components["radio_ext_page"] = gr.Radio(
                choices=["Page 1", "Page 2"], value="Page 1", label="8-Color Page"
            )

            components["btn_ext_extract_btn"] = gr.Button(
                I18n.get("ext_extract_btn", lang),
                variant="primary",
                elem_classes=["primary-btn"],
            )

            components["btn_ext_merge_btn"] = gr.Button(
                "Merge 8-Color",
            )

            components["textbox_ext_status"] = gr.Textbox(
                label=I18n.get("ext_status", lang), interactive=False
            )

        with gr.Column(scale=1):
            ext_hint = gr.Markdown(I18n.get("ext_hint_white", lang))

            ext_work_img = gr.Image(
                label=I18n.get("ext_marked", lang), show_label=False, interactive=True
            )

            with gr.Row():
                with gr.Column():
                    components["md_ext_sampling"] = gr.Markdown(
                        I18n.get("ext_sampling", lang)
                    )
                    ext_warp_view = gr.Image(show_label=False)

                with gr.Column():
                    components["md_ext_reference"] = gr.Markdown(
                        I18n.get("ext_reference", lang)
                    )
                    ext_ref_view = gr.Image(
                        show_label=False, value=ref_img, interactive=False
                    )

            with gr.Row():
                with gr.Column():
                    components["md_ext_result"] = gr.Markdown(
                        I18n.get("ext_result", lang)
                    )
                    ext_lut_view = gr.Image(show_label=False, interactive=True)

                with gr.Column():
                    components["md_ext_manual_fix"] = gr.Markdown(
                        I18n.get("ext_manual_fix", lang)
                    )
                    ext_probe_html = gr.HTML(I18n.get("ext_click_cell", lang))

                    ext_picker = gr.ColorPicker(
                        label=I18n.get("ext_override", lang), value="#FF0000"
                    )

                    components["btn_ext_apply_btn"] = gr.Button(
                        I18n.get("ext_apply_btn", lang)
                    )

                    components["file_ext_download_npy"] = gr.File(
                        label=I18n.get("ext_download_npy", lang)
                    )

    ext_img_in.upload(
        on_extractor_upload,
        [ext_img_in, components["radio_ext_color_mode"]],
        [ext_state_img, ext_work_img, ext_state_pts, ext_curr_coord, ext_hint],
    )

    components["radio_ext_color_mode"].change(
        on_extractor_mode_change,
        [ext_state_img, components["radio_ext_color_mode"]],
        [ext_state_pts, ext_hint, ext_work_img],
    )

    components["radio_ext_color_mode"].change(
        fn=get_extractor_reference_image,
        inputs=[components["radio_ext_color_mode"]],
        outputs=[ext_ref_view],
    )

    components["btn_ext_rotate_btn"].click(
        on_extractor_rotate,
        [ext_state_img, components["radio_ext_color_mode"]],
        [ext_state_img, ext_work_img, ext_state_pts, ext_hint],
    )

    ext_work_img.select(
        on_extractor_click,
        [ext_state_img, ext_state_pts, components["radio_ext_color_mode"]],
        [ext_work_img, ext_state_pts, ext_hint],
    )

    components["btn_ext_reset_btn"].click(
        on_extractor_clear,
        [ext_state_img, components["radio_ext_color_mode"]],
        [ext_work_img, ext_state_pts, ext_hint],
    )

    extract_inputs = [
        ext_state_img,
        ext_state_pts,
        components["slider_ext_offset_x"],
        components["slider_ext_offset_y"],
        components["slider_ext_zoom"],
        components["slider_ext_distortion"],
        components["checkbox_ext_wb"],
        components["checkbox_ext_vignette"],
        components["radio_ext_color_mode"],
        components["radio_ext_page"],
    ]
    extract_outputs = [
        ext_warp_view,
        ext_lut_view,
        components["file_ext_download_npy"],
        components["textbox_ext_status"],
    ]

    ext_event = components["btn_ext_extract_btn"].click(
        run_extraction_wrapper, extract_inputs, extract_outputs
    )
    components["ext_event"] = ext_event

    components["btn_ext_merge_btn"].click(
        merge_8color_data,
        inputs=[],
        outputs=[components["file_ext_download_npy"], components["textbox_ext_status"]],
    )

    for s in [
        components["slider_ext_offset_x"],
        components["slider_ext_offset_y"],
        components["slider_ext_zoom"],
        components["slider_ext_distortion"],
    ]:
        s.release(run_extraction_wrapper, extract_inputs, extract_outputs)

    ext_lut_view.select(
        probe_lut_cell,
        [components["file_ext_download_npy"]],
        [ext_probe_html, ext_picker, ext_curr_coord],
    )
    components["btn_ext_apply_btn"].click(
        manual_fix_cell,
        [ext_curr_coord, ext_picker, components["file_ext_download_npy"]],
        [ext_lut_view, components["textbox_ext_status"]],
    )

    return components


def create_about_tab_content(lang: str) -> dict:
    """Build About tab content from i18n. Returns component dict."""
    components = {}

    # Settings section
    components["md_settings_title"] = gr.Markdown(I18n.get("settings_title", lang))
    cache_size = Stats.get_cache_size()
    cache_size_str = _format_bytes(cache_size)
    components["md_cache_size"] = gr.Markdown(
        I18n.get("settings_cache_size", lang).format(cache_size_str)
    )
    with gr.Row():
        components["btn_clear_cache"] = gr.Button(
            I18n.get("settings_clear_cache", lang), variant="secondary", size="sm"
        )
        components["btn_reset_counters"] = gr.Button(
            I18n.get("settings_reset_counters", lang), variant="secondary", size="sm"
        )
    components["md_settings_status"] = gr.Markdown("")

    # About page content (from i18n)
    components["md_about_content"] = gr.Markdown(I18n.get("about_content", lang))

    return components


def _format_bytes(size_bytes: int) -> str:
    """Format bytes to human readable string."""
    if size_bytes == 0:
        return "0 B"
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
