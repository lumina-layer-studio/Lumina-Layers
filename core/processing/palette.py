# -*- coding: utf-8 -*-
"""调色板提取模块

从预览缓存中提取唯一颜色调色板，确保 quantized_image 可用。
"""

import numpy as np


def ensure_quantized_image_in_cache(cache):
    """保证预览缓存中存在 quantized_image，缺失时自动回填。

    Args:
        cache: preview cache dict

    Returns:
        cache (modified in-place)
    """
    if cache.get("quantized_image") is not None:
        return cache

    dbg = cache.get("debug_data") or {}
    q = dbg.get("quantized_image")
    if q is None:
        q = cache["matched_rgb"].copy()

    cache["quantized_image"] = q
    return cache


def extract_color_palette(preview_cache: dict) -> list:
    """Extract unique colors from preview cache.
    从预览缓存中提取唯一颜色。

    Args:
        preview_cache: Cache data containing:
            - matched_rgb: (H, W, 3) uint8 array
            - mask_solid: (H, W) bool array

    Returns:
        List of dicts sorted by pixel count (descending), each containing:
        - 'color': (R, G, B) tuple
        - 'hex': '#RRGGBB' string
        - 'count': pixel count
        - 'percentage': percentage of total solid pixels
    """
    if preview_cache is None:
        return []

    matched_rgb = preview_cache.get('matched_rgb')
    mask_solid = preview_cache.get('mask_solid')

    if matched_rgb is None or mask_solid is None:
        return []

    # Get only solid pixels
    solid_pixels = matched_rgb[mask_solid]

    if len(solid_pixels) == 0:
        return []

    total_solid = len(solid_pixels)

    # Find unique colors and their counts
    unique_colors, counts = np.unique(solid_pixels, axis=0, return_counts=True)

    # Build palette entries
    palette = []
    for color, count in zip(unique_colors, counts):
        r, g, b = int(color[0]), int(color[1]), int(color[2])
        palette.append({
            'color': (r, g, b),
            'hex': f'#{r:02x}{g:02x}{b:02x}',
            'count': int(count),
            'percentage': round(count / total_solid * 100, 2)
        })

    # Sort by count descending
    palette.sort(key=lambda x: x['count'], reverse=True)

    return palette
