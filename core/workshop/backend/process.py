"""One module backend process and its dedicated control channel.

Local-process mode: a module backend runs with the user's own permissions.
Separate processes, environments, and environment allowlists keep the host
environment clean and make resources attributable; they are not an OS
permission sandbox.

本机进程模式：模块后端以用户自身权限运行。独立进程、环境和变量白名单用于保持
宿主环境干净、资源可归属，并不是操作系统级权限沙箱。
"""

from __future__ import annotations

import os
import subprocess
import threading
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psutil

from api.structured_logging import get_logger

from ..constants import MAX_BACKEND_PROTOCOL_MESSAGE_BYTES
from ..errors import WorkshopBackendError
from .protocol import (
    CONTROL_ENVIRONMENT_VARIABLE,
    PROTOCOL_VERSION,
    ProtocolError,
    decode_backend_message,
    encode_message,
)


log = get_logger(__name__)

_WINDOWS_ENVIRONMENT = frozenset(
    {
        "ALLUSERSPROFILE", "APPDATA", "COMMONPROGRAMFILES", "COMMONPROGRAMFILES(X86)",
        "COMMONPROGRAMW6432", "COMPUTERNAME", "COMSPEC", "HOMEDRIVE", "HOMEPATH",
        "LOCALAPPDATA", "NUMBER_OF_PROCESSORS", "OS", "PATH", "PATHEXT",
        "PROCESSOR_ARCHITECTURE", "PROCESSOR_IDENTIFIER", "PROCESSOR_LEVEL",
        "PROCESSOR_REVISION", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
        "PROGRAMW6432", "PUBLIC", "SYSTEMDRIVE", "SYSTEMROOT", "USERDOMAIN",
        "USERNAME", "USERPROFILE", "WINDIR",
    }
)
_POSIX_ENVIRONMENT = frozenset({"HOME", "LANG", "LOGNAME", "PATH", "SHELL", "TZ", "USER"})
_SHARED_ENVIRONMENT = frozenset(
    {
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
        "http_proxy", "https_proxy", "no_proxy", "all_proxy",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    }
)
_ALLOWED_PREFIXES = ("LC_", "CUDA_", "NVIDIA_")
_CACHE_VARIABLES = ("XDG_CACHE_HOME", "HF_HOME", "TORCH_HOME", "NUMBA_CACHE_DIR", "MPLCONFIGDIR", "CUPY_CACHE_DIR")
_OUTPUT_TAIL_LINES = 40
_OUTPUT_LINE_CHARS = 500


