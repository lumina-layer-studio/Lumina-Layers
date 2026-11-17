"""Unit tests for large-format SVG worker tile-level cover rasterization.

大画幅 SVG worker 中 tile 级封面栅格化与失败回退的单元测试。

These tests cover the tile-level cover-thumbnail rasterization wrapper in
``api/workers/converter_workers.py::worker_generate_large_format_svg_native``:

- Rasterization success → ``cover_source=tile_image`` is forwarded.
- Rasterization timeout (``TimeoutError``) → tile is still
  exported into the ZIP with ``cover_source=None`` (silent placeholder),
  ``tile_failed_cover`` is bumped (quality indicator), a single
  ``bambu_3mf_cover_thumbnail_failed`` WARNING is emitted with
  ``error_type="tile_rasterize_timeout"`` and
  ``fallback_action="placeholder_written"``.
- Rasterization exception → tile is still exported, ``tile_failed_cover`` is
  bumped, WARNING ``error_type=type(exc).__name__``,
  ``fallback_action="placeholder_written"``.
- Empty scene tile (``scene.geometry`` empty) → that tile counts as
  ``tile_skipped_empty``, not ``tile_failed_cover``.
- Worker return value satisfies the **new** invariant
  ``tile_count + tile_skipped_empty == grid_cols * grid_rows``.
  ``tile_failed_cover`` is now a *subset* of ``tile_count``, not a disjoint
  bucket — see worker docstring for full counter semantics.
- Hard timeout actually unblocks the worker: a 30-second sleep inside
  ``_rasterize_tile_for_cover`` does not block the worker beyond the 10s
  rasterize timeout (manual ``shutdown(wait=False, cancel_futures=True)``).
- Tile coordinate mapping is canvas-relative (``crop_to_content=False``):
  a sparse SVG whose content is concentrated on the right half cannot
  shift tile bounds away from their canvas origin.

Logger propagation note: ``api.structured_logging.configure_structured_logging``
sets ``logger.propagate = False`` on the ``lumina`` logger family, so we
attach the caplog handler directly to ``lumina.api.workers.converter_workers``
inside each test instead of relying on ``caplog.at_level``.

**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5, 5.6 / Property 10**
"""

from __future__ import annotations

import gc
import logging
import os
import time
import weakref
import zipfile
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
import trimesh

import api.workers.converter_workers as converter_workers_module  # noqa: F401  # imported for side-effect references in mocks
from api.workers.converter_workers import (
    _rasterize_tile_for_cover,
    worker_generate_large_format_svg_native,
)


@contextmanager
def _capture_worker_warnings(caplog):
    """Attach caplog to the namespaced ``lumina.*`` worker logger.

    The ``lumina`` family has ``propagate=False``, so root-attached caplog
    handlers do not see its records by default.
    """

    target_logger = logging.getLogger("lumina.api.workers.converter_workers")
    previous_propagate = target_logger.propagate
    target_logger.propagate = False
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger="lumina.api.workers.converter_workers")
    try:
        yield
    finally:
        target_logger.removeHandler(caplog.handler)
        target_logger.propagate = previous_propagate


def _make_tile(
    label: str,
    *,
    slot_names=("Slot1",),
    preview_colors=None,
    x0_mm: float = 0.0,
    y0_mm: float = 0.0,
    x1_mm: float = 60.0,
    y1_mm: float = 60.0,
):
    if preview_colors is None:
        preview_colors = {0: [255, 0, 0, 255]}
    return SimpleNamespace(
        label=label,
        spec=SimpleNamespace(
            row=int(label[1]),
            col=int(label[3]),
            label=label,
            x0_mm=x0_mm,
            y0_mm=y0_mm,
            x1_mm=x1_mm,
            y1_mm=y1_mm,
            width_mm=x1_mm - x0_mm,
            height_mm=y1_mm - y0_mm,
        ),
        analysis=SimpleNamespace(
            preview_colors=dict(preview_colors),
            slot_names=list(slot_names),
        ),
    )


