"""
Lumina Studio - Image Crop Extension
Non-invasive crop functionality extension for the converter tab.

This module provides image cropping capabilities without modifying the core layout files.
It uses a decorator pattern to wrap the original create_app function.
"""

import gradio as gr
from core.i18n import I18n
from core.image_preprocessor import ImagePreprocessor


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

    # Cropper.js Modal HTML (CSS only, JS is loaded via head parameter in main.py)
    template = """
<style>
#crop-modal-overlay {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 9999; justify-content: center; align-items: center; }}
#crop-modal {{ background: var(--background-fill-primary, white); border-radius: 12px; padding: 20px; max-width: 90vw; max-height: 90vh; overflow: auto; box-shadow: 0 10px 40px rgba(0,0,0,0.3); }}
.crop-modal-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; padding-bottom: 10px; border-bottom: 1px solid var(--border-color-primary, #eee); }}
.crop-modal-header h3 {{ margin: 0; color: var(--body-text-color, #333); }}
.crop-modal-close {{ background: none; border: none; font-size: 24px; cursor: pointer; color: var(--body-text-color-subdued, #666); }}
.crop-modal-close:hover {{ color: var(--body-text-color, #333); }}
.crop-image-container {{ max-width: 800px; max-height: 500px; margin: 0 auto; }}
.crop-image-container img {{ max-width: 100%; display: block; }}
.crop-info-bar {{ display: flex; justify-content: space-between; align-items: center; margin: 15px 0; padding: 10px; background: var(--background-fill-secondary, #f5f5f5); border-radius: 6px; font-size: 14px; color: var(--body-text-color, #333); }}
.crop-inputs {{ display: flex; gap: 15px; margin: 15px 0; flex-wrap: wrap; }}
.crop-input-group {{ display: flex; flex-direction: column; gap: 5px; }}
.crop-input-group label {{ font-size: 12px; color: var(--body-text-color-subdued, #666); }}
.crop-input-group input {{ width: 80px; padding: 8px; border: 1px solid var(--border-color-primary, #ddd); background: var(--background-fill-primary, white); color: var(--body-text-color, #333); border-radius: 4px; font-size: 14px; }}
.crop-modal-buttons {{ display: flex; gap: 10px; justify-content: flex-end; margin-top: 15px; padding-top: 15px; border-top: 1px solid var(--border-color-primary, #eee); }}
.crop-btn {{ padding: 10px 20px; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; transition: all 0.2s; }}
.crop-btn-secondary {{ background: var(--background-fill-secondary, #f0f0f0); color: var(--body-text-color, #333); }}
.crop-btn-secondary:hover {{ background: var(--background-fill-tertiary, #e0e0e0); }}
.crop-btn-primary {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; }}
.crop-btn-primary:hover {{ opacity: 0.9; }}
</style>
<div id="crop-modal-overlay">
    <div id="crop-modal">
        <div class="crop-modal-header">
            <h3>{title}</h3>
            <button class="crop-modal-close" onclick="window.closeCropModal()">&times;</button>
        </div>
        <div class="crop-image-container"><img id="crop-image" src="" alt="Crop Preview"></div>
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
    )


# JavaScript for Cropper.js (to be injected via head parameter)
CROP_MODAL_JS = """
<script src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.1/cropper.min.js"></script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.1/cropper.min.css">
<style>
/* Hide crop helper components - injected via head */
#crop-data-json, #use-original-hidden-btn, #confirm-crop-hidden-btn,
.hidden-crop-component {
    position: absolute !important;
    left: -9999px !important;
    top: -9999px !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
    opacity: 0 !important;
    visibility: hidden !important;
}

/* Hidden textbox triggers - small but still in DOM flow for Gradio events */
.hidden-textbox-trigger {
    height: 1px !important;
    min-height: 1px !important;
    max-height: 1px !important;
    overflow: hidden !important;
    opacity: 0.01 !important;
    margin: 0 !important;
    padding: 0 !important;
    border: none !important;
    position: absolute !important;
    left: -9999px !important;
}
.hidden-textbox-trigger textarea,
.hidden-textbox-trigger input,
.hidden-textbox-trigger button {
    height: 1px !important;
    min-height: 1px !important;
    padding: 0 !important;
    margin: 0 !important;
    border: none !important;
}
</style>
<script>
window.cropper = null;
window.originalImageData = null;

// Hide crop helper components on page load
function hideCropHelperComponents() {
    ['crop-data-json', 'use-original-hidden-btn', 'confirm-crop-hidden-btn'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) {
            el.style.cssText = 'position:absolute!important;left:-9999px!important;top:-9999px!important;width:1px!important;height:1px!important;overflow:hidden!important;opacity:0!important;visibility:hidden!important;';
        }
    });
}
document.addEventListener('DOMContentLoaded', function() { setTimeout(hideCropHelperComponents, 500); });
setInterval(hideCropHelperComponents, 2000); // Keep hiding in case Gradio re-renders

