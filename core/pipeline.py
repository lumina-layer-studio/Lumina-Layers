# -*- coding: utf-8 -*-
"""
Lumina Studio - Processing Pipeline Framework
图像处理管道框架

提供模块化的管道架构，每个处理步骤定义清晰的输入输出，
支持灵活地插入、移除、替换处理步骤。

Usage:
    pipeline = Pipeline([
        InputValidationStep(),
        ImageProcessingStep(),
        ColorReplacementStep(),
        VoxelBuildStep(),
        MeshGenerationStep(),
        ExportStep(),
    ])
    ctx = PipelineContext(params=params)
    ctx = pipeline.run(ctx)
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np


@dataclass
class PipelineContext:
    """管道上下文，承载所有参数和中间数据。

    每个 Step 从 ctx 读取输入，将结果写回 ctx。
    params: 原始调用参数（只读）
    data:   中间数据（各 step 读写）
    result: 最终输出
    timings: 各步骤耗时
    """

    # 原始参数 —— 由调用方一次性填入，Step 只读
    params: Dict[str, Any] = field(default_factory=dict)

    # 中间数据 —— Step 之间传递的载体
    data: Dict[str, Any] = field(default_factory=dict)

    # 最终结果
    result: Dict[str, Any] = field(default_factory=dict)

    # 各步骤耗时 (step_name -> seconds)
    timings: Dict[str, float] = field(default_factory=dict)

    # 是否提前终止（某个 step 可以设置此标志跳过后续步骤）
    early_return: bool = False

    # progress 回调
    _progress_fn: Optional[Callable] = None

    def progress(self, val: float, desc: str = ""):
        if self._progress_fn is not None:
            self._progress_fn(val, desc=desc)

    # 便捷访问
    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __setitem__(self, key: str, value: Any):
        self.data[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


class PipelineStep(ABC):
    """管道步骤基类。

    每个子类实现 execute(ctx) 方法。
    name 属性用于日志和计时。
    """

    @property
    def name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def execute(self, ctx: PipelineContext) -> PipelineContext:
        """执行处理步骤，返回更新后的 ctx。"""
        ...

    def should_skip(self, ctx: PipelineContext) -> bool:
        """可选：返回 True 则跳过此步骤。"""
        return False


class Pipeline:
    """有序管道，按顺序执行 Step 列表。"""

    def __init__(self, steps: Optional[List[PipelineStep]] = None):
        self.steps: List[PipelineStep] = list(steps or [])

    # ---- 管道编辑 API ----

    def append(self, step: PipelineStep) -> "Pipeline":
        self.steps.append(step)
        return self

    def insert_before(self, target_name: str, step: PipelineStep) -> "Pipeline":
        """在名为 target_name 的步骤之前插入。"""
        for i, s in enumerate(self.steps):
            if s.name == target_name:
                self.steps.insert(i, step)
                return self
        raise ValueError(f"Step '{target_name}' not found in pipeline")

    def insert_after(self, target_name: str, step: PipelineStep) -> "Pipeline":
        """在名为 target_name 的步骤之后插入。"""
        for i, s in enumerate(self.steps):
            if s.name == target_name:
                self.steps.insert(i + 1, step)
                return self
        raise ValueError(f"Step '{target_name}' not found in pipeline")

    def remove(self, step_name: str) -> "Pipeline":
        """按名称移除步骤。"""
        self.steps = [s for s in self.steps if s.name != step_name]
        return self

    def replace(self, step_name: str, new_step: PipelineStep) -> "Pipeline":
        """按名称替换步骤。"""
        for i, s in enumerate(self.steps):
            if s.name == step_name:
                self.steps[i] = new_step
                return self
        raise ValueError(f"Step '{step_name}' not found in pipeline")

    @property
    def step_names(self) -> List[str]:
        return [s.name for s in self.steps]

    # ---- 执行 ----

    def run(self, ctx: PipelineContext) -> PipelineContext:
        """按顺序执行所有步骤。"""
        for step in self.steps:
            if ctx.early_return:
                break
            if step.should_skip(ctx):
                print(f"[PIPELINE] Skipping: {step.name}")
                continue
            t0 = time.perf_counter()
            try:
                ctx = step.execute(ctx)
            except Exception as e:
                print(f"[PIPELINE] Error in {step.name}: {e}")
                raise
            elapsed = time.perf_counter() - t0
            ctx.timings[step.name] = elapsed
            print(f"[PIPELINE] {step.name} done ({elapsed:.3f}s)")
        return ctx
