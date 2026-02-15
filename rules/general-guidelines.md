## General Guidelines

- Gradio 单选框（`Radio`）涉及业务枚举值时，`choices` 的 value 必须使用 `Enum.value`；后端入口收到前端参数后必须第一时间转换为对应 `Enum`，后续流程统一用 `Enum` 判断，禁止继续用字符串包含/相等判断。

### Skill Loading (Mandatory)

- 涉及 i18n 文案链路（新增/修改按钮、状态文案、错误提示、core->ui 返回文案）时，必须先加载并遵循：`.agents/skills/i18n-status-bridge/SKILL.md`。
- 未加载该 skill 前，不得改动 `core/` 与 `ui/` 的文案传递逻辑。
- 若当前任务仅为纯算法/纯数据处理且不影响用户可见文本，可不加载该 skill。

## Testing Requirements

### 测试框架
- 使用 pytest 作为测试框架
- 测试文件位于 `tests/` 目录下：
  - `tests/unit/` - 单元测试
  - `tests/integration/` - 集成测试
  - `tests/e2e/` - 端到端测试（使用 playwright）

### 测试标记
- `@pytest.mark.unit` - 单元测试（快速运行，无外部依赖）
- `@pytest.mark.slow` - 慢速测试（需要 `--runslow` 参数才运行）
- 测试默认跳过 slow 标记的测试

### 测试运行
```bash
# 运行所有测试（不包括 slow）
pytest

# 运行所有测试（包括 slow）
pytest --runslow

# 运行特定测试文件
pytest tests/unit/test_converter_core_flow.py

# 运行特定测试函数
pytest tests/unit/test_converter_core_flow.py::test_convert_image_to_3d_dispatches_vector_svg_flow
```

### 测试规范
- 所有测试必须使用 UTF-8 编码（conftest.py 已自动设置）
- 使用 fixtures 来管理测试数据（如 `temp_lut_file`）
- 端到端测试必须使用 playwright 进行浏览器自动化
- 集成测试可以启动 Gradio 服务器进行测试
- 单元测试不得启动服务器或使用外部依赖

### 测试数据
- 测试数据文件应放在 `tests/` 目录下
- 使用 `tmp_path` fixture 创建临时文件
- 测试结束后自动清理临时文件


