"""Creative Workshop module backend routes (local app only).
创意工坊模块后端接口（仅限本机应用）。

Backends run as local processes with the user's permissions, so every route
requires a loopback client and local origin. Module enablement, consent,
and Registry revocation are checked by the runtime before any process runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, NoReturn

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from api.errors import to_http_exception
from api.file_bridge import UploadTooLargeError, upload_to_tempfile
from api.local_origin_guard import require_local_app_origin
from api.schemas.workshop_backend import (
    BackendAccelerationRequest,
    BackendAuthorizeRequest,
    BackendDeletionResponse,
    BackendTaskListResponse,
    BackendTaskResponse,
)
from api.structured_logging import get_logger
from api.workshop_runtime_service import get_workshop_backend_runtime
from config import get_workshop_data_dir
from core.workshop.backend.runtime import TaskInputFile, WorkshopBackendRuntime
from core.workshop.constants import MAX_BACKEND_TASK_FILE_BYTES, MAX_BACKEND_TASK_INPUTS
from core.workshop.errors import WorkshopBackendError


router = APIRouter(
    prefix="/api/workshop/v1",
    tags=["Creative Workshop backends"],
    dependencies=[Depends(require_local_app_origin)],
)
log = get_logger(__name__)

_OUTPUT_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def get_backend_runtime() -> WorkshopBackendRuntime:
    """Runtime for the configured Workshop data directory."""

    from api.routers import workshop as workshop_routes

    installer = workshop_routes.get_workshop_installer()
    return get_workshop_backend_runtime(getattr(installer, "data_dir", get_workshop_data_dir()))


def raise_backend_error(
    exc: WorkshopBackendError,
    *,
    event: str,
    module_id: str | None = None,
    version: str | None = None,
) -> NoReturn:
    """Log the failure with its context, then map it at this API boundary."""

    http_error = to_http_exception(exc, context="Creative Workshop backend request")
    log.warning(
        "Creative Workshop backend request failed",
        extra={
            "event": event,
            "status_code": http_error.status_code,
            "error_type": type(exc).__name__,
            "error_code": exc.code,
            "error_message": str(exc),
            "module_id": module_id,
            "version": version,
        },
    )
    raise http_error from exc


@router.get("/modules/{module_id}/{version}/backend")
def workshop_backend_status(module_id: str, version: str) -> dict[str, Any]:
    """Backend declaration, review level, consent, footprint, and runtime state."""

    try:
        return get_backend_runtime().describe(module_id, version)
    except WorkshopBackendError as exc:
        raise_backend_error(exc, event="workshop_backend_status_failed", module_id=module_id, version=version)


@router.post("/modules/{module_id}/{version}/backend/authorize")
def workshop_backend_authorize(
    module_id: str,
    version: str,
    payload: BackendAuthorizeRequest,
) -> dict[str, Any]:
    try:
        return get_backend_runtime().authorize(
            module_id,
            version,
            acknowledge_unreviewed=payload.acknowledge_unreviewed,
        )
    except WorkshopBackendError as exc:
        raise_backend_error(exc, event="workshop_backend_authorize_failed", module_id=module_id, version=version)


@router.post(
    "/modules/{module_id}/{version}/backend/prepare",
    response_model=BackendTaskResponse,
)
def workshop_backend_prepare(module_id: str, version: str) -> BackendTaskResponse:
    """Start the cancellable dependency/model preparation task."""

    try:
        return BackendTaskResponse.from_record(get_backend_runtime().start_preparation(module_id, version))
    except WorkshopBackendError as exc:
        raise_backend_error(exc, event="workshop_backend_prepare_failed", module_id=module_id, version=version)


@router.put("/modules/{module_id}/backend/acceleration")
def workshop_backend_acceleration(
    module_id: str,
    payload: BackendAccelerationRequest,
) -> dict[str, Any]:
    try:
        return get_backend_runtime().set_acceleration(module_id, payload.variant)
    except WorkshopBackendError as exc:
        raise_backend_error(exc, event="workshop_backend_acceleration_failed", module_id=module_id)


@router.post("/modules/{module_id}/backend/stop")
def workshop_backend_stop(module_id: str) -> dict[str, str]:
    """User action: end the module's running backend process now."""

    try:
        get_backend_runtime().stop_backend_process(module_id)
    except WorkshopBackendError as exc:
        raise_backend_error(exc, event="workshop_backend_stop_failed", module_id=module_id)
    return {"status": "ok"}


