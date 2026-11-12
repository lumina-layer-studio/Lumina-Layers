"""Unit tests for dynamic catalog preparation and its cache helpers.

动态目录预构建及其缓存辅助函数的单元测试。
"""

from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Callable

import numpy as np
import pytest

import core.material_dynamic_catalog_cache as catalog_cache
import core.material_dynamic_solver as dynamic_solver
import core.material_lut_provider as material_provider
from core.material_gamut_coverage import compute_dynamic_layer_gamut
from core.material_cache_overview import (
    DYNAMIC_CANDIDATE_BUDGET,
    delete_dynamic_layer_cache,
    describe_dynamic_layer_caches,
    prepare_dynamic_layer_cache,
)
from core.material_candidate_cache import (
    MaterialCandidateCacheConfig,
    build_material_candidate_runtime,
    load_material_candidate_runtime,
    save_material_candidate_runtime,
)
from core.material_dynamic_catalog_cache import (
    DynamicCatalogCacheCorruptionError,
    build_dynamic_catalog_cache_key,
    delete_dynamic_candidate_catalog,
    find_dynamic_candidate_catalog_file,
    load_dynamic_candidate_catalog,
    save_dynamic_candidate_catalog,
)
from tests.test_material_dynamic_catalog_cache_unit import (
    _catalog,
    _key,
    _materials,
    _rewrite_npz,
)

_BUDGET = 4096


def _catalog_key(materials, *, backing: int, minimum: int = 5, maximum: int = 6):
    return build_dynamic_catalog_cache_key(
        materials,
        backing_material_index=backing,
        layer_height_mm=0.08,
        substrate="white",
        min_layer_count=minimum,
        max_layer_count=maximum,
        candidate_budget=DYNAMIC_CANDIDATE_BUDGET,
    )


def _load_catalog(materials, tmp_path: Path, *, backing: int):
    return dynamic_solver.load_or_build_persistent_dynamic_catalog(
        materials,
        backing,
        0.08,
        "white",
        dynamic_solver.DynamicMaterialSolveConfig(5, 6, 0.5),
        candidate_budget=DYNAMIC_CANDIDATE_BUDGET,
        cache_root=tmp_path,
    )


def test_padding_corruption_is_detected_by_vectorized_validation(tmp_path: Path) -> None:
    materials = _materials()
    key = _key(materials)
    path = save_dynamic_candidate_catalog(
        _catalog(),
        materials=materials,
        key=key,
        candidate_count_before_dedup=3,
        cache_root=tmp_path,
    )

    def break_padding(payload: dict[str, np.ndarray]) -> None:
        recipes = payload["print_recipes_canonical"].copy()
        recipes[0, 0] = 1 - recipes[0, 0]  # row 0 has 5 layers -> column 0 is padding
        payload["print_recipes_canonical"] = recipes

    _rewrite_npz(path, break_padding)

    with pytest.raises(DynamicCatalogCacheCorruptionError, match="padding"):
        load_dynamic_candidate_catalog(materials=materials, key=key, cache_root=tmp_path)


def test_find_reports_only_built_catalogs_and_delete_removes_them(tmp_path: Path) -> None:
    materials = _materials()
    key = _key(materials)
    assert find_dynamic_candidate_catalog_file(key, cache_root=tmp_path) is None
    assert delete_dynamic_candidate_catalog(key, cache_root=tmp_path) is False

    path = save_dynamic_candidate_catalog(
        _catalog(),
        materials=materials,
        key=key,
        candidate_count_before_dedup=3,
        cache_root=tmp_path,
    )
    assert find_dynamic_candidate_catalog_file(key, cache_root=tmp_path) == path

    assert delete_dynamic_candidate_catalog(key, cache_root=tmp_path) is True
    assert not path.exists()
    assert path.with_suffix(".meta.json").exists()
    assert find_dynamic_candidate_catalog_file(key, cache_root=tmp_path) is None


def test_delete_does_not_orphan_a_builder_already_registered_on_the_same_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = _materials()
    key = _key(materials)
    path = save_dynamic_candidate_catalog(
        _catalog(), materials=materials, key=key,
        candidate_count_before_dedup=3, cache_root=tmp_path,
    )
    registered, resume = Event(), Event()
    original_resolve = catalog_cache._resolve_catalog_record

    def pause_after_registration(*args, **kwargs):
        resolved = original_resolve(*args, **kwargs)
        registered.set()
        assert resume.wait(5)
        return resolved

    monkeypatch.setattr(catalog_cache, "_resolve_catalog_record", pause_after_registration)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            catalog_cache.load_or_build_dynamic_candidate_catalog,
            materials=materials, key=key, builder=lambda: (_catalog(), 3), cache_root=tmp_path,
        )
        try:
            assert registered.wait(5)
            assert delete_dynamic_candidate_catalog(key, cache_root=tmp_path)
        finally:
            resume.set()
        assert future.result(timeout=5).cache_hit is False

    assert find_dynamic_candidate_catalog_file(key, cache_root=tmp_path) == path
    assert load_dynamic_candidate_catalog(materials=materials, key=key, cache_root=tmp_path)
    assert delete_dynamic_candidate_catalog(key, cache_root=tmp_path)
    assert catalog_cache.dynamic_catalog_cache_file_path(key, cache_root=tmp_path) == path


