"""Explicit revision attachment at the final artifact boundary."""
from pathlib import Path

from fastapi import HTTPException

from api.file_registry import FileRegistry
from core.projects.export import embed_project_in_generated_file


def revision_bytes(file_id: str | None, registry: FileRegistry) -> bytes | None:
    if not file_id:
        return None
    entry = registry.get_entry(file_id)
    if not entry or entry.get("purpose") != "project_revision" or entry.get("is_public") is not False:
        raise HTTPException(422, "The requested project revision is unavailable")
    resolved = registry.resolve(file_id)
    if resolved is None:
        raise HTTPException(422, "The requested project revision has expired")
    return Path(resolved[0]).read_bytes()


def embed_generated_project(path: str, file_id: str | None, registry: FileRegistry) -> None:
    data = revision_bytes(file_id, registry)
    if data is not None:
        embed_project_in_generated_file(path, data)
