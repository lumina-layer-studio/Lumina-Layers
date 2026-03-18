# -*- coding: utf-8 -*-
"""Debug 预览保存模块

保存高保真模式的 debug 预览图，显示量化后的图像和轮廓。
"""

import os

import cv2
import numpy as np
from PIL import Image

from config import OUTPUT_DIR


def save_debug_preview(debug_data, material_matrix, mask_solid, image_path, mode_name, num_materials=4):
    """Save high-fidelity mode debug preview image.
    保存高保真模式的 debug 预览图。

    Shows the K-Means quantized image, which is the actual input the vectorizer receives.
    Optionally draws contours to show shape recognition results.

    Args:
        debug_data: Debug data dictionary
        material_matrix: Material matrix
        mask_solid: Solid mask
        image_path: Original image path
        mode_name: Mode name
        num_materials: Number of materials (4 or 6), default 4
    """
    quantized_image = debug_data['quantized_image']
    num_colors = debug_data['num_colors']

    print(f"[DEBUG_PREVIEW] Saving {mode_name} debug preview...")
    print(f"[DEBUG_PREVIEW] Quantized to {num_colors} colors")

    debug_img = quantized_image.copy()

    # Draw contours to show how the vectorizer interprets shapes
    try:
        contour_overlay = debug_img.copy()

        for mat_id in range(num_materials):
            mat_mask = np.zeros(material_matrix.shape[:2], dtype=np.uint8)
            for layer in range(material_matrix.shape[2]):
                mat_mask = np.logical_or(mat_mask, material_matrix[:, :, layer] == mat_id)

            mat_mask = np.logical_and(mat_mask, mask_solid).astype(np.uint8) * 255

            if not np.any(mat_mask):
                continue

            contours, _ = cv2.findContours(
                mat_mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
            )

            cv2.drawContours(contour_overlay, contours, -1, (0, 0, 0), 1)

        debug_img = contour_overlay
        print(f"[DEBUG_PREVIEW] Contours drawn on preview")

    except Exception as e:
        print(f"[DEBUG_PREVIEW] Warning: Could not draw contours: {e}")

    base_name = os.path.splitext(os.path.basename(image_path))[0]
    debug_path = os.path.join(OUTPUT_DIR, f"{base_name}_{mode_name}_Debug.png")

    debug_pil = Image.fromarray(debug_img, mode='RGB')
    debug_pil.save(debug_path, 'PNG')

    print(f"[DEBUG_PREVIEW] ✅ Saved: {debug_path}")
    print(f"[DEBUG_PREVIEW] This is the EXACT image the vectorizer sees before meshing")
