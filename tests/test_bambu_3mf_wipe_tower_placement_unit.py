from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET
import zipfile

import pytest
import trimesh

from config import list_printer_profiles
from core.machine_registry import load_machine_registry, resolve_machine_registry_root
from core.wipe_tower_placement import (
    Rect,
    WipeTowerPlacementRequest,
    _layout_is_safe,
)
from utils.bambu_3mf_writer import (
    BambuStudio3MFWriter,
    _build_wipe_tower_placement_request,
    read_wipe_tower_placement_warnings,
)
from utils.fatcat_metadata import (
    compose_builtin_project_settings,
    compose_project_settings,
    read_project_layout,
)


def _add_material_boxes(
    writer: BambuStudio3MFWriter,
    *,
    width: float,
    depth: float,
    height: float = 2.0,
    count: int = 4,
) -> None:
    for index in range(count):
        writer.add_mesh(
            trimesh.creation.box(extents=[width, depth, height]),
            f"Material {index + 1}",
            ((index * 50) % 255, (index * 80) % 255, (index * 110) % 255),
        )


def _project_settings(writer: BambuStudio3MFWriter) -> dict[str, object]:
    original_path = writer.output_path
    try:
        with TemporaryDirectory() as directory:
            writer.output_path = str(Path(directory) / "placement.3mf")
            writer.export()
            with zipfile.ZipFile(writer.output_path) as package:
                return json.loads(package.read("Metadata/project_settings.config"))
    finally:
        writer.output_path = original_path


def _placement_request(
    writer: BambuStudio3MFWriter,
) -> WipeTowerPlacementRequest:
    request = writer._build_fatcat_project_request(
        writer._build_material_palette()[0], writer._select_metadata_target(),
    )
    if request.get("project_source") == "fatcat_native":
        result = compose_builtin_project_settings(request)
    else:
        result = compose_project_settings(writer._get_base_config_template(), request)
    template = json.loads(result["project_settings_json"])
    bounds_min, bounds_max = writer._get_mesh_bounds()
    request = _build_wipe_tower_placement_request(
        read_project_layout(template, slicer_id=writer.slicer),
        printer_id=writer.printer_id, slicer=writer.slicer, nozzle_size=writer.nozzle_size,
        model_bounds=Rect(
            float(bounds_min[0]),
            float(bounds_min[1]),
            float(bounds_max[0]),
            float(bounds_max[1]),
        ),
        model_height=float(bounds_max[2] - bounds_min[2]),
        material_count=len(writer._build_material_palette()[0]),
    )
    assert request is not None
    return request


def _assert_native_a1_rib_has_no_space(writer: BambuStudio3MFWriter) -> None:
    """Prove the reserved native rib envelope cannot fit either free strip."""
    request = _placement_request(writer)
    assert request.tower_square_rib_body is True
    assert request.purge_volume == 45.0
    assert request.tower_infill_spacing_ratio == 1.5
    assert request.layer_height == 0.08
    assert request.model_brim == 5.0
    assert request.tower_brim == 3.0
    assert request.tower_rib_width == 8.0
    # Ignoring discrete paths and structural lines already gives a 50.31 mm
    # square. Brims, ribs, edge clearance and model separation only enlarge
    # it. The same lower bound applies to every configured strip width.
    body_min = ((request.material_count - 1) * request.purge_volume
                / request.layer_height * request.tower_infill_spacing_ratio) ** 0.5
    tower_min = body_min + 2 * (request.tower_brim + request.edge_clearance) + request.tower_rib_width
    model_margin = request.model_brim + request.edge_clearance
    separation = request.model_tower_clearance - 2 * request.edge_clearance
    assert request.model_bounds.width + 2 * model_margin + tower_min + separation > 180
    assert request.model_bounds.height + 2 * model_margin + tower_min + separation > 180


def _auto_placement_profile_slicer_cases() -> tuple[
    tuple[str, str, str | None], ...
]:
    cases: list[tuple[str, str, str | None]] = []
    registry = load_machine_registry(resolve_machine_registry_root() / "registry.json")
    for profile in list_printer_profiles():
        devices = [
            device for device in registry.devices_by_id.values()
            if device.supported
            and device.nozzle_size == "0.4"
            and device.display_name.casefold() == profile.display_name.casefold()
            and device.brand.casefold() == profile.brand.casefold()
        ]
        cases.extend(
            (profile.id, device.slicer_id, device.device_profile_id)
            for device in devices
        )
    return tuple(cases)


