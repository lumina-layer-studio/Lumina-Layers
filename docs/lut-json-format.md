# LUT JSON 格式规范

## 概述

LUT (Look-Up Table) JSON 文件是 Lumina Studio 用于存储颜色查找表的标准格式。该格式包含调色板定义、打印参数和颜色配方数据，用于将图像像素映射到多材料 3D 打印的层堆叠配方。

## 文件结构

LUT JSON 文件采用 Keyed JSON 格式，包含以下顶层字段：

```json
{
  "palette": { ... },
  "max_color_layers": 5,
  "layer_height_mm": 0.08,
  "line_width_mm": 0.42,
  "base_layers": 10,
  "base_channel_idx": 0,
  "layer_order": "Top2Bottom",
  "color_mode": "4-Color (CMYW)",
  "name": "lumina_lut",
  "entries": [ ... ]
}
```

## 字段说明

### 1. `palette` (必需)

调色板定义，描述所有可用的基础颜色通道。格式为对象，键为颜色名称，值为颜色属性。

**类型**: `Object<string, PaletteEntry>`

**示例**:
```json
"palette": {
  "White": {
    "material": "PLA Basic",
    "hex_color": "#ffffff"
  },
  "Cyan": {
    "material": "PLA Basic",
    "hex_color": "#0086d6"
  },
  "Magenta": {
    "material": "PLA Basic",
    "hex_color": "#ec008c"
  },
  "Yellow": {
    "material": "PLA Basic",
    "hex_color": "#f4ee2a"
  }
}
```

#### PaletteEntry 字段

- **`material`** (必需, string): 材料名称，如 "PLA Basic"、"PETG" 等
- **`hex_color`** (可选, string): 十六进制颜色值，格式为 `#RRGGBB`，用于 UI 预览和切片器集成

**注意**: 
- 颜色名称（对象键）必须非空且唯一
- 颜色名称会在 `entries` 的 `recipe` 字段中引用
- 支持特殊颜色名 "Air" 表示空气层（无材料）

### 2. `max_color_layers` (必需)

配方中最大颜色层数。

**类型**: `integer`  
**默认值**: `5`  
**取值范围**: 通常为 1-6

**示例**:
```json
"max_color_layers": 5
```

### 3. `layer_height_mm` (必需)

单层高度，单位为毫米。

**类型**: `float`  
**默认值**: `0.08`  
**典型值**: 0.04 - 0.20

**示例**:
```json
"layer_height_mm": 0.08
```

### 4. `line_width_mm` (必需)

挤出线宽，单位为毫米。

**类型**: `float`  
**默认值**: `0.42`  
**典型值**: 0.35 - 0.50

**示例**:
```json
"line_width_mm": 0.42
```

### 5. `base_layers` (必需)

底板层数，用于模型底部支撑。

**类型**: `integer`  
**默认值**: `10`  
**取值范围**: 通常为 5-20

**示例**:
```json
"base_layers": 10
```

### 6. `base_channel_idx` (必需)

底板使用的颜色通道索引，对应 `palette` 中的颜色顺序（从 0 开始）。

**类型**: `integer`  
**默认值**: `0`  
**说明**: 通常为 0（White）

**示例**:
```json
"base_channel_idx": 0
```

### 7. `layer_order` (必需)

打印层顺序。

**类型**: `string`  
**可选值**: 
- `"Top2Bottom"`: 从上到下打印（默认）
- `"Bottom2Top"`: 从下到上打印

**示例**:
```json
"layer_order": "Top2Bottom"
```

### 8. `color_mode` (可选)

颜色模式标识符，用于标识 LUT 的颜色系统类型。

**类型**: `string`  
**可选值**:
- `"4-Color (CMYW)"`: 4 色 CMYW 系统
- `"4-Color (RYBW)"`: 4 色 RYBW 系统
- `"6-Color (CMYW)"`: 6 色 CMYW 系统
- `"6-Color (RYBW)"`: 6 色 RYBW 系统
- `"8-Color"`: 8 色系统
- `"5-Color Extended"`: 5 色扩展系统
- `"BW"`: 黑白系统
- `"Merged"`: 合并 LUT

**示例**:
```json
"color_mode": "4-Color (CMYW)"
```

### 9. `name` (必需)

LUT 名称，通常从文件名自动生成。

**类型**: `string`

**示例**:
```json
"name": "lumina_lut"
```

### 10. `entries` (必需)

颜色条目数组，每个条目包含一个可打印颜色及其配方。

**类型**: `Array<LUTEntry>`

