"""Lumina Studio API — Response Pydantic models.
Lumina Studio API — 响应 Pydantic 数据模型。

All API endpoint response schemas are defined here.
所有 API 端点的响应 Schema 均在此定义。
"""

from typing import Optional

from pydantic import BaseModel


class CalibrationResponse(BaseModel):
    """校准板生成响应。"""

    status: str
    message: str
    download_url: str
    preview_url: Optional[str] = None


class PreviewResponse(BaseModel):
    """预览生成响应。"""

    session_id: str
    status: str
    message: str
    preview_url: str
    preview_glb_url: Optional[str] = None
    palette: list[dict]
    dimensions: dict
    contours: Optional[dict[str, list[list[list[float]]]]] = None


class ColorReplaceResponse(BaseModel):
    """颜色替换响应。"""

    status: str
    message: str
    preview_url: str
    replacement_count: int


class MergePreviewResponse(BaseModel):
    """颜色合并预览响应。"""

    status: str
    message: str
    preview_url: str
    merge_map: dict[str, str]
    quality_metric: float
    colors_before: int
    colors_after: int


class GenerateResponse(BaseModel):
    """3MF 生成响应。"""

    status: str
    message: str
    download_url: str
    preview_3d_url: Optional[str] = None
    threemf_disk_path: Optional[str] = None


class BatchItemResult(BaseModel):
    """批量转换单项结果。"""

    filename: str
    status: str
    error: Optional[str] = None


class BatchResponse(BaseModel):
    """批量转换响应。"""

    status: str
    message: str
    download_url: str
    results: list[BatchItemResult]


class LutInfo(BaseModel):
    """单个 LUT 预设信息。"""

    name: str
    color_mode: str
    path: str


class LUTListResponse(BaseModel):
    """LUT 列表响应。"""

    luts: list[LutInfo]


class WorkerPoolStatus(BaseModel):
    """Worker Pool 状态信息。"""

    healthy: bool
    max_workers: int


class HealthResponse(BaseModel):
    """健康检查响应（含 Worker Pool 状态）。"""

    status: str
    version: str
    uptime_seconds: float
    worker_pool: WorkerPoolStatus


class ExtractResponse(BaseModel):
    """颜色提取响应。"""

    session_id: str
    status: str
    message: str
    lut_download_url: str
    warp_view_url: str
    lut_preview_url: str


class ManualFixResponse(BaseModel):
    """手动修正响应。"""

    status: str
    message: str
    lut_preview_url: str


class HeightmapUploadResponse(BaseModel):
    """高度图上传响应。"""

    status: str
    message: str
    thumbnail_url: str
    original_size: tuple[int, int]
    color_height_map: dict[str, float]
    warnings: list[str]


class LutColorEntry(BaseModel):
    """单个 LUT 颜色条目。"""

    hex: str
    rgb: tuple[int, int, int]


class LutColorsResponse(BaseModel):
    """LUT 颜色列表响应。"""

    lut_name: str
    total: int
    colors: list[LutColorEntry]


class CropResponse(BaseModel):
    """裁剪响应。"""

    status: str
    message: str
    cropped_url: str
    width: int
    height: int
