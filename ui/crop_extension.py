"""
Lumina Studio - Image Crop Extension
Non-invasive crop functionality extension for the converter tab.

This module provides image cropping capabilities without modifying the core layout files.
It uses a decorator pattern to wrap the original create_app function.
"""

from core.i18n import I18n
from ui.assets import load_template_text


CROP_MODAL_HTML_TEMPLATE = load_template_text("crop_modal.html")
CROP_MODAL_CSS_TEMPLATE = load_template_text("crop_modal.css")
CROP_MODAL_HEAD_HTML = load_template_text("crop_modal_head.html")


def get_crop_modal_html(lang: str) -> dict[str, str]:
    """Return crop-modal template value payload for the given language."""
    return {
        "title": I18n.get("crop_title", lang),
        "original_size": I18n.get("crop_original_size", lang),
        "selection_size": I18n.get("crop_selection_size", lang),
        "label_x": I18n.get("crop_x", lang),
        "label_y": I18n.get("crop_y", lang),
        "label_w": I18n.get("crop_width", lang),
        "label_h": I18n.get("crop_height", lang),
        "btn_use_original": I18n.get("crop_use_original", lang),
        "btn_confirm": I18n.get("crop_confirm", lang),
        "crop_preview_alt": I18n.get("crop_preview_alt", lang),
    }


def get_crop_head_html() -> str:
    """Return head HTML code (contains script) for crop modal features."""
    return CROP_MODAL_HEAD_HTML
