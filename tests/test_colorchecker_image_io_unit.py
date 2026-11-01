"""Tests for ColorChecker image decoding helpers."""

from __future__ import annotations

import io
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

import core.colorchecker.image_io as image_io


@pytest.mark.parametrize("dtype", [np.uint8, np.uint16])
def test_png_write_round_trips_unicode_paths_without_changing_pixels(tmp_path, dtype) -> None:
    directory = tmp_path / "软件" / "校色 café"
    directory.mkdir(parents=True)
    target = directory / "校准结果.png"
    pixels = np.arange(12 * 8 * 3, dtype=dtype).reshape(8, 12, 3)
    if dtype == np.uint16:
        pixels *= 173

    image_io.write_png_file(target, pixels)

    decoded = image_io.cv2.imdecode(
        np.frombuffer(target.read_bytes(), dtype=np.uint8), image_io.cv2.IMREAD_UNCHANGED,
    )
    assert decoded.dtype == pixels.dtype
    np.testing.assert_array_equal(decoded, pixels)


def test_png_encoding_failure_does_not_truncate_existing_file(tmp_path, monkeypatch) -> None:
    target = tmp_path / "校准结果.png"
    target.write_bytes(b"original")
    monkeypatch.setattr(image_io.cv2, "imencode", lambda *_: (False, None))

    with pytest.raises(ValueError, match="Failed to encode PNG"):
        image_io.write_png_file(target, np.zeros((2, 2, 3), dtype=np.uint8))

    assert target.read_bytes() == b"original"


def test_standard_decode_applies_exif_orientation(monkeypatch) -> None:
    """Standard JPEG decoding should match browser-visible EXIF orientation."""
    source = Image.new("RGB", (2, 3), (0, 0, 0))
    exif = source.getexif()
    exif[274] = 6
    buffer = io.BytesIO()
    source.save(buffer, format="JPEG", exif=exif)

    def fail_imdecode(*_args, **_kwargs):
        raise AssertionError("decode_standard_image_bytes should not use cv2.imdecode")

    monkeypatch.setattr(image_io.cv2, "imdecode", fail_imdecode)

    decoded = image_io.decode_standard_image_bytes(buffer.getvalue())

    assert decoded is not None
    assert decoded.shape[:2] == (2, 3)


def test_raw_upload_preview_uses_display_decode(monkeypatch) -> None:
    """RAW previews should use the display decode path, not strict calibration decode."""
    captured: dict[str, object] = {}

    rgb = np.zeros((4, 6, 3), dtype=np.uint8)
    rgb[:, :] = [56, 34, 12]

    class FakeRaw:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def postprocess(self, **kwargs):
            captured.update(kwargs)
            return rgb

    fake_rawpy = SimpleNamespace(
        imread=lambda _stream: FakeRaw(),
        ColorSpace=SimpleNamespace(sRGB="srgb"),
        DemosaicAlgorithm=SimpleNamespace(AHD="ahd"),
    )
    monkeypatch.setattr(image_io, "rawpy", fake_rawpy)

    decoded, source_type = image_io.decode_uploaded_bytes(
        b"fake raw",
        file_name="shot.ARW",
        mime_type="application/octet-stream",
    )

    assert decoded.shape == (4, 6, 3)
    assert decoded[0, 0].tolist() == [12, 34, 56]
    assert source_type == "raw"
    assert captured["use_camera_wb"] is True
    assert captured["use_auto_wb"] is False
    assert captured["no_auto_bright"] is True
    assert captured["output_bps"] == 8


def test_raw_file_preview_decodes_from_path_without_loading_bytes(
    monkeypatch,
    tmp_path,
) -> None:
    """Server-side RAW previews should avoid holding an extra raw-bytes copy."""
    captured: dict[str, object] = {}
    source = tmp_path / "shot.arw"
    source.write_bytes(b"fake raw")
    rgb = np.zeros((3, 5, 3), dtype=np.uint8)
    rgb[:, :] = [8, 16, 24]

    class FakeRaw:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def postprocess(self, **kwargs):
            captured.update(kwargs)
            return rgb

    def fake_imread(path):
        captured["path"] = path
        return FakeRaw()

    fake_rawpy = SimpleNamespace(
        imread=fake_imread,
        ColorSpace=SimpleNamespace(sRGB="srgb"),
        DemosaicAlgorithm=SimpleNamespace(AHD="ahd"),
    )
    monkeypatch.setattr(image_io, "rawpy", fake_rawpy)

    decoded = image_io.decode_raw_image_file(source, file_name=source.name)

    assert captured["path"] == str(source)
    assert decoded.shape == (3, 5, 3)
    assert decoded[0, 0].tolist() == [24, 16, 8]
    assert captured["use_camera_wb"] is True
    assert captured["no_auto_bright"] is True