@router.post("/modules/{module_id}/backend/presence")
def workshop_backend_presence(module_id: str) -> dict[str, str]:
    """Heartbeat while the module UI is open; extends the idle window."""

    try:
        get_backend_runtime().touch_presence(module_id)
    except WorkshopBackendError as exc:
        raise_backend_error(exc, event="workshop_backend_presence_failed", module_id=module_id)
    return {"status": "ok"}


def _parse_json(value: str, *, expected: type, label: str) -> Any:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise WorkshopBackendError("task-input-invalid", f"Backend task {label} must be JSON.") from exc
    if not isinstance(parsed, expected):
        raise WorkshopBackendError("task-input-invalid", f"Backend task {label} has the wrong shape.")
    return parsed


@router.post(
    "/modules/{module_id}/backend/tasks",
    response_model=BackendTaskResponse,
)
async def workshop_backend_submit(
    module_id: str,
    version: Annotated[str, Form()],
    operation: Annotated[str, Form()],
    params: Annotated[str, Form()] = "{}",
    inputs_meta: Annotated[str, Form()] = "[]",
    idempotency_key: Annotated[str | None, Form()] = None,
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> BackendTaskResponse:
    """Persist one task with its inputs and return immediately.

    The task belongs to the host: closing the module page or this request
    never cancels it. 任务归宿主所有，关闭页面或断开请求都不会取消它。
    """

    uploads = files or []
    temporary: list[str] = []
    try:
        if len(uploads) > MAX_BACKEND_TASK_INPUTS:
            raise WorkshopBackendError("task-inputs-too-many", "Too many backend task inputs.")
        parsed_params = _parse_json(params, expected=dict, label="parameters")
        metadata = _parse_json(inputs_meta, expected=list, label="input list")
        if len(metadata) != len(uploads) or not all(isinstance(item, dict) for item in metadata):
            raise WorkshopBackendError("task-input-invalid", "Backend task inputs do not match their files.")
        if idempotency_key is not None and not 0 < len(idempotency_key) <= 128:
            raise WorkshopBackendError("task-input-invalid", "Backend task idempotency key is invalid.")
        inputs: list[TaskInputFile] = []
        for meta, upload in zip(metadata, uploads):
            path = await upload_to_tempfile(upload, suffix=".workshop-input", max_bytes=MAX_BACKEND_TASK_FILE_BYTES)
            temporary.append(path)
            inputs.append(
                TaskInputFile(
                    name=str(meta.get("name", "")),
                    file_name=str(meta.get("fileName", "")),
                    mime_type=str(meta.get("mimeType", "")),
                    path=Path(path),
                )
            )
        runtime = get_backend_runtime()
        record = await run_in_threadpool(
            runtime.submit,
            module_id,
            version,
            operation=operation,
            params=parsed_params,
            inputs=inputs,
            idempotency_key=idempotency_key,
        )
        return BackendTaskResponse.from_record(record)
    except UploadTooLargeError as exc:
        raise_backend_error(
            WorkshopBackendError("task-input-too-large", "A backend task input exceeds 64 MiB."),
            event="workshop_backend_task_submit_failed",
            module_id=module_id,
            version=version,
        )
        raise exc  # pragma: no cover - raise_backend_error never returns
    except WorkshopBackendError as exc:
        raise_backend_error(exc, event="workshop_backend_task_submit_failed", module_id=module_id, version=version)
    finally:
        for path in temporary:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass


@router.get(
    "/modules/{module_id}/backend/tasks",
    response_model=BackendTaskListResponse,
)
def workshop_backend_tasks(module_id: str) -> BackendTaskListResponse:
    try:
        records = get_backend_runtime().list_tasks(module_id)
    except WorkshopBackendError as exc:
        raise_backend_error(exc, event="workshop_backend_task_list_failed", module_id=module_id)
    return BackendTaskListResponse(tasks=tuple(BackendTaskResponse.from_record(item) for item in records[:500]))


@router.get(
    "/modules/{module_id}/backend/tasks/{task_id}",
    response_model=BackendTaskResponse,
)
def workshop_backend_task(module_id: str, task_id: str) -> BackendTaskResponse:
    try:
        return BackendTaskResponse.from_record(get_backend_runtime().get_task(module_id, task_id))
    except WorkshopBackendError as exc:
        raise_backend_error(exc, event="workshop_backend_task_read_failed", module_id=module_id)


@router.post(
    "/modules/{module_id}/backend/tasks/{task_id}/cancel",
    response_model=BackendTaskResponse,
)
def workshop_backend_cancel(module_id: str, task_id: str) -> BackendTaskResponse:
    """Cancel cooperatively; the process tree ends after the grace period."""

    try:
        return BackendTaskResponse.from_record(get_backend_runtime().cancel_task(module_id, task_id))
    except WorkshopBackendError as exc:
        raise_backend_error(exc, event="workshop_backend_task_cancel_failed", module_id=module_id)


@router.delete(
    "/modules/{module_id}/backend/tasks/{task_id}",
    response_model=BackendDeletionResponse,
)
def workshop_backend_delete_task(module_id: str, task_id: str) -> BackendDeletionResponse:
    try:
        outcome = get_backend_runtime().delete_task(module_id, task_id)
    except WorkshopBackendError as exc:
        raise_backend_error(exc, event="workshop_backend_task_delete_failed", module_id=module_id)
    return BackendDeletionResponse(freed_bytes=outcome.freed_bytes)


@router.get("/modules/{module_id}/backend/tasks/{task_id}/outputs/{name}")
def workshop_backend_output(module_id: str, task_id: str, name: str) -> FileResponse:
    """Serve a finished output from host storage; no backend process needed."""

    try:
        path, entry = get_backend_runtime().output_file(module_id, task_id, name)
    except WorkshopBackendError as exc:
        raise_backend_error(exc, event="workshop_backend_output_failed", module_id=module_id)
    return FileResponse(
        path,
        media_type=entry.mime_type,
        filename=entry.file_name,
        headers=_OUTPUT_HEADERS,
    )


@router.get("/backend/storage")
def workshop_backend_storage() -> dict[str, Any]:
    """Storage overview: environments, interpreters, models, task data."""

    try:
        return get_backend_runtime().storage_overview()
    except WorkshopBackendError as exc:
        raise_backend_error(exc, event="workshop_backend_storage_failed")


@router.delete(
    "/backend/storage/models/{sha256}",
    response_model=BackendDeletionResponse,
)
def workshop_backend_delete_model(sha256: str) -> BackendDeletionResponse:
    try:
        freed = get_backend_runtime().delete_retained_model(sha256)
    except WorkshopBackendError as exc:
        raise_backend_error(exc, event="workshop_backend_model_delete_failed")
    return BackendDeletionResponse(freed_bytes=freed)


@router.delete(
    "/backend/storage/tasks/{module_id}",
    response_model=BackendDeletionResponse,
)
def workshop_backend_delete_task_data(module_id: str) -> BackendDeletionResponse:
    try:
        freed = get_backend_runtime().delete_module_task_data(module_id)
    except WorkshopBackendError as exc:
        raise_backend_error(exc, event="workshop_backend_task_data_delete_failed", module_id=module_id)
    return BackendDeletionResponse(freed_bytes=freed)
