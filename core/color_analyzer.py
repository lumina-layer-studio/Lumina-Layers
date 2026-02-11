"""
Lumina Studio - Color Analyzer

分析图片复杂度，推荐最佳量化颜色数。
独立模块，可单独测试和调用。
"""

import os
import time
from collections import Counter
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np


@dataclass
class ColorAnalysisResult:
    """色彩分析结果"""

    recommended: int  # 推荐颜色数
    max_safe: int  # 最大安全颜色数
    unique_colors: int  # 独特颜色数
    complexity_score: int  # 复杂度评分 (0-100)

    # 详细指标
    hue_score: int = 0  # 色系评分
    concentration_score: int = 0  # 集中度评分
    color_score: int = 0  # 颜色数评分
    edge_score: int = 0  # 边缘评分
    width_factor: float = 1.0  # 宽度因子

    def to_dict(self) -> dict:
        return {
            "recommended": self.recommended,
            "max_safe": self.max_safe,
            "unique_colors": self.unique_colors,
            "complexity_score": self.complexity_score,
        }


class ColorAnalyzer:
    """
    图片色彩复杂度分析器

    算法原理：
    1. 根据目标打印宽度缩放图片（模拟实际打印效果）
    2. 使用多种指标综合判断图片复杂度：
       - 色彩分布的集中度（主色占比）
       - 色系数量（HSV色相分布）
       - 边缘复杂度
    3. 基于综合复杂度推荐合适的量化颜色数
    """

    # 分析时每毫米对应的像素数
    ANALYSIS_PX_PER_MM = 5
    # 最大分析尺寸（像素）
    MAX_ANALYSIS_SIZE = 600
    # 常用颜色值
    COMMON_COLOR_VALUES = [8, 16, 24, 32, 48, 64, 96, 128, 160, 192, 256]

    @classmethod
    def analyze(
        cls, image_path: str, target_width_mm: float = 60.0, verbose: bool = True
    ) -> ColorAnalysisResult:
        """
        分析图片，推荐最佳量化颜色数。

        Args:
            image_path: 图片路径
            target_width_mm: 目标打印宽度（毫米），默认 60mm
            verbose: 是否打印详细日志

        Returns:
            ColorAnalysisResult: 分析结果
        """
        total_start = time.time()

        # 默认结果
        default_result = ColorAnalysisResult(
            recommended=64, max_safe=128, unique_colors=0, complexity_score=50
        )

        if not image_path or not os.path.exists(image_path):
            return default_result

        try:
            # 1. 加载图片
            img_rgb, original_w, original_h = cls._load_image(image_path, verbose)
            if img_rgb is None:
                return default_result

            # 2. 缩放到分析尺寸
            img_rgb = cls._resize_for_analysis(
                img_rgb, original_w, target_width_mm, verbose
            )
            h, w = img_rgb.shape[:2]
            pixel_count = w * h

            if verbose:
                print(f"[ColorAnalysis] 分析尺寸: {w}x{h}, 像素数: {pixel_count:,}")

            # 3. 计算各项指标
            unique_colors = cls._calc_unique_colors(img_rgb, verbose)
            hue_bins, colored_ratio = cls._calc_hue_distribution(
                img_rgb, pixel_count, verbose
            )
            top4_ratio, top8_ratio, top16_ratio = cls._calc_color_concentration(
                img_rgb, verbose
            )
            edge_ratio = cls._calc_edge_complexity(img_rgb, pixel_count, verbose)

            # 4. 计算评分
            hue_score = cls._score_hue(hue_bins, colored_ratio)
            concentration_score = cls._score_concentration(top8_ratio)
            color_score = cls._score_unique_colors(unique_colors)
            edge_score = cls._score_edge(edge_ratio)

            complexity_score = (
                hue_score + concentration_score + color_score + edge_score
            )

            if verbose:
                print(
                    f"[ColorAnalysis] 复杂度评分: {complexity_score} "
                    f"(色系={hue_score}, 集中度={concentration_score}, "
                    f"颜色={color_score}, 边缘={edge_score})"
                )

            # 5. 根据复杂度推荐颜色数
            base_recommended, base_max_safe = cls._complexity_to_colors(
                complexity_score
            )

            # 6. 应用宽度因子
            width_factor = cls._calc_width_factor(target_width_mm)
            recommended = int(base_recommended * width_factor)
            max_safe = int(base_max_safe * width_factor)

            # 7. 对齐到常用值
            recommended = cls._align_to_common(recommended)
            max_safe = cls._align_to_common(max_safe)
            if max_safe < recommended:
                max_safe = recommended

            if verbose:
                print(
                    f"[ColorAnalysis] 宽度因子: {width_factor:.2f} (基于 {target_width_mm}mm)"
                )
                total_time = time.time() - total_start
                print(f"[ColorAnalysis] ✅ 完成! 总耗时: {total_time:.2f}s")
                print(
                    f"[ColorAnalysis] 结果: 复杂度={complexity_score}, "
                    f"推荐={recommended}, 最大安全={max_safe}"
                )

            return ColorAnalysisResult(
                recommended=recommended,
                max_safe=max_safe,
                unique_colors=unique_colors,
                complexity_score=complexity_score,
                hue_score=hue_score,
                concentration_score=concentration_score,
                color_score=color_score,
                edge_score=edge_score,
                width_factor=width_factor,
            )

        except Exception as e:
            print(f"[ColorAnalysis] 分析失败: {e}")
            import traceback

            traceback.print_exc()
            return default_result

    # ==================== 私有方法 ====================

    @classmethod
    def _load_image(cls, image_path: str, verbose: bool):
        """加载图片"""
        t0 = time.time()
        img = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None, 0, 0

        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        h, w = img_rgb.shape[:2]

        if verbose:
            print(
                f"[ColorAnalysis] 加载图片: {time.time() - t0:.2f}s, 原始尺寸: {w}x{h}"
            )

        return img_rgb, w, h

    @classmethod
    def _resize_for_analysis(
        cls, img_rgb, original_w: int, target_width_mm: float, verbose: bool
    ):
        """缩放图片到分析尺寸"""
        target_width_px = int(target_width_mm * cls.ANALYSIS_PX_PER_MM)
        target_width_px = min(target_width_px, cls.MAX_ANALYSIS_SIZE)

        scale = target_width_px / original_w
        if scale != 1.0:
            t0 = time.time()
            h, w = img_rgb.shape[:2]
            target_height_px = int(h * scale)
            img_rgb = cv2.resize(
                img_rgb,
                (target_width_px, target_height_px),
                interpolation=cv2.INTER_AREA,
            )
            if verbose:
                print(
                    f"[ColorAnalysis] 缩放到分析尺寸: {time.time() - t0:.2f}s, "
                    f"新尺寸: {target_width_px}x{target_height_px}"
                )

        return img_rgb

    @classmethod
    def _calc_unique_colors(cls, img_rgb, verbose: bool) -> int:
        """计算独特颜色数（粗量化）"""
        t0 = time.time()
        quantized = (img_rgb // 8) * 8
        pixels = quantized.reshape(-1, 3)
        unique_count = len(np.unique(pixels, axis=0))

        if verbose:
            print(
                f"[ColorAnalysis] 独特颜色数（粗量化32级）: {unique_count}, "
                f"耗时: {time.time() - t0:.2f}s"
            )

        return unique_count

    @classmethod
    def _calc_hue_distribution(cls, img_rgb, pixel_count: int, verbose: bool):
        """计算色系分布"""
        t0 = time.time()
        img_hsv = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2HSV)

        saturation = img_hsv[:, :, 1].flatten()
        value = img_hsv[:, :, 2].flatten()
        hue = img_hsv[:, :, 0].flatten()

        # 只考虑有颜色的像素
        color_mask = (saturation > 30) & (value > 20) & (value < 235)
        colored_hues = hue[color_mask]

        if len(colored_hues) > 100:
            hue_bins = colored_hues // 15  # 12个色系
            hue_counts = np.bincount(hue_bins.astype(int), minlength=12)
            significant_hues = np.sum(hue_counts > len(colored_hues) * 0.05)
            colored_ratio = len(colored_hues) / pixel_count
        else:
            significant_hues = 1
            colored_ratio = 0

        if verbose:
            print(
                f"[ColorAnalysis] 色系数量: {significant_hues}/12, "
                f"有色像素占比: {colored_ratio:.2%}, 耗时: {time.time() - t0:.2f}s"
            )

        return significant_hues, colored_ratio

    @classmethod
    def _calc_color_concentration(cls, img_rgb, verbose: bool):
        """计算主色集中度"""
        t0 = time.time()
        quantized = (img_rgb // 4) * 4
        pixels = [tuple(p) for p in quantized.reshape(-1, 3)]
        color_counts = Counter(pixels)
        total = len(pixels)

        top_colors = color_counts.most_common(16)
        top16_ratio = sum(c[1] for c in top_colors) / total
        top8_ratio = sum(c[1] for c in top_colors[:8]) / total
        top4_ratio = sum(c[1] for c in top_colors[:4]) / total

        if verbose:
            print(
                f"[ColorAnalysis] 主色占比: top4={top4_ratio:.2%}, "
                f"top8={top8_ratio:.2%}, top16={top16_ratio:.2%}, "
                f"耗时: {time.time() - t0:.2f}s"
            )

        return top4_ratio, top8_ratio, top16_ratio

    @classmethod
    def _calc_edge_complexity(cls, img_rgb, pixel_count: int, verbose: bool) -> float:
        """计算边缘复杂度"""
        t0 = time.time()
        gray = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        edge_ratio = np.sum(edges > 0) / pixel_count

        if verbose:
            print(
                f"[ColorAnalysis] 边缘占比: {edge_ratio:.2%}, "
                f"耗时: {time.time() - t0:.2f}s"
            )

        return edge_ratio

    @staticmethod
    def _score_hue(hue_bins: int, colored_ratio: float) -> int:
        """色系评分 (0-35)"""
        if hue_bins <= 2:
            score = 0
        elif hue_bins <= 3:
            score = 7
        elif hue_bins <= 4:
            score = 14
        elif hue_bins <= 6:
            score = 21
        elif hue_bins <= 8:
            score = 28
        else:
            score = 35

        # 有色像素占比低时降低评分
        if colored_ratio < 0.30:
            score = 0
        elif colored_ratio < 0.50:
            score = min(score, 7)

        return score

    @staticmethod
    def _score_concentration(top8_ratio: float) -> int:
        """集中度评分 (0-35)，集中度越高越简单"""
        if top8_ratio > 0.90:
            return 0
        elif top8_ratio > 0.80:
            return 7
        elif top8_ratio > 0.65:
            return 14
        elif top8_ratio > 0.50:
            return 21
        elif top8_ratio > 0.35:
            return 28
        else:
            return 35

    @staticmethod
    def _score_unique_colors(unique_colors: int) -> int:
        """独特颜色评分 (0-20)"""
        if unique_colors < 100:
            return 0
        elif unique_colors < 300:
            return 5
        elif unique_colors < 600:
            return 10
        elif unique_colors < 1000:
            return 15
        else:
            return 20

    @staticmethod
    def _score_edge(edge_ratio: float) -> int:
        """边缘评分 (0-10)"""
        if edge_ratio < 0.03:
            return 0
        elif edge_ratio < 0.06:
            return 3
        elif edge_ratio < 0.10:
            return 6
        else:
            return 10

    @staticmethod
    def _complexity_to_colors(complexity_score: int) -> tuple:
        """复杂度评分转换为基础颜色数"""
        if complexity_score < 20:
            return 16, 24
        elif complexity_score < 40:
            return 24, 32
        elif complexity_score < 55:
            return 48, 64
        elif complexity_score < 70:
            return 96, 128
        elif complexity_score < 85:
            return 128, 192
        else:
            return 192, 256

    @staticmethod
    def _calc_width_factor(target_width_mm: float) -> float:
        """计算宽度因子"""
        # sqrt(width/60) - 60mm为基准
        factor = (target_width_mm / 60.0) ** 0.5
        return max(0.8, min(factor, 2.5))

    @classmethod
    def _align_to_common(cls, value: int) -> int:
        """对齐到常用值"""
        return min(cls.COMMON_COLOR_VALUES, key=lambda x: abs(x - value))


# 便捷函数
def analyze_recommended_colors(image_path: str, target_width_mm: float = 60.0) -> dict:
    """
    分析图片，推荐最佳量化颜色数。

    Args:
        image_path: 图片路径
        target_width_mm: 目标打印宽度（毫米）

    Returns:
        dict: {'recommended': int, 'max_safe': int, 'unique_colors': int, 'complexity_score': int}
    """
    result = ColorAnalyzer.analyze(image_path, target_width_mm)
    return result.to_dict()
