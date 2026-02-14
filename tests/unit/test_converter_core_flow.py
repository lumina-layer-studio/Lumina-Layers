import pytest

from config import ColorMode, MatchStrategy, ModelingMode, StructureMode
from core.converter import ConversionRequest, convert_image_to_3d


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
