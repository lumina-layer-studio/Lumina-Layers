"""
耗材配置文件加载器
负责读取 JSON 格式的耗材 K/S 参数并映射字段名
"""

import json
import os
from typing import Dict, List


class FilamentLoader:
    """耗材配置文件加载器，负责读取 JSON 并映射字段名"""

    @staticmethod
    def load(file_path: str) -> List[Dict]:
        """
        加载耗材配置文件

        Args:
            file_path: JSON 文件路径

        Returns:
            标准化耗材列表，每个元素包含:
            - name: str
            - color: str (hex)
            - FILAMENT_K: List[float] (RGB 三通道)
            - FILAMENT_S: List[float] (RGB 三通道)

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 格式无效或缺少必要字段
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"耗材配置文件不存在: {file_path}")

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件格式无效: {file_path}, 原因: {e}")

        if not isinstance(data, dict):
            raise ValueError(f"配置文件格式无效: {file_path}, 原因: 顶层应为 JSON 对象")

        if 'filaments' not in data:
            raise ValueError("配置文件缺少 filaments 字段")

        filaments = data['filaments']
        if not isinstance(filaments, list):
            raise ValueError("配置文件 filaments 字段应为数组")
        result = []
        for i, filament in enumerate(filaments):
            FilamentLoader.validate_filament(filament, i)
            result.append({
                'name': filament['name'],
                'color': filament.get('color', '#000000'),
                'FILAMENT_K': filament['K'],
                'FILAMENT_S': filament['S'],
            })

        return result

    @staticmethod
    def validate_filament(filament: Dict, index: int) -> None:
        """
        验证单个耗材的字段完整性

        Args:
            filament: 耗材字典
            index: 耗材在列表中的索引（用于错误提示）

        Raises:
            ValueError: 缺少必要字段或字段格式不正确
        """
        name = filament.get('name', f'耗材#{index}')

        for field in ('K', 'S'):
            if field not in filament:
                raise ValueError(f"耗材 '{name}' 缺少 {field} 字段")
            value = filament[field]
            if not isinstance(value, list) or len(value) != 3:
                raise ValueError(f"耗材 '{name}' 的 {field} 应为 3 通道数组")
