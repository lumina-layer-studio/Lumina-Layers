# 需求文档：3MF 生成中孤立像素颜色清理

## 简介

在 Lumina Studio 生成 3MF 文件的流程中，LUT 颜色匹配之后会产生孤立像素问题。两个视觉上接近的量化颜色，经过 LUT 匹配后可能映射到完全不同的材料堆叠组合（material_matrix 中的 5 层堆叠不同），导致打印时产生不必要的换色操作，浪费打印时间。本功能在 LUT 匹配之后、voxel matrix 构建之前，对 material_matrix 执行孤立像素检测与清理，用邻域众数替换孤立像素，消除无意义的单点换色。

## 术语表

- **Material_Matrix**: 形状为 (H,W,5) 的 NumPy 数组，每个像素包含 5 层材料 ID 的堆叠组合，用于光学混色
- **Matched_RGB**: 形状为 (H,W,3) 的 NumPy 数组，LUT 匹配后每个像素的 RGB 颜色值
- **LUT**: 查找表（Look-Up Table），包含所有可用颜色的 RGB 值及其对应的 5 层材料堆叠组合
- **孤立像素**: 其 5 层材料堆叠编码与所有 8 邻域像素的堆叠编码均不相同的像素
- **堆叠编码**: 将 5 层材料 ID 编码为单个整数的紧凑表示，用于快速比较
- **邻域众数**: 8 邻域中出现次数最多的堆叠编码对应的材料组合
- **高保真模式**: LuminaImageProcessor 的 `_process_high_fidelity_mode` 处理路径，包含双边滤波、K-Means 量化和 LUT 匹配
- **像素模式**: LuminaImageProcessor 的 `_process_pixel_mode` 处理路径，直接逐像素 LUT 匹配，保留像素艺术的精确性
- **Voxel_Matrix**: 形状为 (Z,H,W) 的三维体素矩阵，由 material_matrix 构建，用于最终 3MF 网格生成
- **Converter_Tab**: Gradio 界面中的转换器标签页，包含图像上传、参数设置、预览和生成功能，由 `ui/layout_new.py` 的 `create_converter_tab_content` 函数构建
- **Cleanup_Controller**: 控制孤立像素清理执行时机和条件的逻辑单元，负责根据处理模式和 UI 开关状态决定是否执行清理

## 需求

### 需求 1：孤立像素检测

**用户故事：** 作为 Lumina Studio 用户，我希望系统能识别出 LUT 匹配后产生的孤立像素，以便后续清理这些无意义的单点颜色差异。

#### 验收标准

1. WHEN LUT 匹配完成后生成 material_matrix，THE Isolated_Pixel_Detector SHALL 将每个像素的 5 层材料 ID 编码为单个整数（堆叠编码），编码公式为 `layer0 * B^4 + layer1 * B^3 + layer2 * B^2 + layer3 * B + layer4`，其中 B 为材料 ID 的最大值加 1
2. WHEN 对每个非边界像素计算 8 邻域时，THE Isolated_Pixel_Detector SHALL 判定该像素为孤立像素，当且仅当该像素的堆叠编码与所有 8 个邻居的堆叠编码均不相同
3. WHEN 对边界像素（图像边缘）计算邻域时，THE Isolated_Pixel_Detector SHALL 仅使用实际存在的邻居（3 个或 5 个）进行孤立判定，不使用填充或环绕策略

### 需求 2：孤立像素替换

**用户故事：** 作为 Lumina Studio 用户，我希望孤立像素被替换为周围最常见的颜色，以减少不必要的换色操作和打印时间。

#### 验收标准

1. WHEN 一个像素被判定为孤立像素时，THE Isolated_Pixel_Replacer SHALL 统计该像素 8 邻域中每种堆叠编码的出现次数，选择出现次数最多的堆叠编码作为替换值
2. WHEN 邻域众数存在多个并列最多的堆叠编码时，THE Isolated_Pixel_Replacer SHALL 选择其中任意一个作为替换值（确定性选择）
3. WHEN 替换孤立像素时，THE Isolated_Pixel_Replacer SHALL 同时更新 material_matrix 中该像素的 5 层材料 ID 和 matched_rgb 中该像素的 RGB 值，保持两者一致

### 需求 3：处理模式适配

**用户故事：** 作为像素艺术创作者，我希望像素模式下不执行孤立像素清理，以保留我精心设计的每一个像素颜色。

#### 验收标准

1. WHEN 处理模式为高保真模式时，THE Cleanup_Controller SHALL 在 LUT 匹配完成之后、返回结果之前执行孤立像素清理
2. WHEN 处理模式为像素模式时，THE Cleanup_Controller SHALL 跳过孤立像素清理，直接返回原始 LUT 匹配结果

### 需求 4：性能优化

**用户故事：** 作为 Lumina Studio 用户，我希望孤立像素清理不会显著增加处理时间，以保持流畅的使用体验。

#### 验收标准

