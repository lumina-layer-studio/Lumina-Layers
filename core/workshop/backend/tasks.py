"""Durable host-owned backend tasks with input and output files.

Tasks belong to the host, not the iframe: they survive page switches, the
backend process stopping, and source-session closure. Terminal states are
final, so a late result can never overwrite a cancellation.

任务归宿主所有，不随页面切换、后端停止或来源会话关闭而丢失。终态不可再变，
迟到的结果不能覆盖已取消状态。
"""

from __future__ import annotations

import json
import re
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..errors import WorkshopBackendError
from ..install_store import _atomic_write
from ..models import MODULE_ID_PATTERN
from .store import RemovalOutcome, remove_tree


TaskStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "interrupted"]
TaskKind = Literal["operation", "prepare"]
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
_TASK_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
FILE_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SAFE_FILE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$")
OPERATION_PATTERN = re.compile(r"^[a-z][a-z0-9.-]{0,63}$")
MAX_TASK_RECORD_BYTES = 256 * 1024
DEFAULT_RESULT_RETENTION = timedelta(days=14)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def stored_input_path(inputs_dir: Path, index: int, file_name: str) -> Path:
    """Path of input ``index``; its own folder keeps the module's file name.

    Inputs with equal file names therefore never overwrite each other.
    """

    return inputs_dir / f"{index:02d}" / file_name


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


class _TaskModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TaskFile(_TaskModel):
    name: str = Field(pattern=FILE_NAME_PATTERN.pattern)
    file_name: str = Field(pattern=SAFE_FILE_NAME_PATTERN.pattern)
    mime_type: str = Field(min_length=1, max_length=127)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TaskProgress(_TaskModel):
    completed: float = Field(ge=0)
    total: float = Field(ge=0)
    phase: str = Field(max_length=200)


class TaskError(_TaskModel):
    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)


class TaskRecord(_TaskModel):
    task_id: str = Field(pattern=_TASK_ID_PATTERN.pattern)
    module_id: str
    module_version: str
    kind: TaskKind
    operation: str
    params: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, max_length=128)
    status: TaskStatus = "queued"
    progress: TaskProgress | None = None
    error: TaskError | None = None
    inputs: tuple[TaskFile, ...] = ()
    outputs: tuple[TaskFile, ...] = ()
    variant: str | None = None
    cancel_requested: bool = False
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None

    @property
    def terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