@pytest.mark.parametrize(
    ("printer_id", "slicer", "expected_volume"),
    (
        # These are the active native material defaults for the selected
        # slicer profiles, not values inferred from a legacy machine template.
        ("bambu-a1-mini", "BambuStudio", 45.0),
        ("bambu-a1-mini", "OrcaSlicer", 30.0),
        ("flashforge-creator-5", "FlashStudio", 45.0),
        ("anycubic-kobra-3-v2", "AnycubicSlicerNext", 20.0),
    ),
)
def test_tower_planning_uses_native_slicer_prime_volume(
    printer_id: str,
    slicer: str,
    expected_volume: float,
) -> None:
    writer = BambuStudio3MFWriter(
        "prime-volume.3mf",
        printer_id=printer_id,
        slicer=slicer,
    )
    _add_material_boxes(writer, width=4.0, depth=4.0, height=1.2, count=1)

    layout = read_project_layout(writer._get_base_config_template(), slicer_id=slicer)
    assert layout["purge_volume"] == pytest.approx(expected_volume)


@pytest.mark.parametrize(
    ("slicer", "wall_fields", "rib_width", "square_rib_body"),
    [
        ("OrcaSlicer", {"wipe_tower_wall_type": "rib"}, 8.0, True),
        ("OrcaSlicer", {"wipe_tower_wall_type": "rectangle"}, 0.0, False),
        ("OrcaSlicer", {"wipe_tower_wall_type": "rib", "wipe_tower_rib_width": "0"}, 0.0, True),
        ("BambuStudio", {"prime_tower_rib_wall": "1"}, 8.0, True),
        ("BambuStudio", {"prime_tower_rib_wall": "1", "prime_tower_rib_width": "0"}, 0.0, True),
        ("BambuStudio", {"prime_tower_rib_wall": "0"}, 0.0, False),
    ],
)
def test_layout_consumes_native_rib_settings(slicer, wall_fields, rib_width, square_rib_body) -> None:
    writer = BambuStudio3MFWriter("rib-layout.3mf", slicer=slicer)
    prefix = "prime_tower" if slicer == "BambuStudio" else "wipe_tower"
    project = {
        "printable_area": ["0x0", "256x0", "256x256", "0x256"],
        "prime_tower_brim_width": "3", "prime_tower_infill_gap": "150%",
        "prime_volume": "45", f"{prefix}_rib_width": "8",
        f"{prefix}_extra_rib_length": "6", **wall_fields,
    }
    request = _build_wipe_tower_placement_request(
        read_project_layout(project, slicer_id=slicer),
        printer_id=writer.printer_id, slicer=slicer, nozzle_size=writer.nozzle_size,
        model_bounds=Rect(0.0, 0.0, 18.6, 13.2),
        model_height=1.2, material_count=8,
    )
    assert request is not None
    assert request.tower_rib_width == rib_width
    assert request.tower_square_rib_body is square_rib_body
    assert request.tower_extra_rib_length == 6.0
    assert request.tower_brim == 3.0
    assert request.tower_infill_spacing_ratio == 1.5
    assert request.purge_volume == 45.0


