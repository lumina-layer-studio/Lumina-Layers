import pytest
import numpy as np
import gradio as gr

from config import ColorMode, MatchStrategy, ModelingMode, StructureMode
from core.converter import (
    ConversionRequest,
    convert_image_to_3d,
)
from ui.converter_ui import (
    _preview_click_to_original_coords,
    on_preview_click_select_color,
)


def _make_request(modeling_mode: ModelingMode) -> ConversionRequest:
    return ConversionRequest(
        lut_path="dummy.npy",
        target_width_mm=20,
        auto_bg=False,
        bg_tol=40,
        color_mode=ColorMode.CMYW,
        modeling_mode=modeling_mode,
        quantize_colors=16,
        match_strategy=MatchStrategy.RGB_EUCLIDEAN,
        spacer_thick=1.2,
        structure_mode=StructureMode.DOUBLE_SIDED,
    )


@pytest.mark.unit
def test_convert_image_to_3d_dispatches_vector_svg_flow(
    monkeypatch: pytest.MonkeyPatch,
):
    expected = ("vector.3mf", "vector.glb", "preview", "ok")

    def fake_vector(image_path, actual_lut_path, request):
        assert image_path.endswith(".svg")
        assert actual_lut_path == "dummy.npy"
        return expected

    monkeypatch.setattr("core.converter._run_vector_svg_flow", fake_vector)

    request = _make_request(ModelingMode.VECTOR)
    assert convert_image_to_3d("logo.svg", request) == expected


@pytest.mark.unit
def test_convert_image_to_3d_dispatches_raster_flow(monkeypatch: pytest.MonkeyPatch):
    expected = ("raster.3mf", "raster.glb", "preview", "ok")

    def fake_raster(
        image_path,
        actual_lut_path,
        request,
        modeling_mode,
        blur_kernel,
        smooth_sigma,
    ):
        assert image_path.endswith(".png")
        assert actual_lut_path == "dummy.npy"
        assert modeling_mode == ModelingMode.HIGH_FIDELITY
        assert blur_kernel == 0
        assert smooth_sigma == 10
        return expected

    monkeypatch.setattr("core.converter._run_raster_flow", fake_raster)

    request = _make_request(ModelingMode.HIGH_FIDELITY)
    assert convert_image_to_3d("photo.png", request) == expected


@pytest.mark.unit
def test_convert_image_to_3d_vector_mode_requires_svg_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
):
    def should_not_call(*args, **kwargs):
        raise AssertionError("raster flow should not be called in vector mode")

    monkeypatch.setattr("core.converter._run_raster_flow", should_not_call)

    request = _make_request(ModelingMode.VECTOR)
    out_3mf, out_glb, preview, status = convert_image_to_3d("photo.png", request)

    assert out_3mf is None
    assert out_glb is None
    assert preview is None
    assert status


@pytest.mark.unit
def test_preview_click_coords_scaled_preview_maps_back_correctly():
    target_w, target_h = 1000, 1000
    x, y = 400, 300

    # canvas -> scaled preview coords (same formula as UI downscale)
    canvas_w = target_w * 2 + 30 * 2
    canvas_h = target_h * 2 + 30 * 2
    ui_scale = min(1.0, 900 / canvas_w, 560 / canvas_h)
    click_x = (x * 2 + 30) * ui_scale
    click_y = (y * 2 + 30) * ui_scale

    mapped_x, mapped_y = _preview_click_to_original_coords(
        click_x, click_y, target_w, target_h
    )

    assert mapped_x == pytest.approx(x, abs=0.6)
    assert mapped_y == pytest.approx(y, abs=0.6)


@pytest.mark.unit
def test_preview_click_select_color_uses_scaled_coords_correctly(
    monkeypatch: pytest.MonkeyPatch,
):
    target_w, target_h = 1000, 1000
    x, y = 400, 300
    target_rgb = np.array([18, 171, 52], dtype=np.uint8)

    matched_rgb = np.zeros((target_h, target_w, 3), dtype=np.uint8)
    matched_rgb[y, x] = target_rgb
    mask_solid = np.ones((target_h, target_w), dtype=bool)

    cache = {
        "target_w": target_w,
        "target_h": target_h,
        "matched_rgb": matched_rgb,
        "quantized_image": matched_rgb.copy(),
        "mask_solid": mask_solid,
    }

    # avoid heavy highlight rendering path in unit test
    monkeypatch.setattr(
        "ui.converter_ui.generate_highlight_preview",
        lambda *_args, **_kwargs: (None, "ok"),
    )

    canvas_w = target_w * 2 + 30 * 2
    canvas_h = target_h * 2 + 30 * 2
    ui_scale = min(1.0, 900 / canvas_w, 560 / canvas_h)
    evt = gr.SelectData(
        None,
        {"index": ((x * 2 + 30) * ui_scale, (y * 2 + 30) * ui_scale), "value": None},
    )

    _img, _display_text, hex_val, _msg = on_preview_click_select_color(cache, evt)
    assert isinstance(hex_val, str)
    assert "region|" in hex_val
    assert "|m=#12ab34|" in hex_val
