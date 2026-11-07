"""Feedback router for manual bug report intake.

用于手动 Bug 反馈接收的反馈路由。
"""

from __future__ import annotations

import base64
import asyncio
import json
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException

from api.dependencies import get_file_registry, get_session_store
from api.feedback_assembler import (
    collect_direct_original_upload,
    collect_sync_attachments,
    finalize_ticket_async,
    resubmit_ticket_async,
)
from api.feedback_hosted import SubmissionStatus, feedback_server_url
from api.feedback_ticket import generate_ticket_id, ticket_dir_for, ticket_dir_from_id
from api.feedback_sources import collect_backend_diagnostics, collect_source_uploads
from api.feedback_files import FeedbackMultipartParser
from api.feedback_time import format_received_cst, now_beijing
from api.local_origin_guard import require_local_app_origin
from api.structured_logging import get_logger

router = APIRouter(prefix="/api/feedback", tags=["feedback"])
log = get_logger(__name__)
_REPO_ROOT = Path(__file__).resolve().parents[2]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class BugReportSessionIds(BaseModel):
    """Active session identifiers included in the report context.

    报告上下文中包含的活跃 session 标识。
    """

    model_config = ConfigDict(extra="allow")

    converter: str | None = Field(default=None)
    single_stage: str | None = Field(default=None)


class BugReportFinalArtifactRef(BaseModel):
    """Reference to the most recent generation artifact for repro (Req 3.x).

    指向最近一次生成产物的引用，用于复现（Req 3.x）。
    """

    model_config = ConfigDict(extra="allow")

    session_id: str | None = Field(default=None)
    download_url: str | None = Field(default=None)
    artifact_type: Literal["3mf", "zip", "share_card"] | None = None
    disk_path: str | None = Field(default=None)
    source: Literal[
        "converter", "single_stage", "puzzle", "vector", "batch"
    ] | None = None


class BugReportOriginalImageRef(BaseModel):
    """Reference to the user's original uploaded image for repro (Req 2.x).

    指向用户上传原图的引用，用于复现（Req 2.x）。
    """

    model_config = ConfigDict(extra="allow")

    session_id: str | None = Field(default=None)
    filename: str | None = Field(default=None)
    source: Literal["converter", "single_stage"] | None = None


class BugReportWorkshopContext(BaseModel):
    """Complete Creative Workshop diagnostic context.

    完整创意工坊诊断上下文，保留客户端提供的附加数据。
    """

    model_config = ConfigDict(extra="allow")

    module_id: str = Field(min_length=1)
    module_version: str = Field(min_length=1)
    install_source: Literal[
        "registry", "github", "local", "seed", "unknown"
    ] = "unknown"
    audit_status: Literal[
        "official",
        "verified",
        "deprecated",
        "blocked",
        "unreviewed",
        "unknown",
    ] = "unknown"
    runtime_mode: Literal[
        "desktop-secure",
        "browser-restricted",
        "unsafe-development",
        "unknown",
    ] = "unknown"
    error_code: str | None = Field(default=None)


