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
import json
import os
import re
import time
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from math import isfinite
from pathlib import Path
from typing import Any

from api.async_jobs import AsyncJobMiddleware
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.staticfiles import NotModifiedResponse, StaticFiles
from starlette.types import Scope

from api.env_loader import load_env_local
from api.runtime_limits import configure_blas_thread_limits

# Populate process env from <repo>/.env.local before any module reads
# os.environ. This must happen before logging setup (which reads
# LUMINA_LOG_*) and before feedback_email's lru_cached
# is_email_configured() is first invoked by a request handler. Putting
# the call at api.app module scope (rather than only in api_server.py)
# ensures coverage for every entry point that imports the FastAPI app:
# api_server.py, ``python -m uvicorn api.app:app``, debugpy launches,
# launcher subprocesses and CI runners.
# 在任何模块读取 os.environ 之前，从 <repo>/.env.local 把值填入进程
# 环境。必须早于日志初始化（它会读 LUMINA_LOG_*）以及第一次请求触发
# feedback_email 的 lru_cached is_email_configured()。把调用放在
# api.app 模块作用域而不是仅限 api_server.py，可以覆盖所有导入 FastAPI
# 应用的入口：api_server.py、``python -m uvicorn api.app:app``、
# debugpy 启动、启动器子进程及 CI 等。
load_env_local()
configure_blas_thread_limits()

from api.logger import setup_file_logging
from api.structured_logging import (
    configure_structured_logging,
    get_logger,
    reset_request_id,
    reset_session_id,
    set_request_id,
    set_session_id,
)

# Select file logging as early as possible, then ensure structured handlers are active.
setup_file_logging()
configure_structured_logging()

from api.dependencies import (
    file_registry,
    get_file_registry,
    get_session_store,
    session_store,
    worker_pool,
)
from api.file_bridge import file_to_response
from api.material_sync_scheduler import (
    cancel_material_sync_auto_refresh_tasks,
    start_material_sync_auto_refresh_tasks,
)
from api.workshop_seed import install_workshop_seed_if_needed
from api.routers import (
    calibration_router,
    converter_router,
    extractor_router,
    feedback_router,
    five_color_router,
    health_router,
    lut_router,
    lut_registry_router,
    material_registry_router,
    material_sync_router,
    session_router,
    slicer_router,
    single_stage_router,
    system_router,
    vectorizer_router,
    workshop_router,
)
from core.workshop import WorkshopError

log = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VALIDATION_LOG_MESSAGE_LIMIT = 1200
_CLIENT_LOG_FIELD_LIMIT = 256
_CLIENT_LOG_DETAILS_DEPTH = 4
_CLIENT_LOG_DETAILS_ITEMS = 24
_CLIENT_LOG_DETAILS_STRING_LIMIT = 1200
_CLIENT_LOG_REDACTED_LOCAL_PATH = "<redacted:local-path>"
_CLIENT_LOG_WINDOWS_LOCAL_PATH_RE = re.compile(r"\b[A-Za-z]:[\\/][^\s\"'<>),:;]*")
_CLIENT_LOG_POSIX_LOCAL_PATH_RE = re.compile(
    r"(^|[^A-Za-z0-9._~%-])"
    r"(/(?:Users|private|tmp|var|Volumes|home|opt|mnt|workspace|workspaces|app|data|output)"
    r"(?:/[^\s\"'<>),:;]*)?)"
    r"(?=$|[\s\"'<>),:;])"
)


def _compact_log_extra(extra: dict) -> dict:
    """Drop null structured-log fields while preserving explicit false/zero values.
    删除结构化日志中的空字段，同时保留 false / 0 等有效值。
    """
    return {key: value for key, value in extra.items() if value is not None}


def _truncate_log_message(message: str, limit: int) -> str:
    """Return a bounded log message without changing the HTTP response body.
    限制日志消息长度，但不改变 HTTP 响应内容。
    """
    if len(message) <= limit:
        return message
    return f"{message[:limit]}...<truncated>"


