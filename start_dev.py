#!/usr/bin/env python3
"""Cross-platform dev launcher for Lumina Studio.
Lumina Studio 跨平台开发启动器。

Manages Backend (FastAPI :8000) and Frontend (Vite :5173) as child
processes.  Handles graceful shutdown on Ctrl+C / SIGTERM and
auto-terminates the surviving process when either one exits.
管理 Backend（FastAPI :8000）和 Frontend（Vite :5173）子进程。
处理 Ctrl+C / SIGTERM 优雅终止，任一进程退出时自动终止另一个。

Usage / 用法::

    python start_dev.py
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import List, Tuple

# Root directory of the project (项目根目录)
ROOT_DIR: str = os.path.dirname(os.path.abspath(__file__))

# Frontend directory (前端目录)
FRONTEND_DIR: str = os.path.join(ROOT_DIR, "frontend")

# Polling interval in seconds to avoid busy-waiting (轮询间隔，避免忙等待)
POLL_INTERVAL: float = 0.5


def _build_backend_cmd() -> List[str]:
    """Build the command list for the Backend process.
    构建 Backend 进程的命令列表。

    Returns:
        List[str]: Command tokens. (命令列表)
    """
    return [sys.executable, "api_server.py"]


def _build_frontend_cmd() -> List[str]:
    """Build the command list for the Frontend process.
    构建 Frontend 进程的命令列表。

    Returns:
        List[str]: Command tokens. (命令列表)
    """
    return ["npm", "run", "dev"]


def _terminate_all(procs: List[Tuple[str, subprocess.Popen]]) -> None:
    """Terminate all managed child processes gracefully.
    优雅终止所有托管的子进程。

    Sends SIGTERM (terminate) to each process that is still running,
    then waits up to 5 seconds for each to exit before force-killing.
    向每个仍在运行的进程发送 SIGTERM，然后最多等待 5 秒，超时则强制终止。

    Args:
        procs: List of (name, Popen) tuples. (进程名称和 Popen 对象的列表)
    """
    for name, proc in procs:
        if proc.poll() is None:
            print(f"[DEV] Terminating {name} (pid={proc.pid}) ...")
            proc.terminate()

    # Wait for graceful exit, then force-kill stragglers
    # 等待优雅退出，超时后强制终止
    for name, proc in procs:
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            print(f"[DEV] Force-killing {name} (pid={proc.pid})")
            proc.kill()


def main() -> None:
    """Entry point: start Backend and Frontend, monitor until exit.
    入口：启动 Backend 和 Frontend，监控直到退出。
    """
    procs: List[Tuple[str, subprocess.Popen]] = []

    # --- Banner ---
    print("=" * 44)
    print("  Lumina Studio 2.0 — Cross-Platform Launcher")
    print("=" * 44)
    print()

    # 1. Start Backend first (先启动 Backend)
    print("[DEV] Starting Backend (python api_server.py) ...")
    backend = subprocess.Popen(
        _build_backend_cmd(),
        cwd=ROOT_DIR,
    )
    procs.append(("Backend", backend))
    print(f"[DEV] Backend started (pid={backend.pid}, port=8000)")

    # 2. Start Frontend (再启动 Frontend)
    print("[DEV] Starting Frontend (npm run dev) ...")
    frontend = subprocess.Popen(
        _build_frontend_cmd(),
        cwd=FRONTEND_DIR,
        # On Windows, npm is a .cmd script and requires shell=True
        # Windows 上 npm 是 .cmd 脚本，需要 shell=True
        shell=(os.name == "nt"),
    )
    procs.append(("Frontend", frontend))
    print(f"[DEV] Frontend started (pid={frontend.pid}, port=5173)")
    print()
    print("[DEV] Both services running. Press Ctrl+C to stop.")
    print()

    # --- Signal handler for graceful shutdown ---
    # 信号处理器，用于优雅终止
    def shutdown(sig: int | None, frame: object) -> None:
        """Handle SIGINT / SIGTERM: terminate children and exit.
        处理 SIGINT / SIGTERM：终止子进程并退出。
        """
        sig_name = signal.Signals(sig).name if sig else "NONE"
        print(f"\n[DEV] Received {sig_name}, shutting down ...")
        _terminate_all(procs)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # --- Monitor loop ---
    # 监控循环：任一进程退出时终止另一个
    try:
        while True:
            for name, proc in procs:
                ret = proc.poll()
                if ret is not None:
                    print(f"[DEV] {name} exited with code {ret}")
                    _terminate_all(procs)
                    sys.exit(ret if ret != 0 else 1)
            # Sleep to avoid busy-waiting (休眠避免忙等待)
            time.sleep(POLL_INTERVAL)
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[DEV] Unexpected error: {exc}")
        _terminate_all(procs)
        sys.exit(1)


if __name__ == "__main__":
    main()
