"""
Lumina Studio - Image Converter Coordinator (Refactored)

Coordinates modules to complete image-to-3D model conversion.
"""

import os
from dataclasses import dataclass
import numpy as np
import cv2
import trimesh
from PIL import Image, ImageDraw, ImageFont
import gradio as gr
from typing import List, Dict, Tuple, Optional

from config import (
    PrinterConfig,
    ColorMode,
    ColorSystem,
    ModelingMode,
    MatchStrategy,
    PREVIEW_SCALE,
    PREVIEW_MARGIN,
    OUTPUT_DIR,
)
from .ui_status import make_status_tag
from core.image_processing_factory import ImageLoader
from utils import Stats, safe_fix_3mf_names

from core.image_processing import LuminaImageProcessor
from core.mesh_generators import get_mesher
from core.geometry_utils import create_keychain_loop

# Try to import SVG rendering libraries
try:
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPM

    HAS_SVG_LIB = True
except ImportError:
    HAS_SVG_LIB = False

# Import palette HTML generator from extension (non-invasive)
from ui.palette_extension import generate_palette_html, generate_lut_color_grid_html


# ========== LUT Color Extraction Functions ==========


def extract_lut_available_colors(lut_path: str) -> List[dict]:
    """
    Extract all available colors from a LUT file.

    This function loads a LUT .npy file and extracts all unique colors
    that the printer can produce. These colors can be used as replacement
    options in the color replacement feature.

    Args:
        lut_path: Path to the LUT .npy file

    Returns:
        List of dicts, each containing:
        - 'color': (R, G, B) tuple
        - 'hex': '#RRGGBB' string

        Returns empty list if LUT cannot be loaded.
    """
    if not lut_path:
        return []

    try:
        # Load LUT data
        lut_grid = np.load(lut_path)
        measured_colors = lut_grid.reshape(-1, 3)

        # Get unique colors
        unique_colors = np.unique(measured_colors, axis=0)

        # Build color list
        colors = []
        for color in unique_colors:
            r, g, b = int(color[0]), int(color[1]), int(color[2])
            colors.append({"color": (r, g, b), "hex": f"#{r:02x}{g:02x}{b:02x}"})

        # Sort by brightness (dark to light) for better UX
        colors.sort(key=lambda x: sum(x["color"]))

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
        hex_color = entry["hex"]
        r, g, b = entry["color"]
        # Create a display label with RGB values
        label = f"■ {hex_color} (R:{r} G:{g} B:{b})"
        choices.append((label, hex_color))

    return choices


def generate_lut_color_dropdown_html(
    lut_path: str, selected_color: str = None, used_colors: set = None
) -> str:
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
    colors = extract_lut_available_colors(lut_path)
    # Delegate HTML generation to palette_extension (non-invasive)
    return generate_lut_color_grid_html(colors, selected_color, used_colors)


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

    matched_rgb = preview_cache.get("matched_rgb")
    mask_solid = preview_cache.get("mask_solid")

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
        palette.append(
            {
                "color": (r, g, b),
                "hex": f"#{r:02x}{g:02x}{b:02x}",
                "count": int(count),
                "percentage": round(count / total_solid * 100, 2),
            }
        )

    # Sort by count descending
    palette.sort(key=lambda x: x["count"], reverse=True)

    return palette


# ========== Debug Helper Functions ==========


def _save_debug_preview(
    debug_data, material_matrix, mask_solid, image_path, mode_name, num_materials=4
):
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
    quantized_image = debug_data["quantized_image"]
    num_colors = debug_data["num_colors"]

    print(f"[DEBUG_PREVIEW] Saving {mode_name} debug preview...")
    print(f"[DEBUG_PREVIEW] Quantized to {num_colors} colors")

    debug_img = quantized_image.copy()

    # Draw contours to show how the vectorizer interprets shapes
    try:
        contour_overlay = debug_img.copy()

        for mat_id in range(num_materials):
            mat_mask = np.zeros(material_matrix.shape[:2], dtype=np.uint8)
            for layer in range(material_matrix.shape[2]):
                mat_mask = np.logical_or(
                    mat_mask, material_matrix[:, :, layer] == mat_id
                )

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

    debug_pil = Image.fromarray(debug_img, mode="RGB")
    debug_pil.save(debug_path, "PNG")

    print(f"[DEBUG_PREVIEW] ✅ Saved: {debug_path}")
    print(f"[DEBUG_PREVIEW] This is the EXACT image the vectorizer sees before meshing")


# ========== Main Conversion Function ==========


@dataclass(frozen=True)
class ConversionRequest:
    """Shared conversion/preview parameters to avoid deep argument forwarding.

    Notes:
        - `lut_path` supports both string file path and Gradio file-like object.
        - Some fields are preview-only (e.g. quantize/match strategy), while
          others are final-model-only (e.g. spacer/structure/loop settings).
        - `loop_pos` uses image-space coordinates `(x, y)` in pixel units.
        - `color_replacements` maps hex colors, e.g. `{"#ff0000": "#00ff00"}`.
    """

    lut_path: object  # LUT path string or Gradio file-like object
    target_width_mm: float  # Target model width in millimeters
    auto_bg: bool  # Enable automatic background removal
    bg_tol: float  # Background removal tolerance
    color_mode: ColorMode  # Color system key
    modeling_mode: ModelingMode = ModelingMode.HIGH_FIDELITY  # Engine mode
    quantize_colors: int = 64  # K-Means color count (preview + conversion)
    match_strategy: MatchStrategy = MatchStrategy.RGB_EUCLIDEAN  # Color match metric
    spacer_thick: float = 1.2  # Backing/spacer thickness in mm
    structure_mode: str = "Double-sided"  # Structure mode label
    add_loop: bool = False  # Whether to add keychain loop
    loop_width: float = 4.0  # Loop outer width in mm
    loop_length: float = 8.0  # Loop outer length in mm
    loop_hole: float = 2.5  # Loop hole diameter in mm
    loop_pos: Optional[Tuple[float, float]] = None  # Loop attach point (x, y)
    color_replacements: Optional[dict] = None  # Optional color replacement mapping


