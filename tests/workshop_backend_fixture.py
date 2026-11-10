"""Synthetic Workshop backend modules for runtime tests.

Builds small local wheels, hash-locked ``pylock.toml`` files that name
canonical HTTPS URLs (the host maps them to a local wheelhouse offline), and
``.lumina-workshop`` packages whose backend is a minimal stdlib-only test
backend speaking control protocol v1. No business algorithm, real model, or
GPU stack is involved.

为运行时测试构造合成模块：本地小 wheel、按哈希锁定的 pylock.toml、以及只用
标准库实现 v1 控制协议的最小测试后端。
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
WHEEL_URL_BASE = "https://files.example.invalid/lumina-workshop-tests/"
SHARED_PAYLOAD_BYTES = 256 * 1024
CONFLICT_PAYLOAD_BYTES = 128 * 1024


@dataclass(frozen=True)
class FixtureWheel:
    name: str
    version: str
    path: Path

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    @property
    def size(self) -> int:
        return self.path.stat().st_size


def _record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def build_wheel(
    directory: Path,
    name: str,
    version: str,
    files: dict[str, bytes],
) -> FixtureWheel:
    """Write one deterministic pure-Python wheel."""

    directory.mkdir(parents=True, exist_ok=True)
    distribution = name.replace("-", "_")
    dist_info = f"{distribution}-{version}.dist-info"
    entries = dict(files)
    entries[f"{dist_info}/METADATA"] = (
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n"
    ).encode()
    entries[f"{dist_info}/WHEEL"] = (
        "Wheel-Version: 1.0\nGenerator: lumina-tests\n"
        "Root-Is-Purelib: true\nTag: py3-none-any\n"
    ).encode()
    record = [f"{path},{_record_hash(data)},{len(data)}" for path, data in entries.items()]
    record.append(f"{dist_info}/RECORD,,")
    entries[f"{dist_info}/RECORD"] = ("\n".join(record) + "\n").encode()
    path = directory / f"{distribution}-{version}-py3-none-any.whl"
    with ZipFile(path, "w") as archive:
        for member, data in entries.items():
            info = ZipInfo(member, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_STORED if member.endswith(".bin") else ZIP_DEFLATED
            archive.writestr(info, data)
    return FixtureWheel(name=name, version=version, path=path)


def _payload(seed: int, size: int) -> bytes:
    return random.Random(seed).randbytes(size)


def build_fixture_wheelhouse(directory: Path) -> dict[str, FixtureWheel]:
    """Build the synthetic dependency set used by backend runtime tests."""

    wheels = {
        "shared": build_wheel(
            directory,
            "lumina-fixture-shared",
            "1.0.0",
            {
                "lumina_fixture_shared/__init__.py": b"VERSION = '1.0.0'\n",
                "lumina_fixture_shared/payload.bin": _payload(11, SHARED_PAYLOAD_BYTES),
            },
        ),
        "conflict-1": build_wheel(
            directory,
            "lumina-fixture-conflict",
            "1.0.0",
            {
                "lumina_fixture_conflict/__init__.py": b"VERSION = '1.0.0'\n",
                "lumina_fixture_conflict/payload.bin": _payload(21, CONFLICT_PAYLOAD_BYTES),
            },
        ),
        "conflict-2": build_wheel(
            directory,
            "lumina-fixture-conflict",
            "2.0.0",
            {
                "lumina_fixture_conflict/__init__.py": b"VERSION = '2.0.0'\n",
                "lumina_fixture_conflict/payload.bin": _payload(22, CONFLICT_PAYLOAD_BYTES),
            },
        ),
        "accel": build_wheel(
            directory,
            "lumina-fixture-accel",
            "1.0.0",
            {
                "lumina_fixture_accel/__init__.py": b"VERSION = '1.0.0'\nDEVICE = 'synthetic-accelerator'\n",
                "lumina_fixture_accel/kernels.bin": _payload(31, 96 * 1024),
            },
        ),
        "accel-broken": build_wheel(
            directory,
            "lumina-fixture-accel",
            "2.0.0",
            {
                "lumina_fixture_accel/__init__.py": (
                    b"raise RuntimeError('synthetic accelerator is unavailable')\n"
                ),
            },
        ),
    }
    return wheels


def lock_text(wheels: list[FixtureWheel], *, include_sizes: bool = True) -> str:
    """Return a PEP 751 lock naming canonical HTTPS URLs for ``wheels``."""

    lines = ['lock-version = "1.0"', 'created-by = "lumina-tests"', 'requires-python = ">=3.12"']
    for wheel in wheels:
        lines.extend(
            [
                "",
                "[[packages]]",
                f'name = "{wheel.name}"',
                f'version = "{wheel.version}"',
                "[[packages.wheels]]",
                f'url = "{WHEEL_URL_BASE}{wheel.path.name}"',
            ]
        )
        if include_sizes:
            lines.append(f"size = {wheel.size}")
        lines.append(f'hashes = {{ sha256 = "{wheel.sha256}" }}')
    return "\n".join(lines) + "\n"


def backend_manifest(
    module_id: str,
    version: str,
    *,
    platforms: tuple[str, ...] = ("windows-x86_64", "linux-x86_64", "macos-arm64"),
    capabilities: list[dict[str, str]] | None = None,
    models: list[dict[str, object]] | None = None,
    variants: list[dict[str, object]] | None = None,
    idle_timeout_seconds: int | None = None,
) -> dict[str, object]:
    backend: dict[str, object] = {
        "entry": "backend/main.py",
        "python": "3.12",
        "lock": "backend/pylock.toml",
        "platforms": list(platforms),
        "capabilities": capabilities if capabilities is not None else [],
        "models": models if models is not None else [],
        "variants": variants if variants is not None else [],
    }
    if idle_timeout_seconds is not None:
        backend["idleTimeoutSeconds"] = idle_timeout_seconds
    return {
        "manifestVersion": 2,
        "id": module_id,
        "version": version,
        "name": {"zh-CN": "后端测试模块", "en-US": "Backend fixture"},
        "description": {
            "zh-CN": "用于验证通用后端运行时",
            "en-US": "Verifies the generic backend runtime",
        },
        "publisher": "Lumina Layer Studio",
        "workshopApi": {"min": "1.1.0", "maxExclusive": "2.0.0"},
        "luminaVersion": {"min": "2.0.0"},
        "entrypoints": {"ui": "ui/index.html"},
        "permissions": [
            {"name": "handoff.image", "reason": "Hand processed images to Lumina."}
        ],
        "backend": backend,
    }


def write_backend_package(
    directory: Path,
    *,
    module_id: str,
    version: str,
    lock: str,
    manifest: dict[str, object] | None = None,
    extra_files: dict[str, bytes] | None = None,
) -> Path:
    """Write one v2 ``.lumina-workshop`` package with the test backend."""

    directory.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes] = {
        "manifest.json": json.dumps(
            manifest or backend_manifest(module_id, version),
            ensure_ascii=False,
        ).encode("utf-8"),
        "ui/index.html": b"<!doctype html><html><head></head><body>backend fixture</body></html>",
        "assets/icon.png": PNG_1X1,
        "README.md": b"# Backend fixture\n",
        "LICENSE": b"MIT\n",
        "backend/main.py": FIXTURE_BACKEND_MAIN.encode("utf-8"),
        "backend/pylock.toml": lock.encode("utf-8"),
    }
    files.update(extra_files or {})
    path = directory / f"{module_id}-{version}.lumina-workshop"
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return path


def encode_png_rgba(width: int, height: int, pixels: bytes) -> bytes:
    """Encode 8-bit RGBA pixels as a minimal non-interlaced PNG."""

    rows = b"".join(
        b"\x00" + pixels[row * width * 4 : (row + 1) * width * 4] for row in range(height)
    )

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def decode_png_rgba(data: bytes) -> tuple[int, int, bytes]:
    """Decode an 8-bit RGBA PNG (filters 0-4) for assertions."""

    from PIL import Image
    import io

    with Image.open(io.BytesIO(data)) as image:
        if image.mode != "RGBA":
            raise AssertionError(f"expected RGBA PNG, got {image.mode}")
        return image.width, image.height, image.tobytes()


# Minimal test backend: stdlib only, protocol v1. Operations cover progress,
# cooperative cancellation, ignored cancellation with a helper process,
# failure, dependency version reporting, and a transparent PNG output.
FIXTURE_BACKEND_MAIN = r'''"""Lumina Workshop runtime test backend (control protocol v1)."""
import hashlib
import json
import os
import queue
import struct
import subprocess
import sys
import threading
import time
import zlib

VARIANT = os.environ.get("LUMINA_WORKSHOP_BACKEND_VARIANT", "cpu")
if VARIANT != "cpu":
    import lumina_fixture_accel  # only present in the acceleration variant

_read_fd, _write_fd = (int(value) for value in os.environ["LUMINA_WORKSHOP_CONTROL_FDS"].split(","))
_reader = os.fdopen(_read_fd, "rb")
_writer = os.fdopen(_write_fd, "wb", buffering=0)
_write_lock = threading.Lock()
_cancelled = set()
_jobs = queue.Queue()


def send(message):
    data = (json.dumps(message) + "\n").encode("utf-8")
    with _write_lock:
        _writer.write(data)


def read_loop():
    for line in _reader:
        message = json.loads(line)
        kind = message.get("type")
        if kind == "run":
            _jobs.put(message)
        elif kind == "cancel":
            _cancelled.add(message["taskId"])
        elif kind == "shutdown":
            os._exit(0)
    os._exit(0)


def decode_png(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    offset, width, height, chunks = 8, 0, 0, []
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            width, height, depth, color = struct.unpack(">IIBB", body[:10])
            assert depth == 8 and color == 6
        elif kind == b"IDAT":
            chunks.append(body)
    raw = zlib.decompress(b"".join(chunks))
    stride = width * 4
    rows, previous, position = [], bytearray(stride), 0
    for _ in range(height):
        kind = raw[position]
        line = bytearray(raw[position + 1:position + 1 + stride])
        position += 1 + stride
        for index in range(stride):
            left = line[index - 4] if index >= 4 else 0
            up = previous[index]
            corner = previous[index - 4] if index >= 4 else 0
            if kind == 1:
                line[index] = (line[index] + left) & 255
            elif kind == 2:
                line[index] = (line[index] + up) & 255
            elif kind == 3:
                line[index] = (line[index] + (left + up) // 2) & 255
            elif kind == 4:
                estimate = left + up - corner
                pa, pb, pc = abs(estimate - left), abs(estimate - up), abs(estimate - corner)
                predictor = left if pa <= pb and pa <= pc else (up if pb <= pc else corner)
                line[index] = (line[index] + predictor) & 255
        rows.append(bytes(line))
        previous = line
    return width, height, b"".join(rows)


def encode_png(width, height, pixels):
    rows = b"".join(b"\x00" + pixels[row * width * 4:(row + 1) * width * 4] for row in range(height))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")


def dependency_versions():
    versions = {}
    for name in ("lumina_fixture_shared", "lumina_fixture_conflict", "lumina_fixture_accel"):
        try:
            versions[name] = __import__(name).VERSION
        except ImportError:
            versions[name] = None
    return versions


def write_json(directory, name, value):
    with open(os.path.join(directory, name), "w", encoding="utf-8") as stream:
        json.dump(value, stream)


def run(message):
    task_id = message["taskId"]
    operation = message["operation"]
    params = message.get("params") or {}
    output_dir = message["outputDir"]
    if operation == "echo":
        write_json(output_dir, "echo.json", {"params": params, "variant": VARIANT})
        send({"type": "result", "taskId": task_id, "outputs": [{"name": "echo", "fileName": "echo.json", "mimeType": "application/json"}]})
    elif operation == "versions":
        write_json(output_dir, "versions.json", {"versions": dependency_versions(), "variant": VARIANT, "models": message.get("models")})
        send({"type": "result", "taskId": task_id, "outputs": [{"name": "versions", "fileName": "versions.json", "mimeType": "application/json"}]})
    elif operation == "slow":
        steps = int(params.get("steps", 20))
        for step in range(steps):
            if task_id in _cancelled:
                send({"type": "cancelled", "taskId": task_id})
                return
            send({"type": "progress", "taskId": task_id, "completed": step, "total": steps, "phase": "working"})
            time.sleep(float(params.get("delay", 0.05)))
        write_json(output_dir, "slow.json", {"steps": steps})
        send({"type": "result", "taskId": task_id, "outputs": [{"name": "result", "fileName": "slow.json", "mimeType": "application/json"}]})
    elif operation == "stubborn":
        helper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        with open(os.path.join(message["workDir"], "helper.pid"), "w", encoding="utf-8") as stream:
            stream.write(str(helper.pid))
        while True:  # ignores cooperative cancellation by design
            time.sleep(0.2)
    elif operation == "fail":
        send({"type": "error", "taskId": task_id, "code": "fixture-failure", "message": "The fixture failed on purpose."})
    elif operation == "noisy":
        print("native-style noise on stdout", flush=True)
        os.write(1, b"raw fd1 noise\n")
        write_json(output_dir, "noisy.json", {"ok": True})
        send({"type": "result", "taskId": task_id, "outputs": [{"name": "result", "fileName": "noisy.json", "mimeType": "application/json"}]})
    elif operation == "inputs":
        received = []
        for item in message["inputs"]:
            with open(item["path"], "rb") as stream:
                digest = hashlib.sha256(stream.read()).hexdigest()
            received.append({"name": item["name"], "fileName": item["fileName"], "path": item["path"], "sha256": digest})
        write_json(output_dir, "inputs.json", received)
        send({"type": "result", "taskId": task_id, "outputs": [{"name": "inputs", "fileName": "inputs.json", "mimeType": "application/json"}]})
    elif operation == "alpha-invert":
        source = next(item for item in message["inputs"] if item["name"] == "image")
        with open(source["path"], "rb") as stream:
            width, height, pixels = decode_png(stream.read())
        inverted = bytearray(pixels)
        for index in range(3, len(inverted), 4):
            inverted[index] = 255 - inverted[index]
        with open(os.path.join(output_dir, "result.png"), "wb") as stream:
            stream.write(encode_png(width, height, bytes(inverted)))
        send({"type": "result", "taskId": task_id, "outputs": [{"name": "image", "fileName": "result.png", "mimeType": "image/png"}]})
    else:
        send({"type": "error", "taskId": task_id, "code": "unknown-operation", "message": "Unknown fixture operation."})


send({"type": "ready", "protocol": 1, "sdk": {"name": "lumina-test-fixture", "version": "1"}})
threading.Thread(target=read_loop, daemon=True).start()
while True:
    run(_jobs.get())
'''
