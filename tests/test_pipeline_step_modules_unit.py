"""
Unit tests for pipeline step modules.
管道步骤模块的单元测试。

覆盖范围：S01, S03, S06, S12, P01, P04, P05
测试边界情况：空输入、缺失键、无效参数

_需求: 9.3_
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image
import pytest
import trimesh

from config import ColorSystem, LUTMetadata, ModelingMode, PaletteEntry, PrinterConfig
from core.material_color_solver import MaterialParams

# ===========================================================================
# S02 — s02_image_processing 单元测试
# ===========================================================================


class TestS02ImageProcessing:
    """S02 图像处理步骤的单元测试。"""

    def test_reuses_preview_analysis_paths_without_process_image(self, tmp_path):
        """匹配的预览分析缓存应保留处理器上下文但跳过 process_image。"""
        from core.pipeline.s02_image_processing import run

        matched_rgb = np.zeros((3, 4, 3), dtype=np.uint8)
        matched_rgb[..., 0] = 128
        mask_solid = np.ones((3, 4), dtype=bool)
        material_matrix = np.zeros((3, 4, 5), dtype=np.uint8)

        matched_path = tmp_path / "matched_rgb.npy"
        mask_path = tmp_path / "mask_solid.npy"
        matrix_path = tmp_path / "material_matrix.npy"
        np.save(matched_path, matched_rgb)
        np.save(mask_path, mask_solid)
        np.save(matrix_path, material_matrix)

        ctx = {
            "actual_lut_path": str(tmp_path / "lut.npy"),
            "color_mode": "4-Color (RYBW)",
            "hue_weight": 0.0,
            "chroma_gate": 15.0,
            "image_path": str(tmp_path / "input.png"),
            "target_width_mm": 40.0,
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
            "quantize_colors": 48,
            "enable_cleanup": True,
            "reuse_preview_analysis": True,
            "matched_rgb_path": str(matched_path),
            "mask_solid_path": str(mask_path),
            "material_matrix_path": str(matrix_path),
        }

        with patch("core.pipeline.s02_image_processing.LuminaImageProcessor") as processor_cls:
            processor_cls.return_value.process_image.side_effect = AssertionError(
                "process_image should not run for reused preview analysis"
            )
            result = run(ctx)

        assert "error" not in result
        np.testing.assert_array_equal(result["matched_rgb"], matched_rgb)
        np.testing.assert_array_equal(result["mask_solid"], mask_solid)
        np.testing.assert_array_equal(result["material_matrix"], material_matrix)
        assert result["target_w"] == 4
        assert result["target_h"] == 3
        assert result["pixel_scale"] == pytest.approx(10.0)
        assert result["mode_info"]["mode"] == ModelingMode.HIGH_FIDELITY
        assert result["debug_data"] is None
        assert result["processor"] is processor_cls.return_value
        processor_cls.assert_called_once()
        processor_cls.return_value.process_image.assert_not_called()

    def test_required_preview_analysis_rejects_wrong_rank_instead_of_fallback(
        self,
        tmp_path,
    ) -> None:
        """Spatial edits must never fall back to a fresh S02 analysis."""

        from core.pipeline.s02_image_processing import _load_reused_preview_analysis
        from core.errors import CachedPreviewAnalysisError
        from core.preview_analysis_cache import REQUIRED_PREVIEW_ANALYSIS_REUSE

        matched_path = tmp_path / "matched_rgb.npy"
        mask_path = tmp_path / "mask_solid.npy"
        matrix_path = tmp_path / "material_matrix.npy"
        np.save(matched_path, np.zeros((3, 4), dtype=np.uint8))
        np.save(mask_path, np.ones((3, 4), dtype=bool))
        np.save(matrix_path, np.zeros((3, 4, 5), dtype=np.int16))

        with pytest.raises(CachedPreviewAnalysisError):
            _load_reused_preview_analysis(
                {
                    "reuse_preview_analysis": REQUIRED_PREVIEW_ANALYSIS_REUSE,
                    "matched_rgb_path": str(matched_path),
                    "mask_solid_path": str(mask_path),
                    "material_matrix_path": str(matrix_path),
                }
            )

    @staticmethod
    def _material_archive_reuse_context(
        tmp_path,
        *,
        color_replacements: dict[str, str] | None = None,
    ) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray, list]:
        from core.material_color_solver import MaterialParams

        source_path = tmp_path / "source-tile.png"
        Image.fromarray(np.zeros((11, 17, 3), dtype=np.uint8)).save(source_path)

        matched_rgb = np.full((3, 4, 3), [200, 100, 50], dtype=np.uint8)
        matched_rgb[:, 0] = [50, 70, 200]
        mask_solid = np.ones((3, 4), dtype=bool)
        mask_solid[0, 0] = False
        material_matrix = np.zeros((3, 4, 5), dtype=np.int16)
        material_matrix[:, 0, :] = 1

        matched_path = tmp_path / "archive-matched.npy"
        mask_path = tmp_path / "archive-mask.npy"
        material_path = tmp_path / "archive-material.npy"
        np.save(matched_path, matched_rgb)
        np.save(mask_path, mask_solid)
        np.save(material_path, material_matrix)

        def _material(
            name: str,
            equilibrium: tuple[float, float, float],
            absorption: tuple[float, float, float],
        ) -> MaterialParams:
            return MaterialParams(
                name=name,
                directory_name=name.lower(),
                E=np.asarray(equilibrium, dtype=np.float64),
                k=np.asarray(absorption, dtype=np.float64),
                C0_white=np.ones(3, dtype=np.float64),
                estimated_rgb=np.asarray(
                    [int(round(255 * component)) for component in equilibrium],
                    dtype=np.uint8,
                ),
            )

        materials = [
            _material("Red", (0.6, 0.05, 0.05), (4.0, 4.0, 4.0)),
            _material("Blue", (0.05, 0.1, 0.6), (4.0, 4.0, 4.0)),
            _material("White", (0.95, 0.95, 0.95), (0.5, 0.5, 0.5)),
        ]
        ctx = {
            "image_path": str(source_path),
            "target_width_mm": 40.0,
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
            "quantize_colors": 8,
            "material_source": "material_archive",
            "_material_params": materials,
            "selected_materials": ["red", "blue", "white"],
            "color_layers": 5,
            "layer_height_mm": 0.08,
            "material_substrate": "white",
            "reuse_preview_analysis": True,
            "matched_rgb_path": str(matched_path),
            "mask_solid_path": str(mask_path),
            "material_matrix_path": str(material_path),
            "color_replacements": color_replacements,
            "replacement_regions": None,
        }
        return ctx, matched_rgb, mask_solid, material_matrix, materials

    def test_material_archive_reuses_spatial_analysis_before_solver(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        """S02+S03 must consume tile-cache grids even when source pixels differ."""

        from core.pipeline import p03_core_processing
        from core.pipeline import s02_image_processing
        from core.pipeline import s03_color_replacement

        ctx, matched_rgb, mask_solid, material_matrix, materials = (
            self._material_archive_reuse_context(tmp_path)
        )

        def _fail_material_solver(_ctx: dict) -> dict:
            raise AssertionError("material solver must not run for validated reuse")

        def _fail_lut_processor(*_args, **_kwargs):
            raise AssertionError("material archive reuse must not create LUT processor")

        monkeypatch.setattr(
            p03_core_processing,
            "_run_material_archive_branch",
            _fail_material_solver,
        )
        monkeypatch.setattr(
            s02_image_processing,
            "LuminaImageProcessor",
            _fail_lut_processor,
        )

        after_s02 = s02_image_processing.run(ctx)
        after_s03 = s03_color_replacement.run(after_s02)

        np.testing.assert_array_equal(after_s03["matched_rgb"], matched_rgb)
        np.testing.assert_array_equal(after_s03["mask_solid"], mask_solid)
        np.testing.assert_array_equal(after_s03["material_matrix"], material_matrix)
        assert after_s03["target_w"] == 4
        assert after_s03["target_h"] == 3
        assert after_s03["pixel_scale"] == pytest.approx(10.0)
        assert after_s03["mode_info"] == {
            "mode": ModelingMode.HIGH_FIDELITY,
            "lut_match_mode": "material_archive",
        }
        assert after_s03["lut_metadata"] is None
        assert after_s03.get("processor") is None
        assert after_s03["_material_params"] is materials

    def test_material_archive_reused_grid_keeps_global_replacements_working(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        """Real S03 replacement solving must still use preserved material params."""

        from core.pipeline import p03_core_processing
        from core.pipeline import s02_image_processing
        from core.pipeline import s03_color_replacement

        ctx, matched_rgb, mask_solid, material_matrix, materials = (
            self._material_archive_reuse_context(
                tmp_path,
                color_replacements={"#c86432": "#14c814"},
            )
        )

        def _fail_material_solver(_ctx: dict) -> dict:
            raise AssertionError("material solver must not rebuild reused analysis")

        monkeypatch.setattr(
            p03_core_processing,
            "_run_material_archive_branch",
            _fail_material_solver,
        )

        after_s02 = s02_image_processing.run(ctx)
        after_s03 = s03_color_replacement.run(after_s02)

        np.testing.assert_array_equal(after_s03["matched_rgb"][:, 0], matched_rgb[:, 0])
        np.testing.assert_array_equal(
            after_s03["material_matrix"][:, 0],
            material_matrix[:, 0],
        )
        assert not np.array_equal(after_s03["matched_rgb"][:, 1:], matched_rgb[:, 1:])
        assert np.any(after_s03["material_matrix"][:, 1:] != material_matrix[:, 1:])
        np.testing.assert_array_equal(after_s03["mask_solid"], mask_solid)
        assert after_s03["matched_rgb"].shape[:2] == (3, 4)
        assert after_s03["material_matrix"].shape[:2] == (3, 4)
        assert after_s03["_material_params"] is materials

    def test_recipe_only_final_matrix_aligns_to_fresh_non_divisible_lut_grid(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        """Real LUT S02→S03 aligns recipe authority to a fresh tile grid."""

        from api.routers.converter.generate import (
            _prepare_recipe_override_worker_inputs,
        )
        from api.schemas.converter import ConvertGenerateRequest
        from api.session_store import SessionStore
        from core.pipeline import s02_image_processing
        from core.pipeline import s03_color_replacement

        source_path = tmp_path / "source.png"
        lut_path = tmp_path / "lut.npy"
        authority_mask_path = tmp_path / "final-material-authority-mask.npy"
        Image.fromarray(np.full((1, 4, 3), [255, 0, 0], dtype=np.uint8)).save(
            source_path
        )
        lut_path.write_bytes(b"lut")

        # The whole-image preview artifact has four columns, while fresh S02
        # resolves this non-divisible tile to five. This is the production
        # mismatch that previously made S03 silently discard every recipe.
        processed_rgb = np.full((1, 5, 3), [255, 0, 0], dtype=np.uint8)
        processed_matrix = np.ones((1, 5, 5), dtype=np.int16)
        mask_solid = np.ones((1, 5), dtype=bool)
        preview_matrix = np.ones((1, 4, 5), dtype=np.int16)
        preview_mask_solid = np.ones((1, 4), dtype=bool)
        region_1_mask = np.array([[True, True, False, False]], dtype=bool)
        region_2_mask = np.array([[False, True, True, False]], dtype=bool)
        authority_mask = region_1_mask | region_2_mask
        recipe_overrides = [
            {
                "region_id": "region-1",
                "recipe": [5, 5, 5, 5, 5],
                "layer_order": "Top2Bottom",
            },
            {
                "region_id": "region-2",
                "recipe": [7, 7, 7, 7, 7],
                "layer_order": "Top2Bottom",
            },
        ]

        # Use the actual route helper. It starts from the stale preview matrix
        # and applies only custom recipes; it does not replay imported global
        # color mappings. Column 3 therefore remains stack 1 in this artifact.
        store = SessionStore(ttl=1800)
        sid = store.create()
        cache = {
            "material_matrix": preview_matrix.copy(),
            "mask_solid": preview_mask_solid.copy(),
            "lut_metadata": LUTMetadata(
                max_color_layers=5,
                layer_height_mm=0.08,
                base_channel_idx=0,
            ),
        }
        session_data = {
            "selected_region_masks": {
                "region-1": region_1_mask,
                "region-2": region_2_mask,
            }
        }
        request = ConvertGenerateRequest(
            lut_name="test-lut",
            color_layers=5,
            recipe_overrides=recipe_overrides,
        )
        final_matrix_path, recipe_masks_path = (
            _prepare_recipe_override_worker_inputs(
                cache=cache,
                session_data=session_data,
                recipe_overrides=recipe_overrides,
                request=request,
                sid=sid,
                store=store,
            )
        )
        assert final_matrix_path is not None
        assert recipe_masks_path is not None
        prepared_matrix = np.load(final_matrix_path)
        prepared_before_global = np.array(
            [
                [
                    [5, 5, 5, 5, 5],
                    [7, 7, 7, 7, 7],
                    [7, 7, 7, 7, 7],
                    [1, 1, 1, 1, 1],
                ]
            ],
            dtype=np.int16,
        )
        np.testing.assert_array_equal(prepared_matrix, prepared_before_global)
        np.save(authority_mask_path, authority_mask)

        # Global recoloring must update the physical stack outside recipe
        # coverage while the recipe union remains authoritative. Later recipe
        # wins at the overlap (column 1).
        expected_final_matrix = np.array(
            [
                [
                    [5, 5, 5, 5, 5],
                    [7, 7, 7, 7, 7],
                    [7, 7, 7, 7, 7],
                    [7, 7, 7, 7, 7],
                    [2, 2, 2, 2, 2],
                ]
            ],
            dtype=np.int16,
        )

        class _FakeTree:
            @staticmethod
            def query(_values):
                return np.array([0.0]), np.array([1])

        class _FakeProcessor:
            def __init__(self, *_args, **_kwargs) -> None:
                self.enable_cleanup = True
                self.last_match_info = None
                self.kdtree = _FakeTree()
                self.ref_stacks = np.array(
                    [[1, 1, 1, 1, 1], [2, 2, 2, 2, 2]],
                    dtype=np.int16,
                )
                self.lut_rgb = np.array(
                    [[255, 0, 0], [0, 255, 0]],
                    dtype=np.uint8,
                )
                self.process_calls = 0

            @staticmethod
            def _rgb_to_lab(values: np.ndarray) -> np.ndarray:
                return np.asarray(values, dtype=np.float64)

            def process_image(self, **_kwargs) -> dict:
                self.process_calls += 1
                return {
                    "matched_rgb": processed_rgb.copy(),
                    "material_matrix": processed_matrix.copy(),
                    "mask_solid": mask_solid.copy(),
                    "dimensions": (5, 1),
                    "pixel_scale": 8.0,
                    "mode_info": {"mode": ModelingMode.HIGH_FIDELITY},
                }

        monkeypatch.setattr(s02_image_processing, "LUTManager", None)
        monkeypatch.setattr(
            s02_image_processing,
            "LuminaImageProcessor",
            _FakeProcessor,
        )
        ctx = {
            "actual_lut_path": str(lut_path),
            "color_mode": "4-Color (RYBW)",
            "image_path": str(source_path),
            "target_width_mm": 40.0,
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
            "quantize_colors": 8,
            "enable_cleanup": True,
            "reuse_preview_analysis": False,
            "matched_rgb_path": None,
            "mask_solid_path": None,
            "material_matrix_path": str(final_matrix_path),
            "final_material_matrix_is_authoritative": True,
            "final_material_matrix_authority_mask_path": str(
                authority_mask_path
            ),
            "replacement_regions": [
                {
                    "quantized_hex": "#ff0000",
                    "matched_hex": "#ff0000",
                    "replacement_hex": "#00ff00",
                }
            ],
            "recipe_overrides": recipe_overrides,
            # Large-format raster tiling deliberately consumes the already
            # final matrix and does not forward whole-image masks to workers.
            "recipe_override_masks_path": None,
        }

        try:
            after_s02 = s02_image_processing.run(ctx)
            processor = after_s02["processor"]
            after_s03 = s03_color_replacement.run(after_s02)

            assert processor.process_calls == 1
            np.testing.assert_array_equal(
                after_s03["matched_rgb"],
                np.full((1, 5, 3), [0, 255, 0], dtype=np.uint8),
            )
            np.testing.assert_array_equal(
                after_s03["material_matrix"],
                expected_final_matrix,
            )
        finally:
            store.clear_all()

    def test_recipe_only_final_matrix_aligns_to_fresh_material_archive_grid(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        """Real material-archive S02→S03 uses the same safe grid alignment."""

        from core.pipeline import p03_core_processing
        from core.pipeline import s02_image_processing
        from core.pipeline import s03_color_replacement

        source_path = tmp_path / "source-tile.png"
        Image.fromarray(np.zeros((3, 7, 3), dtype=np.uint8)).save(source_path)

        final_matrix = np.array(
            [
                [
                    [6, 6, 6, 6, 6],
                    [6, 6, 6, 6, 6],
                    [1, 1, 1, 1, 1],
                    [1, 1, 1, 1, 1],
                ]
            ],
            dtype=np.int16,
        )
        authority_mask = np.array([[True, True, False, False]], dtype=bool)
        final_matrix_path = tmp_path / "final-material.npy"
        authority_mask_path = tmp_path / "final-material-authority.npy"
        np.save(final_matrix_path, final_matrix)
        np.save(authority_mask_path, authority_mask)

        fresh_rgb = np.full((1, 5, 3), [180, 120, 80], dtype=np.uint8)
        fresh_matrix = np.full((1, 5, 5), 3, dtype=np.int16)
        fresh_mask = np.ones((1, 5), dtype=bool)

        def _run_fresh_material_archive(ctx: dict) -> dict:
            ctx.update(
                {
                    "matched_rgb": fresh_rgb.copy(),
                    "material_matrix": fresh_matrix.copy(),
                    "mask_solid": fresh_mask.copy(),
                    "target_w": 5,
                    "target_h": 1,
                    "pixel_scale": 8.0,
                    "mode_info": {
                        "mode": ModelingMode.HIGH_FIDELITY,
                        "lut_match_mode": "material_archive",
                    },
                    "debug_data": None,
                }
            )
            return ctx

        monkeypatch.setattr(
            p03_core_processing,
            "_run_material_archive_branch",
            _run_fresh_material_archive,
        )
        ctx = {
            "image_path": str(source_path),
            "target_width_mm": 40.0,
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
            "quantize_colors": 8,
            "material_source": "material_archive",
            "reuse_preview_analysis": False,
            "material_matrix_path": str(final_matrix_path),
            "final_material_matrix_is_authoritative": True,
            "final_material_matrix_authority_mask_path": str(
                authority_mask_path
            ),
            "recipe_overrides": [
                {
                    "region_id": "region-1",
                    "recipe": [6, 6, 6, 6, 6],
                    "layer_order": "Top2Bottom",
                }
            ],
            "recipe_override_masks_path": None,
        }

        after_s02 = s02_image_processing.run(ctx)
        after_s03 = s03_color_replacement.run(after_s02)

        expected = np.array(
            [
                [
                    [6, 6, 6, 6, 6],
                    [6, 6, 6, 6, 6],
                    [1, 1, 1, 1, 1],
                    [1, 1, 1, 1, 1],
                    [1, 1, 1, 1, 1],
                ]
            ],
            dtype=np.int16,
        )
        np.testing.assert_array_equal(after_s03["material_matrix"], expected)
        np.testing.assert_array_equal(after_s03["matched_rgb"], fresh_rgb)

    def test_recipe_only_final_matrix_rejects_unsafe_channel_alignment(
        self,
        tmp_path,
    ) -> None:
        """Spatial alignment must not hide incompatible recipe layer counts."""

        from core.pipeline import s03_color_replacement

        final_matrix_path = tmp_path / "final-material.npy"
        authority_mask_path = tmp_path / "final-material-authority.npy"
        np.save(final_matrix_path, np.zeros((1, 4, 6), dtype=np.int16))
        np.save(authority_mask_path, np.ones((1, 4), dtype=bool))
        ctx = {
            "matched_rgb": np.zeros((1, 5, 3), dtype=np.uint8),
            "material_matrix": np.zeros((1, 5, 5), dtype=np.int16),
            "mask_solid": np.ones((1, 5), dtype=bool),
            "material_matrix_path": str(final_matrix_path),
            "final_material_matrix_is_authoritative": True,
            "final_material_matrix_authority_mask_path": str(
                authority_mask_path
            ),
        }

        with pytest.raises(
            ValueError,
            match="layer count does not match processed material matrix",
        ):
            s03_color_replacement.run(ctx)

    @pytest.mark.parametrize(
        ("cached_analysis_is_final", "expect_preserved"),
        [(True, True), (False, False)],
    )
    def test_large_format_final_cache_controls_replacement_reapplication(
        self,
        tmp_path,
        cached_analysis_is_final: bool,
        expect_preserved: bool,
    ) -> None:
        """S02→S03 must treat a reused final trio as authoritative state."""

        from api.routers.converter.generate import _resolve_large_format_shared_params
        from api.schemas.converter import (
            LargeFormatConvertGenerateRequest,
            ModelingMode as ApiModelingMode,
        )
        from core.pipeline import s02_image_processing
        from core.pipeline import s03_color_replacement

        base_ctx, _rgb, _mask, _matrix, materials = (
            self._material_archive_reuse_context(tmp_path)
        )
        final_matched_rgb = np.array(
            [[[200, 100, 50], [50, 70, 200]]],
            dtype=np.uint8,
        )
        final_mask_solid = np.ones((1, 2), dtype=bool)
        final_material_matrix = np.array(
            [[[7, 7, 7, 7, 7], [2, 2, 2, 2, 2]]],
            dtype=np.int16,
        )
        matched_path = tmp_path / "final-matched.npy"
        mask_path = tmp_path / "final-mask.npy"
        material_path = tmp_path / "final-material.npy"
        np.save(matched_path, final_matched_rgb)
        np.save(mask_path, final_mask_solid)
        np.save(material_path, final_material_matrix)

        session_data = {
            "material_source": "material_archive",
            "selected_materials": ["red", "blue", "white"],
            "material_layer_count": 5,
            "material_layer_height_mm": 0.08,
            "material_grid_resolution": 64,
            "replacement_regions": [
                {
                    "quantized_hex": "#c86432",
                    "matched_hex": "#c86432",
                    "replacement_hex": "#3246c8",
                }
            ],
        }
        request = LargeFormatConvertGenerateRequest(
            lut_name="__material_archive__",
            modeling_mode=ApiModelingMode.HIGH_FIDELITY,
        )
        ctx = _resolve_large_format_shared_params(
            session_data,
            request,
            None,
            matched_rgb_path=str(matched_path),
            mask_solid_path=str(mask_path),
            material_matrix_path=str(material_path),
            cached_analysis_is_final=cached_analysis_is_final,
        )
        ctx.update(
            {
                "image_path": base_ctx["image_path"],
                "target_width_mm": 20.0,
                "reuse_preview_analysis": True,
                "_material_params": materials,
                "material_substrate": "white",
                "grid_resolution": 64,
            }
        )

        after_s02 = s02_image_processing.run(ctx)
        after_s03 = s03_color_replacement.run(after_s02)

        if expect_preserved:
            assert ctx["replacement_regions"] is None
            np.testing.assert_array_equal(
                after_s03["matched_rgb"],
                final_matched_rgb,
            )
            np.testing.assert_array_equal(
                after_s03["material_matrix"],
                final_material_matrix,
            )
            np.testing.assert_array_equal(
                after_s03["material_matrix"][0, 0],
                np.array([7, 7, 7, 7, 7], dtype=np.int16),
            )
        else:
            assert ctx["replacement_regions"] == session_data["replacement_regions"]
            assert not np.array_equal(after_s03["matched_rgb"], final_matched_rgb)
            assert not np.array_equal(
                after_s03["material_matrix"],
                final_material_matrix,
            )


# ===========================================================================
# S01 — s01_input_validation 单元测试
# ===========================================================================


class TestS01InputValidation:
    """S01 输入验证步骤的单元测试。"""

    def _make_valid_ctx(self) -> dict:
        """构造 S01 的最小有效 PipelineContext。"""
        return {
            "image_path": "/tmp/test.png",
            "lut_path": "/tmp/test.npy",
            "color_mode": "4-Color",
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
            "backing_color_id": 0,
            "separate_backing": False,
        }

    def test_valid_input_produces_expected_keys(self):
        """有效输入应产生所有声明的输出键。"""
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        assert "actual_lut_path" in result
        assert result["actual_lut_path"] == "/tmp/test.npy"
        assert "color_conf" in result
        assert "slot_names" in result
        assert "preview_colors" in result
        assert "is_svg_vector" in result
        assert result["is_svg_vector"] is False

    def test_none_lut_path_sets_error(self):
        """lut_path 为 None 时应设置 error 键。"""
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        ctx["lut_path"] = None
        result = run(ctx)

        assert "error" in result
        assert "calibration" in result["error"].lower() or "npy" in result["error"].lower()

    def test_none_image_path_sets_error(self):
        """image_path 为 None 时应设置 error 键。"""
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        ctx["image_path"] = None
        result = run(ctx)

        assert "error" in result
        assert "image" in result["error"].lower()

    def test_missing_image_path_raises_key_error(self):
        """缺失 image_path 键应抛出 KeyError。"""
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        del ctx["image_path"]
        with pytest.raises(KeyError):
            run(ctx)

    def test_file_like_object_lut_path(self):
        """file-like 对象的 lut_path 应正确解析 .name 属性。"""
        from core.pipeline.s01_input_validation import run

        mock_file = MagicMock()
        mock_file.name = "/tmp/uploaded_lut.npy"

        ctx = self._make_valid_ctx()
        ctx["lut_path"] = mock_file
        result = run(ctx)

        assert result["actual_lut_path"] == "/tmp/uploaded_lut.npy"

    def test_invalid_lut_path_type_sets_error(self):
        """非字符串且无 .name 属性的 lut_path 应设置 error。"""
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        ctx["lut_path"] = 12345  # 无效类型
        result = run(ctx)

        assert "error" in result

    def test_svg_vector_mode_detection(self):
        """SVG 文件 + VECTOR 模式应设置 is_svg_vector=True。"""
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        ctx["image_path"] = "/tmp/test.svg"
        ctx["modeling_mode"] = ModelingMode.VECTOR
        result = run(ctx)

        assert result["is_svg_vector"] is True

    def test_vector_mode_rejects_non_svg_input(self):
        """S01 应保留 VECTOR + 非 SVG 的既有校验行为。"""
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        ctx["modeling_mode"] = ModelingMode.VECTOR

        result = run(ctx)

        assert result["is_svg_vector"] is False
        assert "Vector Native mode requires SVG files" in result["error"]

    def test_material_archive_vector_mode_rejects_non_svg_before_material_loading(self):
        """材料生成应在加载耗材前拒绝 VECTOR + 非 SVG 输入。"""
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        ctx.update(
            {
                "image_path": "/tmp/input.png",
                "modeling_mode": ModelingMode.VECTOR,
                "material_source": "material_archive",
                "selected_materials": ["fake/material"],
            }
        )

        with patch(
            "core.pipeline.s01_input_validation._apply_material_archive_branch",
        ) as apply_material_archive_branch:
            result = run(ctx)

        assert "Vector Native mode requires SVG files" in result["error"]
        apply_material_archive_branch.assert_not_called()

    @pytest.mark.parametrize("height_mode", ["color", "heightmap"])
    def test_svg_vector_relief_stays_on_native_vector_pipeline(
        self,
        height_mode,
    ):
        """SVG relief must preserve native vector geometry instead of voxelizing it."""
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        ctx.update(
            image_path="/tmp/test.svg",
            modeling_mode=ModelingMode.VECTOR,
            enable_relief=True,
            height_mode=height_mode,
        )

        result = run(ctx)

        assert result["is_svg_vector"] is True
        assert result["modeling_mode"] == ModelingMode.VECTOR
        assert "svg_vector_relief_fallback" not in result

    def test_five_color_translucent_svg_vector_falls_back_to_high_fidelity(self, tmp_path):
        """5-Color Extended native vector cannot preserve SVG opacity stacking."""
        from core.pipeline.s01_input_validation import run

        svg_path = tmp_path / "translucent-line.svg"
        svg_path.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                '<rect x="0" y="0" width="100" height="100" fill="#ff0000"/>'
                '<path d="M0 50 L100 50" stroke="#0000ff" '
                'stroke-opacity="0.5" stroke-width="20" fill="none"/>'
                "</svg>"
            ),
            encoding="utf-8",
        )

        ctx = self._make_valid_ctx()
        ctx["image_path"] = str(svg_path)
        ctx["modeling_mode"] = ModelingMode.VECTOR
        ctx["color_mode"] = "5-Color Extended"
        result = run(ctx)

        assert result["is_svg_vector"] is False
        assert result["modeling_mode"] == ModelingMode.HIGH_FIDELITY
        assert result["svg_vector_opacity_fallback"] is True

    def test_five_color_opaque_svg_vector_stays_native(self, tmp_path):
        """Opaque 5-Color Extended SVGs should keep the native vector path."""
        from core.pipeline.s01_input_validation import run

        svg_path = tmp_path / "opaque.svg"
        svg_path.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                '<rect x="0" y="0" width="100" height="100" fill="#ff0000"/>'
                "</svg>"
            ),
            encoding="utf-8",
        )

        ctx = self._make_valid_ctx()
        ctx["image_path"] = str(svg_path)
        ctx["modeling_mode"] = ModelingMode.VECTOR
        ctx["color_mode"] = "5-Color Extended"
        result = run(ctx)

        assert result["is_svg_vector"] is True
        assert result["modeling_mode"] == ModelingMode.VECTOR
        assert "svg_vector_opacity_fallback" not in result

    def test_five_color_unused_stylesheet_opacity_stays_native(self, tmp_path):
        """Unused stylesheet opacity must not downgrade an opaque SVG."""
        from core.pipeline.s01_input_validation import run

        svg_path = tmp_path / "unused-style-opacity.svg"
        svg_path.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                "<style>.unused{opacity:.5}</style>"
                '<rect x="0" y="0" width="100" height="100" fill="#ff0000"/>'
                "</svg>"
            ),
            encoding="utf-8",
        )

        ctx = self._make_valid_ctx()
        ctx["image_path"] = str(svg_path)
        ctx["modeling_mode"] = ModelingMode.VECTOR
        ctx["color_mode"] = "5-Color Extended"
        result = run(ctx)

        assert result["is_svg_vector"] is True
        assert result["modeling_mode"] == ModelingMode.VECTOR
        assert "svg_vector_opacity_fallback" not in result

    def test_five_color_matching_stylesheet_opacity_falls_back(self, tmp_path):
        """Stylesheet opacity should still downgrade when it matches an element."""
        from core.pipeline.s01_input_validation import run

        svg_path = tmp_path / "matching-style-opacity.svg"
        svg_path.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                "<style>.line{stroke-opacity:.5}</style>"
                '<rect x="0" y="0" width="100" height="100" fill="#ff0000"/>'
                '<path class="line" d="M0 50 L100 50" stroke="#0000ff" '
                'stroke-width="20" fill="none"/>'
                "</svg>"
            ),
            encoding="utf-8",
        )

        ctx = self._make_valid_ctx()
        ctx["image_path"] = str(svg_path)
        ctx["modeling_mode"] = ModelingMode.VECTOR
        ctx["color_mode"] = "5-Color Extended"
        result = run(ctx)

        assert result["is_svg_vector"] is False
        assert result["modeling_mode"] == ModelingMode.HIGH_FIDELITY
        assert result["svg_vector_opacity_fallback"] is True

    @staticmethod
    def _material(name: str, rgb: tuple[int, int, int]) -> MaterialParams:
        return MaterialParams(
            name=name,
            directory_name=name,
            E=np.asarray(rgb, dtype=float) / 255.0,
            k=np.ones(3),
            C0_white=np.ones(3),
            estimated_rgb=np.asarray(rgb, dtype=np.uint8),
        )

    def test_material_archive_svg_vector_mode_enters_native_vector_branch(self):
        """Material archives preserve the native SVG/vector route.
        耗材档案保留原生 SVG/矢量处理路径。
        """
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        ctx.update(
            image_path="/tmp/test.svg",
            modeling_mode=ModelingMode.VECTOR,
            material_source="material_archive",
            selected_materials=["fake/material"],
        )
        materials = [self._material("Material A", (255, 0, 0))]
        with patch("core.pipeline._input_validation_common.load_materials", return_value=materials):
            result = run(ctx)

        assert result["is_svg_vector"] is True
        assert result["slot_names"] == ["Material A"]
        assert result["preview_colors"] == {0: [255, 0, 0, 255]}

    @pytest.mark.parametrize(("explicit_backing", "expected_backing"), [(None, 1), (0, 0)])
    def test_material_archive_resolves_inferred_or_explicit_backing(
        self, explicit_backing: int | None, expected_backing: int,
    ):
        """White is inferred as the base channel while explicit backing is retained.
        自动识别白色底层通道，同时保留用户明确选择的底板通道。
        """
        from core.pipeline.s01_input_validation import run

        ctx = self._make_valid_ctx()
        ctx["material_source"] = "material_archive"
        ctx["selected_materials"] = ["PLA Green", "PLA White"]
        if explicit_backing is not None:
            ctx["backing_color_id"] = explicit_backing
            ctx["material_backing_material_index"] = explicit_backing
        materials = [
            self._material("PLA Green", (0, 180, 0)),
            self._material("PLA White", (248, 248, 245)),
        ]
        with patch("core.pipeline._input_validation_common.load_materials", return_value=materials):
            result = run(ctx)

        assert result["material_base_channel_idx"] == 1
        assert result["backing_color_id"] == expected_backing

    def test_empty_dict_raises_key_error(self):
        """空 dict 应抛出 KeyError。"""
        from core.pipeline.s01_input_validation import run

        with pytest.raises(KeyError):
            run({})

    def test_npz_runtime_lut_uses_metadata_palette_slots(self):
        """legacy_multi 的 .npz 运行时 LUT 应使用 metadata palette 作为材料槽。"""
        from core.pipeline.s01_input_validation import run

        palette = [
            PaletteEntry("White", "PLA", "#FFFFFF"),
            PaletteEntry("Red", "PLA", "#DC143C"),
            PaletteEntry("Yellow", "PLA", "#FFE600"),
            PaletteEntry("Blue", "PLA", "#0064F0"),
            PaletteEntry("Cyan", "PLA", "#0086D6"),
            PaletteEntry("Magenta", "PLA", "#EC008C"),
            PaletteEntry("Black", "PLA", "#000000"),
            PaletteEntry("Green", "PLA", "#00AE42"),
        ]
        metadata = LUTMetadata(
            palette=palette,
            color_mode="Merged",
            max_color_layers=5,
            layer_height_mm=0.08,
        )
        ctx = self._make_valid_ctx()
        ctx["lut_path"] = "/tmp/legacy_multi_runtime.npz"
        ctx["color_mode"] = "4-Color (RYBW)"

        with patch(
            "core.pipeline.s01_input_validation.LUTManager.load_lut_with_metadata",
            return_value=(np.zeros((1, 3), dtype=np.uint8), np.zeros((1, 5), dtype=np.int32), metadata),
        ):
            result = run(ctx)

        assert result["slot_names"] == [
            "White",
            "Red",
            "Yellow",
            "Blue",
            "Cyan",
            "Magenta",
            "Black",
            "Green",
        ]
        assert len(result["preview_colors"]) == 8
        assert result["color_layers"] == 5
        assert result["layer_height_mm"] == 0.08


# ===========================================================================
# S03 — s03_color_replacement 单元测试
# ===========================================================================


class TestS03ColorReplacement:
    """S03 颜色替换步骤的单元测试。"""

    def _make_valid_ctx(self) -> dict:
        """构造 S03 的最小有效 PipelineContext。"""
        h, w = 4, 4
        matched_rgb = np.full((h, w, 3), [128, 64, 32], dtype=np.uint8)
        material_matrix = np.zeros((h, w, 5), dtype=int)
        mask_solid = np.ones((h, w), dtype=bool)

        processor = MagicMock()
        processor._rgb_to_lab = MagicMock(return_value=np.array([[50.0, 0.0, 0.0]]))
        processor.kdtree = MagicMock()
        processor.kdtree.query = MagicMock(return_value=(np.array([0.0]), np.array([0])))
        processor.ref_stacks = np.zeros((10, 5), dtype=int)
        processor.lut_rgb = np.zeros((10, 3), dtype=np.uint8)

        return {
            "matched_rgb": matched_rgb,
            "material_matrix": material_matrix,
            "mask_solid": mask_solid,
            "processor": processor,
            "color_replacements": None,
            "replacement_regions": None,
            "matched_rgb_path": None,
        }

    def test_no_replacement_preserves_matched_rgb(self):
        """无替换时 matched_rgb 应保持不变。"""
        from core.pipeline.s03_color_replacement import run

        ctx = self._make_valid_ctx()
        original_rgb = ctx["matched_rgb"].copy()
        result = run(ctx)

        np.testing.assert_array_equal(result["matched_rgb"], original_rgb)

    def test_no_replacement_preserves_material_matrix(self):
        """无替换时 material_matrix 应保持不变。"""
        from core.pipeline.s03_color_replacement import run

        ctx = self._make_valid_ctx()
        original_mat = ctx["material_matrix"].copy()
        result = run(ctx)

        np.testing.assert_array_equal(result["material_matrix"], original_mat)

    def test_reused_preview_loads_immutable_height_identity_path(self, tmp_path):
        """S03 must load source-height identities independently of display RGB."""
        from core.pipeline.s03_color_replacement import run

        ctx = self._make_valid_ctx()
        ctx["matched_rgb"][:] = [244, 100, 41]
        height_identity = np.empty_like(ctx["matched_rgb"])
        height_identity[:, :2] = [190, 230, 248]
        height_identity[:, 2:] = [17, 34, 51]
        identity_path = tmp_path / "height_identity_rgb.npy"
        np.save(identity_path, height_identity)
        ctx["height_identity_rgb_path"] = str(identity_path)

        result = run(ctx)

        np.testing.assert_array_equal(result["matched_rgb"], ctx["matched_rgb"])
        np.testing.assert_array_equal(
            result["height_identity_rgb"], height_identity
        )

    def test_legacy_matched_path_becomes_default_height_identity(self, tmp_path):
        """Old callers without the new keyword inherit the final cached RGB."""
        from core.pipeline.s03_color_replacement import run

        ctx = self._make_valid_ctx()
        cached_matched = np.full_like(ctx["matched_rgb"], [12, 34, 56])
        matched_path = tmp_path / "cached_matched_rgb.npy"
        np.save(matched_path, cached_matched)
        ctx["matched_rgb_path"] = str(matched_path)

        result = run(ctx)

        np.testing.assert_array_equal(result["matched_rgb"], cached_matched)
        np.testing.assert_array_equal(
            result["height_identity_rgb"], cached_matched
        )

    def test_dimension_change_projects_only_preview_edit_deltas(self, tmp_path):
        """Fresh-size raster analysis stays authoritative outside edited pixels."""

        from core.pipeline.s03_color_replacement import run

        ctx = self._make_valid_ctx()
        fresh_rgb = np.full((4, 4, 3), [80, 90, 100], dtype=np.uint8)
        fresh_material = np.full((4, 4, 5), 3, dtype=np.int16)
        ctx["matched_rgb"] = fresh_rgb.copy()
        ctx["material_matrix"] = fresh_material.copy()

        pristine_rgb = np.zeros((2, 2, 3), dtype=np.uint8)
        edited_rgb = pristine_rgb.copy()
        edited_rgb[0, 0] = [220, 30, 40]
        pristine_material = np.zeros((2, 2, 5), dtype=np.int16)
        edited_material = pristine_material.copy()
        edited_material[0, 0] = [1, 1, 1, 1, 1]
        source_solid = np.ones((2, 2), dtype=bool)

        paths = {}
        for name, value in (
            ("matched_rgb", edited_rgb),
            ("original_matched_rgb", pristine_rgb),
            ("material_matrix", edited_material),
            ("original_material_matrix", pristine_material),
            ("mask_solid", source_solid),
        ):
            path = tmp_path / f"{name}.npy"
            np.save(path, value)
            paths[name] = str(path)
        ctx.update(
            {
                "matched_rgb_path": paths["matched_rgb"],
                "original_matched_rgb_path": paths["original_matched_rgb"],
                "material_matrix_path": paths["material_matrix"],
                "original_material_matrix_path": paths[
                    "original_material_matrix"
                ],
                "mask_solid_path": paths["mask_solid"],
                "edit_projection": {
                    "mode": "delta",
                    "source_shape": [2, 2],
                },
            }
        )

        result = run(ctx)

        expected_rgb = fresh_rgb.copy()
        expected_rgb[:2, :2] = [220, 30, 40]
        np.testing.assert_array_equal(result["matched_rgb"], expected_rgb)
        expected_material = fresh_material.copy()
        expected_material[:2, :2] = [1, 1, 1, 1, 1]
        np.testing.assert_array_equal(
            result["material_matrix"], expected_material
        )
        # Display edits never redefine relief height identity.
        np.testing.assert_array_equal(result["height_identity_rgb"], fresh_rgb)

    def test_dimension_change_fails_closed_when_pristine_artifact_disappears(
        self,
        tmp_path,
    ) -> None:
        """Required edit replay cannot silently fall back to stale or no edits."""

        from core.errors import CachedPreviewAnalysisError
        from core.pipeline.s03_color_replacement import run

        ctx = self._make_valid_ctx()
        edited_path = tmp_path / "matched.npy"
        matrix_path = tmp_path / "material.npy"
        pristine_matrix_path = tmp_path / "original-material.npy"
        mask_path = tmp_path / "mask.npy"
        np.save(edited_path, np.zeros((2, 2, 3), dtype=np.uint8))
        np.save(matrix_path, np.zeros((2, 2, 5), dtype=np.int16))
        np.save(pristine_matrix_path, np.zeros((2, 2, 5), dtype=np.int16))
        np.save(mask_path, np.ones((2, 2), dtype=bool))
        ctx.update(
            {
                "matched_rgb_path": str(edited_path),
                "original_matched_rgb_path": str(tmp_path / "missing.npy"),
                "material_matrix_path": str(matrix_path),
                "original_material_matrix_path": str(pristine_matrix_path),
                "mask_solid_path": str(mask_path),
                "edit_projection": {
                    "mode": "delta",
                    "source_shape": [2, 2],
                },
            }
        )

        with pytest.raises(CachedPreviewAnalysisError):
            run(ctx)

    def test_dimension_change_projects_recipe_override_footprint(self, tmp_path):
        """Recipe masks use the same normalized grid as colour-edit deltas."""

        import pickle

        from core.pipeline.s03_color_replacement import run

        ctx = self._make_valid_ctx()
        ctx["matched_rgb"] = np.full((4, 4, 3), 80, dtype=np.uint8)
        ctx["material_matrix"] = np.zeros((4, 4, 5), dtype=np.int16)
        source_rgb = np.zeros((2, 2, 3), dtype=np.uint8)
        source_material = np.zeros((2, 2, 5), dtype=np.int16)
        source_solid = np.ones((2, 2), dtype=bool)
        paths = {}
        for name, value in (
            ("matched_rgb", source_rgb),
            ("original_matched_rgb", source_rgb),
            ("material_matrix", source_material),
            ("original_material_matrix", source_material),
            ("mask_solid", source_solid),
        ):
            path = tmp_path / f"recipe-{name}.npy"
            np.save(path, value)
            paths[name] = str(path)
        masks_path = tmp_path / "recipe-masks.pkl"
        with masks_path.open("wb") as handle:
            pickle.dump(
                {"region-A": np.array([[True, False], [False, False]])},
                handle,
            )
        ctx.update(
            {
                "matched_rgb_path": paths["matched_rgb"],
                "original_matched_rgb_path": paths["original_matched_rgb"],
                "material_matrix_path": paths["material_matrix"],
                "original_material_matrix_path": paths[
                    "original_material_matrix"
                ],
                "mask_solid_path": paths["mask_solid"],
                "edit_projection": {
                    "mode": "recipe_masks",
                    "source_shape": [2, 2],
                },
                "recipe_overrides": [
                    {
                        "region_id": "region-A",
                        "recipe": [2, 2, 2, 2, 2],
                        "layer_order": "Top2Bottom",
                    }
                ],
                "recipe_override_masks_path": str(masks_path),
                "color_layers": 5,
            }
        )

        result = run(ctx)

        expected = np.zeros((4, 4, 5), dtype=np.int16)
        expected[:2, :2] = 2
        np.testing.assert_array_equal(result["material_matrix"], expected)

    def test_identity_validates_against_final_matched_grid_not_s02_grid(
        self,
        tmp_path,
    ):
        """Matched/identity artifacts may share a valid grid unlike S02 RGB."""
        from core.pipeline.s03_color_replacement import run

        ctx = self._make_valid_ctx()
        ctx["mask_solid"] = np.ones((2, 3), dtype=bool)
        ctx["material_matrix"] = np.zeros((2, 3, 5), dtype=int)
        cached_matched = np.full((2, 3, 3), [244, 100, 41], dtype=np.uint8)
        height_identity = np.empty_like(cached_matched)
        height_identity[:, :1] = [190, 230, 248]
        height_identity[:, 1:] = [17, 34, 51]
        matched_path = tmp_path / "different_grid_matched.npy"
        identity_path = tmp_path / "different_grid_identity.npy"
        np.save(matched_path, cached_matched)
        np.save(identity_path, height_identity)
        ctx["matched_rgb_path"] = str(matched_path)
        ctx["height_identity_rgb_path"] = str(identity_path)

        result = run(ctx)

        np.testing.assert_array_equal(result["matched_rgb"], cached_matched)
        np.testing.assert_array_equal(
            result["height_identity_rgb"], height_identity
        )

    def test_missing_matched_rgb_raises_key_error(self):
        """缺失 matched_rgb 键应抛出 KeyError。"""
        from core.pipeline.s03_color_replacement import run

        ctx = self._make_valid_ctx()
        del ctx["matched_rgb"]
        with pytest.raises(KeyError):
            run(ctx)

    def test_empty_dict_raises_key_error(self):
        """空 dict 应抛出 KeyError。"""
        from core.pipeline.s03_color_replacement import run

        with pytest.raises(KeyError):
            run({})


# ===========================================================================
# S06 — s06_voxel_building 单元测试
# ===========================================================================


class TestS06VoxelBuilding:
    """S06 体素构建步骤的单元测试。"""

    def _make_valid_ctx(self) -> dict:
        """构造 S06 的最小有效 PipelineContext。"""
        h, w = 4, 4
        material_matrix = np.zeros((h, w, 5), dtype=int)
        mask_solid = np.ones((h, w), dtype=bool)
        matched_rgb = np.full((h, w, 3), [128, 64, 32], dtype=np.uint8)

        return {
            "material_matrix": material_matrix,
            "mask_solid": mask_solid,
            "spacer_thick": 1.2,
            "structure_mode": "单面",
            "backing_color_id": 0,
            "color_mode": "4-Color",
            "enable_cloisonne": False,
            "enable_relief": False,
            "color_height_map": None,
            "height_mode": "color",
            "heightmap_path": None,
            "heightmap_max_height": None,
            "matched_rgb": matched_rgb,
            "pixel_scale": 0.1,
        }

    @staticmethod
    def _make_magnet(
        *,
        shape: str,
        thickness_mm: float,
        center_x_mm: float = 0.0,
        center_y_mm: float = 0.0,
        diameter_mm: float | None = None,
        width_mm: float | None = None,
        height_mm: float | None = None,
    ) -> dict:
        return {
            "id": f"magnet-{shape}",
            "shape": shape,
            "preset_key": f"{shape}-preset",
            "diameter_mm": diameter_mm,
            "width_mm": width_mm,
            "height_mm": height_mm,
            "thickness_mm": thickness_mm,
            "center_x_mm": center_x_mm,
            "center_y_mm": center_y_mm,
        }

    def test_valid_input_produces_voxel_matrix(self):
        """有效输入应产生 full_matrix、backing_metadata、total_layers。"""
        from core.pipeline.s06_voxel_building import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        assert "full_matrix" in result
        assert "backing_metadata" in result
        assert "total_layers" in result
        assert isinstance(result["full_matrix"], np.ndarray)
        assert result["full_matrix"].ndim == 3  # (Z, H, W)

    def test_run_uses_stable_height_identity_after_display_color_collision(self):
        """S06 entrypoint must retain distinct source heights after one achieved RGB."""
        from core.pipeline.s06_voxel_building import run

        achieved_rgb = np.array([244, 100, 41], dtype=np.uint8)
        source_low = np.array([190, 230, 248], dtype=np.uint8)
        source_high = np.array([17, 34, 51], dtype=np.uint8)
        ctx = self._make_valid_ctx()
        ctx.update(
            {
                "material_matrix": np.zeros((1, 2, 5), dtype=int),
                "mask_solid": np.ones((1, 2), dtype=bool),
                "matched_rgb": np.array(
                    [[achieved_rgb, achieved_rgb]], dtype=np.uint8
                ),
                "height_identity_rgb": np.array(
                    [[source_low, source_high]], dtype=np.uint8
                ),
                "enable_relief": True,
                "color_height_map": {"bee6f8": 0.48, "112233": 2.0},
            }
        )

        result = run(ctx)

        filled_layers = np.count_nonzero(result["full_matrix"] >= 0, axis=0)
        assert filled_layers[0, 0] == 6
        assert filled_layers[0, 1] == 25
        assert result["backing_metadata"]["max_height_mm"] == pytest.approx(2.0)

    def test_native_reference_sources_use_metadata_base_channel_for_backing_layers(self):
        """原生/参考 LUT 的底板应使用 metadata.base_channel_idx，而不是通用 backing_color_id。"""
        from core.pipeline.s06_voxel_building import run

        ctx = self._make_valid_ctx()
        ctx["backing_color_id"] = 0
        ctx["lut_metadata"] = LUTMetadata(
            palette=[
                PaletteEntry(color="bambugreen", material="PLA Basic"),
                PaletteEntry(color="black", material="PLA Basic"),
                PaletteEntry(color="blue", material="PLA Basic"),
                PaletteEntry(color="cyan", material="PLA Basic"),
                PaletteEntry(color="magenta", material="PLA Basic"),
                PaletteEntry(color="red", material="PLA Basic"),
                PaletteEntry(color="white", material="PLA Basic"),
                PaletteEntry(color="yellow", material="PLA Basic"),
            ],
            base_channel_idx=6,
            extensions={"source_kind": "predictive_package"},
        )

        result = run(ctx)
        backing_start, backing_end = result["backing_metadata"]["backing_z_range"]

        logical_column = np.repeat(result["full_matrix"][:, 0, 0], np.diff(result["voxel_z_edges"]))
        assert logical_column[backing_start: backing_end + 1].tolist() == [6] * (
            backing_end - backing_start + 1
        )

    def test_legacy_sources_keep_explicit_backing_color_id_for_backing_layers(self):
        """经典 LUT 仍应沿用显式 backing_color_id，而不是 metadata.base_channel_idx。"""
        from core.pipeline.s06_voxel_building import run

        ctx = self._make_valid_ctx()
        ctx["backing_color_id"] = 3
        ctx["lut_metadata"] = LUTMetadata(
            palette=[
                PaletteEntry(color="white", material="PLA Basic"),
                PaletteEntry(color="yellow", material="PLA Basic"),
                PaletteEntry(color="red", material="PLA Basic"),
                PaletteEntry(color="blue", material="PLA Basic"),
            ],
            base_channel_idx=0,
            extensions={"source_kind": "legacy_lookup"},
        )

        result = run(ctx)
        backing_start, backing_end = result["backing_metadata"]["backing_z_range"]

        logical_column = np.repeat(result["full_matrix"][:, 0, 0], np.diff(result["voxel_z_edges"]))
        assert logical_column[backing_start: backing_end + 1].tolist() == [3] * (
            backing_end - backing_start + 1
        )

    @pytest.mark.parametrize("source_kind", ["legacy_lookup", "legacy_multi", "predictive_package"])
    @pytest.mark.parametrize("structure_mode", ["Single-sided", "Double-sided"])
    def test_separate_backing_retains_its_mesh_label(self, source_kind, structure_mode):
        from core.pipeline.s06_voxel_building import run

        ctx = self._make_valid_ctx()
        ctx.update(
            structure_mode=structure_mode,
            separate_backing=True,
            backing_color_id=-2,
            separate_backing_color_id=1,
            lut_metadata=LUTMetadata(
                palette=[
                    PaletteEntry(color="Red", material="PLA"),
                    PaletteEntry(color="White", material="PLA"),
                ],
                base_channel_idx=1,
                extensions={"source_kind": source_kind},
            ),
        )

        result = run(ctx)
        backing_start, backing_end = result["backing_metadata"]["backing_z_range"]
        logical_column = np.repeat(result["full_matrix"][:, 0, 0], np.diff(result["voxel_z_edges"]))
        assert np.all(logical_column[backing_start:backing_end + 1] == -2)
        assert np.all(logical_column[:backing_start] == 0)
        assert np.all(logical_column[backing_end + 1:] == 0)

    @pytest.mark.parametrize("structure_mode", ["Single-sided", "Double-sided"])
    def test_pixel_mode_backing_preserves_transparent_pixels(self, structure_mode):
        """Transparent margins and holes must stay empty through every layer."""
        from core.pipeline.s06_voxel_building import run

        h, w = 6, 6
        material_matrix = np.full((h, w, 5), -1, dtype=int)
        material_matrix[2:4, 1:5, :] = 2
        mask_solid = np.zeros((h, w), dtype=bool)
        mask_solid[2:4, 1:5] = True
        mask_solid[2, 2] = False
        material_matrix[~mask_solid] = -1
        ctx = {
            **self._make_valid_ctx(),
            "material_matrix": material_matrix,
            "mask_solid": mask_solid,
            "matched_rgb": np.full((h, w, 3), [128, 64, 32], dtype=np.uint8),
            "backing_color_id": 3,
            "spacer_thick": 0.16,
            "modeling_mode": ModelingMode.PIXEL,
            "structure_mode": structure_mode,
        }

        result = run(ctx)
        backing_start, backing_end = result["backing_metadata"]["backing_z_range"]

        logical_volume = np.repeat(result["full_matrix"], np.diff(result["voxel_z_edges"]), axis=0)
        backing = logical_volume[backing_start: backing_end + 1]
        assert np.all(backing[:, mask_solid] == 3)
        assert np.all(logical_volume[:, ~mask_solid] == -1)
        assert np.all(logical_volume[:backing_start, 0, 0] == -1)
        assert np.all(logical_volume[:backing_start, 2, 1] == 2)

    def test_high_fidelity_backing_stays_on_solid_mask(self):
        """Non-pixel modes keep transparent margins outside the backing footprint."""
        from core.pipeline.s06_voxel_building import run

        h, w = 6, 6
        material_matrix = np.full((h, w, 5), -1, dtype=int)
        material_matrix[2:4, 1:5, :] = 2
        mask_solid = np.zeros((h, w), dtype=bool)
        mask_solid[2:4, 1:5] = True
        ctx = {
            **self._make_valid_ctx(),
            "material_matrix": material_matrix,
            "mask_solid": mask_solid,
            "matched_rgb": np.full((h, w, 3), [128, 64, 32], dtype=np.uint8),
            "backing_color_id": 3,
            "spacer_thick": 0.16,
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
        }

        result = run(ctx)
        backing_start, backing_end = result["backing_metadata"]["backing_z_range"]

        logical_volume = np.repeat(result["full_matrix"], np.diff(result["voxel_z_edges"]), axis=0)
        assert np.all(logical_volume[backing_start: backing_end + 1, 0, 0] == -1)
        assert np.all(logical_volume[backing_start: backing_end + 1, 2, 1] == 3)

    def test_cloisonne_builds_wireframe_without_processor(self):
        """Cloisonne mode must not require ctx["processor"] in material-archive flows."""
        from core.pipeline.s06_voxel_building import run

        h, w = 20, 20
        ctx = self._make_valid_ctx()
        ctx["material_matrix"] = np.zeros((h, w, 5), dtype=int)
        ctx["mask_solid"] = np.ones((h, w), dtype=bool)
        ctx["matched_rgb"] = np.zeros((h, w, 3), dtype=np.uint8)
        ctx["matched_rgb"][:, w // 2 :] = [255, 255, 255]
        ctx["enable_cloisonne"] = True
        ctx["wire_width_mm"] = 0.4
        ctx["wire_height_mm"] = 0.4
        ctx.pop("processor", None)
        ctx.pop("target_w", None)

        result = run(ctx)

        assert result["backing_metadata"]["is_cloisonne"] is True
        assert np.any(result["full_matrix"] == -3)

    def test_missing_material_matrix_raises_key_error(self):
        """缺失 material_matrix 键应抛出 KeyError。"""
        from core.pipeline.s06_voxel_building import run

        ctx = self._make_valid_ctx()
        del ctx["material_matrix"]
        with pytest.raises(KeyError):
            run(ctx)

    def test_missing_mask_solid_raises_key_error(self):
        """缺失 mask_solid 键应抛出 KeyError。"""
        from core.pipeline.s06_voxel_building import run

        ctx = self._make_valid_ctx()
        del ctx["mask_solid"]
        with pytest.raises(KeyError):
            run(ctx)

    def test_empty_dict_raises_key_error(self):
        """空 dict 应抛出 KeyError。"""
        from core.pipeline.s06_voxel_building import run

        with pytest.raises(KeyError):
            run({})

    def test_single_sided_structure(self):
        """单面模式应产生正确的层数。"""
        from core.pipeline.s06_voxel_building import run

        ctx = self._make_valid_ctx()
        ctx["structure_mode"] = "单面"
        result = run(ctx)

        # 单面: optical_layers + spacer_layers
        assert result["total_layers"] > 5  # 至少 5 层光学 + 1 层底板

    def test_double_sided_structure(self):
        """双面模式应产生更多层数。"""
        from core.pipeline.s06_voxel_building import run

        ctx = self._make_valid_ctx()
        ctx["structure_mode"] = "双面"
        result_double = run(ctx)

        ctx2 = self._make_valid_ctx()
        ctx2["structure_mode"] = "单面"
        result_single = run(ctx2)

        assert result_double["total_layers"] > result_single["total_layers"]

    def test_resolve_fridge_cavity_z_range_handles_both_backing_orientations(self):
        """冰箱贴槽位 Z 段应根据底板外侧方向保留 0.4mm 壳层。"""
        from core.pipeline.s06_voxel_building import _resolve_fridge_cavity_z_range

        shell_layers = max(1, int(round(0.4 / PrinterConfig.LAYER_HEIGHT)))
        cavity_layers = 4

        assert _resolve_fridge_cavity_z_range((0, 14), shell_layers, cavity_layers) == (5, 8)
        assert _resolve_fridge_cavity_z_range((5, 19), shell_layers, cavity_layers) == (11, 14)

    def test_centered_fridge_coords_use_pixel_extents_for_silhouette_center(self):
        """实体轮廓中心应基于像素外沿，而不是像素中心索引。"""
        from core.pipeline.s06_voxel_building import (
            _convert_centered_fridge_coords_to_raw_mm,
            _mask_solid_bounds_mm,
        )

        mask_solid = np.ones((7, 7), dtype=bool)

        bounds = _mask_solid_bounds_mm(mask_solid, 0.1)
        center_x_mm, center_y_mm = _convert_centered_fridge_coords_to_raw_mm(mask_solid, 0.1, 0.0, 0.0)

        assert bounds == pytest.approx((0.0, 0.0, 0.7, 0.7))
        assert center_x_mm == pytest.approx(0.35)
        assert center_y_mm == pytest.approx(0.35)

    def test_fridge_quantization_auto_expands_spacer_thick_before_carving(self):
        """当毫米厚度刚好等于磁铁厚度+0.4 时，也必须考虑 0.08mm 层高量化后给 cavity 让位。"""
        from core.pipeline.s06_voxel_building import run

        h = w = 7
        material_matrix = np.stack(
            [np.full((h, w), fill_value=layer_id, dtype=int) for layer_id in range(1, 6)],
            axis=-1,
        )
        ctx = {
            **self._make_valid_ctx(),
            "material_matrix": material_matrix,
            "mask_solid": np.ones((h, w), dtype=bool),
            "matched_rgb": np.full((h, w, 3), [128, 64, 32], dtype=np.uint8),
            "backing_color_id": 7,
            "spacer_thick": 3.4,
            "enable_fridge_magnet": True,
            "fridge_magnets": [
                self._make_magnet(shape="round", diameter_mm=0.28, thickness_mm=3.0),
            ],
        }

        result = run(ctx)
        center_row = center_col = 3

        assert result["spacer_thick"] == pytest.approx(3.44)
        assert result["total_layers"] == 48
        np.testing.assert_array_equal(result["full_matrix"][:5, center_row, center_col], np.array([1, 2, 3, 4, 5]))
        assert np.all(result["full_matrix"][5:43, center_row, center_col] == -1)
        assert np.all(result["full_matrix"][43:48, center_row, center_col] == 7)

    def test_round_fridge_magnet_cavity_only_carves_backing_and_preserves_shell(self):
        """圆形磁铁槽应只在底板内部开盲槽，不得影响光学层或外侧 0.4mm 壳层。"""
        from core.pipeline.s06_voxel_building import run

        h = w = 7
        material_matrix = np.stack(
            [np.full((h, w), fill_value=layer_id, dtype=int) for layer_id in range(1, 6)],
            axis=-1,
        )
        ctx = {
            **self._make_valid_ctx(),
            "material_matrix": material_matrix,
            "mask_solid": np.ones((h, w), dtype=bool),
            "matched_rgb": np.full((h, w, 3), [128, 64, 32], dtype=np.uint8),
            "backing_color_id": 7,
            "spacer_thick": 1.2,
            "enable_fridge_magnet": True,
            "fridge_magnets": [
                self._make_magnet(shape="round", diameter_mm=0.28, thickness_mm=0.32),
            ],
        }

        result = run(ctx)
        center_row = center_col = 3
        optical_slice = result["full_matrix"][:5, center_row, center_col]
        cavity_slice = result["full_matrix"][11:15, center_row, center_col]
        shell_slice = result["full_matrix"][15:20, center_row, center_col]

        np.testing.assert_array_equal(optical_slice, np.array([1, 2, 3, 4, 5]))
        np.testing.assert_array_equal(cavity_slice, np.full(4, -1, dtype=int))
        np.testing.assert_array_equal(shell_slice, np.full(5, 7, dtype=int))

    def test_rect_fridge_magnet_cavity_carves_backing_footprint_without_touching_optical_layers(self):
        """矩形磁铁槽应在底板中形成矩形盲槽，且光学层保持原样。"""
        from core.pipeline.s06_voxel_building import run

        h = w = 9
        material_matrix = np.stack(
            [np.full((h, w), fill_value=layer_id, dtype=int) for layer_id in range(1, 6)],
            axis=-1,
        )
        ctx = {
            **self._make_valid_ctx(),
            "material_matrix": material_matrix,
            "mask_solid": np.ones((h, w), dtype=bool),
            "matched_rgb": np.full((h, w, 3), [128, 64, 32], dtype=np.uint8),
            "backing_color_id": 6,
            "spacer_thick": 1.2,
            "enable_fridge_magnet": True,
            "fridge_magnets": [
                self._make_magnet(shape="rect", width_mm=0.3, height_mm=0.1, thickness_mm=0.24),
            ],
        }

        result = run(ctx)
        cavity_band = result["full_matrix"][12:15]

        assert np.all(cavity_band[:, 4, 3:6] == -1)
        assert np.all(cavity_band[:, 3, 3:6] == 6)
        np.testing.assert_array_equal(result["full_matrix"][:5, 4, 4], np.array([1, 2, 3, 4, 5]))

    def test_fridge_magnet_cavity_preserves_relief_optical_voxels_inside_backing_range(self):
        """浮雕等可变高度底板场景下，即使光学层与底板同材质编号，也不能被磁铁槽擦除。"""
        from core.pipeline.s06_voxel_building import _carve_fridge_magnet_cavities

        full_matrix = np.full((12, 7, 7), -1, dtype=int)
        full_matrix[0:8, 2:5, 2:5] = 7
        backing_z_min_map = np.full((7, 7), -1, dtype=int)
        backing_z_max_map = np.full((7, 7), -1, dtype=int)
        backing_z_min_map[2:5, 2:5] = 0
        backing_z_max_map[2:5, 2:5] = 7
        backing_z_max_map[3, 3] = 4

        carved = _carve_fridge_magnet_cavities(
            full_matrix.copy(),
            mask_solid=np.ones((7, 7), dtype=bool),
            pixel_scale=0.1,
            backing_metadata={
                "backing_color_id": 7,
                "backing_z_range": (0, 7),
                "backing_z_min_map": backing_z_min_map,
                "backing_z_max_map": backing_z_max_map,
            },
            fridge_magnets=[
                self._make_magnet(shape="round", diameter_mm=0.28, thickness_mm=0.24),
            ],
        )

        assert carved[5, 3, 3] == 7
        assert carved[6, 3, 3] == 7
        assert carved[7, 3, 3] == 7
        assert carved[5, 3, 2] == -1
        assert carved[6, 3, 2] == -1

    def test_fridge_magnet_cavity_expands_backing_when_quantized_spacer_is_one_layer_short(self):
        """当量化后的底板仅差 1 层时，应扩展有效底板厚度并继续开槽。"""
        from core.pipeline.s06_voxel_building import run

        h = w = 7
        material_matrix = np.stack(
            [np.full((h, w), fill_value=layer_id, dtype=int) for layer_id in range(1, 6)],
            axis=-1,
        )
        ctx = {
            **self._make_valid_ctx(),
            "material_matrix": material_matrix,
            "mask_solid": np.ones((h, w), dtype=bool),
            "matched_rgb": np.full((h, w, 3), [128, 64, 32], dtype=np.uint8),
            "backing_color_id": 7,
            "spacer_thick": 3.4,
            "enable_fridge_magnet": True,
            "fridge_magnets": [
                self._make_magnet(shape="round", diameter_mm=0.28, thickness_mm=3.0),
            ],
        }

        result = run(ctx)
        center_row = center_col = 3

        assert result["total_layers"] == 48
        np.testing.assert_array_equal(result["full_matrix"][:5, center_row, center_col], np.array([1, 2, 3, 4, 5]))
        np.testing.assert_array_equal(result["full_matrix"][5:43, center_row, center_col], np.full(38, -1, dtype=int))
        np.testing.assert_array_equal(result["full_matrix"][43:48, center_row, center_col], np.full(5, 7, dtype=int))


# ===========================================================================
# S08 — s08_auxiliary_meshes 单元测试
# ===========================================================================


class TestS08AuxiliaryMeshes:
    """S08 auxiliary mesh regression tests."""

    class _FakeMesher:
        def generate_mesh(self, _matrix, mat_id, height_px=None):
            if mat_id != -2:
                return None
            return trimesh.creation.box(extents=(1.0, 1.0, 1.0))

    def test_separate_backing_mesh_uses_selected_backing_color_id(self):
        from core.pipeline.s08_auxiliary_meshes import run

        scene = trimesh.Scene()
        ctx = {
            "scene": scene,
            "valid_slot_names": [],
            "full_matrix": np.full((2, 3, 3), -2, dtype=int),
            "mask_solid": np.ones((3, 3), dtype=bool),
            "matched_rgb": np.zeros((3, 3, 3), dtype=np.uint8),
            "target_h": 3,
            "target_w": 3,
            "pixel_scale": 1.0,
            "total_layers": 2,
            "preview_colors": {
                0: [255, 255, 255, 255],
                1: [0, 255, 255, 255],
            },
            "transform": np.eye(4),
            "mesher": self._FakeMesher(),
            "separate_backing": True,
            "backing_color_id": -2,
            "separate_backing_color_id": 1,
            "backing_metadata": {},
            "enable_cloisonne": False,
            "enable_coating": False,
            "enable_outline": False,
            "free_color_set": None,
            "add_loop": False,
            "loop_info": None,
            "boundary_geometry": None,
        }

        result = run(ctx)

        assert result["valid_slot_names"] == ["Backing"]
        backing = result["scene"].geometry["Backing"]
        assert list(backing.visual.face_colors[0]) == [0, 255, 255, 255]

    @pytest.mark.parametrize("enable_outline", [False, True])
    def test_double_sided_raster_coating_covers_both_outer_faces(
        self,
        enable_outline,
    ):
        from core.export_materials import configure_coating_material
        from core.mesh_generators import HighFidelityMesher
        from core.pipeline.s08_auxiliary_meshes import run

        total_layers = 8
        coating_layers = 2
        layer_height = PrinterConfig.LAYER_HEIGHT
        mask_solid = np.ones((4, 4), dtype=bool)
        ctx = {
            "scene": trimesh.Scene(),
            "valid_slot_names": [],
            "full_matrix": np.zeros((total_layers, 4, 4), dtype=int),
            "mask_solid": mask_solid,
            "matched_rgb": np.zeros((4, 4, 3), dtype=np.uint8),
            "target_h": 4,
            "target_w": 4,
            "pixel_scale": 1.0,
            "total_layers": total_layers,
            "preview_colors": {0: [255, 255, 255, 255]},
            "slot_names": ["White"],
            "material_types": {"White": "PETG"},
            "transform": np.eye(4),
            "mesher": HighFidelityMesher(disable_material_dilation=True),
            "structure_mode": "Double-sided",
            "separate_backing": False,
            "backing_metadata": {},
            "enable_coating": True,
            "coating_height_mm": coating_layers * layer_height,
            "enable_outline": enable_outline,
            "outline_width": 1.0,
            "free_color_set": None,
            "add_loop": False,
            "loop_info": None,
            "boundary_geometry": None,
        }

        # S01 resolves the automatic coating material before S08 consumes it.
        configure_coating_material(ctx)
        result = run(ctx)
        coating = result["scene"].geometry["Coating"]

        assert result["material_types"]["Coating"] == "PETG"
        assert coating.metadata["bambu_material_name"] == "Coating"
        assert len(coating.split(only_watertight=False)) == 2
        assert coating.bounds[0, 2] == pytest.approx(-coating_layers * layer_height)
        assert coating.bounds[1, 2] == pytest.approx(
            (total_layers + coating_layers) * layer_height
        )
        if enable_outline:
            outline = result["scene"].geometry["Outline"]
            bottom_coating, top_coating = sorted(
                coating.split(only_watertight=False),
                key=lambda mesh: mesh.bounds[0, 2],
            )
            # Materials share their boundary faces, never the coating volume.
            assert outline.bounds[0, 2] == pytest.approx(0.0)
            assert outline.bounds[1, 2] == pytest.approx(total_layers * layer_height)
            assert outline.bounds[0, 2] == pytest.approx(bottom_coating.bounds[1, 2])
            assert outline.bounds[1, 2] == pytest.approx(top_coating.bounds[0, 2])
            assert coating.bounds[0, 0] <= outline.bounds[0, 0]
            assert coating.bounds[0, 1] <= outline.bounds[0, 1]
            assert coating.bounds[1, 0] >= outline.bounds[1, 0]
            assert coating.bounds[1, 1] >= outline.bounds[1, 1]

    def test_double_sided_raster_coating_keeps_contact_ranges_for_writer(self):
        """Copy/concatenate must retain point-contact shell ownership."""

        from core.export_materials import configure_coating_material
        from core.mesh_export_parts import (
            get_mesh_export_part_ranges,
            mesh_export_parts_are_conditional,
        )
        from core.mesh_generators import HighFidelityMesher
        from core.pipeline.s08_auxiliary_meshes import run
        from utils import bambu_3mf_writer as writer_module
        from utils.bambu_3mf_writer import BambuStudio3MFWriter

        mask_solid = np.asarray(
            [[True, False], [False, True]],
            dtype=bool,
        )
        total_layers = 4
        ctx = {
            "scene": trimesh.Scene(),
            "valid_slot_names": [],
            "full_matrix": np.zeros((total_layers, 2, 2), dtype=int),
            "mask_solid": mask_solid,
            "matched_rgb": np.zeros((2, 2, 3), dtype=np.uint8),
            "target_h": 2,
            "target_w": 2,
            "pixel_scale": 1.0,
            "total_layers": total_layers,
            "preview_colors": {0: [255, 255, 255, 255]},
            "slot_names": ["White"],
            "material_types": {"White": "PLA"},
            "transform": np.eye(4),
            "mesher": HighFidelityMesher(disable_material_dilation=True),
            "structure_mode": "Double-sided",
            "separate_backing": False,
            "backing_metadata": {},
            "enable_coating": True,
            "coating_height_mm": PrinterConfig.LAYER_HEIGHT,
            "enable_outline": False,
            "free_color_set": None,
            "add_loop": False,
            "loop_info": None,
            "boundary_geometry": None,
        }
        configure_coating_material(ctx)
        result = run(ctx)
        coating = result["scene"].geometry["Coating"]
        ranges = get_mesh_export_part_ranges(coating)
        assert len(ranges) == 4
        assert mesh_export_parts_are_conditional(coating)

        writer = BambuStudio3MFWriter(
            "double-coating-contact.3mf",
            settings={},
            color_mode="4-Color",
            printer_id="bambu-p2s",
            slicer="BambuStudio",
        )
        writer.add_mesh(coating, "Coating", (255, 255, 255))
        assert len(writer.objects) == 1
        entry = writer.objects[0]
        assert len(entry.contact_repair_ranges) == 4
        vertices, faces = writer_module._materialize_n3mf_mesh_view_arrays(
            entry.mesh,
            contact_repair_ranges=entry.contact_repair_ranges,
        )
        assert len(np.unique(vertices, axis=0)) == len(vertices)
        assert len(faces) == len(coating.faces)


# ===========================================================================
# S11 — s11_glb_preview 单元测试
# ===========================================================================


class TestS11GlbPreview:
    """S11 GLB preview regression tests."""

    def test_heightmap_relief_exports_lightweight_segmented_glb(
        self,
        monkeypatch,
        tmp_path,
    ):
        from core.pipeline import s11_glb_preview

        scene = trimesh.Scene()
        mesh = trimesh.creation.box(extents=(1.0, 1.0, 2.0))
        mesh.visual.face_colors = np.tile(
            np.array([255, 0, 0, 255], dtype=np.uint8),
            (len(mesh.faces), 1),
        )
        scene.add_geometry(mesh, node_name="ReliefRed", geom_name="ReliefRed")

        segmented_path = tmp_path / "heightmap-lightweight.glb"

        def _generate_segmented_glb(_cache, *, output_path):
            assert output_path.endswith(".glb")
            segmented_path.write_bytes(b"lightweight segmented glb")
            return str(segmented_path)

        monkeypatch.setattr(s11_glb_preview, "OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr(
            s11_glb_preview,
            "generate_segmented_glb",
            _generate_segmented_glb,
        )
        monkeypatch.setattr(
            scene,
            "export",
            MagicMock(
                side_effect=AssertionError(
                    "print scene must not become preview GLB"
                )
            ),
        )
        ctx = {
            "matched_rgb": np.full((2, 2, 3), [255, 0, 0], dtype=np.uint8),
            "mask_solid": np.ones((2, 2), dtype=bool),
            "pixel_scale": 1.0,
            "image_path": str(tmp_path / "heightmap-source.png"),
            "scene": scene,
            "enable_relief": True,
            "height_mode": "heightmap",
        }

        result = s11_glb_preview.run(ctx)

        glb_path = result["glb_path"]
        assert glb_path is not None
        assert glb_path == str(segmented_path)
        assert segmented_path.read_bytes() == b"lightweight segmented glb"

    @pytest.mark.parametrize(
        "generated_surface_params",
        [
            {"enable_relief": True, "height_mode": "color"},
            {"enable_outline": True},
            {"enable_cloisonne": True},
            {"add_loop": True},
            {"enable_coating": True},
            {"enable_fridge_magnet": True},
        ],
        ids=[
            "color-relief",
            "outline",
            "cloisonne",
            "keychain",
            "coating",
            "fridge-magnet",
        ],
    )
    def test_generated_surface_modes_keep_existing_lightweight_preview(
        self,
        monkeypatch,
        tmp_path,
        generated_surface_params,
    ):
        from core.pipeline import s11_glb_preview

        scene = trimesh.Scene()
        mesh = trimesh.creation.box(extents=(3.0, 2.0, 1.0))
        scene.add_geometry(
            mesh,
            node_name="GeneratedSurface",
            geom_name="GeneratedSurface",
        )

        def _unexpected_segmented_glb(*_args, **_kwargs):
            raise AssertionError("existing lightweight preview must be reused")

        monkeypatch.setattr(s11_glb_preview, "OUTPUT_DIR", str(tmp_path))
        monkeypatch.setattr(
            s11_glb_preview,
            "generate_segmented_glb",
            _unexpected_segmented_glb,
        )
        lightweight_preview_path = tmp_path / "lightweight-preview.glb"
        lightweight_preview_path.write_bytes(b"lightweight preview")
        monkeypatch.setattr(
            scene,
            "export",
            MagicMock(
                side_effect=AssertionError(
                    "print scene must not become preview GLB"
                )
            ),
        )

        ctx = {
            "matched_rgb": np.full((2, 2, 3), [255, 0, 0], dtype=np.uint8),
            "mask_solid": np.ones((2, 2), dtype=bool),
            "pixel_scale": 1.0,
            "image_path": str(tmp_path / "generated-surface-source.png"),
            "scene": scene,
            "preview_glb_path": str(lightweight_preview_path),
            **generated_surface_params,
        }

        result = s11_glb_preview.run(ctx)

        glb_path = result["glb_path"]
        assert glb_path == str(lightweight_preview_path)


# ===========================================================================
# S12 — s12_result_assembly 单元测试
# ===========================================================================


class TestS12ResultAssembly:
    """S12 结果组装步骤的单元测试。"""

    def _make_valid_ctx(self) -> dict:
        """构造 S12 的最小有效 PipelineContext。"""
        return {
            "out_path": "/tmp/output.3mf",
            "glb_path": "/tmp/output.glb",
            "preview_img": None,
            "mode_info": {"mode": ModelingMode.HIGH_FIDELITY},
            "target_w": 100,
            "target_h": 100,
            "loop_info": None,
            "loop_added": False,
            "slot_names": ["White", "Red", "Yellow", "Blue"],
            "heightmap_stats": None,
            "color_recipe_path": None,
            "_hifi_timings": {},
        }

    @patch("core.pipeline.s12_result_assembly.Stats")
    def test_valid_input_produces_result_tuple(self, mock_stats):
        """有效输入应产生 result_tuple。"""
        from core.pipeline.s12_result_assembly import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        assert "result_tuple" in result
        assert isinstance(result["result_tuple"], tuple)
        assert len(result["result_tuple"]) == 5

    @patch("core.pipeline.s12_result_assembly.Stats")
    def test_result_tuple_format(self, mock_stats):
        """result_tuple 应为 (out_path, glb_path, preview_img, msg, recipe_path)。"""
        from core.pipeline.s12_result_assembly import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        out_path, glb_path, preview_img, msg, recipe_path = result["result_tuple"]
        assert out_path == "/tmp/output.3mf"
        assert glb_path == "/tmp/output.glb"
        assert preview_img is None
        assert isinstance(msg, str)
        assert "High-Fidelity" in msg
        assert recipe_path is None

    @patch("core.pipeline.s12_result_assembly.Stats")
    def test_msg_contains_resolution(self, mock_stats):
        """状态消息应包含分辨率信息。"""
        from core.pipeline.s12_result_assembly import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        _, _, _, msg, _ = result["result_tuple"]
        assert "100x100" in msg

    def test_missing_out_path_raises_key_error(self):
        """缺失 out_path 键应抛出 KeyError。"""
        from core.pipeline.s12_result_assembly import run

        ctx = self._make_valid_ctx()
        del ctx["out_path"]
        with pytest.raises(KeyError):
            run(ctx)

    def test_empty_dict_raises_key_error(self):
        """空 dict 应抛出 KeyError。"""
        from core.pipeline.s12_result_assembly import run

        with pytest.raises(KeyError):
            run({})


# ===========================================================================
# P01 — p01_preview_validation 单元测试
# ===========================================================================


class TestP01PreviewValidation:
    """P01 预览输入验证步骤的单元测试。"""

    def _make_valid_ctx(self) -> dict:
        """构造 P01 的最小有效 PipelineContext。"""
        return {
            "image_path": "/tmp/test.png",
            "lut_path": "/tmp/test.npy",
            "modeling_mode": ModelingMode.HIGH_FIDELITY,
            "quantize_colors": 64,
        }

    def test_valid_input_produces_expected_keys(self):
        """有效输入应产生所有声明的输出键。"""
        from core.pipeline.p01_preview_validation import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        assert "actual_lut_path" in result
        assert result["actual_lut_path"] == "/tmp/test.npy"
        assert "modeling_mode" in result
        assert result["modeling_mode"] == ModelingMode.HIGH_FIDELITY
        assert "quantize_colors" in result

    def test_none_image_path_sets_error(self):
        """image_path 为 None 时应设置 error 键。"""
        from core.pipeline.p01_preview_validation import run

        ctx = self._make_valid_ctx()
        ctx["image_path"] = None
        result = run(ctx)

        assert "error" in result

    def test_none_lut_path_sets_error(self):
        """lut_path 为 None 时应设置 error 键。"""
        from core.pipeline.p01_preview_validation import run

        ctx = self._make_valid_ctx()
        ctx["lut_path"] = None
        result = run(ctx)

        assert "error" in result

    def test_missing_image_path_raises_key_error(self):
        """缺失 image_path 键应抛出 KeyError。"""
        from core.pipeline.p01_preview_validation import run

        ctx = self._make_valid_ctx()
        del ctx["image_path"]
        with pytest.raises(KeyError):
            run(ctx)

    def test_quantize_colors_clamped_to_range(self):
        """quantize_colors 应被 clamp 到 [8, 8192] 范围。"""
        from core.pipeline.p01_preview_validation import run

        # 低于下限
        ctx = self._make_valid_ctx()
        ctx["quantize_colors"] = 2
        result = run(ctx)
        assert result["quantize_colors"] >= 8

        # 高于上限
        ctx2 = self._make_valid_ctx()
        ctx2["quantize_colors"] = 10_000
        result2 = run(ctx2)
        assert result2["quantize_colors"] <= 8192

    def test_none_modeling_mode_defaults_to_high_fidelity(self):
        """modeling_mode 为 None 时应默认为 HIGH_FIDELITY。"""
        from core.pipeline.p01_preview_validation import run

        ctx = self._make_valid_ctx()
        ctx["modeling_mode"] = None
        result = run(ctx)

        assert result["modeling_mode"] == ModelingMode.HIGH_FIDELITY

    def test_material_archive_vector_mode_rejects_non_svg_before_material_loading(self):
        """材料预览应在加载耗材前拒绝 VECTOR + 非 SVG 输入。"""
        from core.pipeline.p01_preview_validation import run

        ctx = self._make_valid_ctx()
        ctx.update(
            {
                "image_path": "/tmp/input.png",
                "modeling_mode": ModelingMode.VECTOR,
                "material_source": "material_archive",
                "selected_materials": ["fake/material"],
            }
        )

        with patch(
            "core.pipeline.p01_preview_validation._apply_material_archive_branch",
        ) as apply_material_archive_branch:
            result = run(ctx)

        assert "Vector Native mode requires SVG files" in result["error"]
        apply_material_archive_branch.assert_not_called()

    def test_file_like_object_lut_path(self):
        """file-like 对象的 lut_path 应正确解析。"""
        from core.pipeline.p01_preview_validation import run

        mock_file = MagicMock()
        mock_file.name = "/tmp/uploaded_lut.npy"

        ctx = self._make_valid_ctx()
        ctx["lut_path"] = mock_file
        result = run(ctx)

        assert result["actual_lut_path"] == "/tmp/uploaded_lut.npy"

    def test_five_color_translucent_svg_vector_preview_falls_back_to_high_fidelity(self, tmp_path):
        """Preview must choose the same opacity-safe path as final generation."""
        from core.pipeline.p01_preview_validation import run

        svg_path = tmp_path / "translucent-line.svg"
        svg_path.write_text(
            (
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
                '<rect x="0" y="0" width="100" height="100" fill="#ff0000"/>'
                '<path d="M0 50 L100 50" stroke="#0000ff" '
                'stroke-opacity="0.5" stroke-width="20" fill="none"/>'
                "</svg>"
            ),
            encoding="utf-8",
        )

        ctx = self._make_valid_ctx()
        ctx["image_path"] = str(svg_path)
        ctx["modeling_mode"] = ModelingMode.VECTOR
        ctx["color_mode"] = "5-Color Extended"
        result = run(ctx)

        assert result["modeling_mode"] == ModelingMode.HIGH_FIDELITY
        assert result["svg_vector_opacity_fallback"] is True

    def test_empty_dict_raises_key_error(self):
        """空 dict 应抛出 KeyError。"""
        from core.pipeline.p01_preview_validation import run

        with pytest.raises(KeyError):
            run({})

    def test_npz_runtime_lut_uses_metadata_palette_slots(self):
        """legacy_multi 的 .npz 预览运行时 LUT 应保留 union palette 槽位。"""
        from core.pipeline.p01_preview_validation import run

        palette = [
            PaletteEntry("White", "PLA", "#FFFFFF"),
            PaletteEntry("Red", "PLA", "#DC143C"),
            PaletteEntry("Yellow", "PLA", "#FFE600"),
            PaletteEntry("Blue", "PLA", "#0064F0"),
            PaletteEntry("Cyan", "PLA", "#0086D6"),
            PaletteEntry("Magenta", "PLA", "#EC008C"),
            PaletteEntry("Black", "PLA", "#000000"),
            PaletteEntry("Green", "PLA", "#00AE42"),
        ]
        metadata = LUTMetadata(
            palette=palette,
            color_mode="Merged",
            max_color_layers=5,
            layer_height_mm=0.08,
        )
        ctx = self._make_valid_ctx()
        ctx["lut_path"] = "/tmp/legacy_multi_runtime.npz"
        ctx["color_mode"] = "4-Color (RYBW)"

        with patch(
            "core.pipeline.p01_preview_validation.LUTManager.load_lut_with_metadata",
            return_value=(np.zeros((1, 3), dtype=np.uint8), np.zeros((1, 5), dtype=np.int32), metadata),
        ):
            result = run(ctx)

        assert result["slot_names"] == [
            "White",
            "Red",
            "Yellow",
            "Blue",
            "Cyan",
            "Magenta",
            "Black",
            "Green",
        ]
        assert len(result["preview_colors"]) == 8
        assert result["color_layers"] == 5
        assert result["layer_height_mm"] == 0.08


# ===========================================================================
# P04 — p04_cache_building 单元测试
# ===========================================================================


class TestP04CacheBuilding:
    """P04 预览缓存构建步骤的单元测试。"""

    def _make_valid_ctx(self) -> dict:
        """构造 P04 的最小有效 PipelineContext。"""
        h, w = 4, 4
        return {
            "matched_rgb": np.full((h, w, 3), [128, 64, 32], dtype=np.uint8),
            "material_matrix": np.zeros((h, w, 5), dtype=int),
            "mask_solid": np.ones((h, w), dtype=bool),
            "target_w": w,
            "target_h": h,
            "target_width_mm": 40.0,
            "color_conf": ColorSystem.get("4-Color"),
            "color_mode": "4-Color",
            "quantize_colors": 64,
            "backing_color_id": 0,
            "is_dark": True,
            "lut_metadata": None,
            "debug_data": None,
            "quantized_image": None,
        }

    def test_valid_input_produces_cache(self):
        """有效输入应产生 preview_rgba 和 cache。"""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        assert "preview_rgba" in result
        assert "cache" in result
        assert isinstance(result["cache"], dict)
        assert isinstance(result["preview_rgba"], np.ndarray)

    def test_preview_rgba_shape(self):
        """preview_rgba 应为 (H, W, 4) RGBA 数组。"""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        assert result["preview_rgba"].shape == (4, 4, 4)
        assert result["preview_rgba"].dtype == np.uint8

    def test_cache_contains_required_keys(self):
        """cache 字典应包含必需的键。"""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        cache = result["cache"]
        expected_keys = [
            "target_w",
            "target_h",
            "target_width_mm",
            "mask_solid",
            "material_matrix",
            "matched_rgb",
            "preview_rgba",
            "color_conf",
            "color_mode",
            "quantize_colors",
            "quantized_image",
        ]
        for key in expected_keys:
            assert key in cache, f"cache 缺少键: {key}"

    def test_cache_preserves_explicit_pristine_replacement_artifacts(self):
        """P04 must carry worker-owned reset and height identity arrays."""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()
        original_rgb = np.full_like(ctx["matched_rgb"], [10, 20, 30])
        original_matrix = np.full_like(ctx["material_matrix"], 2)
        ctx["original_matched_rgb"] = original_rgb
        ctx["height_identity_rgb"] = original_rgb
        ctx["original_material_matrix"] = original_matrix
        ctx["matched_rgb"][:] = [40, 50, 60]
        ctx["material_matrix"][:] = 3

        cache = run(ctx)["cache"]

        np.testing.assert_array_equal(cache["matched_rgb"], ctx["matched_rgb"])
        np.testing.assert_array_equal(cache["material_matrix"], ctx["material_matrix"])
        np.testing.assert_array_equal(cache["original_matched_rgb"], original_rgb)
        np.testing.assert_array_equal(cache["height_identity_rgb"], original_rgb)
        np.testing.assert_array_equal(
            cache["original_material_matrix"],
            original_matrix,
        )
        assert cache["original_matched_rgb"] is original_rgb
        assert cache["height_identity_rgb"] is original_rgb
        assert cache["original_material_matrix"] is original_matrix

    def test_cache_aliases_current_arrays_when_preview_has_no_replacements(self):
        """No-remap previews must not allocate duplicate pristine arrays."""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()

        cache = run(ctx)["cache"]

        assert cache["original_matched_rgb"] is cache["matched_rgb"]
        assert cache["height_identity_rgb"] is cache["matched_rgb"]
        assert cache["original_material_matrix"] is cache["material_matrix"]

    def test_pixel_mode_uses_quantize_colors_as_glb_mesh_budget(self):
        """Pixel previews should keep the user's high colour budget in GLB."""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()
        ctx["modeling_mode"] = ModelingMode.PIXEL
        ctx["quantize_colors"] = 256

        cache = run(ctx)["cache"]

        assert cache["modeling_mode"] == ModelingMode.PIXEL
        assert cache["glb_max_meshes"] == 256

    def test_pixel_mode_keeps_transparent_background_in_glb_preview(self):
        """Pixel GLB backing must follow the same silhouette as its colors."""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()
        ctx["modeling_mode"] = ModelingMode.PIXEL
        ctx["mask_solid"] = np.zeros((4, 4), dtype=bool)
        ctx["mask_solid"][1:3, 1:3] = True

        cache = run(ctx)["cache"]

        backing_mask = cache.get("backing_mask", cache["mask_solid"])
        np.testing.assert_array_equal(backing_mask, ctx["mask_solid"])

    def test_high_fidelity_does_not_add_backing_mask_by_default(self):
        """High-fidelity GLB preview keeps backing tied to the visible silhouette."""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()
        ctx["modeling_mode"] = ModelingMode.HIGH_FIDELITY
        ctx["mask_solid"] = np.zeros((4, 4), dtype=bool)
        ctx["mask_solid"][1:3, 1:3] = True

        cache = run(ctx)["cache"]

        assert "backing_mask" not in cache

    @pytest.mark.parametrize("mode", [ModelingMode.PIXEL, ModelingMode.HIGH_FIDELITY])
    @pytest.mark.parametrize("opaque", [False, True])
    def test_exported_glb_backing_matches_alpha_after_cache_round_trip(
        self, tmp_path, mode, opaque
    ):
        """Persisted preview caches must retain the exact backing footprint."""
        from shapely.geometry import Polygon, box
        from shapely.ops import unary_union

        from api.preview_cache_artifacts import (
            externalize_preview_cache_to_artifacts,
            hydrate_preview_cache_for_worker,
        )
        from core.pipeline.p04_cache_building import run
        from core.pipeline.s11_glb_preview import generate_segmented_glb

        ctx = self._make_valid_ctx()
        ctx["modeling_mode"] = mode
        mask = ctx["mask_solid"]
        if not opaque:
            mask[:] = False
            mask[1:4, 1:4] = True
            mask[2, 2] = False
        ctx["material_matrix"][~mask] = -1
        cache = run(ctx)["cache"]
        ref, _ = externalize_preview_cache_to_artifacts(cache, root_dir=tmp_path)
        loaded_cache = hydrate_preview_cache_for_worker(ref)
        output_path = str(tmp_path / "preview.glb")

        assert generate_segmented_glb(loaded_cache, output_path) == output_path

        scene = trimesh.load(output_path, force="scene")
        backing = scene.geometry[scene.graph["backing_plate"][1]]
        top_faces = backing.triangles[backing.face_normals[:, 2] > 0.5]
        actual = unary_union([Polygon(face[:, :2]) for face in top_faces])
        scale = ctx["target_width_mm"] / ctx["target_w"]
        expected = unary_union([
            box(x * scale, (4 - y - 1) * scale, (x + 1) * scale, (4 - y) * scale)
            for y, x in zip(*np.where(mask))
        ])
        assert actual.symmetric_difference(expected).area < 1e-6
        assert backing.volume == pytest.approx(expected.area * PrinterConfig.LAYER_HEIGHT)
        np.testing.assert_array_equal(loaded_cache["mask_solid"], mask)

    def test_high_fidelity_does_not_raise_glb_mesh_budget_by_default(self):
        """High-fidelity mode keeps the default GLB cap unless opted in."""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()
        ctx["modeling_mode"] = ModelingMode.HIGH_FIDELITY
        ctx["quantize_colors"] = 256

        cache = run(ctx)["cache"]

        assert cache["modeling_mode"] == ModelingMode.HIGH_FIDELITY
        assert "glb_max_meshes" not in cache

    def test_high_precision_3d_preview_uses_quantize_colors_as_glb_mesh_budget(self):
        """The advanced 3D preview switch should unlock GLB colours."""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()
        ctx["modeling_mode"] = ModelingMode.HIGH_FIDELITY
        ctx["quantize_colors"] = 256
        ctx["high_precision_3d_preview"] = True

        cache = run(ctx)["cache"]

        assert cache["modeling_mode"] == ModelingMode.HIGH_FIDELITY
        assert cache["glb_max_meshes"] == 256

    def test_missing_matched_rgb_raises_key_error(self):
        """缺失 matched_rgb 键应抛出 KeyError。"""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()
        del ctx["matched_rgb"]
        with pytest.raises(KeyError):
            run(ctx)

    def test_missing_color_conf_raises_key_error(self):
        """缺失 color_conf 键应抛出 KeyError。"""
        from core.pipeline.p04_cache_building import run

        ctx = self._make_valid_ctx()
        del ctx["color_conf"]
        with pytest.raises(KeyError):
            run(ctx)

    def test_empty_dict_raises_key_error(self):
        """空 dict 应抛出 KeyError。"""
        from core.pipeline.p04_cache_building import run

        with pytest.raises(KeyError):
            run({})


