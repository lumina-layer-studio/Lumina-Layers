"""Property-based tests for MIME type inference correctness (Property 10).

Verifies that _guess_media_type() returns the correct MIME type for all known
file extensions, falls back to application/octet-stream for unknown extensions,
and handles case-insensitive matching.

**Validates: Requirements 2.4**
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from api.file_bridge import _guess_media_type

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXPECTED_MIME: dict[str, str] = {
    ".3mf": "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
    ".glb": "model/gltf-binary",
    ".zip": "application/zip",
    ".npy": "application/octet-stream",
    ".npz": "application/octet-stream",
    ".png": "image/png",
    ".jpg": "image/jpeg",
}

KNOWN_EXTENSIONS: list[str] = list(EXPECTED_MIME.keys())

# Extensions that should NOT match any known mapping
UNKNOWN_EXTENSIONS: list[str] = [
    ".txt", ".csv", ".pdf", ".doc", ".html", ".xml", ".yaml",
    ".mp3", ".mp4", ".avi", ".bmp", ".tiff", ".webp", ".obj",
]

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Random filename base: non-empty alphanumeric strings
filename_bases = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N")),
    min_size=1,
    max_size=30,
)

# Random unknown extensions: dot + 1-6 lowercase letters, filtered to exclude known
random_unknown_ext = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz",
    min_size=1,
    max_size=6,
).map(lambda s: f".{s}").filter(lambda e: e not in EXPECTED_MIME)


# ---------------------------------------------------------------------------
# Property 10: MIME type inference correctness
# ---------------------------------------------------------------------------


# **Validates: Requirements 2.4**
@given(ext=st.sampled_from(KNOWN_EXTENSIONS), base=filename_bases)
@settings(max_examples=200)
def test_known_extensions_return_correct_mime(ext: str, base: str) -> None:
    """For all known extensions, _guess_media_type returns the expected MIME type.

    Property: _guess_media_type("file" + ext) == expected_mime[ext]
    """
    path = f"{base}{ext}" if base else f"file{ext}"
    result = _guess_media_type(path)
    assert result == EXPECTED_MIME[ext], (
        f"Extension {ext!r}: expected {EXPECTED_MIME[ext]!r}, got {result!r}"
    )


# **Validates: Requirements 2.4**
@given(ext=random_unknown_ext, base=filename_bases)
@settings(max_examples=200)
def test_unknown_extensions_return_octet_stream(ext: str, base: str) -> None:
    """For unknown extensions, _guess_media_type falls back to application/octet-stream."""
    path = f"{base}{ext}" if base else f"file{ext}"
    result = _guess_media_type(path)
    assert result == "application/octet-stream", (
        f"Unknown extension {ext!r}: expected 'application/octet-stream', got {result!r}"
    )


# **Validates: Requirements 2.4**
@given(ext=st.sampled_from(KNOWN_EXTENSIONS), base=filename_bases)
@settings(max_examples=200)
def test_case_insensitive(ext: str, base: str) -> None:
    """Extensions with mixed case should still return correct MIME types.

    The implementation calls .lower() on the extension, so ".PNG", ".Jpg" etc.
    should all resolve correctly.
    """
    # Test uppercase variant
    upper_path = f"{base}{ext.upper()}"
    assert _guess_media_type(upper_path) == EXPECTED_MIME[ext], (
        f"Uppercase {ext.upper()!r} should match {EXPECTED_MIME[ext]!r}"
    )

    # Test mixed-case variant (capitalize first letter after dot)
    mixed = "." + ext[1:].capitalize()
    mixed_path = f"{base}{mixed}"
    assert _guess_media_type(mixed_path) == EXPECTED_MIME[ext], (
        f"Mixed-case {mixed!r} should match {EXPECTED_MIME[ext]!r}"
    )
