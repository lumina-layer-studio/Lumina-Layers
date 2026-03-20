# -*- coding: utf-8 -*-
"""
Lumina Studio - Core Module (Refactored)
核心算法模块 - 重构版本
"""

# Calibration module
from .calibration import generate_calibration_board

# Extractor module
from .extractor import (
    rotate_image,
    draw_corner_points,
    apply_auto_white_balance,
    apply_brightness_correction,
    run_extraction,
    probe_lut_cell,
    manual_fix_cell,
    generate_simulated_reference
)

# Converter module (refactored)
from .converter import (
    convert_image_to_3d,
    generate_preview_cached,
    render_preview,
    on_preview_click,
    update_preview_with_loop,
    on_remove_loop,
    generate_final_model,
    update_preview_with_backing_color
)

# New refactored modules
from .image_processing import LuminaImageProcessor
from .mesh_generators import get_mesher, VoxelMesher, HighFidelityMesher
from .geometry_utils import create_keychain_loop

__all__ = [
    # Calibration
    'generate_calibration_board',
    
    # Extractor
    'rotate_image',
    'draw_corner_points',
    'apply_auto_white_balance',
    'apply_brightness_correction',
    'run_extraction',
    'probe_lut_cell',
    'manual_fix_cell',
    'generate_simulated_reference',
    
    # Converter (public API)
    'convert_image_to_3d',
    'generate_preview_cached',
    'render_preview',
    'on_preview_click',
    'update_preview_with_loop',
    'on_remove_loop',
    'generate_final_model',
    'update_preview_with_backing_color',
    
    # Refactored modules (for advanced usage)
    'LuminaImageProcessor',
    'get_mesher',
    'VoxelMesher',
    'HighFidelityMesher',
    'create_keychain_loop',
]
