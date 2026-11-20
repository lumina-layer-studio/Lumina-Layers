"""Tests for sponsor-only starter seed collection building."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from api.lut_seed import lut_seed_catalog
from api.material_seed import material_seed_catalog
from scripts.build_sponsor_seeds import (
    canonical_sponsor_brand,
    is_eligible_for_starter_seed,
)


def _make_material_bundle(material_id: str, revision_id: str, channel: str, brand: str) -> tuple[bytes, str, str]:
    mat_bytes = json.dumps({"brand": brand, "material_name": f"{brand} PLA"}).encode("utf-8")
    stage_bytes = json.dumps({"parameters": {"channels": [], "substrates": []}}).encode("utf-8")
    mat_sha = hashlib.sha256(mat_bytes).hexdigest()
    stage_sha = hashlib.sha256(stage_bytes).hexdigest()
    content_hash = f"sha256:{hashlib.sha256((mat_sha + stage_sha).encode('utf-8')).hexdigest()}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"materials/{brand}/pla/material.json", mat_bytes)
        zf.writestr(f"materials/{brand}/pla/stage_A_parameters.json", stage_bytes)
        zf.writestr(
            "lumina_material_bundle.json",
            json.dumps(
                {
                    "kind": "lumina_material_bundle",
                    "schema_version": "2.0",
                    "packages": [
                        {
                            "material_id": material_id,
                            "revision_id": revision_id,
                            "content_hash": content_hash,
                            "channel": channel,
                            "visibility": channel,
                            "local_directory": f"{brand}/pla",
                            "display": {"brand": brand, "material_name": f"{brand} PLA"},
                            "files": [
                                {
                                    "path": f"materials/{brand}/pla/material.json",
                                    "role": "material_archive",
                                    "sha256": mat_sha,
                                    "bytes": len(mat_bytes),
                                    "required": True,
                                },
                                {
                                    "path": f"materials/{brand}/pla/stage_A_parameters.json",
                                    "role": "stage_a_parameters",
                                    "sha256": stage_sha,
                                    "bytes": len(stage_bytes),
                                    "required": True,
                                },
                            ],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )
    raw = buf.getvalue()
    return raw, hashlib.sha256(raw).hexdigest(), content_hash


def _make_lut_bundle(lut_id: str, revision_id: str, channel: str, brand: str, local_path: str) -> tuple[bytes, str, str]:
    lut_payload = json.dumps(
        {
            "color_mode": "4-color",
            "entries": [{"rgb": [255, 0, 0], "stack": [0, 0, 0, 0, 0]}],
        }
    ).encode("utf-8")
    lut_sha = hashlib.sha256(lut_payload).hexdigest()
    content_hash = f"sha256:{lut_sha}"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"luts/{local_path}", lut_payload)
        zf.writestr(
            "lumina_lut_bundle.json",
            json.dumps(
                {
                    "kind": "lumina_lut_bundle",
                    "schema_version": "1.0",
                    "lut_id": lut_id,
                    "revision_id": revision_id,
                    "content_hash": content_hash,
                    "channel": channel,
                    "local_path": local_path,
                    "compatibility": {"color_mode": "4-color", "file_format": "json"},
                    "display": {"brand": brand, "name": f"{brand} · RYBW"},
                    "files": [
                        {
                            "path": f"luts/{local_path}",
                            "role": "lut_file",
                            "sha256": lut_sha,
                            "bytes": len(lut_payload),
                            "required": True,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
        )
    raw = buf.getvalue()
    return raw, hashlib.sha256(raw).hexdigest(), content_hash


def test_sponsor_brand_matching_excludes_non_sponsors_and_mixed_rows():
    assert canonical_sponsor_brand({"display": {"brand": "Aliz"}}) == "aliz"
    assert canonical_sponsor_brand({"display": {"brand": "Alchemakes"}}) == "alchemakes"
    assert canonical_sponsor_brand({"display": {"brand_identity": {"key": "wjxc", "label": "wjxc"}}}) == "karvax"
    assert canonical_sponsor_brand({"display": {"brand": "六朔"}}) == "liushuo"
    assert canonical_sponsor_brand({"display": {"brand": "R3D"}}) is None
    assert canonical_sponsor_brand({"display": {"brand": "三慈"}}) is None
    assert canonical_sponsor_brand({"display": {"brand_identity": {"key": "混合品牌", "label": "混合品牌"}}}) is None

    # A LUT labeled under a sponsor brand that actually mixes a non-sponsor slot is rejected.
    mixed_slot_lut = {
        "channel": "community",
        "display": {
            "brand": "Sailner",
            "filaments": [
                {"brand": "Sailner"},
                {"brand": "SUNLU"},
            ],
        },
    }
    assert not is_eligible_for_starter_seed(mixed_slot_lut)
    assert is_eligible_for_starter_seed({"channel": "official", "display": {"brand": "UnlistedOfficial"}})


def test_build_seed_release_filters_to_sponsors_and_passes_runtime_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    public_dir = tmp_path / "public_v1"
    (public_dir / "materials").mkdir(parents=True)
    (public_dir / "packages").mkdir(parents=True)
    (public_dir / "luts/packages").mkdir(parents=True)
    (public_dir / "DATA-LICENSE.md").write_text("LicenseRef-Lumina-Data-1.0\n", encoding="utf-8")

    sponsor_mat, sponsor_mat_sha, sponsor_mat_content = _make_material_bundle("mat_aliz", "rev_1", "community", "Aliz")
    other_mat, other_mat_sha, other_mat_content = _make_material_bundle("mat_r3d", "rev_1", "community", "R3D")
    (public_dir / "packages" / f"{sponsor_mat_sha}.zip").write_bytes(sponsor_mat)
    (public_dir / "packages" / f"{other_mat_sha}.zip").write_bytes(other_mat)

    (public_dir / "materials/catalog.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "materials": [
                    {
                        "material_id": "mat_aliz",
                        "revision_id": "rev_1",
                        "content_hash": sponsor_mat_content,
                        "channel": "community",
                        "package_url": f"packages/{sponsor_mat_sha}.zip",
                        "package_sha256": f"sha256:{sponsor_mat_sha}",
                        "package_bytes": len(sponsor_mat),
                        "display": {"brand": "Aliz", "material_name": "Aliz PLA"},
                    },
                    {
                        "material_id": "mat_r3d",
                        "revision_id": "rev_1",
                        "content_hash": other_mat_content,
                        "channel": "community",
                        "package_url": f"packages/{other_mat_sha}.zip",
                        "package_sha256": f"sha256:{other_mat_sha}",
                        "package_bytes": len(other_mat),
                        "display": {"brand": "R3D", "material_name": "R3D PLA"},
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    sponsor_lut, sponsor_lut_sha, sponsor_lut_content = _make_lut_bundle("lut_liushuo", "rev_1", "community", "六朔", "liushuo/cmyw.json")
    mixed_lut, mixed_lut_sha, mixed_lut_content = _make_lut_bundle("lut_mixed", "rev_1", "community", "六朔", "liushuo/mixed.json")
    (public_dir / "luts/packages" / f"{sponsor_lut_sha}.zip").write_bytes(sponsor_lut)
    (public_dir / "luts/packages" / f"{mixed_lut_sha}.zip").write_bytes(mixed_lut)

    (public_dir / "luts/catalog.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "items": [
                    {
                        "lut_id": "lut_liushuo",
                        "revision_id": "rev_1",
                        "content_hash": sponsor_lut_content,
                        "channel": "community",
                        "package_url": f"luts/packages/{sponsor_lut_sha}.zip",
                        "package_sha256": f"sha256:{sponsor_lut_sha}",
                        "package_bytes": len(sponsor_lut),
                        "display": {
                            "brand": "六朔",
                            "name": "PETG · CMYW",
                            "filaments": [{"brand": name} for name in ("六朔", "Liu Shuo", "六朔", "liushuo")],
                        },
                    },
                    {
                        "lut_id": "lut_mixed",
                        "revision_id": "rev_1",
                        "content_hash": mixed_lut_content,
                        "channel": "community",
                        "package_url": f"luts/packages/{mixed_lut_sha}.zip",
                        "package_sha256": f"sha256:{mixed_lut_sha}",
                        "package_bytes": len(mixed_lut),
                        "display": {
                            "brand": "六朔",
                            "name": "PETG · CMYW",
                            "filaments": [{"brand": name} for name in ("六朔", "拓竹", "六朔", "六朔")],
                        },
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    release_dir = tmp_path / "release"
    staged_dir = tmp_path / "staged"
    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.build_sponsor_seeds",
            "--public-dir", str(public_dir),
            "--output", str(release_dir),
            "--dataset-version", "2026.11.20.test",
            "--stage-runtime", str(staged_dir),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=True,
    )
    release = json.loads(result.stdout)
    assert release["selection"]["basis"] == "official_and_sponsor_brands"
    assert release["artifacts"]["materials"]["material_count"] == 1
    assert release["artifacts"]["luts"]["lut_count"] == 1

    monkeypatch.setenv("LUMINA_MATERIALS_SEED_PATH", str(staged_dir / "materials/lumina-materials-seed.zip"))
    monkeypatch.setenv("LUMINA_LUTS_SEED_PATH", str(staged_dir / "luts/lumina-luts-seed.zip"))

    mat_items = material_seed_catalog()["items"]
    lut_items = lut_seed_catalog()["items"]
    assert [item["resource_id"] for item in mat_items] == ["mat_aliz"]
    assert [item["resource_id"] for item in lut_items] == ["lut_liushuo"]
