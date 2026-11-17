"""Unit tests for WorkerPoolManager lifecycle and behavior.

Covers: start/shutdown lifecycle, submit success/error, is_alive property,
max_workers defaults, and RuntimeError when pool not started.

**Validates: Requirements 1.1, 1.4, 1.5, 2.3**
"""

import asyncio
from contextlib import suppress
import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

import api.worker_pool as worker_pool
from api.worker_pool import WorkerPoolManager
from config import WorkerPoolConfig


@pytest.fixture(autouse=True)
def _clear_logging_context_between_tests():
    from api.structured_logging import bind_session_id, set_request_id

    set_request_id(None)
    bind_session_id(None)
    yield
    set_request_id(None)
    bind_session_id(None)


# ---------------------------------------------------------------------------
# Helpers — top-level picklable functions for process pool
# ---------------------------------------------------------------------------

def _add(a: int, b: int) -> int:
    """Simple addition for testing submit."""
    return a + b


def _raise_value_error(msg: str) -> None:
    """Raise ValueError in worker process."""
    raise ValueError(msg)




def _slow_task(seconds: float) -> str:
    """Sleep for given seconds, simulating a long-running task."""
    import time
    time.sleep(seconds)
    return "done"




def _read_context_ids() -> tuple[str | None, str | None]:
    """Top-level helper for asserting contextvar propagation into a worker."""
    from api.structured_logging import get_request_id, get_session_id

    return (get_request_id(), get_session_id())


def _read_runtime_demand() -> tuple[int, int, bool, bool]:
    """Return the worker-visible adaptive-parallelism runtime state."""
    from core.task_parallelism_runtime import (
        current_demand_snapshot_path,
        read_outer_demand,
    )
    snapshot_path = current_demand_snapshot_path()
    state = read_outer_demand(snapshot_path, fallback_outer_workers=99)
    return (
        state.outer_demand,
        state.outer_max_workers,
        state.snapshot_fallback,
        snapshot_path is not None,
    )




def _return_mapping() -> dict[str, str]:
    """Return a mutable worker result for timing metadata tests."""
    return {"status": "ok"}


def _return_mapping_with_reserved_key() -> dict[str, object]:
    """Return a mapping that must remain byte-for-byte caller-owned."""
    return {
        "status": "ok",
        "_worker_pool_timing": {"worker_owned": True},
    }


# ---------------------------------------------------------------------------
# Lifecycle tests
# ---------------------------------------------------------------------------

