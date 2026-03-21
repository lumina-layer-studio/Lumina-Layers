# -*- coding: utf-8 -*-
"""
Property-based tests for HEIC format support fix.

Validates that the SUPPORTED_IMAGE_FILE_TYPES constant in ui/layout_new.py
is complete and well-formed.
"""

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from ui.layout_new import SUPPORTED_IMAGE_FILE_TYPES


# ── Required formats that MUST be present ──────────────────────────────
REQUIRED_EXTENSIONS: list[str] = [
    ".jpg", ".jpeg", ".png", ".bmp",
    ".gif", ".webp", ".heic", ".heif",
]


# ── Property 1: Format list completeness ───────────────────────────────
# **Validates: Requirements 1.3, 6.1**
@given(ext=st.sampled_from(REQUIRED_EXTENSIONS))
@settings(max_examples=100)
def test_required_format_present(ext: str) -> None:
    """Every required image extension must be in SUPPORTED_IMAGE_FILE_TYPES.

    **Validates: Requirements 1.3, 6.1**
    """
    assert ext in SUPPORTED_IMAGE_FILE_TYPES, (
        f"Required extension {ext!r} missing from SUPPORTED_IMAGE_FILE_TYPES"
    )


# ── Property 2: Extension format correctness ──────────────────────────
# **Validates: Requirements 6.1**
@given(ext=st.sampled_from(SUPPORTED_IMAGE_FILE_TYPES))
@settings(max_examples=100)
def test_extension_format_valid(ext: str) -> None:
    """Every entry must start with '.' and be all lowercase.

    **Validates: Requirements 6.1**
    """
    assert ext.startswith("."), (
        f"Extension {ext!r} does not start with '.'"
    )
    assert ext == ext.lower(), (
        f"Extension {ext!r} is not all lowercase"
    )
    assert re.fullmatch(r"\.[a-z0-9]+", ext), (
        f"Extension {ext!r} contains invalid characters"
    )


# ── Unit: no duplicates ───────────────────────────────────────────────
def test_no_duplicate_extensions() -> None:
    """SUPPORTED_IMAGE_FILE_TYPES must not contain duplicates."""
    assert len(SUPPORTED_IMAGE_FILE_TYPES) == len(set(SUPPORTED_IMAGE_FILE_TYPES))
