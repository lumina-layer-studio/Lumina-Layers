"""Unit tests for Converter Preview endpoint integration.

Validates:
- LUT name resolution failure returns 404 (Requirement 5.4)
- Session contains preview_cache after successful preview (Requirement 5.2)
- Response includes palette and dimensions fields (Requirement 5.3)
- asyncio.TimeoutError returns HTTP 504 (Requirement 2.3)
- General exception returns HTTP 500 (Requirement 1.4)
"""

from __future__ import annotations

import asyncio
from concurrent.futures.process import BrokenProcessPool
import inspect
import io
import json
import logging
import os
import pickle
import tempfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
from fastapi import UploadFile
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from api.app import app
from api.dependencies import get_session_store, get_file_registry, get_worker_pool
from api.preview_cache_artifacts import (
    externalize_preview_cache,
    hydrate_preview_cache,
    is_preview_cache_artifact_ref,
)
from api.routers.converter.preview import (
    _compact_preview_cache_material_matrices,
    _enforce_preview_cache_size_limit,
    _get_large_format_svg_preview_cache_max_bytes,
    _parse_selected_materials,
    _resolve_upload_source_basename,
    convert_preview,
)
from api.routers.converter.source_validation import validate_converter_source
from api.session_store import SessionStore
from api.file_registry import FileRegistry
from api.worker_pool import WorkerPoolManager
from api.workers.converter_workers import worker_generate_preview
from config import TEMP_DIR
from core.pipeline._input_validation_common import (
    VECTOR_NATIVE_REQUIRES_SVG_DETAIL,
)

# Isolated store/registry per test module to avoid cross-test pollution
_test_store: SessionStore = SessionStore(ttl=1800)
_test_registry: FileRegistry = FileRegistry()


# Mock WorkerPoolManager for dependency override
_mock_pool = MagicMock(spec=WorkerPoolManager)


class _InlineRealWorkerPool:
    """Execute the submitted top-level worker in the endpoint call."""

    async def submit_timed(
        self,
        fn,
        *args,
        timeout=None,
    ):
        del timeout
        return fn(*args), {}


def setup_module(module):
    """Re-apply dependency overrides before this module's tests run.
    在本模块测试运行前重新设置依赖覆盖，确保跨文件测试隔离。
    """
    app.dependency_overrides[get_session_store] = lambda: _test_store
    app.dependency_overrides[get_file_registry] = lambda: _test_registry
    app.dependency_overrides[get_worker_pool] = lambda: _mock_pool


def teardown_module(module):
    """Remove this module's dependency overrides after all tests complete.
    本模块所有测试完成后移除依赖覆盖。
    """
    app.dependency_overrides.pop(get_session_store, None)
    app.dependency_overrides.pop(get_file_registry, None)
    app.dependency_overrides.pop(get_worker_pool, None)


# Apply overrides immediately for module-level client creation
setup_module(None)

client: TestClient = TestClient(app)


async def _timed_submit_via_preview_mock(
    *args: object,
    **kwargs: object,
) -> tuple[object, dict[str, float]]:
    return await _mock_pool.submit(*args, **kwargs), {}


@pytest.fixture(autouse=True)
def _keep_preview_pool_timing_opt_in() -> object:
    """Keep legacy submit assertions while the route uses submit_timed."""
    previous = _mock_pool.submit_timed
    _mock_pool.submit_timed = AsyncMock(
        side_effect=_timed_submit_via_preview_mock,
    )
    with patch(
        "api.routers.converter.preview.validate_converter_source",
        return_value=None,
    ):
        try:
            yield
        finally:
            _mock_pool.submit_timed = previous


# Mock cache_data returned by generate_preview_cached
_mock_matched_rgb: np.ndarray = np.zeros((80, 120, 3), dtype=np.uint8)
_mock_matched_rgb[:40, :, :] = [255, 0, 0]  # top half red (50 rows * 120 cols = 4800 but we use 40 rows)
_mock_matched_rgb[40:, :, :] = [0, 255, 0]  # bottom half green

_mock_mask_solid: np.ndarray = np.ones((80, 120), dtype=bool)

_mock_quantized_image: np.ndarray = _mock_matched_rgb.copy()

_mock_palette: list[dict] = [
    {"hex": "#00ff00", "color": (0, 255, 0), "count": 4800, "percentage": 50.0},
    {"hex": "#ff0000", "color": (255, 0, 0), "count": 4800, "percentage": 50.0},
]
_mock_cache: dict = {
    "target_w": 120,
    "target_h": 80,
    "target_width_mm": 60.0,
    "color_palette": _mock_palette,
    "matched_rgb": _mock_matched_rgb,
    "mask_solid": _mock_mask_solid,
    "quantized_image": _mock_quantized_image,
}
_mock_preview_img: np.ndarray = np.zeros((80, 120, 3), dtype=np.uint8)


def _create_worker_result_files(cache_data: dict | None = None) -> dict:
    """Create temp files simulating worker_generate_preview output.
    创建模拟 worker_generate_preview 输出的临时文件。

    Returns:
        dict: Worker result dict with preview_png_path, cache_data_path, status_msg.
    """
    # Write preview PNG
    fd, png_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    Image.fromarray(_mock_preview_img).save(png_path)

    # Write cache pickle
    fd, cache_path = tempfile.mkstemp(suffix=".pkl")
    os.close(fd)
    with open(cache_path, "wb") as f:
        pickle.dump(cache_data if cache_data is not None else _mock_cache, f)

    return {
        "status_msg": "Preview OK",
        "preview_png_path": png_path,
        "cache_data_path": cache_path,
    }


def _create_worker_artifact_result_files(
    cache_data: dict | None = None,
) -> tuple[dict, dict]:
    """Create temp files simulating a worker-side preview-cache artifact."""
    fd, png_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    Image.fromarray(_mock_preview_img).save(png_path)

    cache = dict(cache_data if cache_data is not None else _mock_cache)
    cache.setdefault("preview_rgba", np.zeros((80, 120, 4), dtype=np.uint8))
    cache["preview_rgba"][..., 3] = 255
    cache.setdefault(
        "material_matrix",
        np.zeros((80, 120, 5), dtype=np.int16),
    )
    cache_ref = externalize_preview_cache(
        "worker-artifact",
        _test_store,
        cache,
    )
    fd, raw_png_path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    Image.fromarray(cache["preview_rgba"]).save(raw_png_path)
    fd, cache_path = tempfile.mkstemp(suffix=".pkl")
    os.close(fd)
    with open(cache_path, "wb") as f:
        pickle.dump(dict(cache_ref["metadata"]), f)

    return (
        {
            "status_msg": "Preview OK",
            "preview_png_path": png_path,
            "cache_data_path": cache_path,
            "cache_artifact_ref": cache_ref,
            "raw_preview_png_path": raw_png_path,
        },
        cache_ref,
    )


def _make_test_image_buf() -> io.BytesIO:
    """Create a minimal PNG image buffer for upload."""
    img = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


class _RecordingSessionStore(SessionStore):
    """SessionStore test double that records created sessions and temp paths."""

    def __init__(self) -> None:
        super().__init__(ttl=1800)
        self.created_session_ids: list[str] = []
        self.registered_temp_paths: list[str] = []

    def create(self, session_id: str | None = None) -> str:
        created = super().create(session_id=session_id)
        self.created_session_ids.append(created)
        return created

    def register_temp_file(self, session_id: str, path: str) -> None:
        self.registered_temp_paths.append(path)
        super().register_temp_file(session_id, path)


class _FailingRegisterBytesRegistry(FileRegistry):
    """FileRegistry test double that fails selected byte registrations."""

    def __init__(self, fail_filename: str) -> None:
        super().__init__()
        self.fail_filename = fail_filename
        self.registered_file_ids: list[str] = []
        self.registered_paths: list[str] = []

    def register_bytes(  # type: ignore[override]
        self,
        session_id: str,
        data: bytes,
        filename: str,
        **kwargs,
    ) -> str:
        if filename == self.fail_filename:
            raise OSError(f"simulated {filename} registration failure")
        file_id = super().register_bytes(session_id, data, filename, **kwargs)
        entry = self.get_entry(file_id)
        if entry is not None:
            self.registered_file_ids.append(file_id)
            self.registered_paths.append(str(entry["path"]))
        return file_id


def _create_worker_result_files_in_dir(
    directory: Path,
    *,
    cache: dict | None = None,
) -> dict:
    """Create worker result files under a test-owned temp directory."""

    preview_path = directory / "worker-preview.png"
    Image.fromarray(_mock_preview_img).save(preview_path)

    cache_path = directory / "worker-cache.pkl"
    with cache_path.open("wb") as f:
        pickle.dump(_mock_cache if cache is None else cache, f)

    return {
        "status_msg": "Preview OK",
        "preview_png_path": str(preview_path),
        "cache_data_path": str(cache_path),
    }


def _preview_cache_with_raw_rgba() -> dict:
    """Return mock preview cache that triggers preview_raw.png registration."""

    cache = dict(_mock_cache)
    cache["preview_rgba"] = np.zeros((80, 120, 4), dtype=np.uint8)
    cache["preview_rgba"][:, :, 3] = 255
    return cache


def _run_preview_with_local_dependencies(
    monkeypatch,
    tmp_path: Path,
    *,
    registry: FileRegistry,
    cache: dict | None = None,
    externalize_side_effect=None,
    worker_timing: dict[str, float] | None = None,
) -> tuple[object, _RecordingSessionStore]:
    """Run /api/convert/preview with isolated dependencies and temp dir."""

    monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
    monkeypatch.setattr("api.file_registry.TEMP_DIR", str(tmp_path))
    monkeypatch.setattr("api.preview_cache_artifacts.TEMP_DIR", str(tmp_path))
    monkeypatch.setattr("api.routers.converter.preview.TEMP_DIR", str(tmp_path))

    store = _RecordingSessionStore()
    pool = MagicMock(spec=WorkerPoolManager)
    worker_result = _create_worker_result_files_in_dir(tmp_path, cache=cache)
    pool.submit = AsyncMock(return_value=worker_result)
    pool.submit_timed = AsyncMock(
        return_value=(worker_result, dict(worker_timing or {}))
    )
    uploaded_path = tmp_path / "uploaded.png"
    Image.new("RGB", (10, 10), (0, 0, 0)).save(uploaded_path)

    previous_overrides = {
        get_session_store: app.dependency_overrides.get(get_session_store),
        get_file_registry: app.dependency_overrides.get(get_file_registry),
        get_worker_pool: app.dependency_overrides.get(get_worker_pool),
    }
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: pool

    externalize_patch = (
        patch(
            "api.routers.converter.preview.externalize_preview_cache",
            side_effect=externalize_side_effect,
        )
        if externalize_side_effect is not None
        else nullcontext()
    )

    try:
        local_client = TestClient(app, raise_server_exceptions=False)
        with (
            patch(
                "api.routers.converter.preview.LUTManager.resolve_source_selection",
                return_value=("/tmp/fake.npy", "Fake LUT"),
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value=str(uploaded_path)),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
            externalize_patch,
        ):
            response = local_client.post(
                "/api/convert/preview",
                files={"image": ("test.png", _make_test_image_buf(), "image/png")},
                data={"lut_name": "test_lut", "color_mode": "4-Color"},
            )
    finally:
        for dependency, previous in previous_overrides.items():
            if previous is None:
                app.dependency_overrides.pop(dependency, None)
            else:
                app.dependency_overrides[dependency] = previous

    return response, store


