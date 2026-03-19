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
import shutil
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
POLL_INTERVAL = 2
SHUTDOWN_TIMEOUT = 5
MAX_AUTO_RESTART = 3
HEALTHY_RESET_WINDOW = 30  # 持续健康多少秒后才重置重启计数

_venv_python_cache: Optional[str] = None


def _find_venv_python() -> str:
    """查找项目 venv 中的 Python 解释器，找不到则回退到当前解释器。
    结果会被缓存以避免重复文件系统查找。
    """
    global _venv_python_cache
    if _venv_python_cache is not None:
        return _venv_python_cache
    candidates = [
        os.path.join(ROOT_DIR, "venv", "bin", "python"),
        os.path.join(ROOT_DIR, "venv", "Scripts", "python.exe"),
        os.path.join(ROOT_DIR, ".venv", "bin", "python"),
        os.path.join(ROOT_DIR, ".venv", "Scripts", "python.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            _venv_python_cache = p
            return p
    _venv_python_cache = sys.executable
    return _venv_python_cache


def _check_npm_available() -> bool:
    """检查 npm 是否在 PATH 中可用。"""
    return shutil.which("npm") is not None


_wsl_cache: Optional[bool] = None


def _is_wsl() -> bool:
    """检测当前是否运行在 WSL2 环境中。"""
    global _wsl_cache
    if _wsl_cache is not None:
        return _wsl_cache
    try:
        with open("/proc/version", "r") as f:
            _wsl_cache = "microsoft" in f.read().lower()
    except OSError:
        _wsl_cache = False
    return _wsl_cache


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


def _find_pids_fuser(port: int) -> list[int]:
    """通过 fuser 查找占用端口的 PID（Linux 常见）。"""
    try:
        result = subprocess.run(
            ["fuser", f"{port}/tcp"],
            capture_output=True, text=True, timeout=5,
        )
        output = (result.stdout + " " + result.stderr).strip()
        pids: list[int] = []
        for token in output.split():
            cleaned = token.strip().rstrip("e")
            try:
                pids.append(int(cleaned))
            except ValueError:
                pass
        return pids
    except FileNotFoundError:
        return []
    except Exception:
        return []


def _find_pids_lsof(port: int) -> list[int]:
    """通过 lsof 查找占用端口的 PID（macOS 常见）。"""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=5,
        )
        pids: list[int] = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line:
                try:
                    pids.append(int(line))
                except ValueError:
                    pass
        return pids
    except FileNotFoundError:
        return []
    except Exception:
        return []


def _find_pids_netstat(port: int) -> list[int]:
    """通过 netstat 查找占用端口的 PID（Windows）。"""
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=5,
        )
        pids: set[int] = set()
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    try:
                        pids.add(int(parts[-1]))
                    except ValueError:
                        pass
        return list(pids)
    except Exception:
        return []


def _find_pids_on_port(port: int) -> list[int]:
    """跨平台查找占用指定端口的所有 PID。
    Cross-platform PID lookup: fuser/lsof on Unix, netstat on Windows.
    """
    if os.name == "nt":
        return _find_pids_netstat(port)
    for strategy in (_find_pids_fuser, _find_pids_lsof):
        pids = strategy(port)
        if pids:
            return pids
    return []


def kill_port(port: int) -> bool:
    """跨平台杀端口，先 SIGTERM 优雅退出，超时后 SIGKILL 强杀。
    Cross-platform port killer with graceful SIGTERM before forced SIGKILL.
    """
    if not is_port_in_use(port):
        return False

    pids = _find_pids_on_port(port)
    if not pids:
        return False

    if os.name == "nt":
        for pid in pids:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True, timeout=5,
                )
            except Exception:
                pass
    else:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and is_port_in_use(port):
            time.sleep(0.2)

        if is_port_in_use(port):
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
            time.sleep(0.3)

    return True


# ── 进程管理 ──────────────────────────────────────────────

