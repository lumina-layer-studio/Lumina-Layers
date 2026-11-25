# 机器与 3MF 来源维护手册

本文记录当前机器选择、原生配置和 3MF 导出的维护边界。设备选择界面仍由
Lumina 维护；原生切片配置和 3MF 项目元数据由 FatCat 维护。

## 数据归属

- **FatCat** 维护各切片器精确版本的原生机器、工艺和材料来源，解析继承链，
  并提供 Python 与 C++ 公共入口。来源索引、target contract 和 canonical
  身份都位于 FatCat 仓库；Lumina 运行时不读取 FatCat wheel 的私有目录结构。
- **Lumina** 维护 `machine_registry/registry.json` 中的设备选择身份、缩略图、
  喷嘴选择、热床尺寸和 UI 板面选项。`tools/machine_adapter/` 从明确的本机
  切片器来源更新 picker 数据，不再生成或读取项目配置快照。
- Lumina 继续负责用户材料选择、几何、布局以及本产品明确要求的层高、线宽、
  填充等工艺参数。自定义 3MF 模板通过现有显式项目入口保留其原有字段。
- OrcaSlicer 2.2.4 的 U1 0.4 完整旧项目兼容来源由 FatCat 安装包维护。
  FatCat 通用来源合成入口将其历史工艺与 2.4.2 原生机器和材料结合，保留
  2.2.4 工艺来源记录。Lumina 不保存兼容文件，也不按机型探测或选择兼容路径。

Lumina 不再维护 `printer_profiles/*.json` 或
`machine_registry/**/metadata_templates/*.json`。设备 picker 中不应出现
`template` 文件路径。

## 设备身份

每个 UI 喷嘴项使用稳定的 `device_profile_id`，并保留切片器原生
`source_profile_name`、喷嘴值和 `revision`。不要只根据品牌或相似机型名推断来源。
旧 UI 设备 ID 到 FatCat 稳定 `machine_uid` / `nozzle_uid` 的映射必须同时匹配
切片器、原生 profile 名和喷嘴。

设备目录只保留 UI 所需的来源身份和硬件事实：

| 字段 | 用途 |
|---|---|
| `source_version` | profile 来源包的版本 |
| `revision` | UI picker 来源记录的原生 profile 内容哈希 |

3MF 的 Application、客户端版本头和附属文件策略由 FatCat 根据实际目标
软件版本生成。Lumina 的目录、provider 和导入命令不保存或覆盖这些值。

## 更新 Lumina 设备 picker

只在需要刷新 UI 可选机型、喷嘴或资产时更新 Lumina registry。已经安装并运行过
目标切片器时，可用本机 profile：

```bash
python tools/machine_adapter/sync_local_profiles.py --output machine_registry
```

只导入单个已知来源时，明确填写切片器、来源版本、厂商边界和输出目录：

```bash
python tools/machine_adapter/import_profiles.py \
  --slicer AnycubicSlicerNext \
  --source-root "$HOME/Library/Application Support/AnycubicSlicerNext/system" \
  --source-version 1.3.2605.22 \
  --vendor Anycubic \
  --output /tmp/anycubic-registry-review
```

`import_profiles.py` 生成 picker 来源数据；它不提取或生成 3MF 的机器、材料或
工艺项目配置。合并生成结果前，先检查 slicer/version、正式 machine list、
喷嘴原生值和 profile revision。Flash Studio、QIDI Studio 等来源仍须按 provider
中声明的正式 profile 边界导入，不要因为目录中存在额外 JSON 就扩大支持范围。

更新 `registry.json` 时确认：

- 每个受支持 nozzle 项保留准确的原生 `source_profile_name`、喷嘴值和 revision。
- 所有缩略图和板面图片路径都是 registry 根目录内的相对路径，且文件存在。
- `supported_build_plate_ids` 只表达当前 UI 已支持的板面选择；空选择保持旧有含义。
- 导出 JSON 中不存在 nozzle `template` 路径，也不生成 metadata template 目录。

`machine_registry/registry.json`、图片和版面事实属于 Lumina UI 数据；不要把这些
数据复制进 FatCat 原生配置快照。

### Prusa 设备图片

Prusa 机型、容量和尺寸由已安装 FatCat 的公共目录读取，不在 Lumina 复制工艺
或材料配置。设备图片使用独立的 `picker-assets.json`，按稳定 `machine_uid`
引用同版本原生配置指定图片的 512 像素 PNG；MMU、喷头数量等变体沿用上游
图片选择。原始 SVG 留在上游来源目录，不作为数千行图片描述提交进本体。

用当前 FatCat 依赖及对应 PrusaResearch 原生图片目录刷新：

