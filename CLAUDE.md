# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Lumina Studio is a physics-based multi-material FDM full-color 3D printing system. It converts arbitrary images into printable full-color 3D models through optical color mixing (transmissive mixing) by stacking transparent filaments. The system uses a closed-loop calibration approach: print physical calibration boards, photograph them to extract actual RGB values, generate LUT lookup tables, and use KDTree nearest-neighbor matching to map image pixels to print layer combinations.

## Architecture

### Layered Architecture

- **Core** (`core/`): Pure business logic, zero UI dependencies
- **API** (`api/`): FastAPI routes + Pydantic schemas, calls Core
- **Workers** (`api/workers/`): CPU-intensive tasks via ProcessPoolExecutor in isolated processes
- **UI** (`ui/`): Gradio components + event handlers (legacy Python frontend)
- **Frontend** (`frontend/`): React + TypeScript SPA, communicates with API via HTTP

### Key Design Patterns

- **Coordinator**: `converter.py` orchestrates image→3D pipeline, delegating to specialized modules
- **Strategy**: `get_mesher()` selects mesh generation strategy (HighFidelityMesher / PixelArtMesher)
- **Thread Separation**: Worker functions accept only file paths and scalar params (pickle-safe), write large results to temp files
- **Centralized Config**: All constants in `config.py` (PrinterConfig, ColorSystem, ModelingMode, BedManager, etc.)

### Four Core Modules

1. **Calibration Generator** — Generates precision calibration boards for physical testing
2. **Color Extractor** — Digitizes photographed calibration boards into LUT files
3. **Image Converter** — Converts images to 3D models using calibration data
4. **Image Vectorizer** — Converts raster images to SVG vector graphics via neroued_vectorizer

## Build & Development Commands

```bash
# Install dependencies
pip install -r requirements.txt
cd frontend && npm install

# Start Gradio monolithic mode
python main.py

# Start frontend + backend separated mode (Windows)
start_dev.bat
# Or manually:
python api_server.py          # Backend :8000
cd frontend && npm run dev    # Frontend :5173

# Run Python tests
python -m pytest tests/ -v

# Run frontend tests
cd frontend && npx vitest --run

# Run Property-Based tests with statistics
python -m pytest tests/ --hypothesis-show-statistics

# Docker
docker build -t lumina-layers .
docker run -p 7860:7860 lumina-layers


# Build frontend for production
cd frontend && tsc -b && vite build
```

## Technology Stack

### Backend (Python)

- **Language**: Python 3.x
- **UI Framework**: Gradio 6.0+
- **API Framework**: FastAPI + Uvicorn (port 8000)
- **Geometry**: Trimesh 4.0+ (mesh generation & export)
- **Computer Vision**: OpenCV (perspective correction, color extraction)
- **Scientific Computing**: NumPy, SciPy, Numba (JIT acceleration)
- **Color Matching**: SciPy KDTree (nearest-neighbor search)
- **Image I/O**: Pillow, pillow-heif (HEIC/HEIF support)
- **Vector Engine**: svgelements, Shapely, mapbox-earcut
- **Vectorizer**: neroued-vectorizer (C++ core, raster→SVG conversion)
- **3MF Export**: Trimesh + lxml + custom BambuStudio metadata writer

### Frontend (TypeScript)

- **Framework**: React 19 + TypeScript 5.8
- **Build Tool**: Vite 6
- **3D Rendering**: Three.js + @react-three/fiber + @react-three/drei
- **State Management**: Zustand 5
- **HTTP Client**: Axios
- **Styling**: Tailwind CSS 4
- **Testing**: Vitest 4 + fast-check (Property-Based Testing)

## Project Structure

```
Lumina-Layers/
├── main.py                 # Gradio monolithic entry point
├── api_server.py           # FastAPI backend entry (uvicorn :8000)
├── config.py               # Centralized configuration
├── core/                   # Pure business logic (no UI deps)
│   ├── converter.py        # Image→3D coordinator
│   ├── calibration.py      # Calibration board generation
│   ├── extractor.py        # Color data extraction from photos
│   ├── image_processing.py # Color quantization & matching
│   ├── mesh_generators.py  # Mesh strategies (HiFi / PixelArt)
│   ├── vector_engine.py    # SVG→3D native vector engine
│   ├── color_replacement.py # Connected-region color replacement
│   ├── heightmap_loader.py # 2.5D relief heightmap processing
│   └── ...
├── api/                    # FastAPI REST backend
│   ├── routers/            # Domain routes (/api/calibration, /converter, etc.)
│   ├── schemas/            # Pydantic request/response models
│   ├── workers/            # CPU-intensive worker functions (process pool)
│   ├── file_bridge.py      # Upload→ndarray/tempfile, HEIC conversion
│   ├── session_store.py    # Session state storage
│   └── worker_pool.py      # ProcessPoolExecutor lifecycle
├── frontend/src/           # React + TypeScript SPA
│   ├── api/                # Axios API clients (per domain)
│   ├── components/         # React components (sections/, ui/, widget/)
│   ├── stores/             # Zustand state stores
│   ├── hooks/              # Custom React hooks
│   └── __tests__/          # Unit + Property-Based tests
├── ui/                     # Gradio UI components (legacy)
├── utils/                  # Helpers (3MF writer, LUT manager, stats)
├── tests/                  # Python tests (pytest + Hypothesis)
├── assets/                 # Reference calibration images & data
└── lut-npy预设/            # Community LUT presets by brand
```

