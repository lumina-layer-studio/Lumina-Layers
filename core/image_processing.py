"""
Lumina Studio - Image Processing Core (图像处理核心)

Handles image loading, preprocessing, color quantization and matching.
处理图像加载、预处理、色彩量化和匹配。主要逻辑已抽取到 core/pipeline/processing_ops/ 子模块。
"""

import os
import time
import numpy as np
import cv2
from PIL import Image

from api.structured_logging import get_logger
from config import (
    MIN_PRINTABLE_ALPHA,
    SVG_PIXELS_PER_MM_DEFAULT,
    PrinterConfig,
    ModelingMode,
    ColorSystem,
    normalize_svg_pixels_per_mm,
)

# HEIC/HEIF support (optional dependency)
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

log = get_logger(__name__)

# ========== processing_ops 子模块导入 ==========
from core.pipeline.processing_ops.lut_loader import load_lut
from core.pipeline.processing_ops.bilateral_filter import apply_bilateral_filter
from core.pipeline.processing_ops.median_filter import apply_median_filter
from core.pipeline.processing_ops.kmeans_quantizer import quantize_colors as kmeans_quantize
from core.pipeline.processing_ops.lut_color_matcher import match_colors_to_lut, map_pixels_to_lut
from core.pipeline.processing_ops.svg_rasterizer import rasterize_svg
from core.pipeline.processing_ops.wireframe_extractor import extract_wireframe_mask
from core.pipeline.processing_ops.dynamic_range_compressor import (
    apply_auto_dynamic_range,
    compute_target_l_range,
)


def _unique_rgb_rows_fast(rgb: np.ndarray) -> np.ndarray:
    """Return unique RGB rows using a packed 24-bit representation."""

    rgb_u8 = np.ascontiguousarray(np.asarray(rgb)[:, :3], dtype=np.uint8)
    if rgb_u8.size == 0:
        return np.empty((0, 3), dtype=np.uint8)
    packed = (
        (rgb_u8[:, 0].astype(np.uint32) << 16)
        | (rgb_u8[:, 1].astype(np.uint32) << 8)
        | rgb_u8[:, 2].astype(np.uint32)
    )
    unique_packed = np.unique(packed)
    unique_rgb = np.empty((len(unique_packed), 3), dtype=np.uint8)
    unique_rgb[:, 0] = (unique_packed >> 16) & 0xFF
    unique_rgb[:, 1] = (unique_packed >> 8) & 0xFF
    unique_rgb[:, 2] = unique_packed & 0xFF
    return unique_rgb


