# 实现计划：高度图浮雕模式（Heightmap Relief Mode）

## 概述

新增独立模块 `core/heightmap_loader.py` 实现高度图的加载、验证、缩放和灰度映射。扩展 `core/converter.py` 中的转换管线支持高度图参数。调整 `ui/layout_new.py` 布局，新增高度图上传/预览组件，提取最大高度滑块为独立组件，实现可见性联动。参数通过 UI → callbacks → converter → heightmap_loader → relief_builder 完整传递。

## 任务

- [x] 1. 创建核心模块 `core/heightmap_loader.py`
  - [x] 1.1 实现 `HeightmapLoader._to_grayscale` 静态方法
    - 接收 np.ndarray 图像（可能为灰度、RGB 或 RGBA）
    - 彩色图使用 `cv2.cvtColor` 转换为灰度（取亮度通道）
    - 返回 (H, W) uint8 灰度数组
    - _需求: 1.2_

  - [x] 1.2 实现 `HeightmapLoader._resize_to_target` 静态方法
    - 使用 `cv2.resize` 双线性插值（`INTER_LINEAR`）缩放灰度图至 (target_w, target_h)
    - 缩放后输出日志记录原始尺寸和目标尺寸
    - 返回 (target_h, target_w) uint8 数组
    - _需求: 2.1, 2.2, 2.3_

  - [x] 1.3 实现 `HeightmapLoader._map_grayscale_to_height` 静态方法
    - 公式: `height_mm = max_relief_height - (grayscale / 255.0) * (max_relief_height - base_thickness)`
    - 使用 NumPy 向量化计算，返回 (H, W) float32 数组，单位 mm
    - _需求: 3.1, 3.2, 3.4_

  - [x] 1.4 实现 `HeightmapLoader._check_aspect_ratio` 静态方法
    - 计算高度图与目标图的宽高比偏差：`|w1/h1 - w2/h2| / (w2/h2)`
    - 偏差超过 20% 返回警告字符串，否则返回 None
    - _需求: 8.2_

  - [x] 1.5 实现 `HeightmapLoader._check_contrast` 静态方法
    - 计算灰度图标准差，小于 1.0 返回警告字符串，否则返回 None
    - _需求: 8.3_

  - [x] 1.6 实现 `HeightmapLoader.load_and_validate` 静态方法
    - 读取图像文件（`cv2.imread`），失败时返回 `success=False` + 错误信息
    - 调用 `_to_grayscale` 转换为灰度
    - 生成缩略预览图（用于 UI 显示）
    - 返回 dict: `{success, grayscale, original_size, thumbnail, warnings, error}`
    - _需求: 1.1, 1.2, 1.3, 8.1_

  - [x] 1.7 实现 `HeightmapLoader.load_and_process` 静态方法
    - 完整处理流程：加载 → 验证 → 灰度转换 → 宽高比检查 → 缩放 → 对比度检查 → 高度映射
    - 计算统计信息：min_mm, max_mm, avg_mm
    - 返回 dict: `{success, height_matrix, stats, warnings, error}`
    - _需求: 1.2, 2.1, 2.3, 3.1, 3.2, 3.3, 3.4, 8.1, 8.2, 8.3_

- [x] 2. 检查点 - HeightmapLoader 模块验证
  - 确保所有测试通过，如有问题请询问用户。

