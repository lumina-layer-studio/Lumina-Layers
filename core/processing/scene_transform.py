# -*- coding: utf-8 -*-
"""
Scene Transform 模块

对 trimesh.Scene 应用坐标变换（镜像/翻转），
用于不同打印结构模式和颜色模式的适配。
"""

from __future__ import annotations

import numpy as np
import trimesh


def apply_scene_transforms(
    scene: trimesh.Scene,
    target_w: int,
    pixel_scale: float,
    color_mode: str,
    structure_mode: str,
) -> None:
    """根据颜色模式和打印结构模式对 scene 应用坐标变换。

    变换规则：
    - 5-Color Extended: Z 轴翻转 + X 轴镜像
    - 单面模式 (Single-sided): X 轴镜像

    Args:
        scene: trimesh.Scene 对象（就地修改）
        target_w: 目标宽度（像素）
        pixel_scale: 像素缩放比例 (mm/px)
        color_mode: 颜色模式字符串
        structure_mode: 打印结构模式字符串
    """
    is_single_sided = "单面" in structure_mode or "Single" in structure_mode
    is_5color = "5-Color Extended" in color_mode

    # 5-Color: Z 翻转
    if is_5color:
        max_z = max(
            g.vertices[:, 2].max()
            for g in scene.geometry.values()
            if hasattr(g, "vertices") and len(g.vertices) > 0
        )
        z_flip = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0],
            [0, 0, -1, max_z],
            [0, 0, 0, 1],
        ])
        for geom_name in list(scene.geometry.keys()):
            scene.geometry[geom_name].apply_transform(z_flip)

    # 单面模式: X 轴镜像
    if is_single_sided:
        model_width_mm = target_w * pixel_scale
        mirror_transform = np.array([
            [-1, 0, 0, model_width_mm],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ])
        for geom_name in list(scene.geometry.keys()):
            scene.geometry[geom_name].apply_transform(mirror_transform)

    # 5-Color: 补充 X 镜像
    if is_5color:
        model_width_mm = target_w * pixel_scale
        x_mirror_again = np.array([
            [-1, 0, 0, model_width_mm],
            [0, 1, 0, 0],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ])
        for geom_name in list(scene.geometry.keys()):
            scene.geometry[geom_name].apply_transform(x_mirror_again)
