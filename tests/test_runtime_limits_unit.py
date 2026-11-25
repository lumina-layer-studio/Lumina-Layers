from __future__ import annotations

import os

import pytest

from api import runtime_limits


def test_configure_blas_thread_limits_sets_missing_defaults(monkeypatch) -> None:
    for env_name in runtime_limits.BLAS_THREAD_ENV_VARS:
        monkeypatch.delenv(env_name, raising=False)

    runtime_limits.configure_blas_thread_limits()

    for env_name in runtime_limits.BLAS_THREAD_ENV_VARS:
        assert os.environ[env_name] == "1"


def test_configure_blas_thread_limits_preserves_operator_overrides(monkeypatch) -> None:
    for env_name in runtime_limits.BLAS_THREAD_ENV_VARS:
        monkeypatch.setenv(env_name, "4")

    runtime_limits.configure_blas_thread_limits()

    for env_name in runtime_limits.BLAS_THREAD_ENV_VARS:
        assert os.environ[env_name] == "4"


@pytest.mark.parametrize(
    ("platform", "threads", "thread_limit", "expected"),
    [
        ("darwin", None, None, ("1", "1")),
        ("darwin", "4", None, ("4", None)),
        ("darwin", None, "3", ("1", "3")),
        ("darwin", "4", "3", ("4", "3")),
        ("linux", None, None, ("1", None)),
        ("win32", None, None, ("1", None)),
    ],
)
def test_openmp_cap_defaults_are_macos_only(monkeypatch, platform, threads, thread_limit, expected) -> None:
    monkeypatch.setattr(runtime_limits.sys, "platform", platform)
    for name, value in (("OMP_NUM_THREADS", threads), ("OMP_THREAD_LIMIT", thread_limit)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    monkeypatch.delenv("KMP_DUPLICATE_LIB_OK", raising=False)

    runtime_limits.configure_blas_thread_limits()
    runtime_limits.configure_blas_thread_limits()

    assert (os.getenv("OMP_NUM_THREADS"), os.getenv("OMP_THREAD_LIMIT")) == expected
    assert "KMP_DUPLICATE_LIB_OK" not in os.environ
