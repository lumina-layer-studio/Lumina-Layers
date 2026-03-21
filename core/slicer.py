# -*- coding: utf-8 -*-
"""
Slicer detection and launch module.

Extracted from ui/layout_new.py — pure business logic, no UI dependencies.
Scans Windows registry for known slicer software and launches them
with subprocess.Popen (non-blocking).
"""

import logging
import os
import platform
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KNOWN_SLICERS: dict[str, dict] = {
    "bambu_studio":  {"match": ["bambu studio"],                          "display_name": "Bambu Studio"},
    "orca_slicer":   {"match": ["orcaslicer"],                            "display_name": "OrcaSlicer"},
    "elegoo_slicer": {"match": ["elegooslicer", "elegoo slicer", "elegoo satellit"], "display_name": "ElegooSlicer"},
    "prusa_slicer":  {"match": ["prusaslicer"],                           "display_name": "PrusaSlicer"},
    "cura":          {"match": ["ultimaker cura", "ultimaker-cura"],      "display_name": "Ultimaker Cura"},
}


@dataclass
class DetectedSlicer:
    """Detected slicer software information."""
    id: str               # Identifier, e.g. "bambu_studio"
    display_name: str      # Display name, e.g. "Bambu Studio"
    exe_path: str          # Absolute path to executable


# ---------------------------------------------------------------------------
# Registry scanning (Windows only)
# ---------------------------------------------------------------------------

def _match_slicer_id(display_name: str) -> tuple[str, str] | None:
    """Match a registry DisplayName against KNOWN_SLICERS.

    Returns (slicer_id, display_name_from_config) or None if no match.
    """
    dn_lower = display_name.lower()
    for sid, info in KNOWN_SLICERS.items():
        for kw in info["match"]:
            if kw in dn_lower:
                # Skip CUDA / NVIDIA entries that accidentally match "cura"
                if sid == "cura" and ("cuda" in dn_lower or "nvidia" in dn_lower):
                    break
                return sid, info["display_name"]
    return None


def _extract_exe_from_icon(icon_value: str) -> str | None:
    """Extract a valid exe path from a registry DisplayIcon value.

    DisplayIcon can be ``"path.exe"`` or ``"path.exe,0"`` and sometimes
    contains a doubled path like ``"F:\\...\\F:\\...\\exe"``.
    """
    icon = icon_value.split(",")[0].strip().strip('"')
    # Handle doubled path: try progressively shorter suffixes
    parts = icon.split("\\")
    for idx in range(1, len(parts)):
        candidate = "\\".join(parts[idx:])
        if os.path.isfile(candidate):
            return candidate
    if os.path.isfile(icon):
        return icon
    return None


def _find_exe_in_directory(directory: str) -> str | None:
    """Find the first non-uninstaller .exe in *directory*."""
    if not os.path.isdir(directory):
        return None
    for fname in os.listdir(directory):
        if fname.lower().endswith(".exe") and "unins" not in fname.lower():
            candidate = os.path.join(directory, fname)
            if os.path.isfile(candidate):
                return candidate
    return None


def scan_registry() -> list[DetectedSlicer]:
    """Scan Windows registry Uninstall keys for known slicer executables.

    On non-Windows platforms this returns an empty list immediately,
    avoiding any ``winreg`` import.
    """
    if platform.system() != "Windows":
        return []

    # Deferred import — only available on Windows
    import winreg  # noqa: F811

    found: dict[str, DetectedSlicer] = {}
    reg_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    for hive, base_path in reg_paths:
        try:
            key = winreg.OpenKey(hive, base_path)
        except OSError:
            continue

        i = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(key, i)
                i += 1
            except OSError:
                break

            try:
                subkey = winreg.OpenKey(key, subkey_name)
                try:
                    display_name: str = winreg.QueryValueEx(subkey, "DisplayName")[0]
                except OSError:
                    subkey.Close()
                    continue

                match = _match_slicer_id(display_name)
                if match is None or match[0] in found:
                    subkey.Close()
                    continue

                sid, config_display_name = match

                # --- resolve exe path ---
                exe_path: str | None = None

                # 1) Try DisplayIcon (most reliable)
                try:
                    icon_val: str = winreg.QueryValueEx(subkey, "DisplayIcon")[0]
                    exe_path = _extract_exe_from_icon(icon_val)
                except OSError:
                    pass

                # 2) Fallback: InstallLocation
                if exe_path is None:
                    try:
                        install_loc: str = winreg.QueryValueEx(subkey, "InstallLocation")[0]
                        exe_path = _find_exe_in_directory(install_loc)
                    except OSError:
                        pass

                subkey.Close()

                if exe_path and exe_path.lower().endswith(".exe") and os.path.isfile(exe_path):
                    found[sid] = DetectedSlicer(
                        id=sid,
                        display_name=config_display_name,
                        exe_path=exe_path,
                    )
                    logger.info("[SLICER] Registry: %s -> %s", config_display_name, exe_path)
            except OSError:
                pass

        key.Close()

    return list(found.values())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_installed_slicers() -> list[DetectedSlicer]:
    """Detect slicer software installed on the system.

    Currently delegates to :func:`scan_registry`.  Future versions may
    add additional discovery strategies (e.g. PATH scanning, macOS
    ``/Applications`` lookup).
    """
    slicers = scan_registry()
    # Filter out entries whose exe no longer exists (defensive)
    slicers = [s for s in slicers if os.path.isfile(s.exe_path)]
    if not slicers:
        logger.info("[SLICER] No slicers detected")
    return slicers


def launch_slicer(
    slicer_id: str,
    file_path: str,
    known_slicers: list[DetectedSlicer],
) -> tuple[bool, str]:
    """Launch *slicer_id* to open *file_path*.

    Parameters
    ----------
    slicer_id:
        Identifier such as ``"bambu_studio"``.
    file_path:
        Absolute path to the file (typically ``.3mf``) to open.
    known_slicers:
        List of previously detected slicers (from :func:`detect_installed_slicers`).

    Returns
    -------
    tuple[bool, str]
        ``(success, message)`` — *success* is ``True`` when the process
        was spawned successfully.
    """
    if not os.path.isfile(file_path):
        return False, f"File does not exist: {file_path}"

    target: DetectedSlicer | None = None
    for s in known_slicers:
        if s.id == slicer_id:
            target = s
            break

    if target is None:
        return False, f"Slicer not found: {slicer_id}"

    try:
        subprocess.Popen([target.exe_path, file_path])
        return True, f"Opened in {target.display_name}"
    except Exception as exc:
        return False, f"Failed to launch {target.display_name}: {exc}"
