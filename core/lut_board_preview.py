"""Compact, page-aware artwork for LUT catalogs. Each source RGB row keeps its grid position."""

from __future__ import annotations

import base64
import math
from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image

from config import PrinterConfig
from core.color_modes import ColorMode
from core.lut_card_layout import (
    EIGHT_COLOR_FULL_TOTAL_RECIPES, EIGHT_COLOR_PAGE_CAPACITY,
    localize_page_layout, resolve_lut_layout,
)


_MAX_SIDE = 48
_MAX_PAGES = math.ceil(EIGHT_COLOR_FULL_TOTAL_RECIPES / EIGHT_COLOR_PAGE_CAPACITY)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _block_fraction(metadata: dict[str, Any]) -> float:
    """Use the same voxel rounding as the calibration print generator."""
    def voxels(value: object, default_mm: float) -> int:
        if type(value) not in (int, float) or not 0 < value <= 100:
            value = default_mm
        return max(1, int(value / PrinterConfig.NOZZLE_WIDTH))

    block = voxels(metadata.get("block_size_mm", metadata.get("block_size")), 5.0)
    gap = voxels(metadata.get("gap_mm", metadata.get("gap")), 0.84)
    return block / (block + gap)


def _page_pixels(rgb: np.ndarray, rows: int, cols: int) -> str:
    # The standard boards fit pixel-for-cell. Only virtual grids from larger
    # custom LUTs are subsampled, using actual positions rather than blended colors.
    y = np.linspace(0, rows - 1, min(rows, _MAX_SIDE)).round().astype(int)
    x = np.linspace(0, cols - 1, min(cols, _MAX_SIDE)).round().astype(int)
    indices = y[:, None] * cols + x[None, :]
    valid = indices < len(rgb)
    pixels = np.zeros((*indices.shape, 4), dtype=np.uint8)
    pixels[valid, :3] = rgb[indices[valid]]
    pixels[valid, 3] = 255
    stream = BytesIO()
    Image.fromarray(pixels).save(stream, format="PNG", compress_level=3)
    return base64.b64encode(stream.getvalue()).decode("ascii")


def lut_board_preview(rgb: np.ndarray, mode: str | None, metadata: dict[str, Any]) -> dict[str, Any]:
    colors = np.asarray(rgb)
    if (not colors.size or colors.size % 3 or colors.dtype.kind not in "uif"
            or (colors.ndim > 1 and colors.shape[-1] != 3)):
        return {}
    if colors.dtype != np.uint8 and (
        not np.isfinite(colors).all() or colors.min() < 0 or colors.max() > 255
    ):
        return {}
    colors = colors.reshape(-1, 3).astype(np.uint8, copy=False)
    mode_name = str(mode or "")
    descriptor = ColorMode.from_name(mode_name)
    is_bw = (descriptor is not None and descriptor.n_materials == 2) or mode_name.casefold() in {"2-color", "2色"}
    # Legacy BW scans saved the whole 6 × 6 window with four zero padding
    # pixels. The printer puts recipes in the first 32 cells only.
    if is_bw and len(colors) == 36 and not colors[32:].any():
        colors = colors[:32]
    count = len(colors)
    is_five = (descriptor is not None and descriptor.name == "5-color-extended") or mode_name.lower() in {"5-color", "5色"}
    single_page = metadata.get("page_index")
    set_size = metadata.get("total_pages")
    whole_count = count
    if is_five and count in (1024, 1444):
        whole_count = 2468
        single_page, set_size = (1 if count == 1024 else 2), 2
    elif (type(single_page) is int and type(set_size) is int and 1 <= single_page <= set_size
          and set_size in (2, _MAX_PAGES) and descriptor is not None and descriptor.n_materials == 8):
        whole_count = EIGHT_COLOR_FULL_TOTAL_RECIPES if set_size == _MAX_PAGES else 2738
    layout = resolve_lut_layout(mode, whole_count)
    pages = layout.pages
    if whole_count != count:
        original = pages[single_page - 1]
        if original.item_count != count:
            return {}
        pages = localize_page_layout(original).pages
    else:
        set_size = len(pages)

    if whole_count == 2468:
        family = "five"
    elif whole_count == 2738:
        family = "eight"
    elif whole_count == EIGHT_COLOR_FULL_TOTAL_RECIPES:
        family = "full"
    elif count in (32, 1024, 1296):
        family = "board"
    else:
        family = "index"
    if "merged" in mode_name.casefold() or str(metadata.get("source_kind", "")).startswith("predictive"):
        family = "index"
    if family == "index":
        side = math.ceil(math.sqrt(count))
        summary = {"number": 1, "rows": side, "cols": side, "padding": 0, "count": count,
                   "png": _page_pixels(colors, side, side)}
        return {"lut_board_preview": {"family": family, "set_size": 1, "pages": [summary]}}
    artwork = [
        {"number": page.page_index + 1, "rows": page.data_rows, "cols": page.data_cols,
         "padding": page.padding, "count": page.item_count,
         "png": _page_pixels(colors[page.start_index:page.start_index + page.item_count], page.data_rows, page.data_cols)}
        for page in pages
    ]
    return {"lut_board_preview": {"family": family, "set_size": set_size,
                                  "block_fraction": _block_fraction(metadata), "pages": artwork}}


def published_lut_board(value: object) -> dict[str, Any]:
    """Project only bounded embedded PNGs and the geometry needed to display them."""
    if not isinstance(value, dict) or value.get("family") not in ("five", "eight", "full", "board", "index"):
        return {}
    size, pages = value.get("set_size"), value.get("pages")
    if type(size) is not int or not 1 <= size <= _MAX_PAGES or not isinstance(pages, list) or not 1 <= len(pages) <= size:
        return {}
    result = []
    previous = 0
    for page in pages:
        if not isinstance(page, dict):
            return {}
        number, rows, cols, padding, count = (page.get(k) for k in ("number", "rows", "cols", "padding", "count"))
        if (not all(type(v) is int for v in (number, rows, cols, padding, count))
                or not previous < number <= size or not 1 <= rows <= 65536 or not 1 <= cols <= 65536
                or not 0 <= padding <= 8 or not 1 <= count <= rows * cols):
            return {}
        png = page.get("png")
        if not isinstance(png, str) or not 32 <= len(png) <= 16384:
            return {}
        try:
            header = base64.b64decode(png, validate=True)[:24]
        except ValueError:
            return {}
        if (header[:16] != _PNG_SIGNATURE + b"\x00\x00\x00\rIHDR"
                or int.from_bytes(header[16:20], "big") != min(cols, _MAX_SIDE)
                or int.from_bytes(header[20:24], "big") != min(rows, _MAX_SIDE)):
            return {}
        result.append({"number": number, "rows": rows, "cols": cols, "padding": padding, "count": count, "png": png})
        previous = number
    board = {"family": value["family"], "set_size": size, "pages": result}
    fraction = value.get("block_fraction")
    if type(fraction) in (int, float) and 0 < fraction < 1:
        board["block_fraction"] = fraction
    return {"lut_board_preview": board}
