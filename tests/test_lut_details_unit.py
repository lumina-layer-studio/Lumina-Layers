from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import msgpack
import numpy as np
import pytest
from config import LUTMetadata, PaletteEntry
from utils.lut_manager import LUTManager
from core.lut_details.aliases import AliasResolver
from core.lut_details.catalog import LutCatalogIndexer
from core.lut_details.parser import LutParser
from core.lut_details.service import LutDetailService


def _write_alias_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "manufacturers": {
                    "Bambu Lab": ["bambulab", "bambu", "bam", "ba", "拓竹", "拓"],
                    "Meta Vendor": ["metavendor"],
                },
                "materials": {
                    "PLA": ["pla", "pla basic", "plabasic", "pla+"],
                    "PETG": ["petg"],
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_lut_json(
    path: Path,
    *,
    manufacturer: str = "",
    material_type: str = "",
    extra: dict[str, object] | None = None,
) -> None:
    payload: dict[str, object] = {
        "manufacturer": manufacturer,
        "type": material_type,
        "palette": {
            "White": {
                "material": material_type or "PLA Basic",
                "hex_color": "#FFFFFF",
                "color_name": "White",
            },
            "Red": {
                "material": material_type or "PLA Basic",
                "hex_color": "#DC143C",
                "color_name": "Ruby Red",
            },
        },
        "entries": [
            {
                "rgb": [255, 255, 255],
                "lab": [100.0, 0.0, 0.0],
                "recipe": ["White", "White", "White", "White", "White"],
            },
            {
                "rgb": [220, 20, 60],
                "lab": [48.0, 67.0, 33.0],
                "recipe": ["Red", "White", "White", "White", "White"],
            },
            {
                "rgb": [120, 160, 240],
                "lab": [65.0, 12.0, -45.0],
                "recipe": ["Red", "Red", "White", "White", "White"],
            },
            {
                "rgb": [40, 200, 120],
                "lab": [72.0, -52.0, 28.0],
                "recipe": ["Red", "Red", "Red", "White", "White"],
            },
        ],
        "max_color_layers": 5,
        "layer_height_mm": 0.08,
        "line_width_mm": 0.42,
        "base_layers": 10,
        "base_channel_idx": 0,
        "layer_order": "Top2Bottom",
        "color_mode": "4-Color (RYBW)",
        "name": path.stem,
    }
    if extra:
        payload.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_alias_resolver_canonicalizes_names_and_search_tokens(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    _write_alias_config(alias_path)

    resolver = AliasResolver.from_file(alias_path)

    assert resolver.canonicalize_manufacturer("bambulab") == "Bambu Lab"
    assert resolver.canonicalize_material("PLA Basic") == "PLA"

    tokens = resolver.build_search_tokens(
        canonical="Bambu Lab",
        raw_values=["Bambulab", "拓竹", "PLA Basic"],
        aliases=resolver.aliases_for_manufacturer("Bambu Lab"),
    )

    assert "bambulab" in tokens
    assert "拓" in tokens
    assert "ba" in tokens
    assert "plabasic" in resolver.build_search_tokens(canonical="PLA", raw_values=["PLA Basic"])


def test_real_alias_asset_canonicalizes_pla_plus() -> None:
    asset_path = Path(__file__).resolve().parents[1] / "assets" / "lut_details_aliases.json"
    resolver = AliasResolver.from_file(asset_path)

    assert resolver.canonicalize_material("PLA+") == "PLA"


def test_real_alias_asset_canonicalizes_chinese_aliz() -> None:
    asset_path = Path(__file__).resolve().parents[1] / "assets" / "lut_details_aliases.json"
    resolver = AliasResolver.from_file(asset_path)

    assert resolver.canonicalize_manufacturer("爱丽兹") == "Aliz"


def test_catalog_indexer_applies_metadata_folder_and_filename_precedence(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    metadata_first = preset_dir / "FolderVendor" / "PETG" / "sample.json"
    _write_lut_json(metadata_first, manufacturer="MetaVendor", material_type="PLA Basic")

    folder_fallback = preset_dir / "Bambulab" / "PETG" / "folder_fallback.json"
    _write_lut_json(folder_fallback)

    filename_fallback = preset_dir / "Custom" / "Bambulab&PLA&RYBW&custom.json"
    _write_lut_json(filename_fallback)

    indexer = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=LutParser(),
    )

    catalog = indexer.build_catalog()
    groups = {group.manufacturer: group for group in catalog.groups}

    meta_item = next(item for item in groups["Meta Vendor"].items if item.name == "FolderVendor - PETG - sample")
    assert meta_item.manufacturer_source == "metadata"
    assert meta_item.material_type == "PLA"
    assert meta_item.material_source == "metadata"

    folder_item = next(item for item in groups["Bambu Lab"].items if item.name == "Bambulab - PETG - folder_fallback")
    assert folder_item.manufacturer_source == "folder"
    assert folder_item.material_type == "PETG"
    assert folder_item.material_source == "folder"

    filename_item = next(item for item in groups["Bambu Lab"].items if item.name == "Custom - Bambulab&PLA&RYBW&custom")
    assert filename_item.manufacturer_source == "filename"
    assert filename_item.material_source == "filename"


def test_catalog_indexer_infers_vendor_from_one_level_vendor_folder(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    vendor_only = preset_dir / "Bambulab" / "Bambulab_PLA_BW.json"
    _write_lut_json(vendor_only)

    catalog = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=LutParser(),
    ).build_catalog()

    groups = {group.manufacturer: group for group in catalog.groups}
    item = next(item for item in groups["Bambu Lab"].items if item.name == "Bambulab - Bambulab_PLA_BW")
    assert item.manufacturer_source == "folder"
    assert item.material_source == "filename"
    assert item.material_type == "PLA"


def test_cloud_migration_keeps_manufacturer_and_material_identity(tmp_path: Path) -> None:
    alias_path = tmp_path / "aliases.json"
    _write_alias_config(alias_path)
    cloud = tmp_path / "shared/Cloud_sync"
    _write_lut_json(cloud / "Bambulab/PETG/folder.json")
    _write_lut_json(cloud / "Custom/Bambulab&PLA&RYBW&custom.json")
    _write_lut_json(cloud / "_revisions/abc/Bambulab&PLA&RYBW&revision.json")
    catalog = LutCatalogIndexer(
        preset_dir=tmp_path / "empty-presets",
        additional_roots=(("Cloud", cloud),),
        alias_resolver=AliasResolver.from_file(alias_path), parser=LutParser(),
    ).build_catalog()
    assert [group.manufacturer for group in catalog.groups] == ["Bambu Lab"]
    items = {item.name: item for item in catalog.groups[0].items}
    assert items["Cloud - Bambulab - PETG - folder"].material_type == "PETG"
    assert items["Cloud - Custom - Bambulab&PLA&RYBW&custom"].material_type == "PLA"
    assert items["Cloud - _revisions - abc - Bambulab&PLA&RYBW&revision"].material_type == "PLA"


def test_catalog_indexer_does_not_treat_hyphenated_vendor_file_as_material_pair(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    hyphenated = preset_dir / "Creality" / "RYBW-Creality Hyper PLA.json"
    _write_lut_json(hyphenated)

    catalog = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=LutParser(),
    ).build_catalog()

    creality_group = next(group for group in catalog.groups if group.manufacturer == "Creality")
    item = next(item for item in creality_group.items if item.name == "Creality - RYBW-Creality Hyper PLA")
    assert item.manufacturer_source == "folder"
    assert item.material_source == "filename"
    assert item.material_type == "PLA"


def test_catalog_indexer_only_uses_underscore_filename_fallback_when_vendor_token_matches_folder(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    mismatched = preset_dir / "Creality" / "Bambulab_PLA_BW.json"
    _write_lut_json(mismatched)

    indexer = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=LutParser(),
    )
    catalog = indexer.build_catalog()

    creality_group = next(group for group in catalog.groups if group.manufacturer == "Creality")
    item = next(item for item in creality_group.items if item.name == "Creality - Bambulab_PLA_BW")
    assert item.manufacturer_source == "folder"
    assert item.material_source == "filename"
    assert item.material_type == "PLA"
    assert indexer._infer_from_filename(mismatched) == ("", "PLA")


def test_catalog_indexer_uses_underscore_filename_fallback_when_vendor_token_matches_folder(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    matched = preset_dir / "Bambulab" / "Bambulab_PLA_BW.json"
    _write_lut_json(matched)

    indexer = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=LutParser(),
    )

    assert indexer._infer_from_filename(matched) == ("Bambulab", "PLA")


def test_catalog_indexer_ignores_mode_folder_as_material_when_metadata_and_filename_are_empty(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    mode_folder_path = preset_dir / "Bambulab" / "4色" / "mode_only.json"
    _write_lut_json(mode_folder_path)

    catalog = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=LutParser(),
    ).build_catalog()

    group = next(group for group in catalog.groups if group.manufacturer == "Bambu Lab")
    item = next(item for item in group.items if item.name == "Bambulab - 4色 - mode_only")
    assert item.manufacturer_source == "folder"
    assert item.material_source == "fallback"
    assert item.material_type == ""


def test_catalog_indexer_handles_mixed_ampersand_and_underscore_filename_materials(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    mixed = preset_dir / "Jayo" / "Jayo&OW_PLA+_RYBW.json"
    _write_lut_json(mixed)

    catalog = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=LutParser(),
    ).build_catalog()

    group = next(group for group in catalog.groups if group.manufacturer == "Jayo")
    item = next(item for item in group.items if item.name == "Jayo - Jayo&OW_PLA+_RYBW")
    assert item.manufacturer_source == "folder"
    assert item.material_source == "filename"
    assert item.material_type == "PLA"


def test_catalog_indexer_ignores_merged_marker_segment_and_keeps_material_empty_when_absent(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    merged = preset_dir / "瑞贝思" / "瑞贝思&Merged_6-Color+BW+4-Color_20260401_141859.json"
    _write_lut_json(merged)

    catalog = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=LutParser(),
    ).build_catalog()

    group = next(group for group in catalog.groups if group.manufacturer == "瑞贝思")
    item = next(item for item in group.items if item.name == "瑞贝思 - 瑞贝思&Merged_6-Color+BW+4-Color_20260401_141859")
    assert item.manufacturer_source == "folder"
    assert item.material_source == "fallback"
    assert item.material_type == ""


def test_catalog_indexer_skips_mode_segment_and_uses_later_ampersand_material(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    mode_first = preset_dir / "瑞贝思" / "瑞贝思&2色&PLA&样品.json"
    _write_lut_json(mode_first)

    catalog = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=LutParser(),
    ).build_catalog()

    group = next(group for group in catalog.groups if group.manufacturer == "瑞贝思")
    item = next(item for item in group.items if item.name == "瑞贝思 - 瑞贝思&2色&PLA&样品")
    assert item.manufacturer_source == "folder"
    assert item.material_source == "filename"
    assert item.material_type == "PLA"


def test_material_inference_does_not_overmatch_ascii_prefix_words(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    indexer = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=LutParser(),
    )

    assert indexer._infer_material_from_stem("plastic_bw") == ""
    assert indexer._infer_material_from_stem("basicity_bw") == ""
    assert indexer._infer_material_from_stem("basic_bw") == ""


def test_detail_service_builds_safe_metadata_and_visualization_points(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    lut_path = preset_dir / "Bambulab" / "PLA" / "detail_source.json"
    _write_lut_json(
        lut_path,
        manufacturer="",
        material_type="",
        extra={
            "batch_id": "A-01",
            "notes": "detail coverage",
            "runtime_package": {"defaults": {"threshold": 5.0}, "modes": {"0.08x5": {"candidate_recipes": [[0]], "pred_lab": [[50, 0, 0]]}}},
        },
    )

    parser = LutParser()
    detail_service = LutDetailService(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=parser,
        indexer=LutCatalogIndexer(preset_dir=preset_dir, alias_resolver=AliasResolver.from_file(alias_path), parser=parser),
    )

    detail = detail_service.get_lut_details("Bambulab - PLA - detail_source")

    assert detail.manufacturer == "Bambu Lab"
    assert detail.manufacturer_source == "folder"
    assert detail.material_type == "PLA"
    assert detail.raw_metadata["batch_id"] == "A-01"
    assert detail.raw_metadata["notes"] == "detail coverage"
    assert "entries" not in detail.raw_metadata
    assert "runtime_package" not in detail.raw_metadata
    assert len(detail.lab_points) == 4
    assert len(detail.lab_points_3d) == 4
    assert len(detail.rgb_points) == 4
    assert detail.coverage_stats.plotted_point_count == 4
    assert len(detail.lab_hull) >= 3
    first_lab = parser.parse(name="Bambulab - PLA - detail_source", path=lut_path).lab[0]
    assert detail.lab_points_3d[0].l == round(float(first_lab[0]), 6)
    assert detail.lab_points_3d[0].a == round(float(first_lab[1]), 6)
    assert detail.lab_points_3d[0].b == round(float(first_lab[2]), 6)


def test_detail_service_omits_lab_hull_when_unique_points_are_below_three(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    lut_path = preset_dir / "Bambulab" / "PLA" / "few_points.json"
    payload = {
        "palette": {
            "White": {"material": "PLA Basic", "hex_color": "#FFFFFF", "color_name": "White"},
        },
        "entries": [
            {"rgb": [255, 255, 255], "lab": [100.0, 0.0, 0.0], "recipe": ["White", "White", "White", "White", "White"]},
            {"rgb": [255, 255, 255], "lab": [100.0, 0.0, 0.0], "recipe": ["White", "White", "White", "White", "White"]},
        ],
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "max_color_layers": 5,
        "layer_height_mm": 0.08,
        "line_width_mm": 0.42,
        "base_layers": 10,
        "base_channel_idx": 0,
        "layer_order": "Top2Bottom",
        "color_mode": "4-Color (RYBW)",
        "name": "few_points",
    }
    lut_path.parent.mkdir(parents=True, exist_ok=True)
    lut_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parser = LutParser()
    detail_service = LutDetailService(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=parser,
        indexer=LutCatalogIndexer(preset_dir=preset_dir, alias_resolver=AliasResolver.from_file(alias_path), parser=parser),
    )

    detail = detail_service.get_lut_details("Bambulab - PLA - few_points")

    assert detail.coverage_stats.plotted_point_count == 2
    assert detail.lab_hull == ()


def test_catalog_indexer_prefers_higher_priority_extensions_for_same_display_name(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    npy_path = preset_dir / "Bambulab" / "PLA" / "same_name.npy"
    npy_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(npy_path, np.array([[255, 255, 255]], dtype=np.uint8))
    json_path = preset_dir / "Bambulab" / "PLA" / "same_name.json"
    _write_lut_json(json_path, manufacturer="Bambulab", material_type="PLA Basic")

    catalog = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=LutParser(),
    ).build_catalog()

    items = [item for group in catalog.groups for item in group.items if item.name == "Bambulab - PLA - same_name"]
    assert len(items) == 1
    assert items[0].path.endswith(".json")


def test_catalog_indexer_falls_back_to_lower_priority_parseable_sibling(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    broken_msgpack_path = preset_dir / "Bambulab" / "PLA" / "same_name.msgpack"
    broken_msgpack_path.parent.mkdir(parents=True, exist_ok=True)
    broken_msgpack_path.write_bytes(b"not-msgpack")
    json_path = preset_dir / "Bambulab" / "PLA" / "same_name.json"
    _write_lut_json(json_path, manufacturer="Bambulab", material_type="PLA Basic")

    catalog = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=LutParser(),
    ).build_catalog()

    items = [item for group in catalog.groups for item in group.items if item.name == "Bambulab - PLA - same_name"]
    assert len(items) == 1
    assert items[0].path.endswith(".json")


def test_detail_lookup_reuses_catalog_resolved_path_cache(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    lut_path = preset_dir / "Bambulab" / "PLA" / "cached_lookup.json"
    _write_lut_json(lut_path, manufacturer="Bambulab", material_type="PLA Basic")

    class _CountingParser(LutParser):
      def __init__(self) -> None:
        super().__init__()
        self.parse_calls: list[str] = []

      def parse(self, *, name: str, path: Path):  # type: ignore[override]
        self.parse_calls.append(path.name)
        return super().parse(name=name, path=path)

    parser = _CountingParser()
    indexer = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=parser,
    )
    service = LutDetailService(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=parser,
        indexer=indexer,
    )

    service.get_catalog()
    assert parser.parse_calls == ["cached_lookup.json"]

    detail = service.get_lut_details("Bambulab - PLA - cached_lookup")
    assert detail.name == "Bambulab - PLA - cached_lookup"
    assert parser.parse_calls == ["cached_lookup.json", "cached_lookup.json"]


def test_detail_lookup_falls_back_when_cached_preferred_sibling_becomes_unparseable(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    json_path = preset_dir / "Bambulab" / "PLA" / "same_name.json"
    _write_lut_json(json_path, manufacturer="Bambulab", material_type="PLA Basic")
    npy_path = preset_dir / "Bambulab" / "PLA" / "same_name.npy"
    np.save(npy_path, np.array([[255, 255, 255]], dtype=np.uint8))

    parser = LutParser()
    indexer = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=parser,
    )
    service = LutDetailService(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=parser,
        indexer=indexer,
    )

    catalog = service.get_catalog()
    assert {item.path for group in catalog.groups for item in group.items if item.name == "Bambulab - PLA - same_name"} == {
        str(json_path.resolve()),
    }

    json_path.write_text("{invalid", encoding="utf-8")

    detail = service.get_lut_details("Bambulab - PLA - same_name")
    assert detail.path.endswith("same_name.npy")


def test_detail_lookup_refreshes_candidates_when_new_sibling_appears_after_cache_build(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    json_path = preset_dir / "Bambulab" / "PLA" / "late_sibling.json"
    _write_lut_json(json_path, manufacturer="Bambulab", material_type="PLA Basic")

    parser = LutParser()
    indexer = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=parser,
    )
    service = LutDetailService(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=parser,
        indexer=indexer,
    )

    service.get_catalog()

    npy_path = preset_dir / "Bambulab" / "PLA" / "late_sibling.npy"
    np.save(npy_path, np.array([[255, 255, 255]], dtype=np.uint8))
    json_path.write_text("{invalid", encoding="utf-8")

    detail = service.get_lut_details("Bambulab - PLA - late_sibling")
    assert detail.path.endswith("late_sibling.npy")


def test_catalog_indexer_refreshes_candidates_on_subsequent_catalog_builds(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    first = preset_dir / "Bambulab" / "PLA" / "first_refresh.json"
    _write_lut_json(first, manufacturer="Bambulab", material_type="PLA Basic")

    indexer = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=LutParser(),
    )

    with patch("core.lut_details.catalog.time.monotonic", side_effect=[0.0, 31.0]):
        first_catalog = indexer.build_catalog()
        assert {item.name for group in first_catalog.groups for item in group.items} == {
            "Bambulab - PLA - first_refresh",
        }

        second = preset_dir / "Bambulab" / "PLA" / "second_refresh.json"
        _write_lut_json(second, manufacturer="Bambulab", material_type="PLA Basic")

        second_catalog = indexer.build_catalog()
    assert {item.name for group in second_catalog.groups for item in group.items} == {
        "Bambulab - PLA - first_refresh",
        "Bambulab - PLA - second_refresh",
    }


def test_catalog_indexer_reuses_cached_catalog_until_file_signature_changes(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    lut_path = preset_dir / "Bambulab" / "PLA" / "cached.json"
    _write_lut_json(lut_path, manufacturer="Bambulab", material_type="PLA Basic")

    class CountingParser(LutParser):
        def __init__(self) -> None:
            super().__init__()
            self.parse_count = 0

        def parse(self, *, name: str, path: Path):
            self.parse_count += 1
            return super().parse(name=name, path=path)

    parser = CountingParser()
    indexer = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=parser,
    )

    with patch("core.lut_details.catalog.time.monotonic", side_effect=[0.0, 1.0, 31.0]):
        first_catalog = indexer.build_catalog()
        second_catalog = indexer.build_catalog()
        _write_lut_json(
            lut_path,
            manufacturer="Bambulab",
            material_type="PLA Basic",
            extra={"cache_bust": "changed-signature"},
        )
        third_catalog = indexer.build_catalog()

    assert first_catalog == second_catalog
    assert {
        item.name for group in third_catalog.groups for item in group.items
    } == {"Bambulab - PLA - cached"}
    assert parser.parse_count == 2


def test_catalog_indexer_skips_candidate_discovery_within_hot_cache_window(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    lut_path = preset_dir / "Bambulab" / "PLA" / "hot_cache.json"
    _write_lut_json(lut_path, manufacturer="Bambulab", material_type="PLA Basic")

    class CountingParser(LutParser):
        def __init__(self) -> None:
            super().__init__()
            self.parse_count = 0

        def parse(self, *, name: str, path: Path):
            self.parse_count += 1
            return super().parse(name=name, path=path)

    parser = CountingParser()
    indexer = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=parser,
    )

    with patch.object(
        indexer,
        "_discover_file_candidates",
        wraps=indexer._discover_file_candidates,
    ) as mock_discover:
        first_catalog = indexer.build_catalog()
        second_catalog = indexer.build_catalog()

    assert first_catalog == second_catalog
    assert mock_discover.call_count == 1
    assert parser.parse_count == 1


def test_catalog_indexer_keeps_deeply_nested_same_stem_entries_distinct(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    first = preset_dir / "Bambulab" / "PLA" / "4色" / "shared_name.json"
    second = preset_dir / "Bambulab" / "PLA" / "6色" / "shared_name.json"
    _write_lut_json(first, manufacturer="Bambulab", material_type="PLA Basic")
    _write_lut_json(second, manufacturer="Bambulab", material_type="PLA Basic")

    catalog = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=LutParser(),
    ).build_catalog()

    item_names = [item.name for group in catalog.groups for item in group.items]
    assert "Bambulab - PLA - 4色 - shared_name" in item_names
    assert "Bambulab - PLA - 6色 - shared_name" in item_names


def test_parser_supports_keyed_msgpack_lookup_payloads(tmp_path: Path) -> None:
    msgpack_path = tmp_path / "keyed.msgpack"
    payload = {
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "palette": {"White": {"material": "PLA Basic"}},
        "entries": [
            {"rgb": [255, 255, 255], "lab": [100.0, 0.0, 0.0], "recipe": ["White"]},
        ],
    }
    msgpack_path.write_bytes(msgpack.packb(payload, use_bin_type=True))

    parsed = LutParser().parse(name="keyed", path=msgpack_path)

    assert parsed.rgb.shape == (1, 3)
    assert parsed.lab.shape == (1, 3)
    assert parsed.metadata.palette[0].color == "White"


def test_parser_synthesizes_display_points_from_first_usable_model_package_mode(tmp_path: Path) -> None:
    msgpack_path = tmp_path / "model_package.msgpack"
    payload = {
        "scope": {"vendor": "Bambulab", "material_type": "PLA Basic"},
        "channel_keys": ["White|PLA Basic"],
        "defaults": {"threshold": 5.0, "margin": 0.7},
        "modes": [
            {
                "color_layers": 5,
                "layer_height_mm": 0.08,
                "layer_order": "Top2Bottom",
                "num_candidates": "oops",
                "candidate_recipes": b"",
                "pred_lab": b"",
            },
            {
                "color_layers": 8,
                "layer_height_mm": 0.08,
                "layer_order": "Top2Bottom",
                "num_candidates": 1,
                "candidate_recipes": np.asarray([[0, 0, 0, 0, 0, 0, 0, 0]], dtype=np.uint8).tobytes(),
                "pred_lab": np.asarray([[50.0, 0.0, 0.0]], dtype="<f4").tobytes(),
            },
        ],
    }
    msgpack_path.write_bytes(msgpack.packb(payload, use_bin_type=True))

    parsed = LutParser().parse(name="model_package", path=msgpack_path)

    assert parsed.source_kind == "predictive_package"
    assert parsed.color_count == 1
    assert parsed.rgb.shape == (1, 3)
    assert parsed.lab.shape == (1, 3)
    assert parsed.metadata.max_color_layers == 8
    assert parsed.metadata.get_supported_modes() == [
        {
            "mode_key": "0.08x8",
            "color_layers": 8,
            "layer_height_mm": 0.08,
            "layer_order": "Top2Bottom",
        }
    ]


def test_parser_builds_lab_from_rgb_for_npy_inputs(tmp_path: Path) -> None:
    npy_path = tmp_path / "legacy.npy"
    np.save(npy_path, np.array([[255, 255, 255], [0, 100, 240]], dtype=np.uint8))

    parsed = LutParser().parse(name="legacy", path=npy_path)

    assert parsed.rgb.shape == (2, 3)
    assert parsed.lab.shape == (2, 3)
    assert "runtime_package" not in parsed.raw_metadata


def test_parser_uses_lab_to_rgb_when_json_entries_omit_rgb(tmp_path: Path) -> None:
    json_path = tmp_path / "lab_only.json"
    payload = {
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "palette": {"White": {"material": "PLA Basic"}},
        "entries": [
          {"lab": [100.0, 0.0, 0.0], "recipe": ["White", "White", "White", "White", "White"]},
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parsed = LutParser().parse(name="lab_only", path=json_path)

    assert parsed.rgb.shape == (1, 3)
    assert parsed.lab.shape == (1, 3)


def test_parser_preserves_rgb_lab_alignment_when_only_some_entries_define_lab(tmp_path: Path) -> None:
    json_path = tmp_path / "partial_lab.json"
    payload = {
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "palette": {"White": {"material": "PLA Basic"}},
        "entries": [
            {"rgb": [255, 255, 255], "lab": [100.0, 0.0, 0.0], "recipe": ["White"]},
            {"rgb": [0, 100, 240], "recipe": ["White"]},
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parsed = LutParser().parse(name="partial_lab", path=json_path)

    assert parsed.rgb.shape == (2, 3)
    assert parsed.lab.shape == (2, 3)
    np.testing.assert_allclose(parsed.lab[0], np.asarray([100.0, 0.0, 0.0], dtype=np.float32))
    assert parsed.lab[1].shape == (3,)


def test_parser_preserves_rgb_lab_alignment_when_entries_include_non_dict_placeholders(tmp_path: Path) -> None:
    json_path = tmp_path / "partial_lab_with_placeholder.json"
    payload = {
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "palette": {"White": {"material": "PLA Basic"}},
        "entries": [
            "bad",
            {"rgb": [255, 255, 255], "lab": [100.0, 0.0, 0.0], "recipe": ["White"]},
            {"rgb": [0, 0, 0], "lab": [0.0, 0.0, 0.0], "recipe": ["White"]},
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parsed = LutParser().parse(name="partial_lab_with_placeholder", path=json_path)

    assert parsed.rgb.shape == (2, 3)
    assert parsed.lab.shape == (2, 3)
    np.testing.assert_allclose(parsed.lab[0], np.asarray([100.0, 0.0, 0.0], dtype=np.float32))
    np.testing.assert_allclose(parsed.lab[1], np.asarray([0.0, 0.0, 0.0], dtype=np.float32))


def test_parser_preserves_rgb_lab_alignment_when_malformed_lab_only_dict_precedes_valid_rows(tmp_path: Path) -> None:
    json_path = tmp_path / "malformed_lab_only_before_valid.json"
    payload = {
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "palette": {"White": {"material": "PLA Basic"}},
        "entries": [
            {"lab": ["bad", 0.0, 0.0], "recipe": ["White"]},
            {"rgb": [255, 255, 255], "lab": [100.0, 0.0, 0.0], "recipe": ["White"]},
            {"rgb": [0, 0, 0], "lab": [0.0, 0.0, 0.0], "recipe": ["White"]},
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parsed = LutParser().parse(name="malformed_lab_only_before_valid", path=json_path)

    assert parsed.rgb.shape == (2, 3)
    assert parsed.lab.shape == (2, 3)
    np.testing.assert_allclose(parsed.lab[0], np.asarray([100.0, 0.0, 0.0], dtype=np.float32))
    np.testing.assert_allclose(parsed.lab[1], np.asarray([0.0, 0.0, 0.0], dtype=np.float32))


def test_parser_skips_malformed_rgb_rows_without_shifting_following_explicit_lab(tmp_path: Path) -> None:
    json_path = tmp_path / "malformed_rgb_before_valid.json"
    payload = {
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "palette": {"White": {"material": "PLA Basic"}},
        "entries": [
            {"rgb": ["bad", 0, 0], "recipe": ["White"]},
            {"rgb": [255, 255, 255], "lab": [100.0, 0.0, 0.0], "recipe": ["White"]},
            {"rgb": [0, 0, 0], "lab": [0.0, 0.0, 0.0], "recipe": ["White"]},
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parsed = LutParser().parse(name="malformed_rgb_before_valid", path=json_path)

    assert parsed.rgb.shape == (2, 3)
    assert parsed.lab.shape == (2, 3)
    np.testing.assert_allclose(parsed.lab[0], np.asarray([100.0, 0.0, 0.0], dtype=np.float32))
    np.testing.assert_allclose(parsed.lab[1], np.asarray([0.0, 0.0, 0.0], dtype=np.float32))


def test_parser_ignores_malformed_explicit_lab_rows_when_rgb_is_available(tmp_path: Path) -> None:
    json_path = tmp_path / "malformed_lab.json"
    payload = {
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "palette": {"White": {"material": "PLA Basic"}},
        "entries": [
            {"rgb": [255, 255, 255], "lab": ["bad", 0.0, 0.0], "recipe": ["White"]},
            {"rgb": [0, 0, 0], "lab": [0.0, 0.0, 0.0], "recipe": ["White"]},
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parsed = LutParser().parse(name="malformed_lab", path=json_path)

    assert parsed.rgb.shape == (2, 3)
    assert parsed.lab.shape == (2, 3)
    assert np.isfinite(parsed.lab).all()


def test_parser_falls_back_to_rgb_lab_when_all_explicit_lab_rows_are_malformed(tmp_path: Path) -> None:
    json_path = tmp_path / "all_malformed_lab.json"
    payload = {
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "palette": {"White": {"material": "PLA Basic"}},
        "entries": [
            {"rgb": [255, 255, 255], "lab": ["bad", 0.0, 0.0], "recipe": ["White"]},
            {"rgb": [0, 0, 0], "lab": ["also-bad", 0.0, 0.0], "recipe": ["White"]},
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parsed = LutParser().parse(name="all_malformed_lab", path=json_path)

    assert parsed.rgb.shape == (2, 3)
    assert parsed.lab.shape == (2, 3)
    assert np.isfinite(parsed.lab).all()


def test_parser_ignores_non_finite_explicit_lab_rows_when_rgb_is_available(tmp_path: Path) -> None:
    json_path = tmp_path / "non_finite_lab.json"
    payload = {
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "palette": {"White": {"material": "PLA Basic"}},
        "entries": [
            {"rgb": [255, 255, 255], "lab": ["NaN", 0.0, 0.0], "recipe": ["White"]},
            {"rgb": [0, 0, 0], "lab": ["Infinity", 0.0, 0.0], "recipe": ["White"]},
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parsed = LutParser().parse(name="non_finite_lab", path=json_path)

    assert parsed.rgb.shape == (2, 3)
    assert parsed.lab.shape == (2, 3)
    assert np.isfinite(parsed.lab).all()


def test_parser_skips_lab_only_rows_with_malformed_lab_values(tmp_path: Path) -> None:
    json_path = tmp_path / "lab_only_malformed.json"
    payload = {
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "palette": {"White": {"material": "PLA Basic"}},
        "entries": [
            {"lab": ["bad", 0.0, 0.0], "recipe": ["White"]},
            {"lab": ["also-bad", 0.0, 0.0], "recipe": ["White"]},
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parsed = LutParser().parse(name="lab_only_malformed", path=json_path)

    assert parsed.rgb.shape == (0, 3)
    assert parsed.lab.shape == (0, 3)


def test_parser_skips_lab_only_rows_with_non_finite_lab_values(tmp_path: Path) -> None:
    json_path = tmp_path / "lab_only_non_finite.json"
    payload = {
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "palette": {"White": {"material": "PLA Basic"}},
        "entries": [
            {"lab": ["NaN", 0.0, 0.0], "recipe": ["White"]},
            {"lab": ["Infinity", 0.0, 0.0], "recipe": ["White"]},
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parsed = LutParser().parse(name="lab_only_non_finite", path=json_path)

    assert parsed.rgb.shape == (0, 3)
    assert parsed.lab.shape == (0, 3)


def test_parser_does_not_reintroduce_lab_only_rows_with_invalid_recipe_in_fallback(tmp_path: Path) -> None:
    json_path = tmp_path / "lab_only_invalid_recipe.json"
    payload = {
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "palette": {"White": {"material": "PLA Basic"}},
        "entries": [
            {"lab": [50.0, 0.0, 0.0], "recipe": "bad-recipe"},
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parsed = LutParser().parse(name="lab_only_invalid_recipe", path=json_path)

    assert parsed.rgb.shape == (0, 3)
    assert parsed.lab.shape == (0, 3)


def test_parser_skips_rows_with_malformed_recipe_scalars_without_aborting_parse(tmp_path: Path) -> None:
    json_path = tmp_path / "malformed_recipe_scalar.json"
    payload = {
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "palette": {"White": {"material": "PLA Basic"}},
        "entries": [
            {"rgb": [255, 255, 255], "recipe": "not-a-list"},
            {"rgb": [0, 0, 0], "recipe": ["White"]},
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parsed = LutParser().parse(name="malformed_recipe_scalar", path=json_path)

    assert parsed.rgb.shape == (1, 3)
    assert parsed.lab.shape == (1, 3)
    np.testing.assert_allclose(parsed.lab[0], np.asarray([0.0, 0.0, 0.0], dtype=np.float32))


def test_parser_skips_rows_with_non_castable_recipe_members_without_aborting_parse(tmp_path: Path) -> None:
    json_path = tmp_path / "malformed_recipe_member.json"
    payload = {
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "palette": {"White": {"material": "PLA Basic"}},
        "entries": [
            {"rgb": [255, 255, 255], "recipe": ["White", {"oops": 1}]},
            {"rgb": [0, 0, 0], "recipe": ["White"]},
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parsed = LutParser().parse(name="malformed_recipe_member", path=json_path)

    assert parsed.rgb.shape == (1, 3)
    assert parsed.lab.shape == (1, 3)
    np.testing.assert_allclose(parsed.lab[0], np.asarray([0.0, 0.0, 0.0], dtype=np.float32))


def test_parser_preserves_alignment_when_recipe_member_row_is_dropped(tmp_path: Path) -> None:
    json_path = tmp_path / "malformed_recipe_member_alignment.json"
    payload = {
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "palette": {"White": {"material": "PLA Basic"}},
        "entries": [
            {"rgb": [255, 255, 255], "lab": [100.0, 0.0, 0.0], "recipe": ["White", {"oops": 1}]},
            {"rgb": [0, 0, 0], "lab": [0.0, 0.0, 0.0], "recipe": ["White"]},
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parsed = LutParser().parse(name="malformed_recipe_member_alignment", path=json_path)

    assert parsed.rgb.shape == (1, 3)
    assert parsed.lab.shape == (1, 3)
    np.testing.assert_allclose(parsed.lab[0], np.asarray([0.0, 0.0, 0.0], dtype=np.float32))


def test_parser_pads_surviving_recipe_rows_to_avoid_ragged_stack_failures(tmp_path: Path) -> None:
    json_path = tmp_path / "ragged_recipe_rows.json"
    payload = {
        "manufacturer": "Bambulab",
        "type": "PLA Basic",
        "palette": {
            "White": {"material": "PLA Basic"},
            "Black": {"material": "PLA Basic"},
        },
        "entries": [
            {"rgb": [255, 255, 255], "recipe": ["White", "Black"]},
            {"rgb": [0, 0, 0], "recipe": ["Black"]},
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    parsed = LutParser().parse(name="ragged_recipe_rows", path=json_path)

    assert parsed.rgb.shape == (2, 3)
    assert parsed.lab.shape == (2, 3)


def test_parser_sanitizes_msgpack_raw_metadata_and_uses_loader_result(tmp_path: Path, monkeypatch) -> None:
    msgpack_path = tmp_path / "sample.msgpack"
    msgpack_path.write_bytes(
        msgpack.packb(
            {
                "palette": {"White": {"material": "PLA Basic"}},
                "entries": [{"rgb": [10, 20, 30], "recipe": ["White"]}],
                "runtime_package": {"modes": {}},
                "custom_meta": "kept",
            },
            use_bin_type=True,
        )
    )

    parsed = LutParser().parse(name="sample", path=msgpack_path)

    assert parsed.color_mode == "Merged"
    assert parsed.color_count == 1
    assert parsed.raw_metadata["custom_meta"] == "kept"
    assert "runtime_package" not in parsed.raw_metadata


def test_parser_falls_back_to_inferred_mode_when_metadata_color_mode_is_missing(tmp_path: Path, monkeypatch) -> None:
    npy_path = tmp_path / "fallback.npy"
    np.save(npy_path, np.array([[255, 255, 255]], dtype=np.uint8))

    monkeypatch.setattr(
        "core.lut_details.parser.LUTManager.infer_color_mode",
        staticmethod(lambda _name, _path: "BW (Black & White)"),
    )
    monkeypatch.setattr(
        "core.lut_details.parser.LUTManager.load_lut_with_metadata",
        staticmethod(
            lambda _path: (
                np.array([[255, 255, 255]], dtype=np.uint8),
                None,
                LUTMetadata(color_mode=None),
            )
        ),
    )

    parsed = LutParser().parse(name="fallback", path=npy_path)

    assert parsed.color_mode == "BW (Black & White)"
    assert parsed.color_count == 1


def test_catalog_indexer_skips_broken_files_and_keeps_valid_entries(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    valid_path = preset_dir / "Bambulab" / "PLA" / "valid.json"
    _write_lut_json(valid_path, manufacturer="Bambulab", material_type="PLA Basic")
    broken_path = preset_dir / "Bambulab" / "PLA" / "broken.json"
    broken_path.parent.mkdir(parents=True, exist_ok=True)
    broken_path.write_text("{invalid", encoding="utf-8")

    class _FailingParser(LutParser):
      def parse(self, *, name: str, path: Path):  # type: ignore[override]
        if path.name == "broken.json":
          raise ValueError("broken")
        return super().parse(name=name, path=path)

    catalog = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=_FailingParser(),
    ).build_catalog()

    items = [item.name for group in catalog.groups for item in group.items]
    assert "Bambulab - PLA - valid" in items
    assert "Bambulab - PLA - broken" not in items


def test_catalog_indexer_raises_when_all_discovered_files_fail_to_parse(tmp_path: Path) -> None:
    alias_path = tmp_path / "lut_details_aliases.json"
    preset_dir = tmp_path / "lut-preset"
    _write_alias_config(alias_path)

    broken_path = preset_dir / "Bambulab" / "PLA" / "broken.json"
    broken_path.parent.mkdir(parents=True, exist_ok=True)
    broken_path.write_text("{invalid", encoding="utf-8")

    class _AlwaysFailingParser(LutParser):
      def parse(self, *, name: str, path: Path):  # type: ignore[override]
        raise ValueError(f"broken: {path.name}")

    indexer = LutCatalogIndexer(
        preset_dir=preset_dir,
        alias_resolver=AliasResolver.from_file(alias_path),
        parser=_AlwaysFailingParser(),
    )

    with pytest.raises(RuntimeError, match="All discovered LUT detail files failed to parse"):
        indexer.build_catalog()
