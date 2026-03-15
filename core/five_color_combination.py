#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5色组合查询功能 - 核心模块

从 8 个基础颜色中选择 5 次（可重复），查询对应的结果颜色。
"""

import numpy as np
from typing import Tuple, List, Optional
from dataclasses import dataclass


@dataclass
class ColorQueryResult:
    """颜色查询结果"""
    found: bool
    selected_indices: List[int]  # 用户选择的 5 个索引
    result_rgb: Optional[Tuple[int, int, int]]  # 结果 RGB 颜色
    row_index: int  # 在 stack LUT 中的行索引
    message: str  # 状态消息
    source: str = ""  # 来源标识（例如 "Aliz-PETG-8色"）


class ColorCountDetector:
    """颜色数量检测器"""
    
    # 已知的 LUT 格式映射
    KNOWN_FORMATS = {
        1024: 4,  # 4-color: (32, 32, 3) = 1024 combinations
        2468: 5,  # 5-color: (77, 32, 3) = 2468 combinations
        1296: 6,  # 6-color: (36, 36, 3) = 1296 combinations
        2738: 8,  # 8-color: (74, 37, 3) = 2738 combinations
    }
    
    @staticmethod
    def detect_color_count(lut_data: np.ndarray) -> Tuple[int, int]:
        """检测 LUT 的颜色数量
        
        Args:
            lut_data: LUT 数组数据
            
        Returns:
            (颜色数量, 组合总数)
            例如: (8, 2738) 表示 8 色 LUT，共 2738 个组合
        """
        # 将数据 reshape 为 (N, 3) 格式
        reshaped = lut_data.reshape(-1, 3)
        combination_count = reshaped.shape[0]
        
        # 查找已知格式
        if combination_count in ColorCountDetector.KNOWN_FORMATS:
            color_count = ColorCountDetector.KNOWN_FORMATS[combination_count]
            return (color_count, combination_count)
        
        # 未知格式，返回 0 表示无法识别
        return (0, combination_count)


class StackFileManager:
    """Stack 文件管理器"""
    
    # Stack 文件命名规范
    STACK_FILE_PATTERN = "assets/smart_{n}color_stacks.npy"
    
    @staticmethod
    def find_stack_file(color_count: int) -> Optional[str]:
        """查找指定颜色数量的 stack 文件
        
        Args:
            color_count: 颜色数量（4, 5, 6, 8 等）
            
        Returns:
            stack 文件路径，如果不存在则返回 None
        """
        import os
        stack_path = StackFileManager.STACK_FILE_PATTERN.format(n=color_count)
        
        if os.path.exists(stack_path):
            return stack_path
        return None
    
    @staticmethod
    def validate_stack_format(stack_data: np.ndarray, color_count: int) -> bool:
        """验证 stack 数据格式
        
        Args:
            stack_data: stack 数组
            color_count: 期望的颜色数量
            
        Returns:
            是否有效
        """
        # 检查形状
        if stack_data.ndim != 2 or stack_data.shape[1] != 5:
            return False
        
        # 检查值范围
        if stack_data.min() < 0 or stack_data.max() >= color_count:
            return False
        
        return True


class StackLUTLoader:
    """堆叠查找表加载器"""
    
    @staticmethod
    def load_stack_lut(file_path: str) -> Tuple[bool, str, Optional[np.ndarray]]:
        """加载堆叠查找表
        
        Args:
            file_path: NPY 文件路径
            
        Returns:
            tuple: (success, message, stack_data)
                - success: 是否成功
                - message: 状态消息
                - stack_data: (N, 5) 数组，每行是一个 5 色组合索引
        """
        try:
            data = np.load(file_path)
            
            # 验证格式
            if data.ndim != 2:
                return False, f"错误：数组维度应为 2，实际为 {data.ndim}", None
            
            if data.shape[1] != 5:
                return False, f"错误：数组列数应为 5，实际为 {data.shape[1]}", None
            
            # 验证值范围
            if data.min() < 0 or data.max() > 7:
                return False, f"错误：数组值应在 0-7 范围内，实际范围 {data.min()}-{data.max()}", None
            
            return True, f"成功加载 {len(data)} 个组合", data
            
        except Exception as e:
            return False, f"加载失败: {str(e)}", None
    
    @staticmethod
    def load_npz_file(file_path: str) -> Tuple[bool, str, Optional[np.ndarray], Optional[np.ndarray]]:
        """加载 NPZ 文件（包含 rgb 和 stacks）
        
        Args:
            file_path: NPZ 文件路径
            
        Returns:
            tuple: (success, message, stack_data, rgb_data)
                - success: 是否成功
                - message: 状态消息
                - stack_data: (N, 5) 数组，每行是一个 5 色组合索引
                - rgb_data: (N, 3) 数组，每行是一个 RGB 颜色
        """
        try:
            data = np.load(file_path)
            
            # 验证必需的键
            if 'rgb' not in data:
                return False, "错误：NPZ 文件缺少 'rgb' 数据", None, None
            
            if 'stacks' not in data:
                return False, "错误：NPZ 文件缺少 'stacks' 数据", None, None
            
            rgb_data = data['rgb']
            stack_data = data['stacks']
            
            # 验证 RGB 数据格式
            if rgb_data.ndim != 2 or rgb_data.shape[1] != 3:
                return False, f"错误：RGB 数据形状应为 (N, 3)，实际为 {rgb_data.shape}", None, None
            
            # 验证 stack 数据格式
            if stack_data.ndim != 2 or stack_data.shape[1] != 5:
                return False, f"错误：Stack 数据形状应为 (N, 5)，实际为 {stack_data.shape}", None, None
            
            # 验证数据长度一致
            if len(rgb_data) != len(stack_data):
                return False, f"错误：RGB 和 Stack 数据长度不一致: {len(rgb_data)} vs {len(stack_data)}", None, None
            
            # 验证 RGB 值范围
            if rgb_data.min() < 0 or rgb_data.max() > 255:
                return False, f"错误：RGB 值应在 0-255 范围内，实际范围 {rgb_data.min()}-{rgb_data.max()}", None, None
            
            return True, f"成功加载 {len(rgb_data)} 个组合", stack_data, rgb_data
            
        except Exception as e:
            return False, f"加载失败: {str(e)}", None, None
    
    @staticmethod
    def load_lut_rgb(file_path: str) -> Tuple[bool, str, Optional[np.ndarray]]:
        """加载 LUT RGB 颜色数据
        
        Args:
            file_path: NPY 文件路径（包含 RGB 颜色数据）
            
        Returns:
            tuple: (success, message, rgb_data)
                - success: 是否成功
                - message: 状态消息
                - rgb_data: (N, 3) 数组，每行是一个 RGB 颜色
        """
        try:
            data = np.load(file_path)
            
            # 处理不同的数组形状
            if data.ndim == 3:
                # 例如 (6, 6, 3) -> reshape 为 (36, 3)
                data = data.reshape(-1, 3)
            elif data.ndim == 2 and data.shape[1] == 3:
                # 已经是 (N, 3) 格式
                pass
            else:
                return False, f"错误：无法解析 RGB 数据，形状为 {data.shape}", None
            
            # 验证 RGB 值范围
            if data.min() < 0 or data.max() > 255:
                return False, f"错误：RGB 值应在 0-255 范围内，实际范围 {data.min()}-{data.max()}", None
            
            return True, f"成功加载 {len(data)} 个颜色", data
            
        except Exception as e:
            return False, f"加载失败: {str(e)}", None

    @staticmethod
    def load_sources_from_json(npz_path: str) -> List[str]:
        """Load source info from NPZ 'sources' field, or fall back to companion JSON.
        优先从 NPZ 的 sources 字段读取，回退到同名 JSON 文件。

        Args:
            npz_path: NPZ/NPY 文件路径

        Returns:
            list: source 字符串列表，如果没有则返回空列表
        """
        import json
        # 1) 尝试从 NPZ 的 sources 字段读取
        if npz_path.endswith('.npz'):
            try:
                data = np.load(npz_path, allow_pickle=True)
                if 'sources' in data:
                    return [str(s) for s in data['sources']]
            except Exception:
                pass
        # 2) 回退到同名 JSON
        json_path = npz_path.rsplit('.', 1)[0] + '.json'
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                return [entry.get('source', '') if isinstance(entry, dict) else '' for entry in data]
        except Exception:
            pass
        return []


class ColorQueryEngine:
    """颜色查询引擎"""
    
    def __init__(self, stack_lut: Optional[np.ndarray], lut_rgb: np.ndarray, color_count: Optional[int] = None, sources: Optional[List[str]] = None):
        """初始化查询引擎
        
        Args:
            stack_lut: (N, 5) 堆叠查找表（可选，如果没有则使用动态查询）
            lut_rgb: (N, 3) RGB 颜色数据
            color_count: 颜色数量（可选，如果没有则自动检测）
            sources: 每条记录的来源标识列表（可选）
        """
        self.lut_rgb = lut_rgb
        self.stack_lut = stack_lut
        self.sources = sources or []
        
        # 检测颜色数量
        if color_count is not None:
            self.color_count = color_count
        elif stack_lut is not None:
            # 从 stack_lut 的最大值推断
            max_color_idx = int(stack_lut.max())
            self.color_count = max_color_idx + 1
        else:
            # 尝试从 lut_rgb 检测
            detected_count, _ = ColorCountDetector.detect_color_count(lut_rgb)
            self.color_count = detected_count if detected_count > 0 else 8  # 默认 8 色
        
        # 验证 stack_lut 和 lut_rgb 长度一致（如果有 stack_lut）
        if stack_lut is not None and len(stack_lut) != len(lut_rgb):
            raise ValueError(f"Stack LUT 和 RGB 数据长度不匹配: {len(stack_lut)} vs {len(lut_rgb)}")
        
        # 提取基础颜色（从前 color_count 行，每行应该是 [i,i,i,i,i]）
        self.base_colors = []
        for i in range(self.color_count):
            if i < len(lut_rgb):
                self.base_colors.append(tuple(lut_rgb[i]))
            else:
                # 如果 LUT 不够，使用默认颜色
                self.base_colors.append((128, 128, 128))
    
    def query(self, selected_indices: List[int]) -> ColorQueryResult:
        """查询 5 色组合
        
        Args:
            selected_indices: 用户选择的 5 个索引，例如 [0, 1, 0, 3, 2]
            
        Returns:
            ColorQueryResult: 查询结果
        """
        # 验证输入
        if len(selected_indices) != 5:
            return ColorQueryResult(
                found=False,
                selected_indices=selected_indices,
                result_rgb=None,
                row_index=-1,
                message=f"错误：需要选择 5 次颜色，当前选择了 {len(selected_indices)} 次"
            )
        
        # 如果有 stack_lut，使用快速查询
        if self.stack_lut is not None:
            return self._query_with_stack(selected_indices)
        else:
            # 否则使用动态查询
            return self._query_without_stack(selected_indices)
    
    def _query_with_stack(self, selected_indices: List[int]) -> ColorQueryResult:
        """使用 stack 文件进行快速查询"""
        target = np.array(selected_indices)
        matches = np.where((self.stack_lut == target).all(axis=1))[0]
        
        if len(matches) > 0:
            row_idx = matches[0]
            result_rgb = tuple(self.lut_rgb[row_idx])
            source = self.sources[row_idx] if row_idx < len(self.sources) else ""
            return ColorQueryResult(
                found=True,
                selected_indices=selected_indices,
                result_rgb=result_rgb,
                row_index=row_idx,
                message=f"找到匹配！行索引: {row_idx}",
                source=source
            )
        else:
            return ColorQueryResult(
                found=False,
                selected_indices=selected_indices,
                result_rgb=None,
                row_index=-1,
                message="未找到匹配的组合"
            )
    
    def _query_without_stack(self, selected_indices: List[int]) -> ColorQueryResult:
        """动态查询（无 stack 文件）"""
        from itertools import product
        
        # 生成所有可能的 5 色组合
        target = tuple(selected_indices)
        
        # 遍历所有组合查找匹配
        for idx, combo in enumerate(product(range(self.color_count), repeat=5)):
            if combo == target:
                if idx < len(self.lut_rgb):
                    result_rgb = tuple(self.lut_rgb[idx])
                    source = self.sources[idx] if idx < len(self.sources) else ""
                    return ColorQueryResult(
                        found=True,
                        selected_indices=selected_indices,
                        result_rgb=result_rgb,
                        row_index=idx,
                        message=f"找到匹配！行索引: {idx}（动态查询）",
                        source=source
                    )
        
        return ColorQueryResult(
            found=False,
            selected_indices=selected_indices,
            result_rgb=None,
            row_index=-1,
            message="未找到匹配的组合"
        )
    
    def get_base_colors(self) -> List[Tuple[int, int, int]]:
        """获取基础颜色
        
        Returns:
            list: 基础颜色 RGB 元组列表
        """
        return self.base_colors
    
    def get_color_names(self) -> List[str]:
        """获取基础颜色的名称
        
        Returns:
            list: 颜色名称列表
        """
        return [get_color_name_from_rgb(rgb) for rgb in self.base_colors]
    
    def reverse_selection(self, selected_indices: List[int]) -> List[int]:
        """反转选择顺序
        
        Args:
            selected_indices: 原始选择，例如 [0, 1, 0, 3, 2]
            
        Returns:
            list: 反转后的选择，例如 [2, 3, 0, 1, 0]
        """
        return list(reversed(selected_indices))


# 辅助函数
def rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    """将 RGB 转换为十六进制颜色代码
    
    Args:
        rgb: (r, g, b) 元组
        
    Returns:
        str: 十六进制颜色代码，例如 "#FF5733"
    """
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def format_selection_sequence(selected_indices: List[int], color_names: Optional[List[str]] = None) -> str:
    """格式化选择序列为可读字符串
    
    Args:
        selected_indices: 选择的索引列表，例如 [0, 1, 0, 3, 2]
        color_names: 颜色名称列表（可选），例如 ["红", "黄", "蓝", "白"]
        
    Returns:
        str: 格式化字符串，例如 "红(0) → 黄(1) → 红(0) → 白(3) → 蓝(2)"
    """
    if not selected_indices:
        return ""
    
    if color_names:
        # 使用颜色名称和索引
        parts = []
        for i in selected_indices:
            if i < len(color_names):
                parts.append(f"{color_names[i]}({i})")
            else:
                parts.append(f"颜色{i}")
        return " → ".join(parts)
    else:
        # 只使用索引
        return " → ".join([f"颜色{i}" for i in selected_indices])


def get_color_name_from_rgb(rgb: Tuple[int, int, int]) -> str:
    """根据 RGB 值推断颜色名称
    
    Args:
        rgb: (r, g, b) 元组
        
    Returns:
        str: 颜色名称
    """
    r, g, b = rgb
    
    # 定义颜色阈值
    threshold = 100
    
    # 黑色
    if r < threshold and g < threshold and b < threshold:
        return "黑"
    
    # 白色
    if r > 255 - threshold and g > 255 - threshold and b > 255 - threshold:
        return "白"
    
    # 红色系
    if r > g + threshold and r > b + threshold:
        if g > threshold or b > threshold:
            return "橙" if g > b else "品红"
        return "红"
    
    # 绿色系
    if g > r + threshold and g > b + threshold:
        return "绿"
    
    # 蓝色系
    if b > r + threshold and b > g + threshold:
        if r > threshold:
            return "紫"
        return "蓝"
    
    # 黄色系
    if r > threshold and g > threshold and b < threshold:
        return "黄"
    
    # 青色系
    if g > threshold and b > threshold and r < threshold:
        return "青"
    
    # 灰色
    if abs(r - g) < 50 and abs(g - b) < 50 and abs(r - b) < 50:
        return "灰"
    
    return "混合色"
