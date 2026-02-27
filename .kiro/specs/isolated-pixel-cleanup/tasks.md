# 实现计划：孤立像素清理（Isolated Pixel Cleanup）

## 概述

在 LUT 颜色匹配之后、voxel matrix 构建之前，新增独立模块 `core/isolated_pixel_cleanup.py` 实现孤立像素检测与替换。通过 `LuminaImageProcessor` 实例属性控制执行，UI 层添加 Checkbox 开关，调用链函数添加 `enable_cleanup` 参数透传。

## 任务

- [x] 1. 创建核心模块 `core/isolated_pixel_cleanup.py`
  - [x] 1.1 实现 `_encode_stacks` 函数：将 (H,W,5) 材料矩阵编码为 (H,W) 整数矩阵
    - 编码公式：`layer0 * B^4 + layer1 * B^3 + layer2 * B^2 + layer3 * B + layer4`，B = max(material_id) + 1
    - 使用 NumPy 向量化操作，dtype 为 int64
    - _需求: 1.1, 4.1_
  - [x] 1.2 编写属性测试：堆叠编码唯一性
    - **Property 1: 堆叠编码唯一性**
    - 随机生成两个 5 层堆叠，验证编码相同当且仅当堆叠相同
    - **验证: 需求 1.1**
  - [x] 1.3 实现 `_detect_isolated` 函数：检测孤立像素，返回 (H,W) 布尔掩码
    - 使用 8 方向切片比较（非 np.roll），正确处理边界像素（3 或 5 邻居）
    - 孤立 = 与所有实际邻居的堆叠编码均不同
    - _需求: 1.2, 1.3, 4.1_
  - [x] 1.4 编写属性测试：孤立像素检测正确性
    - **Property 2: 孤立像素检测正确性**
    - 随机生成小尺寸编码矩阵（3-20），验证孤立判定符合定义（含边界像素）
    - **验证: 需求 1.2, 1.3**
  - [x] 1.5 实现 `_find_neighbor_mode` 函数：对每个孤立像素找到邻域众数堆叠编码
    - 统计 8 邻域中各堆叠编码出现次数，选择最多的作为替换值
    - 多个并列众数时确定性选择其中之一
    - _需求: 2.1, 2.2_
  - [x] 1.6 编写属性测试：邻域众数替换正确性
    - **Property 3: 邻域众数替换正确性**
    - 随机生成含孤立像素的矩阵，验证替换值是邻域众数之一
    - **验证: 需求 2.1, 2.2, 5.1**
  - [x] 1.7 实现 `cleanup_isolated_pixels` 主函数
    - 接收 `material_matrix, matched_rgb, lut_rgb, ref_stacks`，返回清理后的副本
    - 调用 `_encode_stacks` → `_detect_isolated` → `_find_neighbor_mode`
    - 同时更新 material_matrix 和 matched_rgb（通过 LUT 反查保持一致性）
    - 输出清理统计信息（孤立像素数、替换数、百分比）
    - 单轮清理，不修改输入数组
    - _需求: 2.3, 4.3, 5.1, 5.2, 7.2, 8.1, 8.2, 8.3, 8.4, 8.5_
  - [x] 1.8 编写属性测试：LUT 一致性
    - **Property 4: LUT 一致性**
    - 随机生成 material_matrix 和对应 LUT，验证清理后 RGB-堆叠对应同一 LUT 条目
    - **验证: 需求 2.3, 5.2, 8.2, 8.4**
  - [x] 1.9 编写属性测试：非孤立像素不变性
    - **Property 5: 非孤立像素不变性**
    - 随机生成矩阵，验证非孤立像素清理前后值完全相同
    - **验证: 需求 4.3, 8.1**
  - [x] 1.10 编写属性测试：纯函数不修改输入
    - **Property 8: 纯函数不修改输入**
    - 随机生成矩阵，验证调用后输入数组内容不变
    - **验证: 需求 7.2**

- [x] 2. 检查点 - 核心模块完成
  - 确保所有测试通过，如有问题请向用户确认。

