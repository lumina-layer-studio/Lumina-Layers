"""Read Workshop mirror assets without forwarding credentials on redirects."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Self
from urllib.parse import quote

import httpx

from core.public_resources import workshop_mirror_token, workshop_mirror_url


_GITHUB_DOMAINS = ("github.com", "githubusercontent.com", "github.io")
_MIRROR_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class WorkshopMirrorUnavailable(Exception):
    """An unavailable mirror response can be retried against the upstream."""


@dataclass(frozen=True, slots=True)
class WorkshopMirror:
    base_url: str
    token: str = field(repr=False)

    @classmethod
    def from_environment(cls) -> Self | None:
        try:
            url = httpx.URL(workshop_mirror_url())
        except httpx.InvalidURL:
            return None
        host = url.host.rstrip(".")
        if (
            url.scheme != "https" or not host or url.userinfo or url.query or url.fragment
            or any(host == domain or host.endswith(f".{domain}") for domain in _GITHUB_DOMAINS)
        ):
            return None
        token = workshop_mirror_token()
        if token and (not token.isascii() or not token.isprintable() or " " in token):
            return None
        return cls(str(url).rstrip("/"), token)

    @contextmanager
    def stream(self, *segments: str, accept: str) -> Iterator[httpx.Response]:
        relative_path = "/".join(quote(segment, safe="") for segment in segments)
        headers = {"Accept": accept, "User-Agent": "Lumina-Studio-Workshop/1"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            with httpx.Client(timeout=_MIRROR_TIMEOUT, follow_redirects=False) as client:
                with client.stream("GET", f"{self.base_url}/{relative_path}", headers=headers) as response:
                    if response.status_code != 200:
                        raise WorkshopMirrorUnavailable("Workshop mirror did not return 200")
                    yield response
        except httpx.RequestError as exc:
            raise WorkshopMirrorUnavailable("Workshop mirror request failed") from exc
