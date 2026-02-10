# High-Fidelity 新增 ΔE2000 映射策略工作计划

## TL;DR

> **Quick Summary**: 在不破坏现有 RGB 欧式匹配路径的前提下，仅为 High-Fidelity 模式新增一个可切换的 ΔE2000 感知映射策略，并以 NumPy 向量化 + 候选筛选控制性能。
>
> **Deliverables**:
> - High-Fidelity 可切换匹配策略（`MatchStrategy.RGB_EUCLIDEAN` / `MatchStrategy.DELTAE2000`）
> - UI 新增匹配策略选项（仅 High-Fidelity 生效）
> - ΔE2000 向量化匹配实现（唯一色批处理）
> - 代理可执行 QA 场景与性能/稳定性验收脚本化流程
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: 任务1 → 任务2 → 任务4 → 任务6

---

## Context

### Original Request
当前软件在 LUT 映射时使用 RGB 欧式距离，实测视觉效果不佳（会选到“数值近但观感更差”的颜色）。目标是寻找更符合人眼观感的映射方法。

### Interview Summary
**Key Discussions**:
- 用户确认采用 **新增策略并存**（不替换旧方案），便于兼容与 A/B 对比。
- 首轮范围仅限 **High-Fidelity**（不触达 Pixel/Vector）。
- 方向选择为 **全量 ΔE2000**，并强调尽可能使用 **NumPy 向量化**。
- 测试策略选择：暂不建设自动化测试基建，以代理执行 QA 场景为主。

**Research Findings**:
- 当前核心映射路径在 `core/image_processing_factory/processing_modes.py`，High-Fidelity 与 Pixel 均基于 `kdtree.query`（RGB 欧式）。
- LUT 构建在 `core/image_processing_factory/color_modes.py`，目前统一 `KDTree(lut_rgb)`。
- 现有高保真性能骨架（唯一色匹配 + 编码回填）可保留，仅替换匹配度量层。

### Metis Review
**Identified Gaps (addressed)**:
- 缺少可执行边界：本计划明确“默认行为不变、仅 High-Fidelity 生效、禁止顺带改 Pixel/Vector”。
- 缺少量化验收：本计划加入兼容性、功能性、质量性、性能性、稳定性、异常路径验收。
- 缺少稳定性约束：增加 tie-break 规则（ΔE 并列时索引最小优先）确保可复现。

---

## Work Objectives

### Core Objective
在 High-Fidelity 中新增感知色差映射能力，显著改善 LUT 匹配观感，同时保持旧路径兼容与可回退。

### Concrete Deliverables
- High-Fidelity 匹配策略参数（默认旧策略，显式切换新策略）。
- Image Converter UI 新增“匹配策略”控件，并将选项透传到 High-Fidelity 处理链。
- ΔE2000 批量匹配模块（输入唯一色集合，输出 LUT 索引）。
- 代理执行 QA 验收清单（命令/预期/证据路径）。

### Definition of Done
- [x] 默认不传新参数时，输出与旧版本一致（像素级一致）。
- [x] 显式启用 `MatchStrategy.DELTAE2000` 时，流程可跑通并输出有效 3MF 预览链路。
- [x] 在固定样本集上，相比 `rgb_euclidean` 的平均感知误差统计改善。
- [x] 性能在目标样本上满足预算（见默认策略）。

### Must Have
- 新旧策略并存且可切换。
- UI 中可显式选择匹配策略（默认旧策略）。
- 匹配策略参数必须使用 `Enum` 传递（定义于 `config.py`，风格参考 `ModelingMode`）。
- 仅改 High-Fidelity 路径。
- NumPy 向量化实现为主，不引入 Python 嵌套大循环。

### Must NOT Have (Guardrails)
- 不修改 Pixel / Vector 映射逻辑。
- 不引入新的测试框架与大规模重构。
- 不在本轮引入 ICC/CAT/白点适配/色域惩罚（仅保留扩展点）。

---

## Verification Strategy (MANDATORY)

> **UNIVERSAL RULE: ZERO HUMAN INTERVENTION**
>
> 所有任务验收必须由执行代理自动完成，禁止“人工看图确认”。

### Test Decision
- **Infrastructure exists**: NO
- **Automated tests**: None（本轮不新增测试基建）
- **Framework**: none

