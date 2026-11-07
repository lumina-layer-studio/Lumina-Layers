"""Fail-closed inspection for installable Creative Workshop packages."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import stat
import struct
import sys
import unicodedata
from collections.abc import Iterable
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import (
    ZIP_DEFLATED,
    ZIP_STORED,
    BadZipFile,
    LargeZipFile,
    ZipFile,
    ZipInfo,
)

from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from .backend.locks import parse_backend_lock
from .constants import (
    BACKEND_PACKAGE_PREFIX,
    BACKEND_SOURCE_SUFFIXES,
    MAX_BACKEND_FILE_BYTES,
    MAX_BACKEND_FILES,
    MAX_BACKEND_TOTAL_BYTES,
    MAX_COMPRESSION_RATIO,
    MAX_FILE_BYTES,
    MAX_FILE_COUNT,
    MAX_GALLERY_FILE_BYTES,
    MAX_GALLERY_FILES,
    MAX_GALLERY_PIXELS,
    MAX_ICON_BYTES,
    MAX_ICON_PIXELS,
    MAX_IMAGE_EDGE,
    MAX_MANIFEST_BYTES,
    MAX_PACKAGE_BYTES,
    MAX_TEXT_DOCUMENT_BYTES,
    MAX_UNPACKED_BYTES,
    REQUIRED_PACKAGE_FILES,
)
from .errors import WorkshopPackageError
from .models import (
    BackendDeclaration,
    InspectedWorkshopPackage,
    PackageInspectionSummary,
    WorkshopManifest,
    WorkshopManifestV2,
    parse_workshop_manifest,
)


_READ_CHUNK_BYTES = 1024 * 1024
_ALLOWED_COMPRESSION_METHODS = frozenset({ZIP_STORED, ZIP_DEFLATED})
_GALLERY_PREFIX = "assets/gallery/"
_GALLERY_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})
_RESERVED_DEVICE_NAMES = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{index}" for index in range(1, 10)),
        *(f"lpt{index}" for index in range(1, 10)),
    }
)
_CSS_URL = re.compile(r"url\s*\(\s*([^)]+?)\s*\)", flags=re.IGNORECASE)
_HEAD_TAG = re.compile(r"<head(?:\s|>)", flags=re.IGNORECASE)
_SCRIPT_TAG = re.compile(r"<script(?:\s|>)", flags=re.IGNORECASE)
_DYNAMIC_CODE = re.compile(r"\b(?:eval|import)\s*\(", flags=re.IGNORECASE)
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SUSPICIOUS_MEDIA_MARKERS = (
    b"http://",
    b"https://",
    b"file://",
    b"javascript:",
    b"<script",
    b"<svg",
    b"<html",
)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_READ_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _is_symlink(info: ZipInfo) -> bool:
    if info.create_system != 3:
        return False
    mode = (info.external_attr >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def _has_unsupported_file_type(info: ZipInfo) -> bool:
    if info.create_system != 3:
        return False
    mode = (info.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    return file_type not in {0, stat.S_IFREG}


def _validate_member_path(info: ZipInfo, seen: set[str]) -> str:
    # Validate the raw stored name: on Windows ``ZipInfo.filename`` rewrites
    # ``\`` to ``/`` and truncates at NUL, which would hide unsafe paths.
    name = info.orig_filename
    if (
        not name
        or "\x00" in name
        or "\\" in name
        or name.startswith("/")
        or name.endswith("/")
        or unicodedata.normalize("NFC", name) != name
    ):
        raise WorkshopPackageError(f"unsafe archive path: {name!r}")

    raw_parts = name.split("/")
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in raw_parts)
        or len(path.parts) != len(raw_parts)
    ):
        raise WorkshopPackageError(f"unsafe archive path: {name!r}")

    for part in raw_parts:
        if ":" in part or part.endswith((" ", ".")):
            raise WorkshopPackageError(f"unsafe archive path: {name!r}")
        device_name = part.split(".", 1)[0].casefold()
        if device_name in _RESERVED_DEVICE_NAMES:
            raise WorkshopPackageError(
                f"unsafe archive path uses a device name: {name!r}"
            )

    collision_key = name.casefold()
    if collision_key in seen:
        raise WorkshopPackageError(
            f"case-insensitive duplicate archive path: {name!r}"
        )
    seen.add(collision_key)

    if _is_symlink(info):
        raise WorkshopPackageError(
            f"symbolic link archive member is not allowed: {name!r}"
        )
    if _has_unsupported_file_type(info):
        raise WorkshopPackageError(
            f"unsupported archive member type: {name!r}"
        )
    if info.flag_bits & 0x1:
        raise WorkshopPackageError(
            f"encrypted archive member is not allowed: {name!r}"
        )
    if info.compress_type not in _ALLOWED_COMPRESSION_METHODS:
        raise WorkshopPackageError(
            f"unsupported archive compression method: {name!r}"
        )
    return name


def _validate_declared_limits(
    members: list[ZipInfo],
    *,
    max_ratio: float,
) -> int:
    if len(members) > MAX_FILE_COUNT:
        raise WorkshopPackageError(
            f"archive file count exceeds {MAX_FILE_COUNT}"
        )
    if max_ratio <= 0:
        raise WorkshopPackageError("compression ratio limit must be positive")

    unpacked_bytes = 0
    compressed_payload_bytes = 0
    for info in members:
        if info.file_size < 0 or info.compress_size < 0:
            raise WorkshopPackageError("archive contains a negative file size")
        if info.file_size > MAX_FILE_BYTES:
            raise WorkshopPackageError(
                f"declared file size exceeds limit: {info.filename!r}"
            )
        unpacked_bytes += info.file_size
        compressed_payload_bytes += info.compress_size
        if unpacked_bytes > MAX_UNPACKED_BYTES:
            raise WorkshopPackageError(
                "declared unpacked size exceeds package limit"
            )
        if info.file_size and (
            info.file_size / max(info.compress_size, 1) > max_ratio
        ):
            raise WorkshopPackageError(
                f"archive compression ratio exceeds limit: {info.filename!r}"
            )

    if unpacked_bytes and (
        unpacked_bytes / max(compressed_payload_bytes, 1) > max_ratio
    ):
        raise WorkshopPackageError(
            "aggregate archive compression ratio exceeds limit"
        )
    return unpacked_bytes


def _validate_package_file_set(
    member_names: set[str],
) -> tuple[list[str], list[str]]:
    missing = REQUIRED_PACKAGE_FILES - member_names
    if missing:
        missing_list = ", ".join(sorted(missing))
        raise WorkshopPackageError(
            f"missing required file: {missing_list}"
        )

    gallery_names: list[str] = []
    backend_names: list[str] = []
    for name in member_names:
        if name in REQUIRED_PACKAGE_FILES:
            continue
        if name.startswith(_GALLERY_PREFIX):
            gallery_names.append(name)
            continue
        if name.startswith(BACKEND_PACKAGE_PREFIX):
            backend_names.append(name)
            continue
        raise WorkshopPackageError(f"unexpected package file: {name!r}")

    if len(gallery_names) > MAX_GALLERY_FILES:
        raise WorkshopPackageError(
            f"gallery file count exceeds {MAX_GALLERY_FILES}"
        )
    return sorted(gallery_names), sorted(backend_names)


def _validate_backend_files(
    package: ZipFile,
    members_by_name: dict[str, ZipInfo],
    backend_names: list[str],
    declaration: BackendDeclaration,
) -> None:
    """Accept only bounded UTF-8 backend sources and valid wheel locks."""

    if len(backend_names) > MAX_BACKEND_FILES:
        raise WorkshopPackageError(
            f"backend file count exceeds {MAX_BACKEND_FILES}"
        )
    total = 0
    for name in backend_names:
        info = members_by_name[name]
        parts = name.split("/")
        if "__pycache__" in parts or any(part.startswith(".") for part in parts):
            raise WorkshopPackageError(
                f"backend cache or hidden file is not allowed: {name!r}"
            )
        if Path(name).suffix.casefold() not in BACKEND_SOURCE_SUFFIXES:
            raise WorkshopPackageError(
                "backend files must be text sources; native code comes "
                f"only from locked wheels: {name!r}"
            )
        if info.file_size > MAX_BACKEND_FILE_BYTES:
            raise WorkshopPackageError(
                f"backend file size exceeds limit: {name!r}"
            )
        total += info.file_size
        if total > MAX_BACKEND_TOTAL_BYTES:
            raise WorkshopPackageError("backend source size exceeds limit")
        _decode_utf8(name, _read_member(package, info))

    present = set(backend_names)
    for required in declaration.referenced_files():
        if required not in present:
            raise WorkshopPackageError(
                f"backend declaration references a missing file: {required!r}"
            )
    for lock_name in (
        declaration.lock,
        *(variant.lock for variant in declaration.variants),
    ):
        parse_backend_lock(_read_member(package, members_by_name[lock_name]))


def _validate_specific_declared_limits(
    members_by_name: dict[str, ZipInfo],
    gallery_names: Iterable[str],
) -> None:
    checks = (
        ("manifest.json", MAX_MANIFEST_BYTES, "manifest.json size"),
        ("assets/icon.png", MAX_ICON_BYTES, "icon size"),
        ("README.md", MAX_TEXT_DOCUMENT_BYTES, "README.md size"),
        ("LICENSE", MAX_TEXT_DOCUMENT_BYTES, "LICENSE size"),
    )
    for name, maximum, label in checks:
        if members_by_name[name].file_size > maximum:
            raise WorkshopPackageError(f"{label} exceeds limit")

    for name in gallery_names:
        if members_by_name[name].file_size > MAX_GALLERY_FILE_BYTES:
            raise WorkshopPackageError(
                f"gallery image size exceeds limit: {name!r}"
            )


def _read_member(package: ZipFile, info: ZipInfo) -> bytes:
    try:
        with package.open(info, "r") as stream:
            value = stream.read(info.file_size + 1)
            if stream.read(1):
                raise WorkshopPackageError(
                    f"actual file size exceeds declaration: {info.filename!r}"
                )
    except WorkshopPackageError:
        raise
    except (BadZipFile, OSError, RuntimeError, EOFError) as exc:
        raise WorkshopPackageError(
            f"archive member could not be read: {info.filename!r}"
        ) from exc

    if len(value) != info.file_size:
        raise WorkshopPackageError(
            f"actual file size does not match declaration: {info.filename!r}"
        )
    return value


def _decode_utf8(name: str, value: bytes) -> str:
    try:
        text = value.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WorkshopPackageError(f"{name} must be valid UTF-8") from exc
    if "\x00" in text:
        raise WorkshopPackageError(f"{name} must not contain NUL bytes")
    return text


def _json_object_without_duplicates(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise WorkshopPackageError(
                f"invalid manifest: duplicate JSON field {key!r}"
            )
        value[key] = item
    return value


def _parse_manifest(value: bytes) -> WorkshopManifest:
    text = _decode_utf8("manifest.json", value)
    try:
        raw = json.loads(
            text,
            object_pairs_hook=_json_object_without_duplicates,
        )
    except WorkshopPackageError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise WorkshopPackageError("invalid manifest JSON") from exc
    if not isinstance(raw, dict):
        raise WorkshopPackageError("invalid manifest: root must be an object")
    try:
        return parse_workshop_manifest(raw)
    except ValidationError as exc:
        raise WorkshopPackageError(f"invalid manifest: {exc}") from exc


def _is_inline_resource(value: str) -> bool:
    normalized = value.strip().strip("\"'").strip()
    lowered = normalized.casefold()
    return (
        not normalized
        or normalized.startswith("#")
        or lowered.startswith("data:")
        or lowered.startswith("blob:")
        or lowered == "about:blank"
    )


class _RuntimeHtmlResourceValidator(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._inside_style = False

    @staticmethod
    def _validate_css(value: str) -> None:
        for match in _CSS_URL.finditer(value):
            if not _is_inline_resource(match.group(1)):
                raise WorkshopPackageError(
                    "runtime HTML CSS must use only inline resources"
                )

    @classmethod
    def _validate_attributes(
        cls,
        attributes: list[tuple[str, str | None]],
    ) -> None:
        for name, value in attributes:
            if value is None:
                continue
            normalized_name = name.casefold()
            if (
                normalized_name in {"src", "href"}
                and not _is_inline_resource(value)
            ):
                raise WorkshopPackageError(
                    "runtime HTML must not reference package or network files"
                )
            if normalized_name == "style":
                cls._validate_css(value)

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._validate_attributes(attrs)
        if tag.casefold() == "style":
            self._inside_style = True

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self._validate_attributes(attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "style":
            self._inside_style = False

    def handle_data(self, data: str) -> None:
        if self._inside_style:
            self._validate_css(data)


def _validate_runtime_html(value: bytes) -> None:
    try:
        html = value.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WorkshopPackageError(
            "runtime HTML must be valid UTF-8"
        ) from exc
    if "\x00" in html:
        raise WorkshopPackageError("runtime HTML must not contain NUL bytes")

    head = _HEAD_TAG.search(html)
    script = _SCRIPT_TAG.search(html)
    if head is None or (script is not None and script.start() < head.start()):
        raise WorkshopPackageError(
            "runtime HTML must place <head> before the first <script>"
        )
    if _DYNAMIC_CODE.search(html):
        raise WorkshopPackageError(
            "runtime HTML must not use eval or dynamic import"
        )

    validator = _RuntimeHtmlResourceValidator()
    validator.feed(html)
    validator.close()


def _png_dimensions(value: bytes) -> tuple[int, int] | None:
    if not value.startswith(_PNG_SIGNATURE) or len(value) < 33:
        return None
    if value[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", value[16:24])


def _validate_dimensions(
    *,
    width: int,
    height: int,
    max_pixels: int,
    label: str,
) -> None:
    if (
        width <= 0
        or height <= 0
        or width > MAX_IMAGE_EDGE
        or height > MAX_IMAGE_EDGE
        or width * height > max_pixels
    ):
        raise WorkshopPackageError(f"{label} dimensions exceed limit")


def _contains_suspicious_media_metadata(value: bytes) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in _SUSPICIOUS_MEDIA_MARKERS)


def _validate_image(
    *,
    name: str,
    value: bytes,
    icon: bool,
) -> None:
    suffix = Path(name).suffix.casefold()
    if icon:
        if suffix != ".png" or not value.startswith(_PNG_SIGNATURE):
            raise WorkshopPackageError("icon must be a static PNG")
        expected_format = "PNG"
        max_pixels = MAX_ICON_PIXELS
        label = "icon"
    else:
        if suffix not in _GALLERY_SUFFIXES:
            raise WorkshopPackageError(
                "gallery image must be PNG, JPEG, or WebP"
            )
        signatures_match = (
            suffix == ".png"
            and value.startswith(_PNG_SIGNATURE)
        ) or (
            suffix in {".jpg", ".jpeg"}
            and value.startswith(b"\xff\xd8\xff")
        ) or (
            suffix == ".webp"
            and len(value) >= 12
            and value.startswith(b"RIFF")
            and value[8:12] == b"WEBP"
        )
        if not signatures_match:
            raise WorkshopPackageError(
                "gallery image signature does not match its extension"
            )
        expected_formats_by_suffix = {
            ".png": "PNG",
            ".jpg": "JPEG",
            ".jpeg": "JPEG",
            ".webp": "WEBP",
        }
        expected_format = expected_formats_by_suffix[suffix]
        max_pixels = MAX_GALLERY_PIXELS
        label = "gallery image"

    png_size = _png_dimensions(value)
    if png_size is not None:
        _validate_dimensions(
            width=png_size[0],
            height=png_size[1],
            max_pixels=max_pixels,
            label=label,
        )
    if b"acTL" in value or (
        suffix == ".webp" and b"ANIM" in value[:64]
    ):
        raise WorkshopPackageError(f"{label} must not be animated")
    if _contains_suspicious_media_metadata(value):
        raise WorkshopPackageError(
            f"{label} contains an external metadata reference"
        )

    try:
        with io.BytesIO(value) as io_path, Image.open(io_path) as image:
            if image.format != expected_format:
                raise WorkshopPackageError(
                    f"{label} format does not match its package path"
                )
            width, height = image.size
            _validate_dimensions(
                width=width,
                height=height,
                max_pixels=max_pixels,
                label=label,
            )
            if getattr(image, "n_frames", 1) != 1:
                raise WorkshopPackageError(f"{label} must not be animated")
            if any(
                key in image.info
                for key in (
                    "exif",
                    "xmp",
                    "XML:com.adobe.xmp",
                    "icc_profile",
                    "comment",
                )
            ):
                raise WorkshopPackageError(
                    f"{label} contains unsupported metadata"
                )
            image.verify()
    except WorkshopPackageError:
        raise
    except Image.DecompressionBombError as exc:
        raise WorkshopPackageError(
            f"{label} dimensions exceed limit"
        ) from exc
    except (
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
    ) as exc:
        raise WorkshopPackageError(f"{label} is malformed") from exc


def _inspect_open_zip(
    package: ZipFile,
    *,
    archive_path: Path,
    compressed_bytes: int,
    archive_sha256: str,
    max_ratio: float,
) -> InspectedWorkshopPackage:
    members = package.infolist()
    seen: set[str] = set()
    members_by_name: dict[str, ZipInfo] = {}
    for info in members:
        name = _validate_member_path(info, seen)
        members_by_name[name] = info

    unpacked_bytes = _validate_declared_limits(
        members,
        max_ratio=max_ratio,
    )
    gallery_names, backend_names = _validate_package_file_set(
        set(members_by_name)
    )
    _validate_specific_declared_limits(members_by_name, gallery_names)

    manifest_bytes = _read_member(package, members_by_name["manifest.json"])
    runtime_html = _read_member(package, members_by_name["ui/index.html"])
    icon_bytes = _read_member(package, members_by_name["assets/icon.png"])
    readme_bytes = _read_member(package, members_by_name["README.md"])
    license_bytes = _read_member(package, members_by_name["LICENSE"])

    manifest = _parse_manifest(manifest_bytes)
    if isinstance(manifest, WorkshopManifestV2):
        _validate_backend_files(
            package,
            members_by_name,
            backend_names,
            manifest.backend,
        )
    elif backend_names:
        raise WorkshopPackageError("backend files require manifest v2")
    _validate_runtime_html(runtime_html)
    _validate_image(
        name="assets/icon.png",
        value=icon_bytes,
        icon=True,
    )
    _decode_utf8("README.md", readme_bytes)
    _decode_utf8("LICENSE", license_bytes)

    for name in gallery_names:
        _validate_image(
            name=name,
            value=_read_member(package, members_by_name[name]),
            icon=False,
        )

    return InspectedWorkshopPackage(
        archive_path=archive_path,
        manifest=manifest,
        entry_html=manifest.entrypoints.ui,
        compressed_bytes=compressed_bytes,
        unpacked_bytes=unpacked_bytes,
        archive_sha256=archive_sha256,
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        member_names=tuple(sorted(members_by_name)),
    )


def inspect_workshop_package(
    archive_path: str | Path,
    *,
    max_ratio: float = MAX_COMPRESSION_RATIO,
) -> InspectedWorkshopPackage:
    """Inspect one Workshop package without executing module code.

    在不执行模块代码的前提下检查一个创意工坊安装包。
    """

    path = Path(archive_path).expanduser().resolve()
    if path.suffix != ".lumina-workshop":
        raise WorkshopPackageError(
            "Workshop packages must use the .lumina-workshop extension"
        )
    try:
        compressed_bytes = path.stat().st_size
    except OSError as exc:
        raise WorkshopPackageError("Workshop package is not readable") from exc
    if not path.is_file():
        raise WorkshopPackageError("Workshop package is not a regular file")
    if compressed_bytes > MAX_PACKAGE_BYTES:
        raise WorkshopPackageError("compressed package size exceeds limit")

    try:
        archive_sha256 = _hash_file(path)
        with ZipFile(path, "r", allowZip64=True) as package:
            inspected = _inspect_open_zip(
                package,
                archive_path=path,
                compressed_bytes=compressed_bytes,
                archive_sha256=archive_sha256,
                max_ratio=max_ratio,
            )
    except WorkshopPackageError:
        raise
    except (BadZipFile, LargeZipFile, OSError, RuntimeError) as exc:
        raise WorkshopPackageError("invalid Workshop ZIP package") from exc

    if _hash_file(path) != archive_sha256:
        raise WorkshopPackageError("package changed during inspection")
    return inspected


def _destination_is_empty(destination: Path) -> bool:
    if not destination.exists():
        return True
    if not destination.is_dir():
        return False
    try:
        next(destination.iterdir())
    except StopIteration:
        return True
    return False


def _safe_destination_path(root: Path, member_name: str) -> Path:
    target = root.joinpath(*PurePosixPath(member_name).parts)
    root_resolved = root.resolve()
    target_resolved = target.resolve(strict=False)
    try:
        target_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise WorkshopPackageError(
            f"unsafe extraction path: {member_name!r}"
        ) from exc
    return target


def extract_inspected_package(
    inspected: InspectedWorkshopPackage,
    destination: str | Path,
) -> Path:
    """Extract an already-inspected package into an empty directory.

    将已检查的安装包解压到空目录。
    """

    archive_path = inspected.archive_path
    if _hash_file(archive_path) != inspected.archive_sha256:
        raise WorkshopPackageError("package changed after inspection")

    root = Path(destination).expanduser().resolve()
    if not _destination_is_empty(root):
        raise WorkshopPackageError("package extraction requires empty destination")
    root.mkdir(parents=True, exist_ok=True)

    try:
        with ZipFile(archive_path, "r", allowZip64=True) as package:
            members = {info.filename: info for info in package.infolist()}
            if tuple(sorted(members)) != inspected.member_names:
                raise WorkshopPackageError("package changed after inspection")
            for member_name in inspected.member_names:
                info = members[member_name]
                target = _safe_destination_path(root, member_name)
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with package.open(info, "r") as source, target.open("xb") as sink:
                    while chunk := source.read(_READ_CHUNK_BYTES):
                        written += len(chunk)
                        if (
                            written > info.file_size
                            or written > MAX_FILE_BYTES
                        ):
                            raise WorkshopPackageError(
                                "actual file size exceeds declaration"
                            )
                        sink.write(chunk)
                if written != info.file_size:
                    raise WorkshopPackageError(
                        "actual file size does not match declaration"
                    )
    except WorkshopPackageError:
        raise
    except (BadZipFile, OSError, RuntimeError) as exc:
        raise WorkshopPackageError("package extraction failed") from exc
    return root


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect one .lumina-workshop package without extraction.",
    )
    parser.add_argument("archive", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the read-only package inspection CLI.

    运行只读的创意工坊安装包检查命令。
    """

    args = _build_parser().parse_args(argv)
    try:
        inspected = inspect_workshop_package(args.archive)
    except WorkshopPackageError as exc:
        print(f"Workshop package rejected: {exc}", file=sys.stderr)
        return 2
    summary = PackageInspectionSummary.from_inspected(inspected)
    print(
        json.dumps(
            summary.as_json_object(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
