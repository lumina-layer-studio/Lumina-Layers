# layout_new.py 渐进式重构工作计划

## TL;DR

> **Quick Summary**: 以 `ui/layout_new.py` 为核心，在严格“行为不变”前提下执行 TDD 驱动的小步重构；先补表征测试，再按最小改动拆分结构与职责。  
> **Deliverables**:
> - `ui/layout_new.py` 重构后结构（可读性更高、职责更清晰）
> - 必要的直接依赖文件最小联动改动（仅白名单）
> - 覆盖关键行为冻结点的新增/更新测试
>
> **Estimated Effort**: Medium  
> **Parallel Execution**: YES - 3 waves  
> **Critical Path**: Task 1 -> Task 2 -> Task 4 -> Task 6

---

## Context

### Original Request
对 `layout_new.py` 进行重构，使架构合理、代码清晰。

### Interview Summary
**Key Discussions**:
- 行为必须严格保持不变（不可引入功能/输出变化）。
- 允许调整 `layout_new.py` 的直接依赖少量文件。
- 采用“渐进式小步重构”。
- 测试策略确定为 TDD。
- 硬性回归门禁：`pytest -m unit`、`pytest -m integration`、`pytest -m e2e`。

**Research Findings**:
- `main.py` 依赖 `create_app` 与 `HEADER_CSS`（高风险接口点）。
- `ui/__init__.py` 对外 re-export `create_app`（公开契约点）。
- 现有测试覆盖 smoke/e2e 主流程，但 helper/内部逻辑隔离测试不足。
- `pytest.ini` + `tests/` 结构已具备，不需要先建测试框架。

### Metis Review
**Identified Gaps (addressed)**:
- 补充“行为冻结清单”作为首任务，避免“重构=重写”。
- 明确白名单改动边界，防止 scope creep。
- 将“事件绑定语义”纳入新增测试断言，而非仅看 UI 存在性。
- 验收标准全部改为 agent 可执行命令，不依赖人工目测。

---

## Work Objectives

### Core Objective
在不改变外部行为的前提下，提升 `ui/layout_new.py` 的可维护性与可读性，并建立足够的自动化护栏确保安全重构。

### Concrete Deliverables
- `ui/layout_new.py`：按职责分段并减少单函数复杂度（保持公开接口不变）。
- 必要时新增/调整直接依赖文件（白名单内）。
- 新增表征测试，覆盖关键结构、事件 wiring、核心 helper 行为。

### Definition of Done
- [x] 回归门禁全绿：`pytest -m unit -q`、`pytest -m integration -q`、`pytest -m e2e -q`
- [x] `create_app`、`HEADER_CSS`、`ui.__all__` 对外契约保持可用且行为一致
- [x] 新增测试能捕获 tab 结构、关键控件、关键事件绑定语义回归

### Must Have
- TDD（RED-GREEN-REFACTOR）节奏执行。
- 仅做小步、可回滚改动，每步都可验证。
- 公开 API 形态不变：`create_app` 导出路径与可调用性保持。

### Must NOT Have (Guardrails)
- 不改业务功能与用户可感知行为。
- 不进行无关模块清理、全局格式化、跨模块“大抽象升级”。
- 不变更 `main.py` 与 `ui/__init__.py` 的现有导入/导出契约（除非最小兼容性修复且有测试证明）。

---

## Verification Strategy (MANDATORY)

> **UNIVERSAL RULE: ZERO HUMAN INTERVENTION**  
> 所有验收均由 agent 直接执行，不需要人工点击或目测。

### Test Decision
- **Infrastructure exists**: YES
- **Automated tests**: TDD
- **Framework**: pytest (+ pytest-cov, playwright 已存在)

### If TDD Enabled
每个重构任务按 RED-GREEN-REFACTOR 执行：
1. **RED**: 先补失败的表征测试（锁定行为）
2. **GREEN**: 最小代码改动使测试通过
3. **REFACTOR**: 整理结构，保持测试全绿

### Agent-Executed QA Scenarios (global gates)

