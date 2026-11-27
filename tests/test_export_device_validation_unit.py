from __future__ import annotations

from pathlib import Path
import io

import numpy as np
from PIL import Image
from fastapi.testclient import TestClient

from api.app import app
from api.dependencies import get_session_store, get_file_registry, get_worker_pool
from api.file_registry import FileRegistry
from api.session_store import SessionStore

from fastapi import HTTPException
import pytest

from api.export_device_validation import validate_export_device_selection


def test_export_device_validation_allows_legacy_requests_without_registry_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", "/missing/registry")

    validate_export_device_selection(
        printer_id="bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id=None,
        build_plate_id=None,
    )


def test_export_device_validation_accepts_supported_device_and_plate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LUMINA_MACHINE_REGISTRY_DIR", raising=False)

    validate_export_device_selection(
        printer_id="bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
        build_plate_id="textured-pei-plate",
    )


@pytest.mark.parametrize(
    ("overrides", "detail_fragment"),
    [
        (
            {"device_profile_id": None, "build_plate_id": "textured-pei-plate"},
            "requires device_profile_id",
        ),
        (
            {"device_profile_id": "missing-device"},
            "Unknown machine registry device profile",
        ),
        (
            {"printer_id": "bambu-p1s"},
            "does not match requested printer",
        ),
        (
            {"slicer": "OrcaSlicer"},
            "does not match requested slicer/nozzle",
        ),
        (
            {"nozzle_size": "0.2"},
            "does not match requested slicer/nozzle",
        ),
        (
            {"build_plate_id": "cool-plate"},
            "Unsupported build plate",
        ),
    ],
)
def test_export_device_validation_rejects_invalid_combinations_with_422(
    monkeypatch: pytest.MonkeyPatch,
    overrides: dict[str, str | None],
    detail_fragment: str,
) -> None:
    monkeypatch.delenv("LUMINA_MACHINE_REGISTRY_DIR", raising=False)
    selection: dict[str, str | None] = {
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
        "nozzle_size": "0.4",
        "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
        "build_plate_id": "textured-pei-plate",
    }
    selection.update(overrides)

    with pytest.raises(HTTPException) as exc_info:
        validate_export_device_selection(**selection)

    assert exc_info.value.status_code == 422
    assert detail_fragment in str(exc_info.value.detail)


