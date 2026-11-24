"""Track only active archive requests for the Workshop manager."""

from collections.abc import Iterator
from threading import Lock
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException

from core.workshop.install_progress import ArchiveInstallProgress, ArchiveInstallTracker


_active: dict[UUID, ArchiveInstallTracker] = {}
_lock = Lock()


def _track_install(progress_id: UUID | None = None) -> Iterator[ArchiveInstallTracker | None]:
    if progress_id is None:
        yield None
        return
    tracker = ArchiveInstallTracker()
    with _lock:
        if progress_id in _active:
            raise HTTPException(status_code=409, detail="Workshop install is already in progress.")
        _active[progress_id] = tracker
    try:
        yield tracker
    finally:
        with _lock:
            _active.pop(progress_id, None)


TrackArchiveInstall = Annotated[ArchiveInstallTracker | None, Depends(_track_install)]


def get_archive_progress(progress_id: UUID) -> ArchiveInstallProgress | None:
    with _lock:
        tracker = _active.get(progress_id)
        return tracker.snapshot if tracker is not None else None
