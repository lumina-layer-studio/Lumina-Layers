"""Turn long-running API requests into pollable background jobs.
把耗时的 API 请求转成可轮询的后台任务。

Reverse proxies (Lucky, nginx, Cloudflare ...) usually give up when a backend
sends no response headers for 30-100 s, which a deep-stack preview or 3MF
export can easily exceed. A client that sends ``X-Lumina-Async: 1`` opts in:

* The request runs as a background task. If it finishes within
  ``inline_wait`` seconds the response is returned unchanged, so quick
  requests behave exactly as before.
* Otherwise the client gets ``202`` with an ``X-Lumina-Job`` header and polls
  ``GET /api/jobs/{id}``. Each poll waits up to ``poll_wait`` seconds and
  returns either ``202`` (still running) or the original response, replayed
  byte for byte (status, headers, body).
* ``DELETE /api/jobs/{id}`` cancels a job (the client aborted).

反向代理在后端 30–100 秒不返回响应头时会断开（504）。客户端带上
``X-Lumina-Async: 1`` 后，请求在后台执行：短请求照常直接返回；长请求先
返回 202 和任务号，客户端轮询 ``/api/jobs/{id}`` 取回原始响应。

Jobs live in this process's memory; the API server runs a single process.
Job ids are random 128-bit tokens, so only the requester can read a result.
The wrapped request still passes through every route guard unchanged.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from api.structured_logging import get_logger

log = get_logger(__name__)

ASYNC_REQUEST_HEADER = b"x-lumina-async"
JOB_ID_HEADER = "X-Lumina-Job"
JOBS_PATH_PREFIX = "/api/jobs/"
_ASYNC_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _env_seconds(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass
class _Job:
    job_id: str
    started_at: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    status: int = 500
    headers: list[tuple[bytes, bytes]] = field(default_factory=list)
    body: list[bytes] = field(default_factory=list)
    done: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None


class AsyncJobMiddleware:
    """Pure ASGI middleware; see the module docstring."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        inline_wait: float | None = None,
        poll_wait: float | None = None,
        ttl: float | None = None,
    ) -> None:
        self.app = app
        self.inline_wait = (
            inline_wait
            if inline_wait is not None
            else _env_seconds("LUMINA_ASYNC_INLINE_SECONDS", 10.0)
        )
        self.poll_wait = (
            poll_wait
            if poll_wait is not None
            else _env_seconds("LUMINA_ASYNC_POLL_SECONDS", 10.0)
        )
        # Finished results nobody fetched, and running jobs nobody polls, are
        # dropped after this long. 无人领取的结果、无人轮询的任务在此时长后清理。
        self.ttl = ttl if ttl is not None else _env_seconds("LUMINA_ASYNC_JOB_TTL_SECONDS", 900.0)
        self._jobs: dict[str, _Job] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path: str = scope.get("path", "")
        if path.startswith(JOBS_PATH_PREFIX):
            await self._handle_job_request(scope, send, path[len(JOBS_PATH_PREFIX):])
            return
        if scope.get("method") not in _ASYNC_METHODS or not _wants_async(scope):
            await self.app(scope, receive, send)
            return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break

        self._purge()
        job = _Job(job_id=uuid.uuid4().hex)
        job.task = asyncio.create_task(self._run(job, scope, bytes(body)))
        self._jobs[job.job_id] = job
        if await _wait(job.done, self.inline_wait):
            self._jobs.pop(job.job_id, None)
            await _replay(job, send)
            return
        await _send_pending(send, job)

    async def _run(self, job: _Job, scope: Scope, body: bytes) -> None:
        inner_scope = dict(scope)
        # Drop server extensions such as zero-copy file sending; the response
        # must arrive as ordinary body messages so it can be stored.
        inner_scope["extensions"] = {}
        body_sent = False

        async def inner_receive() -> Message:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await job.cancelled.wait()
            return {"type": "http.disconnect"}

        async def inner_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                job.status = int(message["status"])
                job.headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                job.body.append(bytes(message.get("body", b"")))

        try:
            await self.app(inner_scope, inner_receive, inner_send)
        except asyncio.CancelledError:
            job.status = 499
            job.headers = [(b"content-type", b"application/json")]
            job.body = [b'{"detail":"Request cancelled"}']
        except Exception as exc:
            # The job runs outside the request-context middleware, so log here.
            log.exception(
                "Async API job failed",
                extra={
                    "event": "api_async_job_failed",
                    "job_id": job.job_id,
                    "path": scope.get("path"),
                    "method": scope.get("method"),
                    "error_type": type(exc).__name__,
                },
            )
            job.status = 500
            job.headers = [(b"content-type", b"application/json")]
            job.body = [b'{"detail":"Internal server error"}']
        finally:
            job.finished_at = time.monotonic()
            job.done.set()

    async def _handle_job_request(self, scope: Scope, send: Send, job_id: str) -> None:
        self._purge()
        method = scope.get("method")
        job = self._jobs.get(job_id)
        if job is None:
            await _send_json(send, 404, {"detail": "job_not_found"})
            return
        job.last_seen = time.monotonic()
        if method == "DELETE":
            self._cancel(job)
            await _send_json(send, 200, {"status": "cancelled"})
            return
        if method not in ("GET", "HEAD"):
            await _send_json(send, 405, {"detail": "Method Not Allowed"})
            return
        if await _wait(job.done, self.poll_wait):
            self._jobs.pop(job.job_id, None)
            await _replay(job, send)
            return
        await _send_pending(send, job)

    def _cancel(self, job: _Job) -> None:
        self._jobs.pop(job.job_id, None)
        job.cancelled.set()
        if job.task is not None and not job.task.done():
            job.task.cancel()

    def _purge(self) -> None:
        now = time.monotonic()
        for job in list(self._jobs.values()):
            if job.finished_at is not None:
                if now - job.finished_at > self.ttl:
                    self._jobs.pop(job.job_id, None)
            elif now - job.last_seen > self.ttl:
                self._cancel(job)


def _wants_async(scope: Scope) -> bool:
    for name, value in scope.get("headers", []):
        if name == ASYNC_REQUEST_HEADER:
            return value.strip() in (b"1", b"true")
    return False


async def _wait(event: asyncio.Event, timeout: float) -> bool:
    if event.is_set():
        return True
    try:
        await asyncio.wait_for(asyncio.shield(event.wait()), timeout)
    except asyncio.TimeoutError:
        return False
    return True


async def _replay(job: _Job, send: Send) -> None:
    body = b"".join(job.body)
    headers = [(k, v) for k, v in job.headers if k.lower() != b"content-length"]
    headers.append((b"content-length", str(len(body)).encode()))
    await send({"type": "http.response.start", "status": job.status, "headers": headers})
    await send({"type": "http.response.body", "body": body, "more_body": False})


async def _send_pending(send: Send, job: _Job) -> None:
    await _send_json(
        send,
        202,
        {
            "status": "running",
            "job_id": job.job_id,
            "elapsed_seconds": round(time.monotonic() - job.started_at, 1),
        },
        extra_headers=[(JOB_ID_HEADER.lower().encode(), job.job_id.encode())],
    )


async def _send_json(
    send: Send,
    status: int,
    payload: dict,
    extra_headers: list[tuple[bytes, bytes]] | None = None,
) -> None:
    body = json.dumps(payload).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        (b"cache-control", b"no-store"),
        *(extra_headers or []),
    ]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body, "more_body": False})
