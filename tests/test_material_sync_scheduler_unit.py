"""Unit tests for material sync background refresh scheduling."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from api.material_sync_scheduler import (
    cancel_material_sync_auto_refresh_tasks,
    run_material_sync_refresh_once,
    start_material_sync_auto_refresh_tasks,
)


def test_material_sync_auto_refresh_is_disabled_by_explicit_empty_url(monkeypatch) -> None:
    monkeypatch.delenv("LUMINA_MATERIAL_SYNC_STARTUP_REFRESH", raising=False)
    monkeypatch.delenv("LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S", raising=False)
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "")
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "")

    async def _run() -> None:
        tasks = start_material_sync_auto_refresh_tasks()

        assert tasks == []

    asyncio.run(_run())


def test_material_sync_auto_refresh_defaults_to_startup_and_six_hours_when_registry_is_configured(
    monkeypatch,
) -> None:
    monkeypatch.delenv("LUMINA_MATERIAL_SYNC_STARTUP_REFRESH", raising=False)
    monkeypatch.delenv("LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S", raising=False)
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "https://registry.test/v1")

    from api.material_sync_scheduler import (
        material_sync_refresh_interval_s,
        material_sync_startup_refresh_enabled,
    )

    assert material_sync_startup_refresh_enabled() is True
    assert material_sync_refresh_interval_s() == 21_600.0


def test_material_sync_startup_refresh_schedules_one_refresh(monkeypatch) -> None:
    calls: list[str] = []

    async def _fake_refresh_once(*, reason: str) -> dict[str, Any]:
        calls.append(reason)
        return {"installed_count": 0, "skipped_count": 0, "failed_count": 0}

    monkeypatch.setenv("LUMINA_MATERIAL_SYNC_STARTUP_REFRESH", "true")
    monkeypatch.delenv("LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S", raising=False)
    monkeypatch.setattr(
        "api.material_sync_scheduler.run_material_sync_refresh_once",
        _fake_refresh_once,
    )

    async def _run() -> None:
        tasks = start_material_sync_auto_refresh_tasks()
        try:
            await asyncio.sleep(0)
            assert calls == ["startup"]
        finally:
            await cancel_material_sync_auto_refresh_tasks(tasks)

    asyncio.run(_run())


def test_material_sync_refresh_lock_skips_overlapping_registry_refresh(monkeypatch) -> None:
    calls = 0

    def _blocking_refresh() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        time.sleep(0.05)
        return {
            "checked_count": 1,
            "installed_count": 1,
            "skipped_count": 0,
            "failed_count": 0,
            "channels": ["official"],
        }

    monkeypatch.setattr(
        "api.material_sync_scheduler._check_resource_catalogs",
        _blocking_refresh,
        raising=False,
    )

    async def _run() -> None:
        first, second = await asyncio.gather(
            run_material_sync_refresh_once(reason="startup"),
            run_material_sync_refresh_once(reason="scheduled"),
        )

        results = [first, second]
        assert calls == 1
        assert any(result is None for result in results)
        assert any(
            isinstance(result, dict) and result["installed_count"] == 1
            for result in results
        )

    asyncio.run(_run())


def test_material_sync_interval_refresh_schedules_repeated_refresh(monkeypatch) -> None:
    calls: list[str] = []

    async def _fake_refresh_once(*, reason: str) -> dict[str, Any]:
        calls.append(reason)
        return {"installed_count": 0, "skipped_count": 0, "failed_count": 0}

    monkeypatch.setenv("LUMINA_MATERIAL_SYNC_STARTUP_REFRESH", "0")
    monkeypatch.setenv("LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S", "0.01")
    monkeypatch.setattr(
        "api.material_sync_scheduler.run_material_sync_refresh_once",
        _fake_refresh_once,
    )

    async def _run() -> None:
        tasks = start_material_sync_auto_refresh_tasks()
        try:
            await asyncio.sleep(0.04)
        finally:
            await cancel_material_sync_auto_refresh_tasks(tasks)

        assert calls
        assert set(calls) == {"scheduled"}

    asyncio.run(_run())


def test_material_sync_refresh_once_checks_catalog_without_install(monkeypatch) -> None:
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "https://catalog.test/api")
    def _catalog_refresh(**kwargs) -> dict[str, Any]:
        return {"materials": [{"material_id": "public"}], "total_count": 1}

    def _registry_refresh() -> dict[str, Any]:
        raise AssertionError("background checks must never install packages")

    monkeypatch.setattr(
        "api.material_sync_scheduler.list_material_registry_catalog",
        _catalog_refresh,
        raising=False,
    )
    monkeypatch.setattr(
        "api.material_sync_scheduler.refresh_material_sync_from_registry",
        _registry_refresh,
        raising=False,
    )
    monkeypatch.setenv("LUMINA_LUT_REGISTRY_URL", "")

    async def _run() -> None:
        result = await run_material_sync_refresh_once(reason="startup")

        assert result is not None
        assert result["installed_count"] == 0
        assert result["checked_count"] == 1

    asyncio.run(_run())


def test_material_sync_refresh_returns_none_when_registry_refresh_fails(monkeypatch) -> None:
    def _failing_refresh() -> dict[str, Any]:
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(
        "api.material_sync_scheduler._check_resource_catalogs",
        _failing_refresh,
        raising=False,
    )

    async def _run() -> None:
        result = await run_material_sync_refresh_once(reason="startup")

        assert result is None

    asyncio.run(_run())