Scenario: 全量回归门禁
  Tool: Bash
  Preconditions: Python 环境与依赖已安装，项目根目录可执行 pytest
  Steps:
    1. Run: `pytest -m unit -q`
    2. Assert: exit code = 0 且输出包含 `failed=0` 或无失败摘要
    3. Run: `pytest -m integration -q`
    4. Assert: exit code = 0 且输出无失败
    5. Run: `pytest -m e2e -q`
    6. Assert: exit code = 0 且输出无失败
  Expected Result: 三层测试均通过
  Failure Indicators: 任一命令非 0 或出现 FAILED
  Evidence: `.sisyphus/evidence/gate-pytest-{unit|integration|e2e}.log`

Scenario: 公开契约一致性检查
  Tool: Bash
  Preconditions: 代码可 import
  Steps:
    1. Run: `python -c "import ui, main; from ui.layout_new import create_app, HEADER_CSS; assert callable(create_app); assert isinstance(HEADER_CSS, str) and len(HEADER_CSS)>0; assert hasattr(ui, 'create_app'); print('ok')"`
    2. Assert: stdout 包含 `ok`
  Expected Result: 对外契约仍可用
  Failure Indicators: ImportError / AssertionError
  Evidence: `.sisyphus/evidence/contract-check.log`

---

## Execution Strategy

### Parallel Execution Waves

Wave 1 (Start Immediately):
- Task 1: 行为冻结清单 + 基线断言
- Task 3: helper 函数候选测试点盘点（只读分析）

Wave 2 (After Wave 1):
- Task 2: create_app / tab 结构表征测试（TDD RED->GREEN）
- Task 4: helper 关键逻辑表征测试（TDD RED->GREEN）

Wave 3 (After Wave 2):
- Task 5: `layout_new.py` 小步重构（结构拆分/函数提取）
- Task 6: 直接依赖文件最小联动与最终回归

Critical Path: Task 1 -> Task 2 -> Task 5 -> Task 6

### Dependency Matrix

| Task | Depends On | Blocks | Can Parallelize With |
|------|------------|--------|----------------------|
| 1 | None | 2,5 | 3 |
| 2 | 1 | 5 | 4 |
| 3 | None | 4 | 1 |
| 4 | 3 | 5 | 2 |
| 5 | 2,4 | 6 | None |
| 6 | 5 | None | None |

### Agent Dispatch Summary

| Wave | Tasks | Recommended Agents |
|------|-------|--------------------|
| 1 | 1, 3 | `task(category="quick", load_skills=["git-master"], run_in_background=false)` |
| 2 | 2, 4 | `task(category="unspecified-high", load_skills=["git-master"], run_in_background=false)` |
| 3 | 5, 6 | `task(category="unspecified-high", load_skills=["git-master"], run_in_background=false)` |

---

## TODOs

- [x] 1. 建立行为冻结清单与基线门禁

  **What to do**:
  - 从现有入口与测试提炼“不可变行为”清单：公开 API、tab 顺序/可见性、关键按钮与状态流。
  - 明确白名单改动范围：`ui/layout_new.py`、`main.py`、`ui/__init__.py`、相关测试文件。
  - 执行一次现状门禁并保存日志作为基线证据。

  **Must NOT do**:
  - 不修改生产代码行为。
  - 不新增无关测试目标。

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 主要是规则固化与基线验证，复杂度低。
  - **Skills**: [`git-master`]
    - `git-master`: 保障变更边界、便于后续小步提交。
  - **Skills Evaluated but Omitted**:
    - `playwright`: 本任务无需浏览器交互。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 3)
  - **Blocks**: 2, 5
  - **Blocked By**: None

  **References**:
  - `ui/layout_new.py` - 核心重构目标与行为源头。
  - `main.py` - 入口对 `create_app` / `HEADER_CSS` 的依赖契约。
  - `ui/__init__.py` - 对外导出契约。
  - `tests/integration/test_app_smoke.py` - `create_app` 最小 smoke 基线。
  - `tests/e2e/test_gradio_playwright.py` - 当前 UI/E2E 行为基线。
  - `pytest.ini` - marker 与测试分层命令依据。

  **Acceptance Criteria**:
  - [x] 生成行为冻结清单文档并纳入任务上下文。
  - [x] `pytest -m unit -q` / `pytest -m integration -q` / `pytest -m e2e -q` 基线日志可追溯。

  **Agent-Executed QA Scenarios**:
  ```text
  Scenario: 基线门禁成功采集
    Tool: Bash
    Preconditions: 仓库依赖可运行 pytest
    Steps:
      1. 执行 `pytest -m unit -q`
      2. 执行 `pytest -m integration -q`
      3. 执行 `pytest -m e2e -q`
      4. 将输出分别保存为 .sisyphus/evidence/task-1-{unit|integration|e2e}.log
    Expected Result: 三个命令均 exit code 0
    Failure Indicators: 任一命令失败或日志缺失
    Evidence: .sisyphus/evidence/task-1-*.log

  Scenario: 门禁失败时中断（负向）
    Tool: Bash
    Preconditions: 任一测试失败（真实失败场景）
    Steps:
      1. 运行失败命令并捕获返回码
      2. 断言返回码非 0
      3. 记录失败摘要到 .sisyphus/evidence/task-1-fail.log
    Expected Result: 流程被标记为 blocked，不进入后续重构
    Evidence: .sisyphus/evidence/task-1-fail.log
  ```

