from pathlib import Path

import pytest

from config import MatchStrategy, ModelingMode
from core.converter import ConversionRequest, generate_final_model


def _pick_real_image(repo_root: Path) -> Path | None:
    candidates = [
        repo_root / "example" / "any002.png",
        repo_root / "lut-npy预设" / "bambulab" / "bambulab_pla_basic_cmyw_sample.png",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _pick_real_lut(repo_root: Path) -> Path | None:
    candidates = [
        repo_root / "lut-npy预设" / "bambulab" / "bambulab_pla_basic_cmyw.npy",
        repo_root / "lut-npy预设" / "bambulab" / "bambulab_pla_basic_cmyw_new.npy",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


@pytest.mark.e2e
@pytest.mark.slow
def test_real_backend_converter_pipeline_no_mock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo_root = Path(__file__).resolve().parents[2]
    image_path = _pick_real_image(repo_root)
    lut_path = _pick_real_lut(repo_root)

    if image_path is None:
        pytest.skip("No real image asset found (expected example/any002.png)")
    if lut_path is None:
        pytest.skip("No real LUT asset found under lut-npy预设/bambulab")

    # Keep artifacts inside pytest temp dir while exercising full backend code path.
    monkeypatch.setattr("core.converter.OUTPUT_DIR", str(tmp_path))

    request = ConversionRequest(
        lut_path=str(lut_path),
        target_width_mm=20,
        auto_bg=False,
        bg_tol=40,
        color_mode="CMYW",
        modeling_mode=ModelingMode.HIGH_FIDELITY,
        quantize_colors=16,
        match_strategy=MatchStrategy.RGB_EUCLIDEAN,
    )

    out_path, glb_path, preview_img, status = generate_final_model(
        str(image_path), request
    )

    assert out_path is not None and Path(out_path).exists()
    assert status and "❌" not in status
    assert preview_img is not None
    if glb_path is not None:
        assert Path(glb_path).exists()
