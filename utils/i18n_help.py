"""Core-to-UI i18n status tag helpers.

Core code must not call I18n.get directly. It returns tagged payloads and UI resolves
them into localized text.
"""

from __future__ import annotations

import json


_PREFIX = "__i18n__:"


def make_status_tag(key: str, **kwargs: object) -> str:
    """Build a transport-safe i18n tag string for UI resolution."""
    if kwargs:
        return f"{_PREFIX}{key}|{json.dumps(kwargs, ensure_ascii=False)}"
    return f"{_PREFIX}{key}"
