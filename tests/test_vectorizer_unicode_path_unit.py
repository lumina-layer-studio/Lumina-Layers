"""Real-native tests for vectorizer image handoff from non-ASCII paths.
非 ASCII 路径下矢量化图像交接的真实原生测试。

On Windows the native path loader cannot open files under non-ASCII
directories (e.g. a Chinese user name in TEMP_DIR), so the worker hands such
files to the native library as encoded bytes. These tests use the real
neroued_vectorizer, not a mock.
"""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import config
from api.app import create_app
from api.dependencies import get_file_registry, get_worker_pool
from api.file_registry import FileRegistry
from api.workers.vectorizer_workers import worker_vectorize

nv = pytest.importorskip("neroued_vectorizer")

_CJK_DIR_NAME = "测试 用户"
_PARAMS = {"num_colors": 4}


def _two_color_image(mode: str = "RGB", size: tuple[int, int] = (64, 32)) -> Image.Image:
    img = Image.new(mode, size, (255, 255, 255, 255) if mode == "RGBA" else (255, 255, 255))
    for x in range(size[0] // 4, size[0] * 3 // 4):
        for y in range(size[1] // 4, size[1] * 3 // 4):
            img.putpixel((x, y), (200, 30, 30, 255) if mode == "RGBA" else (200, 30, 30))
    return img


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    _two_color_image().save(buffer, format="PNG")
    return buffer.getvalue()


def _exif_rotated_jpeg_bytes() -> bytes:
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90 CW for display
    buffer = io.BytesIO()
    _two_color_image(size=(64, 32)).save(buffer, format="JPEG", quality=95, exif=exif)
    return buffer.getvalue()


def _alpha_png_bytes() -> bytes:
    img = _two_color_image(mode="RGBA", size=(40, 24))
    for x in range(0, 10):
        for y in range(24):
            img.putpixel((x, y), (0, 0, 0, 0))
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _write_input(directory: Path, name: str, data: bytes) -> str:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(data)
    return str(path)


def _run_worker(directory: Path, name: str, data: bytes, monkeypatch) -> dict:
    monkeypatch.setattr(config, "TEMP_DIR", str(directory))
    image_path = _write_input(directory, name, data)
    result = worker_vectorize(image_path, dict(_PARAMS))
    assert not Path(image_path).exists()
    Path(result["svg_path"]).unlink()
    return result


@pytest.fixture
def native_inputs(monkeypatch: pytest.MonkeyPatch) -> list[type]:
    """Record the input type of every real native vectorize call."""
    seen: list[type] = []
    real_vectorize = nv.vectorize

    def _spy(image_input, *args, **kwargs):
        seen.append(type(image_input))
        return real_vectorize(image_input, *args, **kwargs)

    monkeypatch.setattr(nv, "vectorize", _spy)
    return seen


class TestWorkerNonAsciiPath:
    def test_png_under_cjk_directory_vectorizes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, native_inputs: list[type]
    ) -> None:
        result = _run_worker(tmp_path / _CJK_DIR_NAME, "tmpinput.png", _png_bytes(), monkeypatch)

        assert (result["width"], result["height"]) == (64, 32)
        assert result["num_shapes"] > 0
        assert native_inputs == [bytes]

    def test_cjk_filename_vectorizes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result = _run_worker(tmp_path / "ascii", "图像.png", _png_bytes(), monkeypatch)

        assert (result["width"], result["height"]) == (64, 32)

    def test_ascii_path_keeps_native_path_handoff(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, native_inputs: list[type]
    ) -> None:
        if not str(tmp_path).isascii():
            pytest.skip("ASCII-path control requires an ASCII temporary root")
        result = _run_worker(tmp_path / "ascii", "tmpinput.png", _png_bytes(), monkeypatch)

        assert (result["width"], result["height"]) == (64, 32)
        assert native_inputs == [str]

    @pytest.mark.parametrize(
        ("name", "data", "expected_size"),
        [
            ("tmpinput.jpg", _exif_rotated_jpeg_bytes(), (64, 32)),
            ("tmpinput.png", _alpha_png_bytes(), (40, 24)),
        ],
        ids=["exif_oriented_jpeg", "alpha_png"],
    )
    def test_decode_matches_ascii_path(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        name: str,
        data: bytes,
        expected_size: tuple[int, int],
    ) -> None:
        ascii_result = _run_worker(tmp_path / "ascii", name, data, monkeypatch)
        cjk_result = _run_worker(tmp_path / _CJK_DIR_NAME, name, data, monkeypatch)

        assert (ascii_result["width"], ascii_result["height"]) == expected_size
        assert (cjk_result["width"], cjk_result["height"]) == expected_size

    def test_undecodable_file_under_cjk_directory_raises_and_cleans_up(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        directory = tmp_path / _CJK_DIR_NAME
        monkeypatch.setattr(config, "TEMP_DIR", str(directory))
        image_path = _write_input(directory, "tmpinput.png", b"not an image")

        with pytest.raises(RuntimeError):
            worker_vectorize(image_path, dict(_PARAMS))

        assert not Path(image_path).exists()

    def test_missing_file_under_cjk_directory_keeps_native_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, native_inputs: list[type]
    ) -> None:
        directory = tmp_path / _CJK_DIR_NAME
        directory.mkdir()
        monkeypatch.setattr(config, "TEMP_DIR", str(directory))

        # Native diagnostic text differs across platform and codec builds.
        with pytest.raises(RuntimeError):
            worker_vectorize(str(directory / "missing.png"), dict(_PARAMS))

        assert native_inputs == [str]


class _InProcessPool:
    async def submit(self, fn, *args, macos_runtime=None):
        return fn(*args)


class TestVectorizeRouteNonAsciiTempDir:
    @pytest.mark.parametrize("fmt", ["JPEG", "WEBP", "TIFF"])
    def test_upload_under_cjk_temp_dir_returns_svg(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, native_inputs: list[type], fmt: str
    ) -> None:
        temp_dir = tmp_path / _CJK_DIR_NAME / "output" / "temp"
        temp_dir.mkdir(parents=True)
        monkeypatch.setattr(config, "TEMP_DIR", str(temp_dir))
        app = create_app()
        registry = FileRegistry()
        app.dependency_overrides[get_file_registry] = lambda: registry
        app.dependency_overrides[get_worker_pool] = lambda: _InProcessPool()
        client = TestClient(app)
        data = io.BytesIO()
        options = {"lossless": True} if fmt == "WEBP" else {}
        _two_color_image().save(data, format=fmt, **options)
        encoded = _exif_rotated_jpeg_bytes() if fmt == "JPEG" else data.getvalue()
        try:
            response = client.post(
                "/api/vectorize",
                files={"image": ("input." + fmt.lower(), encoded, "image/" + fmt.lower())},
                data={"params": '{"num_colors": 4}'},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert (body["width"], body["height"]) == (64, 32)
            svg = client.get(body["svg_url"])
            assert svg.status_code == 200
            assert b"<svg" in svg.content
        finally:
            app.dependency_overrides.clear()

        assert [p.suffix for p in temp_dir.iterdir()] == [".svg"]
        assert native_inputs == [bytes]
