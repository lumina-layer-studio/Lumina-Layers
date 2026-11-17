# LUT 云库连接与多选 LUT 流程

本文说明 Lumina Studio 的 LUT 云库 v1 行为，以及主转换流程如何从旧的 LUT 合并入口转为同组多选 LUT。本文只描述公开客户端行为，不包含真实 token、服务器私有路径或私有部署配置。

源码默认读取 GitHub 静态目录，打包版读取发行层配置的官方实时库，浏览目录不会自动安装。已有目录可离线查看，界面会标明缓存；未下载内容仍需联网。[资源分发](resource-distribution.md)说明来源与官方服务权益边界；[公开资源与离线使用](public-resources.md)说明固定版本离线包、首次初始化和显式恢复。

## 与耗材云库的关系

Lumina 的云端资料库有两条并列能力：

- 耗材云库：管理耗材档案、材料库 package 和与耗材参数相关的本地材料数据。
- LUT 云库：管理 LUT 包和 LUT 预设，供 LUT 详情、预览、生成和颜色匹配流程使用。

两条能力可以共用 Registry 服务、频道和只读 catalog 访问方式，但安装目标和业务语义不同。耗材云库安装的是材料档案；LUT 云库安装的是单个 LUT 文件。

## v1 行为边界

LUT 云库 v1 采用 catalog/install 模式：

1. 客户端通过 `GET /api/lut-registry/catalog` 获取远端 LUT catalog。
2. 用户选择一个 catalog 条目后，客户端通过 `POST /api/lut-registry/install` 提交 `lut_id` 和 `revision_id`。
3. 后端使用本机配置的 Registry URL、频道和 token 重新拉取 catalog，匹配同一个 `lut_id/revision_id` 后才下载 package。
4. 安装后的 LUT 文件写入本地 `lut-preset/Cloud/...`。
5. 本地同步索引写入 `lut-preset/_sync/luts/index.json`，记录已安装 LUT 的 revision、hash、安装时间和来源信息。
6. `GET /api/lut-registry/status` 返回本机是否已配置云库、当前频道、同步安装数量、本地 LUT 数量，以及 `history` 本地版本记录。
7. `POST /api/lut-registry/restore` 接收 `lut_id`、`revision_id`，验证本机对应文件的内容后切换本地版本记录，不要求登录或联网，不增加下载人数。

目录的 `local_state` 区分 `not_installed`（未下载）、`installed`（本地当前版本）、`local_available`（相同内容在本地，或已保留的历史版本）、`update_available`（同一资源有不同内容尚未下载）、`local_missing`（安装文件缺失）、`local_modified`（安装文件被修改）。仅路径或名称相同不认定为同一资源的更新。版本差异不等于可靠的发布时间先后，界面使用“与本地当前版本不同”。

索引以 `current_revisions` 记录每个 LUT 的本地当前修订；没有该字段的旧索引按本地最后安装记录读取，无须首次启动改写文件。`history` 逐资源给出名称、当前修订和各修订的本地安装时间、可恢复性、有效本地相对路径。恢复入口全局可用，目录断网或条目已不在远端时仍能访问本地记录。

不同内容安装到独立的修订路径，已有项目和转换选择继续引用原文件。恢复只切换本地记录，不自动替换已选 LUT；从转换选择器选择需要的文件才能更改当前转换。文件被修改时重新下载会另存原始内容，保留用户编辑的文件。缺失或内容校验失败的版本不能直接恢复。

同一 LUT 有多个本地修订时，`GET /api/lut/details/catalog` 为有效文件附带 `local_version`（`current` 与 `installed_at`）。本地库和图像转换选择器据此显示本地当前版本／历史版本及安装时间，恢复后刷新标识。单修订条目不增加版本行。

v1 的 LUT 包约束是“一包一 LUT”：一个云端 package 只安装一个 LUT 文件，支持的本地 LUT 扩展名沿用现有 LUT 系统，例如 `.json`、`.npy`、`.npz`、`.msgpack`。安装逻辑会验证 package hash、内容 hash、包大小、`Content-Length`、ZIP 解压前文件大小、同源 package URL、本地目标路径和 LUT 内容可加载性，避免把不可用文件写入本地 LUT 库。

catalog 中的 `local_path` 约定为相对路径，不包含 `lut-preset/`，也不需要包含开头的 `Cloud/`。例如远端返回 `Official/CMYW/profile.json` 时，客户端安装到 `lut-preset/Cloud/Official/CMYW/profile.json`。后端会兼容并规范化误带 `Cloud/` 前缀的 catalog 数据，避免写成 `Cloud/Cloud/...`。

安装完成后，Lumina 不从远端下载预计算详情图，也不在云端保存用户本机详情缓存。LUT 详情、调色板、颜色网格、KD-Tree 匹配和预览/生成所需的数据，仍由本地现有 LUT 详情系统在下载后计算。

## 客户端配置

LUT 云库优先读取独立环境变量；未设置时可回退到耗材云库的只读配置：

```powershell
$env:LUMINA_LUT_REGISTRY_URL = "<LUMINA_REGISTRY_URL>"
$env:LUMINA_LUT_REGISTRY_CHANNELS = "official,community"
$env:LUMINA_LUT_REGISTRY_TOKEN = "<LUMINA_REGISTRY_TOKEN>"
```

普通公开频道通常不需要 token。只有私有频道、上传、审批或维护者操作才需要 Bearer token。公开文档、issue、PR 和日志中只能写 `<LUMINA_REGISTRY_TOKEN>` 这类占位符，不要写真实 token。

如果没有单独配置 `LUMINA_LUT_REGISTRY_URL`，客户端使用耗材读取地址，未设置两者时使用公开默认源。显式空 URL 关闭对应读取。自建服务同一地址可共用材料只读 token；LUT 指向另一地址时必须显式提供对应 token，不转发原服务器凭据。

## 同组多选 LUT 主流程

新的推荐主流程是“同组多选 LUT”，而不是先生成一个用户可见的合并文件：

1. 用户在主转换流程中选择多个兼容的 legacy LUT。
2. 前端发送 `source_kind=legacy_multi`。
3. `lut_name` 保持为所选列表的第一项，用于兼容仍只读取单个 LUT 名称的旧调用链。
4. `lut_names` 发送全部所选 LUT 名称，用于运行时构建完整多 LUT 源。
5. 后端在本次预览或生成运行时创建临时源，完成兼容性校验、颜色匹配和配方解析。
6. 系统不生成用户可见的 `Merged_*` LUT 文件，也不要求用户先进入旧合并入口。

多选 LUT 应保持在同一兼容组内，例如颜色模式、层数、层高、层序和必要调色板语义一致。若组合不兼容，客户端或后端应给出确定性错误，而不是静默降级到单个 LUT。

## 旧 merge API 兼容边界

旧的 `/api/lut/merge` API、历史 `Merged_*` 文件和已保存的合并 LUT 仍保留兼容，便于打开旧项目、复现旧 bug 和处理已有用户数据。

但它们不再是主流程推荐入口。新的 UI 和新文档应优先引导用户在转换流程里直接多选兼容 LUT，让运行时临时源完成组合计算。只有需要导出或检查历史合并产物时，才应提到旧 merge 行为。

## 安全与公开文档规则

- 不在公开文档写真实 Registry token、私有服务器路径、私有对象存储路径或维护者命令。
- token 示例只使用 `<LUMINA_REGISTRY_TOKEN>` 等占位符。
- 公开文档只描述客户端可见的 API、环境变量、本地安装目录和兼容边界。
- 私有频道、上传审批、服务端 catalog 生成和生产部署细节应留在私有运维资料中。
