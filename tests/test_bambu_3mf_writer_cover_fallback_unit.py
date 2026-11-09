"""Cover-source fallback tests for ``BambuStudio3MFWriter``.

中文标题：3MF 封面缩略图失败回退单元测试

This file exercises the five canonical "bad ``cover_source``" inputs from
design.md ``Source Resolution Policy``:

    (a) ``cover_source`` is a path to a file that does not exist
        → ``error_type == "source_unavailable"``
    (b) ``cover_source`` is a path to a 0-byte file
        → ``error_type == "source_empty"``
    (c) ``cover_source`` is empty ``bytes``
        → ``error_type == "source_empty"``
    (d) ``cover_source`` is an unsupported type (``int`` here)
        → ``error_type == "source_unsupported_type"``
    (e) ``cover_source`` is a malformed PNG byte stream (bad header)
        → ``error_type == "source_decode_error"``

Each input must:

- Still produce a structurally valid 3MF (three new cover relationships in
  ``_rels/.rels`` + the five PNG payloads pass ``PIL.Image.open(...).verify()``);
- Emit *exactly one* WARNING with ``event=bambu_3mf_cover_thumbnail_failed``
  whose ``extra`` carries all four documented fields:
  ``path`` / ``error_type`` / ``error_message`` / ``fallback_action``.

Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5 / Property 2, 3.
"""

from __future__ import annotations

import io
import logging
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Iterator, Tuple

import pytest
import trimesh
from PIL import Image

from utils.bambu_3mf_cover import COVER_PLATE_SPECS, COVER_THUMBNAIL_SPECS
from utils.bambu_3mf_writer import BambuStudio3MFWriter


# ---------------------------------------------------------------------------
# Constants and helpers
# ---------------------------------------------------------------------------


_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_WRITER_LOGGER_NAME = "lumina.utils.bambu_3mf_writer"
_REQUIRED_WARNING_FIELDS = ("path", "error_type", "error_message", "fallback_action")


def _make_writer(
    output_path: Path,
    *,
    cover_source: object,
) -> BambuStudio3MFWriter:
    """Build a minimal 2-mesh writer with the given ``cover_source``."""

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


def _verify_png(data: bytes) -> None:
    """Run ``PIL.Image.open(...).verify()``; raises on malformed PNGs."""

    Image.open(io.BytesIO(data)).verify()


def _read_rels(zip_path: Path) -> ET.Element:
    with zipfile.ZipFile(zip_path) as zf:
        return ET.fromstring(zf.read("_rels/.rels"))


def _iter_cover_relationships(root: ET.Element) -> list[ET.Element]:
    rels = root.findall(f"{{{_RELS_NS}}}Relationship") or root.findall(
        "Relationship"
    )
    return [
        rel
        for rel in rels
        if (rel.get("Target") or "").startswith("/Auxiliaries/.thumbnails/")
    ]


def _capture_writer_warnings(
    writer: BambuStudio3MFWriter,
    caplog: pytest.LogCaptureFixture,
) -> list[logging.LogRecord]:
    """Run ``writer.export()`` while capturing WARNING records from the writer.

    The writer logs through ``api.structured_logging.get_logger`` which routes
    to the ``lumina.utils.bambu_3mf_writer`` logger. ``pytest``'s default
    ``caplog`` only attaches at the root, so we explicitly add the handler
    onto the writer's logger to avoid relying on propagation.
    """

    target_logger = logging.getLogger(_WRITER_LOGGER_NAME)
    original_propagate = target_logger.propagate
    target_logger.propagate = False
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=_WRITER_LOGGER_NAME)
    try:
        writer.export()
    finally:
        target_logger.removeHandler(caplog.handler)
        target_logger.propagate = original_propagate
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == "bambu_3mf_cover_thumbnail_failed"
    ]


# ---------------------------------------------------------------------------
# Fixtures — five fallback inputs
# ---------------------------------------------------------------------------


@pytest.fixture()
def empty_file(tmp_path: Path) -> Path:
    """Materialize a 0-byte file at a real path."""

    path = tmp_path / "empty.png"
    path.write_bytes(b"")
    return path


