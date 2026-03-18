# -*- coding: utf-8 -*-
"""颜色替换工具模块

提供颜色替换输入归一化和区域替换应用功能。
"""

import numpy as np


def hex_to_rgb_tuple(hex_color):
    """将 #RRGGBB 转换为 (R, G, B)。"""
    if not isinstance(hex_color, str):
        raise ValueError("hex_color must be a string")

    h = hex_color.strip().lower()
    if h.startswith('#'):
        h = h[1:]
    if len(h) != 6:
        raise ValueError(f"invalid hex color: {hex_color}")

    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def normalize_color_replacements_input(color_replacements):
    """兼容 dict / replacement_regions(list) 两种替换输入，统一为 {hex: hex}。"""
    if not color_replacements:
        return {}

    if isinstance(color_replacements, dict):
        out = {}
        for src, dst in color_replacements.items():
            if not isinstance(src, str) or not isinstance(dst, str):
                continue
            s = src.strip().lower()
            d = dst.strip().lower()
            if s and d:
                out[s] = d
        return out

    if isinstance(color_replacements, list):
        out = {}
        for item in color_replacements:
            if not isinstance(item, dict):
                continue
            src = (item.get('matched') or item.get('matched_hex')
                   or item.get('source') or item.get('quantized')
                   or item.get('quantized_hex')
                   or item.get('selected_color') or '').strip().lower()
            dst = (item.get('replacement') or item.get('replacement_hex')
                   or item.get('replacement_color') or '').strip().lower()
            if src and dst:
                out[src] = dst
        return out

    return {}


def apply_regions_to_raster_outputs(matched_rgb, material_matrix, mask_solid,
                                    replacement_regions, lut_index_resolver, ref_stacks):
    """按 regions 顺序覆盖 raster 输出（matched_rgb + material_matrix）。"""
    out_rgb = matched_rgb.copy()
    out_mat = material_matrix.copy()

    for item in (replacement_regions or []):
        region_mask = item.get('mask')
        replacement_hex = item.get('replacement')
        if region_mask is None or not replacement_hex:
            continue

        effective_mask = region_mask & mask_solid
        if not np.any(effective_mask):
            continue

        replacement_rgb = hex_to_rgb_tuple(replacement_hex)
        out_rgb[effective_mask] = np.array(replacement_rgb, dtype=np.uint8)

        lut_idx = int(lut_index_resolver(replacement_rgb))
        out_mat[effective_mask] = ref_stacks[lut_idx]

    return out_rgb, out_mat
