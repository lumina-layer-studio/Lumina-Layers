# -*- coding: utf-8 -*-
"""
Preview Cache 构建模块

从图像处理结果构建 preview_rgba 和 cache 字典。
"""

from __future__ import annotations

import numpy as np

from config import BedManager


def build_preview_rgba(
    matched_rgb: np.ndarray,
    mask_solid: np.ndarray,
    target_w: int,
    target_h: int,
) -> np.ndarray:
    """从匹配后的 RGB 和实体掩码构建 RGBA 预览图。

    Args:
        matched_rgb: 匹配后的 RGB 图像 (H, W, 3)
        mask_solid: 实体掩码 (H, W)
        target_w: 目标宽度（像素）
        target_h: 目标高度（像素）

    Returns:
        RGBA 预览图 (H, W, 4)，背景透明
    """
    preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
    preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
    preview_rgba[mask_solid, 3] = 255
    return preview_rgba


def build_preview_cache(
    matched_rgb: np.ndarray,
    material_matrix: np.ndarray,
    mask_solid: np.ndarray,
    preview_rgba: np.ndarray,
    target_w: int,
    target_h: int,
    target_width_mm: float,
    color_conf: dict,
    color_mode: str,
    quantize_colors: int,
    backing_color_id: int,
    is_dark: bool,
    lut_metadata: dict | None,
) -> dict:
    """构建预览缓存字典。

    Args:
        matched_rgb: 匹配后的 RGB 图像 (H, W, 3)
        material_matrix: 材料矩阵
        mask_solid: 实体掩码 (H, W)
        preview_rgba: RGBA 预览图 (H, W, 4)
        target_w: 目标宽度（像素）
        target_h: 目标高度（像素）
        target_width_mm: 目标宽度 (mm)
        color_conf: 颜色系统配置
        color_mode: 颜色模式字符串
        quantize_colors: 量化颜色数
        backing_color_id: 底板颜色 ID
        is_dark: 是否深色主题
        lut_metadata: LUT 元数据

    Returns:
        缓存字典
    """
    return {
        "target_w": target_w,
        "target_h": target_h,
        "target_width_mm": target_width_mm,
        "mask_solid": mask_solid,
        "material_matrix": material_matrix,
        "matched_rgb": matched_rgb,
        "preview_rgba": preview_rgba.copy(),
        "color_conf": color_conf,
        "color_mode": color_mode,
        "quantize_colors": quantize_colors,
        "backing_color_id": backing_color_id,
        "is_dark": is_dark,
        "bed_label": BedManager.DEFAULT_BED,
        "lut_metadata": lut_metadata,
    }
