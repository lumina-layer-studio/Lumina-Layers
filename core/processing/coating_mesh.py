# -*- coding: utf-8 -*-
"""
Coating Mesh 生成模块

生成透明涂层（coating）mesh，覆盖在模型表面。
"""

from __future__ import annotations

import cv2
import numpy as np
import trimesh

from config import PrinterConfig


def generate_coating_mesh(
    mask_solid: np.ndarray,
    target_h: int,
    target_w: int,
    pixel_scale: float,
    coating_height_mm: float,
    mesher,
    enable_outline: bool = False,
    outline_width: float = 2.0,
) -> trimesh.Trimesh | None:
    """生成透明涂层 mesh。

    Args:
        mask_solid: 实体掩码 (H, W)
        target_h: 目标高度（像素）
        target_w: 目标宽度（像素）
        pixel_scale: 像素缩放比例 (mm/px)
        coating_height_mm: 涂层高度 (mm)
        mesher: mesh 生成器实例
        enable_outline: 是否启用轮廓（涂层需要覆盖轮廓区域）
        outline_width: 轮廓宽度 (mm)

    Returns:
        生成的 coating mesh，失败返回 None
    """
    coating_layers = max(1, int(round(coating_height_mm / PrinterConfig.LAYER_HEIGHT)))
    print(f"[CONVERTER] 🪟 Generating coating: height={coating_height_mm}mm ({coating_layers} layers)")

    try:
        coating_mask = mask_solid.copy()
        if enable_outline:
            outline_width_px = max(1, int(round(outline_width / pixel_scale)))
            kernel = np.ones((3, 3), np.uint8)
            mask_uint8 = mask_solid.astype(np.uint8) * 255
            dilated_mask = cv2.dilate(mask_uint8, kernel, iterations=outline_width_px)
            coating_mask = (dilated_mask > 0)

        coating_matrix = np.full((coating_layers, target_h, target_w), -1, dtype=int)
        coating_slice = np.where(coating_mask, 0, -1).astype(int)
        coating_matrix[:] = coating_slice[np.newaxis, :, :]

        coating_mesh = mesher.generate_mesh(coating_matrix, 0, target_h)
        if coating_mesh and len(coating_mesh.vertices) > 0:
            coat_transform = np.eye(4)
            coat_transform[0, 0] = pixel_scale
            coat_transform[1, 1] = pixel_scale
            coat_transform[2, 2] = PrinterConfig.LAYER_HEIGHT
            coat_transform[2, 3] = -coating_layers * PrinterConfig.LAYER_HEIGHT
            coating_mesh.apply_transform(coat_transform)
            coating_mesh.visual.face_colors = [200, 200, 200, 80]
            coating_name = "Coating"
            coating_mesh.metadata['name'] = coating_name
            print(f"[CONVERTER] ✅ Coating added ({coating_layers} layers)")
            return coating_mesh
        else:
            print(f"[CONVERTER] Warning: Coating mesh empty, skipping")
            return None
    except Exception as e:
        print(f"[CONVERTER] Coating generation failed: {e}")
        import traceback; traceback.print_exc()
        return None
