from __future__ import annotations

import asyncio
import io
import json
import zipfile

from fastapi import HTTPException, UploadFile
import pytest

from api.file_registry import FileRegistry
from api.project_export import revision_bytes
from api.routers.projects import capture_template, freeze_revision, restore_template
from api.session_store import SessionStore
from core.projects.container import build_project_bytes
from core.projects.schema import ProjectSnapshot, WorkflowDocument


@pytest.mark.parametrize("data", [b"not a project", b"PK\x03\x04truncated"])
def test_invalid_revision_is_a_client_error(data):
    with pytest.raises(HTTPException) as result:
        asyncio.run(freeze_revision(UploadFile(file=io.BytesIO(data)), FileRegistry()))
    assert result.value.status_code == 422


def test_unsafe_revision_is_a_client_error():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../outside", "invalid")
    test_invalid_revision_is_a_client_error(stream.getvalue())


def test_frozen_revision_is_private_and_independent_of_closed_editor():
    registry, store = FileRegistry(), SessionStore()
    snapshot = ProjectSnapshot.new(name="Frozen", workflow_kinds=("converter",), documents=(
        WorkflowDocument(document_id="converter.main", kind="converter", schema_version=2, payload={}),
    ))
    data = build_project_bytes(snapshot)
    result = asyncio.run(freeze_revision(UploadFile(file=io.BytesIO(data)), registry))
    try:
        sid = store.create()
        registry.cleanup_session(sid)
        store.close(sid)
        assert result["revision_id"] == snapshot.revision_id
        assert revision_bytes(result["file_id"], registry) == data
        assert registry.get_entry(result["file_id"])["is_public"] is False
        public = registry.register_bytes("", data, "untrusted.lum")
        try:
            with pytest.raises(HTTPException):
                revision_bytes(public, registry)
        finally:
            registry.cleanup_file(public)
    finally:
        registry.cleanup_file(result["file_id"])


def test_custom_template_uses_private_lifetime_and_existing_loader(tmp_path, monkeypatch):
    import core.custom_3mf_templates as templates
    monkeypatch.setattr(templates, "_path", lambda template_id: tmp_path / (template_id.replace(":", "-") + ".json"))
    from config import SUPPORTED_SLICERS
    settings = {"_lumina_template_slicer": SUPPORTED_SLICERS[0]["id"], "layer_height": "0.12"}
    store = SessionStore()
    result = asyncio.run(restore_template(UploadFile(file=io.BytesIO(json.dumps(settings).encode())), store))
    assert result["template_id"].startswith("project:")
    assert capture_template(result["template_id"]) == settings
    assert len(list(tmp_path.iterdir())) == 1
    store.close(result["session_id"])
    assert list(tmp_path.iterdir()) == []
