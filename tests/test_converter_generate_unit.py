"""Unit tests for Converter Generate endpoint integration.
Converter Generate 端点集成单元测试。

Validates:
- Generate endpoint offloads CPU work to worker pool (Requirement 1.2, 2.1)
- Worker receives only file paths and scalar params dict (Requirement 2.4)
- Session not found returns 404
- No preview_cache returns 409
- Missing image_path returns 409
- asyncio.TimeoutError → HTTP 504
- General Exception → safe HTTP 500
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from concurrent.futures.process import BrokenProcessPool
import inspect
import json
import os
import pickle
import tempfile
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
import numpy as np
from PIL import Image
import pytest

from api.app import app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.preview_cache_artifacts import externalize_preview_cache
from api.routers.converter.color_card import _COLOR_CARD_GENERATION_FAILED_DETAIL
from api.routers.converter.generate import _generate_large_format_raster
from api.routers.converter.generate import _generate_large_format_svg_native
from api.routers.converter.generate import _rasterize_svg_fallback_tile
from api.routers.converter.generate import LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL
from api.routers.converter.generate import LARGE_FORMAT_GENERATION_FAILED_DETAIL
from api.routers.converter.generate import MODEL_GENERATION_FAILED_DETAIL
from api.routers.converter.generate import _recover_virtual_materials_from_preview_cache
from api.routers.converter.generate import _normalize_recipe_overrides
from api.routers.converter.generate import _resolve_large_format_shared_params
from api.routers.converter.generate import _resolve_recipe_overrides
from api.routers.converter.generate import _resolve_large_format_source_basename
from api.routers.converter.generate import _validate_native_vector_relief_compatibility
from api.schemas.converter import (
    ColorMode,
    ConvertGenerateRequest,
    LargeFormatConvertGenerateRequest,
    ModelingMode,
    StructureMode,
)
from api.schemas.system import UserSettings
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager
from api.workers.converter_workers import LargeFormatCachedAnalysisError
from config import ModelingMode as CoreModelingMode
from core.converter import (
    _resolve_material_archive_backing_color_id,
    convert_image_to_3d,
)
from core.pipeline.processing_ops.svg_rasterizer import rasterize_svg

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








async def _timed_submit_via_generate_mock(
    *args: object,
    **kwargs: object,
) -> tuple[object, dict[str, float]]:
    return await _mock_pool.submit(*args, **kwargs), {}


@pytest.fixture(autouse=True)
def _resolved_native_material_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub material preflight for route tests that use synthetic source files.

    只隔离虚构文件的材料预检，保留设备、缓存、worker 路由及错误断言。
    """
    monkeypatch.setattr(
        "api.routers.converter.generate.require_material_selection",
        MagicMock(return_value={"ready": True}),
    )


@pytest.fixture(autouse=True)
def _keep_generate_pool_timing_opt_in() -> object:
    """Keep legacy submit assertions while the route uses submit_timed."""
    previous = _mock_pool.submit_timed
    _mock_pool.submit_timed = AsyncMock(
        side_effect=_timed_submit_via_generate_mock,
    )
    try:
        yield
    finally:
        _mock_pool.submit_timed = previous


class _FailingRegistry(FileRegistry):
    """Registry stub that simulates registration backend failure."""

    def register_path(self, *args: object, **kwargs: object) -> str:
        raise RuntimeError("registry unavailable")


class _SecondRegistrationFailingRegistry(FileRegistry):
    """Registry stub that fails after the first path is owned."""

    def __init__(self) -> None:
        super().__init__()
        self.register_calls = 0
        self.first_file_id: str | None = None

    def register_path(self, *args: object, **kwargs: object) -> str:
        self.register_calls += 1
        if self.register_calls > 1:
            raise RuntimeError("registry unavailable after first file")
        self.first_file_id = super().register_path(*args, **kwargs)
        return self.first_file_id


def test_generate_response_exposes_worker_pool_timing() -> None:
    sid = _create_session_with_preview_and_files(_test_store)
    worker_result = {
        "threemf_path": "/tmp/timed-out.3mf",
        "glb_path": None,
        "status_msg": "OK",
    }
    _mock_pool.submit_timed = AsyncMock(
        return_value=(
            worker_result,
            {
                "queue_wait_s": 0.2,
                "worker_execution_s": 0.8,
                "result_delivery_s": 0.03,
                "pool_roundtrip_s": 1.03,
            },
        )
    )
    payload = {
        "session_id": sid,
        "params": {
            "lut_name": "test_lut",
            "modeling_mode": "high-fidelity",
        },
    }

    with patch("os.path.exists", return_value=True):
        response = client.post("/api/convert/generate", json=payload)

    assert response.status_code == 200, response.text
    performance = response.json()["performance_timing"]
    assert performance["queue_wait_ms"] == 200.0
    assert performance["worker_execution_ms"] == 800.0
    assert performance["result_delivery_ms"] == 30.0
    assert performance["endpoint_post_worker_ms"] >= 0.0


def test_generate_rejects_stale_editor_content_revision_before_worker() -> None:
    """Generation must not combine a stale editor snapshot with current cache."""

    sid = _create_session_with_preview_and_files(_test_store)
    _test_store.put(sid, "visible_region_cache_generation", 7)
    _mock_pool.submit = AsyncMock()
    payload = {
        "session_id": sid,
        "params": {
            "lut_name": "test_lut",
            "modeling_mode": "high-fidelity",
            "editor_content_revision": 6,
        },
    }

    with patch("os.path.exists", return_value=True):
        response = client.post("/api/convert/generate", json=payload)

    assert response.status_code == 409, response.text
    assert "Visible content changed" in response.json()["detail"]
    _mock_pool.submit.assert_not_called()


def test_generate_rejects_stale_selection_revision_before_worker() -> None:
    """Generation must bind both content and shared-selection revisions."""

    sid = _create_session_with_preview_and_files(_test_store)
    _test_store.put(sid, "editor_selection_revision", 3)
    _mock_pool.submit = AsyncMock()
    payload = {
        "session_id": sid,
        "params": {
            "lut_name": "test_lut",
            "modeling_mode": "high-fidelity",
            "selection_revision": 2,
        },
    }

    with patch("os.path.exists", return_value=True):
        response = client.post("/api/convert/generate", json=payload)

    assert response.status_code == 409, response.text
    assert "selection changed" in response.json()["detail"].lower()
    _mock_pool.submit.assert_not_called()


def test_generate_worker_receives_immutable_editor_snapshot_when_store_changes_after_assembly() -> None:
    """A store edit after input assembly cannot mutate the enqueued worker args."""

    sid = _create_session_with_preview_and_files(_test_store)
    old_regions = [
        {
            "selected_color": "#ff0000",
            "replacement_color": "#00ff00",
        }
    ]
    _test_store.put(sid, "replacement_regions", old_regions)
    _test_store.put(sid, "editor_content_revision", 1)
    worker_params_seen: dict[str, object] = {}

    async def submit_after_store_edit(*args: object, **kwargs: object) -> tuple[dict[str, object], dict[str, float]]:
        worker_params_seen.update(args[3])
        # Simulate a real edit arriving after generation assembled its
        # request but before the worker consumes it.
        _test_store.put(sid, "replacement_regions", [{"selected_color": "#0000ff"}])
        _test_store.put(sid, "editor_content_revision", 2)
        return (
            {
                "threemf_path": "/tmp/stale-generation.3mf",
                "glb_path": None,
                "status_msg": "OK",
            },
            {},
        )

    _mock_pool.submit_timed = AsyncMock(side_effect=submit_after_store_edit)
    payload = {
        "session_id": sid,
        "params": {
            "lut_name": "test_lut",
            "modeling_mode": "high-fidelity",
            "editor_content_revision": 1,
        },
    }

    with patch("os.path.exists", return_value=True):
        response = client.post("/api/convert/generate", json=payload)

    assert response.status_code == 409, response.text
    assert worker_params_seen["replacement_regions"] == old_regions
    assert "Editor content changed" in response.json()["detail"]


def test_generate_response_forwards_embedded_wipe_tower_warning() -> None:
    sid = _create_session_with_preview_and_files(_test_store)
    _mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": "/tmp/manual-adjustment.3mf",
            "glb_path": None,
            "status_msg": "OK",
        }
    )
    payload = {
        "session_id": sid,
        "params": {
            "lut_name": "test_lut",
            "modeling_mode": "high-fidelity",
        },
    }

    with (
        patch("os.path.exists", return_value=True),
        patch(
            "api.routers.converter.generate.read_wipe_tower_placement_warnings",
            return_value=["wipe_tower_manual_adjustment_required"],
        ),
    ):
        response = client.post("/api/convert/generate", json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["warnings"] == [
        "wipe_tower_manual_adjustment_required"
    ]


@pytest.mark.asyncio
async def test_large_format_raster_forwards_embedded_tile_warning(tmp_path) -> None:
    image_path = tmp_path / "source.png"
    lut_path = tmp_path / "source.npy"
    tile_path = tmp_path / "tile.3mf"
    Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8)).save(image_path)
    lut_path.write_bytes(b"lut")
    tile_path.write_bytes(b"3mf")
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    pool = MagicMock(spec=WorkerPoolManager)
    pool.submit = AsyncMock(
        return_value={"threemf_path": str(tile_path), "glb_path": None, "status_msg": "ok"}
    )
    request = LargeFormatConvertGenerateRequest(
        lut_name="test_lut",
        modeling_mode=ModelingMode.HIGH_FIDELITY,
    )
    warning_code = "wipe_tower_manual_adjustment_required"
    try:
        with patch(
            "api.routers.converter.generate.read_wipe_tower_placement_warnings",
            return_value=[warning_code],
        ):
            result = await _generate_large_format_raster(
                image_path=str(image_path),
                lut_path=str(lut_path),
                source_basename="source",
                recipe_overrides=None,
                recipe_override_masks_path=None,
                material_matrix_path=None,
                total_width_mm=10.0,
                total_height_mm=10.0,
                tile_width_mm=10.0,
                tile_height_mm=10.0,
                request=request,
                session_data={},
                sid="warning-session",
                store=store,
                registry=registry,
                pool=pool,
            )
        assert result["warnings"] == [warning_code]
    finally:
        store.clear_all()
        registry.clear_all()


@pytest.mark.asyncio
async def test_large_format_raster_memory_error_cancels_pending_tiles(tmp_path) -> None:
    """A tile OOM keeps the original error and cancels unconsumed work."""

    class _Awaitable:
        def __init__(self, value=None, error: BaseException | None = None):
            self.value = value
            self.error = error
            self.cancelled = False

        def cancel(self):
            self.cancelled = True
            return True

        def __await__(self):
            async def _resolve():
                if self.error is not None:
                    raise self.error
                return self.value

            return _resolve().__await__()

    image_path = tmp_path / "source.png"
    lut_path = tmp_path / "source.npy"
    first_tile = tmp_path / "first.3mf"
    Image.fromarray(np.zeros((10, 30, 3), dtype=np.uint8)).save(image_path)
    lut_path.write_bytes(b"lut")
    first_tile.write_bytes(b"3mf")
    first = _Awaitable({"threemf_path": str(first_tile), "glb_path": None, "status_msg": "ok"})
    failing = _Awaitable(error=MemoryError("injected large-format OOM"))
    pending = _Awaitable({"threemf_path": None, "glb_path": None, "status_msg": "pending"})
    pool = MagicMock(spec=WorkerPoolManager)
    pool.submit = MagicMock(side_effect=[first, failing, pending])
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    request = LargeFormatConvertGenerateRequest(
        lut_name="test_lut",
        modeling_mode=ModelingMode.HIGH_FIDELITY,
    )
    try:
        with pytest.raises(MemoryError, match="injected large-format OOM"):
            await _generate_large_format_raster(
                image_path=str(image_path),
                lut_path=str(lut_path),
                source_basename="source",
                recipe_overrides=None,
                recipe_override_masks_path=None,
                material_matrix_path=None,
                total_width_mm=30.0,
                total_height_mm=10.0,
                tile_width_mm=10.0,
                tile_height_mm=10.0,
                request=request,
                session_data={},
                sid="oom-session",
                store=store,
                registry=registry,
                pool=pool,
            )
        assert pending.cancelled is True
        assert pool.submit.call_count == 3
        assert not first_tile.exists()
    finally:
        store.clear_all()
        registry.clear_all()


def test_svg_fallback_rasterizes_one_global_tile_without_full_canvas(tmp_path) -> None:
    svg_path = tmp_path / "source.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 50" '
        'width="100" height="50"><rect width="100" height="50" fill="red"/></svg>',
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def _fake_rasterize(path, target_width_mm, **kwargs):
        captured.update(path=path, target_width_mm=target_width_mm, kwargs=kwargs)
        return np.zeros((20, 40, 4), dtype=np.uint8)

    with patch(
        "api.routers.converter.generate.rasterize_svg",
        side_effect=_fake_rasterize,
    ):
        tile_path = _rasterize_svg_fallback_tile(
            svg_path=str(svg_path),
            total_width_mm=100.0,
            total_height_mm=50.0,
            x0_mm=50.0,
            y0_mm=0.0,
            x1_mm=100.0,
            y1_mm=50.0,
            pixels_per_mm=10.0,
        )

    try:
        assert captured["target_width_mm"] == 50.0
        assert captured["kwargs"]["crop_to_content"] is False
        assert captured["kwargs"]["_cache_result"] is False
        with Image.open(tile_path) as rendered:
            assert rendered.size == (40, 20)
    finally:
        Path(tile_path).unlink(missing_ok=True)


def test_svg_fallback_preserves_percentage_viewport_across_tiles(tmp_path) -> None:
    """The real resvg path crops a full SVG viewport, not a re-laid-out root."""

    svg_path = tmp_path / "percentage-layout.svg"
    svg_path.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
  <defs><filter id="blur"><feGaussianBlur stdDeviation="0.1"/></filter></defs>
  <g filter="url(#blur)">
    <rect width="100%" height="100%" fill="red"/>
    <rect x="50%" width="50%" height="100%" fill="blue"/>
  </g>
</svg>""",
        encoding="utf-8",
    )

    tile_paths: list[str] = []
    try:
        for x0_mm, x1_mm in ((0.0, 50.0), (50.0, 100.0)):
            tile_path = _rasterize_svg_fallback_tile(
                svg_path=str(svg_path),
                total_width_mm=100.0,
                total_height_mm=100.0,
                x0_mm=x0_mm,
                y0_mm=0.0,
                x1_mm=x1_mm,
                y1_mm=100.0,
                pixels_per_mm=4.0,
            )
            tile_paths.append(tile_path)

        with Image.open(tile_paths[0]) as left_image, Image.open(tile_paths[1]) as right_image:
            left_rgb = np.asarray(left_image.convert("RGB"), dtype=np.float32).mean(axis=(0, 1))
            right_rgb = np.asarray(right_image.convert("RGB"), dtype=np.float32).mean(axis=(0, 1))

        assert left_rgb[0] > 240 and left_rgb[2] < 10
        assert right_rgb[2] > 240 and right_rgb[0] < 10
    finally:
        for tile_path in tile_paths:
            Path(tile_path).unlink(missing_ok=True)


@pytest.mark.parametrize(
    ("viewport_width", "viewport_height", "preserve_aspect_ratio"),
    ((100, 100, None), (200, 100, None), (200, 100, "none")),
)
def test_svg_fallback_tiles_match_full_resvg_viewport_crop(
    tmp_path,
    viewport_width: int,
    viewport_height: int,
    preserve_aspect_ratio: str | None,
) -> None:
    """Windowed fallback pixels match cropping the same full resvg canvas."""

    preserve_attribute = (
        f' preserveAspectRatio="{preserve_aspect_ratio}"'
        if preserve_aspect_ratio is not None
        else ""
    )
    svg_path = tmp_path / "viewport-reference.svg"
    svg_path.write_text(
        f'''<svg xmlns="http://www.w3.org/2000/svg" width="{viewport_width}"
height="{viewport_height}" viewBox="0 0 100 100"{preserve_attribute}>
  <defs><clipPath id="canvas"><rect width="100" height="100"/></clipPath></defs>
  <g clip-path="url(#canvas)">
    <rect width="100%" height="100%" fill="red"/>
    <rect x="50%" width="50%" height="100%" fill="blue"/>
  </g>
</svg>''',
        encoding="utf-8",
    )
    density = 4.0
    full = rasterize_svg(
        str(svg_path),
        float(viewport_width),
        pixels_per_mm=density,
        crop_to_content=False,
        _min_quality_px=1,
        _cache_result=False,
    )

    tile_paths: list[str] = []
    try:
        tile_width_mm = viewport_width / 2.0
        for x0_mm, x1_mm in ((0.0, tile_width_mm), (tile_width_mm, viewport_width)):
            tile_path = _rasterize_svg_fallback_tile(
                svg_path=str(svg_path),
                total_width_mm=float(viewport_width),
                total_height_mm=float(viewport_height),
                x0_mm=x0_mm,
                y0_mm=0.0,
                x1_mm=x1_mm,
                y1_mm=float(viewport_height),
                pixels_per_mm=density,
            )
            tile_paths.append(tile_path)

            with Image.open(tile_path) as tile_image:
                actual = np.asarray(tile_image.convert("RGBA"))
            px_x0 = int(round(x0_mm / viewport_width * full.shape[1]))
            px_x1 = int(round(x1_mm / viewport_width * full.shape[1]))
            expected = full[:, px_x0:px_x1]
            np.testing.assert_array_equal(actual, expected)
    finally:
        for tile_path in tile_paths:
            Path(tile_path).unlink(missing_ok=True)


def test_svg_fallback_physical_units_match_full_resvg_viewport_crop(tmp_path) -> None:
    """Physical SVG lengths use the same CSS-pixel viewport as the full render."""

    svg_path = tmp_path / "physical-unit-fallback.svg"
    svg_path.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm">
  <defs><filter id="blur"><feGaussianBlur stdDeviation="0.1"/></filter></defs>
  <g filter="url(#blur)">
    <rect width="100%" height="100%" fill="red"/>
    <rect x="50mm" width="50mm" height="100mm" fill="blue"/>
  </g>
</svg>""",
        encoding="utf-8",
    )
    full = rasterize_svg(
        str(svg_path),
        100.0,
        pixels_per_mm=4.0,
        crop_to_content=False,
        _min_quality_px=1,
        _cache_result=False,
    )
    tile_paths: list[str] = []
    try:
        for x0_mm, x1_mm in ((0.0, 50.0), (50.0, 100.0)):
            tile_path = _rasterize_svg_fallback_tile(
                svg_path=str(svg_path),
                total_width_mm=100.0,
                total_height_mm=100.0,
                x0_mm=x0_mm,
                y0_mm=0.0,
                x1_mm=x1_mm,
                y1_mm=100.0,
                pixels_per_mm=4.0,
            )
            tile_paths.append(tile_path)
            with Image.open(tile_path) as tile_image:
                actual = np.asarray(tile_image.convert("RGBA"))
            px_x0 = int(round(x0_mm / 100.0 * full.shape[1]))
            px_x1 = int(round(x1_mm / 100.0 * full.shape[1]))
            expected = full[:, px_x0:px_x1]
            # Physical-unit conversion can round one CSS pixel differently
            # between the full and windowed resvg calls; geometry and color
            # must still match within that one-channel rounding unit.
            assert np.max(np.abs(actual.astype(np.int16) - expected.astype(np.int16))) <= 1
    finally:
        for tile_path in tile_paths:
            Path(tile_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_svg_fallback_heightmap_uses_independent_global_y_coordinates(tmp_path) -> None:
    """Fallback tiles must receive the corresponding upper/lower heightmap rows."""

    class _Completed:
        def __init__(self, value: dict[str, object]) -> None:
            self.value = value

        def __await__(self):
            async def _resolve():
                return self.value

            return _resolve().__await__()

    svg_path = tmp_path / "heightmap-source.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" '
        'viewBox="0 0 100 100"><rect width="100%" height="100%" fill="red"/></svg>',
        encoding="utf-8",
    )
    lut_path = tmp_path / "lut.npy"
    lut_path.write_bytes(b"lut")
    heightmap = np.zeros((100, 100), dtype=np.uint8)
    heightmap[:50, :] = 64
    heightmap[50:, :] = 192

    sampled: list[tuple[tuple[int, int], float]] = []
    tile_paths: list[Path] = []

    def _submit(_worker, _image_path, _lut_path, tile_params):
        with Image.open(tile_params["heightmap_path"]) as tile_heightmap:
            sampled.append(
                (
                    tile_heightmap.size,
                    float(np.asarray(tile_heightmap).mean()),
                )
            )
        output_path = tmp_path / f"tile-{len(tile_paths)}.3mf"
        output_path.write_bytes(b"3mf")
        tile_paths.append(output_path)
        return _Completed(
            {
                "threemf_path": str(output_path),
                "glb_path": None,
                "status_msg": "ok",
            }
        )

    pool = MagicMock(spec=WorkerPoolManager)
    pool.submit = MagicMock(side_effect=_submit)
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    request = LargeFormatConvertGenerateRequest(
        lut_name="test_lut",
        modeling_mode=ModelingMode.HIGH_FIDELITY,
        enable_relief=True,
        height_mode="heightmap",
    )

    try:
        result = await _generate_large_format_raster(
            image_path=None,
            svg_fallback_path=str(svg_path),
            lut_path=str(lut_path),
            source_basename="heightmap-source",
            recipe_overrides=None,
            recipe_override_masks_path=None,
            material_matrix_path=None,
            total_width_mm=100.0,
            total_height_mm=100.0,
            tile_width_mm=100.0,
            tile_height_mm=50.0,
            request=request,
            session_data={"heightmap_grayscale": heightmap},
            sid="heightmap-fallback-session",
            store=store,
            registry=registry,
            pool=pool,
        )

        assert result["tile_count"] == 2
        assert sampled == [((100, 50), 64.0), ((100, 50), 192.0)]
    finally:
        registry.clear_all()
        store.clear_all()
        for output_path in tile_paths:
            output_path.unlink(missing_ok=True)


def test_color_card_response_forwards_only_embedded_wipe_tower_warnings(
    tmp_path: Path,
) -> None:
    """Color-card responses expose the warning embedded in the final 3MF."""

    _test_store.clear_all()
    _test_registry.clear_all()
    warning_code = "wipe_tower_manual_adjustment_required"

    for case_name, requires_manual_adjustment, expected_warnings in (
        ("manual", True, [warning_code]),
        ("safe", False, []),
    ):
        output_path = tmp_path / f"color-card-{case_name}.3mf"
        with zipfile.ZipFile(output_path, "w") as package:
            package.writestr(
                "Metadata/lumina_wipe_tower_placement.json",
                json.dumps(
                    {
                        "requires_manual_adjustment": requires_manual_adjustment,
                        "warning_code": (
                            warning_code if requires_manual_adjustment else None
                        ),
                    }
                ),
            )

        lut_path = tmp_path / f"color-card-{case_name}.npy"
        np.save(lut_path, np.zeros((1, 3), dtype=np.uint8))
        svg_path = tmp_path / f"color-card-{case_name}.svg"
        svg_path.write_text("<svg/>", encoding="utf-8")
        sid = _test_store.create()
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(
            sid,
            "preview_cache",
            {
                "target_w": 4,
                "target_h": 4,
                "target_width_mm": 40.0,
                "color_palette": [{"hex": "#ff0000"}],
                "color_mode": "4-Color (RYBW)",
            },
        )
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": str(output_path),
                "glb_path": None,
                "status_msg": "OK",
            },
        )

        try:
            with patch(
                "core.color_card.generate_color_card_svg",
                return_value=str(svg_path),
            ):
                response = client.post(
                    "/api/convert/color-card",
                    json={"session_id": sid},
                )

            assert response.status_code == 200, response.text
            assert response.json()["warnings"] == expected_warnings
            assert response.json()["warnings"].count(warning_code) <= 1
        finally:
            _test_store.close(sid)
            _test_registry.clear_all()


def _create_session_with_preview_and_files(store: SessionStore) -> str:
    """Create a session pre-populated with preview_cache and file paths."""
    sid: str = store.create()
    store.put(
        sid,
        "preview_cache",
        {
            "some": "data",
            "target_w": 120,
            "target_h": 80,
            "target_width_mm": 60.0,
        },
    )
    store.put(sid, "image_path", "/tmp/test_image.png")
    store.put(sid, "source_basename", "test-image")
    store.put(sid, "lut_path", "/tmp/test_lut.npy")
    store.put(sid, "replacement_regions", [])
    store.put(sid, "free_color_set", set())
    return sid


def _create_svg_session(
    store: SessionStore,
    *,
    native_tiling_supported: bool,
    warnings: list[str] | None = None,
) -> tuple[str, str, str]:
    """Create a session for SVG large-format tests with real temp files."""
    fd_svg, svg_path = tempfile.mkstemp(suffix=".svg")
    fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
    try:
        with open(fd_svg, "w", encoding="utf-8", closefd=False) as svg_file:
            svg_file.write(
                '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80">'
                '<rect x="0" y="0" width="120" height="80" fill="#ff0000"/>'
                "</svg>"
            )
        with open(fd_lut, "wb", closefd=False) as lut_file:
            lut_file.write(b"lut")
    finally:
        import os

        os.close(fd_svg)
        os.close(fd_lut)

    sid = store.create()
    store.put(
        sid,
        "preview_cache",
        {
            "target_w": 120,
            "target_h": 80,
            "target_width_mm": 60.0,
        },
    )
    store.put(sid, "image_path", svg_path)
    store.put(sid, "source_basename", "source-artwork")
    store.put(sid, "lut_path", lut_path)
    store.put(sid, "replacement_regions", [])
    store.put(sid, "free_color_set", set())
    store.put(
        sid,
        "svg_large_format_policy",
        {
            "native_tiling_supported": native_tiling_supported,
            "warnings": list(warnings or []),
            "inspection_source": "preview-vector-svg",
        },
    )
    return sid, svg_path, lut_path


def test_generate_rejects_unsupported_build_plate_before_worker() -> None:
    sid = _create_session_with_preview_and_files(_test_store)
    _mock_pool.submit = AsyncMock()
    payload = {
        "session_id": sid,
        "params": {
            "lut_name": "test_lut",
            "printer_id": "bambu-h2d",
            "slicer": "BambuStudio",
            "nozzle_size": "0.4",
            "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
            "build_plate_id": "cool-plate",
        },
    }

    with patch("os.path.exists", return_value=True):
        response = client.post("/api/convert/generate", json=payload)

    assert response.status_code == 422
    assert "Unsupported build plate" in response.json()["detail"]
    _mock_pool.submit.assert_not_called()


def _create_raster_large_format_session(store: SessionStore) -> tuple[str, str, str]:
    """Create a PNG-backed session for large-format route tests."""
    fd_img, image_path = tempfile.mkstemp(suffix=".png")
    fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
    try:
        Image.fromarray(np.zeros((20, 20, 3), dtype=np.uint8)).save(image_path)
        with open(lut_path, "wb") as lut_file:
            lut_file.write(b"lut")
    finally:
        os.close(fd_img)
        os.close(fd_lut)

    sid = store.create()
    store.put(
        sid,
        "preview_cache",
        {
            "target_w": 120,
            "target_h": 80,
            "target_width_mm": 60.0,
            "material_matrix": np.zeros((4, 4, 5), dtype=np.uint8),
            "lut_metadata": SimpleNamespace(layer_order="Top2Bottom", base_channel_idx=0),
        },
    )
    store.put(sid, "image_path", image_path)
    store.put(sid, "source_basename", "poster")
    store.put(sid, "lut_path", lut_path)
    store.put(sid, "replacement_regions", [])
    store.put(sid, "free_color_set", set())
    store.put(
        sid,
        "selected_region_masks",
        {"region-1": np.ones((4, 4), dtype=bool)},
    )
    store.put(
        sid,
        "recipe_overrides",
        [{"region_id": "region-1", "recipe": [1, 1, 1, 1, 1], "layer_order": "Top2Bottom"}],
    )
    return sid, image_path, lut_path


def _large_format_success_response(kind: str) -> dict[str, object]:
    """Return a complete large-format helper response for route isolation."""

    return {
        "status": "ok",
        "message": kind,
        "download_url": f"/api/files/{kind}",
        "tile_count": 1,
        "grid_cols": 1,
        "grid_rows": 1,
        "warnings": [],
    }


