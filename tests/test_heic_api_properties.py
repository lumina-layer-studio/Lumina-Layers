# -*- coding: utf-8 -*-
"""
Property-based tests for HEIC/HEIF API layer support.

Feature: heic-api-support
Tests the API layer file_bridge module for correct MIME type mapping.
"""

from hypothesis import given, settings
from hypothesis import strategies as st

from api.file_bridge import _guess_media_type


# ── Known extension → MIME type mapping (mirrors file_bridge.py) ───────
KNOWN_MIME_MAP: dict[str, str] = {
    ".3mf": "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
    ".glb": "model/gltf-binary",
    ".zip": "application/zip",
    ".npy": "application/octet-stream",
    ".npz": "application/octet-stream",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".heic": "image/heic",
    ".heif": "image/heif",
}


# ── Property 1: MIME type mapping completeness ─────────────────────────
# Feature: heic-api-support, Property 1: MIME type mapping completeness
# **Validates: Requirements 2.1, 2.2**
@given(ext=st.sampled_from(list(KNOWN_MIME_MAP.keys())))
@settings(max_examples=100)
def test_mime_type_mapping_completeness(ext: str) -> None:
    """Every known extension maps to its correct MIME type.

    Feature: heic-api-support, Property 1: MIME type mapping completeness

    **Validates: Requirements 2.1, 2.2**
    """
    path = f"/tmp/testfile{ext}"
    result = _guess_media_type(path)
    assert result == KNOWN_MIME_MAP[ext], (
        f"Expected {KNOWN_MIME_MAP[ext]!r} for {ext!r}, got {result!r}"
    )


# ── Helpers for Property 3 ─────────────────────────────────────────────
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

from api.file_bridge import upload_to_tempfile, ensure_png_tempfile, HEIC_EXTENSIONS


def _make_upload_file(filename: str, content: bytes = b"test") -> MagicMock:
    """Create a mock UploadFile with given filename and content.
    创建具有指定文件名和内容的模拟 UploadFile。
    """
    mock = MagicMock()
    mock.filename = filename
    mock.read = AsyncMock(return_value=content)
    return mock


# ── Property 3: Temp file suffix behavior ──────────────────────────────
# Feature: heic-api-support, Property 3: Temp file suffix behavior
# **Validates: Requirements 5.1, 5.2**
@given(
    basename=st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=10,
    ),
    ext=st.sampled_from([".heic", ".heif", ".png", ".jpg", ".svg", ""]),
    use_suffix=st.booleans(),
    explicit_suffix=st.sampled_from([".png", ".jpg", ".tmp", ".heic"]),
)
@settings(max_examples=100)
def test_temp_file_suffix_behavior(
    basename: str, ext: str, use_suffix: bool, explicit_suffix: str
) -> None:
    """upload_to_tempfile() respects suffix rules for all filename/suffix combos.

    Feature: heic-api-support, Property 3: Temp file suffix behavior

    Rules:
    - If explicit suffix provided → use that suffix
    - Otherwise use original filename extension
    - If no extension and no suffix → use .tmp

    **Validates: Requirements 5.1, 5.2**
    """
    filename = f"{basename}{ext}" if ext else basename
    mock_file = _make_upload_file(filename)
    suffix_arg = explicit_suffix if use_suffix else None

    path = asyncio.run(upload_to_tempfile(mock_file, suffix=suffix_arg))
    try:
        if use_suffix:
            assert path.endswith(explicit_suffix), (
                f"Expected suffix {explicit_suffix!r} but got path {path!r}"
            )
        elif ext:
            assert path.endswith(ext), (
                f"Expected suffix {ext!r} from filename but got path {path!r}"
            )
        else:
            assert path.endswith(".tmp"), (
                f"Expected .tmp fallback but got path {path!r}"
            )
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ── Property 2: HEIC conversion output path correctness ────────────────
# Feature: heic-api-support, Property 2: HEIC conversion output path
# **Validates: Requirements 3.4**

NON_HEIC_EXTENSIONS = [".png", ".jpg", ".bmp", ".gif", ".webp", ".svg"]


@given(ext=st.sampled_from(NON_HEIC_EXTENSIONS))
@settings(max_examples=100)
def test_ensure_png_non_heic_preserves_extension(ext: str) -> None:
    """Non-HEIC files pass through with original extension preserved.
    非 HEIC 文件直接透传，保留原始扩展名。

    Feature: heic-api-support, Property 2: HEIC conversion output path

    **Validates: Requirements 3.4**
    """
    mock_file = _make_upload_file(f"photo{ext}", content=b"fake image data")
    path = asyncio.run(ensure_png_tempfile(mock_file))
    try:
        assert path.endswith(ext), (
            f"Expected {ext} suffix, got {path}"
        )
    finally:
        if os.path.exists(path):
            os.unlink(path)


@given(ext=st.sampled_from(list(HEIC_EXTENSIONS)))
@settings(max_examples=100)
def test_ensure_png_heic_outputs_png(ext: str) -> None:
    """HEIC/HEIF files are converted to PNG output path.
    HEIC/HEIF 文件转换后输出路径以 .png 结尾。

    Feature: heic-api-support, Property 2: HEIC conversion output path

    **Validates: Requirements 3.4**
    """
    # Create a real small PNG image as content (PIL can open it regardless of ext)
    from PIL import Image as PILImage
    import io as _io

    buf = _io.BytesIO()
    PILImage.new("RGB", (2, 2), (255, 0, 0)).save(buf, "PNG")
    png_bytes = buf.getvalue()

    mock_file = _make_upload_file(f"photo{ext}", content=png_bytes)

    # HAS_HEIF must be True for the conversion path to execute
    with patch("api.file_bridge.HAS_HEIF", True):
        path = asyncio.run(ensure_png_tempfile(mock_file))
    try:
        assert path.endswith(".png"), (
            f"Expected .png suffix for HEIC input, got {path}"
        )
    finally:
        if os.path.exists(path):
            os.unlink(path)