@pytest.mark.parametrize(
    ("printer_id", "slicer", "device_profile_id"),
    _auto_placement_profile_slicer_cases(),
    ids=lambda value: str(value) if value is not None else "default-profile",
)
def test_enabled_auto_placement_replans_typical_model_across_all_profiles(
    printer_id: str,
    slicer: str,
    device_profile_id: str | None,
) -> None:
    writer = BambuStudio3MFWriter(
        "auto-placement.3mf",
        printer_id=printer_id,
        slicer=slicer,
        device_profile_id=device_profile_id,
    )
    _add_material_boxes(writer, width=60.0, depth=60.0, height=1.2)

    request = _placement_request(writer)
    settings = _project_settings(writer)
    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.adapted is True
    assert placement.requires_manual_adjustment is False
    assert placement.reason.startswith("adapted_")
    assert placement.tower_depth > 0.0
    assert _layout_is_safe(placement, request)
    assert placement.model_bounds.width == pytest.approx(request.model_bounds.width)
    assert placement.model_bounds.height == pytest.approx(request.model_bounds.height)
    assert writer._get_build_item_translation()[:2] == pytest.approx(
        placement.model_translation
    )
    assert isinstance(settings["wipe_tower_x"], list)
    assert isinstance(settings["wipe_tower_y"], list)
    assert float(settings["wipe_tower_x"][0]) == pytest.approx(placement.tower_x)
    assert float(settings["wipe_tower_y"][0]) == pytest.approx(placement.tower_y)
    assert float(settings["prime_tower_width"]) == pytest.approx(
        placement.tower_width
    )
    assert float(settings["wipe_tower_rotation_angle"]) == pytest.approx(
        placement.tower_rotation
    )

    assert (placement.tower_x, placement.tower_y) != pytest.approx(
        (request.tower_x, request.tower_y)
    )

    template_shape = (request.tower_width, request.tower_rotation)
    if (placement.tower_width, placement.tower_rotation) == pytest.approx(
        template_shape
    ):
        # A few FlashStudio templates already use the solver's preferred
        # 30 mm tower shape; auto layout must still replace their coordinates.
        assert template_shape == pytest.approx((30.0, 0.0))


def test_qidi_comma_grouped_bed_exclusions_are_parsed_as_polygons() -> None:
    q2_polygons = tuple(
        tuple(tuple(point) for point in polygon)
        for polygon in read_project_layout(
            {"bed_exclude_area": ["0x0,11x0,11x16,0x16"]},
            slicer_id="QIDIStudio",
        )["bed_exclusions"]
    )
    x_max_polygons = tuple(
        tuple(tuple(point) for point in polygon)
        for polygon in read_project_layout(
            {"bed_exclude_area": [
                "0x0,16x0,16x13,0x13,0x0,0x0,0x0,0x0,"
                "0x13,6x13,6x23,0x23,0x13,0x13,0x13,0x13,"
                "0x387,53x387,53x390,0x390,0x387,0x387,0x397,0x390,"
                "338x390,338x384,390x384,390x390,0x390"
            ]},
            slicer_id="QIDIStudio",
        )["bed_exclusions"]
    )

    assert q2_polygons == (
        ((0.0, 0.0), (11.0, 0.0), (11.0, 16.0), (0.0, 16.0)),
    )
    assert len(x_max_polygons) == 7
    assert x_max_polygons[0] == (
        (0.0, 0.0),
        (16.0, 0.0),
        (16.0, 13.0),
        (0.0, 13.0),
    )
    assert x_max_polygons[-1] == (
        (338.0, 390.0),
        (338.0, 384.0),
        (390.0, 384.0),
        (390.0, 390.0),
        (0.0, 390.0),
    )


def test_irregular_nine_point_bed_exclusion_remains_one_polygon() -> None:
    points = (
        (0.0, 4.0),
        (1.0, 1.0),
        (4.0, 0.0),
        (7.0, 1.0),
        (8.0, 4.0),
        (7.0, 7.0),
        (4.0, 8.0),
        (1.0, 7.0),
        (0.0, 4.0),
    )

    polygons = tuple(
        tuple(tuple(point) for point in polygon)
        for polygon in read_project_layout(
            {"bed_exclude_area": [",".join(f"{x:g}x{y:g}" for x, y in points)]},
            slicer_id="QIDIStudio",
        )["bed_exclusions"]
    )

    assert polygons == (points,)


def test_subdivided_rectangle_edges_are_not_treated_as_qidi_sentinels() -> None:
    points = (
        (0.0, 0.0),
        (1.0, 0.0),
        (2.0, 0.0),
        (3.0, 0.0),
        (4.0, 0.0),
        (4.0, 1.0),
        (4.0, 2.0),
        (4.0, 3.0),
        (4.0, 4.0),
        (3.0, 4.0),
        (2.0, 4.0),
        (0.0, 4.0),
        (0.0, 0.0),
    )

    polygons = tuple(
        tuple(tuple(point) for point in polygon)
        for polygon in read_project_layout(
            {"bed_exclude_area": [",".join(f"{x:g}x{y:g}" for x, y in points)]},
            slicer_id="QIDIStudio",
        )["bed_exclusions"]
    )

    assert polygons == (points,)


