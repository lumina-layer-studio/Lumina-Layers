"""Router integration tests for all API endpoints.
API 路由集成测试，验证所有端点的 stub 响应行为。

Includes both unit tests (specific examples per endpoint) and a property-based
test (Property 4) that verifies all endpoints return 200 + stub response
across randomly generated valid request bodies.
包含单元测试（每个端点的具体示例）和 property-based 测试（Property 4），
验证所有端点在随机生成的有效请求体下返回 200 + stub 响应。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel

from api.app import create_app
from api.schemas.calibration import BackingColor, CalibrationGenerateRequest
from api.schemas.converter import (
    ColorMergePreviewRequest,
    ColorMode,
    ColorReplaceRequest,
    ColorReplacementItem,
    ConvertBatchRequest,
    ConvertGenerateRequest,
    ConvertPreviewRequest,
    ModelingMode,
    StructureMode,
)
from api.schemas.extractor import (
    CalibrationColorMode,
    ExtractorExtractRequest,
    ExtractorManualFixRequest,
    ExtractorPage,
)

# ---------------------------------------------------------------------------
# Shared fixtures and constants
# ---------------------------------------------------------------------------

STUB_RESPONSE: Dict[str, str] = {
    "status": "not_implemented",
    "message": "Phase 2 will integrate core logic",
}


@pytest.fixture()
def client() -> TestClient:
    """Create a fresh TestClient for each test.
    为每个测试创建独立的 TestClient。
    """
    return TestClient(create_app())


# ===========================================================================
# Unit Tests — Specific examples for each endpoint
# ===========================================================================


class TestConverterEndpoints:
    """Unit tests for Converter domain endpoints.
    Converter 领域端点的单元测试。
    """

    def test_post_preview_missing_lut_returns_404(self, client: TestClient) -> None:
        """POST /api/convert/preview with unknown LUT returns 404."""
        import io

        # Create a minimal valid PNG image
        from PIL import Image as _PILImage

        buf = io.BytesIO()
        _PILImage.new("RGB", (4, 4), (128, 64, 32)).save(buf, format="PNG")
        buf.seek(0)
        resp = client.post(
            "/api/convert/preview",
            files={"image": ("test.png", buf, "image/png")},
            data={"lut_name": "nonexistent_lut", "color_mode": "4-Color"},
        )
        assert resp.status_code == 404
        assert "LUT not found" in resp.json()["detail"]

    def test_post_preview_missing_image_returns_422(self, client: TestClient) -> None:
        """POST /api/convert/preview without image returns 422."""
        resp = client.post(
            "/api/convert/preview",
            data={"lut_name": "test_lut", "color_mode": "4-Color"},
        )
        assert resp.status_code == 422

    def test_post_generate_missing_session_returns_422(self, client: TestClient) -> None:
        """POST /api/convert/generate without valid body returns 422."""
        payload = {"lut_name": "test_lut"}
        resp = client.post("/api/convert/generate", json=payload)
        assert resp.status_code == 422

    def test_post_generate_unknown_session_returns_404(self, client: TestClient) -> None:
        """POST /api/convert/generate with unknown session returns 404."""
        payload = {
            "session_id": "nonexistent-session-id",
            "params": {"lut_name": "test_lut"},
        }
        resp = client.post("/api/convert/generate", json=payload)
        assert resp.status_code == 404

    def test_post_batch(self, client: TestClient) -> None:
        """POST /api/convert/batch without required files returns 422."""
        payload = {"params": {"lut_name": "test_lut"}}
        resp = client.post("/api/convert/batch", json=payload)
        assert resp.status_code == 422

    def test_post_replace_color(self, client: TestClient) -> None:
        """POST /api/convert/replace-color with unknown session returns 404."""
        payload = {
            "session_id": "abc123",
            "selected_color": "#ff0000",
            "replacement_color": "#00ff00",
        }
        resp = client.post("/api/convert/replace-color", json=payload)
        assert resp.status_code == 404

    def test_post_merge_colors(self, client: TestClient) -> None:
        """POST /api/convert/merge-colors with unknown session returns 404."""
        payload = {"session_id": "abc123"}
        resp = client.post("/api/convert/merge-colors", json=payload)
        assert resp.status_code == 404


class TestExtractorEndpoints:
    """Unit tests for Extractor domain endpoints.
    Extractor 领域端点的单元测试。
    """

    def test_post_extract(self, client: TestClient) -> None:
        """POST /api/extractor/extract without required image returns 422."""
        payload = {
            "color_mode": "4-Color (RYBW)",
            "corner_points": [[0, 0], [100, 0], [100, 100], [0, 100]],
        }
        resp = client.post("/api/extractor/extract", json=payload)
        assert resp.status_code == 422

    def test_post_manual_fix(self, client: TestClient) -> None:
        """POST /api/extractor/manual-fix with nonexistent LUT returns 500."""
        payload = {
            "lut_path": "/tmp/test.npy",
            "cell_coord": [2, 3],
            "override_color": "#aabbcc",
        }
        resp = client.post("/api/extractor/manual-fix", json=payload)
        assert resp.status_code == 500


class TestCalibrationEndpoints:
    """Unit tests for Calibration domain endpoints.
    Calibration 领域端点的单元测试。
    """

    def test_post_generate(self, client: TestClient) -> None:
        """POST /api/calibration/generate returns CalibrationResponse."""
        payload = {"color_mode": "4-Color (RYBW)", "block_size": 5}
        resp = client.post("/api/calibration/generate", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "download_url" in body
        assert "preview_url" in body
        assert body["download_url"].startswith("/api/files/")
        assert body["preview_url"].startswith("/api/files/")


# ===========================================================================
# Hypothesis strategies — reuse from test_api_schemas_properties.py patterns
# ===========================================================================

st_non_empty_str = st.text(min_size=1, max_size=50).filter(lambda s: s.strip() != "")
st_hex_color = st.from_regex(r"#[0-9a-f]{6}", fullmatch=True)
st_color_mode = st.sampled_from(list(ColorMode))
st_modeling_mode = st.sampled_from(list(ModelingMode))
st_structure_mode = st.sampled_from(list(StructureMode))
st_calibration_color_mode = st.sampled_from(list(CalibrationColorMode))
st_extractor_page = st.sampled_from(list(ExtractorPage))
st_backing_color = st.sampled_from(list(BackingColor))


@st.composite
def st_convert_preview_request(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate a valid JSON-serializable dict for ConvertPreviewRequest."""
    return ConvertPreviewRequest(
        lut_name=draw(st_non_empty_str),
        target_width_mm=draw(st.floats(min_value=10, max_value=400, allow_nan=False)),
        auto_bg=draw(st.booleans()),
        bg_tol=draw(st.integers(min_value=0, max_value=150)),
        color_mode=draw(st_color_mode),
        modeling_mode=draw(st_modeling_mode),
        quantize_colors=draw(st.integers(min_value=8, max_value=256)),
        enable_cleanup=draw(st.booleans()),
    ).model_dump(mode="json")


