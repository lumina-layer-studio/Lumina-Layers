# -*- coding: utf-8 -*-
"""Step 1: 预览输入验证

验证 image_path、lut_path、modeling_mode、quantize_colors 等参数，
将验证后的值写入 ctx.data 供后续步骤使用。
"""

from core.pipeline import PipelineContext, PipelineStep


class PreviewInputValidationStep(PipelineStep):
    """验证并规范化预览生成的输入参数。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        from config import ModelingMode

        p = ctx.params

        # --- image_path ---
        image_path = p.get("image_path")
        if image_path is None:
            ctx.result = {"display": None, "cache": None,
                          "status": "[ERROR] Please upload an image"}
            ctx.early_return = True
            return ctx

        # --- lut_path ---
        lut_path = p.get("lut_path")
        if lut_path is None:
            ctx.result = {"display": None, "cache": None,
                          "status": "[WARNING] Please select or upload calibration file"}
            ctx.early_return = True
            return ctx

        if isinstance(lut_path, str):
            actual_lut_path = lut_path
        elif hasattr(lut_path, "name"):
            actual_lut_path = lut_path.name
        else:
            ctx.result = {"display": None, "cache": None,
                          "status": "[ERROR] Invalid LUT file format"}
            ctx.early_return = True
            return ctx

        # --- modeling_mode ---
        modeling_mode = p.get("modeling_mode", ModelingMode.HIGH_FIDELITY)
        if modeling_mode is None or modeling_mode == "none":
            modeling_mode = ModelingMode.HIGH_FIDELITY
            print("[CONVERTER] Warning: modeling_mode was None, using default HIGH_FIDELITY")
        else:
            modeling_mode = ModelingMode(modeling_mode)

        # --- quantize_colors ---
        quantize_colors = max(8, min(256, int(p.get("quantize_colors", 64))))

        # 写入 ctx.data
        ctx["image_path"] = image_path
        ctx["actual_lut_path"] = actual_lut_path
        ctx["modeling_mode"] = modeling_mode
        ctx["quantize_colors"] = quantize_colors

        return ctx