class TestWorkerPoolLifecycle:
    """Test start/shutdown/is_alive behavior."""

    def test_not_alive_before_start(self) -> None:
        pool = WorkerPoolManager(max_workers=2)
        try:
            assert pool.is_alive is False
            assert pool.demand_snapshot_path.is_file()
            assert pool.outstanding_tasks == 0
        finally:
            pool.shutdown(wait=True)

    def test_demand_init_failure_keeps_optional_telemetry_unavailable(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        target_logger = logging.getLogger("lumina.api.worker_pool")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)
        with patch(
            "api.worker_pool.OuterDemandPublisher",
            side_effect=OSError("injected demand init failure"),
        ):
            pool = WorkerPoolManager(max_workers=2)

        assert pool.demand_snapshot_path is None
        assert pool.outstanding_tasks == 0
        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None)
            == "worker_pool_demand_init_failed"
        ]
        assert len(records) == 1
        assert records[0].error_type == "OSError"
        assert records[0].error_message
        pool.shutdown(wait=True)

    def test_manager_demand_paths_are_unique_and_shutdown_removes_them(
        self,
    ) -> None:
        first = WorkerPoolManager(max_workers=2)
        second = WorkerPoolManager(max_workers=2)
        first_path = first.demand_snapshot_path
        second_path = second.demand_snapshot_path

        assert first_path != second_path
        assert first_path.is_file()
        assert second_path.is_file()

        first.shutdown()
        first.shutdown()
        second.shutdown()

        assert not first_path.exists()
        assert not second_path.exists()
        assert not first_path.parent.exists()
        assert not second_path.parent.exists()

    def test_alive_after_start(self) -> None:
        pool = WorkerPoolManager(max_workers=2)
        pool.start()
        try:
            assert pool.is_alive is True
        finally:
            pool.shutdown(wait=True)

    def test_start_is_idempotent_when_pool_is_already_alive(self) -> None:
        pool = WorkerPoolManager(max_workers=2)
        with patch("api.worker_pool._IsolatedProcessExecutor") as executor_cls:
            pool.start()
            first_pool = pool._pool
            pool.start()
            assert pool._pool is first_pool
            executor_cls.assert_called_once()
            pool.shutdown(wait=False)

    def test_not_alive_after_shutdown(self) -> None:
        pool = WorkerPoolManager(max_workers=2)
        snapshot_path = pool.demand_snapshot_path
        pool.start()
        pool.shutdown(wait=True)
        assert pool.is_alive is False
        assert not snapshot_path.exists()

    def test_shutdown_without_start_is_noop(self) -> None:
        pool = WorkerPoolManager(max_workers=2)
        snapshot_path = pool.demand_snapshot_path
        pool.shutdown(wait=True)  # Should not raise
        assert pool.is_alive is False
        assert not snapshot_path.exists()

    def test_double_shutdown_is_safe(self) -> None:
        pool = WorkerPoolManager(max_workers=2)
        pool.start()
        pool.shutdown(wait=True)
        pool.shutdown(wait=True)  # Should not raise
        assert pool.is_alive is False

    def test_start_after_shutdown_creates_fresh_demand_state(self) -> None:
        pool = WorkerPoolManager(max_workers=1)
        first_path = pool.demand_snapshot_path
        pool.shutdown(wait=True)

        pool.start()
        second_path = pool.demand_snapshot_path
        try:
            assert pool.is_alive is True
            assert second_path != first_path
            assert second_path.is_file()
        finally:
            pool.shutdown(wait=True)

    def test_demand_cleanup_failure_is_logged_without_raising(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        target_logger = logging.getLogger("lumina.api.worker_pool")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)
        pool = WorkerPoolManager(max_workers=1)
        publisher = pool._demand_publisher
        original_cleanup = publisher.cleanup

        def fail_cleanup() -> None:
            raise OSError("injected cleanup failure")

        monkeypatch.setattr(publisher, "cleanup", fail_cleanup)
        try:
            pool.shutdown(wait=True)
            records = [
                record
                for record in caplog.records
                if getattr(record, "event", None)
                == "worker_pool_demand_cleanup_failed"
            ]
            assert len(records) == 1
            assert records[0].error_type == "OSError"
            assert records[0].error_message
            assert records[0].path
        finally:
            original_cleanup()


# ---------------------------------------------------------------------------
# max_workers tests
# ---------------------------------------------------------------------------

class TestMaxWorkers:
    """Test max_workers default and explicit values."""

    def test_explicit_max_workers(self) -> None:
        pool = WorkerPoolManager(max_workers=3)
        assert pool.max_workers == 3

    def test_negative_worker_count_is_rejected_at_start(self) -> None:
        pool = WorkerPoolManager(max_workers=-1)
        try:
            with pytest.raises(ValueError, match="max_workers"):
                pool.start()
            assert not pool.is_alive
        finally:
            pool.shutdown()

    def test_default_max_workers(self) -> None:
        pool = WorkerPoolManager()
        expected = min(os.cpu_count() or 2, 4)
        assert pool.max_workers == expected

    def test_none_max_workers_uses_default(self) -> None:
        pool = WorkerPoolManager(max_workers=None)
        expected = min(os.cpu_count() or 2, 4)
        assert pool.max_workers == expected





