"""Workshop backend control protocol v1 (newline-delimited JSON).

The host and a module backend exchange bounded JSON objects, one per line,
over two dedicated inherited pipes. Process stdout/stderr are diagnostics
only, so native-library output can never corrupt the control channel.
Images and other bytes travel as files in the task directory.

宿主与模块后端通过两条专用继承管道交换有界 JSON（每行一条）。进程标准输出与
错误输出只作诊断，原生库输出不会污染控制通道；图像等数据通过任务目录传递。

Backend → host: ``ready``, ``progress``, ``result``, ``error``, ``cancelled``.
Host → backend: ``run``, ``cancel``, ``shutdown``.
"""

from __future__ import annotations

import json
from typing import Any

from ..constants import (
    BACKEND_PROTOCOL_VERSION,
    MAX_BACKEND_PROTOCOL_MESSAGE_BYTES,
)


BACKEND_MESSAGE_TYPES = frozenset({"ready", "progress", "result", "error", "cancelled"})
HOST_MESSAGE_TYPES = frozenset({"run", "cancel", "shutdown"})
CONTROL_ENVIRONMENT_VARIABLE = "LUMINA_WORKSHOP_CONTROL"
PROTOCOL_VERSION = BACKEND_PROTOCOL_VERSION


class ProtocolError(ValueError):
    """A backend sent a message outside the bounded protocol."""


def encode_message(message: dict[str, Any]) -> bytes:
    if message.get("type") not in HOST_MESSAGE_TYPES | BACKEND_MESSAGE_TYPES:
        raise ProtocolError("unknown message type")
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) + 1 > MAX_BACKEND_PROTOCOL_MESSAGE_BYTES:
        raise ProtocolError("message exceeds protocol size limit")
    return payload + b"\n"


def decode_backend_message(line: bytes) -> dict[str, Any]:
    if len(line) > MAX_BACKEND_PROTOCOL_MESSAGE_BYTES:
        raise ProtocolError("message exceeds protocol size limit")
    try:
        value = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("message is not UTF-8 JSON") from exc
    if not isinstance(value, dict) or value.get("type") not in BACKEND_MESSAGE_TYPES:
        raise ProtocolError("message type is not a backend message")
    if value["type"] != "ready" and not isinstance(value.get("taskId"), str):
        raise ProtocolError("task message requires taskId")
    return value


# Started as ``python -I -X utf8 -X pycache_prefix=<cache> <this file>
# <backend-dir> <entry>``. ``-I`` ignores PYTHON* variables and the user site
# and keeps the script directory off ``sys.path``. The bootstrap converts the
# inherited control handles into private file descriptors, marks them
# non-inheritable so helper processes cannot hold the channel open, and runs
# the module entry as ``__main__``. Modules use the public Python SDK, which
# reads ``LUMINA_WORKSHOP_CONTROL_FDS``.
BOOTSTRAP_SOURCE = '''"""Lumina Workshop backend bootstrap (host protocol v1)."""
import os
import runpy
import sys

_read_ref, _write_ref = os.environ.pop("LUMINA_WORKSHOP_CONTROL").split(",")
if os.name == "nt":
    import msvcrt
    _read_fd = msvcrt.open_osfhandle(int(_read_ref), os.O_RDONLY)
    _write_fd = msvcrt.open_osfhandle(int(_write_ref), os.O_WRONLY)
else:
    _read_fd, _write_fd = int(_read_ref), int(_write_ref)
os.set_inheritable(_read_fd, False)
os.set_inheritable(_write_fd, False)
os.environ["LUMINA_WORKSHOP_CONTROL_FDS"] = "%d,%d" % (_read_fd, _write_fd)
_backend_dir, _entry = sys.argv[1], sys.argv[2]
sys.path.insert(0, _backend_dir)
sys.argv = [_entry]
runpy.run_path(_entry, run_name="__main__")
'''
