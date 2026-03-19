# Lumina Studio Image Pipeline 模块架构文档

## 概述

图像转换系统已完成模块化重构。原 `converter.py`（4523行）和 `image_processing.py`（930行）被拆分为独立的 step 模块，原文件保留为薄包装层确保向后兼容。

系统包含两条流水线：

- **主流水线**（s01-s12）：完整的图像→3D模型转换，从 `converter.py` 拆出
- **图像处理子流水线**（p01-p06）：图像预处理与预览生成，从 `image_processing.py` 拆出
- **原子操作层**（processing_ops/）：可独立复用的图像处理算法

---

## 架构层次

```
core/pipeline/
├── __init__.py              ← 包初始化，导出公共接口
├── coordinator.py           ← 流水线总协调器
├── pipeline_utils.py        ← 共享工具函数
├── s01-s12_*.py             ← 主流水线步骤（图片→3D模型）
├── p01-p06_*.py             ← 图像处理子流水线步骤
└── processing_ops/          ← 原子图像处理操作
    ├── __init__.py
    ├── background_remover.py
    ├── bilateral_filter.py
    ├── ...
    └── wireframe_extractor.py

core/converter.py            ← 薄包装层（保留原有函数签名，委托给 pipeline）
core/image_processing.py     ← 薄编排层（保留原有 API，委托给 p01-p06）
```

---

## 一、编排层

| 文件                              | 职责                                                                   |
| --------------------------------- | ---------------------------------------------------------------------- |
| `core/pipeline/__init__.py`       | 包初始化，导出公共接口                                                 |
| `core/pipeline/coordinator.py`    | 流水线总协调器，按顺序调度各 step 模块，替代原 converter.py 的巨型函数 |
| `core/pipeline/pipeline_utils.py` | 流水线共享工具函数（日志、路径处理、通用辅助）                         |

---

## 二、主流水线 s01-s12（图片→3D模型）

原 `converter.py` 的核心转换逻辑，拆分为 12 个独立步骤。

### 加工顺序

```
图片输入 + LUT文件
  │
  ▼
┌─────────────────────────────────────────────┐
│ s01  输入校验                                │  图片格式、尺寸、参数合法性
├─────────────────────────────────────────────┤
│ s02  图像预处理                              │  缩放、去背景、滤波、量化
├─────────────────────────────────────────────┤
│ s03  颜色替换                                │  量化颜色映射到 LUT 调色板
├─────────────────────────────────────────────┤
│ s04  调试预览                                │  中间步骤可视化（开发用）
├─────────────────────────────────────────────┤
│ s05  预览图生成                              │  最终效果预览供前端展示
├─────────────────────────────────────────────┤
│ s06  体素构建                                │  2D像素图 → 3D体素数据
├─────────────────────────────────────────────┤
│ s07  网格生成                                │  体素 → 三角网格（HiFi/PixelArt）
├─────────────────────────────────────────────┤
│ s08  辅助网格                                │  底板、边框等附加3D结构
├─────────────────────────────────────────────┤
│ s09  3MF导出                                 │  网格打包为全彩打印文件
├─────────────────────────────────────────────┤
│ s10  色彩配方                                │  打印所需颜色配比信息
├─────────────────────────────────────────────┤
│ s11  GLB预览                                 │  生成GLB供Three.js渲染
├─────────────────────────────────────────────┤
│ s12  结果组装                                │  汇总所有输出，构建返回结果
└─────────────────────────────────────────────┘
  │
  ▼
输出：3MF文件 + GLB预览 + 2D预览图 + 配色报告
```

### 各步骤详细说明

| 序号 | 文件                        | 职责                                                               |
| ---- | --------------------------- | ------------------------------------------------------------------ |
| s01  | `s01_input_validation.py`   | 输入校验：检查图片格式、尺寸、参数合法性                           |
| s02  | `s02_image_processing.py`   | 图像预处理：调用 processing_ops 完成缩放、去背景、滤波、量化       |
| s03  | `s03_color_replacement.py`  | 颜色替换：将量化后的颜色映射到 LUT 调色板颜色                      |
| s04  | `s04_debug_preview.py`      | 调试预览：生成中间步骤的可视化图片（开发调试用）                   |
| s05  | `s05_preview_generation.py` | 预览图生成：生成最终效果预览图供前端展示                           |
| s06  | `s06_voxel_building.py`     | 体素构建：将 2D 像素图转换为 3D 体素数据                           |
| s07  | `s07_mesh_generation.py`    | 网格生成：将体素数据转换为三角网格（HighFidelity/PixelArt Mesher） |
| s08  | `s08_auxiliary_meshes.py`   | 辅助网格：生成底板、边框等附加 3D 结构                             |
| s09  | `s09_export_3mf.py`         | 3MF 导出：将网格数据打包为 3MF 全彩打印文件                        |
| s10  | `s10_color_recipe.py`       | 色彩配方：生成打印所需的颜色配比信息                               |
| s11  | `s11_glb_preview.py`        | GLB 预览：生成 GLB 格式的 3D 预览文件供前端 Three.js 渲染          |
| s12  | `s12_result_assembly.py`    | 结果组装：汇总所有输出文件，构建最终返回结果                       |

---

## 三、图像处理子流水线 p01-p06

原 `image_processing.py` 的处理逻辑，拆分为 6 个独立步骤。

### 加工顺序