class ServiceProcess:
    """封装一个子服务进程"""

    def __init__(
        self, name: str, cmd: list[str], cwd: str, port: int,
        color: str, *, strict_port: bool = True,
    ):
        self.name = name
        self.cmd = cmd
        self.cwd = cwd
        self.port = port
        self.actual_port = port
        self.port_detected = threading.Event()
        self.color = color
        self.strict_port = strict_port
        self.proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.port_detected.clear()
        if is_port_in_use(self.port):
            log_sys(f"端口 {self.port} 被占用，正在清理...")
            kill_port(self.port)
            if is_port_in_use(self.port):
                if self.strict_port:
                    if _is_wsl():
                        log_err(
                            f"无法释放端口 {self.port}（WSL2 环境下可能"
                            f"被 Windows 侧进程占用，请在 Windows 中关闭相关程序）"
                        )
                    else:
                        log_err(f"无法释放端口 {self.port}，请手动处理")
                    return
                log_sys(
                    f"端口 {self.port} 无法释放"
                    + ("（可能被 Windows 侧进程占用）" if _is_wsl() else "")
                    + f"，{self.name} 将自动选择可用端口"
                )

        _log(self.name, self.color, f"启动中... (port={self.port})")
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

    _PORT_RE = re.compile(
        r"http://(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0):(\d+)"
    )

    def _stream_output(self) -> None:
        """实时转发子进程输出，并自动检测实际监听端口。"""
        if not self.proc or not self.proc.stdout:
            return
        try:
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                if line:
                    _log(self.name, self.color, line)
                    if not self.port_detected.is_set():
                        clean = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line)
                        match = self._PORT_RE.search(clean)
                        if match:
                            self.actual_port = int(match.group(1))
                            self.port_detected.set()
        except (ValueError, OSError):
            pass

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            _log(self.name, self.color, f"正在停止 (pid={self.proc.pid})...")
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

            if is_port_in_use(self.port):
                kill_port(self.port)

        self.proc = None

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def started(self) -> bool:
        """进程是否曾经成功启动（proc 不为 None 或仍在运行）。"""
        return self.proc is not None


class DevManager:
    """管理所有开发服务"""

    def __init__(self, run_backend: bool = True, run_frontend: bool = True):
        self.services: list[ServiceProcess] = []
        self._exit_event = threading.Event()
        self._restarting = False

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
                strict_port=False,
            ))

    def start_all(self) -> None:
        for svc in self.services:
            svc.start()

    def stop_all(self) -> None:
        for svc in reversed(self.services):
            svc.stop()

    def restart_all(self) -> None:
        log_sys("正在重启所有服务...")
        self._restarting = True
        try:
            self.stop_all()
            self._wait_ports_released()
            self.start_all()
        finally:
            self._restarting = False
        log_ok("重启完成")

    def _wait_ports_released(self, timeout: float = 5.0) -> None:
        """轮询等待所有服务端口释放，替代硬编码 sleep。"""
        deadline = time.monotonic() + timeout
        ports = [svc.port for svc in self.services]
        while time.monotonic() < deadline:
            if not any(is_port_in_use(p) for p in ports):
                return
            time.sleep(0.3)
        stuck = [p for p in ports if is_port_in_use(p)]
        if stuck:
            log_sys(f"端口 {stuck} 仍被占用，继续启动...")

    def check_health(self) -> bool:
        """检查是否有服务意外退出"""
        if self._exit_event.is_set() or self._restarting:
            return True
        for svc in self.services:
            if svc.proc and not svc.alive:
                ret = svc.proc.returncode
                log_err(f"{svc.name} 意外退出 (code={ret})")
                return False
        return True

    def request_exit(self) -> None:
        """请求主循环退出（线程安全）。"""
        self._exit_event.set()

    @property
    def should_exit(self) -> bool:
        return self._exit_event.is_set()


# ── 交互式命令监听 ────────────────────────────────────────

