"""Fetch the wheels selected for one backend before uv installs them."""

from __future__ import annotations

import os
import re
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from packaging.markers import (
    InvalidMarker,
    Marker,
    UndefinedComparison,
    UndefinedEnvironmentName,
    default_environment,
)
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

from ..errors import WorkshopBackendError
from .downloads import DownloadBatch, DownloadProgress, download_https, ordered_sources, source_id
from .locks import BackendLock, LockedWheel, WheelSourcePolicy, PYPI_FILES_PREFIX, render_install_lock
from .store import RemovalOutcome, remove_tree, sha256_file, unlink_with_retry
from .tooling import BackendInterpreter, CancelToken, cancellable_lock, read_python_version


_MARKER_TOKENS = re.compile(
    r"""(?P<literal>'[^']*'|"[^"]*")|(?P<patch>\b(?:python_full_version|implementation_version)\b)"""
    r"|(?P<boundary>\b(?:and|or)\b|[()])"
)


def marker_depends_on_python_patch(expression: str | None) -> bool:
    return expression is not None and any(
        token.lastgroup == "patch" for token in _MARKER_TOKENS.finditer(expression)
    )


def _marker_with_unknown_patch(expression: str) -> Marker:
    """Keep fixed platform constraints while allowing any target patch."""
    parts: list[str] = []
    start = 0
    depends_on_patch = False
    # Quoted literals are consumed whole, so only operators outside them can
    # delimit an atom. PEP 508 combines atoms with and/or and parentheses.
    for token in _MARKER_TOKENS.finditer(expression):
        if token.lastgroup == "patch":
            depends_on_patch = True
        elif token.lastgroup == "boundary":
            parts.append(" python_version >= '0' " if depends_on_patch else expression[start:token.start()])
            parts.append(token.group())
            start = token.end()
            depends_on_patch = False
    parts.append(" python_version >= '0' " if depends_on_patch else expression[start:])
    return Marker("".join(parts))


_TUNA_PYPI_MIRROR = "https://pypi.tuna.tsinghua.edu.cn/"


def wheel_download_urls(
    wheel: LockedWheel,
    policy: WheelSourcePolicy,
    mirrors: Mapping[str, tuple[str, ...]],
    preferred: str,
) -> tuple[str, ...]:
    alternatives = mirrors.get(wheel.sha256, ())
    mirror = policy.mirror_prefix
    if mirror is None and wheel.url.startswith(PYPI_FILES_PREFIX + "packages/") and "?" not in wheel.url:
        mirror = _TUNA_PYPI_MIRROR
    if mirror and wheel.url.startswith(PYPI_FILES_PREFIX):
        alias = mirror.rstrip("/") + "/" + wheel.url[len(PYPI_FILES_PREFIX):]
        if preferred == "auto":
            return ordered_sources(alias, (wheel.url, *alternatives), preferred)
        alternatives = (alias, *alternatives)
    return ordered_sources(wheel.url, alternatives, preferred)


