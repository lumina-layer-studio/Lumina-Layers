"""A failed native write must preserve the last complete file and remove partial data."""

from pathlib import Path

import neroued_3mf as n3mf
import pytest
import trimesh

from utils.bambu_3mf_writer import export_scene_with_bambu_metadata
from utils.merged_bambu_3mf_writer import MaterialSlot, MergedBambu3MFWriter, MergedItem, MergedWriteError


@pytest.mark.parametrize("export_kind", ["single", "merged"])
def test_interrupted_native_export_leaves_no_partial_file(tmp_path, monkeypatch, export_kind):
    scene = trimesh.Scene()
    mesh = trimesh.creation.box()
    mesh.metadata["bambu_material_name"] = "Black"
    scene.add_geometry(mesh, geom_name="Black")

    def write_single(path: Path):
        export_scene_with_bambu_metadata(
            scene=scene, output_path=str(path), slot_names=["Black"],
            preview_colors={"Black": (0, 0, 0, 255)}, settings={},
            enable_wipe_tower_auto_placement=False,
        )

    source = tmp_path / "source.3mf"
    write_single(source)
    target = tmp_path / "保存目录 with spaces" / "result.3mf"
    target.parent.mkdir()
    complete_bytes = source.read_bytes()
    target.write_bytes(complete_bytes)

    def interrupted_write(path, document, options):
        Path(path).write_bytes(b"incomplete ZIP data")
        raise n3mf.IOError("Failed to write to 3MF file")

    monkeypatch.setattr(n3mf, "write_to_file", interrupted_write)
    with pytest.raises((OSError, MergedWriteError)):
        if export_kind == "single":
            write_single(target)
        else:
            MergedBambu3MFWriter().write(
                [MergedItem("source.png", source, (MaterialSlot(0, "Black", "#000000", "PLA"),), 0, 0)],
                target, plate_width_mm=256, plate_depth_mm=256,
                enable_wipe_tower_auto_placement=False,
            )
    assert target.read_bytes() == complete_bytes
    assert list(target.parent.iterdir()) == [target]
