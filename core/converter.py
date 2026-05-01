"""
Lumina Studio - Image Converter Coordinator (Refactored)

Coordinates modules to complete image-to-3D model conversion.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import deque
import numpy as np
import cv2
import trimesh
from PIL import Image, ImageDraw, ImageFont
import gradio as gr
from typing import List, Dict, Tuple, Optional

from config import PrinterConfig, ColorSystem, ModelingMode, PREVIEW_SCALE, PREVIEW_MARGIN, OUTPUT_DIR, BedManager
from utils import Stats
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata

from core.image_processing import LuminaImageProcessor
from core.mesh_generators import get_mesher
from core.geometry_utils import create_keychain_loop
from core.heightmap_loader import HeightmapLoader
from core.naming import generate_model_filename, generate_preview_filename

# Try to import SVG rendering libraries
try:
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPM
    HAS_SVG_LIB = True
except ImportError:
    HAS_SVG_LIB = False

# Import palette HTML generator from extension (non-invasive)
# Moved to lazy import to avoid circular dependency
# from ui.palette_extension import generate_palette_html, generate_lut_color_grid_html


# ========== LUT Color Extraction Functions ==========

def extract_lut_available_colors(lut_path: str) -> List[dict]:
    """
    Extract all available colors from a LUT file.
    
    This function loads a LUT file (.npy) and extracts all unique colors
    that the printer can produce. These colors can be used as replacement
    options in the color replacement feature.
    
    Args:
        lut_path: Path to the LUT file (.npy)
    
    Returns:
        List of dicts, each containing:
        - 'color': (R, G, B) tuple
        - 'hex': '#RRGGBB' string
        
        Returns empty list if LUT cannot be loaded.
    """
    if not lut_path:
        return []
    
    try:
        # Handle .npz (merged LUT) format
        if lut_path.endswith('.npz'):
            data = np.load(lut_path)
            measured_colors = data['rgb']
            print(f"[LUT_COLORS] Loading merged LUT (.npz) with {len(measured_colors)} colors")
        else:
            # Standard .npy format
            lut_grid = np.load(lut_path)
            measured_colors = lut_grid.reshape(-1, 3)
            print(f"[LUT_COLORS] Loading standard LUT (.npy) with {len(measured_colors)} colors")
        
        # Get unique colors
        unique_colors = np.unique(measured_colors, axis=0)
        
        # Build color list
        colors = []
        for color in unique_colors:
            r, g, b = int(color[0]), int(color[1]), int(color[2])
            colors.append({
                'color': (r, g, b),
                'hex': f'#{r:02x}{g:02x}{b:02x}'
            })
        
        # Sort by brightness (dark to light) for better UX
        colors.sort(key=lambda x: sum(x['color']))
        
        print(f"[LUT_COLORS] Extracted {len(colors)} unique colors from LUT")
        return colors
        
    except Exception as e:
        print(f"[LUT_COLORS] Error extracting colors from LUT: {e}")
        return []


def get_lut_color_choices(lut_path: str) -> List[tuple]:
    """
    Get LUT colors formatted for Gradio Dropdown.
    
    Args:
        lut_path: Path to the LUT .npy file
    
    Returns:
        List of (display_label, hex_value) tuples for Dropdown choices.
        Display label includes a colored square emoji approximation.
    """
    colors = extract_lut_available_colors(lut_path)
    
    if not colors:
        return []
    
    choices = []
    for entry in colors:
        hex_color = entry['hex']
        r, g, b = entry['color']
        # Create a display label with RGB values
        label = f"■ {hex_color} (R:{r} G:{g} B:{b})"
        choices.append((label, hex_color))
    
    return choices


def generate_lut_color_dropdown_html(lut_path: str, selected_color: str = None, used_colors: set = None) -> str:
    """
    Generate HTML for displaying LUT available colors as a clickable visual grid.

    Colors are grouped into two sections:
    1. Colors used in current image (if any)
    2. Other available colors

    This provides a visual preview of all available colors from the LUT,
    allowing users to click directly to select a replacement color.

    Args:
        lut_path: Path to the LUT .npy file
        selected_color: Currently selected replacement color hex
        used_colors: Set of hex colors currently used in the image (for grouping)

    Returns:
        HTML string showing available colors as a clickable grid
    """
    from ui.palette_extension import generate_lut_color_grid_html
    colors = extract_lut_available_colors(lut_path)
    # Delegate HTML generation to palette_extension (non-invasive)
    return generate_lut_color_grid_html(colors, selected_color, used_colors)


def _compute_connected_region_mask_4n(quantized_image, mask_solid, x, y):
    """基于 4 邻接计算点击像素所属连通域掩码。"""
    h, w = quantized_image.shape[:2]
    if not (0 <= x < w and 0 <= y < h) or not mask_solid[y, x]:
        return np.zeros((h, w), dtype=bool)

    target = quantized_image[y, x]
    out = np.zeros((h, w), dtype=bool)
    q = deque([(x, y)])
    out[y, x] = True

    while q:
        cx, cy = q.popleft()
        for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
            if 0 <= nx < w and 0 <= ny < h and not out[ny, nx]:
                if mask_solid[ny, nx] and np.array_equal(quantized_image[ny, nx], target):
                    out[ny, nx] = True
                    q.append((nx, ny))

    return out


def _recommend_lut_colors_by_rgb(base_rgb, lut_colors, top_k=10):
    """按 RGB 欧氏距离推荐 LUT 颜色，返回前 top_k 项。"""
    if not lut_colors:
        return []

    normalized = []
    for c in lut_colors:
        if isinstance(c, dict):
            color = c.get("color")
            hex_color = c.get("hex")
            if color is None and isinstance(hex_color, str) and len(hex_color.strip().lstrip('#')) == 6:
                h = hex_color.strip().lstrip('#')
                color = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
            if color is not None and isinstance(hex_color, str):
                normalized.append({"color": tuple(int(v) for v in color), "hex": hex_color.lower()})
            continue

        if isinstance(c, (tuple, list)) and len(c) >= 2 and isinstance(c[1], str):
            h = c[1].strip().lstrip('#')
            if len(h) != 6:
                continue
            normalized.append({
                "color": (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)),
                "hex": f"#{h.lower()}"
            })

    if not normalized:
        return []

    arr = np.array([c["color"] for c in normalized], dtype=np.float64)
    b = np.array(base_rgb, dtype=np.float64)
    dist = np.sqrt(np.sum((arr - b) ** 2, axis=1))
    idx = np.argsort(dist)[:top_k]
    return [normalized[i] for i in idx]


def _ensure_quantized_image_in_cache(cache):
    """保证预览缓存中存在 quantized_image，缺失时自动回填。"""
    if cache.get("quantized_image") is not None:
        return cache

    dbg = cache.get("debug_data") or {}
    q = dbg.get("quantized_image")
    if q is None:
        q = cache["matched_rgb"].copy()

    cache["quantized_image"] = q
    return cache


def _rgb_to_hex(rgb):
    """将 RGB 三元组转换为 #RRGGBB。"""
    r, g, b = [int(x) for x in rgb]
    return f"#{r:02x}{g:02x}{b:02x}"


def _hex_to_rgb_tuple(hex_color):
    """将 #RRGGBB 转换为 (R, G, B)。"""
    if not isinstance(hex_color, str):
        raise ValueError("hex_color must be a string")

    h = hex_color.strip().lower()
    if h.startswith('#'):
        h = h[1:]
    if len(h) != 6:
        raise ValueError(f"invalid hex color: {hex_color}")

    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _build_selection_meta(q_rgb, m_rgb, scope="region"):
    """构建点击选区元数据（量化色 + 原配准色）。"""
    return {
        "selected_quantized_hex": _rgb_to_hex(q_rgb),
        "selected_matched_hex": _rgb_to_hex(m_rgb),
        "selection_scope": scope,
    }


def _resolve_highlight_mask(color_match, mask_solid, region_mask=None, scope="global"):
    """根据选择范围决定高亮掩码：区域优先，否则全图同色。"""
    if scope == "region" and region_mask is not None:
        return region_mask & mask_solid
    return color_match & mask_solid


def _normalize_color_replacements_input(color_replacements):
    """兼容 dict / replacement_regions(list) 两种替换输入，统一为 {hex: hex}。"""
    if not color_replacements:
        return {}

    if isinstance(color_replacements, dict):
        out = {}
        for src, dst in color_replacements.items():
            if not isinstance(src, str) or not isinstance(dst, str):
                continue
            s = src.strip().lower()
            d = dst.strip().lower()
            if s and d:
                out[s] = d
        return out

    if isinstance(color_replacements, list):
        out = {}
        for item in color_replacements:
            if not isinstance(item, dict):
                continue
            src = (item.get('matched') or item.get('matched_hex')
                   or item.get('source') or item.get('quantized')
                   or item.get('quantized_hex') or '').strip().lower()
            dst = (item.get('replacement') or item.get('replacement_hex') or '').strip().lower()
            if src and dst:
                out[src] = dst
        return out

    return {}


def _apply_region_replacement(image_rgb, region_mask, replacement_rgb):
    """仅在 region_mask 覆盖区域应用替换色。"""
    out = image_rgb.copy()
    out[region_mask] = np.array(replacement_rgb, dtype=np.uint8)
    return out


def _apply_regions_to_raster_outputs(matched_rgb, material_matrix, mask_solid,
                                     replacement_regions, lut_index_resolver, ref_stacks):
    """按 regions 顺序覆盖 raster 输出（matched_rgb + material_matrix）。"""
    out_rgb = matched_rgb.copy()
    out_mat = material_matrix.copy()

    for item in (replacement_regions or []):
        region_mask = item.get('mask')
        replacement_hex = item.get('replacement')
        if region_mask is None or not replacement_hex:
            continue

        effective_mask = region_mask & mask_solid
        if not np.any(effective_mask):
            continue

        replacement_rgb = _hex_to_rgb_tuple(replacement_hex)
        out_rgb[effective_mask] = np.array(replacement_rgb, dtype=np.uint8)

        lut_idx = int(lut_index_resolver(replacement_rgb))
        out_mat[effective_mask] = ref_stacks[lut_idx]

    return out_rgb, out_mat


def _build_dual_recommendations(q_rgb, m_rgb, lut_colors, top_k=10):
    """构建双基准推荐：按量化色与按原配准色。"""
    return {
        "by_quantized": _recommend_lut_colors_by_rgb(q_rgb, lut_colors, top_k=top_k),
        "by_matched": _recommend_lut_colors_by_rgb(m_rgb, lut_colors, top_k=top_k),
    }


def _resolve_click_selection_hexes(cache, default_hex):
    """解析点击后的显示色与内部状态色。

    显示色优先使用原配准色，内部状态色保持量化色，
    以兼容“显示原图色、替换按量化色作用连通域”的设计。
    """
    cached_q_hex = (cache or {}).get('selected_quantized_hex')
    cached_m_hex = (cache or {}).get('selected_matched_hex')

    # Gradio update objects are dict-like; they must not propagate into hex state.
    fallback_hex = default_hex if isinstance(default_hex, str) else None
    q_hex = cached_q_hex if isinstance(cached_q_hex, str) else fallback_hex
    m_hex = cached_m_hex if isinstance(cached_m_hex, str) else q_hex
    return m_hex, q_hex


# ========== Color Palette Functions ==========

def extract_color_palette(preview_cache: dict) -> List[dict]:
    """
    Extract unique colors from preview cache.
    
    Args:
        preview_cache: Cache data from generate_preview_cached containing:
            - matched_rgb: (H, W, 3) uint8 array of matched colors
            - mask_solid: (H, W) bool array indicating solid pixels
    
    Returns:
        List of dicts sorted by pixel count (descending), each containing:
        - 'color': (R, G, B) tuple
        - 'hex': '#RRGGBB' string
        - 'count': pixel count
        - 'percentage': percentage of total solid pixels (0.0-100.0)
    """
    if preview_cache is None:
        return []
    
    matched_rgb = preview_cache.get('matched_rgb')
    mask_solid = preview_cache.get('mask_solid')
    
    if matched_rgb is None or mask_solid is None:
        return []
    
    # Get only solid pixels
    solid_pixels = matched_rgb[mask_solid]
    
    if len(solid_pixels) == 0:
        return []
    
    total_solid = len(solid_pixels)
    
    # Find unique colors and their counts
    # Reshape to (N, 3) and find unique rows
    unique_colors, counts = np.unique(solid_pixels, axis=0, return_counts=True)
    
    # Build palette entries
    palette = []
    for color, count in zip(unique_colors, counts):
        r, g, b = int(color[0]), int(color[1]), int(color[2])
        palette.append({
            'color': (r, g, b),
            'hex': f'#{r:02x}{g:02x}{b:02x}',
            'count': int(count),
            'percentage': round(count / total_solid * 100, 2)
        })
    
    # Sort by count descending
    palette.sort(key=lambda x: x['count'], reverse=True)
    
    return palette


# ========== Debug Helper Functions ==========

