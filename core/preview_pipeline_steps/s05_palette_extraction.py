# -*- coding: utf-8 -*-
"""Step 5: 调色板提取

确保 quantized_image 可用，提取颜色调色板，
将结果写入 cache。
"""

from core.pipeline import PipelineContext, PipelineStep


class PaletteExtractionStep(PipelineStep):
    """提取颜色调色板并写入缓存。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        from core.processing.palette import extract_color_palette, ensure_quantized_image_in_cache

        cache = ctx["cache"]
        result = ctx["process_result"]

        # 统一缓存契约：保证 quantized_image 始终可用
        cache["debug_data"] = result.get("debug_data") if isinstance(result, dict) else None
        cache["quantized_image"] = result.get("quantized_image")
        ensure_quantized_image_in_cache(cache)

        # 提取颜色调色板
        color_palette = extract_color_palette(cache)
        cache["color_palette"] = color_palette

        ctx["color_palette"] = color_palette

        return ctx
