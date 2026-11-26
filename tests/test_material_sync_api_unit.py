"""Material sync API tests."""

from __future__ import annotations

import json
import hashlib
import logging
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import httpx
import pytest
from fastapi.testclient import TestClient

from api.app import create_app
from api.routers.material_sync import (
    MATERIAL_SYNC_CATALOG_UNAVAILABLE_DETAIL,
    MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
    MATERIAL_SYNC_REFRESH_UNAVAILABLE_DETAIL,
    MATERIAL_SYNC_ROLLBACK_UNAVAILABLE_DETAIL,
    MATERIAL_SYNC_STATUS_UNAVAILABLE_DETAIL,
)
from core.single_stage import (
    material_files,
    material_library,
    material_registry_client,
    install_material_registry_package,
    list_material_registry_catalog,
    refresh_material_sync_from_registry,
    rollback_material_sync_revision,
)

_OFFICIAL_PASSWORD = "approve-secret"
_AUTH_HEADERS = {
    "X-Lumina-Material-Registry-Official-Password": _OFFICIAL_PASSWORD,
}
_MATERIAL_SYNC_LOGGER_NAMES = (
    "lumina.api.routers.material_sync",
    "lumina.api.app",
)


def _client() -> TestClient:
    return TestClient(create_app(), base_url="http://localhost:8000")


def _enable_material_registry_password(monkeypatch) -> None:
    monkeypatch.setenv(
        "LUMINA_MATERIAL_REGISTRY_OFFICIAL_PASSWORD",
        _OFFICIAL_PASSWORD,
    )


def _capture_material_sync_logs(
    caplog: pytest.LogCaptureFixture,
) -> list[logging.Logger]:
    loggers: list[logging.Logger] = []
    for logger_name in _MATERIAL_SYNC_LOGGER_NAMES:
        logger = logging.getLogger(logger_name)
        logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=logger.name)
        loggers.append(logger)
    return loggers


def _release_caplog_handler(
    loggers: list[logging.Logger],
    caplog: pytest.LogCaptureFixture,
) -> None:
    for logger in loggers:
        logger.removeHandler(caplog.handler)


def _records_for_event(
    caplog: pytest.LogCaptureFixture,
    event: str,
) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == event
    ]


def _assert_http_error_log_safe(
    caplog: pytest.LogCaptureFixture,
    *,
    path: str,
    status_code: int,
    detail: str,
    forbidden_fragments: tuple[str, ...],
) -> None:
    records = [
        record
        for record in _records_for_event(caplog, "api_http_error")
        if getattr(record, "path", None) == path
        and getattr(record, "status_code", None) == status_code
    ]
    assert records
    error_message = str(getattr(records[-1], "error_message", ""))
    assert error_message == detail
    for fragment in forbidden_fragments:
        assert fragment not in error_message


def _assert_route_failure_log_preserves_diagnostics(
    caplog: pytest.LogCaptureFixture,
    *,
    event: str,
    error_type: str,
    raw_fragment: str,
    status_code: int,
) -> None:
    records = _records_for_event(caplog, event)
    assert records
    record = records[-1]
    assert getattr(record, "error_type", None) == error_type
    assert getattr(record, "status_code", None) == status_code
    assert raw_fragment in str(getattr(record, "error_message", ""))


def _registry_install_catalog() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "channels": ["official"],
        "count": 1,
        "materials": [
            {
                "material_id": "mat_cloud_test",
                "revision_id": "rev_cloud_test",
                "content_hash": "sha256:cloud",
                "channel": "official",
                "visibility": "official",
                "local_directory": "BrandA/pla-basic",
                "display": {"brand": "BrandA", "material_name": "PLA Basic"},
                "compatibility": {},
                "package_url": "/v1/packages/material_package.zip",
                "package_sha256": "a" * 64,
                "package_bytes": 1234,
            }
        ],
    }


@pytest.mark.parametrize(
    ("operation", "method", "path"),
    [
        ("list_material_registry_catalog", "GET", "/api/material-sync/catalog"),
        ("refresh_material_sync_from_registry", "POST", "/api/material-sync/refresh"),
        ("list_material_registry_catalog", "POST", "/api/material-sync/install-from-registry"),
        ("install_material_registry_package", "POST", "/api/material-sync/install-from-registry"),
    ],
)
def test_local_api_responds_while_registry_request_is_waiting(
    monkeypatch: pytest.MonkeyPatch, operation: str, method: str, path: str
) -> None:
    """A stalled cloud request must not prevent local API responses."""
    entered = Event()
    release = Event()

    def unavailable_registry(*args: object, **kwargs: object) -> None:
        entered.set()
        if not release.wait(timeout=10):
            raise RuntimeError("Test registry wait expired")
        raise RuntimeError("Material registry catalog request failed")

    monkeypatch.setenv("LUMINA_MATERIAL_SYNC_STARTUP_REFRESH", "false")
    monkeypatch.setenv("LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S", "0")
    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        lambda **kwargs: _registry_install_catalog(),
    )
    monkeypatch.setattr(f"api.routers.material_sync.{operation}", unavailable_registry)
    with _client() as client, ThreadPoolExecutor(max_workers=2) as executor:
        payload = {
            "material_id": "mat_cloud_test",
            "revision_id": "rev_cloud_test",
            "package_url": "/v1/packages/material_package.zip",
            "package_sha256": "a" * 64,
        }
        cloud = executor.submit(
            client.request, method, path,
            **({"json": payload} if path.endswith("install-from-registry") else {}),
        )
        try:
            assert entered.wait(timeout=5), "Cloud request did not reach the registry"
            local = executor.submit(client.get, "/api/health")
            assert local.result(timeout=2).status_code == 200
            assert not cloud.done(), "Cloud request should still be waiting"
        finally:
            release.set()
        assert cloud.result(timeout=5).status_code == 502


