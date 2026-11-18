"""Prepare selected local calibration data for the existing Registry intake."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Literal
import zipfile

from core.filament_display import filament_display
from core.lut_details.parser import LutParser
from core.lut_board_preview import lut_board_preview
from core.single_stage import material_files, material_package, material_runs
from utils.lut_manager import LUTManager

ResourceKind = Literal["materials", "luts"]
MAX_FILE_BYTES = 50 * 1024 * 1024
DATA_LICENSE_ID = "LicenseRef-Lumina-Data-1.0"


def json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_resource(path: Path) -> bytes:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("The selected resource exceeds the 50 MiB contribution limit.")
    return path.read_bytes()


@dataclass
class PreparedContribution:
    kind: ResourceKind
    key: str
    fingerprint: str
    display: dict[str, Any]
    compatibility: dict[str, Any]
    files: dict[str, bytes]
    resource_id: str | None = None

    def summary(self) -> dict[str, Any]:
        return {"kind": self.kind, "key": self.key, "fingerprint": self.fingerprint,
                "display": self.display, "compatibility": self.compatibility,
                "bytes": sum(len(value) for value in self.files.values())}


def prepare_contribution(kind: ResourceKind, key: str) -> PreparedContribution:
    if kind == "materials":
        directory = material_files.resolve_saved_material_dir(Path(material_files.MATERIALS_DIR), key)
        archive_bytes = read_resource(directory / "material.json")
        archive = json.loads(archive_bytes)
        if not isinstance(archive, dict):
            raise ValueError("The material archive must contain a JSON object.")
        params_bytes = read_resource(material_files._resolve_stage_a_params_path(directory, archive))
        params = json.loads(params_bytes)
        if not isinstance(params, dict) or not isinstance(params.get("parameters"), dict):
            raise ValueError("The material archive needs fitted Stage A parameters.")
        for document, fields in ((archive, ("material_summary", "fit_summary")),
                                 (params, ("meta", "source"))):
            if any(field in document and not isinstance(document[field], dict) for field in fields):
                raise ValueError("Calibration metadata must contain JSON objects.")
        display = material_package._display_payload_from_material_archive(archive, key)
        display.update(material_runs.measured_gradient_preview(archive))
        display["material_type"] = material_files._picker_metadata_from_archive(
            archive, material_name=display["material_name"], relative_directory_name=key,
        ).get("material_type") or display.get("material_type", "")
        # Only distribution data: no source photos, local paths, verification history or usage.
        public_archive = {field: archive[field] for field in (
            "schema_version", "kind", "material_name", "brand", "created_at", "updated_at",
            "fit_summary", "material_summary", "verification_count",
        ) if field in archive}
        public_archive["stage_a_params_file"] = "stage_A_parameters.json"
        public_params = {field: params[field] for field in (
            "param_type", "parameters", "fitted_substrates", "validation",
        ) if field in params}
        public_params["meta"] = {field: params.get("meta", {})[field] for field in (
            "schema_version", "generated_at", "workflow", "image_source", "verification_count", "aggregation_method",
        ) if field in params.get("meta", {})}
        # Geometry is needed to reproduce model previews; file provenance is not.
        public_params["source"] = {"spec": params.get("source", {}).get("spec", {})}
        return PreparedContribution(kind, key, sha(archive_bytes + b"\0" + params_bytes), display,
                                    {"material_schema_version": str(archive.get("schema_version", "1.1")),
                                     "layer_height_mm": archive.get("material_summary", {}).get("layer_height_mm")},
                                    {"material.json": json_bytes(public_archive),
                                     "stage_A_parameters.json": json_bytes(public_params)})
    path_value = LUTManager.get_lut_path(key)
    if not path_value:
        raise FileNotFoundError("The selected LUT is no longer in the local library.")
    path = Path(path_value)
    payload = read_resource(path)
    parsed = LutParser().parse(name=key, path=path)
    display = filament_display(parsed.raw_metadata)
    display.update(lut_board_preview(parsed.rgb, parsed.color_mode, parsed.raw_metadata))
    display.update({"name": key, "brand": parsed.metadata.manufacturer, "material_type": parsed.metadata.type})
    # Product metadata is indexed by the actual zero-based channel. Never infer
    # channel order from a product name or from the order of metadata records.
    slots = display.get("filaments", [])
    valid_slots = [row["slot"] for row in slots if type(row.get("slot")) is int]
    by_slot = {row["slot"]: row for row in slots} if (
        len(valid_slots) == len(slots) == len(parsed.metadata.palette)
        and set(valid_slots) == set(range(len(parsed.metadata.palette)))
    ) else {}
    display["filaments"] = [
        {**by_slot.get(index, {}), "slot": index,
         "color_name": by_slot.get(index, {}).get("color_name") or entry.color_name or entry.color,
         **({"color_hex": entry.hex_color} if entry.hex_color else {})}
        for index, entry in enumerate(parsed.metadata.palette)
    ]
    compatibility = {"color_mode": parsed.color_mode,
                     "layer_height_mm": parsed.metadata.layer_height_mm,
                     "max_color_layers": parsed.metadata.max_color_layers,
                     "base_channel_idx": parsed.metadata.base_channel_idx,
                     "layer_order": parsed.metadata.layer_order}
    return PreparedContribution(kind, key, sha(payload), display, compatibility,
                                {"calibration" + path.suffix.lower(): payload})


def with_contribution_license(prepared: PreparedContribution, display: dict[str, Any]) -> dict[str, Any]:
    """Preserve declared terms; the new agreement applies only to declared originals."""
    result = dict(display)
    license_id = next((value for value in (prepared.display.get("license"), display.get("license"))
                       if isinstance(value, str) and value.strip()), None)
    if not license_id and (display.get("attribution") or {}).get("relationship") == "original":
        license_id = DATA_LICENSE_ID
    if license_id:
        result["license"] = license_id
    else:
        result.pop("license", None)
    return result


def contribution_package(prepared: PreparedContribution, display: dict[str, Any],
                         subject: str) -> tuple[bytes, str, str]:
    """Keep LUT bytes untouched and assign a contributor-scoped resource identity."""
    display = with_contribution_license(prepared, display)
    files = dict(prepared.files)
    family = "mat" if prepared.kind == "materials" else "lut"
    resource_id = prepared.resource_id or family + "_" + sha(f"{subject}\n{prepared.key}".encode())[:26]
    if prepared.kind == "materials":
        archive = json.loads(files["material.json"])
        archive.update(display)
        archive["display"] = display
        files["material.json"] = json_bytes(archive)
        prefix = f"materials/{resource_id}/"
        roles = {"material.json": "material_archive", "stage_A_parameters.json": "stage_a_parameters"}
    else:
        prefix = ""
        roles = {name: "lut_file" for name in files}
    records = [{"path": prefix + name, "role": roles[name], "sha256": sha(data),
                "bytes": len(data), "required": True} for name, data in files.items()]
    content_hash = (material_package._material_content_hash_from_file_records(records)
                    if prepared.kind == "materials" else "sha256:" + records[0]["sha256"])
    # A corrected public description can form a new revision of the same calibration.
    revision_id = "rev_" + sha(json_bytes({"content": content_hash, "display": display}))[:26]
    item = {f"{family if family == 'lut' else 'material'}_id": resource_id,
            "revision_id": revision_id, "content_hash": content_hash,
            "display": display, "compatibility": prepared.compatibility, "files": records}
    if prepared.kind == "materials":
        item.update({"local_directory": resource_id, "channel": "community", "visibility": "community"})
        manifest_name = "lumina_material_bundle.json"
        manifest = {"kind": "lumina_material_bundle", "schema_version": "2.0", "packages": [item]}
    else:
        manifest_name = "lumina_lut_bundle.json"
        manifest = {"kind": "lumina_lut_bundle", "schema_version": "1.0", **item}
    buffer = io.BytesIO()
    # Small calibration files need no aggressive compression; predictable size guards
    # also apply to highly repetitive LUTs.
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in files.items():
            archive.writestr(prefix + name, data)
        archive.writestr(manifest_name, json_bytes(manifest))
    return buffer.getvalue(), resource_id, revision_id


def prepare_owned_revision(kind: ResourceKind, resource_id: str, revision_id: str, payload: bytes,
                           display: dict[str, Any]) -> PreparedContribution:
    """Rebuild an owner-only revision from verified distribution files, without installation."""
    if len(payload) > MAX_FILE_BYTES:
        raise ValueError("The selected revision exceeds the contribution limit.")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        infos = archive.infolist()
        if len(infos) > 20 or sum(info.file_size for info in infos) > MAX_FILE_BYTES:
            raise ValueError("The selected revision exceeds the contribution limit.")
        if len({info.filename for info in infos}) != len(infos):
            raise ValueError("The revision archive contains duplicate entries.")
        manifest = json.loads(archive.read("lumina_material_bundle.json" if kind == "materials" else "lumina_lut_bundle.json"))
        if not isinstance(manifest, dict):
            raise ValueError("Invalid revision manifest.")
        packages = manifest.get("packages")
        if kind == "materials" and (not isinstance(packages, list) or len(packages) != 1):
            raise ValueError("Select a single material revision.")
        item = packages[0] if kind == "materials" else manifest
        if not isinstance(item, dict) or not isinstance(item.get("files"), list):
            raise ValueError("Invalid revision files.")
        if item.get("material_id" if kind == "materials" else "lut_id") != resource_id or item.get("revision_id") != revision_id:
            raise ValueError("The server revision identity changed. Refresh your submissions.")
        files: dict[str, bytes] = {}
        roles = {"material_archive": "material.json", "stage_a_parameters": "stage_A_parameters.json"}
        for record in item["files"]:
            if not isinstance(record, dict) or not isinstance(record.get("path"), str) or not isinstance(record.get("sha256"), str):
                raise ValueError("Invalid revision file declaration.")
            path = Path(record["path"])
            if path.is_absolute() or any(part in {".", ".."} for part in path.parts):
                raise ValueError("Invalid revision file path.")
            data = archive.read(record["path"])
            if len(data) != record["bytes"] or sha(data) != record["sha256"].removeprefix("sha256:"):
                raise ValueError("The revision file failed its integrity check.")
            name = roles.get(record["role"]) if kind == "materials" else "calibration" + path.suffix.lower()
            if not name or name in files:
                raise ValueError("Unsupported revision files.")
            files[name] = data
        if kind == "materials" and set(files) != set(roles.values()) or kind == "luts" and len(files) != 1:
            raise ValueError("Incomplete revision files.")
    return PreparedContribution(kind, f"revision:{resource_id}:{revision_id}", sha(payload), dict(display),
                                item.get("compatibility") if isinstance(item.get("compatibility"), dict) else {}, files, resource_id)
