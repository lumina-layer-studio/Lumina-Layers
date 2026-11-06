"""WorkerPoolManager — ProcessPoolExecutor lifecycle manager.
WorkerPoolManager — ProcessPoolExecutor 生命周期管理器。

Provides an async-friendly interface for submitting CPU-bound tasks
to a process pool with graceful shutdown.
提供异步友好的接口，将 CPU 密集型任务提交到进程池并优雅关闭。
"""

from concurrent.futures import CancelledError as FutureCancelledError
from concurrent.futures import Future as ConcurrentFuture
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from multiprocessing.connection import wait as wait_for_process_exit
from pathlib import Path
from typing import Any, Callable, Literal, TypeVar
import asyncio
import os
import sys
import threading
import time
import uuid

from api.structured_logging import get_logger
from core.task_parallelism_runtime import (
    OuterDemandPublisher,
    task_parallelism_runtime_scope,
)

T = TypeVar("T")

_log = get_logger(__name__)

_ENV_MAX_TASKS_PER_CHILD = "LUMINA_WORKER_MAX_TASKS_PER_CHILD"
_DEFAULT_MAX_TASKS_PER_CHILD = 20
_DARWIN_DEFAULT_MAX_TASKS_PER_CHILD = 1
_TERMINATE_GRACE_SECONDS = 1.0
@dataclass
class _LifecycleWaiter:
    loop: asyncio.AbstractEventLoop
    event: asyncio.Event


@dataclass
class _ExecutorGeneration:
    """One concrete executor generation and its submission resources."""

    generation_id: int
    epoch: int
    executor: Any
    demand_publisher: OuterDemandPublisher | None
    worker_lease_path: str | None
    accepting: bool = True


def _default_max_tasks_per_child() -> int:
    return _DARWIN_DEFAULT_MAX_TASKS_PER_CHILD if sys.platform == "darwin" else _DEFAULT_MAX_TASKS_PER_CHILD


def _resolve_max_tasks_per_child() -> int | None:
    """Resolve LUMINA_WORKER_MAX_TASKS_PER_CHILD into a ProcessPoolExecutor arg.
    解析 LUMINA_WORKER_MAX_TASKS_PER_CHILD 环境变量为 ProcessPoolExecutor 参数.

    Behavior:
        - Unset / empty: returns the platform default.
        - Positive int: returns that value (custom recycle threshold).
        - 0 or negative: returns ``None`` (disable recycling, preserve old behavior).
        - Invalid (non-int): emits a structured WARNING and returns the default.

    行为:
        - 未设置或为空: 返回平台默认值.
        - 正整数: 返回该值 (自定义回收阈值).
        - 0 或负数: 返回 None (禁用回收, 保留旧行为).
        - 非法值 (非整数): 打结构化 WARNING 后回退到默认值.

    Returns:
        int | None: The ``max_tasks_per_child`` argument for ``ProcessPoolExecutor``.
                    (传给 ``ProcessPoolExecutor`` 的 ``max_tasks_per_child`` 参数)
    """
    raw = os.environ.get(_ENV_MAX_TASKS_PER_CHILD)
    fallback = _default_max_tasks_per_child()
    if raw is None or raw == "":
        return fallback
    try:
        value = int(raw)
    except ValueError:
        _log.warning(
            "Invalid LUMINA_WORKER_MAX_TASKS_PER_CHILD value; falling back to default",
            extra={
                "event": "worker_pool_max_tasks_invalid",
                "raw_value": raw,
                "error_type": "ValueError",
                "error_message": (
                    f"{_ENV_MAX_TASKS_PER_CHILD} must be an integer; got {raw!r}"
                ),
                "fallback": fallback,
            },
        )
        return fallback
    if value <= 0:
        return None
    return value


def _normalize_windows_output_stream(stream: Any) -> Any:
    """Return a writable UTF-8 stream for a Windows worker process.

    Workers inherit the parent's log path and normalize console encoding.
    """

    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass
    return stream


def _worker_init() -> None:
    """Initialize worker logging with UTF-8 streams and the parent's log path.
    初始化 worker 日志，使用 UTF-8 输出流并继承父进程的日志路径。
    """
    if sys.platform == "win32":
        sys.stdout = _normalize_windows_output_stream(sys.stdout)
        sys.stderr = _normalize_windows_output_stream(sys.stderr)

    from api.logger import setup_file_logging
    from api.structured_logging import configure_structured_logging

    log_path = os.environ.get("LUMINA_LOG_PATH")
    if log_path:
        setup_file_logging(log_path=log_path)
    configure_structured_logging()


