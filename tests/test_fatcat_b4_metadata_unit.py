from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from utils import bambu_3mf_writer
from utils.fatcat_metadata import (
    MetadataTarget,
    build_model_metadata_request,
    build_project_settings_request,
    compose_model_metadata,
    compose_project_settings,
    select_metadata_target,
)


def test_root_external_metadata_uses_fatcat_explicit_scope_not_name_suffix() -> None:
    class RecordingBuilder:
        def __init__(self) -> None:
            self.root_metadata: list[tuple[str, str]] = []
            self.external_metadata: list[tuple[str, str]] = []

        def add_namespace(self, prefix: str, uri: str) -> None:
            pass

        def add_metadata(self, name: str, value: str) -> None:
            self.root_metadata.append((name, value))

        def add_external_model_metadata(self, name: str, value: str) -> None:
            self.external_metadata.append((name, value))

    builder = RecordingBuilder()
    root_model = {
        "namespaces": [],
        "metadata": [
            {"name": "Vendor:3mfVersion", "value": "1"},
            {"name": "Application", "value": "BambuStudio-test"},
        ],
        "external_metadata": [
            {"name": "Application", "value": "BambuStudio-test"}
        ],
    }

    bambu_3mf_writer._apply_root_model_metadata(builder, root_model)

    assert builder.root_metadata == [
        ("Vendor:3mfVersion", "1"),
        ("Application", "BambuStudio-test"),
    ]
    assert builder.external_metadata == [("Application", "BambuStudio-test")]


@pytest.mark.parametrize("slicer,version", [("BambuStudio", "02.09.01.70"), ("OrcaSlicer", "2.4.2")])
def test_target_selection_uses_exact_runtime_profile(slicer: str, version: str) -> None:
    common = {
        "slicer": slicer,
        "printer_id": "bambu-a1-mini",
        "nozzle_size": "0.4",
        "device_profile_id": f"{slicer}:bbl:bambu-lab-a1-mini:0.4",
        "build_plate_id": "textured-pei-plate",
    }
    target = select_metadata_target(**common)
    assert target is not None
    assert target.application_version == version
    assert target.machine_uid == "bambu-lab:a1-mini"
    assert target.nozzle_uid == "nozzle:0.4mm"
    assert target.build_plate_uid == "plate:textured-pei"
    wide_nozzle = select_metadata_target(**{
        **common,
        "nozzle_size": "0.6",
        "device_profile_id": f"{slicer}:bbl:bambu-lab-a1-mini:0.6",
    })
    assert wide_nozzle.nozzle_uid == "nozzle:0.6mm"
    alternative_plate = "smooth-pei-plate" if slicer == "BambuStudio" else "smooth-high-temp-plate"
    alternative_uid = "plate:smooth-pei"
    assert select_metadata_target(**{
        **common,
        "build_plate_id": alternative_plate,
    }).build_plate_uid == alternative_uid
    flashstudio = select_metadata_target(
        slicer="FlashStudio", printer_id="flashforge-ad5x", nozzle_size="0.4",
        device_profile_id="FlashStudio:flashforge:flashforge-ad5x:0.4",
        build_plate_id="engineering-plate",
    )
    assert flashstudio.slicer_id == "FlashStudio"


@pytest.mark.parametrize("target", [
    MetadataTarget("BambuStudio", "02.09.01.70", "bambu-lab:a1-mini", "nozzle:0.4mm", "plate:textured-pei"),
    MetadataTarget("OrcaSlicer", "2.4.2", "bambu-lab:p1s", "nozzle:0.6mm", "plate:textured-pei"),
])
def test_project_request_preserves_template_materials_and_explicit_process_fields(target: MetadataTarget) -> None:
    settings = {
        "layer_height": "0.12",
        "initial_layer_height": "0.20",
        "line_width": "0.42",
        "wall_loops": "2",
        "top_shell_layers": "3",
        "bottom_shell_layers": "2",
        "bottom_surface_pattern": "monotonicline",
        "sparse_infill_density": "100%",
        "sparse_infill_pattern": "grid",
        "outer_wall_speed": "85",
        "travel_speed": "180",
        "enable_support": "0",
        "brim_type": "auto_brim",
        "brim_width": "5",
    }
    request = build_project_settings_request(
        settings,
        ["#112233", "#445566"],
        target=target,
    )

    assert request["material_mode"] == "preserve_template"
    assert request["filament_colour"] == ["#112233", "#445566"]
    assert request["filament_multi_colour"] == ["#112233", "#445566"]
    assert request["enable_prime_tower"] == "1"
    assert request["process_settings"] == settings
    assert "nozzle_temperature" not in request
    assert "filament_settings_id" not in request
    assert request["slicer_id"] == target.slicer_id
    assert request["application_version"] == target.application_version
    assert request["machine_uid"] == target.machine_uid
    assert request["nozzle_uid"] == target.nozzle_uid
    assert request["build_plate_uid"] == target.build_plate_uid
    assert "material_uid" not in request
    # B7.2 assigns native defaults to ordinary exports; preserve is reserved
    # for actual user tuning and must not inject the ordinary precision choice.
    assert "precise_outer_wall" not in request["process_settings"]