class LuminaImageProcessor:
    """
    Image processor class — 图像处理核心类。

    主要逻辑已抽取到 processing_ops 子模块。
    Handles LUT loading, image processing, and color matching.
    """

    @staticmethod
    def _rgb_to_lab(rgb_array):
        """将 RGB 数组转换为 CIELAB 色彩空间，用于色差计算。

        Args:
            rgb_array: numpy array, shape (N, 3) 或 (H, W, 3), dtype uint8

        Returns:
            numpy array, 同输入 shape, dtype float64, Lab 色彩空间
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

    def __init__(
        self,
        lut_path,
        color_mode,
        hue_weight: float = 0.0,
        chroma_gate: float = 15.0,
        color_layers: int | None = None,
        layer_height_mm: float | None = None,
        model_enable: bool = False,
        model_only: bool = False,
        model_threshold: float | None = None,
        model_margin: float | None = None,
        use_lut_constrained: bool = False,
        auto_dynamic_range: bool = False,
        svg_pixels_per_mm: float = SVG_PIXELS_PER_MM_DEFAULT,
    ):
        """Initialize image processor.
        加载 LUT 文件并初始化图像处理器。
        Args:
            lut_path: LUT 文件路径 (.npy/.npz/.json)
            color_mode: 颜色模式字符串 (CMYW/RYBW/6-Color)
            hue_weight: 色相权重 (0.0-1.0)
            chroma_gate: 色度门限 (0-50)
            use_lut_constrained: 启用 LUT-Constrained K-Means 量化
            auto_dynamic_range: 启用自动动态范围压缩（实验性，仅作用于 L*）
            svg_pixels_per_mm: 高保真 SVG 光栅化采样密度（px/mm）
        """
        self.lut_path = lut_path
        self.color_mode = color_mode
        self.hue_weight = float(hue_weight)
        self.chroma_gate = float(chroma_gate)
        self.requested_color_layers = int(color_layers) if color_layers is not None else None
        self.requested_layer_height_mm = float(layer_height_mm) if layer_height_mm is not None else None
        self.model_enable = bool(model_enable)
        self.model_only = bool(model_only)
        self.model_threshold = float(model_threshold) if model_threshold is not None else None
        self.model_margin = float(model_margin) if model_margin is not None else None
        self.use_lut_constrained = bool(use_lut_constrained)
        self.auto_dynamic_range = bool(auto_dynamic_range)
        self.svg_pixels_per_mm = normalize_svg_pixels_per_mm(svg_pixels_per_mm)
        self.hue_matcher = None
        self.enable_cleanup = True
        self._last_unique_colors = 0
        self._last_pixel_skip_count = 0
        lut_data = self._load_lut_data()
        self._apply_lut_data(lut_data)
        self.last_match_info = self._build_initial_match_info()
        self._disable_hue_protection_for_lut_matching()
        self._init_hue_matcher()
        self._log_init_summary()

    def _disable_hue_protection_for_lut_matching(self) -> None:
        """Disable incompatible hue protection and record the requested value."""

        if not self.use_lut_constrained or self.hue_weight <= 0:
            return
        requested_hue_weight = self.hue_weight
        self.hue_weight = 0.0
        log.info(
            "Hue protection ignored for LUT-constrained matching",
            extra={
                "event": "image_processor_hue_protection_disabled",
                "requested_hue_weight": requested_hue_weight,
                "reason": "lut_constrained",
            },
        )

    def _load_lut_data(self):
        return load_lut(
            self.lut_path,
            self.color_mode,
            color_layers=self.requested_color_layers,
            layer_height_mm=self.requested_layer_height_mm,
            model_enable=self.model_enable,
            model_only=self.model_only,
            model_threshold=self.model_threshold,
            model_margin=self.model_margin,
        )

    def _apply_lut_data(self, lut_data):
        self.lut_rgb = lut_data["lut_rgb"]
        self.lut_lab = lut_data["lut_lab"]
        self.ref_stacks = lut_data["ref_stacks"]
        self.kdtree = lut_data["kdtree"]
        self.layer_count = lut_data["layer_count"]
        self.predictive_runtime = lut_data.get("predictive_runtime")
        self.predictive_modes = lut_data.get("predictive_modes", [])
        self.supported_modes = lut_data.get("supported_modes", [])
        self.source_kind = lut_data.get("source_kind", "legacy_lookup")
        self.requested_color_layers = lut_data.get("requested_color_layers", self.layer_count)
        self.requested_layer_height_mm = lut_data.get("requested_layer_height_mm")
        self.predictive_warnings = lut_data.get("predictive_warnings", [])
        self.predictive_threshold = lut_data.get("predictive_threshold")
        self.predictive_margin = lut_data.get("predictive_margin")
        self.native_reference_source = bool(lut_data.get("native_reference_source", False))

    def _build_initial_match_info(self):
        return {
            "match_mode": (
                "predictive"
                if self.predictive_runtime is not None
                and (self.model_only or self.model_enable or not self.native_reference_source)
                else "legacy"
            ),
            "source_kind": self.source_kind,
            "native_reference_source": self.native_reference_source,
            "predictive_modes": list(self.predictive_modes),
            "supported_modes": list(self.supported_modes),
            "requested_color_layers": self.requested_color_layers,
            "requested_layer_height_mm": self.requested_layer_height_mm,
            "warnings": list(self.predictive_warnings),
            "predictive_threshold": self.predictive_threshold,
            "predictive_margin": self.predictive_margin,
            "model_enable": self.model_enable,
            "model_only": self.model_only,
        }

    def _log_init_summary(self):
        log.debug(
            "Initialized LUT processor",
            extra={
                "event": "image_processor_init",
                "color_mode": self.color_mode,
                "layer_count": self.layer_count,
                "source_kind": self.source_kind,
                "match_mode": self.last_match_info.get("match_mode"),
                "hue_weight": self.hue_weight,
                "chroma_gate": self.chroma_gate,
            },
        )

    def _init_hue_matcher(self):
        """Initialize hue-aware color matcher if hue_weight > 0.
        如果 hue_weight > 0，则初始化色相感知的颜色匹配器。
        """
        if self.hue_weight > 0:
            if self.lut_rgb.size == 0 or self.lut_lab.size == 0:
                return
            from core.color_matching_hue_aware import HueAwareColorMatcher

            self.hue_matcher = HueAwareColorMatcher(
                self.lut_rgb, self.lut_lab, hue_weight=self.hue_weight, chroma_gate=self.chroma_gate
            )

    def _load_svg(self, svg_path, target_width_mm, pixels_per_mm: float = 20.0):
        """Rasterize SVG input through shared svg_rasterizer helper.
        通过 svg_rasterizer 辅助函数栅格化 SVG 输入。
        """
        return rasterize_svg(svg_path, target_width_mm, pixels_per_mm)

    def _extract_wireframe_mask(self, rgb_arr, target_w, pixel_scale, wire_width_mm=0.6):
        """Extract wireframe mask through shared wireframe_extractor helper.
        通过 wireframe_extractor 辅助函数提取线框蒙版。
        """
        return extract_wireframe_mask(rgb_arr, pixel_scale, wire_width_mm)

    def process_image(
        self,
        image_path,
        target_width_mm,
        modeling_mode,
        quantize_colors,
        blur_kernel=0,
        smooth_sigma=10,
    ):
        """Main image processing method.
        主要图像处理方法。

        Returns:
            dict with matched_rgb, material_matrix, mask_solid, dimensions,
                 pixel_scale, mode_info, quantized_image, debug_data
        """
        started = time.perf_counter()
        self._log_processing_started(modeling_mode, blur_kernel, smooth_sigma, target_width_mm)
        img, target_w, target_h, px_scale, blur_kernel, smooth_sigma = self._load_and_resize_image(
            image_path, target_width_mm, modeling_mode, blur_kernel, smooth_sigma
        )
        rgb_arr, mask_transparent = self._extract_rgba_arrays(img)
        rgb_arr = self._maybe_apply_auto_dynamic_range(rgb_arr)
        matched_rgb, material_matrix, debug_data = self._run_mode_pipeline(
            modeling_mode, rgb_arr, target_h, target_w, quantize_colors, blur_kernel, smooth_sigma
        )
        matched_rgb, material_matrix = self._apply_cleanup(modeling_mode, matched_rgb, material_matrix)
        # Result contract keys: 'matched_rgb', 'material_matrix', 'mask_solid',
        # 'dimensions', 'pixel_scale', 'mode_info', 'quantized_image'.
        result = self._finalize_process_result(
            matched_rgb,
            material_matrix,
            mask_transparent,
            target_w,
            target_h,
            px_scale,
            modeling_mode,
            rgb_arr,
            debug_data,
        )
        self._log_processing_done(started, target_w, target_h, px_scale, modeling_mode)
        return result

    def _log_processing_started(self, modeling_mode, blur_kernel, smooth_sigma, target_width_mm):
        log.debug(
            "Image processing started",
            extra={
                "event": "image_processor_started",
                "mode": modeling_mode.get_display_name(),
                "blur_kernel": blur_kernel,
                "smooth_sigma": smooth_sigma,
                "target_width_mm": target_width_mm,
            },
        )

    def _finalize_process_result(
        self,
        matched_rgb,
        material_matrix,
        mask_transparent,
        target_w,
        target_h,
        px_scale,
        modeling_mode,
        rgb_arr,
        debug_data,
    ):
        material_matrix[mask_transparent] = -1
        return self._build_process_result(
            matched_rgb,
            material_matrix,
            mask_transparent,
            target_w,
            target_h,
            px_scale,
            modeling_mode,
            rgb_arr,
            debug_data,
        )

    def _log_processing_done(self, started, target_w, target_h, px_scale, modeling_mode):
        log.info(
            "Image processing completed",
            extra={
                "event": "image_processor_done",
                "duration_ms": round((time.perf_counter() - started) * 1000, 3),
                "unique_colors": self._last_unique_colors,
                "final_size": [target_w, target_h],
                "pixel_skip_count": self._last_pixel_skip_count,
                "mode": modeling_mode.get_display_name(),
                "pixel_scale": px_scale,
                "match_mode": self.last_match_info.get("match_mode"),
            },
        )

    def _maybe_apply_auto_dynamic_range(self, rgb_arr):
        """Apply auto dynamic range compression in-place if enabled.
        若启用自动动态范围，则将输入压缩到 LUT/耗材调色板可达的 L* 区间。
        """
        if not self.auto_dynamic_range:
            return rgb_arr
        target = compute_target_l_range(getattr(self, "lut_lab", None))
        if target is None:
            log.debug(
                "Auto dynamic range skipped: no target L* range available",
                extra={
                    "event": "auto_dynamic_range_skipped",
                    "reason": "no_target_range",
                },
            )
            return rgb_arr
        target_lo, target_hi = target
        rgb_out, info = apply_auto_dynamic_range(rgb_arr, target_lo, target_hi)
        if info.get("applied"):
            log.info(
                "Auto dynamic range applied",
                extra={
                    "event": "auto_dynamic_range_applied",
                    "src_l_range": list(info.get("src_l_range") or ()),
                    "tgt_l_range": list(info.get("tgt_l_range") or ()),
                },
            )
        else:
            log.debug(
                "Auto dynamic range skipped",
                extra={
                    "event": "auto_dynamic_range_skipped",
                    "reason": info.get("reason"),
                },
            )
        return rgb_out

    def _extract_rgba_arrays(self, img):
        """Extract RGB data and transparent mask from RGBA image.
        从 RGBA 图像中提取 RGB 数据和透明蒙版。
        """
        img_arr = np.array(img)
        rgb_arr, alpha_arr = img_arr[:, :, :3], img_arr[:, :, 3]
        mask_transparent = alpha_arr < MIN_PRINTABLE_ALPHA
        transparent_count = int(np.sum(mask_transparent))
        self._last_pixel_skip_count = transparent_count
        log.debug(
            "Transparent pixels detected",
            extra={
                "event": "image_transparency_detected",
                "transparent_pixels": transparent_count,
                "alpha_threshold": 10,
            },
        )
        return rgb_arr, mask_transparent

    def _run_mode_pipeline(
        self, modeling_mode, rgb_arr, target_h, target_w, quantize_colors, blur_kernel, smooth_sigma
    ):
        """Run processing pipeline for current modeling mode.
        运行当前建模模式的处理流程。
        """
        if modeling_mode == ModelingMode.HIGH_FIDELITY:
            return self._process_high_fidelity_mode(
                rgb_arr, target_h, target_w, quantize_colors, blur_kernel, smooth_sigma
            )
        matched_rgb, material_matrix = self._process_pixel_mode(rgb_arr, target_h, target_w)
        return matched_rgb, material_matrix, None

    def _build_process_result(
        self,
        matched_rgb,
        material_matrix,
        mask_transparent,
        target_w,
        target_h,
        px_scale,
        modeling_mode,
        rgb_arr,
        debug_data,
    ):
        """Build process_image result payload.
        构建 process_image 方法的返回值。
        """
        result = {
            "matched_rgb": matched_rgb,
            "material_matrix": material_matrix,
            "mask_solid": ~mask_transparent,
            "dimensions": (target_w, target_h),
            "pixel_scale": px_scale,
            "mode_info": {
                "mode": modeling_mode,
                "lut_match_mode": self.last_match_info.get("match_mode", "legacy"),
            },
            "lut_match_info": dict(self.last_match_info),
            "quantized_image": debug_data["quantized_image"] if debug_data else rgb_arr.copy(),
        }
        if debug_data is not None:
            result["debug_data"] = debug_data
        return result

    def _apply_cleanup(self, modeling_mode, matched_rgb, material_matrix):
        """Apply isolated pixel cleanup if enabled.
        如果启用，则应用孤立像素清理。

        Runs in every high-fidelity match mode (legacy LUT lookup *and*
        predictive model matching). The palette-preserving implementation
        in :func:`core.isolated_pixel_cleanup.cleanup_isolated_pixels` no
        longer requires the LUT ``ref_stacks`` to be present, so the
        predictive-mode silent-skip that used to make this checkbox a
        no-op has been removed.
        无论经典 LUT 匹配还是预测匹配路径，只要处于高保真模式且勾选了
        清理开关就会运行；新版清理函数不再依赖 LUT ``ref_stacks``，
        因此预测匹配路径下也能生效（原先是静默跳过）。
        """
        if modeling_mode == ModelingMode.HIGH_FIDELITY and self.enable_cleanup:
            try:
                from core.isolated_pixel_cleanup import cleanup_isolated_pixels

                return cleanup_isolated_pixels(material_matrix, matched_rgb)
            except ImportError:
                log.debug(
                    "Isolated pixel cleanup module unavailable",
                    extra={"event": "isolated_pixel_cleanup_unavailable"},
                )
        return matched_rgb, material_matrix

    def _load_and_resize_image(self, image_path, target_width_mm, modeling_mode, blur_kernel, smooth_sigma):
        """加载图像并缩放到目标尺寸，对 SVG 自动禁用滤波器。
        Load image and resize to target dimensions. Returns (img, w, h, scale, blur, sigma).
        """
        is_svg = image_path.lower().endswith(".svg")
        if is_svg:
            modeling_mode_value = getattr(modeling_mode, "value", modeling_mode)
            svg_pixels_per_mm = (
                self.svg_pixels_per_mm
                if modeling_mode_value == ModelingMode.HIGH_FIDELITY.value
                else SVG_PIXELS_PER_MM_DEFAULT
            )
            log.debug(
                "SVG input detected",
                extra={
                    "event": "svg_input_detected",
                    "pixels_per_mm": svg_pixels_per_mm,
                    "mode": str(modeling_mode_value),
                },
            )
            img = Image.fromarray(
                self._load_svg(
                    image_path,
                    target_width_mm,
                    pixels_per_mm=svg_pixels_per_mm,
                )
            )
            blur_kernel, smooth_sigma = 0, 0
            log.debug(
                "SVG filters disabled",
                extra={"event": "svg_filters_disabled", "blur_kernel": blur_kernel, "smooth_sigma": smooth_sigma},
            )
            target_w, target_h = img.size[0], img.size[1]
            # The rasterizer alpha-crops canvas margins; map the cropped width to
            # the requested width like the preview GLB and preview-reuse paths.
            # 光栅化会裁掉画布边距；与预览 GLB 及预览复用路径一致，按裁后宽度映射到目标宽度。
            pixel_scale = float(target_width_mm) / float(max(1, target_w))
        else:
            img = Image.open(image_path).convert("RGBA")
            self._log_image_info(img, image_path)
            target_w, target_h, pixel_scale = self._calc_dimensions(img, target_width_mm, modeling_mode)
        log.debug(
            "Image resize interpolation selected",
            extra={"event": "image_resize_interpolation_selected", "interpolation": "nearest"},
        )
        img = img.resize((target_w, target_h), Image.Resampling.NEAREST)
        return img, target_w, target_h, pixel_scale, blur_kernel, smooth_sigma

    def _log_image_info(self, img, image_path):
        """Log image properties for debugging (reuses already-loaded image).
        记录图像属性信息，用于调试，复用已加载的图像以避免重复 I/O。

        Args:
            img (PIL.Image.Image): Already loaded RGBA image. (已加载的 RGBA 图像)
            image_path (str): Path for display only. (仅用于显示的路径)
        """
        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        extra = {
            "event": "source_image_loaded",
            "image_path": image_path,
            "image_mode": img.mode,
            "image_size": list(img.size),
            "has_alpha": has_alpha,
        }
        if has_alpha:
            alpha_img = img if img.mode == "RGBA" else img.convert("RGBA")
            alpha_data = np.array(alpha_img)[:, :, 3]
            extra.update({
                "alpha_min": int(alpha_data.min()),
                "alpha_max": int(alpha_data.max()),
                "alpha_mean": round(float(alpha_data.mean()), 3),
                "transparent_pixels": int(np.sum(alpha_data < 10)),
            })
        log.debug("Source image loaded", extra=extra)

    def _calc_dimensions(self, img, target_width_mm, modeling_mode):
        """计算目标尺寸和像素比例。 Calculate target dimensions and pixel scale."""
        if modeling_mode == ModelingMode.HIGH_FIDELITY:
            PIXELS_PER_MM = 10
            target_w = int(target_width_mm * PIXELS_PER_MM)
            pixel_scale = 1.0 / PIXELS_PER_MM
            scale_mode = "high_fidelity"
            pixels_per_mm = PIXELS_PER_MM
        else:
            target_w = int(target_width_mm / PrinterConfig.NOZZLE_WIDTH)
            pixel_scale = PrinterConfig.NOZZLE_WIDTH
            scale_mode = "pixel"
            pixels_per_mm = 1.0 / pixel_scale
        target_w = max(1, target_w)
        target_h = max(1, int(target_w * img.height / img.width))
        log.debug(
            "Image target dimensions resolved",
            extra={
                "event": "image_target_dimensions_resolved",
                "scale_mode": scale_mode,
                "pixels_per_mm": round(float(pixels_per_mm), 3),
                "target_size": [target_w, target_h],
                "target_width_mm": round(float(target_w * pixel_scale), 3),
                "target_height_mm": round(float(target_h * pixel_scale), 3),
            },
        )
        return target_w, target_h, pixel_scale

    def _process_high_fidelity_mode(self, rgb_arr, target_h, target_w, quantize_colors, blur_kernel, smooth_sigma):
        """高保真模式处理流程：bilateral -> median -> kmeans -> lut match。
        High-fidelity mode image processing with filtering, quantization and LUT matching.

        Returns:
            tuple: (matched_rgb, material_matrix, debug_data)
        """
        quantized_image, unique_colors, rgb_processed = self._prepare_high_fidelity_images(
            rgb_arr, quantize_colors, blur_kernel, smooth_sigma
        )
        unique_indices = self._match_high_fidelity_unique_colors(unique_colors)
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
        debug_data = self._build_high_fidelity_debug_data(
            quantized_image, unique_colors, rgb_processed, blur_kernel, smooth_sigma
        )
        return matched_rgb, material_matrix, debug_data

    def _prepare_high_fidelity_images(self, rgb_arr, quantize_colors, blur_kernel, smooth_sigma):
        """Run filtering + quantization and compute unique colors."""
        log.debug(
            "Edge-preserving processing started",
            extra={"event": "edge_preserving_processing_started"},
        )
        rgb_processed = apply_bilateral_filter(rgb_arr, smooth_sigma)
        rgb_processed = apply_median_filter(rgb_processed, blur_kernel)
        log.debug(
            "Sharpening skipped",
            extra={"event": "image_sharpening_skipped", "reason": "reduce_noise"},
        )
        quantized_image = kmeans_quantize(
            rgb_processed, quantize_colors,
            lut_lab=self.lut_lab if self.use_lut_constrained else None,
            lut_rgb=self.lut_rgb if self.use_lut_constrained else None,
            lut_tree=self.kdtree if self.use_lut_constrained else None,
            use_lut_constrained=self.use_lut_constrained,
        )
        t0 = time.perf_counter()
        unique_colors = _unique_rgb_rows_fast(quantized_image.reshape(-1, 3))
        self._last_unique_colors = int(len(unique_colors))
        log.debug(
            "Unique colors extracted",
            extra={
                "event": "unique_colors_extracted",
                "unique_colors": self._last_unique_colors,
                "duration_ms": round((time.perf_counter() - t0) * 1000, 3),
            },
        )
        return quantized_image, unique_colors, rgb_processed

    def _match_high_fidelity_unique_colors(self, unique_colors):
        """Match unique colors to LUT indices in high-fidelity mode."""
        log.debug(
            "High-fidelity colors matching",
            extra={
                "event": "high_fidelity_colors_matching",
                "hue_weight": self.hue_weight,
                "hue_matcher_enabled": self.hue_matcher is not None,
                "unique_colors": int(len(unique_colors)),
            },
        )
        match_result = match_colors_to_lut(
            unique_colors,
            self.lut_rgb,
            self.lut_lab,
            self.kdtree,
            self.hue_matcher,
            predictive_runtime=self.predictive_runtime,
            source_kind=self.source_kind,
            native_reference_source=self.native_reference_source,
            model_enable=self.model_enable,
            model_only=self.model_only,
            ref_stacks=self.ref_stacks,
        )
        if isinstance(match_result, dict):
            self.last_match_info = {
                "match_mode": "predictive",
                "runtime_mode_key": match_result.get("runtime_mode_key"),
                "source_kind": self.source_kind,
                "native_reference_source": self.native_reference_source,
                "predictive_modes": list(self.predictive_modes),
                "supported_modes": list(self.supported_modes),
                "requested_color_layers": self.requested_color_layers,
                "requested_layer_height_mm": self.requested_layer_height_mm,
                "warnings": list(self.predictive_warnings),
                "predictive_threshold": match_result.get("threshold"),
                "predictive_margin": match_result.get("margin"),
                "model_enable": self.model_enable,
                "model_only": self.model_only,
            }
        else:
            self.last_match_info = {
                "match_mode": "legacy",
                "source_kind": self.source_kind,
                "native_reference_source": self.native_reference_source,
                "predictive_modes": list(self.predictive_modes),
                "supported_modes": list(self.supported_modes),
                "requested_color_layers": self.requested_color_layers,
                "requested_layer_height_mm": self.requested_layer_height_mm,
                "warnings": list(self.predictive_warnings),
                "predictive_threshold": self.predictive_threshold,
                "predictive_margin": self.predictive_margin,
                "model_enable": self.model_enable,
                "model_only": self.model_only,
            }
        return match_result

    def _build_high_fidelity_debug_data(self, quantized_image, unique_colors, rgb_processed, blur_kernel, smooth_sigma):
        """Build debug payload for high-fidelity mode."""
        filtered_copy = rgb_processed.copy()
        return {
            "quantized_image": quantized_image.copy(),
            "num_colors": len(unique_colors),
            "bilateral_filtered": filtered_copy,
            "sharpened": filtered_copy,
            "filter_settings": {"blur_kernel": blur_kernel, "smooth_sigma": smooth_sigma},
        }

    def _process_pixel_mode(self, rgb_arr, target_h, target_w):
        """像素模式：去重颜色后匹配 LUT，不做平滑处理。
        Pixel art mode: deduplicate colors then match, no smoothing.

        Returns:
            tuple: (matched_rgb, material_matrix)
        """
        self._log_pixel_mode_step("start")
        flat_rgb = rgb_arr.reshape(-1, 3)
        unique_colors = np.unique(flat_rgb, axis=0)
        self._last_unique_colors = int(len(unique_colors))
        self._log_pixel_mode_step("dedup", pixel_count=len(flat_rgb), unique_count=len(unique_colors))
        unique_match = self._match_pixel_unique_colors(unique_colors)
        matched_rgb, material_matrix = map_pixels_to_lut(
            rgb_arr,
            unique_colors,
            unique_match,
            self.lut_rgb,
            self.ref_stacks,
            target_h,
            target_w,
            self.layer_count,
        )
        self._log_pixel_mode_step("complete")
        return matched_rgb, material_matrix

    def _match_pixel_unique_colors(self, unique_colors):
        unique_match = match_colors_to_lut(
            unique_colors,
            self.lut_rgb,
            self.lut_lab,
            self.kdtree,
            self.hue_matcher,
            predictive_runtime=self.predictive_runtime,
            source_kind=self.source_kind,
            native_reference_source=self.native_reference_source,
            model_enable=self.model_enable,
            model_only=self.model_only,
            ref_stacks=self.ref_stacks,
        )
        self._update_pixel_match_info(unique_match)
        return unique_match

    def _update_pixel_match_info(self, unique_match):
        if isinstance(unique_match, dict):
            self.last_match_info = {
                "match_mode": "predictive",
                "runtime_mode_key": unique_match.get("runtime_mode_key"),
                "source_kind": self.source_kind,
                "native_reference_source": self.native_reference_source,
                "predictive_modes": list(self.predictive_modes),
                "supported_modes": list(self.supported_modes),
                "requested_color_layers": self.requested_color_layers,
                "requested_layer_height_mm": self.requested_layer_height_mm,
                "warnings": list(self.predictive_warnings),
                "predictive_threshold": unique_match.get("threshold"),
                "predictive_margin": unique_match.get("margin"),
                "model_enable": self.model_enable,
                "model_only": self.model_only,
            }
            return
        self.last_match_info = self._build_initial_match_info()

    def _log_pixel_mode_step(self, step, **fields):
        messages = {
            "start": "Direct pixel-level matching started",
            "dedup": (
                "Pixel colors deduplicated"
            ),
            "complete": "Direct pixel-level matching completed",
        }
        extra = {"event": f"image_processor_pixel_mode_{step}", **fields}
        log.debug(messages[step], extra=extra)
