"""Runtime resource limits for numerical backends.
数值计算后端的运行时资源限制。

This module is imported by the API application before routers import NumPy or
SciPy-heavy code. Defaults are applied with ``setdefault`` so deployment
overrides remain honored.

本模块由 API 应用在路由导入 NumPy / SciPy 重计算代码前加载。默认值使用
``setdefault`` 写入，因此部署环境中的显式覆盖仍然生效。
"""

from __future__ import annotations

import os
import sys

BLAS_THREAD_ENV_VARS: tuple[str, ...] = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def configure_blas_thread_limits(default: str = "1") -> None:
    """Cap BLAS/OpenMP thread pools before numerical libraries are imported.
    在数值计算库导入前限制 BLAS/OpenMP 线程池。

    Args:
        default: Thread count used when no environment override exists.
            (环境未显式设置时使用的线程数)
    """

    # On macOS the native wheels can create OpenMP teams inside our workers.
    # Use a hard cap with the default team size. Explicit team sizes and caps
    # remain under the operator's control.
    if sys.platform == "darwin" and "OMP_NUM_THREADS" not in os.environ:
        os.environ.setdefault("OMP_THREAD_LIMIT", default)
    for env_name in BLAS_THREAD_ENV_VARS:
        os.environ.setdefault(env_name, default)
