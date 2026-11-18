"""Persistent, process-safe initialization of a shared resource library."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator


class SeedBusyError(RuntimeError):
    """Another application instance is initializing this library."""


def seed_catalog_signature(path: Path, family: str) -> tuple[Any, ...]:
    """Invalidate cached display metadata when the source or verification inputs change."""

    def marker(file: Path) -> tuple[int, int, int, int]:
        stat = file.stat()
        return stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    descriptor = path.parent.parent / "resource-release.json"
    return (
        marker(path),
        marker(descriptor) if descriptor.exists() else None,
        os.environ.get(f"LUMINA_{family.upper()}_SEED_SHA256"),
    )


def verify_seed_release(path: Path, family: str) -> str | None:
    """Verify packaged resources against their paired release descriptor.

    Standalone user-supplied legacy seeds remain supported without a descriptor.
    """
    descriptor = path.parent.parent / "resource-release.json"
    version = None
    artifact = None
    if descriptor.exists():
        if descriptor.stat().st_size > 512 * 1024:
            raise ValueError("Starter resource descriptor exceeds the size limit")
        release = json.loads(descriptor.read_text(encoding="utf-8"))
        if (
            not isinstance(release, dict)
            or release.get("kind") != "lumina_resource_release"
            or release.get("schema_version") != 1
        ):
            raise ValueError("Unsupported starter resource descriptor")
        artifacts = release.get("artifacts")
        artifact = artifacts.get(family) if isinstance(artifacts, dict) else None
        if (
            not isinstance(artifact, dict)
            or artifact.get("path") != path.name
            or artifact.get("bytes") != path.stat().st_size
        ):
            raise ValueError(f"Starter {family} resource does not match its release")
        version = release.get("dataset_version")
        if not isinstance(version, str) or not version:
            raise ValueError("Starter resource dataset version is missing")
    expected = os.environ.get(f"LUMINA_{family.upper()}_SEED_SHA256", "").strip().lower().removeprefix("sha256:")
    if artifact is None and not expected:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    if artifact is not None and digest.hexdigest() != artifact.get("sha256"):
        raise ValueError(f"Starter {family} resource does not match its release")
    if expected and digest.hexdigest() != expected:
        raise ValueError(f"Starter {family} resource sha256 mismatch")
    return version


@contextmanager
def seed_lock(state_dir: Path) -> Iterator[None]:
    """An OS lock is released on process exit, including interrupted installs."""
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / "seed.lock").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SeedBusyError("Resource library is being initialized by another instance") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_seed_state(state_dir: Path) -> dict[str, Any]:
    path = state_dir / "seed.json"
    if not path.exists():
        return {"state": "uninitialized"}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("state") not in {
            "initializing", "ready", "failed",
        }:
            raise ValueError("Invalid seed state")
        return payload
    except (OSError, ValueError, UnicodeError):
        # A damaged record must not silently authorize automatic reinstallation.
        return {"state": "failed", "error": "Resource initialization record is unreadable", "needs_restore": True}


def write_seed_state(state_dir: Path, **fields: Any) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "seed.json"
    temporary = path.with_name(f".seed-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps({
            "schema_version": 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **fields,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def initialize_seed(
    *, state_dir: Path, has_content: Callable[[], bool],
    install: Callable[[], dict[str, Any] | None], restore: bool = False,
) -> dict[str, Any] | None:
    """Install once; retries retain the installer's revision-level idempotency."""
    with seed_lock(state_dir):
        state = read_seed_state(state_dir)
        if not restore:
            if state["state"] == "ready" or state.get("needs_restore"):
                return None
            if state["state"] == "uninitialized" and has_content():
                write_seed_state(state_dir, state="ready", reason="existing_library")
                return None
        write_seed_state(state_dir, state="initializing")
        try:
            result = install()
        except Exception as exc:
            write_seed_state(state_dir, state="failed", error=str(exc))
            raise
        if result is None:
            # Remember that the library has been opened even without a bundled
            # seed. A later application upgrade must not resurrect deleted data.
            write_seed_state(state_dir, state="ready", reason="no_bundled_seed")
        else:
            write_seed_state(state_dir, state="ready", installed_count=result["installed_count"],
                             dataset_version=result.get("dataset_version"))
        return result
