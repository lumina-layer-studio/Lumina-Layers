"""Resolve account resource identities from verified local installations."""

import hashlib
import json
from pathlib import Path
from typing import Any


def local_resource_references(kind: str) -> dict[str, Any]:
    """Link installed data by verified identity, never by a display name alone."""
    items: dict[str, dict[str, str]] = {}
    if kind == "luts":
        from api.services.lut_registry_sync import read_installed_index
        from utils.lut_manager import LUTManager
        records = read_installed_index().get("luts", {})
        by_hash: dict[str, dict[str, Any]] = {}
        ambiguous: set[str] = set()
        for row in records.values():
            if not all(row.get(key) for key in ("lut_id", "revision_id", "content_hash")):
                continue
            digest = row["content_hash"].removeprefix("sha256:")
            if digest in by_hash and by_hash[digest]["lut_id"] != row["lut_id"]:
                ambiguous.add(digest)
            by_hash[digest] = row
        for name, raw_path in LUTManager.get_all_lut_files().items():
            try:
                digest = hashlib.sha256(Path(raw_path).read_bytes()).hexdigest()
                row = by_hash.get(digest) if digest not in ambiguous else None
                if row:
                    items[name] = {"resource_id": row["lut_id"], "revision_id": row["revision_id"],
                                   "content_hash": row["content_hash"]}
            except OSError:
                continue
    else:
        from core.single_stage.material_sync import catalog_material_source, get_material_sync_status
        from core.single_stage.material_files import MATERIALS_DIR, resolve_saved_material_dir
        from core.single_stage.material_package import _local_material_content_hash
        for row in get_material_sync_status()["installed"]:
            try:
                if not row.get("material_file_exists") or catalog_material_source(row) is None:
                    continue
                directory = resolve_saved_material_dir(Path(MATERIALS_DIR), row["local_directory"])
                metadata = json.loads((directory / "material.json").read_text(encoding="utf-8"))
                if _local_material_content_hash(directory, metadata) != row["content_hash"]:
                    continue
                items[row["local_directory"]] = {"resource_id": row["material_id"], "revision_id": row["revision_id"],
                                                 "content_hash": row["content_hash"]}
            except (OSError, ValueError, KeyError):
                continue
    return {"items": items}


def local_resource_origin(kind: str, key: str) -> dict[str, Any] | None:
    """Retain the installed source even after local edits; inspect only this item."""
    if kind == "materials":
        from core.single_stage.material_sync import catalog_material_source, get_material_sync_status
        from core.single_stage.material_files import MATERIALS_DIR, resolve_saved_material_dir
        from core.single_stage.material_package import _local_material_content_hash

        rows = get_material_sync_status()["installed"]
        row = next((row for row in rows if row.get("local_directory") == key and catalog_material_source(row) == "catalog"), None)
        if row is None:
            return None
        directory = resolve_saved_material_dir(Path(MATERIALS_DIR), key)
        metadata = json.loads((directory / "material.json").read_text(encoding="utf-8"))
        current_hash = _local_material_content_hash(directory, metadata)
        id_field = "material_id"
    else:
        from api.services.lut_registry_sync import read_installed_index, _safe_index_installed_path
        from utils.lut_manager import LUTManager

        path_value = LUTManager.get_lut_path(key)
        if not path_value:
            return None
        path = Path(path_value).resolve()
        current_hash = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        rows = list(read_installed_index().get("luts", {}).values())
        rows = [{**row, "content_hash": "sha256:" + str(row.get("content_hash", "")).removeprefix("sha256:")}
                for row in rows if isinstance(row, dict)]
        path_matches = [row for row in rows if _safe_index_installed_path(row) == path]
        row = max(path_matches, key=lambda row: (
            row.get("content_hash") == current_hash, str(row.get("installed_at") or ""),
        ), default=None)
        if row is None:
            matches = [row for row in rows if row.get("content_hash") == current_hash]
            if len({row.get("lut_id") for row in matches}) > 1:
                # The bytes are public, but the actual source cannot be inferred
                # from several authors' identical calibrations.
                return {"reference": None, "modified": False, "original_author": "", "rights_basis": ""}
            row = matches[0] if matches else None
        if row is None:
            return None
        id_field = "lut_id"
    if not all(isinstance(row.get(field), str) and row[field] for field in (id_field, "revision_id", "content_hash")):
        raise ValueError("The installed resource has incomplete source metadata.")
    display = row.get("display") if isinstance(row.get("display"), dict) else {}
    if kind == "materials" and not display:
        display = {**metadata, **(metadata.get("display") if isinstance(metadata.get("display"), dict) else {})}
    attribution = display.get("attribution") if isinstance(display.get("attribution"), dict) else {}
    return {
        "reference": {"kind": kind, "resource_id": row[id_field], "revision_id": row["revision_id"],
                      "content_hash": row["content_hash"]},
        "modified": current_hash != row["content_hash"],
        "original_author": next((value for value in (attribution.get("original_author"), display.get("contributor_name"), display.get("author"))
                                 if isinstance(value, str) and value.strip()), "")[:200],
        "rights_basis": display["license"][:1000] if isinstance(display.get("license"), str) else "",
        "license": display.get("license") if isinstance(display.get("license"), str) else None,
    }


def preserve_origin_license(display: dict[str, Any], origin: dict[str, Any] | None) -> dict[str, Any]:
    """Carry the installed manifest's declaration into a contribution snapshot."""
    license_id = origin.get("license") if origin else None
    if isinstance(license_id, str) and license_id.strip():
        return {**display, "license": license_id}
    return display
