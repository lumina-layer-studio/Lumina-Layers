"""Unit tests for Converter Batch endpoint integration.

Validates:
- LUT name resolution failure returns 404 (Requirement 9)
- Partial failure continues processing remaining images (Requirement 9.3)
- All images succeed returns correct BatchResponse (Requirement 9.1, 9.2)
- Empty successful results returns null download/preview paths (Requirement 9.3)
- asyncio.TimeoutError from pool.submit returns timeout error in results (Requirement 2.3)
- General Exception from pool.submit returns HTTP 500 error in results (Requirement 1.4)
- Batch merge flow: all-success-fits, all-success-overflows, partial-failure,
  all-failure, writer-fail-5xx (Requirements 1.1, 1.4, 4.1-4.3, 4.6-4.7,
  6.1-6.4, 9.4, 10.4; Properties P11, P12)
"""

from __future__ import annotations

import asyncio
from concurrent.futures.process import BrokenProcessPool
import io
import inspect
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager
from utils.merged_bambu_3mf_writer import MergedWriteError

_test_store: SessionStore = SessionStore(ttl=1800)
_test_registry: FileRegistry = FileRegistry()


@pytest.fixture(autouse=True)
def native_selection_for_worker_orchestration(monkeypatch):
    """These worker tests use fake LUT/archive paths, not native profile fixtures."""
    monkeypatch.setattr(
        "api.routers.converter.generate.require_material_selection",
        lambda *args, **kwargs: {"ready": True, "materials": []},
    )


class _PreviewRegistrationFailingRegistry(FileRegistry):
    """FileRegistry that accepts the merged 3MF and rejects preview GLBs."""

    def __init__(self) -> None:
        super().__init__()
        self.download_id: str | None = None
        self.download_path: str | None = None
        self.preview_path: str | None = None

    def register_path(
        self,
        session_id: str,
        path: str,
        filename: str | None = None,
        ttl_seconds: int | None = None,
        is_public: bool = True,
        purpose: str | None = None,
    ) -> str:
        if filename == "batch.3mf":
            file_id = super().register_path(
                session_id=session_id,
                path=path,
                filename=filename,
                ttl_seconds=ttl_seconds,
                is_public=is_public,
                purpose=purpose,
            )
            self.download_id = file_id
            self.download_path = path
            return file_id
        if filename and filename.endswith(".glb"):
            self.preview_path = path
            raise RuntimeError("preview registry unavailable")
        return super().register_path(
            session_id=session_id,
            path=path,
            filename=filename,
            ttl_seconds=ttl_seconds,
            is_public=is_public,
            purpose=purpose,
        )


class _MockWorkerPool:
    """Mock WorkerPoolManager that delegates submit to a configurable side_effect.
    模拟 WorkerPoolManager，将 submit 委托给可配置的 side_effect。
    """

    def __init__(self) -> None:
        self.submit = AsyncMock()

    @property
    def is_alive(self) -> bool:
        return True

    @property
    def max_workers(self) -> int:
        return 2


_mock_pool = _MockWorkerPool()


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


def _make_test_image_buf(name: str = "test.png") -> tuple[str, io.BytesIO, str]:
    """Create a minimal PNG image upload tuple (filename, buf, content_type)."""
    img = Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return (name, buf, "image/png")