def test_preview_response_exposes_worker_pool_timing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    timing = {
        "queue_wait_s": 0.125,
        "worker_execution_s": 0.75,
        "result_delivery_s": 0.025,
        "pool_roundtrip_s": 0.9,
    }
    registry = FileRegistry()

    response, store = _run_preview_with_local_dependencies(
        monkeypatch,
        tmp_path,
        registry=registry,
        worker_timing=timing,
    )

    assert response.status_code == 200, response.text
    performance = response.json()["performance_timing"]
    assert performance["queue_wait_ms"] == 125.0
    assert performance["worker_execution_ms"] == 750.0
    assert performance["result_delivery_ms"] == 25.0
    assert performance["endpoint_post_worker_ms"] >= 0.0

    session_id = response.json()["session_id"]
    store.close(session_id)
    registry.cleanup_session(session_id)


def test_preview_lut_constrained_positive_hue_weight_succeeds_through_worker(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "input.png"
    lut_path = tmp_path / "lut.npz"
    Image.new("RGB", (8, 8), (220, 20, 60)).save(image_path)
    np.savez(
        lut_path,
        rgb=np.array([[255, 255, 255], [220, 20, 60]], dtype=np.uint8),
        stacks=np.array(
            [[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]],
            dtype=np.int32,
        ),
    )

    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    previous_overrides = {
        get_session_store: app.dependency_overrides.get(get_session_store),
        get_file_registry: app.dependency_overrides.get(get_file_registry),
        get_worker_pool: app.dependency_overrides.get(get_worker_pool),
    }
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: _InlineRealWorkerPool()

    session_id = None
    try:
        local_client = TestClient(app, raise_server_exceptions=False)
        with (
            patch(
                "api.routers.converter.preview.LUTManager.resolve_source_selection",
                return_value=(str(lut_path), "Temporary LUT"),
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value=str(image_path)),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
            patch("config.TEMP_DIR", str(tmp_path)),
            patch("api.preview_cache_artifacts.TEMP_DIR", str(tmp_path)),
            patch("api.routers.converter.preview.TEMP_DIR", str(tmp_path)),
        ):
            response = local_client.post(
                "/api/convert/preview",
                files={
                    "image": (
                        "input.png",
                        image_path.read_bytes(),
                        "image/png",
                    )
                },
                data={
                    "lut_name": "temporary_lut",
                    "color_mode": "4-Color (RYBW)",
                    "target_width_mm": "10",
                    "quantize_colors": "8",
                    "use_lut_constrained": "true",
                    "hue_weight": "0.5",
                },
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            session_id = payload["session_id"]
            assert payload["preview_url"].startswith("/api/files/")
            assert local_client.get(payload["preview_url"]).status_code == 200
    finally:
        if session_id is not None:
            store.close(session_id)
            registry.cleanup_session(session_id)
        for dependency, previous in previous_overrides.items():
            if previous is None:
                app.dependency_overrides.pop(dependency, None)
            else:
                app.dependency_overrides[dependency] = previous


def test_preview_small_real_input_keeps_print_dimensions_with_bounded_display(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worker PNG budget must not become the printable grid dimensions."""
    monkeypatch.setattr("config.IMAGE_PREVIEW_MAX_EDGE", 32)
    monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
    monkeypatch.setattr("api.file_registry.TEMP_DIR", str(tmp_path))
    monkeypatch.setattr("api.preview_cache_artifacts.TEMP_DIR", str(tmp_path))
    monkeypatch.setattr("api.routers.converter.preview.TEMP_DIR", str(tmp_path))
    image_path = tmp_path / "input.png"
    rgba = np.full((12, 8, 4), 255, dtype=np.uint8)
    rgba[:2, :, 3] = 0
    rgba[4:10, 2:6, :3] = [220, 20, 60]
    Image.fromarray(rgba).save(image_path)
    lut_path = tmp_path / "lut.npz"
    np.savez(
        lut_path,
        rgb=np.array([[255, 255, 255], [220, 20, 60]], dtype=np.uint8),
        stacks=np.array([[0, 0, 0, 0, 0], [1, 1, 1, 1, 1]], dtype=np.int32),
    )
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    monkeypatch.setitem(app.dependency_overrides, get_session_store, lambda: store)
    monkeypatch.setitem(app.dependency_overrides, get_file_registry, lambda: registry)
    monkeypatch.setitem(
        app.dependency_overrides, get_worker_pool, lambda: _InlineRealWorkerPool(),
    )

    try:
        local_client = TestClient(app, raise_server_exceptions=False)
        with (
            patch(
                "api.routers.converter.preview.LUTManager.resolve_source_selection",
                return_value=(str(lut_path), "Temporary LUT"),
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value=str(image_path)),
            ),
            patch("api.routers.converter.preview.generate_segmented_glb", return_value=None),
        ):
            response = local_client.post(
                "/api/convert/preview",
                files={"image": ("input.png", image_path.read_bytes(), "image/png")},
                data={
                    "lut_name": "temporary_lut", "color_mode": "4-Color (RYBW)",
                    "target_width_mm": "4", "quantize_colors": "8",
                    "enable_cleanup": "false",
                },
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            dimensions = payload["dimensions"]
            assert dimensions["width"] == 40
            assert dimensions["height"] == 60
            assert dimensions["width_mm"] == 4.0
            assert dimensions["height_mm"] == 6.0
            display_response = local_client.get(payload["preview_url"])
            assert display_response.status_code == 200
            with Image.open(io.BytesIO(display_response.content)) as display:
                assert display.size == (21, 32)
                assert display.mode == "RGBA"
                assert display.getchannel("A").getextrema() == (0, 255)
            raw_response = local_client.get(dimensions["preview_raw_url"])
            assert raw_response.status_code == 200
            with Image.open(io.BytesIO(raw_response.content)) as raw:
                assert raw.size == (40, 60)
    finally:
        store.clear_all()
        registry.clear_all()


def test_empty_svg_real_worker_returns_actionable_422(tmp_path: Path) -> None:
    """Exercise the real vector wrapper that prefixes the stable diagnostic."""

    image_path = tmp_path / "empty.svg"
    image_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<rect width="10" height="10" fill="none"/></svg>',
        encoding="utf-8",
    )
    upload_bytes = image_path.read_bytes()
    lut_path = Path(
        "lut-preset/Custom/Bambulab&PLA&RYBW&红-黄-蓝-白.npy"
    ).resolve()
    assert lut_path.exists()

    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    previous_overrides = {
        get_session_store: app.dependency_overrides.get(get_session_store),
        get_file_registry: app.dependency_overrides.get(get_file_registry),
        get_worker_pool: app.dependency_overrides.get(get_worker_pool),
    }
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: _InlineRealWorkerPool()

    try:
        local_client = TestClient(app, raise_server_exceptions=False)
        with (
            patch(
                "api.routers.converter.preview.LUTManager.resolve_source_selection",
                return_value=(str(lut_path), "Temporary LUT"),
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value=str(image_path)),
            ),
            patch(
                "api.routers.converter.preview.validate_converter_source",
                wraps=validate_converter_source,
            ),
            patch("config.TEMP_DIR", str(tmp_path)),
            patch("api.preview_cache_artifacts.TEMP_DIR", str(tmp_path)),
            patch("api.routers.converter.preview.TEMP_DIR", str(tmp_path)),
        ):
            response = local_client.post(
                "/api/convert/preview",
                files={"image": ("empty.svg", upload_bytes, "image/svg+xml")},
                data={
                    "lut_name": "temporary_lut",
                    "color_mode": "4-Color (RYBW)",
                    "modeling_mode": "vector",
                    "target_width_mm": "10",
                },
            )

        assert response.status_code == 422, response.text
        assert response.json()["detail"]["error"] == (
            "source_svg_no_renderable_geometry"
        )
        assert "No valid shapes" not in response.text
        assert not image_path.exists()
    finally:
        registry.clear_all()
        store.clear_all()
        for dependency, previous in previous_overrides.items():
            if previous is None:
                app.dependency_overrides.pop(dependency, None)
            else:
                app.dependency_overrides[dependency] = previous


class TestPreviewRegistrationFailureRollback:
    """Preview failures after session creation should not leave hidden sessions."""

    def test_preview_cache_externalize_failure_cleans_pre_registration_files(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        registry = FileRegistry()

        def fail_externalize(session_id: str, store: SessionStore, _cache: dict) -> dict:
            partial_path = tmp_path / "preview-cache-partial.npy"
            np.save(partial_path, np.zeros((1, 1), dtype=np.uint8))
            store.register_temp_file(session_id, str(partial_path))
            raise OSError("simulated preview cache externalize failure")

        response, store = _run_preview_with_local_dependencies(
            monkeypatch,
            tmp_path,
            registry=registry,
            externalize_side_effect=fail_externalize,
        )

        assert response.status_code == 500
        assert store.created_session_ids
        assert store.registered_temp_paths
        for session_id in store.created_session_ids:
            assert store.get(session_id) is None
            assert registry.get_session_entries(session_id) == {}
        for path in store.registered_temp_paths:
            assert not os.path.exists(path)
        assert list(tmp_path.iterdir()) == []

    def test_preview_bytes_registration_failure_closes_unreturned_session(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        registry = _FailingRegisterBytesRegistry(fail_filename="preview.png")

        response, store = _run_preview_with_local_dependencies(
            monkeypatch,
            tmp_path,
            registry=registry,
        )

        assert response.status_code == 500
        assert store.created_session_ids
        assert store.registered_temp_paths
        for session_id in store.created_session_ids:
            assert store.get(session_id) is None
            assert registry.get_session_entries(session_id) == {}
        for path in store.registered_temp_paths:
            assert not os.path.exists(path)
        assert list(tmp_path.iterdir()) == []

    def test_preview_raw_registration_failure_cleans_prior_preview_file(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        registry = _FailingRegisterBytesRegistry(fail_filename="preview_raw.png")

        response, store = _run_preview_with_local_dependencies(
            monkeypatch,
            tmp_path,
            registry=registry,
            cache=_preview_cache_with_raw_rgba(),
        )

        assert response.status_code == 500
        assert store.created_session_ids
        assert store.registered_temp_paths
        assert registry.registered_file_ids
        for session_id in store.created_session_ids:
            assert store.get(session_id) is None
            assert registry.get_session_entries(session_id) == {}
        for file_id in registry.registered_file_ids:
            assert registry.get_entry(file_id) is None
        for path in [*store.registered_temp_paths, *registry.registered_paths]:
            assert not os.path.exists(path)
        assert list(tmp_path.iterdir()) == []


class TestBedPreviewRegistrationCleanup:
    """Verify empty-bed preview GLB ownership across registry outcomes."""

    def test_bed_preview_keeps_glb_when_registration_succeeds(self, tmp_path) -> None:
        """Successful registration should preserve the generated GLB file."""
        glb_path = tmp_path / "empty_bed.glb"
        previous_registry_override = app.dependency_overrides.get(get_file_registry)

        class RecordingRegistry:
            def __init__(self) -> None:
                self.registered_path: str | None = None

            def register_path(self, _session_id: str, path: str, **_kwargs) -> str:
                self.registered_path = path
                assert os.path.exists(path)
                return "bed-preview-file"

        registry = RecordingRegistry()

        def fake_generate_empty_bed_glb(_bed_w: int, _bed_h: int) -> str:
            glb_path.write_bytes(b"glb")
            return str(glb_path)

        try:
            app.dependency_overrides[get_file_registry] = lambda: registry
            with patch(
                "api.routers.converter.preview.generate_empty_bed_glb",
                side_effect=fake_generate_empty_bed_glb,
            ):
                response = client.get("/api/convert/bed-preview")
        finally:
            if previous_registry_override is None:
                app.dependency_overrides.pop(get_file_registry, None)
            else:
                app.dependency_overrides[get_file_registry] = previous_registry_override

        assert response.status_code == 200
        assert response.json() == {"preview_3d_url": "/api/files/bed-preview-file"}
        assert registry.registered_path == str(glb_path)
        assert glb_path.exists()

    def test_bed_preview_cleans_glb_when_registration_fails(self, tmp_path) -> None:
        """Failed registration should not leave an unowned empty-bed GLB."""
        glb_path = tmp_path / "empty_bed.glb"
        previous_registry_override = app.dependency_overrides.get(get_file_registry)

        class FailingRegistry:
            def register_path(self, *_args, **_kwargs) -> str:
                raise RuntimeError("forced registry failure")

        def fake_generate_empty_bed_glb(_bed_w: int, _bed_h: int) -> str:
            glb_path.write_bytes(b"glb")
            return str(glb_path)

        try:
            app.dependency_overrides[get_file_registry] = lambda: FailingRegistry()
            with patch(
                "api.routers.converter.preview.generate_empty_bed_glb",
                side_effect=fake_generate_empty_bed_glb,
            ):
                failing_client = TestClient(app, raise_server_exceptions=False)
                response = failing_client.get("/api/convert/bed-preview")
        finally:
            if previous_registry_override is None:
                app.dependency_overrides.pop(get_file_registry, None)
            else:
                app.dependency_overrides[get_file_registry] = previous_registry_override

        assert response.status_code == 500
        assert not glb_path.exists()


# =========================================================================
# 1. LUT name resolution failure returns 404 - Requirement 5.4
# =========================================================================


class TestLutNotFoundReturns404:
    """Verify unresolvable lut_name returns HTTP 404."""

    def test_preview_unknown_lut_returns_404(self) -> None:
        """Send a non-existent lut_name, expect 404."""
        buf = _make_test_image_buf()
        with patch(
            "api.routers.converter.preview.LUTManager.get_lut_path",
            return_value=None,
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "nonexistent_lut",
                    "color_mode": "4-Color",
                },
            )
        assert response.status_code == 404
        assert "LUT" in response.json()["detail"]


class TestPreviewMaterialSourceValidation:
    """Verify preview rejects unsupported material source values early."""

    def test_preview_rejects_invalid_material_source_before_io(self) -> None:
        """Invalid material_source should not resolve LUTs, upload, or submit work."""
        buf = _make_test_image_buf()
        worker_result = _create_worker_result_files()
        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with (
            patch(
                "api.routers.converter.preview.LUTManager.resolve_source_selection",
                return_value=("/tmp/fake.npy", "Fake LUT"),
            ) as resolve_source,
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ) as ensure_png,
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "material_source": "bad-source",
                },
            )

        assert response.status_code == 422
        assert "material_source" in response.json()["detail"]
        resolve_source.assert_not_called()
        ensure_png.assert_not_called()
        _mock_pool.submit.assert_not_called()

    def test_dynamic_material_replacements_reach_exact_worker_path(self) -> None:
        """Task 3B replays dynamic replacements in the exact worker path."""
        buf = _make_test_image_buf()
        _mock_pool.submit = AsyncMock(return_value=_create_worker_result_files())

        with patch(
            "api.routers.converter.preview.ensure_png_tempfile",
            new=AsyncMock(return_value="/tmp/uploaded.png"),
        ) as ensure_png:
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "material_source": "material_archive",
                    "selected_materials": json.dumps(["mat-a", "mat-b"]),
                    "material_dynamic_layer_count_enabled": "true",
                    "replacement_regions": json.dumps(
                        [
                            {
                                "quantized_hex": "#111111",
                                "matched_hex": "#222222",
                                "replacement_hex": "#333333",
                            }
                        ]
                    ),
                },
            )

        assert response.status_code == 200, response.text
        ensure_png.assert_awaited_once()
        call_args = _mock_pool.submit.call_args.args
        submitted = dict(
            zip(inspect.signature(worker_generate_preview).parameters, call_args[1:])
        )
        assert submitted["material_dynamic_layer_count_enabled"] is True
        assert submitted["replacement_regions"] == [
            {
                "quantized_hex": "#111111",
                "matched_hex": "#222222",
                "replacement_hex": "#333333",
            }
        ]



# =========================================================================
# 2. Session contains preview_cache - Requirement 5.2
# =========================================================================


class TestSessionContainsPreviewCache:
    """Verify session stores preview_cache after successful preview."""

    def test_preview_stores_cache_in_session(self) -> None:
        """Mock worker pool submit, verify session has preview_cache."""
        buf = _make_test_image_buf()
        worker_result = _create_worker_result_files()

        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )
        assert response.status_code == 200
        body = response.json()
        session_id: str = body["session_id"]
        assert session_id

        session_data = _test_store.get(session_id)
        assert session_data is not None
        assert "preview_cache" in session_data
        # Verify cache_data was loaded from pickle (values match)
        loaded_cache = hydrate_preview_cache(
            session_data["preview_cache"],
            fields={"matched_rgb"},
        )
        assert loaded_cache["target_w"] == 120
        assert loaded_cache["target_h"] == 80
        np.testing.assert_array_equal(loaded_cache["matched_rgb"], _mock_matched_rgb)

    @pytest.mark.parametrize(
        ("form_data", "expected"),
        [({}, True), ({"enable_smooth_vector_preview": "false"}, False)],
    )
    def test_preview_stores_smooth_vector_renderer_preference(
        self,
        form_data: dict[str, str],
        expected: bool,
    ) -> None:
        """Renderer preference is server-owned session metadata with default-on semantics."""
        buf = _make_test_image_buf()
        _mock_pool.submit = AsyncMock(return_value=_create_worker_result_files())

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                    **form_data,
                },
            )

        assert response.status_code == 200, response.text
        session_data = _test_store.get(response.json()["session_id"])
        assert session_data is not None
        cache_ref = session_data["preview_cache"]
        cache_metadata = (
            cache_ref["metadata"]
            if is_preview_cache_artifact_ref(cache_ref)
            else cache_ref
        )
        assert cache_metadata["enable_smooth_vector_preview"] is expected

    def test_preview_externalizes_cache_arrays_and_original_snapshot(
        self,
    ) -> None:
        """Preview cache arrays should be private artifacts, not session arrays."""
        buf = _make_test_image_buf()
        worker_result = _create_worker_result_files()

        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )

        assert response.status_code == 200
        session_data = _test_store.get(response.json()["session_id"])
        assert session_data is not None
        cache_ref = session_data["preview_cache"]

        assert is_preview_cache_artifact_ref(cache_ref)
        assert cache_ref["metadata"]["target_w"] == 120
        assert cache_ref["metadata"]["target_h"] == 80
        assert "matched_rgb" in cache_ref["fields"]
        assert "mask_solid" in cache_ref["fields"]
        assert "quantized_image" in cache_ref["fields"]
        assert "original_matched_rgb" in cache_ref["fields"]
        assert "matched_rgb" not in cache_ref["metadata"]
        assert "original_matched_rgb" not in session_data
        assert "original_material_matrix" not in session_data
        assert not any(
            isinstance(value, np.ndarray)
            for value in cache_ref["metadata"].values()
        )

    def test_preview_compacts_material_matrix_before_externalizing(self) -> None:
        """Material matrices should not keep int32 when a smaller signed dtype fits."""
        buf = _make_test_image_buf()
        material_matrix = np.full((80, 120, 9), 17, dtype=np.int32)
        material_matrix[0, 0, :] = -1
        worker_result = _create_worker_result_files(
            {
                **_mock_cache,
                "material_matrix": material_matrix,
            }
        )

        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with (
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "material_source": "material_archive",
                    "selected_materials": json.dumps(
                        [f"material-{i}" for i in range(18)]
                    ),
                    "material_layer_count": "9",
                    "material_dynamic_layer_count_enabled": "true",
                    "material_min_layer_count": "6",
                    "material_max_layer_count": "9",
                    "material_delta_e00_tolerance": "0.4",
                    "material_backing_material_index": "1",
                },
            )

        assert response.status_code == 200
        call_args = _mock_pool.submit.call_args.args
        submitted = dict(
            zip(inspect.signature(worker_generate_preview).parameters, call_args[1:])
        )
        assert submitted["material_backing_material_index"] == 1
        assert submitted["material_dynamic_layer_count_enabled"] is True
        assert submitted["material_min_layer_count"] == 6
        assert submitted["material_max_layer_count"] == 9
        assert submitted["material_delta_e00_tolerance"] == 0.4
        session_data = _test_store.get(response.json()["session_id"])
        assert session_data is not None
        assert session_data["material_dynamic_layer_count_enabled"] is True
        assert session_data["material_min_layer_count"] == 6
        assert session_data["material_max_layer_count"] == 9
        assert session_data["material_delta_e00_tolerance"] == 0.4
        cache_ref = session_data["preview_cache"]
        assert cache_ref["fields"]["material_matrix"]["dtype"] == "int8"
        assert cache_ref["fields"]["original_material_matrix"]["dtype"] == "int8"

        loaded_cache = hydrate_preview_cache(
            cache_ref,
            fields={"material_matrix", "original_material_matrix"},
        )
        assert loaded_cache["material_matrix"].dtype == np.int8
        assert loaded_cache["original_material_matrix"].dtype == np.int8
        np.testing.assert_array_equal(
            loaded_cache["material_matrix"],
            material_matrix.astype(np.int8),
        )
        np.testing.assert_array_equal(
            loaded_cache["original_material_matrix"],
            material_matrix.astype(np.int8),
        )

    def test_preview_copies_dynamic_recipes_and_benefit_curve(self) -> None:
        recipes = [
            {
                "target_srgb": [240, 220, 200],
                "matched_srgb": [238, 218, 198],
                "actual_layer_count": 6,
                "padding_layer_count": 0,
                "actual_recipe_top_to_bottom": [0, 1, 0, 1, 0, 1],
                "print_recipe_top_to_bottom": [0, 1, 0, 1, 0, 1],
                "selected_delta_e00": 0.3,
                "best_range_delta_e00": 0.2,
                "fixed_max_delta_e00": 0.4,
                "delta_e00_sacrifice": 0.1,
                "layer_cap_options": [
                    {
                        "max_effective_layer_count": 6,
                        "actual_layer_count": 6,
                        "matched_srgb": [238, 218, 198],
                        "actual_recipe_top_to_bottom": [0, 1, 0, 1, 0, 1],
                        "print_recipe_top_to_bottom": [0, 1, 0, 1, 0, 1],
                        "delta_e00": 0.3,
                    }
                ],
            }
        ]
        benefit_curve = [
            {
                "max_effective_layer_count": 6,
                "weighted_mean_delta_e00": 0.3,
                "marginal_delta_e00_reduction": 0.2,
            }
        ]
        worker_result = _create_worker_result_files(
            {
                **_mock_cache,
                "material_dynamic_layer_info": {
                    "colors": recipes,
                    "benefit_curve": benefit_curve,
                },
            }
        )
        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with (
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={
                    "image": ("test.png", _make_test_image_buf(), "image/png")
                },
                data={
                    "material_source": "material_archive",
                    "selected_materials": json.dumps(["mat-a", "mat-b"]),
                    "material_dynamic_layer_count_enabled": "true",
                },
            )

        assert response.status_code == 200, response.text
        assert response.json()["material_dynamic_recipes"] == recipes
        assert response.json()["material_layer_benefit_curve"] == benefit_curve

    def test_preview_adopts_worker_cache_artifact_ref(self) -> None:
        """Worker-side cache artifacts should become the session preview cache."""
        buf = _make_test_image_buf()
        worker_result, worker_cache_ref = _create_worker_artifact_result_files()

        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )

        assert response.status_code == 200, response.text
        session_data = _test_store.get(response.json()["session_id"])
        assert session_data is not None
        stored_ref = session_data["preview_cache"]
        assert is_preview_cache_artifact_ref(stored_ref)
        assert stored_ref["fields"]["matched_rgb"]["path"] == (
            worker_cache_ref["fields"]["matched_rgb"]["path"]
        )
        assert stored_ref["fields"]["original_matched_rgb"]["path"] == (
            worker_cache_ref["fields"]["matched_rgb"]["path"]
        )
        assert stored_ref["fields"]["material_matrix"]["path"] == (
            worker_cache_ref["fields"]["material_matrix"]["path"]
        )
        assert stored_ref["fields"]["original_material_matrix"]["path"] == (
            worker_cache_ref["fields"]["material_matrix"]["path"]
        )
        tracked_paths = set(_test_store.get_temp_file_paths(response.json()["session_id"]))
        assert worker_cache_ref["fields"]["matched_rgb"]["path"] in tracked_paths
        assert worker_cache_ref["fields"]["material_matrix"]["path"] in tracked_paths
        preview_raw_url = response.json()["dimensions"]["preview_raw_url"]
        raw_file_id = preview_raw_url.rsplit("/", 1)[-1]
        raw_entry = _test_registry.get_entry(raw_file_id)
        assert raw_entry is not None
        assert raw_entry["path"] == worker_result["raw_preview_png_path"]
        assert worker_result["raw_preview_png_path"] in tracked_paths

    def test_preview_replacement_cache_reset_restores_worker_pristine_arrays(
        self,
    ) -> None:
        """Explicit worker originals must survive route adoption and reset."""
        buf = _make_test_image_buf()
        pristine_rgb = np.full((80, 120, 3), [10, 20, 30], dtype=np.uint8)
        replaced_rgb = np.full((80, 120, 3), [40, 50, 60], dtype=np.uint8)
        pristine_matrix = np.zeros((80, 120, 5), dtype=np.int16)
        replaced_matrix = np.full((80, 120, 5), 3, dtype=np.int16)
        worker_result, worker_cache_ref = _create_worker_artifact_result_files(
            {
                **_mock_cache,
                "matched_rgb": replaced_rgb,
                "height_identity_rgb": pristine_rgb.copy(),
                "original_matched_rgb": pristine_rgb.copy(),
                "material_matrix": replaced_matrix,
                "original_material_matrix": pristine_matrix.copy(),
                "preview_rgba": np.dstack(
                    [replaced_rgb, np.full((80, 120), 255, dtype=np.uint8)]
                ),
            }
        )
        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                    "replacement_regions": json.dumps(
                        [
                            {
                                "quantized_hex": "#0a141e",
                                "matched_hex": "#0a141e",
                                "replacement_hex": "#28323c",
                            }
                        ]
                    ),
                },
            )

        assert response.status_code == 200, response.text
        sid = response.json()["session_id"]
        stored_ref = _test_store.get(sid)["preview_cache"]
        assert stored_ref["fields"]["original_matched_rgb"]["path"] == (
            worker_cache_ref["fields"]["original_matched_rgb"]["path"]
        )
        assert stored_ref["fields"]["height_identity_rgb"]["path"] == (
            worker_cache_ref["fields"]["height_identity_rgb"]["path"]
        )
        assert stored_ref["fields"]["original_material_matrix"]["path"] == (
            worker_cache_ref["fields"]["original_material_matrix"]["path"]
        )
        before_reset = hydrate_preview_cache(
            stored_ref,
            fields={
                "matched_rgb",
                "height_identity_rgb",
                "original_matched_rgb",
                "material_matrix",
                "original_material_matrix",
            },
        )
        np.testing.assert_array_equal(before_reset["matched_rgb"], replaced_rgb)
        np.testing.assert_array_equal(before_reset["material_matrix"], replaced_matrix)
        np.testing.assert_array_equal(before_reset["height_identity_rgb"], pristine_rgb)

        with patch(
            "api.routers.converter.replace.schedule_glb_build",
            return_value="test-reset-token",
        ):
            reset_response = client.post(
                "/api/convert/reset-replacements",
                json={"session_id": sid},
            )

        assert reset_response.status_code == 200, reset_response.text
        reset_ref = _test_store.get(sid)["preview_cache"]
        after_reset = hydrate_preview_cache(
            reset_ref,
            fields={"matched_rgb", "height_identity_rgb", "material_matrix"},
        )
        np.testing.assert_array_equal(after_reset["matched_rgb"], pristine_rgb)
        np.testing.assert_array_equal(after_reset["material_matrix"], pristine_matrix)
        np.testing.assert_array_equal(after_reset["height_identity_rgb"], pristine_rgb)

    def test_preview_uses_worker_precomputed_payloads_without_hydrating_inputs(
        self,
    ) -> None:
        """Worker-side palette/groups should avoid main-process input hydration."""
        buf = _make_test_image_buf()
        worker_result, _worker_cache_ref = _create_worker_artifact_result_files()
        expected_palette = [
            {
                "quantized_hex": "#00ff00",
                "matched_hex": "#00ff00",
                "pixel_count": 4800,
                "percentage": 50.0,
            },
            {
                "quantized_hex": "#ff0000",
                "matched_hex": "#ff0000",
                "pixel_count": 4800,
                "percentage": 50.0,
            },
        ]
        fd, region_map_path = tempfile.mkstemp(suffix=".npy")
        os.close(fd)
        region_map = np.zeros((80, 120), dtype=np.uint32)
        np.save(region_map_path, region_map)
        worker_result["response_palette"] = expected_palette
        worker_result["gradient_groups"] = []
        worker_result["gradient_region_id_map_path"] = region_map_path
        hydrate_fields: list[set[str] | None] = []

        def _capture_hydrate(ref: dict, *args, **kwargs) -> dict:
            hydrate_fields.append(kwargs.get("fields"))
            return hydrate_preview_cache(ref, *args, **kwargs)

        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
            patch(
                "api.routers.converter.preview.hydrate_preview_cache",
                side_effect=_capture_hydrate,
            ),
            patch(
                "api.routers.converter.preview.recompute_gradient_groups_into_session",
                side_effect=AssertionError(
                    "route should use worker-computed gradient groups"
                ),
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["palette"] == expected_palette
        assert hydrate_fields == [set()]
        session_data = _test_store.get(body["session_id"])
        assert session_data is not None
        assert session_data["gradient_groups"] == []
        np.testing.assert_array_equal(
            session_data["gradient_region_id_map"],
            region_map,
        )
        tracked_paths = set(_test_store.get_temp_file_paths(body["session_id"]))
        assert region_map_path in tracked_paths

    def test_preview_persists_vector_parse_clip_cache_blob_as_metadata_path(
        self,
    ) -> None:
        """Worker vector cache bytes should become a session-owned metadata path."""
        buf = _make_test_image_buf()
        cache_with_blob = dict(_mock_cache)
        cache_with_blob["vector_parse_clip_cache_blob"] = b"parse-clip-cache"

        fd, png_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        Image.fromarray(_mock_preview_img).save(png_path)
        fd, cache_path = tempfile.mkstemp(suffix=".pkl")
        os.close(fd)
        with open(cache_path, "wb") as handle:
            pickle.dump(cache_with_blob, handle)

        _mock_pool.submit = AsyncMock(
            return_value={
                "status_msg": "Preview OK",
                "preview_png_path": png_path,
                "cache_data_path": cache_path,
            }
        )

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )

        assert response.status_code == 200, response.text
        session_data = _test_store.get(response.json()["session_id"])
        assert session_data is not None
        cache_ref = session_data["preview_cache"]
        metadata = cache_ref["metadata"]
        assert "vector_parse_clip_cache_blob" not in metadata
        vector_cache_path = metadata["vector_parse_clip_cache_path"]
        assert os.path.exists(vector_cache_path)
        with open(vector_cache_path, "rb") as handle:
            assert handle.read() == b"parse-clip-cache"

    def test_preview_cleans_vector_parse_clip_cache_blob_on_register_failure(
        self,
        monkeypatch,
        tmp_path: Path,
    ) -> None:
        """Vector cache fallback files should be removed if session adoption fails."""
        monkeypatch.setattr("api.routers.converter.preview.TEMP_DIR", str(tmp_path))
        buf = _make_test_image_buf()
        cache_with_blob = dict(_mock_cache)
        cache_with_blob["vector_parse_clip_cache_blob"] = b"parse-clip-cache"

        fd, png_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        Image.fromarray(_mock_preview_img).save(png_path)
        fd, cache_path = tempfile.mkstemp(suffix=".pkl")
        os.close(fd)
        with open(cache_path, "wb") as handle:
            pickle.dump(cache_with_blob, handle)

        original_register_temp_file = _test_store.register_temp_file
        attempted_vector_cache_paths: list[str] = []

        def fail_vector_cache_register(session_id: str, path: str) -> None:
            if Path(path).name.startswith("vector_parse_clip_cache_"):
                attempted_vector_cache_paths.append(path)
                raise OSError("simulated vector cache registration failure")
            original_register_temp_file(session_id, path)

        _mock_pool.submit = AsyncMock(
            return_value={
                "status_msg": "Preview OK",
                "preview_png_path": png_path,
                "cache_data_path": cache_path,
            }
        )

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
            patch.object(
                _test_store,
                "register_temp_file",
                side_effect=fail_vector_cache_register,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )

        assert response.status_code == 200, response.text
        assert attempted_vector_cache_paths
        for path in attempted_vector_cache_paths:
            assert not os.path.exists(path)
        assert not list(tmp_path.glob("vector_parse_clip_cache_*.pkl"))
        session_data = _test_store.get(response.json()["session_id"])
        assert session_data is not None
        metadata = session_data["preview_cache"]["metadata"]
        assert "vector_parse_clip_cache_blob" not in metadata
        assert "vector_parse_clip_cache_path" not in metadata

    def test_preview_skips_oversized_vector_parse_clip_cache_blob(
        self,
        monkeypatch,
    ) -> None:
        """Oversized vector cache artifacts should not make preview cache grow."""
        monkeypatch.setenv("LUMINA_VECTOR_PARSE_CLIP_CACHE_MAX_BYTES", "4")
        buf = _make_test_image_buf()
        cache_with_blob = dict(_mock_cache)
        cache_with_blob["vector_parse_clip_cache_blob"] = b"too-large"

        fd, png_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        Image.fromarray(_mock_preview_img).save(png_path)
        fd, cache_path = tempfile.mkstemp(suffix=".pkl")
        os.close(fd)
        with open(cache_path, "wb") as handle:
            pickle.dump(cache_with_blob, handle)

        _mock_pool.submit = AsyncMock(
            return_value={
                "status_msg": "Preview OK",
                "preview_png_path": png_path,
                "cache_data_path": cache_path,
            }
        )

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )

        assert response.status_code == 200, response.text
        session_data = _test_store.get(response.json()["session_id"])
        assert session_data is not None
        metadata = session_data["preview_cache"]["metadata"]
        assert "vector_parse_clip_cache_blob" not in metadata
        assert "vector_parse_clip_cache_path" not in metadata

    def test_preview_registers_worker_vector_parse_clip_cache_path(
        self,
    ) -> None:
        """Worker-owned vector cache artifacts should be adopted by the session."""
        buf = _make_test_image_buf()

        fd, png_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        Image.fromarray(_mock_preview_img).save(png_path)
        fd, cache_path = tempfile.mkstemp(suffix=".pkl")
        os.close(fd)
        with open(cache_path, "wb") as handle:
            pickle.dump(
                {
                    **dict(_mock_cache),
                    "vector_parse_clip_cache_provenance": "b" * 64,
                },
                handle,
            )
        fd, vector_cache_path = tempfile.mkstemp(suffix=".pkl")
        os.close(fd)
        with open(vector_cache_path, "wb") as handle:
            handle.write(b"worker-owned-parse-clip-cache")

        _mock_pool.submit = AsyncMock(
            return_value={
                "status_msg": "Preview OK",
                "preview_png_path": png_path,
                "cache_data_path": cache_path,
                "vector_parse_clip_cache_path": vector_cache_path,
            }
        )

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )

        assert response.status_code == 200, response.text
        session_data = _test_store.get(response.json()["session_id"])
        assert session_data is not None
        metadata = session_data["preview_cache"]["metadata"]
        assert metadata["vector_parse_clip_cache_path"] == vector_cache_path
        assert metadata["vector_parse_clip_cache_provenance"] == "b" * 64
        with open(vector_cache_path, "rb") as handle:
            assert handle.read() == b"worker-owned-parse-clip-cache"

    def test_preview_binds_session_id_before_worker_submit_and_reuses_it(self) -> None:
        """Worker submit should see the same session_id returned by preview."""
        from api.structured_logging import get_session_id

        buf = _make_test_image_buf()
        worker_result = _create_worker_result_files()
        captured: dict[str, str | None] = {}

        async def _submit(*_args: object, **_kwargs: object) -> dict:
            captured["session_id"] = get_session_id()
            return worker_result

        _mock_pool.submit = AsyncMock(side_effect=_submit)

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )

        assert response.status_code == 200
        assert captured["session_id"] == response.json()["session_id"]

    def test_color_card_preview_preserves_source_palette(self) -> None:
        buf = _make_test_image_buf()
        worker_result = _create_worker_result_files()

        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                    "modeling_mode": "color-card",
                },
            )

        assert response.status_code == 200
        body = response.json()
        session_data = _test_store.get(body["session_id"])
        assert session_data is not None
        cache = hydrate_preview_cache(session_data["preview_cache"])

        cached_hex = {entry["hex"].lower() for entry in cache["color_palette"]}
        source_hex = {
            entry["hex"].lower()
            for entry in cache["color_card_source_palette"]
        }
        response_hex = {entry["matched_hex"].lower() for entry in body["palette"]}
        white_pixels = np.all(cache["matched_rgb"] == [255, 255, 255], axis=-1)

        assert source_hex == {"#00ff00", "#ff0000"}
        assert cached_hex == source_hex
        assert response_hex == source_hex
        assert "#ffffff" not in cached_hex
        assert bool(white_pixels.any())

    def test_preview_passes_model_assisted_controls_to_worker(self) -> None:
        """Preview route should forward model-assisted matching controls to the worker."""
        buf = _make_test_image_buf()
        worker_result = _create_worker_result_files()

        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with (
            patch(
                "api.routers.converter.preview.LUTManager.resolve_source_selection",
                return_value=("/tmp/fake.msgpack", "Native Bundle"),
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "source_kind": "native_bundle",
                    "material_type": "PLA",
                    "vendor": "BambuLab",
                    "db_names": "RYBW_008_5L.json",
                    "replacement_regions": json.dumps(
                        [
                            {
                                "quantized_hex": "#111111",
                                "matched_hex": "#111111",
                                "replacement_hex": "#222222",
                            },
                        ],
                    ),
                    "model_enable": "true",
                    "model_only": "false",
                    "model_threshold": "6.5",
                    "model_margin": "0.9",
                },
            )

        assert response.status_code == 200
        call_args = _mock_pool.submit.call_args.args
        submitted = dict(
            zip(inspect.signature(worker_generate_preview).parameters, call_args[1:])
        )
        assert submitted["svg_pixels_per_mm"] == 10.0
        assert submitted["model_enable"] is True
        assert submitted["model_only"] is False
        assert submitted["model_threshold"] == 6.5
        assert submitted["model_margin"] == 0.9
        assert submitted["replacement_regions"] == [
            {
                "quantized_hex": "#111111",
                "matched_hex": "#111111",
                "replacement_hex": "#222222",
            },
        ]
        session_data = _test_store.get(response.json()["session_id"])
        assert session_data is not None
        assert session_data["replacement_regions"] == [
            {
                "quantized_hex": "#111111",
                "matched_hex": "#111111",
                "replacement_hex": "#222222",
            },
        ]


# =========================================================================
# 3. Response includes palette and dimensions - Requirement 5.3
# =========================================================================


class TestResponseContainsPaletteAndDimensions:
    """Verify response JSON includes palette and dimensions fields."""

    def test_preview_response_has_palette_and_dimensions(self) -> None:
        """Mock worker pool submit, verify palette and dimensions in response."""
        buf = _make_test_image_buf()
        worker_result = _create_worker_result_files()

        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )
        assert response.status_code == 200
        body = response.json()

        # palette — new format with quantized_hex, matched_hex, pixel_count, percentage
        assert "palette" in body
        assert isinstance(body["palette"], list)
        assert len(body["palette"]) == 2
        hex_values = {e["matched_hex"] for e in body["palette"]}
        assert "#00ff00" in hex_values
        assert "#ff0000" in hex_values
        for entry in body["palette"]:
            assert "quantized_hex" in entry
            assert "matched_hex" in entry
            assert "pixel_count" in entry
            assert "percentage" in entry

        # preview_glb_url — None when generate_segmented_glb returns None
        assert "preview_glb_url" in body
        assert body["preview_glb_url"] is None

        # dimensions
        assert "dimensions" in body
        assert body["dimensions"]["width"] == 120
        assert body["dimensions"]["height"] == 80
        assert body["warnings"] == []

    def test_preview_logs_aggregate_preview_cache_memory_profile(
        self, monkeypatch
    ) -> None:
        """Preview should emit one aggregate cache-memory profile at DEBUG."""
        monkeypatch.delenv("LUMINA_PREVIEW_CACHE_MEMORY_PROFILE_INFO", raising=False)
        buf = _make_test_image_buf()
        worker_result = _create_worker_result_files()
        logger_mock = MagicMock()

        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
            patch("api.routers.converter.preview.log", logger_mock),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )

        assert response.status_code == 200
        debug_profiles = [
            call.kwargs["extra"]
            for call in logger_mock.debug.call_args_list
            if call.kwargs.get("extra", {}).get("event")
            == "preview_cache_memory_profile"
        ]
        info_profiles = [
            call.kwargs["extra"]
            for call in logger_mock.info.call_args_list
            if call.kwargs.get("extra", {}).get("event")
            == "preview_cache_memory_profile"
        ]

        assert len(debug_profiles) == 1
        assert info_profiles == []
        profile = debug_profiles[0]
        assert profile["session_id"] == response.json()["session_id"]
        assert profile["modeling_mode"] == "high-fidelity"
        assert profile["array_count"] == 3
        assert profile["array_total_bytes"] == 67200
        assert profile["cache_data_bytes"] > 0
        assert profile["largest_arrays"][0]["field"] in {
            "matched_rgb",
            "quantized_image",
        }

    def test_preview_rejects_estimated_cache_over_limit_before_worker(
        self, monkeypatch
    ) -> None:
        """Preview should reject pathological cache sizes before worker submit."""
        monkeypatch.setenv("LUMINA_PREVIEW_CACHE_MAX_BYTES", "1024")
        buf = _make_test_image_buf()
        _mock_pool.submit = AsyncMock(return_value=_create_worker_result_files())

        with patch(
            "api.routers.converter.preview.LUTManager.get_lut_path",
            return_value="/tmp/fake.npy",
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "target_width_mm": "200",
                    "color_mode": "4-Color",
                    "color_layers": "5",
                },
            )

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["error"] == "preview_cache_size_limit_exceeded"
        assert detail["estimate_bytes"] > detail["max_bytes"]
        assert detail["estimated_width"] == 2000
        assert detail["estimated_height"] == 2000
        _mock_pool.submit.assert_not_called()

    def test_preview_schedules_segmented_glb_asynchronously(self) -> None:
        """Preview should return after PNG/cache work and schedule GLB async."""
        buf = _make_test_image_buf()
        worker_result = _create_worker_result_files()

        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.schedule_glb_build",
                return_value="job-token",
            ) as mock_schedule,
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["preview_glb_url"] is None
        mock_schedule.assert_called_once()
        session_id, store, registry, cache = mock_schedule.call_args.args
        assert session_id == body["session_id"]
        assert store is _test_store
        assert registry is _test_registry
        assert is_preview_cache_artifact_ref(cache)
        assert cache["metadata"]["target_w"] == 120
        assert cache["metadata"]["target_h"] == 80
        assert "matched_rgb" in cache["fields"]
        assert "mask_solid" in cache["fields"]


class TestSvgLargeFormatWarnings:
    """Verify preview records SVG native large-format compatibility warnings."""

    def test_preview_returns_and_stores_svg_large_format_warnings(
        self,
        tmp_path: Path,
    ) -> None:
        worker_result = _create_worker_result_files()
        _mock_pool.submit = AsyncMock(return_value=worker_result)
        lut_path = tmp_path / "test-lut.npy"
        np.save(lut_path, np.zeros((1, 3), dtype=np.uint8))

        svg_bytes = io.BytesIO(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">'
                '<text x="10" y="30">Risky text</text>'
                '<rect x="0" y="40" width="120" height="40" fill="#ff0000"/>'
                "</svg>"
            ).encode("utf-8")
        )

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value=str(lut_path),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("risky.svg", svg_bytes, "image/svg+xml")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                    "modeling_mode": "vector",
                },
            )

        assert response.status_code == 200
        submitted_source = _mock_pool.submit.call_args.args[1]
        body = response.json()
        assert "warnings" in body
        assert any("native vector large-format" in warning.lower() for warning in body["warnings"])
        assert any("text" in warning.lower() for warning in body["warnings"])

        session_data = _test_store.get(body["session_id"])
        assert session_data is not None
        assert session_data["source_basename"] == "risky"
        policy = session_data["svg_large_format_policy"]
        assert policy["native_tiling_supported"] is False
        assert policy["inspection_source"] == "preview-vector-svg"
        assert any("text" in warning.lower() for warning in policy["warnings"])

    def test_preview_does_not_store_synthetic_svg_policy_for_non_vector_mode(self) -> None:
        worker_result = _create_worker_result_files()
        _mock_pool.submit = AsyncMock(return_value=worker_result)

        svg_bytes = io.BytesIO(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">'
                '<text x="10" y="30">Risky text</text>'
                '<rect x="0" y="40" width="120" height="40" fill="#ff0000"/>'
                "</svg>"
            ).encode("utf-8")
        )

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("risky.svg", svg_bytes, "image/svg+xml")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                    "modeling_mode": "high-fidelity",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["warnings"] == []

        session_data = _test_store.get(body["session_id"])
        assert session_data is not None
        assert session_data["source_basename"] == "risky"
        assert session_data.get("svg_large_format_policy") is None

    def test_preview_normalizes_windows_style_upload_names_for_source_basename(self) -> None:
        worker_result = _create_worker_result_files()
        _mock_pool.submit = AsyncMock(return_value=worker_result)

        svg_bytes = io.BytesIO(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">'
                '<rect x="0" y="0" width="120" height="80" fill="#ff0000"/>'
                "</svg>"
            ).encode("utf-8")
        )

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": (r"C:\\art\\poster.svg", svg_bytes, "image/svg+xml")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                    "modeling_mode": "vector",
                },
            )

        assert response.status_code == 200
        session_data = _test_store.get(response.json()["session_id"])
        assert session_data is not None
        assert session_data["source_basename"] == "poster"

    def test_preview_source_basename_uses_tempfile_fallback_when_upload_name_is_blank(self) -> None:
        assert _resolve_upload_source_basename("", "/tmp/tmpabcd1234_poster.png") == "poster"

    def test_preview_endpoint_uses_tempfile_basename_when_upload_filename_is_blank(self) -> None:
        worker_result = _create_worker_result_files()
        pool = MagicMock(spec=WorkerPoolManager)
        pool.submit = AsyncMock(return_value=worker_result)
        pool.submit_timed = AsyncMock(return_value=(worker_result, {}))

        upload = UploadFile(filename="", file=_make_test_image_buf())

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/tmpabcd1234_poster.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            result = asyncio.run(
                convert_preview(
                    image=upload,
                    source_kind="legacy_single",
                    lut_name="test_lut",
                    material_type=None,
                    vendor=None,
                    db_names=None,
                    target_width_mm=60.0,
                    color_mode="4-Color",
                    modeling_mode="high-fidelity",
                    color_layers=None,
                    layer_height_mm=None,
                    quantize_colors=48,
                    enable_cleanup=True,
                    svg_pixels_per_mm=10.0,
                    model_enable=False,
                    model_only=False,
                    model_threshold=None,
                    model_margin=None,
                    hue_weight=0.0,
                    chroma_gate=15.0,
                    is_dark=True,
                    material_source="lut",
                    surface_model_file_id=None,
                    surface_selection_json=None,
                    surface_footprint_json=None,
                    surface_placement_json=None,
                    surface_model_transform_json=None,
                    store=_test_store,
                    registry=_test_registry,
                    pool=pool,
                )
            )

        session_data = _test_store.get(result.session_id)
        assert session_data is not None
        assert session_data["source_basename"] == "poster"

    def test_preview_sanitizes_unsafe_upload_basename_characters(self) -> None:
        worker_result = _create_worker_result_files()
        _mock_pool.submit = AsyncMock(return_value=worker_result)

        svg_bytes = io.BytesIO(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">'
                '<rect x="0" y="0" width="120" height="80" fill="#ff0000"/>'
                "</svg>"
            ).encode("utf-8")
        )

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": (r"C:\\art\\bad:name*.svg", svg_bytes, "image/svg+xml")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                    "modeling_mode": "vector",
                },
            )

        assert response.status_code == 200
        session_data = _test_store.get(response.json()["session_id"])
        assert session_data is not None
        assert session_data["source_basename"] == "bad_name"


# =========================================================================
# 4. Timeout returns HTTP 504 - Requirement 2.3
# =========================================================================


class TestTimeoutReturns504:
    """Verify asyncio.TimeoutError from pool.submit returns HTTP 504."""



# =========================================================================
# 5. General exception returns HTTP 500 - Requirement 1.4
# =========================================================================


class TestGeneralExceptionReturns500:
    """Verify general Exception from pool.submit returns HTTP 500."""

    @pytest.mark.parametrize("source_type", ["png", "svg"])
    def test_preview_preserves_source_and_publishes_once(
        self, source_type: str, tmp_path: Path,
    ) -> None:
        """PNG and native SVG inputs reach the worker unchanged."""
        source = tmp_path / f"original.{source_type}"
        if source_type == "png":
            source.write_bytes(_make_test_image_buf().getvalue())
        else:
            source.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">'
                '<rect width="120" height="80" fill="#ff0000"/></svg>',
                encoding="utf-8",
            )
        original_bytes = source.read_bytes()
        worker_result = _create_worker_result_files()
        calls: list[tuple[object, ...]] = []

        async def successful_preview(*args: object) -> dict:
            calls.append(args)
            assert Path(str(args[1])).read_bytes() == original_bytes
            return worker_result

        _mock_pool.submit = AsyncMock(side_effect=successful_preview)
        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value=str(source)),
            ),
            patch("api.routers.converter.preview.schedule_glb_build"),
            patch.object(_test_store, "create", wraps=_test_store.create) as create,
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": (source.name, original_bytes)},
                data={
                    "lut_name": "test_lut", "color_mode": "4-Color",
                    "modeling_mode": "vector" if source_type == "svg" else "high-fidelity",
                    "target_width_mm": 100, "quantize_colors": 48,
                },
            )

        assert response.status_code == 200, response.text
        assert len(calls) == 1
        create.assert_called_once()
        data = response.json()
        try:
            assert _test_store.get(data["session_id"]) is not None
            assert client.get(data["preview_url"]).status_code == 200
            assert source.read_bytes() == original_bytes
        finally:
            _test_registry.cleanup_session(data["session_id"])
            _test_store.close(data["session_id"])

    def test_preview_exception_returns_500(self) -> None:
        """Simulate pool.submit raising RuntimeError, expect 500."""
        buf = _make_test_image_buf()
        private_path = "/Users/min/private/preview-source.png"
        _mock_pool.submit = AsyncMock(
            side_effect=RuntimeError(f"Worker crashed reading {private_path}")
        )

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch("api.routers.converter.preview.log.exception") as log_exception,
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )
        assert response.status_code == 500
        assert response.json()["detail"] == (
            "Preview generation failed. Re-run preview and try again."
        )
        assert private_path not in response.text
        assert "Worker crashed" not in response.text
        assert _mock_pool.submit.await_count == 1
        log_exception.assert_called_once()
        log_extra = log_exception.call_args.kwargs["extra"]
        assert log_extra["error_type"] == "RuntimeError"
        assert log_extra["error_message"] == response.json()["detail"]
        assert private_path not in log_extra["error_message"]

    def test_preview_worker_crash_returns_503_without_replay(
        self, tmp_path: Path,
    ) -> None:
        buf = _make_test_image_buf()
        source = tmp_path / "uploaded.png"
        source.write_bytes(buf.getvalue())
        _mock_pool.submit = AsyncMock(
            side_effect=BrokenProcessPool("worker was killed")
        )

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value=str(source)),
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={"lut_name": "test_lut", "color_mode": "4-Color"},
            )

        assert response.status_code == 503
        assert _mock_pool.submit.await_count == 1
        assert not source.exists()
        assert response.json()["detail"] == (
            "Preview generation failed. Re-run preview and try again."
        )

    def test_preview_vector_source_mismatch_returns_actionable_422(self) -> None:
        """Known VECTOR + raster validation errors must remain user-visible."""
        buf = _make_test_image_buf()
        _mock_pool.submit = AsyncMock(
            side_effect=RuntimeError(VECTOR_NATIVE_REQUIRES_SVG_DETAIL)
        )

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                    "modeling_mode": "vector",
                },
            )

        assert response.status_code == 422
        assert response.json()["detail"] == {
            "error": "vector_native_requires_svg",
            "message": VECTOR_NATIVE_REQUIRES_SVG_DETAIL,
        }


    @pytest.mark.parametrize(
        ("diagnostic", "modeling_mode"),
        [
            (
                "⚠️ Vector Native mode requires SVG files! near match",
                "vector",
            ),
            (VECTOR_NATIVE_REQUIRES_SVG_DETAIL, "high-fidelity"),
        ],
    )
    def test_preview_vector_source_mismatch_allowlist_keeps_other_failures_internal(
        self,
        diagnostic: str,
        modeling_mode: str,
    ) -> None:
        buf = _make_test_image_buf()
        _mock_pool.submit = AsyncMock(side_effect=RuntimeError(diagnostic))

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                    "modeling_mode": modeling_mode,
                },
            )

        assert response.status_code == 500
        assert response.json()["detail"] == (
            "Preview generation failed. Re-run preview and try again."
        )

    @pytest.mark.parametrize(
        ("diagnostic", "expected_error"),
        [
            (
                "[VECTOR_PREVIEW] No valid shapes found in SVG",
                "source_svg_no_renderable_geometry",
            ),
            (
                "[VECTOR_PREVIEW] No valid filled shapes found in SVG.",
                "source_svg_no_renderable_geometry",
            ),
        ],
    )
    def test_preview_known_svg_validation_returns_actionable_422(
        self,
        tmp_path: Path,
        diagnostic: str,
        expected_error: str,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        source = tmp_path / "source.svg"
        source.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>',
            encoding="utf-8",
        )
        _mock_pool.submit = AsyncMock(side_effect=RuntimeError(diagnostic))
        preview_logger = logging.getLogger("lumina.api.routers.converter.preview")
        preview_logger.addHandler(caplog.handler)
        caplog.set_level(
            logging.WARNING,
            logger="lumina.api.routers.converter.preview",
        )

        try:
            with (
                patch(
                    "api.routers.converter.preview.LUTManager.resolve_source_selection",
                    return_value=("/tmp/fake.npy", "Fake LUT"),
                ),
                patch(
                    "api.routers.converter.preview.ensure_png_tempfile",
                    new=AsyncMock(return_value=str(source)),
                ),
            ):
                response = client.post(
                    "/api/convert/preview",
                    files={"image": ("source.svg", source.read_bytes(), "image/svg+xml")},
                    data={
                        "lut_name": "test_lut",
                        "color_mode": "4-Color",
                        "modeling_mode": "vector",
                    },
                )
        finally:
            preview_logger.removeHandler(caplog.handler)

        assert response.status_code == 422
        assert response.json()["detail"]["error"] == expected_error
        assert diagnostic not in response.text
        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_preview_input_rejected"
        ]
        assert len(records) == 1
        record_fields = records[0].__dict__
        assert record_fields["reason"] == expected_error
        assert diagnostic not in repr(record_fields)

    @pytest.mark.parametrize(
        ("diagnostic", "suffix", "modeling_mode"),
        [
            (
                "[VECTOR_PREVIEW] No valid shapes found in SVG: near match",
                ".svg",
                "vector",
            ),
            (
                "[VECTOR_PREVIEW] No valid shapes found in SVG",
                ".png",
                "vector",
            ),
            (
                "[VECTOR_PREVIEW] No valid shapes found in SVG",
                ".svg",
                "high-fidelity",
            ),
        ],
    )
    def test_preview_svg_diagnostic_allowlist_does_not_reclassify_other_failures(
        self,
        tmp_path: Path,
        diagnostic: str,
        suffix: str,
        modeling_mode: str,
    ) -> None:
        source = tmp_path / f"source{suffix}"
        if suffix == ".svg":
            source.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>',
                encoding="utf-8",
            )
        else:
            Image.new("RGB", (4, 4), (0, 0, 0)).save(source)
        _mock_pool.submit = AsyncMock(side_effect=RuntimeError(diagnostic))

        with (
            patch(
                "api.routers.converter.preview.LUTManager.resolve_source_selection",
                return_value=("/tmp/fake.npy", "Fake LUT"),
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value=str(source)),
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": (source.name, source.read_bytes(), "application/octet-stream")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                    "modeling_mode": modeling_mode,
                },
            )

        assert response.status_code == 500
        assert response.json()["detail"] == (
            "Preview generation failed. Re-run preview and try again."
        )

    @pytest.mark.parametrize(
        "diagnostic",
        [
            "[VECTOR_PREVIEW] No valid shapes found in SVG",
            VECTOR_NATIVE_REQUIRES_SVG_DETAIL,
        ],
    )
    def test_preview_surface_artwork_svg_diagnostic_stays_internal_500(
        self,
        tmp_path: Path,
        diagnostic: str,
    ) -> None:
        upload = tmp_path / "upload.svg"
        surface_artwork = tmp_path / "surface-artwork.svg"
        svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"/>'
        upload.write_text(svg, encoding="utf-8")
        surface_artwork.write_text(svg, encoding="utf-8")
        _mock_pool.submit = AsyncMock(side_effect=RuntimeError(diagnostic))

        with (
            patch(
                "api.routers.converter.preview.LUTManager.resolve_source_selection",
                return_value=("/tmp/fake.npy", "Fake LUT"),
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value=str(upload)),
            ),
            patch(
                "api.routers.converter.preview.resolve_surface_preview_config",
                return_value={
                    "surface_artwork_path": str(surface_artwork),
                    "target_width_mm": 10.0,
                },
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("upload.svg", upload.read_bytes(), "image/svg+xml")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                    "modeling_mode": "vector",
                },
            )

        assert response.status_code == 500
        assert response.json()["detail"] == (
            "Preview generation failed. Re-run preview and try again."
        )

    def test_preview_missing_worker_output_uses_public_error_language(self) -> None:
        """Worker status_msg should not leak local paths when no PNG is returned."""
        buf = _make_test_image_buf()
        private_path = "/Users/min/private/preview.png"
        _mock_pool.submit = AsyncMock(
            return_value={
                "status_msg": f"cannot write {private_path}: permission denied",
                "preview_png_path": None,
                "cache_data_path": None,
            }
        )

        with (
            patch(
                "api.routers.converter.preview.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "lut_name": "test_lut",
                    "color_mode": "4-Color",
                },
            )

        assert response.status_code == 500
        assert response.json()["detail"] == (
            "Preview generation failed. Re-run preview and try again."
        )
        assert private_path not in response.text
        assert "permission denied" not in response.text


class TestConverterSourceUploadValidation:
    """Only definite failures in newly uploaded artwork become public 4xx."""

    @staticmethod
    def _post_with_persisted_source(
        source_path: Path,
        *,
        upload_name: str,
        content_type: str,
    ) -> tuple[object, MagicMock]:
        pool = MagicMock(spec=WorkerPoolManager)
        pool.submit_timed = AsyncMock(
            side_effect=RuntimeError("unexpected worker submission")
        )
        previous_pool = app.dependency_overrides.get(get_worker_pool)
        app.dependency_overrides[get_worker_pool] = lambda: pool

        try:
            with (
                patch(
                    "api.routers.converter.preview.LUTManager.resolve_source_selection",
                    return_value=("/tmp/fake.npy", "Fake LUT"),
                ),
                patch(
                    "api.routers.converter.preview.ensure_png_tempfile",
                    new=AsyncMock(return_value=str(source_path)),
                ),
                patch(
                    "api.routers.converter.preview.validate_converter_source",
                    wraps=validate_converter_source,
                ),
                patch(
                    "api.routers.converter.preview.generate_segmented_glb",
                    return_value=None,
                ),
            ):
                response = client.post(
                    "/api/convert/preview",
                    files={"image": (upload_name, b"request-body", content_type)},
                    data={
                        "lut_name": "test_lut",
                        "color_mode": "4-Color",
                        "modeling_mode": "vector" if upload_name.endswith(".svg") else "high-fidelity",
                    },
                )
        finally:
            if previous_pool is None:
                app.dependency_overrides.pop(get_worker_pool, None)
            else:
                app.dependency_overrides[get_worker_pool] = previous_pool

        if response.status_code == 200:
            session_id = response.json()["session_id"]
            _test_store.close(session_id)
            _test_registry.cleanup_session(session_id)
        return response, pool

    def test_corrupt_raster_returns_structured_422_before_worker(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        source = tmp_path / "private-upload-name.png"
        source.write_bytes(b"not-a-real-png")
        preview_logger = logging.getLogger("lumina.api.routers.converter.preview")
        preview_logger.addHandler(caplog.handler)
        caplog.set_level(
            logging.WARNING,
            logger="lumina.api.routers.converter.preview",
        )

        try:
            response, pool = self._post_with_persisted_source(
                source,
                upload_name="private-upload-name.png",
                content_type="image/png",
            )
        finally:
            preview_logger.removeHandler(caplog.handler)

        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "source_image_unreadable"
        assert "private-upload-name" not in response.text
        pool.submit_timed.assert_not_awaited()
        assert not source.exists()
        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_source_upload_rejected"
        ]
        assert len(records) == 1
        record_fields = records[0].__dict__
        assert record_fields["reason"] == "source_image_unreadable"
        assert record_fields["error_message"] == response.json()["detail"]["message"]
        assert "private-upload-name" not in repr(record_fields)
        assert "not-a-real-png" not in repr(record_fields)

    def test_truncated_jpeg_returns_structured_422_before_worker(
        self,
        tmp_path: Path,
    ) -> None:
        buffer = io.BytesIO()
        Image.new("RGB", (100, 100), (12, 34, 56)).save(buffer, format="JPEG")
        source = tmp_path / "truncated.jpg"
        source.write_bytes(buffer.getvalue()[:-10])

        response, pool = self._post_with_persisted_source(
            source,
            upload_name="truncated.jpg",
            content_type="image/jpeg",
        )

        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "source_image_unreadable"
        pool.submit_timed.assert_not_awaited()
        assert not source.exists()

    def test_generic_mime_and_raster_extension_mismatch_remain_accepted(
        self,
        tmp_path: Path,
    ) -> None:
        worker_result = _create_worker_result_files()
        _mock_pool.submit = AsyncMock(return_value=worker_result)
        image_bytes = _make_test_image_buf().getvalue()
        session_id = None

        with (
            patch(
                "api.routers.converter.preview.LUTManager.resolve_source_selection",
                return_value=("/tmp/fake.npy", "Fake LUT"),
            ),
            patch(
                "api.routers.converter.preview.validate_converter_source",
                wraps=validate_converter_source,
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
            patch("config.TEMP_DIR", str(tmp_path)),
            patch("api.routers.converter.preview.TEMP_DIR", str(tmp_path)),
        ):
            response = client.post(
                "/api/convert/preview",
                files={
                    "image": (
                        "png-content.jpg",
                        image_bytes,
                        "application/octet-stream",
                    )
                },
                data={"lut_name": "test_lut", "color_mode": "4-Color"},
            )

        try:
            assert response.status_code == 200, response.text
            session_id = response.json()["session_id"]
        finally:
            if session_id is not None:
                _test_store.close(session_id)
                _test_registry.cleanup_session(session_id)

    def test_malformed_svg_returns_structured_422_before_worker(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        source = tmp_path / "source.svg"
        source.write_text("<svg><path></svg>", encoding="utf-8")
        preview_logger = logging.getLogger("lumina.api.routers.converter.preview")
        preview_logger.addHandler(caplog.handler)
        caplog.set_level(
            logging.WARNING,
            logger="lumina.api.routers.converter.preview",
        )

        try:
            response, pool = self._post_with_persisted_source(
                source,
                upload_name="source.svg",
                content_type="image/svg+xml",
            )
        finally:
            preview_logger.removeHandler(caplog.handler)

        assert response.status_code == 422
        assert response.json()["detail"]["error"] == "source_svg_invalid"
        pool.submit_timed.assert_not_awaited()
        assert not source.exists()
        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "converter_source_upload_rejected"
        ]
        assert len(records) == 1
        record_fields = records[0].__dict__
        assert record_fields["reason"] == "source_svg_invalid"
        assert str(source) not in repr(record_fields)
        assert "<svg><path>" not in repr(record_fields)

    def test_file_open_failure_stays_internal_500(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.png"

        response, pool = self._post_with_persisted_source(
            missing,
            upload_name="missing.png",
            content_type="image/png",
        )

        assert response.status_code == 500
        assert response.json()["detail"] == (
            "Preview generation failed. Re-run preview and try again."
        )
        pool.submit_timed.assert_not_awaited()

    def test_decompression_bomb_returns_structured_413(
        self,
        tmp_path: Path,
    ) -> None:
        source = tmp_path / "source.png"
        source.write_bytes(b"opened-before-pillow")

        with patch(
            "api.routers.converter.source_validation.Image.open",
            side_effect=Image.DecompressionBombError("private diagnostic"),
        ):
            response, pool = self._post_with_persisted_source(
                source,
                upload_name="source.png",
                content_type="image/png",
            )

        assert response.status_code == 413
        assert response.json()["detail"]["error"] == "source_image_too_large"
        assert "private diagnostic" not in response.text
        pool.submit_timed.assert_not_awaited()
        assert not source.exists()


class TestNativeBundleValidation:
    """Verify preview parsing rejects invalid native-bundle selections."""

    def test_preview_rejects_native_bundle_db_names_outside_brand(self) -> None:
        buf = _make_test_image_buf()
        worker_result = _create_worker_result_files()
        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with (
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "source_kind": "native_bundle",
                    "material_type": "PLA",
                    "vendor": "BambuLab",
                    "db_names": "definitely-not-a-real-db",
                },
            )

        assert response.status_code == 422
        assert "native" in str(response.json()["detail"]).lower()

    def test_preview_returns_public_error_for_invalid_native_bundle_contract(self) -> None:
        buf = _make_test_image_buf()

        response = client.post(
            "/api/convert/preview",
            files={"image": ("test.png", buf, "image/png")},
            data={
                "source_kind": "native_bundle",
                "material_type": "PLA",
                "db_names": "RYBW_008_5L.json",
            },
        )

        assert response.status_code == 422
        assert response.json()["detail"] == (
            "Choose a valid LUT or complete native material source, then try again."
        )
        assert "native_bundle requires" not in response.text
        assert '"input"' not in response.text
        assert '"ctx"' not in response.text
        assert "pydantic.dev" not in response.text


class TestNativeBundleDbNamesParsing:
    """Verify preview parsing accepts all supported native DB name shapes."""

    def test_preview_accepts_plain_string_db_name(self) -> None:
        buf = _make_test_image_buf()
        worker_result = _create_worker_result_files()
        _mock_pool.submit = AsyncMock(return_value=worker_result)

        def _resolve_source_selection(*, source_kind, lut_name, material_type, vendor, db_names):
            assert source_kind == "native_bundle"
            assert material_type == "PLA"
            assert vendor == "BambuLab"
            assert db_names == ["RYBW_008_5L.json"]
            return "/tmp/fake.npy", "Native Bundle"

        with (
            patch(
                "api.routers.converter.preview.LUTManager.resolve_source_selection",
                side_effect=_resolve_source_selection,
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "source_kind": "native_bundle",
                    "material_type": "PLA",
                    "vendor": "BambuLab",
                    "db_names": "RYBW_008_5L.json",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"

    def test_preview_accepts_json_stringified_db_names(self) -> None:
        buf = _make_test_image_buf()
        worker_result = _create_worker_result_files()
        _mock_pool.submit = AsyncMock(return_value=worker_result)

        def _resolve_source_selection(*, source_kind, lut_name, material_type, vendor, db_names):
            assert source_kind == "native_bundle"
            assert material_type == "PLA"
            assert vendor == "BambuLab"
            assert db_names == ["RYBW_008_5L.json"]
            return "/tmp/fake.npy", "Native Bundle"

        with (
            patch(
                "api.routers.converter.preview.LUTManager.resolve_source_selection",
                side_effect=_resolve_source_selection,
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files={"image": ("test.png", buf, "image/png")},
                data={
                    "source_kind": "native_bundle",
                    "material_type": "PLA",
                    "vendor": "BambuLab",
                    "db_names": json.dumps(["RYBW_008_5L.json"]),
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"

    def test_preview_accepts_repeated_form_field_db_names(self) -> None:
        buf = _make_test_image_buf()
        worker_result = _create_worker_result_files()
        _mock_pool.submit = AsyncMock(return_value=worker_result)

        def _resolve_source_selection(*, source_kind, lut_name, material_type, vendor, db_names):
            assert source_kind == "native_bundle"
            assert material_type == "PLA"
            assert vendor == "BambuLab"
            assert db_names == ["RYBW_008_5L.json", "CMYW_008_5L.json"]
            return "/tmp/fake.npy", "Native Bundle"

        with (
            patch(
                "api.routers.converter.preview.LUTManager.resolve_source_selection",
                side_effect=_resolve_source_selection,
            ),
            patch(
                "api.routers.converter.preview.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.preview.generate_segmented_glb",
                return_value=None,
            ),
        ):
            response = client.post(
                "/api/convert/preview",
                files=[
                    ("image", ("test.png", buf, "image/png")),
                    ("source_kind", (None, "native_bundle")),
                    ("material_type", (None, "PLA")),
                    ("vendor", (None, "BambuLab")),
                    ("db_names", (None, "RYBW_008_5L.json")),
                    ("db_names", (None, "CMYW_008_5L.json")),
                ],
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"


class TestNativeBundleCleanup:
    """Verify temp native-bundle artifacts are cleaned up before a session exists."""

    def test_preview_upload_failure_cleans_up_temp_native_bundle_file(self) -> None:
        local_client = TestClient(app, raise_server_exceptions=False)
        buf = _make_test_image_buf()
        fd, temp_bundle_path = tempfile.mkstemp(suffix=".msgpack", dir=TEMP_DIR)
        os.close(fd)

        try:
            with (
                patch(
                    "api.routers.converter.preview.LUTManager.resolve_source_selection",
                    return_value=(temp_bundle_path, "Native Bundle"),
                ),
                patch(
                    "api.routers.converter.preview.ensure_png_tempfile",
                    new=AsyncMock(side_effect=Exception("upload failed")),
                ),
            ):
                response = local_client.post(
                    "/api/convert/preview",
                    files={"image": ("test.png", buf, "image/png")},
                    data={
                        "source_kind": "native_bundle",
                        "material_type": "PLA",
                        "vendor": "BambuLab",
                        "db_names": "RYBW_008_5L.json",
                    },
                )

            assert response.status_code == 500
            assert not os.path.exists(temp_bundle_path)
        finally:
            if os.path.exists(temp_bundle_path):
                os.unlink(temp_bundle_path)



class TestParseSelectedMaterials:
    """Regression tests for the _parse_selected_materials helper.

    The frontend sends selected_materials as a JSON-stringified array, which
    FastAPI wraps in a list-of-one-string before the endpoint sees it. This
    helper must unwrap both plain strings and that list shape.
    """

    def test_none_returns_empty(self):
        assert _parse_selected_materials(None) == []

    def test_empty_string_returns_empty(self):
        assert _parse_selected_materials("") == []

    def test_json_stringified_array(self):
        """Direct JSON string (e.g. '["a","b"]') is parsed."""
        assert _parse_selected_materials('["mat1","mat2"]') == ["mat1", "mat2"]

    def test_list_with_one_json_string_item(self):
        """FastAPI form-coercion often wraps the JSON string in a list."""
        assert _parse_selected_materials(['["mat1","mat2"]']) == ["mat1", "mat2"]

    def test_plain_list_of_strings(self):
        """Repeated form fields arrive as a regular list."""
        assert _parse_selected_materials(["mat1", "mat2"]) == ["mat1", "mat2"]

    def test_comma_separated_string(self):
        """Fallback for legacy comma-joined inputs."""
        assert _parse_selected_materials("mat1, mat2") == ["mat1", "mat2"]

    def test_unicode_material_names(self):
        """Chinese material directory names round-trip correctly."""
        value = json.dumps(["瑞贝思 PLA 红", "瑞贝思 PLA 黄"])
        assert _parse_selected_materials([value]) == [
            "瑞贝思 PLA 红",
            "瑞贝思 PLA 黄",
        ]

    def test_malformed_json_falls_back_to_string(self):
        """Invalid JSON is treated as a single literal name."""
        assert _parse_selected_materials("[not-json") == ["[not-json"]


class TestLargeFormatSvgPreviewCacheSizing:
    """Regression coverage for tall SVG + material archive preview guard."""