def _write_v2_material_package(
    zip_path: Path,
    *,
    material_id: str = "mat_sync_test",
    revision_id: str = "rev_sync_test",
    local_directory: str = "BrandA/pla-basic",
) -> str:
    material_payload = json.dumps(
        {
            "brand": "BrandA",
            "material_name": "PLA Basic Imported",
            "stage_a_params_file": "stage_A_parameters.json",
        },
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    stage_a_payload = json.dumps(
        {
            "meta": {},
            "parameters": {
                "channels": [
                    {"color_name": "PLA Basic Imported", "E": [0.1, 0.2, 0.3], "k": [1.0, 1.1, 1.2]}
                ],
                "substrates": [
                    {
                        "substrate_id": "white",
                        "C0": [1.0, 1.0, 1.0],
                    }
                ],
            },
        },
        ensure_ascii=False,
        indent=2,
    ).encode("utf-8")
    material_hash = hashlib.sha256(material_payload).hexdigest()
    stage_a_hash = hashlib.sha256(stage_a_payload).hexdigest()
    content_hash = hashlib.sha256(
        f"material.json:{material_hash}\nstage_A_parameters.json:{stage_a_hash}".encode(
            "utf-8"
        )
    ).hexdigest()
    material_path = f"materials/{local_directory}/material.json"
    stage_a_path = f"materials/{local_directory}/stage_A_parameters.json"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(material_path, material_payload)
        archive.writestr(stage_a_path, stage_a_payload)
        archive.writestr(
            "lumina_material_bundle.json",
            json.dumps(
                {
                    "kind": "lumina_material_bundle",
                    "schema_version": "2.0",
                    "exported_at": "2026-06-08T00:00:00+00:00",
                    "material_count": 1,
                    "packages": [
                        {
                            "material_id": material_id,
                            "revision_id": revision_id,
                            "content_hash": f"sha256:{content_hash}",
                            "channel": "team",
                            "visibility": "team",
                            "local_directory": local_directory,
                            "display": {
                                "brand": "BrandA",
                                "material_name": "PLA Basic Imported",
                            },
                            "files": [
                                {
                                    "path": material_path,
                                    "role": "material_archive",
                                    "sha256": material_hash,
                                    "bytes": len(material_payload),
                                    "required": True,
                                },
                                {
                                    "path": stage_a_path,
                                    "role": "stage_a_parameters",
                                    "sha256": stage_a_hash,
                                    "bytes": len(stage_a_payload),
                                    "required": True,
                                },
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return f"sha256:{content_hash}"


def _extract_v2_material_files(
    package_path: Path,
    material_dir: Path,
    *,
    local_directory: str = "BrandA/pla-basic",
) -> None:
    material_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package_path, "r") as archive:
        package_root = f"materials/{local_directory}"
        material_dir.joinpath("material.json").write_bytes(
            archive.read(f"{package_root}/material.json")
        )
        material_dir.joinpath("stage_A_parameters.json").write_bytes(
            archive.read(f"{package_root}/stage_A_parameters.json")
        )


def _registry_catalog_entry(
    *,
    content_hash: str,
    package_sha256: str,
    material_id: str = "mat_registry_test",
    revision_id: str = "rev_registry_test",
    channel: str = "official",
    local_directory: str = "BrandA/pla-basic",
    package_url: str = "/v1/packages/material_package.zip",
) -> dict[str, object]:
    return {
        "material_id": material_id,
        "revision_id": revision_id,
        "content_hash": content_hash,
        "channel": channel,
        "local_directory": local_directory,
        "package_url": package_url,
        "package_sha256": package_sha256,
    }


def _write_v2_multi_material_package(zip_path: Path) -> dict[str, str]:
    package_records: list[dict[str, object]] = []
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for suffix in ("selected", "other"):
            local_directory = f"BrandA/pla-{suffix}"
            material_payload = json.dumps(
                {
                    "brand": "BrandA",
                    "material_name": f"PLA {suffix.title()}",
                    "stage_a_params_file": "stage_A_parameters.json",
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            stage_a_payload = json.dumps(
                {
                    "meta": {},
                    "parameters": {
                        "channels": [
                            {
                                "color_name": f"PLA {suffix.title()}",
                                "E": [0.1, 0.2, 0.3],
                                "k": [1.0, 1.1, 1.2],
                            }
                        ],
                        "substrates": [
                            {
                                "substrate_id": "white",
                                "C0": [1.0, 1.0, 1.0],
                            }
                        ],
                    },
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8")
            material_hash = hashlib.sha256(material_payload).hexdigest()
            stage_a_hash = hashlib.sha256(stage_a_payload).hexdigest()
            content_hash = hashlib.sha256(
                (
                    f"material.json:{material_hash}\n"
                    f"stage_A_parameters.json:{stage_a_hash}"
                ).encode("utf-8")
            ).hexdigest()
            material_path = f"materials/{local_directory}/material.json"
            stage_a_path = f"materials/{local_directory}/stage_A_parameters.json"
            archive.writestr(material_path, material_payload)
            archive.writestr(stage_a_path, stage_a_payload)
            package_records.append(
                {
                    "material_id": f"mat_{suffix}",
                    "revision_id": f"rev_{suffix}",
                    "content_hash": f"sha256:{content_hash}",
                    "channel": "team",
                    "visibility": "team",
                    "local_directory": local_directory,
                    "display": {
                        "brand": "BrandA",
                        "material_name": f"PLA {suffix.title()}",
                    },
                    "files": [
                        {
                            "path": material_path,
                            "role": "material_archive",
                            "sha256": material_hash,
                            "bytes": len(material_payload),
                            "required": True,
                        },
                        {
                            "path": stage_a_path,
                            "role": "stage_a_parameters",
                            "sha256": stage_a_hash,
                            "bytes": len(stage_a_payload),
                            "required": True,
                        },
                    ],
                }
            )
        archive.writestr(
            "lumina_material_bundle.json",
            json.dumps(
                {
                    "kind": "lumina_material_bundle",
                    "schema_version": "2.0",
                    "exported_at": "2026-06-08T00:00:00+00:00",
                    "material_count": len(package_records),
                    "packages": package_records,
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
    return {
        "selected_material_id": "mat_selected",
        "selected_revision_id": "rev_selected",
        "selected_content_hash": str(package_records[0]["content_hash"]),
        "package_sha256": hashlib.sha256(zip_path.read_bytes()).hexdigest(),
    }


def test_material_sync_status_returns_empty_state_when_index_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    monkeypatch.setattr("core.single_stage.material_files.MATERIALS_DIR", str(materials_root))

    response = _client().get("/api/material-sync/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["index_state"] == "missing"
    assert body["installed_count"] == 0
    assert body["installed"] == []


def test_material_sync_status_unavailable_returns_safe_detail(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_path = "/Users/min/private/materials/_sync/index.json"

    def _fake_get_material_sync_status() -> dict[str, object]:
        raise OSError(f"[Errno 13] Permission denied: '{private_path}'")

    monkeypatch.setattr(
        "api.routers.material_sync.get_material_sync_status",
        _fake_get_material_sync_status,
    )

    loggers = _capture_material_sync_logs(caplog)
    try:
        response = _client().get("/api/material-sync/status")
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == 500
    assert response.json()["detail"] == MATERIAL_SYNC_STATUS_UNAVAILABLE_DETAIL
    assert private_path not in response.text
    assert "Permission denied" not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/status",
        status_code=500,
        detail=MATERIAL_SYNC_STATUS_UNAVAILABLE_DETAIL,
        forbidden_fragments=(private_path, "Permission denied"),
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_status_failed",
        error_type="OSError",
        raw_fragment=private_path,
        status_code=500,
    )


def test_material_sync_install_imports_v2_package_and_updates_status(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    monkeypatch.setattr("core.single_stage.material_files.MATERIALS_DIR", str(materials_root))
    package_path = tmp_path / "material_package.zip"
    content_hash = _write_v2_material_package(package_path)

    install_response = _client().post(
        "/api/material-sync/install",
        files={
            "archive": (
                "material_package.zip",
                package_path.read_bytes(),
                "application/zip",
            )
        },
    )

    assert install_response.status_code == 200
    install_body = install_response.json()
    assert install_body["status"] == "ok"
    assert install_body["installed_count"] == 1
    assert install_body["installed_materials"][0]["directory_name"] == "BrandA/pla-basic"
    assert "archive_path" not in install_body["installed_materials"][0]
    assert "stage_a_params_path" not in install_body["installed_materials"][0]
    assert "materials/BrandA/pla-basic/material.json" not in install_response.text
    assert (
        "materials/BrandA/pla-basic/stage_A_parameters.json"
        not in install_response.text
    )

    status_response = _client().get("/api/material-sync/status")
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["index_state"] == "ready"
    assert status_body["installed_count"] == 1
    assert status_body["installed"][0]["material_id"] == "mat_sync_test"
    assert status_body["installed"][0]["revision_id"] == "rev_sync_test"
    assert status_body["installed"][0]["content_hash"] == content_hash
    assert status_body["installed"][0]["local_exists"] is True
    assert status_body["installed"][0]["material_file_exists"] is True


def test_material_sync_install_rejects_non_zip_upload(tmp_path: Path) -> None:
    response = _client().post(
        "/api/material-sync/install",
        files={"archive": ("not-a-package.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 422


def test_material_sync_install_rejects_oversized_upload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    package_path = tmp_path / "material_package.zip"
    _write_v2_material_package(package_path)
    monkeypatch.setenv("LUMINA_MATERIAL_PACKAGE_MAX_ARCHIVE_BYTES", "32")

    response = _client().post(
        "/api/material-sync/install",
        files={
            "archive": (
                "material_package.zip",
                package_path.read_bytes(),
                "application/zip",
            )
        },
    )

    assert response.status_code == 413
    assert "exceeds maximum size" in response.json()["detail"]


def test_material_sync_install_import_os_error_returns_safe_detail(
    monkeypatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    package_path = tmp_path / "material_package.zip"
    _write_v2_material_package(package_path)
    private_path = "/Users/min/private/materials/BrandA/pla-basic/material.json"

    def _fake_import_saved_stage_a_material_archives(
        *,
        archive_path: str,
    ) -> object:
        raise OSError(f"[Errno 13] Permission denied: '{private_path}'")

    monkeypatch.setattr(
        "api.routers.material_sync.import_saved_stage_a_material_archives",
        _fake_import_saved_stage_a_material_archives,
    )

    loggers = _capture_material_sync_logs(caplog)
    try:
        response = _client().post(
            "/api/material-sync/install",
            files={
                "archive": (
                    "material_package.zip",
                    package_path.read_bytes(),
                    "application/zip",
                )
            },
        )
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == 422
    assert response.json()["detail"] == MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL
    assert private_path not in response.text
    assert "Permission denied" not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/install",
        status_code=422,
        detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
        forbidden_fragments=(private_path, "Permission denied"),
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_install_failed",
        error_type="OSError",
        raw_fragment=private_path,
        status_code=422,
    )


def test_material_sync_install_import_missing_file_returns_safe_404(
    monkeypatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    package_path = tmp_path / "material_package.zip"
    _write_v2_material_package(package_path)
    private_path = "/Users/min/private/materials/BrandA/pla-basic/material.json"

    def _fake_import_saved_stage_a_material_archives(
        *,
        archive_path: str,
    ) -> object:
        raise FileNotFoundError(f"Saved material archive not found: {private_path}")

    monkeypatch.setattr(
        "api.routers.material_sync.import_saved_stage_a_material_archives",
        _fake_import_saved_stage_a_material_archives,
    )

    loggers = _capture_material_sync_logs(caplog)
    try:
        response = _client().post(
            "/api/material-sync/install",
            files={
                "archive": (
                    "material_package.zip",
                    package_path.read_bytes(),
                    "application/zip",
                )
            },
        )
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == 404
    assert response.json()["detail"] == MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL
    assert private_path not in response.text
    assert "Saved material archive" not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/install",
        status_code=404,
        detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
        forbidden_fragments=(private_path, "Saved material archive"),
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_install_failed",
        error_type="FileNotFoundError",
        raw_fragment=private_path,
        status_code=404,
    )


@pytest.mark.parametrize(
    ("exc", "error_type", "forbidden_fragments"),
    [
        (
            ValueError(
                "Material bundle file hash mismatch: "
                "/Users/min/private/materials/BrandA/pla-basic/material.json"
            ),
            "ValueError",
            (
                "/Users/min/private/materials/BrandA/pla-basic/material.json",
                "hash mismatch",
            ),
        ),
        (
            TypeError(
                "Material bundle manifest parser failed for "
                "/Users/min/private/materials/BrandA/pla-basic/material.json"
            ),
            "TypeError",
            (
                "/Users/min/private/materials/BrandA/pla-basic/material.json",
                "parser failed",
            ),
        ),
    ],
)
def test_material_sync_install_import_validation_errors_return_safe_detail(
    monkeypatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    exc: Exception,
    error_type: str,
    forbidden_fragments: tuple[str, ...],
) -> None:
    package_path = tmp_path / "material_package.zip"
    _write_v2_material_package(package_path)

    def _fake_import_saved_stage_a_material_archives(
        *,
        archive_path: str,
    ) -> object:
        raise exc

    monkeypatch.setattr(
        "api.routers.material_sync.import_saved_stage_a_material_archives",
        _fake_import_saved_stage_a_material_archives,
    )

    loggers = _capture_material_sync_logs(caplog)
    try:
        response = _client().post(
            "/api/material-sync/install",
            files={
                "archive": (
                    "material_package.zip",
                    package_path.read_bytes(),
                    "application/zip",
                )
            },
        )
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == 422
    assert response.json()["detail"] == MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL
    for fragment in forbidden_fragments:
        assert fragment not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/install",
        status_code=422,
        detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
        forbidden_fragments=forbidden_fragments,
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_install_failed",
        error_type=error_type,
        raw_fragment=forbidden_fragments[0],
        status_code=422,
    )


def test_material_sync_install_is_local_import_without_official_password(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    monkeypatch.setattr("core.single_stage.material_files.MATERIALS_DIR", str(materials_root))
    package_path = tmp_path / "material_package.zip"
    _write_v2_material_package(package_path)

    response = _client().post(
        "/api/material-sync/install",
        files={
            "archive": (
                "material_package.zip",
                package_path.read_bytes(),
                "application/zip",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["installed_count"] == 1


def test_material_sync_refresh_requires_registry_url(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    monkeypatch.setattr("core.single_stage.material_files.MATERIALS_DIR", str(materials_root))
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "")

    response = _client().post("/api/material-sync/refresh")

    assert response.status_code == 422
    assert "Material registry URL is not configured" in response.json()["detail"]


def test_material_sync_catalog_requires_registry_url_keeps_offline_detail(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "")

    response = _client().get("/api/material-sync/catalog")

    assert response.status_code == 422
    assert response.json()["detail"] == "Material registry URL is not configured"


def test_material_sync_refresh_registry_unavailable_returns_502(monkeypatch) -> None:
    private_url = "https://registry.internal/private/catalog.json"

    def _fake_refresh_material_sync_from_registry() -> dict[str, object]:
        raise RuntimeError(
            f"Material registry catalog request failed for {private_url}: status 500"
        )

    monkeypatch.setattr(
        "api.routers.material_sync.refresh_material_sync_from_registry",
        _fake_refresh_material_sync_from_registry,
    )

    response = _client().post("/api/material-sync/refresh")

    assert response.status_code == 502
    assert response.json()["detail"] == MATERIAL_SYNC_REFRESH_UNAVAILABLE_DETAIL
    assert private_url not in response.text
    assert "status 500" not in response.text


def test_material_sync_catalog_registry_unavailable_returns_safe_detail(
    monkeypatch,
) -> None:
    private_url = "https://registry.internal/private/catalog.json"

    def _fake_list_material_registry_catalog(**_: object) -> dict[str, object]:
        raise RuntimeError(
            f"Material registry catalog request failed for {private_url}: status 502"
        )

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )

    response = _client().get("/api/material-sync/catalog")

    assert response.status_code == 502
    assert response.json()["detail"] == MATERIAL_SYNC_CATALOG_UNAVAILABLE_DETAIL
    assert private_url not in response.text
    assert "status 502" not in response.text


def test_material_sync_catalog_invalid_channel_returns_safe_detail(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_channel = "/Users/min/private/team"
    loggers = _capture_material_sync_logs(caplog)
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "https://registry.test/v1")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_CHANNELS", private_channel)

    try:
        response = _client().get("/api/material-sync/catalog")
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == 422
    assert response.json()["detail"] == MATERIAL_SYNC_CATALOG_UNAVAILABLE_DETAIL
    assert private_channel not in response.text
    assert "Material registry channel is invalid" not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/catalog",
        status_code=422,
        detail=MATERIAL_SYNC_CATALOG_UNAVAILABLE_DETAIL,
        forbidden_fragments=(private_channel, "Material registry channel is invalid"),
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_catalog_failed",
        error_type="ValueError",
        raw_fragment=private_channel,
        status_code=422,
    )


def test_material_sync_install_from_registry_invalid_channel_returns_safe_detail(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_channel = "/Users/min/private/team"
    loggers = _capture_material_sync_logs(caplog)
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "https://registry.test/v1")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_CHANNELS", private_channel)

    try:
        response = _client().post(
            "/api/material-sync/install-from-registry",
            json={
                "package_url": "/v1/packages/material_package.zip",
                "package_sha256": "a" * 64,
                "material_id": "mat_cloud_test",
                "revision_id": "rev_cloud_test",
            },
        )
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == 422
    assert response.json()["detail"] == MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL
    assert private_channel not in response.text
    assert "Material registry channel is invalid" not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/install-from-registry",
        status_code=422,
        detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
        forbidden_fragments=(private_channel, "Material registry channel is invalid"),
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_install_from_registry_failed",
        error_type="ValueError",
        raw_fragment=private_channel,
        status_code=422,
    )


def test_material_sync_install_from_registry_requires_registry_url_keeps_offline_detail(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "")

    response = _client().post(
        "/api/material-sync/install-from-registry",
        json={
            "package_url": "/v1/packages/material_package.zip",
            "package_sha256": "a" * 64,
            "material_id": "mat_cloud_test",
            "revision_id": "rev_cloud_test",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Material registry URL is not configured"


def test_material_sync_refresh_invalid_channel_returns_safe_detail(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_channel = "/Users/min/private/team"
    loggers = _capture_material_sync_logs(caplog)
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "https://registry.test/v1")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_CHANNELS", private_channel)

    try:
        response = _client().post("/api/material-sync/refresh")
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == 422
    assert response.json()["detail"] == MATERIAL_SYNC_REFRESH_UNAVAILABLE_DETAIL
    assert private_channel not in response.text
    assert "Material registry channel is invalid" not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/refresh",
        status_code=422,
        detail=MATERIAL_SYNC_REFRESH_UNAVAILABLE_DETAIL,
        forbidden_fragments=(private_channel, "Material registry channel is invalid"),
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_refresh_failed",
        error_type="ValueError",
        raw_fragment=private_channel,
        status_code=422,
    )


def test_material_sync_refresh_endpoint_returns_core_summary(monkeypatch) -> None:
    def _fake_refresh_material_sync_from_registry() -> dict[str, object]:
        return {
            "registry_url": "https://registry.test/v1",
            "channels": ["official"],
            "checked_count": 1,
            "installed_count": 1,
            "skipped_count": 0,
            "failed_count": 0,
            "installed_materials": [
                {
                    "material_name": "PLA Basic Imported",
                    "directory_name": "BrandA/pla-basic",
                    "brand": "BrandA",
                    "archive_path": "materials/BrandA/pla-basic/material.json",
                    "stage_a_params_path": (
                        "materials/BrandA/pla-basic/stage_A_parameters.json"
                    ),
                }
            ],
            "failures": [],
            "catalog_not_modified": True,
        }

    monkeypatch.setattr(
        "api.routers.material_sync.refresh_material_sync_from_registry",
        _fake_refresh_material_sync_from_registry,
    )

    response = _client().post("/api/material-sync/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["registry_url"] == "https://registry.test/v1"
    assert body["channels"] == ["official"]
    assert body["installed_count"] == 1
    assert "catalog_not_modified" not in body
    assert body["installed_materials"][0]["directory_name"] == "BrandA/pla-basic"
    assert "archive_path" not in body["installed_materials"][0]
    assert "stage_a_params_path" not in body["installed_materials"][0]
    assert "materials/BrandA/pla-basic/material.json" not in response.text
    assert "materials/BrandA/pla-basic/stage_A_parameters.json" not in response.text


def test_material_sync_refresh_endpoint_hides_package_failure_paths(
    caplog: pytest.LogCaptureFixture,
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    temp_root = tmp_path / "temp"
    package_path = tmp_path / "material_package.zip"
    content_hash = _write_v2_material_package(package_path)
    package_bytes = package_path.read_bytes()
    package_sha256 = hashlib.sha256(package_bytes).hexdigest()
    monkeypatch.setattr(material_files, "TEMP_DIR", str(temp_root))
    monkeypatch.setenv("LUMINA_MATERIAL_PACKAGE_MAX_UNCOMPRESSED_BYTES", "1")

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                200,
                headers={"ETag": 'W/"catalog-with-broken-package"'},
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": "mat_sync_test",
                            "revision_id": "rev_sync_test",
                            "content_hash": content_hash,
                            "channel": "official",
                            "visibility": "official",
                            "package_url": "/v1/packages/material_package.zip",
                            "package_sha256": package_sha256,
                        }
                    ],
                },
            )
        if request.url.path == "/v1/packages/material_package.zip":
            return httpx.Response(200, content=package_bytes)
        return httpx.Response(404)

    def _real_refresh_with_mock_transport() -> dict[str, object]:
        return refresh_material_sync_from_registry(
            registry_url="https://registry.test/v1",
            materials_dir=str(materials_root),
            transport=httpx.MockTransport(_handler),
        )

    monkeypatch.setattr(
        "api.routers.material_sync.refresh_material_sync_from_registry",
        _real_refresh_with_mock_transport,
    )

    logger = logging.getLogger("lumina.core.single_stage.materials")
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=logger.name)
    try:
        response = _client().post("/api/material-sync/refresh")
    finally:
        logger.removeHandler(caplog.handler)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["failed_count"] == 1
    sync_index = json.loads(
        (materials_root / "_sync" / "index.json").read_text("utf-8")
    )
    assert sync_index["catalog_validators"] == {}
    assert str(temp_root) not in response.text
    assert "material_registry_package_" not in response.text
    failure_logs = _records_for_event(
        caplog,
        "material_sync_package_refresh_failed",
    )
    assert failure_logs
    assert failure_logs[0].error_type == "ValueError"
    assert str(temp_root) in failure_logs[0].error_message


def test_material_catalog_explicit_refresh_invalidates_cached_directory(monkeypatch) -> None:
    from api.routers import material_sync
    from unittest.mock import Mock

    invalidate = Mock()
    monkeypatch.setattr(material_sync, "invalidate_material_registry_remote_catalog_cache", invalidate)
    fetch = Mock(return_value={"schema_version": "1.0", "channels": ["official"],
                              "count": 0, "total_count": 0, "offset": 0, "limit": 24, "materials": []})
    monkeypatch.setattr(material_sync, "list_material_registry_catalog", fetch)
    response = _client().get("/api/material-sync/catalog", params={"refresh": "true", "limit": 24})
    assert response.status_code == 200
    invalidate.assert_called_once()
    assert fetch.call_args.kwargs["use_cache"] is False


def test_material_sync_catalog_endpoint_returns_remote_catalog_without_installing(
    monkeypatch,
) -> None:
    def _fake_list_material_registry_catalog(**_: object) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "channels": ["official"],
            "count": 1,
            "materials": [
                {
                    "material_id": "mat_cloud_test",
                    "revision_id": "rev_cloud_test",
                    "content_hash": "sha256:cloud",
                    "channel": "official",
                    "visibility": "official",
                    "local_directory": "BrandA/pla-basic",
                    "display": {"brand": "BrandA", "material_name": "PLA Basic"},
                    "compatibility": {},
                    "package_url": "/v1/packages/material_package.zip",
                    "package_sha256": "a" * 64,
                    "package_bytes": 1234,
                }
            ],
        }

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )

    response = _client().get("/api/material-sync/catalog")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["materials"][0]["material_id"] == "mat_cloud_test"
    assert body["materials"][0]["card_metadata"] is None


def test_material_sync_catalog_endpoint_preserves_registry_card_metadata(
    monkeypatch,
) -> None:
    card_metadata = {
        "created_at": "2026-07-15T16:55:22+00:00",
        "updated_at": "2026-07-15T16:55:23+00:00",
        "estimated_rgb": [255, 255, 61],
        "layer_height_mm": 0.08,
        "mean_delta_e": 4.87,
        "verification_count": 1,
        "usage_stats": None,
    }

    def _fake_list_material_registry_catalog(**_: object) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "channels": ["community"],
            "count": 1,
            "total_count": 1,
            "materials": [
                {
                    "material_id": "mat_fit",
                    "revision_id": "rev_fit",
                    "content_hash": "sha256:fit",
                    "channel": "community",
                    "visibility": "community",
                    "local_directory": "BrandA/petg-hf",
                    "display": {"brand": "BrandA", "material_name": "PETG HF"},
                    "compatibility": {},
                    "package_url": "/v1/packages/mat_fit.zip",
                    "package_sha256": "f" * 64,
                    "package_bytes": 7418,
                    "card_metadata": card_metadata,
                }
            ],
        }

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )

    response = _client().get("/api/material-sync/catalog", params={"limit": 24})

    assert response.status_code == 200
    entry = response.json()["materials"][0]
    assert entry["channel"] == "community"
    assert entry["card_metadata"] == card_metadata


def test_material_sync_catalog_allows_public_channels_without_password(
    monkeypatch,
) -> None:
    called = False
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_CHANNELS", "official,community")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_TOKEN", "team-token")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_OFFICIAL_PASSWORD", _OFFICIAL_PASSWORD)

    def _fake_list_material_registry_catalog(**_: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {
            "schema_version": "1.0",
            "channels": ["official", "community"],
            "count": 0,
            "materials": [],
        }

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )

    response = _client().get("/api/material-sync/catalog")

    assert response.status_code == 200
    assert called is True
    assert response.json()["channels"] == ["official", "community"]


def test_material_sync_catalog_allows_private_proxy_without_official_password(
    monkeypatch,
) -> None:
    called = False
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_CHANNELS", "official,team")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_TOKEN", "team-token")

    def _fake_list_material_registry_catalog(**_: object) -> dict[str, object]:
        nonlocal called
        called = True
        return {
            "schema_version": "1.0",
            "channels": ["official", "team"],
            "count": 0,
            "materials": [],
        }

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )

    response = _client().get("/api/material-sync/catalog")

    assert response.status_code == 200
    assert called is True
    assert response.json()["channels"] == ["official", "team"]


def test_material_sync_catalog_ignores_legacy_official_password_header(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_CHANNELS", "official,team")
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_OFFICIAL_PASSWORD", _OFFICIAL_PASSWORD)

    def _fake_list_material_registry_catalog(**_: object) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "channels": ["official", "team"],
            "count": 0,
            "materials": [],
        }

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )

    response = _client().get("/api/material-sync/catalog", headers=_AUTH_HEADERS)

    assert response.status_code == 200
    assert response.json()["channels"] == ["official", "team"]


def test_list_material_registry_catalog_reuses_remote_catalog_cache() -> None:
    request_counts = {"catalog": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            request_counts["catalog"] += 1
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": "mat_cloud",
                            "revision_id": "rev_cloud",
                            "content_hash": "sha256:cloud",
                            "channel": "official",
                            "visibility": "official",
                            "local_directory": "BrandA/pla-basic",
                            "package_url": "/v1/packages/material_package.zip",
                            "package_sha256": "a" * 64,
                            "package_bytes": 10,
                        }
                    ],
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)

    first = list_material_registry_catalog(
        registry_url="https://registry.test/v1",
        channels=["official"],
        transport=transport,
    )
    second = list_material_registry_catalog(
        registry_url="https://registry.test/v1",
        channels=["official"],
        transport=transport,
    )

    assert request_counts == {"catalog": 1}
    assert first == second
    assert second["count"] == 1


def test_list_material_registry_catalog_requests_remote_page() -> None:
    observed_queries: list[dict[str, str]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            observed_queries.append(dict(request.url.params.multi_items()))
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "count": 1,
                    "total_count": 3,
                    "offset": 1,
                    "limit": 1,
                    "materials": [
                        {
                            "material_id": "mat_cloud_1",
                            "revision_id": "rev_cloud_1",
                            "content_hash": "sha256:cloud1",
                            "channel": "official",
                            "visibility": "official",
                            "local_directory": "BrandA/pla-basic-1",
                            "package_url": "/v1/packages/material_package_1.zip",
                            "package_sha256": "b" * 64,
                            "package_bytes": 10,
                        }
                    ],
                },
            )
        return httpx.Response(404)

    catalog = list_material_registry_catalog(
        registry_url="https://registry.test/v1",
        channels=["official"],
        limit=1,
        offset=1,
        transport=httpx.MockTransport(_handler),
    )

    assert observed_queries == [
        {"channel": "official", "offset": "1", "limit": "1"}
    ]
    assert catalog["count"] == 1
    assert catalog["total_count"] == 3
    assert catalog["offset"] == 1
    assert catalog["limit"] == 1
    assert catalog["materials"][0]["material_id"] == "mat_cloud_1"


def test_list_material_registry_catalog_requests_remote_search() -> None:
    observed_queries: list[dict[str, str]] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            observed_queries.append(dict(request.url.params.multi_items()))
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "count": 1,
                    "total_count": 1,
                    "offset": 0,
                    "limit": 50,
                    "materials": [
                        {
                            "material_id": "mat_petg",
                            "revision_id": "rev_petg",
                            "content_hash": "sha256:petg",
                            "channel": "official",
                            "visibility": "official",
                            "local_directory": "BrandB/petg-silk",
                            "display": {"brand": "BrandB", "material_name": "Silk PETG"},
                            "package_url": "/v1/packages/petg.zip",
                            "package_sha256": "c" * 64,
                            "package_bytes": 10,
                        }
                    ],
                },
            )
        return httpx.Response(404)

    catalog = list_material_registry_catalog(
        registry_url="https://registry.test/v1",
        channels=["official"],
        query="petg",
        limit=50,
        offset=0,
        transport=httpx.MockTransport(_handler),
    )

    assert observed_queries == [
        {"channel": "official", "q": "petg", "offset": "0", "limit": "50"}
    ]
    assert catalog["count"] == 1
    assert catalog["total_count"] == 1
    assert catalog["materials"][0]["material_id"] == "mat_petg"


def test_catalog_preserves_registry_only_keyword_after_a_full_metadata_read() -> None:
    calls: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        query = request.url.params.get("q")
        calls.append(query)
        items = [{"material_id": "mat_1", "revision_id": "rev_1", "display": {"name": "Opaque title"}}]
        return httpx.Response(200, json={"materials": items, "offset": 0, "total_count": 1})

    transport = httpx.MockTransport(handler)
    source = "https://search-index.test/v1"
    list_material_registry_catalog(registry_url=source, transport=transport)
    result = list_material_registry_catalog(registry_url=source, transport=transport, query="translated keyword", limit=24)
    assert calls == [None, "translated keyword"]
    assert [item["material_id"] for item in result["materials"]] == ["mat_1"]


@pytest.mark.parametrize("denied", [401, 403])
def test_material_catalog_route_forwards_denied_access(monkeypatch, denied: int) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(denied))
    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        lambda **kwargs: list_material_registry_catalog(registry_url="https://private.test/v1", transport=transport, **kwargs),
    )
    assert _client().get("/api/material-sync/catalog").status_code == denied


def test_list_material_registry_catalog_rejects_cross_origin_redirect() -> None:
    requested_urls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            )
        return httpx.Response(200, json={"schema_version": "1.0", "materials": []})

    with pytest.raises(RuntimeError, match="catalog redirects are not allowed"):
        list_material_registry_catalog(
            registry_url="https://registry.test/v1",
            channels=["official"],
            transport=httpx.MockTransport(_handler),
            use_cache=False,
        )

    assert requested_urls == [
        "https://registry.test/v1/materials/catalog?channel=official"
    ]


