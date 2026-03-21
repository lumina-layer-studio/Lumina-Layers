"""Property-Based tests for WorkerPoolManager and WorkerPoolConfig.
WorkerPoolManager 和 WorkerPoolConfig 的 Property-Based 测试。

Feature: thread-separation-upgrade

Uses Hypothesis to verify universal properties across randomized inputs.
使用 Hypothesis 验证随机输入下的通用属性。

**Validates: Requirements 1.1, 1.4, 2.3, 5.2, 5.3**
"""

import asyncio
import os
import re
import time
from unittest.mock import patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from api.worker_pool import WorkerPoolManager
from config import WorkerPoolConfig


# ---------------------------------------------------------------------------
# Top-level worker functions for Property 2 and 3 (must be picklable)
# 顶层工作函数，用于 Property 2 和 3（必须可序列化）
# ---------------------------------------------------------------------------


def _worker_raise_value_error(msg: str) -> None:
    """Worker that raises ValueError. (抛出 ValueError 的工作函数)"""
    raise ValueError(msg)


def _worker_raise_runtime_error(msg: str) -> None:
    """Worker that raises RuntimeError. (抛出 RuntimeError 的工作函数)"""
    raise RuntimeError(msg)


def _worker_raise_os_error(msg: str) -> None:
    """Worker that raises OSError. (抛出 OSError 的工作函数)"""
    raise OSError(msg)


def _worker_raise_type_error(msg: str) -> None:
    """Worker that raises TypeError. (抛出 TypeError 的工作函数)"""
    raise TypeError(msg)


def _worker_raise_io_error(msg: str) -> None:
    """Worker that raises IOError. (抛出 IOError 的工作函数)"""
    raise IOError(msg)


_EXCEPTION_WORKERS = [
    (ValueError, _worker_raise_value_error),
    (RuntimeError, _worker_raise_runtime_error),
    (OSError, _worker_raise_os_error),
    (TypeError, _worker_raise_type_error),
    (IOError, _worker_raise_io_error),
]


def _worker_sleep(seconds: float) -> str:
    """Worker that sleeps for the given duration. (休眠指定时长的工作函数)"""
    time.sleep(seconds)
    return "done"


# ---------------------------------------------------------------------------
# Property 1: 进程池工作进程数上限
# Feature: thread-separation-upgrade, Property 1: 进程池工作进程数上限
# ---------------------------------------------------------------------------


class TestWorkerPoolMaxWorkersProperty:
    """For any cpu_count (1–128), default max_workers == min(cpu_count, 4).

    **Validates: Requirements 1.1**
    """

    @given(cpu_count=st.integers(min_value=1, max_value=128))
    @settings(max_examples=100)
    def test_max_workers_equals_min_cpu_count_4(self, cpu_count: int) -> None:
        """Property 1: 进程池工作进程数上限.
        Property 1: 工作进程数上限。

        For any cpu_count value (1 to 128), WorkerPoolManager with
        max_workers=None should default to min(cpu_count, 4).

        **Validates: Requirements 1.1**
        """
        with patch("api.worker_pool.os.cpu_count", return_value=cpu_count):
            pool = WorkerPoolManager(max_workers=None)
        assert pool.max_workers == min(cpu_count, 4)


# ---------------------------------------------------------------------------
# Property 4: 配置环境变量覆盖
# Feature: thread-separation-upgrade, Property 4: 配置环境变量覆盖
# ---------------------------------------------------------------------------


class TestWorkerPoolConfigEnvOverrideProperty:
    """For any n (1–32) and f (1.0–3600.0), env vars override config.

    **Validates: Requirements 5.2, 5.3**
    """

    @given(
        n=st.integers(min_value=1, max_value=32),
        f=st.floats(min_value=1.0, max_value=3600.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_env_vars_override_config(self, n: int, f: float) -> None:
        """Property 4: 配置环境变量覆盖.
        Property 4: 环境变量覆盖配置。

        When LUMINA_MAX_WORKERS=n and LUMINA_TASK_TIMEOUT=f are set,
        WorkerPoolConfig.from_env() returns MAX_WORKERS == n and
        TASK_TIMEOUT == f.

        **Validates: Requirements 5.2, 5.3**
        """
        env_patch = {
            "LUMINA_MAX_WORKERS": str(n),
            "LUMINA_TASK_TIMEOUT": str(f),
        }
        with patch.dict(os.environ, env_patch, clear=False):
            cfg = WorkerPoolConfig.from_env()
        assert cfg.MAX_WORKERS == n
        assert cfg.TASK_TIMEOUT == pytest.approx(f)


# ---------------------------------------------------------------------------
# Property 2: Worker 异常传播
# Feature: thread-separation-upgrade, Property 2: Worker 异常传播
# ---------------------------------------------------------------------------


class TestWorkerExceptionPropagationProperty:
    """For any exception type raised in a worker, pool.submit() propagates it.

    **Validates: Requirements 1.4**
    """

    @given(
        exc_index=st.integers(min_value=0, max_value=len(_EXCEPTION_WORKERS) - 1),
        msg=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z"), blacklist_characters="\x00"),
            min_size=1,
            max_size=50,
        ).filter(lambda s: s.strip()),
    )
    @settings(max_examples=100, deadline=5000)
    def test_worker_exception_propagates(self, exc_index: int, msg: str) -> None:
        """Property 2: Worker 异常传播.
        Property 2: Worker 异常传播。

        For any exception type raised inside a worker function,
        pool.submit() should propagate that exact exception type
        and message to the caller, never silently swallowing it.

        **Validates: Requirements 1.4**
        """
        exc_type, worker_fn = _EXCEPTION_WORKERS[exc_index]
        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        try:
            with pytest.raises(exc_type, match=re.escape(msg)):
                asyncio.run(pool.submit(worker_fn, msg, timeout=30.0))
        finally:
            pool.shutdown(wait=True)


# ---------------------------------------------------------------------------
# Property 3: 任务超时取消
# Feature: thread-separation-upgrade, Property 3: 任务超时取消
# ---------------------------------------------------------------------------


class TestTaskTimeoutCancellationProperty:
    """For any timeout t, tasks exceeding t raise asyncio.TimeoutError.

    **Validates: Requirements 2.3**
    """

    @given(
        timeout=st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=20, deadline=30000)
    def test_task_timeout_raises_timeout_error(self, timeout: float) -> None:
        """Property 3: 任务超时取消.
        Property 3: 任务超时取消。

        For any timeout value t (0.1 to 1.0 seconds) and a task that
        sleeps for t + 2 seconds, pool.submit(fn, timeout=t) should
        raise asyncio.TimeoutError within a reasonable time.

        **Validates: Requirements 2.3**
        """
        sleep_duration = timeout + 2.0
        pool = WorkerPoolManager(max_workers=1)
        pool.start()
        try:
            with pytest.raises(asyncio.TimeoutError):
                asyncio.run(pool.submit(_worker_sleep, sleep_duration, timeout=timeout))
        finally:
            pool.shutdown(wait=False)
