"""Supervisor outcome rules with a scripted fake backend process."""

from __future__ import annotations

import time
from pathlib import Path

from core.workshop.backend.process import BackendLaunch
from core.workshop.backend.supervisor import ModuleBackendSupervisor, RunTarget
from core.workshop.backend.tasks import TaskStore


class ScriptedProcess:
    """Fake backend: ready on start, then reacts to run/cancel per script."""

    script: dict[str, object] = {}

    def __init__(self, launch, *, on_message, on_exit, log_fields) -> None:  # noqa: ANN001
        self._on_message = on_message
        self._on_exit = on_exit
        self.pid = 4242
        self.create_time = 1.0
        self.running: str | None = None
        self.output_dir: Path | None = None
        self._alive = False

    def start(self) -> None:
        self._alive = True
        self._on_message({"type": "ready", "protocol": 1})

    def output_tail(self) -> str:
        return ""

    def send(self, message: dict) -> None:
        kind = message["type"]
        if kind == "run":
            self.running = message["taskId"]
            self.output_dir = Path(message["outputDir"])
            if self.script.get("on_run") == "result":
                self._emit_result(self.script.get("outputs", []))
        elif kind == "cancel" and self.script.get("on_cancel") == "late-result":
            # The task finished in the backend right as cancellation arrived.
            self._emit_result([{"name": "out", "fileName": "out.txt", "mimeType": "text/plain"}])
        elif kind == "shutdown":
            self.terminate(grace_seconds=0)

    def _emit_result(self, outputs: list) -> None:  # noqa: ANN001
        assert self.output_dir is not None
        (self.output_dir / "out.txt").write_text("done", encoding="utf-8")
        self._on_message({"type": "result", "taskId": self.running, "outputs": outputs})

    def wait(self, timeout: float):  # noqa: ANN201
        return None if self._alive else 0

    def alive(self) -> bool:
        return self._alive

    def terminate(self, *, grace_seconds: float) -> None:
        if self._alive:
            self._alive = False
            self._on_exit(1, None)

    def shutdown(self, *, wait_seconds: float, grace_seconds: float) -> None:
        self.send({"type": "shutdown"})


def supervisor_for(tmp_path: Path, script: dict) -> tuple[ModuleBackendSupervisor, TaskStore]:  # noqa: ANN001
    ScriptedProcess.script = script
    tasks = TaskStore(tmp_path / "tasks")
    launch = BackendLaunch(
        python=tmp_path / "python",
        bootstrap=tmp_path / "bootstrap.py",
        backend_dir=tmp_path,
        entry=tmp_path / "main.py",
        scratch_dir=tmp_path / "scratch",
        work_dir=tmp_path / "work",
    )
    target = RunTarget(version="1.0.0", variant=None, launch=launch, models={}, idle_timeout_seconds=60)
    supervisor = ModuleBackendSupervisor(
        "fixture.fake",
        tasks=tasks,
        resolve_target=lambda _record: target,
        process_record_path=tmp_path / "process.json",
        cancel_grace_seconds=0.5,
        process_factory=ScriptedProcess,
    )
    return supervisor, tasks


def wait_terminal(tasks: TaskStore, task_id: str):  # noqa: ANN201
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        record = tasks.get("fixture.fake", task_id)
        if record is not None and record.terminal:
            return record
        time.sleep(0.02)
    raise AssertionError("task did not finish")


def test_late_result_after_cancel_request_stays_cancelled(tmp_path: Path) -> None:
    supervisor, tasks = supervisor_for(tmp_path, {"on_cancel": "late-result"})
    record, _created = tasks.create(module_id="fixture.fake", module_version="1.0.0", kind="operation", operation="work")
    supervisor.enqueue(record.task_id)
    deadline = time.monotonic() + 10
    while tasks.get("fixture.fake", record.task_id).status != "running":
        assert time.monotonic() < deadline
        time.sleep(0.02)
    supervisor.cancel(record.task_id)
    final = wait_terminal(tasks, record.task_id)
    assert final.status == "cancelled"
    assert final.outputs == ()
    time.sleep(0.2)
    assert tasks.get("fixture.fake", record.task_id).status == "cancelled"
    supervisor.stop(code="test-end", message="Test finished.")


def test_cancel_after_success_does_not_rewrite_the_outcome(tmp_path: Path) -> None:
    supervisor, tasks = supervisor_for(
        tmp_path,
        {"on_run": "result", "outputs": [{"name": "out", "fileName": "out.txt", "mimeType": "text/plain"}]},
    )
    record, _created = tasks.create(module_id="fixture.fake", module_version="1.0.0", kind="operation", operation="work")
    supervisor.enqueue(record.task_id)
    finished = wait_terminal(tasks, record.task_id)
    assert finished.status == "succeeded"
    assert supervisor.cancel(record.task_id).status == "succeeded"
    supervisor.stop(code="test-end", message="Test finished.")


def test_cancel_arriving_before_the_worker_releases_a_finished_task(tmp_path: Path) -> None:
    supervisor, tasks = supervisor_for(
        tmp_path,
        {"on_run": "result", "outputs": [{"name": "out", "fileName": "out.txt", "mimeType": "text/plain"}]},
    )
    record, _created = tasks.create(module_id="fixture.fake", module_version="1.0.0", kind="operation", operation="work")
    supervisor.enqueue(record.task_id)
    assert wait_terminal(tasks, record.task_id).status == "succeeded"
    # Recreate the moment between the stored result and the worker clearing
    # its current task: the finished outcome is returned and nothing is sent.
    with supervisor._condition:  # noqa: SLF001 - deterministic race window
        supervisor._current_task = record.task_id  # noqa: SLF001
        result = supervisor.cancel(record.task_id)
        flagged = supervisor._cancel_current  # noqa: SLF001
        supervisor._current_task = None  # noqa: SLF001
    assert result is not None and result.status == "succeeded"
    assert flagged is False
    assert tasks.get("fixture.fake", record.task_id).status == "succeeded"
    supervisor.stop(code="test-end", message="Test finished.")


def test_outputs_outside_the_task_directory_are_rejected(tmp_path: Path) -> None:
    supervisor, tasks = supervisor_for(
        tmp_path,
        {"on_run": "result", "outputs": [{"name": "out", "fileName": "../escape.txt", "mimeType": "text/plain"}]},
    )
    record, _created = tasks.create(module_id="fixture.fake", module_version="1.0.0", kind="operation", operation="work")
    supervisor.enqueue(record.task_id)
    final = wait_terminal(tasks, record.task_id)
    assert final.status == "failed"
    assert final.error is not None and final.error.code == "backend-output-invalid"
    supervisor.stop(code="test-end", message="Test finished.")
