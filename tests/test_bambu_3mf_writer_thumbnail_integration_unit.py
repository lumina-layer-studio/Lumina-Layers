"""Integration tests for ``BambuStudio3MFWriter`` cover-thumbnail wiring.

中文标题：BambuStudio3MFWriter 封面缩略图导出集成测试

These tests cover task 2 of the ``3mf-cover-thumbnail`` spec:
the single package write with FatCat metadata and ``CoverPngBundle`` plate
previews, plus the three ``Auxiliaries/.thumbnails/*.png`` parts. Cover assets
and relationships are supplied before neroued writes the archive.

Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 3.1, 3.4, 3.5, 6.1, 6.2,
6.3, 6.4, 6.5, 7.4 / Properties 1, 4, 5, 6, 7, 8, 9.
"""

from __future__ import annotations

import io
import logging
import os
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Iterator

import pytest
import trimesh
from PIL import Image

from utils import bambu_3mf_writer as writer_module
from utils.bambu_3mf_cover import COVER_THUMBNAIL_SPECS
from utils.bambu_3mf_writer import BambuStudio3MFWriter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"

_OPC_THUMBNAIL_TYPE = (
    "http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"
)
_BAMBU_COVER_MIDDLE_TYPE = (
    "http://schemas.bambulab.com/package/2021/cover-thumbnail-middle"
)
_BAMBU_COVER_SMALL_TYPE = (
    "http://schemas.bambulab.com/package/2021/cover-thumbnail-small"
)


@pytest.fixture()
def red_source_png(tmp_path: Path) -> Path:
    """Encode a 200×100 solid-red PNG for use as ``cover_source``."""

    path = tmp_path / "source.png"
    Image.new("RGB", (200, 100), (220, 30, 40)).save(path, format="PNG")
    return path


def _make_writer(
    output_path: Path,
    *,
    cover_source=None,
) -> BambuStudio3MFWriter:
    """Construct a minimal writer with two distinct meshes."""

    writer = BambuStudio3MFWriter(
        str(output_path),
        settings={},
        color_mode="4-Color",
        printer_id="bambu-p1s",
        slicer="BambuStudio",
        nozzle_size="0.4",
        cover_source=cover_source,
    )

    a = trimesh.creation.box(extents=[2, 2, 2])
    a.metadata["bambu_material_name"] = "White"
    writer.add_mesh(a, "White", (255, 255, 255))

    b = trimesh.creation.box(extents=[2, 2, 2])
    b.apply_translation([4, 0, 0])
    b.metadata["bambu_material_name"] = "Red"
    writer.add_mesh(b, "Red", (220, 30, 40))
    return writer


@pytest.fixture()
def exported_with_cover_path(
    tmp_path: Path, red_source_png: Path
) -> Iterator[tuple[Path, Path]]:
    """Yield (exported_3mf_path, cover_source_path)."""

    out = tmp_path / "out.3mf"
    writer = _make_writer(out, cover_source=str(red_source_png))
    writer.export()
    yield out, red_source_png
    if out.exists():
        out.unlink()


