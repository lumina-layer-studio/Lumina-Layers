"""Property-based tests for Session Store thread safety (Property 7).

Uses Hypothesis + concurrent.futures to verify that multi-threaded concurrent
create/put/get operations do not raise exceptions, session_ids are globally
unique, and each session's data is independent (no cross-contamination).

**Validates: Requirement 1.1**
"""

import concurrent.futures
from typing import List, Tuple

from hypothesis import given, settings
from hypothesis import strategies as st

from api.session_store import SessionStore


# ---------------------------------------------------------------------------
# Property 7: Session Store Thread Safety
# ---------------------------------------------------------------------------


# **Validates: Requirement 1.1**
@given(
    n_threads=st.integers(min_value=2, max_value=10),
    n_ops_per_thread=st.integers(min_value=5, max_value=20),
)
@settings(max_examples=50)
def test_concurrent_create_put_get_no_exceptions(
    n_threads: int, n_ops_per_thread: int
) -> None:
    """Concurrent create/put/get operations do not raise exceptions,
    and all session_ids are globally unique."""
    store = SessionStore(ttl=1800)
    errors: List[Exception] = []

    def worker(thread_id: int) -> List[str]:
        local_sids: List[str] = []
        try:
            for i in range(n_ops_per_thread):
                sid = store.create()
                local_sids.append(sid)
                store.put(sid, f"key_{thread_id}_{i}", f"value_{thread_id}_{i}")
                data = store.get(sid)
                assert data is not None, f"get() returned None for {sid}"
                assert data[f"key_{thread_id}_{i}"] == f"value_{thread_id}_{i}"
        except Exception as e:
            errors.append(e)
        return local_sids

    all_session_ids: List[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as executor:
        futures = [executor.submit(worker, tid) for tid in range(n_threads)]
        for f in concurrent.futures.as_completed(futures):
            all_session_ids.extend(f.result())

    # No exceptions raised in any thread
    assert len(errors) == 0, f"Thread errors: {errors}"

    # All session_ids are globally unique
    assert len(all_session_ids) == len(set(all_session_ids)), (
        "Duplicate session_ids detected"
    )

    # Total sessions created matches expectation
    assert len(all_session_ids) == n_threads * n_ops_per_thread


# **Validates: Requirement 1.1**
@given(n_threads=st.integers(min_value=2, max_value=8))
@settings(max_examples=50)
def test_concurrent_sessions_data_isolation(n_threads: int) -> None:
    """Each session's data is independent -- no cross-contamination
    between concurrent threads."""
    store = SessionStore(ttl=1800)
    errors: List[Tuple[int, object]] = []

    def worker(thread_id: int) -> str:
        sid = store.create()
        store.put(sid, "owner", thread_id)
        # Re-read to verify isolation
        data = store.get(sid)
        if data is None:
            errors.append((thread_id, "get() returned None"))
            return sid
        if data.get("owner") != thread_id:
            errors.append((thread_id, f"expected owner={thread_id}, got {data.get('owner')}"))
        return sid

    with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as executor:
        futures = [executor.submit(worker, tid) for tid in range(n_threads)]
        sids = [f.result() for f in futures]

    # No cross-contamination errors
    assert len(errors) == 0, f"Data isolation errors: {errors}"

    # All session_ids are unique
    assert len(sids) == len(set(sids)), "Duplicate session_ids detected"
