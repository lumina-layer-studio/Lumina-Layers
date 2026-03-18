# -*- coding: utf-8 -*-
"""Step 2: LUT 元数据加载

加载 LUT 校准文件的元数据（调色板名称等），
以及颜色系统配置。
"""

from core.pipeline import PipelineContext, PipelineStep


class LutMetadataStep(PipelineStep):
    """加载 LUT 元数据和颜色系统配置。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        from utils.lut_manager import LUTManager
        from config import ColorSystem

        actual_lut_path = ctx["actual_lut_path"]
        color_mode = ctx.params.get("color_mode", "4-Color (RYBW)")

        color_conf = ColorSystem.get(color_mode)
        ctx["color_conf"] = color_conf

        lut_metadata = None
        if LUTManager is not None:
            try:
                _, _, lut_metadata = LUTManager.load_lut_with_metadata(actual_lut_path)
            except Exception as e:
                print(f"[CONVERTER] Warning: Failed to load LUT metadata: {e}")

        ctx["lut_metadata"] = lut_metadata

        return ctx
