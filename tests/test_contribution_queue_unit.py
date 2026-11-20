"""Queue behavior across saves, restarts, accounts and interrupted uploads."""
import base64
import copy
import io
import json
import sqlite3
import zipfile

from PIL import Image
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.contribution_queue import ContributionQueue
from core.resource_contribution import PreparedContribution
from core.resource_seed import seed_lock
from api.services import contribution_queue as service
from api.services.resource_contribution import ContributionError

SERVER = "https://community.example/api/material-registry/v1"


def _sample_print_photo() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (40, 140, 210)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


SAMPLE_PRINT_PHOTO = _sample_print_photo()


@pytest.fixture
def queued(tmp_path, monkeypatch):
    queue = ContributionQueue(tmp_path / "queue.sqlite3", "workspace-one")
    monkeypatch.setattr(service, "queue_store", lambda: queue)
    monkeypatch.setattr(service.connection, "source", lambda: SERVER)
    monkeypatch.setattr(service.connection, "subject", "maker")
    monkeypatch.setattr(service.connection, "status", lambda: {
        "state": "connected", "subject": "maker", "email_verified": True,
    })
    prepared = PreparedContribution("materials", "Brand/Red", "a" * 64,
        {"brand": "Brand", "material_type": "PLA", "material_name": "Red"}, {},
        {"material.json": b"{}", "stage_A_parameters.json": b'{"parameters":{"k":1}}'})
    monkeypatch.setattr(service, "prepare_contribution", lambda *_: copy.deepcopy(prepared))
    monkeypatch.setattr(service, "local_resource_origin", lambda *_: None)
    queue.configure(SERVER, "maker", True)
    return queue, prepared


def test_save_freezes_files_and_reopening_uses_same_snapshot(queued):
    queue, prepared = queued
    result = service.capture_calibration("materials", prepared.key)
    prepared.files["stage_A_parameters.json"] = b"changed locally"
    reopened = ContributionQueue(queue.path, queue.workspace)
    row, snapshot, _ = reopened.snapshot(SERVER, result["id"])
    assert snapshot.files["stage_A_parameters.json"] == b'{"parameters":{"k":1}}'
    assert row["account"] == "maker"
    assert snapshot.display["attribution"] == {"relationship": "original"}
    assert snapshot.display["license"] == "LicenseRef-Lumina-Data-1.0"
    assert service.capture_calibration("materials", prepared.key)["id"] == result["id"]


@pytest.mark.parametrize("license_id", ["CC-BY-4.0", None])
def test_derived_snapshot_keeps_manifest_terms_without_relicensing(queued, monkeypatch, license_id):
    queue, prepared = queued
    origin = {"reference": {"kind": "materials", "resource_id": "mat_original", "revision_id": "rev_original",
                            "content_hash": "sha256:" + "b" * 64}, "license": license_id,
              "original_author": "Original maker", "rights_basis": license_id or ""}
    monkeypatch.setattr(service, "local_resource_origin", lambda *_: origin)
    job = service.capture_calibration("materials", prepared.key)
    row, snapshot, frozen_origin = queue.snapshot(SERVER, job["id"])
    assert row["state"] == "needs_review"
    assert frozen_origin == origin
    assert snapshot.display.get("license") == license_id


def test_pause_resume_does_not_scan_or_resume_old_items(queued):
    queue, prepared = queued
    job = service.capture_calibration("materials", prepared.key, print_images=[SAMPLE_PRINT_PHOTO])["id"]
    queue.pause(SERVER)
    assert service.capture_calibration("materials", "Another") is None
    queue.configure(SERVER, "maker", True)
    assert queue.items(SERVER)[0]["state"] == "paused"
    assert queue.claim(SERVER, "maker") is None
    queue.action(SERVER, job, "retry")
    assert queue.claim(SERVER, "maker") == job


