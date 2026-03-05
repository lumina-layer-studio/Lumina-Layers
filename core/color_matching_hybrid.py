"""
Lumina Studio - 色相感知颜色匹配

改进的颜色匹配算法，在 CIELAB 距离基础上考虑色相（Hue）相似度，
确保同色系颜色优先匹配到同色系的 LUT 颜色。

核心策略：
1. 使用 CIELAB 距离保证感知准确性（基础）
2. 使用 HSV 色相分类实现同色系优先（辅助）
3. 距离阈值保护避免过度牺牲颜色准确性
"""

import numpy as np
import cv2
from scipy.spatial import KDTree


class HueAwareColorMatcher:
    """
    色相感知的颜色匹配器
    
    在 CIELAB 距离的基础上，增加色相相似度权重，
    确保同色系的颜色匹配到同色系的 LUT 颜色。
    """
    
    def __init__(self, lut_rgb, lut_lab, hue_weight=0.3):
        """
        初始化匹配器
        
        Args:
            lut_rgb: LUT 的 RGB 颜色数组 (N, 3)
            lut_lab: LUT 的 LAB 颜色数组 (N, 3)
            hue_weight: 色相权重 (0.0-1.0)，默认 0.3
                       0.0 = 纯 CIELAB 距离（当前行为）
                       0.3-0.5 = 平衡模式（推荐）
                       0.7-1.0 = 强调同色系
        """
        self.lut_rgb = lut_rgb
        self.lut_lab = lut_lab
        self.hue_weight = hue_weight
        
        # 预计算 LUT 颜色的 HSV
        self.lut_hsv = self._rgb_to_hsv(lut_rgb)
        
        # 构建 CIELAB KDTree（用于快速初筛）
        self.kdtree = KDTree(lut_lab)
        
        print(f"[HUE_MATCHER] Initialized with hue_weight={hue_weight}")
    
    @staticmethod
    def _rgb_to_hsv(rgb_array):
        """
        将 RGB 转换为 HSV
        
        Args:
            rgb_array: (N, 3) uint8 数组
        
        Returns:
            (N, 3) float32 数组，H in [0, 360), S in [0, 1], V in [0, 1]
        """
        # OpenCV 的 HSV: H in [0, 180), S in [0, 255], V in [0, 255]
        hsv_cv = cv2.cvtColor(rgb_array.reshape(-1, 1, 3), cv2.COLOR_RGB2HSV)
        hsv_cv = hsv_cv.reshape(-1, 3).astype(np.float32)
        
        # 转换为标准范围
        hsv = np.zeros_like(hsv_cv)
        hsv[:, 0] = hsv_cv[:, 0] * 2.0  # H: [0, 180) -> [0, 360)
        hsv[:, 1] = hsv_cv[:, 1] / 255.0  # S: [0, 255] -> [0, 1]
        hsv[:, 2] = hsv_cv[:, 2] / 255.0  # V: [0, 255] -> [0, 1]
        
        return hsv
    
    @staticmethod
    def _classify_hue(hsv):
        """
        根据色相对颜色进行分类
        
        Args:
            hsv: (3,) HSV 数组
        
        Returns:
            str: 色系名称
        """
        h, s, v = hsv
        
        # 无彩色判断（饱和度过低）
        if s < 0.08:
            if v > 0.9:
                return "白色系"
            elif v < 0.1:
                return "黑色系"
            else:
                return "灰色系"
        
        # 有彩色按色相分类
        if h < 30 or h >= 330:
            return "红色系"
        elif 30 <= h < 60:
            return "橙黄系"
        elif 60 <= h < 90:
            return "黄色系"
        elif 90 <= h < 150:
            return "绿色系"
        elif 150 <= h < 210:
            return "青色系"
        elif 210 <= h < 270:
            return "蓝色系"
        elif 270 <= h < 330:
            return "品红系"
        else:
            return "未知"
    
    def match_color(self, input_rgb, k=50):
        """
        匹配单个颜色 - 色系优先策略（带距离阈值保护）
        
        Args:
            input_rgb: (3,) uint8 数组
            k: 候选数量（增加到 50 以获得更多同色系候选）
        
        Returns:
            int: 最佳匹配的 LUT 索引
        """
        # 限制 k 不超过 LUT 大小
        k = min(k, len(self.lut_rgb))
        
        # 转换到 LAB 和 HSV
        input_lab = cv2.cvtColor(
            input_rgb.reshape(1, 1, 3).astype(np.uint8),
            cv2.COLOR_RGB2BGR
        )
        input_lab = cv2.cvtColor(input_lab, cv2.COLOR_BGR2Lab).astype(np.float64)
        input_lab = input_lab.reshape(3)
        
        input_hsv = self._rgb_to_hsv(input_rgb.reshape(1, 3))[0]
        input_category = self._classify_hue(input_hsv)
        
        # 使用 KDTree 找到 k 个最近的候选
        lab_distances, candidate_indices = self.kdtree.query(input_lab, k=k)
        
        # 如果输入是无彩色，直接返回 LAB 最近的
        if input_category in ["白色系", "黑色系", "灰色系"]:
            return candidate_indices[0]
        
        # 色系优先策略（带距离阈值保护）
        if self.hue_weight > 0:
            # 找出所有同色系的候选
            same_category_candidates = []
            other_candidates = []
            
            for i, lut_idx in enumerate(candidate_indices):
                lut_hsv = self.lut_hsv[lut_idx]
                lut_category = self._classify_hue(lut_hsv)
                
                if lut_category == input_category:
                    same_category_candidates.append((lut_idx, lab_distances[i]))
                else:
                    other_candidates.append((lut_idx, lab_distances[i]))
            
            # 如果有同色系候选
            if same_category_candidates:
                best_same_idx, best_same_dist = min(same_category_candidates, key=lambda x: x[1])
                best_other_idx, best_other_dist = min(other_candidates, key=lambda x: x[1]) if other_candidates else (None, float('inf'))
                
                # 距离阈值保护：
                # 只有当同色系候选的距离不超过其他色系的 (1 + hue_weight) 倍时，才选择同色系
                # 这样可以避免为了色系一致性而牺牲太多颜色准确性
                max_acceptable_dist = best_other_dist * (1.0 + self.hue_weight)
                
                if best_same_dist <= max_acceptable_dist:
                    # 同色系候选在可接受范围内，选择它
                    return best_same_idx
                else:
                    # 同色系候选距离太远，选择其他色系中最近的
                    return best_other_idx
        
        # 如果 hue_weight=0 或没有同色系候选，返回 LAB 最近的
        return candidate_indices[0]
    
    def match_colors_batch(self, input_rgb_array, k=50):
        """
        批量匹配颜色
        
        Args:
            input_rgb_array: (N, 3) uint8 数组
            k: 候选数量
        
        Returns:
            (N,) int 数组：每个输入颜色的最佳匹配索引
        """
        n = len(input_rgb_array)
        result_indices = np.zeros(n, dtype=np.int32)
        
        for i in range(n):
            result_indices[i] = self.match_color(input_rgb_array[i], k=k)
        
        return result_indices
