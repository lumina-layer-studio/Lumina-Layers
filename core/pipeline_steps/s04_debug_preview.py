# -*- coding: utf-8 -*-
"""Step 4: Debug 预览保存"""

from __future__ import annotations

from core.pipeline import PipelineContext, PipelineStep
from config import ModelingMode


class DebugPreviewStep(PipelineStep):
    """保存高保真模式的 debug 预览图。"""

    def should_skip(self, ctx: PipelineContext) -> bool:
        debug_data = ctx.get('debug_data')
        mode_info = ctx.get('mode_info')
        if debug_data is None:
            return True
        if mode_info is None or mode_info.get('mode') != ModelingMode.HIGH_FIDELITY:
            return True
        return False

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        from core.processing.debug_preview import save_debug_preview

        try:
            save_debug_preview(
                debug_data=ctx['debug_data'],
                material_matrix=ctx['material_matrix'],
                mask_solid=ctx['mask_solid'],
                image_path=ctx.params['image_path'],
                mode_name=ctx['mode_info']['name'],
                num_materials=len(ctx['slot_names']),
            )
        except Exception as e:
            print(f"[CONVERTER] Warning: Failed to save debug preview: {e}")
        return ctx
