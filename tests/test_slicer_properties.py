# -*- coding: utf-8 -*-
"""Property-based tests for slicer detection and launch.

Uses Hypothesis to verify correctness properties across arbitrary inputs.
Tests core/slicer.py business logic and api/routers/slicer.py endpoints.
"""

import os
import tempfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from core.slicer import (
    KNOWN_SLICERS,
    DetectedSlicer,
    _match_slicer_id,
    detect_installed_slicers,
    launch_slicer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app():
    """Build a minimal FastAPI app with only the slicer router."""
    from fastapi import FastAPI
    from api.routers.slicer import router
    app = FastAPI()
    app.include_router(router)
    return app


def _make_client() -> TestClient:
    return TestClient(_make_app())


# Known slicer IDs for exclusion in Property 2
_KNOWN_IDS = set(KNOWN_SLICERS.keys())

# All match keywords from KNOWN_SLICERS (lowercased)
_ALL_MATCH_KEYWORDS: list[tuple[str, str, str]] = []
for sid, info in KNOWN_SLICERS.items():
    for kw in info["match"]:
        _ALL_MATCH_KEYWORDS.append((kw, sid, info["display_name"]))


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Strategy for generating random slicer IDs that are NOT in KNOWN_SLICERS
unknown_slicer_ids = st.text(min_size=1, max_size=50).filter(
    lambda s: s not in _KNOWN_IDS
)

# Strategy for random file paths that almost certainly don't exist
random_file_paths = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="/_-."),
    min_size=5,
    max_size=100,
).map(lambda s: f"/nonexistent_test_dir/{s}")


# =========================================================================
# Property 1: 不存在的 exe_path 被过滤
# Feature: slicer-integration, Property 1: Non-existent exe paths filtered
# **Validates: Requirements 1.5**
# =========================================================================

@given(
    num_valid=st.integers(min_value=0, max_value=5),
    num_invalid=st.integers(min_value=0, max_value=5),
)
@settings(max_examples=100)
def test_nonexistent_exe_paths_filtered(num_valid: int, num_invalid: int) -> None:
    """Property 1: For any list of DetectedSlicer entries where some exe_paths
    point to existing temp files and some to non-existent paths,
    detect_installed_slicers() SHALL return only entries with existing exe_paths.

    **Validates: Requirements 1.5**
    """
    assume(num_valid + num_invalid > 0)

    valid_files: list[str] = []
    mock_slicers: list[DetectedSlicer] = []

    # Create temp files for "valid" entries
    tmp_handles = []
    for i in range(num_valid):
        fd, path = tempfile.mkstemp(suffix=".exe")
        os.close(fd)
        tmp_handles.append(path)
        valid_files.append(path)
        mock_slicers.append(
            DetectedSlicer(id=f"valid_{i}", display_name=f"Valid {i}", exe_path=path)
        )

    # Add "invalid" entries with non-existent paths
    for i in range(num_invalid):
        fake_path = f"/nonexistent_slicer_path_{i}/slicer_{i}.exe"
        mock_slicers.append(
            DetectedSlicer(id=f"invalid_{i}", display_name=f"Invalid {i}", exe_path=fake_path)
        )

    try:
        with patch("core.slicer.scan_registry", return_value=mock_slicers):
            result = detect_installed_slicers()

        # Every returned entry must have an existing exe_path
        for s in result:
            assert os.path.isfile(s.exe_path), (
                f"detect_installed_slicers returned entry with non-existent "
                f"exe_path: {s.exe_path}"
            )

        # Count must match the number of valid entries
        assert len(result) == num_valid, (
            f"Expected {num_valid} valid entries, got {len(result)}"
        )
    finally:
        # Cleanup temp files
        for path in tmp_handles:
            try:
                os.unlink(path)
            except OSError:
                pass


# =========================================================================
# Property 2: 未知 slicer_id 返回错误
# Feature: slicer-integration, Property 2: Unknown slicer_id returns error
# **Validates: Requirements 2.2**
# =========================================================================

