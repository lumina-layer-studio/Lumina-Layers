"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                    K-M PHYSICS ENGINE - CORE CALCULATIONS                     ║
║                      Kubelka-Munk 光学理论核心计算                              ║
╚═══════════════════════════════════════════════════════════════════════════════╝

Adapted from ChromaStack project
Original: https://github.com/borealis-zhe/ChromaStack

This module implements the Kubelka-Munk theory for light transmission
through layered translucent materials.
"""

import numpy as np
import itertools
from typing import List, Dict, Tuple


class VirtualPhysics:
    """
    K-M 物理引擎核心类
    
    实现 Kubelka-Munk 理论的光学计算，用于预测多层透明材料的颜色混合效果
    """
    
    @staticmethod
    def linear_to_srgb_bytes(linear: np.ndarray) -> np.ndarray:
        """
        将线性 RGB 转换为 sRGB (0-255)
        
        Args:
            linear: 线性 RGB 数组 (0-1)
        
        Returns:
            sRGB 字节数组 (0-255)
        """
        linear = np.clip(linear, 0, 1)
        srgb = np.where(
            linear <= 0.0031308,
            12.92 * linear,
            1.055 * (linear ** (1.0 / 2.4)) - 0.055
        )
        return (srgb * 255).astype(np.uint8)
    
    @staticmethod
    def km_reflectance_vectorized(
        K: np.ndarray,
        S: np.ndarray,
        h: float,
        Rg: np.ndarray
    ) -> np.ndarray:
        """
        Kubelka-Munk 反射率计算 (向量化版本)
        
        Args:
            K: 吸收系数 (Absorption coefficient)
            S: 散射系数 (Scattering coefficient)
            h: 层厚度 (mm)
            Rg: 底材反射率 (Background reflectance)
        
        Returns:
            计算得到的反射率
        """
        # 避免除零
        S = np.maximum(S, 1e-6)
        
        # K-M 理论公式
        a = 1 + (K / S)
        b = np.sqrt(np.maximum(a**2 - 1, 1e-9))
        
        bSh = b * S * h
        sinh_bSh = np.sinh(bSh)
        cosh_bSh = np.cosh(bSh)
        
        numerator = sinh_bSh * (1 - Rg * a) + Rg * b * cosh_bSh
        denominator = sinh_bSh * (a - Rg) + b * cosh_bSh
        denominator = np.maximum(denominator, 1e-6)
        
        R = numerator / denominator
        return np.clip(R, 0, 1)
    
    def generate_lut_km(
        self,
        filaments_list: List[Dict],
        layer_height: float = 0.08,
        total_layers: int = 5,
        backing_reflectance: np.ndarray = np.array([0.94, 0.94, 0.94]),
        min_K: float = 0.01,
        adaptive_ks_ratio: float = 0.3,
        ks_ratio_threshold: float = 0.01,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        生成 K-M 理论的 LUT (查找表)
        
        Args:
            filaments_list: 耗材列表，每个包含 FILAMENT_K 和 FILAMENT_S
            layer_height: 单层厚度 (mm)
            total_layers: 总层数
            backing_reflectance: 底材反射率 (白色 PLA)
            min_K: K 值最小下限，防止完全透明层
            adaptive_ks_ratio: 自适应修正的目标 K/S 比值。当某通道 K/S 低于
                ks_ratio_threshold 时，将 K 提升到 adaptive_ks_ratio * S。
                设为 0 禁用自适应修正，仅使用 min_K 全局下限。
            ks_ratio_threshold: 触发自适应修正的 K/S 比值阈值
        
        Returns:
            (lut_colors_srgb, indices): LUT 颜色数组和索引映射
        """
        num_filaments = len(filaments_list)
        print(f" [K-M 引擎] 检测到 {num_filaments} 种耗材，正在计算光路混合...")
        
        # 提取 K 和 S 参数
        Ks = np.array([f['FILAMENT_K'] for f in filaments_list])
        Ss = np.array([f['FILAMENT_S'] for f in filaments_list])
        
        # 自适应 K 值修正：仅对 K/S 比值异常小的通道提升 K 值
        # 原理：K/S ≈ 0 意味着该层几乎完全透明，backing 直接穿透导致偏白
        # 实际打印中即使是"透明"层也有最小吸收，用 adaptive_ks_ratio 模拟
        # 
        # 重要：跳过"白色/透明"耗材（所有通道 K 都极小的耗材）
        # 白色耗材的物理特性就是 K≈0、S 大，不应该被修正
        if adaptive_ks_ratio > 0 and ks_ratio_threshold > 0:
            Ss_safe = np.maximum(Ss, 1e-6)
            ratio = Ks / Ss_safe
            
            # 判断每种耗材是否为"白色/透明"：所有通道的 K 值都极小
            # 白色耗材特征：max(K) < 0.05（所有通道几乎不吸光）
            is_white_filament = np.max(Ks, axis=1) < 0.05  # (num_filaments,)
            
            mask = ratio < ks_ratio_threshold
            if np.any(mask):
                Ks = Ks.copy()
                # 只对非白色耗材应用自适应修正
                white_mask_2d = is_white_filament[:, np.newaxis].repeat(3, axis=1)
                apply_mask = mask & ~white_mask_2d
                Ks[apply_mask] = np.maximum(Ks[apply_mask], adaptive_ks_ratio * Ss_safe[apply_mask])
                
                if np.any(is_white_filament & np.any(mask, axis=1)):
                    print(f"  > 跳过白色/透明耗材的自适应修正（保持原始 K 值）")
        
        # 应用 min_K 全局下限（作为兜底保护）
        Ks = np.maximum(Ks, min_K)
        
        # 生成所有可能的层叠组合
        indices = np.array(list(itertools.product(range(num_filaments), repeat=total_layers)))
        num_combos = len(indices)
        
        print(f"  > 组合总数: {num_filaments}^{total_layers} = {num_combos}")
        
        # 初始化反射率为底材反射率
        current_R = np.tile(backing_reflectance, (num_combos, 1))
        
        # 逐层计算反射率（从底层到顶层）
        for layer_idx in range(total_layers - 1, -1, -1):
            filament_ids = indices[:, layer_idx]
            layer_K = Ks[filament_ids]
            layer_S = Ss[filament_ids]
            current_R = self.km_reflectance_vectorized(
                layer_K, layer_S, layer_height, current_R
            )
        
        # 转换为 sRGB
        lut_colors_srgb = self.linear_to_srgb_bytes(current_R)
        
        return lut_colors_srgb, indices


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """
    将 sRGB (0-255) 转换为 CIELAB 颜色空间 (D65)
    
    Args:
        rgb: RGB 数组 (N, 3) 范围 0-255
    
    Returns:
        Lab 数组 (N, 3)
    """
    # 1. 归一化到 0-1
    rgb = rgb.astype(float) / 255.0
    
    # 2. sRGB -> Linear RGB (反 Gamma 校正)
    mask = rgb > 0.04045
    rgb[mask] = ((rgb[mask] + 0.055) / 1.055) ** 2.4
    rgb[~mask] = rgb[~mask] / 12.92
    
    # 3. Linear RGB -> XYZ (D65)
    M = np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041]
    ])
    XYZ = np.dot(rgb, M.T)
    
    # 4. XYZ -> Lab
    XYZ_ref = np.array([0.95047, 1.00000, 1.08883])  # D65 参考白点
    XYZ = XYZ / XYZ_ref
    
    mask = XYZ > 0.008856
    f_XYZ = np.zeros_like(XYZ)
    f_XYZ[mask] = XYZ[mask] ** (1.0/3.0)
    f_XYZ[~mask] = 7.787 * XYZ[~mask] + 16.0/116.0
    
    Lab = np.zeros_like(XYZ)
    Lab[:, 0] = 116.0 * f_XYZ[:, 1] - 16.0       # L
    Lab[:, 1] = 500.0 * (f_XYZ[:, 0] - f_XYZ[:, 1])  # a
    Lab[:, 2] = 200.0 * (f_XYZ[:, 1] - f_XYZ[:, 2])  # b
    
    return Lab


if __name__ == "__main__":
    # 测试代码
    print("=== K-M Physics Engine Test ===")
    
    # 模拟耗材数据
    test_filaments = [
        {
            'Name': 'White',
            'FILAMENT_K': [0.05, 0.05, 0.05],
            'FILAMENT_S': [10.0, 10.0, 10.0]
        },
        {
            'Name': 'Cyan',
            'FILAMENT_K': [0.5, 0.1, 0.1],
            'FILAMENT_S': [5.0, 5.0, 5.0]
        },
        {
            'Name': 'Magenta',
            'FILAMENT_K': [0.1, 0.5, 0.1],
            'FILAMENT_S': [5.0, 5.0, 5.0]
        },
        {
            'Name': 'Yellow',
            'FILAMENT_K': [0.1, 0.1, 0.5],
            'FILAMENT_S': [5.0, 5.0, 5.0]
        }
    ]
    
    engine = VirtualPhysics()
    lut_colors, indices = engine.generate_lut_km(test_filaments)
    
    print(f"✅ Generated LUT with {len(lut_colors)} colors")
    print(f"   Sample colors: {lut_colors[:5]}")
