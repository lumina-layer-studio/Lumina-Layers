"""Property-based tests for SessionStore.clear_all() consistency (Property 2).

Feature: about-page-cache-cleanup, Property 2: SessionStore 清空一致性

Uses Hypothesis to verify:
- After clear_all(), all session data is cleared (_store, _timestamps, _temp_files are empty)
- clear_all() returns the number of sessions that existed before the call

**Validates: Requirements 3.3**
"""

import os
import tempfile

from hypothesis import given, settings
from hypothesis import strategies as st

from api.session_store import SessionStore

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Number of sessions to create: 0 to 20
session_counts = st.integers(min_value=0, max_value=20)

# Number of temp files per session: 0 to 5
temp_file_counts = st.integers(min_value=0, max_value=5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_temp_file() -> str:
    """Create a real temporary file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".tmp")
    try:
        os.write(fd, b"session-temp-content")
    finally:
        os.close(fd)
    return path


# ---------------------------------------------------------------------------
# Property 2: SessionStore 清空一致性
# ---------------------------------------------------------------------------


# **Validates: Requirements 3.3**
@given(
    n=session_counts,
    temp_counts=st.lists(temp_file_counts, min_size=20, max_size=20),
)
@settings(max_examples=100)
def test_clear_all_empties_store_and_returns_session_count(
    n: int, temp_counts: list[int]
) -> None:
    """Feature: about-page-cache-cleanup, Property 2: SessionStore 清空一致性

    For any SessionStore with 0..N sessions, each with arbitrary temp files,
    clear_all() must:
    1. Leave _store empty
    2. Leave _timestamps empty
    3. Leave _temp_files empty
    4. Return the number of sessions that existed before the call
    """
    store = SessionStore()
    all_temp_paths: list[str] = []

    try:
        # Create n sessions, each with a random number of temp files
        for i in range(n):
            sid = store.create()
            for _ in range(temp_counts[i]):
                path = _create_temp_file()
                all_temp_paths.append(path)
                store.register_temp_file(sid, path)

        sessions_before = len(store._store)
        assert sessions_before == n

        result = store.clear_all()

        # Property: _store must be empty after clear_all()
        assert len(store._store) == 0

        # Property: _timestamps must be empty after clear_all()
        assert len(store._timestamps) == 0

        # Property: _temp_files must be empty after clear_all()
        assert len(store._temp_files) == 0

        # Property: return value equals the count of sessions before clear_all()
        assert result == sessions_before
    finally:
        # Clean up any temp files that clear_all() may not have removed
        for p in all_temp_paths:
            if os.path.exists(p):
                os.unlink(p)
