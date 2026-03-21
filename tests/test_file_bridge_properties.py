"""Property-based tests for File Bridge image roundtrip consistency (Property 3).

Uses Hypothesis to generate random RGB ndarrays and verify PNG encode/decode
roundtrip preserves pixel values exactly (PNG is lossless).

**Validates: Requirements 2.1, 2.3**
"""

import io

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from hypothesis.extra.numpy import arrays
from PIL import Image

from api.file_bridge import ndarray_to_png_bytes, pil_to_png_bytes

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Random RGB ndarrays with small dimensions to keep tests fast
rgb_arrays = arrays(
    dtype=np.uint8,
    shape=st.tuples(
        st.integers(min_value=1, max_value=50),
        st.integers(min_value=1, max_value=50),
        st.just(3),
    ),
)


# ---------------------------------------------------------------------------
# Property 3: File Bridge Image Roundtrip Consistency
# ---------------------------------------------------------------------------


# **Validates: Requirements 2.1, 2.3**
@given(arr=rgb_arrays)
@settings(max_examples=200)
def test_ndarray_png_roundtrip(arr: np.ndarray) -> None:
    """ndarray -> PNG bytes -> PIL Image -> ndarray roundtrip preserves pixels.

    For any valid RGB ndarray (H, W, 3, uint8), encoding to PNG via
    ndarray_to_png_bytes() and decoding back must yield identical pixel values.
    The result dtype must be uint8 and shape must be (H, W, 3).
    """
    png_bytes = ndarray_to_png_bytes(arr)

    # Decode back
    decoded_img = Image.open(io.BytesIO(png_bytes))
    decoded_arr = np.array(decoded_img, dtype=np.uint8)

    assert decoded_arr.dtype == np.uint8
    assert decoded_arr.shape == arr.shape
    np.testing.assert_array_equal(decoded_arr, arr)


# **Validates: Requirements 2.1, 2.3**
@given(arr=rgb_arrays)
@settings(max_examples=200)
def test_pil_png_roundtrip(arr: np.ndarray) -> None:
    """PIL Image -> PNG bytes -> PIL Image roundtrip preserves pixels.

    For any valid RGB PIL Image, encoding to PNG via pil_to_png_bytes()
    and decoding back must yield identical pixel values.
    """
    original_img = Image.fromarray(arr, mode="RGB")

    png_bytes = pil_to_png_bytes(original_img)

    # Decode back
    decoded_img = Image.open(io.BytesIO(png_bytes))
    decoded_arr = np.array(decoded_img, dtype=np.uint8)
    original_arr = np.array(original_img, dtype=np.uint8)

    assert decoded_arr.dtype == np.uint8
    assert decoded_arr.shape == original_arr.shape
    np.testing.assert_array_equal(decoded_arr, original_arr)
