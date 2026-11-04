"""Optional frozen .lum linkage for 3MF exports.

The normal 3MF path stays unchanged. Callers that explicitly request an
embedded project snapshot can add one OPC part under ``Metadata/Lumina``.
普通 3MF 导出保持不变；只有显式请求时才会在 ``Metadata/Lumina`` 下加入冻结的
项目快照 OPC part。
"""

from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import tempfile
from xml.dom import minidom
from xml.parsers.expat import ExpatError
import zipfile

from .errors import ProjectValidationError

EMBEDDED_PROJECT_PATH = "Metadata/Lumina/project.lum"
PROJECT_CONTENT_TYPE = "application/vnd.lumina.project+zip"
PROJECT_RELATIONSHIP_TYPE = "https://lumina.studio/relationships/project"
MAX_EMBEDDED_PROJECT_BYTES = 512 * 1024 * 1024

_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_RELATIONSHIPS_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _opc_document(data: bytes, namespace: str, root_name: str):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ProjectValidationError("3MF package XML contains a document type")
    try:
        document = minidom.parseString(data)
    except ExpatError as exc:
        raise ProjectValidationError("3MF package XML is invalid") from exc
    root = document.documentElement
    if root.namespaceURI != namespace or root.localName != root_name:
        raise ProjectValidationError("3MF package XML has an invalid root")
    return document, root


def _append_opc_element(document, root, name: str, attributes: dict[str, str]) -> None:
    # Preserve the existing prefix (normally the default namespace). Several
    # slicers require unprefixed OPC element names despite XML equivalence.
    qualified = f"{root.prefix}:{name}" if root.prefix else name
    child = document.createElementNS(root.namespaceURI, qualified)
    for key, value in attributes.items():
        child.setAttribute(key, value)
    root.appendChild(child)


def _ensure_content_type(xml_bytes: bytes) -> bytes:
    document, root = _opc_document(xml_bytes, _CONTENT_TYPES_NS, "Types")
    found = None
    for child in root.childNodes:
        if child.nodeType != child.ELEMENT_NODE or child.localName != "Override":
            continue
        if child.getAttribute("PartName") == "/" + EMBEDDED_PROJECT_PATH:
            found = child
            break
    if found is not None:
        if found.getAttribute("ContentType") != PROJECT_CONTENT_TYPE:
            raise ProjectValidationError("3MF project part has a conflicting content type")
    else:
        _append_opc_element(document, root, "Override", {
            "PartName": "/" + EMBEDDED_PROJECT_PATH, "ContentType": PROJECT_CONTENT_TYPE,
        })
    return document.toxml(encoding="utf-8")


def _ensure_relationships(xml_bytes: bytes) -> bytes:
    document, root = _opc_document(xml_bytes, _RELATIONSHIPS_NS, "Relationships")
    children = [child for child in root.childNodes if child.nodeType == child.ELEMENT_NODE and child.localName == "Relationship"]
    for child in children:
        if (
            child.getAttribute("Target") == "/" + EMBEDDED_PROJECT_PATH
        ):
            if child.getAttribute("Type") != PROJECT_RELATIONSHIP_TYPE:
                raise ProjectValidationError("3MF project relationship has a conflicting type")
            return document.toxml(encoding="utf-8")
    used_ids = {child.getAttribute("Id") for child in children}
    suffix = 1
    relationship_id = "rLuminaProject"
    while relationship_id in used_ids:
        suffix += 1
        relationship_id = f"rLuminaProject{suffix}"
    _append_opc_element(document, root, "Relationship", {
        "Id": relationship_id, "Type": PROJECT_RELATIONSHIP_TYPE, "Target": "/" + EMBEDDED_PROJECT_PATH,
    })
    return document.toxml(encoding="utf-8")


def embed_project_bytes_in_3mf(
    three_mf_bytes: bytes,
    project_bytes: bytes,
) -> bytes:
    """Add one frozen project part to an existing 3MF package.

    Args:
        three_mf_bytes: Existing OPC/ZIP 3MF bytes.
        project_bytes: Validated ``lumina-project`` package bytes.

    Returns:
        New 3MF bytes. The input is not modified.
    """
    if len(project_bytes) > MAX_EMBEDDED_PROJECT_BYTES:
        raise ProjectValidationError("Embedded project exceeds size limit")
    try:
        source = zipfile.ZipFile(BytesIO(three_mf_bytes), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise ProjectValidationError("3MF package is not a valid ZIP") from exc

    names = [info.filename for info in source.infolist()]
    if EMBEDDED_PROJECT_PATH in names and names.count(EMBEDDED_PROJECT_PATH) > 1:
        raise ProjectValidationError("3MF contains duplicate project parts")
    content_types = (
        source.read("[Content_Types].xml")
        if "[Content_Types].xml" in names
        else f'<?xml version="1.0" encoding="UTF-8"?><Types xmlns="{_CONTENT_TYPES_NS}" />'.encode()
    )
    relationships = (
        source.read("_rels/.rels")
        if "_rels/.rels" in names
        else f'<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="{_RELATIONSHIPS_NS}" />'.encode()
    )

    output = BytesIO()
    with source, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as destination:
        for info in source.infolist():
            if info.filename in {EMBEDDED_PROJECT_PATH, "[Content_Types].xml", "_rels/.rels"}:
                continue
            destination.writestr(info, source.read(info.filename))
        destination.writestr("[Content_Types].xml", _ensure_content_type(content_types))
        destination.writestr("_rels/.rels", _ensure_relationships(relationships))
        destination.writestr(EMBEDDED_PROJECT_PATH, project_bytes)
    return output.getvalue()


def embed_project_file_in_3mf(
    three_mf_path: str | os.PathLike[str],
    project_bytes: bytes,
) -> None:
    """Atomically replace a 3MF file with its explicit embedded-project form.

    将 3MF 替换为显式嵌入工程快照的版本，并使用同目录临时文件保证原文件安全。
    """
    path = Path(three_mf_path)
    updated = embed_project_bytes_in_3mf(path.read_bytes(), project_bytes)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as temporary:
            temporary.write(updated)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def extract_embedded_project_from_3mf(three_mf_bytes: bytes) -> bytes | None:
    """Read the optional frozen project part without executing its contents."""
    try:
        with zipfile.ZipFile(BytesIO(three_mf_bytes), "r") as archive:
            return archive.read(EMBEDDED_PROJECT_PATH) if EMBEDDED_PROJECT_PATH in archive.namelist() else None
    except (zipfile.BadZipFile, OSError, KeyError) as exc:
        raise ProjectValidationError("3MF package is not a valid ZIP") from exc


def embed_project_in_generated_file(output_path: str | os.PathLike[str], project_bytes: bytes) -> None:
    """Embed one frozen revision in each 3MF of a generated tile archive."""
    target = Path(output_path)
    if target.suffix.lower() == ".3mf":
        embed_project_file_in_3mf(target, project_bytes)
        return
    if target.suffix.lower() != ".zip":
        raise ProjectValidationError("Project embedding requires a 3MF or ZIP output")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    try:
        count = 0
        with zipfile.ZipFile(target) as source, zipfile.ZipFile(temporary_name, "w", zipfile.ZIP_DEFLATED) as destination:
            for info in source.infolist():
                data = source.read(info)
                if info.filename.lower().endswith(".3mf"):
                    data = embed_project_bytes_in_3mf(data, project_bytes)
                    count += 1
                destination.writestr(info, data)
            if count == 0:
                raise ProjectValidationError("Generated archive contains no 3MF files")
        os.replace(temporary_name, target)
    finally:
        Path(temporary_name).unlink(missing_ok=True)
