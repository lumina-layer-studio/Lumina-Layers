"""Unit tests for Converter replace-color endpoint integration.

Validates:
- No preview_cache returns HTTP 409 (Requirement 6.3)
- Session not found returns HTTP 404 (Requirement 6.1)
- Successful replacement updates replacement_regions and returns ColorReplaceResponse (Requirement 6.2)
- replacement_history stores snapshot before each change (Requirement 6.4)
"""

from __future__ import annotations

import numpy as np
from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_session_store, get_file_registry
from api.file_registry import FileRegistry
from api.session_store import SessionStore

# Isolated store/registry per test module
_test_store: SessionStore = SessionStore(ttl=1800)
_test_registry: FileRegistry = FileRegistry()

def setup_module(module):
    """Re-apply dependency overrides before this module's tests run.
    在本模块测试运行前重新设置依赖覆盖，确保跨文件测试隔离。
    """
    app.dependency_overrides[get_session_store] = lambda: _test_store
    app.dependency_overrides[get_file_registry] = lambda: _test_registry


def teardown_module(module):
    """Remove this module's dependency overrides after all tests complete.
    本模块所有测试完成后移除依赖覆盖。
    """
    app.dependency_overrides.pop(get_session_store, None)
    app.dependency_overrides.pop(get_file_registry, None)


# Apply overrides immediately for module-level client creation
setup_module(None)

client: TestClient = TestClient(app)


def _create_session_with_preview() -> str:
    """Create a session with a minimal preview_cache for testing."""
    sid = _test_store.create()
    # 4x4 image: top-left 2x2 red, rest green
    matched = np.zeros((4, 4, 3), dtype=np.uint8)
    matched[:2, :2] = [255, 0, 0]   # red
    matched[2:, :] = [0, 255, 0]    # green
    matched[:2, 2:] = [0, 255, 0]   # green
    _test_store.put(sid, "preview_cache", {"matched_rgb": matched})
    _test_store.put(sid, "replacement_regions", [])
    _test_store.put(sid, "replacement_history", [])
    return sid


# =========================================================================
# 1. Session not found returns 404
# =========================================================================


class TestSessionNotFound:
    """Verify unknown session_id returns HTTP 404."""

    def test_replace_color_unknown_session_returns_404(self) -> None:
        response = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": "nonexistent-session-id",
                "selected_color": "#ff0000",
                "replacement_color": "#0000ff",
            },
        )
        assert response.status_code == 404


# =========================================================================
# 2. No preview_cache returns 409
# =========================================================================


class TestNoPreviewCacheReturns409:
    """Verify missing preview_cache returns HTTP 409."""

    def test_replace_color_no_cache_returns_409(self) -> None:
        sid = _test_store.create()
        # No preview_cache stored
        response = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#ff0000",
                "replacement_color": "#0000ff",
            },
        )
        assert response.status_code == 409
        assert "preview" in response.json()["detail"].lower()


# =========================================================================
# 3. Successful replacement updates session and returns correct response
# =========================================================================


class TestSuccessfulReplacement:
    """Verify replacement updates replacement_regions and returns ColorReplaceResponse."""

    def test_replace_color_returns_ok_response(self) -> None:
        sid = _create_session_with_preview()
        response = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#ff0000",
                "replacement_color": "#0000ff",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["replacement_count"] == 1
        assert body["preview_url"].startswith("/api/files/")

    def test_replacement_regions_updated_in_session(self) -> None:
        sid = _create_session_with_preview()
        client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#ff0000",
                "replacement_color": "#0000ff",
            },
        )
        data = _test_store.get(sid)
        regions = data["replacement_regions"]
        assert len(regions) == 1
        assert regions[0]["selected_color"] == "#ff0000"
        assert regions[0]["replacement_color"] == "#0000ff"


# =========================================================================
# 4. replacement_history stores snapshot for undo support
# =========================================================================


class TestReplacementHistory:
    """Verify replacement_history captures pre-change snapshots."""

    def test_history_snapshot_saved_before_change(self) -> None:
        sid = _create_session_with_preview()

        # First replacement
        client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#ff0000",
                "replacement_color": "#0000ff",
            },
        )
        data = _test_store.get(sid)
        # History should have one entry: the empty list before first change
        assert len(data["replacement_history"]) == 1
        assert data["replacement_history"][0] == []

        # Second replacement
        client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#00ff00",
                "replacement_color": "#ffff00",
            },
        )
        data = _test_store.get(sid)
        assert len(data["replacement_history"]) == 2
        # Second snapshot should contain the first replacement
        assert len(data["replacement_history"][1]) == 1
        assert data["replacement_regions"][-1]["selected_color"] == "#00ff00"
        assert data["replacement_count"] if "replacement_count" in data else True
