"""Pipeline regressions for dynamic material effective-layer selection.

动态耗材有效层数在 P03/P04 边界上的回归测试。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from config import ModelingMode
from core.material_color_solver import DEFAULT_LAYER_HEIGHT_MM, MaterialParams
from core.material_dynamic_solver import (
    DynamicMaterialCandidateError,
    DynamicMaterialColorMatch,
    DynamicMaterialLayerOption,
    DynamicMaterialSolveResult,
)
from core.pipeline.p03_core_processing import _run_material_archive_branch


def _material(name: str, rgb: tuple[int, int, int]) -> MaterialParams:
    estimated = np.asarray(rgb, dtype=np.uint8)
    emission = estimated.astype(np.float64) / 255.0
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=emission,
        k=np.full(3, 2.0, dtype=np.float64),
        C0_white=np.ones(3, dtype=np.float64),
        estimated_rgb=estimated,
    )


MATERIALS = [
    _material("Backing", (245, 245, 245)),
    _material("Red", (220, 30, 30)),
    _material("Blue", (30, 30, 220)),
]


def _write_rgba(path: Path, rgba: np.ndarray) -> Path:
    Image.fromarray(np.asarray(rgba, dtype=np.uint8), mode="RGBA").save(path)
    return path


def _base_ctx(image_path: Path) -> dict:
    return {
        "image_path": str(image_path),
        "target_width_mm": 0.2,
        "modeling_mode": ModelingMode.PIXEL,
        "quantize_colors": 8,
        "_material_params": MATERIALS,
        "color_layers": 6,
        "layer_height_mm": DEFAULT_LAYER_HEIGHT_MM,
        "material_substrate": "white",
        "material_source": "material_archive",
        "material_base_channel_idx": 2,
        "material_backing_material_index": 0,
        "enable_cleanup": False,
    }


def _option(
    cap: int,
    actual_count: int,
    matched: tuple[int, int, int],
    actual_bottom_to_top: tuple[int, ...],
    print_bottom_to_top: tuple[int, ...],
    delta_e00: float,
) -> DynamicMaterialLayerOption:
    return DynamicMaterialLayerOption(
        max_effective_layer_count=cap,
        actual_layer_count=actual_count,
        matched_srgb=matched,
        actual_recipe_bottom_to_top=actual_bottom_to_top,
        print_recipe_bottom_to_top=print_bottom_to_top,
        delta_e00=delta_e00,
    )


def _match(
    target: tuple[int, int, int],
    options: tuple[DynamicMaterialLayerOption, ...],
    *,
    selected_index: int,
    fixed_max: float,
) -> DynamicMaterialColorMatch:
    selected = options[selected_index]
    best = options[-1]
    return DynamicMaterialColorMatch(
        target_srgb=target,
        selected=selected,
        best_range=best,
        fixed_max_delta_e00=fixed_max,
        delta_e00_sacrifice=selected.delta_e00 - best.delta_e00,
        layer_cap_options=options,
    )


def _dynamic_result(backing_index: int = 0) -> DynamicMaterialSolveResult:
    first_options = (
        _option(
            5,
            5,
            (11, 21, 31),
            (1, 1, 2, 1, 2),
            (backing_index, backing_index, 1, 1, 2, 1, 2),
            3.0,
        ),
        _option(
            6,
            5,
            (12, 22, 32),
            (1, 1, 2, 1, 2),
            (backing_index, backing_index, 1, 1, 2, 1, 2),
            2.0,
        ),
        _option(7, 7, (13, 23, 33), (1, 2, 2, 1, 1, 2, 1), (1, 2, 2, 1, 1, 2, 1), 1.0),
    )
    second_options = (
        _option(
            5,
            5,
            (201, 211, 221),
            (2, 2, 1, 2, 1),
            (backing_index, backing_index, 2, 2, 1, 2, 1),
            7.0,
        ),
        _option(6, 6, (202, 212, 222), (1, 1, 2, 2, 1, 2), (backing_index, 1, 1, 2, 2, 1, 2), 5.0),
        _option(7, 7, (203, 213, 223), (2, 1, 1, 2, 2, 1, 2), (2, 1, 1, 2, 2, 1, 2), 3.0),
    )
    return DynamicMaterialSolveResult(
        matches=(
            _match((10, 20, 30), first_options, selected_index=0, fixed_max=1.25),
            _match((200, 210, 220), second_options, selected_index=2, fixed_max=3.25),
        ),
        engine="numba",
        candidate_count_before_dedup=120,
        candidate_count_after_dedup=90,
        layer_counts=(5, 6, 7),
    )


def _enable_dynamic(ctx: dict, *, maximum: int = 7) -> None:
    ctx.update(
        {
            "material_dynamic_layer_count_enabled": True,
            "material_min_layer_count": 5,
            "material_max_layer_count": maximum,
            "material_delta_e00_tolerance": 0.5,
        }
    )


def test_dynamic_dispatch_maps_mixed_recipes_and_weighted_benefit_curve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rgba = np.asarray(
        [
            [[10, 20, 30, 255], [10, 20, 30, 255]],
            [[10, 20, 30, 255], [200, 210, 220, 255]],
        ],
        dtype=np.uint8,
    )
    ctx = _base_ctx(_write_rgba(tmp_path / "mixed.png", rgba))
    _enable_dynamic(ctx)
    expected = _dynamic_result()
    calls: list[tuple[np.ndarray, object, int]] = []

    def fake_solve(target_srgb, materials, backing_material_index, **kwargs):
        calls.append((np.asarray(target_srgb).copy(), kwargs["config"], backing_material_index))
        return expected

    monkeypatch.setattr(
        "core.material_dynamic_solver.solve_dynamic_material_colors",
        fake_solve,
    )
    monkeypatch.setattr(
        "core.material_lut_provider.load_solver_cache",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("dynamic mode must not load the fixed solver cache")
        ),
    )
    monkeypatch.setattr(
        "core.material_lut_provider.load_solver_runtime",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("P03 must delegate dynamic runtime loading to the solver")
        ),
    )
    monkeypatch.setattr(
        "core.material_lut_synthesis.ensure_not_worse_than_smaller_N",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("dynamic mode must not use the cross-N fallback")
        ),
    )

    result = _run_material_archive_branch(ctx)

    assert len(calls) == 1
    np.testing.assert_array_equal(calls[0][0], [[10, 20, 30], [200, 210, 220]])
    assert calls[0][1].min_layer_count == 5
    assert calls[0][1].max_layer_count == 7
    assert calls[0][1].delta_e00_tolerance == pytest.approx(0.5)
    assert calls[0][2] == 0
    assert result["color_layers"] == 7
    assert result["material_matrix"].shape == (2, 2, 7)
    np.testing.assert_array_equal(result["material_matrix"][0, 0], [2, 1, 2, 1, 1, 0, 0])
    np.testing.assert_array_equal(result["material_matrix"][1, 1], [2, 1, 2, 2, 1, 1, 2])
    np.testing.assert_array_equal(result["matched_rgb"][0, 0], [11, 21, 31])
    np.testing.assert_array_equal(result["matched_rgb"][1, 1], [203, 213, 223])

    info = result["material_dynamic_layer_info"]
    assert info["enabled"] is True
    assert info["engine"] == "numba"
    assert info["candidate_count_before_dedup"] == 120
    assert info["candidate_count_after_dedup"] == 90
    assert [entry["target_srgb"] for entry in info["colors"]] == [
        [10, 20, 30],
        [200, 210, 220],
    ]
    first = info["colors"][0]
    assert first["actual_layer_count"] == 5
    assert first["padding_layer_count"] == 2
    assert first["actual_recipe_top_to_bottom"] == [2, 1, 2, 1, 1]
    assert first["print_recipe_top_to_bottom"] == [2, 1, 2, 1, 1, 0, 0]
    assert "recipe" not in first
    assert first["layer_cap_options"][0] == {
        "max_effective_layer_count": 5,
        "actual_layer_count": 5,
        "matched_srgb": [11, 21, 31],
        "actual_recipe_top_to_bottom": [2, 1, 2, 1, 1],
        "print_recipe_top_to_bottom": [2, 1, 2, 1, 1, 0, 0],
        "delta_e00": 3.0,
    }
    json.dumps(info)
    curve = info["benefit_curve"]
    assert [point["weighted_mean_delta_e00"] for point in curve] == pytest.approx(
        [4.0, 2.75, 1.5]
    )
    assert [point["marginal_delta_e00_reduction"] for point in curve] == pytest.approx(
        [0.0, 1.25, 1.25]
    )
    solver_info = result["material_solver_info"]
    assert solver_info["path"] == "dynamic_exact"
    assert solver_info["layer_count"] == 7
    assert solver_info["dynamic_min_layer_count"] == 5
    assert solver_info["dynamic_max_layer_count"] == 7
    assert solver_info["dynamic_delta_e00_tolerance"] == pytest.approx(0.5)
    assert solver_info["dynamic_engine"] == "numba"


def test_dynamic_cleanup_reweights_benefit_curve_for_final_target_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = [10, 20, 30, 255]
    second = [200, 210, 220, 255]
    rgba = np.asarray(
        [[first] * 3, [first, second, first], [first] * 3],
        dtype=np.uint8,
    )
    ctx = _base_ctx(_write_rgba(tmp_path / "cleanup.png", rgba))
    ctx["target_width_mm"] = 0.3
    ctx["enable_cleanup"] = True
    _enable_dynamic(ctx)
    monkeypatch.setattr(
        "core.material_dynamic_solver.solve_dynamic_material_colors",
        lambda *args, **kwargs: _dynamic_result(),
    )

    result = _run_material_archive_branch(ctx)

    assert "error" not in result, result.get("material_dynamic_layer_error")
    np.testing.assert_array_equal(result["quantized_image"][1, 1], first[:3])
    np.testing.assert_array_equal(
        result["material_matrix"][1, 1],
        result["material_matrix"][0, 0],
    )
    curve = result["material_dynamic_layer_info"]["benefit_curve"]
    assert [point["weighted_mean_delta_e00"] for point in curve] == pytest.approx(
        [3.0, 2.0, 1.0]
    )


def test_dynamic_preview_replay_applies_exact_replacements_and_merges_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rgba = np.asarray(
        [
            [[10, 20, 30, 255], [10, 20, 30, 255]],
            [[10, 20, 30, 255], [200, 210, 220, 255]],
        ],
        dtype=np.uint8,
    )
    ctx = _base_ctx(_write_rgba(tmp_path / "dynamic-replace.png", rgba))
    _enable_dynamic(ctx)
    ctx["replacement_regions"] = [
        {
            "quantized_hex": "#0a141e",
            "matched_hex": "#0b151f",
            "replacement_hex": "#28323c",
        }
    ]
    monkeypatch.setattr(
        "core.material_dynamic_solver.solve_dynamic_material_colors",
        lambda *args, **kwargs: _dynamic_result(),
    )
    merged_info = {
        "enabled": True,
        "colors": [{"target_srgb": [40, 50, 60]}],
        "benefit_curve": [],
    }
    calls: list[dict] = []

    def fake_apply(
        matched_rgb,
        material_matrix,
        mask_solid,
        target_rgb_map,
        replacements,
        materials,
        **kwargs,
    ):
        calls.append(
            {
                "replacements": replacements,
                "dynamic_layer_info": kwargs["dynamic_layer_info"],
                "material_solver_info": kwargs["material_solver_info"],
            }
        )
        updated_rgb = matched_rgb.copy()
        updated_rgb[0, 0] = [44, 55, 66]
        updated_matrix = material_matrix.copy()
        updated_matrix[0, 0] = [1, 2, 1, 0, 2, 0, 0]
        return (
            updated_rgb,
            updated_matrix,
            1,
            merged_info,
            {"dynamic_engine": "numba", "replacement_merge": True},
            np.asarray(target_rgb_map).copy(),
        )

    monkeypatch.setattr(
        "core.pipeline.s03_color_replacement._apply_dynamic_material_archive_color_replacements",
        fake_apply,
    )

    result = _run_material_archive_branch(ctx)

    assert len(calls) == 1
    assert len(calls[0]["replacements"]) == 1
    assert calls[0]["replacements"][0][0] == "#28323c"
    np.testing.assert_array_equal(
        calls[0]["replacements"][0][1], [[True, True], [True, False]],
    )
    assert calls[0]["dynamic_layer_info"]["enabled"] is True
    assert result["material_dynamic_layer_info"] == merged_info
    assert result["material_solver_info"]["replacement_merge"] is True
    np.testing.assert_array_equal(result["matched_rgb"][0, 0], [44, 55, 66])


def test_dynamic_uses_base_channel_when_explicit_backing_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rgba = np.asarray(
        [
            [[10, 20, 30, 255], [10, 20, 30, 255]],
            [[10, 20, 30, 255], [200, 210, 220, 255]],
        ],
        dtype=np.uint8,
    )
    ctx = _base_ctx(_write_rgba(tmp_path / "fallback-backing.png", rgba))
    del ctx["material_backing_material_index"]
    _enable_dynamic(ctx)
    seen: list[int] = []

    def fake_solve(*, backing_material_index, **kwargs):
        seen.append(backing_material_index)
        return _dynamic_result(backing_index=2)

    monkeypatch.setattr(
        "core.material_dynamic_solver.solve_dynamic_material_colors",
        fake_solve,
    )

    result = _run_material_archive_branch(ctx)

    assert seen == [2]
    np.testing.assert_array_equal(
        result["material_matrix"][0, 0],
        [2, 1, 2, 1, 1, 2, 2],
    )


def test_dynamic_transparent_image_is_empty_without_constructing_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rgba = np.zeros((2, 2, 4), dtype=np.uint8)
    ctx = _base_ctx(_write_rgba(tmp_path / "empty.png", rgba))
    _enable_dynamic(ctx, maximum=8)
    monkeypatch.setattr(
        "core.material_dynamic_solver.solve_dynamic_material_colors",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("an empty image must not invoke the dynamic solver")
        ),
    )
    monkeypatch.setattr(
        "core.material_lut_provider.load_solver_cache",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("an empty dynamic image must not load a fixed cache")
        ),
    )

    result = _run_material_archive_branch(ctx)

    assert result["color_layers"] == 8
    assert result["material_matrix"].shape == (2, 2, 8)
    assert np.all(result["material_matrix"] == -1)
    assert result["material_dynamic_layer_info"]["colors"] == []
    assert result["material_dynamic_layer_info"]["benefit_curve"] == []
    assert result["material_dynamic_layer_info"]["engine"] == "none"


def test_dynamic_invalid_backing_index_uses_typed_failure_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rgba = np.full((2, 2, 4), [10, 20, 30, 255], dtype=np.uint8)
    ctx = _base_ctx(_write_rgba(tmp_path / "bad-backing.png", rgba))
    ctx["material_backing_material_index"] = len(MATERIALS)
    _enable_dynamic(ctx)
    monkeypatch.setattr(
        "core.material_dynamic_solver.solve_dynamic_material_colors",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("invalid backing must fail before exact solving")
        ),
    )

    result = _run_material_archive_branch(ctx)

    typed = result["material_dynamic_layer_error"]
    assert typed["error_type"] == "DynamicMaterialCandidateError"
    assert typed["layer_count"] == 7
    assert typed["phase"] == "backing_material"
    assert "material_matrix" not in result


def test_dynamic_candidate_failure_keeps_typed_metadata_without_partial_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rgba = np.full((2, 2, 4), [10, 20, 30, 255], dtype=np.uint8)
    ctx = _base_ctx(_write_rgba(tmp_path / "failure.png", rgba))
    _enable_dynamic(ctx)
    failure = DynamicMaterialCandidateError(
        "runtime missing",
        layer_count=6,
        phase="runtime_load",
    )
    monkeypatch.setattr(
        "core.material_dynamic_solver.solve_dynamic_material_colors",
        lambda *args, **kwargs: (_ for _ in ()).throw(failure),
    )
    monkeypatch.setattr(
        "core.material_lut_provider.load_solver_cache",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("dynamic mode must not load the fixed solver cache")
        ),
    )

    result = _run_material_archive_branch(ctx)

    assert "error" in result
    typed = result["material_dynamic_layer_error"]
    assert typed["exception"] is failure
    assert typed["error_type"] == "DynamicMaterialCandidateError"
    assert typed["layer_count"] == 6
    assert typed["phase"] == "runtime_load"
    assert "matched_rgb" not in result
    assert "material_matrix" not in result
    assert "material_dynamic_layer_info" not in result
    assert result["color_layers"] == 6


def test_dynamic_cancellation_does_not_publish_partial_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rgba = np.full((2, 2, 4), [10, 20, 30, 255], dtype=np.uint8)
    ctx = _base_ctx(_write_rgba(tmp_path / "cancel.png", rgba))
    _enable_dynamic(ctx)
    monkeypatch.setattr(
        "core.material_dynamic_solver.solve_dynamic_material_colors",
        lambda *args, **kwargs: (_ for _ in ()).throw(asyncio.CancelledError()),
    )

    with pytest.raises(asyncio.CancelledError):
        _run_material_archive_branch(ctx)

    assert "matched_rgb" not in ctx
    assert "material_matrix" not in ctx
    assert "material_dynamic_layer_info" not in ctx
    assert ctx["color_layers"] == 6


def test_p04_preserves_dynamic_and_solver_metadata_unchanged() -> None:
    from core.pipeline.p04_cache_building import run

    h, w = 2, 2
    dynamic_info = {"enabled": True, "colors": [{"actual_layer_count": 5}]}
    solver_info = {"path": "dynamic_exact", "dynamic_engine": "numba"}
    ctx = {
        "matched_rgb": np.zeros((h, w, 3), dtype=np.uint8),
        "material_matrix": np.zeros((h, w, 7), dtype=np.int32),
        "mask_solid": np.ones((h, w), dtype=bool),
        "target_w": w,
        "target_h": h,
        "target_width_mm": 1.0,
        "color_conf": {},
        "color_mode": "4-Color",
        "quantize_colors": 2,
        "material_source": "material_archive",
        "material_solver_info": solver_info,
        "material_dynamic_layer_info": dynamic_info,
    }

    cache = run(ctx)["cache"]

    assert cache["material_solver_info"] is solver_info
    assert cache["material_dynamic_layer_info"] is dynamic_info


class _FixedCache:
    mode = "candidate_hybrid"
    valid_cell_count = 1
    layer_count = 5
    grid_resolution = 64
    palette_hash = "fixed"
    metadata = {"layer_count": 5, "grid_resolution": 64}

    def __init__(self) -> None:
        self.lookup_calls = 0

    def lookup(self, targets, materials):
        self.lookup_calls += 1
        count = len(targets)
        return (
            np.broadcast_to([9, 8, 7], (count, 3)).astype(np.uint8),
            np.broadcast_to([0, 1, 2, 1, 2], (count, 5)).astype(np.int32),
            np.zeros(count, dtype=np.float64),
        )


def test_dynamic_flag_false_keeps_fixed_solver_output_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rgba = np.full((2, 2, 4), [10, 20, 30, 255], dtype=np.uint8)
    path = _write_rgba(tmp_path / "fixed.png", rgba)
    cache = _FixedCache()
    monkeypatch.setattr(
        "core.material_lut_provider.load_solver_cache",
        lambda **kwargs: (cache, 64),
    )
    monkeypatch.setattr(
        "core.material_dynamic_solver.solve_dynamic_material_colors",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("fixed mode must not invoke the dynamic solver")
        ),
    )

    legacy = _run_material_archive_branch(_base_ctx(path))
    explicit_ctx = _base_ctx(path)
    explicit_ctx["material_dynamic_layer_count_enabled"] = False
    explicit_ctx["material_min_layer_count"] = "ignored"
    explicit_ctx["material_max_layer_count"] = None
    explicit_ctx["material_delta_e00_tolerance"] = object()
    explicit = _run_material_archive_branch(explicit_ctx)

    assert cache.lookup_calls == 2
    np.testing.assert_array_equal(explicit["matched_rgb"], legacy["matched_rgb"])
    np.testing.assert_array_equal(explicit["material_matrix"], legacy["material_matrix"])
    assert explicit["material_solver_info"]["path"] == legacy["material_solver_info"]["path"]
    assert "material_dynamic_layer_info" not in explicit


def test_dynamic_preview_matrix_reuse_skips_solver_and_preserves_authority_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Puzzle reuse must retain the accepted dynamic matrix without re-solving."""

    max_layers = 7
    matched_rgb = np.asarray(
        [
            [[12, 34, 56], [78, 90, 12]],
            [[34, 56, 78], [90, 12, 34]],
        ],
        dtype=np.uint8,
    )
    mask_solid = np.asarray([[True, True], [True, False]], dtype=bool)
    quantized_image = matched_rgb.copy()
    material_matrix = np.full((2, 2, max_layers), -1, dtype=np.int32)
    material_matrix[0, 0] = [2, 1, 2, 1, 1, 0, 0]
    material_matrix[0, 1] = [1, 2, 1, 2, 1, 0, 0]
    material_matrix[1, 0] = [2, 2, 1, 1, 2, 0, 0]

    paths = {}
    for name, array in {
        "matched_rgb": matched_rgb,
        "mask_solid": mask_solid,
        "quantized_image": quantized_image,
        "material_matrix": material_matrix,
    }.items():
        path = tmp_path / f"{name}.npy"
        np.save(path, array)
        paths[f"{name}_path"] = str(path)

    ctx = _base_ctx(tmp_path / "must-not-be-opened.png")
    _enable_dynamic(ctx, maximum=max_layers)
    ctx.update(paths)
    ctx["reuse_preview_analysis"] = True

    monkeypatch.setattr(
        "core.material_dynamic_solver.solve_dynamic_material_colors",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("preview matrix reuse must not invoke the dynamic solver")
        ),
    )

    result = _run_material_archive_branch(ctx)

    np.testing.assert_array_equal(result["matched_rgb"], matched_rgb)
    np.testing.assert_array_equal(result["mask_solid"], mask_solid)
    np.testing.assert_array_equal(result["quantized_image"], quantized_image)
    np.testing.assert_array_equal(result["material_matrix"], material_matrix)
    assert result["material_matrix"].dtype == np.int32
    assert result["color_layers"] == max_layers
    assert result["preview_matrix_reuse"] is True
    assert result["material_solver_info"]["path"] == "preview_matrix_reuse"
    assert result["material_dynamic_layer_info"]["preview_matrix_reuse"] is True


def test_dynamic_preview_matrix_reuse_rejects_incomplete_assets(
    tmp_path: Path,
) -> None:
    """Incomplete dynamic analysis must fail rather than falling back to a solver."""

    ctx = _base_ctx(tmp_path / "must-not-be-opened.png")
    _enable_dynamic(ctx, maximum=7)
    ctx.update(
        {
            "reuse_preview_analysis": True,
            "matched_rgb_path": str(tmp_path / "matched.npy"),
            "mask_solid_path": str(tmp_path / "mask.npy"),
            "material_matrix_path": str(tmp_path / "matrix.npy"),
        }
    )

    result = _run_material_archive_branch(ctx)

    assert "error" in result
    assert "Re-run preview" in result["error"]
