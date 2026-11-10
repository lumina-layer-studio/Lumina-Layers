"""Public HTTP flow for module backends: install, consent, prepare, tasks.

Runs the real runtime (pinned uv, base interpreter, offline wheelhouse) behind
FastAPI. Registry and review sources are local fakes; nothing leaves the host.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import api.workshop_runtime_service as runtime_service
from api.app import _run_cleanup_pass, create_app
from api.routers import workshop as workshop_router
from core.workshop.backend.tooling import locate_uv_executable
from core.workshop.models import RegistryIndex, RegistryRefreshResult
from workshop_backend_fixture import (
    backend_manifest,
    build_fixture_wheelhouse,
    decode_png_rgba,
    encode_png_rgba,
    lock_text,
    write_backend_package,
)

pytestmark = pytest.mark.skipif(
    locate_uv_executable() is None,
    reason="pinned uv from requirements.txt is not installed",
)
MODULE = "fixture.api-backend"


class EmptyRegistry:
    def refresh(self) -> RegistryRefreshResult:
        return RegistryRefreshResult(
            source="snapshot",
            verified=True,
            index=RegistryIndex.model_validate(
                {"schemaVersion": 1, "generatedAt": "2026-11-04T00:00:00Z", "modules": []}
            ),
        )


class NoReviews:
    def refresh(self) -> None:
        return None


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):  # noqa: ANN201
    wheels = build_fixture_wheelhouse(tmp_path / "wheelhouse")
    monkeypatch.setenv("LUMINA_WORKSHOP_DATA_DIR", str(tmp_path / "workshop"))
    monkeypatch.setenv("LUMINA_WORKSHOP_PYTHON", sys._base_executable)
    monkeypatch.setenv("LUMINA_WORKSHOP_WHEELHOUSE", str(tmp_path / "wheelhouse"))
    monkeypatch.setenv("LUMINA_WORKSHOP_OFFLINE", "1")
    monkeypatch.setattr(workshop_router, "get_workshop_registry_client", lambda: EmptyRegistry())
    monkeypatch.setattr(runtime_service, "get_review_attestation_client", lambda _data_dir: NoReviews())
    manifest = backend_manifest(
        MODULE,
        "1.0.0",
        capabilities=[{"name": "subprocess", "reason": "Runs a helper in the slow fixture."}],
    )
    manifest["permissions"].append({"name": "project.storage", "reason": "Save edits."})
    manifest["projectSnapshots"] = {"protocol": 1, "schemas": ["editor/v1"]}
    package = write_backend_package(
        tmp_path / "packages",
        module_id=MODULE,
        version="1.0.0",
        lock=lock_text([wheels["shared"]]),
        manifest=manifest,
    )
    yield TestClient(create_app()), package
    runtime_service.shutdown_backend_runtimes()


def wait_task(client: TestClient, task_id: str, timeout: float = 120.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/workshop/v1/modules/{MODULE}/backend/tasks/{task_id}")
        assert response.status_code == 200, response.text
        task = response.json()
        if task["status"] in {"succeeded", "failed", "cancelled", "interrupted"}:
            return task
        time.sleep(0.05)
    raise AssertionError("task did not finish")


def install_and_prepare(client: TestClient, package: Path) -> None:
    with package.open("rb") as stream:
        response = client.post(
            "/api/workshop/v1/install/local",
            files={"archive": (package.name, stream, "application/octet-stream")},
        )
    assert response.status_code == 200, response.text
    detail = response.json()["module"]["version_details"][0]
    assert detail["manifest_version"] == 2
    assert detail["backend"]["capabilities"][0]["name"] == "subprocess"
    assert detail["project_snapshot_protocol"] == 1
    assert detail["project_snapshot_schemas"] == ["editor/v1"]

    refused = client.post(f"/api/workshop/v1/modules/{MODULE}/activate", json={"version": "1.0.0"})
    assert refused.status_code == 409
    # Backend refusals share one boundary mapping across both routers.
    assert refused.json()["detail"]["code"] == "backend-not-prepared"
    assert refused.json()["detail"]["message"]

    status = client.get(f"/api/workshop/v1/modules/{MODULE}/1.0.0/backend").json()
    assert status["review_level"] == "unreviewed"
    assert status["requires_unreviewed_confirmation"] is True
    assert status["preparation"] == "unprepared"
    assert status["dependencies"]["package_count"] == 1

    blocked = client.post(f"/api/workshop/v1/modules/{MODULE}/1.0.0/backend/prepare")
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "backend-authorization-required"
    unconfirmed = client.post(f"/api/workshop/v1/modules/{MODULE}/1.0.0/backend/authorize", json={})
    assert unconfirmed.status_code == 409
    assert unconfirmed.json()["detail"]["code"] == "unreviewed-confirmation-required"
    granted = client.post(
        f"/api/workshop/v1/modules/{MODULE}/1.0.0/backend/authorize",
        json={"acknowledge_unreviewed": True},
    )
    assert granted.status_code == 200 and granted.json()["authorization"] == "granted"

    task = client.post(f"/api/workshop/v1/modules/{MODULE}/1.0.0/backend/prepare").json()
    assert task["kind"] == "prepare"
    assert wait_task(client, task["task_id"])["status"] == "succeeded"
    activated = client.post(f"/api/workshop/v1/modules/{MODULE}/activate", json={"version": "1.0.0"})
    assert activated.status_code == 200, activated.text


def submit(client: TestClient, operation: str, *, params: dict | None = None,
           files: list[tuple[str, bytes, str, str]] | None = None) -> dict:
    entries = files or []
    response = client.post(
        f"/api/workshop/v1/modules/{MODULE}/backend/tasks",
        data={
            "version": "1.0.0",
            "operation": operation,
            "params": json.dumps(params or {}),
            "inputs_meta": json.dumps(
                [{"name": name, "fileName": file_name, "mimeType": mime} for name, _data, file_name, mime in entries]
            ),
        },
        files=[("files", (file_name, data, mime)) for _name, data, file_name, mime in entries] or None,
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_backend_flow_from_install_to_output_after_stop(client) -> None:  # noqa: ANN001
    http, package = client
    install_and_prepare(http, package)
    width, height = 9, 4
    pixels = bytes(value for index in range(width * height) for value in (200, index % 256, 30, (index * 29) % 256))
    task = submit(http, "alpha-invert", files=[("image", encode_png_rgba(width, height, pixels), "source.png", "image/png")])
    finished = wait_task(http, task["task_id"])
    assert finished["status"] == "succeeded", finished
    assert finished["outputs"][0]["mime_type"] == "image/png"

    assert http.post(f"/api/workshop/v1/modules/{MODULE}/backend/stop").status_code == 200
    status = http.get(f"/api/workshop/v1/modules/{MODULE}/1.0.0/backend").json()
    assert status["runtime"]["pid"] is None
    _run_cleanup_pass()  # session/file cleanup must not touch backend results

    output = http.get(f"/api/workshop/v1/modules/{MODULE}/backend/tasks/{task['task_id']}/outputs/image")
    assert output.status_code == 200
    assert output.headers["cache-control"] == "no-store"
    out_width, out_height, out_pixels = decode_png_rgba(output.content)
    assert (out_width, out_height) == (width, height)
    assert out_pixels[3::4] == bytes(255 - value for value in pixels[3::4])

    listed = http.get(f"/api/workshop/v1/modules/{MODULE}/backend/tasks").json()["tasks"]
    assert task["task_id"] in {item["task_id"] for item in listed}


def test_backend_refusals_share_one_mapping_and_keep_log_context(
    client, caplog: pytest.LogCaptureFixture  # noqa: ANN001
) -> None:
    http, package = client
    with package.open("rb") as stream:
        installed = http.post(
            "/api/workshop/v1/install/local",
            files={"archive": (package.name, stream, "application/octet-stream")},
        )
    assert installed.status_code == 200, installed.text
    # Both routers report backend refusals through one boundary helper.
    boundary_logger = logging.getLogger("lumina.api.routers.workshop_backend")
    boundary_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=boundary_logger.name)
    try:
        activate = http.post(f"/api/workshop/v1/modules/{MODULE}/activate", json={"version": "1.0.0"})
        prepare = http.post(f"/api/workshop/v1/modules/{MODULE}/1.0.0/backend/prepare")
    finally:
        boundary_logger.removeHandler(caplog.handler)
    # The general Workshop router and the backend router map alike.
    assert activate.status_code == 409
    assert activate.json()["detail"]["code"] == "backend-not-prepared"
    assert prepare.status_code == 409
    assert prepare.json()["detail"]["code"] == "backend-authorization-required"
    refusals = {
        record.event: record
        for record in caplog.records
        if getattr(record, "status_code", None) == 409
        and getattr(record, "event", None) in {"workshop_module_activate_failed", "workshop_backend_prepare_failed"}
    }
    seen = [(record.name, getattr(record, "event", None), getattr(record, "status_code", None)) for record in caplog.records]
    assert set(refusals) == {"workshop_module_activate_failed", "workshop_backend_prepare_failed"}, seen
    assert refusals["workshop_module_activate_failed"].error_code == "backend-not-prepared"
    assert refusals["workshop_module_activate_failed"].module_id == MODULE
    assert refusals["workshop_module_activate_failed"].version == "1.0.0"
    assert refusals["workshop_backend_prepare_failed"].error_code == "backend-authorization-required"
    assert refusals["workshop_backend_prepare_failed"].error_type == "WorkshopBackendError"


def test_task_continues_without_a_waiting_client_and_disable_cancels(client) -> None:  # noqa: ANN001
    http, package = client
    install_and_prepare(http, package)
    quick = submit(http, "slow", params={"steps": 10, "delay": 0.02})
    # No polling while it runs (the module page was closed); it still finishes.
    time.sleep(1.0)
    assert wait_task(http, quick["task_id"])["status"] == "succeeded"

    long_task = submit(http, "slow", params={"steps": 5000, "delay": 0.05})
    deadline = time.monotonic() + 30
    while http.get(f"/api/workshop/v1/modules/{MODULE}/backend/tasks/{long_task['task_id']}").json()["status"] != "running":
        assert time.monotonic() < deadline
        time.sleep(0.05)
    disabled = http.patch(f"/api/workshop/v1/modules/{MODULE}/enabled", json={"enabled": False})
    assert disabled.status_code == 200
    final = wait_task(http, long_task["task_id"])
    assert final["status"] == "cancelled"
    assert final["error"]["code"] == "module-disabled"
    refused = http.post(
        f"/api/workshop/v1/modules/{MODULE}/backend/tasks",
        data={"version": "1.0.0", "operation": "echo"},
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "module-disabled"


def test_backend_routes_reject_cross_site_and_remote_origins(client) -> None:  # noqa: ANN001
    http, _package = client
    remote = http.get(
        "/api/workshop/v1/backend/storage",
        headers={"Origin": "https://attacker.example"},
    )
    assert remote.status_code == 403
    cross_site = http.get(
        "/api/workshop/v1/backend/storage",
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert cross_site.status_code == 403
    assert http.get("/api/workshop/v1/backend/storage").status_code == 200


def test_uninstall_reports_categories_and_releases_backend(client) -> None:  # noqa: ANN001
    http, package = client
    install_and_prepare(http, package)
    submit(http, "echo")
    response = http.request(
        "DELETE",
        f"/api/workshop/v1/modules/{MODULE}",
        json={"delete_projects": False, "delete_task_data": False, "retain_models": False},
    )
    assert response.status_code == 200, response.text
    report = response.json()["uninstall_report"]
    cleared = {item["kind"] for item in report["cleared"]}
    retained = {item["kind"] for item in report["retained"]}
    assert {"module-code", "environments"} <= cleared
    assert {"projects", "task-data"} <= retained
    assert http.get(f"/api/workshop/v1/modules/{MODULE}/1.0.0/backend").status_code == 404
    overview = http.get("/api/workshop/v1/backend/storage").json()
    assert overview["environments"] == []
    assert overview["shared_store"] == {"objects": 0, "bytes": 0}
    assert [item["module_id"] for item in overview["task_data"]] == [MODULE]
    deleted = http.request("DELETE", f"/api/workshop/v1/backend/storage/tasks/{MODULE}")
    assert deleted.status_code == 200
    assert http.get("/api/workshop/v1/backend/storage").json()["task_data"] == []
