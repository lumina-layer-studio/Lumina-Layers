"""Background scheduler for material Registry refresh.
耗材 Registry 刷新后台调度器。
"""

from __future__ import annotations

import asyncio
import os
import threading
from contextlib import suppress
from typing import Any

from api.structured_logging import get_logger
from core.public_resources import material_registry_url, lut_registry_url
from core.single_stage import list_material_registry_catalog
from api.services.lut_registry_sync import fetch_remote_catalog

log = get_logger(__name__)

_TRUE_ENV_VALUES = {"1", "true", "yes", "on"}
_FALSE_ENV_VALUES = {"0", "false", "no", "off"}
_DEFAULT_REFRESH_INTERVAL_S = 6 * 60 * 60
_REFRESH_LOCK = threading.Lock()


def _material_registry_url_configured() -> bool:
    return bool(material_registry_url() or lut_registry_url())


def _check_resource_catalogs() -> dict[str, Any]:
    """Refresh catalog caches; package installation remains an explicit action."""
    catalogs: dict[str, Any] = {}
    if material_registry_url():
        catalogs["materials"] = list_material_registry_catalog(use_cache=False)
    if lut_registry_url():
        catalogs["luts"] = fetch_remote_catalog()
    return {
        "checked_count": sum(int(value.get("total_count", value.get("total", value.get("count", 0)))) for value in catalogs.values()),
        "installed_count": 0,
        "catalogs": catalogs,
    }


def material_sync_startup_refresh_enabled() -> bool:
    """Return whether app startup should trigger one material refresh.
    返回应用启动时是否触发一次耗材刷新。

    Returns:
        bool: ``True`` when ``LUMINA_MATERIAL_SYNC_STARTUP_REFRESH`` is truthy.
            当环境变量为真值时返回 ``True``。
    """
    raw_value = os.environ.get("LUMINA_MATERIAL_SYNC_STARTUP_REFRESH")
    if raw_value is None or not raw_value.strip():
        return _material_registry_url_configured()
    normalized = raw_value.strip().lower()
    if normalized in _FALSE_ENV_VALUES:
        return False
    return normalized in _TRUE_ENV_VALUES


def material_sync_refresh_interval_s() -> float:
    """Return the configured periodic refresh interval in seconds.
    返回配置的定时刷新间隔秒数。

    Returns:
        float: Positive interval seconds, or ``0.0`` when disabled/invalid.
            正数表示启用定时刷新；无效或未配置时返回 ``0.0``。
    """
    raw_value = os.environ.get("LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S")
    if raw_value is None or not raw_value.strip():
        return float(_DEFAULT_REFRESH_INTERVAL_S) if _material_registry_url_configured() else 0.0
    try:
        interval = float(raw_value)
    except ValueError:
        return 0.0
    return interval if interval > 0 else 0.0


async def run_material_sync_refresh_once(*, reason: str) -> dict[str, Any] | None:
    """Run one non-overlapping public resource catalog check.
    只刷新公开目录，不自动安装资源包。

    Args:
        reason: Operational reason, for example ``startup`` or ``scheduled``.
            触发原因，例如 ``startup`` 或 ``scheduled``。

    Returns:
        dict[str, Any] | None: Refresh summary on success; ``None`` when
            skipped or failed. 成功时返回同步摘要；跳过或失败时返回 ``None``。
    """
    if not _REFRESH_LOCK.acquire(blocking=False):
        log.debug(
            "Material sync auto refresh skipped because another refresh is running",
            extra={
                "event": "material_sync_auto_refresh_skipped",
                "reason": reason,
                "skip_reason": "already_running",
            },
        )
        return None

    try:
        result = await asyncio.to_thread(_check_resource_catalogs)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        log.warning(
            "Material sync auto refresh failed",
            extra={
                "event": "material_sync_auto_refresh_failed",
                "reason": reason,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        return None
    finally:
        _REFRESH_LOCK.release()

    log.info(
        "Material sync auto refresh completed",
        extra={
            "event": "material_sync_auto_refresh_done",
            "reason": reason,
            "channels": result.get("channels"),
            "checked_count": result.get("checked_count"),
            "installed_count": result.get("installed_count"),
            "skipped_count": result.get("skipped_count"),
            "failed_count": result.get("failed_count"),
            "catalog_not_modified": bool(
                result.get("catalog_not_modified", False)
            ),
        },
    )
    return result


async def _material_sync_interval_loop(interval_s: float) -> None:
    """Run scheduled material refresh until cancelled.
    周期性执行耗材刷新直到任务被取消。
    """
    while True:
        await asyncio.sleep(interval_s)
        await run_material_sync_refresh_once(reason="scheduled")


def start_material_sync_auto_refresh_tasks() -> list[asyncio.Task[None]]:
    """Start configured material sync background refresh tasks.
    启动已配置的耗材同步后台刷新任务。

    Returns:
        list[asyncio.Task[None]]: Created background tasks; empty when disabled.
            创建的后台任务列表；未启用时为空。
    """
    tasks: list[asyncio.Task[None]] = []
    startup_enabled = material_sync_startup_refresh_enabled()
    interval_s = material_sync_refresh_interval_s()

    if startup_enabled:
        tasks.append(asyncio.create_task(run_material_sync_refresh_once(reason="startup")))
    if interval_s > 0:
        tasks.append(asyncio.create_task(_material_sync_interval_loop(interval_s)))

    if tasks:
        log.info(
            "Material sync auto refresh scheduled",
            extra={
                "event": "material_sync_auto_refresh_scheduled",
                "startup_enabled": startup_enabled,
                "interval_s": interval_s,
                "task_count": len(tasks),
            },
        )
    return tasks


async def cancel_material_sync_auto_refresh_tasks(
    tasks: list[asyncio.Task[None]],
) -> None:
    """Cancel material sync background refresh tasks and await shutdown.
    取消耗材同步后台刷新任务并等待退出。

    Args:
        tasks: Tasks returned by :func:`start_material_sync_auto_refresh_tasks`.
            由 :func:`start_material_sync_auto_refresh_tasks` 返回的任务。
    """
    for task in tasks:
        task.cancel()
    for task in tasks:
        with suppress(asyncio.CancelledError):
            await task