# ===========================================================================
# P05 — p05_palette_extraction 单元测试
# ===========================================================================


class TestP05PaletteExtraction:
    """P05 调色板提取步骤的单元测试。"""

    def _make_valid_ctx(self) -> dict:
        """构造 P05 的最小有效 PipelineContext。"""
        h, w = 4, 4
        matched_rgb = np.full((h, w, 3), [128, 64, 32], dtype=np.uint8)
        mask_solid = np.ones((h, w), dtype=bool)

        cache = {
            "matched_rgb": matched_rgb,
            "mask_solid": mask_solid,
        }
        return {"cache": cache}

    def test_valid_input_adds_color_palette(self):
        """有效输入应在 cache 中添加 color_palette 键。"""
        from core.pipeline.p05_palette_extraction import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        assert "color_palette" in result["cache"]
        assert isinstance(result["cache"]["color_palette"], list)

    def test_single_color_palette(self):
        """单色图像应提取出 1 个调色板条目。"""
        from core.pipeline.p05_palette_extraction import run

        ctx = self._make_valid_ctx()
        result = run(ctx)

        palette = result["cache"]["color_palette"]
        assert len(palette) == 1
        assert palette[0]["color"] == (128, 64, 32)
        assert palette[0]["percentage"] == 100.0

    def test_missing_cache_raises_key_error(self):
        """缺失 cache 键应抛出 KeyError。"""
        from core.pipeline.p05_palette_extraction import run

        with pytest.raises(KeyError):
            run({})

    def test_cache_missing_matched_rgb_returns_empty_palette(self):
        """cache 中缺失 matched_rgb 时 extract_color_palette 返回空列表。"""
        from core.pipeline.p05_palette_extraction import run

        ctx = {"cache": {"mask_solid": np.ones((4, 4), dtype=bool)}}
        result = run(ctx)
        # extract_color_palette 使用 .get() 访问，缺失时返回空列表
        assert result["cache"]["color_palette"] == []

    def test_empty_dict_raises_key_error(self):
        """空 dict 应抛出 KeyError。"""
        from core.pipeline.p05_palette_extraction import run

        with pytest.raises(KeyError):
            run({})

    def test_multi_color_palette(self):
        """多色图像应提取出多个调色板条目。"""
        from core.pipeline.p05_palette_extraction import run

        h, w = 4, 4
        matched_rgb = np.zeros((h, w, 3), dtype=np.uint8)
        # 上半部分红色，下半部分蓝色
        matched_rgb[:2, :] = [255, 0, 0]
        matched_rgb[2:, :] = [0, 0, 255]
        mask_solid = np.ones((h, w), dtype=bool)

        ctx = {"cache": {"matched_rgb": matched_rgb, "mask_solid": mask_solid}}
        result = run(ctx)

        palette = result["cache"]["color_palette"]
        assert len(palette) == 2
        # 两种颜色各占 50%
        for entry in palette:
            assert entry["percentage"] == 50.0

    def test_palette_extraction_avoids_axis_row_unique(self, monkeypatch):
        """调色板提取不应对 RGB 行调用 np.unique(axis=0)。"""
        from core.pipeline import pipeline_utils
        from core.pipeline.p05_palette_extraction import run

        original_unique = pipeline_utils.np.unique

        def unique_spy(*args, **kwargs):
            if kwargs.get("axis") == 0:
                raise AssertionError("row-wise np.unique is too slow for preview palettes")
            return original_unique(*args, **kwargs)

        monkeypatch.setattr(pipeline_utils.np, "unique", unique_spy)

        h, w = 8, 8
        matched_rgb = np.zeros((h, w, 3), dtype=np.uint8)
        matched_rgb[:4, :] = [255, 0, 0]
        matched_rgb[4:, :] = [0, 0, 255]
        mask_solid = np.ones((h, w), dtype=bool)

        result = run({"cache": {"matched_rgb": matched_rgb, "mask_solid": mask_solid}})

        assert [entry["count"] for entry in result["cache"]["color_palette"]] == [32, 32]
