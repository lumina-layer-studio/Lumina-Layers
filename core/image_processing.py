"""
Lumina Studio - Image Processing Core (Refactored with Strategy Pattern)

This module implements the refactored image processor using the Strategy Pattern
to eliminate complex if-else branching.

Architecture:
- ColorModeStrategy: Handles LUT loading for different color modes
- ProcessingModeStrategy: Handles image processing for different modeling modes
- ProcessorFactory: Assembles the correct strategies
- Helper Classes: Common utilities

The refactored LuminaImageProcessor now delegates to strategies,
making the code cleaner, more maintainable, and easier to extend.
"""

import numpy as np
from PIL import Image
from typing import Dict, Any

from config import PrinterConfig, ColorMode, ModelingMode, MatchStrategy

# Import strategies using relative imports to avoid circular dependency
from .image_processing_factory import ProcessorFactory, ImageLoader, LUTManager


class LuminaImageProcessor:
    """
    Refactored image processor class using Strategy Pattern.

    This class coordinates between color mode strategies and processing mode
    strategies to provide flexible image processing.

    The refactoring eliminates the complex if-else branching by:
    1. Delegating LUT loading to ColorModeStrategy
    2. Delegating image processing to ProcessingModeStrategy
    3. Using helper classes for common operations
    """

    def __init__(self, lut_path: str, color_mode: ColorMode):
        """
        Initialize image processor.

        Args:
            lut_path: LUT file path (.npy)
            color_mode: Color mode string (CMYW/RYBW/6-Color/8-Color)
        """
        self.color_mode = color_mode

        # Create color mode strategy
        self.color_strategy = ProcessorFactory.create_color_strategy(self.color_mode)

        # Load LUT using strategy
        print(
            f"[LuminaImageProcessor] Initializing with color mode: {self.color_mode.value}"
        )
        self.lut_manager = LUTManager.from_strategy(self.color_strategy, lut_path)

    @property
    def lut_rgb(self):
        """LUT RGB colors array (for backward compatibility)."""
        return self.lut_manager.lut_rgb

    @property
    def ref_stacks(self):
        """Reference stacking sequences array (for backward compatibility)."""
        return self.lut_manager.ref_stacks

    @property
    def kdtree(self):
        """KD-Tree for color matching (for backward compatibility)."""
        return self.lut_manager.kdtree

    def process_image(
        self,
        image_path: str,
        target_width_mm: float,
        modeling_mode: ModelingMode,
        quantize_colors: int,
        auto_bg: bool,
        bg_tol: int,
        blur_kernel: int = 0,
        smooth_sigma: float = 10,
        match_strategy: MatchStrategy = MatchStrategy.RGB_EUCLIDEAN,
    ) -> Dict[str, Any]:
        """
        Main image processing method (Refactored).

        This method now delegates to strategies and helpers, eliminating
        complex branching logic.

        Args:
            image_path: Image file path
            target_width_mm: Target width (millimeters)
            modeling_mode: Modeling mode enum
            quantize_colors: K-Means quantization color count
            auto_bg: Whether to auto-remove background
            bg_tol: Background tolerance
            blur_kernel: Median filter kernel size (0=disabled)
            smooth_sigma: Bilateral filter sigma value

        Returns:
            Dictionary containing processing results
        """
        print(f"[LuminaImageProcessor] Mode: {modeling_mode.get_display_name()}")
        print(
            f"[LuminaImageProcessor] Filter settings: blur_kernel={blur_kernel}, smooth_sigma={smooth_sigma}"
        )

        # Create processing strategy
        processing_strategy = ProcessorFactory.create_processing_strategy(modeling_mode)

        # ========== Image Loading (Delegated to ImageLoader) ==========
        is_svg = image_path.lower().endswith(".svg")

        if modeling_mode == ModelingMode.VECTOR and is_svg:
            # Vector + SVG: Ultra-high-fidelity mode
            print(
                "[LuminaImageProcessor] SVG detected - Engaging Ultra-High-Fidelity Vector Mode"
            )
            img_arr = ImageLoader.load_svg(image_path, target_width_mm)
            img = Image.fromarray(img_arr)

            # Force disable filters for vector source
            blur_kernel = 0
            smooth_sigma = 0
            print(
                "[LuminaImageProcessor] SVG Mode: Filters disabled (Vector source is clean)"
            )
            print(
                "[LuminaImageProcessor] Super-sampling at 20 px/mm eliminates jagged edges naturally"
            )

            # Get dimensions from rendered SVG
            target_w, target_h = img.size
            pixel_to_mm_scale = 0.05  # 20 px/mm
        else:
            # Bitmap loading
            img = ImageLoader.load_bitmap(image_path)

            # Calculate target dimensions using processing strategy
            target_w, target_h_none, pixel_to_mm_scale = (
                processing_strategy.get_resolution(target_width_mm)
            )
            target_h = int(target_w * img.height / img.width)

            print(
                f"[LuminaImageProcessor] Target: {target_w}×{target_h}px ({target_w * pixel_to_mm_scale:.1f}×{target_h * pixel_to_mm_scale:.1f}mm)"
            )

        # ========== Image Resizing (NEAREST interpolation) ==========
        print(f"[LuminaImageProcessor] Using NEAREST interpolation (no anti-aliasing)")
        img = img.resize((target_w, target_h), Image.Resampling.NEAREST)

        img_arr = np.array(img)
        rgb_arr = img_arr[:, :, :3]
        alpha_arr = img_arr[:, :, 3]

        # Identify transparent pixels BEFORE color processing
        mask_transparent_initial = alpha_arr < 10
        print(
            f"[LuminaImageProcessor] Found {np.sum(mask_transparent_initial)} transparent pixels (alpha<10)"
        )

        # ========== Color Processing (Delegated to ProcessingStrategy) ==========
        matched_rgb, material_matrix, bg_reference, debug_data = (
            processing_strategy.process(
                rgb_arr=rgb_arr,
                target_h=target_h,
                target_w=target_w,
                lut_rgb=self.lut_manager.lut_rgb,
                ref_stacks=self.lut_manager.ref_stacks,
                kdtree=self.lut_manager.kdtree,
                quantize_colors=quantize_colors,
                blur_kernel=blur_kernel,
                smooth_sigma=smooth_sigma,
                match_strategy=match_strategy,
            )
        )

        # ========== Background Removal ==========
        mask_transparent = mask_transparent_initial.copy()
        if auto_bg:
            bg_color = bg_reference[0, 0]
            diff = np.sum(np.abs(bg_reference - bg_color), axis=-1)
            mask_transparent = np.logical_or(mask_transparent, diff < bg_tol)

        # Apply transparency mask to material matrix
        material_matrix[mask_transparent] = -1
        mask_solid = ~mask_transparent

        # ========== Build Result ==========
        result = {
            "matched_rgb": matched_rgb,
            "material_matrix": material_matrix,
            "mask_solid": mask_solid,
            "dimensions": (target_w, target_h),
            "pixel_scale": pixel_to_mm_scale,
            "mode_info": {"mode": modeling_mode},
        }

        # Add debug data if available
        if debug_data is not None:
            result["debug_data"] = debug_data

        return result
