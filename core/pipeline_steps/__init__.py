# -*- coding: utf-8 -*-
"""
Lumina Studio - Pipeline Steps Package
光栅图像转换管道步骤包

每个 Step 一个文件，方便独立维护和替换。
"""

from core.pipeline_steps.s01_input_validation import InputValidationStep
from core.pipeline_steps.s02_image_processing import ImageProcessingStep
from core.pipeline_steps.s03_color_replacement import ColorReplacementStep
from core.pipeline_steps.s04_debug_preview import DebugPreviewStep
from core.pipeline_steps.s05_preview_generation import PreviewGenerationStep
from core.pipeline_steps.s06_voxel_build import VoxelBuildStep
from core.pipeline_steps.s07_mesh_generation import MeshGenerationStep
from core.pipeline_steps.s08_addon_mesh import AddonMeshStep
from core.pipeline_steps.s09_export import ExportStep
from core.pipeline_steps.s10_color_recipe import ColorRecipeStep
from core.pipeline_steps.s11_glb_preview import GlbPreviewStep
from core.pipeline_steps.s12_final_result import FinalResultStep


def build_raster_pipeline():
    """构建默认的光栅图像转换管道。

    返回的 Pipeline 可以通过 insert_before / insert_after / remove / replace
    灵活地修改处理步骤。

    Example:
        pipeline = build_raster_pipeline()
        pipeline.insert_after('ColorReplacementStep', MyDenoiseStep())
        pipeline.remove('DebugPreviewStep')
    """
    from core.pipeline import Pipeline

    return Pipeline([
        InputValidationStep(),
        ImageProcessingStep(),
        ColorReplacementStep(),
        DebugPreviewStep(),
        PreviewGenerationStep(),
        VoxelBuildStep(),
        MeshGenerationStep(),
        AddonMeshStep(),
        ExportStep(),
        ColorRecipeStep(),
        GlbPreviewStep(),
        FinalResultStep(),
    ])


__all__ = [
    'InputValidationStep',
    'ImageProcessingStep',
    'ColorReplacementStep',
    'DebugPreviewStep',
    'PreviewGenerationStep',
    'VoxelBuildStep',
    'MeshGenerationStep',
    'AddonMeshStep',
    'ExportStep',
    'ColorRecipeStep',
    'GlbPreviewStep',
    'FinalResultStep',
    'build_raster_pipeline',
]
