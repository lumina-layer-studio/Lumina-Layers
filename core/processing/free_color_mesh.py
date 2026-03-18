# -*- coding: utf-8 -*-
"""
Free Color Mesh 提取模块

将指定颜色的像素区域提取为独立的 mesh 对象。
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import trimesh


class FreeColorResult(NamedTuple):
    """单个 free color 的提取结果。"""
    mesh: trimesh.Trimesh
    name: str
    hex_color: str


def extract_free_color_meshes(
    free_color_set: set[str],
    matched_rgb: np.ndarray,
    mask_solid: np.ndarray,
    full_matrix: np.ndarray,
    target_h: int,
    mesher,
    transform: np.ndarray,
) -> list[FreeColorResult]:
    """提取 free color 像素区域并生成独立 mesh。

    Args:
        free_color_set: hex 颜色集合，如 {'#ff0000', '#00ff00'}
        matched_rgb: 匹配后的 RGB 图像 (H, W, 3)
        mask_solid: 实体掩码 (H, W)
        full_matrix: 完整体素矩阵 (layers, H, W)
        target_h: 目标高度（像素）
        mesher: mesh 生成器实例
        transform: 4x4 变换矩阵

    Returns:
        FreeColorResult 列表
    """
    _free_set = {c.lower() for c in free_color_set if c}
    if not _free_set:
        return []

    print(f"[CONVERTER] 🎯 Free Color mode: {len(_free_set)} colors marked")
    results = []

    for hex_c in sorted(_free_set):
        try:
            r_fc = int(hex_c[1:3], 16)
            g_fc = int(hex_c[3:5], 16)
            b_fc = int(hex_c[5:7], 16)
            color_mask = (
                (matched_rgb[:, :, 0] == r_fc) &
                (matched_rgb[:, :, 1] == g_fc) &
                (matched_rgb[:, :, 2] == b_fc) &
                mask_solid
            )
            if not np.any(color_mask):
                print(f"[CONVERTER]   {hex_c}: no pixels found, skipping")
                continue

            fc_matrix = np.where(
                np.broadcast_to(color_mask[np.newaxis, :, :], full_matrix.shape),
                full_matrix, -1,
            )
            fc_matrix = np.where(fc_matrix >= 0, 0, -1)

            fc_mesh = mesher.generate_mesh(fc_matrix, 0, target_h)
            if fc_mesh and len(fc_mesh.vertices) > 0:
                fc_mesh.apply_transform(transform)
                fc_mesh.visual.face_colors = [r_fc, g_fc, b_fc, 255]
                fc_name = f"Free_{hex_c[1:]}"
                fc_mesh.metadata['name'] = fc_name
                results.append(FreeColorResult(mesh=fc_mesh, name=fc_name, hex_color=hex_c))
                print(f"[CONVERTER]   ✅ {hex_c} → '{fc_name}' ({np.sum(color_mask)} px)")
            else:
                print(f"[CONVERTER]   {hex_c}: mesh empty, skipping")
        except Exception as e:
            print(f"[CONVERTER]   Error extracting free color {hex_c}: {e}")

    return results
