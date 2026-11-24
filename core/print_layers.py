"""Physical layer heights shared by conversion, preview, and 3MF export."""

from collections.abc import Mapping
import math

from config import PrinterConfig


def resolve_layer_height_mm(ctx: Mapping[str, object]) -> float:
    """Prefer the effective recipe layer height, including older archive contexts."""
    values = (ctx.get("layer_height_mm"),)
    if ctx.get("material_source") == "material_archive":
        values += (ctx.get("material_layer_height_mm"),)
    for raw in values:
        try:
            height = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(height) and height > 0:
            return height
    return float(PrinterConfig.LAYER_HEIGHT)


def resolve_coating_height_mm(value: object) -> float:
    """Snap the physical film to the 0.02 mm grid, independent of the recipe."""
    try:
        height = float(value)
    except (TypeError, ValueError):
        height = float(PrinterConfig.LAYER_HEIGHT)
    if not math.isfinite(height) or height <= 0:
        height = float(PrinterConfig.LAYER_HEIGHT)
    ticks = math.floor(min(0.12, max(0.04, height)) * 50 + 0.5)
    return ticks / 50