## Coding Standards

### Python

- All new functions require type hints
- Prefer `numpy` vectorized operations over `for` loops
- Bilingual Google-Style docstrings (English summary + Chinese summary):

```python
def func(param: str) -> int:
    """English summary.
    中文摘要。

    Args:
        param (str): English description. (中文描述)

    Returns:
        int: English description. (中文描述)
    """
```

- No emoji in variable or function names
- Worker functions must be pickle-serializable (top-level functions, scalar/path args only)

### TypeScript / React

- Functional components with hooks
- Zustand for state management (no Redux)
- API clients organized by domain in `frontend/src/api/`
- Tailwind CSS for styling, dark/light theme via `themeConfig.ts`

### Frontend Feature Checklist

All new frontend features with user-visible UI must satisfy:

1. **i18n**: All user-facing text must go through `frontend/src/i18n/translations.ts` — no hardcoded Chinese or English strings in components. Use the `useI18n()` hook to retrieve translations.
2. **Theme**: All colors, backgrounds, and borders must use Tailwind theme variables or `themeConfig.ts` tokens. Components must render correctly in both dark and light modes. Never use hardcoded color values (e.g. `#fff`, `bg-white`).
3. **Backend-only features** (core/, api/, utils/) are exempt from i18n and theme requirements.

## Testing

### Python (pytest + Hypothesis)

- Unit tests: `tests/test_*_unit.py`
- Property-Based tests: `tests/test_*_properties.py`
- Run: `python -m pytest tests/ -v`

### Frontend (Vitest + fast-check)

- Unit tests: `frontend/src/__tests__/*.test.ts(x)`
- Property-Based tests: `frontend/src/__tests__/*.property.test.ts`
- Run: `cd frontend && npx vitest --run`

## Performance Considerations

- K-Means color quantization reduces matching complexity (1M pixels → 64 colors)
- KD-Tree spatial index for O(log n) color lookup
- Hue-aware matching engine (`color_matching_hue_aware.py`) improves color fidelity
- NumPy vectorized operations for voxel matrix filling
- Large model preview downsampling (>1600px)
- Numba JIT for critical computation paths
- ProcessPoolExecutor isolates CPU-intensive tasks from asyncio event loop
- `Cache-Control: no-cache` headers ensure preview refresh after color replacement

## Supported Color Systems

| Mode             | Filaments | Colors | Notes                             |
| ---------------- | --------- | ------ | --------------------------------- |
| CMYW             | 4         | 1024   | Cyan/Magenta/Yellow/White         |
| RYBW             | 4         | 1024   | Red/Yellow/Blue/White             |
| 6-Color          | 6         | 1296   | Extended six-color                |
| 8-Color Max      | 8         | 2738   | Professional (dual-page workflow) |
| 5-Color Extended | 5         | —      | Red/Yellow/Blue/Black/White       |
| BW               | 2         | 32     | Black & white grayscale           |

## Output Formats

| Format | Purpose                                                         |
| ------ | --------------------------------------------------------------- |
| `.3mf` | 3D Manufacturing Format (BambuStudio compatible, with metadata) |
| `.glb` | GL Transmission Format (3D preview)                             |
| `.npy` | NumPy array (LUT calibration data)                              |
| `.npz` | Compressed NumPy (merged LUT + stacking data + metadata)        |
| `.svg` | Vector graphics (vector engine input)                           |

## Image Pipeline 模块架构 (core/pipeline/)

converter.py (4523行) 和 image_processing.py (930行) 已拆分为模块化流水线架构，原文件保留为薄包装层确保向后兼容。

### 编排层

| 文件                              | 职责                                     |
| --------------------------------- | ---------------------------------------- |
| `core/pipeline/__init__.py`       | 包初始化，导出公共接口                   |
| `core/pipeline/coordinator.py`    | 流水线总协调器，按顺序调度各 step 模块   |
| `core/pipeline/pipeline_utils.py` | 共享工具函数（日志、路径处理、通用辅助） |

### 主流水线 s01-s12（图片→3D模型，原 converter.py）

