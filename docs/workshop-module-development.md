# 创意工坊模块开发与发布指南

Creative Workshop module development and release guide

## 先理解边界

创意工坊模块是独立发布、由用户安装的自包含网页应用。模块不能导入 Lumina Studio
源码、React 组件、Zustand store、Electron preload 或私有接口；它只能通过公开
`@lumina/workshop-sdk` 与宿主通信。

正式模块运行在 `sandbox="allow-scripts"` 的 iframe 中。桌面版还会按已提交的模块
frame 拦截网络、WebSocket、跳转、弹窗、权限和下载。普通浏览器只运行签名
Registry 中标记为 `official` 的模块、预装官方 seed 和测试 fixture；Registry 社区
模块、GitHub 模块和普通本地模块需要桌面版，本地模块只有在显式不安全开发模式中
才能用合成数据调试。

浏览器放行不会增加权限：iframe 不获得 `allow-same-origin`，固定 CSP 仍保持
`default-src 'none'` 和 `connect-src 'none'`。模块只能使用 manifest 声明且由宿主
实现的 RPC 能力；服务端安装状态仍是 `source` 与 `official` 身份的最终来源。

这套边界对官方模块和第三方模块相同。不要尝试通过 `fetch`、CDN、动态 `import()`、
`eval`、本地文件路径或父页面 DOM 绕过它。

## 获取不可变 SDK

新模块推荐使用的公开 SDK 是：

- npm 包名：`@lumina/workshop-sdk`
- 版本：`1.0.2`
- 公开源码仓库：`https://github.com/lumina-layer-studio/Lumina-Workshop-SDK`
- GitHub Release tag：`v1.0.2`
- 资产：`lumina-workshop-sdk-1.0.2.tgz`
- 校验文件：`lumina-workshop-sdk-1.0.2.tgz.sha256`

SDK 只通过独立公开仓库的不可变 GitHub Release 分发，不发布可变 `latest` 资产，
也不发布到 npm registry。依赖必须写成包含精确版本的 Release URL：

```bash
pnpm add --save-exact \
  https://github.com/lumina-layer-studio/Lumina-Workshop-SDK/releases/download/v1.0.2/lumina-workshop-sdk-1.0.2.tgz
```

发布资产的 SHA-256 是
`f23f8d0b5181116e8173c0a6f4171405980269615f429be4805973ec4efa93ad`；
也可下载同一 Release 的校验文件独立核对。模块仓库必须提交 `pnpm-lock.yaml`，
CI 使用 `pnpm install --frozen-lockfile`。不要依赖本机 vendor 文件、Lumina
工作区中的 `workspace:*` 路径或未发布的 SDK 源码。

### 版本兼容与预装包 / Compatibility and bundled modules

SDK 包版本、Workshop API 版本和模块版本分别管理，不能用它们的数字是否相同判断兼容性。

| 项目 / Item | 当前版本 / Version | 用途 / Purpose |
| --- | --- | --- |
| 宿主锁定的 SDK / Host SDK pin | `1.0.1` | 固定宿主依赖，不限制模块使用 SDK 1.0.2 / Host pin, not a module SDK requirement |
| 推荐的模块 SDK / Recommended module SDK | `1.0.2` | 新模块开发 / New module development |
| Workshop API / Manifest | `1.0.0` / `1` | 两个 SDK 版本共用 / Shared protocol and package format |
| 官方预装拼豆包 / Bundled bead module | `1.0.1` | 固定的离线安装与恢复包 / Pinned offline installation and recovery |
| 在线拼豆更新 / Catalog bead update | `1.0.8` | 用户可安装的已审核更新 / Reviewed user-installed update |

SDK 1.0.2 保留 PNG 交接和 `ui.getState()`，新增可选 `svgBytes`、
`recommendedTotalThicknessMm` 和 `ui.stateChanged` 事件订阅。当前宿主已实现这些扩展；
面向不支持扩展的旧宿主时，应只发送基础 PNG 交接字段，省略 `svgBytes` 和
`recommendedTotalThicknessMm`；同时提供 PNG 并不会让旧宿主接受未知字段。
只面向支持扩展的宿主时，应声明并测试对应宿主范围。宿主不推送事件时仍读取初始状态。
兼容范围由 manifest 的 `workshopApi` 和 `luminaVersion` 声明，并由宿主安装时校验。