### Agent-Executed QA Scenarios (MANDATORY — ALL tasks)

每个任务都必须包含：
- Happy path（正常输入）
- Negative path（异常/边界输入）
- 证据产物保存到 `.sisyphus/evidence/`

---

## Execution Strategy

### Parallel Execution Waves

Wave 1 (Start Immediately):
- Task 1: 设计策略开关与边界
- Task 3: 构建样本与基线采集脚本（不改生产逻辑）

Wave 2 (After Wave 1):
- Task 2: 新增 ΔE2000 匹配模块（向量化）
- Task 4: High-Fidelity 接入新策略

Wave 3 (After Wave 2):
- Task 5: 回归兼容与异常路径
- Task 6: 质量/性能/稳定性总验收

Critical Path: Task 1 → Task 2 → Task 4 → Task 6

### Dependency Matrix

| Task | Depends On | Blocks | Can Parallelize With |
|------|------------|--------|---------------------|
| 1 | None | 2,4 | 3 |
| 2 | 1 | 4,6 | None |
| 3 | None | 6 | 1 |
| 4 | 1,2 | 5,6 | None |
| 5 | 4 | 6 | None |
| 6 | 2,3,4,5 | None | None |

### Agent Dispatch Summary

| Wave | Tasks | Recommended Agents |
|------|-------|-------------------|
| 1 | 1,3 | `task(category="quick", load_skills=["frontend-ui-ux"], run_in_background=false)` |
| 2 | 2,4 | `task(category="unspecified-high", load_skills=["frontend-ui-ux"], run_in_background=false)` |
| 3 | 5,6 | `task(category="quick", load_skills=["playwright"], run_in_background=false)` |

---

## TODOs

- [x] 1. 设计 High-Fidelity 匹配策略开关（并存，不替换）

  **What to do**:
  - 在 `config.py` 新增 `MatchStrategy` 枚举（`str, Enum`），命名与方法风格对齐 `ModelingMode`。
  - UI 控件与处理链仅传递 `MatchStrategy`（或其 `.value`），禁止裸字符串在多处散落。
  - 在 High-Fidelity 入口增加 `match_strategy`（`MatchStrategy.RGB_EUCLIDEAN` / `MatchStrategy.DELTAE2000`）。
  - 在 Image Converter 的 UI 增加“匹配策略”选项控件（推荐 Radio/Dropdown）。
  - 仅当 modeling mode = High-Fidelity 时启用该控件；其他模式隐藏或禁用并给出说明。
  - 将 UI 选择值透传到 `process_image(...)` 调用链。
  - 默认值保持 `rgb_euclidean`，确保旧行为不变。
  - 明确非法策略名错误信息与回退规则。

  **Must NOT do**:
  - 不改 Pixel/Vector 的函数签名与调用逻辑。

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 局部接口扩展，范围清晰。
  - **Skills**: `frontend-ui-ux`
    - `frontend-ui-ux`: 用于保持参数暴露与现有 UI 结构一致性。
  - **Skills Evaluated but Omitted**:
    - `playwright`: 本任务不涉及浏览器交互验收。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 3)
  - **Blocks**: 2, 4
  - **Blocked By**: None

  **References**:
  - `config.py` - `ModelingMode` 枚举实现参考；新增 `MatchStrategy` 应放在同级配置区域。
  - `core/image_processing_factory/processing_modes.py` - High-Fidelity/Pixel/Vector 策略主入口，新增开关应优先落在 High-Fidelity 分支。
  - `core/image_processing.py` - `process_image(...)` 参数透传入口，决定策略参数如何注入。
  - `core/converter.py` - 预览与导出调用链路入口，确保策略可从业务流被触发。
  - `core/converter.py` - Gradio 控件定义与事件绑定位置（UI 选项新增与可见性控制）。

  **Acceptance Criteria**:
  - [ ] `MatchStrategy` 在 `config.py` 中定义完成，类型与 `ModelingMode` 一致（`str, Enum`）。
  - [ ] UI 到处理链传参使用 `MatchStrategy`，无跨模块裸字符串分支判断。
  - [ ] UI 出现“匹配策略”控件，默认值为 `MatchStrategy.RGB_EUCLIDEAN`。
  - [ ] 切换到 Pixel/Vector 时控件不可用（隐藏或禁用）且不会影响输出。
  - [ ] 默认不传 `match_strategy` 时，行为与当前版本一致。
  - [ ] 传 `match_strategy=MatchStrategy.DELTAE2000` 时，高保真路径进入新分支。
  - [ ] 传非法值时返回可预测错误（含允许值提示）。

  **Agent-Executed QA Scenarios**:

  ```bash
  Scenario: 默认策略保持旧行为
    Tool: Bash (python)
    Preconditions: 示例输入图与 LUT 可用
    Steps:
      1. 运行高保真预览一次（不传 match_strategy）
      2. 记录 matched_rgb 哈希到 .sisyphus/evidence/task-1-default-hash.txt
      3. 在同提交重复执行一次并比较哈希
    Expected Result: 两次哈希完全一致
    Failure Indicators: 哈希不一致或报错
    Evidence: .sisyphus/evidence/task-1-default-hash.txt

  Scenario: 非法策略名
    Tool: Bash (python)
    Preconditions: 同上
    Steps:
      1. 调用 match_strategy="invalid_strategy"
      2. 捕获异常文本
      3. 校验异常中包含允许值列表
    Expected Result: 明确报错且不中断进程状态
    Evidence: .sisyphus/evidence/task-1-invalid-strategy.txt

  Scenario: UI 控件可见性与透传
    Tool: Playwright (playwright skill)
    Preconditions: Gradio 服务运行
    Steps:
      1. 打开 Image Converter 页面
      2. 选择 High-Fidelity，确认“匹配策略”控件可见且默认 `MatchStrategy.RGB_EUCLIDEAN`
      3. 切换为 Pixel/Vector，确认控件隐藏或禁用
      4. 切回 High-Fidelity，选择 `MatchStrategy.DELTAE2000` 并生成预览
      5. 断言后端日志/状态反映已使用 `MatchStrategy.DELTAE2000`
    Expected Result: 控件行为与透传一致
    Evidence: .sisyphus/evidence/task-1-ui-strategy-control.png
  ```

  **Commit**: YES
  - Message: `feat(high-fidelity): add pluggable LUT match strategy switch`

