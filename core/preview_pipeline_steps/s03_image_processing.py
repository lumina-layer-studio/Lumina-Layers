# -*- coding: utf-8 -*-
"""Step 3: 图像处理

使用 LuminaImageProcessor 执行核心图像处理：
量化、颜色匹配、材料矩阵生成等。
"""

from core.pipeline import PipelineContext, PipelineStep


class PreviewImageProcessingStep(PipelineStep):
    """调用 LuminaImageProcessor.process_image 执行核心图像处理。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        from core.image_processing import LuminaImageProcessor

        p = ctx.params
        actual_lut_path = ctx["actual_lut_path"]
        color_mode = p.get("color_mode", "4-Color (RYBW)")
        hue_weight = float(p.get("hue_weight", 0.0))
        chroma_gate = float(p.get("chroma_gate", 15.0))
        enable_cleanup = bool(p.get("enable_cleanup", True))

        try:
            print(f"[Core generate_preview_cached] hue_weight={hue_weight}, "
                  f"chroma_gate={chroma_gate}, color_mode={color_mode}")
            processor = LuminaImageProcessor(
                actual_lut_path, color_mode,
                hue_weight=hue_weight, chroma_gate=chroma_gate,
            )
            processor.enable_cleanup = enable_cleanup
            result = processor.process_image(
                image_path=ctx["image_path"],
                target_width_mm=p.get("target_width_mm", 60.0),
                modeling_mode=ctx["modeling_mode"],
                quantize_colors=ctx["quantize_colors"],
                auto_bg=p.get("auto_bg", False),
                bg_tol=p.get("bg_tol", 40),
                blur_kernel=0,
                smooth_sigma=10,
            )
        except Exception as e:
            ctx.result = {"display": None, "cache": None,
                          "status": f"[ERROR] Preview generation failed: {e}"}
            ctx.early_return = True
            return ctx

        ctx["process_result"] = result
        ctx["matched_rgb"] = result["matched_rgb"]
        ctx["material_matrix"] = result["material_matrix"]
        ctx["mask_solid"] = result["mask_solid"]
        ctx["dimensions"] = result["dimensions"]

        return ctx