def test_list_material_registry_catalog_reuses_full_cache_for_legacy_paging() -> None:
    request_counts = {"catalog": 0}

    def _catalog_entry(index: int) -> dict[str, object]:
        return {
            "material_id": f"mat_cloud_{index}",
            "revision_id": f"rev_cloud_{index}",
            "content_hash": f"sha256:cloud{index}",
            "channel": "official",
            "visibility": "official",
            "local_directory": f"BrandA/pla-basic-{index}",
            "package_url": f"/v1/packages/material_package_{index}.zip",
            "package_sha256": str(index) * 64,
            "package_bytes": 10,
        }

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            request_counts["catalog"] += 1
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [_catalog_entry(0), _catalog_entry(1)],
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)

    first_page = list_material_registry_catalog(
        registry_url="https://registry.test/v1",
        channels=["official"],
        limit=1,
        offset=0,
        transport=transport,
    )
    second_page = list_material_registry_catalog(
        registry_url="https://registry.test/v1",
        channels=["official"],
        limit=1,
        offset=1,
        transport=transport,
    )

    assert request_counts == {"catalog": 1}
    assert first_page["count"] == 1
    assert first_page["total_count"] == 2
    assert first_page["materials"][0]["material_id"] == "mat_cloud_0"
    assert second_page["count"] == 1
    assert second_page["total_count"] == 2
    assert second_page["materials"][0]["material_id"] == "mat_cloud_1"


