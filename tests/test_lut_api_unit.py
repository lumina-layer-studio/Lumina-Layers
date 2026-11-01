"""Unit tests for LUT info and merge API endpoints.

Validates:
- GET /api/lut/{name}/info returns correct info or 404 (Requirement 6.7)
- POST /api/lut/merge returns 400 for invalid requests (Requirement 6.8)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path, PureWindowsPath
from types import SimpleNamespace
from urllib.parse import quote
from unittest.mock import patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_session_store
from api.routers import lut as lut_router
from api.routers.lut import _canonicalize_public_color_mode
from api.services.lut_presentation import public_lut_path_reference
from api.schemas.converter import ColorMode, ConvertGenerateRequest, ConvertPreviewRequest
from api.session_store import SessionStore
from config import LUTMetadata, ModelingMode, PaletteEntry
from core.native_reference import (
    get_reference_db_root,
    NativeReferenceContext,
    SOURCE_KIND_COLORD_DB,
    SOURCE_KIND_PACKAGE,
)

client: TestClient = TestClient(app)
_PRIVATE_ERROR_PATH = "/Users/min/private/lut-secret.json"
_UNSAFE_ERROR_FRAGMENTS = (
    _PRIVATE_ERROR_PATH,
    "/Users/",
    "Permission denied",
    "sqlite status",
    "BAD_METADATA",
    "lut-secret.json",
)
_PRIVATE_WINDOWS_LUT_PATH = r"C:\Users\min\private\native-secret.json"
_PRIVATE_LUT_NAME = r"C:\Users\min\private\missing-lut.json"
_LUT_NOT_FOUND_PUBLIC_DETAIL = "Selected LUT was not found or is unavailable."


def _assert_public_lut_path(path: str) -> None:
    assert path
    assert not path.startswith("/")
    assert not PureWindowsPath(path).is_absolute()
    assert "/Users/" not in path
    assert "C:/Users/" not in path.replace("\\", "/")
    assert "private" not in path
    assert "lut-secret" not in path
    assert "native-secret" not in path


def _records_for_event(
    caplog: pytest.LogCaptureFixture,
    event_name: str,
) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == event_name
    ]


def _assert_safe_error_detail(response, expected_detail: str) -> None:
    assert response.json()["detail"] == expected_detail
    for fragment in _UNSAFE_ERROR_FRAGMENTS:
        assert fragment not in response.text


def _assert_latest_http_error_log_safe(
    caplog: pytest.LogCaptureFixture,
    *,
    expected_detail: str,
    forbidden_fragments: tuple[str, ...],
) -> None:
    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "api_http_error"
    ]
    assert records
    error_message = str(getattr(records[-1], "error_message", ""))
    assert error_message == expected_detail
    for fragment in forbidden_fragments:
        assert fragment not in error_message


def _attach_lut_logger(
    caplog: pytest.LogCaptureFixture,
    *,
    level: int = logging.ERROR,
) -> logging.Logger:
    target_logger = logging.getLogger("lumina.api.routers.lut")
    target_logger.addHandler(caplog.handler)
    caplog.set_level(level, logger=target_logger.name)
    return target_logger


def test_legacy_multi_runtime_accepts_cross_color_lut_candidates(tmp_path: Path) -> None:
    from utils.lut_manager import LUTManager

    bw_path = tmp_path / "bw_36.npz"
    four_path = tmp_path / "four.npz"
    eight_path = tmp_path / "eight.npz"
    base_kwargs = {
        "max_color_layers": 5,
        "layer_height_mm": 0.08,
        "line_width_mm": 0.42,
        "base_layers": 10,
        "base_channel_idx": 0,
        "layer_order": "Top2Bottom",
    }
    four_meta = LUTMetadata(
        palette=[
            PaletteEntry("Red", "PLA Basic"),
            PaletteEntry("Yellow", "PLA Basic"),
            PaletteEntry("Blue", "PLA Basic"),
            PaletteEntry("White", "PLA Basic"),
        ],
        color_mode="4-Color (RYBW)",
        **base_kwargs,
    )
    bw_meta = LUTMetadata(
        palette=[
            PaletteEntry("White", "PLA Basic"),
            PaletteEntry("Black", "PLA Basic"),
        ],
        color_mode="BW (Black & White)",
        **base_kwargs,
    )
    eight_meta = LUTMetadata(
        palette=[
            PaletteEntry("Slot 1 (White)", "PLA Basic"),
            PaletteEntry("Slot 2 (Cyan)", "PLA Basic"),
            PaletteEntry("Slot 3 (Magenta)", "PLA Basic"),
            PaletteEntry("Slot 4 (Yellow)", "PLA Basic"),
            PaletteEntry("Slot 5 (Black)", "PLA Basic"),
            PaletteEntry("Slot 6 (Red)", "PLA Basic"),
            PaletteEntry("Slot 7 (Deep Blue)", "PLA Basic"),
            PaletteEntry("Slot 8 (Green)", "PLA Basic"),
        ],
        color_mode="8-Color Max",
        **base_kwargs,
    )
    bw_rgb = np.asarray(
        [[255 - idx * 4, 255 - idx * 4, 255 - idx * 4] for idx in range(36)],
        dtype=np.uint8,
    )
    LUTManager.save_npz_with_metadata(
        str(bw_path),
        bw_rgb,
        None,
        bw_meta,
    )
    LUTManager.save_npz_with_metadata(
        str(four_path),
        np.asarray([[255, 0, 0]], dtype=np.uint8),
        np.asarray([[0, 1, 2, 3, 0]], dtype=np.int32),
        four_meta,
    )
    LUTManager.save_npz_with_metadata(
        str(eight_path),
        np.asarray([[0, 0, 0]], dtype=np.uint8),
        np.asarray([[5, 3, 6, 0, 4]], dtype=np.int32),
        eight_meta,
    )

    paths = {
        "bw": str(bw_path),
        "four": str(four_path),
        "eight": str(eight_path),
    }
    runtime_path = None
    try:
        with patch("utils.lut_manager.LUTManager.get_lut_path", side_effect=lambda name: paths.get(name)):
            runtime_path, display_name = LUTManager.resolve_source_selection(
                source_kind="legacy_multi",
                lut_name="bw",
                lut_names=["bw", "four", "eight"],
            )

        assert display_name == "bw"
        runtime_rgb, runtime_stacks, runtime_meta = LUTManager.load_lut_with_metadata(runtime_path)
        assert runtime_rgb.reshape(-1, 3).shape[0] == 34
        assert [entry.color for entry in runtime_meta.palette] == [
            "Slot 1 (White)",
            "Slot 2 (Cyan)",
            "Slot 3 (Magenta)",
            "Slot 4 (Yellow)",
            "Slot 5 (Black)",
            "Slot 6 (Red)",
            "Slot 7 (Deep Blue)",
            "Slot 8 (Green)",
        ]
        assert runtime_meta.color_mode == "Merged"
        assert runtime_meta.extensions["source_kind"] == "legacy_multi"
        assert runtime_meta.extensions["selected_lut_names"] == ["bw", "four", "eight"]
        assert len({tuple(row) for row in runtime_stacks.tolist()}) == 34
        assert runtime_stacks[-2:].tolist() == [
            [5, 3, 6, 0, 5],
            [5, 3, 6, 0, 4],
        ]

        from core.pipeline.s01_input_validation import run as run_s01

        generate_ctx = run_s01(
            {
                "image_path": "/tmp/source.png",
                "lut_path": runtime_path,
                "color_mode": "4-Color (RYBW)",
                "modeling_mode": ModelingMode.HIGH_FIDELITY,
                "backing_color_id": 0,
                "separate_backing": False,
            }
        )
        assert generate_ctx["slot_names"] == [
            "Slot 1 (White)",
            "Slot 2 (Cyan)",
            "Slot 3 (Magenta)",
            "Slot 4 (Yellow)",
            "Slot 5 (Black)",
            "Slot 6 (Red)",
            "Slot 7 (Deep Blue)",
            "Slot 8 (Green)",
        ]
        assert len(generate_ctx["preview_colors"]) == 8
    finally:
        if runtime_path:
            Path(runtime_path).unlink(missing_ok=True)


class TestLutErrorBoundary:
    """Verify LUT route failures return user-safe details and keep diagnostics in logs."""

    class _FailingDetailsService:
        def get_catalog(self):
            raise OSError(f"sqlite status=BUSY path={_PRIVATE_ERROR_PATH}")

        def get_lut_details(self, _lut_name: str):
            raise RuntimeError(
                f"metadata parse failed at {_PRIVATE_ERROR_PATH} status=BAD_METADATA"
            )

    def test_details_catalog_failure_uses_safe_detail_and_logs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        service = self._FailingDetailsService()
        monkeypatch.setattr(lut_router, "_lut_details_service", service)
        monkeypatch.setattr(lut_router, "get_lut_details_service", lambda: service)
        target_logger = _attach_lut_logger(caplog)

        try:
            response = client.get("/api/lut/details/catalog")
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 500
        _assert_safe_error_detail(
            response,
            "Unable to load the LUT catalog. Check that LUT presets are available and try again.",
        )
        records = _records_for_event(caplog, "lut_details_catalog_failed")
        assert len(records) == 1
        assert records[0].error_type == "OSError"
        assert _PRIVATE_ERROR_PATH in records[0].error_message

    def test_lut_details_failure_uses_safe_detail_and_logs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        service = self._FailingDetailsService()
        monkeypatch.setattr(lut_router, "_lut_details_service", service)
        monkeypatch.setattr(lut_router, "get_lut_details_service", lambda: service)
        target_logger = _attach_lut_logger(caplog)

        try:
            response = client.get("/api/lut/Faulty/details")
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 500
        _assert_safe_error_detail(
            response,
            "Unable to load LUT details. Check that the selected LUT is valid and try again.",
        )
        records = _records_for_event(caplog, "lut_details_failed")
        assert len(records) == 1
        assert records[0].error_type == "RuntimeError"
        assert _PRIVATE_ERROR_PATH in records[0].error_message

    def test_upload_parse_failure_uses_safe_detail_and_logs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        def _fail_load_keyed_payload(*args, **kwargs):
            raise OSError(f"cannot read {_PRIVATE_ERROR_PATH}: Permission denied")

        monkeypatch.setattr(
            lut_router.LUTManager,
            "_load_keyed_payload",
            staticmethod(_fail_load_keyed_payload),
        )
        target_logger = _attach_lut_logger(caplog, level=logging.WARNING)

        try:
            response = client.post(
                "/api/lut/upload",
                files={
                    "file": (
                        "secret.json",
                        (
                            b'{"entries":[{"rgb":[255,255,255],"recipe":["White"]}],'
                            b'"palette":{"White":{"material":"PLA"}}}'
                        ),
                        "application/json",
                    )
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 422
        _assert_safe_error_detail(
            response,
            "Invalid LUT file. Use a supported LUT format with readable color entries.",
        )
        records = _records_for_event(caplog, "lut_upload_validation_failed")
        assert len(records) == 1
        assert records[0].error_type == "_UploadedLutValidationError"
        assert _PRIVATE_ERROR_PATH in records[0].error_message

    def test_upload_save_failure_uses_safe_detail_and_logs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        def _fail_copy(_src, _dst):
            raise PermissionError(f"Permission denied: '{_PRIVATE_ERROR_PATH}'")

        monkeypatch.setattr(lut_router.shutil, "copy2", _fail_copy)
        target_logger = _attach_lut_logger(caplog)

        try:
            response = client.post(
                "/api/lut/upload",
                files={
                    "file": (
                        "save-failure.json",
                        (
                            b'{"entries":[{"rgb":[255,255,255],"recipe":["White"]}],'
                            b'"palette":{"White":{"material":"PLA"}}}'
                        ),
                        "application/json",
                    )
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 500
        _assert_safe_error_detail(
            response,
            "Unable to save the LUT upload. Check server storage permissions and try again.",
        )
        records = _records_for_event(caplog, "lut_upload_failed")
        assert len(records) == 1
        assert records[0].error_type == "PermissionError"
        assert _PRIVATE_ERROR_PATH in records[0].error_message

    def test_recipe_color_prediction_failure_uses_safe_detail_and_logs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        def _fail_load_lut(_path: str):
            raise OSError(f"cannot read {_PRIVATE_ERROR_PATH}: Permission denied")

        monkeypatch.setattr(
            lut_router.LUTManager,
            "get_lut_path",
            staticmethod(lambda _name: "/fake/source.json"),
        )
        monkeypatch.setattr(
            lut_router.LUTManager,
            "load_lut_with_metadata",
            staticmethod(_fail_load_lut),
        )
        target_logger = _attach_lut_logger(caplog, level=logging.WARNING)

        try:
            response = client.post(
                "/api/lut/Faulty/predict-recipe-color",
                json={
                    "recipe": [0, 0, 0, 0, 0],
                    "color_layers": 5,
                    "layer_height_mm": 0.08,
                    "layer_order": "Top2Bottom",
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 422
        _assert_safe_error_detail(
            response,
            (
                "Unable to predict the recipe color. Check that the LUT supports "
                "recipe prediction and the recipe parameters are valid."
            ),
        )
        records = _records_for_event(caplog, "lut_recipe_color_prediction_failed")
        assert len(records) == 1
        assert records[0].error_type == "OSError"
        assert _PRIVATE_ERROR_PATH in records[0].error_message

    def test_recipe_search_failure_uses_safe_detail_and_logs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        def _fail_load_lut(_path: str):
            raise OSError(f"cannot read {_PRIVATE_ERROR_PATH}: Permission denied")

        monkeypatch.setattr(
            lut_router.LUTManager,
            "get_lut_path",
            staticmethod(lambda _name: "/fake/source.json"),
        )
        monkeypatch.setattr(
            lut_router.LUTManager,
            "load_lut_with_metadata",
            staticmethod(_fail_load_lut),
        )
        target_logger = _attach_lut_logger(caplog, level=logging.WARNING)

        try:
            response = client.post(
                "/api/lut/Faulty/search-recipes",
                json={
                    "pattern": "WWWWW",
                    "color_layers": 5,
                    "layer_height_mm": 0.08,
                    "layer_order": "Top2Bottom",
                    "limit": 1,
                },
            )
        finally:
            target_logger.removeHandler(caplog.handler)

        assert response.status_code == 422
        _assert_safe_error_detail(
            response,
            (
                "Unable to search LUT recipes. Check that the LUT supports recipe "
                "search and the search parameters are valid."
            ),
        )
        records = _records_for_event(caplog, "lut_recipe_search_failed")
        assert len(records) == 1
        assert records[0].error_type == "OSError"
        assert _PRIVATE_ERROR_PATH in records[0].error_message

    @pytest.mark.parametrize(
        ("method", "url", "json_payload"),
        [
            ("GET", f"/api/lut/{quote(_PRIVATE_LUT_NAME, safe='')}/info", None),
            ("GET", f"/api/lut/{quote(_PRIVATE_LUT_NAME, safe='')}/colors", None),
            (
                "POST",
                "/api/lut/merge",
                {"primary_name": _PRIVATE_LUT_NAME, "secondary_names": ["secondary"]},
            ),
            (
                "POST",
                "/api/lut/compare",
                {"lut_a_name": _PRIVATE_LUT_NAME, "lut_b_name": "secondary"},
            ),
            (
                "POST",
                f"/api/lut/{quote(_PRIVATE_LUT_NAME, safe='')}/predict-recipe-color",
                {
                    "recipe": [0, 0, 0, 0, 0],
                    "color_layers": 5,
                    "layer_height_mm": 0.08,
                    "layer_order": "Top2Bottom",
                },
            ),
            (
                "POST",
                f"/api/lut/{quote(_PRIVATE_LUT_NAME, safe='')}/search-recipes",
                {
                    "pattern": "WWWWW",
                    "color_layers": 5,
                    "layer_height_mm": 0.08,
                    "layer_order": "Top2Bottom",
                    "limit": 1,
                },
            ),
        ],
    )
    def test_missing_lut_errors_do_not_echo_requested_lut_name(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        method: str,
        url: str,
        json_payload: dict[str, object] | None,
    ) -> None:
        monkeypatch.setattr(
            lut_router.LUTManager,
            "get_lut_path",
            staticmethod(lambda _name: None),
        )
        app_logger = logging.getLogger("lumina.api.app")
        app_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=app_logger.name)

        try:
            response = client.request(method, url, json=json_payload)
        finally:
            app_logger.removeHandler(caplog.handler)

        assert response.status_code == 404
        assert response.json()["detail"] == _LUT_NOT_FOUND_PUBLIC_DETAIL
        assert _PRIVATE_LUT_NAME not in response.text
        assert "LUT not found:" not in response.text
        _assert_latest_http_error_log_safe(
            caplog,
            expected_detail=_LUT_NOT_FOUND_PUBLIC_DETAIL,
            forbidden_fragments=(_PRIVATE_LUT_NAME, "LUT not found:"),
        )

    def test_missing_lut_details_error_does_not_echo_requested_lut_name(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        class _MissingDetailsService:
            def get_lut_details(self, _lut_name: str):
                raise KeyError(_PRIVATE_LUT_NAME)

        service = _MissingDetailsService()
        monkeypatch.setattr(lut_router, "_lut_details_service", service)
        monkeypatch.setattr(lut_router, "get_lut_details_service", lambda: service)
        app_logger = logging.getLogger("lumina.api.app")
        app_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=app_logger.name)

        try:
            response = client.get(f"/api/lut/{quote(_PRIVATE_LUT_NAME, safe='')}/details")
        finally:
            app_logger.removeHandler(caplog.handler)

        assert response.status_code == 404
        assert response.json()["detail"] == _LUT_NOT_FOUND_PUBLIC_DETAIL
        assert _PRIVATE_LUT_NAME not in response.text
        assert "LUT not found:" not in response.text
        _assert_latest_http_error_log_safe(
            caplog,
            expected_detail=_LUT_NOT_FOUND_PUBLIC_DETAIL,
            forbidden_fragments=(_PRIVATE_LUT_NAME, "LUT not found:"),
        )


def test_public_color_mode_canonicalizes_legacy_variants() -> None:
    assert _canonicalize_public_color_mode("8-Color") == "8-Color Max"
    assert _canonicalize_public_color_mode("4-Color CMYW") == "4-Color (CMYW)"
    assert _canonicalize_public_color_mode("6-Color (RYBW)") == "6-Color (RYBWGK 1296)"
    assert _canonicalize_public_color_mode("6-Color RYBWGK") == "6-Color (RYBWGK 1296)"


def test_public_lut_path_reference_keeps_known_roots_relative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preset_root = tmp_path / "lut-preset"
    preset_path = preset_root / "Brand" / "Visible.json"
    monkeypatch.setattr(lut_router.LUTManager, "LUT_PRESET_DIR", str(preset_root))

    reference_path = get_reference_db_root() / "PLA" / "BambuLab" / "CMYW_008_5L.json"

    assert public_lut_path_reference(preset_path) == "lut-preset/Brand/Visible.json"
    assert public_lut_path_reference(reference_path).startswith("reference-db/")
    assert not public_lut_path_reference(reference_path).startswith("/")


def _axis_range() -> SimpleNamespace:
    return SimpleNamespace(min=0.0, max=1.0)


def _fake_lut_detail(path: str) -> SimpleNamespace:
    return SimpleNamespace(
        name="Secret LUT",
        path=path,
        manufacturer="Private",
        manufacturer_source="metadata",
        material_type="PLA",
        material_source="metadata",
        color_mode="4-Color (RYBW)",
        color_count=1,
        source_kind="legacy_lookup",
        schema_version="1.0",
        capabilities=[],
        supported_modes=[],
        raw_metadata={},
        palette=[
            {
                "color": "White",
                "material": "PLA",
                "hex_color": "#FFFFFF",
                "color_name": "White",
            }
        ],
        coverage_stats=SimpleNamespace(
            entry_count=1,
            plotted_point_count=1,
            l_range=_axis_range(),
            a_range=_axis_range(),
            b_range=_axis_range(),
            r_range=_axis_range(),
            g_range=_axis_range(),
            b_rgb_range=_axis_range(),
        ),
        lab_points=[],
        lab_points_3d=[],
        lab_hull=[],
        rgb_points=[],
        max_color_layers=4,
        layer_height_mm=0.2,
        line_width_mm=0.4,
        base_layers=1,
        base_channel_idx=0,
        layer_order="base-first",
    )


class _SuccessfulDetailsService:
    def get_catalog(self) -> SimpleNamespace:
        return SimpleNamespace(
            groups=[
                SimpleNamespace(
                    manufacturer="Private",
                    items=[
                        SimpleNamespace(
                            name="Secret LUT",
                            path=_PRIVATE_ERROR_PATH,
                            color_mode="4-Color (RYBW)",
                            source_kind="legacy_lookup",
                            manufacturer="Private",
                            material_type="PLA",
                            manufacturer_source="metadata",
                            material_source="metadata",
                            search_tokens=["secret", "private"],
                            revision="catalog-read-1",
                        )
                    ],
                )
            ]
        )

    def get_lut_details(self, _lut_name: str) -> SimpleNamespace:
        return _fake_lut_detail(_PRIVATE_ERROR_PATH)


def test_public_lut_listing_and_catalog_responses_hide_local_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lut_router._clear_lut_list_cache()
    service = _SuccessfulDetailsService()
    monkeypatch.setattr(lut_router, "_lut_details_service", service)
    monkeypatch.setattr(lut_router, "get_lut_details_service", lambda: service)
    monkeypatch.setattr(
        lut_router.LUTManager,
        "get_all_lut_files",
        staticmethod(lambda: {"Secret LUT": _PRIVATE_ERROR_PATH}),
    )
    monkeypatch.setattr(
        lut_router.LUTManager,
        "infer_color_mode",
        staticmethod(lambda _name, _path: "4-Color (RYBW)"),
    )
    monkeypatch.setattr(
        lut_router.LUTManager,
        "get_source_catalog",
        staticmethod(
            lambda: {
                "legacy_groups": [
                    {
                        "group_name": "Preset",
                        "items": [
                            {
                                "name": "Secret LUT",
                                "color_mode": "4-Color (RYBW)",
                                "path": _PRIVATE_ERROR_PATH,
                                "fingerprint": "fp-secret",
                            }
                        ],
                    }
                ],
                "native_brand_groups": [
                    {
                        "brand_key": "secret_native",
                        "material_type": "PLA",
                        "vendor": "Private",
                        "display_name": "Private PLA",
                        "db_options": [
                            {
                                "name": "native-secret.json",
                                "path": _PRIVATE_WINDOWS_LUT_PATH,
                                "color_mode": "4-Color (RYBW)",
                                "fingerprint": "fp-native",
                            }
                        ],
                        "default_db_names": ["native-secret.json"],
                        "package_name": None,
                        "model_name": None,
                        "supported_modes": [],
                    }
                ],
            }
        ),
    )

    list_response = client.get("/api/lut/list")
    catalog_response = client.get("/api/lut/catalog")
    details_catalog_response = client.get("/api/lut/details/catalog")
    detail_response = client.get("/api/lut/Secret%20LUT/details")

    assert list_response.status_code == 200
    assert catalog_response.status_code == 200
    assert details_catalog_response.status_code == 200
    assert detail_response.status_code == 200
    assert _PRIVATE_ERROR_PATH not in list_response.text
    assert _PRIVATE_ERROR_PATH not in catalog_response.text
    assert _PRIVATE_ERROR_PATH not in details_catalog_response.text
    assert _PRIVATE_ERROR_PATH not in detail_response.text
    assert _PRIVATE_WINDOWS_LUT_PATH not in catalog_response.text

    listed_path = list_response.json()["luts"][0]["path"]
    legacy_path = catalog_response.json()["legacy_groups"][0]["items"][0]["path"]
    native_path = catalog_response.json()["native_brand_groups"][0]["db_options"][0]["path"]
    details_catalog_path = details_catalog_response.json()["groups"][0]["items"][0]["path"]
    detail_path = detail_response.json()["path"]
    assert {listed_path, legacy_path, details_catalog_path, detail_path} == {listed_path}
    _assert_public_lut_path(listed_path)
    _assert_public_lut_path(native_path)


def test_public_lut_details_responses_hide_local_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = _SuccessfulDetailsService()
    monkeypatch.setattr(lut_router, "_lut_details_service", service)
    monkeypatch.setattr(lut_router, "get_lut_details_service", lambda: service)

    catalog_response = client.get("/api/lut/details/catalog")
    detail_response = client.get("/api/lut/Secret%20LUT/details")

    assert catalog_response.status_code == 200
    assert detail_response.status_code == 200
    assert _PRIVATE_ERROR_PATH not in catalog_response.text
    assert _PRIVATE_ERROR_PATH not in detail_response.text

    catalog_path = catalog_response.json()["groups"][0]["items"][0]["path"]
    detail_path = detail_response.json()["path"]
    assert catalog_path == detail_path
    _assert_public_lut_path(catalog_path)


def test_lut_list_reuses_file_metadata_until_signature_changes(tmp_path: Path) -> None:
    """Repeated list calls reuse inferred metadata within the TTL."""
    lut_router._invalidate_lut_details_service_cache()
    lut_path = tmp_path / "cached.json"
    lut_path.write_text('{"color_mode": "4-Color (RYBW)", "entries": []}', encoding="utf-8")

    try:
        with (
            patch(
                "api.routers.lut.LUTManager.get_all_lut_files",
                return_value={"Cached": str(lut_path)},
            ),
            patch(
                "api.routers.lut.LUTManager.infer_color_mode",
                return_value="4-Color (RYBW)",
            ) as mock_infer_mode,
            patch("api.routers.lut.time.monotonic", side_effect=[0.0, 1.0, 31.0]),
        ):
            first = lut_router.list_luts()
            second = lut_router.list_luts()
            lut_path.write_text(
                '{"color_mode": "4-Color (RYBW)", "entries": [], "changed": true}',
                encoding="utf-8",
            )
            third = lut_router.list_luts()

        assert [item.name for item in first.luts] == ["Cached"]
        assert [item.name for item in second.luts] == ["Cached"]
        assert [item.name for item in third.luts] == ["Cached"]
        assert mock_infer_mode.call_count == 2
    finally:
        lut_router._invalidate_lut_details_service_cache()


def test_lut_list_skips_signature_scan_within_hot_cache_window(tmp_path: Path) -> None:
    """Hot list calls should not stat every LUT file on each request."""
    lut_router._invalidate_lut_details_service_cache()
    lut_path = tmp_path / "cached.json"
    lut_path.write_text('{"color_mode": "4-Color (RYBW)", "entries": []}', encoding="utf-8")

    try:
        with (
            patch(
                "api.routers.lut.LUTManager.get_all_lut_files",
                return_value={"Cached": str(lut_path)},
            ),
            patch(
                "api.routers.lut.LUTManager.infer_color_mode",
                return_value="4-Color (RYBW)",
            ),
            patch(
                "api.routers.lut._build_lut_list_signature",
                wraps=lut_router._build_lut_list_signature,
            ) as mock_signature,
            patch("api.routers.lut.time.monotonic", side_effect=[0.0, 1.0]),
        ):
            first = lut_router.list_luts()
            second = lut_router.list_luts()

        assert [item.name for item in first.luts] == ["Cached"]
        assert [item.name for item in second.luts] == ["Cached"]
        assert mock_signature.call_count == 1
    finally:
        lut_router._invalidate_lut_details_service_cache()


def test_lut_list_renews_hot_window_when_signature_is_unchanged(tmp_path: Path) -> None:
    """An unchanged signature refresh should renew the no-stat hot window."""
    lut_router._invalidate_lut_details_service_cache()
    lut_path = tmp_path / "cached.json"
    lut_path.write_text('{"color_mode": "4-Color (RYBW)", "entries": []}', encoding="utf-8")

    try:
        with (
            patch(
                "api.routers.lut.LUTManager.get_all_lut_files",
                return_value={"Cached": str(lut_path)},
            ),
            patch(
                "api.routers.lut.LUTManager.infer_color_mode",
                return_value="4-Color (RYBW)",
            ),
            patch(
                "api.routers.lut._build_lut_list_signature",
                wraps=lut_router._build_lut_list_signature,
            ) as mock_signature,
            patch("api.routers.lut.time.monotonic", side_effect=[0.0, 6.0, 7.0]),
        ):
            lut_router.list_luts()
            lut_router.list_luts()
            lut_router.list_luts()

        assert mock_signature.call_count == 2
    finally:
        lut_router._invalidate_lut_details_service_cache()


def _raw_lut_colors(count: int) -> list[dict]:
    return [{"hex": "#000000", "color": (0, 0, 0)} for _ in range(count)]


# =========================================================================
# 1. GET /api/lut/{name}/info — success scenario (Requirement 6.7)
# =========================================================================


class TestLutInfoSuccess:
    """Verify the info endpoint returns correct mode and count."""

    @patch(
        "api.routers.lut.LUTManager.load_lut_with_metadata",
        return_value=(
            None,
            None,
            LUTMetadata(
                schema_version="2.0",
                capabilities=["legacy_lookup", "predictive_match", "dynamic_layer_height", "dynamic_layer_count"],
                palette=[
                    PaletteEntry(
                        color="White",
                        material="PLA Basic",
                        hex_color="#FFFFFF",
                        color_name="Jade White",
                    )
                ],
                extensions={
                    "source_kind": "predictive_package",
                    "runtime_package": {
                        "defaults": {"threshold": 5.0},
                        "modes": {},
                    }
                },
            ),
        ),
    )
    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("8-Color", 2738))
    @patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/path.npy")
    def test_info_returns_200_with_correct_fields(
        self, mock_path, mock_detect, mock_load_meta
    ) -> None:
        response = client.get("/api/lut/TestLUT/info")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "TestLUT"
        assert data["color_mode"] == "8-Color Max"
        assert data["color_count"] == 2738
        assert data["schema_version"] == "2.0"
        assert data["supports_predictive_match"] is True
        assert data["supports_dynamic_layer_height"] is True
        assert data["supports_dynamic_layer_count"] is True
        assert data["supports_custom_recipe"] is False
        assert data["source_kind"] == "predictive_package"
        assert data["supported_modes"] == []
        assert data["palette"] == [
            {
                "color": "White",
                "material": "PLA Basic",
                "hex_color": "#FFFFFF",
                "color_name": "Jade White",
            }
        ]
        assert "predictive_match" in data["capabilities"]

    @patch(
        "api.routers.lut.LUTManager.load_lut_with_metadata",
        return_value=(None, None, LUTMetadata()),
    )
    @patch("api.routers.lut.LUTManager.infer_color_mode", return_value="4-Color (RYBW)")
    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("4-Color", 1024))
    @patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/path.npy")
    def test_info_prefers_canonicalized_color_mode_for_response(
        self,
        mock_path,
        mock_detect,
        mock_infer,
        mock_load_meta,
    ) -> None:
        response = client.get("/api/lut/TestLegacy/info")
        assert response.status_code == 200
        data = response.json()
        assert data["color_mode"] == "4-Color (RYBW)"
        assert data["color_count"] == 1024


# =========================================================================
# 2. GET /api/lut/{name}/info — 404 scenario (Requirement 6.7)
# =========================================================================


class TestLutInfoNotFound:
    """Verify the info endpoint returns 404 for non-existent LUT."""

    @patch("api.routers.lut.LUTManager.get_lut_path", return_value=None)
    def test_info_returns_404_when_lut_not_found(self, mock_path) -> None:
        response = client.get("/api/lut/NonExistent/info")
        assert response.status_code == 404
        assert response.json()["detail"] == _LUT_NOT_FOUND_PUBLIC_DETAIL


# =========================================================================
# 3. GET /api/lut/session/{session_id}/info — works for sessions without
#    a globally-known LUT name (material archive / native bundle).
# =========================================================================


class TestSessionLutInfo:
    """Verify the session-scoped LUT info endpoint."""

    def _override_store(self, store: SessionStore) -> None:
        app.dependency_overrides[get_session_store] = lambda: store

    def _clear_override(self) -> None:
        app.dependency_overrides.pop(get_session_store, None)

    def test_returns_404_when_session_missing(self) -> None:
        store = SessionStore(ttl=60)
        self._override_store(store)
        try:
            response = client.get("/api/lut/session/does-not-exist/info")
            assert response.status_code == 404
            assert "Session not found" in response.json()["detail"]
        finally:
            self._clear_override()

    def test_returns_409_when_session_has_no_lut(self) -> None:
        store = SessionStore(ttl=60)
        session_id = store.create()
        self._override_store(store)
        try:
            response = client.get(f"/api/lut/session/{session_id}/info")
            assert response.status_code == 409
            assert "LUT" in response.json()["detail"]
        finally:
            self._clear_override()

    @patch(
        "api.routers.lut.LUTManager.load_lut_with_metadata",
        return_value=(
            None,
            None,
            LUTMetadata(
                palette=[
                    PaletteEntry(
                        color="White",
                        material="PLA Basic",
                        hex_color="#FFFFFF",
                        color_name="Jade White",
                    ),
                    PaletteEntry(
                        color="Red",
                        material="PLA Basic",
                        hex_color="#FF0000",
                        color_name="Ruby",
                    ),
                ],
            ),
        ),
    )
    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("8-Color", 2))
    def test_returns_channel_palette_for_session_lut(
        self,
        mock_detect,
        mock_load_meta,
        tmp_path: Path,
    ) -> None:
        # Need a real file path for os.path.exists guard in the endpoint.
        lut_file = tmp_path / "session_lut.json"
        lut_file.write_text("{}", encoding="utf-8")

        store = SessionStore(ttl=60)
        session_id = store.create()
        store.put(session_id, "lut_path", str(lut_file))
        store.put(session_id, "lut_name", "Material Archive Session")

        self._override_store(store)
        try:
            response = client.get(f"/api/lut/session/{session_id}/info")
            assert response.status_code == 200
            data = response.json()
            assert data["name"] == "Material Archive Session"
            assert data["color_mode"] == "8-Color Max"
            # Channel palette should be returned in LUT order, not quantized order.
            assert [entry["color"] for entry in data["palette"]] == ["White", "Red"]
            assert data["palette"][0]["hex_color"] == "#FFFFFF"
            assert data["palette"][1]["hex_color"] == "#FF0000"
        finally:
            self._clear_override()

    def test_generate_schema_accepts_legacy_8_color_alias(self) -> None:
        request = ConvertGenerateRequest(lut_name="Legacy8", color_mode="8-Color")

        assert request.color_mode is ColorMode.EIGHT_COLOR

    def test_preview_schema_accepts_legacy_8_color_alias(self) -> None:
        request = ConvertPreviewRequest(lut_name="Legacy8", color_mode="8-Color")

        assert request.color_mode is ColorMode.EIGHT_COLOR

    @patch(
        "api.routers.lut.LUTManager.load_lut_with_metadata",
        return_value=(None, None, LUTMetadata()),
    )
    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("BW", 2))
    def test_falls_back_to_file_stem_when_lut_name_missing(
        self,
        mock_detect,
        mock_load_meta,
        tmp_path: Path,
    ) -> None:
        lut_file = tmp_path / "fallback_name.json"
        lut_file.write_text("{}", encoding="utf-8")

        store = SessionStore(ttl=60)
        session_id = store.create()
        store.put(session_id, "lut_path", str(lut_file))
        # Intentionally no "lut_name" stored.

        self._override_store(store)
        try:
            response = client.get(f"/api/lut/session/{session_id}/info")
            assert response.status_code == 200
            assert response.json()["name"] == "fallback_name"
        finally:
            self._clear_override()

    def test_returns_material_archive_palette_for_session_without_lut_file(self) -> None:
        store = SessionStore(ttl=60)
        session_id = store.create()
        store.put(session_id, "lut_path", "__material_archive__")
        store.put(session_id, "lut_name", "__material_archive__")
        store.put(session_id, "material_source", "material_archive")
        store.put(session_id, "selected_materials", [
            "brand/red-pla",
            "brand/green-pla",
            "brand/blue-pla",
            "brand/yellow-pla",
            "brand/cyan-pla",
        ])
        store.put(session_id, "material_layer_count", 7)
        store.put(session_id, "material_layer_height_mm", 0.08)
        store.put(
            session_id,
            "preview_cache",
            {
                "color_layers": 7,
                "layer_height_mm": 0.08,
                "slot_names": [
                    "PLA Red",
                    "PLA Green",
                    "PLA Blue",
                    "PLA Yellow",
                    "PLA Cyan",
                ],
                "preview_colors": {
                    0: [255, 0, 0, 255],
                    1: [0, 255, 0, 255],
                    2: [0, 0, 255, 255],
                    3: [255, 255, 0, 255],
                    4: [0, 255, 255, 255],
                },
            },
        )

        self._override_store(store)
        try:
            response = client.get(f"/api/lut/session/{session_id}/info")
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["name"] == "__material_archive__"
            assert data["color_mode"] == "Material Archive"
            assert data["color_count"] == 5
            assert data["max_color_layers"] == 7
            assert data["layer_height_mm"] == 0.08
            assert [entry["color"] for entry in data["palette"]] == [
                "PLA Red",
                "PLA Green",
                "PLA Blue",
                "PLA Yellow",
                "PLA Cyan",
            ]
            assert [entry["material"] for entry in data["palette"]] == [
                "brand/red-pla",
                "brand/green-pla",
                "brand/blue-pla",
                "brand/yellow-pla",
                "brand/cyan-pla",
            ]
            assert [entry["hex_color"] for entry in data["palette"]] == [
                "#FF0000",
                "#00FF00",
                "#0000FF",
                "#FFFF00",
                "#00FFFF",
            ]
        finally:
            self._clear_override()

    def test_material_archive_session_base_channel_uses_white_slot(self) -> None:
        store = SessionStore(ttl=60)
        session_id = store.create()
        store.put(session_id, "lut_path", "__material_archive__")
        store.put(session_id, "lut_name", "__material_archive__")
        store.put(session_id, "material_source", "material_archive")
        store.put(session_id, "selected_materials", [
            "瑞贝思/瑞贝思 PLA 绿",
            "瑞贝思/瑞贝思 PLA 黄",
            "瑞贝思/瑞贝思 PLA 白",
        ])
        store.put(
            session_id,
            "preview_cache",
            {
                "color_layers": 10,
                "layer_height_mm": 0.08,
                "slot_names": [
                    "瑞贝思 PLA 绿",
                    "瑞贝思 PLA 黄",
                    "瑞贝思 PLA 白",
                ],
                "preview_colors": {
                    0: [67, 160, 71, 255],
                    1: [255, 212, 0, 255],
                    2: [245, 245, 245, 255],
                },
            },
        )

        self._override_store(store)
        try:
            response = client.get(f"/api/lut/session/{session_id}/info")
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["base_channel_idx"] == 2
            assert data["max_color_layers"] == 10
        finally:
            self._clear_override()


class TestLutColorsLayout:
    """Verify LUT colors card payloads use flattened LUT rows."""

    def test_colors_flattens_grid_rgb_before_resolving_layout(self) -> None:
        rgb = np.zeros((32, 32, 3), dtype=np.uint8)

        with (
            patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/four.npy"),
            patch(
                "api.routers.lut.LUTManager.load_lut_with_metadata",
                return_value=(rgb, None, LUTMetadata(color_mode="4-Color (RYBW)")),
            ),
            patch(
                "core.converter.extract_lut_available_colors",
                return_value=_raw_lut_colors(1024),
            ),
        ):
            response = client.get("/api/lut/FourGrid/colors")

        assert response.status_code == 200
        data = response.json()
        assert data["layout"]["total_count"] == 1024
        assert data["layout"]["pages"][0]["data_cols"] == 32
        assert len(data["cards"]) == 1
        assert len(data["cards"][0]["colors"]) == 1024

    def test_colors_uses_extended_page_1_padding_for_standalone_1024_lut(self) -> None:
        rgb = np.zeros((1024, 3), dtype=np.uint8)

        with (
            patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/five-page-1.json"),
            patch(
                "api.routers.lut.LUTManager.load_lut_with_metadata",
                return_value=(rgb, None, LUTMetadata(color_mode="5-Color Extended")),
            ),
            patch(
                "core.converter.extract_lut_available_colors",
                return_value=_raw_lut_colors(1024),
            ),
        ):
            response = client.get("/api/lut/FivePage1/colors")

        assert response.status_code == 200
        data = response.json()
        page = data["layout"]["pages"][0]
        assert page["data_rows"] == 32
        assert page["data_cols"] == 32
        assert page["padding"] == 4
        assert page["physical_rows"] == 40
        assert page["physical_cols"] == 40
        assert data["cards"][0]["page"]["padding"] == 4
        assert len(data["cards"][0]["colors"]) == 1024

    def test_colors_splits_flattened_8color_grid_into_two_cards(self) -> None:
        rgb = np.zeros((74, 37, 3), dtype=np.uint8)

        with (
            patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/eight.npy"),
            patch(
                "api.routers.lut.LUTManager.load_lut_with_metadata",
                return_value=(rgb, None, LUTMetadata(color_mode="8-Color Max")),
            ),
            patch(
                "core.converter.extract_lut_available_colors",
                return_value=_raw_lut_colors(2738),
            ),
        ):
            response = client.get("/api/lut/EightGrid/colors")

        assert response.status_code == 200
        data = response.json()
        assert data["layout"]["total_count"] == 2738
        assert [card["page"]["card_label"] for card in data["cards"]] == ["A", "B"]
        assert [len(card["colors"]) for card in data["cards"]] == [1369, 1369]


class TestPredictRecipeColor:
    """Verify predictive recipe endpoint returns predicted color data."""

    @patch(
        "api.routers.lut.predict_recipe_color",
        return_value={
            "rgb": [255, 255, 255],
            "lab": [100.0, 0.0, 0.0],
            "runtime_mode_key": "0.08x5",
            "source": "stage_model",
        },
    )
    @patch(
        "api.routers.lut.LUTManager.load_lut_with_metadata",
        return_value=(None, None, LUTMetadata()),
    )
    @patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/source.json")
    def test_predict_recipe_color_returns_200(
        self,
        mock_path,
        mock_load_meta,
        mock_predict,
    ) -> None:
        response = client.post(
            "/api/lut/TestSource/predict-recipe-color",
            json={
                "recipe": [0, 0, 0, 0, 0],
                "color_layers": 5,
                "layer_height_mm": 0.08,
                "layer_order": "Top2Bottom",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["rgb"] == [255, 255, 255]
        assert data["runtime_mode_key"] == "0.08x5"

    @patch(
        "api.routers.lut.predict_recipe_color",
        side_effect=ValueError("Recipe is not present in the runtime package; exact prediction unavailable for package-only source"),
    )
    @patch(
        "api.routers.lut.LUTManager.load_lut_with_metadata",
        return_value=(None, None, LUTMetadata()),
    )
    @patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/source.json")
    def test_predict_recipe_color_returns_422_for_non_exact_package_only_recipe(
        self,
        mock_path,
        mock_load_meta,
        mock_predict,
    ) -> None:
        response = client.post(
            "/api/lut/TestSource/predict-recipe-color",
            json={
                "recipe": [0, 1, 0, 1, 0],
                "color_layers": 5,
                "layer_height_mm": 0.08,
                "layer_order": "Top2Bottom",
            },
        )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail == (
            "Unable to predict the recipe color. Check that the LUT supports "
            "recipe prediction and the recipe parameters are valid."
        )
        assert "exact prediction unavailable" not in detail


class TestSourceKindFallback:
    """Verify plain V2 predictive LUTs still surface predictive source_kind without explicit extension."""

    @patch(
        "api.routers.lut.LUTManager.load_lut_with_metadata",
        return_value=(
            None,
            None,
            LUTMetadata(
                schema_version="2.0",
                capabilities=["predictive_match"],
                extensions={
                    "runtime_package": {
                        "defaults": {"threshold": 5.0},
                        "modes": {},
                    }
                },
            ),
        ),
    )
    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("8-Color", 2738))
    @patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/path.json")
    def test_info_source_kind_falls_back_to_predictive_package(
        self, mock_path, mock_detect, mock_load_meta
    ) -> None:
        response = client.get("/api/lut/TestRuntimePackage/info")
        assert response.status_code == 200
        data = response.json()
        assert data["source_kind"] == "predictive_package"


class TestSourceCatalog:
    """Verify the new LUT/source catalog exposes both legacy and native groupings."""

    def test_list_remains_legacy_only(self) -> None:
        response = client.get("/api/lut/list")
        assert response.status_code == 200

        data = response.json()["luts"]
        names = {entry["name"] for entry in data}
        assert not any(name.startswith("ReferenceDB -") for name in names)
        assert not any(name.startswith("ReferencePack -") for name in names)
        assert not any(name.startswith("ReferenceModel -") for name in names)

    def test_catalog_includes_legacy_and_native_groups(self) -> None:
        response = client.get("/api/lut/catalog")
        assert response.status_code == 200

        data = response.json()
        assert "legacy_groups" in data
        assert "native_brand_groups" in data

        legacy_group_names = {group["group_name"] for group in data["legacy_groups"]}
        assert {"Preset", "ReferenceDB", "ReferencePack", "ReferenceModel"} & legacy_group_names

        native_groups = data["native_brand_groups"]
        assert native_groups

        bambu_pla = next(
            group
            for group in native_groups
            if group["vendor"] == "BambuLab" and group["material_type"] == "PLA"
        )
        assert bambu_pla["brand_key"]
        assert bambu_pla["display_name"]
        assert bambu_pla["db_options"]
        assert bambu_pla["default_db_names"]
        assert bambu_pla["package_name"] == "bambulab_pla.msgpack"
        assert bambu_pla["model_name"] == "bambulab_pla_stage_B.json"
        assert bambu_pla["supported_modes"]
        option_names = {option["name"] for option in bambu_pla["db_options"]}
        assert bambu_pla["default_db_names"][0] in option_names

    @patch(
        "api.routers.lut.LUTManager.get_source_catalog",
        return_value={
            "legacy_groups": [
                {
                    "group_name": "Preset",
                    "items": [
                        {
                            "name": "Legacy8",
                            "color_mode": "8-Color",
                            "path": "/legacy8.npy",
                            "fingerprint": "fp-legacy8",
                        }
                    ],
                }
            ],
            "native_brand_groups": [
                {
                    "brand_key": "bambulab_pla",
                    "material_type": "PLA",
                    "vendor": "BambuLab",
                    "display_name": "BambuLab PLA",
                    "db_options": [
                        {
                            "name": "Eight.json",
                            "path": "/Eight.json",
                            "color_mode": "8-Color",
                            "fingerprint": "fp-eight",
                        }
                    ],
                    "default_db_names": ["Eight.json"],
                    "package_name": None,
                    "model_name": None,
                    "supported_modes": [],
                }
            ],
        },
    )
    def test_catalog_canonicalizes_legacy_8_color_aliases(self, mock_catalog) -> None:
        response = client.get("/api/lut/catalog")
        assert response.status_code == 200

        data = response.json()
        assert data["legacy_groups"][0]["items"][0]["color_mode"] == "8-Color Max"
        assert data["native_brand_groups"][0]["db_options"][0]["color_mode"] == "8-Color Max"

    def test_catalog_falls_back_to_bundled_native_assets_when_reference_repo_is_missing(self) -> None:
        from utils.lut_manager import LUTManager

        bundled_root = Path("assets/native_sources/ChromaPrint3D").resolve()
        assert bundled_root.joinpath("data", "model_packs", "bambulab_pla.msgpack").exists()
        assert bundled_root.joinpath("data", "models", "forward", "bambulab_pla_stage_B.json").exists()
        assert bundled_root.joinpath("data", "dbs", "PLA", "BambuLab", "CMYW_008_5L.json").exists()

        LUTManager.invalidate_native_source_index_cache()
        resolved_path = None
        missing_reference_root = Path(os.getcwd(), "missing-reference-root-does-not-exist")

        try:
            with (
                patch(
                    "core.native_reference.iter_reference_repo_candidates",
                    return_value=(missing_reference_root, bundled_root),
                ),
                patch("utils.lut_manager.LUTManager._build_legacy_catalog_groups", return_value=[]),
            ):
                catalog = LUTManager.get_source_catalog()
                native_groups = catalog["native_brand_groups"]
                assert native_groups

                bambu_pla = next(
                    group for group in native_groups if group["brand_key"] == "bambulab_pla"
                )
                assert bambu_pla["package_name"] == "bambulab_pla.msgpack"
                assert bambu_pla["model_name"] == "bambulab_pla_stage_B.json"
                assert "CMYW_008_5L.json" in bambu_pla["default_db_names"]

                resolved_path, resolved_name = LUTManager.resolve_source_selection(
                    source_kind="native_bundle",
                    material_type="PLA",
                    vendor="BambuLab",
                    db_names=["CMYW_008_5L.json"],
                )

                assert Path(resolved_path).exists()
                assert resolved_name == "BambuLab PLA"
        finally:
            LUTManager.invalidate_native_source_index_cache()
            if resolved_path and Path(resolved_path).exists():
                resolved_resolved = Path(resolved_path).resolve()
                if not str(resolved_resolved).startswith(str(bundled_root)):
                    resolved_resolved.unlink(missing_ok=True)

    def test_manager_catalog_payload_omits_internal_resolution_fields(self) -> None:
        fake_path = os.path.join("C:\\tmp", "fake.msgpack")
        native_ctx = NativeReferenceContext(
            source_kind=SOURCE_KIND_PACKAGE,
            primary_path=fake_path,
            package_path=fake_path,
            stage_model_path=os.path.join("C:\\tmp", "fake_stage.json"),
            db_paths=(os.path.join("C:\\tmp", "A.json"),),
            vendor="BambuLab",
            material_type="PLA",
        )

        from utils.lut_manager import LUTManager

        LUTManager.invalidate_native_source_index_cache()
        try:
            with (
                patch("utils.lut_manager.LUTManager._build_legacy_catalog_groups", return_value=[]),
                patch("utils.lut_manager.LUTManager._iter_scanned_lut_files", return_value=[("ReferencePack", "C:\\tmp", fake_path)]),
                patch("utils.lut_manager.discover_native_reference_context", return_value=native_ctx),
            ):
                catalog = LUTManager.get_source_catalog()

            native_group = catalog["native_brand_groups"][0]
            assert "package_path" not in native_group
            assert "model_path" not in native_group
        finally:
            LUTManager.invalidate_native_source_index_cache()

    def test_native_source_catalog_reuses_cached_index(self) -> None:
        from utils.lut_manager import LUTManager

        LUTManager.invalidate_native_source_index_cache()
        try:
            import tempfile

            with tempfile.TemporaryDirectory() as tmpdir:
                fake_path = os.path.join(tmpdir, "A.json")
                with open(fake_path, "w", encoding="utf-8") as fh:
                    fh.write("{}")

                native_ctx = NativeReferenceContext(
                    source_kind=SOURCE_KIND_COLORD_DB,
                    primary_path=fake_path,
                    db_paths=(fake_path,),
                    vendor="BambuLab",
                    material_type="PLA",
                )

                with (
                    patch("utils.lut_manager.LUTManager._build_legacy_catalog_groups", return_value=[]),
                    patch("utils.lut_manager.LUTManager._iter_scanned_lut_files", return_value=[("ReferenceDB", tmpdir, fake_path)]),
                    patch("utils.lut_manager.discover_native_reference_context", return_value=native_ctx) as mock_discover,
                    patch("utils.lut_manager.LUTManager.infer_color_mode", return_value="4-Color (RYBW)"),
                ):
                    first = LUTManager.get_source_catalog()
                    second = LUTManager.get_source_catalog()
                    resolved_path, resolved_name = LUTManager.resolve_source_selection(
                        source_kind="native_bundle",
                        material_type="PLA",
                        vendor="BambuLab",
                        db_names=["A.json"],
                    )

                assert first == second
                assert resolved_path == fake_path
                assert resolved_name == "A.json"
                assert mock_discover.call_count == 1
        finally:
            LUTManager.invalidate_native_source_index_cache()

    def test_source_catalog_reuses_unchanged_legacy_groups(self) -> None:
        from utils.lut_manager import LUTManager

        LUTManager.invalidate_native_source_index_cache()
        legacy_groups = [
            {
                "group_name": "Preset",
                "items": [
                    {
                        "name": "A",
                        "path": "A.json",
                        "color_mode": "4-Color (RYBW)",
                        "fingerprint": "fp-a",
                    }
                ],
            }
        ]
        try:
            with (
                patch(
                    "utils.lut_manager.LUTManager._build_legacy_catalog_groups",
                    return_value=legacy_groups,
                ) as mock_legacy,
                patch(
                    "utils.lut_manager.LUTManager._get_native_source_index",
                    return_value=(),
                ),
            ):
                first = LUTManager.get_source_catalog()
                second = LUTManager.get_source_catalog()

            assert first == second
            assert mock_legacy.call_count == 1
        finally:
            LUTManager.invalidate_native_source_index_cache()

    def test_source_catalog_rereads_same_size_overwrite_after_ttl(self, tmp_path) -> None:
        from utils.lut_manager import LUTManager

        lut_path = tmp_path / "mutable.json"
        before = '{"color_mode":"4-Color (RYBW)"}'
        after = '{"color_mode":"4-Color (CMYW)"}'
        assert len(before) == len(after)
        lut_path.write_text(before, encoding="utf-8")
        initial_stat = lut_path.stat()
        LUTManager.invalidate_native_source_index_cache()
        try:
            with (
                patch("utils.lut_manager.LUTManager._scan_legacy_roots", return_value=(("Custom", str(tmp_path)),)),
                patch("utils.lut_manager.LUTManager._get_native_source_index", return_value=()),
                patch("utils.lut_manager.time.monotonic", side_effect=[0.0, 6.0]),
            ):
                first = LUTManager.get_source_catalog()
                lut_path.write_text(after, encoding="utf-8")
                os.utime(lut_path, ns=(initial_stat.st_atime_ns, initial_stat.st_mtime_ns))
                assert lut_path.stat().st_size == initial_stat.st_size
                second = LUTManager.get_source_catalog()

            assert first["legacy_groups"][0]["items"][0]["color_mode"] == "4-Color (RYBW)"
            assert second["legacy_groups"][0]["items"][0]["color_mode"] == "4-Color (CMYW)"
        finally:
            LUTManager.invalidate_native_source_index_cache()

    def test_source_catalog_reuses_groups_within_hot_cache_window(self) -> None:
        from utils.lut_manager import LUTManager

        LUTManager.invalidate_native_source_index_cache()
        try:
            with (
                patch(
                    "utils.lut_manager.LUTManager._build_legacy_catalog_groups",
                    return_value=[],
                ) as mock_legacy,
                patch(
                    "utils.lut_manager.LUTManager._get_native_source_index",
                    return_value=(),
                ),
                patch("utils.lut_manager.time.monotonic", side_effect=[0.0, 1.0]),
            ):
                first = LUTManager.get_source_catalog()
                second = LUTManager.get_source_catalog()

            assert first == second
            assert mock_legacy.call_count == 1
        finally:
            LUTManager.invalidate_native_source_index_cache()

    def test_source_catalog_rereads_groups_after_hot_window_expires(self) -> None:
        from utils.lut_manager import LUTManager

        LUTManager.invalidate_native_source_index_cache()
        try:
            with (
                patch(
                    "utils.lut_manager.LUTManager._build_legacy_catalog_groups",
                    return_value=[],
                ) as mock_legacy,
                patch(
                    "utils.lut_manager.LUTManager._get_native_source_index",
                    return_value=(),
                ),
                patch("utils.lut_manager.time.monotonic", side_effect=[0.0, 6.0, 7.0]),
            ):
                LUTManager.get_source_catalog()
                LUTManager.get_source_catalog()
                LUTManager.get_source_catalog()

            assert mock_legacy.call_count == 2
        finally:
            LUTManager.invalidate_native_source_index_cache()

    def test_native_source_catalog_auto_refreshes_after_ttl(self) -> None:
        from utils.lut_manager import LUTManager, _NativeBrandIndexItem, _NativeDbIndexItem

        LUTManager.invalidate_native_source_index_cache()
        original_ttl = getattr(LUTManager, "NATIVE_SOURCE_INDEX_TTL_SECONDS", None)
        LUTManager.NATIVE_SOURCE_INDEX_TTL_SECONDS = 10.0
        first_index = (
            _NativeBrandIndexItem(
                brand_key="bambulab_pla",
                material_type="PLA",
                vendor="BambuLab",
                display_name="BambuLab PLA",
                db_options=(
                    _NativeDbIndexItem(
                        name="A.json",
                        path="A.json",
                        color_mode="4-Color (RYBW)",
                    ),
                ),
                default_db_names=("A.json",),
                package_name=None,
                model_name=None,
                supported_modes=(),
                package_path=None,
                model_path=None,
            ),
        )
        second_index = (
            _NativeBrandIndexItem(
                brand_key="bambulab_pla",
                material_type="PLA",
                vendor="BambuLab",
                display_name="BambuLab PLA",
                db_options=(
                    _NativeDbIndexItem(
                        name="B.json",
                        path="B.json",
                        color_mode="4-Color (CMYW)",
                    ),
                ),
                default_db_names=("B.json",),
                package_name=None,
                model_name=None,
                supported_modes=(),
                package_path=None,
                model_path=None,
            ),
        )

        try:
            with (
                patch("utils.lut_manager.time.monotonic", side_effect=[0.0, 0.0, 0.0, 11.0, 11.0, 11.0]),
                patch(
                    "utils.lut_manager.LUTManager._build_native_source_index",
                    side_effect=[first_index, second_index],
                ) as mock_build,
            ):
                first = LUTManager.get_source_catalog()
                second = LUTManager.get_source_catalog()

            assert first["native_brand_groups"][0]["db_options"][0]["name"] == "A.json"
            assert second["native_brand_groups"][0]["db_options"][0]["name"] == "B.json"
            assert mock_build.call_count == 2
        finally:
            if original_ttl is None:
                delattr(LUTManager, "NATIVE_SOURCE_INDEX_TTL_SECONDS")
            else:
                LUTManager.NATIVE_SOURCE_INDEX_TTL_SECONDS = original_ttl
            LUTManager.invalidate_native_source_index_cache()


# =========================================================================
# 3. POST /api/lut/merge — empty secondary list (Requirement 6.8)
# =========================================================================


class TestMergeEmptySecondary:
    """Verify merge returns 400 when secondary_names is empty."""

    def test_merge_empty_secondary_returns_400(self) -> None:
        payload = {
            "primary_name": "SomeLUT",
            "secondary_names": [],
            "dedup_threshold": 3.0,
        }
        response = client.post("/api/lut/merge", json=payload)
        assert response.status_code == 400
        assert "At least one secondary LUT" in response.json()["detail"]


# =========================================================================
# 4. POST /api/lut/merge — Primary mode not 6/8-Color (Requirement 6.8)
# =========================================================================


class TestMergePrimaryModeInvalid:
    """Verify merge returns 400 when primary LUT is not 6-Color or 8-Color."""

    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("4-Color", 1024))
    @patch("api.routers.lut.LUTManager.get_lut_path", return_value="/fake/primary.npy")
    def test_merge_4color_primary_returns_400(self, mock_path, mock_detect) -> None:
        payload = {
            "primary_name": "FourColorLUT",
            "secondary_names": ["SecondaryLUT"],
            "dedup_threshold": 3.0,
        }
        response = client.post("/api/lut/merge", json=payload)
        assert response.status_code == 400
        assert "Primary LUT must be 6-Color or 8-Color" in response.json()["detail"]


# =========================================================================
# 5. POST /api/lut/merge — compatibility failure (Requirement 6.8)
# =========================================================================


class TestMergeCompatibilityFailure:
    """Verify merge returns 400 when LUT modes are incompatible."""

    @patch(
        "api.routers.lut.LUTMerger.validate_compatibility",
        return_value=(False, "Incompatible color modes"),
    )
    @patch("api.routers.lut.LUTMerger.load_lut_with_stacks")
    @patch("api.routers.lut.LUTMerger.detect_color_mode")
    @patch("api.routers.lut.LUTManager.get_lut_path")
    def test_merge_incompatible_modes_returns_400(
        self, mock_path, mock_detect, mock_load, mock_validate
    ) -> None:
        import numpy as np

        # get_lut_path returns a path for both primary and secondary
        mock_path.side_effect = ["/fake/primary.npy", "/fake/secondary.npy"]
        # detect_color_mode: primary is 8-Color, secondary is 8-Color (incompatible)
        mock_detect.side_effect = [("8-Color", 2738), ("8-Color", 2738)]
        # load_lut_with_stacks returns dummy data
        dummy_rgb = np.zeros((10, 3), dtype=np.uint8)
        dummy_stacks = np.zeros((10, 5), dtype=np.int32)
        mock_load.return_value = (dummy_rgb, dummy_stacks)

        payload = {
            "primary_name": "PrimaryLUT",
            "secondary_names": ["SecondaryLUT"],
            "dedup_threshold": 3.0,
        }
        response = client.post("/api/lut/merge", json=payload)
        assert response.status_code == 400
        assert "Incompatible" in response.json()["detail"]


class TestMergeFailureLanguage:
    """Verify merge internals do not leak loader details to API clients."""

    @patch(
        "api.routers.lut.LUTMerger.load_lut_with_stacks",
        side_effect=ValueError(
            "cannot load /Users/min/private/primary.json: corrupt stack data"
        ),
    )
    @patch("api.routers.lut.LUTMerger.detect_color_mode", return_value=("8-Color", 2738))
    @patch(
        "api.routers.lut.LUTManager.get_lut_path",
        return_value="/Users/min/private/primary.json",
    )
    def test_merge_loader_failure_uses_public_error_language(
        self,
        mock_path,
        mock_detect,
        mock_load,
    ) -> None:
        payload = {
            "primary_name": "PrimaryLUT",
            "secondary_names": ["SecondaryLUT"],
            "dedup_threshold": 3.0,
        }
        response = client.post("/api/lut/merge", json=payload)

        assert response.status_code == 500
        detail = response.json()["detail"]
        assert detail == (
            "Unable to merge the selected LUTs. Check that each LUT uses a "
            "supported format and compatible color mode."
        )
        assert "/Users/min/private/primary.json" not in detail
        assert "corrupt stack data" not in detail


# =========================================================================
# 6. POST /api/lut/compare — success scenario
# =========================================================================


class TestCompareSuccess:
    """Verify compare returns 200 with same-recipe stats."""

    @patch("api.routers.lut.LUTMerger.validate_print_params", return_value=(True, []))
    @patch(
        "api.routers.lut.LUTMerger.compare_luts_by_recipe",
        return_value={
            "stats": {
                "matched_recipe_count": 2,
                "recipe_coverage_a": 1.0,
                "recipe_coverage_b": 1.0,
                "mean_delta_e00": 1.25,
                "median_delta_e00": 1.25,
                "p95_delta_e00": 1.8,
                "max_delta_e00": 2.0,
                "identical_rgb_count": 1,
                "recipes_only_in_a": 0,
                "recipes_only_in_b": 0,
            },
            "warnings": [],
            "worst_diffs": [
                {
                    "recipe": ["White", "Red", "Yellow", "Blue", "White"],
                    "rgb_a": [255, 0, 0],
                    "rgb_b": [254, 5, 0],
                    "hex_a": "#FF0000",
                    "hex_b": "#FE0500",
                    "delta_e00": 2.0,
                }
            ],
        },
    )
    @patch("api.routers.lut.LUTMerger.normalize_stacks_for_compare")
    @patch("api.routers.lut.LUTManager.load_lut_with_metadata")
    @patch("api.routers.lut.LUTMerger.load_lut_with_stacks")
    @patch("api.routers.lut.LUTMerger.detect_color_mode")
    @patch("api.routers.lut.LUTManager.get_lut_path")
    def test_compare_returns_200_with_stats(
        self,
        mock_path,
        mock_detect,
        mock_load,
        mock_load_meta,
        mock_normalize,
        mock_compare,
        mock_validate,
    ) -> None:
        import numpy as np

        dummy_rgb = np.array([[255, 0, 0], [0, 255, 0]], dtype=np.uint8)
        dummy_stacks = np.array([[0, 5, 3, 6, 0], [0, 1, 2, 3, 4]], dtype=np.int32)

        mock_path.side_effect = ["/fake/a.json", "/fake/b.json"]
        mock_detect.side_effect = [("4-Color", 1024), ("4-Color", 1024)]
        mock_load.side_effect = [(dummy_rgb, dummy_stacks), (dummy_rgb, dummy_stacks)]
        mock_load_meta.side_effect = [
            (dummy_rgb, dummy_stacks, LUTMetadata(color_mode="4-Color (RYBW)")),
            (dummy_rgb, dummy_stacks, LUTMetadata(color_mode="4-Color (RYBW)")),
        ]
        mock_normalize.side_effect = [dummy_stacks, dummy_stacks]

        payload = {
            "lut_a_name": "LUT_A",
            "lut_b_name": "LUT_B",
            "top_n": 5,
        }
        response = client.post("/api/lut/compare", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["lut_a_name"] == "LUT_A"
        assert data["lut_b_name"] == "LUT_B"
        assert data["stats"]["matched_recipe_count"] == 2
        assert data["stats"]["mean_delta_e00"] == 1.25
        assert data["worst_diffs"][0]["delta_e00"] == 2.0

    @patch("api.routers.lut.LUTMerger.normalize_stacks_for_compare")
    @patch("api.routers.lut.LUTMerger.validate_print_params", return_value=(True, []))
    @patch("api.routers.lut.LUTManager.load_lut_with_metadata")
    @patch("api.routers.lut.LUTMerger.load_lut_with_stacks")
    @patch("api.routers.lut.LUTMerger.detect_color_mode")
    @patch("api.routers.lut.LUTManager.get_lut_path")
    def test_compare_uses_canonical_stacks_from_loader(
        self,
        mock_path,
        mock_detect,
        mock_load,
        mock_load_meta,
        mock_validate,
        mock_normalize,
    ) -> None:
        import numpy as np

        dummy_rgb = np.array([[255, 0, 0]], dtype=np.uint8)
        canonical_stacks = np.array([[0, 5, 3, 6, 0]], dtype=np.int32)

        def compare_side_effect(rgb_a, stacks_a, rgb_b, stacks_b, top_n):
            np.testing.assert_array_equal(stacks_a, canonical_stacks)
            np.testing.assert_array_equal(stacks_b, canonical_stacks)
            return {
                "stats": {
                    "matched_recipe_count": 1,
                    "recipe_coverage_a": 1.0,
                    "recipe_coverage_b": 1.0,
                    "mean_delta_e00": 0.0,
                    "median_delta_e00": 0.0,
                    "p95_delta_e00": 0.0,
                    "max_delta_e00": 0.0,
                    "identical_rgb_count": 1,
                    "recipes_only_in_a": 0,
                    "recipes_only_in_b": 0,
                },
                "warnings": [],
                "worst_diffs": [],
            }

        mock_normalize.side_effect = AssertionError(
            "compare route should not re-normalize canonical stacks"
        )
        mock_path.side_effect = ["/fake/a.json", "/fake/b.json"]
        mock_detect.side_effect = [("4-Color", 1024), ("4-Color", 1024)]
        mock_load.side_effect = [
            (dummy_rgb, canonical_stacks),
            (dummy_rgb, canonical_stacks),
        ]
        mock_load_meta.side_effect = [
            (dummy_rgb, canonical_stacks, LUTMetadata(color_mode="4-Color (RYBW)")),
            (dummy_rgb, canonical_stacks, LUTMetadata(color_mode="4-Color (RYBW)")),
        ]

        with patch(
            "api.routers.lut.LUTMerger.compare_luts_by_recipe",
            side_effect=compare_side_effect,
        ):
            payload = {
                "lut_a_name": "LUT_A",
                "lut_b_name": "LUT_B",
                "top_n": 5,
            }
            response = client.post("/api/lut/compare", json=payload)

        assert response.status_code == 200
        mock_normalize.assert_not_called()


# =========================================================================
# 7. POST /api/lut/compare — 404 scenario
# =========================================================================


class TestCompareNotFound:
    """Verify compare returns 404 when a LUT is missing."""

    @patch("api.routers.lut.LUTManager.get_lut_path", return_value=None)
    def test_compare_returns_404_when_lut_not_found(self, mock_path) -> None:
        payload = {
            "lut_a_name": "MissingLUT",
            "lut_b_name": "OtherLUT",
            "top_n": 5,
        }
        response = client.post("/api/lut/compare", json=payload)
        assert response.status_code == 404
        assert response.json()["detail"] == _LUT_NOT_FOUND_PUBLIC_DETAIL


class TestCompareFailureLanguage:
    """Verify compare internals do not leak loader details to API clients."""

    @patch(
        "api.routers.lut.LUTMerger.load_lut_with_stacks",
        side_effect=ValueError(
            "cannot parse /Users/min/private/a.json: invalid JSON"
        ),
    )
    @patch(
        "api.routers.lut.LUTMerger.detect_color_mode",
        side_effect=[("4-Color", 1024), ("4-Color", 1024)],
    )
    @patch(
        "api.routers.lut.LUTManager.get_lut_path",
        side_effect=["/Users/min/private/a.json", "/Users/min/private/b.json"],
    )
    def test_compare_loader_failure_uses_public_error_language(
        self,
        mock_path,
        mock_detect,
        mock_load,
    ) -> None:
        payload = {
            "lut_a_name": "LUT_A",
            "lut_b_name": "LUT_B",
            "top_n": 5,
        }
        response = client.post("/api/lut/compare", json=payload)

        assert response.status_code == 500
        detail = response.json()["detail"]
        assert detail == (
            "Unable to compare the selected LUTs. Check that both LUTs use "
            "supported formats with comparable recipes."
        )
        assert "/Users/min/private/a.json" not in detail
        assert "invalid JSON" not in detail


# =========================================================================
# 8. POST /api/lut/compare — no shared recipes warning
# =========================================================================


class TestCompareNoSharedRecipes:
    """Verify compare surfaces the empty shared-recipe warning."""

    @patch("api.routers.lut.LUTMerger.validate_print_params", return_value=(True, []))
    @patch(
        "api.routers.lut.LUTMerger.compare_luts_by_recipe",
        return_value={
            "stats": {
                "matched_recipe_count": 0,
                "recipe_coverage_a": 0.0,
                "recipe_coverage_b": 0.0,
                "mean_delta_e00": 0.0,
                "median_delta_e00": 0.0,
                "p95_delta_e00": 0.0,
                "max_delta_e00": 0.0,
                "identical_rgb_count": 0,
                "recipes_only_in_a": 10,
                "recipes_only_in_b": 12,
            },
            "warnings": [],
            "worst_diffs": [],
        },
    )
    @patch("api.routers.lut.LUTMerger.normalize_stacks_for_compare")
    @patch("api.routers.lut.LUTManager.load_lut_with_metadata")
    @patch("api.routers.lut.LUTMerger.load_lut_with_stacks")
    @patch("api.routers.lut.LUTMerger.detect_color_mode")
    @patch("api.routers.lut.LUTManager.get_lut_path")
    def test_compare_includes_no_shared_recipe_warning(
        self,
        mock_path,
        mock_detect,
        mock_load,
        mock_load_meta,
        mock_normalize,
        mock_compare,
        mock_validate,
    ) -> None:
        import numpy as np

        dummy_rgb = np.array([[255, 0, 0]], dtype=np.uint8)
        dummy_stacks = np.array([[0, 5, 3, 6, 0]], dtype=np.int32)

        mock_path.side_effect = ["/fake/a.json", "/fake/b.json"]
        mock_detect.side_effect = [("4-Color", 1024), ("4-Color", 1024)]
        mock_load.side_effect = [(dummy_rgb, dummy_stacks), (dummy_rgb, dummy_stacks)]
        mock_load_meta.side_effect = [
            (dummy_rgb, dummy_stacks, LUTMetadata(color_mode="4-Color (RYBW)")),
            (dummy_rgb, dummy_stacks, LUTMetadata(color_mode="4-Color (RYBW)")),
        ]
        mock_normalize.side_effect = [dummy_stacks, dummy_stacks]

        payload = {
            "lut_a_name": "LUT_A",
            "lut_b_name": "LUT_B",
            "top_n": 5,
        }
        response = client.post("/api/lut/compare", json=payload)

        assert response.status_code == 200
        warnings = response.json()["warnings"]
        assert any("No shared recipes found" in warning for warning in warnings)
