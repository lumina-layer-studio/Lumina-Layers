"""Unit tests for auto-detect-colors temp-file cleanup.

Validates that the session-less ``/api/convert/auto-detect-colors`` endpoint
deletes its uploaded temp file on both success and failure paths, preventing
orphaned files in the system temp directory.
验证无会话的 /api/convert/auto-detect-colors 端点在成功和失败路径上
均删除上传的临时文件，防止在系统临时目录中留下孤立文件。
"""

from __future__ import annotations

import io
import os
import tempfile
from unittest.mock import AsyncMock, patch

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app


client: TestClient = TestClient(app)


def _make_test_image_buf() -> io.BytesIO:
    """Create a minimal valid PNG image buffer for upload."""
    img = Image.fromarray(np.zeros((10, 10, 3), dtype=np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _make_real_tempfile() -> str:
    """Create a real temp file that the endpoint should clean up."""
    fd, path = tempfile.mkstemp(suffix=".png")
    os.write(fd, b"fake-png")
    os.close(fd)
    return path


class TestAutoDetectCleanupOnSuccess:
    """Temp file must be deleted after successful color analysis."""

    def test_temp_file_removed_on_success(self) -> None:
        temp_path = _make_real_tempfile()

        mock_result = {
            "recommended": 48,
            "max_safe": 64,
            "unique_colors": 500,
            "complexity_score": 42,
        }

        with patch(
            "api.routers.converter.ensure_png_tempfile",
            new_callable=AsyncMock,
            return_value=temp_path,
        ), patch(
            "api.routers.converter.ImagePreprocessor.analyze_recommended_colors",
            return_value=mock_result,
        ):
            buf = _make_test_image_buf()
            response = client.post(
                "/api/convert/auto-detect-colors",
                files={"image": ("test.png", buf, "image/png")},
                data={"target_width_mm": "60.0"},
            )

        assert response.status_code == 200
        assert not os.path.exists(temp_path), (
            f"Temp file {temp_path} still exists after successful auto-detect"
        )


class TestAutoDetectCleanupOnFailure:
    """Temp file must be deleted even when color analysis raises."""

    def test_temp_file_removed_on_analysis_error(self) -> None:
        temp_path = _make_real_tempfile()

        with patch(
            "api.routers.converter.ensure_png_tempfile",
            new_callable=AsyncMock,
            return_value=temp_path,
        ), patch(
            "api.routers.converter.ImagePreprocessor.analyze_recommended_colors",
            side_effect=RuntimeError("synthetic analysis failure"),
        ):
            buf = _make_test_image_buf()
            response = client.post(
                "/api/convert/auto-detect-colors",
                files={"image": ("test.png", buf, "image/png")},
                data={"target_width_mm": "60.0"},
            )

        assert response.status_code == 422
        assert not os.path.exists(temp_path), (
            f"Temp file {temp_path} still exists after failed auto-detect"
        )
