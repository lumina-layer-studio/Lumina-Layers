"""Property-based tests for Session Store TTL expiration (Property 2).

Verifies that TTL=0 SessionStore cleanup_expired() removes sessions
and their registered temporary files from disk.

**Validates: Requirements 1.5, 1.6**
"""

import os
import tempfile
import time
from typing import List, Tuple

from hypothesis import given, settings
from hypothesis import strategies as st

from api.session_store import SessionStore

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

session_keys = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=20,
)

session_values = st.one_of(
    st.text(max_size=50),
    st.integers(min_value=-(2**31), max_value=2**31),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
)

kv_pairs = st.lists(
    st.tuples(session_keys, session_values),
    min_size=1,
    max_size=5,
)

temp_file_count = st.integers(min_value=1, max_value=5)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_temp_files(n: int) -> List[Tuple[str, int]]:
    """Create *n* real temporary files, return list of (path, fd)."""
    results: List[Tuple[str, int]] = []
    for _ in range(n):
        fd, path = tempfile.mkstemp(prefix="session_ttl_test_")
        os.write(fd, b"test data")
        os.close(fd)
        results.append((path, fd))
    return results


# ---------------------------------------------------------------------------
# Property 2: Session Store TTL Expiration
# ---------------------------------------------------------------------------


# **Validates: Requirements 1.5, 1.6**
@given(kvs=kv_pairs, n_files=temp_file_count)
@settings(max_examples=100)
def test_ttl_zero_cleanup_removes_session(
    kvs: List[Tuple[str, object]],
    n_files: int,
) -> None:
    """TTL=0 store: cleanup_expired() removes session, data, and temp files."""
    store = SessionStore(ttl=0)
    sid = store.create()

    # Store arbitrary key-value data
    for k, v in kvs:
        store.put(sid, k, v)

    # Create and register real temp files
    temp_paths: List[str] = []
    for path, _ in _create_temp_files(n_files):
        store.register_temp_file(sid, path)
        temp_paths.append(path)

    # Preconditions: session and files exist
    assert store.exists(sid) is True
    for p in temp_paths:
        assert os.path.exists(p), f"Temp file should exist before cleanup: {p}"

    # Small sleep so that time.time() - timestamp > 0 (TTL=0)
    time.sleep(0.01)

    # Cleanup
    count = store.cleanup_expired()
    assert count >= 1, "At least one session should be cleaned up"

    # Post-conditions: session is gone
    assert store.get(sid) is None, "get() should return None after cleanup"
    assert store.exists(sid) is False, "exists() should return False after cleanup"

    # Post-conditions: temp files are deleted from disk
    for p in temp_paths:
        assert not os.path.exists(p), f"Temp file should be deleted after cleanup: {p}"
