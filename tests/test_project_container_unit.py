from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import pytest

from core.projects.container import (
    ProjectLimits,
    build_project_bytes,
    read_project,
    write_project,
)
from core.projects.errors import (
    ProjectFormatError,
    ProjectResourceLimitError,
    ProjectSecurityError,
    ProjectValidationError,
)
from core.projects.migrations import migrate_legacy_recipe
from core.projects.schema import AssetBlob, ProjectSnapshot, WorkflowDocument


def make_snapshot() -> ProjectSnapshot:
    source = AssetBlob(
        asset_id="source-image",
        data=b"same-binary",
        media_type="image/png",
        filename="source.png",
    )
    duplicate = AssetBlob(
        asset_id="duplicate-copy",
        data=b"same-binary",
        media_type="application/octet-stream",
        filename="copy.bin",
    )
    document = WorkflowDocument(
        document_id="doc-converter",
        kind="converter",
        schema_version=1,
        payload={"parameters": {"targetWidthMm": 40.0}, "source": None},
        resource_refs=("source-image", "duplicate-copy"),
        required_capabilities=("converter.v1",),
    )
    return ProjectSnapshot.new(
        name="测试草稿",
        workflow_kinds=("converter",),
        documents=(document,),
        assets=(source, duplicate),
    )


def test_project_round_trip_preserves_identity_unicode_and_binary_assets(
    tmp_path: Path,
) -> None:
    snapshot = make_snapshot()
    path = tmp_path / "draft.lum"

    write_project(path, snapshot)
    restored = read_project(path)

    assert restored.project_id == snapshot.project_id
    assert restored.revision_id == snapshot.revision_id
    assert restored.name == "测试草稿"
    assert restored.assets["source-image"].data == b"same-binary"
    assert restored.assets["duplicate-copy"].data == b"same-binary"
    assert restored.documents[0].resource_refs == (
        "source-image",
        "duplicate-copy",
    )


def test_project_bytes_deduplicate_equal_asset_payloads() -> None:
    package = build_project_bytes(make_snapshot())

    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        asset_members = [
            name for name in archive.namelist() if name.startswith("assets/")
        ]

    assert asset_members == [
        "assets/a1f82722bc8e33aa9100d16001377c07366a779a2c42bc58fdeba9cf8fa9f1fd"
    ]


def test_project_rejects_path_traversal_and_duplicate_normalized_members() -> None:
    def archive_with_names(names: list[str]) -> bytes:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            for name in names:
                archive.writestr(name, b"{}")
        return stream.getvalue()

    with pytest.raises(ProjectSecurityError):
        read_project(archive_with_names(["../evil.json"]))

    with pytest.raises(ProjectSecurityError):
        read_project(archive_with_names(["manifest.json", "MANIFEST.json"]))


def test_project_rejects_malformed_manifest() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("manifest.json", b"not-json")
        archive.writestr("project.json", b"{}")

    with pytest.raises(ProjectFormatError):
        read_project(stream.getvalue())


def test_project_rejects_member_over_limit() -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("manifest.json", b"{}")
        archive.writestr("project.json", b"{}")
        archive.writestr("assets/too-large", b"12345")

    with pytest.raises(ProjectSecurityError):
        read_project(
            stream.getvalue(),
            limits=ProjectLimits(max_member_bytes=4),
        )


def test_project_rejects_scripted_or_external_svg_assets() -> None:
    with pytest.raises(ProjectValidationError):
        AssetBlob(
            asset_id="unsafe-svg",
            data=b'<svg><script>alert(1)</script></svg>',
            media_type="image/svg+xml",
            filename="unsafe.svg",
        )
    with pytest.raises(ProjectValidationError):
        AssetBlob(
            asset_id="external-svg",
            data=b'<svg><image href="https://example.test/a.png" /></svg>',
            media_type="image/svg+xml",
            filename="external.svg",
        )


def test_project_rejects_thumbnail_over_decoded_pixel_limit() -> None:
    width = 4097
    height = 4097
    png_header = (
        b"\x89PNG\r\n\x1a\n"
        + (13).to_bytes(4, "big")
        + b"IHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x06\x00\x00\x00"
    )
    thumbnail = AssetBlob(
        asset_id="thumbnail",
        data=png_header,
        media_type="image/png",
        role="resource",
    )
    snapshot = ProjectSnapshot.new(
        name="Large cover",
        workflow_kinds=("converter",),
        documents=(
            WorkflowDocument(
                document_id="doc",
                kind="converter",
                schema_version=1,
                payload={},
            ),
        ),
        thumbnail=thumbnail,
    )

    with pytest.raises(ProjectResourceLimitError):
        build_project_bytes(snapshot)


def test_atomic_write_keeps_existing_file_when_snapshot_is_invalid(
    tmp_path: Path,
) -> None:
    path = tmp_path / "draft.lum"
    path.write_bytes(b"old-project")

    invalid = ProjectSnapshot.new(
        name="invalid",
        workflow_kinds=("converter",),
        documents=(
            WorkflowDocument(
                document_id="doc",
                kind="converter",
                schema_version=1,
                payload={"safe": True},
            ),
        ),
    )
    invalid.documents[0].payload["sessionId"] = "must-not-be-persisted"

    with pytest.raises(ProjectValidationError):
        write_project(path, invalid)

    assert path.read_bytes() == b"old-project"


def test_legacy_recipe_migration_preserves_known_assets_and_reports_degraded_fields() -> None:
    raw = {
        "format": "lumina-recipe",
        "schema_version": 3,
        "source": "converter",
        "cover": {"width": 1, "height": 1, "mime_type": "image/png"},
        "asset": {
            "primary": {
                "filename": "source.png",
                "mime_type": "image/png",
                "byte_size": 3,
                "sha256": "ignored-by-fixture",
                "encoding": "base64",
                "payload_b64": base64.b64encode(b"abc").decode("ascii"),
            }
        },
        "recipe": {"converter": {"base": {}, "color_ops": {}}},
        "integrity": {"recipe_sha256": "", "asset_checksums": {}},
        "compat": {},
        "warnings": [],
    }

    migrated = migrate_legacy_recipe(raw)

    assert migrated.manifest_dict()["format"] == "lumina-project"
    assert migrated.assets["primary"].data == b"abc"
    assert "converter.color_ops.spatial_region_edits" in migrated.degraded_fields
    assert "converter.model_surface" in migrated.degraded_fields
