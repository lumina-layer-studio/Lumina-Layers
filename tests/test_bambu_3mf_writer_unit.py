"""Unit tests for slicer-specific 3MF metadata generation."""

import json
from io import BytesIO
from pathlib import Path
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from types import SimpleNamespace

import numpy as np
import pytest
import trimesh
from PIL import Image
from scipy.optimize import linprog
from scipy.spatial import ConvexHull

from core.layered_meshing import build_labeled_surface_mesh
from core.errors import NativeMaterialSelectionError
from core.mesh_export_parts import (
    MeshExportPartRange,
    get_mesh_export_part_ranges,
    set_mesh_export_part_ranges,
)
from utils import bambu_3mf_writer as writer_module
from utils.bambu_3mf_writer import BambuStudio3MFWriter, load_export_project_settings
from fatcat_material_assertions import assert_native_materials


def _compose_project(writer: BambuStudio3MFWriter) -> dict:
    palette, _ = writer._build_material_palette()
    request = writer._build_fatcat_project_request(
        palette, writer._select_metadata_target(),
    )
    if request.get("project_source") == "fatcat_native":
        result = writer_module.compose_builtin_project_settings(request)
    else:
        result = writer_module.compose_project_settings(
            writer._get_base_config_template(), request,
        )
    return json.loads(result["project_settings_json"])


def _compose_model(writer, object_ids=None, assembly_id=None, material_indices=None):
    palette, indices = writer._build_material_palette()
    target = writer._select_metadata_target()
    request = writer._build_fatcat_project_request(palette, target)
    if request.get("project_source") == "fatcat_native":
        result = writer_module.compose_builtin_project_settings(request)
    else:
        result = writer_module.compose_project_settings(
            writer._get_base_config_template(), request,
        )
    defaults = result["metadata_defaults"]
    object_ids = list(range(1, len(writer.objects) + 1)) if object_ids is None else object_ids
    request = writer_module.build_model_metadata_request(
        target=target, assembly_id=len(object_ids) + 1 if assembly_id is None else assembly_id,
        object_ids=object_ids, entries=writer.objects,
        material_index_by_object=(
            [indices[entry.material_name] for entry in writer.objects]
            if material_indices is None else material_indices
        ),
        output_path=writer.output_path, bed_type=defaults["plate_value"],
    )
    request["active_material_count"] = len(palette)
    request["identify_id"] = defaults["identify_id"]
    request["component_inputs"] = {}
    request["resource_roles"] = list(writer_module.metadata_resource_specs(writer.slicer))
    if defaults.get("slice_uuid_seed_prefix"):
        request["slice_uuid"] = "0123456789abcdef0123456789abcdef"
    metadata = writer_module.compose_model_metadata(result["project_settings_json"], request)
    for part in metadata["parts"]:
        if part["role"] in {"model_settings", "slice_info"}:
            metadata[f"{part['role']}_xml"] = part["content"]
    return metadata


@pytest.mark.parametrize("material_index", [0, 3])
@pytest.mark.parametrize("slicer,printer_id", [
    ("BambuStudio", "bambu-h2d"),
    ("OrcaSlicer", "bambu-h2d"),
    ("SnapmakerOrca", "snapmaker-u1"),
])
def test_single_volume_object_uses_resolved_material_extruder(
    tmp_path: Path, material_index: int, slicer: str, printer_id: str,
) -> None:
    """A single part must keep its filament after slicer volume promotion."""

    names = ["Blue", "Red", "Yellow", "White"]
    colors = [(47, 49, 129), (182, 61, 68), (248, 224, 65), (255, 254, 252)]
    output = tmp_path / "single-volume.3mf"
    writer = BambuStudio3MFWriter(
        str(output), printer_id=printer_id, slicer=slicer,
        enable_base_layer_height_modifier=False,
        enable_wipe_tower_auto_placement=False,
    )
    writer._set_project_palette(names, {i: color for i, color in enumerate(colors)})
    mesh = trimesh.creation.box(extents=(10, 10, 2))
    mesh.metadata["bambu_material_name"] = names[material_index]
    writer.add_mesh(mesh, "Backing", colors[material_index])
    writer.export()

    with zipfile.ZipFile(output) as archive:
        settings = ET.fromstring(archive.read("Metadata/model_settings.config"))
    obj = settings.find("object")
    assert obj is not None
    assert len(obj.findall("part")) == 1
    assert _metadata_values(obj)["extruder"] == str(material_index + 1)
    assert _metadata_values(obj.find("part"))["extruder"] == str(material_index + 1)


def _convex_hulls_have_positive_interior_overlap(
    first_vertices: np.ndarray,
    second_vertices: np.ndarray,
) -> bool:
    """Return whether two convex hulls share a positive-radius interior ball."""

    hulls = (ConvexHull(first_vertices), ConvexHull(second_vertices))
    halfspaces = np.vstack([hull.equations[:, :3] for hull in hulls])
    offsets = np.concatenate([hull.equations[:, 3] for hull in hulls])
    normal_lengths = np.linalg.norm(halfspaces, axis=1)
    result = linprog(
        np.asarray([0.0, 0.0, 0.0, -1.0]),
        A_ub=np.column_stack((halfspaces, normal_lengths)),
        b_ub=-offsets,
        bounds=[(None, None), (None, None), (None, None), (0.0, None)],
        method="highs",
    )
    return bool(result.success and result.x[3] > 1e-9)


def test_mesh_queue_uses_read_only_float32_uint32_zero_copy_arrays() -> None:
    mesh = trimesh.creation.box(extents=(2.0, 3.0, 0.2))
    entry = writer_module._MeshExportEntry(
        mesh=mesh,
        object_name="White",
        material_name="White",
        color_rgb=(255, 255, 255),
    )
    retained: list[tuple[np.ndarray, np.ndarray]] = []

    class ZeroCopyBuilder:
        def __init__(self) -> None:
            self.received = None

        def add_mesh_object_zero_copy(
            self,
            name,
            vertices,
            faces,
            material_group_id,
            material_index,
        ):
            self.received = (
                name,
                vertices,
                faces,
                material_group_id,
                material_index,
            )
            return 17

        def add_mesh_object(self, *_args, **_kwargs):
            raise AssertionError("owning add_mesh_object path was used")

    builder = ZeroCopyBuilder()
    object_id = writer_module._queue_n3mf_mesh_object(
        builder=builder,
        entry=entry,
        material_group_id=3,
        material_index=2,
        retained_views=retained,
    )

    assert object_id == 17
    assert builder.received is not None
    _name, vertices, faces, _pid, _pindex = builder.received
    assert vertices.dtype == np.float32
    assert faces.dtype == np.uint32
    assert vertices.flags.c_contiguous and faces.flags.c_contiguous
    assert not vertices.flags.writeable and not faces.flags.writeable
    assert retained == [(vertices, faces)]
    assert np.array_equal(vertices, np.asarray(mesh.vertices, dtype=np.float32))
    assert np.array_equal(faces, np.asarray(mesh.faces, dtype=np.uint32))


def test_mesh_queue_requires_the_supported_zero_copy_neroued_contract() -> None:
    mesh = trimesh.creation.box(extents=(1.0, 1.0, 0.08))
    entry = writer_module._MeshExportEntry(
        mesh=mesh,
        object_name="White",
        material_name="White",
        color_rgb=(255, 255, 255),
    )
    retained: list[tuple[np.ndarray, np.ndarray]] = []
    captured = {}

    class LegacyBuilder:
        def add_mesh_object(self, name, mesh_value, pid, pindex):
            captured["object"] = (name, mesh_value, pid, pindex)
            return 9

    with pytest.raises(RuntimeError, match="add_mesh_object_zero_copy"):
        writer_module._queue_n3mf_mesh_object(
            builder=LegacyBuilder(),
            entry=entry,
            material_group_id=3,
            material_index=0,
            retained_views=retained,
        )

    assert captured == {}
    assert retained == []


def test_writer_expands_touching_runs_into_same_material_mesh_leaves() -> None:
    """A slicer assembly keeps safe run topology without duplicating filaments."""

    lower = trimesh.creation.box(extents=(2.0, 2.0, 0.16))
    lower.apply_translation((0.0, 0.0, 0.08))
    upper = trimesh.creation.box(extents=(2.0, 2.0, 0.24))
    upper.apply_translation((0.0, 0.0, 0.28))
    combined = trimesh.util.concatenate((lower, upper))
    set_mesh_export_part_ranges(
        combined,
        (
            MeshExportPartRange(
                0,
                len(lower.vertices),
                0,
                len(lower.faces),
            ),
            MeshExportPartRange(
                len(lower.vertices),
                len(lower.vertices) + len(upper.vertices),
                len(lower.faces),
                len(lower.faces) + len(upper.faces),
            ),
        ),
    )

    writer = BambuStudio3MFWriter(
        "touching-runs.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
    )
    writer.add_mesh(combined, "White", (255, 255, 255))

    assert len(writer.objects) == 2
    assert [entry.object_name for entry in writer.objects] == [
        "White__part_1",
        "White__part_2",
    ]
    assert [entry.material_name for entry in writer.objects] == ["White", "White"]
    assert all(entry.mesh is combined for entry in writer.objects)
    assert all(entry.part_range is not None for entry in writer.objects)

    for entry in writer.objects:
        vertices, faces = writer_module._materialize_n3mf_mesh_view_arrays(
            entry.mesh,
            part_range=entry.part_range,
        )
        leaf = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        assert leaf.is_watertight
        assert leaf.is_winding_consistent
    palette, material_indices = writer._build_material_palette()
    assert palette == [("White", (255, 255, 255))]
    assert material_indices == {"White": 0}

    model_settings = ET.fromstring(
        _compose_model(writer, [2, 3], 4, [0, 0])["model_settings_xml"]
    )
    assert [
        _metadata_values(part)["extruder"]
        for part in model_settings.findall("./object/part")
    ] == ["1", "1"]


def test_writer_materializes_float32_without_a_full_python_mesh_audit() -> None:
    """The writer converts arrays without rescanning every triangle."""

    epsilon = 9.5367431640625e-7
    mesh = trimesh.Trimesh(
        vertices=np.asarray(
            [
                [200.0, 0.0, 0.0],
                [200.0 + epsilon, 0.0, 0.0],
                [200.0, 1.0, 0.0],
            ],
            dtype=np.float64,
        ),
        faces=np.asarray([[0, 1, 2]], dtype=np.int64),
        process=False,
    )
    set_mesh_export_part_ranges(
        mesh,
        (MeshExportPartRange(0, 3, 0, 1),),
    )
    writer = BambuStudio3MFWriter(
        "float32-degenerate-certified.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
    )

    writer.add_mesh(mesh, "White", (255, 255, 255))

    entry = writer.objects[0]
    vertices, faces = writer_module._materialize_n3mf_mesh_view_arrays(
        entry.mesh,
        part_range=entry.part_range,
    )

    assert vertices.dtype == np.float32
    assert faces.dtype == np.uint32
    triangle = vertices[faces[0]]
    assert np.all(
        np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0]) == 0.0
    )


def test_neroued_040_keeps_final_indexed_topology_during_export(tmp_path) -> None:
    n3mf = writer_module._get_n3mf()
    if not hasattr(n3mf, "TriangleWriteMode"):
        pytest.skip("neroued-3mf 0.4 is required")

    body = trimesh.creation.box(extents=(2.0, 2.0, 0.2))
    epsilon = 9.5367431640625e-7
    vertices = np.vstack(
        (
            np.asarray(body.vertices, dtype=np.float64),
            np.asarray(
                [
                    [200.0, 0.0, 0.0],
                    [200.0 + epsilon, 0.0, 0.0],
                    [200.0, 1.0, 0.0],
                ],
                dtype=np.float64,
            ),
        )
    )
    faces = np.vstack(
        (
            np.asarray(body.faces, dtype=np.int64),
            np.asarray([[len(body.vertices), len(body.vertices) + 1, len(body.vertices) + 2]]),
        )
    )
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    output_path = tmp_path / "neroued-keep-indexed-topology.3mf"
    writer = BambuStudio3MFWriter(
        str(output_path),
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
    )
    writer.add_mesh(mesh, "White", (255, 255, 255))

    writer.export()

    with zipfile.ZipFile(output_path) as package:
        _vertex_count, triangle_count = _count_object_model_geometry(package)
    assert triangle_count == len(body.faces) + 1


def test_writer_keeps_safe_conditional_components_in_one_mesh_object() -> None:
    labels = np.full((1, 1, 3), -1, dtype=np.int16)
    labels[0, 0, [0, 2]] = 4
    mesh = build_labeled_surface_mesh(
        labels,
        material_id=4,
        height_px=1,
    )

    writer = BambuStudio3MFWriter(
        "safe-conditional-components.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
    )
    writer.add_mesh(mesh, "White", (255, 255, 255))

    assert len(writer.objects) == 1
    assert writer.objects[0].part_range is None
    assert len(writer.objects[0].contact_repair_ranges) == 2
    vertices, _faces = writer_module._materialize_n3mf_mesh_view_arrays(
        writer.objects[0].mesh,
        contact_repair_ranges=writer.objects[0].contact_repair_ranges,
    )
    np.testing.assert_array_equal(
        vertices,
        np.asarray(mesh.vertices, dtype=np.float32),
    )


