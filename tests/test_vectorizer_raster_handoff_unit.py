"""Regression tests for accepted raster formats at the native vectorizer handoff.
原生矢量化输入交接的已接受栅格格式回归测试。

WebP and TIFF uploads are accepted by the backend but the native loader cannot
decode them, so they used to fail with a generic 500. These tests drive the
real ``neroued_vectorizer`` and require WebP/TIFF results to match the result
for the same pixels encoded as PNG, with all temp files cleaned up. 16-bit grey
TIFF must keep its exact 0..65535 values in every byte order. Exact native
output is only compared on fixtures the native vectorizer renders
deterministically; otherwise the decoded handoff pixels are the oracle.
"""

from __future__ import annotations

import io
import os
import shutil
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
from PIL import Image

nv = pytest.importorskip("neroued_vectorizer")


@pytest.fixture()
def temp_dir(tmp_path, monkeypatch):
    """Isolate config.TEMP_DIR so leftovers can be counted exactly."""
    import config

    work = tmp_path / "temp"
    work.mkdir()
    monkeypatch.setattr(config, "TEMP_DIR", str(work))
    return work


def _banded_rgb() -> Image.Image:
    """Non-square image with four colour bands (stored orientation matters)."""
    img = Image.new("RGB", (96, 64), (255, 255, 255))
    img.paste((220, 20, 60), (0, 16, 96, 32))
    img.paste((255, 230, 0), (0, 32, 96, 48))
    img.paste((0, 102, 255), (48, 48, 96, 64))
    return img


def _rgba_with_transparency() -> Image.Image:
    img = Image.new("RGBA", (80, 80), (0, 0, 0, 0))
    img.paste((255, 0, 0, 255), (16, 16, 64, 64))
    img.paste((0, 0, 255, 255), (32, 32, 48, 48))
    return img


def _write(img: Image.Image, path, fmt: str, **kwargs) -> str:
    img.save(path, fmt, **kwargs)
    return str(path)


def _vectorize(src: str, temp_dir) -> tuple[dict, str]:
    """Run worker_vectorize on a temp copy (the worker deletes its input)."""
    from api.workers.vectorizer_workers import worker_vectorize

    upload = temp_dir / ("upload_" + os.path.basename(src))
    shutil.copyfile(src, upload)
    result = worker_vectorize(str(upload), {})
    with open(result["svg_path"], encoding="utf-8") as f:
        svg = f.read()
    os.unlink(result["svg_path"])
    return result, svg


def _summary(result: dict) -> dict:
    return {k: result[k] for k in ("width", "height", "num_shapes", "num_colors", "palette")}


def _hex_near(palette: list[str], rgb: tuple[int, int, int], tol: int = 16) -> bool:
    return any(
        max(abs(int(h[i:i + 2], 16) - c) for i, c in zip((1, 3, 5), rgb)) <= tol
        for h in palette
    )


# Six vertical bands that span the full 16-bit range, and the review's values.
_BANDS16 = [0, 8192, 16384, 32768, 49152, 65535]
_REVIEW16 = [0, 255, 256, 1000, 65535]
_SIGNED_BANDS16 = [0, 4096, 8192, 16384, 24576, 32767]
_SIGNED_NEGATIVE16 = [-32768, -8192, -1, 0, 4096, 16384, 32767]


def _gray16_bands(levels: list[int], width: int = 160, height: int = 64) -> np.ndarray:
    arr = np.zeros((height, width), dtype=np.int32)
    step = width // len(levels)
    for i, value in enumerate(levels):
        end = (i + 1) * step if i < len(levels) - 1 else width
        arr[:, i * step:end] = value
    return arr


