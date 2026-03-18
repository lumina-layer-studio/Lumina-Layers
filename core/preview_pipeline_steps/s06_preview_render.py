# -*- coding: utf-8 -*-
"""Step 6: 预览渲染

调用 render_preview 生成最终的显示图像，
组装最终返回结果。
"""

from core.pipeline import PipelineContext, PipelineStep


class PreviewRenderStep(PipelineStep):
    """渲染最终预览图像并组装返回结果。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        from core.processing.preview_render import render_preview

        p = ctx.params
        preview_rgba = ctx["preview_rgba"]
        color_conf = ctx["color_conf"]
        cache = ctx["cache"]
        color_palette = ctx["color_palette"]
        target_w, target_h = ctx["dimensions"]

        display = render_preview(
            preview_rgba, None, 0, 0, 0, 0, False, color_conf,
            target_width_mm=p.get("target_width_mm", 60.0),
            is_dark=bool(p.get("is_dark", True)),
        )

        num_colors = len(color_palette)
        status = (f"[OK] Preview ({target_w}×{target_h}px, {num_colors} colors)"
                  " | Click image to place loop")

        ctx.result = {
            "display": display,
            "cache": cache,
            "status": status,
        }

        return ctx
