# -*- coding: utf-8 -*-
"""
Cloisonné Wire Mesh 生成模块

从 full_matrix 中生成景泰蓝掐丝（wire）mesh。
"""

from __future__ import annotations

import numpy as np
import trimesh


def generate_wire_mesh(
    mesher,
    full_matrix: np.ndarray,
    target_h: int,
    transform: np.ndarray,
) -> trimesh.Trimesh | None:
    """生成景泰蓝掐丝 wire mesh。

    Args:
        mesher: mesh 生成器实例
        full_matrix: 完整体素矩阵 (layers, H, W)
        target_h: 目标高度（像素）
        transform: 4x4 变换矩阵

    Returns:
        生成的 wire mesh，失败返回 None
    """
    print(f"[CONVERTER] Generating cloisonné wire mesh (mat_id=-3)...")
    try:
        wire_mesh = mesher.generate_mesh(full_matrix, mat_id=-3, height_px=target_h)
        if wire_mesh is not None and len(wire_mesh.vertices) > 0:
            wire_mesh.apply_transform(transform)
            wire_mesh.visual.face_colors = [218, 165, 32, 255]  # 金色
            wire_name = "Wire"
            wire_mesh.metadata['name'] = wire_name
            print(f"[CONVERTER] ✅ Added wire mesh ({len(wire_mesh.vertices)} verts)")
            return wire_mesh
        else:
            print(f"[CONVERTER] Warning: Wire mesh is empty, skipping")
            return None
    except Exception as e:
        print(f"[CONVERTER] Error generating wire mesh: {e}")
        import traceback; traceback.print_exc()
        return None
