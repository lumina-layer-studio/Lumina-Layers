# 编辑提交、预览与生成

本说明覆盖颜色替换、配方、选区、撤销/重做和生成之间的状态契约。
前端保存用户输入并编排请求；已提交作品由服务端现有 session、preview cache、
replacement history 和持久 mask 共同承载。PNG、GLB、图层预览是派生工件。
提交回执与请求队列不另存一套作品或历史。

用户级撤销由 [documentHistory](../../../frontend/src/stores/converter/documentHistory.ts)
串联换图片、参数和服务端编辑。文档步骤保留输入与会话引用；像素、配方和选区步骤
调用现有服务端历史，不能用旧快照覆盖递增版本。没有会话时，换色和清空换色也进入
文档历史。滑动手势合并为一步，但不能跨越保存点；打开工程和恢复草稿建立新的历史
基线，撤销回到保存点时恢复“已保存”。历史最多保留80步、4个编辑会话和256MiB输入。

## 版本与操作各自负责什么

| 标识 | 用途与归属 |
| --- | --- |
| `operation_id` | 标识一次内容操作；丢失响应后查询同一个操作，不能重放 undo/redo/toggle |
| `editor_content_revision` / selection 文档中的 `content_revision` | 服务端确认的作品内容版本；前端不能自行 `+1` |
| `selection_revision` | 共享选区版本；选区改变和作品内容改变是不同事件 |
| preview request revision、session、epoch | 丢弃旧请求对当前页面的写入；取消请求不证明服务端没有提交 |
| GLB token/CAS | 只让匹配当前内容的派生预览发布，不能替代内容提交确认 |

同 session 的内容操作在第一次 `await` 前同步占位并串行执行。
选区变更等待内容提交；依赖选区的编辑和生成等待选区提交。
旧响应无论成功或失败，若可能已在服务端执行，都对账原 operation receipt，
不能直接覆盖新页面，也不能仅靠丢弃响应解除提交屏障。

选区文档中的 mask、并集轮廓、计数和历史可用状态来自同一次服务端确认。
画布、调色板和渐变面板的选择都进入选区队列；前端不自行增加选区版本，
也不拼接单块轮廓作为权威并集。点选立即用本地像素显示独立视觉草稿，允许确认前
暂时出现相邻块共边；确认文档与对应待处理手势同时更新，剩余手势按顺序重放到
新文档的显示层，全部确认后只显示并集外框。视觉草稿不修改版本、历史或编辑目标。
明确的“取消选择”使用幂等移除，点选手势才使用切换；
多笔刷草稿保留笔画边界，一次应用合并各笔命中的区域并记录一个历史步骤。

有效的选中、取消、清空和内容编辑按发生顺序进入同一历史，内容编辑保留先前的
选区步骤。撤销/重做恢复像素和选区快照，同时发布新的单调选区版本；快照中的
旧版本不复用。无变化操作不新增历史，也不丢弃可重做步骤。历史仍受现有容量
预算限制。切换选择工具保持当前 mask，后续替色始终作用于该 mask。

## 回执与响应丢失

接口是 `GET /api/convert/editor-commit/{session_id}/{operation_id}`，
由 [editor_commit.py](../../../api/editor_commit.py) 管理每个 session 最近
64 条确认记录。重复 operation id 在写缓存、历史和会话前被拒绝为 409，
调用方应查询原回执。

| 状态 | 客户端行为 |
| --- | --- |
| `committed` | 先应用完整业务结果投影，再同步权威内容/选区版本并释放屏障 |
| `failed` | 确认尚未发布；恢复该操作保存的旧状态，允许后续编辑 |
| `pending` / `unknown` / 查询失败 | 保留草稿与错误上下文，暂停依赖编辑、选区和生成，等待显式同步 |

单色、批量和自动渐变换色共用完整映射提交流程，在取得队列执行权后再计算新映射。
即时失败与延迟失败使用同一份回滚记录，恢复映射、本地兼容历史和先前导出入口。
请求失败后先进入未知状态再查询回执，避免临时改色被上一笔“已提交”状态误记成撤销步骤。

