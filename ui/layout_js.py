"""JavaScript assets shared by UI layout modules."""

from .asset_loader import load_asset_text


def _as_script_tag(js_code: str) -> str:
    return f"<script>\n{js_code}\n</script>"


LUT_GRID_JS = _as_script_tag(load_asset_text("js", "lut_grid.js"))
PREVIEW_ZOOM_JS = _as_script_tag(load_asset_text("js", "preview_zoom.js"))

# For Gradio event `js=` callbacks (function string, no <script> wrapper)
OPEN_CROP_MODAL_JS = load_asset_text("js", "open_crop_modal.js")
SHOW_COLOR_TOAST_JS = load_asset_text("js", "show_color_toast.js")
