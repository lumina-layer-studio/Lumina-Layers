"""Install-footprint estimates shown before a backend is authorized.

Estimates come only from the declaration, the lock, and the current
inventory; no module code runs. Exact physical bytes are measured during
preparation and reported afterwards.

授权前展示的安装占用估算，只依据声明、锁文件与本机现有内容，不执行模块代码；
准备完成后再报告实测的物理增量。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ..models import BackendModelFile
from .locks import BackendLock, estimated_wheel


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
) -> DependencyEstimate:
    """Split locked packages into already-present and new downloads."""

    shared_count = 0
    new_bytes = 0
    shared_bytes = 0
    unknown = 0
    for package in lock.packages:
        wheel = estimated_wheel(package, platform_key=platform_key, python_version=python_version)
        size = wheel.size if wheel is not None else None
        present = environment_exists or (package.name, package.version) in package_users
        if present:
            shared_count += 1
            shared_bytes += size or 0
        elif size is None:
            unknown += 1
        else:
            new_bytes += size
    return DependencyEstimate(
        environment_key=environment_key,
        environment_reused=environment_exists,
        package_count=len(lock.packages),
        shared_package_count=shared_count,
        new_download_bytes=new_bytes,
        shared_bytes=shared_bytes,
        unknown_size_packages=unknown,
    )


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
