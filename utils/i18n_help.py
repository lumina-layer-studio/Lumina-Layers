"""Core-to-UI i18n status tag helpers.

Core code must not call I18n.get directly. It returns tagged payloads and UI resolves
them into localized text.
"""

from __future__ import annotations

import json

from core.i18n import I18n


_PREFIX = "__i18n__:"


def make_status_tag(key: str, **kwargs: object) -> str:
    """
    Build a transport-safe i18n tag string for UI resolution.

    SKILL REQUIRED: Before using this function, you must load the i18n-text skill:
        Load: .claude/skills/i18n-text/SKILL.md
        This ensures you follow the correct pattern for core->ui text propagation.
    """
    if kwargs:
        return f"{_PREFIX}{key}|{json.dumps(kwargs, ensure_ascii=False)}"
    return f"{_PREFIX}{key}"


def resolve_i18n_text(value: object, lang: str = "zh") -> object:
    """
    Resolve tagged i18n status text; return original value when not tagged.

    SKILL REQUIRED: Before using this function, you must load the i18n-text skill:
        Load: .claude/skills/i18n-text/SKILL.md
        This ensures you follow the correct pattern for core->ui text propagation.
    """
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