**示例**:
```json
"entries": [
  {
    "rgb": [255, 255, 255],
    "hex": "#FFFFFF",
    "lab": [99.999985, -0.000459, -0.008561],
    "recipe": ["White", "White", "White", "White", "White"]
  },
  {
    "rgb": [215, 250, 255],
    "hex": "#D7FAFF",
    "lab": [96.011964, -10.221886, -6.181428],
    "recipe": ["White", "White", "White", "White", "Cyan"],
    "source": "CMYW_Page1"
  }
]
```

#### LUTEntry 字段

- **`rgb`** (必需, array): RGB 颜色值，格式为 `[R, G, B]`，取值范围 0-255
  - 类型: `[integer, integer, integer]`
  - 用于精确的颜色往返（roundtrip）
  - 示例: `[255, 255, 255]` (白色), `[0, 134, 214]` (青色)

- **`hex`** (必需, string): 十六进制颜色值，格式为 `#RRGGBB`
  - 类型: `string`
  - 从 RGB 值自动计算生成
  - 用于 UI 显示、调试和日志
  - 示例: `"#FFFFFF"` (白色), `"#0086D6"` (青色)

- **`lab`** (必需, array): CIELAB 颜色空间值，格式为 `[L, a, b]`
  - 类型: `[float, float, float]`
  - L: 亮度，范围 0-100
  - a: 红绿轴，范围约 -128 到 127
  - b: 黄蓝轴，范围约 -128 到 127
  - 用于感知均匀的颜色匹配（KD-Tree 最近邻搜索）

- **`recipe`** (必需, array): 层堆叠配方，从底到顶的颜色名称列表
  - 类型: `Array<string>`
  - 长度: 等于 `max_color_layers`
  - 值: 必须是 `palette` 中定义的颜色名称或 "Air"
  - 示例: `["White", "White", "Cyan", "Magenta", "Yellow"]`

- **`source`** (可选, string): 来源 LUT 名称，用于合并 LUT 时标识条目来源
  - 仅在合并 LUT 中出现
  - 示例: `"CMYW_Page1"`, `"Custom_LUT"`

## 颜色模式与条目数量

不同颜色模式的典型条目数量：

| 颜色模式 | 典型条目数 | 说明 |
|---------|-----------|------|
| BW | 32 | 黑白灰度 |
| 4-Color (CMYW) | 1024 | 4^5 = 1024 种组合 |
| 4-Color (RYBW) | 1024 | 4^5 = 1024 种组合 |
| 5-Color Extended | 变化 | 6 层，带黑色外层 |
| 6-Color (CMYW) | 1296 | 6^4 或其他组合 |
| 6-Color (RYBW) | 1296 | 6^4 或其他组合 |
| 8-Color | 2738 | 专业广色域 |
| Merged | 变化 | 多个 LUT 合并后的结果 |

## 数据生成流程

### 1. 提取流程（Extraction）

从校准板照片提取颜色数据：

1. 用户打印物理校准板
2. 拍照并上传到系统
3. 计算机视觉提取每个色块的 RGB 值
4. 系统生成 LUT JSON 文件

### 2. 合并流程（Merge）

合并多个 LUT 文件：

1. 加载多个源 LUT 文件
2. 验证打印参数兼容性
3. 合并调色板（高优先级覆盖低优先级）
4. 去重相似颜色（基于 CIELAB 距离阈值）
5. 生成合并后的 LUT JSON 文件
6. 每个条目添加 `source` 字段标识来源

## 使用场景

### 1. 图像转换

在图像转 3D 模型时：
- 读取 LUT JSON 文件
- 构建 KD-Tree（基于 LAB 值）
- 对图像每个像素进行最近邻搜索
- 获取对应的 `recipe` 配方
- 生成 3D 网格和 3MF 文件

### 2. 切片器集成

导出到切片器时：
- 读取 `palette` 中的 `hex_color`
- 生成切片器配置文件
- 映射材料槽位到颜色通道

### 3. LUT 管理

系统管理 LUT 文件：
- 自动检测颜色模式（基于条目数量和调色板）
- 验证 LUT 完整性
- 提供 LUT 列表和预览

## 兼容性说明

### 旧格式兼容

系统支持旧版 `palette` 数组格式：

```json
"palette": [
  {
    "color": "White",
    "material": "PLA Basic",
    "hex_color": "#ffffff"
  }
]
```

新格式（对象格式）更简洁，推荐使用。

### NPZ 格式

除了 JSON 格式，系统还支持 `.npz` 格式（NumPy 压缩数组）：
- 用于合并 LUT 的高效存储
- 包含 `rgb` 和 `stacks` 数组
- 不包含完整的元数据

## 验证规则

有效的 LUT JSON 文件必须满足：