class BugReportContext(BaseModel):
    """Client runtime context attached to a bug report.

    Bug 报告附带的客户端运行时上下文。
    """

    model_config = ConfigDict(extra="allow")

    url: str = Field()
    user_agent: str = Field()
    screen_width: int = Field(ge=0, le=100_000)
    screen_height: int = Field(ge=0, le=100_000)
    device_pixel_ratio: float = Field(ge=0.0, le=10.0)
    app_version: str = Field()
    language: Literal["zh", "en"]
    theme: Literal["light", "dark"]
    active_tab: str = Field()
    active_session_ids: BugReportSessionIds
    printer_id: str | None = Field(default=None)
    slicer: str | None = Field(default=None)
    custom_3mf_template_id: str | None = Field(default=None)
    nozzle_size: str | None = Field(default=None)
    device_profile_id: str | None = Field(default=None)
    build_plate_id: str | None = Field(default=None)
    external_spool_material: str | None = Field(default=None)
    color_mode: str | None = Field(default=None)
    lut_name: str | None = Field(default=None)
    lut_names: list[str] = Field(default_factory=list)
    source_version: Literal["legacy", "native", "material"] | None = None
    selected_native_brand_key: str | None = Field(default=None)
    selected_native_db_names: list[str] = Field(default_factory=list)
    selected_material_dir_names: list[str] = Field(default_factory=list)
    material_layer_count: int | None = Field(default=None, ge=0, le=1000)
    material_dynamic_layer_count_enabled: bool | None = None
    material_min_layer_count: int | None = Field(default=None, ge=5, le=10)
    material_max_layer_count: int | None = Field(default=None, ge=5, le=10)
    material_delta_e00_tolerance: float | None = Field(
        default=None,
        ge=0.0,
        le=5.0,
    )
    material_layer_height_mm: float | None = Field(default=None, ge=0.0, le=10.0)
    material_backing_material_dir_name: str | None = Field(default=None)
    preserve_upload_filename_for_3mf: bool | None = None
    enable_wipe_tower_auto_placement: bool | None = None
    enable_smooth_vector_preview: bool | None = None
    vector_preview_renderer: Literal["vector_analytic", "segmented"] | None = None
    recent_client_logs: list[dict[str, Any]] = Field(default_factory=list)

    # --- Reproducible-bug-reports extensions (Req 2/3/5/6). All optional so
    #     older clients that predate this upgrade still deserialize cleanly.
    # 可重现 Bug 报告新增字段；全部可选，老客户端不传也能正常反序列化。
    action_history: list[dict[str, Any]] = Field(default_factory=list)
    session_history: list[dict[str, Any]] = Field(default_factory=list)
    active_original_image_ref: BugReportOriginalImageRef | None = None
    active_final_artifact_ref: BugReportFinalArtifactRef | None = None
    workshop: BugReportWorkshopContext | None = None

    advanced_params: dict[str, Any] | None = None

    @field_validator("lut_names", mode="before")
    @classmethod
    def _validate_lut_names(cls, value: Any) -> list[str]:
        """Bound legacy multi-LUT names captured for repro.

        限制用于复现的经典多选 LUT 名称列表。
        """

        if value is None:
            return []
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                continue
            clean = item.strip()
            if clean and clean not in normalized:
                normalized.append(clean)
        return normalized


class BugReportRequest(BaseModel):
    """Bug report request payload.

    Bug 报告请求载荷。
    """

    description: str = Field(min_length=1)
    user_email: str | None = Field(default=None, max_length=320)
    context: BugReportContext
    screenshot_data_url: str | None = None

    @field_validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        """Reject whitespace-only descriptions.

        拒绝只包含空白字符的描述。
        """

        if not value.strip():
            raise ValueError("Description must not be blank")
        return value

    @field_validator("user_email")
    @classmethod
    def _validate_user_email(cls, value: str | None) -> str | None:
        """Validate the optional user email without extra dependencies.

        在不引入额外依赖的前提下校验可选邮箱。
        """

        if value is None or value == "":
            return None
        if len(value) > 320 or not _EMAIL_RE.match(value):
            raise ValueError("Invalid email address")
        return value


_DYNAMIC_MATERIAL_CONTEXT_FIELDS = {
    "material_dynamic_layer_count_enabled",
    "material_min_layer_count",
    "material_max_layer_count",
    "material_delta_e00_tolerance",
}


def _dump_bug_report_request(
    request: BugReportRequest,
    *,
    include_existing_defaults: bool = True,
) -> dict[str, Any]:
    """Serialize a report without inventing absent dynamic-material fields.

    序列化报告时不为旧客户端凭空补入未提交的动态材料字段。

    Args:
        request: Validated bug-report request. / 已校验的 Bug 报告请求。
        include_existing_defaults: Preserve the historical local ticket shape.
            / 保留既有本地工单默认字段结构。

    Returns:
        JSON-compatible request payload. / JSON 兼容的请求载荷。
    """

    if not include_existing_defaults:
        return request.model_dump(mode="json", exclude_unset=True)

    absent_dynamic_fields = (
        _DYNAMIC_MATERIAL_CONTEXT_FIELDS - request.context.model_fields_set
    )
    exclude = {"context": absent_dynamic_fields} if absent_dynamic_fields else None
    return request.model_dump(mode="json", exclude=exclude)


