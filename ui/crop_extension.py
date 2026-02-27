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
    title = I18n.get('crop_title', lang)
    original_size = I18n.get('crop_original_size', lang)
    selection_size = I18n.get('crop_selection_size', lang)
    label_x = I18n.get('crop_x', lang)
    label_y = I18n.get('crop_y', lang)
    label_w = I18n.get('crop_width', lang)
    label_h = I18n.get('crop_height', lang)
    btn_use_original = I18n.get('crop_use_original', lang)
    btn_confirm = I18n.get('crop_confirm', lang)
    lbl_ratio = '比例预设 | Ratio' if lang == 'zh' else 'Aspect Ratio'
    lbl_free = '自由' if lang == 'zh' else 'Free'

    template = """
<script src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.7.1/jquery.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.1/cropper.min.js"></script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.1/cropper.min.css">
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
.crop-ratio-bar {{ display: flex; align-items: center; gap: 8px; margin: 10px 0; flex-wrap: wrap; }}
.crop-ratio-bar span.crop-ratio-label {{ font-size: 13px; color: var(--body-text-color-subdued, #666); margin-right: 4px; }}
.crop-ratio-btn {{ padding: 5px 12px !important; border: 1px solid var(--border-color-primary, #ddd) !important; border-radius: 6px !important; background: var(--background-fill-secondary, #f0f0f0) !important; color: var(--body-text-color, #333) !important; cursor: pointer !important; font-size: 12px !important; transition: all 0.15s !important; }}
.crop-ratio-btn:hover {{ background: var(--background-fill-tertiary, #e0e0e0) !important; }}
.crop-ratio-btn.active {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important; color: white !important; border-color: transparent !important; }}
.crop-inputs {{ display: flex; gap: 15px; margin: 15px 0; flex-wrap: wrap; }}
.crop-input-group {{ display: flex; flex-direction: column; gap: 5px; }}
.crop-input-group label {{ font-size: 12px; color: var(--body-text-color-subdued, #666); }}
.crop-input-group input {{ width: 80px !important; padding: 8px 12px !important; border: 1px solid var(--border-color-primary, #ddd) !important; background: var(--background-fill-primary, white) !important; color: var(--body-text-color, #333) !important; border-radius: 4px !important; font-size: 14px !important; box-sizing: border-box !important; }}
.crop-modal-buttons {{ display: flex; gap: 10px; justify-content: flex-end; margin-top: 15px; padding-top: 15px; border-top: 1px solid var(--border-color-primary, #eee); }}
#crop-modal button.crop-btn {{ padding: 10px 20px !important; border: none !important; border-radius: 6px !important; cursor: pointer !important; font-size: 14px !important; transition: all 0.2s !important; font-weight: 400 !important; text-align: center !important; display: inline-block !important; min-width: 80px !important; }}
#crop-modal button.crop-btn-secondary {{ background: var(--background-fill-secondary, #f0f0f0) !important; color: var(--body-text-color, #333) !important; }}
#crop-modal button.crop-btn-secondary:hover {{ background: var(--background-fill-tertiary, #e0e0e0) !important; }}
#crop-modal button.crop-btn-primary {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important; color: white !important; }}
#crop-modal button.crop-btn-primary:hover {{ opacity: 0.9 !important; }}
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
        <div class="crop-ratio-bar">
            <span class="crop-ratio-label">{lbl_ratio}:</span>
            <button class="crop-ratio-btn active" onclick="window.setCropRatio(NaN, this)">{lbl_free}</button>
            <button class="crop-ratio-btn" onclick="window.setCropRatio(1/1, this)">1:1</button>
            <button class="crop-ratio-btn" onclick="window.setCropRatio(4/3, this)">4:3</button>
            <button class="crop-ratio-btn" onclick="window.setCropRatio(3/2, this)">3:2</button>
            <button class="crop-ratio-btn" onclick="window.setCropRatio(16/9, this)">16:9</button>
            <button class="crop-ratio-btn" onclick="window.setCropRatio(9/16, this)">9:16</button>
            <button class="crop-ratio-btn" onclick="window.setCropRatio(3/4, this)">3:4</button>
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
<script>
window.cropper = null;
window.originalImageData = null;

function hideCropHelperComponents() {{
    ['crop-data-json', 'use-original-hidden-btn', 'confirm-crop-hidden-btn'].forEach(function(id) {{
        var el = document.getElementById(id);
        if (el) {{
            el.style.cssText = 'position:absolute!important;left:-9999px!important;top:-9999px!important;width:1px!important;height:1px!important;overflow:hidden!important;opacity:0!important;visibility:hidden!important;';
        }}
    }});
}}
document.addEventListener('DOMContentLoaded', function() {{ setTimeout(hideCropHelperComponents, 500); }});
setInterval(hideCropHelperComponents, 2000);

window.updateCropDataJson = function(x, y, w, h) {{
    var jsonData = JSON.stringify({{x: x, y: y, w: w, h: h}});
    var container = document.getElementById('crop-data-json');
    if (!container) {{
        console.error('crop-data-json element not found');
        return;
    }}
    var textarea = container.querySelector('textarea');
    if (textarea) {{
        textarea.value = jsonData;
        textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
        textarea.dispatchEvent(new Event('change', {{ bubbles: true }}));
        console.log('Updated crop data JSON:', jsonData);
    }} else {{
        console.error('textarea not found in crop-data-json');
    }}
}};

window.clickGradioButton = function(elemId) {{
    var elem = document.getElementById(elemId);
    if (!elem) {{
        console.error('clickGradioButton: element not found:', elemId);
        return;
    }}
    var btn = elem.querySelector('button') || elem;
    if (btn && btn.tagName === 'BUTTON') {{
        btn.click();
        console.log('Clicked button:', elemId);
    }} else {{
        console.error('Button element not found for:', elemId);
    }}
}};

window.openCropModal = function(imageSrc, width, height) {{
    console.log('openCropModal called:', imageSrc ? imageSrc.substring(0, 50) + '...' : 'null', width, height);
    window.originalImageData = {{ src: imageSrc, width: width, height: height }};
    
    // Reset ratio buttons
    document.querySelectorAll('.crop-ratio-btn').forEach(function(b) {{ b.classList.remove('active'); }});
    var freeBtn = document.querySelector('.crop-ratio-btn');
    if (freeBtn) freeBtn.classList.add('active');
    
    var origSizeEl = document.getElementById('crop-original-size');
    if (origSizeEl) {{
        var prefix = origSizeEl.dataset.prefix || 'Size';
        origSizeEl.textContent = prefix + ': ' + width + ' × ' + height + ' px';
    }}
    
    var img = document.getElementById('crop-image');
    if (!img) {{ console.error('crop-image element not found'); return; }}
    img.src = imageSrc;
    
    var overlay = document.getElementById('crop-modal-overlay');
    if (overlay) overlay.style.display = 'flex';
    
    img.onload = function() {{
        if (window.cropper) window.cropper.destroy();
        window.cropper = new Cropper(img, {{
            viewMode: 1, dragMode: 'crop', autoCropArea: 1, responsive: true,
            crop: function(event) {{
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
                if (selSize) {{
                    var prefix = selSize.dataset.prefix || 'Selection';
                    selSize.textContent = prefix + ': ' + Math.round(data.width) + ' × ' + Math.round(data.height) + ' px';
                }}
            }}
        }});
    }};
}};

window.setCropRatio = function(ratio, btn) {{
    if (!window.cropper) return;
    document.querySelectorAll('.crop-ratio-btn').forEach(function(b) {{ b.classList.remove('active'); }});
    if (btn) btn.classList.add('active');
    window.cropper.setAspectRatio(ratio);
}};

window.closeCropModal = function() {{
    var overlay = document.getElementById('crop-modal-overlay');
    if (overlay) overlay.style.display = 'none';
    if (window.cropper) {{ window.cropper.destroy(); window.cropper = null; }}
}};

window.updateCropperFromInputs = function() {{
    if (!window.cropper) return;
    window.cropper.setData({{
        x: parseInt(document.getElementById('crop-x').value) || 0,
        y: parseInt(document.getElementById('crop-y').value) || 0,
        width: parseInt(document.getElementById('crop-width').value) || 100,
        height: parseInt(document.getElementById('crop-height').value) || 100
    }});
}};

window.useOriginalImage = function() {{
    if (!window.originalImageData) return;
    var w = window.originalImageData.width;
    var h = window.originalImageData.height;
    window.updateCropDataJson(0, 0, w, h);
    window.closeCropModal();
    setTimeout(function() {{ window.clickGradioButton('use-original-hidden-btn'); }}, 100);
}};

window.confirmCrop = function() {{
    if (!window.cropper) return;
    var data = window.cropper.getData(true);
    console.log('confirmCrop data:', data);
    window.updateCropDataJson(Math.round(data.x), Math.round(data.y), Math.round(data.width), Math.round(data.height));
    window.closeCropModal();
    setTimeout(function() {{ window.clickGradioButton('confirm-crop-hidden-btn'); }}, 100);
}};

console.log('Crop modal JS loaded, openCropModal:', typeof window.openCropModal);
</script>
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
        lbl_ratio=lbl_ratio,
        lbl_free=lbl_free,
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

/* LUT swatch breathing highlight animation */
@keyframes lutBreathing {
    0%   { outline: 3px solid rgba(255, 87, 34, 0.9); outline-offset: 2px; }
    50%  { outline: 6px solid rgba(255, 87, 34, 0.3); outline-offset: 4px; }
    100% { outline: 3px solid rgba(255, 87, 34, 0.9); outline-offset: 2px; }
}
.lut-color-swatch.lut-highlight {
    animation: lutBreathing 0.7s ease-in-out 3;
    z-index: 10;
    position: relative;
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
    
    // Reset ratio buttons
    document.querySelectorAll('.crop-ratio-btn').forEach(function(b) { b.classList.remove('active'); });
    var freeBtn = document.querySelector('.crop-ratio-btn');
    if (freeBtn) freeBtn.classList.add('active');
    
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

window.setCropRatio = function(ratio, btn) {
    if (!window.cropper) return;
    document.querySelectorAll('.crop-ratio-btn').forEach(function(b) { b.classList.remove('active'); });
    if (btn) btn.classList.add('active');
    window.cropper.setAspectRatio(ratio);
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
    // ═══════════════════════════════════════════════════════════════
    // Unified dispatchers: auto-detect swatch vs card mode
    // ═══════════════════════════════════════════════════════════════
    function _isCardMode() {
        // Card mode uses bare .lut-color-swatch without .lut-color-swatch-container
        return document.querySelectorAll('.lut-color-swatch-container').length === 0;
    }

    // Search dispatcher
    window.lutSearchDispatch = function(val) {
        if (_isCardMode()) {
            window.lutCardSearch(val);
        } else {
            window.lutSmartSearch(val);
        }
    };

    // Hue dispatcher
    window.lutHueDispatch = function(hueKey, btnEl) {
        // Update button styles
        document.querySelectorAll('.lut-hue-btn').forEach(function(b) {
            b.style.background = '#f5f5f5'; b.style.color = '#333'; b.style.borderColor = '#ccc';
        });
        if (btnEl) { btnEl.style.background = '#333'; btnEl.style.color = '#fff'; btnEl.style.borderColor = '#333'; }
        // Clear search
        var searchBox = document.getElementById('lut-color-search');
        if (searchBox) searchBox.value = '';

        if (hueKey === 'fav') {
            // Show only favorites
            var favs = window._lutFavorites || {};
            if (_isCardMode()) {
                var swatches = document.querySelectorAll('.lut-color-swatch');
                var cnt = 0;
                swatches.forEach(function(s) {
                    if (favs[s.getAttribute('data-color')]) { s.style.opacity = '1'; cnt++; }
                    else { s.style.opacity = '0.12'; }
                });
                var ce = document.getElementById('lut-color-visible-count');
                if (ce) ce.textContent = cnt;
            } else {
                var containers = document.querySelectorAll('.lut-color-swatch-container');
                var cnt = 0;
                containers.forEach(function(c) {
                    var sw = c.querySelector('.lut-color-swatch');
                    if (sw && favs[sw.getAttribute('data-color')]) { c.style.display = 'flex'; cnt++; }
                    else { c.style.display = 'none'; }
                });
                var ce = document.getElementById('lut-color-visible-count');
                if (ce) ce.textContent = cnt;
            }
            return;
        }

        if (_isCardMode()) {
            // Card mode: dim non-matching
            var swatches = document.querySelectorAll('.lut-color-swatch');
            var cnt = 0;
            swatches.forEach(function(s) {
                if (hueKey === 'all' || s.getAttribute('data-hue') === hueKey) { s.style.opacity = '1'; cnt++; }
                else { s.style.opacity = '0.12'; }
            });
            var ce = document.getElementById('lut-color-visible-count');
            if (ce) ce.textContent = cnt;
        } else {
            // Swatch mode: hide non-matching
            var containers = document.querySelectorAll('.lut-color-swatch-container');
            var cnt = 0;
            containers.forEach(function(c) {
                var h = c.getAttribute('data-hue');
                if (hueKey === 'all' || h === hueKey) { c.style.display = 'flex'; cnt++; }
                else { c.style.display = 'none'; }
            });
            var ce = document.getElementById('lut-color-visible-count');
            if (ce) ce.textContent = cnt;
        }
    };

    // Keep backward compat
    window.lutFilterByHue = window.lutHueDispatch;
    window.lutCardFilterByHue = window.lutHueDispatch;

    // LUT color smart search (swatch mode): supports hex, partial hex, RGB
    window.lutSmartSearch = function(searchValue) {
        var query = searchValue.trim().toLowerCase();
        var containers = document.querySelectorAll('.lut-color-swatch-container');
        var visibleCount = 0;
        var firstMatch = null;

        var rgbMatch = query.match(/^(\d{1,3})\s*[,\s]\s*(\d{1,3})\s*[,\s]\s*(\d{1,3})$/);
        var rgbHex = null;
        if (rgbMatch) {
            var r = Math.min(255, parseInt(rgbMatch[1]));
            var g = Math.min(255, parseInt(rgbMatch[2]));
            var b = Math.min(255, parseInt(rgbMatch[3]));
            rgbHex = ('0'+r.toString(16)).slice(-2) + ('0'+g.toString(16)).slice(-2) + ('0'+b.toString(16)).slice(-2);
        }
        var hexQuery = query.replace('#', '');

        containers.forEach(function(container) {
            var swatch = container.querySelector('.lut-color-swatch');
            if (!swatch) return;
            var color = swatch.getAttribute('data-color').toLowerCase().replace('#', '');
            var match = query === '' || (rgbHex ? color === rgbHex : color.includes(hexQuery));
            if (match) { container.style.display = 'flex'; visibleCount++; if (!firstMatch) firstMatch = swatch; }
            else { container.style.display = 'none'; }
        });
        var countEl = document.getElementById('lut-color-visible-count');
        if (countEl) countEl.textContent = visibleCount;
        if (firstMatch && query !== '') window.lutScrollAndHighlight(firstMatch);
    };

    // Card mode search: dim non-matching (preserve grid layout)
    window.lutCardSearch = function(searchValue) {
        var query = searchValue.trim().toLowerCase().replace('#', '');
        var swatches = document.querySelectorAll('.lut-color-swatch');
        var visibleCount = 0;
        var firstMatch = null;

        var rgbMatch = query.match(/^(\d{1,3})\s*[,\s]\s*(\d{1,3})\s*[,\s]\s*(\d{1,3})$/);
        var rgbHex = null;
        if (rgbMatch) {
            var r = Math.min(255, parseInt(rgbMatch[1]));
            var g = Math.min(255, parseInt(rgbMatch[2]));
            var b = Math.min(255, parseInt(rgbMatch[3]));
            rgbHex = ('0'+r.toString(16)).slice(-2) + ('0'+g.toString(16)).slice(-2) + ('0'+b.toString(16)).slice(-2);
        }

        swatches.forEach(function(swatch) {
            var color = swatch.getAttribute('data-color').toLowerCase().replace('#', '');
            var match = query === '' || (rgbHex ? color === rgbHex : color.includes(query));
            if (match) { swatch.style.opacity = '1'; visibleCount++; if (!firstMatch && query !== '') firstMatch = swatch; }
            else { swatch.style.opacity = '0.15'; }
        });
        var countEl = document.getElementById('lut-color-visible-count');
        if (countEl) countEl.textContent = visibleCount;
        if (firstMatch) window.lutScrollAndHighlight(firstMatch);
    };

    // Keep backward compat
    window.filterLutColors = window.lutSmartSearch;

    // Scroll to a swatch and add breathing highlight animation
    window.lutScrollAndHighlight = function(swatchEl) {
        if (!swatchEl) return;
        swatchEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
        // Remove previous highlights
        document.querySelectorAll('.lut-color-swatch.lut-highlight').forEach(function(el) {
            el.classList.remove('lut-highlight');
        });
        swatchEl.classList.add('lut-highlight');
        // Remove after animation
        setTimeout(function() { swatchEl.classList.remove('lut-highlight'); }, 2000);
    };

    // Hue filter: show/hide swatches by data-hue attribute
    window._lutActiveHue = 'all';
    window.lutFilterByHue = function(hueKey, btnEl) {
        window._lutActiveHue = hueKey;
        // Update button styles
        document.querySelectorAll('.lut-hue-btn').forEach(function(b) {
            b.style.background = '#f5f5f5';
            b.style.color = '#333';
            b.style.borderColor = '#ccc';
        });
        if (btnEl) {
            btnEl.style.background = '#333';
            btnEl.style.color = '#fff';
            btnEl.style.borderColor = '#333';
        }
        // Filter containers
        var containers = document.querySelectorAll('.lut-color-swatch-container');
        var visibleCount = 0;
        containers.forEach(function(container) {
            var containerHue = container.getAttribute('data-hue');
            if (hueKey === 'all' || containerHue === hueKey) {
                container.style.display = 'flex';
                visibleCount++;
            } else {
                container.style.display = 'none';
            }
        });
        var countEl = document.getElementById('lut-color-visible-count');
        if (countEl) countEl.textContent = visibleCount;
        // Clear search box when switching hue
        var searchBox = document.getElementById('lut-color-search');
        if (searchBox) searchBox.value = '';
    };

    // Color picker nearest match: called from Gradio backend, scrolls to matched swatch
    window.lutScrollToColor = function(hexColor) {
        if (!hexColor) return;
        var target = hexColor.toLowerCase();
        var swatches = document.querySelectorAll('.lut-color-swatch');
        for (var i = 0; i < swatches.length; i++) {
            if (swatches[i].getAttribute('data-color').toLowerCase() === target) {
                // Reset hue filter to show all
                var allBtn = document.querySelector('.lut-hue-btn[data-hue="all"]');
                if (allBtn) {
                    if (window.lutFilterByHue) window.lutFilterByHue('all', allBtn);
                    else if (window.lutCardFilterByHue) window.lutCardFilterByHue('all', allBtn);
                }
                // Clear search
                var searchBox = document.getElementById('lut-color-search');
                if (searchBox) searchBox.value = '';
                // Scroll and highlight
                window.lutScrollAndHighlight(swatches[i]);
                // Simulate click to select
                swatches[i].click();
                return;
            }
        }
    };

    // ═══════════════════════════════════════════════════════════════
    // Favorites: double-click swatch to toggle, persisted per LUT
    // ═══════════════════════════════════════════════════════════════
    window._lutFavorites = {};  // { '#hexcolor': true }
    window._lutCurrentLutKey = '';

    // Load favorites from localStorage for a given LUT key
    window.lutLoadFavorites = function(lutKey) {
        window._lutCurrentLutKey = lutKey || '';
        try {
            var stored = localStorage.getItem('lut_favorites_' + lutKey);
            window._lutFavorites = stored ? JSON.parse(stored) : {};
        } catch(e) { window._lutFavorites = {}; }
        window._lutApplyFavStars();
    };

    // Save favorites to localStorage
    window._lutSaveFavorites = function() {
        try {
            localStorage.setItem('lut_favorites_' + window._lutCurrentLutKey, JSON.stringify(window._lutFavorites));
        } catch(e) {}
    };

    // Apply star overlays to all favorited swatches
    window._lutApplyFavStars = function() {
        document.querySelectorAll('.lut-color-swatch').forEach(function(s) {
            var hex = s.getAttribute('data-color');
            var star = s.querySelector('.lut-fav-star');
            if (window._lutFavorites[hex]) {
                if (!star) {
                    star = document.createElement('span');
                    star.className = 'lut-fav-star';
                    star.textContent = '⭐';
                    star.style.cssText = 'position:absolute;top:-2px;right:-2px;font-size:8px;pointer-events:none;';
                    s.style.position = 'relative';
                    s.style.overflow = 'visible';
                    s.appendChild(star);
                }
            } else if (star) {
                star.remove();
            }
        });
    };

    // Toggle favorite on double-click
    document.addEventListener('dblclick', function(e) {
        var swatch = e.target.closest('.lut-color-swatch');
        if (!swatch) return;
        var hex = swatch.getAttribute('data-color');
        if (!hex) return;
        if (window._lutFavorites[hex]) {
            delete window._lutFavorites[hex];
        } else {
            window._lutFavorites[hex] = true;
        }
        window._lutSaveFavorites();
        window._lutApplyFavStars();
    }, true);

    // ═══════════════════════════════════════════════════════════════
    // MutationObserver: auto-load favorites when grid re-renders
    // ═══════════════════════════════════════════════════════════════
    (function _initGridObserver() {
        function _onGridChange() {
            var container = document.getElementById('lut-color-grid-container');
            if (!container) return;
            var lutKey = container.getAttribute('data-lut-key') || '';
            if (lutKey) {
                window.lutLoadFavorites(lutKey);
            } else {
                window._lutApplyFavStars();
            }
        }
        // Observe the Gradio app root for subtree changes (grid is re-rendered by Gradio)
        var _gridObsTimer = null;
        var obs = new MutationObserver(function(mutations) {
            // Debounce: grid re-render may trigger many mutations
            if (_gridObsTimer) clearTimeout(_gridObsTimer);
            _gridObsTimer = setTimeout(function() {
                // Check if any mutation involves the grid container
                for (var i = 0; i < mutations.length; i++) {
                    var m = mutations[i];
                    if (m.type === 'childList') {
                        for (var j = 0; j < m.addedNodes.length; j++) {
                            var node = m.addedNodes[j];
                            if (node.nodeType === 1 && (node.id === 'lut-color-grid-container' || (node.querySelector && node.querySelector('#lut-color-grid-container')))) {
                                _onGridChange();
                                return;
                            }
                        }
                    }
                }
            }, 150);
        });
        // Start observing once DOM is ready
        function _startObs() {
            var root = document.querySelector('.gradio-container') || document.body;
            obs.observe(root, { childList: true, subtree: true });
            // Also run once on init in case grid is already rendered
            setTimeout(_onGridChange, 500);
        }
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', _startObs);
        } else {
            _startObs();
        }
    })();
    
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
