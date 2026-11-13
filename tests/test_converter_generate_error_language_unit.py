"""Regression tests for user-safe converter generate failure details."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from api.app import app
from api.dependencies import get_file_registry, get_session_store, get_worker_pool
from api.file_registry import FileRegistry
from api.routers.converter.color_card import _require_color_card_cache_metadata
from api.routers.converter.common import _require_preview_cache
from api.routers.converter.generate import (
    _model_generation_failure_exception,
    _require_preview_cache_for_generate,
)
from api.routers.converter.preview import _require_preview_cache_for_layer_images
from api.routers.converter.puzzle import _require_puzzle_cache
from api.routers.converter.replace import _require_preview_cache_fields
from api.session_store import SessionStore
from api.worker_pool import WorkerPoolManager


VECTOR_SVG_REQUIRED_DETAIL = (
    "⚠️ Vector Native mode requires SVG files!\n\n"
    "Your file is not an SVG. Please either:\n"
    "• Upload an SVG file, or\n"
    "• Switch to 'High-Fidelity' or 'Pixel Art' mode"
)


def _assert_public_converter_detail(detail: str) -> None:
    assert "Call POST" not in detail
    assert "POST" not in detail
    assert "/api/convert" not in detail
    assert "/preview" not in detail
    assert "preview" in detail.lower()


@pytest.mark.parametrize(
    "call",
    [
        lambda: _require_preview_cache({}),
        lambda: _require_preview_cache_for_generate({}),
        lambda: _require_preview_cache_for_generate({"preview_cache": "stale"}),
        lambda: _require_color_card_cache_metadata({}),
        lambda: _require_puzzle_cache({}, fields={"matched_rgb"}),
        lambda: _require_preview_cache_fields({}, fields={"matched_rgb"}),
        lambda: _require_preview_cache_for_layer_images({}),
    ],
)
def test_converter_preview_cache_errors_use_user_language(call) -> None:
    with pytest.raises(HTTPException) as exc_info:
        call()

    assert exc_info.value.status_code in {400, 409}
    _assert_public_converter_detail(str(exc_info.value.detail))


def _seed_generate_session(
    store: SessionStore,
    tmp_path: Path,
    *,
    source_suffix: str = ".png",
    modeling_mode: str = "high-fidelity",
    surface_overlay: bool = False,
) -> str:
    """Create a minimal preview-ready session for /api/convert/generate."""

    image_path = tmp_path / f"source{source_suffix}"
    lut_path = tmp_path / "palette.npy"
    if source_suffix == ".svg":
        image_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 8 8">'
            '<rect width="8" height="8" fill="#f00"/></svg>',
            encoding="utf-8",
        )
    else:
        Image.new("RGB", (8, 8), (255, 0, 0)).save(image_path)
    np.save(lut_path, np.zeros((1, 3), dtype=np.uint8))

    session_id = store.create()
    store.put(
        session_id,
        "preview_cache",
        {
            "target_w": 8,
            "target_h": 8,
            "target_width_mm": 40.0,
            "color_palette": [{"hex": "#ff0000"}],
        },
    )
    store.put(session_id, "image_path", str(image_path))
    store.put(session_id, "lut_path", str(lut_path))
    store.put(session_id, "modeling_mode", modeling_mode)
    if surface_overlay:
        store.put(session_id, "surface_overlay_enabled", True)
    store.put(session_id, "replacement_regions", [])
    store.put(session_id, "free_color_set", set())
    return session_id


def _post_generate_with_pool(
    tmp_path: Path,
    pool: MagicMock,
    *,
    source_suffix: str = ".png",
    modeling_mode: str = "high-fidelity",
    request_modeling_mode: str | None = None,
    surface_overlay: bool = False,
):
    store = SessionStore(ttl=1800)
    registry = FileRegistry()
    session_id = _seed_generate_session(
        store,
        tmp_path,
        source_suffix=source_suffix,
        modeling_mode=modeling_mode,
        surface_overlay=surface_overlay,
    )

    previous_overrides = {
        get_session_store: app.dependency_overrides.get(get_session_store),
        get_file_registry: app.dependency_overrides.get(get_file_registry),
        get_worker_pool: app.dependency_overrides.get(get_worker_pool),
    }
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_file_registry] = lambda: registry
    app.dependency_overrides[get_worker_pool] = lambda: pool

    try:
        client = TestClient(app, raise_server_exceptions=False)
        request_params = {"lut_name": "test_lut"}
        if request_modeling_mode is not None:
            request_params["modeling_mode"] = request_modeling_mode
        return client.post(
            "/api/convert/generate",
            json={
                "session_id": session_id,
                "params": request_params,
            },
        )
    finally:
        for dependency, previous in previous_overrides.items():
            if previous is None:
                app.dependency_overrides.pop(dependency, None)
            else:
                app.dependency_overrides[dependency] = previous
        registry.clear_all()
        store.clear_all()


def test_generate_worker_exception_uses_public_error_language(tmp_path: Path) -> None:
    private_path = "/Users/min/private/source.png"
    pool = MagicMock(spec=WorkerPoolManager)
    pool.submit_timed = AsyncMock(
        side_effect=RuntimeError(f"cannot read {private_path}: decode failed")
    )

    response = _post_generate_with_pool(tmp_path, pool)

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "3MF generation failed. Re-run preview and try generating the model again."
    )
    assert private_path not in response.text
    assert "decode failed" not in response.text


def test_generate_late_template_capacity_error_preserves_422_and_slot_counts(tmp_path: Path) -> None:
    """Auxiliary geometry can exceed template capacity after material preflight."""
    from core.errors import TemplateSlotCapacityError

    pool = MagicMock(spec=WorkerPoolManager)
    pool.submit_timed = AsyncMock(side_effect=TemplateSlotCapacityError(5, 4))

    response = _post_generate_with_pool(tmp_path, pool)

    assert pool.submit_timed.await_count == 1
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "template_slot_capacity"
    assert detail["required_slots"] == 5
    assert detail["available_slots"] == 4


def test_generate_missing_worker_output_uses_public_error_language(tmp_path: Path) -> None:
    private_path = "/Users/min/private/model.3mf"
    pool = MagicMock(spec=WorkerPoolManager)
    pool.submit_timed = AsyncMock(
        return_value=(
            {
                "threemf_path": private_path,
                "glb_path": None,
                "status_msg": f"cannot write {private_path}: permission denied",
            },
            {},
        )
    )

    response = _post_generate_with_pool(tmp_path, pool)

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "3MF generation failed. Re-run preview and try generating the model again."
    )
    assert private_path not in response.text
    assert "permission denied" not in response.text


def test_generate_known_vector_source_mismatch_returns_actionable_validation_error(
    tmp_path: Path,
) -> None:
    pool = MagicMock(spec=WorkerPoolManager)
    pool.submit_timed = AsyncMock(
        return_value=(
            {
                "threemf_path": None,
                "glb_path": None,
                "status_msg": VECTOR_SVG_REQUIRED_DETAIL,
            },
            {},
        )
    )

    response = _post_generate_with_pool(
        tmp_path,
        pool,
        modeling_mode="vector",
        request_modeling_mode="vector",
    )

    assert response.status_code == 422
    assert response.json()["detail"] == {
        "error": "vector_native_requires_svg",
        "message": VECTOR_SVG_REQUIRED_DETAIL,
    }


@pytest.mark.parametrize(
    "diagnostic",
    [
        "Vector processing failed: No valid shapes found in SVG",
        "Vector processing failed: No valid filled shapes found in SVG.",
    ],
)
def test_generate_known_svg_no_geometry_returns_actionable_422(
    tmp_path: Path,
    diagnostic: str,
) -> None:
    pool = MagicMock(spec=WorkerPoolManager)
    pool.submit_timed = AsyncMock(
        return_value=(
            {
                "threemf_path": None,
                "glb_path": None,
                "status_msg": f"{diagnostic}\n\nSuggestions:\n- private parser text",
            },
            {},
        )
    )

    response = _post_generate_with_pool(
        tmp_path,
        pool,
        source_suffix=".svg",
        modeling_mode="vector",
        request_modeling_mode="vector",
    )

    assert response.status_code == 422
    assert response.json()["detail"]["error"] == (
        "source_svg_no_renderable_geometry"
    )
    assert "private parser text" not in response.text




@pytest.mark.parametrize(
    "diagnostic",
    [
        "Vector processing failed: No valid shapes found in SVG",
        VECTOR_SVG_REQUIRED_DETAIL,
        (
            "Vector processing failed: SVG compound path exceeds supported "
            "intersecting subpath complexity near match"
        ),
    ],
)
def test_generate_server_created_color_card_svg_failure_stays_internal(
    tmp_path: Path,
    diagnostic: str,
) -> None:
    pool = MagicMock(spec=WorkerPoolManager)
    pool.submit_timed = AsyncMock(
        return_value=(
            {
                "threemf_path": None,
                "glb_path": None,
                "status_msg": diagnostic,
            },
            {},
        )
    )

    response = _post_generate_with_pool(
        tmp_path,
        pool,
        source_suffix=".svg",
        modeling_mode="vector",
        request_modeling_mode="color-card",
    )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "3MF generation failed. Re-run preview and try generating the model again."
    )
    submitted_source = Path(pool.submit_timed.await_args.args[1])
    assert submitted_source.suffix == ".svg"
    assert submitted_source != tmp_path / "source.svg"


@pytest.mark.parametrize(
    ("status_msg", "source_is_user_upload", "source_path", "modeling_mode", "surface_overlay"),
    [
        (
            "⚠️ Vector Native mode requires SVG files! near match",
            True,
            "/tmp/source.png",
            "vector",
            False,
        ),
        (
            VECTOR_SVG_REQUIRED_DETAIL,
            True,
            "/tmp/source.png",
            "high-fidelity",
            False,
        ),
        (
            VECTOR_SVG_REQUIRED_DETAIL,
            True,
            "/tmp/source.svg",
            "vector",
            False,
        ),
        (
            VECTOR_SVG_REQUIRED_DETAIL,
            True,
            "/tmp/source.png",
            "vector",
            True,
        ),
        (
            VECTOR_SVG_REQUIRED_DETAIL,
            False,
            "/tmp/generated.png",
            "vector",
            False,
        ),
    ],
)
def test_generate_vector_source_mismatch_allowlist_keeps_other_failures_internal(
    status_msg: str,
    source_is_user_upload: bool,
    source_path: str,
    modeling_mode: str,
    surface_overlay: bool,
) -> None:
    exception = _model_generation_failure_exception(
        status_msg,
        source_is_user_upload=source_is_user_upload,
        modeling_mode=modeling_mode,
        source_path=source_path,
        surface_overlay=surface_overlay,
    )

    assert exception.status_code == 500
    assert exception.detail == (
        "3MF generation failed. Re-run preview and try generating the model again."
    )


@pytest.mark.parametrize(
    ("status_msg", "source_path", "modeling_mode", "surface_overlay"),
    [
        (
            "Vector processing failed: No valid shapes found in SVG: near match",
            "/tmp/source.svg",
            "vector",
            False,
        ),
        (
            "Vector processing failed: No valid shapes found in SVG",
            "/tmp/source.png",
            "vector",
            False,
        ),
        (
            "Vector processing failed: No valid shapes found in SVG",
            "/tmp/source.svg",
            "high-fidelity",
            False,
        ),
        (
            "Vector processing failed: No valid shapes found in SVG",
            "/tmp/source.svg",
            "vector",
            True,
        ),
    ],
)
def test_generate_svg_diagnostic_allowlist_does_not_reclassify_other_failures(
    status_msg: str,
    source_path: str,
    modeling_mode: str,
    surface_overlay: bool,
) -> None:
    exception = _model_generation_failure_exception(
        status_msg,
        source_is_user_upload=True,
        modeling_mode=modeling_mode,
        source_path=source_path,
        surface_overlay=surface_overlay,
    )

    assert exception.status_code == 500
    assert exception.detail == (
        "3MF generation failed. Re-run preview and try generating the model again."
    )
