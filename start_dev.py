#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lumina Studio 2.0 — 开发环境启动器（重构版）

功能：
  - 一键启动 Backend (FastAPI :8000) + Frontend (Vite :5174)
  - 支持一键重启（按 r + Enter）
  - 启动前自动清理残留端口占用
  - 彩色日志输出，区分 Backend / Frontend
  - 优雅退出（Ctrl+C / SIGTERM）

用法：
    python start_dev.py              # 启动
    python start_dev.py --backend    # 仅启动后端
    python start_dev.py --frontend   # 仅启动前端
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import re
from typing import Optional

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")

BACKEND_PORT = 8000
FRONTEND_PORT = 5174
POLL_INTERVAL = 0.3
SHUTDOWN_TIMEOUT = 5
MAX_AUTO_RESTART = 3  # 自动重启上限，防止死循环


def _find_venv_python() -> str:
    """查找项目 venv 中的 Python 解释器，找不到则回退到当前解释器。"""
    candidates = [
        os.path.join(ROOT_DIR, "venv", "bin", "python"),
        os.path.join(ROOT_DIR, "venv", "Scripts", "python.exe"),
        os.path.join(ROOT_DIR, ".venv", "bin", "python"),
        os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return sys.executable


# ── 颜色工具 ──────────────────────────────────────────────

class C:
    """ANSI 颜色常量"""
    RESET  = "\033[0m"
    BOLD   = "\033[1m"
    RED    = "\033[31m"
    GREEN  = "\033[32m"
    YELLOW = "\033[33m"
    BLUE   = "\033[34m"
    CYAN   = "\033[36m"
    DIM    = "\033[2m"


def _log(tag: str, color: str, msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"{C.DIM}{ts}{C.RESET} {color}{C.BOLD}[{tag}]{C.RESET} {msg}")


def log_sys(msg: str) -> None:
    _log("SYS", C.YELLOW, msg)


def log_ok(msg: str) -> None:
    _log(" OK", C.GREEN, msg)


def log_err(msg: str) -> None:
    _log("ERR", C.RED, msg)


# ── 端口工具 ──────────────────────────────────────────────

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def kill_port(port: int) -> bool:
    """尝试杀掉占用指定端口的进程（macOS/Linux）"""
    if not is_port_in_use(port):
        return False
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=5,
        )
        pids = result.stdout.strip().split("\n")
        for pid in pids:
            if pid.strip():
                subprocess.run(["kill", "-9", pid.strip()], timeout=5)
        time.sleep(0.5)
        return True
    except Exception:
        return False


# ── 进程管理 ──────────────────────────────────────────────

class ServiceProcess:
    """封装一个子服务进程"""

    def __init__(self, name: str, cmd: list[str], cwd: str, port: int, color: str):
        self.name = name
        self.cmd = cmd
        self.cwd = cwd
        self.port = port
        self.actual_port = port
        self.port_detected = threading.Event()
        self.color = color
        self.proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.port_detected.clear()
        if is_port_in_use(self.port):
            log_sys(f"端口 {self.port} 被占用，正在清理...")
            kill_port(self.port)
            if is_port_in_use(self.port):
                log_err(f"无法释放端口 {self.port}，请手动处理")
                return

        _log(self.name, self.color, f"启动中... (port={self.port})")
        # 使用 start_new_session 创建新进程组，确保重启时能杀死所有子进程
        self.proc = subprocess.Popen(
            self.cmd,
            cwd=self.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            start_new_session=(os.name != "nt"),
            shell=(os.name == "nt" and self.name == "Frontend"),
        )
        self._reader_thread = threading.Thread(
            target=self._stream_output, daemon=True,
        )
        self._reader_thread.start()
        _log(self.name, self.color, f"已启动 (pid={self.proc.pid})")

    def _stream_output(self) -> None:
        """实时转发子进程输出"""
        if not self.proc or not self.proc.stdout:
            return
        try:
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                if line:
                    _log(self.name, self.color, line)
                    if self.name == "Frontend" and not self.port_detected.is_set():
                        # 去除 ANSI 转义序列以正确匹配端口
                        clean_line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line)
                        match = re.search(r"http://(?:localhost|127\.0\.0\.1|\[::1\]):(\d+)", clean_line)
                        if match:
                            self.actual_port = int(match.group(1))
                            self.port_detected.set()
        except (ValueError, OSError):
            pass  # 进程已关闭

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            _log(self.name, self.color, f"正在停止 (pid={self.proc.pid})...")
            # 先杀整个进程组（包含所有子进程），再 fallback 到单进程
            pgid = None
            if os.name != "nt":
                try:
                    pgid = os.getpgid(self.proc.pid)
                except OSError:
                    pgid = None

            if pgid is not None:
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except OSError:
                    pass
            else:
                self.proc.terminate()

            try:
                self.proc.wait(timeout=SHUTDOWN_TIMEOUT)
            except subprocess.TimeoutExpired:
                _log(self.name, self.color, "强制终止")
                if pgid is not None:
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except OSError:
                        pass
                else:
                    self.proc.kill()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass

            # 确保端口被释放
            if is_port_in_use(self.port):
                kill_port(self.port)

        self.proc = None

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


