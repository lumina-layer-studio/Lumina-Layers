"""
Lumina Studio - Image Crop Extension
Non-invasive crop functionality extension for the converter tab.
"""

from core.i18n import I18n


def get_crop_modal_html(lang: str) -> str:
    """Return the crop modal markup for the given language."""
    title = I18n.get("crop_title", lang)
    original_size = I18n.get("crop_original_size", lang)
    selection_size = I18n.get("crop_selection_size", lang)
    label_x = I18n.get("crop_x", lang)
    label_y = I18n.get("crop_y", lang)
    label_w = I18n.get("crop_width", lang)
    label_h = I18n.get("crop_height", lang)
    btn_use_original = I18n.get("crop_use_original", lang)
    btn_confirm = I18n.get("crop_confirm", lang)
    lbl_ratio = "比例预设 | Ratio" if lang == "zh" else "Aspect Ratio"
    lbl_free = "自由" if lang == "zh" else "Free"

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


CROP_MODAL_JS = """
<script src="https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.1/cropper.min.js"></script>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.1/cropper.min.css">
<style>
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
(function() {
    if (window.__luminaCropPaletteInit) {
        return;
    }
    window.__luminaCropPaletteInit = true;

    window.cropper = null;
    window.originalImageData = null;
    window._lutFavorites = {};
    window._lutCurrentLutKey = "";
    window._lutActiveHue = "all";

    function setNativeValue(input, value) {
        if (!input) return;
        var proto = input.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
        var descriptor = Object.getOwnPropertyDescriptor(proto, "value");
        if (descriptor && descriptor.set) {
            descriptor.set.call(input, value);
            return;
        }
        input.value = value;
    }

    function updateGradioTextbox(elemId, value) {
        var container = document.getElementById(elemId);
        if (!container) {
            console.warn("[Palette] Container not found:", elemId);
            return false;
        }
        var input = container.querySelector("textarea, input[type='text'], input");
        if (!input) {
            console.warn("[Palette] Input not found in container:", elemId);
            return false;
        }
        setNativeValue(input, value);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        return true;
    }

    window.updateCropDataJson = function(x, y, w, h) {
        var jsonData = JSON.stringify({ x: x, y: y, w: w, h: h });
        updateGradioTextbox("crop-data-json", jsonData);
    };

    window.clickGradioButton = function(elemId) {
        var elem = document.getElementById(elemId);
        if (!elem) {
            console.error("clickGradioButton: element not found:", elemId);
            return;
        }
        var btn = elem.querySelector("button") || elem;
        if (btn && btn.tagName === "BUTTON") {
            btn.click();
            return;
        }
        console.error("Button element not found for:", elemId);
    };

    function resetCropRatioButtons(activeButton) {
        document.querySelectorAll(".crop-ratio-btn").forEach(function(button) {
            button.classList.remove("active");
        });
        if (activeButton) {
            activeButton.classList.add("active");
        }
    }

    window.openCropModal = function(imageSrc, width, height) {
        if (typeof Cropper === "undefined") {
            console.error("Cropper.js is not loaded yet");
            return;
        }

        window.originalImageData = { src: imageSrc, width: width, height: height };
        resetCropRatioButtons(document.querySelector(".crop-ratio-btn"));

        var origSizeEl = document.getElementById("crop-original-size");
        if (origSizeEl) {
            var prefix = origSizeEl.dataset.prefix || "Size";
            origSizeEl.textContent = prefix + ": " + width + " × " + height + " px";
        }

        var img = document.getElementById("crop-image");
        if (!img) {
            console.error("crop-image element not found");
            return;
        }

        img.src = imageSrc;
        var overlay = document.getElementById("crop-modal-overlay");
        if (overlay) {
            overlay.style.display = "flex";
        }

        img.onload = function() {
            if (window.cropper) {
                window.cropper.destroy();
            }
            window.cropper = new Cropper(img, {
                viewMode: 1,
                dragMode: "crop",
                autoCropArea: 1,
                responsive: true,
                crop: function(event) {
                    var data = event.detail;
                    var cropX = document.getElementById("crop-x");
                    var cropY = document.getElementById("crop-y");
                    var cropW = document.getElementById("crop-width");
                    var cropH = document.getElementById("crop-height");
                    var selSize = document.getElementById("crop-selection-size");
                    if (cropX) cropX.value = Math.round(data.x);
                    if (cropY) cropY.value = Math.round(data.y);
                    if (cropW) cropW.value = Math.round(data.width);
                    if (cropH) cropH.value = Math.round(data.height);
                    if (selSize) {
                        var prefix = selSize.dataset.prefix || "Selection";
                        selSize.textContent = prefix + ": " + Math.round(data.width) + " × " + Math.round(data.height) + " px";
                    }
                }
            });
        };
    };

    window.setCropRatio = function(ratio, btn) {
        if (!window.cropper) return;
        resetCropRatioButtons(btn);
        window.cropper.setAspectRatio(ratio);
    };

    window.closeCropModal = function() {
        var overlay = document.getElementById("crop-modal-overlay");
        if (overlay) {
            overlay.style.display = "none";
        }
        if (window.cropper) {
            window.cropper.destroy();
            window.cropper = null;
        }
    };

    window.updateCropperFromInputs = function() {
        if (!window.cropper) return;
        window.cropper.setData({
            x: parseInt(document.getElementById("crop-x").value, 10) || 0,
            y: parseInt(document.getElementById("crop-y").value, 10) || 0,
            width: parseInt(document.getElementById("crop-width").value, 10) || 100,
            height: parseInt(document.getElementById("crop-height").value, 10) || 100
        });
    };

    window.useOriginalImage = function() {
        if (!window.originalImageData) return;
        window.updateCropDataJson(0, 0, window.originalImageData.width, window.originalImageData.height);
        window.closeCropModal();
        setTimeout(function() {
            window.clickGradioButton("use-original-hidden-btn");
        }, 100);
    };

    window.confirmCrop = function() {
        if (!window.cropper) return;
        var data = window.cropper.getData(true);
        window.updateCropDataJson(
            Math.round(data.x),
            Math.round(data.y),
            Math.round(data.width),
            Math.round(data.height)
        );
        window.closeCropModal();
        setTimeout(function() {
            window.clickGradioButton("confirm-crop-hidden-btn");
        }, 100);
    };

    function isCardMode() {
        return document.querySelectorAll(".lut-color-swatch-container").length === 0;
    }

    window.lutSearchDispatch = function(val) {
        syncGridFavorites();
        if (isCardMode()) {
            window.lutCardSearch(val);
            return;
        }
        window.lutSmartSearch(val);
    };

    window.lutHueDispatch = function(hueKey, btnEl) {
        syncGridFavorites();
        document.querySelectorAll(".lut-hue-btn").forEach(function(button) {
            button.style.background = "#f5f5f5";
            button.style.color = "#333";
            button.style.borderColor = "#ccc";
        });
        if (btnEl) {
            btnEl.style.background = "#333";
            btnEl.style.color = "#fff";
            btnEl.style.borderColor = "#333";
        }

        var searchBox = document.getElementById("lut-color-search");
        if (searchBox) {
            searchBox.value = "";
        }

        if (hueKey === "fav") {
            var favs = window._lutFavorites || {};
            if (isCardMode()) {
                var cardSwatches = document.querySelectorAll(".lut-color-swatch");
                var cardCount = 0;
                cardSwatches.forEach(function(swatch) {
                    if (favs[swatch.getAttribute("data-color")]) {
                        swatch.style.opacity = "1";
                        cardCount++;
                    } else {
                        swatch.style.opacity = "0.12";
                    }
                });
                var cardCountEl = document.getElementById("lut-color-visible-count");
                if (cardCountEl) cardCountEl.textContent = cardCount;
            } else {
                var containers = document.querySelectorAll(".lut-color-swatch-container");
                var visible = 0;
                containers.forEach(function(container) {
                    var swatch = container.querySelector(".lut-color-swatch");
                    if (swatch && favs[swatch.getAttribute("data-color")]) {
                        container.style.display = "flex";
                        visible++;
                    } else {
                        container.style.display = "none";
                    }
                });
                var countEl = document.getElementById("lut-color-visible-count");
                if (countEl) countEl.textContent = visible;
            }
            return;
        }

        if (isCardMode()) {
            var swatches = document.querySelectorAll(".lut-color-swatch");
            var count = 0;
            swatches.forEach(function(swatch) {
                if (hueKey === "all" || swatch.getAttribute("data-hue") === hueKey) {
                    swatch.style.opacity = "1";
                    count++;
                } else {
                    swatch.style.opacity = "0.12";
                }
            });
            var countElCard = document.getElementById("lut-color-visible-count");
            if (countElCard) countElCard.textContent = count;
            return;
        }

        var containers = document.querySelectorAll(".lut-color-swatch-container");
        var visibleCount = 0;
        containers.forEach(function(container) {
            var containerHue = container.getAttribute("data-hue");
            if (hueKey === "all" || containerHue === hueKey) {
                container.style.display = "flex";
                visibleCount++;
            } else {
                container.style.display = "none";
            }
        });
        var visibleCountEl = document.getElementById("lut-color-visible-count");
        if (visibleCountEl) visibleCountEl.textContent = visibleCount;
    };

    window.lutFilterByHue = window.lutHueDispatch;
    window.lutCardFilterByHue = window.lutHueDispatch;

    window.lutSmartSearch = function(searchValue) {
        var query = searchValue.trim().toLowerCase();
        var containers = document.querySelectorAll(".lut-color-swatch-container");
        var visibleCount = 0;
        var firstMatch = null;

        var rgbMatch = query.match(/^(\\d{1,3})\\s*[,\\s]\\s*(\\d{1,3})\\s*[,\\s]\\s*(\\d{1,3})$/);
        var rgbHex = null;
        if (rgbMatch) {
            var r = Math.min(255, parseInt(rgbMatch[1], 10));
            var g = Math.min(255, parseInt(rgbMatch[2], 10));
            var b = Math.min(255, parseInt(rgbMatch[3], 10));
            rgbHex = ("0" + r.toString(16)).slice(-2) + ("0" + g.toString(16)).slice(-2) + ("0" + b.toString(16)).slice(-2);
        }
        var hexQuery = query.replace("#", "");

        containers.forEach(function(container) {
            var swatch = container.querySelector(".lut-color-swatch");
            if (!swatch) return;
            var color = swatch.getAttribute("data-color").toLowerCase().replace("#", "");
            var match = query === "" || (rgbHex ? color === rgbHex : color.includes(hexQuery));
            if (match) {
                container.style.display = "flex";
                visibleCount++;
                if (!firstMatch && query !== "") {
                    firstMatch = swatch;
                }
            } else {
                container.style.display = "none";
            }
        });

        var countEl = document.getElementById("lut-color-visible-count");
        if (countEl) countEl.textContent = visibleCount;
        if (firstMatch) window.lutScrollAndHighlight(firstMatch);
    };

    window.lutCardSearch = function(searchValue) {
        var query = searchValue.trim().toLowerCase().replace("#", "");
        var swatches = document.querySelectorAll(".lut-color-swatch");
        var visibleCount = 0;
        var firstMatch = null;

        var rgbMatch = query.match(/^(\\d{1,3})\\s*[,\\s]\\s*(\\d{1,3})\\s*[,\\s]\\s*(\\d{1,3})$/);
        var rgbHex = null;
        if (rgbMatch) {
            var r = Math.min(255, parseInt(rgbMatch[1], 10));
            var g = Math.min(255, parseInt(rgbMatch[2], 10));
            var b = Math.min(255, parseInt(rgbMatch[3], 10));
            rgbHex = ("0" + r.toString(16)).slice(-2) + ("0" + g.toString(16)).slice(-2) + ("0" + b.toString(16)).slice(-2);
        }

        swatches.forEach(function(swatch) {
            var color = swatch.getAttribute("data-color").toLowerCase().replace("#", "");
            var match = query === "" || (rgbHex ? color === rgbHex : color.includes(query));
            if (match) {
                swatch.style.opacity = "1";
                visibleCount++;
                if (!firstMatch && query !== "") {
                    firstMatch = swatch;
                }
            } else {
                swatch.style.opacity = "0.15";
            }
        });

        var countEl = document.getElementById("lut-color-visible-count");
        if (countEl) countEl.textContent = visibleCount;
        if (firstMatch) window.lutScrollAndHighlight(firstMatch);
    };

    window.filterLutColors = window.lutSmartSearch;

    window.lutScrollAndHighlight = function(swatchEl) {
        if (!swatchEl) return;
        swatchEl.scrollIntoView({ behavior: "smooth", block: "center" });
        document.querySelectorAll(".lut-color-swatch.lut-highlight").forEach(function(element) {
            element.classList.remove("lut-highlight");
        });
        swatchEl.classList.add("lut-highlight");
        setTimeout(function() {
            swatchEl.classList.remove("lut-highlight");
        }, 2000);
    };

    window.lutScrollToColor = function(hexColor) {
        syncGridFavorites();
        if (!hexColor) return;
        var target = hexColor.toLowerCase();
        var swatches = document.querySelectorAll(".lut-color-swatch");
        for (var i = 0; i < swatches.length; i++) {
            if (swatches[i].getAttribute("data-color").toLowerCase() === target) {
                var allBtn = document.querySelector(".lut-hue-btn[data-hue='all']");
                if (allBtn) {
                    window.lutHueDispatch("all", allBtn);
                }
                var searchBox = document.getElementById("lut-color-search");
                if (searchBox) searchBox.value = "";
                window.lutScrollAndHighlight(swatches[i]);
                swatches[i].click();
                return;
            }
        }
    };

    window.lutLoadFavorites = function(lutKey) {
        window._lutCurrentLutKey = lutKey || "";
        try {
            var stored = localStorage.getItem("lut_favorites_" + window._lutCurrentLutKey);
            window._lutFavorites = stored ? JSON.parse(stored) : {};
        } catch (error) {
            window._lutFavorites = {};
        }
        window._lutApplyFavStars();
    };

    window._lutSaveFavorites = function() {
        try {
            localStorage.setItem("lut_favorites_" + window._lutCurrentLutKey, JSON.stringify(window._lutFavorites));
        } catch (error) {
            console.warn("[Palette] Failed to persist favorites:", error);
        }
    };

    window._lutApplyFavStars = function() {
        document.querySelectorAll(".lut-color-swatch").forEach(function(swatch) {
            var hex = swatch.getAttribute("data-color");
            var star = swatch.querySelector(".lut-fav-star");
            if (window._lutFavorites[hex]) {
                if (!star) {
                    star = document.createElement("span");
                    star.className = "lut-fav-star";
                    star.textContent = "⭐";
                    star.style.cssText = "position:absolute;top:-2px;right:-2px;font-size:8px;pointer-events:none;";
                    swatch.style.position = "relative";
                    swatch.style.overflow = "visible";
                    swatch.appendChild(star);
                }
            } else if (star) {
                star.remove();
            }
        });
    };

    function syncGridFavorites() {
        var container = document.getElementById("lut-color-grid-container");
        if (!container) return;
        var lutKey = container.getAttribute("data-lut-key") || "";
        if (lutKey !== window._lutCurrentLutKey) {
            window.lutLoadFavorites(lutKey);
            return;
        }
        window._lutApplyFavStars();
    }

    document.addEventListener("dblclick", function(event) {
        var swatch = event.target.closest(".lut-color-swatch");
        if (!swatch) return;
        var hex = swatch.getAttribute("data-color");
        if (!hex) return;
        if (window._lutFavorites[hex]) {
            delete window._lutFavorites[hex];
        } else {
            window._lutFavorites[hex] = true;
        }
        window._lutSaveFavorites();
        window._lutApplyFavStars();
    }, true);

    setTimeout(syncGridFavorites, 300);

    function handlePaletteSwatchClick(event) {
        var swatch = event.target.closest(".palette-swatch");
        if (!swatch) return false;
        var hexColor = swatch.getAttribute("data-color");
        if (!hexColor) return false;
        updateGradioTextbox("conv-color-selected-hidden", hexColor);
        updateGradioTextbox("conv-highlight-color-hidden", hexColor);
        document.querySelectorAll(".palette-swatch").forEach(function(element) {
            element.style.outline = "none";
            element.style.outlineOffset = "0px";
        });
        swatch.style.outline = "3px solid #2196F3";
        swatch.style.outlineOffset = "2px";
        setTimeout(function() {
            window.clickGradioButton("conv-color-trigger-btn");
            window.clickGradioButton("conv-highlight-trigger-btn");
        }, 50);
        return true;
    }

    function handleLutSwatchClick(event) {
        var swatch = event.target.closest(".lut-color-swatch");
        if (!swatch) return false;
        var hexColor = swatch.getAttribute("data-color");
        if (!hexColor) return false;
        updateGradioTextbox("conv-lut-color-selected-hidden", hexColor);
        document.querySelectorAll(".lut-color-swatch").forEach(function(element) {
            element.style.outline = "none";
            element.style.outlineOffset = "0px";
        });
        swatch.style.outline = "3px solid #2196F3";
        swatch.style.outlineOffset = "2px";
        setTimeout(function() {
            window.clickGradioButton("conv-lut-color-trigger-btn");
        }, 50);
        return true;
    }

    function handlePaletteRowClick(event) {
        var row = event.target.closest(".palette-list-item, .palette-row");
        if (!row) return false;

        var rowType = row.getAttribute("data-row-type");
        var rowId = row.getAttribute("data-row-id") || "";
        var quantized = row.getAttribute("data-quantized");
        var matched = row.getAttribute("data-matched");
        var replacement = row.getAttribute("data-replacement");

        if (rowId) {
            updateGradioTextbox("conv-palette-row-select-hidden", rowId);
            setTimeout(function() {
                window.clickGradioButton("conv-palette-row-select-trigger-btn");
            }, 20);
        }

        if (rowType === "user") {
            if (quantized) {
                updateGradioTextbox("conv-color-selected-hidden", quantized);
                updateGradioTextbox("conv-highlight-color-hidden", matched || quantized);
                setTimeout(function() {
                    window.clickGradioButton("conv-color-trigger-btn");
                }, 50);
            }
            if (replacement) {
                updateGradioTextbox("conv-lut-color-selected-hidden", replacement);
                setTimeout(function() {
                    window.clickGradioButton("conv-lut-color-trigger-btn");
                }, 50);
            }
            return true;
        }

        if (rowType === "auto" && quantized) {
            updateGradioTextbox("conv-color-selected-hidden", quantized);
            updateGradioTextbox("conv-highlight-color-hidden", matched || quantized);
            setTimeout(function() {
                window.clickGradioButton("conv-color-trigger-btn");
            }, 50);
            return true;
        }

        return false;
    }

    document.addEventListener("click", function(event) {
        if (event.target.closest("#conv-palette-delete-selected")) {
            setTimeout(function() {
                window.clickGradioButton("conv-palette-delete-trigger-btn");
            }, 20);
            return;
        }
        if (handlePaletteRowClick(event)) return;
        if (handlePaletteSwatchClick(event)) return;
        handleLutSwatchClick(event);
    }, true);

    console.log("[CROP] Global scripts loaded, openCropModal:", typeof window.openCropModal);
    console.log("[Palette] Global click handler installed");
})();
</script>
"""


def get_crop_head_js():
    """Return the JavaScript code injected into Gradio's head."""
    return CROP_MODAL_JS