SDK 1.0.1 and 1.0.2 share Workshop API 1.0.0 and manifest v1. SDK 1.0.2 adds
optional SVG/thickness handoff and live UI events. The current host supports
these extensions. For older hosts without extension support, send only the base
PNG handoff fields and omit `svgBytes` and `recommendedTotalThicknessMm`;
including PNG alongside unknown fields is not a fallback. Alternatively, require
a tested host range that supports the extensions. Use `ui.getState()` when a host
does not push UI events.
Declare and test the required host range in the manifest rather than matching
the host's SDK dependency version.

预装包保持锁定，不会因为在线目录出现新版本而在启动时强制升级。在线更新仍先作为候选
版本安装，成功启动后才启用；离线恢复仍使用锁定的预装包。SDK、预装包和签名目录的
历史资产不得替换或重新发布。

The bundled seed remains pinned and does not force an update on startup.
Catalog updates activate only after the candidate starts successfully. Offline
recovery uses the pinned seed; existing release assets remain immutable.

## 最小仓库结构

```text
my-workshop-module/
├── .github/workflows/ci.yml
├── .github/workflows/release.yml
├── LICENSE
├── README.md
├── manifest.json
├── package.json
├── pnpm-lock.yaml
├── public/assets/icon.png
├── scripts/package.mjs
├── src/main.ts
└── test/
```

构建产物必须收敛为一个自包含 `ui/index.html`。JavaScript、CSS、worker 和运行所需
图像都应内联为脚本、样式、`data:` 或 `blob:`；运行时不能引用包内其他文件或外部
URL。

## Manifest v1

`manifest.json` 使用关闭式结构，未知字段、未知权限、重复权限和不完整 SemVer 都会
使安装失败：

```json
{
  "manifestVersion": 1,
  "id": "example.pattern-editor",
  "version": "1.0.0",
  "name": {
    "zh-CN": "图案编辑器",
    "en-US": "Pattern Editor"
  },
  "description": {
    "zh-CN": "读取图纸、校正网格并向 Lumina 交接图像。",
    "en-US": "Read a pattern, correct its grid, and hand an image to Lumina."
  },
  "publisher": "Example Studio",
  "workshopApi": {
    "min": "1.0.0",
    "maxExclusive": "2.0.0"
  },
  "luminaVersion": {
    "min": "2.0.0"
  },
  "entrypoints": {
    "ui": "ui/index.html"
  },
  "permissions": [
    {
      "name": "image.pick",
      "reason": "由用户选择一张图纸并读取其像素"
    },
    {
      "name": "project.storage",
      "reason": "保存和恢复本模块的编辑工程"
    },
    {
      "name": "handoff.image",
      "reason": "把用户确认的 PNG 交给 Lumina 转换器"
    }
  ]
}
```

模块 ID 是永久的全局身份，应使用小写分段名。版本、Release tag、包名和 manifest
版本必须精确一致。同一模块 ID 不能换仓库或改作另一种产品。

仓库更名或转移时，登记的仓库地址和历史签名记录保持不变。宿主只接受 GitHub API
从登记地址确认的当前仓库及其精确 Release 资产地址；模块 ID、发布者和审核身份的
变更仍需单独审核。不要用任意新仓库地址替换登记记录。

Repository redirects preserve the reviewed source identity. GitHub API metadata
must confirm the current repository before a changed asset URL is accepted;
publisher or trust changes still require separate review.

### v1 权限

| 权限 | SDK 调用 | 宿主边界 |
| --- | --- | --- |
| `image.pick` | `client.image.pick()` | 用户主动选择；类型、解码尺寸和 64 MiB 上限由宿主校验 |
| `project.storage` | `client.projects.*` | 只能访问本模块命名空间；单记录 64 MiB、模块总量 256 MiB |
| `color-library.read` | `client.colorLibrary.read()` | 只返回规范化色库，不暴露 LUT、耗材档案路径或私有状态 |
| `handoff.image` | `client.handoff.image()` | 重新校验 PNG、像素、物理尺寸、色库身份和 1 MiB 配方信封 |

