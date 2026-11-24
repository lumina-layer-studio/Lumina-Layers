"""Install-footprint estimates shown before a backend is authorized.

Estimates come only from the declaration, the lock, and the current
inventory; no module code runs. Exact physical bytes are measured during
preparation and reported afterwards.

授权前展示的安装占用估算，只依据声明、锁文件与本机现有内容，不执行模块代码；
准备完成后再报告实测的物理增量。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from platform import python_version as host_python_version

from ..errors import WorkshopBackendError
from ..models import BackendModelFile
from .locks import BackendLock, LockedWheel, current_platform_key, estimated_wheel
from .wheel_files import select_locked_wheels


# Approximate size of one uv-managed CPython 3.12 runtime. Shown as an
# estimate only when the shared interpreter is not installed yet.
MANAGED_PYTHON_DOWNLOAD_ESTIMATE_BYTES = 32 * 1024 * 1024
MANAGED_PYTHON_DISK_ESTIMATE_BYTES = 110 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class DependencyEstimate:
    environment_key: str
    environment_reused: bool
    package_count: int
    shared_package_count: int
    new_download_bytes: int
    shared_bytes: int
    unknown_size_packages: int
    missing_wheels: Mapping[str, int | None]

    def as_json(self) -> dict[str, object]:
        return {
            "environment_key": self.environment_key,
            "environment_reused": self.environment_reused,
            "package_count": self.package_count,
            "shared_package_count": self.shared_package_count,
            "new_download_bytes": self.new_download_bytes,
            "shared_bytes": self.shared_bytes,
            "unknown_size_packages": self.unknown_size_packages,
        }


def estimate_dependencies(
    lock: BackendLock,
    *,
    environment_key: str,
    environment_exists: bool,
    package_users: Mapping[tuple[str, str], set[str]],
    platform_key: str,
    python_version: str,
    archive_available: Callable[[LockedWheel], bool] | None = None,
) -> DependencyEstimate:
    """Split locked packages into already-present and new downloads."""

    shared_count = 0
    new_bytes = 0
    shared_bytes = 0
    unknown = 0
    missing_wheels: dict[str, int | None] = {}
    selected: BackendLock | None = None
    if platform_key == current_platform_key():
        full_version = host_python_version()
        if not full_version.startswith(python_version + "."):
            full_version = python_version + ".0"
        try:
            selected = select_locked_wheels(lock, python_version, full_version)
        except WorkshopBackendError:
            # Status stays available for a lock that would fail preparation.
            pass
    packages = selected.packages if selected is not None else lock.packages
    for package in packages:
        wheel = (
            package.wheels[0] if selected is not None
            else estimated_wheel(package, platform_key=platform_key, python_version=python_version)
        )
        size = wheel.size if wheel is not None else None
        if archive_available is None:
            present = environment_exists or (package.name, package.version) in package_users
        else:
            present = environment_exists or (wheel is not None and archive_available(wheel))
        if present:
            shared_count += 1
            shared_bytes += size or 0
        else:
            key = wheel.sha256 if wheel is not None else f"{package.name}=={package.version}"
            if missing_wheels.get(key) is None:
                missing_wheels[key] = size
            if size is None:
                unknown += 1
            else:
                new_bytes += size
    return DependencyEstimate(
        environment_key=environment_key,
        environment_reused=environment_exists,
        package_count=len(packages),
        shared_package_count=shared_count,
        new_download_bytes=new_bytes,
        shared_bytes=shared_bytes,
        unknown_size_packages=unknown,
        missing_wheels=missing_wheels,
    )


def estimate_download_total(
    dependencies: list[DependencyEstimate],
    files: tuple[BackendModelFile, ...],
    present: set[str],
    interpreter_bytes: int,
) -> dict[str, int | bool]:
    wheels: dict[str, int | None] = {}
    for dependency in dependencies:
        for digest, size in dependency.missing_wheels.items():
            if wheels.get(digest) is None:
                wheels[digest] = size
    missing_files = {item.sha256: item.size_bytes for item in files if item.sha256 not in present}
    return {
        "bytes": interpreter_bytes + sum(missing_files.values()) + sum(size or 0 for size in wheels.values()),
        "incomplete": any(size is None for size in wheels.values()),
    }


def model_estimates(
    models: tuple[BackendModelFile, ...],
    present: set[str],
) -> list[dict[str, object]]:
    return [
        {
            "id": model.id,
            "file_name": model.file_name,
            "bytes": model.size_bytes,
            "license": model.license,
            "shared": model.sha256 in present,
        }
        for model in models
    ]