@pytest.mark.parametrize(
    ("printer_id", "model_size"),
    (
        ("qidi-q2", (200.0, 180.0)),
        ("qidi-x-max-4", (300.0, 280.0)),
    ),
)
def test_qidi_auto_layout_respects_real_template_bed_exclusions(
    printer_id: str,
    model_size: tuple[float, float],
) -> None:
    writer = BambuStudio3MFWriter(
        "qidi-exclusion-layout.3mf",
        printer_id=printer_id,
        slicer="QIDIStudio",
    )
    _add_material_boxes(writer, width=model_size[0], depth=model_size[1])

    request = _placement_request(writer)
    placement = writer._get_wipe_tower_placement()

    assert request.bed_exclusions
    assert placement is not None
    assert placement.requires_manual_adjustment is False
    assert _layout_is_safe(placement, request)


def test_p1s_auto_layout_uses_compact_right_side_tower() -> None:
    writer = BambuStudio3MFWriter(
        "p1s-auto-layout.3mf",
        printer_id="bambu-p1s",
        slicer="BambuStudio",
    )
    _add_material_boxes(writer, width=60.0, depth=60.0)

    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.reason == "adapted_right"
    assert placement.model_translation == pytest.approx((128.0, 128.0))
    assert placement.tower_outer_bounds.left > placement.model_outer_bounds.right
    assert placement.tower_outer_bounds.right <= 256
    assert placement.tower_bounds.center[1] == pytest.approx(128.0)
    assert placement.tower_width == pytest.approx(30.0)
    assert placement.tower_rotation == pytest.approx(0.0)


def test_u1_auto_placement_changes_tower_size_and_position_for_typical_model() -> None:
    writer = BambuStudio3MFWriter(
        "u1-typical-auto-placement.3mf",
        printer_id="snapmaker-u1",
        slicer="SnapmakerOrca",
        device_profile_id="SnapmakerOrca:snapmaker:snapmaker-u1:0.4",
    )
    _add_material_boxes(writer, width=60.0, depth=60.0, height=1.2)

    template = writer._get_base_config_template()
    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.adapted is True
    assert placement.requires_manual_adjustment is False
    assert placement.tower_width > 0
    # The native rib planner squares the body before recalculating paths.
    # A wider conservative estimate must not shrink the reserved Y extent.
    assert placement.tower_bounds.height >= placement.tower_bounds.width
    assert "wipe_tower_x" not in template
    assert "wipe_tower_y" not in template
    assert placement.tower_x is not None
    assert placement.tower_y is not None


