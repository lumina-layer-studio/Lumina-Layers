"""Translate generation requests into the existing worker parameter contract."""

from api.schemas.converter import ConvertGenerateRequest


def build_common_generation_params(request: ConvertGenerateRequest) -> dict:
    """Build options shared by whole-image, tiled, and puzzle generation."""
    return {
        "spacer_thick": request.spacer_thick,
        "backing_infill_density_percent": request.backing_infill_density_percent,
        "structure_mode": request.structure_mode.value,
        "color_mode": request.color_mode.value,
        "loop_width": request.loop_width,
        "loop_length": request.loop_length,
        "loop_hole": request.loop_hole,
        "enable_fridge_magnet": request.enable_fridge_magnet,
        "fridge_magnets": [item.model_dump(mode="json") for item in request.fridge_magnets],
        "quantize_colors": request.quantize_colors,
        "svg_pixels_per_mm": request.svg_pixels_per_mm,
        "svg_hole_max_area_mm2": request.svg_hole_max_area_mm2,
        "svg_hole_max_width_mm": request.svg_hole_max_width_mm,
        "separate_backing": request.separate_backing,
        "enable_relief": request.enable_relief,
        "color_height_map": request.color_height_map,
        "heightmap_max_height": request.heightmap_max_height,
        "enable_cleanup": request.enable_cleanup,
        "enable_outline": request.enable_outline,
        "outline_width": request.outline_width,
        "enable_cloisonne": request.enable_cloisonne,
        "wire_width_mm": request.wire_width_mm,
        "wire_height_mm": request.wire_height_mm,
        "enable_coating": request.enable_coating,
        "coating_height_mm": request.coating_height_mm,
        "coating_material": request.coating_material.model_dump() if request.coating_material else None,
        "backing_output": request.backing_output,
        "hue_weight": request.hue_weight,
        "chroma_gate": request.chroma_gate,
        "printer_id": request.printer_id,
        "slicer": request.slicer,
        "nozzle_size": request.nozzle_size,
        "device_profile_id": request.device_profile_id,
        "build_plate_id": request.build_plate_id,
        "external_spool_material": request.external_spool_material,
        "native_filament_profiles": dict(request.native_filament_profiles),
        "enable_base_layer_height_modifier": request.enable_base_layer_height_modifier,
        "enable_wipe_tower_auto_placement": request.enable_wipe_tower_auto_placement,
    }


def build_generation_worker_params(request: ConvertGenerateRequest) -> dict:
    """Add whole-image options; cache paths and per-tile policy stay with callers."""
    return {
        **build_common_generation_params(request),
        "color_layers": request.color_layers,
        "layer_height_mm": request.layer_height_mm,
        "model_enable": request.model_enable,
        "model_only": request.model_only,
        "model_threshold": request.model_threshold,
        "model_margin": request.model_margin,
        "add_loop": request.add_loop,
        "loop_pos": request.loop_pos,
        "loop_angle": request.loop_angle,
        "loop_offset_x": request.loop_offset_x,
        "loop_offset_y": request.loop_offset_y,
        "loop_position_preset": request.loop_position_preset,
        "svg_hole_compensation_enabled": request.svg_hole_compensation_enabled,
        "use_lut_constrained": request.use_lut_constrained,
        "auto_dynamic_range": request.auto_dynamic_range,
        "high_precision_3d_preview": request.high_precision_3d_preview,
        "custom_3mf_template_id": request.custom_3mf_template_id,
    }