def _write_gray16_tiff(
    arr: np.ndarray, path, byte_order: str, *, sample_format: int = 1
) -> str:
    """Write an uncompressed baseline 16-bit grey TIFF by hand (II or MM)."""
    e = "<" if byte_order == "II" else ">"
    height, width = arr.shape
    pixels = arr.astype(f"{e}{'i' if sample_format == 2 else 'u'}2").tobytes()
    tags = [  # tag, type (3=SHORT, 4=LONG), value
        (256, 3, width), (257, 3, height), (258, 3, 16), (259, 3, 1), (262, 3, 1),
        (273, 4, 8 + 2 + 10 * 12 + 4), (277, 3, 1), (278, 3, height), (279, 4, len(pixels)),
        (339, 3, sample_format),
    ]
    ifd = struct.pack(f"{e}H", len(tags))
    for tag, typ, value in tags:
        packed = struct.pack(f"{e}HH", value, 0) if typ == 3 else struct.pack(f"{e}I", value)
        ifd += struct.pack(f"{e}HHI", tag, typ, 1) + packed
    ifd += struct.pack(f"{e}I", 0)
    magic = b"II*\x00" if byte_order == "II" else b"MM\x00*"
    with open(path, "wb") as f:
        f.write(magic + struct.pack(f"{e}I", 8) + ifd + pixels)
    return str(path)


def _write_gray16(arr: np.ndarray, path, source: str) -> str:
    if source in ("II", "MM"):
        return _write_gray16_tiff(arr, path, source)
    fmt = "PNG" if source == "png" else "TIFF"
    mode = "I;16B" if source == "pillow_I;16B" else "I;16"
    data = arr.astype(">u2" if mode == "I;16B" else "<u2").tobytes()
    Image.frombytes(mode, (arr.shape[1], arr.shape[0]), data).save(path, fmt)
    return str(path)


@pytest.mark.parametrize(
    ("name", "fmt", "kwargs"),
    [
        ("img.webp", "WEBP", {"lossless": True}),
        ("webp_bytes.png", "WEBP", {"lossless": True}),
        ("img.tiff", "TIFF", {}),
        ("img.tif", "TIFF", {"compression": "tiff_lzw"}),
    ],
)
def test_webp_and_tiff_match_png_result(tmp_path, temp_dir, name, fmt, kwargs):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    img = _banded_rgb()
    png = _write(img, src_dir / "ref.png", "PNG")
    other = _write(img, src_dir / name, fmt, **kwargs)

    png_result, png_svg = _vectorize(png, temp_dir)
    result, svg = _vectorize(other, temp_dir)

    assert _summary(result) == _summary(png_result)
    assert (result["width"], result["height"]) == (96, 64)
    assert svg == png_svg
    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("fmt", "kwargs"),
    [("WEBP", {"lossless": True, "exact": True}), ("TIFF", {})],
)
def test_alpha_is_preserved_like_png(tmp_path, temp_dir, fmt, kwargs):
    """RGBA WebP/TIFF hand over exact RGBA pixels and vectorize like the PNG.

    The native output for this transparent fixture varies run to run (also for
    the PNG itself), so the deterministic oracle is the decoded RGBA handoff;
    the native result must still succeed with the same size and opaque colours.
    """
    from api.workers.vectorizer_workers import _transcode_for_native_loader

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    img = _rgba_with_transparency()
    png = _write(img, src_dir / "ref.png", "PNG")
    other = _write(img, src_dir / ("img." + fmt.lower()), fmt, **kwargs)

    handoff = _transcode_for_native_loader(other, str(temp_dir))
    try:
        with Image.open(handoff) as out:
            assert (out.format, out.mode, out.size) == ("PNG", "RGBA", (80, 80))
            assert out.tobytes() == img.tobytes()
            assert sorted(set(out.getchannel("A").getdata())) == [0, 255]
    finally:
        os.unlink(handoff)

    png_result, _ = _vectorize(png, temp_dir)
    result, svg = _vectorize(other, temp_dir)

    for res in (png_result, result):
        assert (res["width"], res["height"]) == (80, 80)
        assert _hex_near(res["palette"], (255, 0, 0))
        assert _hex_near(res["palette"], (0, 0, 255))
    assert 'viewBox="0 0 80 80"' in svg
    assert list(temp_dir.iterdir()) == []


def test_handoff_png_keeps_decoded_pixels_and_alpha(tmp_path, temp_dir):
    from api.workers.vectorizer_workers import _transcode_for_native_loader

    img = _rgba_with_transparency()
    src = _write(img, tmp_path / "img.webp", "WEBP", lossless=True, exact=True)

    png_path = _transcode_for_native_loader(src, str(temp_dir))
    try:
        with Image.open(png_path) as out:
            assert out.format == "PNG"
            assert out.mode == "RGBA"
            assert out.tobytes() == img.tobytes()
    finally:
        os.unlink(png_path)


