"""Portable LUT sources, including the actual native model and selected DBs.

The existing LUT loader remains the format owner. Only its path-bearing
metadata is rebound when a snapshot crosses machines.
"""

from __future__ import annotations

import copy
import io
import json
import math
from pathlib import Path, PurePosixPath
import tempfile
import zipfile

import msgpack
import numpy as np

from config import LUTMetadata, get_source_kind
from utils.lut_manager import LUTManager

MAX_DEPENDENCY_BYTES = 512 * 1024 * 1024
_PATH_FIELDS = {"native_model_package_path", "native_stage_model_path", "native_recipe_path"}


def validate_npz_budget(data: bytes) -> None:
    """Account for the inner NPZ expansion before NumPy allocates arrays."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        items = archive.infolist()
        if len(items) > 256 or len({item.filename for item in items}) != len(items) or sum(item.file_size for item in items) > MAX_DEPENDENCY_BYTES:
            raise ValueError("Expanded NPZ exceeds the project resource limit")
        for item in items:
            if not item.filename.endswith(".npy"):
                raise ValueError("Invalid NPZ array entry")
            with archive.open(item) as source:
                _validate_npy_header(source, item.file_size)


def _validate_npy_header(source, byte_size: int) -> None:
    version = np.lib.format.read_magic(source)
    if version not in {(1, 0), (2, 0)}:
        raise ValueError("Unsupported project NPY version")
    reader = np.lib.format.read_array_header_1_0 if version == (1, 0) else np.lib.format.read_array_header_2_0
    shape, _, dtype = reader(source)
    if dtype.hasobject or any(size < 0 for size in shape) or math.prod(shape) * dtype.itemsize > byte_size - source.tell():
        raise ValueError("Invalid project array dimensions or dtype")


def _save_snapshot_npz(path: Path, rgb, stacks, metadata: LUTMetadata) -> None:
    if (
        stacks is None
        and get_source_kind(metadata) == "legacy_lookup"
        and np.asarray(rgb).reshape(-1, 3).shape[0] in {32, 1024, 1296, 2468, 2738}
    ):
        # Freeze the existing preview loader's recipes, channel remapping and
        # outlier filtering before converting an implicit NPY lookup to NPZ.
        # This also repairs earlier project snapshots with missing recipes.
        from core.pipeline.processing_ops.lut_loader import load_lut

        with tempfile.TemporaryDirectory(prefix="classic_lut_", dir=path.parent) as directory:
            source = Path(directory) / "classic.npy"
            np.save(source, rgb, allow_pickle=False)
            runtime = load_lut(str(source), metadata.color_mode)
            rgb, stacks = runtime["lut_rgb"], runtime["ref_stacks"]
            metadata.layer_order = runtime["layer_order"]
    if stacks is not None:
        LUTManager.save_npz_with_metadata(str(path), rgb, stacks, metadata)
    else:
        # None must remain absent, not an object array requiring pickle.
        np.savez_compressed(path, rgb=rgb, metadata_json=np.array(json.dumps(metadata.to_dict())))


def _scrub_source_paths(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _scrub_source_paths(item)
            for key, item in value.items()
            if not str(key).endswith(("_path", "_paths"))
            and key not in {"source_references", "path_hint"}
        }
    if isinstance(value, list):
        return [_scrub_source_paths(item) for item in value]
    return value


def pack_lut_source(path: str) -> bytes:
    """Freeze loader output and every native dependency without machine paths."""
    rgb, stacks, original_metadata = LUTManager.load_lut_with_metadata(path)
    metadata = copy.deepcopy(original_metadata)
    original_extensions = metadata.extensions
    metadata.extensions = _scrub_source_paths(original_extensions)
    dependency_files: dict[str, bytes] = {}

    def capture(source: str) -> str:
        file = Path(source)
        if not file.is_file() or file.suffix.lower() not in {".json", ".msgpack", ".npz", ".npy"}:
            raise ValueError("Native LUT dependency is missing or unsupported")
        data = file.read_bytes()
        if file.suffix.lower() == ".json":
            data = json.dumps(_scrub_source_paths(json.loads(data)), ensure_ascii=False).encode("utf-8")
        elif file.suffix.lower() == ".msgpack":
            data = msgpack.packb(_scrub_source_paths(msgpack.unpackb(data, raw=False)), use_bin_type=True)
        name = f"dependencies/{len(dependency_files)}{file.suffix.lower()}"
        dependency_files[name] = data
        return name

    for field in _PATH_FIELDS:
        source = original_extensions.get(field)
        if source:
            metadata.extensions[field] = capture(source)
    if original_extensions.get("native_db_paths"):
        metadata.extensions["native_db_paths"] = [capture(source) for source in original_extensions["native_db_paths"]]
    with tempfile.TemporaryDirectory(prefix="lumina_lut_snapshot_") as directory:
        target = Path(directory) / "lut.npz"
        _save_snapshot_npz(target, rgb, stacks, metadata)
        dependency_files["lut.npz"] = target.read_bytes()
    if sum(map(len, dependency_files.values())) > MAX_DEPENDENCY_BYTES:
        raise ValueError("LUT source exceeds the project resource limit")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("source.json", '{"format":"lumina-lut-source","version":1}')
        for name, data in dependency_files.items():
            archive.writestr(name, data)
    return output.getvalue()


def unpack_lut_source(data: bytes, directory: Path) -> str:
    """Validate and materialize a snapshot exclusively inside its owned root."""
    if len(data) > MAX_DEPENDENCY_BYTES:
        raise ValueError("LUT source exceeds the project resource limit")
    # PR606 used direct NPZ snapshots. Convert those through the same loader,
    # dropping machine paths before exposing the resource to a new session.
    with zipfile.ZipFile(io.BytesIO(data)) as legacy:
        is_legacy = "source.json" not in legacy.namelist() and "rgb.npy" in legacy.namelist()
    if is_legacy:
        validate_npz_budget(data)
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "lut.npz"
        target.write_bytes(data)
        rgb, stacks, metadata = LUTManager.load_lut_with_metadata(str(target))
        if any(metadata.extensions.get(field) for field in (*_PATH_FIELDS, "native_db_paths")):
            raise ValueError("Legacy project did not embed its native LUT dependencies")
        metadata.extensions = _scrub_source_paths(metadata.extensions)
        _save_snapshot_npz(target, rgb, stacks, metadata)
        return str(target)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > 256 or len({info.filename for info in infos}) != len(infos):
            raise ValueError("Invalid LUT resource entries")
        if sum(info.file_size for info in infos) > MAX_DEPENDENCY_BYTES:
            raise ValueError("Expanded LUT source exceeds the project resource limit")
        for info in infos:
            name = PurePosixPath(info.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in info.filename or info.is_dir():
                raise ValueError("Invalid LUT resource path")
            if info.filename not in {"source.json", "lut.npz"} and (
                len(name.parts) != 2 or name.parts[0] != "dependencies" or name.suffix not in {".json", ".msgpack", ".npz", ".npy"}
            ):
                raise ValueError("Unexpected LUT resource")
        if json.loads(archive.read("source.json")) != {"format": "lumina-lut-source", "version": 1}:
            raise ValueError("Unsupported LUT source version")
        directory.mkdir(parents=True, exist_ok=True)
        for info in infos:
            target = directory / info.filename
            target.parent.mkdir(parents=True, exist_ok=True)
            content = archive.read(info)
            if target.suffix == ".npz":
                validate_npz_budget(content)
            elif target.suffix == ".npy":
                _validate_npy_header(io.BytesIO(content), len(content))
            if info.filename.startswith("dependencies/"):
                if target.suffix == ".json":
                    content = json.dumps(_scrub_source_paths(json.loads(content)), allow_nan=False).encode()
                elif target.suffix == ".msgpack":
                    content = msgpack.packb(_scrub_source_paths(msgpack.unpackb(content, raw=False)), use_bin_type=True)
            target.write_bytes(content)

    target = directory / "lut.npz"
    # Inspect NPZ metadata before the loader has a chance to follow references.
    with np.load(target, allow_pickle=False) as source:
        raw = source["metadata_json"]
        metadata = LUTMetadata.from_dict(json.loads(str(raw.item())))
    original = metadata.extensions
    safe_extensions = _scrub_source_paths(original)

    def rebind(name: str) -> str:
        if not isinstance(name, str) or name not in {info.filename for info in infos} or not name.startswith("dependencies/"):
            raise ValueError("Missing or external LUT dependency")
        return str((directory / name).resolve())

    for field in _PATH_FIELDS:
        if original.get(field):
            safe_extensions[field] = rebind(original[field])
    if original.get("native_db_paths"):
        safe_extensions["native_db_paths"] = [rebind(name) for name in original["native_db_paths"]]
    metadata.extensions = safe_extensions
    rgb, stacks, _ = LUTManager.load_lut_with_metadata(str(target))
    _save_snapshot_npz(target, rgb, stacks, metadata)
    return str(target)