def test_writer_repairs_unsafe_conditional_components_in_one_mesh_object() -> None:
    labels = np.full((1, 2, 2), -1, dtype=np.int16)
    labels[0, 0, 0] = 4
    labels[0, 1, 1] = 4
    mesh = build_labeled_surface_mesh(
        labels,
        material_id=4,
        height_px=2,
    )

    writer = BambuStudio3MFWriter(
        "unsafe-conditional-components.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
    )
    writer.add_mesh(mesh, "White", (255, 255, 255))

    assert len(writer.objects) == 1
    entry = writer.objects[0]
    assert entry.mesh is mesh
    assert entry.part_range is None
    assert len(entry.contact_repair_ranges) == 2

    vertices, faces = writer_module._materialize_n3mf_mesh_view_arrays(
        entry.mesh,
        contact_repair_ranges=entry.contact_repair_ranges,
    )
    assert len(np.unique(vertices, axis=0)) == len(vertices)
    assert len(faces) == len(mesh.faces)
    assert np.max(
        np.linalg.norm(
            vertices.astype(np.float64)
            - np.asarray(mesh.vertices, dtype=np.float32).astype(np.float64),
            axis=1,
        )
    ) <= 0.0005
    ranges = get_mesh_export_part_ranges(mesh)
    first = vertices[ranges[0].vertex_start : ranges[0].vertex_stop]
    second = vertices[ranges[1].vertex_start : ranges[1].vertex_stop]
    assert not _convex_hulls_have_positive_interior_overlap(
        first.astype(np.float64),
        second.astype(np.float64),
    )


def test_writer_repairs_one_connected_shell_with_local_diagonal_contact() -> None:
    labels = np.array(
        [
            [[4, -1], [4, 4]],
            [[4, 4], [-1, -1]],
        ],
        dtype=np.int16,
    )
    mesh = build_labeled_surface_mesh(labels, material_id=4, height_px=2)
    assert mesh is not None

    writer = BambuStudio3MFWriter(
        "connected-local-contact.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
    )
    writer.add_mesh(mesh, "White", (255, 255, 255))

    assert len(writer.objects) == 1
    entry = writer.objects[0]
    assert len(entry.contact_repair_ranges) == 1
    vertices, faces = writer_module._materialize_n3mf_mesh_view_arrays(
        entry.mesh,
        contact_repair_ranges=entry.contact_repair_ranges,
    )
    repaired = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    assert repaired.is_watertight
    assert repaired.is_winding_consistent


def test_writer_preserves_a_closed_cavity_without_contact_perturbation() -> None:
    labels = np.full((3, 3, 3), 4, dtype=np.int16)
    labels[1, 1, 1] = -1
    mesh = build_labeled_surface_mesh(labels, material_id=4, height_px=3)
    assert mesh is not None

    writer = BambuStudio3MFWriter(
        "closed-cavity.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
    )
    writer.add_mesh(mesh, "White", (255, 255, 255))

    entry = writer.objects[0]
    assert len(entry.contact_repair_ranges) == 1
    vertices, faces = writer_module._materialize_n3mf_mesh_view_arrays(
        entry.mesh,
        contact_repair_ranges=entry.contact_repair_ranges,
    )
    np.testing.assert_array_equal(
        vertices,
        np.asarray(mesh.vertices, dtype=np.float32),
    )
    assert len(faces) == len(mesh.faces)


def test_writer_contact_repair_does_not_rescan_all_triangles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The writer does not duplicate local geometry checks globally."""

    labels = np.array(
        [
            [[4, -1], [4, 4]],
            [[4, 4], [-1, -1]],
        ],
        dtype=np.int16,
    )
    mesh = build_labeled_surface_mesh(labels, material_id=4, height_px=2)
    assert mesh is not None
    writer = BambuStudio3MFWriter(
        "single-scan.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
    )
    writer.add_mesh(mesh, "White", (255, 255, 255))
    entry = writer.objects[0]
    assert entry.contact_repair_ranges

    monkeypatch.setattr(
        trimesh,
        "Trimesh",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("certified part was rebuilt for a topology audit")
        ),
    )
    original_cross = np.cross
    cross_batch_sizes: list[int] = []

    def counted_cross(*args, **kwargs):
        cross_batch_sizes.append(len(args[0]))
        return original_cross(*args, **kwargs)

    monkeypatch.setattr(np, "cross", counted_cross)
    vertices, faces = writer_module._materialize_n3mf_mesh_view_arrays(
        entry.mesh,
        contact_repair_ranges=entry.contact_repair_ranges,
    )

    assert len(faces) not in cross_batch_sizes
    assert vertices.dtype == np.float32
    assert faces.dtype == np.uint32


def test_legacy_noncanonical_mesh_keeps_pre_zero_copy_writer_compatibility() -> None:
    """A valid untagged producer keeps the strict pre-0.4 writer contract."""

    legacy_mesh = trimesh.creation.box(extents=(1.0, 1.0, 0.08))
    writer = BambuStudio3MFWriter(
        "legacy-closed-mesh.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
    )

    writer.add_mesh(legacy_mesh, "White", (255, 255, 255))
    entry = writer.objects[0]
    vertices, faces = writer_module._materialize_n3mf_mesh_view_arrays(
        entry.mesh,
        part_range=entry.part_range,
    )

    assert vertices.dtype == np.float32
    assert faces.dtype == np.uint32


def test_writer_does_not_run_full_topology_audit_for_untagged_mesh() -> None:
    """Production export keeps only cheap array-domain validation."""

    open_mesh = trimesh.Trimesh(
        vertices=np.asarray(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ]
        ),
        faces=np.asarray([[0, 1, 2]]),
        process=False,
    )
    writer = BambuStudio3MFWriter(
        "legacy-open-mesh.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p2s",
        slicer="BambuStudio",
    )

    writer.add_mesh(open_mesh, "White", (255, 255, 255))
    entry = writer.objects[0]

    vertices, faces = writer_module._materialize_n3mf_mesh_view_arrays(
        entry.mesh,
        part_range=entry.part_range,
    )

    assert vertices.dtype == np.float32
    assert faces.dtype == np.uint32


def test_writer_rejects_vertices_that_overflow_float32() -> None:
    """Finite source coordinates must remain finite in the 3MF write domain."""

    mesh = SimpleNamespace(
        vertices=np.asarray(
            [
                [1.0e100, 0.0, 0.0],
                [0.0, 1.0e100, 0.0],
                [0.0, 0.0, 1.0e100],
            ],
            dtype=np.float64,
        ),
        faces=np.asarray([[0, 1, 2]], dtype=np.int64),
    )

    with np.errstate(over="ignore", invalid="ignore"):
        with pytest.raises(ValueError, match="finite after float32 conversion"):
            writer_module._materialize_n3mf_mesh_view_arrays(mesh)


def test_exported_xml_round_trips_validated_float32_vertices(tmp_path: Path) -> None:
    mesh = trimesh.creation.box(extents=(1.234567, 2.345678, 0.08))
    mesh.apply_translation((37.1234567, 91.7654321, 0.04))
    expected = np.asarray(mesh.vertices, dtype=np.float32)
    writer = BambuStudio3MFWriter(
        str(tmp_path / "float32-round-trip.3mf"),
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p1s",
        slicer="BambuStudio",
        nozzle_size="0.4",
    )
    writer.add_mesh(mesh, "White", (255, 255, 255))

    output_path = writer.export()

    with zipfile.ZipFile(output_path) as package:
        object_root = ET.fromstring(package.read("3D/Objects/object_1.model"))
    core_ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    serialized = np.asarray(
        [
            (vertex.attrib["x"], vertex.attrib["y"], vertex.attrib["z"])
            for vertex in object_root.findall(".//m:vertex", core_ns)
        ],
        dtype=np.float32,
    )

    assert np.array_equal(serialized, expected)


def _metadata_values(parent: ET.Element) -> dict[str, str]:
    return {child.attrib["key"]: child.attrib["value"] for child in parent.findall("metadata")}


def _assert_bambu_default_flush_volumes(
    project: dict, *, material_count: int, toolhead_count: int,
) -> None:
    """Check native 140 mm³ load/unload volumes and each toolhead's matrix."""
    assert project["flush_volumes_vector"] == ["140"] * (material_count * 2)
    matrices = np.asarray(project["flush_volumes_matrix"], dtype=float).reshape(
        toolhead_count, material_count, material_count,
    )
    expected = np.full((material_count, material_count), 280.0)
    np.fill_diagonal(expected, 0.0)
    for matrix in matrices:
        np.testing.assert_array_equal(matrix, expected)


def _add_rybw_meshes(writer: BambuStudio3MFWriter) -> None:
    for offset, (name, rgb) in enumerate(
        [
            ("White", (255, 255, 255)),
            ("Red", (193, 46, 31)),
            ("Yellow", (244, 238, 42)),
            ("Blue", (10, 41, 137)),
        ]
    ):
        mesh = trimesh.creation.box(extents=[1, 1, 0.08])
        mesh.apply_translation([offset * 2, 0, 0])
        writer.add_mesh(mesh, name, rgb)


def _add_8c_meshes(writer: BambuStudio3MFWriter) -> None:
    for offset, (name, rgb) in enumerate(
        [
            ("White", (255, 255, 255)),
            ("Red", (193, 46, 31)),
            ("Yellow", (244, 238, 42)),
            ("Blue", (10, 41, 137)),
            ("Black", (0, 0, 0)),
            ("Cyan", (0, 170, 220)),
            ("Magenta", (210, 40, 150)),
            ("Green", (0, 174, 66)),
        ]
    ):
        mesh = trimesh.creation.box(extents=[1, 1, 0.08])
        mesh.apply_translation([offset * 2, 0, 0])
        writer.add_mesh(mesh, name, rgb)


def test_orca_project_disables_precise_outer_wall_for_one_wall_art() -> None:
    """The written Orca project must retain the proven no-missing-path fix."""

    writer = BambuStudio3MFWriter(
        "orca-safe-wall.3mf",
        settings={},
        color_mode="8-Color",
        printer_id="bambu-h2d",
        slicer="OrcaSlicer",
    )
    _add_8c_meshes(writer)

    settings = _compose_project(writer)

    assert settings["wall_generator"] == "arachne"
    assert settings["wall_loops"] == "1"
    assert settings["precise_outer_wall"] == "0"
    assert "precise_outer_wall" in set(
        settings["different_settings_to_system"][0].split(";")
    )


def test_bambu_user_template_keeps_explicit_precise_outer_wall_value() -> None:
    writer = BambuStudio3MFWriter(
        "bambu-native-wall.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-h2d",
        slicer="BambuStudio",
    )
    _add_rybw_meshes(writer)
    template = writer._get_base_config_template()
    template["precise_outer_wall"] = "1"
    writer._custom_template = template

    settings = _compose_project(writer)

    assert settings["precise_outer_wall"] == "1"


def test_cover_relationships_preserve_root_rels_default_namespace(tmp_path) -> None:
    output = tmp_path / "output.3mf"
    writer = BambuStudio3MFWriter(
        str(output), settings={}, color_mode="4-Color",
        printer_id="bambu-p1s", slicer="BambuStudio",
    )
    writer.add_mesh(trimesh.creation.box(extents=[1, 1, 1]), "White", (255, 255, 255))
    writer.export()
    with zipfile.ZipFile(output) as archive:
        relationships = archive.read("_rels/.rels")
    assert b"<Relationships xmlns=" in relationships
    assert b"ns0:" not in relationships


def test_builtin_h2d_template_keeps_current_native_slot_shape() -> None:
    template = load_export_project_settings("bambu-h2d", slicer="BambuStudio", nozzle_size="0.4")

    assert template["filament_settings_id"] == ["Bambu PLA Basic @BBL H2D"]
    assert len(template["filament_colour"]) == 1
    assert template["printer_settings_id"] == "Bambu Lab H2D 0.4 nozzle"


def _make_anycubic_writer(tmp_path) -> BambuStudio3MFWriter:
    writer = BambuStudio3MFWriter(
        str(tmp_path / "anycubic-test.3mf"),
        settings={},
        color_mode="4-Color",
        printer_id="anycubic-kobra-s1",
        slicer="AnycubicSlicerNext",
    )

    white = trimesh.creation.box(extents=[2, 4, 6])
    white.apply_translation([1, 2, 3])
    writer.add_mesh(white, "White", (255, 0, 0))

    green = trimesh.creation.box(extents=[1, 1, 1])
    green.apply_translation([2, 2, 0.5])
    writer.add_mesh(green, "Green", (0, 255, 0))
    return writer


