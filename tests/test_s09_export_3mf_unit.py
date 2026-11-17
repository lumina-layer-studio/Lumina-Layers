"""Focused regressions for S09 3MF export handoff."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import trimesh
from unittest.mock import patch

from config import ModelingMode
from core.pipeline import s09_export_3mf


@pytest.mark.parametrize("backing_output", ["same_project", "separate_project"])
def test_s09_passes_full_slot_names_to_exporter(
    monkeypatch, tmp_path, backing_output: str,
) -> None:
    """S09 should preserve the full selected palette when exporting sparse scenes."""

    captured: dict[str, object] = {}

    def _fake_export_scene_with_bambu_metadata(
        *,
        scene,
        output_path: str,
        slot_names,
        preview_colors,
        settings,
        color_mode: str,
        printer_id: str,
        slicer: str,
        nozzle_size: str | float | None = None,
        watermark: str = "LuminaStudio",
        project_slot_names=None,
        enable_base_layer_height_modifier: bool = True,
        enable_wipe_tower_auto_placement: bool = True,
        enable_relief: bool = False,
        base_height_mm: float = 0.0,
        color_height_mm: float = 0.0,
        face_orientation: str = "down",
        backing_infill_density_percent: int = 100,
        cover_source: object | None = None,
        device_profile_id: str | None = None,
        build_plate_id: str | None = None,
        preserve_template_filament_slots: bool | None = None,
        material_types: dict[str, str | None] | None = None,
        custom_3mf_template_id: str | None = None,
        backing_output: str = "same_project",
        native_filament_profiles: dict[str, str] | None = None,
        external_spool_material: str | None = None,
    ) -> str:
        captured["external_spool_material"] = external_spool_material
        captured["scene"] = scene
        captured["output_path"] = output_path
        captured["slot_names"] = list(slot_names)
        captured["preview_colors"] = dict(preview_colors)
        captured["color_mode"] = color_mode
        captured["printer_id"] = printer_id
        captured["slicer"] = slicer
        captured["nozzle_size"] = nozzle_size
        captured["project_slot_names"] = list(project_slot_names) if project_slot_names is not None else None
        captured["watermark"] = watermark
        captured["enable_base_layer_height_modifier"] = enable_base_layer_height_modifier
        captured["enable_wipe_tower_auto_placement"] = (
            enable_wipe_tower_auto_placement
        )
        captured["enable_relief"] = enable_relief
        captured["base_height_mm"] = base_height_mm
        captured["color_height_mm"] = color_height_mm
        captured["face_orientation"] = face_orientation
        captured["backing_infill_density_percent"] = (
            backing_infill_density_percent
        )
        captured["cover_source"] = cover_source
        captured["device_profile_id"] = device_profile_id
        captured["build_plate_id"] = build_plate_id
        captured["preserve_template_filament_slots"] = preserve_template_filament_slots
        captured["material_types"] = material_types
        captured["custom_3mf_template_id"] = custom_3mf_template_id
        captured["backing_output"] = backing_output
        captured["native_filament_profiles"] = native_filament_profiles
        return str(Path(output_path).with_suffix(".zip")) if backing_output == "separate_project" else output_path

    monkeypatch.setattr(s09_export_3mf, "MODELS_DIR", str(tmp_path))
    monkeypatch.setattr(s09_export_3mf, "generate_model_filename", lambda *_args: "native-export.3mf")
    monkeypatch.setattr(s09_export_3mf, "export_scene_with_bambu_metadata", _fake_export_scene_with_bambu_metadata)

    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box(extents=[1, 1, 1]), geom_name="yellow")

    ctx = {
        "scene": scene,
        "valid_slot_names": ["yellow"],
        "slot_names": ["bambugreen", "black", "blue", "cyan", "magenta", "red", "white", "yellow"],
        "preview_colors": {7: [255, 230, 0, 255]},
        "color_mode": "8-Color",
        "image_path": str(tmp_path / "native.png"),
        "modeling_mode": ModelingMode.HIGH_FIDELITY,
        "target_w": 16,
        "pixel_scale": 1.0,
        "structure_mode": "双面",
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
        "build_plate_id": "smooth-pei-plate",
        "custom_3mf_template_id": "selected-native-template",
        "backing_output": backing_output,
        "external_spool_material": "black",
        "native_filament_profiles": {"yellow": "Generic PETG @BBL H2D"},
    }

    result = s09_export_3mf.run(ctx)

    expected_suffix = ".zip" if backing_output == "separate_project" else ".3mf"
    assert result["out_path"] == str(tmp_path / f"native-export{expected_suffix}")
    assert captured["slot_names"] == ["yellow"]
    assert captured["project_slot_names"] == [
        "bambugreen",
        "black",
        "blue",
        "cyan",
        "magenta",
        "red",
        "white",
        "yellow",
    ]
    assert captured["build_plate_id"] == "smooth-pei-plate"
    assert captured["custom_3mf_template_id"] == "selected-native-template"
    assert captured["backing_output"] == backing_output
    assert captured["native_filament_profiles"] == ctx["native_filament_profiles"]
    assert captured["external_spool_material"] == "black"


def _make_minimal_s09_ctx(tmp_path, **extra_ctx) -> dict:
    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box(extents=[1, 1, 1]), geom_name="Slot 1")

    ctx = {
        "scene": scene,
        "valid_slot_names": ["Slot 1"],
        "slot_names": ["Slot 1"],
        "preview_colors": {"Slot 1": (255, 0, 0, 255)},
        "color_mode": "4-Color",
        "image_path": str(tmp_path / "source.png"),
        "modeling_mode": ModelingMode.HIGH_FIDELITY,
        "target_w": 16,
        "pixel_scale": 1.0,
        "structure_mode": "单面",
        "printer_id": "bambu-h2d",
        "slicer": "BambuStudio",
        "nozzle_size": "0.4",
    }
    ctx.update(extra_ctx)
    return ctx


def test_s09_records_actual_x_mirror_transform_metadata(tmp_path) -> None:
    """S09 should expose the effective mirror decision and raster span."""

    export_transform_metadata: dict[str, object] = {}
    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "mirrored-piece.3mf",
    ), patch.object(
        s09_export_3mf,
        "export_scene_with_bambu_metadata",
        autospec=True,
    ) as mock_export:
        mock_export.return_value = str(tmp_path / "mirrored-piece.3mf")
        s09_export_3mf.run(
            _make_minimal_s09_ctx(
                tmp_path,
                target_w=338,
                pixel_scale=0.1,
                bambu_face_orientation="down",
                center_on_bed=False,
                export_transform_metadata=export_transform_metadata,
            )
        )

    assert export_transform_metadata["x_mirrored"] is True
    assert export_transform_metadata["mirror_span_mm"] == pytest.approx(33.8)


def test_s09_passes_base_layer_kwargs_when_ctx_has_them(tmp_path) -> None:
    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "ctx-values.3mf",
    ), patch.object(s09_export_3mf, "export_scene_with_bambu_metadata", autospec=True) as mock_export:
        mock_export.return_value = str(tmp_path / "ctx-values.3mf")

        result = s09_export_3mf.run(
            _make_minimal_s09_ctx(
                tmp_path,
                bambu_base_height_mm=0.8,
                bambu_color_height_mm=2.4,
                bambu_face_orientation="down",
                enable_base_layer_height_modifier=True,
                enable_wipe_tower_auto_placement=False,
                backing_infill_density_percent=20,
            )
        )

    assert result["out_path"] == str(tmp_path / "ctx-values.3mf")
    kwargs = mock_export.call_args.kwargs
    assert kwargs["enable_base_layer_height_modifier"] is True
    assert kwargs["enable_wipe_tower_auto_placement"] is False
    assert kwargs["base_height_mm"] == 0.8
    assert kwargs["color_height_mm"] == 2.4
    assert kwargs["face_orientation"] == "down"
    assert kwargs["backing_infill_density_percent"] == 20


def test_s09_relief_export_disables_base_modifier_at_handoff(tmp_path) -> None:
    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "relief.3mf",
    ), patch.object(s09_export_3mf, "export_scene_with_bambu_metadata", autospec=True) as mock_export:
        mock_export.return_value = str(tmp_path / "relief.3mf")

        s09_export_3mf.run(
            _make_minimal_s09_ctx(
                tmp_path,
                enable_relief=True,
                enable_base_layer_height_modifier=True,
                bambu_base_height_mm=1.2,
                bambu_color_height_mm=0.56,
                bambu_face_orientation="up",
            )
        )

    kwargs = mock_export.call_args.kwargs
    assert kwargs["enable_relief"] is True
    assert kwargs["enable_base_layer_height_modifier"] is False


def test_s09_falls_back_to_safe_defaults_when_ctx_missing_keys(tmp_path) -> None:
    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "defaults.3mf",
    ), patch.object(s09_export_3mf, "export_scene_with_bambu_metadata", autospec=True) as mock_export:
        mock_export.return_value = str(tmp_path / "defaults.3mf")

        result = s09_export_3mf.run(_make_minimal_s09_ctx(tmp_path))

    assert result["out_path"] == str(tmp_path / "defaults.3mf")
    kwargs = mock_export.call_args.kwargs
    assert kwargs["enable_base_layer_height_modifier"] is True
    assert kwargs["enable_wipe_tower_auto_placement"] is True
    assert kwargs["base_height_mm"] == 0.0
    assert kwargs["color_height_mm"] == 0.0
    assert kwargs["face_orientation"] == "down"
    assert kwargs["backing_infill_density_percent"] == 100


def test_s09_passes_face_up_for_five_color(tmp_path) -> None:
    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "face-up.3mf",
    ), patch.object(s09_export_3mf, "export_scene_with_bambu_metadata", autospec=True) as mock_export:
        mock_export.return_value = str(tmp_path / "face-up.3mf")

        s09_export_3mf.run(_make_minimal_s09_ctx(tmp_path, bambu_face_orientation="up"))

    assert mock_export.call_args.kwargs["face_orientation"] == "up"


def test_s09_does_not_x_mirror_face_up_single_sided_exports(tmp_path) -> None:
    captured: dict[str, object] = {}
    export_transform_metadata: dict[str, object] = {}

    def _fake_export_scene_with_bambu_metadata(**kwargs) -> str:
        captured.update(kwargs)
        return kwargs["output_path"]

    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box(extents=[20, 10, 1]), geom_name="Slot 1")

    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "face-up-local.3mf",
    ), patch.object(
        s09_export_3mf,
        "export_scene_with_bambu_metadata",
        _fake_export_scene_with_bambu_metadata,
    ):
        s09_export_3mf.run(
            _make_minimal_s09_ctx(
                tmp_path,
                scene=scene,
                bambu_face_orientation="up",
                center_on_bed=False,
                export_transform_metadata=export_transform_metadata,
            )
        )

    exported_scene = captured["scene"]
    bounds = exported_scene.bounds
    center_x = (bounds[0][0] + bounds[1][0]) / 2
    assert center_x == 0
    assert captured["face_orientation"] == "up"
    assert export_transform_metadata["x_mirrored"] is False
    assert export_transform_metadata["mirror_span_mm"] == pytest.approx(16.0)


def test_s09_passes_face_double_for_doublesided(tmp_path) -> None:
    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "face-double.3mf",
    ), patch.object(s09_export_3mf, "export_scene_with_bambu_metadata", autospec=True) as mock_export:
        mock_export.return_value = str(tmp_path / "face-double.3mf")

        s09_export_3mf.run(_make_minimal_s09_ctx(tmp_path, bambu_face_orientation="double"))

    assert mock_export.call_args.kwargs["face_orientation"] == "double"


def test_s09_passes_device_profile_id_to_exporter(tmp_path) -> None:
    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "registry-device.3mf",
    ), patch.object(s09_export_3mf, "export_scene_with_bambu_metadata", autospec=True) as mock_export:
        mock_export.return_value = str(tmp_path / "registry-device.3mf")

        s09_export_3mf.run(
            _make_minimal_s09_ctx(
                tmp_path,
                device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
            )
        )

    assert mock_export.call_args.kwargs["device_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d:0.4"


def test_s09_trims_template_filament_slots_for_material_archive(tmp_path) -> None:
    captured: dict[str, object] = {}

    def _fake_export_scene_with_bambu_metadata(**kwargs) -> str:
        captured.update(kwargs)
        return kwargs["output_path"]

    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "material-archive.3mf",
    ), patch.object(
        s09_export_3mf,
        "export_scene_with_bambu_metadata",
        _fake_export_scene_with_bambu_metadata,
    ):
        s09_export_3mf.run(
            _make_minimal_s09_ctx(
                tmp_path,
                material_source="material_archive",
                device_profile_id="BambuStudio:bbl:bambu-lab-x2d:0.4",
            )
        )

    assert captured["preserve_template_filament_slots"] is False


@pytest.fixture
def capture_export_logs(caplog, monkeypatch):
    target_logger = logging.getLogger("lumina.core.pipeline.s09_export_3mf")
    # Capture at this logger once, independent of prior logging bootstrap.
    monkeypatch.setattr(target_logger, "propagate", False)
    target_logger.addHandler(caplog.handler)
    try:
        yield
    finally:
        target_logger.removeHandler(caplog.handler)


@pytest.mark.usefixtures("capture_export_logs")
def test_s09_empty_scene_error_log_has_actionable_fields(tmp_path, caplog) -> None:
    empty_scene = trimesh.Scene()
    ctx = _make_minimal_s09_ctx(tmp_path, scene=empty_scene)

    caplog.set_level(logging.ERROR, logger="lumina.core.pipeline.s09_export_3mf")

    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "empty-scene.3mf",
    ), patch.object(s09_export_3mf, "export_scene_with_bambu_metadata", autospec=True) as mock_export:
        result = s09_export_3mf.run(ctx)

    assert result["error"] == "[ERROR] Mesh generation failed: No valid meshes generated"
    assert "out_path" not in result
    mock_export.assert_not_called()

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "s09_export_3mf_empty_scene"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.ERROR
    assert record.error_type == "EmptySceneError"
    assert record.error_message == "No valid meshes generated"
    assert record.geometry_count == 0
    assert record.color_mode == "4-Color"
    assert record.modeling_mode == str(ModelingMode.HIGH_FIDELITY)
    assert record.out_path == str(tmp_path / "empty-scene.3mf")


@pytest.mark.usefixtures("capture_export_logs")
def test_s09_writer_error_log_has_actionable_fields(tmp_path, caplog) -> None:
    ctx = _make_minimal_s09_ctx(tmp_path)

    caplog.set_level(logging.ERROR, logger="lumina.core.pipeline.s09_export_3mf")

    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "writer-failed.3mf",
    ), patch.object(s09_export_3mf, "export_scene_with_bambu_metadata", autospec=True) as mock_export:
        mock_export.side_effect = RuntimeError("writer unavailable")
        result = s09_export_3mf.run(ctx)

    assert result["error"] == "[ERROR] 3MF export failed: writer unavailable"
    assert "out_path" not in result

    records = [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "s09_export_3mf_failed"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.ERROR
    assert record.error_type == "RuntimeError"
    assert record.error_message == "writer unavailable"
    assert record.color_mode == "4-Color"
    assert record.modeling_mode == str(ModelingMode.HIGH_FIDELITY)
    assert record.printer_id == "bambu-h2d"
    assert record.slicer == "BambuStudio"
    assert record.out_path == str(tmp_path / "writer-failed.3mf")


def test_s09_centers_export_scene_on_printer_bed(tmp_path) -> None:
    captured: dict[str, object] = {}

    def _fake_export_scene_with_bambu_metadata(**kwargs) -> str:
        captured.update(kwargs)
        return kwargs["output_path"]

    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box(extents=[20, 10, 1]), geom_name="Slot 1")

    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "centered.3mf",
    ), patch.object(
        s09_export_3mf,
        "export_scene_with_bambu_metadata",
        _fake_export_scene_with_bambu_metadata,
    ):
        result = s09_export_3mf.run(
            _make_minimal_s09_ctx(
                tmp_path,
                scene=scene,
                printer_id="bambu-p1s",
            )
        )

    assert result["out_path"] == str(tmp_path / "centered.3mf")
    exported_scene = captured["scene"]
    bounds = exported_scene.bounds
    center_x = (bounds[0][0] + bounds[1][0]) / 2
    center_y = (bounds[0][1] + bounds[1][1]) / 2
    assert center_x == 128
    assert center_y == 128


def test_s09_can_skip_bed_centering_for_piece_local_exports(tmp_path) -> None:
    captured: dict[str, object] = {}

    def _fake_export_scene_with_bambu_metadata(**kwargs) -> str:
        captured.update(kwargs)
        return kwargs["output_path"]

    scene = trimesh.Scene()
    scene.add_geometry(trimesh.creation.box(extents=[20, 10, 1]), geom_name="Slot 1")

    with patch.object(s09_export_3mf, "MODELS_DIR", str(tmp_path)), patch.object(
        s09_export_3mf,
        "generate_model_filename",
        lambda *_args: "piece-local.3mf",
    ), patch.object(
        s09_export_3mf,
        "export_scene_with_bambu_metadata",
        _fake_export_scene_with_bambu_metadata,
    ):
        result = s09_export_3mf.run(
            _make_minimal_s09_ctx(
                tmp_path,
                scene=scene,
                printer_id="bambu-p1s",
                center_on_bed=False,
            )
        )

    assert result["out_path"] == str(tmp_path / "piece-local.3mf")
    exported_scene = captured["scene"]
    bounds = exported_scene.bounds
    center_x = (bounds[0][0] + bounds[1][0]) / 2
    center_y = (bounds[0][1] + bounds[1][1]) / 2
    assert center_x == 16
    assert center_y == 0