@pytest.fixture(
    params=[
        "missing_path",
        "empty_file",
        "empty_bytes",
        "unsupported_type",
        "decode_error",
    ]
)
def fallback_case(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    empty_file: Path,
) -> Tuple[str, object, str]:
    """Return ``(case_id, cover_source, expected_error_type)``."""

    case = request.param
    if case == "missing_path":
        return case, str(tmp_path / "no_such_file.png"), "source_unavailable"
    if case == "empty_file":
        return case, str(empty_file), "source_empty"
    if case == "empty_bytes":
        return case, b"", "source_empty"
    if case == "unsupported_type":
        return case, 12345, "source_unsupported_type"
    if case == "decode_error":
        # A handful of bytes that does not match the PNG signature; Pillow
        # raises ``UnidentifiedImageError`` (subclass of ``OSError``) which
        # ``_decode_source`` maps to ``source_decode_error``.
        return case, b"not really a png", "source_decode_error"
    raise AssertionError(f"unknown fallback case: {case}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Tests — single WARNING per export
# ---------------------------------------------------------------------------


class TestExactlyOneWarningPerFallback:
    """Each bad cover_source must produce exactly one structured WARNING."""

    def test_emits_single_cover_failed_warning(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        fallback_case: Tuple[str, object, str],
    ) -> None:
        case_id, cover_source, expected_error_type = fallback_case
        out = tmp_path / f"{case_id}.3mf"
        writer = _make_writer(out, cover_source=cover_source)

        records = _capture_writer_warnings(writer, caplog)
        assert len(records) == 1, (
            f"{case_id}: expected exactly 1 cover-failed WARNING, got "
            f"{len(records)}"
        )

    def test_warning_extra_has_four_required_fields(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        fallback_case: Tuple[str, object, str],
    ) -> None:
        case_id, cover_source, expected_error_type = fallback_case
        out = tmp_path / f"{case_id}.3mf"
        writer = _make_writer(out, cover_source=cover_source)

        records = _capture_writer_warnings(writer, caplog)
        assert len(records) == 1
        record = records[0]
        for field in _REQUIRED_WARNING_FIELDS:
            value = getattr(record, field, None)
            assert isinstance(value, str), (
                f"{case_id}: WARNING extra field {field!r} should be a string,"
                f" got {type(value).__name__}"
            )
            assert value, f"{case_id}: WARNING extra field {field!r} is empty"

    def test_warning_carries_expected_error_type(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        fallback_case: Tuple[str, object, str],
    ) -> None:
        case_id, cover_source, expected_error_type = fallback_case
        out = tmp_path / f"{case_id}.3mf"
        writer = _make_writer(out, cover_source=cover_source)

        records = _capture_writer_warnings(writer, caplog)
        assert len(records) == 1
        record = records[0]
        assert getattr(record, "error_type") == expected_error_type, (
            f"{case_id}: expected error_type={expected_error_type!r}"
        )
        assert getattr(record, "fallback_action") == "placeholder_written", case_id


# ---------------------------------------------------------------------------
# Tests — 3MF still valid (relationships + PNG verify)
# ---------------------------------------------------------------------------


class TestThreeMfStillValidOnFallback:
    """Each fallback path must still produce a structurally valid 3MF."""

    def test_three_cover_relationships_present(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        fallback_case: Tuple[str, object, str],
    ) -> None:
        case_id, cover_source, _ = fallback_case
        out = tmp_path / f"{case_id}.3mf"
        writer = _make_writer(out, cover_source=cover_source)

        # Drain the warning so the test focuses on the on-disk artifact.
        _capture_writer_warnings(writer, caplog)

        root = _read_rels(out)
        cover_rels = _iter_cover_relationships(root)
        assert len(cover_rels) == 3, (
            f"{case_id}: expected three cover relationships, got "
            f"{len(cover_rels)}"
        )
        cover_ids = sorted(rel.get("Id") for rel in cover_rels)
        assert cover_ids == ["cover-rel-1", "cover-rel-2", "cover-rel-3"], case_id

    def test_five_cover_pngs_pass_pil_verify(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        fallback_case: Tuple[str, object, str],
    ) -> None:
        case_id, cover_source, _ = fallback_case
        out = tmp_path / f"{case_id}.3mf"
        writer = _make_writer(out, cover_source=cover_source)

        _capture_writer_warnings(writer, caplog)

        with zipfile.ZipFile(out) as zf:
            for spec in COVER_THUMBNAIL_SPECS:
                _verify_png(zf.read(spec.zip_path))
            for spec in COVER_PLATE_SPECS:
                _verify_png(zf.read(spec.zip_path))
