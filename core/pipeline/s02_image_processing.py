"""
S02 — Image processing via LuminaImageProcessor.
S02 — 通过 LuminaImageProcessor 进行图像处理。

从 convert_image_to_3d 搬入的图像处理调用逻辑，包括：
- 创建 LuminaImageProcessor 实例
- 调用 process_image 获取匹配结果
- 加载 LUT 元数据
- 提取处理结果到 PipelineContext
"""

import time
import numpy as np

from api.structured_logging import get_logger
from config import SVG_PIXELS_PER_MM_DEFAULT, ModelingMode
from core.errors import CachedPreviewAnalysisError
from core.image_processing import LuminaImageProcessor
from core.preview_analysis_cache import preview_analysis_reuse_is_required

_log = get_logger(__name__)

# Try to import LUTManager for metadata loading
try:
    from utils.lut_manager import LUTManager
except ImportError:
    LUTManager = None


def _normalize_modeling_mode(value):
    if isinstance(value, ModelingMode):
        return value
    try:
        return ModelingMode(value)
    except (TypeError, ValueError):
        return value


def _load_reused_preview_analysis(ctx: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    """Load preview arrays, failing closed when spatial edits require them.

    加载预览分析数组；若空间编辑明确要求复用，则任何缺失、损坏或结构不匹配
    都会终止生成，而不是静默回退到新的图像分析。
    """

    if not ctx.get("reuse_preview_analysis"):
        return None
    cache_is_required = preview_analysis_reuse_is_required(
        ctx.get("reuse_preview_analysis")
    )
    matched_rgb_path = ctx.get("matched_rgb_path")
    mask_solid_path = ctx.get("mask_solid_path")
    material_matrix_path = ctx.get("material_matrix_path")
    if not (matched_rgb_path and mask_solid_path and material_matrix_path):
        if cache_is_required:
            raise CachedPreviewAnalysisError(
                "Required preview analysis artifacts are incomplete"
            )
        return None
    try:
        matched_rgb = np.load(matched_rgb_path, allow_pickle=False)
        mask_solid = np.load(mask_solid_path, allow_pickle=False)
        material_matrix = np.load(material_matrix_path, allow_pickle=False)
    except (OSError, ValueError, TypeError) as exc:
        if cache_is_required:
            raise CachedPreviewAnalysisError(
                "Required preview analysis artifact is unreadable"
            ) from exc
        _log.warning(
            "Preview analysis reuse failed; falling back to image processing",
            extra={
                "event": "s02_preview_analysis_reuse_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return None

    arrays_are_well_shaped = (
        matched_rgb.ndim == 3
        and matched_rgb.shape[-1] == 3
        and mask_solid.ndim == 2
        and material_matrix.ndim == 3
        and material_matrix.shape[-1] > 0
        and matched_rgb.shape[:2] == mask_solid.shape
        and material_matrix.shape[:2] == mask_solid.shape
    )
    required_dtypes_are_valid = (
        matched_rgb.dtype == np.uint8
        and mask_solid.dtype == np.bool_
        and np.issubdtype(material_matrix.dtype, np.integer)
    )
    if not arrays_are_well_shaped or (
        cache_is_required and not required_dtypes_are_valid
    ):
        if cache_is_required:
            raise CachedPreviewAnalysisError(
                "Required preview analysis arrays are structurally incompatible"
            )
        return None
    if matched_rgb.dtype != np.uint8:
        matched_rgb = matched_rgb.astype(np.uint8, copy=False)
    if mask_solid.dtype != bool:
        mask_solid = mask_solid.astype(bool, copy=False)
    return matched_rgb, mask_solid, material_matrix


def run(ctx: dict) -> dict:
    """Process image through LuminaImageProcessor and extract results.
    通过 LuminaImageProcessor 处理图像并提取结果。

    PipelineContext 输入键 / Input keys:
        - actual_lut_path (str): 解析后的 LUT 文件路径
        - color_mode (str): 颜色模式
        - hue_weight (float): 色相权重
        - chroma_gate (float): 色度门限
        - image_path (str): 输入图像路径
        - target_width_mm (float): 目标宽度 (mm)
        - modeling_mode (ModelingMode): 建模模式
        - quantize_colors (int): 量化颜色数
        - blur_kernel (int): 中值滤波核大小
        - smooth_sigma (int): 双边滤波 sigma
        - enable_cleanup (bool): 启用孤立像素清理
        - svg_pixels_per_mm (float): 高保真 SVG 采样密度 (px/mm)

    PipelineContext 输出键 / Output keys:
        - matched_rgb (np.ndarray): (H, W, 3) uint8 匹配后的 RGB 图像
        - material_matrix (np.ndarray): (H, W, N) int 材料矩阵
        - mask_solid (np.ndarray): (H, W) bool 实体像素掩码
        - target_w (int): 目标宽度 (像素)
        - target_h (int): 目标高度 (像素)
        - pixel_scale (float): 像素比例 (mm/px)
        - mode_info (dict): 模式信息
        - debug_data (dict | None): 调试数据
        - processor (LuminaImageProcessor): 处理器实例
        - lut_metadata: LUT 元数据

    Raises:
        KeyError: 缺少必需的输入键时抛出
    """
    # ---- Material-archive branch ----
    if ctx.get("material_source") == "material_archive":
        ctx['lut_metadata'] = None
        reuse_started = time.perf_counter()
        reused_analysis = _load_reused_preview_analysis(ctx)
        if reused_analysis is not None:
            matched_rgb, mask_solid, material_matrix = reused_analysis
            target_h, target_w = mask_solid.shape
            target_width_mm = float(ctx['target_width_mm'])
            pixel_scale = (
                target_width_mm / float(target_w)
                if target_w > 0
                else 0.0
            )
            modeling_mode = _normalize_modeling_mode(ctx.get('modeling_mode'))
            ctx['matched_rgb'] = matched_rgb
            ctx['material_matrix'] = material_matrix
            ctx['mask_solid'] = mask_solid
            ctx['target_w'] = int(target_w)
            ctx['target_h'] = int(target_h)
            ctx['pixel_scale'] = pixel_scale
            ctx['mode_info'] = {
                'mode': modeling_mode,
                'lut_match_mode': 'material_archive',
            }
            ctx['debug_data'] = None
            ctx['lut_match_info'] = None
            elapsed = time.perf_counter() - reuse_started
            ctx.setdefault('_hifi_timings', {})['image_proc_s'] = elapsed
            _log.debug(
                "material archive preview analysis reused: %.3fs, "
                "%sx%spx, scale=%smm/px",
                elapsed,
                target_w,
                target_h,
                pixel_scale,
                extra={
                    "event": "s02_preview_analysis_reused",
                    "duration_ms": round(elapsed * 1000, 3),
                    "width": int(target_w),
                    "height": int(target_h),
                    "pixel_scale": pixel_scale,
                    "mode": "material_archive",
                },
            )
            return ctx

        from core.pipeline.p03_core_processing import _run_material_archive_branch

        # Preview applies portable edits in P03. Final generation owns them
        # in S03, after loading the confirmed RGB/recipe pair.
        analysis = _run_material_archive_branch({**ctx, "replacement_regions": None})
        analysis["replacement_regions"] = ctx.get("replacement_regions")
        ctx.update(analysis)
        return ctx

    actual_lut_path = ctx['actual_lut_path']
    color_mode = ctx['color_mode']
    hue_weight = ctx.get('hue_weight', 0.0)
    chroma_gate = ctx.get('chroma_gate', 15.0)
    image_path = ctx['image_path']
    target_width_mm = ctx['target_width_mm']
    modeling_mode = ctx['modeling_mode']
    quantize_colors = ctx.get('quantize_colors', 32)
    blur_kernel = ctx.get('blur_kernel', 0)
    smooth_sigma = ctx.get('smooth_sigma', 10)
    enable_cleanup = ctx.get('enable_cleanup', True)
    color_layers = ctx.get('color_layers')
    layer_height_mm = ctx.get('layer_height_mm')
    model_enable = ctx.get('model_enable', False)
    model_only = ctx.get('model_only', False)
    model_threshold = ctx.get('model_threshold')
    model_margin = ctx.get('model_margin')
    use_lut_constrained = ctx.get('use_lut_constrained', False)
    auto_dynamic_range = ctx.get('auto_dynamic_range', False)
    svg_pixels_per_mm = ctx.get('svg_pixels_per_mm', SVG_PIXELS_PER_MM_DEFAULT)

    # Load LUT metadata for palette info
    lut_metadata = None
    if LUTManager is not None:
        try:
            _, _, lut_metadata = LUTManager.load_lut_with_metadata(actual_lut_path)
        except Exception as e:
            _log.warning(
                "Warning: Failed to load LUT metadata: %s",
                e,
                extra={
                    "event": "s02_lut_metadata_load_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )

    ctx['lut_metadata'] = lut_metadata

    _reuse_t0 = time.perf_counter()
    reused_analysis = _load_reused_preview_analysis(ctx)
    if reused_analysis is not None:
        matched_rgb, mask_solid, material_matrix = reused_analysis
        target_h, target_w = mask_solid.shape
        pixel_scale = float(target_width_mm) / float(target_w) if target_w > 0 else 0.0
        modeling_mode = _normalize_modeling_mode(modeling_mode)
        try:
            processor = LuminaImageProcessor(
                actual_lut_path,
                color_mode,
                hue_weight=hue_weight,
                chroma_gate=chroma_gate,
                color_layers=color_layers,
                layer_height_mm=layer_height_mm,
                model_enable=model_enable,
                model_only=model_only,
                model_threshold=model_threshold,
                model_margin=model_margin,
                use_lut_constrained=use_lut_constrained,
                auto_dynamic_range=auto_dynamic_range,
                svg_pixels_per_mm=svg_pixels_per_mm,
            )
            processor.enable_cleanup = enable_cleanup
        except Exception as e:
            ctx['error'] = f"[ERROR] Image processing failed: {e}"
            return ctx

        ctx['matched_rgb'] = matched_rgb
        ctx['material_matrix'] = material_matrix
        ctx['mask_solid'] = mask_solid
        ctx['target_w'] = int(target_w)
        ctx['target_h'] = int(target_h)
        ctx['pixel_scale'] = pixel_scale
        ctx['mode_info'] = {'mode': modeling_mode}
        ctx['debug_data'] = None
        ctx['processor'] = processor
        ctx['lut_match_info'] = getattr(processor, 'last_match_info', None)
        _elapsed = time.perf_counter() - _reuse_t0
        ctx.setdefault('_hifi_timings', {})['image_proc_s'] = _elapsed
        _log.debug(
            "preview analysis reused: %.3fs, %sx%spx, scale=%smm/px",
            _elapsed,
            target_w,
            target_h,
            pixel_scale,
            extra={
                "event": "s02_preview_analysis_reused",
                "duration_ms": round(_elapsed * 1000, 3),
                "width": int(target_w),
                "height": int(target_h),
                "pixel_scale": pixel_scale,
                "mode": str(getattr(modeling_mode, "value", modeling_mode)),
            },
        )
        return ctx

    # Create processor and process image
    _hifi_t0 = time.perf_counter()
    try:
        processor = LuminaImageProcessor(
            actual_lut_path,
            color_mode,
            hue_weight=hue_weight,
            chroma_gate=chroma_gate,
            color_layers=color_layers,
            layer_height_mm=layer_height_mm,
            model_enable=model_enable,
            model_only=model_only,
            model_threshold=model_threshold,
            model_margin=model_margin,
            use_lut_constrained=use_lut_constrained,
            auto_dynamic_range=auto_dynamic_range,
            svg_pixels_per_mm=svg_pixels_per_mm,
        )
        processor.enable_cleanup = enable_cleanup

        result = processor.process_image(
            image_path=image_path,
            target_width_mm=target_width_mm,
            modeling_mode=modeling_mode,
            quantize_colors=quantize_colors,
            blur_kernel=blur_kernel,
            smooth_sigma=smooth_sigma
        )
    except Exception as e:
        ctx['error'] = f"[ERROR] Image processing failed: {e}"
        return ctx

    _elapsed = time.perf_counter() - _hifi_t0
    _hifi_timings = ctx.setdefault('_hifi_timings', {})
    _hifi_timings['image_proc_s'] = _elapsed

    # Extract results into context
    matched_rgb = result['matched_rgb']
    material_matrix = result['material_matrix']
    mask_solid = result['mask_solid']
    target_w, target_h = result['dimensions']

    ctx['matched_rgb'] = matched_rgb
    ctx['material_matrix'] = material_matrix
    ctx['mask_solid'] = mask_solid
    ctx['target_w'] = target_w
    ctx['target_h'] = target_h
    ctx['pixel_scale'] = result['pixel_scale']
    ctx['mode_info'] = result['mode_info']
    ctx['debug_data'] = result.get('debug_data', None)
    ctx['processor'] = processor
    ctx['lut_match_info'] = getattr(processor, 'last_match_info', None)

    _log.debug(
        "image_proc done: %.3fs, %sx%spx, scale=%smm/px",
        _elapsed,
        target_w,
        target_h,
        result["pixel_scale"],
        extra={
            "event": "s02_image_proc_done",
            "duration_ms": round(_elapsed * 1000, 3),
            "width": int(target_w),
            "height": int(target_h),
            "pixel_scale": result["pixel_scale"],
            "mode": str(getattr(modeling_mode, "value", modeling_mode)),
        },
    )

    return ctx
