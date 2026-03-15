"""Backend tests for color-replace architecture fix.
颜色替换架构修复后端测试。

Validates:
- region-replace endpoint returns preview_glb_url=None and no NameError (Requirement 1.1, 1.2)
- reset-replacements endpoint correctly restores original_matched_rgb (Requirement 4.3, 4.4)
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


def setup_module(module) -> None:
    """Re-apply dependency overrides before this module's tests run.
    在本模块测试运行前重新设置依赖覆盖，确保跨文件测试隔离。
    """
    app.dependency_overrides[get_session_store] = lambda: _test_store
    app.dependency_overrides[get_file_registry] = lambda: _test_registry


def teardown_module(module) -> None:
    """Remove this module's dependency overrides after all tests complete.
    本模块所有测试完成后移除依赖覆盖。
    """
    app.dependency_overrides.pop(get_session_store, None)
    app.dependency_overrides.pop(get_file_registry, None)


# Apply overrides immediately for module-level client creation
setup_module(None)

client: TestClient = TestClient(app)


def _create_session_with_region() -> str:
    """Create a session with preview_cache and a selected region mask for region-replace testing.
    创建带有 preview_cache 和已选中区域掩码的 session，用于 region-replace 测试。

    Returns:
        str: Session ID. (会话 ID)
    """
    sid = _test_store.create()
    # 4x4 image: top-left 2x2 red, rest green
    matched = np.zeros((4, 4, 3), dtype=np.uint8)
    matched[:2, :2] = [255, 0, 0]   # red region
    matched[2:, :] = [0, 255, 0]    # green
    matched[:2, 2:] = [0, 255, 0]   # green

    # Also need quantized_image and mask_solid for generate_segmented_glb
    mask_solid = np.ones((4, 4), dtype=bool)

    _test_store.put(sid, "preview_cache", {
        "matched_rgb": matched,
        "quantized_image": matched.copy(),
        "mask_solid": mask_solid,
    })
    # Save pristine copy for reset
    _test_store.put(sid, "original_matched_rgb", matched.copy())
    _test_store.put(sid, "replacement_regions", [])
    _test_store.put(sid, "replacement_history", [])

    # Pre-select a region mask (top-left 2x2 red pixels)
    region_mask = np.zeros((4, 4), dtype=bool)
    region_mask[:2, :2] = True
    _test_store.put(sid, "selected_region_mask", region_mask)
    _test_store.put(sid, "selected_region_id", "test-region-id")

    return sid


# =========================================================================
# Task 5.8: region-replace returns preview_glb_url=None, no NameError
# =========================================================================


class TestRegionReplaceNoNameError:
    """Verify region-replace endpoint returns 200 with preview_glb_url=None.
    验证 region-replace 端点返回 200 且 preview_glb_url 为 None。

    **Validates: Requirements 1.1, 1.2**
    """

    def test_region_replace_returns_200(self) -> None:
        """Endpoint returns HTTP 200 without NameError.
        端点返回 HTTP 200，不抛出 NameError。
        """
        sid = _create_session_with_region()
        response = client.post(
            "/api/convert/region-replace",
            json={
                "session_id": sid,
                "replacement_color": "#0000ff",
            },
        )
        assert response.status_code == 200

    def test_region_replace_preview_glb_url_is_none(self) -> None:
        """Response preview_glb_url is null (None in JSON).
        响应中 preview_glb_url 为 null。
        """
        sid = _create_session_with_region()
        response = client.post(
            "/api/convert/region-replace",
            json={
                "session_id": sid,
                "replacement_color": "#0000ff",
            },
        )
        body = response.json()
        assert body["preview_glb_url"] is None

    def test_region_replace_returns_preview_url(self) -> None:
        """Response contains a valid preview_url.
        响应包含有效的 preview_url。
        """
        sid = _create_session_with_region()
        response = client.post(
            "/api/convert/region-replace",
            json={
                "session_id": sid,
                "replacement_color": "#0000ff",
            },
        )
        body = response.json()
        assert body["preview_url"].startswith("/api/files/")

    def test_region_replace_updates_matched_rgb(self) -> None:
        """Region replacement modifies cache matched_rgb within the mask.
        区域替换修改了掩码范围内的 cache matched_rgb。
        """
        sid = _create_session_with_region()
        client.post(
            "/api/convert/region-replace",
            json={
                "session_id": sid,
                "replacement_color": "#0000ff",
            },
        )
        data = _test_store.get(sid)
        cache = data["preview_cache"]
        matched = cache["matched_rgb"]
        # Top-left 2x2 should now be blue (0, 0, 255)
        expected_blue = np.full((2, 2, 3), [0, 0, 255], dtype=np.uint8)
        np.testing.assert_array_equal(matched[:2, :2], expected_blue)
        # Rest should remain green
        expected_green = np.full((2, 4, 3), [0, 255, 0], dtype=np.uint8)
        np.testing.assert_array_equal(matched[2:, :], expected_green)

    def test_region_replace_no_region_returns_409(self) -> None:
        """Calling region-replace without prior region-detect returns 409.
        未先调用 region-detect 就调用 region-replace 返回 409。
        """
        sid = _test_store.create()
        matched = np.zeros((4, 4, 3), dtype=np.uint8)
        matched[:] = [255, 0, 0]
        _test_store.put(sid, "preview_cache", {"matched_rgb": matched})
        # No selected_region_mask set

        response = client.post(
            "/api/convert/region-replace",
            json={
                "session_id": sid,
                "replacement_color": "#0000ff",
            },
        )
        assert response.status_code == 409


# =========================================================================
# Task 5.9: reset-replacements restores original_matched_rgb
# =========================================================================


class TestResetReplacementsRestoresOriginal:
    """Verify reset-replacements endpoint restores matched_rgb from original.
    验证 reset-replacements 端点从 original_matched_rgb 恢复 matched_rgb。

    **Validates: Requirements 4.3, 4.4**
    """

    def test_reset_restores_matched_rgb(self) -> None:
        """After region-replace + reset, matched_rgb equals original.
        执行 region-replace 后再 reset，matched_rgb 恢复为原始值。
        """
        sid = _create_session_with_region()
        original = _test_store.get(sid)["original_matched_rgb"].copy()

        # Perform a region replacement (modifies matched_rgb)
        client.post(
            "/api/convert/region-replace",
            json={
                "session_id": sid,
                "replacement_color": "#0000ff",
            },
        )

        # Verify matched_rgb was modified
        data = _test_store.get(sid)
        cache = data["preview_cache"]
        assert not np.array_equal(cache["matched_rgb"], original)

        # Reset replacements
        response = client.post(
            "/api/convert/reset-replacements",
            json={"session_id": sid},
        )
        assert response.status_code == 200

        # Verify matched_rgb is restored to original
        data = _test_store.get(sid)
        cache = data["preview_cache"]
        np.testing.assert_array_equal(cache["matched_rgb"], original)

    def test_reset_returns_preview_url(self) -> None:
        """Reset response contains a valid preview_url.
        重置响应包含有效的 preview_url。
        """
        sid = _create_session_with_region()
        response = client.post(
            "/api/convert/reset-replacements",
            json={"session_id": sid},
        )
        body = response.json()
        assert body["status"] == "ok"
        assert body["preview_url"].startswith("/api/files/")

    def test_reset_clears_replacement_regions(self) -> None:
        """Reset clears replacement_regions to empty list.
        重置后 replacement_regions 清空为空列表。
        """
        sid = _create_session_with_region()

        # Add a replacement via replace-color
        client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#ff0000",
                "replacement_color": "#0000ff",
            },
        )
        data = _test_store.get(sid)
        assert len(data["replacement_regions"]) > 0

        # Reset
        client.post(
            "/api/convert/reset-replacements",
            json={"session_id": sid},
        )
        data = _test_store.get(sid)
        assert data["replacement_regions"] == []

    def test_reset_clears_replacement_history(self) -> None:
        """Reset clears replacement_history to empty list.
        重置后 replacement_history 清空为空列表。
        """
        sid = _create_session_with_region()

        # Add a replacement to create history
        client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#ff0000",
                "replacement_color": "#0000ff",
            },
        )
        data = _test_store.get(sid)
        assert len(data["replacement_history"]) > 0

        # Reset
        client.post(
            "/api/convert/reset-replacements",
            json={"session_id": sid},
        )
        data = _test_store.get(sid)
        assert data["replacement_history"] == []

    def test_reset_without_original_uses_current(self) -> None:
        """When no original_matched_rgb saved, reset uses current cache.
        当没有保存 original_matched_rgb 时，重置使用当前缓存。
        """
        sid = _test_store.create()
        matched = np.zeros((4, 4, 3), dtype=np.uint8)
        matched[:] = [128, 128, 128]
        _test_store.put(sid, "preview_cache", {
            "matched_rgb": matched,
            "quantized_image": matched.copy(),
            "mask_solid": np.ones((4, 4), dtype=bool),
        })
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "replacement_history", [])
        # Intentionally NOT setting original_matched_rgb

        response = client.post(
            "/api/convert/reset-replacements",
            json={"session_id": sid},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