- [x] 2. 为 app 结构与事件 wiring 增加表征测试（TDD）

  **What to do**:
  - RED：新增/扩展针对 `create_app` 与各 tab 构建函数的结构/绑定断言。
  - GREEN：只做最小调整使测试通过（如测试夹具、断言位置校正）。
  - REFACTOR：整理测试命名和夹具复用，保持语义清晰。

  **Must NOT do**:
  - 不通过 mock 掩盖真实 wiring 问题。
  - 不把行为测试退化成“仅检查对象类型”。

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需要深入理解 Gradio 组件结构与事件绑定语义。
  - **Skills**: [`git-master`]
    - `git-master`: 保持测试增量原子化，便于定位回归。
  - **Skills Evaluated but Omitted**:
    - `playwright`: 此任务以 pytest 结构断言为主。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Task 4)
  - **Blocks**: 5
  - **Blocked By**: 1

  **References**:
  - `ui/layout_new.py` - `create_app` 与 `create_*_tab_content` 定义。
  - `tests/integration/test_app_smoke.py` - 现有 smoke 断言入口。
  - `tests/e2e/test_gradio_playwright.py` - 现有 tab/交互行为断言样式。
  - `tests/conftest.py` - 公共 fixture 模式。

  **Acceptance Criteria**:
  - [ ] 新增测试先失败（RED），再通过（GREEN）。
  - [x] 覆盖至少：tab 顺序/可见性、关键按钮存在、关键事件触发路径。
  - [x] `pytest -m unit -q` 与 `pytest -m integration -q` 通过。

  **Agent-Executed QA Scenarios**:
  ```text
  Scenario: 结构表征测试 RED->GREEN
    Tool: Bash
    Preconditions: 新增/修改了 layout 结构测试
    Steps:
      1. 先运行目标测试 `pytest -q -k "layout_new and (app or tab)"`
      2. RED 阶段断言存在失败
      3. 完成最小实现/测试调整后再次运行同命令
      4. 断言全部通过
    Expected Result: 同一批用例完成 RED->GREEN 闭环
    Evidence: .sisyphus/evidence/task-2-red-green.log

  Scenario: 事件 wiring 回归（负向）
    Tool: Bash
    Preconditions: 事件绑定语义被误改时
    Steps:
      1. 运行 `pytest -q -k "layout_new and wiring"`
      2. 断言失败信息指向触发次数/绑定缺失
    Expected Result: 用例可侦测 wiring 语义漂移
    Evidence: .sisyphus/evidence/task-2-wiring-fail.log
  ```

