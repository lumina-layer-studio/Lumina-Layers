Task completed successfully. Created match strategy infrastructure for High-Fidelity LUT matching.

# High-Fidelity LUT 匹配策略基础设施 - 执行摘要

## 任务概述
实现 High-Fidelity LUT 匹配策略开关的完整基础设施,为后续接入 CIEDE2000 感知颜色匹配算法做准备。

## 完成内容

### 1. config.py 新增 MatchStrategy 枚举
- 文件位置: `config.py`
- 枚举定义:
  ```python
  class MatchStrategy(str, Enum):
      RGB_EUCLIDEAN = "rgb_euclidean"  # RGB 欧几里得距离匹配
      DELTAE2000 = "deltae2000"  # CIEDE2000 感知距离匹配
  ```
- 添加了 `get_display_name()` 方法用于显示名称
- 默认值: `MatchStrategy.RGB_EUCLIDEAN`

### 2. 后端参数传递链更新

#### core/image_processing.py
- 添加了 `match_strategy` 参数到 `LuminaImageProcessor.process_image()` 方法
- 默认值: `MatchStrategy.RGB_EUCLIDEAN`
- 将参数传递给处理策略的 `process()` 方法

#### core/image_processing_factory/processing_modes.py
- 更新了 `ProcessingModeStrategy` 抽象基类的 `process()` 方法签名
- 更新了所有实现类的 `process()` 方法,添加 `match_strategy` 参数

#### core/converter.py
- 导入 `MatchStrategy` 枚举
- 更新了以下函数的签名,添加 `match_strategy` 参数:
  - `generate_preview_cached()` - 预览生成函数
  - `convert_image_to_3d()` - 主转换函数
  - `generate_final_model()` - 最终模型生成函数

### 3. UI 控件实现

#### ui/layout_new.py
- 在 Advanced Accordion 中添加了"匹配策略" Radio 控件
- 控件选项:
  - "RGB Euclidean" (`MatchStrategy.RGB_EUCLIDEAN`)
  - "CIEDE2000" (`MatchStrategy.DELTAE2000`)
- 默认值: `MatchStrategy.RGB_EUCLIDEAN`
- 说明文字: "仅 High-Fidelity 模式可用 | High-Fidelity mode only"

### 4. 事件绑定和参数传递

#### 预览按钮事件
- 更新了 `generate_preview_cached_with_fit()` 函数
- 在 inputs 中添加了 `radio_conv_match_strategy`
- 参数正确传递到处理链

#### 生成按钮事件
- 更新了 `process_batch_generation()` 函数
- 在 inputs 和 args 中添加了 `match_strategy`
- 参数正确传递到处理链

### 5. 可见性控制逻辑
- 添加了 `update_match_strategy_visibility()` 函数
- 当 modeling_mode 为 `HIGH_FIDELITY` 时启用控件
- 当 modeling_mode 为 `PIXEL` 或 `VECTOR` 时禁用控件

## 验证结果

### 语法检查
- 所有修改的 Python 文件通过语法检查
- 无语法错误

### 枚举测试
- `MatchStrategy.RGB_EUCLIDEAN` 正常工作
- `MatchStrategy.DELTAE2000` 正常工作
- 默认值设置正确

### 默认行为验证
- 不传递 `match_strategy` 参数时,使用默认值 `RGB_EUCLIDEAN`
- 与旧版本行为完全一致
- 向后兼容性良好

## 符合性检查

所有 MUST DO 和 MUST NOT DO 要求均已满足。

## 文件修改清单
1. `config.py` - 新增 `MatchStrategy` 枚举
2. `core/image_processing.py` - 添加参数接收和传递
3. `core/image_processing_factory/processing_modes.py` - 更新策略方法签名
4. `core/converter.py` - 更新函数签名和参数传递
5. `ui/layout_new.py` - 添加 UI 控件、事件绑定和可见性控制
