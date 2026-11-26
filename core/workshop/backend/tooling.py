"""Pinned uv tool access and backend interpreter providers.

The host invokes uv as a subprocess with private cache and interpreter
directories, ignoring user configuration and never touching the user's PATH,
registry, or development environment.
宿主以子进程方式调用固定版本的 uv，使用私有缓存与解释器目录，忽略用户配置，
不修改用户的 PATH、注册表或开发环境。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol
from urllib.parse import unquote, urlsplit

import psutil

from ..constants import BACKEND_PYTHON_VERSIONS
from ..errors import WorkshopBackendError
from .downloads import DownloadBatch, DownloadProgress, download_https, ordered_sources, source_id


PINNED_UV_VERSION = "0.13.7"
_UV_COMMAND_TIMEOUT_SECONDS = 3_600.0
_POLL_SECONDS = 0.1
_OUTPUT_TAIL_CHARS = 4_000
# Environment variables that would redirect uv, pip, or a virtualenv away
# from host-owned locations. Removed before every uv invocation.
_TOOL_ENVIRONMENT_PREFIXES = ("UV_", "PIP_", "CONDA_", "PYTHON")
_TOOL_ENVIRONMENT_NAMES = frozenset({"VIRTUAL_ENV", "PYENV_VERSION"})


class CancelToken:
    """Thread-safe cooperative cancellation flag for runtime operations."""

    def __init__(self) -> None:
        self._event = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise WorkshopBackendError(
                "cancelled",
                "The backend operation was cancelled.",
            )

    def wait(self, seconds: float) -> bool:
        return self._event.wait(seconds)


@contextmanager
def cancellable_lock(lock: threading.Lock, cancel: CancelToken | None) -> Iterator[None]:
    if cancel is None:
        with lock:
            yield
        return
    while not lock.acquire(timeout=0.15):
        cancel.raise_if_cancelled()
    try:
        cancel.raise_if_cancelled()
        yield
    finally:
        lock.release()


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def _kill_process_tree(process: subprocess.Popen[bytes]) -> None:
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
    except psutil.Error:
        children = []
    for child in children:
        try:
            child.kill()
        except psutil.Error:
            pass
    try:
        process.kill()
    except OSError:
        pass


def run_tool_command(
    command: Sequence[str],
    *,
    env: dict[str, str],
    cancel: CancelToken | None,
    timeout_seconds: float,
    cwd: Path | None = None,
) -> CommandResult:
    """Run one tool command, honoring cancellation and a hard timeout.

    运行一个工具命令，支持取消与硬超时。
    """

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen(
            list(command),
            env=env,
            cwd=str(cwd) if cwd else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creationflags,
        )
    except OSError as exc:
        raise WorkshopBackendError(
            "backend-tool-unavailable",
            "The backend dependency tool could not be started.",
        ) from exc
    outputs: dict[str, bytes] = {}

    def drain(name: str, stream) -> None:  # type: ignore[no-untyped-def]
        outputs[name] = stream.read()

    readers = [
        threading.Thread(target=drain, args=("stdout", process.stdout), daemon=True),
        threading.Thread(target=drain, args=("stderr", process.stderr), daemon=True),
    ]
    for reader in readers:
        reader.start()
    deadline = time.monotonic() + timeout_seconds
    try:
        while process.poll() is None:
            if cancel is not None and cancel.cancelled:
                _kill_process_tree(process)
                process.wait()
                cancel.raise_if_cancelled()
            if time.monotonic() >= deadline:
                _kill_process_tree(process)
                process.wait()
                raise WorkshopBackendError(
                    "backend-tool-timeout",
                    "The backend dependency tool did not finish in time.",
                )
            time.sleep(_POLL_SECONDS)
    finally:
        for reader in readers:
            reader.join(timeout=5)
    return CommandResult(
        returncode=process.returncode,
        stdout=outputs.get("stdout", b"").decode("utf-8", "replace"),
        stderr=outputs.get("stderr", b"").decode("utf-8", "replace"),
    )


def _frozen_tool_directory() -> Path | None:
    bundle = getattr(sys, "_MEIPASS", None)
    if not getattr(sys, "frozen", False) or not bundle:
        return None
    return Path(bundle) / "workshop-tools"


def locate_uv_executable() -> Path | None:
    """Find the pinned uv binary: explicit override, frozen bundle, package.

    依次查找显式配置、冻结包内置目录和 uv Python 包提供的 uv 可执行文件。
    """

    override = os.environ.get("LUMINA_WORKSHOP_UV", "").strip()
    if override:
        candidate = Path(override).expanduser()
        return candidate if candidate.is_file() else None
    executable_name = "uv.exe" if os.name == "nt" else "uv"
    frozen = _frozen_tool_directory()
    if frozen is not None:
        candidate = frozen / executable_name
        return candidate if candidate.is_file() else None
    try:
        from uv import find_uv_bin
    except ImportError:
        return None
    try:
        return Path(find_uv_bin())
    except FileNotFoundError:
        return None


def isolated_tool_environment(
    base: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return the host environment without uv/pip/venv redirection."""

    source = dict(os.environ if base is None else base)
    return {
        key: value
        for key, value in source.items()
        if not key.upper().startswith(_TOOL_ENVIRONMENT_PREFIXES)
        and key.upper() not in _TOOL_ENVIRONMENT_NAMES
        and not key.upper().startswith("LUMINA_")
    }