def test_list_material_registry_catalog_filters_legacy_remote_search_locally() -> None:
    request_counts = {"catalog": 0}

    def _catalog_entry(index: int, name: str) -> dict[str, object]:
        return {
            "material_id": f"mat_cloud_{index}",
            "revision_id": f"rev_cloud_{index}",
            "content_hash": f"sha256:cloud{index}",
            "channel": "official",
            "visibility": "official",
            "local_directory": f"BrandA/{name.lower().replace(' ', '-')}",
            "display": {"brand": "BrandA", "material_name": name},
            "package_url": f"/v1/packages/material_package_{index}.zip",
            "package_sha256": str(index) * 64,
            "package_bytes": 10,
        }

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            request_counts["catalog"] += 1
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        _catalog_entry(0, "PLA Basic"),
                        _catalog_entry(1, "Silk PETG"),
                    ],
                },
            )
        return httpx.Response(404)

    catalog = list_material_registry_catalog(
        registry_url="https://registry.test/v1",
        channels=["official"],
        query="petg",
        limit=50,
        offset=0,
        transport=httpx.MockTransport(_handler),
    )

    assert request_counts == {"catalog": 1}
    assert catalog["count"] == 1
    assert catalog["total_count"] == 1
    assert catalog["materials"][0]["material_id"] == "mat_cloud_1"


def test_material_sync_install_from_registry_endpoint_installs_selected_package(
    monkeypatch,
) -> None:
    def _fake_list_material_registry_catalog(*, limit: int | None = None, offset: int = 0) -> dict[str, object]:
        catalog = {
            "schema_version": "1.0",
            "channels": ["official"],
            "count": 1,
            "materials": [
                {
                    "material_id": "mat_cloud_test",
                    "revision_id": "rev_cloud_test",
                    "content_hash": "sha256:cloud",
                    "channel": "official",
                    "visibility": "official",
                    "local_directory": "BrandA/pla-basic",
                    "display": {"brand": "BrandA", "material_name": "PLA Basic"},
                    "compatibility": {},
                    "package_url": "/v1/packages/material_package.zip",
                    "package_sha256": "a" * 64,
                    "package_bytes": 1234,
                }
            ],
        }
        # A capped registry can serve the selected revision after its default page.
        if offset == 0:
            return {**catalog, "source_scope": "test", "offset": 0, "total_count": 2,
                    "materials": [{"material_id": "unrelated", "revision_id": "older"}]}
        assert (offset, limit) == (1, 500)
        return {**catalog, "source_scope": "test", "offset": offset, "total_count": 2}

    def _fake_install_material_registry_package(
        *,
        package_url: str,
        package_sha256: str,
        material_id: str,
        revision_id: str,
        display: dict[str, object],
        channel: str,
    ) -> dict[str, object]:
        assert display == {"brand": "BrandA", "material_name": "PLA Basic"}
        assert channel == "official"
        assert package_url == "/v1/packages/material_package.zip"
        assert package_sha256 == "a" * 64
        assert material_id == "mat_cloud_test"
        assert revision_id == "rev_cloud_test"
        return {
            "registry_url": "https://registry.test/v1",
            "material_id": material_id,
            "revision_id": revision_id,
            "installed_count": 1,
            "installed_materials": [
                {
                    "material_name": "PLA Basic",
                    "directory_name": "BrandA/pla-basic",
                    "brand": "BrandA",
                    "archive_path": "materials/BrandA/pla-basic/material.json",
                    "stage_a_params_path": (
                        "materials/BrandA/pla-basic/stage_A_parameters.json"
                    ),
                }
            ],
        }

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )
    monkeypatch.setattr(
        "api.routers.material_sync.install_material_registry_package",
        _fake_install_material_registry_package,
    )

    response = _client().post(
        "/api/material-sync/install-from-registry",
        json={
            "package_url": "/v1/packages/material_package.zip",
            "package_sha256": "a" * 64,
            "material_id": "mat_cloud_test",
            "revision_id": "rev_cloud_test",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["installed_count"] == 1
    assert body["installed_materials"][0]["directory_name"] == "BrandA/pla-basic"
    assert "archive_path" not in body["installed_materials"][0]
    assert "stage_a_params_path" not in body["installed_materials"][0]
    assert "materials/BrandA/pla-basic/material.json" not in response.text
    assert "materials/BrandA/pla-basic/stage_A_parameters.json" not in response.text


def test_material_sync_install_from_registry_rejects_package_not_in_catalog(
    monkeypatch,
) -> None:
    _enable_material_registry_password(monkeypatch)
    install_called = False

    def _fake_list_material_registry_catalog() -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "channels": ["official"],
            "count": 1,
            "materials": [
                {
                    "material_id": "mat_cloud_test",
                    "revision_id": "rev_cloud_test",
                    "content_hash": "sha256:cloud",
                    "channel": "official",
                    "visibility": "official",
                    "local_directory": "BrandA/pla-basic",
                    "display": {"brand": "BrandA", "material_name": "PLA Basic"},
                    "compatibility": {},
                    "package_url": "/v1/packages/material_package.zip",
                    "package_sha256": "a" * 64,
                    "package_bytes": 1234,
                }
            ],
        }

    def _fake_install_material_registry_package(**_: object) -> dict[str, object]:
        nonlocal install_called
        install_called = True
        return {
            "registry_url": "https://registry.test/v1",
            "material_id": "mat_cloud_test",
            "revision_id": "rev_cloud_test",
            "installed_count": 0,
            "installed_materials": [],
        }

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )
    monkeypatch.setattr(
        "api.routers.material_sync.install_material_registry_package",
        _fake_install_material_registry_package,
    )

    response = _client().post(
        "/api/material-sync/install-from-registry",
        json={
            "package_url": "https://evil.test/material_package.zip",
            "package_sha256": "a" * 64,
            "material_id": "mat_cloud_test",
            "revision_id": "rev_cloud_test",
        },
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 422
    assert "current material registry catalog" in response.json()["detail"]
    assert install_called is False


def test_material_sync_install_from_registry_maps_invalid_package_to_502(
    monkeypatch,
) -> None:
    _enable_material_registry_password(monkeypatch)

    def _fake_list_material_registry_catalog() -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "channels": ["official"],
            "count": 1,
            "materials": [
                {
                    "material_id": "mat_cloud_test",
                    "revision_id": "rev_cloud_test",
                    "content_hash": "sha256:cloud",
                    "channel": "official",
                    "visibility": "official",
                    "local_directory": "BrandA/pla-basic",
                    "display": {"brand": "BrandA", "material_name": "PLA Basic"},
                    "compatibility": {},
                    "package_url": "/v1/packages/material_package.zip",
                    "package_sha256": "a" * 64,
                    "package_bytes": 1234,
                }
            ],
        }

    def _fake_install_material_registry_package(**_: object) -> dict[str, object]:
        raise FileNotFoundError("Saved material archive not found in ZIP")

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )
    monkeypatch.setattr(
        "api.routers.material_sync.install_material_registry_package",
        _fake_install_material_registry_package,
    )

    response = _client().post(
        "/api/material-sync/install-from-registry",
        json={
            "package_url": "/v1/packages/material_package.zip",
            "package_sha256": "a" * 64,
            "material_id": "mat_cloud_test",
            "revision_id": "rev_cloud_test",
        },
        headers=_AUTH_HEADERS,
    )

    assert response.status_code == 502
    assert response.json()["detail"] == MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL
    assert "Saved material archive" not in response.text


@pytest.mark.parametrize(
    ("exc", "status_code", "forbidden_fragments"),
    [
        (
            RuntimeError(
                "Material registry package request failed for "
                "https://registry.internal/private/material_package.zip: status 500"
            ),
            502,
            ("https://registry.internal/private/material_package.zip", "status 500"),
        ),
        (
            FileNotFoundError(
                "Saved material archive not found in "
                "/Users/min/private/materials/BrandA/pla-basic/material.json"
            ),
            502,
            (
                "/Users/min/private/materials/BrandA/pla-basic/material.json",
                "Saved material archive",
            ),
        ),
        (
            OSError(
                "[Errno 13] Permission denied: "
                "'/Users/min/private/materials/BrandA/pla-basic/material.json'"
            ),
            500,
            (
                "/Users/min/private/materials/BrandA/pla-basic/material.json",
                "Permission denied",
            ),
        ),
        (
            ValueError(
                "Material bundle file hash mismatch: "
                "/Users/min/private/materials/BrandA/pla-basic/material.json"
            ),
            502,
            (
                "/Users/min/private/materials/BrandA/pla-basic/material.json",
                "hash mismatch",
            ),
        ),
        (
            TypeError(
                "Material bundle manifest parser failed for "
                "/Users/min/private/materials/BrandA/pla-basic/material.json"
            ),
            502,
            (
                "/Users/min/private/materials/BrandA/pla-basic/material.json",
                "parser failed",
            ),
        ),
    ],
)
def test_material_sync_install_from_registry_failures_return_safe_detail(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
    exc: Exception,
    status_code: int,
    forbidden_fragments: tuple[str, ...],
) -> None:
    _enable_material_registry_password(monkeypatch)

    def _fake_install_material_registry_package(**_: object) -> dict[str, object]:
        raise exc

    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        _registry_install_catalog,
    )
    monkeypatch.setattr(
        "api.routers.material_sync.install_material_registry_package",
        _fake_install_material_registry_package,
    )

    loggers = _capture_material_sync_logs(caplog)
    try:
        response = _client().post(
            "/api/material-sync/install-from-registry",
            json={
                "package_url": "/v1/packages/material_package.zip",
                "package_sha256": "a" * 64,
                "material_id": "mat_cloud_test",
                "revision_id": "rev_cloud_test",
            },
            headers=_AUTH_HEADERS,
        )
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == status_code
    assert response.json()["detail"] == MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL
    for fragment in forbidden_fragments:
        assert fragment not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/install-from-registry",
        status_code=status_code,
        detail=MATERIAL_SYNC_INSTALL_UNAVAILABLE_DETAIL,
        forbidden_fragments=forbidden_fragments,
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_install_from_registry_failed",
        error_type=type(exc).__name__,
        raw_fragment=forbidden_fragments[0],
        status_code=status_code,
    )
    route_record = _records_for_event(
        caplog,
        "material_sync_install_from_registry_failed",
    )[-1]
    assert getattr(route_record, "material_id", None) == "mat_cloud_test"
    assert getattr(route_record, "revision_id", None) == "rev_cloud_test"


