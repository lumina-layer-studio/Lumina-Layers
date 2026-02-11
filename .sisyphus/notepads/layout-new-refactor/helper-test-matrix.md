# Helper 函数测试矩阵

> 分析目标：`ui/layout_new.py` 中的私有 helper 函数
> 创建时间：2025-02-11
> 用途：TDD 测试用例设计的参考依据

---

## 测试矩阵概览

| 函数分类 | 函数名 | 正向场景 | 边界场景 | 负向场景 | 优先级 |
|---------|--------|---------|---------|---------|--------|
| LUT 读写 | `load_last_lut_setting()` | 2 | 2 | 1 | 高 |
| LUT 读写 | `save_last_lut_setting()` | 2 | 2 | 2 | 高 |
| 尺寸计算 | `_get_image_size()` | 3 | 2 | 2 | 高 |
| 尺寸计算 | `calc_height_from_width()` | 2 | 2 | 2 | 中 |
| 尺寸计算 | `calc_width_from_height()` | 2 | 2 | 2 | 中 |
| 尺寸计算 | `init_dims()` | 2 | 2 | 1 | 中 |
| 预览缩放 | `_scale_preview_image()` | 2 | 2 | 2 | 中 |
| 预览缩放 | `_preview_update()` | 2 | 1 | 1 | 低 |
| i18n 文本 | `_get_header_html()` | 2 | 1 | 1 | 低 |
| i18n 文本 | `_get_stats_html()` | 2 | 1 | 1 | 低 |
| i18n 文本 | `_get_footer_html()` | 2 | 1 | 1 | 低 |
| i18n 文本 | `_get_all_component_updates()` | 1 | 1 | 1 | 中 |
| i18n 文本 | `_get_component_list()` | 1 | 1 | 1 | 低 |
| 其他 | `get_extractor_reference_image()` | 3 | 2 | 2 | 高 |
| 其他 | `_format_bytes()` | 4 | 1 | 0 | 低 |

---

## 1. LUT 读写函数

### 1.1 `load_last_lut_setting()`

**函数签名：**
```python
def load_last_lut_setting() -> str | None
```

**功能描述：**
从 `user_settings.json` 加载上次选择的 LUT 名称。

**测试场景矩阵：**

| 场景类型 | 测试用例 | 输入 | 预期输出 | 断言 |
|---------|---------|------|---------|------|
| **正向** | 正常文件存在 | 配置文件存在且包含 `last_lut` | 返回 LUT 名称字符串 | `assert isinstance(result, str)` |
| **正向** | 空配置文件 | 配置文件存在但无 `last_lut` 键 | 返回 `None` | `assert result is None` |
| **边界** | 配置文件不存在 | `user_settings.json` 不存在 | 返回 `None` | `assert result is None` |
| **边界** | 配置文件损坏 | 配置文件包含无效 JSON | 返回 `None` | `assert result is None` |
| **负向** | 权限拒绝 | 配置文件不可读 | 返回 `None`，打印错误 | `assert result is None` |

**测试依赖：**
- 需要创建临时配置文件
- 需要模拟文件系统权限错误

---

### 1.2 `save_last_lut_setting(lut_name)`

**函数签名：**
```python
def save_last_lut_setting(lut_name: str | None) -> None
```

**功能描述：**
持久化当前 LUT 选择到 `user_settings.json`。

**测试场景矩阵：**

| 场景类型 | 测试用例 | 输入 | 预期行为 | 断言 |
|---------|---------|------|---------|------|
| **正向** | 保存新 LUT 名称 | `"my_custom_lut"` | 写入配置文件 | 验证文件内容包含 `{"last_lut": "my_custom_lut"}` |
| **正向** | 清除 LUT 设置 | `None` | 写入 `null` 值 | 验证文件内容 `{"last_lut": null}` |
| **边界** | 覆盖现有配置 | 配置文件已存在 | 保留其他键，只更新 `last_lut` | 验证其他键未被删除 |
| **边界** | 创建新配置文件 | 配置文件不存在 | 创建新文件 | 验证文件已创建 |
| **负向** | 权限拒绝 | 配置目录只读 | 打印错误，不崩溃 | 验证函数正常返回 |
| **负向** | 磁盘空间不足 | 磁盘已满 | 打印错误，不崩溃 | 验证函数正常返回 |

