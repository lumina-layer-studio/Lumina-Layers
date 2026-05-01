"""Property-based tests for Calibration parameter mapping completeness (Property 5).

Uses Hypothesis to generate random valid CalibrationGenerateRequest parameters
and verify that all CalibrationColorMode enum values route to the correct core
function, and that block_size/gap within Pydantic validation range do not cause
parameter errors.

**Validates: Requirements 3.5**
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from PIL import Image

from api.app import app
from api.schemas.calibration import BackingColor, CalibrationGenerateRequest
from api.schemas.extractor import CalibrationColorMode

client: TestClient = TestClient(app)

# ---------------------------------------------------------------------------
# Shared mock fixtures
# ---------------------------------------------------------------------------

_mock_preview: Image.Image = Image.fromarray(
    np.zeros((10, 10, 3), dtype=np.uint8)
)
_mock_return = ("/tmp/fake.3mf", _mock_preview, "OK")

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

color_modes = st.sampled_from(list(CalibrationColorMode))
backing_colors = st.sampled_from(list(BackingColor))
block_sizes = st.integers(min_value=3, max_value=10)
gap_values = st.floats(min_value=0.4, max_value=2.0, allow_nan=False, allow_infinity=False)

# Mapping from color_mode enum value to the mock target path
_MODE_TO_MOCK_TARGET: dict[str, str] = {
    "BW (Black & White)": "api.routers.calibration.generate_bw_calibration_board",
    "4-Color": "api.routers.calibration.generate_calibration_board",
    "CMYW": "api.routers.calibration.generate_calibration_board",
    "RYBW": "api.routers.calibration.generate_calibration_board",
    "5-Color Extended (1444)": "api.routers.calibration.generate_5color_extended_batch_zip",
    "6-Color (Smart 1296)": "api.routers.calibration.generate_smart_board",
    "8-Color Max": "api.routers.calibration.generate_8color_batch_zip",
}


# ---------------------------------------------------------------------------
# Property 5: Calibration routing completeness
# ---------------------------------------------------------------------------


# **Validates: Requirements 3.5**
@given(
    mode=color_modes,
    block_size=block_sizes,
    gap=gap_values,
    backing=backing_colors,
)
@settings(max_examples=200)
def test_all_color_modes_route_to_valid_core_function(
    mode: CalibrationColorMode,
    block_size: int,
    gap: float,
    backing: BackingColor,
) -> None:
    """Every CalibrationColorMode enum value routes to exactly one core function.

    For any valid CalibrationGenerateRequest, the endpoint must:
    1. Return HTTP 200
    2. Call exactly one of the four core functions
    """
    mock_target = _MODE_TO_MOCK_TARGET[mode.value]

    with patch(mock_target, return_value=_mock_return) as called_mock:
        response = client.post(
            "/api/calibration/generate",
            json={
                "color_mode": mode.value,
                "block_size": block_size,
                "gap": gap,
                "backing": backing.value,
            },
        )

    assert response.status_code == 200, (
        f"Expected 200 for mode={mode.value}, got {response.status_code}: "
        f"{response.text}"
    )
    called_mock.assert_called_once()


# **Validates: Requirements 3.5**
@given(
    mode=color_modes,
    block_size=block_sizes,
    gap=gap_values,
    backing=backing_colors,
)
@settings(max_examples=200)
def test_block_size_and_gap_do_not_cause_parameter_errors(
    mode: CalibrationColorMode,
    block_size: int,
    gap: float,
    backing: BackingColor,
) -> None:
    """block_size and gap within Pydantic validation range never cause parameter errors.

    All four core functions are mocked; the test verifies that the router
    does not raise any argument-related exceptions when dispatching.
    """
    with (
        patch(
            "api.routers.calibration.generate_bw_calibration_board",
            return_value=_mock_return,
        ),
        patch(
            "api.routers.calibration.generate_calibration_board",
            return_value=_mock_return,
        ),
        patch(
            "api.routers.calibration.generate_smart_board",
            return_value=_mock_return,
        ),
        patch(
            "api.routers.calibration.generate_8color_batch_zip",
            return_value=_mock_return,
        ),
        patch(
            "api.routers.calibration.generate_5color_extended_batch_zip",
            return_value=_mock_return,
        ),
    ):
        response = client.post(
            "/api/calibration/generate",
            json={
                "color_mode": mode.value,
                "block_size": block_size,
                "gap": gap,
                "backing": backing.value,
            },
        )

    assert response.status_code == 200, (
        f"Parameter error for mode={mode.value}, block_size={block_size}, "
        f"gap={gap}: {response.text}"
    )
    data = response.json()
    assert data["status"] == "ok"
    assert "download_url" in data
    assert "preview_url" in data


# **Validates: Requirements 3.5**
def test_enum_coverage_is_exhaustive() -> None:
    """The routing map covers every CalibrationColorMode enum member.

    This is a static check: every enum value must have a corresponding
    entry in the routing dispatch table.
    """
    for member in CalibrationColorMode:
        assert member.value in _MODE_TO_MOCK_TARGET, (
            f"CalibrationColorMode.{member.name} ({member.value!r}) "
            f"has no routing entry"
        )
