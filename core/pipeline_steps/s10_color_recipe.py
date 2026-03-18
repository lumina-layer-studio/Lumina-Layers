# -*- coding: utf-8 -*-
"""Step 10: Color Recipe 报告"""

from __future__ import annotations

import os

import numpy as np

from core.pipeline import PipelineContext, PipelineStep
from config import OUTPUT_DIR


class ColorRecipeStep(PipelineStep):
    """生成颜色配方报告。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        mask_solid = ctx['mask_solid']
        processor = ctx['processor']
        out_path = ctx['out_path']
        lut_metadata = ctx.get('lut_metadata')
        matched_rgb = ctx['matched_rgb']
        material_matrix = ctx['material_matrix']

        color_recipe_path = None
        recipe_policy = os.getenv("LUMINA_COLOR_RECIPE_POLICY", "auto").strip().lower()
        try:
            recipe_auto_max_pixels = int(os.getenv("LUMINA_COLOR_RECIPE_AUTO_MAX_PIXELS", "1200000"))
        except Exception:
            recipe_auto_max_pixels = 1200000

        solid_pixels = int(np.count_nonzero(mask_solid))
        enable_recipe = recipe_policy == "on" or (
            recipe_policy == "auto" and solid_pixels <= recipe_auto_max_pixels
        )

        if enable_recipe:
            try:
                from utils.color_recipe_logger import ColorRecipeLogger
                model_filename = os.path.basename(out_path)
                color_recipe_path = ColorRecipeLogger.create_from_processor(
                    processor=processor, output_dir=OUTPUT_DIR,
                    model_filename=model_filename,
                    matched_rgb=matched_rgb, material_matrix=material_matrix,
                    mask_solid=mask_solid, metadata=lut_metadata,
                )
            except Exception as e:
                print(f"[CONVERTER] Warning: Failed to generate color recipe report: {e}")
        else:
            print(f"[CONVERTER] Skipping color recipe report: policy={recipe_policy}, "
                  f"solid_pixels={solid_pixels}, auto_max={recipe_auto_max_pixels}")

        ctx['color_recipe_path'] = color_recipe_path
        return ctx