```bash
python -m tools.machine_adapter.sync_prusa_assets \
  --asset-root /path/to/PrusaResearch/assets \
  --registry-root machine_registry
```

该命令只读取公共配置结果并渲染引用图片，不生成几何或 3MF，也不保存原生
工艺快照。图片及索引随 `machine_registry/` 一起安装，运行时无需联网或安装
PrusaSlicer。来源记录见该版本目录中的 `SOURCES.md`。

设备列表的切片软件支持范围直接取已加载的设备目录。`PrinterProfile`
只保存几何和设备选择使用的硬件事实；旧模板文件名、切片器模板映射和
拼接模板文件名的方法已经删除。

## 更新 FatCat 原生配置

原生项目源的更新在 FatCat 仓库完成。`scripts/sync_native_project_sources.py`
使用 FatCat 中的 source map、target contract 和明确指定的切片器安装包提取原生
profile 及其继承闭包。脚本不 import Lumina，也不依赖 Lumina checkout。更新机器
绑定与耗材 profile 时，使用 FatCat 的 `sync_native_machine_bindings.py` 和
`sync_installed_material_profiles.py`，并按精确 slicer/version/machine/nozzle
来源记录生成，不能用其他软件或近似机型默认补缺。

示例（命令在 FatCat 仓库中运行）：

```bash
python3 scripts/sync_native_project_sources.py \
  --application-root BambuStudio=/Applications/BambuStudio.app \
  --application-root OrcaSlicer=/Applications/OrcaSlicer.app
```

上例仅示范两个明确来源；刷新其他 target 时也要显式提供其目标版本的安装包。
生成后核对 source map、profile inheritance、原生 G-code、运动限制、材料身份、
物理喷头数组、canonical UID 和 target binding。无对应精确来源时应保留为
unavailable 并报告，不要从别的版本或软件复制默认。

FatCat Python 包名为 `fatcat-metadata`，import 名为 `fatcat_metadata`，版本固定为
`0.1.8`。Lumina 的打包合同要求 `native_project_source_catalog` 和随包的
`native_project_sources/source-index.json`。Lumina 只通过公共目录 API 解析 picker
身份；C++ 消费者可使用 FatCat 的 `native_project_source_catalog` 和
`compose_builtin_project_settings`，四参 `compose_project_settings` 用于
显式项目来源。Lumina 的 `load_export_project_settings` 读取内置来源或用户
保存的项目，导出入口不再接收已经不起作用的 `metadata_consumer_type` 参数。

## 3MF 导出维护检查

- 内置单件导出按精确 slicer/version/machine/nozzle 选择 FatCat 来源，并把用户选
  的材料及 Lumina 明确工艺值作为请求传入。
- 用户自定义模板使用现有显式 source 项目路径；未知字段和用户调整必须保留，
  也不要求该机器存在 FatCat 默认工艺才能使用。
- 合并/拼图导出把实际输入项目交给 FatCat 显式合成入口。machine/profile ID 相同
  不表示项目未修改；来源中的温度、流量和未知字段仍是数据来源。
- U1 兼容分支使用上述 Orca 2.2.4 完整项目，经现有双参数显式项目入口处理；不要
  将其描述成 Orca 2.4.2 原生工艺配置。
- Lumina 计算对象和 wipe-tower 布局；FatCat 应用其返回的元数据结果；neroued
  writer 完成一次最终 3MF 写入。

检查生成包中的 `Metadata/project_settings.config`、
`Metadata/model_settings.config`、`Metadata/slice_info.config`、
`3D/3dmodel.model` 及目标 slicer 要求的 sidecar。核对机器/喷嘴身份、材料 ID、
物理数组形状、用户温度和流量、Lumina 显式工艺值以及对象/part 关系。对于合并包，
至少选一个带用户改动的来源项目，确认这些改动在输出中仍能读回。

## GUI 验收范围

原生配置入口变更后，需另行用真实目标软件打开代表性单件和合并包。建议覆盖：

- Bambu Studio：A1 mini 单喷头、H2D 双喷头与双喷头变体。
- OrcaSlicer：一台有精确 process 来源的代表机，以及 U1 2.2.4 兼容路径。
- Snapmaker Orca、ElegooSlicer、AnycubicSlicerNext、FlashStudio 和 QIDI Studio：
  各选一台 registry 当前支持的机型。
- 至少一个自定义 3MF 模板，以及至少一个保留了用户温度/流量修改的合并项目。

这些是验收样本建议，不表示 GUI 验收已完成。确认过程中记录实际软件版本、设备、
喷嘴、材料和输出包路径；如目标软件重写项目，再从未修改的生成包复查。
