# -*- coding: utf-8 -*-
"""Step 5: 2D 预览 + 挂件环"""

from __future__ import annotations

import numpy as np
from PIL import Image

from core.pipeline import PipelineContext, PipelineStep


class PreviewGenerationStep(PipelineStep):
    """生成 2D RGBA 预览图，计算挂件环信息。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        from core.processing.loop_utils import calculate_loop_info, draw_loop_on_preview

        p = ctx.params
        target_w, target_h = ctx['target_w'], ctx['target_h']
        matched_rgb = ctx['matched_rgb']
        mask_solid = ctx['mask_solid']

        # 生成 RGBA 预览
        preview_rgba = np.zeros((target_h, target_w, 4), dtype=np.uint8)
        preview_rgba[mask_solid, :3] = matched_rgb[mask_solid]
        preview_rgba[mask_solid, 3] = 255

        # 挂件环
        loop_info = None
        add_loop = p.get('add_loop', False)
        loop_pos = p.get('loop_pos')

        if add_loop and loop_pos is not None:
            loop_info = calculate_loop_info(
                loop_pos, p.get('loop_width', 0), p.get('loop_length', 0),
                p.get('loop_hole', 0),
                mask_solid, ctx['material_matrix'],
                target_w, target_h, ctx['pixel_scale'],
            )
            if loop_info:
                preview_rgba = draw_loop_on_preview(
                    preview_rgba, loop_info, ctx['color_conf'], ctx['pixel_scale'],
                )

        ctx['preview_rgba'] = preview_rgba
        ctx['preview_img'] = Image.fromarray(preview_rgba, mode='RGBA')
        ctx['loop_info'] = loop_info

        return ctx
