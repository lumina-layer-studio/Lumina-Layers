"""Build sponsor-only starter seed collections from a verified public/v1 snapshot.

By default the generated starter packs (`lumina-materials-seed.zip` and
`lumina-luts-seed.zip`) contain `official` channel calibrations and approved
single-brand calibrations from Lumina's sponsor and partner roster. Run from
the repository root with `python -m scripts.build_sponsor_seeds` to stage them.

Original distribution package ZIPs remain byte-for-byte intact. This script
never contacts any remote server.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

# Canonical sponsor & partner filament brands aligned with Official-website
# (`pages/sponsors.vue`) and Lumina Wiki (`docs/project/sponsors/sponsors.mdx`).
SPONSOR_BRAND_GROUPS: dict[str, dict[str, tuple[str, ...]]] = {
    "funding_sponsors": {
        "liushuo": ("liushuo", "六朔"),
        "aliz": ("aliz", "爱丽兹", "爱丽兹三维科技", "aliz爱丽兹"),
        "ching_leung": ("ching leung", "精亮", "精亮科技"),
    },
    "filament_sponsors": {
        "alchemakes": ("alchemakes", "魔创"),
        "antinsky": ("antinsky", "蚁在云端"),
        "anycubic": ("anycubic", "纵维立方"),
        "bambu_lab": ("bambu lab", "bambulab", "拓竹", "bambu lab 拓竹"),
        "bing3d": ("bing3d", "必应"),
        "biqu": ("biqu", "必趣", "biqu必趣"),
        "cailab": ("cailab", "彩多屋"),
        "elegoo": ("elegoo", "爱乐酷", "elegoo爱乐酷"),
        "inslogic": ("inslogic",),
        "kynix": ("kynix",),
        "polymaker": ("polymaker",),
        "rebirth3d": ("rebirth3d", "瑞贝思"),
        "sailner": ("sailner", "赛纳", "赛纳三维"),
        "snapmaker": ("snapmaker", "快造", "快造科技", "快造3d", "snapmaker 3d"),
        "xyd": ("xyd", "xyd小明", "xyd小明耗材", "小明电子科技", "xyd xiaoming"),
    },
    "special_thanks_partners": {
        "karvax": ("karvax", "wjxc", "无境新材", "无境"),
    },
}

_NON_WORD_RE = re.compile(r"[\s_\-·/]+", re.UNICODE)


def _norm_token(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return _NON_WORD_RE.sub("", value.strip().casefold())


SPONSOR_ALIAS_TO_CANONICAL: dict[str, str] = {
    _norm_token(alias): canonical
    for group in SPONSOR_BRAND_GROUPS.values()
    for canonical, aliases in group.items()
    for alias in (canonical, *aliases)
    if _norm_token(alias)
}

DISALLOWED_MIXED_TOKENS: frozenset[str] = frozenset(
    _norm_token(label)
    for label in ("混合品牌", "mixed", "mixed brand", "mixed brands", "custom")
)


def canonical_sponsor_brand(row: dict[str, Any]) -> str | None:
    """Return canonical sponsor key if `row` belongs strictly to one sponsor brand."""
    display = row.get("display") if isinstance(row.get("display"), dict) else {}
    brand_identity = (
        display.get("brand_identity")
        if isinstance(display.get("brand_identity"), dict)
        else {}
    )

    candidates = [
        brand_identity.get("key"),
        brand_identity.get("label"),
        display.get("brand"),
        display.get("manufacturer"),
        row.get("brand"),
    ]
    names = brand_identity.get("names")
    if isinstance(names, dict):
        candidates.extend(names.values())

    for raw in candidates:
        token = _norm_token(raw)
        if token in DISALLOWED_MIXED_TOKENS:
            return None

    matched = {
        SPONSOR_ALIAS_TO_CANONICAL[_norm_token(raw)]
        for raw in candidates
        if _norm_token(raw) in SPONSOR_ALIAS_TO_CANONICAL
    }
    if len(matched) != 1:
        return None
    sponsor_key = next(iter(matched))

    # Every named slot must resolve to the same sponsor as the LUT.
    filaments = display.get("filaments")
    if isinstance(filaments, list):
        for slot in filaments:
            if not isinstance(slot, dict):
                continue
            slot_brand = _norm_token(slot.get("brand"))
            if not slot_brand:
                continue
            if SPONSOR_ALIAS_TO_CANONICAL.get(slot_brand) != sponsor_key:
                return None

    return sponsor_key


def is_eligible_for_starter_seed(row: dict[str, Any]) -> bool:
    """Official calibrations and single-brand sponsor calibrations qualify."""
    channel = row.get("channel")
    if channel == "official":
        return True
    if channel != "community":
        return False
    return canonical_sponsor_brand(row) is not None


def _encoded_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _write_stored_member(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.compress_type = zipfile.ZIP_STORED
    archive.writestr(info, payload)


def build_seed_release(
    public_dir: Path,
    output_dir: Path,
    dataset_version: str,
    *,
    sponsor_only: bool = True,
) -> dict[str, Any]:
    """Build `lumina-materials-seed.zip`, `lumina-luts-seed.zip`, and `resource-release.json`."""
    if not dataset_version or not dataset_version.strip():
        raise ValueError("dataset_version must be a non-empty string")
    license_path = public_dir / "DATA-LICENSE.md"
    if not license_path.is_file():
        raise FileNotFoundError(f"Missing DATA-LICENSE.md in {public_dir}")
    license_text = license_path.read_bytes()

    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, dict[str, Any]] = {}
    included_brands: dict[str, set[str]] = {"materials": set(), "luts": set()}

    specs = (
        ("materials", "materials", "material_id", "lumina_material_bundle.json", "lumina_material_seed.json", "lumina_material_seed", "material_count"),
        ("luts", "items", "lut_id", "lumina_lut_bundle.json", "lumina_lut_seed.json", "lumina_lut_seed", "lut_count"),
    )

    for kind, rows_key, id_field, bundle_manifest_name, seed_manifest_name, seed_kind, count_field in specs:
        catalog_path = public_dir / kind / "catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        rows = catalog.get(rows_key)
        if not isinstance(rows, list):
            raise ValueError(f"Invalid {kind} catalog rows in {catalog_path}")

        entries: list[dict[str, Any]] = []
        identities: set[tuple[str, str]] = set()
        destination = output_dir / f"lumina-{kind}-seed.zip"

        with zipfile.ZipFile(destination, "w") as archive:
            for row in sorted(rows, key=lambda item: (item[id_field], item["revision_id"])):
                identity = (row[id_field], row["revision_id"])
                if identity in identities or row.get("channel") not in {"official", "community"}:
                    raise ValueError("Only unique approved public revisions belong in the collection")
                identities.add(identity)

                if sponsor_only and not is_eligible_for_starter_seed(row):
                    continue

                sponsor_key = canonical_sponsor_brand(row)
                if sponsor_key:
                    included_brands[kind].add(sponsor_key)

                relative = PurePosixPath(row["package_url"])
                if relative.is_absolute() or ".." in relative.parts or "\\" in str(relative):
                    raise ValueError("The snapshot must contain local distribution package paths")
                payload = (public_dir / relative).read_bytes()
                digest = hashlib.sha256(payload).hexdigest()
                expected_sha = str(row["package_sha256"]).removeprefix("sha256:")
                if digest != expected_sha or len(payload) != row["package_bytes"]:
                    raise ValueError(f"Distribution package {relative} failed its checksum")

                with zipfile.ZipFile(io.BytesIO(payload)) as original:
                    manifest = json.loads(original.read(bundle_manifest_name))
                    original_package = manifest["packages"][0] if kind == "materials" else manifest

                for field in (id_field, "revision_id", "content_hash", "channel"):
                    if row[field] != original_package[field]:
                        raise ValueError(f"Snapshot {field} differs from its package for {row[id_field]}")

                member_path = f"packages/{digest}.zip"
                _write_stored_member(archive, member_path, payload)
                entries.append(
                    {
                        **original_package,
                        "display": row.get("display", original_package.get("display", {})),
                        "path": member_path,
                        "package_sha256": digest,
                        "package_bytes": len(payload),
                    }
                )

            if not entries:
                raise ValueError(f"No {kind} entries matched starter seed selection")

            _write_stored_member(
                archive,
                seed_manifest_name,
                _encoded_json(
                    {
                        "kind": seed_kind,
                        "schema_version": "1.0",
                        "dataset_version": dataset_version,
                        "packages": entries,
                    }
                ),
            )
            _write_stored_member(archive, "DATA-LICENSE.md", license_text)

        archive_bytes = destination.read_bytes()
        artifacts[kind] = {
            "path": destination.name,
            "bytes": len(archive_bytes),
            "sha256": hashlib.sha256(archive_bytes).hexdigest(),
            "manifest": seed_manifest_name,
            count_field: len(entries),
            "download_url": (
                f"https://github.com/lumina-layer-studio/Lumina-materials/"
                f"releases/download/v{dataset_version}/{destination.name}"
            ),
        }

    selection: dict[str, Any] = {
        "basis": (
            "official_and_sponsor_brands"
            if sponsor_only
            else "all_current_approved_public_resources"
        ),
        "publication_review": True,
        "calibration_review": False,
    }
    if sponsor_only:
        selection["sponsor_brands"] = sorted(
            included_brands["materials"] | included_brands["luts"]
        )

    release = {
        "kind": "lumina_resource_release",
        "schema_version": 1,
        "dataset_version": dataset_version,
        "artifacts": artifacts,
        "selection": selection,
        "licenses": {
            "new_contributions": "LicenseRef-Lumina-Data-1.0 with explicit contributor consent",
            "existing_data": "Original per-resource licenses and source information are retained; no retroactive relicensing",
        },
    }
    (output_dir / "resource-release.json").write_bytes(
        json.dumps(release, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    )
    return release


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-dir", type=Path, required=True, help="Verified public/v1 snapshot directory")
    parser.add_argument("--output", type=Path, required=True, help="Directory for built release artifacts")
    parser.add_argument("--dataset-version", required=True, help="Dataset version string (e.g. 2026.11.20.1)")
    parser.add_argument(
        "--all-public",
        action="store_true",
        help="Include all public resources instead of filtering to official and sponsor brands",
    )
    parser.add_argument(
        "--stage-runtime",
        type=Path,
        default=None,
        help="Optional runtime resources directory to stage materials/, luts/, and resource-release.json",
    )
    args = parser.parse_args()
    result = build_seed_release(
        args.public_dir,
        args.output,
        args.dataset_version,
        sponsor_only=not args.all_public,
    )
    if args.stage_runtime is not None:
        from scripts.prepare_public_resources import prepare_resources

        prepare_resources(
            args.output / "resource-release.json",
            args.stage_runtime,
            source_dir=args.output,
        )
    print(
        json.dumps(
            {
                "dataset_version": result["dataset_version"],
                "selection": result["selection"],
                "artifacts": result["artifacts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