def _redact_client_log_local_paths(value: str) -> str:
    """Redact local filesystem fragments in frontend diagnostic payloads.
    脱敏前端诊断 payload 中的本地文件系统片段。
    """
    redacted = _CLIENT_LOG_WINDOWS_LOCAL_PATH_RE.sub(
        _CLIENT_LOG_REDACTED_LOCAL_PATH,
        value,
    )
    return _CLIENT_LOG_POSIX_LOCAL_PATH_RE.sub(
        lambda match: f"{match.group(1)}{_CLIENT_LOG_REDACTED_LOCAL_PATH}",
        redacted,
    )


def _format_error_detail(detail: Any) -> str:
    """Return a concise human-readable detail string for logs and UI.
    为日志和前端错误提示生成简洁可读的错误详情。
    """

    encoded_detail = jsonable_encoder(detail)
    if isinstance(encoded_detail, str):
        return encoded_detail
    if isinstance(encoded_detail, list):
        validation_parts = []
        for item in encoded_detail:
            if not isinstance(item, dict):
                continue
            message = item.get("msg")
            location = item.get("loc")
            if not message:
                continue
            if isinstance(location, list) and location:
                location_text = ".".join(str(part) for part in location)
                validation_parts.append(f"{location_text}: {message}")
            else:
                validation_parts.append(str(message))
        if validation_parts:
            return "; ".join(validation_parts)
    return json.dumps(encoded_detail, ensure_ascii=False, separators=(",", ":"))


def _sanitize_validation_errors(errors: Sequence[Any]) -> list[dict[str, Any]]:
    """Return validation errors safe for HTTP responses.
    生成可安全返回给前端的校验错误列表。
    """
    sanitized: list[dict[str, Any]] = []
    for error in errors:
        if not isinstance(error, dict):
            sanitized.append({
                "type": type(error).__name__,
                "loc": [],
                "msg": "Invalid request",
            })
            continue

        raw_loc = error.get("loc", [])
        if isinstance(raw_loc, list):
            loc = list(raw_loc)
        elif isinstance(raw_loc, tuple):
            loc = list(raw_loc)
        elif raw_loc is None:
            loc = []
        else:
            loc = [str(raw_loc)]

        item: dict[str, Any] = {
            "loc": loc,
            "msg": str(error.get("msg") or "Invalid request"),
        }
        if error.get("type") is not None:
            item["type"] = str(error["type"])
        sanitized.append(item)
    return sanitized


def _sanitize_client_log_value(value: Any, *, depth: int = 0) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _truncate_log_message(
            _redact_client_log_local_paths(value),
            _CLIENT_LOG_DETAILS_STRING_LIMIT,
        )
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else str(value)
    if depth >= _CLIENT_LOG_DETAILS_DEPTH:
        return "<truncated:depth>"
    if isinstance(value, (list, tuple)):
        items = [
            _sanitize_client_log_value(item, depth=depth + 1)
            for item in list(value)[:_CLIENT_LOG_DETAILS_ITEMS]
        ]
        remaining = len(value) - _CLIENT_LOG_DETAILS_ITEMS
        if remaining > 0:
            items.append(f"<truncated:{remaining}>")
        return items
    if isinstance(value, dict):
        sanitized = {}
        items = list(value.items())
        for raw_key, raw_value in items[:_CLIENT_LOG_DETAILS_ITEMS]:
            key = _truncate_log_message(
                _redact_client_log_local_paths(str(raw_key)),
                120,
            )
            sanitized[key] = _sanitize_client_log_value(raw_value, depth=depth + 1)
        remaining = len(items) - _CLIENT_LOG_DETAILS_ITEMS
        if remaining > 0:
            sanitized["__truncated_keys"] = remaining
        return sanitized
    return _truncate_log_message(str(value), _CLIENT_LOG_DETAILS_STRING_LIMIT)


def _coerce_client_log_duration(value: Any) -> float | None:
    if isinstance(value, (int, float)) and isfinite(float(value)):
        return round(float(value), 3)
    return None


