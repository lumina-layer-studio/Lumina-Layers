"""Per-module backend supervision: on-demand start, tasks, cancel, idle stop.

Each module has one supervisor. It starts the backend process when a task
is submitted, runs one task at a time (so terminating a process tree never
affects another task), cancels cooperatively and then terminates the tree
after a grace period, and stops the process after an idle period.

每个模块一个监管者：提交任务时按需启动后端，同时只执行一个任务（终止进程树
不会误伤其他任务），先协作取消、超过宽限期再终止进程树，空闲后释放进程。
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from api.structured_logging import get_logger

from ..constants import MAX_BACKEND_TASK_FILE_BYTES, MAX_BACKEND_TASK_OUTPUTS
from ..errors import WorkshopBackendError
from ..install_store import _atomic_write
from .process import BackendLaunch, BackendProcess
from .store import remove_tree
from .tasks import (
    FILE_NAME_PATTERN,
    SAFE_FILE_NAME_PATTERN,
    TaskError,
    TaskFile,
    TaskProgress,
    TaskRecord,
    TaskStore,
    stored_input_path,
)


log = get_logger(__name__)

SupervisorState = Literal["stopped", "starting", "ready", "busy", "stopping", "failed"]
_ERROR_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{0,79}$")
_MIME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,63}/[a-z0-9][a-z0-9!#$&^_.+-]{0,63}$")
_PROGRESS_WRITE_INTERVAL_SECONDS = 0.2
PRESENCE_TTL_SECONDS = 90.0
PRESENCE_IDLE_SECONDS = 900.0


@dataclass(frozen=True, slots=True)
class RunTarget:
    """Resolved environment and code for one task run."""

    version: str
    variant: str | None
    launch: BackendLaunch
    models: dict[str, str]
    idle_timeout_seconds: float
    fallback: "RunTarget | None" = None


TargetResolver = Callable[[TaskRecord], RunTarget]
VariantFailure = Callable[[str, str], None]


@dataclass(slots=True)
class _Outcome:
    kind: str
    message: dict[str, Any]


class ModuleBackendSupervisor:
    """Own one module's backend process and execute its queued tasks.

    管理一个模块的后端进程并依次执行其排队任务。
    """

    def __init__(
        self,
        module_id: str,
        *,
        tasks: TaskStore,
        resolve_target: TargetResolver,
        process_record_path: Path,
        cancel_grace_seconds: float = 5.0,
        start_timeout_seconds: float = 120.0,
        on_task_finished: Callable[[TaskRecord], None] | None = None,
        on_variant_failed: VariantFailure | None = None,
        on_process_released: Callable[[str], None] | None = None,
        process_factory: Callable[..., BackendProcess] = BackendProcess,
    ) -> None:
        self.module_id = module_id
        self._on_variant_failed = on_variant_failed
        # Told the version of every released process: the version may now be
        # unused (for example after switching to a newer version's task).
        self._on_process_released = on_process_released
        self._tasks = tasks
        self._resolve_target = resolve_target
        self._process_record_path = process_record_path
        self._cancel_grace = cancel_grace_seconds
        self._start_timeout = start_timeout_seconds
        self._on_task_finished = on_task_finished
        self._process_factory = process_factory
        self._condition = threading.Condition(threading.RLock())
        self._queue: deque[str] = deque()
        self._worker: threading.Thread | None = None
        self._process: BackendProcess | None = None
        self._process_target: tuple[str, str | None] | None = None
        self._ready = False
        self._exited = True
        self._current_task: str | None = None
        self._outcome: _Outcome | None = None
        self._state: SupervisorState = "stopped"
        self._stopping = False
        self._last_failure: str | None = None
        self._presence_until = 0.0
        self._idle_timeout = 300.0
        self._last_progress_write = 0.0
        self._cancel_current = False
        self._stop_reason: tuple[str, str] | None = None

    # ----- public API -------------------------------------------------

    def enqueue(self, task_id: str) -> None:
        with self._condition:
            if self._stopping:
                raise WorkshopBackendError("backend-stopping", "The module backend is stopping.")
            if task_id not in self._queue and task_id != self._current_task:
                self._queue.append(task_id)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(
                    target=self._run_worker,
                    name=f"workshop-backend-{self.module_id}",
                    daemon=True,
                )
                self._worker.start()
            self._condition.notify_all()

    def cancel(self, task_id: str) -> TaskRecord | None:
        """Cancel a queued task now, or request cancellation of a running one."""

        with self._condition:
            if task_id in self._queue:
                self._queue.remove(task_id)
                record = self._tasks.finish(
                    self.module_id,
                    task_id,
                    "cancelled",
                    error=TaskError(code="cancelled", message="The task was cancelled."),
                )
                self._notify_finished(record)
                return record
            if task_id == self._current_task:
                current = self._tasks.get(self.module_id, task_id)
                if current is not None and current.terminal:
                    # Finished just before the worker released it.
                    return current
                self._cancel_current = True
                record = self._tasks.update(self.module_id, task_id, cancel_requested=True)
                self._send({"type": "cancel", "taskId": task_id})
                self._condition.notify_all()
                return record if record is not None else self._tasks.get(self.module_id, task_id)
        record = self._tasks.get(self.module_id, task_id)
        if record is not None and not record.terminal:
            record = self._tasks.finish(
                self.module_id,
                task_id,
                "cancelled",
                error=TaskError(code="cancelled", message="The task was cancelled."),
            )
            self._notify_finished(record)
        return record

    def touch_presence(self) -> None:
        with self._condition:
            self._presence_until = time.monotonic() + PRESENCE_TTL_SECONDS
            self._condition.notify_all()

    def stop(self, *, code: str, message: str, grace_seconds: float | None = None) -> None:
        """Cancel queued and running tasks, then end this module's process tree."""

        grace = self._cancel_grace if grace_seconds is None else grace_seconds
        with self._condition:
            self._stopping = True
            self._stop_reason = (code, message)
            queued = list(self._queue)
            self._queue.clear()
            current = self._current_task
            if current is not None:
                self._cancel_current = True
            self._state = "stopping" if self._process is not None else "stopped"
            self._condition.notify_all()
        for task_id in queued:
            self._notify_finished(
                self._tasks.finish(
                    self.module_id,
                    task_id,
                    "cancelled",
                    error=TaskError(code=code, message=message),
                )
            )
        if current is not None:
            self._tasks.update(self.module_id, current, cancel_requested=True)
            self._send({"type": "cancel", "taskId": current})
            deadline = time.monotonic() + grace
            with self._condition:
                while self._current_task == current and time.monotonic() < deadline:
                    self._condition.wait(min(0.1, max(0.0, deadline - time.monotonic())))
        self._terminate_process()
        if current is not None:
            self._notify_finished(
                self._tasks.finish(
                    self.module_id,
                    current,
                    "cancelled",
                    error=TaskError(code=code, message=message),
                )
            )
        worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=30)
        with self._condition:
            self._stopping = False
            self._stop_reason = None
            self._state = "stopped"
            self._current_task = None

    def stop_idle_process(self) -> None:
        """Stop the process when no task is queued or running (user action)."""

        with self._condition:
            busy = self._current_task is not None or bool(self._queue)
        if busy:
            self.stop(code="stopped-by-user", message="The module backend was stopped.")
        else:
            self._terminate_process()

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return {
                "state": self._state,
                "pid": self._process.pid if self._process is not None and not self._exited else None,
                "version": self._process_target[0] if self._process_target else None,
                "variant": self._process_target[1] if self._process_target else None,
                "current_task_id": self._current_task,
                "queued": len(self._queue),
                "last_failure": self._last_failure,
            }

    def release_idle_version(self, keep: set[str], finished_task: str | None = None) -> bool:
        """Stop an idle process whose version is no longer retained.

        ``finished_task`` has already ended; the worker may not have let go of
        it yet, which must not make the process look busy.
        """

        with self._condition:
            target = self._process_target
            idle = self._current_task in (None, finished_task) and not self._queue
            stale = target is not None and target[0] not in keep and not self._exited
        if idle and stale:
            self._terminate_process()
            return True
        return False

    def active_versions(self) -> set[str]:
        with self._condition:
            versions: set[str] = set()
            if self._process_target is not None and not self._exited:
                versions.add(self._process_target[0])
            return versions

    def process_alive(self) -> bool:
        with self._condition:
            return self._process is not None and not self._exited

    # ----- worker -----------------------------------------------------

    def _run_worker(self) -> None:
        while True:
            with self._condition:
                while not self._queue and not self._stopping:
                    idle = self._idle_timeout
                    if time.monotonic() < self._presence_until:
                        idle = max(idle, PRESENCE_IDLE_SECONDS)
                    if self._process is None or self._exited:
                        self._state = "stopped" if self._last_failure is None else "failed"
                        self._worker = None
                        return
                    if not self._condition.wait(timeout=idle):
                        if not self._queue and time.monotonic() >= self._presence_until:
                            break
                if self._stopping:
                    self._worker = None
                    return
                if not self._queue:
                    idle_release = True
                else:
                    idle_release = False
                    task_id = self._queue.popleft()
                    self._current_task = task_id
                    self._outcome = None
                    self._cancel_current = False
            if idle_release:
                log.info(
                    "Workshop backend released after idle period",
                    extra={"event": "workshop_backend_idle_stop", "module_id": self.module_id},
                )
                self._terminate_process()
                continue
            try:
                self._run_task(task_id)
            except Exception as exc:  # noqa: BLE001 - task boundary must record failure
                log.exception(
                    "Workshop backend task failed unexpectedly",
                    extra={
                        "event": "workshop_backend_task_failed",
                        "module_id": self.module_id,
                        "task_id": task_id,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
                self._notify_finished(
                    self._tasks.finish(
                        self.module_id,
                        task_id,
                        "failed",
                        error=TaskError(code="backend-failed", message="The backend task failed."),
                    )
                )
            finally:
                with self._condition:
                    self._current_task = None
                    if self._state == "busy":
                        self._state = "ready"
                    self._condition.notify_all()

    def _run_task(self, task_id: str) -> None:
        record = self._tasks.get(self.module_id, task_id)
        if record is None or record.terminal:
            return
        if record.cancel_requested:
            self._notify_finished(
                self._tasks.finish(
                    self.module_id,
                    task_id,
                    "cancelled",
                    error=TaskError(code="cancelled", message="The task was cancelled."),
                )
            )
            return
        try:
            target = self._start_with_fallback(self._resolve_target(record))
        except WorkshopBackendError as exc:
            self._last_failure = exc.code
            self._notify_finished(
                self._tasks.finish(
                    self.module_id,
                    task_id,
                    "failed",
                    error=TaskError(code=exc.code, message=str(exc)[:500]),
                )
            )
            return
        running = self._tasks.update(
            self.module_id,
            task_id,
            status="running",
            variant=target.variant,
        )
        if running is None:
            return
        outputs_dir = self._tasks.outputs_dir(running)
        remove_tree(outputs_dir)
        outputs_dir.mkdir(parents=True, exist_ok=True)
        work_dir = self._tasks.work_dir(running)
        work_dir.mkdir(parents=True, exist_ok=True)
        inputs_dir = self._tasks.inputs_dir(running)
        message = {
            "type": "run",
            "taskId": task_id,
            "operation": running.operation,
            "params": running.params,
            "inputs": [
                {
                    "name": item.name,
                    "path": str(stored_input_path(inputs_dir, index, item.file_name)),
                    "fileName": item.file_name,
                    "mimeType": item.mime_type,
                }
                for index, item in enumerate(running.inputs)
            ],
            "outputDir": str(outputs_dir),
            "workDir": str(work_dir),
            "models": target.models,
            "variant": target.variant or "cpu",
        }
        with self._condition:
            self._state = "busy"
        self._send(message)
        self._await_outcome(running)

    def _await_outcome(self, record: TaskRecord) -> None:
        task_id = record.task_id
        cancel_deadline: float | None = None
        with self._condition:
            while True:
                if self._outcome is not None:
                    outcome = self._outcome
                    break
                if self._exited:
                    outcome = _Outcome("exited", {})
                    break
                if self._cancel_current and cancel_deadline is None:
                    cancel_deadline = time.monotonic() + self._cancel_grace
                if cancel_deadline is not None and time.monotonic() >= cancel_deadline:
                    outcome = _Outcome("cancel-timeout", {})
                    break
                self._condition.wait(0.1)
            # Cancellation decided before this point wins over a late result.
            cancel_requested = self._cancel_current
            stop_code, stop_message = self._stop_reason or (
                "cancelled",
                "The task was cancelled.",
            )
        if outcome.kind == "cancel-timeout":
            # Cooperative cancellation was ignored: end the whole tree.
            log.info(
                "Workshop backend task cancellation forced",
                extra={"event": "workshop_backend_cancel_forced", "module_id": self.module_id, "task_id": task_id},
            )
            self._terminate_process()
        if cancel_requested:
            self._notify_finished(
                self._tasks.finish(
                    self.module_id,
                    task_id,
                    "cancelled",
                    error=TaskError(code=stop_code, message=stop_message),
                )
            )
            remove_tree(self._tasks.outputs_dir(record))
            return
        if outcome.kind == "result":
            try:
                outputs = self._collect_outputs(record, outcome.message.get("outputs"))
            except WorkshopBackendError as exc:
                self._notify_finished(
                    self._tasks.finish(
                        self.module_id,
                        task_id,
                        "failed",
                        error=TaskError(code=exc.code, message=str(exc)[:500]),
                    )
                )
                return
            self._notify_finished(
                self._tasks.finish(self.module_id, task_id, "succeeded", outputs=outputs)
            )
            return
        if outcome.kind == "error":
            code = outcome.message.get("code")
            text = outcome.message.get("message")
            self._notify_finished(
                self._tasks.finish(
                    self.module_id,
                    task_id,
                    "failed",
                    error=TaskError(
                        code=code if isinstance(code, str) and _ERROR_CODE_PATTERN.fullmatch(code) else "backend-error",
                        message=(text if isinstance(text, str) and text.strip() else "The backend reported an error.")[:500],
                    ),
                )
            )
            return
        if outcome.kind == "cancelled":
            self._notify_finished(
                self._tasks.finish(
                    self.module_id,
                    task_id,
                    "cancelled",
                    error=TaskError(code="cancelled", message="The task was cancelled."),
                )
            )
            return
        self._notify_finished(
            self._tasks.finish(
                self.module_id,
                task_id,
                "failed",
                error=TaskError(
                    code="backend-crashed",
                    message="The module backend stopped before finishing the task.",
                ),
            )
        )

    def _collect_outputs(self, record: TaskRecord, raw: Any) -> tuple[TaskFile, ...]:
        if not isinstance(raw, list) or len(raw) > MAX_BACKEND_TASK_OUTPUTS:
            raise WorkshopBackendError("backend-output-invalid", "The backend returned an invalid output list.")
        outputs_dir = self._tasks.outputs_dir(record).resolve()
        collected: list[TaskFile] = []
        names: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                raise WorkshopBackendError("backend-output-invalid", "A backend output entry is invalid.")
            name = item.get("name")
            file_name = item.get("fileName")
            mime_type = item.get("mimeType")
            if (
                not isinstance(name, str)
                or FILE_NAME_PATTERN.fullmatch(name) is None
                or name in names
                or not isinstance(file_name, str)
                or SAFE_FILE_NAME_PATTERN.fullmatch(file_name) is None
                or file_name.endswith((".", " "))
                or not isinstance(mime_type, str)
                or _MIME_PATTERN.fullmatch(mime_type) is None
            ):
                raise WorkshopBackendError("backend-output-invalid", "A backend output entry is invalid.")
            path = outputs_dir / file_name
            try:
                info = path.lstat()
            except OSError as exc:
                raise WorkshopBackendError("backend-output-missing", "A declared backend output file is missing.") from exc
            if path.is_symlink() or not path.is_file() or path.resolve().parent != outputs_dir:
                raise WorkshopBackendError("backend-output-invalid", "A backend output is not a regular task file.")
            if info.st_size > MAX_BACKEND_TASK_FILE_BYTES:
                raise WorkshopBackendError("backend-output-too-large", "A backend output exceeds 64 MiB.")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            names.add(name)
            collected.append(
                TaskFile(
                    name=name,
                    file_name=file_name,
                    mime_type=mime_type,
                    size_bytes=info.st_size,
                    sha256=digest,
                )
            )
        return tuple(collected)

    # ----- process management -----------------------------------------

    def _start_with_fallback(self, target: RunTarget) -> RunTarget:
        try:
            self._ensure_process(target)
            return target
        except WorkshopBackendError:
            if target.fallback is None or target.variant is None:
                raise
            # Acceleration failed to initialize: record why, keep CPU usable.
            if self._on_variant_failed is not None:
                self._on_variant_failed(target.version, target.variant)
            self._ensure_process(target.fallback)
            return target.fallback

    def _ensure_process(self, target: RunTarget) -> None:
        wanted = (target.version, target.variant)
        with self._condition:
            reuse = self._process is not None and not self._exited and self._process_target == wanted and self._ready
            self._idle_timeout = target.idle_timeout_seconds
        if reuse:
            return
        self._terminate_process()
        with self._condition:
            self._state = "starting"
            self._ready = False
            self._exited = False
            self._process_target = wanted
        process = self._process_factory(
            target.launch,
            on_message=self._handle_message,
            on_exit=self._handle_exit,
            log_fields={"module_id": self.module_id, "version": target.version, "variant": target.variant or "cpu"},
        )
        with self._condition:
            self._process = process
        process.start()
        self._write_process_record(process, target)
        deadline = time.monotonic() + self._start_timeout
        with self._condition:
            while not self._ready and not self._exited and time.monotonic() < deadline:
                self._condition.wait(0.1)
            ready = self._ready
        if not ready:
            tail = process.output_tail()
            self._terminate_process()
            log.warning(
                "Workshop backend failed to start",
                extra={
                    "event": "workshop_backend_start_failed",
                    "module_id": self.module_id,
                    "version": target.version,
                    "variant": target.variant or "cpu",
                    "error_message": tail[-1500:] or "no ready handshake",
                },
            )
            with self._condition:
                self._state = "failed"
            raise WorkshopBackendError(
                "backend-start-failed",
                "The module backend did not complete its startup handshake.",
            )
        with self._condition:
            self._state = "ready"
            self._last_failure = None
        log.info(
            "Workshop backend started",
            extra={
                "event": "workshop_backend_started",
                "module_id": self.module_id,
                "version": target.version,
                "variant": target.variant or "cpu",
                "pid": process.pid,
            },
        )

    def _remove_process_record(self) -> None:
        # Best effort: the exit watcher and a stop can race on Windows; a
        # leftover record is harmless because startup checks pid + time.
        try:
            self._process_record_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _write_process_record(self, process: BackendProcess, target: RunTarget) -> None:
        if process.pid is None or process.create_time is None:
            return
        try:
            _atomic_write(
                self._process_record_path,
                json.dumps(
                    {
                        "pid": process.pid,
                        "createTime": process.create_time,
                        "moduleId": self.module_id,
                        "version": target.version,
                    }
                ).encode("utf-8"),
            )
        except OSError:
            pass

    def _terminate_process(self) -> None:
        with self._condition:
            process = self._process
        if process is None:
            return
        process.shutdown(wait_seconds=0.5, grace_seconds=1.0)
        released: str | None = None
        with self._condition:
            if self._process is process:
                released = self._process_target[0] if self._process_target else None
                self._process = None
                self._process_target = None
                self._ready = False
                self._exited = True
                if self._state not in {"failed", "stopping"}:
                    self._state = "stopped"
            self._condition.notify_all()
        self._remove_process_record()
        if released is not None and self._on_process_released is not None:
            try:
                self._on_process_released(released)
            except Exception as exc:  # noqa: BLE001 - observer must not break stops
                log.warning(
                    "Workshop backend release observer failed",
                    extra={
                        "event": "workshop_backend_release_observer_failed",
                        "module_id": self.module_id,
                        "version": released,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )

    def _send(self, message: dict[str, Any]) -> None:
        with self._condition:
            process = self._process
        if process is None:
            return
        try:
            process.send(message)
        except (OSError, ValueError):
            pass

    def _handle_message(self, message: dict[str, Any]) -> None:
        kind = message["type"]
        with self._condition:
            if kind == "ready":
                if message.get("protocol") == 1:
                    self._ready = True
                self._condition.notify_all()
                return
            if message.get("taskId") != self._current_task:
                return
            if kind == "progress":
                now = time.monotonic()
                if now - self._last_progress_write < _PROGRESS_WRITE_INTERVAL_SECONDS:
                    return
                self._last_progress_write = now
                task_id = self._current_task
            else:
                self._outcome = _Outcome(kind, message)
                self._condition.notify_all()
                return
        completed = message.get("completed")
        total = message.get("total")
        phase = message.get("phase", "")
        if (
            isinstance(completed, (int, float))
            and isinstance(total, (int, float))
            and not isinstance(completed, bool)
            and 0 <= completed <= max(total, 0)
            and isinstance(phase, str)
        ):
            self._tasks.update(
                self.module_id,
                task_id,
                progress=TaskProgress(completed=completed, total=total, phase=phase[:200]),
            )

    def _handle_exit(self, returncode: int | None, protocol_failure: str | None) -> None:
        with self._condition:
            self._exited = True
            self._ready = False
            if protocol_failure is not None:
                self._last_failure = "backend-protocol-error"
            self._condition.notify_all()
        self._remove_process_record()
        log.info(
            "Workshop backend process exited",
            extra={
                "event": "workshop_backend_exited",
                "module_id": self.module_id,
                "returncode": returncode,
            },
        )

    def _notify_finished(self, record: TaskRecord | None) -> None:
        if record is not None and self._on_task_finished is not None:
            try:
                self._on_task_finished(record)
            except Exception as exc:  # noqa: BLE001 - observer must not break tasks
                log.warning(
                    "Workshop backend task observer failed",
                    extra={
                        "event": "workshop_backend_task_observer_failed",
                        "module_id": self.module_id,
                        "task_id": record.task_id,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
