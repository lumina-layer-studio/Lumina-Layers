"""Property-based tests for image crop functionality.

Uses Hypothesis to verify correctness properties across arbitrary inputs.

- Property 3: CropRegion.clamp boundary invariant
- Property 4: Crop endpoint response completeness
"""

from __future__ import annotations

import io
import os
import sys

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from fastapi.testclient import TestClient
from PIL import Image

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.image_preprocessor import CropRegion
from api.app import app
from api.dependencies import get_file_registry
from api.file_registry import FileRegistry

# Isolated registry to avoid cross-test pollution
_test_registry: FileRegistry = FileRegistry()
app.dependency_overrides[get_file_registry] = lambda: _test_registry

client: TestClient = TestClient(app)


# ============================================================================
# Property 3: CropRegion.clamp boundary invariant
# Feature: image-crop-refactor, Property 3: CropRegion.clamp 边界不变量
# **Validates: Requirements 5.4**
# ============================================================================

@settings(max_examples=200)
@given(
    img_w=st.integers(min_value=1, max_value=5000),
    img_h=st.integers(min_value=1, max_value=5000),
    x=st.integers(min_value=-10000, max_value=10000),
    y=st.integers(min_value=-10000, max_value=10000),
    w=st.integers(min_value=-10000, max_value=10000),
    h=st.integers(min_value=-10000, max_value=10000),
)
def test_clamp_boundary_invariant(
    img_w: int, img_h: int, x: int, y: int, w: int, h: int
) -> None:
    """Property 3: CropRegion.clamp boundary invariant

    For any image dimensions (img_w, img_h) >= 1 and any integer crop
    coordinates (x, y, w, h), CropRegion(x, y, w, h).clamp(img_w, img_h)
    must return a region satisfying:
        0 <= cx < img_w
        0 <= cy < img_h
        1 <= cw <= img_w - cx
        1 <= ch <= img_h - cy

    Validates: Requirements 5.4
    """
    region = CropRegion(x, y, w, h)
    clamped = region.clamp(img_w, img_h)

    cx, cy, cw, ch = clamped.x, clamped.y, clamped.width, clamped.height

    # x in [0, img_w - 1)
    assert 0 <= cx < img_w, (
        f"cx={cx} out of range [0, {img_w}). "
        f"Input: img=({img_w}x{img_h}), crop=({x},{y},{w},{h})"
    )

    # y in [0, img_h - 1)
    assert 0 <= cy < img_h, (
        f"cy={cy} out of range [0, {img_h}). "
        f"Input: img=({img_w}x{img_h}), crop=({x},{y},{w},{h})"
    )

    # width in [1, img_w - cx]
    assert 1 <= cw <= img_w - cx, (
        f"cw={cw} out of range [1, {img_w - cx}]. "
        f"Input: img=({img_w}x{img_h}), crop=({x},{y},{w},{h}), cx={cx}"
    )

    # height in [1, img_h - cy]
    assert 1 <= ch <= img_h - cy, (
        f"ch={ch} out of range [1, {img_h - cy}]. "
        f"Input: img=({img_w}x{img_h}), crop=({x},{y},{w},{h}), cy={cy}"
    )


# ============================================================================
# Property 4: Crop endpoint response completeness
# Feature: image-crop-refactor, Property 4: 裁剪端点响应完整性
# **Validates: Requirements 5.3**
# ============================================================================

def _make_test_png(width: int = 100, height: int = 80) -> io.BytesIO:
    """Create a small RGB PNG image in memory."""
    arr = np.random.randint(0, 256, (height, width, 3), dtype=np.uint8)
    img = Image.fromarray(arr, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


@settings(max_examples=100)
@given(
    x=st.integers(min_value=-500, max_value=500),
    y=st.integers(min_value=-500, max_value=500),
    w=st.integers(min_value=1, max_value=500),
    h=st.integers(min_value=1, max_value=500),
)
def test_crop_endpoint_response_completeness(
    x: int, y: int, w: int, h: int
) -> None:
    """Property 4: Crop endpoint response completeness

    For any valid image file and any crop coordinates, POST /api/convert/crop
    must return JSON containing:
        - status field
        - cropped_url starting with /api/files/
        - width >= 1
        - height >= 1

    Note: The endpoint enforces width >= 1 and height >= 1 via Form(ge=1),
    so we only generate w, h >= 1 here.

    Validates: Requirements 5.3
    """
    buf = _make_test_png(100, 80)

    response = client.post(
        "/api/convert/crop",
        files={"image": ("test.png", buf, "image/png")},
        data={
            "x": str(x),
            "y": str(y),
            "width": str(w),
            "height": str(h),
        },
    )

    assert response.status_code == 200, (
        f"Expected 200, got {response.status_code}. "
        f"Coords: ({x},{y},{w},{h}), body: {response.text}"
    )

    body = response.json()

    # status field present
    assert "status" in body, f"Missing 'status' field. Body: {body}"

    # cropped_url starts with /api/files/
    assert "cropped_url" in body, f"Missing 'cropped_url' field. Body: {body}"
    assert body["cropped_url"].startswith("/api/files/"), (
        f"cropped_url does not start with /api/files/: {body['cropped_url']}"
    )

    # width >= 1
    assert "width" in body, f"Missing 'width' field. Body: {body}"
    assert body["width"] >= 1, f"width < 1: {body['width']}"

    # height >= 1
    assert "height" in body, f"Missing 'height' field. Body: {body}"
    assert body["height"] >= 1, f"height < 1: {body['height']}"