def select_locked_wheels(lock: BackendLock, python_version: str, full_version: str | None) -> BackendLock:
    """Select wheels for this platform, allowing unresolved patch predicates in previews."""
    if lock.requires_python is not None:
        try:
            requirement = SpecifierSet(lock.requires_python)
        except InvalidSpecifier as exc:
            raise WorkshopBackendError("dependency-install-failed", "Invalid Python requirement in the backend lock.") from exc
        if full_version is not None and not requirement.contains(full_version):
            raise WorkshopBackendError("dependency-install-failed", "The backend lock requires a different Python version.")
    major, minor = (int(part) for part in python_version.split("."))
    abi = f"cp{major}{minor}"
    tags = [*cpython_tags((major, minor), abis=[abi]), *compatible_tags((major, minor), interpreter=abi)]
    ranks = {}
    for index, tag in enumerate(tags):
        ranks.setdefault(tag, index)
    patch = full_version or python_version + ".0"
    environment = {
        **default_environment(),
        "python_version": python_version,
        "python_full_version": patch,
        "implementation_name": "cpython",
        "implementation_version": patch,
        "platform_python_implementation": "CPython",
        "extra": "",
    }
    packages = []
    for package in lock.packages:
        matches = []
        patch_unresolved = full_version is None and marker_depends_on_python_patch(package.marker)
        try:
            if package.marker:
                marker = Marker(package.marker)
                if patch_unresolved:
                    marker = _marker_with_unknown_patch(package.marker)
                if not marker.evaluate(environment, context="lock_file"):
                    continue
            for wheel in package.wheels:
                _, _, build, wheel_tags = parse_wheel_filename(wheel.file_name)
                scores = [ranks[tag] for tag in wheel_tags if tag in ranks]
                if scores:
                    matches.append((min(scores), build or (-1, ""), wheel))
        except (InvalidMarker, UndefinedComparison, UndefinedEnvironmentName, InvalidWheelFilename, KeyError) as exc:
            raise WorkshopBackendError(
                "dependency-install-failed", f"Invalid marker or wheel filename locked for {package.name}."
            ) from exc
        if not matches:
            if patch_unresolved:
                continue
            raise WorkshopBackendError(
                "dependency-install-failed", f"No compatible wheel is locked for {package.name}."
            )
        _, _, selected = max(matches, key=lambda item: (-item[0], item[1]))
        packages.append(replace(package, wheels=(selected,)))
    return replace(lock, packages=tuple(packages))


def _select_wheels(lock: BackendLock, interpreter: BackendInterpreter, cancel: CancelToken) -> BackendLock:
    version = read_python_version(interpreter.executable, cancel)
    if version is None or not version.startswith(interpreter.python_version + "."):
        raise WorkshopBackendError("dependency-install-failed", "Could not query the backend Python version.")
    return select_locked_wheels(lock, interpreter.python_version, version)


