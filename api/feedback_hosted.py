"""Submit assembled bug-report tickets to the official feedback server.

将已装配的 Bug 报告工单提交到官方反馈服务器。

Clients no longer hold SMTP credentials. After the local ticket directory is
assembled, the backend uploads the complete ticket document, index, summary,
and every attachment to the Lumina Distribution feedback service. The server asks for
a small proof of work per submission instead of trusting any client secret.

客户端不再保存 SMTP 凭据。本地工单目录装配完成后，后端把完整工单、索引、
摘要与全部附件上传到 Lumina Distribution 反馈服务；服务端对每次提交要求少量工作量
证明，而不是信任任何客户端密钥。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from contextlib import ExitStack
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx

from api.structured_logging import get_logger
from api.feedback_files import FeedbackFile

__all__ = [
    "BUNDLE_SCHEMA",
    "DEFAULT_FEEDBACK_SERVER_URL",
    "ENV_FEEDBACK_SERVER_URL",
    "HostedSubmissionError",
    "SubmissionStatus",
    "TicketBundle",
    "build_ticket_bundle",
    "feedback_server_url",
    "solve_proof_of_work",
    "submit_ticket_bundle",
    "submit_ticket_directory",
]

log = get_logger(__name__)

SubmissionStatus = Literal["pending", "submitted", "failed", "disabled"]

DEFAULT_FEEDBACK_SERVER_URL = "https://launcher.luminastudio.com.cn"
"""Official Lumina Distribution feedback service base URL.

官方 Lumina Distribution 反馈服务的基础地址。
"""

ENV_FEEDBACK_SERVER_URL = "LUMINA_FEEDBACK_SERVER_URL"
"""Env var overriding the server base URL; ``off`` disables uploads.