def _run_in_worker_with_context(
    fn: Callable[..., T],
    request_id: str | None,
    session_id: str | None,
    demand_snapshot_path: str | None,
    *args: Any,
    worker_lease_path: str | None = None,
) -> T:
    """Replay parent context and CPU parallelism telemetry in the worker."""

    from api.structured_logging import set_request_id, set_session_id

    if request_id is not None:
        set_request_id(request_id)
    if session_id is not None:
        set_session_id(session_id)
    if demand_snapshot_path is None:
        return fn(*args)
    with task_parallelism_runtime_scope(demand_snapshot_path, worker_lease_path):
        return fn(*args)


def _run_in_worker_with_context_timed(
    fn: Callable[..., T],
    request_id: str | None,
    session_id: str | None,
    demand_snapshot_path: str | None,
    *args: Any,
    worker_lease_path: str | None = None,
) -> tuple[T, int, int]:
    """Run one contextualized worker task and return timing bounds."""

    worker_started_ns = time.perf_counter_ns()
    result = _run_in_worker_with_context(
        fn,
        request_id,
        session_id,
        demand_snapshot_path,
        *args,
        worker_lease_path=worker_lease_path,
    )
    worker_finished_ns = time.perf_counter_ns()
    return result, worker_started_ns, worker_finished_ns


def _shutdown_executor(
    executor: ProcessPoolExecutor,
    *,
    wait: bool,
    cancel_futures: bool,
) -> None:
    """Shutdown a process executor while supporting older Python signatures."""

    try:
        executor.shutdown(wait=wait, cancel_futures=cancel_futures)
    except TypeError:
        executor.shutdown(wait=wait)


