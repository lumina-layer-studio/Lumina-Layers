"""
P04 — Preview cache building.
P04 — 预览缓存构建。

从 generate_preview_cached 函数搬入的逻辑，包括：
- 构建 preview_rgba（RGBA 预览图像）
- 构建 cache 字典（包含所有预览相关数据）
- 统一缓存契约：保证 quantized_image 始终可用
"""

import time
import numpy as np

from api.structured_logging import get_logger
from config import BedManager
from core.pipeline.pipeline_utils import _ensure_quantized_image_in_cache

_log = get_logger(__name__)
_DEFAULT_GLB_MAX_MESHES = 128


def run(ctx: dict) -> dict:
    """Build preview RGBA image and cache dictionary.
    构建预览 RGBA 图像和缓存字典。

    PipelineContext 输入键 / Input keys:
        - matched_rgb (np.ndarray): LUT 匹配后的 RGB 图像 (H, W, 3)
        - material_matrix (np.ndarray): 材料矩阵 (H, W, N)
        - mask_solid (np.ndarray): 实体掩码 (H, W) bool
        - target_w (int): 目标宽度（像素）
        - target_h (int): 目标高度（像素）
        - target_width_mm (float): 目标宽度（毫米）
        - color_conf (dict): 颜色系统配置
        - color_mode (str): 颜色模式字符串
        - quantize_colors (int): 量化颜色数
        - high_precision_3d_preview (bool): 是否将 GLB 颜色上限提升到量化颜色数
        - backing_color_id (int): 底板材料 ID
        - is_dark (bool): 是否深色主题
        - lut_metadata (object | None): LUT 元数据
        - debug_data (dict | None): 调试数据
        - quantized_image (np.ndarray | None): 量化后的图像

    PipelineContext 输出键 / Output keys:
        - preview_rgba (np.ndarray): RGBA 预览图像 (H, W, 4)
        - cache (dict): 预览缓存字典

    Raises:
        KeyError: 缺少必需的输入键时抛出
    """
    # ---- 读取必需输入 ----
    _t0 = time.perf_counter()
    matched_rgb = ctx['matched_rgb']
    material_matrix = ctx['material_matrix']
    mask_solid = ctx['mask_solid']
    target_w = ctx['target_w']
    target_h = ctx['target_h']
    target_width_mm = ctx['target_width_mm']
    color_layers = ctx.get('color_layers')
    layer_height_mm = ctx.get('layer_height_mm')
    model_enable = bool(ctx.get('model_enable', False))
    model_only = bool(ctx.get('model_only', False))
    model_threshold = ctx.get('model_threshold')
    model_margin = ctx.get('model_margin')
    color_conf = ctx['color_conf']
    color_mode = ctx['color_mode']
    modeling_mode = ctx.get('modeling_mode')
    quantize_colors = ctx['quantize_colors']
    enable_cleanup = bool(ctx.get('enable_cleanup', True))
    high_precision_3d_preview = bool(ctx.get('high_precision_3d_preview', False))
    svg_pixels_per_mm = ctx.get('svg_pixels_per_mm')
    hue_weight = ctx.get('hue_weight', 0.0)
    chroma_gate = ctx.get('chroma_gate', 15.0)
    use_lut_constrained = bool(ctx.get('use_lut_constrained', False))
    auto_dynamic_range = bool(ctx.get('auto_dynamic_range', False))
    material_source = ctx.get('material_source', 'lut')
    backing_color_id = ctx.get('backing_color_id', 0)
    is_dark = ctx.get('is_dark', True)
    lut_metadata = ctx.get('lut_metadata')
    debug_data = ctx.get('debug_data')
    quantized_image = ctx.get('quantized_image')
    original_quantized_image = ctx.get('original_quantized_image')
    original_matched_rgb = np.asarray(
        ctx.get('original_matched_rgb', matched_rgb),
        dtype=np.uint8,
    )
    height_identity_rgb = np.asarray(
        ctx.get('height_identity_rgb', original_matched_rgb),
        dtype=np.uint8,
    )
    original_material_matrix = np.asarray(
        ctx.get('original_material_matrix', material_matrix),
    )

    # ---- 构建 preview_rgba ----
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    preview_rgba[mask_solid, 3] = 255

    # ---- 构建 cache 字典 ----
    cache = {
        'target_w': target_w,
        'target_h': target_h,
        'target_width_mm': target_width_mm,
        'color_layers': color_layers,
        'layer_height_mm': layer_height_mm,
        'model_enable': model_enable,
        'model_only': model_only,
        'model_threshold': model_threshold,
        'model_margin': model_margin,
        'mask_solid': mask_solid,
        'material_matrix': material_matrix,
        'matched_rgb': matched_rgb,
        'original_matched_rgb': original_matched_rgb,
        'height_identity_rgb': height_identity_rgb,
        'original_material_matrix': original_material_matrix,
        'preview_rgba': preview_rgba.copy(),
        'color_conf': color_conf,
        'color_mode': color_mode,
        'modeling_mode': modeling_mode,
        'quantize_colors': quantize_colors,
        'enable_cleanup': enable_cleanup,
        'svg_pixels_per_mm': svg_pixels_per_mm,
        'hue_weight': hue_weight,
        'chroma_gate': chroma_gate,
        'use_lut_constrained': use_lut_constrained,
        'auto_dynamic_range': auto_dynamic_range,
        'material_source': material_source,
        'backing_color_id': backing_color_id,
        'is_dark': is_dark,
        'bed_label': BedManager.DEFAULT_BED,
        'lut_metadata': lut_metadata,
        'lut_match_info': ctx.get('lut_match_info'),
        # For Merged LUTs, preserve the corrected preview_colors and slot_names from P01
        'preview_colors': ctx.get('preview_colors'),
        'slot_names': ctx.get('slot_names'),
    }
    if ctx.get('pixel_scale') is not None:
        cache['pixel_scale'] = ctx['pixel_scale']
    # Preserve material solver diagnostics verbatim for preview response
    # assembly and later generation/editing stages. Fixed/LUT flows that do
    # not publish these keys retain their previous cache shape.
    # 原样保留耗材求解诊断，供预览响应与后续生成/编辑阶段使用；未发布这些键的
    # 固定层数或 LUT 流程保持原有缓存结构。
    for metadata_key in (
        "material_solver_info",
        "material_dynamic_layer_info",
        "original_material_solver_info",
        "original_material_dynamic_layer_info",
    ):
        if metadata_key in ctx:
            cache[metadata_key] = ctx[metadata_key]
    modeling_mode_value = getattr(modeling_mode, "value", modeling_mode)
    if modeling_mode_value == "pixel" or high_precision_3d_preview:
        try:
            glb_mesh_budget = int(quantize_colors)
        except (TypeError, ValueError):
            glb_mesh_budget = 0
        if glb_mesh_budget > _DEFAULT_GLB_MAX_MESHES:
            cache['glb_max_meshes'] = glb_mesh_budget

    # 统一缓存契约：保证 quantized_image 始终可用
    cache['debug_data'] = debug_data
    cache['quantized_image'] = quantized_image
    if original_quantized_image is not None:
        cache['original_quantized_image'] = original_quantized_image
    _ensure_quantized_image_in_cache(cache)

    # ---- 写入输出 ----
    ctx['preview_rgba'] = preview_rgba
    ctx['cache'] = cache
    _elapsed = time.perf_counter() - _t0
    ctx.setdefault('_preview_timings', {})['p04_s'] = _elapsed
    _log.debug(
        "cache_building done: %.3fs",
        _elapsed,
        extra={
            "event": "p04_cache_building_done",
            "duration_ms": round(_elapsed * 1000, 3),
            "width": int(target_w),
            "height": int(target_h),
            "mode": str(color_mode),
            "has_debug_data": debug_data is not None,
            "has_quantized_image": cache.get("quantized_image") is not None,
        },
    )
    return ctx