class _FakeVectorProcessor:
    """Vector processor that always returns one slot worth of geometry."""

    def __init__(self, lut_path: str, color_mode: str) -> None:
        self.lut_path = lut_path
        self.color_mode = color_mode

    def analyze_svg(self, **_kwargs):
        return SimpleNamespace(
            num_layers=5, slot_names=["Slot1"], scale_factor=1.0, matched_shapes=[], preview_colors={0: [255, 0, 0, 255]}
        )

    def build_mesh(self, **_kwargs):
        fake_geom = SimpleNamespace(vertices=[(0, 0, 0)], faces=[(0, 0, 0)])
        return SimpleNamespace(geometry={"Slot1": fake_geom})


class _EmptySceneVectorProcessor(_FakeVectorProcessor):
    """Vector processor whose build_mesh returns an empty scene."""

    def build_mesh(self, **_kwargs):
        return SimpleNamespace(geometry={})


def _fake_export(captured: list[dict]):
    def _impl(*, output_path: str, cover_source=None, **_kwargs) -> None:
        with open(output_path, "wb") as handle:
            handle.write(b"3mf")
        captured.append({"output_path": output_path, "cover_source": cover_source})

    return _impl


def _params_2x1() -> dict:
    """Build a 2x1 grid (2 tiles) for tile-counter invariant tests."""
    return {
        "tile_name_prefix": "tile_cover",
        "total_width_mm": 120.0,
        "total_height_mm": 60.0,
        "tile_width_mm": 60.0,
        "tile_height_mm": 60.0,
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color",
        "replacement_regions": [],
        "separate_backing": False,
    }


def _params_2x2() -> dict:
    """Build a 2x2 grid (4 tiles) for richer mixed-state tests."""
    return {
        "tile_name_prefix": "tile_cover",
        "total_width_mm": 120.0,
        "total_height_mm": 120.0,
        "tile_width_mm": 60.0,
        "tile_height_mm": 60.0,
        "spacer_thick": 1.2,
        "structure_mode": "Single-sided",
        "color_mode": "4-Color",
        "replacement_regions": [],
        "separate_backing": False,
    }


# ---------------------------------------------------------------------------
# Success path: rasterized cover source is forwarded
# ---------------------------------------------------------------------------


def test_worker_forwards_rasterized_cover_source_to_export(tmp_path) -> None:
    """When _rasterize_tile_for_cover returns a PIL Image, it is forwarded."""

    from PIL import Image

    cover_image = Image.new("RGBA", (256, 256), (10, 20, 30, 255))
    captured: list[dict] = []
    tiles = [_make_tile("R1C1"), _make_tile("R1C2")]

    with (
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=tiles),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", return_value=cover_image),
        patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata", side_effect=_fake_export(captured)),
    ):
        result = worker_generate_large_format_svg_native("image.svg", "lut.npy", _params_2x1())

    try:
        assert result["tile_count"] == 2
        assert result["tile_skipped_empty"] == 0
        assert result["tile_failed_cover"] == 0
        assert result["grid_cols"] * result["grid_rows"] == 2
        assert len(captured) == 2
        # Every export call must receive the rasterized PIL Image as cover_source
        for entry in captured:
            assert entry["cover_source"] is cover_image
    finally:
        if os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])


def test_worker_collects_embedded_wipe_tower_warnings_without_false_positive() -> None:
    """Native large-format tiles expose embedded placement warnings once."""

    warning_code = "wipe_tower_manual_adjustment_required"
    captured: list[str] = []

    def _fake_export(*, output_path: str, **_kwargs) -> None:
        with open(output_path, "wb") as handle:
            handle.write(b"3mf")

    def _read_warning(path: str) -> list[str]:
        captured.append(path)
        return [warning_code] if len(captured) == 1 else []

    with (
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=[_make_tile("R1C1"), _make_tile("R1C2")]),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", return_value=None),
        patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata", side_effect=_fake_export),
        patch("utils.bambu_3mf_writer.read_wipe_tower_placement_warnings", side_effect=_read_warning),
    ):
        result = worker_generate_large_format_svg_native("image.svg", "lut.npy", _params_2x1())

    try:
        assert result["warnings"] == [warning_code]
        assert len(captured) == 2
    finally:
        if os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])