覆盖反馈服务地址的环境变量；设为 ``off`` 时停用上传。
"""

ENV_FEEDBACK_SERVER_TIMEOUT_S = "LUMINA_FEEDBACK_SERVER_TIMEOUT_S"
BUNDLE_SCHEMA = "lumina-feedback-bundle/1"
MAX_PROOF_OF_WORK_BITS = 26
_DISABLED_VALUES = frozenset(("off", "disabled", "false", "0", "none"))
_TICKET_TEXT_FILES = frozenset(("ticket.json", "index.md", "summary.txt"))
_VOLATILE_TICKET_KEYS = ("submission",)
_ATTEMPTS = 2
_RETRY_DELAY_S = 2.0


class HostedSubmissionError(Exception):
    """Upload failure with a stable, non-sensitive category.

    带稳定、不含敏感信息分类的上传失败。
    """

    def __init__(self, error_type: str, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.http_status = http_status


@dataclass(frozen=True)
class BundleFile:
    """One attachment that will be uploaded. 一个将被上传的附件。"""

    name: str
    kind: str
    path: Path
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class TicketBundle:
    """Upload-ready view of one local ticket directory.

    本地工单目录的待上传视图。

    Attributes:
        ticket_id: Ticket id. / 工单号。
        document: JSON ``report`` part sent to the server. / 发送给服务端的 JSON 文档。
        files: All ticket attachments. / 全部工单附件。
        held_back: Legacy field; new bundles never omit files. / 兼容旧字段，新工单不省略文件。
    """

    ticket_id: str
    document: dict[str, Any]
    files: list[BundleFile] = field(default_factory=list)
    held_back: list[dict[str, Any]] = field(default_factory=list)


def feedback_server_url() -> str | None:
    """Return the feedback server base URL, or ``None`` when uploads are off.

    返回反馈服务基础地址；停用上传时返回 ``None``。
    """
    raw = os.environ.get(ENV_FEEDBACK_SERVER_URL)
    if raw is None or not raw.strip():
        return DEFAULT_FEEDBACK_SERVER_URL
    value = raw.strip()
    if value.lower() in _DISABLED_VALUES:
        return None
    return value.rstrip("/")


def _timeout() -> httpx.Timeout:
    try:
        seconds = float(os.environ.get(ENV_FEEDBACK_SERVER_TIMEOUT_S, "180"))
    except ValueError:
        seconds = 180.0
    seconds = seconds if seconds > 0 else 180.0
    return httpx.Timeout(seconds, connect=min(seconds, 15.0))


_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _has_proxy_env() -> bool:
    return any(bool((os.environ.get(name) or "").strip()) for name in _PROXY_ENV_KEYS)


def _build_http_client(
    *,
    timeout: httpx.Timeout,
    transport: httpx.AsyncBaseTransport | None,
    trust_env: bool,
) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=timeout,
        transport=transport,
        follow_redirects=False,
        trust_env=trust_env,
    )


def _attachment_kind(name: str) -> str:
    stem = Path(name).stem
    if stem == "original":
        return "original_image"
    if stem == "final":
        return "final_artifact"
    if stem == "lut" or re.fullmatch(r"lut_[0-9]+", stem):
        return "lut"
    return {"materials": "materials_bundle", "screenshot": "screenshot"}.get(stem, "attachment")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_optional_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def build_ticket_bundle(ticket_dir: Path, payload: dict[str, Any]) -> TicketBundle:
    """Collect the upload document and attachment list for a ticket.

    收集工单的上传文档与附件清单。

    Args:
        ticket_dir: Local ticket directory. / 本地工单目录。
        payload: Current ``ticket.json`` content. / 当前 ``ticket.json`` 内容。

    Returns:
        TicketBundle: Files to upload plus files held back on this device.
            / 待上传文件以及仅保留在本机的文件。
    """
    ticket = {key: value for key, value in payload.items() if key not in _VOLATILE_TICKET_KEYS}
    files: list[BundleFile] = []
    held_back: list[dict[str, Any]] = []
    candidates = [
        path for path in ticket_dir.iterdir()
        if path.is_file() and not path.is_symlink() and path.name not in _TICKET_TEXT_FILES
    ]
    for path in sorted(candidates):
        size = path.stat().st_size
        kind = _attachment_kind(path.name) or "attachment"
        files.append(BundleFile(path.name, kind, path, size, _file_sha256(path)))
    files.sort(key=lambda item: item.name)
    held_back.sort(key=lambda item: item["name"])
    document = {
        "schema": BUNDLE_SCHEMA,
        "ticket_id": str(payload.get("ticket_id")),
        "ticket": ticket,
        "index_md": _read_optional_text(ticket_dir / "index.md"),
        "summary_txt": _read_optional_text(ticket_dir / "summary.txt"),
        "attachments": [
            {"name": item.name, "kind": item.kind, "size_bytes": item.size_bytes, "sha256": item.sha256}
            for item in files
        ],
    }
    return TicketBundle(str(payload.get("ticket_id")), document, files, held_back)


def _leading_zero_bits(digest: bytes) -> int:
    count = 0
    for byte in digest:
        if byte:
            return count + 8 - byte.bit_length()
        count += 8
    return count


def solve_proof_of_work(challenge: str, ticket_id: str, bits: int) -> str:
    """Find a decimal nonce meeting the server's leading-zero-bit target.

    寻找满足服务端前导零比特要求的十进制 nonce。

    Args:
        challenge: Server-signed challenge. / 服务端签名的挑战串。
        ticket_id: Ticket bound into the proof. / 绑定进证明的工单号。
        bits: Required leading zero bits. / 需要的前导零比特数。

    Returns:
        str: Nonce as decimal text. / 十进制 nonce 文本。
    """
    if not 0 <= bits <= MAX_PROOF_OF_WORK_BITS:
        raise HostedSubmissionError("ProofOfWorkTooHard", "Server requested an unsupported difficulty.")
    prefix = hashlib.sha256(f"{challenge}:{ticket_id}:".encode("ascii"))
    nonce = 0
    while True:
        candidate = prefix.copy()
        candidate.update(str(nonce).encode("ascii"))
        if _leading_zero_bits(candidate.digest()) >= bits:
            return str(nonce)
        nonce += 1


async def _request_proof(client: httpx.AsyncClient, base_url: str, ticket_id: str) -> dict[str, str]:
    response = await client.post(f"{base_url}/v2/feedback/challenges")
    _raise_for_status(response)
    try:
        issued = response.json()
        challenge = str(issued["challenge"])
        bits = int(issued["difficulty_bits"])
    except (ValueError, KeyError, TypeError) as exc:
        raise HostedSubmissionError("InvalidChallenge", "Server returned an invalid challenge.") from exc
    if issued.get("algorithm") != "sha256-leading-zero-bits" or not challenge.isascii():
        raise HostedSubmissionError("InvalidChallenge", "Server returned an unsupported challenge.")
    nonce = await asyncio.to_thread(solve_proof_of_work, challenge, ticket_id, bits)
    return {"X-Lumina-Ticket": ticket_id, "X-Lumina-Challenge": challenge, "X-Lumina-Proof": nonce}


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code < 400:
        return
    categories = {403: "ProofRejected", 408: "UploadTimeout", 409: "TicketConflict",
                  413: "BundleTooLarge", 422: "BundleRejected", 429: "RateLimited"}
    error_type = categories.get(response.status_code)
    if error_type is None:
        error_type = "ServerUnavailable" if response.status_code >= 500 else "ServerRejected"
    raise HostedSubmissionError(
        error_type,
        f"Feedback server returned HTTP {response.status_code}.",
        http_status=response.status_code,
    )


async def _post_bundle(
    client: httpx.AsyncClient,
    base_url: str,
    bundle: TicketBundle,
    headers: dict[str, str],
) -> dict[str, Any]:
    with ExitStack() as stack:
        parts: list[tuple[str, Any]] = [
            ("report", (None, json.dumps(bundle.document, ensure_ascii=False), "application/json")),
        ]
        for item in bundle.files:
            handle = stack.enter_context(FeedbackFile(item.path, item.size_bytes))
            parts.append(("attachment", (item.name, handle, "application/octet-stream")))
        canonical = json.dumps(
            bundle.document, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        )
        headers = {**headers, "X-Lumina-Bundle-SHA256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}
        response = await client.post(f"{base_url}/v2/feedback/bundles", files=parts, headers=headers)
    _raise_for_status(response)
    try:
        return response.json()
    except ValueError as exc:
        raise HostedSubmissionError("InvalidReceipt", "Server returned an invalid receipt.") from exc


async def submit_ticket_bundle(
    bundle: TicketBundle,
    *,
    base_url: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Upload one bundle with a fresh proof of work, retrying transient errors.

    使用新的工作量证明上传一个工单包，并对临时性错误重试。

    Args:
        bundle: Upload-ready ticket. / 待上传工单。
        base_url: Feedback server base URL. / 反馈服务基础地址。
        transport: Optional httpx transport for tests. / 测试用 httpx transport。

    Returns:
        dict[str, Any]: Server receipt. / 服务端回执。

    Raises:
        HostedSubmissionError: Upload failed after retries. / 重试后仍失败。
    """
    last_error = HostedSubmissionError("NotAttempted", "Upload was not attempted.")
    trust_modes = [True] if transport is not None else ([False, True] if _has_proxy_env() else [False])
    non_fallback_errors = {"TicketConflict", "BundleTooLarge", "BundleRejected", "RateLimited"}
    for mode_index, trust_env in enumerate(trust_modes):
        async with _build_http_client(
            timeout=_timeout(),
            transport=transport,
            trust_env=trust_env,
        ) as client:
            for attempt in range(_ATTEMPTS):
                try:
                    headers = await _request_proof(client, base_url, bundle.ticket_id)
                    return await _post_bundle(client, base_url, bundle, headers)
                except HostedSubmissionError as exc:
                    last_error = exc
                    retryable = exc.error_type in {"ProofRejected", "ServerUnavailable", "UploadTimeout"}
                except httpx.HTTPError as exc:
                    last_error = HostedSubmissionError(
                        type(exc).__name__, f"Feedback server unreachable: {exc}"
                    )
                    retryable = True
                if not retryable or attempt + 1 >= _ATTEMPTS:
                    break
                await asyncio.sleep(_RETRY_DELAY_S)
        if last_error.error_type in non_fallback_errors or mode_index + 1 >= len(trust_modes):
            break
    raise last_error


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


