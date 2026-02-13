"""
Lumina Studio - Image Crop Extension
Non-invasive crop functionality extension for the converter tab.

This module provides image cropping capabilities without modifying the core layout files.
It uses a decorator pattern to wrap the original create_app function.
"""

import gradio as gr
from core.i18n import I18n
from core.image_preprocessor import ImagePreprocessor
from .asset_loader import load_asset_text


def get_crop_modal_html(lang: str) -> str:
    """Return the crop modal HTML for the given language."""
    title = I18n.get("crop_title", lang)
    original_size = I18n.get("crop_original_size", lang)
    selection_size = I18n.get("crop_selection_size", lang)
    label_x = I18n.get("crop_x", lang)
    label_y = I18n.get("crop_y", lang)
    label_w = I18n.get("crop_width", lang)
    label_h = I18n.get("crop_height", lang)
    btn_use_original = I18n.get("crop_use_original", lang)
    btn_confirm = I18n.get("crop_confirm", lang)
    crop_preview_alt = I18n.get("crop_preview_alt", lang)
    crop_modal_css = load_asset_text("css", "crop_modal.css")

    # Cropper.js Modal HTML (CSS only, JS is loaded via head parameter in main.py)
    template = """
<style>
{crop_modal_css}
</style>
<div id="crop-modal-overlay">
    <div id="crop-modal">
        <div class="crop-modal-header">
            <h3>{title}</h3>
            <button class="crop-modal-close" onclick="window.closeCropModal()">&times;</button>
        </div>
        <div class="crop-image-container"><img id="crop-image" src="" alt="{crop_preview_alt}"></div>
        <div class="crop-info-bar">
            <span id="crop-original-size" data-prefix="{original_size}">{original_size}: -- × -- px</span>
            <span id="crop-selection-size" data-prefix="{selection_size}">{selection_size}: -- × -- px</span>
        </div>
        <div class="crop-inputs">
            <div class="crop-input-group"><label>{label_x}</label><input type="number" id="crop-x" value="0" min="0" oninput="window.updateCropperFromInputs()"></div>
            <div class="crop-input-group"><label>{label_y}</label><input type="number" id="crop-y" value="0" min="0" oninput="window.updateCropperFromInputs()"></div>
            <div class="crop-input-group"><label>{label_w}</label><input type="number" id="crop-width" value="100" min="1" oninput="window.updateCropperFromInputs()"></div>
            <div class="crop-input-group"><label>{label_h}</label><input type="number" id="crop-height" value="100" min="1" oninput="window.updateCropperFromInputs()"></div>
        </div>
        <div class="crop-modal-buttons">
            <button class="crop-btn crop-btn-secondary" onclick="window.useOriginalImage()">{btn_use_original}</button>
            <button class="crop-btn crop-btn-primary" onclick="window.confirmCrop()">{btn_confirm}</button>
        </div>
    </div>
</div>
"""
    return template.format(
        title=title,
        original_size=original_size,
        selection_size=selection_size,
        label_x=label_x,
        label_y=label_y,
        label_w=label_w,
        label_h=label_h,
        btn_use_original=btn_use_original,
        btn_confirm=btn_confirm,
        crop_preview_alt=crop_preview_alt,
        crop_modal_css=crop_modal_css,
    )


# JavaScript for Cropper.js (to be injected via head parameter)
CROP_MODAL_JS = load_asset_text("js", "crop_modal_head.js")


def get_crop_head_js():
    """Return the JavaScript code to be injected via head parameter."""
    return CROP_MODAL_JS
