"""
色相感知颜色匹配器 (Hue-Aware Color Matcher)

核心思想：在 LCH 色彩空间中使用加权距离进行颜色匹配。

CIELAB 的 L*a*b* 用欧氏距离时，亮度差异容易压过色相差异，
导致浅粉色匹配到白色而不是红色系。

本模块将 CIELAB 转换到 LCH（亮度-彩度-色相）空间，
通过对三个维度分别设置权重来控制匹配行为：
  - w_L: 亮度权重（越大 → 亮度差异越不敏感 → 更倾向同色相）
  - w_C: 彩度权重（越大 → 彩度差异越不敏感）
  - w_H: 色相权重（越小 → 色相差异越敏感 → 更严格保持同色相）

对于无彩色（黑白灰），色相无意义，通过 CIEDE2000 风格的 ΔH 公式
自动处理（彩度为 0 时 ΔH=0）。

兼容项目现有的 OpenCV LAB 格式（L:0-255, a:0-255, b:0-255）。
"""

import numpy as np
import cv2
from scipy.spatial import KDTree


class HueAwareColorMatcher:
    """LCH 加权距离颜色匹配器"""

    # 预设配置
    # w_L 越大 → 亮度差异越不敏感（允许跨亮度匹配同色相）
    # w_H 越小 → 色相差异越敏感（更严格保持同色相）
    PRESETS = {
        # 纯 CIELAB 距离（等同于原始 KDTree 行为）
        'classic': {'w_L': 1.0, 'w_C': 1.0, 'w_H': 1.0},
        # 轻度色相保护（≈hw=0.3）
        'mild': {'w_L': 1.0, 'w_C': 1.0, 'w_H': 0.44},
        # 平衡模式（≈hw=0.5）：推荐默认值
        'balanced': {'w_L': 1.0, 'w_C': 1.0, 'w_H': 0.26},
        # 强色相保护（≈hw=1.0）
        'strong': {'w_L': 1.0, 'w_C': 1.0, 'w_H': 0.15},
    }

    def __init__(self, lut_rgb: np.ndarray, lut_lab: np.ndarray,
                 hue_weight: float = 0.0,
                 preset: str = None,
                 w_L: float = None, w_C: float = None, w_H: float = None):
        """
        初始化匹配器。

        参数:
            lut_rgb: LUT 的 RGB 数组 (N, 3), uint8
            lut_lab: LUT 的 CIELAB 数组 (N, 3), float (OpenCV 格式)
            hue_weight: 简化参数 (0.0-1.0)，自动映射到 w_L/w_H
                        0.0 = 纯 CIELAB，1.0 = 最强色相保护
            preset: 预设名称 ('classic', 'mild', 'balanced', 'strong')
            w_L, w_C, w_H: 手动指定权重（优先级最高）
        """
        self.lut_rgb = np.asarray(lut_rgb, dtype=np.uint8)
        self.lut_lab = np.asarray(lut_lab, dtype=np.float64)
        self.n_colors = len(lut_rgb)

        # 预计算 LUT 的 LCH（基于 OpenCV LAB 格式）
        self.lut_lch = self._lab_to_lch(self.lut_lab)

        # 构建 CIELAB KDTree 用于快速初筛
        self.kdtree = KDTree(self.lut_lab)

        # 解析权重参数
        self._resolve_weights(hue_weight, preset, w_L, w_C, w_H)

        print(f"[HueAwareMatcher] 初始化: {self.n_colors} 色, "
              f"w_L={self.w_L:.2f}, w_C={self.w_C:.2f}, w_H={self.w_H:.2f}")

    def _resolve_weights(self, hue_weight, preset, w_L, w_C, w_H):
        """解析权重参数，优先级：手动 > 预设 > hue_weight 映射"""
        if w_L is not None and w_C is not None and w_H is not None:
            self.w_L = w_L
            self.w_C = w_C
            self.w_H = w_H
        elif preset and preset in self.PRESETS:
            p = self.PRESETS[preset]
            self.w_L = p['w_L']
            self.w_C = p['w_C']
            self.w_H = p['w_H']
        else:
            # hue_weight 0.0-1.0 映射到权重
            # 核心策略：w_L 保持 1.0 不变，只通过降低 w_H 放大色相惩罚。
            # 使用指数曲线而非线性映射，让滑块一旦拉起就快速进入强保护区间，
            # 避免中间值"犹豫"导致色块（部分颜色匹配同色系、部分不匹配）。
            #
            # 映射: w_H = 0.15 + 0.85 * (1 - hw)^3
            #   hw=0.0 → w_H=1.0   (纯 CIELAB)
            #   hw=0.3 → w_H=0.44  (已有明显保护)
            #   hw=0.5 → w_H=0.26  (强保护)
            #   hw=0.7 → w_H=0.17  (接近最强)
            #   hw=1.0 → w_H=0.15  (最强)
            hw = np.clip(hue_weight, 0.0, 1.0)
            self.w_L = 1.0                   # 固定！不改变亮度维度
            self.w_C = 1.0                   # 固定
            self.w_H = 0.15 + 0.85 * (1.0 - hw) ** 3  # 指数曲线，快速下降

    @staticmethod
    def _lab_to_lch(lab: np.ndarray) -> np.ndarray:
        """
        OpenCV LAB → LCH 转换。

        OpenCV LAB 格式: L:0-255, a:0-255(128=0), b:0-255(128=0)

        L = L (保持 OpenCV 范围)
        C = sqrt((a-128)² + (b-128)²)  彩度
        H = atan2(b-128, a-128)        色相角 (度, 0-360)
        """
        L = lab[..., 0]
        a = lab[..., 1] - 128.0  # 中心化
        b = lab[..., 2] - 128.0
        C = np.sqrt(a ** 2 + b ** 2)
        H = np.degrees(np.arctan2(b, a)) % 360
        return np.stack([L, C, H], axis=-1)

    @staticmethod
    def _delta_hue(h1_deg, h2_deg, c1, c2):
        """
        计算色相差 ΔH（改进的 CIEDE2000 风格）。

        ΔH = 2 * min(C1, C2) * sin(Δh / 2)

        使用 min(C1, C2) 而非 sqrt(C1*C2)，确保：
        1. 任一颜色彩度低 → ΔH 很小（低彩度色相不可靠）
        2. 只有双方都是高彩度时，色相差异才有显著影响
        3. 正确处理色相角的环形特性（350° 和 10° 差 20°，不是 340°）
        """
        dh = h2_deg - h1_deg
        # 环形处理：确保 dh 在 [-180, 180]
        dh = (dh + 180) % 360 - 180
        dh_rad = np.radians(dh)
        return 2.0 * np.minimum(c1, c2) * np.sin(dh_rad / 2.0)

    def _weighted_distance(self, input_lch, candidate_lch):
        """
        计算 LCH 加权距离。

        input_lch: (3,) 单个颜色
        candidate_lch: (K, 3) K 个候选

        返回: (K,) 距离数组
        """
        dL = (candidate_lch[:, 0] - input_lch[0]) / self.w_L
        dC = (candidate_lch[:, 1] - input_lch[1]) / self.w_C
        dH = self._delta_hue(
            input_lch[2], candidate_lch[:, 2],
            input_lch[1], candidate_lch[:, 1]
        ) / self.w_H

        return np.sqrt(dL ** 2 + dC ** 2 + dH ** 2)

    def match_colors_batch(self, input_rgb: np.ndarray, k: int = 16) -> np.ndarray:
        """
        批量颜色匹配。

        参数:
            input_rgb: (N, 3) uint8 RGB 数组
            k: KDTree 初筛候选数量

        返回:
            (N,) int 数组，每个输入颜色在 LUT 中的最佳匹配索引
        """
        input_rgb = np.asarray(input_rgb, dtype=np.uint8)
        n = len(input_rgb)

        # 如果权重全为 1（纯 CIELAB），直接用 KDTree
        if (abs(self.w_L - 1.0) < 1e-6 and
            abs(self.w_C - 1.0) < 1e-6 and
            abs(self.w_H - 1.0) < 1e-6):
            input_lab = self._rgb_to_lab(input_rgb)
            _, indices = self.kdtree.query(input_lab)
            return indices

        # 转换到 LAB 和 LCH
        input_lab = self._rgb_to_lab(input_rgb)
        input_lch = self._lab_to_lch(input_lab)

        # KDTree 初筛
        k_actual = min(k, self.n_colors)
        _, candidate_indices = self.kdtree.query(input_lab, k=k_actual)

        if candidate_indices.ndim == 1:
            candidate_indices = candidate_indices.reshape(-1, 1)

        # 对每个输入颜色，在候选中用加权距离重新排序
        result = np.empty(n, dtype=np.intp)

        for i in range(n):
            cand_idx = candidate_indices[i]
            cand_lch = self.lut_lch[cand_idx]
            distances = self._weighted_distance(input_lch[i], cand_lch)
            best = np.argmin(distances)
            result[i] = cand_idx[best]

        return result

    @staticmethod
    def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
        """RGB (N,3) uint8 → OpenCV LAB (N,3) float64"""
        rgb_3d = rgb.reshape(1, -1, 3).astype(np.uint8)
        bgr = cv2.cvtColor(rgb_3d, cv2.COLOR_RGB2BGR)
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64)
        return lab.reshape(-1, 3)
