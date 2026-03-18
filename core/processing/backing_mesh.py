# -*- coding: utf-8 -*-
"""
Backing Mesh 生成模块

从 full_matrix 中生成独立的 backing（底板）mesh。
"""

from __future__ import annotations

import numpy as np
import trimesh


def generate_backing_mesh(
    mesher,
    full_matrix: np.ndarray,
    target_h: int,
    transform: np.ndarray,
    preview_colors: dict,
) -> trimesh.Trimesh | None:
    """生成独立的 backing mesh。

    Args:
        mesher: mesh 生成器实例（来自 core.mesh_generators）
        full_matrix: 完整体素矩阵 (layers, H, W)
        target_h: 目标高度（像素）
        transform: 4x4 变换矩阵
        preview_colors: 预览颜色字典 {mat_id: [R, G, B, A]}

    Returns:
        生成的 backing mesh，失败返回 None
    """
    print(f"[CONVERTER] Attempting to generate separate backing mesh (mat_id=-2)...")
    try:
        backing_mesh = mesher.generate_mesh(full_matrix, mat_id=-2, height_px=target_h)
        if backing_mesh is None or len(backing_mesh.vertices) == 0:
            print(f"[CONVERTER] Warning: Backing mesh is empty, skipping separate backing object")
            return None

        backing_mesh.apply_transform(transform)
        backing_mesh.visual.face_colors = preview_colors[0]
        backing_name = "Backing"
        backing_mesh.metadata['name'] = backing_name
        print(f"[CONVERTER] ✅ Added backing mesh as separate object (white)")
        return backing_mesh
    except Exception as e:
        print(f"[CONVERTER] Error generating backing mesh: {e}")
        import traceback; traceback.print_exc()
        return None
