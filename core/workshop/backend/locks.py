"""Strict PEP 751 ``pylock.toml`` subset used by module backends.

Module backends ship hash-locked, wheels-only dependency locks. The host
parses them without executing module code, derives a canonical content digest
for environment sharing, and can rewrite wheel locations to a local
wheelhouse or HTTPS mirror. Content is always verified by uv against the
locked SHA-256, whatever location is used.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tomllib
import platform as platform_module
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from ..constants import (
    MAX_BACKEND_LOCK_BYTES,
    MAX_BACKEND_LOCK_PACKAGES,
    MAX_BACKEND_LOCK_WHEELS,
)
from ..errors import WorkshopPackageError


_NAME_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+!_-]{0,63}$")
_WHEEL_FILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!-]{0,239}\.whl$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_NON_WHEEL_SOURCES = ("sdist", "vcs", "directory", "archive")
PYPI_FILES_PREFIX = "https://files.pythonhosted.org/"


@dataclass(frozen=True, slots=True)
class LockedWheel:
    """One hash-pinned wheel candidate for a locked package."""

    file_name: str
    url: str
    sha256: str
    size: int | None


@dataclass(frozen=True, slots=True)
class LockedPackage:
    """One exact package entry; uv evaluates its marker and wheel tags."""

    name: str
    version: str
    marker: str | None
    wheels: tuple[LockedWheel, ...]


@dataclass(frozen=True, slots=True)
class BackendLock:
    """Validated lock with a canonical digest independent of formatting."""

    packages: tuple[LockedPackage, ...]
    requires_python: str | None
    digest: str


@dataclass(frozen=True, slots=True)
class WheelSourcePolicy:
    """Host-owned wheel locations; never part of a module's identity.

    ``wheelhouse`` serves wheels by file name for offline or development
    use. ``mirror_prefix`` replaces the PyPI files host for regional mirrors.
    """

    wheelhouse: Path | None = None
    mirror_prefix: str | None = None
    offline: bool = False


def normalize_package_name(value: str) -> str:
    """Return the PEP 503 normalized distribution name."""

    return re.sub(r"[-_.]+", "-", value).lower()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise WorkshopPackageError(f"invalid backend lock: {message}")


def _wheel_file_name(entry: dict[str, Any], url: str) -> str:
    raw = entry.get("name")
    if raw is None:
        raw = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
    _require(isinstance(raw, str), "wheel name must be a string")
    _require(_WHEEL_FILE_PATTERN.fullmatch(raw) is not None, "unsafe wheel file name")
    return raw


def _parse_wheel(entry: Any) -> LockedWheel:
    _require(isinstance(entry, dict), "wheel entries must be tables")
    _require("path" not in entry, "local wheel paths are not allowed")
    url = entry.get("url")
    _require(isinstance(url, str) and len(url) <= 4096, "wheel url is required")
    parsed = urlsplit(url)
    _require(
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment,
        "wheel url must be credential-free HTTPS",
    )
    hashes = entry.get("hashes")
    _require(isinstance(hashes, dict), "wheel hashes are required")
    sha256 = hashes.get("sha256")
    _require(
        isinstance(sha256, str) and _SHA256_PATTERN.fullmatch(sha256) is not None,
        "wheel sha256 must be 64 lowercase hex characters",
    )
    size = entry.get("size")
    _require(
        size is None or (isinstance(size, int) and not isinstance(size, bool) and size >= 0),
        "wheel size must be a non-negative integer",
    )
    return LockedWheel(
        file_name=_wheel_file_name(entry, url),
        url=url,
        sha256=sha256,
        size=size,
    )


def _parse_package(entry: Any) -> LockedPackage:
    _require(isinstance(entry, dict), "packages must be tables")
    for key in _NON_WHEEL_SOURCES:
        _require(key not in entry, "backend locks must use prebuilt wheels only")
    name = entry.get("name")
    version = entry.get("version")
    _require(isinstance(name, str) and _NAME_PATTERN.fullmatch(name) is not None, "package name is invalid")
    _require(
        isinstance(version, str) and _VERSION_PATTERN.fullmatch(version) is not None,
        "package version must be exact",
    )
    marker = entry.get("marker")
    _require(marker is None or (isinstance(marker, str) and 0 < len(marker) <= 2000), "marker is invalid")
    wheels = entry.get("wheels")
    _require(
        isinstance(wheels, list) and 0 < len(wheels) <= MAX_BACKEND_LOCK_WHEELS,
        "each package needs between one and 64 wheels",
    )
    parsed_wheels = tuple(_parse_wheel(item) for item in wheels)
    _require(
        len({wheel.file_name for wheel in parsed_wheels}) == len(parsed_wheels),
        "duplicate wheel file names",
    )
    return LockedPackage(
        name=normalize_package_name(name),
        version=version,
        marker=marker,
        wheels=parsed_wheels,
    )


def _canonical_digest(packages: tuple[LockedPackage, ...]) -> str:
    canonical = sorted(
        [
            package.name,
            package.version,
            package.marker or "",
            sorted([wheel.file_name, wheel.sha256] for wheel in package.wheels),
        ]
        for package in packages
    )
    payload = json.dumps(canonical, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def parse_backend_lock(data: bytes) -> BackendLock:
    """Validate one bounded pylock.toml without resolving or downloading.

    在不解析依赖、不下载文件的前提下校验一份有界 pylock.toml。
    """

    _require(len(data) <= MAX_BACKEND_LOCK_BYTES, "lock exceeds size limit")
    try:
        text = data.decode("utf-8", errors="strict")
        document = tomllib.loads(text)
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise WorkshopPackageError("invalid backend lock: not valid TOML") from exc
    lock_version = document.get("lock-version")
    _require(
        isinstance(lock_version, str) and lock_version.split(".", 1)[0] == "1",
        "lock-version must be 1.x",
    )
    requires_python = document.get("requires-python")
    _require(
        requires_python is None or (isinstance(requires_python, str) and len(requires_python) <= 200),
        "requires-python is invalid",
    )
    raw_packages = document.get("packages", [])
    _require(
        isinstance(raw_packages, list) and len(raw_packages) <= MAX_BACKEND_LOCK_PACKAGES,
        "packages must be a bounded array",
    )
    packages = tuple(_parse_package(item) for item in raw_packages)
    identities = [(package.name, package.version, package.marker) for package in packages]
    _require(len(identities) == len(set(identities)), "duplicate package entries")
    return BackendLock(
        packages=packages,
        requires_python=requires_python,
        digest=_canonical_digest(packages),
    )


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def _resolved_url(wheel: LockedWheel, policy: WheelSourcePolicy) -> str:
    if policy.wheelhouse is not None:
        candidate = policy.wheelhouse / wheel.file_name
        if candidate.is_file():
            return candidate.resolve().as_uri()
    if policy.mirror_prefix and wheel.url.startswith(PYPI_FILES_PREFIX):
        return policy.mirror_prefix.rstrip("/") + "/" + wheel.url[len(PYPI_FILES_PREFIX):]
    return wheel.url


def render_install_lock(lock: BackendLock, policy: WheelSourcePolicy) -> str:
    """Write an equivalent pylock.toml whose wheel URLs follow host policy.

    生成等价的 pylock.toml，仅按宿主策略改写下载位置，哈希保持不变。
    """

    lines = [
        'lock-version = "1.0"',
        'created-by = "lumina-workshop-host"',
    ]
    if lock.requires_python:
        lines.append(f"requires-python = {_toml_string(lock.requires_python)}")
    for package in lock.packages:
        lines.extend(
            [
                "",
                "[[packages]]",
                f"name = {_toml_string(package.name)}",
                f"version = {_toml_string(package.version)}",
            ]
        )
        if package.marker:
            lines.append(f"marker = {_toml_string(package.marker)}")
        for wheel in package.wheels:
            lines.extend(
                [
                    "[[packages.wheels]]",
                    f"name = {_toml_string(wheel.file_name)}",
                    f"url = {_toml_string(_resolved_url(wheel, policy))}",
                ]
            )
            if wheel.size is not None:
                lines.append(f"size = {wheel.size}")
            lines.append(f"hashes = {{ sha256 = {_toml_string(wheel.sha256)} }}")
    return "\n".join(lines) + "\n"


def current_platform_key() -> str | None:
    """Return this host's backend platform key, or ``None`` if unsupported."""

    machine = platform_module.machine().lower()
    if sys.platform == "win32" and machine in {"amd64", "x86_64"}:
        return "windows-x86_64"
    if sys.platform.startswith("linux") and machine in {"x86_64", "amd64"}:
        return "linux-x86_64"
    if sys.platform == "darwin" and machine == "arm64":
        return "macos-arm64"
    return None


