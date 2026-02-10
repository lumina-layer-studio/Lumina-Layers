"""
Processing Mode Strategies

Each strategy handles image processing for a specific modeling mode:
- HighFidelityStrategy: High-quality mode with filtering and K-Means quantization
- PixelStrategy: Pixel art mode with direct color matching
- VectorStrategy: Vector/SVG mode with ultra-high-fidelity processing
"""

from abc import ABC, abstractmethod
from typing import Tuple, Dict, Any
import numpy as np
import cv2
from scipy.spatial import KDTree

from config import PrinterConfig, MatchStrategy


class ProcessingModeStrategy(ABC):
    """
    Abstract base class for processing mode strategies.

    Each strategy is responsible for:
    1. Determining resolution (pixels per mm)
    2. Applying filters (if applicable)
    3. Performing color quantization (if applicable)
    4. Matching colors to LUT
    """

    @abstractmethod
    def get_resolution(self, target_width_mm: float) -> Tuple[int, int, float]:
        """
        Calculate target resolution based on width.

        Args:
            target_width_mm: Target width in millimeters

        Returns:
            Tuple of (target_w, target_h, pixel_to_mm_scale)
        """
        pass

    def process(
        self,
        rgb_arr: np.ndarray,
        target_h: int,
        target_w: int,
        lut_rgb: np.ndarray,
        ref_stacks: np.ndarray,
        kdtree: KDTree,
        quantize_colors: int,
        blur_kernel: int,
        smooth_sigma: float,
        match_strategy: MatchStrategy = MatchStrategy.RGB_EUCLIDEAN,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Dict[str, Any]]:
        """Process image with high-fidelity pipeline."""
        import time

        total_start = time.time()

        print(f"[HighFidelityStrategy] Starting edge-preserving processing...")

        # Step 1: Bilateral filter (edge-preserving smoothing)
        t0 = time.time()
        if smooth_sigma > 0:
            print(
                f"[HighFidelityStrategy] Applying bilateral filter (sigma={smooth_sigma})..."
            )
            rgb_processed = cv2.bilateralFilter(
                rgb_arr.astype(np.uint8),
                d=9,
                sigmaColor=smooth_sigma,
                sigmaSpace=smooth_sigma,
            )
        else:
            print(f"[HighFidelityStrategy] Bilateral filter disabled (sigma=0)")
            rgb_processed = rgb_arr.astype(np.uint8)
        print(
            f"[HighFidelityStrategy] [TIME] Bilateral filter: {time.time() - t0:.2f}s"
        )

        # Step 2: Optional median filter
        t0 = time.time()
        if blur_kernel > 0:
            kernel_size = blur_kernel if blur_kernel % 2 == 1 else blur_kernel + 1
            print(
                f"[HighFidelityStrategy] Applying median blur (kernel={kernel_size})..."
            )
            rgb_processed = cv2.medianBlur(rgb_processed, kernel_size)
        else:
            print(f"[HighFidelityStrategy] Median blur disabled (kernel=0)")
        print(f"[HighFidelityStrategy] [TIME] Median blur: {time.time() - t0:.2f}s")

        # Step 3: Skip sharpening to prevent noise amplification
        print(f"[HighFidelityStrategy] Skipping sharpening to reduce noise...")
        rgb_sharpened = rgb_processed

        # Step 4: K-Means quantization with pre-scaling optimization
        h, w = rgb_sharpened.shape[:2]
        total_pixels = h * w

        KMEANS_PIXEL_THRESHOLD = 500_000

        t0 = time.time()
        if total_pixels > KMEANS_PIXEL_THRESHOLD:
            # Pre-scaling optimization for large images
            scale_factor = np.sqrt(total_pixels / KMEANS_PIXEL_THRESHOLD)
            small_h = int(h / scale_factor)
            small_w = int(w / scale_factor)

            print(
                f"[HighFidelityStrategy] 🚀 Pre-scaling optimization: {w}×{h} → {small_w}×{small_h}"
            )

            rgb_small = cv2.resize(
                rgb_sharpened, (small_w, small_h), interpolation=cv2.INTER_AREA
            )

            pixels_small = rgb_small.reshape(-1, 3).astype(np.float32)
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 0.5)
            flags = cv2.KMEANS_PP_CENTERS

            t_kmeans = time.time()
            print(
                f"[HighFidelityStrategy] K-Means++ on downscaled image ({quantize_colors} colors)..."
            )
            _, _, centers = cv2.kmeans(
                pixels_small, quantize_colors, None, criteria, 5, flags
            )
            print(
                f"[HighFidelityStrategy] [TIME] K-Means: {time.time() - t_kmeans:.2f}s"
            )

            # Map centers to full image using KDTree
            t_map = time.time()
            print(f"[HighFidelityStrategy] Mapping centers to full image...")
            centers = centers.astype(np.float32)
            pixels_full = rgb_sharpened.reshape(-1, 3).astype(np.float32)

            centers_tree = KDTree(centers)
            _, labels = centers_tree.query(pixels_full)
            print(
                f"[HighFidelityStrategy] [TIME] KDTree query: {time.time() - t_map:.2f}s"
            )

            centers = centers.astype(np.uint8)
            quantized_pixels = centers[labels]
            quantized_image = quantized_pixels.reshape(h, w, 3)

            print(f"[HighFidelityStrategy] ✅ Pre-scaling optimization complete!")
        else:
            # Direct K-Means for smaller images
            print(
                f"[HighFidelityStrategy] K-Means++ quantization to {quantize_colors} colors..."
            )
            pixels = rgb_sharpened.reshape(-1, 3).astype(np.float32)
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
            flags = cv2.KMEANS_PP_CENTERS

            _, labels, centers = cv2.kmeans(
                pixels, quantize_colors, None, criteria, 10, flags
            )

            centers = centers.astype(np.uint8)
            quantized_pixels = centers[labels.flatten()]
            quantized_image = quantized_pixels.reshape(h, w, 3)
        print(
            f"[HighFidelityStrategy] [TIME] Total quantization: {time.time() - t0:.2f}s"
        )

        # Post-quantization cleanup
        t0 = time.time()
        print(f"[HighFidelityStrategy] Applying post-quantization cleanup...")
        quantized_image = cv2.medianBlur(quantized_image, 3)
        print(
            f"[HighFidelityStrategy] [TIME] Post-quantization cleanup: {time.time() - t0:.2f}s"
        )

        # Find unique colors
        t0 = time.time()
        unique_colors = np.unique(quantized_image.reshape(-1, 3), axis=0)
        print(f"[HighFidelityStrategy] Found {len(unique_colors)} unique colors")
        print(
            f"[HighFidelityStrategy] [TIME] Find unique colors: {time.time() - t0:.2f}s"
        )

        # Match to LUT
        t0 = time.time()
        print(
            f"[HighFidelityStrategy] Matching colors to LUT with {match_strategy} strategy..."
        )
        if match_strategy == MatchStrategy.RGB_EUCLIDEAN:
            _, unique_indices = kdtree.query(unique_colors.astype(float))
        elif match_strategy == MatchStrategy.DELTAE2000:
            from core.color_matchers import match_colors_deltae2000

            unique_indices = match_colors_deltae2000(unique_colors, lut_rgb)
        else:
            raise ValueError(
                f"Invalid match_strategy: {match_strategy}. Valid values: {list(MatchStrategy)}"
            )
        print(f"[HighFidelityStrategy] [TIME] LUT matching: {time.time() - t0:.2f}s")

        # Build color lookup table and map
        t0 = time.time()
        print(f"[HighFidelityStrategy] Building color lookup table...")

        unique_codes = (
            unique_colors[:, 0].astype(np.int32) * 65536
            + unique_colors[:, 1].astype(np.int32) * 256
            + unique_colors[:, 2].astype(np.int32)
        )

        sort_idx = np.argsort(unique_codes)
        sorted_codes = unique_codes[sort_idx]
        sorted_lut_indices = unique_indices[sort_idx]

        flat_quantized = quantized_image.reshape(-1, 3)
        pixel_codes = (
            flat_quantized[:, 0].astype(np.int32) * 65536
            + flat_quantized[:, 1].astype(np.int32) * 256
            + flat_quantized[:, 2].astype(np.int32)
        )

        insert_positions = np.searchsorted(sorted_codes, pixel_codes)
        lut_indices_for_pixels = sorted_lut_indices[insert_positions]

        matched_rgb = lut_rgb[lut_indices_for_pixels].reshape(target_h, target_w, 3)
        material_matrix = ref_stacks[lut_indices_for_pixels].reshape(
            target_h, target_w, PrinterConfig.COLOR_LAYERS
        )
        print(f"[HighFidelityStrategy] [TIME] Color mapping: {time.time() - t0:.2f}s")

        print(
            f"[HighFidelityStrategy] [OK] Total processing time: {time.time() - total_start:.2f}s"
        )

        # Prepare debug data
        debug_data = {
            "quantized_image": quantized_image.copy(),
            "num_colors": len(unique_colors),
            "bilateral_filtered": rgb_processed.copy(),
            "sharpened": rgb_sharpened.copy(),
            "filter_settings": {
                "blur_kernel": blur_kernel,
                "smooth_sigma": smooth_sigma,
            },
        }

        return matched_rgb, material_matrix, quantized_image, debug_data

    def get_mode_name(self) -> str:
        return "High-Fidelity"


