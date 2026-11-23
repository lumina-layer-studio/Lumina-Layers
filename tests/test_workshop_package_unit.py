from __future__ import annotations

import base64
import io
import json
import stat
import struct
import zlib
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest
from PIL import Image

from core.workshop import (
    WorkshopPackageError,
    extract_inspected_package,
    inspect_workshop_package,
)
from core.workshop import package_validator


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def valid_manifest() -> dict[str, object]:
    return {
        "manifestVersion": 1,
        "id": "fixture.hello",
        "version": "1.0.0",
        "name": {
            "zh-CN": "测试模块",
            "en-US": "Fixture module",
        },
        "description": {
            "zh-CN": "用于安装包测试",
            "en-US": "Used for package tests",
        },
        "publisher": "Lumina Layer Studio",
        "workshopApi": {
            "min": "1.0.0",
            "maxExclusive": "2.0.0",
        },
        "luminaVersion": {
            "min": "1.0.0",
        },
        "entrypoints": {
            "ui": "ui/index.html",
        },
        "permissions": [
            {
                "name": "project.storage",
                "reason": "Save editable fixture projects.",
            }
        ],
    }


def required_files() -> dict[str, bytes]:
    return {
        "ui/index.html": (
            b"<!doctype html><html><head></head><body>fixture</body></html>"
        ),
        "assets/icon.png": PNG_1X1,
        "README.md": b"# Fixture\n",
        "LICENSE": b"MIT\n",
    }


def raw_zip_info(name: str) -> ZipInfo:
    """Build a ZipInfo that stores ``name`` byte-exact on every platform.

    ``ZipInfo(name)`` rewrites ``\\`` to ``/`` on Windows, so an archive built
    from a plain string could never carry a backslash member there.
    """
    info = ZipInfo("placeholder")
    info.filename = name
    info.orig_filename = name
    return info


def write_raw_zip(
    tmp_path: Path,
    entries: list[tuple[str | ZipInfo, bytes]],
    *,
    compression: int = ZIP_DEFLATED,
    name: str = "module.lumina-workshop",
) -> Path:
    archive = tmp_path / name
    with ZipFile(archive, "w", compression=compression) as package:
        for entry_name, value in entries:
            package.writestr(entry_name, value)
    return archive


def write_workshop_zip(
    tmp_path: Path,
    *,
    manifest: dict[str, object] | None = None,
    files: dict[str, bytes] | None = None,
    compression: int = ZIP_DEFLATED,
    name: str = "module.lumina-workshop",
) -> Path:
    package_files = required_files()
    if files is not None:
        package_files.update(files)
    entries: list[tuple[str | ZipInfo, bytes]] = [
        (
            "manifest.json",
            json.dumps(
                manifest if manifest is not None else valid_manifest(),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
    ]
    entries.extend(package_files.items())
    return write_raw_zip(
        tmp_path,
        entries,
        compression=compression,
        name=name,
    )


def make_apng() -> bytes:
    output = io.BytesIO()
    first = Image.new("RGBA", (2, 2), (255, 0, 0, 255))
    second = Image.new("RGBA", (2, 2), (0, 0, 255, 255))
    first.save(
        output,
        format="PNG",
        save_all=True,
        append_images=[second],
        duration=100,
        loop=0,
    )
    return output.getvalue()


def make_png_header(width: int, height: int) -> bytes:
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

    def chunk(kind: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(kind)
        checksum = zlib.crc32(data, checksum)
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", checksum & 0xFFFFFFFF)
        )

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr_data) + chunk(b"IEND", b"")


def test_valid_package_is_inspected_without_execution(tmp_path: Path) -> None:
    archive = write_workshop_zip(tmp_path)

    inspected = inspect_workshop_package(archive)

    assert inspected.manifest.id == "fixture.hello"
    assert inspected.manifest.version == "1.0.0"
    assert inspected.entry_html == "ui/index.html"
    assert inspected.compressed_bytes == archive.stat().st_size
    assert inspected.unpacked_bytes > 0
    assert len(inspected.archive_sha256) == 64
    assert len(inspected.manifest_sha256) == 64


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("../escape.txt", "unsafe archive path"),
        ("/absolute.txt", "unsafe archive path"),
        (raw_zip_info("folder\\escape.txt"), "unsafe archive path"),
        ("UI/index.html", "case-insensitive duplicate"),
    ],
)
def test_archive_paths_fail_closed(
    tmp_path: Path,
    name: str | ZipInfo,
    message: str,
) -> None:
    archive = write_raw_zip(
        tmp_path,
        [("ui/index.html", b"ok"), (name, b"x")],
    )

    with pytest.raises(WorkshopPackageError, match=message):
        inspect_workshop_package(archive)


