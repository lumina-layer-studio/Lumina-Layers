"""
Lumina Studio - Converter Tab
Converter tab UI and event handlers
"""

import json
import time

import gradio as gr
from PIL import Image as PILImage

from config import ColorMode, ModelingMode, StructureMode, MatchStrategy
from utils import LUTManager
from core.converter import (
    ConversionRequest,
    generate_final_model,
)
from ui.converter_ui import (
    generate_preview_cached,
    render_preview,
    update_preview_with_loop,
    on_remove_loop,
    on_preview_click_select_color,
    generate_lut_grid_html,
)
from ui.ui_detection import (
    detect_lut_color_mode,
    detect_image_type,
)
from core.i18n import I18n
from ui.i18n_bridge import resolve_i18n_text
from ui.assets import LUT_GRID_JS, OPEN_CROP_MODAL_JS, SHOW_COLOR_TOAST_JS
from ui.callbacks import (
    on_lut_select,
    on_lut_upload_save,
    on_apply_color_replacement,
    on_clear_color_replacements,
    on_undo_color_replacement,
    on_preview_generated_update_palette,
    on_highlight_color_change,
)


CONFIG_FILE = "user_settings.json"


# Helper functions from layout_new.py (to be imported or copied)
def load_last_lut_setting():
    """Load the last selected LUT name from the user settings file."""
    import os

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("last_lut", None)
        except Exception as e:
            print(f"Failed to load settings: {e}")
    return None


def save_last_lut_setting(lut_name):
    """Persist the current LUT selection to the user settings file."""
    import os

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


def _get_image_size(img):
    """Get image dimensions (width, height). Supports file path or numpy array."""
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
    """Compute height (mm) from width (mm) preserving aspect ratio."""
    size = _get_image_size(img)
    if size is None or width is None:
        return gr.update()

    w_px, h_px = size
    if w_px == 0:
        return 0

    ratio = h_px / w_px
    return round(width * ratio, 1)


def calc_width_from_height(height, img):
    """Compute width (mm) from height (mm) preserving aspect ratio."""
    size = _get_image_size(img)
    if size is None or height is None:
        return gr.update()

    w_px, h_px = size
    if h_px == 0:
        return 0

    ratio = w_px / h_px
    return round(height * ratio, 1)


def init_dims(img):
    """Compute default width/height (mm) from image aspect ratio."""
    size = _get_image_size(img)
    if size is None:
        return 60, 60

    w_px, h_px = size
    default_w = 60
    default_h = round(default_w * (h_px / w_px), 1)
    return default_w, default_h