def convert_image_to_3d(
    image_path,
    request: ConversionRequest,
    blur_kernel=0,
    smooth_sigma=10,
):
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

    Returns:
        Tuple of (3mf_path, glb_path, preview_image, status_message)
    """
    # Input validation
    if image_path is None:
        return None, None, None, make_status_tag("msg_no_image")
    if request.lut_path is None:
        return None, None, None, make_status_tag("msg_no_lut")

    # Handle LUT path (supports string path or Gradio File object)
    if isinstance(request.lut_path, str):
        actual_lut_path = request.lut_path
    elif hasattr(request.lut_path, "name"):
        actual_lut_path = request.lut_path.name
    else:
        return None, None, None, make_status_tag("conv_err_invalid_lut_file")

    modeling_mode = ModelingMode(request.modeling_mode)
    target_width_mm = request.target_width_mm
    spacer_thick = request.spacer_thick
    structure_mode = request.structure_mode
    auto_bg = request.auto_bg
    bg_tol = request.bg_tol
    color_mode = request.color_mode
    add_loop = request.add_loop
    loop_width = request.loop_width
    loop_length = request.loop_length
    loop_hole = request.loop_hole
    loop_pos = request.loop_pos
    quantize_colors = request.quantize_colors
    color_replacements = request.color_replacements
    match_strategy = request.match_strategy

    print(f"[CONVERTER] Starting conversion...")
    print(
        f"[CONVERTER] Mode: {modeling_mode.get_display_name()}, Quantize: {quantize_colors}"
    )
    print(
        f"[CONVERTER] Filters: blur_kernel={blur_kernel}, smooth_sigma={smooth_sigma}"
    )
    print(f"[CONVERTER] LUT: {actual_lut_path}")

    # ========== [UPDATED] Native Vector Mode Detection ==========
    # Check if user selected vector mode AND file is SVG
    if modeling_mode == ModelingMode.VECTOR and image_path.lower().endswith(".svg"):
        print("[CONVERTER] 🎨 Using Native Vector Engine (Shapely/Clipper)...")

        try:
            from core.vector_engine import VectorProcessor

            # 1. Execute Conversion
            vec_processor = VectorProcessor(actual_lut_path, color_mode)

            # Convert SVG to 3D scene
            scene = vec_processor.svg_to_mesh(
                svg_path=image_path,
                target_width_mm=target_width_mm,
                thickness_mm=spacer_thick,
                structure_mode=structure_mode,
                color_replacements=color_replacements,
            )

            # 2. Export 3MF
            base_name = os.path.splitext(os.path.basename(image_path))[0]
            out_path = os.path.join(OUTPUT_DIR, f"{base_name}_Lumina_Vector.3mf")
            scene.export(out_path)

            # [CRITICAL FIX] Disable safe_fix_3mf_names for Vector Mode
            # Vector engine assigns names internally. External fixing causes index shifts
            # if layers are missing (e.g., skipping Green causes Yellow to be named Green).
            # safe_fix_3mf_names(out_path, color_conf['slots'])  # <-- DISABLED

            print(f"[CONVERTER] ✅ Vector 3MF exported: {out_path}")

            # 4. Generate GLB Preview
            glb_path = None
            try:
                glb_path = os.path.join(OUTPUT_DIR, f"{base_name}_Preview.glb")
                scene.export(glb_path)
                print(f"[CONVERTER] ✅ Preview GLB exported: {glb_path}")
            except Exception as e:
                print(f"[CONVERTER] Warning: Preview generation skipped: {e}")

            # 5. [FIX] Generate 2D Preview Image from SVG
            preview_img = None
            if HAS_SVG_LIB:
                try:
                    # Use SVG-safe rasterization with bounds normalization

                    preview_rgba = ImageLoader.load_svg(image_path, target_width_mm)

                    # Apply color replacements to preview if provided
                    if color_replacements:
                        from core.color_replacement import ColorReplacementManager

                        manager = ColorReplacementManager.from_dict(color_replacements)
                        replacements = manager.get_all_replacements()

                        if replacements:
                            print(
                                f"[CONVERTER] Applying {len(replacements)} color replacements to SVG preview..."
                            )

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
                                diff = np.abs(
                                    rgb_data.astype(int) - orig_arr.astype(int)
                                )
                                distance = np.sum(diff, axis=2)

                                # Match pixels within threshold (generous for SVG rasterization artifacts)
                                threshold = (
                                    50  # Increased threshold for better matching
                                )
                                match_mask = (distance < threshold) & mask_solid

                                if np.any(match_mask):
                                    rgb_data[match_mask] = repl_arr
                                    matched_count = np.sum(match_mask)
                                    print(
                                        f"[CONVERTER]   {orig_color} -> {repl_color}: {matched_count} pixels"
                                    )

                            # Update preview with replaced colors
                            preview_rgba[:, :, :3] = rgb_data
                            print(
                                f"[CONVERTER] ✅ Color replacements applied to SVG preview"
                            )

                    # Downscale overly large previews for UI performance
                    max_preview_px = 1600
                    h, w = preview_rgba.shape[:2]
                    if w > max_preview_px:
                        scale = max_preview_px / w
                        new_w = max_preview_px
                        new_h = max(1, int(h * scale))
                        preview_rgba = cv2.resize(
                            preview_rgba, (new_w, new_h), interpolation=cv2.INTER_AREA
                        )

                    # Fix black background issue: ensure transparent areas have white RGB
                    # This prevents black borders when displaying in UI
                    alpha_channel = preview_rgba[:, :, 3]
                    transparent_mask = alpha_channel == 0
                    if np.any(transparent_mask):
                        preview_rgba[transparent_mask, :3] = (
                            255  # Set RGB to white for transparent pixels
                        )

                    preview_img = preview_rgba
                    print("[CONVERTER] ✅ Generated 2D vector preview")
                except Exception as e:
                    print(f"[CONVERTER] Failed to render SVG preview: {e}")
            else:
                print("[CONVERTER] svglib not installed, skipping 2D preview")

            # Update stats
            Stats.increment("conversions")

            # Return results
            msg = make_status_tag("conv_vector_conversion_complete")
            return out_path, glb_path, preview_img, msg

        except Exception as e:
            error_msg = make_status_tag("conv_vector_processing_failed", error=str(e))

            print(f"[CONVERTER] {error_msg}")
            return None, None, None, error_msg

    # If vector mode selected but file is not SVG, show warning
    if modeling_mode == ModelingMode.VECTOR and not image_path.lower().endswith(".svg"):
        return (
            None,
            None,
            None,
            make_status_tag("conv_vector_mode_requires_svg"),
        )

    # ========== [EXISTING] Raster-based Processing ==========

    color_conf = ColorSystem.get(color_mode)
    slot_names = color_conf["slots"]
    preview_colors = color_conf["preview"]

    # Step 1: Image Processing
    try:
        processor = LuminaImageProcessor(actual_lut_path, color_mode)
        result = processor.process_image(
            image_path=image_path,
            target_width_mm=target_width_mm,
            modeling_mode=modeling_mode,
            quantize_colors=quantize_colors,
            auto_bg=auto_bg,
            bg_tol=bg_tol,
            blur_kernel=blur_kernel,
            smooth_sigma=smooth_sigma,
            match_strategy=match_strategy,
        )
    except Exception as e:
        return (
            None,
            None,
            None,
            make_status_tag("conv_image_processing_failed", error=str(e)),
        )

    matched_rgb = result["matched_rgb"]
    material_matrix = result["material_matrix"]
    mask_solid = result["mask_solid"]
    target_w, target_h = result["dimensions"]
    pixel_scale = result["pixel_scale"]
    mode_info = result["mode_info"]
    debug_data = result.get("debug_data", None)

    # Apply color replacements if provided
    if color_replacements:
        from core.color_replacement import ColorReplacementManager

        manager = ColorReplacementManager.from_dict(color_replacements)
        matched_rgb = manager.apply_to_image(matched_rgb)
        print(f"[CONVERTER] Applied {len(manager)} color replacements")

    print(
        f"[CONVERTER] Image processed: {target_w}×{target_h}px, scale={pixel_scale}mm/px"
    )

    # Step 2: Save Debug Preview (High-Fidelity mode only)
    if debug_data is not None and mode_info["mode"] == ModelingMode.HIGH_FIDELITY:
        try:
            num_materials = len(slot_names)
            _save_debug_preview(
                debug_data=debug_data,
                material_matrix=material_matrix,
                mask_solid=mask_solid,
                image_path=image_path,
                mode_name=mode_info["name"],
                num_materials=num_materials,
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
            loop_pos,
            loop_width,
            loop_length,
            loop_hole,
            mask_solid,
            material_matrix,
            target_w,
            target_h,
            pixel_scale,
        )

        if loop_info:
            preview_rgba = _draw_loop_on_preview(
                preview_rgba, loop_info, color_conf, pixel_scale
            )

    preview_img = Image.fromarray(preview_rgba, mode="RGBA")

    # Step 5: Build Voxel Matrix
    full_matrix = _build_voxel_matrix(
        material_matrix, mask_solid, spacer_thick, structure_mode
    )

    total_layers = full_matrix.shape[0]
    print(f"[CONVERTER] Voxel matrix: {full_matrix.shape} (Z×H×W)")

    # Step 6: Generate 3D Meshes
    scene = trimesh.Scene()

    transform = np.eye(4)
    transform[0, 0] = pixel_scale
    transform[1, 1] = pixel_scale
    transform[2, 2] = PrinterConfig.LAYER_HEIGHT

    print(
        f"[CONVERTER] Transform: XY={pixel_scale}mm/px, Z={PrinterConfig.LAYER_HEIGHT}mm/layer"
    )

    mesher = get_mesher(modeling_mode)
    print(f"[CONVERTER] Using mesher: {mesher.__class__.__name__}")

    valid_slot_names = []
    num_materials = len(slot_names)
    print(f"[CONVERTER] Generating meshes for {num_materials} materials...")

    for mat_id in range(num_materials):
        mesh = mesher.generate_mesh(full_matrix, mat_id, target_h)
        if mesh:
            # [ROLLBACK] Removed smart simplification as per user request
            # Warning: Large models may produce huge 3MF files
            mesh.apply_transform(transform)
            mesh.visual.face_colors = preview_colors[mat_id]
            name = slot_names[mat_id]
            mesh.metadata["name"] = name
            scene.add_geometry(mesh, node_name=name, geom_name=name)
            valid_slot_names.append(name)
            print(f"[CONVERTER] Added mesh for {name}")

    # Step 7: Add Keychain Loop
    loop_added = False
    loop_thickness = total_layers * PrinterConfig.LAYER_HEIGHT

    if add_loop and loop_info is not None:
        try:
            loop_mesh = create_keychain_loop(
                width_mm=loop_info["width_mm"],
                length_mm=loop_info["length_mm"],
                hole_dia_mm=loop_info["hole_dia_mm"],
                thickness_mm=loop_thickness,
                attach_x_mm=loop_info["attach_x_mm"],
                attach_y_mm=loop_info["attach_y_mm"],
            )

            if loop_mesh is not None:
                loop_mesh.visual.face_colors = preview_colors[loop_info["color_id"]]
                loop_mesh.metadata["name"] = "Keychain_Loop"
                scene.add_geometry(
                    loop_mesh, node_name="Keychain_Loop", geom_name="Keychain_Loop"
                )
                valid_slot_names.append("Keychain_Loop")
                loop_added = True
                print(f"[CONVERTER] Loop added successfully")
        except Exception as e:
            print(f"[CONVERTER] Loop creation failed: {e}")

    # ========== Step 8: Export 3MF ==========
    # 单面模式需要 X 轴镜像修正，使 3MF 输出与预览/GLB 一致
    is_single_sided = "单面" in structure_mode or "Single" in structure_mode
    if is_single_sided:
        model_width_mm = target_w * pixel_scale
        mirror_transform = np.array(
            [[-1, 0, 0, model_width_mm], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
        )
        for geom_name in list(scene.geometry.keys()):
            scene.geometry[geom_name].apply_transform(mirror_transform)

    base_name = os.path.splitext(os.path.basename(image_path))[0]
    out_path = os.path.join(OUTPUT_DIR, f"{base_name}_Lumina.3mf")
    scene.export(out_path)

    safe_fix_3mf_names(out_path, valid_slot_names)

    print(f"[CONVERTER] 3MF exported: {out_path}")

    # Step 9: Generate 3D Preview
    preview_mesh = _create_preview_mesh(matched_rgb, mask_solid, total_layers)

    if preview_mesh:
        preview_mesh.apply_transform(transform)

        if loop_added and loop_info:
            try:
                preview_loop = create_keychain_loop(
                    width_mm=loop_info["width_mm"],
                    length_mm=loop_info["length_mm"],
                    hole_dia_mm=loop_info["hole_dia_mm"],
                    thickness_mm=loop_thickness,
                    attach_x_mm=loop_info["attach_x_mm"],
                    attach_y_mm=loop_info["attach_y_mm"],
                )
                if preview_loop:
                    loop_color = preview_colors[loop_info["color_id"]]
                    preview_loop.visual.face_colors = [loop_color] * len(
                        preview_loop.faces
                    )
                    preview_mesh = trimesh.util.concatenate(
                        [preview_mesh, preview_loop]
                    )
            except Exception as e:
                print(f"[CONVERTER] Preview loop failed: {e}")

    if preview_mesh:
        glb_path = os.path.join(OUTPUT_DIR, f"{base_name}_Preview.glb")
        preview_mesh.export(glb_path)
    else:
        glb_path = None

    # Step 10: Generate Status Message
    Stats.increment("conversions")

    mode_name = mode_info["mode"].get_display_name()
    msg = make_status_tag(
        "conv_conversion_complete",
        mode_name=mode_name,
        target_w=target_w,
        target_h=target_h,
    )

    if loop_added and loop_info is not None:
        msg += "\n" + make_status_tag(
            "conv_loop_added", loop_material=slot_names[loop_info["color_id"]]
        )

    total_pixels = target_w * target_h
    if glb_path is None and total_pixels > 2_000_000:
        msg += "\n" + make_status_tag("msg_model_too_large")
    elif glb_path and total_pixels > 500_000:
        msg += "\n" + make_status_tag("msg_preview_simplified")

    return out_path, glb_path, preview_img, msg


# ========== Helper Functions ==========


def _calculate_loop_info(
    loop_pos,
    loop_width,
    loop_length,
    loop_hole,
    mask_solid,
    material_matrix,
    target_w,
    target_h,
    pixel_scale,
):
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
        max(0, top_row - 2) : top_row + 3, max(0, attach_col - 3) : attach_col + 4
    ]
    search_area = search_area[search_area >= 0]
    if len(search_area) > 0:
        unique, counts = np.unique(search_area, return_counts=True)
        for mat_id in unique[np.argsort(-counts)]:
            if mat_id != 0:
                loop_color_id = int(mat_id)
                break

    return {
        "attach_x_mm": attach_col * pixel_scale,
        "attach_y_mm": (target_h - 1 - top_row) * pixel_scale,
        "width_mm": loop_width,
        "length_mm": loop_length,
        "hole_dia_mm": loop_hole,
        "color_id": loop_color_id,
    }


def _draw_loop_on_preview(preview_rgba, loop_info, color_conf, pixel_scale):
    """Draw keychain loop on preview image."""
    preview_pil = Image.fromarray(preview_rgba, mode="RGBA")
    draw = ImageDraw.Draw(preview_pil)

    loop_color_rgba = tuple(color_conf["preview"][loop_info["color_id"]][:3]) + (255,)

    attach_col = int(loop_info["attach_x_mm"] / pixel_scale)
    attach_row = int(
        (preview_rgba.shape[0] - 1) - loop_info["attach_y_mm"] / pixel_scale
    )

    loop_w_px = int(loop_info["width_mm"] / pixel_scale)
    loop_h_px = int(loop_info["length_mm"] / pixel_scale)
    hole_r_px = int(loop_info["hole_dia_mm"] / 2 / pixel_scale)
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
            [loop_left, rect_top, loop_right, rect_bottom], fill=loop_color_rgba
        )

    draw.ellipse(
        [
            circle_center_x - circle_r_px,
            circle_center_y - circle_r_px,
            circle_center_x + circle_r_px,
            circle_center_y + circle_r_px,
        ],
        fill=loop_color_rgba,
    )

    draw.ellipse(
        [
            circle_center_x - hole_r_px,
            circle_center_y - hole_r_px,
            circle_center_x + hole_r_px,
            circle_center_y + hole_r_px,
        ],
        fill=(0, 0, 0, 0),
    )

    return np.array(preview_pil)


def _build_voxel_matrix(material_matrix, mask_solid, spacer_thick, structure_mode):
    """Build complete voxel matrix."""
    target_h, target_w = material_matrix.shape[:2]
    mask_transparent = ~mask_solid

    bottom_voxels = np.transpose(material_matrix, (2, 0, 1))

    spacer_layers = max(1, int(round(spacer_thick / PrinterConfig.LAYER_HEIGHT)))

    if "双面" in structure_mode or "Double" in structure_mode:
        top_voxels = np.transpose(material_matrix[..., ::-1], (2, 0, 1))
        total_layers = 5 + spacer_layers + 5
        full_matrix = np.full((total_layers, target_h, target_w), -1, dtype=int)

        full_matrix[0:5] = bottom_voxels

        spacer = np.full((target_h, target_w), -1, dtype=int)
        spacer[~mask_transparent] = 0
        for z in range(5, 5 + spacer_layers):
            full_matrix[z] = spacer

        full_matrix[5 + spacer_layers :] = top_voxels
    else:
        total_layers = 5 + spacer_layers
        full_matrix = np.full((total_layers, target_h, target_w), -1, dtype=int)

        full_matrix[0:5] = bottom_voxels

        spacer = np.full((target_h, target_w), -1, dtype=int)
        spacer[~mask_transparent] = 0
        for z in range(5, total_layers):
            full_matrix[z] = spacer

    return full_matrix


def _create_preview_mesh(matched_rgb, mask_solid, total_layers):
    """
    Create simplified 3D preview mesh for browser display.

    Args:
        matched_rgb: RGB color array
        mask_solid: Boolean mask of solid pixels
        total_layers: Total number of Z layers

    Returns:
        Trimesh object or None if model too large
    """
    height, width = matched_rgb.shape[:2]
    total_pixels = width * height

    DISABLE_THRESHOLD = 2_000_000
    SIMPLIFY_THRESHOLD = 500_000
    TARGET_PIXELS = 300_000

    if total_pixels > DISABLE_THRESHOLD:
        print(f"[PREVIEW] Model too large ({total_pixels:,} pixels)")
        print(f"[PREVIEW] 3D preview disabled to prevent crash")
        return None

    if total_pixels > SIMPLIFY_THRESHOLD:
        scale_factor = int(np.sqrt(total_pixels / TARGET_PIXELS))
        scale_factor = max(2, min(scale_factor, 16))

        print(f"[PREVIEW] Downsampling by {scale_factor}×")

        new_height = height // scale_factor
        new_width = width // scale_factor

        matched_rgb = cv2.resize(
            matched_rgb, (new_width, new_height), interpolation=cv2.INTER_AREA
        )
        mask_solid = cv2.resize(
            mask_solid.astype(np.uint8),
            (new_width, new_height),
            interpolation=cv2.INTER_NEAREST,
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

            world_y = height - 1 - y
            x0, x1 = x + shrink, x + 1 - shrink
            y0, y1 = world_y + shrink, world_y + 1 - shrink
            z0, z1 = 0, total_layers

            base_idx = len(vertices)
            vertices.extend(
                [
                    [x0, y0, z0],
                    [x1, y0, z0],
                    [x1, y1, z0],
                    [x0, y1, z0],
                    [x0, y0, z1],
                    [x1, y0, z1],
                    [x1, y1, z1],
                    [x0, y1, z1],
                ]
            )

            cube_faces = [
                [0, 2, 1],
                [0, 3, 2],
                [4, 5, 6],
                [4, 6, 7],
                [0, 1, 5],
                [0, 5, 4],
                [1, 2, 6],
                [1, 6, 5],
                [2, 3, 7],
                [2, 7, 6],
                [3, 0, 4],
                [3, 4, 7],
            ]

            for f in cube_faces:
                faces.append([v + base_idx for v in f])
                face_colors.append(rgba)

    if not vertices:
        return None

    mesh = trimesh.Trimesh(vertices=vertices, faces=faces)
    mesh.visual.face_colors = np.array(face_colors, dtype=np.uint8)

    print(
        f"[PREVIEW] Generated: {len(mesh.vertices):,} vertices, {len(mesh.faces):,} faces"
    )

    return mesh


# ========== Preview Related Functions ==========


def generate_preview_cached(
    image_path,
    request: ConversionRequest,
):
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

    Returns:
        tuple: (preview_image, cache_data, status_message)
    """
    if image_path is None:
        return None, None, make_status_tag("msg_no_image")
    if request.lut_path is None:
        return None, None, make_status_tag("msg_no_lut")

    if isinstance(request.lut_path, str):
        actual_lut_path = request.lut_path
    elif hasattr(request.lut_path, "name"):
        actual_lut_path = request.lut_path.name
    else:
        return None, None, make_status_tag("conv_err_invalid_lut_file")

    modeling_mode = ModelingMode(request.modeling_mode)
    target_width_mm = request.target_width_mm
    auto_bg = request.auto_bg
    bg_tol = request.bg_tol
    color_mode = request.color_mode
    quantize_colors = request.quantize_colors
    match_strategy = request.match_strategy

    # Clamp quantize_colors to valid range
    quantize_colors = max(8, min(256, quantize_colors))

    color_conf = ColorSystem.get(color_mode)

    try:
        processor = LuminaImageProcessor(actual_lut_path, color_mode)
        result = processor.process_image(
            image_path=image_path,
            target_width_mm=target_width_mm,
            modeling_mode=modeling_mode,
            quantize_colors=quantize_colors,  # Use user-specified value
            auto_bg=auto_bg,
            bg_tol=bg_tol,
            blur_kernel=0,
            smooth_sigma=10,
            match_strategy=match_strategy,
        )
    except Exception as e:
        return (
            None,
            None,
            make_status_tag("conv_preview_generation_failed", error=str(e)),
        )

    matched_rgb = result["matched_rgb"]
    material_matrix = result["material_matrix"]
    mask_solid = result["mask_solid"]
    target_w, target_h = result["dimensions"]

    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    preview_rgba[mask_solid, 3] = 255

    cache = {
        "target_w": target_w,
        "target_h": target_h,
        "mask_solid": mask_solid,
        "material_matrix": material_matrix,
        "matched_rgb": matched_rgb,
        "preview_rgba": preview_rgba.copy(),
        "color_conf": color_conf,
        "quantize_colors": quantize_colors,
    }

    # Extract color palette from cache
    color_palette = extract_color_palette(cache)
    cache["color_palette"] = color_palette

    display = render_preview(preview_rgba, None, 0, 0, 0, 0, False, color_conf)

    num_colors = len(color_palette)
    return (
        display,
        cache,
        make_status_tag(
            "conv_preview_generated",
            target_w=target_w,
            target_h=target_h,
            num_colors=num_colors,
        ),
    )


