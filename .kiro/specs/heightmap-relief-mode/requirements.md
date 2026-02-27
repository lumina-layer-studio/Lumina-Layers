# 需求文档：高度图浮雕模式

## 简介

当前 2.5D 浮雕模式按颜色统一分配高度，同一颜色的所有像素高度相同，无法实现局部精细控制。本功能允许用户额外上传一张黑白灰度图作为高度图（Heightmap），与原图像素一一对应，灰度值直接映射到 Z 轴高度，实现逐像素级别的高度控制。用户可以在 Photoshop 等工具中精确绘制高度图，替代或补充现有的按颜色分配高度方式。

## 术语表

- **Converter**：核心转换模块，负责将像素画图像转换为 3D 模型（3MF 格式）
- **Heightmap**：高度图，一张与原图尺寸对应的灰度图像，灰度值表示对应像素的 Z 轴高度
- **Heightmap_Loader**：高度图加载与预处理模块，负责读取、验证、缩放高度图
- **Relief_Builder**：2.5D 浮雕体素矩阵构建器（即现有 `_build_relief_voxel_matrix` 的扩展）
- **UI_Layout**：Gradio 前端界面布局模块
- **Pixel_Scale**：像素比例尺，单位为 mm/pixel
- **OPTICAL_LAYERS**：光学叠色层，固定为顶部 5 层（0.4mm），用于实现全彩光学混色
- **Height_Matrix**：高度矩阵，(H, W) 的浮点数组，每个像素对应一个高度值（单位 mm）
- **Grayscale_Value**：灰度值，范围 0-255，0 为纯黑，255 为纯白

## 需求

### 需求 1：高度图上传与验证

**用户故事：** 作为用户，我希望能上传一张灰度图作为高度图，以便精确控制浮雕模型每个像素的高度。

#### 验收标准

1. WHEN 用户开启 2.5D 浮雕模式, THE UI_Layout SHALL 显示高度图上传组件，支持 PNG、JPG、BMP 格式的图像文件
2. WHEN 用户上传高度图, THE Heightmap_Loader SHALL 将图像转换为单通道灰度图（若为彩色图则取亮度通道）
3. WHEN 高度图上传成功, THE UI_Layout SHALL 在上传区域旁显示高度图缩略预览
4. IF 用户未上传高度图且开启了浮雕模式, THEN THE Converter SHALL 回退到现有的按颜色分配高度方式（color_height_map）

### 需求 2：高度图与原图尺寸对齐

**用户故事：** 作为用户，我希望高度图能自动与原图对齐，即使两者尺寸不完全一致也能正常工作。

#### 验收标准

1. WHEN 高度图尺寸与原图处理后的像素尺寸（target_w × target_h）不一致, THE Heightmap_Loader SHALL 使用双线性插值将高度图缩放至与原图相同的像素尺寸
2. WHEN 高度图缩放完成, THE Heightmap_Loader SHALL 输出一条日志，记录原始尺寸和缩放后尺寸
3. THE Heightmap_Loader SHALL 保证缩放后的高度图与原图像素一一对应，形状为 (target_h, target_w)

### 需求 3：灰度值到高度的映射

**用户故事：** 作为用户，我希望高度图中越黑的区域越高，越白的区域越低，并且可以控制最大高度范围。

#### 验收标准

1. THE Heightmap_Loader SHALL 将灰度值 0（纯黑）映射为最大浮雕高度，灰度值 255（纯白）映射为最小高度（底板厚度）
2. THE Heightmap_Loader SHALL 使用线性插值公式计算每个像素的高度：`height_mm = max_relief_height - (grayscale / 255.0) * (max_relief_height - base_thickness)`
3. THE Heightmap_Loader SHALL 复用现有的"最大浮雕高度"滑块（`slider_conv_auto_height_max`，范围 2.0-15.0mm，默认 5.0mm）作为高度图模式的最大高度参数，不新增额外滑块
4. THE Heightmap_Loader SHALL 将计算结果存储为 Height_Matrix，数据类型为 float32，单位为 mm