// Update hidden Gradio textbox with JSON data
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

// Click a Gradio button by elem_id
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

console.log('Crop modal JS loaded, openCropModal:', typeof window.openCropModal);

// ═══════════════════════════════════════════════════════════════
// Color Palette Click Handler (Global - survives Gradio re-renders)
// ═══════════════════════════════════════════════════════════════

(function() {
    // LUT color search filter function (called from oninput attribute)
    window.filterLutColors = function(searchValue) {
        var query = searchValue.toLowerCase().replace('#', '');
        var containers = document.querySelectorAll('.lut-color-swatch-container');
        var visibleCount = 0;
        containers.forEach(function(container) {
            var swatch = container.querySelector('.lut-color-swatch');
            if (swatch) {
                var color = swatch.getAttribute('data-color').toLowerCase().replace('#', '');
                if (query === '' || color.includes(query)) {
                    container.style.display = 'flex';
                    visibleCount++;
                } else {
                    container.style.display = 'none';
                }
            }
        });
        var countEl = document.getElementById('lut-color-visible-count');
        if (countEl) countEl.textContent = visibleCount;
    };
    
    // Helper function to update Gradio textbox
    function updateGradioTextbox(elemId, value) {
        var container = document.querySelector('#' + elemId);
        if (!container) {
            console.warn('[Palette] Container not found:', elemId);
            return false;
        }
        var input = container.querySelector('textarea, input[type="text"], input');
        if (input) {
            var nativeSetter = Object.getOwnPropertyDescriptor(
                input.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 
                'value'
            );
            if (nativeSetter && nativeSetter.set) {
                nativeSetter.set.call(input, value);
            } else {
                input.value = value;
            }
            input.dispatchEvent(new Event('input', { bubbles: true }));
            input.dispatchEvent(new Event('change', { bubbles: true }));
            console.log('[Palette] Updated textbox:', elemId, 'with value:', value);
            return true;
        }
        console.warn('[Palette] Input not found in container:', elemId);
        return false;
    }
    
    // Handle palette swatch click
    function handlePaletteSwatchClick(e) {
        var swatch = e.target.closest('.palette-swatch');
        if (!swatch) return;
        
        var hexColor = swatch.getAttribute('data-color');
        if (!hexColor) return;
        
        console.log('[Palette] Color clicked:', hexColor);
        
        // Update hidden textboxes
        updateGradioTextbox('conv-color-selected-hidden', hexColor);
        updateGradioTextbox('conv-highlight-color-hidden', hexColor);
        
        // Update visual selection
        document.querySelectorAll('.palette-swatch').forEach(function(el) {
            el.style.outline = 'none';
            el.style.outlineOffset = '0px';
        });
        swatch.style.outline = '3px solid #2196F3';
        swatch.style.outlineOffset = '2px';
        
        // Click hidden buttons to trigger Gradio callbacks
        setTimeout(function() {
            window.clickGradioButton('conv-color-trigger-btn');
            window.clickGradioButton('conv-highlight-trigger-btn');
        }, 50);
    }
    
    // Handle LUT color swatch click
    function handleLutSwatchClick(e) {
        var swatch = e.target.closest('.lut-color-swatch');
        if (!swatch) return;
        
        var hexColor = swatch.getAttribute('data-color');
        if (!hexColor) return;
        
        console.log('[LUT] Color clicked:', hexColor);
        
        // Update hidden textbox
        updateGradioTextbox('conv-lut-color-selected-hidden', hexColor);
        
        // Update visual selection
        document.querySelectorAll('.lut-color-swatch').forEach(function(el) {
            el.style.outline = 'none';
            el.style.outlineOffset = '0px';
        });
        swatch.style.outline = '3px solid #2196F3';
        swatch.style.outlineOffset = '2px';
        
        // Click hidden button to trigger Gradio callback
        setTimeout(function() {
            window.clickGradioButton('conv-lut-color-trigger-btn');
        }, 50);
    }
    
    // Use event delegation on document body - this survives Gradio re-renders
    document.addEventListener('click', function(e) {
        // Check for palette swatch
        if (e.target.closest('.palette-swatch')) {
            handlePaletteSwatchClick(e);
            return;
        }
        // Check for LUT swatch
        if (e.target.closest('.lut-color-swatch')) {
            handleLutSwatchClick(e);
            return;
        }
    }, true);  // Use capture phase to ensure we get the event first
    
    console.log('[Palette] Global click handler installed');
})();
</script>
"""


def get_crop_head_js():
    """Return the JavaScript code to be injected via head parameter."""
    return CROP_MODAL_JS