| 文件                        | 职责                                                         |
| --------------------------- | ------------------------------------------------------------ |
| `s01_input_validation.py`   | 输入校验：图片格式、尺寸、参数合法性                         |
| `s02_image_processing.py`   | 图像预处理：调用 processing_ops 完成缩放、去背景、滤波、量化 |
| `s03_color_replacement.py`  | 颜色替换：将量化颜色映射到 LUT 调色板                        |
| `s04_debug_preview.py`      | 调试预览：生成中间步骤可视化图片                             |
| `s05_preview_generation.py` | 预览图生成：最终效果预览供前端展示                           |
| `s06_voxel_building.py`     | 体素构建：2D 像素图转 3D 体素数据                            |
| `s07_mesh_generation.py`    | 网格生成：体素转三角网格（HighFidelity/PixelArt Mesher）     |
| `s08_auxiliary_meshes.py`   | 辅助网格：底板、边框等附加 3D 结构                           |
| `s09_export_3mf.py`         | 3MF 导出：网格打包为全彩打印文件                             |
| `s10_color_recipe.py`       | 色彩配方：打印所需颜色配比信息                               |
| `s11_glb_preview.py`        | GLB 预览：生成 GLB 供前端 Three.js 渲染                      |
| `s12_result_assembly.py`    | 结果组装：汇总所有输出，构建最终返回结果                     |

### 图像处理子流水线 p01-p06（原 image_processing.py）

| 文件                        | 职责                                     |
| --------------------------- | ---------------------------------------- |
| `p01_preview_validation.py` | 预览校验：验证预览请求参数和图片         |
| `p02_lut_metadata.py`       | LUT 元数据：加载和解析 LUT 颜色信息      |
| `p03_core_processing.py`    | 核心处理：编排缩放→去背景→滤波→量化→匹配 |
| `p04_cache_building.py`     | 缓存构建：处理结果缓存，避免重复计算     |
| `p05_palette_extraction.py` | 调色板提取：从处理后图像提取使用的颜色   |
| `p06_bed_rendering.py`      | 打印床渲染：生成打印床布局预览图         |

### 原子图像处理操作 (core/pipeline/processing_ops/)

| 文件                        | 职责                                     |
| --------------------------- | ---------------------------------------- |
| `__init__.py`               | 包初始化，导出所有操作函数               |
| `background_remover.py`     | 去除图片背景（透明/白色背景处理）        |
| `bilateral_filter.py`       | 双边滤波：保边去噪                       |
| `median_filter.py`          | 中值滤波：去除椒盐噪声                   |
| `image_scaler.py`           | 图像缩放：按目标尺寸缩放                 |
| `kmeans_quantizer.py`       | K-Means 量化：颜色减少到指定数量         |
| `lut_loader.py`             | LUT 加载器：读取 .npy 调色板文件         |
| `lut_color_matcher.py`      | LUT 颜色匹配：像素匹配到最近 LUT 颜色    |
| `hue_aware_matcher.py`      | 色相感知匹配：基于色相权重的高级颜色匹配 |
| `svg_rasterizer.py`         | SVG 栅格化：SVG 矢量图转位图             |
| `wireframe_extractor.py`    | 线框提取：从图像提取线框/轮廓            |
| `isolated_pixel_cleanup.py` | 孤立像素清理：去除量化后孤立噪点         |

### 兼容层

| 文件                       | 职责                                                       |
| -------------------------- | ---------------------------------------------------------- |
| `core/converter.py`        | 薄包装层：保留原有函数签名，委托给 coordinator + step 模块 |
| `core/image_processing.py` | 薄编排层：保留原有 API，委托给 p01-p06 模块                |

### Pipeline 测试文件

| 文件                                       | 职责                                  |
| ------------------------------------------ | ------------------------------------- |
| `tests/test_pipeline_step_properties.py`   | step 模块的 Property-Based 测试       |
| `tests/test_pipeline_step_modules_unit.py` | step 模块的单元测试                   |
| `tests/test_coordinator_properties.py`     | coordinator 的 Property-Based 测试    |
| `tests/test_processing_ops_properties.py`  | processing_ops 的 Property-Based 测试 |
| `tests/test_processing_ops_unit.py`        | processing_ops 的单元测试             |
| `tests/test_backward_compat_properties.py` | 向后兼容性的 Property-Based 测试      |

## Important Notes

- The project maintains dual frontends: Gradio (legacy) and React (primary development direction)
- React frontend has full feature coverage and is the recommended interface
- Slicer integration supports BambuStudio, OrcaSlicer, and ElegooSlicer
- PyInstaller is used for standalone executable packaging
- License: CC BY-NC-SA 4.0 with commercial exemption for individual creators and small businesses selling physical prints
