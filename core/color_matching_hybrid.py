"""
Lumina Studio - 色相感知颜色匹配 (Vectorized)

改进的颜色匹配算法，在 CIELAB 距离基础上考虑色相（Hue）相似度。
使用完全向量化的 NumPy 操作替代 Python 循环，大幅提升性能。

核心策略：
1. 使用 KDTree 快速查找 K 个最近邻候选 (CIELAB 空间)
2. 计算候选颜色的色相距离 (连续角度差)
3. 应用加权惩罚：Effective Distance = LabDist * (1 + Weight * (HueDiff / 45°))
4. 向量化优选最佳匹配
"""

import numpy as np
import cv2
from scipy.spatial import cKDTree as KDTree


class HueAwareColorMatcher:
    """
    色相感知的颜色匹配器 (高性能向量化版)
    """
    
    def __init__(self, lut_rgb, lut_lab, hue_weight=0.3):
        """
        初始化匹配器
        
        Args:
            lut_rgb: LUT 的 RGB 颜色数组 (N, 3)
            lut_lab: LUT 的 LAB 颜色数组 (N, 3)
            hue_weight: 色相权重 (0.0-1.0)，默认 0.3
                       0.0 = 纯 CIELAB 距离
                       0.3 = 平衡模式 (推荐)
                       0.7+ = 强行优先同色系
        """
        self.lut_rgb = lut_rgb
        self.lut_lab = lut_lab
        self.hue_weight = hue_weight
        
        # 预计算 LUT 颜色的 HSV (H in [0, 360])
        self.lut_hsv = self._rgb_to_hsv(lut_rgb)
        
        # 构建 CIELAB KDTree
        self.kdtree = KDTree(lut_lab)
        
        print(f"[HUE_MATCHER] Vectorized Matcher initialized (hue_weight={hue_weight})")
    
    @staticmethod
    def _rgb_to_hsv(rgb_array):
        """
        将 RGB 转换为 HSV (向量化)
        
        Args:
            rgb_array: (N, 3) uint8 数组
        
        Returns:
            (N, 3) float32 数组，H in [0, 360), S in [0, 1], V in [0, 1]
        """
        if len(rgb_array) == 0:
            return np.zeros((0, 3), dtype=np.float32)
            
        # OpenCV 需要 (N, 1, 3) 形状
        hsv_cv = cv2.cvtColor(rgb_array.reshape(-1, 1, 3), cv2.COLOR_RGB2HSV)
        hsv_cv = hsv_cv.reshape(-1, 3).astype(np.float32)
        
        # 转换为标准范围
        hsv = np.zeros_like(hsv_cv)
        hsv[:, 0] = hsv_cv[:, 0] * 2.0  # H: [0, 180) -> [0, 360)
        hsv[:, 1] = hsv_cv[:, 1] / 255.0  # S: [0, 255] -> [0, 1]
        hsv[:, 2] = hsv_cv[:, 2] / 255.0  # V: [0, 255] -> [0, 1]
        
        return hsv
    
    @staticmethod
    def _rgb_to_lab(rgb_array):
        """
        将 RGB 转换为 LAB (向量化)
        """
        if len(rgb_array) == 0:
            return np.zeros((0, 3), dtype=np.float64)
            
        lab = cv2.cvtColor(rgb_array.reshape(-1, 1, 3), cv2.COLOR_RGB2Lab)
        return lab.reshape(-1, 3).astype(np.float64)

    def match_color(self, input_rgb, k=20):
        """
        匹配单个颜色 (兼容性包装器)
        
        Args:
            input_rgb: (3,) uint8 数组
            k: 候选数量
            
        Returns:
            int: 最佳匹配的 LUT 索引
        """
        # 包装成 batch (1, 3)
        input_batch = input_rgb.reshape(1, 3)
        indices = self.match_colors_batch(input_batch, k=k)
        return indices[0]

    def match_colors_batch(self, input_rgb_array, k=20):
        """
        批量匹配颜色 (向量化极速版)
        
        Args:
            input_rgb_array: (N, 3) uint8 数组
            k: 候选数量 (默认 20)
        
        Returns:
            (N,) int 数组：每个输入颜色的最佳匹配索引
        """
        n = len(input_rgb_array)
        if n == 0:
            return np.array([], dtype=np.int32)
            
        # 1. 转换输入颜色到 Lab 和 HSV
        input_lab = self._rgb_to_lab(input_rgb_array)
        input_hsv = self._rgb_to_hsv(input_rgb_array)
        
        # 2. KDTree 批量查询 (N, k)
        # distances: (N, k) Lab 距离
        # indices: (N, k) LUT 索引
        # 注意: k 不能超过 LUT 大小
        real_k = min(k, len(self.lut_rgb))
        # workers=-1 使用所有 CPU 核心
        lab_distances, candidate_indices = self.kdtree.query(input_lab, k=real_k, workers=-1)
        
        # 如果 hue_weight 为 0，直接返回最近邻 (第 0 列)
        if self.hue_weight <= 0.001:
            return candidate_indices[:, 0]
            
        # 3. 获取候选颜色的 Hue
        # candidate_indices 是 (N, k)，我们需要用它从 self.lut_hsv (M, 3) 中取值
        # 结果 shape: (N, k, 3)
        candidate_hsv = self.lut_hsv[candidate_indices]
        
        # 4. 计算 Hue 距离 (向量化)
        # input_hsv: (N, 3) -> (N, 1, 3) 用于广播
        input_h = input_hsv[:, 0].reshape(n, 1)
        cand_h = candidate_hsv[:, :, 0] # (N, k)
        
        # 最短角度差: min(|a-b|, 360-|a-b|)
        diff = np.abs(input_h - cand_h)
        hue_diff = np.minimum(diff, 360.0 - diff) # (N, k)
        
        # 5. 计算加权惩罚距离
        # 策略: Effective Dist = LabDist * (1 + Weight * (HueDiff / 45))
        # 45度是一个经验值，代表"显著色相差异"的阈值
        penalty_factor = 1.0 + self.hue_weight * (hue_diff / 45.0)
        final_distances = lab_distances * penalty_factor
        
        # 6. 选择每一行的最小值索引 (0..k-1)
        best_candidate_indices = np.argmin(final_distances, axis=1)
        
        # 7. 映射回全局 LUT 索引
        # 使用 numpy 高级索引: indices[row, col]
        row_indices = np.arange(n)
        result_indices = candidate_indices[row_indices, best_candidate_indices]
        
        return result_indices
