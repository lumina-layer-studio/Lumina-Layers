# -*- coding: utf-8 -*-
"""Step 7: Mesh 生成（并行）"""

from __future__ import annotations

from core.pipeline import PipelineContext, PipelineStep
from config import ModelingMode
from core.mesh_generators import get_mesher
from core.processing.mesh_builder import build_material_meshes


class MeshGenerationStep(PipelineStep):
    """为每种材质生成 3D mesh，支持并行。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        p = ctx.params
        modeling_mode = p.get('modeling_mode', ModelingMode.VECTOR)
        full_matrix = ctx['full_matrix']
        target_h = ctx['target_h']
        pixel_scale = ctx['pixel_scale']
        slot_names = ctx['slot_names']
        preview_colors = ctx['preview_colors']

        ctx.progress(0.30, "生成 3D 网格中... | Generating meshes...")

        mesher = get_mesher(modeling_mode)

        scene, valid_slot_names, transform = build_material_meshes(
            mesher=mesher,
            full_matrix=full_matrix,
            target_h=target_h,
            pixel_scale=pixel_scale,
            slot_names=slot_names,
            preview_colors=preview_colors,
        )

        ctx['scene'] = scene
        ctx['valid_slot_names'] = valid_slot_names
        ctx['mesher'] = mesher
        ctx['transform'] = transform

        return ctx