async def _parse_bug_report_submission(
    http_request: Request,
) -> tuple[BugReportRequest, UploadFile | None, str | None]:
    """Parse either the legacy JSON body or the multipart attachment body.

    解析兼容旧客户端的 JSON 请求，或包含原图的 multipart 请求。

    Args:
        http_request: Incoming Starlette request. / 收到的 Starlette 请求。

    Returns:
        tuple: Validated payload, optional original image, and omission reason.
            / 已校验载荷、可选原图与省略原因。
    """
    content_type = http_request.headers.get("content-type", "").lower()
    is_multipart = content_type.startswith("multipart/form-data")
    multipart_form: FormData | None = None
    keep_upload_open = False
    try:
        if is_multipart:
            parser = FeedbackMultipartParser(
                http_request.headers, http_request.stream(),
                max_files=float("inf"), max_fields=float("inf"), max_part_size=float("inf"),
            )
            try:
                multipart_form = await parser.parse()
            except MultiPartException as exc:
                raise HTTPException(status_code=400, detail=exc.message) from exc

            raw_payload = multipart_form.get("request_payload")
            upload_value = multipart_form.get("original_image")
            omission_value = multipart_form.get("original_image_omission_reason")
            if not isinstance(raw_payload, str):
                raise ValueError("request_payload must be a JSON string")
            payload_value = json.loads(raw_payload)
            original_upload = (
                upload_value if isinstance(upload_value, UploadFile) else None
            )
            uploaded_fields = {
                field_name
                for field_name, value in multipart_form.multi_items()
                if isinstance(value, UploadFile)
            }
            unexpected_file_fields = uploaded_fields - {"original_image", "source_files"}
            if unexpected_file_fields:
                raise ValueError("File fields must be original_image or source_files")
            if omission_value is not None and omission_value != "too_large":
                raise ValueError(
                    "original_image_omission_reason must be 'too_large'"
                )
            omission_reason = (
                omission_value if isinstance(omission_value, str) else None
            )
            if original_upload is not None and omission_reason is not None:
                raise ValueError(
                    "original_image and original_image_omission_reason are exclusive"
                )
            source_uploads = [value for value in multipart_form.getlist("source_files") if isinstance(value, UploadFile)]
            http_request.state.feedback_source_uploads = source_uploads
            request_model = BugReportRequest.model_validate(payload_value)
            keep_upload_open = original_upload is not None or bool(source_uploads)
            return request_model, original_upload, omission_reason

        payload_value = await http_request.json()
        return BugReportRequest.model_validate(payload_value), None, None
    except ValidationError as exc:
        errors: list[dict[str, Any]] = []
        for error in exc.errors():
            normalized = dict(error)
            location = tuple(normalized.get("loc") or ())
            if not location or location[0] != "body":
                location = ("body", *location)
            normalized["loc"] = location
            errors.append(normalized)
        raise RequestValidationError(errors, body=payload_value) from exc
    except json.JSONDecodeError as exc:
        location: tuple[str | int, ...] = (
            ("body", "request_payload", exc.pos)
            if is_multipart
            else ("body", exc.pos)
        )
        raise RequestValidationError(
            [{
                "type": "json_invalid",
                "loc": location,
                "msg": "JSON decode error",
                "input": {},
                "ctx": {"error": exc.msg},
            }],
            body=exc.doc,
        ) from exc
    except (ValueError, TypeError) as exc:
        raise RequestValidationError(
            [{
                "type": "value_error",
                "loc": ("body",),
                "msg": str(exc),
                "input": None,
                "ctx": {"error": str(exc)},
            }]
        ) from exc
    finally:
        if multipart_form is not None and not keep_upload_open:
            try:
                await multipart_form.close()
            except OSError as exc:
                log.warning(
                    "Bug-report multipart form cleanup failed.",
                    extra={
                        "event": "feedback_attachment_collection_failed",
                        "attachment_kind": "original_image",
                        "error_type": type(exc).__name__,
                        "error_message": str(exc),
                    },
                )


