"""Contracts for the native 3MF writer dependency and frozen packaging."""

from __future__ import annotations

from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

import pytest
from packaging.requirements import Requirement

from scripts.fatcat_packaging_contract import (
    FATCAT_DISTRIBUTION, FATCAT_MODULE, FATCAT_VERSION,
    FATCAT_WRITER_DISTRIBUTION, FATCAT_WRITER_VERSION,
    FATCAT_REQUIRED_ENTRY_POINTS, FATCAT_REQUIRED_DATA_FILES,
    FATCAT_REPOSITORY, FATCAT_SOURCE_COMMIT, FATCAT_WRITER_REPOSITORY,
    FATCAT_WRITER_SOURCE_COMMIT,
)


ROOT = Path(__file__).resolve().parents[1]


def _neroued_requirement() -> Requirement:
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if line.strip().lower().startswith("neroued-3mf"):
            return Requirement(line.strip())
    raise AssertionError("requirements.txt does not declare neroued-3mf")


def test_neroued_requirement_selects_official_production_path_release() -> None:
    requirement = _neroued_requirement()

    assert str(requirement.specifier) == f"=={FATCAT_WRITER_VERSION}"
    assert requirement.marker is None
    assert "0.3.99" not in requirement.specifier
    assert "0.6.0" not in requirement.specifier


def test_native_requirement_pins_the_public_sdk_without_a_python_marker() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    requirement = next(
        Requirement(line.strip())
        for line in requirements.splitlines()
        if line.strip().startswith(FATCAT_DISTRIBUTION)
    )

    assert str(requirement.specifier) == f"=={FATCAT_VERSION}"
    assert requirement.marker is None
    assert requirement.url is None
    assert FATCAT_REPOSITORY in requirements
    assert FATCAT_SOURCE_COMMIT in requirements


def test_fatcat_build_contract_uses_public_root_and_writer_source() -> None:
    build_script = (ROOT / "scripts" / "build_3mf_native_wheels.py").read_text(
        encoding="utf-8",
    )

    assert FATCAT_REPOSITORY == "https://github.com/MOVIBALE/fatcat-metadata"
    assert FATCAT_VERSION == "0.1.6"
    assert len(FATCAT_SOURCE_COMMIT) == 40
    assert len(FATCAT_WRITER_SOURCE_COMMIT) == 40
    assert FATCAT_WRITER_VERSION == "0.4.2"
    assert FATCAT_WRITER_REPOSITORY == "https://github.com/Neroued/neroued_3mf.git"
    assert 'fatcat_root / "pyproject.toml"' in build_script
    assert '"source_commit": writer_commit' in build_script
    assert '"project_root": "."' in build_script
    assert 'fatcat_root / "cpp"' not in build_script


@pytest.mark.parametrize("missing_target", ["bambu-studio-02.09.01.70.json", "orca-slicer-2.4.2.json"])
def test_shared_fatcat_packaging_contract_rejects_missing_target_data(
    monkeypatch,
    tmp_path: Path,
    missing_target: str,
) -> None:
    from scripts.fatcat_packaging_contract import validate_fatcat_packaging_contract

    module_path = tmp_path / "site-packages" / f"{FATCAT_MODULE}.py"
    data_root = module_path.parent / "fatcat_metadata_data"
    for relative_path in FATCAT_REQUIRED_DATA_FILES:
        path = data_root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    (data_root / "translations" / "targets" / missing_target).unlink()
    fatcat = SimpleNamespace(
        __file__=str(module_path),
        **{name: lambda *_args: None for name in FATCAT_REQUIRED_ENTRY_POINTS},
    )
    writer = SimpleNamespace()
    versions = {
        FATCAT_DISTRIBUTION: FATCAT_VERSION,
        FATCAT_WRITER_DISTRIBUTION: FATCAT_WRITER_VERSION,
    }
    monkeypatch.setattr(metadata, "version", versions.__getitem__)

    with pytest.raises(FileNotFoundError, match=missing_target):
        validate_fatcat_packaging_contract(fatcat, writer)


def test_installed_neroued_exposes_explicit_zero_copy_mesh_view() -> None:
    import neroued_3mf

    assert metadata.version("neroued-3mf") == FATCAT_WRITER_VERSION
    assert callable(
        getattr(
            neroued_3mf.DocumentBuilder(),
            "add_mesh_object_zero_copy",
            None,
        )
    )


def test_ci_native_wheel_bootstrap_uses_the_same_pinned_inputs() -> None:
    action = (
        ROOT / ".github" / "actions" / "prepare-3mf-native-wheels" / "action.yml"
    ).read_text(encoding="utf-8")

    assert "--get FATCAT_WRITER_SOURCE_COMMIT" in action
    assert "--get FATCAT_WRITER_REPOSITORY" in action
    assert "--install" in action
    assert "scripts/build_3mf_native_wheels.py" in action
    assert "--output-dir \"$GITHUB_WORKSPACE/wheelhouse/3mf\"" in action


def test_ci_pins_the_fatcat_0100_source_revision() -> None:
    action = (
        ROOT / ".github" / "actions" / "prepare-3mf-native-wheels" / "action.yml"
    ).read_text(encoding="utf-8")
    assert "scripts/fatcat_packaging_contract.py" in action
    assert "--get FATCAT_SOURCE_COMMIT" in action
    assert "--get FATCAT_WRITER_SOURCE_COMMIT" in action
    assert f"{FATCAT_DISTRIBUTION}=={FATCAT_VERSION}" in (
        ROOT / "requirements.txt"
    ).read_text(encoding="utf-8")


def test_public_fatcat_source_builds_without_a_token() -> None:
    action = (
        ROOT / ".github" / "actions" / "prepare-3mf-native-wheels" / "action.yml"
    ).read_text(encoding="utf-8")
    build_script = (ROOT / "scripts" / "build_3mf_native_wheels.py").read_text(
        encoding="utf-8",
    )

    assert 'git clone --no-checkout "$FATCAT_REPOSITORY"' in action
    assert 'git clone --no-checkout "$NEROUED_REPOSITORY"' in action
    assert "fatcat-token" not in action
    assert "FATCAT_TOKEN" not in action
    assert "http.extraheader" not in action
    assert "fatcat_root / \"pyproject.toml\"" in build_script

    for workflow in (
        ROOT / ".github" / "workflows" / "layered-mesh-geometry.yml",
        ROOT / ".github" / "workflows" / "native-svg-core.yml",
    ):
        text = workflow.read_text(encoding="utf-8")
        assert "FATCAT_REPO_TOKEN" not in text
        assert "fatcat-token:" not in text
        assert "--secret id=fatcat_token" not in text
