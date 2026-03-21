"""Unit tests for POST /api/convert/upload-heightmap endpoint.

Validates:
- Valid image upload returns 200 with color_height_map and thumbnail_url (Requirement 8.1, 8.2)
- Invalid file format returns 422 (Requirement 8.3)
- Aspect ratio mismatch produces warnings (Requirement 8.3)
- Missing session returns 404
- Missing preview_cache returns 409
"""

from __future__ import annotations

import io
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app
from api.dependencies import get_session_store, get_file_registry
from api.session_store import SessionStore
from api.file_registry import FileRegistry

# Isolated store/registry per test module
_test_store: SessionStore = SessionStore(ttl=1800)
_test_registry: FileRegistry = FileRegistry()

app.dependency_overrides[get_session_store] = lambda: _test_store
app.dependency_overrides[get_file_registry] = lambda: _test_registry

client: TestClient = TestClient(app)


def _make_grayscale_png(width: int = 100, height: int = 100) -> io.BytesIO:
    """Create a grayscale PNG image buffer with a gradient."""
    arr = np.linspace(0, 255, width * height, dtype=np.uint8).reshape(height, width)
    img = Image.fromarray(arr, mode="L")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _make_rgb_png(width: int = 100, height: int = 100) -> io.BytesIO:
    """Create a simple RGB PNG image buffer."""
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    arr[:, :, 0] = 128  # red channel
    img = Image.fromarray(arr, mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _make_text_file() -> io.BytesIO:
    """Create a plain text file buffer (invalid image format)."""
    buf = io.BytesIO(b"this is not an image file at all")
    buf.seek(0)
    return buf


def _setup_session_with_preview(
    store: SessionStore,
    target_w: int = 100,
    target_h: int = 100,
) -> str:
    """Create a session with preview_cache containing matched_rgb and palette."""
    session_id = store.create()

    matched_rgb = np.zeros((target_h, target_w, 3), dtype=np.uint8)
    # Top half red, bottom half green
    matched_rgb[: target_h // 2, :, :] = [255, 0, 0]
    matched_rgb[target_h // 2 :, :, :] = [0, 255, 0]

    mask_solid = np.ones((target_h, target_w), dtype=bool)

    red_count = (target_h // 2) * target_w
    green_count = (target_h - target_h // 2) * target_w
    total = red_count + green_count

    palette = [
        {
            "hex": "#ff0000",
            "color": (255, 0, 0),
            "count": red_count,
            "percentage": round(red_count / total * 100, 1),
        },
        {
            "hex": "#00ff00",
            "color": (0, 255, 0),
            "count": green_count,
            "percentage": round(green_count / total * 100, 1),
        },
    ]

    cache = {
        "target_w": target_w,
        "target_h": target_h,
        "target_width_mm": 60.0,
        "matched_rgb": matched_rgb,
        "mask_solid": mask_solid,
        "color_palette": palette,
    }
    store.put(session_id, "preview_cache", cache)
    return session_id


# =========================================================================
# 1. Valid grayscale PNG upload returns 200 - Requirement 8.1, 8.2
# =========================================================================


class TestValidHeightmapUpload:
    """Verify valid heightmap upload returns 200 with expected fields."""

    def test_valid_grayscale_png_returns_200(self) -> None:
        session_id = _setup_session_with_preview(_test_store)
        buf = _make_grayscale_png(100, 100)

        response = client.post(
            "/api/convert/upload-heightmap",
            files={"heightmap": ("heightmap.png", buf, "image/png")},
            data={"session_id": session_id, "max_relief_height": "2.0"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert "color_height_map" in body
        assert isinstance(body["color_height_map"], dict)
        assert len(body["color_height_map"]) == 2
        assert "ff0000" in body["color_height_map"]
        assert "00ff00" in body["color_height_map"]

        # Heights must be within [LAYER_HEIGHT, max_relief_height]
        for hex_key, height in body["color_height_map"].items():
            assert 0.08 <= height <= 2.0, f"Height {height} out of range for {hex_key}"

        assert "thumbnail_url" in body
        assert "original_size" in body
        assert body["original_size"] == [100, 100]

    def test_valid_rgb_png_returns_200(self) -> None:
        """RGB images should also be accepted (converted to grayscale internally)."""
        session_id = _setup_session_with_preview(_test_store)
        buf = _make_rgb_png(100, 100)

        response = client.post(
            "/api/convert/upload-heightmap",
            files={"heightmap": ("heightmap.png", buf, "image/png")},
            data={"session_id": session_id},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert len(body["color_height_map"]) == 2


# =========================================================================
# 2. Invalid file format returns 422 - Requirement 8.3
# =========================================================================


class TestInvalidFormatReturns422:
    """Verify non-image file upload returns HTTP 422."""

    def test_text_file_returns_422(self) -> None:
        session_id = _setup_session_with_preview(_test_store)
        buf = _make_text_file()

        response = client.post(
            "/api/convert/upload-heightmap",
            files={"heightmap": ("notes.txt", buf, "text/plain")},
            data={"session_id": session_id},
        )

        assert response.status_code == 422
        body = response.json()
        assert "detail" in body


# =========================================================================
# 3. Aspect ratio mismatch warning - Requirement 8.3
# =========================================================================


class TestAspectRatioWarning:
    """Verify aspect ratio mismatch produces warnings in response."""

    def test_mismatched_aspect_ratio_returns_warning(self) -> None:
        """Upload 200x100 heightmap for 100x100 target -> >20% deviation."""
        session_id = _setup_session_with_preview(_test_store, target_w=100, target_h=100)
        # Heightmap is 200x100 (ratio 2.0), target is 100x100 (ratio 1.0)
        buf = _make_grayscale_png(width=200, height=100)

        response = client.post(
            "/api/convert/upload-heightmap",
            files={"heightmap": ("wide.png", buf, "image/png")},
            data={"session_id": session_id},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["warnings"]) > 0
        # Warning should mention aspect ratio deviation
        assert any("宽高比" in w or "偏差" in w for w in body["warnings"])

    def test_matching_aspect_ratio_no_warning(self) -> None:
        """Upload 100x100 heightmap for 100x100 target -> no warning."""
        session_id = _setup_session_with_preview(_test_store, target_w=100, target_h=100)
        buf = _make_grayscale_png(width=100, height=100)

        response = client.post(
            "/api/convert/upload-heightmap",
            files={"heightmap": ("square.png", buf, "image/png")},
            data={"session_id": session_id},
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body["warnings"]) == 0


# =========================================================================
# 4. Missing session returns 404
# =========================================================================


class TestMissingSessionReturns404:
    """Verify non-existent session_id returns HTTP 404."""

    def test_unknown_session_returns_404(self) -> None:
        buf = _make_grayscale_png()

        response = client.post(
            "/api/convert/upload-heightmap",
            files={"heightmap": ("hm.png", buf, "image/png")},
            data={"session_id": "nonexistent-session-id"},
        )

        assert response.status_code == 404
        assert "Session" in response.json()["detail"]


# =========================================================================
# 5. Missing preview_cache returns 409
# =========================================================================


class TestMissingPreviewCacheReturns409:
    """Verify session without preview_cache returns HTTP 409."""

    def test_no_preview_cache_returns_409(self) -> None:
        # Create session but do NOT add preview_cache
        session_id = _test_store.create()
        buf = _make_grayscale_png()

        response = client.post(
            "/api/convert/upload-heightmap",
            files={"heightmap": ("hm.png", buf, "image/png")},
            data={"session_id": session_id},
        )

        assert response.status_code == 409
        assert "preview" in response.json()["detail"].lower()
