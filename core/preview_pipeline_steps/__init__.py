# -*- coding: utf-8 -*-
"""
Lumina Studio - Preview Pipeline Steps Package
预览生成管道步骤包

将 generate_preview_cached 拆分为独立的管道步骤，
每个 Step 一个文件，方便独立维护和替换。
"""

from core.preview_pipeline_steps.s01_preview_input_validation import PreviewInputValidationStep
from core.preview_pipeline_steps.s02_lut_metadata import LutMetadataStep
from core.preview_pipeline_steps.s03_image_processing import PreviewImageProcessingStep
from core.preview_pipeline_steps.s04_cache_build import CacheBuildStep
from core.preview_pipeline_steps.s05_palette_extraction import PaletteExtractionStep
from core.preview_pipeline_steps.s06_preview_render import PreviewRenderStep


def build_preview_pipeline():
    """构建默认的预览生成管道。

    返回的 Pipeline 可以通过 insert_before / insert_after / remove / replace
    灵活地修改处理步骤。

    Example:
        pipeline = build_preview_pipeline()
        pipeline.insert_after('LutMetadataStep', MyCustomStep())
        pipeline.remove('PaletteExtractionStep')
    """
    from core.pipeline import Pipeline

    return Pipeline([
        PreviewInputValidationStep(),
        LutMetadataStep(),
        PreviewImageProcessingStep(),
        CacheBuildStep(),
        PaletteExtractionStep(),
        PreviewRenderStep(),
    ])


__all__ = [
    'PreviewInputValidationStep',
    'LutMetadataStep',
    'PreviewImageProcessingStep',
    'CacheBuildStep',
    'PaletteExtractionStep',
    'PreviewRenderStep',
    'build_preview_pipeline',
]