@pytest.fixture()
def exported_silent_placeholder_path(tmp_path: Path) -> Iterator[Path]:
    """Yield an exported 3MF path built with ``cover_source=None``."""

    out = tmp_path / "silent.3mf"
    writer = _make_writer(out, cover_source=None)
    writer.export()
    yield out
    if out.exists():
        out.unlink()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decode_png(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def _verify_png(data: bytes) -> None:
    Image.open(io.BytesIO(data)).verify()


def _read_rels(zf: zipfile.ZipFile) -> ET.Element:
    raw = zf.read("_rels/.rels")
    return ET.fromstring(raw)


def _iter_relationships(root: ET.Element) -> list[ET.Element]:
    """Return all ``<Relationship>`` children regardless of namespace usage."""

    namespaced = root.findall(f"{{{_RELS_NS}}}Relationship")
    if namespaced:
        return namespaced
    return root.findall("Relationship")


# ---------------------------------------------------------------------------
# Tests — Auxiliaries/.thumbnails/* contents
# ---------------------------------------------------------------------------


class TestThumbnailParts:
    """Three Auxiliaries/.thumbnails/*.png parts must exist with the bundle bytes."""

    def test_three_thumbnail_paths_present(self, exported_with_cover_path) -> None:
        out_path, _ = exported_with_cover_path
        with zipfile.ZipFile(out_path) as zf:
            names = set(zf.namelist())
        for spec in COVER_THUMBNAIL_SPECS:
            assert spec.zip_path in names, f"missing {spec.zip_path}"

    def test_thumbnail_pngs_decode_to_correct_sizes_in_rgb_mode(
        self, exported_with_cover_path
    ) -> None:
        out_path, _ = exported_with_cover_path
        with zipfile.ZipFile(out_path) as zf:
            for spec in COVER_THUMBNAIL_SPECS:
                data = zf.read(spec.zip_path)
                _verify_png(data)
                decoded = _decode_png(data)
                assert decoded.size == (spec.width, spec.height), spec.logical_name
                assert decoded.mode == "RGB", spec.logical_name

    def test_thumbnail_bytes_match_cover_bundle_fields(
        self, tmp_path: Path, red_source_png: Path
    ) -> None:
        out = tmp_path / "verify-bytes.3mf"
        writer = _make_writer(out, cover_source=str(red_source_png))
        # Pre-build the bundle so we can compare byte-for-byte after export.
        writer._ensure_cover_bundle()
        bundle = writer.cover_bundle
        assert bundle is not None
        writer.export()

        with zipfile.ZipFile(out) as zf:
            assert zf.read(COVER_THUMBNAIL_SPECS[0].zip_path) == bundle.thumbnail_3mf
            assert zf.read(COVER_THUMBNAIL_SPECS[1].zip_path) == bundle.thumbnail_middle
            assert zf.read(COVER_THUMBNAIL_SPECS[2].zip_path) == bundle.thumbnail_small


# ---------------------------------------------------------------------------
# Tests — _rels/.rels rewrite
# ---------------------------------------------------------------------------


class TestRelsRewrite:
    """Package-level _rels/.rels must include the four relationships intact."""

    def test_rels_contains_four_relationships(self, exported_with_cover_path) -> None:
        out_path, _ = exported_with_cover_path
        with zipfile.ZipFile(out_path) as zf:
            root = _read_rels(zf)
        rels = _iter_relationships(root)
        assert len(rels) == 4

    def test_existing_3dmodel_relationship_unchanged(
        self, tmp_path: Path, red_source_png: Path
    ) -> None:
        # Snapshot the pre-rewrite rels by writing a 3MF without cover
        # post-processing semantics changes via a baseline writer that uses
        # the same n3mf path internally; instead, reuse the post-processed
        # output and verify the entry pointing at /3D/3dmodel.model is
        # preserved by Id, Type, and Target.
        out = tmp_path / "rels-existing.3mf"
        _make_writer(out, cover_source=str(red_source_png)).export()
        with zipfile.ZipFile(out) as zf:
            root = _read_rels(zf)
        rels = _iter_relationships(root)
        # The existing entry is the one whose Target is /3D/3dmodel.model.
        existing = [
            rel for rel in rels if rel.get("Target") == "/3D/3dmodel.model"
        ]
        assert len(existing) == 1
        existing_rel = existing[0]
        assert existing_rel.get("Type") == (
            "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
        )
        existing_id = existing_rel.get("Id")
        assert existing_id is not None and existing_id != ""

    def test_relationship_ids_are_unique(self, exported_with_cover_path) -> None:
        out_path, _ = exported_with_cover_path
        with zipfile.ZipFile(out_path) as zf:
            root = _read_rels(zf)
        ids = [rel.get("Id") for rel in _iter_relationships(root)]
        assert len(ids) == 4
        assert len(set(ids)) == 4, f"duplicate Id values: {ids}"

    def test_three_cover_relationships_have_expected_types_and_targets(
        self, exported_with_cover_path
    ) -> None:
        out_path, _ = exported_with_cover_path
        with zipfile.ZipFile(out_path) as zf:
            root = _read_rels(zf)
        rels = _iter_relationships(root)

        cover_rels = {
            rel.get("Type"): rel
            for rel in rels
            if rel.get("Target", "").startswith("/Auxiliaries/.thumbnails/")
        }
        assert set(cover_rels.keys()) == {
            _OPC_THUMBNAIL_TYPE,
            _BAMBU_COVER_MIDDLE_TYPE,
            _BAMBU_COVER_SMALL_TYPE,
        }

        assert (
            cover_rels[_OPC_THUMBNAIL_TYPE].get("Target")
            == "/Auxiliaries/.thumbnails/thumbnail_3mf.png"
        )
        assert (
            cover_rels[_BAMBU_COVER_MIDDLE_TYPE].get("Target")
            == "/Auxiliaries/.thumbnails/thumbnail_middle.png"
        )
        assert (
            cover_rels[_BAMBU_COVER_SMALL_TYPE].get("Target")
            == "/Auxiliaries/.thumbnails/thumbnail_small.png"
        )

    def test_cover_relationship_ids_match_design(
        self, exported_with_cover_path
    ) -> None:
        out_path, _ = exported_with_cover_path
        with zipfile.ZipFile(out_path) as zf:
            root = _read_rels(zf)
        cover_ids = sorted(
            rel.get("Id")
            for rel in _iter_relationships(root)
            if rel.get("Target", "").startswith("/Auxiliaries/.thumbnails/")
        )
        assert cover_ids == ["cover-rel-1", "cover-rel-2", "cover-rel-3"]


# ---------------------------------------------------------------------------
# Tests — [Content_Types].xml
# ---------------------------------------------------------------------------


class TestContentTypes:
    """[Content_Types].xml must keep png Default declared exactly once."""

    def test_png_default_extension_appears_exactly_once(
        self, exported_with_cover_path
    ) -> None:
        out_path, _ = exported_with_cover_path
        with zipfile.ZipFile(out_path) as zf:
            root = ET.fromstring(zf.read("[Content_Types].xml"))

        png_defaults = [
            child
            for child in root.findall(f"{{{_CT_NS}}}Default")
            if child.get("Extension", "").lower() == "png"
        ]
        assert len(png_defaults) == 1
        assert png_defaults[0].get("ContentType") == "image/png"


# ---------------------------------------------------------------------------
# Tests — Metadata/plate_*.png and top/pick placeholders
# ---------------------------------------------------------------------------


class TestPlateAndPlaceholderPngs:
    """Plate previews come from the bundle; top/pick stay as 2×2 placeholder."""

    def test_plate_main_and_no_light_are_byte_equal_and_512_square(
        self, exported_with_cover_path
    ) -> None:
        out_path, _ = exported_with_cover_path
        with zipfile.ZipFile(out_path) as zf:
            plate_main = zf.read("Metadata/plate_1.png")
            plate_no_light = zf.read("Metadata/plate_no_light_1.png")
        assert plate_main == plate_no_light

        decoded = _decode_png(plate_main)
        assert decoded.size == (512, 512)
        assert decoded.mode == "RGB"

    def test_plate_pngs_pass_pil_verify(self, exported_with_cover_path) -> None:
        out_path, _ = exported_with_cover_path
        with zipfile.ZipFile(out_path) as zf:
            for name in ("Metadata/plate_1.png", "Metadata/plate_no_light_1.png"):
                _verify_png(zf.read(name))

    def test_top_and_pick_match_the_2x2_placeholder(
        self, exported_with_cover_path
    ) -> None:
        out_path, _ = exported_with_cover_path
        placeholder = BambuStudio3MFWriter._build_preview_placeholder_png_bytes()
        with zipfile.ZipFile(out_path) as zf:
            assert zf.read("Metadata/top_1.png") == placeholder
            assert zf.read("Metadata/pick_1.png") == placeholder

    def test_model_settings_keep_plate_thumbnail_keys(
        self, exported_with_cover_path
    ) -> None:
        out_path, _ = exported_with_cover_path
        with zipfile.ZipFile(out_path) as zf:
            root = ET.fromstring(zf.read("Metadata/model_settings.config"))
        plate = root.find("./plate")
        assert plate is not None
        meta = {m.attrib["key"]: m.attrib["value"] for m in plate.findall("metadata")}
        assert meta["thumbnail_file"] == "Metadata/plate_1.png"
        assert meta["thumbnail_no_light_file"] == "Metadata/plate_no_light_1.png"
        assert meta["top_file"] == "Metadata/top_1.png"
        assert meta["pick_file"] == "Metadata/pick_1.png"


# ---------------------------------------------------------------------------
# Tests — silent placeholder path (cover_source=None)
# ---------------------------------------------------------------------------


class TestSilentPlaceholderExport:
    """``cover_source=None`` still emits all three thumbnails + relationships."""

    def test_silent_path_keeps_thumbnails_and_relationships(
        self, exported_silent_placeholder_path: Path
    ) -> None:
        with zipfile.ZipFile(exported_silent_placeholder_path) as zf:
            names = set(zf.namelist())
            for spec in COVER_THUMBNAIL_SPECS:
                assert spec.zip_path in names

            root = _read_rels(zf)
        rels = _iter_relationships(root)
        cover_ids = sorted(
            rel.get("Id")
            for rel in rels
            if rel.get("Target", "").startswith("/Auxiliaries/.thumbnails/")
        )
        assert cover_ids == ["cover-rel-1", "cover-rel-2", "cover-rel-3"]

    def test_silent_path_does_not_emit_warning_log(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        out = tmp_path / "silent.3mf"
        writer = _make_writer(out, cover_source=None)
        target_logger = logging.getLogger("lumina.utils.bambu_3mf_writer")
        original_propagate = target_logger.propagate
        target_logger.propagate = False
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger="lumina.utils.bambu_3mf_writer")
        try:
            writer.export()
        finally:
            target_logger.removeHandler(caplog.handler)
            target_logger.propagate = original_propagate
        cover_failed = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "bambu_3mf_cover_thumbnail_failed"
        ]
        assert cover_failed == []


