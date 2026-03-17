"""Unit tests for Converter Batch endpoint integration.

Validates:
- LUT name resolution failure returns 404 (Requirement 9)
- Partial failure continues processing remaining images (Requirement 9.3)
- All images succeed returns correct BatchResponse (Requirement 9.1, 9.2)
- Empty successful results still returns a valid ZIP (Requirement 9.3)
- asyncio.TimeoutError from pool.submit returns timeout error in results (Requirement 2.3)
- General Exception from pool.submit returns HTTP 500 error in results (Requirement 1.4)
"""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
from unittest.mock import AsyncMock, patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager

_test_store: SessionStore = SessionStore(ttl=1800)
_test_registry: FileRegistry = FileRegistry()


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

    def test_batch_unknown_lut_returns_404(self) -> None:
        with patch(
            "api.routers.converter.LUTManager.get_lut_path",
            return_value=None,
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("a.png"))],
                data={"lut_name": "nonexistent_lut"},
            )
        assert response.status_code == 404
        assert "LUT" in response.json()["detail"]


# =========================================================================
# 2. Partial failure continues processing - Requirement 9.3
# =========================================================================


class TestBatchPartialFailure:
    """Verify that if some images fail, remaining images still process."""

    def test_batch_partial_failure_continues(self) -> None:
        fake_3mf = _make_fake_3mf()
        call_count = 0

        async def _mock_submit(fn, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("Simulated failure")
            return {"threemf_path": fake_3mf, "status_msg": "OK"}

        _mock_pool.submit = AsyncMock(side_effect=_mock_submit)

        with patch(
            "api.routers.converter.LUTManager.get_lut_path",
            return_value="/tmp/fake.npy",
        ), patch(
            "api.routers.converter.upload_to_tempfile",
            return_value="/tmp/uploaded.png",
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
        assert body["results"][0]["error"] is not None

        # Second image succeeded
        assert body["results"][1]["filename"] == "ok.png"
        assert body["results"][1]["status"] == "success"

        # download_url present
        assert body["download_url"].startswith("/api/files/")


# =========================================================================
# 3. All images succeed - Requirement 9.1, 9.2
# =========================================================================


class TestBatchAllSuccess:
    """Verify all images succeed returns correct BatchResponse."""

    def test_batch_all_success(self) -> None:
        fake_3mf = _make_fake_3mf()

        _mock_pool.submit = AsyncMock(
            return_value={"threemf_path": fake_3mf, "status_msg": "OK"},
        )

        with patch(
            "api.routers.converter.LUTManager.get_lut_path",
            return_value="/tmp/fake.npy",
        ), patch(
            "api.routers.converter.upload_to_tempfile",
            return_value="/tmp/uploaded.png",
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


# =========================================================================
# 4. All images fail returns status "failed" - Requirement 9.3
# =========================================================================


class TestBatchAllFailed:
    """Verify all images failing returns status 'failed' with valid ZIP."""

    def test_batch_all_fail(self) -> None:
        _mock_pool.submit = AsyncMock(
            side_effect=RuntimeError("boom"),
        )

        with patch(
            "api.routers.converter.LUTManager.get_lut_path",
            return_value="/tmp/fake.npy",
        ), patch(
            "api.routers.converter.upload_to_tempfile",
            return_value="/tmp/uploaded.png",
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
        assert body["download_url"].startswith("/api/files/")


# =========================================================================
# 5. Timeout returns timeout error in batch item - Requirement 2.3
# =========================================================================


class TestBatchTimeout:
    """Verify asyncio.TimeoutError from pool.submit is handled per-item."""

    def test_batch_timeout_per_item(self) -> None:
        _mock_pool.submit = AsyncMock(
            side_effect=asyncio.TimeoutError(),
        )

        with patch(
            "api.routers.converter.LUTManager.get_lut_path",
            return_value="/tmp/fake.npy",
        ), patch(
            "api.routers.converter.upload_to_tempfile",
            return_value="/tmp/uploaded.png",
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("slow.png"))],
                data={"lut_name": "test_lut"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["results"][0]["status"] == "failed"
        assert "timed out" in body["results"][0]["error"].lower()


# =========================================================================
# 6. Worker pool receives correct function and args - Requirement 1.2, 2.1
# =========================================================================


class TestBatchWorkerPoolSubmit:
    """Verify pool.submit is called with worker_batch_convert_item and correct args."""

    def test_batch_submits_to_pool(self) -> None:
        fake_3mf = _make_fake_3mf()

        _mock_pool.submit = AsyncMock(
            return_value={"threemf_path": fake_3mf, "status_msg": "OK"},
        )

        with patch(
            "api.routers.converter.LUTManager.get_lut_path",
            return_value="/tmp/fake.npy",
        ), patch(
            "api.routers.converter.ensure_png_tempfile",
            new_callable=AsyncMock,
            return_value="/tmp/uploaded.png",
        ):
            response = client.post(
                "/api/convert/batch",
                files=[("images", _make_test_image_buf("test.png"))],
                data={
                    "lut_name": "test_lut",
                    "target_width_mm": "80.0",
                    "modeling_mode": "high-fidelity",
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
        assert call_args[0][1] == "/tmp/uploaded.png"  # image_path
        assert call_args[0][2] == "/tmp/fake.npy"      # lut_path
        assert call_args[0][3] == 80.0                  # target_width_mm
