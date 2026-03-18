# -*- coding: utf-8 -*-
"""Step 4: 缓存构建

从图像处理结果构建 preview_rgba 和 cache 字典，
供后续步骤和 API 层使用。
"""

from core.pipeline import PipelineContext, PipelineStep
from core.processing.preview_cache import build_preview_rgba, build_preview_cache


class CacheBuildStep(PipelineStep):
    """构建预览 RGBA 图像和缓存字典。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        p = ctx.params
        matched_rgb = ctx["matched_rgb"]
        material_matrix = ctx["material_matrix"]
        mask_solid = ctx["mask_solid"]
        target_w, target_h = ctx["dimensions"]

        preview_rgba = build_preview_rgba(
            matched_rgb=matched_rgb, mask_solid=mask_solid,
            target_w=target_w, target_h=target_h,
        )
        ctx["preview_rgba"] = preview_rgba

        cache = build_preview_cache(
            matched_rgb=matched_rgb,
            material_matrix=material_matrix,
            mask_solid=mask_solid,
            preview_rgba=preview_rgba,
            target_w=target_w,
            target_h=target_h,
            target_width_mm=p.get("target_width_mm", 60.0),
            color_conf=ctx["color_conf"],
            color_mode=p.get("color_mode", "4-Color (RYBW)"),
            quantize_colors=ctx["quantize_colors"],
            backing_color_id=int(p.get("backing_color_id", 0)),
            is_dark=bool(p.get("is_dark", True)),
            lut_metadata=ctx["lut_metadata"],
        )
        ctx["cache"] = cache

        return ctx
