# -*- coding: utf-8 -*-
"""Step 6: 体素矩阵构建"""

from __future__ import annotations

import numpy as np

from core.pipeline import PipelineContext, PipelineStep
from core.heightmap_loader import HeightmapLoader


class VoxelBuildStep(PipelineStep):
    """根据模式构建体素矩阵（flat / relief / heightmap / cloisonné / faceup）。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        from core.processing.voxel_builder import (
            build_voxel_matrix, build_voxel_matrix_faceup,
            build_relief_voxel_matrix, build_cloisonne_voxel_matrix,
        )

        p = ctx.params
        material_matrix = ctx['material_matrix']
        mask_solid = ctx['mask_solid']
        matched_rgb = ctx['matched_rgb']
        processor = ctx['processor']
        spacer_thick = p['spacer_thick']
        structure_mode = p['structure_mode']
        backing_color_id = ctx['backing_color_id']
        color_mode = p['color_mode']
        enable_relief = p.get('enable_relief', False)
        color_height_map = p.get('color_height_map')
        height_mode = p.get('height_mode', 'color')
        heightmap_path = p.get('heightmap_path')
        heightmap_max_height = p.get('heightmap_max_height')
        enable_cloisonne = p.get('enable_cloisonne', False)
        wire_width_mm = p.get('wire_width_mm', 0.4)
        wire_height_mm = p.get('wire_height_mm', 0.4)
        target_w, target_h = ctx['target_w'], ctx['target_h']
        pixel_scale = ctx['pixel_scale']

        try:
            # ========== 5-Color Extended ==========
            if "5-Color Extended" in color_mode:
                print(f"[CONVERTER] 5-Color Extended: forcing single-sided face-up")
                structure_mode = "单面"
                if enable_relief:
                    print(f"[CONVERTER] 5-Color Extended: 2.5D relief mode disabled (incompatible)")
                    enable_relief = False
                full_matrix, backing_metadata = build_voxel_matrix_faceup(
                    material_matrix, mask_solid, spacer_thick, backing_color_id,
                )

            # ========== Cloisonné ==========
            elif enable_cloisonne:
                print(f"[CONVERTER] 🎨 Cloisonné Mode ENABLED")
                print(f"[CONVERTER] Wire: width={wire_width_mm}mm, height={wire_height_mm}mm")
                structure_mode = "单面"
                mask_wireframe = processor._extract_wireframe_mask(
                    matched_rgb, target_w, pixel_scale, wire_width_mm,
                )
                full_matrix, backing_metadata = build_cloisonne_voxel_matrix(
                    material_matrix, mask_solid, mask_wireframe,
                    spacer_thick, wire_height_mm, backing_color_id,
                )

            # ========== Heightmap Relief ==========
            heightmap_height_matrix = None
            heightmap_stats = None
            if enable_relief and height_mode == "heightmap" and heightmap_path is not None:
                print(f"[CONVERTER] Heightmap Relief Mode: 尝试加载高度图...")
                print(f"[CONVERTER] 高度图路径: {heightmap_path}")
                try:
                    hm_max = heightmap_max_height if heightmap_max_height is not None else 5.0
                    hm_result = HeightmapLoader.load_and_process(
                        heightmap_path=heightmap_path,
                        target_w=target_w, target_h=target_h,
                        max_relief_height=hm_max, base_thickness=spacer_thick,
                    )
                    if hm_result['success']:
                        heightmap_height_matrix = hm_result['height_matrix']
                        heightmap_stats = hm_result['stats']
                        for w in hm_result.get('warnings', []):
                            print(f"[CONVERTER] {w}")
                        print(f"[CONVERTER] 高度图加载成功: {heightmap_height_matrix.shape}")
                    else:
                        print(f"[CONVERTER] WARNING: 高度图处理失败: {hm_result['error']}，回退到 flat 模式")
                except Exception as e:
                    print(f"[CONVERTER] WARNING: 高度图处理异常: {e}，回退到 flat 模式")
            elif enable_relief and height_mode == "heightmap" and heightmap_path is None:
                print("[CONVERTER] WARNING: heightmap mode selected but no heightmap provided, falling back to flat")

            if heightmap_height_matrix is not None:
                print(f"[CONVERTER] 2.5D Heightmap Relief Mode ENABLED")
                full_matrix, backing_metadata = build_relief_voxel_matrix(
                    matched_rgb=matched_rgb, material_matrix=material_matrix,
                    mask_solid=mask_solid,
                    color_height_map=color_height_map if color_height_map else {},
                    default_height=spacer_thick, structure_mode=structure_mode,
                    backing_color_id=backing_color_id, pixel_scale=pixel_scale,
                    height_matrix=heightmap_height_matrix,
                )
            elif enable_relief and height_mode == "color" and color_height_map:
                print(f"[CONVERTER] 2.5D Relief Mode ENABLED")
                print(f"[CONVERTER] Color height map: {color_height_map}")
                full_matrix, backing_metadata = build_relief_voxel_matrix(
                    matched_rgb=matched_rgb, material_matrix=material_matrix,
                    mask_solid=mask_solid, color_height_map=color_height_map,
                    default_height=spacer_thick, structure_mode=structure_mode,
                    backing_color_id=backing_color_id, pixel_scale=pixel_scale,
                )
            else:
                full_matrix, backing_metadata = build_voxel_matrix(
                    material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id,
                )

            total_layers = full_matrix.shape[0]
            print(f"[CONVERTER] Voxel matrix: {full_matrix.shape} (Z×H×W)")
            print(f"[CONVERTER] Backing layer: z={backing_metadata['backing_z_range']}, "
                  f"color_id={backing_metadata['backing_color_id']}")

        except Exception as e:
            print(f"[CONVERTER] Error marking backing layer: {e}")
            print(f"[CONVERTER] Falling back to original behavior (backing_color_id=0)")
            try:
                full_matrix, backing_metadata = build_voxel_matrix(
                    material_matrix, mask_solid, spacer_thick, structure_mode, backing_color_id=0,
                )
                total_layers = full_matrix.shape[0]
                print(f"[CONVERTER] Fallback successful: {full_matrix.shape} (Z×H×W)")
            except Exception as fallback_error:
                ctx.result = (None, None, None,
                              f"[ERROR] Voxel matrix generation failed: {fallback_error}", None)
                ctx.early_return = True
                return ctx

        ctx['full_matrix'] = full_matrix
        ctx['backing_metadata'] = backing_metadata
        ctx['total_layers'] = total_layers
        ctx['structure_mode'] = structure_mode
        ctx['heightmap_stats'] = heightmap_stats

        return ctx
