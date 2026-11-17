"""Unit tests for the persistent dynamic material candidate catalog.

动态耗材候选目录持久缓存单元测试。
"""

from __future__ import annotations

import json
import os
import struct
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

import core.material_dynamic_catalog_cache as catalog_cache
import core.material_dynamic_solver as dynamic_solver
import core.material_lut_provider as material_provider
from core.material_candidate_cache import (
    PREVIEW_SAFE_CANDIDATE_BUDGET,
    MaterialCandidateRuntime,
)
from core.material_color_solver import MaterialParams
from core.material_dynamic_catalog_cache import (
    DYNAMIC_CATALOG_ALGORITHM_VERSION,
    DynamicCatalogCacheCorruptionError,
    build_dynamic_catalog_cache_key,
    dynamic_catalog_cache_file_path,
    load_dynamic_candidate_catalog,
    load_or_build_dynamic_candidate_catalog,
    save_dynamic_candidate_catalog,
)
from core.material_dynamic_solver import build_dynamic_candidate_catalog


def _material(name: str, rgb: tuple[float, float, float]) -> MaterialParams:
    return MaterialParams(
        name=name,
        directory_name=name.lower(),
        E=np.asarray(rgb, dtype=np.float64),
        k=np.asarray([8.0, 8.0, 8.0], dtype=np.float64),
        C0_white=np.ones(3, dtype=np.float64),
        estimated_rgb=np.asarray(np.round(np.asarray(rgb) * 255), dtype=np.uint8),
    )


def _materials() -> list[MaterialParams]:
    return [
        _material("Red", (0.85, 0.08, 0.06)),
        _material("Blue", (0.05, 0.10, 0.85)),
    ]


def _duplicate_optical_materials() -> list[MaterialParams]:
    optics = (0.42, 0.31, 0.18)
    return [
        _material("Identity A", optics),
        _material("Identity B", optics),
    ]


@pytest.mark.parametrize("materials", [_materials(), _duplicate_optical_materials()])
def test_established_dynamic_enumeration_order_and_rebinding(materials):
    assert catalog_cache.dynamic_material_canonical_order(materials) == (1, 0)
    reordered = list(reversed(materials))
    assert catalog_cache.dynamic_material_canonical_order(reordered) == (0, 1)
    assert [materials[index].directory_name for index in (1, 0)] == [
        reordered[index].directory_name for index in (0, 1)
    ]


def _catalog() -> dynamic_solver.DynamicCandidateCatalog:
    return build_dynamic_candidate_catalog(
        np.asarray([[12, 34, 56], [78, 90, 123]], dtype=np.uint8),
        np.asarray(
            [
                [0, 1, 1, 0, 1, 0],
                [1, 0, 1, 0, 0, 1],
            ],
            dtype=np.int32,
        ),
        np.asarray([5, 6], dtype=np.int16),
        6,
    )


def _key(
    materials: list[MaterialParams],
    *,
    backing_material_index: int = 0,
    min_layer_count: int = 5,
    max_layer_count: int = 6,
    candidate_budget: int = 2048,
    algorithm_version: str = DYNAMIC_CATALOG_ALGORITHM_VERSION,
):
    return build_dynamic_catalog_cache_key(
        materials,
        backing_material_index=backing_material_index,
        layer_height_mm=0.08,
        substrate="white",
        min_layer_count=min_layer_count,
        max_layer_count=max_layer_count,
        candidate_budget=candidate_budget,
        algorithm_version=algorithm_version,
    )


def _runtime(recipes: np.ndarray, layer_count: int) -> MaterialCandidateRuntime:
    rows = int(recipes.shape[0])
    return MaterialCandidateRuntime(
        candidate_recipes=np.asarray(recipes, dtype=np.uint8),
        achieved_srgb=np.full((rows, 3), 255, dtype=np.uint8),
        achieved_lab=np.zeros((rows, 3), dtype=np.float64),
        pinned_mask=np.zeros(rows, dtype=np.bool_),
        metadata={
            "layer_count": layer_count,
            "layer_height_mm": 0.08,
            "substrate": "white",
            "palette_hash": "test",
            "grid_resolution": 8,
        },
    )


