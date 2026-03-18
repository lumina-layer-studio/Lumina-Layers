# -*- coding: utf-8 -*-
"""体素矩阵构建模块

提供多种体素矩阵构建策略：
- build_voxel_matrix: 标准双面/单面
- build_voxel_matrix_6layer: 6 层（5-Color Extended）
- build_voxel_matrix_faceup: 面朝上单面
- build_relief_voxel_matrix: 2.5D 浮雕
- build_cloisonne_voxel_matrix: 掐丝珐琅
"""

import numpy as np

from config import PrinterConfig


def normalize_color_height_map(color_height_map: dict[str, float]) -> dict[str, float]:
    """Normalize hex keys to '#rrggbb' format.
    将 hex 键归一化为 '#rrggbb' 格式。
    """
    normalized = {}
    for key, value in color_height_map.items():
        if not key.startswith('#'):
            normalized[f'#{key}'] = value
        else:
            normalized[key] = value
    return normalized


def build_voxel_matrix(material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id=0):
    """Build complete voxel matrix with backing layer marked using special material_id.

    Args:
        material_matrix: (H, W, N) material matrix (N optical layers)
        mask_solid: (H, W) solid pixel mask
        spacer_thick: backing thickness (mm)
        structure_mode: "双面" or "单面" (Double-sided or Single-sided)
        backing_color_id: backing material ID (0-7), default is 0 (White)

    Returns:
        tuple: (full_matrix, backing_metadata)
    """
    if material_matrix.ndim != 3:
        raise ValueError(f"material_matrix must be 3D (H, W, N), got shape={material_matrix.shape}")
    target_h, target_w, optical_layers = material_matrix.shape
    mask_transparent = ~mask_solid

    bottom_voxels = np.transpose(material_matrix, (2, 0, 1))

    spacer_layers = max(1, int(round(spacer_thick / PrinterConfig.LAYER_HEIGHT)))

    if "双面" in structure_mode or "Double" in structure_mode:
        top_voxels = np.transpose(material_matrix[..., ::-1], (2, 0, 1))
        total_layers = optical_layers + spacer_layers + optical_layers
        full_matrix = np.full((total_layers, target_h, target_w), -1, dtype=int)

        full_matrix[0:optical_layers] = bottom_voxels

        spacer = np.full((target_h, target_w), -1, dtype=int)
        spacer[~mask_transparent] = backing_color_id
        for z in range(optical_layers, optical_layers + spacer_layers):
            full_matrix[z] = spacer

        full_matrix[optical_layers + spacer_layers:] = top_voxels

        backing_z_range = (optical_layers, optical_layers + spacer_layers - 1)
    else:
        total_layers = optical_layers + spacer_layers
        full_matrix = np.full((total_layers, target_h, target_w), -1, dtype=int)

        full_matrix[0:optical_layers] = bottom_voxels

        spacer = np.full((target_h, target_w), -1, dtype=int)
        spacer[~mask_transparent] = backing_color_id
        for z in range(optical_layers, total_layers):
            full_matrix[z] = spacer

        backing_z_range = (optical_layers, total_layers - 1)

    backing_metadata = {
        'backing_color_id': backing_color_id,
        'backing_z_range': backing_z_range
    }

    return full_matrix, backing_metadata


def build_voxel_matrix_6layer(material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id=0):
    """Build complete voxel matrix for 6-layer structures (5-Color Extended mode)."""
    return build_voxel_matrix(
        material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id=backing_color_id
    )