@pytest.mark.parametrize(
    "printer_id,slicer,device_profile_id,machine_profile_id,display_name,brand,vendor_key,source_version,"
    "hardware_identity",
    [
        (
            "anycubic-kobra-x",
            "AnycubicSlicerNext",
            "AnycubicSlicerNext:anycubic:anycubic-kobra-x:0.4",
            "AnycubicSlicerNext:anycubic:anycubic-kobra-x",
            "Anycubic Kobra X",
            "Anycubic",
            "Anycubic",
            "1.3.2604.18",
            {
                "printer_model": "Anycubic Kobra X",
                "printer_settings_id": "Anycubic Kobra X 0.4 nozzle",
                "printer_variant": "0.4",
                "nozzle_diameter": ["0.4"],
                "printable_area": ["0x0", "260x0", "260x260", "0x260"],
            },
        ),
        (
            "elegoo-cc2",
            "ElegooSlicer",
            "ElegooSlicer:elegoo:elegoo-centauri-carbon-2:0.4",
            "ElegooSlicer:elegoo:elegoo-centauri-carbon-2",
            "Elegoo Centauri Carbon 2",
            "Elegoo",
            "Elegoo",
            "01.05.00.07",
            {
                "printer_model": "Elegoo Centauri Carbon 2",
                "printer_settings_id": "Elegoo Centauri Carbon 2 0.4 nozzle",
                "printer_variant": "0.4",
                "nozzle_diameter": ["0.4"],
                "printable_area": ["0x0", "256x0", "256x256", "0x256"],
            },
        ),
        (
            "bambu-h2d",
            "BambuStudio",
            "BambuStudio:bbl:bambu-lab-h2d:0.4",
            "BambuStudio:bbl:bambu-lab-h2d",
            "Bambu Lab H2D",
            "Bambu Lab",
            "BBL",
            "02.07.00.07",
            {
                "printer_model": "Bambu Lab H2D",
                "printer_settings_id": "Bambu Lab H2D 0.4 nozzle",
                "printer_variant": "0.4",
                "nozzle_diameter": ["0.4", "0.4"],
                "printable_area": ["0x0", "350x0", "350x320", "0x320"],
            },
        ),
    ],
)
def test_registry_exports_use_active_palette_and_exact_native_hardware(
    tmp_path,
    monkeypatch,
    printer_id,
    slicer,
    device_profile_id,
    machine_profile_id,
    display_name,
    brand,
    vendor_key,
    source_version,
    hardware_identity,
) -> None:
    registry_root = tmp_path / "machine_registry"
    _write_registry_fixture(
        registry_root,
        source_profile_name=hardware_identity.get("printer_settings_id"),
        device_profile_id=device_profile_id,
        machine_profile_id=machine_profile_id,
        slicer_id=slicer,
        nozzle_size="0.4",
        source_version=source_version,
        display_name=display_name,
        brand=brand,
        vendor_key=vendor_key,
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    writer = BambuStudio3MFWriter(
        str(tmp_path / "registry-slots.3mf"),
        settings={},
        color_mode="4-Color",
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size="0.4",
        device_profile_id=device_profile_id,
    )
    writer._set_project_palette(
        ["White", "Red", "Yellow", "Blue"],
        {
            0: (255, 255, 255, 255),
            1: (193, 46, 31, 255),
            2: (244, 238, 42, 255),
            3: (10, 41, 137, 255),
        },
    )

    settings = _compose_project(writer)

    assert len(settings["filament_settings_id"]) == 4
    assert len(settings["filament_colour"]) == 4
    assert settings["filament_colour"][:4] == ["#FFFFFF", "#C12E1F", "#F4EE2A", "#0A2989"]
    assert settings["printer_model"] == hardware_identity["printer_model"]
    assert settings["nozzle_diameter"] == hardware_identity["nozzle_diameter"]


def _write_registry_fixture(
    registry_root,
    *,
    source_profile_name: str | None = None,
    revision: str = "sha256:abc",
    device_profile_id: str = "BambuStudio:bbl:bambu-lab-h2d:0.4",
    machine_profile_id: str = "BambuStudio:bbl:bambu-lab-h2d",
    slicer_id: str = "BambuStudio",
    nozzle_size: str = "0.4",
    source_version: str = "02.07.01.57",
    display_name: str = "Bambu Lab H2D",
    brand: str = "Bambu Lab",
    vendor_key: str = "BBL",
    bed_width: int = 350,
    bed_depth: int = 320,
    bed_height: int = 325,
    build_plates: list[dict[str, str]] | None = None,
    supported_build_plate_ids: list[str] | None = None,
    default_build_plate_id: str = "",
) -> None:
    registry_root.mkdir(parents=True, exist_ok=True)
    slicer_payload = {
        "slicer_id": slicer_id,
        "display_name": "Bambu Studio",
        "source_kind": "local_install",
        "source_version": source_version,
        "profile_format": "bambu_orca",
        "build_plates": build_plates or [],
        "machines": [
            {
                "machine_profile_id": machine_profile_id,
                "display_name": display_name,
                "brand": brand,
                "vendor_key": vendor_key,
                "bed_width": bed_width,
                "bed_depth": bed_depth,
                "bed_height": bed_height,
                "thumbnail": "",
                "supported_build_plate_ids": supported_build_plate_ids or [],
                "default_build_plate_id": default_build_plate_id,
                "nozzles": [
                    {
                        "device_profile_id": device_profile_id,
                        "nozzle_size": nozzle_size,
                        "source_profile_name": (
                            source_profile_name or f"{display_name} {nozzle_size} nozzle"
                        ),
                        "revision": revision,
                        "supported": True,
                    }
                ],
            }
        ],
    }
    (registry_root / "registry.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-06-09T00:00:00+08:00",
                "slicers": [slicer_payload],
            }
        ),
        encoding="utf-8",
    )


def test_selected_build_plate_updates_project_and_plate_metadata(
    tmp_path,
    monkeypatch,
) -> None:
    registry_root = tmp_path / "machine_registry"
    plate = {
        "id": "smooth-pei-plate",
        "display_name": "Smooth PEI Plate / High Temp Plate",
        "image": "plates/high-temp.png",
        "source_path": "resources/images/bed_high_templ.png",
        "source_version": "02.07.01.57",
        "revision": "sha256:plate",
    }
    _write_registry_fixture(
        registry_root,
        source_profile_name="Bambu Lab H2D 0.4 nozzle",
        build_plates=[plate],
        supported_build_plate_ids=[plate["id"]],
        default_build_plate_id=plate["id"],
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))
    writer = BambuStudio3MFWriter(
        str(tmp_path / "selected-plate.3mf"),
        settings={},
        color_mode="4-Color",
        printer_id="bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
        build_plate_id=plate["id"],
    )
    _add_rybw_meshes(writer)

    project = _compose_project(writer)
    model_root = ET.fromstring(_compose_model(writer, [1, 2, 3, 4], 5)["model_settings_xml"])
    plate_root = model_root.find("./plate")

    assert project["curr_bed_type"] == "High Temp Plate"
    assert "curr_bed_type" not in project["different_settings_to_system"][0].split(";")
    assert plate_root is not None
    assert _metadata_values(plate_root)["bed_type"] == "High Temp Plate"


def test_selected_build_plate_is_validated_for_device_profile(tmp_path, monkeypatch) -> None:
    registry_root = tmp_path / "machine_registry"
    _write_registry_fixture(
        registry_root,
        build_plates=[],
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    with pytest.raises(ValueError, match="Unsupported build plate"):
        BambuStudio3MFWriter(
            str(tmp_path / "invalid-plate.3mf"),
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            nozzle_size="0.4",
            device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
            build_plate_id="other-machine-plate",
        )


def test_flashstudio_selected_build_plate_updates_plate_sidecar(
    tmp_path,
    monkeypatch,
) -> None:
    registry_root = tmp_path / "machine_registry"
    plate = {
        "id": "smooth-high-temp-plate",
        "display_name": "Smooth High Temp Plate",
        "image": "plates/high-temp.png",
        "source_path": "resources/images/bed_high_templ.png",
        "source_version": "02.01.01.00",
        "revision": "sha256:plate",
    }
    _write_registry_fixture(
        registry_root,
        source_profile_name="Flashforge Creator 5 Pro 0.4 nozzle",
        slicer_id="FlashStudio",
        device_profile_id="FlashStudio:flashforge:flashforge-creator-5-pro:0.4",
        machine_profile_id="FlashStudio:flashforge:flashforge-creator-5-pro",
        source_version="02.01.01.00",
        display_name="Flashforge Creator 5 Pro",
        brand="Flashforge",
        vendor_key="Flashforge",
        build_plates=[plate],
        supported_build_plate_ids=[plate["id"]],
        default_build_plate_id=plate["id"],
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))
    writer = BambuStudio3MFWriter(
        str(tmp_path / "flash-selected-plate.3mf"),
        printer_id="flashforge-creator-5-pro",
        slicer="FlashStudio",
        nozzle_size="0.4",
        device_profile_id="FlashStudio:flashforge:flashforge-creator-5-pro:0.4",
        build_plate_id=plate["id"],
    )

    _add_rybw_meshes(writer)
    writer.export()
    with zipfile.ZipFile(writer.output_path) as package:
        sidecar = json.loads(package.read("Metadata/plate_1.json"))
        project = json.loads(package.read("Metadata/project_settings.config"))
        model_text = package.read("3D/3dmodel.model").decode("utf-8")
        entries = set(package.namelist())

    assert sidecar["bed_type"] == "hot_plate"
    assert project["curr_bed_type"] == "High Temp Plate"
    assert project["printer_settings_id"] == "Flashforge Creator 5 Pro 0.4 nozzle"
    assert project["print_settings_id"] == "Lumina"
    assert '<metadata name="Application">BambuStudio-02.06.00.51</metadata>' in model_text
    assert "Metadata/filament_sequence.json" not in entries
    assert "Metadata/cut_information.xml" not in entries
    assert "Metadata/custom_gcode_per_layer.xml" not in entries


