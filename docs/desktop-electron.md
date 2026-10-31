# 桌面客户端（Electron）源码运行指南

Electron 为 Python + React 应用提供原生窗口、文件选择与保存、创意工坊宿主和退出确认。运行环境仍需安装 Python、Node.js 及项目依赖。架构说明见 [`electron-integration.md`](electron-integration.md)。

## 1. 运行方式

| 方式 | 命令 | 后端 | 前端 |
|---|---|---|---|
| 浏览器 | `python start_all.py` | 本机 Python | Vite |
| 桌面窗口 | `cd electron` 后执行 `pnpm start` | 主进程启动 `api_server.py` | 主进程启动 Vite |

macOS/Linux 可使用 `python3`。桌面窗口会管理自己的后端和前端进程，无需先运行 `start_all.py`。

Electron 会查找项目内的 `venv`、`.venv` 和 `.venv312` 虚拟环境；没有找到时才使用
PATH 中的 Python。更新依赖时应使用实际启动后端的解释器，启动输出会显示其路径。

## 2. 原生 3MF 依赖

本分支支持普通 64 位 CPython 3.12～3.14：Windows x64、Linux x86-64
（glibc 2.28+）和 Apple Silicon macOS 14+。Intel Mac、Linux ARM、Alpine、
Windows ARM、32 位或 free-threaded Python 尚无完整应用所需的 wheel 组合。

3MF 导出链路使用两个独立依赖：

- 元数据 SDK：`fatcat-metadata==0.1.3`，Python 导入名为 `fatcat_metadata`。
  包含 Windows 长路径和精确机型查询修复。
