"""Last known stage of the active job in a worker slot."""

from __future__ import annotations

import json
from ctypes import Array, c_char


WORKER_PROGRESS_BYTES = 1024
_worker_progress: Array[c_char] | None = None


def bind_worker_progress(progress: Array[c_char] | None) -> None:
    """Attach the small shared record to the worker process."""
    global _worker_progress
    _worker_progress = progress


def read_worker_progress(progress: Array[c_char]) -> dict[str, str | int]:
    """Read progress even if the worker died while publishing it."""
    try:
        return json.loads(progress.value) if progress.value else {}
    except ValueError:
        return {}


def report_worker_stage(
    phase: str, *, cache_state: str | None = None, row_count: int | None = None,
    piece_label: str | None = None,
) -> None:
    """Publish the last stage before a potentially expensive operation."""
    if _worker_progress is None:
        return
    fields = read_worker_progress(_worker_progress)
    fields["worker_phase"] = phase
    if cache_state is not None:
        fields["worker_cache_state"] = cache_state
    if row_count is not None:
        fields["worker_row_count"] = int(row_count)
    if piece_label is not None:
        fields["worker_piece_label"] = piece_label
    # A child may terminate during a write. Avoid a lock that it could leave held.
    _worker_progress.value = json.dumps(fields).encode("ascii")