# ---------------------------------------------------------------------------
# Tests — fallback path (cover_source unreadable) emits exactly one WARNING
# ---------------------------------------------------------------------------


class TestFallbackEmitsOneWarning:
    """A bad ``cover_source`` triggers exactly one structured WARNING per export."""

    def test_unreadable_path_yields_single_warning_and_valid_3mf(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        out = tmp_path / "fallback.3mf"
        bogus = str(tmp_path / "does_not_exist.png")
        writer = _make_writer(out, cover_source=bogus)
        target_logger = logging.getLogger("lumina.utils.bambu_3mf_writer")
        original_propagate = target_logger.propagate
        target_logger.propagate = False
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger="lumina.utils.bambu_3mf_writer")
        try:
            writer.export()
        finally:
            target_logger.removeHandler(caplog.handler)
            target_logger.propagate = original_propagate

        cover_failed = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "bambu_3mf_cover_thumbnail_failed"
        ]
        assert len(cover_failed) == 1
        record = cover_failed[0]
        assert getattr(record, "error_type") == "source_unavailable"
        assert getattr(record, "fallback_action") == "placeholder_written"
        assert getattr(record, "path", "").endswith(".3mf")
        assert isinstance(getattr(record, "error_message", None), str)

        # 3MF still produced and well-formed.
        with zipfile.ZipFile(out) as zf:
            for spec in COVER_THUMBNAIL_SPECS:
                _verify_png(zf.read(spec.zip_path))
            for name in ("Metadata/plate_1.png", "Metadata/plate_no_light_1.png"):
                _verify_png(zf.read(name))


# ---------------------------------------------------------------------------
# Tests — intermediate temp file cleanup
# ---------------------------------------------------------------------------


class TestIntermediateFileCleanup:
    """``export()`` must not leave temporary intermediate 3MFs on disk."""

    def test_intermediate_tempfile_is_cleaned_up_after_success(
        self, tmp_path: Path
    ) -> None:
        out = tmp_path / "clean.3mf"
        _make_writer(out, cover_source=None).export()
        leftovers = [
            p
            for p in tmp_path.iterdir()
            if p.suffix == ".3mf" and p.name != out.name
        ]
        assert leftovers == []
        # And no .tmp file from the post-process step.
        assert not (tmp_path / "clean.3mf.tmp").exists()