def render_preview(
    preview_rgba,
    loop_pos,
    loop_width,
    loop_length,
    loop_hole,
    loop_angle,
    loop_enabled,
    color_conf,
):
    """Render preview with keychain loop and coordinate grid."""
    h, w = preview_rgba.shape[:2]
    new_w, new_h = w * PREVIEW_SCALE, h * PREVIEW_SCALE

    margin = PREVIEW_MARGIN
    canvas_w = new_w + margin + margin  # Left + right margins
    canvas_h = new_h + margin + margin  # Top + bottom margins

    canvas = Image.new("RGBA", (canvas_w, canvas_h), (240, 240, 245, 255))
    draw = ImageDraw.Draw(canvas)

    grid_color = (220, 220, 225, 255)
    grid_color_main = (200, 200, 210, 255)

    grid_step = 10 * PREVIEW_SCALE
    main_step = 50 * PREVIEW_SCALE

    for x in range(margin, canvas_w, grid_step):
        draw.line([(x, margin), (x, canvas_h)], fill=grid_color, width=1)
    for y in range(margin, canvas_h, grid_step):
        draw.line([(margin, y), (canvas_w, y)], fill=grid_color, width=1)

    for x in range(margin, canvas_w, main_step):
        draw.line([(x, margin), (x, canvas_h)], fill=grid_color_main, width=1)
    for y in range(margin, canvas_h, main_step):
        draw.line([(margin, y), (canvas_w, y)], fill=grid_color_main, width=1)

    axis_color = (100, 100, 120, 255)
    draw.line([(margin, margin), (margin, canvas_h)], fill=axis_color, width=2)
    draw.line(
        [(margin, canvas_h - 1), (canvas_w, canvas_h - 1)], fill=axis_color, width=2
    )

    label_color = (80, 80, 100, 255)
    try:
        font = ImageFont.load_default()
    except:
        font = None

    for i, x in enumerate(range(margin, canvas_w, main_step)):
        px_value = i * 50
        if font:
            draw.text(
                (x - 5, canvas_h - margin + 5),
                str(px_value),
                fill=label_color,
                font=font,
            )

    for i, y in enumerate(range(margin, canvas_h, main_step)):
        px_value = i * 50
        if font:
            draw.text((5, y - 5), str(px_value), fill=label_color, font=font)

    pil_img = Image.fromarray(preview_rgba, mode="RGBA")
    pil_img = pil_img.resize((new_w, new_h), Image.Resampling.NEAREST)
    canvas.paste(
        pil_img, (margin, margin), pil_img
    )  # Paste at (margin, margin) not (margin, 0)

    if loop_enabled and loop_pos is not None:
        canvas = _draw_loop_on_canvas(
            canvas,
            loop_pos,
            loop_width,
            loop_length,
            loop_hole,
            loop_angle,
            color_conf,
            margin,
        )

    return np.array(canvas)