**测试依赖：**
- 需要创建临时配置文件
- 需要模拟文件系统权限错误

---

## 2. 尺寸计算函数

### 2.1 `_get_image_size(img)`

**函数签名：**
```python
def _get_image_size(img) -> tuple[int, int] | None
```

**功能描述：**
获取图像尺寸（宽度、高度）。支持文件路径或 numpy 数组。

**测试场景矩阵：**

| 场景类型 | 测试用例 | 输入 | 预期输出 | 断言 |
|---------|---------|------|---------|------|
| **正向** | 图片文件路径 | 有效 `.png`/`.jpg` 文件路径 | `(width, height)` 元组 | `assert size == (w, h)` |
| **正向** | Numpy 数组 | `np.array` 形状 `(H, W, C)` | `(W, H)` 元组 | `assert size == (arr.shape[1], arr.shape[0])` |
| **正向** | SVG 文件（可选） | 有效 `.svg` 文件路径 | `(width, height)` 元组（需要 svglib） | `assert size is not None` |
| **边界** | None 输入 | `None` | 返回 `None` | `assert result is None` |
| **边界** | 无效文件路径 | 不存在的文件路径 | 返回 `None` | `assert result is None` |
| **负向** | 损坏的图片文件 | 损坏的二进制文件 | 返回 `None` | `assert result is None` |
| **负向** | 错误的数组形状 | `np.array` 形状 `(H,)`（1D） | 返回 `None` | `assert result is None` |
| **负向** | SVG 但无 svglib | `.svg` 文件，无 svglib | 返回 `None` | `assert result is None` |

**测试依赖：**
- 需要创建测试图片文件
- 需要创建测试 numpy 数组
- 可选：创建测试 SVG 文件

---

### 2.2 `calc_height_from_width(width, img)`

**函数签名：**
```python
def calc_height_from_width(width: float, img) -> float | gr.update
```

**功能描述：**
根据宽度（mm）计算高度（mm），保持纵横比。

**测试场景矩阵：**

| 场景类型 | 测试用例 | 输入 | 预期输出 | 断言 |
|---------|---------|------|---------|------|
| **正向** | 标准计算 | `width=60, img=1920x1080` | `33.75` (60 × 1080 / 1920) | `assert result == 33.75` |
| **正向** | 正方形图片 | `width=50, img=1000x1000` | `50.0` | `assert result == 50.0` |
| **边界** | 极小宽度 | `width=0.1, img=1920x1080` | `0.05625` | `assert result > 0` |
| **边界** | None 输入 | `width=None, img=path` | `gr.update()` | `isinstance(result, type(gr.update()))` |
| **负向** | 宽度为 0 | `width=0, img=path` | 返回 `0` | `assert result == 0` |
| **负向** | 图片尺寸未知 | `width=60, img=None` | `gr.update()` | 验证返回类型 |

**测试依赖：**
- 需要创建测试图片文件
- 需要测试 numpy 数组输入

---

### 2.3 `calc_width_from_height(height, img)`

**函数签名：**
```python
def calc_width_from_height(height: float, img) -> float | gr.update
```

**功能描述：**
根据高度（mm）计算宽度（mm），保持纵横比。

**测试场景矩阵：**

| 场景类型 | 测试用例 | 输入 | 预期输出 | 断言 |
|---------|---------|------|---------|------|
| **正向** | 标准计算 | `height=60, img=1920x1080` | `106.7` (60 × 1920 / 1080) | `assert result == 106.666...` |
| **正向** | 正方形图片 | `height=50, img=1000x1000` | `50.0` | `assert result == 50.0` |
| **边界** | 极小高度 | `height=0.1, img=1920x1080` | `0.177...` | `assert result > 0` |
| **边界** | None 输入 | `height=None, img=path` | `gr.update()` | 验证返回类型 |
| **负向** | 高度为 0 | `height=0, img=path` | 返回 `0` | `assert result == 0` |
| **负向** | 图片尺寸未知 | `height=60, img=None` | `gr.update()` | 验证返回类型 |