def test_registered_but_unbuilt_record_is_not_reported_as_built(tmp_path: Path) -> None:
    materials = _materials()
    key = _key(materials)
    catalog_cache._resolve_catalog_record(key, tmp_path, register=True)

    assert find_dynamic_candidate_catalog_file(key, cache_root=tmp_path) is None


def test_persist_saves_built_runtime_only_in_the_isolated_folder(tmp_path: Path) -> None:
    materials = _materials()
    isolated = material_provider.dynamic_layer_runtime_root(tmp_path)

    built, _grid = material_provider.load_dynamic_candidate_runtime(
        materials, 5, 0.08, "white",
        candidate_budget=_BUDGET, cache_root=tmp_path, persist=True,
    )

    # Fixed-layer lookups scan the shared folder: nothing may appear there.
    assert load_material_candidate_runtime(
        materials, 5, 0.08, "white", candidate_budget=_BUDGET, cache_root=tmp_path
    ) is None
    saved = load_material_candidate_runtime(
        materials, 5, 0.08, "white", candidate_budget=_BUDGET, cache_root=isolated
    )
    assert saved is not None
    assert np.array_equal(saved.achieved_srgb, built.achieved_srgb)
    assert np.array_equal(saved.candidate_recipes, built.candidate_recipes)


def test_dynamic_loader_prefers_a_manual_smart_cache_in_the_shared_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = _materials()
    manual = build_material_candidate_runtime(
        materials=materials, layer_count=5, layer_height_mm=0.08, substrate="white",
        config=MaterialCandidateCacheConfig.persisted_for_budget(_BUDGET),
    )
    save_material_candidate_runtime(manual, cache_root=tmp_path)
    monkeypatch.setattr(
        material_provider,
        "build_material_candidate_runtime",
        lambda **_kwargs: pytest.fail("a saved smart cache must be reused"),
    )

    loaded, _grid = material_provider.load_dynamic_candidate_runtime(
        materials, 5, 0.08, "white", candidate_budget=_BUDGET, cache_root=tmp_path,
    )

    assert np.array_equal(loaded.candidate_recipes, manual.candidate_recipes)


def test_default_dynamic_runtime_load_does_not_write_to_disk(tmp_path: Path) -> None:
    materials = _materials()
    material_provider.load_dynamic_candidate_runtime(
        materials, 5, 0.08, "white", candidate_budget=_BUDGET, cache_root=tmp_path,
    )

    assert load_material_candidate_runtime(
        materials, 5, 0.08, "white", candidate_budget=_BUDGET, cache_root=tmp_path
    ) is None


