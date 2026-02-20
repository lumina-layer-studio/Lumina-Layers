# 基本设定
- 使用中文作为交互语言
- 对文件修改要最小化 不要修改不必要的部分 不要进行格式化
- 如果你测试运行中发生编码错误，你要通过调整执行环境的编码来解决而不是去修改代码

# python设定
- 已经安装了uv工具
# 控制台设定
- 使用utf8控制台编码

## General Guidelines
- Gradio 单选框（`Radio`）涉及业务枚举值时，`choices` 的 value 必须使用 `Enum.value`；后端入口收到前端参数后必须第一时间转换为对应 `Enum`，后续流程统一用 `Enum` 判断，禁止继续用字符串包含/相等判断。
- 在修改代码后运行测试
- 在ui上添加按钮后添加相关测试

### Skill Loading (Mandatory)

- 涉及 i18n 文案链路（新增/修改按钮、状态文案、错误提示、core->ui 返回文案）时，必须先加载并遵循：`.claude/skills/i18n-text/SKILL.md`。
- 未加载该 skill 前，不得改动 `core/` 与 `ui/` 的文案传递逻辑。
- 若当前任务仅为纯算法/纯数据处理且不影响用户可见文本，可不加载该 skill。
- 涉及测试相关工作（编写测试、修改测试、运行测试、调试测试失败）时，必须先加载并遵循：`.claude/skills/testing-framework/SKILL.md`。

---

## 代码规范 (Code Standards)

**基于 2026-02-08 至 2026-02-20 的重构实践总结**

这些规则确保代码的一致性、可维护性和可扩展性。
**重要**: 这些规则不仅适用于重构代码，更是编写新代码时必须遵循的标准。

### 一、分层解耦原则

#### 1.1 核心层与UI层分离

**规则**: `core/` 模块不得直接返回面向用户的文本字符串

**实践**:
- ✅ **正确**: 核心层返回带标签的结构化数据
  ```python
  # core/converter.py
  from utils.i18n_help import make_status_tag

  def convert_image():
      if error:
          return make_status_tag("error.conversion_failed", detail=str(e))
      return make_status_tag("success.conversion_complete", count=num_colors)
  ```

- ❌ **错误**: 核心层直接返回中英文字符串
  ```python
  # core/converter.py
  def convert_image():
      if error:
          return "转换失败: " + str(e)  # ❌ 禁止
      return "转换完成，共生成 " + str(num_colors) + " 种颜色"  # ❌ 禁止
  ```

**UI层负责解析**:
```python
# ui/tabs/converter_tab.py
from utils.i18n_help import resolve_i18n_text

result = convert_image()
status = resolve_i18n_text(result, lang="zh")
gr.Info(status)
```

#### 1.2 业务逻辑与视图分离

**规则**: 提取UI相关代码到独立模块，保持核心模块纯业务逻辑

**实践**:
- ✅ UI代码放在 `ui/` 或 `ui/tabs/` 目录
- ✅ 核心业务逻辑放在 `core/` 目录
- ✅ 工具函数放在 `utils/` 目录

**示例**:
```
core/converter.py          # 纯业务逻辑
core/converter_core.py     # 核心算法
ui/converter_ui.py         # UI辅助函数
ui/tabs/converter_tab.py   # Gradio界面
```

---

### 二、类型安全优先

#### 2.1 使用枚举替代字符串匹配

**规则**: 涉及业务模式的参数必须使用枚举类型，禁止字符串包含判断

**实践**:
- ✅ **正确**: 定义枚举并在后端入口第一时间转换
  ```python
  # config.py
  from enum import Enum

  class ColorMode(str, Enum):
      CMYW = "cmyw"
      RYBW = "rybw"
      SIX_COLOR = "6-color"
      EIGHT_COLOR = "8-color"

  # Gradio Radio 组件
  mode = gr.Radio(
      choices=[ColorMode.CMYW, ColorMode.RYBW, ...],
      value=ColorMode.CMYW
  )

  # 后端入口第一时间转换
  def convert_handler(mode_str: str, ...):
      mode = ColorMode(mode_str)  # 字符串→枚举
      if mode == ColorMode.SIX_COLOR:  # ✅ 枚举相等判断
          ...
  ```

- ❌ **错误**: 字符串包含判断
  ```python
  # ❌ 禁止
  if "6-Color" in mode:
      ...
  if mode == "6-color":
      ...
  ```

#### 2.2 使用数据类统一参数管理

**规则**: 多参数函数使用 `@dataclass` 封装参数