- [x] 3. 集成到 `LuminaImageProcessor`（`core/image_processing.py`）
  - [x] 3.1 在 `__init__` 方法中添加 `self.enable_cleanup = True` 实例属性
    - _需求: 7.3, 7.4_
  - [x] 3.2 在 `process_image` 方法中添加孤立像素清理后处理调用
    - 在 `_process_high_fidelity_mode` 返回后、背景移除逻辑之前插入
    - 仅当 `modeling_mode == HIGH_FIDELITY and self.enable_cleanup` 时执行
    - 使用 try/except ImportError 捕获模块导入失败，静默跳过
    - 像素模式下自动跳过清理
    - _需求: 3.1, 3.2, 7.3, 7.4, 7.5_
  - [x] 3.3 编写属性测试：关闭状态等价性
    - **Property 7: 关闭状态等价性**
    - 验证 enable_cleanup=False 时输出与原始 LUT 匹配结果完全相同
    - **验证: 需求 6.3**
  - [x] 3.4 编写属性测试：清理单调性
    - **Property 6: 清理单调性**
    - 随机生成矩阵，验证二次检测孤立数 ≤ 首次
    - **验证: 需求 5.3**
  - [x] 3.5 编写属性测试：统计信息正确性
    - **Property 9: 统计信息正确性**
    - 随机生成矩阵，验证统计数值与实际检测结果一致
    - **验证: 需求 8.3**

- [x] 4. 修改调用链函数（`core/converter.py`）
  - [x] 4.1 为 `generate_preview_cached` 添加 `enable_cleanup` 参数
    - 在创建 `LuminaImageProcessor` 后设置 `processor.enable_cleanup = enable_cleanup`
    - _需求: 6.2, 7.6_
  - [x] 4.2 为 `convert_image_to_3d` 添加 `enable_cleanup` 参数
    - 在创建 `LuminaImageProcessor` 后设置 `processor.enable_cleanup = enable_cleanup`
    - _需求: 6.2, 7.6_
  - [x] 4.3 为 `generate_final_model` 添加 `enable_cleanup` 参数
    - 透传给 `convert_image_to_3d`
    - _需求: 6.2, 7.6_

- [x] 5. 修改 UI 层（`ui/layout_new.py`）
  - [x] 5.1 在 `create_converter_tab_content` 的 Advanced Accordion 内添加 Checkbox
    - 标签："孤立像素清理 | Isolated Pixel Cleanup"，默认值 True
    - 放在 tolerance slider 之后
    - _需求: 6.1_
  - [x] 5.2 为 `generate_preview_cached_with_fit` 添加 `enable_cleanup` 参数并透传
    - 更新预览按钮的 inputs 列表，末尾追加 Checkbox 组件
    - _需求: 6.2, 7.6_
  - [x] 5.3 为 `process_batch_generation` 添加 `enable_cleanup` 参数并透传给 `generate_final_model`
    - 更新生成按钮的 inputs 列表，末尾追加 Checkbox 组件
    - _需求: 6.2, 7.6_
  - [x] 5.4 实现像素模式下 Checkbox 禁用逻辑
    - 当 modeling_mode 切换为像素模式时，设置 Checkbox interactive=False 并显示提示
    - 切换回高保真模式时恢复 interactive=True
    - _需求: 6.4_

- [x] 6. 创建单元测试文件 `tests/test_isolated_pixel_cleanup.py`
  - [x] 6.1 编写核心单元测试
    - 编码计算：手工构造已知堆叠，验证编码值
    - 3×3 矩阵孤立检测：中心像素与所有邻居不同 → 孤立
    - 3×3 矩阵非孤立：中心像素与至少一个邻居相同 → 非孤立
    - 边界像素处理：角落像素（3 邻居）和边缘像素（5 邻居）
    - 1×1 图像：无邻居，不判定为孤立
    - 全同色图像：无孤立像素
    - _需求: 1.1, 1.2, 1.3, 2.1, 4.3_
  - [x] 6.2 编写集成相关单元测试
    - ImportError 降级：模拟模块不存在，验证跳过清理
    - 像素模式跳过：验证像素模式下不执行清理
    - 高保真模式执行：验证高保真模式下执行清理
    - _需求: 3.1, 3.2, 7.5_

- [x] 7. 最终检查点 - 确保所有测试通过
  - 确保所有测试通过，如有问题请向用户确认。

## 备注

- 所有任务均为必须任务
- 每个任务引用了具体的需求编号，确保可追溯性
- 属性测试使用 Hypothesis 库，验证设计文档中的 9 个正确性属性
- 单元测试聚焦具体示例和边界情况
- 检查点确保增量验证