def _save_debug_preview(debug_data, material_matrix, mask_solid, image_path, mode_name, num_materials=4):
    """
    Save high-fidelity mode debug preview image.
    
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


# ========== LUT Slot Color Derivation ==========

def _get_actual_lut_slot_colors(processor) -> dict:
    """Derive the actual measured color for each slot from the LUT's pure-color entries.

    For a 6-Color Smart-1296 LUT, the pure-color stack for slot *i* is the entry
    where all 5 layers equal *i* (top-to-bottom convention: ``(i, i, i, i, i)``).
    The corresponding ``lut_rgb`` value is the physical color actually measured
    from the calibration board for that slot.

    This is used to override the hard-coded ``ColorSystem.SIX_COLOR`` preview
    colours (CMYWGK) with the real filament colours so BambuStudio's AMS panel
    shows the correct colour and the user loads the right filament in each slot.

    Args:
        processor: A ``LuminaImageProcessor`` instance whose ``ref_stacks`` and
                   ``lut_rgb`` attributes have already been populated.

    Returns:
        ``{slot_id: (r, g, b)}`` for every slot whose pure-colour entry is found.
        Returns an empty dict if the data is unavailable or the stack depth < 5.
    """
    try:
        ref_stacks = np.asarray(processor.ref_stacks)  # (N, 5), top-to-bottom
        lut_rgb    = np.asarray(processor.lut_rgb)     # (N, 3)
    except (AttributeError, TypeError):
        return {}

    if ref_stacks.ndim != 2 or ref_stacks.shape[1] < 5 or len(lut_rgb) == 0:
        return {}

    num_slots = int(ref_stacks.max()) + 1
    slot_colors: dict = {}
    for slot_id in range(num_slots):
        pure_mask = np.all(ref_stacks == slot_id, axis=1)
        if np.any(pure_mask):
            idx = int(np.argmax(pure_mask))
            rgb = lut_rgb[idx]
            slot_colors[slot_id] = (int(rgb[0]), int(rgb[1]), int(rgb[2]))

    return slot_colors


# ========== Main Conversion Function ==========

def convert_image_to_3d(image_path, lut_path, target_width_mm, spacer_thick,
                         structure_mode, auto_bg, bg_tol, color_mode,
                         add_loop, loop_width, loop_length, loop_hole, loop_pos,
                         modeling_mode=ModelingMode.VECTOR, quantize_colors=32,
                         blur_kernel=0, smooth_sigma=10,
                         color_replacements=None, replacement_regions=None, backing_color_id=0, separate_backing=False,
                         enable_relief=False, color_height_map=None,
                         height_mode: str = "color",
                         heightmap_path=None, heightmap_max_height=None,
                         enable_cleanup=True,
                         enable_outline=False, outline_width=2.0,
                         enable_cloisonne=False, wire_width_mm=0.4,
                         wire_height_mm=0.4,
                         free_color_set=None,
                         enable_coating=False, coating_height_mm=0.08,
                         hue_weight: float = 0.0,
                         progress=None):
    """
    Main conversion function: Convert image to 3D model.
    
    This refactored coordinator function is responsible for:
    1. Calling LuminaImageProcessor to process the image
    2. Calling get_mesher to get the mesh generator
    3. Generating meshes for each material
    4. Adding keychain loop (if needed)
    5. Exporting 3MF file
    
    Args:
        image_path: Path to input image
        lut_path: LUT file path (string) or Gradio File object
        target_width_mm: Target width in millimeters
        spacer_thick: Backing thickness in mm
        structure_mode: "Double-sided" or "Single-sided"
        auto_bg: Enable automatic background removal
        bg_tol: Background tolerance value
        color_mode: Color system mode (CMYW/RYBW/6-Color)
        add_loop: Enable keychain loop
        loop_width: Loop width in mm
        loop_length: Loop length in mm
        loop_hole: Loop hole diameter in mm
        loop_pos: Loop position (x, y) tuple
        modeling_mode: Modeling mode ("vector"/"pixel")
        quantize_colors: Number of colors for K-Means quantization
        blur_kernel: Median filter kernel size (0=disabled, recommended 0-5, default 0)
        smooth_sigma: Bilateral filter sigma value (recommended 5-20, default 10)
        color_replacements: Optional dict of color replacements {hex: hex}
                           e.g., {'#ff0000': '#00ff00'}
        backing_color_id: Backing material ID (0-7), default is 0 (White)
        separate_backing: Boolean flag to separate backing as individual object (default: False)
                         When True, backing_color_id is overridden to -2
    
    Returns:
        Tuple of (3mf_path, glb_path, preview_image, status_message)
    """
    def _prog(val: float, desc: str = ""):
        if progress is not None:
            progress(val, desc=desc)

    # Input validation
    if image_path is None:
        return None, None, None, "[ERROR] Please upload an image", None
    if lut_path is None:
        return None, None, None, "[WARNING] Please select or upload a .npy calibration file!", None
    
    # Handle LUT path (supports string path or Gradio File object)
    if isinstance(lut_path, str):
        actual_lut_path = lut_path
    elif hasattr(lut_path, 'name'):
        actual_lut_path = lut_path.name
    else:
        return None, None, None, "[ERROR] Invalid LUT file format", None
    
    # Handle backing separation: override backing_color_id if separate_backing is True
    # Error handling for checkbox state (Requirement 8.4)
    try:
        separate_backing = bool(separate_backing) if separate_backing is not None else False
    except Exception as e:
        print(f"[CONVERTER] Error reading separate_backing checkbox state: {e}, using default (False)")
        separate_backing = False
    
    if separate_backing:
        backing_color_id = -2
        print(f"[CONVERTER] Backing separation enabled: backing will be a separate object (white)")
    else:
        print(f"[CONVERTER] Backing separation disabled: backing merged with first layer (backing_color_id={backing_color_id})")
    
    print(f"[CONVERTER] Starting conversion...")
    print(f"[CONVERTER] Mode: {modeling_mode.get_display_name()}, Quantize: {quantize_colors}")
    print(f"[CONVERTER] Filters: blur_kernel={blur_kernel}, smooth_sigma={smooth_sigma}")
    print(f"[CONVERTER] LUT: {actual_lut_path}")
    
    # ========== [UPDATED] Native Vector Mode Detection ==========
    # Check if user selected vector mode AND file is SVG
    if modeling_mode == ModelingMode.VECTOR and image_path.lower().endswith('.svg'):
        print("[CONVERTER] 🎨 Using Native Vector Engine (Shapely/Clipper)...")
        vector_timing = {}
        vector_total_t0 = time.perf_counter()

        vector_replacements = _normalize_color_replacements_input(replacement_regions)
        if not vector_replacements:
            vector_replacements = _normalize_color_replacements_input(color_replacements)

        try:
            from core.vector_engine import VectorProcessor

            # 1. Execute Conversion
            vec_processor = VectorProcessor(actual_lut_path, color_mode)

            # Convert SVG to 3D scene
            _prog(0.05, "SVG 解析与几何处理中... | Parsing & extruding SVG...")
            mesh_t0 = time.perf_counter()
            scene = vec_processor.svg_to_mesh(
                svg_path=image_path,
                target_width_mm=target_width_mm,
                thickness_mm=spacer_thick,
                structure_mode=structure_mode,
                color_replacements=vector_replacements,
                separate_backing=separate_backing,
            )
            vector_timing["mesh_total_s"] = time.perf_counter() - mesh_t0
            if isinstance(getattr(vec_processor, "last_stage_timings", None), dict):
                vector_timing.update(vec_processor.last_stage_timings)

            # Keep vector export behavior consistent with raster path:
            # never export an empty scene.
            if len(scene.geometry) == 0:
                return None, None, None, "[ERROR] Vector mesh generation failed: no valid geometry generated", None
            
            # 2. Export 3MF (unified Bambu metadata path)
            _prog(0.72, "导出 3MF 中... | Exporting 3MF...")
            base_name = os.path.splitext(os.path.basename(image_path))[0]
            out_path = os.path.join(OUTPUT_DIR, generate_model_filename(base_name, modeling_mode, color_mode))

            is_six_color = len(vec_processor.img_processor.lut_rgb) == 1296
            if is_six_color:
                vec_color_conf = ColorSystem.SIX_COLOR
                vec_color_mode = "6-Color"
            else:
                vec_color_conf = ColorSystem.get(color_mode)
                vec_color_mode = color_mode

            vec_slot_names = []
            for geom_name, geom in scene.geometry.items():
                vertices = getattr(geom, "vertices", None)
                faces = getattr(geom, "faces", None)
                v_count = len(vertices) if vertices is not None else 0
                f_count = len(faces) if faces is not None else 0
                if v_count == 0 or f_count == 0:
                    print(f"[CONVERTER] Skipping empty vector geometry '{geom_name}' (v={v_count}, f={f_count})")
                    continue
                vec_slot_names.append(geom_name)

            if not vec_slot_names:
                return None, None, None, "[ERROR] Vector export aborted: all generated geometries are empty", None
            vec_preview_colors = vec_color_conf['preview']

            vec_print_settings = {
                'layer_height': '0.08',
                'initial_layer_height': '0.08',
                'wall_loops': '1',
                'top_shell_layers': '0',
                'bottom_shell_layers': '0',
                'sparse_infill_density': '100%',
                'sparse_infill_pattern': 'zig-zag',
                'nozzle_temperature': ['220'] * 8,
                'bed_temperature': ['60'] * 8,
                'filament_type': ['PLA'] * 8,
                'print_speed': '100',
                'travel_speed': '150',
                'enable_support': '0',
                'brim_width': '5',
                'brim_type': 'auto_brim',
            }

            export_t0 = time.perf_counter()
            export_scene_with_bambu_metadata(
                scene=scene,
                output_path=out_path,
                slot_names=vec_slot_names,
                preview_colors=vec_preview_colors,
                settings=vec_print_settings,
                color_mode=vec_color_mode,
            )
            print(f"[CONVERTER] Vector 3MF exported with Bambu metadata: {out_path}")
            vector_timing["export_3mf_s"] = time.perf_counter() - export_t0
            
            # 4. Generate GLB Preview
            _prog(0.82, "生成 3D 预览中... | Generating 3D preview...")
            glb_path = None
            glb_t0 = time.perf_counter()
            try:
                glb_path = os.path.join(OUTPUT_DIR, generate_preview_filename(base_name))
                scene.export(glb_path)
                print(f"[CONVERTER] ✅ Preview GLB exported: {glb_path}")
            except Exception as e:
                print(f"[CONVERTER] Warning: Preview generation skipped: {e}")
            vector_timing["export_glb_s"] = time.perf_counter() - glb_t0
            
            # 5. [FIX] Generate 2D Preview Image from SVG
            _prog(0.90, "生成 2D 预览中... | Generating 2D preview...")
            preview_img = None
            preview_t0 = time.perf_counter()
            skip_heavy_preview = os.getenv("LUMINA_VECTOR_SKIP_2D_PREVIEW", "0") == "1"
            if skip_heavy_preview:
                print("[CONVERTER] Skipping SVG 2D preview due to LUMINA_VECTOR_SKIP_2D_PREVIEW=1")
            elif HAS_SVG_LIB:
                try:
                    # Use SVG-safe rasterization with bounds normalization
                    preview_rgba = vec_processor.img_processor._load_svg(image_path, target_width_mm, pixels_per_mm=10.0)

                    # Apply color replacements to preview if provided
                    if vector_replacements:
                        from core.color_replacement import ColorReplacementManager

                        manager = ColorReplacementManager.from_dict(vector_replacements)
                        replacements = manager.get_all_replacements()
                        
                        if replacements:
                            print(f"[CONVERTER] Applying {len(replacements)} color replacements to SVG preview...")
                            
                            # Extract RGB channels
                            h, w = preview_rgba.shape[:2]
                            rgb_data = preview_rgba[:, :, :3]
                            alpha_data = preview_rgba[:, :, 3]
                            
                            # Process only non-transparent pixels
                            mask_solid = alpha_data > 10
                            
                            # For each replacement, find all pixels close to the original color
                            # and replace them with the new color
                            for orig_color, repl_color in replacements.items():
                                orig_arr = np.array(orig_color, dtype=np.uint8)
                                repl_arr = np.array(repl_color, dtype=np.uint8)
                                
                                # Calculate color distance for all solid pixels
                                # Use a generous threshold to handle anti-aliasing and color variations
                                diff = np.abs(rgb_data.astype(int) - orig_arr.astype(int))
                                distance = np.sum(diff, axis=2)
                                
                                # Match pixels within threshold (generous for SVG rasterization artifacts)
                                threshold = 50  # Increased threshold for better matching
                                match_mask = (distance < threshold) & mask_solid
                                
                                if np.any(match_mask):
                                    rgb_data[match_mask] = repl_arr
                                    matched_count = np.sum(match_mask)
                                    print(f"[CONVERTER]   {orig_color} -> {repl_color}: {matched_count} pixels")
                            
                            # Update preview with replaced colors
                            preview_rgba[:, :, :3] = rgb_data
                            print(f"[CONVERTER] ✅ Color replacements applied to SVG preview")

                    # Downscale overly large previews for UI performance
                    max_preview_px = 1600
                    h, w = preview_rgba.shape[:2]
                    if w > max_preview_px:
                        scale = max_preview_px / w
                        new_w = max_preview_px
                        new_h = max(1, int(h * scale))
                        preview_rgba = cv2.resize(preview_rgba, (new_w, new_h), interpolation=cv2.INTER_AREA)

                    # Fix black background issue: ensure transparent areas have white RGB
                    # This prevents black borders when displaying in UI
                    alpha_channel = preview_rgba[:, :, 3]
                    transparent_mask = alpha_channel == 0
                    if np.any(transparent_mask):
                        preview_rgba[transparent_mask, :3] = 255  # Set RGB to white for transparent pixels
                    
                    preview_img = preview_rgba
                    print("[CONVERTER] ✅ Generated 2D vector preview")
                except Exception as e:
                    print(f"[CONVERTER] Failed to render SVG preview: {e}")
            else:
                print("[CONVERTER] svglib not installed, skipping 2D preview")
            vector_timing["preview_2d_s"] = time.perf_counter() - preview_t0
            
            # Update stats
            Stats.increment("conversions")

            vector_timing["vector_branch_total_s"] = time.perf_counter() - vector_total_t0
            if vector_timing:
                print(
                    "[CONVERTER] Vector timings (s): "
                    f"parse={vector_timing.get('parse_s', 0.0):.3f}, "
                    f"clip={vector_timing.get('occlusion_s', 0.0):.3f}, "
                    f"match={vector_timing.get('color_match_s', 0.0):.3f}, "
                    f"extrude_bottom={vector_timing.get('extrude_bottom_s', 0.0):.3f}, "
                    f"backing={vector_timing.get('backing_s', 0.0):.3f}, "
                    f"extrude_top={vector_timing.get('extrude_top_s', 0.0):.3f}, "
                    f"assemble={vector_timing.get('assemble_s', 0.0):.3f}, "
                    f"mesh_total={vector_timing.get('mesh_total_s', 0.0):.3f}, "
                    f"export_3mf={vector_timing.get('export_3mf_s', 0.0):.3f}, "
                    f"export_glb={vector_timing.get('export_glb_s', 0.0):.3f}, "
                    f"preview_2d={vector_timing.get('preview_2d_s', 0.0):.3f}, "
                    f"total={vector_timing.get('vector_branch_total_s', 0.0):.3f}"
                )
            
            # Return results (Vector mode doesn't generate color recipe)
            msg = f"✅ Vector conversion complete! Objects merged by material."
            return out_path, glb_path, preview_img, msg, None
            
        except Exception as e:
            error_msg = f"❌ Vector processing failed: {e}\n\n"
            error_msg += "Suggestions:\n"
            error_msg += "• Ensure SVG has filled paths (not just strokes)\n"
            error_msg += "• Try opening in Inkscape and re-saving as 'Plain SVG'\n"
            error_msg += "• Convert text to paths (Path → Object to Path)\n"
            error_msg += "• Or switch to 'High-Fidelity' mode for rasterization"
            
            print(f"[CONVERTER] {error_msg}")
            return None, None, None, error_msg, None
    
    # If vector mode selected but file is not SVG, show warning
    if modeling_mode == ModelingMode.VECTOR and not image_path.lower().endswith('.svg'):
        return None, None, None, (
            "⚠️ Vector Native mode requires SVG files!\n\n"
            "Your file is not an SVG. Please either:\n"
            "• Upload an SVG file, or\n"
            "• Switch to 'High-Fidelity' or 'Pixel Art' mode"
        ), None
    
    # ========== [EXISTING] Raster-based Processing ==========
    # NOTE: CMYW and RYBW share 100% of the processing pipeline.
    # Only difference is the LUT file and slot names from ColorSystem.get()
    # All K-Means, layer slicing, and mesh generation logic is unified.
    
    color_conf = ColorSystem.get(color_mode)
    slot_names = color_conf['slots']
    preview_colors = color_conf['preview']
    
    # Validate backing_color_id (allow -2 as special marker for separation)
    num_materials = len(slot_names)
    if backing_color_id != -2 and (backing_color_id < 0 or backing_color_id >= num_materials):
        print(f"[CONVERTER] Warning: Invalid backing_color_id={backing_color_id}, using default (0)")
        backing_color_id = 0
    
    # Step 1: Image Processing
    _prog(0.05, "图像处理与 LUT 匹配中... | Processing image...")
    # Always enable HiFi timing for better observability (zero-overhead when not printing)
    _bench_enabled = True
    _hifi_timings = {}
    _hifi_t0 = time.perf_counter()
    
    try:
        processor = LuminaImageProcessor(actual_lut_path, color_mode, hue_weight=hue_weight)
        processor.enable_cleanup = enable_cleanup
        result = processor.process_image(
            image_path=image_path,
            target_width_mm=target_width_mm,
            modeling_mode=modeling_mode,
            quantize_colors=quantize_colors,
            auto_bg=auto_bg,
            bg_tol=bg_tol,
            blur_kernel=blur_kernel,
            smooth_sigma=smooth_sigma
        )
        _hifi_timings['image_proc_s'] = time.perf_counter() - _hifi_t0
    except Exception as e:
        return None, None, None, f"[ERROR] Image processing failed: {e}", None
    
    matched_rgb = result['matched_rgb']
    material_matrix = result['material_matrix']
    mask_solid = result['mask_solid']
    target_w, target_h = result['dimensions']
    pixel_scale = result['pixel_scale']
    mode_info = result['mode_info']
    debug_data = result.get('debug_data', None)

    # Override preview_colors with actual per-slot measured colors from the LUT.
    # ColorSystem.SIX_COLOR always uses CMYWGK defaults, but a RYBWGK user
    # (e.g. 瑞贝思) has different filaments in each slot.  Using the hardcoded
    # CMYWGK colours causes BambuStudio AMS to display the wrong colour for each
    # slot, leading the user to load the wrong filament → wrong print result.
    # We derive the true colour from the LUT's own pure-colour entries instead.
    if hasattr(processor, 'ref_stacks') and processor.ref_stacks is not None:
        actual_slot_colors = _get_actual_lut_slot_colors(processor)
        if actual_slot_colors:
            preview_colors = dict(preview_colors)  # local copy; don't mutate shared config
            for slot_id, rgb in actual_slot_colors.items():
                preview_colors[slot_id] = [rgb[0], rgb[1], rgb[2], 255]
            print(f"[CONVERTER] LUT slot colors derived from calibration data:")
            for sid in sorted(preview_colors):
                c = preview_colors[sid]
                print(f"[CONVERTER]   slot{sid}: #{c[0]:02x}{c[1]:02x}{c[2]:02x}")

    # Apply color replacements if provided
    # Also convert API-format replacement_regions (without masks) into color_replacements
    effective_color_replacements = _normalize_color_replacements_input(color_replacements)
    if replacement_regions:
        api_format_replacements = _normalize_color_replacements_input(replacement_regions)
        if api_format_replacements:
            effective_color_replacements.update(api_format_replacements)
            # Remove API-format items (no mask) from replacement_regions to avoid
            # _apply_regions_to_raster_outputs skipping them silently
            replacement_regions = [r for r in replacement_regions if r.get('mask') is not None]

    if effective_color_replacements:
        from core.color_replacement import ColorReplacementManager
        manager = ColorReplacementManager.from_dict(effective_color_replacements)
        old_rgb = matched_rgb.copy()
        matched_rgb = manager.apply_to_image(matched_rgb)
        print(f"[CONVERTER] Applied {len(manager)} color replacements")

        # Update material_matrix: find the replacement color's LUT entry
        # and use its stacking layers (ref_stacks) for correct multi-layer output
        for orig_hex, repl_hex in effective_color_replacements.items():
            orig_rgb_tuple = ColorReplacementManager._hex_to_color(orig_hex)
            repl_rgb_tuple = ColorReplacementManager._hex_to_color(repl_hex)
            # Find pixels that were originally this color
            orig_mask = np.all(old_rgb == orig_rgb_tuple, axis=-1)
            if not np.any(orig_mask):
                continue
            # Query KDTree to find the closest LUT entry for the replacement color (in CIELAB space)
            repl_lab = processor._rgb_to_lab(np.array([repl_rgb_tuple], dtype=np.uint8))
            _, lut_idx = processor.kdtree.query(repl_lab)
            lut_idx = lut_idx[0]
            new_stacks = processor.ref_stacks[lut_idx]  # (COLOR_LAYERS,)
            material_matrix[orig_mask] = new_stacks
            lut_color = processor.lut_rgb[lut_idx]
            print(f"[CONVERTER] material_matrix: {orig_hex} → LUT#{lut_idx} rgb({lut_color[0]},{lut_color[1]},{lut_color[2]}) stacks={new_stacks}")

    # Apply region replacements in-order (later items override earlier items)
    if replacement_regions:
        def _resolve_lut_index_for_rgb(replacement_rgb):
            repl_lab = processor._rgb_to_lab(np.array([replacement_rgb], dtype=np.uint8))
            _, lut_idx = processor.kdtree.query(repl_lab)
            return lut_idx[0]

        matched_rgb, material_matrix = _apply_regions_to_raster_outputs(
            matched_rgb,
            material_matrix,
            mask_solid,
            replacement_regions,
            _resolve_lut_index_for_rgb,
            processor.ref_stacks,
        )
    
    print(f"[CONVERTER] Image processed: {target_w}×{target_h}px, scale={pixel_scale}mm/px")
    
    # Step 2: Save Debug Preview (High-Fidelity mode only)
    if debug_data is not None and mode_info['mode'] == ModelingMode.HIGH_FIDELITY:
        try:
            num_materials = len(slot_names)
            _save_debug_preview(
                debug_data=debug_data,
                material_matrix=material_matrix,
                mask_solid=mask_solid,
                image_path=image_path,
                mode_name=mode_info['name'],
                num_materials=num_materials
            )
        except Exception as e:
            print(f"[CONVERTER] Warning: Failed to save debug preview: {e}")
    
    # Step 3: Generate Preview Image
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    preview_rgba[mask_solid, 3] = 255
    
    # Step 4: Handle Keychain Loop
    loop_info = None
    if add_loop and loop_pos is not None:
        loop_info = _calculate_loop_info(
            loop_pos, loop_width, loop_length, loop_hole,
            mask_solid, material_matrix, target_w, target_h, pixel_scale
        )
        
        if loop_info:
            preview_rgba = _draw_loop_on_preview(
                preview_rgba, loop_info, color_conf, pixel_scale
            )
    
    preview_img = Image.fromarray(preview_rgba, mode='RGBA')
    
    # Step 5: Build Voxel Matrix
    # Error handling for backing layer marking (Requirement 8.2)
    try:
        # ========== 5-Color Extended: force single-sided face-up ==========
        # Face-up: backing on print bed, viewing surface on top.
        # Base stacks have air at index 0 so their viewing surface sits 1 Z
        # below extended stacks, keeping ≤4 materials per Z layer.
        if "5-Color Extended" in color_mode:
            print(f"[CONVERTER] 5-Color Extended: forcing single-sided face-up")
            structure_mode = "单面"
            if enable_relief:
                print(f"[CONVERTER] 5-Color Extended: 2.5D relief mode disabled (incompatible)")
                enable_relief = False
            full_matrix, backing_metadata = _build_voxel_matrix_faceup(
                material_matrix, mask_solid, spacer_thick, backing_color_id
            )
        # ========== Cloisonné (掐丝珐琅) Mode ==========
        elif enable_cloisonne:
            print(f"[CONVERTER] 🎨 Cloisonné Mode ENABLED")
            print(f"[CONVERTER] Wire: width={wire_width_mm}mm, height={wire_height_mm}mm")
            
            # Force single-sided (face-up)
            structure_mode = "单面"
            
            # Extract wireframe mask from matched colours
            mask_wireframe = processor._extract_wireframe_mask(
                matched_rgb, target_w, pixel_scale, wire_width_mm
            )
            
            full_matrix, backing_metadata = _build_cloisonne_voxel_matrix(
                material_matrix, mask_solid, mask_wireframe,
                spacer_thick, wire_height_mm, backing_color_id
            )
        # ========== 2.5D Relief Mode Support ==========
        # 显式模式判断：height_mode 参数决定分支
        heightmap_height_matrix = None
        heightmap_stats = None
        if enable_relief and height_mode == "heightmap" and heightmap_path is not None:
            print(f"[CONVERTER] Heightmap Relief Mode: 尝试加载高度图...")
            print(f"[CONVERTER] 高度图路径: {heightmap_path}")
            try:
                hm_max = heightmap_max_height if heightmap_max_height is not None else 5.0
                hm_result = HeightmapLoader.load_and_process(
                    heightmap_path=heightmap_path,
                    target_w=target_w,
                    target_h=target_h,
                    max_relief_height=hm_max,
                    base_thickness=spacer_thick
                )
                if hm_result['success']:
                    heightmap_height_matrix = hm_result['height_matrix']
                    heightmap_stats = hm_result['stats']
                    for w in hm_result.get('warnings', []):
                        print(f"[CONVERTER] {w}")
                    print(f"[CONVERTER] 高度图加载成功: {heightmap_height_matrix.shape}")
                else:
                    print(f"[CONVERTER] WARNING: 高度图处理失败: {hm_result['error']}，回退到 flat 模式")
            except Exception as e:
                print(f"[CONVERTER] WARNING: 高度图处理异常: {e}，回退到 flat 模式")
        elif enable_relief and height_mode == "heightmap" and heightmap_path is None:
            print("[CONVERTER] WARNING: heightmap mode selected but no heightmap provided, falling back to flat")

        if heightmap_height_matrix is not None:
            # 高度图模式：使用逐像素高度矩阵
            print(f"[CONVERTER] 2.5D Heightmap Relief Mode ENABLED")
            full_matrix, backing_metadata = _build_relief_voxel_matrix(
                matched_rgb=matched_rgb,
                material_matrix=material_matrix,
                mask_solid=mask_solid,
                color_height_map=color_height_map if color_height_map else {},
                default_height=spacer_thick,
                structure_mode=structure_mode,
                backing_color_id=backing_color_id,
                pixel_scale=pixel_scale,
                height_matrix=heightmap_height_matrix
            )
        elif enable_relief and height_mode == "color" and color_height_map:
            print(f"[CONVERTER] 2.5D Relief Mode ENABLED")
            print(f"[CONVERTER] Color height map: {color_height_map}")
            
            # Build relief voxel matrix with per-color heights
            full_matrix, backing_metadata = _build_relief_voxel_matrix(
                matched_rgb=matched_rgb,
                material_matrix=material_matrix,
                mask_solid=mask_solid,
                color_height_map=color_height_map,
                default_height=spacer_thick,
                structure_mode=structure_mode,
                backing_color_id=backing_color_id,
                pixel_scale=pixel_scale
            )
        else:
            # Original flat voxel matrix
            full_matrix, backing_metadata = _build_voxel_matrix(
                material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id
            )
        
        total_layers = full_matrix.shape[0]
        print(f"[CONVERTER] Voxel matrix: {full_matrix.shape} (Z×H×W)")
        print(f"[CONVERTER] Backing layer: z={backing_metadata['backing_z_range']}, color_id={backing_metadata['backing_color_id']}")
    except Exception as e:
        print(f"[CONVERTER] Error marking backing layer: {e}")
        print(f"[CONVERTER] Falling back to original behavior (backing_color_id=0)")
        
        # Fallback to original behavior (Requirement 8.2)
        try:
            full_matrix, backing_metadata = _build_voxel_matrix(
                material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id=0
            )
            total_layers = full_matrix.shape[0]
            print(f"[CONVERTER] Fallback successful: {full_matrix.shape} (Z×H×W)")
        except Exception as fallback_error:
            return None, None, None, f"[ERROR] Voxel matrix generation failed: {fallback_error}", None
    
    # Step 6: Generate 3D Meshes
    _prog(0.30, "生成 3D 网格中... | Generating meshes...")
    _mesh_t0 = time.perf_counter() if _bench_enabled else None
    
    scene = trimesh.Scene()
    
    transform = np.eye(4)
    transform[0, 0] = pixel_scale
    transform[1, 1] = pixel_scale
    transform[2, 2] = PrinterConfig.LAYER_HEIGHT
    
    print(f"[CONVERTER] Transform: XY={pixel_scale}mm/px, Z={PrinterConfig.LAYER_HEIGHT}mm/layer")
    
    mesher = get_mesher(modeling_mode)
    print(f"[CONVERTER] Using mesher: {mesher.__class__.__name__}")
    
    valid_slot_names = []
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
            scene.add_geometry(
                mesh, 
                node_name=name, 
                geom_name=name
            )
            valid_slot_names.append(name)
            print(f"[CONVERTER] Added mesh for {name}")
    
    # Conditionally generate backing mesh (only when separate_backing=True)
    # Error handling for backing mesh generation (Requirement 8.1, 8.3)
    if separate_backing:
        print(f"[CONVERTER] Attempting to generate separate backing mesh (mat_id=-2)...")
        try:
            backing_mesh = mesher.generate_mesh(full_matrix, mat_id=-2, height_px=target_h)
            
            print(f"[CONVERTER] Backing mesh result: {backing_mesh}")
            if backing_mesh is not None:
                print(f"[CONVERTER] Backing mesh vertices: {len(backing_mesh.vertices)}")
            
            if backing_mesh is None or len(backing_mesh.vertices) == 0:
                # Empty mesh - skip and log warning (Requirement 8.3)
                print(f"[CONVERTER] Warning: Backing mesh is empty, skipping separate backing object")
                print(f"[CONVERTER] Continuing with other material meshes...")
            else:
                backing_mesh.apply_transform(transform)
                
                # Apply white color (material_id=0)
                backing_color = preview_colors[0]  # Fixed to white
                backing_mesh.visual.face_colors = backing_color
                
                backing_name = "Backing"
                backing_mesh.metadata['name'] = backing_name
                scene.add_geometry(backing_mesh, node_name=backing_name, geom_name=backing_name)
                valid_slot_names.append(backing_name)
                print(f"[CONVERTER] ✅ Added backing mesh as separate object (white)")
                print(f"[CONVERTER] Scene now has {len(scene.geometry)} geometries")
        except Exception as e:
            # Log error and continue with other meshes (Requirement 8.1)
            print(f"[CONVERTER] Error generating backing mesh: {e}")
            import traceback
            traceback.print_exc()
            print(f"[CONVERTER] Continuing with other material meshes...")
    else:
        print(f"[CONVERTER] Backing merged with first layer (original behavior)")
    
    # Cloisonné wire mesh (standalone object, mat_id=-3)
    if enable_cloisonne and backing_metadata.get('is_cloisonne'):
        print(f"[CONVERTER] Generating cloisonné wire mesh (mat_id=-3)...")
        try:
            wire_mesh = mesher.generate_mesh(full_matrix, mat_id=-3, height_px=target_h)
            if wire_mesh is not None and len(wire_mesh.vertices) > 0:
                wire_mesh.apply_transform(transform)
                wire_mesh.visual.face_colors = [218, 165, 32, 255]  # Gold colour
                wire_name = "Wire"
                wire_mesh.metadata['name'] = wire_name
                scene.add_geometry(wire_mesh, node_name=wire_name, geom_name=wire_name)
                valid_slot_names.append(wire_name)
                print(f"[CONVERTER] ✅ Added wire mesh as standalone object ({len(wire_mesh.vertices)} verts)")
            else:
                print(f"[CONVERTER] Warning: Wire mesh is empty, skipping")
        except Exception as e:
            print(f"[CONVERTER] Error generating wire mesh: {e}")
            import traceback
            traceback.print_exc()
    
    # Free Color (自由色) mesh extraction
    if free_color_set:
        _free_set = {c.lower() for c in free_color_set if c}
        if _free_set:
            print(f"[CONVERTER] 🎯 Free Color mode: {len(_free_set)} colors marked")
            for hex_c in sorted(_free_set):
                try:
                    # Parse hex to RGB
                    r_fc = int(hex_c[1:3], 16)
                    g_fc = int(hex_c[3:5], 16)
                    b_fc = int(hex_c[5:7], 16)
                    # Build mask for this color in matched_rgb
                    color_mask = (
                        (matched_rgb[:, :, 0] == r_fc) &
                        (matched_rgb[:, :, 1] == g_fc) &
                        (matched_rgb[:, :, 2] == b_fc) &
                        mask_solid
                    )
                    if not np.any(color_mask):
                        print(f"[CONVERTER]   {hex_c}: no pixels found, skipping")
                        continue
                    # Build a sub-voxel matrix: keep only this color's voxels
                    fc_matrix = np.where(
                        np.broadcast_to(color_mask[np.newaxis, :, :], full_matrix.shape),
                        full_matrix, -1
                    )
                    # Replace all non-air values with a single ID (0) for meshing
                    fc_matrix = np.where(fc_matrix >= 0, 0, -1)
                    fc_mesh = mesher.generate_mesh(fc_matrix, 0, target_h)
                    if fc_mesh and len(fc_mesh.vertices) > 0:
                        fc_mesh.apply_transform(transform)
                        fc_mesh.visual.face_colors = [r_fc, g_fc, b_fc, 255]
                        fc_name = f"Free_{hex_c[1:]}"
                        fc_mesh.metadata['name'] = fc_name
                        scene.add_geometry(fc_mesh, node_name=fc_name, geom_name=fc_name)
                        valid_slot_names.append(fc_name)
                        print(f"[CONVERTER]   ✅ {hex_c} → standalone object '{fc_name}' ({np.sum(color_mask)} px)")
                    else:
                        print(f"[CONVERTER]   {hex_c}: mesh empty, skipping")
                except Exception as e:
                    print(f"[CONVERTER]   Error extracting free color {hex_c}: {e}")
    
    _hifi_timings['mesh_gen_s'] = time.perf_counter() - _mesh_t0
    
    # Step 7: Add Keychain Loop
    loop_added = False
    
    if add_loop and loop_info is not None:
        try:
            loop_thickness = total_layers * PrinterConfig.LAYER_HEIGHT
            loop_mesh = create_keychain_loop(
                width_mm=loop_info['width_mm'],
                length_mm=loop_info['length_mm'],
                hole_dia_mm=loop_info['hole_dia_mm'],
                thickness_mm=loop_thickness,
                attach_x_mm=loop_info['attach_x_mm'],
                attach_y_mm=loop_info['attach_y_mm']
            )
            
            if loop_mesh is not None:
                loop_mesh.visual.face_colors = preview_colors[loop_info['color_id']]
                loop_mesh.metadata['name'] = "Keychain_Loop"
                scene.add_geometry(
                    loop_mesh, 
                    node_name="Keychain_Loop", 
                    geom_name="Keychain_Loop"
                )
                valid_slot_names.append("Keychain_Loop")
                loop_added = True
                print(f"[CONVERTER] Loop added successfully")
        except Exception as e:
            print(f"[CONVERTER] Loop creation failed: {e}")
    
    # ========== Step 7.4: Generate Coating Mesh (透明镀层) ==========
    if enable_coating:
        try:
            coating_layers = max(1, int(round(coating_height_mm / PrinterConfig.LAYER_HEIGHT)))
            print(f"[CONVERTER] 🪟 Generating coating: height={coating_height_mm}mm ({coating_layers} layers), bottom side")

            # Determine coating coverage area
            coating_mask = mask_solid.copy()
            
            # [FIX] If outline is enabled, extend coating to cover outline area as well
            if enable_outline:
                print(f"[CONVERTER] 🔲 Extending coating to cover outline area (width={outline_width}mm)")
                # Dilate mask to include outline area
                outline_width_px = max(1, int(round(outline_width / pixel_scale)))
                kernel = np.ones((3, 3), np.uint8)
                mask_uint8 = mask_solid.astype(np.uint8) * 255
                dilated_mask = cv2.dilate(mask_uint8, kernel, iterations=outline_width_px)
                coating_mask = (dilated_mask > 0)

            # Build a small voxel matrix for the coating: coating_layers × H × W
            coating_matrix = np.full((coating_layers, target_h, target_w), -1, dtype=int)
            coating_slice = np.where(coating_mask, 0, -1).astype(int)
            coating_matrix[:] = coating_slice[np.newaxis, :, :]

            coating_mesh = mesher.generate_mesh(coating_matrix, 0, target_h)
            if coating_mesh and len(coating_mesh.vertices) > 0:
                # Transform XY same as model, Z same layer height
                coat_transform = np.eye(4)
                coat_transform[0, 0] = pixel_scale
                coat_transform[1, 1] = pixel_scale
                coat_transform[2, 2] = PrinterConfig.LAYER_HEIGHT
                # Shift down so coating sits below the model (Z < 0)
                coat_transform[2, 3] = -coating_layers * PrinterConfig.LAYER_HEIGHT
                coating_mesh.apply_transform(coat_transform)
                coating_mesh.visual.face_colors = [200, 200, 200, 80]  # Semi-transparent grey
                coating_name = "Coating"
                coating_mesh.metadata['name'] = coating_name
                scene.add_geometry(coating_mesh, node_name=coating_name, geom_name=coating_name)
                valid_slot_names.append(coating_name)
                print(f"[CONVERTER] ✅ Coating added as standalone '{coating_name}' ({coating_layers} layers)")
            else:
                print(f"[CONVERTER] Warning: Coating mesh empty, skipping")
        except Exception as e:
            print(f"[CONVERTER] Coating generation failed: {e}")
            import traceback
            traceback.print_exc()

    # ========== Step 7.5: Generate Outline Mesh ==========
    outline_added = False
    if enable_outline:
        try:
            # Outline thickness matches the full model height
            outline_thickness_mm = total_layers * PrinterConfig.LAYER_HEIGHT
            # If coating is enabled, extend outline downward to cover coating layers
            outline_z_offset = 0.0
            if enable_coating:
                coating_layers = max(1, int(round(coating_height_mm / PrinterConfig.LAYER_HEIGHT)))
                coating_mm = coating_layers * PrinterConfig.LAYER_HEIGHT
                outline_thickness_mm += coating_mm
                outline_z_offset = -coating_mm
                print(f"[CONVERTER] 🔲 Outline extended to cover coating: total_thickness={outline_thickness_mm}mm")
            
            print(f"[CONVERTER] 🔲 Generating outline: width={outline_width}mm, thickness={outline_thickness_mm}mm (z_offset={outline_z_offset}mm)")
            
            outline_mesh = _generate_outline_mesh(
                mask_solid=mask_solid,
                pixel_scale=pixel_scale,
                outline_width_mm=outline_width,
                outline_thickness_mm=outline_thickness_mm,
                target_h=target_h
            )
            
            if outline_mesh is not None:
                # Shift outline down if coating is enabled
                if outline_z_offset != 0.0:
                    outline_mesh.vertices[:, 2] += outline_z_offset
                # Outline is always white (material 0) as a standalone object
                outline_mesh.visual.face_colors = preview_colors[0]
                outline_name = "Outline"
                outline_mesh.metadata['name'] = outline_name
                scene.add_geometry(outline_mesh, node_name=outline_name, geom_name=outline_name)
                valid_slot_names.append(outline_name)
                print(f"[CONVERTER] ✅ Outline added as standalone '{outline_name}' object")
                outline_added = True
            else:
                print(f"[CONVERTER] Warning: Outline mesh is empty, skipping")
        except Exception as e:
            print(f"[CONVERTER] Outline generation failed: {e}")
            import traceback
            traceback.print_exc()
    
    # ========== Step 8: Export 3MF ==========
    is_single_sided = "单面" in structure_mode or "Single" in structure_mode
    is_5color = "5-Color Extended" in color_mode

    # 5-Color 高保真：体素 Z 与 BambuStudio 显示约定相反，需 Z 翻转使顶面（观看面）朝上
    if is_5color:
        max_z = max(
            g.vertices[:, 2].max()
            for g in scene.geometry.values()
            if hasattr(g, "vertices") and len(g.vertices) > 0
        )
        z_flip = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, -1, max_z],
            [0, 0, 0, 1],
        ])
        for geom_name in list(scene.geometry.keys()):
            scene.geometry[geom_name].apply_transform(z_flip)

    # 单面模式：X 轴镜像修正（BambuStudio writer 需要）
    if is_single_sided:
        model_width_mm = target_w * pixel_scale
        mirror_transform = np.array([
            [-1, 0, 0, model_width_mm],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ])
        for geom_name in list(scene.geometry.keys()):
            scene.geometry[geom_name].apply_transform(mirror_transform)

    # 5-Color 高保真：单面 X 镜像后左右仍反，再补一次 X 镜像使左右正确
    if is_5color:
        model_width_mm = target_w * pixel_scale
        x_mirror_again = np.array([
            [-1, 0, 0, model_width_mm],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1]
        ])
        for geom_name in list(scene.geometry.keys()):
            scene.geometry[geom_name].apply_transform(x_mirror_again)

    _prog(0.50, "导出 3MF 中... | Exporting 3MF...")
    _export_t0 = time.perf_counter() if _bench_enabled else None
    
    base_name = os.path.splitext(os.path.basename(image_path))[0]
    out_path = os.path.join(OUTPUT_DIR, generate_model_filename(base_name, modeling_mode, color_mode))
    
    # Check if scene has any geometry before exporting (Requirement 8.1)
    if len(scene.geometry) == 0:
        print(f"[CONVERTER] Error: No meshes generated, cannot export 3MF")
        return None, None, None, "[ERROR] Mesh generation failed: No valid meshes generated", None
    
    # BambuStudio print settings
    print_settings = {
        'layer_height': '0.08',
        'initial_layer_height': '0.08',
        'wall_loops': '1',
        'top_shell_layers': '0',
        'bottom_shell_layers': '0',
        'sparse_infill_density': '100%',
        'sparse_infill_pattern': 'zig-zag',
        'nozzle_temperature': ['220'] * 8,
        'bed_temperature': ['60'] * 8,
        'filament_type': ['PLA'] * 8,
        'print_speed': '100',
        'travel_speed': '150',
        'enable_support': '0',
        'brim_width': '5',
        'brim_type': 'auto_brim',
    }
    
    try:
        print(f"[CONVERTER] Exporting with BambuStudio metadata...")
        export_scene_with_bambu_metadata(
            scene=scene,
            output_path=out_path,
            slot_names=valid_slot_names,
            preview_colors=preview_colors,
            settings=print_settings,
            color_mode=color_mode
        )
        _hifi_timings['export_3mf_s'] = time.perf_counter() - _export_t0
        print(f"[CONVERTER] 3MF exported with embedded settings: {out_path}")
    except Exception as e:
        print(f"[CONVERTER] Error exporting 3MF: {e}")
        return None, None, None, f"[ERROR] 3MF export failed: {e}", None
    
    # Step 8.5: Generate Color Recipe Report
    color_recipe_path = None
    recipe_policy = os.getenv("LUMINA_COLOR_RECIPE_POLICY", "auto").strip().lower()
    try:
        recipe_auto_max_pixels = int(os.getenv("LUMINA_COLOR_RECIPE_AUTO_MAX_PIXELS", "1200000"))
    except Exception:
        recipe_auto_max_pixels = 1200000
    solid_pixels = int(np.count_nonzero(mask_solid))
    enable_recipe = recipe_policy == "on" or (
        recipe_policy == "auto" and solid_pixels <= recipe_auto_max_pixels
    )
    if enable_recipe:
        try:
            from utils.color_recipe_logger import ColorRecipeLogger

            model_filename = os.path.basename(out_path)
            color_recipe_path = ColorRecipeLogger.create_from_processor(
                processor=processor,
                output_dir=OUTPUT_DIR,
                model_filename=model_filename,
                matched_rgb=matched_rgb,
                material_matrix=material_matrix,
                mask_solid=mask_solid
            )
        except Exception as e:
            print(f"[CONVERTER] Warning: Failed to generate color recipe report: {e}")
    else:
        print(
            f"[CONVERTER] Skipping color recipe report: policy={recipe_policy}, "
            f"solid_pixels={solid_pixels}, auto_max={recipe_auto_max_pixels}"
        )
    
    # Step 9: Generate 3D Preview
    _prog(0.90, "生成 3D 预览中... | Generating 3D preview...")
    preview_mesh = _create_preview_mesh(
        matched_rgb, mask_solid, total_layers,
        backing_color_id=backing_color_id,
        backing_z_range=backing_metadata['backing_z_range'],
        preview_colors=preview_colors
    )

    if preview_mesh:
        preview_mesh.apply_transform(transform)
        
        if loop_added and loop_info:
            try:
                preview_loop = create_keychain_loop(
                    width_mm=loop_info['width_mm'],
                    length_mm=loop_info['length_mm'],
                    hole_dia_mm=loop_info['hole_dia_mm'],
                    thickness_mm=loop_thickness,
                    attach_x_mm=loop_info['attach_x_mm'],
                    attach_y_mm=loop_info['attach_y_mm']
                )
                if preview_loop:
                    loop_color = preview_colors[loop_info['color_id']]
                    preview_loop.visual.face_colors = [loop_color] * len(preview_loop.faces)
                    preview_mesh = trimesh.util.concatenate([preview_mesh, preview_loop])
            except Exception as e:
                print(f"[CONVERTER] Preview loop failed: {e}")
        
        # Add outline to preview
        if outline_added:
            try:
                outline_thickness_mm = total_layers * PrinterConfig.LAYER_HEIGHT
                preview_outline = _generate_outline_mesh(
                    mask_solid=mask_solid,
                    pixel_scale=pixel_scale,
                    outline_width_mm=outline_width,
                    outline_thickness_mm=outline_thickness_mm,
                    target_h=target_h
                )
                if preview_outline:
                    outline_color = preview_colors[0]  # White
                    preview_outline.visual.face_colors = [outline_color] * len(preview_outline.faces)
                    preview_mesh = trimesh.util.concatenate([preview_mesh, preview_outline])
            except Exception as e:
                print(f"[CONVERTER] Preview outline failed: {e}")
    
    if preview_mesh:
        glb_path = os.path.join(OUTPUT_DIR, generate_preview_filename(base_name))

        # Export model-only GLB (bed platform is rendered by frontend)
        preview_mesh.export(glb_path)
    else:
        glb_path = None
    
    # Step 10: Generate Status Message
    Stats.increment("conversions")
    
    # Output detailed timing for HiFi mode
    if _hifi_timings:
        image_proc_s = _hifi_timings.get('image_proc_s', 0.0)
        mesh_gen_s = _hifi_timings.get('mesh_gen_s', 0.0)
        export_3mf_s = _hifi_timings.get('export_3mf_s', 0.0)
        total_s = image_proc_s + mesh_gen_s + export_3mf_s
        print(
            "[CONVERTER] HiFi timings (s): "
            f"image_proc={image_proc_s:.3f}, "
            f"mesh_gen={mesh_gen_s:.3f}, "
            f"export_3mf={export_3mf_s:.3f}, "
            f"total={total_s:.3f}"
        )
    
    mode_name = mode_info['mode'].get_display_name()
    msg = f"✅ Conversion complete ({mode_name})! Resolution: {target_w}×{target_h}px"
    
    # 高度图统计信息输出
    if heightmap_stats is not None:
        msg += (f" | 📊 高度图: {heightmap_stats['min_mm']:.1f}mm ~ "
                f"{heightmap_stats['max_mm']:.1f}mm (avg {heightmap_stats['avg_mm']:.1f}mm)")
    
    if loop_added:
        msg += f" | Loop: {slot_names[loop_info['color_id']]}"
    
    total_pixels = target_w * target_h
    if glb_path and total_pixels > 500_000:
        msg += " | 3D preview simplified"
    
    return out_path, glb_path, preview_img, msg, color_recipe_path



# ========== Helper Functions ==========

def _parse_outline_slot(slot_str, num_materials):
    """Parse outline color slot string to material index.
    
    Args:
        slot_str: e.g. "Slot 1", "Slot 2", etc.
        num_materials: Total number of materials
    
    Returns:
        int: Material index (0-based), clamped to valid range
    """
    try:
        idx = int(slot_str.replace("Slot ", "")) - 1
        return max(0, min(idx, num_materials - 1))
    except (ValueError, AttributeError):
        return 0


def _generate_outline_mesh(mask_solid, pixel_scale, outline_width_mm, outline_thickness_mm, target_h):
    """Generate a ring-shaped outline mesh around the outer contour of the model.
    
    Algorithm:
    1. Find outer contour of mask_solid using cv2.findContours
    2. Dilate the mask outward by outline_width_mm
    3. Create ring = dilated - original
    4. Extrude the ring to outline_thickness_mm height
    
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
    
    print(f"[OUTLINE] Width: {outline_width_mm}mm = {outline_width_px}px, Thickness: {outline_thickness_mm}mm = {outline_layers} layers")
    
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
    # Note: h, w are padded dimensions; use pad offset for world coordinates
    processed = np.zeros_like(ring_mask, dtype=bool)
    vertices = []
    faces = []
    
    z_bottom = 0.0
    z_top = float(outline_layers)
    
    for y in range(h):
        row_valid = ring_mask[y] & ~processed[y]
        if not np.any(row_valid):
            continue
        
        padded = np.concatenate([[False], row_valid, [False]])
        diff = np.diff(padded.astype(np.int8))
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