class TestWorkerPoolConfigEnvValidation:
    """Validate env override parsing for worker pool config."""

    def test_invalid_max_workers_falls_back_and_logs_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("LUMINA_MAX_WORKERS", "abc")
        target_logger = logging.getLogger("lumina.config")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)

        cfg = WorkerPoolConfig.from_env()

        assert cfg.MAX_WORKERS == WorkerPoolConfig.MAX_WORKERS
        warnings = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "worker_pool_max_workers_invalid"
        ]
        assert len(warnings) == 1
        assert getattr(warnings[0], "env_var", None) == "LUMINA_MAX_WORKERS"
        assert getattr(warnings[0], "raw_value", None) == "abc"
        assert getattr(warnings[0], "fallback", None) == WorkerPoolConfig.MAX_WORKERS
        assert getattr(warnings[0], "error_type", None) == "ValueError"
        assert getattr(warnings[0], "error_message", None)


    @pytest.mark.parametrize("raw_value", ["0", "-2"])
    def test_non_positive_max_workers_falls_back_and_logs_warning(
        self,
        raw_value: str,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("LUMINA_MAX_WORKERS", raw_value)
        target_logger = logging.getLogger("lumina.config")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)

        cfg = WorkerPoolConfig.from_env()

        assert cfg.MAX_WORKERS == WorkerPoolConfig.MAX_WORKERS
        warnings = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "worker_pool_max_workers_invalid"
        ]
        assert len(warnings) == 1
        assert getattr(warnings[0], "raw_value", None) == raw_value
        assert getattr(warnings[0], "fallback", None) == WorkerPoolConfig.MAX_WORKERS





# ---------------------------------------------------------------------------
# submit tests
# ---------------------------------------------------------------------------

