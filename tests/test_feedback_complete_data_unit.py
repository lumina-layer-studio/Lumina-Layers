"""Lossless ticket regressions. / 完整工单数据回归。"""

import asyncio
import io
import json
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest
from starlette.datastructures import UploadFile

from api import feedback_assembler, feedback_hosted
from api.routers.feedback import BugReportRequest
from tests.test_feedback_router_unit import _payload, client, feedback_root


def test_report_preserves_full_diagnostics_and_unknown_workflow_state() -> None:
    payload = _payload()
    details = {
        "error_stack": "Traceback\n/Users/min/project/source.svg\n" + "x" * 16000,
        "status_code": 500,
        "items": list(range(80)),
        "nested": {"a": {"b": {"c": {"d": {"e": "keep"}}}}},
    }
    payload["context"]["recent_client_logs"] = [{"details": details}] * 120
    payload["context"]["workflow_state"] = {"model": "plate.stl", "custom": details}
    request = BugReportRequest.model_validate(payload)
    dumped = request.model_dump(mode="json")
    assert dumped["context"]["recent_client_logs"] == payload["context"]["recent_client_logs"]
    assert dumped["context"]["workflow_state"] == payload["context"]["workflow_state"]


def test_large_original_upload_is_kept_exactly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feedback_assembler, "MAX_DIRECT_ORIGINAL_IMAGE_BYTES", 1, raising=False)
    data = b"<svg>original source</svg>"
    upload = UploadFile(io.BytesIO(data), filename="source.svg", size=len(data))
    result = asyncio.run(feedback_assembler.collect_direct_original_upload(
        tmp_path, upload, session_id=None,
    ))
    assert result["status"] == "attached"
    assert (tmp_path / result["filename"]).read_bytes() == data


def test_original_upload_is_saved_without_a_workflow_reference(client, feedback_root: Path) -> None:
    data = b"<svg><!-- original before any session --></svg>"
    response = client.post("/api/feedback/bug-report", data={"request_payload": json.dumps(_payload())}, files={
        "original_image": ("original.svg", data, "image/svg+xml"),
    })
    assert response.status_code == 200
    ticket = next(feedback_root.glob("*/*/ticket.json")).parent
    assert (ticket / "original.svg").read_bytes() == data


def test_bundle_includes_every_file_without_size_or_type_filter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"ticket_id": "LUM-202610-12345678", "description": "failure", "context": {}}
    files = {"source.stl": b"solid model", "backend.log": b"Traceback", "empty.dat": b""}
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    monkeypatch.setattr(feedback_hosted, "MAX_UPLOAD_ATTACHMENT_BYTES", 1, raising=False)
    monkeypatch.setattr(feedback_hosted, "MAX_UPLOAD_BUNDLE_FILE_BYTES", 1, raising=False)
    monkeypatch.setattr(feedback_hosted, "MAX_UPLOAD_ATTACHMENTS", 1, raising=False)
    bundle = feedback_hosted.build_ticket_bundle(tmp_path, payload)
    assert {item.name for item in bundle.files} == set(files)
    assert bundle.held_back == []


def test_final_project_copy_preserves_even_damaged_source_bytes(tmp_path: Path) -> None:
    from api.file_registry import FileRegistry

    source = tmp_path / "bad.3mf"
    source.write_bytes(b"damaged original project needed to reproduce")
    registry = FileRegistry()
    registry.register_path("session", str(source))
    ticket = tmp_path / "ticket"
    ticket.mkdir()
    result = feedback_assembler.collect_sync_attachments(
        ticket, {"context": {"active_final_artifact_ref": {"session_id": "session"}}}, registry,
    )
    assert result.final_artifact["status"] == "attached"
    assert (ticket / "final.3mf").read_bytes() == source.read_bytes()


def test_preset_lut_is_copied_before_its_source_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    source = root / "lut-preset" / "Brand" / "preset.npy"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"exact preset bytes from the reporting device")
    monkeypatch.setattr(feedback_assembler, "REPO_ROOT", root)
    monkeypatch.setattr("api.feedback_assembler.LUTManager.LUT_PRESET_DIR", str(root / "lut-preset"))
    monkeypatch.setattr(feedback_assembler, "_find_lut_file", lambda _: source)
    ticket = tmp_path / "ticket"
    ticket.mkdir()
    result = feedback_assembler._collect_single_lut(ticket, "Brand - preset", filename_prefix="lut")
    assert result["status"] == "attached"
    assert result["kind"] == "preset"
    expected = source.read_bytes()
    source.unlink()
    assert (ticket / result["filename"]).read_bytes() == expected


