"""Property-based tests for Session Store CRUD consistency (Property 1).

Uses Hypothesis to verify create/get/put operations consistency and UUID4 format.

**Validates: Requirements 1.1, 1.2, 1.3**
"""

import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

from api.session_store import SessionStore

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Keys: non-empty strings (session data field names)
session_keys = st.text(min_size=1, max_size=50)

# Values: simple JSON-serializable types that SessionStore might hold
simple_values = st.one_of(
    st.text(max_size=100),
    st.integers(min_value=-(2**31), max_value=2**31),
    st.floats(allow_nan=False, allow_infinity=False),
    st.booleans(),
)

# Dictionaries of key-value pairs for multi-put tests
kv_dicts = st.dictionaries(
    keys=session_keys,
    values=simple_values,
    min_size=1,
    max_size=20,
)


# ---------------------------------------------------------------------------
# Property 1: Session Store CRUD Consistency
# ---------------------------------------------------------------------------


# **Validates: Requirements 1.1, 1.2, 1.3**
@given(data=st.data())
@settings(max_examples=100)
def test_create_returns_valid_uuid4(data: st.DataObject) -> None:
    """create() returns a valid UUID4 format string."""
    store = SessionStore()
    session_id = store.create()

    # Must be a valid UUID4
    parsed = uuid.UUID(session_id, version=4)
    assert str(parsed) == session_id
    assert parsed.version == 4


# **Validates: Requirements 1.1, 1.2, 1.3**
@given(data=st.data())
@settings(max_examples=100)
def test_create_then_get_returns_empty_dict(data: st.DataObject) -> None:
    """create() followed by get() returns an empty dict {}."""
    store = SessionStore()
    session_id = store.create()

    result = store.get(session_id)
    assert result is not None
    assert result == {}


# **Validates: Requirements 1.1, 1.2, 1.3**
@given(key=session_keys, value=simple_values)
@settings(max_examples=200)
def test_put_then_get_consistency(key: str, value: object) -> None:
    """put(sid, k, v) then get(sid)[k] == v for arbitrary k, v."""
    store = SessionStore()
    session_id = store.create()

    store.put(session_id, key, value)
    result = store.get(session_id)

    assert result is not None
    assert key in result
    assert result[key] == value


# **Validates: Requirements 1.1, 1.2, 1.3**
@given(kv=kv_dicts)
@settings(max_examples=200)
def test_multiple_puts_all_retrievable(kv: dict) -> None:
    """Multiple put() calls with different keys -- all retrievable via get()."""
    store = SessionStore()
    session_id = store.create()

    for k, v in kv.items():
        store.put(session_id, k, v)

    result = store.get(session_id)
    assert result is not None

    for k, v in kv.items():
        assert k in result, f"Key {k!r} missing after put"
        assert result[k] == v, (
            f"Value mismatch for key {k!r}: expected {v!r}, got {result[k]!r}"
        )


# **Validates: Requirements 1.1, 1.2, 1.3**
@given(data=st.data())
@settings(max_examples=100)
def test_exists_after_create(data: st.DataObject) -> None:
    """exists() returns True after create()."""
    store = SessionStore()
    session_id = store.create()

    assert store.exists(session_id) is True
