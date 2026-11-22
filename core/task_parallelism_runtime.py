"""Atomic runtime demand state for adaptive task parallelism."""

from __future__ import annotations

from contextlib import contextmanager, suppress
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Callable, Iterator, TextIO, TypeVar
import uuid

DEMAND_SNAPSHOT_VERSION = 1
WORKER_LEASE_VERSION = 1
MAX_REASONABLE_OUTSTANDING_TASKS = 1_000_000
MAX_REASONABLE_LEASED_WORKERS = 1_000_000
# Process identifiers are an OS scalar, not a task-count scalar. Linux's
# configurable pid_max is commonly 4,194,304 and Windows exposes PIDs as a
# DWORD; keep a bounded unsigned-32-bit envelope without coupling it to the
# number of tasks the scheduler may publish.
MAX_REASONABLE_PROCESS_ID = (1 << 32) - 1

WORKER_LEASE_FILENAME = "workers.json"
WORKER_LEASE_LOCK_FILENAME = "workers.lock"
_LEASE_STALE_SECONDS = 24 * 60 * 60
_LEASE_REFRESH_SECONDS = 60.0
_LEASE_LOCK_TIMEOUT_SECONDS = 2.0

_SNAPSHOT_FIELDS = {
    "version",
    "generation",
    "outstanding",
    "outer_max_workers",
    "updated_monotonic_ns",
}
_WORKER_LEASE_FIELDS = {
    "version",
    "generation",
    "leases",
    "updated_monotonic_ns",
}
_WORKER_LEASE_ENTRY_FIELDS = {
    "pid",
    "created",
    "touched",
    "workers",
    "stage",
    "effective_cpu",
}
_RUNTIME_STATE = threading.local()
_LeaseResult = TypeVar("_LeaseResult")


@dataclass(frozen=True)
class OuterDemandState:
    """Describe current outer process-pool demand for one inner stage.

    描述内部阶段可见的外层进程池当前负载。

    Args:
        outer_demand: Active outer demand used as the CPU/memory divisor.
            用作 CPU 与内存除数的外层活跃任务数。
        outer_max_workers: Configured outer process-pool capacity.
            外层进程池配置容量。
        generation: Monotonic publisher generation, or zero for fallback.
            发布器递增代次；回退状态为零。
        snapshot_fallback: Whether configured capacity replaced live state.
            是否因实时状态不可用而回退到配置容量。
    """

    outer_demand: int
    outer_max_workers: int
    generation: int
    snapshot_fallback: bool


def _positive_int(value: object, *, default: int = 1) -> int:
    if isinstance(value, bool):
        return max(1, int(default))
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return max(1, int(default))
    return parsed if parsed > 0 else max(1, int(default))


def _fallback_state(fallback_outer_workers: int) -> OuterDemandState:
    outer_workers = _positive_int(fallback_outer_workers)
    return OuterDemandState(
        outer_demand=outer_workers,
        outer_max_workers=outer_workers,
        generation=0,
        snapshot_fallback=True,
    )


def _snapshot_int(
    payload: dict[str, object],
    key: str,
    *,
    minimum: int,
    maximum: int = sys.maxsize,
) -> int:
    value = payload.get(key)
    if type(value) is not int:
        raise ValueError(f"{key} must be an integer")
    parsed = int(value)
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{key} is outside the accepted range")
    return parsed


