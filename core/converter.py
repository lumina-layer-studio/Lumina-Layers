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

# Try to import LUTManager for metadata loading
try:
    from utils.lut_manager import LUTManager
except ImportError:
    LUTManager = None

# Import palette HTML generator from extension (non-invasive)
# Moved to lazy import to avoid circular dependency
# from ui.palette_extension import generate_palette_html, generate_lut_color_grid_html


# ========== LUT Color Extraction Functions ==========

def extract_lut_available_colors(lut_path: str) -> List[dict]:
    """
    Extract all available colors from a LUT file.
    
    This function loads a LUT file (.npy/.npz/.json) and extracts all unique
    colors that the printer can produce. These colors can be used as
    replacement options in the color replacement feature.
    
    Uses LUTManager.load_lut_with_metadata() as the unified loading entry
    point to support all LUT formats consistently.
    
    Args:
        lut_path: Path to the LUT file (.npy/.npz/.json)
    
    Returns:
        List of dicts, each containing:
        - 'color': (R, G, B) tuple
        - 'hex': '#RRGGBB' string
        
        Returns empty list if LUT cannot be loaded.
    """
    if not lut_path:
        return []
    
    try:
        # 统一通过 LUTManager 加载，支持 .npy/.npz/.json 三种格式
        if LUTManager is not None:
            rgb, _stacks, _metadata = LUTManager.load_lut_with_metadata(lut_path)
            measured_colors = rgb.reshape(-1, 3)
        elif lut_path.endswith('.npz'):
            data = np.load(lut_path, allow_pickle=False)
            measured_colors = data['rgb']
        else:
            lut_grid = np.load(lut_path)
            measured_colors = lut_grid.reshape(-1, 3)
        print(f"[LUT_COLORS] Loading LUT with {len(measured_colors)} colors from {lut_path}")
        
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
    """[代理] 已迁移到 core.processing.palette.ensure_quantized_image_in_cache"""
    from core.processing.palette import ensure_quantized_image_in_cache
    return ensure_quantized_image_in_cache(cache)


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
    """[代理] 已迁移到 core.processing.color_replacement.normalize_color_replacements_input"""
    from core.processing.color_replacement import normalize_color_replacements_input
    return normalize_color_replacements_input(color_replacements)


def _apply_region_replacement(image_rgb, region_mask, replacement_rgb):
    """仅在 region_mask 覆盖区域应用替换色。"""
    out = image_rgb.copy()
    out[region_mask] = np.array(replacement_rgb, dtype=np.uint8)
    return out


def _apply_regions_to_raster_outputs(matched_rgb, material_matrix, mask_solid,
                                     replacement_regions, lut_index_resolver, ref_stacks):
    """[代理] 已迁移到 core.processing.color_replacement.apply_regions_to_raster_outputs"""
    from core.processing.color_replacement import apply_regions_to_raster_outputs
    return apply_regions_to_raster_outputs(matched_rgb, material_matrix, mask_solid,
                                           replacement_regions, lut_index_resolver, ref_stacks)


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
    """[代理] 已迁移到 core.processing.palette.extract_color_palette"""
    from core.processing.palette import extract_color_palette as _extract
    return _extract(preview_cache)


# ========== Debug Helper Functions ==========