def test_material_sync_install_from_registry_rejects_missing_catalog_entry_without_password(
    monkeypatch,
) -> None:
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_OFFICIAL_PASSWORD", _OFFICIAL_PASSWORD)
    monkeypatch.setattr(
        "api.routers.material_sync.list_material_registry_catalog",
        lambda: {
            "schema_version": "1.0",
            "channels": ["official"],
            "count": 0,
            "materials": [],
        },
    )

    response = _client().post(
        "/api/material-sync/install-from-registry",
        json={
            "package_url": "/v1/packages/material_package.zip",
            "package_sha256": "a" * 64,
            "material_id": "mat_cloud_test",
            "revision_id": "rev_cloud_test",
        },
    )

    assert response.status_code == 422


def test_install_material_registry_package_imports_only_selected_material(
    tmp_path: Path, monkeypatch,
) -> None:
    materials_root = tmp_path / "materials"
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", "")
    package_path = tmp_path / "multi_material_package.zip"
    package_info = _write_v2_multi_material_package(package_path)
    package_bytes = package_path.read_bytes()

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/packages/multi_material_package.zip":
            return httpx.Response(200, content=package_bytes)
        return httpx.Response(404)

    result = install_material_registry_package(
        registry_url="https://registry.test/v1",
        package_url="/v1/packages/multi_material_package.zip",
        package_sha256=package_info["package_sha256"],
        material_id=package_info["selected_material_id"],
        revision_id=package_info["selected_revision_id"],
        display={"market_names": {"INTL": "Selected International"}, "sku": "OLD-101"},
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert result["installed_count"] == 1
    assert result["installed_materials"][0]["directory_name"] == "BrandA/pla-selected"
    assert (materials_root / "BrandA" / "pla-selected" / "material.json").is_file()
    assert (materials_root / "BrandA" / "pla-other" / "material.json").exists() is False
    [local] = material_library.list_saved_stage_a_material_archives(materials_dir=str(materials_root))
    assert local["display"]["market_names"] == {"INTL": "Selected International"}
    assert local["display"]["sku"] == "OLD-101"
    assert local["sync_material_id"] == package_info["selected_material_id"]


def test_refresh_material_sync_from_registry_imports_only_catalog_revision(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    package_path = tmp_path / "multi_material_package.zip"
    package_info = _write_v2_multi_material_package(package_path)
    package_bytes = package_path.read_bytes()

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": package_info["selected_material_id"],
                            "revision_id": package_info["selected_revision_id"],
                            "content_hash": package_info["selected_content_hash"],
                            "channel": "official",
                            "visibility": "official",
                            "package_url": "/v1/packages/multi_material_package.zip",
                            "package_sha256": package_info["package_sha256"],
                        }
                    ],
                },
            )
        if request.url.path == "/v1/packages/multi_material_package.zip":
            return httpx.Response(200, content=package_bytes)
        return httpx.Response(404)

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert result["installed_count"] == 1
    assert result["failed_count"] == 0
    assert result["installed_materials"][0]["directory_name"] == "BrandA/pla-selected"
    assert (materials_root / "BrandA" / "pla-selected" / "material.json").is_file()
    assert (materials_root / "BrandA" / "pla-other" / "material.json").exists() is False


@pytest.mark.parametrize("catalog_key", ["materials", "packages"])
def test_public_registry_refresh_fails_over_catalog_and_package(tmp_path, monkeypatch, catalog_key):
    primary = "https://primary.test/v1"
    backup = "https://backup.test/v1"
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_URL", primary)
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_FALLBACK_URL", backup)
    monkeypatch.delenv("LUMINA_MATERIAL_REGISTRY_TOKEN", raising=False)
    package_path = tmp_path / "bundle.zip"
    info = _write_v2_multi_material_package(package_path)
    package_bytes = package_path.read_bytes()
    calls = []
    def handle(request):
        calls.append((request.url.host, request.url.path))
        if request.url.host == "primary.test":
            return httpx.Response(503)
        if request.url.path.endswith("/catalog"):
            assert "if-none-match" not in request.headers
            return httpx.Response(200, headers={"etag": '"backup-only"'}, json={catalog_key: [{
                "material_id": info["selected_material_id"],
                "revision_id": info["selected_revision_id"],
                "content_hash": info["selected_content_hash"], "channel": "official",
                "visibility": "official", "package_url": backup + "/packages/bundle.zip",
                "package_sha256": info["package_sha256"],
            }]})
        return httpx.Response(200, content=package_bytes)
    root = tmp_path / "materials"
    result = refresh_material_sync_from_registry(
        materials_dir=str(root), channels=["official"], transport=httpx.MockTransport(handle))
    assert result["installed_count"] == 1
    assert result["failed_count"] == 0
    assert (root / "BrandA" / "pla-selected" / "material.json").is_file()
    assert not (root / "BrandA" / "pla-other").exists()
    assert calls == [("primary.test", "/v1/materials/catalog"), ("backup.test", "/v1/materials/catalog"),
                     ("primary.test", "/v1/packages/bundle.zip"), ("backup.test", "/v1/packages/bundle.zip")]


def test_refresh_material_sync_from_registry_adopts_exact_local_material(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    package_path = tmp_path / "material_package.zip"
    content_hash = _write_v2_material_package(
        package_path,
        material_id="mat_registry_test",
        revision_id="rev_registry_test",
    )
    package_bytes = package_path.read_bytes()
    package_sha256 = hashlib.sha256(package_bytes).hexdigest()
    local_material_dir = materials_root / "BrandA" / "pla-basic"
    local_material_dir.mkdir(parents=True)
    with zipfile.ZipFile(package_path, "r") as archive:
        local_material_dir.joinpath("material.json").write_bytes(
            archive.read("materials/BrandA/pla-basic/material.json")
        )
        local_material_dir.joinpath("stage_A_parameters.json").write_bytes(
            archive.read("materials/BrandA/pla-basic/stage_A_parameters.json")
        )
    request_counts = {"catalog": 0, "package": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            request_counts["catalog"] += 1
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": "mat_registry_test",
                            "revision_id": "rev_registry_test",
                            "content_hash": content_hash,
                            "channel": "official",
                            "local_directory": "BrandA/pla-basic",
                            "display": {
                                "brand": "BrandA",
                                "material_name": "PLA Basic Imported",
                            },
                            "package_url": "/v1/packages/material_package.zip",
                            "package_sha256": package_sha256,
                        }
                    ],
                },
            )
        if request.url.path == "/v1/packages/material_package.zip":
            request_counts["package"] += 1
            return httpx.Response(200, content=package_bytes)
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)
    first = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=transport,
    )
    second = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=transport,
    )

    assert first["installed_count"] == 0
    assert first["skipped_count"] == 1
    assert first["failed_count"] == 0
    assert second["installed_count"] == 0
    assert second["skipped_count"] == 1
    assert second["failed_count"] == 0
    assert request_counts == {"catalog": 2, "package": 0}
    assert len(list(materials_root.rglob("material.json"))) == 1
    index = json.loads((materials_root / "_sync" / "index.json").read_text("utf-8"))
    installed = index["installed"]["mat_registry_test"]
    assert installed["revision_id"] == "rev_registry_test"
    assert installed["content_hash"] == content_hash
    assert installed["local_directory"] == "BrandA/pla-basic"
    assert installed["source"] == "registry_adopted"


@pytest.mark.parametrize(
    "material_order",
    [
        ("mat_a", "mat_b"),
        ("mat_b", "mat_a"),
    ],
)
def test_refresh_material_sync_from_registry_rejects_ambiguous_catalog_adoption(
    tmp_path: Path,
    material_order: tuple[str, str],
) -> None:
    materials_root = tmp_path / "materials"
    package_path = tmp_path / "material_package.zip"
    content_hash = _write_v2_material_package(
        package_path,
        material_id="mat_source",
        revision_id="rev_source",
    )
    local_material_dir = materials_root / "BrandA" / "pla-basic"
    local_material_dir.mkdir(parents=True)
    with zipfile.ZipFile(package_path, "r") as archive:
        local_material_dir.joinpath("material.json").write_bytes(
            archive.read("materials/BrandA/pla-basic/material.json")
        )
        local_material_dir.joinpath("stage_A_parameters.json").write_bytes(
            archive.read("materials/BrandA/pla-basic/stage_A_parameters.json")
        )
    original_payloads = {
        path.name: path.read_bytes()
        for path in local_material_dir.iterdir()
        if path.is_file()
    }
    requested_paths: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": material_id,
                            "revision_id": f"rev_{material_id[-1]}",
                            "content_hash": content_hash,
                            "channel": "official",
                            "local_directory": "BrandA/pla-basic",
                            "package_url": f"/v1/packages/{material_id}.zip",
                            "package_sha256": "a" * 64,
                        }
                        for material_id in material_order
                    ],
                },
            )
        return httpx.Response(500, content=b"package download must not run")

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert result["checked_count"] == 2
    assert result["installed_count"] == 0
    assert result["skipped_count"] == 0
    assert result["failed_count"] == 2
    assert {failure["material_id"] for failure in result["failures"]} == {
        "mat_a",
        "mat_b",
    }
    assert all(
        failure["error"].startswith("ambiguous_local_match:")
        for failure in result["failures"]
    )
    assert requested_paths == ["/v1/materials/catalog"]
    assert {
        path.name: path.read_bytes()
        for path in local_material_dir.iterdir()
        if path.is_file()
    } == original_payloads
    index = json.loads((materials_root / "_sync" / "index.json").read_text("utf-8"))
    assert index["installed"] == {}
    registry_state = index["registries"]["https://registry.test/v1"]
    assert registry_state["checked_count"] == 2
    assert registry_state["installed_count"] == 0
    assert registry_state["skipped_count"] == 0
    assert registry_state["failed_count"] == 2


def test_refresh_material_sync_from_registry_preserves_modified_local_material(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    package_path = tmp_path / "material_package.zip"
    content_hash = _write_v2_material_package(
        package_path,
        material_id="mat_registry_test",
        revision_id="rev_registry_test",
    )
    package_bytes = package_path.read_bytes()
    local_material_dir = materials_root / "BrandA" / "pla-basic"
    local_material_dir.mkdir(parents=True)
    with zipfile.ZipFile(package_path, "r") as archive:
        material_payload = archive.read("materials/BrandA/pla-basic/material.json")
        local_material_dir.joinpath("material.json").write_bytes(
            material_payload + b"\n"
        )
        local_material_dir.joinpath("stage_A_parameters.json").write_bytes(
            archive.read("materials/BrandA/pla-basic/stage_A_parameters.json")
        )
    package_requests = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal package_requests
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": "mat_registry_test",
                            "revision_id": "rev_registry_test",
                            "content_hash": content_hash,
                            "channel": "official",
                            "local_directory": "BrandA/pla-basic",
                            "package_url": "/v1/packages/material_package.zip",
                            "package_sha256": hashlib.sha256(package_bytes).hexdigest(),
                        }
                    ],
                },
            )
        if request.url.path == "/v1/packages/material_package.zip":
            package_requests += 1
            return httpx.Response(200, content=package_bytes)
        return httpx.Response(404)

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert result["installed_count"] == 1
    assert result["skipped_count"] == 0
    assert result["failed_count"] == 0
    assert package_requests == 1
    assert (
        local_material_dir.joinpath("material.json").read_bytes()
        == material_payload + b"\n"
    )
    assert len(list(materials_root.rglob("material.json"))) == 2
    index = json.loads((materials_root / "_sync" / "index.json").read_text("utf-8"))
    installed_directory = index["installed"]["mat_registry_test"]["local_directory"]
    assert installed_directory.startswith("BrandA/pla-basic_")


def test_refresh_material_sync_from_registry_fails_closed_for_multiple_revisions(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    requested_paths: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": "mat_ambiguous",
                            "revision_id": "rev_a",
                            "content_hash": "sha256:a",
                            "channel": "official",
                            "local_directory": "BrandA/pla-a",
                            "package_url": "/v1/packages/rev_a.zip",
                            "package_sha256": "a" * 64,
                        },
                        {
                            "material_id": "mat_ambiguous",
                            "revision_id": "rev_b",
                            "content_hash": "sha256:b",
                            "channel": "official",
                            "local_directory": "BrandA/pla-b",
                            "package_url": "/v1/packages/rev_b.zip",
                            "package_sha256": "b" * 64,
                        },
                    ],
                },
            )
        return httpx.Response(500, content=b"package download must not run")

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert result["checked_count"] == 2
    assert result["installed_count"] == 0
    assert result["skipped_count"] == 0
    assert result["failed_count"] == 2
    assert all(
        failure["error"].startswith("ambiguous_revision:")
        for failure in result["failures"]
    )
    assert {failure["revision_id"] for failure in result["failures"]} == {
        "rev_a",
        "rev_b",
    }
    assert requested_paths == ["/v1/materials/catalog"]
    assert list(materials_root.rglob("material.json")) == []