def _terminate_executor_workers(
    executor: ProcessPoolExecutor,
) -> tuple[int, int]:
    """Terminate worker processes owned by a ProcessPoolExecutor.

    This is used only while cleaning up a failed executor generation. It is
    deliberately separate from the lifetime of a user computation.
    这里只在清理已经失败的 executor 世代时使用，不限制用户计算的运行时长。
    """

    processes = getattr(executor, "_processes", None)
    if not processes:
        return 0, 0

    terminated = 0
    survivors = 0
    for proc in list(processes.values()):
        if proc is None:
            continue
        try:
            # The executor's manager thread owns join()/waitpid(). Calling
            # either here races that thread while it handles BrokenProcessPool,
            # and can leave an exited process reporting is_alive() forever.
            # The process sentinel independently confirms OS-level exit.
            sentinel = proc.sentinel
            if wait_for_process_exit([sentinel], timeout=0):
                continue
            proc.terminate()
            exited = bool(wait_for_process_exit(
                [sentinel], timeout=_TERMINATE_GRACE_SECONDS,
            ))
            if not exited:
                kill = getattr(proc, "kill", None)
                if callable(kill):
                    kill()
                    exited = bool(wait_for_process_exit(
                        [sentinel], timeout=_TERMINATE_GRACE_SECONDS,
                    ))
            if not exited:
                survivors += 1
                _log.error(
                    "Worker process survived terminate and kill",
                    extra={
                        "event": "worker_pool_process_terminate_failed",
                        "pid": getattr(proc, "pid", None),
                        "error_type": "WorkerStillAlive",
                        "error_message": (
                            "Worker process is still alive after terminate/kill"
                        ),
                    },
                )
            else:
                terminated += 1
        except (OSError, RuntimeError, ValueError) as exc:
            try:
                still_alive = not bool(wait_for_process_exit(
                    [proc.sentinel], timeout=0,
                ))
            except (OSError, RuntimeError, ValueError):
                still_alive = True
            survivors += int(still_alive)
            _log.warning(
                "Failed to terminate a worker in the broken executor",
                extra={
                    "event": "worker_pool_process_terminate_failed",
                    "pid": getattr(proc, "pid", None),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )
    return terminated, survivors


class WorkerPoolManager:
    """Manage a ProcessPoolExecutor for CPU-bound tasks.
    管理用于 CPU 密集型任务的进程池。

    Attributes:
        _max_workers (int): Maximum number of worker processes. (最大工作进程数)
        _max_tasks_per_child (int | None): Tasks each child handles before being
            recycled, or ``None`` to disable recycling.
            (每个子进程被回收前可处理的任务数，``None`` 表示禁用回收)
        _pool (ProcessPoolExecutor | None): The underlying executor. (底层执行器)
    """

    def __init__(
        self,
        max_workers: int | None = None,
    ) -> None:
        """Initialize the CPU worker pool without application resource quotas.

        初始化仅负责 CPU worker 池；桌面任务不再经过内存额度审批或计算时限。
        """
        self._max_workers: int = max_workers or min(os.cpu_count() or 2, 4)
        self._max_tasks_per_child: int | None = _resolve_max_tasks_per_child()
        self._pool: ProcessPoolExecutor | None = None
        self._pool_lock = threading.RLock()
        self._service_epoch = 0
        self._service_open = False
        self._restart_start_pending = False
        self._restart_in_progress = False
        self._generation_counter = 0
        self._generation: _ExecutorGeneration | None = None
        self._lifecycle_waiters: list[_LifecycleWaiter] = []
        self._publisher_cleanup_pending = False
        self._demand_publisher: OuterDemandPublisher | None = (
            self._create_demand_publisher()
        )
        self._active_task_lock = threading.Lock()
        self._active_tasks: dict[
            str,
            tuple[object, OuterDemandPublisher | None],
        ] = {}

    def _signal_lifecycle_locked(self) -> None:
        """Wake submissions waiting for an executor lifecycle transition."""

        for waiter in tuple(self._lifecycle_waiters):
            try:
                waiter.loop.call_soon_threadsafe(waiter.event.set)
            except RuntimeError:
                pass

    def _current_generation_locked(self) -> _ExecutorGeneration | None:
        """Return the formally published current generation, if any."""

        generation = self._generation
        if generation is not None and generation.executor is self._pool:
            return generation
        return None

    async def _wait_for_generation(
        self,
        request_epoch: int,
    ) -> None:
        """Wait for an accepting executor generation without polling."""

        loop = asyncio.get_running_loop()
        waiter = _LifecycleWaiter(loop, asyncio.Event())
        with self._pool_lock:
            generation = self._current_generation_locked()
            if self._service_epoch != request_epoch:
                raise RuntimeError("WorkerPool request epoch is closed")
            if generation is not None and generation.accepting:
                return
            if not self._service_open:
                raise RuntimeError("WorkerPool not started")
            self._lifecycle_waiters.append(waiter)
        try:
            await waiter.event.wait()
        finally:
            with self._pool_lock:
                if waiter in self._lifecycle_waiters:
                    self._lifecycle_waiters.remove(waiter)

    def _create_demand_publisher(self) -> OuterDemandPublisher | None:
        """Create isolated demand state without making it a startup dependency."""

        try:
            return OuterDemandPublisher(max_workers=self._max_workers)
        except (OSError, RuntimeError, ValueError) as exc:
            _log.warning(
                "Failed to initialize worker-pool demand state",
                extra={
                    "event": "worker_pool_demand_init_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "max_workers": self._max_workers,
                },
            )
            return None

    def _update_demand(
        self,
        publisher: OuterDemandPublisher | None,
        operation: Literal["increment", "decrement"],
    ) -> None:
        """Publish one demand transition without changing task outcomes."""

        if publisher is None:
            return
        try:
            getattr(publisher, operation)()
        except (OSError, RuntimeError, ValueError) as exc:
            _log.warning(
                "Failed to publish worker-pool demand",
                extra={
                    "event": "worker_pool_demand_update_failed",
                    "operation": operation,
                    "path": str(publisher.snapshot_path),
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )

    def _register_active_task(
        self,
        *,
        owner: object,
        publisher: OuterDemandPublisher | None,
    ) -> str:
        """Track one executor task until its underlying work is truly done."""

        token = uuid.uuid4().hex
        with self._active_task_lock:
            self._active_tasks[token] = (
                owner,
                publisher,
            )
        self._update_demand(publisher, "increment")
        return token

    def _complete_active_task(self, token: str) -> None:
        """Idempotently release demand for one finished task."""

        with self._active_task_lock:
            state = self._active_tasks.pop(token, None)
        if state is None:
            return
        _owner, publisher = state
        self._update_demand(publisher, "decrement")
        self._maybe_cleanup_publisher()

    def _complete_executor_generation(
        self,
        owner: _ExecutorGeneration,
    ) -> None:
        """Complete every task owned by an executor confirmed to be stopped."""

        with self._active_task_lock:
            tokens = [
                token
                for token, (task_owner, _publisher) in (
                    self._active_tasks.items()
                )
                if task_owner is owner
            ]
        for token in tokens:
            self._complete_active_task(token)

    def start(self) -> None:
        """Initialize the process pool.
        初始化进程池。
        """
        with self._pool_lock:
            if self._restart_in_progress:
                return
            if self._restart_start_pending and not self._service_open:
                self._restart_start_pending = False
                return
            generation = self._current_generation_locked()
            if generation is not None and generation.accepting:
                return
            preserve_epoch = self._restart_start_pending
            self._restart_start_pending = False
            if not preserve_epoch:
                self._service_epoch += 1
            self._service_open = True
            if self._demand_publisher is None:
                self._demand_publisher = self._create_demand_publisher()
            executor = ProcessPoolExecutor(
                max_workers=self._max_workers,
                initializer=_worker_init,
                max_tasks_per_child=self._max_tasks_per_child,
            )
            self._generation_counter += 1
            self._pool = executor
            self._generation = _ExecutorGeneration(
                generation_id=self._generation_counter,
                epoch=self._service_epoch,
                executor=executor,
                demand_publisher=self._demand_publisher,
                worker_lease_path=(
                    str(self._demand_publisher.worker_lease_path)
                    if self._demand_publisher is not None
                    else None
                ),
            )
            self._signal_lifecycle_locked()

    def _restart_after_failed_pool(
        self,
        failed_pool: ProcessPoolExecutor,
        *,
        reason: str,
    ) -> None:
        """Replace a failed executor with a fresh process pool."""

        error_message = f"Worker pool restarted after {reason}"
        with self._pool_lock:
            generation = self._current_generation_locked()
            if generation is None or generation.executor is not failed_pool:
                return
            if not self._service_open:
                return
            generation.accepting = False
            restart_epoch = self._service_epoch
            self._restart_in_progress = True
            self._pool = None
            self._signal_lifecycle_locked()

        terminated, surviving_workers = _terminate_executor_workers(
            failed_pool
        )
        _shutdown_executor(failed_pool, wait=False, cancel_futures=True)
        if surviving_workers == 0:
            self._complete_executor_generation(generation)

        restarted = False
        with self._pool_lock:
            current_epoch_open = (
                self._service_open and self._service_epoch == restart_epoch
            )
            if current_epoch_open and self._pool is None:
                self._generation = None
                self._restart_start_pending = True
                restarted = True
            else:
                if self._pool is None:
                    self._generation = None
                self._restart_start_pending = False
            self._restart_in_progress = False
            self._signal_lifecycle_locked()
        if restarted:
            try:
                self.start()
            except Exception as exc:
                with self._pool_lock:
                    if self._service_epoch == restart_epoch:
                        self._service_open = False
                        self._restart_start_pending = False
                        self._signal_lifecycle_locked()
                _log.error(
                    "Worker pool restart failed",
                    extra={
                        "event": "worker_pool_restart_failed",
                        "reason": reason,
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
            else:
                _log.warning(
                    "Worker pool restarted after failed task",
                    extra={
                        "event": "worker_pool_restarted",
                        "reason": reason,
                        "terminated_workers": terminated,
                        "surviving_workers": surviving_workers,
                        "max_workers": self._max_workers,
                        "error_type": reason,
                        "error_message": error_message,
                    },
                )

    async def submit(
        self,
        fn: Callable[..., T],
        *args: Any,
    ) -> T:
        """Submit a CPU task and await its result without an application quota."""

        result, _timing = await self._submit_internal(
            fn,
            args,
            include_timing=False,
        )
        return result

    async def submit_timed(
        self,
        fn: Callable[..., T],
        *args: Any,
    ) -> tuple[T, dict[str, float]]:
        """Submit a CPU task and return executor timing metadata."""

        result, timing = await self._submit_internal(
            fn,
            args,
            include_timing=True,
        )
        if timing is None:
            raise RuntimeError("Timed worker submission returned no timing")
        return result, timing

    def _complete_future_task(
        self,
        completed: ConcurrentFuture[Any],
        task_token: str,
    ) -> None:
        """Complete a task unless a broken pool may still have a live worker."""

        if completed.cancelled():
            self._complete_active_task(task_token)
            return
        try:
            exception = completed.exception()
        except FutureCancelledError:
            self._complete_active_task(task_token)
            return
        if isinstance(exception, BrokenProcessPool):
            # CPython marks futures broken before it terminates every worker.
            # The restart path releases the executor generation only after all
            # known child processes are confirmed stopped.
            return
        self._complete_active_task(task_token)

    async def _await_generation_for_submit(
        self,
        request_epoch: int,
    ) -> _ExecutorGeneration:
        """Return a current accepting generation without binding before await."""

        while True:
            with self._pool_lock:
                generation = self._current_generation_locked()
                if self._service_epoch != request_epoch:
                    raise RuntimeError("WorkerPool request epoch is closed")
                if (
                    self._service_open
                    and generation is not None
                    and generation.accepting
                ):
                    return generation
                if not self._service_open:
                    raise RuntimeError("WorkerPool not started")
            await self._wait_for_generation(request_epoch)

    async def _submit_internal(
        self,
        fn: Callable[..., T],
        args: tuple[Any, ...],
        *,
        include_timing: bool,
    ) -> tuple[T, dict[str, float] | None]:
        """Submit work, preserving cancellation and real worker failures."""

        from api.structured_logging import get_request_id, get_session_id

        loop = asyncio.get_running_loop()
        request_id = get_request_id()
        session_id = get_session_id()
        worker_entry = (
            _run_in_worker_with_context_timed
            if include_timing
            else _run_in_worker_with_context
        )
        with self._pool_lock:
            initial_generation = self._current_generation_locked()
            if not self._service_open or initial_generation is None:
                raise RuntimeError("WorkerPool not started")
            request_epoch = self._service_epoch

        active_task_token: str | None = None
        executor_future: ConcurrentFuture[Any] | None = None
        submitted_generation: _ExecutorGeneration | None = None
        submission_uncertain = False
        submitted_ns = time.perf_counter_ns() if include_timing else None
        try:
            while True:
                generation = await self._await_generation_for_submit(
                    request_epoch,
                )
                with self._pool_lock:
                    current = self._current_generation_locked()
                    if (
                        not self._service_open
                        or self._service_epoch != request_epoch
                    ):
                        raise RuntimeError("WorkerPool request epoch is closed")
                    if (
                        current is None
                        or current is not generation
                        or not current.accepting
                    ):
                        continue
                    submitted_generation = current
                    publisher = current.demand_publisher
                    snapshot_path = (
                        str(publisher.snapshot_path)
                        if publisher is not None
                        else None
                    )
                    worker_lease_path = current.worker_lease_path
                    active_task_token = self._register_active_task(
                        owner=current,
                        publisher=publisher,
                    )
                    try:
                        executor_future = current.executor.submit(
                            worker_entry,
                            fn,
                            request_id,
                            session_id,
                            snapshot_path,
                            *args,
                            worker_lease_path=worker_lease_path,
                        )
                    except BaseException:
                        submission_uncertain = True
                        raise
                    try:
                        executor_future.add_done_callback(
                            lambda completed, token=active_task_token: (
                                self._complete_future_task(completed, token)
                            )
                        )
                    except BaseException:
                        submission_uncertain = True
                        raise
                    break

            if executor_future is None:
                raise RuntimeError("WorkerPool submission produced no future")
            future = asyncio.wrap_future(executor_future, loop=loop)
            raw_result = await asyncio.shield(future)
            if not include_timing:
                return raw_result, None
            result, worker_started_ns, worker_finished_ns = raw_result
            received_ns = time.perf_counter_ns()
            if submitted_ns is None:
                raise RuntimeError("Timed worker submission has no start time")
            timing = {
                "queue_wait_s": max(
                    0.0,
                    (worker_started_ns - submitted_ns) / 1_000_000_000,
                ),
                "worker_execution_s": max(
                    0.0,
                    (worker_finished_ns - worker_started_ns) / 1_000_000_000,
                ),
                "result_delivery_s": max(
                    0.0,
                    (received_ns - worker_finished_ns) / 1_000_000_000,
                ),
                "pool_roundtrip_s": max(
                    0.0,
                    (received_ns - submitted_ns) / 1_000_000_000,
                ),
            }
            _log.debug(
                "Worker pool task timing",
                extra={
                    "event": "worker_pool_task_timing",
                    "worker_name": getattr(fn, "__name__", type(fn).__name__),
                    **timing,
                },
            )
            return result, timing
        except BrokenProcessPool:
            if submitted_generation is not None:
                self._restart_after_failed_pool(
                    submitted_generation.executor,
                    reason="broken_process_pool",
                )
            raise
        except BaseException:
            if submission_uncertain and submitted_generation is not None:
                self._restart_after_failed_pool(
                    submitted_generation.executor,
                    reason="submit_failed",
                )
            elif active_task_token is not None and executor_future is None:
                self._complete_active_task(active_task_token)
            raise
        finally:
            if active_task_token is not None and executor_future is None:
                if not submission_uncertain:
                    self._complete_active_task(active_task_token)

    def _maybe_cleanup_publisher(self) -> None:
        """Remove telemetry files only after the last submitted task ends."""

        with self._active_task_lock:
            if self._active_tasks:
                return
        with self._pool_lock:
            if self._service_open or not self._publisher_cleanup_pending:
                return
            publisher = self._demand_publisher
            if publisher is None:
                self._publisher_cleanup_pending = False
                return
            try:
                publisher.cleanup()
            except (OSError, RuntimeError, ValueError) as exc:
                _log.warning(
                    "Failed to clean up worker-pool demand state",
                    extra={
                        "event": "worker_pool_demand_cleanup_failed",
                        "path": str(publisher.snapshot_path),
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )
            else:
                self._demand_publisher = None
                self._publisher_cleanup_pending = False

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the pool gracefully.
        优雅关闭进程池。

        Args:
            wait (bool): Whether to wait for pending tasks to complete.
                         (是否等待待处理任务完成)
        """
        with self._pool_lock:
            self._service_open = False
            self._service_epoch += 1
            self._restart_start_pending = False
            generation = self._current_generation_locked()
            if generation is not None:
                generation.accepting = False
            executor = self._pool
            self._pool = None
            self._generation = None
            self._publisher_cleanup_pending = self._demand_publisher is not None
            self._signal_lifecycle_locked()

        if executor is not None:
            _shutdown_executor(
                executor,
                wait=wait,
                cancel_futures=not wait,
            )
        if wait and generation is not None:
            self._complete_executor_generation(generation)
        self._maybe_cleanup_publisher()

    @property
    def is_alive(self) -> bool:
        """Check if the pool is running.
        检查进程池是否正在运行。

        Returns:
            bool: True if pool is initialized and not shut down. (进程池已初始化且未关闭)
        """
        return self._pool is not None

    @property
    def max_workers(self) -> int:
        """Get the maximum number of worker processes.
        获取最大工作进程数。

        Returns:
            int: Max workers count. (最大工作进程数)
        """
        return self._max_workers

    @property
    def demand_snapshot_path(self) -> Path | None:
        """Get the current pool-owned demand snapshot path.

        获取当前进程池拥有的负载快照路径。

        Returns:
            Path | None: Active path, or ``None`` when optional telemetry is
                unavailable. 当前有效路径；可选遥测不可用时为 ``None``。
        """

        publisher = self._demand_publisher
        return publisher.snapshot_path if publisher is not None else None

    @property
    def outstanding_tasks(self) -> int:
        """Get submitted tasks whose result has not been delivered.

        获取已提交但结果尚未交付的任务数。

        Returns:
            int: Current in-memory outstanding count.
                当前内存中的未完成任务数。
        """

        publisher = self._demand_publisher
        return publisher.outstanding if publisher is not None else 0

    @property
    def max_tasks_per_child(self) -> int | None:
        """Get the per-child task recycling threshold.
        获取每个子进程的任务回收阈值。

        Returns:
            int | None: Max tasks a worker handles before being recycled, or
                ``None`` if recycling is disabled.
                (子进程被回收前可处理的最大任务数，``None`` 表示禁用回收)
        """
        return self._max_tasks_per_child