已知内容操作的 committed 回执若缺少业务结果，也不能只改版本号就解除屏障。
业务投影包括预览 URL、替换区域、配方、自由色、计数、基础层参数、动态结果和
undo/redo 标志；不复制 RGB 数组、mask、cache manifest 或 history checkpoint。
回执数量有界不等于业务列表可以截断：129 项列表必须保留第 129 项及对应计数。
响应模型中的可选 `null` 表示未提供，空列表表示明确清空；reset 的明确清空语义单独保留。
选区文档补读失败不能反过来否定已经确认的内容提交。

## 发布与回滚边界

[replace.py](../../../api/routers/converter/replace.py) 复用现有缓存事务，
按 `replacement_history_lock -> selection lock` 顺序协调 session 内的修改。
提交前失败可以恢复工作副本；`cache.commit()` 成功后事务的 `published` 标记
同时保护内存和 artifact-backed 缓存，不能再恢复旧数组或旧会话字段。
发布后历史、回执或派生阶段失败时，保留已发布作品和真实确认状态：未收敛的操作保持
pending/unknown，已发布的 committed 回执不伪报失败。非 200 响应不等于已经回滚。

GLB 调度在内容回执之后执行。GLB 失败只记录派生错误，并由既有 token/CAS
阻止旧结果发布；不能撤销二维内容、材料矩阵、配方或历史，也不要求生成等待无关 GLB。

## 配方的空间目标与基础输入

已应用配方使用应用时保存的 `recipe_override_applied_masks` 位压缩快照，
由 [selection_state.py](../../../api/selection_state.py) 的
`resolve_recipe_override_masks` 统一解析。具备快照键的 session 若 mask 缺失、为空、
损坏或形状不匹配，必须明确失败；不得改用后续临时选区或扩大为全图。
只有没有快照键的旧 session 才使用现有兼容路径。

配方增层属于 `recipe_overrides` 派生状态，不写回基础 `color_layers` /
`layer_height_mm`，避免自动预览重建 session 并清空编辑。
真实来源、几何、基础输入变化仍触发原预览失效；生成通过既有配方层数解析取得实际层数。
Escape 关闭颜色二维子页本身不承担作品回滚，没有证据支持把它改成清空编辑。

## 生成快照与下载

JSON 项目和 PNG 分享卡的 v5 格式可内嵌 `asset.editor`。它复用既有
replacement history 快照及 session 编解码，保存可编辑 RGB、材料层矩阵、
原始基线、实际应用的区域配方蒙版和当前选区；原图或 SVG 仍单独保存在
`asset.primary`，不以预览截图代替。快照不包含旧会话文件路径、GLB 或 pickle。
单个压缩快照及解压数据上限均为 512 MiB。

保存等待选区和内容提交确认，再以两种 revision 捕获快照；自定义配方对话框
也使用相同提交入口。导入先从源文件重建新预览，校验工作源文件的 SHA-256、
网格尺寸、物理宽度、像素比例、建模模式、耗材通道及实体蒙版，
复用既有 checkpoint 恢复后才公开新会话。新会话重新建立内容代次，不能要求旧代次
编号相同。缺少实际应用蒙版的旧项目继续明确提示，不能凭区域 ID 猜回蒙版。
源文件改名不影响校验；裁剪和旋转后的实际工作文件内容必须匹配。校验失败发生在
提交和修改新会话之前。耗材档案仍绑定原始材料通道，编辑新增的内部通道或配方不参与
来源身份校验，避免拒绝正常的编辑恢复。
恢复回执复用普通内容提交的状态映射，与新会话一次发布；二维稳定底图和当前预览
都取已编辑 RGBA，不能再被初始预览的 `preview_raw_url` 覆盖。未恢复编辑的普通预览
仍使用原始 RGBA 底图，上传原图对照及临时高亮继续保留各自语义。

标准、拼图和大画幅生成复用
[generate.py](../../../api/routers/converter/generate.py) 的快照规则：