class HighFidelityStrategy(ProcessingModeStrategy):
    """
    Strategy for high-fidelity mode.

    Features:
    - High resolution (10 px/mm)
    - Edge-preserving bilateral filtering
    - Optional median denoising
    - K-Means color quantization
    - Smart color mapping with lookup table optimization
    """

    def get_resolution(self, target_width_mm: float) -> Tuple[int, int, float]:
        """Calculate resolution for high-fidelity mode (10 px/mm)."""
        target_w = int(target_width_mm * 10)
        pixel_to_mm_scale = 0.1
        return target_w, None, pixel_to_mm_scale

    def get_mode_name(self) -> str:
        return "High-Fidelity"


class PixelStrategy(ProcessingModeStrategy):
    """
    Strategy for pixel art mode.

    Features:
    - Nozzle-width resolution
    - Direct pixel-level color matching
    - No filtering or quantization
    """

    def get_resolution(self, target_width_mm: float) -> Tuple[int, int, float]:
        """Calculate resolution for pixel mode (based on nozzle width)."""
        target_w = int(target_width_mm / PrinterConfig.NOZZLE_WIDTH)
        pixel_to_mm_scale = PrinterConfig.NOZZLE_WIDTH
        return target_w, None, pixel_to_mm_scale

    def process(
        self,
        rgb_arr: np.ndarray,
        target_h: int,
        target_w: int,
        lut_rgb: np.ndarray,
        ref_stacks: np.ndarray,
        kdtree: KDTree,
        quantize_colors: int,
        blur_kernel: int,
        smooth_sigma: float,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Dict[str, Any]]:
        """Process image with direct pixel matching."""
        print(f"[PixelStrategy] Direct pixel-level matching...")

        flat_rgb = rgb_arr.reshape(-1, 3)
        _, indices = kdtree.query(flat_rgb)

        matched_rgb = lut_rgb[indices].reshape(target_h, target_w, 3)
        material_matrix = ref_stacks[indices].reshape(
            target_h, target_w, PrinterConfig.COLOR_LAYERS
        )

        print(f"[PixelStrategy] Direct matching complete!")

        return matched_rgb, material_matrix, rgb_arr, None

    def get_mode_name(self) -> str:
        return "Pixel Art"


