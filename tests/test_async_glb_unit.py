"""Regression tests for the async segmented-GLB build pipeline.

Covers / 覆盖范围:
    1. Replace endpoints return ``preview_glb_url = None`` immediately
       rather than synchronously waiting for ``generate_segmented_glb``.
       替换端点立即返回 ``preview_glb_url = None``，不再同步等 GLB。
    2. ``GET /api/convert/glb-status/{session_id}`` transitions from
       ``pending`` to ``ready`` after the worker thread finishes, and
       publishes the newly registered GLB URL in cache.
       ``glb-status`` 端点在后台线程完成后由 pending 切换到 ready，并把
       新注册的 GLB URL 从 cache 暴露给前端。
    3. Job-token guarding: a newer replace supersedes the in-flight job
       so the older thread's result is discarded and the status endpoint
       keeps reporting the newer token.
       job_token 守护：新任务覆盖未完成任务后，旧线程的结果被丢弃。
    4. Failure path: if ``generate_segmented_glb`` raises, ``status``
       becomes ``error`` and a safe public error text is surfaced.
       失败路径：后台抛错时状态切换为 ``error`` 并回传安全公开文案。

    The tests monkeypatch ``generate_segmented_glb`` so they can exercise
    the async scheduler deterministically without spending 30+ seconds on
    actual mesh building. A minimal LUT session is seeded directly into
    the SessionStore to keep each test independent of the full /preview
    pipeline.
    测试通过 monkeypatch 替换 ``generate_segmented_glb``，避免真实 GLB
    构建的 30+ 秒耗时，同时保持与调度器的契约一致。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Callable

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import (
    externalize_preview_cache,
    is_preview_cache_artifact_ref,
    merge_preview_cache_metadata,
    preview_cache_transaction,
    refresh_preview_cache_revision,
)
from api.routers.converter import async_glb as async_glb_module
from api.session_store import SessionStore
from config import ModelingMode
from core import vector_engine
from shapely.geometry import box

_test_store: SessionStore = SessionStore(ttl=1800)
_test_registry: FileRegistry = FileRegistry()
_GLB_STATUS_SAFE_ERROR = "3D preview could not be updated. Re-run preview and try again."


def setup_module(module) -> None:
    app.dependency_overrides[get_session_store] = lambda: _test_store
    app.dependency_overrides[get_file_registry] = lambda: _test_registry


def teardown_module(module) -> None:
    app.dependency_overrides.pop(get_session_store, None)
    app.dependency_overrides.pop(get_file_registry, None)


setup_module(None)
client: TestClient = TestClient(app)


def setup_function() -> None:
    global _test_store, _test_registry
    _test_store = SessionStore(ttl=1800)
    _test_registry = FileRegistry()


def _seed_session(tmp_path: Path) -> str:
    """Build a minimal LUT-backed session that region-replace can act on.

    Keeping the shape identical to the real pipeline's preview cache is
    what matters here — the actual LUT content is irrelevant because the
    GLB build is monkey-patched in every test.
    构造一个 region-replace 能处理的最小 LUT 会话；内容对 GLB 行为无关，
    因为每个用例都会 monkeypatch 真实的 mesh 构建。
    """

    lut_path = tmp_path / "simple_lut.npz"
    rgb = np.asarray(
        [[255, 0, 0], [0, 0, 255], [0, 255, 0]], dtype=np.uint8
    )
    stacks = np.asarray([[0, 0], [1, 1], [2, 2]], dtype=np.int16)
    np.savez(lut_path, rgb=rgb, stacks=stacks)

    sid = _test_store.create()
    matched = np.zeros((3, 3, 3), dtype=np.uint8)
    matched[:, :] = [255, 0, 0]
    material_matrix = np.zeros((3, 3, 2), dtype=np.int16)
    mask_solid = np.ones((3, 3), dtype=bool)
    cache = {
        "matched_rgb": matched.copy(),
        "quantized_image": matched.copy(),
        "mask_solid": mask_solid,
        "material_matrix": material_matrix.copy(),
        "color_conf": {
            "preview": {0: [255, 0, 0, 255], 1: [0, 0, 255, 255], 2: [0, 255, 0, 255]},
            "slots": ["Red", "Blue"],
        },
        "preview_rgba": np.dstack(
            [matched.copy(), np.full((3, 3), 255, dtype=np.uint8)]
        ),
        "color_layers": 2,
        "layer_height_mm": 0.08,
        "target_w": 3,
        "target_h": 3,
        "target_width_mm": 60.0,
    }
    _test_store.put(sid, "preview_cache", cache)
    _test_store.put(sid, "original_matched_rgb", matched.copy())
    _test_store.put(sid, "original_material_matrix", material_matrix.copy())
    _test_store.put(sid, "replacement_regions", [])
    _test_store.put(sid, "replacement_history", [])
    _test_store.put(sid, "lut_path", str(lut_path))
    _test_store.put(sid, "color_mode", "4-Color (RYBW)")
    _test_store.put(sid, "color_layers", 2)
    _test_store.put(sid, "layer_height_mm", 0.08)
    _test_store.put(sid, "material_source", "lut")
    return sid


def _convert_seeded_session_to_artifact(sid: str, tmp_path: Path) -> dict:
    session_data = _test_store.get(sid)
    assert session_data is not None
    cache = dict(session_data["preview_cache"])
    cache["original_matched_rgb"] = session_data["original_matched_rgb"]
    cache["original_material_matrix"] = session_data["original_material_matrix"]
    ref = externalize_preview_cache(
        sid,
        _test_store,
        cache,
        root_dir=tmp_path,
    )
    _test_store.put(sid, "preview_cache", ref)
    return ref


def _install_glb_stub(
    monkeypatch: pytest.MonkeyPatch,
    builder: Callable[[dict], str | None],
) -> list[str]:
    """Replace the real ``generate_segmented_glb`` with *builder*.

    Returns a list that records every call — tests can assert how many
    background builds actually ran (e.g. to check job-token cancellation).
    返回一个列表，记录 builder 被调用的次数与对应 job_token，便于测试断言。
    """

    calls: list[str] = []

    def _wrapper(cache: dict, *, output_path: str) -> str | None:
        # Production caller now passes ``output_path=`` after the A2
        # follow-up signature change; absorb it so every legacy
        # builder lambda continues to work unchanged.
        calls.append(cache.get("glb_job_token", ""))
        return builder(cache)

    monkeypatch.setattr(async_glb_module, "generate_segmented_glb", _wrapper)
    return calls


def _wait_for_status(
    sid: str, predicate: Callable[[dict], bool], timeout_s: float = 5.0
) -> dict:
    """Poll /glb-status until *predicate* accepts or *timeout_s* elapses.

    Chosen over a fixed sleep so the tests stay fast on CI (the stub
    builds finish in milliseconds) while still tolerating ThreadPool
    scheduler latency.
    轮询 glb-status 直到满足谓词或超时，保证测试稳定又快。
    """

    deadline = time.perf_counter() + timeout_s
    last: dict = {}
    while time.perf_counter() < deadline:
        resp = client.get(f"/api/convert/glb-status/{sid}")
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if predicate(last):
            return last
        time.sleep(0.02)
    raise AssertionError(
        f"glb-status predicate never matched within {timeout_s}s; last={last}"
    )


def _native_vector_cache(sid: str, tmp_path: Path) -> dict:
    session_data = _test_store.get(sid)
    assert session_data is not None
    cache = dict(session_data["preview_cache"])
    svg_path = tmp_path / "preview.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="3" height="3">'
        '<rect width="3" height="3" fill="#ff0000"/></svg>', encoding="utf-8",
    )
    geometry = box(0, 0, 3, 3)
    cache_key = vector_engine._vector_parse_clip_cache_key(
        str(svg_path), target_width_mm=60.0, sampling_precision=0.02,
        expand_stroke_to_fill=False, gradient_color_bands=None,
    )
    geometry_path = tmp_path / "vector-geometry.pkl"
    geometry_path.write_bytes(vector_engine._serialize_vector_parse_clip_cache(
        cache_key, {
            "shape_data": [{"poly": geometry, "color": (255, 0, 0)}],
            "clipped_shapes": [{"geometry": geometry, "color": (255, 0, 0)}],
            "silhouette": geometry,
            "image_vectorizer_bounds": geometry,
            "scale_factor": 20.0,
            "bbox": (0, 0, 3, 3),
        },
    ))
    _test_store.register_temp_file(sid, str(geometry_path))
    cache.update(
        {
            "modeling_mode": "vector",
            "enable_smooth_vector_preview": True,
            "vector_parse_clip_cache_path": str(geometry_path),
            "vector_parse_clip_cache_provenance": (
                vector_engine._vector_parse_clip_cache_provenance(cache_key)
            ),
            "height_identity_rgb": cache["matched_rgb"].copy(),
            "preview_colors": {0: [255, 255, 255, 255]},
            "backing_color_id": 0,
            "spacer_thick": 1.6,
        }
    )
    _test_store.put(sid, "preview_cache", cache)
    return cache


class TestRendererDispatch:
    @pytest.mark.parametrize("smooth", [False, True])
    def test_new_session_reuses_mesh_and_contours_after_first_session_closes(
        self, tmp_path: Path, smooth: bool,
    ) -> None:
        def render(name: str, width: float) -> tuple[dict, Path]:
            sid = _seed_session(tmp_path)
            cache = _native_vector_cache(sid, tmp_path)
            cache.update(enable_smooth_vector_preview=smooth, target_width_mm=width)
            target = tmp_path / f"{name}.glb"
            path, renderer = async_glb_module._build_preview_glb(
                session_id=sid, store=_test_store, cache=cache, output_path=str(target),
            )
            assert path == str(target)
            assert renderer == ("vector_analytic" if smooth else "segmented")
            _test_store.close(sid)
            return cache, target

        initial, first = render("first", 60)
        original = first.read_bytes()
        first.unlink()
        repeated, second = render("second", 60)
        assert repeated["_glb_reused"]
        assert second.read_bytes() == original
        assert repeated["color_contours"] == initial["color_contours"]
        assert repeated["color_contours"] is not initial["color_contours"]
        resized, _ = render("resized", 30)
        assert not resized["_glb_reused"]

    def test_material_layers_and_slot_colors_invalidate_unchanged_surface(self, tmp_path: Path) -> None:
        sid = _seed_session(tmp_path)
        cache = _test_store.get(sid)["preview_cache"]
        cache["material_source"] = "material_archive"
        cache["material_matrix"][:, :, 1] = 0

        def render(name: str) -> bytes:
            target = tmp_path / f"{name}.glb"
            path, _ = async_glb_module._build_preview_glb(
                session_id=sid, store=_test_store, cache=cache, output_path=str(target),
            )
            assert path and not cache["_glb_reused"]
            return target.read_bytes()

        original = render("initial")
        cache["material_matrix"][:, :, 1] = 1
        swapped = render("swapped")
        assert swapped != original
        cache["preview_colors"] = {1: [90, 200, 25, 255]}
        assert render("recolored") != swapped

    def test_real_session_artifact_reaches_analytic_glb(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sid = _seed_session(tmp_path)
        cache = _native_vector_cache(sid, tmp_path)
        monkeypatch.setattr(
            async_glb_module, "generate_segmented_glb",
            lambda *_args, **_kwargs: pytest.fail("valid artifact must reach analytic renderer"),
        )
        output = tmp_path / "real-analytic.glb"
        path, renderer = async_glb_module._build_preview_glb(
            session_id=sid, store=_test_store, cache=cache, output_path=str(output),
        )
        assert renderer == "vector_analytic"
        assert path == str(output)
        assert output.read_bytes()[:4] == b"glTF"

    @pytest.mark.parametrize("mismatch", ["provenance", "owner", "runtime"])
    def test_real_session_artifact_rejects_mismatched_reuse(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mismatch: str,
    ) -> None:
        sid = _seed_session(tmp_path)
        cache = _native_vector_cache(sid, tmp_path)
        if mismatch == "provenance":
            key = json.loads(cache["vector_parse_clip_cache_provenance"])
            key[1] += 1
            cache["vector_parse_clip_cache_provenance"] = (
                vector_engine._vector_parse_clip_cache_provenance(key)
            )
        elif mismatch == "owner":
            sid = _test_store.create()
        else:
            monkeypatch.setattr(
                vector_engine.native_svg_adapter, "native_build_identity",
                lambda: "different-build",
            )
        calls = []

        def segmented(_cache, *, output_path):
            calls.append(output_path)
            return output_path

        monkeypatch.setattr(async_glb_module, "generate_segmented_glb", segmented)
        output = tmp_path / "fallback.glb"
        path, renderer = async_glb_module._build_preview_glb(
            session_id=sid, store=_test_store, cache=cache, output_path=str(output),
        )
        assert renderer == "segmented"
        assert path == str(output)
        assert calls == [str(output)]

    @pytest.mark.parametrize("modeling_mode", ["vector", ModelingMode.VECTOR])
    def test_native_vector_prefers_analytic_renderer(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        modeling_mode: str | ModelingMode,
    ) -> None:
        sid = _seed_session(tmp_path)
        cache = _native_vector_cache(sid, tmp_path)
        cache["modeling_mode"] = modeling_mode
        calls: list[str] = []

        monkeypatch.setattr(
            async_glb_module,
            "build_vector_quick_preview_parts",
            lambda **_kwargs: [object()],
        )

        def export(_parts: list[object], *, output_path: str) -> str:
            calls.append("analytic")
            Path(output_path).write_bytes(b"analytic")
            return output_path

        monkeypatch.setattr(
            async_glb_module,
            "export_vector_quick_preview_glb",
            export,
        )
        monkeypatch.setattr(
            async_glb_module,
            "generate_segmented_glb",
            lambda *_args, **_kwargs: pytest.fail("segmented renderer should not run"),
        )

        output_path = tmp_path / "analytic.glb"
        result, renderer = async_glb_module._build_preview_glb(
            session_id=sid,
            store=_test_store,
            cache=cache,
            output_path=str(output_path),
        )

        assert result == str(output_path)
        assert renderer == "vector_analytic"
        assert calls == ["analytic"]

    def test_analytic_renderer_publishes_canvas_color_contours(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sid = _seed_session(tmp_path)
        cache = _native_vector_cache(sid, tmp_path)
        matched = np.zeros((20, 20, 3), dtype=np.uint8)
        matched[10:20, 4:16] = [0, 0, 255]
        mask_solid = np.zeros((20, 20), dtype=bool)
        mask_solid[10:20, 4:16] = True
        cache.update(
            {
                "matched_rgb": matched,
                "mask_solid": mask_solid,
                "target_width_mm": 20.0,
                "color_contours": {"stale": [[[0.0, 0.0]]]},
            }
        )
        monkeypatch.setattr(
            async_glb_module,
            "build_vector_quick_preview_parts",
            lambda **_kwargs: [object()],
        )

        def export(_parts: list[object], *, output_path: str) -> str:
            Path(output_path).write_bytes(b"analytic")
            return output_path

        monkeypatch.setattr(async_glb_module, "export_vector_quick_preview_glb", export)

        _result, renderer = async_glb_module._build_preview_glb(
            session_id=sid,
            store=_test_store,
            cache=cache,
            output_path=str(tmp_path / "analytic.glb"),
        )

        assert renderer == "vector_analytic"
        assert set(cache["color_contours"]) == {"0000ff"}
        points = np.array(cache["color_contours"]["0000ff"][0])
        # 1 mm per pixel with a bottom-left canvas origin: the blue block
        # occupies canvas Y 0..10 mm and never reaches the canvas top.
        assert points[:, 1].max() == pytest.approx(10.0)
        assert points[:, 0].min() == pytest.approx(4.0)

    @pytest.mark.parametrize(
        ("cache_update", "register_geometry"),
        [
            ({"enable_smooth_vector_preview": False}, True),
            ({"modeling_mode": "high-fidelity"}, True),
            ({}, False),
        ],
    )
    def test_renderer_falls_back_to_segmented_when_ineligible_or_stale(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        cache_update: dict,
        register_geometry: bool,
    ) -> None:
        sid = _seed_session(tmp_path)
        cache = _native_vector_cache(sid, tmp_path)
        cache.update(cache_update)
        if not register_geometry:
            foreign_path = tmp_path / "foreign-vector-geometry.pkl"
            foreign_path.write_bytes(b"not-session-owned")
            cache["vector_parse_clip_cache_path"] = str(foreign_path)
        _test_store.put(sid, "preview_cache", cache)
        calls: list[str] = []

        monkeypatch.setattr(
            async_glb_module,
            "load_vector_quick_preview_source",
            lambda *_args, **_kwargs: pytest.fail(
                "unowned or ineligible Vector source must not be loaded"
            ),
        )

        def segmented(_cache: dict, *, output_path: str) -> str:
            calls.append("segmented")
            Path(output_path).write_bytes(b"segmented")
            return output_path

        monkeypatch.setattr(async_glb_module, "generate_segmented_glb", segmented)

        output_path = tmp_path / "segmented.glb"
        result, renderer = async_glb_module._build_preview_glb(
            session_id=sid,
            store=_test_store,
            cache=cache,
            output_path=str(output_path),
        )

        assert result == str(output_path)
        assert renderer == "segmented"
        assert calls == ["segmented"]

    def test_valid_owned_source_with_invalid_payload_falls_back(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sid = _seed_session(tmp_path)
        cache = _native_vector_cache(sid, tmp_path)
        monkeypatch.setattr(
            async_glb_module,
            "load_vector_quick_preview_source",
            lambda *_args, **_kwargs: None,
        )

        def segmented(_cache: dict, *, output_path: str) -> str:
            Path(output_path).write_bytes(b"segmented")
            return output_path

        monkeypatch.setattr(async_glb_module, "generate_segmented_glb", segmented)

        result, renderer = async_glb_module._build_preview_glb(
            session_id=sid,
            store=_test_store,
            cache=cache,
            output_path=str(tmp_path / "fallback.glb"),
        )

        assert result is not None
        assert renderer == "segmented"

    def test_analytic_geometry_error_falls_back_without_stuck_pending_status(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        sid = _seed_session(tmp_path)
        cache = _native_vector_cache(sid, tmp_path)
        monkeypatch.setattr(
            async_glb_module,
            "build_vector_quick_preview_parts",
            lambda **_kwargs: [object()],
        )
        monkeypatch.setattr(
            async_glb_module,
            "export_vector_quick_preview_glb",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                ValueError("preview geometry rejected")
            ),
        )

        def segmented(_cache: dict, *, output_path: str) -> str:
            Path(output_path).write_bytes(b"segmented")
            return output_path

        monkeypatch.setattr(async_glb_module, "generate_segmented_glb", segmented)

        result, renderer = async_glb_module._build_preview_glb(
            session_id=sid,
            store=_test_store,
            cache=cache,
            output_path=str(tmp_path / "fallback.glb"),
        )

        assert result is not None
        assert renderer == "segmented"

    def test_segmented_filenames_are_immutable_per_job(self) -> None:
        first = async_glb_module.generate_segmented_glb_filename("same-session")
        second = async_glb_module.generate_segmented_glb_filename("same-session")

        assert first != second


class TestRendererRebuildEndpoint:
    @pytest.mark.parametrize("modeling_mode", ["vector", ModelingMode.VECTOR])
    def test_updates_renderer_only_and_schedules_same_session(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        modeling_mode: str | ModelingMode,
    ) -> None:
        sid = _seed_session(tmp_path)
        before = _native_vector_cache(sid, tmp_path)
        before["modeling_mode"] = modeling_mode
        _test_store.put(sid, "preview_cache", before)
        original_matched = before["matched_rgb"]
        scheduled: list[tuple[str, dict, dict[str, object]]] = []

        def schedule(
            session_id: str,
            _store: SessionStore,
            _registry: FileRegistry,
            cache: dict,
            *,
            metadata_updates: dict[str, object] | None = None,
        ) -> str:
            updates = dict(metadata_updates or {})
            scheduled.append((session_id, cache, updates))
            _store.put(
                session_id,
                "preview_cache",
                async_glb_module._with_cache_metadata(cache, updates),
            )
            return "renderer-job-token"

        monkeypatch.setattr(
            "api.routers.converter.preview.schedule_glb_build",
            schedule,
        )

        response = client.post(
            "/api/convert/vector-preview-renderer",
            json={
                "session_id": sid,
                "enable_smooth_vector_preview": False,
            },
        )

        assert response.status_code == 200, response.text
        assert response.json() == {
            "session_id": sid,
            "status": "pending",
            "job_token": "renderer-job-token",
            "glb_url": None,
            "renderer": "segmented",
        }
        assert scheduled and scheduled[0][0] == sid
        assert scheduled[0][2] == {
            "enable_smooth_vector_preview": False,
            "vector_preview_renderer": "segmented",
        }
        after = _test_store.get(sid)["preview_cache"]
        assert after["enable_smooth_vector_preview"] is False
        assert after["vector_preview_renderer"] == "segmented"
        assert after["matched_rgb"] is original_matched
        for key in before:
            if key not in {
                "enable_smooth_vector_preview",
                "vector_preview_renderer",
            }:
                assert after[key] is before[key]

    def test_rejects_missing_closed_and_non_vector_sessions(
        self,
        tmp_path: Path,
    ) -> None:
        missing = client.post(
            "/api/convert/vector-preview-renderer",
            json={
                "session_id": "missing-session",
                "enable_smooth_vector_preview": True,
            },
        )
        assert missing.status_code == 404

        closed_sid = _seed_session(tmp_path)
        _test_store.close(closed_sid)
        closed = client.post(
            "/api/convert/vector-preview-renderer",
            json={
                "session_id": closed_sid,
                "enable_smooth_vector_preview": True,
            },
        )
        assert closed.status_code == 404

        raster_sid = _seed_session(tmp_path)
        raster = client.post(
            "/api/convert/vector-preview-renderer",
            json={
                "session_id": raster_sid,
                "enable_smooth_vector_preview": True,
            },
        )
        assert raster.status_code == 409


class TestReplaceReturnsImmediately:
    def test_region_replace_returns_glb_url_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = _seed_session(tmp_path)
        # Pin the stub so we can observe status transitions without waiting
        # for real mesh construction.
        # 使用 stub 避免真实 GLB 构建的耗时。
        stub_glb_path = tmp_path / "fake.glb"
        stub_glb_path.write_bytes(b"glb-placeholder")
        _install_glb_stub(monkeypatch, lambda _c: str(stub_glb_path))

        # Seed a connected region so /region-replace has something to act on.
        # 种入一个连通区域 mask，让 region-replace 有目标。
        region_mask = np.zeros((3, 3), dtype=bool)
        region_mask[:2, :2] = True
        _test_store.put(sid, "selected_region_mask", region_mask)
        _test_store.put(sid, "selected_region_id", "region-a")

        response = client.post(
            "/api/convert/region-replace",
            json={"session_id": sid, "replacement_color": "#0000ff"},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["preview_glb_url"] is None
        assert body["preview_url"]

    def test_replace_color_returns_glb_url_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = _seed_session(tmp_path)
        stub_glb_path = tmp_path / "fake.glb"
        stub_glb_path.write_bytes(b"glb-placeholder")
        _install_glb_stub(monkeypatch, lambda _c: str(stub_glb_path))

        response = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#ff0000",
                "replacement_color": "#0000ff",
            },
        )
        assert response.status_code == 200, response.text
        assert response.json().get("preview_glb_url") is None


class TestGlbStatusLifecycle:
    def test_idle_before_any_replace(self, tmp_path: Path) -> None:
        sid = _seed_session(tmp_path)
        resp = client.get(f"/api/convert/glb-status/{sid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "idle"
        assert body["glb_url"] is None
        assert body["job_token"] is None

    def test_unknown_session_returns_404(self) -> None:
        resp = client.get("/api/convert/glb-status/not-a-session")
        assert resp.status_code == 404

    def test_pending_then_ready_after_replace(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = _seed_session(tmp_path)
        stub_glb_path = tmp_path / "fake.glb"
        stub_glb_path.write_bytes(b"glb-placeholder")

        # A slow-ish stub ensures we can observe a pending snapshot
        # between scheduling and completion without racing.
        # 让 stub 延迟一点，确保 pending 状态能被观察到（否则太快直接 ready）。
        def slow_builder(cache: dict) -> str:
            time.sleep(0.05)
            cache["color_contours"] = {
                "#ff0000": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]]
            }
            return str(stub_glb_path)

        _install_glb_stub(monkeypatch, slow_builder)

        resp = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#ff0000",
                "replacement_color": "#0000ff",
            },
        )
        assert resp.status_code == 200

        final = _wait_for_status(sid, lambda b: b["status"] == "ready")
        assert isinstance(final["glb_url"], str)
        assert final["glb_url"].startswith("/api/files/")
        assert isinstance(final["job_token"], str)
        assert final["error"] is None
        assert final["color_contours"] == {
            "#ff0000": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]]
        }

    def test_worker_exception_status_uses_safe_public_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        sid = _seed_session(tmp_path)
        private_path = "/Users/min/private/async-preview.glb"

        def broken(_cache: dict) -> str | None:
            raise OSError(f"cannot write {private_path}: permission denied")

        _install_glb_stub(monkeypatch, broken)
        target_logger = logging.getLogger("lumina.api.routers.converter.async_glb")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)

        try:
            resp = client.post(
                "/api/convert/replace-color",
                json={
                    "session_id": sid,
                    "selected_color": "#ff0000",
                    "replacement_color": "#0000ff",
                },
            )
            assert resp.status_code == 200

            final = _wait_for_status(sid, lambda b: b["status"] == "error")
            assert final["glb_url"] is None
            assert final["error"] == _GLB_STATUS_SAFE_ERROR
            assert private_path not in final["error"]
            assert "OSError" not in final["error"]
            assert "permission denied" not in final["error"]

            failure_records = [
                record
                for record in caplog.records
                if getattr(record, "event", "") == "converter_glb_build_failed"
            ]
            assert failure_records
            assert getattr(failure_records[-1], "error_type", "") == "OSError"
            assert private_path in getattr(failure_records[-1], "error_message", "")
        finally:
            target_logger.removeHandler(caplog.handler)

    def test_registration_failure_cleans_unregistered_glb(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A registry failure must not leave the generated GLB unowned."""
        sid = _seed_session(tmp_path)
        job_token = "job-token"
        _test_store.put(
            sid,
            "preview_cache",
            {
                **_test_store.get(sid)["preview_cache"],
                "glb_job_token": job_token,
                "glb_url": None,
                "glb_error": None,
            },
        )
        glb_path = tmp_path / "unregistered.glb"

        def builder(_cache: dict, *, output_path: str) -> str:
            glb_path.write_bytes(b"unregistered-glb")
            return str(glb_path)

        class FailingRegistry:
            def register_path(self, *_args: object, **_kwargs: object) -> str:
                raise RuntimeError("forced registry failure")

        monkeypatch.setattr(async_glb_module, "generate_segmented_glb", builder)
        async_glb_module._run_glb_build_job(
            sid,
            job_token,
            _test_store,
            FailingRegistry(),
        )

        status = async_glb_module.get_glb_status(
            _test_store.get(sid)["preview_cache"]
        )
        assert status["status"] == "error"
        assert status["glb_url"] is None
        assert status["error"] == _GLB_STATUS_SAFE_ERROR
        assert "forced registry failure" not in status["error"]
        assert not glb_path.exists()

    def test_session_closed_during_registration_cleans_registered_glb(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A close racing with registration must not leave an orphaned GLB."""
        sid = _seed_session(tmp_path)
        job_token = "job-token"
        _test_store.put(
            sid,
            "preview_cache",
            {
                **_test_store.get(sid)["preview_cache"],
                "glb_job_token": job_token,
                "glb_url": None,
                "glb_error": None,
            },
        )
        glb_path = tmp_path / "closed-during-registration.glb"

        def builder(_cache: dict, *, output_path: str) -> str:
            del output_path
            glb_path.write_bytes(b"registered-then-closed")
            return str(glb_path)

        class ClosingRegistry(FileRegistry):
            registered_file_id: str | None = None

            def register_path(self, *args: object, **kwargs: object) -> str:
                file_id = super().register_path(*args, **kwargs)
                self.registered_file_id = file_id
                _test_store.close(sid)
                return file_id

        registry = ClosingRegistry()
        monkeypatch.setattr(async_glb_module, "generate_segmented_glb", builder)

        async_glb_module._run_glb_build_job(
            sid,
            job_token,
            _test_store,
            registry,
        )

        assert _test_store.get(sid) is None
        assert registry.registered_file_id is not None
        assert registry.get_entry(registry.registered_file_id) is None
        assert not glb_path.exists()

    def test_job_superseded_during_registration_cleans_registered_glb(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A newer token racing with registration must keep the newer job pending."""
        sid = _seed_session(tmp_path)
        old_token = "old-token"
        new_token = "new-token"
        _test_store.put(
            sid,
            "preview_cache",
            {
                **_test_store.get(sid)["preview_cache"],
                "glb_job_token": old_token,
                "glb_url": None,
                "glb_error": None,
            },
        )
        glb_path = tmp_path / "superseded-during-registration.glb"

        def builder(_cache: dict, *, output_path: str) -> str:
            del output_path
            glb_path.write_bytes(b"registered-then-superseded")
            return str(glb_path)

        class SupersedingRegistry(FileRegistry):
            registered_file_id: str | None = None

            def register_path(self, *args: object, **kwargs: object) -> str:
                file_id = super().register_path(*args, **kwargs)
                self.registered_file_id = file_id
                _test_store.put(
                    sid,
                    "preview_cache",
                    {
                        "glb_job_token": new_token,
                        "glb_url": None,
                        "glb_error": None,
                    },
                )
                return file_id

        registry = SupersedingRegistry()
        monkeypatch.setattr(async_glb_module, "generate_segmented_glb", builder)

        async_glb_module._run_glb_build_job(
            sid,
            old_token,
            _test_store,
            registry,
        )

        status = async_glb_module.get_glb_status(
            _test_store.get(sid)["preview_cache"]
        )
        assert status["status"] == "pending"
        assert status["job_token"] == new_token
        assert registry.registered_file_id is not None
        assert registry.get_entry(registry.registered_file_id) is None
        assert not glb_path.exists()

    def test_job_superseded_during_final_publish_cannot_overwrite_newer_job(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Publishing the completed cache must compare-and-set the job token."""
        sid = _seed_session(tmp_path)
        old_token = "old-token"
        new_token = "new-token"
        _test_store.put(
            sid,
            "preview_cache",
            {
                **_test_store.get(sid)["preview_cache"],
                "glb_job_token": old_token,
                "glb_url": None,
                "glb_error": None,
            },
        )
        glb_path = tmp_path / "superseded-during-publish.glb"
        glb_path.write_bytes(b"stale-glb")
        monkeypatch.setattr(
            async_glb_module,
            "_build_preview_glb",
            lambda **_kwargs: (str(glb_path), "segmented"),
        )
        original_with_metadata = async_glb_module._with_cache_metadata

        def supersede_before_publish(cache: dict, metadata: dict) -> dict:
            if "glb_completed_at" in metadata:
                _test_store.put(
                    sid,
                    "preview_cache",
                    {
                        "glb_job_token": new_token,
                        "glb_url": None,
                        "glb_error": None,
                    },
                )
            return original_with_metadata(cache, metadata)

        monkeypatch.setattr(
            async_glb_module,
            "_with_cache_metadata",
            supersede_before_publish,
        )

        async_glb_module._run_glb_build_job(
            sid,
            old_token,
            _test_store,
            _test_registry,
        )

        final_cache = _test_store.get(sid)["preview_cache"]
        assert final_cache["glb_job_token"] == new_token
        assert final_cache["glb_url"] is None
        assert _test_registry.get_session_entries(sid) == {}
        assert not glb_path.exists()

    @pytest.mark.parametrize("artifact_backed", [False, True])
    def test_cache_mutation_before_new_job_token_blocks_stale_publication(
        self,
        artifact_backed: bool,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A committed edit must invalidate the old worker before rescheduling."""
        sid = _seed_session(tmp_path)
        old_token = "old-token"
        cache = _test_store.get(sid)["preview_cache"]
        if artifact_backed:
            cache = _convert_seeded_session_to_artifact(sid, tmp_path)
        scheduled_cache = async_glb_module._with_cache_metadata(
            cache,
            {
                "glb_job_token": old_token,
                "glb_url": None,
                "glb_error": None,
            },
        )
        _test_store.put(sid, "preview_cache", scheduled_cache)
        glb_path = tmp_path / f"stale-{'artifact' if artifact_backed else 'plain'}.glb"
        glb_path.write_bytes(b"stale-glb")
        monkeypatch.setattr(
            async_glb_module,
            "_build_preview_glb",
            lambda **_kwargs: (str(glb_path), "segmented"),
        )
        original_with_metadata = async_glb_module._with_cache_metadata
        replacement_rgb = np.full((3, 3, 3), 37, dtype=np.uint8)

        def commit_edit_before_publish(cache_value: dict, metadata: dict) -> dict:
            completed = original_with_metadata(cache_value, metadata)
            if "glb_completed_at" in metadata:
                session_data = _test_store.get(sid)
                assert session_data is not None
                with preview_cache_transaction(
                    sid,
                    _test_store,
                    session_data,
                    fields={"matched_rgb"},
                ) as transaction:
                    transaction["matched_rgb"] = replacement_rgb
                    transaction.commit({"matched_rgb"})
            return completed

        monkeypatch.setattr(
            async_glb_module,
            "_with_cache_metadata",
            commit_edit_before_publish,
        )

        async_glb_module._run_glb_build_job(
            sid,
            old_token,
            _test_store,
            _test_registry,
        )

        latest_cache = _test_store.get(sid)["preview_cache"]
        if artifact_backed:
            stored_rgb = np.load(latest_cache["fields"]["matched_rgb"]["path"])
        else:
            stored_rgb = latest_cache["matched_rgb"]
        np.testing.assert_array_equal(stored_rgb, replacement_rgb)
        assert latest_cache.get("metadata", latest_cache)["glb_url"] is None
        assert _test_registry.get_session_entries(sid) == {}
        assert not glb_path.exists()

    def test_final_publish_exception_cleans_registered_glb(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A transient store failure must not orphan a registered GLB."""

        class FailFirstCompareAndSetStore(SessionStore):
            compare_and_set_calls = 0

            def compare_and_set(self, *args: object, **kwargs: object) -> bool:
                self.compare_and_set_calls += 1
                if self.compare_and_set_calls == 1:
                    raise RuntimeError("forced publication failure")
                return super().compare_and_set(*args, **kwargs)

        store = FailFirstCompareAndSetStore(ttl=1800)
        sid = store.create()
        job_token = "job-token"
        store.put(
            sid,
            "preview_cache",
            {
                "glb_job_token": job_token,
                "glb_url": None,
                "glb_error": None,
                "matched_rgb": np.full((2, 2, 3), 255, dtype=np.uint8),
            },
        )
        glb_path = tmp_path / "registered-before-publish-error.glb"
        glb_path.write_bytes(b"unpublished-glb")
        registry = FileRegistry()
        monkeypatch.setattr(
            async_glb_module,
            "_build_preview_glb",
            lambda **_kwargs: (str(glb_path), "segmented"),
        )

        async_glb_module._run_glb_build_job(
            sid,
            job_token,
            store,
            registry,
        )

        assert store.compare_and_set_calls == 2
        status = async_glb_module.get_glb_status(
            store.get(sid)["preview_cache"]
        )
        assert status["status"] == "error"
        assert status["glb_url"] is None
        assert registry.get_session_entries(sid) == {}
        assert not glb_path.exists()

    def test_missing_glb_output_uses_safe_status_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A worker that returns no GLB path must not expose helper names."""
        sid = _seed_session(tmp_path)
        job_token = "job-token"
        _test_store.put(
            sid,
            "preview_cache",
            {
                **_test_store.get(sid)["preview_cache"],
                "glb_job_token": job_token,
                "glb_url": None,
                "glb_error": None,
            },
        )

        def builder(_cache: dict, *, output_path: str) -> None:
            return None

        monkeypatch.setattr(async_glb_module, "generate_segmented_glb", builder)
        async_glb_module._run_glb_build_job(
            sid,
            job_token,
            _test_store,
            _test_registry,
        )

        status = async_glb_module.get_glb_status(
            _test_store.get(sid)["preview_cache"]
        )
        assert status["status"] == "error"
        assert status["glb_url"] is None
        assert status["error"] == _GLB_STATUS_SAFE_ERROR
        assert "generate_segmented_glb" not in status["error"]

    def test_completion_log_separates_queue_execution_and_stage_timings(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        sid = _seed_session(tmp_path)
        job_token = "timed-job"
        _test_store.put(
            sid,
            "preview_cache",
            {
                **_test_store.get(sid)["preview_cache"],
                "glb_job_token": job_token,
                "glb_url": None,
                "glb_error": None,
            },
        )
        glb_path = tmp_path / "timed.glb"

        def builder(cache: dict, *, output_path: str) -> str:
            del output_path
            glb_path.write_bytes(b"timed-glb")
            cache["_segmented_glb_timings"] = {
                "mesh_loop_s": 1.25,
                "export_s": 0.5,
                "total_s": 1.75,
            }
            return str(glb_path)

        monkeypatch.setattr(async_glb_module, "generate_segmented_glb", builder)
        perf_values = iter([10.0, 12.0])
        monkeypatch.setattr(
            async_glb_module.time,
            "perf_counter",
            lambda: next(perf_values),
        )
        target_logger = logging.getLogger("lumina.api.routers.converter.async_glb")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.INFO, logger=target_logger.name)
        try:
            async_glb_module._run_glb_build_job(
                sid,
                job_token,
                _test_store,
                _test_registry,
                scheduled_perf_counter=9.0,
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_glb_completed"
        ]
        assert len(records) == 1
        record = records[0]
        assert record.queue_wait_ms == 1000.0
        assert record.execution_ms == 2000.0
        assert record.segmented_glb_timings == {
            "mesh_loop_s": 1.25,
            "export_s": 0.5,
            "total_s": 1.75,
        }
        assert str(glb_path) not in record.getMessage()

    def test_superseded_job_cleans_abandoned_glb(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A stale async job must delete its generated GLB before returning."""
        sid = _seed_session(tmp_path)
        old_token = "old-token"
        new_token = "new-token"
        _test_store.put(
            sid,
            "preview_cache",
            {
                **_test_store.get(sid)["preview_cache"],
                "glb_job_token": old_token,
                "glb_url": None,
                "glb_error": None,
            },
        )
        glb_path = tmp_path / "superseded.glb"

        def builder(_cache: dict, *, output_path: str) -> str:
            glb_path.write_bytes(b"superseded-glb")
            _test_store.put(
                sid,
                "preview_cache",
                {"glb_job_token": new_token, "glb_url": None, "glb_error": None},
            )
            return str(glb_path)

        monkeypatch.setattr(async_glb_module, "generate_segmented_glb", builder)
        async_glb_module._run_glb_build_job(
            sid,
            old_token,
            _test_store,
            _test_registry,
        )

        status = async_glb_module.get_glb_status(
            _test_store.get(sid)["preview_cache"]
        )
        assert status["status"] == "pending"
        assert status["job_token"] == new_token
        assert status["glb_url"] is None
        assert status["error"] is None
        assert not glb_path.exists()

    def test_artifact_cache_schedule_and_worker_store_glb_metadata(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = _seed_session(tmp_path)
        ref = _convert_seeded_session_to_artifact(sid, tmp_path)
        matched_path = ref["fields"]["matched_rgb"]["path"]
        submitted: list[tuple] = []

        class FakeExecutor:
            def submit(self, *args: object) -> None:
                submitted.append(args)

        monkeypatch.setattr(async_glb_module, "_GLB_EXECUTOR", FakeExecutor())
        job_token = async_glb_module.schedule_glb_build(
            sid,
            _test_store,
            _test_registry,
            ref,
        )

        scheduled_ref = _test_store.get(sid)["preview_cache"]
        assert is_preview_cache_artifact_ref(scheduled_ref)
        assert scheduled_ref["fields"]["matched_rgb"]["path"] == matched_path
        assert scheduled_ref["metadata"]["glb_job_token"] == job_token
        assert async_glb_module.get_glb_status(scheduled_ref)["status"] == "pending"
        assert submitted

        stub_glb_path = tmp_path / "artifact.glb"
        stub_glb_path.write_bytes(b"artifact-glb")

        def builder(cache: dict, *, output_path: str) -> str:
            assert isinstance(cache["matched_rgb"], np.ndarray)
            assert isinstance(cache["material_matrix"], np.ndarray)
            cache["color_contours"] = {"#ff0000": [[[0.0, 0.0], [1.0, 1.0]]]}
            return str(stub_glb_path)

        monkeypatch.setattr(async_glb_module, "generate_segmented_glb", builder)
        async_glb_module._run_glb_build_job(
            sid,
            job_token,
            _test_store,
            _test_registry,
        )

        completed_ref = _test_store.get(sid)["preview_cache"]
        assert is_preview_cache_artifact_ref(completed_ref)
        assert completed_ref["fields"]["matched_rgb"]["path"] == matched_path
        status = async_glb_module.get_glb_status(completed_ref)
        assert status["status"] == "ready"
        assert status["glb_url"].startswith("/api/files/")
        assert completed_ref["metadata"]["color_contours"] == {
            "#ff0000": [[[0.0, 0.0], [1.0, 1.0]]]
        }

    def test_executor_failure_marks_only_derived_glb_as_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A scheduler failure preserves the committed 2D cache state."""

        sid = _seed_session(tmp_path)
        current_cache = refresh_preview_cache_revision(
            _test_store.get(sid)["preview_cache"]
        )
        _test_store.put(sid, "preview_cache", current_cache)
        original_rgb = current_cache["matched_rgb"].copy()

        class FailingExecutor:
            def submit(self, *args: object) -> None:
                raise RuntimeError("executor unavailable")

        monkeypatch.setattr(async_glb_module, "_GLB_EXECUTOR", FailingExecutor())
        job_token = async_glb_module.schedule_glb_build(
            sid,
            _test_store,
            _test_registry,
            current_cache,
        )

        cache = _test_store.get(sid)["preview_cache"]
        status = async_glb_module.get_glb_status(cache)
        assert status["status"] == "error"
        assert status["job_token"] == job_token
        assert status["error"] == _GLB_STATUS_SAFE_ERROR
        np.testing.assert_array_equal(cache["matched_rgb"], original_rgb)

    @pytest.mark.parametrize("artifact_backed", [False, True])
    def test_stale_scheduler_claims_latest_cache_without_restoring_old_content(
        self,
        artifact_backed: bool,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Late scheduling from edit A must not overwrite newer edit B."""
        sid = _seed_session(tmp_path)
        base_cache = _test_store.get(sid)["preview_cache"]
        if artifact_backed:
            old_cache = externalize_preview_cache(
                sid,
                _test_store,
                {**base_cache, "content_marker": "old"},
                root_dir=tmp_path,
            )
            current_cache = merge_preview_cache_metadata(
                old_cache,
                {"content_marker": "new"},
            )
        else:
            old_cache = refresh_preview_cache_revision(
                {**base_cache, "content_marker": "old"}
            )
            current_cache = refresh_preview_cache_revision(
                {**base_cache, "content_marker": "new"}
            )
        _test_store.put(sid, "preview_cache", current_cache)
        submitted: list[tuple[object, ...]] = []

        class FakeExecutor:
            def submit(self, *args: object) -> None:
                submitted.append(args)

        monkeypatch.setattr(async_glb_module, "_GLB_EXECUTOR", FakeExecutor())

        job_token = async_glb_module.schedule_glb_build(
            sid,
            _test_store,
            _test_registry,
            old_cache,
            metadata_updates={"requested_renderer": "vector_analytic"},
        )

        scheduled_cache = _test_store.get(sid)["preview_cache"]
        scheduled_state = (
            scheduled_cache["metadata"]
            if artifact_backed
            else scheduled_cache
        )
        assert scheduled_state["content_marker"] == "new"
        assert scheduled_state["requested_renderer"] == "vector_analytic"
        assert scheduled_state["glb_job_token"] == job_token
        assert len(submitted) == 1
        assert submitted[0][2] == job_token

    def test_artifact_cache_hydration_failure_returns_safe_status_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sid = _seed_session(tmp_path)
        ref = _convert_seeded_session_to_artifact(sid, tmp_path)
        job_token = "job-token"
        ref["metadata"]["glb_job_token"] = job_token
        ref["metadata"]["glb_url"] = None
        ref["metadata"]["glb_error"] = None
        stale_path = ref["fields"]["matched_rgb"]["path"]
        os.remove(stale_path)
        _test_store.put(sid, "preview_cache", ref)

        calls: list[dict] = []

        def builder(cache: dict, *, output_path: str) -> str:
            calls.append(cache)
            return output_path

        monkeypatch.setattr(async_glb_module, "generate_segmented_glb", builder)
        async_glb_module._run_glb_build_job(
            sid,
            job_token,
            _test_store,
            _test_registry,
        )

        response = client.get(f"/api/convert/glb-status/{sid}")
        assert response.status_code == 200
        status = response.json()
        assert status["status"] == "error"
        assert status["glb_url"] is None
        assert "3D preview cache is unavailable" in status["error"]
        assert "Re-run preview" in status["error"]
        assert "FileNotFoundError" not in status["error"]
        assert stale_path not in status["error"]
        assert calls == []

    def test_session_close_removes_active_glb_and_vector_geometry(
        self,
        tmp_path: Path,
    ) -> None:
        """Both lightweight display artifacts remain session-bound."""

        sid = _seed_session(tmp_path)
        cache = _native_vector_cache(sid, tmp_path)
        geometry_path = Path(cache["vector_parse_clip_cache_path"])
        glb_file_id = _test_registry.register_bytes(
            sid,
            b"active-vector-preview",
            "active-vector-preview.glb",
        )
        glb_entry = _test_registry.get_entry(glb_file_id)
        assert glb_entry is not None
        glb_path = Path(glb_entry["path"])
        cache["glb_url"] = f"/api/files/{glb_file_id}"
        _test_store.put(sid, "preview_cache", cache)

        response = client.post(
            "/api/session/close",
            json={"session_id": sid},
        )

        assert response.status_code == 200, response.text
        assert _test_store.get(sid) is None
        assert _test_registry.resolve(glb_file_id) is None
        assert not glb_path.exists()
        assert not geometry_path.exists()


class TestJobTokenGuard:
    def test_newer_job_discards_older_result(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A newer replace while an old build is still running must win.

        We observe this indirectly: the status payload after both
        responses has ``job_token`` equal to the newest task's token, and
        its ``glb_url`` is the one produced by the *second* builder call
        (we give each call a distinct output path so the URLs differ).
        验证：旧任务仍在跑时来了新任务，最终 job_token 为新任务的，且
        glb_url 对应第二次 builder 的输出（用不同路径区分）。
        """

        sid = _seed_session(tmp_path)
        first_path = tmp_path / "first.glb"
        first_path.write_bytes(b"first-glb")
        second_path = tmp_path / "second.glb"
        second_path.write_bytes(b"second-glb")

        # Order the outputs strictly: first call returns first_path, second
        # returns second_path. A small sleep in the first call lets the
        # second request arrive before the first finishes.
        # 让两个 builder 的输出可区分，第一次故意慢，第二次在其完成前发起。
        call_index = {"i": 0}

        def sequencer(_cache: dict) -> str:
            call_index["i"] += 1
            idx = call_index["i"]
            if idx == 1:
                time.sleep(0.1)
                return str(first_path)
            return str(second_path)

        _install_glb_stub(monkeypatch, sequencer)

        r1 = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#ff0000",
                "replacement_color": "#0000ff",
            },
        )
        assert r1.status_code == 200
        first_token = _test_store.get(sid)["preview_cache"]["glb_job_token"]

        # Race: fire the second replace right away before the first
        # background build has a chance to finish.
        # 竞争：第一个后台任务还未结束就发第二个 replace。
        r2 = client.post(
            "/api/convert/replace-color",
            json={
                "session_id": sid,
                "selected_color": "#0000ff",
                "replacement_color": "#00ff00",
            },
        )
        assert r2.status_code == 200
        second_token = _test_store.get(sid)["preview_cache"]["glb_job_token"]
        assert second_token != first_token

        final = _wait_for_status(sid, lambda b: b["status"] == "ready")
        assert final["job_token"] == second_token
        # file registry was handed the *second* path; assert that's the
        # one behind the final URL.
        # 验证 FileRegistry 解析出的路径是第二次的产物。
        file_id = final["glb_url"].rsplit("/", 1)[-1]
        resolved = _test_registry.resolve(file_id)
        assert resolved is not None
        resolved_path, _ = resolved
        assert Path(resolved_path).resolve() == second_path.resolve()