@given(slicer_id=unknown_slicer_ids)
@settings(max_examples=100)
def test_unknown_slicer_id_returns_error(slicer_id: str) -> None:
    """Property 2: For any slicer_id string NOT in the known slicer list,
    launch_slicer() SHALL return (False, non-empty message).

    **Validates: Requirements 2.2**
    """
    # Create a real temp file so the "file not found" check doesn't trigger first
    fd, tmp_file = tempfile.mkstemp(suffix=".3mf")
    os.close(fd)

    try:
        # Use an empty known_slicers list — the unknown ID won't match anything
        ok, msg = launch_slicer(slicer_id, tmp_file, [])
        assert ok is False, (
            f"launch_slicer should return False for unknown slicer_id={slicer_id!r}"
        )
        assert isinstance(msg, str) and len(msg) > 0, (
            f"launch_slicer should return a non-empty error message, got: {msg!r}"
        )
    finally:
        os.unlink(tmp_file)


# =========================================================================
# Property 3: 不存在的文件路径返回错误
# Feature: slicer-integration, Property 3: Non-existent file_path returns error
# **Validates: Requirements 2.3**
# =========================================================================

@given(file_path=random_file_paths)
@settings(max_examples=100)
def test_nonexistent_file_path_returns_error(file_path: str) -> None:
    """Property 3: For any file_path that does not exist on the filesystem,
    POST /api/slicer/launch SHALL return an error status response.

    **Validates: Requirements 2.3**
    """
    assume(not os.path.isfile(file_path))

    client = _make_client()
    resp = client.post("/api/slicer/launch", json={
        "slicer_id": "bambu_studio",
        "file_path": file_path,
    })

    # Should be 400 (file not found) — not 200
    assert resp.status_code == 400, (
        f"Expected 400 for non-existent file_path={file_path!r}, "
        f"got {resp.status_code}"
    )
    data = resp.json()
    assert data["status"] == "error", (
        f"Expected status='error', got {data['status']!r}"
    )


# =========================================================================
# Property 4: 无效请求体返回 422
# Feature: slicer-integration, Property 4: Invalid request body returns 422
# **Validates: Requirements 3.6, 6.5, 6.6**
# =========================================================================

# Strategy: generate JSON dicts that are invalid for SlicerLaunchRequest
_invalid_body_strategy = st.one_of(
    # Missing both required fields
    st.fixed_dictionaries({}),
    # Missing file_path
    st.fixed_dictionaries({"slicer_id": st.text(min_size=1, max_size=20)}),
    # Missing slicer_id
    st.fixed_dictionaries({"file_path": st.text(min_size=1, max_size=50)}),
    # Wrong type for slicer_id (number instead of string)
    st.fixed_dictionaries({
        "slicer_id": st.integers(),
        "file_path": st.text(min_size=1, max_size=50),
    }),
    # Wrong type for file_path (number instead of string)
    st.fixed_dictionaries({
        "slicer_id": st.text(min_size=1, max_size=20),
        "file_path": st.integers(),
    }),
    # Empty string for file_path (violates min_length=1)
    st.just({"slicer_id": "test", "file_path": ""}),
    # Completely random keys
    st.dictionaries(
        keys=st.text(min_size=1, max_size=10).filter(
            lambda k: k not in ("slicer_id", "file_path")
        ),
        values=st.one_of(st.text(max_size=20), st.integers(), st.booleans()),
        min_size=0,
        max_size=3,
    ),
)


@given(body=_invalid_body_strategy)
@settings(max_examples=100)
def test_invalid_request_body_returns_422(body: dict) -> None:
    """Property 4: For any JSON dict that is missing required fields or has
    wrong types, POST /api/slicer/launch SHALL return HTTP 422.

    **Validates: Requirements 3.6, 6.5, 6.6**
    """
    # Skip bodies that accidentally form a valid request
    if (
        isinstance(body.get("slicer_id"), str)
        and isinstance(body.get("file_path"), str)
        and len(body.get("file_path", "")) >= 1
    ):
        assume(False)

    client = _make_client()
    resp = client.post("/api/slicer/launch", json=body)

    assert resp.status_code == 422, (
        f"Expected 422 for invalid body {body!r}, got {resp.status_code}"
    )


# =========================================================================
# Property 5: 注册表匹配产生正确名称
# Feature: slicer-integration, Property 5: Registry match produces correct display_name
# **Validates: Requirements 1.4**
# =========================================================================

