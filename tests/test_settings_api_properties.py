"""Property-based tests for Settings API endpoints.

Uses Hypothesis to verify correctness properties of the Settings API
round-trip behaviour and invalid payload rejection.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

from api.app import app

client: TestClient = TestClient(app)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Valid values for constrained string fields
modeling_modes = st.sampled_from(["high-fidelity", "pixel", "vector"])
color_modes = st.sampled_from(["4-Color", "6-Color", "8-Color Max", "BW", "Merged"])
safe_text = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "P", "Z")),
    min_size=0,
    max_size=100,
)


# ---------------------------------------------------------------------------
# Property 6: Settings API round-trip
# **Validates: Requirements 5.1, 5.3**
# ---------------------------------------------------------------------------


@given(
    last_lut=safe_text,
    last_modeling_mode=modeling_modes,
    last_color_mode=color_modes,
    last_slicer=safe_text,
    palette_mode=safe_text,
    enable_crop_modal=st.booleans(),
)
@settings(max_examples=100)
def test_settings_round_trip(
    last_lut: str,
    last_modeling_mode: str,
    last_color_mode: str,
    last_slicer: str,
    palette_mode: str,
    enable_crop_modal: bool,
) -> None:
    """Property 6: For any valid UserSettings, POST then GET SHALL return
    equivalent data.

    Feature: global-settings, Property 6: Settings API round-trip
    **Validates: Requirements 5.1, 5.3**
    """
    payload = {
        "last_lut": last_lut,
        "last_modeling_mode": last_modeling_mode,
        "last_color_mode": last_color_mode,
        "last_slicer": last_slicer,
        "palette_mode": palette_mode,
        "enable_crop_modal": enable_crop_modal,
    }

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_file = Path(tmp_dir) / "user_settings.json"
        with patch("api.routers.system.SETTINGS_FILE", tmp_file):
            # POST — write settings
            post_resp = client.post("/api/system/settings", json=payload)
            assert post_resp.status_code == 200, (
                f"POST failed: {post_resp.text}"
            )

            # GET — read back
            get_resp = client.get("/api/system/settings")
            assert get_resp.status_code == 200, (
                f"GET failed: {get_resp.text}"
            )

            returned = get_resp.json()["settings"]

            # Round-trip equality
            assert returned["last_lut"] == last_lut
            assert returned["last_modeling_mode"] == last_modeling_mode
            assert returned["last_color_mode"] == last_color_mode
            assert returned["last_slicer"] == last_slicer
            assert returned["palette_mode"] == palette_mode
            assert returned["enable_crop_modal"] == enable_crop_modal


# ---------------------------------------------------------------------------
# Property 7: Settings API 拒绝无效 payload
# **Validates: Requirements 5.4**
# ---------------------------------------------------------------------------


@given(
    bad_value=st.one_of(
        st.text(min_size=1, max_size=20),
        st.integers(),
        st.lists(st.integers(), min_size=1, max_size=3),
    ),
)
@settings(max_examples=100)
def test_settings_rejects_invalid_enable_crop_modal(bad_value) -> None:
    """Property 7: For any non-boolean value in enable_crop_modal,
    POST /api/system/settings SHALL return 422.

    Feature: global-settings, Property 7: Settings API 拒绝无效 payload
    **Validates: Requirements 5.4**
    """
    # Skip values that Pydantic would coerce to bool successfully
    # (integers 0/1 and strings "true"/"false" etc. are coerced by Pydantic)
    if isinstance(bad_value, (int, float)):
        # Pydantic v2 coerces int to bool; use a list instead
        bad_value = [bad_value]
    if isinstance(bad_value, str) and bad_value.lower() in (
        "true", "false", "1", "0", "yes", "no", "on", "off",
    ):
        bad_value = {"nested": bad_value}

    payload = {
        "last_lut": "",
        "last_modeling_mode": "high-fidelity",
        "last_color_mode": "4-Color",
        "last_slicer": "",
        "palette_mode": "swatch",
        "enable_crop_modal": bad_value,
    }

    resp = client.post("/api/system/settings", json=payload)
    assert resp.status_code == 422, (
        f"Expected 422 for enable_crop_modal={bad_value!r}, got {resp.status_code}: {resp.text}"
    )