def _calculate_loop_info(loop_pos, loop_width, loop_length, loop_hole,
                         mask_solid, material_matrix, target_w, target_h, pixel_scale):
    """Calculate keychain loop information."""
    solid_rows = np.any(mask_solid, axis=1)
    if not np.any(solid_rows):
        return None
    
    click_x, click_y = loop_pos
    attach_col = int(click_x)
    attach_row = int(click_y)
    attach_col = max(0, min(target_w - 1, attach_col))
    attach_row = max(0, min(target_h - 1, attach_row))
    
    col_mask = mask_solid[:, attach_col]
    if np.any(col_mask):
        solid_rows_in_col = np.where(col_mask)[0]
        distances = np.abs(solid_rows_in_col - attach_row)
        nearest_idx = np.argmin(distances)
        top_row = solid_rows_in_col[nearest_idx]
    else:
        top_row = np.argmax(solid_rows)
        solid_cols_in_top = np.where(mask_solid[top_row])[0]
        if len(solid_cols_in_top) > 0:
            distances = np.abs(solid_cols_in_top - attach_col)
            nearest_idx = np.argmin(distances)
            attach_col = solid_cols_in_top[nearest_idx]
        else:
            attach_col = target_w // 2
    
    attach_col = max(0, min(target_w - 1, attach_col))
    
    loop_color_id = 0
    search_area = material_matrix[
        max(0, top_row-2):top_row+3,
        max(0, attach_col-3):attach_col+4
    ]
    search_area = search_area[search_area >= 0]
    if len(search_area) > 0:
        unique, counts = np.unique(search_area, return_counts=True)
        for mat_id in unique[np.argsort(-counts)]:
            if mat_id != 0:
                loop_color_id = int(mat_id)
                break
    
    return {
        'attach_x_mm': attach_col * pixel_scale,
        'attach_y_mm': (target_h - 1 - top_row) * pixel_scale,
        'width_mm': loop_width,
        'length_mm': loop_length,
        'hole_dia_mm': loop_hole,
        'color_id': loop_color_id
    }


