"""Unit & Property-Based tests for region-3d-preview-sync.
区域 3D 预览同步的单元测试和 Property-Based 测试。

Feature: region-3d-preview-sync
Tests that the region-replace endpoint returns a valid GLB URL and
color_contours after successful region replacement, and degrades
gracefully when GLB generation fails.

**Validates: Requirements 1.1, 1.2, 1.3, 3.1**
"""

from __future__ import annotations

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.session_store import SessionStore


# ---------------------------------------------------------------------------
# Fixtures: shared app, store, registry, and client
# ---------------------------------------------------------------------------

@pytest.fixture()
def store() -> SessionStore:
    """Create a fresh SessionStore for each test.
    为每个测试创建全新的 SessionStore。
    """
    return SessionStore(ttl=600)


@pytest.fixture()
def registry() -> FileRegistry:
    """Create a fresh FileRegistry for each test.
    为每个测试创建全新的 FileRegistry。
    """
    return FileRegistry()


@pytest.fixture()
def client(store: SessionStore, registry: FileRegistry) -> TestClient:
    """Build a TestClient with overridden dependencies.
    构建使用覆盖依赖的 TestClient。
    """
    app = create_app()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Helper: set up a valid session with preview_cache and region mask
# ---------------------------------------------------------------------------

def _setup_session(
    store: SessionStore,
    matched_rgb: np.ndarray,
    region_mask: np.ndarray,
    color_contours: dict | None = None,
) -> str:
    """Populate a session with the minimum cache data for region-replace.
    为 region-replace 填充最小缓存数据到 Session 中。

    Args:
        store (SessionStore): Session store instance. (Session 存储实例)
        matched_rgb (np.ndarray): Matched RGB array (H, W, 3). (匹配 RGB 数组)
        region_mask (np.ndarray): Boolean region mask (H, W). (区域布尔掩码)
        color_contours (dict | None): Optional color contours data. (可选颜色轮廓数据)

    Returns:
        str: The created session ID. (创建的 Session ID)
    """
    session_id = store.create()
    h, w = matched_rgb.shape[:2]
    cache = {
        "matched_rgb": matched_rgb.copy(),
        "mask_solid": np.ones((h, w), dtype=bool),
        "target_w": w,
        "target_h": h,
        "target_width_mm": 10.0,
    }
    if color_contours is not None:
        cache["color_contours"] = color_contours
    store.put(session_id, "preview_cache", cache)
    store.put(session_id, "selected_region_mask", region_mask)
    store.put(session_id, "selected_region_id", 1)
    return session_id


# ---------------------------------------------------------------------------
# Hypothesis strategies
# ---------------------------------------------------------------------------

_rgb_st = st.tuples(
    st.integers(0, 255), st.integers(0, 255), st.integers(0, 255)
)


def _hex_from_rgb(r: int, g: int, b: int) -> str:
    """Convert RGB ints to hex string like '#FF0000'.
    将 RGB 整数转换为十六进制字符串。
    """
    return f"#{r:02X}{g:02X}{b:02X}"


# ===========================================================================
# Property 1: 区域替换后响应包含有效的 GLB URL 和颜色轮廓
# Feature: region-3d-preview-sync, Property 1
# **Validates: Requirements 1.1, 1.2, 3.1**
# ===========================================================================


