# 3MF Metadata Export

## Purpose

This guide describes the current 3MF export boundary and where its configuration lives.
Lumina supplies selected device/material facts, geometry, layout, and explicit product
process values. FatCat composes slicer project metadata; the pinned `neroued-3mf`
writer writes the final package once.

本文说明当前 3MF 导出边界及配置归属。Lumina 提供用户选择的设备和材料事实、几何、
布局及明确的产品工艺值；FatCat 合成切片器项目元数据，固定版本的 `neroued-3mf` 单次写出最终包。

## Code entry points / 代码入口

New callers import from `utils.slicer_3mf_writer`:

```python
from utils.slicer_3mf_writer import (
    Slicer3MFWriter,
    MergedSlicer3MFWriter,
    export_scene_with_slicer_metadata,
)
```

The existing `BambuStudio3MFWriter`, `MergedBambu3MFWriter`, and
`export_scene_with_bambu_metadata` names remain aliases of these same objects.
Existing Bambu module imports, call parameters and defaults continue to work.
The scene pipeline and puzzle assembly use the neutral entry point; the scene
pipeline keeps its local legacy hook name for existing callers that replace it.

新调用方使用上述通用入口。旧 Bambu 类名、函数名和模块导入继续兼容，指向同一实现，
调用参数和默认值保持不变。场景流水线与拼图组装已接入通用入口；场景流水线保留原有
本地调用钩子名称，兼容已有替换调用。

| Responsibility / 职责 | Owner / 位置 |
| --- | --- |
| Single export orchestration / 单件导出组织 | `Slicer3MFWriter.export()` |
| Batch and puzzle orchestration / 批量与拼图组织 | `MergedSlicer3MFWriter` |
| Fixed composer envelopes and request types / 固定合成结果与请求类型 | `utils/fatcat_metadata.py` |
| Shared device and placement facts / 共用设备与摆放事实 | `utils/slicer_3mf_support.py` |
| Product colour lookup / 产品颜色查找 | `core/export_materials.py` |
| Cover and plate image bytes / 封面与盘面图片字节 | `utils/bambu_3mf_cover.py` |
| Native parts and relationships / 原生部件与关系 | FatCat's installed `fatcat_metadata_neroued` adapter |

Each export prepares configuration, queues geometry, describes metadata, builds
resources and writes once. Internal records keep source slot mappings and queued
IDs explicit; single exports retain their zero-copy arrays through the final write.
`TypedDict` constrains the fixed SDK envelopes and model inputs, without adding
a second schema validator or filtering opaque native project settings. Runtime
validation stays at the existing SDK, source parser and writer boundaries.

导出按配置、几何、元数据、资源、单次写包组织。内部数据结构明确记录源槽位映射和
入队对象身份，单件导出的零拷贝数组保留到写出结束。固定 SDK 外层字段及模型输入
使用 `TypedDict` 提供静态约束；原生项目里的未知设置继续完整保留。运行时校验仍由
已有 SDK、源文件解析器及 writer 边界负责。

## Ownership

- **FatCat** owns stable native machine/nozzle identities, native source data, material
  and process composition rules, and slicer-specific package metadata.
- **Lumina** owns the device picker and its registry/assets, user material selection,
  geometry/layout, and explicit Lumina process intent. It does not read FatCat's
  private package files.
- **neroued-3mf** owns the one final 3MF package write.