def read_outer_demand(
    snapshot_path: str | os.PathLike[str] | None,
    *,
    fallback_outer_workers: int,
) -> OuterDemandState:
    """Read one atomic demand snapshot or fail closed to configured demand.

    读取一次原子负载快照；文件无效时安全回退到配置的外层并发数。

    Args:
        snapshot_path: Pool-owned JSON snapshot path, when installed.
            进程池拥有的 JSON 快照路径；未安装时为 ``None``。
        fallback_outer_workers: Configured outer capacity used on read failure.
            读取失败时使用的外层配置容量。

    Returns:
        Validated live state or a conservative fallback state.
        校验后的实时状态或保守回退状态。
    """

    fallback = _fallback_state(fallback_outer_workers)
    if snapshot_path is None:
        return fallback
    try:
        path = Path(os.fspath(snapshot_path))
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or set(payload) != _SNAPSHOT_FIELDS:
            return fallback
        version = _snapshot_int(
            payload,
            "version",
            minimum=DEMAND_SNAPSHOT_VERSION,
            maximum=DEMAND_SNAPSHOT_VERSION,
        )
        if version != DEMAND_SNAPSHOT_VERSION:
            return fallback
        generation = _snapshot_int(payload, "generation", minimum=0)
        outstanding = _snapshot_int(
            payload,
            "outstanding",
            minimum=0,
            maximum=MAX_REASONABLE_OUTSTANDING_TASKS,
        )
        outer_max_workers = _snapshot_int(
            payload,
            "outer_max_workers",
            minimum=1,
            maximum=MAX_REASONABLE_OUTSTANDING_TASKS,
        )
        _snapshot_int(payload, "updated_monotonic_ns", minimum=0)
    except (
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return fallback

    return OuterDemandState(
        outer_demand=max(1, min(outstanding, outer_max_workers)),
        outer_max_workers=outer_max_workers,
        generation=generation,
        snapshot_fallback=False,
    )


def _directory_opener(directory_fd: int) -> Callable[[str, int], int]:
    def open_entry(path: str, flags: int) -> int:
        return os.open(Path(path).name, flags, 0o600, dir_fd=directory_fd)

    return open_entry


def _open_json(path: Path, mode: str, directory_fd: int | None) -> TextIO:
    if directory_fd is None:
        return path.open(mode, encoding="utf-8")
    return open(path.name, mode, encoding="utf-8", opener=_directory_opener(directory_fd))


def _write_json_atomically(
    target: Path,
    payload: dict,
    *,
    directory_fd: int | None = None,
    attempts: int = 6,
) -> None:
    """Publish a complete snapshot, retrying once if temp cleanup races it.

    原子发布快照；临时目录或暂存文件被清理时重新写入一次。
    """

    try:
        _write_json_once(target, payload, directory_fd=directory_fd, attempts=attempts)
    except FileNotFoundError:
        # Restage within the same directory. A removed, locked directory must
        # fail here so its lease transaction can re-read under the new lock.
        _write_json_once(target, payload, directory_fd=directory_fd, attempts=attempts)


def _write_json_once(
    target: Path, payload: dict, *, directory_fd: int | None, attempts: int,
) -> None:
    if directory_fd is None:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary_path = target.with_name(f".{target.name}-{uuid.uuid4().hex}.tmp")
    try:
        with _open_json(temporary_path, "w", directory_fd) as handle:
            json.dump(
                payload,
                handle,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        for attempt in range(attempts):
            try:
                if directory_fd is None:
                    os.replace(temporary_path, target)
                else:
                    os.replace(
                        temporary_path.name, target.name,
                        src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                    )
                return
            except PermissionError:
                # Windows readers can briefly deny atomic replacement.
                # Keep the last complete file until the reader closes.
                if attempt == attempts - 1:
                    raise
                time.sleep(0.005 * (attempt + 1))
    finally:
        if directory_fd is None:
            temporary_path.unlink(missing_ok=True)
        else:
            with suppress(FileNotFoundError):
                os.unlink(temporary_path.name, dir_fd=directory_fd)


def _worker_lease_payload(leases: dict[str, dict], generation: int) -> dict:
    return {
        "version": int(WORKER_LEASE_VERSION),
        "generation": int(generation),
        "leases": leases,
        "updated_monotonic_ns": int(time.monotonic_ns()),
    }


def _process_create_time(pid: int) -> float:
    """Return one process create time, or ``0.0`` when it cannot be read.

    读取某个进程的创建时间；读取不到时返回 ``0.0``（表示无法核对 PID 复用）。
    """

    try:
        import psutil

        return float(psutil.Process(pid).create_time())
    except (ImportError, OSError, ValueError, psutil.Error):
        return 0.0


def _lease_owner_alive(pid: int, created: float) -> bool:
    """Return whether a lease owner process is still the one that reserved it.

    判断租约持有进程是否仍是当初预留的那一个（避免 PID 复用误判）。
    ``created`` 是持有进程的创建时间，不是预留时刻；无法核对时保留租约。
    """

    try:
        import psutil
    except ImportError:  # Without psutil the lease is kept: fail closed.
        return True
    try:
        if not psutil.pid_exists(pid):
            return False
        if created <= 0:
            return True
        return abs(float(psutil.Process(pid).create_time()) - created) < 1.0
    except (OSError, ValueError, psutil.Error):
        return True


def read_worker_leases(
    path: str | os.PathLike[str] | None,
) -> tuple[dict[str, dict], bool]:
    """Read the shared inner-worker lease table.

    读取共享的内部 worker 租约表。

    Args:
        path: Lease table published by the owning process pool.
            拥有该进程池发布的租约表路径。

    Returns:
        ``(leases, invalid)``. ``invalid`` reports a file that exists but
        cannot be trusted, so callers can refuse to add load instead of
        assuming the machine is idle. 无法信任的既有文件返回 ``invalid``，
        调用方据此拒绝加负载，而不是当作无人占用。
    """

    if path is None:
        return {}, False
    return _read_worker_leases(path, None)


def _read_worker_leases(
    path: str | os.PathLike[str], directory_fd: int | None,
) -> tuple[dict[str, dict], bool]:
    try:
        with _open_json(Path(os.fspath(path)), "r", directory_fd) as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict) or set(payload) != _WORKER_LEASE_FIELDS:
            return {}, True
        version = _snapshot_int(
            payload,
            "version",
            minimum=WORKER_LEASE_VERSION,
            maximum=WORKER_LEASE_VERSION,
        )
        if version != WORKER_LEASE_VERSION:
            return {}, True
        _snapshot_int(payload, "generation", minimum=0)
        _snapshot_int(payload, "updated_monotonic_ns", minimum=0)
        raw_leases = payload.get("leases")
        if not isinstance(raw_leases, dict):
            return {}, True
        leases: dict[str, dict] = {}
        for token, entry in raw_leases.items():
            if not isinstance(token, str) or not isinstance(entry, dict):
                return {}, True
            if set(entry) != _WORKER_LEASE_ENTRY_FIELDS:
                return {}, True
            created = entry["created"]
            if isinstance(created, bool) or not isinstance(created, (int, float)):
                return {}, True
            touched = entry["touched"]
            if isinstance(touched, bool) or not isinstance(touched, (int, float)):
                return {}, True
            leases[token] = {
                "pid": _snapshot_int(
                    entry, "pid", minimum=1, maximum=MAX_REASONABLE_PROCESS_ID
                ),
                "created": float(created),
                "touched": float(touched),
                "workers": _snapshot_int(
                    entry,
                    "workers",
                    minimum=0,
                    maximum=MAX_REASONABLE_LEASED_WORKERS,
                ),
                "stage": str(entry["stage"]),
                "effective_cpu": _snapshot_int(
                    entry,
                    "effective_cpu",
                    minimum=1,
                    maximum=MAX_REASONABLE_LEASED_WORKERS,
                ),
            }
        return leases, False
    except FileNotFoundError:
        return {}, False
    except (
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return {}, True


def worker_lease_lock_path(lease_path: str | os.PathLike[str]) -> Path:
    """Return the sibling lock file guarding one lease table.

    返回守护某个租约表的同级锁文件路径。Windows 锁住此文件，POSIX 锁住其目录。
    """

    return Path(os.fspath(lease_path)).with_name(WORKER_LEASE_LOCK_FILENAME)


@dataclass(frozen=True)
class _HeldLeaseLock:
    directory_fd: int | None


@contextmanager
def _exclusive_file_lock(
    lock_path: Path,
    *,
    timeout_seconds: float = _LEASE_LOCK_TIMEOUT_SECONDS,
) -> Iterator[_HeldLeaseLock | None]:
    """Hold a lock tied to one lifetime of the coordination directory.

    锁定一代协调目录；超时返回未获得锁。
    """

    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    handle = None
    directory_fd = None
    acquired = False
    try:
        for retry in (True, False):
            try:
                lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                if os.name != "nt":
                    directory_fd = os.open(lock_path.parent, os.O_RDONLY | os.O_DIRECTORY)
                opener = None if directory_fd is None else _directory_opener(directory_fd)
                handle = open(lock_path, "a+b", opener=opener)
                break
            except FileNotFoundError:
                if directory_fd is not None:
                    os.close(directory_fd)
                    directory_fd = None
                if not retry:
                    raise
        if directory_fd is None and handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        while True:
            try:
                if directory_fd is None:
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    # POSIX permits an open file to be unlinked. Lock the
                    # directory and keep all lease I/O relative to that handle.
                    fcntl.flock(directory_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.005)
        yield _HeldLeaseLock(directory_fd) if acquired else None
    finally:
        if acquired and handle is not None and directory_fd is None:
            try:
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        try:
            if handle is not None:
                handle.close()
        finally:
            if directory_fd is not None:
                os.close(directory_fd)


@dataclass(frozen=True)
class WorkerLeaseGrant:
    """Describe the workers one inner stage may start right now.

    描述某个内部阶段此刻最多可以启动多少个 worker。

    Args:
        token: Lease identity, or ``None`` when nothing was reserved.
            租约标识；未预留成功时为 ``None``。
        workers: Workers this stage may keep in flight.
            本阶段允许同时在飞的 worker 数。
        state: ``granted`` / ``unavailable`` / ``invalid`` / ``lock_timeout``.
            准入结果状态。
        sibling_tasks: Other tasks holding a lease at admission time.
            准入时刻已持有租约的其他任务数。
        sibling_workers: Workers those tasks already reserved.
            这些任务已预留的 worker 数。
        effective_cpu_capacity: Process CPU capacity used as the ceiling.
            用作上限的有效 CPU 容量。
        limiting_reason: Why the granted count is what it is.
            授予该数量的原因。
    """

    token: str | None
    workers: int
    state: str
    sibling_tasks: int
    sibling_workers: int
    effective_cpu_capacity: int
    limiting_reason: str


class WorkerLeaseStore:
    """Reserve inner-stage workers across sibling tasks through one file.

    通过一个文件在兄弟任务之间预留内部阶段的 worker。

    已有任务编排只会发布“同时有多少个任务”，无法表达“这些任务已经占用了多少
    个 worker”。本存储把该信息做成同一目录下的原子替换文件，使后来进入的任务
    能看到真实占用，而不是重新做一次静态均分。它不做调度：不排队、不抢占、不
    终止正在运行的计算，只回答“此刻还能启动几个”。

    Args:
        path: Lease table path shared by the owning pool.
            拥有该池共享的租约表路径。
        stale_seconds: Age after which an unverifiable lease is dropped.
            无法核实持有者的租约在此秒数后被丢弃。
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        stale_seconds: float = _LEASE_STALE_SECONDS,
    ) -> None:
        self._path = Path(os.fspath(path))
        self._lock_path = worker_lease_lock_path(self._path)
        self._stale_seconds = max(0.0, float(stale_seconds))
        self._generation = 0

    @property
    def path(self) -> Path:
        """Return the shared lease table path.

        返回共享租约表路径。
        """

        return self._path

    def _run_locked(
        self,
        operation: Callable[[int | None], _LeaseResult],
        unavailable: _LeaseResult,
    ) -> _LeaseResult:
        for retry in (True, False):
            with _exclusive_file_lock(self._lock_path) as lock:
                if lock is None:
                    return unavailable
                directory_fd = lock.directory_fd
                try:
                    result = operation(directory_fd)
                    if directory_fd is not None and not os.path.samestat(
                        os.fstat(directory_fd), self._path.parent.stat(),
                    ):
                        raise FileNotFoundError(f"Worker lease directory changed: {self._path.parent}")
                except FileNotFoundError:
                    if not retry:
                        raise
                    # Release the old lock and read the live table again.
                else:
                    return result
        return unavailable

    def _read_locked(self, directory_fd: int | None) -> tuple[dict[str, dict], bool]:
        leases, invalid = _read_worker_leases(self._path, directory_fd)
        now = time.time()
        live = {}
        for token, entry in leases.items():
            if now - entry["touched"] > self._stale_seconds:
                continue
            if not _lease_owner_alive(entry["pid"], entry["created"]):
                continue
            live[token] = entry
        return live, invalid

    def _write_locked(self, leases: dict[str, dict], directory_fd: int | None) -> None:
        generation = self._generation + 1
        _write_json_atomically(
            self._path,
            _worker_lease_payload(leases, generation),
            directory_fd=directory_fd,
        )
        self._generation = generation

    def reserve(
        self,
        *,
        requested_workers: int,
        effective_cpu_capacity: int,
        stage: str,
        owner_pid: int | None = None,
    ) -> WorkerLeaseGrant:
        """Reserve as many of ``requested_workers`` as the machine still has.

        在机器仍然空余的容量内预留 ``requested_workers`` 个 worker。

        Returns:
            A grant whose ``workers`` never exceeds the live free capacity.
            A grant of zero is a real answer: the caller must do the work in
            its own process instead of starting workers. 授予值不会超过当前
            实测空闲容量；授予 0 也是有效答案——调用方改为在本进程内串行完成，
            而不是新增进程。
        """

        requested = max(1, int(requested_workers))
        capacity = max(1, int(effective_cpu_capacity))
        pid = int(owner_pid if owner_pid is not None else os.getpid())

        def reserve_locked(directory_fd: int | None) -> WorkerLeaseGrant:
            leases, invalid = self._read_locked(directory_fd)
            if invalid:
                return WorkerLeaseGrant(
                    None, 1, "invalid", 0, 0, capacity, "lease_state_invalid",
                )
            sibling_tasks = len(leases)
            sibling_workers = sum(entry["workers"] for entry in leases.values())
            free = max(0, capacity - sibling_workers)
            workers = min(requested, free)
            if workers == 0:
                # Every CPU is already spoken for by worker leases. Do not add
                # a worker process; the caller stays in-process, so the sum of
                # leased workers still fits the machine.
                reason = "lease_capacity_exhausted"
            elif workers < requested:
                reason = "worker_lease_contention"
            else:
                reason = "granted"
            token = uuid.uuid4().hex
            now = time.time()
            leases[token] = {
                "pid": pid,
                "created": _process_create_time(pid),
                "touched": now,
                "workers": workers,
                "stage": str(stage),
                "effective_cpu": capacity,
            }
            self._write_locked(leases, directory_fd)
            return WorkerLeaseGrant(
                token, workers, "granted", sibling_tasks, sibling_workers, capacity,
                reason,
            )

        return self._run_locked(
            reserve_locked,
            WorkerLeaseGrant(None, requested, "lock_timeout", 0, 0, capacity, "lease_lock_timeout"),
        )

    def allowed_workers(self, token: str) -> int | None:
        """Return how many workers this lease may keep in flight now.

        返回该租约此刻允许在飞的 worker 数。

        Re-read at a material-completion boundary so a task that started with a
        large grant gives capacity back to later arrivals without ever killing
        running work or increasing its own concurrency.
        在材质完成边界重读，使先到的大额租约把容量让给后到的任务；既不会终止
        正在运行的计算，也不会提高自身并发。

        The result never drops below one worker for a lease that is already
        running: a dispatched task must be able to finish the materials it has
        not submitted yet, so each running task keeps a one-worker progress
        floor. That floor is the reason this accounting bounds the sum of
        *admitted* workers rather than claiming an exact instantaneous total -
        a task admitted at zero never starts workers at all.
        已在运行的租约不会降到 1 个 worker 以下：已派发的任务必须能跑完尚未
        提交的材质，因此每个运行中的任务保留 1 个 worker 的推进下限。正因为有
        这个下限，本账本保证的是“准入时总和不超过容量”，而不是宣称任何时刻的
        精确总数；被准入为 0 的任务根本不会启动 worker 进程。

        ``None`` 表示状态不可知，调用方应沿用当前额度。
        """

        def allowed_locked(directory_fd: int | None) -> int | None:
            leases, invalid = self._read_locked(directory_fd)
            if invalid:
                return 1
            entry = leases.get(str(token))
            if entry is None:
                return None
            others = sum(
                item["workers"] for name, item in leases.items() if name != str(token)
            )
            allowed = max(1, min(entry["workers"], entry["effective_cpu"] - others))
            now = time.time()
            if allowed < entry["workers"] or now - entry["touched"] >= _LEASE_REFRESH_SECONDS:
                # Persist the shrink so siblings immediately see the released
                # capacity, and keep a long-running holder from looking stale.
                leases[str(token)] = {
                    **entry,
                    "workers": allowed,
                    "touched": now,
                }
                self._write_locked(leases, directory_fd)
            return allowed

        return self._run_locked(allowed_locked, None)

    def release(self, token: str | None) -> bool:
        """Drop one lease, leaving sibling leases untouched.

        释放一个租约，不影响兄弟租约。

        Returns:
            ``True`` once the lease is no longer in a trustworthy table (an
            already-absent lease counts, so a retry is idempotent), ``False``
            when the lock timed out or the table is untrustworthy. The caller
            can then retry instead of assuming the capacity went back - a
            reservation left behind here keeps occupying the machine for as
            long as the holder process lives. 账本可信且该租约已不在其中时返回
            ``True``（本来就已不存在也算，便于重试保持幂等）；锁超时或账本不
            可信时返回 ``False``，使调用方可以重试，而不是假定额度已经归还——
            遗留的额度会一直占用到持有进程退出。
        """

        if token is None:
            return True

        def release_locked(directory_fd: int | None) -> bool:
            leases, invalid = self._read_locked(directory_fd)
            if invalid:
                return False
            if str(token) not in leases:
                return True
            leases.pop(str(token))
            self._write_locked(leases, directory_fd)
            return True

        return self._run_locked(release_locked, False)

    def snapshot(self) -> dict:
        """Return leased task and worker totals for diagnostics.

        返回租约任务数与 worker 总数，用于诊断。
        """

        def snapshot_locked(directory_fd: int | None) -> dict:
            leases, invalid = self._read_locked(directory_fd)
            if invalid:
                return {"tasks": 0, "workers": 0, "state": "invalid"}
            return {
                "tasks": len(leases),
                "workers": sum(entry["workers"] for entry in leases.values()),
                "state": "ok",
            }

        return self._run_locked(snapshot_locked, {"tasks": 0, "workers": 0, "state": "lock_timeout"})


class OuterDemandPublisher:
    """Publish bounded outstanding-task state through atomic replacement.

    通过原子替换发布有界的未完成任务状态。

    Args:
        max_workers: Configured outer process-pool capacity.
            外层进程池配置容量。
        parent_dir: Optional parent directory for deterministic tests.
            测试可注入的父目录。
    """

    def __init__(
        self,
        *,
        max_workers: int,
        parent_dir: Path | None = None,
    ) -> None:
        self._max_workers = _positive_int(max_workers)
        self._lock = threading.Lock()
        self._outstanding = 0
        self._generation = 0
        self._worker_lease_generation = 0
        self._closed = False
        self._directory = Path(
            tempfile.mkdtemp(
                prefix="lumina-parallelism-",
                dir=str(parent_dir) if parent_dir is not None else None,
            )
        )
        self._snapshot_path = self._directory / "demand.json"
        self._worker_lease_path = self._directory / WORKER_LEASE_FILENAME
        with self._lock:
            self._publish_locked()
            self._publish_worker_leases_locked({})

    @property
    def snapshot_path(self) -> Path:
        """Return the unique atomic snapshot path.

        返回此发布器唯一的原子快照路径。
        """

        return self._snapshot_path

    @property
    def worker_lease_path(self) -> Path:
        """Return the shared inner-worker lease table owned by this pool.

        返回此进程池共享的内部 worker 租约表路径。内部阶段在本文件里登记自己
        实际启动的 worker 数，使后来进入的任务能看到已有负载，而不是只看到
        任务数量。
        """

        return self._worker_lease_path

    @property
    def outstanding(self) -> int:
        """Return the in-memory submitted-but-undelivered task count.

        返回内存中的已提交但尚未交付结果的任务数。
        """

        with self._lock:
            return self._outstanding

    def increment(self) -> None:
        """Record one submitted task and publish the new generation.

        记录一个已提交任务并发布新代次。
        """

        with self._lock:
            if self._closed:
                raise RuntimeError("outer demand publisher is closed")
            self._outstanding += 1
            self._generation += 1
            self._publish_locked()

    def decrement(self) -> None:
        """Record one delivered task and publish the new generation.

        记录一个已交付任务并发布新代次。
        """

        with self._lock:
            if self._closed:
                return
            self._outstanding = max(0, self._outstanding - 1)
            self._generation += 1
            self._publish_locked()

    def cleanup(self) -> None:
        """Remove the pool-owned snapshot and temporary directory.

        删除进程池拥有的快照与临时目录；重复调用安全。
        """

        with self._lock:
            if self._closed:
                return
            self._snapshot_path.unlink(missing_ok=True)
            self._worker_lease_path.unlink(missing_ok=True)
            worker_lease_lock_path(self._worker_lease_path).unlink(missing_ok=True)
            try:
                self._directory.rmdir()
            except OSError:
                # A lease holder outside this process may still be writing.
                # Leaving the directory behind is safer than failing cleanup.
                pass
            self._closed = True

    def _publish_locked(self) -> None:
        payload = {
            "version": int(DEMAND_SNAPSHOT_VERSION),
            "generation": int(self._generation),
            "outstanding": int(self._outstanding),
            "outer_max_workers": int(self._max_workers),
            "updated_monotonic_ns": int(time.monotonic_ns()),
        }
        _write_json_atomically(self._snapshot_path, payload)

    def _publish_worker_leases_locked(self, leases: dict[str, dict]) -> None:
        _write_json_atomically(
            self._worker_lease_path,
            _worker_lease_payload(leases, self._worker_lease_generation),
        )


def current_demand_snapshot_path() -> Path | None:
    """Return the worker-local demand snapshot path when installed.

    返回当前 worker 安装的负载快照路径；未安装时为 ``None``。
    """

    return getattr(_RUNTIME_STATE, "demand_snapshot_path", None)


def current_worker_lease_path() -> Path | None:
    """Return the pool-owned inner-worker lease table when installed.

    返回当前任务所属进程池的 worker 租约表路径；未安装时为 ``None``。

    ``None`` means this process is not running under a pool that publishes
    worker leases (for example a single CLI conversion). Inner stages then keep
    the static plan and report that no lease was available, instead of claiming
    an instantaneous bound they cannot prove. 未安装表示当前进程不在发布
    租约的池里（例如单次 CLI 转换），内部阶段沿用静态计划并如实报告没有租约。
    """

    return getattr(_RUNTIME_STATE, "worker_lease_path", None)


@contextmanager
def task_parallelism_runtime_scope(
    snapshot_path: str | os.PathLike[str],
    worker_lease_path: str | os.PathLike[str] | None = None,
) -> Iterator[None]:
    """Install one demand path for a worker task and restore prior state.

    为单个 worker 任务安装负载路径，并在退出时恢复之前的状态。

    Args:
        snapshot_path: Parent-published atomic snapshot path.
            父进程发布的原子快照路径。
        worker_lease_path: Optional parent-published worker lease table.
            可选的父进程 worker 租约表路径；未提供时内部阶段不做租约准入。

    Yields:
        ``None`` while the path is installed for the current thread.
        当前线程安装路径期间返回 ``None``。
    """

    previous_path = getattr(_RUNTIME_STATE, "demand_snapshot_path", None)
    previous_lease = getattr(_RUNTIME_STATE, "worker_lease_path", None)
    _RUNTIME_STATE.demand_snapshot_path = Path(os.fspath(snapshot_path))
    if worker_lease_path is None:
        # A scope states the whole context: a nested scope without a lease
        # table means "no lease accounting here", not "inherit the outer one",
        # which would attach this task's reservations to another pool.
        _RUNTIME_STATE.worker_lease_path = None
    else:
        _RUNTIME_STATE.worker_lease_path = Path(os.fspath(worker_lease_path))
    try:
        yield
    finally:
        if previous_lease is None:
            _RUNTIME_STATE.worker_lease_path = None
        else:
            _RUNTIME_STATE.worker_lease_path = previous_lease
        if previous_path is None:
            try:
                del _RUNTIME_STATE.demand_snapshot_path
            except AttributeError:
                pass
        else:
            _RUNTIME_STATE.demand_snapshot_path = previous_path
