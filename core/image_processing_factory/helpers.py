"""
Helper Classes for Image Processing

These classes contain common functionality extracted from
LuminaImageProcessor to avoid code duplication.

Classes:
- ImageLoader: Handles image loading and scaling
- LUTManager: Manages LUT data and KD-Tree operations
- ColorMatcher: Performs color matching operations
"""

from typing import Tuple, Optional
import numpy as np
from PIL import Image
from scipy.spatial import KDTree
import cv2


class ImageLoader:
    """
    Helper class for image loading operations.

    Handles:
    - SVG rendering (if libraries available)
    - Bitmap loading
    - Resolution calculation
    - Aspect ratio preservation
    """

    @staticmethod
    def load_svg(svg_path: str, target_width_mm: float) -> np.ndarray:
        """
        Load and render SVG file.

        Args:
            svg_path: Path to SVG file
            target_width_mm: Target width in millimeters

        Returns:
            RGBA image array (H, W, 4)

        Raises:
            ImportError: If svglib/reportlab not installed
        """
        try:
            from svglib.svglib import svg2rlg
            from reportlab.graphics import renderPM
        except ImportError:
            raise ImportError(
                "Please install 'svglib' and 'reportlab' for SVG support."
            )

        print(f"[ImageLoader] Rasterizing: {svg_path}")

        # 1. 读取 SVG
        drawing = svg2rlg(svg_path)

        # --- 步骤 A: 撑大画布 (确保内容不被切断) ---
        x1, y1, x2, y2 = drawing.getBounds()
        raw_w = x2 - x1
        raw_h = y2 - y1

        # 添加 20% 安全边距
        padding_x = raw_w * 0.2
        padding_y = raw_h * 0.2

        drawing.translate(-x1 + padding_x, -y1 + padding_y)
        drawing.width = raw_w + (padding_x * 2)
        drawing.height = raw_h + (padding_y * 2)

        # 2. 缩放
        pixels_per_mm = 20.0
        target_width_px = int(target_width_mm * pixels_per_mm)

        if raw_w > 0:
            scale_factor = target_width_px / raw_w
        else:
            scale_factor = 1.0

        drawing.scale(scale_factor, scale_factor)
        drawing.width = int(drawing.width * scale_factor)
        drawing.height = int(drawing.height * scale_factor)

        # ================== 【终极方案】双重渲染差分法 ==================
        try:
            # Pass 1: 白底渲染 (0xFFFFFF)
            # 强制不使用透明通道，完全模拟打印在白纸上的效果
            pil_white = renderPM.drawToPIL(
                drawing, bg=0xFFFFFF, configPIL={"transparent": False}
            )
            arr_white = np.array(pil_white.convert("RGB"))  # 丢弃 Alpha，只看颜色

            # Pass 2: 黑底渲染 (0x000000)
            # 强制不使用透明通道，完全模拟打印在黑纸上的效果
            pil_black = renderPM.drawToPIL(
                drawing, bg=0x000000, configPIL={"transparent": False}
            )
            arr_black = np.array(pil_black.convert("RGB"))

            # 计算差异 (Difference)
            # diff = |白底图 - 黑底图|
            # 如果像素是实心的，它挡住了背景，所以在白底和黑底上颜色一样 -> diff 为 0
            # 如果像素是透明的，它透出了背景，所以在白底是白，黑底是黑 -> diff 很大
            diff = np.abs(arr_white.astype(int) - arr_black.astype(int))
            diff_sum = np.sum(diff, axis=2)

            # 生成完美的 Alpha 掩膜
            # 只要差异小于 10，我们就认为它是实心内容 (容错处理抗锯齿边缘)
            # 这样绝对不会误伤图像内部的任何颜色
            alpha_mask = np.where(diff_sum < 10, 255, 0).astype(np.uint8)

            # 合成最终图像
            # 我们取白底图的颜色 (因为它是实心的，取黑底图也一样)，然后把算出来的 alpha 贴上去
            r, g, b = cv2.split(arr_white)
            img_final = cv2.merge([r, g, b, alpha_mask])

            # 执行安全裁切
            coords = cv2.findNonZero(alpha_mask)

            if coords is not None:
                x, y, w_rect, h_rect = cv2.boundingRect(coords)

                if w_rect > 0 and h_rect > 0:
                    print(f"[SVG] Dual-Pass Crop: {w_rect}x{h_rect} (Safe & Clean)")

                    # 留 2 像素边缘
                    pad = 2
                    y_start = max(0, y - pad)
                    y_end = min(img_final.shape[0], y + h_rect + pad)
                    x_start = max(0, x - pad)
                    x_end = min(img_final.shape[1], x + w_rect + pad)

                    img_final = img_final[y_start:y_end, x_start:x_end]
                else:
                    print("[SVG] Warning: Content too small.")
            else:
                print("[SVG] Warning: Image appears fully transparent.")

            print(
                f"[SVG] Final resolution: {img_final.shape[1]}x{img_final.shape[0]} px"
            )
            return img_final

        except Exception as e:
            print(f"[SVG] Dual-Pass failed: {e}")
            import traceback

            traceback.print_exc()

            # 最后的保底：如果双重渲染失败，回退到普通渲染
            pil_img = renderPM.drawToPIL(
                drawing, bg=None, configPIL={"transparent": True}
            )
            return np.array(pil_img.convert("RGBA"))

    @staticmethod
    def load_bitmap(image_path: str) -> Image.Image:
        """
        Load bitmap image.

        Args:
            image_path: Path to image file

        Returns:
            PIL Image in RGBA mode
        """
        img = Image.open(image_path).convert("RGBA")

        # Debug info
        print(f"[ImageLoader] Original image: {image_path}")
        print(f"[ImageLoader] Image mode: {Image.open(image_path).mode}")
        print(f"[ImageLoader] Image size: {Image.open(image_path).size}")

        # Check alpha channel
        original_img = Image.open(image_path)
        has_alpha = original_img.mode in ("RGBA", "LA") or (
            original_img.mode == "P" and "transparency" in original_img.info
        )
        print(f"[ImageLoader] Has alpha channel: {has_alpha}")

        if has_alpha and original_img.mode != "RGBA":
            original_img = original_img.convert("RGBA")

        if has_alpha:
            alpha_data = np.array(original_img)[:, :, 3]
            print(
                f"[ImageLoader] Alpha stats: min={alpha_data.min()}, max={alpha_data.max()}, mean={alpha_data.mean():.1f}"
            )
            print(
                f"[ImageLoader] Transparent pixels (alpha<10): {np.sum(alpha_data < 10)}"
            )

        return img

    @staticmethod
    def calculate_target_dimensions(
        img: Image.Image, target_width_mm: float, modeling_mode: str
    ) -> Tuple[int, int, float]:
        """
        Calculate target dimensions and pixel scale.

        Args:
            img: Source image
            target_width_mm: Target width in millimeters
            modeling_mode: Processing mode ('high-fidelity', 'pixel', 'vector')

        Returns:
            Tuple of (target_w, target_h, pixel_to_mm_scale)
        """
        from config import PrinterConfig, ModelingMode

        if modeling_mode == ModelingMode.VECTOR:
            # Vector mode: 20 px/mm (ultra-high-fidelity)
            PIXELS_PER_MM = 20.0
            target_w = int(target_width_mm * PIXELS_PER_MM)
            pixel_to_mm_scale = 1.0 / PIXELS_PER_MM
        elif modeling_mode == ModelingMode.HIGH_FIDELITY:
            # High-fidelity mode: 10 px/mm
            PIXELS_PER_MM = 10
            target_w = int(target_width_mm * PIXELS_PER_MM)
            pixel_to_mm_scale = 1.0 / PIXELS_PER_MM
        else:
            # Pixel mode: based on nozzle width
            target_w = int(target_width_mm / PrinterConfig.NOZZLE_WIDTH)
            pixel_to_mm_scale = PrinterConfig.NOZZLE_WIDTH

        target_h = int(target_w * img.height / img.width)

        print(
            f"[ImageLoader] Target: {target_w}×{target_h}px ({target_w * pixel_to_mm_scale:.1f}×{target_h * pixel_to_mm_scale:.1f}mm)"
        )

        return target_w, target_h, pixel_to_mm_scale