@st.composite
def st_convert_generate_request(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate a valid JSON-serializable dict for ConvertGenerateRequest."""
    return ConvertGenerateRequest(
        lut_name=draw(st_non_empty_str),
        target_width_mm=draw(st.floats(min_value=10, max_value=400, allow_nan=False)),
        spacer_thick=draw(st.floats(min_value=0.2, max_value=3.5, allow_nan=False)),
        structure_mode=draw(st_structure_mode),
        auto_bg=draw(st.booleans()),
        bg_tol=draw(st.integers(min_value=0, max_value=150)),
        color_mode=draw(st_color_mode),
        modeling_mode=draw(st_modeling_mode),
        quantize_colors=draw(st.integers(min_value=8, max_value=256)),
        enable_cleanup=draw(st.booleans()),
        separate_backing=draw(st.booleans()),
        add_loop=draw(st.booleans()),
        loop_width=draw(st.floats(min_value=2, max_value=10, allow_nan=False)),
        loop_length=draw(st.floats(min_value=4, max_value=15, allow_nan=False)),
        loop_hole=draw(st.floats(min_value=1, max_value=5, allow_nan=False)),
        enable_relief=draw(st.booleans()),
        heightmap_max_height=draw(st.floats(min_value=0.08, max_value=15.0, allow_nan=False)),
        enable_outline=draw(st.booleans()),
        outline_width=draw(st.floats(min_value=0.5, max_value=10.0, allow_nan=False)),
        enable_cloisonne=draw(st.booleans()),
        wire_width_mm=draw(st.floats(min_value=0.2, max_value=1.2, allow_nan=False)),
        wire_height_mm=draw(st.floats(min_value=0.04, max_value=1.0, allow_nan=False)),
        enable_coating=draw(st.booleans()),
        coating_height_mm=draw(st.floats(min_value=0.04, max_value=0.12, allow_nan=False)),
    ).model_dump(mode="json")


@st.composite
def st_convert_batch_request(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate a valid JSON-serializable dict for ConvertBatchRequest."""
    params = draw(st_convert_generate_request())
    return {"params": params}


@st.composite
def st_color_replace_request(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate a valid JSON-serializable dict for ColorReplaceRequest."""
    return ColorReplaceRequest(
        session_id=draw(st_non_empty_str),
        selected_color=draw(st_hex_color),
        replacement_color=draw(st_hex_color),
    ).model_dump(mode="json")


@st.composite
def st_color_merge_preview_request(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate a valid JSON-serializable dict for ColorMergePreviewRequest."""
    return ColorMergePreviewRequest(
        session_id=draw(st_non_empty_str),
        merge_enable=draw(st.booleans()),
        merge_threshold=draw(st.floats(min_value=0.1, max_value=5.0, allow_nan=False)),
        merge_max_distance=draw(st.integers(min_value=5, max_value=50)),
    ).model_dump(mode="json")


@st.composite
def st_extractor_extract_request(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate a valid JSON-serializable dict for ExtractorExtractRequest."""
    corner_points = [
        draw(st.tuples(st.integers(min_value=0, max_value=5000), st.integers(min_value=0, max_value=5000)))
        for _ in range(4)
    ]
    return ExtractorExtractRequest(
        color_mode=draw(st_calibration_color_mode),
        corner_points=corner_points,
        offset_x=draw(st.integers(min_value=-30, max_value=30)),
        offset_y=draw(st.integers(min_value=-30, max_value=30)),
        zoom=draw(st.floats(min_value=0.8, max_value=1.2, allow_nan=False)),
        distortion=draw(st.floats(min_value=-0.2, max_value=0.2, allow_nan=False)),
        vignette_correction=draw(st.booleans()),
        page=draw(st_extractor_page),
    ).model_dump(mode="json")


@st.composite
def st_extractor_manual_fix_request(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate a valid JSON-serializable dict for ExtractorManualFixRequest."""
    return ExtractorManualFixRequest(
        lut_path=draw(st_non_empty_str),
        cell_coord=draw(
            st.tuples(
                st.integers(min_value=0, max_value=100),
                st.integers(min_value=0, max_value=100),
            )
        ),
        override_color=draw(st_hex_color),
    ).model_dump(mode="json")


@st.composite
def st_calibration_generate_request(draw: st.DrawFn) -> Dict[str, Any]:
    """Generate a valid JSON-serializable dict for CalibrationGenerateRequest."""
    return CalibrationGenerateRequest(
        color_mode=draw(st_calibration_color_mode),
        block_size=draw(st.integers(min_value=3, max_value=10)),
        gap=draw(st.floats(min_value=0.4, max_value=2.0, allow_nan=False)),
        backing=draw(st_backing_color),
    ).model_dump(mode="json")


# ---------------------------------------------------------------------------
# All 8 endpoints with their path and matching request body strategy
# ---------------------------------------------------------------------------

# Endpoints still returning stub responses (Phase 1)
# Note: All endpoints are now fully implemented, no stubs remain.
STUB_ENDPOINT_TABLE: List[Tuple[str, st.SearchStrategy[Dict[str, Any]]]] = []

# Integrated endpoints (Phase 2) — kept for reference
ENDPOINT_TABLE: List[Tuple[str, st.SearchStrategy[Dict[str, Any]]]] = [
    *STUB_ENDPOINT_TABLE,
    ("/api/calibration/generate", st_calibration_generate_request()),
]


# ===========================================================================
# Property 4: All Endpoints Return Stub Response
# Feature: fastapi-backend-scaffold, Property 4: 所有端点返回 Stub 响应
# ===========================================================================


# **Validates: Requirements 6.7, 7.4, 8.3**
@pytest.mark.skipif(len(STUB_ENDPOINT_TABLE) == 0, reason="No stub endpoints remain")
@given(data=st.data())
@settings(max_examples=100)
def test_all_endpoints_return_stub_response(data: st.DataObject) -> None:
    """Property 4: For any registered API endpoint that is still a stub,
    sending a POST request with a valid request body should return HTTP 200
    and a JSON response containing ``status='not_implemented'``.

    **Validates: Requirements 6.7, 7.4, 8.3**
    """
    client = TestClient(create_app())

    path, strategy = data.draw(st.sampled_from(STUB_ENDPOINT_TABLE))
    payload = data.draw(strategy)

    resp = client.post(path, json=payload)

    assert resp.status_code == 200, f"Endpoint {path} returned {resp.status_code}, expected 200. " f"Body: {resp.text}"
    body = resp.json()
    assert "status" in body, f"Endpoint {path} response missing 'status' field: {body}"
    assert body["status"] == "not_implemented", f"Endpoint {path} status={body['status']!r}, expected 'not_implemented'"