### 需求 4：基于高度图的体素矩阵构建

**用户故事：** 作为用户，我希望系统根据高度图逐像素构建浮雕体素矩阵，而非按颜色统一高度。

#### 验收标准

1. WHEN 用户提供了高度图, THE Relief_Builder SHALL 使用 Height_Matrix 逐像素确定每个位置的 Z 轴层数，替代现有的 color_height_map 逐颜色方式
2. THE Relief_Builder SHALL 为每个实心像素保留顶部 OPTICAL_LAYERS（5 层，0.4mm）作为光学叠色层
3. THE Relief_Builder SHALL 在光学叠色层下方填充 backing_color_id 材料作为基座层
4. THE Relief_Builder SHALL 根据 Height_Matrix 中的最大值确定体素矩阵的总 Z 层数
5. IF Height_Matrix 中某像素的高度值小于 OPTICAL_LAYERS 对应的厚度（0.4mm）, THEN THE Relief_Builder SHALL 将该像素的高度钳制为 OPTICAL_LAYERS 的最小厚度

### 需求 5：高度图模式的 UI 交互

**用户故事：** 作为用户，我希望高度图模式与现有浮雕控件协调工作，操作流程清晰。

#### 验收标准

1. WHEN 用户上传高度图, THE UI_Layout SHALL 隐藏"自动高度生成器"折叠面板和逐色高度调节滑块，因为高度图模式替代了按颜色分配高度
2. WHEN 用户移除已上传的高度图, THE UI_Layout SHALL 恢复显示"自动高度生成器"和逐色高度调节滑块
3. THE UI_Layout SHALL 复用现有的"最大浮雕高度"滑块（`slider_conv_auto_height_max`）作为高度图模式的最大高度控制，不新增额外滑块
4. WHEN 用户未开启 2.5D 浮雕模式, THE UI_Layout SHALL 隐藏高度图上传组件及相关控件

### 需求 6：高度图参数传递与集成

**用户故事：** 作为开发者，我希望高度图数据能正确传递到转换管线中，与现有架构无缝集成。

#### 验收标准

1. THE Converter SHALL 在 `convert_image_to_3d` 函数中接受新参数 `heightmap_path`（可选，字符串类型，高度图文件路径）
2. THE Converter SHALL 在 `convert_image_to_3d` 函数中接受新参数 `heightmap_max_height`（可选，浮点类型，最大浮雕高度，单位 mm）
3. WHEN `heightmap_path` 不为 None 且 `enable_relief` 为 True, THE Converter SHALL 优先使用高度图模式，忽略 `color_height_map` 参数
4. THE UI_Layout SHALL 将高度图文件路径和最大高度参数通过 Gradio 事件绑定传递给 `generate_final_model` 和 `process_batch_generation` 函数

### 需求 7：高度图预览反馈

**用户故事：** 作为用户，我希望在生成模型前能看到高度图的效果预览，确认高度分布是否符合预期。

#### 验收标准

1. WHEN 用户上传高度图并点击"预览"按钮, THE Converter SHALL 在状态栏显示高度图的统计信息，包括：最小高度、最大高度、平均高度（单位 mm）
2. WHEN 高度图模式激活, THE Converter SHALL 在 3D 预览（GLB）中体现逐像素的高度差异

### 需求 8：错误处理

**用户故事：** 作为用户，我希望在高度图有问题时得到清晰的错误提示。

#### 验收标准

1. IF 上传的高度图文件无法被读取为图像, THEN THE Heightmap_Loader SHALL 返回描述性错误信息并在 UI 状态栏显示
2. IF 高度图的宽高比与原图的宽高比偏差超过 20%, THEN THE Heightmap_Loader SHALL 在状态栏显示警告信息，提示用户高度图可能与原图不匹配
3. IF 高度图为全黑或全白（灰度值标准差小于 1.0）, THEN THE Heightmap_Loader SHALL 在状态栏显示警告信息，提示高度图缺乏高度变化