class UvTool:
    """Run the pinned uv binary against host-private directories.

    使用宿主私有目录调用固定版本的 uv。
    """

    def __init__(
        self,
        executable: Path,
        *,
        cache_dir: Path,
        python_install_dir: Path,
        download_staging_dir: Path | None = None,
        timeout_seconds: float = _UV_COMMAND_TIMEOUT_SECONDS,
    ) -> None:
        self.executable = Path(executable)
        self.cache_dir = Path(cache_dir)
        self.python_install_dir = Path(python_install_dir)
        self._download_staging_dir = download_staging_dir or self.cache_dir
        self._python_downloads: dict[str, tuple[str, str]] = {}
        self.timeout_seconds = timeout_seconds

    def environment(self) -> dict[str, str]:
        env = isolated_tool_environment()
        env.update(
            {
                "UV_NO_CONFIG": "1",
                "UV_CACHE_DIR": str(self.cache_dir),
                "UV_PYTHON_INSTALL_DIR": str(self.python_install_dir),
                "UV_PYTHON_INSTALL_BIN": "0",
                "UV_PYTHON_INSTALL_REGISTRY": "0",
                "UV_LINK_MODE": "hardlink",
                "UV_NO_PROGRESS": "1",
                "UV_NO_MODIFY_PATH": "1",
                # Only an explicit ``uv python install`` may download Python.
                "UV_PYTHON_DOWNLOADS": "manual",
            }
        )
        return env

    def run(
        self,
        *arguments: str,
        cancel: CancelToken | None = None,
        failure_code: str,
        failure_message: str,
    ) -> CommandResult:
        result = run_tool_command(
            [str(self.executable), *arguments],
            env=self.environment(),
            cancel=cancel,
            timeout_seconds=self.timeout_seconds,
        )
        if result.returncode != 0:
            error = WorkshopBackendError(failure_code, failure_message)
            error.tool_output = result.stderr[-_OUTPUT_TAIL_CHARS:]  # type: ignore[attr-defined]
            raise error
        return result

    def version(self) -> str:
        result = self.run(
            "--version",
            failure_code="backend-tool-unavailable",
            failure_message="The backend dependency tool is unavailable.",
        )
        parts = result.stdout.split()
        return parts[1] if len(parts) > 1 else result.stdout.strip()

    def create_venv(
        self,
        target: Path,
        python_executable: Path,
        *,
        cancel: CancelToken | None,
    ) -> None:
        self.run(
            "venv",
            str(target),
            "--python",
            str(python_executable),
            "--relocatable",
            "--no-project",
            cancel=cancel,
            failure_code="environment-create-failed",
            failure_message="The backend environment could not be created.",
        )

    def sync(
        self,
        python_executable: Path,
        lock_path: Path,
        *,
        offline: bool,
        cancel: CancelToken | None,
    ) -> None:
        arguments = [
            "pip",
            "sync",
            str(lock_path),
            "--python",
            str(python_executable),
            "--strict",
        ]
        if offline:
            arguments.append("--offline")
        self.run(
            *arguments,
            cancel=cancel,
            failure_code="dependency-install-failed",
            failure_message=(
                "Backend dependencies could not be downloaded or verified. "
                "Check the network or mirror settings, then retry."
            ),
        )

    def install_python(
        self,
        python_version: str,
        *,
        mirror: str | None,
        cancel: CancelToken | None,
    ) -> None:
        arguments = [
            "python",
            "install",
            python_version,
            "--install-dir",
            str(self.python_install_dir),
            "--no-bin",
            "--no-registry",
        ]
        if mirror:
            arguments.extend(["--mirror", mirror])
        self.run(
            *arguments,
            cancel=cancel,
            failure_code="interpreter-install-failed",
            failure_message="The backend Python runtime could not be downloaded, verified or installed.",
        )

    def find_python(self, python_version: str) -> Path | None:
        result = run_tool_command(
            [
                str(self.executable),
                "python",
                "find",
                python_version,
                "--managed-python",
                "--no-project",
            ],
            env=self.environment(),
            cancel=None,
            timeout_seconds=120,
        )
        if result.returncode != 0:
            return None
        candidate = Path(result.stdout.strip().splitlines()[-1]) if result.stdout.strip() else None
        if candidate is None or not candidate.is_file():
            return None
        try:
            candidate.resolve().relative_to(self.python_install_dir.resolve())
        except ValueError:
            return None
        return candidate

    def preferred_python_download(
        self, python_version: str, cancel: CancelToken | None = None,
    ) -> tuple[str, str]:
        if cancel is not None:
            cancel.raise_if_cancelled()
        cached = self._python_downloads.get(python_version)
        if cached is not None:
            return cached
        result = self.run(
            "python", "list", f"cpython@{python_version}", "--only-downloads", "--output-format", "json",
            cancel=cancel,
            failure_code="interpreter-install-failed",
            failure_message="The Python runtime download could not be identified.",
        )
        entries = json.loads(result.stdout)
        for item in entries:
            if item.get("implementation") == "cpython" and item.get("url"):
                distribution = str(item["version"]), str(item["url"])
                self._python_downloads[python_version] = distribution
                return distribution
        raise WorkshopBackendError("interpreter-install-failed", "No compatible Python runtime is available.")

    def download_and_install_python(
        self,
        python_version: str,
        *,
        mirrors: tuple[str, ...],
        preferred: str,
        configured_mirror: str | None = None,
        cancel: CancelToken | None,
        progress: Callable[[DownloadProgress], None],
        installing: Callable[[], None],
    ) -> None:
        version, primary = self.preferred_python_download(python_version, cancel)
        revision, filename = urlsplit(primary).path.rsplit("/", 2)[-2:]
        archive_name = unquote(filename)
        if Path(archive_name).name != archive_name or not revision.isascii() or not revision.isdigit():
            raise WorkshopBackendError("interpreter-install-failed", "The Python runtime download path is invalid.")
        candidates = tuple(f"{mirror.rstrip('/')}/{revision}/{filename}" for mirror in mirrors)
        configured = f"{configured_mirror.rstrip('/')}/{revision}/{filename}" if configured_mirror else None
        if configured is not None:
            if preferred == "auto":
                primary, configured = configured, primary
            candidates = (configured, *candidates)
        urls = ordered_sources(primary, candidates, preferred)
        self._download_staging_dir.mkdir(parents=True, exist_ok=True)
        last_error: WorkshopBackendError | None = None
        for url in urls:
            batch = DownloadBatch((None,), progress)
            try:
                with TemporaryDirectory(prefix="python-download-", dir=self._download_staging_dir) as directory:
                    local_mirror = Path(directory)
                    archive = local_mirror / revision / archive_name
                    archive.parent.mkdir()
                    download_https(
                        url, archive, cancel=cancel, progress=batch.attempt(0, archive_name, url)
                    )
                    installing()
                    # uv verifies the archive against its embedded distribution checksum.
                    self.install_python(version, mirror=local_mirror.as_uri(), cancel=cancel)
                    return
            except WorkshopBackendError as exc:
                if exc.code == "cancelled":
                    raise
                last_error = exc
        message = "The Python runtime could not be downloaded and installed."
        if last_error is not None:
            message += f" {source_id(url) or 'Download source'}: {last_error}"
        raise WorkshopBackendError("interpreter-install-failed", message) from last_error

    def uninstall_python(self, python_version: str) -> None:
        self.run(
            "python",
            "uninstall",
            python_version,
            "--install-dir",
            str(self.python_install_dir),
            failure_code="interpreter-remove-failed",
            failure_message="The unused backend Python runtime could not be removed.",
        )

    def clean_cache(self) -> None:
        if not self.cache_dir.exists():
            return
        self.run(
            "cache",
            "clean",
            failure_code="cache-clean-failed",
            failure_message="The backend download cache could not be cleaned.",
        )