def test_installed_preset_lut_uses_the_actual_resource_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from utils.lut_manager import LUTManager

    root = tmp_path / "installed-app" / "lut-preset"
    source = root / "Brand" / "sample.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"installed preset LUT bytes")
    monkeypatch.setattr(LUTManager, "LUT_PRESET_DIR", str(root))
    monkeypatch.setattr(LUTManager, "get_lut_path", lambda _: str(source))
    ticket = tmp_path / "ticket"
    ticket.mkdir()
    result = feedback_assembler._collect_single_lut(ticket, "Brand - sample", filename_prefix="lut")
    assert result["status"] == "attached"
    assert result["kind"] == "preset"
    assert result["preset_relative_path"] == "lut-preset/Brand/sample.json"
    assert (ticket / result["filename"]).read_bytes() == source.read_bytes()


def test_empty_original_source_survives_finalization(client, feedback_root: Path) -> None:
    payload = _payload()
    payload["context"]["active_original_image_ref"] = {"filename": "empty.png", "source": "converter"}
    response = client.post("/api/feedback/bug-report", data={"request_payload": json.dumps(payload)}, files={
        "original_image": ("empty.png", b"", "image/png"),
    })
    assert response.status_code == 200
    ticket = next(feedback_root.glob("*/*/ticket.json")).parent
    report = json.loads((ticket / "ticket.json").read_text(encoding="utf-8"))
    assert report["attachments"]["original_image"]["status"] == "attached"
    assert (ticket / "original.png").read_bytes() == b""


def test_multipart_collects_all_sources_session_files_and_backend_traceback(
    client, feedback_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import zipfile
    from api.dependencies import get_file_registry, get_session_store

    registry = get_file_registry()
    sessions = get_session_store()
    session_id = sessions.create()
    model = tmp_path / "plate.stl"
    model.write_bytes(b"solid original model")
    registry.register_path(session_id, str(model), is_public=False, purpose="model_surface_source")
    sessions.put(session_id, "model_path", str(model))
    backend_log = tmp_path / "lumina_test.log"
    backend_log.write_text("Traceback: /Users/min/source.svg\nRuntimeError: failed", encoding="utf-8")
    monkeypatch.setenv("LUMINA_LOG_PATH", str(backend_log))
    payload = _payload(description="Traceback /Users/min/source.svg" + "x" * 12000)
    payload["context"]["active_session_ids"]["converter"] = session_id
    response = client.post("/api/feedback/bug-report", data={"request_payload": json.dumps(payload)}, files=[
        ("source_files", ("原图.svg", b"<svg>unmodified source</svg>", "image/svg+xml")),
        ("source_files", ("plate.stl", model.read_bytes(), "application/octet-stream")),
    ])
    assert response.status_code == 200, response.text
    ticket = next(feedback_root.glob("*/*/ticket.json")).parent
    report = json.loads((ticket / "ticket.json").read_text(encoding="utf-8"))
    assert report["description"] == payload["description"]
    sources = report["attachments"]["source_files"]
    assert [entry["original_filename"] for entry in sources] == ["原图.svg", "plate.stl"]
    assert (ticket / sources[0]["filename"]).read_bytes() == b"<svg>unmodified source</svg>"
    sessions.close(session_id)
    with zipfile.ZipFile(ticket / "session-data.zip") as archive:
        assert model.read_bytes() in [archive.read(name) for name in archive.namelist()]
    with zipfile.ZipFile(ticket / "backend-logs.zip") as archive:
        assert backend_log.read_bytes() in [archive.read(name) for name in archive.namelist()]


def test_real_unhandled_exception_traceback_is_packaged(client, feedback_root: Path) -> None:
    import uuid
    import zipfile

    marker = f"full-backend-trace-{uuid.uuid4()}"

    @client.app.get("/test-feedback-crash")
    async def crash():
        raise RuntimeError(marker)

    assert client.get("/test-feedback-crash").status_code == 500
    assert client.post("/api/feedback/bug-report", json=_payload()).status_code == 200
    ticket = next(feedback_root.glob("*/*/ticket.json")).parent
    with zipfile.ZipFile(ticket / "backend-logs.zip") as archive:
        records = [
            json.loads(line) for name in archive.namelist()
            for line in archive.read(name).decode("utf-8").splitlines()
        ]
    record = next(item for item in records if item.get("error_message") == marker)
    assert "Traceback" in record["exception"]
    assert "raise RuntimeError(marker)" in record["exception"]
    assert marker in record["exception"]


def test_session_archive_maps_file_ids_and_reports_missing_sources(tmp_path: Path) -> None:
    import zipfile
    from api.file_registry import FileRegistry
    from api.feedback_sources import collect_backend_diagnostics

    source = tmp_path / "calibrated-full.png"
    source.write_bytes(b"full calibrated input")
    registry = FileRegistry()
    file_id = registry.register_path("colorchecker-session", str(source), is_public=False)
    ticket = tmp_path / "ticket"
    ticket.mkdir()
    sections = collect_backend_diagnostics(ticket, {
        "source_file_ids": [file_id, "expired-file-id"],
        "active_session_ids": {},
    }, registry, None)
    inventory = sections["session_data"]["files"]
    captured = next(item for item in inventory if file_id in item.get("file_ids", []))
    assert captured["status"] == "attached"
    assert captured["file_ids"] == [file_id]
    assert captured["session_ids"] == ["colorchecker-session"]
    missing = next(item for item in inventory if "expired-file-id" in item.get("file_ids", []))
    assert missing["status"] == "failed"
    assert missing["error_type"] == "FileNotFoundError"
    with zipfile.ZipFile(ticket / "session-data.zip") as archive:
        assert archive.read(captured["archive_path"]) == source.read_bytes()
        assert json.loads(archive.read("files.json")) == inventory


@pytest.mark.parametrize("runtime_override", [False, True])
def test_backend_archive_preserves_the_actual_solver_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, runtime_override: bool,
) -> None:
    import zipfile
    from api.file_registry import FileRegistry
    from api.feedback_sources import collect_backend_diagnostics
    from core import material_cache

    materials = tmp_path / "user-data" / "materials"
    monkeypatch.setattr(material_cache, "MATERIALS_DIR", str(materials))
    monkeypatch.delenv("LUMINA_RUNTIME_CACHE_DIR", raising=False)
    cache_root = tmp_path / "runtime-cache" if runtime_override else materials
    if runtime_override:
        monkeypatch.setenv("LUMINA_RUNTIME_CACHE_DIR", str(cache_root))
    cache = cache_root / "_solver_cache" / "solver-record.npz"
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"actual solver data")
    ticket = tmp_path / "ticket"
    ticket.mkdir()
    sections = collect_backend_diagnostics(ticket, {}, FileRegistry(), None)
    captured = next(item for item in sections["session_data"]["files"] if item["path"] == str(cache))
    with zipfile.ZipFile(ticket / "session-data.zip") as archive:
        assert archive.read(captured["archive_path"]) == cache.read_bytes()


