#!/usr/bin/env python3
"""Unified Lumina Studio launcher.

Starts the backend and frontend, supports selective startup/restart, and cleans
child processes on startup and shutdown.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
FRONTEND_DIR = ROOT / "frontend"
BACKEND_PORT = 8000
FRONTEND_PORT = 4174
FRONTEND_PORT_RANGE = [FRONTEND_PORT + i for i in range(6)]
WINDOWS_COMMAND_SHIMS = {"pnpm"}

_R = "\033[0m"
_B = "\033[1m"
_DIM = "\033[2m"
_COLORS = {
    "main-backend": "\033[36m",
    "main-frontend": "\033[34m",
    "SYS": "\033[33m",
    "OK": "\033[32m",
    "ERR": "\033[31m",
}

_job = None


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _log(tag: str, msg: str) -> None:
    color = _COLORS.get(tag, "")
    print(f"{_DIM}{_ts()}{_R} {color}{_B}[{tag}]{_R} {msg}", flush=True)


def _sys(msg: str) -> None:
    _log("SYS", msg)


def _ok(msg: str) -> None:
    _log("OK", msg)


def _err(msg: str) -> None:
    _log("ERR", msg)


def _enable_ansi() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleMode(
            ctypes.windll.kernel32.GetStdHandle(-11), 7
        )
    except Exception:
        pass


def _init_job() -> None:
    global _job
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.windll.kernel32
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.OpenProcess.restype = wintypes.HANDLE

        job = kernel.CreateJobObjectW(None, None)
        if not job:
            return

        class _BasicLimitInfo(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_void_p),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64),
            ]

        class _ExtendedLimitInfo(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimitInfo),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = _ExtendedLimitInfo()
        info.BasicLimitInformation.LimitFlags = 0x2000
        if kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            _job = job
        else:
            kernel.CloseHandle(job)
    except Exception as exc:
        _err(f"failed to initialize Windows Job Object: {exc}")


def _assign_to_job(pid: int) -> None:
    if os.name != "nt" or not _job:
        return
    try:
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x0201, False, pid)
        if handle:
            kernel.AssignProcessToJobObject(_job, handle)
            kernel.CloseHandle(handle)
    except Exception:
        pass


def _kill_job() -> None:
    global _job
    if os.name != "nt" or not _job:
        return
    try:
        import ctypes
        ctypes.windll.kernel32.TerminateJobObject(_job, 1)
        ctypes.windll.kernel32.CloseHandle(_job)
    except Exception:
        pass
    _job = None


def _find_python() -> str:
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        return sys.executable
    candidates = [
        ROOT / ".venv312" / "bin" / "python",
        ROOT / ".venv" / "bin" / "python",
        ROOT / "venv" / "bin" / "python",
        ROOT / ".venv312" / "Scripts" / "python.exe",
        ROOT / ".venv" / "Scripts" / "python.exe",
        ROOT / "venv" / "Scripts" / "python.exe",
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return sys.executable


def _find_node() -> str:
    from shutil import which

    return which("node") or "node"


PYTHON = _find_python()


def _package_manager_cmd(*args: str, os_name: str | None = None) -> list[str]:
    cmd = ["pnpm", *args]
    if (os_name or os.name) == "nt" and cmd[0] in WINDOWS_COMMAND_SHIMS:
        return ["cmd", "/c", *cmd]
    return cmd


def _frontend_cmd() -> list[str]:
    vite_args = ["--host", "0.0.0.0", "--port", str(FRONTEND_PORT)]
    vite_js = FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    if vite_js.exists():
        return [_find_node(), str(vite_js), *vite_args]
    return _package_manager_cmd("dev", "--", *vite_args)


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _wait_port_free(port: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _port_in_use(port):
            return True
        time.sleep(0.3)
    return not _port_in_use(port)


def _get_process_cmdline(pid: int) -> str:
    if os.name != "nt":
        return ""
    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        f"$p = Get-CimInstance Win32_Process -Filter 'ProcessId={pid}';"
        "if (-not $p) { $p = Get-WmiObject Win32_Process -Filter "
        f"'ProcessId={pid}' }};"
        "if ($p) { Write-Output $p.CommandLine }"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=0x08000000,
            timeout=5,
        ).stdout
        if out.strip():
            return out.strip()
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["wmic", "process", "where", f"ProcessId={pid}", "get", "CommandLine", "/VALUE"],
            capture_output=True,
            text=True,
            creationflags=0x08000000,
            timeout=5,
        ).stdout
        for line in out.splitlines():
            if line.startswith("CommandLine="):
                return line[12:]
    except Exception:
        pass
    return ""


def _get_posix_cmdline(pid: int) -> str:
    if os.name == "nt":
        return ""
    try:
        return subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _is_project_process(pid: int) -> bool:
    cmdline = (_get_process_cmdline(pid) if os.name == "nt" else _get_posix_cmdline(pid))
    if not cmdline:
        return False
    markers = [
        "api_server.py",
        str(ROOT),
        str(FRONTEND_DIR),
        "Lumina-Layers",
    ]
    return any(marker and marker in cmdline for marker in markers)


def _kill_pid_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(pid)],
            capture_output=True,
            creationflags=0x08000000,
        )
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def _windows_listening_pids(ports: list[int]) -> list[tuple[int, int]]:
    if os.name != "nt":
        return []
    try:
        out = subprocess.run(
            "netstat -ano",
            shell=True,
            capture_output=True,
            encoding="gbk",
            errors="ignore",
            creationflags=0x08000000,
            timeout=10,
        ).stdout
    except Exception as exc:
        _err(f"failed to scan listening ports: {exc}")
        return []

    wanted = "|".join(str(port) for port in ports)
    matches: list[tuple[int, int]] = []
    for line in out.splitlines():
        match = re.search(rf"\s+TCP\s+[\d\.\[\]:]+:({wanted})\s+\S+\s+LISTENING\s+(\d+)", line)
        if match:
            matches.append((int(match.group(2)), int(match.group(1))))
    return matches


def _sweep_windows_ports(ports: list[int], force: bool = False) -> None:
    seen: set[int] = set()
    for pid, port in _windows_listening_pids(ports):
        if pid == os.getpid() or pid in seen:
            continue
        seen.add(pid)
        if force or _is_project_process(pid):
            _kill_pid_tree(pid)
            _sys(f"terminated leftover PID {pid} on port {port}")
        else:
            _sys(f"skipped PID {pid} on port {port}; not a Lumina process")


def _sweep_posix_port(port: int, force: bool = False) -> None:
    if os.name == "nt":
        return
    try:
        out = subprocess.run(
            ["lsof", "-tiTCP:" + str(port), "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return
    for pid_str in out.split():
        try:
            pid = int(pid_str)
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        if not force and not _is_project_process(pid):
            _sys(f"skipped PID {pid} on port {port}; not a Lumina process")
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            _sys(f"killed leftover listener PID {pid} on port {port}")
        except (ProcessLookupError, PermissionError, OSError):
            pass


def _clean_startup_ports(run_backend: bool, run_frontend: bool, force: bool = False) -> None:
    ports: list[int] = []
    if run_backend:
        ports.append(BACKEND_PORT)
    if run_frontend:
        ports.extend(FRONTEND_PORT_RANGE)
    if not ports:
        return
    _sys("cleaning leftover Lumina processes...")
    if os.name == "nt":
        _sweep_windows_ports(ports, force=force)
    else:
        for port in ports:
            _sweep_posix_port(port, force=force)
    _kill_lumina_node_orphans()
    if run_backend:
        _wait_port_free(BACKEND_PORT, timeout=10)
    _ok("cleanup complete")


def _kill_lumina_node_orphans() -> None:
    """Kill leftover frontend/test helper processes that belong to this repo.

    Port listeners catch the active Vite server, but wrapper parents such as
    pnpm/npm/cmd and helper children such as esbuild may not be LISTENing when
    cleanup runs.  Scan command lines and kill only processes clearly tied to
    this project.
    """
    if os.name != "nt":
        return
    try:
        script = (
            "$ErrorActionPreference='SilentlyContinue';"
            "Get-CimInstance Win32_Process | "
            "ForEach-Object { \"$($_.ProcessId)|$($_.Name)|$($_.CommandLine)\" }"
        )
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=0x08000000,
            timeout=10,
        ).stdout
    except Exception as exc:
        _err(f"failed to scan project helper processes: {exc}")
        return

    root = str(ROOT).lower()
    frontend = str(FRONTEND_DIR).lower()
    killed: set[int] = set()
    for line in out.splitlines():
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid == os.getpid() or pid in killed:
            continue
        name = (parts[1] or "").lower()
        cmdline = (parts[2] or "").lower()
        belongs_here = root in cmdline or frontend in cmdline or "lumina-layers" in cmdline
        if not belongs_here:
            continue
        is_helper = (
            name in {"node.exe", "cmd.exe", "esbuild.exe"}
            and any(token in cmdline for token in (
                "vite", "vitest", "esbuild", "pnpm", "npm", "node_modules",
            ))
        )
        if not is_helper:
            continue
        _kill_pid_tree(pid)
        killed.add(pid)
        _sys(f"terminated Lumina helper leftover PID {pid}")
    if killed:
        _ok(f"helper cleanup complete ({len(killed)} process trees)")


class Service:
    def __init__(
        self,
        key: str,
        name: str,
        cmd: list[str],
        cwd: Path,
        url: str,
        port: int,
        vite_cache_dir: Path | None = None,
    ) -> None:
        self.key = key
        self.name = name
        self.cmd = cmd
        self.cwd = cwd
        self.url = url
        self.port = port
        self.vite_cache_dir = vite_cache_dir
        self.proc: subprocess.Popen | None = None
        self.actual_port = port
        self._port_seen = threading.Event()

    def start(self) -> bool:
        if self.alive:
            _sys(f"{self.name} already running (pid={self.proc.pid})")
            return True
        try:
            flags = 0
            if os.name == "nt":
                flags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000
            self.proc = subprocess.Popen(
                self.cmd,
                cwd=str(self.cwd),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=flags,
                start_new_session=(os.name != "nt"),
            )
        except FileNotFoundError as exc:
            _err(f"{self.name} failed to start: {exc}")
            return False
        except Exception as exc:
            _err(f"{self.name} failed to start: {exc}")
            return False
        _assign_to_job(self.proc.pid)
        threading.Thread(target=self._pump, daemon=True).start()
        _log(self.name, f"started (pid={self.proc.pid})")
        return True

    def _pump(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        try:
            for raw in self.proc.stdout:
                line = raw.rstrip("\n")
                if not line:
                    continue
                _log(self.name, line)
                if self.vite_cache_dir is not None and not self._port_seen.is_set():
                    clean = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", line)
                    match = re.search(r"http://(?:localhost|127\.0\.0\.1):(\d+)", clean)
                    if match:
                        self.actual_port = int(match.group(1))
                        self._port_seen.set()
        except (ValueError, OSError):
            pass

    def stop(self) -> None:
        if self.proc is None or self.proc.poll() is not None:
            self.proc = None
            self._sweep_port()
            return
        _log(self.name, "stopping...")
        if os.name == "nt":
            _kill_pid_tree(self.proc.pid)
        else:
            self._signal_posix(signal.SIGTERM)
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._signal_posix(signal.SIGKILL)
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass
        self.proc = None
        self._sweep_port()

    def _signal_posix(self, sig: int) -> None:
        if self.proc is None:
            return
        try:
            os.killpg(os.getpgid(self.proc.pid), sig)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                os.kill(self.proc.pid, sig)
            except (ProcessLookupError, PermissionError, OSError):
                pass

    def _sweep_port(self) -> None:
        ports = [self.port]
        if self.vite_cache_dir is not None:
            ports = sorted(set(FRONTEND_PORT_RANGE + [self.actual_port]))
        if os.name == "nt":
            _sweep_windows_ports(ports, force=False)
        else:
            for port in ports:
                _sweep_posix_port(port, force=False)

    def restart(self) -> None:
        _log(self.name, "restarting...")
        self.stop()
        if self.vite_cache_dir is not None:
            self._clean_vite_cache()
        if self.port == BACKEND_PORT:
            _wait_port_free(BACKEND_PORT, timeout=10)
        elif self.vite_cache_dir is not None:
            for port in sorted(set(FRONTEND_PORT_RANGE + [self.actual_port])):
                _wait_port_free(port, timeout=3)
        time.sleep(0.5)
        self._port_seen.clear()
        self.actual_port = self.port
        self.start()

    def _clean_vite_cache(self) -> None:
        if self.vite_cache_dir is None or not self.vite_cache_dir.exists():
            return
        try:
            import shutil
            shutil.rmtree(self.vite_cache_dir, ignore_errors=False)
            _log(self.name, f"cleared vite cache at {self.vite_cache_dir}")
        except OSError as exc:
            _err(f"{self.name} failed to clear vite cache: {exc}")

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


def build_services(run_backend: bool, run_frontend: bool) -> list[Service]:
    services: list[Service] = []
    if run_backend:
        services.append(Service(
            "1", "main-backend", [PYTHON, "api_server.py"], ROOT,
            f"http://localhost:{BACKEND_PORT}", BACKEND_PORT,
        ))
    if run_frontend:
        services.append(Service(
            "2", "main-frontend", _frontend_cmd(), FRONTEND_DIR,
            f"http://localhost:{FRONTEND_PORT}", FRONTEND_PORT,
            vite_cache_dir=FRONTEND_DIR / "node_modules" / ".vite",
        ))
    return services


def restart_all_services(services: list[Service], run_backend: bool, run_frontend: bool) -> None:
    """Stop everything, run one cleanup pass, then start everything again."""
    _sys("restarting all services...")
    for svc in services:
        svc.stop()
    _clean_startup_ports(run_backend, run_frontend, force=False)
    for svc in services:
        if svc.vite_cache_dir is not None:
            svc._clean_vite_cache()
        svc._port_seen.clear()
        svc.actual_port = svc.port
    time.sleep(0.5)
    for svc in services:
        svc.start()


def print_banner(services: list[Service]) -> None:
    print(f"\n{_B}  Lumina Studio — Unified Launcher{_R}")
    print(f"{_DIM}  python: {PYTHON}{_R}")
    print(f"{_DIM}  ──────────────────────────────────────────────{_R}")
    for svc in services:
        color = _COLORS.get(svc.name, "")
        print(f"   {color}[{svc.key}] {svc.name:<14}{_R} {svc.url}")
    print(f"{_DIM}  ──────────────────────────────────────────────{_R}")
    print(
        f"   {_B}1-2{_R}=restart one  {_B}b{_R}=backend  {_B}f{_R}=frontend  "
        f"{_B}r{_R}=all  {_B}s{_R}=status  {_B}q{_R}=quit"
    )
    print(f"{_DIM}  ──────────────────────────────────────────────{_R}\n")


def _check_dependencies(run_backend: bool, run_frontend: bool) -> bool:
    """Check selected services before port cleanup or process creation."""
    ready = True
    if run_backend:
        try:
            result = subprocess.run(
                [PYTHON, "api_server.py", "--check-dependencies"],
                cwd=ROOT, timeout=60,
            )
            ready = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired) as exc:
            _err(f"Cannot check backend dependencies with {PYTHON}: {exc}")
            ready = False
    if run_frontend:
        from scripts.source_dependencies import check_frontend_dependencies

        for issue in check_frontend_dependencies(FRONTEND_DIR):
            _err(issue)
            ready = False
    return ready


def main() -> None:
    parser = argparse.ArgumentParser(description="Unified launcher for Lumina Studio")
    parser.add_argument("--backend", action="store_true", help="start only the backend")
    parser.add_argument("--frontend", action="store_true", help="start only the frontend")
    parser.add_argument("--kill", action="store_true", help="clean leftover Lumina processes and exit")
    parser.add_argument("--force", "-f", action="store_true", help="with --kill, kill any listener on Lumina ports")
    parser.add_argument("--check-dependencies", action="store_true", help="check selected services without starting them")
    args = parser.parse_args()

    _enable_ansi()
    run_backend = args.backend or not args.frontend
    run_frontend = args.frontend or not args.backend

    if args.kill:
        if args.force:
            _sys("force cleanup: terminating any listener on Lumina ports...")
        else:
            _sys("cleanup: terminating only Lumina project leftovers...")
        _clean_startup_ports(True, True, force=args.force)
        return

    if not _check_dependencies(run_backend, run_frontend):
        raise SystemExit(1)
    if args.check_dependencies:
        return

    _init_job()
    _clean_startup_ports(run_backend, run_frontend, force=False)

    services = build_services(run_backend, run_frontend)
    by_key = {svc.key: svc for svc in services}
    stopping = threading.Event()

    print_banner(services)
    for svc in services:
        svc.start()

    def shutdown() -> None:
        if stopping.is_set():
            return
        stopping.set()
        _sys("shutting down services...")
        for svc in services:
            svc.stop()
        _clean_startup_ports(run_backend, run_frontend, force=False)
        _kill_job()

    def exit_now(code: int = 0) -> None:
        shutdown()
        os._exit(code)

    def on_signal(_signum, _frame) -> None:
        exit_now(0)

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            handler_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)

            def on_console(ctrl: int) -> bool:
                if ctrl in (2, 5, 6):
                    shutdown()
                    os._exit(0)
                return False

            console_handler = handler_type(on_console)
            ctypes.windll.kernel32.SetConsoleCtrlHandler(console_handler, True)
            setattr(shutdown, "_console_handler", console_handler)
        except Exception:
            pass

    def show_status() -> None:
        for svc in services:
            state = f"{_COLORS['OK']}running{_R}" if svc.alive else f"{_COLORS['ERR']}stopped{_R}"
            url = f"http://localhost:{svc.actual_port}" if svc.vite_cache_dir is not None else svc.url
            _log(svc.name, f"[{svc.key}] {state} {url}")

    def input_loop() -> None:
        while not stopping.is_set():
            try:
                cmd = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                break
            if not cmd:
                continue
            if cmd in by_key:
                by_key[cmd].restart()
            elif cmd == "b":
                for svc in services:
                    if svc.name.endswith("backend"):
                        svc.restart()
            elif cmd == "f":
                for svc in services:
                    if svc.name.endswith("frontend"):
                        svc.restart()
            elif cmd == "r":
                restart_all_services(services, run_backend, run_frontend)
            elif cmd == "s":
                show_status()
            elif cmd in ("q", "quit", "exit"):
                exit_now(0)
            else:
                _sys(f"unknown command: {cmd!r} (use 1-2 / b / f / r / s / q)")

    threading.Thread(target=input_loop, daemon=True).start()

    reported: set[str] = set()
    try:
        while not stopping.is_set():
            time.sleep(1)
            for svc in services:
                if svc.proc is not None and not svc.alive and svc.name not in reported:
                    _err(f"{svc.name} exited (code={svc.proc.returncode}). Press [{svc.key}] to restart.")
                    reported.add(svc.name)
                elif svc.alive and svc.name in reported:
                    reported.discard(svc.name)
    finally:
        shutdown()


if __name__ == "__main__":
    main()
