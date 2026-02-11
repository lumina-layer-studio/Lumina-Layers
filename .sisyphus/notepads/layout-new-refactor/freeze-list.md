# 行为冻结清单 (Behavior Freeze List)

> **重构基线** - 本清单记录 `ui/layout_new.py` 在重构前的所有不可变行为。
> **创建时间**: 2026-02-11 (Task 1)
> **适用范围**: layout-new-refactor 计划

---

## 1. 公开 API 契约（不可变）

### 1.1 `create_app()` 函数

**当前签名**:
```python
def create_app() -> gr.Blocks:
    """Create and return the main Gradio application."""
```

**不可变行为**:
- [x] 返回类型必须为 `gr.Blocks` 实例
- [x] 必须初始化以下状态变量：
  - `lang_state: gr.State` - 语言状态（"zh" 或 "en"）
  - `theme_state: gr.State` - 主题状态（True 为深色，False 为浅色）
- [x] 必须创建 4 个主标签页，顺序固定：
  1. 图像转换 (Converter Tab)
  2. 校准板生成 (Calibration Tab)
  3. 颜色提取 (Extractor Tab)
  4. 关于 (About Tab)
- [x] 必须包含全局事件绑定：
  - `change_language` - 语言切换按钮点击
  - `on_clear_cache` - 清除缓存按钮点击
  - `on_reset_counters` - 重置计数器按钮点击

### 1.2 `HEADER_CSS` 常量

**当前定义**:
```python
HEADER_CSS = """
/* Header 区域样式 */
#header-container {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    ...
}
"""
```

**不可变行为**:
- [x] 必须保持为字符串类型
- [x] 必须可从 `ui.layout_new` 导入
- [x] CSS 内容字节级一致

### 1.3 `ui.__init__.py` 导出

**当前导出**:
```python
from .layout_new import create_app

__all__ = ["create_app"]
```

**不可变行为**:
- [x] 必须导出 `create_app` 函数
- [x] `__all__` 必须包含 `create_app`

### 1.4 `main.py` 依赖

**当前导入契约**:
```python
# Line 36
from ui.layout_new import create_app

# Line 79
from ui.layout_new import HEADER_CSS

# Line 91
css=CUSTOM_CSS + HEADER_CSS
```

**不可变行为**:
- [x] `create_app` 必须可调用且返回 `gr.Blocks`
- [x] `HEADER_CSS` 必须可访问且为非空字符串

---

## 2. Tab 结构与顺序（不可变）

### 2.1 Tab 创建顺序

`create_app()` 中的 Tab 创建顺序（从左到右）：

**Tab 顺序 (严格不变)**:
1. **Converter** (id=0) - 💎 图像转换 / Image Converter
2. **Calibration** (id=1) - 📐 校准板生成 / Calibration
3. **Extractor** (id=2) - 🎨 颜色提取 / Color Extractor
4. **About** (id=3) - ℹ️ 关于 / About

### 2.2 Tab 构建函数签名

| 函数 | 签名 | 返回值 |
|------|------|--------|
| `create_converter_tab_content()` | `(lang: str, lang_state: gr.State) -> dict` | 组件字典 |
| `create_calibration_tab_content()` | `(lang: str) -> dict` | 组件字典 |
| `create_extractor_tab_content()` | `(lang: str) -> dict` | 组件字典 |
| `create_about_tab_content()` | `(lang: str) -> dict` | 组件字典 |

---

## 3. 关键按钮与状态流（不可变）

### 3.1 Converter Tab 关键按钮

| 按钮标签（中文） | 按钮功能 | 事件绑定 |
|----------------|----------|----------|
| "👁️ 生成预览" | 生成 3D 预览 | `generate_preview_cached_with_fit` |
| "🚀 生成 3MF" | 生成 3MF 模型 | `process_batch_generation` |
| "清除替换" | 清除颜色替换历史 | `on_clear_color_replacements_with_fit` |
| "撤销替换" | 撤销最后一次颜色替换 | `on_undo_color_replacement_with_fit` |
| "启用挂孔" | 启用钥匙圈挂孔（复选框） | - |
| "批量模式" | 切换批量/单图模式 | `toggle_batch_mode` |

### 3.2 Calibration Tab 关键按钮

| 按钮标签（中文） | 按钮功能 | 事件绑定 |
|----------------|----------|----------|
| "📐 生成校准板" | 生成校准板 3MF | `generate_board_wrapper` |

### 3.3 Extractor Tab 关键按钮

| 按钮标签（中文） | 按钮功能 | 事件绑定 |
|----------------|----------|----------|
| "🎨 提取颜色" | 从照片提取颜色数据 | `ext_event` |

### 3.4 全局功能按钮

| 按钮标签（中文） | 按钮功能 | 事件绑定 |
|----------------|----------|----------|
| "🌐 中文/English" | 切换语言 | `change_language` |
| "🗑️ 清除缓存" | 清除 Gradio 缓存 | `on_clear_cache` |
| "🔄 重置计数器" | 重置统计计数器 | `on_reset_counters` |

