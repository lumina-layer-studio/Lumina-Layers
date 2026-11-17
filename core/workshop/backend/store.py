"""Host content store: SHA-256 objects shared by hard links.

uv's private cache gives hard-link sharing while it lives, but its official
``prune``/``clean <name>`` commands cannot release one version of a package
that another environment still needs without losing that sharing (see the
backend runtime design notes). The host therefore adopts large environment
and model files into ``objects/<sha256>`` and reclaims an object once no
environment or model view links to it and no caller still references it.

Link counts alone cannot see a copied view (volumes without hard links) or
an object a running preparation is about to link, so collection also honours
a logical ``keep`` set and in-flight pins. Publishing, linking, and the
per-object collection decision share one lock, so a new link can never race
with the deletion of its object.

宿主内容仓：按 SHA-256 存放对象并以硬链接共享。除链接数外，回收还会保留
调用方声明仍在使用的对象和正在准备中的对象；发布、链接与回收判断互斥。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import threading
import time
import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .tooling import CancelToken


ADOPT_MIN_BYTES = 64 * 1024
_HASH_CHUNK_BYTES = 1024 * 1024
_REMOVE_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)


@dataclass(slots=True)
class AdoptionStats:
    """Physical-storage effect of adopting one tree into the store."""

    files: int = 0
    new_bytes: int = 0
    shared_bytes: int = 0
    linked_files: int = 0
    copied_without_links: bool = False


@dataclass(slots=True)
class RemovalOutcome:
    """Bytes actually released by a removal and paths still pending."""

    freed_bytes: int = 0
    pending: list[str] = field(default_factory=list)


def sha256_file(path: Path, cancel: CancelToken | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_HASH_CHUNK_BYTES):
            if cancel is not None:
                cancel.raise_if_cancelled()
            digest.update(chunk)
    return digest.hexdigest()


def _clear_readonly(path: str) -> None:
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    except OSError:
        pass


def unlink_with_retry(path: Path) -> bool:
    """Remove one file name, retrying briefly while Windows releases maps.

    Another process mapping the same file through a different hard-link
    name does not block this; only a name that is itself mapped or open is
    locked, typically for a short time after its process exits.
    """

    for delay in (0.0, *_REMOVE_RETRY_DELAYS):
        if delay:
            time.sleep(delay)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return True
        except PermissionError:
            _clear_readonly(str(path))
        except OSError:
            continue
    return not path.exists()


def releasable_bytes(root: Path) -> int:
    """Bytes freed if ``root`` were deleted now (last-link files only)."""

    total = 0
    if not root.exists():
        return 0
    for directory, _dirs, files in os.walk(root):
        for name in files:
            try:
                info = (Path(directory) / name).lstat()
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode) and info.st_nlink <= 1:
                total += info.st_size
    return total


def remove_tree(root: Path) -> RemovalOutcome:
    """Delete a directory tree, reporting names that stay locked.

    删除目录树；仍被占用而无法删除的路径作为待回收项返回。
    """

    outcome = RemovalOutcome()
    if not root.exists() and not root.is_symlink():
        return outcome
    if root.is_symlink() or root.is_file():
        size = root.lstat().st_size if root.lstat().st_nlink <= 1 else 0
        if unlink_with_retry(root):
            outcome.freed_bytes += size
        else:
            outcome.pending.append(str(root))
        return outcome
    for directory, dirs, files in os.walk(root, topdown=False):
        for name in files:
            path = Path(directory) / name
            try:
                info = path.lstat()
            except OSError:
                continue
            size = info.st_size if info.st_nlink <= 1 else 0
            if unlink_with_retry(path):
                outcome.freed_bytes += size
            else:
                outcome.pending.append(str(path))
        for name in dirs:
            path = Path(directory) / name
            try:
                if path.is_symlink():
                    path.unlink()
                else:
                    path.rmdir()
            except OSError:
                # A directory stays only because a locked file inside it
                # was already recorded as pending.
                pass
    try:
        root.rmdir()
    except OSError:
        if root.exists() and not outcome.pending:
            outcome.pending.append(str(root))
    return outcome


class ContentStore:
    """Deduplicate large immutable files by SHA-256 and link count.

    以 SHA-256 与链接数对大型不可变文件去重并按引用回收。
    """

    def __init__(self, root: Path, *, min_bytes: int = ADOPT_MIN_BYTES) -> None:
        self.root = Path(root)
        self.objects_dir = self.root / "objects"
        self.temporary_dir = self.root / "tmp"
        self.min_bytes = min_bytes
        self.objects_dir.mkdir(parents=True, exist_ok=True)
        self.temporary_dir.mkdir(parents=True, exist_ok=True)
        # Guards publish/link against the per-object collection decision.
        self._lock = threading.RLock()
        self._pins: dict[str, int] = {}

    def object_path(self, sha256: str) -> Path:
        return self.objects_dir / sha256[:2] / sha256

    def has(self, sha256: str) -> bool:
        return self.object_path(sha256).is_file()

    def object_size(self, sha256: str) -> int | None:
        try:
            return self.object_path(sha256).stat().st_size
        except OSError:
            return None

    def pin(self, digests: Iterable[str]) -> None:
        """Keep objects through collection while an operation still needs them."""

        with self._lock:
            for digest in digests:
                self._pins[digest] = self._pins.get(digest, 0) + 1

    def unpin(self, digests: Iterable[str]) -> None:
        with self._lock:
            for digest in digests:
                count = self._pins.get(digest, 0) - 1
                if count <= 0:
                    self._pins.pop(digest, None)
                else:
                    self._pins[digest] = count

    def _publish(self, source: Path, sha256: str) -> Path:
        target = self.object_path(sha256)
        with self._lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            staged = target.with_name(f".{sha256}.{uuid.uuid4().hex}")
            os.link(source, staged)
            try:
                os.replace(staged, target)
            finally:
                if staged.exists():
                    staged.unlink()
        return target

    def _link_locked(self, source: Path, destination: Path) -> bool:
        """Expose ``source`` at ``destination``; ``False`` means a full copy.

        Caller holds the store lock. A volume without hard links (FAT/exFAT,
        some network shares) gets a real copy; such copies are owned by their
        view, so the caller keeps the object alive through its ``keep`` set.
        """

        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            current = destination.stat()
            target = source.stat()
            if (current.st_dev, current.st_ino) == (target.st_dev, target.st_ino):
                return True
            unlink_with_retry(destination)
        try:
            os.link(source, destination)
            return True
        except OSError:
            staged = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}")
            try:
                shutil.copyfile(source, staged)
                os.replace(staged, destination)
            finally:
                if staged.exists():
                    unlink_with_retry(staged)
            return False

    def adopt_tree(
        self,
        tree: Path,
        *,
        cancel: CancelToken | None = None,
    ) -> AdoptionStats:
        """Hard-link large files of a freshly built tree to store objects."""

        stats = AdoptionStats()
        links_supported = True
        for directory, _dirs, files in os.walk(tree):
            for name in files:
                if cancel is not None:
                    cancel.raise_if_cancelled()
                path = Path(directory) / name
                try:
                    info = path.lstat()
                except OSError:
                    continue
                if not stat.S_ISREG(info.st_mode):
                    continue
                stats.files += 1
                if not links_supported or info.st_size < self.min_bytes:
                    stats.new_bytes += info.st_size
                    continue
                digest = sha256_file(path, cancel)
                target = self.object_path(digest)
                try:
                    # The existence check and the new link happen together so
                    # collection cannot delete the object in between.
                    with self._lock:
                        if target.is_file():
                            existing = target.stat()
                            if (existing.st_dev, existing.st_ino) != (info.st_dev, info.st_ino):
                                if existing.st_size != info.st_size:
                                    raise OSError("content store object size mismatch")
                                replacement = path.with_name(f".{name}.{uuid.uuid4().hex}")
                                os.link(target, replacement)
                                os.replace(replacement, path)
                            stats.shared_bytes += info.st_size
                        else:
                            self._publish(path, digest)
                            stats.new_bytes += info.st_size
                    stats.linked_files += 1
                except OSError:
                    # FAT/exFAT, some network shares, or cross-volume roots:
                    # keep the real copy and report its full physical size.
                    links_supported = False
                    stats.copied_without_links = True
                    stats.new_bytes += info.st_size
        return stats

    def import_verified_file(self, source: Path, sha256: str, destination: Path) -> bool:
        """Publish a verified temporary file and expose it at ``destination``.

        Publication and the first link are one step, so collection never
        sees the new object without its user. Returns ``False`` when the view
        had to be a copy.
        """

        target = self.object_path(sha256)
        with self._lock:
            if target.is_file():
                unlink_with_retry(source)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(source, target)
            return self._link_locked(target, destination)

    def link_existing(self, sha256: str, destination: Path) -> bool | None:
        """Expose a stored object; ``None`` when the store does not hold it."""

        target = self.object_path(sha256)
        with self._lock:
            if not target.is_file():
                return None
            return self._link_locked(target, destination)

    def collect_garbage(self, *, keep: Collection[str] = ()) -> RemovalOutcome:
        """Delete objects nothing links to, references, or has pinned.

        ``keep`` names objects that callers still reference logically, for
        example models whose views are copies or that the user retained.
        """

        outcome = RemovalOutcome()
        if not self.objects_dir.is_dir():
            return outcome
        for shard in sorted(self.objects_dir.iterdir()):
            if not shard.is_dir():
                continue
            for entry in sorted(shard.iterdir()):
                with self._lock:
                    try:
                        info = entry.lstat()
                    except OSError:
                        continue
                    if entry.name.startswith("."):
                        # Leftovers of an interrupted publication (whose
                        # writer holds this lock while it exists).
                        if unlink_with_retry(entry):
                            outcome.freed_bytes += info.st_size if info.st_nlink <= 1 else 0
                        continue
                    if info.st_nlink > 1 or entry.name in keep or entry.name in self._pins:
                        continue
                    if unlink_with_retry(entry):
                        outcome.freed_bytes += info.st_size
                    else:
                        outcome.pending.append(str(entry))
            with self._lock:
                try:
                    shard.rmdir()
                except OSError:
                    pass
        return outcome

    def clear_temporary(self) -> RemovalOutcome:
        """Remove download leftovers; call only while no preparation runs."""

        outcome = RemovalOutcome()
        for leftover in self.temporary_dir.iterdir() if self.temporary_dir.is_dir() else ():
            result = remove_tree(leftover)
            outcome.freed_bytes += result.freed_bytes
            outcome.pending.extend(result.pending)
        return outcome

    def usage(self) -> tuple[int, int]:
        """Return ``(object_count, bytes)`` currently held by the store."""

        count = 0
        total = 0
        if not self.objects_dir.is_dir():
            return 0, 0
        for directory, _dirs, files in os.walk(self.objects_dir):
            for name in files:
                try:
                    total += (Path(directory) / name).lstat().st_size
                    count += 1
                except OSError:
                    continue
        return count, total