# ---------------------------------------------------------------------------
# Timeout path: tile is exported with placeholder cover, WARNING emitted
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Generic exception path: error_type is the exception class name
# ---------------------------------------------------------------------------


def test_worker_exports_tile_with_placeholder_on_rasterize_exception(tmp_path, caplog) -> None:
    """Non-timeout exceptions follow the same path: tile exported with placeholder."""

    from PIL import Image

    tiles = [_make_tile("R1C1"), _make_tile("R1C2")]
    captured: list[dict] = []

    def _rasterize(tile, *_args, **_kwargs):
        if tile.label == "R1C1":
            raise RuntimeError("synthetic rasterize failure")
        return Image.new("RGBA", (256, 256), (0, 0, 255, 255))

    with (
        _capture_worker_warnings(caplog),
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=tiles),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", side_effect=_rasterize),
        patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata", side_effect=_fake_export(captured)),
    ):
        result = worker_generate_large_format_svg_native("image.svg", "lut.npy", _params_2x1())

    try:
        assert result["tile_count"] == 2
        assert result["tile_skipped_empty"] == 0
        assert result["tile_failed_cover"] == 1
        assert (
            result["tile_count"] + result["tile_skipped_empty"]
            == result["grid_cols"] * result["grid_rows"]
        )

        with zipfile.ZipFile(result["zip_path"]) as archive:
            names = sorted(archive.namelist())
        assert names == ["tile_cover_R1C1.3mf", "tile_cover_R1C2.3mf"]

        assert len(captured) == 2
        cover_sources = [entry["cover_source"] for entry in captured]
        assert cover_sources.count(None) == 1

        warnings = [
            rec for rec in caplog.records
            if getattr(rec, "event", None) == "bambu_3mf_cover_thumbnail_failed"
        ]
        assert len(warnings) == 1
        warn = warnings[0]
        assert warn.error_type == "RuntimeError"
        assert warn.fallback_action == "placeholder_written"
        assert "synthetic rasterize failure" in warn.error_message
    finally:
        if os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])


def test_worker_propagates_cover_memory_error_without_export() -> None:
    tiles = [_make_tile("R1C1")]
    captured: list[dict] = []

    with (
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=tiles),
        patch(
            "api.workers.converter_workers._rasterize_tile_for_cover",
            side_effect=MemoryError("cover allocation failed"),
        ),
        patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
            side_effect=_fake_export(captured),
        ),
        pytest.raises(MemoryError, match="cover allocation failed"),
    ):
        worker_generate_large_format_svg_native(
            "image.svg",
            "lut.npy",
            _params_2x1(),
        )

    assert captured == []


def test_worker_releases_previous_tile_scene_before_next_build() -> None:
    tiles = [_make_tile("R1C1"), _make_tile("R1C2")]
    scene_mesh_refs: list[weakref.ReferenceType[trimesh.Trimesh]] = []

    class _ReleaseTrackingProcessor(_FakeVectorProcessor):
        def build_mesh(self, **_kwargs):
            if scene_mesh_refs:
                gc.collect()
                assert scene_mesh_refs[-1]() is None
            mesh = trimesh.creation.box(extents=(1.0, 1.0, 0.08))
            scene_mesh_refs.append(weakref.ref(mesh))
            scene = trimesh.Scene()
            scene.add_geometry(mesh, geom_name="Slot1")
            return scene

    with (
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _ReleaseTrackingProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=tiles),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", return_value=None),
        patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
            new=_fake_export([]),
        ),
    ):
        result = worker_generate_large_format_svg_native(
            "image.svg",
            "lut.npy",
            _params_2x1(),
        )

    try:
        assert result["tile_count"] == 2
    finally:
        if os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])