class LUTManager:
    """
    Helper class for LUT management.

    Handles:
    - LUT loading and validation
    - KD-Tree construction
    - Color data access
    """

    def __init__(self, lut_rgb: np.ndarray, ref_stacks: np.ndarray, kdtree: KDTree):
        """
        Initialize LUT manager.

        Args:
            lut_rgb: LUT RGB colors (N, 3)
            ref_stacks: Reference stacking sequences (N, 5)
            kdtree: KD-Tree for color matching
        """
        self.lut_rgb = lut_rgb
        self.ref_stacks = ref_stacks
        self.kdtree = kdtree

    @classmethod
    def from_strategy(cls, strategy, lut_path: str) -> "LUTManager":
        """
        Create LUT manager from a color mode strategy.

        Args:
            strategy: ColorModeStrategy instance
            lut_path: Path to LUT file

        Returns:
            LUTManager instance
        """
        lut_rgb, ref_stacks, kdtree = strategy.load_lut(lut_path)
        return cls(lut_rgb, ref_stacks, kdtree)

    def query(self, colors: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Query KD-Tree for nearest colors.

        Args:
            colors: RGB colors to query (N, 3)

        Returns:
            Tuple of (distances, indices)
        """
        return self.kdtree.query(colors)

    def get_rgb(self, indices: np.ndarray) -> np.ndarray:
        """
        Get RGB colors by indices.

        Args:
            indices: Color indices

        Returns:
            RGB colors array
        """
        return self.lut_rgb[indices]

    def get_stacks(self, indices: np.ndarray) -> np.ndarray:
        """
        Get stacking sequences by indices.

        Args:
            indices: Color indices

        Returns:
            Stacking sequences array
        """
        return self.ref_stacks[indices]


class ColorMatcher:
    """
    Helper class for color matching operations.

    Handles:
    - Batch color matching
    - Optimized lookup tables
    - Material matrix generation
    """

    @staticmethod
    def match_colors(
        unique_colors: np.ndarray,
        kdtree: KDTree,
        quantized_image: np.ndarray,
        target_h: int,
        target_w: int,
        lut_rgb: np.ndarray,
        ref_stacks: np.ndarray,
        color_layers: int,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Match quantized colors to LUT and generate material matrix.

        Args:
            unique_colors: Unique colors in quantized image (N, 3)
            kdtree: KD-Tree for color matching
            quantized_image: Quantized image (H, W, 3)
            target_h: Target height
            target_w: Target width
            lut_rgb: LUT RGB colors
            ref_stacks: Reference stacking sequences
            color_layers: Number of color layers

        Returns:
            Tuple of (matched_rgb, material_matrix)
        """
        from config import PrinterConfig

        print("[ColorMatcher] Matching colors to LUT...")
        _, unique_indices = kdtree.query(unique_colors.astype(float))

        # Build color lookup table
        print("[ColorMatcher] Building color lookup table...")

        unique_codes = (
            unique_colors[:, 0].astype(np.int32) * 65536
            + unique_colors[:, 1].astype(np.int32) * 256
            + unique_colors[:, 2].astype(np.int32)
        )

        sort_idx = np.argsort(unique_codes)
        sorted_codes = unique_codes[sort_idx]
        sorted_lut_indices = unique_indices[sort_idx]

        # Map all pixels
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

        return matched_rgb, material_matrix