class TestSubmit:
    """Test async submit behavior."""

    @pytest.mark.asyncio
    async def test_synchronous_submit_failure_restarts_pool_and_cleans_demand(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A submit-time executor failure keeps its error and does not leak demand."""

        real_executor = worker_pool.ProcessPoolExecutor
        factory_calls = 0

        class _FailingExecutor:
            _processes: dict = {}

            def submit(self, *_args, **_kwargs):
                raise OSError("synchronous submit failure")

            def shutdown(self, **_kwargs):
                return None

        def _factory(**kwargs):
            nonlocal factory_calls
            factory_calls += 1
            if factory_calls == 1:
                return _FailingExecutor()
            return real_executor(**kwargs)

        monkeypatch.setattr(worker_pool, "ProcessPoolExecutor", _factory)
        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        try:
            with pytest.raises(OSError, match="synchronous submit failure"):
                await pool.submit(_add, 1, 2)
            assert pool.outstanding_tasks == 0
            assert await pool.submit(_add, 2, 3) == 5
        finally:
            pool.shutdown(wait=True)

    @pytest.mark.asyncio
    async def test_submit_returns_result(self) -> None:
        pool = WorkerPoolManager(max_workers=2)
        pool.start()
        try:
            result = await pool.submit(_add, 3, 7)
            assert result == 10
        finally:
            pool.shutdown(wait=True)

    @pytest.mark.asyncio
    async def test_worker_receives_live_demand_snapshot_path(self) -> None:
        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        try:
            assert await pool.submit(_read_runtime_demand) == (
                1,
                1,
                False,
                True,
            )
        finally:
            pool.shutdown(wait=True)












    @pytest.mark.asyncio
    async def test_concurrent_submissions_publish_running_and_queued_demand(
        self,
    ) -> None:
        pool = WorkerPoolManager(max_workers=2)
        pool.start()
        first = asyncio.create_task(pool.submit(_slow_task, 0.15))
        second = asyncio.create_task(pool.submit(_slow_task, 0.15))
        try:
            await asyncio.sleep(0.04)
            payload = json.loads(
                pool.demand_snapshot_path.read_text(encoding="utf-8")
            )
            assert payload["outstanding"] == 2
            assert pool.outstanding_tasks == 2
            assert await asyncio.gather(first, second) == ["done", "done"]
            assert pool.outstanding_tasks == 0
        finally:
            pool.shutdown(wait=True)

    @pytest.mark.asyncio
    async def test_submit_does_not_mutate_or_overwrite_mapping_results(
        self,
    ) -> None:
        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        try:
            result = await pool.submit(_return_mapping_with_reserved_key)
        finally:
            pool.shutdown(wait=True)

        assert result == {
            "status": "ok",
            "_worker_pool_timing": {"worker_owned": True},
        }

    @pytest.mark.asyncio
    async def test_submit_timed_returns_bounded_timing_without_info_log(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        target_logger = logging.getLogger("lumina.api.worker_pool")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.DEBUG, logger=target_logger.name)
        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        try:
            result, timing = await pool.submit_timed(_return_mapping)
        finally:
            pool.shutdown(wait=True)

        assert result == {"status": "ok"}
        assert set(timing) == {
            "queue_wait_s",
            "worker_execution_s",
            "result_delivery_s",
            "pool_roundtrip_s",
        }
        assert all(float(value) >= 0.0 for value in timing.values())
        assert timing["pool_roundtrip_s"] >= timing["worker_execution_s"]

        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "worker_pool_task_timing"
        ]
        assert len(records) == 1
        assert records[0].levelno == logging.DEBUG

    @pytest.mark.asyncio
    async def test_submit_raises_runtime_error_when_not_started(self) -> None:
        pool = WorkerPoolManager(max_workers=2)
        with pytest.raises(RuntimeError, match="WorkerPool not started"):
            await pool.submit(_add, 1, 2)

    @pytest.mark.asyncio
    async def test_submit_propagates_worker_exception(self) -> None:
        """Worker exceptions should propagate to the caller."""
        pool = WorkerPoolManager(max_workers=2)
        pool.start()
        try:
            with pytest.raises(ValueError, match="test error"):
                await pool.submit(_raise_value_error, "test error")
            assert pool.outstanding_tasks == 0
            payload = json.loads(
                pool.demand_snapshot_path.read_text(encoding="utf-8")
            )
            assert payload["outstanding"] == 0
        finally:
            pool.shutdown(wait=True)


    @pytest.mark.asyncio
    async def test_cancelled_submission_keeps_demand_until_worker_finishes(
        self,
    ) -> None:
        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        task = asyncio.create_task(pool.submit(_slow_task, 0.3))
        try:
            await asyncio.sleep(0.04)
            assert pool.outstanding_tasks == 1
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert pool.outstanding_tasks == 1
            for _ in range(100):
                if pool.outstanding_tasks == 0:
                    break
                await asyncio.sleep(0.01)
            assert pool.outstanding_tasks == 0
        finally:
            pool.shutdown(wait=True)


    @pytest.mark.asyncio
    async def test_demand_publish_failure_does_not_change_task_result(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        target_logger = logging.getLogger("lumina.api.worker_pool")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)
        pool = WorkerPoolManager(max_workers=1)
        pool.start()

        def fail_publish() -> None:
            raise OSError("injected demand write failure")

        monkeypatch.setattr(
            pool._demand_publisher,
            "_publish_locked",
            fail_publish,
        )
        try:
            assert await pool.submit(_add, 4, 5) == 9
            records = [
                record
                for record in caplog.records
                if getattr(record, "event", None)
                == "worker_pool_demand_update_failed"
            ]
            assert len(records) == 2
            assert {record.operation for record in records} == {
                "increment",
                "decrement",
            }
            assert all(record.error_type == "OSError" for record in records)
            assert all(record.error_message for record in records)
            assert all(record.path for record in records)
        finally:
            pool.shutdown(wait=True)

class TestContextvarPropagation:
    """Verify request_id / session_id flow into the worker process."""

    @pytest.mark.asyncio
    async def test_submit_propagates_request_id_and_session_id(self) -> None:
        from api.structured_logging import (
            reset_request_id,
            reset_session_id,
            set_request_id,
            set_session_id,
        )

        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        request_token = set_request_id("req-round2-abc")
        session_token = set_session_id("sess-round2-xyz")
        try:
            result = await pool.submit(_read_context_ids)
            assert result == ("req-round2-abc", "sess-round2-xyz")
        finally:
            reset_session_id(session_token)
            reset_request_id(request_token)
            pool.shutdown(wait=True)

    @pytest.mark.asyncio
    async def test_submit_passes_none_when_parent_has_no_ids(self) -> None:
        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        try:
            result = await pool.submit(_read_context_ids)
            assert result == (None, None)
        finally:
            pool.shutdown(wait=True)


class TestSubmitIsTransparentToParentContext:
    """submit() must not silently bind a new session_id on the parent context."""

    @pytest.mark.asyncio
    async def test_submit_leaves_parent_session_id_none_when_unset(self) -> None:
        from api.structured_logging import get_session_id

        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        try:
            assert get_session_id() is None
            await pool.submit(_add, 1, 2)
            assert get_session_id() is None
        finally:
            pool.shutdown(wait=True)

    @pytest.mark.asyncio
    async def test_submit_preserves_parent_session_id_when_set(self) -> None:
        from api.structured_logging import (
            get_session_id,
            reset_session_id,
            set_session_id,
        )

        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        token = set_session_id("parent-sess-explicit")
        try:
            await pool.submit(_add, 1, 2)
            assert get_session_id() == "parent-sess-explicit"
        finally:
            reset_session_id(token)
            pool.shutdown(wait=True)


class TestRunInWorkerWithContext:
    """Unit-test the wrapper without spawning subprocesses."""

    def test_wrapper_sets_request_id_before_invoking_fn(self) -> None:
        from api.worker_pool import _run_in_worker_with_context
        from api.structured_logging import get_request_id, get_session_id

        captured: dict[str, str | None] = {}

        def _capture(*_args: object) -> None:
            captured["request_id"] = get_request_id()
            captured["session_id"] = get_session_id()

        _run_in_worker_with_context(
            _capture,
            "req-direct",
            "sess-direct",
            "/tmp/lumina-demand-test.json",
            None,
        )
        assert captured == {"request_id": "req-direct", "session_id": "sess-direct"}

    def test_wrapper_skips_set_when_ids_are_none(self) -> None:
        from api.worker_pool import _run_in_worker_with_context
        from api.structured_logging import (
            get_request_id,
            get_session_id,
            reset_request_id,
            reset_session_id,
            set_request_id,
            set_session_id,
        )

        outer_request = set_request_id("outer-req")
        outer_session = set_session_id("outer-sess")
        try:
            captured: dict[str, str | None] = {}

            def _capture(*_args: object) -> None:
                captured["request_id"] = get_request_id()
                captured["session_id"] = get_session_id()

            _run_in_worker_with_context(
                _capture,
                None,
                None,
                "/tmp/lumina-demand-test.json",
            )
            assert captured == {"request_id": "outer-req", "session_id": "outer-sess"}
        finally:
            reset_session_id(outer_session)
            reset_request_id(outer_request)

    def test_wrapper_returns_fn_result(self) -> None:
        from api.worker_pool import _run_in_worker_with_context

        def _add_local(a: int, b: int) -> int:
            return a + b

        assert (
            _run_in_worker_with_context(
                _add_local,
                "rid",
                "sid",
                "/tmp/lumina-demand-test.json",
                2,
                3,
            )
            == 5
        )

    def test_wrapper_installs_and_restores_worker_lease_path(self) -> None:
        from api.worker_pool import _run_in_worker_with_context
        from core.task_parallelism_runtime import (
            current_demand_snapshot_path,
            current_worker_lease_path,
        )

        observed: list[tuple[Path | None, Path | None]] = []

        def capture_paths() -> None:
            observed.append(
                (current_demand_snapshot_path(), current_worker_lease_path())
            )

        assert current_worker_lease_path() is None
        _run_in_worker_with_context(
            capture_paths,
            None,
            None,
            "/tmp/lumina-demand-test.json",
            worker_lease_path="/tmp/lumina-workers-test.json",
        )

        assert observed == [
            (
                Path("/tmp/lumina-demand-test.json"),
                Path("/tmp/lumina-workers-test.json"),
            )
        ]
        assert current_worker_lease_path() is None

    def test_wrapper_installs_and_restores_demand_path(self) -> None:
        from api.worker_pool import _run_in_worker_with_context
        from core.task_parallelism_runtime import current_demand_snapshot_path

        observed: list[Path | None] = []

        def capture_path() -> None:
            observed.append(current_demand_snapshot_path())

        assert current_demand_snapshot_path() is None
        _run_in_worker_with_context(
            capture_path,
            None,
            None,
            "/tmp/lumina-demand-test.json",
        )

        assert observed == [Path("/tmp/lumina-demand-test.json")]
        assert current_demand_snapshot_path() is None


# ---------------------------------------------------------------------------
# max_tasks_per_child tests (worker recycling for long-running RSS bounds)
# ---------------------------------------------------------------------------

class TestMaxTasksPerChild:
    """Test LUMINA_WORKER_MAX_TASKS_PER_CHILD env var resolution and propagation.
    LUMINA_WORKER_MAX_TASKS_PER_CHILD 环境变量解析与传递测试.

    Validates env-driven worker recycling configuration that bounds
    long-running RSS growth in production.
    验证环境变量驱动的 worker 进程回收配置, 用于在生产长跑场景下
    限制 RSS 单调增长.
    """

    def test_default_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", raising=False)
        pool = WorkerPoolManager(max_workers=2)
        expected = 1 if worker_pool.sys.platform == "darwin" else 20
        assert pool.max_tasks_per_child == expected

    def test_default_is_1_on_darwin_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", raising=False)
        monkeypatch.setattr(worker_pool.sys, "platform", "darwin")
        pool = WorkerPoolManager(max_workers=2)
        assert pool.max_tasks_per_child == 1

    def test_default_is_20_off_darwin_when_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", raising=False)
        monkeypatch.setattr(worker_pool.sys, "platform", "linux")
        pool = WorkerPoolManager(max_workers=2)
        assert pool.max_tasks_per_child == 20

    def test_env_var_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", "5")
        pool = WorkerPoolManager(max_workers=2)
        assert pool.max_tasks_per_child == 5

    def test_env_zero_disables_recycling(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", "0")
        pool = WorkerPoolManager(max_workers=2)
        assert pool.max_tasks_per_child is None

    def test_env_invalid_falls_back_to_default(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", "abc")
        target_logger = logging.getLogger("lumina.api.worker_pool")
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=target_logger.name)

        pool = WorkerPoolManager(max_workers=2)

        expected = 1 if worker_pool.sys.platform == "darwin" else 20
        assert pool.max_tasks_per_child == expected
        warnings = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "worker_pool_max_tasks_invalid"
        ]
        assert len(warnings) == 1
        assert getattr(warnings[0], "raw_value", None) == "abc"
        assert getattr(warnings[0], "fallback", None) == expected
        assert getattr(warnings[0], "error_type", None) == "ValueError"
        assert getattr(warnings[0], "error_message", None)

    def test_each_slot_keeps_the_configured_child_recycling(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("LUMINA_WORKER_MAX_TASKS_PER_CHILD", "20")
        pool = WorkerPoolManager(max_workers=3)

        async def run() -> None:
            assert await asyncio.gather(*(
                pool.submit(_slow_task, 0.05) for _ in range(3)
            )) == ["done"] * 3

        with patch(
            "api.worker_pool.ProcessPoolExecutor",
            wraps=worker_pool.ProcessPoolExecutor,
        ) as executor_cls:
            pool.start()
            try:
                asyncio.run(run())
            finally:
                pool.shutdown(wait=True)
        assert executor_cls.call_count == 3
        for call in executor_cls.call_args_list:
            assert call.kwargs["max_workers"] == 1
            assert call.kwargs["max_tasks_per_child"] == 20
            assert call.kwargs["mp_context"].get_start_method() == "spawn"