def test_persist_failure_is_logged_and_does_not_fail_the_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[dict[str, object]] = []

    def failing_save(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(material_provider, "save_material_candidate_runtime", failing_save)
    monkeypatch.setattr(
        material_provider._log,
        "warning",
        lambda _message, *, extra: warnings.append(extra),
    )

    runtime, _grid = material_provider.load_dynamic_candidate_runtime(
        _materials(), 5, 0.08, "white",
        candidate_budget=_BUDGET, cache_root=tmp_path, persist=True,
    )

    assert runtime.valid_cell_count > 0
    assert len(warnings) == 1
    assert warnings[0]["event"] == "dynamic_layer_runtime_save_failed"
    assert warnings[0]["error_type"] == "OSError"
    assert warnings[0]["layer_count"] == 5


def test_prepared_runtimes_are_reused_when_backing_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = _materials()
    first = prepare_dynamic_layer_cache(materials, 0, 0.08, "white", 5, 6, cache_root=tmp_path)
    assert first.built is True
    assert first.overview.is_ready is True
    assert first.overview.saved_layer_counts == (5, 6)
    assert find_dynamic_candidate_catalog_file(
        _catalog_key(materials, backing=0), cache_root=tmp_path
    ) is not None

    monkeypatch.setattr(
        material_provider,
        "build_material_candidate_runtime",
        lambda **_kwargs: pytest.fail("saved per-layer runtimes must be reused"),
    )
    second = _load_catalog(materials, tmp_path, backing=1)

    assert second.cache_hit is False  # new backing -> new catalog, built from saved runtimes
    padded_rows = second.catalog.minimum_actual_layer_counts < 6
    assert np.all(second.catalog.print_recipes[padded_rows, 0] == 1)


def test_shared_loader_matches_solver_catalog(tmp_path: Path) -> None:
    materials = _materials()
    prepared = _load_catalog(materials, tmp_path, backing=0)

    result = dynamic_solver.solve_dynamic_material_colors(
        np.asarray([[120, 30, 40]], dtype=np.uint8),
        materials,
        backing_material_index=0,
        layer_height_mm=0.08,
        substrate="white",
        config=dynamic_solver.DynamicMaterialSolveConfig(5, 6, 0.5),
        material_candidate_budget=DYNAMIC_CANDIDATE_BUDGET,
        catalog_cache_root=tmp_path,
    )

    assert result.candidate_count_after_dedup == prepared.catalog.score_srgb.shape[0]
    assert result.candidate_count_before_dedup == prepared.candidate_count_before_dedup


def test_prepare_never_changes_fixed_layer_matching(tmp_path: Path) -> None:
    materials = _materials()
    targets = np.random.default_rng(3).integers(0, 256, (300, 3)).astype(np.uint8)

    def fixed_match() -> tuple[np.ndarray, ...]:
        runtime, _grid = material_provider.load_solver_runtime(
            materials, 6, 0.08, "white", cache_root=tmp_path
        )
        return tuple(np.asarray(value) for value in runtime.lookup(targets, materials))

    before = fixed_match()
    prepare_dynamic_layer_cache(materials, 0, 0.08, "white", 5, 6, cache_root=tmp_path)
    after = fixed_match()

    for old, new in zip(before, after, strict=True):
        assert np.array_equal(old, new)
    assert not any(
        load_material_candidate_runtime(
            materials, layers, 0.08, "white",
            candidate_budget=budget, cache_root=tmp_path,
        )
        for layers in (5, 6)
        for budget in material_provider.PERSISTED_RUNTIME_PROBE_BUDGETS
    ), "Prepare must not add anything fixed-layer lookups can find"


def test_delete_removes_prepared_runtimes_but_keeps_manual_smart_caches(tmp_path: Path) -> None:
    materials = _materials()
    manual = build_material_candidate_runtime(
        materials=materials, layer_count=5, layer_height_mm=0.08, substrate="white",
        config=MaterialCandidateCacheConfig.persisted_for_budget(DYNAMIC_CANDIDATE_BUDGET),
    )
    save_material_candidate_runtime(manual, cache_root=tmp_path)
    prepare_dynamic_layer_cache(materials, 0, 0.08, "white", 5, 6, cache_root=tmp_path)

    assert delete_dynamic_layer_cache(materials, 0, 0.08, "white", 5, 6, cache_root=tmp_path)

    overview = describe_dynamic_layer_caches(materials, 0, 0.08, "white", 5, 6, cache_root=tmp_path)
    assert overview.catalog is None
    assert overview.saved_layer_counts == (5,), "only the manual smart cache (5 layers) remains"
    assert overview.prepared_layer_counts == ()
    assert load_material_candidate_runtime(
        materials, 5, 0.08, "white", candidate_budget=DYNAMIC_CANDIDATE_BUDGET, cache_root=tmp_path
    ) is not None


@pytest.mark.parametrize("operation", [prepare_dynamic_layer_cache, compute_dynamic_layer_gamut])
def test_prepare_and_coverage_build_layer_runtimes_before_taking_the_catalog_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: Callable[..., object],
) -> None:
    lock_depth = {"held": 0}
    builds_under_lock: list[int] = []
    lock_class = catalog_cache._DynamicCatalogKeyLock
    real_enter, real_exit = lock_class.__enter__, lock_class.__exit__
    real_build = material_provider.build_material_candidate_runtime

    def enter(self):
        result = real_enter(self)
        lock_depth["held"] += 1
        return result

    def exit_(self, *args):
        lock_depth["held"] -= 1
        return real_exit(self, *args)

    def build(**kwargs):
        builds_under_lock.append(lock_depth["held"])
        return real_build(**kwargs)

    monkeypatch.setattr(lock_class, "__enter__", enter)
    monkeypatch.setattr(lock_class, "__exit__", exit_)
    monkeypatch.setattr(material_provider, "build_material_candidate_runtime", build)

    operation(_materials(), 0, 0.08, "white", 5, 6, cache_root=tmp_path)

    assert builds_under_lock == [0, 0], "per-layer builds must not hold the catalog lock"


def test_prepare_is_a_no_op_when_everything_is_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = _materials()
    prepare_dynamic_layer_cache(materials, 0, 0.08, "white", 5, 6, cache_root=tmp_path)
    monkeypatch.setattr(
        dynamic_solver,
        "_build_dynamic_candidate_catalog_from_runtimes",
        lambda *_args: pytest.fail("a prepared catalog must not be rebuilt"),
    )

    again = prepare_dynamic_layer_cache(materials, 0, 0.08, "white", 5, 6, cache_root=tmp_path)

    assert again.built is False
    assert again.elapsed_seconds == 0.0


def test_prepare_fills_missing_layers_when_conversion_built_only_the_catalog(
    tmp_path: Path,
) -> None:
    materials = _materials()
    _load_catalog(materials, tmp_path, backing=0)  # what a plain conversion leaves behind

    result = prepare_dynamic_layer_cache(materials, 0, 0.08, "white", 5, 6, cache_root=tmp_path)

    assert result.built is True
    assert result.overview.missing_layer_counts == ()
