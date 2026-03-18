# -*- coding: utf-8 -*-
"""Step 2: 图像处理（LuminaImageProcessor）"""

from __future__ import annotations

from core.pipeline import PipelineContext, PipelineStep
from config import ColorSystem, ModelingMode
from core.image_processing import LuminaImageProcessor

try:
    from utils.lut_manager import LUTManager
except ImportError:
    LUTManager = None


class ImageProcessingStep(PipelineStep):
    """调用 LuminaImageProcessor 处理图像，生成 matched_rgb / material_matrix / mask_solid。"""

    def execute(self, ctx: PipelineContext) -> PipelineContext:
        p = ctx.params
        actual_lut_path = ctx['actual_lut_path']
        color_mode = p['color_mode']

        ctx.progress(0.05, "图像处理与 LUT 匹配中... | Processing image...")

        # 加载 LUT 元数据
        lut_metadata = None
        if LUTManager is not None:
            try:
                _, _, lut_metadata = LUTManager.load_lut_with_metadata(actual_lut_path)
            except Exception as e:
                print(f"[CONVERTER] Warning: Failed to load LUT metadata: {e}")
        ctx['lut_metadata'] = lut_metadata

        try:
            processor = LuminaImageProcessor(
                actual_lut_path, color_mode,
                hue_weight=p.get('hue_weight', 0.0),
                chroma_gate=p.get('chroma_gate', 15.0),
            )
            processor.enable_cleanup = p.get('enable_cleanup', True)
            result = processor.process_image(
                image_path=p['image_path'],
                target_width_mm=p['target_width_mm'],
                modeling_mode=p.get('modeling_mode', ModelingMode.HIGH_FIDELITY),
                quantize_colors=p.get('quantize_colors', 32),
                auto_bg=p['auto_bg'],
                bg_tol=p['bg_tol'],
                blur_kernel=p.get('blur_kernel', 0),
                smooth_sigma=p.get('smooth_sigma', 10),
            )
        except Exception as e:
            ctx.result = (None, None, None, f"[ERROR] Image processing failed: {e}", None)
            ctx.early_return = True
            return ctx

        ctx['processor'] = processor
        ctx['matched_rgb'] = result['matched_rgb']
        ctx['material_matrix'] = result['material_matrix']
        ctx['mask_solid'] = result['mask_solid']
        ctx['target_w'], ctx['target_h'] = result['dimensions']
        ctx['pixel_scale'] = result['pixel_scale']
        ctx['mode_info'] = result['mode_info']
        ctx['debug_data'] = result.get('debug_data', None)

        # 颜色系统配置
        color_conf = ColorSystem.get(color_mode)
        ctx['color_conf'] = color_conf
        ctx['slot_names'] = color_conf['slots']
        ctx['preview_colors'] = color_conf['preview']

        # 验证 backing_color_id
        num_materials = len(color_conf['slots'])
        backing_color_id = ctx['backing_color_id']
        if backing_color_id != -2 and (backing_color_id < 0 or backing_color_id >= num_materials):
            print(f"[CONVERTER] Warning: Invalid backing_color_id={backing_color_id}, using default (0)")
            ctx['backing_color_id'] = 0

        return ctx
