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

## 代码重构规则 (Refactoring Rules)

**基于 2026-02-08 至 2026-02-20 的重构实践总结**

这些规则确保代码重构的一致性、可维护性和渐进性。

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

**规则**: 禁止在 Python 文件中硬编码 CSS/JS 字符串

**实践**:
- ✅ **正确**: 使用外部文件
  ```python
  # ui/assets/css/custom.css
  .my-button { color: blue; }

  # ui/assets.py
  def load_asset_text(*parts):
      return (Path(__file__).parent / "assets" / Path(*parts)).read_text()

  CUSTOM_CSS = load_asset_text("css", "custom.css")

  # main.py
  demo.css = CUSTOM_CSS
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

**规则**: 使用 `assets` 模块统一管理静态资源

**目录结构**:
```
ui/
  assets.py          # 资源加载器
  assets/
    css/
      custom.css
      header.css
    js/
      preview_zoom.js
    templates/
      crop_modal.html
```

---

### 五、函数单一职责

#### 5.1 函数拆分原则

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

#### 5.2 提取重复逻辑

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

### 六、渐进式重构
 
#### 6.1 小步提交原则

**规则**: 每次重构只做一件事，保持功能不变

**实践**:
- Commit 1: 提取函数到新模块
- Commit 2: 更新调用处
- Commit 3: 移除旧代码
- Commit 4: 更新测试

**禁止**: 一次提交完成多项不相关的重构

---

### 七、代码清理

#### 7.1 移除未使用代码

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

#### 7.2 简化导入结构

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

### 八、重构检查清单

在进行重构时，必须确认以下事项:

#### 8.1 功能不变性
- [ ] 所有现有功能保持不变
- [ ] 所有测试通过
- [ ] 无新的警告或错误

#### 8.2 类型安全
- [ ] 使用枚举替代字符串判断
- [ ] 添加类型注解
- [ ] 使用数据类封装参数
 
#### 8.3 可维护性
- [ ] 移除重复代码
- [ ] 提取公共逻辑
- [ ] 添加清晰的文档字符串

#### 8.4 国际化
- [ ] 核心层使用 `make_status_tag`
- [ ] UI层使用 `resolve_i18n_text`
- [ ] 禁止硬编码中英文字符串

---
 