def _orientation6_exif() -> Image.Exif:
    exif = Image.Exif()
    exif[0x0112] = 6  # display rotated 90 degrees clockwise
    return exif


def test_webp_exif_orientation_matches_stored_pixel_png_oracle(tmp_path, temp_dir):
    """WebP EXIF orientation is not applied, like native PNG/JPEG handling."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    img = _banded_rgb()
    png = _write(img, src_dir / "ref.png", "PNG")
    jpeg = _write(img, src_dir / "ref.jpg", "JPEG", quality=95, exif=_orientation6_exif())
    webp = _write(img, src_dir / "img.webp", "WEBP", lossless=True, exif=_orientation6_exif())

    png_result, png_svg = _vectorize(png, temp_dir)
    jpeg_result, _ = _vectorize(jpeg, temp_dir)
    result, svg = _vectorize(webp, temp_dir)

    assert (jpeg_result["width"], jpeg_result["height"]) == (96, 64)
    assert _summary(result) == _summary(png_result)
    assert svg == png_svg


def test_tiff_orientation_tag_matches_decoded_pixel_png_oracle(tmp_path, temp_dir):
    """TIFF Orientation is applied by the decoder; the oracle is the rotated PNG.

    The native output for this rotated fixture varies run to run (also for the
    oracle PNG itself), so the exact oracle is the rotated handoff pixels; both
    real results must have the rotated size and all four band colours.
    """
    from api.workers.vectorizer_workers import _transcode_for_native_loader

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    img = _banded_rgb()
    displayed = img.transpose(Image.Transpose.ROTATE_270)
    oracle_png = _write(displayed, src_dir / "oracle.png", "PNG")
    tiff = _write(img, src_dir / "img.tiff", "TIFF", exif=_orientation6_exif())

    png_path = _transcode_for_native_loader(tiff, str(temp_dir))
    try:
        with Image.open(png_path) as out:
            assert out.size == (64, 96)
            assert out.tobytes() == displayed.tobytes()
    finally:
        os.unlink(png_path)

    oracle_result, _ = _vectorize(oracle_png, temp_dir)
    result, svg = _vectorize(tiff, temp_dir)

    for res in (oracle_result, result):
        assert (res["width"], res["height"]) == (64, 96)
        for band in ((255, 255, 255), (220, 20, 60), (255, 230, 0), (0, 102, 255)):
            assert _hex_near(res["palette"], band)
    assert 'viewBox="0 0 64 96"' in svg
    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("name", "fmt"),
    [("img.png", "PNG"), ("img.jpg", "JPEG"), ("img.bmp", "BMP")],
)
def test_pillow_pixel_guard_does_not_gate_native_formats(temp_dir, monkeypatch, name, fmt):
    """Native-readable uploads never reach Pillow, so its pixel limit cannot reject them."""
    from api.workers.vectorizer_workers import worker_vectorize

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 200)
    upload = _write(_banded_rgb(), temp_dir / name, fmt)

    result = worker_vectorize(upload, {})

    assert (result["width"], result["height"]) == (96, 64)
    assert Image.MAX_IMAGE_PIXELS == 200
    os.unlink(result["svg_path"])
    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("name", "fmt", "kwargs"),
    [("img.webp", "WEBP", {"lossless": True}), ("img.tiff", "TIFF", {})],
)
def test_pillow_pixel_guard_on_webp_tiff_hands_original_path_to_native(
    temp_dir, monkeypatch, name, fmt, kwargs
):
    """Over-limit WebP/TIFF is not decoded; the native loader gets the original file.

    Whether the native build can read WebP/TIFF depends on the runtime, so a
    sentinel stops the call instead of asserting a native failure.
    """
    from api.workers.vectorizer_workers import worker_vectorize

    class _Sentinel(RuntimeError):
        pass

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 200)
    upload = _write(_banded_rgb(), temp_dir / name, fmt, **kwargs)
    seen: list[str] = []

    def _spy(path, config):
        seen.append(path)
        raise _Sentinel(path)

    with patch.object(nv, "vectorize", side_effect=_spy):
        with pytest.raises(_Sentinel):
            worker_vectorize(upload, {})

    assert seen == [upload]
    assert Image.MAX_IMAGE_PIXELS == 200
    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("name", "fmt"),
    [("img.png", "PNG"), ("img.jpg", "JPEG"), ("img.bmp", "BMP")],
)
def test_natively_readable_formats_keep_original_path(tmp_path, temp_dir, name, fmt):
    from api.workers.vectorizer_workers import worker_vectorize

    upload = _write(_banded_rgb(), temp_dir / name, fmt)
    seen: list[str] = []
    real_vectorize = nv.vectorize

    def _spy(path, config):
        seen.append(path)
        return real_vectorize(path, config)

    with patch.object(nv, "vectorize", side_effect=_spy):
        result = worker_vectorize(upload, {})

    assert seen == [upload]
    os.unlink(result["svg_path"])
    assert list(temp_dir.iterdir()) == []


def test_native_failure_cleans_input_and_handoff_png(tmp_path, temp_dir):
    from api.workers.vectorizer_workers import worker_vectorize

    upload = _write(_banded_rgb(), temp_dir / "img.webp", "WEBP", lossless=True)
    seen: list[str] = []

    def _fail(path, config):
        seen.append(path)
        assert os.path.exists(path)
        raise RuntimeError("native failure")

    with patch.object(nv, "vectorize", side_effect=_fail):
        with pytest.raises(RuntimeError, match="native failure"):
            worker_vectorize(upload, {})

    assert len(seen) == 1 and seen[0] != upload and seen[0].endswith(".png")
    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize("keep", [12, 40, -20])
def test_undecodable_webp_still_fails_inside_boundary_and_cleans_up(temp_dir, keep):
    """Broken WebP keeps the existing worker-error policy (mapped to 500)."""
    from api.routers.vectorizer import _VECTORIZER_BOUNDARY_ERRORS
    from api.workers.vectorizer_workers import worker_vectorize

    buf = io.BytesIO()
    _banded_rgb().save(buf, "WEBP", lossless=True)
    upload = temp_dir / "truncated.webp"
    upload.write_bytes(buf.getvalue()[:keep])

    with pytest.raises(_VECTORIZER_BOUNDARY_ERRORS):
        worker_vectorize(str(upload), {})

    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize(
    ("filename", "fmt", "content_type"),
    [
        ("input.webp", "WEBP", "image/webp"),
        ("input.tiff", "TIFF", "image/tiff"),
        ("webp_bytes.png", "WEBP", "image/png"),
    ],
)
def test_api_vectorize_returns_same_svg_as_png(temp_dir, filename, fmt, content_type):
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.dependencies import get_file_registry, get_worker_pool
    from api.file_registry import FileRegistry
    from api.workers.vectorizer_workers import worker_vectorize

    async def _run_inline(fn, *args, macos_runtime=None):
        return fn(*args)

    def _encode(img_fmt: str) -> bytes:
        buf = io.BytesIO()
        kwargs = {"lossless": True} if img_fmt == "WEBP" else {}
        _banded_rgb().save(buf, img_fmt, **kwargs)
        return buf.getvalue()

    app = create_app()
    registry = FileRegistry()
    pool = SimpleNamespace(submit=AsyncMock(side_effect=_run_inline))
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: pool
    client = TestClient(app)
    try:
        bodies = {}
        svgs = {}
        for key, name, img_fmt, ctype in (
            ("png", "input.png", "PNG", "image/png"),
            ("other", filename, fmt, content_type),
        ):
            response = client.post(
                "/api/vectorize",
                files={"image": (name, _encode(img_fmt), ctype)},
                data={"params": "{}"},
            )
            assert response.status_code == 200, response.text
            bodies[key] = response.json()
            download = client.get(bodies[key]["svg_url"])
            assert download.status_code == 200
            svgs[key] = download.text
    finally:
        app.dependency_overrides.clear()

    assert pool.submit.await_args_list[1].args[0] is worker_vectorize
    for field in ("width", "height", "num_shapes", "num_colors", "palette"):
        assert bodies["other"][field] == bodies["png"][field]
    assert svgs["other"] == svgs["png"]
    assert svgs["other"].lstrip().startswith(("<?xml", "<svg"))
    assert 'data-lumina-origin="image-vectorizer"' in svgs["other"]
    leftovers = {p.suffix for p in temp_dir.iterdir()}
    assert leftovers <= {".svg"}
    assert len(list(temp_dir.iterdir())) == 2  # the two registered outputs


@pytest.mark.parametrize("levels", [_BANDS16, _REVIEW16], ids=["bands", "review_values"])
@pytest.mark.parametrize(
    ("source", "decoded_mode"),
    [("II", "I;16"), ("MM", "I;16B"), ("pillow_I;16", "I;16"), ("pillow_I;16B", "I;16B")],
)
def test_16bit_grey_tiff_handoff_keeps_exact_values(tmp_path, temp_dir, levels, source, decoded_mode):
    """Every 16-bit grey byte order reaches the native loader as exact 0..65535 values."""
    from api.workers.vectorizer_workers import _transcode_for_native_loader

    arr = _gray16_bands(levels)
    src = _write_gray16(arr, tmp_path / "img.tiff", source)
    with Image.open(src) as im:
        assert im.mode == decoded_mode

    handoff = _transcode_for_native_loader(src, str(temp_dir))
    try:
        with Image.open(handoff) as out:
            assert (out.format, out.mode, out.size) == ("PNG", "I;16", (160, 64))
            decoded = np.asarray(out.convert("I")).astype(np.int64)
        assert np.array_equal(decoded, arr.astype(np.int64))
    finally:
        os.unlink(handoff)
    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize("levels", [_BANDS16, _REVIEW16], ids=["bands", "review_values"])
@pytest.mark.parametrize("byte_order", ["II", "MM"])
def test_16bit_grey_tiff_vectorizes_like_16bit_png(tmp_path, temp_dir, levels, byte_order):
    """A 16-bit grey TIFF in either byte order matches the same pixels as a 16-bit PNG."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    arr = _gray16_bands(levels)
    png16 = _write_gray16(arr, src_dir / "ref16.png", "png")
    tiff = _write_gray16_tiff(arr, src_dir / "img.tiff", byte_order)

    png_result, png_svg = _vectorize(png16, temp_dir)
    result, svg = _vectorize(tiff, temp_dir)

    assert _summary(result) == _summary(png_result)
    assert svg == png_svg
    if levels is _BANDS16:
        oracle = Image.fromarray((arr >> 8).astype(np.uint8), "L")
        _, oracle_svg = _vectorize(_write(oracle, src_dir / "oracle8.png", "PNG"), temp_dir)
        assert result["num_colors"] == len(_BANDS16)
        assert svg == oracle_svg
    assert list(temp_dir.iterdir()) == []


