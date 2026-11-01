"""Regression tests for the batch replace endpoints.

Covers ``POST /api/convert/replace-colors-batch`` and
``POST /api/convert/region-replace-batch`` — the two endpoints added to
eliminate the "multi-colour / multi-region replace feels slow" regression.
The legacy per-colour / per-region endpoints regenerate the segmented GLB
on every call; batch endpoints must produce the same pixel-level state as
the loop but report a single replacement in the response (one PNG+GLB
render for the whole batch).

批量替换端点的回归测试：验证批量端点的像素效果与循环调用等价，但语义上
只做一次 PNG/GLB 渲染。测试也固定错误路径（404/409/400）。
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.routers.converter import replace as replace_router
from api.session_store import SessionStore
from core.gradient_group_analyzer import REGION_ID_ENCODING_MULTIPLIER


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_batch_cache_tests_from_async_glb(monkeypatch):
    """Batch endpoint assertions must not leak real GLB worker threads."""

    monkeypatch.setattr(
        replace_router,
        "schedule_glb_build",
        lambda *_args, **_kwargs: "test-glb-token",
    )


def _make_client(
    matched_rgb: np.ndarray,
    *,
    mask_solid: np.ndarray | None = None,
    quantized_image: np.ndarray | None = None,
    region_id_map: np.ndarray | None = None,
) -> tuple[TestClient, str, SessionStore]:
    """Build a TestClient + session seeded with just enough cache to drive
    the batch replace endpoints.
    构造 TestClient + 预置 session，覆盖 batch 端点需要的 cache 字段。
    """
    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry

    sid = store.create()
    cache: dict = {
        "matched_rgb": matched_rgb.copy(),
        "original_matched_rgb": matched_rgb.copy(),
        "height_identity_rgb": matched_rgb.copy(),
    }
    if mask_solid is not None:
        cache["mask_solid"] = mask_solid.copy()
    if quantized_image is not None:
        cache["quantized_image"] = quantized_image.copy()
    store.put(sid, "preview_cache", cache)
    store.put(sid, "replacement_regions", [])
    store.put(sid, "replacement_history", [])
    if region_id_map is not None:
        store.put(sid, "gradient_region_id_map", region_id_map.copy())
    return TestClient(app), sid, store


@pytest.fixture()
def red_green_canvas() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """4x4 canvas: top 2 rows red, bottom 2 rows green.
    Plus a solid mask and a quantised preview (identical to matched_rgb
    since there's no dithering).
    4x4 画布：上半红、下半绿；mask 全 1；quantized 等于 matched。
    """
    matched = np.zeros((4, 4, 3), dtype=np.uint8)
    matched[:2, :] = (255, 0, 0)
    matched[2:, :] = (0, 255, 0)
    mask_solid = np.ones((4, 4), dtype=bool)
    quantized = matched.copy()
    return matched, mask_solid, quantized


# ---------------------------------------------------------------------------
# /replace-colors-batch
# ---------------------------------------------------------------------------


class TestReplaceColorsBatch:
    def test_retry_after_lost_response_does_not_apply_or_record_the_edit_twice(
        self,
        red_green_canvas: tuple[np.ndarray, np.ndarray, np.ndarray],
    ) -> None:
        matched, mask_solid, quantized = red_green_canvas
        client, sid, store = _make_client(
            matched, mask_solid=mask_solid, quantized_image=quantized,
        )
        request = {
            "session_id": sid,
            "operation_id": "interrupted-batch-1",
            "replacements": [{"selected_color": "#ff0000", "replacement_color": "#0000ff"}],
        }
        with client:
            first = client.post("/api/convert/replace-colors-batch", json=request)
            assert first.status_code == 200, first.text
            after_first = store.get(sid)["preview_cache"]["matched_rgb"].copy()
            history_size = len(store.get(sid)["replacement_undo_stack"])
            assert history_size == 1

            retry = client.post("/api/convert/replace-colors-batch", json=request)
            assert retry.status_code == 409, retry.text
            np.testing.assert_array_equal(store.get(sid)["preview_cache"]["matched_rgb"], after_first)
            assert len(store.get(sid)["replacement_undo_stack"]) == history_size

            receipt = client.get(f"/api/convert/editor-commit/{sid}/interrupted-batch-1")
            assert receipt.status_code == 200, receipt.text
            assert receipt.json()["status"] == "committed"
            assert receipt.json()["editor_content_revision"] == first.json()["editor_content_revision"]
            assert receipt.json()["result"]["replacement_regions"] == [{
                "quantized_hex": "#ff0000", "matched_hex": "#ff0000", "replacement_hex": "#0000ff",
            }]
            assert receipt.json()["result"]["preview_url"] == first.json()["preview_url"]

    def test_global_replace_returns_authoritative_selection_revision_for_next_gesture(
        self,
        red_green_canvas: tuple[np.ndarray, np.ndarray, np.ndarray],
    ) -> None:
        """A global replace rebases the selection before the next mutation.
        全局换色后，服务端必须先重绑选区内容版本，下一次选区手势才能继续。

        This drives the real selection endpoint, preview-cache transaction, visible
        component cache, and batch replacement endpoint together. A client-side
        ``content_revision + 1`` guess is deliberately not used.
        该用例串联真实选区端点、预览缓存事务、可见组件缓存和批量替色端点，
        明确不依赖客户端猜测 ``content_revision + 1``。
        """
        matched, mask_solid, quantized = red_green_canvas
        client, sid, store = _make_client(
            matched,
            mask_solid=mask_solid,
            quantized_image=quantized,
        )

        selected = client.post(
            "/api/convert/selection/mutate",
            json={
                "session_id": sid,
                "operation": "same-color-toggle",
                "base_selection_revision": 0,
                "content_revision": 0,
                "color_hex": "ff0000",
            },
        )
        assert selected.status_code == 200, selected.text
        before_replace = selected.json()
        assert before_replace["selected_pixel_count"] == 8

        first_replace = client.post(
            "/api/convert/replace-colors-batch",
            json={
                "session_id": sid,
                "replacements": [
                    {"selected_color": "#ff0000", "replacement_color": "#0000ff"},
                ],
            },
        )
        assert first_replace.status_code == 200, first_replace.text
        first_body = first_replace.json()
        first_selection = first_body["selection"]
        assert first_selection["selection_revision"] == before_replace["selection_revision"]
        assert first_selection["content_revision"] != before_replace["content_revision"]
        assert first_selection["selected_color_hexes"] == ["#0000ff"]

        selected_again = client.post(
            "/api/convert/selection/mutate",
            json={
                "session_id": sid,
                "operation": "same-color-toggle",
                "base_selection_revision": first_selection["selection_revision"],
                "content_revision": first_selection["content_revision"],
                "color_hex": "0000ff",
            },
        )
        assert selected_again.status_code == 200, selected_again.text
        second_selection = selected_again.json()
        assert second_selection["selection_revision"] > first_selection["selection_revision"]
        assert second_selection["selected_pixel_count"] == 0

        second_replace = client.post(
            "/api/convert/replace-colors-batch",
            json={
                "session_id": sid,
                "replacements": [
                    {"selected_color": "#ff0000", "replacement_color": "#0000ff"},
                    {"selected_color": "#00ff00", "replacement_color": "#ffff00"},
                ],
            },
        )
        assert second_replace.status_code == 200, second_replace.text
        assert second_replace.json()["selection"]["content_revision"] != (
            second_selection["content_revision"]
        )
        np.testing.assert_array_equal(
            store.get(sid)["preview_cache"]["matched_rgb"][:2, :],
            np.full((2, 4, 3), [0, 0, 255], dtype=np.uint8),
        )
        np.testing.assert_array_equal(
            store.get(sid)["preview_cache"]["matched_rgb"][2:, :],
            np.full((2, 4, 3), [255, 255, 0], dtype=np.uint8),
        )

    def test_fifty_sequential_edits_keep_selection_and_content_versions_aligned(
        self,
        red_green_canvas: tuple[np.ndarray, np.ndarray, np.ndarray],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Fifty ordered edits must not self-create a stale-content 409.
        连续 50 次有序编辑不能因为客户端自身版本不同步而产生 409。
        """
        monkeypatch.setattr(
            replace_router,
            "schedule_visible_region_cache_prewarm",
            lambda *_args, **_kwargs: None,
        )
        matched, mask_solid, quantized = red_green_canvas
        client, sid, store = _make_client(
            matched,
            mask_solid=mask_solid,
            quantized_image=quantized,
        )

        selected = client.post(
            "/api/convert/selection/mutate",
            json={
                "session_id": sid,
                "operation": "same-color-toggle",
                "base_selection_revision": 0,
                "content_revision": 0,
                "color_hex": "ff0000",
            },
        )
        assert selected.status_code == 200, selected.text
        document = selected.json()
        content_revisions: list[int] = []

        palette = ["0000ff", "ffff00", "ff00ff", "00ffff"]
        for index in range(50):
            target = palette[index % len(palette)]
            replacement = client.post(
                "/api/convert/replace-colors-batch",
                json={
                    "session_id": sid,
                    "replacements": [
                        {"selected_color": "#ff0000", "replacement_color": f"#{target}"},
                        {"selected_color": "#00ff00", "replacement_color": "#101010"},
                    ],
                },
            )
            assert replacement.status_code == 200, (
                f"edit {index + 1} failed: {replacement.text}"
            )
            response_document = replacement.json()["selection"]
            content_revisions.append(response_document["content_revision"])
            assert response_document["selection_revision"] == document["selection_revision"]
            assert response_document["selected_color_hexes"] == [f"#{target}"]

            cleared = client.post(
                "/api/convert/selection/mutate",
                json={
                    "session_id": sid,
                    "operation": "same-color-toggle",
                    "base_selection_revision": response_document["selection_revision"],
                    "content_revision": response_document["content_revision"],
                    "color_hex": target,
                },
            )
            assert cleared.status_code == 200, (
                f"clear {index + 1} failed: {cleared.text}"
            )
            document = cleared.json()
            assert document["selected_pixel_count"] == 0

            if index < 49:
                selected_next = client.post(
                    "/api/convert/selection/mutate",
                    json={
                        "session_id": sid,
                        "operation": "same-color-toggle",
                        "base_selection_revision": document["selection_revision"],
                        "content_revision": document["content_revision"],
                        "color_hex": target,
                    },
                )
                assert selected_next.status_code == 200, (
                    f"select {index + 1} failed: {selected_next.text}"
                )
                document = selected_next.json()
                assert document["selected_pixel_count"] == 8

        assert content_revisions == sorted(set(content_revisions))
        assert len(content_revisions) == 50
        np.testing.assert_array_equal(
            store.get(sid)["preview_cache"]["matched_rgb"][:2, :],
            np.full((2, 4, 3), [255, 255, 0], dtype=np.uint8),
        )

    def test_batch_applies_all_pairs_in_one_call(
        self, red_green_canvas: tuple[np.ndarray, np.ndarray, np.ndarray]
    ) -> None:
        """All pairs mutate matched_rgb in a single request.
        一次请求里所有 pair 都应用到 matched_rgb。
        """
        matched, mask_solid, quantized = red_green_canvas
        client, sid, store = _make_client(
            matched, mask_solid=mask_solid, quantized_image=quantized
        )

        response = client.post(
            "/api/convert/replace-colors-batch",
            json={
                "session_id": sid,
                "replacements": [
                    {"selected_color": "#ff0000", "replacement_color": "#0000ff"},
                    {"selected_color": "#00ff00", "replacement_color": "#ffff00"},
                ],
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "ok"
        assert body["replacement_count"] == 2
        assert body["preview_url"].startswith("/api/files/")

        updated = store.get(sid)["preview_cache"]["matched_rgb"]
        assert np.all(updated[:2, :] == (0, 0, 255)), "red → blue"
        assert np.all(updated[2:, :] == (255, 255, 0)), "green → yellow"
        np.testing.assert_array_equal(
            store.get(sid)["preview_cache"]["height_identity_rgb"],
            matched,
        )

    def test_batch_reset_and_replay_never_rekeys_height_identity(
        self, red_green_canvas: tuple[np.ndarray, np.ndarray, np.ndarray]
    ) -> None:
        """Undo-style reset/replay changes display RGB, never height identity."""
        matched, mask_solid, quantized = red_green_canvas
        client, sid, store = _make_client(
            matched, mask_solid=mask_solid, quantized_image=quantized
        )
        batch_payload = {
            "session_id": sid,
            "replacements": [
                {"selected_color": "#ff0000", "replacement_color": "#0000ff"},
                {"selected_color": "#00ff00", "replacement_color": "#ffff00"},
            ],
        }

        assert client.post(
            "/api/convert/replace-colors-batch", json=batch_payload
        ).status_code == 200
        np.testing.assert_array_equal(
            store.get(sid)["preview_cache"]["height_identity_rgb"], matched
        )

        assert client.post(
            "/api/convert/reset-replacements", json={"session_id": sid}
        ).status_code == 200
        reset_cache = store.get(sid)["preview_cache"]
        np.testing.assert_array_equal(reset_cache["matched_rgb"], matched)
        np.testing.assert_array_equal(reset_cache["height_identity_rgb"], matched)

        assert client.post(
            "/api/convert/replace-colors-batch", json=batch_payload
        ).status_code == 200
        replay_cache = store.get(sid)["preview_cache"]
        assert not np.array_equal(replay_cache["matched_rgb"], matched)
        np.testing.assert_array_equal(replay_cache["height_identity_rgb"], matched)

    def test_batch_appends_all_regions_and_single_history_snapshot(
        self, red_green_canvas: tuple[np.ndarray, np.ndarray, np.ndarray]
    ) -> None:
        """replacement_regions grows by N; undo stack grows by 1.
        replacement_regions 增加 N 条，undo 栈只增加 1 个快照。
        """
        matched, mask_solid, quantized = red_green_canvas
        client, sid, store = _make_client(
            matched, mask_solid=mask_solid, quantized_image=quantized
        )

        client.post(
            "/api/convert/replace-colors-batch",
            json={
                "session_id": sid,
                "replacements": [
                    {"selected_color": "#ff0000", "replacement_color": "#0000ff"},
                    {"selected_color": "#00ff00", "replacement_color": "#ffff00"},
                ],
            },
        )
        data = store.get(sid)
        assert len(data["replacement_regions"]) == 2
        assert data["replacement_regions"][0]["selected_color"] == "#ff0000"
        assert data["replacement_regions"][1]["selected_color"] == "#00ff00"
        # Single batch → single pre-change checkpoint (not N).
        # 整批只有 1 个 checkpoint，不是 N 个。
        assert len(data["replacement_undo_stack"]) == 1
        checkpoint = data["replacement_undo_stack"][0]
        assert checkpoint["session_fields"]["replacement_regions"] == []

    def test_batch_undo_redo_restores_backend_cache(
        self, red_green_canvas: tuple[np.ndarray, np.ndarray, np.ndarray]
    ) -> None:
        """Undo/redo restores the backend preview cache, not just frontend metadata.
        撤销/重做恢复后端 preview_cache，而不是只恢复前端元数据。
        """
        matched, mask_solid, quantized = red_green_canvas
        client, sid, store = _make_client(
            matched, mask_solid=mask_solid, quantized_image=quantized
        )

        response = client.post(
            "/api/convert/replace-colors-batch",
            json={
                "session_id": sid,
                "replacements": [
                    {"selected_color": "#ff0000", "replacement_color": "#0000ff"},
                ],
            },
        )
        assert response.status_code == 200, response.text
        replaced = store.get(sid)["preview_cache"]["matched_rgb"].copy()
        assert np.all(replaced[:2, :] == (0, 0, 255))

        undo = client.post(
            "/api/convert/replacement-history",
            json={"session_id": sid, "action": "undo"},
        )
        assert undo.status_code == 200, undo.text
        assert undo.json()["can_redo"] is True
        restored = store.get(sid)["preview_cache"]["matched_rgb"]
        np.testing.assert_array_equal(restored, matched)
        assert store.get(sid)["replacement_regions"] == []

        redo = client.post(
            "/api/convert/replacement-history",
            json={"session_id": sid, "action": "redo"},
        )
        assert redo.status_code == 200, redo.text
        np.testing.assert_array_equal(
            store.get(sid)["preview_cache"]["matched_rgb"],
            replaced,
        )
        assert len(store.get(sid)["replacement_regions"]) == 1

    def test_batch_replays_from_original_rgb_for_undo_redo(
        self, red_green_canvas: tuple[np.ndarray, np.ndarray, np.ndarray]
    ) -> None:
        """A later batch is the full desired map, not an append-only delta.
        后续批量请求代表“当前完整映射”，必须从原图重放，支持撤销/重做。
        """
        matched, mask_solid, quantized = red_green_canvas
        client, sid, store = _make_client(
            matched, mask_solid=mask_solid, quantized_image=quantized
        )
        store.put(sid, "original_matched_rgb", matched.copy())

        response_a = client.post(
            "/api/convert/replace-colors-batch",
            json={
                "session_id": sid,
                "replacements": [
                    {"selected_color": "#ff0000", "replacement_color": "#0000ff"},
                ],
            },
        )
        assert response_a.status_code == 200, response_a.text
        updated_a = store.get(sid)["preview_cache"]["matched_rgb"]
        assert np.all(updated_a[:2, :] == (0, 0, 255))

        response_b = client.post(
            "/api/convert/replace-colors-batch",
            json={
                "session_id": sid,
                "replacements": [
                    {"selected_color": "#ff0000", "replacement_color": "#ffff00"},
                ],
            },
        )
        assert response_b.status_code == 200, response_b.text
        updated_b = store.get(sid)["preview_cache"]["matched_rgb"]
        assert np.all(updated_b[:2, :] == (255, 255, 0))
        assert store.get(sid)["replacement_regions"] == [
            {"selected_color": "#ff0000", "replacement_color": "#ffff00"}
        ]

    def test_batch_unknown_session_returns_404(
        self, red_green_canvas: tuple[np.ndarray, np.ndarray, np.ndarray]
    ) -> None:
        matched, *_ = red_green_canvas
        client, _, _ = _make_client(matched)
        response = client.post(
            "/api/convert/replace-colors-batch",
            json={
                "session_id": "bogus",
                "replacements": [
                    {"selected_color": "#ff0000", "replacement_color": "#0000ff"}
                ],
            },
        )
        assert response.status_code == 404

    def test_batch_no_preview_cache_returns_409(self) -> None:
        app = create_app()
        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        app.dependency_overrides[get_session_store] = lambda: store
        app.dependency_overrides[get_file_registry] = lambda: registry
        client = TestClient(app)
        sid = store.create()  # no preview_cache

        response = client.post(
            "/api/convert/replace-colors-batch",
            json={
                "session_id": sid,
                "replacements": [
                    {"selected_color": "#ff0000", "replacement_color": "#0000ff"}
                ],
            },
        )
        assert response.status_code == 409

    def test_batch_empty_replacements_restores_original_global_remaps_only(
        self, red_green_canvas: tuple[np.ndarray, np.ndarray, np.ndarray]
    ) -> None:
        """Empty list replays to no global remap without clearing recipes.
        空列表用于撤销到“没有全局换色”，但不清空自定义配方状态。
        """
        matched, mask_solid, quantized = red_green_canvas
        client, sid, store = _make_client(
            matched, mask_solid=mask_solid, quantized_image=quantized
        )
        custom_base = matched.copy()
        custom_base[0, 0] = (128, 128, 128)
        store.get(sid)["preview_cache"]["matched_rgb"] = custom_base.copy()
        material_base = np.zeros((*matched.shape[:2], 2), dtype=np.int16)
        material_base[0, 0] = [7, 7]
        store.get(sid)["preview_cache"]["material_matrix"] = material_base.copy()
        store.put(sid, "original_matched_rgb", matched.copy())
        store.put(sid, "recipe_overrides", [{"region_id": "r1", "recipe": [0]}])

        client.post(
            "/api/convert/replace-colors-batch",
            json={
                "session_id": sid,
                "replacements": [
                    {"selected_color": "#ff0000", "replacement_color": "#0000ff"},
                ],
            },
        )
        response = client.post(
            "/api/convert/replace-colors-batch",
            json={"session_id": sid, "replacements": []},
        )
        assert response.status_code == 200, response.text
        updated = store.get(sid)["preview_cache"]["matched_rgb"]
        assert np.array_equal(updated, custom_base)
        updated_material = store.get(sid)["preview_cache"]["material_matrix"]
        assert np.array_equal(updated_material, material_base)
        assert store.get(sid)["replacement_regions"] == []
        assert store.get(sid)["recipe_overrides"] == [
            {"region_id": "r1", "recipe": [0]}
        ]


# ---------------------------------------------------------------------------
# /region-replace-batch
# ---------------------------------------------------------------------------


@pytest.fixture()
def two_red_stripes() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """100x100 all-red canvas; two gradient regions tagged inside.
    region 1 covers x∈[10,40); region 2 covers x∈[60,90).
    Quantised preview + mask_solid also supplied so click items work.
    """
    matched = np.full((100, 100, 3), (255, 0, 0), dtype=np.uint8)
    mask_solid = np.ones((100, 100), dtype=bool)
    quantized = matched.copy()
    region_id_map = np.zeros((100, 100), dtype=np.uint32)
    region_id_map[:, 10:40] = 1 * REGION_ID_ENCODING_MULTIPLIER + 1
    region_id_map[:, 60:90] = 1 * REGION_ID_ENCODING_MULTIPLIER + 2
    return matched, mask_solid, quantized, region_id_map


class TestRegionReplaceBatch:
    def test_batch_two_gradient_regions_different_targets(
        self,
        two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    ) -> None:
        """Two gradient-region items land different colours in one call.
        一次请求里两个 gradient region 分别被刷成不同颜色。
        """
        matched, mask_solid, quantized, region_id_map = two_red_stripes
        client, sid, store = _make_client(
            matched,
            mask_solid=mask_solid,
            quantized_image=quantized,
            region_id_map=region_id_map,
        )
        response = client.post(
            "/api/convert/region-replace-batch",
            json={
                "session_id": sid,
                "items": [
                    {
                        "replacement_color": "#00ff00",
                        "gradient_group_index": 1,
                        "gradient_region_index": 1,
                    },
                    {
                        "replacement_color": "#0000ff",
                        "gradient_group_index": 1,
                        "gradient_region_index": 2,
                    },
                ],
            },
        )
        assert response.status_code == 200, response.text
        updated = store.get(sid)["preview_cache"]["matched_rgb"]
        assert np.all(updated[:, 10:40] == (0, 255, 0)), "region 1 → green"
        assert np.all(updated[:, 60:90] == (0, 0, 255)), "region 2 → blue"
        outside = np.r_[0:10, 40:60, 90:100]
        assert np.all(updated[:, outside] == (255, 0, 0)), (
            "pixels outside any gradient region stay red"
        )
        np.testing.assert_array_equal(
            store.get(sid)["preview_cache"]["height_identity_rgb"], matched
        )

    def test_batch_preserves_gradient_region_id_map(
        self,
        two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    ) -> None:
        """region_id_map must survive the batch for further edits.
        region_id_map 在 batch 之后仍需保留，支持后续编辑。
        """
        matched, mask_solid, quantized, region_id_map = two_red_stripes
        client, sid, store = _make_client(
            matched,
            mask_solid=mask_solid,
            quantized_image=quantized,
            region_id_map=region_id_map,
        )
        client.post(
            "/api/convert/region-replace-batch",
            json={
                "session_id": sid,
                "items": [
                    {
                        "replacement_color": "#00ff00",
                        "gradient_group_index": 1,
                        "gradient_region_index": 1,
                    }
                ],
            },
        )
        assert store.get(sid).get("gradient_region_id_map") is not None

    def test_batch_click_and_gradient_mixed(
        self,
        two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    ) -> None:
        """Click-detected item and gradient item can coexist in one batch.
        一批里混合 click 与 gradient item 都能正常作用。
        """
        matched, mask_solid, quantized, region_id_map = two_red_stripes
        # Give the top-left a distinct colour so flood-fill from (5, 5)
        # picks up exactly that quadrant (not the whole canvas).
        # 在左上角打一块白，flood-fill 只会选这一块。
        matched[0:5, 0:5] = (200, 200, 200)
        quantized = matched.copy()
        client, sid, store = _make_client(
            matched,
            mask_solid=mask_solid,
            quantized_image=quantized,
            region_id_map=region_id_map,
        )
        response = client.post(
            "/api/convert/region-replace-batch",
            json={
                "session_id": sid,
                "items": [
                    {
                        "replacement_color": "#000000",
                        "click_x": 2,
                        "click_y": 2,
                    },
                    {
                        "replacement_color": "#00ff00",
                        "gradient_group_index": 1,
                        "gradient_region_index": 1,
                    },
                ],
            },
        )
        assert response.status_code == 200, response.text
        updated = store.get(sid)["preview_cache"]["matched_rgb"]
        assert np.all(updated[0:5, 0:5] == (0, 0, 0)), "click region → black"
        assert np.all(updated[:, 10:40] == (0, 255, 0)), "gradient region 1 → green"

    def test_batch_gradient_without_region_id_map_returns_409(
        self,
        two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    ) -> None:
        matched, mask_solid, quantized, _ = two_red_stripes
        client, sid, _ = _make_client(
            matched, mask_solid=mask_solid, quantized_image=quantized
        )
        response = client.post(
            "/api/convert/region-replace-batch",
            json={
                "session_id": sid,
                "items": [
                    {
                        "replacement_color": "#00ff00",
                        "gradient_group_index": 1,
                        "gradient_region_index": 1,
                    }
                ],
            },
        )
        assert response.status_code == 409
        # 409 文案已改为用户友好提示，不再暴露内部字段名。
        assert "Gradient region data is unavailable" in response.json()["detail"]

    def test_batch_unknown_gradient_region_returns_404(
        self,
        two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    ) -> None:
        matched, mask_solid, quantized, region_id_map = two_red_stripes
        client, sid, _ = _make_client(
            matched,
            mask_solid=mask_solid,
            quantized_image=quantized,
            region_id_map=region_id_map,
        )
        response = client.post(
            "/api/convert/region-replace-batch",
            json={
                "session_id": sid,
                "items": [
                    {
                        "replacement_color": "#00ff00",
                        "gradient_group_index": 9,
                        "gradient_region_index": 9,
                    }
                ],
            },
        )
        assert response.status_code == 404

    def test_batch_item_missing_mask_source_returns_400(
        self,
        two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    ) -> None:
        """No click coords, no gradient indices → 400.
        既没传 click 坐标也没传 gradient 索引，返回 400。
        """
        matched, mask_solid, quantized, _ = two_red_stripes
        client, sid, _ = _make_client(
            matched, mask_solid=mask_solid, quantized_image=quantized
        )
        response = client.post(
            "/api/convert/region-replace-batch",
            json={
                "session_id": sid,
                "items": [{"replacement_color": "#00ff00"}],
            },
        )
        assert response.status_code == 400

    def test_batch_group_only_covers_whole_group(
        self,
        two_red_stripes: tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray],
    ) -> None:
        """gradient_group_index alone flattens the entire group.
        只传 gradient_group_index（不传 region）= 整组 mask。
        """
        matched, mask_solid, quantized, region_id_map = two_red_stripes
        client, sid, store = _make_client(
            matched,
            mask_solid=mask_solid,
            quantized_image=quantized,
            region_id_map=region_id_map,
        )
        response = client.post(
            "/api/convert/region-replace-batch",
            json={
                "session_id": sid,
                "items": [
                    {
                        "replacement_color": "#00ff00",
                        "gradient_group_index": 1,
                    }
                ],
            },
        )
        assert response.status_code == 200, response.text
        updated = store.get(sid)["preview_cache"]["matched_rgb"]
        assert np.all(updated[:, 10:40] == (0, 255, 0)), "region 1 → green"
        assert np.all(updated[:, 60:90] == (0, 255, 0)), "region 2 → green"
        np.testing.assert_array_equal(
            store.get(sid)["preview_cache"]["height_identity_rgb"], matched
        )
