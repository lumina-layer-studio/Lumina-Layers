"""Logging-field truncation tests for the cover-thumbnail pipeline.

中文标题：3MF 封面缩略图日志字段截断与取值集合单元测试

Per R6.3, the structured WARNING ``bambu_3mf_cover_thumbnail_failed`` carries
four ``extra`` fields with the following length / value contracts:

- ``path``        : ≤ 1024 characters
- ``error_type``  : ≤ 256 characters
- ``error_message`` : ≤ 2048 characters; truncated with ``"..."`` suffix
- ``fallback_action`` : value drawn from ``{"placeholder_written"}``

This file checks each contract by exercising

1. ``utils.bambu_3mf_cover._truncate`` directly (suffix + length);
2. ``CoverThumbnailBuilder.build`` with inputs that surface very long error
   messages so the truncation actually fires;
3. ``BambuStudio3MFWriter._ensure_cover_bundle`` with an output path longer
   than 1024 characters, asserting the emitted WARNING's ``path`` field stays
   within the cap.

History note: an earlier worker draft also emitted ``fallback_action=
"tile_skipped"`` when SVG large-format tile rasterization timed out, but that
path now writes the silent-placeholder cover too (cover-failed tile is still
exported), so the vocabulary collapsed back to a single value. We keep the
contract test below to lock the vocabulary down — adding a new
``fallback_action`` value is a behaviour change that should be reviewed.

Validates: Requirements 6.3, 10.4, 10.5 / Property 2, 3.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from utils import bambu_3mf_cover as cover_module
from utils.bambu_3mf_cover import CoverThumbnailBuilder
from utils.bambu_3mf_writer import BambuStudio3MFWriter


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_VALID_FALLBACK_ACTIONS = frozenset({"placeholder_written"})
_PATH_LIMIT = 1024
_ERROR_TYPE_LIMIT = 256
_ERROR_MESSAGE_LIMIT = 2048
_WRITER_LOGGER_NAME = "lumina.utils.bambu_3mf_writer"


# ---------------------------------------------------------------------------
# Tests — _truncate behaviour (the foundation of the contract)
# ---------------------------------------------------------------------------


class TestTruncatePureFunction:
    """Direct tests for ``_truncate``; the building block for length caps."""

    def test_short_value_passes_through_unchanged(self) -> None:
        assert cover_module._truncate("hello", 2048) == "hello"
        assert cover_module._truncate("hello", 5) == "hello"

    def test_value_exactly_at_limit_passes_through(self) -> None:
        value = "x" * 256
        assert cover_module._truncate(value, 256) == value
        assert len(cover_module._truncate(value, 256)) == 256

    def test_long_error_message_truncates_to_limit_with_ellipsis(self) -> None:
        result = cover_module._truncate("x" * 5000, _ERROR_MESSAGE_LIMIT)
        assert len(result) <= _ERROR_MESSAGE_LIMIT
        assert len(result) == _ERROR_MESSAGE_LIMIT
        assert result.endswith("...")

    def test_long_error_type_truncates_to_256_with_ellipsis(self) -> None:
        result = cover_module._truncate("y" * 1000, _ERROR_TYPE_LIMIT)
        assert len(result) <= _ERROR_TYPE_LIMIT
        assert len(result) == _ERROR_TYPE_LIMIT
        assert result.endswith("...")

    def test_long_path_truncates_to_1024_with_ellipsis(self) -> None:
        result = cover_module._truncate("z" * 4096, _PATH_LIMIT)
        assert len(result) <= _PATH_LIMIT
        assert len(result) == _PATH_LIMIT
        assert result.endswith("...")


# ---------------------------------------------------------------------------
# Tests — _make_warning enforces the length contract on every dict it returns
# ---------------------------------------------------------------------------


class TestMakeWarningEnforcesFieldLengths:
    """``_make_warning`` is the single source of truth for non-tile warnings."""

    def test_long_error_message_is_capped_at_2048(self) -> None:
        warning = cover_module._make_warning("source_decode_error", "x" * 5000)
        assert len(warning["error_message"]) <= _ERROR_MESSAGE_LIMIT
        assert warning["error_message"].endswith("...")

    def test_long_error_type_is_capped_at_256(self) -> None:
        warning = cover_module._make_warning("y" * 1000, "boom")
        assert len(warning["error_type"]) <= _ERROR_TYPE_LIMIT
        assert warning["error_type"].endswith("...")

    def test_fallback_action_is_placeholder_written(self) -> None:
        warning = cover_module._make_warning("source_decode_error", "boom")
        assert warning["fallback_action"] == "placeholder_written"
        assert warning["fallback_action"] in _VALID_FALLBACK_ACTIONS


# ---------------------------------------------------------------------------
# Tests — Builder.build surfaces a clamped warning when error_message > 2048
# ---------------------------------------------------------------------------


class TestBuilderClampsWarningFields:
    """End-to-end: builder output respects the same length contract."""

    def test_long_path_yields_clamped_error_message(self, tmp_path: Path) -> None:
        # Construct a cover_source path longer than 2048 characters so that the
        # synthesized "no such file: …" message exceeds the cap. The path does
        # not need to exist on disk; ``_decode_source`` only formats the
        # missing-path string and routes through ``_make_warning``.
        long_segment = "x" * 3000
        fake_path = str(tmp_path / f"{long_segment}.png")

        bundle = CoverThumbnailBuilder().build(fake_path)

        assert bundle.is_placeholder is True
        assert bundle.warning is not None
        warning = bundle.warning

        assert warning["error_type"] == "source_unavailable"
        assert len(warning["error_type"]) <= _ERROR_TYPE_LIMIT

        assert len(warning["error_message"]) <= _ERROR_MESSAGE_LIMIT
        assert warning["error_message"].endswith("...")

        assert warning["fallback_action"] == "placeholder_written"
        assert warning["fallback_action"] in _VALID_FALLBACK_ACTIONS

    def test_unsupported_type_warning_is_within_limits(self) -> None:
        bundle = CoverThumbnailBuilder().build(12345)
        assert bundle.is_placeholder is True
        assert bundle.warning is not None
        warning = bundle.warning
        assert warning["error_type"] == "source_unsupported_type"
        assert len(warning["error_type"]) <= _ERROR_TYPE_LIMIT
        assert len(warning["error_message"]) <= _ERROR_MESSAGE_LIMIT
        assert warning["fallback_action"] == "placeholder_written"


# ---------------------------------------------------------------------------
# Tests — Writer's WARNING extra.path is capped at 1024 characters
# ---------------------------------------------------------------------------


class TestWriterPathFieldClampedTo1024:
    """A 1500-char output_path must surface a 1024-char ``path`` in the WARNING.

    The writer never has to actually create this file on disk: the path-cap
    behaviour lives in ``_ensure_cover_bundle``, which only inspects
    ``self.output_path`` as a string before emitting the structured WARNING.
    """

    def test_warning_path_field_does_not_exceed_limit(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Build an output_path much longer than 1024 chars by stuffing a
        # very long basename into the writer instance. We never call
        # ``export()`` so the OS PATH_MAX limit does not apply.
        long_segment = "p" * 1500
        fake_output = str(tmp_path / f"{long_segment}.3mf")
        assert len(fake_output) > _PATH_LIMIT

        writer = BambuStudio3MFWriter(
            fake_output,
            settings={},
            color_mode="4-Color",
            printer_id="bambu-p1s",
            slicer="BambuStudio",
            nozzle_size="0.4",
            cover_source=str(tmp_path / "definitely_missing.png"),
        )

        target_logger = logging.getLogger(_WRITER_LOGGER_NAME)
        original_propagate = target_logger.propagate
        target_logger.propagate = False
        target_logger.addHandler(caplog.handler)
        caplog.set_level(logging.WARNING, logger=_WRITER_LOGGER_NAME)
        try:
            writer._ensure_cover_bundle()
        finally:
            target_logger.removeHandler(caplog.handler)
            target_logger.propagate = original_propagate

        records = [
            record
            for record in caplog.records
            if getattr(record, "event", None) == "bambu_3mf_cover_thumbnail_failed"
        ]
        assert len(records) == 1, "expected exactly one cover-failed WARNING"
        record = records[0]

        path_field = getattr(record, "path", None)
        assert isinstance(path_field, str)
        assert len(path_field) <= _PATH_LIMIT

        # Other fields stay within their caps as well.
        error_type = getattr(record, "error_type", "")
        error_message = getattr(record, "error_message", "")
        fallback_action = getattr(record, "fallback_action", "")
        assert len(error_type) <= _ERROR_TYPE_LIMIT
        assert len(error_message) <= _ERROR_MESSAGE_LIMIT
        assert fallback_action in _VALID_FALLBACK_ACTIONS


# ---------------------------------------------------------------------------
# Tests — fallback_action vocabulary is fixed
# ---------------------------------------------------------------------------


class TestFallbackActionVocabulary:
    """The single-value vocabulary is the contract; lock it down."""

    def test_set_membership_is_exactly_one_value(self) -> None:
        assert _VALID_FALLBACK_ACTIONS == {"placeholder_written"}

    def test_cover_module_only_emits_placeholder_written(self) -> None:
        # Sweep the documented error categories; every one of them must be
        # the writer-side ``placeholder_written``. The SVG large-format
        # worker (task 6) also emits ``placeholder_written`` because
        # cover-failed tiles are now exported with the silent placeholder
        # rather than dropped.
        for source in (
            "/definitely/not/a/real/path.png",
            b"",
            b"not really a png",
            12345,
        ):
            bundle = CoverThumbnailBuilder().build(source)
            assert bundle.warning is not None
            assert bundle.warning["fallback_action"] == "placeholder_written"
            assert bundle.warning["fallback_action"] in _VALID_FALLBACK_ACTIONS
