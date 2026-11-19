# Lumina 耗材服务器连接说明

源码默认读取 GitHub 公开快照，打包版由发行层连接官方实时目录；两版均先预览、再按需下载，自建服务器配置继续有效。分发区别与尚未接通的官方服务权益见[资源分发](resource-distribution.md)。主动投稿复用 Registry 的现有账号、投稿记录与审核，操作见[资源投稿](resource-contributions.md)。

## 本地耗材目录

源码仓库不附带预置的 `materials/` 档案。源码启动时会自动创建这个可写目录，其内容不纳入 Git；也可通过 `LUMINA_MATERIALS_DIR` 指定其他存储位置。

首次使用可在公开库选择安装、导入耗材包或自己校准。打包版提供固定版本离线资源；源码可运行 `python scripts/prepare_public_resources.py` 准备同一对材料/LUT资源，详见[公开资源与离线使用](public-resources.md)。部署仍支持 `LUMINA_MATERIALS_SEED_PATH` / `LUMINA_MATERIALS_SEED_URL` 和可选的 `LUMINA_MATERIALS_SEED_SHA256`。

打包版首次启动也可保留空库。用户从云端或随包的离线目录查看品牌、包装名和色号，选定条目后单独安装。已有个人资料或主动删空后的工作区均沿用原有内容。

更新现有检出前，请先备份旧 `materials/` 中需要保留的档案；Git 会删除原先跟踪的文件。更新后可恢复备份，或将 `LUMINA_MATERIALS_DIR` 指向仓库外的档案目录。

## 与 LUT 云库的关系

Lumina 的云端资料库分成两条并列能力：

- 耗材云库：同步耗材档案和材料库 package，安装到本地耗材库，供耗材档案、材料包和相关打印参数流程使用。
- LUT 云库：同步 LUT 包和预设，安装到本地 `lut-preset/Cloud/...`，供现有 LUT 详情、预览和生成流程使用。

两者可以使用同一 Registry 服务地址和公开频道，也可以在部署上分开。它们的数据类型、安装目录和运行时用途不同：耗材云库不等同于 LUT 云库，LUT 云库也不会替代耗材档案管理。LUT 云库的公开行为见 [LUT 云库连接与多选 LUT 流程](lut-registry-cloud.md)。

## 服务地址

源码默认读取 `https://raw.githubusercontent.com/lumina-layer-studio/Lumina-materials/master/public/v1`；`LUMINA_PUBLIC_CATALOG_URL` 可配置同格式静态镜像。打包层显式注入 `https://materials.luminastudio.com.cn/api/material-registry/v1`，读取 `official,community` 两个公开频道。该镜像不提供账号和投稿接口，当前官方读接口仍匿名开放。下面是自建实时服务的示例地址：

```text
https://registry.example.invalid/api/material-registry/v1
```

频道示例：

```text
official,community
```

自建服务的频道和认证要求以部署方配置为准；需要认证时配置 `LUMINA_MATERIAL_REGISTRY_TOKEN`。旧私有令牌不会自动带到未显式配置的公共默认源。

旧版 `.env.local` 示例中的空地址行沿用默认公开目录。需要停用云端目录时，在文件中明确写 `LUMINA_MATERIAL_REGISTRY_URL=""`；进程环境中的显式空值也可停用。

`/materials/catalog`、`/packages/upload` 等路径由独立 Material Registry 服务提供。Studio 负责连接、同步和本地资源整理；投稿通过单独的 `LUMINA_CONTRIBUTION_REGISTRY_URL` 连接账号主站，默认是 `https://dan5.shmx.top/api/material-registry/v1`，不把读取令牌带到投稿请求中。主应用不实现 Registry 的账号和审核服务端路由。

## 普通使用者配置

仅在需要连接自己的 Registry 时设置。变量未设置时使用公共默认源；**显式设置为空字符串**可关闭耗材云端读取，LUT 未单独配置时也随之关闭。

以下地址必须替换成实际获授权的服务地址：

```powershell
$env:LUMINA_MATERIAL_REGISTRY_URL = "https://registry.example.invalid/api/material-registry/v1"
$env:LUMINA_MATERIAL_REGISTRY_CHANNELS = "official,community"
```

应用会从当前进程环境或仓库根目录的 `.env.local` 读取以下可选配置：

```text
LUMINA_MATERIAL_REGISTRY_TOKEN
LUMINA_MATERIAL_REGISTRY_TIMEOUT_S
LUMINA_MATERIAL_SYNC_STARTUP_REFRESH
LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S
```

私有 `team` 频道所需 token 应放在本机 `.env.local` 或受控部署环境中，不要写进脚本、提交或命令历史。

