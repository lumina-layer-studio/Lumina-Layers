"""Unit tests for the feedback router.

测试覆盖：
- 同步路径返回 ``assembly_status == 'in_progress'``、
  ``submission_status`` 为 ``'pending'`` / ``'disabled'``
- 工单目录 ``feedback/<YYYY-MM>/<ticket_id>/ticket.json`` 正确落地
- 失败场景（screenshot 过大 / 校验失败 / 目录写入失败）
- 工单上传状态查询与失败重传
"""

from __future__ import annotations

import asyncio
import json
import logging
import zipfile
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

UNTRUSTED_ORIGIN_HEADERS = {"Origin": "https://attacker.example"}
LOCAL_FRONTEND_ORIGIN_HEADERS = {"Origin": "http://localhost:5174"}
DESCRIPTION_RAW_DIAGNOSTICS = (
    r"导出失败：AxiosError: Request failed with status code 500 "
    r"at /Users/min/private/model.3mf; retry /api/files/output-model; "
    r"file:///Users/min/private/source.png; C:\Users\min\secret\source.png"
)
GENERIC_HTTP_STATUS_DETAIL = (
    "The server reported an error while processing this request."
)


def _capture_feedback_logger(
    caplog: pytest.LogCaptureFixture,
    level: int,
) -> logging.Logger:
    target_logger = logging.getLogger("lumina.api.routers.feedback")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(level, logger=target_logger.name)
    return target_logger


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "description": "Preview failed after generate.",
        "user_email": None,
        "context": {
            "url": "http://localhost:5174/",
            "user_agent": "pytest",
            "screen_width": 1280,
            "screen_height": 720,
            "device_pixel_ratio": 1.0,
            "app_version": "2.0.0",
            "language": "en",
            "theme": "light",
            "active_tab": "converter",
            "active_session_ids": {"converter": "session-abcdef", "single_stage": None},
            "color_mode": "4-Color (RYBW)",
            "lut_name": None,
            "source_version": "legacy",
            "selected_native_brand_key": None,
            "selected_native_db_names": [],
            "selected_material_dir_names": [],
            "material_layer_count": None,
            "material_layer_height_mm": None,
            "material_backing_material_dir_name": None,
            "preserve_upload_filename_for_3mf": False,
            "enable_wipe_tower_auto_placement": False,
            "enable_smooth_vector_preview": True,
            "vector_preview_renderer": "vector_analytic",
            "recent_client_logs": [
                {
                    "timestamp": "2026-05-10T01:02:03.000Z",
                    "method": "error",
                    "label": "api: request failed",
                    "elapsed_ms": 12.346,
                    "scope": "api",
                    "phase": "request-failed",
                    "details": {"status_code": 500},
                }
            ],
            "action_history": [],
            "session_history": [],
            "active_original_image_ref": None,
            "active_final_artifact_ref": None,
            "advanced_params": None,
        },
        "screenshot_data_url": None,
    }
    payload.update(overrides)
    return payload


def _read_ticket_json(feedback_root: Path, ticket_id: str) -> dict[str, Any]:
    """Locate ``feedback/<YYYY-MM>/<ticket_id>/ticket.json`` and decode it."""
    for month_dir in feedback_root.iterdir():
        if not month_dir.is_dir():
            continue
        candidate = month_dir / ticket_id / "ticket.json"
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    raise AssertionError(f"ticket.json for {ticket_id} not found under {feedback_root}")


def _iter_json_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for key, item in value.items():
            strings.append(str(key))
            strings.extend(_iter_json_strings(item))
        return strings
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_iter_json_strings(item))
        return strings
    return []


def _assert_description_diagnostics_complete(text: str) -> None:
    assert "Request failed with status code 500" in text
    assert "AxiosError" in text
    assert "/Users/min/private" in text
    assert "file:///Users/min" in text
    assert "[redacted_local_path]" not in text
    assert "/api/files/output-model" in text



def test_bug_report_context_preserves_dynamic_material_scalars() -> None:
    from api.routers.feedback import BugReportContext

    context = dict(_payload()["context"])
    context.update(
        {
            "source_version": "material",
            "material_dynamic_layer_count_enabled": True,
            "material_min_layer_count": 5,
            "material_max_layer_count": 9,
            "material_delta_e00_tolerance": 0.4,
        }
    )

    dumped = BugReportContext.model_validate(context).model_dump()

    assert dumped["material_dynamic_layer_count_enabled"] is True
    assert dumped["material_min_layer_count"] == 5
    assert dumped["material_max_layer_count"] == 9
    assert dumped["material_delta_e00_tolerance"] == pytest.approx(0.4)


