"""Lossless source and backend diagnostic collection. / 完整源文件与后端诊断采集。"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
import traceback
from typing import Any, Iterator
import zipfile

from starlette.datastructures import UploadFile

from api.structured_logging import get_logger
from api.file_registry import FileRegistry
from api.session_store import SessionStore
from api.session_value_codec import encode_session_value
from core.material_cache import default_cache_directory

log = get_logger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[1]


async def collect_source_uploads(
    ticket_dir: Path, uploads: list[UploadFile],
) -> list[dict[str, Any]]:
    """Save every browser source with its exact bytes and original filename.

    保存浏览器传来的全部源文件，保留完整字节及原始文件名。

    Args:
        ticket_dir: Reserved ticket directory. / 已预留的工单目录。
        uploads: All selected source files. / 全部已选择源文件。

    Returns:
        Per-file capture results. / 每个文件的采集结果。
    """
    results: list[dict[str, Any]] = []
    for index, upload in enumerate(uploads):
        original_name = upload.filename or "source"
        suffix = Path(original_name.replace("\\", "/")).suffix
        # The source name is metadata; the generated name owns the disk path.
        destination = ticket_dir / f"source_{index:04d}{suffix}"
        result: dict[str, Any] = {"original_filename": original_name, "filename": destination.name}
        try:
            await upload.seek(0)
            with destination.open("xb") as output:
                while chunk := await upload.read(1024 * 1024):
                    output.write(chunk)
            result.update(status="attached", size_bytes=destination.stat().st_size)
        except OSError as exc:
            destination.unlink(missing_ok=True)
            result.update(status="failed", error_type=type(exc).__name__, error_message=str(exc))
            log.warning("Source attachment could not be saved.", extra={
                "event": "feedback_attachment_collection_failed", "attachment_kind": "source_file",
                "ticket_id": ticket_dir.name, "error_type": type(exc).__name__,
                "error_message": str(exc),
            })
        results.append(result)
    return results


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)


def _archive_result(path: Path) -> dict[str, Any]:
    return {"status": "attached", "filename": path.name, "size_bytes": path.stat().st_size}


@dataclass
class _SessionSource:
    path: Path
    original_filename: str
    file_ids: set[str] = field(default_factory=set)
    session_ids: set[str] = field(default_factory=set)


class _SessionCapture:
    def __init__(self, file_registry: FileRegistry, session_store: SessionStore | None) -> None:
        self.file_registry = file_registry
        self.session_store = session_store
        self.sources: dict[Path, _SessionSource] = {}
        self.states: dict[str, Any] = {}
        self.registry_entries: dict[str, Any] = {}
        self.missing_files: list[dict[str, Any]] = []

    def _add_source(self, path: Path, session_id: str | None = None) -> _SessionSource:
        source = self.sources.setdefault(path, _SessionSource(path, path.name))
        if session_id:
            source.session_ids.add(session_id)
        return source

    def _add_registered_file(self, file_id: str, entry: dict[str, Any]) -> None:
        self.registry_entries[file_id] = entry
        source = self._add_source(Path(entry["path"]), entry.get("session_id"))
        source.original_filename = entry.get("filename") or source.path.name
        source.file_ids.add(file_id)

    def _collect_session(self, session_id: str) -> None:
        for file_id, entry in self.file_registry.get_session_entries(session_id).items():
            if entry.get("path"):
                self._add_registered_file(file_id, entry)
        state = (
            self.session_store.get_snapshot(session_id)
            if self.session_store is not None else None
        )
        if state is None:
            self.states[session_id] = {"status": "unavailable_after_cleanup"}
            return
        self.states[session_id] = state
        for value in _strings(state):
            if "\x00" in value:
                continue
            candidate = Path(value)
            try:
                if candidate.is_file():
                    self._add_source(candidate, session_id)
            except OSError:
                continue
        for value in self.session_store.get_temp_file_paths(session_id):
            self._add_source(Path(value), session_id)

    def collect(self, context: dict[str, Any]) -> None:
        session_ids = set(_strings(context.get("active_session_ids", {})))
        session_ids.update(
            entry["session_id"] for entry in context.get("session_history", [])
            if isinstance(entry, dict) and isinstance(entry.get("session_id"), str)
        )
        file_ids = set(_strings(context.get("source_file_ids") or []))
        for value in _strings(context):
            if value.startswith("/api/files/"):
                file_ids.add(value.removeprefix("/api/files/").split("?", 1)[0])
        for file_id in sorted(file_ids):
            entry = self.file_registry.get_entry(file_id)
            if not entry or not entry.get("path"):
                self.missing_files.append({
                    "file_ids": [file_id], "status": "failed", "error_type": "FileNotFoundError",
                    "error_message": f"Registered source file is unavailable: {file_id}",
                })
                continue
            self._add_registered_file(file_id, entry)
            if isinstance(entry.get("session_id"), str):
                session_ids.add(entry["session_id"])
        for session_id in sorted(session_ids):
            self._collect_session(session_id)
        cache_directory = default_cache_directory()
        if cache_directory.is_dir():
            for path in cache_directory.rglob("*"):
                if path.is_file():
                    self._add_source(path)

    def write(self, path: Path) -> dict[str, Any]:
        inventory: list[dict[str, Any]] = []
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for index, (_, source) in enumerate(sorted(self.sources.items())):
                basename = Path(source.original_filename.replace("\\", "/")).name
                member = f"files/{index:04d}_{basename}"
                entry = {
                    "path": str(source.path), "original_filename": source.original_filename,
                    "archive_path": member, "file_ids": sorted(source.file_ids),
                    "session_ids": sorted(source.session_ids),
                }
                try:
                    archive.write(source.path, member)
                    entry["status"] = "attached"
                except OSError as exc:
                    entry.update(
                        status="failed", error_type=type(exc).__name__, error_message=str(exc),
                    )
                inventory.append(entry)
            inventory.extend(self.missing_files)
            archive.writestr(
                "session-values.json",
                json.dumps(encode_session_value(self.states), ensure_ascii=False),
            )
            archive.writestr(
                "file-registry.json", json.dumps(self.registry_entries, ensure_ascii=False),
            )
            archive.writestr("files.json", json.dumps(inventory, ensure_ascii=False))
        return {**_archive_result(path), "files": inventory}


def _collect_session_archive(
    path: Path, context: dict[str, Any],
    file_registry: FileRegistry, session_store: SessionStore | None,
) -> dict[str, Any]:
    capture = _SessionCapture(file_registry, session_store)
    capture.collect(context)
    return capture.write(path)


def _collect_log_archive(path: Path) -> dict[str, Any]:
    flushed: set[logging.Handler] = set()
    for logger_name in ("lumina", ""):
        for handler in logging.getLogger(logger_name).handlers:
            # Only disk logs are archived. A detached console must not prevent
            # collecting the files that explain the original failure.
            if isinstance(handler, logging.FileHandler) and handler not in flushed:
                handler.flush()
                flushed.add(handler)
    configured_log = os.environ.get("LUMINA_LOG_PATH")
    logs = sorted((REPO_ROOT / "logs").glob("lumina_*.log*"))
    if configured_log:
        configured = Path(configured_log)
        logs.extend(configured.parent.glob(configured.name + "*"))
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index, source in enumerate(sorted(set(logs))):
            if source.is_file():
                archive.write(source, f"logs/{index:04d}_{source.name}")
    return _archive_result(path)


def collect_backend_diagnostics(
    ticket_dir: Path, context: dict[str, Any],
    file_registry: FileRegistry, session_store: SessionStore | None,
) -> dict[str, Any]:
    """Archive complete session data and logs with independent failure results.

    分别归档完整会话与日志，每项采集独立记录结果，使工单不依赖原会话生命周期。

    Args:
        ticket_dir: Reserved ticket directory. / 已预留的工单目录。
        context: Complete client workflow context. / 完整客户端工作流上下文。
        file_registry: Server-owned registered files. / 服务端已注册文件。
        session_store: Server-owned session state. / 服务端会话状态。

    Returns:
        Attachment manifest sections. / 附件清单各分段。
    """
    sections: dict[str, Any] = {}
    collectors = (
        ("session_data", _collect_session_archive, "session-data.zip",
         (context, file_registry, session_store)),
        ("backend_logs", _collect_log_archive, "backend-logs.zip", ()),
    )
    for kind, collector, filename, args in collectors:
        try:
            sections[kind] = collector(ticket_dir / filename, *args)
        except Exception as exc:  # Collection boundary; other archives must still be captured.
            sections[kind] = {
                "status": "failed", "error_type": type(exc).__name__,
                "error_message": str(exc), "error_stack": traceback.format_exc(),
            }
            log.warning("Diagnostic archive collection failed.", exc_info=True, extra={
                "event": "feedback_attachment_collection_failed", "attachment_kind": kind,
                "ticket_id": ticket_dir.name, "error_type": type(exc).__name__,
                "error_message": str(exc),
            })
    return sections