def _large_format_payload(
    sid: str,
    *,
    modeling_mode: str,
    use_cached_matched_rgb: bool,
    target_width_mm: float = 120.0,
    target_height_mm: float = 80.0,
    request_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a large-format route payload with explicit physical dimensions."""

    return {
        "session_id": sid,
        "params": {
            "target_height_mm": target_height_mm,
            "tile_width_mm": 40.0,
            "tile_height_mm": 40.0,
            "params": {
                "lut_name": "test_lut",
                "modeling_mode": modeling_mode,
                "target_width_mm": target_width_mm,
                "use_cached_matched_rgb": use_cached_matched_rgb,
                **(request_overrides or {}),
            },
        },
    }


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
        assert response.json()["detail"] == (
            "Source image is unavailable. Re-upload the image, run preview, and try again."
        )

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
        expected_fridge_magnets = [
            {
                "id": "magnet-round",
                "shape": "round",
                "preset_key": "round-18",
                "diameter_mm": 18.0,
                "width_mm": None,
                "height_mm": None,
                "thickness_mm": 2.0,
                "center_x_mm": 20.0,
                "center_y_mm": 25.0,
            },
            {
                "id": "magnet-rect",
                "shape": "rect",
                "preset_key": "rect-20x10",
                "diameter_mm": None,
                "width_mm": 20.0,
                "height_mm": 10.0,
                "thickness_mm": 2.5,
                "center_x_mm": 40.0,
                "center_y_mm": 15.0,
            },
        ]

        payload = {
            "session_id": sid,
            "params": {
                "lut_name": "test_lut",
                "target_width_mm": 80.0,
                "spacer_thick": 1.5,
                "structure_mode": "Single-sided",
                "color_mode": "4-Color (RYBW)",
                "modeling_mode": "high-fidelity",
                "model_enable": True,
                "model_only": False,
                "model_threshold": 6.5,
                "model_margin": 0.9,
                "quantize_colors": 64,
                "enable_cleanup": False,
                "separate_backing": True,
                "add_loop": True,
                "loop_width": 5.0,
                "loop_length": 10.0,
                "loop_hole": 3.0,
                "loop_pos": [50.0, 50.0],
                "enable_fridge_magnet": True,
                "fridge_magnets": expected_fridge_magnets,
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
                "printer_id": "bambu-p1s",
                "slicer": "OrcaSlicer",
                "nozzle_size": "0.2",
                "device_profile_id": "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
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
        assert body["preview_3d_url"] is None
        assert body["threemf_disk_path"] is None
        assert "/tmp/out.3mf" not in response.text

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
        assert submitted_params["spacer_thick"] == 2.96
        assert submitted_params["structure_mode"] == "Single-sided"
        assert submitted_params["color_mode"] == "4-Color (RYBW)"
        assert submitted_params["model_enable"] is True
        assert submitted_params["model_only"] is False
        assert submitted_params["model_threshold"] == 6.5
        assert submitted_params["model_margin"] == 0.9
        assert submitted_params["quantize_colors"] == 64
        assert submitted_params["enable_cleanup"] is False
        assert submitted_params["separate_backing"] is True
        assert submitted_params["nozzle_size"] == "0.2"
        assert submitted_params["device_profile_id"] == "OrcaSlicer:bbl:bambu-lab-p1s:0.2"

        # Verify modeling_mode is converted to core enum
        assert submitted_params["modeling_mode"] == CoreModelingMode("high-fidelity")

        # Verify keychain loop parameters
        assert submitted_params["add_loop"] is True
        assert submitted_params["loop_width"] == 5.0
        assert submitted_params["loop_length"] == 10.0
        assert submitted_params["loop_hole"] == 3.0
        assert submitted_params["loop_pos"] == (50.0, 50.0)
        assert submitted_params["enable_fridge_magnet"] is True
        assert submitted_params["fridge_magnets"] == expected_fridge_magnets

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
        assert submitted_params["enable_base_layer_height_modifier"] is True

    def test_vector_generate_forwards_parse_clip_cache_path(self, tmp_path) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)
        source_path = tmp_path / "source.svg"
        source_path.write_bytes(b"x" * (2 * 1024**2))
        parse_cache_path = tmp_path / "vector-parse-cache.pkl"
        parse_cache_path.write_bytes(b"x" * (3 * 1024**2 // 2))
        lut_path = tmp_path / "test-lut.npy"
        np.save(lut_path, np.zeros((1, 3), dtype=np.uint8))
        _test_store.put(sid, "image_path", str(source_path))
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(
            sid,
            "preview_cache",
            {
                "target_w": 120,
                "target_h": 80,
                "target_width_mm": 60.0,
                "vector_parse_clip_cache_path": str(parse_cache_path),
            },
        )
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": "/tmp/out.3mf",
                "glb_path": None,
                "status_msg": "OK",
            },
        )
        payload = {
            "session_id": sid,
            "params": {
                "lut_name": "test_lut",
                "modeling_mode": "vector",
            },
        }

        with patch("os.path.exists", return_value=True):
            response = client.post("/api/convert/generate", json=payload)

        assert response.status_code == 200, response.text
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["vector_parse_clip_cache_path"] == str(
            parse_cache_path
        )

    def test_color_card_generate_uses_source_palette(self, tmp_path) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)
        lut_path = tmp_path / "test-lut.npy"
        np.save(lut_path, np.zeros((1, 3), dtype=np.uint8))
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(
            sid,
            "preview_cache",
            {
                "target_w": 120,
                "target_h": 80,
                "target_width_mm": 60.0,
                "color_palette": [
                    {"hex": "#ffffff", "count": 1000, "percentage": 80.0},
                    {"hex": "#ff0000", "count": 100, "percentage": 10.0},
                    {"hex": "#00ff00", "count": 100, "percentage": 10.0},
                ],
                "color_card_source_palette": [
                    {"hex": "#ff0000", "count": 100, "percentage": 50.0},
                    {"hex": "#00ff00", "count": 100, "percentage": 50.0},
                ],
                "vector_parse_clip_cache_path": "/tmp/old-vector-parse-cache.pkl",
            },
        )
        captured: dict[str, object] = {}

        def _fake_generate_color_card_svg(hex_colors, **_kwargs):
            fd, svg_path = tempfile.mkstemp(suffix=".svg")
            os.close(fd)
            with open(svg_path, "w", encoding="utf-8") as svg_file:
                svg_file.write("<svg></svg>")
            captured["hex_colors"] = list(hex_colors)
            captured["svg_path"] = svg_path
            return svg_path

        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": "/tmp/out.3mf",
                "glb_path": None,
                "status_msg": "OK",
            },
        )
        payload = {
            "session_id": sid,
            "params": {
                "lut_name": "test_lut",
                "modeling_mode": "color-card",
            },
        }

        with (
            patch("core.color_card.generate_color_card_svg", _fake_generate_color_card_svg),
            patch("os.path.exists", return_value=True),
        ):
            response = client.post("/api/convert/generate", json=payload)

        assert response.status_code == 200, response.text
        assert captured["hex_colors"] == ["#ff0000", "#00ff00"]
        submitted_image_path = _mock_pool.submit.call_args.args[1]
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_image_path == captured["svg_path"]
        assert submitted_params["modeling_mode"] == CoreModelingMode.VECTOR
        assert submitted_params["vector_parse_clip_cache_path"] is None


    def test_dynamic_color_card_rejects_before_svg_or_session_mutation(
        self,
        tmp_path,
    ) -> None:
        _test_store.clear_all()
        image_path = tmp_path / "input.png"
        Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
        sid = _test_store.create()
        _test_store.put(sid, "image_path", str(image_path))
        _test_store.put(sid, "lut_path", "__material_archive__")
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(sid, "selected_materials", ["mat-a", "mat-b"])
        _test_store.put(sid, "material_dynamic_layer_count_enabled", True)
        _test_store.put(sid, "material_min_layer_count", 5)
        _test_store.put(sid, "material_max_layer_count", 8)
        _test_store.put(sid, "material_delta_e00_tolerance", 0.5)
        _test_store.put(
            sid,
            "preview_cache",
            {
                "target_w": 4,
                "target_h": 4,
                "target_width_mm": 40.0,
                "color_palette": [{"hex": "#ff0000"}],
                "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
                "mask_solid": np.ones((4, 4), dtype=bool),
                "material_matrix": np.zeros((4, 4, 8), dtype=np.uint8),
            },
        )
        _mock_pool.submit = AsyncMock()

        with (
            patch("core.color_card.generate_color_card_svg") as generate_svg,
            patch.object(_test_store, "register_temp_file") as register_temp,
        ):
            generate_svg.return_value = str(tmp_path / "card.svg")
            response = client.post(
                "/api/convert/generate",
                json={
                    "session_id": sid,
                    "params": {
                        "lut_name": "__material_archive__",
                        "modeling_mode": "color-card",
                    },
                },
            )

        assert response.status_code == 422
        generate_svg.assert_not_called()
        register_temp.assert_not_called()
        _mock_pool.submit.assert_not_called()

    def test_color_card_endpoint_rejects_dynamic_session_before_svg(
        self,
    ) -> None:
        _test_store.clear_all()
        sid = _test_store.create()
        _test_store.put(sid, "lut_path", "__material_archive__")
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(sid, "material_dynamic_layer_count_enabled", True)
        _test_store.put(sid, "material_min_layer_count", 5)
        _test_store.put(sid, "material_max_layer_count", 8)
        _test_store.put(sid, "material_delta_e00_tolerance", 0.5)
        _test_store.put(
            sid,
            "preview_cache",
            {
                "target_w": 4,
                "target_h": 4,
                "target_width_mm": 40.0,
                "color_palette": [{"hex": "#ff0000"}],
            },
        )
        _mock_pool.submit = AsyncMock()

        with (
            patch("core.color_card.generate_color_card_svg") as generate_svg,
            patch.object(_test_store, "register_temp_file") as register_temp,
        ):
            response = client.post(
                "/api/convert/color-card",
                json={"session_id": sid},
            )

        assert response.status_code == 422
        generate_svg.assert_not_called()
        register_temp.assert_not_called()
        _mock_pool.submit.assert_not_called()

    def test_color_card_endpoint_reads_artifact_metadata_without_hydrating(
        self,
        tmp_path,
    ) -> None:
        _test_store.clear_all()
        lut_path = tmp_path / "source.npy"
        out_path = tmp_path / "card.3mf"
        lut_path.write_bytes(b"lut")
        out_path.write_bytes(b"3mf")

        sid = _test_store.create()
        cache_ref = externalize_preview_cache(
            sid,
            _test_store,
            {
                "target_w": 4,
                "target_h": 4,
                "target_width_mm": 40.0,
                "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
                "mask_solid": np.ones((4, 4), dtype=bool),
                "material_matrix": np.zeros((4, 4, 5), dtype=np.uint8),
                "color_palette": [
                    {"hex": "#ff0000"},
                    {"hex": "#00ff00"},
                ],
                "color_mode": "4-Color (RYBW)",
                "color_conf": {"layer_count": 5},
            },
            root_dir=tmp_path,
        )
        _test_store.put(sid, "preview_cache", cache_ref)
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(sid, "material_source", "lut")

        captured: dict[str, object] = {}

        def _fake_generate_color_card_svg(hex_colors, **_kwargs):
            svg_path = tmp_path / "card.svg"
            svg_path.write_text("<svg></svg>", encoding="utf-8")
            captured["hex_colors"] = list(hex_colors)
            captured["svg_path"] = str(svg_path)
            return str(svg_path)

        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": str(out_path),
                "glb_path": None,
                "status_msg": "OK",
            },
        )

        with (
            patch(
                "api.routers.converter.common.hydrate_preview_cache",
                side_effect=AssertionError("color-card must not hydrate artifact arrays"),
            ),
            patch("core.color_card.generate_color_card_svg", _fake_generate_color_card_svg),
        ):
            response = client.post(
                "/api/convert/color-card",
                json={
                    "session_id": sid,
                    "printer_id": "bambu-p1s",
                    "slicer": "OrcaSlicer",
                    "nozzle_size": "0.2",
                    "device_profile_id": "OrcaSlicer:bbl:bambu-lab-p1s:0.2",
                    "build_plate_id": "smooth-high-temp-plate",
                },
            )

        assert response.status_code == 200, response.text
        assert captured["hex_colors"] == ["#ff0000", "#00ff00"]
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["color_layers"] == 5
        assert submitted_params["printer_id"] == "bambu-p1s"
        assert submitted_params["slicer"] == "OrcaSlicer"
        assert submitted_params["nozzle_size"] == "0.2"
        assert submitted_params["device_profile_id"] == (
            "OrcaSlicer:bbl:bambu-lab-p1s:0.2"
        )
        assert submitted_params["build_plate_id"] == "smooth-high-temp-plate"

    def test_color_card_endpoint_rejects_unsupported_plate_before_svg(
        self,
        tmp_path,
    ) -> None:
        _test_store.clear_all()
        lut_path = tmp_path / "source.npy"
        lut_path.write_bytes(b"lut")
        sid = _test_store.create()
        _test_store.put(
            sid,
            "preview_cache",
            {
                "target_w": 4,
                "target_h": 4,
                "target_width_mm": 40.0,
                "color_palette": [{"hex": "#ff0000"}],
            },
        )
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(sid, "material_source", "lut")
        _mock_pool.submit = AsyncMock()

        with patch("core.color_card.generate_color_card_svg") as generate_svg:
            response = client.post(
                "/api/convert/color-card",
                json={
                    "session_id": sid,
                    "printer_id": "bambu-h2d",
                    "slicer": "BambuStudio",
                    "nozzle_size": "0.4",
                    "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
                    "build_plate_id": "cool-plate",
                },
            )

        assert response.status_code == 422
        assert "Unsupported build plate" in response.json()["detail"]
        generate_svg.assert_not_called()
        _mock_pool.submit.assert_not_called()

    def test_color_card_worker_exception_uses_public_error_language(
        self,
        tmp_path,
    ) -> None:
        lut_path = tmp_path / "source.npy"
        lut_path.write_bytes(b"lut")
        private_path = "/Users/min/private/color-card.svg"

        sid = _test_store.create()
        _test_store.put(
            sid,
            "preview_cache",
            {
                "target_w": 4,
                "target_h": 4,
                "target_width_mm": 40.0,
                "color_palette": [{"hex": "#ff0000"}, {"hex": "#00ff00"}],
            },
        )
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(sid, "material_source", "lut")

        def _fake_generate_color_card_svg(hex_colors, **_kwargs):
            svg_path = tmp_path / "card.svg"
            svg_path.write_text("<svg></svg>", encoding="utf-8")
            return str(svg_path)

        _mock_pool.submit = AsyncMock(
            side_effect=RuntimeError(f"cannot open {private_path}: invalid vector")
        )

        try:
            with patch("core.color_card.generate_color_card_svg", _fake_generate_color_card_svg):
                response = client.post(
                    "/api/convert/color-card",
                    json={"session_id": sid},
                )

            assert response.status_code == 500
            assert response.json()["detail"] == (
                "Color card 3MF generation failed. Re-run preview and try "
                "generating the color card again."
            )
            assert private_path not in response.text
            assert "invalid vector" not in response.text
        finally:
            _test_store.close(sid)

    def test_color_card_missing_worker_output_uses_public_error_language(
        self,
        tmp_path,
    ) -> None:
        lut_path = tmp_path / "source.npy"
        lut_path.write_bytes(b"lut")
        private_path = "/Users/min/private/card.3mf"

        sid = _test_store.create()
        _test_store.put(
            sid,
            "preview_cache",
            {
                "target_w": 4,
                "target_h": 4,
                "target_width_mm": 40.0,
                "color_palette": [{"hex": "#ff0000"}, {"hex": "#00ff00"}],
            },
        )
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(sid, "material_source", "lut")

        def _fake_generate_color_card_svg(hex_colors, **_kwargs):
            svg_path = tmp_path / "card.svg"
            svg_path.write_text("<svg></svg>", encoding="utf-8")
            return str(svg_path)

        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": private_path,
                "glb_path": None,
                "status_msg": f"cannot write {private_path}: permission denied",
            }
        )

        try:
            with patch("core.color_card.generate_color_card_svg", _fake_generate_color_card_svg):
                response = client.post(
                    "/api/convert/color-card",
                    json={"session_id": sid},
                )

            assert response.status_code == 500
            assert response.json()["detail"] == (
                "Color card 3MF generation failed. Re-run preview and try "
                "generating the color card again."
            )
            assert private_path not in response.text
            assert "permission denied" not in response.text
        finally:
            _test_store.close(sid)

    def test_material_archive_vector_forwards_cached_material_matrix_without_region_replace(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)
        preview_cache = _test_store.get(sid)["preview_cache"]
        preview_cache["matched_rgb"] = np.zeros((4, 4, 3), dtype=np.uint8)
        preview_cache["height_identity_rgb"] = np.full(
            (4, 4, 3), [190, 230, 248], dtype=np.uint8
        )
        preview_cache["mask_solid"] = np.ones((4, 4), dtype=bool)
        preview_cache["material_matrix"] = np.ones((4, 4, 5), dtype=np.int32)
        _test_store.put(sid, "preview_cache", preview_cache)
        _test_store.put(sid, "material_source", "material_archive")

        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": "/tmp/out.3mf",
                "glb_path": "/tmp/out.glb",
                "status_msg": "OK",
            }
        )
        payload = {
            "session_id": sid,
            "params": {
                "lut_name": "__material_archive__",
                "modeling_mode": "vector",
                "use_cached_matched_rgb": False,
            },
        }

        with patch("os.path.exists", return_value=True):
            response = client.post("/api/convert/generate", json=payload)

        assert response.status_code == 200
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["matched_rgb_path"] is not None
        assert submitted_params["height_identity_rgb_path"] is not None
        assert submitted_params["mask_solid_path"] is not None
        assert submitted_params["material_matrix_path"] is not None
        np.testing.assert_array_equal(
            np.load(submitted_params["material_matrix_path"]),
            preview_cache["material_matrix"],
        )
        np.testing.assert_array_equal(
            np.load(submitted_params["height_identity_rgb_path"]),
            preview_cache["height_identity_rgb"],
        )

    @pytest.mark.parametrize("preview_changes, enabled", [
        ({"svg_hole_compensation_enabled": False}, True),
        ({"svg_hole_max_area_mm2": 0.1}, True),
        ({"svg_hole_max_width_mm": 0.05}, True),
        ({"target_width_mm": 100.0}, True),
        ({"svg_hole_compensation_enabled": True}, False),
        ({}, True),
    ])
    def test_material_archive_compensation_requires_matching_preview(
        self, tmp_path, preview_changes, enabled,
    ) -> None:
        source = tmp_path / "source.svg"
        source.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        sid = _create_session_with_preview_and_files(_test_store)
        request = ConvertGenerateRequest(
            lut_name="__material_archive__", modeling_mode="vector",
            target_width_mm=220.0, use_cached_matched_rgb=False,
            svg_hole_compensation_enabled=enabled,
            svg_hole_max_area_mm2=0.75, svg_hole_max_width_mm=0.12,
        )
        cache = {
            **request.model_dump(), "material_source": "material_archive",
            "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
            "mask_solid": np.ones((4, 4), dtype=bool),
            "material_matrix": np.ones((4, 4, 5), dtype=np.int32),
            **preview_changes,
        }
        _test_store.put(sid, "preview_cache", cache)
        _test_store.put(sid, "image_path", str(source))
        _test_store.put(sid, "material_source", "material_archive")
        _mock_pool.submit = AsyncMock(return_value={
            "threemf_path": "/tmp/out.3mf", "glb_path": None, "status_msg": "OK",
        })
        try:
            with patch("os.path.exists", return_value=True):
                response = client.post("/api/convert/generate", json={
                    "session_id": sid, "params": request.model_dump(mode="json"),
                })
            if preview_changes:
                assert response.status_code == 409, response.text
                _mock_pool.submit.assert_not_called()
            else:
                assert response.status_code == 200, response.text
                params = _mock_pool.submit.call_args.args[3]
                assert params["svg_hole_compensation_enabled"] is True
                assert params["material_matrix_path"] is not None
        finally:
            _test_store.close(sid)

    def test_generate_artifact_cache_forwards_field_paths_without_hydrating(
        self,
        tmp_path,
    ) -> None:
        """Artifact-backed generate must not hydrate arrays in the main process."""
        _test_store.clear_all()
        image_path = tmp_path / "input.png"
        lut_path = tmp_path / "source.npy"
        out_path = tmp_path / "out.3mf"
        Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
        lut_path.write_bytes(b"lut")
        out_path.write_bytes(b"3mf")

        sid = _test_store.create()
        request = ConvertGenerateRequest(
            lut_name="test_lut",
            target_width_mm=40.0,
            use_cached_matched_rgb=True,
        )
        cache_ref = externalize_preview_cache(
            sid,
            _test_store,
            {
                "target_w": 4,
                "target_h": 4,
                "target_width_mm": 40.0,
                "color_mode": request.color_mode.value,
                "modeling_mode": request.modeling_mode.value,
                "color_layers": request.color_layers,
                "layer_height_mm": request.layer_height_mm,
                "quantize_colors": request.quantize_colors,
                "enable_cleanup": request.enable_cleanup,
                "hue_weight": request.hue_weight,
                "chroma_gate": request.chroma_gate,
                "use_lut_constrained": request.use_lut_constrained,
                "auto_dynamic_range": request.auto_dynamic_range,
                "model_enable": request.model_enable,
                "model_only": request.model_only,
                "model_threshold": request.model_threshold,
                "model_margin": request.model_margin,
                "svg_pixels_per_mm": request.svg_pixels_per_mm,
                "material_source": "lut",
                "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
                "height_identity_rgb": np.full(
                    (4, 4, 3), [190, 230, 248], dtype=np.uint8
                ),
                "mask_solid": np.ones((4, 4), dtype=bool),
                "material_matrix": np.zeros((4, 4, 5), dtype=np.uint8),
            },
            root_dir=tmp_path,
        )
        _test_store.put(sid, "preview_cache", cache_ref)
        _test_store.put(sid, "image_path", str(image_path))
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "free_color_set", set())
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": str(out_path),
                "glb_path": None,
                "status_msg": "OK",
            },
        )

        with patch(
            "api.routers.converter.common.hydrate_preview_cache",
            side_effect=AssertionError("generate must not fully hydrate artifact cache"),
        ):
            response = client.post(
                "/api/convert/generate",
                json={
                    "session_id": sid,
                    "params": request.model_dump(mode="json"),
                },
            )

        assert response.status_code == 200, response.text
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["matched_rgb_path"] == cache_ref["fields"]["matched_rgb"]["path"]
        assert submitted_params["height_identity_rgb_path"] == cache_ref["fields"]["height_identity_rgb"]["path"]
        assert submitted_params["mask_solid_path"] == cache_ref["fields"]["mask_solid"]["path"]
        assert submitted_params["material_matrix_path"] == cache_ref["fields"]["material_matrix"]["path"]

    def test_generate_artifact_cache_rejects_relief_height_below_manifest_depth(
        self,
        tmp_path,
    ) -> None:
        _test_store.clear_all()
        image_path = tmp_path / "input.png"
        out_path = tmp_path / "out.3mf"
        Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
        out_path.write_bytes(b"3mf")

        sid = _test_store.create()
        cache_ref = externalize_preview_cache(
            sid,
            _test_store,
            {
                "target_w": 4,
                "target_h": 4,
                "target_width_mm": 40.0,
                "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
                "mask_solid": np.ones((4, 4), dtype=bool),
                "material_matrix": np.zeros((4, 4, 10), dtype=np.uint8),
            },
            root_dir=tmp_path,
        )
        _test_store.put(sid, "preview_cache", cache_ref)
        _test_store.put(sid, "image_path", str(image_path))
        _test_store.put(sid, "lut_path", "__material_archive__")
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(sid, "selected_materials", ["mat-a", "mat-b"])
        _test_store.put(sid, "material_layer_count", 5)
        _test_store.put(sid, "material_layer_height_mm", 0.08)
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "free_color_set", set())
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": str(out_path),
                "glb_path": None,
                "status_msg": "OK",
            },
        )

        response = client.post(
            "/api/convert/generate",
            json={
                "session_id": sid,
                "params": {
                    "lut_name": "__material_archive__",
                    "enable_relief": True,
                    "height_mode": "color",
                    "color_height_map": {"#111111": 0.6},
                    "heightmap_max_height": 0.6,
                },
            },
        )

        assert response.status_code == 422, response.text
        assert "0.80 mm" in response.json()["detail"]
        _mock_pool.submit.assert_not_called()

    def test_generate_reuses_artifact_preview_analysis_when_params_match(
        self,
        tmp_path,
    ) -> None:
        """Default raster generate should reuse matching preview analysis artifacts."""
        _test_store.clear_all()
        image_path = tmp_path / "input.png"
        lut_path = tmp_path / "source.npy"
        out_path = tmp_path / "out.3mf"
        Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
        lut_path.write_bytes(b"lut")
        out_path.write_bytes(b"3mf")

        sid = _test_store.create()
        cache_ref = externalize_preview_cache(
            sid,
            _test_store,
            {
                "target_w": 4,
                "target_h": 4,
                "target_width_mm": 40.0,
                "color_mode": "4-Color (RYBW)",
                "modeling_mode": "high-fidelity",
                "color_layers": 5,
                "layer_height_mm": 0.08,
                "quantize_colors": 48,
                "enable_cleanup": True,
                "hue_weight": 0.0,
                "chroma_gate": 15.0,
                "use_lut_constrained": False,
                "auto_dynamic_range": False,
                "model_enable": False,
                "model_only": False,
                "model_threshold": None,
                "model_margin": None,
                "svg_pixels_per_mm": 10.0,
                "material_source": "lut",
                "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
                "mask_solid": np.ones((4, 4), dtype=bool),
                "material_matrix": np.zeros((4, 4, 5), dtype=np.uint8),
            },
            root_dir=tmp_path,
        )
        _test_store.put(sid, "preview_cache", cache_ref)
        _test_store.put(sid, "image_path", str(image_path))
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(sid, "color_mode", "4-Color (RYBW)")
        _test_store.put(sid, "modeling_mode", "high-fidelity")
        _test_store.put(sid, "color_layers", 5)
        _test_store.put(sid, "layer_height_mm", 0.08)
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "free_color_set", set())
        _test_store.put(sid, "material_source", "lut")
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": str(out_path),
                "glb_path": None,
                "status_msg": "OK",
            },
        )

        response = client.post(
            "/api/convert/generate",
            json={
                "session_id": sid,
                "params": {
                    "lut_name": "test_lut",
                    "target_width_mm": 40.0,
                    "color_mode": "4-Color (RYBW)",
                    "modeling_mode": "high-fidelity",
                    "color_layers": 5,
                    "layer_height_mm": 0.08,
                    "quantize_colors": 48,
                    "enable_cleanup": True,
                    "svg_pixels_per_mm": 10.0,
                },
            },
        )

        assert response.status_code == 200, response.text
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["reuse_preview_analysis"] is True
        assert submitted_params["matched_rgb_path"] == cache_ref["fields"]["matched_rgb"]["path"]
        assert submitted_params["mask_solid_path"] == cache_ref["fields"]["mask_solid"]["path"]
        assert submitted_params["material_matrix_path"] == cache_ref["fields"]["material_matrix"]["path"]
        assert submitted_params["color_layers"] == 5
        assert submitted_params["layer_height_mm"] == pytest.approx(0.08)

    def test_generate_forwards_ready_preview_glb_when_analysis_params_match(
        self,
        tmp_path,
    ) -> None:
        """Default raster generate should reuse the already-built preview GLB."""
        _test_store.clear_all()
        _test_registry.clear_all()
        image_path = tmp_path / "input.png"
        lut_path = tmp_path / "source.npy"
        out_path = tmp_path / "out.3mf"
        preview_glb_path = tmp_path / "preview.glb"
        Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
        lut_path.write_bytes(b"lut")
        out_path.write_bytes(b"3mf")
        preview_glb_path.write_bytes(b"glb")

        sid = _test_store.create()
        preview_glb_id = _test_registry.register_path(sid, str(preview_glb_path))
        cache_ref = externalize_preview_cache(
            sid,
            _test_store,
            {
                "target_w": 4,
                "target_h": 4,
                "target_width_mm": 40.0,
                "color_mode": "4-Color (RYBW)",
                "modeling_mode": "high-fidelity",
                "color_layers": 5,
                "layer_height_mm": 0.08,
                "quantize_colors": 48,
                "enable_cleanup": True,
                "hue_weight": 0.0,
                "chroma_gate": 15.0,
                "use_lut_constrained": False,
                "auto_dynamic_range": False,
                "model_enable": False,
                "model_only": False,
                "model_threshold": None,
                "model_margin": None,
                "svg_pixels_per_mm": 10.0,
                "material_source": "lut",
                "high_precision_3d_preview": False,
                "glb_url": f"/api/files/{preview_glb_id}",
                "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
                "mask_solid": np.ones((4, 4), dtype=bool),
                "material_matrix": np.zeros((4, 4, 5), dtype=np.uint8),
            },
            root_dir=tmp_path,
        )
        _test_store.put(sid, "preview_cache", cache_ref)
        _test_store.put(sid, "image_path", str(image_path))
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(sid, "color_mode", "4-Color (RYBW)")
        _test_store.put(sid, "modeling_mode", "high-fidelity")
        _test_store.put(sid, "color_layers", 5)
        _test_store.put(sid, "layer_height_mm", 0.08)
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "free_color_set", set())
        _test_store.put(sid, "material_source", "lut")
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": str(out_path),
                "glb_path": None,
                "status_msg": "OK",
            },
        )

        response = client.post(
            "/api/convert/generate",
            json={
                "session_id": sid,
                "params": {
                    "lut_name": "test_lut",
                    "target_width_mm": 40.0,
                    "color_mode": "4-Color (RYBW)",
                    "modeling_mode": "high-fidelity",
                    "color_layers": 5,
                    "layer_height_mm": 0.08,
                    "quantize_colors": 48,
                    "enable_cleanup": True,
                    "svg_pixels_per_mm": 10.0,
                    "high_precision_3d_preview": False,
                },
            },
        )

        assert response.status_code == 200, response.text
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["reuse_preview_analysis"] is True
        assert submitted_params["preview_glb_path"] == str(preview_glb_path)

        loop_response = client.post(
            "/api/convert/generate",
            json={
                "session_id": sid,
                "params": {
                    "lut_name": "test_lut",
                    "target_width_mm": 40.0,
                    "color_mode": "4-Color (RYBW)",
                    "modeling_mode": "high-fidelity",
                    "color_layers": 5,
                    "layer_height_mm": 0.08,
                    "quantize_colors": 48,
                    "enable_cleanup": True,
                    "svg_pixels_per_mm": 10.0,
                    "high_precision_3d_preview": False,
                    "add_loop": True,
                },
            },
        )

        assert loop_response.status_code == 200, loop_response.text
        loop_params = _mock_pool.submit.call_args.args[3]
        assert loop_params["reuse_preview_analysis"] is False
        assert loop_params["preview_glb_path"] is None

    def test_generate_reuses_preview_analysis_when_optional_layer_defaults_match(
        self,
        tmp_path,
    ) -> None:
        """Omitted layer settings should match preview-derived LUT defaults."""
        _test_store.clear_all()
        image_path = tmp_path / "input.png"
        lut_path = tmp_path / "source.npy"
        out_path = tmp_path / "out.3mf"
        Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
        lut_path.write_bytes(b"lut")
        out_path.write_bytes(b"3mf")

        sid = _test_store.create()
        cache_ref = externalize_preview_cache(
            sid,
            _test_store,
            {
                "target_w": 4,
                "target_h": 4,
                "target_width_mm": 40.0,
                "color_mode": "4-Color (RYBW)",
                "modeling_mode": "high-fidelity",
                "color_layers": 5,
                "layer_height_mm": 0.08,
                "quantize_colors": 48,
                "enable_cleanup": True,
                "hue_weight": 0.0,
                "chroma_gate": 15.0,
                "use_lut_constrained": False,
                "auto_dynamic_range": False,
                "model_enable": False,
                "model_only": False,
                "model_threshold": None,
                "model_margin": None,
                "svg_pixels_per_mm": 10.0,
                "material_source": "lut",
                "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
                "mask_solid": np.ones((4, 4), dtype=bool),
                "material_matrix": np.zeros((4, 4, 5), dtype=np.uint8),
            },
            root_dir=tmp_path,
        )
        _test_store.put(sid, "preview_cache", cache_ref)
        _test_store.put(sid, "image_path", str(image_path))
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(sid, "color_mode", "4-Color (RYBW)")
        _test_store.put(sid, "modeling_mode", "high-fidelity")
        _test_store.put(sid, "color_layers", None)
        _test_store.put(sid, "layer_height_mm", None)
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "free_color_set", set())
        _test_store.put(sid, "material_source", "lut")
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": str(out_path),
                "glb_path": None,
                "status_msg": "OK",
            },
        )

        response = client.post(
            "/api/convert/generate",
            json={
                "session_id": sid,
                "params": {
                    "lut_name": "test_lut",
                    "target_width_mm": 40.0,
                    "color_mode": "4-Color (RYBW)",
                    "modeling_mode": "high-fidelity",
                    "quantize_colors": 48,
                    "enable_cleanup": True,
                    "svg_pixels_per_mm": 10.0,
                },
            },
        )

        assert response.status_code == 200, response.text
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["reuse_preview_analysis"] is True
        assert submitted_params["matched_rgb_path"] == cache_ref["fields"]["matched_rgb"]["path"]
        assert submitted_params["mask_solid_path"] == cache_ref["fields"]["mask_solid"]["path"]
        assert submitted_params["material_matrix_path"] == cache_ref["fields"]["material_matrix"]["path"]

    def test_generate_does_not_reuse_preview_analysis_when_params_mismatch(
        self,
        tmp_path,
    ) -> None:
        """A mismatched preview-analysis parameter must fall back to full S02."""
        _test_store.clear_all()
        image_path = tmp_path / "input.png"
        lut_path = tmp_path / "source.npy"
        out_path = tmp_path / "out.3mf"
        Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
        lut_path.write_bytes(b"lut")
        out_path.write_bytes(b"3mf")

        sid = _test_store.create()
        cache_ref = externalize_preview_cache(
            sid,
            _test_store,
            {
                "target_w": 4,
                "target_h": 4,
                "target_width_mm": 40.0,
                "color_mode": "4-Color (RYBW)",
                "modeling_mode": "high-fidelity",
                "color_layers": 5,
                "layer_height_mm": 0.08,
                "quantize_colors": 48,
                "enable_cleanup": False,
                "hue_weight": 0.0,
                "chroma_gate": 15.0,
                "use_lut_constrained": False,
                "auto_dynamic_range": False,
                "model_enable": False,
                "model_only": False,
                "model_threshold": None,
                "model_margin": None,
                "svg_pixels_per_mm": 10.0,
                "material_source": "lut",
                "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
                "mask_solid": np.ones((4, 4), dtype=bool),
                "material_matrix": np.zeros((4, 4, 5), dtype=np.uint8),
            },
            root_dir=tmp_path,
        )
        _test_store.put(sid, "preview_cache", cache_ref)
        _test_store.put(sid, "image_path", str(image_path))
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "free_color_set", set())
        _test_store.put(sid, "material_source", "lut")
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": str(out_path),
                "glb_path": None,
                "status_msg": "OK",
            },
        )

        response = client.post(
            "/api/convert/generate",
            json={
                "session_id": sid,
                "params": {
                    "lut_name": "test_lut",
                    "target_width_mm": 40.0,
                    "color_mode": "4-Color (RYBW)",
                    "modeling_mode": "high-fidelity",
                    "color_layers": 5,
                    "layer_height_mm": 0.08,
                    "quantize_colors": 48,
                    "enable_cleanup": True,
                    "svg_pixels_per_mm": 10.0,
                },
            },
        )

        assert response.status_code == 200, response.text
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["reuse_preview_analysis"] is False
        assert submitted_params["matched_rgb_path"] is None
        assert submitted_params["mask_solid_path"] is None
        assert submitted_params["material_matrix_path"] is None

    def test_generate_heightmap_mode_rejects_missing_session_heightmap(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)
        payload = {
            "session_id": sid,
            "params": {
                "lut_name": "test_lut",
                "enable_relief": True,
                "height_mode": "heightmap",
                "color_height_map": {"#ff0000": 2.88},
                "heightmap_max_height": 2.88,
            },
        }
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": "/tmp/out.3mf",
                "glb_path": "/tmp/out.glb",
                "status_msg": "OK",
            }
        )

        with patch("os.path.exists", return_value=True):
            response = client.post("/api/convert/generate", json=payload)

        assert response.status_code == 409
        assert "heightmap" in response.json()["detail"].lower()
        _mock_pool.submit.assert_not_called()

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

    def test_generate_passes_enable_base_layer_modifier_false(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)

        payload = {
            "session_id": sid,
            "params": {
                "lut_name": "test_lut",
                "enable_base_layer_height_modifier": False,
                "enable_wipe_tower_auto_placement": False,
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
        assert submitted_params["enable_base_layer_height_modifier"] is False
        assert submitted_params["enable_wipe_tower_auto_placement"] is False

    def test_generated_download_survives_source_session_close(self) -> None:
        fd_img, image_path = tempfile.mkstemp(suffix=".png")
        fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
        fd_out, out_path = tempfile.mkstemp(suffix=".3mf")
        try:
            os.write(fd_img, b"image")
            os.write(fd_lut, b"lut")
            os.write(fd_out, b"3mf payload")
        finally:
            os.close(fd_img)
            os.close(fd_lut)
            os.close(fd_out)

        sid = _test_store.create()
        _test_store.put(sid, "preview_cache", {"some": "data", "target_w": 10, "target_h": 10})
        _test_store.put(sid, "image_path", image_path)
        _test_store.put(sid, "source_basename", "海报.final")
        _test_store.put(sid, "lut_path", lut_path)
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "free_color_set", set())

        payload = {
            "session_id": sid,
            "preserve_upload_filename_for_3mf": True,
            "params": {"lut_name": "test_lut"},
        }
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": out_path,
                "glb_path": None,
                "status_msg": "OK",
            }
        )

        try:
            response = client.post("/api/convert/generate", json=payload)
            assert response.status_code == 200
            download_url = response.json()["download_url"]
            download_file_id = download_url.rsplit("/", 1)[-1]
            entry = _test_registry.get_entry(download_file_id)
            assert entry is not None
            assert entry["filename"] == "海报.final.3mf"
            assert entry["path"] == out_path
            assert entry["lifecycle"] == "ephemeral"
            assert entry["session_id"] != sid

            close_response = client.post("/api/session/close", json={"session_id": sid})
            assert close_response.status_code == 200

            download_response = client.get(download_url)
            assert download_response.status_code == 200
            assert download_response.content == b"3mf payload"
            assert download_response.headers["content-disposition"] == (
                "attachment; filename*=utf-8''%E6%B5%B7%E6%8A%A5.final.3mf"
            )
        finally:
            for path in (image_path, lut_path, out_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_generated_download_keeps_worker_filename_by_default(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)
        _test_store.put(sid, "source_basename", "海报.final")
        worker_path = "/tmp/descriptive_Lumina_HiFi_4C_20260813_123456.3mf"
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": worker_path,
                "glb_path": None,
                "status_msg": "OK",
            }
        )

        with patch("os.path.exists", return_value=True):
            response = client.post(
                "/api/convert/generate",
                json={"session_id": sid, "params": {"lut_name": "test_lut"}},
            )

        assert response.status_code == 200, response.text
        file_id = response.json()["download_url"].rsplit("/", 1)[-1]
        entry = _test_registry.get_entry(file_id)
        assert entry is not None
        assert entry["filename"] == os.path.basename(worker_path)

    def test_preserve_upload_filename_requires_strict_boolean(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)
        _mock_pool.submit.reset_mock()

        response = client.post(
            "/api/convert/generate",
            json={
                "session_id": sid,
                "preserve_upload_filename_for_3mf": "true",
                "params": {"lut_name": "test_lut"},
            },
        )

        assert response.status_code == 422
        _mock_pool.submit.assert_not_called()

    def test_preserve_upload_filename_does_not_rename_generated_color_card(
        self,
    ) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)
        _test_store.put(sid, "source_basename", "poster")
        session_data = _test_store.get(sid)
        assert session_data is not None
        preview_cache = dict(session_data["preview_cache"])
        preview_cache["color_palette"] = [
            {"hex": "#ff0000"},
            {"hex": "#00ff00"},
        ]
        _test_store.put(sid, "preview_cache", preview_cache)
        worker_path = "/tmp/Lumina_ColorCard_20260813_123456.3mf"
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": worker_path,
                "glb_path": None,
                "status_msg": "OK",
            }
        )

        with (
            patch("os.path.exists", return_value=True),
            patch(
                "core.color_card.generate_color_card_svg",
                return_value="/tmp/generated-color-card.svg",
            ),
        ):
            response = client.post(
                "/api/convert/generate",
                json={
                    "session_id": sid,
                    "preserve_upload_filename_for_3mf": True,
                    "params": {
                        "lut_name": "test_lut",
                        "modeling_mode": "color-card",
                    },
                },
            )

        assert response.status_code == 200, response.text
        file_id = response.json()["download_url"].rsplit("/", 1)[-1]
        entry = _test_registry.get_entry(file_id)
        assert entry is not None
        assert entry["filename"] == os.path.basename(worker_path)

    def test_generate_defaults_enable_base_layer_modifier_true_when_field_missing(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)

        payload = {
            "session_id": sid,
            "params": {
                "lut_name": "test_lut",
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
        assert submitted_params["enable_base_layer_height_modifier"] is True
        assert submitted_params["enable_wipe_tower_auto_placement"] is True


class TestNativeVectorPreviewGlbReuse:
    """Native planar SVG generation reuses only the current session preview."""

    @staticmethod
    def _seed_ready_vector_preview(
        tmp_path,
        *,
        preview_owner: str | None = None,
        preview_ttl_seconds: int | None = None,
    ) -> tuple[str, str, str, str, str]:
        _test_store.clear_all()
        _test_registry.clear_all()

        image_path = tmp_path / "input.svg"
        lut_path = tmp_path / "source.npy"
        out_path = tmp_path / "out.3mf"
        preview_glb_path = tmp_path / "segmented-preview.glb"
        image_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4">'
            '<rect width="4" height="4" fill="#ff0000"/></svg>',
            encoding="utf-8",
        )
        lut_path.write_bytes(b"lut")
        out_path.write_bytes(b"3mf")
        preview_glb_path.write_bytes(b"segmented-glb")

        sid = _test_store.create()
        owner = preview_owner or sid
        preview_glb_id = _test_registry.register_path(
            owner,
            str(preview_glb_path),
            ttl_seconds=preview_ttl_seconds,
        )
        cache_ref = externalize_preview_cache(
            sid,
            _test_store,
            {
                "target_w": 4,
                "target_h": 4,
                "target_width_mm": 40.0,
                "color_mode": "4-Color (RYBW)",
                "modeling_mode": "vector",
                "color_layers": 5,
                "layer_height_mm": 0.08,
                "quantize_colors": 48,
                "enable_cleanup": True,
                "hue_weight": 0.0,
                "chroma_gate": 15.0,
                "use_lut_constrained": False,
                "auto_dynamic_range": False,
                "model_enable": False,
                "model_only": False,
                "model_threshold": None,
                "model_margin": None,
                "svg_pixels_per_mm": 10.0,
                "material_source": "lut",
                "high_precision_3d_preview": False,
                "glb_url": f"/api/files/{preview_glb_id}",
                "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
                "mask_solid": np.ones((4, 4), dtype=bool),
                "material_matrix": np.zeros((4, 4, 5), dtype=np.uint8),
            },
            root_dir=tmp_path,
        )
        _test_store.put(sid, "preview_cache", cache_ref)
        _test_store.put(sid, "image_path", str(image_path))
        _test_store.put(sid, "source_basename", "input")
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(sid, "color_mode", "4-Color (RYBW)")
        _test_store.put(sid, "modeling_mode", "vector")
        _test_store.put(sid, "color_layers", 5)
        _test_store.put(sid, "layer_height_mm", 0.08)
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "free_color_set", set())
        _test_store.put(sid, "material_source", "lut")
        return (
            sid,
            str(out_path),
            str(preview_glb_path),
            preview_glb_id,
            str(image_path),
        )

    @staticmethod
    def _payload(sid: str, **overrides: object) -> dict[str, object]:
        return {
            "session_id": sid,
            "params": {
                "lut_name": "test_lut",
                "target_width_mm": 40.0,
                "color_mode": "4-Color (RYBW)",
                "modeling_mode": "vector",
                "color_layers": 5,
                "layer_height_mm": 0.08,
                "quantize_colors": 48,
                "enable_cleanup": True,
                "svg_pixels_per_mm": 10.0,
                "high_precision_3d_preview": False,
                **overrides,
            },
        }

    def test_native_vector_generate_reuses_ready_preview_glb_without_reregistering(
        self,
        tmp_path,
    ) -> None:
        sid, out_path, preview_path, preview_id, _image_path = (
            self._seed_ready_vector_preview(tmp_path)
        )
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": out_path,
                "glb_path": preview_path,
                "status_msg": "OK",
            }
        )

        response = client.post(
            "/api/convert/generate",
            json=self._payload(sid),
        )

        assert response.status_code == 200, response.text
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["reuse_preview_analysis"] is False
        assert submitted_params["preview_glb_path"] == preview_path
        assert response.json()["preview_3d_url"] == f"/api/files/{preview_id}"
        assert set(_test_registry.get_session_entries(sid)) == {preview_id}
        assert os.path.exists(preview_path)

        download_url = response.json()["download_url"]
        close_response = client.post(
            "/api/session/close",
            json={"session_id": sid},
        )

        assert close_response.status_code == 200
        assert client.get(f"/api/files/{preview_id}").status_code == 404
        download_response = client.get(download_url)
        assert download_response.status_code == 200
        assert download_response.content == b"3mf"

    def test_native_vector_generate_does_not_return_preview_superseded_in_flight(
        self,
        tmp_path,
    ) -> None:
        sid, out_path, preview_path, _preview_id, _image_path = (
            self._seed_ready_vector_preview(tmp_path)
        )

        async def finish_after_preview_is_invalidated(*_args, **_kwargs):
            session_data = _test_store.get(sid)
            assert session_data is not None
            cache_ref = dict(session_data["preview_cache"])
            metadata = dict(cache_ref["metadata"])
            metadata["glb_url"] = None
            metadata["glb_job_token"] = "replacement-job"
            cache_ref["metadata"] = metadata
            _test_store.put(sid, "preview_cache", cache_ref)
            return {
                "threemf_path": out_path,
                "glb_path": preview_path,
                "status_msg": "OK",
            }

        _mock_pool.submit = AsyncMock(side_effect=finish_after_preview_is_invalidated)

        response = client.post(
            "/api/convert/generate",
            json=self._payload(sid),
        )

        assert response.status_code == 200, response.text
        assert response.json()["preview_3d_url"] is None
        assert os.path.exists(preview_path)

    def test_native_vector_missing_3mf_preserves_reused_preview_glb(
        self,
        tmp_path,
    ) -> None:
        sid, _out_path, preview_path, preview_id, _image_path = (
            self._seed_ready_vector_preview(tmp_path)
        )
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": None,
                "glb_path": preview_path,
                "status_msg": "worker returned no 3MF",
            }
        )

        response = client.post(
            "/api/convert/generate",
            json=self._payload(sid),
        )

        assert response.status_code == 500
        assert response.json()["detail"] == MODEL_GENERATION_FAILED_DETAIL
        assert os.path.exists(preview_path)
        assert set(_test_registry.get_session_entries(sid)) == {preview_id}

    @pytest.mark.parametrize(
        "request_overrides",
        [
            {
                "enable_relief": True,
                "height_mode": "color",
                "color_height_map": {"#ff0000": 2.0},
                "structure_mode": "Single-sided",
            },
            {"enable_coating": True, "coating_height_mm": 0.08},
            {"add_loop": True},
            {
                "enable_fridge_magnet": True,
                "fridge_magnets": [
                    {
                        "id": "magnet-round",
                        "shape": "round",
                        "preset_key": "round-18",
                        "diameter_mm": 18.0,
                        "width_mm": None,
                        "height_mm": None,
                        "thickness_mm": 2.0,
                        "center_x_mm": 20.0,
                        "center_y_mm": 25.0,
                    }
                ],
            },
            {"enable_outline": True, "outline_width": 2.0},
            {"enable_cloisonne": True},
        ],
        ids=[
            "relief",
            "coating",
            "keychain-loop",
            "fridge-magnet",
            "outline",
            "cloisonne",
        ],
    )
    def test_native_vector_generate_reuses_preview_glb_for_live_settings(
        self,
        tmp_path,
        request_overrides: dict[str, object],
    ) -> None:
        sid, out_path, preview_path, preview_id, _image_path = (
            self._seed_ready_vector_preview(tmp_path)
        )
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": out_path,
                "glb_path": preview_path,
                "status_msg": "OK",
            }
        )

        response = client.post(
            "/api/convert/generate",
            json=self._payload(sid, **request_overrides),
        )

        assert response.status_code == 200, response.text
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["preview_glb_path"] == preview_path
        assert response.json()["preview_3d_url"] == f"/api/files/{preview_id}"
        assert set(_test_registry.get_session_entries(sid)) == {preview_id}

    def test_native_vector_generate_rejects_parameter_mismatch_for_preview_glb(
        self,
        tmp_path,
    ) -> None:
        sid, out_path, _preview_path, _preview_id, _image_path = (
            self._seed_ready_vector_preview(tmp_path)
        )
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": out_path,
                "glb_path": None,
                "status_msg": "OK",
            }
        )

        response = client.post(
            "/api/convert/generate",
            json=self._payload(sid, target_width_mm=41.0),
        )

        assert response.status_code == 200, response.text
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["preview_glb_path"] is None
        assert response.json()["preview_3d_url"] is None

    @pytest.mark.parametrize(
        "request_overrides",
        [
            {
                "replacement_regions": [
                    {
                        "quantized_hex": "#ff0000",
                        "matched_hex": "#ff0000",
                        "replacement_hex": "#00ff00",
                    }
                ]
            },
            {
                "recipe_overrides": [
                    {
                        "region_id": "region-1",
                        "recipe": [0, 0, 0, 0, 0],
                        "layer_order": "Top2Bottom",
                    }
                ]
            },
            {"free_color_set": ["#00ff00"]},
        ],
        ids=["replacement-regions", "recipe-overrides", "free-color-set"],
    )
    def test_native_vector_generate_rejects_preview_glb_for_new_edit_state(
        self,
        tmp_path,
        request_overrides: dict[str, object],
    ) -> None:
        sid, out_path, _preview_path, _preview_id, _image_path = (
            self._seed_ready_vector_preview(tmp_path)
        )
        if "recipe_overrides" in request_overrides:
            _test_store.put(
                sid,
                "selected_region_masks",
                {"region-1": np.ones((4, 4), dtype=bool)},
            )
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": out_path,
                "glb_path": None,
                "status_msg": "OK",
            }
        )

        response = client.post(
            "/api/convert/generate",
            json=self._payload(sid, **request_overrides),
        )

        assert response.status_code == 200, response.text
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["preview_glb_path"] is None
        assert response.json()["preview_3d_url"] is None

    def test_native_vector_generate_reuses_preview_glb_for_matching_edit_state(
        self,
        tmp_path,
    ) -> None:
        sid, out_path, preview_path, preview_id, _image_path = (
            self._seed_ready_vector_preview(tmp_path)
        )
        replacement_regions = [
            {
                "quantized_hex": "#ff0000",
                "matched_hex": "#ff0000",
                "replacement_hex": "#00ff00",
            }
        ]
        recipe_overrides = [
            {
                "region_id": "region-1",
                "recipe": [0, 0, 0, 0, 0],
                "layer_order": "Top2Bottom",
            }
        ]
        _test_store.put(sid, "replacement_regions", replacement_regions)
        _test_store.put(sid, "recipe_overrides", recipe_overrides)
        _test_store.put(sid, "free_color_set", {"00ff00"})
        _test_store.put(
            sid,
            "selected_region_masks",
            {"region-1": np.ones((4, 4), dtype=bool)},
        )
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": out_path,
                "glb_path": preview_path,
                "status_msg": "OK",
            }
        )

        response = client.post(
            "/api/convert/generate",
            json=self._payload(
                sid,
                replacement_regions=replacement_regions,
                recipe_overrides=recipe_overrides,
                free_color_set=["#00FF00"],
            ),
        )

        assert response.status_code == 200, response.text
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["preview_glb_path"] == preview_path
        assert response.json()["preview_3d_url"] == f"/api/files/{preview_id}"

    def test_native_vector_generate_reuses_preview_glb_for_equivalent_legacy_replacement_record(
        self,
        tmp_path,
    ) -> None:
        sid, out_path, preview_path, preview_id, _image_path = (
            self._seed_ready_vector_preview(tmp_path)
        )
        _test_store.put(
            sid,
            "replacement_regions",
            [
                {
                    "selected_color": "#aabbcc",
                    "replacement_color": "#00ff00",
                }
            ],
        )
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": out_path,
                "glb_path": preview_path,
                "status_msg": "OK",
            }
        )

        response = client.post(
            "/api/convert/generate",
            json=self._payload(
                sid,
                replacement_regions=[
                    {
                        "quantized_hex": "#112233",
                        "matched_hex": "#AABBCC",
                        "replacement_hex": "#00FF00",
                    }
                ],
            ),
        )

        assert response.status_code == 200, response.text
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["preview_glb_path"] == preview_path
        assert response.json()["preview_3d_url"] == f"/api/files/{preview_id}"

    def test_native_vector_generate_rejects_expired_preview_glb(
        self,
        tmp_path,
    ) -> None:
        sid, out_path, preview_path, _preview_id, _image_path = (
            self._seed_ready_vector_preview(
                tmp_path,
                preview_ttl_seconds=0,
            )
        )
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": out_path,
                "glb_path": None,
                "status_msg": "OK",
            }
        )

        response = client.post(
            "/api/convert/generate",
            json=self._payload(sid),
        )

        assert response.status_code == 200, response.text
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["preview_glb_path"] is None
        assert response.json()["preview_3d_url"] is None
        assert not os.path.exists(preview_path)

    def test_native_vector_generate_rejects_foreign_session_preview_glb(
        self,
        tmp_path,
    ) -> None:
        foreign_sid = _test_store.create()
        sid, out_path, _preview_path, _preview_id, _image_path = (
            self._seed_ready_vector_preview(
                tmp_path,
                preview_owner=foreign_sid,
            )
        )
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": out_path,
                "glb_path": None,
                "status_msg": "OK",
            }
        )

        response = client.post(
            "/api/convert/generate",
            json=self._payload(sid),
        )

        assert response.status_code == 200, response.text
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["preview_glb_path"] is None
        assert response.json()["preview_3d_url"] is None

    def test_native_vector_generate_rejects_model_surface_preview_glb(
        self,
        tmp_path,
    ) -> None:
        sid, out_path, _preview_path, _preview_id, _image_path = (
            self._seed_ready_vector_preview(tmp_path)
        )
        surface_path = tmp_path / "surface.stl"
        surface_path.write_bytes(b"surface")
        _test_store.put(sid, "surface_overlay_enabled", True)
        _test_store.put(sid, "surface_model_path", str(surface_path))
        _test_store.put(sid, "surface_footprint", {"width_mm": 40.0})
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": out_path,
                "glb_path": None,
                "status_msg": "OK",
            }
        )

        response = client.post(
            "/api/convert/generate",
            json=self._payload(sid),
        )

        assert response.status_code == 200, response.text
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["converter_params"]["preview_glb_path"] is None
        assert response.json()["preview_3d_url"] is None

    def test_vector_mode_raster_source_does_not_enter_native_svg_reuse(
        self,
        tmp_path,
    ) -> None:
        sid, out_path, _preview_path, _preview_id, image_path = (
            self._seed_ready_vector_preview(tmp_path)
        )
        raster_path = Path(image_path).with_suffix(".png")
        raster_path.write_bytes(b"raster-source")
        _test_store.put(sid, "image_path", str(raster_path))
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": out_path,
                "glb_path": None,
                "status_msg": "OK",
            }
        )

        response = client.post(
            "/api/convert/generate",
            json=self._payload(sid),
        )

        assert response.status_code == 200, response.text
        submitted_params = _mock_pool.submit.call_args.args[3]
        assert submitted_params["preview_glb_path"] is None
        assert response.json()["preview_3d_url"] is None


# =========================================================================
# 5. Timeout → HTTP 504 - Requirement 2.3
# =========================================================================


class TestGenerateTimeout:
    """Verify asyncio.TimeoutError from pool.submit returns HTTP 504."""



# =========================================================================
# 6. Worker exception → HTTP 500 - Requirement 1.4
# =========================================================================


def test_s06_failure_reaches_api_without_export_or_replacing_previous_download(
    tmp_path: Path,
) -> None:
    """Run the real worker/coordinator/S06 failure path with prepared image inputs."""
    from core.pipeline import coordinator, s06_voxel_building

    sid = _create_session_with_preview_and_files(_test_store)
    image_path = tmp_path / "source.png"
    Image.new("RGB", (2, 2), "white").save(image_path)
    lut_path = tmp_path / "lut.npy"
    np.save(lut_path, np.zeros((1, 3), dtype=np.uint8))
    _test_store.put(sid, "image_path", str(image_path))
    _test_store.put(sid, "lut_path", str(lut_path))
    previous = tmp_path / "previous.3mf"
    previous.write_bytes(b"previous successful model")
    previous_id = _test_registry.register_path(
        "previous-download", str(previous), ttl_seconds=600,
    )
    original_cache = _test_store.get(sid)["preview_cache"]

    def prepare_voxel_inputs(ctx: dict) -> dict:
        ctx.update(
            material_matrix=np.zeros((2, 2, 5), dtype=int),
            mask_solid=np.ones((2, 2), dtype=bool),
            matched_rgb=np.full((2, 2, 3), 255, dtype=np.uint8),
            pixel_scale=0.1,
        )
        return ctx

    async def run_worker_inline(worker, *args):
        return worker(*args)

    _mock_pool.submit = AsyncMock(side_effect=run_worker_inline)
    later_steps = []
    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(coordinator.s01_input_validation, "run", side_effect=lambda ctx: ctx))
            for module, label, *_ in coordinator._RASTER_STEPS:
                if label < "S06":
                    stack.enter_context(patch.object(module, "run", side_effect=prepare_voxel_inputs))
                elif label > "S06":
                    later_steps.append(stack.enter_context(patch.object(module, "run")))
            relief = stack.enter_context(patch.object(
                s06_voxel_building, "_build_relief_voxel_matrix",
                side_effect=RuntimeError("internal relief failure details"),
            ))
            flat = stack.enter_context(patch.object(
                s06_voxel_building, "_build_voxel_matrix",
                wraps=s06_voxel_building._build_voxel_matrix,
            ))
            register = stack.enter_context(patch.object(_test_registry, "register_path", wraps=_test_registry.register_path))
            response = client.post("/api/convert/generate", json={
                "session_id": sid,
                "params": {
                    "lut_name": "test_lut", "modeling_mode": "high-fidelity",
                    "enable_relief": True, "color_height_map": {"#ffffff": 2.4},
                },
            })

        relief.assert_called_once()
        flat.assert_not_called()
        for step in later_steps:
            step.assert_not_called()
        register.assert_not_called()
        assert response.status_code == 500, response.text
        assert response.json()["detail"] == MODEL_GENERATION_FAILED_DETAIL
        assert "internal relief failure" not in response.text
        assert "download_url" not in response.json()
        assert _test_store.get(sid)["preview_cache"] is original_cache
        assert previous.read_bytes() == b"previous successful model"
        assert client.get(f"/api/files/{previous_id}").status_code == 200
    finally:
        _test_store.close(sid)
        _test_registry.cleanup_session("previous-download")


class TestGenerateWorkerException:
    """Verify general Exception from pool.submit returns a safe HTTP 500."""

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
        assert response.json()["detail"] == MODEL_GENERATION_FAILED_DETAIL
        assert "Worker crashed" not in response.text

    def test_generate_broken_worker_pool_returns_retryable_503(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)
        payload = {
            "session_id": sid,
            "params": {"lut_name": "test_lut"},
        }
        _mock_pool.submit = AsyncMock(
            side_effect=BrokenProcessPool("worker was killed")
        )

        with patch("os.path.exists", return_value=True):
            response = client.post("/api/convert/generate", json=payload)

        assert response.status_code == 503
        assert response.json()["detail"] == MODEL_GENERATION_FAILED_DETAIL
        assert "worker was killed" not in response.text



class TestGenerateRegistryFailureCleanup:
    """Final worker outputs should not leak when registry ownership fails."""

    def test_generate_missing_3mf_discards_unexpected_worker_glb(
        self,
        tmp_path,
    ) -> None:
        image_path = tmp_path / "source.png"
        lut_path = tmp_path / "source.npy"
        glb_path = tmp_path / "unexpected.glb"
        Image.fromarray(np.zeros((2, 2, 3), dtype=np.uint8)).save(image_path)
        lut_path.write_bytes(b"lut")
        glb_path.write_bytes(b"glb")

        sid = _test_store.create()
        _test_store.put(
            sid,
            "preview_cache",
            {"target_w": 2, "target_h": 2, "target_width_mm": 20.0},
        )
        _test_store.put(sid, "image_path", str(image_path))
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "free_color_set", set())
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": None,
                "glb_path": str(glb_path),
                "status_msg": "worker returned no 3MF",
            }
        )

        try:
            response = client.post(
                "/api/convert/generate",
                json={"session_id": sid, "params": {"lut_name": "test_lut"}},
            )

            assert response.status_code == 500
            assert response.json()["detail"] == MODEL_GENERATION_FAILED_DETAIL
            assert not glb_path.exists()
            assert _test_registry.get_session_entries(sid) == {}
        finally:
            glb_path.unlink(missing_ok=True)
            _test_store.close(sid)

    def test_generate_registry_failure_cleans_unregistered_worker_outputs(self) -> None:
        paths: list[str] = []

        def _make_file(suffix: str, payload: bytes) -> str:
            fd, path = tempfile.mkstemp(suffix=suffix)
            paths.append(path)
            os.write(fd, payload)
            os.close(fd)
            return path

        image_path = _make_file(".png", b"img")
        lut_path = _make_file(".npy", b"lut")
        threemf_path = _make_file(".3mf", b"3mf")
        glb_path = _make_file(".glb", b"glb")

        sid = _test_store.create()
        _test_store.put(
            sid,
            "preview_cache",
            {"target_w": 10, "target_h": 10, "target_width_mm": 10.0},
        )
        _test_store.put(sid, "image_path", image_path)
        _test_store.put(sid, "lut_path", lut_path)
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "free_color_set", set())
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": threemf_path,
                "glb_path": glb_path,
                "status_msg": "OK",
            }
        )

        original_registry_override = app.dependency_overrides[get_file_registry]
        app.dependency_overrides[get_file_registry] = lambda: _FailingRegistry()
        failing_client = TestClient(app, raise_server_exceptions=False)
        try:
            response = failing_client.post(
                "/api/convert/generate",
                json={"session_id": sid, "params": {"lut_name": "test_lut"}},
            )

            assert response.status_code == 500
            assert response.json()["detail"] == MODEL_GENERATION_FAILED_DETAIL
            assert "registry unavailable" not in response.text
            assert not os.path.exists(threemf_path)
            assert not os.path.exists(glb_path)
            assert os.path.exists(image_path)
            assert os.path.exists(lut_path)
        finally:
            app.dependency_overrides[get_file_registry] = original_registry_override
            for path in paths:
                if os.path.exists(path):
                    os.unlink(path)
            _test_store.close(sid)

    def test_color_card_registry_failure_cleans_unregistered_worker_outputs(
        self,
        tmp_path,
    ) -> None:
        lut_path = tmp_path / "source.npy"
        threemf_path = tmp_path / "card.3mf"
        glb_path = tmp_path / "card.glb"
        lut_path.write_bytes(b"lut")
        threemf_path.write_bytes(b"3mf")
        glb_path.write_bytes(b"glb")

        sid = _test_store.create()
        _test_store.put(
            sid,
            "preview_cache",
            {
                "target_w": 4,
                "target_h": 4,
                "target_width_mm": 40.0,
                "color_palette": [{"hex": "#ff0000"}, {"hex": "#00ff00"}],
            },
        )
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(sid, "material_source", "lut")

        def _fake_generate_color_card_svg(hex_colors, **_kwargs):
            svg_path = tmp_path / "card.svg"
            svg_path.write_text("<svg></svg>", encoding="utf-8")
            return str(svg_path)

        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": str(threemf_path),
                "glb_path": str(glb_path),
                "status_msg": "OK",
            }
        )
        original_registry_override = app.dependency_overrides[get_file_registry]
        app.dependency_overrides[get_file_registry] = lambda: _FailingRegistry()
        failing_client = TestClient(app, raise_server_exceptions=False)
        try:
            with patch(
                "core.color_card.generate_color_card_svg",
                _fake_generate_color_card_svg,
            ):
                response = failing_client.post(
                    "/api/convert/color-card",
                    json={"session_id": sid},
                )

            assert response.status_code == 500
            assert response.json()["detail"] == _COLOR_CARD_GENERATION_FAILED_DETAIL
            assert "registry unavailable" not in response.text
            assert not threemf_path.exists()
            assert not glb_path.exists()
            assert lut_path.exists()
        finally:
            app.dependency_overrides[get_file_registry] = original_registry_override
            for path in (threemf_path, glb_path, tmp_path / "card.svg"):
                if path.exists():
                    path.unlink()
            _test_store.close(sid)

    def test_generate_discards_print_glb_and_preserves_downloaded_3mf(self) -> None:
        paths: list[str] = []

        def _make_file(suffix: str, payload: bytes) -> str:
            fd, path = tempfile.mkstemp(suffix=suffix)
            paths.append(path)
            os.write(fd, payload)
            os.close(fd)
            return path

        image_path = _make_file(".png", b"img")
        lut_path = _make_file(".npy", b"lut")
        threemf_path = _make_file(".3mf", b"3mf")
        glb_path = _make_file(".glb", b"glb")
        registry = _SecondRegistrationFailingRegistry()

        sid = _test_store.create()
        _test_store.put(
            sid,
            "preview_cache",
            {"target_w": 10, "target_h": 10, "target_width_mm": 10.0},
        )
        _test_store.put(sid, "image_path", image_path)
        _test_store.put(sid, "lut_path", lut_path)
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "free_color_set", set())
        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": threemf_path,
                "glb_path": glb_path,
                "status_msg": "OK",
            }
        )

        original_registry_override = app.dependency_overrides[get_file_registry]
        app.dependency_overrides[get_file_registry] = lambda: registry
        failing_client = TestClient(app, raise_server_exceptions=False)
        try:
            response = failing_client.post(
                "/api/convert/generate",
                json={"session_id": sid, "params": {"lut_name": "test_lut"}},
            )

            assert response.status_code == 200
            payload = response.json()
            assert payload["download_url"].startswith("/api/files/")
            assert payload["preview_3d_url"] is None
            download_file_id = payload["download_url"].rsplit("/", 1)[-1]
            assert os.path.exists(threemf_path)
            assert not os.path.exists(glb_path)
            assert os.path.exists(image_path)
            assert os.path.exists(lut_path)
            assert registry.register_calls == 1
            assert registry.first_file_id == download_file_id
            entry = registry.get_entry(registry.first_file_id)
            assert entry is not None
            assert entry["path"] == threemf_path
            assert entry["lifecycle"] == "ephemeral"
            assert entry["session_id"] != sid

            close_response = failing_client.post(
                "/api/session/close",
                json={"session_id": sid},
            )
            assert close_response.status_code == 200
            download_response = failing_client.get(payload["download_url"])
            assert download_response.status_code == 200
            assert download_response.content == b"3mf"
        finally:
            app.dependency_overrides[get_file_registry] = original_registry_override
            registry.cleanup_expired()
            for path in paths:
                if os.path.exists(path):
                    os.unlink(path)
            _test_store.close(sid)

    def test_generate_drops_new_glb_when_session_closes_during_worker(
        self,
        tmp_path,
    ) -> None:
        image_path = tmp_path / "source.png"
        lut_path = tmp_path / "source.npy"
        threemf_path = tmp_path / "result.3mf"
        glb_path = tmp_path / "result.glb"
        Image.fromarray(np.zeros((2, 2, 3), dtype=np.uint8)).save(image_path)
        lut_path.write_bytes(b"lut")
        threemf_path.write_bytes(b"3mf")
        glb_path.write_bytes(b"glb")

        sid = _test_store.create()
        _test_store.put(
            sid,
            "preview_cache",
            {"target_w": 2, "target_h": 2, "target_width_mm": 20.0},
        )
        _test_store.put(sid, "image_path", str(image_path))
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "free_color_set", set())

        async def close_session_then_return(*_args, **_kwargs):
            _test_store.close(sid)
            _test_registry.cleanup_session(sid)
            return {
                "threemf_path": str(threemf_path),
                "glb_path": str(glb_path),
                "status_msg": "OK",
            }

        _mock_pool.submit = AsyncMock(side_effect=close_session_then_return)

        download_file_id: str | None = None
        try:
            response = client.post(
                "/api/convert/generate",
                json={"session_id": sid, "params": {"lut_name": "test_lut"}},
            )

            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["preview_3d_url"] is None
            assert not glb_path.exists()
            assert _test_registry.get_session_entries(sid) == {}
            assert _test_store.get(sid) is None

            download_file_id = payload["download_url"].rsplit("/", 1)[-1]
            download_entry = _test_registry.get_entry(download_file_id)
            assert download_entry is not None
            assert download_entry["lifecycle"] == "ephemeral"
            assert download_entry["session_id"] != sid
            download_response = client.get(payload["download_url"])
            assert download_response.status_code == 200
            assert download_response.content == b"3mf"
        finally:
            if download_file_id is not None:
                _test_registry.cleanup_file(download_file_id)
            for path in (image_path, lut_path, threemf_path, glb_path):
                path.unlink(missing_ok=True)

    def test_color_card_glb_registry_failure_preserves_downloaded_3mf(
        self,
        tmp_path,
    ) -> None:
        lut_path = tmp_path / "source.npy"
        threemf_path = tmp_path / "card.3mf"
        glb_path = tmp_path / "card.glb"
        svg_path = tmp_path / "card.svg"
        lut_path.write_bytes(b"lut")
        threemf_path.write_bytes(b"3mf")
        glb_path.write_bytes(b"glb")
        registry = _SecondRegistrationFailingRegistry()

        sid = _test_store.create()
        _test_store.put(
            sid,
            "preview_cache",
            {
                "target_w": 4,
                "target_h": 4,
                "target_width_mm": 40.0,
                "color_palette": [{"hex": "#ff0000"}, {"hex": "#00ff00"}],
            },
        )
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(sid, "material_source", "lut")

        def _fake_generate_color_card_svg(hex_colors, **_kwargs):
            svg_path.write_text("<svg></svg>", encoding="utf-8")
            return str(svg_path)

        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": str(threemf_path),
                "glb_path": str(glb_path),
                "status_msg": "OK",
            }
        )
        original_registry_override = app.dependency_overrides[get_file_registry]
        app.dependency_overrides[get_file_registry] = lambda: registry
        failing_client = TestClient(app, raise_server_exceptions=False)
        try:
            with patch(
                "core.color_card.generate_color_card_svg",
                _fake_generate_color_card_svg,
            ):
                response = failing_client.post(
                    "/api/convert/color-card",
                    json={"session_id": sid},
                )

            assert response.status_code == 200
            payload = response.json()
            assert payload["download_url"].startswith("/api/files/")
            assert payload["preview_3d_url"] is None
            download_file_id = payload["download_url"].rsplit("/", 1)[-1]
            assert threemf_path.exists()
            assert not glb_path.exists()
            assert lut_path.exists()
            assert svg_path.exists()
            assert registry.register_calls == 2
            assert registry.first_file_id == download_file_id
            entry = registry.get_entry(registry.first_file_id)
            assert entry is not None
            assert entry["path"] == str(threemf_path)
            assert entry["lifecycle"] == "ephemeral"
            assert entry["session_id"] != sid

            close_response = failing_client.post(
                "/api/session/close",
                json={"session_id": sid},
            )
            assert close_response.status_code == 200
            download_response = failing_client.get(payload["download_url"])
            assert download_response.status_code == 200
            assert download_response.content == b"3mf"
        finally:
            app.dependency_overrides[get_file_registry] = original_registry_override
            registry.cleanup_expired()
            for path in (threemf_path, glb_path, svg_path):
                if path.exists():
                    path.unlink()
            _test_store.close(sid)

    @pytest.mark.asyncio
    async def test_large_format_svg_registry_failure_cleans_unregistered_zip(
        self,
        tmp_path,
    ) -> None:
        image_path = tmp_path / "source.svg"
        lut_path = tmp_path / "source.npy"
        zip_path = tmp_path / "tiles.zip"
        image_path.write_text("<svg/>", encoding="utf-8")
        lut_path.write_bytes(b"lut")
        zip_path.write_bytes(b"zip")

        mock_pool = SimpleNamespace(
            submit=AsyncMock(
                return_value={
                    "zip_path": str(zip_path),
                    "tile_count": 1,
                    "grid_cols": 1,
                    "grid_rows": 1,
                    "warnings": [],
                }
            )
        )
        request = LargeFormatConvertGenerateRequest(
            total_width_mm=20.0,
            total_height_mm=20.0,
            tile_width_mm=20.0,
            tile_height_mm=20.0,
            lut_name="test_lut",
        )

        with pytest.raises(HTTPException) as exc_info:
            await _generate_large_format_svg_native(
                image_path=str(image_path),
                lut_path=str(lut_path),
                source_basename="source",
                recipe_overrides=None,
                recipe_override_masks_path=None,
                material_matrix_path=None,
                total_width_mm=20.0,
                total_height_mm=20.0,
                tile_width_mm=20.0,
                tile_height_mm=20.0,
                request=request,
                session_data={},
                sid="session-1",
                store=_test_store,
                registry=_FailingRegistry(),
                pool=mock_pool,
                warnings=[],
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == LARGE_FORMAT_GENERATION_FAILED_DETAIL
        assert "registry unavailable" not in str(exc_info.value.detail)
        assert not zip_path.exists()


    @pytest.mark.asyncio
    async def test_large_format_svg_native_forwards_color_relief_params(
        self,
        tmp_path,
    ) -> None:
        image_path = tmp_path / "source.svg"
        lut_path = tmp_path / "source.npy"
        zip_path = tmp_path / "tiles.zip"
        image_path.write_text("<svg/>", encoding="utf-8")
        lut_path.write_bytes(b"lut")
        zip_path.write_bytes(b"zip")
        captured_params = {}

        async def _submit(
            _fn,
            _image_path,
            _lut_path,
            params,
        ):
            captured_params.update(params)
            return {
                "zip_path": str(zip_path),
                "tile_count": 1,
                "grid_cols": 1,
                "grid_rows": 1,
                "warnings": [],
            }

        request = LargeFormatConvertGenerateRequest(
            total_width_mm=20.0,
            total_height_mm=20.0,
            tile_width_mm=20.0,
            tile_height_mm=20.0,
            lut_name="test_lut",
            enable_relief=True,
            height_mode="color",
            color_height_map={"#ff0000": 2.4},
            heightmap_max_height=3.2,
        )
        registry = FileRegistry()

        result = await _generate_large_format_svg_native(
            image_path=str(image_path),
            lut_path=str(lut_path),
            source_basename="source",
            recipe_overrides=None,
            recipe_override_masks_path=None,
            material_matrix_path=None,
            total_width_mm=20.0,
            total_height_mm=20.0,
            tile_width_mm=20.0,
            tile_height_mm=20.0,
            request=request,
            session_data={},
            sid="session-color",
            store=_test_store,
            registry=registry,
            pool=SimpleNamespace(submit=AsyncMock(side_effect=_submit)),
            warnings=[],
        )

        assert result["status"] == "ok"
        assert captured_params["enable_relief"] is True
        assert captured_params["height_mode"] == "color"
        assert captured_params["color_height_map"] == {"#ff0000": 2.4}
        assert captured_params["heightmap_max_height"] == pytest.approx(3.2)

    @pytest.mark.asyncio
    async def test_large_format_svg_native_materializes_heightmap_for_worker(
        self,
        tmp_path,
    ) -> None:
        image_path = tmp_path / "source.svg"
        lut_path = tmp_path / "source.npy"
        zip_path = tmp_path / "tiles.zip"
        image_path.write_text("<svg/>", encoding="utf-8")
        lut_path.write_bytes(b"lut")
        zip_path.write_bytes(b"zip")
        heightmap = np.arange(32, dtype=np.uint8).reshape(4, 8)
        captured_path = None

        async def _submit(
            _fn,
            _image_path,
            _lut_path,
            params,
        ):
            nonlocal captured_path
            captured_path = params["heightmap_path"]
            assert os.path.exists(captured_path)
            with Image.open(captured_path) as loaded:
                assert np.array_equal(np.asarray(loaded), heightmap)
            return {
                "zip_path": str(zip_path),
                "tile_count": 1,
                "grid_cols": 1,
                "grid_rows": 1,
                "warnings": [],
            }

        request = LargeFormatConvertGenerateRequest(
            total_width_mm=20.0,
            total_height_mm=20.0,
            tile_width_mm=20.0,
            tile_height_mm=20.0,
            lut_name="test_lut",
            enable_relief=True,
            height_mode="heightmap",
            heightmap_max_height=3.2,
        )
        registry = FileRegistry()

        result = await _generate_large_format_svg_native(
            image_path=str(image_path),
            lut_path=str(lut_path),
            source_basename="source",
            recipe_overrides=None,
            recipe_override_masks_path=None,
            material_matrix_path=None,
            total_width_mm=20.0,
            total_height_mm=20.0,
            tile_width_mm=20.0,
            tile_height_mm=20.0,
            request=request,
            session_data={"heightmap_grayscale": heightmap},
            sid="session-heightmap",
            store=_test_store,
            registry=registry,
            pool=SimpleNamespace(submit=AsyncMock(side_effect=_submit)),
            warnings=[],
        )

        assert result["status"] == "ok"
        assert captured_path is not None
        assert not os.path.exists(captured_path)

    @pytest.mark.asyncio
    async def test_large_format_raster_registry_failure_cleans_unregistered_zip(
        self,
        tmp_path,
    ) -> None:
        image_path = tmp_path / "source.png"
        lut_path = tmp_path / "source.npy"
        Image.fromarray(np.zeros((20, 20, 3), dtype=np.uint8)).save(image_path)
        lut_path.write_bytes(b"lut")

        request = LargeFormatConvertGenerateRequest(
            total_width_mm=20.0,
            total_height_mm=20.0,
            tile_width_mm=20.0,
            tile_height_mm=20.0,
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )

        async def _write_tile(*_args, **_kwargs):
            tile_path = tmp_path / "tile.3mf"
            tile_path.write_bytes(b"3mf")
            return {"threemf_path": str(tile_path), "status_msg": "OK"}

        mock_pool = MagicMock(spec=WorkerPoolManager)
        mock_pool.submit = AsyncMock(side_effect=_write_tile)

        with pytest.raises(HTTPException) as exc_info:
            await _generate_large_format_raster(
                image_path=str(image_path),
                lut_path=str(lut_path),
                source_basename="source",
                recipe_overrides=None,
                recipe_override_masks_path=None,
                material_matrix_path=None,
                total_width_mm=20.0,
                total_height_mm=20.0,
                tile_width_mm=20.0,
                tile_height_mm=20.0,
                request=request,
                session_data={},
                sid="session-1",
                store=_test_store,
                registry=_FailingRegistry(),
                pool=mock_pool,
                warnings=[],
            )

        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == LARGE_FORMAT_GENERATION_FAILED_DETAIL
        assert "registry unavailable" not in str(exc_info.value.detail)
        assert not (tmp_path / "tile.3mf").exists()

    @pytest.mark.asyncio
    async def test_large_format_raster_broken_pool_stops_remaining_tiles(
        self,
        tmp_path,
    ) -> None:
        image_path = tmp_path / "source.png"
        lut_path = tmp_path / "source.npy"
        Image.fromarray(np.zeros((20, 40, 3), dtype=np.uint8)).save(image_path)
        lut_path.write_bytes(b"lut")
        request = LargeFormatConvertGenerateRequest(
            total_width_mm=40.0,
            total_height_mm=20.0,
            tile_width_mm=20.0,
            tile_height_mm=20.0,
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )
        mock_pool = MagicMock(spec=WorkerPoolManager)
        mock_pool.submit = AsyncMock(
            side_effect=BrokenProcessPool("worker was killed")
        )

        with pytest.raises(HTTPException) as exc_info:
            await _generate_large_format_raster(
                image_path=str(image_path),
                lut_path=str(lut_path),
                source_basename="source",
                recipe_overrides=None,
                recipe_override_masks_path=None,
                material_matrix_path=None,
                total_width_mm=40.0,
                total_height_mm=20.0,
                tile_width_mm=20.0,
                tile_height_mm=20.0,
                request=request,
                session_data={},
                sid="session-broken-pool",
                store=_test_store,
                registry=FileRegistry(),
                pool=mock_pool,
                warnings=[],
            )

        assert exc_info.value.status_code == 503
        assert exc_info.value.detail == LARGE_FORMAT_GENERATION_FAILED_DETAIL
        assert mock_pool.submit.call_count == 2
        assert mock_pool.submit.await_count == 1


class TestLargeFormatFridgeMagnetValidation:
    """Verify unsupported fridge-magnet combinations fail deterministically."""

    def test_large_format_rejects_fridge_magnet_mode(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 80.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "enable_fridge_magnet": True,
                    "fridge_magnets": [
                        {
                            "id": "magnet-round",
                            "shape": "round",
                            "preset_key": "round-18",
                            "diameter_mm": 18.0,
                            "width_mm": None,
                            "height_mm": None,
                            "thickness_mm": 2.0,
                            "center_x_mm": 0.0,
                            "center_y_mm": 0.0,
                        }
                    ],
                },
            },
        }

        response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 422
        assert "fridge magnet" in response.json()["detail"].lower()


class TestStandardCachedAnalysisRouting:
    """Explicit standard-generation cache reuse must fail closed."""

    _INVALID_DETAIL = (
        "Cached preview data is unavailable or invalid. "
        "Re-run preview and try again."
    )

    @staticmethod
    def _semantic_cache_metadata(
        request: ConvertGenerateRequest,
        *,
        material_source: str,
    ) -> dict[str, object]:
        """Return analysis metadata matching one standard generate request."""

        return {
            "target_width_mm": request.target_width_mm,
            "color_mode": request.color_mode.value,
            "modeling_mode": request.modeling_mode.value,
            "color_layers": request.color_layers,
            "layer_height_mm": request.layer_height_mm,
            "quantize_colors": request.quantize_colors,
            "enable_cleanup": request.enable_cleanup,
            "hue_weight": request.hue_weight,
            "chroma_gate": request.chroma_gate,
            "use_lut_constrained": request.use_lut_constrained,
            "auto_dynamic_range": request.auto_dynamic_range,
            "model_enable": request.model_enable,
            "model_only": request.model_only,
            "model_threshold": request.model_threshold,
            "model_margin": request.model_margin,
            "svg_pixels_per_mm": request.svg_pixels_per_mm,
            "material_source": material_source,
        }

    def _create_session(
        self,
        tmp_path,
        *,
        modeling_mode: ModelingMode,
        material_source: str = "lut",
        color_layers: int | None = 5,
        layer_height_mm: float | None = 0.08,
        matched_rgb: object | None = None,
        mask_solid: object | None = None,
        material_matrix: object | None = None,
        quantized_image: object | None = None,
        cache_overrides: dict[str, object] | None = None,
    ) -> tuple[str, dict[str, object]]:
        """Create one route-isolated standard cached-generation session."""

        image_path = tmp_path / (
            "source.svg" if modeling_mode == ModelingMode.VECTOR else "source.png"
        )
        if modeling_mode == ModelingMode.VECTOR:
            image_path.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">'
                '<rect width="40" height="40" fill="#fff"/></svg>',
                encoding="utf-8",
            )
        else:
            Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)

        lut_path = tmp_path / "source.npy"
        lut_path.write_bytes(b"lut")
        out_path = tmp_path / "out.3mf"
        out_path.write_bytes(b"3mf")

        request = ConvertGenerateRequest(
            lut_name=(
                "__material_archive__"
                if material_source == "material_archive"
                else "test_lut"
            ),
            modeling_mode=modeling_mode,
            target_width_mm=40.0,
            color_layers=color_layers,
            layer_height_mm=layer_height_mm,
            use_cached_matched_rgb=True,
        )
        cache = {
            "target_w": 4,
            "target_h": 4,
            **self._semantic_cache_metadata(
                request,
                material_source=material_source,
            ),
            "matched_rgb": (
                np.zeros((4, 4, 3), dtype=np.uint8)
                if matched_rgb is None
                else matched_rgb
            ),
            "mask_solid": (
                np.ones((4, 4), dtype=bool)
                if mask_solid is None
                else mask_solid
            ),
            "material_matrix": (
                np.zeros((4, 4, 5), dtype=np.int16)
                if material_matrix is None
                else material_matrix
            ),
            "quantized_image": (
                np.zeros((4, 4, 3), dtype=np.uint8)
                if quantized_image is None
                else quantized_image
            ),
            **(cache_overrides or {}),
        }

        sid = _test_store.create()
        _test_store.put(sid, "preview_cache", cache)
        _test_store.put(sid, "image_path", str(image_path))
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(sid, "material_source", material_source)
        _test_store.put(sid, "color_layers", color_layers)
        _test_store.put(sid, "layer_height_mm", layer_height_mm)
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "free_color_set", set())
        if material_source == "material_archive":
            _test_store.put(sid, "selected_materials", [])

        _mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": str(out_path),
                "glb_path": None,
                "status_msg": "OK",
            }
        )
        return sid, {
            "session_id": sid,
            "params": request.model_dump(mode="json"),
        }

    def test_generate_explicit_cache_accepts_matching_omitted_layer_defaults(
        self,
        tmp_path,
    ) -> None:
        """Fresh preview/generate requests may both omit optional layer values."""

        from core.preview_analysis_cache import REQUIRED_PREVIEW_ANALYSIS_REUSE

        sid, payload = self._create_session(
            tmp_path,
            modeling_mode=ModelingMode.VECTOR,
            color_layers=None,
            layer_height_mm=None,
        )
        try:
            response = client.post("/api/convert/generate", json=payload)

            assert response.status_code == 200, response.text
            submitted_params = _mock_pool.submit.call_args.args[3]
            assert (
                submitted_params["reuse_preview_analysis"]
                == REQUIRED_PREVIEW_ANALYSIS_REUSE
            )
        finally:
            _test_store.close(sid)

    def test_generate_explicit_cache_inherits_preview_layer_settings(
        self,
        tmp_path,
    ) -> None:
        """An omitted generate value inherits the explicit preview setting."""

        from core.preview_analysis_cache import REQUIRED_PREVIEW_ANALYSIS_REUSE

        sid, payload = self._create_session(
            tmp_path,
            modeling_mode=ModelingMode.VECTOR,
            color_layers=6,
            layer_height_mm=0.12,
        )
        payload["params"]["color_layers"] = None
        payload["params"]["layer_height_mm"] = None
        try:
            response = client.post("/api/convert/generate", json=payload)

            assert response.status_code == 200, response.text
            submitted_params = _mock_pool.submit.call_args.args[3]
            assert (
                submitted_params["reuse_preview_analysis"]
                == REQUIRED_PREVIEW_ANALYSIS_REUSE
            )
            assert submitted_params["color_layers"] == 6
            assert submitted_params["layer_height_mm"] == pytest.approx(0.12)
        finally:
            _test_store.close(sid)

    @pytest.mark.parametrize(
        ("dynamic_enabled", "matching_edits", "use_cached_rgb", "expect_replay"),
        [
            (True, False, True, False),
            (False, False, True, True),
            (False, True, True, False),
            (False, True, False, False),
        ],
        ids=("dynamic-final-cache", "new-fixed-edit", "fixed-final-cache", "fixed-forwarded-cache"),
    )
    def test_generate_replays_only_edits_not_already_confirmed_in_cache(
        self,
        tmp_path,
        dynamic_enabled: bool,
        matching_edits: bool,
        use_cached_rgb: bool,
        expect_replay: bool,
    ) -> None:
        """Final RGB/recipe pairs must not be changed by replaying saved edits."""

        from core.preview_analysis_cache import REQUIRED_PREVIEW_ANALYSIS_REUSE

        max_layer_count = 6
        sid, payload = self._create_session(
            tmp_path,
            modeling_mode=ModelingMode.HIGH_FIDELITY,
            material_source="material_archive",
            color_layers=max_layer_count,
            material_matrix=np.zeros(
                (4, 4, max_layer_count),
                dtype=np.int32,
            ),
        )
        dynamic_settings = {
            "material_dynamic_layer_count_enabled": dynamic_enabled,
            "material_min_layer_count": 5,
            "material_max_layer_count": max_layer_count,
            "material_delta_e00_tolerance": 0.5,
        }
        for key, value in dynamic_settings.items():
            _test_store.put(sid, key, value)
        _test_store.put(sid, "selected_materials", ["mat-a", "mat-b"])
        _test_store.put(
            sid,
            "replacement_regions",
            [
                {
                    "selected_color": "#445566" if matching_edits else "#112233",
                    "replacement_color": "#778899",
                }
            ],
        )
        payload["params"].update(dynamic_settings)
        requested_replacements = [
            {
                "quantized_hex": "#112233",
                "matched_hex": "#445566",
                "replacement_hex": "#778899",
            }
        ]
        payload["params"]["replacement_regions"] = requested_replacements
        payload["params"]["use_cached_matched_rgb"] = use_cached_rgb

        try:
            response = client.post("/api/convert/generate", json=payload)

            assert response.status_code == 200, response.text
            submitted_params = _mock_pool.submit.call_args.args[3]
            if use_cached_rgb:
                assert submitted_params["reuse_preview_analysis"] == REQUIRED_PREVIEW_ANALYSIS_REUSE
            assert submitted_params["replacement_regions"] == (
                requested_replacements if expect_replay else None
            )
            assert submitted_params["matched_rgb_path"] is not None
            assert submitted_params["mask_solid_path"] is not None
            assert submitted_params["material_matrix_path"] is not None
            assert (
                submitted_params["quantized_image_path"] is not None
            ) is dynamic_enabled
        finally:
            _test_store.close(sid)

    @pytest.mark.parametrize(
        "quantized_image",
        [
            None,
            np.zeros((4, 4, 3), dtype=np.int16),
            np.zeros((3, 4, 3), dtype=np.uint8),
        ],
        ids=("missing", "wrong-dtype", "wrong-grid"),
    )
    def test_generate_dynamic_cached_analysis_requires_quantized_image(
        self,
        tmp_path,
        quantized_image: np.ndarray | None,
    ) -> None:
        """Dynamic P03 reuse rejects an incomplete or invalid four-asset cache."""

        max_layer_count = 6
        sid, payload = self._create_session(
            tmp_path,
            modeling_mode=ModelingMode.HIGH_FIDELITY,
            material_source="material_archive",
            color_layers=max_layer_count,
            material_matrix=np.zeros(
                (4, 4, max_layer_count),
                dtype=np.int32,
            ),
            cache_overrides={"quantized_image": quantized_image},
        )
        dynamic_settings = {
            "material_dynamic_layer_count_enabled": True,
            "material_min_layer_count": 5,
            "material_max_layer_count": max_layer_count,
            "material_delta_e00_tolerance": 0.5,
        }
        for key, value in dynamic_settings.items():
            _test_store.put(sid, key, value)
        _test_store.put(sid, "selected_materials", ["mat-a", "mat-b"])
        payload["params"].update(dynamic_settings)

        try:
            response = client.post("/api/convert/generate", json=payload)

            assert response.status_code == 409, response.text
            assert response.json()["detail"] == self._INVALID_DETAIL
            _mock_pool.submit.assert_not_called()
        finally:
            _test_store.close(sid)

    @pytest.mark.parametrize(
        ("modeling_mode", "material_source", "invalid_arrays"),
        [
            (
                ModelingMode.HIGH_FIDELITY,
                "lut",
                {"matched_rgb": np.zeros((4, 4), dtype=np.uint8)},
            ),
            (
                ModelingMode.VECTOR,
                "lut",
                {"mask_solid": np.ones((4, 4), dtype=np.uint8)},
            ),
            (
                ModelingMode.HIGH_FIDELITY,
                "material_archive",
                {"material_matrix": np.zeros((4, 4, 5), dtype=np.float32)},
            ),
        ],
    )
    def test_generate_explicit_cache_rejects_malformed_trio_before_worker(
        self,
        tmp_path,
        modeling_mode: ModelingMode,
        material_source: str,
        invalid_arrays: dict[str, np.ndarray],
    ) -> None:
        """Raster, vector, and archive paths must reject malformed arrays."""

        sid, payload = self._create_session(
            tmp_path,
            modeling_mode=modeling_mode,
            material_source=material_source,
            **invalid_arrays,
        )
        try:
            response = client.post("/api/convert/generate", json=payload)

            assert response.status_code == 409, response.text
            assert response.json()["detail"] == self._INVALID_DETAIL
            _mock_pool.submit.assert_not_called()
        finally:
            _test_store.close(sid)

    def test_generate_explicit_cache_rejects_semantic_mismatch_before_worker(
        self,
        tmp_path,
    ) -> None:
        """Explicit reuse must not forward arrays created with stale params."""

        sid, payload = self._create_session(
            tmp_path,
            modeling_mode=ModelingMode.HIGH_FIDELITY,
            cache_overrides={"enable_cleanup": False},
        )
        try:
            response = client.post("/api/convert/generate", json=payload)

            assert response.status_code == 409, response.text
            assert response.json()["detail"] == self._INVALID_DETAIL
            _mock_pool.submit.assert_not_called()
        finally:
            _test_store.close(sid)

    @pytest.mark.parametrize(
        "modeling_mode",
        [ModelingMode.VECTOR, ModelingMode.HIGH_FIDELITY],
    )
    def test_generate_dimension_change_replays_edits_on_fresh_analysis(
        self,
        tmp_path,
        modeling_mode: ModelingMode,
    ) -> None:
        """A size change forwards edit deltas but never reuses the old grid."""

        pristine_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
        edited_rgb = pristine_rgb.copy()
        edited_rgb[:2, :2] = [220, 30, 40]
        pristine_material = np.zeros((4, 4, 5), dtype=np.int16)
        edited_material = pristine_material.copy()
        edited_material[:2, :2] = 1
        sid, payload = self._create_session(
            tmp_path,
            modeling_mode=modeling_mode,
            matched_rgb=edited_rgb,
            material_matrix=edited_material,
            cache_overrides={
                "original_matched_rgb": pristine_rgb,
                "original_material_matrix": pristine_material,
            },
        )
        payload["params"]["target_width_mm"] = 80.0
        try:
            response = client.post("/api/convert/generate", json=payload)

            assert response.status_code == 200, response.text
            submitted = _mock_pool.submit.call_args.args[3]
            assert submitted["reuse_preview_analysis"] is False
            assert submitted["edit_projection"] == {
                "mode": "delta",
                "source_shape": [4, 4],
            }
            assert submitted["original_matched_rgb_path"] is not None
            assert submitted["original_material_matrix_path"] is not None
            np.testing.assert_array_equal(
                np.load(submitted["original_matched_rgb_path"]),
                pristine_rgb,
            )
            np.testing.assert_array_equal(
                np.load(submitted["original_material_matrix_path"]),
                pristine_material,
            )
            assert submitted["preview_glb_path"] is None
        finally:
            _test_store.close(sid)

    def test_generate_dimension_change_rejects_missing_pristine_edit_artifacts(
        self,
        tmp_path,
    ) -> None:
        """A stale cache cannot masquerade as an edit delta after resizing."""

        sid, payload = self._create_session(
            tmp_path,
            modeling_mode=ModelingMode.VECTOR,
        )
        payload["params"]["target_width_mm"] = 80.0
        try:
            response = client.post("/api/convert/generate", json=payload)

            assert response.status_code == 409, response.text
            assert response.json()["detail"] == self._INVALID_DETAIL
            _mock_pool.submit.assert_not_called()
        finally:
            _test_store.close(sid)

    def test_generate_dimension_change_without_edits_needs_no_replay_artifacts(
        self,
        tmp_path,
    ) -> None:
        """A plain size change runs fresh analysis without old-grid artifacts."""

        sid, payload = self._create_session(
            tmp_path,
            modeling_mode=ModelingMode.VECTOR,
        )
        payload["params"]["target_width_mm"] = 80.0
        payload["params"]["use_cached_matched_rgb"] = False
        try:
            response = client.post("/api/convert/generate", json=payload)

            assert response.status_code == 200, response.text
            submitted = _mock_pool.submit.call_args.args[3]
            assert submitted["reuse_preview_analysis"] is False
            assert submitted["edit_projection"] is None
            assert submitted["matched_rgb_path"] is None
            assert submitted["material_matrix_path"] is None
        finally:
            _test_store.close(sid)

    def test_generate_dimension_change_projects_recipe_only_edits(
        self,
        tmp_path,
    ) -> None:
        """A custom recipe footprint also activates fresh-size edit replay."""

        pristine_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
        pristine_material = np.zeros((4, 4, 5), dtype=np.int16)
        sid, payload = self._create_session(
            tmp_path,
            modeling_mode=ModelingMode.VECTOR,
            cache_overrides={
                "original_matched_rgb": pristine_rgb.copy(),
                "original_material_matrix": pristine_material.copy(),
            },
        )
        payload["params"].update(
            {
                "target_width_mm": 80.0,
                "use_cached_matched_rgb": False,
                "recipe_overrides": [
                    {
                        "region_id": "region-A",
                        "recipe": [1, 1, 1, 1, 1],
                        "layer_order": "Top2Bottom",
                    }
                ],
            }
        )
        try:
            with patch(
                "api.routers.converter.generate._prepare_recipe_override_worker_inputs",
                return_value=(None, str(tmp_path / "masks.pkl")),
            ):
                response = client.post("/api/convert/generate", json=payload)

            assert response.status_code == 200, response.text
            submitted = _mock_pool.submit.call_args.args[3]
            assert submitted["edit_projection"] == {
                "mode": "recipe_masks",
                "source_shape": [4, 4],
            }
            assert submitted["reuse_preview_analysis"] is False
            assert submitted["original_matched_rgb_path"] is None
            assert submitted["original_material_matrix_path"] is None
            assert submitted["recipe_override_masks_path"].endswith("masks.pkl")
        finally:
            _test_store.close(sid)

    @pytest.mark.parametrize("large_format", [False, True])
    @pytest.mark.parametrize("preview_changes", [
        {"svg_hole_compensation_enabled": False},
        {"svg_hole_max_area_mm2": 0.1},
        {"target_width_mm": 60.0},
        {},
    ])
    def test_recipe_region_masks_require_matching_compensated_geometry(
        self, tmp_path, large_format, preview_changes,
    ) -> None:
        sid, payload = self._create_session(tmp_path, modeling_mode=ModelingMode.VECTOR)
        settings = {
            "svg_hole_compensation_enabled": True,
            "svg_hole_max_area_mm2": 0.5, "svg_hole_max_width_mm": 0.1,
        }
        cache = _test_store.get(sid)["preview_cache"]
        cache.update({**settings, **preview_changes})
        mask = np.zeros((4, 4), dtype=bool)
        mask[1:3, 1:3] = True
        _test_store.put(sid, "selected_region_masks", {"region-A": mask})
        payload["params"].update({
            **settings, "use_cached_matched_rgb": False,
            "recipe_overrides": [{
                "region_id": "region-A", "recipe": [1] * 5,
                "layer_order": "Top2Bottom",
            }],
        })
        if large_format:
            payload = {
                "session_id": sid,
                "params": {
                    "target_height_mm": 40.0,
                    "tile_width_mm": 20.0, "tile_height_mm": 20.0,
                    "params": payload["params"],
                },
            }
        route = "/api/convert/generate-large-format" if large_format else "/api/convert/generate"
        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_svg_native",
                return_value=_large_format_success_response("native"),
            ) as native_tiles:
                response = client.post(route, json=payload)
                if preview_changes:
                    assert response.status_code == 409, response.text
                    _mock_pool.submit.assert_not_called()
                    native_tiles.assert_not_called()
                else:
                    assert response.status_code == 200, response.text
                    params = native_tiles.call_args.kwargs if large_format else _mock_pool.submit.call_args.args[3]
                    assert params["material_matrix_path"] is not None
                    with open(params["recipe_override_masks_path"], "rb") as stream:
                        saved = pickle.load(stream)
                    np.testing.assert_array_equal(saved["region-A"], mask)
        finally:
            _test_store.close(sid)

    @pytest.mark.parametrize("compensation_enabled, artwork_width", [
        (False, 40.0), (True, 40.0), (True, 60.0),
    ])
    def test_model_surface_uses_artwork_width_for_edit_grid_identity(
        self,
        tmp_path,
        compensation_enabled,
        artwork_width,
    ) -> None:
        """The outer model size must not invalidate unchanged surface artwork."""

        sid, payload = self._create_session(
            tmp_path,
            modeling_mode=ModelingMode.VECTOR,
        )
        settings = {
            "svg_hole_compensation_enabled": compensation_enabled,
            "svg_hole_max_area_mm2": 0.5,
            "svg_hole_max_width_mm": 0.1,
        }
        payload["params"].update(settings)
        _test_store.get(sid)["preview_cache"].update(settings)
        model_path = tmp_path / "surface-model.stl"
        model_path.write_bytes(b"solid surface\nendsolid surface\n")
        _test_store.put(sid, "surface_overlay_enabled", True)
        _test_store.put(sid, "surface_model_path", str(model_path))
        _test_store.put(sid, "surface_target_width_mm", artwork_width)
        _test_store.put(
            sid,
            "surface_footprint",
            {
                "frame": {
                    "origin": [0.0, 0.0, 0.0],
                    "normal": [0.0, 0.0, 1.0],
                    "u_axis": [1.0, 0.0, 0.0],
                    "v_axis": [0.0, 1.0, 0.0],
                },
                "outer": [[0.0, 0.0], [40.0, 0.0], [40.0, 40.0]],
                "holes": [],
                "bounds_width_mm": 40.0,
                "bounds_height_mm": 40.0,
            },
        )
        payload["params"]["target_width_mm"] = 80.0
        try:
            response = client.post("/api/convert/generate", json=payload)

            if compensation_enabled and artwork_width != 40.0:
                assert response.status_code == 409, response.text
                _mock_pool.submit.assert_not_called()
                return
            assert response.status_code == 200, response.text
            submitted = _mock_pool.submit.call_args.args[3]
            converter_params = submitted["converter_params"]
            assert converter_params["target_width_mm"] == pytest.approx(40.0)
            assert converter_params["edit_projection"] is None
            assert converter_params["original_matched_rgb_path"] is None
            assert converter_params["original_material_matrix_path"] is None
        finally:
            _test_store.close(sid)

    def test_generate_explicit_cache_rejects_deleted_artifact_before_worker(
        self,
        tmp_path,
    ) -> None:
        """An artifact removed after preview must require a fresh preview."""

        sid, payload = self._create_session(
            tmp_path,
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )
        cache = _test_store.get(sid)["preview_cache"]
        cache_ref = externalize_preview_cache(
            sid,
            _test_store,
            cache,
            root_dir=tmp_path / "cache",
        )
        _test_store.put(sid, "preview_cache", cache_ref)
        os.unlink(cache_ref["fields"]["mask_solid"]["path"])
        try:
            response = client.post("/api/convert/generate", json=payload)

            assert response.status_code == 409, response.text
            assert response.json()["detail"] == self._INVALID_DETAIL
            _mock_pool.submit.assert_not_called()
        finally:
            _test_store.close(sid)

    def test_generate_required_cache_worker_error_returns_safe_409(
        self,
        tmp_path,
    ) -> None:
        """A post-validation worker failure must request a new preview."""

        from core.errors import CachedPreviewAnalysisError

        sid, payload = self._create_session(
            tmp_path,
            modeling_mode=ModelingMode.VECTOR,
        )
        private_path = "/Users/min/private/deleted-preview-cache.npy"
        _mock_pool.submit = AsyncMock(
            side_effect=CachedPreviewAnalysisError(
                f"cannot read {private_path}"
            )
        )
        try:
            response = client.post("/api/convert/generate", json=payload)

            assert response.status_code == 409, response.text
            assert response.json()["detail"] == self._INVALID_DETAIL
            assert private_path not in response.text
        finally:
            _test_store.close(sid)


class TestLargeFormatCachedAnalysisRouting:
    """Verify large-format routes preserve validated spatial preview edits."""

    @staticmethod
    def _analysis_arrays() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        matched_rgb = np.arange(8 * 12 * 3, dtype=np.uint8).reshape(8, 12, 3)
        mask_solid = (np.arange(8 * 12).reshape(8, 12) % 3) != 0
        material_matrix = np.arange(8 * 12 * 5, dtype=np.int16).reshape(8, 12, 5)
        return matched_rgb, mask_solid, material_matrix

    @staticmethod
    def _semantic_cache_metadata(
        *,
        modeling_mode: ModelingMode,
        target_width_mm: float = 120.0,
        material_source: str = "lut",
    ) -> dict[str, object]:
        """Return the canonical preview-analysis parameters for one request."""

        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=modeling_mode,
            target_width_mm=target_width_mm,
        )
        return {
            "target_width_mm": target_width_mm,
            "color_mode": request.color_mode.value,
            "modeling_mode": request.modeling_mode.value,
            "color_layers": 5,
            "layer_height_mm": 0.08,
            "quantize_colors": request.quantize_colors,
            "enable_cleanup": request.enable_cleanup,
            "hue_weight": request.hue_weight,
            "chroma_gate": request.chroma_gate,
            "use_lut_constrained": request.use_lut_constrained,
            "auto_dynamic_range": request.auto_dynamic_range,
            "model_enable": request.model_enable,
            "model_only": request.model_only,
            "model_threshold": request.model_threshold,
            "model_margin": request.model_margin,
            "svg_pixels_per_mm": request.svg_pixels_per_mm,
            "material_source": material_source,
        }

    @staticmethod
    def _put_legacy_cache(
        sid: str,
        *,
        matched_rgb: object,
        mask_solid: object,
        material_matrix: object,
        target_w: object = 12,
        target_h: object = 8,
        modeling_mode: ModelingMode = ModelingMode.VECTOR,
    ) -> None:
        _test_store.put(
            sid,
            "preview_cache",
            {
                "target_w": target_w,
                "target_h": target_h,
                **TestLargeFormatCachedAnalysisRouting._semantic_cache_metadata(
                    modeling_mode=modeling_mode,
                ),
                "matched_rgb": matched_rgb,
                "mask_solid": mask_solid,
                "material_matrix": material_matrix,
            },
        )

    def test_large_format_cached_native_svg_forwards_legacy_arrays(self) -> None:
        sid, svg_path, lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=True,
        )
        matched_rgb, mask_solid, material_matrix = self._analysis_arrays()
        self._put_legacy_cache(
            sid,
            matched_rgb=matched_rgb,
            mask_solid=mask_solid,
            material_matrix=material_matrix,
        )

        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_svg_native",
                return_value=_large_format_success_response("native"),
            ) as native_helper:
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="vector",
                        use_cached_matched_rgb=True,
                    ),
                )

            assert response.status_code == 200, response.text
            kwargs = native_helper.call_args.kwargs
            for key in ("matched_rgb_path", "mask_solid_path", "material_matrix_path"):
                assert kwargs[key] is not None
                assert os.path.isfile(kwargs[key])
            assert np.array_equal(np.load(kwargs["matched_rgb_path"]), matched_rgb)
            assert np.array_equal(np.load(kwargs["mask_solid_path"]), mask_solid)
            assert np.array_equal(np.load(kwargs["material_matrix_path"]), material_matrix)
        finally:
            _test_store.close(sid)
            for path in (svg_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_dynamic_native_svg_reuses_int32_matrix_without_quantized_asset(
        self,
    ) -> None:
        """Native SVG keeps its three vector cache assets; P03 quantized data is raster-only."""

        sid, svg_path, lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=True,
        )
        matched_rgb = np.zeros((8, 12, 3), dtype=np.uint8)
        mask_solid = np.ones((8, 12), dtype=bool)
        material_matrix = np.zeros((8, 12, 7), dtype=np.int32)
        _test_store.put(
            sid,
            "preview_cache",
            {
                "target_w": 12,
                "target_h": 8,
                **self._semantic_cache_metadata(
                    modeling_mode=ModelingMode.VECTOR,
                    material_source="material_archive",
                ),
                "color_layers": 7,
                "matched_rgb": matched_rgb,
                "mask_solid": mask_solid,
                "material_matrix": material_matrix,
                "material_dynamic_layer_info": {
                    "enabled": True,
                    "max_layer_count": 7,
                },
            },
        )
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(sid, "selected_materials", ["brand/base", "brand/red"])
        _test_store.put(sid, "color_layers", 7)
        _test_store.put(sid, "material_dynamic_layer_count_enabled", True)
        _test_store.put(sid, "material_min_layer_count", 5)
        _test_store.put(sid, "material_max_layer_count", 7)
        _test_store.put(sid, "material_delta_e00_tolerance", 0.5)

        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_svg_native",
                return_value=_large_format_success_response("native-dynamic"),
            ) as native_helper:
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="vector",
                        use_cached_matched_rgb=True,
                        request_overrides={
                            "lut_name": "__material_archive__",
                            "color_layers": 7,
                            "material_dynamic_layer_count_enabled": True,
                            "material_min_layer_count": 5,
                            "material_max_layer_count": 7,
                            "material_delta_e00_tolerance": 0.5,
                        },
                    ),
                )

            assert response.status_code == 200, response.text
            kwargs = native_helper.call_args.kwargs
            assert kwargs["dynamic_material_settings"] == (True, 5, 7, 0.5)
            for field_name in (
                "matched_rgb_path",
                "mask_solid_path",
                "material_matrix_path",
            ):
                assert kwargs[field_name] is not None
            assert "quantized_image_path" not in kwargs
        finally:
            _test_store.close(sid)
            for path in (svg_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_dynamic_native_svg_rejects_non_int32_matrix(self) -> None:
        sid, svg_path, lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=True,
        )
        _test_store.put(
            sid,
            "preview_cache",
            {
                "target_w": 12,
                "target_h": 8,
                **self._semantic_cache_metadata(
                    modeling_mode=ModelingMode.VECTOR,
                    material_source="material_archive",
                ),
                "color_layers": 7,
                "matched_rgb": np.zeros((8, 12, 3), dtype=np.uint8),
                "mask_solid": np.ones((8, 12), dtype=bool),
                "material_matrix": np.zeros((8, 12, 7), dtype=np.int16),
                "material_dynamic_layer_info": {"enabled": True},
            },
        )
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(sid, "selected_materials", ["brand/base", "brand/red"])
        _test_store.put(sid, "color_layers", 7)
        _test_store.put(sid, "material_dynamic_layer_count_enabled", True)
        _test_store.put(sid, "material_min_layer_count", 5)
        _test_store.put(sid, "material_max_layer_count", 7)
        _test_store.put(sid, "material_delta_e00_tolerance", 0.5)

        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_svg_native"
            ) as native_helper:
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="vector",
                        use_cached_matched_rgb=True,
                        request_overrides={
                            "lut_name": "__material_archive__",
                            "color_layers": 7,
                            "material_dynamic_layer_count_enabled": True,
                            "material_min_layer_count": 5,
                            "material_max_layer_count": 7,
                            "material_delta_e00_tolerance": 0.5,
                        },
                    ),
                )

            assert response.status_code == 409, response.text
            assert response.json()["detail"] == LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL
            native_helper.assert_not_called()
        finally:
            _test_store.close(sid)
            for path in (svg_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_cached_native_worker_error_returns_sanitized_409(
        self,
    ) -> None:
        """A post-validation cache failure must not leak its private path."""

        sid, svg_path, lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=True,
        )
        matched_rgb, mask_solid, material_matrix = self._analysis_arrays()
        self._put_legacy_cache(
            sid,
            matched_rgb=matched_rgb,
            mask_solid=mask_solid,
            material_matrix=material_matrix,
        )
        private_path = "/Users/min/private/deleted-preview-cache.npy"
        _mock_pool.submit = AsyncMock(
            side_effect=LargeFormatCachedAnalysisError(
                f"cannot read {private_path}: file disappeared"
            )
        )

        try:
            response = client.post(
                "/api/convert/generate-large-format",
                json=_large_format_payload(
                    sid,
                    modeling_mode="vector",
                    use_cached_matched_rgb=True,
                ),
            )

            assert response.status_code == 409, response.text
            assert (
                response.json()["detail"]
                == LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL
            )
            assert private_path not in response.text
            assert "file disappeared" not in response.text
        finally:
            _test_store.close(sid)
            for path in (svg_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_cached_native_svg_forwards_artifact_paths_without_hydration(
        self,
        tmp_path,
    ) -> None:
        sid, svg_path, lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=True,
        )
        matched_rgb, mask_solid, material_matrix = self._analysis_arrays()
        cache_ref = externalize_preview_cache(
            sid,
            _test_store,
            {
                "target_w": 12,
                "target_h": 8,
                **self._semantic_cache_metadata(modeling_mode=ModelingMode.VECTOR),
                "matched_rgb": matched_rgb,
                "mask_solid": mask_solid,
                "material_matrix": material_matrix,
            },
            root_dir=tmp_path,
        )
        _test_store.put(sid, "preview_cache", cache_ref)

        try:
            with (
                patch(
                    "api.routers.converter.generate.hydrate_preview_cache",
                    side_effect=AssertionError("large-format cache must not hydrate arrays"),
                ),
                patch(
                    "api.routers.converter.generate._generate_large_format_svg_native",
                    return_value=_large_format_success_response("native"),
                ) as native_helper,
            ):
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="vector",
                        use_cached_matched_rgb=True,
                    ),
                )

            assert response.status_code == 200, response.text
            kwargs = native_helper.call_args.kwargs
            assert kwargs["matched_rgb_path"] == cache_ref["fields"]["matched_rgb"]["path"]
            assert kwargs["mask_solid_path"] == cache_ref["fields"]["mask_solid"]["path"]
            assert kwargs["material_matrix_path"] == cache_ref["fields"]["material_matrix"]["path"]
            assert np.array_equal(np.load(kwargs["matched_rgb_path"]), matched_rgb)
            assert np.array_equal(np.load(kwargs["mask_solid_path"]), mask_solid)
            assert np.array_equal(np.load(kwargs["material_matrix_path"]), material_matrix)
        finally:
            _test_store.close(sid)
            for path in (svg_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_cached_raster_forwards_validated_paths(self) -> None:
        sid, image_path, lut_path = _create_raster_large_format_session(_test_store)
        matched_rgb, mask_solid, material_matrix = self._analysis_arrays()
        self._put_legacy_cache(
            sid,
            matched_rgb=matched_rgb,
            mask_solid=mask_solid,
            material_matrix=material_matrix,
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )
        _test_store.put(sid, "recipe_overrides", [])
        _test_store.put(sid, "selected_region_masks", {})

        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=_large_format_success_response("raster"),
            ) as raster_helper:
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="high-fidelity",
                        use_cached_matched_rgb=True,
                    ),
                )

            assert response.status_code == 200, response.text
            kwargs = raster_helper.call_args.kwargs
            assert np.array_equal(np.load(kwargs["matched_rgb_path"]), matched_rgb)
            assert np.array_equal(np.load(kwargs["mask_solid_path"]), mask_solid)
            assert np.array_equal(np.load(kwargs["material_matrix_path"]), material_matrix)
        finally:
            _test_store.close(sid)
            for path in (image_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_dynamic_cached_raster_forwards_quantized_image(
        self,
    ) -> None:
        """The dynamic large-format route passes the fourth P03 asset to tiling."""

        sid, image_path, lut_path = _create_raster_large_format_session(_test_store)
        matched_rgb = np.arange(8 * 12 * 3, dtype=np.uint8).reshape(8, 12, 3)
        mask_solid = np.ones((8, 12), dtype=bool)
        quantized_image = np.flip(matched_rgb, axis=2).copy()
        material_matrix = np.zeros((8, 12, 6), dtype=np.int32)
        cache = {
            "target_w": 12,
            "target_h": 8,
            **self._semantic_cache_metadata(
                modeling_mode=ModelingMode.HIGH_FIDELITY,
                material_source="material_archive",
            ),
            "color_layers": 6,
            "matched_rgb": matched_rgb,
            "mask_solid": mask_solid,
            "quantized_image": quantized_image,
            "material_matrix": material_matrix,
        }
        _test_store.put(sid, "preview_cache", cache)
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(sid, "selected_materials", ["mat-a", "mat-b"])
        _test_store.put(sid, "material_layer_count", 6)
        _test_store.put(sid, "material_dynamic_layer_count_enabled", True)
        _test_store.put(sid, "material_min_layer_count", 5)
        _test_store.put(sid, "material_max_layer_count", 6)
        _test_store.put(sid, "material_delta_e00_tolerance", 0.5)
        _test_store.put(sid, "recipe_overrides", [])
        _test_store.put(sid, "selected_region_masks", {})

        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=_large_format_success_response("raster"),
            ) as raster_helper:
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="high-fidelity",
                        use_cached_matched_rgb=True,
                        request_overrides={
                            "lut_name": "__material_archive__",
                            "color_layers": 6,
                            "material_dynamic_layer_count_enabled": True,
                            "material_min_layer_count": 5,
                            "material_max_layer_count": 6,
                            "material_delta_e00_tolerance": 0.5,
                        },
                    ),
                )

            assert response.status_code == 200, response.text
            quantized_path = raster_helper.call_args.kwargs[
                "quantized_image_path"
            ]
            assert quantized_path is not None
            assert np.array_equal(np.load(quantized_path), quantized_image)
        finally:
            _test_store.close(sid)
            for path in (image_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_dynamic_cached_raster_rejects_missing_quantized_image(
        self,
    ) -> None:
        """A stale dynamic cache must fail before the large-format helper runs."""

        sid, image_path, lut_path = _create_raster_large_format_session(_test_store)
        matched_rgb = np.zeros((8, 12, 3), dtype=np.uint8)
        mask_solid = np.ones((8, 12), dtype=bool)
        material_matrix = np.zeros((8, 12, 6), dtype=np.int32)
        _test_store.put(
            sid,
            "preview_cache",
            {
                "target_w": 12,
                "target_h": 8,
                **self._semantic_cache_metadata(
                    modeling_mode=ModelingMode.HIGH_FIDELITY,
                    material_source="material_archive",
                ),
                "color_layers": 6,
                "matched_rgb": matched_rgb,
                "mask_solid": mask_solid,
                "material_matrix": material_matrix,
            },
        )
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(sid, "selected_materials", ["mat-a", "mat-b"])
        _test_store.put(sid, "material_layer_count", 6)
        _test_store.put(sid, "material_dynamic_layer_count_enabled", True)
        _test_store.put(sid, "material_min_layer_count", 5)
        _test_store.put(sid, "material_max_layer_count", 6)
        _test_store.put(sid, "material_delta_e00_tolerance", 0.5)

        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=_large_format_success_response("raster"),
            ) as raster_helper:
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="high-fidelity",
                        use_cached_matched_rgb=True,
                        request_overrides={
                            "lut_name": "__material_archive__",
                            "color_layers": 6,
                            "material_dynamic_layer_count_enabled": True,
                            "material_min_layer_count": 5,
                            "material_max_layer_count": 6,
                            "material_delta_e00_tolerance": 0.5,
                        },
                    ),
                )

            assert response.status_code == 409, response.text
            assert (
                response.json()["detail"]
                == LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL
            )
            raster_helper.assert_not_called()
        finally:
            _test_store.close(sid)
            for path in (image_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_cached_request_inherits_preview_layer_settings(self) -> None:
        sid, image_path, lut_path = _create_raster_large_format_session(_test_store)
        matched_rgb, mask_solid, material_matrix = self._analysis_arrays()
        self._put_legacy_cache(
            sid,
            matched_rgb=matched_rgb,
            mask_solid=mask_solid,
            material_matrix=material_matrix,
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )
        session_data = _test_store.get(sid)
        cache = session_data["preview_cache"]
        cache["color_layers"] = 6
        cache["layer_height_mm"] = 0.12
        _test_store.put(sid, "preview_cache", cache)
        _test_store.put(sid, "color_layers", 6)
        _test_store.put(sid, "layer_height_mm", 0.12)
        _test_store.put(sid, "recipe_overrides", [])
        _test_store.put(sid, "selected_region_masks", {})

        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=_large_format_success_response("raster"),
            ) as raster_helper:
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="high-fidelity",
                        use_cached_matched_rgb=True,
                    ),
                )

            assert response.status_code == 200, response.text
            effective_request = raster_helper.call_args.kwargs["request"]
            assert effective_request.color_layers == 6
            assert effective_request.layer_height_mm == pytest.approx(0.12)
        finally:
            _test_store.close(sid)
            for path in (image_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    @pytest.mark.parametrize(
        ("request_overrides", "target_width_mm"),
        [
            ({"target_width_mm": 121.0}, 120.0),
            ({"color_mode": "8-Color Max"}, 120.0),
            ({"modeling_mode": "pixel"}, 120.0),
            ({"color_layers": 8}, 120.0),
            ({"layer_height_mm": 0.12}, 120.0),
            ({"quantize_colors": 64}, 120.0),
            ({"enable_cleanup": False}, 120.0),
            ({"hue_weight": 0.5}, 120.0),
            ({"chroma_gate": 10.0}, 120.0),
            ({"use_lut_constrained": True}, 120.0),
            ({"auto_dynamic_range": True}, 120.0),
            ({"model_enable": True}, 120.0),
            ({"model_only": True}, 120.0),
            ({"model_threshold": 0.25}, 120.0),
            ({"model_margin": 0.05}, 120.0),
            ({"svg_pixels_per_mm": 8.0}, 120.0),
        ],
    )
    def test_large_format_cached_semantic_mismatch_requires_new_preview(
        self,
        request_overrides: dict[str, object],
        target_width_mm: float,
    ) -> None:
        """Every analysis-affecting request change must reject stale arrays."""

        sid, image_path, lut_path = _create_raster_large_format_session(_test_store)
        matched_rgb, mask_solid, material_matrix = self._analysis_arrays()
        self._put_legacy_cache(
            sid,
            matched_rgb=matched_rgb,
            mask_solid=mask_solid,
            material_matrix=material_matrix,
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )
        _mock_pool.submit = AsyncMock()

        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=_large_format_success_response("raster"),
            ) as raster_helper:
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="high-fidelity",
                        use_cached_matched_rgb=True,
                        target_width_mm=target_width_mm,
                        request_overrides=request_overrides,
                    ),
                )

            assert response.status_code == 409, response.text
            assert response.json()["detail"] == LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL
            raster_helper.assert_not_called()
            _mock_pool.submit.assert_not_called()
        finally:
            _test_store.close(sid)
            for path in (image_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_cached_material_source_mismatch_requires_new_preview(
        self,
    ) -> None:
        sid, image_path, lut_path = _create_raster_large_format_session(_test_store)
        matched_rgb, mask_solid, material_matrix = self._analysis_arrays()
        self._put_legacy_cache(
            sid,
            matched_rgb=matched_rgb,
            mask_solid=mask_solid,
            material_matrix=material_matrix,
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )
        _test_store.put(sid, "material_source", "material_archive")
        _mock_pool.submit = AsyncMock()

        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=_large_format_success_response("raster"),
            ) as raster_helper:
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="high-fidelity",
                        use_cached_matched_rgb=True,
                    ),
                )

            assert response.status_code == 409, response.text
            assert response.json()["detail"] == LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL
            raster_helper.assert_not_called()
            _mock_pool.submit.assert_not_called()
        finally:
            _test_store.close(sid)
            for path in (image_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_cached_old_metadata_requires_new_preview(self) -> None:
        """Old caches without semantic fields are unsafe for explicit reuse."""

        sid, image_path, lut_path = _create_raster_large_format_session(_test_store)
        matched_rgb, mask_solid, material_matrix = self._analysis_arrays()
        _test_store.put(
            sid,
            "preview_cache",
            {
                "target_w": 12,
                "target_h": 8,
                "target_width_mm": 120.0,
                "matched_rgb": matched_rgb,
                "mask_solid": mask_solid,
                "material_matrix": material_matrix,
            },
        )

        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=_large_format_success_response("raster"),
            ) as raster_helper:
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="high-fidelity",
                        use_cached_matched_rgb=True,
                    ),
                )

            assert response.status_code == 409, response.text
            assert response.json()["detail"] == LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL
            raster_helper.assert_not_called()
        finally:
            _test_store.close(sid)
            for path in (image_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_semantic_mismatch_is_ignored_when_cache_flag_false(
        self,
    ) -> None:
        """Ordinary generation must not validate or consume stale analysis."""

        sid, svg_path, lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=True,
        )
        matched_rgb, mask_solid, material_matrix = self._analysis_arrays()
        self._put_legacy_cache(
            sid,
            matched_rgb=matched_rgb,
            mask_solid=mask_solid,
            material_matrix=material_matrix,
            modeling_mode=ModelingMode.VECTOR,
        )

        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=_large_format_success_response("raster"),
            ) as raster_helper:
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="vector",
                        use_cached_matched_rgb=False,
                        request_overrides={
                            "color_mode": "8-Color Max",
                            "modeling_mode": "pixel",
                            "color_layers": 8,
                        },
                    ),
                )

            assert response.status_code == 200, response.text
            kwargs = raster_helper.call_args.kwargs
            assert kwargs["matched_rgb_path"] is None
            assert kwargs["mask_solid_path"] is None
            assert kwargs["material_matrix_path"] is None
        finally:
            _test_store.close(sid)
            for path in (svg_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    @pytest.mark.parametrize(
        ("cached_analysis_is_final", "expected_replacements"),
        [
            (True, None),
            (
                False,
                [
                    {
                        "quantized_hex": "#ff0000",
                        "matched_hex": "#ff0000",
                        "replacement_hex": "#0000ff",
                    }
                ],
            ),
        ],
    )
    def test_large_format_native_shared_params_apply_global_mapping_at_most_once(
        self,
        cached_analysis_is_final: bool,
        expected_replacements: list[dict[str, str]] | None,
    ) -> None:
        """A complete final cache must override native SVG global mappings."""

        replacement_regions = [
            {
                "quantized_hex": "#ff0000",
                "matched_hex": "#ff0000",
                "replacement_hex": "#0000ff",
            }
        ]
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.VECTOR,
            backing_infill_density_percent=25,
        )

        params = _resolve_large_format_shared_params(
            {
                "material_source": "lut",
                "replacement_regions": replacement_regions,
            },
            request,
            None,
            matched_rgb_path="matched.npy",
            mask_solid_path="mask.npy",
            material_matrix_path="material.npy",
            cached_analysis_is_final=cached_analysis_is_final,
        )

        assert params["replacement_regions"] == expected_replacements
        assert params["backing_infill_density_percent"] == 25

    @pytest.mark.parametrize(
        "malformed_case",
        [
            "missing",
            "unreadable",
            "matched_wrong_rank",
            "matched_wrong_dtype",
            "mask_wrong_rank",
            "mask_wrong_dtype",
            "material_wrong_rank",
            "material_wrong_dtype",
            "material_empty_channels",
            "spatial_mismatch",
            "metadata_mismatch",
            "target_w_non_numeric",
            "target_h_non_numeric",
            "missing_metadata",
            "corrupt_zip_artifact",
        ],
    )
    def test_large_format_cached_malformed_cache_returns_safe_409(
        self,
        malformed_case: str,
        tmp_path,
    ) -> None:
        sid, svg_path, lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=True,
        )
        matched_rgb, mask_solid, material_matrix = self._analysis_arrays()
        local_secret_path: str | None = None
        target_w = 12
        target_h = 8
        cache_already_stored = False

        if malformed_case == "missing":
            material_matrix = None
        elif malformed_case == "unreadable":
            cache_ref = externalize_preview_cache(
                sid,
                _test_store,
                {
                    "target_w": target_w,
                    "target_h": target_h,
                    "target_width_mm": 60.0,
                    "matched_rgb": matched_rgb,
                    "mask_solid": mask_solid,
                    "material_matrix": material_matrix,
                },
                root_dir=tmp_path,
            )
            unreadable_path = tmp_path / "private-cache-mask.npy"
            unreadable_path.write_bytes(b"not-a-numpy-array")
            cache_ref["fields"]["mask_solid"]["path"] = str(unreadable_path)
            local_secret_path = str(unreadable_path)
            _test_store.put(sid, "preview_cache", cache_ref)
            cache_already_stored = True
        elif malformed_case == "matched_wrong_rank":
            matched_rgb = matched_rgb[..., 0]
        elif malformed_case == "matched_wrong_dtype":
            matched_rgb = matched_rgb.astype(np.int16)
        elif malformed_case == "mask_wrong_rank":
            mask_solid = mask_solid[..., None]
        elif malformed_case == "mask_wrong_dtype":
            mask_solid = mask_solid.astype(np.uint8)
        elif malformed_case == "material_wrong_rank":
            material_matrix = material_matrix[..., 0]
        elif malformed_case == "material_wrong_dtype":
            material_matrix = material_matrix.astype(np.float32)
        elif malformed_case == "material_empty_channels":
            material_matrix = material_matrix[..., :0]
        elif malformed_case == "spatial_mismatch":
            material_matrix = material_matrix[:-1, :, :]
        elif malformed_case == "metadata_mismatch":
            target_h = 7
        elif malformed_case == "target_w_non_numeric":
            target_w = "bad"
        elif malformed_case == "target_h_non_numeric":
            target_h = "bad"
        elif malformed_case == "missing_metadata":
            _test_store.put(
                sid,
                "preview_cache",
                {
                    "target_width_mm": 60.0,
                    "matched_rgb": matched_rgb,
                    "mask_solid": mask_solid,
                    "material_matrix": material_matrix,
                },
            )
            cache_already_stored = True
        elif malformed_case == "corrupt_zip_artifact":
            cache_ref = externalize_preview_cache(
                sid,
                _test_store,
                {
                    "target_w": target_w,
                    "target_h": target_h,
                    "target_width_mm": 60.0,
                    "matched_rgb": matched_rgb,
                    "mask_solid": mask_solid,
                    "material_matrix": material_matrix,
                },
                root_dir=tmp_path,
            )
            corrupt_path = tmp_path / "private-corrupt-cache.npz"
            corrupt_path.write_bytes(b"PK\x03\x04truncated-private-archive")
            cache_ref["fields"]["material_matrix"]["path"] = str(corrupt_path)
            local_secret_path = str(corrupt_path)
            _test_store.put(sid, "preview_cache", cache_ref)
            cache_already_stored = True

        if not cache_already_stored:
            self._put_legacy_cache(
                sid,
                matched_rgb=matched_rgb,
                mask_solid=mask_solid,
                material_matrix=material_matrix,
                target_w=target_w,
                target_h=target_h,
            )

        target_height_mm = 70.0 if malformed_case == "metadata_mismatch" else 80.0
        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_svg_native",
                return_value=_large_format_success_response("native"),
            ) as native_helper:
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="vector",
                        use_cached_matched_rgb=True,
                        target_height_mm=target_height_mm,
                    ),
                )

            assert response.status_code == 409, response.text
            detail = response.json()["detail"]
            assert detail == LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL
            assert "re-run preview" in detail.lower()
            if local_secret_path is not None:
                assert local_secret_path not in detail
            native_helper.assert_not_called()
        finally:
            _test_store.close(sid)
            for path in (svg_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_cached_flag_false_ignores_malformed_cache(self) -> None:
        sid, svg_path, lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=True,
        )
        matched_rgb, mask_solid, material_matrix = self._analysis_arrays()
        self._put_legacy_cache(
            sid,
            matched_rgb=matched_rgb.astype(np.float32),
            mask_solid=mask_solid[..., None],
            material_matrix=material_matrix[:-1, :, :],
        )

        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_svg_native",
                return_value=_large_format_success_response("native"),
            ) as native_helper:
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="vector",
                        use_cached_matched_rgb=False,
                    ),
                )

            assert response.status_code == 200, response.text
            kwargs = native_helper.call_args.kwargs
            assert kwargs["matched_rgb_path"] is None
            assert kwargs["mask_solid_path"] is None
            assert kwargs["material_matrix_path"] is None
        finally:
            _test_store.close(sid)
            for path in (svg_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_cached_flag_false_ignores_corrupt_analysis_artifact(
        self,
        tmp_path,
    ) -> None:
        sid, svg_path, lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=True,
        )
        matched_rgb, mask_solid, material_matrix = self._analysis_arrays()
        cache_ref = externalize_preview_cache(
            sid,
            _test_store,
            {
                "target_w": 12,
                "target_h": 8,
                "target_width_mm": 60.0,
                "matched_rgb": matched_rgb,
                "mask_solid": mask_solid,
                "material_matrix": material_matrix,
            },
            root_dir=tmp_path,
        )
        corrupt_path = tmp_path / "ignored-corrupt-cache.npz"
        corrupt_path.write_bytes(b"PK\x03\x04truncated-private-archive")
        cache_ref["fields"]["matched_rgb"]["path"] = str(corrupt_path)
        _test_store.put(sid, "preview_cache", cache_ref)

        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_svg_native",
                return_value=_large_format_success_response("native"),
            ) as native_helper:
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="vector",
                        use_cached_matched_rgb=False,
                    ),
                )

            assert response.status_code == 200, response.text
            kwargs = native_helper.call_args.kwargs
            assert kwargs["matched_rgb_path"] is None
            assert kwargs["mask_solid_path"] is None
            assert kwargs["material_matrix_path"] is None
        finally:
            _test_store.close(sid)
            for path in (svg_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)


class TestLargeFormatDimensionsAndRouting:
    """Verify large-format ratio resolution and SVG routing behavior."""

    def test_large_format_source_basename_falls_back_to_image_path_when_session_value_missing(self) -> None:
        resolved = _resolve_large_format_source_basename({}, "/tmp/tmpabcd1234_poster-art.png")

        assert resolved == "poster-art"

    def test_large_format_source_basename_re_normalizes_unsafe_session_value(self) -> None:
        resolved = _resolve_large_format_source_basename(
            {"source_basename": " bad:name* "},
            "/tmp/ignored.png",
        )

        assert resolved == "bad_name"

    def test_large_format_inherits_dynamic_settings_before_helper(self) -> None:
        sid, _image_path, _lut_path = _create_raster_large_format_session(
            _test_store
        )
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(sid, "selected_materials", ["mat-a", "mat-b"])
        _test_store.put(sid, "material_layer_count", 10)
        _test_store.put(sid, "material_dynamic_layer_count_enabled", True)
        _test_store.put(sid, "material_min_layer_count", 6)
        _test_store.put(sid, "material_max_layer_count", 8)
        _test_store.put(sid, "material_delta_e00_tolerance", 0.4)
        _test_store.put(sid, "recipe_overrides", [])

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "__material_archive__",
                    "modeling_mode": "high-fidelity",
                    "target_width_mm": 90.0,
                },
            },
        }
        raster_response = {
            "status": "ok",
            "message": "raster",
            "download_url": "/api/files/raster",
            "tile_count": 4,
            "grid_cols": 2,
            "grid_rows": 2,
            "warnings": [],
        }

        with patch(
            "api.routers.converter.generate._generate_large_format_raster",
            return_value=raster_response,
        ) as raster_helper:
            response = client.post(
                "/api/convert/generate-large-format",
                json=payload,
            )

        assert response.status_code == 200, response.text
        assert raster_helper.call_args.kwargs["dynamic_material_settings"] == (
            True,
            6,
            8,
            0.4,
        )

    @pytest.mark.parametrize("surface_overlay_enabled", [True, False])
    def test_large_format_rejects_model_surface_overlay_before_tiling(
        self,
        surface_overlay_enabled: bool,
    ) -> None:
        """Overlay sessions must not be tiled as flat artwork at the ordinary width."""

        sid, image_path, lut_path = _create_raster_large_format_session(_test_store)
        _test_store.put(sid, "recipe_overrides", [])
        _test_store.put(sid, "selected_region_masks", {})
        if surface_overlay_enabled:
            _test_store.put(sid, "surface_overlay_enabled", True)
            _test_store.put(sid, "surface_model_path", image_path)
            _test_store.put(
                sid,
                "surface_footprint",
                {"bounds_width_mm": 960.0, "bounds_height_mm": 480.0},
            )
        payload = _large_format_payload(
            sid,
            modeling_mode="high-fidelity",
            use_cached_matched_rgb=False,
            target_width_mm=60.0,
            target_height_mm=40.0,
        )
        material_selection = MagicMock(return_value={"ready": True})

        try:
            with patch(
                "api.routers.converter.generate.require_material_selection",
                material_selection,
            ), patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=_large_format_success_response("raster"),
            ) as raster_helper, patch(
                "api.routers.converter.generate._generate_large_format_svg_native",
                return_value=_large_format_success_response("svg"),
            ) as svg_helper:
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=payload,
                )

            if surface_overlay_enabled:
                assert response.status_code == 422, response.text
                detail = response.json()["detail"]
                assert "model surface overlay" in detail
                assert "Turn off large-format mode or model surface overlay" in detail
                material_selection.assert_not_called()
                raster_helper.assert_not_called()
                svg_helper.assert_not_called()
            else:
                assert response.status_code == 200, response.text
                raster_helper.assert_called_once()
                assert raster_helper.call_args.kwargs["total_width_mm"] == 60.0
        finally:
            _test_store.close(sid)
            for path in (image_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_dynamic_mismatch_rejects_before_temp_preparation(
        self,
    ) -> None:
        from api.routers.converter.common import (
            _resolve_session_dynamic_material_settings,
        )

        sid, _image_path, _lut_path = _create_raster_large_format_session(
            _test_store
        )
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(sid, "selected_materials", ["mat-a", "mat-b"])
        _test_store.put(sid, "material_dynamic_layer_count_enabled", True)
        _test_store.put(sid, "material_min_layer_count", 5)
        _test_store.put(sid, "material_max_layer_count", 8)
        _test_store.put(sid, "material_delta_e00_tolerance", 0.5)

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "__material_archive__",
                    "modeling_mode": "high-fidelity",
                    "target_width_mm": 90.0,
                    "material_max_layer_count": 9,
                },
            },
        }

        async def _late_validate(**kwargs):
            _resolve_session_dynamic_material_settings(
                session_data=kwargs["session_data"],
                request=kwargs["request"],
                material_source="material_archive",
            )
            raise AssertionError("mismatch validation did not run")

        with (
            patch(
                "api.routers.converter.generate._prepare_recipe_override_worker_inputs",
                return_value=(None, None),
            ) as prepare_inputs,
            patch(
                "api.routers.converter.generate._generate_large_format_raster",
                side_effect=_late_validate,
            ) as raster_helper,
        ):
            response = client.post(
                "/api/convert/generate-large-format",
                json=payload,
            )

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == (
            "dynamic_material_preview_mismatch"
        )
        prepare_inputs.assert_not_called()
        raster_helper.assert_not_called()

    def test_large_format_dynamic_mismatch_rejects_before_svg_rasterization(
        self,
    ) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=True,
        )
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(sid, "selected_materials", ["mat-a", "mat-b"])
        _test_store.put(sid, "material_dynamic_layer_count_enabled", True)
        _test_store.put(sid, "material_min_layer_count", 5)
        _test_store.put(sid, "material_max_layer_count", 8)
        _test_store.put(sid, "material_delta_e00_tolerance", 0.5)
        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "__material_archive__",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                    "material_max_layer_count": 9,
                },
            },
        }

        with (
            patch.object(_test_store, "register_temp_file") as register_temp,
            patch.object(_test_store, "put") as store_put,
        ):
            response = client.post(
                "/api/convert/generate-large-format",
                json=payload,
            )

        assert response.status_code == 409
        register_temp.assert_not_called()
        store_put.assert_not_called()

    def test_large_format_maps_typed_dynamic_worker_error(self) -> None:
        from core.material_dynamic_solver import DynamicMaterialCandidateError

        sid, _image_path, _lut_path = _create_raster_large_format_session(
            _test_store
        )
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(sid, "selected_materials", ["mat-a", "mat-b"])
        _test_store.put(sid, "material_layer_count", 10)
        _test_store.put(sid, "material_dynamic_layer_count_enabled", True)
        _test_store.put(sid, "material_min_layer_count", 6)
        _test_store.put(sid, "material_max_layer_count", 8)
        _test_store.put(sid, "material_delta_e00_tolerance", 0.4)
        _test_store.put(sid, "recipe_overrides", [])
        _mock_pool.submit = AsyncMock(
            side_effect=DynamicMaterialCandidateError(
                "no candidate",
                target_srgb=(12, 34, 56),
                layer_count=6,
                phase="exact_search",
            )
        )
        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 90.0,
                "tile_height_mm": 60.0,
                "params": {
                    "lut_name": "__material_archive__",
                    "modeling_mode": "high-fidelity",
                    "target_width_mm": 90.0,
                },
            },
        }

        response = client.post(
            "/api/convert/generate-large-format",
            json=payload,
        )

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == (
            "dynamic_material_no_candidate"
        )

    def test_large_format_svg_width_only_derives_height_and_uses_native_path(self) -> None:
        sid, svg_path, lut_path = _create_svg_session(_test_store, native_tiling_supported=True)

        payload = {
            "session_id": sid,
            "params": {
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                },
            },
        }

        native_response = {
            "status": "ok",
            "message": "native",
            "download_url": "/api/files/native",
            "tile_count": 4,
            "grid_cols": 2,
            "grid_rows": 2,
            "warnings": [],
        }

        with (
            patch("api.routers.converter.generate.Image.open", side_effect=AssertionError("raster path should not open SVG")),
            patch("api.routers.converter.generate._generate_large_format_svg_native", return_value=native_response) as native_helper,
        ):
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 200
        assert response.json()["warnings"] == []
        native_helper.assert_called_once()
        assert native_helper.call_args.kwargs["image_path"] == svg_path
        assert native_helper.call_args.kwargs["lut_path"] == lut_path
        assert native_helper.call_args.kwargs["source_basename"] == "source-artwork"
        assert native_helper.call_args.kwargs["total_width_mm"] == 90.0
        assert native_helper.call_args.kwargs["total_height_mm"] == 60.0

    def test_large_format_svg_height_only_derives_width(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=True)

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 100.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                },
            },
        }

        native_response = {
            "status": "ok",
            "message": "native",
            "download_url": "/api/files/native",
            "tile_count": 6,
            "grid_cols": 3,
            "grid_rows": 2,
            "warnings": [],
        }

        with patch(
            "api.routers.converter.generate._generate_large_format_svg_native",
            return_value=native_response,
        ) as native_helper:
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 200
        assert native_helper.call_args.kwargs["source_basename"] == "source-artwork"
        assert native_helper.call_args.kwargs["total_width_mm"] == 150.0
        assert native_helper.call_args.kwargs["total_height_mm"] == 100.0

    def test_large_format_rejects_missing_both_dimensions(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=True)

        payload = {
            "session_id": sid,
            "params": {
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                },
            },
        }

        response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 422
        assert "width" in response.json()["detail"].lower()
        assert "height" in response.json()["detail"].lower()

    def test_large_format_rejects_dimensions_inconsistent_with_preview_ratio(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=True)

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 90.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 100.0,
                },
            },
        }

        with patch("api.routers.converter.generate._generate_large_format_svg_native") as native_helper:
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 422
        assert "aspect ratio" in response.json()["detail"].lower()
        native_helper.assert_not_called()

    def test_large_format_svg_unsupported_falls_back_to_raster_with_warning(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=False,
            warnings=["Native vector large-format is unavailable because the SVG uses text elements."],
        )

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                },
            },
        }

        fallback_response = {
            "status": "ok",
            "message": "fallback",
            "download_url": "/api/files/raster",
            "tile_count": 4,
            "grid_cols": 2,
            "grid_rows": 2,
            "warnings": [
                "Native vector large-format is unavailable because the SVG uses text elements.",
                "Raster fallback was used for this large-format SVG request.",
            ],
        }

        with (
            patch(
                "api.routers.converter.generate._generate_large_format_svg_native",
            ) as native_helper,
            patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=fallback_response,
            ) as raster_helper,
            patch("api.routers.converter.generate.log.info") as log_info,
        ):
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 200
        body = response.json()
        assert native_helper.call_count == 0
        raster_helper.assert_called_once()
        assert raster_helper.call_args.kwargs["source_basename"] == "source-artwork"
        assert any("raster fallback" in warning.lower() for warning in body["warnings"])
        done_fields = next(
            call.kwargs["extra"]
            for call in log_info.call_args_list
            if call.kwargs.get("extra", {}).get("event")
            == "converter_generate_large_format_done"
        )
        assert done_fields["fallback_reason"] == "unsupported_svg_feature"

    def test_dynamic_large_format_svg_unsupported_native_tiling_returns_422_without_raster_fallback(
        self,
    ) -> None:
        sid, svg_path, lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=False,
            warnings=["Native vector large-format is unavailable because the SVG uses text elements."],
        )
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(sid, "selected_materials", ["brand/base", "brand/red"])
        _test_store.put(sid, "material_dynamic_layer_count_enabled", True)
        _test_store.put(sid, "material_min_layer_count", 5)
        _test_store.put(sid, "material_max_layer_count", 7)
        _test_store.put(sid, "material_delta_e00_tolerance", 0.5)

        try:
            with (
                patch("api.routers.converter.generate._generate_large_format_svg_native") as native_helper,
                patch("api.routers.converter.generate._generate_large_format_raster") as raster_helper,
            ):
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="vector",
                        use_cached_matched_rgb=False,
                    ),
                )

            assert response.status_code == 422, response.text
            assert "native svg large-format" in response.json()["detail"].lower()
            native_helper.assert_not_called()
            raster_helper.assert_not_called()
        finally:
            _test_store.close(sid)
            for path in (svg_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_dynamic_large_format_svg_native_failure_returns_422_without_raster_fallback(
        self,
    ) -> None:
        sid, svg_path, lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=True,
        )
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(sid, "selected_materials", ["brand/base", "brand/red"])
        _test_store.put(sid, "material_dynamic_layer_count_enabled", True)
        _test_store.put(sid, "material_min_layer_count", 5)
        _test_store.put(sid, "material_max_layer_count", 7)
        _test_store.put(sid, "material_delta_e00_tolerance", 0.5)

        try:
            with (
                patch(
                    "api.routers.converter.generate._generate_large_format_svg_native",
                    side_effect=HTTPException(
                        status_code=500,
                        detail=LARGE_FORMAT_GENERATION_FAILED_DETAIL,
                    ),
                ) as native_helper,
                patch("api.routers.converter.generate._generate_large_format_raster") as raster_helper,
            ):
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="vector",
                        use_cached_matched_rgb=False,
                    ),
                )

            assert response.status_code == 422, response.text
            assert "native vector generation could not complete" in response.json()["detail"].lower()
            native_helper.assert_called_once()
            raster_helper.assert_not_called()
        finally:
            _test_store.close(sid)
            for path in (svg_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_route_passes_recipe_override_artifacts_to_raster_helper(self) -> None:
        sid, image_path, lut_path = _create_raster_large_format_session(_test_store)

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "high-fidelity",
                    "target_width_mm": 90.0,
                    "recipe_overrides": [
                        {
                            "region_id": "region-1",
                            "recipe": [1, 1, 1, 1, 1],
                            "layer_order": "Top2Bottom",
                        }
                    ],
                },
            },
        }

        raster_response = {
            "status": "ok",
            "message": "raster",
            "download_url": "/api/files/raster",
            "tile_count": 4,
            "grid_cols": 2,
            "grid_rows": 2,
            "warnings": [],
        }

        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=raster_response,
            ) as raster_helper:
                response = client.post("/api/convert/generate-large-format", json=payload)

            assert response.status_code == 200
            raster_helper.assert_called_once()
            kwargs = raster_helper.call_args.kwargs
            assert kwargs["image_path"] == image_path
            assert kwargs["lut_path"] == lut_path
            assert kwargs["recipe_overrides"] == [
                {
                    "region_id": "region-1",
                    "recipe": [1, 1, 1, 1, 1],
                    "layer_order": "Top2Bottom",
                }
            ]
            assert kwargs["material_matrix_path"] is not None
            assert os.path.exists(kwargs["material_matrix_path"])
            assert kwargs["recipe_override_masks_path"] is not None
            assert os.path.exists(kwargs["recipe_override_masks_path"])
        finally:
            _test_store.clear_all()

    def test_large_format_recipe_only_route_marks_final_matrix_authoritative(
        self,
    ) -> None:
        """Recipe-only generation must not depend on the cached-trio flag."""

        sid, image_path, lut_path = _create_raster_large_format_session(_test_store)
        _test_store.put(
            sid,
            "replacement_regions",
            [
                {
                    "quantized_hex": "#ff0000",
                    "matched_hex": "#ff0000",
                    "replacement_hex": "#00ff00",
                }
            ],
        )
        payload = _large_format_payload(
            sid,
            modeling_mode="high-fidelity",
            use_cached_matched_rgb=False,
            target_width_mm=90.0,
            target_height_mm=60.0,
        )

        try:
            with patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=_large_format_success_response("raster"),
            ) as raster_helper:
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=payload,
                )

            assert response.status_code == 200, response.text
            kwargs = raster_helper.call_args.kwargs
            assert kwargs["matched_rgb_path"] is None
            assert kwargs["mask_solid_path"] is None
            assert kwargs["material_matrix_path"] is not None
            assert os.path.exists(kwargs["material_matrix_path"])
            assert kwargs["final_material_matrix_is_authoritative"] is True
        finally:
            _test_store.close(sid)
            for path in (image_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    @pytest.mark.parametrize(
        (
            "cached_analysis_is_final",
            "final_material_matrix_is_authoritative",
        ),
        [(False, False), (False, True), (True, True)],
        ids=("ordinary", "recipe-only", "complete-trio"),
    )
    def test_large_format_shared_params_separate_rgb_and_matrix_finality(
        self,
        cached_analysis_is_final: bool,
        final_material_matrix_is_authoritative: bool,
    ) -> None:
        """Final recipes keep global RGB mapping unless the full trio is final."""

        assert "final_material_matrix_is_authoritative" in inspect.signature(
            _resolve_large_format_shared_params
        ).parameters
        assert "final_material_matrix_authority_mask_path" in inspect.signature(
            _resolve_large_format_shared_params
        ).parameters
        replacement_regions = [
            {
                "quantized_hex": "#ff0000",
                "matched_hex": "#ff0000",
                "replacement_hex": "#00ff00",
            }
        ]
        params = _resolve_large_format_shared_params(
            {"material_source": "lut", "replacement_regions": replacement_regions},
            LargeFormatConvertGenerateRequest(
                lut_name="test_lut",
                modeling_mode=ModelingMode.HIGH_FIDELITY,
            ),
            None,
            material_matrix_path=(
                "final-material.npy"
                if final_material_matrix_is_authoritative
                else None
            ),
            cached_analysis_is_final=cached_analysis_is_final,
            final_material_matrix_is_authoritative=(
                final_material_matrix_is_authoritative
            ),
            final_material_matrix_authority_mask_path=(
                "recipe-authority-mask.npy"
                if final_material_matrix_is_authoritative
                and not cached_analysis_is_final
                else None
            ),
        )

        assert params["final_material_matrix_is_authoritative"] is (
            final_material_matrix_is_authoritative
        )
        assert params["replacement_regions"] == (
            None if cached_analysis_is_final else replacement_regions
        )
        assert params["final_material_matrix_authority_mask_path"] == (
            "recipe-authority-mask.npy"
            if final_material_matrix_is_authoritative
            and not cached_analysis_is_final
            else None
        )

    def test_large_format_artifact_cache_uses_metadata_without_hydrating(
        self,
        tmp_path,
    ) -> None:
        _test_store.clear_all()
        image_path = tmp_path / "input.png"
        lut_path = tmp_path / "source.npy"
        Image.fromarray(np.zeros((8, 12, 3), dtype=np.uint8)).save(image_path)
        lut_path.write_bytes(b"lut")

        sid = _test_store.create()
        cache_ref = externalize_preview_cache(
            sid,
            _test_store,
            {
                "target_w": 12,
                "target_h": 8,
                "target_width_mm": 60.0,
                "matched_rgb": np.zeros((8, 12, 3), dtype=np.uint8),
                "mask_solid": np.ones((8, 12), dtype=bool),
                "material_matrix": np.zeros((8, 12, 5), dtype=np.uint8),
            },
            root_dir=tmp_path,
        )
        _test_store.put(sid, "preview_cache", cache_ref)
        _test_store.put(sid, "image_path", str(image_path))
        _test_store.put(sid, "lut_path", str(lut_path))
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "free_color_set", set())

        raster_response = {
            "status": "ok",
            "message": "raster",
            "download_url": "/api/files/raster",
            "tile_count": 1,
            "grid_cols": 1,
            "grid_rows": 1,
            "warnings": [],
        }

        with (
            patch(
                "api.routers.converter.common.hydrate_preview_cache",
                side_effect=AssertionError("large-format must not fully hydrate artifact cache"),
            ),
            patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=raster_response,
            ) as raster_helper,
        ):
            response = client.post(
                "/api/convert/generate-large-format",
                json={
                    "session_id": sid,
                    "params": {
                        "target_height_mm": 80.0,
                        "tile_width_mm": 40.0,
                        "tile_height_mm": 40.0,
                        "params": {
                            "lut_name": "test_lut",
                            "modeling_mode": "high-fidelity",
                            "target_width_mm": 120.0,
                        },
                    },
                },
            )

        assert response.status_code == 200, response.text
        raster_helper.assert_called_once()
        assert raster_helper.call_args.kwargs["material_matrix_path"] is None

    def test_large_format_artifact_cache_rejects_relief_height_below_manifest_depth(
        self,
        tmp_path,
    ) -> None:
        _test_store.clear_all()
        image_path = tmp_path / "input.png"
        Image.fromarray(np.zeros((8, 12, 3), dtype=np.uint8)).save(image_path)

        sid = _test_store.create()
        cache_ref = externalize_preview_cache(
            sid,
            _test_store,
            {
                "target_w": 12,
                "target_h": 8,
                "target_width_mm": 60.0,
                "matched_rgb": np.zeros((8, 12, 3), dtype=np.uint8),
                "mask_solid": np.ones((8, 12), dtype=bool),
                "material_matrix": np.zeros((8, 12, 10), dtype=np.uint8),
            },
            root_dir=tmp_path,
        )
        _test_store.put(sid, "preview_cache", cache_ref)
        _test_store.put(sid, "image_path", str(image_path))
        _test_store.put(sid, "lut_path", "__material_archive__")
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(sid, "selected_materials", ["mat-a", "mat-b"])
        _test_store.put(sid, "material_layer_count", 5)
        _test_store.put(sid, "material_layer_height_mm", 0.08)
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "free_color_set", set())

        with patch("api.routers.converter.generate._generate_large_format_raster") as raster_helper:
            response = client.post(
                "/api/convert/generate-large-format",
                json={
                    "session_id": sid,
                    "params": {
                        "target_height_mm": 80.0,
                        "tile_width_mm": 40.0,
                        "tile_height_mm": 40.0,
                        "params": {
                            "lut_name": "__material_archive__",
                            "modeling_mode": "high-fidelity",
                            "target_width_mm": 120.0,
                            "enable_relief": True,
                            "height_mode": "color",
                            "color_height_map": {"#111111": 0.6},
                            "heightmap_max_height": 0.6,
                        },
                    },
                },
            )

        assert response.status_code == 422, response.text
        assert "0.80 mm" in response.json()["detail"]
        raster_helper.assert_not_called()

    def test_large_format_rejects_relief_height_below_override_depth(
        self,
        tmp_path,
    ) -> None:
        _test_store.clear_all()
        image_path = tmp_path / "input.png"
        Image.fromarray(np.zeros((8, 12, 3), dtype=np.uint8)).save(image_path)

        sid = _test_store.create()
        cache_ref = externalize_preview_cache(
            sid,
            _test_store,
            {
                "target_w": 12,
                "target_h": 8,
                "target_width_mm": 60.0,
                "matched_rgb": np.zeros((8, 12, 3), dtype=np.uint8),
                "mask_solid": np.ones((8, 12), dtype=bool),
                "material_matrix": np.zeros((8, 12, 5), dtype=np.uint8),
            },
            root_dir=tmp_path,
        )
        _test_store.put(sid, "preview_cache", cache_ref)
        _test_store.put(sid, "image_path", str(image_path))
        _test_store.put(sid, "lut_path", "__material_archive__")
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(sid, "selected_materials", ["mat-a", "mat-b"])
        _test_store.put(sid, "material_layer_count", 5)
        _test_store.put(sid, "material_layer_height_mm", 0.08)
        _test_store.put(sid, "replacement_regions", [])
        _test_store.put(sid, "free_color_set", set())
        _test_store.put(sid, "selected_region_masks", {"region-1": np.ones((8, 12), dtype=bool)})

        with patch("api.routers.converter.generate._generate_large_format_raster") as raster_helper:
            response = client.post(
                "/api/convert/generate-large-format",
                json={
                    "session_id": sid,
                    "params": {
                        "target_height_mm": 80.0,
                        "tile_width_mm": 40.0,
                        "tile_height_mm": 40.0,
                        "params": {
                            "lut_name": "__material_archive__",
                            "modeling_mode": "high-fidelity",
                            "target_width_mm": 120.0,
                            "color_layers": 10,
                            "enable_relief": True,
                            "height_mode": "color",
                            "color_height_map": {"#111111": 0.6},
                            "heightmap_max_height": 0.6,
                            "recipe_overrides": [
                                {
                                    "region_id": "region-1",
                                    "recipe": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
                                    "layer_order": "Top2Bottom",
                                },
                            ],
                        },
                    },
                },
            )

        assert response.status_code == 422, response.text
        assert "0.80 mm" in response.json()["detail"]
        raster_helper.assert_not_called()

    def test_large_format_heightmap_mode_rejects_missing_session_heightmap(self) -> None:
        sid, image_path, lut_path = _create_raster_large_format_session(_test_store)
        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "high-fidelity",
                    "target_width_mm": 90.0,
                    "enable_relief": True,
                    "height_mode": "heightmap",
                    "color_height_map": {"#ff0000": 2.88},
                    "heightmap_max_height": 2.88,
                },
            },
        }

        try:
            with patch("api.routers.converter.generate._generate_large_format_raster") as raster_helper:
                response = client.post("/api/convert/generate-large-format", json=payload)

            assert response.status_code == 409
            assert "heightmap" in response.json()["detail"].lower()
            raster_helper.assert_not_called()
        finally:
            _test_store.clear_all()
            for path in (image_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_svg_with_recipe_overrides_uses_native_path_when_supported(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=True)
        session_data = _test_store.get(sid)
        assert session_data is not None
        session_data["preview_cache"]["material_matrix"] = np.zeros((4, 4, 5), dtype=np.uint8)
        session_data["preview_cache"]["lut_metadata"] = SimpleNamespace(
            layer_order="Top2Bottom",
            base_channel_idx=2,
        )
        session_data["selected_region_masks"] = {"region-1": np.ones((4, 4), dtype=bool)}

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                    "recipe_overrides": [
                        {
                            "region_id": "region-1",
                            "recipe": [1, 1, 1, 1, 1],
                            "layer_order": "Top2Bottom",
                        }
                    ],
                },
            },
        }

        native_response = {
            "status": "ok",
            "message": "native",
            "download_url": "/api/files/native",
            "tile_count": 4,
            "grid_cols": 2,
            "grid_rows": 2,
            "warnings": [],
        }

        with (
            patch(
                "api.routers.converter.generate._generate_large_format_svg_native",
                return_value=native_response,
            ) as native_helper,
            patch(
                "api.routers.converter.generate._generate_large_format_raster",
            ) as raster_helper,
        ):
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 200
        native_helper.assert_called_once()
        raster_helper.assert_not_called()
        kwargs = native_helper.call_args.kwargs
        assert kwargs["recipe_overrides"] == [
            {
                "region_id": "region-1",
                "recipe": [1, 1, 1, 1, 1],
                "layer_order": "Top2Bottom",
            }
        ]
        assert kwargs["recipe_override_masks_path"] is not None
        assert os.path.exists(kwargs["recipe_override_masks_path"])
        assert kwargs["material_matrix_path"] is not None
        assert os.path.exists(kwargs["material_matrix_path"])
        assert kwargs["base_channel_idx"] == 2
        assert response.json()["warnings"] == []

    def test_large_format_svg_material_archive_uses_native_path_when_supported(self) -> None:
        sid, svg_path, lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=True,
        )
        _test_store.put(sid, "material_source", "material_archive")
        _test_store.put(
            sid,
            "selected_materials",
            ["brand/red", "brand/blue", "brand/white"],
        )
        _test_store.put(sid, "material_layer_count", 7)
        _test_store.put(sid, "material_layer_height_mm", 0.12)
        _test_store.put(sid, "material_grid_resolution", 64)
        _test_store.put(sid, "material_backing_material_index", 2)

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "__material_archive__",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                    "color_layers": 7,
                    "layer_height_mm": 0.12,
                    "material_backing_material_index": 2,
                },
            },
        }

        with (
            patch(
                "api.routers.converter.generate._generate_large_format_svg_native",
                return_value=_large_format_success_response("native-archive"),
            ) as native_helper,
            patch(
                "api.routers.converter.generate._generate_large_format_raster",
            ) as raster_helper,
        ):
            response = client.post("/api/convert/generate-large-format", json=payload)

        try:
            assert response.status_code == 200, response.text
            native_helper.assert_called_once()
            raster_helper.assert_not_called()
            kwargs = native_helper.call_args.kwargs
            assert kwargs["lut_path"] == "__material_archive__"
            assert kwargs["session_data"]["selected_materials"] == [
                "brand/red",
                "brand/blue",
                "brand/white",
            ]
            assert kwargs["session_data"]["material_backing_material_index"] == 2
            assert response.json()["warnings"] == []
        finally:
            _test_store.close(sid)
            for path in (svg_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    @pytest.mark.parametrize(
        ("native_error", "expected_error_type"),
        [
            (
                HTTPException(
                    status_code=500,
                    detail=LARGE_FORMAT_GENERATION_FAILED_DETAIL,
                ),
                "HTTPException",
            ),
            (AssertionError("native tile invariant failed"), "AssertionError"),
        ],
    )
    def test_large_format_svg_native_failure_falls_back_to_raster(
        self,
        native_error: Exception,
        expected_error_type: str,
    ) -> None:
        sid, svg_path, lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=True,
        )

        async def _fallback_response(**kwargs: object) -> dict[str, object]:
            return {
                **_large_format_success_response("raster-fallback"),
                "warnings": list(kwargs["warnings"]),
            }

        try:
            with (
                patch(
                    "api.routers.converter.generate._generate_large_format_svg_native",
                    side_effect=native_error,
                ) as native_helper,
                patch(
                    "api.routers.converter.generate._generate_large_format_raster",
                    side_effect=_fallback_response,
                ) as raster_helper,
                patch("api.routers.converter.generate.log.warning") as log_warning,
            ):
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="vector",
                        use_cached_matched_rgb=False,
                    ),
                )

            assert response.status_code == 200, response.text
            native_helper.assert_called_once()
            raster_helper.assert_called_once()
            warnings = response.json()["warnings"]
            assert any("native vector generation failed" in item.lower() for item in warnings)
            assert any("raster fallback" in item.lower() for item in warnings)
            fallback_fields = next(
                call.kwargs["extra"]
                for call in log_warning.call_args_list
                if call.kwargs.get("extra", {}).get("event")
                == "converter_large_format_svg_fallback"
            )
            assert fallback_fields["fallback_reason"] == "native_vector_failure"
            assert fallback_fields["error_type"] == expected_error_type
        finally:
            _test_store.close(sid)
            for path in (svg_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)



    def test_large_format_svg_broken_worker_never_starts_raster_fallback(
        self,
    ) -> None:
        sid, svg_path, lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=True,
        )

        try:
            with (
                patch(
                    "api.routers.converter.generate._generate_large_format_svg_native",
                    side_effect=BrokenProcessPool("native worker was killed"),
                ) as native_helper,
                patch(
                    "api.routers.converter.generate._generate_large_format_raster",
                ) as raster_helper,
            ):
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="vector",
                        use_cached_matched_rgb=False,
                    ),
                )

            assert response.status_code == 503
            native_helper.assert_called_once()
            raster_helper.assert_not_called()
        finally:
            _test_store.close(sid)
            for path in (svg_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_svg_fallback_failure_returns_bounded_error(self) -> None:
        sid, svg_path, lut_path = _create_svg_session(
            _test_store,
            native_tiling_supported=True,
        )
        expected_error_message = "fallback archive write failed"

        try:
            with (
                patch(
                    "api.routers.converter.generate._generate_large_format_svg_native",
                    side_effect=AssertionError("native tile invariant failed"),
                ) as native_helper,
                patch(
                    "api.routers.converter.generate._generate_large_format_raster",
                    side_effect=OSError("fallback archive write failed"),
                ) as raster_helper,
                patch(
                    "api.routers.converter.generate._log_large_format_failure",
                ) as failure_log,
            ):
                response = client.post(
                    "/api/convert/generate-large-format",
                    json=_large_format_payload(
                        sid,
                        modeling_mode="vector",
                        use_cached_matched_rgb=False,
                    ),
                )

            assert response.status_code == 500
            assert response.json()["detail"] == LARGE_FORMAT_GENERATION_FAILED_DETAIL
            native_helper.assert_called_once()
            raster_helper.assert_called_once()
            failure_log.assert_called_once_with(
                session_id=sid,
                failure_kind="raster_fallback_failed",
                error_type="OSError",
                error_message=expected_error_message,
            )
        finally:
            _test_store.close(sid)
            for path in (svg_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_reinspects_unmarked_svg_policy_before_using_native_path(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=True)
        session_data = _test_store.get(sid)
        assert session_data is not None
        session_data["svg_large_format_policy"] = {
            "native_tiling_supported": True,
            "warnings": [],
            "unsupported_features": [],
        }

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                },
            },
        }

        fallback_response = {
            "status": "ok",
            "message": "fallback",
            "download_url": "/api/files/raster",
            "tile_count": 4,
            "grid_cols": 2,
            "grid_rows": 2,
            "warnings": [
                "Native vector large-format is unavailable for this SVG; large-format generation will fall back to raster tiling. Unsupported features: text.",
                "Raster fallback was used for this large-format SVG request.",
            ],
        }

        with (
            patch(
                "api.routers.converter.generate.inspect_svg_large_format_support",
                return_value={
                    "native_tiling_supported": False,
                    "warnings": [
                        "Native vector large-format is unavailable for this SVG; large-format generation will fall back to raster tiling. Unsupported features: text."
                    ],
                    "unsupported_features": ["text"],
                },
            ) as inspect_helper,
            patch(
                "api.routers.converter.generate._generate_large_format_svg_native",
            ) as native_helper,
            patch(
                "api.routers.converter.generate._generate_large_format_raster",
                return_value=fallback_response,
            ) as raster_helper,
        ):
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 200
        inspect_helper.assert_called_once()
        native_helper.assert_not_called()
        raster_helper.assert_called_once()
        assert raster_helper.call_args.kwargs["source_basename"] == "source-artwork"
        updated_policy = _test_store.get(sid)["svg_large_format_policy"]
        assert updated_policy["inspection_source"] == "generate-large-format"
        assert updated_policy["native_tiling_supported"] is False

    def test_large_format_reuses_preview_svg_policy_without_reinspection(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=True)

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                },
            },
        }

        native_response = {
            "status": "ok",
            "message": "native",
            "download_url": "/api/files/native",
            "tile_count": 4,
            "grid_cols": 2,
            "grid_rows": 2,
            "warnings": [],
        }

        with (
            patch(
                "api.routers.converter.generate.inspect_svg_large_format_support",
                side_effect=AssertionError("stored preview policy should be reused"),
            ),
            patch(
                "api.routers.converter.generate._generate_large_format_svg_native",
                return_value=native_response,
            ) as native_helper,
        ):
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 200
        native_helper.assert_called_once()


    def test_large_format_svg_native_worker_error_returns_500(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=True)
        private_path = "/Users/min/private/source.svg"
        raw_error_message = f"cannot read {private_path}: Permission denied"
        log_calls: list[tuple[str, str, dict[str, object]]] = []
        _mock_pool.submit = AsyncMock(side_effect=ValueError(raw_error_message))

        def _capturing_safe_log(level: str, event: str, **fields: object) -> None:
            log_calls.append((level, event, fields))

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                },
            },
        }

        with patch(
            "api.routers.converter.generate._safe_log",
            side_effect=_capturing_safe_log,
        ):
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 500
        assert response.json()["detail"] == (
            "Large-format generation failed. Try again or check the server log for details."
        )
        assert private_path not in response.text
        assert "Permission denied" not in response.text
        assert "Large-format SVG generation failed" not in response.text
        failure_logs = [
            (level, fields)
            for level, event, fields in log_calls
            if event == "converter_large_format_failed"
        ]
        assert len(failure_logs) == 2
        failures_by_kind = {
            str(fields["failure_kind"]): (level, fields)
            for level, fields in failure_logs
        }
        level, fields = failures_by_kind["svg_native_worker"]
        assert level == "error"
        assert fields["session_id"] == sid
        assert fields["error_type"] == "ValueError"
        assert private_path in str(fields["error_message"])
        assert "Permission denied" in str(fields["error_message"])
        fallback_level, fallback_fields = failures_by_kind[
            "raster_fallback_failed"
        ]
        assert fallback_level == "error"
        assert fallback_fields["session_id"] == sid
        assert fallback_fields["error_type"] == "HTTPException"
        assert fallback_fields["error_message"] == (
            LARGE_FORMAT_GENERATION_FAILED_DETAIL
        )

    def test_large_format_raster_helper_writes_sanitized_zip_entry_names(self) -> None:
        fd_img, image_path = tempfile.mkstemp(suffix=".png")
        os.close(fd_img)
        fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
        os.close(fd_lut)
        fd_3mf, threemf_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_3mf)

        Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8)).save(image_path)
        with open(lut_path, "wb") as lut_file:
            lut_file.write(b"lut")
        with open(threemf_path, "wb") as threemf_file:
            threemf_file.write(b"3mf")

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        sid = store.create()
        mock_pool = MagicMock(spec=WorkerPoolManager)
        mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": threemf_path,
                "status_msg": "ok",
            }
        )
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )

        try:
            result = asyncio.run(
                _generate_large_format_raster(
                    image_path=image_path,
                    lut_path=lut_path,
                    source_basename=" bad:name* ",
                    recipe_overrides=None,
                    recipe_override_masks_path=None,
                    material_matrix_path=None,
                    total_width_mm=40.0,
                    total_height_mm=40.0,
                    tile_width_mm=40.0,
                    tile_height_mm=40.0,
                    request=request,
                    session_data={},
                    sid=sid,
                    store=store,
                    registry=registry,
                    pool=mock_pool,
                )
            )

            download_id = result["download_url"].rsplit("/", 1)[-1]
            zip_path, _filename = registry.resolve(download_id)
            with zipfile.ZipFile(zip_path, "r") as archive:
                assert archive.namelist() == ["bad_name_R1C1.3mf"]
        finally:
            store.clear_all()
            for path in (image_path, lut_path, threemf_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_material_archive_raster_params_stay_generate_compatible(self) -> None:
        fd_img, image_path = tempfile.mkstemp(suffix=".png")
        os.close(fd_img)
        fd_3mf, threemf_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_3mf)

        Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8)).save(image_path)
        with open(threemf_path, "wb") as threemf_file:
            threemf_file.write(b"3mf")

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        sid = store.create()
        mock_pool = MagicMock(spec=WorkerPoolManager)
        captured_params: dict = {}

        async def _mock_submit(_fn, _tile_path, _lut_path, tile_params):
            if "backing_color_id" in tile_params:
                raise TypeError("generate_final_model() got an unexpected keyword argument 'backing_color_id'")
            captured_params.update(tile_params)
            return {
                "threemf_path": threemf_path,
                "status_msg": "ok",
            }

        mock_pool.submit = AsyncMock(side_effect=_mock_submit)
        request = LargeFormatConvertGenerateRequest(
            lut_name="__material_archive__",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )

        try:
            result = asyncio.run(
                _generate_large_format_raster(
                    image_path=image_path,
                    lut_path="__material_archive__",
                    source_basename="poster",
                    recipe_overrides=None,
                    recipe_override_masks_path=None,
                    material_matrix_path=None,
                    total_width_mm=40.0,
                    total_height_mm=40.0,
                    tile_width_mm=40.0,
                    tile_height_mm=40.0,
                    request=request,
                    session_data={
                        "material_source": "material_archive",
                        "selected_materials": ["mat-a", "mat-b"],
                        "material_layer_count": 5,
                        "material_layer_height_mm": 0.08,
                        "material_grid_resolution": 64,
                        "material_backing_material_index": 1,
                    },
                    sid=sid,
                    store=store,
                    registry=registry,
                    pool=mock_pool,
                )
            )

            assert result["status"] == "ok"
            assert captured_params["material_source"] == "material_archive"
            assert captured_params["selected_materials"] == ["mat-a", "mat-b"]
            assert captured_params["material_backing_material_index"] == 1
            assert "backing_color_id" not in captured_params
        finally:
            store.clear_all()
            for path in (image_path, threemf_path):
                if os.path.exists(path):
                    os.unlink(path)

    @pytest.mark.parametrize(
        (
            "source_size",
            "cache_size",
            "total_width_mm",
            "tile_width_mm",
        ),
        [
            ((20, 20), (2, 2), 10.0, 1.0),
            ((100, 100), (100, 100), 10.000001, 10.0),
        ],
        ids=("cache-grid-too-small", "rounded-tail-collapses"),
    )
    @pytest.mark.asyncio
    async def test_large_format_cached_raster_rejects_collapsed_tile_bounds_before_submit(
        self,
        tmp_path,
        source_size: tuple[int, int],
        cache_size: tuple[int, int],
        total_width_mm: float,
        tile_width_mm: float,
    ) -> None:
        """Every physical tile must occupy source and cache pixels."""

        source_width, source_height = source_size
        cache_width, cache_height = cache_size
        image_path = tmp_path / "source.png"
        lut_path = tmp_path / "lut.npy"
        matched_path = tmp_path / "matched.npy"
        mask_path = tmp_path / "mask.npy"
        material_path = tmp_path / "material.npy"
        Image.fromarray(
            np.zeros((source_height, source_width, 3), dtype=np.uint8)
        ).save(image_path)
        lut_path.write_bytes(b"lut")
        np.save(
            matched_path,
            np.zeros((cache_height, cache_width, 3), dtype=np.uint8),
        )
        np.save(mask_path, np.ones((cache_height, cache_width), dtype=bool))
        np.save(
            material_path,
            np.zeros((cache_height, cache_width, 5), dtype=np.int16),
        )

        worker_output = tmp_path / "unexpected-tile.3mf"
        worker_output.write_bytes(b"3mf")
        mock_pool = SimpleNamespace(
            submit=AsyncMock(
                return_value={
                    "threemf_path": str(worker_output),
                    "status_msg": "ok",
                }
            )
        )
        registry = MagicMock(spec=FileRegistry)
        registry.register_path.return_value = "unexpected-download"
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )
        created_temp_paths: list[str] = []
        original_mkstemp = tempfile.mkstemp

        def _record_mkstemp(*args: object, **kwargs: object):
            fd, path = original_mkstemp(*args, **kwargs)
            created_temp_paths.append(path)
            return fd, path

        try:
            with (
                patch(
                    "api.routers.converter.generate.tempfile.mkstemp",
                    side_effect=_record_mkstemp,
                ),
                pytest.raises(HTTPException) as exc_info,
            ):
                await _generate_large_format_raster(
                    image_path=str(image_path),
                    lut_path=str(lut_path),
                    source_basename="poster",
                    recipe_overrides=None,
                    recipe_override_masks_path=None,
                    matched_rgb_path=str(matched_path),
                    mask_solid_path=str(mask_path),
                    material_matrix_path=str(material_path),
                    total_width_mm=total_width_mm,
                    total_height_mm=10.0,
                    tile_width_mm=tile_width_mm,
                    tile_height_mm=10.0,
                    request=request,
                    session_data={},
                    sid="collapsed-grid-session",
                    store=SessionStore(ttl=1800),
                    registry=registry,
                    pool=mock_pool,
                )

            assert exc_info.value.status_code == 409
            assert (
                exc_info.value.detail
                == LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL
            )
            mock_pool.submit.assert_not_called()
            registry.register_path.assert_not_called()
            assert created_temp_paths == []
            assert matched_path.exists()
            assert mask_path.exists()
            assert material_path.exists()
        finally:
            for path in created_temp_paths:
                if os.path.exists(path):
                    os.unlink(path)

    @pytest.mark.asyncio
    async def test_large_format_cached_raster_keeps_nonempty_259_by_400_grid(
        self,
        tmp_path,
    ) -> None:
        """A normal 259×400 grid tiled at 210 mm must keep all four tiles."""

        image_path = tmp_path / "source.jpg"
        lut_path = tmp_path / "lut.npy"
        matched_path = tmp_path / "matched.npy"
        mask_path = tmp_path / "mask.npy"
        material_path = tmp_path / "material.npy"
        Image.fromarray(np.zeros((400, 259, 3), dtype=np.uint8)).save(image_path)
        lut_path.write_bytes(b"lut")
        np.save(matched_path, np.zeros((400, 259, 3), dtype=np.uint8))
        np.save(mask_path, np.ones((400, 259), dtype=bool))
        np.save(material_path, np.zeros((400, 259, 5), dtype=np.int16))

        captured_shapes: list[
            tuple[tuple[int, int], tuple[int, int]]
        ] = []

        async def _submit(
            _fn,
            tile_path,
            _lut_path,
            tile_params,
        ):
            with Image.open(tile_path) as tile_image:
                source_shape = (tile_image.height, tile_image.width)
            cache_shape = np.load(tile_params["material_matrix_path"]).shape[:2]
            captured_shapes.append((source_shape, cache_shape))
            output_path = tmp_path / f"tile-{len(captured_shapes)}.3mf"
            output_path.write_bytes(b"3mf")
            return {"threemf_path": str(output_path), "status_msg": "ok"}

        registry = FileRegistry()
        mock_pool = SimpleNamespace(submit=AsyncMock(side_effect=_submit))
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.VECTOR,
        )
        download_id: str | None = None
        try:
            result = await _generate_large_format_raster(
                image_path=str(image_path),
                lut_path=str(lut_path),
                source_basename="poster",
                recipe_overrides=None,
                recipe_override_masks_path=None,
                matched_rgb_path=str(matched_path),
                mask_solid_path=str(mask_path),
                material_matrix_path=str(material_path),
                total_width_mm=259.0,
                total_height_mm=400.0,
                tile_width_mm=210.0,
                tile_height_mm=210.0,
                request=request,
                session_data={},
                sid="normal-grid-session",
                store=SessionStore(ttl=1800),
                registry=registry,
                pool=mock_pool,
            )

            download_id = result["download_url"].rsplit("/", 1)[-1]
            expected_shapes = [
                ((210, 210), (210, 210)),
                ((210, 49), (210, 49)),
                ((190, 210), (190, 210)),
                ((190, 49), (190, 49)),
            ]
            assert result["tile_count"] == 4
            assert result["grid_cols"] == 2
            assert result["grid_rows"] == 2
            assert captured_shapes == expected_shapes
            assert mock_pool.submit.call_count == 4
        finally:
            if download_id is not None:
                registry.cleanup_file(download_id)

    @pytest.mark.asyncio
    async def test_large_format_cached_raster_crops_spatial_arrays_by_physical_grid(
        self,
        tmp_path,
    ) -> None:
        image_path = tmp_path / "source.png"
        lut_path = tmp_path / "lut.npy"
        Image.fromarray(np.zeros((13, 19, 3), dtype=np.uint8)).save(image_path)
        lut_path.write_bytes(b"lut")

        yy, xx = np.indices((8, 10))
        matched_rgb = np.stack(
            [yy.astype(np.uint8), xx.astype(np.uint8), (yy * 10 + xx).astype(np.uint8)],
            axis=-1,
        )
        mask_solid = ((yy + xx) % 2 == 0)
        material_matrix = np.stack(
            [yy * 100 + xx, yy * 100 + xx + 1000, yy * 100 + xx + 2000],
            axis=-1,
        ).astype(np.int16)
        matched_path = tmp_path / "matched.npy"
        mask_path = tmp_path / "mask.npy"
        material_path = tmp_path / "material.npy"
        np.save(matched_path, matched_rgb)
        np.save(mask_path, mask_solid)
        np.save(material_path, material_matrix)

        captured: list[dict[str, object]] = []
        route_local_paths: list[str] = []

        async def _submit(_fn, tile_path, _lut_path, tile_params):
            assert os.path.exists(tile_path)
            paths = [
                tile_params["matched_rgb_path"],
                tile_params["mask_solid_path"],
                tile_params["material_matrix_path"],
            ]
            assert all(path and os.path.exists(path) for path in paths)
            route_local_paths.extend([tile_path, *paths])
            captured.append(
                {
                    "matched": np.load(paths[0]),
                    "mask": np.load(paths[1]),
                    "material": np.load(paths[2]),
                    "reuse": tile_params["reuse_preview_analysis"],
                    "recipe_masks": tile_params["recipe_override_masks_path"],
                }
            )
            tile_output = tmp_path / f"tile-{len(captured)}.3mf"
            tile_output.write_bytes(b"3mf")
            return {"threemf_path": str(tile_output), "status_msg": "ok"}

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        sid = store.create()
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )
        download_id: str | None = None
        try:
            result = await _generate_large_format_raster(
                image_path=str(image_path),
                lut_path=str(lut_path),
                source_basename="poster",
                recipe_overrides=None,
                recipe_override_masks_path=None,
                matched_rgb_path=str(matched_path),
                mask_solid_path=str(mask_path),
                material_matrix_path=str(material_path),
                total_width_mm=100.0,
                total_height_mm=80.0,
                tile_width_mm=50.0,
                tile_height_mm=40.0,
                request=request,
                session_data={},
                sid=sid,
                store=store,
                registry=registry,
                pool=SimpleNamespace(submit=AsyncMock(side_effect=_submit)),
            )

            download_id = result["download_url"].rsplit("/", 1)[-1]
            expected_bounds = [
                (slice(0, 4), slice(0, 5)),
                (slice(0, 4), slice(5, 10)),
                (slice(4, 8), slice(0, 5)),
                (slice(4, 8), slice(5, 10)),
            ]
            assert len(captured) == 4
            for tile, (ys, xs) in zip(captured, expected_bounds):
                assert tile["matched"].shape[:2] == tile["mask"].shape
                assert tile["matched"].shape[:2] == tile["material"].shape[:2]
                assert np.array_equal(tile["matched"], matched_rgb[ys, xs])
                assert np.array_equal(tile["mask"], mask_solid[ys, xs])
                assert np.array_equal(tile["material"], material_matrix[ys, xs])
                assert tile["reuse"] is True
                assert tile["recipe_masks"] is None
            assert route_local_paths
            assert all(not os.path.exists(path) for path in route_local_paths)
            assert matched_path.exists()
            assert mask_path.exists()
            assert material_path.exists()
        finally:
            if download_id is not None:
                registry.cleanup_file(download_id)
            store.clear_all()

    @pytest.mark.asyncio
    async def test_large_format_cached_raster_cleans_spatial_tile_paths_on_failure(
        self,
        tmp_path,
    ) -> None:
        image_path = tmp_path / "source.png"
        lut_path = tmp_path / "lut.npy"
        Image.fromarray(np.zeros((9, 13, 3), dtype=np.uint8)).save(image_path)
        lut_path.write_bytes(b"lut")
        matched_path = tmp_path / "matched.npy"
        mask_path = tmp_path / "mask.npy"
        material_path = tmp_path / "material.npy"
        np.save(matched_path, np.zeros((6, 8, 3), dtype=np.uint8))
        np.save(mask_path, np.ones((6, 8), dtype=bool))
        np.save(material_path, np.zeros((6, 8, 5), dtype=np.int16))
        route_local_paths: list[str] = []

        async def _fail(_fn, tile_path, _lut_path, tile_params):
            paths = [
                tile_params["matched_rgb_path"],
                tile_params["mask_solid_path"],
                tile_params["material_matrix_path"],
            ]
            assert all(path and os.path.exists(path) for path in paths)
            route_local_paths.extend([tile_path, *paths])
            raise RuntimeError("worker failed")

        store = SessionStore(ttl=1800)
        sid = store.create()
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )
        try:
            with pytest.raises(HTTPException) as exc_info:
                await _generate_large_format_raster(
                    image_path=str(image_path),
                    lut_path=str(lut_path),
                    source_basename="poster",
                    recipe_overrides=None,
                    recipe_override_masks_path=None,
                    matched_rgb_path=str(matched_path),
                    mask_solid_path=str(mask_path),
                    material_matrix_path=str(material_path),
                    total_width_mm=80.0,
                    total_height_mm=60.0,
                    tile_width_mm=80.0,
                    tile_height_mm=60.0,
                    request=request,
                    session_data={},
                    sid=sid,
                    store=store,
                    registry=FileRegistry(),
                    pool=SimpleNamespace(submit=AsyncMock(side_effect=_fail)),
                )

            assert exc_info.value.status_code == 500
            assert route_local_paths
            assert all(not os.path.exists(path) for path in route_local_paths)
            assert matched_path.exists()
            assert mask_path.exists()
            assert material_path.exists()
        finally:
            store.clear_all()


    @pytest.mark.asyncio
    async def test_large_format_cached_raster_uses_final_recipe_matrix_once(
        self,
        tmp_path,
    ) -> None:
        image_path = tmp_path / "source.png"
        lut_path = tmp_path / "lut.npy"
        Image.fromarray(np.zeros((11, 17, 3), dtype=np.uint8)).save(image_path)
        lut_path.write_bytes(b"lut")
        matched_rgb = np.full((4, 8, 3), [255, 0, 0], dtype=np.uint8)
        mask_solid = np.ones((4, 8), dtype=bool)
        final_material_matrix = np.full((4, 8, 5), 1, dtype=np.int16)
        final_material_matrix[:, 4:, :] = 2
        override_mask = np.zeros((4, 8), dtype=bool)
        override_mask[:2, 2:6] = True
        final_material_matrix[override_mask, :] = np.array(
            [3, 1, 3, 1, 3],
            dtype=np.int16,
        )

        matched_path = tmp_path / "matched.npy"
        mask_path = tmp_path / "mask.npy"
        material_path = tmp_path / "final-material.npy"
        recipe_masks_path = tmp_path / "recipe-masks.pkl"
        np.save(matched_path, matched_rgb)
        np.save(mask_path, mask_solid)
        np.save(material_path, final_material_matrix)
        with open(recipe_masks_path, "wb") as handle:
            pickle.dump({"region-1": override_mask}, handle)

        captured_matrices: list[np.ndarray] = []
        captured_masks_paths: list[str | None] = []

        async def _submit(_fn, _tile_path, _lut_path, tile_params):
            matched_tile = np.load(tile_params["matched_rgb_path"])
            mask_tile = np.load(tile_params["mask_solid_path"])
            material_tile = np.load(tile_params["material_matrix_path"])
            assert matched_tile.shape[:2] == mask_tile.shape == material_tile.shape[:2]
            captured_matrices.append(material_tile)
            captured_masks_paths.append(tile_params["recipe_override_masks_path"])
            output_path = tmp_path / f"recipe-tile-{len(captured_matrices)}.3mf"
            output_path.write_bytes(b"3mf")
            return {"threemf_path": str(output_path), "status_msg": "ok"}

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        sid = store.create()
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )
        download_id: str | None = None
        try:
            result = await _generate_large_format_raster(
                image_path=str(image_path),
                lut_path=str(lut_path),
                source_basename="poster",
                recipe_overrides=[
                    {
                        "region_id": "region-1",
                        "recipe": [3, 1, 3, 1, 3],
                        "layer_order": "Top2Bottom",
                    }
                ],
                recipe_override_masks_path=str(recipe_masks_path),
                matched_rgb_path=str(matched_path),
                mask_solid_path=str(mask_path),
                material_matrix_path=str(material_path),
                total_width_mm=80.0,
                total_height_mm=40.0,
                tile_width_mm=40.0,
                tile_height_mm=40.0,
                request=request,
                session_data={},
                sid=sid,
                store=store,
                registry=registry,
                pool=SimpleNamespace(submit=AsyncMock(side_effect=_submit)),
            )

            download_id = result["download_url"].rsplit("/", 1)[-1]
            assert len(captured_matrices) == 2
            assert np.array_equal(captured_matrices[0], final_material_matrix[:, :4])
            assert np.array_equal(captured_matrices[1], final_material_matrix[:, 4:])
            assert np.all(captured_matrices[0][0, 0] == 1)
            assert np.array_equal(
                captured_matrices[0][0, 2],
                np.array([3, 1, 3, 1, 3]),
            )
            assert np.all(captured_matrices[1][3, 3] == 2)
            assert captured_masks_paths == [None, None]
        finally:
            if download_id is not None:
                registry.cleanup_file(download_id)
            store.clear_all()

    @pytest.mark.asyncio
    async def test_large_format_cached_dynamic_material_raster_keeps_spatial_inputs(
        self,
        tmp_path,
    ) -> None:
        image_path = tmp_path / "source.png"
        Image.fromarray(np.zeros((15, 21, 4), dtype=np.uint8)).save(image_path)
        matched_rgb = np.arange(6 * 10 * 3, dtype=np.uint8).reshape(6, 10, 3)
        mask_solid = np.ones((6, 10), dtype=bool)
        material_matrix = np.arange(6 * 10 * 6, dtype=np.int32).reshape(6, 10, 6)
        quantized_image = np.flip(matched_rgb, axis=2).copy()
        matched_path = tmp_path / "matched.npy"
        mask_path = tmp_path / "mask.npy"
        material_path = tmp_path / "material.npy"
        quantized_path = tmp_path / "quantized.npy"
        np.save(matched_path, matched_rgb)
        np.save(mask_path, mask_solid)
        np.save(material_path, material_matrix)
        np.save(quantized_path, quantized_image)
        captured: list[dict[str, object]] = []

        async def _submit(_fn, _tile_path, _lut_path, tile_params):
            assert _fn.__name__ == "worker_generate_model"
            arrays = [
                np.load(tile_params["matched_rgb_path"]),
                np.load(tile_params["mask_solid_path"]),
                np.load(tile_params["material_matrix_path"]),
                np.load(tile_params["quantized_image_path"]),
            ]
            assert (
                arrays[0].shape[:2]
                == arrays[1].shape
                == arrays[2].shape[:2]
                == arrays[3].shape[:2]
            )
            captured.append(
                {
                    "arrays": arrays,
                    "material_source": tile_params["material_source"],
                    "reuse": tile_params["reuse_preview_analysis"],
                    "dynamic_enabled": tile_params[
                        "material_dynamic_layer_count_enabled"
                    ],
                    "dynamic_max": tile_params["material_max_layer_count"],
                }
            )
            output_path = tmp_path / f"archive-tile-{len(captured)}.3mf"
            output_path.write_bytes(b"3mf")
            return {"threemf_path": str(output_path), "status_msg": "ok"}

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        sid = store.create()
        request = LargeFormatConvertGenerateRequest(
            lut_name="__material_archive__",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )
        download_id: str | None = None
        try:
            result = await _generate_large_format_raster(
                image_path=str(image_path),
                lut_path="__material_archive__",
                source_basename="poster",
                recipe_overrides=None,
                recipe_override_masks_path=None,
                matched_rgb_path=str(matched_path),
                mask_solid_path=str(mask_path),
                material_matrix_path=str(material_path),
                quantized_image_path=str(quantized_path),
                total_width_mm=100.0,
                total_height_mm=60.0,
                tile_width_mm=50.0,
                tile_height_mm=30.0,
                request=request,
                session_data={
                    "material_source": "material_archive",
                    "selected_materials": ["mat-a", "mat-b"],
                    "material_layer_count": 6,
                    "material_layer_height_mm": 0.08,
                    "material_grid_resolution": 64,
                    "material_backing_material_index": 1,
                },
                sid=sid,
                store=store,
                registry=registry,
                pool=SimpleNamespace(submit=AsyncMock(side_effect=_submit)),
                dynamic_material_settings=(True, 5, 6, 0.5),
            )

            download_id = result["download_url"].rsplit("/", 1)[-1]
            assert len(captured) == 4
            assert all(item["material_source"] == "material_archive" for item in captured)
            assert all(item["reuse"] is True for item in captured)
            assert all(item["dynamic_enabled"] is True for item in captured)
            assert all(item["dynamic_max"] == 6 for item in captured)
            expected_quantized_tiles = [
                quantized_image[:3, :5],
                quantized_image[:3, 5:],
                quantized_image[3:, :5],
                quantized_image[3:, 5:],
            ]
            assert all(
                np.array_equal(item["arrays"][3], expected)
                for item, expected in zip(captured, expected_quantized_tiles)
            )
        finally:
            if download_id is not None:
                registry.cleanup_file(download_id)
            store.clear_all()

    @pytest.mark.asyncio
    async def test_large_format_dynamic_cached_analysis_requires_quantized_image(
        self,
        tmp_path,
    ) -> None:
        """Dynamic raster tiling rejects an incomplete cache before submitting tiles."""

        image_path = tmp_path / "source.png"
        Image.fromarray(np.zeros((6, 10, 3), dtype=np.uint8)).save(image_path)
        lut_path = tmp_path / "source.npy"
        lut_path.write_bytes(b"lut")
        matched_path = tmp_path / "matched.npy"
        mask_path = tmp_path / "mask.npy"
        material_path = tmp_path / "material.npy"
        np.save(matched_path, np.zeros((6, 10, 3), dtype=np.uint8))
        np.save(mask_path, np.ones((6, 10), dtype=bool))
        np.save(material_path, np.zeros((6, 10, 6), dtype=np.int32))

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        sid = store.create()
        pool = SimpleNamespace(submit=AsyncMock())
        request = LargeFormatConvertGenerateRequest(
            lut_name="__material_archive__",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )
        try:
            with pytest.raises(HTTPException) as exc_info:
                await _generate_large_format_raster(
                    image_path=str(image_path),
                    lut_path="__material_archive__",
                    source_basename="poster",
                    recipe_overrides=None,
                    recipe_override_masks_path=None,
                    matched_rgb_path=str(matched_path),
                    mask_solid_path=str(mask_path),
                    material_matrix_path=str(material_path),
                    total_width_mm=100.0,
                    total_height_mm=60.0,
                    tile_width_mm=50.0,
                    tile_height_mm=30.0,
                    request=request,
                    session_data={"material_source": "material_archive"},
                    sid=sid,
                    store=store,
                    registry=registry,
                    pool=pool,
                    dynamic_material_settings=(True, 5, 6, 0.5),
                )

            assert exc_info.value.status_code == 409
            assert (
                exc_info.value.detail
                == LARGE_FORMAT_CACHED_ANALYSIS_INVALID_DETAIL
            )
            pool.submit.assert_not_called()
        finally:
            store.clear_all()

    def test_large_format_raster_recipe_override_only_slices_final_matrix_once(self) -> None:
        fd_img, image_path = tempfile.mkstemp(suffix=".png")
        os.close(fd_img)
        fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
        os.close(fd_lut)
        fd_mm, material_matrix_path = tempfile.mkstemp(suffix=".npy")
        os.close(fd_mm)
        fd_masks, recipe_override_masks_path = tempfile.mkstemp(suffix=".pkl")
        os.close(fd_masks)
        fd_3mf, threemf_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_3mf)

        Image.fromarray(np.zeros((20, 20, 3), dtype=np.uint8)).save(image_path)
        with open(lut_path, "wb") as lut_file:
            lut_file.write(b"lut")
        np.save(material_matrix_path, np.zeros((4, 8, 5), dtype=np.uint8))
        authority_mask = np.zeros((4, 8), dtype=bool)
        authority_mask[:2, 2:6] = True
        with open(recipe_override_masks_path, "wb") as mask_file:
            pickle.dump({"region-1": authority_mask}, mask_file)
        with open(threemf_path, "wb") as threemf_file:
            threemf_file.write(b"3mf")

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        sid = store.create()
        store.put(sid, "preview_cache", {"target_w": 8, "target_h": 4})
        store.put(sid, "heightmap_grayscale", np.arange(20 * 20, dtype=np.uint8).reshape(20, 20))
        mock_pool = MagicMock(spec=WorkerPoolManager)
        captured_paths: list[str] = []
        captured_shapes: dict[str, tuple[int, ...]] = {}
        captured_recipe_mask_paths: list[str | None] = []
        captured_authority_masks: list[np.ndarray] = []
        captured_reuse_flags: list[bool] = []

        async def _mock_submit(_fn, _tile_path, _lut_path, tile_params):
            matrix_path = tile_params["material_matrix_path"]
            masks_path = tile_params["recipe_override_masks_path"]
            authority_mask_path = tile_params[
                "final_material_matrix_authority_mask_path"
            ]
            heightmap_path = tile_params["heightmap_path"]
            captured_paths.extend(
                [
                    _tile_path,
                    heightmap_path,
                    matrix_path,
                    authority_mask_path,
                ]
            )
            captured_shapes["matrix"] = tuple(np.load(matrix_path).shape)
            captured_recipe_mask_paths.append(masks_path)
            captured_authority_masks.append(np.load(authority_mask_path))
            captured_reuse_flags.append(bool(tile_params["reuse_preview_analysis"]))
            assert tile_params["final_material_matrix_is_authoritative"] is True
            assert tile_params["matched_rgb_path"] is None
            assert tile_params["mask_solid_path"] is None
            with Image.open(heightmap_path) as hm_img:
                captured_shapes["heightmap"] = hm_img.size
            with Image.open(_tile_path) as tile_img:
                captured_shapes["tile"] = tile_img.size
            return {
                "threemf_path": threemf_path,
                "status_msg": "ok",
            }

        mock_pool.submit = AsyncMock(side_effect=_mock_submit)
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
            enable_relief=True,
            height_mode="heightmap",
        )

        try:
            result = asyncio.run(
                _generate_large_format_raster(
                    image_path=image_path,
                    lut_path=lut_path,
                    source_basename="poster",
                    recipe_overrides=[
                        {
                            "region_id": "region-1",
                            "recipe": [1, 1, 1, 1, 1],
                            "layer_order": "Top2Bottom",
                        }
                    ],
                    recipe_override_masks_path=recipe_override_masks_path,
                    material_matrix_path=material_matrix_path,
                    final_material_matrix_is_authoritative=True,
                    total_width_mm=80.0,
                    total_height_mm=40.0,
                    tile_width_mm=40.0,
                    tile_height_mm=40.0,
                    request=request,
                    session_data={
                        "preview_cache": {"target_w": 8, "target_h": 4},
                        "heightmap_grayscale": np.arange(20 * 20, dtype=np.uint8).reshape(20, 20),
                    },
                    sid=sid,
                    store=store,
                    registry=registry,
                    pool=mock_pool,
                )
            )

            download_id = result["download_url"].rsplit("/", 1)[-1]
            zip_path, _filename = registry.resolve(download_id)
            assert os.path.exists(zip_path)
            assert captured_shapes["matrix"] == (4, 4, 5)
            assert captured_shapes["tile"] == (10, 20)
            assert captured_shapes["heightmap"] == (10, 20)
            assert captured_recipe_mask_paths == [None, None]
            assert np.array_equal(captured_authority_masks[0], authority_mask[:, :4])
            assert np.array_equal(captured_authority_masks[1], authority_mask[:, 4:])
            assert captured_reuse_flags == [False, False]
            assert captured_paths
            assert all(not os.path.exists(path) for path in captured_paths)
            entry = registry.get_entry(download_id)
            assert entry is not None
            assert entry["lifecycle"] == "ephemeral"
            assert zip_path not in set(store.get_temp_file_paths(sid))
        finally:
            store.clear_all()
            for path in (image_path, lut_path, material_matrix_path, recipe_override_masks_path, threemf_path):
                if os.path.exists(path):
                    os.unlink(path)

    @pytest.mark.asyncio
    async def test_recipe_authority_survives_non_divisible_route_and_fresh_s02_grids(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        """Four physical tiles align recipe authority to each fresh S02 grid.

        LUT and material-archive entry points have equivalent direct S02→S03
        coverage in ``test_pipeline_step_modules_unit.py``. This route-level
        test exercises their shared recipe-authority alignment after the real
        19×13 source and 100×68 recipe cache are cropped into four tiles.
        """

        from core.image_processing import (
            LuminaImageProcessor as RealLuminaImageProcessor,
        )
        from core.pipeline import s02_image_processing
        from core.pipeline import s03_color_replacement

        image_path = tmp_path / "source.png"
        lut_path = tmp_path / "lut.npy"
        material_matrix_path = tmp_path / "final-material.npy"
        recipe_masks_path = tmp_path / "recipe-masks.pkl"
        Image.fromarray(np.zeros((13, 19, 3), dtype=np.uint8)).save(image_path)
        lut_path.write_bytes(b"lut")

        final_material_matrix = np.ones((68, 100, 5), dtype=np.int16)
        authority_mask = np.zeros((68, 100), dtype=bool)
        authority_mask[5:35, 5:45] = True
        authority_mask[5:35, 55:95] = True
        authority_mask[43:65, 5:45] = True
        authority_mask[43:65, 55:95] = True
        final_material_matrix[authority_mask] = 7
        np.save(material_matrix_path, final_material_matrix)
        with open(recipe_masks_path, "wb") as handle:
            pickle.dump({"region-1": authority_mask}, handle)

        class _FakeTree:
            @staticmethod
            def query(_values):
                return np.array([0.0]), np.array([1])

        class _GridOnlyProcessor:
            def __init__(self, *_args, **_kwargs) -> None:
                self.enable_cleanup = True
                self.last_match_info = None
                self.kdtree = _FakeTree()
                self.ref_stacks = np.array(
                    [[1, 1, 1, 1, 1], [2, 2, 2, 2, 2]],
                    dtype=np.int16,
                )
                self.lut_rgb = np.array(
                    [[255, 0, 0], [0, 255, 0]],
                    dtype=np.uint8,
                )

            @staticmethod
            def _rgb_to_lab(values: np.ndarray) -> np.ndarray:
                return np.asarray(values, dtype=np.float64)

            def process_image(
                self,
                *,
                image_path: str,
                target_width_mm: float,
                modeling_mode,
                **_kwargs,
            ) -> dict:
                with Image.open(image_path) as tile_image:
                    target_w, target_h, pixel_scale = (
                        RealLuminaImageProcessor._calc_dimensions(
                            self,
                            tile_image,
                            target_width_mm,
                            modeling_mode,
                        )
                    )
                return {
                    "matched_rgb": np.full(
                        (target_h, target_w, 3),
                        [255, 0, 0],
                        dtype=np.uint8,
                    ),
                    "material_matrix": np.ones(
                        (target_h, target_w, 5),
                        dtype=np.int16,
                    ),
                    "mask_solid": np.ones((target_h, target_w), dtype=bool),
                    "dimensions": (target_w, target_h),
                    "pixel_scale": pixel_scale,
                    "mode_info": {"mode": modeling_mode},
                }

        monkeypatch.setattr(s02_image_processing, "LUTManager", None)
        monkeypatch.setattr(
            s02_image_processing,
            "LuminaImageProcessor",
            _GridOnlyProcessor,
        )

        observed: list[dict[str, tuple[int, int]]] = []
        worker_outputs: list[str] = []

        async def _submit(_fn, tile_path, worker_lut_path, tile_params):
            with Image.open(tile_path) as tile_image:
                source_shape = (tile_image.height, tile_image.width)
            matrix_crop = np.load(
                tile_params["material_matrix_path"],
                allow_pickle=False,
            )
            authority_crop = np.load(
                tile_params["final_material_matrix_authority_mask_path"],
                allow_pickle=False,
            )
            ctx = dict(tile_params)
            ctx.update(
                {
                    "actual_lut_path": worker_lut_path,
                    "image_path": tile_path,
                }
            )
            after_s02 = s02_image_processing.run(ctx)
            after_s03 = s03_color_replacement.run(after_s02)

            target_shape = after_s03["material_matrix"].shape[:2]
            expected_authority = np.asarray(
                Image.fromarray(authority_crop.astype(np.uint8)).resize(
                    (target_shape[1], target_shape[0]),
                    resample=Image.Resampling.NEAREST,
                ),
                dtype=bool,
            )
            assert np.any(expected_authority)
            assert np.any(~expected_authority)
            assert np.all(
                after_s03["material_matrix"][expected_authority] == 7
            )
            assert np.all(
                after_s03["material_matrix"][~expected_authority] == 2
            )
            observed.append(
                {
                    "source": source_shape,
                    "cache": matrix_crop.shape[:2],
                    "fresh": target_shape,
                }
            )
            output_path = tmp_path / f"tile-{len(observed)}.3mf"
            output_path.write_bytes(b"3mf")
            worker_outputs.append(str(output_path))
            return {"threemf_path": str(output_path), "status_msg": "ok"}

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        sid = store.create()
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )
        download_id: str | None = None
        try:
            result = await _generate_large_format_raster(
                image_path=str(image_path),
                lut_path=str(lut_path),
                source_basename="poster",
                recipe_overrides=[
                    {
                        "region_id": "region-1",
                        "recipe": [7, 7, 7, 7, 7],
                        "layer_order": "Top2Bottom",
                    }
                ],
                recipe_override_masks_path=str(recipe_masks_path),
                material_matrix_path=str(material_matrix_path),
                final_material_matrix_is_authoritative=True,
                total_width_mm=10.0,
                total_height_mm=6.8,
                tile_width_mm=5.0,
                tile_height_mm=4.0,
                request=request,
                session_data={
                    "replacement_regions": [
                        {
                            "quantized_hex": "#ff0000",
                            "matched_hex": "#ff0000",
                            "replacement_hex": "#00ff00",
                        }
                    ]
                },
                sid=sid,
                store=store,
                registry=registry,
                pool=SimpleNamespace(submit=AsyncMock(side_effect=_submit)),
            )

            download_id = result["download_url"].rsplit("/", 1)[-1]
            assert observed == [
                {"source": (8, 10), "cache": (40, 50), "fresh": (40, 50)},
                {"source": (8, 9), "cache": (40, 50), "fresh": (44, 50)},
                {"source": (5, 10), "cache": (28, 50), "fresh": (25, 50)},
                {"source": (5, 9), "cache": (28, 50), "fresh": (27, 50)},
            ]
        finally:
            if download_id is not None:
                registry.cleanup_file(download_id)
            store.clear_all()
            for output_path in worker_outputs:
                if os.path.exists(output_path):
                    os.unlink(output_path)

    @pytest.mark.asyncio
    async def test_large_format_recipe_authority_mask_tile_path_cleans_on_failure(
        self,
        tmp_path,
    ) -> None:
        image_path = tmp_path / "source.png"
        lut_path = tmp_path / "lut.npy"
        material_matrix_path = tmp_path / "final-material.npy"
        recipe_masks_path = tmp_path / "recipe-masks.pkl"
        Image.fromarray(np.zeros((20, 20, 3), dtype=np.uint8)).save(image_path)
        lut_path.write_bytes(b"lut")
        np.save(
            material_matrix_path,
            np.zeros((4, 4, 5), dtype=np.int16),
        )
        with open(recipe_masks_path, "wb") as handle:
            pickle.dump(
                {"region-1": np.eye(4, dtype=bool)},
                handle,
            )

        route_local_paths: list[str] = []

        async def _fail(_fn, tile_path, _lut_path, tile_params):
            paths = [
                tile_path,
                tile_params["material_matrix_path"],
                tile_params["final_material_matrix_authority_mask_path"],
            ]
            assert all(path and os.path.exists(path) for path in paths)
            route_local_paths.extend(paths)
            raise RuntimeError("worker failed")

        store = SessionStore(ttl=1800)
        sid = store.create()
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )
        try:
            with pytest.raises(HTTPException) as exc_info:
                await _generate_large_format_raster(
                    image_path=str(image_path),
                    lut_path=str(lut_path),
                    source_basename="poster",
                    recipe_overrides=[
                        {
                            "region_id": "region-1",
                            "recipe": [1, 1, 1, 1, 1],
                            "layer_order": "Top2Bottom",
                        }
                    ],
                    recipe_override_masks_path=str(recipe_masks_path),
                    material_matrix_path=str(material_matrix_path),
                    final_material_matrix_is_authoritative=True,
                    total_width_mm=40.0,
                    total_height_mm=40.0,
                    tile_width_mm=40.0,
                    tile_height_mm=40.0,
                    request=request,
                    session_data={},
                    sid=sid,
                    store=store,
                    registry=FileRegistry(),
                    pool=SimpleNamespace(submit=AsyncMock(side_effect=_fail)),
                )

            assert exc_info.value.status_code == 500
            assert route_local_paths
            assert all(not os.path.exists(path) for path in route_local_paths)
            assert material_matrix_path.exists()
            assert recipe_masks_path.exists()
        finally:
            store.clear_all()


    def test_large_format_raster_all_tile_failure_sanitizes_status_message(self) -> None:
        fd_img, image_path = tempfile.mkstemp(suffix=".png")
        os.close(fd_img)
        fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
        os.close(fd_lut)
        private_path = "/Users/min/private/tile-R1C1.3mf"
        log_calls: list[tuple[str, str, dict[str, object]]] = []

        def _capturing_safe_log(level: str, event: str, **fields: object) -> None:
            log_calls.append((level, event, fields))

        Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8)).save(image_path)
        with open(lut_path, "wb") as lut_file:
            lut_file.write(b"lut")

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        sid = store.create()
        mock_pool = MagicMock(spec=WorkerPoolManager)
        mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": None,
                "status_msg": f"cannot write {private_path}: Permission denied",
            }
        )
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )

        try:
            with (
                patch(
                    "api.routers.converter.generate._safe_log",
                    side_effect=_capturing_safe_log,
                ),
                pytest.raises(HTTPException) as exc_info,
            ):
                asyncio.run(
                    _generate_large_format_raster(
                        image_path=image_path,
                        lut_path=lut_path,
                        source_basename="poster",
                        recipe_overrides=None,
                        recipe_override_masks_path=None,
                        material_matrix_path=None,
                        total_width_mm=40.0,
                        total_height_mm=40.0,
                        tile_width_mm=40.0,
                        tile_height_mm=40.0,
                        request=request,
                        session_data={},
                        sid=sid,
                        store=store,
                        registry=registry,
                        pool=mock_pool,
                    )
                )

            assert exc_info.value.status_code == 500
            assert exc_info.value.detail == (
                "Large-format generation failed. Try again or check the server log for details."
            )
            detail = str(exc_info.value.detail)
            assert private_path not in detail
            assert "Permission denied" not in detail
            assert "All tiles failed" not in detail
            failure_logs = [
                (level, fields)
                for level, event, fields in log_calls
                if event == "converter_large_format_failed"
            ]
            assert len(failure_logs) == 1
            level, fields = failure_logs[0]
            assert level == "error"
            assert fields["session_id"] == sid
            assert fields["failure_kind"] == "tile_failed"
            assert fields["error_type"] == "LargeFormatTileFailure"
            assert private_path in str(fields["error_message"])
            assert "Permission denied" in str(fields["error_message"])
        finally:
            store.clear_all()
            for path in (image_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_recipe_override_matrix_load_failure_is_sanitized(self) -> None:
        fd_img, image_path = tempfile.mkstemp(suffix=".png")
        os.close(fd_img)
        fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
        os.close(fd_lut)
        private_path = "/Users/min/private/material-matrix.npy"
        log_calls: list[tuple[str, str, dict[str, object]]] = []

        def _capturing_safe_log(level: str, event: str, **fields: object) -> None:
            log_calls.append((level, event, fields))

        Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8)).save(image_path)
        with open(lut_path, "wb") as lut_file:
            lut_file.write(b"lut")

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )

        try:
            with (
                patch(
                    "api.routers.converter.generate.np.load",
                    side_effect=OSError(
                        f"cannot load {private_path}: Permission denied"
                    ),
                ),
                patch(
                    "api.routers.converter.generate._safe_log",
                    side_effect=_capturing_safe_log,
                ),
                pytest.raises(HTTPException) as exc_info,
            ):
                asyncio.run(
                    _generate_large_format_raster(
                        image_path=image_path,
                        lut_path=lut_path,
                        source_basename="poster",
                        recipe_overrides=[
                            {"region_id": "r1", "recipe": [1, 1, 1, 1, 1]},
                        ],
                        recipe_override_masks_path=None,
                        material_matrix_path=private_path,
                        total_width_mm=40.0,
                        total_height_mm=40.0,
                        tile_width_mm=40.0,
                        tile_height_mm=40.0,
                        request=request,
                        session_data={},
                        sid="large-format-session",
                        store=store,
                        registry=registry,
                        pool=MagicMock(spec=WorkerPoolManager),
                    )
                )

            assert exc_info.value.status_code == 500
            assert exc_info.value.detail == (
                "Large-format recipe override data could not be loaded. Re-run preview and try again."
            )
            detail = str(exc_info.value.detail)
            assert private_path not in detail
            assert "Permission denied" not in detail
            failure_logs = [
                (level, fields)
                for level, event, fields in log_calls
                if event == "converter_large_format_failed"
            ]
            assert len(failure_logs) == 1
            level, fields = failure_logs[0]
            assert level == "error"
            assert fields["session_id"] == "large-format-session"
            assert fields["failure_kind"] == "recipe_override_matrix"
            assert fields["error_type"] == "OSError"
            assert fields["artifact_role"] == "material_matrix"
            assert fields["path"] == private_path
            assert private_path in str(fields["error_message"])
            assert "Permission denied" in str(fields["error_message"])
        finally:
            store.clear_all()
            for path in (image_path, lut_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_recipe_override_masks_load_failure_is_sanitized(self) -> None:
        fd_img, image_path = tempfile.mkstemp(suffix=".png")
        os.close(fd_img)
        fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
        os.close(fd_lut)
        fd_masks, masks_path = tempfile.mkstemp(suffix=".pkl")
        os.close(fd_masks)
        private_path = "/Users/min/private/recipe-masks.pkl"
        log_calls: list[tuple[str, str, dict[str, object]]] = []

        def _capturing_safe_log(level: str, event: str, **fields: object) -> None:
            log_calls.append((level, event, fields))

        Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8)).save(image_path)
        with open(lut_path, "wb") as lut_file:
            lut_file.write(b"lut")

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )

        try:
            with (
                patch(
                    "api.routers.converter.generate.np.load",
                    return_value=np.zeros((10, 10, 5), dtype=np.int16),
                ),
                patch(
                    "api.routers.converter.generate.pickle.load",
                    side_effect=pickle.UnpicklingError(
                        f"cannot load {private_path}: Permission denied"
                    ),
                ),
                patch(
                    "api.routers.converter.generate._safe_log",
                    side_effect=_capturing_safe_log,
                ),
                pytest.raises(HTTPException) as exc_info,
            ):
                asyncio.run(
                    _generate_large_format_raster(
                        image_path=image_path,
                        lut_path=lut_path,
                        source_basename="poster",
                        recipe_overrides=[
                            {"region_id": "r1", "recipe": [1, 1, 1, 1, 1]},
                        ],
                        recipe_override_masks_path=masks_path,
                        material_matrix_path="/tmp/material-matrix.npy",
                        total_width_mm=40.0,
                        total_height_mm=40.0,
                        tile_width_mm=40.0,
                        tile_height_mm=40.0,
                        request=request,
                        session_data={},
                        sid="large-format-session",
                        store=store,
                        registry=registry,
                        pool=MagicMock(spec=WorkerPoolManager),
                    )
                )

            assert exc_info.value.status_code == 500
            assert exc_info.value.detail == (
                "Large-format recipe override data could not be loaded. Re-run preview and try again."
            )
            detail = str(exc_info.value.detail)
            assert private_path not in detail
            assert "Permission denied" not in detail
            failure_logs = [
                (level, fields)
                for level, event, fields in log_calls
                if event == "converter_large_format_failed"
            ]
            assert len(failure_logs) == 1
            level, fields = failure_logs[0]
            assert level == "error"
            assert fields["session_id"] == "large-format-session"
            assert fields["failure_kind"] == "recipe_override_masks"
            assert fields["error_type"] == "UnpicklingError"
            assert fields["artifact_role"] == "recipe_override_masks"
            assert fields["path"] == masks_path
            assert private_path in str(fields["error_message"])
            assert "Permission denied" in str(fields["error_message"])
        finally:
            store.clear_all()
            for path in (image_path, lut_path, masks_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_svg_fallback_success_cleans_route_local_png(self) -> None:
        sid, _svg_path, _lut_path = _create_svg_session(_test_store, native_tiling_supported=False)

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 60.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "modeling_mode": "vector",
                    "target_width_mm": 90.0,
                },
            },
        }

        raster_response = {
            "status": "ok",
            "message": "raster",
            "download_url": "/api/files/raster",
            "tile_count": 4,
            "grid_cols": 2,
            "grid_rows": 2,
            "warnings": ["Raster fallback was used for this large-format SVG request."],
        }
        captured = {"image_path": "unset", "svg_fallback_path": "unset"}

        def _fake_raster_helper(**kwargs):
            captured["image_path"] = kwargs["image_path"]
            captured["svg_fallback_path"] = kwargs["svg_fallback_path"]
            return raster_response

        with patch(
            "api.routers.converter.generate._generate_large_format_raster",
            side_effect=_fake_raster_helper,
        ):
            response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 200
        assert captured["image_path"] is None
        assert captured["svg_fallback_path"] == _svg_path

    def test_large_format_raster_helper_deletes_tile_3mf_and_glb_after_packaging(self) -> None:
        fd_img, image_path = tempfile.mkstemp(suffix=".png")
        os.close(fd_img)
        fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
        os.close(fd_lut)
        fd_3mf, threemf_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_3mf)
        fd_glb, glb_path = tempfile.mkstemp(suffix=".glb")
        os.close(fd_glb)

        Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8)).save(image_path)
        with open(lut_path, "wb") as lut_file:
            lut_file.write(b"lut")
        with open(threemf_path, "wb") as threemf_file:
            threemf_file.write(b"3mf")
        with open(glb_path, "wb") as glb_file:
            glb_file.write(b"glb")

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        sid = store.create()
        mock_pool = MagicMock(spec=WorkerPoolManager)
        mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": threemf_path,
                "glb_path": glb_path,
                "status_msg": "ok",
            }
        )
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )

        try:
            result = asyncio.run(
                _generate_large_format_raster(
                    image_path=image_path,
                    lut_path=lut_path,
                    source_basename="poster",
                    recipe_overrides=None,
                    recipe_override_masks_path=None,
                    material_matrix_path=None,
                    total_width_mm=40.0,
                    total_height_mm=40.0,
                    tile_width_mm=40.0,
                    tile_height_mm=40.0,
                    request=request,
                    session_data={},
                    sid=sid,
                    store=store,
                    registry=registry,
                    pool=mock_pool,
                )
            )

            download_id = result["download_url"].rsplit("/", 1)[-1]
            zip_path, _filename = registry.resolve(download_id)
            assert os.path.exists(zip_path)
            assert not os.path.exists(threemf_path)
            assert not os.path.exists(glb_path)
        finally:
            store.clear_all()
            for path in (image_path, lut_path, threemf_path, glb_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_raster_helper_cleans_collected_outputs_when_zip_creation_fails(self) -> None:
        fd_img, image_path = tempfile.mkstemp(suffix=".png")
        os.close(fd_img)
        fd_lut, lut_path = tempfile.mkstemp(suffix=".npy")
        os.close(fd_lut)
        fd_3mf, threemf_path = tempfile.mkstemp(suffix=".3mf")
        os.close(fd_3mf)
        fd_glb, glb_path = tempfile.mkstemp(suffix=".glb")
        os.close(fd_glb)

        Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8)).save(image_path)
        with open(lut_path, "wb") as lut_file:
            lut_file.write(b"lut")
        with open(threemf_path, "wb") as threemf_file:
            threemf_file.write(b"3mf")
        with open(glb_path, "wb") as glb_file:
            glb_file.write(b"glb")

        store = SessionStore(ttl=1800)
        registry = FileRegistry()
        sid = store.create()
        mock_pool = MagicMock(spec=WorkerPoolManager)
        mock_pool.submit = AsyncMock(
            return_value={
                "threemf_path": threemf_path,
                "glb_path": glb_path,
                "status_msg": "ok",
            }
        )
        request = LargeFormatConvertGenerateRequest(
            lut_name="test_lut",
            modeling_mode=ModelingMode.HIGH_FIDELITY,
        )

        try:
            with patch("api.routers.converter.generate.zipfile.ZipFile", side_effect=RuntimeError("zip failed")):
                with pytest.raises(RuntimeError, match="zip failed"):
                    asyncio.run(
                        _generate_large_format_raster(
                            image_path=image_path,
                            lut_path=lut_path,
                            source_basename="poster",
                            recipe_overrides=None,
                            recipe_override_masks_path=None,
                            material_matrix_path=None,
                            total_width_mm=40.0,
                            total_height_mm=40.0,
                            tile_width_mm=40.0,
                            tile_height_mm=40.0,
                            request=request,
                            session_data={},
                            sid=sid,
                            store=store,
                            registry=registry,
                            pool=mock_pool,
                        )
                    )

            assert not os.path.exists(threemf_path)
            assert not os.path.exists(glb_path)
        finally:
            store.clear_all()
            for path in (image_path, lut_path, threemf_path, glb_path):
                if os.path.exists(path):
                    os.unlink(path)

    def test_large_format_rejects_fridge_magnet_flag_even_with_empty_list(self) -> None:
        sid: str = _create_session_with_preview_and_files(_test_store)

        payload = {
            "session_id": sid,
            "params": {
                "target_height_mm": 80.0,
                "tile_width_mm": 40.0,
                "tile_height_mm": 40.0,
                "params": {
                    "lut_name": "test_lut",
                    "enable_fridge_magnet": True,
                    "fridge_magnets": [],
                },
            },
        }

        response = client.post("/api/convert/generate-large-format", json=payload)

        assert response.status_code == 422
        assert "fridge magnet" in response.json()["detail"].lower()


def test_convert_generate_request_accepts_native_bundle_source() -> None:
    """ConvertGenerateRequest should support native-bundle source selection fields."""

    request = ConvertGenerateRequest(
        source_kind="native_bundle",
        material_type="PLA",
        vendor="BambuLab",
        db_names=["RYBW_008_5L"],
    )

    assert request.source_kind == "native_bundle"
    assert request.material_type == "PLA"
    assert request.vendor == "BambuLab"
    assert request.db_names == ["RYBW_008_5L"]
    assert request.nozzle_size == "0.4"


@pytest.mark.parametrize(
    ("structure_mode", "color_mode"),
    [
        (StructureMode.DOUBLE_SIDED, ColorMode.FOUR_COLOR_RYBW),
        (StructureMode.SINGLE_SIDED, ColorMode.FIVE_COLOR_EXT),
    ],
)
def test_native_vector_relief_validation_rejects_flat_export_branches(
    structure_mode: StructureMode,
    color_mode: ColorMode,
) -> None:
    request = ConvertGenerateRequest(
        lut_name="test-lut",
        modeling_mode=ModelingMode.VECTOR,
        structure_mode=structure_mode,
        color_mode=color_mode,
        enable_relief=True,
        height_mode="color",
        color_height_map={"#ff0000": 2.0},
    )

    with pytest.raises(HTTPException) as exc_info:
        _validate_native_vector_relief_compatibility(request)

    assert exc_info.value.status_code == 422
    assert "Native SVG relief supports only" in str(exc_info.value.detail)


def test_resolve_recipe_overrides_uses_session_when_request_array_is_empty() -> None:
    request = ConvertGenerateRequest(
        lut_name="test-lut",
        recipe_overrides=[],
    )

    resolved = _resolve_recipe_overrides(
        {"recipe_overrides": [{"region_id": "region-1", "recipe": [1, 1, 1, 1, 1], "layer_order": "Top2Bottom"}]},
        request,
    )

    assert resolved == [
        {"region_id": "region-1", "recipe": [1, 1, 1, 1, 1], "layer_order": "Top2Bottom"}
    ]


def test_resolve_recipe_overrides_backfills_session_virtual_materials_when_request_omits_them() -> None:
    """Backend safety: session-persisted virtual_materials must survive when the
    request body's recipe_overrides (same region_id) forgets to send them.

    apply 端点会把用户声明的 virtual_materials 随 recipe_overrides 一起持久化
    到 session。前端旧版本 / 第三方调用方可能在 /generate 时只回传
    ``{region_id, recipe, layer_order}``——若 backend 简单用 request 覆盖 session，
    virtual_materials 就整条丢失，worker 无法扩展 ctx["slot_names"]，
    S07 只会给 LUT 原生通道生成 mesh，表现为 3MF 缺少自定义颜色对象、
    该通道像素无网格（看起来像"方块 / 透明失效"）。

    回归保证：当 request 的某个 region_id 没带 virtual_materials、session
    同一 region_id 有持久化的 virtuals 时，resolver 必须把它们合并回来。
    """
    session_data = {
        "recipe_overrides": [
            {
                "region_id": "region-1",
                "recipe": [4, 0, 0, 0, 0, 4],
                "layer_order": "Top2Bottom",
                "virtual_materials": [{"name": "Black", "hex": "#111111"}],
            }
        ]
    }
    request = ConvertGenerateRequest(
        lut_name="test-lut",
        recipe_overrides=[
            {
                "region_id": "region-1",
                "recipe": [4, 0, 0, 0, 0, 4],
                "layer_order": "Top2Bottom",
                # Intentionally no ``virtual_materials`` — old-client scenario.
            }
        ],
    )

    resolved = _resolve_recipe_overrides(session_data, request)

    assert resolved is not None
    assert len(resolved) == 1
    assert resolved[0]["region_id"] == "region-1"
    assert resolved[0]["recipe"] == [4, 0, 0, 0, 0, 4]
    assert resolved[0]["virtual_materials"] == [
        {"name": "Black", "hex": "#111111"}
    ]


def test_resolve_recipe_overrides_backfills_virtuals_from_preview_cache_when_session_item_lacks_them() -> None:
    """A stale frontend may send virtual material indices without virtuals.

    apply-recipe-override has already extended preview_cache slot_names and
    preview_colors, so generate can reconstruct the missing virtual_materials
    list from that cache instead of letting worker mesh generation see channel
    ids that do not exist in its palette.

    旧前端 / 陈旧状态可能只把虚拟通道索引发到 /generate，却漏掉
    virtual_materials。apply 端点已经把虚拟材料写进 preview_cache，
    generate 应从 cache 回补，避免 worker 只看到材料矩阵里的 N+1 通道，
    却没有对应调色板，最终 3MF 生成 500。
    """
    session_data = {
        "preview_cache": {
            "lut_metadata": SimpleNamespace(palette=[object(), object(), object(), object()]),
            "slot_names": ["White", "Cyan", "Magenta", "Yellow", "Black"],
            "preview_colors": {
                0: [245, 245, 245, 255],
                1: [0, 183, 235, 255],
                2: [230, 0, 126, 255],
                3: [255, 212, 0, 255],
                4: [17, 17, 17, 255],
            },
        },
        "recipe_overrides": [
            {
                "region_id": "region-1",
                "recipe": [4, 4, 4, 4, 4, 4, 4],
                "layer_order": "Top2Bottom",
                # Intentionally missing virtual_materials.
            }
        ],
    }
    request = ConvertGenerateRequest(
        lut_name="test-lut",
        recipe_overrides=[
            {
                "region_id": "region-1",
                "recipe": [4, 4, 4, 4, 4, 4, 4],
                "layer_order": "Top2Bottom",
            }
        ],
    )

    resolved = _resolve_recipe_overrides(session_data, request)

    assert resolved is not None
    assert resolved[0]["virtual_materials"] == [
        {"name": "Black", "hex": "#111111"}
    ]


def test_recover_virtual_materials_from_material_archive_preview_cache() -> None:
    """Material-archive sessions have no LUT metadata during generation.

    Recovery must use ``selected_materials`` as the native palette length so a
    stale generate request carrying recipe indices can still rebuild virtual
    material declarations from the preview cache.
    """
    session_data = {
        "material_source": "material_archive",
        "selected_materials": ["mat-red", "mat-blue", "mat-white"],
        "preview_cache": {
            "slot_names": ["Red", "Blue", "White", "Black"],
            "preview_colors": {
                0: [153, 13, 13, 255],
                1: [13, 26, 153, 255],
                2: [242, 242, 242, 255],
                3: [17, 17, 17, 255],
            },
        },
    }

    recovered = _recover_virtual_materials_from_preview_cache(
        session_data,
        [3, 3, 3, 3, 3],
    )

    assert recovered == [{"name": "Black", "hex": "#111111"}]


def test_material_archive_backing_color_id_uses_requested_index() -> None:
    assert _resolve_material_archive_backing_color_id(["mat-a", "mat-b", "mat-c"], 2) == 2
    assert _resolve_material_archive_backing_color_id(["mat-a"], None) == 0
    assert _resolve_material_archive_backing_color_id(["mat-green", "mat-white"], None) == 1
    assert _resolve_material_archive_backing_color_id(["brand/PLA 绿", "brand/PLA 白"], None) == 1
    with pytest.raises(ValueError, match="outside selected_materials"):
        _resolve_material_archive_backing_color_id(["mat-a"], 1)


def test_direct_converter_uses_requested_material_archive_backing_index() -> None:
    captured_ctx: dict = {}

    def _capture_pipeline_ctx(ctx: dict) -> dict:
        captured_ctx.update(ctx)
        return {
            **ctx,
            "result_tuple": (None, None, None, "captured", None),
        }

    with patch(
        "core.converter.run_raster_pipeline",
        side_effect=_capture_pipeline_ctx,
    ):
        convert_image_to_3d(
            image_path="input.png",
            lut_path="__material_archive__",
            target_width_mm=70.0,
            spacer_thick=1.2,
            structure_mode="Single-sided",
            color_mode="4-Color (RYBW)",
            add_loop=False,
            loop_width=4.0,
            loop_length=8.0,
            loop_hole=2.5,
            loop_pos=None,
            modeling_mode=CoreModelingMode.HIGH_FIDELITY,
            material_source="material_archive",
            selected_materials=["brand/yellow", "brand/white"],
            material_backing_material_index=1,
        )

    assert captured_ctx["backing_color_id"] == 1
    assert captured_ctx["separate_backing_color_id"] == 1
    assert captured_ctx["separate_backing"] is False


def test_generate_route_infers_material_archive_white_backing_when_unspecified(tmp_path) -> None:
    _test_store.clear_all()
    image_path = tmp_path / "input.png"
    out_path = tmp_path / "out.3mf"
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
    out_path.write_bytes(b"3mf")

    session_id = _test_store.create()
    _test_store.put(session_id, "image_path", str(image_path))
    _test_store.put(session_id, "lut_path", "__material_archive__")
    _test_store.put(session_id, "material_source", "material_archive")
    _test_store.put(
        session_id,
        "selected_materials",
        ["brand/pla-green", "brand/pla-yellow", "brand/pla-white"],
    )
    _test_store.put(session_id, "material_layer_count", 7)
    _test_store.put(session_id, "material_layer_height_mm", 0.08)
    _test_store.put(session_id, "replacement_regions", [])
    _test_store.put(session_id, "free_color_set", set())
    _test_store.put(
        session_id,
        "preview_cache",
        {
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
            "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
            "mask_solid": np.ones((4, 4), dtype=bool),
            "material_matrix": np.zeros((4, 4, 7), dtype=np.uint8),
        },
    )

    _mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": str(out_path),
            "glb_path": None,
            "status_msg": "OK",
        }
    )

    response = client.post(
        "/api/convert/generate",
        json={"session_id": session_id, "params": {"lut_name": "__material_archive__"}},
    )

    assert response.status_code == 200, response.text
    submitted_params = _mock_pool.submit.call_args.args[3]
    assert submitted_params["material_backing_material_index"] == 2


def test_generate_route_inherits_dynamic_settings_and_maps_typed_error(
    tmp_path,
) -> None:
    from core.material_dynamic_solver import DynamicMaterialCandidateError

    _test_store.clear_all()
    image_path = tmp_path / "input.png"
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
    sid = _test_store.create()
    _test_store.put(sid, "image_path", str(image_path))
    _test_store.put(sid, "lut_path", "__material_archive__")
    _test_store.put(sid, "material_source", "material_archive")
    _test_store.put(sid, "selected_materials", ["mat-a", "mat-b"])
    _test_store.put(sid, "material_layer_count", 10)
    _test_store.put(sid, "material_dynamic_layer_count_enabled", True)
    _test_store.put(sid, "material_min_layer_count", 6)
    _test_store.put(sid, "material_max_layer_count", 8)
    _test_store.put(sid, "material_delta_e00_tolerance", 0.4)
    _test_store.put(sid, "replacement_regions", [])
    _test_store.put(sid, "free_color_set", set())
    _test_store.put(
        sid,
        "preview_cache",
        {
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
            "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
            "mask_solid": np.ones((4, 4), dtype=bool),
            "material_matrix": np.zeros((4, 4, 8), dtype=np.uint8),
        },
    )
    captured: dict[str, object] = {}

    async def _raise_typed(_worker, _image, _lut, params):
        captured.update(params)
        raise DynamicMaterialCandidateError(
            "no candidate",
            target_srgb=(12, 34, 56),
            layer_count=6,
            phase="exact_search",
        )

    _mock_pool.submit = AsyncMock(side_effect=_raise_typed)

    response = client.post(
        "/api/convert/generate",
        json={
            "session_id": sid,
            "params": {"lut_name": "__material_archive__"},
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "dynamic_material_no_candidate"
    assert captured["material_dynamic_layer_count_enabled"] is True
    assert captured["material_min_layer_count"] == 6
    assert captured["material_max_layer_count"] == 8
    assert captured["material_delta_e00_tolerance"] == 0.4


def test_generate_route_accepts_dynamic_native_svg_cached_analysis(tmp_path) -> None:
    """Regular native SVG generation projects the authoritative vector cache."""

    _test_store.clear_all()
    svg_path = tmp_path / "native.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4">'
        '<path d="M0,0 L4,0 L4,4 Z" fill="#ff0000"/>'
        "</svg>",
        encoding="utf-8",
    )
    out_path = tmp_path / "native.3mf"
    out_path.write_bytes(b"3mf")
    sid = _test_store.create()
    _test_store.put(sid, "image_path", str(svg_path))
    _test_store.put(sid, "lut_path", "__material_archive__")
    _test_store.put(sid, "material_source", "material_archive")
    _test_store.put(sid, "selected_materials", ["brand/base", "brand/red"])
    _test_store.put(sid, "color_layers", 7)
    _test_store.put(sid, "layer_height_mm", 0.08)
    _test_store.put(sid, "material_dynamic_layer_count_enabled", True)
    _test_store.put(sid, "material_min_layer_count", 5)
    _test_store.put(sid, "material_max_layer_count", 7)
    _test_store.put(sid, "material_delta_e00_tolerance", 0.5)
    _test_store.put(sid, "replacement_regions", [])
    _test_store.put(sid, "free_color_set", set())
    _test_store.put(
        sid,
        "preview_cache",
        {
            "target_w": 40,
            "target_h": 40,
            "target_width_mm": 40.0,
            "color_mode": "4-Color (RYBW)",
            "modeling_mode": "vector",
            "color_layers": 7,
            "layer_height_mm": 0.08,
            "quantize_colors": 48,
            "enable_cleanup": True,
            "hue_weight": 0.0,
            "chroma_gate": 15.0,
            "use_lut_constrained": False,
            "auto_dynamic_range": False,
            "model_enable": False,
            "model_only": False,
            "model_threshold": None,
            "model_margin": None,
            "svg_pixels_per_mm": 10.0,
            "material_source": "material_archive",
            "matched_rgb": np.zeros((40, 40, 3), dtype=np.uint8),
            "mask_solid": np.ones((40, 40), dtype=bool),
            "material_matrix": np.zeros((40, 40, 7), dtype=np.int32),
            "material_dynamic_layer_info": {
                "enabled": True,
                "max_layer_count": 7,
                "colors": [],
            },
        },
    )
    _mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": str(out_path),
            "glb_path": None,
            "status_msg": "ok",
        }
    )

    response = client.post(
        "/api/convert/generate",
        json={
            "session_id": sid,
            "params": {
                "lut_name": "__material_archive__",
                "modeling_mode": "vector",
                "target_width_mm": 40.0,
                "color_layers": 7,
                "material_dynamic_layer_count_enabled": True,
                "material_min_layer_count": 5,
                "material_max_layer_count": 7,
                "material_delta_e00_tolerance": 0.5,
                "use_cached_matched_rgb": True,
            },
        },
    )

    assert response.status_code == 200, response.text
    submitted_params = _mock_pool.submit.call_args.args[3]
    assert submitted_params["material_dynamic_layer_count_enabled"] is True
    assert submitted_params["material_matrix_path"] is not None
    assert submitted_params["quantized_image_path"] is None
    assert submitted_params["reuse_preview_analysis"] == "required"


def test_generate_route_rejects_material_archive_relief_color_height_below_optical_depth(tmp_path) -> None:
    _test_store.clear_all()
    image_path = tmp_path / "input.png"
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)

    session_id = _test_store.create()
    _test_store.put(session_id, "image_path", str(image_path))
    _test_store.put(session_id, "lut_path", "__material_archive__")
    _test_store.put(session_id, "material_source", "material_archive")
    _test_store.put(session_id, "selected_materials", ["mat-a", "mat-b"])
    _test_store.put(session_id, "material_layer_count", 10)
    _test_store.put(session_id, "material_layer_height_mm", 0.08)
    _test_store.put(session_id, "replacement_regions", [])
    _test_store.put(session_id, "free_color_set", set())
    _test_store.put(
        session_id,
        "preview_cache",
        {
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
            "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
            "mask_solid": np.ones((4, 4), dtype=bool),
            "material_matrix": np.zeros((4, 4, 10), dtype=np.uint8),
        },
    )
    _mock_pool.submit = AsyncMock()

    response = client.post(
        "/api/convert/generate",
        json={
            "session_id": session_id,
            "params": {
                "lut_name": "__material_archive__",
                "enable_relief": True,
                "height_mode": "color",
                "color_height_map": {"#111111": 0.6},
                "heightmap_max_height": 0.6,
            },
        },
    )

    assert response.status_code == 422, response.text
    assert "0.80 mm" in response.json()["detail"]
    _mock_pool.submit.assert_not_called()


def test_generate_route_rejects_material_archive_relief_height_below_override_depth(tmp_path) -> None:
    _test_store.clear_all()
    image_path = tmp_path / "input.png"
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)

    session_id = _test_store.create()
    _test_store.put(session_id, "image_path", str(image_path))
    _test_store.put(session_id, "lut_path", "__material_archive__")
    _test_store.put(session_id, "material_source", "material_archive")
    _test_store.put(session_id, "selected_materials", ["mat-a", "mat-b"])
    _test_store.put(session_id, "material_layer_count", 5)
    _test_store.put(session_id, "material_layer_height_mm", 0.08)
    _test_store.put(session_id, "replacement_regions", [])
    _test_store.put(session_id, "free_color_set", set())
    _test_store.put(session_id, "selected_region_masks", {"region-1": np.ones((4, 4), dtype=bool)})
    _test_store.put(
        session_id,
        "preview_cache",
        {
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
            "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
            "mask_solid": np.ones((4, 4), dtype=bool),
            "material_matrix": np.zeros((4, 4, 5), dtype=np.uint8),
        },
    )
    _mock_pool.submit = AsyncMock()

    response = client.post(
        "/api/convert/generate",
        json={
            "session_id": session_id,
            "params": {
                "lut_name": "__material_archive__",
                "color_layers": 10,
                "enable_relief": True,
                "height_mode": "color",
                "color_height_map": {"#111111": 0.6},
                "heightmap_max_height": 0.6,
                "recipe_overrides": [
                    {
                        "region_id": "region-1",
                        "recipe": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
                        "layer_order": "Top2Bottom",
                    },
                ],
            },
        },
    )

    assert response.status_code == 422, response.text
    assert "0.80 mm" in response.json()["detail"]
    _mock_pool.submit.assert_not_called()


def test_generate_route_rejects_material_archive_heightmap_below_optical_depth(tmp_path) -> None:
    _test_store.clear_all()
    image_path = tmp_path / "input.png"
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)

    session_id = _test_store.create()
    _test_store.put(session_id, "image_path", str(image_path))
    _test_store.put(session_id, "lut_path", "__material_archive__")
    _test_store.put(session_id, "material_source", "material_archive")
    _test_store.put(session_id, "selected_materials", ["mat-a", "mat-b"])
    _test_store.put(session_id, "material_layer_count", 10)
    _test_store.put(session_id, "material_layer_height_mm", 0.08)
    _test_store.put(session_id, "replacement_regions", [])
    _test_store.put(session_id, "free_color_set", set())
    _test_store.put(session_id, "heightmap_grayscale", np.zeros((4, 4), dtype=np.uint8))
    _test_store.put(
        session_id,
        "preview_cache",
        {
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
            "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
            "mask_solid": np.ones((4, 4), dtype=bool),
            "material_matrix": np.zeros((4, 4, 10), dtype=np.uint8),
        },
    )
    _mock_pool.submit = AsyncMock()

    response = client.post(
        "/api/convert/generate",
        json={
            "session_id": session_id,
            "params": {
                "lut_name": "__material_archive__",
                "enable_relief": True,
                "height_mode": "heightmap",
                "heightmap_max_height": 0.6,
            },
        },
    )

    assert response.status_code == 422, response.text
    assert "heightmap_max_height" in response.json()["detail"]
    assert "0.80 mm" in response.json()["detail"]
    _mock_pool.submit.assert_not_called()


def test_generate_route_forwards_material_archive_backing_index(tmp_path) -> None:
    _test_store.clear_all()
    image_path = tmp_path / "input.png"
    out_path = tmp_path / "out.3mf"
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
    out_path.write_bytes(b"3mf")

    session_id = _test_store.create()
    _test_store.put(session_id, "image_path", str(image_path))
    _test_store.put(session_id, "lut_path", "__material_archive__")
    _test_store.put(session_id, "material_source", "material_archive")
    _test_store.put(session_id, "selected_materials", ["mat-a", "mat-b", "mat-c"])
    _test_store.put(session_id, "material_layer_count", 5)
    _test_store.put(session_id, "material_layer_height_mm", 0.08)
    _test_store.put(session_id, "material_grid_resolution", 64)
    _test_store.put(session_id, "material_backing_material_index", 1)
    _test_store.put(session_id, "replacement_regions", [])
    _test_store.put(session_id, "free_color_set", set())
    _test_store.put(
        session_id,
        "preview_cache",
        {
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
            "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
            "mask_solid": np.ones((4, 4), dtype=bool),
            "material_matrix": np.zeros((4, 4, 5), dtype=np.uint8),
        },
    )

    _mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": str(out_path),
            "glb_path": None,
            "status_msg": "OK",
        }
    )

    response = client.post(
        "/api/convert/generate",
        json={
            "session_id": session_id,
            "params": {
                "lut_name": "__material_archive__",
                "material_backing_material_index": 2,
            },
        },
    )

    assert response.status_code == 200, response.text
    submitted_params = _mock_pool.submit.call_args.args[3]
    assert submitted_params["material_source"] == "material_archive"
    assert submitted_params["selected_materials"] == ["mat-a", "mat-b", "mat-c"]
    assert submitted_params["material_backing_material_index"] == 2


def _create_material_archive_artifact_generate_session(tmp_path):
    _test_store.clear_all()
    image_path = tmp_path / "input.png"
    out_path = tmp_path / "out.3mf"
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
    out_path.write_bytes(b"3mf")

    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    matched_rgb[:, :, 1] = 66
    mask_solid = np.ones((4, 4), dtype=bool)
    material_matrix = np.zeros((4, 4, 5), dtype=np.uint8)
    material_matrix[:, :, :] = np.array([0, 1, 2, 1, 0], dtype=np.uint8)

    session_id = _test_store.create()
    cache_ref = externalize_preview_cache(
        session_id,
        _test_store,
        {
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
            "matched_rgb": matched_rgb,
            "mask_solid": mask_solid,
            "material_matrix": material_matrix,
        },
        root_dir=tmp_path,
    )
    _test_store.put(session_id, "image_path", str(image_path))
    _test_store.put(session_id, "lut_path", "__material_archive__")
    _test_store.put(session_id, "material_source", "material_archive")
    _test_store.put(
        session_id,
        "selected_materials",
        ["mat-red", "mat-blue", "mat-white"],
    )
    _test_store.put(session_id, "material_layer_count", 5)
    _test_store.put(session_id, "material_layer_height_mm", 0.08)
    _test_store.put(session_id, "replacement_regions", [])
    _test_store.put(session_id, "free_color_set", set())
    _test_store.put(session_id, "preview_cache", cache_ref)

    return session_id, cache_ref, out_path


def test_generate_route_reuses_material_archive_preview_cache_for_hifi(tmp_path) -> None:
    """Material-archive high-fidelity generation must reuse preview analysis.

    The material solver can choose a different stack on a second pass. Final
    3MF generation therefore needs the same matched RGB and material matrix
    that powered the accepted preview, not a fresh solve.
    """
    _test_store.clear_all()
    image_path = tmp_path / "input.png"
    out_path = tmp_path / "out.3mf"
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
    out_path.write_bytes(b"3mf")

    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    matched_rgb[:, :, 0] = 33
    mask_solid = np.ones((4, 4), dtype=bool)
    material_matrix = np.zeros((4, 4, 5), dtype=np.uint8)
    material_matrix[:, :, :] = np.array([0, 1, 2, 1, 0], dtype=np.uint8)

    session_id = _test_store.create()
    _test_store.put(session_id, "image_path", str(image_path))
    _test_store.put(session_id, "lut_path", "__material_archive__")
    _test_store.put(session_id, "material_source", "material_archive")
    _test_store.put(
        session_id,
        "selected_materials",
        ["mat-red", "mat-blue", "mat-white"],
    )
    _test_store.put(session_id, "material_layer_count", 5)
    _test_store.put(session_id, "material_layer_height_mm", 0.08)
    _test_store.put(session_id, "replacement_regions", [])
    _test_store.put(session_id, "free_color_set", set())
    _test_store.put(
        session_id,
        "preview_cache",
        {
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
            "matched_rgb": matched_rgb,
            "mask_solid": mask_solid,
            "material_matrix": material_matrix,
        },
    )

    _mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": str(out_path),
            "glb_path": None,
            "status_msg": "OK",
        }
    )

    response = client.post(
        "/api/convert/generate",
        json={
            "session_id": session_id,
            "params": {
                "lut_name": "__material_archive__",
                "modeling_mode": "high-fidelity",
            },
        },
    )

    assert response.status_code == 200, response.text
    submitted_params = _mock_pool.submit.call_args.args[3]
    assert submitted_params["matched_rgb_path"] is not None
    assert submitted_params["mask_solid_path"] is not None
    assert submitted_params["material_matrix_path"] is not None
    np.testing.assert_array_equal(
        np.load(submitted_params["matched_rgb_path"]),
        matched_rgb,
    )
    np.testing.assert_array_equal(
        np.load(submitted_params["mask_solid_path"]),
        mask_solid,
    )
    np.testing.assert_array_equal(
        np.load(submitted_params["material_matrix_path"]),
        material_matrix,
    )


def test_generate_route_reuses_material_archive_artifact_cache_for_hifi(tmp_path) -> None:
    session_id, cache_ref, out_path = _create_material_archive_artifact_generate_session(tmp_path)

    _mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": str(out_path),
            "glb_path": None,
            "status_msg": "OK",
        }
    )

    response = client.post(
        "/api/convert/generate",
        json={
            "session_id": session_id,
            "params": {
                "lut_name": "__material_archive__",
                "modeling_mode": "high-fidelity",
            },
        },
    )

    assert response.status_code == 200, response.text
    submitted_params = _mock_pool.submit.call_args.args[3]
    assert submitted_params["matched_rgb_path"] == cache_ref["fields"]["matched_rgb"]["path"]
    assert submitted_params["mask_solid_path"] == cache_ref["fields"]["mask_solid"]["path"]
    assert submitted_params["material_matrix_path"] == cache_ref["fields"]["material_matrix"]["path"]


def test_generate_route_rejects_material_archive_missing_artifact_field(tmp_path) -> None:
    session_id, cache_ref, out_path = _create_material_archive_artifact_generate_session(tmp_path)
    cache_ref["fields"].pop("mask_solid")
    _test_store.put(session_id, "preview_cache", cache_ref)
    _mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": str(out_path),
            "glb_path": None,
            "status_msg": "OK",
        }
    )

    response = client.post(
        "/api/convert/generate",
        json={
            "session_id": session_id,
            "params": {
                "lut_name": "__material_archive__",
                "modeling_mode": "high-fidelity",
            },
        },
    )

    assert response.status_code == 409
    assert "mask_solid" in response.json()["detail"]
    assert "Re-run preview" in response.json()["detail"]
    _mock_pool.submit.assert_not_called()


def test_generate_route_rejects_material_archive_missing_artifact_file(tmp_path) -> None:
    session_id, cache_ref, out_path = _create_material_archive_artifact_generate_session(tmp_path)
    os.remove(cache_ref["fields"]["matched_rgb"]["path"])
    _mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": str(out_path),
            "glb_path": None,
            "status_msg": "OK",
        }
    )

    response = client.post(
        "/api/convert/generate",
        json={
            "session_id": session_id,
            "params": {
                "lut_name": "__material_archive__",
                "modeling_mode": "high-fidelity",
            },
        },
    )

    assert response.status_code == 409
    assert "matched_rgb artifact" in response.json()["detail"]
    assert "Re-run preview" in response.json()["detail"]
    _mock_pool.submit.assert_not_called()


def test_generate_route_rejects_material_archive_corrupt_artifact_file(tmp_path) -> None:
    session_id, cache_ref, out_path = _create_material_archive_artifact_generate_session(tmp_path)
    with open(cache_ref["fields"]["material_matrix"]["path"], "w", encoding="utf-8") as f:
        f.write("not a numpy array")
    _mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": str(out_path),
            "glb_path": None,
            "status_msg": "OK",
        }
    )

    response = client.post(
        "/api/convert/generate",
        json={
            "session_id": session_id,
            "params": {
                "lut_name": "__material_archive__",
                "modeling_mode": "high-fidelity",
            },
        },
    )

    assert response.status_code == 409
    assert "material_matrix artifact" in response.json()["detail"]
    assert "Re-run preview" in response.json()["detail"]
    _mock_pool.submit.assert_not_called()


def test_generate_route_forwards_cache_recovered_virtual_materials(tmp_path) -> None:
    """The actual /generate route must pass recovered virtuals to the worker."""
    _test_store.clear_all()
    image_path = tmp_path / "input.png"
    lut_path = tmp_path / "source.msgpack"
    out_path = tmp_path / "out.3mf"
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
    lut_path.write_bytes(b"lut")
    out_path.write_bytes(b"3mf")

    session_id = _test_store.create()
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    _test_store.put(session_id, "image_path", str(image_path))
    _test_store.put(session_id, "lut_path", str(lut_path))
    _test_store.put(session_id, "replacement_regions", [])
    _test_store.put(session_id, "free_color_set", set())
    _test_store.put(session_id, "selected_region_masks", {"region-1": mask})
    _test_store.put(
        session_id,
        "preview_cache",
        {
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
            "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
            "mask_solid": np.ones((4, 4), dtype=bool),
            "material_matrix": np.zeros((4, 4, 5), dtype=np.uint8),
            "lut_metadata": SimpleNamespace(
                layer_order="Top2Bottom",
                base_channel_idx=0,
                palette=[object(), object(), object(), object()],
            ),
            "slot_names": ["White", "Cyan", "Magenta", "Yellow", "Black"],
            "preview_colors": {
                0: [245, 245, 245, 255],
                1: [0, 183, 235, 255],
                2: [230, 0, 126, 255],
                3: [255, 212, 0, 255],
                4: [17, 17, 17, 255],
            },
        },
    )

    _mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": str(out_path),
            "glb_path": None,
            "status_msg": "OK",
        }
    )

    response = client.post(
        "/api/convert/generate",
        json={
            "session_id": session_id,
            "params": {
                "lut_name": "test_lut",
                "color_layers": 7,
                "recipe_overrides": [
                    {
                        "region_id": "region-1",
                        "recipe": [4, 4, 4, 4, 4, 4, 4],
                        "layer_order": "Top2Bottom",
                    }
                ],
            },
        },
    )

    assert response.status_code == 200, response.text
    submitted_params = _mock_pool.submit.call_args.args[3]
    assert submitted_params["recipe_overrides"] == [
        {
            "region_id": "region-1",
            "recipe": [4, 4, 4, 4, 4, 4, 4],
            "layer_order": "Top2Bottom",
            "virtual_materials": [{"name": "Black", "hex": "#111111"}],
        }
    ]
    assert submitted_params["material_matrix_path"] is not None
    material_matrix = np.load(submitted_params["material_matrix_path"])
    assert material_matrix.shape == (4, 4, 7)
    assert np.all(material_matrix[mask] == np.array([4, 4, 4, 4, 4, 4, 4]))


def test_generate_route_recovers_select_all_recipe_override_mask(tmp_path) -> None:
    """Select-all recipe overrides must not require a pre-persisted region mask."""
    _test_store.clear_all()
    image_path = tmp_path / "input.png"
    out_path = tmp_path / "out.3mf"
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
    out_path.write_bytes(b"3mf")

    session_id = _test_store.create()
    target_rgb = np.array([0x89, 0x47, 0x35], dtype=np.uint8)
    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    matched_rgb[0, 0] = target_rgb
    matched_rgb[1, 1] = target_rgb
    matched_rgb[2, 2] = np.array([0x20, 0x20, 0x20], dtype=np.uint8)
    expected_mask = np.zeros((4, 4), dtype=bool)
    expected_mask[0, 0] = True
    expected_mask[1, 1] = True

    _test_store.put(session_id, "image_path", str(image_path))
    _test_store.put(session_id, "lut_path", "__material_archive__")
    _test_store.put(session_id, "material_source", "material_archive")
    _test_store.put(
        session_id,
        "selected_materials",
        ["mat-black", "mat-cyan", "mat-yellow", "mat-white", "mat-red"],
    )
    _test_store.put(session_id, "material_layer_count", 7)
    _test_store.put(session_id, "material_layer_height_mm", 0.08)
    _test_store.put(session_id, "replacement_regions", [])
    _test_store.put(session_id, "free_color_set", set())
    _test_store.put(
        session_id,
        "preview_cache",
        {
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
            "matched_rgb": matched_rgb,
            "mask_solid": np.ones((4, 4), dtype=bool),
            "material_matrix": np.zeros((4, 4, 7), dtype=np.uint8),
            "slot_names": ["Black", "Cyan", "Yellow", "White", "Red"],
            "preview_colors": {
                0: [16, 16, 16, 255],
                1: [0, 183, 235, 255],
                2: [255, 212, 0, 255],
                3: [245, 245, 245, 255],
                4: [220, 20, 60, 255],
            },
        },
    )

    _mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": str(out_path),
            "glb_path": None,
            "status_msg": "OK",
        }
    )

    response = client.post(
        "/api/convert/generate",
        json={
            "session_id": session_id,
            "params": {
                "lut_name": "__material_archive__",
                "modeling_mode": "vector",
                "target_width_mm": 113,
                "spacer_thick": 0.24,
                "structure_mode": "Single-sided",
                "color_layers": 7,
                "layer_height_mm": 0.08,
                "separate_backing": True,
                "recipe_overrides": [
                    {
                        "region_id": "__select_all_color__:894735",
                        "recipe": [4, 4, 4, 4, 4, 4, 4],
                        "layer_order": "Top2Bottom",
                    }
                ],
            },
        },
    )

    assert response.status_code == 200, response.text
    submitted_params = _mock_pool.submit.call_args.args[3]
    assert submitted_params["recipe_override_masks_path"] is not None
    with open(submitted_params["recipe_override_masks_path"], "rb") as f:
        masks = pickle.load(f)
    assert masks.keys() == {"__select_all_color__:894735"}
    assert np.array_equal(masks["__select_all_color__:894735"], expected_mask)

    material_matrix = np.load(submitted_params["material_matrix_path"])
    assert np.all(material_matrix[expected_mask] == np.array([4, 4, 4, 4, 4, 4, 4]))
    assert np.all(material_matrix[2, 2] == np.zeros(7, dtype=np.uint8))


def test_generate_route_recovers_select_all_recipe_override_mask_from_artifact_cache(tmp_path) -> None:
    _test_store.clear_all()
    image_path = tmp_path / "input.png"
    out_path = tmp_path / "out.3mf"
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
    out_path.write_bytes(b"3mf")

    session_id = _test_store.create()
    target_rgb = np.array([0x89, 0x47, 0x35], dtype=np.uint8)
    matched_rgb = np.zeros((4, 4, 3), dtype=np.uint8)
    matched_rgb[0, 0] = target_rgb
    matched_rgb[1, 1] = target_rgb
    expected_mask = np.zeros((4, 4), dtype=bool)
    expected_mask[0, 0] = True
    expected_mask[1, 1] = True
    cache_ref = externalize_preview_cache(
        session_id,
        _test_store,
        {
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
            "matched_rgb": matched_rgb,
            "mask_solid": np.ones((4, 4), dtype=bool),
            "material_matrix": np.zeros((4, 4, 7), dtype=np.uint8),
            "slot_names": ["Black", "Cyan", "Yellow", "White", "Red"],
            "preview_colors": {
                0: [16, 16, 16, 255],
                1: [0, 183, 235, 255],
                2: [255, 212, 0, 255],
                3: [245, 245, 245, 255],
                4: [220, 20, 60, 255],
            },
        },
        root_dir=tmp_path,
    )

    _test_store.put(session_id, "image_path", str(image_path))
    _test_store.put(session_id, "lut_path", "__material_archive__")
    _test_store.put(session_id, "material_source", "material_archive")
    _test_store.put(
        session_id,
        "selected_materials",
        ["mat-black", "mat-cyan", "mat-yellow", "mat-white", "mat-red"],
    )
    _test_store.put(session_id, "material_layer_count", 7)
    _test_store.put(session_id, "material_layer_height_mm", 0.08)
    _test_store.put(session_id, "replacement_regions", [])
    _test_store.put(session_id, "free_color_set", set())
    _test_store.put(session_id, "preview_cache", cache_ref)

    _mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": str(out_path),
            "glb_path": None,
            "status_msg": "OK",
        }
    )

    from api.preview_cache_artifacts import hydrate_preview_cache as real_hydrate_preview_cache

    hydrate_fields: list[frozenset[str]] = []

    def _tracking_hydrate(cache_ref_arg, *, fields=None, mmap_mode=None):
        hydrate_fields.append(frozenset(fields or ()))
        return real_hydrate_preview_cache(cache_ref_arg, fields=fields, mmap_mode=mmap_mode)

    with patch("api.routers.converter.generate.hydrate_preview_cache", side_effect=_tracking_hydrate):
        response = client.post(
            "/api/convert/generate",
            json={
                "session_id": session_id,
                "params": {
                    "lut_name": "__material_archive__",
                    "modeling_mode": "vector",
                    "target_width_mm": 113,
                    "spacer_thick": 0.24,
                    "structure_mode": "Single-sided",
                    "color_layers": 7,
                    "layer_height_mm": 0.08,
                    "separate_backing": True,
                    "recipe_overrides": [
                        {
                            "region_id": "__select_all_color__:894735",
                            "recipe": [4, 4, 4, 4, 4, 4, 4],
                            "layer_order": "Top2Bottom",
                        }
                    ],
                },
            },
        )

    assert response.status_code == 200, response.text
    assert frozenset({"material_matrix"}) in hydrate_fields
    assert frozenset({"matched_rgb"}) in hydrate_fields
    assert frozenset({"mask_solid"}) in hydrate_fields
    assert frozenset() not in hydrate_fields

    submitted_params = _mock_pool.submit.call_args.args[3]
    with open(submitted_params["recipe_override_masks_path"], "rb") as f:
        masks = pickle.load(f)
    assert np.array_equal(masks["__select_all_color__:894735"], expected_mask)


def test_generate_route_rejects_stale_recipe_override_artifact_cache(tmp_path) -> None:
    _test_store.clear_all()
    image_path = tmp_path / "input.png"
    lut_path = tmp_path / "source.msgpack"
    out_path = tmp_path / "out.3mf"
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
    lut_path.write_bytes(b"lut")
    out_path.write_bytes(b"3mf")

    session_id = _test_store.create()
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    cache_ref = externalize_preview_cache(
        session_id,
        _test_store,
        {
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
            "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
            "mask_solid": np.ones((4, 4), dtype=bool),
            "material_matrix": np.zeros((4, 4, 5), dtype=np.uint8),
            "lut_metadata": SimpleNamespace(
                layer_order="Top2Bottom",
                base_channel_idx=0,
                palette=[object(), object(), object(), object()],
            ),
        },
        root_dir=tmp_path,
    )
    stale_material_matrix_path = cache_ref["fields"]["material_matrix"]["path"]
    os.remove(stale_material_matrix_path)

    _test_store.put(session_id, "image_path", str(image_path))
    _test_store.put(session_id, "lut_path", str(lut_path))
    _test_store.put(session_id, "replacement_regions", [])
    _test_store.put(session_id, "free_color_set", set())
    _test_store.put(session_id, "selected_region_masks", {"region-1": mask})
    _test_store.put(session_id, "preview_cache", cache_ref)
    _mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": str(out_path),
            "glb_path": None,
            "status_msg": "OK",
        }
    )

    response = client.post(
        "/api/convert/generate",
        json={
            "session_id": session_id,
            "params": {
                "lut_name": "test_lut",
                "color_layers": 5,
                "recipe_overrides": [
                    {
                        "region_id": "region-1",
                        "recipe": [1, 1, 1, 1, 1],
                        "layer_order": "Top2Bottom",
                    }
                ],
            },
        },
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "material_matrix artifact" in detail
    assert "Re-run preview" in detail
    assert stale_material_matrix_path not in detail
    _mock_pool.submit.assert_not_called()


def test_generate_route_preserves_session_recipe_overrides_when_request_is_empty(tmp_path) -> None:
    """A stale empty request must not erase an already-applied recipe.

    ``/apply-recipe-override`` persists the effective overrides in the
    session before generation. The frontend can still send an empty local
    array when that state is stale; generation must keep the session override
    so the worker receives a material_matrix_path and exports the edited 3MF.

    ``/apply-recipe-override`` 已经把生效配方写入 session；前端局部状态
    陈旧时仍可能发空数组。生成端必须继续使用 session 里的覆盖，否则
    3MF 会悄悄回到原始配方。
    """
    _test_store.clear_all()
    image_path = tmp_path / "input.png"
    lut_path = tmp_path / "source.msgpack"
    out_path = tmp_path / "out.3mf"
    Image.fromarray(np.zeros((4, 4, 3), dtype=np.uint8)).save(image_path)
    lut_path.write_bytes(b"lut")
    out_path.write_bytes(b"3mf")

    session_id = _test_store.create()
    mask = np.zeros((4, 4), dtype=bool)
    mask[1:3, 1:3] = True
    _test_store.put(session_id, "image_path", str(image_path))
    _test_store.put(session_id, "lut_path", str(lut_path))
    _test_store.put(session_id, "replacement_regions", [])
    _test_store.put(session_id, "free_color_set", set())
    _test_store.put(session_id, "selected_region_masks", {"region-1": mask})
    _test_store.put(
        session_id,
        "recipe_overrides",
        [
            {
                "region_id": "region-1",
                "recipe": [1, 1, 1, 1, 1],
                "layer_order": "Top2Bottom",
                "color_layers": 5,
                "actual_recipe_top_to_bottom": [1, 1, 1, 1, 1],
                "print_recipe_top_to_bottom": [1, 1, 1, 1, 1, 2, 2],
                "actual_layer_count": 5,
                "padding_layer_count": 2,
            }
        ],
    )
    material_matrix = np.zeros((4, 4, 7), dtype=np.uint8)
    material_matrix[mask] = np.asarray([1, 1, 1, 1, 1, 2, 2], dtype=np.uint8)
    _test_store.put(
        session_id,
        "preview_cache",
        {
            "target_w": 4,
            "target_h": 4,
            "target_width_mm": 40.0,
            "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
            "mask_solid": np.ones((4, 4), dtype=bool),
            "material_matrix": material_matrix,
            "lut_metadata": SimpleNamespace(
                layer_order="Top2Bottom",
                base_channel_idx=0,
                palette=[object(), object(), object(), object()],
            ),
        },
    )

    _mock_pool.submit = AsyncMock(
        return_value={
            "threemf_path": str(out_path),
            "glb_path": None,
            "status_msg": "OK",
        }
    )

    response = client.post(
        "/api/convert/generate",
        json={
            "session_id": session_id,
            "params": {
                "lut_name": "test_lut",
                "color_layers": 7,
                "recipe_overrides": [],
            },
        },
    )

    assert response.status_code == 200, response.text
    submitted_params = _mock_pool.submit.call_args.args[3]
    assert submitted_params["recipe_overrides"] == [
        {
            "region_id": "region-1",
            "recipe": [1, 1, 1, 1, 1],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "actual_recipe_top_to_bottom": [1, 1, 1, 1, 1],
            "print_recipe_top_to_bottom": [1, 1, 1, 1, 1, 2, 2],
            "actual_layer_count": 5,
            "padding_layer_count": 2,
        }
    ]
    material_matrix = np.load(submitted_params["material_matrix_path"])
    assert material_matrix.shape == (4, 4, 7)


def test_large_format_worker_params_preserve_normalized_dynamic_recipe_metadata() -> None:
    raw_overrides = [
        {
            "region_id": "region-1",
            "recipe": [1, 1, 1, 1, 1],
            "layer_order": "Top2Bottom",
            "color_layers": 5,
            "actual_recipe_top_to_bottom": [1, 1, 1, 1, 1],
            "print_recipe_top_to_bottom": [1, 1, 1, 1, 1, 2, 2],
            "actual_layer_count": 5,
            "padding_layer_count": 2,
        }
    ]
    normalized = _normalize_recipe_overrides(raw_overrides)
    request = LargeFormatConvertGenerateRequest(
        lut_name="test_lut",
        color_layers=7,
    )

    worker_params = _resolve_large_format_shared_params(
        {"replacement_regions": [], "free_color_set": set()},
        request,
        None,
        recipe_overrides=normalized,
    )

    assert worker_params["recipe_overrides"] == raw_overrides


def test_resolve_recipe_overrides_prefers_request_virtual_materials_when_provided() -> None:
    """When both request and session carry virtuals for the same region, request wins.

    新前端会在 apply 后把 virtual_materials 一起存进 store，generate 时随
    recipe_overrides 再发一遍。此时请求体是事实来源，resolver 不得用 session
    的版本覆盖掉用户最新的虚拟耗材声明。
    """
    session_data = {
        "recipe_overrides": [
            {
                "region_id": "region-1",
                "recipe": [4, 0, 0, 0, 0, 4],
                "layer_order": "Top2Bottom",
                "virtual_materials": [{"name": "Black", "hex": "#000000"}],
            }
        ]
    }
    request = ConvertGenerateRequest(
        lut_name="test-lut",
        recipe_overrides=[
            {
                "region_id": "region-1",
                "recipe": [4, 0, 0, 0, 0, 4],
                "layer_order": "Top2Bottom",
                "virtual_materials": [{"name": "Crimson", "hex": "#DC143C"}],
            }
        ],
    )

    resolved = _resolve_recipe_overrides(session_data, request)

    assert resolved is not None
    assert resolved[0]["virtual_materials"] == [
        {"name": "Crimson", "hex": "#DC143C"}
    ]


def test_resolve_recipe_overrides_keeps_other_region_virtuals_untouched() -> None:
    """Backfill must be scoped by region_id, not applied globally.

    region-1 带了 virtuals、region-2 没带时，resolver 只应为 region-2 从 session
    回补对应的 virtuals；不应把 region-1 的 virtuals 覆盖或跨 region 乱涂。
    """
    session_data = {
        "recipe_overrides": [
            {
                "region_id": "region-1",
                "recipe": [4, 0, 0, 0, 0, 4],
                "layer_order": "Top2Bottom",
                "virtual_materials": [{"name": "Black", "hex": "#000000"}],
            },
            {
                "region_id": "region-2",
                "recipe": [5, 0, 0, 0, 0, 5],
                "layer_order": "Top2Bottom",
                "virtual_materials": [{"name": "Red", "hex": "#FF0000"}],
            },
        ]
    }
    request = ConvertGenerateRequest(
        lut_name="test-lut",
        recipe_overrides=[
            {
                "region_id": "region-1",
                "recipe": [4, 0, 0, 0, 0, 4],
                "layer_order": "Top2Bottom",
                "virtual_materials": [{"name": "Black", "hex": "#111111"}],
            },
            {
                "region_id": "region-2",
                "recipe": [5, 0, 0, 0, 0, 5],
                "layer_order": "Top2Bottom",
                # Missing virtuals — must be backfilled from session["region-2"].
            },
        ],
    )

    resolved = _resolve_recipe_overrides(session_data, request)

    assert resolved is not None
    by_region = {item["region_id"]: item for item in resolved}
    assert by_region["region-1"]["virtual_materials"] == [
        {"name": "Black", "hex": "#111111"}
    ]
    assert by_region["region-2"]["virtual_materials"] == [
        {"name": "Red", "hex": "#FF0000"}
    ]


class TestUserSettingsBaseLayerModifierCompatibility:
    """Verify persisted user settings keep the new base-layer flag compatible."""

    def test_user_settings_default_enables_base_layer_modifier(self) -> None:
        settings = UserSettings()

        assert settings.enable_base_layer_height_modifier is True

    def test_user_settings_accepts_missing_base_layer_modifier_key(self) -> None:
        settings = UserSettings(
            **{
                "printer_model": "bambu-h2d",
                "slicer_software": "BambuStudio",
                "nozzle_size": "0.4",
            }
        )

        assert settings.enable_base_layer_height_modifier is True

    def test_user_settings_roundtrip_preserves_base_layer_modifier_false(self) -> None:
        payload = {
            "last_lut": "",
            "last_modeling_mode": "high-fidelity",
            "last_color_mode": "4-Color (RYBW)",
            "last_slicer": "",
            "palette_mode": "swatch",
            "enable_crop_modal": True,
            "printer_model": "bambu-h2d",
            "slicer_software": "BambuStudio",
            "nozzle_size": "0.4",
            "enable_base_layer_height_modifier": False,
        }
        mock_file = MagicMock()
        mock_file.exists.return_value = True
        mock_file.read_text.return_value = json.dumps(payload)

        with patch("api.routers.system.SETTINGS_FILE", mock_file):
            post_response = client.post("/api/system/settings", json=payload)
            get_response = client.get("/api/system/settings")

        assert post_response.status_code == 200
        written_payload = json.loads(mock_file.write_text.call_args.args[0])
        assert written_payload["enable_base_layer_height_modifier"] is False
        assert get_response.status_code == 200
        assert get_response.json()["settings"]["enable_base_layer_height_modifier"] is False


class TestConverterEntryAcceptsBaseLayerModifierKwarg:
    """Contract tests: the ctx key plumbed by the /api/convert/generate router
    must be accepted by every downstream entry point that is called via
    ``**kwargs`` with the router ``params`` dict, otherwise the worker process
    raises ``TypeError`` and the API returns a generic 500.

    契约测试：/api/convert/generate 路由组装的 ctx 键必须被每一个通过 ``**kwargs``
    消费 params 字典的下游入口接受，否则 worker 进程抛 ``TypeError``，API 返回 500。
    """

    def test_generate_final_model_signature_accepts_enable_base_layer_modifier(self) -> None:
        import inspect

        from core.converter import generate_final_model

        params = inspect.signature(generate_final_model).parameters
        assert "enable_base_layer_height_modifier" in params
        assert params["enable_base_layer_height_modifier"].default is True

    def test_convert_image_to_3d_signature_accepts_enable_base_layer_modifier(self) -> None:
        import inspect

        from core.converter import convert_image_to_3d

        params = inspect.signature(convert_image_to_3d).parameters
        assert "enable_base_layer_height_modifier" in params
        assert params["enable_base_layer_height_modifier"].default is True

    def test_converter_signatures_accept_wipe_tower_auto_placement(self) -> None:
        import inspect

        from core.converter import convert_image_to_3d, generate_final_model

        for entry_point in (convert_image_to_3d, generate_final_model):
            params = inspect.signature(entry_point).parameters
            assert "enable_wipe_tower_auto_placement" in params
            assert params["enable_wipe_tower_auto_placement"].default is True

    def test_convert_image_to_3d_signature_accepts_material_backing_index(self) -> None:
        import inspect

        from core.converter import convert_image_to_3d

        params = inspect.signature(convert_image_to_3d).parameters
        assert "material_backing_material_index" in params
        assert params["material_backing_material_index"].default is None