**实践**:
```python
# core/converter.py
from dataclasses import dataclass

@dataclass
class ConversionRequest:
    """统一的转换请求参数"""
    image_path: str
    lut_path: str
    color_mode: ColorMode
    modeling_mode: ModelingMode
    color_detail: int = 64
    blur: float = 0.0
    smooth: float = 0.0

def convert_image_to_3d(request: ConversionRequest):
    """使用数据类作为参数"""
    ...
```

---

### 三、模块化拆分原则

#### 3.1 大文件拆分

**规则**: 单个文件超过 500 行时，考虑按功能拆分

**拆分策略**:
1. **按功能模块拆分**: 一个功能一个文件
   ```
   ui/layout_new.py (1806行) →
     ui/tabs/calibration_tab.py
     ui/tabs/converter_tab.py
     ui/tabs/extractor_tab.py
     ui/tabs/about_tab.py
   ```

2. **按抽象层次拆分**: 核心、UI、工具分离
   ```
   core/converter.py (臃肿) →
     core/converter_core.py      # 核心算法
     ui/converter_ui.py          # UI辅助
     ui/tabs/converter_tab.py    # Gradio界面
   ```

#### 3.2 提取独立功能模块

**规则**: 可复用的功能提取到独立模块

**实践**:
```python
# 提取前: 混在converter.py中
def detect_grid_corners(image):
    ...  # 200行检测逻辑

# 提取后: 独立模块
# ui/detection.py
class GridDetector:
    def detect_corners(self, image):
        ...
```

---

### 四、静态资源外部化

#### 4.1 CSS/JS 外部化

**规则**: 禁止在 Python 文件中硬编码 CSS/JS 字符串，所有静态资源必须外部化

**两种静态资源管理方式**:

