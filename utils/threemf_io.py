"""Publish native 3MF output only after its complete archive has been written."""

from __future__ import annotations

from contextlib import suppress
import os
from pathlib import Path
import shutil
import tempfile
from typing import TYPE_CHECKING

from api.structured_logging import get_logger

if TYPE_CHECKING:
    import neroued_3mf as n3mf

log = get_logger(__name__)


def write_3mf_document(
    output_path: str | Path, document: n3mf.Document, options: n3mf.WriteOptions,
) -> None:
    """Clean interrupted writes and preserve an existing complete destination."""
    import neroued_3mf as n3mf

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent, prefix=".lumina-3mf-", suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    stage = "write"
    try:
        n3mf.write_to_file(str(temporary), document, options)
        stage = "publish"
        os.replace(temporary, target)
    except OSError as exc:
        available_bytes = None
        partial_bytes = None
        with suppress(OSError):
            available_bytes = shutil.disk_usage(target.parent).free
        with suppress(OSError):
            partial_bytes = temporary.stat().st_size
        log.exception(
            "Could not save the 3MF. Check available disk space and write access to the output folder.",
            extra={
                "event": "native_3mf_write_failed", "path": str(target),
                "stage": stage, "error_type": type(exc).__name__, "error_message": str(exc),
                "os_error_number": exc.errno, "available_bytes": available_bytes,
                "partial_bytes": partial_bytes,
            },
        )
        raise
    finally:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
