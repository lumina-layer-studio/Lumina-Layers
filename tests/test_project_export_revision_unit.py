from __future__ import annotations

from io import BytesIO
import hashlib
import shutil
import tracemalloc
import zipfile

import pytest

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


@pytest.mark.parametrize("tile_archive", [False, True])
def test_project_embedding_keeps_large_mesh_memory_bounded(tmp_path, tile_archive):
    """A highly compressible model must not expand completely in RAM."""
    model_path = tmp_path / "large.3mf"
    chunk = b"<vertex x='1' y='2' z='3'/>\n" * 20000
    digest = hashlib.sha256()
    with zipfile.ZipFile(model_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.comment = b"original 3mf comment"
        info = zipfile.ZipInfo("3D/3dmodel.model", (2026, 11, 12, 23, 4, 56))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.comment = b"mesh metadata"
        info.external_attr = 0o640 << 16
        with archive.open(info, "w") as model:
            for _ in range(32):
                model.write(chunk)
                digest.update(chunk)
    path = model_path
    if tile_archive:
        path = tmp_path / "tiles.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.comment = b"tile archive comment"
            archive.write(model_path, "tiles/large.3mf")
            archive.writestr("guide.txt", b"assembly guide")

    tracemalloc.start()
    try:
        embed_project_in_generated_file(path, b"frozen revision")
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 8 * 1024**2, f"Embedding allocated {peak:,} bytes"

    if tile_archive:
        restored = tmp_path / "restored.3mf"
        with zipfile.ZipFile(path) as archive:
            assert archive.comment == b"tile archive comment"
            assert archive.read("guide.txt") == b"assembly guide"
            with archive.open("tiles/large.3mf") as source, restored.open("wb") as target:
                shutil.copyfileobj(source, target)
        path = restored
    with zipfile.ZipFile(path) as archive:
        assert archive.comment == b"original 3mf comment"
        assert archive.read(EMBEDDED_PROJECT_PATH) == b"frozen revision"
        copied = archive.getinfo("3D/3dmodel.model")
        assert copied.date_time == info.date_time
        assert copied.comment == info.comment
        assert copied.external_attr == info.external_attr
        with archive.open(copied) as model:
            assert hashlib.file_digest(model, "sha256").digest() == digest.digest()


@pytest.mark.parametrize("tile_archive", [False, True])
def test_failed_embedding_preserves_original_and_removes_temporary_files(tmp_path, tile_archive):
    path = tmp_path / ("tiles.zip" if tile_archive else "model.3mf")
    original = _minimal_3mf().replace(b"model", b"BAD!!", 1)
    if tile_archive:
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("tiles/model.3mf", original)
        original = path.read_bytes()
    else:
        path.write_bytes(original)

    with pytest.raises(zipfile.BadZipFile):
        embed_project_in_generated_file(path, b"frozen revision")
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]