- [x] 3. helper 与私有函数测试点清单化（只读分析 + 用例设计）

  **What to do**:
  - 识别高价值 helper：尺寸计算、预览缩放、i18n 文本更新、LUT 读写。
  - 形成最小必要测试矩阵（正常/异常输入）。

  **Must NOT do**:
  - 不提前修改 helper 实现。

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: 主要是测试设计与覆盖映射。
  - **Skills**: [`git-master`]
    - `git-master`: 便于后续拆分为小提交。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 1)
  - **Blocks**: 4
  - **Blocked By**: None

  **References**:
  - `ui/layout_new.py` - helper 函数定义与边界条件。
  - `tests/unit` - 单测目录与风格基线。

  **Acceptance Criteria**:
  - [ ] 输出 helper 测试矩阵（函数 x 场景 x 断言）。
  - [ ] 至少覆盖 1 个负向场景（非法输入/缺失文件/空值）。

  **Agent-Executed QA Scenarios**:
  ```text
  Scenario: helper 覆盖矩阵生成
    Tool: Bash
    Preconditions: 已完成函数盘点
    Steps:
      1. 汇总 helper 名称与场景到 markdown
      2. 运行 `python -c "from ui import layout_new; print('ok')"` 验证目标可导入
    Expected Result: 矩阵文件完整且函数可定位
    Evidence: .sisyphus/evidence/task-3-matrix.md

  Scenario: 缺失负向用例拦截（负向）
    Tool: Bash
    Preconditions: 矩阵未包含负向项
    Steps:
      1. 审核矩阵中 negative 列
      2. 若为空则任务失败并记录
    Expected Result: 至少 1 条负向场景被要求补充
    Evidence: .sisyphus/evidence/task-3-negative-check.log
  ```

- [x] 4. helper 关键路径补齐表征测试（TDD）

  **What to do**:
  - RED：先写 helper 关键路径失败用例（尺寸计算、i18n 更新、LUT 持久化边界）。
  - GREEN：修正测试夹具/调用方式使其通过（不改行为语义）。
  - REFACTOR：减少重复 fixture 与断言样板。

  **Must NOT do**:
  - 不引入与重构无关的新功能断言。

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 需平衡私有实现可测性与行为冻结。
  - **Skills**: [`git-master`]
    - `git-master`: 管理测试改动节奏。

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Task 2)
  - **Blocks**: 5
  - **Blocked By**: 3

  **References**:
  - `ui/layout_new.py` - helper 函数与返回约定。
  - `tests/conftest.py` - 文件/路径类 fixture 复用。
  - `requirements-test.txt` - pytest 生态约束。

  **Acceptance Criteria**:
  - [x] 关键 helper 的 RED->GREEN 证据可追溯（测试日志）。
  - [x] `pytest -m unit -q` 全绿。

  **Agent-Executed QA Scenarios**:
  ```text
  Scenario: helper 单测 RED->GREEN
    Tool: Bash
    Preconditions: 新增 helper 测试已写入
    Steps:
      1. 运行 `pytest -q -k "layout_new and helper"`
      2. 记录 RED 失败日志
      3. 完成最小改动后重跑同命令
      4. 断言通过
    Expected Result: helper 行为冻结完成
    Evidence: .sisyphus/evidence/task-4-red-green.log

  Scenario: 输入边界异常（负向）
    Tool: Bash
    Preconditions: 提供空值/非法尺寸/缺失文件场景
    Steps:
      1. 运行 `pytest -q -k "layout_new and (invalid or missing or edge)"`
      2. 断言异常路径按预期处理
    Expected Result: 异常路径可被自动化验证
    Evidence: .sisyphus/evidence/task-4-negative.log
  ```

- [x] 5. 执行 `layout_new.py` 小步重构（结构清晰化）

  **What to do**:
  - 仅做行为等价的结构重排：函数提取、块拆分、命名清晰化（保持外部接口）。
  - 每次只做一种重构动作，动作后立即运行局部+unit/integration 回归。
  - 优先降低 `create_app` 的认知负担，明确“构建/绑定/状态”分段。

  **Must NOT do**:
  - 不改变 `create_app` 对外签名。
  - 不改变 `HEADER_CSS` 外部可用性。
  - 不进行大范围跨文件重构。

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 主重构任务，风险最高。
  - **Skills**: [`git-master`]
    - `git-master`: 原子化提交与回退友好。
  - **Skills Evaluated but Omitted**:
    - `frontend-ui-ux`: 本任务不涉及视觉改版。

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential
  - **Blocks**: 6
  - **Blocked By**: 2, 4

  **References**:
  - `ui/layout_new.py` - 主体重构文件。
  - `main.py` - 入口依赖验证点。
  - `ui/__init__.py` - API 导出一致性。
  - `tests/integration/test_app_smoke.py` - 入口可创建性回归。
  - `tests/e2e/test_gradio_playwright.py` - 用户流程与控件可用性回归。

  **Acceptance Criteria**:
  - [x] 所有新增/既有相关测试通过。
  - [ ] 局部重构后无 API 破坏。
  - [ ] 重构提交可按小步回溯（每步均有测试证据）。

  **Agent-Executed QA Scenarios**:
  ```text
  Scenario: 单步重构后快速回归
    Tool: Bash
    Preconditions: 完成一次单一动作重构（如函数提取）
    Steps:
      1. 运行 `pytest -q -k "layout_new"`
      2. 运行 `pytest -m unit -q`
      3. 断言均通过后再进行下一步重构
    Expected Result: 每步重构都可验证且可继续
    Evidence: .sisyphus/evidence/task-5-step-*.log

  Scenario: API 契约破坏检测（负向）
    Tool: Bash
    Preconditions: 若误改导出/签名
    Steps:
      1. 运行契约检查命令
      2. 断言失败时立即停止并回滚到上一步
    Expected Result: API 破坏被立刻阻断
    Evidence: .sisyphus/evidence/task-5-contract-fail.log
  ```