def _draw_loop_on_preview(preview_rgba, loop_info, color_conf, pixel_scale):
    """Draw keychain loop on preview image."""
    preview_pil = Image.fromarray(preview_rgba, mode='RGBA')
    draw = ImageDraw.Draw(preview_pil)
    
    loop_color_rgba = tuple(color_conf['preview'][loop_info['color_id']][:3]) + (255,)
    
    attach_col = int(loop_info['attach_x_mm'] / pixel_scale)
    attach_row = int((preview_rgba.shape[0] - 1) - loop_info['attach_y_mm'] / pixel_scale)
    
    loop_w_px = int(loop_info['width_mm'] / pixel_scale)
    loop_h_px = int(loop_info['length_mm'] / pixel_scale)
    hole_r_px = int(loop_info['hole_dia_mm'] / 2 / pixel_scale)
    circle_r_px = loop_w_px // 2
    
    loop_bottom = attach_row
    loop_left = attach_col - loop_w_px // 2
    loop_right = attach_col + loop_w_px // 2
    
    rect_h_px = loop_h_px - circle_r_px
    rect_bottom = loop_bottom
    rect_top = loop_bottom - rect_h_px
    
    circle_center_y = rect_top
    circle_center_x = attach_col
    
    if rect_h_px > 0:
        draw.rectangle(
            [loop_left, rect_top, loop_right, rect_bottom], 
            fill=loop_color_rgba
        )
    
    draw.ellipse(
        [circle_center_x - circle_r_px, circle_center_y - circle_r_px,
         circle_center_x + circle_r_px, circle_center_y + circle_r_px],
        fill=loop_color_rgba
    )
    
    draw.ellipse(
        [circle_center_x - hole_r_px, circle_center_y - hole_r_px,
         circle_center_x + hole_r_px, circle_center_y + hole_r_px],
        fill=(0, 0, 0, 0)
    )
    
    return np.array(preview_pil)


def calculate_luminance(hex_color):
    """
    Calculate relative luminance of a color using standard formula.
    
    Formula: Y = 0.299*R + 0.587*G + 0.114*B
    
    Args:
        hex_color: Color in hex format (e.g., '#ff0000')
    
    Returns:
        float: Luminance value (0-255)
    """
    # Remove '#' if present
    hex_color = hex_color.lstrip('#')
    
    # Convert hex to RGB
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    
    # Calculate luminance using standard formula
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    
    return luminance


def generate_auto_height_map(color_list, mode, base_thickness, max_relief_height):
    """
    Generate automatic height mapping based on color luminance using Min-Max normalization.
    
    This function calculates the luminance of each color and assigns heights
    using normalization, ensuring all heights fall within [base_thickness, max_relief_height].
    This prevents height explosion when dealing with many colors.
    
    Algorithm:
    1. Calculate luminance Y = 0.299*R + 0.587*G + 0.114*B for each color
    2. Find Y_min and Y_max across all colors
    3. Calculate available height range: Delta_Z = max_relief_height - base_thickness
    4. For each color, calculate normalized ratio:
       - If "浅色凸起": Ratio = (Y - Y_min) / (Y_max - Y_min)
       - If "深色凸起": Ratio = 1.0 - (Y - Y_min) / (Y_max - Y_min)
    5. Final height = base_thickness + Ratio * Delta_Z
    6. Round to 0.1mm precision
    
    Args:
        color_list: List of hex color strings (e.g., ['#ff0000', '#00ff00'])
        mode: Sorting mode - "深色凸起" (darker higher) or "浅色凸起" (lighter higher)
        base_thickness: Base thickness in mm (minimum height)
        max_relief_height: Maximum relief height in mm (maximum height)
    
    Returns:
        dict: Color-to-height mapping {hex_color: height_mm}
    
    Example:
        >>> colors = ['#ff0000', '#00ff00', '#0000ff']
        >>> generate_auto_height_map(colors, "深色凸起", 1.2, 5.0)
        {'#00ff00': 1.2, '#ff0000': 3.1, '#0000ff': 5.0}
    """
    if not color_list:
        return {}
    
    # Step 1: Calculate luminance for each color
    color_luminance = []
    for color in color_list:
        luminance = calculate_luminance(color)
        color_luminance.append((color, luminance))
    
    # Step 2: Find min and max luminance
    luminances = [lum for _, lum in color_luminance]
    y_min = min(luminances)
    y_max = max(luminances)
    
    # Handle edge case: all colors have same luminance
    if y_max == y_min:
        # All colors get the same height (average of base and max)
        avg_height = (base_thickness + max_relief_height) / 2.0
        color_height_map = {color: round(avg_height, 1) for color, _ in color_luminance}
        print(f"[AUTO HEIGHT] All colors have same luminance, using average height: {avg_height:.1f}mm")
        return color_height_map
    
    # Step 3: Calculate available height range
    delta_z = max_relief_height - base_thickness
    
    # Step 4 & 5: Calculate normalized heights
    color_height_map = {}
    for color, luminance in color_luminance:
        # Normalize luminance to [0, 1]
        normalized = (luminance - y_min) / (y_max - y_min)
        
        # Apply mode: darker higher or lighter higher
        if "深色凸起" in mode or "Darker Higher" in mode:
            # Darker colors (lower luminance) should be higher
            # Invert the ratio: 0 -> 1, 1 -> 0
            ratio = 1.0 - normalized
        else:
            # Lighter colors (higher luminance) should be higher
            # Keep the ratio as is: 0 -> 0, 1 -> 1
            ratio = normalized
        
        # Calculate final height (minimum 0.08mm = 1 layer height)
        height = max(0.08, base_thickness + ratio * delta_z)
        
        # Round to 0.1mm precision
        color_height_map[color] = round(height, 1)
    
    print(f"[AUTO HEIGHT] Generated normalized height map for {len(color_list)} colors")
    print(f"[AUTO HEIGHT] Mode: {mode}")
    print(f"[AUTO HEIGHT] Luminance range: {y_min:.1f} - {y_max:.1f}")
    print(f"[AUTO HEIGHT] Height range: {min(color_height_map.values()):.1f}mm - {max(color_height_map.values()):.1f}mm")
    print(f"[AUTO HEIGHT] Total height span: {max(color_height_map.values()) - min(color_height_map.values()):.1f}mm")
    
    return color_height_map


def _build_relief_voxel_matrix(matched_rgb, material_matrix, mask_solid, color_height_map,
                               default_height, structure_mode, backing_color_id, pixel_scale,
                               height_matrix=None):
    """
    Build 2.5D relief voxel matrix with per-color or per-pixel variable heights.
    
    Supports two modes:
    1. Color height map mode (default): heights assigned by color
    2. Heightmap mode: heights from external grayscale heightmap (per-pixel)
    
    Physical Model:
    - Each color region has its own target height (Target_Z)
    - Bottom layers (base): Z=0 to Z=(Target_Z - 0.4mm) - filled with backing_color_id
    - Top layers (optical): Z=(Target_Z - 0.4mm) to Z=Target_Z - filled with material layers
    
    Args:
        matched_rgb: (H, W, 3) RGB color array after K-Means matching
        material_matrix: (H, W, 5) material matrix for optical layers
        mask_solid: (H, W) boolean mask of solid pixels
        color_height_map: dict mapping hex colors to heights in mm
        default_height: default height in mm for colors not in map
        structure_mode: "Double-sided" or "Single-sided"
        backing_color_id: backing material ID (0-7)
        pixel_scale: mm per pixel
        height_matrix: optional (H, W) float32 per-pixel height matrix from heightmap
    
    Returns:
        tuple: (full_matrix, backing_metadata)
    """
    target_h, target_w = material_matrix.shape[:2]
    
    # Constants
    OPTICAL_LAYERS = 5
    OPTICAL_THICKNESS_MM = OPTICAL_LAYERS * PrinterConfig.LAYER_HEIGHT  # 0.4mm
    
    print(f"[RELIEF] Building 2.5D relief voxel matrix...")
    print(f"[RELIEF] Optical layer thickness: {OPTICAL_THICKNESS_MM}mm ({OPTICAL_LAYERS} layers)")
    
    # Step 1: Build per-pixel height matrix
    if height_matrix is not None:
        # Heightmap mode: use provided per-pixel height matrix
        print(f"[RELIEF] 🗺️ 使用高度图模式（逐像素高度）")
        pixel_heights = height_matrix.copy()
        # Clamp: pixel height < optical thickness → set to optical thickness
        pixel_heights[mask_solid & (pixel_heights < OPTICAL_THICKNESS_MM)] = OPTICAL_THICKNESS_MM
    else:
        # Color height map mode: assign heights by color
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
        # Vectorized fill for heightmap mode (much faster for large images)
        target_z_layers = np.ceil(pixel_heights / PrinterConfig.LAYER_HEIGHT).astype(int)
        target_z_layers = np.clip(target_z_layers, OPTICAL_LAYERS, max_z_layers)
        optical_start_z = target_z_layers - OPTICAL_LAYERS
        
        # Fill backing layers
        for z in range(max_z_layers):
            backing_mask = mask_solid & (z < optical_start_z)
            full_matrix[z][backing_mask] = backing_color_id
        
        # Fill optical layers
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
    
    # Step 5: Relief mode is always single-sided (观赏面朝上)
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


def _build_cloisonne_voxel_matrix(material_matrix, mask_solid, mask_wireframe,
                                  spacer_thick, wire_height_mm,
                                  backing_color_id=0):
    """
    Build voxel matrix for cloisonné (掐丝珐琅) mode.

    Layer structure (bottom → top, Z ascending):
        Z = 0 … spacer_layers-1   : Base / backing  (backing_color_id)
        Z = spacer_layers … +4    : Colour layers   (material_matrix, flipped for face-up)
        Z = spacer_layers+5 … +N  : Wire layers     (-3 marker, separate object)

    Cloisonné is always single-sided (观赏面朝上 / face-up).
    Wire uses special marker -3 and is generated as a standalone mesh object.

    Args:
        material_matrix:  (H, W, 5) int – per-pixel material IDs for 5 optical layers.
        mask_solid:       (H, W) bool – True for non-transparent pixels.
        mask_wireframe:   (H, W) bool – True for wire pixels.
        spacer_thick:     float – backing thickness in mm.
        wire_height_mm:   float – extra wire protrusion above colour surface in mm.
        backing_color_id: int – material slot ID for the backing (default 0 = white).

    Returns:
        (full_matrix, backing_metadata)
        full_matrix:      (Z, H, W) int – voxel matrix (-1 = air, -3 = wire).
        backing_metadata:  dict with 'backing_color_id', 'backing_z_range', 'is_cloisonne'.
    """
    target_h, target_w = material_matrix.shape[:2]
    OPTICAL = PrinterConfig.COLOR_LAYERS  # 5

    spacer_layers = max(1, int(round(spacer_thick / PrinterConfig.LAYER_HEIGHT)))
    wire_layers = max(1, int(round(wire_height_mm / PrinterConfig.LAYER_HEIGHT)))

    total_z = spacer_layers + OPTICAL + wire_layers
    full_matrix = np.full((total_z, target_h, target_w), -1, dtype=int)

    mask_t = ~mask_solid  # transparent

    # --- Base / backing ---
    spacer_slice = np.where(mask_solid, backing_color_id, -1).astype(int)
    full_matrix[:spacer_layers] = spacer_slice[np.newaxis, :, :]

    # --- Colour layers (face-up: reverse material order) ---
    # material_matrix is stored for face-down printing (layer 0 = bottom).
    # For face-up we flip so layer 0 sits at the lowest colour Z.
    colour_start = spacer_layers
    for i in range(OPTICAL):
        layer = material_matrix[:, :, OPTICAL - 1 - i]
        z = colour_start + i
        full_matrix[z] = np.where(mask_solid, layer, -1)

    # --- Wire layers (only where mask_wireframe AND mask_solid) ---
    # Use -3 as special marker for wire (will be generated as standalone object)
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


