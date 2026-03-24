#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lumina Studio 2.0 — 开发环境启动器（跨平台）

功能：
  - 一键启动 Backend (FastAPI :8000) + Frontend (Vite :5174)
  - 启动前自动清理残留端口和僵尸进程
  - Windows: Job Object 确保子进程随父进程终止
  - Linux/WSL: start_new_session 隔离子进程组
  - 彩色日志输出，区分 Backend / Frontend
  - 优雅退出（Ctrl+C 或关闭窗口时自动清理所有子进程）

用法：
    python start_dev.py              # 启动前后端
    python start_dev.py --backend    # 仅启动后端
    python start_dev.py --frontend   # 仅启动前端
    python start_dev.py --kill       # 清理残留进程后退出
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
import atexit
from typing import Optional, List
from pathlib import Path

# Windows 特定导入
if os.name == "nt":
    import ctypes
    from ctypes import wintypes

# 模块级引用，防止 ctypes 控制台回调被 GC 回收后成为悬空指针
_console_handler_ref = None

ROOT_DIR = Path(__file__).parent.resolve()
FRONTEND_DIR = ROOT_DIR / "frontend"

BACKEND_PORT = 8000
FRONTEND_PORT = 5180
POLL_INTERVAL = 0.5
SHUTDOWN_TIMEOUT = 5
MAX_AUTO_RESTART = 3
STARTUP_GRACE_PERIOD = 10

_shutdown_event = threading.Event()

# ── Windows Job Object 支持 ─────────────────────────────────

if os.name == "nt":
    kernel32 = ctypes.windll.kernel32

    # 常量定义
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE 只在 ExtendedLimitInformation (class=9) 里有效
    JobObjectExtendedLimitInformation = 9

    # 确保 CreateJobObjectW / OpenProcess 返回 64 位 HANDLE（不设置会被截断为 32 位）
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.OpenProcess.restype = wintypes.HANDLE

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        """对应 JOBOBJECT_BASIC_LIMIT_INFORMATION，字段顺序与 Windows SDK 一致"""
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit",     ctypes.c_int64),
            ("LimitFlags",              wintypes.DWORD),
            ("MinimumWorkingSetSize",   ctypes.c_size_t),
            ("MaximumWorkingSetSize",   ctypes.c_size_t),
            ("ActiveProcessLimit",      wintypes.DWORD),
            ("Affinity",                ctypes.c_void_p),
            ("PriorityClass",           wintypes.DWORD),
            ("SchedulingClass",         wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount",  ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount",   ctypes.c_uint64),
            ("WriteTransferCount",  ctypes.c_uint64),
            ("OtherTransferCount",  ctypes.c_uint64),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        """对应 JOBOBJECT_EXTENDED_LIMIT_INFORMATION（class=9），支持 KILL_ON_JOB_CLOSE"""
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo",                IO_COUNTERS),
            ("ProcessMemoryLimit",    ctypes.c_size_t),
            ("JobMemoryLimit",        ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed",     ctypes.c_size_t),
        ]

    def create_job_object() -> Optional[wintypes.HANDLE]:
        """创建 Windows Job Object；父进程退出时 OS 关闭 handle，触发 KILL_ON_JOB_CLOSE"""
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None

        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        ok = kernel32.SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not ok:
            kernel32.CloseHandle(job)
            return None

        return job

    def assign_process_to_job(job: wintypes.HANDLE, pid: int) -> bool:
        """将指定进程加入 Job Object"""
        try:
            # 需要 PROCESS_SET_QUOTA 和 PROCESS_TERMINATE 权限
            proc_handle = kernel32.OpenProcess(0x0200 | 0x0001, False, pid)
            if not proc_handle:
                return False
            result = kernel32.AssignProcessToJobObject(job, proc_handle)
            kernel32.CloseHandle(proc_handle)
            return bool(result)
        except Exception:
            return False

    def terminate_job(job: wintypes.HANDLE) -> None:
        """强制终止 Job Object 中的所有进程"""
        if job:
            kernel32.TerminateJobObject(job, 1)
            kernel32.CloseHandle(job)

# ── 颜色工具 ──────────────────────────────────────────────