def _draw_loop_on_canvas(
    pil_img,
    loop_pos,
    loop_width,
    loop_length,
    loop_hole,
    loop_angle,
    color_conf,
    margin,
):
    """Draw keychain loop marker on canvas."""
    loop_w_px = int(loop_width / PrinterConfig.NOZZLE_WIDTH * PREVIEW_SCALE)
    loop_h_px = int(loop_length / PrinterConfig.NOZZLE_WIDTH * PREVIEW_SCALE)
    hole_r_px = int(loop_hole / 2 / PrinterConfig.NOZZLE_WIDTH * PREVIEW_SCALE)
    circle_r_px = loop_w_px // 2

    cx = int(loop_pos[0] * PREVIEW_SCALE) + margin
    cy = int(loop_pos[1] * PREVIEW_SCALE)

    loop_size = max(loop_w_px, loop_h_px) * 2 + 20
    loop_layer = Image.new("RGBA", (loop_size, loop_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(loop_layer)

    lc = loop_size // 2
    rect_h = max(1, loop_h_px - circle_r_px)

    loop_color = (220, 60, 60, 200)
    outline_color = (255, 255, 255, 255)

    draw.rectangle(
        [lc - loop_w_px // 2, lc, lc + loop_w_px // 2, lc + rect_h],
        fill=loop_color,
        outline=outline_color,
        width=2,
    )

    draw.ellipse(
        [lc - circle_r_px, lc - circle_r_px, lc + circle_r_px, lc + circle_r_px],
        fill=loop_color,
        outline=outline_color,
        width=2,
    )

    draw.ellipse(
        [lc - hole_r_px, lc - hole_r_px, lc + hole_r_px, lc + hole_r_px],
        fill=(0, 0, 0, 0),
    )

    if loop_angle != 0:
        loop_layer = loop_layer.rotate(
            -loop_angle, center=(lc, lc), expand=False, resample=Image.BICUBIC
        )

    paste_x = cx - lc
    paste_y = cy - lc - rect_h // 2
    pil_img.paste(loop_layer, (paste_x, paste_y), loop_layer)

    return pil_img


def on_preview_click(cache, loop_pos, evt: gr.SelectData):
    """Handle preview image click event."""
    if evt is None or cache is None:
        return (
            loop_pos,
            False,
            make_status_tag("conv_invalid_click_generate_preview_first"),
        )

    click_x, click_y = evt.index

    # 获取图像尺寸
    target_w = cache["target_w"]
    target_h = cache["target_h"]

    # 计算canvas大小
    canvas_w = target_w * PREVIEW_SCALE + PREVIEW_MARGIN + PREVIEW_MARGIN
    canvas_h = target_h * PREVIEW_SCALE + PREVIEW_MARGIN + PREVIEW_MARGIN

    # 计算Gradio缩放比例（同时考虑宽度和高度）
    gradio_display_height = 600
    gradio_display_width = 900
    scale_by_height = gradio_display_height / canvas_h
    scale_by_width = gradio_display_width / canvas_w
    gradio_scale = min(1.0, scale_by_height, scale_by_width)

    # 转换回canvas坐标
    canvas_click_x = click_x / gradio_scale
    canvas_click_y = click_y / gradio_scale

    # Remove margin offset - image starts at (margin, margin)
    click_x = canvas_click_x - PREVIEW_MARGIN
    click_y = canvas_click_y - PREVIEW_MARGIN

    orig_x = click_x / PREVIEW_SCALE
    orig_y = click_y / PREVIEW_SCALE

    orig_x = max(0, min(target_w - 1, orig_x))
    orig_y = max(0, min(target_h - 1, orig_y))

    pos_info = make_status_tag(
        "conv_loop_position", x=f"{orig_x:.1f}", y=f"{orig_y:.1f}"
    )
    return (orig_x, orig_y), True, pos_info


def update_preview_with_loop(
    cache, loop_pos, add_loop, loop_width, loop_length, loop_hole, loop_angle
):
    """Update preview image with keychain loop."""
    if cache is None:
        return None

    preview_rgba = cache["preview_rgba"].copy()
    color_conf = cache["color_conf"]

    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        add_loop,
        color_conf,
    )
    return display


def on_remove_loop():
    """Remove keychain loop."""
    return None, False, 0, make_status_tag("conv_loop_removed")


def generate_final_model(
    image_path,
    request: ConversionRequest,
):
    """
    Wrapper function for generating final model.

    Directly calls main conversion function with smart defaults:
    - blur_kernel=0 (disable median filter, preserve details)
    - smooth_sigma=10 (gentle bilateral filter, preserve edges)

    Args:
        color_replacements: Optional dict of color replacements {hex: hex}
                           e.g., {'#ff0000': '#00ff00'}
    """
    return convert_image_to_3d(
        image_path,
        request,
        blur_kernel=0,
        smooth_sigma=10,
    )


# ========== Color Replacement Functions ==========


def update_preview_with_replacements(
    cache,
    color_replacements: dict,
    loop_pos=None,
    add_loop=False,
    loop_width=4,
    loop_length=8,
    loop_hole=2.5,
    loop_angle=0,
    lang: str = "zh",
):
    """
    Update preview image with color replacements applied.

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

    Returns:
        tuple: (display_image, updated_cache, palette_html)
    """
    if cache is None:
        return None, None, ""

    from core.color_replacement import ColorReplacementManager

    # Get original matched_rgb (use stored original if available)
    original_rgb = cache.get("original_matched_rgb", cache["matched_rgb"])
    mask_solid = cache["mask_solid"]
    color_conf = cache["color_conf"]
    target_h, target_w = original_rgb.shape[:2]

    # Apply color replacements if any
    if color_replacements:
        manager = ColorReplacementManager.from_dict(color_replacements)
        matched_rgb = manager.apply_to_image(original_rgb)
    else:
        matched_rgb = original_rgb.copy()

    # Build new preview RGBA
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    preview_rgba[mask_solid, 3] = 255

    # Update cache with new data
    updated_cache = cache.copy()
    updated_cache["matched_rgb"] = matched_rgb
    updated_cache["preview_rgba"] = preview_rgba.copy()

    # Store original if not already stored
    if "original_matched_rgb" not in updated_cache:
        updated_cache["original_matched_rgb"] = original_rgb

    # Re-extract palette with new colors
    color_palette = extract_color_palette(updated_cache)
    updated_cache["color_palette"] = color_palette

    # Render display with loop if enabled
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        add_loop,
        color_conf,
    )

    # Generate palette HTML for display
    palette_html = generate_palette_html(color_palette, color_replacements, lang=lang)

    return display, updated_cache, palette_html


# generate_palette_html is now imported from ui.palette_extension


# ========== Color Highlight Functions ==========


def generate_highlight_preview(
    cache,
    highlight_color: str,
    loop_pos=None,
    add_loop=False,
    loop_width=4,
    loop_length=8,
    loop_hole=2.5,
    loop_angle=0,
):
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
        return None, make_status_tag("palette_need_preview")

    if not highlight_color:
        # No highlight - return normal preview
        preview_rgba = cache.get("preview_rgba")
        if preview_rgba is None:
            return None, make_status_tag("conv_err_invalid_cache")

        color_conf = cache["color_conf"]
        display = render_preview(
            preview_rgba,
            loop_pos if add_loop else None,
            loop_width,
            loop_length,
            loop_hole,
            loop_angle,
            add_loop,
            color_conf,
        )
        return display, make_status_tag("conv_preview_restored")

    # Parse highlight color
    highlight_hex = highlight_color.strip().lower()
    if not highlight_hex.startswith("#"):
        highlight_hex = "#" + highlight_hex

    # Convert hex to RGB
    try:
        r = int(highlight_hex[1:3], 16)
        g = int(highlight_hex[3:5], 16)
        b = int(highlight_hex[5:7], 16)
        highlight_rgb = np.array([r, g, b], dtype=np.uint8)
    except (ValueError, IndexError):
        return None, make_status_tag("conv_err_invalid_color", color=highlight_color)

    # Get data from cache
    matched_rgb = cache.get("matched_rgb")
    mask_solid = cache.get("mask_solid")
    color_conf = cache.get("color_conf")

    if matched_rgb is None or mask_solid is None:
        return None, make_status_tag("conv_err_incomplete_cache")

    target_h, target_w = matched_rgb.shape[:2]

    # Create highlight mask - pixels matching the highlight color
    color_match = np.all(matched_rgb == highlight_rgb, axis=2)
    highlight_mask = color_match & mask_solid

    # Count highlighted pixels
    highlight_count = np.sum(highlight_mask)
    total_solid = np.sum(mask_solid)

    if highlight_count == 0:
        return None, make_status_tag("conv_color_not_found", color=highlight_hex)

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
            preview_rgba[border_mask, 0] = 0  # R
            preview_rgba[border_mask, 1] = 255  # G
            preview_rgba[border_mask, 2] = 255  # B
            preview_rgba[border_mask, 3] = 200  # Alpha
    except Exception as e:
        print(f"[HIGHLIGHT] Border effect skipped: {e}")

    # Render display
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        add_loop,
        color_conf,
    )

    return (
        display,
        make_status_tag(
            "conv_highlight_result",
            color=highlight_hex,
            percent=highlight_percentage,
            pixels=f"{highlight_count:,}",
        ),
    )