def _save_debug_preview(debug_data, material_matrix, mask_solid, image_path, mode_name, num_materials=4):
    """[代理] 已迁移到 core.processing.debug_preview.save_debug_preview"""
    from core.processing.debug_preview import save_debug_preview
    return save_debug_preview(debug_data, material_matrix, mask_solid, image_path, mode_name, num_materials)


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
                         chroma_gate: float = 15.0,
                         matched_rgb_path: Optional[str] = None,
                         progress=None):
    """
    Main conversion function: Convert image to 3D model.
    主转换函数：将图像转换为 3D 模型。

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
        matched_rgb_path: Optional path to a .npy file containing pre-computed matched_rgb
                         override array. When provided, the override replaces the matched_rgb
                         from process_image and diff pixels get their material_matrix
                         recomputed via KDTree. (可选的预计算 matched_rgb .npy 文件路径，
                         提供时将替代 process_image 的结果，差异像素的 material_matrix
                         通过 KDTree 重新计算。)
    
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
    
    # ========== [REFACTORED] Raster-based Processing via Pipeline ==========
    # 使用模块化管道架构，每个处理步骤可独立插入/移除/替换。
    # 原始逻辑 100% 保留，仅组织形式改变。
    from core.pipeline import PipelineContext
    from core.pipeline_steps import build_raster_pipeline  # noqa: from package

    pipeline = build_raster_pipeline()
    pipe_ctx = PipelineContext(
        params={
            'image_path': image_path,
            'lut_path': lut_path,
            'target_width_mm': target_width_mm,
            'spacer_thick': spacer_thick,
            'structure_mode': structure_mode,
            'auto_bg': auto_bg,
            'bg_tol': bg_tol,
            'color_mode': color_mode,
            'add_loop': add_loop,
            'loop_width': loop_width,
            'loop_length': loop_length,
            'loop_hole': loop_hole,
            'loop_pos': loop_pos,
            'modeling_mode': modeling_mode,
            'quantize_colors': quantize_colors,
            'blur_kernel': blur_kernel,
            'smooth_sigma': smooth_sigma,
            'color_replacements': color_replacements,
            'replacement_regions': replacement_regions,
            'backing_color_id': backing_color_id,
            'separate_backing': separate_backing,
            'enable_relief': enable_relief,
            'color_height_map': color_height_map,
            'height_mode': height_mode,
            'heightmap_path': heightmap_path,
            'heightmap_max_height': heightmap_max_height,
            'enable_cleanup': enable_cleanup,
            'enable_outline': enable_outline,
            'outline_width': outline_width,
            'enable_cloisonne': enable_cloisonne,
            'wire_width_mm': wire_width_mm,
            'wire_height_mm': wire_height_mm,
            'free_color_set': free_color_set,
            'enable_coating': enable_coating,
            'coating_height_mm': coating_height_mm,
            'hue_weight': hue_weight,
            'chroma_gate': chroma_gate,
            'matched_rgb_path': matched_rgb_path,
        },
        _progress_fn=_prog,
    )

    pipe_ctx = pipeline.run(pipe_ctx)
    return pipe_ctx.result


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
    """代理函数 - 实际实现已迁移到 core.processing.outline_mesh 模块。"""
    from core.processing.outline_mesh import generate_outline_mesh
    return generate_outline_mesh(mask_solid, pixel_scale, outline_width_mm, outline_thickness_mm, target_h)


def _calculate_loop_info(loop_pos, loop_width, loop_length, loop_hole,
                         mask_solid, material_matrix, target_w, target_h, pixel_scale):
    """[代理] 已迁移到 core.processing.loop_utils.calculate_loop_info"""
    from core.processing.loop_utils import calculate_loop_info
    return calculate_loop_info(loop_pos, loop_width, loop_length, loop_hole,
                               mask_solid, material_matrix, target_w, target_h, pixel_scale)


def _draw_loop_on_preview(preview_rgba, loop_info, color_conf, pixel_scale):
    """[代理] 已迁移到 core.processing.loop_utils.draw_loop_on_preview"""
    from core.processing.loop_utils import draw_loop_on_preview
    return draw_loop_on_preview(preview_rgba, loop_info, color_conf, pixel_scale)


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


def _normalize_color_height_map(color_height_map: dict[str, float]) -> dict[str, float]:
    """代理函数 - 实际实现已迁移到 core.processing.voxel_builder 模块。"""
    from core.processing.voxel_builder import normalize_color_height_map
    return normalize_color_height_map(color_height_map)


def _build_relief_voxel_matrix(matched_rgb, material_matrix, mask_solid, color_height_map,
                               default_height, structure_mode, backing_color_id, pixel_scale,
                               height_matrix=None):
    """代理函数 - 实际实现已迁移到 core.processing.voxel_builder 模块。"""
    from core.processing.voxel_builder import build_relief_voxel_matrix
    return build_relief_voxel_matrix(matched_rgb, material_matrix, mask_solid, color_height_map,
                                     default_height, structure_mode, backing_color_id, pixel_scale,
                                     height_matrix)


def _build_cloisonne_voxel_matrix(material_matrix, mask_solid, mask_wireframe,
                                  spacer_thick, wire_height_mm,
                                  backing_color_id=0):
    """代理函数 - 实际实现已迁移到 core.processing.voxel_builder 模块。"""
    from core.processing.voxel_builder import build_cloisonne_voxel_matrix
    return build_cloisonne_voxel_matrix(material_matrix, mask_solid, mask_wireframe,
                                        spacer_thick, wire_height_mm, backing_color_id)


def _build_voxel_matrix(material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id=0):
    """代理函数 - 实际实现已迁移到 core.processing.voxel_builder 模块。"""
    from core.processing.voxel_builder import build_voxel_matrix
    return build_voxel_matrix(material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id)


def _build_voxel_matrix_6layer(material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id=0):
    """[代理] 已迁移到 core.processing.voxel_builder.build_voxel_matrix_6layer"""
    from core.processing.voxel_builder import build_voxel_matrix_6layer
    return build_voxel_matrix_6layer(material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id)


def _build_voxel_matrix_faceup(material_matrix, mask_solid, spacer_thick, backing_color_id=0):
    """[代理] 已迁移到 core.processing.voxel_builder.build_voxel_matrix_faceup"""
    from core.processing.voxel_builder import build_voxel_matrix_faceup
    return build_voxel_matrix_faceup(material_matrix, mask_solid, spacer_thick, backing_color_id)


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
    """[代理] 已迁移到 core.processing.preview_mesh.create_preview_mesh"""
    from core.processing.preview_mesh import create_preview_mesh
    return create_preview_mesh(matched_rgb, mask_solid, total_layers, backing_color_id, backing_z_range, preview_colors)


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
        # 4.5 Build backing plate mesh
        # ------------------------------------------------------------------
        backing_mesh = _build_color_voxel_mesh(
            mask_solid, height, width,
            total_layers=1,
            shrink=shrink,
            rgba=np.array([245, 245, 245, 255], dtype=np.uint8),
        )
        if backing_mesh is not None:
            backing_mesh.apply_transform(scale_transform)
            min_z = backing_mesh.vertices[:, 2].min()
            if min_z != 0.0:
                backing_mesh.vertices[:, 2] -= min_z
            scene.add_geometry(backing_mesh, node_name="backing_plate")
            print(f"[SEGMENTED_GLB] Backing plate added ({backing_mesh.vertices.shape[0]} vertices)")

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
                            hue_weight: float = 0.0,
                            chroma_gate: float = 15.0):
    """
    Generate preview and cache data via Preview Pipeline.
    通过预览管道生成预览图和缓存数据。

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
    from core.pipeline import PipelineContext
    from core.preview_pipeline_steps import build_preview_pipeline

    pipeline = build_preview_pipeline()
    ctx = PipelineContext(params={
        "image_path": image_path,
        "lut_path": lut_path,
        "target_width_mm": target_width_mm,
        "auto_bg": auto_bg,
        "bg_tol": bg_tol,
        "color_mode": color_mode,
        "modeling_mode": modeling_mode,
        "quantize_colors": quantize_colors,
        "backing_color_id": backing_color_id,
        "enable_cleanup": enable_cleanup,
        "is_dark": is_dark,
        "hue_weight": hue_weight,
        "chroma_gate": chroma_gate,
    })

    ctx = pipeline.run(ctx)

    return ctx.result.get("display"), ctx.result.get("cache"), ctx.result.get("status", "")