def test_model_request_uses_writer_ids_and_current_geometry_descriptors() -> None:
    entries = [
        SimpleNamespace(
            mesh=SimpleNamespace(
                bounds=np.asarray([[1.0, 2.0, 0.0], [5.0, 8.0, 3.0]])
            ),
            object_name="Cyan",
        ),
        SimpleNamespace(
            mesh=SimpleNamespace(
                bounds=np.asarray([[-2.0, 4.0, 1.0], [0.0, 6.0, 2.0]])
            ),
            object_name="Magenta",
        ),
    ]
    request = build_model_metadata_request(
        target=MetadataTarget("OrcaSlicer", "2.4.2", "bambu-lab:a1-mini", "nozzle:0.4mm", "plate:textured-pei"),
        assembly_id=9,
        object_ids=[4, 7],
        entries=entries,
        material_index_by_object=[1, 3],
        output_path="/tmp/exported.3mf",
        bed_type="Textured PEI Plate",
    )

    assert request["assembly_id"] == 9
    assert request["slicer_id"] == "OrcaSlicer"
    assert request["application_version"] == "2.4.2"
    assert request["source_file"] == "exported.3mf"
    assert [part["part_id"] for part in request["parts"]] == [4, 7]
    assert request["parts"][0]["material_index"] == 1
    assert request["parts"][0]["source_object_id"] == 0
    assert request["parts"][0]["source_volume_id"] == 0
    assert request["parts"][0]["source_offset_x"] == "3"
    assert request["parts"][0]["matrix"] == "1 0 0 5 0 1 0 8 0 0 1 3 0 0 0 1"
    assert request["plate"]["bed_type"] == "Textured PEI Plate"
    assert "resources" not in request["plate"]


def test_compose_wrappers_call_the_native_entry_points_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeFatCat:
        @staticmethod
        def compose_project_settings(base: str, request: str) -> str:
            calls.append("project")
            return '{"project_settings_json":"{\\"layer_height\\":\\"0.12\\"}"}'

        @staticmethod
        def compose_model_metadata(project: str, request: str) -> str:
            calls.append("model")
            return '{"parts":[],"root_model":{},"settings_parts":{}}'

        @staticmethod
        def patch_wipe_tower(project: str, settings: str, dialect: str) -> str:
            return project

    monkeypatch.setattr(
        "utils.fatcat_metadata._load_fatcat",
        lambda: FakeFatCat,
    )
    project = compose_project_settings({}, {"layer_height": "0.12"})
    model = compose_model_metadata({}, {"parts": [], "plate": {}},)

    assert project["project_settings_json"] == '{"layer_height":"0.12"}'
    assert model["parts"] == []
    assert calls == ["project", "model"]


def test_patch_wipe_tower_uses_the_fixed_three_argument_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, str, str]] = []

    class FakeFatCat:
        @staticmethod
        def compose_project_settings(_base: str, _request: str) -> str:
            raise AssertionError("compose_project_settings is not part of this test")

        @staticmethod
        def compose_model_metadata(_project: str, _request: str) -> str:
            raise AssertionError("compose_model_metadata is not part of this test")

        @staticmethod
        def patch_wipe_tower(project: str, settings: str, dialect: str) -> str:
            captured.append((project, settings, dialect))
            return project

    monkeypatch.setattr("utils.fatcat_metadata._load_fatcat", lambda: FakeFatCat)
    from utils.fatcat_metadata import patch_wipe_tower

    result = patch_wipe_tower(
        {"initial_layer_print_height": "0.20"},
        {"enabled": True, "positions": [{"plate_index": 0, "x_mm": 143.0}]},
        {"enabled_key": "selected_target_tower_enabled"},
    )

    assert result["initial_layer_print_height"] == "0.20"
    assert len(captured) == 1
    assert '"enabled_key":"selected_target_tower_enabled"' in captured[0][2]
