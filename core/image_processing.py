"""
Lumina Studio - Image Processing Core (编排层)

Handles image loading, preprocessing, color quantization and matching.
重构后的薄编排层，委托给 core/pipeline/processing_ops/ 子模块。
"""

import os
import numpy as np
import cv2
from PIL import Image

from config import PrinterConfig, ModelingMode, ColorSystem

# HEIC/HEIF support (optional dependency)
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

# ── processing_ops 子模块导入 ──────────────────────────────────────
from core.pipeline.processing_ops.lut_loader import load_lut
from core.pipeline.processing_ops.bilateral_filter import apply_bilateral_filter
from core.pipeline.processing_ops.median_filter import apply_median_filter
from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors as kmeans_quantize
from core.pipeline.processing_ops.lut_color_matcher import match_colors_to_lut, map_pixels_to_lut
from core.pipeline.processing_ops.svg_rasterizer import rasterize_svg
from core.pipeline.processing_ops.wireframe_extractor import extract_wireframe_mask


class LuminaImageProcessor:
    """
    Image processor class — 编排层。

    签名不变，内部委托给 processing_ops 子模块。
    Handles LUT loading, image processing, and color matching.
    """

    @staticmethod
    def _rgb_to_lab(rgb_array):
        """将 RGB 数组转换为 CIELAB 空间（感知均匀色彩空间）。

        Args:
            rgb_array: numpy array, shape (N, 3) 或 (H, W, 3), dtype uint8

        Returns:
            numpy array, 同 shape, dtype float64, Lab 值
        """
        original_shape = rgb_array.shape
        if rgb_array.ndim == 2:
            rgb_3d = rgb_array.reshape(1, -1, 3).astype(np.uint8)
        else:
            rgb_3d = rgb_array.astype(np.uint8)
        bgr = cv2.cvtColor(rgb_3d, cv2.COLOR_RGB2BGR)
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64)
        if len(original_shape) == 2:
            return lab.reshape(original_shape)
        return lab

    def __init__(self, lut_path, color_mode, hue_weight: float = 0.0, chroma_gate: float = 15.0):
        """Initialize image processor.
        初始化图像处理器，委托给 lut_loader 加载 LUT 数据。

        Args:
            lut_path: LUT file path (.npy/.npz/.json)
            color_mode: Color mode string (CMYW/RYBW/6-Color)
            hue_weight: 色相感知权重 (0.0-1.0)
            chroma_gate: 暗色子集彩度门槛 (0-50)
        """
        self.lut_path = lut_path
        self.color_mode = color_mode
        self.hue_weight = float(hue_weight)
        self.chroma_gate = float(chroma_gate)
        self.hue_matcher = None
        self.enable_cleanup = True
        lut_data = load_lut(lut_path, color_mode)
        self.lut_rgb = lut_data["lut_rgb"]
        self.lut_lab = lut_data["lut_lab"]
        self.ref_stacks = lut_data["ref_stacks"]
        self.kdtree = lut_data["kdtree"]
        self.layer_count = lut_data["layer_count"]
        self._init_hue_matcher()

    def _init_hue_matcher(self):
        """Initialize hue-aware color matcher if hue_weight > 0.
        仅当 hue_weight > 0 时初始化色相感知匹配器。
        """
        if self.hue_weight > 0:
            from core.color_matching_hue_aware import HueAwareColorMatcher

            self.hue_matcher = HueAwareColorMatcher(
                self.lut_rgb, self.lut_lab, hue_weight=self.hue_weight, chroma_gate=self.chroma_gate
            )

    def _load_svg(self, svg_path, target_width_mm, pixels_per_mm: float = 20.0):
        """SVG 双通道光栅化 — 委托给 svg_rasterizer。"""
        return rasterize_svg(svg_path, target_width_mm, pixels_per_mm)

    def _extract_wireframe_mask(self, rgb_arr, target_w, pixel_scale, wire_width_mm=0.6):
        """景泰蓝掐丝描边提取 — 委托给 wireframe_extractor。"""
        return extract_wireframe_mask(rgb_arr, pixel_scale, wire_width_mm)

    def process_image(
        self,
        image_path,
        target_width_mm,
        modeling_mode,
        quantize_colors,
        auto_bg,
        bg_tol,
        blur_kernel=0,
        smooth_sigma=10,
    ):
        """Main image processing method.
        主图像处理方法，编排加载、匹配、清理、背景移除。

        Returns:
            dict with matched_rgb, material_matrix, mask_solid, dimensions,
                 pixel_scale, mode_info, quantized_image, debug_data
        """
        print(
            f"[IMAGE_PROCESSOR] Mode: {modeling_mode.get_display_name()}, blur_kernel={blur_kernel}, smooth_sigma={smooth_sigma}"
        )
        img, target_w, target_h, px_scale, blur_kernel, smooth_sigma = self._load_and_resize_image(
            image_path, target_width_mm, modeling_mode, blur_kernel, smooth_sigma
        )
        img_arr = np.array(img)
        rgb_arr, alpha_arr = img_arr[:, :, :3], img_arr[:, :, 3]
        mask_transparent = alpha_arr < 10
        print(f"[IMAGE_PROCESSOR] Found {np.sum(mask_transparent)} transparent pixels (alpha<10)")
        debug_data = None
        if modeling_mode == ModelingMode.HIGH_FIDELITY:
            matched_rgb, material_matrix, bg_ref, debug_data = self._process_high_fidelity_mode(
                rgb_arr, target_h, target_w, quantize_colors, blur_kernel, smooth_sigma
            )
        else:
            matched_rgb, material_matrix, bg_ref = self._process_pixel_mode(rgb_arr, target_h, target_w)
        matched_rgb, material_matrix = self._apply_cleanup(modeling_mode, matched_rgb, material_matrix)
        if auto_bg:
            mask_transparent = np.logical_or(mask_transparent, np.sum(np.abs(bg_ref - bg_ref[0, 0]), axis=-1) < bg_tol)
        material_matrix[mask_transparent] = -1
        result = {
            "matched_rgb": matched_rgb,
            "material_matrix": material_matrix,
            "mask_solid": ~mask_transparent,
            "dimensions": (target_w, target_h),
            "pixel_scale": px_scale,
            "mode_info": {"mode": modeling_mode},
            "quantized_image": debug_data["quantized_image"] if debug_data else rgb_arr.copy(),
        }
        if debug_data is not None:
            result["debug_data"] = debug_data
        return result

    def _apply_cleanup(self, modeling_mode, matched_rgb, material_matrix):
        """孤立像素清理（高保真模式可选后处理）。Apply isolated pixel cleanup if enabled."""
        if modeling_mode == ModelingMode.HIGH_FIDELITY and self.enable_cleanup:
            try:
                from core.isolated_pixel_cleanup import cleanup_isolated_pixels

                return cleanup_isolated_pixels(material_matrix, matched_rgb, self.lut_rgb, self.ref_stacks)
            except ImportError:
                print("[IMAGE_PROCESSOR] isolated_pixel_cleanup module not found, skipping")
        return matched_rgb, material_matrix

    def _load_and_resize_image(self, image_path, target_width_mm, modeling_mode, blur_kernel, smooth_sigma):
        """加载图像（SVG 或位图）并缩放到目标尺寸。
        Load image and resize to target dimensions. Returns (img, w, h, scale, blur, sigma).
        """
        SVG_PIXELS_PER_MM = 10.0
        is_svg = image_path.lower().endswith(".svg")
        if is_svg:
            print("[IMAGE_PROCESSOR] SVG detected - Engaging Ultra-High-Fidelity Vector Mode")
            img = Image.fromarray(self._load_svg(image_path, target_width_mm, pixels_per_mm=SVG_PIXELS_PER_MM))
            blur_kernel, smooth_sigma = 0, 0
            print("[IMAGE_PROCESSOR] SVG Mode: Filters disabled (Vector source is clean)")
            target_w, target_h, pixel_scale = img.size[0], img.size[1], 1.0 / SVG_PIXELS_PER_MM
        else:
            img = Image.open(image_path).convert("RGBA")
            self._log_image_info(img, image_path)
            target_w, target_h, pixel_scale = self._calc_dimensions(img, target_width_mm, modeling_mode)
        print(f"[IMAGE_PROCESSOR] Using NEAREST interpolation (no anti-aliasing)")
        img = img.resize((target_w, target_h), Image.Resampling.NEAREST)
        return img, target_w, target_h, pixel_scale, blur_kernel, smooth_sigma

    def _log_image_info(self, img, image_path):
        """Log image properties for debugging (reuses already-loaded image).
        记录图像信息（复用已加载的图像对象，避免重复 I/O）。

        Args:
            img (PIL.Image.Image): Already loaded RGBA image. (已加载的 RGBA 图像)
            image_path (str): Path for display only. (仅用于显示的路径)
        """
        print(f"[IMAGE_PROCESSOR] Original image: {image_path}, mode: {img.mode}, size: {img.size}")
        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        print(f"[IMAGE_PROCESSOR] Has alpha channel: {has_alpha}")
        if has_alpha:
            alpha_img = img if img.mode == "RGBA" else img.convert("RGBA")
            alpha_data = np.array(alpha_img)[:, :, 3]
            print(
                f"[IMAGE_PROCESSOR] Alpha stats: min={alpha_data.min()}, max={alpha_data.max()}, "
                f"mean={alpha_data.mean():.1f}, transparent(alpha<10): {np.sum(alpha_data < 10)}"
            )

    def _calc_dimensions(self, img, target_width_mm, modeling_mode):
        """计算目标尺寸和像素比例。Calculate target dimensions and pixel scale."""
        if modeling_mode == ModelingMode.HIGH_FIDELITY:
            PIXELS_PER_MM = 10
            target_w = int(target_width_mm * PIXELS_PER_MM)
            pixel_scale = 1.0 / PIXELS_PER_MM
            print(f"[IMAGE_PROCESSOR] High-res mode: {PIXELS_PER_MM} px/mm")
        else:
            target_w = int(target_width_mm / PrinterConfig.NOZZLE_WIDTH)
            pixel_scale = PrinterConfig.NOZZLE_WIDTH
            print(f"[IMAGE_PROCESSOR] Pixel mode: {1.0/pixel_scale:.2f} px/mm")
        target_h = int(target_w * img.height / img.width)
        print(
            f"[IMAGE_PROCESSOR] Target: {target_w}x{target_h}px ({target_w*pixel_scale:.1f}x{target_h*pixel_scale:.1f}mm)"
        )
        return target_w, target_h, pixel_scale

    def _process_high_fidelity_mode(self, rgb_arr, target_h, target_w, quantize_colors, blur_kernel, smooth_sigma):
        """高保真模式：bilateral -> median -> kmeans -> lut match。
        High-fidelity mode image processing with filtering, quantization and LUT matching.

        Returns:
            tuple: (matched_rgb, material_matrix, quantized_image, debug_data)
        """
        import time

        total_start = time.time()
        print(f"[IMAGE_PROCESSOR] Starting edge-preserving processing...")
        rgb_processed = apply_bilateral_filter(rgb_arr, smooth_sigma)
        rgb_processed = apply_median_filter(rgb_processed, blur_kernel)
        print(f"[IMAGE_PROCESSOR] Skipping sharpening to reduce noise...")
        quantized_image = kmeans_quantize(rgb_processed, quantize_colors)
        t0 = time.time()
        unique_colors = np.unique(quantized_image.reshape(-1, 3), axis=0)
        print(f"[IMAGE_PROCESSOR] Found {len(unique_colors)} unique colors ({time.time() - t0:.2f}s)")
        print(f"[IMAGE_PROCESSOR] hue_weight={self.hue_weight}, hue_matcher={'YES' if self.hue_matcher else 'NONE'}")
        unique_indices = match_colors_to_lut(unique_colors, self.lut_rgb, self.lut_lab, self.kdtree, self.hue_matcher)
        matched_rgb, material_matrix = map_pixels_to_lut(
            quantized_image,
            unique_colors,
            unique_indices,
            self.lut_rgb,
            self.ref_stacks,
            target_h,
            target_w,
            self.layer_count,
        )
        print(f"[IMAGE_PROCESSOR] Total processing time: {time.time() - total_start:.2f}s")
        filtered_copy = rgb_processed.copy()
        debug_data = {
            "quantized_image": quantized_image.copy(),
            "num_colors": len(unique_colors),
            "bilateral_filtered": filtered_copy,
            "sharpened": filtered_copy,
            "filter_settings": {"blur_kernel": blur_kernel, "smooth_sigma": smooth_sigma},
        }
        return matched_rgb, material_matrix, quantized_image, debug_data

    def _process_pixel_mode(self, rgb_arr, target_h, target_w):
        """像素模式：先去重再 LUT 匹配，跳过滤波和量化。
        Pixel art mode: deduplicate colors then match, no smoothing.

        Returns:
            tuple: (matched_rgb, material_matrix, bg_reference)
        """
        print(f"[IMAGE_PROCESSOR] Direct pixel-level matching (Pixel Art mode, CIELAB space)...")
        flat_rgb = rgb_arr.reshape(-1, 3)
        unique_colors, inverse = np.unique(flat_rgb, axis=0, return_inverse=True)
        print(f"[IMAGE_PROCESSOR] Pixel dedup: {len(flat_rgb)} pixels -> {len(unique_colors)} unique colors")
        if self.hue_matcher is not None:
            print(f"[IMAGE_PROCESSOR] Hue-aware matching enabled (hue_weight={self.hue_weight})")
            unique_indices = self.hue_matcher.match_colors_batch(unique_colors, k=32)
        else:
            unique_lab = self._rgb_to_lab(unique_colors)
            _, unique_indices = self.kdtree.query(unique_lab)
        indices = unique_indices[inverse]
        matched_rgb = self.lut_rgb[indices].reshape(target_h, target_w, 3)
        material_matrix = self.ref_stacks[indices].reshape(target_h, target_w, self.layer_count)
        print(f"[IMAGE_PROCESSOR] Direct matching complete!")
        return matched_rgb, material_matrix, rgb_arr