def _export_two_mesh_registry_3mf(
    tmp_path,
    *,
    registry_root,
    monkeypatch,
    printer_id: str,
    slicer: str,
    device_profile_id: str,
    source_profile_name: str | None = None,
    machine_profile_id: str,
    source_version: str,
    display_name: str,
    brand: str,
    vendor_key: str,
) -> zipfile.ZipFile:
    _write_registry_fixture(
        registry_root,
        source_profile_name=source_profile_name,
        device_profile_id=device_profile_id,
        machine_profile_id=machine_profile_id,
        slicer_id=slicer,
        source_version=source_version,
        display_name=display_name,
        brand=brand,
        vendor_key=vendor_key,
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    out_path = tmp_path / f"{printer_id}-{slicer}.3mf"
    writer = BambuStudio3MFWriter(
        str(out_path),
        settings={},
        color_mode="4-Color",
        printer_id=printer_id,
        slicer=slicer,
        nozzle_size="0.4",
        device_profile_id=device_profile_id,
    )
    first = trimesh.creation.box(extents=[2, 2, 1])
    first.metadata["bambu_material_name"] = "Slot 1 (White)"
    writer.add_mesh(first, "Slot 1 (White)", (255, 255, 255))
    second = trimesh.creation.box(extents=[2, 2, 1])
    second.apply_translation([4, 0, 0])
    second.metadata["bambu_material_name"] = "Slot 2 (Black)"
    writer.add_mesh(second, "Slot 2 (Black)", (0, 0, 0))
    writer.export()
    return zipfile.ZipFile(out_path, "r")


def _count_object_model_geometry(archive: zipfile.ZipFile) -> tuple[int, int]:
    ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    vertex_count = 0
    triangle_count = 0
    object_model_names = [
        name
        for name in archive.namelist()
        if name.startswith("3D/Objects/") and name.endswith(".model")
    ]
    for name in object_model_names:
        root = ET.fromstring(archive.read(name))
        vertex_count += len(root.findall(".//m:vertex", ns))
        triangle_count += len(root.findall(".//m:triangle", ns))
    return vertex_count, triangle_count


@pytest.mark.parametrize(
    "printer_id,slicer,device_profile_id,machine_profile_id,source_version,"
    "display_name,brand,vendor_key,expected_slice_header",
    [
        (
            "anycubic-kobra-x",
            "AnycubicSlicerNext",
            "AnycubicSlicerNext:anycubic:anycubic-kobra-x:0.4",
            "AnycubicSlicerNext:anycubic:anycubic-kobra-x",
            "1.3.2605.22",
            "Anycubic Kobra X",
            "Anycubic",
            "Anycubic",
            {"X-ACNext-Client-Version": "2.0.0.6 20261030184430"},
        ),
        (
            "elegoo-cc2",
            "ElegooSlicer",
            "ElegooSlicer:elegoo:elegoo-centauri-carbon-2:0.4",
            "ElegooSlicer:elegoo:elegoo-centauri-carbon-2",
            "01.05.01.06",
            "Elegoo Centauri Carbon 2",
            "Elegoo",
            "Elegoo",
            {
                "X-BBL-Client-Version": "01.05.03.05",
                "X-BBL-Client-Name": "ElegooSlicer",
            },
        ),
        (
            "flashforge-ad5x",
            "FlashStudio",
            "FlashStudio:flashforge:flashforge-ad5x:0.4",
            "FlashStudio:flashforge:flashforge-ad5x",
            "02.01.01.00",
            "Flashforge AD5X",
            "Flashforge",
            "Flashforge",
            {"X-BBL-Client-Version": "02.06.00.51"},
        ),
    ],
)
def test_registry_ac_and_elegoo_exports_keep_native_identity_and_geometry(
    tmp_path,
    monkeypatch,
    printer_id,
    slicer,
    device_profile_id,
    machine_profile_id,
    source_version,
    display_name,
    brand,
    vendor_key,
    expected_slice_header,
) -> None:
    registry_root = tmp_path / "machine_registry"
    with _export_two_mesh_registry_3mf(
        tmp_path,
        registry_root=registry_root,
        monkeypatch=monkeypatch,
        printer_id=printer_id,
        slicer=slicer,
        device_profile_id=device_profile_id,
        source_profile_name=f"{display_name} 0.4 nozzle",
        machine_profile_id=machine_profile_id,
        source_version=source_version,
        display_name=display_name,
        brand=brand,
        vendor_key=vendor_key,
    ) as archive:
        entries = set(archive.namelist())
        project_settings = json.loads(
            archive.read("Metadata/project_settings.config").decode("utf-8")
        )
        slice_info = ET.fromstring(archive.read("Metadata/slice_info.config"))
        slice_header = {
            item.attrib["key"]: item.attrib["value"]
            for item in slice_info.findall("./header/header_item")
        }
        model_xml = archive.read("3D/3dmodel.model").decode("utf-8")
        package_text = "\n".join(
            archive.read(name).decode("utf-8", errors="ignore")
            for name in archive.namelist()
            if name.endswith((".model", ".config", ".json", ".xml"))
        )

        assert project_settings["printer_model"] == display_name
        assert project_settings["printer_settings_id"] == f"{display_name} 0.4 nozzle"
        expected_application = {
            "AnycubicSlicerNext": "BambuStudio-2.0.0.6",
            "ElegooSlicer": "ElegooSlicer-1.5.3.5",
            "FlashStudio": "BambuStudio-02.06.00.51",
        }[slicer]
        assert f'name="Application">{expected_application}</metadata>' in model_xml
        for key, expected_value in expected_slice_header.items():
            assert slice_header[key] == expected_value
        assert "A1 mini" not in package_text
        assert "Bambu Lab A1" not in package_text
        vertices, triangles = _count_object_model_geometry(archive)
        assert vertices > 0
        assert triangles > 0

        if slicer == "AnycubicSlicerNext":
            assert "Metadata/custom_gcode_per_layer.xml" in entries
            assert "Metadata/filament_sequence.json" not in entries
            assert "Metadata/cut_information.xml" not in entries
        else:
            assert "Metadata/custom_gcode_per_layer.xml" not in entries
            assert "Metadata/filament_sequence.json" not in entries
            assert "Metadata/cut_information.xml" not in entries
        if slicer == "FlashStudio":
            assert slice_header["OrcaSlicer-Version"] == "2.4.2"


def test_load_export_project_settings_uses_exact_fatcat_native_project(
    tmp_path, monkeypatch,
) -> None:
    registry_root = tmp_path / "machine_registry"
    registry_root.mkdir(parents=True, exist_ok=True)
    (registry_root / "registry.json").write_text(
        """
        {
          "schema_version": 1,
          "generated_at": "2026-06-09T00:00:00+08:00",
          "slicers": [{
            "slicer_id": "BambuStudio",
            "display_name": "Bambu Studio",
            "source_kind": "local_install",
            "source_version": "02.07.01.57",
            "profile_format": "bambu_orca",
            "machines": [{
              "machine_profile_id": "BambuStudio:bbl:bambu-lab-h2d",
              "display_name": "Bambu Lab H2D",
              "brand": "Bambu Lab",
              "vendor_key": "BBL",
              "bed_width": 350,
              "bed_depth": 320,
              "bed_height": 325,
              "thumbnail": "",
              "nozzles": [{
                "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
                "nozzle_size": "0.4",
                "source_profile_name": "Bambu Lab H2D 0.4 nozzle",
                "revision": "sha256:abc",
                "supported": true
              }]
            }]
          }]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    template = load_export_project_settings(
        "bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
    )

    assert template["printer_model"] == "Bambu Lab H2D"
    assert template["layer_height"] == "0.2"
    assert template["from"] == "project"
    assert template["name"] == "project_settings"
    assert template["version"] == "02.09.01.70"
    assert "curr_bed_type" not in template
    assert template["filament_settings_id"] == ["Bambu PLA Basic @BBL H2D"]
    _assert_bambu_default_flush_volumes(template, material_count=1, toolhead_count=2)
    assert "type" not in template
    assert "instantiation" not in template
    assert "inherits" not in template


def test_load_export_project_settings_uses_configured_registry_and_fatcat_source(
    tmp_path,
    monkeypatch,
) -> None:
    registry_root = tmp_path / "machine_registry"
    _write_registry_fixture(
        registry_root,
    )
    unrelated_cwd = tmp_path / "cwd"
    unrelated_cwd.mkdir()
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))
    monkeypatch.chdir(unrelated_cwd)

    template = load_export_project_settings(
        "bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
    )

    assert template["printer_model"] == "Bambu Lab H2D"
    assert template["layer_height"] == "0.2"
    assert template["from"] == "project"


def test_load_export_project_settings_rejects_mismatched_registry_profile(tmp_path, monkeypatch) -> None:
    registry_root = tmp_path / "machine_registry"
    _write_registry_fixture(
        registry_root,
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    with pytest.raises(ValueError, match="does not match requested slicer/nozzle"):
        load_export_project_settings(
            "bambu-h2d",
            slicer="OrcaSlicer",
            nozzle_size="0.2",
            device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
        )


def test_load_export_project_settings_rejects_registry_profile_for_other_printer(tmp_path, monkeypatch) -> None:
    registry_root = tmp_path / "machine_registry"
    _write_registry_fixture(
        registry_root,
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    with pytest.raises(ValueError, match="does not match requested printer"):
        load_export_project_settings(
            "bambu-p1s",
            slicer="BambuStudio",
            nozzle_size="0.4",
            device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
        )


def test_load_export_project_settings_normalizes_slicer_alias_for_registry_profile(tmp_path, monkeypatch) -> None:
    registry_root = tmp_path / "machine_registry"
    _write_registry_fixture(
        registry_root,
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    template = load_export_project_settings(
        "bambu-h2d",
        slicer="bambu_studio",
        nozzle_size="0.4mm",
        device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
    )

    assert template["printer_model"] == "Bambu Lab H2D"
    assert template["from"] == "project"


def test_load_export_project_settings_uses_pinned_native_source_across_registry_revisions(
    tmp_path, monkeypatch,
) -> None:
    registry_root = tmp_path / "machine_registry"
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    _write_registry_fixture(
        registry_root,
        source_profile_name="Bambu Lab H2D 0.4 nozzle",
        revision="sha256:old",
    )
    first = load_export_project_settings(
        "bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
    )

    _write_registry_fixture(
        registry_root,
        source_profile_name="Bambu Lab H2D 0.4 nozzle",
        revision="sha256:new",
    )
    second = load_export_project_settings(
        "bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
    )

    assert first["printer_model"] == "Bambu Lab H2D"
    assert second["printer_model"] == "Bambu Lab H2D"
    assert first["printer_settings_id"] == "Bambu Lab H2D 0.4 nozzle"
    assert second["printer_settings_id"] == "Bambu Lab H2D 0.4 nozzle"
    assert first["layer_height"] == second["layer_height"] == "0.2"
    assert first["from"] == "project"
    assert second["from"] == "project"


def test_load_export_project_settings_uses_exact_native_quarter_nozzle_source(
    tmp_path,
    monkeypatch,
) -> None:
    registry_root = tmp_path / "machine_registry"
    _write_registry_fixture(
        registry_root,
        source_profile_name="Anycubic Kobra X 0.25 nozzle",
        device_profile_id="AnycubicSlicerNext:anycubic:anycubic-kobra-x:0.25",
        machine_profile_id="AnycubicSlicerNext:anycubic:anycubic-kobra-x",
        slicer_id="AnycubicSlicerNext",
        nozzle_size="0.25",
        display_name="Anycubic Kobra X",
        brand="Anycubic",
        vendor_key="Anycubic",
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    template = load_export_project_settings(
        "anycubic-kobra-x",
        slicer="AnycubicSlicerNext",
        nozzle_size="0.25",
        device_profile_id="AnycubicSlicerNext:anycubic:anycubic-kobra-x:0.25",
    )

    assert template["printer_settings_id"] == "Anycubic Kobra X 0.25 nozzle"
    assert template["print_settings_id"] == "Lumina"
    assert template["default_print_profile"] == "0.10mm Standard @Anycubic Kobra X 0.25 nozzle"
    assert template["default_filament_profile"] == [
        "Anycubic PLA @Anycubic Kobra X 0.25 nozzle",
    ]
    assert template["filament_settings_id"] == [
        "Anycubic PLA @Anycubic Kobra X 0.25 nozzle",
    ]
    assert template["nozzle_diameter"] == ["0.25"]
    assert "0.2 nozzle" not in json.dumps(template)


def test_writer_uses_fatcat_application_metadata_for_slice_info(tmp_path, monkeypatch) -> None:
    registry_root = tmp_path / "machine_registry"
    _write_registry_fixture(
        registry_root,
        source_version="99.88.77.66",
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    writer = BambuStudio3MFWriter(
        str(tmp_path / "registry-application.3mf"),
        settings={},
        color_mode="4-Color",
        printer_id="bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
    )

    _add_rybw_meshes(writer)
    assert writer._get_base_config_template()["version"] == "02.09.01.70"
    metadata = _compose_model(writer)
    application = next(
        item["value"] for item in metadata["root_model"]["metadata"]
        if item["name"] == "Application"
    )
    assert application == "BambuStudio-02.09.01.70"
    config = ET.fromstring(_compose_model(writer)["slice_info_xml"])
    header = config.find("header")
    assert header is not None
    values = {
        item.attrib["key"]: item.attrib["value"]
        for item in header.findall("header_item")
    }
    assert values["X-BBL-Client-Version"] == "02.09.01.70"


def test_flash_studio_without_device_profile_uses_exact_native_metadata(tmp_path) -> None:
    writer = BambuStudio3MFWriter(
        str(tmp_path / "flash-studio-native.3mf"),
        settings={},
        color_mode="4-Color",
        printer_id="flashforge-ad5x",
        slicer="FlashStudio",
        nozzle_size="0.25",
    )

    _add_rybw_meshes(writer)
    metadata = _compose_model(writer)
    application = next(
        item["value"] for item in metadata["root_model"]["metadata"]
        if item["name"] == "Application"
    )
    assert application == "BambuStudio-02.06.00.51"
    root = ET.fromstring(_compose_model(writer)["slice_info_xml"])
    header = root.find("header")
    assert header is not None
    values = {
        item.attrib["key"]: item.attrib["value"]
        for item in header.findall("header_item")
    }
    assert values == {
        "X-BBL-Client-Type": "slicer",
        "X-BBL-Client-Version": "02.06.00.51",
        "OrcaSlicer-Version": "2.4.2",
    }
    uuid_node = header.find("uuid")
    assert uuid_node is not None
    assert re.fullmatch(r"[0-9a-f]{32}", uuid_node.attrib["value"])


def test_bundled_flash_studio_quarter_profile_exports_native_package(tmp_path) -> None:
    output_path = tmp_path / "flash-studio-creator-5-quarter.3mf"
    writer = BambuStudio3MFWriter(
        str(output_path),
        settings={},
        color_mode="4-Color",
        printer_id="flashforge-creator-5",
        slicer="FlashStudio",
        nozzle_size="0.25",
        device_profile_id=(
            "FlashStudio:flashforge:flashforge-creator-5:0.25"
        ),
    )
    _add_rybw_meshes(writer)
    writer.export()

    with zipfile.ZipFile(output_path, "r") as archive:
        entries = set(archive.namelist())
        project = json.loads(
            archive.read("Metadata/project_settings.config").decode("utf-8")
        )
        slice_root = ET.fromstring(archive.read("Metadata/slice_info.config"))
        slice_header = {
            item.attrib["key"]: item.attrib["value"]
            for item in slice_root.findall("./header/header_item")
        }
        plate = json.loads(archive.read("Metadata/plate_1.json").decode("utf-8"))
        plate_small = Image.open(BytesIO(archive.read("Metadata/plate_1_small.png")))
        model_settings = ET.fromstring(archive.read("Metadata/model_settings.config"))
        model_text = archive.read("3D/3dmodel.model").decode("utf-8")
        model_root = ET.fromstring(model_text)
        rels_root = ET.fromstring(archive.read("_rels/.rels"))

    assert project["printer_model"] == "Flashforge Creator 5"
    assert project["printer_settings_id"] == "Flashforge Creator 5 0.25 nozzle"
    assert project["nozzle_diameter"] == ["0.25"] * 4
    assert (
        project["default_print_profile"]
        == "0.12mm Standard @FF C5 0.25 nozzle"
    )
    assert project["default_filament_profile"] == ['Flashforge PLA Basic @FF C5 0.25 nozzle'] * 4
    assert project["version"] == "02.06.00.51"
    assert project["auxiliary_fan"] == "0"
    assert project["before_layer_change_gcode"] == ";BEFORE_LAYER_CHANGE\n;[layer_z]"
    assert project["layer_height"] == "0.08"
    assert project["initial_layer_print_height"] == "0.08"
    assert project["wall_generator"] == "arachne"
    assert project["sparse_infill_density"] == "100%"
    assert project["skirt_loops"] == "0"
    assert project["skirt_distance"] == "2"
    assert project["skirt_height"] == "1"
    assert project["draft_shield"] == "disabled"
    assert "filament_map_mode" not in project
    for key in (
        "filament_colour",
        "filament_multi_colour",
        "filament_settings_id",
        "filament_type",
        "filament_vendor",
    ):
        assert len(project[key]) == 4
    assert "filament_self_index" not in project
    assert project["filament_extruder_variant"] == ["Direct Drive Standard"] * 4
    assert slice_header == {
        "X-BBL-Client-Type": "slicer",
        "X-BBL-Client-Version": "02.06.00.51",
        "OrcaSlicer-Version": "2.4.2",
    }
    uuid_node = slice_root.find("./header/uuid")
    assert uuid_node is not None
    assert re.fullmatch(r"[0-9a-f]{32}", uuid_node.attrib["value"])
    assert plate["version"] == 2
    assert plate["nozzle_diameter"] == pytest.approx(0.25)
    assert all(item["layer_height"] == pytest.approx(0.08) for item in plate["bbox_objects"])
    assert len(plate["bbox_objects"]) == 1
    assert plate["bbox_objects"][0]["name"] == output_path.stem
    assert plate["first_layer_time"] == pytest.approx(0.0)
    assert not any(item["name"] == "wipe_tower" for item in plate["bbox_objects"])
    assert plate_small.size == (128, 128)
    plate_metadata = {
        item.attrib["key"]: item.attrib["value"]
        for item in model_settings.findall("./plate/metadata")
    }
    assert plate_metadata["filament_maps"] == "1 2 3 4"
    object_metadata = {
        item.attrib["key"]: item.attrib["value"]
        for item in model_settings.findall("./object/metadata")
    }
    assert object_metadata["name"] == output_path.stem
    assert '<metadata name="Application">BambuStudio-02.06.00.51</metadata>' in model_text
    model_metadata = {
        item.attrib["name"]: item.text or ""
        for item in model_root
        if item.tag.endswith("metadata")
    }
    assert model_metadata["Thumbnail_Middle"] == (
        "/Auxiliaries/.thumbnails/thumbnail_middle.png"
    )
    assert model_metadata["Thumbnail_Small"] == (
        "/Auxiliaries/.thumbnails/thumbnail_small.png"
    )
    assert model_metadata["OrcaSlicer"] == "2.4.2"
    relationships = list(rels_root)
    assert len(relationships) == 4
    assert "Metadata/plate_1.json" in entries
    assert "Metadata/plate_1_small.png" in entries
    assert {
        "Auxiliaries/.thumbnails/thumbnail_3mf.png",
        "Auxiliaries/.thumbnails/thumbnail_middle.png",
        "Auxiliaries/.thumbnails/thumbnail_small.png",
    }.issubset(entries)
    assert "Metadata/filament_sequence.json" not in entries
    assert "Metadata/cut_information.xml" not in entries
    assert "Metadata/custom_gcode_per_layer.xml" not in entries


def test_bundled_qidi_q2_profile_exports_native_package_with_lumina_process(tmp_path) -> None:
    output_path = tmp_path / "qidi-q2.3mf"
    writer = BambuStudio3MFWriter(
        str(output_path),
        settings={},
        color_mode="4-Color",
        printer_id="qidi-q2",
        slicer="QIDIStudio",
        nozzle_size="0.4",
        device_profile_id="QIDIStudio:qidi:q2:0.4",
    )
    _add_rybw_meshes(writer)
    writer.export()

    with zipfile.ZipFile(output_path, "r") as archive:
        entries = set(archive.namelist())
        project = json.loads(
            archive.read("Metadata/project_settings.config").decode("utf-8")
        )
        slice_root = ET.fromstring(archive.read("Metadata/slice_info.config"))
        model_text = archive.read("3D/3dmodel.model").decode("utf-8")
        model_settings = ET.fromstring(archive.read("Metadata/model_settings.config"))
        plate = json.loads(archive.read("Metadata/plate_1.json").decode("utf-8"))
        sequence = json.loads(
            archive.read("Metadata/filament_sequence.json").decode("utf-8")
        )
        relationships = ET.fromstring(archive.read("_rels/.rels"))
        model_relationships = ET.fromstring(
            archive.read("3D/_rels/3dmodel.model.rels")
        )

    header = {
        item.attrib["key"]: item.attrib["value"]
        for item in slice_root.findall("./header/header_item")
    }
    assert header == {
        "X-QDT-Client-Type": "slicer",
        "X-QDT-Client-Version": "02.07.02.73",
    }
    assert project["version"] == "02.07.02.73"
    assert project["printer_model"] == "Q2"
    assert project["printer_settings_id"] == "Q2 0.4 nozzle"
    assert project["printer_variant"] == "0.4"
    assert project["nozzle_diameter"] == ["0.4"]
    assert project["default_print_profile"] == "0.20mm Standard @Q2"
    assert project["layer_height"] == "0.08"
    assert project["line_width"] == "0.42"
    assert project["wall_loops"] == "1"
    assert project["sparse_infill_density"] == "100%"
    assert project["skirt_loops"] == "0"
    assert project["skirt_distance"] == "2"
    assert project["skirt_height"] == "1"
    assert project["draft_shield"] == "disabled"
    assert len(project["filament_settings_id"]) == 4
    assert '<metadata name="Application">QIDIStudio-02.07.02.73</metadata>' in model_text
    assert '<metadata name="OrcaSlicer">2.1.0.14</metadata>' in model_text
    assert '<metadata name="QIDIStudio:3mfVersion">1</metadata>' in model_text
    assert 'xmlns:QIDIStudio="http://schemas.qiditech.com/package/2021"' in model_text
    assert {
        "Metadata/plate_1.json",
        "Metadata/filament_sequence.json",
        "Metadata/cut_information.xml",
    }.issubset(entries)
    assert "Metadata/plate_1_small.png" not in entries
    assert "Metadata/custom_gcode_per_layer.xml" not in entries
    assert sequence["plate_1"] == {
        "sequence": [],
        "nozzle_sequence": [],
        "optimal_assignment": [],
    }
    assert len(plate["filament_colors"]) == 4
    assert plate["filament_ids"] == [0, 1, 2, 3]
    plate_metadata = {
        item.attrib["key"]: item.attrib["value"]
        for item in model_settings.findall("./plate/metadata")
    }
    assert plate_metadata["filament_maps"] == "1 1 1 1"
    assert plate_metadata["filament_volume_maps"] == "0 0 0 0"
    relationship_types = {item.attrib["Type"] for item in relationships}
    assert (
        "http://schemas.qiditech.com/package/2021/cover-thumbnail-middle"
        in relationship_types
    )
    assert (
        "http://schemas.qiditech.com/package/2021/cover-thumbnail-small"
        in relationship_types
    )
    assert len(list(model_relationships)) == 1


def test_flash_studio_creator_5_pro_uses_exact_native_profile_with_lumina_process(tmp_path) -> None:
    """C5 Pro exports keep current native identities and Lumina process values."""

    writer = BambuStudio3MFWriter(
        str(tmp_path / "creator-5-pro-manual-shape.3mf"),
        settings={},
        color_mode="4-Color",
        printer_id="flashforge-creator-5-pro",
        slicer="FlashStudio",
        nozzle_size="0.4",
        device_profile_id=(
            "FlashStudio:flashforge:flashforge-creator-5-pro:0.4"
        ),
    )
    _add_rybw_meshes(writer)

    project = _compose_project(writer)

    assert project["version"] == "02.06.00.51"
    assert project["printer_model"] == "Flashforge Creator 5 Pro"
    assert project["printer_settings_id"] == (
        "Flashforge Creator 5 Pro 0.4 nozzle"
    )
    assert project["nozzle_diameter"] == ["0.4"] * 4
    assert project["default_print_profile"] == (
        "0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle"
    )
    assert project["print_settings_id"] == "Lumina"
    assert project["auxiliary_fan"] == "1"
    assert project["bed_mesh_max"] == "99999,99999"
    assert project["bed_mesh_min"] == "-99999,-99999"
    assert project["before_layer_change_gcode"] == (
        ";BEFORE_LAYER_CHANGE\n;[layer_z]"
    )
    assert project["default_filament_profile"] == ['Flashforge PLA Basic @FF C5P'] * 4
    for key in (
        "filament_colour",
        "filament_multi_colour",
        "filament_settings_id",
        "filament_type",
        "filament_vendor",
        "nozzle_temperature",
    ):
        assert len(project[key]) == 4
    assert "bed_temperature" not in project

    # Native machine metadata must not replace Lumina's print process.
    assert project["layer_height"] == "0.08"
    assert project["initial_layer_print_height"] == "0.08"
    assert project["wall_loops"] == "1"
    assert project["wall_generator"] == "arachne"
    assert project["sparse_infill_density"] == "100%"
    assert project["sparse_infill_pattern"] == "rectilinear"
    assert "print_speed" not in project
    assert project["outer_wall_speed"]
    assert project["inner_wall_speed"]
    assert project["travel_speed"] == "150"


@pytest.mark.parametrize(
    (
        "printer_id",
        "nozzle_size",
        "device_profile_id",
        "printer_model",
        "printer_settings_id",
        "printer_variant",
        "nozzle_diameter",
        "default_print_profile",
    ),
    [
        (
            "flashforge-guider-3-ultra",
            "0.4",
            "FlashStudio:flashforge:flashforge-guider-3-ultra:0.4",
            "Flashforge Guider 3 Ultra",
            "Flashforge Guider 3 Ultra 0.4 Nozzle",
            "0.4",
            ["0.4", "0.4"],
            "0.20mm Standard @Flashforge G3U 0.4 Nozzle",
        ),
    ],
)
def test_bundled_flash_studio_guider_rejects_unprintable_native_material(
    tmp_path,
    printer_id,
    nozzle_size,
    device_profile_id,
    printer_model,
    printer_settings_id,
    printer_variant,
    nozzle_diameter,
    default_print_profile,
) -> None:
    output_path = tmp_path / f"flash-studio-{printer_id}-{nozzle_size}.3mf"
    writer = BambuStudio3MFWriter(
        str(output_path),
        settings={},
        color_mode="4-Color",
        printer_id=printer_id,
        slicer="FlashStudio",
        nozzle_size=nozzle_size,
        device_profile_id=device_profile_id,
    )
    _add_rybw_meshes(writer)
    from utils.fatcat_metadata import native_source_for_target

    source = native_source_for_target(writer._select_metadata_target())
    assert source["source_machine_profile_name"] == printer_settings_id
    assert source["hardware_settings"]["printer_model"] == printer_model
    assert source["hardware_settings"]["nozzle_diameter"] == nozzle_diameter
    assert source["nozzle_uid"] == f"nozzle:{printer_variant}mm"
    assert source["default_print_profile_name"] == default_print_profile

    # The native G3U PLA profiles declare no compatible plate. Hardware being
    # available must not allow writing an unprintable project or changing PLA.
    with pytest.raises(NativeMaterialSelectionError) as error:
        writer.export()
    selection = error.value.material_selection
    assert selection["machine_uid"] == "flashforge:guider-3-ultra"
    assert selection["nozzle_uid"] == "nozzle:0.4mm"
    assert selection["ready"] is False
    assert selection["build_plates"] == []
    assert selection["issues"][0]["code"] == "native_material_plate_incompatible"
    assert selection["issues"][0]["material_type"] == "PLA"
    assert not output_path.exists()


def test_writer_base_template_uses_native_device_profile(tmp_path, monkeypatch) -> None:
    registry_root = tmp_path / "machine_registry"
    registry_root.mkdir(parents=True, exist_ok=True)
    (registry_root / "registry.json").write_text(
        """
        {
          "schema_version": 1,
          "generated_at": "2026-06-09T00:00:00+08:00",
          "slicers": [{
            "slicer_id": "BambuStudio",
            "display_name": "Bambu Studio",
            "source_kind": "local_install",
            "source_version": "02.07.01.57",
            "profile_format": "bambu_orca",
            "machines": [{
              "machine_profile_id": "BambuStudio:bbl:bambu-lab-h2d",
              "display_name": "Bambu Lab H2D",
              "brand": "Bambu Lab",
              "vendor_key": "BBL",
              "bed_width": 350,
              "bed_depth": 320,
              "bed_height": 325,
              "thumbnail": "",
              "nozzles": [{
                "device_profile_id": "BambuStudio:bbl:bambu-lab-h2d:0.4",
                "nozzle_size": "0.4",
                "source_profile_name": "Bambu Lab H2D 0.4 nozzle",
                "revision": "sha256:abc",
                "supported": true
              }]
            }]
          }]
        }
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    writer = BambuStudio3MFWriter(
        "registry-device-profile.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-h2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
    )

    _add_rybw_meshes(writer)
    settings = writer._get_base_config_template()
    assert settings["printer_model"] == "Bambu Lab H2D"
    assert settings["printer_settings_id"] == "Bambu Lab H2D 0.4 nozzle"


def test_anycubic_registry_keeps_full_client_version_stamp(tmp_path, monkeypatch) -> None:
    registry_root = tmp_path / "machine_registry"
    _write_registry_fixture(
        registry_root,
        device_profile_id="AnycubicSlicerNext:anycubic:anycubic-kobra-s1:0.4",
        machine_profile_id="AnycubicSlicerNext:anycubic:anycubic-kobra-s1",
        slicer_id="AnycubicSlicerNext",
        source_version="1.3.9.4",
        display_name="Anycubic Kobra S1",
        brand="Anycubic",
        vendor_key="Anycubic",
        bed_width=250,
        bed_depth=250,
        bed_height=250,
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    writer = BambuStudio3MFWriter(
        str(tmp_path / "anycubic-registry.3mf"),
        settings={},
        color_mode="4-Color",
        printer_id="anycubic-kobra-s1",
        slicer="AnycubicSlicerNext",
        nozzle_size="0.4",
        device_profile_id="AnycubicSlicerNext:anycubic:anycubic-kobra-s1:0.4",
    )

    _add_rybw_meshes(writer)
    config = ET.fromstring(_compose_model(writer)["slice_info_xml"])
    header = config.find("header")
    assert header is not None
    values = {
        item.attrib["key"]: item.attrib["value"]
        for item in header.findall("header_item")
    }
    assert values["X-ACNext-Client-Version"] == "2.0.0.6 20261030184430"


def test_anycubic_registry_separates_profile_and_client_versions(tmp_path, monkeypatch) -> None:
    registry_root = tmp_path / "machine_registry"
    _write_registry_fixture(
        registry_root,
        device_profile_id="AnycubicSlicerNext:anycubic:anycubic-kobra-x:0.4",
        machine_profile_id="AnycubicSlicerNext:anycubic:anycubic-kobra-x",
        slicer_id="AnycubicSlicerNext",
        source_version="1.3.2605.22",
        display_name="Anycubic Kobra X",
        brand="Anycubic",
        vendor_key="Anycubic",
        bed_width=260,
        bed_depth=260,
        bed_height=260,
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    writer = BambuStudio3MFWriter(
        str(tmp_path / "anycubic-client-version.3mf"),
        settings={},
        color_mode="4-Color",
        printer_id="anycubic-kobra-x",
        slicer="AnycubicSlicerNext",
        nozzle_size="0.4",
        device_profile_id="AnycubicSlicerNext:anycubic:anycubic-kobra-x:0.4",
    )

    _add_rybw_meshes(writer)
    metadata = _compose_model(writer)
    application = next(
        item["value"] for item in metadata["root_model"]["metadata"]
        if item["name"] == "Application"
    )
    assert application == "BambuStudio-2.0.0.6"
    assert writer._registry_device_profile.source_version == "1.3.2605.22"
    # Fat Cat pins this profile source independently of the locally installed
    # Anycubic package. The saved project keeps the pinned source version.
    assert writer._get_base_config_template()["version"] == "2.0.0.6"
    config = ET.fromstring(_compose_model(writer)["slice_info_xml"])
    header = config.find("header")
    assert header is not None
    values = {
        item.attrib["key"]: item.attrib["value"]
        for item in header.findall("header_item")
    }
    assert values["X-ACNext-Client-Version"] == "2.0.0.6 20261030184430"


def test_load_export_project_settings_rejects_registry_only_printer_id(tmp_path, monkeypatch) -> None:
    registry_root = tmp_path / "machine_registry"
    _write_registry_fixture(
        registry_root,
        device_profile_id="OrcaSlicer:snapmaker:snapmaker-artisan:0.4",
        machine_profile_id="OrcaSlicer:snapmaker:snapmaker-artisan",
        slicer_id="OrcaSlicer",
        source_version="02.04.00.00",
        display_name="Snapmaker Artisan",
        brand="Snapmaker",
        vendor_key="Snapmaker",
        bed_width=400,
        bed_depth=400,
        bed_height=400,
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    with pytest.raises(ValueError, match="no unique native source for requested machine/nozzle"):
        load_export_project_settings(
            printer_id="snapmaker-artisan",
            slicer="OrcaSlicer",
            nozzle_size="0.4",
            device_profile_id="OrcaSlicer:snapmaker:snapmaker-artisan:0.4",
        )


def test_bambu_registry_x2d_uses_exact_native_project(tmp_path, monkeypatch) -> None:
    registry_root = tmp_path / "machine_registry"
    _write_registry_fixture(
        registry_root,
        source_profile_name="Bambu Lab X2D 0.4 nozzle",
        device_profile_id="BambuStudio:bbl:bambu-lab-x2d:0.4",
        machine_profile_id="BambuStudio:bbl:bambu-lab-x2d",
        nozzle_size="0.4",
        source_version="02.07.00.07",
        display_name="Bambu Lab X2D",
        brand="Bambu Lab",
        bed_width=256,
        bed_depth=256,
        bed_height=261,
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    template = load_export_project_settings(
        printer_id="bambu-lab-x2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id="BambuStudio:bbl:bambu-lab-x2d:0.4",
    )

    assert template["from"] == "project"
    assert template["name"] == "project_settings"
    assert template["version"] == "02.09.01.70"
    assert template["printer_model"] == "Bambu Lab X2D"
    assert template["printer_settings_id"] == "Bambu Lab X2D 0.4 nozzle"
    assert template["nozzle_diameter"] == ["0.4", "0.4"]
    assert template["printable_area"] == ["0x0", "256x0", "256x256", "0x256 "]
    assert template["default_filament_profile"] == ["Bambu PLA Basic @BBL X2D 0.4 nozzle"]
    assert template["default_print_profile"] == "0.20mm Standard @BBL X2D"
    assert "X2D start gcode" in template["machine_start_gcode"]
    assert "X2D end gcode" in template["machine_end_gcode"]
    assert template["printer_structure"] == "corexy"
    assert template["layer_height"] == "0.2"
    assert template["prime_tower_width"] == "35"
    assert template["prime_tower_brim_width"] == "-1"
    assert template["different_settings_to_system"] == [
        "enable_prime_tower;filament_colour;filament_multi_colour"
    ]
    assert template["filament_settings_id"] == [
        "Bambu PLA Basic @BBL X2D 0.4 nozzle"
    ]
    _assert_bambu_default_flush_volumes(template, material_count=1, toolhead_count=2)
    assert "type" not in template
    assert "instantiation" not in template
    assert "inherits" not in template


def test_bambu_a2_registry_uses_exact_native_project(tmp_path, monkeypatch) -> None:
    registry_root = tmp_path / "machine_registry"
    _write_registry_fixture(
        registry_root,
        source_profile_name="Bambu Lab A2L 0.4 nozzle",
        device_profile_id="BambuStudio:bbl:bambu-lab-a2l:0.4",
        machine_profile_id="BambuStudio:bbl:bambu-lab-a2l",
        nozzle_size="0.4",
        source_version="02.07.00.07",
        display_name="Bambu Lab A2L",
        brand="Bambu Lab",
        bed_width=330,
        bed_depth=320,
        bed_height=325,
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    template = load_export_project_settings(
        printer_id="bambu-lab-a2l",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id="BambuStudio:bbl:bambu-lab-a2l:0.4",
    )

    assert template["from"] == "project"
    assert template["name"] == "project_settings"
    assert template["version"] == "02.09.01.70"
    assert template["printer_model"] == "Bambu Lab A2L"
    assert template["printer_settings_id"] == "Bambu Lab A2L 0.4 nozzle"
    assert template["default_filament_profile"] == ["Bambu PLA Basic @BBL A2L 0.4 nozzle"]
    assert template["default_print_profile"] == "0.20mm Standard @BBL A2L"
    assert "A2L start gcode" in template["machine_start_gcode"]
    assert "A2L end gcode" in template["machine_end_gcode"]
    assert template["printer_structure"] == "i3"
    assert template["default_wipe_tower_pos"] == "0.0x1.0"
    assert template["prime_tower_width"] == "35"
    assert template["prime_tower_brim_width"] == "-1"
    assert "curr_bed_type" not in template
    assert template["filament_settings_id"] == [
        "Bambu PLA Basic @BBL A2L 0.4 nozzle"
    ]
    assert template["different_settings_to_system"] == [
        "enable_prime_tower;filament_colour;filament_multi_colour"
    ]
    _assert_bambu_default_flush_volumes(template, material_count=1, toolhead_count=1)
    assert template["layer_height"] == "0.2"
    assert "type" not in template
    assert "instantiation" not in template
    assert "inherits" not in template


def test_bambu_registry_project_settings_can_trim_native_template_filament_slots(
    tmp_path, monkeypatch
) -> None:
    registry_root = tmp_path / "machine_registry"
    _write_registry_fixture(
        registry_root,
        source_profile_name="Bambu Lab X2D 0.4 nozzle",
        device_profile_id="BambuStudio:bbl:bambu-lab-x2d:0.4",
        machine_profile_id="BambuStudio:bbl:bambu-lab-x2d",
        nozzle_size="0.4",
        source_version="02.07.00.07",
        display_name="Bambu Lab X2D",
        brand="Bambu Lab",
        bed_width=256,
        bed_depth=256,
        bed_height=261,
    )
    monkeypatch.setenv("LUMINA_MACHINE_REGISTRY_DIR", str(registry_root))

    writer = BambuStudio3MFWriter(
        "x2d-slots.3mf",
        settings={},
        color_mode="4-Color",
        printer_id="bambu-lab-x2d",
        slicer="BambuStudio",
        nozzle_size="0.4",
        device_profile_id="BambuStudio:bbl:bambu-lab-x2d:0.4",
        preserve_template_filament_slots=False,
    )
    writer._set_project_palette(
        [
            "PLA slot 1",
            "PLA slot 2",
            "PLA slot 3",
            "PLA slot 4",
        ],
        {
            0: (255, 255, 249, 255),
            1: (253, 203, 166, 255),
            2: (205, 60, 70, 255),
            3: (169, 168, 166, 255),
        },
    )
    writer._material_types.update({f"PLA slot {index}": "PLA" for index in range(1, 5)})

    settings = _compose_project(writer)
    writer.add_mesh(
        trimesh.creation.box(extents=[1, 1, 1]), "PLA slot 1", (255, 255, 255)
    )

    assert settings["filament_settings_id"] == [
        "Bambu PLA Basic @BBL X2D 0.4 nozzle",
        "Bambu PLA Basic @BBL X2D 0.4 nozzle",
        "Bambu PLA Basic @BBL X2D 0.4 nozzle",
        "Bambu PLA Basic @BBL X2D 0.4 nozzle",
    ]
    assert settings["filament_colour"] == ["#FFFFF9", "#FDCBA6", "#CD3C46", "#A9A8A6"]
    assert settings["filament_multi_colour"] == ["#FFFFF9", "#FDCBA6", "#CD3C46", "#A9A8A6"]
    assert settings["filament_type"] == ["PLA", "PLA", "PLA", "PLA"]
    source = writer._get_base_config_template()
    for key in (
        "filament_is_mixed",
        "activate_air_filtration",
        "additional_fan_full_speed_layer",
        "pressure_advance",
    ):
        if key in source:
            assert len(settings[key]) == 4
        else:
            assert key not in settings
    _assert_bambu_default_flush_volumes(settings, material_count=4, toolhead_count=2)
    assert len(settings["different_settings_to_system"]) == 1
    assert settings["version"] == "02.09.01.70"
    assert settings["prime_tower_width"] == "35"


def test_bambu_h2c_extends_beyond_native_slots_without_group_vector_bloat() -> None:
    writer = BambuStudio3MFWriter(
        "h2c-extended-materials.3mf",
        settings={},
        color_mode="8-Color",
        printer_id="bambu-h2c",
        slicer="BambuStudio",
        nozzle_size="0.2",
        device_profile_id="BambuStudio:bbl:bambu-lab-h2c:0.2",
        preserve_template_filament_slots=False,
    )
    writer._set_project_palette(
        [f"PLA slot {index}" for index in range(10)],
        {index: (index * 20, index * 10, index * 5, 255) for index in range(10)},
    )
    writer._material_types.update({f"PLA slot {index}": "PLA" for index in range(10)})

    settings = _compose_project(writer)

    assert len(settings["filament_colour"]) == 10
    assert len(settings["filament_type"]) == 10
    # Bambu 02.09.01.70 exposes two nozzle variants and eight drying-time values.
    assert len(settings["filament_extruder_variant"]) == 20
    assert len(settings["filament_dev_ams_drying_time"]) == 80
    _assert_bambu_default_flush_volumes(settings, material_count=10, toolhead_count=2)


class TestAnycubicWriterMetadata:
    def test_project_process_targets_selected_orca_printer(self) -> None:
        writer = BambuStudio3MFWriter(
            "orca-a1-mini.3mf",
            settings={},
            color_mode="4-Color",
            printer_id="bambu-a1-mini",
            slicer="OrcaSlicer",
        )
        writer.add_mesh(
            trimesh.creation.box(extents=[1, 1, 1]),
            "White",
            (255, 255, 255),
        )

        settings = _compose_project(writer)

        assert settings["print_compatible_printers"] == [
            settings["printer_settings_id"]
        ]

    def test_writer_base_template_uses_selected_nozzle_size_variant(self) -> None:
        writer = BambuStudio3MFWriter(
            "selected-nozzle.3mf",
            settings={},
            color_mode="4-Color",
            printer_id="bambu-p1s",
            slicer="BambuStudio",
            nozzle_size="0.2",
        )
        writer.add_mesh(
            trimesh.creation.box(extents=[1, 1, 1]),
            "White",
            (255, 255, 255),
        )

        settings = writer._get_base_config_template()
        assert settings["nozzle_diameter"] == ["0.2"]
        assert settings["printer_settings_id"] == "Bambu Lab P1S 0.2 nozzle"

    def test_project_settings_allow_line_width_overrides(self) -> None:
        writer = BambuStudio3MFWriter(
            "line-width-overrides.3mf",
            settings={
                "line_width": "0.22",
                "initial_layer_line_width": "0.22",
            },
            color_mode="4-Color",
            printer_id="bambu-p1s",
            slicer="BambuStudio",
            nozzle_size="0.2",
        )
        writer.add_mesh(trimesh.creation.box(extents=[1, 1, 1]), "White", (255, 255, 255))

        settings = _compose_project(writer)
        assert settings["line_width"] == "0.22"
        assert settings["initial_layer_line_width"] == "0.22"

    def test_project_settings_preserves_difference_index_slot_shape(self, monkeypatch) -> None:
        writer = BambuStudio3MFWriter(
            "difference-index.3mf",
            settings={
                "line_width": "0.22",
                "wall_loops": "3",
            },
            color_mode="4-Color",
            printer_id="bambu-p1s",
            slicer="BambuStudio",
            nozzle_size="0.2",
            preserve_template_filament_slots=True,
        )
        writer.add_mesh(trimesh.creation.box(extents=[1, 1, 1]), "White", (255, 255, 255))
        slot_count = 4
        from fatcat_native_source_fixtures import complete_native_project

        template = complete_native_project(writer, ["PLA"] * slot_count)
        template["different_settings_to_system"] = [
            "line_width",
            "wall_loops;top_shell_layers",
            "bottom_shell_layers",
        ] + [""] * (slot_count - 2) + ["printer_settings_id"]
        writer._custom_template = template

        settings = _compose_project(writer)

        different_settings = settings["different_settings_to_system"]
        assert isinstance(different_settings, list)
        assert len(different_settings) == len(settings["filament_settings_id"]) + 2
        difference_index = different_settings[0].split(";")
        assert difference_index == sorted(set(difference_index))
        assert {
            "line_width",
            "wall_loops",
        } <= set(difference_index)
        assert {"wall_loops", "top_shell_layers"} <= set(
            different_settings[1].split(";")
        )
        assert different_settings[2] == "bottom_shell_layers"
        assert different_settings[3:-1] == [""] * (
            len(settings["filament_settings_id"]) - 2
        )
        assert "printer_settings_id" in different_settings[-1].split(";")

    def test_shared_material_palette_deduplicates_project_filaments(self) -> None:
        writer = BambuStudio3MFWriter(
            "shared-materials.3mf",
            settings={},
            color_mode="8-Color",
            printer_id="bambu-h2d",
            slicer="BambuStudio",
        )

        first = trimesh.creation.box(extents=[1, 1, 1])
        first.metadata["bambu_material_name"] = "Slot 1 (White)"
        writer.add_mesh(first, "A1__Slot 1 (White)", (255, 255, 255))

        second = trimesh.creation.box(extents=[1, 1, 1])
        second.apply_translation([2, 0, 0])
        second.metadata["bambu_material_name"] = "Slot 1 (White)"
        writer.add_mesh(second, "A2__Slot 1 (White)", (255, 255, 255))

        third = trimesh.creation.box(extents=[1, 1, 1])
        third.apply_translation([4, 0, 0])
        third.metadata["bambu_material_name"] = "Slot 2 (Black)"
        writer.add_mesh(third, "A1__Slot 2 (Black)", (0, 0, 0))

        settings = _compose_project(writer)
        assert settings["filament_colour"] == ["#FFFFFF", "#000000"]

        root = ET.fromstring(_compose_model(writer, [1, 2, 3], 4, [0, 0, 1])["model_settings_xml"])
        part_extruders = [
            _metadata_values(part)["extruder"]
            for part in root.findall("./object/part")
        ]
        assert part_extruders == ["1", "1", "2"]

    def test_bambu_project_settings_resolve_petg_material_identity(self) -> None:
        writer = BambuStudio3MFWriter(
            "petg-materials.3mf",
            settings={},
            color_mode="4-Color",
            printer_id="bambu-p1s",
            slicer="BambuStudio",
            nozzle_size="0.2",
        )
        writer._set_project_palette(
            ["爱丽兹 PETG Basic 青色", "PLA Basic White"],
            {
                0: (0, 122, 214, 255),
                1: (255, 255, 255, 255),
            },
        )

        settings = _compose_project(writer)

        assert settings["filament_type"] == ["PETG", "PLA"]
        assert settings["filament_settings_id"] == [
            "Bambu PETG Basic @BBL X1C 0.2 nozzle",
            "Bambu PLA Basic @BBL X1C 0.2 nozzle",
        ]
        assert_native_materials(
            settings, slicer_id="BambuStudio", machine_uid="bambu-lab:p1s",
            nozzle_uid="nozzle:0.2mm", material_types=["PETG", "PLA"],
        )


    def test_anycubic_model_settings_match_sample_shape(self, tmp_path) -> None:
        writer = _make_anycubic_writer(tmp_path)

        root = ET.fromstring(_compose_model(writer, [1, 2], 3)["model_settings_xml"])
        first_part = root.find("./object/part")
        assert first_part is not None

        part_meta = _metadata_values(first_part)
        assert part_meta["source_file"] == "anycubic-test.3mf"
        assert part_meta["source_object_id"] == "0"
        assert part_meta["source_volume_id"] == "0"
        assert part_meta["source_offset_x"] == "1"
        assert part_meta["source_offset_y"] == "2"
        assert part_meta["source_offset_z"] == "3"
        assert part_meta["extruder"] == "1"
        assert part_meta["matrix"] == "1 0 0 2 0 1 0 4 0 0 1 6 0 0 0 1"

        plate = root.find("./plate")
        assert plate is not None
        plate_meta = _metadata_values(plate)
        assert "filament_map_mode" not in plate_meta
        assert plate_meta["thumbnail_file"] == "Metadata/plate_1.png"
        assert plate_meta["thumbnail_no_light_file"] == "Metadata/plate_no_light_1.png"
        assert plate_meta["top_file"] == "Metadata/top_1.png"
        assert plate_meta["pick_file"] == "Metadata/pick_1.png"

        model_instance = plate.find("./model_instance")
        assert model_instance is not None
        instance_meta = _metadata_values(model_instance)
        assert instance_meta["identify_id"] == "1"

    def test_anycubic_project_settings_preserve_template_filament_metadata(self, tmp_path) -> None:
        writer = _make_anycubic_writer(tmp_path)
        settings = _compose_project(writer)
        template = load_export_project_settings("anycubic-kobra-s1", slicer="AnycubicSlicerNext")

        expected_vendor = template["filament_vendor"][0]
        expected_settings_id = template["filament_settings_id"][0]

        assert settings["filament_vendor"] == [expected_vendor, expected_vendor]
        assert template["filament_ids"] == ["GFPLA"]
        assert settings["filament_ids"] == ["GFPLA", "GFPLA"]
        assert settings["filament_settings_id"] == [expected_settings_id, expected_settings_id]
        assert settings["filament_colour"] == ["#FF0000", "#00FF00"]
        assert all(value != "Bambu Lab" for value in settings["filament_vendor"])

    def test_export_scene_uses_global_slot_number_for_sparse_slots(self, monkeypatch) -> None:
        captured_colors: list[tuple[str, tuple[int, int, int]]] = []

        class _FakeWriter:
            def __init__(
                self,
                output_path: str,
                settings=None,
                color_mode: str = "4-Color",
                printer_id: str = "bambu-h2d",
                slicer: str = "BambuStudio",
                nozzle_size: str | None = None,
                watermark: str = "LuminaStudio",
                **kwargs,
            ) -> None:
                self.output_path = output_path

            def add_mesh(self, mesh, name: str, color_rgb: tuple[int, int, int]) -> None:
                captured_colors.append((name, color_rgb))

            def export(self) -> str:
                return self.output_path

        monkeypatch.setattr(writer_module, "BambuStudio3MFWriter", _FakeWriter)

        scene = trimesh.Scene()
        scene.add_geometry(trimesh.creation.box(extents=[1, 1, 1]), geom_name="Slot 1 (White)")
        shifted = trimesh.creation.box(extents=[1, 1, 1])
        shifted.apply_translation([2, 0, 0])
        scene.add_geometry(shifted, geom_name="Slot 3 (Green)")

        out_path = writer_module.export_scene_with_bambu_metadata(
            scene=scene,
            output_path="sparse-slots.3mf",
            slot_names=["Slot 1 (White)", "Slot 3 (Green)"],
            preview_colors={
                0: (255, 255, 255, 255),
                1: (0, 0, 0, 255),
                2: (0, 174, 66, 255),
            },
            settings={},
            color_mode="8-Color",
            printer_id="bambu-h2d",
            slicer="BambuStudio",
        )

        assert out_path == "sparse-slots.3mf"
        assert captured_colors == [
            ("Slot 1 (White)", (255, 255, 255)),
            ("Slot 3 (Green)", (0, 174, 66)),
        ]

    def test_export_scene_uses_full_palette_order_for_sparse_native_plain_names(self, monkeypatch) -> None:
        captured_colors: list[tuple[str, tuple[int, int, int]]] = []
        captured_object_names: list[str] = []
        captured_settings: dict[str, object] = {}
        captured_color_mode: dict[str, str] = {}
        captured_source_colours: dict[str, str] = {}

        class _CapturingWriter(writer_module.BambuStudio3MFWriter):
            def __init__(
                self,
                output_path: str,
                settings=None,
                color_mode: str = "4-Color",
                printer_id: str = "bambu-h2d",
                slicer: str = "BambuStudio",
                nozzle_size: str | None = None,
                watermark: str = "LuminaStudio",
                **kwargs,
            ) -> None:
                captured_color_mode["value"] = color_mode
                super().__init__(
                    output_path,
                    settings,
                    color_mode,
                    printer_id,
                    slicer,
                    nozzle_size,
                    watermark,
                    **kwargs,
                )

            def add_mesh(self, mesh, name: str, color_rgb: tuple[int, int, int]) -> None:
                captured_colors.append((name, color_rgb))
                super().add_mesh(mesh, name, color_rgb)

            def export(self) -> str:
                captured_object_names.extend(entry.object_name for entry in self.objects)
                palette, _ = self._build_material_palette()
                request = self._build_fatcat_project_request(
                    palette, self._select_metadata_target(),
                )
                captured_source_colours.update(request["source_slot_colours"])
                captured_settings.update(_compose_project(self))
                return self.output_path

        monkeypatch.setattr(writer_module, "BambuStudio3MFWriter", _CapturingWriter)

        scene = trimesh.Scene()
        for offset, name in enumerate(("yellow", "red", "white", "bambugreen")):
            mesh = trimesh.creation.box(extents=[1, 1, 1])
            mesh.apply_translation([offset * 2, 0, 0])
            scene.add_geometry(mesh, geom_name=name)

        full_palette = [
            "bambugreen",
            "black",
            "blue",
            "cyan",
            "magenta",
            "red",
            "white",
            "yellow",
        ]
        preview_colors = {
            0: (0, 174, 66, 255),
            1: (0, 0, 0, 255),
            2: (10, 41, 137, 255),
            3: (0, 255, 255, 255),
            4: (255, 0, 255, 255),
            5: (220, 20, 60, 255),
            6: (255, 255, 255, 255),
            7: (255, 230, 0, 255),
        }
        preview_colors.update({
            name: preview_colors[index]
            for index, name in enumerate(full_palette)
        })

        out_path = writer_module.export_scene_with_bambu_metadata(
            scene=scene,
            output_path="native-sparse.3mf",
            slot_names=["yellow", "red", "white", "bambugreen"],
            preview_colors=preview_colors,
            settings={},
            color_mode="8-Color",
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            project_slot_names=full_palette,
        )

        assert out_path == "native-sparse.3mf"
        assert captured_color_mode["value"] == "8-Color"
        assert captured_object_names == ["yellow", "red", "white", "bambugreen"]
        assert captured_colors == [
            ("yellow", (255, 230, 0)),
            ("red", (220, 20, 60)),
            ("white", (255, 255, 255)),
            ("bambugreen", (0, 174, 66)),
        ]
        assert captured_settings["filament_colour"] == [
            "#00AE42",
            "#000000",
            "#0A2989",
            "#00FFFF",
            "#FF00FF",
            "#DC143C",
            "#FFFFFF",
            "#FFE600",
        ]
        assert captured_settings["filament_ids"] == ["GFA00"] * 8
        assert captured_source_colours == {
            str(index): colour
            for index, colour in enumerate(captured_settings["filament_colour"])
        }

    def test_export_scene_forwards_registry_device_profile_id(self, monkeypatch) -> None:
        captured: dict[str, object] = {}

        class _FakeWriter:
            def __init__(
                self,
                output_path: str,
                settings=None,
                color_mode: str = "4-Color",
                printer_id: str = "bambu-h2d",
                slicer: str = "BambuStudio",
                nozzle_size: str | None = None,
                watermark: str = "LuminaStudio",
                *,
                device_profile_id: str | None = None,
                **kwargs,
            ) -> None:
                self.output_path = output_path
                captured["device_profile_id"] = device_profile_id

            def add_mesh(self, mesh, name: str, color_rgb: tuple[int, int, int]) -> None:
                return None

            def export(self) -> str:
                return self.output_path

        monkeypatch.setattr(writer_module, "BambuStudio3MFWriter", _FakeWriter)

        scene = trimesh.Scene()
        scene.add_geometry(trimesh.creation.box(extents=[1, 1, 1]), geom_name="Slot 1 (White)")

        out_path = writer_module.export_scene_with_bambu_metadata(
            scene=scene,
            output_path="registry-export.3mf",
            slot_names=["Slot 1 (White)"],
            preview_colors={0: (255, 255, 255, 255)},
            settings={},
            color_mode="4-Color",
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            nozzle_size="0.4",
            device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.4",
        )

        assert out_path == "registry-export.3mf"
        assert captured["device_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d:0.4"

    def test_anycubic_slice_info_and_custom_parts_use_acnext_layout(self, tmp_path) -> None:
        writer = _make_anycubic_writer(tmp_path)
        writer.export()
        with zipfile.ZipFile(writer.output_path) as package:
            slice_info = ET.fromstring(package.read("Metadata/slice_info.config"))
            part_paths = set(package.namelist())
            custom_xml = ET.fromstring(package.read("Metadata/custom_gcode_per_layer.xml"))
        header = slice_info.find("./header")
        assert header is not None
        header_items = {item.attrib["key"]: item.attrib["value"] for item in header.findall("header_item")}
        assert header_items == {
            "X-ACNext-Client-Type": "slicer",
            "X-ACNext-Client-Version": "2.0.0.6 20261030184430",
        }
        assert "Metadata/custom_gcode_per_layer.xml" in part_paths
        assert "Metadata/filament_sequence.json" not in part_paths
        assert "Metadata/cut_information.xml" not in part_paths
        plate = custom_xml.find("./plate")
        assert plate is not None
        plate_info = plate.find("./plate_info")
        mode = plate.find("./mode")
        assert plate_info is not None and plate_info.attrib["id"] == "1"
        assert mode is not None and mode.attrib["value"] == "MultiExtruder"

    def test_anycubic_export_package_contains_expected_files(self, tmp_path) -> None:
        writer = _make_anycubic_writer(tmp_path)
        out_path = writer.export()

        with zipfile.ZipFile(out_path) as package:
            names = set(package.namelist())
            assert "Metadata/plate_1.png" in names
            assert "Metadata/plate_no_light_1.png" in names
            assert "Metadata/top_1.png" in names
            assert "Metadata/pick_1.png" in names
            assert "Metadata/custom_gcode_per_layer.xml" in names
            assert "Metadata/filament_sequence.json" not in names
            assert "Metadata/cut_information.xml" not in names

            model_root = ET.fromstring(package.read("3D/3dmodel.model"))
            core_ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
            model_metadata = {
                node.attrib["name"]: (node.text or "") for node in model_root.findall("m:metadata", core_ns)
            }
            assert model_metadata["Application"] == "BambuStudio-2.0.0.6"
            assert model_metadata["BambuStudio:3mfVersion"] == "1"

            slice_root = ET.fromstring(package.read("Metadata/slice_info.config"))
            header = slice_root.find("./header")
            assert header is not None
            header_items = {item.attrib["key"]: item.attrib["value"] for item in header.findall("header_item")}
            assert header_items["X-ACNext-Client-Type"] == "slicer"
            assert header_items["X-ACNext-Client-Version"] == "2.0.0.6 20261030184430"

    def test_orca_registry_u1_uses_orca_native_filament_metadata(self, tmp_path) -> None:
        writer = writer_module.BambuStudio3MFWriter(
            output_path=str(tmp_path / "snapmaker-u1-orca-registry.3mf"),
            settings={},
            color_mode="4-Color",
            printer_id="snapmaker-u1",
            slicer="OrcaSlicer",
            nozzle_size="0.4",
            device_profile_id="OrcaSlicer:snapmaker:snapmaker-u1:0.4",
        )
        _add_rybw_meshes(writer)

        out_path = writer.export()

        with zipfile.ZipFile(out_path) as package:
            model_root = ET.fromstring(package.read("3D/3dmodel.model"))
            core_ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
            model_metadata = {
                node.attrib["name"]: (node.text or "")
                for node in model_root.findall("m:metadata", core_ns)
            }
            build_item = model_root.find("m:build/m:item", core_ns)
            project_settings = json.loads(
                package.read("Metadata/project_settings.config").decode("utf-8")
            )
            slice_root = ET.fromstring(package.read("Metadata/slice_info.config"))
            slice_header = slice_root.find("./header")
            assert slice_header is not None
            slice_header_items = {
                item.attrib["key"]: item.attrib["value"]
                for item in slice_header.findall("header_item")
            }
            root_rels = package.read("_rels/.rels")

        serialized = json.dumps(project_settings, ensure_ascii=False)
        assert model_metadata["Application"] == "BambuStudio-02.06.00.51"
        assert model_metadata["BambuStudio:3mfVersion"] == "1"
        assert model_metadata["OrcaSlicer"] == "2.4.2"
        assert slice_header_items["X-BBL-Client-Type"] == "slicer"
        assert slice_header_items["X-BBL-Client-Version"] == "02.06.00.51"
        assert slice_header_items["OrcaSlicer-Version"] == "2.4.2"
        assert root_rels.startswith(b"<?xml version=")
        assert b"<Relationships xmlns=" in root_rels
        assert b"ns0:" not in root_rels
        assert build_item is not None
        assert build_item.attrib["printable"] == "1"
        assert build_item.attrib["auto_drop"] == "1"
        assert len(build_item.attrib["transform"].split()) == 12
        assert "Snapmaker PLA Basic @U1" in serialized
        assert project_settings["printer_settings_id"] == "Snapmaker U1 (0.4 nozzle)"
        assert project_settings["filament_settings_id"] == ["Snapmaker PLA Basic @U1"] * 4
        assert project_settings["default_print_profile"] == "0.08 Extra Fine @Snapmaker U1 (0.4 nozzle)"
        assert project_settings["default_filament_profile"] == ["Snapmaker PLA Basic @U1"] * 4
        assert project_settings["print_settings_id"] == "Lumina"
        assert project_settings["inherits_group"] == [""] * 6
        assert project_settings["version"] == "2.2.4"
        assert project_settings["textured_plate_temp"] == ["65"] * 4
        assert project_settings["nozzle_temperature"] == ["220"] * 4
        assert project_settings["different_settings_to_system"][0].startswith(
            "bottom_shell_layers;"
        )

    def test_orca_registry_u1_preserves_native_metadata_for_8c_exports(
        self, tmp_path
    ) -> None:
        writer = writer_module.BambuStudio3MFWriter(
            output_path=str(tmp_path / "snapmaker-u1-orca-registry-8c.3mf"),
            settings={},
            color_mode="8-Color",
            printer_id="snapmaker-u1",
            slicer="OrcaSlicer",
            nozzle_size="0.4",
            device_profile_id="OrcaSlicer:snapmaker:snapmaker-u1:0.4",
        )
        _add_8c_meshes(writer)

        out_path = writer.export()

        with zipfile.ZipFile(out_path) as package:
            model_root = ET.fromstring(package.read("3D/3dmodel.model"))
            core_ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
            model_metadata = {
                node.attrib["name"]: (node.text or "")
                for node in model_root.findall("m:metadata", core_ns)
            }
            build_item = model_root.find("m:build/m:item", core_ns)
            project_settings = json.loads(
                package.read("Metadata/project_settings.config").decode("utf-8")
            )
            slice_root = ET.fromstring(package.read("Metadata/slice_info.config"))
            slice_header = slice_root.find("./header")
            assert slice_header is not None
            slice_header_items = {
                item.attrib["key"]: item.attrib["value"]
                for item in slice_header.findall("header_item")
            }

        assert model_metadata["OrcaSlicer"] == "2.4.2"
        assert slice_header_items["OrcaSlicer-Version"] == "2.4.2"
        assert build_item is not None
        assert build_item.attrib["printable"] == "1"
        assert build_item.attrib["auto_drop"] == "1"
        assert project_settings["filament_settings_id"] == ["Snapmaker PLA Basic @U1"] * 8
        assert project_settings["print_settings_id"] == "Lumina"
        assert project_settings["inherits_group"] == [""] * 10
        assert project_settings["default_filament_profile"] == ["Snapmaker PLA Basic @U1"] * 8
        assert project_settings["version"] == "2.2.4"
        assert project_settings["textured_plate_temp"] == ["65"] * 8
        assert project_settings["nozzle_temperature"] == ["220"] * 8
        assert len(project_settings["different_settings_to_system"]) == 10
        assert "prime_tower_width" in project_settings["different_settings_to_system"][0]

    def test_snapmaker_orca_registry_u1_uses_snapmaker_orca_filament_metadata(
        self, tmp_path
    ) -> None:
        writer = writer_module.BambuStudio3MFWriter(
            output_path=str(tmp_path / "snapmaker-u1-snaporca-registry.3mf"),
            settings={},
            color_mode="4-Color",
            printer_id="snapmaker-u1",
            slicer="SnapmakerOrca",
            nozzle_size="0.4",
            device_profile_id="SnapmakerOrca:snapmaker:snapmaker-u1:0.4",
        )
        _add_rybw_meshes(writer)

        out_path = writer.export()

        with zipfile.ZipFile(out_path) as package:
            model_root = ET.fromstring(package.read("3D/3dmodel.model"))
            core_ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
            model_metadata = {
                node.attrib["name"]: (node.text or "")
                for node in model_root.findall("m:metadata", core_ns)
            }
            project_settings = json.loads(
                package.read("Metadata/project_settings.config").decode("utf-8")
            )
            slice_root = ET.fromstring(package.read("Metadata/slice_info.config"))
            slice_header = slice_root.find("./header")
            assert slice_header is not None
            slice_header_items = {
                item.attrib["key"]: item.attrib["value"]
                for item in slice_header.findall("header_item")
            }

        assert model_metadata["Application"] == "Snapmaker_Orca-2.4.1"
        assert slice_header_items["X-BBL-Client-Type"] == "slicer"
        assert slice_header_items["X-BBL-Client-Version"] == ""
        assert project_settings["printer_settings_id"] == "Snapmaker U1 (0.4 nozzle)"
        assert project_settings["filament_settings_id"] == ["Snapmaker PLA Basic @U1"] * 4
        assert project_settings["default_print_profile"] == (
            "0.20mm Standard @Snapmaker U1 (0.4 nozzle)"
        )
        assert project_settings["default_filament_profile"] == ["Snapmaker PLA Basic @U1"] * 4
        assert project_settings["textured_plate_temp"] == ["65"] * 4
        assert project_settings["nozzle_temperature"] == ["220"] * 4
        assert "inherits_group" not in project_settings
        assert "filament_colour;filament_multi_colour" in project_settings[
            "different_settings_to_system"
        ][1]

    def test_snapmaker_orca_u1_without_device_profile_uses_exact_native_metadata(
        self, tmp_path
    ) -> None:
        writer = writer_module.BambuStudio3MFWriter(
            output_path=str(tmp_path / "snapmaker-u1-snaporca-native.3mf"),
            settings={},
            color_mode="4-Color",
            printer_id="snapmaker-u1",
            slicer="SnapmakerOrca",
            nozzle_size="0.4",
        )
        _add_rybw_meshes(writer)

        out_path = writer.export()

        with zipfile.ZipFile(out_path) as package:
            model_root = ET.fromstring(package.read("3D/3dmodel.model"))
            core_ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
            model_metadata = {
                node.attrib["name"]: (node.text or "")
                for node in model_root.findall("m:metadata", core_ns)
            }
            project_settings = json.loads(
                package.read("Metadata/project_settings.config").decode("utf-8")
            )
            slice_root = ET.fromstring(package.read("Metadata/slice_info.config"))
            slice_header = slice_root.find("./header")
            assert slice_header is not None
            slice_header_items = {
                item.attrib["key"]: item.attrib["value"]
                for item in slice_header.findall("header_item")
            }

        assert model_metadata["Application"] == "Snapmaker_Orca-2.4.1"
        assert slice_header_items["X-BBL-Client-Type"] == "slicer"
        assert slice_header_items["X-BBL-Client-Version"] == ""
        assert project_settings["printer_settings_id"] == "Snapmaker U1 (0.4 nozzle)"
        assert project_settings["filament_settings_id"] == ["Snapmaker PLA Basic @U1"] * 4
        assert project_settings["textured_plate_temp"] == ["65"] * 4
        assert project_settings["nozzle_temperature"] == ["220"] * 4

    @pytest.mark.parametrize(
        ("slicer", "nozzle_size", "device_profile_id"),
        [
            (
                "OrcaSlicer",
                "0.6",
                "OrcaSlicer:snapmaker:snapmaker-u1:0.6",
            ),
            (
                "SnapmakerOrca",
                "0.2",
                "SnapmakerOrca:snapmaker:snapmaker-u1:0.2",
            ),
            (
                "SnapmakerOrca",
                "0.6",
                "SnapmakerOrca:snapmaker:snapmaker-u1:0.6",
            ),
            (
                "SnapmakerOrca",
                "0.8",
                "SnapmakerOrca:snapmaker:snapmaker-u1:0.8",
            ),
        ],
    )
    def test_registry_u1_non_default_nozzles_use_exact_native_material_sources(
        self,
        slicer: str,
        nozzle_size: str,
        device_profile_id: str,
    ) -> None:
        if slicer == "OrcaSlicer":
            # This exact nozzle source has compatible materials, but no PLA.
            with pytest.raises(
                NativeMaterialSelectionError,
                match="no available native filament profile",
            ) as error:
                load_export_project_settings("snapmaker-u1", slicer=slicer,
                    nozzle_size=nozzle_size, device_profile_id=device_profile_id)
            selection = error.value.material_selection
            assert selection["ready"] is False
            assert selection["machine_uid"] == "snapmaker:u1"
            assert selection["nozzle_uid"] == "nozzle:0.6mm"
            assert selection["issues"][0]["code"] == "native_material_unavailable"
            assert selection["materials"][0]["material_type"] == "PLA"
            assert selection["materials"][0]["profiles"] == []
            return
        project = load_export_project_settings("snapmaker-u1", slicer=slicer,
            nozzle_size=nozzle_size, device_profile_id=device_profile_id)
        assert project["version"] == "2.4.1"
        assert project["printer_settings_id"] == f"Snapmaker U1 ({nozzle_size} nozzle)"
        assert project["nozzle_diameter"] == [nozzle_size] * 4
        assert project["filament_settings_id"] == [f"Generic PLA @U1 {nozzle_size} nozzle"]
        assert project["filament_type"] == ["PLA"]
        assert project["textured_plate_temp"] == ["65"]
        assert project["nozzle_temperature"] == ["220"]

    def test_bambu_export_centers_and_drops_build_item_on_selected_bed(self, tmp_path) -> None:
        writer = writer_module.BambuStudio3MFWriter(
            output_path=str(tmp_path / "bambu-p1s-centered.3mf"),
            settings={},
            color_mode="4-Color",
            printer_id="bambu-p1s",
            slicer="BambuStudio",
            nozzle_size="0.4",
        )
        writer.add_mesh(
            trimesh.creation.box(extents=[2, 2, 0.4]),
            "White",
            (255, 255, 255),
        )

        out_path = writer.export()

        with zipfile.ZipFile(out_path) as package:
            model_root = ET.fromstring(package.read("3D/3dmodel.model"))

        core_ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
        build_item = model_root.find("m:build/m:item", core_ns)
        assert build_item is not None
        assert [float(value) for value in build_item.attrib["transform"].split()] == pytest.approx(
            [1, 0, 0, 0, 1, 0, 0, 0, 1, 128, 128, 0.2]
        )

    def test_bambu_export_centers_negative_local_vertices_with_build_transform(
        self,
        tmp_path,
    ) -> None:
        """Bed placement must not be baked into serialized mesh vertices."""

        writer = writer_module.BambuStudio3MFWriter(
            output_path=str(tmp_path / "bambu-p1s-local-coordinates.3mf"),
            settings={},
            color_mode="4-Color",
            printer_id="bambu-p1s",
            slicer="BambuStudio",
            nozzle_size="0.4",
        )
        mesh = trimesh.creation.box(extents=[2, 4, 0.4])
        mesh.apply_translation([-11, -22, 0])
        writer.add_mesh(mesh, "White", (255, 255, 255))

        out_path = writer.export()

        with zipfile.ZipFile(out_path) as package:
            model_root = ET.fromstring(package.read("3D/3dmodel.model"))
            object_root = ET.fromstring(
                package.read("3D/Objects/object_1.model")
            )

        core_ns = {
            "m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
        }
        build_item = model_root.find("m:build/m:item", core_ns)
        vertices = object_root.findall(".//m:vertex", core_ns)

        assert build_item is not None
        assert [float(value) for value in build_item.attrib["transform"].split()] == pytest.approx(
            [1, 0, 0, 0, 1, 0, 0, 0, 1, 139, 150, 0.2]
        )
        assert min(float(vertex.attrib["x"]) for vertex in vertices) == pytest.approx(
            -12.0
        )
        assert max(float(vertex.attrib["x"]) for vertex in vertices) == pytest.approx(
            -10.0
        )
        assert min(float(vertex.attrib["y"]) for vertex in vertices) == pytest.approx(
            -24.0
        )
        assert max(float(vertex.attrib["y"]) for vertex in vertices) == pytest.approx(
            -20.0
        )

    def test_h2d_0_2_bambu_version_uses_fatcat_target_stamp(self, tmp_path) -> None:
        writer = writer_module.BambuStudio3MFWriter(
            output_path=str(tmp_path / "h2d-0_2.3mf"),
            settings={},
            color_mode="4-Color",
            printer_id="bambu-h2d",
            slicer="BambuStudio",
            nozzle_size="0.2",
        )

        _add_rybw_meshes(writer)
        metadata = _compose_model(writer)
        application = next(
            item["value"] for item in metadata["root_model"]["metadata"]
            if item["name"] == "Application"
        )
        assert application == "BambuStudio-02.09.01.70"

        slice_info = ET.fromstring(_compose_model(writer)["slice_info_xml"])
        header = slice_info.find("./header")
        assert header is not None
        header_items = {item.attrib["key"]: item.attrib["value"] for item in header.findall("header_item")}
        assert header_items["X-BBL-Client-Version"] == "02.09.01.70"

    def test_non_h2_0_2_bambu_version_uses_same_fatcat_target_stamp(self, tmp_path) -> None:
        writer = writer_module.BambuStudio3MFWriter(
            output_path=str(tmp_path / "p1s-0_2.3mf"),
            settings={},
            color_mode="4-Color",
            printer_id="bambu-p1s",
            slicer="BambuStudio",
            nozzle_size="0.2",
        )

        _add_rybw_meshes(writer)
        metadata = _compose_model(writer)
        application = next(
            item["value"] for item in metadata["root_model"]["metadata"]
            if item["name"] == "Application"
        )
        assert application == "BambuStudio-02.09.01.70"

        slice_info = ET.fromstring(_compose_model(writer)["slice_info_xml"])
        header = slice_info.find("./header")
        assert header is not None
        header_items = {item.attrib["key"]: item.attrib["value"] for item in header.findall("header_item")}
        assert header_items["X-BBL-Client-Version"] == "02.09.01.70"