---

## 4. 模块级常量（不可变）

| 常量名 | 类型 | 用途 |
|--------|------|------|
| `HEADER_CSS` | `str` | Header 样式 |
| `LUT_GRID_CSS` | `str` | LUT 色块网格样式 |
| `PREVIEW_ZOOM_CSS` | `str` | 预览缩放样式 |
| `LUT_GRID_JS` | `str` | LUT 色块选择 JavaScript |
| `PREVIEW_ZOOM_JS` | `str` | 预览缩放 JavaScript |
| `CONFIG_FILE` | `str` | 配置文件名 ("user_settings.json") |

---

## 5. Helper 函数签名（内部重构可改，但签名保持）

| 分类 | 函数名 | 当前签名 |
|------|--------|----------|
| **LUT 读写** | `load_last_lut_setting()` | `() -> str \| None` |
| | `save_last_lut_setting()` | `(lut_name: str \| None) -> None` |
| **尺寸计算** | `_get_image_size()` | `(img) -> tuple[int, int] \| None` |
| | `calc_height_from_width()` | `(width: float, img) -> float \| gr.update` |
| | `calc_width_from_height()` | `(height: float, img) -> float \| gr.update` |
| | `init_dims()` | `(img) -> tuple[float, float]` |
| **预览缩放** | `_scale_preview_image()` | `(img, max_w=900, max_h=560) -> np.ndarray` |
| | `_preview_update()` | `(img) -> gr.update` |
| **i18n 文本** | `_get_header_html()` | `(lang: str) -> str` |
| | `_get_stats_html()` | `(lang: str, stats: dict) -> str` |
| | `_get_footer_html()` | `(lang: str) -> str` |
| | `_get_all_component_updates()` | `(lang: str, components: dict) -> list` |
| | `_get_component_list()` | `(components: dict) -> list` |
| **其他** | `get_extractor_reference_image()` | `(mode_str: str) -> PILImage.Image \| None` |
| | `_format_bytes()` | `(size_bytes: int) -> str` |

---

## 6. 白名单改动范围

允许修改的文件：

| 文件 | 允许的修改类型 | 限制 |
|------|----------------|------|
| `ui/layout_new.py` | 代码重构、函数提取、结构优化 | 不改变公开 API 签名和行为 |
| `main.py` | 最小兼容性修复 | 仅在导入变化时调整 |
| `ui/__init__.py` | 最小兼容性修复 | 仅在导出契约变化时调整 |
| 测试文件 | 测试增强 | 不破坏现有测试 |

---

## 7. 基线门禁结果（环境问题）

### 执行日期
2026-02-11

### 测试环境状态
- **pytest**: 未安装（exit code 127）
- **Python**: 可用

### 门禁执行计划
待 pytest 安装后执行：
```bash
pytest -m unit -q > .sisyphus/evidence/task-1-unit.log 2>&1
pytest -m integration -q > .sisyphus/evidence/task-1-integration.log 2>&1
pytest -m e2e -q > .sisyphus/evidence/task-1-e2e.log 2>&1
```

### 当前状态
- [x] 行为冻结清单已建立
- [x] 白名单范围已明确
- [ ] 基线门禁待执行（pytest 未安装）

---

## 8. 重构风险评估

### 高风险区域
1. **`create_app()` 结构**：控制整个应用初始化流程
2. **Tab 事件绑定**：错误绑定会导致功能失效
3. **i18n 系统集成**：语言切换依赖正确的组件 ID 映射

### 中风险区域
1. **Helper 函数重构**：内部逻辑错误可能影响 UI 交互
2. **CSS/JS 常量**：内容变化可能影响视觉效果

### 低风险区域
1. **代码格式化**：空行、缩进、注释调整
2. **变量重命名**：局部变量名优化

---

## 9. 验证检查清单

每次重构后必须验证：

### 自动化验证
- [ ] `python -c "from ui import layout_new; print('ok')"` 成功
- [ ] `python -c "from ui.layout_new import create_app, HEADER_CSS; assert callable(create_app); assert isinstance(HEADER_CSS, str) and len(HEADER_CSS)>0; print('ok')"` 成功
- [ ] `pytest -m unit -q` 全绿（pytest 安装后）
- [ ] `pytest -m integration -q` 全绿（pytest 安装后）
- [ ] `pytest -m e2e -q` 全绿（pytest 安装后）

### 功能验证
- [ ] 启动应用：`python main.py`
- [ ] 检查 Tab 顺序：Converter → Calibration → Extractor → About
- [ ] 检查语言切换功能
- [ ] 检查关键按钮功能

---

**文档版本**: v2.0 (完整版)
**最后更新**: 2026-02-11
**维护者**: Atlas (layout-new-refactor Task 1)