def _env_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _material_registry_service_enabled() -> bool:
    """Return whether this process should expose Registry write-service routes.
    判断当前进程是否暴露耗材 Registry 写服务路由。
    """
    return _env_enabled("LUMINA_ENABLE_MATERIAL_REGISTRY_SERVICE") or _env_enabled(
        "LUMINA_MATERIAL_REGISTRY_SERVICE_MODE"
    )


_FRONTEND_MEDIA_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".html": "text/html",
}


class _FrontendStaticFiles(StaticFiles):
    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        """Keep browser entry types independent of host MIME associations.

        固定浏览器入口资源类型，避免系统文件关联阻止脚本与样式加载。
        """
        media_type = _FRONTEND_MEDIA_TYPES.get(Path(full_path).suffix.lower())
        if media_type is None:
            return super().file_response(full_path, stat_result, scope, status_code)
        response = FileResponse(
            full_path,
            status_code=status_code,
            stat_result=stat_result,
            media_type=media_type,
        )
        # File timestamps alone cannot distinguish a cached, incorrect MIME type.
        representation = f"{response.headers['etag']}:{media_type}"
        response.headers["etag"] = f'"{representation.encode().hex()}"'
        request_headers = Headers(scope=scope)
        if request_headers.get("if-none-match") and self.is_not_modified(
            response.headers, request_headers
        ):
            return NotModifiedResponse(response.headers)
        return response


def _configure_frontend_dist(app: FastAPI) -> None:
    """Serve a built React SPA from the configured directory.
    提供指定目录中已构建的 React SPA。
    """
    if not _env_enabled("LUMINA_SERVE_FRONTEND_DIST"):
        return

    dist_dir = Path(
        os.environ.get("LUMINA_FRONTEND_DIST_DIR") or _REPO_ROOT / "frontend" / "dist"
    ).resolve()
    index_path = dist_dir / "index.html"
    assets_dir = dist_dir / "assets"
    if not index_path.is_file():
        log.warning(
            "Frontend dist index missing",
            extra={
                "event": "frontend_dist_missing",
                "path": str(index_path),
            },
        )
        return

    if assets_dir.is_dir():
        app.mount(
            "/assets", _FrontendStaticFiles(directory=str(assets_dir)),
            name="frontend-assets",
        )

    # A cached entry can load an old UI against an upgraded backend.
    index_headers = {"Cache-Control": "no-store"}

    @app.get("/", include_in_schema=False)
    async def frontend_index() -> FileResponse:
        return FileResponse(index_path, media_type="text/html", headers=index_headers)

    @app.get("/{full_path:path}", include_in_schema=False)
    async def frontend_spa_fallback(request: Request, full_path: str) -> FileResponse:
        if request.url.path.startswith("/api"):
            raise HTTPException(status_code=404, detail="Not Found")
        requested_path = (dist_dir / full_path).resolve()
        if (
            requested_path.is_file()
            and (requested_path == dist_dir or dist_dir in requested_path.parents)
        ):
            return FileResponse(
                requested_path,
                media_type=_FRONTEND_MEDIA_TYPES.get(requested_path.suffix.lower()),
                headers=index_headers if requested_path == index_path else None,
            )
        return FileResponse(index_path, media_type="text/html", headers=index_headers)