class WheelArchiveCache:
    """Reuse verified wheels across locks and mirrors by their SHA-256."""

    def __init__(self, root: Path, *, staging_dir: Path | None = None) -> None:
        self.root = root
        self._staging_dir = staging_dir or root / ".staging"
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _path(self, wheel: LockedWheel) -> Path:
        return self.root / wheel.sha256 / wheel.file_name

    def _archive_paths(self, wheel: LockedWheel) -> Iterator[Path]:
        same_name = self._path(wheel)
        yield same_name
        yield from (path for path in same_name.parent.glob("*.whl") if path != same_name)

    def available(self, wheel: LockedWheel, policy: WheelSourcePolicy) -> bool:
        """Check the local inventory for the preflight estimate."""
        return any(path.is_file() for path in self._archive_paths(wheel)) or (
            policy.wheelhouse is not None and (policy.wheelhouse / wheel.file_name).is_file()
        )

    def _cached(self, wheel: LockedWheel, cancel: CancelToken) -> Path | None:
        return next((path for path in self._archive_paths(wheel) if self._matches(path, wheel, cancel)), None)

    @staticmethod
    def _matches(path: Path, wheel: LockedWheel, cancel: CancelToken) -> bool:
        return (
            path.is_file()
            and (wheel.size is None or path.stat().st_size == wheel.size)
            and sha256_file(path, cancel) == wheel.sha256
        )

    def _download(
        self,
        wheel: LockedWheel,
        urls: tuple[str, ...],
        batch: DownloadBatch,
        index: int,
        cancel: CancelToken,
        unreachable_mirrors: set[str],
    ) -> tuple[Path, int]:
        with self._guard:
            lock = self._locks.setdefault(wheel.sha256, threading.Lock())
        with cancellable_lock(lock, cancel):
            cached = self._cached(wheel, cancel)
            if cached is not None:
                return cached, 0
            target = self._path(wheel)
            target.parent.mkdir(parents=True, exist_ok=True)
            self._staging_dir.mkdir(parents=True, exist_ok=True)
            last_error: WorkshopBackendError | None = None
            last_source = ""
            for url in urls:
                mirror = url != wheel.url
                authority = urlsplit(url).netloc
                if mirror and authority in unreachable_mirrors:
                    continue
                temporary = self._staging_dir / f"wheel-{uuid.uuid4().hex}.part"
                report = batch.attempt(index, wheel.file_name, url)
                try:
                    timeout = httpx.Timeout(60, connect=5) if mirror and url.startswith(_TUNA_PYPI_MIRROR) else None
                    download_https(
                        url, temporary, cancel=cancel, progress=report, size=wheel.size,
                        timeout=timeout,
                    )
                    if not self._matches(temporary, wheel, cancel):
                        raise WorkshopBackendError(
                            "download-verification-failed", "The wheel did not match its locked SHA-256 or size."
                        )
                    size = temporary.stat().st_size
                    os.replace(temporary, target)
                    return target, size
                except WorkshopBackendError as exc:
                    if exc.code == "cancelled":
                        raise
                    if mirror and isinstance(exc.__cause__, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError)):
                        unreachable_mirrors.add(authority)
                    last_error = exc
                    last_source = source_id(url)
                finally:
                    if temporary.exists():
                        unlink_with_retry(temporary)
            message = f"Could not download and verify {wheel.file_name}."
            if last_error is not None:
                message += f" {last_source or 'Download source'}: {last_error}"
            raise WorkshopBackendError("dependency-install-failed", message) from last_error

    def prepare(
        self,
        lock: BackendLock,
        interpreter: BackendInterpreter,
        policy: WheelSourcePolicy,
        mirrors: Mapping[str, tuple[str, ...]],
        preferred: str,
        cancel: CancelToken,
        on_progress: Callable[[DownloadProgress], None],
    ) -> tuple[str, tuple[str, ...]]:
        selected = _select_wheels(lock, interpreter, cancel)
        wheels = {package.wheels[0].sha256: package.wheels[0] for package in selected.packages}
        local: dict[str, str] = {}
        cached: set[str] = set()
        needed = []
        for wheel in wheels.values():
            supplied = policy.wheelhouse / wheel.file_name if policy.wheelhouse else None
            if supplied is not None and self._matches(supplied, wheel, cancel):
                local[wheel.sha256] = supplied.resolve().as_uri()
                continue
            archive = self._cached(wheel, cancel)
            if archive is not None:
                local[wheel.sha256] = archive.resolve().as_uri()
                cached.add(wheel.sha256)
            elif not policy.offline:
                needed.append(wheel)
        batch = DownloadBatch((wheel.size for wheel in needed), on_progress)
        unreachable_mirrors: set[str] = set()
        for index, wheel in enumerate(needed):
            urls = wheel_download_urls(wheel, policy, mirrors, preferred)
            archive, size = self._download(wheel, urls, batch, index, cancel, unreachable_mirrors)
            batch.finish(index, size)
            local[wheel.sha256] = archive.resolve().as_uri()
            cached.add(wheel.sha256)
        return render_install_lock(selected, policy, verified_urls=local), tuple(sorted(cached))

    def prune(self, retained: set[str]) -> RemovalOutcome:
        outcome = RemovalOutcome()
        if self.root.is_dir():
            for entry in self.root.iterdir():
                leftovers = (entry,) if entry.name not in retained else tuple(entry.glob(".*.part"))
                for leftover in leftovers:
                    removed = remove_tree(leftover)
                    outcome.freed_bytes += removed.freed_bytes
                    outcome.pending.extend(removed.pending)
        return outcome

    def usage(self) -> dict[str, int]:
        files = size = 0
        for archive in self.root.glob("*/*.whl"):
            try:
                size += archive.stat().st_size
            except OSError:
                continue
            files += 1
        return {"files": files, "bytes": size}
