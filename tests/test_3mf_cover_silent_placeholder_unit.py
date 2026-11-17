"""Silent-placeholder regression for cover-source ``None`` callers.

中文标题：无原图调用点的封面静默占位回归测试

This test guards the contract documented in design.md "Source Resolution
Policy": when a caller explicitly passes ``cover_source=None`` to
``export_scene_with_bambu_metadata`` (calibration / 色卡 / 单段 kit /
recipe swatch), the writer must:

1. Still write a structurally valid 3MF — three new cover relationships in
   ``_rels/.rels`` and the five cover PNG payloads pass
   ``PIL.Image.open(...).verify()``.
2. Stay completely silent — *no* ``bambu_3mf_cover_thumbnail_failed``
   WARNING is emitted. This is what differentiates the silent-placeholder
   path (no source by design) from the fallback-placeholder path
   (source provided but unreadable / undecodable), which is covered by
   ``tests/test_bambu_3mf_writer_cover_fallback_unit.py``.

Validates: Requirements 6.1, 6.5 / Property 2, 8.
"""

from __future__ import annotations

import io
import logging
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest
import trimesh
from PIL import Image

from utils.bambu_3mf_cover import COVER_PLATE_SPECS, COVER_THUMBNAIL_SPECS
from utils.bambu_3mf_writer import (
    BambuStudio3MFWriter,
    export_scene_with_bambu_metadata,
)


_RELS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_WRITER_LOGGER_NAME = "lumina.utils.bambu_3mf_writer"
_COVER_FAILED_EVENT = "bambu_3mf_cover_thumbnail_failed"


def _build_minimal_scene() -> "trimesh.Scene":
    """Build a 2-mesh scene that mirrors what calibration call sites pass."""

    scene = trimesh.Scene()
    a = trimesh.creation.box(extents=[2, 2, 2])
    a.visual.face_colors = (255, 255, 255, 255)
    a.metadata["name"] = "White"
    scene.add_geometry(a, node_name="White", geom_name="White")

    b = trimesh.creation.box(extents=[2, 2, 2])
    b.apply_translation([4, 0, 0])
    b.visual.face_colors = (220, 30, 40, 255)
    b.metadata["name"] = "Red"
    scene.add_geometry(b, node_name="Red", geom_name="Red")
    return scene


def _verify_png(data: bytes) -> None:
    """Run ``PIL.Image.open(...).verify()``; raises on malformed PNGs."""

    Image.open(io.BytesIO(data)).verify()


def _read_cover_relationships(zip_path: Path) -> list[ET.Element]:
    with zipfile.ZipFile(zip_path) as zf:
        root = ET.fromstring(zf.read("_rels/.rels"))
    rels = root.findall(f"{{{_RELS_NS}}}Relationship") or root.findall(
        "Relationship"
    )
    return [
        rel
        for rel in rels
        if (rel.get("Target") or "").startswith("/Auxiliaries/.thumbnails/")
    ]


def _capture_cover_failed_warnings(
    fn,
    caplog: pytest.LogCaptureFixture,
) -> list[logging.LogRecord]:
    """Run ``fn()`` while capturing WARNING records from the writer logger.

    The writer logs through ``api.structured_logging.get_logger`` which routes
    to ``lumina.utils.bambu_3mf_writer``; ``pytest``'s default ``caplog`` only
    attaches at the root, so attach explicitly to avoid relying on
    propagation.
    """

    target_logger = logging.getLogger(_WRITER_LOGGER_NAME)
    original_propagate = target_logger.propagate
    target_logger.propagate = False
    target_logger.addHandler(caplog.handler)
    caplog.set_level(logging.WARNING, logger=_WRITER_LOGGER_NAME)
    try:
        fn()
    finally:
        target_logger.removeHandler(caplog.handler)
        target_logger.propagate = original_propagate
    return [
        record
        for record in caplog.records
        if getattr(record, "event", None) == _COVER_FAILED_EVENT
    ]