def clear_highlight_preview(
    cache,
    loop_pos=None,
    add_loop=False,
    loop_width=4,
    loop_length=8,
    loop_hole=2.5,
    loop_angle=0,
):
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
    print(
        f"[CLEAR_HIGHLIGHT] Called with cache={cache is not None}, loop_pos={loop_pos}, add_loop={add_loop}"
    )

    if cache is None:
        print("[CLEAR_HIGHLIGHT] Cache is None!")
        return None, make_status_tag("palette_need_preview")

    preview_rgba = cache.get("preview_rgba")
    if preview_rgba is None:
        print("[CLEAR_HIGHLIGHT] preview_rgba is None!")
        return None, make_status_tag("conv_err_invalid_cache")

    print(f"[CLEAR_HIGHLIGHT] preview_rgba shape: {preview_rgba.shape}")

    color_conf = cache["color_conf"]
    display = render_preview(
        preview_rgba,
        loop_pos if add_loop else None,
        loop_width,
        loop_length,
        loop_hole,
        loop_angle,
        add_loop,
        color_conf,
    )

    print(
        f"[CLEAR_HIGHLIGHT] display shape: {display.shape if display is not None else None}"
    )

    return display, make_status_tag("conv_preview_restored")


# [新增] 预览图点击吸取颜色并高亮
def on_preview_click_select_color(cache, evt: gr.SelectData):
    """
    预览图点击事件处理：吸取颜色并高亮显示
    1. 识别点击位置的颜色
    2. 生成该颜色的高亮预览图
    3. 返回颜色信息给 UI
    """
    if cache is None:
        return (
            None,
            make_status_tag("palette_not_selected"),
            None,
            make_status_tag("palette_need_preview"),
        )

    if evt is None or evt.index is None:
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            make_status_tag("conv_invalid_click"),
        )

    # 1. 获取点击坐标（Gradio返回的是显示图像上的像素坐标）
    display_click_x, display_click_y = evt.index

    # 2. 获取原始图像尺寸和canvas尺寸
    target_w = cache.get("target_w")
    target_h = cache.get("target_h")

    if target_w is None or target_h is None:
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            make_status_tag("conv_err_incomplete_cache"),
        )

    # 3. 计算canvas的实际尺寸（包含margin和scale）
    canvas_w = target_w * PREVIEW_SCALE + PREVIEW_MARGIN * 2
    canvas_h = target_h * PREVIEW_SCALE + PREVIEW_MARGIN * 2

    # 4. Gradio Image组件设置了height=600，会自动缩放图像以适应显示
    # 计算Gradio的缩放比例
    gradio_display_height = 600  # 从ui/layout_new.py中的height参数

    # Gradio会保持宽高比缩放，取较小的缩放比例
    gradio_scale = min(1.0, gradio_display_height / canvas_h)

    # 5. 将显示坐标转换回canvas坐标
    canvas_click_x = display_click_x / gradio_scale
    canvas_click_y = display_click_y / gradio_scale

    # 6. 移除margin得到缩放后图像上的坐标
    scaled_img_x = canvas_click_x - PREVIEW_MARGIN
    scaled_img_y = canvas_click_y - PREVIEW_MARGIN

    # 7. 除以PREVIEW_SCALE得到原始图像坐标
    orig_x = int(scaled_img_x / PREVIEW_SCALE)
    orig_y = int(scaled_img_y / PREVIEW_SCALE)

    matched_rgb = cache.get("matched_rgb")
    mask_solid = cache.get("mask_solid")
    if matched_rgb is None or mask_solid is None:
        return (
            None,
            make_status_tag("palette_not_selected"),
            None,
            make_status_tag("conv_err_invalid_cache"),
        )

    h, w = matched_rgb.shape[:2]

    # 检查坐标是否越界
    if not (0 <= orig_x < w and 0 <= orig_y < h):
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            make_status_tag("conv_click_invalid_area", x=orig_x, y=orig_y),
        )

    # 检查是否点击了透明/背景区域
    if not mask_solid[orig_y, orig_x]:
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            make_status_tag("conv_click_background"),
        )

    # 2. 获取像素颜色
    rgb = matched_rgb[orig_y, orig_x]
    hex_color = f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"

    print(f"[CLICK] Coords: ({orig_x}, {orig_y}), Color: {hex_color}")

    # 3. 立即生成高亮预览（强制关闭挂孔显示）
    display_img, status_msg = generate_highlight_preview(
        cache, highlight_color=hex_color, add_loop=False
    )

    # 返回:
    # 1. 更新后的预览图 (高亮模式)
    # 2. "已选颜色"显示文本
    # 3. "已选颜色"内部状态变量
    # 4. 状态栏消息
    if display_img is None:
        return (
            gr.update(),
            make_status_tag("conv_selected_color_at_click", color=hex_color),
            hex_color,
            status_msg,
        )
    return (
        display_img,
        make_status_tag("conv_selected_color_at_click", color=hex_color),
        hex_color,
        status_msg,
    )


