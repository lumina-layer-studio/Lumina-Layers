"""Creative Workshop package and runtime limits."""

from __future__ import annotations


# Host Workshop API. 1.1.0 adds optional module backends; frontend-only
# modules keep declaring and negotiating 1.0.0.
WORKSHOP_API_VERSION = "1.1.0"
WORKSHOP_BACKEND_API_VERSION = "1.1.0"
WORKSHOP_MANIFEST_VERSION = 1
WORKSHOP_BACKEND_MANIFEST_VERSION = 2

MAX_PACKAGE_BYTES = 100 * 1024 * 1024
MAX_UNPACKED_BYTES = 300 * 1024 * 1024
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_FILE_COUNT = 2_000
MAX_COMPRESSION_RATIO = 100.0

MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_EDGE = 16_384
MAX_IMAGE_PIXELS = 64_000_000
MAX_MANIFEST_BYTES = 256 * 1024
MAX_ICON_BYTES = 2 * 1024 * 1024
MAX_ICON_PIXELS = 1_048_576
MAX_GALLERY_FILES = 20
MAX_GALLERY_FILE_BYTES = 5 * 1024 * 1024
MAX_GALLERY_PIXELS = 16_000_000
MAX_TEXT_DOCUMENT_BYTES = 1024 * 1024

REQUIRED_PACKAGE_FILES = frozenset(
    {
        "manifest.json",
        "ui/index.html",
        "assets/icon.png",
        "README.md",
        "LICENSE",
    }
)
ALLOWED_PERMISSION_NAMES = frozenset(
    {
        "image.pick",
        "project.storage",
        "color-library.read",
        "handoff.image",
    }
)

# Manifest v2 backend declarations. Backend code is bounded UTF-8 source;
# native binaries may only come from hash-locked wheels, and model weights
# are downloaded and verified separately rather than shipped in packages.
BACKEND_PACKAGE_PREFIX = "backend/"
BACKEND_SOURCE_SUFFIXES = frozenset(
    {".py", ".toml", ".json", ".txt", ".md", ".cfg", ".ini", ".csv"}
)
MAX_BACKEND_FILES = 1_000
MAX_BACKEND_FILE_BYTES = 2 * 1024 * 1024
MAX_BACKEND_TOTAL_BYTES = 32 * 1024 * 1024
MAX_BACKEND_LOCK_BYTES = 2 * 1024 * 1024
MAX_BACKEND_LOCK_PACKAGES = 1_000
MAX_BACKEND_LOCK_WHEELS = 64
MAX_BACKEND_MODELS = 32
MAX_BACKEND_MODEL_BYTES = 16 * 1024 * 1024 * 1024
MAX_BACKEND_VARIANTS = 4
MAX_BACKEND_CAPABILITIES = 8
BACKEND_PYTHON_VERSIONS = frozenset({"3.12"})
BACKEND_PLATFORMS = frozenset(
    {"windows-x86_64", "linux-x86_64", "macos-arm64"}
)
BACKEND_CAPABILITY_NAMES = frozenset(
    {"network", "subprocess", "external-files"}
)
BACKEND_IDLE_TIMEOUT_MIN_SECONDS = 30
BACKEND_IDLE_TIMEOUT_MAX_SECONDS = 3_600

# Backend task transport. Binary inputs/outputs reuse the 64 MiB RPC limit.
MAX_BACKEND_TASK_INPUTS = 8
MAX_BACKEND_TASK_OUTPUTS = 16
MAX_BACKEND_TASK_FILE_BYTES = 64 * 1024 * 1024
MAX_BACKEND_TASK_PARAMS_BYTES = 64 * 1024
MAX_BACKEND_PROTOCOL_MESSAGE_BYTES = 1024 * 1024
BACKEND_PROTOCOL_VERSION = 1