def test_license_change_needs_fresh_consent_and_preserves_old_snapshot_terms(queued):
    from core import contribution_queue
    queue, prepared = queued
    job = service.capture_calibration("materials", prepared.key, print_images=[SAMPLE_PRINT_PHOTO])["id"]
    with queue.transaction() as db:
        db.execute("UPDATE contribution_grants SET consent_version='public-calibration-v1'")
        row = db.execute("SELECT snapshot FROM contribution_jobs WHERE id=?", (job,)).fetchone()
        previous = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(row["snapshot"])) as source, zipfile.ZipFile(previous, "w") as target:
            for name in source.namelist():
                payload = source.read(name)
                if name == "snapshot.json":
                    metadata = json.loads(payload)
                    metadata["consent_version"] = "public-calibration-v1"
                    metadata["display"].pop("license", None)
                    payload = json.dumps(metadata).encode()
                target.writestr(name, payload)
        from core.resource_contribution import sha
        db.execute("UPDATE contribution_jobs SET snapshot=?,digest=? WHERE id=?",
                   (previous.getvalue(), sha(previous.getvalue()), job))
    assert not queue.grant(SERVER)["enabled"]
    assert queue.claim(SERVER, "maker") is None
    assert queue.items(SERVER)[0]["state"] == "paused"
    queue.configure(SERVER, "maker", True)
    assert queue.items(SERVER)[0]["state"] == "paused"
    assert queue.grant(SERVER)["consent_version"] == contribution_queue.CONSENT_VERSION
    assert queue.snapshot(SERVER, job)[1].display["license"] == "CC-BY-4.0"


def test_account_service_and_workspace_are_separate(queued):
    queue, prepared = queued
    job = service.capture_calibration("materials", prepared.key, print_images=[SAMPLE_PRINT_PHOTO])["id"]
    queue.configure(SERVER, "other", True)
    assert queue.claim(SERVER, "other") is None
    assert queue.items(SERVER)[0]["state"] == "paused"
    assert not queue.items(SERVER + "/other")
    other = ContributionQueue(queue.path, "workspace-two")
    assert other.grant(SERVER) is None
    assert other.items(SERVER) == []
    with pytest.raises(ValueError):
        other.snapshot(SERVER, job)
    with pytest.raises(ValueError, match="Reconnect"):
        queue.review(SERVER, job, "other", prepared.display)


def test_new_save_cannot_be_assigned_to_a_previously_connected_account(queued, monkeypatch):
    queue, prepared = queued
    monkeypatch.setattr(service.connection, "subject", "other")
    assert service.capture_calibration("materials", prepared.key) is None
    assert queue.grant(SERVER)["enabled"] == 0
    assert queue.items(SERVER) == []


def test_budget_is_shared_and_cancel_releases_snapshot(queued, monkeypatch):
    queue, prepared = queued
    monkeypatch.setattr("core.contribution_queue.MAX_PENDING", 1)
    job = service.capture_calibration("materials", prepared.key)["id"]
    other = ContributionQueue(queue.path, "workspace-two")
    other.configure(SERVER, "maker", True)
    with pytest.raises(ValueError, match="full"):
        other.add(SERVER, "maker", prepared, prepared.display, None, ready=True)
    queue.action(SERVER, job, "cancel")
    assert other.add(SERVER, "maker", prepared, prepared.display, None, ready=True)
    assert queue.items(SERVER)[0]["state"] == "cancelled"


def test_public_or_imported_remeasurement_needs_source_review(queued, monkeypatch):
    queue, prepared = queued
    monkeypatch.setattr(service, "local_resource_origin", lambda *_: {
        "reference": {"kind": "materials", "resource_id": "mat_public", "revision_id": "rev_1",
                      "content_hash": "sha256:" + "1" * 64}, "modified": True})
    result = service.capture_calibration("materials", prepared.key)
    assert result["state"] == "needs_review"
    queue.action(SERVER, result["id"], "pause")
    with pytest.raises(ValueError, match="details"):
        queue.action(SERVER, result["id"], "retry")
    assert queue.claim(SERVER, "maker") is None
    monkeypatch.setattr(service, "local_resource_origin", lambda *_: None)
    prepared.fingerprint = "b" * 64
    # A previous derived capture must not convert this into original work.
    assert service.capture_calibration("materials", prepared.key, new_calibration=False)["state"] == "needs_review"