def generate_lut_grid_html(lut_path, lang: str = "zh"):
    """
    生成 LUT 可用颜色的 HTML 网格
    """
    from core.i18n import I18n

    colors = extract_lut_available_colors(lut_path)

    if not colors:
        return f"<div style='color:orange'>LUT 文件无效或为空</div>"

    count = len(colors)

    html = f"""
    <div class="lut-grid-container">
        <div style="margin-bottom: 8px; font-size: 12px; color: #666;">
            可用颜色: {count} 种
        </div>
        <div style="
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
        hex_val = entry["hex"]
        r, g, b = entry["color"]
        rgb_val = f"R:{r} G:{g} B:{b}"

        html += f"""
        <div class="lut-swatch lut-color-swatch"
             data-color="{hex_val}"
             style="background-color: {hex_val}; width:24px; height:24px; cursor:pointer; border:1px solid #ddd; border-radius:3px;"
             title="{hex_val} ({rgb_val})">
        </div>
        """

    html += "</div></div>"
    return html


# ========== Auto-detection Functions ==========


def detect_lut_color_mode(lut_path):
    """
    自动检测LUT文件的颜色模式

    Args:
        lut_path: LUT文件路径

    Returns:
        str: 颜色模式枚举值（用于 UI Radio 的 value）
    """
    if not lut_path or not os.path.exists(lut_path):
        return None

    try:
        lut_data = np.load(lut_path)
        total_colors = (
            lut_data.shape[0] * lut_data.shape[1]
            if lut_data.ndim >= 2
            else len(lut_data)
        )

        print(
            f"[AUTO_DETECT] LUT shape: {lut_data.shape}, total colors: {total_colors}"
        )

        # 8色模式：2738色 (8^5 = 32768, 但实际智能选择2738)
        if total_colors >= 2600 and total_colors <= 2800:
            print(f"[AUTO_DETECT] Detected 8-Color mode (2738 colors)")
            return ColorMode.EIGHT_COLOR_MAX.value

        # 6色模式：1296色 (6^5 = 7776, 但实际选择1296)
        elif total_colors >= 1200 and total_colors <= 1400:
            print(f"[AUTO_DETECT] Detected 6-Color mode (1296 colors)")
            return ColorMode.SIX_COLOR.value

        # 4色模式：1024色 (4^5 = 1024)
        elif total_colors >= 900 and total_colors <= 1100:
            print(
                f"[AUTO_DETECT] Detected 4-Color mode (1024 colors) - keeping current selection"
            )
            return None  # 不自动切换4色模式，保持用户选择

        else:
            print(f"[AUTO_DETECT] Unknown LUT format with {total_colors} colors")
            return None

    except Exception as e:
        print(f"[AUTO_DETECT] Error detecting LUT mode: {e}")
        return None


def detect_image_type(image_path):
    """
    自动检测图像类型并返回推荐的建模模式

    Args:
        image_path: 图像文件路径

    Returns:
        str: 建模模式 ("🎨 High-Fidelity (Smooth)", "📐 SVG Mode") 或 None
    """
    if not image_path:
        return None

    try:
        # 检查文件扩展名
        ext = os.path.splitext(image_path)[1].lower()

        if ext == ".svg":
            print(f"[AUTO_DETECT] SVG file detected, recommending SVG Mode")
            return "📐 SVG Mode"
        else:
            print(f"[AUTO_DETECT] Raster image detected ({ext}), keeping current mode")
            return None  # 不自动切换光栅图像模式

    except Exception as e:
        print(f"[AUTO_DETECT] Error detecting image type: {e}")
        return None