class DevManager:
    """管理所有开发服务"""

    def __init__(self, run_backend: bool = True, run_frontend: bool = True):
        self.services: list[ServiceProcess] = []
        self._shutdown = False

        if run_backend:
            self.services.append(ServiceProcess(
                name="Backend",
                cmd=[_find_venv_python(), "api_server.py"],
                cwd=ROOT_DIR,
                port=BACKEND_PORT,
                color=C.CYAN,
            ))

        if run_frontend:
            self.services.append(ServiceProcess(
                name="Frontend",
                cmd=["npm", "run", "dev"],
                cwd=FRONTEND_DIR,
                port=FRONTEND_PORT,
                color=C.BLUE,
            ))

    def start_all(self) -> None:
        self._shutdown = False
        for svc in self.services:
            svc.start()

    def stop_all(self) -> None:
        self._shutdown = True
        for svc in reversed(self.services):
            svc.stop()

    def restart_all(self) -> None:
        log_sys("正在重启所有服务...")
        self.stop_all()
        time.sleep(1)
        self.start_all()
        log_ok("重启完成")

    def check_health(self) -> bool:
        """检查是否有服务意外退出"""
        if self._shutdown:
            return True
        for svc in self.services:
            if svc.proc and not svc.alive:
                ret = svc.proc.returncode
                log_err(f"{svc.name} 意外退出 (code={ret})")
                return False
        return True


# ── 交互式命令监听 ────────────────────────────────────────

def _input_listener(manager: DevManager) -> None:
    """监听用户键盘输入，支持交互式命令"""
    while True:
        try:
            cmd = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if cmd in ("r", "restart"):
            manager.restart_all()
        elif cmd in ("q", "quit", "exit"):
            log_sys("用户请求退出")
            manager.stop_all()
            os._exit(0)
        elif cmd in ("s", "status"):
            for svc in manager.services:
                status = f"{C.GREEN}运行中{C.RESET}" if svc.alive else f"{C.RED}已停止{C.RESET}"
                _log(svc.name, svc.color, f"状态: {status}")
        elif cmd in ("h", "help"):
            print(f"""
{C.BOLD}可用命令：{C.RESET}
  {C.GREEN}r{C.RESET} / restart  — 重启所有服务
  {C.GREEN}s{C.RESET} / status   — 查看服务状态
  {C.GREEN}q{C.RESET} / quit     — 退出
  {C.GREEN}h{C.RESET} / help     — 显示帮助
""")


# ── 主入口 ────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Lumina Studio 开发启动器")
    parser.add_argument("--backend", action="store_true", help="仅启动后端")
    parser.add_argument("--frontend", action="store_true", help="仅启动前端")
    args = parser.parse_args()

    # 如果都没指定，则全部启动
    run_backend = args.backend or (not args.backend and not args.frontend)
    run_frontend = args.frontend or (not args.backend and not args.frontend)

    print(f"""
{C.BOLD}{C.CYAN}╔══════════════════════════════════════════╗
║     Lumina Studio 2.0 — Dev Launcher     ║
╚══════════════════════════════════════════╝{C.RESET}
""")

    venv_py = _find_venv_python()
    log_sys(f"Python: {venv_py}")

    manager = DevManager(run_backend=run_backend, run_frontend=run_frontend)

    # 信号处理
    def shutdown(sig: int, _: object) -> None:
        sig_name = signal.Signals(sig).name
        log_sys(f"收到 {sig_name}，正在退出...")
        manager.stop_all()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # 启动服务
    manager.start_all()

    frontend_svc = next((svc for svc in manager.services if svc.name == "Frontend"), None)
    actual_frontend_port = FRONTEND_PORT
    if frontend_svc:
        # 等待最多 5 秒获取前端实际端口
        if frontend_svc.port_detected.wait(timeout=5.0):
            actual_frontend_port = frontend_svc.actual_port

    svc_names = " + ".join(svc.name for svc in manager.services)
    log_ok(f"{svc_names} 已启动")
    print(f"""
{C.DIM}────────────────────────────────────────────{C.RESET}
  Backend:  {C.CYAN}http://localhost:{BACKEND_PORT}{C.RESET}
  Frontend: {C.BLUE}http://localhost:{actual_frontend_port}{C.RESET}
{C.DIM}────────────────────────────────────────────{C.RESET}
  {C.GREEN}r{C.RESET}=重启  {C.GREEN}s{C.RESET}=状态  {C.GREEN}q{C.RESET}=退出  {C.GREEN}h{C.RESET}=帮助
{C.DIM}────────────────────────────────────────────{C.RESET}
""")

    # 启动输入监听线程
    input_thread = threading.Thread(target=_input_listener, args=(manager,), daemon=True)
    input_thread.start()

    # 主循环：健康检查
    restart_count = 0
    try:
        while True:
            if not manager.check_health():
                restart_count += 1
                if restart_count > MAX_AUTO_RESTART:
                    log_err(f"已连续自动重启 {MAX_AUTO_RESTART} 次，停止重试。请检查服务日志。")
                    log_sys("按 r 手动重启，或 q 退出")
                else:
                    log_sys(f"检测到服务异常退出，自动重启 ({restart_count}/{MAX_AUTO_RESTART})...")
                    manager.restart_all()
            else:
                restart_count = 0  # 健康时重置计数
            time.sleep(POLL_INTERVAL)
    except (KeyboardInterrupt, SystemExit):
        log_sys("正在退出...")
        manager.stop_all()
        sys.exit(0)


if __name__ == "__main__":
    main()