1. **ui/static/**: 通过文件路径直接引用（暴露给Gradio）
   - 第三方库（libs/）
   - CSS文件
   - 通过 `/gradio_api/file=ui/static/...` 访问

2. **ui/assets/**: 通过 `load_asset_text` 读取为字符串
   - JS代码片段（需要嵌入到Python代码中）
   - 模板文件（通过 `load_template_text` 读取）

**实践**:
- ✅ **正确**: 使用外部文件
  ```python
  # ui/static/css/custom.css - 通过文件路径引用
  .my-button { color: blue; }

  # ui/assets/js/custom.js - 读取为字符串
  console.log("Hello from assets");

  # ui/assets.py
  def load_asset_text(*parts):
      return (Path(__file__).parent / "assets" / Path(*parts)).read_text()

  CUSTOM_JS = load_asset_text("js", "custom.js")
  ```

- ❌ **错误**: 硬编码字符串
  ```python
  # ❌ 禁止
  custom_css = """
  .my-button {
      color: blue;
  }
  """
  demo.css = custom_css
  ```

#### 4.2 统一资源管理

**规则**: 根据资源用途选择合适的目录

**目录结构**:
```
ui/
  static/                    # 通过文件路径引用（暴露给Gradio）
    css/
      app_layout.css         # 应用布局样式
      lut_interaction.css    # LUT交互样式
      preview_zoom.css       # 预览缩放样式
    libs/
      cropperjs/1.6.1/       # CropperJS第三方库
      jquery/3.7.1/          # jQuery第三方库

  assets/                    # 读取为字符串（通过Python代码加载）
    js/
      lut_grid.js            # LUT网格交互脚本
      preview_zoom.js        # 预览缩放脚本
      open_crop_modal.js     # 打开裁剪模态框脚本
      show_color_toast.js    # 颜色提示脚本
    template/
      crop_modal_head.html   # 裁剪模态框头部模板
      lut_grid.html          # LUT网格模板
      palette_row.html       # 调色板行模板

  assets.py                  # 资源加载工具（统一入口）
```

**资产加载器实践**:
```python
# ui/assets.py
from pathlib import Path

_ASSET_ROOT = Path(__file__).resolve().parent / "assets"
_TEMPLATE_ROOT = _ASSET_ROOT / "template"

def load_asset_text(*parts: str) -> str:
    """从 ui/assets/ 目录加载静态资源文本"""
    return (_ASSET_ROOT / Path(*parts)).read_text(encoding="utf-8")

def load_template_text(filename: str) -> str:
    """从 ui/assets/template/ 目录加载模板文本"""
    return (_TEMPLATE_ROOT / filename).read_text(encoding="utf-8")

def _as_script_tag(js_code: str) -> str:
    """将JS代码包装在script标签中"""
    return f"<script>\n{js_code}\n</script>"

# 导出常用资源（从assets/读取）
LUT_GRID_JS = _as_script_tag(load_asset_text("js", "lut_grid.js"))
PREVIEW_ZOOM_JS = _as_script_tag(load_asset_text("js", "preview_zoom.js"))

# For Gradio事件回调（不需要<script>包装）
OPEN_CROP_MODAL_JS = load_asset_text("js", "open_crop_modal.js")
SHOW_COLOR_TOAST_JS = load_asset_text("js", "show_color_toast.js")

# 加载模板
def load_crop_modal_template():
    return load_template_text("crop_modal_head.html")
```

#### 4.3 模板驱动架构

**规则**: 复杂UI组件使用HTML模板而非Python字符串拼接

**实践**:
- ✅ **正确**: 使用模板文件（存放在 `ui/assets/template/`）
  ```html
  <!-- ui/assets/template/palette_row.html -->
  <div class="palette-row" data-index="{{index}}">
      {% for color in colors %}
      <div class="color-item" data-rgb="{{color.rgb}}">
          <div class="color-box" style="background-color: {{color.hex}}"></div>
          <span class="color-label">{{color.label}}</span>
      </div>
      {% endfor %}
  </div>
  ```

  ```python
  # ui/palette_ui.py
  from ui.assets import load_template_text
  from jinja2 import Template

  def render_palette_row(index: int, colors: list) -> str:
      template_str = load_template_text("palette_row.html")
      template = Template(template_str)
      return template.render(index=index, colors=colors)
  ```

- ❌ **错误**: Python字符串拼接
  ```python
  # ❌ 禁止
  def render_palette_row(index, colors):
      html = f'<div class="palette-row" data-index="{index}">'
      for color in colors:
          html += f'<div class="color-item" data-rgb="{color.rgb}">...'
      return html
  ```

---

### 五、静态文件选择规则

#### 5.1 何时使用 ui/static

**规则**: 需要通过文件路径直接引用的静态资源使用 `ui/static/`

**适用场景**:
- **第三方库**: cropperjs, jquery等（通过 `<script src="/gradio_api/file=ui/static/libs/...">` 引用）
- **CSS样式表**: 应用布局、组件样式（通过 `<link href="/gradio_api/file=ui/static/css/...">` 引用）
- **任何需要在HTML中通过URL引用的资源**

**示例**:
```html
<!-- ui/assets/template/crop_modal_head.html -->
<link rel="stylesheet" href="/gradio_api/file=ui/static/libs/cropperjs/1.6.1/cropper.min.css">
<script src="/gradio_api/file=ui/static/libs/jquery/3.7.1/jquery.min.js"></script>
```

#### 5.2 何时使用 ui/assets

**规则**: 需要读取为字符串嵌入到Python代码中的静态资源使用 `ui/assets/`

**适用场景**:
- **JS代码片段**: 需要通过Gradio的 `js=` 参数传递的函数
- **模板文件**: Jinja2模板（通过 `load_template_text` 读取）
- **任何需要在Python代码中处理的内容**

**示例**:
```python
# ui/assets.py
from ui.assets import load_asset_text

# 读取JS代码片段，用于Gradio事件回调
OPEN_CROP_MODAL_JS = load_asset_text("js", "open_crop_modal.js")

# 读取模板文件
def load_crop_modal_template():
    return load_template_text("crop_modal_head.html")
```

#### 5.3 资源引用规范

**规则**: 所有静态资源通过 `ui/assets.py` 统一引用，禁止跨层级相对导入

**实践**:
```python
# ✅ 正确: 通过assets.py导入
from ui.assets import (
    # 从assets/读取的JS和模板
    OPEN_CROP_MODAL_JS,
    LUT_GRID_JS,
    load_template_text,
)

# ❌ 错误: 直接读取文件
from pathlib import Path
js_content = (Path(__file__).parent / "assets" / "js" / "custom.js").read_text()

# ❌ 错误: 跨层级导入
from ui.tabs.converter_tab import some_js_code
```

---

### 六、函数单一职责

#### 6.1 函数拆分原则

**规则**: 单个函数超过 100 行或承担多个职责时，必须拆分

**实践**:
```python
# ❌ 拆分前: 200行臃肿函数
def convert_image_to_3d(image_path, lut_path, ...):
    # 1. 参数验证 (20行)
    # 2. 向量SVG处理 (80行)
    # 3. 栅格处理 (80行)
    # 4. 导出 (20行)

# ✅ 拆分后: 协调函数 + 专职函数
def convert_image_to_3d(request: ConversionRequest):
    """协调函数: 负责输入验证和流程分发"""
    _validate_request(request)
    if request.modeling_mode == ModelingMode.VECTOR:
        return _run_vector_svg_flow(request)
    return _run_raster_flow(request)

def _run_vector_svg_flow(request: ConversionRequest):
    """专职函数: 向量SVG处理"""
    ...

def _run_raster_flow(request: ConversionRequest):
    """专职函数: 栅格处理"""
    ...
```

#### 6.2 提取重复逻辑

**规则**: 出现 2 次以上的相同逻辑必须提取为独立函数

**实践**:
```python
# ❌ 重复代码
def func_a():
    if not os.path.exists(path):
        return make_status_tag("error.file_not_found", path=path)
    ...

def func_b():
    if not os.path.exists(path):
        return make_status_tag("error.file_not_found", path=path)
    ...

# ✅ 提取公共逻辑
def _ensure_file_exists(path: str):
    if not os.path.exists(path):
        return make_status_tag("error.file_not_found", path=path)
    return None
```

---

### 七、渐进式重构（适用于重构现有代码）

**注意**: 
- 本节规则仅适用于重构现有代码，编写新代码时不需要关注。
- 重构时**不需要兼容性包装器**，直接修改所有调用处使用新接口。

#### 7.1 小步提交原则

**规则**: 每次重构只做一件事，保持功能不变

**实践**:
- Commit 1: 提取函数到新模块
- Commit 2: 更新调用处
- Commit 3: 移除旧代码
- Commit 4: 更新测试

**禁止**: 一次提交完成多项不相关的重构

---

### 八、代码清理

#### 8.1 移除未使用代码

**规则**: 重构后移除不再使用的导入和函数

**实践**:
```python
# ❌ 移除前
import numpy as np
import cv2
import unused_module  # 未使用

def old_func():  # 未被调用
    pass

def active_func():
    ...

# ✅ 移除后
import numpy as np
import cv2

def active_func():
    ...
```

#### 8.2 简化导入结构

**规则**: 使用相对导入和合理的导入分组

**实践**:
```python
# ✅ 标准导入顺序
# 1. 标准库
from pathlib import Path
from typing import Optional

# 2. 第三方库
import numpy as np
import gradio as gr

# 3. 本地模块
from config import ColorMode
from core.converter import convert_image
```

---

### 九、代码规范检查清单

在编写新代码或重构现有代码时，必须确认以下事项:

#### 9.1 功能不变性（重构时检查）
- [ ] 所有现有功能保持不变
- [ ] 所有测试通过
- [ ] 无新的警告或错误

#### 9.2 类型安全
- [ ] 使用枚举替代字符串判断
- [ ] 添加类型注解
- [ ] 使用数据类封装参数

#### 9.3 可维护性
- [ ] 移除重复代码
- [ ] 提取公共逻辑
- [ ] 添加清晰的文档字符串

#### 9.4 国际化
- [ ] 核心层使用 `make_status_tag`
- [ ] UI层使用 `resolve_i18n_text`
- [ ] 禁止硬编码中英文字符串

---

## 代码规范示例总结

以下示例展示了如何应用上述规则进行日常开发：

### 示例 1: 新增功能时使用枚举

当添加新的模式选项时：

```python
# ✅ 正确做法: 定义枚举
class ExportFormat(str, Enum):
    STL = "stl"
    OBJ = "obj"
    THREE_MF = "3mf"

# Gradio组件使用枚举
format_radio = gr.Radio(
    choices=[ExportFormat.STL, ExportFormat.OBJ, ExportFormat.THREE_MF],
    value=ExportFormat.THREE_MF,
    label="导出格式"
)

# 后端入口转换
def export_handler(format_str: str, model_data):
    export_format = ExportFormat(format_str)  # 字符串→枚举
    if export_format == ExportFormat.THREE_MF:
        return export_to_3mf(model_data)
    ...
```

```python
# ❌ 错误做法: 字符串判断
def export_handler(format_str: str, model_data):
    if format_str == "3mf":  # 魔法字符串
        ...
    if "3mf" in format_str:  # 包含判断更危险
        ...
```

### 示例 2: 编写新函数时保持单一职责

当添加新的导出功能时：

```python
# ✅ 正确做法: 拆分为小函数
def export_model(request: ExportRequest):
    """导出协调函数"""
    _validate_export_request(request)
    if request.format == ExportFormat.THREE_MF:
        return _export_to_3mf(request)
    return _export_to_mesh_format(request)

def _export_to_3mf(request: ExportRequest):
    """3MF格式专用导出"""
    mesh = _generate_mesh(request)
    metadata = _build_metadata(request)
    return _write_3mf(mesh, metadata)

def _export_to_mesh_format(request: ExportRequest):
    """STL/OBJ格式导出"""
    mesh = _generate_mesh(request)
    if request.format == ExportFormat.STL:
        return _write_stl(mesh)
    return _write_obj(mesh)
```

```python
# ❌ 错误做法: 所有逻辑混在一个函数
def export_model(format_str, model_data, quality, ...):
    # 200+行混合逻辑
    if format_str == "3mf":
        # 3MF导出逻辑 (50行)
        ...
    elif format_str == "stl":
        # STL导出逻辑 (50行)
        ...
    # 公共逻辑 (100行)
    ...
```

### 示例 3: 添加新UI组件时使用外部资源

当创建新的模态框组件时：

```html
<!-- ✅ 正确做法: ui/assets/template/new_modal.html -->
<div class="new-modal" id="{{modal_id}}">
    <div class="modal-header">
        <h3>{{title}}</h3>
        <button class="close-btn">&times;</button>
    </div>
    <div class="modal-content">
        {{content|safe}}
    </div>
</div>
```

```css
/* ✅ 正确做法: ui/static/css/new_modal.css - 通过文件路径引用 */
.new-modal {
    position: fixed;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
}
```

```python
# ✅ 正确做法: 通过assets.py加载
from ui.assets import load_template_text