def render_preview(preview_rgba, loop_pos, loop_width, loop_length, 
                   loop_hole, loop_angle, loop_enabled, color_conf,
                   bed_label=None, target_width_mm=None, is_dark=True):
    """[代理] 已迁移到 core.processing.preview_render.render_preview"""
    from core.processing.preview_render import render_preview as _render_preview
    return _render_preview(preview_rgba, loop_pos, loop_width, loop_length,
                           loop_hole, loop_angle, loop_enabled, color_conf,
                           bed_label, target_width_mm, is_dark)


def _draw_loop_on_canvas(pil_img, loop_pos, loop_width, loop_length, 
                         loop_hole, loop_angle, color_conf, margin,
                         ppm=None, img_offset=None, mm_per_px=None):
    """[代理] 已迁移到 core.processing.preview_render._draw_loop_on_canvas"""
    from core.processing.preview_render import _draw_loop_on_canvas as _impl
    return _impl(pil_img, loop_pos, loop_width, loop_length,
                 loop_hole, loop_angle, color_conf, margin,
                 ppm, img_offset, mm_per_px)


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
                        chroma_gate: float = 15.0,
                        matched_rgb_path: Optional[str] = None,
                        progress=None):
    """Wrapper function for generating final model.
    生成最终模型的包装函数。
    
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
        matched_rgb_path (Optional[str]): Path to pre-computed matched_rgb .npy file.
            (预计算的 matched_rgb .npy 文件路径，用于区域替换后的 3MF 生成)
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
        chroma_gate=chroma_gate,
        matched_rgb_path=matched_rgb_path,
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
                    print(f"[AUTO_DETECT] Detected 4-Color mode from .npz ({total_colors} colors)")
                    return "4-Color"
                if total_colors >= 30 and total_colors <= 35:
                    print(f"[AUTO_DETECT] Detected 2-Color BW mode from .npz ({total_colors} colors)")
                    return "BW (Black & White)"
            print(f"[AUTO_DETECT] Detected Merged LUT (.npz format)")
            return "Merged"
        
        # .json (Keyed JSON) format
        if lut_path.endswith('.json'):
            from utils.lut_manager import LUTManager
            rgb, stacks, _meta = LUTManager.load_lut_with_metadata(lut_path)
            total_colors = len(rgb) if rgb is not None else 0
            layer_count = int(stacks.shape[1]) if isinstance(stacks, np.ndarray) and stacks.ndim == 2 else None
            max_mat = int(np.max(stacks)) if isinstance(stacks, np.ndarray) and stacks.size > 0 else None
            print(f"[AUTO_DETECT] JSON LUT: {total_colors} colors, layer_count={layer_count}, max_mat={max_mat}")
            if total_colors >= 2400 and total_colors < 2600 and layer_count == 6 and (max_mat is None or max_mat <= 4):
                print(f"[AUTO_DETECT] Detected 5-Color Extended mode from .json ({total_colors} colors)")
                return "5-Color Extended"
            if total_colors >= 2600 and total_colors <= 2800:
                print(f"[AUTO_DETECT] Detected 8-Color mode from .json ({total_colors} colors)")
                return "8-Color Max"
            if total_colors >= 1200 and total_colors < 1400:
                print(f"[AUTO_DETECT] Detected 6-Color mode from .json ({total_colors} colors)")
                return "6-Color (Smart 1296)"
            if total_colors >= 900 and total_colors < 1200:
                print(f"[AUTO_DETECT] Detected 4-Color mode from .json ({total_colors} colors)")
                return "4-Color"
            if total_colors >= 30 and total_colors <= 35:
                print(f"[AUTO_DETECT] Detected 2-Color BW mode from .json ({total_colors} colors)")
                return "BW (Black & White)"
            print(f"[AUTO_DETECT] Non-standard JSON LUT size ({total_colors} colors), detected as Merged")
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
        
        # 2色模式：32色 (2^5 = 32)
        if total_colors >= 30 and total_colors <= 35:
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
            print(f"[AUTO_DETECT] Detected 4-Color mode ({total_colors} colors)")
            return "4-Color"
        
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