FatCat is distributed as `fatcat-metadata`, imported as `fatcat_metadata`.
Lumina uses `fatcat-metadata==0.1.4` for H3C and the slicer profiles listed below.
It retains Windows long-path support and the exact `native_project_source` query. Install the released wheel from PyPI
through `requirements.txt`.
Lumina resolves only the selected machine's native dependencies during export.
Maintainer builds use the public
[`MOVIBALE/fatcat-metadata`](https://github.com/MOVIBALE/fatcat-metadata) root
project at source revision `c2f39b9dedfeb8b6c015784e2aae1d82e56e7ffd` and pins
the writer contract in
`scripts/fatcat_packaging_contract.py`; build and installation steps are in
[the desktop setup guide](desktop-electron.md).

FatCat 发行包名为 `fatcat-metadata`，导入名为 `fatcat_metadata`。
本体使用 `fatcat-metadata==0.1.4`，新增 H3C 并更新下列切片配置，保留 Windows 长路径支持，并用
`native_project_source` 只解析所选机型依赖。通过 `requirements.txt`
从 PyPI 安装正式 wheel。
维护者从公开仓库
[`MOVIBALE/fatcat-metadata`](https://github.com/MOVIBALE/fatcat-metadata) 的根项目构建，
源码提交固定为 `c2f39b9dedfeb8b6c015784e2aae1d82e56e7ffd`，并在
`scripts/fatcat_packaging_contract.py` 维护 writer 合同；构建与安装步骤见
[桌面环境指南](desktop-electron.md)。

The writer uses the official PyPI release `neroued-3mf==0.4.2`.
Generic Production APIs and Windows Unicode/long-path output are included
after [upstream PR #17](https://github.com/Neroued/neroued_3mf/pull/17) and
[PR #18](https://github.com/Neroued/neroued_3mf/pull/18) were merged.
Source builds pin release commit `656f87c55caf742cef2e958a7fc5199cdba2c6f0`;
no downstream writer patch, version suffix, or fork download channel is required.

写包库使用 PyPI 正式版 `neroued-3mf==0.4.2`，已包含上游合并的通用
Production 接口及 Windows 中文/长路径修复。源码构建固定同一发行提交，
无需下游补丁、定制版本后缀或 fork 下载渠道。

The current source pin includes Bambu Studio 02.09.01.70, OrcaSlicer 2.4.2,
QIDI Studio 02.07.02.73, ElegooSlicer 1.5.3.5, Anycubic Slicer Next
2.0.0.6, Flash Studio 1.7.19, Snapmaker Orca 2.4.1, and PrusaSlicer
3.0.0-alpha13 metadata.
Native process defaults supply specific printing speeds. Lumina no longer sends
the historical overall `print_speed` placeholder. Specific speed overrides follow
each target's declared FatCat contract; Bambu-family overall-speed requests are rejected.
Explicit unsupported overrides are rejected; they are not silently dropped.
FatCat's declared aliases replace matching product defaults, while conflicting
explicit aliases still produce an error. Saved user-template settings remain opaque
source data rather than being reinterpreted as new process overrides.

Built-in exports and merges pass the product name `Lumina` through FatCat's
`project_preset_name` request field. FatCat writes an independent project preset
name while retaining the original native source and all composed process values.
The displayed project name therefore does not claim the source's original layer
height. Imported single-project templates retain their own preset name.

当前源码固定值包含上述八种软件的元数据版本。具体打印速度来自原生工艺配置，
Lumina 不再发送历史 `print_speed` 总速度占位值；具体速度修改遵循目标软件的
FatCat 合同，Bambu 家族不支持的总速度请求会报错。明确请求的不支持参数仍会
报错，不会静默忽略。明确指定任一首层高度名称会替换默认值；两个名称
下明确提供矛盾值时仍会报错。用户模板中的设置继续作为原始来源数据保留，
不会被重新解释成新的工艺修改请求。

内置导出和合并通过 project_preset_name 向 FatCat 传入项目名称 Lumina。
FatCat 统一写入独立项目预设名称，保留原生来源与已合成的工艺参数，避免显示
原生 0.20mm 名称时让用户误以为实际层高也是 0.20mm。单件用户模板保留自身预设名称。

## Current Selection and Composition

Built-in exports use FatCat's `resolve_project_materials` for both preflight and
final composition. It returns native filament candidates and the plates compatible
with the complete selection. Ambiguous presets require an explicit user choice;
an incompatible plate is a configuration error, not an internal server failure.
Lumina's **Print materials…** action opens the same selection dialog after preview.
Saving there changes only native preset and plate choices; generation resumes only
when requested. Generate and batch actions show this dialog when preflight needs
input, then continue after confirmation. Choices are scoped to the slicer, exact
device and nozzle, and are included in saved recipes and bug-report context.
Imported user templates retain their own material tuning and bypass built-in
selection. Layer heights, speeds, flow and other explicit process overrides stay
on the existing composition path; preflight does not rewrite them.

内置导出的预检和最终组装共用 FatCat 的原生耗材解析规则，返回候选预设和整套材料
共同兼容的打印板。多个候选时由用户明确选择，板型不兼容则返回可操作的配置错误。
预览后可点击「打印耗材…」主动修改；这里保存选择不会立即生成。直接生成或批量
生成遇到歧义时，也会打开同一窗口，确认后继续。选择按切片软件、具体设备和喷嘴
隔离，并写入配方及工单复现上下文。导入的用户模板继续保留自身耗材调校；层高、
速度、流量等明确工艺值仍走已有组装流程，预检不会改写这些值。

Automatic tower placement first preserves the selected native body style. If
it cannot fit safely, the shared single/batch/puzzle solver may select a
rectangular body only when FatCat declares that native style. FatCat writes
the style through its tower API and records the native process difference.
Model dimensions, layer settings, materials and purge volumes are retained.
When no safe layout fits, or the printable area is absent, automatic export
stops with an actionable error. Turning automatic placement off retains the
manual layout path.

自动摆塔优先保留原生塔形状；放不下时，单件、批量及拼图共用的求解器只尝试
FatCat 明确声明支持的矩形塔。塔形状由 FatCat 原生接口写入并记录工艺差异，
保留模型尺寸、层设置、材料和冲刷量。所有支持形状均无安全解或缺少打印区域时，
自动导出停止并给出可操作错误；关闭自动摆放后仍可自行安排布局。

Lumina maps its selected registry entry to FatCat's public native-source catalog by
exact slicer, source profile name, and nozzle identity. The resulting stable machine
and nozzle identifiers, requested plate, selected materials, and explicit process
values are passed to FatCat. No similar-family machine or project snapshot is used as
a built-in fallback.

- Built-in single exports use FatCat's installed native-source composer.
- Saved user project templates keep the existing explicit-project composer and retain
  their unknown settings; they do not need an available built-in process preset.
- Merged exports pass the actual source projects to FatCat's explicit-project composer.
  Matching preset IDs do not authorize replacing source values: user-edited temperatures,
  flow settings, and unknown keys remain source data.
- Wipe-tower placement and object layout are computed by Lumina and passed explicitly
  to FatCat for metadata application.

Lumina resolves the picker entry through FatCat's public
`native_project_source_catalog(slicer_id)` binding. Built-in project composition uses
`compose_project_settings(request_json)`; user projects and merged source projects use
the existing explicit two-argument form. C++ consumers use the same packaged source
catalog and built-in composer through a public packaged data root. The existing
four-argument explicit-source composer remains supported.

**Snapmaker U1 compatibility source.** OrcaSlicer 2.4.2 has an exact native U1 0.4
machine source, but its native process is unavailable. The complete native catalogue
contains `Snapmaker PLA @U1`, whose textured plate temperature is zero.
The separate declared Snapmaker PLA default only lists A250/A350 as compatible. FatCat packages
one complete Orca 2.2.4 compatibility project and selects it through the same
built-in source composer. Hardware comes from 2.4.2; process and the real
Snapmaker PLA Basic @U1 material retain their 2.2.4 project settings, including
65 C textured plate and 220 C nozzle temperatures for the actual default Textured PEI plate. The result records both
`process_source` and `material_source` provenance. Lumina does not store or
probe a compatibility file or select a special machine path.

**Snapmaker U1 兼容来源。** OrcaSlicer 2.4.2 提供精确的 U1 0.4 机器来源，但没有可用的原生工艺来源。完整材料目录中的 Snapmaker PLA @U1 纹理板温度为 0，
不能用于所选纹理板。
机器声明的 Snapmaker PLA 默认材料仅兼容 A250/A350。
FatCat 安装包保存来自 Orca 2.2.4 的完整兼容项目，由同一内置来源合成入口选择。
硬件使用 2.4.2 来源；工艺及实际 Snapmaker PLA Basic @U1 材料保留 2.2.4 项目原值，
包括纹理板 65°C、喷嘴 220°C。结果同时记录 `process_source` 和 `material_source`。Lumina 不保存或探测
兼容文件，也不选择机型特例路径。

**Flat puzzle backing.** Ordinary flat puzzles accept the selected sparse backing
infill and base layer-height modifier. Workers receive both values. The shared
merge path retains each source's Z ranges and remaps object/extruder identities;
viewing-surface protection stays at 100% while deep backing uses the chosen
density. Actual relief geometry still requires 100% backing.

**平面拼图底板。** 普通平面拼图保留用户选择的稀疏底板填充率和底板层高修改器。
Worker 接收两项参数，共用合并路径保留源 Z 区间并映射对象和挤出机身份。
观赏面保护区仍为 100%，深层底板使用所选填充率；实际浮雕几何仍要求 100%。
单块只使用全局调色板中的部分材料时，仅提供实际源槽位；缺失全局选择由 FatCat
通用来源合成入口补齐，用户材料温度、流量、工艺及未知字段继续取自实际源项目。

## User Project Templates

### PrusaSlicer 3 preview / Prusa 3 预览版

Select **PrusaSlicer 3.0.0-alpha13** in Settings, then the exact Prusa machine.
The 32 built-in device entries come from FatCat's public native catalogue, with
the native default 0.4 mm nozzle and sheet. They are not separate Lumina preset
copies. Ordinary single-material devices cannot print the four-material palette;
select an MMU or a multi-tool configuration with sufficient capacity.

The common writer follows FatCat's `geometry_layout=core` and fixed native slot
policy. Material-archive palettes do not remove physical MMU slots or XL tools.
Prusa layer ranges support backing layer height and infill. Merged exports
preserve source filament tuning and object/volume/range extruders; incompatible
project-wide differences are rejected. Native tower purge/ramming values and
cyclic transitions drive the existing placement calculation. Actual tower shape
still comes from the slicer.

Real TCP generation with the process worker pool and native GUI slicing were
observed for MMU3 single images, two-image batch, two-piece puzzle, XL 5T image,
material-archive image, and an imported user template. The template's GUI-exported G-code used 237°C and
0.91 extrusion multipliers. Other geometry workflows share this writer but have
not each been sliced with Prusa. Neither all machine/material combinations nor
physical printing are claimed. Prusa 2.x, SLA, other 3.x versions, mixed native
configuration containers and native hardware slot compaction remain unsupported.

设置中选择准确的 Prusa 设备。32 个内置设备来自 FatCat 公共原生目录；本体不再复制
一份逐机型预设。普通单材料设备用于四色会明确提示容量不足，多色需要 MMU 或足够的
打印头。保留真实硬件槽数、源耗材调校和局部层高；无法表示的合并差异明确拒绝。
以上代表样本已实际生成并在预览版切片，其他几何流程没有逐一验过，不声明全组合或
实体打印通过。

### Import and persistence / 导入与保存

In **Settings → Printer & Slicer → 3MF project template**, select the slicer that
saved your single-plate project, import its `.3mf`, and select a matching printer
and nozzle. The imported template is selected automatically. Choose **Use built-in
settings** to stop using it; **Delete template** removes the local saved settings.
FatCat validates and imports the project settings through the existing SDK entry;
Lumina stores them without copying the source geometry or adding another parser.

Image, vector, material-archive, large-format and model-surface exports pass the
selected template through the common writer. Batch, puzzle, calibration and swatch
generation reject a selected custom template explicitly; select built-in settings
for those workflows. A missing template or hardware/slicer mismatch is an error,
not permission to replace it with built-in settings.

Templates retain global tuning, including speed, temperature,
flow, retraction and cooling. Lumina applies its geometry-related layer, line-width,
wall, shell and infill values. Tower handling follows the automatic placement
option. Material slot tables are preserved or compacted according to the workflow.
Source geometry, per-object tuning and modifiers are not imported.

Template selection is saved in local and backend settings and in converter recipes.
Recipes carry a **device-local ID**, not the template file: on another device,
import the original project and select the new local template. The UI keeps an
unavailable selection visible instead of silently clearing it. Bug reports capture
the saved settings when available (up to 256 KiB); the reproduction loader does not
automatically reinstall that snapshot as a local template.

在 **设置 → 打印与切片 → 3MF 项目模板** 中，先选择保存原项目的切片软件，
导入单盘 `.3mf` 项目，并选择匹配的打印机和喷嘴。导入后自动选中模板；切换到
**使用内置配置** 可停用，**删除模板** 删除本机保存的设置。项目由 FatCat 的现有
入口校验和导入，Lumina 仅保存配置，不复制原模型，也不另建元数据解析器。

图像、矢量、材料档案、大幅分块及模型覆面导出使用同一个 writer 接收模板。
批量、拼图、校准和色块生成暂不支持自定义模板，会明确拒绝；请先切回内置配置。
模板缺失或机型、喷嘴、软件不匹配时会报错，不会静默替换成内置配置。

模板保留速度、温度、流量、回抽、冷却等全局调校，耗材槽表按生成流程保留或收紧；Lumina 根据模型需要
覆盖层高、线宽、墙层、顶底壳层及填充率，擦料塔遵循自动摆放选项。
原模型、原模型局部设置和修改器不导入。

模板选择会保存到本机、后端设置和转换分享配方。配方只带本机模板 ID，不携带
模板文件；换设备后需要导入原项目并重新选择。不可用的选择会保留并提示。
错误报告会尽力保存不超过 256 KiB 的模板设置快照，但复现加载器暂不自动安装该快照。

## Maintained Files

- `utils/fatcat_metadata.py`: public catalog lookup and the thin Lumina-to-FatCat adapter.
- `utils/bambu_3mf_writer.py`: single export, explicit user-template path, and final package writing.
- `utils/merged_bambu_3mf_writer.py`: source-project-preserving merged export.
- `core/machine_process_overlay.py`: explicit Lumina product process values; it does not load
  machine templates. Export code passes the explicit process values to FatCat.
- `core/puzzle_3mf.py`: one puzzle assembly entry using the shared merged writer;
  the caller supplies source material identities and Lumina-computed placement.
- `machine_registry/registry.json` and its plate assets: user-facing device choices and UI facts.
- `tools/machine_adapter/`: refreshes Lumina's picker registry from explicit local slicer
  sources; it does not produce 3MF project templates.
- FatCat's own `native_project_sources/` and target contracts: maintained in the FatCat
  repository and queried through its public Python/C++ entry points.

## Package Inspection

For Bambu-family 3MFs, inspect `Metadata/project_settings.config`,
`Metadata/model_settings.config`, `Metadata/slice_info.config`, and `3D/3dmodel.model`.
PrusaSlicer 3 uses `Metadata/PrusaSlicer3_project.json` and its native object/volume
metadata in `3D/3dmodel.model`; the Bambu-family settings files are not universal.
Check the selected machine/nozzle identity, source material identities and array shapes,
explicit process values, application/client version, and slicer-specific sidecars. For a
merge, compare edited source values and unknown fields with the final project settings.
For U1 0.4, confirm the retained project identifies Snapmaker U1 0.4 and keep its
OrcaSlicer 2.2.4 process and material provenance explicit. This branch uses the existing source-project
composer; it must not be reported as a project composed from an OrcaSlicer 2.4.2 native
process or material preset.

## Slicer Launch Isolation

Some slicers may rewrite a 3MF after opening it. `/api/slicer/launch` opens a temporary
copy under `output/temp/`, so the canonical export under `output/models/` is not mutated.

部分切片器打开 3MF 后可能会改写文件。`/api/slicer/launch` 会打开 `output/temp/` 下的临时副本，
`output/models/` 中的规范导出文件不会因此被改写。

## Base-plate Layer-Height Modifier / 底板层高修改器

### Motivation / 动机

For multi-color FDM prints, the solid-color base plate often dominates print
time while contributing nothing to color fidelity. Bambu-family slicers accept
a per-Z-range `layer_height` override via `Metadata/layer_config_ranges.xml`.
Lumina Studio targets half the nozzle diameter, then selects the nearest safe
height that lands exactly on the backing boundary and stays inside the selected
printer's limits. For a backing that starts on the build plate, the slicer's
fixed first-layer height is accounted for separately. Colored layers keep the
configured fine height. Relief exports skip this optimization because their
backing boundary can vary across the model, so one global Z range cannot be
proven safe; the writer emits no `layer_config_ranges.xml` when
`enable_relief=True`. Measured base-plate time savings for compatible flat
geometry are 40–60% depending on geometry.

对于多色 FDM 打印，纯色底板往往占据最大打印耗时，却对最终色彩效果
没有贡献。Bambu 系切片器支持通过 `Metadata/layer_config_ranges.xml`
按 Z 区间覆盖 `layer_height`。Lumina Studio 以喷嘴直径的一半为目标，随后
选择既能准确落在底板边界、又符合当前机型限制的最接近层高。底板贴着热床
时，切片器固定的首层层高会单独计入。彩色层仍保持原层高，底板耗时通常可
节省 40–60%。浮雕模型的底板边界可能随位置变化，无法证明单个全局 Z 区间
安全，因此浮雕会跳过这项优化；`enable_relief=True` 时 writer 不会生成
`layer_config_ranges.xml`。

### Formula / 计算规则

| Input / 输入 | Value / 值 |
|---|---|
| `target_layer_height` | `nozzle_diameter × 0.5` |
| Candidate grid / 候选网格 | `0.02 mm` increments / 以 `0.02 mm` 递增 |
| Backing above colours (`face=down`) / 底板在彩色层上方 | `base_height_mm % candidate == 0` |
| Backing on build plate (`face=up`) / 底板贴热床 | `(base_height_mm - initial_layer_print_height) % candidate == 0` |
| Printer bounds / 机型限制 | shared `min_layer_height` / `max_layer_height`, plus `candidate ≤ nozzle_diameter × 0.7` |
| Minimum backing layers / 最少底板层数 | two coarse layers for `face=down`; one fixed first layer + one coarse layer for `face=up` / `face=down` 至少两层粗层，`face=up` 至少一层固定首层加一层粗层 |
| Selection / 选择方式 | nearest to target; lower value wins a tie / 最接近目标，等距时取较小值 |
| `face=down`, `0.4` nozzle + `0.40` base | `0.20 mm` |
| `face=down`, `0.2` nozzle + `0.40` base | `0.10 mm` |
| `face=down`, `0.2` or `0.4` nozzle + `0.24` base | `0.12 mm` |
| `face=up`, `0.4` nozzle + `0.24` base + `0.08` first layer | `0.16 mm` after the `0.08 mm` first layer / `0.08 mm` 首层后使用 `0.16 mm` |
| `face=up`, `0.2` nozzle + `0.24` base + `0.08` first layer | skip (the required `0.16 mm` exceeds the printer limit) / 跳过（所需 `0.16 mm` 超出机型限制） |
| `base_height_mm` | `backing_layer_count × PrinterConfig.LAYER_HEIGHT` |
| `color_height_mm` | `num_color_layers × PrinterConfig.LAYER_HEIGHT` |

Z ranges emitted per `face_orientation`:

| Orientation / 朝向 | Condition / 判定 | Z range |
|---|---|---|
| `down` | Single-sided, non-5-Color-Extended / 单面且非 5-Color Extended | `[color_height_mm, color_height_mm + base_height_mm]` |
| `up` | 5-Color Extended (base on top) / 5-Color Extended（底板在顶部） | `[0, base_height_mm]` |
| `double` | Double-sided / 双面 | Skipped — colored layers exist on both sides / 跳过，正反两面都是彩色层 |

### Skip Conditions / 跳过条件

The writer skips emitting `layer_config_ranges.xml` when any of:

- toggle is off (`enable_base_layer_height_modifier=False`)
- relief is enabled (`enable_relief=True`), because a single global backing
  range could overlap variable-height optical layers
- `base_height_mm ≤ 0` (no backing)
- no `0.02 mm` candidate lands exactly on the backing boundary after accounting
  for the fixed first layer when applicable
- every divisible candidate is outside the selected printer's layer-height
  limits, is not coarser than the configured fine height, or would leave fewer
  than two backing layers
- `face_orientation == "double"`

Puzzle and batch assembly preserve source object-height ranges. The shared
merged writer remaps object indexes while XY placement leaves local Z unchanged.
拼图和批量装配保留源对象高度区间；共用合并 writer 重映射对象序号，XY 摆放不改变局部 Z。

### Example XML / 样例 XML

```xml
<?xml version="1.0" encoding="UTF-8"?>
<objects>
 <object id="1">
  <range min_z="2.4" max_z="3.2">
   <option opt_key="extruder">0</option>
   <option opt_key="layer_height">0.2</option>
  </range>
 </object>
</objects>
```

### End-to-end Wiring / 全链路

```
SettingsPanel (WikiTooltip + Switch)
  └─► settingsStore.enableBaseLayerHeightModifier
        └─► POST /api/system/settings  → user_settings.json
        └─► ConvertGenerateRequest.enable_base_layer_height_modifier
              └─► worker params dict
                    └─► core.converter.generate_final_model(...)
                          └─► pipeline ctx["enable_base_layer_height_modifier"]
                                ├─► raster/vector ctx guard disables it for relief
                                └─► core/pipeline/s09_export_3mf.py
                                      └─► export boundary rechecks enable_relief
                                            └─► utils/bambu_3mf_writer.export_scene_with_bambu_metadata
                                                  └─► writer omits LCR for enable_relief=True
                                                        └─► build_layer_config_ranges_xml (flat safe cases only)
```

Bambu geometry keys (`bambu_base_height_mm`, `bambu_color_height_mm`,
`bambu_face_orientation`) are populated by `core/pipeline/s06_voxel_building.py`
(raster) and `core/pipeline/coordinator.py::_update_bambu_base_layer_ctx_for_vector`
(vector). Both branches disable the modifier for relief, and the export/writer
boundary repeats that guard so a caller cannot accidentally emit a global LCR
for relief geometry.

几何相关的 Bambu 上下文键由 `s06`（光栅）和 `coordinator` 的
`_update_bambu_base_layer_ctx_for_vector`（矢量）统一写入。两条分支都会在浮雕
模式关闭修改器，导出与 writer 边界还会再次检查，避免任何调用方误给浮雕
写入全局 LCR 区间。

### Backing sparse-infill contract / 背板稀疏填充契约

`PrinterConfig.VIEWING_SURFACE_SOLID_DEPTH_MM` is the single project-level
source of truth for the protected viewing-surface depth (default `3.0 mm`).
The writer stores the requested deep-backing density in
`Metadata/project_settings.config` as `sparse_infill_density`, then adds
`sparse_infill_density=100%` object-height overrides to
`Metadata/layer_config_ranges.xml` for the protected zones. The range builder
splits overlaps with the existing coarse `layer_height` override into sorted,
non-overlapping ranges.

`PrinterConfig.VIEWING_SURFACE_SOLID_DEPTH_MM` 是观赏面保护深度的唯一项目级
配置来源，默认值为 `3.0 mm`。writer 把用户选择的深层底板填充率写入
`Metadata/project_settings.config` 的 `sparse_infill_density`，再通过
`Metadata/layer_config_ranges.xml` 为观赏面保护区覆盖
`sparse_infill_density=100%`。区间构建器会把该覆盖与已有的粗层高覆盖拆分为
按 Z 排序且互不重叠的区间。

| Orientation / 朝向 | Protected solid range / 实心保护区 |
|---|---|
| `down` | `[0, color_height + solid_depth]` |
| `up` | `[base_height - solid_depth, base_height + color_height]` |
| `double` | Both viewing-side ranges; overlapping ranges are merged / 两侧观赏面区间，相交时合并 |

If the complete backing fits inside the protected depth (or inside both depths
for a double-sided model), the effective global density is promoted to `100%`
and no density-only range is needed. Sparse relief is rejected because its
variable backing boundary cannot be protected by a single global Z range.
Raster, vector, native large-format, batch, and puzzle exports forward the same
density and geometry context. The shared merged writer remaps the one-based
model-object indexes while preserving source local height ranges.

当整块底板不超过保护深度（双面模型则不超过两侧保护深度之和）时，实际全局
填充率会提升为 `100%`，无需额外的密度区间。浮雕底板边界随位置变化，无法用
单一全局 Z 区间可靠保护，因此稀疏浮雕会被拒绝。光栅、矢量、原生大画幅、
批量和拼图导出统一透传密度与几何上下文，共用合并 writer 重映射从 1 开始的
模型对象序号并保留源对象局部高度区间。

### Turning it Off / 关闭方式

- UI: **Settings → Slicer Settings → Base-plate layer-height modifier**（仅当
  所选切片器属于 Bambu 家族时可见）
- Programmatic: send `enable_base_layer_height_modifier=false` in
  `POST /api/convert/generate`
- Config: set `"enable_base_layer_height_modifier": false` in `user_settings.json`

Bambu-family slicer IDs (see `frontend/src/utils/settingsOptionIds.ts`):
`BambuStudio`, `OrcaSlicer`, `SnapmakerOrca`, `ElegooSlicer`,
`AnycubicSlicerNext`, `FlashStudio`, `QIDIStudio`.

### Regression Tests / 回归测试入口

- `tests/test_bambu_layer_config_ranges_unit.py` — formula + XML shape +
  end-to-end writer produces valid XML
- `tests/test_pipeline_bambu_base_layer_ctx_unit.py` — raster/vector ctx
  derivation
- `tests/test_s09_export_3mf_unit.py` — s09 forwards ctx to writer and
  falls back to safe defaults
- `tests/test_puzzle_3mf_unit.py` — combined puzzle preserves source-local
  `Metadata/layer_config_ranges.xml` with remapped object indexes
- `tests/test_converter_generate_unit.py::TestConverterEntryAcceptsBaseLayerModifierKwarg`
  — signature contract (prevents API↔worker kwargs drift)
- `tests/test_bambu_3mf_writer_unit.py` — writer-level kwargs plumbing
- `tests/test_backing_infill_contract_unit.py` — 10 mm boundary, canonical
  solid depth, orientation ranges, thin-backing promotion, and generated 3MF
  process metadata
- `frontend/src/components/__tests__/SettingsPanel.baseLayerHeightModifier.test.tsx`
  — UI gating by slicer family + translation assertions
- `frontend/src/__tests__/settingsOptionIds.test.ts` — `isBambuFamilySlicer`
  canonicalization

**Native material and plate support.** The bundled catalogue includes complete
machine-compatible material candidates, resolved through their unchanged native
inheritance. Selection also checks the actual active plate, including an omitted
plate's source default. Native zero plate temperatures mean unsupported; they
are not replaced with invented temperatures. The test matrix checks both
supported compositions and precise rejection of unsupported active combinations.
Imported unused material tails retain their source settings even when their
material would be unsupported as an active native selection on that plate.
Exact nondefault SnapmakerOrca nozzle sources and FlashStudio 0.25 mm use their
actual compatible native materials; OrcaSlicer 2.4.2 U1 0.6 mm has no PLA source.

**Legacy merged calls.** Calls that omit `metadata_target` infer their exact
existing machine/nozzle identity from the source project before using the same
FatCat export path. An omitted plate keeps the imported project's actual plate.
Structural relationships and content types follow the current FatCat dialect;
geometry, UUID, Z-range, process and material preservation remain checked.
