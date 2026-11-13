"""Exact visible RGB counts with bounded working memory."""

import numpy as np

_COUNT_TILE_EDGE = 512
_MAX_SPARSE_COLORS = 65_536


def count_visible_rgb(
    rgb: np.ndarray, mask: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return lexicographically sorted uint8 RGB colors and int64 counts.

    Each tile contributes exact counts to a compact palette. When that palette
    grows large, use the fixed RGB24 key space to bound merge work and memory.
    Neither sampling nor resizing changes the colors or their weights.
    """
    height, width = mask.shape
    histogram = None
    keys = np.empty(0, dtype=np.uint32)
    counts = np.empty(0, dtype=np.int64)
    for y in range(0, height, _COUNT_TILE_EDGE):
        for x in range(0, width, _COUNT_TILE_EDGE):
            selected = mask[y:y + _COUNT_TILE_EDGE, x:x + _COUNT_TILE_EDGE]
            pixels = rgb[y:y + _COUNT_TILE_EDGE, x:x + _COUNT_TILE_EDGE][selected]
            if not pixels.size:
                continue
            packed = pixels[:, 0].astype(np.uint32)
            np.left_shift(packed, 16, out=packed)
            packed |= pixels[:, 1].astype(np.uint32) << 8
            packed |= pixels[:, 2]
            tile_keys, tile_counts = np.unique(packed, return_counts=True)
            if histogram is not None:
                histogram[tile_keys] += tile_counts
                continue
            merged_keys = np.union1d(keys, tile_keys)
            merged_counts = np.zeros(merged_keys.size, dtype=np.int64)
            merged_counts[np.searchsorted(merged_keys, keys)] = counts
            merged_counts[np.searchsorted(merged_keys, tile_keys)] += tile_counts
            keys, counts = merged_keys, merged_counts
            if keys.size > _MAX_SPARSE_COLORS:
                histogram = np.zeros(1 << 24, dtype=np.int64)
                histogram[keys] = counts
    if histogram is not None:
        keys = np.flatnonzero(histogram)
        counts = histogram[keys]
    colors = np.empty((keys.size, 3), dtype=np.uint8)
    colors[:, 0] = (keys >> 16) & 255
    colors[:, 1] = (keys >> 8) & 255
    colors[:, 2] = keys & 255
    return colors, counts.astype(np.int64, copy=False)
