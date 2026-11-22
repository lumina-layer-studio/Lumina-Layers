"""Physical artwork outline data for the interactive keychain attachment."""

import numpy as np
from shapely import get_parts
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

KEYCHAIN_REFERENCE_METADATA = "lumina_keychain_attachment"


def vector_keychain_reference(footprint: BaseGeometry) -> dict | None:
    """Pack the same artwork-space exterior the analytic preview extrudes."""
    outlines = [
        np.asarray(part.exterior.coords).tolist()
        for part in get_parts(footprint)
        if isinstance(part, Polygon) and not part.is_empty
    ]
    if not outlines:
        return None
    return {"bounds_mm": list(footprint.bounds), "outlines_mm": outlines}


def _raster_outward_runs(cells: np.ndarray, sign: int, pixel_scale: float) -> list[list[float]]:
    """Run-length encode the exact outside cell edges along one axis."""
    scan = cells[::-1] if sign > 0 else cells
    height, width = scan.shape
    origin = 0 if sign > 0 else -height
    levels = np.full(width, -height - 1, dtype=np.int32)
    # Bound strided argmax's temporary storage even for wide, high-resolution uploads.
    block = max(1, 1_000_000 // height)
    for start in range(0, width, block):
        band = scan[:, start:start + block]
        columns = np.arange(band.shape[1])
        rows = np.argmax(band, axis=0)
        present = band[rows, columns]
        levels[start + columns[present]] = origin + height - rows[present]
    changes = np.flatnonzero(levels[1:] != levels[:-1]) + 1
    breaks = np.r_[0, changes, width]
    return [
        [float(begin * pixel_scale), float(end * pixel_scale), float(levels[begin] * pixel_scale)]
        for begin, end in zip(breaks[:-1], breaks[1:])
        if levels[begin] != -height - 1
    ]


def raster_keychain_reference(mask: np.ndarray, pixel_scale: float) -> dict | None:
    """Keep raw print-grid contact even when the surrounding GLB is downsampled."""
    if mask.ndim != 2 or not mask.size or not np.isfinite(pixel_scale) or pixel_scale <= 0:
        return None
    cells = mask[::-1]
    top = _raster_outward_runs(cells, 1, pixel_scale)
    if not top:
        return None
    bottom = _raster_outward_runs(cells, -1, pixel_scale)
    right = _raster_outward_runs(cells.T, 1, pixel_scale)
    left = _raster_outward_runs(cells.T, -1, pixel_scale)
    return {
        "bounds_mm": [top[0][0], right[0][0], top[-1][1], right[-1][1]],
        "bands_mm": [top, bottom, right, left],
    }