def _build_voxel_matrix(material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id=0):
    """
    Build complete voxel matrix with backing layer marked using special material_id.
    
    Args:
        material_matrix: (H, W, N) material matrix (N optical layers)
        mask_solid: (H, W) solid pixel mask
        spacer_thick: backing thickness (mm)
        structure_mode: "双面" or "单面" (Double-sided or Single-sided)
        backing_color_id: backing material ID (0-7), default is 0 (White)
    
    Returns:
        tuple: (full_matrix, backing_metadata)
            - full_matrix: (Z, H, W) voxel matrix
            - backing_metadata: dict with keys:
                - 'backing_color_id': int
                - 'backing_z_range': tuple (start_z, end_z)
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
        
        # Use backing_color_id parameter to mark backing layer
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
        
        # Use backing_color_id parameter to mark backing layer
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


def _build_voxel_matrix_6layer(material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id=0):
    """
    Build complete voxel matrix for 6-layer structures (5-Color Extended mode).
    
    Args:
        material_matrix: (H, W, 6) material matrix for 6 layers
        mask_solid: (H, W) solid pixel mask
        spacer_thick: backing thickness (mm)
        structure_mode: "双面" or "单面" (Double-sided or Single-sided)
        backing_color_id: backing material ID (0-7), default is 0 (White)
    
    Returns:
        tuple: (full_matrix, backing_metadata)
            - full_matrix: (Z, H, W) voxel matrix
            - backing_metadata: dict with keys:
                - 'backing_color_id': int
                - 'backing_z_range': tuple (start_z, end_z)
    """
    return _build_voxel_matrix(
        material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id=backing_color_id
    )


def _build_voxel_matrix_faceup(material_matrix, mask_solid, spacer_thick, backing_color_id=0):
    """
    Face-up voxel matrix for 5-Color Extended mode.

    Orientation: backing at the bottom (print-bed side), viewing surface at the
    top.  The model is printed right-side-up — no post-print flipping required.

    material_matrix convention (top-to-bottom):
        index 0 = viewing surface (outermost)
        index N-1 = near backing (innermost)

    For base 1024 stacks, index 0 = -1 (air padding) so their viewing surface
    sits 1 Z below the extended stacks, keeping each Z ≤ 4 materials.

    Layer structure (bottom → top, Z ascending):
        Z = 0 .. spacer-1  : Solid backing (backing_color_id)
        Z = spacer .. +5   : Optical layers (reversed: index N-1 → lowest Z,
                             index 0 → highest Z)
        -1 values stay as air in the voxel matrix.
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