- [x] 6. 最小联动依赖校准 + 全链路回归收口

  **What to do**:
  - 若重构导致直接依赖文件需要最小调整，仅限白名单文件。
  - 执行完整门禁并保存证据。
  - 复核“Must NOT Have”无违反项。

  **Must NOT do**:
  - 不新增 CI/文档扩展等本次范围外工作。

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: 最终收口阶段，需要高置信验证。
  - **Skills**: [`git-master`]
    - `git-master`: 确保收口提交干净、可审计。

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Sequential
  - **Blocks**: None
  - **Blocked By**: 5

  **References**:
  - `main.py` - 对外入口联动检查。
  - `ui/__init__.py` - 对外导出联动检查。
  - `pytest.ini` - 分层门禁命令来源。

  **Acceptance Criteria**:
  - [x] `pytest -m unit -q` 通过
  - [x] `pytest -m integration -q` 通过
  - [x] `pytest -m e2e -q` 通过
  - [x] 契约检查命令输出 `ok`

  **Agent-Executed QA Scenarios**:
  ```text
  Scenario: 全链路收口回归成功
    Tool: Bash
    Preconditions: 所有代码改动已完成
    Steps:
      1. 依次执行 unit/integration/e2e 三条门禁命令
      2. 执行契约检查 python 命令
      3. 汇总输出到 .sisyphus/evidence/task-6-final.log
    Expected Result: 全部通过并可交付
    Evidence: .sisyphus/evidence/task-6-final.log

  Scenario: e2e 失败阻断发布（负向）
    Tool: Bash
    Preconditions: e2e 存在失败
    Steps:
      1. 执行 `pytest -m e2e -q`
      2. 断言非 0 返回码
      3. 标记任务未完成，不允许收口
    Expected Result: 失败时流程停止
    Evidence: .sisyphus/evidence/task-6-e2e-fail.log
  ```

---

## Commit Strategy

| After Task | Message | Files | Verification |
|------------|---------|-------|--------------|
| 2 | `test(layout): add characterization tests for app and tabs` | `tests/...` | `pytest -m unit -q && pytest -m integration -q` |
| 4 | `test(layout): add helper-level regression coverage` | `tests/...` | `pytest -m unit -q` |
| 5 | `refactor(layout): simplify layout_new structure without behavior change` | `ui/layout_new.py` (+ whitelist files if needed) | `pytest -m unit -q && pytest -m integration -q` |
| 6 | `chore(layout): finalize compatibility and full regression pass` | minimal whitelist files | `pytest -m unit -q && pytest -m integration -q && pytest -m e2e -q` |

---

## Success Criteria

### Verification Commands
```bash
pytest -m unit -q
pytest -m integration -q
pytest -m e2e -q
python -c "import ui, main; from ui.layout_new import create_app, HEADER_CSS; assert callable(create_app); assert isinstance(HEADER_CSS, str) and len(HEADER_CSS)>0; assert hasattr(ui, 'create_app'); print('ok')"
```

### Final Checklist
- [x] All Must Have present
- [x] All Must NOT Have absent
- [x] TDD evidence recorded for key tasks
- [x] Public API contract unchanged
- [x] Regression gates all green
