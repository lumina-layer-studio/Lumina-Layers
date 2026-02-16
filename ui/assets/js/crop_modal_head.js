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

    function updatePaletteSelectionVisual(token) {
        var selected = (token || '').toLowerCase();

        document.querySelectorAll('.palette-swatch').forEach(function(el) {
            el.style.outline = 'none';
            el.style.outlineOffset = '0px';
        });

        document.querySelectorAll('.palette-applied-item').forEach(function(el) {
            el.style.border = '1px solid #eee';
            el.style.boxShadow = 'none';
            var itemToken = (el.getAttribute('data-color') || '').toLowerCase();
            if (itemToken && selected && itemToken === selected) {
                el.style.border = '2px solid #2196F3';
                el.style.boxShadow = '0 0 0 1px rgba(33,150,243,0.2)';
            }
        });

        document.querySelectorAll('.palette-swatch').forEach(function(el) {
            var swatchToken = (el.getAttribute('data-color') || '').toLowerCase();
            if (swatchToken && selected && swatchToken === selected) {
                el.style.outline = '3px solid #2196F3';
                el.style.outlineOffset = '2px';
            }
        });
    }

    function applyPaletteSelection(hexColor) {
        if (!hexColor) return;

        console.log('[Palette] Color clicked:', hexColor);

        updateGradioTextbox('conv-color-selected-hidden', hexColor);
        updateGradioTextbox('conv-highlight-color-hidden', hexColor);

        updatePaletteSelectionVisual(hexColor);

        setTimeout(function() {
            window.clickGradioButton('conv-color-trigger-btn');
            window.clickGradioButton('conv-highlight-trigger-btn');
        }, 50);
    }

    // Handle palette swatch click
    function handlePaletteSwatchClick(e) {
        var swatch = e.target.closest('.palette-swatch');
        if (!swatch) return;
        
        var hexColor = swatch.getAttribute('data-color');
        if (!hexColor) return;

        applyPaletteSelection(hexColor);
    }

    function handleAppliedItemClick(e) {
        var item = e.target.closest('.palette-applied-item');
        if (!item) return;

        var hexColor = item.getAttribute('data-color');
        if (!hexColor) return;

        applyPaletteSelection(hexColor);
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
        if (e.target.closest('.palette-applied-item')) {
            handleAppliedItemClick(e);
            return;
        }

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
