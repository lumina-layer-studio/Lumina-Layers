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
    generate_simulated_reference,
)

# Import image_processing (doesn't depend on converter)
from .image_processing import LuminaImageProcessor
from .mesh_generators import get_mesher, VoxelMesher, HighFidelityMesher
from .geometry_utils import create_keychain_loop


# Lazy imports to avoid circular dependency with ui/layout_new
def __getattr__(name):
    """Lazy import converter module to avoid circular dependency."""
    if name in [
        "convert_image_to_3d",
        "generate_preview_cached",
        "render_preview",
        "on_preview_click",
        "update_preview_with_loop",
        "on_remove_loop",
    ]:
        from . import converter

        return getattr(converter, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Calibration
    "generate_calibration_board",
    # Extractor
    "rotate_image",
    "draw_corner_points",
    "apply_auto_white_balance",
    "apply_brightness_correction",
    "run_extraction",
    "probe_lut_cell",
    "manual_fix_cell",
    "generate_simulated_reference",
    # Converter (public API) - lazy imported
    "convert_image_to_3d",
    "generate_preview_cached",
    "render_preview",
    "on_preview_click",
    "update_preview_with_loop",
    "on_remove_loop",
    # Refactored modules (for advanced usage)
    "LuminaImageProcessor",
    "get_mesher",
    "VoxelMesher",
    "HighFidelityMesher",
    "create_keychain_loop",
]