async def _bug_report_submission_dependency(
    http_request: Request,
) -> AsyncIterator[tuple[BugReportRequest, UploadFile | None, str | None]]:
    """Parse a submission and close any multipart temp file on every exit.

    解析提交，并在成功、校验失败或后续处理失败时统一关闭 multipart 临时文件。

    Args:
        http_request: Incoming Starlette request. / 收到的 Starlette 请求。

    Yields:
        tuple: Validated payload, optional source image, and omission reason.
            / 已校验载荷、可选原图与省略原因。
    """
    submission: tuple[BugReportRequest, UploadFile | None, str | None] | None = None
    try:
        submission = await _parse_bug_report_submission(http_request)
        yield submission
    finally:
        uploads = list(getattr(http_request.state, "feedback_source_uploads", []))
        if submission is not None and submission[1] is not None:
            uploads.append(submission[1])
        for upload in uploads:
            await upload.close()
        try:
            await http_request.close()
        except OSError as exc:
            log.warning(
                "Bug-report multipart cleanup failed.",
                extra={
                    "event": "feedback_attachment_collection_failed",
                    "attachment_kind": "original_image",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                },
            )


class BugReportResponse(BaseModel):
    """Bug report submission response payload.

    Bug 报告提交响应载荷。

    ``submission_status`` is ``pending`` while the background task uploads
    the ticket to the official feedback server, or ``disabled`` when uploads
    are switched off on this installation. Poll the status endpoint for the
    final result.

    ``submission_status`` 在后台任务上传工单期间为 ``pending``；本机停用上传
    时为 ``disabled``。最终结果请轮询状态接口。
    """

    ticket_id: str
    dump_path: str
    submission_status: SubmissionStatus
    assembly_status: Literal["in_progress", "done", "partial_failed"] | None = None
    original_image_status: Literal[
        "attached",
        "session_fallback",
        "not_applicable",
        "too_large",
        "failed",
    ] = "not_applicable"


class BugReportHeldBackAttachment(BaseModel):
    """A ticket file kept only on this device. 仅保留在本机的工单文件。"""

    name: str
    size_bytes: int
    reason: Literal["too_large", "unsupported_type", "empty", "rejected"]


class BugReportStatusResponse(BaseModel):
    """Current upload state of one local ticket.

    单个本地工单当前的上传状态。
    """

    ticket_id: str
    assembly_status: str | None = None
    submission_status: SubmissionStatus
    error_type: str | None = None
    uploaded_attachments: list[str] = Field(default_factory=list)
    held_back_attachments: list[BugReportHeldBackAttachment] = Field(default_factory=list)


def _original_image_response_status(
    attachment: Any,
    *,
    expected: bool,
) -> Literal[
    "attached",
    "session_fallback",
    "not_applicable",
    "too_large",
    "failed",
]:
    """Map the detailed manifest to the compact frontend response state.

    将详细附件清单映射为前端使用的简洁状态。
    """
    if not isinstance(attachment, dict):
        return "failed" if expected else "not_applicable"
    status_value = attachment.get("status")
    if status_value == "attached":
        return (
            "attached"
            if attachment.get("capture_source") == "browser_upload"
            else "session_fallback"
        )
    if status_value == "too_large":
        return "too_large"
    if status_value == "not_applicable" and not expected:
        return "not_applicable"
    return "failed"


def _preferred_session_id(context: BugReportContext) -> str | None:
    """Choose the most useful session id for structured logging.

    为结构化日志选择最有用的 session id。
    """

    return context.active_session_ids.converter or context.active_session_ids.single_stage


