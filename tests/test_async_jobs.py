"""Tests for the long-request -> pollable job middleware."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse

from api.async_jobs import AsyncJobMiddleware

ASYNC = {"X-Lumina-Async": "1"}


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AsyncJobMiddleware, inline_wait=0.2, poll_wait=0.2, ttl=60)

    @app.post("/api/fast")
    async def fast(payload: dict):
        return {"echo": payload}

    @app.post("/api/slow")
    async def slow(payload: dict):
        await asyncio.sleep(0.7)
        return JSONResponse({"echo": payload}, status_code=201, headers={"X-Extra": "yes"})

    @app.post("/api/slow-error")
    async def slow_error():
        await asyncio.sleep(0.5)
        return JSONResponse({"detail": "nope"}, status_code=422)

    @app.post("/api/crash")
    async def crash():
        await asyncio.sleep(0.5)
        raise RuntimeError("boom")

    @app.post("/api/upload")
    async def upload(image: UploadFile = File(...)):
        await asyncio.sleep(0.5)
        return {"size": len(await image.read())}

    @app.get("/api/plain")
    async def plain():
        return {"ok": True}

    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _poll(client: httpx.AsyncClient, job_id: str) -> httpx.Response:
    for _ in range(50):
        response = await client.get(f"/api/jobs/{job_id}")
        if response.status_code != 202:
            return response
    raise AssertionError("job never finished")


@pytest.mark.anyio
async def test_quick_request_is_answered_inline():
    async with _client(_app()) as client:
        response = await client.post("/api/fast", json={"a": 1}, headers=ASYNC)
    assert response.status_code == 200
    assert response.json() == {"echo": {"a": 1}}


@pytest.mark.anyio
async def test_requests_without_opt_in_are_untouched():
    async with _client(_app()) as client:
        slow = await client.post("/api/slow", json={"a": 1})
        plain = await client.get("/api/plain", headers=ASYNC)
    assert slow.status_code == 201
    assert plain.json() == {"ok": True}


@pytest.mark.anyio
async def test_slow_request_becomes_a_job_and_replays_the_response():
    async with _client(_app()) as client:
        first = await client.post("/api/slow", json={"a": 2}, headers=ASYNC)
        assert first.status_code == 202
        job_id = first.headers["x-lumina-job"]
        assert first.json()["job_id"] == job_id
        final = await _poll(client, job_id)
        assert final.status_code == 201
        assert final.headers["x-extra"] == "yes"
        assert final.json() == {"echo": {"a": 2}}
        # A delivered result is consumed.
        again = await client.get(f"/api/jobs/{job_id}")
        assert again.status_code == 404


@pytest.mark.anyio
async def test_error_status_is_replayed():
    async with _client(_app()) as client:
        first = await client.post("/api/slow-error", headers=ASYNC)
        final = await _poll(client, first.json()["job_id"])
    assert final.status_code == 422
    assert final.json() == {"detail": "nope"}


@pytest.mark.anyio
async def test_unhandled_exception_in_a_job_becomes_a_500():
    async with _client(_app()) as client:
        first = await client.post("/api/crash", headers=ASYNC)
        final = await _poll(client, first.json()["job_id"])
    assert final.status_code == 500
    assert final.json() == {"detail": "Internal server error"}


@pytest.mark.anyio
async def test_multipart_upload_body_reaches_the_handler():
    async with _client(_app()) as client:
        first = await client.post(
            "/api/upload", files={"image": ("a.png", b"x" * 300_000)}, headers=ASYNC
        )
        final = await _poll(client, first.json()["job_id"])
    assert final.json() == {"size": 300_000}


@pytest.mark.anyio
async def test_cancel_and_unknown_jobs():
    async with _client(_app()) as client:
        first = await client.post("/api/slow", json={}, headers=ASYNC)
        job_id = first.json()["job_id"]
        cancelled = await client.delete(f"/api/jobs/{job_id}")
        assert cancelled.status_code == 200
        assert (await client.get(f"/api/jobs/{job_id}")).status_code == 404
        assert (await client.get("/api/jobs/does-not-exist")).status_code == 404


def test_real_app_registers_the_middleware():
    from api.app import create_app

    app = create_app()
    names = [m.cls.__name__ for m in app.user_middleware]
    # Inside CORS so 202/job responses still get CORS headers.
    assert names.index("CORSMiddleware") < names.index("AsyncJobMiddleware")