---

- [x] 2. 实现 ΔE2000 向量化匹配模块（唯一色批处理）

  **What to do**:
  - 新增独立 matcher：输入 `unique_colors` 与 `lut_rgb`，输出每个唯一色对应 LUT 索引。
  - 优先采用 NumPy 向量化实现 ΔE2000 核心计算。
  - 增加并列 tie-break：ΔE 相同/极近时索引最小优先。
  - 允许候选优化扩展点（本轮默认全量比较，保留 TopK 钩子）。

  **Must NOT do**:
  - 不改 LUT 文件格式与 `ref_stacks` 结构。

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 数值算法实现 + 性能约束。
  - **Skills**: `frontend-ui-ux`
    - `frontend-ui-ux`: 通用 Python 结构实现能力（无更贴切算法 skill 可用）。
  - **Skills Evaluated but Omitted**:
    - `playwright`: 非 UI 算法实现。

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2
  - **Blocks**: 4, 6
  - **Blocked By**: 1

  **References**:
  - `core/image_processing_factory/processing_modes.py` - 当前 unique-color 映射位置，需替换/扩展其中匹配步骤。
  - `core/image_processing_factory/helpers.py` - `ColorMatcher.match_colors` 的可复用匹配抽象点。
  - `requirements.txt` - 已有 `colormath` 依赖可作对照/回退实现参考（本轮首选 NumPy 向量化）。

  **Acceptance Criteria**:
  - [ ] 对 N 个 unique colors 返回 N 个合法 LUT 索引。
  - [ ] 同输入重复运行，索引结果完全一致。
  - [ ] 计算逻辑无 Python 双层像素循环（以向量化为主）。

  **Agent-Executed QA Scenarios**:

  ```bash
  Scenario: 向量化匹配输出形状与索引合法
    Tool: Bash (python)
    Preconditions: 准备一组 unique_colors 与 lut_rgb
    Steps:
      1. 调用 deltae2000 matcher
      2. 断言输出长度 == unique_colors 数量
      3. 断言所有索引在 [0, len(lut_rgb)-1]
    Expected Result: 全部断言通过
    Evidence: .sisyphus/evidence/task-2-shape-index.txt

  Scenario: 并列 tie-break 稳定性
    Tool: Bash (python)
    Preconditions: 构造两条 ΔE 极近候选 LUT
    Steps:
      1. 连续执行 5 次同输入匹配
      2. 比较输出索引序列
    Expected Result: 5 次完全一致
    Evidence: .sisyphus/evidence/task-2-tiebreak-stability.txt
  ```

  **Commit**: YES
  - Message: `feat(color): add numpy-vectorized deltae2000 unique-color matcher`

