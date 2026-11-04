"""Immutable backend environments keyed by lock content.

Environment key = platform + interpreter minor version + canonical lock
digest. Identical locks share one environment; different locks get separate
environments, so conflicting versions coexist. Files are deduplicated across
environments through the content store.

后端环境按“平台 + 解释器小版本 + 规范化锁内容”区分：相同锁共用一个环境，
不同锁各自独立，冲突版本自然共存；跨环境的相同文件经内容仓去重。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..errors import WorkshopBackendError
from .locks import BackendLock, WheelSourcePolicy, render_install_lock
from .store import ContentStore, RemovalOutcome, remove_tree
from .tooling import BackendInterpreter, CancelToken, UvTool


ENVIRONMENT_RECORD_NAME = "lumina-environment.json"
_ENVIRONMENT_SCHEMA = 1


@dataclass(frozen=True, slots=True)
class EnvironmentRecord:
    """Completed environment metadata written as the last build step."""

    key: str
    lock_digest: str
    platform: str
    python_version: str
    interpreter_key: str
    packages: tuple[tuple[str, str], ...]
    created_at: str
    new_bytes: int
    shared_bytes: int
    copied_without_links: bool

    def as_json(self) -> dict[str, object]:
        return {
            "schemaVersion": _ENVIRONMENT_SCHEMA,
            "key": self.key,
            "lockDigest": self.lock_digest,
            "platform": self.platform,
            "pythonVersion": self.python_version,
            "interpreterKey": self.interpreter_key,
            "packages": [list(item) for item in self.packages],
            "createdAt": self.created_at,
            "newBytes": self.new_bytes,
            "sharedBytes": self.shared_bytes,
            "copiedWithoutLinks": self.copied_without_links,
        }

    @classmethod
    def from_json(cls, value: dict[str, object]) -> "EnvironmentRecord":
        if value.get("schemaVersion") != _ENVIRONMENT_SCHEMA:
            raise ValueError("unsupported environment record")
        packages = value.get("packages")
        if not isinstance(packages, list):
            raise ValueError("environment packages are invalid")
        return cls(
            key=str(value["key"]),
            lock_digest=str(value["lockDigest"]),
            platform=str(value["platform"]),
            python_version=str(value["pythonVersion"]),
            interpreter_key=str(value["interpreterKey"]),
            packages=tuple((str(item[0]), str(item[1])) for item in packages),
            created_at=str(value["createdAt"]),
            new_bytes=int(value["newBytes"]),
            shared_bytes=int(value["sharedBytes"]),
            copied_without_links=bool(value["copiedWithoutLinks"]),
        )


def environment_key(
    lock: BackendLock,
    *,
    platform_key: str,
    python_version: str,
) -> str:
    """Return the shared environment identity for one lock on this host."""

    payload = f"{platform_key}|{python_version}|{lock.digest}".encode("ascii")
    return hashlib.sha256(payload).hexdigest()[:32]


def environment_python(root: Path) -> Path:
    if os.name == "nt":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


class EnvironmentManager:
    """Create, look up, and remove lock-keyed environments.

    创建、查找和删除按锁内容区分的环境。
    """

    def __init__(
        self,
        root: Path,
        *,
        uv: UvTool | None,
        store: ContentStore,
        sources: WheelSourcePolicy,
    ) -> None:
        self.root = Path(root)
        self.staging_dir = self.root / ".staging"
        self.root.mkdir(parents=True, exist_ok=True)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self._uv = uv
        self._store = store
        self._sources = sources
        self._locks_guard = threading.Lock()
        self._key_locks: dict[str, threading.Lock] = {}

    def _key_lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._key_locks.setdefault(key, threading.Lock())

    def path(self, key: str) -> Path:
        if len(key) != 32 or any(char not in "0123456789abcdef" for char in key):
            raise WorkshopBackendError("environment-invalid", "Environment key is invalid.")
        return self.root / key

    def get(self, key: str) -> EnvironmentRecord | None:
        root = self.path(key)
        record_path = root / ENVIRONMENT_RECORD_NAME
        if not record_path.is_file() or not environment_python(root).is_file():
            return None
        try:
            return EnvironmentRecord.from_json(
                json.loads(record_path.read_text(encoding="utf-8"))
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def list(self) -> tuple[EnvironmentRecord, ...]:
        records: list[EnvironmentRecord] = []
        for child in sorted(self.root.iterdir()):
            if child.name.startswith(".") or not child.is_dir():
                continue
            try:
                record = self.get(child.name)
            except WorkshopBackendError:
                continue
            if record is not None:
                records.append(record)
        return tuple(records)

    def package_users(self) -> dict[tuple[str, str], set[str]]:
        """Map installed ``(name, version)`` pairs to environment keys."""

        users: dict[tuple[str, str], set[str]] = {}
        for record in self.list():
            for package in record.packages:
                users.setdefault(package, set()).add(record.key)
        return users

    def ensure(
        self,
        lock: BackendLock,
        *,
        platform_key: str,
        interpreter: BackendInterpreter,
        cancel: CancelToken | None,
    ) -> tuple[EnvironmentRecord, bool]:
        """Return the environment for ``lock``, building it if absent."""

        key = environment_key(
            lock,
            platform_key=platform_key,
            python_version=interpreter.python_version,
        )
        with self._key_lock(key):
            existing = self.get(key)
            if existing is not None:
                return existing, False
            if self._uv is None:
                raise WorkshopBackendError(
                    "backend-tool-unavailable",
                    "The backend dependency tool is not installed.",
                )
            # A directory without a valid record is what an earlier removal
            # left while some files were in use; it would block the move below.
            if self.path(key).exists() and remove_tree(self.path(key)).pending:
                raise WorkshopBackendError(
                    "environment-busy",
                    "Files of an earlier copy of this environment are still in use. "
                    "Close programs using them or restart Lumina, then try again.",
                )
            transaction = f"{key}-{uuid.uuid4().hex}"
            staging = self.staging_dir / transaction
            # PEP 751 file names: ``pylock.<name>.toml`` with no dots in name.
            install_lock = self.staging_dir / f"pylock.{transaction}.toml"
            try:
                install_lock.write_text(
                    render_install_lock(lock, self._sources),
                    encoding="utf-8",
                )
                self._uv.create_venv(staging, interpreter.executable, cancel=cancel)
                self._uv.sync(
                    environment_python(staging),
                    install_lock,
                    offline=self._sources.offline,
                    cancel=cancel,
                )
                stats = self._store.adopt_tree(staging, cancel=cancel)
                record = EnvironmentRecord(
                    key=key,
                    lock_digest=lock.digest,
                    platform=platform_key,
                    python_version=interpreter.python_version,
                    interpreter_key=interpreter.key,
                    packages=tuple(
                        sorted({(package.name, package.version) for package in lock.packages})
                    ),
                    created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    new_bytes=stats.new_bytes,
                    shared_bytes=stats.shared_bytes,
                    copied_without_links=stats.copied_without_links,
                )
                (staging / ENVIRONMENT_RECORD_NAME).write_text(
                    json.dumps(record.as_json(), sort_keys=True),
                    encoding="utf-8",
                )
                if cancel is not None:
                    cancel.raise_if_cancelled()
                os.replace(staging, self.path(key))
                return record, True
            finally:
                install_lock.unlink(missing_ok=True)
                if staging.exists():
                    remove_tree(staging)

    def remove(
        self,
        key: str,
        *,
        still_needed: Callable[[], bool] | None = None,
    ) -> RemovalOutcome | None:
        """Delete one environment; shared objects stay with their users.

        ``still_needed`` is re-checked under the key lock that ``ensure``
        also takes, so a preparation that claimed this environment after the
        caller's snapshot keeps it; the result is then ``None``.
        """

        root = self.path(key)
        with self._key_lock(key):
            if still_needed is not None and still_needed():
                return None
            if not root.exists():
                return RemovalOutcome()
            record_path = root / ENVIRONMENT_RECORD_NAME
            # Removing the completion record first makes a partially deleted
            # environment invisible even if some locked files stay pending.
            record_path.unlink(missing_ok=True)
            return remove_tree(root)

    def remove_orphans(self, *, skip: Callable[[str], bool]) -> RemovalOutcome:
        """Delete environment directories that no longer hold a valid record.

        A removal whose files were still in use leaves one behind. Each pass
        looks at what is on disk now instead of replaying remembered paths,
        so a key that is in use again is never touched; ``skip`` names keys
        a running preparation has claimed.
        """

        outcome = RemovalOutcome()
        for child in sorted(self.root.iterdir()) if self.root.is_dir() else ():
            if child.name.startswith(".") or not child.is_dir():
                continue
            try:
                self.path(child.name)
            except WorkshopBackendError:
                continue
            if skip(child.name):
                continue
            with self._key_lock(child.name):
                if self.get(child.name) is not None:
                    continue
                result = remove_tree(child)
            outcome.freed_bytes += result.freed_bytes
            outcome.pending.extend(result.pending)
        return outcome

    def remove_staging_leftovers(self) -> RemovalOutcome:
        outcome = RemovalOutcome()
        for child in self.staging_dir.iterdir() if self.staging_dir.is_dir() else ():
            result = remove_tree(child)
            outcome.freed_bytes += result.freed_bytes
            outcome.pending.extend(result.pending)
        return outcome
