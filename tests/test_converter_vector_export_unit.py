"""Unit tests for the vector branch export in converter.py.

Validates that:
    1. The vector branch calls export_scene_with_bambu_metadata (not scene.export).
    2. The slot_names passed to the exporter match the final scene geometry keys.
"""

import json
import os
import sys
import types
import zipfile
from unittest.mock import patch, MagicMock

# Add project root to path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import pytest
import trimesh
import numpy as np
from utils.bambu_3mf_writer import export_scene_with_bambu_metadata, BambuStudio3MFWriter


def _build_fake_processor(scene):
    """Return a MagicMock that behaves like VectorProcessor."""
    vp = MagicMock()
    vp.svg_to_mesh.return_value = scene
    vp.img_processor.lut_rgb = np.zeros((256, 3))
    vp.img_processor._load_svg.return_value = np.zeros((100, 100, 4), dtype=np.uint8)
    vp.color_mode = "4-Color"

    fake_analysis = MagicMock()
    fake_analysis.preview_colors = {0: [255, 255, 255, 255], 1: [255, 0, 0, 255],
                                    2: [255, 255, 0, 255], 3: [0, 0, 255, 255]}
    fake_analysis.slot_names = ["White", "Red", "Yellow", "Blue"]
    fake_analysis.stage_timings = {}
    fake_analysis.num_layers = 4
    vp.analyze_svg.return_value = fake_analysis
    vp.build_mesh.return_value = scene
    vp.render_preview = MagicMock(return_value=np.zeros((100, 100, 4), dtype=np.uint8))
    return vp


# =====================================================================
# 1. Vector branch uses Bambu metadata export
# =====================================================================