def _run_cleanup_pass(
    active_session_store=None,
    active_file_registry=None,
) -> tuple[list[str], list[str], int]:
    """Run one cleanup pass for expired sessions and registry files.
    执行一次过期 session 与 registry 文件清理。
    """
    store = session_store if active_session_store is None else active_session_store
    registry = file_registry if active_file_registry is None else active_file_registry

    expired_sids = store.cleanup_expired()
    registry_cleanup_sids = list(
        dict.fromkeys([*expired_sids, *store.get_registry_cleanup_candidate_session_ids()])
    )
    for sid in registry_cleanup_sids:
        registry.cleanup_session(sid)
    expired_files = registry.cleanup_expired()
    return expired_sids, registry_cleanup_sids, expired_files


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application startup and shutdown lifecycle.
    管理应用启动和关闭的生命周期。

    Startup:
        - Initialize the WorkerPool process pool.
          初始化 WorkerPool 进程池。
        - Start the periodic session cleanup background task.
          启动定期会话清理后台任务。
        - Run feedback startup cleanup to mark interrupted tickets and
          prune TTL-expired attachments (see
          :func:`api.feedback_assembler.run_startup_cleanup`).
          执行反馈工单启动清理，标记中断工单并删除过期大附件。

    Shutdown:
        - Gracefully shut down the WorkerPool, waiting for in-flight tasks.
          优雅关闭 WorkerPool，等待正在执行的任务完成。
    """
    # --- Startup ---
    worker_pool.start()
    log.info(
        "Worker pool started",
        extra={"event": "worker_pool_started", "max_workers": worker_pool.max_workers},
    )

    if os.environ.get("LUMINA_RUNTIME_PROBE", "").strip() == "1":
        try:
            yield
        finally:
            worker_pool.shutdown(wait=True)
            log.info(
                "Worker pool shutdown complete",
                extra={"event": "worker_pool_shutdown"},
            )
        return

    # Feedback startup cleanup: best-effort; never blocks app boot.
    # 反馈启动清理：尽力而为，绝不阻塞应用启动。
    try:
        from pathlib import Path as _Path
        from api.feedback_assembler import run_startup_cleanup

        override = os.environ.get("LUMINA_FEEDBACK_DUMP_DIR")
        repo_root = _Path(__file__).resolve().parent.parent
        feedback_root = _Path(override).resolve() if override else (repo_root / "feedback").resolve()
        run_startup_cleanup(feedback_root)
    except Exception as exc:  # noqa: BLE001 — cleanup must never crash startup.
        log.error(
            "Feedback startup cleanup raised.",
            extra={
                "event": "feedback_ticket_assembled_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )

    try:
        from api.material_seed import install_material_seed_if_needed

        seed_result = install_material_seed_if_needed()
        if seed_result is not None:
            log.info(
                "Material seed installed",
                extra={
                    "event": "material_seed_install_done",
                    "installed_count": seed_result["installed_count"],
                    "seed_source": seed_result["seed_source"],
                },
            )
    except Exception as exc:  # noqa: BLE001 — seed bootstrap must not block startup.
        log.warning(
            "Material seed install failed",
            extra={
                "event": "material_seed_install_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )

    try:
        workshop_seed_result = install_workshop_seed_if_needed()
        if workshop_seed_result is not None:
            log.info(
                "Creative Workshop seed converged",
                extra={
                    "event": "workshop_seed_converge_done",
                    "module_id": workshop_seed_result.module_id,
                    "version": workshop_seed_result.version,
                    "seed_action": workshop_seed_result.action,
                },
            )
    except (OSError, ValueError, WorkshopError) as exc:
        log.error(
            "Creative Workshop seed convergence failed",
            extra={
                "event": "workshop_seed_converge_failed",
                "error_type": type(exc).__name__,
                "error_message": (
                    "configured Workshop seed could not be verified "
                    "or installed"
                ),
                "seed_configured": True,
            },
        )

    async def _cleanup_loop() -> None:
        """Periodically clean up expired sessions and their registered files.
        定期清理过期会话及其注册文件。
        """
        while True:
            await asyncio.sleep(60)
            expired_sids, registry_cleanup_sids, expired_files = _run_cleanup_pass()
            if expired_sids:
                log.info(
                    "Expired sessions cleaned",
                    extra={"event": "session_cleanup", "cleaned_sessions": len(expired_sids)},
                )
            inactive_registry_cleanup_count = len(
                [sid for sid in registry_cleanup_sids if sid not in expired_sids]
            )
            if inactive_registry_cleanup_count:
                log.info(
                    "Inactive session registry files cleaned",
                    extra={
                        "event": "inactive_session_registry_cleanup",
                        "cleaned_sessions": inactive_registry_cleanup_count,
                    },
                )
            if expired_files:
                log.info(
                    "Expired files cleaned",
                    extra={"event": "file_cleanup", "cleaned_files": expired_files},
                )

    cleanup_task = asyncio.create_task(_cleanup_loop())
    material_sync_refresh_tasks = start_material_sync_auto_refresh_tasks()

    yield

    # --- Shutdown ---
    cleanup_task.cancel()
    await cancel_material_sync_auto_refresh_tasks(material_sync_refresh_tasks)
    worker_pool.shutdown(wait=True)
    log.info("Worker pool shutdown complete", extra={"event": "worker_pool_shutdown"})


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.
    创建并配置 FastAPI 应用实例。

    Returns:
        FastAPI: A fully-configured application instance with CORS middleware,
            lifespan manager, and all domain routers registered.
            配置完整的应用实例，已注册 CORS 中间件、生命周期管理器和所有领域路由。
    """
    app = FastAPI(title="Lumina Studio API", version="2.0", lifespan=lifespan)

    # Long requests -> pollable jobs, so reverse proxies do not time out (504).
    # Added before CORS so job responses still carry CORS headers.
    # 长请求转为可轮询任务，避免反向代理超时 504。
    app.add_middleware(AsyncJobMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        request_token = set_request_id(request_id)
        session_token = set_session_id(None)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 3)
            log.exception(
                "Unhandled API exception",
                extra={
                    "event": "api_unhandled_exception",
                    "request_id": request_id,
                    "path": request.url.path,
                    "method": request.method,
                    "status_code": 500,
                    "duration_ms": duration_ms,
                    "error_type": type(exc).__name__,
                    "error_message": _truncate_log_message(
                        str(exc),
                        _VALIDATION_LOG_MESSAGE_LIMIT,
                    ),
                },
            )
            reset_request_id(request_token)
            reset_session_id(session_token)
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal server error"},
                headers={"X-Request-ID": request_id},
            )

        if isinstance(response, Response):
            response.headers["X-Request-ID"] = request_id
        reset_request_id(request_token)
        reset_session_id(session_token)
        return response

    @app.exception_handler(StarletteHTTPException)
    async def _log_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Log handled HTTP errors with actionable fields and stable responses.
        使用可定位字段记录 HTTP 错误，同时保持稳定响应体。
        """

        request_id = getattr(
            request.state,
            "request_id",
            request.headers.get("X-Request-ID"),
        )
        error_message = _truncate_log_message(
            _format_error_detail(exc.detail),
            _VALIDATION_LOG_MESSAGE_LIMIT,
        )
        log_method = log.error if exc.status_code >= 500 else log.warning
        log_method(
            "API HTTP error",
            extra=_compact_log_extra({
                "event": "api_http_error",
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "status_code": exc.status_code,
                "error_type": type(exc).__name__,
                "error_message": error_message,
            }),
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": jsonable_encoder(exc.detail)},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _log_request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Log FastAPI 422 validation details so frontend bugs are diagnosable.

        记录 FastAPI 422 验证错误详情，方便定位前端载荷不匹配的 bug。
        """
        # Pydantic/FastAPI validation entries can include the raw submitted
        # ``input`` and ``ctx`` values. Keep only the actionable shape needed by
        # frontend error rendering and logs.
        # Pydantic/FastAPI 校验项可能包含原始 ``input`` 和 ``ctx``，响应体只保留
        # 前端错误展示和日志诊断需要的字段。
        encoded_errors = jsonable_encoder(_sanitize_validation_errors(exc.errors()))
        request_id = getattr(
            request.state,
            "request_id",
            request.headers.get("X-Request-ID"),
        )
        log.warning(
            "API validation failed",
            extra=_compact_log_extra({
                "event": "api_validation_failed",
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "status_code": 422,
                "error_type": "RequestValidationError",
                "error_message": _truncate_log_message(
                    _format_error_detail(encoded_errors),
                    _VALIDATION_LOG_MESSAGE_LIMIT,
                ),
                "validation_error_count": len(encoded_errors),
            }),
        )
        return JSONResponse(
            status_code=422,
            content={"detail": encoded_errors},
        )

    app.include_router(converter_router)
    app.include_router(extractor_router)
    app.include_router(feedback_router)
    app.include_router(calibration_router)
    app.include_router(five_color_router)
    app.include_router(health_router)
    app.include_router(lut_router)
    app.include_router(lut_registry_router)
    if _material_registry_service_enabled():
        app.include_router(material_registry_router)
    app.include_router(material_sync_router)
    app.include_router(session_router)
    app.include_router(slicer_router)
    app.include_router(single_stage_router)
    app.include_router(system_router)
    app.include_router(vectorizer_router)
    app.include_router(workshop_router)

    @app.get("/api/files/{file_id}")
    def serve_file(
        request: Request,
        file_id: str,
        registry=Depends(get_file_registry),
        store=Depends(get_session_store),
    ):
        """Serve a registered file by file_id."""
        entry = registry.get_entry(file_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="File not found or expired")
        if entry.get("is_public") is False:
            raise HTTPException(status_code=404, detail="File not found or expired")

        result = registry.resolve(file_id)
        if result is None:
            raise HTTPException(status_code=404, detail="File not found or expired")

        path, filename = result
        current_entry = registry.get_entry(file_id)
        if (
            current_entry is None
            or current_entry.get("is_public") is False
            or current_entry.get("path") != path
        ):
            raise HTTPException(status_code=404, detail="File not found or expired")

        if current_entry.get("lifecycle") == "session_bound":
            session_id = current_entry.get("session_id")
            if not session_id or store.touch(session_id) is None:
                recovered_entry = registry.get_entry(file_id)
                if (
                    recovered_entry is None
                    or recovered_entry.get("is_public") is False
                    or recovered_entry.get("lifecycle") != "ephemeral"
                    or recovered_entry.get("path") != path
                ):
                    raise HTTPException(status_code=404, detail="File not found or expired")
                recovered_result = registry.resolve(file_id)
                if recovered_result is None:
                    raise HTTPException(status_code=404, detail="File not found or expired")
                path, filename = recovered_result
                recovered_entry = registry.get_entry(file_id)
                if (
                    recovered_entry is None
                    or recovered_entry.get("is_public") is False
                    or recovered_entry.get("lifecycle") != "ephemeral"
                    or recovered_entry.get("path") != path
                ):
                    raise HTTPException(status_code=404, detail="File not found or expired")

        return file_to_response(
            path,
            filename,
            accept_encoding=request.headers.get("accept-encoding"),
            range_header=request.headers.get("range"),
        )

    @app.post("/api/client-log")
    async def client_log(payload: dict[str, Any]):
        """Receive frontend timing events and write to server log."""
        label = _truncate_log_message(str(payload.get("label", "?")), _CLIENT_LOG_FIELD_LIMIT)
        elapsed = _coerce_client_log_duration(payload.get("elapsed_ms"))
        scope = payload.get("scope", None)
        phase = payload.get("phase", None)
        details = payload.get("details", None)
        log.debug(
            "Client log received",
            extra=_compact_log_extra({
                "event": "client_log",
                "client_label": label,
                "client_scope": (
                    _truncate_log_message(str(scope), _CLIENT_LOG_FIELD_LIMIT)
                    if scope is not None
                    else None
                ),
                "client_phase": (
                    _truncate_log_message(str(phase), _CLIENT_LOG_FIELD_LIMIT)
                    if phase is not None
                    else None
                ),
                "client_details": (
                    _sanitize_client_log_value(details)
                    if details is not None
                    else None
                ),
                "duration_ms": elapsed,
            }),
        )
        return {"ok": True}

    _configure_frontend_dist(app)

    return app


app: FastAPI = create_app()
