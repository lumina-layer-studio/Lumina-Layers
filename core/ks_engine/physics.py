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
        
        # === DEBUG: 打印每种耗材的 K/S 参数 ===
        print(f"\n[DEBUG K-M] 耗材 K/S 参数详情:")
        for i, fil in enumerate(filaments_list):
            name = fil.get('name', f'耗材#{i}')
            color = fil.get('color', '#000000')
            K = Ks[i]
            S = Ss[i]
            print(f"  [{i}] {name} ({color})")
            print(f"      K: [{K[0]:.6f}, {K[1]:.6f}, {K[2]:.6f}]")
            print(f"      S: [{S[0]:.6f}, {S[1]:.6f}, {S[2]:.6f}]")
            print(f"      K/S: [{K[0]/max(S[0],1e-6):.6f}, {K[1]/max(S[1],1e-6):.6f}, {K[2]/max(S[2],1e-6):.6f}]")
        print()
        
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
        # 但对白色/透明材料（所有通道 K < 0.05）使用更小的下限
        is_white_filament = np.max(Ks, axis=1) < 0.05
        Ks_adjusted = Ks.copy()
        
        # 白色材料使用 min_K / 100 作为下限（保持极小的吸收）
        white_min_K = min_K / 100.0
        for i in range(len(Ks)):
            if is_white_filament[i]:
                Ks_adjusted[i] = np.maximum(Ks[i], white_min_K)
                print(f"  > 白色材料 {filaments_list[i].get('name', f'#{i}')} 使用特殊 min_K={white_min_K:.6f}")
            else:
                Ks_adjusted[i] = np.maximum(Ks[i], min_K)
        
        Ks = Ks_adjusted
        
        # 生成所有可能的层叠组合
        indices = np.array(list(itertools.product(range(num_filaments), repeat=total_layers)))
        num_combos = len(indices)
        
        print(f"  > 组合总数: {num_filaments}^{total_layers} = {num_combos}")
        
        # === DEBUG: 打印特定配方 [2 1 4 5 4] 的 K/S 参数 ===
        target_recipe = [2, 1, 4, 5, 4]
        if num_filaments >= 6:  # 确保索引有效
            target_idx = None
            for idx, combo in enumerate(indices):
                if list(combo) == target_recipe:
                    target_idx = idx
                    break
            
            if target_idx is not None:
                print(f"\n[DEBUG K-M] 目标配方 {target_recipe} 的 K/S 参数:")
                for layer_i, mat_id in enumerate(target_recipe):
                    name = filaments_list[mat_id].get('name', f'耗材#{mat_id}')
                    K = Ks[mat_id]
                    S = Ss[mat_id]
                    print(f"  第 {layer_i+1} 层: {name}")
                    print(f"    K: [{K[0]:.6f}, {K[1]:.6f}, {K[2]:.6f}]")
                    print(f"    S: [{S[0]:.6f}, {S[1]:.6f}, {S[2]:.6f}]")
                print()
        
        # 初始化反射率为底材反射率
        current_R = np.tile(backing_reflectance, (num_combos, 1))
        
        # === DEBUG: 打印目标配方的逐层计算过程 ===
        if num_filaments >= 6 and 'target_idx' in locals() and target_idx is not None:
            print(f"\n[DEBUG K-M] 目标配方 {target_recipe} 的逐层计算过程:")
            print(f"  初始反射率 (backing): [{backing_reflectance[0]:.6f}, {backing_reflectance[1]:.6f}, {backing_reflectance[2]:.6f}]")
        
        # 逐层计算反射率（从底层到顶层）
        for layer_idx in range(total_layers - 1, -1, -1):
            filament_ids = indices[:, layer_idx]
            layer_K = Ks[filament_ids]
            layer_S = Ss[filament_ids]
            
            # === DEBUG: 打印目标配方当前层的 K/S 值 ===
            if num_filaments >= 6 and 'target_idx' in locals() and target_idx is not None:
                mat_id = filament_ids[target_idx]
                K_used = layer_K[target_idx]
                S_used = layer_S[target_idx]
                R_before = current_R[target_idx]
                print(f"  第 {total_layers - layer_idx} 层 (索引 {layer_idx}): 材料 #{mat_id} {filaments_list[mat_id].get('name', '')}")
                print(f"    使用的 K: [{K_used[0]:.6f}, {K_used[1]:.6f}, {K_used[2]:.6f}]")
                print(f"    使用的 S: [{S_used[0]:.6f}, {S_used[1]:.6f}, {S_used[2]:.6f}]")
                print(f"    层前反射率: [{R_before[0]:.6f}, {R_before[1]:.6f}, {R_before[2]:.6f}]")
            
            current_R = self.km_reflectance_vectorized(
                layer_K, layer_S, layer_height, current_R
            )
            
            # === DEBUG: 打印目标配方当前层计算后的反射率 ===
            if num_filaments >= 6 and 'target_idx' in locals() and target_idx is not None:
                R_after = current_R[target_idx]
                print(f"    层后反射率: [{R_after[0]:.6f}, {R_after[1]:.6f}, {R_after[2]:.6f}]")
        
        # 转换为 sRGB
        lut_colors_srgb = self.linear_to_srgb_bytes(current_R)
        
        # === DEBUG: 打印目标配方的计算结果 ===
        if num_filaments >= 6 and target_idx is not None:
            final_R = current_R[target_idx]
            final_srgb = lut_colors_srgb[target_idx]
            print(f"[DEBUG K-M] 目标配方 {target_recipe} 的计算结果:")
            print(f"  最终反射率 R: [{final_R[0]:.6f}, {final_R[1]:.6f}, {final_R[2]:.6f}]")
            print(f"  sRGB 颜色: [{final_srgb[0]}, {final_srgb[1]}, {final_srgb[2]}]")
            print(f"  HEX: #{final_srgb[0]:02x}{final_srgb[1]:02x}{final_srgb[2]:02x}")
            print()
        
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
