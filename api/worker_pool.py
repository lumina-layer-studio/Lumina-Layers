"""Bounded CPU workers with per-process failure isolation and shared demand."""

from concurrent.futures import Future as ConcurrentFuture
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from contextvars import Context, copy_context
from multiprocessing import get_context
from multiprocessing.connection import wait as wait_for_process_exit
from queue import Empty, Queue
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


_QueuedTask = tuple[
    ConcurrentFuture[Any], Callable[..., Any], tuple[Any, ...],
    dict[str, Any], Context, str,
]


class _IsolatedProcessExecutor:
    """A shared FIFO feeding independently replaceable, single-process slots.

    Each dispatcher owns exactly one ProcessPoolExecutor and gives it one task
    at a time. Unstarted jobs stay in the parent queue, so a broken child cannot
    invalidate either another slot's work or the pending queue.
    """

    def __init__(self, max_workers: int, max_tasks_per_child: int | None) -> None:
        if max_workers < 1:
            raise ValueError("max_workers must be greater than 0")
        self._max_tasks_per_child = max_tasks_per_child
        self._queue: Queue[_QueuedTask | None] = Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._threads: list[threading.Thread] = []
        try:
            for index in range(max_workers):
                thread = threading.Thread(
                    target=self._run_slot,
                    args=(index,),
                    name=f"lumina-worker-{index}",
                    daemon=True,
                )
                thread.start()
                self._threads.append(thread)
        except BaseException:
            self.shutdown(wait=True, cancel_futures=True)
            raise

    def submit(
        self, fn: Callable[..., T], *args: Any,
        task_name: str, **kwargs: Any,
    ) -> ConcurrentFuture[T]:
        future: ConcurrentFuture[T] = ConcurrentFuture()
        with self._lock:
            if self._closed:
                raise RuntimeError("WorkerPool is shut down")
            self._queue.put((future, fn, args, kwargs, copy_context(), task_name))
        return future

    def _run_slot(self, index: int) -> None:
        executor: ProcessPoolExecutor | None = None
        try:
            while (job := self._queue.get()) is not None:
                executor = self._run_job(index, executor, job)
                # Do not retain the previous request/result while idle.
                del job
        finally:
            if executor is not None:
                _shutdown_executor(executor, wait=True, cancel_futures=False)

    def _run_job(
        self,
        index: int,
        executor: ProcessPoolExecutor | None,
        job: _QueuedTask,
    ) -> ProcessPoolExecutor | None:
        future, fn, args, kwargs, context, task_name = job
        if not future.set_running_or_notify_cancel():
            return executor
        try:
            if executor is None:
                executor = ProcessPoolExecutor(
                    max_workers=1,
                    initializer=_worker_init,
                    max_tasks_per_child=self._max_tasks_per_child,
                    # Dispatchers are threads. Never fork the API process
                    # from one, including when child recycling is disabled.
                    mp_context=get_context("spawn"),
                )
            submitted = False
            try:
                result_future = executor.submit(fn, *args, **kwargs)
                submitted = True
                result = result_future.result()
            except BaseException as exc:
                if not submitted or isinstance(exc, BrokenProcessPool):
                    # Complete the caller only after this slot's child has
                    # stopped. Other dispatchers keep serving their jobs.
                    terminated, survivors = _terminate_executor_workers(executor)
                    _shutdown_executor(executor, wait=True, cancel_futures=True)
                    executor = None
                    context.run(
                        _log.warning,
                        "Worker process retired after a task failure",
                        extra={
                            "event": "worker_process_failed",
                            "worker_index": index,
                            "worker_name": task_name,
                            "terminated_workers": terminated,
                            "surviving_workers": survivors,
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                        },
                    )
                raise
        except BaseException as exc:
            # Keep the remote traceback cause, without pinning this dispatcher
            # frame (and its input/result objects) in the caller's exception.
            future.set_exception(exc.with_traceback(None))
        else:
            future.set_result(result)
        return executor

    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        cancelled: list[ConcurrentFuture[Any]] = []
        with self._lock:
            if not self._closed:
                self._closed = True
                if cancel_futures:
                    while True:
                        try:
                            job = self._queue.get_nowait()
                        except Empty:
                            break
                        if job is not None:
                            cancelled.append(job[0])
                for _thread in self._threads:
                    self._queue.put(None)
        # Future callbacks can acquire the manager lock. Do not invoke them
        # while holding the executor lock (submit acquires them in reverse).
        for future in cancelled:
            future.cancel()
        if wait:
            for thread in self._threads:
                thread.join()