1. THE Isolated_Pixel_Cleanup SHALL 使用 NumPy 向量化操作实现堆叠编码计算和邻域比较，避免 Python 层面的逐像素双重循环
2. WHEN 处理 500x500 像素的图像时，THE Isolated_Pixel_Cleanup SHALL 在 2 秒内完成孤立像素检测和替换（在常规硬件上）
3. THE Isolated_Pixel_Cleanup SHALL 仅修改被判定为孤立的像素，保持所有非孤立像素的 material_matrix 和 matched_rgb 值不变

### 需求 5：正确性保证（往返一致性）

**用户故事：** 作为开发者，我希望清理操作的正确性可验证，确保不会引入新的数据不一致。

#### 验收标准

1. FOR ALL 经过清理的像素，THE Isolated_Pixel_Cleanup SHALL 保证替换后的 material_matrix 值来自该像素的某个邻居，而非凭空生成的新值
2. FOR ALL 经过清理的像素，THE Isolated_Pixel_Cleanup SHALL 保证替换后的 matched_rgb 值与替换后的 material_matrix 值对应同一个 LUT 条目
3. WHEN 对已清理的 material_matrix 再次执行孤立像素检测时，THE Isolated_Pixel_Detector SHALL 检测到的孤立像素数量小于或等于清理前的数量（幂等性趋势）

### 需求 6：UI 开关控制

**用户故事：** 作为 Lumina Studio 用户，我希望在界面上有一个开关来启用或禁用孤立像素清理，以便直观对比开启和关闭清理后的效果差异。

#### 验收标准

1. THE Converter_Tab SHALL 在高级参数区域（Advanced Accordion）内提供一个 Gradio Checkbox 组件，标签为"孤立像素清理 | Isolated Pixel Cleanup"，默认值为开启（True）
2. WHEN 用户切换孤立像素清理开关状态后点击预览或生成按钮时，THE Converter_Tab SHALL 将该开关的当前值作为参数传递给图像处理流程
3. WHEN 孤立像素清理开关为关闭状态时，THE Cleanup_Controller SHALL 跳过孤立像素清理步骤，直接返回原始 LUT 匹配结果，行为等同于未集成清理功能
4. WHEN 处理模式为像素模式时，THE Converter_Tab SHALL 将孤立像素清理开关设为禁用状态（interactive=False），并显示提示信息说明像素模式下不支持此功能

### 需求 7：非侵入性集成（硬性要求）

**用户故事：** 作为开发者，我希望孤立像素清理功能以独立模块的形式集成，不修改现有代码的函数签名和核心逻辑，以降低引入回归缺陷的风险。

#### 验收标准

1. THE Isolated_Pixel_Cleanup SHALL 作为独立 Python 模块（`core/isolated_pixel_cleanup.py`）实现，包含所有检测和替换逻辑
2. THE Isolated_Pixel_Cleanup 模块 SHALL 暴露一个纯函数接口 `cleanup_isolated_pixels(material_matrix, matched_rgb, lut_rgb, ref_stacks)`，接收 NumPy 数组并返回清理后的 NumPy 数组副本，不修改输入数组
3. THE LuminaImageProcessor 类的 `process_image`、`_process_high_fidelity_mode`、`_process_pixel_mode` 方法 SHALL 保持现有函数签名不变，不增加、删除或修改任何参数
4. THE LuminaImageProcessor 类的 `_process_high_fidelity_mode` 和 `_process_pixel_mode` 方法 SHALL 保持现有核心逻辑不变，孤立像素清理 SHALL 在这些方法返回结果之后、`process_image` 方法返回最终结果之前，作为可选的后处理步骤调用
5. IF `core/isolated_pixel_cleanup.py` 模块导入失败，THEN THE LuminaImageProcessor SHALL 捕获 ImportError 并跳过清理步骤，在控制台输出警告信息，正常返回未清理的结果
6. THE Converter_Tab 中新增的 UI 组件（Checkbox）SHALL 通过 Gradio 的 inputs 列表传递给现有的预览和生成回调函数，不修改现有回调函数的核心逻辑结构

### 需求 8：精度优先

**用户故事：** 作为追求高质量打印的用户，我希望孤立像素清理对颜色精确度的影响降到最低，确保清理后的图像尽可能保持原始色彩还原度。

#### 验收标准

1. THE Isolated_Pixel_Replacer SHALL 仅替换被判定为孤立的像素（与所有邻居的堆叠编码均不同），不修改任何非孤立像素的 material_matrix 和 matched_rgb 值
2. WHEN 替换孤立像素时，THE Isolated_Pixel_Replacer SHALL 使用邻域众数对应的完整 5 层材料堆叠和对应的 LUT RGB 值进行替换，保证替换值来自 LUT 中的合法条目
3. THE Isolated_Pixel_Cleanup SHALL 在清理完成后计算并输出清理统计信息，包括：孤立像素总数、实际替换像素数、替换像素占总像素的百分比，以便用户评估清理影响范围
4. FOR ALL 经过清理的像素，THE Isolated_Pixel_Replacer SHALL 保证替换后的 matched_rgb 值与替换后的 material_matrix 值严格对应同一个 LUT 条目，不产生 RGB 与材料堆叠不匹配的情况
5. THE Isolated_Pixel_Cleanup SHALL 执行单轮清理（single pass），不进行多轮迭代清理，以避免过度平滑导致细节丢失
