---
name: testing-framework
description: 所有测试相关任务（编写测试、修改测试、运行测试、调试测试失败）必须遵循本技能规范。每次进行代码修改后都需要根据本技能进行测试。
allowed-tools: Read, Grep, Edit, Write, Bash, LSP, Glob
---

# testing-framework

## 目标
确保 Lumina Studio 的测试编写遵循统一规范和最佳实践。

## 何时必须加载
- 编写新的测试（单元测试/集成测试/E2E测试）
- 修改现有测试逻辑
- 调试测试失败
- 运行测试并验证结果
- 涉及测试框架配置的修改

## 测试框架概览

### 核心技术栈
- **pytest >= 8.0.0** - 主要测试框架
- **pytest-cov >= 5.0.0** - 代码覆盖率工具
- **playwright >= 1.48.0** - 浏览器E2E测试

### 测试文件结构
```
tests/
├── unit/              # 单元测试（快速，无外部依赖）
├── integration/       # 集成测试（可启动Gradio服务器）
├── e2e/              # 端到端测试（浏览器自动化）
└── conftest.py       # pytest fixtures配置
```

## 测试标记系统

### 标记定义
- `@pytest.mark.unit` - 单元测试（快速运行，无外部依赖）
- `@pytest.mark.slow` - 慢速测试（需要 `--runslow` 参数才运行）
- `@pytest.mark.integration` - 集成测试
- `@pytest.mark.e2e` - 端到端测试

### 默认行为
- 测试默认跳过 `slow` 标记的测试
- 运行slow测试需要显式指定 `--runslow` 参数

## 测试编写规范

### 1. UTF-8 编码
所有测试自动使用UTF-8编码（conftest.py已自动设置），无需手动处理。

### 2. Fixtures 使用
**优先复用现有fixtures**（在 `conftest.py` 中定义）：
- `temp_lut_file` - 临时LUT文件
- `free_port` - 获取可用端口
- `temp_cwd` - 临时工作目录
- `tmp_path` - pytest内置临时目录

### 3. 测试分层原则

#### 单元测试（tests/unit/）
- **禁止**启动服务器或使用外部依赖
- **禁止**网络请求
- **必须**快速运行（< 1秒）
- 使用mock隔离外部依赖

示例：
```python
@pytest.mark.unit
def test_patch_asscalar():
    class Dummy:
        def item(self):
            return 42
    assert main.patch_asscalar(Dummy()) == 42
```

#### 集成测试（tests/integration/）
- 可以启动Gradio服务器（使用 `free_port` fixture）
- 可以测试API端点
- 使用真实依赖但控制范围

示例：
```python
@pytest.mark.integration
def test_gradio_api_endpoints(free_port: int):
    # 启动服务器并测试API
    pass
```

#### E2E测试（tests/e2e/）
- **必须**使用playwright进行浏览器自动化
- 测试完整用户流程
- 可以标记为 `slow`

示例：
```python
@pytest.mark.e2e
@pytest.mark.slow
def test_converter_workflow_with_real_backend(page):
    # 浏览器自动化测试完整流程
    pass
```

## 测试运行命令

```bash
# 运行所有快速测试（不包括slow）
pytest

# 运行所有测试（包括slow）
pytest --runslow

# 运行特定测试文件
pytest tests/unit/test_converter_core_flow.py

# 运行特定测试函数
pytest tests/unit/test_converter_core_flow.py::test_convert_image_to_3d_dispatches_vector_svg_flow

# 运行特定标记的测试
pytest -m unit
pytest -m integration
pytest -m "not slow"

# 查看测试覆盖率
pytest --cov=. --cov-report=html
```

## 测试数据管理

### 临时文件
- **优先使用** `tmp_path` fixture创建临时文件
- 测试结束后自动清理
- 避免硬编码路径

```python
def test_with_temp_file(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_text("content")
    # 测试逻辑...
    # 自动清理
```

### 持久化测试数据
- 测试数据文件应放在 `tests/` 目录下
- 使用相对路径引用

## 强制规则

1. **单元测试不得启动服务器** - 违反测试分层原则
2. **必须使用UTF-8编码** - conftest.py已自动设置，但需确保遵循
3. **E2E测试必须使用playwright** - 不得使用其他浏览器自动化工具
4. **slow测试必须标记** - 防止CI/CD变慢
5. **优先复用fixtures** - 不要重复造轮子

## Do / Don't

### Do
```python
@pytest.mark.unit
def test_fast_computation():
    # 纯计算逻辑，快速运行
    assert add(1, 2) == 3

@pytest.mark.slow
def test_full_workflow():
    # 需要启动服务器的完整测试
    pass
```

### Don't
```python
# ❌ 单元测试启动服务器
@pytest.mark.unit
def test_something():
    server = start_gradio()  # 错误！

# ❌ 硬编码编码处理
def test_with_encoding():
    with open("file.txt", encoding="utf-8") as f:  # 不需要，conftest已设置
        pass

# ❌ slow测试没有标记
def test_slow_operation():
    time.sleep(100)  # 需要添加 @pytest.mark.slow
```

## 调试测试失败

### 步骤
1. **查看详细输出**：`pytest -vv`
2. **只运行失败的测试**：`pytest --lf`
3. **进入pdb调试**：在测试中添加 `import pdb; pdb.set_trace()` 或使用 `pytest --pdb`
4. **查看print输出**：`pytest -s`

### 常见问题
- **端口冲突**：使用 `free_port` fixture
- **编码错误**：确认conftest.py的 `force_utf8_env` fixture生效
- **临时文件未清理**：使用 `tmp_path` 而非手动创建

## 提交前检查清单

- [ ] 新测试文件放在正确的目录（unit/integration/e2e）
- [ ] 添加了适当的pytest标记（unit/slow/integration/e2e）
- [ ] 单元测试无外部依赖（无服务器/网络）
- [ ] E2E测试使用了playwright
- [ ] 优先使用现有fixtures（temp_lut_file, free_port等）
- [ ] slow测试已标记，不会影响默认测试运行
- [ ] 测试通过：`pytest`（快速测试）和 `pytest --runslow`（全部测试）
- [ ] 代码覆盖率没有降低（或降低有合理原因）

## 参考文件

### 配置文件
- `pytest.ini` - pytest配置
- `conftest.py` - 全局fixtures
- `requirements-test.txt` - 测试依赖

### 示例测试
- `tests/unit/test_main.py` - 单元测试示例
- `tests/integration/test_gradio_api.py` - 集成测试示例
- `tests/e2e/test_gradio_playwright.py` - E2E测试示例

### 相关文档
- `rules/general-guidelines.md` - 项目通用规范
- `README.md` - 项目文档