def _input_listener(manager: DevManager) -> None:
    """监听用户键盘输入，支持交互式命令"""
    while not manager.should_exit:
        try:
            cmd = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            break
        if cmd in ("r", "restart"):
            manager.restart_all()
        elif cmd in ("q", "quit", "exit"):
            log_sys("用户请求退出")
            manager.request_exit()
            break
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

    run_backend = args.backend or (not args.backend and not args.frontend)
    run_frontend = args.frontend or (not args.backend and not args.frontend)

    print(f"""
{C.BOLD}{C.CYAN}╔══════════════════════════════════════════╗
║     Lumina Studio 2.0 — Dev Launcher     ║
╚══════════════════════════════════════════╝{C.RESET}
""")

    venv_py = _find_venv_python()
    log_sys(f"Python: {venv_py}")

    if run_frontend and not _check_npm_available():
        log_err("未找到 npm，请先安装 Node.js（https://nodejs.org/）")
        sys.exit(1)

    manager = DevManager(run_backend=run_backend, run_frontend=run_frontend)

    def shutdown(sig: int, _: object) -> None:
        sig_name = signal.Signals(sig).name
        log_sys(f"收到 {sig_name}，正在退出...")
        manager.request_exit()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    manager.start_all()

    backend_svc = next((s for s in manager.services if s.name == "Backend"), None)
    frontend_svc = next((s for s in manager.services if s.name == "Frontend"), None)

    started_svcs = [svc for svc in manager.services if svc.started]
    for svc in started_svcs:
        svc.port_detected.wait(timeout=5.0)

    if not started_svcs:
        log_err("没有服务成功启动，请检查端口占用后重试")
        sys.exit(1)

    actual_backend_port = backend_svc.actual_port if backend_svc else BACKEND_PORT
    actual_frontend_port = frontend_svc.actual_port if frontend_svc else FRONTEND_PORT

    started_names = " + ".join(svc.name for svc in started_svcs)
    failed_svcs = [svc for svc in manager.services if not svc.started]
    if failed_svcs:
        failed_names = ", ".join(svc.name for svc in failed_svcs)
        log_ok(f"{started_names} 已启动（{failed_names} 启动失败）")
    else:
        log_ok(f"{started_names} 已启动")

    url_lines: list[str] = []
    if backend_svc and backend_svc.started:
        url_lines.append(f"  Backend:  {C.CYAN}http://localhost:{actual_backend_port}{C.RESET}")
    if frontend_svc and frontend_svc.started:
        url_lines.append(f"  Frontend: {C.BLUE}http://localhost:{actual_frontend_port}{C.RESET}")
    urls = "\n".join(url_lines)

    print(f"""
{C.DIM}────────────────────────────────────────────{C.RESET}
{urls}
{C.DIM}────────────────────────────────────────────{C.RESET}
  {C.GREEN}r{C.RESET}=重启  {C.GREEN}s{C.RESET}=状态  {C.GREEN}q{C.RESET}=退出  {C.GREEN}h{C.RESET}=帮助
{C.DIM}────────────────────────────────────────────{C.RESET}
""")

    input_thread = threading.Thread(target=_input_listener, args=(manager,), daemon=True)
    input_thread.start()

    restart_count = 0
    last_restart_time: Optional[float] = None
    auto_restart_exhausted = False

    try:
        while not manager.should_exit:
            if not manager.check_health():
                if not auto_restart_exhausted:
                    restart_count += 1
                    last_restart_time = time.monotonic()
                    if restart_count > MAX_AUTO_RESTART:
                        log_err(f"已连续自动重启 {MAX_AUTO_RESTART} 次，停止重试。请检查服务日志。")
                        log_sys("按 r 手动重启，或 q 退出")
                        auto_restart_exhausted = True
                    else:
                        log_sys(f"检测到服务异常退出，自动重启 ({restart_count}/{MAX_AUTO_RESTART})...")
                        manager.restart_all()
            elif restart_count > 0 and last_restart_time is not None:
                if time.monotonic() - last_restart_time > HEALTHY_RESET_WINDOW:
                    restart_count = 0
                    last_restart_time = None
                    auto_restart_exhausted = False
            time.sleep(POLL_INTERVAL)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        log_sys("正在退出...")
        manager.stop_all()


if __name__ == "__main__":
    main()
