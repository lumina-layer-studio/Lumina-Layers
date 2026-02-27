"""
K/S 理论 LUT 生成器
负责从耗材 K/S 参数计算颜色查找表，并保存为标准 .npy 文件
"""

import os
import numpy as np
import itertools
from typing import Callable, Dict, List, Tuple, Optional

from core.ks_engine.physics import VirtualPhysics


class KSLutGenerator:
    """K/S 理论 LUT 生成器"""

    def __init__(self, physics: VirtualPhysics = None):
        self.physics = physics or VirtualPhysics()

    @staticmethod
    def validate_selection(num_filaments: int) -> Tuple[bool, int, str]:
        """
        验证耗材选择

        Args:
            num_filaments: 选择的耗材数量

        Returns:
            (is_valid, total_colors, message)
        """
        if num_filaments < 2:
            return False, 0, "请至少选择 2 种耗材"
        if num_filaments > 8:
            return False, 0, "最多支持 8 种耗材"

        total_colors = num_filaments ** 5
        message = f"预计颜色总数: {total_colors}"

        if total_colors > 32768:
            message += "（警告：颜色数量较多，计算可能耗时较长）"

        return True, total_colors, message

    def generate(
        self,
        filaments: List[Dict],
        selected_indices: List[int],
        layer_height: float = 0.08,
        total_layers: int = 5,
        backing_reflectance: np.ndarray = None,
        progress_callback: Callable = None,
        min_K: float = 0.01,
        adaptive_ks_ratio: float = 0.3,
        ks_ratio_threshold: float = 0.01,
    ) -> Tuple[np.ndarray, dict]:
        """
        生成 LUT

        Args:
            filaments: 完整耗材列表
            selected_indices: 用户选择的耗材索引
            layer_height: 单层厚度 (mm)
            total_layers: 总层数
            backing_reflectance: 底材反射率
            progress_callback: 进度回调 fn(stage: str, percent: float)
            min_K: K 值最小下限（全局兜底）
            adaptive_ks_ratio: 自适应修正目标 K/S 比值（0 禁用）
            ks_ratio_threshold: 触发自适应修正的 K/S 阈值

        Returns:
            (lut_grid, metadata) 其中:
            - lut_grid: reshape 后的网格形状 uint8 数组
            - metadata: {"num_filaments": N, "total_colors": N^5, "shape": (...)}
        """
        num_filaments = len(selected_indices)
        is_valid, total_colors, msg = self.validate_selection(num_filaments)
        if not is_valid:
            raise ValueError(msg)

        # 从完整耗材列表中按 selected_indices 提取选中耗材
        selected_filaments = [filaments[i] for i in selected_indices]

        if backing_reflectance is None:
            backing_reflectance = np.array([0.94, 0.94, 0.94])

        if progress_callback:
            progress_callback("计算颜色组合", 0.0)

        # 调用物理引擎计算
        lut_colors_srgb, indices = self.physics.generate_lut_km(
            selected_filaments,
            layer_height=layer_height,
            total_layers=total_layers,
            backing_reflectance=backing_reflectance,
            min_K=min_K,
            adaptive_ks_ratio=adaptive_ks_ratio,
            ks_ratio_threshold=ks_ratio_threshold,
        )

        if progress_callback:
            progress_callback("重塑网格", 0.8)

        # reshape 为兼容格式
        lut_grid, stacks = self.reshape_to_grid(lut_colors_srgb, num_filaments)

        # === DEBUG: K/S LUT 生成结果 ===
        print(f"[DEBUG KS-GEN] num_filaments: {num_filaments}")
        print(f"[DEBUG KS-GEN] lut_colors_srgb shape: {lut_colors_srgb.shape}, dtype: {lut_colors_srgb.dtype}")
        print(f"[DEBUG KS-GEN] lut_grid shape: {lut_grid.shape}")
        print(f"[DEBUG KS-GEN] stacks: {'None' if stacks is None else f'shape={stacks.shape}'}")
        if stacks is not None:
            print(f"[DEBUG KS-GEN] 前5个stacks: {stacks[:5].tolist()}")
            print(f"[DEBUG KS-GEN] 前5个颜色 (sRGB): {lut_colors_srgb[:5].tolist()}")
        print(f"[DEBUG KS-GEN] 前5个grid颜色: {lut_grid.reshape(-1, 3)[:5].tolist()}")
        # === END DEBUG ===

        if progress_callback:
            progress_callback("完成", 1.0)

        filament_names = [f.get('name', f'耗材#{i}') for i, f in enumerate(selected_filaments)]
        filament_colors = [f.get('color', '#000000') for f in selected_filaments]

        metadata = {
            "num_filaments": num_filaments,
            "total_colors": total_colors,
            "shape": lut_grid.shape,
            "filament_names": filament_names,
            "filament_colors": filament_colors,
            "layer_height": layer_height,
            "total_layers": total_layers,
            "backing_reflectance": backing_reflectance.tolist(),
            "min_K": min_K,
            "adaptive_ks_ratio": adaptive_ks_ratio,
            "ks_ratio_threshold": ks_ratio_threshold,
            "stacks": stacks,
        }

        return lut_grid, metadata

    @staticmethod
    def reshape_to_grid(
        colors: np.ndarray, num_filaments: int
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """
        将 (N^5, 3) 扁平颜色数组 reshape 为网格形状

        2色: (32, 1, 3)
        4色: (32, 32, 3)
        其他: (N^5, 1, 3) + stacks

        Args:
            colors: (N^5, 3) 的 sRGB 颜色数组
            num_filaments: 耗材数量

        Returns:
            (lut_grid, stacks) - stacks 为 None 表示不需要额外 stacks 文件
        """
        total_colors = num_filaments ** 5

        if num_filaments == 2:
            # 2色: (32, 1, 3)
            lut_grid = colors.reshape(32, 1, 3)
            return lut_grid, None

        elif num_filaments == 4:
            # 4色: (32, 32, 3) — 4^5=1024, 32x32
            lut_grid = colors.reshape(32, 32, 3)
            return lut_grid, None

        else:
            # 3/5/6/7/8色: (N^5, 1, 3) + stacks 索引
            lut_grid = colors.reshape(total_colors, 1, 3)

            # 生成 stacks 索引数组：所有 N^5 种组合的叠层索引
            stacks = np.array(
                list(itertools.product(range(num_filaments), repeat=5)),
                dtype=np.int32,
            )

            return lut_grid, stacks

    def save(
        self,
        lut_grid: np.ndarray,
        file_path: str,
        stacks: np.ndarray = None,
        metadata: dict = None,
    ) -> Tuple[str, int]:
        """
        保存 LUT 到 .npy 文件

        Args:
            lut_grid: reshape 后的 LUT 数组
            file_path: 保存路径
            stacks: stacks 索引数组（6色/8色等模式需要）
            metadata: LUT 元数据（含 filament_names 等，保存为 _meta.json）

        Returns:
            (保存的文件路径, 颜色总数)
        """
        import json

        # 确保目标目录存在
        dir_path = os.path.dirname(file_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        # 保存 LUT（确保 uint8 类型）
        lut_data = lut_grid.astype(np.uint8)
        np.save(file_path, lut_data)

        # 计算颜色总数
        total_colors = lut_grid.reshape(-1, 3).shape[0]

        # 如果有 stacks，保存 stacks 索引文件
        if stacks is not None:
            base, ext = os.path.splitext(file_path)
            stacks_path = base + "_stacks.npy"
            np.save(stacks_path, stacks)

        # 保存 metadata 为 _meta.json 伴随文件
        if metadata is not None:
            base, ext = os.path.splitext(file_path)
            meta_path = base + "_meta.json"
            # 只保存可序列化的字段，排除 stacks（已单独保存）
            meta_to_save = {k: v for k, v in metadata.items() if k != 'stacks'}
            try:
                with open(meta_path, 'w', encoding='utf-8') as f:
                    json.dump(meta_to_save, f, ensure_ascii=False, indent=2)
                print(f"[LUT_GENERATOR] Saved metadata: {meta_path}")
            except Exception as e:
                print(f"[LUT_GENERATOR] Warning: Failed to save metadata: {e}")

        return file_path, total_colors
