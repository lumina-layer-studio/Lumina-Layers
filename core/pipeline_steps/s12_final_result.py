# -*- coding: utf-8 -*-
"""Step 12: 生成状态消息 + 组装最终结果"""

from __future__ import annotations

from core.pipeline import PipelineContext, PipelineStep
from utils import Stats


class FinalResultStep(PipelineStep):
    """组装最终返回值。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        mode_info = ctx['mode_info']
        target_w, target_h = ctx['target_w'], ctx['target_h']
        loop_added = ctx.get('loop_added', False)
        loop_info = ctx.get('loop_info')
        slot_names = ctx['slot_names']
        heightmap_stats = ctx.get('heightmap_stats')
        glb_path = ctx.get('glb_path')

        Stats.increment("conversions")

        # 输出计时信息
        if ctx.timings:
            parts = [f"{k}={v:.3f}" for k, v in ctx.timings.items()]
            total = sum(ctx.timings.values())
            print(f"[PIPELINE] Timings (s): {', '.join(parts)}, total={total:.3f}")

        mode_name = mode_info['mode'].get_display_name()
        msg = f"✅ Conversion complete ({mode_name})! Resolution: {target_w}×{target_h}px"

        if heightmap_stats is not None:
            msg += (f" | 📊 高度图: {heightmap_stats['min_mm']:.1f}mm ~ "
                    f"{heightmap_stats['max_mm']:.1f}mm (avg {heightmap_stats['avg_mm']:.1f}mm)")

        if loop_added and loop_info:
            msg += f" | Loop: {slot_names[loop_info['color_id']]}"

        total_pixels = target_w * target_h
        if glb_path and total_pixels > 500_000:
            msg += " | 3D preview simplified"

        ctx.result = (
            ctx.get('out_path'),
            glb_path,
            ctx.get('preview_img'),
            msg,
            ctx.get('color_recipe_path'),
        )
        return ctx