---

- [x] 3. 建立基线采集脚本化流程（兼容/质量/性能）

  **What to do**:
  - 固定样本集（至少 3 张：人像/高饱和插画/低对比照片）。
  - 采集旧策略基线：输出耗时、结果哈希、感知误差统计基准。
  - 定义统一 evidence 命名规范。

  **Must NOT do**:
  - 不引入测试框架（pytest 等）。

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `frontend-ui-ux`
  - **Skills Evaluated but Omitted**:
    - `playwright`: 本任务可用 shell/python 完成。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 1)
  - **Blocks**: 6
  - **Blocked By**: None

  **References**:
  - `.sisyphus/drafts/HighFidelityStrategy_doc.md` - 已记录的问题背景与目标。
  - `core/converter.py` - 可复用现有预览生成调用链作为采样入口。

  **Acceptance Criteria**:
  - [ ] 形成 baseline 证据文件（旧策略）不少于 3 组。
  - [ ] 每组包含：耗时、输出哈希、统计摘要。

  **Agent-Executed QA Scenarios**:

  ```bash
  Scenario: 基线采集完整性
    Tool: Bash (python)
    Preconditions: 样本图和 LUT 可访问
    Steps:
      1. 对 3 张样本逐一运行旧策略
      2. 记录每次耗时与输出哈希
      3. 写入 .sisyphus/evidence/task-3-baseline-summary.json
    Expected Result: JSON 含 3 组完整记录
    Evidence: .sisyphus/evidence/task-3-baseline-summary.json
  ```

  **Commit**: YES
  - Message: `chore(qa): add baseline capture workflow for high-fidelity mapping`

---

- [x] 4. 在 High-Fidelity 主流程接入新 matcher（不破坏旧路径）

  **What to do**:
  - 在 unique-color 匹配处按 `match_strategy` 分派：
    - `MatchStrategy.RGB_EUCLIDEAN`: 保持 `kdtree.query` 现状
    - `MatchStrategy.DELTAE2000`: 走新向量化 matcher
  - 保留现有编码回填 (`np.searchsorted`) 机制。
  - 确保 `material_matrix` 与 `matched_rgb` 输出契约不变。

  **Must NOT do**:
  - 不修改 quantization/滤波参数默认行为。

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: `frontend-ui-ux`
  - **Skills Evaluated but Omitted**:
    - `playwright`: 该任务主要是后端处理链。

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2
  - **Blocks**: 5, 6
  - **Blocked By**: 1, 2

  **References**:
  - `core/image_processing_factory/processing_modes.py` - High-Fidelity 唯一色匹配与回填主逻辑。
  - `core/image_processing.py` - 参数透传与结果包装契约。
  - `core/image_processing_factory/helpers.py` - 可选抽象复用位置。

  **Acceptance Criteria**:
  - [ ] 新旧策略都能输出 `(matched_rgb, material_matrix, quantized_image, debug_data)`。
  - [ ] 默认策略输出与基线一致（同输入同参数）。
  - [ ] 新策略输出可生成后续预览与建模流程所需数据。

  **Agent-Executed QA Scenarios**:

  ```bash
  Scenario: 新旧策略 A/B 可切换
    Tool: Bash (python)
    Preconditions: 固定输入样本
    Steps:
      1. 运行 match_strategy=MatchStrategy.RGB_EUCLIDEAN，保存哈希A
      2. 运行 match_strategy=MatchStrategy.DELTAE2000，保存哈希B
      3. 断言两次都成功返回完整结果字段
    Expected Result: A/B 均成功，且输出结构一致
    Evidence: .sisyphus/evidence/task-4-ab-structure.txt

  Scenario: 默认兼容性
    Tool: Bash (python)
    Preconditions: 已有 task-3 baseline
    Steps:
      1. 不传 match_strategy 运行
      2. 与 baseline 哈希比较
    Expected Result: 哈希一致
    Evidence: .sisyphus/evidence/task-4-default-compat.txt
  ```

  **Commit**: YES
  - Message: `feat(high-fidelity): wire deltae2000 matcher with legacy fallback`

