# Runtime support

## Current contract

- Run from source with `python api_server.py` or `python start_all.py`, or use
  the Electron desktop app. See the [installation guide](../README.md#installation)
  and [desktop guide](desktop-electron.md).
- Electron starts the local Python backend and Vite frontend. A built frontend
  can also be served by the API with `LUMINA_SERVE_FRONTEND_DIST` and
  `LUMINA_FRONTEND_DIST_DIR`.
- Local settings, slicer launch, feedback, cache cleanup and material management
  keep their origin guards. The retired `LUMINA_ALLOW_PUBLIC_GRAY_API` variable
  has no effect.
- Development servers keep explicit `VITE_ALLOWED_HOSTS` configuration. The
  retired `VITE_ALLOW_ALL_HOSTS` variable no longer bypasses the host allowlist.
- PostgreSQL backends and migrations remain opt-in. Provision a database
  independently and follow the [server backend guide](server-mode-scaffold.md).
- Native SVG uses the independent AGPL-3.0-only `lumina-svg-core` 0.3.4 PyPI release.
  Studio CI installs and verifies the published wheels on Windows, both Mac
  architectures and Linux. Linux x86-64 wheels use manylinux_2_28 / glibc 2.28+;
  Python 3.12/3.13 Mac wheels require macOS 12+, and Python 3.14 requires 14+.
  Studio's ordinary installation requires compatible wheels and stops on
  unsupported targets. SDK maintainers can separately build the SVG release
  source archive with a C++17 toolchain; that does not establish Studio support.
- Linux cgroup CPU/memory limits and the optional local GEOS dense-buffer
  runtime remain independent of deployment packaging.
- Native 3MF metadata comes from FatCat; its dependency setup is documented in
  the desktop source guide.
- Creative Workshop module backends (Workshop API 1.1.0) run as local processes
  prepared by the pinned `uv` from `requirements.txt`; the frozen desktop backend
  carries it under `workshop-tools/`. Backend routes accept only loopback,
  local-origin requests, so LAN/remote browsers get a clear 403. In a plain
  local browser only browser-trusted official modules can open, so only they
  can reach their backends. Targets: Windows x64, Linux x86-64, Apple Silicon
  macOS; automated verification currently runs on Windows.

## Retired on 2026-10-06

Docker image builds, Compose provisioning, PowerShell container deployment,
scheduled container updates, public-test origin bypasses, image-based CI and
container-based Linux wheel builds are removed. No replacement deployment or
compatibility switch is provided.

Historical design plans, experiment results and old changelog entries retain
their original evidence. References there to the retired deployment describe
past behavior and must not be used as current installation instructions.
This document owns the current support decision. Source changes do not remove
previously installed services, scheduled tasks or user data.

## 中文说明

当前支持源码本地运行和 Electron 桌面客户端。桌面页面服务、本地访问限制、
Linux 资源限额检测、可选 PostgreSQL 后端及本地 GEOS 构建均继续保留。
桌面窗口启动本机 Python 和 Vite。原生 3MF 元数据来自 FatCat，
依赖准备方式见桌面源码指南。
SVG 使用独立项目发布到 PyPI 的 AGPLv3 运行时 `lumina-svg-core` 0.3.4，CI 安装并核验
发布包。Linux x86-64 要求 glibc 2.28+；Mac 的 Python 3.12/3.13 包要求 macOS 12+，
3.14 要求 macOS 14+。Studio 普通安装要求兼容 wheel，不支持的平台会停止安装。
SDK 维护者可以另用 C++17 工具链构建 SVG 发行源码包；这不代表 Studio 支持该平台。

2026-10-06 起移除 Docker 构建、部署、定时自动更新、数据库容器配置、
相关 CI 及公网测试访问旁路。旧开关 `LUMINA_ALLOW_PUBLIC_GRAY_API` 和
`VITE_ALLOW_ALL_HOSTS` 不再生效，开发服务器仍支持显式主机名单。
历史文档仅记录当时的实现和验证结果，以本文和当前安装指南为准。
本次源代码清理不会删除已有服务、定时任务或用户数据。
