# -*- coding: utf-8 -*-
"""Step 1: 输入验证 + LUT 路径解析"""

from __future__ import annotations

from core.pipeline import PipelineContext, PipelineStep
from config import ModelingMode


class InputValidationStep(PipelineStep):
    """验证输入参数，解析 LUT 路径，处理 separate_backing 标志。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        p = ctx.params
        image_path = p['image_path']
        lut_path = p['lut_path']

        if image_path is None:
            ctx.result = (None, None, None, "[ERROR] Please upload an image", None)
            ctx.early_return = True
            return ctx
        if lut_path is None:
            ctx.result = (None, None, None,
                          "[WARNING] Please select or upload a .npy calibration file!", None)
            ctx.early_return = True
            return ctx

        # 解析 LUT 路径
        if isinstance(lut_path, str):
            actual_lut_path = lut_path
        elif hasattr(lut_path, 'name'):
            actual_lut_path = lut_path.name
        else:
            ctx.result = (None, None, None, "[ERROR] Invalid LUT file format", None)
            ctx.early_return = True
            return ctx

        ctx['actual_lut_path'] = actual_lut_path

        # separate_backing 处理
        separate_backing = p.get('separate_backing', False)
        try:
            separate_backing = bool(separate_backing) if separate_backing is not None else False
        except Exception as e:
            print(f"[CONVERTER] Error reading separate_backing checkbox state: {e}, using default (False)")
            separate_backing = False

        backing_color_id = p.get('backing_color_id', 0)
        if separate_backing:
            backing_color_id = -2
            print(f"[CONVERTER] Backing separation enabled: backing will be a separate object (white)")
        else:
            print(f"[CONVERTER] Backing separation disabled: backing merged with first layer (backing_color_id={backing_color_id})")

        ctx['separate_backing'] = separate_backing
        ctx['backing_color_id'] = backing_color_id

        modeling_mode = p.get('modeling_mode', ModelingMode.VECTOR)
        print(f"[CONVERTER] Starting conversion...")
        print(f"[CONVERTER] Mode: {modeling_mode.get_display_name()}, Quantize: {p.get('quantize_colors', 32)}")
        print(f"[CONVERTER] Filters: blur_kernel={p.get('blur_kernel', 0)}, smooth_sigma={p.get('smooth_sigma', 10)}")
        print(f"[CONVERTER] LUT: {actual_lut_path}")

        return ctx