# Strategy: pick a known keyword and wrap it with random prefix/suffix
_keyword_strategy = st.sampled_from(_ALL_MATCH_KEYWORDS)
_padding_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
    min_size=0,
    max_size=20,
)


@given(
    keyword_info=_keyword_strategy,
    prefix=_padding_text,
    suffix=_padding_text,
)
@settings(max_examples=100)
def test_registry_match_produces_correct_display_name(
    keyword_info: tuple[str, str, str],
    prefix: str,
    suffix: str,
) -> None:
    """Property 5: For any DisplayName string containing a known slicer keyword,
    _match_slicer_id() SHALL return the correct display_name from KNOWN_SLICERS.

    **Validates: Requirements 1.4**
    """
    keyword, expected_sid, expected_display_name = keyword_info

    # Build a DisplayName that contains the keyword
    display_name = f"{prefix} {keyword} {suffix}".strip()

    # Skip CUDA/NVIDIA false positives for "cura" keyword
    dn_lower = display_name.lower()
    if expected_sid == "cura" and ("cuda" in dn_lower or "nvidia" in dn_lower):
        assume(False)

    result = _match_slicer_id(display_name)

    assert result is not None, (
        f"_match_slicer_id({display_name!r}) returned None, "
        f"expected match for keyword={keyword!r}"
    )

    matched_sid, matched_display_name = result
    assert matched_display_name == expected_display_name, (
        f"Expected display_name={expected_display_name!r}, "
        f"got {matched_display_name!r} for input={display_name!r}"
    )


# =========================================================================
# Feature: slicer-launch-integration
# Property 1: GenerateResponse 包含 3MF 磁盘路径
# **Validates: Requirements 1.1, 7.1, 7.2**
# =========================================================================

from api.schemas.responses import GenerateResponse


# Strategy: non-empty strings representing arbitrary 3MF disk paths
_nonempty_path_strategy = st.text(min_size=1).filter(lambda s: s.strip() != "")


@given(path=_nonempty_path_strategy)
@settings(max_examples=200)
def test_generate_response_contains_threemf_disk_path(path: str) -> None:
    """Property 1: For any successful 3MF generation where generate_final_model
    returns a valid threemf_path, GenerateResponse.threemf_disk_path SHALL equal
    that path and be a non-empty string.

    Feature: slicer-launch-integration, Property 1: GenerateResponse 包含 3MF 磁盘路径
    **Validates: Requirements 1.1, 7.1, 7.2**
    """
    resp = GenerateResponse(
        status="ok",
        message="Model generated",
        download_url="/api/files/test-id",
        preview_3d_url="/api/files/preview-id",
        threemf_disk_path=path,
    )

    # threemf_disk_path must equal the input path
    assert resp.threemf_disk_path == path, (
        f"Expected threemf_disk_path={path!r}, got {resp.threemf_disk_path!r}"
    )
    # threemf_disk_path must be a non-empty string
    assert isinstance(resp.threemf_disk_path, str) and len(resp.threemf_disk_path) > 0, (
        f"threemf_disk_path should be a non-empty string, got {resp.threemf_disk_path!r}"
    )


def test_generate_response_threemf_disk_path_none_when_omitted() -> None:
    """When threemf_disk_path is not provided, it should default to None.

    Feature: slicer-launch-integration, Property 1: GenerateResponse 包含 3MF 磁盘路径
    **Validates: Requirements 1.1, 7.1, 7.2**
    """
    resp = GenerateResponse(
        status="ok",
        message="Model generated",
        download_url="/api/files/test-id",
    )
    assert resp.threemf_disk_path is None, (
        f"Expected threemf_disk_path=None when omitted, got {resp.threemf_disk_path!r}"
    )


@given(path=st.none())
@settings(max_examples=50)
def test_generate_response_threemf_disk_path_explicit_none(path) -> None:
    """When threemf_disk_path is explicitly set to None, the field should be None.

    Feature: slicer-launch-integration, Property 1: GenerateResponse 包含 3MF 磁盘路径
    **Validates: Requirements 1.1, 7.1, 7.2**
    """
    resp = GenerateResponse(
        status="ok",
        message="Model generated",
        download_url="/api/files/test-id",
        threemf_disk_path=path,
    )
    assert resp.threemf_disk_path is None, (
        f"Expected threemf_disk_path=None, got {resp.threemf_disk_path!r}"
    )