def create_new_modal(title: str, content: str):
    template_str = load_template_text("new_modal.html")
    template = Template(template_str)
    return template.render(
        modal_id=f"modal_{uuid.uuid4().hex[:8]}",
        title=title,
        content=content
    )

# CSS通过文件路径引用（在模板中）:
# <link rel="stylesheet" href="/gradio_api/file=ui/static/css/new_modal.css">
```

```python
# ❌ 错误做法: 硬编码HTML/CSS
def create_new_modal(title, content):
    html = f"""
    <div class="new-modal">
        <div class="modal-header">
            <h3>{title}</h3>
            ...
        </div>
    </div>
    """
    return html
```

### 示例 4: 添加核心功能时遵循i18n规范

当在core层添加新的处理函数时：

```python
# ✅ 正确做法: 返回i18n标签
from utils.i18n_help import make_status_tag

def process_image(image_path: str) -> str:
    """处理图像并返回状态标签"""
    try:
        result = _do_process(image_path)
        return make_status_tag("success.process_complete",
                             pixels=result.pixel_count,
                             duration=result.duration)
    except FileNotFoundError:
        return make_status_tag("error.file_not_found", path=image_path)
    except Exception as e:
        return make_status_tag("error.process_failed",
                             detail=str(e))
```

```python
# ❌ 错误做法: 直接返回中英文字符串
def process_image(image_path: str) -> str:
    """❌ 禁止: 核心层不应返回用户可见文本"""
    try:
        result = _do_process(image_path)
        return f"处理完成，共 {result.pixel_count} 像素，耗时 {result.duration} 秒"
    except FileNotFoundError:
        return f"文件未找到: {image_path}"