@pytest.mark.parametrize("byte_order", ["MM", "II"])
@pytest.mark.parametrize(
    ("sample_format", "levels", "display_levels"),
    [
        (1, _BANDS16, None),
        (2, _SIGNED_BANDS16, [0, 16, 32, 64, 96, 128]),
        (2, _SIGNED_NEGATIVE16, [0, 0, 0, 0, 16, 64, 128]),
    ],
    ids=["unsigned", "signed_positive", "signed_negative"],
)
def test_api_16bit_grey_tiff_returns_png_equivalent_svg(
    tmp_path, temp_dir, byte_order, sample_format, levels, display_levels
):
    from fastapi.testclient import TestClient

    from api.app import create_app
    from api.dependencies import get_file_registry, get_worker_pool
    from api.file_registry import FileRegistry

    async def _run_inline(fn, *args, macos_runtime=None):
        return fn(*args)

    arr = _gray16_bands(levels)
    png_path = tmp_path / "bands.png"
    if display_levels is None:
        _write_gray16(arr, png_path, "png")
    else:
        # Independent display values: signed native samples scale by 1/256,
        # round to the nearest 8-bit value and saturate negatives to black.
        Image.fromarray(_gray16_bands(display_levels).astype(np.uint8)).save(png_path)
    uploads = {
        "png": ("bands.png", str(png_path), "image/png"),
        "tiff": (
            "bands16.tiff",
            _write_gray16_tiff(arr, tmp_path / "bands16.tiff", byte_order, sample_format=sample_format),
            "image/tiff",
        ),
    }
    app = create_app()
    registry = FileRegistry()
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: SimpleNamespace(
        submit=AsyncMock(side_effect=_run_inline)
    )
    client = TestClient(app)
    bodies, svgs = {}, {}
    try:
        for key, (name, path, ctype) in uploads.items():
            with open(path, "rb") as f:
                response = client.post(
                    "/api/vectorize",
                    files={"image": (name, f.read(), ctype)},
                    data={"params": "{}"},
                )
            assert response.status_code == 200, response.text
            bodies[key] = response.json()
            download = client.get(bodies[key]["svg_url"])
            assert download.status_code == 200
            svgs[key] = download.text
    finally:
        app.dependency_overrides.clear()

    for field in ("width", "height", "num_shapes", "num_colors", "palette"):
        assert bodies["tiff"][field] == bodies["png"][field]
    expected_colors = len(set(display_levels if display_levels is not None else levels))
    assert bodies["tiff"]["num_colors"] == expected_colors
    assert svgs["tiff"] == svgs["png"]
    assert {p.suffix for p in temp_dir.iterdir()} <= {".svg"}


