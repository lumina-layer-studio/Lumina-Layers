"""Process-wide wiring of the Workshop backend runtime for the API.

One runtime exists per Workshop data directory and is created lazily, so
starting the app or listing frontend-only modules never touches backend
storage. Installers created here carry the runtime hooks that bind package
identity and keep versions needed by running tasks.

为 API 进程按创意工坊数据目录懒加载后端运行时；启动应用或列出纯前端模块不会
触碰后端存储。此处创建的安装器带有绑定包身份和保留在用版本的钩子。
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from api.structured_logging import get_logger
from config import get_asset_path, get_workshop_data_dir
from core.workshop import WorkshopInstaller, load_registry_keys
from core.workshop.backend.locks import WheelSourcePolicy
from core.workshop.backend.model_files import HttpsModelFetcher
from core.workshop.backend.review import (
    ReviewAttestationClient,
    ReviewContext,
)
from core.workshop.backend.runtime import WorkshopBackendRuntime
from core.workshop.backend.tooling import locate_uv_executable
from core.workshop.errors import WorkshopError
from core.workshop.models import InspectedWorkshopPackage, WorkshopManifestV2


log = get_logger(__name__)

_REVIEW_CONTEXT_TTL_SECONDS = 300.0
_runtimes: dict[str, WorkshopBackendRuntime] = {}
_runtimes_lock = threading.Lock()


def _key(data_dir: str | Path) -> str:
    return os.path.normcase(str(Path(data_dir).expanduser().resolve()))


def _https_or_none(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        log.warning(
            "Ignoring non-HTTPS Workshop mirror setting",
            extra={"event": "workshop_backend_mirror_ignored", "error_message": "mirror must be HTTPS"},
        )
        return None
    return value.strip()


def get_review_attestation_client(data_dir: Path) -> ReviewAttestationClient:
    """Signed review attestations, verified with the app-owned keys."""

    return ReviewAttestationClient(
        keys=load_registry_keys(get_asset_path("workshop-registry/keys.json")),
        cache_dir=data_dir / "cache",
    )


class _CachedReviewContext:
    """Refresh Registry and review evidence at most every few minutes."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._lock = threading.Lock()
        self._value: ReviewContext | None = None
        self._loaded_at = 0.0

    def __call__(self) -> ReviewContext:
        with self._lock:
            if self._value is not None and time.monotonic() - self._loaded_at < _REVIEW_CONTEXT_TTL_SECONDS:
                return self._value
            registry = None
            try:
                from api.routers import workshop as workshop_routes

                result = workshop_routes.get_workshop_registry_client().refresh()
                registry = result.index if result.verified else None
            except (WorkshopError, OSError):
                registry = None
            try:
                reviews = get_review_attestation_client(self._data_dir).refresh()
            except (WorkshopError, OSError):
                reviews = None
            self._value = ReviewContext.from_sources(registry, reviews)
            self._loaded_at = time.monotonic()
            return self._value


def _build_runtime(data_dir: Path) -> WorkshopBackendRuntime:
    environment = os.environ
    wheelhouse = environment.get("LUMINA_WORKSHOP_WHEELHOUSE", "").strip()
    external_python = environment.get("LUMINA_WORKSHOP_PYTHON", "").strip()
    return WorkshopBackendRuntime(
        data_dir=data_dir,
        installer_factory=lambda: create_workshop_installer(data_dir),
        uv_executable=locate_uv_executable(),
        model_fetcher=HttpsModelFetcher(),
        review_context=_CachedReviewContext(data_dir),
        wheel_sources=WheelSourcePolicy(
            wheelhouse=Path(wheelhouse) if wheelhouse else None,
            mirror_prefix=_https_or_none(environment.get("LUMINA_WORKSHOP_WHEEL_MIRROR")),
            offline=environment.get("LUMINA_WORKSHOP_OFFLINE", "").strip().lower() in {"1", "true", "yes"},
        ),
        external_python=Path(external_python) if external_python else None,
        python_mirror=_https_or_none(environment.get("LUMINA_WORKSHOP_PYTHON_MIRROR")),
    )


def get_workshop_backend_runtime(data_dir: str | Path) -> WorkshopBackendRuntime:
    """Return the runtime for one data directory, creating it on first use."""

    key = _key(data_dir)
    with _runtimes_lock:
        runtime = _runtimes.get(key)
        if runtime is None:
            runtime = _build_runtime(Path(data_dir).expanduser().resolve())
            _runtimes[key] = runtime
        return runtime


def existing_workshop_backend_runtime(data_dir: str | Path) -> WorkshopBackendRuntime | None:
    with _runtimes_lock:
        return _runtimes.get(_key(data_dir))


def create_workshop_installer(data_dir: str | Path | None = None) -> WorkshopInstaller:
    """Build an installer whose hooks reach the runtime only when needed."""

    root = Path(data_dir if data_dir is not None else get_workshop_data_dir())

    def record_package(inspected: InspectedWorkshopPackage, staging: Path) -> None:
        if isinstance(inspected.manifest, WorkshopManifestV2):
            get_workshop_backend_runtime(root).record_package(inspected, staging)

    def version_in_use(module_id: str, version: str) -> bool:
        runtime = existing_workshop_backend_runtime(root)
        return runtime is not None and runtime.version_in_use(module_id, version)

    return WorkshopInstaller(
        data_dir=root,
        after_extract=record_package,
        version_in_use=version_in_use,
    )


def start_existing_backend_runtime() -> None:
    """Reconcile backend storage at app startup if a runtime was ever used."""

    data_dir = Path(get_workshop_data_dir())
    if not (data_dir / "runtime").is_dir():
        return
    get_workshop_backend_runtime(data_dir).startup()


def purge_expired_backend_task_data() -> None:
    with _runtimes_lock:
        runtimes = list(_runtimes.values())
    for runtime in runtimes:
        runtime.purge_expired_task_data()


def shutdown_backend_runtimes() -> None:
    """Stop every backend process this API process started."""

    with _runtimes_lock:
        runtimes = list(_runtimes.values())
        _runtimes.clear()
    for runtime in runtimes:
        runtime.shutdown()
