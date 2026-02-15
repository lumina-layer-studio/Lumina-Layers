"""
Lumina Studio - UI Layout (Refactored with i18n)
UI layout definition - Refactored version with language switching support
"""

import gradio as gr

from config import ColorMode, ModelingMode, StructureMode, MatchStrategy
from core.calibration import (
    generate_calibration_board,
    generate_smart_board,
    generate_8color_batch_zip,
)
from core.i18n import I18n
from ui.converter_ui import generate_lut_grid_html
from utils import Stats
from .callbacks import (
    on_lut_select,
)
from .tabs import calibration_tab as _calibration_tab
from .tabs import converter_tab as _converter_tab
from .tabs import (
    create_converter_tab_content,
    create_calibration_tab_content,
    create_extractor_tab_content,
    create_about_tab_content,
)
from .tabs import extractor_tab as _extractor_tab

# CSS/JS constants moved to ui/layout_css.py and ui/layout_js.py

CONFIG_FILE = "user_settings.json"


def load_last_lut_setting():
    """Compatibility wrapper for legacy helper import path."""
    _converter_tab.CONFIG_FILE = CONFIG_FILE
    return _converter_tab.load_last_lut_setting()


def save_last_lut_setting(lut_name):
    """Compatibility wrapper for legacy helper import path."""
    _converter_tab.CONFIG_FILE = CONFIG_FILE
    return _converter_tab.save_last_lut_setting(lut_name)


def _get_image_size(img):
    """Compatibility wrapper for legacy helper import path."""
    return _converter_tab._get_image_size(img)


get_extractor_reference_image = _extractor_tab.get_extractor_reference_image


process_batch_generation = _converter_tab.process_batch_generation


# ============================================================================
# Image Dimension Helper Functions
# NOTE: Moved to converter_tab.py
# ============================================================================


def create_app():
    """Build the Gradio app (tabs, i18n, events) and return the Blocks instance."""

    with gr.Blocks(title="Lumina Studio") as app:
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
                lang_btn = gr.Button(
                    value=I18n.get("lang_btn_en", "zh"), size="sm", elem_id="lang-btn"
                )
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
            inputs=[components["dropdown_conv_lut_dropdown"], lang_state],
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
                                I18n.get("color_mode_bw", lang),
                                ColorMode.BW.value,
                            ),
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
                    )
                )
            elif choice_key == "conv_structure":
                updates.append(
                    gr.update(
                        label=I18n.get(choice_key, lang),
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
                    )
                )
            elif choice_key == "conv_match_strategy":
                updates.append(
                    gr.update(
                        label=I18n.get("conv_match_strategy", lang),
                        info=I18n.get("conv_match_strategy_info", lang),
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
                    )
                )
            elif choice_key == "ext_page":
                updates.append(
                    gr.update(
                        label=I18n.get("ext_8color_page", lang),
                        choices=[
                            (I18n.get("ext_page_1", lang), "Page 1"),
                            (I18n.get("ext_page_2", lang), "Page 2"),
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
            if dropdown_key == "cal_backing":
                updates.append(
                    gr.update(
                        label=I18n.get("cal_backing", lang),
                        choices=[
                            (I18n.get("backing_white", lang), "White"),
                            (I18n.get("backing_cyan", lang), "Cyan"),
                            (I18n.get("backing_magenta", lang), "Magenta"),
                            (I18n.get("backing_yellow", lang), "Yellow"),
                            (I18n.get("backing_red", lang), "Red"),
                            (I18n.get("backing_blue", lang), "Blue"),
                            (I18n.get("backing_black", lang), "Black"),
                        ],
                    )
                )
            elif info_key in I18n.TEXTS:
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


# ---------- Tab builders ----------
# NOTE: Tab creation functions moved to ui/tabs/*.py
# Functions: create_converter_tab_content, create_calibration_tab_content,
#           create_extractor_tab_content, create_about_tab_content
# ============================================================================


def _format_bytes(size_bytes: int) -> str:
    """Format bytes to human readable string.

    NOTE: Kept in layout_new.py for use by other functions.
    """
    if size_bytes == 0:
        return "0 B"
    size = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
