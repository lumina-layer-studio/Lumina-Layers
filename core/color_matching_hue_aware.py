"""
Lumina Studio - Hue-Aware Color Matching

改进的颜色匹配算法，考虑色相（Hue）相似度，确保同色系匹配。
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
                       1.0 = 完全基于色相
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
    def _hue_distance(h1, h2):
        """
        计算色相距离（考虑环形特性）
        
        Args:
            h1, h2: 色相值，范围 [0, 360)
        
        Returns:
            距离，范围 [0, 180]
        """
        diff = np.abs(h1 - h2)
        # 色相是环形的，最大距离是 180 度
        return np.minimum(diff, 360 - diff)
    
    def _is_achromatic(self, hsv, threshold=0.08):
        """
        判断颜色是否为无彩色（黑白灰）
        
        Args:
            hsv: (3,) 或 (N, 3) HSV 数组
            threshold: 饱和度阈值，默认 0.08
        
        Returns:
            bool 或 (N,) bool 数组
        """
        # 饱和度极低（< 0.08）就算无彩色，不再要求明度极端
        # 这样可以正确识别浅灰色、深灰色等
        if hsv.ndim == 1:
            s = hsv[1]
            return s < threshold
        else:
            s = hsv[:, 1]
            return s < threshold
    
    def _classify_hue(self, hsv):
        """
        根据色相对颜色进行分类
        
        Args:
            hsv: (3,) HSV 数组
        
        Returns:
            str: 色系名称
        """
        h, s, v = hsv
        
        # 无彩色判断
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
        匹配单个颜色 - 色系优先策略(带距离阈值保护)
        
        Args:
            input_rgb: (3,) uint8 数组
            k: 候选数量(增加到50以获得更多同色系候选)
        
        Returns:
            int: 最佳匹配的 LUT 索引
        """
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
        
        # 如果输入是无彩色,直接返回 LAB 最近的
        if input_category in ["白色系", "黑色系", "灰色系"]:
            return candidate_indices[0]
        
        # 色系优先策略(带距离阈值保护)
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
                
                # 距离阈值保护:
                # 只有当同色系候选的距离不超过其他色系的 (1 + hue_weight) 倍时,才选择同色系
                # 这样可以避免为了色系一致性而牺牲太多颜色准确性
                max_acceptable_dist = best_other_dist * (1.0 + self.hue_weight)
                
                if best_same_dist <= max_acceptable_dist:
                    # 同色系候选在可接受范围内,选择它
                    return best_same_idx
                else:
                    # 同色系候选距离太远,选择其他色系中最近的
                    return best_other_idx
        
        # 如果 hue_weight=0 或没有同色系候选,返回 LAB 最近的
        return candidate_indices[0]
    
    def match_colors_batch(self, input_rgb_array, k=10):
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


def test_hue_aware_matching():
    """测试色相感知匹配"""
    # 创建一个简单的 LUT（8 色）
    lut_rgb = np.array([
        [255, 255, 255],  # 白色
        [255, 0, 0],      # 红色
        [255, 0, 255],    # 品红
        [0, 255, 255],    # 青色
        [0, 0, 255],      # 蓝色
        [255, 255, 0],    # 黄色
        [0, 255, 0],      # 绿色
        [0, 0, 0],        # 黑色
    ], dtype=np.uint8)
    
    # 转换到 LAB
    lut_lab = cv2.cvtColor(
        lut_rgb.reshape(-1, 1, 3),
        cv2.COLOR_RGB2BGR
    )
    lut_lab = cv2.cvtColor(lut_lab, cv2.COLOR_BGR2Lab).astype(np.float64)
    lut_lab = lut_lab.reshape(-1, 3)
    
    # 测试颜色
    test_colors = {
        '浅粉色': np.array([253, 239, 232], dtype=np.uint8),  # #fdefe8
        '浅红色': np.array([255, 200, 200], dtype=np.uint8),
        '浅蓝色': np.array([200, 200, 255], dtype=np.uint8),
        '浅绿色': np.array([200, 255, 200], dtype=np.uint8),
    }
    
    print("\n" + "="*60)
    print("色相感知匹配测试")
    print("="*60)
    
    for hue_weight in [0.0, 0.3, 0.5, 0.7]:
        print(f"\n【hue_weight = {hue_weight}】")
        matcher = HueAwareColorMatcher(lut_rgb, lut_lab, hue_weight=hue_weight)
        
        for name, color in test_colors.items():
            idx = matcher.match_color(color, k=5)
            matched = lut_rgb[idx]
            print(f"  {name} {tuple(color)} → {tuple(matched)} (索引 {idx})")


if __name__ == '__main__':
    test_hue_aware_matching()
