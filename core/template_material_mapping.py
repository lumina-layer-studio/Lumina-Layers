"""Prepare derived template routing maps without changing saved material data."""

from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING, Any, Mapping

from core.errors import TemplateMaterialMappingError

if TYPE_CHECKING:
    from utils.fatcat_metadata import MetadataTarget


def prepare_template_for_export(
    template: Mapping[str, Any], *, target: MetadataTarget,
) -> dict[str, Any]:
    """Invalidate stale automatic Bambu routing caches on an export-only copy."""
    prepared = deepcopy(dict(template))
    if target.slicer_id != "BambuStudio":
        return prepared

    from utils.fatcat_metadata import read_project_material_slots

    material_count = len(read_project_material_slots(prepared, target=target))
    if not material_count:
        return prepared
    mode = prepared.get("filament_map_mode")
    automatic_modes = {"Auto For Flush", "Auto For Match"}
    known_modes = automatic_modes | {"Manual", "Nozzle Manual"}
    safe_mode = mode if isinstance(mode, str) and mode in known_modes else "unspecified"
    for field in ("filament_nozzle_map", "filament_volume_map"):
        values = prepared.get(field)
        # FatCat supports native singleton broadcasts and equal per-slot groups.
        # Leave those layouts and missing fields to its existing composition rules.
        if not isinstance(values, list) or len(values) <= 1 or len(values) % material_count == 0:
            continue
        if safe_mode in automatic_modes:
            # Bambu rebuilds these derived maps after automatic grouping. They
            # can lag behind an added material in a saved project. Never fill in
            # manual assignments or replace the material preset/variant arrays.
            prepared.pop(field)
        else:
            raise TemplateMaterialMappingError(field, material_count, len(values), safe_mode)
    return prepared