@pytest.mark.parametrize("missing_material", [False, True])
def test_finalize_uses_the_installed_material_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, missing_material: bool,
) -> None:
    import zipfile

    material_root = tmp_path / "user-data" / "materials"
    source = material_root / "selected-material" / "profile.json"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"installed material profile")
    monkeypatch.setattr(feedback_assembler, "MATERIALS_DIR", str(material_root), raising=False)
    monkeypatch.setenv("LUMINA_FEEDBACK_SERVER_URL", "off")
    ticket = tmp_path / "ticket"
    ticket.mkdir()
    selected = ["selected-material", "missing-material"] if missing_material else ["selected-material"]
    (ticket / "ticket.json").write_text(json.dumps({
        "ticket_id": "LUM-202610-12345678", "description": "failure", "attachments": {},
        "context": {"source_material_dir_names": selected},
    }), encoding="utf-8")
    asyncio.run(feedback_assembler.finalize_ticket_async(ticket, None))
    with zipfile.ZipFile(ticket / "materials.zip") as archive:
        assert archive.read("selected-material/profile.json") == source.read_bytes()
    report = json.loads((ticket / "ticket.json").read_text(encoding="utf-8"))
    assert report["assembly_status"] == ("partial_failed" if missing_material else "done")
    assert report["attachments"]["materials_bundle"]["missing_dirs"] == (
        ["missing-material"] if missing_material else []
    )


