"""
Lumina Studio - UI Styles
UI style definitions
"""

CUSTOM_CSS = """
/* Global Theme - Full Width */
.gradio-container {
    max-width: 100% !important;
    width: 100% !important;
    padding-left: 24px !important;
    padding-right: 24px !important;
    margin: 0 !important;
}

/* Header Styling */
.header-banner {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 20px 30px;
    border-radius: 16px;
    margin-bottom: 20px;
    box-shadow: 0 10px 40px rgba(102, 126, 234, 0.3);
}

.header-banner h1 {
    color: white !important;
    font-size: 2.5em !important;
    margin: 0 !important;
    text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
}

.header-banner p {
    color: rgba(255,255,255,0.9) !important;
    margin: 5px 0 0 0 !important;
}

/* Stats Bar */
.stats-bar, .stats-bar-inline {
    background: rgba(0,0,0,0.15);
    padding: 8px 16px;
    border-radius: 10px;
    color: rgba(255,255,255,0.85);
    font-family: 'Courier New', monospace;
    text-align: center;
    font-size: 13px;
}

.stats-bar-inline {
    margin: 0 !important;
}

.stats-bar-inline strong,
.stats-bar strong {
    color: rgba(255,255,255,0.95);
}

/* Tab Styling */
.tab-nav button {
    font-size: 1.1em !important;
    padding: 12px 24px !important;
    border-radius: 10px 10px 0 0 !important;
}

.tab-nav button.selected {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    color: white !important;
}

/* Card Styling */
.input-card, .output-card {
    background: var(--background-fill-primary, #fafafa);
    border-radius: 12px;
    padding: 15px;
    border: 1px solid var(--border-color-primary, #e0e0e0);
}

/* Button Styling */
.primary-btn {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    border: none !important;
    font-size: 1.1em !important;
    padding: 12px 24px !important;
    border-radius: 10px !important;
    box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4) !important;
}

.primary-btn:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(102, 126, 234, 0.5) !important;
}

/* Mode indicator */
.mode-indicator {
    background: var(--background-fill-secondary, #f0f0ff);
    border: 2px solid #667eea;
    border-radius: 8px;
    padding: 10px;
    margin: 10px 0;
    font-weight: bold;
}

/* Language Button */
#lang-btn {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    color: white !important;
    border: none !important;
    padding: 8px 20px !important;
    border-radius: 20px !important;
    font-weight: bold !important;
    font-size: 0.95em !important;
    box-shadow: 0 2px 8px rgba(102, 126, 234, 0.3) !important;
    transition: all 0.3s ease !important;
    cursor: pointer !important;
}

#lang-btn:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 4px 12px rgba(102, 126, 234, 0.5) !important;
}

#lang-btn:active {
    transform: translateY(0) !important;
}

#theme-btn {
    background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%) !important;
    color: white !important;
    border: none !important;
    padding: 6px 18px !important;
    border-radius: 20px !important;
    font-weight: bold !important;
    font-size: 0.9em !important;
    box-shadow: 0 2px 8px rgba(79, 70, 229, 0.3) !important;
    transition: all 0.3s ease !important;
    cursor: pointer !important;
}

#theme-btn:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 4px 12px rgba(79, 70, 229, 0.5) !important;
}

#theme-btn:active {
    transform: translateY(0) !important;
}

/* Footer */
.footer {
    text-align: center;
    padding: 20px;
    color: #888;
    font-size: 0.9em;
}

/* Vertical Radio Button Layout */
.vertical-radio fieldset {
    display: flex !important;
    flex-direction: column !important;
    gap: 8px !important;
}

.vertical-radio .wrap {
    display: flex !important;
    flex-direction: column !important;
    gap: 8px !important;
}

.vertical-radio label {
    display: flex !important;
    align-items: center !important;
    padding: 8px 12px !important;
    border-radius: 6px !important;
    background: var(--background-fill-secondary, #f8f8f8) !important;
    transition: all 0.2s ease !important;
}

.vertical-radio label:hover {
    background: #f0f0ff !important;
    border-color: #667eea !important;
}

.vertical-radio input[type="radio"]:checked + label {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    color: white !important;
}

/* Micro Upload Dropzone - Ultra Compact */
.micro-upload {
    min-height: 60px !important;
    max-height: 60px !important;
    height: 60px !important;
    padding: 0 !important;
    margin: 8px 0 !important;
}

.micro-upload > div {
    min-height: 60px !important;
    max-height: 60px !important;
    height: 60px !important;
    border: 1.5px dashed #999 !important;
    border-radius: 6px !important;
    background: #fafafa !important;
    transition: all 0.2s ease !important;
    padding: 0 !important;
}

.micro-upload > div:hover {
    border-color: #667eea !important;
    background: #f5f5ff !important;
}

/* Center the content */
.micro-upload .wrap {
    min-height: 60px !important;
    max-height: 60px !important;
    height: 60px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    padding: 0 12px !important;
}

/* Shrink the upload icon */
.micro-upload svg {
    width: 14px !important;
    height: 14px !important;
    min-width: 14px !important;
    min-height: 14px !important;
    margin: 0 6px 0 0 !important;
    flex-shrink: 0 !important;
}

/* Shrink the text */
.micro-upload span {
    font-size: 11px !important;
    line-height: 1.2 !important;
    margin: 0 !important;
    padding: 0 !important;
    white-space: nowrap !important;
    overflow: hidden !important;
    text-overflow: ellipsis !important;
}

/* Hide any extra padding/margins */
.micro-upload .file-preview {
    display: none !important;
}

.micro-upload button {
    font-size: 10px !important;
    padding: 2px 6px !important;
    height: auto !important;
}

/* Hidden Number Components - for crop data */
.hidden-number,
.hidden-number *,
#crop-data-x,
#crop-data-y,
#crop-data-w,
#crop-data-h {
    display: none !important;
    visibility: hidden !important;
    position: absolute !important;
    left: -9999px !important;
    width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
    opacity: 0 !important;
    pointer-events: none !important;
}

/* Hidden Button Components - for JavaScript triggers */
.hidden-button,
.hidden-button *,
#use-original-hidden-btn,
#confirm-crop-hidden-btn {
    display: none !important;
    visibility: hidden !important;
    position: absolute !important;
    left: -9999px !important;
    width: 0 !important;
    height: 0 !important;
    overflow: hidden !important;
    opacity: 0 !important;
}

/* Hidden crop components - must be in DOM but invisible */
.hidden-crop-component,
.hidden-crop-component *,
div.hidden-crop-component,
div[class*="hidden-crop-component"] {
    position: absolute !important;
    left: -9999px !important;
    top: -9999px !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
    opacity: 0 !important;
    pointer-events: auto !important;
    visibility: hidden !important;
}

/* Crop modal host: keep in DOM without occupying layout, allow overlay to show */
.crop-modal-container {
    position: absolute !important;
    left: -9999px !important;
    top: -9999px !important;
    width: 0 !important;
    height: 0 !important;
    overflow: visible !important;
    pointer-events: auto !important;
    visibility: visible !important;
    opacity: 1 !important;
}

#crop-data-json,
#crop-data-json *,
div#crop-data-json,
#use-original-hidden-btn,
#use-original-hidden-btn *,
div#use-original-hidden-btn,
#confirm-crop-hidden-btn,
#confirm-crop-hidden-btn *,
div#confirm-crop-hidden-btn {
    position: absolute !important;
    left: -9999px !important;
    top: -9999px !important;
    width: 1px !important;
    height: 1px !important;
    overflow: hidden !important;
    opacity: 0 !important;
    visibility: hidden !important;
}

/* Fullscreen 3D Preview */
#conv-3d-fullscreen-container {
    position: fixed;
    top: 0;
    left: 0;
    width: 100vw;
    height: 100vh;
    background: #1a1a2e;
    z-index: 10000;
    padding: 0;
    box-sizing: border-box;
    overflow: hidden;
}

#conv-3d-fullscreen-container .model3D {
    border-radius: 0 !important;
    border: none !important;
}

#conv-3d-fullscreen {
    min-height: 100vh !important;
    height: 100vh !important;
    border-radius: 0;
    border: none;
}

#conv-3d-fullscreen label {
    display: none !important;
}

/* Floating 2D Thumbnail in fullscreen 3D mode - bottom right corner */
#conv-2d-thumbnail-container {
    position: fixed !important;
    bottom: 20px !important;
    right: 20px !important;
    width: 260px !important;
    max-width: 260px !important;
    z-index: 10001 !important;
    background: rgba(30, 30, 46, 0.95) !important;
    border-radius: 12px !important;
    border: 2px solid rgba(102, 126, 234, 0.5) !important;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4) !important;
    padding: 8px !important;
    overflow: visible !important;
}

#conv-2d-thumbnail-container label {
    display: none !important;
}

#conv-2d-thumbnail-container .image-container {
    border-radius: 8px !important;
    overflow: hidden !important;
}

#conv-2d-back-btn {
    position: absolute !important;
    top: 8px !important;
    left: 8px !important;
    z-index: 10 !important;
    width: 32px !important;
    height: 32px !important;
    min-width: 32px !important;
    padding: 0 !important;
    margin: 0 !important;
    font-size: 18px !important;
    line-height: 32px !important;
    text-align: center !important;
    border-radius: 8px !important;
    background: rgba(60, 60, 80, 0.7) !important;
    color: rgba(255,255,255,0.85) !important;
    border: none !important;
    backdrop-filter: blur(4px) !important;
    cursor: pointer !important;
}

#conv-2d-back-btn:hover {
    background: rgba(80, 80, 110, 0.9) !important;
    color: white !important;
}

/* Floating 3D Thumbnail - bottom right corner */
#conv-3d-thumbnail-container {
    position: fixed !important;
    bottom: 20px !important;
    right: 20px !important;
    width: 280px !important;
    max-width: 280px !important;
    z-index: 999 !important;
    background: #1e1e2e !important;
    border-radius: 12px !important;
    border: 2px solid rgba(102, 126, 234, 0.5) !important;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4) !important;
    padding: 8px !important;
    overflow: visible !important;
}

#conv-3d-thumbnail-container .model3D {
    border-radius: 8px !important;
    overflow: hidden !important;
}

#conv-3d-thumbnail-container label {
    display: none !important;
}

#conv-3d-fullscreen-btn {
    position: absolute !important;
    top: 8px !important;
    left: 8px !important;
    z-index: 10 !important;
    width: 32px !important;
    height: 32px !important;
    min-width: 32px !important;
    padding: 0 !important;
    margin: 0 !important;
    font-size: 18px !important;
    line-height: 32px !important;
    text-align: center !important;
    border-radius: 8px !important;
    background: rgba(60, 60, 80, 0.7) !important;
    color: rgba(255,255,255,0.85) !important;
    border: none !important;
    backdrop-filter: blur(4px) !important;
    cursor: pointer !important;
}

#conv-3d-fullscreen-btn:hover {
    background: rgba(80, 80, 110, 0.9) !important;
    color: white !important;
}

/* Hide Gradio Model3D toolbar (reset/close buttons) and upload prompt in thumbnail */
#conv-3d-thumbnail-container .model3D .controls,
#conv-3d-thumbnail-container .model3D .toolbar,
#conv-3d-thumbnail-container .model3D > div > div:last-child:not(canvas),
#conv-3d-thumbnail-container .model3D button,
#conv-3d-thumbnail-container .model3D .icon-buttons,
#conv-3d-thumbnail-container .model3D .canvas-control,
#conv-3d-thumbnail-container .upload-text,
#conv-3d-thumbnail-container .model3D .upload-container {
    display: none !important;
}

/* Split button container — no gap, unified look */
#conv-slicer-split-btn {
    gap: 0 !important;
    padding: 0 !important;
    align-items: stretch !important;
}

/* Slicer open button - base styles (left part) */
#conv-open-slicer-btn {
    border: none !important;
    color: white !important;
    font-size: 1.05em !important;
    font-weight: 600 !important;
    padding: 10px 20px !important;
    border-radius: 10px 0 0 10px !important;
    transition: all 0.2s ease !important;
}

/* Arrow button - base styles (right part) */
#conv-slicer-arrow-btn {
    border: none !important;
    border-left: 1px solid rgba(255,255,255,0.25) !important;
    color: white !important;
    font-size: 1.05em !important;
    padding: 10px 0 !important;
    border-radius: 0 10px 10px 0 !important;
    transition: all 0.2s ease !important;
    min-width: 42px !important;
    max-width: 42px !important;
}

/* Bambu Studio - green */
#conv-open-slicer-btn.slicer-bambu,
#conv-slicer-arrow-btn.slicer-bambu {
    background: linear-gradient(135deg, #00ae42 0%, #00c853 100%) !important;
    box-shadow: 0 4px 12px rgba(0, 174, 66, 0.35) !important;
}
#conv-open-slicer-btn.slicer-bambu:hover,
#conv-slicer-arrow-btn.slicer-bambu:hover {
    background: linear-gradient(135deg, #009e3a 0%, #00b848 100%) !important;
    box-shadow: 0 6px 16px rgba(0, 174, 66, 0.45) !important;
}

/* OrcaSlicer - gray */
#conv-open-slicer-btn.slicer-orca,
#conv-slicer-arrow-btn.slicer-orca {
    background: linear-gradient(135deg, #4a4a4a 0%, #636363 100%) !important;
    box-shadow: 0 4px 12px rgba(74, 74, 74, 0.35) !important;
}
#conv-open-slicer-btn.slicer-orca:hover,
#conv-slicer-arrow-btn.slicer-orca:hover {
    background: linear-gradient(135deg, #3a3a3a 0%, #555555 100%) !important;
    box-shadow: 0 6px 16px rgba(74, 74, 74, 0.45) !important;
}

/* ElegooSlicer - blue */
#conv-open-slicer-btn.slicer-elegoo,
#conv-slicer-arrow-btn.slicer-elegoo {
    background: linear-gradient(135deg, #1565c0 0%, #1e88e5 100%) !important;
    box-shadow: 0 4px 12px rgba(21, 101, 192, 0.35) !important;
}
#conv-open-slicer-btn.slicer-elegoo:hover,
#conv-slicer-arrow-btn.slicer-elegoo:hover {
    background: linear-gradient(135deg, #0d47a1 0%, #1976d2 100%) !important;
    box-shadow: 0 6px 16px rgba(21, 101, 192, 0.45) !important;
}

/* Download / default - purple (matches app theme) */
#conv-open-slicer-btn.slicer-download,
#conv-slicer-arrow-btn.slicer-download {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
    box-shadow: 0 4px 12px rgba(102, 126, 234, 0.35) !important;
}
#conv-open-slicer-btn.slicer-download:hover,
#conv-slicer-arrow-btn.slicer-download:hover {
    background: linear-gradient(135deg, #5a6fd6 0%, #6a4196 100%) !important;
    box-shadow: 0 6px 16px rgba(102, 126, 234, 0.45) !important;
}

/* Slicer dropdown compact */
#conv-slicer-dropdown {
    max-width: 100% !important;
}
#conv-slicer-dropdown .wrap {
    min-height: unset !important;
}
"""