1. 在 session 的 history/selection 短锁内校验客户端的两种 revision，并捕获完整输入。
2. 独立复制可变输入；缓存工件路径保持引用，数组与嵌套编辑字段不与实时 session 混用。
3. 锁外组装参数，worker 入队前和完成后再次检查内容/选区版本；真实过期请求仍返回 409。
4. 只把匹配输入版本的成功文件注册为当前结果；响应携带实际使用的版本。

最终 `.3mf`、`.zip`、导出配方和分享卡属于 TTL 下载，使用独立注册身份，
关闭或切换源 session 后仍应可下载。PNG、GLB、中间数组可以随 session 清理。
下载后的中间文件清理保留当前编辑缓存 manifest、撤销历史及解析后的 SVG 来源引用，
继续编辑、保存项目和生成分享卡仍可使用；真正关闭源会话时才释放这些引用。
内容提交成功会清除当前打开切片软件的旧产物快捷入口，但不会删除已注册的 TTL 下载。
本次生成失败不能发布新成功下载，也不能删除用户此前的成功作品和下载。

擦料塔自动摆放优先预留完整 brim，并搜索水平/垂直长条和目标支持的塔形状。
完整 brim 估算在床边放不下时，继续求解模型实体和塔的布局：仍保留两者之间
完整 brim 的间距，只将床边实际 brim 范围交给原生切片确认。可用布局会应用模型
平移与塔参数，并标记 `model_brim_requires_review`，不把它当成全部验证通过。
模型实体和塔也无法安排或缺少打印区域时，仍生成工程并保留原生塔参数，
不应用失败候选。两种情况均保留材料、工艺、模型尺寸和原有 brim 设置。
沿用 `wipe_tower_manual_adjustment_required` 警告贯穿工程元数据、生成响应和下载界面。
分盘 ZIP 汇总内含各个原生 3MF 的警告；下载成功不表示已经验证可打印。
当前布局估算使用轴对齐包围盒，自动 brim 的真实切片占地由原生切片决定。
需在切片软件中逐个检查工程；原生耗材/板型错误和实际写包失败仍是生成错误。

S06 中浮雕、掐丝、五色朝上或磁铁孔槽加工失败通过现有阶段错误出口终止；
所选高度图读取失败或缺失也不能被平面模型替代。普通平面入口和兼容分支优先级保持独立。

## 维护与验证入口

- 前端编排：[converter store](../../../frontend/src/stores/converter/store.ts)、
  [editorRevision](../../../frontend/src/stores/converter/editorRevision.ts)、
  [previewCommitGuard](../../../frontend/src/stores/converter/previewCommitGuard.ts)。
- 回执与发布行为：[editor commit tests](../../../tests/test_editor_commit_unit.py)、
  [真实替色 endpoint tests](../../../tests/test_converter_replace_integration_unit.py)、
  [配方 tests](../../../tests/test_converter_recipe_override_unit.py)。
- 生成输入、旧下载与阶段失败：[生成 tests](../../../tests/test_converter_generate_unit.py)、
  [S06 tests](../../../tests/test_s06_failure_unit.py)。
- 前端受控时序：[回执对账](../../../frontend/src/__tests__/converter-store-commit-reconciliation.test.ts)、
  [选区竞态](../../../frontend/src/__tests__/converter-store-selection-race.test.ts)、
  [生成版本](../../../frontend/src/__tests__/converter-store-generate-revision-sync.test.ts)。

验证必须比较 session、RGB/材料矩阵、mask、历史和版本，不能只检查 HTTP 200 或 PNG。
回归场景包括 A 区域配方后改选非重叠 B、响应丢失、提交前失败、发布后失败、连续编辑、
编辑期间生成及源 session 关闭后下载。前端测试通过 `python scripts/run_vitest.py` 运行。
本地确定性证据不能证明所有现场生成错误具有同一根因；现场诊断仍需要 request/session、
operation id、内容/选区版本、提交阶段、HTTP 状态与对应素材，参见
[日志指南](../../logging-guide.md)。