@pytest.mark.parametrize("byte_order", ["II", "MM"])
@pytest.mark.parametrize("levels", [_SIGNED_BANDS16, _SIGNED_NEGATIVE16], ids=["positive", "negative"])
def test_signed16_tiff_handoff_preserves_native_sample_range(
    tmp_path, temp_dir, byte_order, levels
):
    from api.workers.vectorizer_workers import _transcode_for_native_loader

    samples = _gray16_bands(levels)
    source = _write_gray16_tiff(samples, tmp_path / "signed.tiff", byte_order, sample_format=2)
    with Image.open(source) as image:
        assert image.mode == "I"
        assert image.tag_v2[258] == (16,)
        assert image.tag_v2[339] == (2,)

    handoff = _transcode_for_native_loader(source, str(temp_dir))
    try:
        with Image.open(handoff) as image:
            assert image.mode == "I;16"
            np.testing.assert_array_equal(np.asarray(image), np.maximum(samples, 0))
    finally:
        os.unlink(handoff)


@pytest.mark.parametrize(
    ("dtype", "mode", "sample_format"),
    [(np.int32, "I", 2), (np.float32, "F", 3)],
    ids=["integer", "float"],
)
def test_32bit_tiff_keeps_native_unscaled_greys(tmp_path, temp_dir, dtype, mode, sample_format):
    """32-bit integer/float samples must not be reinterpreted as 16-bit."""
    samples = _gray16_bands([0, 64, 128, 255, 1000, 65536]).astype(dtype)
    source = _write(Image.fromarray(samples), tmp_path / "integer32.tiff", "TIFF")
    oracle = _write(
        Image.fromarray(_gray16_bands([0, 64, 128, 255, 255, 255]).astype(np.uint8)),
        tmp_path / "display.png",
        "PNG",
    )
    with Image.open(source) as image:
        assert image.mode == mode
        assert image.tag_v2[258] == (32,)
        assert image.tag_v2[339] == (sample_format,)

    result, svg = _vectorize(source, temp_dir)
    expected, expected_svg = _vectorize(oracle, temp_dir)

    assert _summary(result) == _summary(expected)
    assert svg == expected_svg


@pytest.mark.parametrize("fmt", ["WEBP", "TIFF"])
def test_raster_handoff_preserves_embedded_icc_profile(tmp_path, temp_dir, fmt):
    from PIL import ImageCms

    from api.workers.vectorizer_workers import _transcode_for_native_loader

    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    image = _banded_rgb()
    options = {"lossless": True} if fmt == "WEBP" else {}
    source = _write(image, tmp_path / ("profile." + fmt.lower()), fmt, icc_profile=profile, **options)
    handoff = _transcode_for_native_loader(source, str(temp_dir))
    try:
        with Image.open(handoff) as decoded:
            assert decoded.info["icc_profile"] == profile
            assert decoded.tobytes() == image.tobytes()
    finally:
        os.unlink(handoff)
