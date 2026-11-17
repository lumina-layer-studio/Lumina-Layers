"""Source defaults use public snapshots; distribution injects its hosted service."""

from __future__ import annotations

import os

from core.resource_sources import effective_preferences

PUBLIC_REGISTRY_URL = "https://materials.luminastudio.com.cn/api/material-registry/v1"
PUBLIC_REGISTRY_FALLBACK_URL = "https://dan5.shmx.top/api/material-registry/v1"
PUBLIC_CHANNELS = ("official", "community")
GITHUB_CATALOG_URL = "https://raw.githubusercontent.com/lumina-layer-studio/Lumina-materials/master/public/v1"


def public_catalog_url() -> str:
    """Allow a static mirror, including the local acceptance fixture."""
    return os.environ.get("LUMINA_PUBLIC_CATALOG_URL", GITHUB_CATALOG_URL).strip().rstrip("/")


def is_static_catalog(url: str) -> bool:
    preferences = effective_preferences()
    return bool(url) and url.rstrip("/") in {
        public_catalog_url(), GITHUB_CATALOG_URL, preferences["mirror_url"],
    }


def resource_provider(family: str) -> str:
    url = lut_registry_url() if family == "LUT" else material_registry_url()
    return "github" if is_static_catalog(url) else "registry" if url else "disabled"


def material_registry_url() -> str:
    """An explicitly empty URL disables public resources."""
    return _selected_url("MATERIAL")


def lut_registry_url() -> str:
    return _selected_url("LUT")


def default_registry_url(family: str) -> str:
    material = os.environ.get("LUMINA_MATERIAL_REGISTRY_URL", public_catalog_url()).strip().rstrip("/")
    return os.environ.get("LUMINA_LUT_REGISTRY_URL", material).strip().rstrip("/") if family == "LUT" else material


def _selected_url(family: str) -> str:
    preferences = effective_preferences()
    if preferences["mode"] == "github":
        return GITHUB_CATALOG_URL
    if preferences["mode"] == "mirror":
        return preferences["mirror_url"]
    return default_registry_url(family)


def registry_read_token(family: str, source: str | None = None) -> str:
    """Read credentials belong only to an explicitly configured source."""
    source = source if source is not None else lut_registry_url() if family == "LUT" else material_registry_url()
    if is_static_catalog(source):
        return ""
    if source != default_registry_url(family):
        return ""
    if family == "LUT":
        explicit_source = any(key in os.environ for key in (
            "LUMINA_LUT_REGISTRY_URL", "LUMINA_MATERIAL_REGISTRY_URL",
        ))
        if not explicit_source:
            return ""
        if "LUMINA_LUT_REGISTRY_TOKEN" in os.environ:
            return os.environ["LUMINA_LUT_REGISTRY_TOKEN"].strip()
        if lut_registry_url() != material_registry_url():
            return ""
    if "LUMINA_MATERIAL_REGISTRY_URL" not in os.environ:
        return ""
    return os.environ.get("LUMINA_MATERIAL_REGISTRY_TOKEN", "").strip()
