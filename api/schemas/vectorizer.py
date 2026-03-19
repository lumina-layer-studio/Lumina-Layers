"""Vectorizer domain Pydantic schemas.
Vectorizer 领域的 Pydantic 数据模型。

This module defines request and response models for the image-to-SVG
vectorization API powered by neroued_vectorizer.
本模块定义由 neroued_vectorizer 驱动的图像转 SVG 矢量化 API
的请求与响应模型。
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class VectorizeParams(BaseModel):
    """Parameters for image vectorization.
    图像矢量化参数。
    """

    # Core
    num_colors: int = Field(0, ge=0, le=256, description="颜色数 (0=自动)")
    smoothness: float = Field(0.5, ge=0.0, le=1.0, description="平滑度 [0, 1]")
    detail_level: float = Field(-1.0, ge=-1.0, le=1.0, description="细节等级 (-1=禁用, 0~1)")

    # Output enhancement
    svg_enable_stroke: bool = Field(True, description="启用描边")
    svg_stroke_width: float = Field(0.5, ge=0.0, le=20.0, description="描边宽度")
    thin_line_max_radius: float = Field(2.5, ge=0.5, le=10.0, description="薄线检测半径")
    enable_coverage_fix: bool = Field(True, description="启用覆盖修复")
    min_coverage_ratio: float = Field(0.998, ge=0.0, le=1.0, description="最小覆盖率阈值")

    # Preprocessing
    smoothing_spatial: float = Field(15.0, ge=0.0, le=50.0, description="空间平滑半径")
    smoothing_color: float = Field(25.0, ge=0.0, le=80.0, description="颜色平滑半径")
    max_working_pixels: int = Field(3000000, ge=100000, le=100000000, description="最大工作像素数")

    # Segmentation
    slic_region_size: int = Field(20, ge=5, le=100, description="超像素区域大小")
    edge_sensitivity: float = Field(0.8, ge=0.0, le=1.0, description="边缘敏感度 [0, 1]")
    refine_passes: int = Field(6, ge=0, le=20, description="边界细化迭代次数")
    enable_antialias_detect: bool = Field(False, description="启用抗锯齿检测")
    aa_tolerance: float = Field(10.0, ge=1.0, le=50.0, description="抗锯齿容差 (LAB ΔE)")

    # Curve fitting
    curve_fit_error: float = Field(0.8, ge=0.1, le=5.0, description="曲线拟合误差 (像素)")
    contour_simplify: float = Field(0.45, ge=0.0, le=2.0, description="轮廓简化强度")
    merge_segment_tolerance: float = Field(0.05, ge=0.0, le=0.5, description="线段合并容差")

    # Filtering
    min_region_area: int = Field(50, ge=0, le=1000000, description="最小区域面积 (像素²)")
    max_merge_color_dist: float = Field(200.0, ge=0.0, le=2000.0, description="最大合并色差 (LAB ΔE²)")
    min_contour_area: float = Field(10.0, ge=0.0, le=1000000.0, description="最小轮廓面积 (像素²)")
    min_hole_area: float = Field(4.0, ge=0.0, le=100000.0, description="最小孔洞面积 (像素²)")


class VectorizeResponse(BaseModel):
    """Response model for vectorization result.
    矢量化结果的响应模型。

    Attributes:
        status: Operation status string.
            操作状态。
        message: Human-readable status message.
            状态消息。
        svg_url: URL to download the generated SVG file.
            SVG 文件下载 URL。
        width: Source image width in pixels.
            源图像宽度（像素）。
        height: Source image height in pixels.
            源图像高度（像素）。
        num_shapes: Number of shapes in the SVG output.
            SVG 中的形状数量。
        num_colors: Number of resolved colors.
            实际颜色数。
        palette: List of hex color strings in the palette.
            调色板颜色列表（hex 格式）。
    """

    status: str = Field("ok", description="操作状态")
    message: str = Field("", description="状态消息")
    svg_url: str = Field(..., description="SVG 文件下载 URL")
    width: int = Field(..., description="图像宽度 (像素)")
    height: int = Field(..., description="图像高度 (像素)")
    num_shapes: int = Field(..., description="形状数量")
    num_colors: int = Field(..., description="颜色数量")
    palette: List[str] = Field(default_factory=list, description="调色板 (hex 列表)")


class VectorizeDefaultsResponse(BaseModel):
    """Response model returning default vectorization parameters.
    返回默认矢量化参数的响应模型。

    Attributes:
        defaults: Default vectorization parameters.
            默认矢量化参数。
    """

    defaults: VectorizeParams = Field(default_factory=VectorizeParams)