def test_export_device_validation_reports_missing_explicit_registry_as_503(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv(
        "LUMINA_MACHINE_REGISTRY_DIR",
        str(tmp_path / "missing-registry"),
    )

    with pytest.raises(HTTPException) as exc_info:
        validate_export_device_selection(
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            nozzle_size="0.4",
            device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
            build_plate_id="textured-pei-plate",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Machine registry is unavailable."


@pytest.mark.parametrize(
    "registry_json",
    [
        '{"schema_version": 1, "generated_at": "test", "slicers": [{}]}',
        '{"schema_version": 1, "generated_at": "test", "slicers": null}',
    ],
)
def test_export_device_validation_reports_malformed_registry_as_503(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    registry_json: str,
) -> None:
    registry_root = tmp_path / "machine-registry"
    registry_root.mkdir()
    (registry_root / "registry.json").write_text(registry_json, encoding="utf-8")
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    with pytest.raises(HTTPException) as exc_info:
        validate_export_device_selection(
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            nozzle_size="0.4",
            device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
            build_plate_id="textured-pei-plate",
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Machine registry is unavailable."


@pytest.mark.parametrize(("path", "params"), [
    ("/api/convert/generate", {"params": {"lut_name": "unused.json"}}),
    ("/api/convert/generate-large-format", {"params": {"params": {"lut_name": "unused.json"}}}),
    ("/api/convert/generate-puzzle", {"params": {"target_height_mm": 30, "params": {"lut_name": "unused.json"}}}),
    ("/api/calibration/generate", {}),
    ("/api/calibration/generate-single-stage-kit", {"palette": [
        {"color": "White"}, {"color": "Red"}, {"color": "Yellow"}, {"color": "Blue"},
    ]}),
    ("/api/five-color/generate-swatch", {"lut_name": "unused.json", "recipes": [
        {"selected_indices": [0, 1, 2, 3, 0, 1], "result_hex": "#ff0000"},
    ]}),
    ("/api/extractor/generate-material-swatch", {"recipes": [
        {"directory_names": ["white"], "result_hex": "#ffffff"},
    ]}),
    ("/api/convert/batch", None),
])
def test_export_routes_reject_invalid_device_before_worker(path, params, monkeypatch):
    monkeypatch.delenv("LUMINA_MACHINE_REGISTRY_DIR", raising=False)
    store = SessionStore()
    session_id = store.create()
    store.put(session_id, "preview_cache", {"matched_rgb": np.zeros((2, 2, 3), dtype=np.uint8)})
    monkeypatch.setitem(app.dependency_overrides, get_session_store, lambda: store)
    monkeypatch.setitem(app.dependency_overrides, get_file_registry, lambda: FileRegistry())
    # An accidental worker call fails immediately instead of doing export work.
    monkeypatch.setitem(app.dependency_overrides, get_worker_pool, lambda: object())
    client = TestClient(app)

    if params is None:
        buffer = io.BytesIO()
        Image.new("RGB", (2, 2)).save(buffer, format="PNG")
        response = client.post(path, data={"device_profile_id": "missing-device", "lut_name": "unused.json"},
                               files={"images": ("source.png", buffer.getvalue(), "image/png")})
    else:
        payload = dict(params)
        if path.startswith("/api/convert/"):
            payload["session_id"] = session_id
            options = dict(payload["params"])
            if "params" in options:
                options["params"] = {**options["params"], "device_profile_id": "missing-device"}
            else:
                options["device_profile_id"] = "missing-device"
            payload["params"] = options
        else:
            payload["device_profile_id"] = "missing-device"
        response = client.post(path, json=payload)

    assert response.status_code == 422
    assert "Unknown machine registry device profile" in str(response.json()["detail"])


def test_swatch_export_routes_map_native_material_selection_error_to_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    from core.errors import NativeMaterialSelectionError

    plate_error = NativeMaterialSelectionError(
        {
            "device_profile_id": "BambuStudio:bbl:bambu-lab-x1-carbon:0.4",
            "build_plate_id": "engineering-plate",
            "issues": [
                {
                    "message": (
                        "Source material slot 0 type 'PLA BASIC' does not support "
                        "selected build plate 'Engineering Plate'."
                    )
                }
            ],
        }
    )

    class _StubEngine:
        color_count = 4
        _lut_metadata = None

        @staticmethod
        def get_color_names() -> list[str]:
            return ["White", "Red", "Yellow", "Blue"]

        @staticmethod
        def get_base_colors() -> np.ndarray:
            return np.zeros((4, 3), dtype=np.uint8)

        @staticmethod
        def accepted_selection_lengths() -> tuple[int, ...]:
            return (5,)

        @staticmethod
        def query(_indices: list[int]) -> SimpleNamespace:
            return SimpleNamespace(found=True, result_rgb=np.array([255, 0, 0], dtype=np.uint8))

    monkeypatch.delenv("LUMINA_MACHINE_REGISTRY_DIR", raising=False)
    monkeypatch.setitem(app.dependency_overrides, get_file_registry, lambda: FileRegistry())
    monkeypatch.setattr("api.routers.five_color._load_engine", lambda *_a, **_k: (_StubEngine(), "stub"))
    monkeypatch.setattr(
        "api.routers.five_color.LUTManager.load_lut_with_metadata",
        lambda *_a, **_k: (None, None, SimpleNamespace(palette=[])),
    )
    monkeypatch.setattr(
        "core.recipe_swatch.generate_recipe_swatch",
        lambda **_k: (_ for _ in ()).throw(plate_error),
    )
    monkeypatch.setattr(
        "api.routers.single_stage._load_palette_or_raise",
        lambda _names: [
            SimpleNamespace(
                directory_name="pla-basic",
                name="PLA Basic",
                estimated_rgb=np.array([255, 255, 255], dtype=np.uint8),
                material_type="PLA Basic",
            )
        ],
    )
    monkeypatch.setattr(
        "core.material_recipe_swatch.generate_material_recipe_swatch",
        lambda **_k: (_ for _ in ()).throw(plate_error),
    )

    client = TestClient(app, raise_server_exceptions=False)
    device_fields = {
        "printer_id": "bambu-x1c",
        "slicer": "BambuStudio",
        "nozzle_size": "0.4",
        "device_profile_id": "BambuStudio:bbl:bambu-lab-x1-carbon:0.4",
        "build_plate_id": "engineering-plate",
    }

    five_color_resp = client.post(
        "/api/five-color/generate-swatch",
        json={
            "lut_name": "stub.json",
            "recipes": [{"selected_indices": [0, 1, 2, 3, 0], "result_hex": "#FF0000"}],
            **device_fields,
        },
    )
    assert five_color_resp.status_code == 422, five_color_resp.text
    assert five_color_resp.json()["detail"]["error"] == "native_material_selection_required"
    assert "Engineering Plate" in five_color_resp.json()["detail"]["message"]

    material_resp = client.post(
        "/api/extractor/generate-material-swatch",
        json={
            "recipes": [
                {
                    "directory_names": ["pla-basic"],
                    "result_hex": "#FFFFFF",
                    "layer_height_mm": 0.08,
                    "substrate": "white",
                }
            ],
            **device_fields,
        },
    )
    assert material_resp.status_code == 422, material_resp.text
    assert material_resp.json()["detail"]["error"] == "native_material_selection_required"
    assert "Engineering Plate" in material_resp.json()["detail"]["message"]
