"""Check a source installation before importing native/application modules.

Bootstrap diagnostics use only the standard library; PEP 440/508 validation
uses packaging from requirements.txt once the environment has been installed.
"""

from __future__ import annotations

import importlib
import json
import os
import platform
import re
import shlex
import shutil
import struct
import subprocess
import sys
import sysconfig
from importlib import metadata
from pathlib import Path
from typing import Any

REQUIREMENTS = Path(__file__).resolve().parents[1] / "requirements.txt"
OPTIONAL_IMAGE_DECODERS = frozenset({"pillow-heif", "rawpy"})
NATIVE_MODULES = (
    "fatcat_metadata", "fatcat_metadata_neroued", "neroued_3mf",
    "lumina_svg_core", "neroued_vectorizer",
)


def _command(arguments: list[str]) -> str:
    if os.name == "nt":
        return "& " + " ".join("'" + argument.replace("'", "''") + "'" for argument in arguments)
    return shlex.join(arguments)


def _supported_python() -> bool:
    return (
        platform.python_implementation() == "CPython"
        and (3, 12) <= sys.version_info[:2] <= (3, 14)
        and struct.calcsize("P") == 8
        and not sysconfig.get_config_var("Py_GIL_DISABLED")
    )


def check_backend_dependencies() -> list[str]:
    """Return missing/incompatible runtime dependencies without loading the app."""
    if not _supported_python():
        return ["Use ordinary 64-bit CPython 3.12–3.14 (recommended: Python 3.12)."]

    try:
        from packaging.requirements import Requirement
    except ImportError:
        return ["packaging: not installed; install requirements.txt to check runtime versions."]

    issues: list[str] = []
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        requirement = line.split("#", 1)[0].strip()
        if not requirement or requirement.startswith("-"):
            continue
        parsed = Requirement(requirement)
        if (
            parsed.name.lower().replace("_", "-") in OPTIONAL_IMAGE_DECODERS
            or parsed.marker is not None and not parsed.marker.evaluate()
        ):
            continue
        name = parsed.name
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            issues.append(f"{name}: not installed" + (f" (required {parsed.specifier})" if parsed.specifier else ""))
            continue
        if installed not in parsed.specifier:
            issues.append(f"{name}: required {parsed.specifier}, installed {installed}")
    if issues:
        return issues

    modules: dict[str, Any] = {}
    for name in NATIVE_MODULES:
        try:
            modules[name] = importlib.import_module(name)
        except Exception as exc:  # Native-extension import is an external-library boundary.
            issues.append(f"{name}: cannot load module ({type(exc).__name__}: {exc})")
    if issues:
        return issues

    adapter = modules["fatcat_metadata_neroued"]
    for name in ("apply_root_model_metadata", "apply_metadata_components"):
        if not callable(getattr(adapter, name, None)):
            issues.append(f"fatcat_metadata_neroued: missing entry point {name}")
    from scripts.fatcat_packaging_contract import validate_fatcat_packaging_contract

    try:
        validate_fatcat_packaging_contract(modules["fatcat_metadata"], modules["neroued_3mf"])
    except (RuntimeError, FileNotFoundError) as exc:
        issues.append(f"fatcat-metadata: {exc}")
    return issues


def report_backend_dependencies() -> bool:
    """Print a concise diagnostic and an interpreter-specific repair command."""
    issues = check_backend_dependencies()
    if not issues:
        return True
    print("Lumina source dependencies are not ready.", file=sys.stderr)
    print(f"Python: {sys.executable}", file=sys.stderr)
    for issue in issues:
        print(f"  - {issue}", file=sys.stderr)
    if not _supported_python():
        print("Create and activate a supported Python virtual environment, then install requirements.txt.", file=sys.stderr)
        return False
    print("Install the requirements in this Python environment:", file=sys.stderr)
    print("  " + _command([
        sys.executable, "-m", "pip", "install", "--upgrade", "--force-reinstall",
        "--no-cache-dir", "-r", str(REQUIREMENTS),
    ]), file=sys.stderr)
    print("Supported Python/platforms and setup: README_CN.md / README.md", file=sys.stderr)
    return False


def check_frontend_dependencies(frontend: Path) -> list[str]:
    """Check the Node/Vite runtime actually used by the source launcher."""
    issues: list[str] = []
    node = shutil.which("node")
    if node is None:
        issues.append("Node.js not found. Install Node.js 24.x, or 22.x >= 22.13.")
    else:
        try:
            result = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10)
            match = re.fullmatch(r"v?(\d+)\.(\d+)\.\d+\s*", result.stdout)
            if result.returncode or not match or (int(match[1]), int(match[2])) < (22, 13):
                issues.append(f"Node.js >= 22.13 required; found {result.stdout.strip() or result.stderr.strip()}.")
        except (OSError, subprocess.TimeoutExpired) as exc:
            issues.append(f"Node.js cannot run: {exc}")

    vite = frontend / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite.is_file():
        if shutil.which("pnpm") is None:
            package_manager = json.loads((frontend / "package.json").read_text(encoding="utf-8"))["packageManager"]
            issues.append(f"pnpm not found. Install {package_manager} to prepare frontend dependencies.")
        issues.append("Frontend dependencies are not installed. Run: " + _command([
            "pnpm", "--dir", str(frontend), "install", "--frozen-lockfile",
        ]))
    elif node is not None and not issues:
        try:
            result = subprocess.run(
                [node, "--input-type=module", "-e", "await import('vite')"],
                cwd=frontend, capture_output=True, text=True, timeout=15,
            )
            if result.returncode:
                issues.append("Vite cannot load: " + result.stderr.strip() + "\nRun: " + _command([
                    "pnpm", "--dir", str(frontend), "install", "--frozen-lockfile",
                ]))
        except (OSError, subprocess.TimeoutExpired) as exc:
            issues.append(f"Vite cannot load: {exc}")
    return issues
