"""WorkerPoolManager — ProcessPoolExecutor lifecycle manager.
WorkerPoolManager — ProcessPoolExecutor 生命周期管理器。

Provides an async-friendly interface for submitting CPU-bound tasks
to a process pool, with timeout support and graceful shutdown.
提供异步友好的接口，将 CPU 密集型任务提交到进程池，
支持超时控制和优雅关闭。
"""

from concurrent.futures import ProcessPoolExecutor
from typing import Any, Callable, TypeVar
import asyncio
import os

T = TypeVar("T")


class WorkerPoolManager:
    """Manage a ProcessPoolExecutor for CPU-bound tasks.
    管理用于 CPU 密集型任务的进程池。

    Attributes:
        _max_workers (int): Maximum number of worker processes. (最大工作进程数)
        _pool (ProcessPoolExecutor | None): The underlying executor. (底层执行器)
    """

    def __init__(self, max_workers: int | None = None) -> None:
        """Initialize WorkerPoolManager.
        初始化 WorkerPoolManager。

        Args:
            max_workers (int | None): Max worker processes. Defaults to min(cpu_count, 4).
                                      (最大工作进程数，默认 min(cpu_count, 4))
        """
        self._max_workers: int = max_workers or min(os.cpu_count() or 2, 4)
        self._pool: ProcessPoolExecutor | None = None

    def start(self) -> None:
        """Initialize the process pool.
        初始化进程池。
        """
        self._pool = ProcessPoolExecutor(max_workers=self._max_workers)

    async def submit(
        self,
        fn: Callable[..., T],
        *args: Any,
        timeout: float = 300.0,
    ) -> T:
        """Submit a CPU task to the pool and await result.
        提交 CPU 任务到进程池并等待结果。

        Args:
            fn (Callable[..., T]): Top-level function (must be picklable).
                                   (顶层函数，必须可序列化)
            *args (Any): Scalar args or file paths only.
                         (仅标量参数或文件路径)
            timeout (float): Max seconds to wait. Defaults to 300.0.
                             (最大等待秒数，默认 300.0)

        Returns:
            T: Function return value. (函数返回值)

        Raises:
            asyncio.TimeoutError: If task exceeds timeout. (任务超时)
            RuntimeError: If pool not started. (进程池未启动)
        """
        if self._pool is None:
            raise RuntimeError("WorkerPool not started")
        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(self._pool, fn, *args)
        return await asyncio.wait_for(future, timeout=timeout)

    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the pool gracefully.
        优雅关闭进程池。

        Args:
            wait (bool): Whether to wait for pending tasks to complete.
                         (是否等待待处理任务完成)
        """
        if self._pool is not None:
            self._pool.shutdown(wait=wait)
            self._pool = None

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
