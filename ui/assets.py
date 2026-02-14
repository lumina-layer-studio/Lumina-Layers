"""Centralized UI asset loader and exported CSS/JS constants."""

from pathlib import Path


_ASSET_ROOT = Path(__file__).resolve().parent / "assets"


def load_asset_text(*parts: str) -> str:
    """Load a UTF-8 text asset from ui/assets."""
    return (_ASSET_ROOT / Path(*parts)).read_text(encoding="utf-8")


def _as_script_tag(js_code: str) -> str:
    return f"<script>\n{js_code}\n</script>"


CUSTOM_CSS = load_asset_text("css", "custom.css")
HEADER_CSS = load_asset_text("css", "header.css")
LUT_GRID_CSS = load_asset_text("css", "lut_grid.css")
PREVIEW_ZOOM_CSS = load_asset_text("css", "preview_zoom.css")

LUT_GRID_JS = _as_script_tag(load_asset_text("js", "lut_grid.js"))
PREVIEW_ZOOM_JS = _as_script_tag(load_asset_text("js", "preview_zoom.js"))

# For Gradio event `js=` callbacks (function string, no <script> wrapper)
OPEN_CROP_MODAL_JS = load_asset_text("js", "open_crop_modal.js")
SHOW_COLOR_TOAST_JS = load_asset_text("js", "show_color_toast.js")