def build_voxel_matrix_faceup(material_matrix, mask_solid, spacer_thick, backing_color_id=0):
    """Face-up voxel matrix for 5-Color Extended mode.

    Orientation: backing at the bottom (print-bed side), viewing surface at the top.
    The model is printed right-side-up — no post-print flipping required.
    """
    target_h, target_w, optical_layers = material_matrix.shape
    spacer_layers = max(1, int(round(spacer_thick / PrinterConfig.LAYER_HEIGHT)))
    total_layers = spacer_layers + optical_layers
    full_matrix = np.full((total_layers, target_h, target_w), -1, dtype=int)

    # Backing: solid block at the bottom
    spacer = np.where(mask_solid, backing_color_id, -1).astype(int)
    full_matrix[:spacer_layers] = spacer[np.newaxis, :, :]

    # Optical: reversed order so index 0 (viewing surface) → highest Z
    for i in range(optical_layers):
        layer = material_matrix[:, :, optical_layers - 1 - i]
        z = spacer_layers + i
        full_matrix[z] = np.where(mask_solid, layer, -1)

    backing_z_range = (0, spacer_layers - 1)
    return full_matrix, {
        'backing_color_id': backing_color_id,
        'backing_z_range': backing_z_range,
    }


def build_cloisonne_voxel_matrix(material_matrix, mask_solid, mask_wireframe,
                                 spacer_thick, wire_height_mm,
                                 backing_color_id=0):
    """Build voxel matrix for cloisonné (掐丝珐琅) mode.

    Layer structure (bottom → top, Z ascending):
        Z = 0 … spacer_layers-1   : Base / backing  (backing_color_id)
        Z = spacer_layers … +4    : Colour layers   (material_matrix, flipped for face-up)
        Z = spacer_layers+5 … +N  : Wire layers     (-3 marker, separate object)
    """
    target_h, target_w = material_matrix.shape[:2]
    OPTICAL = PrinterConfig.COLOR_LAYERS  # 5

    spacer_layers = max(1, int(round(spacer_thick / PrinterConfig.LAYER_HEIGHT)))
    wire_layers = max(1, int(round(wire_height_mm / PrinterConfig.LAYER_HEIGHT)))

    total_z = spacer_layers + OPTICAL + wire_layers
    full_matrix = np.full((total_z, target_h, target_w), -1, dtype=int)

    # --- Base / backing ---
    spacer_slice = np.where(mask_solid, backing_color_id, -1).astype(int)
    full_matrix[:spacer_layers] = spacer_slice[np.newaxis, :, :]

    # --- Colour layers (face-up: reverse material order) ---
    colour_start = spacer_layers
    for i in range(OPTICAL):
        layer = material_matrix[:, :, OPTICAL - 1 - i]
        z = colour_start + i
        full_matrix[z] = np.where(mask_solid, layer, -1)

    # --- Wire layers ---
    wire_mask_2d = mask_wireframe & mask_solid
    wire_slice = np.where(wire_mask_2d, -3, -1).astype(int)
    wire_start = colour_start + OPTICAL
    full_matrix[wire_start:] = wire_slice[np.newaxis, :, :]

    backing_z_range = (0, spacer_layers - 1)
    backing_metadata = {
        'backing_color_id': backing_color_id,
        'backing_z_range': backing_z_range,
        'is_cloisonne': True,
        'wire_layers': wire_layers,
    }

    print(f"[CLOISONNE] Voxel matrix: {full_matrix.shape} "
          f"(base={spacer_layers}, colour={OPTICAL}, wire={wire_layers})")
    return full_matrix, backing_metadata