def test_symlink_member_is_rejected(tmp_path: Path) -> None:
    link = ZipInfo("assets/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive = write_raw_zip(tmp_path, [(link, b"../../outside")])

    with pytest.raises(WorkshopPackageError, match="symbolic link"):
        inspect_workshop_package(archive)


def test_more_than_2000_members_is_rejected(tmp_path: Path) -> None:
    archive = write_raw_zip(
        tmp_path,
        [(f"extra/{index}.txt", b"x") for index in range(2001)],
        compression=ZIP_STORED,
    )

    with pytest.raises(WorkshopPackageError, match="file count"):
        inspect_workshop_package(archive)


def test_declared_single_file_limit_is_checked_before_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = write_workshop_zip(tmp_path, compression=ZIP_STORED)
    monkeypatch.setattr(package_validator, "MAX_FILE_BYTES", 32)

    with pytest.raises(WorkshopPackageError, match="file size"):
        inspect_workshop_package(archive)


def test_declared_aggregate_limit_is_checked_before_reading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    archive = write_workshop_zip(tmp_path, compression=ZIP_STORED)
    monkeypatch.setattr(package_validator, "MAX_FILE_BYTES", 1024 * 1024)
    monkeypatch.setattr(package_validator, "MAX_UNPACKED_BYTES", 128)

    with pytest.raises(WorkshopPackageError, match="unpacked size"):
        inspect_workshop_package(archive)


def test_zip_bomb_ratio_is_rejected(tmp_path: Path) -> None:
    archive = write_raw_zip(
        tmp_path,
        [("ui/index.html", b"0" * (2 * 1024 * 1024))],
    )

    with pytest.raises(WorkshopPackageError, match="compression ratio"):
        inspect_workshop_package(archive, max_ratio=2)


def test_missing_fixed_file_is_rejected(tmp_path: Path) -> None:
    files = required_files()
    files.pop("LICENSE")
    archive = write_raw_zip(
        tmp_path,
        [
            (
                "manifest.json",
                json.dumps(valid_manifest()).encode("utf-8"),
            ),
            *files.items(),
        ],
    )

    with pytest.raises(WorkshopPackageError, match="missing required file"):
        inspect_workshop_package(archive)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda manifest: manifest.update({"unexpected": True}),
            "manifest",
        ),
        (
            lambda manifest: manifest.update({"version": "1.0"}),
            "SemVer",
        ),
        (
            lambda manifest: manifest["permissions"][0].update(
                {"name": "network.fetch"}
            ),
            "permission",
        ),
        (
            lambda manifest: manifest["permissions"][0].update({"reason": "  "}),
            "reason",
        ),
    ],
)
def test_manifest_is_strictly_validated(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    manifest = valid_manifest()
    mutate(manifest)
    archive = write_workshop_zip(tmp_path, manifest=manifest)

    with pytest.raises(WorkshopPackageError, match=message):
        inspect_workshop_package(archive)


def test_material_import_permission_requires_workshop_api_1_2(
    tmp_path: Path,
) -> None:
    manifest = valid_manifest()
    manifest["permissions"].append(
        {"name": "material.import", "reason": "Import the measured material."}
    )
    with pytest.raises(WorkshopPackageError, match="workshopApi.min"):
        inspect_workshop_package(write_workshop_zip(tmp_path, manifest=manifest))

    manifest["workshopApi"]["min"] = "1.2.0"
    accepted_dir = tmp_path / "accepted"
    accepted_dir.mkdir()
    inspected = inspect_workshop_package(
        write_workshop_zip(accepted_dir, manifest=manifest)
    )
    assert [permission.name for permission in inspected.manifest.permissions] == [
        "project.storage",
        "material.import",
    ]


@pytest.mark.parametrize(
    "html",
    [
        b"<html><script>ok()</script><head></head><body></body></html>",
        b"<html><head><script src='module.js'></script></head></html>",
        b"<html><head><link href='style.css'></head></html>",
        b"<html><head><style>body{background:url(icon.png)}</style></head></html>",
        b"<html><head></head><body><script>eval('1')</script></body></html>",
        b"<html><head></head><body><script>import('module.js')</script></body></html>",
        b"<html><head></head><img src='https://example.com/pixel.png'></html>",
    ],
)
def test_runtime_html_must_be_one_inline_self_contained_file(
    tmp_path: Path,
    html: bytes,
) -> None:
    archive = write_workshop_zip(
        tmp_path,
        files={"ui/index.html": html},
    )

    with pytest.raises(WorkshopPackageError, match="runtime HTML"):
        inspect_workshop_package(archive)


def test_runtime_html_allows_resource_syntax_inside_inline_javascript(
    tmp_path: Path,
) -> None:
    archive = write_workshop_zip(
        tmp_path,
        files={
            "ui/index.html": b"""
                <!doctype html>
                <html>
                  <head></head>
                  <body>
                    <script>
                      const hrefIsString =
                        typeof window.location.href == "string";
                      const image = new Image();
                      image.src = objectUrl;
                      const workerUrl = URL.createObjectURL(workerBlob);
                    </script>
                  </body>
                </html>
            """,
        },
    )

    inspected = inspect_workshop_package(archive)

    assert inspected.entry_html == "ui/index.html"


def test_runtime_html_rejects_external_url_in_style_attribute(
    tmp_path: Path,
) -> None:
    archive = write_workshop_zip(
        tmp_path,
        files={
            "ui/index.html": (
                b"<html><head></head><body "
                b"style='background:url(icon.png)'></body></html>"
            ),
        },
    )

    with pytest.raises(WorkshopPackageError, match="runtime HTML CSS"):
        inspect_workshop_package(archive)


@pytest.mark.parametrize(
    "name",
    [
        "ui/module.js",
        "ui/worker.mjs",
        "ui/extra.html",
        "ui/module.wasm",
    ],
)
def test_executable_files_outside_entry_html_are_rejected(
    tmp_path: Path,
    name: str,
) -> None:
    archive = write_workshop_zip(tmp_path, files={name: b"payload"})

    with pytest.raises(WorkshopPackageError, match="unexpected package file"):
        inspect_workshop_package(archive)


@pytest.mark.parametrize(
    ("name", "payload", "message"),
    [
        (
            "manifest.json",
            b"{" + b" " * (256 * 1024) + b"}",
            "manifest.json size",
        ),
        (
            "assets/icon.png",
            PNG_1X1 + b"x" * (2 * 1024 * 1024),
            "icon size",
        ),
        (
            "README.md",
            b"x" * (1024 * 1024 + 1),
            "README.md size",
        ),
        (
            "LICENSE",
            b"x" * (1024 * 1024 + 1),
            "LICENSE size",
        ),
    ],
    ids=["manifest", "icon", "readme", "license"],
)
def test_fixed_file_specific_limits_are_enforced(
    tmp_path: Path,
    name: str,
    payload: bytes,
    message: str,
) -> None:
    if name == "manifest.json":
        files = required_files()
        archive = write_raw_zip(
            tmp_path,
            [(name, payload), *files.items()],
            compression=ZIP_STORED,
        )
    else:
        archive = write_workshop_zip(
            tmp_path,
            files={name: payload},
            compression=ZIP_STORED,
        )

    with pytest.raises(WorkshopPackageError, match=message):
        inspect_workshop_package(archive)


def test_icon_must_be_a_static_png(tmp_path: Path) -> None:
    archive = write_workshop_zip(
        tmp_path,
        files={"assets/icon.png": b"<svg></svg>"},
    )

    with pytest.raises(WorkshopPackageError, match="static PNG"):
        inspect_workshop_package(archive)


def test_animated_png_icon_is_rejected(tmp_path: Path) -> None:
    archive = write_workshop_zip(
        tmp_path,
        files={"assets/icon.png": make_apng()},
    )

    with pytest.raises(WorkshopPackageError, match="animated"):
        inspect_workshop_package(archive)


def test_icon_decompression_dimensions_are_bounded(tmp_path: Path) -> None:
    archive = write_workshop_zip(
        tmp_path,
        files={"assets/icon.png": make_png_header(20_000, 1)},
    )

    with pytest.raises(WorkshopPackageError, match="dimensions"):
        inspect_workshop_package(archive)


@pytest.mark.parametrize(
    ("name", "payload"),
    [
        ("assets/gallery/payload.svg", b"<svg></svg>"),
        ("assets/gallery/payload.html", b"<html></html>"),
    ],
)
def test_gallery_rejects_executable_document_formats(
    tmp_path: Path,
    name: str,
    payload: bytes,
) -> None:
    archive = write_workshop_zip(tmp_path, files={name: payload})

    with pytest.raises(WorkshopPackageError, match="gallery image"):
        inspect_workshop_package(archive)


def test_gallery_count_is_bounded(tmp_path: Path) -> None:
    files = {
        f"assets/gallery/{index}.png": PNG_1X1
        for index in range(21)
    }
    archive = write_workshop_zip(tmp_path, files=files)

    with pytest.raises(WorkshopPackageError, match="gallery file count"):
        inspect_workshop_package(archive)


def test_gallery_images_must_be_static_and_dimension_bounded(
    tmp_path: Path,
) -> None:
    animated = write_workshop_zip(
        tmp_path,
        files={"assets/gallery/animated.png": make_apng()},
        name="animated.lumina-workshop",
    )
    oversized = write_workshop_zip(
        tmp_path,
        files={"assets/gallery/oversized.png": make_png_header(20_000, 1)},
        name="oversized.lumina-workshop",
    )

    with pytest.raises(WorkshopPackageError, match="animated"):
        inspect_workshop_package(animated)
    with pytest.raises(WorkshopPackageError, match="dimensions"):
        inspect_workshop_package(oversized)


@pytest.mark.parametrize("name", ["README.md", "LICENSE"])
def test_documents_must_be_utf8(tmp_path: Path, name: str) -> None:
    archive = write_workshop_zip(tmp_path, files={name: b"\xff\xfe"})

    with pytest.raises(WorkshopPackageError, match="UTF-8"):
        inspect_workshop_package(archive)


def test_inspected_package_extracts_only_after_validation(tmp_path: Path) -> None:
    archive = write_workshop_zip(tmp_path)
    inspected = inspect_workshop_package(archive)
    destination = tmp_path / "extracted"

    extracted = extract_inspected_package(inspected, destination)

    assert extracted == destination
    assert (destination / "manifest.json").is_file()
    assert (destination / "ui" / "index.html").read_bytes().startswith(
        b"<!doctype html>"
    )
    assert not (tmp_path / "escape.txt").exists()


def test_extraction_rejects_nonempty_destination(tmp_path: Path) -> None:
    archive = write_workshop_zip(tmp_path)
    inspected = inspect_workshop_package(archive)
    destination = tmp_path / "destination"
    destination.mkdir()
    (destination / "keep.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(WorkshopPackageError, match="empty destination"):
        extract_inspected_package(inspected, destination)

    assert (destination / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_extraction_rejects_archive_changed_after_inspection(
    tmp_path: Path,
) -> None:
    archive = write_workshop_zip(tmp_path)
    inspected = inspect_workshop_package(archive)
    archive.write_bytes(archive.read_bytes() + b"changed")

    with pytest.raises(WorkshopPackageError, match="changed after inspection"):
        extract_inspected_package(inspected, tmp_path / "destination")