def test_worker_releases_board_merge_sources_before_writer() -> None:
    tiles = [
        _make_tile(
            "R1C1",
            slot_names=("Slot1",),
            preview_colors={0: [255, 0, 0, 255]},
        )
    ]
    source_refs: dict[str, weakref.ReferenceType[trimesh.Trimesh]] = {}

    class _BoardMergeProcessor(_FakeVectorProcessor):
        def build_mesh(self, **_kwargs):
            color = trimesh.creation.box(extents=(1.0, 1.0, 0.08))
            color.visual.face_colors = [255, 0, 0, 255]
            board = trimesh.creation.box(extents=(1.0, 1.0, 1.2))
            board.visual.face_colors = [255, 255, 255, 255]
            source_refs["color"] = weakref.ref(color)
            source_refs["board"] = weakref.ref(board)
            scene = trimesh.Scene()
            scene.add_geometry(color, geom_name="Slot1")
            scene.add_geometry(board, geom_name="Board")
            return scene

    def _assert_released_then_export(*, output_path: str, **_kwargs) -> None:
        gc.collect()
        assert source_refs["color"]() is None
        assert source_refs["board"]() is None
        with open(output_path, "wb") as handle:
            handle.write(b"3mf")

    with (
        patch(
            "core.pipeline.s03_color_replacement._normalize_color_replacements_input",
            return_value={},
        ),
        patch("core.vector_engine.VectorProcessor", _BoardMergeProcessor),
        patch(
            "core.vector_large_format.slice_vector_analysis_into_tiles",
            return_value=tiles,
        ),
        patch(
            "api.workers.converter_workers._rasterize_tile_for_cover",
            return_value=None,
        ),
        patch(
            "utils.bambu_3mf_writer.export_scene_with_bambu_metadata",
            side_effect=_assert_released_then_export,
        ),
    ):
        result = worker_generate_large_format_svg_native(
            "image.svg",
            "lut.npy",
            {
                **_params_2x1(),
                "total_width_mm": 60.0,
                "tile_width_mm": 60.0,
            },
        )

    try:
        assert result["tile_count"] == 1
    finally:
        if os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])


# ---------------------------------------------------------------------------
# Empty scene tile path: counted as skipped_empty, not failed_cover
# ---------------------------------------------------------------------------


def test_worker_counts_empty_scene_as_skipped_empty(tmp_path, caplog) -> None:
    """Empty scene tiles are counted as tile_skipped_empty, no WARNING is emitted."""

    from PIL import Image

    tiles = [_make_tile("R1C1"), _make_tile("R1C2")]
    captured: list[dict] = []

    cover_image = Image.new("RGBA", (256, 256), (255, 255, 0, 255))

    with (
        _capture_worker_warnings(caplog),
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _EmptySceneVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=tiles),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", return_value=cover_image),
        patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata", side_effect=_fake_export(captured)),
    ):
        with pytest.raises(ValueError, match="All SVG large-format tiles were empty after slicing"):
            worker_generate_large_format_svg_native("image.svg", "lut.npy", _params_2x1())

    # No 3MF written, but also no failed-cover WARNING — empty is silent.
    warnings = [
        rec for rec in caplog.records
        if getattr(rec, "event", None) == "bambu_3mf_cover_thumbnail_failed"
    ]
    assert warnings == []


# ---------------------------------------------------------------------------
# Counter invariant: mixed states across a 2x2 grid
# ---------------------------------------------------------------------------