def build_relief_voxel_matrix(matched_rgb, material_matrix, mask_solid, color_height_map,
                              default_height, structure_mode, backing_color_id, pixel_scale,
                              height_matrix=None):
    """Build 2.5D relief voxel matrix with per-color or per-pixel variable heights.

    Supports two modes:
    1. Color height map mode (default): heights assigned by color
    2. Heightmap mode: heights from external grayscale heightmap (per-pixel)
    """
    color_height_map = normalize_color_height_map(color_height_map)

    target_h, target_w = material_matrix.shape[:2]

    # Constants
    OPTICAL_LAYERS = 5
    OPTICAL_THICKNESS_MM = OPTICAL_LAYERS * PrinterConfig.LAYER_HEIGHT  # 0.4mm

    print(f"[RELIEF] Building 2.5D relief voxel matrix...")
    print(f"[RELIEF] Optical layer thickness: {OPTICAL_THICKNESS_MM}mm ({OPTICAL_LAYERS} layers)")

    # Step 1: Build per-pixel height matrix
    if height_matrix is not None:
        print(f"[RELIEF] 🗺️ 使用高度图模式（逐像素高度）")
        pixel_heights = height_matrix.copy()
        pixel_heights[mask_solid & (pixel_heights < OPTICAL_THICKNESS_MM)] = OPTICAL_THICKNESS_MM
    else:
        pixel_heights = np.full((target_h, target_w), default_height, dtype=np.float32)
        for y in range(target_h):
            for x in range(target_w):
                if not mask_solid[y, x]:
                    continue
                r, g, b = matched_rgb[y, x]
                hex_color = f'#{r:02x}{g:02x}{b:02x}'
                if hex_color in color_height_map:
                    pixel_heights[y, x] = color_height_map[hex_color]

    # Step 2: Calculate max height to determine total Z layers
    max_height_mm = np.max(pixel_heights[mask_solid]) if np.any(mask_solid) else default_height
    max_z_layers = max(OPTICAL_LAYERS + 1, int(np.ceil(max_height_mm / PrinterConfig.LAYER_HEIGHT)))

    print(f"[RELIEF] Max height: {max_height_mm:.2f}mm ({max_z_layers} layers)")
    if np.any(mask_solid):
        print(f"[RELIEF] Height range: {np.min(pixel_heights[mask_solid]):.2f}mm - {max_height_mm:.2f}mm")

    # Step 3: Initialize voxel matrix
    full_matrix = np.full((max_z_layers, target_h, target_w), -1, dtype=int)

    # Step 4: Fill voxel matrix
    if height_matrix is not None:
        # Vectorized fill for heightmap mode
        target_z_layers = np.ceil(pixel_heights / PrinterConfig.LAYER_HEIGHT).astype(int)
        target_z_layers = np.clip(target_z_layers, OPTICAL_LAYERS, max_z_layers)
        optical_start_z = target_z_layers - OPTICAL_LAYERS

        for z in range(max_z_layers):
            backing_mask = mask_solid & (z < optical_start_z)
            full_matrix[z][backing_mask] = backing_color_id

        solid_ys, solid_xs = np.where(mask_solid)
        for layer_idx in range(OPTICAL_LAYERS):
            z_positions = optical_start_z + layer_idx
            for i in range(len(solid_ys)):
                y, x = solid_ys[i], solid_xs[i]
                z = z_positions[y, x]
                if z < max_z_layers:
                    mat_id = material_matrix[y, x, OPTICAL_LAYERS - 1 - layer_idx]
                    full_matrix[z, y, x] = mat_id
    else:
        # Original per-pixel loop for color height map mode
        for y in range(target_h):
            for x in range(target_w):
                if not mask_solid[y, x]:
                    continue
                target_height_mm = max(0.08, pixel_heights[y, x])
                target_z_layers_px = int(np.ceil(target_height_mm / PrinterConfig.LAYER_HEIGHT))
                target_z_layers_px = max(OPTICAL_LAYERS, min(target_z_layers_px, max_z_layers))
                optical_start_z_px = target_z_layers_px - OPTICAL_LAYERS
                for z in range(optical_start_z_px):
                    full_matrix[z, y, x] = backing_color_id
                for layer_idx in range(OPTICAL_LAYERS):
                    z = optical_start_z_px + layer_idx
                    if z < max_z_layers:
                        mat_id = material_matrix[y, x, OPTICAL_LAYERS - 1 - layer_idx]
                        full_matrix[z, y, x] = mat_id

    # Step 5: Relief mode is always single-sided
    backing_z_range = (0, max_z_layers - OPTICAL_LAYERS - 1)

    backing_metadata = {
        'backing_color_id': backing_color_id,
        'backing_z_range': backing_z_range,
        'is_relief': True,
        'max_height_mm': max_height_mm
    }

    print(f"[RELIEF] ✅ Relief voxel matrix built: {full_matrix.shape}")
    print(f"[RELIEF] Backing range: Z={backing_z_range[0]} to Z={backing_z_range[1]}")
    print(f"[RELIEF] Mode: Single-sided (viewing surface on top)")

    return full_matrix, backing_metadata
