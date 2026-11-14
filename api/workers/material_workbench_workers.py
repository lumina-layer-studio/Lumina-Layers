"""Picklable material-workbench entry points; inputs are paths and scalars."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

from core.material_lut_synthesis import load_multiple_materials

if TYPE_CHECKING:
    from core.material_cache_overview import DynamicLayerCachePrepareResult
    from core.material_color_solver import MaterialParams
    from core.material_gamut_coverage import GamutContributionResult, GamutCoverageResult


class MaterialWorkbenchParams(TypedDict):
    directory_names: list[str]
    materials_dir: str
    cache_root: str
    layer_mode: str
    layer_count: int
    min_layer_count: int | None
    backing_index: int | None
    layer_height_mm: float
    substrate: str
    max_points: int


def _load_materials(params: MaterialWorkbenchParams) -> list[MaterialParams]:
    return load_multiple_materials(params["directory_names"], materials_dir=params["materials_dir"])


def worker_material_gamut_coverage(params: MaterialWorkbenchParams) -> GamutCoverageResult:
    from core.material_gamut_coverage import compute_dynamic_layer_gamut, compute_fixed_layer_gamut

    materials = _load_materials(params)
    if params["layer_mode"] == "dynamic":
        return compute_dynamic_layer_gamut(
            materials, int(params["backing_index"]), params["layer_height_mm"],
            params["substrate"], int(params["min_layer_count"]), params["layer_count"],
            max_points=params["max_points"], cache_root=params["cache_root"],
        )
    return compute_fixed_layer_gamut(
        materials, params["layer_count"], params["layer_height_mm"], params["substrate"],
        max_points=params["max_points"], cache_root=params["cache_root"],
    )


def worker_material_gamut_contributions(params: MaterialWorkbenchParams) -> GamutContributionResult:
    from core.material_gamut_coverage import compute_material_contributions

    return compute_material_contributions(
        _load_materials(params), params["layer_count"], params["layer_height_mm"], params["substrate"],
    )


def worker_material_cache_prepare(params: MaterialWorkbenchParams) -> DynamicLayerCachePrepareResult:
    from core.material_cache_overview import prepare_dynamic_layer_cache

    return prepare_dynamic_layer_cache(
        _load_materials(params), int(params["backing_index"]), params["layer_height_mm"],
        params["substrate"], int(params["min_layer_count"]), params["layer_count"],
        cache_root=params["cache_root"],
    )


def worker_material_cache_delete(params: MaterialWorkbenchParams) -> bool:
    from core.material_cache_overview import delete_dynamic_layer_cache

    return delete_dynamic_layer_cache(
        _load_materials(params), int(params["backing_index"]), params["layer_height_mm"],
        params["substrate"], int(params["min_layer_count"]), params["layer_count"],
        cache_root=params["cache_root"],
    )