class TestRegionReplaceGlbProperty:
    """Property 1: After region replacement, response contains valid GLB URL and color contours.
    Property 1: 区域替换后响应包含有效的 GLB URL 和颜色轮廓。

    For any valid session cache with matched_rgb, mask_solid, and
    selected_region_mask, calling region-replace SHALL return a response
    where preview_glb_url starts with '/api/files/' and color_contours
    is a non-empty dict.

    **Feature: region-3d-preview-sync, Property 1: 区域替换后响应包含有效的 GLB URL 和颜色轮廓**
    **Validates: Requirements 1.1, 1.2, 3.1**
    """

    @given(replacement_rgb=_rgb_st)
    @settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
    def test_region_replace_returns_valid_glb_url_and_contours(
        self, replacement_rgb: tuple[int, int, int],
        store: SessionStore, registry: FileRegistry, client: TestClient,
    ) -> None:
        """For any random replacement color, region-replace SHALL return
        a preview_glb_url starting with '/api/files/' and a non-empty
        color_contours dict when GLB generation succeeds.

        对于任意随机替换颜色，当 GLB 生成成功时，region-replace 应返回
        以 '/api/files/' 开头的 preview_glb_url 和非空的 color_contours 字典。

        **Validates: Requirements 1.1, 1.2, 3.1**
        """
        r, g, b = replacement_rgb
        hex_color = _hex_from_rgb(r, g, b)

        # Set up a 4x4 image with a 2x2 region mask
        matched_rgb = np.full((4, 4, 3), [128, 64, 32], dtype=np.uint8)
        region_mask = np.zeros((4, 4), dtype=bool)
        region_mask[1:3, 1:3] = True

        fake_contours = {"ff0000": [[[0, 0], [1, 0], [1, 1]]]}
        session_id = _setup_session(store, matched_rgb, region_mask)

        # Create a temp GLB file to simulate successful generation
        fd, fake_glb_path = tempfile.mkstemp(suffix=".glb")
        os.write(fd, b"fake-glb-data")
        os.close(fd)

        try:
            with patch(
                "api.routers.converter.generate_segmented_glb"
            ) as mock_glb:
                # Mock GLB generation: write contours into cache and return path
                def _fake_generate(cache: dict) -> str:
                    cache["color_contours"] = fake_contours
                    return fake_glb_path

                mock_glb.side_effect = _fake_generate

                resp = client.post(
                    "/api/convert/region-replace",
                    json={"session_id": session_id, "replacement_color": hex_color},
                )

            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
            data = resp.json()

            # Property assertions
            assert data["preview_glb_url"] is not None, "preview_glb_url should not be None"
            assert data["preview_glb_url"].startswith("/api/files/"), (
                f"preview_glb_url should start with '/api/files/', got: {data['preview_glb_url']}"
            )
            assert data["color_contours"] is not None, "color_contours should not be None"
            assert isinstance(data["color_contours"], dict), "color_contours should be a dict"
            assert len(data["color_contours"]) > 0, "color_contours should be non-empty"
        finally:
            if os.path.exists(fake_glb_path):
                os.unlink(fake_glb_path)


# ===========================================================================
# Unit Test: GLB 失败时优雅降级
# **Validates: Requirements 1.3**
# ===========================================================================


