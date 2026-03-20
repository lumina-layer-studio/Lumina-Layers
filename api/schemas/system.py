"""Lumina Studio API — System Pydantic models.
Lumina Studio API — 系统管理 Pydantic 数据模型。

Cache cleanup response schemas and internal data structures.
缓存清理响应 Schema 及内部数据结构。
"""

from dataclasses import dataclass

from pydantic import BaseModel


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
    last_color_mode: str = "4-Color"
    last_slicer: str = ""
    palette_mode: str = "swatch"
    enable_crop_modal: bool = True


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
