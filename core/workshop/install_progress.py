"""Live progress for downloading and staging an extension archive."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Literal

from .backend.downloads import DownloadBatch, DownloadProgress


InstallPhase = Literal["resolving", "downloading", "verifying", "installing"]


@dataclass(frozen=True, slots=True)
class ArchiveInstallProgress:
    phase: InstallPhase
    download: DownloadProgress | None = None


class ArchiveInstallTracker:
    def __init__(self) -> None:
        self.snapshot = ArchiveInstallProgress("resolving")

    def stage(self, phase: InstallPhase) -> None:
        transfer = self.snapshot.download
        if transfer is not None:
            transfer = replace(transfer, bytes_per_second=None, eta_seconds=None)
        self.snapshot = ArchiveInstallProgress(phase, transfer)

    def download(self, name: str, url: str, size: int | None) -> Callable[[int, int | None], None]:
        def publish(progress: DownloadProgress) -> None:
            self.snapshot = ArchiveInstallProgress("downloading", progress)

        return DownloadBatch((size,), publish).attempt(0, name, url)
