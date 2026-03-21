"""Property-based tests for ClearCacheResponse JSON round-trip (Property 5).

Feature: about-page-cache-cleanup, Property 5: ClearCacheResponse 序列化 round-trip

Uses Hypothesis to verify:
- Serializing a ClearCacheResponse to JSON and deserializing it back
  produces an instance equal to the original.

**Validates: Requirements 3.7**
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from api.schemas.system import CacheCleanupDetails, ClearCacheResponse

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

cache_cleanup_details_st = st.builds(
    CacheCleanupDetails,
    registry_cleaned=st.integers(min_value=0, max_value=10_000),
    sessions_cleaned=st.integers(min_value=0, max_value=10_000),
    output_files_cleaned=st.integers(min_value=0, max_value=10_000),
)

clear_cache_response_st = st.builds(
    ClearCacheResponse,
    status=st.text(min_size=0, max_size=50),
    message=st.text(min_size=0, max_size=200),
    deleted_files=st.integers(min_value=0, max_value=100_000),
    freed_bytes=st.integers(min_value=0, max_value=10**12),
    details=cache_cleanup_details_st,
)


# ---------------------------------------------------------------------------
# Property 5: ClearCacheResponse 序列化 round-trip
# ---------------------------------------------------------------------------


# **Validates: Requirements 3.7**
@given(response=clear_cache_response_st)
@settings(max_examples=100)
def test_clear_cache_response_json_round_trip(
    response: ClearCacheResponse,
) -> None:
    """Feature: about-page-cache-cleanup, Property 5: ClearCacheResponse 序列化 round-trip

    For any valid ClearCacheResponse, serializing to JSON and deserializing
    back should produce an instance equal to the original.
    """
    json_str = response.model_dump_json()
    restored = ClearCacheResponse.model_validate_json(json_str)
    assert restored == response