def test_refresh_material_sync_from_registry_preserves_installed_ambiguous_revision(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    package_path = tmp_path / "rev_a.zip"
    rev_a_content_hash = _write_v2_material_package(
        package_path,
        material_id="mat_ambiguous",
        revision_id="rev_a",
        local_directory="BrandA/pla-a",
    )
    material_dir = materials_root / "BrandA" / "pla-a"
    _extract_v2_material_files(
        package_path,
        material_dir,
        local_directory="BrandA/pla-a",
    )
    sync_dir = materials_root / "_sync"
    sync_dir.mkdir()
    sync_dir.joinpath("index.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "installed": {
                    "mat_ambiguous": {
                        "revision_id": "rev_a",
                        "content_hash": rev_a_content_hash,
                        "channel": "official",
                        "source": "package",
                        "local_directory": "BrandA/pla-a",
                    }
                },
                "revisions": {},
            }
        ),
        encoding="utf-8",
    )
    requested_paths: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": "mat_ambiguous",
                            "revision_id": "rev_a",
                            "content_hash": rev_a_content_hash,
                            "channel": "official",
                            "local_directory": "BrandA/pla-a",
                            "package_url": "/v1/packages/rev_a.zip",
                            "package_sha256": "a" * 64,
                        },
                        {
                            "material_id": "mat_ambiguous",
                            "revision_id": "rev_b",
                            "content_hash": "sha256:b",
                            "channel": "official",
                            "local_directory": "BrandA/pla-b",
                            "package_url": "/v1/packages/rev_b.zip",
                            "package_sha256": "b" * 64,
                        },
                    ],
                },
            )
        return httpx.Response(500, content=b"package download must not run")

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert result["checked_count"] == 2
    assert result["installed_count"] == 0
    assert result["skipped_count"] == 1
    assert result["failed_count"] == 1
    assert result["failures"][0]["revision_id"] == "rev_b"
    assert result["failures"][0]["error"].startswith("ambiguous_revision:")
    assert requested_paths == ["/v1/materials/catalog"]
    index = json.loads(sync_dir.joinpath("index.json").read_text("utf-8"))
    assert index["installed"]["mat_ambiguous"]["revision_id"] == "rev_a"


def test_install_material_registry_package_rejects_cross_origin_package_url(
    tmp_path: Path,
) -> None:
    requested_urls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, content=b"not used")

    try:
        install_material_registry_package(
            registry_url="https://registry.test/v1",
            package_url="https://attacker.test/pkg.zip",
            package_sha256="a" * 64,
            material_id="mat_cloud_test",
            revision_id="rev_cloud_test",
            materials_dir=str(tmp_path / "materials"),
            token="team-token",
            transport=httpx.MockTransport(_handler),
        )
    except ValueError as exc:
        assert "same origin" in str(exc)
    else:
        raise AssertionError("Expected cross-origin package_url to be rejected")

    assert requested_urls == []


def test_install_material_registry_package_rejects_cross_origin_redirect(
    tmp_path: Path,
) -> None:
    requested_urls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.host == "registry.test":
            return httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            )
        return httpx.Response(200, content=b"unexpected redirected request")

    try:
        install_material_registry_package(
            registry_url="https://registry.test/v1",
            package_url="/v1/packages/redirect.zip",
            package_sha256="a" * 64,
            material_id="mat_cloud_test",
            revision_id="rev_cloud_test",
            materials_dir=str(tmp_path / "materials"),
            token="team-token",
            transport=httpx.MockTransport(_handler),
        )
    except ValueError as exc:
        assert "redirects" in str(exc)
    else:
        raise AssertionError("Expected redirected package download to be rejected")

    assert requested_urls == ["https://registry.test/v1/packages/redirect.zip"]


def test_material_package_import_rejects_zip_entry_count_limit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    package_path = tmp_path / "material_package.zip"
    _write_v2_material_package(package_path)
    monkeypatch.setenv("LUMINA_MATERIAL_PACKAGE_MAX_ZIP_ENTRIES", "2")

    with pytest.raises(ValueError, match="too many entries"):
        material_library.import_saved_stage_a_material_archives(
            archive_path=str(package_path),
            materials_dir=str(tmp_path / "materials"),
        )


def test_refresh_material_sync_from_registry_rejects_oversized_package(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    package_path = tmp_path / "material_package.zip"
    content_hash = _write_v2_material_package(package_path)
    package_bytes = package_path.read_bytes()
    monkeypatch.setenv(
        "LUMINA_MATERIAL_PACKAGE_MAX_ARCHIVE_BYTES",
        str(len(package_bytes) - 1),
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": "mat_sync_test",
                            "revision_id": "rev_sync_test",
                            "content_hash": content_hash,
                            "channel": "official",
                            "package_url": "/v1/packages/material_package.zip",
                            "package_sha256": hashlib.sha256(package_bytes).hexdigest(),
                        }
                    ],
                },
            )
        if request.url.path == "/v1/packages/material_package.zip":
            return httpx.Response(
                200,
                content=package_bytes,
                headers={"content-length": str(len(package_bytes))},
            )
        return httpx.Response(404)

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert result["installed_count"] == 0
    assert result["failed_count"] == 1
    assert "exceeds maximum size" in result["failures"][0]["error"]
    assert (materials_root / "BrandA" / "pla-basic" / "material.json").exists() is False


def test_refresh_material_sync_from_registry_installs_new_revision_and_skips_same_revision(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    package_path = tmp_path / "material_package.zip"
    content_hash = _write_v2_material_package(
        package_path,
        material_id="mat_registry_test",
        revision_id="rev_registry_test",
    )
    package_bytes = package_path.read_bytes()
    package_sha256 = hashlib.sha256(package_bytes).hexdigest()
    request_counts = {"catalog": 0, "package": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            request_counts["catalog"] += 1
            assert request.headers["authorization"] == "Bearer team-token"
            assert request.url.params.get_list("channel") == ["official", "team"]
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "cursor": "cursor-1",
                    "materials": [
                        {
                            "material_id": "mat_registry_test",
                            "revision_id": "rev_registry_test",
                            "content_hash": content_hash,
                            "channel": "team",
                            "package_url": "/v1/packages/material_package.zip",
                            "package_sha256": package_sha256,
                        }
                    ],
                },
            )
        if request.url.path == "/v1/packages/material_package.zip":
            request_counts["package"] += 1
            return httpx.Response(200, content=package_bytes)
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)

    first = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        channels=["official", "team"],
        token="team-token",
        materials_dir=str(materials_root),
        transport=transport,
    )
    second = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        channels=["official", "team"],
        token="team-token",
        materials_dir=str(materials_root),
        transport=transport,
    )

    assert first["checked_count"] == 1
    assert first["installed_count"] == 1
    assert first["skipped_count"] == 0
    assert first["failed_count"] == 0
    assert first["installed_materials"][0]["directory_name"] == "BrandA/pla-basic"
    assert second["installed_count"] == 0
    assert second["skipped_count"] == 1
    assert request_counts == {"catalog": 2, "package": 1}

    index = json.loads((materials_root / "_sync" / "index.json").read_text("utf-8"))
    assert "https://registry.test/v1" in index["registries"]
    assert index["catalog_validators"] == {}
    assert index["registries"]["https://registry.test/v1"]["channels"] == [
        "official",
        "team",
    ]


def test_refresh_material_sync_from_registry_persists_etag_and_reuses_it_after_restart(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    package_path = tmp_path / "material_package.zip"
    content_hash = _write_v2_material_package(
        package_path,
        material_id="mat_registry_test",
        revision_id="rev_registry_test",
    )
    package_bytes = package_path.read_bytes()
    package_sha256 = hashlib.sha256(package_bytes).hexdigest()
    catalog_etag = 'W/"catalog-v1"'
    catalog_headers: list[str | None] = []
    package_requests = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal package_requests
        if request.url.path == "/v1/materials/catalog":
            catalog_headers.append(request.headers.get("if-none-match"))
            if request.headers.get("if-none-match") == catalog_etag:
                return httpx.Response(304, headers={"ETag": catalog_etag})
            return httpx.Response(
                200,
                headers={"ETag": catalog_etag},
                json={
                    "schema_version": "1.0",
                    "materials": [
                        _registry_catalog_entry(
                            content_hash=content_hash,
                            package_sha256=package_sha256,
                        )
                    ],
                },
            )
        if request.url.path == "/v1/packages/material_package.zip":
            package_requests += 1
            return httpx.Response(200, content=package_bytes)
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)
    first = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=transport,
    )
    local_material_dir = materials_root / "BrandA" / "pla-basic"
    local_material_dir.joinpath("usage_stats.json").write_text(
        json.dumps({"total": 1}),
        encoding="utf-8",
    )
    solver_cache = local_material_dir / "_solver_cache"
    solver_cache.mkdir()
    solver_cache.joinpath("solution.json").write_text("{}", encoding="utf-8")
    second = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=transport,
    )

    assert first["catalog_not_modified"] is False
    assert first["installed_count"] == 1
    assert second["catalog_not_modified"] is True
    assert second["checked_count"] == 1
    assert second["installed_count"] == 0
    assert second["skipped_count"] == 1
    assert catalog_headers == [None, catalog_etag]
    assert package_requests == 1

    index = json.loads((materials_root / "_sync" / "index.json").read_text("utf-8"))
    validator = index["catalog_validators"]["https://registry.test/v1"]["official"]
    assert index["schema_version"] == "1.0"
    assert validator["etag"] == catalog_etag
    assert validator["checked_count"] == 1
    assert validator["channels"] == ["official"]
    assert set(json.loads(validator["local_state_hash"])) == {"materials", "bindings"}

    monkeypatch.setattr(material_files, "MATERIALS_DIR", str(materials_root))
    status_response = _client().get("/api/material-sync/status")
    assert status_response.status_code == 200
    assert "catalog_validators" not in status_response.text
    assert catalog_etag not in status_response.text
    assert validator["local_state_hash"] not in status_response.text


@pytest.mark.parametrize("drift_kind", ["delete", "modify"])
def test_refresh_material_sync_from_registry_repairs_local_content_drift(
    tmp_path: Path,
    drift_kind: str,
) -> None:
    materials_root = tmp_path / "materials"
    package_path = tmp_path / "material_package.zip"
    content_hash = _write_v2_material_package(
        package_path,
        material_id="mat_registry_test",
        revision_id="rev_registry_test",
    )
    package_bytes = package_path.read_bytes()
    package_sha256 = hashlib.sha256(package_bytes).hexdigest()
    catalog_etag = 'W/"catalog-v1"'
    conditional_headers: list[str | None] = []
    package_requests = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal package_requests
        if request.url.path == "/v1/materials/catalog":
            conditional_headers.append(request.headers.get("if-none-match"))
            return httpx.Response(
                200,
                headers={"ETag": catalog_etag},
                json={
                    "schema_version": "1.0",
                    "materials": [
                        _registry_catalog_entry(
                            content_hash=content_hash,
                            package_sha256=package_sha256,
                        )
                    ],
                },
            )
        if request.url.path == "/v1/packages/material_package.zip":
            package_requests += 1
            return httpx.Response(200, content=package_bytes)
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)
    refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=transport,
    )
    original_dir = materials_root / "BrandA" / "pla-basic"
    original_material_bytes = (original_dir / "material.json").read_bytes()
    if drift_kind == "delete":
        (original_dir / "stage_A_parameters.json").unlink()
    else:
        (original_dir / "material.json").write_bytes(
            original_material_bytes + b"\n"
        )

    repaired = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=transport,
    )

    assert repaired["catalog_not_modified"] is False
    assert repaired["installed_count"] == 1
    assert repaired["failed_count"] == 0
    assert conditional_headers == [None, None]
    assert package_requests == 2
    if drift_kind == "delete":
        assert (original_dir / "stage_A_parameters.json").exists() is False
    else:
        assert (
            original_dir.joinpath("material.json").read_bytes()
            == original_material_bytes + b"\n"
        )
    index = json.loads((materials_root / "_sync" / "index.json").read_text("utf-8"))
    repaired_directory = index["installed"]["mat_registry_test"]["local_directory"]
    assert repaired_directory.startswith("BrandA/pla-basic_")
    assert (
        materials_root / Path(repaired_directory) / "stage_A_parameters.json"
    ).is_file()