@dataclass(frozen=True, slots=True)
class BackendInterpreter:
    """One interpreter used to create backend environments."""

    key: str
    python_version: str
    executable: Path
    managed: bool


class InterpreterProvider(Protocol):
    def ensure(
        self,
        python_version: str,
        cancel: CancelToken | None,
    ) -> BackendInterpreter: ...

    def release(self, interpreter: BackendInterpreter) -> int: ...

    def installed(self) -> tuple[BackendInterpreter, ...]: ...


def _directory_bytes(path: Path) -> int:
    total = 0
    seen: set[tuple[int, int]] = set()
    for directory, _dirs, files in os.walk(path):
        for name in files:
            try:
                stat = (Path(directory) / name).lstat()
            except OSError:
                continue
            key = (stat.st_dev, stat.st_ino)
            if key in seen:
                continue
            seen.add(key)
            total += stat.st_size
    return total


class ManagedInterpreterProvider:
    """Download one shared CPython minor version into the runtime directory.

    将共享的 CPython 小版本下载到运行时私有目录，按小版本复用。
    """

    def __init__(self, uv: UvTool, *, mirror: str | None = None) -> None:
        self._uv = uv
        self._mirror = mirror
        self._lock = threading.Lock()
        self._installed_lock = threading.Lock()
        self._installed_cache: tuple[BackendInterpreter, ...] | None = None

    def ensure(
        self,
        python_version: str,
        cancel: CancelToken | None,
        *,
        mirrors: tuple[str, ...] = (),
        preferred: str = "auto",
        progress: Callable[[DownloadProgress], None] | None = None,
        installing: Callable[[], None] = lambda: None,
    ) -> BackendInterpreter:
        with cancellable_lock(self._lock, cancel):
            executable = self._uv.find_python(python_version)
            if executable is None:
                # Status requests can read the last complete snapshot during installation.
                self.installed()
                try:
                    if progress is None:
                        self._uv.install_python(python_version, mirror=self._mirror, cancel=cancel)
                    else:
                        self._uv.download_and_install_python(
                            python_version, mirrors=mirrors, preferred=preferred,
                            configured_mirror=self._mirror, cancel=cancel,
                            progress=progress, installing=installing,
                        )
                finally:
                    with self._installed_lock:
                        self._installed_cache = None
                executable = self._uv.find_python(python_version)
            if executable is None:
                raise WorkshopBackendError(
                    "interpreter-install-failed",
                    "The backend Python runtime is unavailable after installation.",
                )
            return BackendInterpreter(
                key=f"managed-{python_version}",
                python_version=python_version,
                executable=executable,
                managed=True,
            )

    def release(self, interpreter: BackendInterpreter) -> int:
        if not interpreter.managed:
            return 0
        with self._lock:
            self.installed()
            before = _directory_bytes(self._uv.python_install_dir)
            try:
                self._uv.uninstall_python(interpreter.python_version)
            finally:
                with self._installed_lock:
                    self._installed_cache = None
            after = _directory_bytes(self._uv.python_install_dir)
            return max(0, before - after)

    def installed(self) -> tuple[BackendInterpreter, ...]:
        with self._installed_lock:
            if self._installed_cache is not None:
                return self._installed_cache
            found: list[BackendInterpreter] = []
            if self._uv.python_install_dir.is_dir():
                for version in sorted(BACKEND_PYTHON_VERSIONS):
                    executable = self._uv.find_python(version)
                    if executable is not None:
                        found.append(
                            BackendInterpreter(
                                key=f"managed-{version}",
                                python_version=version,
                                executable=executable,
                                managed=True,
                            )
                        )
            self._installed_cache = tuple(found)
            return self._installed_cache

    def preview_version(self, python_version: str) -> str | None:
        for interpreter in self.installed():
            if interpreter.python_version == python_version:
                return preview_python_version(interpreter.executable)
        version, _url = self._uv.preferred_python_download(python_version)
        return version


