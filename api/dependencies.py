"""Lumina Studio API — Dependency Injection.
Lumina Studio API — 依赖注入模块。

Global singletons and FastAPI dependency functions.
Separated from app.py to avoid circular imports between
app and router modules.
全局单例和 FastAPI 依赖注入函数。
从 app.py 分离以避免 app 与 router 模块之间的循环导入。
"""

from api.file_registry import FileRegistry
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager
from config import WorkerPoolConfig

# Global singletons
session_store: SessionStore = SessionStore(ttl=1800)
file_registry: FileRegistry = FileRegistry()

_worker_pool_config = WorkerPoolConfig.from_env()
worker_pool: WorkerPoolManager = WorkerPoolManager(max_workers=_worker_pool_config.MAX_WORKERS)


def get_session_store() -> SessionStore:
    """FastAPI dependency: return global SessionStore."""
    return session_store


def get_file_registry() -> FileRegistry:
    """FastAPI dependency: return global FileRegistry."""
    return file_registry


def get_worker_pool() -> WorkerPoolManager:
    """FastAPI dependency: return global WorkerPoolManager.
    FastAPI 依赖注入：返回全局 WorkerPoolManager 实例。

    Returns:
        WorkerPoolManager: The global worker pool singleton. (全局工作进程池单例)
    """
    return worker_pool