```
图片输入 + LUT文件
  │
  ▼
┌─────────────────────────────────────────────┐
│ p01  预览校验                                │  验证预览请求参数和图片
├─────────────────────────────────────────────┤
│ p02  LUT元数据                               │  加载和解析LUT颜色信息
├─────────────────────────────────────────────┤
│ p03  核心处理                                │  缩放→去背景→滤波→量化→匹配
├─────────────────────────────────────────────┤
│ p04  缓存构建                                │  处理结果缓存，避免重复计算
├─────────────────────────────────────────────┤
│ p05  调色板提取                              │  从处理后图像提取使用的颜色
├─────────────────────────────────────────────┤
│ p06  打印床渲染                              │  生成打印床布局预览图
└─────────────────────────────────────────────┘
  │
  ▼
输出：2D预览图 + 缓存字典 + 调色板
```

### 各步骤详细说明

| 序号 | 文件                        | 职责                                                         |
| ---- | --------------------------- | ------------------------------------------------------------ |
| p01  | `p01_preview_validation.py` | 预览校验：验证预览请求的参数和图片                           |
| p02  | `p02_lut_metadata.py`       | LUT 元数据：加载和解析 LUT 文件的颜色信息                    |
| p03  | `p03_core_processing.py`    | 核心处理：编排图像处理的主流程（缩放→去背景→滤波→量化→匹配） |
| p04  | `p04_cache_building.py`     | 缓存构建：构建处理结果缓存，避免重复计算                     |
| p05  | `p05_palette_extraction.py` | 调色板提取：从处理后的图像中提取使用的颜色调色板             |
| p06  | `p06_bed_rendering.py`      | 打印床渲染：生成打印床布局的预览图                           |

---

## 四、原子图像处理操作 (processing_ops/)

每个算法独立一个文件，可被任意 step 模块引用调用。

| 文件                        | 职责                                          |
| --------------------------- | --------------------------------------------- |
| `__init__.py`               | 包初始化，导出所有操作函数                    |
| `background_remover.py`     | 去除图片背景（透明/白色背景处理）             |
| `bilateral_filter.py`       | 双边滤波：保边去噪                            |
| `median_filter.py`          | 中值滤波：去除椒盐噪声                        |
| `image_scaler.py`           | 图像缩放：按目标尺寸缩放图片                  |
| `kmeans_quantizer.py`       | K-Means 量化：将图像颜色减少到指定数量        |
| `lut_loader.py`             | LUT 加载器：读取 .npy 格式的 LUT 调色板文件   |
| `lut_color_matcher.py`      | LUT 颜色匹配：将像素颜色匹配到最近的 LUT 颜色 |
| `hue_aware_matcher.py`      | 色相感知匹配：基于色相权重的高级颜色匹配算法  |
| `svg_rasterizer.py`         | SVG 栅格化：将 SVG 矢量图转为位图             |
| `wireframe_extractor.py`    | 线框提取：从图像中提取线框/轮廓               |
| `isolated_pixel_cleanup.py` | 孤立像素清理：去除量化后的孤立噪点像素        |

---

## 五、兼容层

原文件保留为薄包装层，确保所有外部导入（api/、ui/、workers/）无需修改。

| 文件                       | 职责                                                           |
| -------------------------- | -------------------------------------------------------------- |
| `core/converter.py`        | 薄包装层：保留原有函数签名，内部委托给 coordinator + step 模块 |
| `core/image_processing.py` | 薄编排层：保留原有 API，内部委托给 p01-p06 模块                |

---

## 六、数据流概览

```
image_path + lut_path
       │
       ▼
  s01 输入校验
       │
       ▼
  s02 图像预处理（调用 processing_ops）
       │
       ├── matched_rgb      (H,W,3) uint8  匹配后的RGB图像
       ├── material_matrix   (H,W,N) int    每像素的材料堆叠ID
       └── mask_solid        (H,W)   bool   实体/透明掩码
       │
       ▼
  s03 颜色替换
       │
       ▼
  s06 体素构建 → full_matrix (Z,H,W) int
       │
       ▼
  s07 网格生成 → trimesh.Scene (多材质mesh)
       │
       ▼
  s08 辅助网格 + s09 3MF导出
       │
       ├── 3MF文件  → output/*.3mf
       ├── GLB预览  → output/*.glb (s11)
       ├── 2D预览   → PIL.Image (s05)
       └── 配色报告  → output/*.html (s10)
```

---

## 七、测试文件

| 文件                                       | 职责                                  |
| ------------------------------------------ | ------------------------------------- |
| `tests/test_pipeline_step_properties.py`   | step 模块的 Property-Based 测试       |
| `tests/test_pipeline_step_modules_unit.py` | step 模块的单元测试                   |
| `tests/test_coordinator_properties.py`     | coordinator 的 Property-Based 测试    |
| `tests/test_processing_ops_properties.py`  | processing_ops 的 Property-Based 测试 |
| `tests/test_processing_ops_unit.py`        | processing_ops 的单元测试             |
| `tests/test_backward_compat_properties.py` | 向后兼容性的 Property-Based 测试      |

运行测试：

```bash
# 运行全部 Python 测试
python -m pytest tests/ -v

# 只运行 pipeline 相关测试
python -m pytest tests/test_pipeline_step_properties.py tests/test_pipeline_step_modules_unit.py tests/test_coordinator_properties.py tests/test_processing_ops_properties.py tests/test_processing_ops_unit.py tests/test_backward_compat_properties.py -v

# 带统计信息
python -m pytest tests/ --hypothesis-show-statistics
```

---

## 八、重构统计

| 指标                     | 重构前 | 重构后                |
| ------------------------ | ------ | --------------------- |
| converter.py 行数        | 4523   | ~749（薄包装层）      |
| image_processing.py 行数 | 930    | ~250（薄编排层）      |
| 新增模块文件             | —      | 30 个                 |
| 新增测试文件             | —      | 6 个（~340 测试用例） |
| api/frontend/ui 修改     | —      | 零修改                |