class C:
    """ANSI 颜色常量"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    CYAN = "\033[36m"
    DIM = "\033[2m"

    # Windows CMD 支持
    @classmethod
    def enable_windows_colors(cls):
        if os.name == "nt":
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)


def _log(tag: str, color: str, msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"{C.DIM}{ts}{C.RESET} {color}{C.BOLD}[{tag}]{C.RESET} {msg}", flush=True)


def log_sys(msg: str) -> None:
    _log("SYS", C.YELLOW, msg)


def log_ok(msg: str) -> None:
    _log(" OK", C.GREEN, msg)


def log_err(msg: str) -> None:
    _log("ERR", C.RED, msg)


def log_info(msg: str) -> None:
    _log("INFO", C.BLUE, msg)


# ── 工具函数 ──────────────────────────────────────────────

def find_venv_python() -> str:
    """查找项目 venv 中的 Python 解释器"""
    candidates = [
        ROOT_DIR / "venv" / "Scripts" / "python.exe",
        ROOT_DIR / ".venv" / "Scripts" / "python.exe",
        ROOT_DIR / "venv" / "bin" / "python",
        ROOT_DIR / ".venv" / "bin" / "python",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return sys.executable


def find_npm() -> str:
    """查找 npm 可执行文件路径"""
    # 首先尝试虚拟环境中的 npm
    candidates = [
        ROOT_DIR / "frontend" / "node_modules" / ".bin" / "npm.cmd",
        ROOT_DIR / "frontend" / "node_modules" / ".bin" / "npm",
    ]
    
    # 检查虚拟环境目录
    venv_node = ROOT_DIR / "venv" / "Scripts" / "npm.cmd"
    if venv_node.exists():
        candidates.insert(0, venv_node)
    
    for p in candidates:
        if p.exists():
            return str(p)
    
    # 尝试在 PATH 中查找
    try:
        if os.name == "nt":
            which_cmd = ["where", "npm.cmd"]
            kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW}
        else:
            which_cmd = ["which", "npm"]
            kwargs = {}
        result = subprocess.run(
            which_cmd, capture_output=True, text=True, **kwargs,
        )
        if result.returncode == 0:
            paths = result.stdout.strip().splitlines()
            if paths:
                return paths[0].strip()
    except Exception:
        pass
    
    # 默认回退
    return "npm"


def is_port_in_use(port: int) -> bool:
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def get_processes_using_port(port: int) -> List[int]:
    """获取占用指定端口的进程 PID 列表（跨平台）"""
    pids = []
    try:
        if os.name == "nt":
            # Windows: 使用 netstat 和 findstr
            result = subprocess.run(
                ["netstat", "-ano", "|", "findstr", f":{port}"],
                capture_output=True,
                text=True,
                shell=True,
                encoding="gbk",
                errors="ignore"
            )
            for line in result.stdout.splitlines():
                match = re.search(r"\s+(\d+)\s*$", line)
                if match:
                    pid = int(match.group(1))
                    if pid not in pids:
                        pids.append(pid)
        else:
            # Linux/WSL: lsof → ss → fuser 级联查找，直到找到 PID
            try:
                result = subprocess.run(
                    ["lsof", "-ti", f":{port}"],
                    capture_output=True, text=True,
                )
                for pid_str in result.stdout.strip().split():
                    if pid_str.isdigit():
                        pids.append(int(pid_str))
            except FileNotFoundError:
                pass

            if not pids:
                try:
                    result = subprocess.run(
                        ["ss", "-tlnp", "sport", "=", f":{port}"],
                        capture_output=True, text=True,
                    )
                    for m in re.finditer(r"pid=(\d+)", result.stdout):
                        pid = int(m.group(1))
                        if pid not in pids:
                            pids.append(pid)
                except FileNotFoundError:
                    pass

            if not pids:
                try:
                    result = subprocess.run(
                        ["fuser", f"{port}/tcp"],
                        capture_output=True, text=True,
                    )
                    for pid_str in result.stdout.strip().split():
                        if pid_str.isdigit():
                            pids.append(int(pid_str))
                except FileNotFoundError:
                    pass
    except Exception as e:
        log_err(f"获取端口 {port} 进程失败: {e}")
    return pids


def kill_process_tree(pid: int, force: bool = False) -> bool:
    """终止进程及其所有子进程"""
    try:
        if os.name == "nt":
            # Windows: 使用 taskkill /T 终止进程树
            cmd = ["taskkill", "/T", "/F" if force else "", "/PID", str(pid)]
            cmd = [c for c in cmd if c]  # 移除空字符串
            result = subprocess.run(
                cmd,
                capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            return result.returncode == 0
        else:
            sig = signal.SIGKILL if force else signal.SIGTERM
            try:
                subprocess.run(
                    ["pkill", f"-{int(sig)}", "-P", str(pid)],
                    capture_output=True,
                )
            except FileNotFoundError:
                pass
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
            return True
    except Exception as e:
        log_err(f"终止进程 {pid} 失败: {e}")
        return False



def cleanup_residual_processes() -> None:
    """清理可能残留的进程"""
    log_sys("正在清理残留进程...")

    # 1. 检查并终止占用端口的进程
    for port in [BACKEND_PORT, FRONTEND_PORT]:
        if is_port_in_use(port):
            log_sys(f"端口 {port} 被占用，正在查找并终止相关进程...")
            pids = get_processes_using_port(port)
            for pid in pids:
                if pid != os.getpid():  # 不要自杀
                    kill_process_tree(pid, force=True)
                    log_info(f"已终止占用端口 {port} 的进程 (PID: {pid})")

    # 2. 尝试终止可能残留的 python 进程（运行 api_server.py 的）
    if os.name == "nt":
        # 使用 wmic 查找运行 api_server.py 的 python 进程
        try:
            result = subprocess.run(
                ["wmic", "process", "where", "CommandLine like '%api_server.py%'", "get", "ProcessId"],
                capture_output=True,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            for line in result.stdout.splitlines()[1:]:  # 跳过标题行
                pid_str = line.strip()
                if pid_str.isdigit():
                    pid = int(pid_str)
                    if pid != os.getpid():
                        kill_process_tree(pid, force=True)
                        log_info(f"已终止残留后端进程 (PID: {pid})")
        except Exception:
            pass
    else:
        try:
            result = subprocess.run(
                ["pgrep", "-f", "api_server.py"],
                capture_output=True, text=True,
            )
            for line in result.stdout.strip().splitlines():
                pid_str = line.strip()
                if pid_str.isdigit():
                    pid = int(pid_str)
                    if pid != os.getpid():
                        kill_process_tree(pid, force=True)
                        log_info(f"已终止残留后端进程 (PID: {pid})")
        except FileNotFoundError:
            pass

    # 等待端口释放（重试）
    ports_to_check = [BACKEND_PORT, FRONTEND_PORT]
    for attempt in range(6):
        still_busy = [p for p in ports_to_check if is_port_in_use(p)]
        if not still_busy:
            break
        if attempt == 0:
            log_sys("等待端口释放...")
        time.sleep(0.5)

    if still_busy:
        # 所有工具均未能清理，尝试 fuser -k 强杀
        if os.name != "nt":
            for p in still_busy:
                try:
                    subprocess.run(["fuser", "-k", f"{p}/tcp"], capture_output=True)
                    log_info(f"已通过 fuser 强制释放端口 {p}")
                except FileNotFoundError:
                    pass
            time.sleep(0.5)
            still_busy = [p for p in still_busy if is_port_in_use(p)]

    if still_busy:
        log_err(f"端口 {', '.join(map(str, still_busy))} 仍被占用")
    else:
        log_ok("清理完成")


# ── 进程管理 ──────────────────────────────────────────────

class ServiceProcess:
    """封装一个子服务进程，确保正确管理和清理"""

    _job_handle: Optional[int] = None  # Windows Job Object HANDLE

    def __init__(self, name: str, cmd: List[str], cwd: Path, port: int, color: str):
        self.name = name
        self.cmd = cmd
        self.cwd = cwd
        self.port = port
        self.actual_port = port
        self.port_detected = threading.Event()
        self.color = color
        self.proc: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()
        self._start_time: float = 0.0

    @classmethod
    def set_job_handle(cls, handle) -> None:
        """设置全局 Job Object 句柄"""
        cls._job_handle = handle

    def start(self) -> bool:
        """启动服务进程，返回是否成功"""
        self._shutdown_event.clear()

        # 检查端口
        if is_port_in_use(self.port):
            log_err(f"端口 {self.port} 仍被占用，启动失败")
            return False

        _log(self.name, self.color, f"启动中... (port={self.port})")

        try:
            # Windows 特定标志
            creationflags = 0
            if os.name == "nt":
                # CREATE_NEW_PROCESS_GROUP: 允许独立接收 Ctrl+C
                # CREATE_NO_WINDOW: 不创建控制台窗口
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW

            self.proc = subprocess.Popen(
                self.cmd,
                cwd=str(self.cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags if os.name == "nt" else 0,
                start_new_session=(os.name != "nt"),
                shell=False,
            )
            self._start_time = time.monotonic()

            # 将进程加入 Job Object（Windows）
            if os.name == "nt" and self._job_handle and self.proc.pid:
                assign_process_to_job(self._job_handle, self.proc.pid)

            # 启动输出读取线程
            self._reader_thread = threading.Thread(
                target=self._stream_output,
                daemon=True,
            )
            self._reader_thread.start()

            _log(self.name, self.color, f"已启动 (pid={self.proc.pid})")
            return True

        except Exception as e:
            log_err(f"启动 {self.name} 失败: {e}")
            return False

    def _stream_output(self) -> None:
        """实时转发子进程输出，持续读取直到管道关闭"""
        if not self.proc or not self.proc.stdout:
            return

        try:
            for line in self.proc.stdout:
                line = line.rstrip("\n")
                if line:
                    _log(self.name, self.color, line)
                    if self.name == "Frontend" and not self.port_detected.is_set():
                        clean_line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line)
                        match = re.search(r"http://(?:localhost|127\.0\.0\.1|\[::1\]):(\d+)", clean_line)
                        if match:
                            self.actual_port = int(match.group(1))
                            self.port_detected.set()
        except (ValueError, OSError):
            if not self._shutdown_event.is_set():
                log_err(f"{self.name} 输出管道异常断开")

        if self.proc and not self._shutdown_event.is_set():
            ret = self.proc.poll()
            if ret is not None and ret != 0:
                _log(self.name, self.color,
                     f"{C.RED}进程退出，退出码: {ret}{C.RESET}")

    def stop(self, timeout: int = SHUTDOWN_TIMEOUT) -> None:
        """优雅地停止服务进程"""
        self._shutdown_event.set()

        if not self.proc:
            return

        if self.proc.poll() is not None:
            if self._reader_thread:
                self._reader_thread.join(timeout=2)
            self.proc = None
            return

        _log(self.name, self.color, f"正在停止 (pid={self.proc.pid})...")

        # 1. 尝试优雅终止
        try:
            if os.name == "nt":
                try:
                    ctypes.windll.kernel32.GenerateConsoleCtrlEvent(1, self.proc.pid)
                    time.sleep(0.5)
                except Exception:
                    pass
            else:
                # start_new_session=True 保证子进程是独立进程组组长，
                # killpg(child_pid) 不会误杀父进程
                try:
                    os.killpg(self.proc.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                except OSError:
                    self.proc.terminate()
        except Exception:
            pass

        # 2. 等待进程退出
        try:
            self.proc.wait(timeout=timeout)
            _log(self.name, self.color, "已停止")
            if self._reader_thread:
                self._reader_thread.join(timeout=2)
            self.proc = None
            return
        except subprocess.TimeoutExpired:
            pass

        # 3. 强制终止
        _log(self.name, self.color, "强制终止...")
        try:
            if os.name == "nt":
                kill_process_tree(self.proc.pid, force=True)
            else:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except OSError:
                    self.proc.kill()

            self.proc.wait(timeout=3)
            _log(self.name, self.color, "已强制终止")
        except Exception as e:
            log_err(f"终止 {self.name} 失败: {e}")

        if self._reader_thread:
            self._reader_thread.join(timeout=2)
        self.proc = None

    @property
    def alive(self) -> bool:
        """检查进程是否仍在运行"""
        return self.proc is not None and self.proc.poll() is None


# ── 开发管理器 ──────────────────────────────────────────────

class DevManager:
    """管理所有开发服务"""

    def __init__(self, run_backend: bool = True, run_frontend: bool = True):
        self.services: List[ServiceProcess] = []
        self._shutdown = False
        self._lock = threading.Lock()

        # 查找 Python 解释器
        venv_python = find_venv_python()

        if run_backend:
            self.services.append(ServiceProcess(
                name="Backend",
                cmd=[venv_python, "api_server.py"],
                cwd=ROOT_DIR,
                port=BACKEND_PORT,
                color=C.CYAN,
            ))

        if run_frontend:
            # 查找 npm 并使用正确的命令格式
            npm_cmd = find_npm()
            
            # Windows 上如果 npm 是 .cmd 文件，需要通过 cmd /c 执行
            if os.name == "nt" and (npm_cmd.endswith(".cmd") or npm_cmd.endswith(".bat")):
                cmd = ["cmd", "/c", npm_cmd, "run", "dev"]
            else:
                cmd = [npm_cmd, "run", "dev"]
            
            self.services.append(ServiceProcess(
                name="Frontend",
                cmd=cmd,
                cwd=FRONTEND_DIR,
                port=FRONTEND_PORT,
                color=C.BLUE,
            ))

    def start_all(self) -> None:
        """启动所有服务"""
        with self._lock:
            self._shutdown = False
            for svc in self.services:
                if not svc.start():
                    log_err(f"{svc.name} 启动失败")

    def stop_all(self) -> None:
        """停止所有服务"""
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True

            # 使用线程并发停止，加快退出速度
            threads = []
            for svc in reversed(self.services):
                t = threading.Thread(target=svc.stop)
                t.start()
                threads.append(t)

            for t in threads:
                t.join(timeout=SHUTDOWN_TIMEOUT + 2)

    def restart_all(self) -> None:
        """重启所有服务"""
        log_sys("正在重启所有服务...")
        self.stop_all()
        time.sleep(1)
        # 清理可能残留的进程
        cleanup_residual_processes()
        self.start_all()
        log_ok("重启完成")

    def check_health(self) -> bool:
        """检查服务健康状况，返回是否需要自动重启

        启动失败（STARTUP_GRACE_PERIOD 内退出）不触发自动重启。
        """
        if self._shutdown:
            return True

        all_healthy = True
        for svc in self.services:
            if svc.proc and not svc.alive:
                ret = svc.proc.returncode
                if svc._reader_thread:
                    svc._reader_thread.join(timeout=2)
                uptime = time.monotonic() - svc._start_time
                if uptime < STARTUP_GRACE_PERIOD:
                    log_err(
                        f"{svc.name} 启动失败 (退出码={ret}，运行 {uptime:.1f}s)，"
                        f"请检查上方错误日志"
                    )
                    svc.proc = None
                else:
                    log_err(f"{svc.name} 意外退出 (退出码={ret}，运行 {uptime:.1f}s)")
                    all_healthy = False

        return all_healthy


# ── 主程序 ──────────────────────────────────────────────

def print_banner():
    """打印启动横幅"""
    print(f"""
{C.BOLD}{C.CYAN}╔══════════════════════════════════════════╗
║     Lumina Studio 2.0 — Dev Launcher     ║
╚══════════════════════════════════════════╝{C.RESET}
""")


def print_help():
    """打印帮助信息"""
    print(f"""
{C.BOLD}可用命令：{C.RESET}
  {C.GREEN}r{C.RESET} / restart  — 重启所有服务
  {C.GREEN}s{C.RESET} / status   — 查看服务状态
  {C.GREEN}k{C.RESET} / kill     — 清理残留进程
  {C.GREEN}q{C.RESET} / quit     — 退出
  {C.GREEN}h{C.RESET} / help     — 显示帮助
