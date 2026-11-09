"""LUMINA_OUTPUT_DIR moves generated files out of the application directory."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _config_dirs(env_override: dict[str, str]) -> dict[str, str]:
    env = {**os.environ, **env_override}
    code = (
        "import json, config;"
        "print(json.dumps({'output': config.OUTPUT_DIR, 'temp': config.TEMP_DIR, 'models': config.MODELS_DIR}))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, env=env,
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_output_dir_override_relocates_output_temp_and_models(tmp_path: Path) -> None:
    target = tmp_path / "plus-output"
    dirs = _config_dirs({"LUMINA_OUTPUT_DIR": str(target)})
    assert dirs["output"] == str(target)
    assert dirs["temp"] == str(target / "temp")
    assert dirs["models"] == str(target / "models")
    assert (target / "temp").is_dir() and (target / "models").is_dir()


def test_output_dir_defaults_to_repository_output() -> None:
    env = {"LUMINA_OUTPUT_DIR": ""}
    dirs = _config_dirs(env)
    assert dirs["output"] == str(REPO_ROOT / "output")


def test_relative_output_dir_is_rejected() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", "import config"], cwd=REPO_ROOT,
        env={**os.environ, "LUMINA_OUTPUT_DIR": "relative/output"},
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode != 0
    assert "LUMINA_OUTPUT_DIR must be an absolute directory path" in completed.stderr
