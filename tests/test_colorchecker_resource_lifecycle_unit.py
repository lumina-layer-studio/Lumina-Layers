"""ColorChecker resource lifecycle tests."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from api.colorchecker_artifacts import (
    COLORCHECKER_FULL_PENDING_PURPOSE,
    COLORCHECKER_FULL_PURPOSE,
    COLORCHECKER_SOURCE_PURPOSE,
)
from api.dependencies import get_file_registry, get_session_store
from api.file_registry import FileRegistry
from api.preview_resources import PREVIEW_PUBLIC_PURPOSE
from api.routers.extractor import (
    COLORCHECKER_PROCESSING_FAILED_DETAIL,
    COLORCHECKER_SERVICE_UNAVAILABLE_DETAIL,
)
from api.session_store import SessionStore
from config import COLORCHECKER_TEMP_TTL_SECONDS, IMAGE_PREVIEW_MAX_EDGE

_COLORCHECKER_PREVIEW_UNREADABLE_DETAIL = (
    "ColorChecker preview is unavailable or unreadable. "
    "Re-run ColorChecker calibration and try again."
)
_COLORCHECKER_PREVIEW_GENERATION_FAILED_DETAIL = (
    "ColorChecker preview could not be generated from this image. "
    "Choose a supported image file and try again."
)
_COLORCHECKER_PREVIEW_SERVICE_UNAVAILABLE_DETAIL = (
    "ColorChecker preview service is unavailable. "
    "Check the server ColorChecker dependencies and try again."
)
_COLORCHECKER_PREVIEW_PREPARATION_FAILED_DETAIL = (
    "ColorChecker preview could not be prepared. Please try again."
)
_PREVIEW_ARTIFACT_UNREADABLE_DETAIL = (
    "Preview artifact is unavailable or unreadable. "
    "Re-run the previous step and try again."
)
_COLORCHECKER_UNREADABLE_DETAIL = (
    "ColorChecker calibrated image is unavailable or unreadable. "
    "Recalibrate and try again."
)


def _png_bytes(width: int = 8, height: int = 6) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (128, 96, 64)).save(buffer, format="PNG")
    return buffer.getvalue()


def _custom_reference_patches() -> list[dict[str, object]]:
    return [
        {
            "index": index,
            "label": f"Patch {index}",
            "sRGB": [index, index + 1, index + 2],
        }
        for index in range(1, 25)
    ]


def _client_with_state(
    *,
    raise_server_exceptions: bool = True,
) -> tuple[TestClient, SessionStore, FileRegistry]:
    app = create_app()
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    return TestClient(app, raise_server_exceptions=raise_server_exceptions), store, registry


def _records_for_event(
    caplog: pytest.LogCaptureFixture,
    event_name: str,
) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == event_name
    ]


class _RegisterPathFailingRegistry(FileRegistry):
    """Registry stub that fails while retaining the attempted source path."""

    def __init__(self) -> None:
        super().__init__()
        self.paths: list[str] = []

    def register_path(self, *args: object, **kwargs: object) -> str:
        path = kwargs.get("path")
        if path is None and len(args) >= 2:
            path = args[1]
        if path is not None:
            self.paths.append(str(path))
        raise RuntimeError(
            "colorchecker source registry unavailable at /Users/min/private/source.png"
        )


def _register_colorchecker_source(
    registry: FileRegistry,
    tmp_path,
    *,
    width: int = 8,
    height: int = 6,
) -> str:
    source_path = tmp_path / f"source-{width}x{height}.png"
    Image.new("RGB", (width, height), (128, 96, 64)).save(source_path, format="PNG")
    return registry.register_path(
        "colorchecker-source:test",
        str(source_path),
        source_path.name,
        ttl_seconds=COLORCHECKER_TEMP_TTL_SECONDS,
        is_public=False,
        purpose=COLORCHECKER_SOURCE_PURPOSE,
    )


def _register_bad_colorchecker_full_artifact(
    registry: FileRegistry,
    tmp_path,
) -> tuple[str, str]:
    bad_path = tmp_path / "bad-colorchecker.png"
    bad_path.write_bytes(b"not a png")
    file_id = registry.register_path(
        "colorchecker:test",
        str(bad_path),
        bad_path.name,
        ttl_seconds=COLORCHECKER_TEMP_TTL_SECONDS,
        is_public=False,
        purpose=COLORCHECKER_FULL_PURPOSE,
    )
    return file_id, str(bad_path)


def test_save_upload_to_tempfile_handles_short_os_write(monkeypatch, tmp_path) -> None:
    """Preview upload persistence should retry raw short writes."""
    import api.preview_resources as preview_resources

    payload = b"abcdefghijklmnopqrstuvwxyz"
    original_write = preview_resources.os.write
    written_lengths: list[int] = []

    def short_write(fd: int, data) -> int:  # noqa: ANN001
        chunk = bytes(data[:5])
        written_lengths.append(len(chunk))
        return original_write(fd, chunk)

    monkeypatch.setattr(preview_resources, "TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(preview_resources.os, "write", short_write)

    upload = UploadFile(filename="short-write.bin", file=io.BytesIO(payload))
    path = asyncio.run(preview_resources.save_upload_to_tempfile(upload))
    try:
        with open(path, "rb") as saved:
            assert saved.read() == payload
        assert len(written_lengths) > 1
    finally:
        os.remove(path)


def test_preview_resource_returns_private_source_id_and_bounded_preview() -> None:
    """Preview resource upload should expose only a bounded public preview plus private id."""
    client, _store, registry = _client_with_state()

    response = client.post(
        "/api/system/preview-resources",
        data={"context": "colorchecker"},
        files={"file": ("chart.png", _png_bytes(12, 8), "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    source_id = body["resource_id"]
    assert body["preview_url"].startswith("/api/files/")
    assert body["full_width"] == 12
    assert body["full_height"] == 8
    assert body["preview_width"] == 12
    assert body["preview_height"] == 8

    source_entry = registry.get_entry(source_id)
    assert source_entry is not None
    assert source_entry["is_public"] is False
    assert source_entry["purpose"] == COLORCHECKER_SOURCE_PURPOSE
    preview_entry = registry.get_entry(body["preview_id"])
    assert preview_entry is not None
    assert preview_entry["is_public"] is True
    assert preview_entry["purpose"] == PREVIEW_PUBLIC_PURPOSE
    assert preview_entry["session_id"].endswith(f"{source_id}:role:source")
    assert client.get(f"/api/files/{source_id}").status_code == 404
    assert client.get(body["preview_url"]).status_code == 200

    release_response = client.post(
        "/api/extractor/colorchecker-release",
        data={"file_id": source_id},
    )
    assert release_response.status_code == 200
    assert release_response.json()["released"] is True
    assert registry.resolve(source_id) is None
    assert client.get(body["preview_url"]).status_code == 404


def test_preview_artifact_rejects_unreadable_private_artifact_without_path(
    tmp_path,
) -> None:
    client, _store, registry = _client_with_state()
    file_id, bad_path = _register_bad_colorchecker_full_artifact(registry, tmp_path)

    response = client.post(
        "/api/system/preview-artifacts",
        data={"resource_id": file_id, "context": "colorchecker"},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail == _PREVIEW_ARTIFACT_UNREADABLE_DETAIL
    assert bad_path not in detail
    assert "cannot identify image file" not in detail


def test_preview_resource_upload_rejects_decode_error_without_path(monkeypatch) -> None:
    import core.colorchecker_adapter as adapter

    client, _store, _registry = _client_with_state(raise_server_exceptions=False)
    private_path = "/Users/min/private/chart.tiff"

    def fail_decode(*_args, **_kwargs):
        raise adapter.ColorCheckerCalibrationError(
            f"cannot decode {private_path}: decoder exploded"
        )

    monkeypatch.setattr(adapter, "decode_colorchecker_file", fail_decode)

    response = client.post(
        "/api/system/preview-resources",
        data={"context": "colorchecker"},
        files={"file": ("chart.tiff", b"not an image", "image/tiff")},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == _COLORCHECKER_PREVIEW_GENERATION_FAILED_DETAIL
    assert private_path not in response.text
    assert "decoder exploded" not in response.text


def test_preview_resource_upload_hides_unavailable_error_detail(monkeypatch) -> None:
    import core.colorchecker_adapter as adapter

    client, _store, _registry = _client_with_state(raise_server_exceptions=False)
    private_path = "/Users/min/private/core/colorchecker.py"

    def fail_decode(*_args, **_kwargs):
        raise adapter.ColorCheckerUnavailableError(
            f"cannot import {private_path}"
        )

    monkeypatch.setattr(adapter, "decode_colorchecker_file", fail_decode)

    response = client.post(
        "/api/system/preview-resources",
        data={"context": "colorchecker"},
        files={"file": ("chart.png", _png_bytes(), "image/png")},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == _COLORCHECKER_PREVIEW_SERVICE_UNAVAILABLE_DETAIL
    assert private_path not in response.text
    assert "cannot import" not in response.text


def test_extractor_colorchecker_source_bounds_registry_failure(
    caplog: pytest.LogCaptureFixture,
    monkeypatch,
    tmp_path,
) -> None:
    import api.preview_resources as preview_resources

    monkeypatch.setattr(preview_resources, "TEMP_DIR", str(tmp_path))
    app = create_app()
    registry = _RegisterPathFailingRegistry()
    app.dependency_overrides[get_session_store] = lambda: SessionStore(ttl=1800)
    app.dependency_overrides[get_file_registry] = lambda: registry
    client = TestClient(app, raise_server_exceptions=False)
    app_logger = logging.getLogger("lumina.api.app")
    app_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=app_logger.name)

    try:
        response = client.post(
            "/api/extractor/colorchecker-source",
            files={"image": ("chart.png", _png_bytes(12, 8), "image/png")},
        )
    finally:
        app_logger.removeHandler(caplog.handler)

    assert response.status_code == 500
    assert response.json()["detail"] == _COLORCHECKER_PREVIEW_PREPARATION_FAILED_DETAIL
    assert "colorchecker source registry unavailable" not in response.text
    assert "/Users/min/private" not in response.text
    assert len(registry.paths) == 1
    assert list(tmp_path.iterdir()) == []
    assert _records_for_event(caplog, "api_unhandled_exception") == []


def test_colorchecker_source_keeps_standard_type_hint_for_extensionless_upload(monkeypatch) -> None:
    """Extensionless standard images should still decode through the private source id."""
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state()
    captured: dict[str, object] = {}

    class FakeDetectResult:
        detected = True
        confidence = 1.0
        candidate_count = 1

        def to_response(self) -> dict[str, object]:
            return {
                "detected": True,
                "corners": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 12.0, "y": 0.0},
                    {"x": 12.0, "y": 8.0},
                    {"x": 0.0, "y": 8.0},
                ],
                "patchOrientation": "normal",
                "confidence": 1.0,
                "score": 1.0,
                "mode": "fake",
                "reason": "",
                "candidateCount": 1,
            }

    def fake_detect(image_bgr, **_kwargs):
        captured["shape"] = image_bgr.shape
        return FakeDetectResult()

    monkeypatch.setattr(adapter, "detect_colorchecker_chart", fake_detect)

    source_response = client.post(
        "/api/extractor/colorchecker-source",
        files={"image": ("chart", _png_bytes(12, 8), "image/png")},
    )

    assert source_response.status_code == 200
    source_id = source_response.json()["colorchecker_source_file_id"]
    source_entry = registry.get_entry(source_id)
    assert source_entry is not None
    assert source_entry["filename"].endswith(".png")

    detect_response = client.post(
        "/api/extractor/colorchecker-detect-chart",
        data={"colorchecker_source_file_id": source_id},
    )

    assert detect_response.status_code == 200
    assert captured["shape"] == (8, 12, 3)


def test_colorchecker_source_accepts_extensionless_octet_stream_standard_image(monkeypatch) -> None:
    """Unknown-MIME extensionless standard images should not be forced through RAW."""
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state()
    captured: dict[str, object] = {}

    class FakeDetectResult:
        detected = True
        confidence = 1.0
        candidate_count = 1

        def to_response(self) -> dict[str, object]:
            return {
                "detected": True,
                "corners": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 12.0, "y": 0.0},
                    {"x": 12.0, "y": 8.0},
                    {"x": 0.0, "y": 8.0},
                ],
                "patchOrientation": "normal",
                "confidence": 1.0,
                "score": 1.0,
                "mode": "fake",
                "reason": "",
                "candidateCount": 1,
            }

    def fake_detect(image_bgr, **_kwargs):
        captured["shape"] = image_bgr.shape
        return FakeDetectResult()

    monkeypatch.setattr(adapter, "detect_colorchecker_chart", fake_detect)

    source_response = client.post(
        "/api/extractor/colorchecker-source",
        files={"image": ("chart", _png_bytes(12, 8), "application/octet-stream")},
    )

    assert source_response.status_code == 200
    source_id = source_response.json()["colorchecker_source_file_id"]
    source_entry = registry.get_entry(source_id)
    assert source_entry is not None
    assert source_entry["filename"] == "chart"

    detect_response = client.post(
        "/api/extractor/colorchecker-detect-chart",
        data={"colorchecker_source_file_id": source_id},
    )

    assert detect_response.status_code == 200
    assert captured["shape"] == (8, 12, 3)


def test_colorchecker_source_heic_extension_redecodes_as_standard(tmp_path) -> None:
    """HEIC-like standard sources should not be treated as RAW after registration."""
    from api.routers.extractor import _decode_colorchecker_source

    registry = FileRegistry()
    source_path = tmp_path / "photo.heic"
    source_path.write_bytes(_png_bytes(12, 8))
    source_id = registry.register_path(
        "colorchecker-source:heic",
        str(source_path),
        source_path.name,
        ttl_seconds=COLORCHECKER_TEMP_TTL_SECONDS,
        is_public=False,
        purpose=COLORCHECKER_SOURCE_PURPOSE,
    )

    decoded = _decode_colorchecker_source(registry, source_id)

    assert decoded.source_type == "standard"
    assert decoded.image_bgr.shape == (8, 12, 3)


def test_colorchecker_source_infers_heic_suffix_for_extensionless_upload(tmp_path) -> None:
    """Extensionless HEIC uploads should keep a standard-image type hint."""
    from api.preview_resources import colorchecker_source_registry_filename

    source_path = tmp_path / "upload.tmp"
    source_path.write_bytes(b"fake")

    filename = colorchecker_source_registry_filename(
        SimpleNamespace(filename="chart", content_type="image/heic"),
        str(source_path),
        "standard",
    )

    assert filename == "chart.heic"


def test_preview_artifact_returns_bounded_preview_for_private_source(
    monkeypatch,
    tmp_path,
) -> None:
    """Preview artifact endpoint should expose only a bounded public preview."""
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state()
    source_id = _register_colorchecker_source(registry, tmp_path, width=18, height=10)

    def fake_decode(*_args, **_kwargs):
        return SimpleNamespace(
            image_bgr=np.zeros((10, 18, 3), dtype=np.uint8),
            source_type="standard",
        )

    monkeypatch.setattr(adapter, "decode_colorchecker_file", fake_decode)

    response = client.post(
        "/api/system/preview-artifacts",
        data={"context": "colorchecker", "resource_id": source_id},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["preview_url"].startswith("/api/files/")
    assert body["preview_width"] == 18
    assert body["preview_height"] == 10
    preview_entry = registry.get_entry(body["preview_id"])
    assert preview_entry is not None
    assert preview_entry["is_public"] is True
    assert preview_entry["purpose"] == PREVIEW_PUBLIC_PURPOSE
    assert client.get(body["preview_url"]).status_code == 200


def test_preview_artifact_source_decode_error_uses_safe_detail(
    monkeypatch,
    tmp_path,
) -> None:
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state(raise_server_exceptions=False)
    source_id = _register_colorchecker_source(registry, tmp_path, width=18, height=10)
    private_path = "/Users/min/private/source.png"

    def fail_decode(*_args, **_kwargs):
        raise adapter.ColorCheckerCalibrationError(
            f"cannot decode {private_path}: raw plugin failed"
        )

    monkeypatch.setattr(adapter, "decode_colorchecker_file", fail_decode)

    response = client.post(
        "/api/system/preview-artifacts",
        data={"context": "colorchecker", "resource_id": source_id},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == _COLORCHECKER_PREVIEW_GENERATION_FAILED_DETAIL
    assert private_path not in response.text
    assert "raw plugin failed" not in response.text


def test_colorchecker_source_preserves_raw_extension_when_mime_is_standard(monkeypatch) -> None:
    """RAW-looking filenames should not be relabeled from browser MIME alone."""
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state()
    captured: dict[str, object] = {}

    def fake_decode(*_args, **kwargs):
        captured["file_name"] = kwargs["file_name"]
        return SimpleNamespace(
            image_bgr=np.zeros((8, 12, 3), dtype=np.uint8),
            source_type="raw",
        )

    monkeypatch.setattr(adapter, "decode_colorchecker_file", fake_decode)

    response = client.post(
        "/api/extractor/colorchecker-source",
        files={"image": ("shot.dng", _png_bytes(12, 8), "image/tiff")},
    )

    assert response.status_code == 200
    source_id = response.json()["colorchecker_source_file_id"]
    source_entry = registry.get_entry(source_id)
    assert source_entry is not None
    assert captured["file_name"] == "shot.dng"
    assert source_entry["filename"] == "shot.dng"


def test_colorchecker_calibrate_returns_private_full_id_and_releases(
    monkeypatch,
    tmp_path,
) -> None:
    """Calibration should expose only preview URLs and private full-image id."""
    import core.colorchecker_adapter as adapter
    import api.routers.extractor as extractor_router

    client, _store, registry = _client_with_state()
    calibrated = np.zeros((80, 120, 3), dtype=np.uint8)
    calibrated[:, :] = [10, 120, 240]
    overlay = np.zeros((40, 60, 3), dtype=np.uint8)
    captured: dict[str, object] = {}
    source_id = _register_colorchecker_source(registry, tmp_path, width=8, height=6)

    def fake_decode(*_args, **_kwargs):
        return SimpleNamespace(image_bgr=np.zeros((6, 8, 3), dtype=np.uint8))

    def fake_apply(*args, **kwargs):
        captured["image_shape"] = args[0].shape
        captured["corners"] = args[1]
        captured.update(kwargs)
        return SimpleNamespace(
            calibrated_image=calibrated,
            overlay_image=overlay,
            patch_points=[{"x": 1.0, "y": 2.0}] * 24,
            display_summary={"deltaE00": {"mean": 1.0, "median": 1.0, "p95": 2.0, "max": 3.0}},
        )

    monkeypatch.setattr(adapter, "decode_colorchecker_file", fake_decode)
    monkeypatch.setattr(adapter, "apply_colorchecker_calibration", fake_apply)
    # Windows OpenCV's narrow-path writer may reject a valid Unicode path.
    # Calibration must still save through Python's Unicode-aware filesystem.
    unicode_temp = tmp_path / "软件" / "校色结果"
    unicode_temp.mkdir(parents=True)
    monkeypatch.setattr(extractor_router, "TEMP_DIR", str(unicode_temp))
    monkeypatch.setattr(extractor_router.cv2, "imwrite", lambda *_args: False)
    source_preview_id = registry.register_bytes(
        f"bounded-preview-owner:{source_id}:role:source",
        _png_bytes(120, 80),
        "source-preview.jpg",
        ttl_seconds=COLORCHECKER_TEMP_TTL_SECONDS,
        is_public=True,
        purpose=PREVIEW_PUBLIC_PURPOSE,
    )

    response = client.post(
        "/api/extractor/colorchecker-calibrate",
        data={
            "colorchecker_source_file_id": source_id,
            "corner_points": "[[0,0],[4,0],[4,3],[0,3]]",
            "corner_points_width": "4",
            "corner_points_height": "3",
            "patch_orientation": "flip_horizontal",
            "reference_patches": json.dumps(_custom_reference_patches()),
            "reference_source": json.dumps(
                {
                    "sourceType": "user_upload",
                    "sourceName": "Uploaded reference",
                    "serialNumber": "SN-1",
                }
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "calibrated_url" not in body
    assert body["calibrated_preview_url"].startswith("/api/files/")
    assert body["overlay_url"].startswith("/api/files/")
    assert body["full_width"] == 120
    assert body["full_height"] == 80
    assert body["preview_width"] == 120
    assert body["preview_height"] == 80
    assert captured["image_shape"] == (6, 8, 3)
    assert captured["corners"] == [[0, 0], [8, 0], [8, 6], [0, 6]]
    assert captured["patch_orientation"] == "flip_horizontal"
    assert captured["reference_id"] is None
    assert captured["reference_patches"][0]["sRGB"] == [1, 2, 3]
    assert captured["reference_source"]["sourceName"] == "Uploaded reference"

    assert client.get(f"/api/files/{source_id}").status_code == 404
    source_touch_response = client.post(
        "/api/extractor/colorchecker-touch",
        data={"file_id": source_id},
    )
    assert source_touch_response.status_code == 200
    assert source_touch_response.json()["renewed"] is True

    full_id = body["calibrated_full_file_id"]
    calibrated_preview_id = body["calibrated_preview_file_id"]
    entry = registry.get_entry(full_id)
    assert entry is not None
    assert entry["is_public"] is False
    assert entry["purpose"] == COLORCHECKER_FULL_PENDING_PURPOSE
    assert os.path.exists(entry["path"])
    assert client.get(f"/api/files/{full_id}").status_code == 404
    calibrated_preview_entry = registry.get_entry(calibrated_preview_id)
    assert calibrated_preview_entry is not None
    assert calibrated_preview_entry["session_id"].endswith(f"{full_id}:role:calibrated")
    overlay_preview_entry = registry.get_entry(body["overlay_preview_file_id"])
    assert overlay_preview_entry is not None
    assert overlay_preview_entry["session_id"].endswith(f"{full_id}:role:overlay")

    touch_pending_response = client.post(
        "/api/extractor/colorchecker-touch",
        data={"file_id": full_id},
    )
    assert touch_pending_response.status_code == 200
    assert touch_pending_response.json()["renewed"] is True

    def fail_full_image_load(*_args, **_kwargs):
        raise AssertionError("confirm should reuse the bounded preview")

    monkeypatch.setattr(extractor_router, "load_colorchecker_full_rgb", fail_full_image_load)

    mismatched_preview_id = registry.register_bytes(
        "preview:other",
        _png_bytes(),
        "wrong-preview.jpg",
        ttl_seconds=COLORCHECKER_TEMP_TTL_SECONDS,
        is_public=True,
        purpose=PREVIEW_PUBLIC_PURPOSE,
    )
    mismatch_response = client.post(
        "/api/extractor/colorchecker-confirm",
        data={"file_id": full_id, "preview_file_id": mismatched_preview_id},
    )
    assert mismatch_response.status_code == 422
    assert registry.get_entry(full_id)["purpose"] == COLORCHECKER_FULL_PENDING_PURPOSE

    overlay_mismatch_response = client.post(
        "/api/extractor/colorchecker-confirm",
        data={"file_id": full_id, "preview_file_id": body["overlay_preview_file_id"]},
    )
    assert overlay_mismatch_response.status_code == 422
    assert registry.get_entry(full_id)["purpose"] == COLORCHECKER_FULL_PENDING_PURPOSE

    confirm_response = client.post(
        "/api/extractor/colorchecker-confirm",
        data={
            "file_id": full_id,
            "preview_file_id": calibrated_preview_id,
            "source_file_id": source_id,
            "source_preview_file_id": source_preview_id,
        },
    )
    assert confirm_response.status_code == 200
    confirm_body = confirm_response.json()
    assert confirm_body["confirmed"] is True
    assert confirm_body["calibrated_preview_url"] == body["calibrated_preview_url"]
    assert confirm_body["preview_width"] == 120
    assert confirm_body["preview_height"] == 80
    assert confirm_body["source_preview_url"].startswith("/api/files/")
    assert confirm_body["source_preview_width"] == 120
    assert confirm_body["source_preview_height"] == 80
    confirmed_preview_id = confirm_body["calibrated_preview_url"].rsplit("/", 1)[-1]
    confirmed_preview_entry = registry.get_entry(confirmed_preview_id)
    assert confirmed_preview_entry is not None
    assert confirmed_preview_entry["is_public"] is True
    assert confirmed_preview_entry["ttl_seconds"] == COLORCHECKER_TEMP_TTL_SECONDS
    confirmed_source_preview_id = confirm_body["source_preview_url"].rsplit("/", 1)[-1]
    confirmed_source_preview_entry = registry.get_entry(confirmed_source_preview_id)
    assert confirmed_source_preview_entry is not None
    assert confirmed_source_preview_entry["is_public"] is True
    assert not confirmed_source_preview_entry["session_id"].endswith(f"{full_id}:role:source")
    assert client.get(confirm_body["calibrated_preview_url"]).status_code == 200
    assert client.get(confirm_body["source_preview_url"]).status_code == 200
    confirmed_entry = registry.get_entry(full_id)
    assert confirmed_entry is not None
    assert confirmed_entry["purpose"] == COLORCHECKER_FULL_PURPOSE

    touch_confirmed_response = client.post(
        "/api/extractor/colorchecker-touch",
        data={"file_id": full_id},
    )
    assert touch_confirmed_response.status_code == 200
    assert touch_confirmed_response.json()["renewed"] is True

    source_release_response = client.post(
        "/api/extractor/colorchecker-release",
        data={"file_id": source_id},
    )
    assert source_release_response.status_code == 200
    assert source_release_response.json()["released"] is True
    assert registry.resolve(source_id) is None
    assert client.get(f"/api/files/{source_preview_id}").status_code == 404
    assert client.get(confirm_body["source_preview_url"]).status_code == 200

    release_response = client.post(
        "/api/extractor/colorchecker-release",
        data={"file_id": full_id},
    )
    assert release_response.status_code == 200
    assert release_response.json()["released"] is True
    assert registry.resolve(full_id) is None
    assert os.path.exists(entry["path"]) is False
    assert client.get(body["calibrated_preview_url"]).status_code == 404
    assert client.get(body["overlay_url"]).status_code == 404
    assert client.get(confirm_body["source_preview_url"]).status_code == 200


def test_colorchecker_confirm_rejects_unreadable_source_preview_without_path(
    tmp_path,
) -> None:
    client, _store, registry = _client_with_state()
    full_path = tmp_path / "full.png"
    source_path = tmp_path / "source.png"
    bad_preview_path = tmp_path / "bad-source-preview.jpg"
    Image.new("RGB", (8, 6), (10, 20, 30)).save(full_path, format="PNG")
    Image.new("RGB", (8, 6), (10, 20, 30)).save(source_path, format="PNG")
    bad_preview_path.write_bytes(b"not a preview")
    full_id = registry.register_path(
        "colorchecker:full",
        str(full_path),
        full_path.name,
        ttl_seconds=COLORCHECKER_TEMP_TTL_SECONDS,
        is_public=False,
        purpose=COLORCHECKER_FULL_PENDING_PURPOSE,
    )
    source_id = registry.register_path(
        "colorchecker:source",
        str(source_path),
        source_path.name,
        ttl_seconds=COLORCHECKER_TEMP_TTL_SECONDS,
        is_public=False,
        purpose=COLORCHECKER_SOURCE_PURPOSE,
    )
    source_preview_id = registry.register_path(
        f"bounded-preview-owner:{source_id}:role:source",
        str(bad_preview_path),
        bad_preview_path.name,
        ttl_seconds=COLORCHECKER_TEMP_TTL_SECONDS,
        is_public=True,
        purpose=PREVIEW_PUBLIC_PURPOSE,
    )

    response = client.post(
        "/api/extractor/colorchecker-confirm",
        data={
            "file_id": full_id,
            "source_file_id": source_id,
            "source_preview_file_id": source_preview_id,
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail == _COLORCHECKER_PREVIEW_UNREADABLE_DETAIL
    assert str(bad_preview_path) not in detail
    assert "cannot identify image file" not in detail


def test_colorchecker_confirm_rejects_unreadable_full_artifact_without_path(
    tmp_path,
) -> None:
    client, _store, registry = _client_with_state()
    file_id, bad_path = _register_bad_colorchecker_full_artifact(registry, tmp_path)

    response = client.post(
        "/api/extractor/colorchecker-confirm",
        data={"file_id": file_id},
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail == _COLORCHECKER_UNREADABLE_DETAIL
    assert bad_path not in detail
    assert "cannot identify image file" not in detail


_UNSAFE_JSON_DETAIL_FRAGMENTS = ("Expecting", "line", "column", "char")


@pytest.mark.parametrize(
    ("url", "data", "expected_detail"),
    [
        (
            "/api/extractor/colorchecker-warp-preview",
            {
                "colorchecker_source_file_id": "missing-source",
                "corner_points": "[bad",
            },
            "Invalid corner_points JSON. Check the form value and try again.",
        ),
        (
            "/api/extractor/colorchecker-detect-chart",
            {
                "colorchecker_source_file_id": "missing-source",
                "assist_point": "{bad",
            },
            "Invalid assist_point JSON. Check the form value and try again.",
        ),
        (
            "/api/extractor/colorchecker-detect-chart",
            {
                "colorchecker_source_file_id": "missing-source",
                "reference_patches": "[bad",
            },
            "Invalid reference_patches JSON. Check the form value and try again.",
        ),
        (
            "/api/extractor/colorchecker-detect-chart",
            {
                "colorchecker_source_file_id": "missing-source",
                "reference_patches": json.dumps(_custom_reference_patches()),
                "reference_source": "{bad",
            },
            "Invalid reference_source JSON. Check the form value and try again.",
        ),
        (
            "/api/extractor/colorchecker-calibrate",
            {
                "colorchecker_source_file_id": "missing-source",
                "corner_points": "[bad",
            },
            "Invalid corner_points JSON. Check the form value and try again.",
        ),
        (
            "/api/extractor/colorchecker-calibrate",
            {
                "colorchecker_source_file_id": "missing-source",
                "corner_points": "[[0,0],[4,0],[4,3],[0,3]]",
                "patch_points": "[bad",
            },
            "Invalid patch_points JSON. Check the form value and try again.",
        ),
        (
            "/api/extractor/extract",
            {
                "corner_points": "[bad",
            },
            "Invalid corner_points JSON. Check the form value and try again.",
        ),
    ],
)
def test_colorchecker_json_parse_errors_hide_parser_details(
    url,
    data,
    expected_detail,
) -> None:
    client, _store, _registry = _client_with_state(raise_server_exceptions=False)

    response = client.post(url, data=data)

    assert response.status_code == 422
    assert response.json()["detail"] == expected_detail
    for fragment in _UNSAFE_JSON_DETAIL_FRAGMENTS:
        assert fragment not in response.text


@pytest.mark.parametrize(
    "patch_points",
    [
        [{"x": "bad", "y": 0}],
        [{"x": 1}],
        [{"x": float(i), "y": 0.0} for i in range(23)] + [{"x": "bad", "y": 0.0}],
    ],
)
def test_colorchecker_calibrate_rejects_invalid_patch_points_without_500(
    monkeypatch,
    tmp_path,
    patch_points,
) -> None:
    """Malformed manual patch points are client errors, not server failures."""
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state(raise_server_exceptions=False)
    source_id = _register_colorchecker_source(registry, tmp_path, width=8, height=6)

    def fake_decode(*_args, **_kwargs):
        return SimpleNamespace(
            image_bgr=np.zeros((6, 8, 3), dtype=np.uint8),
            source_type="standard",
        )

    monkeypatch.setattr(adapter, "decode_colorchecker_file", fake_decode)

    response = client.post(
        "/api/extractor/colorchecker-calibrate",
        data={
            "colorchecker_source_file_id": source_id,
            "corner_points": "[[0,0],[4,0],[4,3],[0,3]]",
            "corner_points_width": "4",
            "corner_points_height": "3",
            "patch_points": json.dumps(patch_points),
        },
    )

    assert response.status_code == 422
    assert "patch_points" in response.text


def test_colorchecker_calibrate_rejects_non_array_patch_points_before_source_lookup() -> None:
    client, _store, _registry = _client_with_state(raise_server_exceptions=False)

    response = client.post(
        "/api/extractor/colorchecker-calibrate",
        data={
            "colorchecker_source_file_id": "missing-source",
            "corner_points": "[[0,0],[4,0],[4,3],[0,3]]",
            "patch_points": json.dumps({"x": 1.0, "y": 2.0}),
        },
    )

    assert response.status_code == 422
    assert "patch_points" in response.text


def test_colorchecker_calibrate_accepts_manual_patch_point_pairs(
    monkeypatch,
    tmp_path,
) -> None:
    """Route validation must preserve the core contract accepting [x, y] pairs."""
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state()
    source_id = _register_colorchecker_source(registry, tmp_path, width=8, height=6)
    patch_points = [[float(i), 1.0] for i in range(24)]
    captured: dict[str, object] = {}

    def fake_decode(*_args, **_kwargs):
        return SimpleNamespace(
            image_bgr=np.zeros((6, 8, 3), dtype=np.uint8),
            source_type="standard",
        )

    def fake_apply(*_args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            calibrated_image=np.zeros((8, 12, 3), dtype=np.uint8),
            overlay_image=np.zeros((4, 6, 3), dtype=np.uint8),
            patch_points=[{"x": 1.0, "y": 2.0}] * 24,
            display_summary={"deltaE00": {"mean": 1.0}},
        )

    monkeypatch.setattr(adapter, "decode_colorchecker_file", fake_decode)
    monkeypatch.setattr(adapter, "apply_colorchecker_calibration", fake_apply)

    response = client.post(
        "/api/extractor/colorchecker-calibrate",
        data={
            "colorchecker_source_file_id": source_id,
            "corner_points": "[[0,0],[4,0],[4,3],[0,3]]",
            "corner_points_width": "4",
            "corner_points_height": "3",
            "patch_points": json.dumps(patch_points),
        },
    )

    assert response.status_code == 200
    assert captured["patch_points"] == patch_points


def test_colorchecker_calibrate_passes_raw_source_path_to_core(
    monkeypatch,
    tmp_path,
) -> None:
    """RAW calibration should keep the core on its strict RAW file path."""
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state()
    source_path = tmp_path / "shot.dng"
    source_path.write_bytes(b"fake raw")
    source_id = registry.register_path(
        "colorchecker-source:raw",
        str(source_path),
        "shot.dng",
        ttl_seconds=COLORCHECKER_TEMP_TTL_SECONDS,
        is_public=False,
        purpose=COLORCHECKER_SOURCE_PURPOSE,
    )
    captured: dict[str, object] = {}

    def fake_decode(path, **kwargs):
        captured["decoded_path"] = path
        captured["decoded_file_name"] = kwargs["file_name"]
        return SimpleNamespace(
            image_bgr=np.zeros((6, 8, 3), dtype=np.uint8),
            source_type="raw",
        )

    def fake_apply(*args, **kwargs):
        captured["calibration_image"] = args[0]
        captured["corners"] = args[1]
        captured.update(kwargs)
        return SimpleNamespace(
            calibrated_image=np.zeros((8, 12, 3), dtype=np.uint8),
            overlay_image=np.zeros((4, 6, 3), dtype=np.uint8),
            patch_points=[{"x": 1.0, "y": 2.0}] * 24,
            display_summary={
                "deltaE00": {"mean": 1.0, "median": 1.0, "p95": 2.0, "max": 3.0}
            },
        )

    monkeypatch.setattr(adapter, "decode_colorchecker_file", fake_decode)
    monkeypatch.setattr(adapter, "apply_colorchecker_calibration", fake_apply)

    response = client.post(
        "/api/extractor/colorchecker-calibrate",
        data={
            "colorchecker_source_file_id": source_id,
            "corner_points": "[[0,0],[4,0],[4,3],[0,3]]",
            "corner_points_width": "4",
            "corner_points_height": "3",
        },
    )

    assert response.status_code == 200
    assert captured["decoded_path"] == str(source_path)
    assert captured["decoded_file_name"] == "shot.dng"
    assert captured["calibration_image"] == str(source_path)
    assert captured["file_name"] == "shot.dng"
    assert captured["mime_type"] == "application/octet-stream"
    assert captured["corners"] == [[0, 0], [8, 0], [8, 6], [0, 6]]


def test_colorchecker_calibrate_hides_unavailable_error_detail(
    monkeypatch,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state(raise_server_exceptions=False)
    source_id = _register_colorchecker_source(registry, tmp_path, width=16, height=8)
    private_path = "/Users/min/private/core/colorchecker.py"

    def fake_decode(*_args, **_kwargs):
        return SimpleNamespace(image_bgr=np.zeros((8, 16, 3), dtype=np.uint8))

    def fail_apply(*_args, **_kwargs):
        raise adapter.ColorCheckerUnavailableError(
            f"cannot import {private_path}"
        )

    monkeypatch.setattr(adapter, "decode_colorchecker_file", fake_decode)
    monkeypatch.setattr(adapter, "apply_colorchecker_calibration", fail_apply)

    target_logger = logging.getLogger("lumina.api.routers.extractor")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=target_logger.name)
    try:
        response = client.post(
            "/api/extractor/colorchecker-calibrate",
            data={
                "colorchecker_source_file_id": source_id,
                "corner_points": "[[0,0],[8,0],[8,4],[0,4]]",
                "corner_points_width": "8",
                "corner_points_height": "4",
            },
        )
    finally:
        target_logger.removeHandler(caplog.handler)

    assert response.status_code == 500
    assert response.json()["detail"] == COLORCHECKER_SERVICE_UNAVAILABLE_DETAIL
    assert private_path not in response.text
    assert "cannot import" not in response.text

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "extractor_colorchecker_calibrate_failed"
    ]
    assert len(records) == 1
    assert records[0].status_code == 500
    assert records[0].error_type == "ColorCheckerUnavailableError"
    assert private_path in records[0].error_message


def test_colorchecker_calibrate_hides_calibration_error_detail(
    monkeypatch,
    tmp_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state(raise_server_exceptions=False)
    source_id = _register_colorchecker_source(registry, tmp_path, width=16, height=8)
    private_path = "/Users/min/private/chart.png"

    def fake_decode(*_args, **_kwargs):
        return SimpleNamespace(image_bgr=np.zeros((8, 16, 3), dtype=np.uint8))

    def fail_apply(*_args, **_kwargs):
        raise adapter.ColorCheckerCalibrationError(
            f"cannot solve chart at {private_path}: singular matrix"
        )

    monkeypatch.setattr(adapter, "decode_colorchecker_file", fake_decode)
    monkeypatch.setattr(adapter, "apply_colorchecker_calibration", fail_apply)

    target_logger = logging.getLogger("lumina.api.routers.extractor")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=target_logger.name)
    try:
        response = client.post(
            "/api/extractor/colorchecker-calibrate",
            data={
                "colorchecker_source_file_id": source_id,
                "corner_points": "[[0,0],[8,0],[8,4],[0,4]]",
                "corner_points_width": "8",
                "corner_points_height": "4",
            },
        )
    finally:
        target_logger.removeHandler(caplog.handler)

    assert response.status_code == 422
    assert response.json()["detail"] == COLORCHECKER_PROCESSING_FAILED_DETAIL
    assert private_path not in response.text
    assert "singular matrix" not in response.text

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "extractor_colorchecker_calibrate_failed"
    ]
    assert len(records) == 1
    assert records[0].status_code == 422
    assert records[0].error_type == "ColorCheckerCalibrationError"
    assert private_path in records[0].error_message


def test_colorchecker_warp_preview_uses_colorchecker_ttl(monkeypatch, tmp_path) -> None:
    """Warp preview should use the ColorChecker artifact TTL constant."""
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state()

    def fake_decode(*_args, **_kwargs):
        return SimpleNamespace(image_bgr=np.zeros((8, 16, 3), dtype=np.uint8))

    captured: dict[str, object] = {}

    def fake_warp(*args, **kwargs):
        captured["corner_points"] = args[1]
        captured.update(kwargs)
        return SimpleNamespace(
            preview_png=_png_bytes(),
            preview_width=8,
            preview_height=6,
            auto_patch_points=[],
        )

    source_id = _register_colorchecker_source(registry, tmp_path, width=16, height=8)
    monkeypatch.setattr(adapter, "decode_colorchecker_file", fake_decode)
    monkeypatch.setattr(adapter, "warp_colorchecker_preview", fake_warp)

    response = client.post(
        "/api/extractor/colorchecker-warp-preview",
        data={
            "colorchecker_source_file_id": source_id,
            "corner_points": "[[0,0],[8,0],[8,4],[0,4]]",
            "corner_points_width": "8",
            "corner_points_height": "4",
            "patch_orientation": "rotate_180",
        },
    )

    assert response.status_code == 200
    preview_id = response.json()["preview_url"].rsplit("/", 1)[-1]
    entry = registry.get_entry(preview_id)
    assert entry is not None
    assert entry["ttl_seconds"] == COLORCHECKER_TEMP_TTL_SECONDS
    assert captured["corner_points"] == [[0, 0], [16, 0], [16, 8], [0, 8]]
    assert captured["patch_orientation"] == "rotate_180"


def test_colorchecker_warp_preview_hides_core_error_detail(
    monkeypatch,
    tmp_path,
) -> None:
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state(raise_server_exceptions=False)
    source_id = _register_colorchecker_source(registry, tmp_path, width=16, height=8)
    private_path = "/Users/min/private/chart.png"

    def fake_decode(*_args, **_kwargs):
        return SimpleNamespace(image_bgr=np.zeros((8, 16, 3), dtype=np.uint8))

    def fail_warp(*_args, **_kwargs):
        raise adapter.ColorCheckerCalibrationError(
            f"cannot warp {private_path}: singular matrix"
        )

    monkeypatch.setattr(adapter, "decode_colorchecker_file", fake_decode)
    monkeypatch.setattr(adapter, "warp_colorchecker_preview", fail_warp)

    response = client.post(
        "/api/extractor/colorchecker-warp-preview",
        data={
            "colorchecker_source_file_id": source_id,
            "corner_points": "[[0,0],[8,0],[8,4],[0,4]]",
            "corner_points_width": "8",
            "corner_points_height": "4",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == COLORCHECKER_PROCESSING_FAILED_DETAIL
    assert private_path not in response.text
    assert "singular matrix" not in response.text


def test_colorchecker_detect_uses_private_source_and_preview_coordinates(
    monkeypatch,
    tmp_path,
) -> None:
    """Auto-detected full-image corners should be returned in preview space."""
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state()
    source_id = _register_colorchecker_source(registry, tmp_path, width=16, height=8)
    captured: dict[str, object] = {}

    def fake_decode(*_args, **_kwargs):
        return SimpleNamespace(image_bgr=np.zeros((1000, 2000, 3), dtype=np.uint8))

    def fake_detect(*_args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            detected=True,
            corners=[
                {"x": 0.0, "y": 0.0},
                {"x": 2000.0, "y": 0.0},
                {"x": 2000.0, "y": 1000.0},
                {"x": 0.0, "y": 1000.0},
            ],
            patch_orientation="normal",
            confidence=0.9,
            score=0.1,
            mode="auto",
            reason="",
            candidate_count=1,
            to_response=lambda: {
                "detected": True,
                "corners": [
                    {"x": 0.0, "y": 0.0},
                    {"x": 2000.0, "y": 0.0},
                    {"x": 2000.0, "y": 1000.0},
                    {"x": 0.0, "y": 1000.0},
                ],
                "patchOrientation": "normal",
                "confidence": 0.9,
                "score": 0.1,
                "mode": "auto",
                "reason": "",
                "candidateCount": 1,
            },
        )

    monkeypatch.setattr(adapter, "decode_colorchecker_file", fake_decode)
    monkeypatch.setattr(adapter, "detect_colorchecker_chart", fake_detect)

    response = client.post(
        "/api/extractor/colorchecker-detect-chart",
        data={
            "colorchecker_source_file_id": source_id,
            "reference_patches": json.dumps(_custom_reference_patches()),
            "reference_source": json.dumps({"sourceName": "Detect upload"}),
        },
    )

    assert response.status_code == 200
    body = response.json()
    expected_preview_width = int(IMAGE_PREVIEW_MAX_EDGE)
    expected_preview_height = int(IMAGE_PREVIEW_MAX_EDGE / 2)
    assert body["preview_width"] == expected_preview_width
    assert body["preview_height"] == expected_preview_height
    assert body["corners"] == [
        {"x": 0.0, "y": 0.0},
        {"x": float(expected_preview_width), "y": 0.0},
        {"x": float(expected_preview_width), "y": float(expected_preview_height)},
        {"x": 0.0, "y": float(expected_preview_height)},
    ]
    assert captured["assist_point"] is None
    assert captured["reference_id"] is None
    assert captured["reference_patches"][0]["sRGB"] == [1, 2, 3]
    assert captured["reference_source"]["sourceName"] == "Detect upload"


def test_colorchecker_detect_hides_unavailable_error_detail(
    monkeypatch,
    tmp_path,
) -> None:
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state(raise_server_exceptions=False)
    source_id = _register_colorchecker_source(registry, tmp_path, width=16, height=8)
    private_path = "/Users/min/private/core/colorchecker.py"

    def fake_decode(*_args, **_kwargs):
        return SimpleNamespace(image_bgr=np.zeros((8, 16, 3), dtype=np.uint8))

    def fail_detect(*_args, **_kwargs):
        raise adapter.ColorCheckerUnavailableError(
            f"cannot import {private_path}"
        )

    monkeypatch.setattr(adapter, "decode_colorchecker_file", fake_decode)
    monkeypatch.setattr(adapter, "detect_colorchecker_chart", fail_detect)

    response = client.post(
        "/api/extractor/colorchecker-detect-chart",
        data={"colorchecker_source_file_id": source_id},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == COLORCHECKER_SERVICE_UNAVAILABLE_DETAIL
    assert private_path not in response.text
    assert "cannot import" not in response.text


def test_colorchecker_detect_rejects_ambiguous_reference_selection(
    monkeypatch,
    tmp_path,
) -> None:
    """Detect endpoint should require reference_id xor custom reference patches."""
    import core.colorchecker_adapter as adapter

    client, _store, registry = _client_with_state()
    source_id = _register_colorchecker_source(registry, tmp_path, width=16, height=8)

    def fake_decode(*_args, **_kwargs):
        return SimpleNamespace(image_bgr=np.zeros((8, 16, 3), dtype=np.uint8))

    monkeypatch.setattr(adapter, "decode_colorchecker_file", fake_decode)

    response = client.post(
        "/api/extractor/colorchecker-detect-chart",
        data={
            "colorchecker_source_file_id": source_id,
            "reference_id": "dafan",
            "reference_patches": json.dumps(_custom_reference_patches()),
        },
    )

    assert response.status_code == 422
    assert "mutually exclusive" in response.json()["detail"]


def test_extractor_uses_private_colorchecker_image_and_scales_points(
    tmp_path,
    monkeypatch,
) -> None:
    """LUT extraction should read the private full image without uploading it."""
    import api.routers.extractor as extractor_router

    client, _store, registry = _client_with_state()
    full_image_path = tmp_path / "full.png"
    Image.new("RGB", (40, 20), (10, 20, 30)).save(full_image_path, format="PNG")
    full_id = registry.register_path(
        "colorchecker:test",
        str(full_image_path),
        "full.png",
        ttl_seconds=600,
        is_public=False,
        purpose=COLORCHECKER_FULL_PURPOSE,
    )
    pending_id = registry.register_path(
        "colorchecker:pending",
        str(full_image_path),
        "pending.png",
        ttl_seconds=600,
        is_public=False,
        purpose=COLORCHECKER_FULL_PENDING_PURPOSE,
    )
    lut_path = tmp_path / "lut.json"
    lut_path.write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run_extraction(**kwargs):
        captured.update(kwargs)
        return (
            np.zeros((4, 4, 3), dtype=np.uint8),
            np.zeros((4, 4, 3), dtype=np.uint8),
            str(lut_path),
            "ok",
        )

    monkeypatch.setattr(extractor_router, "run_extraction", fake_run_extraction)

    pending_response = client.post(
        "/api/extractor/extract",
        data={
            "corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "colorchecker_calibrated_file_id": pending_id,
            "corner_points_width": "10",
            "corner_points_height": "10",
        },
    )
    assert pending_response.status_code == 404
    assert captured == {}

    auto_wb_response = client.post(
        "/api/extractor/extract",
        data={
            "corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "colorchecker_calibrated_file_id": full_id,
            "corner_points_width": "10",
            "corner_points_height": "10",
            "auto_wb": "true",
        },
    )
    assert auto_wb_response.status_code == 422
    assert "auto_wb" in auto_wb_response.json()["detail"]
    assert captured == {}

    response = client.post(
        "/api/extractor/extract",
        data={
            "corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "colorchecker_calibrated_file_id": full_id,
            "corner_points_width": "10",
            "corner_points_height": "10",
        },
    )

    assert response.status_code == 200
    assert captured["img"].shape == (20, 40, 3)
    assert captured["points"] == [[0, 0], [40, 0], [40, 20], [0, 20]]
    assert captured["auto_wb"] is False


def test_extract_rejects_unreadable_colorchecker_full_artifact_without_path(
    tmp_path,
    monkeypatch,
) -> None:
    import api.routers.extractor as extractor_router

    client, _store, registry = _client_with_state()
    file_id, bad_path = _register_bad_colorchecker_full_artifact(registry, tmp_path)
    captured: dict[str, object] = {}

    def fake_run_extraction(**kwargs):
        captured.update(kwargs)
        raise AssertionError("extract should stop before running LUT extraction")

    monkeypatch.setattr(extractor_router, "run_extraction", fake_run_extraction)

    response = client.post(
        "/api/extractor/extract",
        data={
            "corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "colorchecker_calibrated_file_id": file_id,
            "corner_points_width": "10",
            "corner_points_height": "10",
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail == _COLORCHECKER_UNREADABLE_DETAIL
    assert bad_path not in detail
    assert "cannot identify image file" not in detail
    assert captured == {}


def test_stage_a_uses_private_colorchecker_images_only_when_restored(
    tmp_path,
    monkeypatch,
) -> None:
    """Stage A should require explicit restored source for ColorChecker images."""
    import api.routers.single_stage as single_stage_router

    client, _store, registry = _client_with_state()
    white_path = tmp_path / "white.png"
    black_path = tmp_path / "black.png"
    Image.new("RGB", (40, 20), (200, 200, 200)).save(white_path, format="PNG")
    Image.new("RGB", (80, 40), (20, 20, 20)).save(black_path, format="PNG")
    white_id = registry.register_path(
        "colorchecker:white",
        str(white_path),
        "white.png",
        ttl_seconds=600,
        is_public=False,
        purpose=COLORCHECKER_FULL_PURPOSE,
    )
    black_id = registry.register_path(
        "colorchecker:black",
        str(black_path),
        "black.png",
        ttl_seconds=600,
        is_public=False,
        purpose=COLORCHECKER_FULL_PURPOSE,
    )
    pending_white_id = registry.register_path(
        "colorchecker:white:pending",
        str(white_path),
        "white-pending.png",
        ttl_seconds=600,
        is_public=False,
        purpose=COLORCHECKER_FULL_PENDING_PURPOSE,
    )
    params_path = tmp_path / "params.json"
    params_path.write_text("{}", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_extract(
        white_rgb,
        black_rgb,
        white_points,
        black_points,
        zip_path,
        **kwargs,
    ):
        captured.update(
            {
                "white_shape": white_rgb.shape,
                "black_shape": black_rgb.shape,
                "white_points": white_points,
                "black_points": black_points,
                "image_source": kwargs.get("image_source"),
                "zip_path": zip_path,
            }
        )
        return SimpleNamespace(
            params_path=str(params_path),
            params_payload={},
            fit_summary={
                "substrate_count": 2,
                "channel_count": 3,
                "orientation_ranking": None,
            },
            material_summary={
                "sample_count": 2,
                "per_substrate_sample_count": 1,
                "grid_rows": 1,
                "grid_cols": 1,
                "layer_height_mm": 0.2,
            },
            source_summary={},
            warnings=[],
            white_warp_rgb=np.zeros((4, 4, 3), dtype=np.uint8),
            black_warp_rgb=np.zeros((4, 4, 3), dtype=np.uint8),
        )

    monkeypatch.setattr(
        single_stage_router,
        "extract_stage_a_material_from_gradient_cards",
        fake_extract,
    )

    raw_response = client.post(
        "/api/extractor/extract-gradient-card-stage-a",
        data={
            "white_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "black_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "white_colorchecker_file_id": white_id,
            "black_colorchecker_file_id": black_id,
            "image_source": "raw",
        },
        files={
            "white_image": ("white.png", _png_bytes(), "image/png"),
            "black_image": ("black.png", _png_bytes(), "image/png"),
            "dataset_zip": ("kit.zip", b"zip", "application/zip"),
        },
    )
    assert raw_response.status_code == 422
    assert captured == {}

    mixed_response = client.post(
        "/api/extractor/extract-gradient-card-stage-a",
        data={
            "white_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "black_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "white_colorchecker_file_id": white_id,
            "white_corner_points_width": "10",
            "white_corner_points_height": "10",
            "image_source": "restored",
        },
        files={
            "black_image": ("black.png", _png_bytes(), "image/png"),
            "dataset_zip": ("kit.zip", b"zip", "application/zip"),
        },
    )
    assert mixed_response.status_code == 422
    assert captured == {}

    restored_upload_response = client.post(
        "/api/extractor/extract-gradient-card-stage-a",
        data={
            "white_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "black_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "image_source": "restored",
        },
        files={
            "white_image": ("white.png", _png_bytes(), "image/png"),
            "black_image": ("black.png", _png_bytes(), "image/png"),
            "dataset_zip": ("kit.zip", b"zip", "application/zip"),
        },
    )
    assert restored_upload_response.status_code == 422
    assert captured == {}

    pending_response = client.post(
        "/api/extractor/extract-gradient-card-stage-a",
        data={
            "white_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "black_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "white_colorchecker_file_id": pending_white_id,
            "black_colorchecker_file_id": black_id,
            "white_corner_points_width": "10",
            "white_corner_points_height": "10",
            "black_corner_points_width": "10",
            "black_corner_points_height": "10",
            "image_source": "restored",
        },
        files={
            "dataset_zip": ("kit.zip", b"zip", "application/zip"),
        },
    )
    assert pending_response.status_code == 404
    assert captured == {}

    response = client.post(
        "/api/extractor/extract-gradient-card-stage-a",
        data={
            "white_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "black_corner_points": "[[0,0],[10,0],[10,10],[0,10]]",
            "white_colorchecker_file_id": white_id,
            "black_colorchecker_file_id": black_id,
            "white_corner_points_width": "10",
            "white_corner_points_height": "10",
            "black_corner_points_width": "10",
            "black_corner_points_height": "10",
            "image_source": "restored",
        },
        files={
            "dataset_zip": ("kit.zip", b"zip", "application/zip"),
        },
    )

    assert response.status_code == 200
    assert captured["white_shape"] == (20, 40, 3)
    assert captured["black_shape"] == (40, 80, 3)
    assert captured["white_points"] == [[0, 0], [40, 0], [40, 20], [0, 20]]
    assert captured["black_points"] == [[0, 0], [80, 0], [80, 40], [0, 40]]
    assert captured["image_source"] == "restored"