def _rewrite_npz(path: Path, mutate) -> None:
    with np.load(path, allow_pickle=False) as loaded:
        payload = {name: np.array(loaded[name], copy=True) for name in loaded.files}
    mutate(payload)
    with path.open("wb") as handle:
        np.savez_compressed(handle, **payload)


def _metadata_from_payload(payload: dict[str, np.ndarray]) -> dict[str, object]:
    return json.loads(payload["metadata_json"].tobytes().decode("utf-8"))


def _store_metadata(
    payload: dict[str, np.ndarray], metadata: dict[str, object]
) -> None:
    payload["metadata_json"] = np.frombuffer(
        json.dumps(
            metadata,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
        dtype=np.uint8,
    )


def test_cache_key_covers_version_palette_backing_range_height_substrate_and_budget() -> None:
    materials = _materials()
    base = _key(materials)

    assert _key(list(reversed(materials)), backing_material_index=1) == base
    variants = {
        _key(materials, backing_material_index=1),
        _key(materials, min_layer_count=6),
        _key(materials, max_layer_count=7),
        _key(materials, candidate_budget=4096),
        _key(materials, algorithm_version="dynamic-ciede2000-v-next"),
        build_dynamic_catalog_cache_key(
            materials,
            backing_material_index=0,
            layer_height_mm=0.12,
            substrate="white",
            min_layer_count=5,
            max_layer_count=6,
            candidate_budget=2048,
        ),
        build_dynamic_catalog_cache_key(
            materials,
            backing_material_index=0,
            layer_height_mm=0.08,
            substrate="black",
            min_layer_count=5,
            max_layer_count=6,
            candidate_budget=2048,
        ),
    }
    assert base not in variants
    assert len(variants) == 7


def test_identity_safe_candidate_universe_uses_new_algorithm_version() -> None:
    assert DYNAMIC_CATALOG_ALGORITHM_VERSION == "dynamic-ciede2000-v2"


def test_old_sampling_source_catalog_is_rebuilt_without_deleting_old_payload(
    tmp_path: Path,
) -> None:
    materials = _materials()
    current_key = _key(materials)
    old_key = replace(current_key, candidate_source_version="hybrid-v2")
    old_path = save_dynamic_candidate_catalog(
        _catalog(), materials=materials, key=old_key,
        candidate_count_before_dedup=3, cache_root=tmp_path,
    )
    old_bytes = old_path.read_bytes()
    assert load_dynamic_candidate_catalog(
        materials=materials, key=current_key, cache_root=tmp_path,
    ) is None

    rebuilt = load_or_build_dynamic_candidate_catalog(
        materials=materials, key=current_key,
        builder=lambda: (_catalog(), 3), cache_root=tmp_path,
    )
    assert rebuilt.cache_hit is False
    assert rebuilt.rebuilt_corrupt is False

    def forbidden_build():
        raise AssertionError("the rebuilt catalog must be reusable")

    reopened = load_or_build_dynamic_candidate_catalog(
        materials=materials, key=current_key,
        builder=forbidden_build, cache_root=tmp_path,
    )
    assert reopened.cache_hit is True
    np.testing.assert_array_equal(
        reopened.catalog.print_recipes, rebuilt.catalog.print_recipes,
    )
    assert old_path.read_bytes() == old_bytes


def test_catalog_round_trip_rebinds_canonical_recipes_to_current_user_order(
    tmp_path: Path,
) -> None:
    materials = _materials()
    key = _key(materials)
    original = _catalog()
    save_dynamic_candidate_catalog(
        original,
        materials=materials,
        key=key,
        candidate_count_before_dedup=3,
        cache_root=tmp_path,
    )

    reversed_materials = list(reversed(materials))
    loaded = load_dynamic_candidate_catalog(
        materials=reversed_materials,
        key=_key(reversed_materials, backing_material_index=1),
        cache_root=tmp_path,
    )

    assert loaded is not None
    np.testing.assert_array_equal(loaded.catalog.score_srgb, original.score_srgb)
    np.testing.assert_array_equal(loaded.catalog.score_lab, original.score_lab)
    np.testing.assert_array_equal(
        loaded.catalog.print_recipes,
        1 - original.print_recipes,
    )
    assert loaded.candidate_count_before_dedup == 3


def test_duplicate_optical_material_identities_keep_key_backing_and_rebind_stable(
    tmp_path: Path,
) -> None:
    materials = _duplicate_optical_materials()
    original = _catalog()
    key = _key(materials, backing_material_index=0)
    save_dynamic_candidate_catalog(
        original,
        materials=materials,
        key=key,
        candidate_count_before_dedup=3,
        cache_root=tmp_path,
    )

    reversed_materials = list(reversed(materials))
    reversed_key = _key(reversed_materials, backing_material_index=1)
    loaded = load_dynamic_candidate_catalog(
        materials=reversed_materials,
        key=reversed_key,
        cache_root=tmp_path,
    )

    assert reversed_key == key
    assert loaded is not None
    np.testing.assert_array_equal(
        loaded.catalog.print_recipes,
        1 - original.print_recipes,
    )


def test_cache_hit_is_bit_identical_to_fresh_build_and_does_not_rebuild(
    tmp_path: Path,
) -> None:
    materials = _materials()
    key = _key(materials)
    built = _catalog()
    build_calls = 0

    def builder() -> tuple[dynamic_solver.DynamicCandidateCatalog, int]:
        nonlocal build_calls
        build_calls += 1
        return built, 3

    first = load_or_build_dynamic_candidate_catalog(
        materials=materials,
        key=key,
        builder=builder,
        cache_root=tmp_path,
    )
    second = load_or_build_dynamic_candidate_catalog(
        materials=materials,
        key=key,
        builder=builder,
        cache_root=tmp_path,
    )

    assert build_calls == 1
    assert first.cache_hit is False
    assert second.cache_hit is True
    for field in (
        "score_srgb",
        "score_lab",
        "print_recipes",
        "minimum_actual_layer_counts",
        "max_layer_reachable",
        "source_indices",
    ):
        np.testing.assert_array_equal(
            getattr(first.catalog, field),
            getattr(second.catalog, field),
        )


def test_cache_write_atomically_replaces_payload_and_descriptor_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = _materials()
    key = _key(materials)
    replacements: list[tuple[Path, Path]] = []
    original_replace = os.replace

    def capture_replace(source: os.PathLike[str], target: os.PathLike[str]) -> None:
        replacements.append((Path(source), Path(target)))
        original_replace(source, target)

    monkeypatch.setattr(catalog_cache.os, "replace", capture_replace)
    path = save_dynamic_candidate_catalog(
        _catalog(),
        materials=materials,
        key=key,
        candidate_count_before_dedup=3,
        cache_root=tmp_path,
    )

    assert [target for _source, target in replacements] == [path.with_suffix(".meta.json"), path]
    assert path.suffix == ".npz"
    assert path.with_suffix(".meta.json").is_file()
    assert list(path.parent.glob("*.tmp-*")) == []


def test_corrupt_entry_is_removed_and_explicitly_rebuilt(tmp_path: Path) -> None:
    materials = _materials()
    key = _key(materials)
    path = save_dynamic_candidate_catalog(
        _catalog(), materials=materials, key=key,
        candidate_count_before_dedup=3, cache_root=tmp_path,
    )
    path.write_bytes(b"not-an-npz")
    build_calls = 0

    def builder() -> tuple[dynamic_solver.DynamicCandidateCatalog, int]:
        nonlocal build_calls
        build_calls += 1
        return _catalog(), 3

    result = load_or_build_dynamic_candidate_catalog(
        materials=materials,
        key=key,
        builder=builder,
        cache_root=tmp_path,
    )

    assert build_calls == 1
    assert result.cache_hit is False
    assert result.rebuilt_corrupt is True
    assert path.exists()
    assert len(list(path.parent.glob(path.name + ".corrupt-*"))) == 1
    assert load_dynamic_candidate_catalog(
        materials=materials,
        key=key,
        cache_root=tmp_path,
    ) is not None


def test_invalid_payload_raises_corruption_instead_of_becoming_a_hit(
    tmp_path: Path,
) -> None:
    materials = _materials()
    key = _key(materials)
    path = save_dynamic_candidate_catalog(
        _catalog(), materials=materials, key=key,
        candidate_count_before_dedup=3, cache_root=tmp_path,
    )
    with path.open("wb") as handle:
        np.savez_compressed(
            handle,
            score_srgb=np.asarray([[1, 2, 3]], dtype=np.uint8),
            metadata_json=np.frombuffer(b"{}", dtype=np.uint8),
        )

    with pytest.raises(DynamicCatalogCacheCorruptionError):
        load_dynamic_candidate_catalog(
            materials=materials,
            key=key,
            cache_root=tmp_path,
        )


@pytest.mark.parametrize(
    "mutate",
    (
        lambda payload: payload.__setitem__(
            "source_indices", np.asarray([0, 0], dtype=np.int64)
        ),
        lambda payload: payload.__setitem__(
            "source_indices", np.asarray([0, 3], dtype=np.int64)
        ),
        lambda payload: payload.__setitem__(
            "score_srgb",
            np.asarray([[12, 34, 56], [12, 34, 56]], dtype=np.uint8),
        ),
        lambda payload: payload.__setitem__(
            "max_layer_reachable", np.asarray([False, False], dtype=np.bool_)
        ),
        lambda payload: (
            payload.__setitem__(
                "minimum_actual_layer_counts", np.asarray([5, 6], dtype=np.int16)
            ),
            payload.__setitem__(
                "max_layer_reachable", np.asarray([True, False], dtype=np.bool_)
            ),
        ),
    ),
    ids=(
        "duplicate-source-index",
        "source-index-out-of-range",
        "duplicate-rgb",
        "no-fixed-max-candidate",
        "max-count-not-reachable",
    ),
)
def test_catalog_payload_rejects_cross_field_invariant_corruption(
    tmp_path: Path,
    mutate,
) -> None:
    materials = _materials()
    key = _key(materials)
    path = save_dynamic_candidate_catalog(
        _catalog(),
        materials=materials,
        key=key,
        candidate_count_before_dedup=3,
        cache_root=tmp_path,
    )
    _rewrite_npz(path, mutate)

    with pytest.raises(DynamicCatalogCacheCorruptionError):
        load_dynamic_candidate_catalog(
            materials=materials,
            key=key,
            cache_root=tmp_path,
        )


def test_catalog_payload_rejects_backing_identity_mismatch(tmp_path: Path) -> None:
    materials = _materials()
    key = _key(materials)
    path = save_dynamic_candidate_catalog(
        _catalog(),
        materials=materials,
        key=key,
        candidate_count_before_dedup=3,
        cache_root=tmp_path,
    )

    def corrupt(payload: dict[str, np.ndarray]) -> None:
        metadata = _metadata_from_payload(payload)
        backing_index = 1 - int(metadata["canonical_backing_material_index"])
        metadata["canonical_backing_material_index"] = backing_index
        payload["print_recipes_canonical"][0, 0] = backing_index
        _store_metadata(payload, metadata)

    _rewrite_npz(path, corrupt)

    with pytest.raises(DynamicCatalogCacheCorruptionError):
        load_dynamic_candidate_catalog(
            materials=materials,
            key=key,
            cache_root=tmp_path,
        )


def test_flipped_compressed_bytes_are_quarantined_and_rebuilt(tmp_path: Path) -> None:
    materials = _materials()
    key = _key(materials)
    path = save_dynamic_candidate_catalog(
        _catalog(),
        materials=materials,
        key=key,
        candidate_count_before_dedup=3,
        cache_root=tmp_path,
    )
    raw = bytearray(path.read_bytes())
    with zipfile.ZipFile(path) as archive:
        member = archive.getinfo("source_indices.npy")
        header = raw[member.header_offset : member.header_offset + 30]
        filename_length, extra_length = struct.unpack_from("<HH", header, 26)
        data_start = member.header_offset + 30 + filename_length + extra_length
        raw[data_start + max(0, member.compress_size // 2)] ^= 0xFF
    path.write_bytes(raw)
    build_calls = 0

    def builder() -> tuple[dynamic_solver.DynamicCandidateCatalog, int]:
        nonlocal build_calls
        build_calls += 1
        return _catalog(), 3

    result = load_or_build_dynamic_candidate_catalog(
        materials=materials,
        key=key,
        builder=builder,
        cache_root=tmp_path,
    )

    assert build_calls == 1
    assert result.rebuilt_corrupt is True
    assert len(list(path.parent.glob(path.name + ".corrupt-*"))) == 1

    assert load_dynamic_candidate_catalog(
        materials=materials,
        key=key,
        cache_root=tmp_path,
    ) is not None


def test_persisted_payload_contains_catalog_only_and_never_target_results(
    tmp_path: Path,
) -> None:
    materials = _materials()
    key = _key(materials)
    path = save_dynamic_candidate_catalog(
        _catalog(),
        materials=materials,
        key=key,
        candidate_count_before_dedup=3,
        cache_root=tmp_path,
    )

    with np.load(path, allow_pickle=False) as payload:
        assert set(payload.files) == {
            "score_srgb",
            "score_lab",
            "print_recipes_canonical",
            "minimum_actual_layer_counts",
            "max_layer_reachable",
            "source_indices",
            "metadata_json",
        }
        metadata = json.loads(payload["metadata_json"].tobytes().decode("utf-8"))
    assert "target_srgb" not in metadata
    assert "matches" not in metadata
    assert "search" not in metadata


def test_production_solver_pins_candidate_budget_for_every_layer_and_skips_fixed_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = _materials()
    runtimes = {
        5: _runtime(np.asarray([[0, 0, 0, 0, 0]], dtype=np.uint8), 5),
        6: _runtime(np.asarray([[1, 1, 1, 1, 1, 1]], dtype=np.uint8), 6),
    }
    calls: list[tuple[int, int]] = []

    def dynamic_loader(
        _materials: list[MaterialParams],
        layer_count: int,
        layer_height_mm: float,
        substrate: str,
        *,
        candidate_budget: int,
        cache_root: str | Path | None = None,
    ) -> tuple[MaterialCandidateRuntime, int]:
        del layer_height_mm, substrate, cache_root
        calls.append((layer_count, candidate_budget))
        return runtimes[layer_count], 8

    monkeypatch.setattr(dynamic_solver, "load_dynamic_candidate_runtime", dynamic_loader)
    # Preparing the palette before an image is chosen must populate the exact
    # catalog subsequently consumed by the first real preview.
    dynamic_solver.prepare_dynamic_material_catalog(
        materials, 0, 0.08, "white",
        dynamic_solver.DynamicMaterialSolveConfig(5, 6, 0.5),
        catalog_cache_root=tmp_path,
    )
    monkeypatch.setattr(
        "core.material_lut_provider.load_solver_cache",
        lambda *_args, **_kwargs: pytest.fail("legacy fixed cache must not be queried"),
    )

    dynamic_solver.solve_dynamic_material_colors(
        np.asarray([[120, 30, 40]], dtype=np.uint8),
        materials,
        backing_material_index=0,
        layer_height_mm=0.08,
        substrate="white",
        config=dynamic_solver.DynamicMaterialSolveConfig(5, 6, 0.5),
        catalog_cache_root=tmp_path,
    )

    assert calls == [
        (5, PREVIEW_SAFE_CANDIDATE_BUDGET),
        (6, PREVIEW_SAFE_CANDIDATE_BUDGET),
    ]


def test_production_solver_duplicate_optics_fresh_and_hit_preserve_identities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = _duplicate_optical_materials()
    runtimes = {
        layer_count: _runtime(
            np.asarray(
                [
                    [0] * layer_count,
                    [1] * layer_count,
                ],
                dtype=np.uint8,
            ),
            layer_count,
        )
        for layer_count in (5, 6)
    }
    loader_orders: list[tuple[str, ...]] = []

    def dynamic_loader(
        loader_materials: list[MaterialParams],
        layer_count: int,
        _layer_height_mm: float,
        _substrate: str,
        *,
        candidate_budget: int,
        cache_root: str | Path | None = None,
    ) -> tuple[MaterialCandidateRuntime, int]:
        del candidate_budget, cache_root
        loader_orders.append(
            tuple(material.directory_name for material in loader_materials)
        )
        return runtimes[layer_count], 8

    monkeypatch.setattr(
        dynamic_solver,
        "load_dynamic_candidate_runtime",
        dynamic_loader,
    )
    config = dynamic_solver.DynamicMaterialSolveConfig(5, 6, 0.5)
    targets = np.asarray([[120, 90, 60]], dtype=np.uint8)
    hit_root = tmp_path / "hit"
    fresh_root = tmp_path / "fresh"

    original_fresh = dynamic_solver.solve_dynamic_material_colors(
        targets,
        materials,
        backing_material_index=0,
        layer_height_mm=0.08,
        substrate="white",
        config=config,
        catalog_cache_root=hit_root,
    )
    reversed_materials = list(reversed(materials))
    reversed_hit = dynamic_solver.solve_dynamic_material_colors(
        targets,
        reversed_materials,
        backing_material_index=1,
        layer_height_mm=0.08,
        substrate="white",
        config=config,
        catalog_cache_root=hit_root,
    )
    reversed_fresh = dynamic_solver.solve_dynamic_material_colors(
        targets,
        reversed_materials,
        backing_material_index=1,
        layer_height_mm=0.08,
        substrate="white",
        config=config,
        catalog_cache_root=fresh_root,
    )

    def recipe_identities(recipe, palette) -> tuple[str, ...]:
        return tuple(
            palette[index].directory_name
            for index in recipe
        )

    assert len(loader_orders) == 4
    assert len(set(loader_orders)) == 1
    original_option = original_fresh.matches[0].selected
    hit_option = reversed_hit.matches[0].selected
    fresh_option = reversed_fresh.matches[0].selected
    assert recipe_identities(
        original_option.actual_recipe_bottom_to_top,
        materials,
    ) == recipe_identities(
        hit_option.actual_recipe_bottom_to_top,
        reversed_materials,
    )
    assert recipe_identities(
        hit_option.actual_recipe_bottom_to_top,
        reversed_materials,
    ) == recipe_identities(
        fresh_option.actual_recipe_bottom_to_top,
        reversed_materials,
    )
    assert recipe_identities(
        hit_option.print_recipe_bottom_to_top,
        reversed_materials,
    ) == recipe_identities(
        fresh_option.print_recipe_bottom_to_top,
        reversed_materials,
    )
    assert recipe_identities(
        hit_option.print_recipe_bottom_to_top,
        reversed_materials,
    )[0] == materials[0].directory_name
    assert hit_option.matched_srgb == (
        fresh_option.matched_srgb
    )


def test_dynamic_runtime_provider_bypasses_legacy_fixed_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = _materials()
    runtime = _runtime(np.asarray([[0, 0, 0, 0, 0]], dtype=np.uint8), 5)
    candidate_calls: list[int] = []
    monkeypatch.setattr(
        material_provider,
        "load_solver_cache",
        lambda *_args, **_kwargs: pytest.fail("fixed cache must not be probed"),
    )

    def load_candidate(*_args, candidate_budget: int, **_kwargs):
        candidate_calls.append(candidate_budget)
        return runtime

    monkeypatch.setattr(
        material_provider,
        "load_material_candidate_runtime",
        load_candidate,
    )

    loaded, diagnostic_grid = material_provider.load_dynamic_candidate_runtime(
        materials,
        5,
        0.08,
        "white",
        candidate_budget=PREVIEW_SAFE_CANDIDATE_BUDGET,
    )

    assert loaded is runtime
    assert diagnostic_grid == runtime.grid_resolution
    assert candidate_calls == [PREVIEW_SAFE_CANDIDATE_BUDGET]


def test_dynamic_runtime_provider_reuses_identity_safe_cache_for_duplicate_optics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = _duplicate_optical_materials()
    runtime = _runtime(np.asarray([[0, 1, 0, 1, 0]], dtype=np.uint8), 5)
    build_orders: list[list[str]] = []
    monkeypatch.setattr(
        material_provider,
        "load_material_candidate_runtime",
        lambda *_args, **_kwargs: runtime,
    )

    def build_runtime(*, materials, **_kwargs):
        build_orders.append([material.directory_name for material in materials])
        return runtime

    monkeypatch.setattr(
        material_provider,
        "build_material_candidate_runtime",
        build_runtime,
    )

    loaded, _diagnostic_grid = material_provider.load_dynamic_candidate_runtime(
        materials,
        5,
        0.08,
        "white",
        candidate_budget=PREVIEW_SAFE_CANDIDATE_BUDGET,
    )

    assert loaded is runtime
    assert build_orders == []


def test_concurrent_miss_builds_once_and_second_caller_hits(tmp_path: Path) -> None:
    materials = _materials()
    key = _key(materials)
    start = threading.Barrier(2)
    build_lock = threading.Lock()
    build_calls = 0

    def builder() -> tuple[dynamic_solver.DynamicCandidateCatalog, int]:
        nonlocal build_calls
        with build_lock:
            build_calls += 1
        time.sleep(0.1)
        return _catalog(), 3

    def invoke():
        start.wait(timeout=2)
        return load_or_build_dynamic_candidate_catalog(
            materials=materials,
            key=key,
            builder=builder,
            cache_root=tmp_path,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _value: invoke(), range(2)))

    assert build_calls == 1
    assert sorted(result.cache_hit for result in results) == [False, True]


def test_blocked_build_does_not_block_another_catalog_cache_hit(tmp_path: Path) -> None:
    materials = _materials()
    cached_key = _key(materials)
    blocked_key = _key(materials, candidate_budget=4096)
    save_dynamic_candidate_catalog(
        _catalog(), materials=materials, key=cached_key,
        candidate_count_before_dedup=3, cache_root=tmp_path,
    )
    entered = threading.Event()
    release = threading.Event()

    def blocked_builder():
        entered.set()
        assert release.wait(10)
        return _catalog(), 3

    with ThreadPoolExecutor(max_workers=2) as executor:
        blocked = executor.submit(
            load_or_build_dynamic_candidate_catalog,
            materials=materials, key=blocked_key, builder=blocked_builder,
            cache_root=tmp_path,
        )
        assert entered.wait(2)
        hit = executor.submit(
            load_or_build_dynamic_candidate_catalog,
            materials=materials, key=cached_key,
            builder=lambda: pytest.fail("existing catalog must be reused"),
            cache_root=tmp_path,
        )
        try:
            assert hit.result(timeout=1).cache_hit
        finally:
            release.set()
            blocked.result(timeout=2)


def test_cache_emits_structured_hit_miss_build_and_corruption_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[tuple[str, dict[str, object]]] = []

    def capture_debug(_message: str, *, extra: dict[str, object]) -> None:
        records.append(("DEBUG", extra))

    def capture_warning(_message: str, *, extra: dict[str, object]) -> None:
        records.append(("WARNING", extra))

    monkeypatch.setattr(catalog_cache._log, "debug", capture_debug)
    monkeypatch.setattr(catalog_cache._log, "warning", capture_warning)
    materials = _materials()
    key = _key(materials)

    def builder() -> tuple[dynamic_solver.DynamicCandidateCatalog, int]:
        return _catalog(), 3

    load_or_build_dynamic_candidate_catalog(
        materials=materials,
        key=key,
        builder=builder,
        cache_root=tmp_path,
    )
    load_or_build_dynamic_candidate_catalog(
        materials=materials,
        key=key,
        builder=builder,
        cache_root=tmp_path,
    )
    path = dynamic_catalog_cache_file_path(key, cache_root=tmp_path)
    path.write_bytes(b"corrupt")
    load_or_build_dynamic_candidate_catalog(
        materials=materials,
        key=key,
        builder=builder,
        cache_root=tmp_path,
    )

    events = {extra["event"]: (level, extra) for level, extra in records}
    assert "dynamic_material_catalog_cache_miss" in events
    assert "dynamic_material_catalog_cache_build_done" in events
    assert "dynamic_material_catalog_cache_hit" in events
    warning_level, warning = events[
        "dynamic_material_catalog_cache_corrupt_rebuild"
    ]
    assert warning_level == "WARNING"
    assert warning["error_type"]
    assert warning["error_message"]


def test_invalid_builder_catalog_is_typed_failure_and_is_not_persisted(
    tmp_path: Path,
) -> None:
    materials = _materials()
    key = _key(materials)
    valid = _catalog()
    invalid = dynamic_solver.DynamicCandidateCatalog(
        score_srgb=valid.score_srgb,
        score_lab=valid.score_lab,
        print_recipes=valid.print_recipes,
        minimum_actual_layer_counts=valid.minimum_actual_layer_counts,
        max_layer_reachable=valid.max_layer_reachable,
        source_indices=np.asarray([0, 0], dtype=np.int64),
    )
    path = dynamic_catalog_cache_file_path(key, cache_root=tmp_path)

    with pytest.raises(dynamic_solver.DynamicMaterialCandidateError) as caught:
        load_or_build_dynamic_candidate_catalog(
            materials=materials,
            key=key,
            builder=lambda: (invalid, 3),
            cache_root=tmp_path,
        )

    assert caught.value.phase == "dynamic_catalog_cache_build"
    assert not path.exists()


def test_corrupt_rebuild_rejects_invalid_builder_without_replacing_entry(
    tmp_path: Path,
) -> None:
    materials = _materials()
    key = _key(materials)
    valid = _catalog()
    invalid = dynamic_solver.DynamicCandidateCatalog(
        score_srgb=valid.score_srgb,
        score_lab=valid.score_lab,
        print_recipes=valid.print_recipes,
        minimum_actual_layer_counts=valid.minimum_actual_layer_counts,
        max_layer_reachable=np.asarray([False, False], dtype=np.bool_),
        source_indices=valid.source_indices,
    )
    path = save_dynamic_candidate_catalog(
        _catalog(), materials=materials, key=key,
        candidate_count_before_dedup=3, cache_root=tmp_path,
    )
    path.write_bytes(b"corrupt")

    with pytest.raises(dynamic_solver.DynamicMaterialCandidateError) as caught:
        load_or_build_dynamic_candidate_catalog(
            materials=materials,
            key=key,
            builder=lambda: (invalid, 3),
            cache_root=tmp_path,
        )

    assert caught.value.phase == "dynamic_catalog_cache_build"
    assert not path.exists()
    assert len(list(path.parent.glob(path.name + ".corrupt-*"))) == 1


def test_cache_build_failure_emits_paired_structured_failed_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: list[tuple[str, dict[str, object]]] = []

    def capture_debug(_message: str, *, extra: dict[str, object]) -> None:
        records.append(("DEBUG", extra))

    def capture_warning(_message: str, *, extra: dict[str, object]) -> None:
        records.append(("WARNING", extra))

    monkeypatch.setattr(catalog_cache._log, "debug", capture_debug)
    monkeypatch.setattr(catalog_cache._log, "warning", capture_warning)
    materials = _materials()
    key = _key(materials)

    def failing_builder() -> tuple[dynamic_solver.DynamicCandidateCatalog, int]:
        raise RuntimeError("catalog exploded")

    with pytest.raises(dynamic_solver.DynamicMaterialCandidateError):
        load_or_build_dynamic_candidate_catalog(
            materials=materials,
            key=key,
            builder=failing_builder,
            cache_root=tmp_path,
        )

    init_events = [
        extra
        for _level, extra in records
        if extra["event"] == "dynamic_material_catalog_cache_build_init"
    ]
    failed_events = [
        (level, extra)
        for level, extra in records
        if extra["event"] == "dynamic_material_catalog_cache_build_failed"
    ]
    done_events = [
        extra
        for _level, extra in records
        if extra["event"] == "dynamic_material_catalog_cache_build_done"
    ]
    assert len(init_events) == 1
    assert len(failed_events) == 1
    assert done_events == []
    level, failed = failed_events[0]
    assert level == "WARNING"
    assert failed["error_type"] == "RuntimeError"
    assert failed["error_message"] == "catalog exploded"
    assert failed["cache_key"]
    assert failed["layer_count"] == key.max_layer_count


def test_custom_runtime_loader_bypasses_persistent_catalog_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materials = _materials()
    runtime = _runtime(np.asarray([[0, 0, 0, 0, 0]], dtype=np.uint8), 5)
    monkeypatch.setattr(
        catalog_cache,
        "load_or_build_dynamic_candidate_catalog",
        lambda **_kwargs: pytest.fail("custom loaders must bypass persistence"),
    )

    result = dynamic_solver.solve_dynamic_material_colors(
        np.asarray([[120, 30, 40]], dtype=np.uint8),
        materials,
        backing_material_index=0,
        layer_height_mm=0.08,
        substrate="white",
        config=dynamic_solver.DynamicMaterialSolveConfig(5, 5, 0.5),
        runtime_loader=lambda _m, _k, _h, _s: (runtime, 8),
    )

    assert len(result.matches) == 1
