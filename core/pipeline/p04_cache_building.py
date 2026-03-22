"""
P04 — Preview cache building.
P04 — 预览缓存构建。

从 generate_preview_cached 函数搬入的逻辑，包括：
- 构建 preview_rgba（RGBA 预览图像）
- 构建 cache 字典（包含所有预览相关数据）
- 统一缓存契约：保证 quantized_image 始终可用
"""

import numpy as np

from config import BedManager
from core.pipeline.pipeline_utils import _ensure_quantized_image_in_cache


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
    matched_rgb = ctx['matched_rgb']
    material_matrix = ctx['material_matrix']
    mask_solid = ctx['mask_solid']
    target_w = ctx['target_w']
    target_h = ctx['target_h']
    target_width_mm = ctx['target_width_mm']
    color_conf = ctx['color_conf']
    color_mode = ctx['color_mode']
    quantize_colors = ctx['quantize_colors']
    backing_color_id = ctx.get('backing_color_id', 0)
    is_dark = ctx.get('is_dark', True)
    lut_metadata = ctx.get('lut_metadata')
    debug_data = ctx.get('debug_data')
    quantized_image = ctx.get('quantized_image')

    # ---- 构建 preview_rgba ----
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    preview_rgba[mask_solid, 3] = 255

    # ---- 构建 cache 字典 ----
    cache = {
        'target_w': target_w,
        'target_h': target_h,
        'target_width_mm': target_width_mm,
        'mask_solid': mask_solid,
        'material_matrix': material_matrix,
        'matched_rgb': matched_rgb,
        'preview_rgba': preview_rgba.copy(),
        'color_conf': color_conf,
        'color_mode': color_mode,
        'quantize_colors': quantize_colors,
        'backing_color_id': backing_color_id,
        'is_dark': is_dark,
        'bed_label': BedManager.DEFAULT_BED,
        'lut_metadata': lut_metadata,
        # For Merged LUTs, preserve the corrected preview_colors and slot_names from P01
        'preview_colors': ctx.get('preview_colors'),
        'slot_names': ctx.get('slot_names'),
    }

    # 统一缓存契约：保证 quantized_image 始终可用
    cache['debug_data'] = debug_data
    cache['quantized_image'] = quantized_image
    _ensure_quantized_image_in_cache(cache)

    # ---- 写入输出 ----
    ctx['preview_rgba'] = preview_rgba
    ctx['cache'] = cache
    return ctx