**测试依赖：**
- 需要创建测试图片文件
- 需要测试 numpy 数组输入

---

### 2.4 `init_dims(img)`

**函数签名：**
```python
def init_dims(img) -> tuple[float, float]
```

**功能描述：**
从图像纵横比计算默认宽度/高度（mm）。

**测试场景矩阵：**

| 场景类型 | 测试用例 | 输入 | 预期输出 | 断言 |
|---------|---------|------|---------|------|
| **正向** | 横向图片 | `img=1920x1080` | `(60.0, 33.75)` | `assert result == (60.0, 33.75)` |
| **正向** | 纵向图片 | `img=1080x1920` | `(60.0, 106.666...)` | `assert result == (60.0, 106.666...)` |
| **边界** | 正方形图片 | `img=1000x1000` | `(60.0, 60.0)` | `assert result == (60.0, 60.0)` |
| **边界** | None 输入 | `img=None` | `(60, 60)` | `assert result == (60, 60)` |
| **负向** | 无效图片路径 | `img="nonexistent.png"` | `(60, 60)` | `assert result == (60, 60)` |

**测试依赖：**
- 需要创建不同纵横比的测试图片

---

## 3. 预览缩放函数

### 3.1 `_scale_preview_image(img, max_w=900, max_h=560)`

**函数签名：**
```python
def _scale_preview_image(img, max_w: int = 900, max_h: int = 560) -> np.ndarray
```

**功能描述：**
缩放预览图像以适应固定框，不改变容器大小。

**测试场景矩阵：**

| 场景类型 | 测试用例 | 输入 | 预期输出 | 断言 |
|---------|---------|------|---------|------|
| **正向** | 大图缩小 | `2000x1500` 图像 | 缩放到 `<900x560` | `assert result.shape[0] <= 560 and result.shape[1] <= 900` |
| **正向** | 小图不变 | `400x300` 图像 | 原样返回 | `assert result.shape == img.shape` |
| **边界** | 极限尺寸 | `900x560` 图像 | 原样返回 | `assert result.shape == (560, 900, C)` |
| **边界** | None 输入 | `None` | 返回 `None` | `assert result is None` |
| **边界** | 零尺寸图像 | `0x0` 数组 | 原样返回 | `assert result.shape == img.shape` |
| **负向** | 非数组输入 | `"not_an_image"` | 返回原输入 | `assert result == "not_an_image"` |
| **负向** | PIL 图像输入 | `PIL.Image` 对象 | 转换为数组并缩放 | `isinstance(result, np.ndarray)` |

**测试依赖：**
- 需要创建不同尺寸的测试图像
- 需要 PIL 图像和 numpy 数组

---

### 3.2 `_preview_update(img)`

**函数签名：**
```python
def _preview_update(img) -> gr.update
```

**功能描述：**
返回 Gradio 更新对象用于预览图像，不调整容器大小。

**测试场景矩阵：**

| 场景类型 | 测试用例 | 输入 | 预期输出 | 断言 |
|---------|---------|------|---------|------|
| **正向** | 正常图像 | `np.ndarray` 图像 | `gr.update(value=...)` | 验证包含 `value` 键 |
| **正向** | 已有更新对象 | `gr.update(...)` | 原样返回 | `assert result == input` |
| **边界** | None 输入 | `None` | `gr.update(value=None)` | 验证返回值 |

**测试依赖：**
- 需要 gradio 模块

---

## 4. i18n 文本更新函数

### 4.1 `_get_header_html(lang: str)`

**函数签名：**
```python
def _get_header_html(lang: str) -> str
```

**功能描述：**
返回指定语言的 header HTML（标题 + 副标题）。

**测试场景矩阵：**

