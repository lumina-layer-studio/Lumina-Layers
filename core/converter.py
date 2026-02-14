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
from typing import List, Dict, Tuple, Optional

from config import (
    PrinterConfig,
    ColorMode,
    ColorSystem,
    ModelingMode,
    StructureMode,
    MatchStrategy,
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

# ========== Debug Helper Functions ==========
# ========== Color Palette Functions ==========


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
    structure_mode: StructureMode = StructureMode.DOUBLE_SIDED  # Structure mode
    add_loop: bool = False  # Whether to add keychain loop
    loop_width: float = 4.0  # Loop outer width in mm
    loop_length: float = 8.0  # Loop outer length in mm
    loop_hole: float = 2.5  # Loop hole diameter in mm
    loop_pos: Optional[Tuple[float, float]] = None  # Loop attach point (x, y)
    color_replacements: Optional[dict] = None  # Optional color replacement mapping


def _run_vector_svg_flow(image_path, actual_lut_path, request: ConversionRequest):
    """Run vector-only SVG conversion flow."""
    target_width_mm = request.target_width_mm
    spacer_thick = request.spacer_thick
    structure_mode = request.structure_mode
    color_mode = request.color_mode
    color_replacements = request.color_replacements

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
                            diff = np.abs(rgb_data.astype(int) - orig_arr.astype(int))
                            distance = np.sum(diff, axis=2)

                            # Match pixels within threshold (generous for SVG rasterization artifacts)
                            threshold = 50  # Increased threshold for better matching
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
                            "[CONVERTER] ✅ Color replacements applied to SVG preview"
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


def _run_raster_flow(
    image_path,
    actual_lut_path,
    request: ConversionRequest,
    modeling_mode: ModelingMode,
    blur_kernel,
    smooth_sigma,
):
    """Run raster conversion flow."""
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
    is_single_sided = structure_mode == StructureMode.SINGLE_SIDED
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
    quantize_colors = request.quantize_colors

    print(f"[CONVERTER] Starting conversion...")
    print(
        f"[CONVERTER] Mode: {modeling_mode.get_display_name()}, Quantize: {quantize_colors}"
    )
    print(
        f"[CONVERTER] Filters: blur_kernel={blur_kernel}, smooth_sigma={smooth_sigma}"
    )
    print(f"[CONVERTER] LUT: {actual_lut_path}")

    # ========== Native Vector Mode Detection ==========
    # Check if user selected vector mode AND file is SVG
    if modeling_mode == ModelingMode.VECTOR and image_path.lower().endswith(".svg"):
        return _run_vector_svg_flow(image_path, actual_lut_path, request)

    # If vector mode selected but file is not SVG, show warning
    if modeling_mode == ModelingMode.VECTOR and not image_path.lower().endswith(".svg"):
        return (
            None,
            None,
            None,
            make_status_tag("conv_vector_mode_requires_svg"),
        )

    # ========== Raster-based Processing ==========
    return _run_raster_flow(
        image_path,
        actual_lut_path,
        request,
        modeling_mode,
        blur_kernel,
        smooth_sigma,
    )


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


def _build_voxel_matrix(
    material_matrix, mask_solid, spacer_thick, structure_mode: StructureMode
):
    """Build complete voxel matrix."""
    target_h, target_w = material_matrix.shape[:2]
    mask_transparent = ~mask_solid

    bottom_voxels = np.transpose(material_matrix, (2, 0, 1))

    spacer_layers = max(1, int(round(spacer_thick / PrinterConfig.LAYER_HEIGHT)))

    if structure_mode == StructureMode.DOUBLE_SIDED:
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

