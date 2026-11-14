"""Source startup reports actionable failures before importing the application."""

from __future__ import annotations

import importlib
import sys
from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from scripts import source_dependencies
    from scripts.fatcat_packaging_contract import (
        FATCAT_REQUIRED_DATA_FILES, FATCAT_REQUIRED_ENTRY_POINTS,
    )

    requirements = tmp_path / "requirements.txt"
    requirements.write_text(
        "--only-binary=fatcat-metadata,neroued-3mf,lumina-svg-core,neroued-vectorizer\n"
        "fastapi\nuvicorn\nnumpy\nPillow\npillow-heif>=0.18.0\nrawpy>=0.21.0\n"
        "fatcat-metadata==0.1.5\nneroued-3mf==0.4.2\n"
        "lumina-svg-core==0.3.4\nneroued-vectorizer>=0.1.1\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(source_dependencies, "REQUIREMENTS", requirements)
    versions = {
        "fastapi": "0.115.0", "uvicorn": "0.35.0", "numpy": "2.2.0",
        "Pillow": "11.0.0", "fatcat-metadata": "0.1.5",
        "neroued-3mf": "0.4.2", "lumina-svg-core": "0.3.4",
        "neroued-vectorizer": "0.1.1",
    }

    def version(name: str) -> str:
        if name not in versions:
            raise metadata.PackageNotFoundError(name)
        return versions[name]

    monkeypatch.setattr(metadata, "version", version)
    fatcat = SimpleNamespace(
        __file__=str(tmp_path / "fatcat_metadata.so"),
        **{name: lambda *_args: None for name in FATCAT_REQUIRED_ENTRY_POINTS},
    )
    for relative in FATCAT_REQUIRED_DATA_FILES:
        path = tmp_path / "fatcat_metadata_data" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
    modules = {
        "fatcat_metadata": fatcat,
        "fatcat_metadata_neroued": SimpleNamespace(
            apply_root_model_metadata=lambda *_args: None,
            apply_metadata_components=lambda *_args: None,
        ),
        "neroued_3mf": SimpleNamespace(),
        "lumina_svg_core": SimpleNamespace(),
        "neroued_vectorizer": SimpleNamespace(),
    }
    original_import = importlib.import_module

    def import_module(name: str):
        if name in modules:
            value = modules[name]
            if isinstance(value, Exception):
                raise value
            return value
        return original_import(name)

    monkeypatch.setattr(importlib, "import_module", import_module)
    return source_dependencies, versions, modules


def test_optional_image_decoders_do_not_block_source_startup(runtime) -> None:
    checker, _, _ = runtime

    assert checker.check_backend_dependencies() == []


def test_missing_package_reports_the_distribution(runtime) -> None:
    checker, versions, _ = runtime
    del versions["uvicorn"]

    issues = checker.check_backend_dependencies()

    assert any("uvicorn" in issue and "not installed" in issue for issue in issues)


def test_bootstrap_can_explain_an_environment_without_packaging(runtime, monkeypatch, capsys) -> None:
    checker, _, _ = runtime
    monkeypatch.setitem(sys.modules, "packaging.requirements", None)

    assert checker.report_backend_dependencies() is False
    error = capsys.readouterr().err
    assert "packaging" in error and "requirements.txt" in error
    assert "Traceback" not in error


def test_environment_markers_do_not_require_inapplicable_packages(runtime) -> None:
    checker, _, _ = runtime
    with checker.REQUIREMENTS.open("a", encoding="utf-8") as handle:
        handle.write('not-applicable; python_version < "3.0"\n')

    assert checker.check_backend_dependencies() == []


def test_old_fatcat_reports_required_and_installed_versions(runtime) -> None:
    checker, versions, _ = runtime
    versions["fatcat-metadata"] = "0.1.2"

    issues = checker.check_backend_dependencies()

    assert any("fatcat-metadata" in x and "0.1.5" in x and "0.1.2" in x for x in issues)


@pytest.mark.parametrize(
    "requirement, distribution, installed",
    [
        ("neroued-vectorizer>=0.1.1", "neroued-vectorizer", "0.0.1"),
        ("shapely>=2.1.0", "shapely", "1.8.5"),
        ("cryptography>=44.0.0,<46.0.0", "cryptography", "47.0.0"),
    ],
)
def test_minimum_and_upper_version_constraints_are_checked(runtime, requirement, distribution, installed) -> None:
    checker, versions, _ = runtime
    with checker.REQUIREMENTS.open("a", encoding="utf-8") as handle:
        handle.write(requirement + "\n")
    versions[distribution] = installed

    issues = checker.check_backend_dependencies()

    assert any(distribution in x and installed in x for x in issues)


def test_windows_repair_commands_work_in_powershell(runtime, monkeypatch) -> None:
    checker, _, _ = runtime
    monkeypatch.setattr(checker, "os", SimpleNamespace(name="nt"))

    command = checker._command(["C:\\Users\\O'Brien Name\\python.exe", "-m", "pip", "install"])

    assert command == "& 'C:\\Users\\O''Brien Name\\python.exe' '-m' 'pip' 'install'"


@pytest.mark.parametrize(
    "module, failure",
    [
        ("fatcat_metadata_neroued", ModuleNotFoundError("No module named 'fatcat_metadata_neroued'")),
        ("lumina_svg_core", ImportError("incompatible architecture")),
        ("neroued_3mf", OSError("libstdc++.so.6: version GLIBCXX not found")),
        ("neroued_vectorizer", AttributeError("Native module was built for an incompatible NumPy ABI")),
    ],
)
def test_installed_but_unloadable_native_modules_are_actionable(runtime, module, failure) -> None:
    checker, _, modules = runtime
    modules[module] = failure

    issues = checker.check_backend_dependencies()

    assert any(module in issue and str(failure) in issue for issue in issues)


def test_same_version_missing_native_entry_point_is_rejected(runtime) -> None:
    checker, _, modules = runtime
    delattr(modules["fatcat_metadata"], "native_project_source")

    assert any("native_project_source" in x for x in checker.check_backend_dependencies())


def test_incomplete_adapter_is_rejected(runtime) -> None:
    checker, _, modules = runtime
    delattr(modules["fatcat_metadata_neroued"], "apply_metadata_components")

    assert any("apply_metadata_components" in x for x in checker.check_backend_dependencies())


def test_repair_command_targets_the_actual_python_and_requirements(runtime, monkeypatch, capsys) -> None:
    checker, versions, _ = runtime
    versions["fatcat-metadata"] = "0.1.2"
    monkeypatch.setattr(sys, "executable", "/tmp/custom environment/bin/python")

    assert checker.report_backend_dependencies() is False

    error = capsys.readouterr().err
    assert sys.executable in error
    assert str(checker.REQUIREMENTS) in error
    assert all(argument in error for argument in ("-m", "pip", "install"))
    assert "--force-reinstall" in error
    assert "Traceback" not in error


def test_unsupported_python_is_reported_before_native_import(runtime, monkeypatch) -> None:
    checker, _, modules = runtime
    monkeypatch.setattr(sys, "version_info", (3, 11, 9))
    modules["fatcat_metadata"] = AssertionError("Must not load native modules on unsupported Python")

    issues = checker.check_backend_dependencies()

    assert any("Python" in x and "3.12" in x and "3.14" in x for x in issues)


def test_api_dependency_diagnostic_does_not_start_or_import_the_app(monkeypatch) -> None:
    import api_server
    from scripts import source_dependencies

    monkeypatch.setattr(source_dependencies, "report_backend_dependencies", lambda: True)
    monkeypatch.setattr(api_server, "_run_server", lambda _env: pytest.fail("Server started during diagnostic"))

    assert api_server.main(["--check-dependencies"]) == 0


def test_api_refuses_bad_dependencies_before_starting_server(monkeypatch) -> None:
    import api_server
    from scripts import source_dependencies

    monkeypatch.setattr(source_dependencies, "report_backend_dependencies", lambda: False)
    monkeypatch.setattr(api_server, "_run_server", lambda _env: pytest.fail("Bad environment started the server"))

    assert api_server.main([]) == 1


def test_frozen_runtime_keeps_its_existing_packaged_checks(monkeypatch) -> None:
    import api_server
    from scripts import source_dependencies

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(source_dependencies, "report_backend_dependencies", lambda: pytest.fail("Source requirements checked in frozen runtime"))
    calls = []
    monkeypatch.setattr(api_server, "_run_server", lambda env: calls.append(env))

    assert api_server.main([]) == 0
    assert len(calls) == 1