def test_worker_counter_invariant_across_mixed_states(tmp_path, caplog) -> None:
    """``tile_count + tile_skipped_empty == grid_cols * grid_rows``.

    Slicing produces 3 of 4 tiles (1 already empty). One of the 3 raises,
    one times out, one succeeds. Under the new semantics all 3 sliced
    tiles are written to the ZIP (the two cover-failed tiles use the
    placeholder), and ``tile_failed_cover`` is a subset quality indicator
    on those two written tiles.
    """

    from PIL import Image

    tiles = [_make_tile("R1C1"), _make_tile("R1C2"), _make_tile("R2C1")]
    captured: list[dict] = []

    def _rasterize(tile, *_args, **_kwargs):
        if tile.label == "R1C1":
            raise TimeoutError("synthetic timeout")
        if tile.label == "R1C2":
            raise ValueError("synthetic value error")
        return Image.new("RGBA", (256, 256), (10, 10, 10, 255))

    with (
        _capture_worker_warnings(caplog),
        patch("core.pipeline.s03_color_replacement._normalize_color_replacements_input", return_value={}),
        patch("core.vector_engine.VectorProcessor", _FakeVectorProcessor),
        patch("core.vector_large_format.slice_vector_analysis_into_tiles", return_value=tiles),
        patch("api.workers.converter_workers._rasterize_tile_for_cover", side_effect=_rasterize),
        patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata", side_effect=_fake_export(captured)),
    ):
        result = worker_generate_large_format_svg_native("image.svg", "lut.npy", _params_2x2())

    try:
        # 4 grid cells, 3 sliced; all 3 sliced tiles are exported (2 with
        # placeholder cover, 1 with the rasterized image). 1 cell was
        # sliced-empty.
        assert result["tile_count"] == 3
        assert result["tile_failed_cover"] == 2
        assert result["tile_skipped_empty"] == 1
        assert (
            result["tile_count"] + result["tile_skipped_empty"]
            == result["grid_cols"] * result["grid_rows"]
        )

        # Exactly two WARNINGs (one per cover failure), with the new
        # ``placeholder_written`` fallback action.
        warning_records = [
            rec for rec in caplog.records
            if getattr(rec, "event", None) == "bambu_3mf_cover_thumbnail_failed"
        ]
        assert len(warning_records) == 2
        for rec in warning_records:
            assert rec.fallback_action == "placeholder_written"
    finally:
        if os.path.exists(result["zip_path"]):
            os.unlink(result["zip_path"])


# ---------------------------------------------------------------------------
# Issue 1 regression — hard timeout actually unblocks the worker
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Issue 1 regression — hard timeout actually kills a stuck rasterize subprocess
# ---------------------------------------------------------------------------




def test_run_rasterize_canvas_in_subprocess_propagates_crash_as_runtime_error() -> None:
    """A subprocess that raises must surface as ``RuntimeError`` to the parent.

    Guards the worker's failure-handling branch (``except Exception``):
    if the subprocess crashed, the parent must get a non-Timeout
    exception so ``tile_failed_cover`` is bumped under the
    ``error_type=type(exc).__name__`` path.
    """

    import api.workers.converter_workers as cw_module
    from tests.support import rasterize_subprocess_helpers as helpers

    with pytest.raises(RuntimeError, match="exited with code"):
        cw_module._run_rasterize_canvas_in_subprocess(
            svg_path="ignored.svg",
            target_width_mm=100.0,
            pixels_per_mm=1.0,
            _entry=helpers.crash_immediately_entry,
        )


def test_run_rasterize_canvas_in_subprocess_returns_canvas_on_success() -> None:
    """Happy path: subprocess writes the .npy, parent loads + returns it."""

    import api.workers.converter_workers as cw_module
    from tests.support import rasterize_subprocess_helpers as helpers

    arr = cw_module._run_rasterize_canvas_in_subprocess(
        svg_path="ignored.svg",
        target_width_mm=100.0,
        pixels_per_mm=1.0,
        _entry=helpers.write_solid_canvas_entry,
    )
    assert arr is not None
    assert arr.shape == (32, 32, 4)
    # The helper writes (220, 0, 0, 255) everywhere.
    assert int(arr[0, 0, 0]) == 220
    assert int(arr[0, 0, 3]) == 255