---

- [x] 5. 异常与边界路径收敛

---

- [x] 6. 最终质量/性能/稳定性验收与结论输出

  **What to do**:
  - 对样本集执行 A/B：旧策略 vs 新策略。
  - 产出统计：平均 ΔE、P95 ΔE、总耗时比、重复运行一致性。
  - 形成结论报告，给出“是否默认切换”的建议（本轮仍默认旧策略）。

  **Must NOT do**:
  - 不修改默认策略值（除非用户后续明确要求）。

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: `playwright`, `frontend-ui-ux`
    - `playwright`: 验证前端预览路径在两策略下均可用。
    - `frontend-ui-ux`: 产出结构化比较报告。
  - **Skills Evaluated but Omitted**:
    - 无

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3
  - **Blocks**: None
  - **Blocked By**: 2,3,4,5

  **References**:
  - `core/converter.py` - 预览入口与状态信息输出。
  - `core/image_processing.py` - 主处理链产物。
  - `.sisyphus/evidence/task-3-baseline-summary.json` - 基线对照。

  **Acceptance Criteria**:
  - [ ] 兼容性：默认策略输出哈希与 baseline 一致。
  - [ ] 功能性：`MatchStrategy.DELTAE2000` 策略可稳定运行并产出完整结果。
  - [ ] 质量性：样本集 `mean ΔE` 或 `P95 ΔE` 至少一项优于旧策略。
  - [ ] 性能性：新策略总耗时不超过旧策略 **2.5x**（默认阈值，可后续调）。
  - [ ] 稳定性：同输入重复 3 次，输出哈希一致。

  **Agent-Executed QA Scenarios**:

  ```bash
  Scenario: 端到端 A/B 统计对比
    Tool: Bash (python)
    Preconditions: 3 张固定样本 + 固定 LUT
    Steps:
      1. 对每张图跑 MatchStrategy.RGB_EUCLIDEAN，记录耗时/哈希/统计
      2. 对每张图跑 MatchStrategy.DELTAE2000，记录同指标
      3. 聚合输出 compare_report.json
    Expected Result: 报告包含质量与性能对比字段
    Evidence: .sisyphus/evidence/task-6-compare-report.json

  Scenario: UI 预览链路可用性
    Tool: Playwright (playwright skill)
    Preconditions: Gradio 服务可访问
    Steps:
      1. 打开页面并进入 Image Converter
      2. 分别选择两种策略生成预览
      3. 断言预览区域出现并截图
    Expected Result: 两种策略都可生成预览
    Evidence: .sisyphus/evidence/task-6-ui-ab-preview.png
  ```

  **Commit**: YES
  - Message: `docs(qa): add ab verification report for high-fidelity deltae2000 strategy`

---

## Commit Strategy

| After Task | Message | Files | Verification |
|------------|---------|-------|--------------|
| 1 | `feat(high-fidelity): add pluggable LUT match strategy switch` | processing entry files | default compatibility check |
| 2 | `feat(color): add numpy-vectorized deltae2000 unique-color matcher` | matcher module | shape/index/stability checks |
| 3 | `chore(qa): add baseline capture workflow for high-fidelity mapping` | qa scripts/evidence schema | baseline JSON generated |
| 4-5 | `feat/fix(high-fidelity): wire and harden deltae2000 path` | high-fidelity path | A/B + edge checks |
| 6 | `docs(qa): add ab verification report for high-fidelity deltae2000 strategy` | evidence/report docs | compare report complete |

---

## Success Criteria

### Verification Commands
```bash
python main.py  # Expected: app starts without strategy-related errors
```

```bash
python -m core.converter  # Expected: processing pipeline callable in current environment
```

```bash
python <qa_ab_script>.py  # Expected: generates .sisyphus/evidence/task-6-compare-report.json
```

### Final Checklist
- [x] All Must Have present
- [x] All Must NOT Have absent
- [x] Default behavior unchanged
- [x] New strategy can be enabled explicitly
- [x] Evidence files generated for all key QA scenarios
