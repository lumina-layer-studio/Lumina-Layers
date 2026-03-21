import threading
import time
import uuid
import os
from typing import Any, Dict, Optional


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
        self._lock: threading.Lock = threading.Lock()
        self._ttl: int = ttl

    def create(self) -> str:
        """创建新 session，返回 session_id (UUID4)。"""
        session_id = str(uuid.uuid4())
        with self._lock:
            self._store[session_id] = {}
            self._timestamps[session_id] = time.time()
            self._temp_files[session_id] = []
        return session_id

    def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """获取 session 数据，更新访问时间戳。不存在返回 None。"""
        with self._lock:
            if session_id not in self._store:
                return None
            self._timestamps[session_id] = time.time()
            return self._store[session_id]

    def put(self, session_id: str, key: str, value: Any) -> None:
        """写入 session 数据字段。session 不存在时自动创建。"""
        with self._lock:
            if session_id not in self._store:
                self._store[session_id] = {}
                self._timestamps[session_id] = time.time()
                self._temp_files[session_id] = []
            self._store[session_id][key] = value
            self._timestamps[session_id] = time.time()

    def register_temp_file(self, session_id: str, path: str) -> None:
        """注册临时文件路径，session 清理时一并删除。"""
        with self._lock:
            if session_id in self._temp_files:
                self._temp_files[session_id].append(path)

    def cleanup_expired(self) -> int:
        """清理过期 session，返回清理数量。"""
        now = time.time()
        expired: list[str] = []
        with self._lock:
            for sid, ts in self._timestamps.items():
                if now - ts > self._ttl:
                    expired.append(sid)
            for sid in expired:
                self._remove_session(sid)
        return len(expired)

    def _remove_session(self, session_id: str) -> None:
        """内部方法：删除 session 及其临时文件（需在锁内调用）。"""
        for path in self._temp_files.get(session_id, []):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
        self._store.pop(session_id, None)
        self._timestamps.pop(session_id, None)
        self._temp_files.pop(session_id, None)

    def clear_all(self) -> int:
        """清除所有会话及其临时文件，返回清理的会话数量。"""
        with self._lock:
            count = len(self._store)
            for sid in list(self._store.keys()):
                self._remove_session(sid)
            return count

    def exists(self, session_id: str) -> bool:
        """检查 session 是否存在。"""
        with self._lock:
            return session_id in self._store
