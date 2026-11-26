"""Bounded GitHub Release downloads for Creative Workshop modules.
创意工坊模块的有界 GitHub Release 下载边界。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, closing, contextmanager
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlsplit

import httpx

from config import TEMP_DIR

from .constants import MAX_PACKAGE_BYTES
from .errors import WorkshopPackageError, WorkshopReleaseError
from .install_progress import ArchiveInstallTracker
from .mirror import WorkshopMirror, WorkshopMirrorUnavailable
from .models import MODULE_ID_PATTERN, RegistryVersion, validate_semver
from .package_validator import inspect_workshop_package


_MAX_GITHUB_RELEASE_METADATA_BYTES = 1024 * 1024
_MAX_REDIRECTS = 5
_GITHUB_REPOSITORY_PART = re.compile(r"^[A-Za-z0-9_.-]+$")
_GITHUB_ASSET_NAME = re.compile(
    r"^(?P<module_id>[a-z0-9]+(?:[.-][a-z0-9]+"
    r"(?:[a-z0-9-]*[a-z0-9])?)*)-"
    r"(?P<version>[0-9A-Za-z.+-]+)\.lumina-workshop$"
)
_TRUSTED_DOWNLOAD_HOSTS = frozenset(
    {
        "github.com",
        "api.github.com",
        "objects.githubusercontent.com",
        "github-releases.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)

PackageDownloader = Callable[[str, int | None, str | None], Path]
JsonFetcher = Callable[[str], dict[str, object]]


def _http_timeout() -> httpx.Timeout:
    return httpx.Timeout(
        connect=15.0,
        read=60.0,
        write=60.0,
        pool=15.0,
    )


def _new_http_client() -> httpx.Client:
    return httpx.Client(
        timeout=_http_timeout(),
        follow_redirects=False,
    )


def _validated_remote_url(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _TRUSTED_DOWNLOAD_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.fragment
    ):
        raise WorkshopReleaseError(
            "remote URL left the trusted GitHub release boundary"
        )
    return url


def _content_length_within_limit(
    response: httpx.Response,
    maximum: int,
) -> None:
    raw_length = response.headers.get("Content-Length")
    if raw_length is None:
        return
    try:
        declared = int(raw_length)
    except ValueError as exc:
        raise WorkshopReleaseError(
            "remote response has invalid Content-Length"
        ) from exc
    if declared < 0 or declared > maximum:
        raise WorkshopReleaseError(
            "remote response exceeds the size limit"
        )


def _request_with_redirects(
    client: httpx.Client,
    url: str,
    *,
    accept: str,
) -> httpx.Response:
    current = _validated_remote_url(url)
    for _redirect in range(_MAX_REDIRECTS + 1):
        if (
            accept == "application/vnd.github+json"
            and urlsplit(current).netloc != "api.github.com"
        ):
            raise WorkshopReleaseError(
                "GitHub API metadata must remain inside api.github.com"
            )
        request = client.build_request(
            "GET",
            current,
            headers={
                "Accept": accept,
                "User-Agent": "Lumina-Studio-Workshop/1",
            },
        )
        response = client.send(request, stream=True)
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("Location")
        response.close()
        if not location:
            raise WorkshopReleaseError(
                "remote redirect did not include a destination"
            )
        current = _validated_remote_url(urljoin(current, location))
    raise WorkshopReleaseError("remote response exceeded redirect limit")


def fetch_github_json(url: str) -> dict[str, object]:
    """Fetch bounded JSON through the HTTPS GitHub API only.

    仅通过 HTTPS GitHub API 获取有大小限制的 JSON 文档。
    """

    chunks: list[bytes] = []
    received = 0
    with _new_http_client() as client:
        response = _request_with_redirects(
            client,
            url,
            accept="application/vnd.github+json",
        )
        try:
            if response.status_code != 200:
                raise WorkshopReleaseError(
                    "GitHub release request failed with status "
                    f"{response.status_code}"
                )
            _content_length_within_limit(
                response,
                _MAX_GITHUB_RELEASE_METADATA_BYTES,
            )
            for chunk in response.iter_bytes():
                received += len(chunk)
                if received > _MAX_GITHUB_RELEASE_METADATA_BYTES:
                    raise WorkshopReleaseError(
                        "GitHub release metadata exceeds the size limit"
                    )
                chunks.append(chunk)
        finally:
            response.close()
    try:
        decoded = b"".join(chunks).decode("utf-8", errors="strict")
        payload = json.loads(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkshopReleaseError(
            "GitHub release metadata is not valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise WorkshopReleaseError(
            "GitHub release metadata root must be an object"
        )
    return payload


def stream_package_download(
    url: str,
    expected_bytes: int | None = None,
    expected_sha256: str | None = None,
    *,
    progress: ArchiveInstallTracker | None = None,
) -> Path:
    """Stream one package into a bounded temporary file.

    将一个模块包流式写入有界临时文件。
    """

    report = None
    if progress is not None:
        report = progress.download(unquote(urlsplit(url).path.rsplit("/", 1)[-1]), url, expected_bytes)
    return _save_package(_stream_github_package(url), expected_bytes, expected_sha256, report)


@contextmanager
def _stream_github_package(url: str) -> Iterator[httpx.Response]:
    with _new_http_client() as client, closing(_request_with_redirects(
        client, url, accept="application/octet-stream",
    )) as response:
        yield response


def _save_package(
    source: AbstractContextManager[httpx.Response],
    expected_bytes: int | None,
    expected_sha256: str | None,
    report: Callable[[int, int | None], None] | None = None,
) -> Path:
    Path(TEMP_DIR).mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(
        suffix=".lumina-workshop",
        prefix="workshop-download-",
        dir=TEMP_DIR,
    )
    path = Path(raw_path)
    received = 0
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as output, source as response:
            if response.status_code != 200:
                raise WorkshopReleaseError(
                    f"package download failed with status {response.status_code}"
                )
            _content_length_within_limit(response, MAX_PACKAGE_BYTES)
            if report is not None:
                report(0, expected_bytes)
            for chunk in response.iter_bytes():
                received += len(chunk)
                if received > MAX_PACKAGE_BYTES:
                    raise WorkshopReleaseError("package download exceeds the size limit")
                digest.update(chunk)
                output.write(chunk)
                if report is not None:
                    report(received, expected_bytes)
            output.flush()
            os.fsync(output.fileno())
        if expected_bytes is not None and received != expected_bytes:
            raise WorkshopReleaseError(
                "downloaded package size does not match release metadata"
            )
        if (
            expected_sha256 is not None
            and not hmac.compare_digest(
                digest.hexdigest(),
                expected_sha256,
            )
        ):
            raise WorkshopReleaseError(
                "downloaded package digest does not match release metadata"
            )
        if report is not None:
            report(received, received)
        return path
    except (OSError, httpx.HTTPError, WorkshopReleaseError, WorkshopMirrorUnavailable):
        _remove_rejected_download(path)
        raise


def _inspect_remote_package(
    path: Path,
    *,
    expected_module_id: str,
    expected_version: str,
    expected_manifest_sha256: str | None = None,
) -> None:
    try:
        inspected = inspect_workshop_package(path)
    except WorkshopPackageError as exc:
        raise WorkshopReleaseError(
            "remote package failed Workshop validation"
        ) from exc
    if (
        inspected.manifest.id != expected_module_id
        or inspected.manifest.version != expected_version
    ):
        raise WorkshopReleaseError(
            "remote package identity does not match the selected release"
        )
    if (
        expected_manifest_sha256 is not None
        and not hmac.compare_digest(
            inspected.manifest_sha256,
            expected_manifest_sha256,
        )
    ):
        raise WorkshopReleaseError(
            "package manifest digest does not match Registry metadata"
        )


def _remove_rejected_download(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _download_preferred_package(
    candidate: RegistryVersion, module_id: str, progress: ArchiveInstallTracker | None,
) -> Path:
    mirror = WorkshopMirror.from_environment()
    if mirror is not None:
        try:
            return _save_package(
                mirror.stream(
                    "packages", module_id, candidate.version, candidate.asset_name,
                    accept="application/octet-stream",
                ),
                candidate.asset_bytes,
                candidate.sha256,
                progress.download(candidate.asset_name, mirror.base_url, candidate.asset_bytes) if progress else None,
            )
        except WorkshopMirrorUnavailable:
            pass
    if progress is not None:
        return stream_package_download(
            candidate.download_url, candidate.asset_bytes, candidate.sha256, progress=progress,
        )
    return stream_package_download(candidate.download_url, candidate.asset_bytes, candidate.sha256)


def download_registry_package(
    candidate: RegistryVersion,
    *,
    package_downloader: PackageDownloader | None = None,
    progress: ArchiveInstallTracker | None = None,
) -> Path:
    """Download and re-verify one exact Registry candidate.

    下载并再次校验 Registry 指定的精确候选版本。
    """

    suffix = f"-{candidate.version}.lumina-workshop"
    module_id = candidate.asset_name.removesuffix(suffix)
    if module_id == candidate.asset_name or MODULE_ID_PATTERN.fullmatch(module_id) is None:
        raise WorkshopReleaseError("Registry asset name is invalid")
    path = (
        _download_preferred_package(candidate, module_id, progress)
        if package_downloader is None
        else package_downloader(candidate.download_url, candidate.asset_bytes, candidate.sha256)
    )
    try:
        if progress is not None:
            progress.stage("verifying")
        _inspect_remote_package(
            path,
            expected_module_id=module_id,
            expected_version=candidate.version,
            expected_manifest_sha256=candidate.manifest_sha256,
        )
    except WorkshopReleaseError:
        _remove_rejected_download(path)
        raise
    return path


def _repository_parts(repository_url: str) -> tuple[str, str]:
    parsed = urlsplit(repository_url)
    parts = tuple(part for part in parsed.path.split("/") if part)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
        or repository_url.endswith("/")
        or len(parts) != 2
        or any(
            _GITHUB_REPOSITORY_PART.fullmatch(part) is None
            for part in parts
        )
        or parts[1].endswith(".git")
    ):
        raise WorkshopReleaseError(
            "repository must be an exact GitHub HTTPS URL"
        )
    return parts[0], parts[1]


def _canonical_repository_url(
    repository_url: str,
    *,
    fetch_json: JsonFetcher,
) -> str:
    owner, repository = _repository_parts(repository_url)
    metadata = fetch_json(
        "https://api.github.com/repos/"
        f"{quote(owner, safe='')}/{quote(repository, safe='')}"
    )
    repository_id = metadata.get("id")
    full_name = metadata.get("full_name")
    canonical_url = metadata.get("html_url")
    if (
        not isinstance(repository_id, int)
        or isinstance(repository_id, bool)
        or repository_id <= 0
        or not isinstance(full_name, str)
        or not isinstance(canonical_url, str)
        or canonical_url != f"https://github.com/{full_name}"
    ):
        raise WorkshopReleaseError(
            "GitHub asset URL does not match the requested repository"
        )
    _repository_parts(canonical_url)
    return canonical_url


def resolve_github_release_package(
    repository_url: str,
    version: str,
    *,
    fetch_json: JsonFetcher | None = None,
    package_downloader: PackageDownloader | None = None,
    progress: ArchiveInstallTracker | None = None,
) -> Path:
    """Resolve a full public Release, including confirmed repository moves.

    解析正式公开的 Release 和标准安装包, 支持 GitHub 确认的仓库迁移。
    """

    try:
        validate_semver(version)
    except ValueError as exc:
        raise WorkshopReleaseError(
            "GitHub release version must be valid SemVer"
        ) from exc
    owner, repository = _repository_parts(repository_url)
    tag = f"v{version}"
    metadata_url = (
        "https://api.github.com/repos/"
        f"{quote(owner, safe='')}/{quote(repository, safe='')}/"
        f"releases/tags/{quote(tag, safe='')}"
    )
    active_fetcher = fetch_json or fetch_github_json
    metadata = active_fetcher(metadata_url)
    if (
        metadata.get("tag_name") != tag
        or metadata.get("draft") is not False
        or metadata.get("prerelease") is not False
    ):
        raise WorkshopReleaseError(
            "GitHub release must be full, public, and non-prerelease"
        )
    assets = metadata.get("assets")
    if not isinstance(assets, list):
        raise WorkshopReleaseError(
            "GitHub release assets are unavailable"
        )
    matches: list[tuple[dict[str, object], re.Match[str]]] = []
    for item in assets:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str):
            continue
        match = _GITHUB_ASSET_NAME.fullmatch(name)
        if match is not None and match.group("version") == version:
            matches.append((item, match))
    if len(matches) != 1:
        raise WorkshopReleaseError(
            "GitHub release must contain exactly one standard package asset"
        )
    asset, name_match = matches[0]
    asset_name = str(asset["name"])
    expected_url = (
        f"{repository_url}/releases/download/{tag}/{asset_name}"
    )
    if asset.get("browser_download_url") != expected_url:
        canonical_repository = _canonical_repository_url(
            repository_url,
            fetch_json=active_fetcher,
        )
        canonical_asset_url = (
            f"{canonical_repository}/releases/download/{tag}/{asset_name}"
        )
        if asset.get("browser_download_url") != canonical_asset_url:
            raise WorkshopReleaseError(
                "GitHub asset URL does not match the requested repository"
            )
    asset_size = asset.get("size")
    if (
        not isinstance(asset_size, int)
        or isinstance(asset_size, bool)
        or asset_size <= 0
        or asset_size > MAX_PACKAGE_BYTES
    ):
        raise WorkshopReleaseError(
            "GitHub package asset has an invalid size"
        )
    expected_digest = None
    digest_value = asset.get("digest")
    if isinstance(digest_value, str) and digest_value.startswith("sha256:"):
        possible_digest = digest_value.removeprefix("sha256:")
        if re.fullmatch(r"[0-9a-f]{64}", possible_digest):
            expected_digest = possible_digest
    if package_downloader is not None:
        path = package_downloader(expected_url, asset_size, expected_digest)
    elif progress is not None:
        path = stream_package_download(expected_url, asset_size, expected_digest, progress=progress)
    else:
        path = stream_package_download(expected_url, asset_size, expected_digest)
    try:
        if progress is not None:
            progress.stage("verifying")
        _inspect_remote_package(
            path,
            expected_module_id=name_match.group("module_id"),
            expected_version=version,
        )
    except WorkshopReleaseError:
        _remove_rejected_download(path)
        raise
    return path
