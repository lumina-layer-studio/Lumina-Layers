# -*- coding: utf-8 -*-
"""
Unit tests for HEIC/HEIF API layer error handling and endpoint integration.

Feature: heic-api-support
Validates: Requirements 4.1, 4.2, 1.2
"""

import asyncio
import io
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.file_bridge import (
    HAS_HEIF,
    _guess_media_type,
    ensure_png_tempfile,
)


def _make_upload_file(filename: str, content: bytes = b"fake") -> MagicMock:
    """Create a mock UploadFile with given filename and content.
    创建具有指定文件名和内容的模拟 UploadFile。
    """
    mock = MagicMock()
    mock.filename = filename
    mock.read = AsyncMock(return_value=content)
    return mock


# ── Test 1: ensure_png_tempfile raises 422 when HAS_HEIF=False ────────
# Validates: Requirement 4.1
class TestEnsurePngRaises422WhenHeifNotInstalled:
    """HAS_HEIF=False + HEIC upload → HTTP 422 with install guidance."""

    def test_heic_extension(self) -> None:
        mock_file = _make_upload_file("photo.heic")
        with patch("api.file_bridge.HAS_HEIF", False):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(ensure_png_tempfile(mock_file))
            assert exc_info.value.status_code == 422
            assert "pillow-heif" in exc_info.value.detail

    def test_heif_extension(self) -> None:
        mock_file = _make_upload_file("photo.heif")
        with patch("api.file_bridge.HAS_HEIF", False):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(ensure_png_tempfile(mock_file))
            assert exc_info.value.status_code == 422
            assert "pillow-heif" in exc_info.value.detail

    def test_uppercase_heic_extension(self) -> None:
        """Filename with .HEIC (uppercase) should also trigger 422."""
        mock_file = _make_upload_file("photo.HEIC")
        with patch("api.file_bridge.HAS_HEIF", False):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(ensure_png_tempfile(mock_file))
            assert exc_info.value.status_code == 422


# ── Test 2: HAS_HEIF flag consistency with pillow_heif install ─────────
# Validates: Requirement 1.2
class TestHasHeifFlagConsistency:
    """HAS_HEIF flag must match actual pillow_heif availability."""

    def test_flag_matches_import(self) -> None:
        try:
            import pillow_heif  # noqa: F401
            heif_available = True
        except ImportError:
            heif_available = False

        assert HAS_HEIF is heif_available, (
            f"HAS_HEIF={HAS_HEIF} but pillow_heif importable={heif_available}"
        )


# ── Test 3: _guess_media_type unknown extension → default ──────────────
# Validates: Requirement 2.1, 2.2 (inverse — unknown ext)
class TestGuessMediaTypeUnknown:
    """Unknown extensions return application/octet-stream."""

    def test_unknown_extension_returns_default(self) -> None:
        assert _guess_media_type("/tmp/file.xyz") == "application/octet-stream"

    def test_no_extension_returns_default(self) -> None:
        assert _guess_media_type("/tmp/noext") == "application/octet-stream"


# ── Test 4 & 5: _guess_media_type HEIC/HEIF → correct MIME ────────────
# Validates: Requirement 2.1, 2.2
class TestGuessMediaTypeHeic:
    """HEIC/HEIF extensions map to correct MIME types."""

    def test_heic_returns_image_heic(self) -> None:
        assert _guess_media_type("/tmp/photo.heic") == "image/heic"

    def test_heif_returns_image_heif(self) -> None:
        assert _guess_media_type("/tmp/photo.heif") == "image/heif"


# ── Test 6: ensure_png_tempfile non-HEIC returns original path ─────────
# Validates: Requirement 3.4
class TestEnsurePngNonHeicPassthrough:
    """Non-HEIC files pass through without conversion."""

    def test_png_returns_original_path(self) -> None:
        mock_file = _make_upload_file("image.png", content=b"PNG data")
        path = asyncio.run(ensure_png_tempfile(mock_file))
        try:
            assert path.endswith(".png")
            assert os.path.exists(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_jpg_returns_original_path(self) -> None:
        mock_file = _make_upload_file("image.jpg", content=b"JPEG data")
        path = asyncio.run(ensure_png_tempfile(mock_file))
        try:
            assert path.endswith(".jpg")
            assert os.path.exists(path)
        finally:
            if os.path.exists(path):
                os.unlink(path)
