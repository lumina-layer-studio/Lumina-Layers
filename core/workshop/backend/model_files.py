"""Hash-pinned model files shared through the content store.

Models are not Python packages: the host downloads each declared file once,
verifies size and SHA-256, stores it by digest, and exposes it to each module
version under its declared file name. The runtime keeps a stored model while
an installed version or the user's retention choice references it, so the
same rule holds on volumes where views are copies instead of hard links.

模型文件按 SHA-256 存入内容仓，字节相同即共享；只要已安装版本或用户的保留
选择仍引用它，宿主就保留该对象，不支持硬链接的卷也遵循同一规则。
"""

from __future__ import annotations

import hashlib
import os
import stat
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from ..errors import WorkshopBackendError
from ..models import BackendModelFile, MODULE_ID_PATTERN, validate_semver
from .store import ContentStore, RemovalOutcome, remove_tree, unlink_with_retry
from .tooling import CancelToken


_CHUNK_BYTES = 1024 * 1024
ProgressCallback = Callable[[int], None]


class ModelFetcher(Protocol):
    """Download one URL into ``destination`` with a byte bound."""

    def fetch(
        self,
        url: str,
        destination: Path,
        *,
        expected_bytes: int,
        cancel: CancelToken | None,
        progress: ProgressCallback,
    ) -> None: ...


class HttpsModelFetcher:
    """Bounded HTTPS model download with timeouts and HTTPS-only redirects."""

    def __init__(
        self,
        *,
        connect_timeout_seconds: float = 15.0,
        read_timeout_seconds: float = 60.0,
    ) -> None:
        self._timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=read_timeout_seconds,
            pool=connect_timeout_seconds,
        )

    def fetch(
        self,
        url: str,
        destination: Path,
        *,
        expected_bytes: int,
        cancel: CancelToken | None,
        progress: ProgressCallback,
    ) -> None:
        received = 0
        with httpx.Client(timeout=self._timeout, follow_redirects=True) as client:
            with client.stream(
                "GET",
                url,
                headers={"User-Agent": "Lumina-Studio-Workshop/1"},
            ) as response:
                if urlsplit(str(response.url)).scheme != "https":
                    raise WorkshopBackendError(
                        "model-download-failed",
                        "Model downloads must stay on HTTPS.",
                    )
                if response.status_code != 200:
                    raise WorkshopBackendError(
                        "model-download-failed",
                        f"The model server returned HTTP {response.status_code}.",
                    )
                with destination.open("xb") as sink:
                    for chunk in response.iter_bytes(_CHUNK_BYTES):
                        if cancel is not None:
                            cancel.raise_if_cancelled()
                        received += len(chunk)
                        if received > expected_bytes:
                            raise WorkshopBackendError(
                                "model-verification-failed",
                                "The model file is larger than declared.",
                            )
                        sink.write(chunk)
                        progress(received)


class ModelManager:
    """Prepare, expose, retain, and release backend model files.

    准备、提供、保留与释放后端模型文件。
    """

    def __init__(
        self,
        root: Path,
        *,
        store: ContentStore,
        fetcher: ModelFetcher,
    ) -> None:
        self.root = Path(root)
        self.views_dir = self.root / "views"
        self.views_dir.mkdir(parents=True, exist_ok=True)
        self._store = store
        self._fetcher = fetcher

    def view_dir(self, module_id: str, version: str) -> Path:
        if MODULE_ID_PATTERN.fullmatch(module_id) is None:
            raise WorkshopBackendError("module-invalid", "Module ID is invalid.")
        validate_semver(version)
        return self.views_dir / module_id / version

    def _download(
        self,
        model: BackendModelFile,
        destination: Path,
        *,
        cancel: CancelToken | None,
        progress: ProgressCallback,
    ) -> bool:
        """Download, verify, publish, and expose one model; ``False`` = copied view."""

        temporary = self._store.temporary_dir / f"model-{uuid.uuid4().hex}"
        try:
            try:
                self._fetcher.fetch(
                    model.url,
                    temporary,
                    expected_bytes=model.size_bytes,
                    cancel=cancel,
                    progress=progress,
                )
            except WorkshopBackendError:
                raise
            except (httpx.HTTPError, OSError) as exc:
                raise WorkshopBackendError(
                    "model-download-failed",
                    "A model file could not be downloaded. Check the network, then retry.",
                ) from exc
            size = temporary.stat().st_size
            digest = hashlib.sha256()
            with temporary.open("rb") as stream:
                while chunk := stream.read(_CHUNK_BYTES):
                    digest.update(chunk)
            if size != model.size_bytes or digest.hexdigest() != model.sha256:
                raise WorkshopBackendError(
                    "model-verification-failed",
                    "A downloaded model file did not match its declared size and SHA-256.",
                )
            return self._store.import_verified_file(temporary, model.sha256, destination)
        finally:
            if temporary.exists():
                unlink_with_retry(temporary)

    def ensure_models(
        self,
        module_id: str,
        version: str,
        models: Sequence[BackendModelFile],
        *,
        cancel: CancelToken | None,
        progress: Callable[[str, int, int], None],
    ) -> tuple[dict[str, Path], int, int]:
        """Return model paths plus physical ``(new_bytes, shared_bytes)``.

        A view that had to be a copy adds its full size to ``new_bytes``:
        the disk really grows by that much even though nothing downloads.
        """

        view = self.view_dir(module_id, version)
        paths: dict[str, Path] = {}
        new_bytes = 0
        shared_bytes = 0
        for model in models:
            if cancel is not None:
                cancel.raise_if_cancelled()
            destination = view / model.file_name
            linked = self._store.link_existing(model.sha256, destination)
            if linked is None:
                linked = self._download(
                    model,
                    destination,
                    cancel=cancel,
                    progress=lambda received, model=model: progress(
                        model.id,
                        received,
                        model.size_bytes,
                    ),
                )
                new_bytes += model.size_bytes
                if not linked:
                    new_bytes += model.size_bytes
            elif linked:
                shared_bytes += model.size_bytes
            else:
                new_bytes += model.size_bytes
            paths[model.id] = destination
        return paths, new_bytes, shared_bytes

    def copy_usage(self) -> tuple[int, int]:
        """``(files, bytes)`` of views that are copies rather than links."""

        count = 0
        total = 0
        for directory, _dirs, files in os.walk(self.views_dir):
            for name in files:
                try:
                    info = (Path(directory) / name).lstat()
                except OSError:
                    continue
                if stat.S_ISREG(info.st_mode) and info.st_nlink <= 1:
                    count += 1
                    total += info.st_size
        return count, total

    def remove_view(self, module_id: str, version: str | None = None) -> RemovalOutcome:
        if version is None:
            if MODULE_ID_PATTERN.fullmatch(module_id) is None:
                raise WorkshopBackendError("module-invalid", "Module ID is invalid.")
            return remove_tree(self.views_dir / module_id)
        return remove_tree(self.view_dir(module_id, version))

    def views(self) -> tuple[tuple[str, str], ...]:
        found: list[tuple[str, str]] = []
        for module_dir in sorted(self.views_dir.iterdir()) if self.views_dir.is_dir() else ():
            if not module_dir.is_dir():
                continue
            for version_dir in sorted(module_dir.iterdir()):
                if version_dir.is_dir():
                    found.append((module_dir.name, version_dir.name))
        return tuple(found)