def _scale_preview_image(img, max_w: int = 900, max_h: int = 560):
    """Scale preview image to fit within a fixed box without changing container size."""
    import numpy as np

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
    lang="zh",
    progress=gr.Progress(),
):
    """Dispatch to single-image or batch generation; batch writes a ZIP of 3MFs."""
    import os
    import shutil
    import zipfile

    if modeling_mode in (None, ""):
        return (
            None,
            None,
            _preview_update(None),
            I18n.get("conv_err_modeling_mode_required", lang),
        )

    if color_mode in (None, ""):
        return (
            None,
            None,
            _preview_update(None),
            I18n.get("conv_err_color_mode_required", lang),
        )

    try:
        color_mode = ColorMode(color_mode)
    except Exception:
        return (
            None,
            None,
            _preview_update(None),
            I18n.get("conv_err_color_mode_required", lang),
        )

    structure_mode = StructureMode(structure_mode)

    try:
        modeling_mode = ModelingMode(modeling_mode)
    except Exception:
        return (
            None,
            None,
            _preview_update(None),
            I18n.get("conv_err_modeling_mode_invalid", lang),
        )

    if match_strategy in (None, "") and modeling_mode in (
        ModelingMode.HIGH_FIDELITY,
        ModelingMode.HIGH_FIDELITY.value,
    ):
        return (
            None,
            None,
            _preview_update(None),
            I18n.get("conv_err_match_strategy_required", lang),
        )

    try:
        match_strategy = MatchStrategy(match_strategy)
    except Exception:
        return (
            None,
            None,
            _preview_update(None),
            I18n.get("conv_err_match_strategy_invalid", lang),
        )
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
        return (
            out_path,
            glb_path,
            _preview_update(preview_img),
            resolve_i18n_text(status, lang),
        )

    if not batch_files:
        return None, None, None, I18n.get("conv_err_batch_no_images", lang)

    generated_files = []
    total_files = len(batch_files)
    logs = []

    output_dir = os.path.join("outputs", f"batch_{int(time.time())}")
    os.makedirs(output_dir, exist_ok=True)

    logs.append(I18n.get("conv_batch_start", lang).format(count=total_files))

    for i, file_obj in enumerate(batch_files):
        path = getattr(file_obj, "name", file_obj) if file_obj else None
        if not path or not os.path.isfile(path):
            continue
        filename = os.path.basename(path)
        progress(
            i / total_files,
            desc=I18n.get("conv_batch_progress_desc", lang).format(filename=filename),
        )
        logs.append(
            I18n.get("conv_batch_progress", lang).format(
                current=i + 1, total=total_files, filename=filename
            )
        )

        try:
            result_3mf, _, _, _ = generate_final_model(path, request)

            if result_3mf and os.path.exists(result_3mf):
                new_name = os.path.splitext(filename)[0] + ".3mf"
                dest_path = os.path.join(output_dir, new_name)
                shutil.copy2(result_3mf, dest_path)
                generated_files.append(dest_path)
        except Exception as e:
            logs.append(
                I18n.get("conv_batch_failed_item", lang).format(
                    filename=filename, error=str(e)
                )
            )
            print(f"Batch error on {filename}: {e}")

    if generated_files:
        zip_path = os.path.join("outputs", f"Lumina_Batch_{int(time.time())}.zip")
        with zipfile.ZipFile(zip_path, "w") as zipf:
            for f in generated_files:
                zipf.write(f, os.path.basename(f))
        logs.append(
            I18n.get("conv_batch_done", lang).format(count=len(generated_files))
        )
        return zip_path, None, _preview_update(None), "\n".join(logs)
    return (
        None,
        None,
        _preview_update(None),
        I18n.get("conv_batch_failed_no_valid", lang) + "\n" + "\n".join(logs),
    )


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
                    label=I18n.get("conv_lut_dropdown_label", lang),
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
                            ColorMode.CMYW.value,
                        ),
                        (
                            I18n.get("conv_color_mode_rybw", lang),
                            ColorMode.RYBW.value,
                        ),
                        (
                            I18n.get("color_mode_6color", lang),
                            ColorMode.SIX_COLOR.value,
                        ),
                        (
                            I18n.get("color_mode_8color", lang),
                            ColorMode.EIGHT_COLOR_MAX.value,
                        ),
                    ],
                    value=ColorMode.RYBW.value,
                    label=I18n.get("conv_color_mode", lang),
                )

                components["radio_conv_structure"] = gr.Radio(
                    choices=[
                        (
                            I18n.get("conv_structure_double", lang),
                            StructureMode.DOUBLE_SIDED.value,
                        ),
                        (
                            I18n.get("conv_structure_single", lang),
                            StructureMode.SINGLE_SIDED.value,
                        ),
                    ],
                    value=StructureMode.DOUBLE_SIDED.value,
                    label=I18n.get("conv_structure", lang),
                )

            with gr.Row(elem_classes=["compact-row"]):
                components["radio_conv_modeling_mode"] = gr.Radio(
                    choices=[
                        (
                            I18n.get("conv_modeling_mode_hifi", lang),
                            ModelingMode.HIGH_FIDELITY.value,
                        ),
                        (
                            I18n.get("conv_modeling_mode_pixel", lang),
                            ModelingMode.PIXEL.value,
                        ),
                        (
                            I18n.get("conv_modeling_mode_vector", lang),
                            ModelingMode.VECTOR.value,
                        ),
                    ],
                    value=ModelingMode.HIGH_FIDELITY.value,
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
                            (
                                I18n.get("conv_match_strategy_rgb", lang),
                                MatchStrategy.RGB_EUCLIDEAN,
                            ),
                            (
                                I18n.get("conv_match_strategy_deltae", lang),
                                MatchStrategy.DELTAE2000,
                            ),
                        ],
                        value=MatchStrategy.RGB_EUCLIDEAN,
                        label=I18n.get("conv_match_strategy", lang),
                        info=I18n.get("conv_match_strategy_info", lang),
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
                        label=I18n.get("conv_3d_label", lang),
                        clear_color=(0.9, 0.9, 0.9, 1.0),
                        height=600,
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

    components["image_conv_image_label"].upload(
        on_image_upload_process_with_html,
        inputs=[components["image_conv_image_label"]],
        outputs=[
            preprocess_img_width,
            preprocess_img_height,
            preprocess_processed_path,
            preprocess_dimensions_html,
        ],
    ).then(fn=None, inputs=None, outputs=None, js=OPEN_CROP_MODAL_JS)

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

    def auto_detect_colors(image_path, target_width_mm):
        """自动检测推荐的色彩细节值"""
        if image_path is None:
            return gr.update(), ""
        try:
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
    ).then(fn=None, inputs=None, outputs=None, js=SHOW_COLOR_TOAST_JS)
    # ========== END Image Crop Extension Events ==========

    components["dropdown_conv_lut_dropdown"].change(
        on_lut_select,
        inputs=[components["dropdown_conv_lut_dropdown"], lang_state],
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
        fn=lambda lut_file, current_color_mode: (
            detect_lut_color_mode(lut_file.name if lut_file else None)
            or current_color_mode
        ),
        inputs=[conv_lut_upload, components["radio_conv_color_mode"]],
        outputs=[components["radio_conv_color_mode"]],
    )

    components["image_conv_image_label"].change(
        fn=init_dims,
        inputs=[components["image_conv_image_label"]],
        outputs=[components["slider_conv_width"], conv_target_height_mm],
    ).then(
        # 自动检测图像类型并切换建模模式
        fn=lambda image_file, current_modeling_mode: (
            detect_image_type(image_file) or current_modeling_mode
        ),
        inputs=[
            components["image_conv_image_label"],
            components["radio_conv_modeling_mode"],
        ],
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
        lang_val,
    ):
        if modeling_mode in (None, ""):
            return (
                _preview_update(None),
                None,
                I18n.get("conv_err_modeling_mode_required", lang_val),
            )

        if color_mode in (None, ""):
            return (
                _preview_update(None),
                None,
                I18n.get("conv_err_color_mode_required", lang_val),
            )

        try:
            parsed_color_mode = ColorMode(color_mode)
        except Exception:
            return (
                _preview_update(None),
                None,
                I18n.get("conv_err_color_mode_required", lang_val),
            )

        is_hifi_mode = modeling_mode in (
            ModelingMode.HIGH_FIDELITY,
            ModelingMode.HIGH_FIDELITY.value,
        )
        if match_strategy in (None, "") and is_hifi_mode:
            return (
                _preview_update(None),
                None,
                I18n.get("conv_err_match_strategy_required", lang_val),
            )

        try:
            parsed_modeling_mode = ModelingMode(modeling_mode)
        except Exception:
            return (
                _preview_update(None),
                None,
                I18n.get("conv_err_modeling_mode_invalid", lang_val),
            )

        try:
            parsed_match_strategy = MatchStrategy(match_strategy)
        except Exception:
            return (
                _preview_update(None),
                None,
                I18n.get("conv_err_match_strategy_invalid", lang_val),
            )

        request = ConversionRequest(
            lut_path=lut_path,
            target_width_mm=target_width_mm,
            auto_bg=auto_bg,
            bg_tol=bg_tol,
            color_mode=parsed_color_mode,
            modeling_mode=parsed_modeling_mode,
            quantize_colors=quantize_colors,
            match_strategy=parsed_match_strategy,
        )
        display, cache, status = generate_preview_cached(image_path, request)
        return _preview_update(display), cache, resolve_i18n_text(status, lang_val)

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
                lang_state,
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
        lang_val,
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
        return _preview_update(display), resolve_i18n_text(status, lang_val)

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
            lang_state,
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
    def on_preview_click_sync_ui(cache, lang_val, evt: gr.SelectData):
        img, display_text, hex_val, msg = on_preview_click_select_color(cache, evt)
        resolved_msg = resolve_i18n_text(msg, lang_val)
        if hex_val is None:
            return _preview_update(img), gr.update(), gr.update(), resolved_msg
        # conv_selected_display is a ColorPicker, so it must receive hex color value.
        return _preview_update(img), hex_val, hex_val, resolved_msg

    conv_preview.select(
        fn=on_preview_click_sync_ui,
        inputs=[conv_preview_cache, lang_state],
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

    def on_remove_loop_i18n(lang_val):
        loop_pos_val, loop_enable_val, loop_angle_val, loop_info_val = on_remove_loop()
        return (
            loop_pos_val,
            loop_enable_val,
            loop_angle_val,
            resolve_i18n_text(loop_info_val, lang_val),
        )

    components["btn_conv_loop_remove"].click(
        on_remove_loop_i18n,
        inputs=[lang_state],
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
            lang_state,
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
        is_hifi = modeling_mode in (
            ModelingMode.HIGH_FIDELITY,
            ModelingMode.HIGH_FIDELITY.value,
        )
        return gr.update(interactive=is_hifi)

    components["radio_conv_modeling_mode"].change(
        fn=update_match_strategy_visibility,
        inputs=[components["radio_conv_modeling_mode"]],
        outputs=[components["radio_conv_match_strategy"]],
    )

    return components