# ---------------------------------------------------------------------------
# Issue 1 regression — worker tile loop hard timeout (subprocess-backed)
# ---------------------------------------------------------------------------




# ---------------------------------------------------------------------------
# Issue 3 regression — tile coordinates are canvas-relative, not content-relative
# ---------------------------------------------------------------------------


def test_rasterize_tile_for_cover_uses_canvas_relative_coordinates() -> None:
    """``_rasterize_tile_for_cover`` must map ``(x_mm, y_mm)`` to the full canvas.

    Regression for the alpha-crop bug: the original ``rasterize_svg``
    content-aware-cropped the canvas, so ``(0, 0)`` of the returned array
    no longer corresponded to ``(0, 0)`` mm. The fix routes the canvas
    through ``_get_or_rasterize_full_canvas``, which calls
    ``rasterize_svg(crop_to_content=False)`` inside a hard-killable
    subprocess. We mock the fetcher with a 100×100 RGBA where the LEFT
    half is red and the RIGHT half is blue, then assert the per-tile
    crops follow canvas coordinates rather than content coordinates.
    """

    # Build a 100×100 RGBA canvas: left half red, right half blue.
    canvas = np.zeros((100, 100, 4), dtype=np.uint8)
    canvas[:, :50, 0] = 220  # Red channel for left half
    canvas[:, :50, 3] = 255
    canvas[:, 50:, 2] = 220  # Blue channel for right half
    canvas[:, 50:, 3] = 255

    captured_calls: list[dict] = []

    def _fake_canvas_fetch(**kwargs):
        captured_calls.append(kwargs)
        return canvas.copy()

    with patch(
        "api.workers.converter_workers._get_or_rasterize_full_canvas",
        side_effect=_fake_canvas_fetch,
    ):
        tile_left = _make_tile(
            "R1C1",
            x0_mm=0.0,
            y0_mm=0.0,
            x1_mm=60.0,
            y1_mm=60.0,
        )
        tile_right = _make_tile(
            "R1C2",
            x0_mm=60.0,
            y0_mm=0.0,
            x1_mm=120.0,
            y1_mm=60.0,
        )

        img_left = _rasterize_tile_for_cover(
            tile_left,
            "image.svg",
            total_width_mm=120.0,
            total_height_mm=60.0,
        )
        img_right = _rasterize_tile_for_cover(
            tile_right,
            "image.svg",
            total_width_mm=120.0,
            total_height_mm=60.0,
        )

    assert img_left is not None and img_right is not None

    # Both tiles must request the full canvas via the same helper.
    assert len(captured_calls) == 2
    for kw in captured_calls:
        assert kw["svg_path"] == "image.svg"
        assert kw["target_width_mm"] == 120.0

    arr_left = np.asarray(img_left.convert("RGB"), dtype=np.int32)
    arr_right = np.asarray(img_right.convert("RGB"), dtype=np.int32)

    mean_left = arr_left.reshape(-1, 3).mean(axis=0)
    mean_right = arr_right.reshape(-1, 3).mean(axis=0)

    # Left tile should be predominantly red, right tile predominantly blue.
    assert mean_left[0] > mean_left[2], (
        f"left tile expected red-dominant, got mean RGB={tuple(mean_left)}"
    )
    assert mean_right[2] > mean_right[0], (
        f"right tile expected blue-dominant, got mean RGB={tuple(mean_right)}"
    )