Lumina 默认在启动时检查一次目录，之后每 6 小时检查一次，**不会自动下载全库**。安装由用户选择触发。将 `LUMINA_MATERIAL_SYNC_STARTUP_REFRESH=false`、`LUMINA_MATERIAL_SYNC_REFRESH_INTERVAL_S=0` 可关闭后台检查。公开目录支持持久缓存与条件请求；断网时显示缓存状态，本地已安装内容继续可用，未下载内容仍需联网。没有任何自动上传。

如果同一个 `material_id` 在 catalog 中同时出现多个 revision，批量刷新会以 `ambiguous_revision` 失败关闭，不会根据 revision 字符串或返回顺序猜测最新版。用户仍可在云端耗材面板中明确选择某个 revision 手工安装。

## 手动完整同步的 Catalog 条件请求

支持条件请求的独立 Registry 会在 `/materials/catalog` 的成功响应中返回
`ETag`。Lumina 在首次完整同步并确认所有 catalog 条目已经本地收敛后，将
validator 保存到耗材库的 `_sync/index.json`：

```text
catalog_validators[规范化 Registry URL][有序频道组合]
```

这是 schema `1.0` 的可选后端字段，不会出现在 `/api/material-sync/status`、
`/api/material-sync/refresh` 响应、前端状态或日志中。同一个 URL 的
`official,community` 与 `community,official` 是不同的请求表示，会分别保存。

下一次刷新前，Lumina 会重新计算本地状态摘要。摘要覆盖耗材目录中参与同步的
有效文件和同步索引绑定，忽略 `usage_stats.json`、`_solver_cache` 以及
validator 自身。只有当前摘要仍与保存值一致时才发送 `If-None-Match`：

- Registry 返回 `304 Not Modified` 且本地摘要仍一致时，不解析 catalog
  JSON，也不下载 package；公开刷新响应沿用上次条目数作为 `checked_count`，
  并全部计入 `skipped_count`。
- 若等待 `304` 期间本地内容发生变化，Lumina 最多补发一次不带条件头的完整
  catalog 请求。
- 若必需的 `material.json` 或 Stage-A 参数文件被删除或修改，下一次完整响应
  会按真实文件 hash 重新下载。原目录不会被覆盖，干净副本沿用现有时间后缀
  冲突规则安装。
- 无有效 `ETag`、存在包级失败或 catalog 尚未完全本地收敛时，当前频道组合的
  validator 会被清除，下一次继续执行完整请求。

旧 Registry 不返回 `ETag` 时无需额外配置，Lumina 会保持原有的 `200` 完整
同步行为。Lumina 主应用内的兼容 Registry 路由也继续走这条兼容路径，不复制
独立服务的服务端 ETag 实现。本次代码交付不包含云端部署；上面的条件请求只有
在独立 Registry 更新上线后才会生效。

## 连接验证

用浏览器或命令行打开：

```text
https://registry.example.invalid/api/material-registry/v1/materials/catalog?channel=official&channel=community&limit=1
```

PowerShell 验证：

```powershell
Invoke-RestMethod `
  "https://registry.example.invalid/api/material-registry/v1/materials/catalog?channel=official&channel=community&limit=1"
```

正常响应应包含：

```json
{
  "schema_version": "1.0",
  "channels": ["official", "community"],
  "count": 1,
  "total_count": 1,
  "materials": [
    {
      "material_id": "example-material",
      "name": "Example PLA White",
      "vendor": "Example Vendor",
      "channel": "official",
      "package_url": "https://registry.example.invalid/api/material-registry/v1/packages/example-material.zip"
    }
  ]
}
```

`materials` 中会返回实际耗材条目。`total_count` 会随后续发布变化。

## 维护者上传

上传接口：

```text
POST https://registry.example.invalid/api/material-registry/v1/packages/upload
```

独立 Registry 服务使用 Bearer token，不再使用旧版主应用的 official password header。

正确鉴权头：

```text
Authorization: Bearer <LUMINA_REGISTRY_TOKEN>
```

错误示例：

```text
X-Lumina-Material-Registry-Official-Password: ...
```

这个旧头不会被云端独立服务接受，会返回：

```json
{"detail":"maintainer role is required"}
```

真实 token 和开发者上传/审批命令不应写入公开仓库或 issue。

## 常见问题

### catalog 能访问，但上传返回 403

原因通常是没有带维护者 Bearer token，或仍在使用旧的 `X-Lumina-Material-Registry-Official-Password` 头。

### 上传接口 404

确认路径是：

```text
/api/material-registry/v1/packages/upload
```

不是：

```text
/api/material-registry/v1/materials/upload
```

### package 下载失败

Lumina 客户端要求 catalog URL 和 package URL 是同一个 origin，并拒绝重定向。不要把 catalog 指到一个域名、package 指到另一个域名。

### HTTPS

远端 Registry 应使用 HTTPS。实际域名、反向代理、证书和访问凭证由部署方提供并在私有运维文档中维护；本文只保留示例地址和通用客户端配置。