def _platform_matches(tag: str, platform_key: str) -> bool:
    for part in tag.split("."):
        if part == "any":
            return True
        if platform_key == "windows-x86_64" and part == "win_amd64":
            return True
        if platform_key == "linux-x86_64" and part.endswith("_x86_64") and (
            part.startswith("manylinux") or part.startswith("linux")
        ):
            return True
        if platform_key == "macos-arm64" and part.startswith("macosx_") and part.endswith(
            ("_arm64", "_universal2")
        ):
            return True
    return False


def _python_matches(python_tag: str, abi_tag: str, minor: int) -> bool:
    for part in python_tag.split("."):
        if part in {"py3", f"py3{minor}", f"cp3{minor}"}:
            return True
        if part.startswith("cp3") and part[3:].isdigit() and "abi3" in abi_tag.split("."):
            if int(part[3:]) <= minor:
                return True
    return False


def estimated_wheel(
    package: LockedPackage,
    *,
    platform_key: str,
    python_version: str,
) -> LockedWheel | None:
    """Pick the largest plausibly compatible wheel for size previews.

    This only estimates disk use for the preview; uv performs the actual
    marker and tag evaluation during installation.
    仅用于预览估算占用；真实的标记与标签选择由 uv 在安装时完成。
    """

    minor = int(python_version.split(".", 1)[1])
    compatible: list[LockedWheel] = []
    for wheel in package.wheels:
        parts = wheel.file_name[: -len(".whl")].split("-")
        if len(parts) < 5:
            continue
        python_tag, abi_tag, platform_tag = parts[-3], parts[-2], parts[-1]
        if _platform_matches(platform_tag, platform_key) and _python_matches(
            python_tag,
            abi_tag,
            minor,
        ):
            compatible.append(wheel)
    if not compatible:
        return None
    return max(compatible, key=lambda wheel: wheel.size or 0)