def _resolve_feedback_root() -> Path:
    """Return the on-disk root for ticket directories.

    返回工单目录的磁盘根路径。

    Honours the existing ``LUMINA_FEEDBACK_DUMP_DIR`` override (same variable
    used by legacy flat dump) and otherwise defaults to ``<repo>/feedback``.

    优先使用现有的 ``LUMINA_FEEDBACK_DUMP_DIR`` 环境变量（与旧版扁平 dump
    保持一致），未设置时回退到 ``<repo>/feedback``。

    Returns:
        Path: Resolved feedback root.
    """
    override = os.environ.get("LUMINA_FEEDBACK_DUMP_DIR")
    if override:
        return Path(override).resolve()
    return (_REPO_ROOT / "feedback").resolve()


_DATA_URL_STRICT_RE = re.compile(
    r"^data:([^;,]+);base64,(.+)$", re.DOTALL,
)
_MIME_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
}


def _decode_screenshot_data_url(data_url: str) -> tuple[str, bytes]:
    """Decode a ``data:image/...;base64,...`` URL into (ext, bytes).

    解码 ``data:image/...;base64,...`` URL 为 (扩展名, 字节) 元组。

    Strict validation rules:
    1. Must match ``data:<mime>;base64,<payload>`` exactly.
    2. MIME must be in ``_MIME_TO_EXT`` (no unknown MIME fallback).
    3. Base64 payload is decoded with ``validate=True``.

    严格校验规则：
    1. 必须精确匹配 ``data:<mime>;base64,<payload>``。
    2. MIME 必须在 ``_MIME_TO_EXT`` 中（不允许未知 MIME 兜底）。
    3. Base64 解码使用 ``validate=True``。

    Args:
        data_url: Raw data URL string from the request.
            请求中的原始 data URL 字符串。

    Returns:
        tuple[str, bytes]: Extension (with dot) and decoded bytes.

    Raises:
        HTTPException: 400 when the data URL is malformed, has an
            unsupported MIME type, or contains invalid base64.
    """
    match = _DATA_URL_STRICT_RE.match(data_url)
    if match is None:
        log.warning(
            "Screenshot data URL format invalid.",
            extra={
                "event": "feedback_screenshot_invalid",
                "error_type": "InvalidDataUrlFormat",
                "error_message": "data URL does not match data:<mime>;base64,<payload>",
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid screenshot data URL",
        )
    mime = match.group(1).strip().lower()
    payload = match.group(2)
    ext = _MIME_TO_EXT.get(mime)
    if ext is None:
        log.warning(
            "Screenshot MIME type not supported.",
            extra={
                "event": "feedback_screenshot_invalid",
                "error_type": "UnsupportedMimeType",
                "error_message": f"MIME type '{mime}' is not in the allowed list",
                "mime_type": mime,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid screenshot data URL",
        )
    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, TypeError) as exc:
        log.warning(
            "Screenshot base64 payload invalid.",
            extra={
                "event": "feedback_screenshot_invalid",
                "error_type": "InvalidBase64",
                "error_message": str(exc),
                "mime_type": mime,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid screenshot data URL",
        ) from exc
    return ext, raw


def _relative_ticket_path(ticket_dir: Path) -> str:
    """Return a non-sensitive logical POSIX path for response bodies.

    返回用于响应体的非敏感逻辑 POSIX 路径。
    """
    try:
        return ticket_dir.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return f"feedback/{ticket_dir.parent.name}/{ticket_dir.name}"


def _capture_custom_3mf_template(template_id: str) -> dict[str, Any]:
    from core.custom_3mf_templates import load_template

    try:
        settings = load_template(template_id)
        json.dumps(settings, ensure_ascii=False)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"status": "unavailable", "error_type": type(exc).__name__}
    return {"status": "captured", "settings": settings}


@router.post(
    "/bug-report",
    response_model=BugReportResponse,
    dependencies=[Depends(require_local_app_origin)],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "$ref": "#/components/schemas/BugReportRequest",
                    },
                },
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["request_payload"],
                        "properties": {
                            "request_payload": {
                                "type": "string",
                                "description": (
                                    "JSON-encoded BugReportRequest payload."
                                ),
                            },
                            "original_image": {
                                "type": "string",
                                "format": "binary",
                            },
                            "source_files": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                            },
                            "original_image_omission_reason": {
                                "type": "string",
                                "enum": ["too_large"],
                            },
                        },
                    },
                },
            },
        },
    },
)
async def submit_bug_report(
    http_request: Request,
    background_tasks: BackgroundTasks,
    submission: tuple[
        BugReportRequest,
        UploadFile | None,
        str | None,
    ] = Depends(_bug_report_submission_dependency),
) -> BugReportResponse:
    """Receive a manual user-triggered bug report.

    接收用户手动触发的 Bug 报告。

    Before returning, capture complete sources, session data, and backend
    diagnostics. File copying runs in worker threads. Material packaging,
    index/summary rendering, and official-server upload run via BackgroundTasks.
    Collection time depends on the complete data size.

    返回前完整保存源文件、会话数据和后端诊断，文件复制在线程中执行。
    耗材打包、索引摘要渲染和官方服务器上传由后台任务调度，采集耗时取决于数据大小。

    Args:
        http_request: Raw Starlette request (used for rate-limit client key).
            原始 Starlette request（用于限流取客户端 key）。
        background_tasks: FastAPI background scheduler.
            FastAPI 后台任务调度器。
        submission: Parsed JSON or multipart submission.
            已解析的 JSON 或 multipart 提交。

    Returns:
        BugReportResponse: Ticket id, email / assembly status, and dump path.
            工单号、邮件与装配状态、以及落盘路径。
    """

    request, original_upload, original_omission_reason = submission

    # Validate screenshot data URL format early — reject before creating ticket.
    # 提前校验截图格式，非法时直接 400，不创建工单。
    if request.screenshot_data_url:
        _decode_screenshot_data_url(request.screenshot_data_url)

    now = now_beijing()
    feedback_root = _resolve_feedback_root()
    try:
        feedback_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.error(
            "Bug report feedback root creation failed.",
            extra={
                "event": "feedback_dump_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "path": str(feedback_root),
            },
        )
        raise HTTPException(status_code=500, detail="Internal error storing report") from exc

    preferred_session_id = _preferred_session_id(request.context)

    try:
        ticket_id = generate_ticket_id(feedback_root, now=now, reserve=True)
    except OSError as exc:
        log.error(
            "Bug report ticket id generation failed.",
            extra={
                "event": "feedback_dump_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "path": str(feedback_root),
                "session_id": preferred_session_id,
            },
        )
        raise HTTPException(status_code=500, detail="Internal error storing report") from exc

    ticket_dir = ticket_dir_for(feedback_root, ticket_id, now)

    request_dump = _dump_bug_report_request(request)
    attachment_context_dump = deepcopy(request_dump.get("context") or {})
    context_dump = deepcopy(attachment_context_dump)
    if context_dump.get("custom_3mf_template_id"):
        context_dump["custom_3mf_template_snapshot"] = _capture_custom_3mf_template(
            context_dump["custom_3mf_template_id"]
        )

    received_at_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    request_id = getattr(http_request.state, "request_id", None)

    payload: dict[str, Any] = {
        "schema_version": 3,
        "ticket_id": ticket_id,
        "received_at_cst": format_received_cst(now),
        "received_at_utc": received_at_utc,
        "description": request.description,
        "user_email": request.user_email,
        "context": context_dump,
        "screenshot_attached": request.screenshot_data_url is not None,
        "server": {
            "schema_version": 3,
            "request_id": request_id,
            "received_at_utc": received_at_utc,
        },
        "attachments": {
            "original_image": {
                "status": "not_applicable",
                "filename": None,
                "size_bytes": None,
                "mime_type": None,
                "source_session_id": None,
                "capture_source": None,
                "direct_upload_status": "not_provided",
            },
            "final_artifact": {
                "status": "not_applicable",
                "filename": None,
                "size_bytes": None,
                "artifact_type": None,
                "source_session_id": None,
                "generated_at": None,
                "history_count": 0,
            },
            "lut": {
                "status": "not_applicable",
                "kind": None,
                "name": None,
                "preset_relative_path": None,
                "filename": None,
                "size_bytes": None,
                "metadata": {},
            },
            "materials_bundle": {
                "status": "not_applicable",
                "filename": None,
                "compressed_size_bytes": None,
                "entry_count": 0,
                "included_dirs": [],
                "excluded_cache_keys": [],
            },
            "screenshot": {
                "status": "not_applicable",
                "filename": None,
                "size_bytes": None,
            },
        },
        "submission": {
            "status": "pending" if feedback_server_url() else "disabled",
        },
        "assembly_status": "in_progress",
    }

    ticket_json_path = ticket_dir / "ticket.json"
    try:
        ticket_json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        log.error(
            "Bug report ticket.json write failed.",
            extra={
                "event": "feedback_dump_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "path": str(ticket_json_path),
                "session_id": preferred_session_id,
            },
        )
        raise HTTPException(status_code=500, detail="Internal error storing report") from exc

    # Screenshot landing — already validated by early check above.
    if request.screenshot_data_url:
        ext, raw = _decode_screenshot_data_url(request.screenshot_data_url)
        screenshot_path = ticket_dir / f"screenshot{ext}"
        try:
            screenshot_path.write_bytes(raw)
            payload["attachments"]["screenshot"] = {
                "status": "attached",
                "filename": screenshot_path.name,
                "size_bytes": screenshot_path.stat().st_size,
            }
        except OSError as exc:
            payload["attachments"]["screenshot"] = {
                "status": "failed",
                "filename": screenshot_path.name,
                "size_bytes": None,
                "error_type": type(exc).__name__,
                "error_message": "Screenshot could not be saved.",
            }
            log.warning(
                "Screenshot write failed.",
                extra={
                    "event": "feedback_attachment_lookup_failed",
                    "error_type": type(exc).__name__,
                    "error_message": str(exc),
                    "path": str(screenshot_path),
                    "attachment_kind": "screenshot",
                    "ticket_id": ticket_id,
                },
            )

    # Sync attachment collection (original image / final artifact / LUT)
    file_registry = get_file_registry()
    session_store = get_session_store()
    try:
        original_ref = request.context.active_original_image_ref
        direct_original = await collect_direct_original_upload(
            ticket_dir,
            original_upload,
            session_id=(
                original_ref.session_id
                if original_ref is not None
                else None
            ),
            omission_reason=original_omission_reason,
        )
        payload["attachments"]["original_image"] = direct_original
        attachment_payload = {**payload, "context": attachment_context_dump}
        sync_result = await asyncio.to_thread(
            collect_sync_attachments,
            ticket_dir=ticket_dir,
            payload=attachment_payload,
            file_registry=file_registry,
            now=now,
            session_store=session_store,
        )
        payload["attachments"]["original_image"] = sync_result.original_image
        payload["attachments"]["final_artifact"] = sync_result.final_artifact
        payload["attachments"]["lut"] = sync_result.lut
    except Exception as exc:  # noqa: BLE001 — never let attachment collection crash submit.
        log.error(
            "Sync attachment collection raised.",
            extra={
                "event": "feedback_attachment_lookup_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "ticket_id": ticket_id,
            },
        )

    payload["attachments"]["source_files"] = await collect_source_uploads(
        ticket_dir, list(getattr(http_request.state, "feedback_source_uploads", [])),
    )
    try:
        payload["attachments"].update(await asyncio.to_thread(collect_backend_diagnostics,
            ticket_dir, context_dump, get_file_registry(), get_session_store(),
        ))
    except Exception as exc:
        payload["attachments"]["backend_diagnostics"] = {
            "status": "failed", "error_type": type(exc).__name__, "error_message": str(exc),
        }
        log.warning("Backend diagnostic collection failed.", extra={
            "event": "feedback_attachment_collection_failed", "attachment_kind": "backend_diagnostics",
            "ticket_id": ticket_id, "error_type": type(exc).__name__, "error_message": str(exc),
        })

    # Persist the updated manifest before returning so the background task
    # starts from a complete view of sync-phase results.
    try:
        ticket_json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as exc:
        log.warning(
            "Ticket manifest rewrite after sync collection failed.",
            extra={
                "event": "feedback_dump_failed",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "path": str(ticket_json_path),
            },
        )

    # Schedule async finalize (materials zip + index/summary + server upload)
    background_tasks.add_task(
        finalize_ticket_async, ticket_dir, file_registry, session_store
    )

    submission_status: SubmissionStatus = payload["submission"]["status"]
    response_original_ref = request.context.active_original_image_ref
    original_image_expected = (
        request.context.active_tab == "converter"
        and response_original_ref is not None
        and response_original_ref.source == "converter"
        and bool(response_original_ref.session_id or response_original_ref.filename)
    )
    original_image_status = _original_image_response_status(
        payload.get("attachments", {}).get("original_image"),
        expected=original_image_expected,
    )

    log.info(
        "Bug report submitted.",
        extra={
            "event": "feedback_bug_report_submitted",
            "ticket_id": ticket_id,
            "session_id": preferred_session_id,
            "session_id_converter": request.context.active_session_ids.converter,
            "session_id_single_stage": request.context.active_session_ids.single_stage,
            "description_length": len(request.description),
            "has_screenshot": request.screenshot_data_url is not None,
            "language": request.context.language,
            "active_tab": request.context.active_tab,
            "source_version": request.context.source_version,
            "color_mode": request.context.color_mode,
            "lut_name": request.context.lut_name,
            "submission_status": submission_status,
            "original_image_status": original_image_status,
            "recent_client_log_count": len(request.context.recent_client_logs),
        },
    )

    return BugReportResponse(
        ticket_id=ticket_id,
        dump_path=_relative_ticket_path(ticket_dir),
        submission_status=submission_status,
        assembly_status="in_progress",
        original_image_status=original_image_status,
    )