- [x] 3. 扩展 `core/converter.py` 转换管线
  - [x] 3.1 扩展 `convert_image_to_3d` 函数签名
    - 新增参数 `heightmap_path: Optional[str] = None`
    - 新增参数 `heightmap_max_height: Optional[float] = None`
    - 在 Step 5（Build Voxel Matrix）中添加高度图模式分支：
      - 当 `heightmap_path` 不为 None 且 `enable_relief=True` 时，调用 `HeightmapLoader.load_and_process`
      - 将返回的 `height_matrix` 传入 `_build_relief_voxel_matrix`
      - 处理失败时回退到 `color_height_map` 模式
    - _需求: 6.1, 6.2, 6.3_

  - [x] 3.2 扩展 `_build_relief_voxel_matrix` 函数
    - 新增参数 `height_matrix: Optional[np.ndarray] = None`
    - 当 `height_matrix` 不为 None 时，使用逐像素高度替代 `color_height_map` 逻辑
    - 使用 NumPy 向量化操作替代逐像素 Python 循环，提升性能
    - 高度钳制：像素高度 < OPTICAL_LAYERS 厚度（0.4mm）时钳制为最小值
    - 体素矩阵 Z 维度 = ceil(max(height_matrix[mask_solid]) / LAYER_HEIGHT)
    - _需求: 4.1, 4.2, 4.3, 4.4, 4.5_

  - [x] 3.3 扩展 `generate_final_model` 函数签名
    - 新增参数 `heightmap_path=None` 和 `heightmap_max_height=None`
    - 透传至 `convert_image_to_3d`
    - _需求: 6.1, 6.2_

  - [x] 3.4 在 `convert_image_to_3d` 中添加高度图统计信息输出
    - 高度图模式激活时，在状态消息中追加：最小高度、最大高度、平均高度
    - GLB 预览中体现逐像素高度差异（已由 `_create_preview_mesh` 自动处理）
    - _需求: 7.1, 7.2_

- [x] 4. 检查点 - Converter 扩展验证
  - 确保所有测试通过，如有问题请询问用户。

- [x] 5. 调整 UI 布局 `ui/layout_new.py`
  - [x] 5.1 提取 `slider_conv_auto_height_max` 为独立组件
    - 将该滑块从自动高度生成器 Accordion 内部移至外部
    - Accordion 仅保留模式选择和应用按钮
    - 确保现有功能不受影响（滑块值仍可被 Accordion 内逻辑读取）
    - _需求: 3.3, 5.3_

  - [x] 5.2 新增高度图上传组件 `image_conv_heightmap`
    - 类型: `gr.Image`，`type="filepath"`，支持 PNG/JPG/BMP
    - 放置在浮雕模式复选框下方
    - 仅在浮雕模式开启时可见
    - _需求: 1.1, 5.4_

  - [x] 5.3 新增高度图预览组件 `image_conv_heightmap_preview`
    - 类型: `gr.Image`，不可交互
    - 放置在上传组件旁边
    - 上传成功后显示缩略预览
    - _需求: 1.3_

  - [x] 5.4 实现高度图上传回调 `on_heightmap_upload`
    - 调用 `HeightmapLoader.load_and_validate` 验证高度图
    - 成功时：显示预览、隐藏逐色高度滑块和自动高度 Accordion
    - 失败时：在状态栏显示错误信息
    - 警告信息追加到状态栏
    - _需求: 1.3, 5.1, 5.2, 8.1, 8.2, 8.3_

  - [x] 5.5 实现高度图移除回调 `on_heightmap_clear`
    - 隐藏预览组件
    - 恢复显示逐色高度滑块和自动高度 Accordion
    - _需求: 5.2_

  - [x] 5.6 实现浮雕模式切换时的高度图组件可见性联动
    - 浮雕模式关闭时隐藏高度图上传组件及预览
    - 浮雕模式开启时显示高度图上传组件
    - _需求: 5.4_

- [x] 6. 参数传递链集成
  - [x] 6.1 扩展 `process_batch_generation` 函数
    - 新增参数 `heightmap_path=None` 和 `heightmap_max_height=None`
    - 将参数加入 `args` 元组，透传至 `generate_final_model`
    - _需求: 6.4_

  - [x] 6.2 绑定 Gradio 事件
    - 生成按钮点击事件中添加 `image_conv_heightmap` 和 `slider_conv_auto_height_max` 作为输入
    - 确保高度图路径和最大高度值正确传递到 `process_batch_generation`
    - _需求: 6.4_

- [x] 7. 检查点 - 完整功能集成验证
  - 确保所有测试通过，如有问题请询问用户。

