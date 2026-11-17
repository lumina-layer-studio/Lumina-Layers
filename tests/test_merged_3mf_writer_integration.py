"""Integration tests for MergedBambu3MFWriter — real writer, no mocks.

Validates the output 3MF is structurally correct for Bambu/Orca slicers:
- Per-item .model files have triangles > 0
- Top-level model has requiredextensions="p"
- Raw XML contains NO ns0:path (only p:path)
- Build items have printable="1"
- Component transforms from source are preserved in bbox calculation

LUM-20250519-001 Issue 2 regression tests.
"""

from __future__ import annotations

import json
import os
import tempfile
import tracemalloc
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pytest
import trimesh

from config import TEMP_DIR
from utils.bambu_3mf_writer import (
    export_scene_with_bambu_metadata,
    read_wipe_tower_placement_warnings,
)
from utils.merged_bambu_3mf_writer import (
    MergedBambu3MFWriter,
    MergedItem,
    MaterialSlot,
)

_NS_CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
_NS_PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"


def test_batch_footprint_reads_geometry_with_bounded_python_memory() -> None:
    """Layout inspection must not materialize every XML vertex and triangle."""
    from utils.merged_bambu_3mf_writer import read_merge_source_info

    source = _make_source_3mf(mesh_override=trimesh.creation.icosphere(subdivisions=5))
    try:
        # Initialise the metadata SDK before measuring the per-model reader.
        from utils.fatcat_metadata import read_source_metadata
        expected_slots = read_source_metadata(source)["slots"]
        tracemalloc.start()
        try:
            footprint, slots = read_merge_source_info(source)
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert footprint == pytest.approx((2.0, 2.0))
        assert slots == expected_slots
        # A normal ~20k-face input needs only a streaming XML buffer for layout.
        assert peak < 8 * 1024 * 1024, f"footprint inspection allocated {peak:,} bytes"
    finally:
        source.unlink(missing_ok=True)


def _make_source_3mf(
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    *,
    width_mm: float = 10.0,
    depth_mm: float = 8.0,
    height_mm: float = 2.0,
    printer_id: str = "bambu-h2d",
    slicer: str = "BambuStudio",
    enable_base_layer_height_modifier: bool = False,
    enable_wipe_tower_auto_placement: bool = True,
    backing_infill_density_percent: int = 100,
    base_height_mm: float = 0.8,
    color_height_mm: float = 2.4,
    mesh_override: trimesh.Trimesh | None = None,
) -> Path:
    """Create a minimal real Bambu 3MF with one slot."""
    os.makedirs(TEMP_DIR, exist_ok=True)
    scene = trimesh.Scene()
    if mesh_override is None:
        box = trimesh.creation.box(extents=[width_mm, depth_mm, height_mm])
        box.apply_translation(
            [
                offset_x + width_mm / 2.0,
                offset_y + depth_mm / 2.0,
                height_mm / 2.0,
            ]
        )
    else:
        box = mesh_override.copy()
    box.metadata["bambu_material_name"] = "Bambu PLA Black"
    scene.add_geometry(box, geom_name="Bambu PLA Black")

    fd, path = tempfile.mkstemp(suffix=".3mf", dir=TEMP_DIR, prefix="integ_src_")
    os.close(fd)
    export_scene_with_bambu_metadata(
        scene=scene,
        output_path=path,
        slot_names=["Bambu PLA Black"],
        preview_colors={"Bambu PLA Black": (16, 16, 16, 255)},
        settings={},
        color_mode="4-Color",
        printer_id=printer_id,
        slicer=slicer,
        enable_base_layer_height_modifier=enable_base_layer_height_modifier,
        enable_wipe_tower_auto_placement=enable_wipe_tower_auto_placement,
        base_height_mm=base_height_mm,
        color_height_mm=color_height_mm,
        face_orientation="down",
        backing_infill_density_percent=backing_infill_density_percent,
    )
    return Path(path)


