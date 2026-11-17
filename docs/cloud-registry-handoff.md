# Lumina 云端耗材与 LUT Registry 交接文档

本文保留 Registry 的历史兼容记录，并提供自建服务的配置与运维参考。当前源码和打包版默认匿名读取公开镜像，目录检查与安装已经分开；最新行为见[公开资源与离线使用](public-resources.md)。下文运维示例不代表公开镜像提供登录、上传或管理接口。

## 历史兼容记录

2026-07-09 的内部联调曾验证以下两类只读 catalog。下列数量属于历史记录，不代表当前服务的内容数量或匿名访问权限：

- 耗材云库：`materials/catalog`，当前公开频道返回 `total_count=181`。
- LUT 云库：`luts/catalog`，当前公开频道返回 `total_count=67`。

两类云库共用同一个 Registry 服务地址，但数据类型和本地安装目标不同：

- 耗材 package 安装到本地耗材库，服务于材料档案和打印参数流程。
- LUT package 安装到本地 `lut-preset/Cloud/...`，服务于 LUT 详情、预览、生成和颜色匹配流程。

相关 PR 已合并：

- Lumina Materials PR #2：`Reconcile cloud LUT packages`，merge commit `1631031`。
- Lumina Material Registry PR #2：`Normalize LUT registry package file hashes`，merge commit `ba6e642`。

当时的部署已应用这轮 LUT Registry 兼容修复和 67 个 LUT 数据集，服务状态验证为 active。后续部署应从已审查的提交构建和发布，单独核对服务器状态。

## 仓库职责

| 仓库 | 职责 | 当前说明 |
| --- | --- | --- |
| `Lumina-Layers` | 客户端和主应用集成 | 读取 Registry catalog，安装云端耗材/LUT 到本地。 |
| `Lumina-materials` | 内容源 | 维护耗材 package、LUT 源文件、LUT package 和去重报告。 |
| `Lumina-material-registry` | Registry 服务端 | 提供 catalog、upload、approve、download、unpublish 等 API。 |

后续不要直接把 Lumina Studio 本地 `lut-preset/` 当作权威源上传。新的公开内容应先进入 `Lumina-materials`，通过 package 校验后再同步到 Registry。

## 服务地址

自备 Registry 的 base URL 示例；使用前必须替换为你自行部署或已获授权的地址：

```text
https://registry.example.invalid/api/material-registry/v1
```

频道示例：

```text
official,community
```

频道的可见性和认证要求由服务部署方决定，不能仅凭 `official` 或 `community` 的名称判断是否允许匿名访问。按部署方要求配置 Bearer token，上传、审批、下架和恢复还需要相应角色权限。真实服务地址和 token 不写入公开文档、PR、issue 或日志；本地私有说明可放在 git-excluded 的 `docs/private/material-registry-developer-access.md`。

## Lumina Studio 连接配置

未设置 URL 时使用公开默认源；显式空字符串关闭读取。需要连接自建服务器时配置：

```powershell
$env:LUMINA_MATERIAL_REGISTRY_URL = "https://registry.example.invalid/api/material-registry/v1"
$env:LUMINA_MATERIAL_REGISTRY_CHANNELS = "official,community"
```

配置 LUT 云库：

```powershell
$env:LUMINA_LUT_REGISTRY_URL = "https://registry.example.invalid/api/material-registry/v1"
$env:LUMINA_LUT_REGISTRY_CHANNELS = "official,community"
```

如果没有单独配置 `LUMINA_LUT_REGISTRY_URL`，Studio 的 LUT 云库逻辑会回退使用 `LUMINA_MATERIAL_REGISTRY_URL`。为了排障清楚，团队测试时建议两组变量都显式设置。

## 自备服务的 catalog 验证

PowerShell 验证耗材 catalog：

```powershell
Invoke-RestMethod "https://registry.example.invalid/api/material-registry/v1/materials/catalog?channel=official&channel=community&limit=1"
```

PowerShell 验证 LUT catalog：

```powershell
Invoke-RestMethod "https://registry.example.invalid/api/material-registry/v1/luts/catalog?channel=official&channel=community&limit=1"
```

注意 URL 里有 `&`，在 shell 中必须放进引号，否则后半段 query 可能被 shell 当成命令分隔符。

历史联调记录（自建实例的数据数量以实际部署为准）：

- `materials/catalog` 返回 `channels=["official","community"]`，`total_count=181`。
- `luts/catalog` 返回 `channels=["official","community"]`，`total_count=67`，并同时包含 `items` 和 `luts` 字段。