async def submit_ticket_directory(
    ticket_dir: Path,
    payload: dict[str, Any],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Upload a ticket directory and return its new ``submission`` section.

    上传工单目录并返回新的 ``submission`` 状态段。

    The caller persists the returned section into ``ticket.json``; failures
    are returned as ``status="failed"`` instead of raised so ticket assembly
    never breaks because the network is down.

    调用方负责把返回的状态段写回 ``ticket.json``；失败以 ``status="failed"``
    返回而不抛出，网络故障不会打断工单装配。

    Args:
        ticket_dir: Local ticket directory. / 本地工单目录。
        payload: Current ``ticket.json`` content. / 当前 ``ticket.json`` 内容。
        transport: Optional httpx transport for tests. / 测试用 httpx transport。

    Returns:
        dict[str, Any]: ``submission`` section. / ``submission`` 状态段。
    """
    previous = payload.get("submission") if isinstance(payload.get("submission"), dict) else {}
    ticket_id = str(payload.get("ticket_id"))
    section: dict[str, Any] = {
        "status": "disabled",
        "server_status": None,
        "attempts": int(previous.get("attempts") or 0),
        "last_attempt_at_utc": previous.get("last_attempt_at_utc"),
        "submitted_at_utc": None,
        "error_type": None,
        "http_status": None,
        "uploaded_attachments": [],
        "held_back_attachments": [],
    }
    base_url = feedback_server_url()
    if base_url is None:
        return section
    section["attempts"] += 1
    section["last_attempt_at_utc"] = _utc_now()
    try:
        bundle = await asyncio.to_thread(build_ticket_bundle, ticket_dir, payload)
        section["held_back_attachments"] = bundle.held_back
        receipt = await submit_ticket_bundle(bundle, base_url=base_url, transport=transport)
    except (HostedSubmissionError, OSError) as exc:
        error_type = exc.error_type if isinstance(exc, HostedSubmissionError) else type(exc).__name__
        http_status = exc.http_status if isinstance(exc, HostedSubmissionError) else None
        section.update(status="failed", error_type=error_type, http_status=http_status)
        log.warning(
            "Bug report upload to the feedback server failed.",
            extra={
                "event": "feedback_hosted_submission_failed",
                "ticket_id": ticket_id,
                "error_type": error_type,
                "error_message": str(exc),
                "http_status": http_status,
                "attempt": section["attempts"],
                "dependency": "httpx",
            },
        )
        return section
    section.update(
        status="submitted",
        server_status=str(receipt.get("status")),
        submitted_at_utc=_utc_now(),
        uploaded_attachments=[item.name for item in bundle.files],
    )
    log.info(
        "Bug report uploaded to the feedback server.",
        extra={
            "event": "feedback_hosted_submission_done",
            "ticket_id": ticket_id,
            "server_status": section["server_status"],
            "uploaded_attachment_count": len(bundle.files),
            "held_back_attachment_count": len(bundle.held_back),
            "attempt": section["attempts"],
        },
    )
    return section
