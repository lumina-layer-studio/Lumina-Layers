# -*- coding: utf-8 -*-
"""Step 9: 坐标变换 + 3MF 导出"""

from __future__ import annotations

import os

from core.pipeline import PipelineContext, PipelineStep
from config import ModelingMode, OUTPUT_DIR
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata
from core.naming import generate_model_filename
from core.processing.scene_transform import apply_scene_transforms


class ExportStep(PipelineStep):
    """应用坐标变换（镜像/翻转），导出 3MF 文件。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        p = ctx.params
        scene = ctx['scene']
        target_w = ctx['target_w']
        pixel_scale = ctx['pixel_scale']
        preview_colors = ctx['preview_colors']
        valid_slot_names = ctx['valid_slot_names']
        color_mode = p['color_mode']
        structure_mode = ctx['structure_mode']
        image_path = p['image_path']
        modeling_mode = p.get('modeling_mode', ModelingMode.VECTOR)

        # 应用坐标变换（镜像/翻转）
        apply_scene_transforms(
            scene=scene, target_w=target_w, pixel_scale=pixel_scale,
            color_mode=color_mode, structure_mode=structure_mode,
        )

        ctx.progress(0.50, "导出 3MF 中... | Exporting 3MF...")

        base_name = os.path.splitext(os.path.basename(image_path))[0]
        out_path = os.path.join(OUTPUT_DIR, generate_model_filename(base_name, modeling_mode, color_mode))

        if len(scene.geometry) == 0:
            print(f"[CONVERTER] Error: No meshes generated, cannot export 3MF")
            ctx.result = (None, None, None, "[ERROR] Mesh generation failed: No valid meshes generated", None)
            ctx.early_return = True
            return ctx

        print_settings = {
            'layer_height': '0.08',
            'initial_layer_height': '0.08',
            'wall_loops': '1',
            'top_shell_layers': '0',
            'bottom_shell_layers': '0',
            'sparse_infill_density': '100%',
            'sparse_infill_pattern': 'zig-zag',
            'nozzle_temperature': ['220'] * 8,
            'bed_temperature': ['60'] * 8,
            'filament_type': ['PLA'] * 8,
            'print_speed': '100',
            'travel_speed': '150',
            'enable_support': '0',
            'brim_width': '5',
            'brim_type': 'auto_brim',
        }

        try:
            print(f"[CONVERTER] Exporting with BambuStudio metadata...")
            export_scene_with_bambu_metadata(
                scene=scene, output_path=out_path,
                slot_names=valid_slot_names, preview_colors=preview_colors,
                settings=print_settings, color_mode=color_mode,
            )
            print(f"[CONVERTER] 3MF exported with embedded settings: {out_path}")
        except Exception as e:
            print(f"[CONVERTER] Error exporting 3MF: {e}")
            ctx.result = (None, None, None, f"[ERROR] 3MF export failed: {e}", None)
            ctx.early_return = True
            return ctx

        ctx['out_path'] = out_path
        ctx['base_name'] = base_name

        return ctx