如果不传 `channel=community`，默认只看 `official`，可能看到 0 条或少量条目。

## Studio 端 LUT 验证

启动 Studio 后，可检查主应用自己的 LUT 云库代理接口：

```text
GET /api/lut-registry/status
GET /api/lut-registry/catalog?limit=5
POST /api/lut-registry/install
```

安装成功后，LUT 会写入：

```text
lut-preset/Cloud/...
```

同步索引写入：

```text
lut-preset/_sync/luts/index.json
```

Registry PR #2 已修正一个关键契约：catalog 的 `content_hash` 和下载包 manifest 里的 `lut_file.content_hash` 都使用裸 64 位 LUT 文件 sha256。旧的 `sha256:<hash>` 格式会导致当前 Studio 安装器拒绝安装。

## 内容同步规则

LUT 内容同步遵循以下顺序：

1. 在 `Lumina-materials` 中加入或更新 `luts-src/...`。
2. 运行 LUT package 构建脚本，生成 `lut-packages/...`。
3. 运行校验：

```powershell
python scripts/validate_lut_packages.py --packages lut-packages
python scripts/validate_packages.py --packages packages
```

4. 通过 Registry API 上传到 pending，再审批到 `community` 或 `official`。
5. 同步后检查线上 catalog 和 package 下载 hash。
6. 对过期线上条目执行 unpublish，不直接删除历史文件。

这次 LUT 同步结果：

- 服务器原有 LUT catalog：69 条。
- 与 `Lumina-materials` 对比后，服务器额外候选：21 条。
- 实际反向整理进 `Lumina-materials` 的唯一内容：19 条。
- 跳过重复上传：2 条。
- 线上最终公开 LUT catalog：67 条。

## 去重规则

去重优先级：

1. `local_path` 重复：通常应视为冲突，不能同时发布。
2. LUT 文件 sha256 重复：默认视为重复上传。
3. 不同 `local_path` 指向同一个文件 sha256：只有在明确作为别名保留时才允许。

当前 67 个 LUT 中：

- 没有重复 `local_path`。
- 有 1 组保留的文件 hash 别名：
  - `通用LUT[有色差]RYBW General for personal use.npy`
  - `Elegoo/Elegoo_pla_RYBW.npy`

这组是既有别名，不是本次新增的重复上传。

## 上传和审批

上传和审批必须使用独立 Registry 的 Bearer token：

```text
Authorization: Bearer <LUMINA_REGISTRY_TOKEN>
```

不要使用旧版主应用的 header：

```text
X-Lumina-Material-Registry-Official-Password: ...
```

旧 header 会返回 403，例如：

```json
{"detail":"maintainer role is required"}
```

真实 maintainer、approver、team token 只能通过私有渠道分发。不要把 token 写入 commit、PR、issue、公开聊天记录、脚本示例或日志。

## 服务器运行状态检查

常用只读检查：

```bash
systemctl is-active lumina-material-registry.service
systemctl is-active caddy.service
journalctl -u lumina-material-registry.service -n 100 --no-pager
```

历史部署使用 Caddy；自建实例应按实际使用的反向代理排障。

服务端代码更新后的最低检查：

```bash
cd <registry-app-dir>
<venv-python> -m py_compile registry_service/store.py
systemctl restart lumina-material-registry.service
systemctl is-active lumina-material-registry.service
```

生产数据变更前必须先做服务器数据目录备份。备份路径属于私有运维信息，不写入公开文档。

## 常见问题

### catalog 返回 0 条

先确认是否传了两个频道：

```text
channel=official&channel=community
```

默认只读 `official`，而很多社区内容在 `community`。

### 上传返回 403

通常是缺少 Bearer token，token 角色不对，或者仍使用旧的 official password header。

### Studio 安装 LUT 时 hash 校验失败

确认 Registry 服务包含 PR #2 的修复，并且线上 package manifest 里的 `lut_file.content_hash` 是裸 64 位 sha256，不是 `sha256:<hash>`。

### package 下载 502 或连接失败

先查：

```bash
systemctl is-active lumina-material-registry.service
systemctl is-active caddy.service
journalctl -u lumina-material-registry.service -n 100 --no-pager
journalctl -u caddy.service -n 100 --no-pager
```

如果服务 active，但公网偶发失败，用带重试的下载校验区分网络瞬断和包损坏。

## 相关文档

- [耗材服务器连接说明](material-registry-connection.md)
- [LUT 云库连接与多选 LUT 流程](lut-registry-cloud.md)
- `docs/private/material-registry-developer-access.md`：本机私有文档，git-excluded，可记录真实 token 和私有运维路径。
