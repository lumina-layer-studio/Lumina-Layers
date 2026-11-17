"""Bounded public source declarations; account identity is owned by Registry."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit


def normalize_attribution(value: object) -> dict[str, Any]:
    """Validate a declaration without interpreting it as proof of authorship."""
    if not isinstance(value, dict):
        raise ValueError("Resource attribution must be an object.")
    relationship = value.get("relationship")
    if not isinstance(relationship, str) or relationship not in {"original", "adapted", "redistributed"}:
        raise ValueError("Choose whether this is your calibration, an adaptation or a redistribution.")
    if relationship == "original":
        # Names and IDs for original work come from the authenticated contributor,
        # never from an editable author field in an uploaded package.
        return {"relationship": relationship}
    result: dict[str, Any] = {"relationship": relationship}
    for field, limit in (("original_author", 200), ("source_url", 2048), ("rights_basis", 1000)):
        text = value.get(field, "")
        if not isinstance(text, str) or len(text.strip()) > limit or any(
                ord(char) < 32 and not (field == "rights_basis" and char in "\r\n\t") for char in text):
            raise ValueError(f"Invalid attribution field: {field}.")
        result[field] = text.strip()
    if not result["original_author"] or not result["rights_basis"]:
        raise ValueError("Name the original author and describe the original license or permission.")
    if result["source_url"]:
        try:
            parsed = urlsplit(result["source_url"])
            valid = parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Use an HTTP(S) source link without credentials.")
    source = value.get("source")
    if source is not None:
        if not isinstance(source, dict) or not isinstance(source.get("kind"), str) or source["kind"] not in {"materials", "luts"}:
            raise ValueError("Invalid original resource reference.")
        reference = {"kind": source["kind"]}
        for field in ("resource_id", "revision_id"):
            text = source.get(field)
            if not isinstance(text, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,199}", text):
                raise ValueError("Invalid original resource identity.")
            reference[field] = text
        content_hash = source.get("content_hash")
        if not isinstance(content_hash, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", content_hash):
            raise ValueError("Invalid original resource content hash.")
        reference["content_hash"] = content_hash
        result["source"] = reference
    if not result["source_url"] and "source" not in result:
        raise ValueError("Provide the original source link.")
    return result
