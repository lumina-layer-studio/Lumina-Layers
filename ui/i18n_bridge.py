"""Resolve i18n tags returned from core into localized UI strings."""

from __future__ import annotations

import json

from core.i18n import I18n


_PREFIX = "__i18n__:"


def resolve_i18n_text(value: object, lang: str = "zh") -> object:
    """Resolve tagged i18n status text; return original value when not tagged."""
    if not isinstance(value, str):
        return value

    # Support multi-line payloads that may contain multiple tags.
    if "\n" in value:
        parts = [resolve_i18n_text(part, lang) for part in value.split("\n")]
        return "\n".join(str(part) for part in parts)

    if not value.startswith(_PREFIX):
        return value

    payload = value[len(_PREFIX) :]
    if "|" not in payload:
        return I18n.get(payload, lang)

    key, raw_args = payload.split("|", 1)
    text = I18n.get(key, lang)
    try:
        args = json.loads(raw_args)
        if isinstance(args, dict):
            return text.format(**args)
    except Exception:
        return text
    return text