def test_many_large_sources_round_trip_with_a_low_file_handle_limit(tmp_path: Path) -> None:
    pytest.importorskip("resource")
    script = textwrap.dedent('''
        import asyncio, hashlib, json, resource, sys
        from pathlib import Path
        import httpx
        from fastapi import FastAPI, Request
        from api.feedback_files import FeedbackMultipartParser
        from api.feedback_hosted import _post_bundle, build_ticket_bundle

        directory = Path(sys.argv[1])
        source = b"original source bytes" * 50000
        digest = hashlib.sha256(source).hexdigest()
        for index in range(80):
            (directory / f"source_{index:04d}.stl").write_bytes(source)
        bundle = build_ticket_bundle(directory, {"ticket_id": "LUM-202610-12345678", "context": {}})
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        resource.setrlimit(resource.RLIMIT_NOFILE, (min(64, soft), hard))
        app = FastAPI()

        @app.post("/v2/feedback/bundles")
        async def receive(request: Request):
            parser = FeedbackMultipartParser(request.headers, request.stream(), max_files=float("inf"))
            form = await parser.parse()
            try:
                uploads = form.getlist("attachment")
                assert len(uploads) == 80
                for upload in uploads:
                    assert hashlib.sha256(await upload.read()).hexdigest() == digest
                return {"ticket_id": bundle.ticket_id, "status": "received", "attachments": len(uploads)}
            finally:
                await form.close()

        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://feedback.test") as client:
                receipt = await _post_bundle(client, "https://feedback.test", bundle, {})
                assert receipt["attachments"] == 80

        asyncio.run(run())
    ''')
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)], capture_output=True, text=True,
        encoding="utf-8", timeout=60,
    )
    assert result.returncode == 0, result.stderr


def test_material_packing_keeps_other_requests_responsive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading
    import time
    from api.feedback_materials_bundle import MaterialsBundleResult

    started = threading.Event()
    finished = threading.Event()

    def slow_pack(*args, **kwargs):
        started.set()
        time.sleep(0.1)
        finished.set()
        return MaterialsBundleResult("not_applicable", None, None, 0)

    monkeypatch.setattr(feedback_assembler, "pack_materials", slow_pack)
    monkeypatch.setenv("LUMINA_FEEDBACK_SERVER_URL", "off")
    (tmp_path / "ticket.json").write_text(json.dumps({
        "ticket_id": "LUM-202610-12345678", "context": {"source_material_dir_names": ["material"]},
    }), encoding="utf-8")

    async def run():
        task = asyncio.create_task(feedback_assembler.finalize_ticket_async(tmp_path, None))
        while not started.is_set():
            await asyncio.sleep(0.001)
        assert not finished.is_set(), "Material packaging blocked the request event loop"
        await task

    asyncio.run(run())


def test_diagnostic_capture_survives_concurrent_session_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from concurrent.futures import ThreadPoolExecutor
    import threading
    import zipfile
    from api.feedback_sources import collect_backend_diagnostics
    from api.file_registry import FileRegistry
    from api.session_store import SessionStore
    from api.session_value_codec import decode_session_value

    sessions = SessionStore()
    session_id = sessions.create()
    source = tmp_path / "original.svg"
    source.write_bytes(b"<svg>source</svg>")
    sessions.put(session_id, "image_path", str(source))
    nested = {"values": ["original value"]}
    sessions.put(session_id, "nested", nested)
    reached = threading.Event()
    resume = threading.Event()
    original_is_file = Path.is_file

    def pause_at_source(path: Path, *args, **kwargs):
        if path == source:
            reached.set()
            assert resume.wait(5)
        return original_is_file(path, *args, **kwargs)

    monkeypatch.setattr(Path, "is_file", pause_at_source)
    ticket = tmp_path / "ticket"
    ticket.mkdir()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(collect_backend_diagnostics, ticket, {
            "active_session_ids": {"converter": session_id},
        }, FileRegistry(), sessions)
        try:
            assert reached.wait(5)
            sessions.put(session_id, "job_result", {"status": "done"})
            nested["values"].append("new value")
            nested["new_field"] = "new field"
        finally:
            resume.set()
        sections = future.result(timeout=10)
    assert sections["session_data"]["status"] == "attached"
    with zipfile.ZipFile(ticket / "session-data.zip") as archive:
        captured = decode_session_value(json.loads(archive.read("session-values.json")))[session_id]
        assert "job_result" not in captured
        assert captured["nested"] == {"values": ["original value"]}