def test_remeasurement_ownership_requires_the_pre_save_content(queued):
    queue, prepared = queued
    service.capture_calibration("materials", prepared.key)
    assert service.owns_calibration("materials", prepared.key)
    prepared.fingerprint = "c" * 64  # Same name overwritten by an imported file.
    assert not service.owns_calibration("materials", prepared.key)
    assert service.capture_calibration("materials", prepared.key, new_calibration=False)["state"] == "needs_review"


def test_metadata_gap_waits_for_review_of_the_frozen_snapshot(queued):
    queue, prepared = queued
    prepared.display["material_type"] = ""
    job = service.capture_calibration("materials", prepared.key)["id"]
    assert queue.claim(SERVER, "maker") is None
    queue.review(SERVER, job, "maker", {**prepared.display, "material_type": "PLA"}, print_images=[SAMPLE_PRINT_PHOTO])
    assert queue.claim(SERVER, "maker") == job
    assert queue.snapshot(SERVER, job)[1].display["material_type"] == "PLA"
    assert queue.print_images(SERVER, job) == [SAMPLE_PRINT_PHOTO]


def test_capture_without_print_photo_waits_in_needs_review_with_print_photo_reason(queued):
    queue, prepared = queued
    result = service.capture_calibration("materials", prepared.key)
    assert result["state"] == "needs_review"
    assert queue.items(SERVER)[0]["reason"] == "print_photo"
    assert queue.claim(SERVER, "maker") is None
    queue.review(SERVER, result["id"], "maker", prepared.display, print_images=[SAMPLE_PRINT_PHOTO])
    assert queue.claim(SERVER, "maker") == result["id"]


def test_success_records_receipt_and_releases_blob(queued, monkeypatch):
    queue, prepared = queued
    job = service.capture_calibration("materials", prepared.key, print_images=[SAMPLE_PRINT_PHOTO])["id"]
    sent = []
    def submit(snapshot, display, expected_subject, **kwargs):
        sent.append((snapshot, display, expected_subject, kwargs.get("print_images")))
        return {"kind": "materials", "status": "pending", "submission_id": "receipt"}
    monkeypatch.setattr(service.connection, "submit", submit)
    service.process_one()
    service.process_one()
    assert len(sent) == 1
    assert sent[0][2] == "maker"
    assert sent[0][3] == [SAMPLE_PRINT_PHOTO]
    assert queue.items(SERVER)[0]["state"] == "received"
    with pytest.raises(ValueError):
        queue.snapshot(SERVER, job)


def test_transient_retry_keeps_bytes_and_crash_recovers_sending(queued, monkeypatch):
    queue, prepared = queued
    job = service.capture_calibration("materials", prepared.key, print_images=[SAMPLE_PRINT_PHOTO])["id"]
    def offline(*args, **kwargs):
        raise ContributionError(502, "offline")
    monkeypatch.setattr(service.connection, "submit", offline)
    service.process_one()
    item = queue.items(SERVER)[0]
    assert item["state"] == "queued" and item["attempts"] == 1 and item["next_attempt"] > 0
    service.process_one()
    assert queue.items(SERVER)[0]["attempts"] == 1
    queue.action(SERVER, job, "retry")
    assert queue.claim(SERVER, "maker") == job  # Simulate a crash while sending.
    monkeypatch.setattr(service.connection, "submit", lambda *a, **kw: {"status": "pending"})
    service.process_one()
    assert queue.items(SERVER)[0]["state"] == "received"


def test_worker_never_uploads_under_other_or_unverified_account(queued, monkeypatch):
    queue, prepared = queued
    service.capture_calibration("materials", prepared.key, print_images=[SAMPLE_PRINT_PHOTO])
    monkeypatch.setattr(service.connection, "submit", lambda *a, **kw: pytest.fail("unexpected upload"))
    for account, verified in (("other", True), ("maker", False)):
        monkeypatch.setattr(service.connection, "status", lambda: {
            "state": "connected", "subject": account, "email_verified": verified})
        service.process_one()
    assert queue.items(SERVER)[0]["attempts"] == 0