权限理由会显示给用户。更新新增权限时，宿主必须再次确认，拒绝后旧版本继续可用。
v1 没有一般网络权限。

## 连接宿主

模块入口只使用 SDK：

```ts
import {
  applyWorkshopUiState,
  connectWorkshop,
} from "@lumina/workshop-sdk";

const moduleId = "example.pattern-editor";
const moduleVersion = "1.0.0";

const client = await connectWorkshop({
  moduleId,
  moduleVersion,
});

const unsubscribeUiState = client.ui.subscribeState(applyWorkshopUiState);
applyWorkshopUiState(await client.ui.getState());
await client.lifecycle.ready();
```

模块关闭时调用 `unsubscribeUiState()`。SDK 1.0.2 的订阅会重放连接期间收到的最新状态，
并防止迟到的 `getState()` 返回值覆盖新状态；旧宿主不发送事件时仍可读取初始状态。

握手必须在 iframe load 后 10 秒内完成。普通请求默认 30 秒，图片交接 120 秒，
原生图片选择器最多等待 5 分钟；控制消息不超过 1 MiB，单次二进制不超过 64 MiB。
错误应使用稳定的 kebab-case 代码，用户消息不能包含堆栈、路径、令牌或原始项目内容。

## 项目、迁移与配方信封

项目记录必须带独立的 `schemaVersion`。读取后先完整验证，再按已知版本逐步迁移；遇到
未知新版本或迁移失败时保留原记录，不做部分写回。更新候选版本启动前，宿主会创建项目
快照；启动或迁移失败时可回滚代码和项目指针。

分享卡只保存重新编辑所需的 JSON：

```ts
const recipeSource = {
  manifestSchemaVersion: 1 as const,
  moduleId,
  moduleVersion,
  projectSchemaVersion: "example-project/v1",
  renderSchemaVersion: "example-render/v1",
  payload: {
    rows: 24,
    columns: 24,
    edits: [],
  },
};
```

信封总量不得超过 1 MiB。不要保存 `Blob`、图片字节、对象 URL、本机路径、GitHub
token、Registry 签名或桌面令牌。Lumina 导入分享卡时只校验通用信封；安装好的模块
负责验证和迁移自身 payload。模块缺失时，转换器图像和参数仍会恢复，并提示用户安装
精确模块版本。

## 图像交接

模块只能通过 `client.handoff.image()` 进入 Lumina 转换器。交接对象至少包含：

- 与当前 manifest 一致的模块 ID 和版本；
- 标准 PNG 的 `ArrayBuffer`、像素宽高与非空内容；
- 推荐物理宽高；
- 可选但自洽的方形网格行列和节距；
- 当前宿主色库 ID；
- 1 MiB 以内的配方信封。

如果转换器已有工作，第一次交接返回 `needs-confirmation`，模块应显示清楚的替换确认，
再由用户触发第二次交接。成功后仍走 Lumina 原有的 LUT/耗材档案、叠色预览和 3MF
生成路径。不要把辅助网格、编号、水印、选中框或诊断覆盖层写入最终 PNG。

## 单文件包

标准资产名是：

```text
<module-id>-<version>.lumina-workshop
```

它是一个 ZIP，但根目录只能包含：

```text
manifest.json
ui/index.html
assets/icon.png
assets/gallery/*     # 可选静态 PNG/JPEG/WebP，最多 20 张
README.md
LICENSE
```

不允许额外 JavaScript 文件、source map、符号链接、重复/大小写冲突路径、路径穿越、
加密成员、动画图片或压缩炸弹。`ui/index.html` 必须在第一个 `<script>` 前出现
`<head>`，不得使用 `eval`、动态 `import()` 或非内联资源。

本地构建应可复现，并先用宿主检查器验证：

```bash
python -m core.workshop.package_validator \
  dist/example.pattern-editor-1.0.0.lumina-workshop
```

## GitHub Release

每个版本发布一个非 draft、非 prerelease 的不可变 Release：

```text
tag:        v1.0.0
asset:      example.pattern-editor-1.0.0.lumina-workshop
checksum:   example.pattern-editor-1.0.0.lumina-workshop.sha256
```

