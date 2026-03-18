# -*- coding: utf-8 -*-
"""描边网格生成模块

在模型外轮廓生成环形描边 mesh，用于 3MF 导出和 GLB 预览。
"""

import cv2
import numpy as np
import trimesh

from config import PrinterConfig


def generate_outline_mesh(mask_solid, pixel_scale, outline_width_mm, outline_thickness_mm, target_h):
    """Generate a ring-shaped outline mesh around the outer contour of the model.
    在模型外轮廓周围生成环形描边网格。

    Algorithm:
    1. Dilate the mask outward by outline_width_mm
    2. Create ring = dilated - original
    3. Extrude the ring to outline_thickness_mm height

    Args:
        mask_solid: (H, W) boolean mask of solid pixels
        pixel_scale: mm per pixel
        outline_width_mm: Width of the outline in mm
        outline_thickness_mm: Thickness (height) of the outline in mm
        target_h: Image height in pixels

    Returns:
        trimesh.Trimesh or None
    """
    # Convert outline width from mm to pixels
    outline_width_px = max(1, int(round(outline_width_mm / pixel_scale)))

    # Convert thickness from mm to layers
    outline_layers = max(1, int(round(outline_thickness_mm / PrinterConfig.LAYER_HEIGHT)))

    print(f"[OUTLINE] Width: {outline_width_mm}mm = {outline_width_px}px, "
          f"Thickness: {outline_thickness_mm}mm = {outline_layers} layers")

    # [FIX] Pad the mask before dilation so edges touching image boundaries
    # can still expand outward. Without padding, cv2.dilate treats the border
    # as zeros and the outline ring is missing on boundary-touching sides.
    pad = outline_width_px + 1
    mask_uint8 = mask_solid.astype(np.uint8) * 255
    padded_mask = cv2.copyMakeBorder(mask_uint8, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)

    # Dilate the padded mask outward
    kernel = np.ones((3, 3), np.uint8)
    dilated = cv2.dilate(padded_mask, kernel, iterations=outline_width_px)

    # Also pad the original mask for subtraction
    padded_original = cv2.copyMakeBorder(mask_uint8, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)

    # Ring = dilated minus original (in padded space, preserving outline beyond image edges)
    ring_mask = (dilated > 0) & ~(padded_original > 0)

    # Use padded dimensions for mesh generation; offset coordinates by -pad later
    h, w = ring_mask.shape
    # h_original is needed for Y-flip coordinate conversion
    h_original = mask_solid.shape[0]

    if not np.any(ring_mask):
        print(f"[OUTLINE] Ring mask is empty, skipping")
        return None

    ring_pixel_count = np.sum(ring_mask)
    print(f"[OUTLINE] Ring mask: {ring_pixel_count} pixels")

    # Use greedy rectangle merging to generate optimized mesh
    processed = np.zeros_like(ring_mask, dtype=bool)
    vertices = []
    faces = []

    for y in range(h):
        row_valid = ring_mask[y] & ~processed[y]
        if not np.any(row_valid):
            continue

        padded_row = np.concatenate([[False], row_valid, [False]])
        diff = np.diff(padded_row.astype(np.int8))
        starts = np.where(diff == 1)[0]
        ends = np.where(diff == -1)[0]

        for x_start, x_end in zip(starts, ends):
            if processed[y, x_start]:
                continue

            y_end = y + 1
            while y_end < h:
                seg_mask = ring_mask[y_end, x_start:x_end]
                seg_proc = processed[y_end, x_start:x_end]
                if not (np.all(seg_mask) and not np.any(seg_proc)):
                    break
                y_end += 1

            processed[y:y_end, x_start:x_end] = True

            # Convert to world coordinates (flip Y, apply scale)
            # Subtract pad offset so coordinates align with the original (unpadded) model
            world_x0 = float(x_start - pad) * pixel_scale
            world_x1 = float(x_end - pad) * pixel_scale
            world_y0 = float(h_original - (y_end - pad)) * pixel_scale
            world_y1 = float(h_original - (y - pad)) * pixel_scale
            z_bot = 0.0
            z_tp = float(outline_layers) * PrinterConfig.LAYER_HEIGHT

            base_idx = len(vertices)
            vertices.extend([
                [world_x0, world_y0, z_bot], [world_x1, world_y0, z_bot],
                [world_x1, world_y1, z_bot], [world_x0, world_y1, z_bot],
                [world_x0, world_y0, z_tp], [world_x1, world_y0, z_tp],
                [world_x1, world_y1, z_tp], [world_x0, world_y1, z_tp]
            ])
            cube_faces = [
                [0, 2, 1], [0, 3, 2],
                [4, 5, 6], [4, 6, 7],
                [0, 1, 5], [0, 5, 4],
                [1, 2, 6], [1, 6, 5],
                [2, 3, 7], [2, 7, 6],
                [3, 0, 4], [3, 4, 7]
            ]
            faces.extend([[v + base_idx for v in f] for f in cube_faces])

    if not vertices:
        return None

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
    mesh.merge_vertices()
    mesh.update_faces(mesh.unique_faces())

    print(f"[OUTLINE] ✅ Generated outline mesh: {len(mesh.vertices):,} verts, {len(mesh.faces):,} faces")
    return mesh