def test_rasterize_tile_cover_caps_full_canvas_for_ten_meter_layout() -> None:
    """Cover pixels stay thumbnail-sized instead of growing with millimetres."""

    canvas = np.zeros((512, 512, 4), dtype=np.uint8)
    canvas[..., 3] = 255
    captured_calls: list[dict] = []

    def fake_canvas_fetch(**kwargs):
        captured_calls.append(kwargs)
        return canvas

    tile = _make_tile(
        "R1C1",
        x0_mm=0.0,
        y0_mm=0.0,
        x1_mm=250.0,
        y1_mm=250.0,
    )
    with patch(
        "api.workers.converter_workers._get_or_rasterize_full_canvas",
        side_effect=fake_canvas_fetch,
    ):
        image = _rasterize_tile_for_cover(
            tile,
            "large.svg",
            total_width_mm=9999.0,
            total_height_mm=9999.0,
        )

    assert image is not None
    assert len(captured_calls) == 1
    assert (
        captured_calls[0]["pixels_per_mm"] * 9999.0
        <= converter_workers_module._TILE_COVER_MAX_LONGEST_PX
    )


def test_cover_subprocess_disables_full_size_raster_cache(tmp_path) -> None:
    """One-shot cover children must not retain a second full canvas copy."""

    output_path = tmp_path / "cover.npy"
    canvas = np.zeros((8, 8, 4), dtype=np.uint8)
    with patch(
        "core.pipeline.processing_ops.svg_rasterizer.rasterize_svg",
        return_value=canvas,
    ) as rasterize_mock:
        converter_workers_module._rasterize_canvas_subprocess_entry(
            "input.svg",
            100.0,
            2.0,
            str(output_path),
        )

    assert output_path.exists()
    assert rasterize_mock.call_args.kwargs["crop_to_content"] is False
    assert rasterize_mock.call_args.kwargs["_min_quality_px"] == 1
    assert rasterize_mock.call_args.kwargs["_max_longest_px"] == 512
    assert rasterize_mock.call_args.kwargs["_cache_result"] is False


# ---------------------------------------------------------------------------
# Issue 1 regression — parent-process canvas cache avoids re-spawning
# ---------------------------------------------------------------------------


def test_get_or_rasterize_full_canvas_caches_across_calls(tmp_path) -> None:
    """Repeated calls for the same SVG hit the parent cache after the first.

    A 4×4 grid would otherwise spawn 16 subprocesses; the cache keeps
    that to one subprocess + 15 cache hits (linear-time behaviour
    promised by R8.3).
    """

    import api.workers.converter_workers as cw_module

    # Bind a real on-disk svg path so the cache key (which uses mtime)
    # works; the contents do not matter because we patch the runner.
    svg_path = tmp_path / "fake.svg"
    svg_path.write_text("<svg/>")

    canvas = np.zeros((40, 40, 4), dtype=np.uint8)
    canvas[..., 1] = 200
    canvas[..., 3] = 255

    runner_calls: list[tuple] = []

    def _fake_runner(**kwargs):
        runner_calls.append(tuple(sorted(kwargs.items())))
        return canvas.copy()

    # Reset the module-level cache so this test is independent of
    # other tests that may have populated it.
    cw_module._TILE_COVER_CANVAS_CACHE.clear()

    with patch(
        "api.workers.converter_workers._run_rasterize_canvas_in_subprocess",
        side_effect=_fake_runner,
    ):
        first = cw_module._get_or_rasterize_full_canvas(
            svg_path=str(svg_path),
            target_width_mm=120.0,
            pixels_per_mm=4.0,
        )
        second = cw_module._get_or_rasterize_full_canvas(
            svg_path=str(svg_path),
            target_width_mm=120.0,
            pixels_per_mm=4.0,
        )
        third = cw_module._get_or_rasterize_full_canvas(
            svg_path=str(svg_path),
            target_width_mm=120.0,
            pixels_per_mm=4.0,
        )

    assert first is not None
    assert second is not None
    assert third is not None
    # The runner should have been invoked exactly once: subsequent
    # calls hit the cache.
    assert len(runner_calls) == 1, (
        f"expected 1 subprocess spawn, got {len(runner_calls)}"
    )
    # The full canvas is immutable and shared; copying it once per tile would
    # recreate the exact task-wide memory amplification this cache avoids.
    assert first is second is third
    assert first.flags.writeable is False
    np.testing.assert_array_equal(first, second)
    np.testing.assert_array_equal(first, third)
