"""CSS assets shared by the refactored UI layout."""

from .asset_loader import load_asset_text


HEADER_CSS = load_asset_text("css", "header.css")
LUT_GRID_CSS = load_asset_text("css", "lut_grid.css")
PREVIEW_ZOOM_CSS = load_asset_text("css", "preview_zoom.css")