class TestRegionReplaceGlbGracefulDegradation:
    """GLB generation failure should degrade gracefully.
    GLB 生成失败时应优雅降级。

    When generate_segmented_glb raises an exception, the endpoint SHALL
    return preview_glb_url=None while still returning a valid 2D preview.

    **Validates: Requirements 1.3**
    """

    def test_glb_failure_returns_none_glb_url(
        self, store: SessionStore, registry: FileRegistry, client: TestClient,
    ) -> None:
        """When generate_segmented_glb raises, preview_glb_url SHALL be None
        and the 2D preview SHALL still be valid.

        当 generate_segmented_glb 抛出异常时，preview_glb_url 应为 None，
        且 2D 预览仍应有效。

        **Validates: Requirements 1.3**
        """
        matched_rgb = np.full((4, 4, 3), [100, 200, 50], dtype=np.uint8)
        region_mask = np.zeros((4, 4), dtype=bool)
        region_mask[0:2, 0:2] = True
        session_id = _setup_session(store, matched_rgb, region_mask)

        with patch(
            "api.routers.converter.generate_segmented_glb",
            side_effect=RuntimeError("GLB generation failed"),
        ):
            resp = client.post(
                "/api/convert/region-replace",
                json={"session_id": session_id, "replacement_color": "#FF0000"},
            )

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()

        # GLB URL should be None (graceful degradation)
        assert data["preview_glb_url"] is None, (
            "preview_glb_url should be None when GLB generation fails"
        )
        # 2D preview should still be valid
        assert data["preview_url"] is not None, "preview_url should still be present"
        assert data["preview_url"].startswith("/api/files/"), (
            "preview_url should be a valid file URL"
        )
        # Response message should indicate success (2D worked)
        assert "message" in data

    def test_glb_returns_none_path_gracefully(
        self, store: SessionStore, registry: FileRegistry, client: TestClient,
    ) -> None:
        """When generate_segmented_glb returns None, preview_glb_url SHALL be None.

        当 generate_segmented_glb 返回 None 时，preview_glb_url 应为 None。

        **Validates: Requirements 1.3**
        """
        matched_rgb = np.full((4, 4, 3), [50, 100, 150], dtype=np.uint8)
        region_mask = np.zeros((4, 4), dtype=bool)
        region_mask[2:4, 2:4] = True
        session_id = _setup_session(store, matched_rgb, region_mask)

        with patch(
            "api.routers.converter.generate_segmented_glb",
            return_value=None,
        ):
            resp = client.post(
                "/api/convert/region-replace",
                json={"session_id": session_id, "replacement_color": "#00FF00"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["preview_glb_url"] is None
        assert data["preview_url"].startswith("/api/files/")


# ===========================================================================
# Unit Test: color_contours 包含在响应中
# **Validates: Requirements 3.1**
# ===========================================================================


class TestRegionReplaceColorContours:
    """color_contours data should be included in the response.
    颜色轮廓数据应包含在响应中。

    When generate_segmented_glb updates cache['color_contours'],
    the response SHALL include the updated contours data.

    **Validates: Requirements 3.1**
    """

    def test_color_contours_included_in_response(
        self, store: SessionStore, registry: FileRegistry, client: TestClient,
    ) -> None:
        """Response SHALL include color_contours when cache has contour data.

        当缓存中有轮廓数据时，响应应包含 color_contours。

        **Validates: Requirements 3.1**
        """
        matched_rgb = np.full((4, 4, 3), [200, 100, 50], dtype=np.uint8)
        region_mask = np.zeros((4, 4), dtype=bool)
        region_mask[0:2, 0:2] = True
        session_id = _setup_session(store, matched_rgb, region_mask)

        expected_contours = {
            "c84632": [[[0, 0], [1, 0], [1, 1], [0, 1]]],
            "ff0000": [[[2, 2], [3, 2], [3, 3], [2, 3]]],
        }

        fd, fake_glb_path = tempfile.mkstemp(suffix=".glb")
        os.write(fd, b"fake-glb")
        os.close(fd)

        try:
            with patch(
                "api.routers.converter.generate_segmented_glb"
            ) as mock_glb:
                def _fake_generate(cache: dict) -> str:
                    cache["color_contours"] = expected_contours
                    return fake_glb_path

                mock_glb.side_effect = _fake_generate

                resp = client.post(
                    "/api/convert/region-replace",
                    json={"session_id": session_id, "replacement_color": "#FF0000"},
                )

            assert resp.status_code == 200
            data = resp.json()

            assert data["color_contours"] is not None, "color_contours should be present"
            assert data["color_contours"] == expected_contours, (
                f"color_contours mismatch: {data['color_contours']}"
            )
        finally:
            if os.path.exists(fake_glb_path):
                os.unlink(fake_glb_path)

    def test_color_contours_none_when_not_in_cache(
        self, store: SessionStore, registry: FileRegistry, client: TestClient,
    ) -> None:
        """Response SHALL have color_contours=None when cache has no contour data
        and GLB generation does not produce any.

        当缓存中无轮廓数据且 GLB 生成未产生轮廓时，color_contours 应为 None。

        **Validates: Requirements 3.1**
        """
        matched_rgb = np.full((4, 4, 3), [80, 80, 80], dtype=np.uint8)
        region_mask = np.zeros((4, 4), dtype=bool)
        region_mask[1:3, 1:3] = True
        session_id = _setup_session(store, matched_rgb, region_mask)

        fd, fake_glb_path = tempfile.mkstemp(suffix=".glb")
        os.write(fd, b"fake-glb")
        os.close(fd)

        try:
            with patch(
                "api.routers.converter.generate_segmented_glb",
                return_value=fake_glb_path,
            ):
                resp = client.post(
                    "/api/convert/region-replace",
                    json={"session_id": session_id, "replacement_color": "#AABBCC"},
                )

            assert resp.status_code == 200
            data = resp.json()
            # No contours were set in cache, so should be None
            assert data["color_contours"] is None
        finally:
            if os.path.exists(fake_glb_path):
                os.unlink(fake_glb_path)
