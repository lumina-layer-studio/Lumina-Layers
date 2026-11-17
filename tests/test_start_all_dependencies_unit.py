"""The source launcher checks the selected services before touching processes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import start_all


def test_backend_probe_uses_the_selected_python(monkeypatch) -> None:
    commands = []
    monkeypatch.setattr(start_all, "PYTHON", "/custom/venv/bin/python")

    def run(command, **kwargs):
        commands.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", run)

    assert start_all._check_dependencies(True, False) is True
    assert commands[0][0] == [start_all.PYTHON, "api_server.py", "--check-dependencies"]
    assert commands[0][1]["cwd"] == start_all.ROOT
    assert commands[0][1]["timeout"] > 0


def test_bad_backend_stops_before_cleanup_or_service_creation(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["start_all.py", "--backend"])
    monkeypatch.setattr(start_all, "_check_dependencies", lambda *_args: False)
    monkeypatch.setattr(start_all, "_clean_startup_ports", lambda *_args, **_kwargs: pytest.fail("Ports touched before dependency check"))
    monkeypatch.setattr(start_all, "build_services", lambda *_args: pytest.fail("Services created before dependency check"))

    with pytest.raises(SystemExit) as exc:
        start_all.main()

    assert exc.value.code == 1


def test_dependency_only_command_exits_without_starting_services(monkeypatch) -> None:
    monkeypatch.setattr(sys, "argv", ["start_all.py", "--backend", "--check-dependencies"])
    monkeypatch.setattr(start_all, "_check_dependencies", lambda *_args: True)
    monkeypatch.setattr(start_all, "build_services", lambda *_args: pytest.fail("Diagnostic started services"))

    start_all.main()


def test_frontend_reports_missing_node_pnpm_and_installation(monkeypatch, tmp_path: Path) -> None:
    from scripts import source_dependencies

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package.json").write_text('{"packageManager":"pnpm@10.33.2"}', encoding="utf-8")
    monkeypatch.setattr(source_dependencies.shutil, "which", lambda _name: None)

    issues = source_dependencies.check_frontend_dependencies(frontend)

    assert any("Node.js" in x for x in issues)
    assert any("pnpm" in x and "10.33.2" in x for x in issues)
    assert any(all(argument in x for argument in ("pnpm", "--dir", "--frozen-lockfile")) for x in issues)


def test_installed_vite_can_run_without_pnpm_on_path(monkeypatch, tmp_path: Path) -> None:
    from scripts import source_dependencies

    frontend = tmp_path / "frontend"
    vite = frontend / "node_modules/vite/bin/vite.js"
    vite.parent.mkdir(parents=True)
    vite.write_text("", encoding="utf-8")
    monkeypatch.setattr(source_dependencies.shutil, "which", lambda name: "/tools/node" if name == "node" else None)
    monkeypatch.setattr(subprocess, "run", lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, "v22.23.2\n", ""))

    assert source_dependencies.check_frontend_dependencies(frontend) == []
