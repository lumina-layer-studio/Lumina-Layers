"""Read session-owned geometry and solve an artwork-space preview anchor."""

import numpy as np
import shapely
from shapely.affinity import scale

from core.keychain_attachment import LoopProfile, solve_raster_loop, solve_vector_loop


def worker_keychain_anchor(
    path: str, backing_path: str | None, pixel_scale: float,
    vector_mm_per_unit: float | None,
    profile: LoopProfile, preset: str,
) -> tuple[float, float]:
    source = np.load(path, mmap_mode="r", allow_pickle=False)
    if vector_mm_per_unit is None:
        mask = source if backing_path is None else (
            source | np.load(backing_path, mmap_mode="r", allow_pickle=False)
        )
        (x, y), (cx, cy) = solve_raster_loop(mask, pixel_scale, pixel_scale, profile, preset)
    else:
        body = scale(shapely.from_wkb(source.tobytes()), vector_mm_per_unit, -vector_mm_per_unit, origin=(0, 0))
        x, y = solve_vector_loop(body, profile, preset)
        x0, y0, x1, y1 = body.bounds
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return x - cx, y - cy
