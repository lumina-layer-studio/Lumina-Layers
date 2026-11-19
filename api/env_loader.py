"""Lightweight ``.env.local`` loader for development entry points.

为开发入口提供轻量的 ``.env.local`` 加载器。

The Lumina backend reads configuration via ``os.environ`` directly;
this module provides a tiny self-contained parser so operators can
keep machine-local settings in a gitignored ``.env.local``
file without pulling in an extra runtime dependency such as
``python-dotenv``.

Lumina 后端直接通过 ``os.environ`` 读取配置；本模块提供一个零依赖
的小解析器，让运维可以把本机专用配置放在被 gitignore 的
``.env.local`` 文件中，无需引入 ``python-dotenv`` 之类的运行时依赖。

Usage:
    用法::

        from api.env_loader import load_env_local
        load_env_local()  # before importing api.app

The loader is intentionally silent on success and on missing files;
malformed lines are skipped without raising. Existing process
environment variables always win, so a shell-exported value cannot
be silently overridden by ``.env.local``.

加载器在成功与文件缺失时都保持静默；错误格式的行会被直接跳过且不抛
异常。已经存在于进程环境的变量始终优先，shell 导出的值不会被
``.env.local`` 静默覆盖。
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CATALOG_URL_KEYS = {"LUMINA_MATERIAL_REGISTRY_URL", "LUMINA_LUT_REGISTRY_URL"}


def _strip_inline_quotes(value: str) -> str:
    """Strip a single matched pair of surrounding quotes from ``value``.

    去掉 ``value`` 两端成对的引号（仅一层）。

    Args:
        value: Raw value string after ``KEY=`` split, with surrounding
            whitespace already trimmed.
            从 ``KEY=`` 切分后得到的原始值，外侧空白已剥离。

    Returns:
        str: ``value`` with one matching pair of single or double
            quotes removed when both ends agree, otherwise unchanged.
            两端引号匹配时去掉成对的单/双引号；否则原样返回。
    """

    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _resolve_path(path: str | Path | None) -> Path:
    """Resolve the ``.env.local`` path used for loading.

    解析用于加载的 ``.env.local`` 路径。

    Resolution order:
        解析顺序：

        1. Explicit ``path`` argument (any callable site override).
           显式 ``path`` 参数（调用方覆盖）。
        2. ``LUMINA_ENV_LOCAL_PATH`` environment variable.
           ``LUMINA_ENV_LOCAL_PATH`` 环境变量。
        3. ``<repo>/.env.local`` (default).
           ``<repo>/.env.local`` （默认）。

    Args:
        path: Optional override; ``None`` falls through to the env var
            and finally to the repo-root default.
            可选覆盖；为 ``None`` 时按上述顺序回落。

    Returns:
        Path: Absolute path candidate. The file may not exist.
            候选绝对路径，文件不一定存在。
    """

    if path is not None:
        return Path(path).resolve()
    override = os.environ.get("LUMINA_ENV_LOCAL_PATH")
    if override:
        return Path(override).resolve()
    return (_REPO_ROOT / ".env.local").resolve()


def load_env_local(
    path: str | Path | None = None,
    *,
    override_existing: bool = False,
) -> dict[str, str]:
    """Populate ``os.environ`` with values from a ``.env.local`` file.

    用 ``.env.local`` 文件中的值填充 ``os.environ``。

    The file format is the well-known ``KEY=VALUE`` shape: blank lines
    and lines starting with ``#`` are skipped, the first ``=`` on a
    line splits key from value, surrounding whitespace is trimmed, and
    one matching pair of single or double quotes is stripped from the
    value. Lines that do not contain ``=`` or that have an empty key
    are silently ignored so a half-edited file cannot crash the
    server entry point.

    文件格式为常见的 ``KEY=VALUE``：空行和以 ``#`` 开头的行被跳过；
    每行的第一个 ``=`` 分隔键与值；外侧空白会被去除；值两端成对的
    单/双引号会被剥离一层。不含 ``=`` 或键为空的行会被静默忽略，避免
    编辑到一半的文件让服务启动崩溃。

    Args:
        path: Optional explicit ``.env.local`` path. Defaults to the
            repo-root file or ``LUMINA_ENV_LOCAL_PATH`` if set.
            可选的 ``.env.local`` 显式路径。默认按
            ``LUMINA_ENV_LOCAL_PATH``-> 仓库根 ``.env.local`` 的顺序解析。
        override_existing: When ``True``, values from the file replace
            existing ``os.environ`` entries. Defaults to ``False`` so
            shell-exported variables always win.
            为 ``True`` 时文件中的值会覆盖已存在的 ``os.environ`` 项；
            默认 ``False``，shell 导出的变量始终优先。

    Returns:
        dict[str, str]: Mapping of keys parsed from the file (regardless
            of whether they were applied to ``os.environ``). Empty dict
            when the file is absent or unreadable.
            从文件解析出的键值映射（不论是否真的写入 ``os.environ``）。
            文件缺失或不可读时返回空字典。
    """

    target = _resolve_path(path)
    if not target.is_file():
        return {}

    parsed: dict[str, str] = {}
    try:
        text = target.read_text(encoding="utf-8")
    except OSError:
        return {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        value = value.strip()
        # Older sample files left these URLs unfilled. Keep the built-in catalog
        # in that case. Operators can still disable it with a quoted empty URL.
        if key in _CATALOG_URL_KEYS and not value:
            continue
        value = _strip_inline_quotes(value)
        parsed[key] = value
        if override_existing or key not in os.environ:
            os.environ[key] = value

    return parsed