class WorkerPoolManager:
    """Manage isolated CPU workers, request context, timing and demand telemetry."""

    def __init__(self, max_workers: int | None = None) -> None:
        self._max_workers = max_workers or min(os.cpu_count() or 2, 4)
        self._max_tasks_per_child = _resolve_max_tasks_per_child()
        self._pool: _IsolatedProcessExecutor | None = None
        self._pool_lock = threading.RLock()
        self._demand_publisher = self._create_demand_publisher()
        self._retired_publishers: set[OuterDemandPublisher] = set()
        self._active_tasks: dict[str, OuterDemandPublisher | None] = {}

    def _create_demand_publisher(self) -> OuterDemandPublisher | None:
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

    def _complete_task(self, token: str) -> None:
        with self._pool_lock:
            publisher = self._active_tasks.pop(token)
            self._update_demand(publisher, "decrement")
            self._cleanup_retired_publishers()

    def _cleanup_retired_publishers(self) -> None:
        """Called under the manager lock, after each close or completion."""
        for publisher in tuple(self._retired_publishers):
            if publisher in self._active_tasks.values():
                continue
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
                self._retired_publishers.remove(publisher)

    def start(self) -> None:
        with self._pool_lock:
            if self._pool is not None:
                return
            if self._demand_publisher is None:
                self._demand_publisher = self._create_demand_publisher()
            self._pool = _IsolatedProcessExecutor(
                self._max_workers, self._max_tasks_per_child,
            )

    async def submit(self, fn: Callable[..., T], *args: Any) -> T:
        result, _timing = await self._submit_internal(fn, args, include_timing=False)
        return result

    async def submit_timed(
        self, fn: Callable[..., T], *args: Any,
    ) -> tuple[T, dict[str, float]]:
        result, timing = await self._submit_internal(fn, args, include_timing=True)
        if timing is None:
            raise RuntimeError("Timed worker submission returned no timing")
        return result, timing

    async def _submit_internal(
        self,
        fn: Callable[..., T],
        args: tuple[Any, ...],
        *,
        include_timing: bool,
    ) -> tuple[T, dict[str, float] | None]:
        from api.structured_logging import get_request_id, get_session_id

        loop = asyncio.get_running_loop()
        worker_entry = (
            _run_in_worker_with_context_timed
            if include_timing else _run_in_worker_with_context
        )
        submitted_ns = time.perf_counter_ns()
        # Capture and submit under the same lock. A shutdown cannot move this
        # request into a new service generation while it waits in the queue.
        with self._pool_lock:
            if self._pool is None:
                raise RuntimeError("WorkerPool not started")
            publisher = self._demand_publisher
            token = uuid.uuid4().hex
            self._active_tasks[token] = publisher
            self._update_demand(publisher, "increment")
            try:
                executor_future = self._pool.submit(
                    worker_entry, fn, get_request_id(), get_session_id(),
                    str(publisher.snapshot_path) if publisher is not None else None,
                    *args,
                    task_name=getattr(fn, "__name__", type(fn).__name__),
                    worker_lease_path=(
                        str(publisher.worker_lease_path) if publisher is not None else None
                    ),
                )
            except BaseException:
                self._complete_task(token)
                raise
            executor_future.add_done_callback(lambda _completed: self._complete_task(token))

        future = asyncio.wrap_future(executor_future, loop=loop)
        # A disconnected caller does not own a running process's lifetime.
        # Consume a late exception even if nobody remains to await its result.
        future.add_done_callback(lambda done: None if done.cancelled() else done.exception())
        try:
            raw_result = await asyncio.shield(future)
        except asyncio.CancelledError:
            executor_future.cancel()  # Succeeds only if the job has not started.
            raise
        if not include_timing:
            return raw_result, None
        result, worker_started_ns, worker_finished_ns = raw_result
        received_ns = time.perf_counter_ns()
        timing = {
            "queue_wait_s": max(0.0, (worker_started_ns - submitted_ns) / 1_000_000_000),
            "worker_execution_s": max(0.0, (worker_finished_ns - worker_started_ns) / 1_000_000_000),
            "result_delivery_s": max(0.0, (received_ns - worker_finished_ns) / 1_000_000_000),
            "pool_roundtrip_s": max(0.0, (received_ns - submitted_ns) / 1_000_000_000),
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

    def shutdown(self, wait: bool = True) -> None:
        with self._pool_lock:
            executor = self._pool
            self._pool = None
            if self._demand_publisher is not None:
                self._retired_publishers.add(self._demand_publisher)
                self._demand_publisher = None
            self._cleanup_retired_publishers()
        if executor is not None:
            executor.shutdown(wait=wait, cancel_futures=not wait)

    @property
    def is_alive(self) -> bool:
        return self._pool is not None

    @property
    def max_workers(self) -> int:
        return self._max_workers

    @property
    def demand_snapshot_path(self) -> Path | None:
        publisher = self._demand_publisher
        return publisher.snapshot_path if publisher is not None else None

    @property
    def outstanding_tasks(self) -> int:
        """Count running and queued jobs, including work whose caller left."""
        with self._pool_lock:
            return len(self._active_tasks)

    @property
    def max_tasks_per_child(self) -> int | None:
        return self._max_tasks_per_child
