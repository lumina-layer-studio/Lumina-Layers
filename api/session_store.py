import os
import shutil
import threading
import time
import uuid
from collections.abc import Mapping
from typing import Any, Dict, Optional


def _snapshot_containers(value: Any, memo: dict[int, Any]) -> Any:
    identity = id(value)
    if identity in memo:
        return memo[identity]
    if isinstance(value, dict):
        snapshot = value.copy()
        memo[identity] = snapshot
        for key, item in snapshot.items():
            snapshot[key] = _snapshot_containers(item, memo)
        return snapshot
    if isinstance(value, list):
        snapshot = value[:]
        memo[identity] = snapshot
        for index, item in enumerate(snapshot):
            snapshot[index] = _snapshot_containers(item, memo)
        return snapshot
    if isinstance(value, tuple):
        snapshot = tuple(_snapshot_containers(item, memo) for item in value)
        memo[identity] = snapshot
        return snapshot
    if isinstance(value, set):
        snapshot = value.copy()
        memo[identity] = snapshot
        return snapshot
    return value


class SessionStore:
    """服务端内存 Session 管理器。

    以 Dict[str, Dict[str, Any]] 存储会话数据，
    支持 TTL 自动过期和临时文件清理。
    """

    DEFAULT_TTL: int = 1800  # 30 分钟

    def __init__(self, ttl: int = DEFAULT_TTL) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}
        self._timestamps: Dict[str, float] = {}
        self._temp_files: Dict[str, list[str]] = {}
        self._closing_sessions: set[str] = set()
        self._retired_sessions: Dict[str, float] = {}
        self._lock: threading.Lock = threading.Lock()
        self._lease_seconds: int = ttl

    def create(self, session_id: str | None = None) -> str:
        """Create a new session.

        创建新 session。

        Args:
            session_id (str | None): Optional explicit session id. If None, a
                fresh UUID4 is minted. If the supplied id collides with any
                active / closing / retired session, a fresh UUID4 is minted
                instead.
                可选的显式 session id；若为 None 则随机生成 UUID4；若发生冲突
                则改为新 UUID4。

        Returns:
            str: The session id actually registered (the supplied id, or a
            freshly minted one).
        """
        if session_id is None:
            session_id = str(uuid.uuid4())
        with self._lock:
            self._prune_retired_locked()
            while (
                session_id in self._store
                or session_id in self._closing_sessions
                or session_id in self._retired_sessions
            ):
                session_id = str(uuid.uuid4())
            self._store[session_id] = {}
            self._timestamps[session_id] = self._renew_lease_locked(session_id)
            self._temp_files[session_id] = []
        return session_id

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取 session 数据，更新访问时间戳。不存在返回 None。"""
        with self._lock:
            self._prune_retired_locked()
            if session_id in self._retired_sessions:
                return None
            if session_id not in self._store:
                return None
            if session_id in self._closing_sessions:
                return None
            self._renew_lease_locked(session_id)
            return self._store[session_id]

    def put(self, session_id: str, key: str, value: Any) -> None:
        """写入 session 数据字段。session 不存在时自动创建。"""
        with self._lock:
            self._prune_retired_locked()
            if session_id in self._retired_sessions:
                return
            if session_id in self._closing_sessions:
                return
            if session_id not in self._store:
                self._store[session_id] = {}
                self._temp_files[session_id] = []
            self._renew_lease_locked(session_id)
            self._store[session_id][key] = value

    def get_snapshot(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Return session state with detached nested containers under the lock.

        在锁内复制会话及嵌套容器，避免采集期间请求更新字段改变遍历结构。
        Domain objects and array buffers retain their original references.
        领域对象和数组缓冲仍保留原始引用。

        Args:
            session_id: Owning session identifier. / 所属会话编号。

        Returns:
            Detached containers, or None for an unavailable session.
            复制后的容器；会话不可用时返回 None。
        """
        with self._lock:
            self._prune_retired_locked()
            if (
                session_id in self._retired_sessions
                or session_id in self._closing_sessions
                or session_id not in self._store
            ):
                return None
            self._renew_lease_locked(session_id)
            return _snapshot_containers(self._store[session_id], {})

    def compare_and_set(
        self,
        session_id: str,
        key: str,
        value: Any,
        *,
        revision_path: tuple[str, ...],
        expected_revision: Any,
    ) -> bool:
        """Atomically replace a value when its revision field still matches.
        仅当当前值的 revision 字段仍匹配时，原子替换该 session 字段。

        Args:
            session_id: Owning session id. (所属 session id。)
            key: Top-level session field to replace. (待替换的顶层字段。)
            value: Complete replacement value. (完整的新值。)
            revision_path: Mapping-key path used to find the revision token.
                (用于定位版本 token 的映射键路径。)
            expected_revision: Revision that must still be current.
                (提交时必须仍然有效的版本值。)

        Returns:
            ``True`` only when the active session was updated. A missing,
            closing, retired, or superseded session returns ``False``.
            仅在活动 session 成功写入时返回 ``True``；不存在、关闭中、
            已退役或版本已被替换时返回 ``False``。
        """

        with self._lock:
            self._prune_retired_locked()
            if (
                session_id in self._retired_sessions
                or session_id in self._closing_sessions
                or session_id not in self._store
            ):
                return False
            current = self._store[session_id].get(key)
            revision: Any = current
            for field in revision_path:
                if not isinstance(revision, Mapping) or field not in revision:
                    return False
                revision = revision[field]
            if not revision_path or revision != expected_revision:
                return False
            self._renew_lease_locked(session_id)
            self._store[session_id][key] = value
            return True

    def register_temp_file(self, session_id: str, path: str) -> None:
        """注册临时文件路径，session 清理时一并删除。"""
        with self._lock:
            self._prune_retired_locked()
            if session_id in self._retired_sessions:
                return
            if session_id in self._closing_sessions:
                return
            if session_id in self._temp_files:
                self._temp_files[session_id].append(path)

    def touch(self, session_id: str) -> float | None:
        """Renew the session lease and return the new expiry timestamp.
        续期指定 session 的租约，并返回新的过期时间戳。
        """
        with self._lock:
            self._prune_retired_locked()
            if session_id in self._retired_sessions:
                return None
            if session_id not in self._store:
                return None
            if session_id in self._closing_sessions:
                return None
            return self._renew_lease_locked(session_id)

    def close(self, session_id: str) -> int:
        """Close a session immediately and clean its tracked temp files.
        立即关闭指定 session，并清理其追踪的临时文件。
        """
        return self.close_except(session_id, keep_paths=None)

    def cleanup_temp_files_except(self, session_id: str, keep_paths: set[str] | None = None) -> int:
        """Clean tracked temp files while preserving the session itself.
        清理追踪的临时文件，但保留 session 数据本身。
        """
        cleaned, _ = self._cleanup_session(session_id, keep_paths=keep_paths, remove_session=False)
        return cleaned

    def close_except(self, session_id: str, keep_paths: set[str] | None = None) -> int:
        """Close a session while preserving selected temp-file paths.
        关闭指定 session，并保留 keep_paths 中的临时文件路径。
        """
        cleaned, _ = self._cleanup_session(session_id, keep_paths=keep_paths, remove_session=True)
        return cleaned

    def cleanup_expired(self) -> list[str]:
        """Clean up expired sessions and return their IDs.
        清理过期 session，返回已清理的 session ID 列表。
        """
        now = time.time()
        with self._lock:
            self._prune_retired_locked(now)
            expired_candidates = [
                sid for sid, expires_at in self._timestamps.items() if now >= expires_at
            ]
        cleaned_sessions: list[str] = []
        for sid in expired_candidates:
            _, closed = self._cleanup_session(sid, keep_paths=None, remove_session=True)
            if closed:
                cleaned_sessions.append(sid)
        return cleaned_sessions

    def clear_all(self) -> int:
        """清除所有会话及其临时文件，返回清理的会话数量。"""
        with self._lock:
            self._prune_retired_locked()
            session_ids = list(self._store.keys())
        cleaned_sessions = 0
        for sid in session_ids:
            _, closed = self._cleanup_session(sid, keep_paths=None, remove_session=True)
            if closed:
                cleaned_sessions += 1
        return cleaned_sessions

    def exists(self, session_id: str) -> bool:
        """检查 session 是否存在。"""
        with self._lock:
            self._prune_retired_locked()
            if session_id in self._retired_sessions:
                return False
            return session_id in self._store and session_id not in self._closing_sessions

    def get_temp_file_paths(self, session_id: str) -> list[str]:
        """Return a snapshot of tracked temp-file paths for a session.
        返回指定 session 当前追踪的临时文件路径快照。
        """
        with self._lock:
            return list(self._temp_files.get(session_id, []))

    def get_inactive_session_ids(self) -> list[str]:
        """Return inactive session IDs that are still tracked for follow-up cleanup.
        返回当前仍被追踪、且已进入 inactive/closing 状态的 session ID 列表。
        """
        with self._lock:
            self._prune_retired_locked()
            return sorted(sid for sid in self._closing_sessions if sid in self._store)

    def get_registry_cleanup_candidate_session_ids(self) -> list[str]:
        """Return session IDs whose registry files still need periodic cleanup attempts.
        返回其 registry 文件仍需周期性重试清理的 session ID 列表。
        """
        with self._lock:
            self._prune_retired_locked()
            candidate_ids = set(self._retired_sessions)
            candidate_ids.update(sid for sid in self._closing_sessions if sid in self._store)
            return sorted(candidate_ids)

    def _renew_lease_locked(self, session_id: str) -> float:
        """Renew the stored lease expiry for a session.
        在锁内更新 session 的租约过期时间。
        """
        expires_at = time.time() + self._lease_seconds
        self._timestamps[session_id] = expires_at
        return expires_at

    def _prune_retired_locked(self, now: float | None = None) -> None:
        """Drop expired tombstones so retired session tracking stays bounded.
        清理过期的 tombstone，避免 retired session 跟踪无限增长。
        """
        current_time = time.time() if now is None else now
        expired_sids = [
            sid for sid, expires_at in self._retired_sessions.items() if current_time >= expires_at
        ]
        for sid in expired_sids:
            self._retired_sessions.pop(sid, None)

    def _cleanup_session(
        self,
        session_id: str,
        keep_paths: set[str] | None = None,
        remove_session: bool = True,
    ) -> tuple[int, bool]:
        """Run session temp-file cleanup with filesystem work outside the store lock.
        执行 session 临时文件清理，并将文件系统操作移到锁外。
        """
        keep_paths = keep_paths or set()
        with self._lock:
            self._prune_retired_locked()
            if session_id not in self._store:
                return 0, True
            if remove_session:
                self._closing_sessions.add(session_id)
            snapshot_paths = list(self._temp_files.get(session_id, []))

        attempted_paths = [path for path in snapshot_paths if path not in keep_paths]
        cleaned, failed_paths = self._delete_paths(attempted_paths)
        attempted_path_set = set(attempted_paths)
        failed_path_set = set(failed_paths)

        with self._lock:
            self._prune_retired_locked()
            if session_id not in self._store:
                self._closing_sessions.discard(session_id)
                return cleaned, True

            current_paths = list(self._temp_files.get(session_id, []))
            updated_paths: list[str] = []
            can_close = True

            for path in current_paths:
                if path in keep_paths or path in failed_path_set:
                    updated_paths.append(path)
                    if path in failed_path_set:
                        can_close = False
                    continue
                if path in attempted_path_set:
                    continue
                updated_paths.append(path)
                if remove_session and path not in keep_paths:
                    can_close = False

            self._temp_files[session_id] = updated_paths

            if remove_session and can_close:
                self._store.pop(session_id, None)
                self._timestamps.pop(session_id, None)
                self._temp_files.pop(session_id, None)
                self._closing_sessions.discard(session_id)
                self._retired_sessions[session_id] = time.time() + self._lease_seconds
                return cleaned, True

            return cleaned, False

    def _delete_paths(self, paths: list[str]) -> tuple[int, list[str]]:
        """Delete paths outside the store lock and report failures that still exist.
        在锁外删除路径，并报告删除失败后仍存在的路径。
        """
        cleaned = 0
        failed_paths: list[str] = []

        for path in paths:
            if not os.path.exists(path):
                cleaned += 1
                continue

            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                cleaned += 1
            except FileNotFoundError:
                cleaned += 1
            except (PermissionError, OSError):
                if os.path.exists(path):
                    failed_paths.append(path)
                else:
                    cleaned += 1

        return cleaned, failed_paths
