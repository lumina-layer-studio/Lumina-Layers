"""Sampling regressions for incomplete or silently degraded SciPy installs."""

from __future__ import annotations

import numpy as np
import pytest
from scipy.stats import qmc

from core import material_candidate_sampling as sampling


@pytest.mark.parametrize("fault", [
    "constant", "constant_dimension", "short", "wrong_dimensions", "flat",
    "nan", "inf", "negative", "upper_bound",
])
def test_invalid_sobol_samples_use_deterministic_seeded_fallback(
    monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    def broken_points(sampler: qmc.Sobol, power: int) -> np.ndarray:
        points = np.random.default_rng(37).random((2 ** power, sampler.d))
        if fault == "constant":
            points[:] = 0.25
        elif fault == "constant_dimension":
            points[:, 0] = 0.25
        elif fault == "short":
            points = points[:-1]
        elif fault == "wrong_dimensions":
            points = points[:, :-1]
        elif fault == "flat":
            points = points[:, 0]
        else:
            points[0, 0] = {
                "nan": np.nan, "inf": np.inf, "negative": -0.1,
                "upper_bound": 1.0,
            }[fault]
        return points

    monkeypatch.setattr(qmc.Sobol, "random_base2", broken_points)
    first = sampling._low_discrepancy_recipes(
        material_count=4, layer_count=10, count=4096, seed=7,
    )
    second = sampling._low_discrepancy_recipes(
        material_count=4, layer_count=10, count=4096, seed=7,
    )
    expected = np.floor(np.random.default_rng(7).random((4096, 10)) * 4)

    assert first.shape == (4096, 10)
    assert np.all((first >= 0) & (first < 4))
    assert np.unique(first, axis=0).shape[0] > 4000
    np.testing.assert_array_equal(first, expected.astype(np.uint16))
    np.testing.assert_array_equal(first, second)


def test_sobol_exception_keeps_existing_seeded_fallback(monkeypatch) -> None:
    def unavailable(*_args):
        raise OSError("direction numbers unavailable")

    monkeypatch.setattr(sampling, "_sobol_points", unavailable)
    recipes = sampling._low_discrepancy_recipes(
        material_count=4, layer_count=10, count=4096, seed=7,
    )
    expected = np.floor(np.random.default_rng(7).random((4096, 10)) * 4)
    np.testing.assert_array_equal(recipes, expected.astype(np.uint16))


def test_invalid_later_block_restarts_the_entire_seeded_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    draw = qmc.Sobol.random

    def broken_draw(sampler, count):
        generated = sampler.num_generated
        points = draw(sampler, count)
        if generated:
            points[0, 0] = 1.0
        return points

    monkeypatch.setattr(qmc.Sobol, "random", broken_draw)
    recipes = sampling._low_discrepancy_recipes(
        material_count=17, layer_count=5, count=43, seed=7, block_rows=8,
    )
    expected = np.floor(np.random.default_rng(7).random((43, 5)) * 17).astype(np.uint16)
    np.testing.assert_array_equal(recipes, expected)


@pytest.mark.parametrize("points", [
    np.full((32, 10), 0.25),
    np.full((32, 10), np.nan),
    np.full((32, 10), 1.0),
    np.zeros((31, 10)),
])
def test_invalid_rng_fallback_fails_instead_of_returning_recipes(
    monkeypatch: pytest.MonkeyPatch, points: np.ndarray,
) -> None:
    def unavailable(*_args):
        raise OSError("direction numbers unavailable")

    monkeypatch.setattr(sampling, "_sobol_points", unavailable)
    monkeypatch.setattr(sampling, "_rng_points", lambda *_args: points)
    with pytest.raises(ValueError, match="sample points"):
        sampling._low_discrepancy_recipes(
            material_count=4, layer_count=10, count=32, seed=7,
        )


@pytest.mark.parametrize("count", [0, 1, 2, 1024])
def test_healthy_sobol_keeps_exact_existing_recipes(count: int) -> None:
    points = sampling._sobol_points(count, 10, 7)
    expected = np.floor(points * 4).astype(np.uint16)
    recipes = sampling._low_discrepancy_recipes(
        material_count=4, layer_count=10, count=count, seed=7,
    )
    assert recipes.shape == (count, 10)
    np.testing.assert_array_equal(recipes, expected)


def test_collapsed_sobol_still_fills_high_layer_candidate_budget(monkeypatch) -> None:
    monkeypatch.setattr(
        sampling, "_sobol_points", lambda count, layers, seed: np.full((count, layers), 0.25),
    )
    batch = sampling.generate_candidate_recipes(
        material_count=4, layer_count=10, candidate_budget=4096, seed=7,
    )
    assert batch.recipes.shape == (4096, 10)
    assert np.unique(batch.recipes, axis=0).shape[0] == 4096
    assert np.all((batch.recipes >= 0) & (batch.recipes < 4))


@pytest.mark.parametrize("materials,layers,budget", [(4, 5, 1024), (1, 10, 1)])
def test_exhaustive_small_spaces_do_not_depend_on_sobol(
    monkeypatch, materials: int, layers: int, budget: int,
) -> None:
    def forbidden(*_args):
        raise AssertionError("exhaustive recipe spaces must not use sampling")

    monkeypatch.setattr(sampling, "_sobol_points", forbidden)
    monkeypatch.setattr(sampling, "_rng_points", forbidden)
    batch = sampling.generate_candidate_recipes(
        material_count=materials, layer_count=layers, candidate_budget=budget, seed=7,
    )
    assert batch.recipes.shape == (budget, layers)
    assert np.unique(batch.recipes, axis=0).shape[0] == budget
    assert np.all((batch.recipes >= 0) & (batch.recipes < materials))