def read_python_version(executable: Path, cancel: CancelToken | None = None) -> str | None:
    result = run_tool_command(
        [str(executable), "-I", "-c", "import platform; print(platform.python_version())"],
        env=isolated_tool_environment(), cancel=cancel, timeout_seconds=15,
    )
    return result.stdout.strip() if result.returncode == 0 else None


@lru_cache(maxsize=32)
def _cached_python_version(executable: Path, _modified_ns: int) -> str | None:
    return read_python_version(executable)


def preview_python_version(executable: Path) -> str | None:
    try:
        return _cached_python_version(executable, executable.stat().st_mtime_ns)
    except OSError:
        return None


def _interpreter_minor(executable: Path) -> str | None:
    result = run_tool_command(
        [
            str(executable),
            "-I",
            "-c",
            "import sys; print('%d.%d' % sys.version_info[:2])",
        ],
        env=isolated_tool_environment(),
        cancel=None,
        timeout_seconds=60,
    )
    return result.stdout.strip() if result.returncode == 0 else None


class ExternalInterpreterProvider:
    """Use an explicitly configured interpreter; never install or delete it.

    使用显式配置的解释器（开发或离线场景），宿主从不安装或删除它。
    """

    def __init__(self, executable: Path) -> None:
        self._executable = Path(executable)
        self._verified: dict[str, BackendInterpreter] = {}

    def ensure(
        self,
        python_version: str,
        cancel: CancelToken | None,
    ) -> BackendInterpreter:
        if cancel is not None:
            cancel.raise_if_cancelled()
        cached = self._verified.get(python_version)
        if cached is not None:
            return cached
        if not self._executable.is_file():
            raise WorkshopBackendError(
                "interpreter-unavailable",
                "The configured backend Python interpreter does not exist.",
            )
        if _interpreter_minor(self._executable) != python_version:
            raise WorkshopBackendError(
                "interpreter-version-mismatch",
                f"The configured backend interpreter is not Python {python_version}.",
            )
        interpreter = BackendInterpreter(
            key=f"external-{python_version}",
            python_version=python_version,
            executable=self._executable,
            managed=False,
        )
        self._verified[python_version] = interpreter
        return interpreter

    def release(self, interpreter: BackendInterpreter) -> int:
        return 0

    def installed(self) -> tuple[BackendInterpreter, ...]:
        return tuple(self._verified.values())

    def preview_version(self, python_version: str) -> str | None:
        version = preview_python_version(self._executable)
        return version if version and version.startswith(python_version + ".") else None


def remove_python_install_dir_if_empty(path: Path) -> None:
    """Remove an empty managed interpreter root left after uninstall."""

    try:
        if path.is_dir() and not any(path.iterdir()):
            shutil.rmtree(path)
    except OSError:
        pass
