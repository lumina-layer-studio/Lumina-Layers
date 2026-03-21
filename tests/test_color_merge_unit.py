"""Unit tests for Converter merge-colors endpoint integration.

Validates:
- Session not found returns HTTP 404 (Requirement 7.1)
- No preview_cache returns HTTP 409 (Requirement 7.3)
- merge_enable=False returns empty merge_map with quality=100 (Requirement 7.2)
- Successful merge returns merge_map, quality_metric, colors_before, colors_after (Requirement 7.2)
- merge_map stored in session after merge (Requirement 7.2)
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
    """Create a session with a multi-color preview_cache for merge testing."""
    sid = _test_store.create()
    # 10x10 image: 90 red pixels, 5 green pixels, 5 blue pixels
    matched = np.zeros((10, 10, 3), dtype=np.uint8)
    matched[:, :] = [255, 0, 0]       # all red
    matched[0, :5] = [0, 255, 0]      # 5 green (5%)
    matched[0, 5:] = [0, 0, 255]      # 5 blue (5%)
    mask_solid = np.ones((10, 10), dtype=bool)
    _test_store.put(sid, "preview_cache", {
        "matched_rgb": matched,
        "mask_solid": mask_solid,
    })
    return sid


# =========================================================================
# 1. Session not found returns 404
# =========================================================================


class TestMergeSessionNotFound:
    """Verify unknown session_id returns HTTP 404."""

    def test_merge_colors_unknown_session_returns_404(self) -> None:
        response = client.post(
            "/api/convert/merge-colors",
            json={
                "session_id": "nonexistent-session-id",
                "merge_enable": True,
                "merge_threshold": 0.5,
                "merge_max_distance": 20,
            },
        )
        assert response.status_code == 404


# =========================================================================
# 2. No preview_cache returns 409
# =========================================================================


class TestMergeNoPreviewCacheReturns409:
    """Verify missing preview_cache returns HTTP 409."""

    def test_merge_colors_no_cache_returns_409(self) -> None:
        sid = _test_store.create()
        # No preview_cache stored
        response = client.post(
            "/api/convert/merge-colors",
            json={
                "session_id": sid,
                "merge_enable": True,
                "merge_threshold": 0.5,
                "merge_max_distance": 20,
            },
        )
        assert response.status_code == 409
        assert "preview" in response.json()["detail"].lower()


# =========================================================================
# 3. merge_enable=False returns empty merge_map with quality=100
# =========================================================================


class TestMergeDisabled:
    """Verify merge_enable=False returns identity response."""

    def test_merge_disabled_returns_empty_map_and_perfect_quality(self) -> None:
        sid = _create_session_with_preview()
        response = client.post(
            "/api/convert/merge-colors",
            json={
                "session_id": sid,
                "merge_enable": False,
                "merge_threshold": 0.5,
                "merge_max_distance": 20,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["merge_map"] == {}
        assert body["quality_metric"] == 100.0
        assert body["colors_before"] == body["colors_after"]


# =========================================================================
# 4. Successful merge returns valid response fields
# =========================================================================


class TestSuccessfulMerge:
    """Verify successful merge returns merge_map, quality_metric, colors_before, colors_after."""

    def _create_session_with_mergeable_colors(self) -> str:
        """Create a session where some colors are low-usage and close to others."""
        sid = _test_store.create()
        # 10x10 image: 90 red(255,0,0), 5 near-red(254,0,0), 5 blue(0,0,255)
        # near-red is 5% usage and very close to red in CIELAB space
        matched = np.zeros((10, 10, 3), dtype=np.uint8)
        matched[:, :] = [255, 0, 0]          # 90 red
        matched[0, :5] = [254, 0, 0]         # 5 near-red (5%)
        matched[0, 5:] = [0, 0, 255]         # 5 blue (5%)
        mask_solid = np.ones((10, 10), dtype=bool)
        _test_store.put(sid, "preview_cache", {
            "matched_rgb": matched,
            "mask_solid": mask_solid,
        })
        return sid

    def test_merge_response_has_required_fields(self) -> None:
        sid = self._create_session_with_mergeable_colors()
        response = client.post(
            "/api/convert/merge-colors",
            json={
                "session_id": sid,
                "merge_enable": True,
                "merge_threshold": 5.0,  # high threshold to catch 5% colors
                "merge_max_distance": 50,
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "merge_map" in body
        assert "quality_metric" in body
        assert "colors_before" in body
        assert "colors_after" in body
        assert body["preview_url"].startswith("/api/files/")
        assert isinstance(body["quality_metric"], (int, float))
        assert 0.0 <= body["quality_metric"] <= 100.0
        assert body["colors_before"] >= body["colors_after"]


# =========================================================================
# 5. merge_map stored in session
# =========================================================================


class TestMergeMapStoredInSession:
    """Verify merge_map is persisted in session after merge."""

    def test_merge_map_saved_to_session(self) -> None:
        sid = _create_session_with_preview()
        client.post(
            "/api/convert/merge-colors",
            json={
                "session_id": sid,
                "merge_enable": True,
                "merge_threshold": 0.5,
                "merge_max_distance": 20,
            },
        )
        data = _test_store.get(sid)
        assert data is not None
        assert "merge_map" in data
        assert isinstance(data["merge_map"], dict)

    def test_merge_disabled_stores_empty_map(self) -> None:
        sid = _create_session_with_preview()
        client.post(
            "/api/convert/merge-colors",
            json={
                "session_id": sid,
                "merge_enable": False,
                "merge_threshold": 0.5,
                "merge_max_distance": 20,
            },
        )
        data = _test_store.get(sid)
        assert data is not None
        assert data["merge_map"] == {}
