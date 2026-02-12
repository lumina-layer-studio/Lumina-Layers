"""Helpers for loading static UI asset text files."""

from pathlib import Path


_ASSET_ROOT = Path(__file__).resolve().parent / "assets"


def load_asset_text(*parts: str) -> str:
    """Load a UTF-8 text asset from ui/assets."""
    return (_ASSET_ROOT / Path(*parts)).read_text(encoding="utf-8")
