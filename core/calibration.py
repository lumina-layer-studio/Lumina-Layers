"""
Lumina Studio - Calibration Generator Module

Generates calibration boards for physical color testing.
"""

import os
from typing import Optional
import itertools
import zipfile

import numpy as np
import trimesh
from PIL import Image

from colormath.color_objects import sRGBColor, LabColor
from colormath.color_conversions import convert_color
from colormath.color_diff import delta_e_cie2000

from config import PrinterConfig, ColorSystem, SmartConfig, OUTPUT_DIR, get_asset_path
from core.naming import generate_calibration_filename
from utils import Stats
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata


def _generate_voxel_mesh(voxel_matrix: np.ndarray, material_index: int,
                          grid_h: int, grid_w: int) -> Optional[trimesh.Trimesh]:
    """
    Generate mesh for a specific material from voxel data.
    
    Args:
        voxel_matrix: 3D array of material indices (Z, H, W)
        material_index: Material ID to generate mesh for
        grid_h: Grid height in voxels
        grid_w: Grid width in voxels
    
    Returns:
        Trimesh object or None if no voxels found
    """
    scale_x = PrinterConfig.NOZZLE_WIDTH
    scale_y = PrinterConfig.NOZZLE_WIDTH
    scale_z = PrinterConfig.LAYER_HEIGHT
    shrink = PrinterConfig.SHRINK_OFFSET

    vertices, faces = [], []
    total_z_layers = voxel_matrix.shape[0]

    for z in range(total_z_layers):
        z_bottom, z_top = z * scale_z, (z + 1) * scale_z
        layer_mask = (voxel_matrix[z] == material_index)
        if not np.any(layer_mask):
            continue

        for y in range(grid_h):
            world_y = y * scale_y
            row = layer_mask[y]
            padded_row = np.pad(row, (1, 1), mode='constant')
            diff = np.diff(padded_row.astype(int))
            starts, ends = np.where(diff == 1)[0], np.where(diff == -1)[0]

            for start, end in zip(starts, ends):
                x0, x1 = start * scale_x + shrink, end * scale_x - shrink
                y0, y1 = world_y + shrink, world_y + scale_y - shrink

                base_idx = len(vertices)
                vertices.extend([
                    [x0, y0, z_bottom], [x1, y0, z_bottom], [x1, y1, z_bottom], [x0, y1, z_bottom],
                    [x0, y0, z_top], [x1, y0, z_top], [x1, y1, z_top], [x0, y1, z_top]
                ])
                cube_faces = [
                    [0, 2, 1], [0, 3, 2], [4, 5, 6], [4, 6, 7],
                    [0, 1, 5], [0, 5, 4], [1, 2, 6], [1, 6, 5],
                    [2, 3, 7], [2, 7, 6], [3, 0, 4], [3, 4, 7]
                ]
                faces.extend([[v + base_idx for v in f] for f in cube_faces])

    if not vertices:
        return None

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
    mesh.merge_vertices()
    mesh.update_faces(mesh.unique_faces())
    return mesh


