# -*- coding: utf-8 -*-
"""3D 预览网格生成模块

为浏览器显示创建简化的 3D 预览网格。
"""

import cv2
import numpy as np
import trimesh


def create_preview_mesh(matched_rgb, mask_solid, total_layers,
                        backing_color_id=0, backing_z_range=None, preview_colors=None):
    """Create simplified 3D preview mesh for browser display.
    为浏览器显示创建简化的 3D 预览网格。

    Args:
        matched_rgb: (H, W, 3) RGB color array
        mask_solid: (H, W) boolean mask of solid pixels
        total_layers: Total number of Z layers
        backing_color_id: Backing material ID (0-7), default 0
        backing_z_range: (start_z, end_z) tuple or None
        preview_colors: List of preview colors for materials

    Returns:
        trimesh.Trimesh or None
    """
    height, width = matched_rgb.shape[:2]
    total_pixels = width * height

    SIMPLIFY_THRESHOLD = 500_000
    TARGET_PIXELS = 300_000

    if total_pixels > SIMPLIFY_THRESHOLD:
        scale_factor = int(np.sqrt(total_pixels / TARGET_PIXELS))
        scale_factor = max(2, min(scale_factor, 16))

        print(f"[PREVIEW] Downsampling by {scale_factor}x ({total_pixels:,} -> ~{TARGET_PIXELS:,} pixels)")

        new_height = height // scale_factor
        new_width = width // scale_factor

        matched_rgb = cv2.resize(
            matched_rgb, (new_width, new_height),
            interpolation=cv2.INTER_AREA
        )
        mask_solid = cv2.resize(
            mask_solid.astype(np.uint8), (new_width, new_height),
            interpolation=cv2.INTER_NEAREST
        ).astype(bool)

        height, width = new_height, new_width
        shrink = 0.05 * scale_factor
    else:
        shrink = 0.05

    vertices = []
    faces = []
    face_colors = []

    for y in range(height):
        for x in range(width):
            if not mask_solid[y, x]:
                continue

            rgb = matched_rgb[y, x]
            rgba = [int(rgb[0]), int(rgb[1]), int(rgb[2]), 255]

            world_y = (height - 1 - y)
            x0, x1 = x + shrink, x + 1 - shrink
            y0, y1 = world_y + shrink, world_y + 1 - shrink

            cube_faces = [
                [0, 2, 1], [0, 3, 2],
                [4, 5, 6], [4, 6, 7],
                [0, 1, 5], [0, 5, 4],
                [1, 2, 6], [1, 6, 5],
                [2, 3, 7], [2, 7, 6],
                [3, 0, 4], [3, 4, 7]
            ]

            if backing_z_range is not None and preview_colors is not None:
                backing_start, backing_end = backing_z_range

                # Backing layer box
                z0_backing = backing_start
                z1_backing = backing_end + 1

                base_idx = len(vertices)
                vertices.extend([
                    [x0, y0, z0_backing], [x1, y0, z0_backing], [x1, y1, z0_backing], [x0, y1, z0_backing],
                    [x0, y0, z1_backing], [x1, y0, z1_backing], [x1, y1, z1_backing], [x0, y1, z1_backing]
                ])

                actual_backing_color_id = 0 if backing_color_id == -2 else backing_color_id
                backing_rgba = [int(preview_colors[actual_backing_color_id][0]),
                               int(preview_colors[actual_backing_color_id][1]),
                               int(preview_colors[actual_backing_color_id][2]), 255]

                for f in cube_faces:
                    faces.append([v + base_idx for v in f])
                    face_colors.append(backing_rgba)

                # Bottom layers (0 to backing_start)
                if backing_start > 0:
                    base_idx = len(vertices)
                    vertices.extend([
                        [x0, y0, 0], [x1, y0, 0], [x1, y1, 0], [x0, y1, 0],
                        [x0, y0, backing_start], [x1, y0, backing_start],
                        [x1, y1, backing_start], [x0, y1, backing_start]
                    ])
                    for f in cube_faces:
                        faces.append([v + base_idx for v in f])
                        face_colors.append(rgba)

                # Top layers (backing_end+1 to total_layers)
                if backing_end + 1 < total_layers:
                    z0_top = backing_end + 1
                    base_idx = len(vertices)
                    vertices.extend([
                        [x0, y0, z0_top], [x1, y0, z0_top], [x1, y1, z0_top], [x0, y1, z0_top],
                        [x0, y0, total_layers], [x1, y0, total_layers],
                        [x1, y1, total_layers], [x0, y1, total_layers]
                    ])
                    for f in cube_faces:
                        faces.append([v + base_idx for v in f])
                        face_colors.append(rgba)
            else:
                # Original behavior: single box from 0 to total_layers
                base_idx = len(vertices)
                vertices.extend([
                    [x0, y0, 0], [x1, y0, 0], [x1, y1, 0], [x0, y1, 0],
                    [x0, y0, total_layers], [x1, y0, total_layers],
                    [x1, y1, total_layers], [x0, y1, total_layers]
                ])
                for f in cube_faces:
                    faces.append([v + base_idx for v in f])
                    face_colors.append(rgba)

    if not vertices:
        return None

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
    mesh.visual.face_colors = np.array(face_colors, dtype=np.uint8)

    print(f"[PREVIEW] Generated: {len(mesh.vertices):,} vertices, {len(mesh.faces):,} faces")

    return mesh