def test_unexpected_diagnostic_failure_does_not_abort_the_ticket(
    client, feedback_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("unexpected diagnostic capture failure")

    monkeypatch.setattr("api.routers.feedback.collect_backend_diagnostics", fail)
    response = client.post("/api/feedback/bug-report", data={"request_payload": json.dumps(_payload())}, files={
        "source_files": ("original.stl", b"complete model", "application/octet-stream"),
    })
    assert response.status_code == 200, response.text
    ticket = next(feedback_root.glob("*/*/ticket.json")).parent
    report = json.loads((ticket / "ticket.json").read_text(encoding="utf-8"))
    assert report["assembly_status"] == "partial_failed"
    assert report["attachments"]["backend_diagnostics"]["error_type"] == "RuntimeError"
    assert report["submission"]["status"] == "disabled"
    assert (ticket / "source_0000.stl").read_bytes() == b"complete model"


def test_session_archive_preserves_restorable_arrays_and_complex_values(tmp_path: Path) -> None:
    import zipfile
    import numpy as np
    from api.feedback_sources import collect_backend_diagnostics
    from api.file_registry import FileRegistry
    from api.session_store import SessionStore
    from api.session_value_codec import decode_session_value

    sessions = SessionStore()
    session_id = sessions.create()
    cache = {
        "array": np.arange(6, dtype=np.int16).reshape(2, 3),
        "bytes": b"\x00\xffsource", "tuple": (2, 3), "set": {"red", "blue"},
        "path": tmp_path / "source.svg",
        "typed_keys": {(2, 3): b"keyed data"},
    }
    sessions.put(session_id, "cache", cache)
    ticket = tmp_path / "ticket"
    ticket.mkdir()
    collect_backend_diagnostics(ticket, {"active_session_ids": {"converter": session_id}}, FileRegistry(), sessions)
    with zipfile.ZipFile(ticket / "session-data.zip") as archive:
        restored = decode_session_value(json.loads(archive.read("session-values.json")))[session_id]["cache"]
    np.testing.assert_array_equal(restored["array"], cache["array"])
    assert restored["array"].dtype == cache["array"].dtype
    for key in ("bytes", "tuple", "set", "path", "typed_keys"):
        assert restored[key] == cache[key]


@pytest.mark.parametrize("failed_kind", ["session_data", "backend_logs"])
def test_archive_failure_preserves_other_data_and_marks_collection_incomplete(
    client, feedback_root: Path, monkeypatch: pytest.MonkeyPatch, failed_kind: str,
) -> None:
    def fail(*args, **kwargs):
        raise OSError("archive write failed")

    function = "_collect_session_archive" if failed_kind == "session_data" else "_collect_log_archive"
    monkeypatch.setattr(f"api.feedback_sources.{function}", fail)
    response = client.post("/api/feedback/bug-report", data={"request_payload": json.dumps(_payload())}, files={
        "source_files": ("original.stl", b"complete model", "application/octet-stream"),
    })
    assert response.status_code == 200, response.text
    ticket = next(feedback_root.glob("*/*/ticket.json")).parent
    report = json.loads((ticket / "ticket.json").read_text(encoding="utf-8"))
    assert report["assembly_status"] == "partial_failed"
    assert report["attachments"][failed_kind]["error_type"] == "OSError"
    assert "Traceback" in report["attachments"][failed_kind]["error_stack"]
    other = "backend_logs" if failed_kind == "session_data" else "session_data"
    assert report["attachments"][other]["status"] == "attached"
    bundle = feedback_hosted.build_ticket_bundle(ticket, report)
    assert report["attachments"][other]["filename"] in {item.name for item in bundle.files}
    assert (ticket / "source_0000.stl").read_bytes() == b"complete model"


def test_log_archive_survives_disconnected_console(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import logging
    import zipfile
    from api import feedback_sources

    class DisconnectedConsole(io.StringIO):
        def flush(self) -> None:
            raise BrokenPipeError("console reader has exited")

    log_path = tmp_path / "diagnostics.jsonl"
    handler = logging.FileHandler(log_path, encoding="utf-8")
    # Leave actual bytes buffered so the archive must flush the file handler.
    handler.stream.write("original preview failure\n")
    console = logging.StreamHandler(DisconnectedConsole())
    monkeypatch.setattr(logging.getLogger("lumina"), "handlers", [console, handler])
    monkeypatch.setattr(logging.getLogger(), "handlers", [console, handler])
    monkeypatch.setattr(feedback_sources, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("LUMINA_LOG_PATH", str(log_path))
    archive_path = tmp_path / "backend-logs.zip"
    try:
        result = feedback_sources._collect_log_archive(archive_path)
        assert result["status"] == "attached"
        with zipfile.ZipFile(archive_path) as archive:
            assert len(archive.namelist()) == 1
            assert archive.read(archive.namelist()[0]) == b"original preview failure\n"
    finally:
        handler.close()