- 写包库：`neroued-3mf==0.4.2`，使用原作者正式发布的 PyPI wheel。
  通用 Production 接口和 Windows 中文/长路径修复已分别在上游
  [PR #17](https://github.com/Neroued/neroued_3mf/pull/17) 和
  [PR #18](https://github.com/Neroued/neroued_3mf/pull/18) 合并。
  无需安装 fork 版本或应用补丁；写包库与 FatCat SDK 的版本独立。

### 使用预编译包

在下一节创建并激活干净的虚拟环境后，从 Lumina 仓库根目录执行：

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

两个依赖均从 PyPI 获取匹配平台的 wheel，无需在应用机器上安装 C++ 编译器。
`requirements.txt` 对四个原生核心包要求二进制 wheel；平台或 Python 不匹配时会
在安装阶段失败。安装不依赖 GitHub 登录或有时限的 Actions artifact。
已有实验环境含旧版 `lumina-3mf-metadata-cpp` 或本地同版本构建时，建议重新创建
虚拟环境，避免共享包文件或旧依赖混入；这不是首次安装步骤。

### 维护者从源码构建

来源提交、仓库和版本由 `scripts/fatcat_packaging_contract.py`
统一维护。FatCat 来自公开仓库
[`MOVIBALE/fatcat-metadata`](https://github.com/MOVIBALE/fatcat-metadata)，固定
完整提交 `5023982e03680e0cd89fb9175dd0ca401d41f6f4`。构建脚本从其根目录
的 `pyproject.toml` 构建 `0.1.3` wheel，无需进入 `cpp/`，不会修改 SDK 源码。
以下供维护者复现源码构建；普通用户使用上方 PyPI 安装即可。
它需要 Git、CMake 和 C++20 编译器（FatCat 本身使用 C++17）。
源码提交和版本必须与下方固定值一致。

writer 固定在上游 v0.4.2 提交 `656f87c55caf742cef2e958a7fc5199cdba2c6f0`，
版本为 `neroued-3mf==0.4.2`。两个源码目录都应保持干净；
构建脚本从上游标签解析真实版本，不注入定制版本号，也不应用 writer 补丁。
从 Lumina 仓库根目录准备本地源码并构建：

```powershell
git clone https://github.com/MOVIBALE/fatcat-metadata.git ..\fatcat-metadata
git -C ..\fatcat-metadata checkout 5023982e03680e0cd89fb9175dd0ca401d41f6f4
git clone https://github.com/Neroued/neroued_3mf.git ..\neroued-3mf
git -C ..\neroued-3mf checkout 656f87c55caf742cef2e958a7fc5199cdba2c6f0

python scripts/build_3mf_native_wheels.py `
  --fatcat-root ..\fatcat-metadata `
  --neroued-source ..\neroued-3mf `
  --install
```

构建产物可以提供给使用相同 Python、操作系统和 CPU 架构的机器。
`--install` 会校验 manifest 中的源码提交和 wheel SHA256，
先卸载旧的 `lumina-3mf-metadata-cpp`，再以 `--no-deps --force-reinstall` 安装
本次精确 wheel。两个包共用 `fatcat_metadata_data`，不能在新包安装后才卸载旧包。
本地修改 SDK 并以同一版本重新构建时也需要此安装步骤，不能只依赖普通 `pip install -r`。
已有当前构建产物时可运行 `python scripts/build_3mf_native_wheels.py --install-only`。
生成目录仅受控更新原生 wheel，其他文件保留。完成后再安装
`requirements.txt` 中的其余应用依赖。

SVG 运行时固定使用独立项目发布的 `lumina-svg-core==0.3.4`（AGPLv3）。
`requirements.txt` 会从公开 PyPI 选择匹配 Python、系统和架构的安装包。
支持 Python 3.12～3.14；Linux x86-64 要求 glibc 2.28+，Mac 的 Python 3.12/3.13
安装包要求 macOS 12+，3.14 要求 macOS 14+。完整 Lumina 应用仍要求 macOS 14+，
由全部原生依赖的支持交集决定。已有开发环境也按下面的统一依赖安装命令更新。

## 3. 环境准备

先安装 Python 3.12～3.14、[Node.js 24.x LTS](https://nodejs.org/en/download)
和 [pnpm 10.33.2](https://pnpm.io/installation)；Node.js 22.x 必须至少为 22.13。
在仓库根目录创建虚拟环境：

```bash
python -m venv .venv
```

Windows PowerShell 用 `.\.venv\Scripts\Activate.ps1` 激活；macOS/Linux 用
`source .venv/bin/activate`（系统仅提供 `python3` 时，用它创建虚拟环境）。然后执行：

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
pnpm --dir frontend install --frozen-lockfile
pnpm --dir electron install --frozen-lockfile
```

上述命令直接安装上一节指定的两个正式依赖。

运行测试时另外安装 `requirements-dev.txt`；仅在明确启用 PostgreSQL 后端时安装 `api/requirements-postgres.txt`，配置方法见 [server-mode-scaffold.md](server-mode-scaffold.md)。

`frontend/` 和 `electron/` 分别安装依赖；pnpm 版本由各目录的 `packageManager` 固定。Electron 安装时会下载当前平台的运行时，其安装脚本已在 `onlyBuiltDependencies` 中允许。`core/requirements-glb-v2.txt` 是可选光栅预览依赖。

## 4. 启动与退出

```bash
pnpm --dir electron start
```

主进程按以下顺序启动：

1. 选择可用的后端端口；若已保存端口被占用则选择其他空闲端口，不会终止占用者。确认本次后端健康后，才将端口保存到用户数据目录的 `backend-port.json`。前端使用 4174 端口，被占用时则报错退出。
2. 优先选择仓库 `.venv` 或 `venv` 中的 Python，再回退到 `PATH`，启动 `api_server.py`。后端健康检查必须确认响应来自本次启动的 Lumina 进程。
3. 启动 `frontend/node_modules/vite/bin/vite.js`，把选定的后端地址传给 Vite 代理。
4. 打开 `http://127.0.0.1:4174`，页面加载失败时自动重试。启动期间显示过渡窗口。

已记住的后端端口被其他程序占用时，桌面窗口选择空闲端口，确认本次 Python 进程健康后才记录新端口。前端继续使用固定的 Vite 地址；不会终止占用端口的其他进程。

重复启动会聚焦已有窗口。关闭主窗口会弹出当前语言的退出确认框；确认后停止本次启动的 Python、Vite 及其子进程。

### 界面缩放

桌面版把页面固定排在一套统一的尺寸上（1536×864），不再让排版区分辨率或系统缩放变化。因此同一块屏幕上，面板、顶栏等元素占窗口的比例是固定的：1080p 开 125%、4K 开 200%、2K 开 100% 得到的界面比例一致。设置入口在 **设置 → 常规 → 界面缩放**，仅桌面版显示；浏览器使用浏览器自带的缩放。

这是有意的设计：软件不跟随系统的显示器分辨率或系统缩放，换屏幕、改系统缩放都不会改变界面的排版比例，只有用户自己选档才会变。代价是文字的实际物理大小随屏幕而变（高分屏上偏大），观感与其他跟随系统设置的应用不同；如果改成直接使用系统缩放，排版就会重新由系统决定，这正是当前实现要避免的。

- **100%（默认）**：上述统一尺寸。缩放倍数按窗口所在显示器的逻辑尺寸计算（`min(宽 / 1536, 高 / 864)`），把分辨率和系统缩放一并抵消掉。
- **80%–175%**：在统一尺寸的基础上再放大或缩小，档位为 80、90、100、110、125、150、175。
- **快捷键**：Ctrl 加号、Ctrl 减号逐档调整，Ctrl 0 回到 100%；macOS 用 Command。键盘由 `before-input-event` 接管；macOS 原生「显示」菜单使用同一套持久化缩放逻辑。
- **最小窗口**：页面至少保留 960×620 CSS 像素，窗口最小尺寸等于它乘以当前页面倍数，切换档位或换屏时更新，避免面板挤压后遮住 3D 工具栏。已打开的普通窗口小于新的最小尺寸时会主动放大，并保持在工作区内；最大化、最小化和全屏窗口不调整。所选档位按这个最小尺寸放不进屏幕工作区时，页面倍数会降到刚好放得下。

### macOS 原生菜单

应用启动时安装 Lumina 菜单，前端就绪后同步中英文文案和可用操作。设置（Command+,）、反馈问题调用现有页面入口；文件菜单的导入（Command+O）使用转换页上传器，支持图片、SVG 和分享卡；保存已生成文件（Command+Shift+S）使用现有下载和保存对话框。相关工作流未挂载、文件尚未生成或操作不可用时，对应菜单项禁用。编辑菜单的撤销/重做是原生文本编辑操作，不替代转换器的业务历史。

显示、窗口、隐藏、服务和退出保留 macOS 原生行为，退出继续经过确认并清理子进程。帮助菜单链接到当前语言的 Lumina 文档。Windows/Linux 继续隐藏应用菜单。通过 `electron .` 开发启动时，系统应用名仍可能为 Electron；应用包品牌信息由打包流程处理。
- 倍数按显示器计算，不按窗口大小计算：拖小窗口时字号不变，只是可见区域变少；窗口移到另一台显示器或显示器设置变化时自动重算。窗口没有最大化时，面板的固定像素宽度占窗口的比例会比满屏时大一些。
- 偏好保存在用户数据目录的 `interface-scale.json`（与 `backend-port.json` 同处），每台电脑各自一份。

窗口首次打开时按“1440×900 × 缩放倍数”居中，超过工作区 90% 则预先最大化；最大化发生在页面加载之前，避免页面按旧宽度排好面板后再重新对齐。每次实际改变缩放都会在桌面日志里记一行 `Interface scale <档位>: zoom <倍数> on a <宽>x<高> display`。

## 5. 日志与排障

桌面日志在 `app.getPath("logs")/lumina-electron.log`，记录主进程、Python 和 Vite 输出。Python 的结构化日志默认在仓库 `logs/`；分析方式见 [`logging-guide.md`](logging-guide.md)。

| 症状 | 检查与处理 |
|---|---|
| Backend Start Failed | 确认所选 Python 已安装 `requirements.txt`，查看桌面日志中的解释器路径。 |
| 后端长时间未就绪 | 检查原生依赖是否匹配当前 Python 和平台，查看 Python 日志。 |
| 本地端口不可用 | 关闭自己不再使用的服务，再重试。 |
| 窗口白屏 | 查看 Vite 输出，确认前端依赖完整、4174 端口可用。 |
| Electron 运行时缺失 | 在 `electron/` 重跑 `pnpm install`，确认 Electron 安装脚本获准执行。 |
| pnpm 无法识别 | 按 pnpm 官方安装说明安装 10.33.2；不要假定所有 Node.js 都自带 Corepack。 |

项目启动器残留可用 `python start_all.py --kill` 清理。只清理本项目启动的进程。

## 6. 验证

桌面测试使用 `pnpm --dir electron test`。修改启动、退出或窗口行为时，检查窗口能打开、退出确认有效、退出后自己的子进程已停止。修改界面缩放时，另需确认自动档在不同缩放比例的显示器上给出预期倍数、手动档和快捷键即时生效、重新打开后沿用上次档位。修改前后端业务功能时，按实际受影响的功能运行测试。
