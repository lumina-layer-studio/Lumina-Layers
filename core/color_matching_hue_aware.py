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
        "classic": {"w_L": 1.0, "w_C": 1.0, "w_H": 1.0},
        # 轻度色相保护（≈hw=0.3）
        "mild": {"w_L": 1.0, "w_C": 1.0, "w_H": 0.44},
        # 平衡模式（≈hw=0.5）：推荐默认值
        "balanced": {"w_L": 1.0, "w_C": 1.0, "w_H": 0.26},
        # 强色相保护（≈hw=1.0）
        "strong": {"w_L": 1.0, "w_C": 1.0, "w_H": 0.15},
    }

    def __init__(
        self,
        lut_rgb: np.ndarray,
        lut_lab: np.ndarray,
        hue_weight: float = 0.0,
        preset: str = None,
        w_L: float = None,
        w_C: float = None,
        w_H: float = None,
        chroma_gate: float = 15.0,
    ):
        """
        初始化匹配器。
        Initialize matcher.

        参数 (Args):
            lut_rgb: LUT 的 RGB 数组 (N, 3), uint8
            lut_lab: LUT 的 CIELAB 数组 (N, 3), float (OpenCV 格式)
            hue_weight: 简化参数 (0.0-1.0)，自动映射到 w_L/w_H
                        0.0 = 纯 CIELAB，1.0 = 最强色相保护
            preset: 预设名称 ('classic', 'mild', 'balanced', 'strong')
            w_L, w_C, w_H: 手动指定权重（优先级最高）
            chroma_gate: 暗色子集彩度门槛 (LCH 彩度)。
                         输入像素彩度 > 此值时跳过暗色子集强制/过渡，
                         走正常色相优先匹配。防止深色有彩色被错误匹配到灰色。
                         (Chroma gate for dark subset bypass. Pixels with chroma
                          above this skip dark-forced matching.)
                         默认 15.0，0 = 禁用（所有低亮度都走暗色子集）。
        """
        self.lut_rgb = np.asarray(lut_rgb, dtype=np.uint8)
        self.lut_lab = np.asarray(lut_lab, dtype=np.float64)
        self.n_colors = len(lut_rgb)
        self.chroma_gate = float(chroma_gate)

        # 预计算 LUT 的 LCH（基于 OpenCV LAB 格式）
        self.lut_lch = self._lab_to_lch(self.lut_lab)

        # 构建 CIELAB KDTree 用于快速初筛
        self.kdtree = KDTree(self.lut_lab)

        # 解析权重参数
        self._resolve_weights(hue_weight, preset, w_L, w_C, w_H)

        # 构建无彩暗色子集（v7 暗色描边线保护）
        self._dark_indices, self._dark_kdtree, self._dark_lab = self._build_dark_achromatic_subset(max_L=153, max_C=8)

        print(
            f"[HueAwareMatcher] 初始化: {self.n_colors} 色, "
            f"w_L={self.w_L:.2f}, w_C={self.w_C:.2f}, w_H={self.w_H:.2f}, "
            f"chroma_gate={self.chroma_gate:.1f}, "
            f"暗色子集={len(self._dark_indices)} 色"
        )

    def _resolve_weights(self, hue_weight, preset, w_L, w_C, w_H):
        """解析权重参数，优先级：手动 > 预设 > hue_weight 映射"""
        if w_L is not None and w_C is not None and w_H is not None:
            self.w_L = w_L
            self.w_C = w_C
            self.w_H = w_H
        elif preset and preset in self.PRESETS:
            p = self.PRESETS[preset]
            self.w_L = p["w_L"]
            self.w_C = p["w_C"]
            self.w_H = p["w_H"]
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
            self.w_L = 1.0  # 固定！不改变亮度维度
            self.w_C = 1.0  # 固定
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
        C = np.sqrt(a**2 + b**2)
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
        dH = self._delta_hue(input_lch[2], candidate_lch[:, 2], input_lch[1], candidate_lch[:, 1]) / self.w_H

        return np.sqrt(dL**2 + dC**2 + dH**2)

    @staticmethod
    def _hue_diff(h1, h2):
        """色相角差（环形，返回 0-180）"""
        d = np.abs(h1 - h2)
        return np.where(d > 180, 360 - d, d)

    @staticmethod
    def _adaptive_hue_threshold(chroma):
        """根据彩度自适应色相阈值，平滑过渡，避免硬分界导致色块。

        高彩度 → 严格色相约束；低彩度 → 放宽但仍优先色相；
        极低彩度（C≤2）→ 不约束色相（真正的灰色）。
        """
        if chroma > 15:
            return 20.0, 45.0  # 高彩度：严格色相
        elif chroma > 8:
            return 25.0, 50.0  # 中高彩度
        elif chroma > 5:
            return 30.0, 55.0  # 中彩度
        elif chroma > 2:
            return 50.0, 80.0  # 低彩度：放宽但仍优先色相
        else:
            return 999.0, 999.0  # 极低彩度：不约束

    @staticmethod
    def _adaptive_hue_threshold_vec(chroma_arr):
        """Vectorized adaptive hue threshold for array of chroma values.
        向量化自适应色相阈值，对整列 chroma 一次性计算。

        Args:
            chroma_arr (np.ndarray): (N,) chroma values. (彩度数组)

        Returns:
            tuple[np.ndarray, np.ndarray]: (ht, ht_relaxed) each (N,).
                (严格/宽松色相阈值数组)
        """
        conditions = [chroma_arr > 15, chroma_arr > 8, chroma_arr > 5, chroma_arr > 2]
        ht = np.select(conditions, [20.0, 25.0, 30.0, 50.0], default=999.0)
        ht_relaxed = np.select(conditions, [45.0, 50.0, 55.0, 80.0], default=999.0)
        return ht, ht_relaxed

    def _build_dark_achromatic_subset(self, max_L: float = 153, max_C: float = 8):
        """构建 LUT 中的无彩暗色子集。
        Build achromatic dark color subset from LUT.

        用于 v7 暗色描边线保护：低亮度输入像素只在此子集中匹配，
        避免黑色线条被匹配到红色/蓝色组合。

        Args:
            max_L: 最大亮度阈值 (OpenCV LAB 范围 0-255, 153≈标准 L*60)
            max_C: 最大彩度阈值 (LCH 彩度)

        Returns:
            tuple: (dark_indices, dark_kdtree, dark_lab)
        """
        mask = (self.lut_lch[:, 0] < max_L) & (self.lut_lch[:, 1] <= max_C)
        dark_indices = np.where(mask)[0]
        if len(dark_indices) == 0:
            return np.array([], dtype=np.intp), None, np.empty((0, 3))
        dark_lab = self.lut_lab[dark_indices]
        dark_kdtree = KDTree(dark_lab)
        return dark_indices, dark_kdtree, dark_lab

    def match_colors_batch(self, input_rgb: np.ndarray, k: int = 16) -> np.ndarray:
        """Batch hue-priority color matching (vectorized).
        色相优先批量颜色匹配（向量化实现）。

        Strategy: hue as hard constraint with adaptive thresholds.
        策略：色相作为硬约束，自适应阈值随彩度平滑过渡。

        Args:
            input_rgb (np.ndarray): (N, 3) uint8 RGB array. (输入 RGB 数组)
            k (int): KDTree candidate count for initial screening.
                (KDTree 初筛候选数量)

        Returns:
            np.ndarray: (N,) int array of best LUT indices per input color.
                (每个输入颜色在 LUT 中的最佳匹配索引)
        """
        input_rgb = np.asarray(input_rgb, dtype=np.uint8)
        n = len(input_rgb)

        print(f"[HueAwareMatcher] match_colors_batch (vectorized) n={n}, k={k}")

        if abs(self.w_L - 1.0) < 1e-6 and abs(self.w_C - 1.0) < 1e-6 and abs(self.w_H - 1.0) < 1e-6:
            input_lab = self._rgb_to_lab(input_rgb)
            _, indices = self.kdtree.query(input_lab)
            return indices

        input_lab = self._rgb_to_lab(input_rgb)
        input_lch = self._lab_to_lch(input_lab)

        k_actual = min(k, self.n_colors)
        _, candidate_indices = self.kdtree.query(input_lab, k=k_actual)
        if candidate_indices.ndim == 1:
            candidate_indices = candidate_indices.reshape(-1, 1)

        has_dark = self._dark_indices is not None and len(self._dark_indices) > 0
        k_dark = min(k, len(self._dark_indices)) if has_dark else 0
        DARK_FORCE_L = 128.0
        DARK_TRANSITION_L = 179.0

        result = np.empty(n, dtype=np.intp)

        # ── Classify pixels into 3 branches ──
        input_l = input_lch[:, 0]
        input_c = input_lch[:, 1]
        is_chromatic = (self.chroma_gate > 0) & (input_c > self.chroma_gate)
        dark_eligible = has_dark and k_dark > 0
        dark_force_mask = np.zeros(n, dtype=bool)
        dark_trans_mask = np.zeros(n, dtype=bool)
        if dark_eligible:
            low_chroma = ~is_chromatic
            dark_force_mask = low_chroma & (input_l < DARK_FORCE_L)
            dark_trans_mask = low_chroma & ~dark_force_mask & (input_l < DARK_TRANSITION_L)
        normal_mask = ~dark_force_mask & ~dark_trans_mask

        # ── Branch 1: Dark force (batch) ──
        if np.any(dark_force_mask):
            idx = np.where(dark_force_mask)[0]
            _, df_cand = self._dark_kdtree.query(input_lab[idx], k=k_dark)
            if df_cand.ndim == 1:
                df_cand = df_cand.reshape(-1, 1)
            df_lab = self._dark_lab[df_cand]
            df_dist = np.linalg.norm(df_lab - input_lab[idx, np.newaxis, :], axis=2)
            df_best = np.argmin(df_dist, axis=1)
            result[idx] = self._dark_indices[df_cand[np.arange(len(idx)), df_best]]

        # ── Branch 2: Dark transition (batch) ──
        if np.any(dark_trans_mask):
            idx = np.where(dark_trans_mask)[0]
            m = len(idx)
            t = (input_l[idx] - DARK_FORCE_L) / (DARK_TRANSITION_L - DARK_FORCE_L)

            dt_cand = candidate_indices[idx]
            dt_cand_lab = self.lut_lab[dt_cand]
            dt_dist = np.linalg.norm(dt_cand_lab - input_lab[idx, np.newaxis, :], axis=2)
            dt_best_local = np.argmin(dt_dist, axis=1)
            arange_m = np.arange(m)
            dt_best_full = dt_cand[arange_m, dt_best_local]
            dt_dist_full = dt_dist[arange_m, dt_best_local]

            _, dt_dark_cand = self._dark_kdtree.query(input_lab[idx], k=k_dark)
            if dt_dark_cand.ndim == 1:
                dt_dark_cand = dt_dark_cand.reshape(-1, 1)
            dt_dark_lab = self._dark_lab[dt_dark_cand]
            dt_dark_dist = np.linalg.norm(dt_dark_lab - input_lab[idx, np.newaxis, :], axis=2)
            dt_dark_best_local = np.argmin(dt_dark_dist, axis=1)
            dt_best_dark = self._dark_indices[dt_dark_cand[arange_m, dt_dark_best_local]]
            dt_dist_dark = dt_dark_dist[arange_m, dt_dark_best_local]

            use_dark = dt_dist_dark * (1.0 + t) <= dt_dist_full * (2.0 - t)
            result[idx] = np.where(use_dark, dt_best_dark, dt_best_full)

        # ── Branch 3: Normal hue-priority matching (fully vectorized) ──
        if np.any(normal_mask):
            idx = np.where(normal_mask)[0]
            m = len(idx)
            arange_m = np.arange(m)

            nm_cand = candidate_indices[idx]
            nm_cand_lab = self.lut_lab[nm_cand]
            nm_lab_dist = np.linalg.norm(nm_cand_lab - input_lab[idx, np.newaxis, :], axis=2)

            nm_cand_lch = self.lut_lch[nm_cand]
            nm_cand_h = nm_cand_lch[:, :, 2]
            nm_cand_c = nm_cand_lch[:, :, 1]

            nm_input_c = input_c[idx]
            nm_input_h = input_lch[idx, 2]

            ht, ht_relaxed = self._adaptive_hue_threshold_vec(nm_input_c)

            hdiff = self._hue_diff(nm_input_h[:, np.newaxis], nm_cand_h)
            min_cand_c = np.maximum(1.0, nm_input_c * 0.3)

            same_hue = (hdiff < ht[:, np.newaxis]) & (nm_cand_c > min_cand_c[:, np.newaxis])
            relaxed = (hdiff < ht_relaxed[:, np.newaxis]) & (nm_cand_c > min_cand_c[:, np.newaxis] * 0.5)

            is_gray = nm_input_c <= 2.0
            has_same = np.any(same_hue, axis=1)
            has_relax = np.any(relaxed, axis=1)

            eff_dist = nm_lab_dist.copy()

            use_same = ~is_gray & has_same
            if np.any(use_same):
                eff_dist[use_same] = np.where(same_hue[use_same], nm_lab_dist[use_same], 1e9)

            use_relaxed = ~is_gray & ~has_same & has_relax
            if np.any(use_relaxed):
                eff_dist[use_relaxed] = np.where(relaxed[use_relaxed], nm_lab_dist[use_relaxed], 1e9)

            best_local = np.argmin(eff_dist, axis=1)
            result[idx] = nm_cand[arange_m, best_local]

        return result

    @staticmethod
    def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
        """RGB (N,3) uint8 → OpenCV LAB (N,3) float64"""
        rgb_3d = rgb.reshape(1, -1, 3).astype(np.uint8)
        bgr = cv2.cvtColor(rgb_3d, cv2.COLOR_RGB2BGR)
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2Lab).astype(np.float64)
        return lab.reshape(-1, 3)