def test_refresh_material_sync_from_registry_retries_once_when_304_races_with_drift(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    package_path = tmp_path / "material_package.zip"
    content_hash = _write_v2_material_package(
        package_path,
        material_id="mat_registry_test",
        revision_id="rev_registry_test",
    )
    package_bytes = package_path.read_bytes()
    package_sha256 = hashlib.sha256(package_bytes).hexdigest()
    catalog_etag = 'W/"catalog-v1"'
    catalog_headers: list[str | None] = []
    package_requests = 0

    def _catalog_payload() -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "materials": [
                _registry_catalog_entry(
                    content_hash=content_hash,
                    package_sha256=package_sha256,
                )
            ],
        }

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal package_requests
        if request.url.path == "/v1/materials/catalog":
            conditional_etag = request.headers.get("if-none-match")
            catalog_headers.append(conditional_etag)
            if len(catalog_headers) == 2:
                assert conditional_etag == catalog_etag
                material_path = (
                    materials_root / "BrandA" / "pla-basic" / "material.json"
                )
                material_path.write_bytes(material_path.read_bytes() + b"\n")
                return httpx.Response(304, headers={"ETag": catalog_etag})
            return httpx.Response(
                200,
                headers={"ETag": catalog_etag},
                json=_catalog_payload(),
            )
        if request.url.path == "/v1/packages/material_package.zip":
            package_requests += 1
            return httpx.Response(200, content=package_bytes)
        return httpx.Response(404)

    transport = httpx.MockTransport(_handler)
    refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=transport,
    )
    raced = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=transport,
    )

    assert catalog_headers == [None, catalog_etag, None]
    assert package_requests == 2
    assert raced["catalog_not_modified"] is False
    assert raced["installed_count"] == 1
    assert raced["failed_count"] == 0
    assert len(list(materials_root.rglob("material.json"))) == 2


def test_refresh_material_sync_from_registry_rejects_cross_origin_package_url(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    requested_urls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": "mat_registry_test",
                            "revision_id": "rev_registry_test",
                            "content_hash": "sha256:abc",
                            "channel": "official",
                            "package_url": "https://attacker.test/pkg.zip",
                            "package_sha256": "a" * 64,
                        }
                    ],
                },
            )
        return httpx.Response(500)

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        token="team-token",
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert requested_urls == ["https://registry.test/v1/materials/catalog?channel=official"]
    assert result["checked_count"] == 1
    assert result["installed_count"] == 0
    assert result["failed_count"] == 1
    assert "same origin" in result["failures"][0]["error"]
    assert (materials_root / "BrandA" / "pla-basic" / "material.json").exists() is False


def test_refresh_material_sync_from_registry_rejects_cross_origin_redirect(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    requested_urls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": "mat_registry_test",
                            "revision_id": "rev_registry_test",
                            "content_hash": "sha256:abc",
                            "channel": "official",
                            "package_url": "/v1/packages/redirect.zip",
                            "package_sha256": "a" * 64,
                        }
                    ],
                },
            )
        if request.url.host == "registry.test":
            return httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            )
        return httpx.Response(200, content=b"unexpected redirected request")

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        token="team-token",
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert requested_urls == [
        "https://registry.test/v1/materials/catalog?channel=official",
        "https://registry.test/v1/packages/redirect.zip",
    ]
    assert result["checked_count"] == 1
    assert result["installed_count"] == 0
    assert result["failed_count"] == 1
    assert "redirects" in result["failures"][0]["error"]
    assert (materials_root / "BrandA" / "pla-basic" / "material.json").exists() is False


def test_refresh_material_sync_from_registry_rejects_catalog_cross_origin_redirect(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    requested_urls: list[str] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest/meta-data/"},
            )
        return httpx.Response(200, json={"schema_version": "1.0", "materials": []})

    with pytest.raises(RuntimeError, match="catalog redirects are not allowed"):
        refresh_material_sync_from_registry(
            registry_url="https://registry.test/v1",
            token="team-token",
            materials_dir=str(materials_root),
            transport=httpx.MockTransport(_handler),
        )

    assert requested_urls == [
        "https://registry.test/v1/materials/catalog?channel=official"
    ]
    assert (materials_root / "BrandA" / "pla-basic" / "material.json").exists() is False


def test_refresh_material_sync_from_registry_preserves_local_rollback(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    old_package_path = tmp_path / "rev_old.zip"
    new_package_path = tmp_path / "rev_new.zip"
    old_content_hash = _write_v2_material_package(
        old_package_path,
        material_id="mat_test",
        revision_id="rev_old",
        local_directory="BrandA/pla-basic",
    )
    new_content_hash = _write_v2_material_package(
        new_package_path,
        material_id="mat_test",
        revision_id="rev_new",
        local_directory="BrandA/pla-basic-new",
    )
    old_dir = materials_root / "BrandA" / "pla-basic"
    new_dir = materials_root / "BrandA" / "pla-basic-new"
    _extract_v2_material_files(
        old_package_path,
        old_dir,
        local_directory="BrandA/pla-basic",
    )
    _extract_v2_material_files(
        new_package_path,
        new_dir,
        local_directory="BrandA/pla-basic-new",
    )
    (materials_root / "_sync").mkdir()
    (materials_root / "_sync" / "index.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "installed": {
                    "mat_test": {
                        "revision_id": "rev_old",
                        "content_hash": old_content_hash,
                        "channel": "official",
                        "source": "package",
                        "local_directory": "BrandA/pla-basic",
                        "display_brand": "BrandA",
                        "display_name": "PLA Basic",
                    }
                },
                "revisions": {
                    "mat_test": {
                        "rev_new": {
                            "revision_id": "rev_new",
                            "content_hash": new_content_hash,
                            "channel": "official",
                            "source": "package",
                            "local_directory": "BrandA/pla-basic-new",
                            "display_brand": "BrandA",
                            "display_name": "PLA Basic",
                        },
                        "rev_old": {
                            "revision_id": "rev_old",
                            "content_hash": old_content_hash,
                            "channel": "official",
                            "source": "package",
                            "local_directory": "BrandA/pla-basic",
                            "display_brand": "BrandA",
                            "display_name": "PLA Basic",
                        },
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    request_counts = {"catalog": 0, "package": 0}

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            request_counts["catalog"] += 1
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": "mat_test",
                            "revision_id": "rev_new",
                            "content_hash": new_content_hash,
                            "channel": "official",
                            "package_url": "/v1/packages/rev_new.zip",
                            "package_sha256": "a" * 64,
                        }
                    ],
                },
            )
        if request.url.path == "/v1/packages/rev_new.zip":
            request_counts["package"] += 1
            return httpx.Response(500)
        return httpx.Response(404)

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert result["checked_count"] == 1
    assert result["installed_count"] == 0
    assert result["skipped_count"] == 1
    assert result["failed_count"] == 0
    assert request_counts == {"catalog": 1, "package": 0}
    index = json.loads((materials_root / "_sync" / "index.json").read_text("utf-8"))
    assert index["installed"]["mat_test"]["revision_id"] == "rev_old"


