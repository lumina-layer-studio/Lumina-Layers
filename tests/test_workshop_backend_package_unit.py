"""Manifest v2, backend lock, and package-file rules for module backends."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from core.workshop import WorkshopPackageError, inspect_workshop_package
from core.workshop.backend.locks import (
    WheelSourcePolicy,
    estimated_wheel,
    parse_backend_lock,
    render_install_lock,
)
from core.workshop.models import WorkshopManifestV1, WorkshopManifestV2
from workshop_backend_fixture import PNG_1X1, backend_manifest

SHA = "a" * 63 + "b"
LOCK = f"""
lock-version = "1.0"
requires-python = ">=3.12"

[[packages]]
name = "Demo_Pkg"
version = "1.2.3"
wheels = [
  {{ url = "https://files.pythonhosted.org/packages/aa/demo_pkg-1.2.3-cp312-cp312-win_amd64.whl", size = 1000, hashes = {{ sha256 = "{SHA}" }} }},
  {{ url = "https://files.pythonhosted.org/packages/bb/demo_pkg-1.2.3-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl", size = 2000, hashes = {{ sha256 = "{'c' * 64}" }} }},
]
"""


def write_package(tmp_path: Path, manifest: dict, files: dict[str, bytes]) -> Path:
    path = tmp_path / f"{manifest['id']}-{manifest['version']}.lumina-workshop"
    entries = {
        "manifest.json": json.dumps(manifest).encode("utf-8"),
        "ui/index.html": b"<!doctype html><html><head></head><body>ok</body></html>",
        "assets/icon.png": PNG_1X1,
        "README.md": b"# ok\n",
        "LICENSE": b"MIT\n",
        **files,
    }
    with ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return path


def backend_files(lock: str = LOCK) -> dict[str, bytes]:
    return {"backend/main.py": b"print('ok')\n", "backend/pylock.toml": lock.encode("utf-8")}


def test_lock_digest_ignores_formatting_and_normalizes_names() -> None:
    first = parse_backend_lock(LOCK.encode())
    reformatted = parse_backend_lock(("# comment\n" + LOCK.replace("Demo_Pkg", "demo-pkg")).encode())
    assert first.packages[0].name == "demo-pkg"
    assert first.digest == reformatted.digest
    changed = parse_backend_lock(LOCK.replace("1.2.3", "1.2.4", 1).encode())
    assert changed.digest != first.digest


@pytest.mark.parametrize(
    ("original", "replacement"),
    [
        ('url = "https://files', 'url = "http://files'),
        (f'sha256 = "{SHA}"', f'md5 = "{SHA}"'),
        (f'sha256 = "{SHA}"', 'sha256 = "not-a-digest"'),
    ],
)
def test_lock_requires_https_and_sha256(original: str, replacement: str) -> None:
    text = LOCK.replace(original, replacement, 1)
    assert text != LOCK
    with pytest.raises(WorkshopPackageError):
        parse_backend_lock(text.encode())


def test_lock_rejects_source_builds_and_local_paths() -> None:
    sdist = LOCK + '\n[[packages]]\nname = "built"\nversion = "1.0"\n[packages.sdist]\nurl = "https://x.invalid/built.tar.gz"\n'
    with pytest.raises(WorkshopPackageError, match="wheels only"):
        parse_backend_lock(sdist.encode())
    local = LOCK.replace('url = "https://files.pythonhosted.org/packages/aa/', 'path = "wheels/', 1)
    with pytest.raises(WorkshopPackageError):
        parse_backend_lock(local.encode())


def test_wheelhouse_and_mirror_rewrite_locations_but_keep_hashes(tmp_path: Path) -> None:
    lock = parse_backend_lock(LOCK.encode())
    (tmp_path / "demo_pkg-1.2.3-cp312-cp312-win_amd64.whl").write_bytes(b"x")
    rendered = render_install_lock(
        lock,
        WheelSourcePolicy(wheelhouse=tmp_path, mirror_prefix="https://mirror.example/pypi/"),
    )
    reparsed_hashes = {wheel.sha256 for wheel in parse_backend_lock(
        rendered.replace("file:///", "https://local.invalid/").encode()
    ).packages[0].wheels}
    assert reparsed_hashes == {wheel.sha256 for wheel in lock.packages[0].wheels}
    assert (tmp_path / "demo_pkg-1.2.3-cp312-cp312-win_amd64.whl").resolve().as_uri() in rendered
    assert "https://mirror.example/pypi/packages/bb/" in rendered


def test_preview_wheel_selection_matches_platform() -> None:
    package = parse_backend_lock(LOCK.encode()).packages[0]
    windows = estimated_wheel(package, platform_key="windows-x86_64", python_version="3.12")
    linux = estimated_wheel(package, platform_key="linux-x86_64", python_version="3.12")
    assert windows is not None and windows.size == 1000
    assert linux is not None and linux.size == 2000
    assert estimated_wheel(package, platform_key="macos-arm64", python_version="3.12") is None


def test_v2_manifest_requires_backend_api_and_valid_declaration() -> None:
    manifest = backend_manifest("fixture.ok", "1.0.0")
    assert isinstance(WorkshopManifestV2.model_validate(manifest), WorkshopManifestV2)
    old_api = {**manifest, "workshopApi": {"min": "1.0.0", "maxExclusive": "2.0.0"}}
    with pytest.raises(ValueError, match="workshopApi.min"):
        WorkshopManifestV2.model_validate(old_api)
    for bad in (
        {"entry": "main.py"},
        {"entry": "backend/../escape.py"},
        {"lock": "backend/requirements.txt"},
        {"lock": "backend/locks.v2.toml"},
        {"python": "3.9"},
        {"platforms": ["windows-arm64"]},
        {"capabilities": [{"name": "root-access", "reason": "no"}]},
    ):
        declaration = {**manifest["backend"], **bad}
        with pytest.raises(ValueError):
            WorkshopManifestV2.model_validate({**manifest, "backend": declaration})
    with pytest.raises(ValueError):
        WorkshopManifestV1.model_validate(manifest)


def test_package_accepts_backend_sources_and_validates_locks(tmp_path: Path) -> None:
    manifest = backend_manifest("fixture.ok", "1.0.0")
    inspected = inspect_workshop_package(write_package(tmp_path, manifest, backend_files()))
    assert isinstance(inspected.manifest, WorkshopManifestV2)
    assert "backend/main.py" in inspected.member_names

    broken = tmp_path / "broken"
    broken.mkdir()
    with pytest.raises(WorkshopPackageError, match="invalid backend lock"):
        inspect_workshop_package(write_package(broken, manifest, backend_files('lock-version = "9.0"\n')))


def test_backend_package_preserves_project_snapshot_capability(tmp_path: Path) -> None:
    manifest = backend_manifest("fixture.editor", "1.0.0")
    manifest["permissions"] = [{"name": "project.storage", "reason": "Save edits."}]
    manifest["projectSnapshots"] = {"protocol": 1, "schemas": ["editor/v1"]}

    inspected = inspect_workshop_package(write_package(tmp_path, manifest, backend_files()))
    assert isinstance(inspected.manifest, WorkshopManifestV2)
    assert inspected.manifest.backend.entry == "backend/main.py"
    assert inspected.manifest.project_snapshots is not None
    assert inspected.manifest.project_snapshots.schemas == ("editor/v1",)

    manifest["permissions"] = []
    with pytest.raises(ValueError, match="project.storage"):
        WorkshopManifestV2.model_validate(manifest)


@pytest.mark.parametrize(
    "extra",
    [
        {"backend/native.pyd": b"MZ"},
        {"backend/lib.so": b"\x7fELF"},
        {"backend/__pycache__/main.cpython-312.pyc": b"\x00"},
        {"backend/.hidden.py": b"x = 1\n"},
        {"backend/bad.py": b"\xff\xfe"},
    ],
)
def test_package_rejects_binaries_caches_and_non_utf8_backend_files(tmp_path: Path, extra: dict[str, bytes]) -> None:
    manifest = backend_manifest("fixture.ok", "1.0.0")
    with pytest.raises(WorkshopPackageError):
        inspect_workshop_package(write_package(tmp_path, manifest, {**backend_files(), **extra}))


def test_declared_files_must_exist_and_v1_packages_cannot_carry_backends(tmp_path: Path) -> None:
    manifest = backend_manifest("fixture.ok", "1.0.0")
    with pytest.raises(WorkshopPackageError, match="missing file"):
        inspect_workshop_package(write_package(tmp_path, manifest, {"backend/main.py": b"x = 1\n"}))
    v1 = {key: value for key, value in manifest.items() if key != "backend"}
    v1.update({"manifestVersion": 1, "workshopApi": {"min": "1.0.0", "maxExclusive": "2.0.0"}})
    other = tmp_path / "v1"
    other.mkdir()
    with pytest.raises(WorkshopPackageError, match="require manifest v2"):
        inspect_workshop_package(write_package(other, v1, backend_files()))