1. **必需字段**: 所有必需字段都存在
2. **调色板**: 至少包含一个颜色定义
3. **颜色名称**: 非空且唯一
4. **配方引用**: `recipe` 中的颜色名必须在 `palette` 中定义
5. **配方长度**: 所有 `recipe` 长度必须等于 `max_color_layers`
6. **RGB 范围**: RGB 值在 0-255 之间
7. **十六进制格式**: `hex` 字段必须匹配 `#RRGGBB` 格式，且与 RGB 值一致
8. **LAB 范围**: L 在 0-100，a/b 在合理范围内
9. **打印参数**: 数值在合理范围内

## RGB 与十六进制颜色转换

### RGB 转十六进制

每个 RGB 分量（0-255）转换为两位十六进制数（00-FF）：

```
RGB [255, 255, 255] → #FFFFFF (白色)
RGB [215, 250, 255] → #D7FAFF (浅青色)
RGB [0, 134, 214]   → #0086D6 (青色)
RGB [236, 0, 140]   → #EC008C (品红色)
RGB [244, 238, 42]  → #F4EE2A (黄色)
```

**转换公式**:
```
HEX = "#" + R.toString(16).padStart(2, '0').toUpperCase() 
          + G.toString(16).padStart(2, '0').toUpperCase()
          + B.toString(16).padStart(2, '0').toUpperCase()
```

**Python 实现**:
```python
def rgb_to_hex(r: int, g: int, b: int) -> str:
    """将 RGB 转换为十六进制颜色代码"""
    return f"#{r:02X}{g:02X}{b:02X}"
```

### 十六进制转 RGB

将十六进制字符串的每两位转换为十进制数：

```
#FFFFFF → RGB [255, 255, 255]
#D7FAFF → RGB [215, 250, 255]
#0086D6 → RGB [0, 134, 214]
```

**Python 实现**:
```python
def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """将十六进制颜色代码转换为 RGB"""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
```

### 在 LUT JSON 中的应用

虽然 `entries` 中同时存储 RGB 数组和十六进制字符串，但在不同场景有不同用途：

1. **调色板定义**: `palette` 中的 `hex_color` 字段用于 UI 预览
2. **条目数据**: `entries` 中的 `hex` 字段用于快速查看和调试
3. **切片器集成**: 导出到切片器时使用十六进制颜色
4. **颜色选择器**: UI 中的颜色选择器使用十六进制格式
5. **数值计算**: RGB 数组用于颜色匹配和 LAB 转换

**示例对应关系**:
```json
{
  "palette": {
    "Cyan": {
      "material": "PLA Basic",
      "hex_color": "#0086d6"  // 调色板中的十六进制
    }
  },
  "entries": [
    {
      "rgb": [0, 134, 214],   // RGB 数组格式
      "hex": "#0086D6",       // 对应的十六进制（自动生成）
      "lab": [52.123, -15.456, -42.789],
      "recipe": ["Cyan", "Cyan", "Cyan", "Cyan", "Cyan"]
    }
  ]
}
```

**字段一致性**:
- `entries[i].rgb` 和 `entries[i].hex` 必须表示相同的颜色
- 系统在保存时自动从 RGB 计算 hex 值，确保一致性
- 加载时可以验证两者是否匹配

## 示例文件

### 最小示例

```json
{
  "palette": {
    "White": {
      "material": "PLA Basic",
      "hex_color": "#ffffff"
    }
  },
  "max_color_layers": 1,
  "layer_height_mm": 0.08,
  "line_width_mm": 0.42,
  "base_layers": 10,
  "base_channel_idx": 0,
  "layer_order": "Top2Bottom",
  "name": "minimal_lut",
  "entries": [
    {
      "rgb": [255, 255, 255],
      "hex": "#FFFFFF",
      "lab": [100.0, 0.0, 0.0],
      "recipe": ["White"]
    }
  ]
}
```

### 完整 4 色示例

参见项目中的 `lut-npy预设/Custom/CMYK.json` 文件。

## 相关文件

- **生成代码**: `utils/lut_manager.py` - `LUTManager.save_keyed_json()`
- **加载代码**: `utils/lut_manager.py` - `LUTManager.load_lut_with_metadata()`
- **合并代码**: `core/lut_merger.py` - `LUTMerger.merge_luts()`
- **元数据定义**: `config.py` - `LUTMetadata`, `PaletteEntry`
- **API 端点**: `api/routers/lut.py` - LUT 管理和合并接口

## 更新历史

- **v1.6.3**: 当前格式，支持对象格式调色板和 `source` 字段
- **早期版本**: 数组格式调色板，无 `source` 字段