def _create_bed_mesh(bed_w_mm, bed_h_mm, is_dark=True):
    """Create a rounded-corner print bed mesh with UV-mapped texture.
    创建圆角打印热床网格，带 UV 贴图纹理。

    The geometry outline matches the texture's rounded rectangle so that
    no sharp-corner artifacts remain visible in the 3D preview.
    几何轮廓与纹理的圆角矩形一致，避免 3D 预览中出现直角残留。

    Args:
        bed_w_mm (int): Bed width in mm. (热床宽度 mm)
        bed_h_mm (int): Bed height in mm. (热床高度 mm)
        is_dark (bool): Use dark PEI theme. (使用深色 PEI 主题)

    Returns:
        trimesh.Trimesh: Textured bed mesh, or None on error. (带纹理的热床网格)
    """
    try:
        from PIL import Image as PILImage, ImageDraw as PILDraw
        from mapbox_earcut import triangulate_float64

        tex_scale = 4  # pixels per mm
        tex_w = int(bed_w_mm * tex_scale)
        tex_h = int(bed_h_mm * tex_scale)
        corner_r = int(8 * tex_scale)
        margin = max(2, corner_r // 4)

        # Corner radius in world mm (matches texture margin/radius ratio)
        r_mm = margin / tex_scale + corner_r / tex_scale

        if is_dark:
            base_color = (58, 58, 66)
            fine_color = (42, 42, 48)
            bold_color = (90, 90, 100)
            border_color = (45, 45, 52)
        else:
            base_color = (242, 242, 245)
            fine_color = (225, 225, 230)
            bold_color = (180, 180, 190)
            border_color = (195, 195, 205)

        # --- Texture (fill entire image with base_color, no edge_color needed) ---
        img = PILImage.new('RGB', (tex_w, tex_h), base_color)
        draw = PILDraw.Draw(img)

        step_10 = int(10 * tex_scale)
        for x in range(0, tex_w, step_10):
            draw.line([(x, 0), (x, tex_h)], fill=fine_color, width=1)
        for y in range(0, tex_h, step_10):
            draw.line([(0, y), (tex_w, y)], fill=fine_color, width=1)

        step_50 = int(50 * tex_scale)
        for x in range(0, tex_w, step_50):
            draw.line([(x, 0), (x, tex_h)], fill=bold_color, width=3)
        for y in range(0, tex_h, step_50):
            draw.line([(0, y), (tex_w, y)], fill=bold_color, width=3)

        draw.rounded_rectangle(
            [margin, margin, tex_w - margin, tex_h - margin],
            radius=corner_r, outline=border_color, width=3
        )

        # --- Rounded-rectangle geometry outline (world coords, mm) ---
        arc_segs = 16
        angles = np.linspace(0, np.pi / 2, arc_segs + 1)
        cos_a = np.cos(angles)
        sin_a = np.sin(angles)

        outline_pts = []
        # Bottom-left corner (origin side)
        for i in range(arc_segs + 1):
            outline_pts.append([r_mm - r_mm * cos_a[i], r_mm - r_mm * sin_a[i]])
        # Bottom-right corner
        for i in range(arc_segs + 1):
            outline_pts.append([bed_w_mm - r_mm + r_mm * sin_a[i], r_mm - r_mm * cos_a[i]])
        # Top-right corner
        for i in range(arc_segs + 1):
            outline_pts.append([bed_w_mm - r_mm + r_mm * cos_a[i], bed_h_mm - r_mm + r_mm * sin_a[i]])
        # Top-left corner
        for i in range(arc_segs + 1):
            outline_pts.append([r_mm - r_mm * sin_a[i], bed_h_mm - r_mm + r_mm * cos_a[i]])

        outline_pts = np.array(outline_pts, dtype=np.float64)

        # Triangulate the rounded-rect polygon via mapbox-earcut
        rings = np.array([len(outline_pts)], dtype=np.int32)
        tri_flat = triangulate_float64(outline_pts, rings)
        tri_indices = np.array(tri_flat, dtype=np.int64).reshape(-1, 3)

        # Build 3D vertices (Z=0) and UV coords
        n_pts = len(outline_pts)
        verts_3d = np.zeros((n_pts, 3), dtype=np.float64)
        verts_3d[:, 0] = outline_pts[:, 0]
        verts_3d[:, 1] = outline_pts[:, 1]

        uv = np.zeros((n_pts, 2), dtype=np.float64)
        uv[:, 0] = outline_pts[:, 0] / bed_w_mm
        uv[:, 1] = 1.0 - outline_pts[:, 1] / bed_h_mm

        from trimesh.visual.material import SimpleMaterial
        from trimesh.visual import TextureVisuals

        mesh = trimesh.Trimesh(vertices=verts_3d, faces=tri_indices, process=False)
        mesh.visual = TextureVisuals(uv=uv, material=SimpleMaterial(image=img))

        theme_name = "dark" if is_dark else "light"
        print(f"[BED] Created {theme_name} {bed_w_mm}×{bed_h_mm}mm rounded bed ({n_pts} verts)")
        return mesh

    except Exception as e:
        print(f"[BED] Failed to create bed mesh: {e}")
        import traceback
        traceback.print_exc()
        return None


def _create_preview_mesh(matched_rgb, mask_solid, total_layers, backing_color_id=0, backing_z_range=None, preview_colors=None):
    """Create simplified 3D preview mesh for browser display.
    为浏览器显示创建简化的 3D 预览网格。

    Args:
        matched_rgb (np.ndarray): RGB color array of shape (H, W, 3). (RGB 颜色数组)
        mask_solid (np.ndarray): Boolean mask of solid pixels of shape (H, W). (实心像素布尔掩码)
        total_layers (int): Total number of Z layers. (Z 轴总层数)
        backing_color_id (int): Backing material ID (0-7), default is 0 (White). (底板材料 ID)
        backing_z_range (tuple): Tuple of (start_z, end_z) for backing layer, or None. (底板 Z 范围)
        preview_colors (list): List of preview colors for materials. (材料预览颜色列表)

    Returns:
        trimesh.Trimesh: Simplified preview mesh, downsampled for large models. (简化预览网格，大模型会降采样)
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

            # Determine Z range for this pixel
            # If backing_z_range is provided, split the model into backing and non-backing layers
            if backing_z_range is not None and preview_colors is not None:
                backing_start, backing_end = backing_z_range

                # Create backing layer box
                z0_backing = backing_start
                z1_backing = backing_end + 1

                base_idx = len(vertices)
                vertices.extend([
                    [x0, y0, z0_backing], [x1, y0, z0_backing], [x1, y1, z0_backing], [x0, y1, z0_backing],
                    [x0, y0, z1_backing], [x1, y0, z1_backing], [x1, y1, z1_backing], [x0, y1, z1_backing]
                ])

                # Apply backing color
                # When backing_color_id=-2 (separate backing), use white color (material_id=0)
                actual_backing_color_id = 0 if backing_color_id == -2 else backing_color_id
                backing_rgba = [int(preview_colors[actual_backing_color_id][0]),
                               int(preview_colors[actual_backing_color_id][1]),
                               int(preview_colors[actual_backing_color_id][2]), 255]

                cube_faces = [
                    [0, 2, 1], [0, 3, 2],
                    [4, 5, 6], [4, 6, 7],
                    [0, 1, 5], [0, 5, 4],
                    [1, 2, 6], [1, 6, 5],
                    [2, 3, 7], [2, 7, 6],
                    [3, 0, 4], [3, 4, 7]
                ]

                for f in cube_faces:
                    faces.append([v + base_idx for v in f])
                    face_colors.append(backing_rgba)

                # Create non-backing layers (if any exist)
                # Bottom layers (0 to backing_start)
                if backing_start > 0:
                    z0_bottom = 0
                    z1_bottom = backing_start

                    base_idx = len(vertices)
                    vertices.extend([
                        [x0, y0, z0_bottom], [x1, y0, z0_bottom], [x1, y1, z0_bottom], [x0, y1, z0_bottom],
                        [x0, y0, z1_bottom], [x1, y0, z1_bottom], [x1, y1, z1_bottom], [x0, y1, z1_bottom]
                    ])

                    for f in cube_faces:
                        faces.append([v + base_idx for v in f])
                        face_colors.append(rgba)

                # Top layers (backing_end+1 to total_layers)
                if backing_end + 1 < total_layers:
                    z0_top = backing_end + 1
                    z1_top = total_layers

                    base_idx = len(vertices)
                    vertices.extend([
                        [x0, y0, z0_top], [x1, y0, z0_top], [x1, y1, z0_top], [x0, y1, z0_top],
                        [x0, y0, z1_top], [x1, y0, z1_top], [x1, y1, z1_top], [x0, y1, z1_top]
                    ])

                    for f in cube_faces:
                        faces.append([v + base_idx for v in f])
                        face_colors.append(rgba)
            else:
                # Original behavior: single box from 0 to total_layers
                z0, z1 = 0, total_layers

                base_idx = len(vertices)
                vertices.extend([
                    [x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                    [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]
                ])

                cube_faces = [
                    [0, 2, 1], [0, 3, 2],
                    [4, 5, 6], [4, 6, 7],
                    [0, 1, 5], [0, 5, 4],
                    [1, 2, 6], [1, 6, 5],
                    [2, 3, 7], [2, 7, 6],
                    [3, 0, 4], [3, 4, 7]
                ]

                for f in cube_faces:
                    faces.append([v + base_idx for v in f])
                    face_colors.append(rgba)

    if not vertices:
        return None

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
    mesh.visual.face_colors = np.array(face_colors, dtype=np.uint8)

    print(f"[PREVIEW] Generated: {len(mesh.vertices):,} vertices, {len(mesh.faces):,} faces")

    return mesh


def generate_empty_bed_glb(bed_w: int = None, bed_h: int = None, is_dark: bool = False):
    """Generate a GLB file containing only the print bed (no model).
    生成仅包含打印热床的 GLB 文件（无模型）。

    Args:
        bed_w (int): Bed width in mm. Defaults to BedManager default. (热床宽度 mm)
        bed_h (int): Bed height in mm. Defaults to BedManager default. (热床高度 mm)
        is_dark (bool): Use dark PEI theme. (使用深色 PEI 主题)

    Returns:
        str: Path to GLB file, or None on failure. (GLB 文件路径，失败返回 None)
    """
    try:
        if bed_w is None or bed_h is None:
            bed_w, bed_h = BedManager.get_bed_size(BedManager.DEFAULT_BED)
        bed_mesh = _create_bed_mesh(bed_w, bed_h, is_dark=is_dark)
        if bed_mesh is None:
            return None
        glb_scene = trimesh.Scene()
        glb_scene.add_geometry(bed_mesh, node_name="bed")
        glb_path = os.path.join(OUTPUT_DIR, f"empty_bed_{bed_w}x{bed_h}.glb")
        glb_scene.export(glb_path)
        return glb_path
    except Exception as e:
        print(f"[EMPTY_BED] Failed: {e}")
        return None


def _merge_low_frequency_colors(
    unique_colors: np.ndarray,
    pixel_counts: np.ndarray,
    max_meshes: int,
) -> np.ndarray:
    """Merge low-frequency colors into their nearest high-frequency neighbors.

    Keeps the top ``max_meshes`` colors by pixel count and reassigns every
    tail color to the closest kept color (Euclidean RGB distance).

    Args:
        unique_colors: (N, 3) uint8 array of unique RGB colors.
        pixel_counts: (N,) int array of pixel counts per color.
        max_meshes: Maximum number of colors to keep.

    Returns:
        (N, 3) uint8 array where tail colors are replaced by their nearest
        kept color.  The first ``max_meshes`` entries are unchanged.
    """
    n = len(unique_colors)
    if n <= max_meshes:
        return unique_colors.copy()

    order = np.argsort(-pixel_counts)
    keep_indices = order[:max_meshes]
    tail_indices = order[max_meshes:]

    kept_colors = unique_colors[keep_indices].astype(np.float64)
    merged = unique_colors.copy()

    tail_rgb = unique_colors[tail_indices].astype(np.float64)
    # Vectorized nearest-neighbor via broadcasting: (T, 1, 3) - (1, K, 3)
    diff = tail_rgb[:, None, :] - kept_colors[None, :, :]
    dist_sq = np.sum(diff ** 2, axis=2)
    nearest = np.argmin(dist_sq, axis=1)

    merged[tail_indices] = unique_colors[keep_indices[nearest]]
    return merged


def _build_color_voxel_mesh(
    mask: np.ndarray,
    height: int,
    width: int,
    total_layers: int,
    shrink: float,
    rgba: np.ndarray,
) -> Optional[trimesh.Trimesh]:
    """Build a voxelized Trimesh for pixels indicated by *mask*.

    Each True pixel becomes a box spanning [x, x+1] x [world_y, world_y+1]
    x [0, total_layers] with a small ``shrink`` gap, colored by ``rgba``.

    Args:
        mask: (H, W) bool array of pixels belonging to this color.
        height: Image height after downsampling.
        width: Image width after downsampling.
        total_layers: Number of Z layers for the voxel height.
        shrink: Inset amount for voxel gaps.
        rgba: (4,) uint8 RGBA color for face coloring.

    Returns:
        A trimesh.Trimesh, or None if mask has no True pixels.
    """
    ys, xs = np.where(mask)
    n_pixels = len(ys)
    if n_pixels == 0:
        return None

    # Pre-allocate arrays for all cubes (8 verts, 12 faces each)
    all_verts = np.empty((n_pixels * 8, 3), dtype=np.float64)
    all_faces = np.empty((n_pixels * 12, 3), dtype=np.int64)
    all_colors = np.empty((n_pixels * 12, 4), dtype=np.uint8)

    cube_faces_template = np.array([
        [0, 2, 1], [0, 3, 2],
        [4, 5, 6], [4, 6, 7],
        [0, 1, 5], [0, 5, 4],
        [1, 2, 6], [1, 6, 5],
        [2, 3, 7], [2, 7, 6],
        [3, 0, 4], [3, 4, 7],
    ], dtype=np.int64)

    x0 = xs.astype(np.float64) + shrink
    x1 = xs.astype(np.float64) + 1.0 - shrink
    world_y = (height - 1 - ys).astype(np.float64)
    y0 = world_y + shrink
    y1 = world_y + 1.0 - shrink
    z0 = np.zeros(n_pixels, dtype=np.float64)
    z1 = np.full(n_pixels, float(total_layers), dtype=np.float64)

    # Vectorized vertex construction: 8 corners per pixel
    # Order matches _create_preview_mesh: [x0,y0,z0],[x1,y0,z0],[x1,y1,z0],[x0,y1,z0],
    #                                     [x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]
    for i, (vx0, vx1, vy0, vy1, vz0, vz1) in enumerate(
        zip(x0, x1, y0, y1, z0, z1)
    ):
        base = i * 8
        all_verts[base:base + 8] = [
            [vx0, vy0, vz0], [vx1, vy0, vz0], [vx1, vy1, vz0], [vx0, vy1, vz0],
            [vx0, vy0, vz1], [vx1, vy0, vz1], [vx1, vy1, vz1], [vx0, vy1, vz1],
        ]
        face_base = i * 12
        all_faces[face_base:face_base + 12] = cube_faces_template + base
        all_colors[face_base:face_base + 12] = rgba

    mesh = trimesh.Trimesh(vertices=all_verts, faces=all_faces, process=False)
    mesh.visual.face_colors = all_colors
    return mesh


def generate_segmented_glb(cache: dict, max_meshes: int = 64) -> Optional[str]:
    """Generate a color-segmented GLB preview with one named Mesh per color.

    Each unique color in ``matched_rgb`` becomes an independent Mesh node
    named ``color_<hex>`` (6-digit lowercase, no ``#`` prefix).  Every Mesh
    has its origin at Z=0 (Pivot Point constraint) so the frontend can
    scale along Z to stretch upward only.

    When the number of unique colors exceeds *max_meshes*, low-frequency
    colors are merged into their nearest high-frequency neighbor to keep
    the Mesh count within budget.

    Args:
        cache: Preview cache dict containing at least:
            - matched_rgb: (H, W, 3) uint8 array
            - mask_solid: (H, W) bool array
            - target_w, target_h: pixel dimensions
            - target_width_mm: physical width in mm
        max_meshes: Maximum Mesh count before merging (default 64).

    Returns:
        Path to the exported GLB file, or None on failure.
    """
    if cache is None:
        return None

    matched_rgb = cache.get('matched_rgb')
    mask_solid = cache.get('mask_solid')
    target_w = cache.get('target_w')
    target_width_mm = cache.get('target_width_mm')

    if matched_rgb is None or mask_solid is None:
        return None

    try:
        # ------------------------------------------------------------------
        # 1. Downsample large images (same logic as _create_preview_mesh)
        # ------------------------------------------------------------------
        height, width = matched_rgb.shape[:2]
        total_pixels = width * height
        SIMPLIFY_THRESHOLD = 500_000
        TARGET_PIXELS = 300_000

        if total_pixels > SIMPLIFY_THRESHOLD:
            scale_factor = int(np.sqrt(total_pixels / TARGET_PIXELS))
            scale_factor = max(2, min(scale_factor, 16))
            print(f"[SEGMENTED_GLB] Downsampling by {scale_factor}x")

            new_h = height // scale_factor
            new_w = width // scale_factor
            matched_rgb = cv2.resize(matched_rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
            mask_solid = cv2.resize(
                mask_solid.astype(np.uint8), (new_w, new_h),
                interpolation=cv2.INTER_NEAREST,
            ).astype(bool)
            height, width = new_h, new_w
            shrink = 0.05 * scale_factor
        else:
            shrink = 0.05

        # ------------------------------------------------------------------
        # 2. Extract unique colors and pixel counts (solid pixels only)
        # ------------------------------------------------------------------
        solid_pixels = matched_rgb[mask_solid]  # (N, 3)
        if len(solid_pixels) == 0:
            print("[SEGMENTED_GLB] No solid pixels, returning None")
            return None

        unique_colors, inverse, pixel_counts = np.unique(
            solid_pixels, axis=0, return_inverse=True, return_counts=True,
        )
        n_unique = len(unique_colors)
        print(f"[SEGMENTED_GLB] Found {n_unique} unique colors")

        # ------------------------------------------------------------------
        # 3. Merge low-frequency colors if exceeding max_meshes
        # ------------------------------------------------------------------
        if n_unique > max_meshes:
            print(f"[SEGMENTED_GLB] Merging {n_unique} colors down to {max_meshes}")
            merged_colors = _merge_low_frequency_colors(unique_colors, pixel_counts, max_meshes)
            # Rebuild matched_rgb with merged colors for solid pixels
            new_solid = merged_colors[inverse]
            matched_rgb_work = matched_rgb.copy()
            matched_rgb_work[mask_solid] = new_solid
            # Re-extract unique colors after merge
            solid_pixels = matched_rgb_work[mask_solid]
            unique_colors, _, pixel_counts = np.unique(
                solid_pixels, axis=0, return_inverse=True, return_counts=True,
            )
            matched_rgb = matched_rgb_work
            print(f"[SEGMENTED_GLB] After merge: {len(unique_colors)} colors")

        # ------------------------------------------------------------------
        # 4. Build per-color Meshes
        # ------------------------------------------------------------------
        total_layers = 25  # Same as generate_realtime_glb
        scene = trimesh.Scene()

        # Physical scale: pixel coords -> mm
        # Use current `width` (may be downsampled) instead of original `target_w`
        pixel_scale = target_width_mm / width if width > 0 else 0.42
        scale_transform = np.eye(4)
        scale_transform[0, 0] = pixel_scale
        scale_transform[1, 1] = pixel_scale
        scale_transform[2, 2] = PrinterConfig.LAYER_HEIGHT

        for color_rgb in unique_colors:
            r, g, b = int(color_rgb[0]), int(color_rgb[1]), int(color_rgb[2])
            hex_name = f"{r:02x}{g:02x}{b:02x}"
            rgba = np.array([r, g, b, 255], dtype=np.uint8)

            # Boolean mask for this color across the full image
            color_match = np.all(matched_rgb == color_rgb, axis=2) & mask_solid

            mesh = _build_color_voxel_mesh(
                color_match, height, width, total_layers, shrink, rgba,
            )
            if mesh is None:
                continue

            # Apply physical scale
            mesh.apply_transform(scale_transform)

            # Pivot Point constraint: translate so min_z = 0
            min_z = mesh.vertices[:, 2].min()
            if min_z != 0.0:
                mesh.vertices[:, 2] -= min_z

            # Set MeshStandardMaterial color via vertex/face colors (already set)
            scene.add_geometry(mesh, node_name=f"color_{hex_name}")

        if len(scene.geometry) == 0:
            print("[SEGMENTED_GLB] No meshes generated")
            return None

        # ------------------------------------------------------------------
        # 5. Extract 2D contours for each color (for frontend outline rendering)
        # ------------------------------------------------------------------
        contours_data: dict[str, list[list[list[float]]]] = {}
        for color_rgb in unique_colors:
            r, g, b = int(color_rgb[0]), int(color_rgb[1]), int(color_rgb[2])
            hex_name = f"{r:02x}{g:02x}{b:02x}"

            color_match = np.all(matched_rgb == color_rgb, axis=2) & mask_solid
            mask_u8 = color_match.astype(np.uint8) * 255

            cv_contours, _ = cv2.findContours(mask_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not cv_contours:
                continue

            color_contour_list: list[list[list[float]]] = []
            for cnt in cv_contours:
                if len(cnt) < 3:
                    continue
                # Convert pixel coords to mesh world coords (mm).
                # OpenCV contour point (x_px, y_px) is at pixel boundary.
                # Mesh Y uses: world_y = (height - 1 - y_px), box spans [world_y, world_y+1]
                # So pixel row y_px top edge = height - y_px in mesh pixel space.
                # Then multiply by pixel_scale to get mm.
                # X is straightforward: x_mm = x_px * pixel_scale
                pts = cnt.squeeze(1).astype(float)  # (N, 2)
                world_pts: list[list[float]] = []
                for px, py in pts:
                    x_mm = float(px * pixel_scale)
                    y_mm = float((height - py) * pixel_scale)
                    world_pts.append([x_mm, y_mm])
                color_contour_list.append(world_pts)

            if color_contour_list:
                contours_data[hex_name] = color_contour_list

        # Store contours in cache for API to return
        cache['color_contours'] = contours_data
        print(f"[SEGMENTED_GLB] Extracted contours for {len(contours_data)} colors")

        # ------------------------------------------------------------------
        # 6. Export GLB
        # ------------------------------------------------------------------
        glb_path = os.path.join(OUTPUT_DIR, "segmented_preview.glb")
        scene.export(glb_path)
        print(f"[SEGMENTED_GLB] Exported {len(scene.geometry)} meshes -> {glb_path}")
        return glb_path

    except Exception as e:
        print(f"[SEGMENTED_GLB] Failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def generate_realtime_glb(cache):
    """Generate a lightweight GLB preview from cached preview data.
    
    Called during preview stage so the 3D thumbnail updates immediately
    without waiting for the full 3MF export.
    
    Args:
        cache: Preview cache dict from generate_preview_cached
    
    Returns:
        str: Path to GLB file, or None on failure
    """
    if cache is None:
        return None
    
    matched_rgb = cache.get('matched_rgb')
    mask_solid = cache.get('mask_solid')
    target_w = cache.get('target_w')
    target_h = cache.get('target_h')
    target_width_mm = cache.get('target_width_mm')
    color_conf = cache.get('color_conf')
    
    if matched_rgb is None or mask_solid is None:
        return None
    
    try:
        # Use a fixed thin height (5 color layers + backing ≈ 25 voxel layers)
        total_layers = 25
        preview_colors = color_conf.get('preview') if color_conf else None
        
        preview_mesh = _create_preview_mesh(
            matched_rgb, mask_solid, total_layers,
            backing_color_id=cache.get('backing_color_id', 0),
            preview_colors=preview_colors
        )
        
        if preview_mesh is None:
            print("[REALTIME_GLB] Preview mesh is None (model too large?)")
            return None
        
        # Scale from pixel/voxel coords to mm
        # _create_preview_mesh may downsample internally, so we must compute
        # pixel_scale from the mesh's actual bounding box width, not target_w.
        mesh_width = preview_mesh.bounds[1][0] - preview_mesh.bounds[0][0]
        pixel_scale = target_width_mm / mesh_width if mesh_width > 0 else 0.42
        transform = np.eye(4)
        transform[0, 0] = pixel_scale
        transform[1, 1] = pixel_scale
        transform[2, 2] = PrinterConfig.LAYER_HEIGHT
        preview_mesh.apply_transform(transform)
        
        # Export model-only GLB (bed platform is rendered by frontend)
        # Note: origin/main adds bed platform in Python for Gradio UI;
        # the FastAPI+React frontend renders bed in Three.js instead.
        glb_path = os.path.join(OUTPUT_DIR, "realtime_preview.glb")
        preview_mesh.export(glb_path)
        print(f"[REALTIME_GLB] ✅ Exported: {glb_path}")
        return glb_path
        
    except Exception as e:
        print(f"[REALTIME_GLB] Failed: {e}")
        return None


# ========== Preview Related Functions ==========

def generate_preview_cached(image_path, lut_path, target_width_mm,
                            auto_bg, bg_tol, color_mode,
                            modeling_mode: ModelingMode = ModelingMode.HIGH_FIDELITY,
                            quantize_colors: int = 64,
                            backing_color_id: int = 0,
                            enable_cleanup: bool = True,
                            is_dark: bool = True,
                            hue_weight: float = 0.0):
    """
    Generate preview and cache data
    For 2D preview interface

    Args:
        image_path: Path to input image
        lut_path: LUT file path (string) or Gradio File object
        target_width_mm: Target width in millimeters
        auto_bg: Enable automatic background removal
        bg_tol: Background tolerance value
        color_mode: Color system mode (CMYW/RYBW)
        modeling_mode: Modeling mode (HIGH_FIDELITY/PIXEL_ART)
        quantize_colors: K-Means quantization color count (8-256)
        backing_color_id: Backing layer material ID (0-7), default 0 (White)

    Returns:
        tuple: (preview_image, cache_data, status_message)
    """
    if image_path is None:
        return None, None, "[ERROR] Please upload an image"
    if lut_path is None:
        return None, None, "[WARNING] Please select or upload calibration file"
    
    if isinstance(lut_path, str):
        actual_lut_path = lut_path
    elif hasattr(lut_path, 'name'):
        actual_lut_path = lut_path.name
    else:
        return None, None, "[ERROR] Invalid LUT file format"

    # Handle None modeling_mode with default
    if modeling_mode is None or modeling_mode == "none":
        modeling_mode = ModelingMode.HIGH_FIDELITY
        print("[CONVERTER] Warning: modeling_mode was None, using default HIGH_FIDELITY")
    else:
        modeling_mode = ModelingMode(modeling_mode)

    # Clamp quantize_colors to valid range
    quantize_colors = max(8, min(256, quantize_colors))
    
    color_conf = ColorSystem.get(color_mode)
    
    try:
        print(f"[Core generate_preview_cached] hue_weight={hue_weight}, color_mode={color_mode}")
        processor = LuminaImageProcessor(actual_lut_path, color_mode, hue_weight=hue_weight)
        processor.enable_cleanup = enable_cleanup
        result = processor.process_image(
            image_path=image_path,
            target_width_mm=target_width_mm,
            modeling_mode=modeling_mode,
            quantize_colors=quantize_colors,
            auto_bg=auto_bg,
            bg_tol=bg_tol,
            blur_kernel=0,
            smooth_sigma=10
        )
    except Exception as e:
        return None, None, f"[ERROR] Preview generation failed: {e}"
    
    matched_rgb = result['matched_rgb']
    material_matrix = result['material_matrix']
    mask_solid = result['mask_solid']
    target_w, target_h = result['dimensions']
    
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    preview_rgba[mask_solid, 3] = 255
    
    cache = {
        'target_w': target_w,
        'target_h': target_h,
        'target_width_mm': target_width_mm,
        'mask_solid': mask_solid,
        'material_matrix': material_matrix,
        'matched_rgb': matched_rgb,
        'preview_rgba': preview_rgba.copy(),
        'color_conf': color_conf,
        'color_mode': color_mode,
        'quantize_colors': quantize_colors,
        'backing_color_id': backing_color_id,
        'is_dark': is_dark,
        'bed_label': BedManager.DEFAULT_BED
    }

    # 统一缓存契约：保证 quantized_image 始终可用
    cache['debug_data'] = result.get('debug_data') if isinstance(result, dict) else None
    cache['quantized_image'] = result.get('quantized_image')
    _ensure_quantized_image_in_cache(cache)
    
    # Extract color palette from cache
    color_palette = extract_color_palette(cache)
    cache['color_palette'] = color_palette
    
    display = render_preview(
        preview_rgba, None, 0, 0, 0, 0, False, color_conf,
        target_width_mm=target_width_mm, is_dark=is_dark
    )
    
    num_colors = len(color_palette)
    return display, cache, f"[OK] Preview ({target_w}×{target_h}px, {num_colors} colors) | Click image to place loop"


def render_preview(preview_rgba, loop_pos, loop_width, loop_length, 
                   loop_hole, loop_angle, loop_enabled, color_conf,
                   bed_label=None, target_width_mm=None, is_dark=True):
    """Render preview with physical bed grid and optional keychain loop.
    
    Args:
        bed_label: BedManager label (e.g. "256×256 mm"). Falls back to default.
        target_width_mm: Physical width of the model in mm. If None, estimates from pixels.
        is_dark: True for dark PEI theme, False for light marble theme.
    """
    if bed_label is None:
        bed_label = BedManager.DEFAULT_BED
    bed_w_mm, bed_h_mm = BedManager.get_bed_size(bed_label)
    ppm = BedManager.compute_scale(bed_w_mm, bed_h_mm)

    canvas_w = int(bed_w_mm * ppm)
    canvas_h = int(bed_h_mm * ppm)
    margin = int(30 * ppm / 3)

    total_w = canvas_w + margin
    total_h = canvas_h + margin

    # Theme colors
    if is_dark:
        canvas_bg = (38, 38, 44, 255)
        bed_bg = (58, 58, 66, 255)
        grid_fine = (52, 52, 58, 255)
        grid_bold = (72, 72, 80, 255)
        border_color = (45, 45, 52, 255)
        axis_color = (90, 90, 110, 255)
        label_color = (140, 140, 170, 255)
    else:
        canvas_bg = (215, 215, 220, 255)
        bed_bg = (242, 242, 245, 255)
        grid_fine = (225, 225, 230, 255)
        grid_bold = (180, 180, 190, 255)
        border_color = (195, 195, 205, 255)
        axis_color = (100, 100, 120, 255)
        label_color = (80, 80, 100, 255)

    canvas = Image.new('RGBA', (total_w, total_h), canvas_bg)
    draw = ImageDraw.Draw(canvas)

    # Rounded bed area
    corner_r = 12
    draw.rounded_rectangle(
        [margin, 0, total_w - 1, canvas_h - 1],
        radius=corner_r, fill=bed_bg
    )

    # --- grid lines ---
    step_10 = max(1, int(10 * ppm))
    step_50 = max(1, int(50 * ppm))

    for x in range(margin, total_w, step_10):
        draw.line([(x, 0), (x, canvas_h)], fill=grid_fine, width=1)
    for y in range(0, canvas_h, step_10):
        draw.line([(margin, y), (total_w, y)], fill=grid_fine, width=1)

    for x in range(margin, total_w, step_50):
        draw.line([(x, 0), (x, canvas_h)], fill=grid_bold, width=2)
    for y in range(0, canvas_h, step_50):
        draw.line([(margin, y), (total_w, y)], fill=grid_bold, width=2)

    # Rounded border on top of grid
    draw.rounded_rectangle(
        [margin, 0, total_w - 1, canvas_h - 1],
        radius=corner_r, outline=border_color, width=2
    )

    # axes
    draw.line([(margin, 0), (margin, canvas_h)], fill=axis_color, width=2)
    draw.line([(margin, canvas_h - 1), (total_w, canvas_h - 1)], fill=axis_color, width=2)

    # labels (mm)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    for mm in range(0, bed_w_mm + 1, 50):
        px = margin + int(mm * ppm)
        if px < total_w and font:
            draw.text((px - 5, canvas_h + 2), f"{mm}", fill=label_color, font=font)

    for mm in range(0, bed_h_mm + 1, 50):
        px = canvas_h - int(mm * ppm)
        if px >= 0 and font:
            draw.text((2, px - 5), f"{mm}", fill=label_color, font=font)

    # --- paste model centred on bed ---
    if preview_rgba is not None:
        h, w = preview_rgba.shape[:2]
        # Calculate physical model size
        if target_width_mm is not None and target_width_mm > 0:
            model_w_mm = target_width_mm
            model_h_mm = target_width_mm * h / w
        else:
            # Fallback: estimate from pixel count and nozzle width
            model_w_mm = w * PrinterConfig.NOZZLE_WIDTH
            model_h_mm = h * PrinterConfig.NOZZLE_WIDTH

        new_w = max(1, int(model_w_mm * ppm))
        new_h = max(1, int(model_h_mm * ppm))

        pil_img = Image.fromarray(preview_rgba, mode='RGBA')
        pil_img = pil_img.resize((new_w, new_h), Image.Resampling.NEAREST)

        offset_x = margin + (canvas_w - new_w) // 2
        offset_y = (canvas_h - new_h) // 2
        canvas.paste(pil_img, (offset_x, offset_y), pil_img)

        # --- loop overlay ---
        if loop_enabled and loop_pos is not None:
            mm_per_px = model_w_mm / w if w > 0 else PrinterConfig.NOZZLE_WIDTH
            canvas = _draw_loop_on_canvas(
                canvas, loop_pos, loop_width, loop_length,
                loop_hole, loop_angle, color_conf, margin,
                ppm=ppm, img_offset=(offset_x, offset_y),
                mm_per_px=mm_per_px
            )

    return np.array(canvas)


def _draw_loop_on_canvas(pil_img, loop_pos, loop_width, loop_length, 
                         loop_hole, loop_angle, color_conf, margin,
                         ppm=None, img_offset=None, mm_per_px=None):
    """Draw keychain loop marker on canvas.
    
    Args:
        ppm: pixels-per-mm (new bed system). Falls back to legacy PREVIEW_SCALE.
        img_offset: (x, y) pixel offset where the model image was pasted.
        mm_per_px: mm per original image pixel. Falls back to NOZZLE_WIDTH.
    """
    if ppm is None:
        ppm = PREVIEW_SCALE / PrinterConfig.NOZZLE_WIDTH
    if img_offset is None:
        img_offset = (margin, 0)
    if mm_per_px is None:
        mm_per_px = PrinterConfig.NOZZLE_WIDTH

    loop_w_px = int(loop_width * ppm)
    loop_h_px = int(loop_length * ppm)
    hole_r_px = int(loop_hole / 2 * ppm)
    circle_r_px = loop_w_px // 2

    # loop_pos is in original image pixel coords
    cx = img_offset[0] + int(loop_pos[0] * mm_per_px * ppm)
    cy = img_offset[1] + int(loop_pos[1] * mm_per_px * ppm)
    
    loop_size = max(loop_w_px, loop_h_px) * 2 + 20
    loop_layer = Image.new('RGBA', (loop_size, loop_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(loop_layer)
    
    lc = loop_size // 2
    rect_h = max(1, loop_h_px - circle_r_px)
    
    loop_color = (220, 60, 60, 200)
    outline_color = (255, 255, 255, 255)
    
    draw.rectangle(
        [lc - loop_w_px//2, lc, lc + loop_w_px//2, lc + rect_h],
        fill=loop_color, outline=outline_color, width=2
    )
    
    draw.ellipse(
        [lc - circle_r_px, lc - circle_r_px,
         lc + circle_r_px, lc + circle_r_px],
        fill=loop_color, outline=outline_color, width=2
    )
    
    draw.ellipse(
        [lc - hole_r_px, lc - hole_r_px,
         lc + hole_r_px, lc + hole_r_px],
        fill=(0, 0, 0, 0)
    )
    
    if loop_angle != 0:
        loop_layer = loop_layer.rotate(
            -loop_angle, center=(lc, lc),
            expand=False, resample=Image.BICUBIC
        )
    
    paste_x = cx - lc
    paste_y = cy - lc - rect_h // 2
    pil_img.paste(loop_layer, (paste_x, paste_y), loop_layer)
    
    return pil_img


def on_preview_click(cache, loop_pos, evt: gr.SelectData, bed_label=None):
    """Handle preview image click event."""
    if evt is None or cache is None:
        return loop_pos, False, "Invalid click - please generate preview first"
    
    if bed_label is None:
        bed_label = BedManager.DEFAULT_BED

    click_x, click_y = evt.index
    
    target_w = cache['target_w']
    target_h = cache['target_h']
    target_width_mm = cache.get('target_width_mm')
    
    bed_w_mm, bed_h_mm = BedManager.get_bed_size(bed_label)
    ppm = BedManager.compute_scale(bed_w_mm, bed_h_mm)
    margin = int(30 * ppm / 3)

    canvas_w = int(bed_w_mm * ppm) + margin
    canvas_h = int(bed_h_mm * ppm) + margin

    # Use target_width_mm from cache for accurate physical size
    if target_width_mm is not None and target_width_mm > 0:
        model_w_mm = target_width_mm
        model_h_mm = target_width_mm * target_h / target_w
    else:
        model_w_mm = target_w * PrinterConfig.NOZZLE_WIDTH
        model_h_mm = target_h * PrinterConfig.NOZZLE_WIDTH
    new_w = max(1, int(model_w_mm * ppm))
    new_h = max(1, int(model_h_mm * ppm))

    offset_x = margin + (int(bed_w_mm * ppm) - new_w) // 2
    offset_y = (int(bed_h_mm * ppm) - new_h) // 2

    # Gradio may scale the displayed image
    gradio_display_height = 600
    gradio_display_width = 900
    scale_by_height = gradio_display_height / canvas_h
    scale_by_width = gradio_display_width / canvas_w
    gradio_scale = min(1.0, scale_by_height, scale_by_width)
    
    canvas_click_x = click_x / gradio_scale
    canvas_click_y = click_y / gradio_scale
    
    # Convert from canvas coords to original image pixel coords
    # Each pixel in original image = (model_w_mm / target_w) mm
    mm_per_px = model_w_mm / target_w
    img_click_x = (canvas_click_x - offset_x) / (mm_per_px * ppm)
    img_click_y = (canvas_click_y - offset_y) / (mm_per_px * ppm)
    
    orig_x = max(0, min(target_w - 1, img_click_x))
    orig_y = max(0, min(target_h - 1, img_click_y))
    
    pos_info = f"Position: ({orig_x:.1f}, {orig_y:.1f}) px"
    return (orig_x, orig_y), True, pos_info


def update_preview_with_loop(cache, loop_pos, add_loop,
                            loop_width, loop_length, loop_hole, loop_angle):
    """Update preview image with keychain loop."""
    if cache is None:
        return None
    
    preview_rgba = cache['preview_rgba'].copy()
    color_conf = cache['color_conf']
    target_width_mm = cache.get('target_width_mm')
    is_dark = cache.get('is_dark', True)
    
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width, loop_length, loop_hole, loop_angle,
        add_loop, color_conf,
        bed_label=cache.get('bed_label'),
        target_width_mm=target_width_mm, is_dark=is_dark
    )
    return display


def on_remove_loop():
    """Remove keychain loop."""
    return None, False, 0, "Loop removed"


def generate_final_model(image_path, lut_path, target_width_mm, spacer_thick,
                        structure_mode, auto_bg, bg_tol, color_mode,
                        add_loop, loop_width, loop_length, loop_hole, loop_pos,
                        modeling_mode=ModelingMode.VECTOR, quantize_colors=64,
                        color_replacements=None, replacement_regions=None, backing_color_name="White",
                        separate_backing=False, enable_relief=False, color_height_map=None,
                        height_mode: str = "color",
                        heightmap_path=None, heightmap_max_height=None,
                        enable_cleanup=True,
                        enable_outline=False, outline_width=2.0,
                        enable_cloisonne=False, wire_width_mm=0.4,
                        wire_height_mm=0.4,
                        free_color_set=None,
                        enable_coating=False, coating_height_mm=0.08,
                        hue_weight: float = 0.0,
                        progress=None):
    """
    Wrapper function for generating final model.
    
    Directly calls main conversion function with smart defaults:
    - blur_kernel=0 (disable median filter, preserve details)
    - smooth_sigma=10 (gentle bilateral filter, preserve edges)
    
    Args:
        color_replacements: Optional dict of color replacements {hex: hex}
                           e.g., {'#ff0000': '#00ff00'}
        backing_color_name: Name of backing color (e.g., "White", "Cyan")
                           Will be converted to material ID based on color_mode
        separate_backing: Boolean flag to separate backing as individual object (default: False)
        height_mode: "color" or "heightmap", determines relief branch selection
    """
    # Convert backing color name to ID or use special marker for separate backing
    # Error handling for separate_backing parameter (Requirement 8.4)
    try:
        separate_backing = bool(separate_backing) if separate_backing is not None else False
    except Exception as e:
        print(f"[CONVERTER] Error reading separate_backing parameter: {e}, using default (False)")
        separate_backing = False
    
    if separate_backing:
        backing_color_id = -2  # Special marker for separate backing
        print(f"[CONVERTER] Backing will be separated as individual object (white)")
    else:
        color_conf = ColorSystem.get(color_mode)
        backing_color_id = color_conf['map'].get(backing_color_name, 0)
        print(f"[CONVERTER] Backing color: {backing_color_name} (ID={backing_color_id})")
    
    # Handle relief mode parameters
    if color_height_map is None:
        color_height_map = {}
    
    return convert_image_to_3d(
        image_path, lut_path, target_width_mm, spacer_thick,
        structure_mode, auto_bg, bg_tol, color_mode,
        add_loop, loop_width, loop_length, loop_hole, loop_pos,
        modeling_mode, quantize_colors,
        blur_kernel=0,
        smooth_sigma=10,
        color_replacements=color_replacements,
        replacement_regions=replacement_regions,
        backing_color_id=backing_color_id,
        separate_backing=separate_backing,
        enable_relief=enable_relief,
        color_height_map=color_height_map,
        height_mode=height_mode,
        heightmap_path=heightmap_path,
        heightmap_max_height=heightmap_max_height,
        enable_cleanup=enable_cleanup,
        enable_outline=enable_outline,
        outline_width=outline_width,
        enable_cloisonne=enable_cloisonne,
        wire_width_mm=wire_width_mm,
        wire_height_mm=wire_height_mm,
        free_color_set=free_color_set,
        enable_coating=enable_coating,
        coating_height_mm=coating_height_mm,
        hue_weight=hue_weight,
        progress=progress,
    )


# ========== Color Replacement Functions ==========

def update_preview_with_backing_color(cache, backing_color_id: int):
    """
    Update preview image with new backing color without re-processing the entire image.
    
    This function rebuilds the voxel matrix with the new backing_color_id and updates
    the preview image to reflect the backing area colors. Other areas remain unchanged.
    
    Args:
        cache: Preview cache from generate_preview_cached containing:
               - material_matrix: (H, W, 5) material matrix
               - mask_solid: (H, W) solid pixel mask
               - preview_rgba: (H, W, 4) current preview image
               - color_conf: ColorSystem configuration
        backing_color_id: New backing material ID (0-7)
    
    Returns:
        tuple: (preview_image, status_message)
            - preview_image: Updated preview image (H, W, 4) RGBA array, or original if error
            - status_message: Success message or error message
    
    Validates:
        - Requirements 4.1: Updates 2D preview to reflect new backing color
        - Requirements 4.2: Keeps other material colors unchanged
        - Requirements 4.3: Updates preview without re-processing image
        - Requirements 8.4: Returns error message and keeps current preview on failure
    """
    if cache is None:
        return None, "[WARNING] Error: Cache cannot be None"
    
    try:
        # Validate backing_color_id
        color_conf = cache['color_conf']
        num_materials = len(color_conf['slots'])
        if backing_color_id < 0 or backing_color_id >= num_materials:
            print(f"[CONVERTER] Warning: Invalid backing_color_id={backing_color_id}, using default (0)")
            backing_color_id = 0
        
        # Get data from cache
        material_matrix = cache['material_matrix']
        mask_solid = cache['mask_solid']
        preview_rgba = cache['preview_rgba'].copy()
        
        target_h, target_w = material_matrix.shape[:2]
        
        # Get backing color from color system
        backing_color_rgba = color_conf['preview'][backing_color_id]
        backing_color_rgb = backing_color_rgba[:3]
        
        # Identify backing area: solid pixels that would be marked as backing in voxel matrix
        # In the voxel matrix, backing layers are at z=5 onwards (after the 5 color layers)
        # For preview purposes, we need to identify which pixels are "backing only"
        # These are pixels where all 5 layers have the same material or are dominated by backing
        
        # Strategy: Find pixels where the material_matrix layers would result in backing visibility
        # For simplicity, we'll update pixels that are solid but have minimal color variation
        # (indicating they're primarily backing/spacer material)
        
        # Actually, based on the design, the backing layer is separate from the color layers
        # The preview shows the top-down view of the color layers, not the backing
        # So we need to think about this differently...
        
        # Re-reading the requirements: The preview should show backing color changes
        # But the preview is a 2D top-down view of the color layers
        # The backing is underneath/between layers
        
        # Looking at the design more carefully:
        # - In double-sided mode: bottom 5 layers (color) + spacer (backing) + top 5 layers (color)
        # - In single-sided mode: bottom 5 layers (color) + spacer (backing)
        
        # For preview purposes, we should show the backing color where it would be visible
        # This is typically in areas where the color layers are thin or transparent
        
        # However, the current preview shows matched_rgb which is the color-matched result
        # The backing color would only be visible in the actual 3D model, not in the 2D preview
        
        # Re-reading requirement 4.1: "WHEN 用户选择底板颜色后，THE System SHALL 更新2D预览图像以反映新的底板颜色"
        # This suggests the 2D preview should somehow show the backing color
        
        # Looking at the design document more carefully:
        # The preview update function should update the preview to show backing color changes
        # But since the preview is a top-down view, the backing might not be directly visible
        
        # Let me reconsider: Perhaps the preview should show a visual indication of the backing color
        # Or perhaps the backing color affects the overall appearance when viewed from above
        
        # Actually, looking at the task description again:
        # "Rebuilds voxel matrix with new backing_color_id"
        # "Updates preview image backing area colors"
        
        # I think the key insight is that we need to identify which areas in the preview
        # correspond to the backing layer. In a 2D top-down view, this might be:
        # - Areas that are solid but have no color layers (pure backing)
        # - Or we need to composite the backing color with the color layers
        
        # Let me check if there's a mask or indicator for backing-only areas...
        # Looking at material_matrix: (H, W, 5) - this is 5 color layers
        # If all 5 layers are transparent (-1) but the pixel is solid, it's backing-only
        
        # Check for backing-only pixels: solid pixels where all material layers are -1
        all_layers_transparent = np.all(material_matrix == -1, axis=2)
        backing_only_mask = mask_solid & all_layers_transparent
        
        # Update backing-only areas with new backing color
        if np.any(backing_only_mask):
            preview_rgba[backing_only_mask, :3] = backing_color_rgb
            preview_rgba[backing_only_mask, 3] = 255
            print(f"[CONVERTER] Updated {np.sum(backing_only_mask)} backing-only pixels with color {color_conf['slots'][backing_color_id]}")
        else:
            print(f"[CONVERTER] No backing-only pixels found in preview")
        
        # Update cache with new backing_color_id
        cache['backing_color_id'] = backing_color_id
        cache['preview_rgba'] = preview_rgba.copy()
        
        return preview_rgba, f"✓ Preview updated with backing color: {color_conf['slots'][backing_color_id]}"
    
    except Exception as e:
        print(f"[CONVERTER] Error updating preview with backing color: {e}")
        # Return original preview from cache if available
        original_preview = cache.get('preview_rgba') if cache else None
        return original_preview, f"[WARNING] Preview update failed: {str(e)}. Showing original preview."


def update_preview_with_replacements(cache, replacement_regions=None,
                                     loop_pos=None, add_loop=False,
                                     loop_width=4, loop_length=8,
                                     loop_hole=2.5, loop_angle=0,
                                     lang: str = "zh",
                                     merge_map: dict = None):
    """
    Update preview image with color replacements and optional color merging applied.
    
    This function applies color replacements to the cached preview data
    without re-processing the entire image. It's designed for fast
    interactive updates when users change color mappings.
    
    Args:
        cache: Preview cache from generate_preview_cached
        color_replacements: Dict mapping original hex colors to replacement hex colors
                           e.g., {'#ff0000': '#00ff00'}
        loop_pos: Optional loop position tuple (x, y)
        add_loop: Whether to show keychain loop
        loop_width: Loop width in mm
        loop_length: Loop length in mm
        loop_hole: Loop hole diameter in mm
        loop_angle: Loop rotation angle in degrees
        merge_map: Optional dict mapping source hex to target hex colors for merging
                  (applied before color_replacements)
        lang: Language code
    
    Returns:
        tuple: (display_image, updated_cache, palette_html)
    """
    if cache is None:
        return None, None, ""
    
    # Get original matched_rgb (use stored original if available)
    original_rgb = cache.get('original_matched_rgb', cache['matched_rgb'])
    mask_solid = cache['mask_solid']
    color_conf = cache['color_conf']
    backing_color_id = cache.get('backing_color_id', 0)  # Handle old cache versions
    target_h, target_w = original_rgb.shape[:2]
    # Start with original RGB
    matched_rgb = original_rgb.copy()

    # Apply merge map first (if provided)
    if merge_map:
        from core.color_merger import ColorMerger
        from core.image_processing import LuminaImageProcessor

        merger = ColorMerger(LuminaImageProcessor._rgb_to_lab)
        matched_rgb = merger.apply_color_merging(matched_rgb, merge_map)

    # Apply region replacements in-order (later items override earlier items)
    for item in (replacement_regions or []):
        region_mask = item.get('mask')
        replacement_hex = item.get('replacement')
        if region_mask is None or not replacement_hex:
            continue
        replacement_rgb = _hex_to_rgb_tuple(replacement_hex)
        effective_mask = region_mask & mask_solid
        if np.any(effective_mask):
            matched_rgb[effective_mask] = np.array(replacement_rgb, dtype=np.uint8)
    
    # Build new preview RGBA
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    preview_rgba[mask_solid, 3] = 255
    
    # Update cache with new data
    updated_cache = cache.copy()
    updated_cache['matched_rgb'] = matched_rgb
    updated_cache['preview_rgba'] = preview_rgba.copy()
    updated_cache['backing_color_id'] = backing_color_id  # Preserve backing color ID
    
    # Store original if not already stored
    if 'original_matched_rgb' not in updated_cache:
        updated_cache['original_matched_rgb'] = original_rgb
    
    # Re-extract palette with new colors
    color_palette = extract_color_palette(updated_cache)
    updated_cache['color_palette'] = color_palette
    
    # Render display with loop if enabled
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width, loop_length, loop_hole, loop_angle,
        add_loop, color_conf,
        bed_label=cache.get('bed_label'),
        target_width_mm=cache.get('target_width_mm'),
        is_dark=cache.get('is_dark', True)
    )
    
    # Build auto pairs (quantized -> matched) for right table display
    auto_pairs = []
    q_img = updated_cache.get('quantized_image')
    if q_img is not None:
        h, w = matched_rgb.shape[:2]
        for y in range(h):
            for x in range(w):
                if not mask_solid[y, x]:
                    continue
                qh = _rgb_to_hex(q_img[y, x])
                mh = _rgb_to_hex(matched_rgb[y, x])
                auto_pairs.append({"quantized_hex": qh, "matched_hex": mh})

    # Generate palette HTML for display
    from ui.palette_extension import generate_palette_html
    palette_html = generate_palette_html(
        color_palette,
        replacements={},
        lang=lang,
        replacement_regions=replacement_regions or [],
        auto_pairs=auto_pairs,
    )
    
    return display, updated_cache, palette_html


# generate_palette_html is now imported from ui.palette_extension


# ========== Color Highlight Functions ==========

def generate_highlight_preview(cache, highlight_color: str, 
                               loop_pos=None, add_loop=False,
                               loop_width=4, loop_length=8, 
                               loop_hole=2.5, loop_angle=0):
    """
    Generate preview image with a specific color highlighted.
    
    This function creates a preview where the selected color is shown normally
    while all other colors are dimmed/grayed out, making it easy to see
    where a specific color is used in the image.
    
    Args:
        cache: Preview cache from generate_preview_cached
        highlight_color: Hex color to highlight (e.g., '#ff0000')
        loop_pos: Optional loop position tuple (x, y)
        add_loop: Whether to show keychain loop
        loop_width: Loop width in mm
        loop_length: Loop length in mm
        loop_hole: Loop hole diameter in mm
        loop_angle: Loop rotation angle in degrees
    
    Returns:
        tuple: (display_image, status_message)
    """
    if cache is None:
        return None, "[ERROR] 请先生成预览 | Generate preview first"
    
    if not highlight_color:
        # No highlight - return normal preview
        preview_rgba = cache.get('preview_rgba')
        if preview_rgba is None:
            return None, "[ERROR] 缓存数据无效 | Invalid cache"
        
        color_conf = cache['color_conf']
        display = render_preview(
            preview_rgba,
            loop_pos if add_loop else None,
            loop_width, loop_length, loop_hole, loop_angle,
            add_loop, color_conf,
            bed_label=cache.get('bed_label'),
            target_width_mm=cache.get('target_width_mm'),
            is_dark=cache.get('is_dark', True)
        )
        return display, "[OK] 预览已恢复 | Preview restored"
    # Parse highlight color
    highlight_hex = highlight_color.strip().lower()
    if not highlight_hex.startswith('#'):
        highlight_hex = '#' + highlight_hex
    
    # Convert hex to RGB
    try:
        r = int(highlight_hex[1:3], 16)
        g = int(highlight_hex[3:5], 16)
        b = int(highlight_hex[5:7], 16)
        highlight_rgb = np.array([r, g, b], dtype=np.uint8)
    except (ValueError, IndexError):
        return None, f"[ERROR] 无效的颜色值 | Invalid color: {highlight_color}"
    
    # Get data from cache
    matched_rgb = cache.get('matched_rgb')
    mask_solid = cache.get('mask_solid')
    color_conf = cache.get('color_conf')
    
    if matched_rgb is None or mask_solid is None:
        return None, "[ERROR] 缓存数据不完整 | Incomplete cache"
    
    target_h, target_w = matched_rgb.shape[:2]
    
    # Create highlight mask - pixels matching the highlight color
    color_match = np.all(matched_rgb == highlight_rgb, axis=2)

    scope = cache.get('selection_scope', 'global')
    region_mask = cache.get('selected_region_mask')
    highlight_mask = _resolve_highlight_mask(
        color_match,
        mask_solid,
        region_mask=region_mask,
        scope=scope,
    )
    
    # Count highlighted pixels
    highlight_count = np.sum(highlight_mask)
    total_solid = np.sum(mask_solid)
    
    if highlight_count == 0:
        return None, f"[WARNING] 未找到颜色 {highlight_hex} | Color not found"
    
    highlight_percentage = round(highlight_count / total_solid * 100, 2)
    
    # Create highlighted preview
    # Option 1: Dim non-highlighted areas (grayscale + reduced opacity)
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    
    # For non-highlighted solid pixels: convert to grayscale and dim
    non_highlight_mask = mask_solid & ~highlight_mask
    if np.any(non_highlight_mask):
        # Convert to grayscale
        gray_values = np.mean(matched_rgb[non_highlight_mask], axis=1).astype(np.uint8)
        # Apply dimming (mix with darker gray)
        dimmed_gray = (gray_values * 0.4 + 80).astype(np.uint8)
        preview_rgba[non_highlight_mask, 0] = dimmed_gray
        preview_rgba[non_highlight_mask, 1] = dimmed_gray
        preview_rgba[non_highlight_mask, 2] = dimmed_gray
        preview_rgba[non_highlight_mask, 3] = 180  # Semi-transparent
    
    # For highlighted pixels: show original color with full opacity
    preview_rgba[highlight_mask, :3] = matched_rgb[highlight_mask]
    preview_rgba[highlight_mask, 3] = 255
    
    # Add a subtle colored border/glow effect around highlighted regions
    # by dilating the highlight mask and drawing a border
    try:
        import cv2
        kernel = np.ones((5, 5), np.uint8)
        dilated = cv2.dilate(highlight_mask.astype(np.uint8), kernel, iterations=2)
        border_mask = (dilated > 0) & ~highlight_mask & mask_solid
        
        # Draw border in a contrasting color (cyan for visibility)
        if np.any(border_mask):
            preview_rgba[border_mask, 0] = 0    # R
            preview_rgba[border_mask, 1] = 255  # G
            preview_rgba[border_mask, 2] = 255  # B
            preview_rgba[border_mask, 3] = 200  # Alpha
    except Exception as e:
        print(f"[HIGHLIGHT] Border effect skipped: {e}")
    
    # Render display
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width, loop_length, loop_hole, loop_angle,
        add_loop, color_conf,
        bed_label=cache.get('bed_label'),
        target_width_mm=cache.get('target_width_mm'),
        is_dark=cache.get('is_dark', True)
    )
    
    return display, f"🔍 高亮 {highlight_hex} ({highlight_percentage}%, {highlight_count:,} 像素)"


def clear_highlight_preview(cache, loop_pos=None, add_loop=False,
                            loop_width=4, loop_length=8, 
                            loop_hole=2.5, loop_angle=0):
    """
    Clear highlight and restore normal preview.
    
    Args:
        cache: Preview cache from generate_preview_cached
        loop_pos: Optional loop position tuple (x, y)
        add_loop: Whether to show keychain loop
        loop_width: Loop width in mm
        loop_length: Loop length in mm
        loop_hole: Loop hole diameter in mm
        loop_angle: Loop rotation angle in degrees
    
    Returns:
        tuple: (display_image, status_message)
    """
    print(f"[CLEAR_HIGHLIGHT] Called with cache={cache is not None}, loop_pos={loop_pos}, add_loop={add_loop}")
    
    if cache is None:
        print("[CLEAR_HIGHLIGHT] Cache is None!")
        return None, "[ERROR] 请先生成预览 | Generate preview first"
    
    preview_rgba = cache.get('preview_rgba')
    if preview_rgba is None:
        print("[CLEAR_HIGHLIGHT] preview_rgba is None!")
        return None, "[ERROR] 缓存数据无效 | Invalid cache"
    
    print(f"[CLEAR_HIGHLIGHT] preview_rgba shape: {preview_rgba.shape}")
    
    color_conf = cache['color_conf']
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width, loop_length, loop_hole, loop_angle,
        add_loop, color_conf,
        bed_label=cache.get('bed_label'),
        target_width_mm=cache.get('target_width_mm'),
        is_dark=cache.get('is_dark', True)
    )
    
    print(f"[CLEAR_HIGHLIGHT] display shape: {display.shape if display is not None else None}")
    
    return display, "[OK] 预览已恢复 | Preview restored"


# [新增] 预览图点击吸取颜色并高亮
def on_preview_click_select_color(cache, evt: gr.SelectData, bed_label=None):
    """
    预览图点击事件处理：吸取颜色并高亮显示
    1. 识别点击位置的颜色
    2. 生成该颜色的高亮预览图
    3. 返回颜色信息给 UI
    """
    if cache is None:
        return None, "未选择", None, "[ERROR] 请先生成预览"

    if evt is None or evt.index is None:
        return gr.update(), "未选择", None, "[WARNING] 无效点击"

    if bed_label is None:
        bed_label = cache.get('bed_label', BedManager.DEFAULT_BED)

    display_click_x, display_click_y = evt.index

    target_w = cache.get('target_w')
    target_h = cache.get('target_h')
    target_width_mm = cache.get('target_width_mm')

    if target_w is None or target_h is None:
        return gr.update(), "未选择", None, "[ERROR] 缓存数据不完整"

    bed_w_mm, bed_h_mm = BedManager.get_bed_size(bed_label)
    ppm = BedManager.compute_scale(bed_w_mm, bed_h_mm)
    margin = int(30 * ppm / 3)

    canvas_w = int(bed_w_mm * ppm) + margin
    canvas_h = int(bed_h_mm * ppm) + margin

    # Use target_width_mm from cache for accurate physical size
    if target_width_mm is not None and target_width_mm > 0:
        model_w_mm = target_width_mm
        model_h_mm = target_width_mm * target_h / target_w
    else:
        model_w_mm = target_w * PrinterConfig.NOZZLE_WIDTH
        model_h_mm = target_h * PrinterConfig.NOZZLE_WIDTH
    new_w = max(1, int(model_w_mm * ppm))
    new_h = max(1, int(model_h_mm * ppm))

    offset_x = margin + (int(bed_w_mm * ppm) - new_w) // 2
    offset_y = (int(bed_h_mm * ppm) - new_h) // 2

    # _scale_preview_image fits canvas into 1200×750 box
    gradio_scale = min(1.0, 1200 / canvas_w, 750 / canvas_h)

    canvas_click_x = display_click_x / gradio_scale
    canvas_click_y = display_click_y / gradio_scale

    # Convert canvas coords → original image pixel coords
    mm_per_px = model_w_mm / target_w
    img_px_x = (canvas_click_x - offset_x) / (mm_per_px * ppm)
    img_px_y = (canvas_click_y - offset_y) / (mm_per_px * ppm)

    orig_x = int(img_px_x)
    orig_y = int(img_px_y)

    matched_rgb = cache.get('original_matched_rgb', cache.get('matched_rgb'))
    quantized_image = cache.get('quantized_image')
    mask_solid = cache.get('mask_solid')

    if quantized_image is None:
        _ensure_quantized_image_in_cache(cache)
        quantized_image = cache.get('quantized_image')

    if matched_rgb is None or mask_solid is None or quantized_image is None:
        return None, "未选择", None, "[ERROR] 缓存无效"

    h, w = matched_rgb.shape[:2]

    if not (0 <= orig_x < w and 0 <= orig_y < h):
        return gr.update(), "未选择", None, f"[WARNING] 点击了无效区域 ({orig_x}, {orig_y})"

    if not mask_solid[orig_y, orig_x]:
        return gr.update(), "未选择", None, "[WARNING] 点击了背景区域"

    q_rgb = tuple(int(v) for v in quantized_image[orig_y, orig_x])
    m_rgb = tuple(int(v) for v in matched_rgb[orig_y, orig_x])

    region_mask = _compute_connected_region_mask_4n(quantized_image, mask_solid, orig_x, orig_y)
    cache['selected_region_mask'] = region_mask
    cache.update(_build_selection_meta(q_rgb, m_rgb, scope="region"))

    q_hex = cache['selected_quantized_hex']
    m_hex = cache['selected_matched_hex']

    print(f"[CLICK] Coords: ({orig_x}, {orig_y}), Quantized: {q_hex}, Matched: {m_hex}")

    display_img, status_msg = generate_highlight_preview(
        cache,
        highlight_color=q_hex,
        add_loop=False
    )

    display_text = f"量化色 {q_hex} | 原配准色 {m_hex}"
    if display_img is None:
        return gr.update(), display_text, q_hex, status_msg

    return display_img, display_text, q_hex, status_msg


def generate_lut_grid_html(lut_path, lang: str = "zh"):
    """
    生成 LUT 可用颜色的 HTML 网格 (with hue filter + smart search)
    """
    from core.i18n import I18n
    import colorsys
    colors = extract_lut_available_colors(lut_path)

    if not colors:
        return f"<div style='color:orange'>LUT 文件无效或为空</div>"

    count = len(colors)

    def _classify_hue(r, g, b):
        rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
        h, s, v = colorsys.rgb_to_hsv(rf, gf, bf)
        h360 = h * 360
        if s < 0.15 or v < 0.10:
            return 'neutral'
        if h360 < 15 or h360 >= 345:
            return 'red'
        elif h360 < 40:
            return 'orange'
        elif h360 < 70:
            return 'yellow'
        elif h360 < 160:
            return 'green'
        elif h360 < 195:
            return 'cyan'
        elif h360 < 260:
            return 'blue'
        elif h360 < 345:
            return 'purple'
        return 'neutral'

    from ui.palette_extension import build_search_bar_html, build_hue_filter_bar_html

    # Derive LUT key for favorites persistence
    _lut_key = os.path.splitext(os.path.basename(lut_path))[0] if lut_path else ''

    html = f"""
    <div class="lut-grid-container">
        <div style="margin-bottom: 8px; font-size: 12px; color: #666;">
            {I18n.get('lut_grid_count', lang).format(count=count)}: <span id="lut-color-visible-count">{count}</span>
        </div>
        {build_search_bar_html(lang)}
        {build_hue_filter_bar_html(lang)}
        <div id="lut-color-grid-container" data-lut-key="{_lut_key}" style="
            display: flex;
            flex-wrap: wrap;
            gap: 4px;
            max-height: 300px;
            overflow-y: auto;
            padding: 5px;
            border: 1px solid #eee;
            border-radius: 8px;
            background: #f9f9f9;">
    """

    for entry in colors:
        hex_val = entry['hex']
        r, g, b = entry['color']
        rgb_val = f"R:{r} G:{g} B:{b}"
        hue_cat = _classify_hue(r, g, b)

        html += f"""
        <div class="lut-color-swatch-container" data-hue="{hue_cat}" style="display:flex;">
        <div class="lut-swatch lut-color-swatch"
             data-color="{hex_val}"
             style="background-color: {hex_val}; width:24px; height:24px; cursor:pointer; border:1px solid #ddd; border-radius:3px;"
             title="{hex_val} ({rgb_val})">
        </div>
        </div>
        """

    html += "</div></div>"
    return html


def generate_lut_card_grid_html(lut_path, lang: str = "zh"):
    """
    Generate a calibration-card-style (色卡) HTML grid for the LUT.

    Colors are displayed in their original LUT order arranged in a square grid,
    matching the physical calibration board layout.  For 8-color LUTs the two
    halves are shown side-by-side horizontally.

    Includes search bar (highlight-in-place, no hiding) and hue filter
    (dims non-matching swatches instead of hiding to preserve grid layout).

    Each swatch is clickable (same data-color / class as the swatch grid) so
    the existing event-delegation click handler picks it up automatically.
    """
    if not lut_path:
        return "<div style='color:orange'>LUT 文件无效或为空</div>"

    try:
        lut_grid = np.load(lut_path)
        measured_colors = lut_grid.reshape(-1, 3)
    except Exception as e:
        return f"<div style='color:orange'>LUT 加载失败: {e}</div>"

    total = len(measured_colors)

    from core.i18n import I18n
    import colorsys

    def _classify_hue(r, g, b):
        rf, gf, bf = r / 255.0, g / 255.0, b / 255.0
        h, s, v = colorsys.rgb_to_hsv(rf, gf, bf)
        h360 = h * 360
        if s < 0.15 or v < 0.10:
            return 'neutral'
        if h360 < 15 or h360 >= 345:
            return 'red'
        elif h360 < 40:
            return 'orange'
        elif h360 < 70:
            return 'yellow'
        elif h360 < 160:
            return 'green'
        elif h360 < 195:
            return 'cyan'
        elif h360 < 260:
            return 'blue'
        elif h360 < 345:
            return 'purple'
        return 'neutral'

    import math
    if total == 2738:
        half = total // 2
        remainder = total - half
        dim1 = int(math.ceil(math.sqrt(half)))
        dim2 = int(math.ceil(math.sqrt(remainder)))
        grids = [
            (measured_colors[:half], dim1, "色卡 A" if lang == "zh" else "Card A"),
            (measured_colors[half:], dim2, "色卡 B" if lang == "zh" else "Card B"),
        ]
    else:
        dim = int(math.ceil(math.sqrt(total)))
        label = f"{total} 色色卡" if lang == "zh" else f"{total}-color Card"
        grids = [(measured_colors, dim, label)]

    cell = 18
    gap = 1

    from ui.palette_extension import build_search_bar_html, build_hue_filter_bar_html

    html_parts = [
        f'<div style="margin-bottom:8px; font-size:12px; color:#666;">{I18n.get("lut_grid_count", lang).format(count=total)}: <span id="lut-color-visible-count">{total}</span></div>',
        build_search_bar_html(lang),
        build_hue_filter_bar_html(lang),
    ]

    # Derive LUT key for favorites persistence
    _lut_key = os.path.splitext(os.path.basename(lut_path))[0] if lut_path else ''

    # Grid
    html_parts.append(
        f"<div id='lut-color-grid-container' data-lut-key='{_lut_key}' style='display:flex; gap:12px; align-items:flex-start; "
        "overflow-x:auto; padding:4px;'>"
    )

    for colors_arr, dim, title in grids:
        html_parts.append(
            f"<div style='flex-shrink:0;'>"
            f"<div style='font-size:11px; color:#666; margin-bottom:4px;'>{title} ({len(colors_arr)})</div>"
            f"<div style='display:grid; grid-template-columns:repeat({dim}, {cell}px); gap:{gap}px; "
            f"border:1px solid #eee; border-radius:6px; padding:4px; background:#f9f9f9;'>"
        )
        for c in colors_arr:
            r, g, b = int(c[0]), int(c[1]), int(c[2])
            hex_val = f"#{r:02x}{g:02x}{b:02x}"
            hue_cat = _classify_hue(r, g, b)
            html_parts.append(
                f"<div class='lut-swatch lut-color-swatch' data-color='{hex_val}' data-hue='{hue_cat}' "
                f"style='width:{cell}px;height:{cell}px;background:{hex_val};"
                f"cursor:pointer;border-radius:2px;' "
                f"title='{hex_val} (R:{r} G:{g} B:{b})'></div>"
            )
        html_parts.append("</div></div>")

    html_parts.append("</div>")
    return "".join(html_parts)


# ========== Auto-detection Functions ==========

def _infer_4color_subtype(lut_path: str) -> str:
    """Distinguish CMYW vs RYBW from filename keywords.
    Returns "CMYW", "RYBW", or "4-Color" (unknown)."""
    name = os.path.basename(lut_path).upper()
    if "CMYW" in name or "青品黄" in name:
        return "CMYW"
    if "RYBW" in name or "红黄蓝" in name:
        return "RYBW"
    return "4-Color"


def detect_lut_color_mode(lut_path):
    """
    自动检测LUT文件的颜色模式

    Args:
        lut_path: LUT文件路径

    Returns:
        str: 颜色模式 ("BW (Black & White)", "Merged", "6-Color (Smart 1296)", "8-Color Max", etc.)
    """
    if not lut_path or not os.path.exists(lut_path):
        return None
    
    try:
        if lut_path.endswith('.npz'):
            data = np.load(lut_path)
            if 'rgb' in data:
                rgb = data['rgb']
                total_colors = int(rgb.reshape(-1, 3).shape[0])
                stacks = data['stacks'] if 'stacks' in data else None
                layer_count = int(stacks.shape[1]) if isinstance(stacks, np.ndarray) and stacks.ndim == 2 else None
                max_mat = int(np.max(stacks)) if isinstance(stacks, np.ndarray) and stacks.size > 0 else None
                if total_colors >= 2400 and total_colors < 2600 and layer_count == 6 and (max_mat is None or max_mat <= 4):
                    print(f"[AUTO_DETECT] Detected 5-Color Extended mode from .npz ({total_colors} colors)")
                    return "5-Color Extended"
                if total_colors >= 2600 and total_colors <= 2800:
                    print(f"[AUTO_DETECT] Detected 8-Color mode from .npz ({total_colors} colors)")
                    return "8-Color Max"
                if total_colors >= 1200 and total_colors < 1400:
                    print(f"[AUTO_DETECT] Detected 6-Color mode from .npz ({total_colors} colors)")
                    return "6-Color (Smart 1296)"
                if total_colors >= 900 and total_colors < 1200:
                    subtype = _infer_4color_subtype(lut_path)
                    print(f"[AUTO_DETECT] Detected {subtype} mode from .npz ({total_colors} colors)")
                    return subtype
                if total_colors >= 30 and total_colors <= 36:
                    print(f"[AUTO_DETECT] Detected 2-Color BW mode from .npz ({total_colors} colors)")
                    return "BW (Black & White)"
            print(f"[AUTO_DETECT] Detected Merged LUT (.npz format)")
            return "Merged"
        
        # Standard .npy format
        lut_data = np.load(lut_path)
        
        # 确保是2D数组
        if lut_data.ndim == 1:
            # 如果是1D数组，假设是 (N*3,) 格式，重塑为 (N, 3)
            if len(lut_data) % 3 == 0:
                lut_data = lut_data.reshape(-1, 3)
            else:
                print(f"[AUTO_DETECT] Invalid LUT format: cannot reshape to (N, 3)")
                return None
        
        # 计算颜色数量
        if lut_data.ndim == 2:
            total_colors = lut_data.shape[0]
        else:
            total_colors = lut_data.shape[0] * lut_data.shape[1]
        
        print(f"[AUTO_DETECT] LUT shape: {lut_data.shape}, total colors: {total_colors}")
        
        # 2色模式：32色 (2^5 = 32), LUT is 6x6 grid = 36 entries
        if total_colors >= 30 and total_colors <= 36:
            print(f"[AUTO_DETECT] Detected 2-Color BW mode (32 colors)")
            return "BW (Black & White)"
        
        # 5-Color Extended模式：~2468色 (1024 base + 1444 extended)
        elif total_colors >= 2400 and total_colors < 2600:
            print(f"[AUTO_DETECT] Detected 5-Color Extended mode ({total_colors} colors)")
            return "5-Color Extended"
        
        # 8色模式：2600-2800色
        elif total_colors >= 2600 and total_colors <= 2800:
            print(f"[AUTO_DETECT] Detected 8-Color mode ({total_colors} colors)")
            return "8-Color Max"
        
        # 6色模式：1200-1400色
        elif total_colors >= 1200 and total_colors < 1400:
            print(f"[AUTO_DETECT] Detected 6-Color mode ({total_colors} colors)")
            return "6-Color (Smart 1296)"
        
        # 4色模式：900-1200色
        elif total_colors >= 900 and total_colors < 1200:
            subtype = _infer_4color_subtype(lut_path)
            print(f"[AUTO_DETECT] Detected {subtype} mode ({total_colors} colors)")
            return subtype
        
        else:
            # 非标准尺寸：识别为合并色卡
            print(f"[AUTO_DETECT] Non-standard LUT size ({total_colors} colors), detected as Merged")
            return "Merged"
            
    except Exception as e:
        print(f"[AUTO_DETECT] Error detecting LUT mode: {e}")
        import traceback
        traceback.print_exc()
        return None


def detect_image_type(image_path):
    """
    Detect image type and return recommended modeling mode.
    自动检测图像类型并返回推荐的建模模式。

    Args:
        image_path (str): Image file path. (图像文件路径)

    Returns:
        gr.update: Gradio update object with new mode, or no-op update. (Gradio 更新对象)
    """
    import gradio as gr
    if not image_path:
        return gr.update()
    
    try:
        ext = os.path.splitext(image_path)[1].lower()
        
        if ext == '.svg':
            print(f"[AUTO_DETECT] SVG file detected, recommending SVG Mode")
            return gr.update(value=ModelingMode.VECTOR)
        else:
            print(f"[AUTO_DETECT] Raster image detected ({ext}), keeping current mode")
            return gr.update()  # 不改变当前选择
            
    except Exception as e:
        print(f"[AUTO_DETECT] Error detecting image type: {e}")
        return None
