"""Property-based tests for FileRegistry.clear_all() consistency (Property 1).

Feature: about-page-cache-cleanup, Property 1: FileRegistry 清空一致性

Uses Hypothesis to verify:
- After clear_all(), the registry is empty (_registry length == 0)
- clear_all() returns the number of entries that existed before the call

**Validates: Requirements 3.2**
"""

import os
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from api.file_registry import FileRegistry

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

session_ids = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=30,
)

_extensions = st.sampled_from([".3mf", ".glb", ".png", ".jpg", ".bin"])
filenames = st.builds(
    lambda name, ext: name + ext,
    name=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=20,
    ),
    ext=_extensions,
)

# Number of entries to register: 0 to 15
entry_counts = st.integers(min_value=0, max_value=15)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_temp_file() -> str:
    """Create a real temporary file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".tmp")
    try:
        os.write(fd, b"test-content")
    finally:
        os.close(fd)
    return path


# ---------------------------------------------------------------------------
# Property 1: FileRegistry 清空一致性
# ---------------------------------------------------------------------------


# **Validates: Requirements 3.2**
@given(
    n=entry_counts,
    sid=session_ids,
    fnames=st.lists(filenames, min_size=15, max_size=15),
)
@settings(max_examples=100)
def test_clear_all_empties_registry_and_returns_entry_count(
    n: int, sid: str, fnames: list[str]
) -> None:
    """Feature: about-page-cache-cleanup, Property 1: FileRegistry 清空一致性

    For any FileRegistry with 0..N registered entries, clear_all() must:
    1. Leave _registry empty (length == 0)
    2. Return the number of entries that existed before the call
    """
    registry = FileRegistry()
    temp_paths: list[str] = []

    try:
        # Register n files with real temp files
        for i in range(n):
            path = _create_temp_file()
            temp_paths.append(path)
            registry.register_path(sid, path, fnames[i])

        entries_before = len(registry._registry)
        assert entries_before == n

        result = registry.clear_all()

        # Property: registry must be empty after clear_all()
        assert len(registry._registry) == 0

        # Property: return value equals the count of entries before clear_all()
        # Note: clear_all() returns count of *successfully deleted files*,
        # which equals entries_before when all files exist on disk
        assert result == entries_before
    finally:
        # Clean up any temp files that clear_all() may not have removed
        for p in temp_paths:
            if os.path.exists(p):
                os.unlink(p)
