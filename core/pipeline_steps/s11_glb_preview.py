# -*- coding: utf-8 -*-
"""Step 11: GLB 3D 预览导出"""

from __future__ import annotations

import os

import trimesh

from core.pipeline import PipelineContext, PipelineStep
from config import PrinterConfig, OUTPUT_DIR
from core.geometry_utils import create_keychain_loop
from core.naming import generate_preview_filename


class GlbPreviewStep(PipelineStep):
    """生成 GLB 3D 预览文件。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        from core.processing.preview_mesh import create_preview_mesh
        from core.processing.outline_mesh import generate_outline_mesh

        p = ctx.params
        matched_rgb = ctx['matched_rgb']
        mask_solid = ctx['mask_solid']
        total_layers = ctx['total_layers']
        backing_color_id = ctx['backing_color_id']
        backing_metadata = ctx['backing_metadata']
        preview_colors = ctx['preview_colors']
        transform = ctx['transform']
        pixel_scale = ctx['pixel_scale']
        loop_info = ctx.get('loop_info')
        loop_added = ctx.get('loop_added', False)
        outline_added = ctx.get('outline_added', False)
        base_name = ctx['base_name']

        ctx.progress(0.90, "生成 3D 预览中... | Generating 3D preview...")

        preview_mesh = create_preview_mesh(
            matched_rgb, mask_solid, total_layers,
            backing_color_id=backing_color_id,
            backing_z_range=backing_metadata['backing_z_range'],
            preview_colors=preview_colors,
        )

        if preview_mesh:
            preview_mesh.apply_transform(transform)

            # 挂件环预览
            if loop_added and loop_info:
                try:
                    loop_thickness = total_layers * PrinterConfig.LAYER_HEIGHT
                    preview_loop = create_keychain_loop(
                        width_mm=loop_info['width_mm'],
                        length_mm=loop_info['length_mm'],
                        hole_dia_mm=loop_info['hole_dia_mm'],
                        thickness_mm=loop_thickness,
                        attach_x_mm=loop_info['attach_x_mm'],
                        attach_y_mm=loop_info['attach_y_mm'],
                    )
                    if preview_loop:
                        loop_color = preview_colors[loop_info['color_id']]
                        preview_loop.visual.face_colors = [loop_color] * len(preview_loop.faces)
                        preview_mesh = trimesh.util.concatenate([preview_mesh, preview_loop])
                except Exception as e:
                    print(f"[CONVERTER] Preview loop failed: {e}")

            # Outline 预览
            if outline_added:
                try:
                    outline_thickness_mm = total_layers * PrinterConfig.LAYER_HEIGHT
                    preview_outline = generate_outline_mesh(
                        mask_solid=mask_solid, pixel_scale=pixel_scale,
                        outline_width_mm=p.get('outline_width', 2.0),
                        outline_thickness_mm=outline_thickness_mm,
                        target_h=ctx['target_h'],
                    )
                    if preview_outline:
                        outline_color = preview_colors[0]
                        preview_outline.visual.face_colors = [outline_color] * len(preview_outline.faces)
                        preview_mesh = trimesh.util.concatenate([preview_mesh, preview_outline])
                except Exception as e:
                    print(f"[CONVERTER] Preview outline failed: {e}")

        glb_path = None
        if preview_mesh:
            glb_path = os.path.join(OUTPUT_DIR, generate_preview_filename(base_name))
            preview_mesh.export(glb_path)

        ctx['glb_path'] = glb_path
        return ctx
