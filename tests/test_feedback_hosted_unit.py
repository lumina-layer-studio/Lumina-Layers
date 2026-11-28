"""Unit tests for uploading bug-report tickets to the official feedback server.

官方反馈服务上传客户端的单元测试：工作量证明、附件筛选、重试与降级。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from email.parser import BytesParser
from email.policy import HTTP
from pathlib import Path
from typing import Any

import httpx
import pytest

import api.feedback_hosted as feedback_hosted

TICKET = "LUM-202609-0a1b2c3d"
PNG = b"\x89PNG\r\n\x1a\n" + b"pixels"


def _ticket_dir(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    ticket_dir = tmp_path / "2026-09" / TICKET
    ticket_dir.mkdir(parents=True)
    payload = {
        "ticket_id": TICKET,
        "description": "Crash",
        "user_email": None,
        "context": {"app_version": "1"},
        "assembly_status": "done",
        "submission": {"status": "pending", "attempts": 0},
    }
    (ticket_dir / "ticket.json").write_text(json.dumps(payload), encoding="utf-8")
    (ticket_dir / "index.md").write_text("# index", encoding="utf-8")
    (ticket_dir / "summary.txt").write_text("摘要", encoding="utf-8")
    (ticket_dir / "original.png").write_bytes(PNG)
    (ticket_dir / "final.glb").write_bytes(b"glTF")
    (ticket_dir / "lut_1.npy").write_bytes(b"\x93NUMPY")
    return ticket_dir, payload


def _parse_multipart(request: httpx.Request) -> dict[str, list[tuple[str | None, bytes]]]:
    raw = b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n" + request.read()
    message = BytesParser(policy=HTTP).parsebytes(raw)
    parts: dict[str, list[tuple[str | None, bytes]]] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        parts.setdefault(name, []).append((part.get_filename(), part.get_payload(decode=True)))
    return parts


class FakeServer:
    """Minimal stand-in for the Distribution intake contract."""

    def __init__(self, *, bits: int = 4, bundle_statuses: list[int] | None = None) -> None:
        self.bits = bits
        self.bundle_statuses = list(bundle_statuses or [])
        self.bundles: list[dict[str, Any]] = []
        self.challenges = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/feedback/challenges":
            self.challenges += 1
            return httpx.Response(200, json={
                "challenge": f"c{self.challenges}.sig", "difficulty_bits": self.bits,
                "expires_in": 600, "algorithm": "sha256-leading-zero-bits",
            })
        assert request.url.path == "/v2/feedback/bundles"
        assert "content-length" in request.headers
        digest = hashlib.sha256(
            f"{request.headers['x-lumina-challenge']}:{request.headers['x-lumina-ticket']}:"
            f"{request.headers['x-lumina-proof']}".encode()
        ).digest()
        assert feedback_hosted._leading_zero_bits(digest) >= self.bits
        parts = _parse_multipart(request)
        self.bundles.append({
            "report": json.loads(parts["report"][0][1]),
            "files": {name: data for name, data in parts.get("attachment", [])},
        })
        status = self.bundle_statuses.pop(0) if self.bundle_statuses else 200
        return httpx.Response(status, json={"ticket_id": TICKET, "status": "received"})


def _submit(ticket_dir: Path, payload: dict[str, Any], server: FakeServer,
            monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("LUMINA_FEEDBACK_SERVER_URL", "https://feedback.example.test")
    monkeypatch.setattr(feedback_hosted, "_RETRY_DELAY_S", 0)
    return asyncio.run(feedback_hosted.submit_ticket_directory(
        ticket_dir, payload, transport=httpx.MockTransport(server)))


def test_server_url_defaults_to_official_service_and_can_be_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUMINA_FEEDBACK_SERVER_URL", raising=False)
    assert feedback_hosted.feedback_server_url() == feedback_hosted.DEFAULT_FEEDBACK_SERVER_URL
    monkeypatch.setenv("LUMINA_FEEDBACK_SERVER_URL", "http://127.0.0.1:8766/")
    assert feedback_hosted.feedback_server_url() == "http://127.0.0.1:8766"
    monkeypatch.setenv("LUMINA_FEEDBACK_SERVER_URL", "off")
    assert feedback_hosted.feedback_server_url() is None


def test_proof_of_work_meets_requested_difficulty() -> None:
    nonce = feedback_hosted.solve_proof_of_work("challenge", TICKET, 10)
    digest = hashlib.sha256(f"challenge:{TICKET}:{nonce}".encode()).digest()
    assert feedback_hosted._leading_zero_bits(digest) >= 10
    with pytest.raises(feedback_hosted.HostedSubmissionError):
        feedback_hosted.solve_proof_of_work("challenge", TICKET, 40)


def test_bundle_preserves_every_file(tmp_path: Path) -> None:
    ticket_dir, payload = _ticket_dir(tmp_path)
    bundle = feedback_hosted.build_ticket_bundle(ticket_dir, payload)

    assert [item.name for item in bundle.files] == ["final.glb", "lut_1.npy", "original.png"]
    assert bundle.held_back == []
    assert bundle.document["index_md"] == "# index"
    assert bundle.document["summary_txt"] == "摘要"
    assert "submission" not in bundle.document["ticket"]
    assert bundle.document["attachments"][2] == {
        "name": "original.png", "kind": "original_image", "size_bytes": len(PNG),
        "sha256": hashlib.sha256(PNG).hexdigest(),
    }


def test_submission_uploads_bundle_with_proof(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ticket_dir, payload = _ticket_dir(tmp_path)
    server = FakeServer()

    section = _submit(ticket_dir, payload, server, monkeypatch)

    assert section["status"] == "submitted"
    assert section["attempts"] == 1
    assert section["uploaded_attachments"] == ["final.glb", "lut_1.npy", "original.png"]
    uploaded = server.bundles[0]
    assert uploaded["report"]["ticket_id"] == TICKET
    assert uploaded["files"]["original.png"] == PNG


def test_rejected_proof_is_retried_with_a_new_challenge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ticket_dir, payload = _ticket_dir(tmp_path)
    server = FakeServer(bundle_statuses=[403])

    section = _submit(ticket_dir, payload, server, monkeypatch)

    assert section["status"] == "submitted"
    assert server.challenges == 2


def test_rejected_attachment_reports_failure_without_dropping_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket_dir, payload = _ticket_dir(tmp_path)
    server = FakeServer(bundle_statuses=[422])

    section = _submit(ticket_dir, payload, server, monkeypatch)

    assert section["status"] == "failed"
    assert len(server.bundles) == 1
    assert server.bundles[0]["files"]
    assert section["held_back_attachments"] == []


def test_rate_limit_is_reported_without_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ticket_dir, payload = _ticket_dir(tmp_path)
    server = FakeServer(bundle_statuses=[429])

    section = _submit(ticket_dir, payload, server, monkeypatch)

    assert section["status"] == "failed"
    assert section["error_type"] == "RateLimited"
    assert section["http_status"] == 429
    assert len(server.bundles) == 1


def test_unreachable_server_fails_gracefully(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ticket_dir, payload = _ticket_dir(tmp_path)

    def _refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    section = _submit(ticket_dir, payload, _refuse, monkeypatch)  # type: ignore[arg-type]

    assert section["status"] == "failed"
    assert section["error_type"] == "ConnectError"


def test_disabled_uploads_do_not_touch_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ticket_dir, payload = _ticket_dir(tmp_path)
    monkeypatch.setenv("LUMINA_FEEDBACK_SERVER_URL", "off")

    def _fail(request: httpx.Request) -> httpx.Response:
        raise AssertionError("network must not be used")

    section = asyncio.run(feedback_hosted.submit_ticket_directory(
        ticket_dir, payload, transport=httpx.MockTransport(_fail)))

    assert section["status"] == "disabled"
    assert section["attempts"] == 0


def test_bundle_accepts_all_32_numbered_luts(tmp_path: Path) -> None:
    ticket_dir, payload = _ticket_dir(tmp_path)
    (ticket_dir / "lut_32.json").write_text("{}", encoding="utf-8")

    bundle = feedback_hosted.build_ticket_bundle(ticket_dir, payload)

    assert "lut_32.json" in [item.name for item in bundle.files]


def test_complete_ticket_with_32_luts_uploads_every_attachment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket_dir, payload = _ticket_dir(tmp_path)
    (ticket_dir / "final.glb").unlink()
    (ticket_dir / "final.3mf").write_bytes(b"PK\x03\x04")
    (ticket_dir / "materials.zip").write_bytes(b"PK\x03\x04")
    (ticket_dir / "screenshot.png").write_bytes(PNG)
    for index in range(2, 33):
        (ticket_dir / f"lut_{index}.npy").write_bytes(b"\x93NUMPY")
    server = FakeServer()

    section = _submit(ticket_dir, payload, server, monkeypatch)

    assert section["status"] == "submitted"
    assert section["held_back_attachments"] == []
    assert len(server.bundles[0]["files"]) == 36
    assert len(server.bundles[0]["report"]["attachments"]) == 36


def test_former_request_budget_does_not_filter_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket_dir, payload = _ticket_dir(tmp_path)
    (ticket_dir / "final.3mf").write_bytes(b"PK" + b"0" * 30)
    monkeypatch.setattr(feedback_hosted, "MAX_UPLOAD_BUNDLE_FILE_BYTES", len(PNG) + 6, raising=False)

    bundle = feedback_hosted.build_ticket_bundle(ticket_dir, payload)

    assert [item.name for item in bundle.files] == ["final.3mf", "final.glb", "lut_1.npy", "original.png"]
    assert bundle.held_back == []
    assert "final.3mf" in [item.name for item in bundle.files]


def test_former_attachment_count_limit_does_not_filter_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ticket_dir, payload = _ticket_dir(tmp_path)
    monkeypatch.setattr(feedback_hosted, "MAX_UPLOAD_ATTACHMENTS", 1, raising=False)

    bundle = feedback_hosted.build_ticket_bundle(ticket_dir, payload)

    assert [item.name for item in bundle.files] == ["final.glb", "lut_1.npy", "original.png"]
    assert bundle.held_back == []


def test_rejected_large_request_reports_failure_without_dropping_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket_dir, payload = _ticket_dir(tmp_path)
    server = FakeServer(bundle_statuses=[413])

    section = _submit(ticket_dir, payload, server, monkeypatch)

    assert section["status"] == "failed"
    assert len(server.bundles) == 1
    assert server.bundles[0]["files"]
    assert section["held_back_attachments"] == []


def test_direct_mode_bypasses_dead_local_proxy_env_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket_dir, payload = _ticket_dir(tmp_path)
    server = FakeServer()
    real_client = httpx.AsyncClient
    seen_trust_env: list[bool] = []
    monkeypatch.setenv("LUMINA_FEEDBACK_SERVER_URL", "https://feedback.example.test")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setattr(feedback_hosted, "_RETRY_DELAY_S", 0)

    def _fake_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        trust_env = kwargs.get("trust_env", True)
        seen_trust_env.append(trust_env)
        if trust_env:
            raise AssertionError("dead proxy env should not be used when direct succeeds")
        return real_client(
            timeout=kwargs.get("timeout"),
            transport=httpx.MockTransport(server),
            follow_redirects=False,
            trust_env=False,
        )

    monkeypatch.setattr(feedback_hosted.httpx, "AsyncClient", _fake_async_client)
    section = asyncio.run(feedback_hosted.submit_ticket_directory(ticket_dir, payload))

    assert section["status"] == "submitted"
    assert seen_trust_env == [False]


def test_falls_back_to_proxy_env_when_direct_cannot_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket_dir, payload = _ticket_dir(tmp_path)
    server = FakeServer()
    real_client = httpx.AsyncClient
    seen_trust_env: list[bool] = []
    monkeypatch.setenv("LUMINA_FEEDBACK_SERVER_URL", "https://feedback.example.test")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.corp.example:8080")
    monkeypatch.setattr(feedback_hosted, "_RETRY_DELAY_S", 0)

    def _refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("direct blocked by firewall", request=request)

    def _fake_async_client(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        trust_env = kwargs.get("trust_env", True)
        seen_trust_env.append(trust_env)
        handler = server if trust_env else _refuse
        return real_client(
            timeout=kwargs.get("timeout"),
            transport=httpx.MockTransport(handler),
            follow_redirects=False,
            trust_env=False,
        )

    monkeypatch.setattr(feedback_hosted.httpx, "AsyncClient", _fake_async_client)
    section = asyncio.run(feedback_hosted.submit_ticket_directory(ticket_dir, payload))

    assert section["status"] == "submitted"
    assert seen_trust_env == [False, True]
    assert len(server.bundles) == 1


def test_upload_timeout_408_retries_with_fresh_challenge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticket_dir, payload = _ticket_dir(tmp_path)
    server = FakeServer(bundle_statuses=[408])

    section = _submit(ticket_dir, payload, server, monkeypatch)

    assert section["status"] == "submitted"
    assert server.challenges == 2

