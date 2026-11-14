"""Integration tests for system router structured log canaries."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from api.app import create_app
from api.dependencies import get_file_registry
from api.file_registry import FileRegistry
from api.schemas.system import UserSettings


_IMAGE_PREVIEW_PREPARATION_FAILED_DETAIL = (
    "Image preview could not be prepared. Please try again."
)
_COLORCHECKER_PREVIEW_PREPARATION_FAILED_DETAIL = (
    "ColorChecker preview could not be prepared. Please try again."
)


def _client_with_registry() -> tuple[TestClient, FileRegistry]:
    app = create_app()
    registry = FileRegistry()
    app.dependency_overrides[get_file_registry] = lambda: registry
    return TestClient(app), registry


def _capture_system_logger(caplog: pytest.LogCaptureFixture) -> logging.Logger:
    target_logger = logging.getLogger("lumina.api.routers.system")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=target_logger.name)
    return target_logger


def _capture_app_logger(caplog: pytest.LogCaptureFixture) -> logging.Logger:
    target_logger = logging.getLogger("lumina.api.app")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=target_logger.name)
    return target_logger


def _records_for_event(
    caplog: pytest.LogCaptureFixture,
    event_name: str,
) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == event_name
    ]


def _png_bytes(width: int = 4, height: int = 4) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


class _RegisterPathFailingRegistry(FileRegistry):
    """Registry stub that records the preview path before failing."""

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
            "preview registry unavailable at /Users/min/private/preview.png"
        )


class _TrackingRegistry(FileRegistry):
    """Registry stub that exposes registered preview ids for cleanup checks."""

    def __init__(self) -> None:
        super().__init__()
        self.file_ids: list[str] = []

    def register_path(self, *args: object, **kwargs: object) -> str:
        file_id = super().register_path(*args, **kwargs)
        self.file_ids.append(file_id)
        return file_id


_HEIC_UNREADABLE_DETAIL = (
    "HEIC/HEIF 文件解码失败: 请重新上传有效的 HEIC/HEIF 图片，"
    "或先转换为 PNG/JPEG 后再试。"
)
_RAW_UNREADABLE_DETAIL = (
    "RAW 文件解码失败: 请重新上传有效的 RAW 图片，或先转换为 PNG/JPEG 后再试。"
)
_HEIC_UNSUPPORTED_DETAIL = (
    "当前环境暂不支持 HEIC/HEIF 图片，请先转换为 PNG/JPEG 后再上传。"
)
_RAW_UNSUPPORTED_DETAIL = (
    "当前环境暂不支持 RAW 图片，请先转换为 PNG/JPEG 后再上传。"
)
_UNREADABLE_IMAGE_FORBIDDEN_FRAGMENTS = (
    "cannot identify image file",
    "Input/output error",
    "LibRaw",
    "output/temp",
)
_OPTIONAL_DEPENDENCY_FORBIDDEN_FRAGMENTS = (
    "pip install",
    "pillow-heif",
    "rawpy",
)


class TestSystemImagePreviewCanary:
    """Sessionless endpoint canary verifies session_id is not bound."""

    def test_preview_decodes_actual_format_instead_of_trusting_png_filename(self) -> None:
        pillow_heif = pytest.importorskip("pillow_heif")
        buffer = io.BytesIO()
        pillow_heif.from_pillow(Image.new("RGB", (24, 16), "red")).save(buffer)
        client, registry = _client_with_registry()
        try:
            response = client.post(
                "/api/system/image-preview",
                files={"file": ("misnamed.png", buffer.getvalue(), "image/png")},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            preview = client.get(body["preview_url"])
            assert preview.status_code == 200
            assert preview.content.startswith(b"\x89PNG\r\n\x1a\n")
            with Image.open(io.BytesIO(preview.content)) as image:
                assert image.size == (24, 16)
                assert (body["width"], body["height"]) == image.size
        finally:
            registry.clear_all()

    def test_image_preview_emits_sessionless_contract_canary(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        client, registry = _client_with_registry()
        target_logger = _capture_system_logger(caplog)
        try:
            response = client.post(
                "/api/system/image-preview",
                files={"file": ("preview_input.png", _png_bytes(6, 5), "image/png")},
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["preview_url"].startswith("/api/files/")
        assert body["width"] == 6
        assert body["height"] == 5

        records = _records_for_event(caplog, "system_image_preview_done")
        assert len(records) == 1
        record = records[0]
        file_id = body["preview_url"].rsplit("/", 1)[-1]
        registered = registry.get_entry(file_id)

        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.original_filename == "preview_input.png"
        assert record.file_id == file_id
        assert record.image_width == 6
        assert record.image_height == 5
        assert registered is not None
        assert record.file_size_bytes == Path(str(registered["path"])).stat().st_size

    def test_invalid_image_preview_cleans_temp_file_and_hides_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
        client, registry = _client_with_registry()

        response = client.post(
            "/api/system/image-preview",
            files={"file": ("bad.png", b"not a real image", "image/png")},
        )

        assert response.status_code == 422, response.text
        assert response.json()["detail"] == "无法读取图片尺寸：无效或损坏的图片文件"
        assert str(tmp_path) not in response.text
        assert list(tmp_path.iterdir()) == []
        assert registry.get_session_entries("preview.png") == {}

    def test_registration_failure_returns_readable_error_and_cleans_temp(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
        app = create_app()
        registry = _RegisterPathFailingRegistry()
        app.dependency_overrides[get_file_registry] = lambda: registry
        client = TestClient(app, raise_server_exceptions=False)
        system_logger = _capture_system_logger(caplog)
        app_logger = _capture_app_logger(caplog)
        try:
            response = client.post(
                "/api/system/image-preview",
                files={"file": ("preview_input.png", _png_bytes(6, 5), "image/png")},
            )
        finally:
            system_logger.removeHandler(caplog.handler)
            app_logger.removeHandler(caplog.handler)

        assert response.status_code == 500
        assert response.json()["detail"] == _IMAGE_PREVIEW_PREPARATION_FAILED_DETAIL
        assert "preview registry unavailable" not in response.text
        assert "/Users/min/private" not in response.text
        assert len(registry.paths) == 1
        assert list(tmp_path.iterdir()) == []
        records = _records_for_event(caplog, "system_image_preview_registration_failed")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.ERROR
        assert record.error_type == "RuntimeError"
        assert (
            record.error_message
            == "preview registry unavailable at /Users/min/private/preview.png"
        )
        assert record.original_filename == "preview_input.png"
        assert _records_for_event(caplog, "api_unhandled_exception") == []

    def test_post_registration_failure_rolls_back_registry_file(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
        app = create_app()
        registry = _TrackingRegistry()
        app.dependency_overrides[get_file_registry] = lambda: registry
        client = TestClient(app, raise_server_exceptions=False)

        def fail_getsize(_path: str) -> int:
            raise OSError("stat failed at /Users/min/private/preview.png")

        monkeypatch.setattr("api.routers.system.os.path.getsize", fail_getsize)
        system_logger = _capture_system_logger(caplog)
        app_logger = _capture_app_logger(caplog)
        try:
            response = client.post(
                "/api/system/image-preview",
                files={"file": ("preview_input.png", _png_bytes(6, 5), "image/png")},
            )
        finally:
            system_logger.removeHandler(caplog.handler)
            app_logger.removeHandler(caplog.handler)

        assert response.status_code == 500
        assert response.json()["detail"] == _IMAGE_PREVIEW_PREPARATION_FAILED_DETAIL
        assert "stat failed" not in response.text
        assert "/Users/min/private" not in response.text
        assert len(registry.file_ids) == 1
        assert registry.get_entry(registry.file_ids[0]) is None
        assert list(tmp_path.iterdir()) == []
        records = _records_for_event(caplog, "system_image_preview_registration_failed")
        assert len(records) == 1
        assert records[0].error_type == "OSError"
        assert records[0].error_message == "stat failed at /Users/min/private/preview.png"
        assert _records_for_event(caplog, "api_unhandled_exception") == []

    def test_preview_resource_registration_failure_returns_readable_error(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr("api.preview_resources.TEMP_DIR", str(tmp_path))
        app = create_app()
        registry = _RegisterPathFailingRegistry()
        app.dependency_overrides[get_file_registry] = lambda: registry
        client = TestClient(app, raise_server_exceptions=False)
        app_logger = _capture_app_logger(caplog)
        try:
            response = client.post(
                "/api/system/preview-resources",
                data={"context": "colorchecker"},
                files={"file": ("chart.png", _png_bytes(6, 5), "image/png")},
            )
        finally:
            app_logger.removeHandler(caplog.handler)

        assert response.status_code == 500
        assert response.json()["detail"] == _COLORCHECKER_PREVIEW_PREPARATION_FAILED_DETAIL
        assert "preview registry unavailable" not in response.text
        assert "/Users/min/private" not in response.text
        assert len(registry.paths) == 1
        assert list(tmp_path.iterdir()) == []
        assert _records_for_event(caplog, "api_unhandled_exception") == []

    def test_heic_conversion_failure_cleans_temp_files_at_api_boundary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        payload = _png_bytes()

        def fail_save(self, path, *args, **kwargs):  # noqa: ANN001
            raise RuntimeError("simulated conversion save failure")

        monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
        monkeypatch.setattr("api.file_bridge.HAS_HEIF", True)
        monkeypatch.setattr(Image.Image, "save", fail_save)
        client, registry = _client_with_registry()

        response = client.post(
            "/api/system/image-preview",
            files={"file": ("photo.heic", payload, "image/heic")},
        )

        assert response.status_code == 422, response.text
        assert "HEIC/HEIF 文件解码失败" in response.json()["detail"]
        assert list(tmp_path.iterdir()) == []
        assert registry.get_session_entries("preview.png") == {}

    def test_bad_heic_preview_returns_sanitized_422_and_cleans_temp(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
        monkeypatch.setattr("api.file_bridge.HAS_HEIF", True)
        client, registry = _client_with_registry()
        app_logger = _capture_app_logger(caplog)
        try:
            response = client.post(
                "/api/system/image-preview",
                files={"file": ("bad.heic", b"not a heic image", "image/heic")},
            )
        finally:
            app_logger.removeHandler(caplog.handler)

        assert response.status_code == 422, response.text
        assert response.json()["detail"] == _HEIC_UNREADABLE_DETAIL
        assert str(tmp_path) not in response.text
        assert all(fragment not in response.text for fragment in _UNREADABLE_IMAGE_FORBIDDEN_FRAGMENTS)
        records = _records_for_event(caplog, "api_http_error")
        assert len(records) == 1
        assert records[0].error_message == _HEIC_UNREADABLE_DETAIL
        assert _records_for_event(caplog, "api_unhandled_exception") == []
        assert list(tmp_path.iterdir()) == []
        assert registry.get_session_entries("preview.png") == {}

    def test_bad_raw_preview_returns_sanitized_422_and_cleans_temp(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
        monkeypatch.setattr("api.file_bridge.HAS_RAW", True)
        client, registry = _client_with_registry()
        app_logger = _capture_app_logger(caplog)
        try:
            response = client.post(
                "/api/system/image-preview",
                files={"file": ("bad.dng", b"not a raw image", "application/octet-stream")},
            )
        finally:
            app_logger.removeHandler(caplog.handler)

        assert response.status_code == 422, response.text
        assert response.json()["detail"] == _RAW_UNREADABLE_DETAIL
        assert str(tmp_path) not in response.text
        assert all(fragment not in response.text for fragment in _UNREADABLE_IMAGE_FORBIDDEN_FRAGMENTS)
        records = _records_for_event(caplog, "api_http_error")
        assert len(records) == 1
        assert records[0].error_message == _RAW_UNREADABLE_DETAIL
        assert _records_for_event(caplog, "api_unhandled_exception") == []
        assert list(tmp_path.iterdir()) == []
        assert registry.get_session_entries("preview.png") == {}

    def test_heic_preview_missing_dependency_returns_safe_422(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
        monkeypatch.setattr("api.file_bridge.HAS_HEIF", False)
        client, registry = _client_with_registry()
        app_logger = _capture_app_logger(caplog)
        try:
            response = client.post(
                "/api/system/image-preview",
                files={"file": ("photo.heic", b"not a heic image", "image/heic")},
            )
        finally:
            app_logger.removeHandler(caplog.handler)

        assert response.status_code == 422, response.text
        assert response.json()["detail"] == _HEIC_UNSUPPORTED_DETAIL
        assert all(
            fragment not in response.text
            for fragment in _OPTIONAL_DEPENDENCY_FORBIDDEN_FRAGMENTS
        )
        records = _records_for_event(caplog, "api_http_error")
        assert len(records) == 1
        assert records[0].error_message == _HEIC_UNSUPPORTED_DETAIL
        assert all(
            fragment not in records[0].error_message
            for fragment in _OPTIONAL_DEPENDENCY_FORBIDDEN_FRAGMENTS
        )
        assert _records_for_event(caplog, "api_unhandled_exception") == []
        assert list(tmp_path.iterdir()) == []
        assert registry.get_session_entries("preview.png") == {}

    def test_raw_preview_missing_dependency_returns_safe_422(
        self,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr("config.TEMP_DIR", str(tmp_path))
        monkeypatch.setattr("api.file_bridge.HAS_RAW", False)
        client, registry = _client_with_registry()
        app_logger = _capture_app_logger(caplog)
        try:
            response = client.post(
                "/api/system/image-preview",
                files={
                    "file": (
                        "photo.dng",
                        b"not a raw image",
                        "application/octet-stream",
                    )
                },
            )
        finally:
            app_logger.removeHandler(caplog.handler)

        assert response.status_code == 422, response.text
        assert response.json()["detail"] == _RAW_UNSUPPORTED_DETAIL
        assert all(
            fragment not in response.text
            for fragment in _OPTIONAL_DEPENDENCY_FORBIDDEN_FRAGMENTS
        )
        records = _records_for_event(caplog, "api_http_error")
        assert len(records) == 1
        assert records[0].error_message == _RAW_UNSUPPORTED_DETAIL
        assert all(
            fragment not in records[0].error_message
            for fragment in _OPTIONAL_DEPENDENCY_FORBIDDEN_FRAGMENTS
        )
        assert _records_for_event(caplog, "api_unhandled_exception") == []
        assert list(tmp_path.iterdir()) == []
        assert registry.get_session_entries("preview.png") == {}


class TestSystemSaveSettingsCanary:
    """Settings persistence canary isolates the real user settings file."""

    def test_save_settings_emits_sessionless_contract_canary(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        settings_path = tmp_path / "settings.json"
        monkeypatch.setattr("api.routers.system.SETTINGS_FILE", settings_path)
        client, _registry = _client_with_registry()
        payload = UserSettings().model_dump()
        serialized = json.dumps(payload, indent=2, ensure_ascii=False)

        target_logger = _capture_system_logger(caplog)
        try:
            response = client.post("/api/system/settings", json=payload)
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "success"
        assert settings_path.read_text(encoding="utf-8") == serialized

        records = _records_for_event(caplog, "system_save_settings_done")
        assert len(records) == 1
        record = records[0]
        assert record.levelno == logging.INFO
        assert "session_id" not in record.__dict__
        assert record.settings_field_count == len(payload)
        assert record.bytes_written == len(serialized.encode("utf-8"))
        assert record.settings_path == str(settings_path)