class TestSilentPlaceholderWhenCoverSourceIsNone:
    """``cover_source=None`` is the silent-placeholder path, not fallback."""

    def test_export_scene_with_cover_source_none_emits_no_warning(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        out = tmp_path / "silent_none.3mf"
        scene = _build_minimal_scene()

        records = _capture_cover_failed_warnings(
            lambda: export_scene_with_bambu_metadata(
                scene=scene,
                output_path=str(out),
                slot_names=["White", "Red"],
                preview_colors={
                    0: (255, 255, 255, 255),
                    1: (220, 30, 40, 255),
                },
                settings={
                    "layer_height": "0.08",
                    "initial_layer_height": "0.08",
                },
                color_mode="4-Color",
                printer_id="bambu-p1s",
                slicer="BambuStudio",
                nozzle_size="0.4",
                cover_source=None,
            ),
            caplog,
        )

        assert records == [], (
            "cover_source=None must NOT emit "
            f"{_COVER_FAILED_EVENT}; got {len(records)} record(s)"
        )

    def test_export_scene_with_cover_source_none_writes_three_relationships(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        out = tmp_path / "silent_none_rels.3mf"
        scene = _build_minimal_scene()

        _capture_cover_failed_warnings(
            lambda: export_scene_with_bambu_metadata(
                scene=scene,
                output_path=str(out),
                slot_names=["White", "Red"],
                preview_colors={
                    0: (255, 255, 255, 255),
                    1: (220, 30, 40, 255),
                },
                settings={"layer_height": "0.08", "initial_layer_height": "0.08"},
                color_mode="4-Color",
                printer_id="bambu-p1s",
                slicer="BambuStudio",
                nozzle_size="0.4",
                cover_source=None,
            ),
            caplog,
        )

        cover_rels = _read_cover_relationships(out)
        assert len(cover_rels) == 3
        assert sorted(rel.get("Id") for rel in cover_rels) == [
            "cover-rel-1",
            "cover-rel-2",
            "cover-rel-3",
        ]

        with zipfile.ZipFile(out) as zf:
            for spec in COVER_THUMBNAIL_SPECS:
                _verify_png(zf.read(spec.zip_path))
            for spec in COVER_PLATE_SPECS:
                _verify_png(zf.read(spec.zip_path))


class TestSilentVsFallbackPlaceholderSemantics:
    """Confirm silent placeholder and fallback placeholder are observably different.

    Silent path (``cover_source=None``)         → no WARNING.
    Fallback path (``cover_source`` invalid)    → exactly one WARNING.
    """

    def _export(
        self,
        out: Path,
        cover_source: object,
    ) -> None:
        writer = BambuStudio3MFWriter(
            str(out),
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
        writer.export()

    def test_none_source_is_silent(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        out = tmp_path / "diff_silent.3mf"
        records = _capture_cover_failed_warnings(
            lambda: self._export(out, cover_source=None),
            caplog,
        )
        assert records == []

    def test_invalid_source_emits_warning(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        out = tmp_path / "diff_fallback.3mf"
        # Empty bytes is the canonical "source provided but unusable" case;
        # the writer must emit exactly one WARNING here, distinguishing it
        # from the silent ``None`` path above.
        records = _capture_cover_failed_warnings(
            lambda: self._export(out, cover_source=b""),
            caplog,
        )
        assert len(records) == 1
        assert getattr(records[0], "fallback_action") == "placeholder_written"


class TestCalibrationCallSitesUseSilentPlaceholder:
    """End-to-end: at least one real call site (BW calibration) is silent.

    This complements ``test_calibration_device_config_unit`` by adding the
    structural-log assertion that R6.5 specifically requires.
    """

    def test_bw_calibration_board_does_not_emit_cover_failed_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from core.calibration import generate_bw_calibration_board

        monkeypatch.setattr("core.calibration.MODELS_DIR", str(tmp_path))

        records = _capture_cover_failed_warnings(
            lambda: generate_bw_calibration_board(
                block_size_mm=3.0,
                gap_mm=0.4,
                backing_thickness_mm=0.4,
                printer_id="bambu-p1s",
                slicer="OrcaSlicer",
                nozzle_size="0.2",
            ),
            caplog,
        )

        assert records == [], (
            "BW calibration export must be silent under cover_source=None; "
            f"got {len(records)} {_COVER_FAILED_EVENT} record(s)"
        )
