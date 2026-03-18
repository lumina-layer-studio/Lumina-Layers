# -*- coding: utf-8 -*-
"""Step 3: matched_rgb 覆盖 + 颜色替换"""

from __future__ import annotations

import numpy as np

from core.pipeline import PipelineContext, PipelineStep


class ColorReplacementStep(PipelineStep):
    """处理 matched_rgb_path 覆盖、全局颜色替换、区域颜色替换。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        p = ctx.params
        processor = ctx['processor']
        matched_rgb = ctx['matched_rgb']
        material_matrix = ctx['material_matrix']
        mask_solid = ctx['mask_solid']

        # --- matched_rgb_path 覆盖 ---
        matched_rgb_path = p.get('matched_rgb_path')
        if matched_rgb_path is not None:
            try:
                override_rgb = np.load(matched_rgb_path)
                if override_rgb.shape != matched_rgb.shape:
                    print(f"[CONVERTER] Warning: matched_rgb_path shape {override_rgb.shape} "
                          f"does not match processed shape {matched_rgb.shape}, ignoring override")
                else:
                    diff_mask = np.any(matched_rgb != override_rgb, axis=-1) & mask_solid
                    if np.any(diff_mask):
                        diff_pixels = override_rgb[diff_mask]
                        unique_colors = np.unique(diff_pixels, axis=0)
                        for color in unique_colors:
                            color_mask = np.all(override_rgb == color, axis=-1) & diff_mask
                            repl_lab = processor._rgb_to_lab(color.reshape(1, 3))
                            _, lut_idx = processor.kdtree.query(repl_lab)
                            new_stacks = processor.ref_stacks[lut_idx[0]]
                            material_matrix[color_mask] = new_stacks
                        print(f"[CONVERTER] matched_rgb override applied: "
                              f"{np.sum(diff_mask)} pixels updated across {len(unique_colors)} colors")
                    matched_rgb = override_rgb
            except Exception as e:
                print(f"[CONVERTER] Warning: Failed to load matched_rgb_path '{matched_rgb_path}': {e}, "
                      f"using original processed result")

        # --- 全局颜色替换 ---
        from core.processing.color_replacement import normalize_color_replacements_input

        color_replacements = p.get('color_replacements')
        replacement_regions = p.get('replacement_regions')

        effective_color_replacements = normalize_color_replacements_input(color_replacements)
        if replacement_regions:
            api_format_replacements = normalize_color_replacements_input(replacement_regions)
            if api_format_replacements:
                effective_color_replacements.update(api_format_replacements)
                replacement_regions = [r for r in replacement_regions if r.get('mask') is not None]

        if effective_color_replacements:
            from core.color_replacement import ColorReplacementManager
            manager = ColorReplacementManager.from_dict(effective_color_replacements)
            old_rgb = matched_rgb.copy()
            matched_rgb = manager.apply_to_image(matched_rgb)
            print(f"[CONVERTER] Applied {len(manager)} color replacements")

            for orig_hex, repl_hex in effective_color_replacements.items():
                orig_rgb_tuple = ColorReplacementManager._hex_to_color(orig_hex)
                repl_rgb_tuple = ColorReplacementManager._hex_to_color(repl_hex)
                orig_mask = np.all(old_rgb == orig_rgb_tuple, axis=-1)
                if not np.any(orig_mask):
                    continue
                repl_lab = processor._rgb_to_lab(np.array([repl_rgb_tuple], dtype=np.uint8))
                _, lut_idx = processor.kdtree.query(repl_lab)
                lut_idx = lut_idx[0]
                new_stacks = processor.ref_stacks[lut_idx]
                material_matrix[orig_mask] = new_stacks
                lut_color = processor.lut_rgb[lut_idx]
                print(f"[CONVERTER] material_matrix: {orig_hex} → LUT#{lut_idx} "
                      f"rgb({lut_color[0]},{lut_color[1]},{lut_color[2]}) stacks={new_stacks}")

        # --- 区域替换 ---
        if replacement_regions:
            from core.processing.color_replacement import apply_regions_to_raster_outputs

            def _resolve_lut_index_for_rgb(replacement_rgb):
                repl_lab = processor._rgb_to_lab(np.array([replacement_rgb], dtype=np.uint8))
                _, lut_idx = processor.kdtree.query(repl_lab)
                return lut_idx[0]

            matched_rgb, material_matrix = apply_regions_to_raster_outputs(
                matched_rgb, material_matrix, mask_solid,
                replacement_regions, _resolve_lut_index_for_rgb, processor.ref_stacks,
            )

        ctx['matched_rgb'] = matched_rgb
        ctx['material_matrix'] = material_matrix

        target_w, target_h = ctx['target_w'], ctx['target_h']
        print(f"[CONVERTER] Image processed: {target_w}×{target_h}px, scale={ctx['pixel_scale']}mm/px")

        return ctx