def backend_environment(
    *,
    scratch_dir: Path,
    extra: Mapping[str, str],
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return an allowlisted environment with writes redirected per module.

    The desktop token, Lumina settings, PyInstaller loader variables, and
    library paths of the host never reach module code.
    桌面令牌、Lumina 配置、冻结程序的加载变量与宿主库路径不会传给模块代码。
    """

    source = dict(os.environ if base is None else base)
    allowed = _WINDOWS_ENVIRONMENT if os.name == "nt" else _POSIX_ENVIRONMENT
    environment: dict[str, str] = {}
    for key, value in source.items():
        upper = key.upper() if os.name == "nt" else key
        if upper in allowed or key in _SHARED_ENVIRONMENT or upper.startswith(_ALLOWED_PREFIXES):
            environment[key] = value
    temporary = scratch_dir / "tmp"
    cache = scratch_dir / "cache"
    temporary.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    for name in ("TMP", "TEMP", "TMPDIR"):
        environment[name] = str(temporary)
    for name in _CACHE_VARIABLES:
        environment[name] = str(cache / name.lower())
    environment["PYTHONIOENCODING"] = "utf-8"
    environment.update(extra)
    return environment


@dataclass(frozen=True, slots=True)
class BackendLaunch:
    """Everything needed to start one backend process."""

    python: Path
    bootstrap: Path
    backend_dir: Path
    entry: Path
    scratch_dir: Path
    work_dir: Path
    extra_environment: dict[str, str] = field(default_factory=dict)


class BackendProcess:
    """Start, talk to, and terminate one backend process tree.

    启动并与一个后端进程通信，必要时终止整棵进程树。
    """

    def __init__(
        self,
        launch: BackendLaunch,
        *,
        on_message: Callable[[dict[str, Any]], None],
        on_exit: Callable[[int | None, str | None], None],
        log_fields: Mapping[str, object],
    ) -> None:
        self._launch = launch
        self._on_message = on_message
        self._on_exit = on_exit
        self._log_fields = dict(log_fields)
        self._process: subprocess.Popen[bytes] | None = None
        self._job: Any = None
        self._writer: Any = None
        self._write_lock = threading.Lock()
        self._output_tail: deque[str] = deque(maxlen=_OUTPUT_TAIL_LINES)
        self._protocol_failure: str | None = None
        self._threads: list[threading.Thread] = []
        self.create_time: float | None = None

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    def output_tail(self) -> str:
        return "\n".join(self._output_tail)[-4000:]

    def start(self) -> None:
        launch = self._launch
        launch.work_dir.mkdir(parents=True, exist_ok=True)
        host_read, child_write = os.pipe()
        child_read, host_write = os.pipe()
        os.set_inheritable(child_read, True)
        os.set_inheritable(child_write, True)
        arguments = [
            str(launch.python),
            "-I",
            "-X",
            "utf8",
            "-X",
            f"pycache_prefix={launch.scratch_dir / 'cache' / 'pycache'}",
            str(launch.bootstrap),
            str(launch.backend_dir),
            str(launch.entry),
        ]
        extra = {
            **launch.extra_environment,
            "LUMINA_WORKSHOP_PROTOCOL": str(PROTOCOL_VERSION),
        }
        try:
            if os.name == "nt":
                self._start_windows(arguments, extra, child_read, child_write)
            else:
                self._start_posix(arguments, extra, child_read, child_write)
        except BaseException:
            for descriptor in (host_read, host_write):
                os.close(descriptor)
            raise
        finally:
            os.close(child_read)
            os.close(child_write)
        self._writer = os.fdopen(host_write, "wb", buffering=0)
        reader = os.fdopen(host_read, "rb")
        assert self._process is not None
        try:
            self.create_time = psutil.Process(self._process.pid).create_time()
        except psutil.Error:
            self.create_time = None
        self._spawn_thread(self._read_protocol, reader)
        self._spawn_thread(self._drain_output, self._process.stdout, "stdout")
        self._spawn_thread(self._drain_output, self._process.stderr, "stderr")
        self._spawn_thread(self._wait_for_exit)

    def _spawn_thread(self, target: Callable[..., None], *args: object) -> None:
        thread = threading.Thread(target=target, args=args, daemon=True)
        self._threads.append(thread)
        thread.start()

    def _start_windows(
        self,
        arguments: list[str],
        extra: dict[str, str],
        child_read: int,
        child_write: int,
    ) -> None:
        import msvcrt

        from .win_job import CREATE_NO_WINDOW, CREATE_SUSPENDED, WindowsJob

        read_handle = msvcrt.get_osfhandle(child_read)
        write_handle = msvcrt.get_osfhandle(child_write)
        environment = backend_environment(
            scratch_dir=self._launch.scratch_dir,
            extra={**extra, CONTROL_ENVIRONMENT_VARIABLE: f"{read_handle},{write_handle}"},
        )
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.lpAttributeList = {"handle_list": [read_handle, write_handle]}
        try:
            process = subprocess.Popen(
                arguments,
                cwd=str(self._launch.work_dir),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                startupinfo=startupinfo,
                creationflags=CREATE_SUSPENDED | CREATE_NO_WINDOW,
            )
        except OSError as exc:
            raise WorkshopBackendError(
                "backend-start-failed",
                "The module backend process could not be started.",
            ) from exc
        self._process = process
        try:
            job = WindowsJob()
            job.assign(process.pid)
            self._job = job
        except OSError as exc:
            # Without a job, targeted stops fall back to a psutil tree walk.
            log.warning(
                "Workshop backend job object unavailable",
                extra={
                    "event": "workshop_backend_job_unavailable",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    **self._log_fields,
                },
            )
        try:
            psutil.Process(process.pid).resume()
        except psutil.Error as exc:
            self.terminate(grace_seconds=0)
            raise WorkshopBackendError(
                "backend-start-failed",
                "The module backend process could not be resumed.",
            ) from exc

    def _start_posix(
        self,
        arguments: list[str],
        extra: dict[str, str],
        child_read: int,
        child_write: int,
    ) -> None:
        environment = backend_environment(
            scratch_dir=self._launch.scratch_dir,
            extra={**extra, CONTROL_ENVIRONMENT_VARIABLE: f"{child_read},{child_write}"},
        )
        try:
            # Stay in the host's process group: Electron's group SIGTERM on
            # quit then reaches backends too; targeted stops walk the tree.
            self._process = subprocess.Popen(
                arguments,
                cwd=str(self._launch.work_dir),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                close_fds=True,
                pass_fds=(child_read, child_write),
            )
        except OSError as exc:
            raise WorkshopBackendError(
                "backend-start-failed",
                "The module backend process could not be started.",
            ) from exc

    def _read_protocol(self, reader: Any) -> None:
        try:
            while True:
                line = reader.readline(MAX_BACKEND_PROTOCOL_MESSAGE_BYTES + 1)
                if not line:
                    return
                if not line.endswith(b"\n"):
                    raise ProtocolError("message exceeds protocol size limit")
                self._on_message(decode_backend_message(line.rstrip(b"\r\n")))
        except ProtocolError as exc:
            self._protocol_failure = str(exc)
            log.warning(
                "Workshop backend protocol violation",
                extra={
                    "event": "workshop_backend_protocol_failed",
                    "error_type": "ProtocolError",
                    "error_message": str(exc),
                    **self._log_fields,
                },
            )
            self.terminate(grace_seconds=0)
        except (OSError, ValueError):
            return
        finally:
            try:
                reader.close()
            except OSError:
                pass

    def _drain_output(self, stream: Any, name: str) -> None:
        try:
            for raw in iter(stream.readline, b""):
                text = raw.decode("utf-8", "replace").rstrip()
                if not text:
                    continue
                text = text[:_OUTPUT_LINE_CHARS]
                self._output_tail.append(text)
                log.debug(
                    "Workshop backend output",
                    extra={
                        "event": "workshop_backend_output",
                        "stream": name,
                        "line": text,
                        **self._log_fields,
                    },
                )
        except (OSError, ValueError):
            return

    def _wait_for_exit(self) -> None:
        assert self._process is not None
        returncode = self._process.wait()
        for thread in self._threads:
            if thread is not threading.current_thread():
                thread.join(timeout=2)
        if self._job is not None:
            self._job.close()
            self._job = None
        try:
            self._writer.close()
        except OSError:
            pass
        self._on_exit(returncode, self._protocol_failure)

    def send(self, message: dict[str, Any]) -> None:
        payload = encode_message(message)
        with self._write_lock:
            if self._writer is None:
                raise OSError("backend control channel is not open")
            self._writer.write(payload)

    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _descendants_without_job(self) -> list[psutil.Process]:
        """Descendants no job object owns (POSIX, or Windows without a job)."""

        process = self._process
        if process is None or self._job is not None or process.poll() is not None:
            return []
        try:
            return psutil.Process(process.pid).children(recursive=True)
        except psutil.Error:
            return []

    def shutdown(self, *, wait_seconds: float, grace_seconds: float) -> None:
        """Ask the backend to exit, then end it and every helper it started.

        A helper outlives its exiting parent on POSIX and can no longer be
        found from it, so the tree is listed before the request. On Windows
        the job object ends the whole tree when the parent exits.
        """

        helpers = self._descendants_without_job()
        try:
            self.send({"type": "shutdown"})
        except (OSError, ValueError):
            pass
        if self.wait(timeout=wait_seconds) is None:
            self.terminate(grace_seconds=grace_seconds)
        _end_processes(helpers, grace_seconds=grace_seconds)

    def terminate(self, *, grace_seconds: float) -> None:
        """End the backend and every descendant; idempotent."""

        process = self._process
        if process is None or process.poll() is not None:
            return
        if self._job is not None:
            self._job.terminate(1)
        else:
            try:
                root = psutil.Process(process.pid)
                members = [root, *root.children(recursive=True)]
            except psutil.Error:
                members = []
            _end_processes(members, grace_seconds=grace_seconds)
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            log.error(
                "Workshop backend did not exit after termination",
                extra={"event": "workshop_backend_terminate_failed", **self._log_fields},
            )

    def wait(self, timeout: float) -> int | None:
        if self._process is None:
            return None
        try:
            return self._process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None


def _end_processes(members: list[psutil.Process], *, grace_seconds: float) -> None:
    """Terminate ``members``, killing any still running after the grace period."""

    signal_method = "terminate" if grace_seconds > 0 else "kill"
    for member in members:
        try:
            getattr(member, signal_method)()
        except psutil.Error:
            pass
    if grace_seconds > 0 and members:
        _gone, alive = psutil.wait_procs(members, timeout=grace_seconds)
        for member in alive:
            try:
                member.kill()
            except psutil.Error:
                pass


def process_tree_alive(pid: int, create_time: float) -> bool:
    try:
        process = psutil.Process(pid)
        return process.create_time() == create_time and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        return psutil.pid_exists(pid)


def kill_recorded_process(pid: int, create_time: float) -> bool:
    """Kill a leftover backend recorded by an earlier host run."""

    if not process_tree_alive(pid, create_time):
        return False
    try:
        root = psutil.Process(pid)
        members = [root, *root.children(recursive=True)]
    except psutil.Error:
        return False
    for member in members:
        try:
            member.kill()
        except psutil.Error:
            pass
    psutil.wait_procs(members, timeout=10)
    return True
