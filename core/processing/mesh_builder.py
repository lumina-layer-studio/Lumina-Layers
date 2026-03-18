# -*- coding: utf-8 -*-
"""
Mesh Builder 模块

并行/串行生成多材质 3D mesh 并组装到 trimesh.Scene 中。
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import trimesh

from config import PrinterConfig


def build_material_meshes(
    mesher,
    full_matrix: np.ndarray,
    target_h: int,
    pixel_scale: float,
    slot_names: list[str],
    preview_colors: dict,
) -> tuple[trimesh.Scene, list[str], np.ndarray]:
    """为每种材质生成 3D mesh 并组装到 Scene 中。

    Args:
        mesher: mesh 生成器实例（来自 core.mesh_generators.get_mesher）
        full_matrix: 完整体素矩阵 (layers, H, W)
        target_h: 目标高度（像素）
        pixel_scale: 像素缩放比例 (mm/px)
        slot_names: 材质槽名称列表
        preview_colors: 预览颜色字典 {mat_id: [R, G, B, A]}

    Returns:
        tuple: (scene, valid_slot_names, transform)
            - scene: 包含所有材质 mesh 的 trimesh.Scene
            - valid_slot_names: 成功生成的材质名称列表
            - transform: 4x4 变换矩阵
    """
    scene = trimesh.Scene()

    transform = np.eye(4)
    transform[0, 0] = pixel_scale
    transform[1, 1] = pixel_scale
    transform[2, 2] = PrinterConfig.LAYER_HEIGHT

    print(f"[CONVERTER] Transform: XY={pixel_scale}mm/px, Z={PrinterConfig.LAYER_HEIGHT}mm/layer")
    print(f"[CONVERTER] Using mesher: {mesher.__class__.__name__}")

    num_materials = len(slot_names)
    print(f"[CONVERTER] Generating meshes for {num_materials} materials...")

    max_workers = min(4, num_materials)
    parallel_enabled = max_workers > 1 and os.getenv("LUMINA_DISABLE_PARALLEL_MESH", "0") != "1"
    mesh_results = {}
    mesh_errors = {}

    if parallel_enabled:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_map = {
                pool.submit(mesher.generate_mesh, full_matrix, mat_id, target_h): mat_id
                for mat_id in range(num_materials)
            }
            for future in as_completed(future_map):
                mat_id = future_map[future]
                try:
                    mesh_results[mat_id] = future.result()
                except Exception as e:
                    mesh_errors[mat_id] = e
    else:
        for mat_id in range(num_materials):
            try:
                mesh_results[mat_id] = mesher.generate_mesh(full_matrix, mat_id, target_h)
            except Exception as e:
                mesh_errors[mat_id] = e

    valid_slot_names = []
    for mat_id in range(num_materials):
        if mat_id in mesh_errors:
            e = mesh_errors[mat_id]
            print(f"[CONVERTER] Error generating mesh for material {mat_id} ({slot_names[mat_id]}): {e}")
            print(f"[CONVERTER] Continuing with other materials...")
            continue
        mesh = mesh_results.get(mat_id)
        if mesh:
            mesh.apply_transform(transform)
            mesh.visual.face_colors = preview_colors[mat_id]
            name = slot_names[mat_id]
            mesh.metadata['name'] = name
            scene.add_geometry(mesh, node_name=name, geom_name=name)
            valid_slot_names.append(name)
            print(f"[CONVERTER] Added mesh for {name}")

    return scene, valid_slot_names, transform