def _load_ticket_for_status(ticket_id: str) -> tuple[Path, dict[str, Any]]:
    """Resolve and read a local ticket, mapping absence to 404.

    定位并读取本地工单；不存在时返回 404。
    """
    try:
        ticket_dir = ticket_dir_from_id(_resolve_feedback_root(), ticket_id)
        payload = json.loads((ticket_dir / "ticket.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Ticket not found") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket_dir, payload


def _status_response(ticket_id: str, payload: dict[str, Any]) -> BugReportStatusResponse:
    submission = payload.get("submission")
    if not isinstance(submission, dict):
        # Tickets written before server uploads existed were never submitted.
        submission = {"status": "failed", "error_type": "LegacyTicket"}
    return BugReportStatusResponse(
        ticket_id=ticket_id,
        assembly_status=payload.get("assembly_status"),
        submission_status=submission.get("status", "failed"),
        error_type=submission.get("error_type"),
        uploaded_attachments=submission.get("uploaded_attachments") or [],
        held_back_attachments=submission.get("held_back_attachments") or [],
    )


@router.get(
    "/bug-report/{ticket_id}/status",
    response_model=BugReportStatusResponse,
    dependencies=[Depends(require_local_app_origin)],
)
async def get_bug_report_status(ticket_id: str) -> BugReportStatusResponse:
    """Report whether a local ticket reached the official feedback server.

    返回本地工单是否已上传到官方反馈服务。
    """

    _, payload = _load_ticket_for_status(ticket_id)
    return _status_response(ticket_id, payload)


@router.post(
    "/bug-report/{ticket_id}/resubmit",
    response_model=BugReportStatusResponse,
    dependencies=[Depends(require_local_app_origin)],
)
async def resubmit_bug_report(ticket_id: str, http_request: Request) -> BugReportStatusResponse:
    """Retry uploading a ticket whose previous upload failed.

    重新上传之前上传失败的工单。
    """

    ticket_dir, _ = _load_ticket_for_status(ticket_id)
    if feedback_server_url() is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Feedback upload is disabled on this installation",
        )
    payload = await resubmit_ticket_async(ticket_dir)
    return _status_response(ticket_id, payload)
