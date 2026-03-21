import os
import threading
import uuid
from typing import Optional, Tuple


class FileRegistry:
    """文件注册表，管理生成文件的 UUID 映射。

    支持两种注册方式：
    1. register_path(session_id, path, filename) — 注册磁盘文件路径
    2. register_bytes(session_id, data, filename) — 注册内存字节流（保存为临时文件）
    """

    def __init__(self) -> None:
        self._registry: dict[str, dict] = {}  # {file_id: {path, filename, session_id}}
        self._lock = threading.Lock()

    def register_path(self, session_id: str, path: str,
                      filename: Optional[str] = None) -> str:
        """注册磁盘文件，返回 file_id。"""
        file_id = str(uuid.uuid4())
        if filename is None:
            filename = os.path.basename(path)
        with self._lock:
            self._registry[file_id] = {
                "path": path,
                "filename": filename,
                "session_id": session_id,
            }
        return file_id

    def register_bytes(self, session_id: str, data: bytes,
                       filename: str) -> str:
        """注册字节流（写入临时文件），返回 file_id。"""
        import tempfile
        suffix = os.path.splitext(filename)[1] or ".bin"
        fd, path = tempfile.mkstemp(suffix=suffix)
        try:
            os.write(fd, data)
        finally:
            os.close(fd)
        return self.register_path(session_id, path, filename)

    def resolve(self, file_id: str) -> Optional[Tuple[str, str]]:
        """解析 file_id，返回 (path, filename) 或 None。"""
        with self._lock:
            entry = self._registry.get(file_id)
        if entry is None:
            return None
        path = entry["path"]
        if not os.path.exists(path):
            return None
        return path, entry["filename"]

    def cleanup_session(self, session_id: str) -> int:
        """清理指定 session 的所有注册文件，返回清理数量。"""
        to_remove = []
        with self._lock:
            for fid, entry in self._registry.items():
                if entry["session_id"] == session_id:
                    to_remove.append(fid)
            for fid in to_remove:
                self._registry.pop(fid, None)
        return len(to_remove)

    def clear_all(self) -> int:
        """清除所有注册文件并删除磁盘文件，返回清理数量。"""
        with self._lock:
            count = 0
            for fid, entry in list(self._registry.items()):
                path = entry.get("path")
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                        count += 1
                    except OSError:
                        pass
                self._registry.pop(fid, None)
            return count
