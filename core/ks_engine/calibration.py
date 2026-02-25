"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                    K/S ENGINE - CALIBRATION MODULE                            ║
║                      K/S 引擎 - 校准模块                                       ║
╚═══════════════════════════════════════════════════════════════════════════════╝

This module provides calibration card generation and K/S parameter calculation
for the Chroma K/S physics engine.

Adapted from ChromaStack project:
https://github.com/borealis-zhe/ChromaStack
"""

import os
from typing import List, Tuple
import numpy as np
import trimesh


# ========== 阶梯卡生成 ==========

def create_block(
    x: float,
    y: float,
    z: float,
    w: float,
    l: float,
    h: float
) -> trimesh.Trimesh:
    """
    创建立方体网格
    
    Args:
        x: X 轴起始位置 (mm)
        y: Y 轴起始位置 (mm)
        z: Z 轴起始位置 (mm)
        w: 宽度 (X 方向, mm)
        l: 长度 (Y 方向, mm)
        h: 高度 (Z 方向, mm)
    
    Returns:
        trimesh.Trimesh: 立方体网格对象
    """
    # 创建立方体 (默认中心在原点)
    box = trimesh.creation.box(extents=[w, l, h])
    
    # 计算目标中心点
    cx = x + w / 2
    cy = y + l / 2
    cz = z + h / 2
    
    # 移动到指定位置
    box.apply_translation([cx, cy, cz])
    
    return box


def generate_step_card(
    layer_height: float = 0.08,
    num_steps: int = 5,
    base_thickness: float = 0.6,
    base_width: float = 20.0,
    step_length: float = 10.0,
    start_layers: int = 1,
    output_dir: str = "output/ks_engine/calibration"
) -> Tuple[List[str], str]:
    """
    生成 K/S 校准阶梯卡
    
    生成 3 个 STL 文件：
    1. 黑色底座 (左侧)
    2. 白色底座 (右侧)
    3. 测试颜色阶梯 (覆盖在底座上方)
    
    Args:
        layer_height: 打印层高 (mm)，必须与实际打印设置一致
        num_steps: 阶梯数量，测试 start_layers 到 (start_layers + num_steps - 1) 层
        base_thickness: 底座厚度 (mm)，确保不透光
        base_width: 每个底座的宽度 (mm)
        step_length: 每个阶梯的长度 (mm)
        start_layers: 起始层数
        output_dir: 输出目录路径
    
    Returns:
        (file_paths, status_message):
            - file_paths: 生成的 3 个 STL 文件路径列表
            - status_message: 状态信息字符串
    
    Example:
        >>> paths, msg = generate_step_card(
        ...     layer_height=0.08,
        ...     num_steps=5,
        ...     base_thickness=0.6
        ... )
        >>> print(paths)
        ['output/.../01_Base_Black.stl', '...', '...']
    """
    # 创建输出目录
    os.makedirs(output_dir, exist_ok=True)
    
    # 计算总长度
    total_length = num_steps * step_length
    
    status_lines = []
    status_lines.append(f"🔧 正在生成 K/S 校准阶梯卡...")
    status_lines.append(f"   层高: {layer_height}mm")
    status_lines.append(f"   阶梯数: {num_steps} (测试 {start_layers}-{start_layers + num_steps - 1} 层)")
    status_lines.append(f"   底座厚度: {base_thickness}mm")
    status_lines.append("")
    
    # ========== 1. 生成黑色底座 (左半边) ==========
    mesh_base_black = create_block(
        x=0, y=0, z=0,
        w=base_width,
        l=total_length,
        h=base_thickness
    )
    
    # ========== 2. 生成白色底座 (右半边) ==========
    mesh_base_white = create_block(
        x=base_width, y=0, z=0,
        w=base_width,
        l=total_length,
        h=base_thickness
    )
    
    # ========== 3. 生成测试颜色阶梯 ==========
    steps = []
    
    for i in range(num_steps):
        layers = start_layers + i
        step_thickness = layers * layer_height
        
        # Y 轴位置递增
        y_pos = i * step_length
        
        # Z 轴起始位置：紧贴底座上方
        z_pos = base_thickness
        
        step_mesh = create_block(
            x=0, y=y_pos, z=z_pos,
            w=base_width * 2,  # 横跨黑白两个底座
            l=step_length,
            h=step_thickness
        )
        
        steps.append(step_mesh)
        status_lines.append(f"   ✓ 阶梯 {i+1}: {layers} 层 ({step_thickness:.2f}mm)")
    
    # 合并所有阶梯为一个对象
    mesh_steps = trimesh.util.concatenate(steps)
    
    status_lines.append("")
    
    # ========== 4. 导出 STL 文件 ==========
    file_paths = []
    
    # 导出黑色底座
    path_black = os.path.join(output_dir, "01_Base_Black.stl")
    mesh_base_black.export(path_black)
    file_paths.append(os.path.abspath(path_black))
    status_lines.append(f"✅ 已生成: 01_Base_Black.stl")
    
    # 导出白色底座
    path_white = os.path.join(output_dir, "02_Base_White.stl")
    mesh_base_white.export(path_white)
    file_paths.append(os.path.abspath(path_white))
    status_lines.append(f"✅ 已生成: 02_Base_White.stl")
    
    # 导出测试阶梯
    path_steps = os.path.join(output_dir, "03_Target_Color_Steps.stl")
    mesh_steps.export(path_steps)
    file_paths.append(os.path.abspath(path_steps))
    status_lines.append(f"✅ 已生成: 03_Target_Color_Steps.stl")
    
    status_lines.append("")
    status_lines.append("📋 使用说明:")
    status_lines.append("1. 在切片软件中同时加载这 3 个 STL")
    status_lines.append("2. 选择 '作为单一对象的多部分加载'")
    status_lines.append("3. 设置耗材映射:")
    status_lines.append("   - 01_Base_Black → 黑色耗材")
    status_lines.append("   - 02_Base_White → 白色耗材")
    status_lines.append("   - 03_Target_Color → 要测试的耗材 (如 Cyan)")
    status_lines.append("4. 打印后放在 A4纸/校色背景板上拍照（推荐背景板，MakerWorld 搜索 2192593），用于下一步 K/S 计算")
    
    status_message = "\n".join(status_lines)
    
    return file_paths, status_message


# ========== K/S 参数计算 (占位符) ==========

def calculate_ks_parameters(
    image_path: str,
    layer_height: float = 0.08,
    num_steps: int = 5,
    backing_reflectance_white: float = 0.94,
    backing_reflectance_black: float = 0.00
) -> Tuple[dict, str, str]:
    """
    从校准照片计算 K/S 参数
    
    Args:
        image_path: 校准照片路径
        layer_height: 打印层高 (mm)
        num_steps: 阶梯数量
        backing_reflectance_white: 白底反射率
        backing_reflectance_black: 黑底反射率
    
    Returns:
        (ks_params, fitting_plot_path, status_message):
            - ks_params: {'K': [K_r, K_g, K_b], 'S': [S_r, S_g, S_b]}
            - fitting_plot_path: 拟合曲线图路径
            - status_message: 状态信息
    
    Note:
        此功能待实现，需要从 ChromaStack 的 KS_calibration.py 移植
    """
    # TODO: 实现 K/S 参数计算
    # 参考: ChromaStack-main/ChromaStack-main/filament_cali/KS_calibration.py
    
    status = "⚠️ K/S 参数计算功能尚未实现\n"
    status += "请参考 ChromaStack 的 KS_calibration.py 进行移植"
    
    return {}, "", status


if __name__ == "__main__":
    # 测试代码
    print("=== K/S Calibration Module Test ===\n")
    
    paths, msg = generate_step_card(
        layer_height=0.08,
        num_steps=5,
        base_thickness=0.6,
        output_dir="output/ks_engine/calibration_test"
    )
    
    print(msg)
    print(f"\n生成的文件:")
    for p in paths:
        print(f"  - {p}")
