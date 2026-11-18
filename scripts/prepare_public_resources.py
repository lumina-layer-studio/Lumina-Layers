#!/usr/bin/env python3
"""Prepare the pinned public material/LUT pair for source or desktop use."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "assets/resource-release.json"
_PREFIX = "https://github.com/lumina-layer-studio/Lumina-materials/releases/download/"
_MAX_BYTES = 256 * 1024 * 1024


class _PublicReleaseRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        parsed = urlsplit(newurl)
        if parsed.scheme != "https" or parsed.hostname not in {
            "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
        } or parsed.username or parsed.password:
            raise ValueError("Unexpected public resource download redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def load_release(path: Path) -> dict[str, Any]:
    if path.stat().st_size > 512 * 1024:
        raise ValueError("Resource release manifest is too large")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("kind") != "lumina_resource_release" or payload.get("schema_version") != 1:
        raise ValueError("Unsupported public resource release")
    if not isinstance(payload.get("dataset_version"), str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,80}", payload["dataset_version"]):
        raise ValueError("Invalid resource dataset version")
    for kind in ("materials", "luts"):
        artifact = payload.get("artifacts", {}).get(kind)
        if not isinstance(artifact, dict) or artifact.get("path") != f"lumina-{kind}-seed.zip":
            raise ValueError("Invalid public resource artifact filename")
        if type(artifact.get("bytes")) is not int or not 0 < artifact["bytes"] <= _MAX_BYTES:
            raise ValueError("Invalid public resource size")
        if not re.fullmatch(r"[a-f0-9]{64}", str(artifact.get("sha256", ""))):
            raise ValueError("Invalid public resource sha256")
        url = artifact.get("download_url", "")
        expected = f"{_PREFIX}v{payload['dataset_version']}/{artifact['path']}"
        if url != expected:
            raise ValueError("Public resources must reference their fixed dataset release")
    return payload


def obtain_artifact(
    artifact: dict[str, Any], destination: Path, *, source_dir: Path | None = None,
    source_path: Path | None = None,
) -> None:
    """Verify exact locked bytes before replacing any runtime resource."""
    if source_path is not None or source_dir is not None:
        source = source_path if source_path is not None else source_dir / artifact["path"]
        if source.stat().st_size != artifact["bytes"]:
            raise ValueError(f"Public resource size mismatch: {artifact['path']}")
        payload = source.read_bytes()
    else:
        opener = build_opener(_PublicReleaseRedirect())
        with opener.open(artifact["download_url"], timeout=45) as response:
            payload = response.read(artifact["bytes"] + 1)
    if len(payload) != artifact["bytes"] or hashlib.sha256(payload).hexdigest() != artifact["sha256"]:
        raise ValueError(f"Public resource size or sha256 mismatch: {artifact['path']}")
    destination.write_bytes(payload)


def prepare_resources(
    lock_path: Path, output: Path, *, source_dir: Path | None = None,
    source_paths: dict[str, Path] | None = None,
) -> dict[str, Any]:
    release = load_release(lock_path)
    if output.is_symlink():
        raise ValueError("Resource output directory cannot be a symlink")
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".public-resources-", dir=output) as temporary:
        staged = Path(temporary)
        for kind in ("materials", "luts"):
            artifact = release["artifacts"][kind]
            obtain_artifact(artifact, staged / artifact["path"], source_dir=source_dir,
                            source_path=(source_paths or {}).get(kind))
        # Both packages are complete and checked before either is activated.
        for kind in ("materials", "luts"):
            target = output / kind
            if target.is_symlink():
                raise ValueError("Resource target directory cannot be a symlink")
        for kind in ("materials", "luts"):
            target = output / kind
            target.mkdir(exist_ok=True)
            name = release["artifacts"][kind]["path"]
            (staged / name).replace(target / name)
        descriptor = staged / "resource-release.json"
        descriptor.write_text(json.dumps(release, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        descriptor.replace(output / "resource-release.json")
    return release


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=LOCK_PATH)
    parser.add_argument("--source-dir", type=Path, help="Use an already downloaded release directory without networking")
    parser.add_argument("--output", type=Path, default=ROOT / "resources")
    parser.add_argument("--materials-seed", type=Path, help="Frozen native-build material input")
    parser.add_argument("--luts-seed", type=Path, help="Frozen native-build LUT input")
    args = parser.parse_args()
    if bool(args.materials_seed) != bool(args.luts_seed) or (args.source_dir and args.materials_seed):
        parser.error("Provide a release directory or both frozen seed inputs")
    paths = {"materials": args.materials_seed, "luts": args.luts_seed} if args.materials_seed else None
    release = prepare_resources(args.release, args.output, source_dir=args.source_dir, source_paths=paths)
    print(f"Prepared public resources {release['dataset_version']} in {args.output}")


if __name__ == "__main__":
    main()