class TestVectorBranchExport:
    """Confirm the vector conversion path goes through the unified
    Bambu metadata exporter rather than the plain trimesh export."""

    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_bambu_export_called(self, MockVP, mock_bambu_export, tmp_path):
        """export_scene_with_bambu_metadata should be invoked for SVG vector mode."""
        from config import ModelingMode

        svg_file = tmp_path / "test.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">'
            '<rect x="0" y="0" width="100" height="100" fill="#ff0000"/>'
            "</svg>"
        )

        fake_scene = trimesh.Scene()
        mesh = trimesh.creation.box(extents=[10, 10, 1])
        mesh.metadata["name"] = "White"
        mesh.visual.face_colors = [255, 255, 255, 255]
        fake_scene.add_geometry(mesh, geom_name="White")

        MockVP.return_value = _build_fake_processor(fake_scene)

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy.npy")
        np.save(dummy_lut, np.zeros(10))

        convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=50.0,
            spacer_thick=1.6,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
        )

        mock_bambu_export.assert_called_once()

    @patch("core.pipeline.vector_glb_preview.export_vector_glb_preview")
    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_reuses_existing_preview_glb_after_print_export(
        self,
        MockVP,
        mock_bambu_export,
        mock_glb_export,
        tmp_path,
    ) -> None:
        """A validated lightweight preview must replace generate-time GLB export."""
        from config import ModelingMode
        from core.converter import convert_image_to_3d

        svg_file = tmp_path / "reuse-preview.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
            '<rect width="20" height="20" fill="#ff0000"/>'
            "</svg>",
            encoding="utf-8",
        )
        scene = trimesh.Scene()
        scene.add_geometry(
            trimesh.creation.box(extents=(10.0, 10.0, 1.0)),
            geom_name="White",
        )
        MockVP.return_value = _build_fake_processor(scene)
        lut_path = tmp_path / "lut.npy"
        np.save(lut_path, np.zeros(10))
        preview_glb = tmp_path / "segmented-preview.glb"
        preview_glb.write_bytes(b"lightweight-preview")

        with patch("config.OUTPUT_DIR", str(tmp_path)):
            result = convert_image_to_3d(
                image_path=str(svg_file),
                lut_path=str(lut_path),
                target_width_mm=20.0,
                spacer_thick=1.2,
                structure_mode="Single-sided",
                color_mode="4-Color",
                add_loop=False,
                loop_width=5,
                loop_length=20,
                loop_hole=3,
                loop_pos="Top",
                modeling_mode=ModelingMode.VECTOR,
                enable_relief=True,
                color_height_map={"#ff0000": 2.0},
                preview_glb_path=str(preview_glb),
            )

        assert result[1] == str(preview_glb)
        mock_bambu_export.assert_called_once()
        mock_glb_export.assert_not_called()

    @patch("core.pipeline.vector_glb_preview.export_vector_glb_preview")
    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_missing_preview_glb_skips_print_scene_export(
        self,
        MockVP,
        mock_bambu_export,
        mock_glb_export,
        tmp_path,
    ) -> None:
        """A stale worker argument must never become the returned model path."""
        from config import ModelingMode
        from core.converter import convert_image_to_3d

        svg_file = tmp_path / "missing-preview.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
            '<rect width="20" height="20" fill="#ff0000"/>'
            "</svg>",
            encoding="utf-8",
        )
        scene = trimesh.Scene()
        scene.add_geometry(
            trimesh.creation.box(extents=(10.0, 10.0, 1.0)),
            geom_name="White",
        )
        MockVP.return_value = _build_fake_processor(scene)
        lut_path = tmp_path / "lut.npy"
        np.save(lut_path, np.zeros(10))
        missing_preview = tmp_path / "expired-preview.glb"

        with patch("config.OUTPUT_DIR", str(tmp_path)):
            result = convert_image_to_3d(
                image_path=str(svg_file),
                lut_path=str(lut_path),
                target_width_mm=20.0,
                spacer_thick=1.2,
                structure_mode="Single-sided",
                color_mode="4-Color",
                add_loop=False,
                loop_width=5,
                loop_length=20,
                loop_hole=3,
                loop_pos="Top",
                modeling_mode=ModelingMode.VECTOR,
                preview_glb_path=str(missing_preview),
            )

        assert result[1] is None
        mock_bambu_export.assert_called_once()
        mock_glb_export.assert_not_called()

    @patch("core.pipeline.vector_glb_preview.export_vector_glb_preview")
    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_generate_without_preview_glb_returns_only_completed_3mf(
        self,
        MockVP,
        mock_bambu_export,
        mock_glb_export,
        tmp_path,
    ) -> None:
        from config import ModelingMode
        from core.converter import convert_image_to_3d

        svg_file = tmp_path / "glb-budget.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
            '<rect width="20" height="20" fill="#ff0000"/>'
            "</svg>",
            encoding="utf-8",
        )
        scene = trimesh.Scene()
        scene.add_geometry(
            trimesh.creation.box(extents=(10.0, 10.0, 1.0)),
            geom_name="White",
        )
        MockVP.return_value = _build_fake_processor(scene)
        lut_path = tmp_path / "lut.npy"
        np.save(lut_path, np.zeros(10))
        result = convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=str(lut_path),
            target_width_mm=20.0,
            spacer_thick=1.2,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
        )

        assert result[0] is not None
        assert result[1] is None
        mock_bambu_export.assert_called_once()
        mock_glb_export.assert_not_called()

    @patch("core.pipeline.vector_glb_preview.export_vector_glb_preview")
    @patch("core.vector_engine.VectorProcessor")
    def test_effective_layer_height_reaches_processor_and_project_settings(
        self,
        MockVP,
        mock_glb_export,
        tmp_path,
        monkeypatch,
    ):
        """Ordinary vector export must use the same effective layer height as preview/tiles."""
        from config import ModelingMode

        svg_file = tmp_path / "custom-layer-height.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
            '<rect x="0" y="0" width="50" height="50" fill="#ff0000"/>'
            "</svg>"
        )

        fake_scene = trimesh.Scene()
        mesh = trimesh.creation.box(extents=[10, 10, 2.6])
        mesh.metadata["name"] = "White"
        fake_scene.add_geometry(mesh, geom_name="White")
        fake_processor = _build_fake_processor(fake_scene)
        MockVP.return_value = fake_processor

        dummy_lut = str(tmp_path / "custom-layer-height.npy")
        np.save(dummy_lut, np.zeros(10))

        import config

        monkeypatch.setattr(config, "MODELS_DIR", str(tmp_path))
        monkeypatch.setattr(config, "OUTPUT_DIR", str(tmp_path))
        mock_glb_export.return_value = str(tmp_path / "preview.glb")

        from core.converter import convert_image_to_3d

        result = convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=50.0,
            spacer_thick=1.2,
            structure_mode="Double-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
            color_layers=7,
            layer_height_mm=0.10,
        )

        model_path = result[0]
        assert model_path is not None
        with zipfile.ZipFile(model_path) as archive:
            project_settings = json.loads(
                archive.read("Metadata/project_settings.config").decode("utf-8")
            )

        assert fake_processor.layer_height_mm == pytest.approx(0.10)
        assert project_settings["layer_height"] == "0.1"
        assert project_settings["initial_layer_print_height"] == "0.1"

    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_slot_names_match_scene_geometry(self, MockVP, mock_bambu_export, tmp_path):
        """When backing is merged, slot_names should match the post-merge geometry keys."""
        from config import ModelingMode

        svg_file = tmp_path / "test2.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
            '<circle cx="25" cy="25" r="20" fill="#0000ff"/>'
            "</svg>"
        )

        fake_scene = trimesh.Scene()
        for name in ["White", "Cyan", "Board"]:
            m = trimesh.creation.box(extents=[5, 5, 0.5])
            m.metadata["name"] = name
            fake_scene.add_geometry(m, geom_name=name)

        MockVP.return_value = _build_fake_processor(fake_scene)

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy2.npy")
        np.save(dummy_lut, np.zeros(10))

        convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=30.0,
            spacer_thick=1.6,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
            nozzle_size="0.2",
            device_profile_id="BambuStudio:bbl:bambu-lab-h2d:0.2",
        )

        _, kwargs = mock_bambu_export.call_args
        assert kwargs["slot_names"] == ["White", "Cyan"]
        assert kwargs["project_slot_names"] == ["White", "Red", "Yellow", "Blue"]
        assert kwargs["settings"]["line_width"] == "0.22"
        assert kwargs["settings"]["initial_layer_line_width"] == "0.22"
        assert kwargs["device_profile_id"] == "BambuStudio:bbl:bambu-lab-h2d:0.2"

    @patch("core.pipeline.vector_glb_preview.export_vector_glb_preview")
    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_backing_color_id_merges_board_into_selected_slot(
        self,
        MockVP,
        mock_bambu_export,
        _mock_glb_export,
        tmp_path,
    ):
        from config import ModelingMode
        from core import vector_engine as vector_engine_module

        svg_file = tmp_path / "material-backing.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
            '<circle cx="25" cy="25" r="20" fill="#00ffff"/>'
            "</svg>"
        )

        fake_scene = trimesh.Scene()
        white = trimesh.creation.box(extents=[5, 5, 0.5])
        white.metadata["name"] = "White"
        white.visual.face_colors = [255, 255, 255, 255]
        fake_scene.add_geometry(white, geom_name="White")

        cyan = trimesh.creation.box(extents=[5, 5, 0.5])
        cyan.metadata["name"] = "Cyan"
        cyan.visual.face_colors = [0, 255, 255, 255]
        fake_scene.add_geometry(cyan, geom_name="Cyan")

        board = trimesh.creation.box(extents=[7, 7, 0.5])
        board.metadata["name"] = "Board"
        board.visual.face_colors = [255, 0, 255, 255]
        fake_scene.add_geometry(board, geom_name="Board")

        fake_processor = _build_fake_processor(fake_scene)
        fake_processor.analyze_svg.return_value.slot_names = ["White", "Cyan"]
        fake_processor.analyze_svg.return_value.preview_colors = {
            0: [255, 255, 255, 255],
            1: [0, 255, 255, 255],
        }
        MockVP.return_value = fake_processor

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy-material-backing.npy")
        np.save(dummy_lut, np.zeros(10))

        with (
            patch(
                "trimesh.util.concatenate",
                side_effect=AssertionError(
                    "board merge must use the direct vector concatenator"
                ),
            ),
            patch(
                "core.vector_engine._concatenate_meshes_fast",
                wraps=vector_engine_module._concatenate_meshes_fast,
            ) as concatenate_meshes,
        ):
            convert_image_to_3d(
                image_path=str(svg_file),
                lut_path=dummy_lut,
                target_width_mm=30.0,
                spacer_thick=1.6,
                structure_mode="Single-sided",
                color_mode="4-Color",
                add_loop=False,
                loop_width=5,
                loop_length=20,
                loop_hole=3,
                loop_pos="Top",
                modeling_mode=ModelingMode.VECTOR,
                backing_color_id=1,
            )

        concatenate_meshes.assert_called_once_with([cyan, board])
        fake_processor.build_mesh.assert_called_once()
        mock_bambu_export.assert_called_once()

        _, build_kwargs = fake_processor.build_mesh.call_args
        assert build_kwargs["backing_color_id"] == 1

        _, export_kwargs = mock_bambu_export.call_args
        exported_scene = export_kwargs["scene"]
        assert export_kwargs["slot_names"] == ["White", "Cyan"]
        assert "Board" not in exported_scene.geometry
        merged_cyan = exported_scene.geometry["Cyan"]
        assert len(merged_cyan.vertices) == len(cyan.vertices) + len(board.vertices)
        assert len(merged_cyan.faces) == len(cyan.faces) + len(board.faces)
        assert merged_cyan.metadata["name"] == "Cyan"
        np.testing.assert_array_equal(
            exported_scene.geometry["White"].vertices,
            white.vertices,
        )
        face_colors = np.asarray(merged_cyan.visual.face_colors)
        assert face_colors.shape == (len(merged_cyan.faces), 4)
        assert np.unique(face_colors, axis=0).tolist() == [[
            0,
            255,
            255,
            255,
        ]]

    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_separate_backing_reuses_selected_material_slot(self, MockVP, mock_bambu_export, tmp_path):
        """Board stays editable without creating a synthetic filament."""
        from config import ModelingMode

        svg_file = tmp_path / "test3.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
            '<circle cx="25" cy="25" r="20" fill="#0000ff"/>'
            "</svg>"
        )

        fake_scene = trimesh.Scene()
        for name in ["White", "Cyan", "Board"]:
            m = trimesh.creation.box(extents=[5, 5, 0.5])
            m.metadata["name"] = name
            fake_scene.add_geometry(m, geom_name=name)

        fake_processor = _build_fake_processor(fake_scene)
        fake_processor.analyze_svg.return_value.slot_names = ["White", "Cyan"]
        fake_processor.analyze_svg.return_value.preview_colors = {
            0: [255, 255, 255, 255],
            1: [0, 255, 255, 255],
        }
        MockVP.return_value = fake_processor

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy3.npy")
        np.save(dummy_lut, np.zeros(10))

        convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=30.0,
            spacer_thick=1.6,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
            separate_backing=True,
        )

        _, kwargs = mock_bambu_export.call_args
        assert kwargs["slot_names"] == ["White", "Cyan", "Board"]
        assert kwargs["project_slot_names"] == ["White", "Cyan"]
        assert (
            kwargs["scene"].geometry["Board"].metadata["bambu_material_name"]
            == "White"
        )

    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_separate_backing_uses_selected_backing_color_id(self, MockVP, mock_bambu_export, tmp_path):
        from config import ModelingMode

        svg_file = tmp_path / "separate-material-backing.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
            '<circle cx="25" cy="25" r="20" fill="#0000ff"/>'
            "</svg>"
        )

        fake_scene = trimesh.Scene()
        for name in ["White", "Cyan", "Board"]:
            m = trimesh.creation.box(extents=[5, 5, 0.5])
            m.metadata["name"] = name
            fake_scene.add_geometry(m, geom_name=name)

        fake_processor = _build_fake_processor(fake_scene)
        fake_processor.analyze_svg.return_value.slot_names = ["White", "Cyan"]
        fake_processor.analyze_svg.return_value.preview_colors = {
            0: [255, 255, 255, 255],
            1: [0, 255, 255, 255],
        }
        MockVP.return_value = fake_processor

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy-separate-material-backing.npy")
        np.save(dummy_lut, np.zeros(10))

        convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=30.0,
            spacer_thick=1.6,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
            backing_color_id=1,
            separate_backing=True,
        )

        _, build_kwargs = fake_processor.build_mesh.call_args
        assert build_kwargs["backing_color_id"] == 1

        _, export_kwargs = mock_bambu_export.call_args
        assert export_kwargs["slot_names"] == ["White", "Cyan", "Board"]
        assert export_kwargs["project_slot_names"] == ["White", "Cyan"]
        assert export_kwargs["preview_colors"]["Board"] == [0, 255, 255, 255]
        assert (
            export_kwargs["scene"]
            .geometry["Board"]
            .metadata["bambu_material_name"]
            == "Cyan"
        )

    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_vector_add_loop_exports_keychain_geometry(self, MockVP, mock_bambu_export, tmp_path):
        """Vector exports should include the requested keychain loop object."""
        from shapely.geometry import GeometryCollection, box

        from config import ModelingMode
        from core.vector_structure import VectorStructurePlan

        svg_file = tmp_path / "loop-vector.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="84">'
            '<rect x="10" y="10" width="60" height="64" fill="#ff0000"/>'
            "</svg>"
        )

        fake_scene = trimesh.Scene()
        red = trimesh.creation.box(extents=[80, 84, 1])
        red.metadata["name"] = "Red"
        red.visual.face_colors = [255, 0, 0, 255]
        fake_scene.add_geometry(red, geom_name="Red")

        fake_processor = _build_fake_processor(fake_scene)
        fake_processor.analyze_svg.return_value.preview_colors = {
            0: [255, 255, 255, 255],
            1: [255, 0, 0, 255],
            2: [255, 255, 0, 255],
            3: [0, 0, 255, 255],
        }
        fake_processor.analyze_svg.return_value.slot_names = ["White", "Red", "Yellow", "Blue"]
        fake_processor.analyze_svg.return_value.num_layers = 4
        footprint = box(-40, -42, 40, 42)
        fake_processor.analyze_svg.return_value.structure_plan = VectorStructurePlan(
            footprint, footprint, GeometryCollection(), 0.0,
        )
        MockVP.return_value = fake_processor

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy-loop-vector.npy")
        np.save(dummy_lut, np.zeros(10))

        convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=80.0,
            spacer_thick=1.2,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=True,
            loop_width=4.5,
            loop_length=5.0,
            loop_hole=2.5,
            loop_pos=None,
            modeling_mode=ModelingMode.VECTOR,
            loop_offset_x=3.392669411755735,
            loop_offset_y=-0.16220436514278447,
            loop_position_preset="top-center",
            center_on_bed=False,
        )

        _, export_kwargs = mock_bambu_export.call_args
        exported_scene = export_kwargs["scene"]
        keychain = exported_scene.geometry["Keychain_Loop"]

        assert "Keychain_Loop" in export_kwargs["slot_names"]
        assert "Keychain_Loop" not in export_kwargs["project_slot_names"]
        assert export_kwargs["preview_colors"]["Keychain_Loop"] == [255, 0, 0, 255]
        assert keychain.metadata["name"] == "Keychain_Loop"
        assert keychain.metadata["bambu_material_name"] == "Red"
        assert len(keychain.vertices) > 0
        assert len(keychain.faces) > 0

    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_vector_export_centers_scene_on_selected_printer_bed(self, MockVP, mock_bambu_export, tmp_path):
        """3MF placement must not translate vertices before writer serialization."""
        from config import ModelingMode

        svg_file = tmp_path / "center-vector.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
            '<rect x="0" y="0" width="50" height="50" fill="#ffffff"/>'
            "</svg>"
        )

        fake_scene = trimesh.Scene()
        mesh = trimesh.creation.box(extents=[20, 10, 1])
        mesh.metadata["name"] = "White"
        fake_scene.add_geometry(mesh, geom_name="White")
        MockVP.return_value = _build_fake_processor(fake_scene)

        writer_bounds = None

        def capture_writer_bounds(*_args, **kwargs):
            nonlocal writer_bounds
            writer_bounds = np.asarray(kwargs["scene"].bounds).copy()

        mock_bambu_export.side_effect = capture_writer_bounds

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy-centered-vector.npy")
        np.save(dummy_lut, np.zeros(10))

        convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=30.0,
            spacer_thick=1.6,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
            printer_id="bambu-p1s",
        )

        _, kwargs = mock_bambu_export.call_args
        exported_scene = kwargs["scene"]
        assert writer_bounds is not None
        writer_center_x = (writer_bounds[0][0] + writer_bounds[1][0]) / 2
        writer_center_y = (writer_bounds[0][1] + writer_bounds[1][1]) / 2
        assert writer_center_x == pytest.approx(0.0)
        assert writer_center_y == pytest.approx(0.0)

        # The retained scene is still centred afterwards for the GLB preview.
        bounds = exported_scene.bounds
        center_x = (bounds[0][0] + bounds[1][0]) / 2
        center_y = (bounds[0][1] + bounds[1][1]) / 2
        assert center_x == pytest.approx(128)
        assert center_y == pytest.approx(128)

    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_vector_branch_sets_processor_coating_options(self, MockVP, mock_bambu_export, tmp_path):
        from config import ModelingMode

        svg_file = tmp_path / "coating-vector.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
            '<rect x="0" y="0" width="50" height="50" fill="#ffffff"/>'
            "</svg>"
        )

        fake_scene = trimesh.Scene()
        mesh = trimesh.creation.box(extents=[20, 10, 1])
        mesh.metadata["name"] = "White"
        fake_scene.add_geometry(mesh, geom_name="White")
        fake_processor = _build_fake_processor(fake_scene)
        MockVP.return_value = fake_processor

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy-coating-vector.npy")
        np.save(dummy_lut, np.zeros(10))

        convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=30.0,
            spacer_thick=1.6,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
            enable_coating=True,
            coating_height_mm=0.12,
        )

        assert fake_processor.enable_coating is True
        assert fake_processor.coating_height_mm == 0.12

    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_empty_scene_returns_error(self, MockVP, mock_bambu_export, tmp_path):
        """Empty vector scene should fail before exporter is called."""
        from config import ModelingMode

        svg_file = tmp_path / "empty.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            '<rect x="0" y="0" width="10" height="10" fill="#ffffff"/>'
            "</svg>"
        )

        empty_scene = trimesh.Scene()
        MockVP.return_value = _build_fake_processor(empty_scene)

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy4.npy")
        np.save(dummy_lut, np.zeros(10))

        out_path, glb_path, preview_img, msg, _ = convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=20.0,
            spacer_thick=1.6,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
        )

        assert out_path is None
        assert glb_path is None
        assert preview_img is None
        assert "no valid geometry" in msg.lower()
        mock_bambu_export.assert_not_called()

        mock_bambu_export.assert_not_called()

    @patch("utils.bambu_3mf_writer.export_scene_with_bambu_metadata")
    @patch("core.vector_engine.VectorProcessor")
    def test_fridge_magnet_params_forwarded_to_build_mesh(self, MockVP, mock_bambu_export, tmp_path):
        """Vector branch should forward fridge-magnet params into build_mesh."""
        from config import ModelingMode

        svg_file = tmp_path / "fridge.svg"
        svg_file.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="50" height="50">'
            '<circle cx="25" cy="25" r="20" fill="#0000ff"/>'
            "</svg>"
        )

        fake_scene = trimesh.Scene()
        mesh = trimesh.creation.box(extents=[5, 5, 0.5])
        mesh.metadata["name"] = "White"
        fake_scene.add_geometry(mesh, geom_name="White")

        fake_processor = _build_fake_processor(fake_scene)
        MockVP.return_value = fake_processor

        expected_fridge_magnets = [
            {
                "id": "magnet-round",
                "shape": "round",
                "preset_key": "round-18",
                "diameter_mm": 18.0,
                "width_mm": None,
                "height_mm": None,
                "thickness_mm": 2.0,
                "center_x_mm": 20.0,
                "center_y_mm": 25.0,
            }
        ]

        from core.converter import convert_image_to_3d

        dummy_lut = str(tmp_path / "dummy-fridge.npy")
        np.save(dummy_lut, np.zeros(10))

        convert_image_to_3d(
            image_path=str(svg_file),
            lut_path=dummy_lut,
            target_width_mm=30.0,
            spacer_thick=1.6,
            structure_mode="Single-sided",
            color_mode="4-Color",
            add_loop=False,
            loop_width=5,
            loop_length=20,
            loop_hole=3,
            loop_pos="Top",
            modeling_mode=ModelingMode.VECTOR,
            enable_fridge_magnet=True,
            fridge_magnets=expected_fridge_magnets,
        )

        _, kwargs = fake_processor.build_mesh.call_args
        assert kwargs["enable_fridge_magnet"] is True
        assert kwargs["fridge_magnets"] == expected_fridge_magnets


class TestBambuExportGuardrails:

    def test_export_scene_raises_on_missing_slot_geometry(self, tmp_path):
        scene = trimesh.Scene()
        scene.add_geometry(trimesh.creation.box(extents=[5, 5, 1]), geom_name="White")

        out_path = tmp_path / "out.3mf"
        with pytest.raises(ValueError, match="Missing geometries"):
            export_scene_with_bambu_metadata(
                scene=scene,
                output_path=str(out_path),
                slot_names=["White", "Cyan"],
                preview_colors={0: [255, 255, 255, 255], 1: [0, 134, 214, 255]},
                settings={},
                color_mode="4-Color",
            )

    def test_writer_add_mesh_rejects_empty_mesh(self, tmp_path):
        writer = BambuStudio3MFWriter(str(tmp_path / "x.3mf"), settings={}, color_mode="4-Color")
        empty = trimesh.Trimesh(vertices=np.zeros((0, 3)), faces=np.zeros((0, 3), dtype=np.int64))
        with pytest.raises(ValueError, match="empty geometry"):
            writer.add_mesh(empty, "White", (255, 255, 255))