""")


def print_status(manager: DevManager):
    """打印服务状态"""
    for svc in manager.services:
        status = f"{C.GREEN}运行中{C.RESET}" if svc.alive else f"{C.RED}已停止{C.RESET}"
        pid = svc.proc.pid if svc.proc else "-"
        _log(svc.name, svc.color, f"状态: {status} (PID: {pid})")


def input_listener(manager: DevManager):
    """监听用户输入命令"""
    while not _shutdown_event.is_set():
        try:
            cmd = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if cmd in ("r", "restart"):
            manager.restart_all()
        elif cmd in ("s", "status"):
            print_status(manager)
        elif cmd in ("k", "kill"):
            cleanup_residual_processes()
        elif cmd in ("q", "quit", "exit"):
            log_sys("用户请求退出...")
            _shutdown_event.set()
        elif cmd in ("h", "help", "?"):
            print_help()


def setup_signal_handlers(manager: DevManager):
    """设置信号处理器（仅设置退出标志，由主循环负责清理）"""
    def signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        log_sys(f"收到信号 {sig_name}，正在退出...")
        _shutdown_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Windows 特定: 处理控制台关闭事件
    if os.name == "nt":
        try:
            def console_handler(ctrl_type):
                # 只处理 Python signal handler 捕获不到的事件（窗口关闭、注销）
                # CTRL_C_EVENT(0) 和 CTRL_BREAK_EVENT(1) 已由 signal_handler 处理，不在此拦截
                if ctrl_type in (2, 6):  # CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT
                    log_sys("检测到控制台关闭，正在清理...")
                    manager.stop_all()
                    if ServiceProcess._job_handle:
                        terminate_job(ServiceProcess._job_handle)
                    # 必须显式退出，否则 Python 主循环继续运行，终端无法归还
                    os._exit(0)
                return False

            global _console_handler_ref
            console_handler_cftype = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
            # 必须存入模块级变量，否则函数返回后 ctypes 对象被 GC，回调成悬空指针
            _console_handler_ref = console_handler_cftype(console_handler)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(_console_handler_ref, True)
        except Exception as e:
            log_err(f"设置控制台处理器失败: {e}")


def main():
    parser = argparse.ArgumentParser(description="Lumina Studio 开发启动器")
    parser.add_argument("--backend", action="store_true", help="仅启动后端")
    parser.add_argument("--frontend", action="store_true", help="仅启动前端")
    parser.add_argument("--kill", action="store_true", help="仅清理残留进程")
    args = parser.parse_args()

    # 启用 Windows 颜色支持
    C.enable_windows_colors()

    # 仅清理模式
    if args.kill:
        print_banner()
        cleanup_residual_processes()
        return

    # 确定启动哪些服务
    run_backend = args.backend or (not args.backend and not args.frontend)
    run_frontend = args.frontend or (not args.backend and not args.frontend)

    print_banner()

    # 初始化 Windows Job Object
    if os.name == "nt":
        job = create_job_object()
        if job:
            ServiceProcess.set_job_handle(job)
            log_ok("已启用 Windows Job Object 进程管理")
        else:
            log_err("创建 Job Object 失败，进程可能无法正确清理")

    # 预清理残留进程
    cleanup_residual_processes()

    # 创建管理器
    manager = DevManager(run_backend=run_backend, run_frontend=run_frontend)

    # 注册退出清理
    atexit.register(manager.stop_all)

    # 设置信号处理
    setup_signal_handlers(manager)

    # 启动服务
    manager.start_all()

    # 等待前端端口检测
    frontend_svc = next((svc for svc in manager.services if svc.name == "Frontend"), None)
    actual_frontend_port = FRONTEND_PORT
    if frontend_svc:
        if frontend_svc.port_detected.wait(timeout=5.0):
            actual_frontend_port = frontend_svc.actual_port

    # 打印启动信息（只显示实际启动的服务）
    running = [svc for svc in manager.services if svc.alive]
    failed = [svc for svc in manager.services if not svc.alive]

    if running:
        svc_names = " + ".join(svc.name for svc in running)
        log_ok(f"{svc_names} 已启动")
    for svc in failed:
        log_err(f"{svc.name} 未能启动")

    backend_up = any(s.name == "Backend" for s in running)
    frontend_up = any(s.name == "Frontend" for s in running)

    print(f"\n{C.DIM}────────────────────────────────────────────{C.RESET}")
    if backend_up:
        print(f"  Backend:  {C.CYAN}http://localhost:{BACKEND_PORT}{C.RESET}")
    if frontend_up:
        print(f"  Frontend: {C.BLUE}http://localhost:{actual_frontend_port}{C.RESET}")
    print(f"""{C.DIM}────────────────────────────────────────────{C.RESET}
  {C.GREEN}r{C.RESET}=重启  {C.GREEN}s{C.RESET}=状态  {C.GREEN}k{C.RESET}=清理  {C.GREEN}q{C.RESET}=退出  {C.GREEN}h{C.RESET}=帮助
{C.DIM}────────────────────────────────────────────{C.RESET}
""")

    # 启动输入监听线程
    input_thread = threading.Thread(target=input_listener, args=(manager,), daemon=True)
    input_thread.start()

    # 主循环：健康检查
    restart_count = 0
    while not _shutdown_event.is_set():
        if not manager.check_health():
            restart_count += 1
            if restart_count > MAX_AUTO_RESTART:
                log_err(f"已连续自动重启 {MAX_AUTO_RESTART} 次，停止重试。请检查服务日志。")
                log_sys("按 r 手动重启，或 q 退出")
            else:
                log_sys(f"检测到服务异常，自动重启 ({restart_count}/{MAX_AUTO_RESTART})...")
                manager.restart_all()
        else:
            restart_count = 0
        _shutdown_event.wait(POLL_INTERVAL)

    log_sys("正在退出...")
    manager.stop_all()

    if os.name == "nt" and ServiceProcess._job_handle:
        try:
            terminate_job(ServiceProcess._job_handle)
        except Exception:
            pass

    # 强制退出，避免 input() 阻塞在 stdin 导致进程挂起
    os._exit(0)


if __name__ == "__main__":
    main()