class TaskStore:
    """Persist tasks under ``tasks/<module-id>/<task-id>/``.

    在 ``tasks/<模块 ID>/<任务 ID>/`` 下持久化任务及其文件。
    """

    def __init__(
        self,
        root: Path,
        *,
        retention: timedelta = DEFAULT_RESULT_RETENTION,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.retention = retention
        self._clock = clock
        self._lock = threading.RLock()

    @staticmethod
    def _module_dir_name(module_id: str) -> str:
        if MODULE_ID_PATTERN.fullmatch(module_id) is None:
            raise WorkshopBackendError("module-invalid", "Module ID is invalid.")
        return module_id

    def task_dir(self, module_id: str, task_id: str) -> Path:
        if _TASK_ID_PATTERN.fullmatch(task_id) is None:
            raise WorkshopBackendError("task-not-found", "The backend task does not exist.")
        return self.root / self._module_dir_name(module_id) / task_id

    def inputs_dir(self, record: TaskRecord) -> Path:
        return self.task_dir(record.module_id, record.task_id) / "inputs"

    def outputs_dir(self, record: TaskRecord) -> Path:
        return self.task_dir(record.module_id, record.task_id) / "outputs"

    def work_dir(self, record: TaskRecord) -> Path:
        return self.task_dir(record.module_id, record.task_id) / "work"

    def _write(self, record: TaskRecord) -> TaskRecord:
        payload = json.dumps(
            record.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > MAX_TASK_RECORD_BYTES:
            raise WorkshopBackendError("task-record-too-large", "The backend task record is too large.")
        _atomic_write(self.task_dir(record.module_id, record.task_id) / "task.json", payload)
        return record

    def _read_path(self, path: Path) -> TaskRecord | None:
        try:
            if path.stat().st_size > MAX_TASK_RECORD_BYTES:
                return None
            return TaskRecord.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValidationError):
            return None

    def get(self, module_id: str, task_id: str) -> TaskRecord | None:
        with self._lock:
            record = self._read_path(self.task_dir(module_id, task_id) / "task.json")
            if record is None or record.module_id != module_id:
                return None
            return record

    def require(self, module_id: str, task_id: str) -> TaskRecord:
        record = self.get(module_id, task_id)
        if record is None:
            raise WorkshopBackendError("task-not-found", "The backend task does not exist.")
        return record

    def list(self, module_id: str | None = None) -> tuple[TaskRecord, ...]:
        with self._lock:
            module_dirs = (
                [self.root / self._module_dir_name(module_id)]
                if module_id is not None
                else [path for path in self.root.iterdir() if path.is_dir()]
            )
            records: list[TaskRecord] = []
            for module_dir in module_dirs:
                if not module_dir.is_dir():
                    continue
                for task_dir in module_dir.iterdir():
                    record = self._read_path(task_dir / "task.json")
                    if record is not None and record.module_id == module_dir.name:
                        records.append(record)
            return tuple(sorted(records, key=lambda item: (item.created_at, item.task_id), reverse=True))

    def create(
        self,
        *,
        module_id: str,
        module_version: str,
        kind: TaskKind,
        operation: str,
        params: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        prepare_files: Callable[[TaskRecord, Path], tuple[TaskFile, ...]] | None = None,
    ) -> tuple[TaskRecord, bool]:
        """Create a queued task, or return the existing one for the same key."""

        if OPERATION_PATTERN.fullmatch(operation) is None:
            raise WorkshopBackendError("operation-invalid", "The backend operation name is invalid.")
        with self._lock:
            if idempotency_key is not None:
                for existing in self.list(module_id):
                    if existing.idempotency_key == idempotency_key and existing.kind == kind:
                        return existing, False
            now = _iso(self._clock())
            record = TaskRecord(
                task_id=uuid.uuid4().hex,
                module_id=module_id,
                module_version=module_version,
                kind=kind,
                operation=operation,
                params=params or {},
                idempotency_key=idempotency_key,
                created_at=now,
                updated_at=now,
            )
            directory = self.task_dir(module_id, record.task_id)
            directory.mkdir(parents=True, exist_ok=False)
            try:
                if prepare_files is not None:
                    inputs_dir = directory / "inputs"
                    inputs_dir.mkdir()
                    record = record.model_copy(update={"inputs": prepare_files(record, inputs_dir)})
                return self._write(record), True
            except BaseException:
                remove_tree(directory)
                raise

    def update(
        self,
        module_id: str,
        task_id: str,
        *,
        allow_terminal: bool = False,
        **changes: Any,
    ) -> TaskRecord | None:
        """Apply changes unless the task is already terminal.

        Returns ``None`` when the task is terminal (or missing) so callers can
        discard late backend messages instead of overwriting the outcome.
        """

        with self._lock:
            current = self.get(module_id, task_id)
            if current is None or (current.terminal and not allow_terminal):
                return None
            values = current.model_dump(mode="python")
            values.update(changes)
            values["updated_at"] = _iso(self._clock())
            status = values.get("status")
            if status in TERMINAL_STATUSES and values.get("finished_at") is None:
                values["finished_at"] = values["updated_at"]
            if status == "running" and values.get("started_at") is None:
                values["started_at"] = values["updated_at"]
            return self._write(TaskRecord.model_validate(values))

    def finish(
        self,
        module_id: str,
        task_id: str,
        status: TaskStatus,
        *,
        error: TaskError | None = None,
        outputs: tuple[TaskFile, ...] = (),
    ) -> TaskRecord | None:
        if status not in TERMINAL_STATUSES:
            raise ValueError("finish requires a terminal status")
        changes: dict[str, Any] = {"status": status, "error": error}
        if outputs:
            changes["outputs"] = outputs
        record = self.update(module_id, task_id, **changes)
        if record is not None:
            remove_tree(self.work_dir(record))
        return record

    def delete(self, module_id: str, task_id: str) -> RemovalOutcome:
        with self._lock:
            record = self.require(module_id, task_id)
            if not record.terminal:
                raise WorkshopBackendError(
                    "task-active",
                    "Cancel the backend task before deleting it.",
                )
            return remove_tree(self.task_dir(module_id, task_id))

    def delete_module(self, module_id: str) -> RemovalOutcome:
        with self._lock:
            return remove_tree(self.root / self._module_dir_name(module_id))

    def unfinished(self) -> tuple[TaskRecord, ...]:
        return tuple(record for record in self.list() if not record.terminal)

    def mark_unfinished_interrupted(self, *, code: str, message: str) -> int:
        count = 0
        for record in self.unfinished():
            if self.finish(
                record.module_id,
                record.task_id,
                "interrupted",
                error=TaskError(code=code, message=message),
            ) is not None:
                count += 1
        return count

    def purge_expired(self) -> RemovalOutcome:
        """Delete finished tasks older than the retention period."""

        outcome = RemovalOutcome()
        cutoff = self._clock() - self.retention
        for record in self.list():
            if not record.terminal or record.finished_at is None:
                continue
            try:
                finished = datetime.fromisoformat(record.finished_at)
            except ValueError:
                continue
            if finished < cutoff:
                result = remove_tree(self.task_dir(record.module_id, record.task_id))
                outcome.freed_bytes += result.freed_bytes
                outcome.pending.extend(result.pending)
        return outcome

    def module_usage(self) -> dict[str, tuple[int, int]]:
        """Return ``module_id -> (task_count, bytes)`` for the overview."""

        usage: dict[str, tuple[int, int]] = {}
        for module_dir in self.root.iterdir() if self.root.is_dir() else ():
            if not module_dir.is_dir():
                continue
            count = 0
            total = 0
            for path in module_dir.rglob("*"):
                try:
                    if path.is_file():
                        total += path.stat().st_size
                    elif path.parent == module_dir:
                        count += 1
                except OSError:
                    continue
            usage[module_dir.name] = (count, total)
        return usage
