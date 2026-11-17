"""Screen previews stay bounded without changing the printable image grid."""

import pickle
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from core.preview_sizing import preview_dimensions
from api.workers.converter_workers import worker_generate_preview
from core.pipeline import p06_bed_rendering


def test_large_format_display_dimensions_use_screen_budget() -> None:
    """Check the ticket's model dimensions without allocating its image."""
    display_w, display_h = preview_dimensions(12000, 16326)

    assert (display_w, display_h) == (1176, 1600)
    assert display_w * display_h <= 1600 * 1600


@pytest.mark.parametrize("shape", [(12, 8), (8, 12), (12, 1)])
def test_display_render_bounds_pixels_and_preserves_model_cache(
    monkeypatch: pytest.MonkeyPatch,
    shape: tuple[int, int],
) -> None:
    monkeypatch.setattr("config.IMAGE_PREVIEW_MAX_EDGE", 8)
    raw_h, raw_w = shape
    rgba = np.zeros((raw_h, raw_w, 4), dtype=np.uint8)
    rgba[:, raw_w // 2:] = [120, 30, 220, 255]
    original = rgba.copy()
    cache = {"target_w": raw_w, "target_h": raw_h, "preview_rgba": rgba}
    context = {
        "preview_rgba": rgba,
        "cache": cache,
        "color_conf": {},
        "target_width_mm": 1200.0,
    }

    result = p06_bed_rendering.run(context)
    display = result["display_image"]

    assert max(display.shape[:2]) == 8
    assert display.shape[:2] == preview_dimensions(raw_w, raw_h)[::-1]
    assert set(map(tuple, display.reshape(-1, 4))) <= {
        (0, 0, 0, 0), (120, 30, 220, 255),
    }
    np.testing.assert_array_equal(rgba, original)
    assert result["target_width_mm"] == 1200.0
    assert result["cache"] is cache
    assert cache["target_w"] == raw_w
    assert cache["target_h"] == raw_h
    assert cache["preview_rgba"] is rgba


def test_display_render_keeps_small_pixel_art_unchanged() -> None:
    rgba = np.array(
        [[[255, 0, 0, 255], [0, 0, 0, 0]],
         [[0, 255, 0, 128], [0, 0, 255, 255]]],
        dtype=np.uint8,
    )

    display = p06_bed_rendering.render_preview(
        rgba, None, 0, 0, 0, 0, False, {}, target_width_mm=1200.0,
    )

    np.testing.assert_array_equal(display, rgba)
    assert not np.shares_memory(display, rgba)


def test_display_render_scales_loop_position_with_the_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("config.IMAGE_PREVIEW_MAX_EDGE", 40)
    rgba = np.zeros((40, 80, 4), dtype=np.uint8)

    display = p06_bed_rendering.render_preview(
        rgba, (40, 20), 1.0, 1.0, 0.2, 0, True, {}, target_width_mm=8.0,
    )

    assert display.shape == (20, 40, 4)
    marker_y, marker_x = np.where(display[..., 3] > 0)
    assert marker_x.min() >= 17
    assert marker_x.max() <= 23
    assert marker_y.min() >= 6
    assert marker_y.max() <= 13
    assert not rgba.any()


@pytest.mark.parametrize("image_type", ["numpy", "pil"])
def test_worker_bounds_display_png_but_retains_raw_model_grid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    image_type: str,
) -> None:
    monkeypatch.setattr("config.IMAGE_PREVIEW_MAX_EDGE", 8)
    rgba = np.zeros((12, 8, 4), dtype=np.uint8)
    rgba[:, 4:] = [120, 30, 220, 255]
    display = Image.fromarray(rgba) if image_type == "pil" else rgba
    cache = {
        "preview_rgba": rgba,
        "target_w": 8,
        "target_h": 12,
        "target_width_mm": 1200.0,
        "color_conf": {},
    }
    with (
        patch("core.converter.generate_preview_cached", return_value=(display, cache, "OK")),
        patch("config.TEMP_DIR", str(tmp_path)),
    ):
        result = worker_generate_preview(
            image_path="image.png", lut_path="lut.npy", target_width_mm=1200.0,
            color_mode="4-Color (RYBW)", modeling_mode="high-fidelity",
            color_layers=5, layer_height_mm=0.08, quantize_colors=8,
            enable_cleanup=False,
        )

    with Image.open(result["preview_png_path"]) as saved_display:
        assert saved_display.size == (5, 8)
        assert saved_display.mode == "RGBA"
        assert set(saved_display.getdata()) <= {(0, 0, 0, 0), (120, 30, 220, 255)}
    with Image.open(result["raw_preview_png_path"]) as raw_image:
        np.testing.assert_array_equal(raw_image, rgba)
    with open(result["cache_data_path"], "rb") as handle:
        metadata = pickle.load(handle)
    assert metadata["target_w"] == 8
    assert metadata["target_h"] == 12
    assert metadata["target_width_mm"] == 1200.0
    np.testing.assert_array_equal(
        np.load(result["cache_artifact_ref"]["fields"]["preview_rgba"]["path"]),
        rgba,
    )
