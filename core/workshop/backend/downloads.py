"""Source preferences and byte progress for host-managed downloads."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, TypedDict
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import Field

from ..constants import MAX_BACKEND_MODEL_BYTES
from ..errors import WorkshopBackendError
from ..models import StrictFrozenModel

if TYPE_CHECKING:
    from .tooling import CancelToken


_SOURCE_ID_PATTERN = r"^[a-z0-9.:][a-z0-9.:-]{0,252}$"
SourceId = Annotated[str, Field(pattern=_SOURCE_ID_PATTERN)]
_SAMPLE_INTERVAL_SECONDS = 0.25
_SAMPLE_EXPIRY_SECONDS = 4.0
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
    try:
        host = httpx.URL(url).raw_host.decode("ascii").lower().rstrip(".")
    except (httpx.InvalidURL, UnicodeError):
        return ""
    if re.fullmatch(_SOURCE_ID_PATTERN, host) is None:
        return ""
    return _SOURCE_ALIASES.get(host, host)


def source_options(urls: Iterable[str]) -> list[str]:
    return sorted({source_id(url) for url in urls} - {""})


def ordered_sources(
    primary: str,
    alternatives: Iterable[str],
    preferred: str,
    *,
    auto_source: str | None = None,
) -> tuple[str, ...]:
    """Keep the declared order within a source and preserve the primary fallback."""

    urls = tuple(dict.fromkeys((primary, *alternatives)))
    if preferred == "original":
        return (primary,)
    selected = auto_source if preferred == "auto" else preferred
    return tuple(sorted(urls, key=lambda url: source_id(url) != selected)) if selected else urls


class DownloadSourceRoute(TypedDict):
    original: str
    sources: list[str]
    count: int
    bytes: int
    unknown_size_count: int


def summarize_source_routes(
    routes: Iterable[tuple[str, tuple[str, ...], int | None]],
) -> list[DownloadSourceRoute]:
    groups: dict[tuple[str, tuple[str, ...]], DownloadSourceRoute] = {}
    for url, candidates, size in routes:
        original = source_id(url)
        sources = tuple(dict.fromkeys(source_id(candidate) for candidate in candidates if candidate))
        item = groups.setdefault(
            (original, sources),
            {"original": original, "sources": list(sources), "count": 0, "bytes": 0, "unknown_size_count": 0},
        )
        item["count"] += 1
        item["bytes"] += size or 0
        if size is None:
            item["unknown_size_count"] += 1
    return list(groups.values())


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
        self._rate_source: str | None = None
        self._sample_at = 0.0
        self._sample_bytes = 0
        self._rate: float | None = None

    def attempt(self, index: int, name: str, url: str) -> Callable[[int, int | None], None]:
        self._sizes[index] = self._declared_sizes[index]
        last_report_at = time.monotonic()
        source = source_id(url)
        if source != self._rate_source or last_report_at - self._sample_at > _SAMPLE_EXPIRY_SECONDS:
            self._rate_source = source
            self._sample_at = last_report_at
            self._sample_bytes = 0
            self._rate = None
        last_received = 0
        self._report(index, name, source, 0)

        def update(received: int, total: int | None) -> None:
            nonlocal last_report_at, last_received
            if total is not None and self._declared_sizes[index] is None:
                self._sizes[index] = total
            now = time.monotonic()
            self._sample_bytes += max(0, received - last_received)
            last_received = received
            elapsed = now - self._sample_at
            if elapsed >= _SAMPLE_INTERVAL_SECONDS and self._sample_bytes:
                sample = self._sample_bytes / elapsed
                self._rate = (
                    sample if self._rate is None or elapsed > _SAMPLE_EXPIRY_SECONDS
                    else (self._rate + sample) / 2
                )
                self._sample_at = now
                self._sample_bytes = 0
            if now - last_report_at < _SAMPLE_INTERVAL_SECONDS and received not in (0, total):
                return
            last_report_at = now
            self._report(index, name, source, received)

        return update

    def _report(self, index: int, name: str, source: str, received: int) -> None:
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
            source=source,
            file_index=index + 1,
            file_count=len(self._sizes),
            file_received_bytes=received,
            file_total_bytes=file_size,
            received_bytes=received_total,
            total_bytes=total,
            bytes_per_second=self._rate,
            eta_seconds=(
                math.ceil(max(0, remaining) / self._rate)
                if self._rate and remaining is not None else None
            ),
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
                        host = source_id(url) or "The download source"
                        raise WorkshopBackendError(
                            "download-failed", f"{host} returned HTTP {response.status_code}."
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
                        for chunk in response.iter_bytes():
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
    except OSError as exc:
        if cancel is not None:
            cancel.raise_if_cancelled()
        raise WorkshopBackendError("download-failed", "The download could not be written to local storage.") from exc
    except (httpx.HTTPError, httpx.InvalidURL, ValueError) as exc:
        if cancel is not None:
            cancel.raise_if_cancelled()
        host = source_id(url) or "the download source"
        raise WorkshopBackendError("download-failed", f"Could not download the file from {host}.") from exc