```

```python
# ✅ UI层解析标签
from utils.i18n_help import resolve_i18n_text

def on_process_click(image_path):
    status_tag = process_image(image_path)
    status_text = resolve_i18n_text(status_tag, lang="zh")
    gr.Info(status_text)
```

### 示例 5: 创建新模块时的组织规范

当添加新的功能模块时：

```python
# ✅ 正确做法: 按职责分离文件结构
core/
  new_feature.py          # 核心业务逻辑
  new_feature_core.py     # 核心算法
ui/
  new_feature_ui.py       # UI辅助函数
  tabs/
    new_feature_tab.py    # Gradio界面
  static/
    css/
      new_feature.css     # 样式（通过文件路径引用）
    libs/
      some_lib/           # 第三方库（通过文件路径引用）
  assets/
    js/
      new_feature.js      # JS代码片段（读取为字符串）
    template/
      new_feature.html    # 模板文件（读取为字符串）
```

```python
# ❌ 错误做法: 所有代码混在一个文件
# ui/layout_new.py (再增加500行...)
# core/converter.py (再增加300行...)
```

---

## 规则优先级

**必须遵守（违反会导致代码被拒绝）**:
1. 分层解耦: core层不得返回用户可见文本
2. 类型安全: 业务模式必须使用枚举，禁止字符串匹配
3. 静态资源: 禁止硬编码CSS/JS/HTML字符串
4. 国际化: core层使用make_status_tag，UI层使用resolve_i18n_text

**强烈推荐（影响代码质量）**:
1. 函数单一职责: >100行函数必须拆分
2. 模块化: >500行文件必须拆分
3. 代码清理: 及时移除未使用代码
4. 提取重复: 2次以上相同逻辑必须提取

---

**遵循这些规则可以确保新代码和重构代码都保持高质量、一致性和可维护性。**