| 场景类型 | 测试用例 | 输入 | 预期输出 | 断言 |
|---------|---------|------|---------|------|
| **正向** | 中文 | `"zh"` | 包含中文副标题 | `assert "Lumina Studio" in result` |
| **正向** | 英文 | `"en"` | 包含英文副标题 | `assert "Lumina Studio" in result` |
| **边界** | 无效语言代码 | `"fr"` | 使用默认翻译 | 验证 HTML 格式正确 |

**测试依赖：**
- 需要 `I18n.get()` 模拟

---

### 4.2 `_get_stats_html(lang: str, stats: dict)`

**函数签名：**
```python
def _get_stats_html(lang: str, stats: dict) -> str
```

**功能描述：**
返回统计栏 HTML（校准数 / 提取数 / 转换数）。

**测试场景矩阵：**

| 场景类型 | 测试用例 | 输入 | 预期输出 | 断言 |
|---------|---------|------|---------|------|
| **正向** | 正常统计数据 | `stats={"calibrations": 10, ...}` | 包含统计数字 | `assert "10" in result` |
| **正向** | 零统计数据 | `stats={"calibrations": 0, ...}` | 显示为 0 | `assert "0" in result` |
| **边界** | 空字典 | `stats={}` | 显示为 0 | 验证 HTML 格式 |

**测试依赖：**
- 需要 `I18n.get()` 模拟

---

### 4.3 `_get_footer_html(lang: str)`

**函数签名：**
```python
def _get_footer_html(lang: str) -> str
```

**功能描述：**
返回指定语言的 footer HTML。

**测试场景矩阵：**

| 场景类型 | 测试用例 | 输入 | 预期输出 | 断言 |
|---------|---------|------|---------|------|
| **正向** | 中文 | `"zh"` | 包含中文提示 | `assert "<div" in result and "</div>" in result` |
| **正向** | 英文 | `"en"` | 包含英文提示 | `assert "<div" in result and "</div>" in result` |

**测试依赖：**
- 需要 `I18n.get()` 模拟

---

### 4.4 `_get_all_component_updates(lang: str, components: dict)`

**函数签名：**
```python
def _get_all_component_updates(lang: str, components: dict) -> list
```

**功能描述：**
为所有组件构建 `gr.update()` 列表以应用 i18n。

**测试场景矩阵：**

| 场景类型 | 测试用例 | 输入 | 预期输出 | 断言 |
|---------|---------|------|---------|------|
| **正向** | 空组件字典 | `components={}` | 返回空列表 | `assert result == []` |
| **边界** | 包含事件对象 | `components={"event": Dependency(...)}` | 跳过事件对象 | `len(result) == 0` |
| **负向** | 无效组件类型 | `components={"key": "string"}` | 返回 `gr.update()` | 验证列表项类型 |

**测试依赖：**
- 需要创建模拟 Gradio 组件
- 需要 gradio 模块

---

### 4.5 `_get_component_list(components: dict)`

**函数签名：**
```python
def _get_component_list(components: dict) -> list
```

**功能描述：**
按字典顺序返回组件值（用于 Gradio 输出）。

**测试场景矩阵：**

| 场景类型 | 测试用例 | 输入 | 预期输出 | 断言 |
|---------|---------|------|---------|------|
| **正向** | 空字典 | `components={}` | 返回空列表 | `assert result == []` |
| **边界** | 混合组件类型 | 包含 `Block` 和 `Dependency` | 只返回 `Block` | 验证结果只包含 Block 对象 |

**测试依赖：**
- 需要创建模拟 Gradio 组件
- 需要 gradio 模块

---

## 5. 其他 Helper 函数

### 5.1 `get_extractor_reference_image(mode_str)`

**函数签名：**
```python
def get_extractor_reference_image(mode_str: str) -> PILImage.Image | None
```

**功能描述：**
加载或生成颜色提取器参考图像（磁盘缓存）。

**测试场景矩阵：**

