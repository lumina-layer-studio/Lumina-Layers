"""
Lumina Studio - Extractor Tab
Color extractor tab UI and event handlers
"""

import os

import gradio as gr
from PIL import Image as PILImage

from core.extractor import (
    rotate_image,
    draw_corner_points,
    run_extraction,
    probe_lut_cell,
    manual_fix_cell,
)
from core.i18n import I18n
from ui.i18n_bridge import resolve_i18n_text
from ui.callbacks import (
    get_first_hint,
    get_next_hint,
    on_extractor_upload,
    on_extractor_mode_change,
    on_extractor_rotate,
    on_extractor_click,
    on_extractor_clear,
    run_extraction_wrapper,
    merge_8color_data,
)


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
        from core.calibration import generate_smart_board, generate_calibration_board

        block_size = 10
        gap = 0
        backing = "White"

        if gen_mode == "6-Color":
            _, img, _ = generate_smart_board(block_size, gap)
        else:
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
                    (
                        I18n.get("color_mode_6color", lang),
                        I18n.get("color_mode_6color", "en"),
                    ),
                    (
                        I18n.get("color_mode_8color", lang),
                        I18n.get("color_mode_8color", "en"),
                    ),
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
                choices=[
                    (I18n.get("ext_page_1", lang), "Page 1"),
                    (I18n.get("ext_page_2", lang), "Page 2"),
                ],
                value="Page 1",
                label=I18n.get("ext_8color_page", lang),
            )

            components["btn_ext_extract_btn"] = gr.Button(
                I18n.get("ext_extract_btn", lang),
                variant="primary",
                elem_classes=["primary-btn"],
            )

            components["btn_ext_merge_btn"] = gr.Button(
                I18n.get("ext_merge_8color", lang),
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
        lambda i, mode: on_extractor_upload(i, mode, lang),
        [ext_img_in, components["radio_ext_color_mode"]],
        [ext_state_img, ext_work_img, ext_state_pts, ext_curr_coord, ext_hint],
    )

    components["radio_ext_color_mode"].change(
        lambda img, mode: on_extractor_mode_change(img, mode, lang),
        [ext_state_img, components["radio_ext_color_mode"]],
        [ext_state_pts, ext_hint, ext_work_img],
    )

    components["radio_ext_color_mode"].change(
        fn=get_extractor_reference_image,
        inputs=[components["radio_ext_color_mode"]],
        outputs=[ext_ref_view],
    )

    components["btn_ext_rotate_btn"].click(
        lambda i, mode: on_extractor_rotate(i, mode, lang),
        [ext_state_img, components["radio_ext_color_mode"]],
        [ext_state_img, ext_work_img, ext_state_pts, ext_hint],
    )

    def on_extractor_click_with_lang(img, pts, mode, evt: gr.SelectData):
        return on_extractor_click(img, pts, mode, evt, lang)

    ext_work_img.select(
        on_extractor_click_with_lang,
        [ext_state_img, ext_state_pts, components["radio_ext_color_mode"]],
        [ext_work_img, ext_state_pts, ext_hint],
    )

    components["btn_ext_reset_btn"].click(
        lambda img, mode: on_extractor_clear(img, mode, lang),
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
        lambda *args: run_extraction_wrapper(*args, lang=lang),
        extract_inputs,
        extract_outputs,
    )
    components["ext_event"] = ext_event

    components["btn_ext_merge_btn"].click(
        lambda: merge_8color_data(lang),
        inputs=[],
        outputs=[components["file_ext_download_npy"], components["textbox_ext_status"]],
    )

    for s in [
        components["slider_ext_offset_x"],
        components["slider_ext_offset_y"],
        components["slider_ext_zoom"],
        components["slider_ext_distortion"],
    ]:
        s.release(
            lambda *args: run_extraction_wrapper(*args, lang=lang),
            extract_inputs,
            extract_outputs,
        )

    def probe_lut_cell_i18n(lut_path, evt: gr.SelectData):
        html, hex_val, coord = probe_lut_cell(lut_path, evt)
        return resolve_i18n_text(html, lang), hex_val, coord

    ext_lut_view.select(
        probe_lut_cell_i18n,
        [components["file_ext_download_npy"]],
        [ext_probe_html, ext_picker, ext_curr_coord],
    )

    def manual_fix_cell_i18n(coord, color_input, lut_path):
        lut_img, status = manual_fix_cell(coord, color_input, lut_path)
        return lut_img, resolve_i18n_text(status, lang)

    components["btn_ext_apply_btn"].click(
        manual_fix_cell_i18n,
        [ext_curr_coord, ext_picker, components["file_ext_download_npy"]],
        [ext_lut_view, components["textbox_ext_status"]],
    )

    return components