- [x] 8. 属性测试 `tests/test_heightmap_properties.py`
  - [x] 8.1 编写属性测试：灰度映射公式正确性
    - **Property 1: 灰度映射公式正确性**
    - 生成器：`st.integers(0, 255)`, `st.floats(2.0, 15.0)`, `st.floats(0.1, 2.0)`
    - 验证输出值域在 [base_thickness, max_relief_height] 范围内
    - 验证 g=0 时输出 max_relief_height, g=255 时输出 base_thickness
    - **验证: 需求 3.1, 3.2**

  - [x] 8.2 编写属性测试：高度图处理输出形状与类型不变量
    - **Property 2: 高度图处理输出形状与类型不变量**
    - 生成器：随机 (H, W, C) 图像数组 + 随机目标尺寸
    - 验证返回形状为 (target_h, target_w)，dtype 为 float32
    - 验证所有值在 [base_thickness, max_relief_height] 范围内
    - **验证: 需求 1.2, 2.1, 2.3, 3.4**

  - [x] 8.3 编写属性测试：体素矩阵结构不变量
    - **Property 3: 体素矩阵结构不变量**
    - 生成器：随机 Height_Matrix + material_matrix + mask_solid
    - 验证实心像素总层数 = max(OPTICAL_LAYERS, ceil(height/LAYER_HEIGHT))
    - 验证顶部 5 层材料来自 material_matrix，下方层为 backing_color_id
    - 验证非实心像素所有层 = -1
    - **验证: 需求 4.1, 4.2, 4.3, 4.4**

  - [x] 8.4 编写属性测试：模式优先级正确性
    - **Property 4: 模式优先级正确性**
    - 生成器：随机组合 heightmap_path (None/有效路径) + enable_relief (True/False) + color_height_map
    - 验证 heightmap_path 不为 None 且 enable_relief=True 时使用高度图模式
    - 验证 heightmap_path 为 None 时回退到 color_height_map 模式
    - **验证: 需求 1.4, 6.3**

  - [x] 8.5 编写属性测试：验证警告条件
    - **Property 5: 验证警告条件**
    - 生成器：随机尺寸对 + 随机灰度图
    - 验证宽高比偏差大于 20% 时返回警告
    - 验证灰度标准差小于 1.0 时返回警告
    - **验证: 需求 8.2, 8.3**

  - [x] 8.6 编写属性测试：无效文件错误处理
    - **Property 6: 无效文件错误处理**
    - 生成器：`st.binary()` 生成随机字节序列写入临时文件
    - 验证 `load_and_validate` 返回 `success=False` 且 `error` 非空
    - **验证: 需求 8.1**

- [x] 9. 单元测试 `tests/test_heightmap_unit.py`
  - [x] 9.1 编写单元测试：灰度映射边界条件
    - 纯黑图（全 0）映射为最大高度
    - 纯白图（全 255）映射为底板厚度
    - 中灰图（128）映射为中间值
    - _需求: 3.1_

  - [x] 9.2 编写单元测试：彩色图转灰度
    - 验证 RGB 图像正确转换为灰度
    - 验证 RGBA 图像正确处理 alpha 通道
    - _需求: 1.2_

  - [x] 9.3 编写单元测试：尺寸缩放
    - 验证不同尺寸高度图正确缩放至目标尺寸
    - 验证缩放后形状为 (target_h, target_w)
    - _需求: 2.1, 2.3_

  - [x] 9.4 编写单元测试：高度钳制
    - 验证高度值小于 OPTICAL_LAYERS 厚度时被钳制为最小值
    - _需求: 4.5_

  - [x] 9.5 编写单元测试：错误处理
    - 验证无效文件返回描述性错误
    - 验证宽高比偏差警告
    - 验证低对比度警告
    - _需求: 8.1, 8.2, 8.3_

- [x] 10. 最终检查点 - 全部测试通过
  - 确保所有测试通过，如有问题请询问用户。

## 备注

- 所有任务均为必须
- 每个任务引用了具体需求编号，确保可追溯性
- 检查点任务确保增量验证
- 属性测试使用 Hypothesis 库，验证通用正确性属性
- 单元测试验证具体边界条件和示例场景