def test_refresh_material_sync_from_registry_preserves_index_when_catalog_unavailable(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    material_dir = materials_root / "BrandA" / "pla-basic"
    material_dir.mkdir(parents=True)
    (material_dir / "material.json").write_text("{}", encoding="utf-8")
    sync_dir = materials_root / "_sync"
    sync_dir.mkdir()
    index_path = sync_dir / "index.json"
    index_payload = {
        "schema_version": "1.0",
        "installed": {
            "mat_test": {
                "revision_id": "rev_old",
                "content_hash": "sha256:old",
                "channel": "official",
                "source": "package",
                "local_directory": "BrandA/pla-basic",
                "display_brand": "BrandA",
                "display_name": "PLA Basic",
            }
        },
        "revisions": {
            "mat_test": {
                "rev_old": {
                    "revision_id": "rev_old",
                    "content_hash": "sha256:old",
                    "channel": "official",
                    "source": "package",
                    "local_directory": "BrandA/pla-basic",
                    "display_brand": "BrandA",
                    "display_name": "PLA Basic",
                }
            }
        },
    }
    index_path.write_text(json.dumps(index_payload, ensure_ascii=False), encoding="utf-8")
    before_index = index_path.read_text(encoding="utf-8")

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/materials/catalog"
        return httpx.Response(503, json={"detail": "temporarily unavailable"})

    with pytest.raises(RuntimeError, match="catalog request failed"):
        refresh_material_sync_from_registry(
            registry_url="https://registry.test/v1",
            materials_dir=str(materials_root),
            transport=httpx.MockTransport(_handler),
        )

    assert index_path.read_text(encoding="utf-8") == before_index
    assert (material_dir / "material.json").is_file()


def test_refresh_material_sync_from_registry_reports_corrupt_package_without_install(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    package_path = tmp_path / "material_package.zip"
    content_hash = _write_v2_material_package(package_path)
    package_bytes = package_path.read_bytes()

    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/materials/catalog":
            return httpx.Response(
                200,
                json={
                    "schema_version": "1.0",
                    "materials": [
                        {
                            "material_id": "mat_sync_test",
                            "revision_id": "rev_sync_test",
                            "content_hash": content_hash,
                            "channel": "official",
                            "package_url": "/v1/packages/material_package.zip",
                            "package_sha256": "sha256:deadbeef",
                        }
                    ],
                },
            )
        if request.url.path == "/v1/packages/material_package.zip":
            return httpx.Response(200, content=package_bytes)
        return httpx.Response(404)

    result = refresh_material_sync_from_registry(
        registry_url="https://registry.test/v1",
        materials_dir=str(materials_root),
        transport=httpx.MockTransport(_handler),
    )

    assert result["checked_count"] == 1
    assert result["installed_count"] == 0
    assert result["failed_count"] == 1
    assert result["failures"][0]["material_id"] == "mat_sync_test"
    assert "package_sha256" in result["failures"][0]["error"]
    assert (materials_root / "BrandA" / "pla-basic" / "material.json").exists() is False


def test_material_sync_status_lists_installed_package_and_local_presence(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    material_dir = materials_root / "Generic" / "PLA Basic"
    material_dir.mkdir(parents=True)
    (material_dir / "material.json").write_text(
        json.dumps({"material_name": "PLA Basic", "brand": "Generic"}),
        encoding="utf-8",
    )
    (materials_root / "_sync").mkdir()
    (materials_root / "_sync" / "index.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "last_sync_at": "2026-06-08T01:02:03+00:00",
                "registries": {},
                "installed": {
                    "mat_test": {
                        "revision_id": "rev_test",
                        "content_hash": "sha256:abc",
                        "channel": "stable",
                        "source": "package",
                        "local_directory": "Generic/PLA Basic",
                        "display_brand": "Generic",
                        "display_name": "PLA Basic",
                        "installed_at": "2026-06-08T01:02:03+00:00",
                        "updated_at": "2026-06-08T01:02:03+00:00",
                    }
                },
                "local_overrides": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("core.single_stage.material_files.MATERIALS_DIR", str(materials_root))

    response = _client().get("/api/material-sync/status")

    assert response.status_code == 200
    body = response.json()
    assert body["index_state"] == "ready"
    assert body["last_sync_at"] == "2026-06-08T01:02:03+00:00"
    assert body["installed_count"] == 1
    assert body["installed"][0] == {
        "material_id": "mat_test",
        "revision_id": "rev_test",
        "content_hash": "sha256:abc",
        "channel": "stable",
        "source": "package",
        "local_directory": "Generic/PLA Basic",
        "display_brand": "Generic",
        "display_name": "PLA Basic",
        "installed_at": "2026-06-08T01:02:03+00:00",
        "updated_at": "2026-06-08T01:02:03+00:00",
        "local_exists": True,
        "material_file_exists": True,
        "available_revisions": [],
        "revision_history": [],
    }


def test_material_sync_status_handles_corrupt_index_without_traceback(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    (materials_root / "_sync").mkdir(parents=True)
    (materials_root / "_sync" / "index.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr("core.single_stage.material_files.MATERIALS_DIR", str(materials_root))

    response = _client().get("/api/material-sync/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["index_state"] == "invalid"
    assert body["installed_count"] == 0
    assert body["installed"] == []


def test_material_library_api_marks_official_synced_material(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    material_dir = materials_root / "BrandA" / "pla-basic"
    material_dir.mkdir(parents=True)
    (material_dir / "material.json").write_text(
        json.dumps(
            {
                "material_name": "PLA Basic",
                "brand": "BrandA",
                "stage_a_params_file": "stage_A_parameters.json",
                "material_summary": {"estimated_rgb": [120, 130, 140]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (material_dir / "stage_A_parameters.json").write_text(json.dumps({
        "parameters": {
            "channels": [{"E": [0.1, 0.2, 0.3], "k": [1.0, 1.1, 1.2]}],
            "substrates": [{"substrate_id": "white", "C0": [1.0, 1.0, 1.0]}],
        },
    }), encoding="utf-8")
    (materials_root / "_sync").mkdir()
    (materials_root / "_sync" / "index.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "installed": {
                    "mat_official": {
                        "revision_id": "rev_official",
                        "content_hash": "sha256:official",
                        "channel": "official",
                        "source": "package",
                        "local_directory": "BrandA/pla-basic",
                        "display_brand": "BrandA",
                        "display_name": "PLA Basic",
                    }
                },
                "revisions": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("core.single_stage.material_files.MATERIALS_DIR", str(materials_root))

    response = _client().get("/api/extractor/gradient-card-materials")

    assert response.status_code == 200
    material = response.json()["materials"][0]
    assert material["sync_material_id"] == "mat_official"
    assert material["sync_revision_id"] == "rev_official"
    assert material["sync_channel"] == "official"
    assert material["sync_official"] is True


def test_material_library_api_marks_cloud_official_matching_local_material(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    material_dir = materials_root / "BrandA" / "pla-basic"
    material_dir.mkdir(parents=True)
    material_payload = json.dumps(
        {
            "material_name": "PLA Basic",
            "brand": "BrandA",
            "stage_a_params_file": "stage_A_parameters.json",
            "material_summary": {"estimated_rgb": [120, 130, 140]},
        },
        ensure_ascii=False,
    )
    stage_a_payload = json.dumps({
        "parameters": {
            "channels": [{"E": [0.1, 0.2, 0.3], "k": [1.0, 1.1, 1.2]}],
            "substrates": [{"substrate_id": "white", "C0": [1.0, 1.0, 1.0]}],
        },
    }, ensure_ascii=False)
    (material_dir / "material.json").write_text(material_payload, encoding="utf-8")
    (material_dir / "stage_A_parameters.json").write_text(
        stage_a_payload,
        encoding="utf-8",
    )
    material_hash = hashlib.sha256(material_payload.encode("utf-8")).hexdigest()
    stage_a_hash = hashlib.sha256(stage_a_payload.encode("utf-8")).hexdigest()
    content_hash = "sha256:" + hashlib.sha256(
        f"material.json:{material_hash}\nstage_A_parameters.json:{stage_a_hash}".encode(
            "utf-8"
        )
    ).hexdigest()

    def _fake_list_material_registry_catalog(**_: object) -> dict[str, object]:
        return {
            "schema_version": "1.0",
            "channels": ["official"],
            "count": 1,
            "total_count": 1,
            "offset": 0,
            "limit": None,
            "materials": [
                {
                    "material_id": "mat_cloud_official",
                    "revision_id": "rev_cloud_official",
                    "content_hash": content_hash,
                    "channel": "official",
                    "visibility": "official",
                    "local_directory": "BrandA/pla-basic",
                    "display": {"brand": "BrandA", "material_name": "PLA Basic"},
                    "compatibility": {},
                    "package_url": "/v1/packages/official/pla-basic.zip",
                    "package_sha256": "a" * 64,
                    "package_bytes": 1024,
                }
            ],
        }

    monkeypatch.setattr(
        material_registry_client,
        "list_material_registry_catalog",
        _fake_list_material_registry_catalog,
    )
    monkeypatch.setattr("core.single_stage.material_files.MATERIALS_DIR", str(materials_root))

    response = _client().get("/api/extractor/gradient-card-materials")

    assert response.status_code == 200
    material = response.json()["materials"][0]
    assert material["sync_material_id"] == "mat_cloud_official"
    assert material["sync_revision_id"] == "rev_cloud_official"
    assert material["sync_channel"] == "official"
    assert material["sync_official"] is True


def test_material_sync_rollback_switches_installed_revision(
    monkeypatch,
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    old_dir = materials_root / "BrandA" / "pla-basic"
    new_dir = materials_root / "BrandA" / "pla-basic-new"
    old_dir.mkdir(parents=True)
    new_dir.mkdir(parents=True)
    (old_dir / "material.json").write_text("{}", encoding="utf-8")
    (new_dir / "material.json").write_text("{}", encoding="utf-8")
    (materials_root / "_sync").mkdir()
    (materials_root / "_sync" / "index.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "installed": {
                    "mat_test": {
                        "revision_id": "rev_new",
                        "content_hash": "sha256:new",
                        "channel": "official",
                        "source": "package",
                        "local_directory": "BrandA/pla-basic-new",
                        "display_brand": "BrandA",
                        "display_name": "PLA Basic",
                        "installed_at": "2026-06-08T02:00:00+00:00",
                        "updated_at": "2026-06-08T02:00:00+00:00",
                    }
                },
                "revisions": {
                    "mat_test": {
                        "rev_old": {
                            "revision_id": "rev_old",
                            "content_hash": "sha256:old",
                            "channel": "official",
                            "source": "package",
                            "local_directory": "BrandA/pla-basic",
                            "display_brand": "BrandA",
                            "display_name": "PLA Basic",
                            "installed_at": "2026-06-08T01:00:00+00:00",
                            "updated_at": "2026-06-08T01:00:00+00:00",
                        }
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("core.single_stage.material_files.MATERIALS_DIR", str(materials_root))

    response = _client().post(
        "/api/material-sync/rollback",
        json={"material_id": "mat_test", "revision_id": "rev_old"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["material_id"] == "mat_test"
    assert body["revision_id"] == "rev_old"
    assert body["local_directory"] == "BrandA/pla-basic"

    index = json.loads((materials_root / "_sync" / "index.json").read_text("utf-8"))
    assert index["installed"]["mat_test"]["revision_id"] == "rev_old"
    assert "rev_new" in index["revisions"]["mat_test"]


def test_material_sync_rollback_is_local_without_official_password(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LUMINA_MATERIAL_REGISTRY_OFFICIAL_PASSWORD", _OFFICIAL_PASSWORD)
    materials_root = tmp_path / "materials"
    material_dir = materials_root / "BrandA" / "pla-basic"
    material_dir.mkdir(parents=True)
    (material_dir / "material.json").write_text("{}", encoding="utf-8")
    (materials_root / "_sync").mkdir()
    (materials_root / "_sync" / "index.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "installed": {},
                "revisions": {
                    "mat_test": {
                        "rev_old": {
                            "revision_id": "rev_old",
                            "content_hash": "sha256:old",
                            "channel": "official",
                            "source": "package",
                            "local_directory": "BrandA/pla-basic",
                        }
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("core.single_stage.material_files.MATERIALS_DIR", str(materials_root))

    response = _client().post(
        "/api/material-sync/rollback",
        json={"material_id": "mat_test", "revision_id": "rev_old"},
    )

    assert response.status_code == 200
    assert response.json()["revision_id"] == "rev_old"


def test_material_sync_rollback_os_error_returns_safe_detail(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_path = "/Users/min/private/materials/_sync/index.json"

    def _fake_rollback_material_sync_revision(
        *,
        material_id: str,
        revision_id: str,
    ) -> dict[str, object]:
        raise OSError(f"[Errno 13] Permission denied: '{private_path}'")

    monkeypatch.setattr(
        "api.routers.material_sync.rollback_material_sync_revision",
        _fake_rollback_material_sync_revision,
    )

    loggers = _capture_material_sync_logs(caplog)
    try:
        response = _client().post(
            "/api/material-sync/rollback",
            json={"material_id": "mat_test", "revision_id": "rev_old"},
        )
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == 500
    assert response.json()["detail"] == MATERIAL_SYNC_ROLLBACK_UNAVAILABLE_DETAIL
    assert private_path not in response.text
    assert "Permission denied" not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/rollback",
        status_code=500,
        detail=MATERIAL_SYNC_ROLLBACK_UNAVAILABLE_DETAIL,
        forbidden_fragments=(private_path, "Permission denied"),
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_rollback_failed",
        error_type="OSError",
        raw_fragment=private_path,
        status_code=500,
    )
    route_record = _records_for_event(caplog, "material_sync_rollback_failed")[-1]
    assert getattr(route_record, "material_id", None) == "mat_test"
    assert getattr(route_record, "revision_id", None) == "rev_old"


def test_material_sync_rollback_missing_revision_returns_safe_detail(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_detail = "Material sync rollback target is missing material.json: BrandA/missing"

    def _fake_rollback_material_sync_revision(
        *,
        material_id: str,
        revision_id: str,
    ) -> dict[str, object]:
        raise FileNotFoundError(raw_detail)

    monkeypatch.setattr(
        "api.routers.material_sync.rollback_material_sync_revision",
        _fake_rollback_material_sync_revision,
    )

    loggers = _capture_material_sync_logs(caplog)
    try:
        response = _client().post(
            "/api/material-sync/rollback",
            json={"material_id": "mat_test", "revision_id": "rev_missing"},
        )
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == 404
    assert response.json()["detail"] == MATERIAL_SYNC_ROLLBACK_UNAVAILABLE_DETAIL
    assert "BrandA/missing" not in response.text
    assert "material.json" not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/rollback",
        status_code=404,
        detail=MATERIAL_SYNC_ROLLBACK_UNAVAILABLE_DETAIL,
        forbidden_fragments=("BrandA/missing", "material.json"),
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_rollback_failed",
        error_type="FileNotFoundError",
        raw_fragment=raw_detail,
        status_code=404,
    )
    route_record = _records_for_event(caplog, "material_sync_rollback_failed")[-1]
    assert getattr(route_record, "material_id", None) == "mat_test"
    assert getattr(route_record, "revision_id", None) == "rev_missing"


def test_material_sync_rollback_value_error_returns_safe_detail(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    private_path = "/Users/min/private/materials/_sync/index.json"
    raw_detail = f"Material sync index is invalid: {private_path}"

    def _fake_rollback_material_sync_revision(
        *,
        material_id: str,
        revision_id: str,
    ) -> dict[str, object]:
        raise ValueError(raw_detail)

    monkeypatch.setattr(
        "api.routers.material_sync.rollback_material_sync_revision",
        _fake_rollback_material_sync_revision,
    )

    loggers = _capture_material_sync_logs(caplog)
    try:
        response = _client().post(
            "/api/material-sync/rollback",
            json={"material_id": "mat_test", "revision_id": "rev_old"},
        )
    finally:
        _release_caplog_handler(loggers, caplog)

    assert response.status_code == 422
    assert response.json()["detail"] == MATERIAL_SYNC_ROLLBACK_UNAVAILABLE_DETAIL
    assert private_path not in response.text
    assert "Material sync index is invalid" not in response.text
    _assert_http_error_log_safe(
        caplog,
        path="/api/material-sync/rollback",
        status_code=422,
        detail=MATERIAL_SYNC_ROLLBACK_UNAVAILABLE_DETAIL,
        forbidden_fragments=(private_path, "Material sync index is invalid"),
    )
    _assert_route_failure_log_preserves_diagnostics(
        caplog,
        event="material_sync_rollback_failed",
        error_type="ValueError",
        raw_fragment=raw_detail,
        status_code=422,
    )
    route_record = _records_for_event(caplog, "material_sync_rollback_failed")[-1]
    assert getattr(route_record, "material_id", None) == "mat_test"
    assert getattr(route_record, "revision_id", None) == "rev_old"


def test_rollback_material_sync_revision_rejects_missing_local_files(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    (materials_root / "_sync").mkdir(parents=True)
    (materials_root / "_sync" / "index.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "installed": {},
                "revisions": {
                    "mat_test": {
                        "rev_missing": {
                            "revision_id": "rev_missing",
                            "content_hash": "sha256:missing",
                            "channel": "official",
                            "source": "package",
                            "local_directory": "BrandA/missing",
                            "display_brand": "BrandA",
                            "display_name": "Missing",
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    try:
        rollback_material_sync_revision(
            material_id="mat_test",
            revision_id="rev_missing",
            materials_dir=str(materials_root),
        )
    except FileNotFoundError as exc:
        assert "material.json" in str(exc)
    else:
        raise AssertionError("rollback should reject missing material files")


def test_refresh_material_sync_from_registry_uses_cross_process_lock(
    tmp_path: Path,
) -> None:
    materials_root = tmp_path / "materials"
    sync_dir = materials_root / "_sync"
    sync_dir.mkdir(parents=True)
    (sync_dir / "refresh.lock").write_text("active", encoding="utf-8")
    request_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(500)

    try:
        refresh_material_sync_from_registry(
            registry_url="https://registry.test/v1",
            materials_dir=str(materials_root),
            transport=httpx.MockTransport(_handler),
        )
    except RuntimeError as exc:
        assert "already running" in str(exc)
    else:
        raise AssertionError("refresh should reject an active file lock")

    assert request_count == 0