def _replace_project_difference_index(
    path: Path,
    keys: list[str],
) -> None:
    """Replace only the source package's project override index."""

    replacement_path = path.with_suffix(".rewrite.3mf")
    with zipfile.ZipFile(path, "r") as source_package:
        with zipfile.ZipFile(
            replacement_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as replacement_package:
            for member in source_package.infolist():
                payload = source_package.read(member.filename)
                if member.filename == "Metadata/project_settings.config":
                    settings = json.loads(payload)
                    settings["different_settings_to_system"] = [
                        ";".join(keys)
                    ]
                    payload = json.dumps(settings).encode("utf-8")
                replacement_package.writestr(member, payload)
    os.replace(replacement_path, path)


class TestMergedWriterBambuCompatibility:
    """Real writer integration: output 3MF must be Bambu/Orca compatible."""

    def test_output_has_triangles_and_correct_structure(self) -> None:
        """Per-item .model files have triangles > 0, correct namespace prefixes."""
        src1 = _make_source_3mf(offset_x=0.0)
        src2 = _make_source_3mf(offset_x=15.0)

        items = [
            MergedItem(
                source_filename="a.png",
                source_3mf_path=src1,
                slots=(MaterialSlot(0, "Black", "#101010", "GFL00"),),
                tx_mm=0.0,
                ty_mm=0.0,
            ),
            MergedItem(
                source_filename="b.png",
                source_3mf_path=src2,
                slots=(MaterialSlot(0, "Black", "#101010", "GFL00"),),
                tx_mm=50.0,
                ty_mm=20.0,
            ),
        ]

        fd, out_path = tempfile.mkstemp(suffix=".3mf", dir=TEMP_DIR, prefix="integ_out_")
        os.close(fd)

        try:
            writer = MergedBambu3MFWriter()
            writer.write(
                items,
                Path(out_path),
                plate_width_mm=200.0,
                plate_depth_mm=200.0,
                # Preserve this fixture's origin; layout has separate cases.
                enable_wipe_tower_auto_placement=False,
            )

            with zipfile.ZipFile(out_path, "r") as zf:
                # 1. Top-level model has requiredextensions="p"
                main_xml = zf.read("3D/3dmodel.model").decode("utf-8")
                assert 'requiredextensions' in main_xml, (
                    "Missing requiredextensions attribute"
                )
                assert '"p"' in main_xml, "requiredextensions should be 'p'"
                main_root = ET.fromstring(main_xml)
                root_metadata = {
                    node.get("name"): node.text or ""
                    for node in main_root.findall(f"{{{_NS_CORE}}}metadata")
                }
                assert root_metadata.get("Application", "").startswith("BambuStudio-")
                assert root_metadata.get("BambuStudio:3mfVersion") == "1"

                # 2. No ns0:path in raw XML
                assert "ns0:path" not in main_xml, (
                    "Found ns0:path — namespace registration broken"
                )
                assert "ns0:" not in main_xml, (
                    "Found ns0: prefix — namespace registration broken"
                )

                # 3. Has p:path
                assert "p:path" in main_xml, "Missing p:path in components"

                # 4. Build items have printable="1"
                assert 'printable="1"' in main_xml, (
                    "Build items missing printable='1'"
                )

                # 5. Per-item models have triangles > 0
                for idx in range(1, 3):
                    model_path = f"3D/Objects/object_{idx}.model"
                    assert model_path in zf.namelist(), (
                        f"Missing {model_path}"
                    )
                    model_bytes = zf.read(model_path)
                    model_root = ET.fromstring(model_bytes)
                    tri_count = 0
                    for obj in model_root.iter(f"{{{_NS_CORE}}}object"):
                        mesh = obj.find(f"{{{_NS_CORE}}}mesh")
                        if mesh is None:
                            continue
                        tris = mesh.find(f"{{{_NS_CORE}}}triangles")
                        if tris is not None:
                            tri_count += len(tris.findall(f"{{{_NS_CORE}}}triangle"))
                    assert tri_count > 0, (
                        f"{model_path} has 0 triangles — slicer will show empty"
                    )

                # 6. Bambu/Orca project metadata keeps the plate/object
                # binding that makes process/material presets visible.
                settings_root = ET.fromstring(zf.read("Metadata/model_settings.config"))
                plate = settings_root.find("plate")
                assert plate is not None, "model_settings.config missing <plate>"
                model_instances = plate.findall("model_instance")
                assert len(model_instances) == 2
                config_objects = settings_root.findall("object")
                assert {
                    md.get("value")
                    for instance in model_instances
                    for md in instance.findall("metadata")
                    if md.get("key") == "object_id"
                } == {
                    obj.get("id") for obj in config_objects
                }
                assert all(
                    any(md.tag == "metadata" and "face_count" in md.attrib for md in obj)
                    for obj in config_objects
                )

                # 7. FatCat links every settings part and external model through
                # 3D/_rels/3dmodel.model.rels.
                ns_rels = "http://schemas.openxmlformats.org/package/2006/relationships"
                rels = ET.fromstring(zf.read("3D/_rels/3dmodel.model.rels"))
                relationships = rels.findall(f"{{{ns_rels}}}Relationship")
                assert {
                    (rel.get("Target") or "").lstrip("/")
                    for rel in relationships
                    if rel.get("Type")
                    == "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
                } == {
                    "3D/Objects/object_1.model",
                    "3D/Objects/object_2.model",
                }
                assert {
                    rel.get("Target") for rel in relationships
                    if rel.get("Type") == "http://schemas.bambulab.com/package/2021/settings"
                } == {
                    "/Metadata/model_settings.config", "/Metadata/project_settings.config",
                    "/Metadata/slice_info.config", "/Metadata/lumina_wipe_tower_placement.json",
                    "/Metadata/filament_sequence.json", "/Metadata/cut_information.xml",
                }
                assert all((rel.get("Target") or "").lstrip("/") in zf.namelist()
                           for rel in relationships)

                # 8. Root relationships carry the main model and any package
                # cover thumbnails that are present in the ZIP.
                names = set(zf.namelist())
                top_rels = ET.fromstring(zf.read("_rels/.rels"))
                top_relationships = top_rels.findall(f"{{{ns_rels}}}Relationship")
                top_targets = {
                    (rel.get("Target") or "").lstrip("/")
                    for rel in top_relationships
                }
                assert "3D/3dmodel.model" in top_targets
                assert top_targets.issubset(names)
                thumbnail_names = {
                    "Metadata/plate_1.png",
                    "Auxiliaries/.thumbnails/thumbnail_3mf.png",
                }
                if names & thumbnail_names:
                    assert top_targets & thumbnail_names

                # 9. Each serialized part has the FatCat dialect content type.
                ct_root = ET.fromstring(zf.read("[Content_Types].xml"))
                ct_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
                assert {
                    node.get("Extension")
                    for node in ct_root.findall(f"{{{ct_ns}}}Default")
                } == {"config", "json", "model", "png", "rels", "xml"}
                assert {
                    node.get("PartName"): node.get("ContentType")
                    for node in ct_root.findall(f"{{{ct_ns}}}Override")
                } == {
                    "/3D/3dmodel.model": "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
                    "/3D/Objects/object_1.model": "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
                    "/3D/Objects/object_2.model": "application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
                    "/Metadata/model_settings.config": "text/xml",
                    "/Metadata/project_settings.config": "text/xml",
                    "/Metadata/slice_info.config": "text/xml",
                    "/Metadata/cut_information.xml": "text/xml",
                    "/Metadata/filament_sequence.json": "application/json",
                    "/Metadata/lumina_wipe_tower_placement.json": "application/json",
                }

                # 10. These sidecars use model indexes in Bambu reference
                # packages; using generated assembly ids can make the slicer
                # drop project/process metadata while importing.
                cut_root = ET.fromstring(zf.read("Metadata/cut_information.xml"))
                assert [
                    obj.get("id")
                    for obj in cut_root.findall("object")
                ] == ["1", "2"]
                filament_sequence = json.loads(
                    zf.read("Metadata/filament_sequence.json").decode("utf-8")
                )
                assert filament_sequence == {
                    "plate_1": {
                        "nozzle_sequence": [],
                        "optimal_assignment": [],
                        "sequence": [],
                    }
                }
        finally:
            for p in (src1, src2, Path(out_path)):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass

    def test_component_transform_applied_to_bbox(self) -> None:
        """Source 3MF with non-identity component transform: world bbox min
        must equal placement after merge.

        This prevents regression of ignoring component transforms in bbox
        calculation.
        """
        # Create a source 3MF where the mesh is at local origin but the
        # component has a translation transform.
        src = _make_source_3mf(offset_x=20.0, offset_y=10.0)

        items = [
            MergedItem(
                source_filename="offset.png",
                source_3mf_path=src,
                slots=(MaterialSlot(0, "Black", "#101010", "GFL00"),),
                tx_mm=100.0,
                ty_mm=50.0,
            ),
        ]

        fd, out_path = tempfile.mkstemp(suffix=".3mf", dir=TEMP_DIR, prefix="integ_transform_")
        os.close(fd)

        try:
            writer = MergedBambu3MFWriter()
            writer.write(items, Path(out_path), plate_width_mm=300.0, plate_depth_mm=300.0)

            # Parse output and compute world bbox min.
            with zipfile.ZipFile(out_path, "r") as zf:
                main_root = ET.fromstring(zf.read("3D/3dmodel.model"))
                build = main_root.find(f"{{{_NS_CORE}}}build")
                build_items = build.findall(f"{{{_NS_CORE}}}item")
                assert len(build_items) == 1

                # Get build item transform.
                transform_str = build_items[0].get("transform")
                parts = transform_str.split()
                build_dx = float(parts[9])
                build_dy = float(parts[10])

                # Get per-item model vertices.
                resources = main_root.find(f"{{{_NS_CORE}}}resources")
                obj = resources.findall(f"{{{_NS_CORE}}}object")[0]
                components = obj.find(f"{{{_NS_CORE}}}components")
                comp = components.findall(f"{{{_NS_CORE}}}component")[0]
                per_item_path = comp.get(f"{{{_NS_PROD}}}path").lstrip("/")
                comp_transform_str = comp.get("transform", "1 0 0 0 1 0 0 0 1 0 0 0")
                comp_parts = comp_transform_str.split()
                comp_dx = float(comp_parts[9])
                comp_dy = float(comp_parts[10])

                mesh_id = comp.get("objectid")
                per_item_root = ET.fromstring(zf.read(per_item_path))
                per_item_resources = per_item_root.find(f"{{{_NS_CORE}}}resources")
                mesh_obj = None
                for o in per_item_resources.findall(f"{{{_NS_CORE}}}object"):
                    if o.get("id") == mesh_id:
                        mesh_obj = o
                        break
                assert mesh_obj is not None

                mesh = mesh_obj.find(f"{{{_NS_CORE}}}mesh")
                vertices = mesh.find(f"{{{_NS_CORE}}}vertices")
                min_x = float("inf")
                min_y = float("inf")
                for v in vertices.findall(f"{{{_NS_CORE}}}vertex"):
                    x = float(v.get("x"))
                    y = float(v.get("y"))
                    if x < min_x:
                        min_x = x
                    if y < min_y:
                        min_y = y

                # World bbox min = local vertex min + component transform + build transform
                world_min_x = min_x + comp_dx + build_dx
                world_min_y = min_y + comp_dy + build_dy

                assert abs(world_min_x - 100.0) < 1e-3, (
                    f"World min_x={world_min_x:.4f} != target tx_mm=100.0"
                )
                assert abs(world_min_y - 50.0) < 1e-3, (
                    f"World min_y={world_min_y:.4f} != target ty_mm=50.0"
                )
        finally:
            for p in (src, Path(out_path)):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass

    def test_per_item_model_preserves_adjacent_float32_vertices(self) -> None:
        """Merged serialization must not collapse distinct float32 vertices."""

        x0 = np.float32(200.0)
        x1 = np.nextafter(x0, np.float32(np.inf), dtype=np.float32)
        precision_mesh = trimesh.Trimesh(
            vertices=np.array(
                [
                    [x0, 0.0, 0.0],
                    [x1, 0.0, 0.0],
                    [x0, 1.0, 0.0],
                    [x0, 0.0, 1.0],
                ],
                dtype=np.float64,
            ),
            faces=np.array(
                [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]],
                dtype=np.int64,
            ),
            process=False,
        )
        assert precision_mesh.is_watertight
        source = _make_source_3mf(mesh_override=precision_mesh)
        item = MergedItem(
            source_filename="precision.png",
            source_3mf_path=source,
            slots=(MaterialSlot(0, "Black", "#101010", "GFL00"),),
            tx_mm=0.0,
            ty_mm=0.0,
        )
        fd, out_path = tempfile.mkstemp(
            suffix=".3mf",
            dir=TEMP_DIR,
            prefix="integ_precision_merged_",
        )
        os.close(fd)

        def mesh_coordinates(package_path: Path) -> tuple[
            list[tuple[float, float, float]],
            list[tuple[int, int, int]],
        ]:
            with zipfile.ZipFile(package_path) as package:
                root = ET.fromstring(package.read("3D/Objects/object_1.model"))
            coordinates = [
                (
                    float(vertex.get("x", "0")),
                    float(vertex.get("y", "0")),
                    float(vertex.get("z", "0")),
                )
                for vertex in root.findall(f".//{{{_NS_CORE}}}vertex")
            ]
            faces = [
                (
                    int(triangle.get("v1", "0")),
                    int(triangle.get("v2", "0")),
                    int(triangle.get("v3", "0")),
                )
                for triangle in root.findall(f".//{{{_NS_CORE}}}triangle")
            ]
            return coordinates, faces

        try:
            MergedBambu3MFWriter().write(
                [item],
                Path(out_path),
                plate_width_mm=300.0,
                plate_depth_mm=300.0,
                enable_wipe_tower_auto_placement=False,
            )

            source_coordinates, _source_faces = mesh_coordinates(source)
            merged_coordinates, merged_faces = mesh_coordinates(Path(out_path))
            assert len(set(source_coordinates)) == len(source_coordinates)
            assert len(set(merged_coordinates)) == len(merged_coordinates)
            np.testing.assert_array_equal(
                np.asarray(merged_coordinates, dtype=np.float32),
                np.asarray(source_coordinates, dtype=np.float32),
            )
            assert all(
                len({merged_coordinates[index] for index in face}) == 3
                for face in merged_faces
            )
        finally:
            source.unlink(missing_ok=True)
            Path(out_path).unlink(missing_ok=True)

    def test_merged_output_recomputes_wipe_tower_for_full_group(self) -> None:
        src1 = _make_source_3mf(
            width_mm=50.0,
            depth_mm=60.0,
            printer_id="bambu-a1-mini",
        )
        src2 = _make_source_3mf(
            width_mm=50.0,
            depth_mm=60.0,
            printer_id="bambu-a1-mini",
        )
        items = [
            MergedItem(
                source_filename="left.png",
                source_3mf_path=src1,
                slots=(MaterialSlot(0, "Black", "#101010", "GFL00"),),
                tx_mm=10.0,
                ty_mm=10.0,
            ),
            MergedItem(
                source_filename="right.png",
                source_3mf_path=src2,
                slots=(MaterialSlot(1, "White", "#FFFFFF", "GFA00"),),
                tx_mm=120.0,
                ty_mm=10.0,
            ),
        ]
        fd, out_path = tempfile.mkstemp(
            suffix=".3mf",
            dir=TEMP_DIR,
            prefix="integ_wipe_group_",
        )
        os.close(fd)

        try:
            MergedBambu3MFWriter().write(
                items,
                Path(out_path),
                plate_width_mm=180.0,
                plate_depth_mm=180.0,
            )

            with zipfile.ZipFile(out_path) as package:
                placement = json.loads(
                    package.read("Metadata/lumina_wipe_tower_placement.json")
                )
                settings = json.loads(
                    package.read("Metadata/project_settings.config")
                )

            model_bounds = placement["model_bounds_mm"]
            model_outer = placement["model_outer_bounds_mm"]
            tower_outer = placement["tower"]["outer_bounds_mm"]
            difference_index = set(
                settings["different_settings_to_system"][0].split(";")
            )
            assert model_bounds[2] - model_bounds[0] == pytest.approx(160.0)
            assert model_bounds[3] - model_bounds[1] == pytest.approx(60.0)
            assert placement["adapted"] is True
            assert placement["requires_manual_adjustment"] is False
            assert settings["enable_prime_tower"] == "1"
            assert float(settings["wipe_tower_x"][0]) == pytest.approx(
                placement["tower"]["x_mm"]
            )
            assert float(settings["wipe_tower_y"][0]) == pytest.approx(
                placement["tower"]["y_mm"]
            )
            assert (
                model_outer[2] <= tower_outer[0]
                or tower_outer[2] <= model_outer[0]
                or model_outer[3] <= tower_outer[1]
                or tower_outer[3] <= model_outer[1]
            )
            assert difference_index >= {
                "prime_tower_width",
                "wipe_tower_rotation_angle",
                "wipe_tower_x",
                "wipe_tower_y",
            }
            assert read_wipe_tower_placement_warnings(out_path) == []
        finally:
            for path in (src1, src2, Path(out_path)):
                path.unlink(missing_ok=True)

    def test_merged_output_replans_safe_native_tower_layout(
        self,
    ) -> None:
        """Enabled auto layout must replan even a collision-free template."""

        source = _make_source_3mf(
            width_mm=10.0,
            depth_mm=8.0,
            printer_id="bambu-h2d",
        )
        _replace_project_difference_index(source, ["enable_prime_tower"])
        item = MergedItem(
            source_filename="centered.png",
            source_3mf_path=source,
            slots=(MaterialSlot(0, "Black", "#101010", "GFL00"),),
            tx_mm=170.0,
            ty_mm=156.0,
        )
        fd, out_path = tempfile.mkstemp(
            suffix=".3mf",
            dir=TEMP_DIR,
            prefix="integ_wipe_native_",
        )
        os.close(fd)

        try:
            MergedBambu3MFWriter().write(
                [item],
                Path(out_path),
                plate_width_mm=350.0,
                plate_depth_mm=320.0,
            )

            with zipfile.ZipFile(out_path) as package:
                placement = json.loads(
                    package.read(
                        "Metadata/lumina_wipe_tower_placement.json"
                    )
                )
                settings = json.loads(
                    package.read("Metadata/project_settings.config")
                )

            difference_index = set(
                settings["different_settings_to_system"][0].split(";")
            )
            assert placement["adapted"] is True
            assert placement["requires_manual_adjustment"] is False
            assert float(settings["prime_tower_width"]) == pytest.approx(
                placement["tower"]["width_mm"]
            )
            assert float(settings["wipe_tower_x"][0]) == pytest.approx(
                placement["tower"]["x_mm"]
            )
            assert float(settings["wipe_tower_y"][0]) == pytest.approx(
                placement["tower"]["y_mm"]
            )
            assert difference_index >= {
                "enable_prime_tower",
                "prime_tower_width",
                "wipe_tower_rotation_angle",
                "wipe_tower_x",
                "wipe_tower_y",
            }
            assert read_wipe_tower_placement_warnings(out_path) == []
        finally:
            for path in (source, Path(out_path)):
                path.unlink(missing_ok=True)

    def test_merged_output_can_disable_wipe_tower_auto_placement(self) -> None:
        src1 = _make_source_3mf(
            width_mm=50.0,
            depth_mm=60.0,
            printer_id="bambu-a1-mini",
        )
        src2 = _make_source_3mf(
            width_mm=50.0,
            depth_mm=60.0,
            printer_id="bambu-a1-mini",
        )
        items = [
            MergedItem(
                source_filename="left.png",
                source_3mf_path=src1,
                slots=(MaterialSlot(0, "Black", "#101010", "GFL00"),),
                tx_mm=10.0,
                ty_mm=10.0,
            ),
            MergedItem(
                source_filename="right.png",
                source_3mf_path=src2,
                slots=(MaterialSlot(0, "Black", "#101010", "GFL00"),),
                tx_mm=120.0,
                ty_mm=10.0,
            ),
        ]
        fd, out_path = tempfile.mkstemp(
            suffix=".3mf",
            dir=TEMP_DIR,
            prefix="integ_wipe_disabled_",
        )
        os.close(fd)

        try:
            with zipfile.ZipFile(src1) as source_package:
                source_settings = json.loads(
                    source_package.read("Metadata/project_settings.config")
                )

            MergedBambu3MFWriter().write(
                items,
                Path(out_path),
                plate_width_mm=180.0,
                plate_depth_mm=180.0,
                enable_wipe_tower_auto_placement=False,
            )

            with zipfile.ZipFile(out_path) as package:
                placement = json.loads(
                    package.read("Metadata/lumina_wipe_tower_placement.json")
                )
                settings = json.loads(
                    package.read("Metadata/project_settings.config")
                )

            assert placement == {
                "schema_version": 1,
                "enabled": False,
                "available": False,
                "adapted": False,
                "requires_manual_adjustment": False,
                "warning_code": None,
                "reason": "disabled_by_user",
            }
            for key in (
                "wipe_tower_x",
                "wipe_tower_y",
                "prime_tower_width",
                "wipe_tower_rotation_angle",
            ):
                assert settings[key] == source_settings[key]
            assert read_wipe_tower_placement_warnings(out_path) == []
        finally:
            for path in (src1, src2, Path(out_path)):
                path.unlink(missing_ok=True)

    def test_impossible_merged_layout_exports_with_manual_warning(
        self, tmp_path: Path,
    ) -> None:
        source = _make_source_3mf(
            width_mm=179.0,
            depth_mm=179.0,
            printer_id="bambu-a1-mini",
            # Construct the source without requiring its own automatic fit.
            enable_wipe_tower_auto_placement=False,
        )
        item = MergedItem(
            source_filename="full-bed.png",
            source_3mf_path=source,
            slots=(MaterialSlot(0, "Black", "#101010", "GFL00"),),
            tx_mm=0.5,
            ty_mm=0.5,
        )
        out_path = tmp_path / "no-fit-merged.3mf"

        try:
            MergedBambu3MFWriter().write(
                [item], out_path, plate_width_mm=180.0, plate_depth_mm=180.0,
            )
            assert out_path.exists()
            assert read_wipe_tower_placement_warnings(out_path) == ["wipe_tower_manual_adjustment_required"]
            with zipfile.ZipFile(out_path) as package:
                placement = json.loads(package.read("Metadata/lumina_wipe_tower_placement.json"))
            assert placement["requires_manual_adjustment"] is True
            assert placement["placement_applied"] is False
            assert placement["adapted"] is False
        finally:
            source.unlink(missing_ok=True)
            Path(out_path).unlink(missing_ok=True)

    def test_project_process_and_filament_presets_are_preserved(self) -> None:
        """Merged 3MF keeps source project process/device/filament presets."""
        os.makedirs(TEMP_DIR, exist_ok=True)
        scene = trimesh.Scene()
        box = trimesh.creation.box(extents=[10.0, 8.0, 2.0])
        box.apply_translation([5.0, 4.0, 1.0])
        box.metadata["bambu_material_name"] = "Bambu PETG Basic"
        scene.add_geometry(box, geom_name="Bambu PETG Basic")

        fd, src_path = tempfile.mkstemp(
            suffix=".3mf",
            dir=TEMP_DIR,
            prefix="integ_preset_src_",
        )
        os.close(fd)
        export_scene_with_bambu_metadata(
            scene=scene,
            output_path=src_path,
            slot_names=["Bambu PETG Basic"],
            preview_colors={"Bambu PETG Basic": (16, 16, 16, 255)},
            settings={},
            color_mode="4-Color",
            printer_id="bambu-p1s",
            slicer="OrcaSlicer",
            nozzle_size="0.2",
            device_profile_id="OrcaSlicer:bbl:bambu-lab-p1s:0.2",
            build_plate_id="engineering-plate",
            enable_base_layer_height_modifier=False,
        )

        items = [
            MergedItem(
                source_filename="preset-a.png",
                source_3mf_path=Path(src_path),
                slots=(MaterialSlot(0, "Bambu PETG Basic", "#101010", "GFL00"),),
                tx_mm=10.0,
                ty_mm=20.0,
            ),
            MergedItem(
                source_filename="preset-b.png",
                source_3mf_path=Path(src_path),
                slots=(MaterialSlot(0, "Bambu PETG Basic", "#101010", "GFL00"),),
                tx_mm=40.0,
                ty_mm=20.0,
            ),
        ]

        fd, out_path = tempfile.mkstemp(
            suffix=".3mf",
            dir=TEMP_DIR,
            prefix="integ_preset_merged_",
        )
        os.close(fd)

        try:
            writer = MergedBambu3MFWriter()
            writer.write(
                items,
                Path(out_path),
                plate_width_mm=200.0,
                plate_depth_mm=200.0,
                enable_wipe_tower_auto_placement=False,
            )

            with (
                zipfile.ZipFile(src_path, "r") as src_zip,
                zipfile.ZipFile(out_path, "r") as out_zip,
            ):
                src_project = json.loads(
                    src_zip.read("Metadata/project_settings.config").decode("utf-8")
                )
                merged_project = json.loads(
                    out_zip.read("Metadata/project_settings.config").decode("utf-8")
                )
                for key in (
                    "print_settings_id",
                    "printer_model",
                    "printer_settings_id",
                    "default_print_profile",
                    "nozzle_diameter",
                ):
                    assert merged_project.get(key) == src_project.get(key)
                assert merged_project["filament_settings_id"] == (
                    src_project["filament_settings_id"][:1]
                )
                assert merged_project["curr_bed_type"] == "Engineering Plate"

                merged_model_settings = ET.fromstring(
                    out_zip.read("Metadata/model_settings.config")
                )
                merged_plate = merged_model_settings.find("plate")
                assert merged_plate is not None
                assert {
                    metadata.get("key"): metadata.get("value")
                    for metadata in merged_plate.findall("metadata")
                }["bed_type"] == "Engineering Plate"
        finally:
            for p in (Path(src_path), Path(out_path)):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass

    def test_layer_config_ranges_use_model_indices_after_merge(self) -> None:
        """Merged 3MF layer-height modifiers target Bambu model indexes."""
        src1 = _make_source_3mf(
            offset_x=0.0,
            enable_base_layer_height_modifier=True,
            backing_infill_density_percent=20,
            base_height_mm=10.0,
            color_height_mm=0.4,
        )
        src2 = _make_source_3mf(
            offset_x=15.0,
            enable_base_layer_height_modifier=True,
            backing_infill_density_percent=20,
            base_height_mm=10.0,
            color_height_mm=0.4,
        )

        items = [
            MergedItem(
                source_filename="a.png",
                source_3mf_path=src1,
                slots=(MaterialSlot(0, "Black", "#101010", "GFL00"),),
                tx_mm=0.0,
                ty_mm=0.0,
            ),
            MergedItem(
                source_filename="b.png",
                source_3mf_path=src2,
                slots=(MaterialSlot(0, "Black", "#101010", "GFL00"),),
                tx_mm=50.0,
                ty_mm=20.0,
            ),
        ]

        fd, out_path = tempfile.mkstemp(
            suffix=".3mf",
            dir=TEMP_DIR,
            prefix="integ_layer_config_",
        )
        os.close(fd)

        try:
            writer = MergedBambu3MFWriter()
            writer.write(
                items,
                Path(out_path),
                plate_width_mm=200.0,
                plate_depth_mm=200.0,
                enable_wipe_tower_auto_placement=False,
            )

            with zipfile.ZipFile(out_path, "r") as zf:
                assert "Metadata/layer_config_ranges.xml" in zf.namelist()

                main_root = ET.fromstring(zf.read("3D/3dmodel.model"))
                build = main_root.find(f"{{{_NS_CORE}}}build")
                assert build is not None
                build_ids = [
                    item.get("objectid")
                    for item in build.findall(f"{{{_NS_CORE}}}item")
                ]
                assert build_ids != ["1", "2"]

                layer_root = ET.fromstring(zf.read("Metadata/layer_config_ranges.xml"))
                layer_object_ids = [
                    obj.get("id")
                    for obj in layer_root.findall("object")
                ]
                assert layer_object_ids == ["1", "2"]
                assert layer_object_ids != build_ids
                for layer_object in layer_root.findall("object"):
                    ranges = layer_object.findall("range")
                    assert len(ranges) == 3
                    for item, expected in zip(ranges, [(0.0, 0.4), (0.4, 3.4), (3.4, 10.4)]):
                        assert (
                            float(item.get("min_z", "nan")),
                            float(item.get("max_z", "nan")),
                        ) == pytest.approx(expected)
                    density_options = [
                        next(
                            (
                                option.text
                                for option in item.findall("option")
                                if option.get("opt_key")
                                == "sparse_infill_density"
                            ),
                            None,
                        )
                        for item in ranges
                    ]
                    assert density_options == ["100%", "100%", None]

                merged_project = json.loads(
                    zf.read("Metadata/project_settings.config").decode("utf-8")
                )
                assert merged_project["sparse_infill_density"] == "20%"

                cut_root = ET.fromstring(zf.read("Metadata/cut_information.xml"))
                cut_object_ids = [
                    obj.get("id")
                    for obj in cut_root.findall("object")
                ]
                assert cut_object_ids == ["1", "2"]
                assert cut_object_ids != build_ids

                rels = ET.fromstring(zf.read("3D/_rels/3dmodel.model.rels"))
                relationships = rels.findall(
                    "{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"
                )
                assert {
                    rel.get("Target") for rel in relationships
                    if rel.get("Type") == "http://schemas.bambulab.com/package/2021/settings"
                } == {
                    "/Metadata/model_settings.config", "/Metadata/project_settings.config",
                    "/Metadata/slice_info.config", "/Metadata/lumina_wipe_tower_placement.json",
                    "/Metadata/filament_sequence.json", "/Metadata/cut_information.xml",
                    "/Metadata/layer_config_ranges.xml",
                }
                assert all((rel.get("Target") or "").lstrip("/") in zf.namelist()
                           for rel in relationships)

        finally:
            for p in (src1, src2, Path(out_path)):
                try:
                    p.unlink(missing_ok=True)
                except OSError:
                    pass
