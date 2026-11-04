from __future__ import annotations

from io import BytesIO
import zipfile

from core.projects.export import (
    EMBEDDED_PROJECT_PATH,
    embed_project_bytes_in_3mf,
    extract_embedded_project_from_3mf,
    embed_project_in_generated_file,
)


def _minimal_3mf() -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types" />',
        )
        archive.writestr(
            "_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships" />',
        )
        archive.writestr("3D/3dmodel.model", b"model")
    return output.getvalue()


def test_embedded_project_is_explicit_and_revision_bytes_are_frozen() -> None:
    source = _minimal_3mf()
    first_revision = b"lumina-project-revision-1"
    second_revision = b"lumina-project-revision-2"

    exported = embed_project_bytes_in_3mf(source, first_revision)
    assert extract_embedded_project_from_3mf(exported) == first_revision
    with zipfile.ZipFile(BytesIO(exported)) as archive:
        assert EMBEDDED_PROJECT_PATH in archive.namelist()
        content_types = archive.read("[Content_Types].xml")
        relationships = archive.read("_rels/.rels")
    assert b"application/vnd.lumina.project+zip" in content_types
    assert b"https://lumina.studio/relationships/project" in relationships
    # Real slicers read these OPC element names without resolving prefixes.
    assert b"<Relationships " in relationships
    assert b"<Relationship " in relationships
    assert b"<Types " in content_types
    assert b"<Override " in content_types

    later = embed_project_bytes_in_3mf(source, second_revision)
    assert extract_embedded_project_from_3mf(later) == second_revision
    assert extract_embedded_project_from_3mf(exported) == first_revision


def test_tile_archive_embeds_identical_revision_in_every_3mf(tmp_path):
    path = tmp_path / "tiles.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("tiles/a.3mf", _minimal_3mf())
        archive.writestr("tiles/b.3mf", _minimal_3mf())
        archive.writestr("guide.txt", b"assembly guide")
    embed_project_in_generated_file(path, b"frozen revision")
    with zipfile.ZipFile(path) as archive:
        for name in ["tiles/a.3mf", "tiles/b.3mf"]:
            assert extract_embedded_project_from_3mf(archive.read(name)) == b"frozen revision"
        assert archive.read("guide.txt") == b"assembly guide"