def test_bug_report_context_preserves_build_plate_selection() -> None:
    from api.routers.feedback import BugReportContext

    context = dict(_payload()["context"])
    context.update(
        {
            "printer_id": "bambu-h2d",
            "slicer": "BambuStudio",
            "nozzle_size": "0.4",
            "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
            "build_plate_id": "smooth-pei-plate",
        }
    )

    dumped = BugReportContext.model_validate(context).model_dump()

    assert dumped["build_plate_id"] == "smooth-pei-plate"
    assert dumped["device_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d:0.4"


def test_bug_report_context_preserves_upload_filename_preference() -> None:
    from api.routers.feedback import BugReportContext

    context = dict(_payload()["context"])
    context["preserve_upload_filename_for_3mf"] = True

    dumped = BugReportContext.model_validate(context).model_dump()

    assert dumped["preserve_upload_filename_for_3mf"] is True

    context.pop("preserve_upload_filename_for_3mf")
    legacy_dumped = BugReportContext.model_validate(context).model_dump()
    assert legacy_dumped["preserve_upload_filename_for_3mf"] is None


def test_bug_report_context_preserves_wipe_tower_auto_placement() -> None:
    from api.routers.feedback import BugReportContext

    context = dict(_payload()["context"])
    context["enable_wipe_tower_auto_placement"] = False

    dumped = BugReportContext.model_validate(context).model_dump()

    assert dumped["enable_wipe_tower_auto_placement"] is False

    context.pop("enable_wipe_tower_auto_placement")
    legacy_dumped = BugReportContext.model_validate(context).model_dump()
    assert legacy_dumped["enable_wipe_tower_auto_placement"] is None


def test_bug_report_context_preserves_vector_preview_renderer() -> None:
    from api.routers.feedback import BugReportContext

    context = dict(_payload()["context"])
    context.update(
        {
            "enable_smooth_vector_preview": True,
            "vector_preview_renderer": "vector_analytic",
        }
    )

    dumped = BugReportContext.model_validate(context).model_dump()

    assert dumped["enable_smooth_vector_preview"] is True
    assert dumped["vector_preview_renderer"] == "vector_analytic"

    context.pop("enable_smooth_vector_preview")
    context.pop("vector_preview_renderer")
    legacy_dumped = BugReportContext.model_validate(context).model_dump()
    assert legacy_dumped["enable_smooth_vector_preview"] is None
    assert legacy_dumped["vector_preview_renderer"] is None


@pytest.fixture()
def feedback_root(tmp_path: Path) -> Path:
    root = tmp_path / "feedback_root"
    root.mkdir()
    return root


@pytest.fixture()
def client(
    monkeypatch: pytest.MonkeyPatch,
    feedback_root: Path,
) -> TestClient:
    from api.app import create_app

    monkeypatch.setenv("LUMINA_FEEDBACK_DUMP_DIR", str(feedback_root))
    monkeypatch.setenv("LUMINA_FEEDBACK_STARTUP_CLEANUP", "false")
    # Never reach the real feedback server from unit tests.
    monkeypatch.setenv("LUMINA_FEEDBACK_SERVER_URL", "off")
    app = create_app()
    return TestClient(app)


def test_external_spool_identity_is_preserved_in_saved_ticket(client, feedback_root) -> None:
    payload = _payload()
    material = "PETG Basic 黑色"
    payload["context"].update(
        printer_id="bambu-lab-x2d", external_spool_material=material,
        advanced_params={"generation": {"external_spool_material": material}},
    )
    response = client.post("/api/feedback/bug-report", json=payload)
    assert response.status_code == 200, response.text
    ticket = _read_ticket_json(feedback_root, response.json()["ticket_id"])
    assert ticket["context"]["external_spool_material"] == material
    assert ticket["context"]["advanced_params"]["generation"]["external_spool_material"] == material


def test_submit_bug_report_accepts_full_payload_and_logs_canary(
    client: TestClient,
    feedback_root: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _capture_feedback_logger(caplog, logging.INFO)
    payload = _payload(
        user_email="user@example.com",
        screenshot_data_url="data:image/png;base64," + ("a" * 1024),
    )

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["ticket_id"].startswith("LUM-")
    assert data["submission_status"] == "disabled"
    assert "email_status" not in data and "relay_available" not in data
    assert data["assembly_status"] in ("in_progress", "done", "partial_failed")
    assert data["dump_path"].endswith(data["ticket_id"])

    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["schema_version"] == 3
    assert ticket_json["ticket_id"] == data["ticket_id"]
    assert ticket_json["description"] == payload["description"]
    assert ticket_json["context"]["preserve_upload_filename_for_3mf"] is False
    assert ticket_json["context"]["enable_smooth_vector_preview"] is True
    assert ticket_json["context"]["vector_preview_renderer"] == "vector_analytic"
    assert ticket_json["attachments"]["screenshot"]["status"] == "attached"

    canaries = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_bug_report_submitted"
    ]
    assert len(canaries) == 1
    assert canaries[0].ticket_id == data["ticket_id"]
    assert canaries[0].description_length == len(payload["description"])
    assert canaries[0].language == "en"
    assert canaries[0].has_screenshot is True
    assert canaries[0].submission_status == "disabled"
    assert canaries[0].source_version == "legacy"
    assert canaries[0].recent_client_log_count == 1


@pytest.mark.parametrize("legacy_env_value", ["", "1"])
def test_submit_bug_report_rejects_untrusted_origin_before_ticket_write(
    client: TestClient,
    feedback_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    legacy_env_value: str,
) -> None:
    monkeypatch.setenv("LUMINA_ALLOW_PUBLIC_GRAY_API", legacy_env_value)
    response = client.post(
        "/api/feedback/bug-report",
        json=_payload(description="cross-origin probe"),
        headers=UNTRUSTED_ORIGIN_HEADERS,
    )

    assert response.status_code == 403
    assert "local Lumina Studio app" in response.json()["detail"]
    assert list(feedback_root.rglob("ticket.json")) == []


def test_submit_bug_report_allows_local_frontend_origin(
    client: TestClient,
    feedback_root: Path,
) -> None:
    response = client.post(
        "/api/feedback/bug-report",
        json=_payload(description="local frontend report"),
        headers=LOCAL_FRONTEND_ORIGIN_HEADERS,
    )

    assert response.status_code == 200
    ticket_id = response.json()["ticket_id"]
    ticket_json = _read_ticket_json(feedback_root, ticket_id)
    assert ticket_json["description"] == "local frontend report"


def test_submit_bug_report_rejects_unregistered_final_artifact_disk_path(
    client: TestClient,
    feedback_root: Path,
) -> None:
    """A crafted disk_path cannot attach an unregistered output artifact.

    构造请求中的 disk_path 不能把未注册 output 产物附进反馈工单。
    """
    from api.feedback_assembler import REPO_ROOT

    output_dir = REPO_ROOT / "output" / "feedback_security_probe"
    output_dir.mkdir(parents=True, exist_ok=True)
    sentinel = output_dir / "foreign_model.3mf"
    sentinel.write_bytes(b"PK\x03\x04FOREIGN_MODEL_SENTINEL")

    try:
        payload = _payload()
        payload["context"]["active_final_artifact_ref"] = {
            "session_id": "not-the-current-session",
            "download_url": None,
            "artifact_type": "3mf",
            "disk_path": str(sentinel),
            "source": "converter",
        }

        response = client.post("/api/feedback/bug-report", json=payload)

        assert response.status_code == 200
        data = response.json()
        ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
        final_artifact = ticket_json["attachments"]["final_artifact"]
        assert final_artifact["status"] == "expired_ttl"

        month_dir = next(
            p for p in feedback_root.iterdir() if p.is_dir() and p.name.startswith("20")
        )
        ticket_dir = month_dir / data["ticket_id"]
        assert not (ticket_dir / "final.3mf").exists()
        assert not (ticket_dir / "final.zip").exists()
    finally:
        sentinel.unlink(missing_ok=True)
        try:
            output_dir.rmdir()
        except OSError:
            pass


def test_submit_bug_report_accepts_description_only(client: TestClient) -> None:
    response = client.post("/api/feedback/bug-report", json=_payload(description="Only text"))

    assert response.status_code == 200
    data = response.json()
    assert data["submission_status"] == "disabled"
    assert data["assembly_status"] in ("in_progress", "done", "partial_failed")


def test_bug_report_openapi_declares_json_and_multipart_bodies(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    request_body = schema["paths"]["/api/feedback/bug-report"]["post"][
        "requestBody"
    ]

    assert request_body["required"] is True
    content = request_body["content"]
    assert content["application/json"]["schema"] == {
        "$ref": "#/components/schemas/BugReportRequest",
    }
    multipart_schema = content["multipart/form-data"]["schema"]
    assert multipart_schema["required"] == ["request_payload"]
    assert multipart_schema["properties"]["original_image"] == {
        "type": "string",
        "format": "binary",
    }
    assert multipart_schema["properties"][
        "original_image_omission_reason"
    ]["enum"] == ["too_large"]




@pytest.mark.parametrize(
    ("filename", "mime_type", "original_bytes"),
    [
        ("source.png", "image/png", b"\x89PNG\r\nEXACT_SOURCE"),
        (
            "source.svg",
            "image/svg+xml",
            b'<svg xmlns="http://www.w3.org/2000/svg"><rect/></svg>',
        ),
        ("source.heic", "image/heic", b"ftypheic\x00EXACT_SOURCE"),
        ("source.raw", "application/octet-stream", b"RAW_EXACT_SOURCE"),
    ],
)
def test_submit_bug_report_multipart_saves_exact_original_without_session(
    client: TestClient,
    feedback_root: Path,
    filename: str,
    mime_type: str,
    original_bytes: bytes,
) -> None:
    """Pre-preview PNG/SVG/HEIC/RAW reports preserve exact browser bytes."""
    payload = _payload(description="Preview failed before session creation")
    payload["context"]["active_session_ids"]["converter"] = None
    payload["context"]["active_original_image_ref"] = {
        "session_id": None,
        "filename": filename,
        "source": "converter",
    }

    response = client.post(
        "/api/feedback/bug-report",
        files={
            "request_payload": (
                None,
                json.dumps(payload),
                "application/json",
            ),
            "original_image": (
                filename,
                original_bytes,
                mime_type,
            ),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["original_image_status"] == "attached"
    ticket_dir = next(feedback_root.glob(f"*/{data['ticket_id']}"))
    original_path = ticket_dir / f"original{Path(filename).suffix}"
    assert original_path.read_bytes() == original_bytes

    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    original = ticket_json["attachments"]["original_image"]
    assert original["status"] == "attached"
    assert original["capture_source"] == "browser_upload"
    assert original["direct_upload_status"] == "attached"
    assert original["source_session_id"] is None
    assert original["size_bytes"] == len(original_bytes)
    assert "sha256" not in original


def test_submit_bug_report_multipart_uses_direct_upload_before_session(
    client: TestClient,
    feedback_root: Path,
    tmp_path: Path,
) -> None:
    from api.dependencies import get_file_registry

    session_id = "direct-upload-priority-session"
    session_source = tmp_path / "session-source.png"
    session_source.write_bytes(b"SESSION_SOURCE")
    get_file_registry().register_path(
        session_id=session_id,
        path=str(session_source),
        filename=session_source.name,
    )
    payload = _payload(description="Direct source wins")
    payload["context"]["active_original_image_ref"] = {
        "session_id": session_id,
        "filename": "browser-source.svg",
        "source": "converter",
    }

    response = client.post(
        "/api/feedback/bug-report",
        files={
            "request_payload": (None, json.dumps(payload), "application/json"),
            "original_image": (
                r"..\..\browser-source.svg",
                b"<svg>DIRECT_SOURCE</svg>",
                "image/svg+xml",
            ),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["original_image_status"] == "attached"
    ticket_dir = next(feedback_root.glob(f"*/{data['ticket_id']}"))
    assert (ticket_dir / "original.svg").read_bytes() == b"<svg>DIRECT_SOURCE</svg>"
    assert not (ticket_dir / "original.png").exists()
    assert not (tmp_path / "browser-source.svg").exists()


def test_submit_bug_report_direct_write_failure_falls_back_to_session(
    client: TestClient,
    feedback_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from api.dependencies import get_file_registry

    session_id = "direct-write-failure-session"
    session_source = tmp_path / "session-source.png"
    session_source.write_bytes(b"SESSION_FALLBACK")
    get_file_registry().register_path(
        session_id=session_id,
        path=str(session_source),
        filename=session_source.name,
    )
    payload = _payload(description="Direct write fails, session survives")
    payload["context"]["active_original_image_ref"] = {
        "session_id": session_id,
        "filename": "browser-source.svg",
        "source": "converter",
    }
    real_path_open = Path.open

    def fail_direct_original_open(
        path: Path,
        mode: str = "r",
        *args: Any,
        **kwargs: Any,
    ):
        if path.name == "original.svg" and mode == "xb":
            raise OSError("simulated direct write failure")
        return real_path_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_direct_original_open)

    response = client.post(
        "/api/feedback/bug-report",
        files={
            "request_payload": (None, json.dumps(payload), "application/json"),
            "original_image": (
                "browser-source.svg",
                b"<svg>DIRECT_SOURCE</svg>",
                "image/svg+xml",
            ),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["original_image_status"] == "session_fallback"
    ticket_dir = next(feedback_root.glob(f"*/{data['ticket_id']}"))
    assert not (ticket_dir / "original.svg").exists()
    assert (ticket_dir / "original.png").read_bytes() == b"SESSION_FALLBACK"
    original = _read_ticket_json(
        feedback_root,
        data["ticket_id"],
    )["attachments"]["original_image"]
    assert original["capture_source"] == "file_registry"
    assert original["direct_upload_status"] == "failed"


def test_submit_bug_report_oversized_omission_falls_back_to_session(
    client: TestClient,
    feedback_root: Path,
    tmp_path: Path,
) -> None:
    from api.dependencies import get_file_registry

    session_id = "oversized-fallback-session"
    session_source = tmp_path / "session-source.png"
    session_source.write_bytes(b"SESSION_FALLBACK")
    get_file_registry().register_path(
        session_id=session_id,
        path=str(session_source),
        filename=session_source.name,
    )
    payload = _payload(description="Browser source exceeds upload limit")
    payload["context"]["active_original_image_ref"] = {
        "session_id": session_id,
        "filename": "oversized.png",
        "source": "converter",
    }

    response = client.post(
        "/api/feedback/bug-report",
        files={
            "request_payload": (None, json.dumps(payload), "application/json"),
            "original_image_omission_reason": (None, "too_large"),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["original_image_status"] == "session_fallback"
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    original = ticket_json["attachments"]["original_image"]
    assert original["status"] == "attached"
    assert original["capture_source"] == "file_registry"
    assert original["direct_upload_status"] == "too_large"


def test_submit_bug_report_oversized_original_does_not_block_text_report(
    client: TestClient,
    feedback_root: Path,
) -> None:
    payload = _payload(description="Oversized source still reports")
    payload["context"]["active_session_ids"]["converter"] = None
    payload["context"]["active_original_image_ref"] = {
        "session_id": None,
        "filename": "oversized.png",
        "source": "converter",
    }

    response = client.post(
        "/api/feedback/bug-report",
        files={
            "request_payload": (None, json.dumps(payload), "application/json"),
            "original_image_omission_reason": (None, "too_large"),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["original_image_status"] == "too_large"
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["description"] == "Oversized source still reports"
    assert ticket_json["attachments"]["original_image"]["status"] == "too_large"
    ticket_dir = next(feedback_root.glob(f"*/{data['ticket_id']}"))
    assert list(ticket_dir.glob("original.*")) == []


def test_stream_original_is_saved_without_a_size_cutoff(
    client: TestClient,
    feedback_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.routers.feedback as feedback_router
    from api.dependencies import get_file_registry

    monkeypatch.setattr(feedback_router, "MAX_DIRECT_ORIGINAL_IMAGE_BYTES", 8, raising=False)
    session_id = "stream-oversized-fallback-session"
    session_source = tmp_path / "session-source.png"
    session_source.write_bytes(b"SESSION_FALLBACK")
    get_file_registry().register_path(
        session_id=session_id,
        path=str(session_source),
        filename=session_source.name,
    )
    payload = _payload(description="Stream-capped source still reports")
    payload["context"]["active_session_ids"]["converter"] = session_id
    payload["context"]["active_original_image_ref"] = {
        "session_id": session_id,
        "filename": "oversized.png",
        "source": "converter",
    }

    response = client.post(
        "/api/feedback/bug-report",
        files={
            "request_payload": (None, json.dumps(payload), "application/json"),
            "original_image": (
                "oversized.png",
                b"0123456789ABCDEF",
                "image/png",
            ),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["original_image_status"] == "attached"
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["description"] == "Stream-capped source still reports"
    original = ticket_json["attachments"]["original_image"]
    assert original["status"] == "attached"
    assert original["capture_source"] == "browser_upload"
    assert original["direct_upload_status"] == "attached"
    ticket_dir = next(feedback_root.glob(f"*/{data['ticket_id']}"))
    assert (ticket_dir / "original.png").read_bytes() == b"0123456789ABCDEF"


def test_submit_bug_report_keeps_non_image_original_source(
    client: TestClient,
    feedback_root: Path,
) -> None:
    payload = _payload(description="Unsupported source still reports")
    payload["context"]["active_session_ids"]["converter"] = None
    payload["context"]["active_original_image_ref"] = {
        "session_id": None,
        "filename": "source.txt",
        "source": "converter",
    }

    response = client.post(
        "/api/feedback/bug-report",
        files={
            "request_payload": (None, json.dumps(payload), "application/json"),
            "original_image": ("source.txt", b"not-an-image", "text/plain"),
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["original_image_status"] == "attached"
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    original = ticket_json["attachments"]["original_image"]
    assert original["status"] == "attached"
    assert original["direct_upload_status"] == "attached"
    ticket_dir = next(feedback_root.glob(f"*/{data['ticket_id']}"))
    assert (ticket_dir / "original.txt").read_bytes() == b"not-an-image"


def test_feedback_description_preserves_diagnostics_and_api_context() -> None:
    from api.routers.feedback import BugReportRequest
    descriptions = ["中文描述：切换到 8 色时 3D 预览异常", DESCRIPTION_RAW_DIAGNOSTICS,
                    "AxiosError: Request failed with status code 500 at /api/files/output-model?token=secret#debug"]
    for description in descriptions:
        assert BugReportRequest.model_validate(_payload(description=description)).description == description



def test_submit_bug_report_preserves_description_for_export(
    client: TestClient,
    feedback_root: Path,
) -> None:
    response = client.post(
        "/api/feedback/bug-report",
        json=_payload(description=DESCRIPTION_RAW_DIAGNOSTICS),
    )

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    ticket_dir = next(feedback_root.glob(f"*/{data['ticket_id']}"))
    exported_text = "\n".join(
        [
            json.dumps(ticket_json, ensure_ascii=False),
            (ticket_dir / "index.md").read_text(encoding="utf-8"),
            (ticket_dir / "summary.txt").read_text(encoding="utf-8"),
        ]
    )
    _assert_description_diagnostics_complete(exported_text)


def _enable_fake_feedback_server(
    monkeypatch: pytest.MonkeyPatch,
    receipts: list[Any],
    *,
    fail: bool = False,
) -> None:
    """Route uploads to an in-memory fake instead of the network."""
    import api.feedback_hosted as feedback_hosted

    async def _submit(bundle: Any, *, base_url: str, transport: Any = None) -> dict[str, Any]:
        receipts.append({"bundle": bundle, "base_url": base_url})
        if fail:
            raise feedback_hosted.HostedSubmissionError(
                "ServerUnavailable", "down", http_status=503
            )
        return {"ticket_id": bundle.ticket_id, "status": "received"}

    monkeypatch.setenv("LUMINA_FEEDBACK_SERVER_URL", "https://feedback.example.test/")
    monkeypatch.setattr(feedback_hosted, "submit_ticket_bundle", _submit)


def test_submit_bug_report_uploads_complete_ticket_to_feedback_server(
    client: TestClient,
    feedback_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    receipts: list[Any] = []
    _enable_fake_feedback_server(monkeypatch, receipts)

    private_path = tmp_path / "private-output" / "model.3mf"
    payload = _payload(
        description=DESCRIPTION_RAW_DIAGNOSTICS,
        screenshot_data_url="data:image/png;base64," + ("a" * 1024),
    )
    from core import custom_3mf_templates

    template_settings = {
        "layer_height": "0.16",
        "filament_settings_id": ["Native PLA"],
        "print_host": "fake-private-printer.local",
        "printhost_apikey": "fake-private-api-key",
        "printhost_password": "fake-private-password",
        "printhost_user": "fake-private-user",
        "printhost_cafile": "/fake/private/certificate.pem",
        "host_type": "octoprint",
        "nested": [{"printhost_future_option": "fake-private-option", "wall_loops": "3"}],
    }
    monkeypatch.setattr(custom_3mf_templates, "load_template", lambda _id: template_settings)
    payload["context"]["custom_3mf_template_id"] = "00000000-0000-4000-8000-000000000001"
    private_path.parent.mkdir()
    with zipfile.ZipFile(private_path, "w") as project:
        project.writestr("3D/3dmodel.model", b"GEOMETRY")
        project.writestr("Metadata/project_settings.config", json.dumps(template_settings))
    original_project_bytes = private_path.read_bytes()
    from api.dependencies import get_file_registry

    artifact_id = get_file_registry().register_path(
        session_id="session-abcdef", path=str(private_path), filename="model.3mf",
    )
    payload["context"]["recent_client_logs"] = [
        {
            "timestamp": "2026-05-10T01:02:03.000Z",
            "method": "error",
            "label": "api: request failed",
            "elapsed_ms": 12.346,
            "scope": "api",
            "phase": "request-failed",
            "details": {
                "status_code": 500,
                "api_path": "/api/files/output-model",
                "api_path_transport_error": (
                    "Request failed with status code 500 at /api/files/output-model"
                ),
            },
        }
    ]
    payload["context"]["active_final_artifact_ref"] = {
        "session_id": "session-abcdef",
        "download_url": f"/api/files/{artifact_id}",
        "artifact_type": "3mf",
        "disk_path": private_path.as_posix(),
        "source": "converter",
    }

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    # Upload runs in the background task; the synchronous answer is pending.
    assert data["submission_status"] == "pending"
    assert len(receipts) == 1
    assert receipts[0]["base_url"] == "https://feedback.example.test"
    bundle = receipts[0]["bundle"]
    document = bundle.document
    assert document["schema"] == "lumina-feedback-bundle/1"
    assert document["ticket_id"] == data["ticket_id"]
    # The same ticket.json, index.md and summary.txt the old email carried.
    assert document["index_md"] and document["summary_txt"]
    assert "submission" not in document["ticket"]
    assert {item.name for item in bundle.files} >= {"final.3mf", "screenshot.png", "session-data.zip", "backend-logs.zip"}
    assert {item["kind"] for item in document["attachments"]} == {"final_artifact", "screenshot", "attachment"}

    uploaded_text = json.dumps(document, ensure_ascii=False)
    _assert_description_diagnostics_complete(uploaded_text)
    assert "fake-private-api-key" in uploaded_text
    expected_template_settings = template_settings
    assert document["ticket"]["context"]["custom_3mf_template_snapshot"] == {
        "status": "captured", "settings": expected_template_settings,
    }
    assert template_settings["printhost_apikey"] == "fake-private-api-key"
    final_project = next(item.path for item in bundle.files if item.name == "final.3mf")
    with zipfile.ZipFile(final_project) as project:
        assert project.read("3D/3dmodel.model") == b"GEOMETRY"
        assert json.loads(project.read("Metadata/project_settings.config")) == expected_template_settings
    assert private_path.read_bytes() == original_project_bytes
    assert document["ticket"]["context"]["active_final_artifact_ref"]["disk_path"] == private_path.as_posix()
    assert private_path.as_posix() in uploaded_text
    assert feedback_root.as_posix() not in uploaded_text
    details = document["ticket"]["context"]["recent_client_logs"][0]["details"]
    assert details == payload["context"]["recent_client_logs"][0]["details"]

    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["submission"]["status"] == "submitted"
    assert ticket_json["context"]["custom_3mf_template_snapshot"]["settings"] == expected_template_settings
    assert {"final.3mf", "screenshot.png", "backend-logs.zip", "session-data.zip"} <= set(ticket_json["submission"]["uploaded_attachments"])
    assert "email" not in ticket_json

    status_response = client.get(f"/api/feedback/bug-report/{data['ticket_id']}/status")
    assert status_response.status_code == 200
    assert status_response.json()["submission_status"] == "submitted"


def test_failed_upload_can_be_resubmitted_once_server_recovers(
    client: TestClient,
    feedback_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipts: list[Any] = []
    _enable_fake_feedback_server(monkeypatch, receipts, fail=True)

    data = client.post("/api/feedback/bug-report", json=_payload()).json()
    status_url = f"/api/feedback/bug-report/{data['ticket_id']}/status"
    failed = client.get(status_url).json()
    assert failed["submission_status"] == "failed"
    assert failed["error_type"] == "ServerUnavailable"

    _enable_fake_feedback_server(monkeypatch, receipts)
    resubmitted = client.post(f"/api/feedback/bug-report/{data['ticket_id']}/resubmit")
    assert resubmitted.status_code == 200
    assert resubmitted.json()["submission_status"] == "submitted"
    first, second = receipts[0]["bundle"].document, receipts[1]["bundle"].document
    # Retries send identical content so the server treats them idempotently.
    assert first == second

    again = client.post(f"/api/feedback/bug-report/{data['ticket_id']}/resubmit")
    assert again.json()["submission_status"] == "submitted"
    assert len(receipts) == 2
    assert _read_ticket_json(feedback_root, data["ticket_id"])["submission"]["attempts"] == 2


def test_resubmit_resumes_interrupted_assembly_before_uploading(
    client: TestClient,
    feedback_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipts: list[Any] = []
    _enable_fake_feedback_server(monkeypatch, receipts, fail=True)
    data = client.post("/api/feedback/bug-report", json=_payload()).json()
    ticket_dir = next(feedback_root.glob(f"*/{data['ticket_id']}"))
    # Simulate a restart before index/summary were rendered: startup cleanup
    # marks the ticket interrupted and the upload failed.
    ticket = json.loads((ticket_dir / "ticket.json").read_text(encoding="utf-8"))
    ticket["assembly_status"] = "interrupted"
    ticket["submission"] = {"status": "failed", "error_type": "UploadInterrupted"}
    (ticket_dir / "ticket.json").write_text(json.dumps(ticket), encoding="utf-8")
    (ticket_dir / "index.md").unlink()
    (ticket_dir / "summary.txt").unlink()

    _enable_fake_feedback_server(monkeypatch, receipts)
    response = client.post(f"/api/feedback/bug-report/{data['ticket_id']}/resubmit")

    assert response.status_code == 200
    body = response.json()
    assert body["submission_status"] == "submitted"
    assert body["assembly_status"] in ("done", "partial_failed")
    uploaded = receipts[-1]["bundle"].document
    assert uploaded["index_md"] and uploaded["summary_txt"]
    assert uploaded["ticket"]["assembly_status"] in ("done", "partial_failed")
    assert (ticket_dir / "index.md").exists()


def test_large_attachment_is_uploaded_and_reported(
    client: TestClient,
    feedback_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import api.feedback_hosted as feedback_hosted

    receipts: list[Any] = []
    _enable_fake_feedback_server(monkeypatch, receipts)
    monkeypatch.setattr(feedback_hosted, "MAX_UPLOAD_ATTACHMENT_BYTES", 16, raising=False)
    payload = _payload(screenshot_data_url="data:image/png;base64," + ("a" * 1024))

    data = client.post("/api/feedback/bug-report", json=payload).json()
    status_body = client.get(f"/api/feedback/bug-report/{data['ticket_id']}/status").json()

    assert status_body["submission_status"] == "submitted"
    assert status_body["held_back_attachments"] == []
    assert "screenshot.png" in status_body["uploaded_attachments"]


def test_bug_report_status_rejects_unknown_or_malformed_ticket(client: TestClient) -> None:
    assert client.get("/api/feedback/bug-report/LUM-202609-00000000/status").status_code == 404
    assert client.get("/api/feedback/bug-report/..%2F..%2Fsecret/status").status_code == 404
    assert client.post("/api/feedback/bug-report/LUM-2026-bad/resubmit").status_code == 404


def test_resubmit_is_unavailable_when_uploads_are_disabled(client: TestClient) -> None:
    data = client.post("/api/feedback/bug-report", json=_payload()).json()
    assert data["submission_status"] == "disabled"
    response = client.post(f"/api/feedback/bug-report/{data['ticket_id']}/resubmit")
    assert response.status_code == 503


def test_bug_report_status_rejects_untrusted_origin(client: TestClient) -> None:
    data = client.post("/api/feedback/bug-report", json=_payload()).json()
    response = client.get(
        f"/api/feedback/bug-report/{data['ticket_id']}/status",
        headers=UNTRUSTED_ORIGIN_HEADERS,
    )
    assert response.status_code == 403


def test_submit_bug_report_assembly_marks_done_after_background_task(
    client: TestClient,
    feedback_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """TestClient runs BackgroundTasks synchronously after the response body.

    Starlette TestClient 会在响应返回后同步执行 BackgroundTasks，
    因此 ``ticket.json`` 应已被装配器标记为 ``done`` 或 ``partial_failed``。
    """
    response = client.post("/api/feedback/bug-report", json=_payload(description="Assembly"))

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["assembly_status"] in ("done", "partial_failed")
    # Index + summary should have been rendered by finalize_ticket_async.
    month_dir = next(
        p for p in feedback_root.iterdir() if p.is_dir() and p.name.startswith("20")
    )
    ticket_dir = month_dir / data["ticket_id"]
    assert (ticket_dir / "index.md").exists()
    assert (ticket_dir / "summary.txt").exists()


def test_submit_bug_report_marks_partial_when_declared_attachments_missing(
    client: TestClient,
    feedback_root: Path,
) -> None:
    payload = _payload(description="Missing repro attachments")
    payload["context"]["active_session_ids"] = {
        "converter": "missing-repro-session",
        "single_stage": None,
    }
    payload["context"]["active_original_image_ref"] = {
        "session_id": "missing-repro-session",
        "filename": "source.png",
        "source": "converter",
    }
    payload["context"]["active_final_artifact_ref"] = {
        "session_id": "missing-repro-session",
        "download_url": "/api/files/missing-final-id",
        "artifact_type": "3mf",
        "disk_path": None,
        "source": "converter",
    }

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["attachments"]["original_image"]["status"] == (
        "unavailable_after_cleanup"
    )
    assert ticket_json["attachments"]["final_artifact"]["status"] == "expired_ttl"
    assert ticket_json["assembly_status"] == "partial_failed"


def test_submit_bug_report_marks_failed_when_attachment_copy_fails(
    client: TestClient,
    feedback_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil

    from api.dependencies import get_file_registry

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_image = source_dir / "source.png"
    source_image.write_bytes(b"PNGDATA")
    source_model = source_dir / "model.3mf"
    source_model.write_bytes(b"3MFDATA")
    session_id = "copy-fails-session"
    registry = get_file_registry()
    registry.register_path(
        session_id=session_id,
        path=str(source_image),
        filename="source.png",
    )
    registry.register_path(
        session_id=session_id,
        path=str(source_model),
        filename="model.3mf",
    )

    original_copy2 = shutil.copy2

    def _fail_ticket_copy(src: object, dst: object, *args: object, **kwargs: object) -> object:
        if Path(dst).name in {"original.png", "final.3mf"}:
            raise OSError("disk full")
        return original_copy2(src, dst, *args, **kwargs)

    monkeypatch.setattr("api.feedback_assembler.shutil.copy2", _fail_ticket_copy)

    payload = _payload(description="Copy fails during attachment collection")
    payload["context"]["active_session_ids"] = {
        "converter": session_id,
        "single_stage": None,
    }
    payload["context"]["active_original_image_ref"] = {
        "session_id": session_id,
        "filename": "source.png",
        "source": "converter",
    }
    payload["context"]["active_final_artifact_ref"] = {
        "session_id": session_id,
        "download_url": None,
        "artifact_type": "3mf",
        "disk_path": None,
        "source": "converter",
    }

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    original = ticket_json["attachments"]["original_image"]
    final = ticket_json["attachments"]["final_artifact"]
    assert original["status"] == "failed"
    assert original["error_type"] == "OSError"
    assert original["error_message"] == "Original image could not be saved."
    assert final["status"] == "failed"
    assert final["error_type"] == "OSError"
    assert final["error_message"] == "Final artifact could not be saved."
    assert ticket_json["assembly_status"] == "partial_failed"


def test_submit_bug_report_preserves_material_source_context(
    client: TestClient,
    feedback_root: Path,
) -> None:
    payload = _payload()
    payload["context"] = {
        **payload["context"],
        "color_mode": None,
        "lut_name": None,
        "source_version": "material",
        "selected_material_dir_names": ["Aliz/red", "Wujing/white"],
        "material_layer_count": 10,
        "material_layer_height_mm": 0.06,
        "material_backing_material_dir_name": "Wujing/white",
    }

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["context"]["source_version"] == "material"
    assert ticket_json["context"]["lut_name"] is None
    assert ticket_json["context"]["selected_material_dir_names"] == ["Aliz/red", "Wujing/white"]
    assert ticket_json["context"]["material_layer_count"] == 10
    assert ticket_json["context"]["material_layer_height_mm"] == 0.06
    assert ticket_json["context"]["material_backing_material_dir_name"] == "Wujing/white"
    assert ticket_json["server"]["schema_version"] == 3


def test_submit_bug_report_preserves_complete_workshop_context(
    client: TestClient,
    feedback_root: Path,
) -> None:
    payload = _payload()
    payload["context"]["active_tab"] = "workshop"
    payload["context"]["workshop"] = {
        "module_id": "lumina.bead-pattern",
        "module_version": "1.0.0",
        "install_source": "seed",
        "audit_status": "official",
        "runtime_mode": "desktop-secure",
        "error_code": None,
        "project_schema_version": "bead-project/v1",
        "input_mode": "numbered-grid",
        "rows": 52,
        "columns": 52,
        "compression": 50,
        "palette": [{"name": "private-red", "hex": "#ff0000"}],
        "cellsRle": [[2704, 1]],
        "sourcePath": "/Users/min/private-pattern.png",
        "imageBytes": "private-image-bytes",
        "packagePath": "/Users/min/private-module.lumina-workshop",
        "githubToken": "ghp_private-token",
        "registrySignature": "private-registry-signature",
        "desktopToken": "private-desktop-token",
    }

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    ticket_json = _read_ticket_json(
        feedback_root,
        response.json()["ticket_id"],
    )
    assert ticket_json["context"]["workshop"] == payload["context"]["workshop"]


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("module_id", []),
        ("module_version", None),
        ("install_source", "remote"),
        ("audit_status", "trusted"),
        ("runtime_mode", "browser"),
        ("error_code", {}),
    ],
)
def test_submit_bug_report_rejects_out_of_bounds_workshop_diagnostics(
    client: TestClient,
    feedback_root: Path,
    field_name: str,
    bad_value: object,
) -> None:
    payload = _payload()
    payload["context"]["workshop"] = {
        "module_id": "lumina.bead-pattern",
        "module_version": "1.0.0",
        "install_source": "seed",
        "audit_status": "official",
        "runtime_mode": "desktop-secure",
        "error_code": None,
        field_name: bad_value,
    }

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 422
    assert list(feedback_root.rglob("ticket.json")) == []


def test_submit_bug_report_accepts_older_client_without_workshop_context(
    client: TestClient,
    feedback_root: Path,
) -> None:
    payload = _payload()
    payload["context"].pop("workshop", None)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    ticket_json = _read_ticket_json(
        feedback_root,
        response.json()["ticket_id"],
    )
    assert ticket_json["context"]["workshop"] is None


def test_submit_bug_report_preserves_recent_client_logs(
    client: TestClient,
    feedback_root: Path,
) -> None:
    payload = _payload()
    payload["context"]["recent_client_logs"] = [
        {
            "label": f"event-{index}",
            "elapsed_ms": index + 0.12345,
            "details": {
                "long": "x" * 1300,
                **{f"k{item}": item for item in range(30)},
            },
        }
        for index in range(55)
    ]

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    logs = ticket_json["context"]["recent_client_logs"]
    assert logs == payload["context"]["recent_client_logs"]


def test_submit_bug_report_preserves_context_diagnostic_strings(
    client: TestClient,
    feedback_root: Path,
) -> None:
    payload = _payload()
    payload["context"]["recent_client_logs"] = [
        {
            "timestamp": "file:///Users/min/private/log.txt",
            "method": "error",
            "label": "Request failed with status code 500",
            "elapsed_ms": 12.3456,
            "scope": r"\\LUMINA-NAS\private\trace.log",
            "phase": "HTTP 500",
            "details": {
                "posix_path": "failed at /Users/min/private/model.3mf",
                "private_tmp": "open /private/tmp/lumina/model.png",
                "windows_path": r"C:\Users\min\secret\model.3mf",
                "windows_forward_path": "C:/Users/min/secret/model.3mf",
                "unc_path": r"\\LUMINA-NAS\share\secret.3mf",
                "file_url": "file:///Users/min/private/model.3mf",
                "windows_file_url": "file:///C:/Users/min/private/model.3mf",
                "generic_http_error": "Request failed with status code 500",
                "api_path_transport_error": (
                    "Request failed with status code 500 at /api/files/output-model"
                ),
                "business_detail": "Color palette has no hex entries.",
                "api_path": "/api/files/output-model",
            },
        }
    ]
    payload["context"]["action_history"] = [
        {
            "timestamp": 1760000000000,
            "action_type": "api_error",
            "snapshot": {
                "active_tab": "converter",
                "advanced_params": {
                    "relief": {
                        "source": "file:///Users/min/private/source.png",
                        "color_height_map": {"#ffffff": 0.24},
                    },
                },
            },
            "error": {
                "status_code": 500,
                "path": "/api/files/output-model",
                "error_message": "HTTP 404: /api/files/output-model",
                "local_path_error_message": (
                    r"Request failed with status code 500 at C:\Users\min\secret.3mf"
                ),
                "stack": "Traceback at /home/min/lumina/app.py",
            },
        }
    ]
    payload["context"]["advanced_params"] = {
        "relief": {
            "source": "file:///Users/min/private/source.png",
            "color_height_map": {"#ffffff": 0.24},
        }
    }

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    context_text = json.dumps(ticket_json["context"], ensure_ascii=False)
    for key in ("recent_client_logs", "action_history", "session_history"):
        assert ticket_json["context"][key] == payload["context"][key]


@pytest.mark.parametrize(
    "patch",
    [
        {"description": ""},
        {"user_email": "not-an-email"},
    ],
)
def test_submit_bug_report_rejects_invalid_payloads(
    client: TestClient,
    patch: dict[str, object],
    caplog: pytest.LogCaptureFixture,
) -> None:
    response = client.post("/api/feedback/bug-report", json=_payload(**patch))

    assert response.status_code == 422
    assert [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_bug_report_submitted"
    ] == []


def test_legacy_json_validation_keeps_fastapi_body_location(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/feedback/bug-report",
        json=_payload(description=""),
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "description"]


def test_invalid_multipart_closes_original_upload(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closed_filenames: list[str | None] = []
    real_close = UploadFile.close

    async def track_close(upload: UploadFile) -> None:
        closed_filenames.append(upload.filename)
        await real_close(upload)

    monkeypatch.setattr(UploadFile, "close", track_close)
    response = client.post(
        "/api/feedback/bug-report",
        files={
            "request_payload": (
                None,
                json.dumps(_payload(description="")),
                "application/json",
            ),
            "original_image": ("source.png", b"SOURCE", "image/png"),
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "description"]
    assert closed_filenames == ["source.png"]


def test_submit_bug_report_rejects_invalid_large_screenshot_base64(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _capture_feedback_logger(caplog, logging.WARNING)
    payload = _payload(screenshot_data_url="data:image/png;base64," + ("a" * 7_000_001))

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 400
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_screenshot_invalid"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "InvalidBase64"


def test_submit_bug_report_accepts_repeated_local_submissions(
    client: TestClient,
    feedback_root: Path,
) -> None:
    """Each local report remains independently saved after repeated submits."""
    responses = [
        client.post("/api/feedback/bug-report", json=_payload(description=f"Report {index}"))
        for index in range(31)
    ]
    assert all(response.status_code == 200 for response in responses)
    ticket_ids = [response.json()["ticket_id"] for response in responses]
    assert len(set(ticket_ids)) == 31
    assert [
        _read_ticket_json(feedback_root, ticket_id)["description"]
        for ticket_id in ticket_ids
    ] == [f"Report {index}" for index in range(31)]


def test_submit_bug_report_returns_500_when_ticket_dir_creation_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the ticket id generator cannot create its reserved dir the handler 500s.

    工单目录保留失败时，handler 应返回 500 而不是抛原始异常。
    """

    def _raise(*_args: Any, **_kwargs: Any) -> str:
        raise OSError("disk full")

    monkeypatch.setattr("api.routers.feedback.generate_ticket_id", _raise)
    _capture_feedback_logger(caplog, logging.ERROR)

    response = client.post("/api/feedback/bug-report", json=_payload())

    assert response.status_code == 500
    failures = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_dump_failed"
    ]
    assert len(failures) == 1
    assert failures[0].error_type == "OSError"


def test_submit_bug_report_accepts_valid_png_screenshot(
    client: TestClient,
    feedback_root: Path,
) -> None:
    """A valid PNG data URL is accepted and saved as screenshot.png."""
    import base64

    valid_png_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode()
    payload = _payload(screenshot_data_url=f"data:image/png;base64,{valid_png_b64}")

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["attachments"]["screenshot"]["status"] == "attached"
    assert ticket_json["attachments"]["screenshot"]["filename"] == "screenshot.png"


def test_submit_bug_report_marks_screenshot_failed_when_write_fails(
    client: TestClient,
    feedback_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed screenshot write is explicit in ``ticket.json``.

    截图写入失败时，``ticket.json`` 必须显式标记失败，不能伪装成不适用。
    """
    import base64

    original_write_bytes = Path.write_bytes

    def _fail_screenshot_write(self: Path, data: bytes) -> int:
        if self.name.startswith("screenshot"):
            raise OSError("disk full while writing screenshot")
        return original_write_bytes(self, data)

    monkeypatch.setattr(Path, "write_bytes", _fail_screenshot_write)
    _capture_feedback_logger(caplog, logging.WARNING)

    valid_png_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode()
    payload = _payload(screenshot_data_url=f"data:image/png;base64,{valid_png_b64}")

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    screenshot = ticket_json["attachments"]["screenshot"]
    assert screenshot == {
        "status": "failed",
        "filename": "screenshot.png",
        "size_bytes": None,
        "error_type": "OSError",
        "error_message": "Screenshot could not be saved.",
    }
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_attachment_lookup_failed"
    ]
    assert warnings
    assert warnings[0].attachment_kind == "screenshot"
    assert warnings[0].error_type == "OSError"


def test_submit_bug_report_rejects_non_image_mime_screenshot(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """data:text/plain;base64,... returns 400."""
    import base64

    b64 = base64.b64encode(b"hello world").decode()
    payload = _payload(screenshot_data_url=f"data:text/plain;base64,{b64}")
    _capture_feedback_logger(caplog, logging.WARNING)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 400
    assert "Invalid screenshot data URL" in response.json()["detail"]
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_screenshot_invalid"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "UnsupportedMimeType"


def test_submit_bug_report_rejects_missing_base64_marker(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """data:image/png,not-base64 (no ;base64) returns 400."""
    payload = _payload(screenshot_data_url="data:image/png,not-base64-content")
    _capture_feedback_logger(caplog, logging.WARNING)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 400
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_screenshot_invalid"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "InvalidDataUrlFormat"


def test_submit_bug_report_rejects_invalid_base64_payload(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """data:image/png;base64,%%% returns 400."""
    payload = _payload(screenshot_data_url="data:image/png;base64,%%%")
    _capture_feedback_logger(caplog, logging.WARNING)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 400
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_screenshot_invalid"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "InvalidBase64"


def test_submit_bug_report_rejects_svg_screenshot(
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """data:image/svg+xml;base64,... returns 400 (SVG not in allowed list)."""
    import base64

    b64 = base64.b64encode(b"<svg></svg>").decode()
    payload = _payload(screenshot_data_url=f"data:image/svg+xml;base64,{b64}")
    _capture_feedback_logger(caplog, logging.WARNING)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 400
    warnings = [
        record for record in caplog.records
        if getattr(record, "event", None) == "feedback_screenshot_invalid"
    ]
    assert len(warnings) == 1
    assert warnings[0].error_type == "UnsupportedMimeType"
    assert warnings[0].mime_type == "image/svg+xml"


# ---------------------------------------------------------------------------
# Task 6.7: advanced_params schema / sanitizer integration tests
# ---------------------------------------------------------------------------


def _full_advanced_params() -> dict[str, Any]:
    """Return a fully-populated grouped ``advanced_params`` payload.

    构造覆盖全部 11 个分组的 ``advanced_params`` 测试载荷。
    """
    return {
        "dimensions": {
            "target_width_mm": 120,
            "target_height_mm": 80,
            "spacer_thick": 0.06,
            "base_spacer_thick": 0.12,
        },
        "generation": {
            "structure_mode": "standard",
            "modeling_mode": "flat",
            "color_layers": 4,
            "layer_height_mm": 0.08,
            "model_enable": False,
            "model_only": False,
            "model_threshold": None,
            "model_margin": None,
            "quantize_colors": 8,
            "quantize_colors_unlocked": False,
            "enable_cleanup": True,
            "hue_enable": True,
            "chroma_gate": 0.5,
            "use_lut_constrained": False,
            "auto_dynamic_range": True,
            "separate_backing": False,
        },
        "relief": {
            "enable_relief": True,
            "color_height_map": {"#ff0000": 0.1, "#00ff00": 0.2},
            "heightmap_max_height": 0.6,
            "autoHeightMode": "linear",
            "heightmapFile": None,
            "hasHeightmapThumbnail": False,
        },
        "outline": {"enable_outline": True, "outline_width": 0.2},
        "cloisonne": {
            "enable_cloisonne": False,
            "wire_width_mm": None,
            "wire_height_mm": None,
        },
        "coating": {"enable_coating": False, "coating_height_mm": None},
        "loop": {
            "add_loop": False,
            "loop_width": None,
            "loop_length": None,
            "loop_hole": None,
            "loop_angle": None,
            "loop_offset_x": None,
            "loop_offset_y": None,
            "loop_position_preset": None,
        },
        "fridge_magnet": {
            "enable_fridge_magnet": False,
            "selectedFridgeMagnetId": None,
            "fridge_magnets": None,
        },
        "puzzle": {
            "puzzleEnabled": False,
            "puzzleStyle": None,
            "puzzleSizingMode": None,
            "pieceWidthMm": None,
            "pieceHeightMm": None,
            "puzzleRows": None,
            "puzzleCols": None,
            "targetPieceCount": None,
            "connectorStyle": None,
            "labelsEnabled": None,
            "engraveBackLabels": None,
            "irregularityStrength": None,
            "minNeckWidthMm": None,
        },
        "large_format": {
            "largeFormatEnabled": False,
            "tileWidthMm": None,
            "tileHeightMm": None,
        },
        "color_replacement": {"replacement_regions": None},
    }


def test_submit_bug_report_accepts_grouped_advanced_params(
    client: TestClient,
    feedback_root: Path,
) -> None:
    """Pydantic accepts ``advanced_params`` as a grouped 11-key dict and the
    router persists it into ``ticket.json``.

    Pydantic 接收包含全部 11 个分组的 ``advanced_params``，路由把它写入
    ``ticket.json``。
    """
    payload = _payload()
    payload["context"]["advanced_params"] = _full_advanced_params()

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    advanced = ticket_json["context"]["advanced_params"]
    assert isinstance(advanced, dict)
    # All 11 group keys are preserved end-to-end (size is far below 16 KB).
    expected_groups = {
        "dimensions",
        "generation",
        "relief",
        "outline",
        "cloisonne",
        "coating",
        "loop",
        "fridge_magnet",
        "puzzle",
        "large_format",
        "color_replacement",
    }
    assert expected_groups.issubset(advanced.keys())
    assert advanced["dimensions"]["target_width_mm"] == 120
    assert advanced["relief"]["color_height_map"] == {
        "#ff0000": 0.1,
        "#00ff00": 0.2,
    }


def test_submit_bug_report_accepts_null_advanced_params(
    client: TestClient,
    feedback_root: Path,
) -> None:
    """``advanced_params: None`` round-trips untouched.

    显式传 ``None`` 时原样写回 ``ticket.json``。
    """
    payload = _payload()
    payload["context"]["advanced_params"] = None

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["context"]["advanced_params"] is None


def test_submit_bug_report_accepts_missing_advanced_params(
    client: TestClient,
    feedback_root: Path,
) -> None:
    """Old clients that omit the field still succeed; default is ``None``.

    老客户端不传 ``advanced_params`` 时仍然成功，默认值为 ``None``。
    """
    payload = _payload()
    payload["context"].pop("advanced_params", None)

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    assert ticket_json["context"]["advanced_params"] is None


@pytest.mark.parametrize(
    "bad_value",
    [
        [],
        ["not", "a", "dict"],
        "string-advanced-params",
        123,
    ],
    ids=["empty-list", "list", "string", "number"],
)
def test_submit_bug_report_rejects_non_dict_advanced_params(
    client: TestClient,
    bad_value: Any,
) -> None:
    """Non-dict ``advanced_params`` values are rejected at validation time.

    ``advanced_params`` 不是 dict/None 时，Pydantic 返回 422。
    """
    payload = _payload()
    payload["context"]["advanced_params"] = bad_value

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 422





def test_submit_bug_report_preserves_large_advanced_params(
    client: TestClient,
    feedback_root: Path,
) -> None:
    """When the sanitized ``advanced_params`` exceeds 16 KB, ticket.json stores
    exactly ``{"_size_trimmed": True, "_original_byte_length": N}`` — never a
    third shape.

    sanitized ``advanced_params`` 超过 16 KB 上限时，``ticket.json`` 里
    的 advanced_params 固定为 ``{"_size_trimmed": True,
    "_original_byte_length": N}``，不会出现第三种形态。
    """
    # 15 × 1200-char strings sit under the 1200-char per-string cap but
    # together serialize to ~18 KB, guaranteed to cross the 16 KB total cap.
    # 每个字符串恰好不触发 _truncate_feedback_text，但总体积会超过 16 KB。
    payload_advanced: dict[str, Any] = _full_advanced_params()
    payload_advanced["generation"] = {
        f"field_{i:02d}": "x" * 1200 for i in range(15)
    }

    payload = _payload()
    payload["context"]["advanced_params"] = payload_advanced

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    advanced = ticket_json["context"]["advanced_params"]

    assert advanced == payload_advanced


def test_submit_bug_report_preserves_action_history_advanced_params(
    client: TestClient,
    feedback_root: Path,
) -> None:
    """``action_history`` snapshots keep their full ``advanced_params`` (e.g.
    a 64-key ``relief.color_height_map``) through the generic + dedicated
    sanitization pipeline.

    ``action_history`` 中的 snapshot 经过通用 + 专用 sanitizer 后，嵌套的
    ``advanced_params``（例如 64 键的 ``relief.color_height_map``）被完整
    保留。
    """
    snapshot_advanced = _full_advanced_params()
    snapshot_advanced["relief"] = {
        "enable_relief": True,
        "color_height_map": {f"#{i:06x}": float(i) * 0.01 for i in range(64)},
        "heightmap_max_height": 0.5,
        "autoHeightMode": "linear",
        "heightmapFile": None,
        "hasHeightmapThumbnail": False,
    }

    payload = _payload()
    payload["context"]["action_history"] = [
        {
            "timestamp": 1747000000000,
            "action_type": "advanced_param_change",
            "changed_fields": {
                "enable_relief": {"from": False, "to": True}
            },
            "snapshot": {
                "active_tab": "converter",
                "source_version": "legacy",
                "advanced_params": snapshot_advanced,
            },
        }
    ]

    response = client.post("/api/feedback/bug-report", json=payload)

    assert response.status_code == 200
    data = response.json()
    ticket_json = _read_ticket_json(feedback_root, data["ticket_id"])
    history = ticket_json["context"]["action_history"]
    assert len(history) == 1

    entry_snapshot = history[0]["snapshot"]
    assert isinstance(entry_snapshot, dict)
    assert "advanced_params" in entry_snapshot
    advanced = entry_snapshot["advanced_params"]
    assert isinstance(advanced, dict)
    color_map = advanced["relief"]["color_height_map"]
    assert isinstance(color_map, dict)
    # All 64 entries survive — the generic sanitizer would have cut to 24.
    assert len(color_map) == 64
    assert "__truncated_keys" not in color_map


def test_assembler_entry_points_remain_untouched() -> None:
    """Non-regression: ``collect_sync_attachments`` and ``finalize_ticket_async``
    are imported into the router with their original signatures — nothing
    wraps them at import time.

    非回归校验：``collect_sync_attachments`` 和 ``finalize_ticket_async``
    被路由原样引用，没有被装饰 / 重命名 / 改签名。
    """
    import inspect

    import api.feedback_assembler as feedback_assembler
    import api.routers.feedback as feedback_router

    # Same function object imported in the router as exported by the module.
    assert (
        feedback_router.collect_sync_attachments
        is feedback_assembler.collect_sync_attachments
    )
    assert (
        feedback_router.finalize_ticket_async
        is feedback_assembler.finalize_ticket_async
    )

    sync_params = list(
        inspect.signature(feedback_assembler.collect_sync_attachments).parameters
    )
    assert sync_params == [
        "ticket_dir",
        "payload",
        "file_registry",
        "now",
        "session_store",
    ]

    async_params = list(
        inspect.signature(feedback_assembler.finalize_ticket_async).parameters
    )
    assert async_params == ["ticket_dir", "file_registry", "session_store"]
    assert inspect.iscoroutinefunction(feedback_assembler.finalize_ticket_async)