def _make_fake_3mf(suffix: str = ".3mf") -> str:
    """Create a temporary fake 3MF file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.write(fd, b"fake-3mf-content")
    os.close(fd)
    return path


# =========================================================================
# 1. LUT not found returns 404 - Requirement 9
# =========================================================================


class TestBatchLutNotFound:
    """Verify unresolvable lut_name returns HTTP 404."""

    def test_batch_missing_lut_name_returns_public_source_selection_error(self) -> None:
        _mock_pool.submit = AsyncMock()

        response = client.post(
            "/api/convert/batch",
            files=[("images", _make_test_image_buf("a.png"))],
            data={"source_kind": "legacy_single"},
        )

        assert response.status_code == 422
        assert response.json()["detail"] == (
            "Choose a valid LUT or complete native material source, then try again."
        )
        assert "legacy_single requires lut_name" not in response.text
        assert '"input"' not in response.text
        assert '"ctx"' not in response.text
        assert "pydantic.dev" not in response.text
        _mock_pool.submit.assert_not_called()

    def test_batch_unknown_lut_returns_404(self) -> None:
        with patch(
            "api.routers.converter.generate.LUTManager.get_lut_path",
            return_value=None,
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("a.png"))],
                data={"lut_name": "nonexistent_lut"},
            )
        assert response.status_code == 404
        assert "LUT" in response.json()["detail"]


class TestBatchMaterialSourceValidation:
    """Verify batch rejects unsupported material source values early."""

    def test_batch_rejects_invalid_material_source_before_io(self) -> None:
        """Invalid material_source should not resolve LUTs, upload, or submit work."""
        _mock_pool.submit = AsyncMock(
            return_value=_make_worker_result("invalid-source.png", 30.0, 20.0),
        )

        with (
            patch(
                "api.routers.converter.generate.LUTManager.resolve_source_selection",
                return_value=("/tmp/fake.npy", "Fake LUT"),
            ) as resolve_source,
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new_callable=AsyncMock,
                return_value="/tmp/uploaded.png",
            ) as ensure_png,
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                _noop_3mf_write,
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("invalid-source.png"))],
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


class TestBatchColorCardRejected:
    def test_batch_rejects_color_card_mode(self) -> None:
        _mock_pool.submit = AsyncMock()

        with patch(
            "api.routers.converter.generate.LUTManager.get_lut_path",
            return_value="/tmp/fake.npy",
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("a.png"))],
                data={"lut_name": "test_lut", "modeling_mode": "color-card"},
            )

        assert response.status_code == 422
        assert "color-card" in response.json()["detail"]
        _mock_pool.submit.assert_not_called()


# =========================================================================
# 2. Partial failure continues processing - Requirement 9.3
# =========================================================================


class TestBatchPartialFailure:
    """Verify that if some images fail, remaining images still process."""

    def test_batch_partial_failure_continues(self) -> None:
        call_count = 0
        private_path = "/Users/min/private/batch-input/fail.png"
        raw_error_message = f"cannot read {private_path}: Permission denied"
        log_calls: list[tuple[str, str, dict[str, object]]] = []

        async def _mock_submit(fn, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError(raw_error_message)
            return _make_worker_result("ok.png", 30.0, 20.0)

        def _capturing_safe_log(level: str, event: str, **fields: object) -> None:
            log_calls.append((level, event, fields))

        _mock_pool.submit = AsyncMock(side_effect=_mock_submit)

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                _noop_3mf_write,
            ),
            patch(
                "api.routers.converter.generate._safe_log",
                side_effect=_capturing_safe_log,
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[
                    ("images", _make_test_image_buf("fail.png")),
                    ("images", _make_test_image_buf("ok.png")),
                ],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert len(body["results"]) == 2

        # First image failed
        assert body["results"][0]["filename"] == "fail.png"
        assert body["results"][0]["status"] == "failed"
        assert body["results"][0]["error"] == (
            "This file could not be converted. Re-upload it or check the server log for details."
        )
        assert private_path not in response.text
        assert "Permission denied" not in response.text
        failure_logs = [
            (level, fields)
            for level, event, fields in log_calls
            if event == "converter_batch_item_failed"
        ]
        assert len(failure_logs) == 1
        level, fields = failure_logs[0]
        assert level == "warning"
        assert fields["filename"] == "fail.png"
        assert fields["failure_kind"] == "worker_exception"
        assert fields["error_type"] == "RuntimeError"
        assert private_path in str(fields["error_message"])
        assert "Permission denied" in str(fields["error_message"])

        # Second image succeeded
        assert body["results"][1]["filename"] == "ok.png"
        assert body["results"][1]["status"] == "success"

        # download_url present
        assert body["download_url"].startswith("/api/files/")
        assert body["threemf_disk_path"] is None
        assert body["preview_3d_url"].startswith("/api/files/")
        assert len(body["preview_items"]) == 1
        assert body["preview_items"][0]["filename"] == "ok.png"
        assert body["preview_items"][0]["url"] == body["preview_3d_url"]
        assert body["preview_items"][0]["tx_mm"] == 160.0
        assert body["preview_items"][0]["ty_mm"] == 150.0
        assert body["preview_items"][0]["width_mm"] == 30.0
        assert body["preview_items"][0]["depth_mm"] == 20.0


# =========================================================================
# 3. All images succeed - Requirement 9.1, 9.2
# =========================================================================


@pytest.mark.parametrize("modeling_mode", ["high-fidelity", "vector"])
@pytest.mark.parametrize("source", ["lut", "material_archive", "dynamic_material"])
def test_batch_parallelism_preserves_upload_order_and_partial_success(
    tmp_path: Path, modeling_mode: str, source: str,
) -> None:
    """Separate uploads overlap within capacity and retain their result identity."""

    active = 0
    peak_active = 0
    pair_started: asyncio.Event | None = None
    completed: list[str] = []
    upload_paths: list[Path] = []
    merged_names: list[str] = []
    filenames = [f"image-{index}.png" for index in range(5)]

    async def save_upload(upload):
        path = tmp_path / upload.filename
        path.write_bytes(b"input")
        upload_paths.append(path)
        return str(path)

    async def submit_item(_fn, image_path, *_args):
        nonlocal active, peak_active, pair_started
        filename = Path(image_path).name
        index = filenames.index(filename)
        active += 1
        peak_active = max(peak_active, active)
        try:
            if index < 4:
                if pair_started is None:
                    pair_started = asyncio.Event()
                current_pair = pair_started
                if active == 2:
                    pair_started = None
                    current_pair.set()
                await asyncio.wait_for(current_pair.wait(), timeout=0.5)
                if index % 2 == 0:
                    await asyncio.sleep(0.01)
            assert Path(image_path).exists()
            completed.append(filename)
            if index == 1:
                raise RuntimeError("one image cannot be converted")
            return _make_worker_result(filename)
        finally:
            active -= 1

    def merge_items(self, items, output_path, **kwargs):
        merged_names.extend(item.source_filename for item in items)
        _noop_3mf_write(self, items, output_path, **kwargs)

    params = {"lut_name": "test_lut", "modeling_mode": modeling_mode}
    if source != "lut":
        params.update({
            "material_source": "material_archive",
            "selected_materials": json.dumps(["Red", "White"]),
            "material_backing_material_index": "1",
            "material_layer_count": "10",
            "material_dynamic_layer_count_enabled": str(source == "dynamic_material").lower(),
        })
    _mock_pool.submit = AsyncMock(side_effect=submit_item)
    with (
        patch("api.routers.converter.generate.LUTManager.get_lut_path", return_value="/tmp/fake.npy"),
        patch("api.routers.converter.generate.ensure_png_tempfile", side_effect=save_upload),
        patch("utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write", merge_items),
    ):
        response = client.post(
            "/api/convert/batch",
            files=[("images", _make_test_image_buf(name)) for name in filenames],
            data=params,
        )

    assert response.status_code == 200, response.text
    assert peak_active == _mock_pool.max_workers
    assert active == 0
    assert completed == [filenames[1], filenames[0], filenames[3], filenames[2], filenames[4]]
    body = response.json()
    assert [item["filename"] for item in body["results"]] == filenames
    assert [item["status"] for item in body["results"]] == [
        "success", "failed", "success", "success", "success",
    ]
    expected_successes = [name for name in filenames if name != filenames[1]]
    assert merged_names == expected_successes
    assert [item["filename"] for item in body["preview_items"]] == expected_successes
    assert all(not path.exists() for path in upload_paths)
    # Changing source sessions must not invalidate the completed batch download.
    sid = _test_store.create()
    _test_store.close(sid)
    _test_registry.cleanup_session(sid)
    download = client.get(body["download_url"])
    assert download.status_code == 200
    assert download.content == b"fake-merged-3mf"


@pytest.mark.parametrize("failure_kind", ["pool", "solver"])
def test_batch_fatal_failure_drains_sibling_and_cleans_its_outputs(
    tmp_path: Path, failure_kind: str,
) -> None:
    from core.material_dynamic_solver import DynamicMaterialSolverError

    sibling_outputs: list[str] = []
    upload_paths: list[Path] = []

    async def save_upload(upload):
        path = tmp_path / upload.filename
        path.write_bytes(b"input")
        upload_paths.append(path)
        return str(path)

    async def submit_item(_fn, image_path, *_args):
        if Path(image_path).name == "fail.png":
            if failure_kind == "pool":
                raise BrokenProcessPool("worker was killed")
            raise DynamicMaterialSolverError("solver unavailable")
        await asyncio.sleep(0.01)
        result = _make_worker_result("sibling.png")
        sibling_outputs.extend(result[key] for key in (
            "threemf_path", "preview_glb_path", "metadata_sidecar_path",
        ))
        return result

    _mock_pool.submit = AsyncMock(side_effect=submit_item)
    with (
        patch("api.routers.converter.generate.LUTManager.get_lut_path", return_value="/tmp/fake.npy"),
        patch("api.routers.converter.generate.ensure_png_tempfile", side_effect=save_upload),
        patch("utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write") as merge,
    ):
        response = client.post(
            "/api/convert/batch",
            files=[("images", _make_test_image_buf(name)) for name in (
                "fail.png", "sibling.png", "later-1.png", "later-2.png",
            )],
            data={"lut_name": "test_lut"},
        )

    assert response.status_code == 503, response.text
    assert _mock_pool.submit.await_count == 2
    assert len(sibling_outputs) == 3
    assert all(not Path(path).exists() for path in sibling_outputs)
    assert all(not path.exists() for path in upload_paths)
    merge.assert_not_called()


@pytest.mark.asyncio
async def test_batch_cancellation_keeps_shared_lut_until_workers_finish(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from api.routers.converter import generate as generate_router

    shared_lut = tmp_path / "native-bundle.msgpack"
    shared_lut.write_bytes(b"shared LUT")
    upload_paths: list[Path] = []
    output_paths: list[str] = []
    active = 0
    started = asyncio.Event()
    release = asyncio.Event()

    async def save_upload(upload):
        path = tmp_path / upload.filename
        path.write_bytes(b"input")
        upload_paths.append(path)
        return str(path)

    async def submit_item(_fn, image_path, lut_path, *_args):
        nonlocal active
        active += 1
        if active == 2:
            started.set()
        await release.wait()
        assert Path(image_path).exists()
        assert Path(lut_path).exists()
        result = _make_worker_result(Path(image_path).name)
        output_paths.extend(result[key] for key in (
            "threemf_path", "preview_glb_path", "metadata_sidecar_path",
        ))
        active -= 1
        return result

    _mock_pool.submit = AsyncMock(side_effect=submit_item)
    test_app = FastAPI()
    test_app.include_router(generate_router.router, prefix="/api/convert")
    test_app.dependency_overrides[get_worker_pool] = lambda: _mock_pool
    test_app.dependency_overrides[get_file_registry] = lambda: _test_registry
    with (
        patch.object(generate_router, "TEMP_DIR", str(tmp_path)),
        patch.object(generate_router.LUTManager, "resolve_source_selection", return_value=(str(shared_lut), "Native")),
        patch.object(generate_router, "ensure_png_tempfile", side_effect=save_upload),
    ):
        async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://testserver") as http:
            request = asyncio.create_task(http.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf(f"image-{i}.png")) for i in range(4)],
                data={
                    "source_kind": "native_bundle", "material_type": "PLA",
                    "vendor": "Bambu", "db_names": json.dumps(["red.cdb", "white.cdb"]),
                },
            ))
            try:
                await asyncio.wait_for(started.wait(), timeout=2.0)
                request.cancel()
                await asyncio.sleep(0)
                assert shared_lut.exists()
                assert all(path.exists() for path in upload_paths)
            finally:
                release.set()
                if not request.done() and not request.cancelling():
                    request.cancel()
                await asyncio.gather(request, return_exceptions=True)

    assert request.cancelled()
    assert _mock_pool.submit.await_count == 2
    assert active == 0
    assert len(output_paths) == 6
    assert not shared_lut.exists()
    assert all(not path.exists() for path in upload_paths)
    assert all(not Path(path).exists() for path in output_paths)


class TestBatchAllSuccess:
    """Verify all images succeed returns correct BatchResponse."""

    def test_batch_all_success(self) -> None:
        results_iter = iter(
            [
                _make_worker_result("img1.png", 30.0, 20.0),
                _make_worker_result("img2.png", 30.0, 20.0),
            ]
        )

        async def _mock_submit(fn, *args, **kwargs):
            return next(results_iter)

        _mock_pool.submit = AsyncMock(side_effect=_mock_submit)

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                _noop_3mf_write,
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[
                    ("images", _make_test_image_buf("img1.png")),
                    ("images", _make_test_image_buf("img2.png")),
                ],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "2/2" in body["message"]
        assert len(body["results"]) == 2
        assert all(r["status"] == "success" for r in body["results"])
        assert body["download_url"].startswith("/api/files/")
        assert body["threemf_disk_path"] is None
        assert body["preview_3d_url"].startswith("/api/files/")
        assert [item["filename"] for item in body["preview_items"]] == [
            "img1.png",
            "img2.png",
        ]
        assert body["preview_items"][0]["url"] == body["preview_3d_url"]
        assert body["preview_items"][0]["tx_mm"] == 144.0
        assert body["preview_items"][1]["tx_mm"] == 176.0
        assert all(item["ty_mm"] == 150.0 for item in body["preview_items"])


# =========================================================================
# 4. All images fail returns status "failed" - Requirement 9.3
# =========================================================================


class TestBatchAllFailed:
    """Verify all images failing returns status 'failed' with null artifacts."""

    def test_batch_all_fail(self) -> None:
        private_path = "/Users/min/private/batch-input/bad.png"
        _mock_pool.submit = AsyncMock(
            side_effect=RuntimeError(f"cannot read {private_path}: Permission denied"),
        )

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("bad.png"))],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert "0/1" in body["message"]
        assert body["results"][0]["status"] == "failed"
        assert body["results"][0]["error"] == (
            "This file could not be converted. Re-upload it or check the server log for details."
        )
        assert private_path not in response.text
        assert "Permission denied" not in response.text
        assert body["download_url"] is None
        assert body["threemf_disk_path"] is None
        assert body["preview_3d_url"] is None
        assert body["preview_items"] == []


    def test_batch_broken_worker_pool_stops_before_next_group(self) -> None:
        _mock_pool.submit = AsyncMock(
            side_effect=BrokenProcessPool("worker was killed")
        )

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[
                    ("images", _make_test_image_buf("complex-1.png")),
                    ("images", _make_test_image_buf("complex-2.png")),
                    ("images", _make_test_image_buf("complex-3.png")),
                    ("images", _make_test_image_buf("complex-4.png")),
                ],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 503
        assert _mock_pool.submit.await_count == _mock_pool.max_workers

    def test_batch_worker_missing_output_sanitizes_status_message(self) -> None:
        private_path = "/Users/min/private/batch-output/missing.3mf"
        log_calls: list[tuple[str, str, dict[str, object]]] = []

        def _capturing_safe_log(level: str, event: str, **fields: object) -> None:
            log_calls.append((level, event, fields))

        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": None,
                "status_msg": f"failed at {private_path}: Permission denied",
            },
        )

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.generate._safe_log",
                side_effect=_capturing_safe_log,
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("missing.png"))],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["results"][0]["status"] == "failed"
        assert body["results"][0]["error"] == (
            "This file could not be converted. Re-upload it or check the server log for details."
        )
        assert private_path not in response.text
        assert "Permission denied" not in response.text
        failure_logs = [
            (level, fields)
            for level, event, fields in log_calls
            if event == "converter_batch_item_failed"
        ]
        assert len(failure_logs) == 1
        level, fields = failure_logs[0]
        assert level == "warning"
        assert fields["filename"] == "missing.png"
        assert fields["failure_kind"] == "missing_output"
        assert fields["error_type"] == "MissingBatchOutput"
        assert private_path in str(fields["error_message"])
        assert "Permission denied" in str(fields["error_message"])


# =========================================================================
# 5. Timeout returns timeout error in batch item - Requirement 2.3
# =========================================================================


class TestBatchTimeout:
    """Verify asyncio.TimeoutError from pool.submit is handled per-item."""



# =========================================================================
# 6. Worker pool receives correct function and args - Requirement 1.2, 2.1
# =========================================================================


class TestBatchWorkerPoolSubmit:
    """Verify batch requests submit their settings to the worker pool."""

    @pytest.mark.parametrize("width", ["0.49", "10.01", "nan", "inf", "-inf", "invalid"])
    def test_batch_rejects_invalid_outline_width(self, width: str) -> None:
        _mock_pool.submit = AsyncMock()
        response = client.post(
            "/api/convert/batch",
            files=[("images", _make_test_image_buf())],
            data={"lut_name": "test_lut", "enable_outline": "true", "outline_width": width},
        )
        assert response.status_code == 422
        _mock_pool.submit.assert_not_called()

    @pytest.mark.parametrize("height", ["0.03", "0.13", "nan", "inf"])
    def test_batch_rejects_invalid_coating_height(self, height):
        _mock_pool.submit = AsyncMock()
        response = client.post(
            "/api/convert/batch",
            files=[("images", _make_test_image_buf())],
            data={"lut_name": "test_lut", "enable_coating": "true", "coating_height_mm": height},
        )
        assert response.status_code == 422
        _mock_pool.submit.assert_not_called()

    @pytest.mark.parametrize("coating_enabled", [True, False])
    @pytest.mark.parametrize("compensation_enabled", [True, False])
    def test_batch_submits_to_pool(self, coating_enabled, compensation_enabled) -> None:
        _mock_pool.submit = AsyncMock(
            return_value=_make_worker_result("test.png", 30.0, 20.0),
        )

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new_callable=AsyncMock,
                return_value="/tmp/uploaded.svg",
            ),
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                autospec=True,
                side_effect=_noop_3mf_write,
            ) as merged_write_mock,
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("test.svg"))],
                data={
                    "lut_name": "test_lut",
                    "target_width_mm": "80.0",
                    "spacer_thick": "1.4",
                    "structure_mode": "Single-sided",
                    "color_mode": "8-Color Max",
                    "modeling_mode": "vector",
                    "color_layers": "10",
                    "layer_height_mm": "0.08",
                    "quantize_colors": "64",
                    "enable_cleanup": "false",
                    "hue_weight": "0.5",
                    "chroma_gate": "12",
                    "enable_relief": "true",
                    "height_mode": "color",
                    "color_height_map": json.dumps(
                        {"#ff0000": 1.7, "#ffffff": 1.3}
                    ),
                    "heightmap_max_height": "4.2",
                    "printer_id": "bambu-p1s",
                    "slicer": "OrcaSlicer",
                    "nozzle_size": "0.2",
                    "enable_base_layer_height_modifier": "false",
                    "enable_wipe_tower_auto_placement": "false",
                    "high_precision_3d_preview": "true",
                    "enable_coating": str(coating_enabled).lower(),
                    "coating_height_mm": "0.12",
                    "svg_hole_compensation_enabled": str(compensation_enabled).lower(),
                    "svg_hole_max_area_mm2": "0.75",
                    "svg_hole_max_width_mm": "0.21",
                },
            )

        assert response.status_code == 200

        # Verify pool.submit was called once (one image)
        assert _mock_pool.submit.call_count == 1

        # Verify the first argument is the worker function
        from api.workers.converter_workers import worker_batch_convert_item

        call_args = _mock_pool.submit.call_args
        assert call_args[0][0] is worker_batch_convert_item

        # Verify file path and lut_path are passed as scalars
        assert call_args[0][1] == "/tmp/uploaded.svg"  # image_path
        assert call_args[0][2] == "/tmp/fake.npy"  # lut_path
        assert call_args[0][3] == 80.0  # target_width_mm
        assert call_args[0][4] == 1.4
        assert call_args[0][5] == "Single-sided"
        assert call_args[0][6] == "8-Color Max"
        assert call_args[0][7] == "vector"
        assert call_args[0][8] == 10
        assert call_args[0][9] == 0.08
        assert call_args[0][10] == 64
        assert call_args[0][11] is False
        # ``artifact_prefix`` is forwarded as a scalar so per-image
        # intermediate artifacts share a stable prefix (task 7/14);
        # the value is f"batch-{batch_run_id}-" where batch_run_id is a uuid4 hex.
        artifact_prefix = call_args[0][12]
        assert artifact_prefix.startswith("batch-")
        assert artifact_prefix.endswith("-")
        assert len(artifact_prefix) > len("batch--")  # has uuid content
        assert call_args[0][13] == 0.5
        assert call_args[0][14] == 12
        assert call_args[0][15] is True
        assert call_args[0][16] == "color"
        assert call_args[0][17] == {"#ff0000": 1.7, "#ffffff": 1.3}
        assert call_args[0][18] == 4.2
        assert call_args[0][20] == "bambu-p1s"
        assert call_args[0][21] == "OrcaSlicer"
        assert call_args[0][22] == "0.2"
        assert call_args[0][23] is False
        assert call_args[0][36] is True
        worker_args = inspect.signature(worker_batch_convert_item).bind(
            *call_args.args[1:]
        ).arguments
        assert worker_args["enable_wipe_tower_auto_placement"] is False
        assert (
            merged_write_mock.call_args.kwargs[
                "enable_wipe_tower_auto_placement"
            ]
            is False
        )
        expected_options = {
            "enable_coating": coating_enabled,
            "coating_height_mm": 0.12,
            "coating_material": None,
            "svg_hole_compensation_enabled": compensation_enabled,
            "svg_hole_max_area_mm2": 0.75,
            "svg_hole_max_width_mm": 0.21,
        }
        assert {key: worker_args.get(key) for key in expected_options} == expected_options

    def test_batch_submits_material_archive_source_to_worker(self) -> None:
        """Batch endpoint forwards material-archive source params to worker."""
        _mock_pool.submit = AsyncMock(
            return_value=_make_worker_result("material.png", 30.0, 20.0),
        )

        with (
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new_callable=AsyncMock,
                return_value="/tmp/uploaded.png",
            ),
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                _noop_3mf_write,
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("material.png"))],
                data={
                    "material_source": "material_archive",
                    "selected_materials": json.dumps(
                        ["brand/red", "brand/white"]
                    ),
                    "material_layer_count": "7",
                    "material_layer_height_mm": "0.06",
                    "material_grid_resolution": "33",
                    "material_backing_material_index": "1",
                    "material_dynamic_layer_count_enabled": "true",
                    "material_min_layer_count": "6",
                    "material_max_layer_count": "9",
                    "material_delta_e00_tolerance": "0.4",
                    "separate_backing": "true",
                },
            )

        assert response.status_code == 200
        call_args = _mock_pool.submit.call_args
        from api.workers.converter_workers import worker_batch_convert_item

        worker_args = inspect.signature(worker_batch_convert_item).bind(
            *call_args.args[1:]
        ).arguments
        assert worker_args["lut_path"] == "__material_archive__"
        assert worker_args["color_layers"] is None
        assert worker_args["layer_height_mm"] is None
        assert worker_args["material_source"] == "material_archive"
        assert worker_args["selected_materials"] == ["brand/red", "brand/white"]
        assert worker_args["material_layer_count"] == 7
        assert worker_args["material_layer_height_mm"] == 0.06
        assert worker_args["material_grid_resolution"] == 33
        assert worker_args["material_backing_material_index"] == 1
        assert worker_args["separate_backing"] is True
        assert worker_args["material_dynamic_layer_count_enabled"] is True
        assert worker_args["material_min_layer_count"] == 6
        assert worker_args["material_max_layer_count"] == 9
        assert worker_args["material_delta_e00_tolerance"] == 0.4

    def test_batch_submits_native_bundle_source_to_worker(self) -> None:
        """Batch endpoint resolves reverse-LUT native bundle params."""
        _mock_pool.submit = AsyncMock(
            return_value=_make_worker_result("native.png", 30.0, 20.0),
        )

        with (
            patch(
                "api.routers.converter.generate.LUTManager.resolve_source_selection",
                return_value=("/tmp/native-bundle.msgpack", "Native Bundle"),
            ) as resolve_mock,
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new_callable=AsyncMock,
                return_value="/tmp/uploaded.png",
            ),
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                _noop_3mf_write,
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("native.png"))],
                data={
                    "source_kind": "native_bundle",
                    "material_type": "PLA",
                    "vendor": "Bambu",
                    "db_names": json.dumps(["red.cdb", "white.cdb"]),
                    "color_layers": "6",
                    "layer_height_mm": "0.08",
                    "model_enable": "true",
                    "model_only": "true",
                    "model_threshold": "0.3",
                    "model_margin": "0.1",
                    "use_lut_constrained": "true",
                    "auto_dynamic_range": "true",
                },
            )

        assert response.status_code == 200
        resolve_mock.assert_called_once_with(
            source_kind="native_bundle",
            lut_name=None,
            material_type="PLA",
            vendor="Bambu",
            db_names=["red.cdb", "white.cdb"],
        )
        call_args = _mock_pool.submit.call_args
        assert call_args[0][2] == "/tmp/native-bundle.msgpack"
        assert call_args[0][8] == 6
        assert call_args[0][9] == 0.08
        assert call_args[0][24] is True
        assert call_args[0][25] is True
        assert call_args[0][26] == 0.3
        assert call_args[0][27] == 0.1
        assert call_args[0][28] == "lut"
        assert call_args[0][34] is True
        assert call_args[0][35] is True

    def test_batch_material_archive_source_reaches_worker(self) -> None:
        """Material-archive batch source forwards selected materials."""
        _mock_pool.submit = AsyncMock(
            return_value=_make_worker_result("test.png", 30.0, 20.0),
        )

        with (
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new_callable=AsyncMock,
                return_value="/tmp/uploaded.png",
            ),
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                _noop_3mf_write,
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("test.png"))],
                data={
                    "material_source": "material_archive",
                    "selected_materials": json.dumps(["brand/red", "brand/white"]),
                    "material_layer_count": "7",
                    "material_layer_height_mm": "0.06",
                    "material_grid_resolution": "128",
                    "material_backing_material_index": "1",
                    "lut_name": "__material_archive__",
                },
            )

        assert response.status_code == 200
        call_args = _mock_pool.submit.call_args
        assert call_args[0][2] == "__material_archive__"
        assert call_args[0][28] == "material_archive"
        assert call_args[0][29] == ["brand/red", "brand/white"]
        assert call_args[0][30] == 7
        assert call_args[0][31] == 0.06
        assert call_args[0][32] == 128
        assert call_args[0][33] == 1

    def test_batch_native_source_reaches_worker(self) -> None:
        """Native reverse-LUT batch source resolves and forwards model flags."""
        _mock_pool.submit = AsyncMock(
            return_value=_make_worker_result("test.png", 30.0, 20.0),
        )

        with (
            patch(
                "api.routers.converter.generate.LUTManager.resolve_source_selection",
                return_value=("/tmp/native-bundle.msgpack", "Native Bundle"),
            ) as resolve_mock,
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new_callable=AsyncMock,
                return_value="/tmp/uploaded.png",
            ),
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                _noop_3mf_write,
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("test.png"))],
                data={
                    "source_kind": "native_bundle",
                    "material_type": "PLA",
                    "vendor": "Bambu",
                    "db_names": json.dumps(["red.cdb", "white.cdb"]),
                    "model_enable": "true",
                    "model_only": "true",
                    "model_threshold": "0.3",
                    "model_margin": "0.1",
                    "use_lut_constrained": "true",
                    "auto_dynamic_range": "true",
                },
            )

        assert response.status_code == 200
        resolve_mock.assert_called_once_with(
            source_kind="native_bundle",
            lut_name=None,
            material_type="PLA",
            vendor="Bambu",
            db_names=["red.cdb", "white.cdb"],
        )
        call_args = _mock_pool.submit.call_args
        assert call_args[0][2] == "/tmp/native-bundle.msgpack"
        assert call_args[0][24] is True
        assert call_args[0][25] is True
        assert call_args[0][26] == 0.3
        assert call_args[0][27] == 0.1
        assert call_args[0][34] is True
        assert call_args[0][35] is True

    def test_batch_relief_requires_color_height_map(self) -> None:
        _mock_pool.submit = AsyncMock(
            return_value={"threemf_path": _make_fake_3mf(), "status_msg": "OK"},
        )

        with patch(
            "api.routers.converter.generate.LUTManager.get_lut_path",
            return_value="/tmp/fake.npy",
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("test.png"))],
                data={
                    "lut_name": "test_lut",
                    "enable_relief": "true",
                    "height_mode": "color",
                },
            )

        assert response.status_code == 422
        assert "color_height_map" in response.json()["detail"]
        assert _mock_pool.submit.call_count == 0

    @pytest.mark.parametrize(
        ("structure_mode", "color_mode"),
        [
            ("Double-sided", "4-Color (RYBW)"),
            ("Single-sided", "5-Color Extended"),
        ],
    )
    def test_batch_rejects_unsupported_native_vector_relief(
        self,
        structure_mode,
        color_mode,
    ) -> None:
        _mock_pool.submit = AsyncMock()

        with patch(
            "api.routers.converter.generate.LUTManager.get_lut_path",
            return_value="/tmp/fake.npy",
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("test.svg"))],
                data={
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "structure_mode": structure_mode,
                    "color_mode": color_mode,
                    "enable_relief": "true",
                    "height_mode": "color",
                    "color_height_map": json.dumps({"#ff0000": 2.0}),
                },
            )

        assert response.status_code == 422
        assert "Native SVG relief supports only" in response.json()["detail"]
        _mock_pool.submit.assert_not_called()

    def test_batch_rejects_heightmap_relief_before_worker(self) -> None:
        """Batch keeps its existing color-relief-only contract for SVGs."""
        _mock_pool.submit = AsyncMock()

        with patch(
            "api.routers.converter.generate.LUTManager.get_lut_path",
            return_value="/tmp/fake.npy",
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("test.svg"))],
                data={
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "enable_relief": "true",
                    "height_mode": "heightmap",
                },
            )

        assert response.status_code == 422
        assert "not supported" in response.json()["detail"].lower()
        _mock_pool.submit.assert_not_called()


class TestBatchCleanup:
    """Verify batch route removes uploaded temps and packaged intermediates."""

    def test_batch_deletes_uploaded_png_temps_on_success_and_failure(self) -> None:
        temp_success = _make_fake_3mf(".png")
        temp_failure = _make_fake_3mf(".png")
        temp_paths = iter([temp_success, temp_failure])
        call_count = 0

        async def _mock_submit(fn, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_worker_result("ok.png", 30.0, 20.0)
            raise RuntimeError("boom")

        _mock_pool.submit = AsyncMock(side_effect=_mock_submit)

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(side_effect=lambda _upload: next(temp_paths)),
            ),
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                _noop_3mf_write,
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[
                    ("images", _make_test_image_buf("ok.png")),
                    ("images", _make_test_image_buf("fail.png")),
                ],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        assert not os.path.exists(temp_success)
        assert not os.path.exists(temp_failure)

    def test_batch_deletes_all_successful_3mf_files_after_merge(self) -> None:
        temp_one = _make_fake_3mf(".png")
        temp_two = _make_fake_3mf(".png")
        temp_paths = iter([temp_one, temp_two])

        worker_results = [
            _make_worker_result("img1.png", 30.0, 20.0),
            _make_worker_result("img2.png", 30.0, 20.0),
        ]
        results_iter = iter(worker_results)

        async def _mock_submit(fn, *args, **kwargs):
            return next(results_iter)

        _mock_pool.submit = AsyncMock(side_effect=_mock_submit)

        # Collect intermediate file paths to verify cleanup
        intermediate_3mf_paths = [wr["threemf_path"] for wr in worker_results]
        intermediate_glb_paths = [wr["preview_glb_path"] for wr in worker_results]

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(side_effect=lambda _upload: next(temp_paths)),
            ),
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                _noop_3mf_write,
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[
                    ("images", _make_test_image_buf("img1.png")),
                    ("images", _make_test_image_buf("img2.png")),
                ],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        # Per-image intermediate 3MF and GLB files should be cleaned up
        for p in intermediate_3mf_paths + intermediate_glb_paths:
            assert not os.path.exists(p), f"Intermediate file not cleaned: {p}"

    def test_batch_typed_dynamic_failure_cleans_prior_successes(self) -> None:
        from core.material_dynamic_solver import DynamicMaterialCandidateError

        first_result = _make_worker_result("ok.png", 30.0, 20.0)
        uploaded_paths = iter([_make_fake_3mf(".png"), _make_fake_3mf(".png")])
        call_count = 0

        async def _mock_submit(_fn, *_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return first_result
            raise DynamicMaterialCandidateError(
                "no candidate",
                target_srgb=(12, 34, 56),
                layer_count=6,
                phase="exact_search",
            )

        _mock_pool.submit = AsyncMock(side_effect=_mock_submit)
        artifact_paths = [
            first_result["threemf_path"],
            first_result["preview_glb_path"],
            first_result["metadata_sidecar_path"],
        ]

        try:
            with patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(side_effect=lambda _upload: next(uploaded_paths)),
            ):
                response = client.post(
                    "/api/convert/batch",
                    files=[
                        ("images", _make_test_image_buf("ok.png")),
                        ("images", _make_test_image_buf("fail.png")),
                    ],
                    data={
                        "material_source": "material_archive",
                        "selected_materials": json.dumps(["mat-a", "mat-b"]),
                        "material_dynamic_layer_count_enabled": "true",
                    },
                )
            remaining = [path for path in artifact_paths if os.path.exists(path)]
        finally:
            for path in artifact_paths:
                if path and os.path.exists(path):
                    os.remove(path)

        assert response.status_code == 409
        assert remaining == []


# =========================================================================
# 7. Batch Merge Flow — 5 example tests (R10 §4, P11, P12)
# =========================================================================


def _make_sidecar_json(
    source_filename: str,
    width_mm: float = 30.0,
    depth_mm: float = 20.0,
    num_slots: int = 2,
) -> str:
    """Create a temporary sidecar JSON file and return its path."""
    slots = [
        {
            "slot_id": i,
            "slot_name": f"Slot {i}",
            "preview_color": f"#{i:02x}{i:02x}{i:02x}",
            "material_id": f"MAT{i:02d}",
        }
        for i in range(num_slots)
    ]
    sidecar = {
        "schema_version": 1,
        "source_filename": source_filename,
        "xy_bbox_mm": {"width_mm": width_mm, "depth_mm": depth_mm},
        "slots": slots,
    }
    fd, path = tempfile.mkstemp(suffix=".json", prefix="sidecar-")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(sidecar, f)
    return path


def _make_worker_result(
    filename: str,
    width_mm: float = 30.0,
    depth_mm: float = 20.0,
) -> dict:
    """Create a full 5-key worker result with real temp files."""
    threemf_path = _make_fake_3mf(".3mf")
    glb_fd, glb_path = tempfile.mkstemp(suffix=".glb")
    os.write(glb_fd, b"fake-glb-content")
    os.close(glb_fd)
    sidecar_path = _make_sidecar_json(filename, width_mm, depth_mm)
    return {
        "threemf_path": threemf_path,
        "preview_glb_path": glb_path,
        "metadata_sidecar_path": sidecar_path,
        "xy_bbox_mm": (width_mm, depth_mm),
        "status_msg": "OK",
    }


def _noop_3mf_write(
    self,
    items,
    output_path,
    *,
    plate_width_mm,
    plate_depth_mm,
    enable_wipe_tower_auto_placement=True,
    **kwargs,
):
    """No-op replacement for MergedBambu3MFWriter.write that creates an empty file."""
    Path(output_path).write_bytes(b"fake-merged-3mf")


class TestBatchMergeFlow:
    """Batch merge flow integration tests (R10 §4).

    Validates: Requirements 1.1, 1.4, 4.1, 4.2, 4.3, 4.6, 4.7, 6.1, 6.2, 6.3, 6.4, 9.4, 10.4
    Properties: P11, P12
    """

    # ------------------------------------------------------------------
    # 1. all-success-fits: 3 images succeed, layout fits within plate
    # ------------------------------------------------------------------
    def test_selected_printer_bed_drives_batch_layout(self) -> None:
        """Batch layout uses the selected printer bed dimensions."""
        _mock_pool.submit = AsyncMock(
            return_value=_make_worker_result("img.png", 30.0, 20.0),
        )
        writer_plate_dims: list[tuple[float, float]] = []

        def _tracking_3mf_write(
            self,
            items,
            output_path,
            *,
            plate_width_mm,
            plate_depth_mm,
            enable_wipe_tower_auto_placement=True,
            **kwargs,
        ):
            writer_plate_dims.append((plate_width_mm, plate_depth_mm))
            Path(output_path).write_bytes(b"fake-merged-3mf")

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                _tracking_3mf_write,
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("img.png"))],
                data={
                    "lut_name": "test_lut",
                    "printer_id": "snapmaker-u1",
                    "slicer": "SnapmakerOrca",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert writer_plate_dims == [(270.0, 270.0)]
        assert body["preview_items"][0]["tx_mm"] == 120.0
        assert body["preview_items"][0]["ty_mm"] == 125.0

    def test_all_success_fits(self) -> None:
        """3 images all succeed + layout fits within plate.

        Asserts: download_url non-null, preview_3d_url non-null,
        warnings has no plate-overflow, all results are success.
        """
        results_iter = iter(
            [
                _make_worker_result("img1.png", 30.0, 20.0),
                _make_worker_result("img2.png", 30.0, 20.0),
                _make_worker_result("img3.png", 30.0, 20.0),
            ]
        )

        async def _mock_submit(fn, *args, **kwargs):
            return next(results_iter)

        _mock_pool.submit = AsyncMock(side_effect=_mock_submit)

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                _noop_3mf_write,
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[
                    ("images", _make_test_image_buf("img1.png")),
                    ("images", _make_test_image_buf("img2.png")),
                    ("images", _make_test_image_buf("img3.png")),
                ],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["download_url"] is not None
        assert body["download_url"].startswith("/api/files/")
        assert body["threemf_disk_path"] is None
        assert body["preview_3d_url"] is not None
        assert body["preview_3d_url"].startswith("/api/files/")
        assert body["preview_items"] == [
            {
                "url": body["preview_3d_url"],
                "filename": "img1.png",
                "tx_mm": 128.0,
                "ty_mm": 150.0,
                "width_mm": 30.0,
                "depth_mm": 20.0,
            },
            {
                "url": body["preview_items"][1]["url"],
                "filename": "img2.png",
                "tx_mm": 160.0,
                "ty_mm": 150.0,
                "width_mm": 30.0,
                "depth_mm": 20.0,
            },
            {
                "url": body["preview_items"][2]["url"],
                "filename": "img3.png",
                "tx_mm": 192.0,
                "ty_mm": 150.0,
                "width_mm": 30.0,
                "depth_mm": 20.0,
            },
        ]
        # No plate-overflow warning
        overflow_warnings = [
            w for w in body["warnings"] if w["code"] == "plate-overflow"
        ]
        assert len(overflow_warnings) == 0
        # All results are success
        assert len(body["results"]) == 3
        assert all(r["status"] == "success" for r in body["results"])

    def test_merged_wipe_tower_warning_is_returned_with_download(self) -> None:
        _mock_pool.submit = AsyncMock(
            return_value=_make_worker_result("img.png", 30.0, 20.0),
        )

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                _noop_3mf_write,
            ),
            patch(
                "api.routers.converter.generate.read_wipe_tower_placement_warnings",
                return_value=["wipe_tower_manual_adjustment_required"],
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("img.png"))],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["download_url"] is not None
        assert body["warnings"] == [
            {
                "code": "wipe_tower_manual_adjustment_required",
                "message": (
                    "文件已继续生成，但当前模型和擦料塔无法在所选热床上同时安全摆放。"
                    "请务必在切片软件中手动移动模型，或调整擦料塔的宽度和位置后再打印。"
                ),
            }
        ]

    def test_preview_registration_failure_preserves_final_download(self) -> None:
        """Preview registration failure should not discard the merged 3MF."""
        _mock_pool.submit = AsyncMock(
            return_value=_make_worker_result("img.png", 30.0, 20.0),
        )
        registry = _PreviewRegistrationFailingRegistry()
        log_calls: list[tuple[str, str, dict[str, object]]] = []

        def _capturing_safe_log(level: str, event: str, **fields: object) -> None:
            log_calls.append((level, event, fields))

        original_registry_override = app.dependency_overrides[get_file_registry]
        app.dependency_overrides[get_file_registry] = lambda: registry
        try:
            with (
                patch(
                    "api.routers.converter.generate.LUTManager.get_lut_path",
                    return_value="/tmp/fake.npy",
                ),
                patch(
                    "api.routers.converter.generate.ensure_png_tempfile",
                    new=AsyncMock(return_value="/tmp/uploaded.png"),
                ),
                patch(
                    "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                    _noop_3mf_write,
                ),
                patch(
                    "api.routers.converter.generate._safe_log",
                    side_effect=_capturing_safe_log,
                ),
            ):
                response = client.post(
                    "/api/convert/batch",
                    files=[("images", _make_test_image_buf("img.png"))],
                    data={"lut_name": "test_lut"},
                )

            assert response.status_code == 200
            body = response.json()
            assert body["status"] == "ok"
            assert body["download_url"].startswith("/api/files/")
            assert body["preview_3d_url"] is None
            assert body["preview_items"] == []
            assert [
                warning["code"]
                for warning in body["warnings"]
                if warning["code"] == "preview-unavailable"
            ] == ["preview-unavailable"]

            download_response = client.get(body["download_url"])
        finally:
            app.dependency_overrides[get_file_registry] = original_registry_override

        assert download_response.status_code == 200
        assert download_response.content == b"fake-merged-3mf"
        assert registry.download_path is not None
        assert Path(registry.download_path).exists()
        assert registry.preview_path is not None
        assert not Path(registry.preview_path).exists()

        assert not any(
            event == "batch_merge_3mf_failed" for _level, event, _fields in log_calls
        )
        warning_logs = [
            (level, fields)
            for level, event, fields in log_calls
            if event == "batch_merge_preview_unavailable"
        ]
        assert len(warning_logs) == 1
        level, fields = warning_logs[0]
        assert level == "warning"
        assert fields["error_type"] == "RuntimeError"
        assert fields["stage"] == "preview_file_registry"

    def test_later_preview_path_failure_keeps_earlier_preview(self) -> None:
        """One bad preview path should not hide previews already registered."""
        worker_results = [
            _make_worker_result("ok-preview.png", 30.0, 20.0),
            _make_worker_result("bad-preview.png", 30.0, 20.0),
        ]
        bad_preview_path = worker_results[1]["preview_glb_path"]
        results_iter = iter(worker_results)

        async def _mock_submit(fn, *args, **kwargs):
            return next(results_iter)

        _mock_pool.submit = AsyncMock(side_effect=_mock_submit)
        registry = FileRegistry()
        log_calls: list[tuple[str, str, dict[str, object]]] = []
        original_path_exists = Path.exists

        def _exists_with_late_preview_failure(path: Path) -> bool:
            if str(path) == bad_preview_path:
                raise ValueError("preview source path could not be inspected")
            return original_path_exists(path)

        def _capturing_safe_log(level: str, event: str, **fields: object) -> None:
            log_calls.append((level, event, fields))

        original_registry_override = app.dependency_overrides[get_file_registry]
        app.dependency_overrides[get_file_registry] = lambda: registry
        try:
            with (
                patch(
                    "api.routers.converter.generate.LUTManager.get_lut_path",
                    return_value="/tmp/fake.npy",
                ),
                patch(
                    "api.routers.converter.generate.ensure_png_tempfile",
                    new=AsyncMock(return_value="/tmp/uploaded.png"),
                ),
                patch(
                    "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                    _noop_3mf_write,
                ),
                patch(
                    "api.routers.converter.generate._safe_log",
                    side_effect=_capturing_safe_log,
                ),
                patch.object(Path, "exists", _exists_with_late_preview_failure),
            ):
                response = client.post(
                    "/api/convert/batch",
                    files=[
                        ("images", _make_test_image_buf("ok-preview.png")),
                        ("images", _make_test_image_buf("bad-preview.png")),
                    ],
                    data={"lut_name": "test_lut"},
                )
        finally:
            app.dependency_overrides[get_file_registry] = original_registry_override

        assert response.status_code == 200
        body = response.json()
        assert body["download_url"].startswith("/api/files/")
        assert body["preview_3d_url"] == body["preview_items"][0]["url"]
        assert [item["filename"] for item in body["preview_items"]] == [
            "ok-preview.png"
        ]
        assert [
            warning["code"]
            for warning in body["warnings"]
            if warning["code"] == "preview-unavailable"
        ] == ["preview-unavailable"]
        assert not any(
            event == "batch_merge_3mf_failed" for _level, event, _fields in log_calls
        )
        warning_logs = [
            (level, fields)
            for level, event, fields in log_calls
            if event == "batch_merge_preview_unavailable"
        ]
        assert len(warning_logs) == 1
        level, fields = warning_logs[0]
        assert level == "warning"
        assert fields["error_type"] == "ValueError"
        assert fields["stage"] == "preview_source"

    # ------------------------------------------------------------------
    # 2. all-success-overflows: layout exceeds plate → plate-overflow warning
    # ------------------------------------------------------------------
    def test_all_success_overflows(self) -> None:
        """All images succeed but layout exceeds plate.

        Asserts: download_url non-null, preview_3d_url non-null,
        warnings contains exactly 1 plate-overflow entry (P11).
        """
        results_iter = iter(
            [
                _make_worker_result("big1.png", 200.0, 200.0),
                _make_worker_result("big2.png", 200.0, 200.0),
                _make_worker_result("big3.png", 200.0, 200.0),
            ]
        )

        async def _mock_submit(fn, *args, **kwargs):
            return next(results_iter)

        _mock_pool.submit = AsyncMock(side_effect=_mock_submit)

        # Mock layout_shelf_by_row to return exceeds_plate=True
        from core.batch_layout.layout_helper import LayoutResult, Placement

        fake_layout = LayoutResult(
            placements=(
                Placement(tx_mm=0.0, ty_mm=0.0),
                Placement(tx_mm=203.0, ty_mm=0.0),
                Placement(tx_mm=0.0, ty_mm=203.0),
            ),
            exceeds_plate=True,
        )

        from api.routers.converter.generate import (
            BATCH_PLATE_OVERFLOW_FALLBACK_MESSAGE,
        )
        from scripts.log_quality_check import _has_actionable_warning_error_field

        log_calls: list[tuple[str, str, dict[str, object]]] = []

        def _capturing_safe_log(level: str, event: str, **fields: object) -> None:
            log_calls.append((level, event, fields))

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "api.routers.converter.generate.layout_shelf_by_row",
                return_value=fake_layout,
            ),
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                _noop_3mf_write,
            ),
            patch(
                "api.routers.converter.generate._safe_log",
                side_effect=_capturing_safe_log,
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[
                    ("images", _make_test_image_buf("big1.png")),
                    ("images", _make_test_image_buf("big2.png")),
                    ("images", _make_test_image_buf("big3.png")),
                ],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["download_url"] is not None
        assert body["download_url"].startswith("/api/files/")
        assert body["threemf_disk_path"] is None
        assert body["preview_3d_url"] is not None
        assert body["preview_3d_url"].startswith("/api/files/")
        assert len(body["preview_items"]) == 1
        assert [item["filename"] for item in body["preview_items"]] == [
            "big1.png",
        ]
        # Exactly 1 plate-overflow warning (P11)
        overflow_warnings = [
            w for w in body["warnings"] if w["code"] == "plate-overflow"
        ]
        assert len(overflow_warnings) == 1
        assert overflow_warnings[0]["code"] == "plate-overflow"
        assert isinstance(overflow_warnings[0]["message"], str)
        overflow_log = next(
            (
                (level, event, fields)
                for level, event, fields in log_calls
                if event == "batch_merge_plate_overflow_warning"
            ),
            None,
        )
        assert overflow_log is not None
        log_level, log_event, log_fields = overflow_log
        assert log_level == "warning"
        assert log_event == "batch_merge_plate_overflow_warning"
        assert (
            log_fields["error_message"]
            == BATCH_PLATE_OVERFLOW_FALLBACK_MESSAGE
        )
        assert (
            log_fields["fallback_action"]
            == "merged_3mf_returned_with_plate_overflow_warning"
        )
        assert _has_actionable_warning_error_field(log_fields)

    # ------------------------------------------------------------------
    # 2b. large-success-preview-limited: full 3MF keeps all, preview fits current bed
    # ------------------------------------------------------------------
    def test_large_success_preview_limited(self) -> None:
        """Large batches keep all results but preview only the prefix that fits."""
        item_count = 44
        results_iter = iter(
            [
                _make_worker_result(f"img{i}.png", 30.0, 80.0)
                for i in range(item_count)
            ]
        )

        async def _mock_submit(fn, *args, **kwargs):
            return next(results_iter)

        _mock_pool.submit = AsyncMock(side_effect=_mock_submit)

        written_item_counts: list[int] = []

        def _tracking_3mf_write(
            self,
            items,
            output_path,
            *,
            plate_width_mm,
            plate_depth_mm,
            enable_wipe_tower_auto_placement=True,
            **kwargs,
        ):
            written_item_counts.append(len(items))
            Path(output_path).write_bytes(b"fake-merged-3mf")

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                _tracking_3mf_write,
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[
                    ("images", _make_test_image_buf(f"img{i}.png"))
                    for i in range(item_count)
                ],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert len(body["results"]) == item_count
        assert all(r["status"] == "success" for r in body["results"])
        assert written_item_counts == [item_count]
        assert len(body["preview_items"]) == 33
        assert body["preview_items"][0]["tx_mm"] == 0.0
        assert body["preview_items"][0]["ty_mm"] == 38.0
        assert body["preview_items"][10]["tx_mm"] == 320.0
        assert body["preview_items"][10]["ty_mm"] == 38.0
        assert body["preview_items"][11]["tx_mm"] == 0.0
        assert body["preview_items"][11]["ty_mm"] == 120.0
        assert body["preview_items"][32]["tx_mm"] == 320.0
        assert body["preview_items"][32]["ty_mm"] == 202.0
        assert all(
            0 <= item["tx_mm"]
            and 0 <= item["ty_mm"]
            and item["tx_mm"] + item["width_mm"] <= 350
            and item["ty_mm"] + item["depth_mm"] <= 320
            for item in body["preview_items"]
        )
        preview_limit_warnings = [
            w for w in body["warnings"] if w["code"] == "preview-limited"
        ]
        assert len(preview_limit_warnings) == 1

    # ------------------------------------------------------------------
    # 3. partial-failure: 3 succeed + 1 fails
    # ------------------------------------------------------------------
    def test_partial_failure(self) -> None:
        """3 images succeed, 1 fails.

        Asserts: failed item in results, merged 3MF/GLB only contain 3 items.
        """
        call_count = 0

        async def _mock_submit(fn, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Simulated conversion failure")
            filenames = ["ok1.png", "fail.png", "ok2.png", "ok3.png"]
            return _make_worker_result(filenames[call_count - 1], 30.0, 20.0)

        _mock_pool.submit = AsyncMock(side_effect=_mock_submit)

        write_call_items_count = []

        def _tracking_3mf_write(
            self,
            items,
            output_path,
            *,
            plate_width_mm,
            plate_depth_mm,
            enable_wipe_tower_auto_placement=True,
            **kwargs,
        ):
            write_call_items_count.append(len(items))
            Path(output_path).write_bytes(b"fake-merged-3mf")

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                _tracking_3mf_write,
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[
                    ("images", _make_test_image_buf("ok1.png")),
                    ("images", _make_test_image_buf("fail.png")),
                    ("images", _make_test_image_buf("ok2.png")),
                    ("images", _make_test_image_buf("ok3.png")),
                ],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert len(body["results"]) == 4

        # Failed item is in results
        failed_items = [r for r in body["results"] if r["status"] == "failed"]
        assert len(failed_items) == 1
        assert failed_items[0]["filename"] == "fail.png"
        assert failed_items[0]["error"] is not None

        # Successful items
        success_items = [r for r in body["results"] if r["status"] == "success"]
        assert len(success_items) == 3

        # MergedBambu3MFWriter.write was called with N=3 items
        assert len(write_call_items_count) == 1
        assert write_call_items_count[0] == 3

        # download_url and preview_3d_url are present
        assert body["download_url"] is not None
        assert body["threemf_disk_path"] is None
        assert body["preview_3d_url"] is not None
        assert len(body["preview_items"]) == 3
        assert [item["filename"] for item in body["preview_items"]] == [
            "ok1.png",
            "ok2.png",
            "ok3.png",
        ]

    # ------------------------------------------------------------------
    # 4. all-failure: all images fail
    # ------------------------------------------------------------------
    def test_all_failure(self) -> None:
        """All images fail.

        Asserts: download_url == None, preview_3d_url == None,
        warnings == [], all results are failed.
        """
        _mock_pool.submit = AsyncMock(
            side_effect=RuntimeError("All items fail"),
        )

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[
                    ("images", _make_test_image_buf("bad1.png")),
                    ("images", _make_test_image_buf("bad2.png")),
                    ("images", _make_test_image_buf("bad3.png")),
                ],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["download_url"] is None
        assert body["threemf_disk_path"] is None
        assert body["preview_3d_url"] is None
        assert body["preview_items"] == []
        assert body["warnings"] == []
        assert len(body["results"]) == 3
        assert all(r["status"] == "failed" for r in body["results"])

    # ------------------------------------------------------------------
    # 5. writer-fail-5xx: MergedBambu3MFWriter.write raises MergedWriteError
    # ------------------------------------------------------------------
    def test_writer_fail_5xx(self) -> None:
        """MergedBambu3MFWriter.write raises MergedWriteError.

        Asserts: HTTP 500, log contains batch_merge_3mf_failed with
        stage=='merge_3mf', no residual temp files (P12).
        """
        worker_results = [
            _make_worker_result("img1.png", 30.0, 20.0),
            _make_worker_result("img2.png", 30.0, 20.0),
        ]
        results_iter = iter(worker_results)

        async def _mock_submit(fn, *args, **kwargs):
            return next(results_iter)

        _mock_pool.submit = AsyncMock(side_effect=_mock_submit)

        # Collect all intermediate file paths for residual check
        intermediate_paths = []
        for wr in worker_results:
            intermediate_paths.append(wr["threemf_path"])
            intermediate_paths.append(wr["preview_glb_path"])
            intermediate_paths.append(wr["metadata_sidecar_path"])

        private_path = "/Users/min/private/batch-output/merged.3mf"
        raw_error_message = f"cannot write {private_path}: Permission denied"

        def _failing_3mf_write(
            self,
            items,
            output_path,
            *,
            plate_width_mm,
            plate_depth_mm,
            enable_wipe_tower_auto_placement=True,
            **kwargs,
        ):
            raise MergedWriteError(raw_error_message)

        # Capture _safe_log calls to verify structured log emission
        log_calls: list[tuple] = []
        original_safe_log = None

        def _capturing_safe_log(level, event, **fields):
            log_calls.append((level, event, fields))

        with (
            patch(
                "api.routers.converter.generate.LUTManager.get_lut_path",
                return_value="/tmp/fake.npy",
            ),
            patch(
                "api.routers.converter.generate.ensure_png_tempfile",
                new=AsyncMock(return_value="/tmp/uploaded.png"),
            ),
            patch(
                "utils.merged_bambu_3mf_writer.MergedBambu3MFWriter.write",
                _failing_3mf_write,
            ),
            patch(
                "api.routers.converter.generate._safe_log",
                side_effect=_capturing_safe_log,
            ),
        ):
            response = client.post(
                "/api/convert/batch",
                files=[
                    ("images", _make_test_image_buf("img1.png")),
                    ("images", _make_test_image_buf("img2.png")),
                ],
                data={"lut_name": "test_lut"},
            )

        # HTTP 500
        assert response.status_code == 500
        assert response.json()["detail"] == (
            "Batch 3MF merge failed. Try again or check the server log for details."
        )
        assert private_path not in response.text
        assert "Permission denied" not in response.text
        assert "Batch merge failed at stage=" not in response.text
        assert "merge_3mf" not in response.text

        # Verify structured log: batch_merge_3mf_failed with stage=="merge_3mf"
        error_logs = [
            (level, event, fields)
            for level, event, fields in log_calls
            if event == "batch_merge_3mf_failed"
        ]
        assert len(error_logs) == 1, (
            f"Expected exactly 1 batch_merge_3mf_failed log, got {len(error_logs)}. "
            f"All log calls: {log_calls}"
        )
        level, event, fields = error_logs[0]
        assert level == "error"
        assert fields["stage"] == "merge_3mf"
        assert fields["error_type"] == "MergedWriteError"
        assert private_path in fields["error_message"]
        assert "Permission denied" in fields["error_message"]

        # No residual intermediate temp files (P12)
        for p in intermediate_paths:
            assert not os.path.exists(p), f"Residual temp file found: {p}"