def generate_calibration_board(color_mode: str, block_size_mm: float,
                                gap_mm: float, backing_color: str):
    """
    Generate a 1024-color calibration board as 3MF.
    
    Args:
        color_mode: Color system mode (CMYW/RYBW)
        block_size_mm: Size of each color block in mm
        gap_mm: Gap between blocks in mm
        backing_color: Color name for backing layer
    
    Returns:
        Tuple of (output_path, preview_image, status_message)
    """
    color_conf = ColorSystem.get(color_mode)
    slot_names = color_conf['slots']
    preview_colors = color_conf['preview']
    color_map = color_conf['map']

    backing_id = color_map.get(backing_color, 0)

    grid_dim, padding = 32, 1
    total_w = total_h = grid_dim + (padding * 2)

    pixels_per_block = max(1, int(block_size_mm / PrinterConfig.NOZZLE_WIDTH))
    pixels_gap = max(1, int(gap_mm / PrinterConfig.NOZZLE_WIDTH))

    voxel_w = total_w * (pixels_per_block + pixels_gap)
    voxel_h = total_h * (pixels_per_block + pixels_gap)

    backing_layers = int(PrinterConfig.BACKING_MM / PrinterConfig.LAYER_HEIGHT)
    total_layers = PrinterConfig.COLOR_LAYERS + backing_layers

    full_matrix = np.full((total_layers, voxel_h, voxel_w), backing_id, dtype=int)

    # Generate 1024 permutations (4^5 combinations)
    for i in range(1024):
        digits = []
        temp = i
        for _ in range(5):
            digits.append(temp % 4)
            temp //= 4
        stack = digits[::-1]

        row = (i // grid_dim) + padding
        col = (i % grid_dim) + padding
        px = col * (pixels_per_block + pixels_gap)
        py = row * (pixels_per_block + pixels_gap)

        for z in range(PrinterConfig.COLOR_LAYERS):
            full_matrix[z, py:py+pixels_per_block, px:px+pixels_per_block] = stack[z]

    # Set corner markers with mode-specific colors
    if "RYBW" in color_mode:
        corners = [
            (0, 0, 0),              # TL = White
            (0, total_w-1, 1),      # TR = Red
            (total_h-1, total_w-1, 3),  # BR = Blue
            (total_h-1, 0, 2)       # BL = Yellow
        ]
    else:  # CMYW
        corners = [
            (0, 0, 0),              # TL = White
            (0, total_w-1, 1),      # TR = Cyan
            (total_h-1, total_w-1, 2),  # BR = Magenta
            (total_h-1, 0, 3)       # BL = Yellow
        ]

    for r, c, mat_id in corners:
        px = c * (pixels_per_block + pixels_gap)
        py = r * (pixels_per_block + pixels_gap)
        for z in range(PrinterConfig.COLOR_LAYERS):
            full_matrix[z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id

    # Build 3MF scene
    scene = trimesh.Scene()
    for mat_id in range(4):
        mesh = _generate_voxel_mesh(full_matrix, mat_id, voxel_h, voxel_w)
        if mesh:
            mesh.visual.face_colors = preview_colors[mat_id]
            name = slot_names[mat_id]
            mesh.metadata['name'] = name
            scene.add_geometry(mesh, node_name=name, geom_name=name)

    # Export with BambuStudio metadata
    output_path = os.path.join(OUTPUT_DIR, generate_calibration_filename(color_mode, "Standard"))
    
    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=output_path,
        slot_names=slot_names,
        preview_colors=preview_colors,
        settings={
            'layer_height': '0.08',
            'initial_layer_height': '0.08',
            'wall_loops': '1',
            'top_shell_layers': '0',
            'bottom_shell_layers': '0',
            'sparse_infill_density': '100%',
            'sparse_infill_pattern': 'zig-zag',
        },
        color_mode=color_mode
    )

    # Generate preview
    bottom_layer = full_matrix[0].astype(np.uint8)
    preview_arr = np.zeros((voxel_h, voxel_w, 3), dtype=np.uint8)
    for mat_id, rgba in preview_colors.items():
        preview_arr[bottom_layer == mat_id] = rgba[:3]

    Stats.increment("calibrations")

    return output_path, Image.fromarray(preview_arr), f"[OK] 校准板已生成！已组合为一个对象 | 颜色: {', '.join(slot_names)}"



# ========== Lumina Smart 1296 (6-Color System) ==========

def get_top_1296_colors():
    """
    Intelligent color selection algorithm for 6-color system.
    
    Returns 1296 most representative color combinations from 7776 possible
    combinations (6^5) to fill a 36x36 grid without gaps.
    
    This function is public and can be called by image_processing.py to
    reconstruct the stacking order.
    
    Returns:
        List of 1296 tuples, each representing a 5-layer color stack
    """
    print("[SMART] Simulating 6^5 = 7776 combinations...")
    
    # Simulate all combinations in Lab color space
    candidates = []
    filaments = SmartConfig.FILAMENTS
    layer_h = PrinterConfig.LAYER_HEIGHT
    backing = np.array([255, 255, 255])
    
    # Pre-calculate single layer alpha values
    alphas = {}
    for fid, props in filaments.items():
        bd = props['td'] / 10.0
        alphas[fid] = min(1.0, layer_h / bd) if bd > 0 else 1.0
    
    # Generate all 6^5 combinations
    for stack in itertools.product(range(6), repeat=5):
        # Fast color mixing simulation
        curr = backing.astype(float)
        for fid in stack:
            rgb = np.array(filaments[fid]['rgb'])
            a = alphas[fid]
            curr = rgb * a + curr * (1.0 - a)
        
        final_rgb = curr.astype(np.uint8)
        
        # Convert to Lab for color difference calculation
        srgb = sRGBColor(final_rgb[0]/255.0, final_rgb[1]/255.0, final_rgb[2]/255.0)
        lab = convert_color(srgb, LabColor)
        
        candidates.append({
            "stack": stack,
            "lab": lab,
            "rgb": final_rgb
        })
    
    print(f"[SMART] Total candidates: {len(candidates)}. Filtering top 1296...")
    
    # Greedy selection algorithm
    selected = []
    
    # Pre-select seed colors (6 pure colors)
    for i in range(6):
        stack = (i,) * 5
        for c in candidates:
            if c['stack'] == stack:
                selected.append(c)
                break
    
    print(f"[SMART] Seed colors: {len(selected)}")
    
    # Round 1: High quality selection (RGB distance > 8)
    target = 1296
    for c in candidates:
        if len(selected) >= target:
            break
        if any(c['stack'] == s['stack'] for s in selected):
            continue
        
        is_distinct = True
        for s in selected:
            if np.linalg.norm(c['rgb'].astype(int) - s['rgb'].astype(int)) < 8:
                is_distinct = False
                break
        
        if is_distinct:
            selected.append(c)
    
    print(f"[SMART] Round 1 (High Quality) selected: {len(selected)}")
    
    # Round 2: Fill remaining slots with lower threshold
    if len(selected) < target:
        print(f"[SMART] Filling remaining {target - len(selected)} spots...")
        for c in candidates:
            if len(selected) >= target:
                break
            if any(c['stack'] == s['stack'] for s in selected):
                continue
            selected.append(c)
    
    print(f"[SMART] Final selection: {len(selected)} colors")
    
    return [s['stack'] for s in selected[:target]]


def generate_smart_board(block_size_mm=5.0, gap_mm=0.8):
    """
    Generate Lumina Smart 1296 (6-Color) calibration board with 38x38 border layout.
    
    Features:
    - 38x38 physical grid (36x36 data + 2 border protection)
    - 1296 intelligently selected color blocks
    - Corner alignment markers in outermost ring
    - Face Down printing optimization
    
    Args:
        block_size_mm: Size of each color block in mm
        gap_mm: Gap between blocks in mm
    
    Returns:
        Tuple of (output_path, preview_image, status_message)
    """
    print("[SMART] Generating Smart 1296 calibration board (38x38 Layout)...")
    
    # Get 1296 intelligently selected colors
    stacks = get_top_1296_colors()
    
    # Geometry parameters (38x38 layout)
    data_dim = 36
    padding = 1
    total_dim = data_dim + 2 * padding
    block_w = float(block_size_mm)
    gap = float(gap_mm)
    margin = 5.0
    
    # Calculate board dimensions (based on 38x38)
    board_w = margin * 2 + total_dim * block_w + (total_dim - 1) * gap
    board_h = board_w
    
    print(f"[SMART] Board size: {board_w:.1f} x {board_h:.1f} mm (Grid: {total_dim}x{total_dim})")
    
    # Get color configuration
    color_conf = ColorSystem.SIX_COLOR
    preview_colors = color_conf['preview']
    slot_names = color_conf['slots']
    
    # Calculate voxel grid dimensions (based on 38x38)
    pixels_per_block = max(1, int(block_w / PrinterConfig.NOZZLE_WIDTH))
    pixels_gap = max(1, int(gap / PrinterConfig.NOZZLE_WIDTH))
    
    voxel_w = total_dim * (pixels_per_block + pixels_gap)
    voxel_h = total_dim * (pixels_per_block + pixels_gap)
    
    # Layer configuration
    color_layers = 5
    backing_layers = int(PrinterConfig.BACKING_MM / PrinterConfig.LAYER_HEIGHT)
    total_layers = color_layers + backing_layers
    
    # Initialize voxel matrix (filled with White Slot 0)
    full_matrix = np.full((total_layers, voxel_h, voxel_w), 0, dtype=int)
    
    print(f"[SMART] Voxel matrix: {total_layers} x {voxel_h} x {voxel_w}")
    
    # 约定转换：get_top_1296_colors() 返回底到顶约定 (stack[0]=背面，stack[4]=观赏面)
    # 转换为顶到底约定 (stack[0]=观赏面，stack[4]=背面)，与 4 色模式统一
    stacks = [tuple(reversed(s)) for s in stacks]
    
    # Fill 1296 intelligent color blocks (with padding offset)
    for idx, stack in enumerate(stacks):
        # Data area logical coordinates (0..35)
        r_data = idx // data_dim
        c_data = idx % data_dim
        
        # Physical area coordinates (with border offset -> 1..36)
        row = r_data + padding
        col = c_data + padding
        
        px = col * (pixels_per_block + pixels_gap)
        py = row * (pixels_per_block + pixels_gap)
        
        # Fill 5 color layers (直接映射，与 4 色模式一致)
        # Z=0 (physical first layer) = viewing surface = stack[0] (顶到底约定)
        # Z=4 (physical fifth layer) = internal layer = stack[4] (顶到底约定)
        for z in range(color_layers):
            mat_id = stack[z]
            full_matrix[z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
    
    # Set corner alignment markers (in outermost ring 0 and 37)
    # TL: White (0), TR: Cyan (1), BR: Magenta (2), BL: Yellow (4)
    corners = [
        (0, 0, 0),                      # TL = White
        (0, total_dim-1, 1),            # TR = Cyan
        (total_dim-1, total_dim-1, 2),  # BR = Magenta
        (total_dim-1, 0, 4)             # BL = Yellow
    ]
    
    # Set corner alignment markers (in outermost ring)
    # TL: White (0), TR: Cyan (1), BR: Magenta (2), BL: Yellow (4)
    # Place markers on viewing surface (Z=0) for visual identification after printing
    # Face-Down mode: viewing surface is at Z=0 (first printed layer)
    viewing_surface_z = 0  # Z index of viewing surface (first printed layer in Face-Down mode)
    for r, c, mat_id in corners:
        px = c * (pixels_per_block + pixels_gap)
        py = r * (pixels_per_block + pixels_gap)
        full_matrix[viewing_surface_z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
    
    # Generate 3MF scene
    scene = trimesh.Scene()
    
    for mat_id in range(6):
        mesh = _generate_voxel_mesh(full_matrix, mat_id, voxel_h, voxel_w)
        if mesh:
            mesh.visual.face_colors = preview_colors[mat_id]
            name = slot_names[mat_id]
            mesh.metadata['name'] = name
            scene.add_geometry(mesh, node_name=name, geom_name=name)
    
    # Export
    output_path = os.path.join(OUTPUT_DIR, generate_calibration_filename("6-Color", "Smart1296"))
    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=output_path,
        slot_names=slot_names,
        preview_colors=preview_colors,
        settings={
            'layer_height': '0.08',
            'initial_layer_height': '0.08',
            'wall_loops': '1',
            'top_shell_layers': '0',
            'bottom_shell_layers': '0',
            'sparse_infill_density': '100%',
            'sparse_infill_pattern': 'zig-zag',
        },
        color_mode="6-Color"
    )
    
    # Generate preview image
    bottom_layer = full_matrix[0].astype(np.uint8)
    preview_arr = np.zeros((voxel_h, voxel_w, 3), dtype=np.uint8)
    for mat_id, rgba in preview_colors.items():
        preview_arr[bottom_layer == mat_id] = rgba[:3]
    
    Stats.increment("calibrations")
    
    print(f"[SMART] ✅ Smart 1296 board generated: {output_path}")
    
    return (
        output_path,
        Image.fromarray(preview_arr),
        f"✅ Smart 1296 (38x38 边框版) 生成完毕 | 尺寸：{board_w:.1f}mm | 颜色：{', '.join(slot_names)}"
    )


def generate_8color_board(page_index=0):
    # 1. Load Data
    try:
        path = get_asset_path('smart_8color_stacks.npy')
        all_stacks = np.load(path)
        print(f"[8COLOR] Loaded {len(all_stacks)} stacks from {path}")
        
        # 约定转换：smart_8color_stacks.npy 存储底到顶约定 (stack[0]=背面，stack[4]=观赏面)
        # 转换为顶到底约定 (stack[0]=观赏面，stack[4]=背面)，与 4 色模式统一
        all_stacks = np.array([s[::-1] for s in all_stacks])
        
        # Debug: Check surface black count (转换后 stack[0] 为观赏面)
        surface_black = sum(1 for s in all_stacks if s[0] == 5)
        print(f"[8COLOR] Surface black: {surface_black}/{len(all_stacks)} ({surface_black/len(all_stacks)*100:.2f}%)")
    except Exception as e: 
        print(f"[8COLOR] Error loading data: {e}")
        return None, None, "[ERROR] Data not found. Run analyze_colors.py first."

    # 2. Slice Data (1369 per page for 37x37)
    per_page = 1369
    start = page_index * per_page
    stacks = all_stacks[start : start + per_page]

    # 3. Layout: 37x37 Data + 1 Padding = 39x39 Physical
    data_dim, padding = 37, 1
    total_dim = 39
    
    # Calculate Voxels
    px_blk = max(1, int(5.0 / PrinterConfig.NOZZLE_WIDTH))
    px_gap = max(1, int(0.8 / PrinterConfig.NOZZLE_WIDTH))
    v_w = total_dim * (px_blk + px_gap)
    
    full_matrix = np.full((5 + int(PrinterConfig.BACKING_MM/0.08), v_w, v_w), 0, dtype=int)

    # 4. Fill Data
    for i, stack in enumerate(stacks):
        r, c = (i // data_dim) + padding, (i % data_dim) + padding
        py, px = r * (px_blk + px_gap), c * (px_blk + px_gap)
        
        # Debug first few stacks
        if i < 3:
            print(f"[8COLOR] Stack {i} (顶到底): {stack}")
        
        # 直接写入，与 4 色模式一致（已在加载时完成约定转换）
        # stack[0] = 观赏面 -> Z=0 (物理第 1 层，观赏面)
        # stack[4] = 背面   -> Z=4 (物理第 5 层)
        for z, mid in enumerate(stack):
            full_matrix[z, py:py+px_blk, px:px+px_blk] = mid

    # 5. Set Corner Markers (Crucial for Page ID)
    # Page 1 TR = Cyan(1), Page 2 TR = Magenta(2)
    page_mark = 1 if page_index == 0 else 2
    
    # 8 色材料 ID: 0=White, 1=Cyan, 2=Magenta, 3=Yellow, 4=Black, 5=Red, 6=DeepBlue, 7=Green
    corners = [
        (0, 0, 0),              # TL: White (ID=0)
        (0, total_dim-1, page_mark),   # TR: Page ID (Cyan=1 or Magenta=2)
        (total_dim-1, total_dim-1, 5), # BR: Red (ID=5) - TODO: Should be Black(4)?
        (total_dim-1, 0, 4)     # BL: Black (ID=4) - TODO: Should be Yellow(3)?
    ]
    for r, c, mid in corners:
        py, px = r * (px_blk + px_gap), c * (px_blk + px_gap)
        for z in range(5): full_matrix[z, py:py+px_blk, px:px+px_blk] = mid

    # 6. Export 3MF & Preview
    scene = trimesh.Scene()
    conf = ColorSystem.EIGHT_COLOR
    for mid in range(8):
        m = _generate_voxel_mesh(full_matrix, mid, v_w, v_w)
        if m:
            m.visual.face_colors = conf['preview'][mid]
            m.metadata['name'] = conf['slots'][mid]
            scene.add_geometry(m, geom_name=conf['slots'][mid])
            
    out_name = generate_calibration_filename("8-Color", f"Page{page_index+1}")
    out_path = os.path.join(OUTPUT_DIR, out_name)
    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=out_path,
        slot_names=conf['slots'],
        preview_colors=conf['preview'],
        settings={
            'layer_height': '0.08',
            'initial_layer_height': '0.08',
            'wall_loops': '1',
            'top_shell_layers': '0',
            'bottom_shell_layers': '0',
            'sparse_infill_density': '100%',
            'sparse_infill_pattern': 'zig-zag',
        },
        color_mode="8-Color"
    )
    
    # Simple preview generation
    prev = np.zeros((v_w, v_w, 3), dtype=np.uint8)
    for mid, col in conf['preview'].items(): prev[full_matrix[0]==mid] = col[:3]
    
    # Debug: Check what's on the first layer
    unique, counts = np.unique(full_matrix[0], return_counts=True)
    material_stats = dict(zip(unique, counts))
    print(f"[8COLOR] First layer (Z=0) materials: {material_stats}")
    
    # Calculate actual color blocks (not pixels)
    total_pixels = v_w * v_w
    block_pixels = px_blk * px_blk
    print(f"[8COLOR] Pixel stats:")
    print(f"  Total pixels: {total_pixels}")
    print(f"  Pixels per block: {block_pixels}")
    for mid, pixel_count in material_stats.items():
        block_count = pixel_count / block_pixels
        percentage = pixel_count / total_pixels * 100
        mat_name = conf['slots'][mid] if mid < len(conf['slots']) else f"Material{mid}"
        print(f"  {mat_name} (ID={mid}): {pixel_count} pixels = ~{block_count:.1f} blocks ({percentage:.1f}%)")
    
    return out_path, Image.fromarray(prev), "OK"

def generate_8color_batch_zip():
    """Generates both pages and zips them."""
    f1, _, _ = generate_8color_board(0)
    f2, _, _ = generate_8color_board(1)
    
    if not f1 or not f2: return None, None, "[ERROR] Generation failed"
    
    zip_path = os.path.join(OUTPUT_DIR, generate_calibration_filename("8-Color", "Kit", ".zip"))
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.write(f1, os.path.basename(f1))
        zf.write(f2, os.path.basename(f2))
        
    _, prev, _ = generate_8color_board(0) # Show Page 1 as preview
    return zip_path, prev, "[OK] 8-Color Kit (Page 1 & 2) Generated!"


def generate_bw_calibration_board(block_size_mm=5.0, gap_mm=0.8, backing_color="White"):
    """
    Generate Black & White (2-Color) calibration board with 8x8 border layout.
    
    Features:
    - 8x8 physical grid (6x6 data + 2 border protection)
    - 32 exhaustive color combinations (2^5 = 32)
    - Corner alignment markers in outermost ring
    - Face Down printing (same as 4-color mode)
    
    Args:
        block_size_mm: Size of each color block in mm
        gap_mm: Gap between blocks in mm
        backing_color: Backing layer color ("White" or "Black")
    
    Returns:
        Tuple of (output_path, preview_image, status_message)
    """
    print("[BW] Generating Black & White calibration board (8x8 Layout)...")
    
    # Get color configuration
    color_conf = ColorSystem.BW
    preview_colors = color_conf['preview']
    slot_names = color_conf['slots']
    color_map = color_conf['map']
    
    backing_id = color_map.get(backing_color, 0)
    
    # Geometry parameters (8x8 layout with border)
    data_dim = 6  # 6x6 = 36 blocks (we only use 32)
    padding = 1   # 1 block border on each side
    total_dim = data_dim + 2 * padding  # 8x8 total
    block_w = float(block_size_mm)
    gap = float(gap_mm)
    margin = 5.0
    
    # Calculate board dimensions
    board_w = margin * 2 + total_dim * block_w + (total_dim - 1) * gap
    board_h = board_w
    
    print(f"[BW] Board size: {board_w:.1f} x {board_h:.1f} mm (Grid: {total_dim}x{total_dim})")
    
    # Calculate voxel grid dimensions
    pixels_per_block = max(1, int(block_w / PrinterConfig.NOZZLE_WIDTH))
    pixels_gap = max(1, int(gap / PrinterConfig.NOZZLE_WIDTH))
    
    voxel_w = total_dim * (pixels_per_block + pixels_gap)
    voxel_h = total_dim * (pixels_per_block + pixels_gap)
    
    # Layer configuration
    color_layers = 5
    backing_layers = int(PrinterConfig.BACKING_MM / PrinterConfig.LAYER_HEIGHT)
    total_layers = color_layers + backing_layers
    
    # Initialize voxel matrix (filled with White Slot 0)
    full_matrix = np.full((total_layers, voxel_h, voxel_w), 0, dtype=int)
    
    print(f"[BW] Voxel matrix: {total_layers} x {voxel_h} x {voxel_w}")
    
    # Generate all 32 combinations (2^5 = 32)
    print("[BW] Generating 32 combinations (2^5)...")
    stacks = []
    for i in range(32):
        digits = []
        temp = i
        for _ in range(5):
            digits.append(temp % 2)
            temp //= 2
        stack = digits[::-1]  # [顶...底] format
        stacks.append(stack)
    
    # Fill 32 blocks in 6x6 data area (with padding offset)
    for idx in range(32):
        # Data area logical coordinates (0..5)
        r_data = idx // data_dim
        c_data = idx % data_dim
        
        # Physical area coordinates (with border offset -> 1..6)
        row = r_data + padding
        col = c_data + padding
        
        stack = stacks[idx]
        
        px = col * (pixels_per_block + pixels_gap)
        py = row * (pixels_per_block + pixels_gap)
        
        # Fill 5 color layers (Z=0 is viewing surface)
        # stack format is [顶...底], so stack[0] -> Z=0
        for z in range(color_layers):
            mat_id = stack[z]
            full_matrix[z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
    
    # Set corner alignment markers (in outermost ring 0 and 7)
    # TL: White (0), TR: Black (1), BR: Black (1), BL: Black (1)
    corners = [
        (0, 0, 0),                      # TL = White
        (0, total_dim-1, 1),            # TR = Black
        (total_dim-1, total_dim-1, 1),  # BR = Black
        (total_dim-1, 0, 1)             # BL = Black
    ]
    
    for r, c, mat_id in corners:
        px = c * (pixels_per_block + pixels_gap)
        py = r * (pixels_per_block + pixels_gap)
        for z in range(color_layers):
            full_matrix[z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
    
    # Generate 3MF scene
    scene = trimesh.Scene()
    
    for mat_id in range(2):
        mesh = _generate_voxel_mesh(full_matrix, mat_id, voxel_h, voxel_w)
        if mesh:
            mesh.visual.face_colors = preview_colors[mat_id]
            name = slot_names[mat_id]
            mesh.metadata['name'] = name
            scene.add_geometry(mesh, node_name=name, geom_name=name)
    
    # Export
    output_path = os.path.join(OUTPUT_DIR, generate_calibration_filename("BW", "Standard"))
    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=output_path,
        slot_names=slot_names,
        preview_colors=preview_colors,
        settings={
            'layer_height': '0.08',
            'initial_layer_height': '0.08',
            'wall_loops': '1',
            'top_shell_layers': '0',
            'bottom_shell_layers': '0',
            'sparse_infill_density': '100%',
            'sparse_infill_pattern': 'zig-zag',
        },
        color_mode="BW"
    )
    
    # Generate preview image
    bottom_layer = full_matrix[0].astype(np.uint8)
    preview_arr = np.zeros((voxel_h, voxel_w, 3), dtype=np.uint8)
    for mat_id, rgba in preview_colors.items():
        preview_arr[bottom_layer == mat_id] = rgba[:3]
    
    Stats.increment("calibrations")
    
    print(f"[BW] ✅ Black & White calibration board generated: {output_path}")
    
    return (
        output_path,
        Image.fromarray(preview_arr),
        f"✅ BW (8x8 边框版) 生成完毕 | 尺寸：{board_w:.1f}mm | 颜色：{', '.join(slot_names)}"
    )




def select_extended_1444_colors(base_1024_stacks):
    """
    Intelligent color selection algorithm for 5-Color Extended (6-layer) system.

    Selects 1444 most representative 6-layer color combinations from 3073 possible
    combinations (3×1024 + 1 for KWWWWW) to extend the base 1024 5-layer colors.

    The 6-layer structure:
    - First 5 layers: identical to 4-color mode (RYBW combinations, 1024 total)
    - 6th layer (outermost/viewing surface): R, Y, B (3 choices), or K (only in KWWWWW)
    - Total theoretical: 3×1024 + 1 = 3073
    - Actual selection: 1443 (greedy) + 1 (KWWWWW) = 1444 colors

    Args:
        base_1024_stacks: List of 1024 base 5-layer color stacks (from 4-color mode)

    Returns:
        List of 1444 tuples, each representing a 6-layer color stack
    """
    print("[5C_EXT] Selecting 1444 extended colors from 3073 candidates...")

    LAYER_HEIGHT = PrinterConfig.LAYER_HEIGHT
    BACKING = np.array([255, 255, 255])

    FILAMENTS = {
        0: {"name": "White",   "rgb": [255, 255, 255], "td": 5.0},
        1: {"name": "Red",     "rgb": [220, 20, 60],   "td": 4.0},
        2: {"name": "Yellow",  "rgb": [255, 230, 0],   "td": 6.0},
        3: {"name": "Blue",    "rgb": [0, 100, 240],   "td": 2.0},
        4: {"name": "Black",   "rgb": [20, 20, 20],    "td": 0.6},
    }

    alphas = {}
    for fid, props in FILAMENTS.items():
        bd = props['td'] / 10.0
        alphas[fid] = min(1.0, LAYER_HEIGHT / bd) if bd > 0 else 1.0

    def simulate_color(stack):
        """Simulate final color from a stack (Bottom-to-Top alpha blending)"""
        curr = BACKING.astype(float)
        for fid in reversed(stack):  # Iterate from Bottom to Top for correct reflection simulation
            rgb = np.array(FILAMENTS[fid]['rgb'])
            a = alphas[fid]
            curr = rgb * a + curr * (1.0 - a)
        return curr.astype(np.uint8)

    candidates = []

    for base_stack in base_1024_stacks:
        for layer6 in [1, 2, 3]:  # R, Y, B (viewing surface, outermost layer)
            # stack format: [top...bottom] where top is viewing surface
            # layer6 should be at index 0 (viewing surface), base_stack follows
            stack = (layer6,) + tuple(base_stack)
            final_rgb = simulate_color(stack)
            candidates.append({
                "stack": stack,
                "rgb": final_rgb
            })

    kwwwww_stack = (4, 0, 0, 0, 0, 0)  # KWWWWW (K on outermost/viewing surface)
    kwwwww_rgb = simulate_color(kwwwww_stack)
    candidates.append({
        "stack": kwwwww_stack,
        "rgb": kwwwww_rgb,
        "is_special": True
    })

    print(f"[5C_EXT] Total candidates: {len(candidates)} (3072 + 1 KWWWWW)")

    selected = []

    selected.append({
        "stack": kwwwww_stack,
        "rgb": kwwwww_rgb
    })
    print(f"[5C_EXT] Pre-selected KWWWWW (special case)")

    target = 1444

    print(f"[5C_EXT] Round 1: Greedy selection (RGB distance > 8)...")
    selected_rgbs = np.array([s['rgb'] for s in selected], dtype=int)
    
    for c in candidates:
        if len(selected) >= target:
            break
        
        # Check if already selected (by stack)
        if any(c['stack'] == s['stack'] for s in selected):
            continue

        is_distinct = True
        if len(selected_rgbs) > 0:
            c_rgb = c['rgb'].astype(int)
            # Vectorized distance check
            dists = np.linalg.norm(selected_rgbs - c_rgb, axis=1)
            if np.any(dists < 8):
                is_distinct = False

        if is_distinct:
            selected.append(c)
            selected_rgbs = np.vstack([selected_rgbs, c['rgb'].astype(int)])

    print(f"[5C_EXT] Round 1 selected: {len(selected)}")

    if len(selected) < target:
        print(f"[5C_EXT] Filling remaining {target - len(selected)} spots...")
        for c in candidates:
            if len(selected) >= target:
                break
            if any(c['stack'] == s['stack'] for s in selected):
                continue
            selected.append(c)

    print(f"[5C_EXT] Final selection: {len(selected)} colors")

    return [s['stack'] for s in selected[:target]]


def get_top_1444_colors():
    """
    Intelligent color selection algorithm for 5-Color (RYBW+) system.

    Returns 1444 most representative color combinations from 4096 possible
    combinations (4^5 + 4^5*3) to fill a 38x38 grid.

    This function is public and can be called to reconstruct the stacking order.

    Returns:
        List of 1444 tuples, each representing a 5 or 6-layer color stack
    """
    print("[5C1444] Simulating 4096 combinations (4^5 + 4^5*3)...")

    LAYER_HEIGHT = PrinterConfig.LAYER_HEIGHT
    BACKING = np.array([255, 255, 255])

    FILAMENTS = {
        0: {"name": "White",   "rgb": [255, 255, 255], "td": 5.0},
        1: {"name": "Red",     "rgb": [220, 20, 60],   "td": 4.0},
        2: {"name": "Yellow",  "rgb": [255, 230, 0],   "td": 6.0},
        3: {"name": "Blue",    "rgb": [0, 100, 240],   "td": 2.0},
    }

    alphas = {}
    for fid, props in FILAMENTS.items():
        bd = props['td'] / 10.0
        alphas[fid] = min(1.0, LAYER_HEIGHT / bd) if bd > 0 else 1.0

    candidates_5layer = []
    candidates_6layer = []

    for stack in itertools.product(range(4), repeat=5):
        curr = BACKING.astype(float)
        for fid in stack:
            rgb = np.array(FILAMENTS[fid]['rgb'])
            a = alphas[fid]
            curr = rgb * a + curr * (1.0 - a)
        final_rgb = curr.astype(np.uint8)
        candidates_5layer.append({
            "stack": stack,
            "layers": 5,
            "rgb": final_rgb
        })

    for stack_5 in itertools.product(range(4), repeat=5):
        for layer6 in range(1, 4):  # R, Y, B (not White)
            stack = stack_5 + (layer6,)
            curr = BACKING.astype(float)
            for fid in stack:
                rgb = np.array(FILAMENTS[fid]['rgb'])
                a = alphas[fid]
                curr = rgb * a + curr * (1.0 - a)
            final_rgb = curr.astype(np.uint8)
            candidates_6layer.append({
                "stack": stack,
                "layers": 6,
                "rgb": final_rgb
            })

    print(f"[5C1444] Total candidates: 5layer={len(candidates_5layer)}, 6layer={len(candidates_6layer)}")

    all_candidates = candidates_5layer + candidates_6layer

    selected = []

    print(f"[5C1444] Pre-selecting seed colors...")
    for i in range(4):
        stack = (i,) * 5
        for c in candidates_5layer:
            if c['stack'] == stack:
                selected.append(c)
                break

    print(f"[5C1444] Seed colors: {len(selected)}")

    target = 1444

    print(f"[5C1444] Round 1: High quality selection (RGB distance > 8)...")
    for c in all_candidates:
        if len(selected) >= target:
            break
        if any(c['stack'] == s['stack'] for s in selected):
            continue

        is_distinct = True
        for s in selected:
            if np.linalg.norm(c['rgb'].astype(int) - s['rgb'].astype(int)) < 8:
                is_distinct = False
                break

        if is_distinct:
            selected.append(c)

    print(f"[5C1444] Round 1 selected: {len(selected)}")

    if len(selected) < target:
        print(f"[5C1444] Filling remaining {target - len(selected)} spots...")
        for c in all_candidates:
            if len(selected) >= target:
                break
            if any(c['stack'] == s['stack'] for s in selected):
                continue
            selected.append(c)

    print(f"[5C1444] Final selection: {len(selected)} colors")

    return [s['stack'] for s in selected[:target]]


def generate_5color1444_board(block_size_mm=5.0, gap_mm=0.8):
    """
    Generate 5-Color (RYBW+ 1444) calibration board with 38x38 border layout.

    Features:
    - 38x38 physical grid (36x36 data + 2 border protection)
    - 1444 intelligently selected color blocks
    - Corner alignment markers in outermost ring
    - Face Down printing optimization

    Args:
        block_size_mm: Size of each color block in mm
        gap_mm: Gap between blocks in mm

    Returns:
        Tuple of (output_path, preview_image, status_message)
    """
    print("[5C1444] Generating 5-Color 1444 calibration board (38x38 Layout)...")

    stacks = get_top_1444_colors()

    data_dim = 36
    padding = 1
    total_dim = data_dim + 2 * padding
    block_w = float(block_size_mm)
    gap = float(gap_mm)
    margin = 5.0

    board_w = margin * 2 + total_dim * block_w + (total_dim - 1) * gap
    board_h = board_w

    print(f"[5C1444] Board size: {board_w:.1f} x {board_h:.1f} mm (Grid: {total_dim}x{total_dim})")

    preview_colors = {
        0: [255, 255, 255, 255],
        1: [220, 20, 60, 255],
        2: [255, 230, 0, 255],
        3: [0, 100, 240, 255],
    }
    slot_names = ["White", "Red", "Yellow", "Blue"]

    pixels_per_block = max(1, int(block_w / PrinterConfig.NOZZLE_WIDTH))
    pixels_gap = max(1, int(gap / PrinterConfig.NOZZLE_WIDTH))

    voxel_w = total_dim * (pixels_per_block + pixels_gap)
    voxel_h = total_dim * (pixels_per_block + pixels_gap)

    color_layers = 6
    backing_layers = int(PrinterConfig.BACKING_MM / PrinterConfig.LAYER_HEIGHT)
    total_layers = color_layers + backing_layers

    full_matrix = np.full((total_layers, voxel_h, voxel_w), 0, dtype=int)

    print(f"[5C1444] Voxel matrix: {total_layers} x {voxel_h} x {voxel_w}")

    for idx, stack in enumerate(stacks):
        r_data = idx // data_dim
        c_data = idx % data_dim

        row = r_data + padding
        col = c_data + padding

        px = col * (pixels_per_block + pixels_gap)
        py = row * (pixels_per_block + pixels_gap)

        stack_len = len(stack)
        for z in range(min(stack_len, color_layers)):
            mat_id = stack[z]
            if mat_id < 4:
                full_matrix[z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id

    # Set corner alignment markers (in outermost ring)
    # TL: White (0), TR: Red (1), BR: Yellow (2), BL: Blue (3)
    # Place markers on viewing surface (topmost layer) for visual identification after printing
    corners = [
        (0, 0, 0),
        (0, total_dim-1, 1),
        (total_dim-1, total_dim-1, 2),
        (total_dim-1, 0, 3)
    ]

    viewing_surface_z = total_layers - 1  # Viewing surface is the last printed layer (top)
    for r, c, mat_id in corners:
        px = c * (pixels_per_block + pixels_gap)
        py = r * (pixels_per_block + pixels_gap)
        full_matrix[viewing_surface_z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id

    scene = trimesh.Scene()

    for mat_id, rgba in preview_colors.items():
        mesh = _generate_voxel_mesh(full_matrix, mat_id, voxel_h, voxel_w)
        if mesh:
            mesh.visual.face_colors = rgba
            name = slot_names[mat_id]
            mesh.metadata['name'] = name
            scene.add_geometry(mesh, node_name=name, geom_name=name)

    output_path = os.path.join(OUTPUT_DIR, generate_calibration_filename("5-Color", "Standard"))
    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=output_path,
        slot_names=slot_names,
        preview_colors=preview_colors,
        settings={
            'layer_height': '0.08',
            'initial_layer_height': '0.08',
            'wall_loops': '1',
            'top_shell_layers': '0',
            'bottom_shell_layers': '0',
            'sparse_infill_density': '100%',
            'sparse_infill_pattern': 'zig-zag',
        },
        color_mode="RYBW"
    )

    bottom_layer = full_matrix[0].astype(np.uint8)
    preview_arr = np.zeros((voxel_h, voxel_w, 3), dtype=np.uint8)
    for mat_id, rgba in preview_colors.items():
        preview_arr[bottom_layer == mat_id] = rgba[:3]

    Stats.increment("calibrations")

    print(f"[5C1444] ✅ Calibration board generated: {output_path}")

    return (
        output_path,
        Image.fromarray(preview_arr),
        f"✅ 5-Color (1444) 生成完毕 | 尺寸：{board_w:.1f}mm | 颜色：{', '.join(slot_names)}"
    )


def merge_5color_extended(base_lut_path, extended_lut_path, output_path=None):
    """
    Merge 4-Color base LUT (1024) and 5-Color Extended LUT (1444) into a single 2468-color LUT.
    
    Args:
        base_lut_path: Path to base 1024-color LUT (.npy file)
        extended_lut_path: Path to extended 1444-color LUT (.npy file)
        output_path: Optional output path for merged LUT (.npz file)
    
    Returns:
        Tuple of (rgb_array, stacks_array, output_path)
    """
    print("[5C_EXT] Merging 5-Color Extended LUT...")
    
    # Load base LUT (1024 colors, 5-layer)
    print(f"  Loading base LUT: {base_lut_path}")
    base_rgb = np.load(base_lut_path).reshape(-1, 3)
    print(f"    Base RGB: {len(base_rgb)} colors")
    
    # Load extended LUT (1444 colors, 6-layer)
    print(f"  Loading extended LUT: {extended_lut_path}")
    extended_rgb = np.load(extended_lut_path).reshape(-1, 3)
    print(f"    Extended RGB: {len(extended_rgb)} colors")
    
    # Merge RGB arrays
    merged_rgb = np.vstack([base_rgb, extended_rgb])
    print(f"  Merged RGB: {len(merged_rgb)} colors")
    
    # Generate stacks
    # Base 1024: 5-layer stacks, pad with air(-1) at top for 6-layer uniformity.
    # Air at position 0 keeps base/extended viewing surfaces on separate Z levels.
    base_stacks = []
    for i in range(len(base_rgb)):
        digits = []
        temp = i
        for _ in range(5):
            digits.append(temp % 4)
            temp //= 4
        stack = (-1,) + tuple(reversed(digits))
        base_stacks.append(stack)
    
    # Extended 1444: 6-layer stacks
    base_5layer = [tuple(reversed([i//4**j%4 for j in range(5)])) for i in range(1024)]
    extended_stacks = select_extended_1444_colors(base_5layer)
    
    # Merge stacks
    merged_stacks = base_stacks + extended_stacks
    print(f"  Merged stacks: {len(merged_stacks)} stacks")
    
    # Convert to numpy arrays
    rgb_array = np.array(merged_rgb, dtype=np.uint8)
    stacks_array = np.array(merged_stacks, dtype=np.int32)
    
    # Save to .npz file
    if output_path is None:
        output_path = "output/merged_5color_extended_2468.npz"
    
    np.savez(output_path, rgb=rgb_array, stacks=stacks_array)
    print(f"  Saved merged LUT: {output_path}")
    
    return rgb_array, stacks_array, output_path


def generate_5color_extended_board(block_size_mm=5.0, gap_mm=0.8, page_index=0):
    """
    Generate 5-Color Extended calibration board with dual-page support.
    
    Features:
    - Page 0: Base 1024 colors (5-layer, 32x32 grid)
    - Page 1: Extended 1444 colors (6-layer, 38x38 grid)
    - Corner alignment markers with page ID
    - Face Down printing for both pages (viewing surface at Z=0)
    
    Args:
        block_size_mm: Size of each color block in mm
        gap_mm: Gap between blocks in mm
        page_index: 0 for base 1024, 1 for extended 1444
    
    Returns:
        Tuple of (output_path, preview_image, status_message)
    """
    print(f"[5C_EXT] Generating 5-Color Extended calibration board - Page {page_index + 1}...")

    # Color configuration (5 slots: W, R, Y, B, K)
    preview_colors = {
        0: [255, 255, 255, 255],  # White
        1: [220, 20, 60, 255],    # Red
        2: [255, 230, 0, 255],    # Yellow
        3: [0, 100, 240, 255],    # Blue
        4: [20, 20, 20, 255],     # Black
    }
    slot_names = ["White", "Red", "Yellow", "Blue", "Black"]

    if page_index == 0:
        # Page 1: Base 1024 colors (5-layer, similar to 4-color mode)
        return _generate_5color_base_page(block_size_mm, gap_mm, preview_colors, slot_names)
    else:
        # Page 2: Extended 1444 colors (6-layer)
        return _generate_5color_extended_page(block_size_mm, gap_mm, preview_colors, slot_names)


def _generate_5color_base_page(block_size_mm, gap_mm, preview_colors, slot_names):
    """Generate Page 1: Base 1024 colors (5-layer RYBW combinations)."""
    print("[5C_EXT] Generating Base Page (1024 colors, 5-layer)...")
    
    # 32x32 grid for 1024 colors
    data_dim = 32
    padding = 1
    total_dim = data_dim + 2 * padding  # 34x34 physical
    block_w = float(block_size_mm)
    gap = float(gap_mm)
    margin = 5.0
    
    board_w = margin * 2 + total_dim * block_w + (total_dim - 1) * gap
    
    pixels_per_block = max(1, int(block_w / PrinterConfig.NOZZLE_WIDTH))
    pixels_gap = max(1, int(gap / PrinterConfig.NOZZLE_WIDTH))
    
    voxel_w = total_dim * (pixels_per_block + pixels_gap)
    voxel_h = total_dim * (pixels_per_block + pixels_gap)
    
    # 5 color layers + white backing (Face-Down mode, same as 4-color mode)
    color_layers = 5
    backing_layers = int(PrinterConfig.BACKING_MM / PrinterConfig.LAYER_HEIGHT)
    total_layers = color_layers + backing_layers
    
    full_matrix = np.full((total_layers, voxel_h, voxel_w), 0, dtype=int)  # 0 = White backing
    
    # Generate 1024 base stacks (4^5 combinations of RYBW)
    # Face-Down mode: Z=0 is viewing surface (top), Z=4 is bottom
    for i in range(1024):
        digits = []
        temp = i
        for _ in range(5):
            digits.append(temp % 4)
            temp //= 4
        stack = digits[::-1]  # [top...bottom] for Face-Down mode (Z=0 is viewing surface)
        
        row = (i // data_dim) + padding
        col = (i % data_dim) + padding
        
        px = col * (pixels_per_block + pixels_gap)
        py = row * (pixels_per_block + pixels_gap)
        
        # Fill 5 color layers (Face-Down mode: Z=0 is viewing surface)
        for z in range(color_layers):
            mat_id = stack[z]
            if mat_id < 4:
                full_matrix[z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
    
    # Corner markers for Page 1: TL=White, TR=Red(Page1 ID), BR=Blue, BL=Yellow
    corners = [
        (0, 0, 0),                      # TL = White
        (0, total_dim-1, 1),            # TR = Red (Page 1 ID)
        (total_dim-1, total_dim-1, 3),  # BR = Blue
        (total_dim-1, 0, 2)             # BL = Yellow
    ]
    
    for r, c, mat_id in corners:
        px = c * (pixels_per_block + pixels_gap)
        py = r * (pixels_per_block + pixels_gap)
        for z in range(color_layers):
            full_matrix[z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
    
    # Generate 3MF
    scene = trimesh.Scene()
    for mat_id, rgba in preview_colors.items():
        if mat_id < 4:  # Only 4 colors for base page
            mesh = _generate_voxel_mesh(full_matrix, mat_id, voxel_h, voxel_w)
            if mesh:
                mesh.visual.face_colors = rgba
                name = slot_names[mat_id]
                mesh.metadata['name'] = name
                scene.add_geometry(mesh, node_name=name, geom_name=name)
    
    output_path = os.path.join(OUTPUT_DIR, generate_calibration_filename("5-Color Extended", "Page1"))
    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=output_path,
        slot_names=slot_names[:4],
        preview_colors=preview_colors,
        settings={
            'layer_height': '0.08',
            'initial_layer_height': '0.08',
            'wall_loops': '1',
            'top_shell_layers': '0',
            'bottom_shell_layers': '0',
            'sparse_infill_density': '100%',
            'sparse_infill_pattern': 'zig-zag',
        },
        color_mode="5-Color Extended"
    )
    
    # Preview
    bottom_layer = full_matrix[0].astype(np.uint8)
    preview_arr = np.zeros((voxel_h, voxel_w, 3), dtype=np.uint8)
    for mat_id, rgba in preview_colors.items():
        if mat_id < 4:
            preview_arr[bottom_layer == mat_id] = rgba[:3]
    
    Stats.increment("calibrations")
    
    return (
        output_path,
        Image.fromarray(preview_arr),
        f"✅ 5-Color Extended Page 1 (1024 colors) 生成完毕 | 尺寸：{board_w:.1f}mm"
    )


def _generate_5color_extended_page(block_size_mm, gap_mm, preview_colors, slot_names):
    """Generate Page 2: Extended 1444 colors (6-layer with Black).
    
    Features:
    - 1444 extended colors (6-layer stacks)
    - 38x38 grid with padding
    - Face Down printing (viewing surface at Z=0, first printed layer)
    - Corner markers: TL=Blue, TR=Red(Page2 ID), BR=Black, BL=Yellow
    """
    print("[5C_EXT] Generating Extended Page (1444 colors, 6-layer)...")
    
    # Get base 1024 stacks for extended color selection
    base_stacks = []
    for i in range(1024):
        digits = []
        temp = i
        for _ in range(5):
            digits.append(temp % 4)
            temp //= 4
        stack = tuple(reversed(digits))
        base_stacks.append(stack)
    
    # Get extended 1444 stacks (6-layer)
    extended_stacks = select_extended_1444_colors(base_stacks)
    
    # 38x38 grid for 1444 colors
    data_dim = 38
    padding = 1
    total_dim = data_dim + 2 * padding  # 40x40 physical
    block_w = float(block_size_mm)
    gap = float(gap_mm)
    margin = 5.0
    
    board_w = margin * 2 + total_dim * block_w + (total_dim - 1) * gap
    
    pixels_per_block = max(1, int(block_w / PrinterConfig.NOZZLE_WIDTH))
    pixels_gap = max(1, int(gap / PrinterConfig.NOZZLE_WIDTH))
    
    voxel_w = total_dim * (pixels_per_block + pixels_gap)
    voxel_h = total_dim * (pixels_per_block + pixels_gap)
    
    # 6 color layers + white backing (Face-Down mode, viewing surface at Z=0)
    color_layers = 6
    backing_layers = int(PrinterConfig.BACKING_MM / PrinterConfig.LAYER_HEIGHT)
    total_layers = color_layers + backing_layers
    
    full_matrix = np.full((total_layers, voxel_h, voxel_w), 0, dtype=int)  # 0 = White backing
    
    # Fill 1444 extended colors (6-layer)
    for idx in range(1444):
        stack = extended_stacks[idx]
        r_data = idx // data_dim
        c_data = idx % data_dim
        
        row = r_data + padding
        col = c_data + padding
        
        px = col * (pixels_per_block + pixels_gap)
        py = row * (pixels_per_block + pixels_gap)
        
        # Map stack to physical layers (Face-Down mode: Z=0 is viewing surface)
        for z in range(color_layers):
            mat_id = stack[z]  # Direct mapping: stack[0] at Z=0 (viewing surface)
            if mat_id < 5:
                full_matrix[z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
    
    corners = [
        (0, 0, 3),                      # TL = Blue
        (0, total_dim-1, 1),            # TR = Red (Page 2 ID)
        (total_dim-1, total_dim-1, 4),  # BR = Black
        (total_dim-1, 0, 2)             # BL = Yellow
    ]
    
    viewing_surface_z = 0  # Face-Down mode: viewing surface is the first printed layer (Z=0)
    for r, c, mat_id in corners:
        px = c * (pixels_per_block + pixels_gap)
        py = r * (pixels_per_block + pixels_gap)
        full_matrix[viewing_surface_z, py:py+pixels_per_block, px:px+pixels_per_block] = mat_id
    
    # Generate 3MF
    scene = trimesh.Scene()
    for mat_id, rgba in preview_colors.items():
        mesh = _generate_voxel_mesh(full_matrix, mat_id, voxel_h, voxel_w)
        if mesh:
            mesh.visual.face_colors = rgba
            name = slot_names[mat_id]
            mesh.metadata['name'] = name
            scene.add_geometry(mesh, node_name=name, geom_name=name)
    
    output_path = os.path.join(OUTPUT_DIR, generate_calibration_filename("5-Color Extended", "Page2"))
    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=output_path,
        slot_names=slot_names,
        preview_colors=preview_colors,
        settings={
            'layer_height': '0.08',
            'initial_layer_height': '0.08',
            'wall_loops': '1',
            'top_shell_layers': '0',
            'bottom_shell_layers': '0',
            'sparse_infill_density': '100%',
            'sparse_infill_pattern': 'zig-zag',
        },
        color_mode="5-Color Extended"
    )
    
    # Preview
    bottom_layer = full_matrix[0].astype(np.uint8)
    preview_arr = np.zeros((voxel_h, voxel_w, 3), dtype=np.uint8)
    for mat_id, rgba in preview_colors.items():
        preview_arr[bottom_layer == mat_id] = rgba[:3]
    
    Stats.increment("calibrations")
    
    return (
        output_path,
        Image.fromarray(preview_arr),
        f"✅ 5-Color Extended Page 2 (1444 colors) 生成完毕 | 尺寸：{board_w:.1f}mm"
    )


def generate_5color_extended_batch_zip(block_size_mm=5.0, gap_mm=0.8):
    """Generates both pages and zips them."""
    f1, _, _ = generate_5color_extended_board(block_size_mm, gap_mm, page_index=0)
    f2, _, _ = generate_5color_extended_board(block_size_mm, gap_mm, page_index=1)
    
    if not f1 or not f2:
        return None, None, "❌ Generation failed"
    
    zip_path = os.path.join(OUTPUT_DIR, generate_calibration_filename("5-Color Extended", "Kit", ".zip"))
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.write(f1, os.path.basename(f1))
        zf.write(f2, os.path.basename(f2))
    
    _, prev, _ = generate_5color_extended_board(block_size_mm, gap_mm, page_index=0)  # Show Page 1 as preview
    return zip_path, prev, "✅ 5-Color Extended Kit (Page 1 & 2) Generated!"
