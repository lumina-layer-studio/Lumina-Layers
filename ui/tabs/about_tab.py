"""
Lumina Studio - About Tab
About page and settings UI
"""

import gradio as gr

from core.i18n import I18n
from utils import Stats


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