Release workflow 应使用 Node 22、pnpm 10.33.2、冻结 lockfile，完整测试后只打包一次，
从最终资产计算小写 SHA-256。不要重用 tag、替换既有资产或提供可变 `latest` 下载。
Registry 收录时还会绑定 GitHub 仓库、Release tag、字节数、包摘要、manifest 摘要、
权限、兼容范围和审核状态。

## 本地测试 fixture

模块仓库测试不应启动真实 Lumina，也不应复制私有宿主代码。用实现
`WorkshopParentWindowLike` 的小型 harness：

1. 接收 `lumina.workshop.ready`；
2. 核对模块 ID、版本和 API 版本；
3. 通过 `MessageChannel` 发送 `lumina.workshop.connect`；
4. 对每个 RPC 返回固定、合成、无隐私的数据；
5. 覆盖握手超时、权限拒绝、超限 payload、保存/恢复、交接确认和稳定错误码。

主仓库提供的最小 fixture 用于验证宿主契约；模块自己的识别、编辑、渲染和迁移测试
仍留在独立仓库。

## 模块后端（Workshop API 1.1.0）

需要本机 Python 处理的模块声明 manifest v2 后端；公开契约见 SDK 仓库
`docs/backend-protocol.md`（SDK 1.1.0 尚未发布，宿主仍锁定 SDK 1.0.1，后端 RPC 契约
由宿主侧 `frontend/src/workshop/contracts.ts` 承接，与此前支持 1.0.2 扩展的方式相同）。

宿主行为：

- 安装只暂存代码；授权前只解析声明与 `pylock.toml`，不执行模块代码。管理界面展示
  来源、审核等级（官方 / 签名 `reviews-v1.json` 中按包摘要列出的已审核社区版本 /
  未审核）、声明的能力、预计新增与已共享的依赖/模型/Python 运行时。未审核代码需要
  用户勾选风险确认；声明不受系统强制限制，本机进程模式不是沙箱。
- 准备是可取消的后台任务：托管 Python → 按锁内容区分的环境（相同锁共用，冲突版本
  各自独立，大文件经 `runtime/store` 按 SHA-256 硬链接共享）→ 模型下载校验 → 后端
  自检。失败或取消会撤销本次新增内容；只有准备成功的版本才能激活。
- 任务归宿主：落盘于 `runtime/tasks/<模块>/<任务>/`，切页、关闭 iframe 或停止后端都
  不取消任务；取消先协作、宽限期后终止整棵进程树（Windows Job Object；POSIX 进程组
  与进程树）。停用、卸载、退出程序会结束该模块的任务和进程。空闲（默认 5 分钟，模块
  界面打开时延长）后释放进程。
- 卸载默认保留工程、原图副本与结果，可分别选择删除；可选保留已下载模型。无人引用的
  环境、共享文件、Python 运行时与下载缓存按引用回收；结果在卸载报告的“已清理 / 仍共享
  / 已保留 / 未能删除”中列出。已完成任务数据默认保留 14 天，可在“存储”页删除。

开发与离线验证可用的宿主环境变量：`LUMINA_WORKSHOP_UV`（uv 路径）、
`LUMINA_WORKSHOP_PYTHON`（显式解释器，宿主不会安装或删除它）、
`LUMINA_WORKSHOP_WHEELHOUSE`（按文件名提供本地 wheel，仍按锁中哈希校验）、
`LUMINA_WORKSHOP_OFFLINE=1`、`LUMINA_WORKSHOP_WHEEL_MIRROR` 与
`LUMINA_WORKSHOP_PYTHON_MIRROR`（仅 HTTPS 镜像）。

## 发布前检查

```bash
pnpm install --frozen-lockfile
pnpm test
pnpm build
pnpm run package
```

同时确认：

- 包只含允许文件，且入口完全自包含；
- manifest、tag、资产名和实际版本完全一致；
- 权限理由准确，没有申请未使用权限；
- 浅色/深色、中文/英文均可用；
- 浏览器限制提示、桌面沙箱和离线已安装流程可复现；
- 项目迁移、权限扩张拒绝、启动失败和回滚不丢数据；
- 分享卡往返不保存图片字节、路径或凭据；
- README、LICENSE、图标和图库不含外部活动内容。
