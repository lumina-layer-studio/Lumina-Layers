"""Per-workspace public catalog preferences. Account endpoints stay independent."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


def sources_path() -> Path:
    return Path(os.environ.get("LUMINA_SETTINGS_PATH", "user_settings.json")).expanduser().parent / "resource-sources.json"


def normalize_source(mode: str, mirror_url: str = "") -> dict[str, str]:
    if mode not in {"default", "github", "mirror"}:
        raise ValueError("Choose the default source, GitHub or a static mirror.")
    if mode != "mirror":
        return {"mode": mode, "mirror_url": ""}
    value = mirror_url.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        parsed.port
        if (len(value) > 2048 or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or any(c.isspace() for c in value)
                or any(c in value for c in ("%", "\\"))
                or any(part in {".", ".."} for part in parsed.path.split("/"))
                or parsed.scheme not in {"https", "http"}
                or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"})):
            raise ValueError
    except ValueError as exc:
        raise ValueError("Use an HTTPS static catalog address without credentials, query or fragment.") from exc
    return {"mode": mode, "mirror_url": value}


def source_preferences() -> dict[str, str]:
    path = sources_path()
    try:
        if path.stat().st_size > 4096:
            raise ValueError("Resource source settings exceed the supported size.")
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return normalize_source("default")
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError("Unsupported resource source settings. Restore the settings file before changing sources.")
    return normalize_source(data.get("mode", ""), data.get("mirror_url", ""))


def effective_preferences() -> dict[str, str]:
    # A broken optional preference must not prevent startup or local conversion.
    try:
        return source_preferences()
    except (OSError, ValueError, TypeError, AttributeError):
        return normalize_source("default")


def save_source_preferences(mode: str, mirror_url: str = "") -> dict[str, str]:
    value = normalize_source(mode, mirror_url)
    source_preferences()  # Preserve unknown/newer schemas rather than overwrite them.
    path = sources_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix=".resource-sources-", suffix=".tmp", dir=path.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": 1, **value}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return value


def source_settings_status() -> dict[str, Any]:
    try:
        return {**source_preferences(), "error": None}
    except (OSError, ValueError, TypeError, AttributeError):
        return {**normalize_source("default"), "error": "invalid_settings"}
