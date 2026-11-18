"""Save-event orchestration and a single, bounded background upload worker."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import sqlite3
import time
from typing import Any

from api.services.resource_activity import local_resource_origin, preserve_origin_license
from api.services.resource_contribution import ContributionError, connection
from api.structured_logging import get_logger
from core.contribution_queue import ContributionQueue
from core.resource_contribution import prepare_contribution
from core.resource_seed import SeedBusyError, seed_lock

log = get_logger(__name__)


def queue_store() -> ContributionQueue:
    from core.single_stage.material_files import MATERIALS_DIR

    # The DB/budget follows the shared resources; grants and jobs additionally
    # belong to the persistent workspace, never a runtime build directory.
    root = Path(MATERIALS_DIR).resolve() / "_sync" / "contributions"
    workspace = os.environ.get("LUMINA_CONTRIBUTION_WORKSPACE", "").strip()
    if not workspace:
        settings = os.environ.get("LUMINA_SETTINGS_PATH", "").strip()
        workspace = str(Path(settings).resolve().parent if settings else Path(MATERIALS_DIR).resolve())
    return ContributionQueue(root / "queue.sqlite3", str(Path(workspace).resolve()))


def owns_calibration(kind: str, key: str) -> bool:
    """A prior name alone cannot establish ownership after import or replacement."""
    try:
        queue = queue_store()
        if not queue.path.exists():
            return False
        server = connection.source()
        grant = queue.grant(server)
        return bool(grant and grant["enabled"] and (not connection.subject or connection.subject == grant["account"])
                    and not local_resource_origin(kind, key) and
                    queue.owns_snapshot(server, grant["account"], prepare_contribution(kind, key)))
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error):
        return False


def capture_calibration(kind: str, key: str, *, new_calibration: bool = True) -> dict[str, Any] | None:
    """Freeze only a just-saved calibration. No account or other network calls."""
    try:
        queue = queue_store()
        if not queue.path.exists():
            return None
        server = connection.source()
        grant = queue.grant(server)
        if not grant or not grant["enabled"]:
            return None
        if connection.subject and connection.subject != grant["account"]:
            queue.pause(server)
            return None
        prepared = prepare_contribution(kind, key)
        origin = local_resource_origin(kind, key)
        prepared.display = preserve_origin_license(prepared.display, origin)
        display = dict(prepared.display)
        # Remeasurements must prove ownership against the pre-save bytes.
        ready = not origin and new_calibration
        if ready:
            display["attribution"] = {"relationship": "original"}
        if kind == "materials":
            ready = ready and bool(display.get("brand") and display.get("material_type"))
        else:
            slots = display.get("filaments", [])
            # Extraction records a whole-board brand/material. A mixed-board
            # calibration needs explicit per-channel details before publication.
            ready = ready and bool(slots) and all(
                row.get("brand") and row.get("material_type") and row.get("color_name") for row in slots)
        job_id = queue.add(server, grant["account"], prepared, display, origin, ready=bool(ready),
                           reason="" if ready else "details")
        return {"id": job_id, "state": "queued" if ready else "needs_review"} if job_id else None
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error) as exc:
        log.warning("Calibration saved; contribution could not be queued", extra={
            "event": "contribution_snapshot_failed", "kind": kind,
            "error_type": type(exc).__name__,
            "error_message": "Manage pending items in My submissions, then contribute the saved resource manually.",
        })
        return {"state": "needs_attention", "reason": "snapshot_failed"}


def process_one() -> None:
    queue = queue_store()
    if not queue.path.exists():
        return
    server = connection.source()
    if not any(row["state"] == "sending" or (row["state"] == "queued" and row["next_attempt"] <= time.time())
               for row in queue.items(server)):
        return
    try:
        # Same lock across instances, including while a request is in flight.
        with seed_lock(queue.path.parent / "worker"):
            with connection.lock:
                status = connection.status()
                if status.get("state") != "connected":
                    return
                account = status["subject"]
                if not status.get("email_verified"):
                    return
                job_id = queue.claim(server, account)
                if not job_id:
                    return
                try:
                    _, prepared, _ = queue.snapshot(server, job_id)
                    receipt = connection.submit(prepared, prepared.display, expected_subject=account)
                    queue.finish(job_id, receipt=receipt)
                except ContributionError as exc:
                    queue.finish(job_id, reason="connection" if exc.status in (401, 403) else "upload",
                                 retryable=exc.status in {408, 425, 429, 500, 502, 503, 504})
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    queue.finish(job_id, reason="snapshot")
                    log.warning("Contribution needs review before retry", extra={
                        "event": "contribution_upload_failed", "error_type": type(exc).__name__,
                        "error_message": "The saved snapshot could not be processed; review My submissions.",
                    })
    except SeedBusyError:
        return


async def contribution_worker() -> None:
    while True:
        operation = asyncio.create_task(asyncio.to_thread(process_one))
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            # Let an already-sent request store its receipt before shutdown.
            await asyncio.gather(operation, return_exceptions=True)
            raise
        except (ContributionError, OSError, ValueError, sqlite3.Error) as exc:
            log.debug("Contribution processing postponed", extra={
                "event": "contribution_worker_deferred", "error_type": type(exc).__name__,
            })
        await asyncio.sleep(30)