class VectorStrategy(ProcessingModeStrategy):
    """
    Strategy for vector/SVG mode.

    Features:
    - Ultra-high-fidelity (20 px/mm)
    - Super-sampling for smooth curves
    - No filtering needed (vector source is clean)
    """

    def get_resolution(self, target_width_mm: float) -> Tuple[int, int, float]:
        """Calculate resolution for vector mode (20 px/mm)."""
        PIXELS_PER_MM = 20.0
        target_w = int(target_width_mm * PIXELS_PER_MM)
        pixel_to_mm_scale = 1.0 / PIXELS_PER_MM
        return target_w, None, pixel_to_mm_scale

    def process(
        self,
        rgb_arr: np.ndarray,
        target_h: int,
        target_w: int,
        lut_rgb: np.ndarray,
        ref_stacks: np.ndarray,
        kdtree: KDTree,
        quantize_colors: int,
        blur_kernel: int,
        smooth_sigma: float,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, Dict[str, Any]]:
        """
        Process image with vector-specific pipeline.

        Note: Vector mode uses high-fidelity processing but with
        filters disabled (vector source has no noise).
        """
        # Vector mode uses high-fidelity logic but with filters pre-disabled
        # The image loading already handles super-sampling
        strategy = HighFidelityStrategy()
        return strategy.process(
            rgb_arr,
            target_h,
            target_w,
            lut_rgb,
            ref_stacks,
            kdtree,
            quantize_colors,
            blur_kernel=0,
            smooth_sigma=0,  # Force disable filters
            match_strategy=match_strategy,
        )

    def get_mode_name(self) -> str:
        return "Vector"