def test_worker_lock_prevents_parallel_upload_and_pause_during_send_is_retained(queued, monkeypatch):
    queue, prepared = queued
    service.capture_calibration("materials", prepared.key, print_images=[SAMPLE_PRINT_PHOTO])
    def submit(*args, **kwargs):
        queue.pause(SERVER)
        raise ContributionError(502, "response lost")
    monkeypatch.setattr(service.connection, "submit", submit)
    with seed_lock(queue.path.parent / "worker"):
        service.process_one()
    assert queue.items(SERVER)[0]["attempts"] == 0
    service.process_one()
    assert queue.items(SERVER)[0]["state"] == "paused"


def test_full_queue_never_rolls_back_local_save(queued, monkeypatch):
    monkeypatch.setattr("core.contribution_queue.MAX_BYTES", 1)
    assert service.capture_calibration("materials", "Brand/Red") == {
        "state": "needs_attention", "reason": "snapshot_failed"}


def test_newer_schema_is_not_modified(tmp_path):
    queue = ContributionQueue(tmp_path / "future.sqlite3", "workspace")
    with sqlite3.connect(queue.path) as db:
        db.execute("PRAGMA user_version=2")
    with pytest.raises(ValueError, match="newer"):
        queue.items(SERVER)
    with sqlite3.connect(queue.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 2


def test_queue_reads_do_not_rewrite_the_database(queued):
    queue, prepared = queued
    job = service.capture_calibration("materials", prepared.key)["id"]
    before = queue.path.read_bytes()
    reopened = ContributionQueue(queue.path, queue.workspace)
    assert reopened.grant(SERVER)["account"] == "maker"
    assert reopened.owns_snapshot(SERVER, "maker", prepared)
    assert reopened.items(SERVER)[0]["id"] == job
    assert reopened.snapshot(SERVER, job)[1].fingerprint == prepared.fingerprint
    assert queue.path.read_bytes() == before


def test_queue_readers_do_not_wait_for_an_uncommitted_writer(queued):
    queue, _ = queued
    with sqlite3.connect(queue.path) as writer:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE contribution_grants SET enabled=0")
        # Readers should see the committed grant without requesting a write lock.
        assert ContributionQueue(queue.path, queue.workspace).grant(SERVER)["enabled"] == 1


def test_api_requires_verified_consent_and_uses_immutable_review(queued, monkeypatch):
    from api.routers.contributions import router
    queue, prepared = queued
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    headers = {"X-Lumina-Contribution": "1"}
    config = {"account_id": "maker", "enabled": True, "consent": False}
    assert client.put("/api/contributions/automatic", json=config, headers=headers).status_code == 422
    config["consent"] = True
    assert client.put("/api/contributions/automatic", json=config).status_code == 403
    assert client.put("/api/contributions/automatic", json=config, headers=headers).status_code == 200
    prepared.display["material_type"] = ""
    job = service.capture_calibration("materials", prepared.key)["id"]
    prepared.files.clear()  # The original file can disappear after saving.
    request = {"kind": "materials", "key": prepared.key, "queue_id": job, "fingerprint": "a" * 64,
               "name": "Red", "product": {"brand": "Brand", "material_type": "PLA"},
               "consent": True, "account_id": "other", "attribution": {"relationship": "original"}}
    assert client.post("/api/contributions/submit", json=request, headers=headers).status_code == 409
    request["account_id"] = "maker"
    assert client.post("/api/contributions/submit", json=request, headers=headers).status_code == 422
    request["print_images"] = [SAMPLE_PRINT_PHOTO]
    response = client.post("/api/contributions/submit", json=request, headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"
    assert queue.snapshot(SERVER, job)[1].files["material.json"] == b"{}"
    assert queue.print_images(SERVER, job) == [SAMPLE_PRINT_PHOTO]
