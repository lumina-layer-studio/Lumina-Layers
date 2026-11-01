"""Bounded failover for public material and LUT registry reads."""
from __future__ import annotations

import os
from time import sleep
from typing import Any, Callable, Sequence, TypeVar
from urllib.parse import urljoin, urlsplit

import httpx

_Result = TypeVar("_Result")


def _origin(url: str) -> tuple[str, str | None, int | None]:
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def _valid_base(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        _origin(url)
        return bool(parsed.scheme in {"https", "http"} and parsed.hostname
                    and not parsed.username and not parsed.password
                    and not parsed.query and not parsed.fragment
                    and not any(part in {".", ".."} for part in parsed.path.split("/"))
                    and not any(char in url for char in ("%", "\\", "\r", "\n")))
    except ValueError:
        return False


def fallback_base(primary: str, family: str) -> str | None:
    """Resolve an explicit, distinct fallback. / 解析显式配置的独立备用地址。

    Args:
        primary: Primary registry URL. / 主库地址。
        family: MATERIAL or LUT. / 材料库或 LUT 库。

    Returns:
        Valid fallback URL, or None. / 有效备用地址或 None。
    """
    value = os.environ.get(f"LUMINA_{family}_REGISTRY_FALLBACK_URL")
    if value is None and family == "LUT":
        material_primary = os.environ.get("LUMINA_MATERIAL_REGISTRY_URL", "").strip().rstrip("/")
        if primary.rstrip("/") == material_primary:
            value = os.environ.get("LUMINA_MATERIAL_REGISTRY_FALLBACK_URL")
    fallback = (value or "").strip().rstrip("/")
    # A public fallback must not downgrade an HTTPS primary to remote HTTP.
    # Local HTTP endpoints remain usable as development primaries, but a
    # remote backup is always required to use TLS.
    if (not _valid_base(primary) or not _valid_base(fallback)
            or urlsplit(fallback).scheme != "https"):
        return None
    if _origin(primary) == _origin(fallback):
        return None
    return fallback


def map_package_url(url: str, source: str, target: str) -> str:
    """Map only safe same-source package paths. / 仅映射安全的同源包路径。

    Args:
        url: Catalog package URL. / 目录包地址。
        source: Trusted source base. / 可信源地址。
        target: Configured target base. / 配置的目标地址。

    Returns:
        Equivalent package URL. / 对应包地址。

    Raises:
        ValueError: Unsafe or unrelated URL. / 地址不安全或不属于可信源。
    """
    if not isinstance(url, str) or not url:
        raise ValueError("Registry package URL must be a nonempty string")
    resolved = urljoin(source.rstrip("/") + "/", url)
    parsed = urlsplit(resolved)
    prefix = urlsplit(source).path.rstrip("/") + "/"
    if (not _valid_base(resolved) or _origin(resolved) != _origin(source)
            or not parsed.path.startswith(prefix)):
        raise ValueError("Registry package URL is outside the trusted package path")
    relative = parsed.path[len(prefix):]
    if not relative.startswith(("packages/", "luts/packages/")):
        raise ValueError("Registry package URL is outside the trusted package path")
    return target.rstrip("/") + "/" + relative


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 429} or 500 <= exc.response.status_code <= 599
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout,
                        httpx.ReadError, httpx.RemoteProtocolError)):
        return True
    return exc.__cause__ is not None and _retryable(exc.__cause__)


def _public_client(client: Any, headers: dict[str, str], channels: Sequence[str]) -> bool:
    # Caller-supplied validators are origin-specific; do not forward or mutate them.
    sensitive = {
        "authorization", "cookie", "proxy-authorization",
        "if-none-match", "if-modified-since",
    }
    combined = {**dict(getattr(client, "headers", {})), **headers}
    return (bool(channels) and set(channels) <= {"official", "community", "public"}
            and not any(key.lower() in sensitive and value for key, value in combined.items())
            and not getattr(client, "auth", None) and not getattr(client, "cookies", None))


def read_with_fallback(*, client: Any, primary: str, fallback: str | None,
                       headers: dict[str, str], channels: Sequence[str],
                       action: Callable[[str], _Result],
                       retry_primary: bool = False) -> _Result:
    """Recover a transient read with at most one backup or same-origin retry.

    Args:
        client: HTTP client. / HTTP 客户端。
        primary: Primary base URL. / 主地址。
        fallback: Validated fallback base. / 已校验备用地址。
        headers: Request headers. / 请求头。
        channels: Requested channels. / 请求频道。
        action: Complete read operation, including stream consumption. / 包含流读取的完整操作。
        retry_primary: Allow one same-origin catalog retry when no public backup is usable.

    Returns:
        Successful read result. / 成功读取的结果。
    """
    allowed = bool(fallback) and _public_client(client, headers, channels)
    try:
        return action(primary)
    except Exception as exc:
        if not _retryable(exc):
            raise
        if allowed and _public_client(client, headers, channels):
            return action(fallback)
        if not retry_primary:
            raise
        # A rate limit or explicit Retry-After belongs to the caller's next
        # refresh, not an immediate retry. Keep the total at two requests.
        if isinstance(exc, httpx.HTTPStatusError) and (
            exc.response.status_code == 429 or "retry-after" in exc.response.headers
        ):
            raise
        sleep(0.25)
        return action(primary)


def fetch_catalog(*, client: Any, primary: str, family: str, suffix: str,
                  channels: Sequence[str], headers: dict[str, str], params: Any,
                  etag: str | None = None) -> Any:
    """Read a catalog with stable primary package URLs. / 读取目录并保留稳定的主库包地址。

    Args:
        client: HTTP client. / HTTP 客户端。
        primary: Primary base URL. / 主地址。
        family: MATERIAL or LUT. / 库类型。
        suffix: Catalog route. / 目录路径。
        channels: Requested channels. / 请求频道。
        headers: Request headers. / 请求头。
        params: Query parameters. / 查询参数。
        etag: Primary cache validator. / 主库缓存校验值。

    Returns:
        HTTP response with normalized fallback package URLs. / 包地址规范化后的响应。
    """
    def request(base: str) -> Any:
        request_headers = dict(headers)
        if etag is not None and base == primary:
            request_headers["If-None-Match"] = etag
        response = client.get(base + suffix, headers=request_headers, params=params,
                              follow_redirects=False)
        if not 300 <= response.status_code < 400:
            response.raise_for_status()
        if base != primary:
            if 300 <= response.status_code < 400:
                raise ValueError("Backup registry redirects and unsolicited 304 are not allowed")
            payload = response.json()
            groups = ([payload] if isinstance(payload, list) else
                      [payload.get(key, []) for key in ("materials", "packages", "items", "luts")]
                      if isinstance(payload, dict) else [])
            for entries in groups:
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict) and entry.get("package_url"):
                            entry["package_url"] = map_package_url(entry["package_url"], base, primary)
            # Source-specific validators must never validate another origin's catalog.
            clean_headers = {key: value for key, value in response.headers.items()
                             if key.lower() not in {"etag", "content-length", "content-encoding"}}
            return httpx.Response(200, json=payload, headers=clean_headers, request=response.request)
        return response
    return read_with_fallback(client=client, primary=primary,
                              fallback=fallback_base(primary, family), headers=headers,
                              channels=channels, action=request, retry_primary=True)