| 场景类型 | 测试用例 | 输入 | 预期输出 | 断言 |
|---------|---------|------|---------|------|
| **正向** | 6-Color 模式 | `"6-Color (Smart 1296)"` | 返回参考图像 | `isinstance(result, PILImage.Image)` |
| **正向** | CMYW 模式 | `"CMYW"` | 返回参考图像 | `isinstance(result, PILImage.Image)` |
| **正向** | RYBW 模式 | `"RYBW"` | 返回参考图像 | `isinstance(result, PILImage.Image)` |
| **边界** | 缓存文件已存在 | 对应 `.png` 文件存在 | 从缓存加载 | 验证文件未重新生成 |
| **边界** | 缓存目录不存在 | `assets/` 不存在 | 创建目录并生成 | 验证目录已创建 |
| **负向** | 生成失败 | 校准板生成失败 | 返回 `None` | `assert result is None` |
| **负向** | 未知模式 | `"Unknown Mode"` | 默认为 RYBW | 验证文件名正确 |

**测试依赖：**
- 需要创建临时 `assets/` 目录
- 需要模拟校准板生成函数

---

### 5.2 `_format_bytes(size_bytes: int)`

**函数签名：**
```python
def _format_bytes(size_bytes: int) -> str
```

**功能描述：**
格式化字节为人类可读字符串。

**测试场景矩阵：**

| 场景类型 | 测试用例 | 输入 | 预期输出 | 断言 |
|---------|---------|------|---------|------|
| **正向** | 字节 | `0` | `"0 B"` | `assert result == "0 B"` |
| **正向** | 千字节 | `1024` | `"1.0 KB"` | `assert result == "1.0 KB"` |
| **正向** | 兆字节 | `1048576` | `"1.0 MB"` | `assert result == "1.0 MB"` |
| **正向** | 吉字节 | `1073741824` | `"1.0 GB"` | `assert result == "1.0 GB"` |
| **正向** | 太字节 | `1099511627776` | `"1.0 TB"` | `assert result == "1.0 TB"` |
| **边界** | 非整数 | `1536` | `"1.5 KB"` | `assert result == "1.5 KB"` |

**测试依赖：**
- 无需外部依赖

---

## 测试实施建议

### 优先级排序

1. **高优先级**（P0）：
   - LUT 读写函数（配置持久化核心功能）
   - `_get_image_size()`（尺寸计算基础）
   - `get_extractor_reference_image()`（校准流程依赖）

2. **中优先级**（P1）：
   - 其他尺寸计算函数
   - 预览缩放函数
   - `_get_all_component_updates()`

3. **低优先级**（P2）：
   - 简单 i18n 文本函数
   - `_format_bytes()`

### 测试隔离策略

- 使用 `pytest.fixture` 创建临时文件和目录
- 使用 `unittest.mock` 模拟外部依赖（`I18n`, `gradio`, 文件系统）
- 每个测试用例独立清理临时资源

### 覆盖率目标

- 函数覆盖率：≥ 80%
- 分支覆盖率：≥ 60%
- 负向场景覆盖率：100%（每个函数至少 1 个负向测试）

---

## 附录：函数依赖关系图

```
load_last_lut_setting() ──────────┐
save_last_lut_setting() ──────────┤
                                  │
_get_image_size() ──────────────────┤
  ├─> calc_height_from_width() ───┤
  ├─> calc_width_from_height() ───┤
  └─> init_dims() ────────────────┤
                                  │
_scale_preview_image() ────────────┤
  └─> _preview_update() ──────────┤
                                  │
_get_header_html() ────────────────┤
_get_stats_html() ────────────────┤
_get_footer_html() ────────────────┤
_get_all_component_updates() ───────┤
_get_component_list() ──────────────┤
                                  │
get_extractor_reference_image() ────┤
_format_bytes() ────────────────────┘
```

---

## 测试实施检查清单

- [ ] 为每个高优先级函数编写至少 1 个正向测试
- [ ] 为每个高优先级函数编写至少 1 个负向测试
- [ ] 为 LUT 读写函数创建临时配置文件 fixture
- [ ] 为尺寸计算函数创建测试图片文件 fixture
- [ ] 模拟 `I18n.get()` 以支持 i18n 测试
- [ ] 模拟 `gradio.update()` 以支持 Gradio 组件测试
- [ ] 验证所有测试可独立运行
- [ ] 运行测试并检查覆盖率报告

---

*最后更新：2025-02-11*