def test_disabled_auto_placement_preserves_u1_template_without_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "snapmaker-u1-auto-placement-disabled.3mf"
    writer = BambuStudio3MFWriter(
        str(output_path),
        printer_id="snapmaker-u1",
        slicer="SnapmakerOrca",
        device_profile_id="SnapmakerOrca:snapmaker:snapmaker-u1:0.4",
        enable_wipe_tower_auto_placement=False,
    )
    _add_material_boxes(writer, width=180.0, depth=230.0)
    template = writer._get_base_config_template()

    def fail_if_solver_runs(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("wipe-tower solver must not run when disabled")

    monkeypatch.setattr(
        "utils.bambu_3mf_writer.solve_wipe_tower_placement",
        fail_if_solver_runs,
    )

    writer.export()

    with zipfile.ZipFile(output_path) as package:
        settings = json.loads(package.read("Metadata/project_settings.config"))
        placement = json.loads(
            package.read("Metadata/lumina_wipe_tower_placement.json")
        )

    for key in (
        "wipe_tower_x",
        "wipe_tower_y",
        "prime_tower_width",
        "wipe_tower_rotation_angle",
    ):
        if key in template:
            assert settings[key] == template[key]
        else:
            assert key not in settings
    assert placement == {
        "schema_version": 1,
        "enabled": False,
        "available": False,
        "adapted": False,
        "requires_manual_adjustment": False,
        "warning_code": None,
        "reason": "disabled_by_user",
    }
    assert read_wipe_tower_placement_warnings(output_path) == []


@pytest.mark.parametrize("slicer", ("BambuStudio", "OrcaSlicer"))
def test_a1_mini_uses_vertical_strip_for_tall_model(
    slicer: str,
) -> None:
    writer = BambuStudio3MFWriter(
        "a1-mini-tall.3mf",
        printer_id="bambu-a1-mini",
        slicer=slicer,
    )
    _add_material_boxes(writer, width=100.0, depth=155.0)

    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.requires_manual_adjustment is False
    assert placement.warning_code is None
    if slicer == "BambuStudio":
        assert placement.tower_wall_type == "rectangle"
        assert placement.reason == "adapted_right_rectangle"
        _assert_native_a1_rib_has_no_space(writer)
    else:
        assert placement.tower_wall_type is None
        assert placement.reason == "adapted_right"
    assert placement.adapted is True
    settings = _project_settings(writer)
    assert _layout_is_safe(placement, _placement_request(writer))
    assert placement.model_bounds.width == pytest.approx(100.0)
    assert placement.model_bounds.height == pytest.approx(155.0)
    assert placement.tower_width == pytest.approx(30.0)
    assert placement.tower_bounds.height > placement.tower_bounds.width
    assert settings["wipe_tower_rotation_angle"] == "0"
    assert placement.tower_bounds.right + 3.0 <= 178.0 + 1e-6
    assert float(settings["wipe_tower_x"][0]) == pytest.approx(placement.tower_bounds.left)
    assert float(settings["wipe_tower_y"][0]) == pytest.approx(placement.tower_bounds.bottom)
    assert set(settings["different_settings_to_system"][0].split(";")) >= {
        "prime_tower_width", "wipe_tower_rotation_angle", "wipe_tower_x", "wipe_tower_y",
    }
    if slicer == "BambuStudio":
        assert writer._get_base_config_template()["prime_tower_rib_wall"] == "1"
        assert settings["prime_tower_rib_wall"] == "0"
        assert "prime_tower_rib_wall" in (
            settings["different_settings_to_system"][0].split(";")
        )


def test_a1_mini_adapted_strip_keeps_visible_physical_edge_clearance() -> None:
    writer = BambuStudio3MFWriter(
        "a1-mini-real-wide.3mf",
        printer_id="bambu-a1-mini",
        slicer="BambuStudio",
    )
    _add_material_boxes(writer, width=110.0, depth=124.0, height=1.2)

    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.requires_manual_adjustment is False
    assert placement.warning_code is None
    assert placement.tower_wall_type == "rectangle"
    assert placement.reason.endswith("_rectangle")
    assert placement.adapted is True
    _assert_native_a1_rib_has_no_space(writer)
    assert _layout_is_safe(placement, _placement_request(writer))
    assert placement.model_bounds.width == pytest.approx(110.0)
    assert placement.model_bounds.height == pytest.approx(124.0)
    assert placement.tower_width == pytest.approx(30.0)
    assert placement.tower_bounds.height > placement.tower_bounds.width
    physical_tower = placement.tower_bounds.expanded(3.0)
    assert physical_tower.left >= 4.0 - 1e-6
    assert physical_tower.bottom >= 4.0 - 1e-6
    assert physical_tower.right <= 176.0 + 1e-6
    assert physical_tower.top <= 176.0 + 1e-6


def test_elegoo_cc2_adapted_strip_keeps_visible_physical_edge_clearance() -> None:
    writer = BambuStudio3MFWriter(
        "cc2-real-wide.3mf",
        printer_id="elegoo-cc2",
        slicer="ElegooSlicer",
    )
    _add_material_boxes(writer, width=200.0, depth=115.0, height=1.2)

    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.requires_manual_adjustment is False
    assert placement.adapted is True
    assert placement.tower_width == pytest.approx(200.0)
    physical_tower = placement.tower_bounds.expanded(3.0)
    assert physical_tower.left >= 4.0 - 1e-6
    assert physical_tower.bottom >= 4.0 - 1e-6
    assert physical_tower.right <= 252.0 + 1e-6
    assert physical_tower.top <= 224.0 + 1e-6


def test_a1_mini_uses_nearest_feasible_width_when_30_mm_would_squeeze_model() -> None:
    writer = BambuStudio3MFWriter(
        "a1-mini-real-tall.3mf",
        printer_id="bambu-a1-mini",
        slicer="BambuStudio",
    )
    _add_material_boxes(writer, width=130.0, depth=146.6)

    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.requires_manual_adjustment is False
    assert placement.warning_code is None
    assert placement.tower_wall_type == "rectangle"
    assert placement.reason.endswith("_rectangle")
    _assert_native_a1_rib_has_no_space(writer)
    assert _layout_is_safe(placement, _placement_request(writer))
    assert placement.model_bounds.width == pytest.approx(130.0)
    assert placement.model_bounds.height == pytest.approx(146.6)
    assert placement.tower_width == pytest.approx(22.0)
    assert placement.tower_bounds.height > placement.tower_bounds.width
    assert (placement.tower_bounds.left - 3.0) - (placement.model_bounds.right + 5.0) >= 8.0 - 1e-6


@pytest.mark.parametrize("material_count", (4, 5, 6, 8))
def test_orca_multicolor_project_collapses_dual_variant_filament_arrays(
    material_count: int,
) -> None:
    writer = BambuStudio3MFWriter(
        "a1-mini-orca-multicolor.3mf",
        printer_id="bambu-a1-mini",
        slicer="OrcaSlicer",
        color_mode=(
            "8-Color Max"
            if material_count == 8
            else "6-Color"
            if material_count == 6
            else "5-Color Extended"
            if material_count == 5
            else "4-Color"
        ),
    )
    _add_material_boxes(
        writer,
        # Palette normalization needs a feasible footprint for every count;
        # automatic layout rejection is covered by its dedicated cases.
        width=40.0,
        depth=40.0,
        count=material_count,
    )

    settings = _project_settings(writer)

    assert len(settings["filament_colour"]) == material_count
    assert len(settings["filament_settings_id"]) == material_count
    source = writer._get_base_config_template()
    for key in (
        "filament_extruder_variant",
        "filament_flow_ratio",
        "filament_max_volumetric_speed",
        "filament_retraction_length",
        "filament_self_index",
    ):
        assert len(settings[key]) == material_count
    assert "flush_volumes_vector" not in source
    assert "flush_volumes_vector" not in settings


def test_profile_model_brim_is_reserved_unless_explicitly_disabled() -> None:
    writer = BambuStudio3MFWriter(
        "profile-brim.3mf",
        printer_id="bambu-a1-mini",
        slicer="OrcaSlicer",
    )
    _add_material_boxes(writer, width=100.0, depth=100.0)

    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.model_outer_bounds.width == pytest.approx(114.0)

    no_brim_writer = BambuStudio3MFWriter(
        "no-brim.3mf",
        printer_id="bambu-a1-mini",
        slicer="OrcaSlicer",
        settings={"brim_type": "no_brim", "brim_width": "5"},
    )
    _add_material_boxes(no_brim_writer, width=100.0, depth=100.0)

    no_brim_placement = no_brim_writer._get_wipe_tower_placement()

    assert no_brim_placement is not None
    assert no_brim_placement.model_outer_bounds.width == pytest.approx(104.0)


@pytest.mark.parametrize(
    "printer_id",
    ["flashforge-creator-5", "flashforge-creator-5-pro"],
)
def test_c5_family_uses_30_mm_vertical_strip_for_tall_model(printer_id: str) -> None:
    writer = BambuStudio3MFWriter(
        "c5-long-strip.3mf",
        printer_id=printer_id,
        slicer="FlashStudio",
    )
    # The native 35 mm tower is the template input for small models.
    # Flash Studio expands a nominal narrow tower to a roughly 58.5 x 61 mm
    # interface footprint. A 200 mm horizontal setting is therefore clamped
    # back into this tall model; the native-safe fallback is the 30 mm width
    # idiom plus a left translation of the unchanged model.
    _add_material_boxes(writer, width=180.0, depth=203.0)

    settings = _project_settings(writer)
    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.adapted is True
    assert placement.requires_manual_adjustment is False
    assert placement.reason in {"adapted_right", "adapted_left"}
    assert float(settings["prime_tower_width"]) == pytest.approx(30.0)
    assert settings["enable_prime_tower"] == "1"
    assert placement.tower_bounds.width == pytest.approx(58.5)
    assert placement.tower_bounds.height >= 61.0
    assert placement.model_bounds.width == pytest.approx(180.0)
    assert placement.model_bounds.left == pytest.approx(5.0)
    model_brim_right = placement.model_bounds.right + 5.0
    assert placement.tower_bounds.left - model_brim_right >= 7.5 - 1e-6


def test_kobra_3_v2_reserves_anycubic_native_tower_envelope() -> None:
    writer = BambuStudio3MFWriter(
        "kobra-3-v2-native-envelope.3mf",
        printer_id="anycubic-kobra-3-v2",
        slicer="AnycubicSlicerNext",
    )
    # Anycubic Slicer Next clamps a nominal 30 mm tower to X=205 and
    # Y=197.5 on the 255 mm Kobra 3 V2 bed. This exposes a native envelope
    # of 50 x 57.5 mm that is larger than the generic volume estimate.
    _add_material_boxes(writer, width=180.0, depth=203.0)

    settings = _project_settings(writer)
    placement = writer._get_wipe_tower_placement()

    assert placement is not None
    assert placement.adapted is True
    assert placement.requires_manual_adjustment is False
    assert placement.reason in {"adapted_right", "adapted_left"}
    assert float(settings["prime_tower_width"]) == pytest.approx(30.0)
    assert settings["wipe_tower_rotation_angle"] == "0"
    assert placement.tower_bounds.width == pytest.approx(50.0)
    assert placement.tower_bounds.height >= 57.5
    assert placement.model_bounds.width == pytest.approx(180.0)
    assert placement.model_bounds.left >= 5.0
    model_brim_right = placement.model_bounds.right + 5.0
    assert placement.tower_bounds.left - model_brim_right >= 8.0 - 1e-6


def test_impossible_automatic_layout_exports_with_warning_and_preserves_tower(tmp_path: Path) -> None:
    output_path = tmp_path / "manual-adjustment-required.3mf"
    writer = BambuStudio3MFWriter(
        str(output_path),
        printer_id="bambu-a1-mini",
        slicer="OrcaSlicer",
    )
    _add_material_boxes(writer, width=179.0, depth=179.0)
    writer.enable_wipe_tower_auto_placement = False
    baseline = _project_settings(writer)
    writer.enable_wipe_tower_auto_placement = True

    writer.export()

    assert output_path.exists()
    assert read_wipe_tower_placement_warnings(output_path) == ["wipe_tower_manual_adjustment_required"]
    with zipfile.ZipFile(output_path) as package:
        settings = json.loads(package.read("Metadata/project_settings.config"))
        placement = json.loads(package.read("Metadata/lumina_wipe_tower_placement.json"))
    assert placement["requires_manual_adjustment"] is True
    assert placement["adapted"] is False
    assert placement["placement_applied"] is False
    for key in ("enable_prime_tower", "prime_tower_width", "wipe_tower_x", "wipe_tower_y", "wipe_tower_rotation_angle"):
        assert settings.get(key) == baseline.get(key)
    for entry in writer.objects:
        assert entry.mesh.extents[:2] == pytest.approx([179.0, 179.0])


def test_safe_export_embeds_no_manual_warning(tmp_path: Path) -> None:
    output_path = tmp_path / "safe.3mf"
    writer = BambuStudio3MFWriter(
        str(output_path),
        printer_id="bambu-p1s",
        slicer="BambuStudio",
    )
    _add_material_boxes(writer, width=80.0, depth=80.0)

    writer.export()

    assert read_wipe_tower_placement_warnings(output_path) == []


def test_missing_printable_area_exports_with_manual_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "missing-printable-area.3mf"
    writer = BambuStudio3MFWriter(
        str(output_path),
        printer_id="bambu-p1s",
        slicer="BambuStudio",
    )
    _add_material_boxes(writer, width=80.0, depth=80.0)
    template = writer._get_base_config_template()
    template.pop("printable_area", None)
    writer._custom_template = template

    writer.export()
    assert output_path.exists()
    assert read_wipe_tower_placement_warnings(output_path) == ["wipe_tower_manual_adjustment_required"]
