"""Source preferences and byte progress for host-managed downloads."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import Field

from ..constants import MAX_BACKEND_MODEL_BYTES
from ..errors import WorkshopBackendError
from ..models import StrictFrozenModel

if TYPE_CHECKING:
    from .tooling import CancelToken


SourceId = Annotated[str, Field(pattern=r"^[a-z0-9.:][a-z0-9.:-]{0,252}$")]
_SOURCE_ALIASES = {
    "www.modelscope.cn": "modelscope.cn",
    "modelscope.ai": "modelscope.cn",
    "www.modelscope.ai": "modelscope.cn",
    "www.huggingface.co": "huggingface.co",
    "pypi.org": "files.pythonhosted.org",
}


class DownloadPreferences(StrictFrozenModel):
    """Preferred source for each download category in one preparation."""

    python: SourceId = "auto"
    wheels: SourceId = "auto"
    models: SourceId = "auto"
    artifacts: SourceId = "auto"


def source_id(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return _SOURCE_ALIASES.get(host, host)


def source_options(urls: Iterable[str]) -> list[str]:
    return sorted({source_id(url) for url in urls if source_id(url)})


def ordered_sources(primary: str, alternatives: Iterable[str], preferred: str) -> tuple[str, ...]:
    """Keep the declared order within a source and preserve the primary fallback."""

    urls = tuple(dict.fromkeys((primary, *alternatives)))
    if preferred == "original":
        return (primary,)
    if preferred == "auto":
        return urls
    return tuple(sorted(urls, key=lambda url: source_id(url) != preferred))


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    file_name: str
    source: str
    file_index: int
    file_count: int
    file_received_bytes: int
    file_total_bytes: int | None
    received_bytes: int
    total_bytes: int | None
    bytes_per_second: float | None
    eta_seconds: int | None


class DownloadBatch:
    """Report accepted bytes within a phase and sample active transfer speed."""

    def __init__(
        self,
        sizes: Iterable[int | None],
        publish: Callable[[DownloadProgress], None],
    ) -> None:
        self._declared_sizes = tuple(sizes)
        self._sizes = list(self._declared_sizes)
        self._publish = publish
        self._completed_bytes = 0

    def attempt(self, index: int, name: str, url: str) -> Callable[[int, int | None], None]:
        self._sizes[index] = self._declared_sizes[index]
        last_at = time.monotonic()
        last_received = 0
        rate: float | None = None
        self._report(index, name, url, 0, None)

        def update(received: int, total: int | None) -> None:
            nonlocal last_at, last_received, rate
            if total is not None and self._declared_sizes[index] is None:
                self._sizes[index] = total
            now = time.monotonic()
            elapsed = now - last_at
            if elapsed < 0.25 and received != total and received != 0:
                return
            if elapsed >= 0.2 and received > last_received:
                sample = (received - last_received) / elapsed
                rate = sample if rate is None else (rate + sample) / 2
                last_at, last_received = now, received
            self._report(index, name, url, received, rate)

        return update

    def _report(self, index: int, name: str, url: str, received: int, rate: float | None) -> None:
        total = (
            sum(size for size in self._sizes if size is not None)
            if None not in self._sizes
            else None
        )
        received_total = self._completed_bytes + received
        file_size = self._sizes[index]
        remaining = total - received_total if total is not None else (
            file_size - received if file_size is not None else None
        )
        self._publish(DownloadProgress(
            file_name=name,
            source=source_id(url),
            file_index=index + 1,
            file_count=len(self._sizes),
            file_received_bytes=received,
            file_total_bytes=file_size,
            received_bytes=received_total,
            total_bytes=total,
            bytes_per_second=rate,
            eta_seconds=round(max(0, remaining) / rate) if rate and remaining is not None else None,
        ))

    def finish(self, index: int, size: int) -> None:
        self._sizes[index] = size
        self._completed_bytes += size


def _download_url(url: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https" and bool(parsed.hostname)
        and parsed.username is None and parsed.password is None
    )


def download_https(
    url: str,
    destination: Path,
    *,
    cancel: CancelToken | None,
    progress: Callable[[int, int | None], None],
    size: int | None = None,
    timeout: httpx.Timeout | None = None,
) -> None:
    """Stream a bounded artifact to a new file and report the actual byte count."""

    try:
        with httpx.Client(timeout=timeout or httpx.Timeout(60, connect=15), follow_redirects=False) as client:
            for _ in range(11):
                if cancel is not None:
                    cancel.raise_if_cancelled()
                if not _download_url(url):
                    raise WorkshopBackendError("download-failed", "Downloads must stay on HTTPS.")
                with client.stream(
                    "GET", url,
                    headers={"User-Agent": "Lumina-Studio-Workshop/1", "Accept-Encoding": "identity"},
                ) as response:
                    if response.is_redirect and "Location" in response.headers:
                        url = urljoin(url, response.headers["Location"])
                        continue
                    if response.status_code != 200:
                        raise WorkshopBackendError(
                            "download-failed", f"The download server returned HTTP {response.status_code}."
                        )
                    length = response.headers.get("Content-Length", "")
                    total = size
                    if total is None and length.isdecimal() and not response.headers.get("Content-Encoding"):
                        total = int(length)
                    limit = size if size is not None else MAX_BACKEND_MODEL_BYTES
                    if total is not None and total > limit:
                        raise WorkshopBackendError("download-verification-failed", "The download is too large.")
                    progress(0, total)
                    received = 0
                    with destination.open("xb") as sink:
                        for chunk in response.iter_bytes(1024 * 1024):
                            if cancel is not None:
                                cancel.raise_if_cancelled()
                            received += len(chunk)
                            if received > limit:
                                raise WorkshopBackendError("download-verification-failed", "The download is too large.")
                            sink.write(chunk)
                            progress(received, total)
                    progress(received, received)
                    return
            raise WorkshopBackendError("download-failed", "The download server redirected too many times.")
    except (httpx.HTTPError, httpx.InvalidURL, OSError, ValueError) as exc:
        raise WorkshopBackendError("download-failed", "The file could not be downloaded.") from exc
