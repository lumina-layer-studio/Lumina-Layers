"""Lumina Studio API — System Management Router.
Lumina Studio API — 系统管理路由。

Provides cache cleanup utilities and the ``POST /api/system/clear-cache``
endpoint (endpoint registered in a later task).
提供缓存清理工具函数，以及 ``POST /api/system/clear-cache`` 端点
（端点在后续任务中注册）。
"""

import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

import config
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.schemas.system import (
    CacheCleanupDetails,
    ClearCacheResponse,
    ClearCacheResult,
    SaveSettingsResponse,
    StatsResponse,
    UserSettings,
    UserSettingsResponse,
)
from api.session_store import SessionStore

router = APIRouter(prefix="/api/system", tags=["System"])

CLEANABLE_EXTENSIONS: set[str] = {".3mf", ".glb", ".png", ".jpg"}


def cleanup_output_dir(output_dir: str) -> tuple[int, int]:
    """Scan *output_dir* and delete files whose extension is in
    :data:`CLEANABLE_EXTENSIONS`.

    扫描 *output_dir*，删除扩展名匹配的临时文件。

    Returns:
        ``(deleted_count, freed_bytes)``。
        If *output_dir* does not exist, returns ``(0, 0)`` without raising.
    """
    if not os.path.isdir(output_dir):
        return 0, 0

    deleted_count = 0
    freed_bytes = 0

    for entry in os.scandir(output_dir):
        if not entry.is_file():
            continue
        _, ext = os.path.splitext(entry.name)
        if ext.lower() not in CLEANABLE_EXTENSIONS:
            continue
        try:
            size = entry.stat().st_size
            os.remove(entry.path)
            deleted_count += 1
            freed_bytes += size
        except OSError:
            pass

    return deleted_count, freed_bytes


def perform_cache_cleanup(
    file_registry: FileRegistry,
    session_store: SessionStore,
    output_dir: str,
) -> ClearCacheResult:
    """Coordinate a full cache cleanup across all subsystems.

    执行缓存清理，依次清理 FileRegistry、SessionStore 和 OUTPUT_DIR，
    返回汇总统计结果。

    Steps:
        1. ``FileRegistry.clear_all()`` — clear registry & delete files
        2. ``SessionStore.clear_all()`` — clear sessions & temp files
        3. ``cleanup_output_dir()`` — delete matching files in OUTPUT_DIR
    """
    registry_cleaned: int = file_registry.clear_all()
    sessions_cleaned: int = session_store.clear_all()
    output_files_cleaned, freed_bytes = cleanup_output_dir(output_dir)

    return ClearCacheResult(
        registry_cleaned=registry_cleaned,
        sessions_cleaned=sessions_cleaned,
        output_files_cleaned=output_files_cleaned,
        total_freed_bytes=freed_bytes,
    )


@router.post("/clear-cache")
def clear_cache(
    file_registry: FileRegistry = Depends(get_file_registry),
    session_store: SessionStore = Depends(get_session_store),
) -> ClearCacheResponse:
    """Clear all cached/temporary files across subsystems.

    清除所有子系统中的缓存和临时文件，返回清理统计信息。
    """
    result: ClearCacheResult = perform_cache_cleanup(
        file_registry, session_store, config.OUTPUT_DIR
    )
    total_deleted: int = (
        result.registry_cleaned
        + result.sessions_cleaned
        + result.output_files_cleaned
    )
    return ClearCacheResponse(
        status="success",
        message=f"Cache cleared: {total_deleted} files deleted",
        deleted_files=total_deleted,
        freed_bytes=result.total_freed_bytes,
        details=CacheCleanupDetails(
            registry_cleaned=result.registry_cleaned,
            sessions_cleaned=result.sessions_cleaned,
            output_files_cleaned=result.output_files_cleaned,
        ),
    )


# ---------------------------------------------------------------------------
# Settings & Stats endpoints
# ---------------------------------------------------------------------------

SETTINGS_FILE: Path = Path("user_settings.json")


@router.get("/settings")
def get_settings() -> UserSettingsResponse:
    """读取 user_settings.json 并返回 UserSettings。文件不存在时返回默认值。"""
    if not SETTINGS_FILE.exists():
        return UserSettingsResponse(status="success", settings=UserSettings())
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        return UserSettingsResponse(status="success", settings=UserSettings(**data))
    except (json.JSONDecodeError, ValueError):
        return UserSettingsResponse(status="success", settings=UserSettings())


@router.post("/settings")
def save_settings(settings: UserSettings) -> SaveSettingsResponse:
    """将 UserSettings 写入 user_settings.json。"""
    try:
        SETTINGS_FILE.write_text(
            json.dumps(settings.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return SaveSettingsResponse(status="success", message="Settings saved")
    except OSError as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to save settings: {e}"
        )


@router.get("/stats")
def get_stats() -> StatsResponse:
    """获取使用统计数据。"""
    from utils.stats import Stats

    data: dict = Stats.get_all()
    return StatsResponse(
        calibrations=data.get("calibrations", 0),
        extractions=data.get("extractions", 0),
        conversions=data.get("conversions", 0),
    )
