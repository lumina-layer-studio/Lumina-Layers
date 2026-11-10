"""HTTP models for Workshop module backends.
创意工坊模块后端的 HTTP 接口模型。
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import Field, field_validator

from api.schemas.workshop import WorkshopHttpModel
from core.workshop.backend.tasks import TaskRecord


_VARIANT_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


class BackendAuthorizeRequest(WorkshopHttpModel):
    acknowledge_unreviewed: bool = False


class BackendAccelerationRequest(WorkshopHttpModel):
    variant: str | None = None

    @field_validator("variant")
    @classmethod
    def variant_is_safe(cls, value: str | None) -> str | None:
        if value is not None and _VARIANT_PATTERN.fullmatch(value) is None:
            raise ValueError("variant is invalid")
        return value


class BackendTaskFileResponse(WorkshopHttpModel):
    name: str
    file_name: str
    mime_type: str
    size_bytes: int


class BackendTaskProgressResponse(WorkshopHttpModel):
    completed: float
    total: float
    phase: str


class BackendTaskErrorResponse(WorkshopHttpModel):
    code: str
    message: str


class BackendTaskResponse(WorkshopHttpModel):
    task_id: str
    module_id: str
    module_version: str
    kind: Literal["operation", "prepare"]
    operation: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled", "interrupted"]
    progress: BackendTaskProgressResponse | None
    error: BackendTaskErrorResponse | None
    inputs: tuple[BackendTaskFileResponse, ...]
    outputs: tuple[BackendTaskFileResponse, ...]
    variant: str | None
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None

    @classmethod
    def from_record(cls, record: TaskRecord) -> "BackendTaskResponse":
        return cls(
            task_id=record.task_id,
            module_id=record.module_id,
            module_version=record.module_version,
            kind=record.kind,
            operation=record.operation,
            status=record.status,
            progress=(
                BackendTaskProgressResponse(**record.progress.model_dump())
                if record.progress is not None
                else None
            ),
            error=(
                BackendTaskErrorResponse(**record.error.model_dump())
                if record.error is not None
                else None
            ),
            inputs=tuple(
                BackendTaskFileResponse(
                    name=item.name,
                    file_name=item.file_name,
                    mime_type=item.mime_type,
                    size_bytes=item.size_bytes,
                )
                for item in record.inputs
            ),
            outputs=tuple(
                BackendTaskFileResponse(
                    name=item.name,
                    file_name=item.file_name,
                    mime_type=item.mime_type,
                    size_bytes=item.size_bytes,
                )
                for item in record.outputs
            ),
            variant=record.variant,
            created_at=record.created_at,
            updated_at=record.updated_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
        )


class BackendTaskListResponse(WorkshopHttpModel):
    tasks: tuple[BackendTaskResponse, ...] = Field(max_length=500)


class BackendDeletionResponse(WorkshopHttpModel):
    status: Literal["ok"] = "ok"
    freed_bytes: int
