"""
Lumina Studio - Calibration Tab
Calibration board tab UI and event handlers
"""

import gradio as gr

from core.calibration import (
    generate_calibration_board,
    generate_smart_board,
    generate_8color_batch_zip,
)
from core.i18n import I18n
from ui.i18n_bridge import resolve_i18n_text


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
                label=I18n.get("cal_color_mode", lang),
            )

            components["slider_cal_block_size"] = gr.Slider(
                3, 10, 5, step=1, label=I18n.get("cal_block_size", lang)
            )

            components["slider_cal_gap"] = gr.Slider(
                0.4, 2.0, 0.82, step=0.02, label=I18n.get("cal_gap", lang)
            )

            components["dropdown_cal_backing"] = gr.Dropdown(
                choices=[
                    (I18n.get("backing_white", lang), "White"),
                    (I18n.get("backing_cyan", lang), "Cyan"),
                    (I18n.get("backing_magenta", lang), "Magenta"),
                    (I18n.get("backing_yellow", lang), "Yellow"),
                    (I18n.get("backing_red", lang), "Red"),
                    (I18n.get("backing_blue", lang), "Blue"),
                ],
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

            cal_preview = gr.Image(
                label=I18n.get("cal_preview_label", lang), show_label=False
            )

            components["file_cal_download"] = gr.File(
                label=I18n.get("cal_download", lang)
            )

    # Event binding - Call different generator based on mode
    def generate_board_wrapper(color_mode, block_size, gap, backing):
        """Wrapper function to call appropriate generator based on mode"""
        if color_mode == "8-Color Max":
            out, prev, status = generate_8color_batch_zip()
            return out, prev, resolve_i18n_text(status, lang)
        if "6-Color" in color_mode:
            # Call Smart 1296 generator
            out, prev, status = generate_smart_board(block_size, gap)
            return out, prev, resolve_i18n_text(status, lang)
        else:
            # Call traditional 4-color generator
            out, prev, status = generate_calibration_board(
                color_mode, block_size, gap, backing
            )
            return out, prev, resolve_i18n_text(status, lang)

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
