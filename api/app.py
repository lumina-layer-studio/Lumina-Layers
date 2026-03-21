"""Lumina Studio API — Application Factory.
Lumina Studio API — 应用工厂模块。

Provides a ``create_app()`` factory function that builds a fully-configured
FastAPI instance with CORS middleware and all domain routers registered.
Uses an async ``lifespan`` context manager to manage WorkerPool and
background tasks lifecycle.
提供 ``create_app()`` 工厂函数，构建配置完整的 FastAPI 实例，
包含 CORS 中间件和所有领域路由的注册。
使用异步 ``lifespan`` 上下文管理器管理 WorkerPool 和后台任务的生命周期。
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from api.dependencies import (
    file_registry,
    get_file_registry,
    get_session_store,
    session_store,
    worker_pool,
)
from api.file_bridge import file_to_response
from api.routers import (
    calibration_router,
    converter_router,
    extractor_router,
    five_color_router,
    health_router,
    lut_router,
    slicer_router,
    system_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown lifecycle.
    管理应用启动和关闭的生命周期。

    Startup:
        - Initialize the WorkerPool process pool.
          初始化 WorkerPool 进程池。
        - Start the periodic session cleanup background task.
          启动定期会话清理后台任务。

    Shutdown:
        - Gracefully shut down the WorkerPool, waiting for in-flight tasks.
          优雅关闭 WorkerPool，等待正在执行的任务完成。
    """
    # --- Startup ---
    worker_pool.start()
    print(f"[POOL] Started with {worker_pool.max_workers} workers")

    async def _cleanup_loop() -> None:
        """Periodically clean up expired sessions.
        定期清理过期会话。
        """
        while True:
            await asyncio.sleep(60)
            count = session_store.cleanup_expired()
            if count > 0:
                print(f"[SESSION] Cleaned up {count} expired sessions")

    cleanup_task = asyncio.create_task(_cleanup_loop())

    yield

    # --- Shutdown ---
    cleanup_task.cancel()
    worker_pool.shutdown(wait=True)
    print("[POOL] Shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.
    创建并配置 FastAPI 应用实例。

    Returns:
        FastAPI: A fully-configured application instance with CORS middleware,
            lifespan manager, and all domain routers registered.
            配置完整的应用实例，已注册 CORS 中间件、生命周期管理器和所有领域路由。
    """
    app = FastAPI(title="Lumina Studio API", version="2.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(converter_router)
    app.include_router(extractor_router)
    app.include_router(calibration_router)
    app.include_router(five_color_router)
    app.include_router(health_router)
    app.include_router(lut_router)
    app.include_router(slicer_router)
    app.include_router(system_router)

    @app.get("/api/files/{file_id}")
    def serve_file(file_id: str):
        """Serve a registered file by file_id."""
        result = file_registry.resolve(file_id)
        if result is None:
            raise HTTPException(status_code=404, detail="File not found or expired")
        path, filename = result
        return file_to_response(path, filename)

    return app


app: FastAPI = create_app()
