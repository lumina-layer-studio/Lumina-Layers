"""Property-based tests for File Registry register/resolve consistency (Property 4).

Uses Hypothesis to verify:
- register_path() returns valid UUID4
- resolve(file_id) returns (path, filename) consistent with registration
- resolve(unknown_id) returns None
- cleanup_session() invalidates all file_ids for that session

**Validates: Requirements 1.2**
"""

import os
import tempfile
import uuid

from hypothesis import given, settings
from hypothesis import strategies as st

from api.file_registry import FileRegistry

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Session IDs: non-empty printable strings
session_ids = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P")),
    min_size=1,
    max_size=30,
)

# Filenames: simple alphanumeric names with common extensions
_extensions = st.sampled_from([".3mf", ".glb", ".png", ".jpg", ".npy", ".npz", ".zip", ".bin"])
filenames = st.builds(
    lambda name, ext: name + ext,
    name=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=20,
    ),
    ext=_extensions,
)


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
# Property 4: File Registry Register/Resolve Consistency
# ---------------------------------------------------------------------------


# **Validates: Requirements 1.2**
@given(sid=session_ids, filename=filenames)
@settings(max_examples=100)
def test_register_path_returns_valid_uuid4(sid: str, filename: str) -> None:
    """register_path() returns a valid UUID4 format string."""
    registry = FileRegistry()
    path = _create_temp_file()
    try:
        file_id = registry.register_path(sid, path, filename)

        parsed = uuid.UUID(file_id, version=4)
        assert str(parsed) == file_id
        assert parsed.version == 4
    finally:
        os.unlink(path)


# **Validates: Requirements 1.2**
@given(sid=session_ids, filename=filenames)
@settings(max_examples=100)
def test_register_resolve_consistency(sid: str, filename: str) -> None:
    """register_path(sid, path, filename) then resolve(file_id) returns (path, filename)."""
    registry = FileRegistry()
    path = _create_temp_file()
    try:
        file_id = registry.register_path(sid, path, filename)

        result = registry.resolve(file_id)
        assert result is not None

        resolved_path, resolved_filename = result
        assert resolved_path == path
        assert resolved_filename == filename
    finally:
        os.unlink(path)


# **Validates: Requirements 1.2**
@given(unknown_id=st.uuids().map(str))
@settings(max_examples=100)
def test_resolve_unknown_id_returns_none(unknown_id: str) -> None:
    """resolve() with a random UUID that was never registered returns None."""
    registry = FileRegistry()

    result = registry.resolve(unknown_id)
    assert result is None


# **Validates: Requirements 1.2**
@given(
    sid=session_ids,
    file_data=st.lists(filenames, min_size=1, max_size=5),
)
@settings(max_examples=50)
def test_cleanup_session_invalidates_file_ids(
    sid: str, file_data: list[str]
) -> None:
    """After cleanup_session(), all file_ids for that session resolve to None."""
    registry = FileRegistry()
    temp_paths: list[str] = []
    file_ids: list[str] = []

    try:
        for fname in file_data:
            path = _create_temp_file()
            temp_paths.append(path)
            fid = registry.register_path(sid, path, fname)
            file_ids.append(fid)

        # All file_ids should resolve before cleanup
        for fid in file_ids:
            assert registry.resolve(fid) is not None

        # Cleanup the session
        cleaned = registry.cleanup_session(sid)
        assert cleaned == len(file_ids)

        # All file_ids should resolve to None after cleanup
        for fid in file_ids:
            assert registry.resolve(fid) is None
    finally:
        for p in temp_paths:
            if os.path.exists(p):
                os.unlink(p)
