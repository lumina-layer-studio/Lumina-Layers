"""Unit tests for Converter Generate endpoint integration.
Converter Generate 端点集成单元测试。

Validates:
- Generate endpoint offloads CPU work to worker pool (Requirement 1.2, 2.1)
- Worker receives only file paths and scalar params dict (Requirement 2.4)
- Session not found returns 404
- No preview_cache returns 409
- Missing image_path returns 409
- asyncio.TimeoutError → HTTP 504
- General Exception → HTTP 500
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager
from config import ModelingMode as CoreModelingMode

_test_store: SessionStore = SessionStore(ttl=1800)
_test_registry: FileRegistry = FileRegistry()
_mock_pool: MagicMock = MagicMock(spec=WorkerPoolManager)

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


def _create_session_with_preview_and_files(store: SessionStore) -> str:
    """Create a session pre-populated with preview_cache and file paths."""
    sid: str = store.create()
    store.put(sid, "preview_cache", {"some": "data"})
    store.put(sid, "image_path", "/tmp/test_image.png")
    store.put(sid, "lut_path", "/tmp/test_lut.npy")
    store.put(sid, "replacement_regions", [])
    store.put(sid, "free_color_set", set())
    return sid


# =========================================================================
# 1. Session not found returns 404
# =========================================================================


class TestGenerateSessionNotFound:
    """Verify unknown session_id returns HTTP 404."""

    def test_generate_unknown_session_returns_404(self) -> None:
        payload = {
            "session_id": "nonexistent-session-id",
            "params": {"lut_name": "test_lut"},
        }
        response = client.post("/api/convert/generate", json=payload)
        assert response.status_code == 404
        assert "Session" in response.json()["detail"]


# =========================================================================
# 2. No preview_cache returns 409
# =========================================================================


class TestGenerateNoPreviewCache:
    """Verify missing preview_cache returns HTTP 409."""

    def test_generate_no_preview_cache_returns_409(self) -> None:
        sid: str = _test_store.create()
        payload = {
            "session_id": sid,
            "params": {"lut_name": "test_lut"},
        }
        response = client.post("/api/convert/generate", json=payload)
        assert response.status_code == 409
        assert "preview" in response.json()["detail"].lower()


# =========================================================================
# 3. Missing image_path returns 409
# =========================================================================


class TestGenerateMissingImagePath:
    """Verify missing or non-existent image_path returns HTTP 409."""

    def test_generate_missing_image_path_returns_409(self) -> None:
        sid: str = _test_store.create()
        _test_store.put(sid, "preview_cache", {"some": "data"})
        payload = {
            "session_id": sid,
            "params": {"lut_name": "test_lut"},
        }
        response = client.post("/api/convert/generate", json=payload)
        assert response.status_code == 409
        assert "Image file missing" in response.json()["detail"]

    def test_generate_nonexistent_image_file_returns_409(self) -> None:
        sid: str = _test_store.create()
        _test_store.put(sid, "preview_cache", {"some": "data"})
        _test_store.put(sid, "image_path", "/tmp/does_not_exist_12345.png")
        _test_store.put(sid, "lut_path", "/tmp/test_lut.npy")
        payload = {
            "session_id": sid,
            "params": {"lut_name": "test_lut"},
        }
        response = client.post("/api/convert/generate", json=payload)
        assert response.status_code == 409


# =========================================================================
# 4. Parameter completeness via worker pool - Requirement 1.2, 2.1, 2.4
# =========================================================================


class TestGenerateParameterCompleteness:
    """Verify all parameters are correctly collected and passed to worker_generate_model via pool.submit."""

    def test_generate_passes_all_advanced_params(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)

        payload = {
            "session_id": sid,
            "params": {
                "lut_name": "test_lut",
                "target_width_mm": 80.0,
                "spacer_thick": 1.5,
                "structure_mode": "Single-sided",
                "auto_bg": True,
                "bg_tol": 60,
                "color_mode": "4-Color",
                "modeling_mode": "high-fidelity",
                "quantize_colors": 64,
                "enable_cleanup": False,
                "separate_backing": True,
                "add_loop": True,
                "loop_width": 5.0,
                "loop_length": 10.0,
                "loop_hole": 3.0,
                "loop_pos": [50.0, 50.0],
                "enable_relief": True,
                "color_height_map": {"#ff0000": 2.0},
                "heightmap_max_height": 8.0,
                "enable_outline": True,
                "outline_width": 3.0,
                "enable_cloisonne": True,
                "wire_width_mm": 0.6,
                "wire_height_mm": 0.5,
                "enable_coating": True,
                "coating_height_mm": 0.1,
            },
        }

        # Mock pool.submit to return worker-style dict result
        worker_result = {
            "threemf_path": "/tmp/out.3mf",
            "glb_path": "/tmp/out.glb",
            "status_msg": "OK",
        }
        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with patch("os.path.exists", return_value=True):
            response = client.post("/api/convert/generate", json=payload)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["download_url"].startswith("/api/files/")
        assert body["preview_3d_url"].startswith("/api/files/")

        # Verify pool.submit was called exactly once
        _mock_pool.submit.assert_called_once()

        # Extract positional args: (worker_fn, image_path, lut_path, params_dict)
        call_args = _mock_pool.submit.call_args
        worker_fn = call_args.args[0]
        submitted_image_path = call_args.args[1]
        submitted_lut_path = call_args.args[2]
        submitted_params = call_args.args[3]

        # Verify worker function identity
        from api.workers.converter_workers import worker_generate_model
        assert worker_fn is worker_generate_model

        # Verify file paths from session
        assert submitted_image_path == "/tmp/test_image.png"
        assert submitted_lut_path == "/tmp/test_lut.npy"

        # Verify params dict contains all scalar parameters
        assert submitted_params["target_width_mm"] == 80.0
        assert submitted_params["spacer_thick"] == 1.5
        assert submitted_params["structure_mode"] == "Single-sided"
        assert submitted_params["auto_bg"] is True
        assert submitted_params["bg_tol"] == 60
        assert submitted_params["color_mode"] == "4-Color"
        assert submitted_params["quantize_colors"] == 64
        assert submitted_params["enable_cleanup"] is False
        assert submitted_params["separate_backing"] is True

        # Verify modeling_mode is converted to core enum
        assert submitted_params["modeling_mode"] == CoreModelingMode("high-fidelity")

        # Verify keychain loop parameters
        assert submitted_params["add_loop"] is True
        assert submitted_params["loop_width"] == 5.0
        assert submitted_params["loop_length"] == 10.0
        assert submitted_params["loop_hole"] == 3.0
        assert submitted_params["loop_pos"] == (50.0, 50.0)

        # Verify relief parameters
        assert submitted_params["enable_relief"] is True
        assert submitted_params["color_height_map"] == {"#ff0000": 2.0}
        assert submitted_params["heightmap_max_height"] == 8.0

        # Verify outline parameters
        assert submitted_params["enable_outline"] is True
        assert submitted_params["outline_width"] == 3.0

        # Verify cloisonne parameters
        assert submitted_params["enable_cloisonne"] is True
        assert submitted_params["wire_width_mm"] == 0.6
        assert submitted_params["wire_height_mm"] == 0.5

        # Verify coating parameters
        assert submitted_params["enable_coating"] is True
        assert submitted_params["coating_height_mm"] == 0.1

        # Verify session-derived parameters (empty → None)
        assert submitted_params["replacement_regions"] is None
        assert submitted_params["free_color_set"] is None

    def test_generate_passes_replacement_regions_from_request(self) -> None:
        """Verify replacement_regions from request body override session data."""
        sid: str = _create_session_with_preview_and_files(_test_store)

        payload = {
            "session_id": sid,
            "params": {
                "lut_name": "test_lut",
                "replacement_regions": [
                    {
                        "quantized_hex": "#ff0000",
                        "matched_hex": "#ee0000",
                        "replacement_hex": "#00ff00",
                    }
                ],
            },
        }

        worker_result = {
            "threemf_path": "/tmp/out.3mf",
            "glb_path": "/tmp/out.glb",
            "status_msg": "OK",
        }
        _mock_pool.submit = AsyncMock(return_value=worker_result)

        with patch("os.path.exists", return_value=True):
            response = client.post("/api/convert/generate", json=payload)

        assert response.status_code == 200
        submitted_params = _mock_pool.submit.call_args.args[3]
        regions = submitted_params["replacement_regions"]
        assert len(regions) == 1
        assert regions[0]["quantized_hex"] == "#ff0000"
        assert regions[0]["matched_hex"] == "#ee0000"
        assert regions[0]["replacement_hex"] == "#00ff00"


# =========================================================================
# 5. Timeout → HTTP 504 - Requirement 2.3
# =========================================================================


class TestGenerateTimeout:
    """Verify asyncio.TimeoutError from pool.submit returns HTTP 504."""

    def test_generate_timeout_returns_504(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)

        payload = {
            "session_id": sid,
            "params": {"lut_name": "test_lut"},
        }

        _mock_pool.submit = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch("os.path.exists", return_value=True):
            response = client.post("/api/convert/generate", json=payload)

        assert response.status_code == 504
        assert "timed out" in response.json()["detail"].lower()


# =========================================================================
# 6. Worker exception → HTTP 500 - Requirement 1.4
# =========================================================================


class TestGenerateWorkerException:
    """Verify general Exception from pool.submit returns HTTP 500."""

    def test_generate_worker_exception_returns_500(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)

        payload = {
            "session_id": sid,
            "params": {"lut_name": "test_lut"},
        }

        _mock_pool.submit = AsyncMock(side_effect=RuntimeError("Worker crashed"))

        with patch("os.path.exists", return_value=True):
            response = client.post("/api/convert/generate", json=payload)

        assert response.status_code == 500
        assert "Worker crashed" in response.json()["detail"]
