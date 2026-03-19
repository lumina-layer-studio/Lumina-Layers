"""Lumina Studio API — System Pydantic models.
Lumina Studio API — 系统管理 Pydantic 数据模型。

Cache cleanup response schemas and internal data structures.
缓存清理响应 Schema 及内部数据结构。
"""

from dataclasses import dataclass

from pydantic import BaseModel


class PrinterInfo(BaseModel):
    """Printer hardware metadata exposed to the frontend.
    暴露给前端的打印机硬件元数据。
    """

    id: str
    display_name: str
    brand: str
    bed_width: int
    bed_depth: int
    bed_height: int
    nozzle_count: int
    is_dual_head: bool
    supported_slicers: list[str] = []


class PrinterListResponse(BaseModel):
    """Response for GET /api/system/printers.
    GET /api/system/printers 响应。
    """

    status: str
    printers: list[PrinterInfo]


class CacheCleanupDetails(BaseModel):
    """缓存清理详情。"""

    registry_cleaned: int
    sessions_cleaned: int
    output_files_cleaned: int


class ClearCacheResponse(BaseModel):
    """缓存清理响应。"""

    status: str
    message: str
    deleted_files: int
    freed_bytes: int
    details: CacheCleanupDetails


@dataclass
class ClearCacheResult:
    """perform_cache_cleanup 内部返回值。"""

    registry_cleaned: int
    sessions_cleaned: int
    output_files_cleaned: int
    total_freed_bytes: int


class UserSettings(BaseModel):
    """用户设置模型，对应 user_settings.json 字段。"""

    last_lut: str = ""
    last_modeling_mode: str = "high-fidelity"
    last_color_mode: str = "4-Color (RYBW)"
    last_slicer: str = ""
    palette_mode: str = "swatch"
    enable_crop_modal: bool = True
    printer_model: str = "bambu-h2d"
    slicer_software: str = "BambuStudio"


class UserSettingsResponse(BaseModel):
    """GET /api/system/settings 响应。"""

    status: str
    settings: UserSettings


class SaveSettingsResponse(BaseModel):
    """POST /api/system/settings 响应。"""

    status: str
    message: str


class StatsResponse(BaseModel):
    """GET /api/system/stats 响应。"""

    calibrations: int = 0
    extractions: int = 0
    conversions: int = 0


class SlicerInfo(BaseModel):
    """切片器软件信息。"""

    id: str
    display_name: str


class SlicerListResponse(BaseModel):
    """GET /api/system/slicers 响应。"""

    status: str
    slicers: list[SlicerInfo]
