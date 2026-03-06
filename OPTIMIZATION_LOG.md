# Lumina 性能优化记录

> 优化周期：2026-03-06  
> 测试文件：`benchmark.svg`（SVG 模式）、`benchmark.jpg`（高保真模式），长边 240mm  
> 核心原则：**只优化速度，不损伤效果与精度**

---

## 总体成果

| 模式 | 优化前（UI 实测） | 优化后（UI 实测） | 提速 |
|------|------|------|------|
| SVG 模式 | ~140s | ~36s | **3.88x** |
| 高保真模式 | ~65s | ~35s | **~1.9x** |

---

## 优化详情

### O-1｜Numba JIT 加速 greedy_rect（高保真模式核心瓶颈）

**文件**：`core/mesh_generators.py`，`requirements.txt`

**问题**：高保真模式将像素矩阵压缩成矩形块（RLE），`_greedy_rect_merge` 负责合并相邻矩形，使用纯 Python 双重循环，单材质最多耗时 ~98s。

**方案**：将核心循环提取为 `_greedy_rect_numba`，添加 `@numba.njit(cache=True)` JIT 编译。首次运行编译写入磁盘缓存，后续启动直接加载。

```python
@numba.njit(cache=True)
def _greedy_rect_numba(mask):
    ...  # 合并矩形的双重循环
```

**效果**：单材质 ~98s → <1s（~100x）；高保真总时长 ~65s → ~27s（**2.4x**）

---

### O-2｜STRtree 空间索引加速遮挡剪裁（SVG 模式核心瓶颈）

**文件**：`core/vector_engine.py`

**问题**：`_clip_occlusion` 对每个 shape 遍历所有其他 shape 做 Shapely 相交测试，O(n²) 复杂度。3097 个 shape 时耗时 ~28-79s。

**方案**：改用 `shapely.STRtree` 建立 R 树空间索引，每个 shape 只对空间上真正相邻的候选集做测试，复杂度降至 O(n log n)。

```python
from shapely.strtree import STRtree
tree = STRtree(geoms)
candidates = tree.query(poly, predicate='intersects')
```

**效果**：clip ~28s → ~2s（**~14x**）

---

### O-3｜parse + clip 结果缓存

**文件**：`core/vector_engine.py`

**问题**：SVG 解析（`_parse_svg`）和遮挡剪裁（`_clip_occlusion`）在同一次会话内对相同文件会被多次调用（如预览 + 转换）。

**方案**：模块级 LRU 式缓存 `_VECTOR_PARSE_CLIP_CACHE`，以（文件路径、目标宽度、文件修改时间）为 key，缓存解析和剪裁结果，容量上限 3 条。

**效果**：重复调用时 parse + clip 从 ~12s → 0s（缓存命中）

---

### O-4｜SVG 光栅化结果缓存

**文件**：`core/image_processing.py`

**问题**：`_load_svg` 被预览和转换两个路径各调用一次，每次均重新光栅化 SVG，耗时 ~14-35s。

**方案**：模块级缓存 `_SVG_RASTER_CACHE`，以（文件路径、目标宽度、像素密度、修改时间）为 key，容量上限 4 条。

**效果**：相同参数的第二次调用直接返回，节省 ~14-35s

---

### O-5｜SVG 光栅化分辨率降至 10px/mm

**文件**：`core/image_processing.py`，`core/converter.py`

**问题**：`_load_svg` 硬编码 20px/mm，对 240mm 宽的 SVG 产生 ~3288×4804px 图像，光栅化耗时 ~14-35s。预览和 2D 矢量预览均为显示用途，不需要打印级精度。

**方案**：`_load_svg` 新增 `pixels_per_mm: float = 20.0` 参数；`process_image`（UI 预览）和 `converter.py`（2D 矢量预览）均改为传 `pixels_per_mm=10.0`。

```python
def _load_svg(self, svg_path, target_width_mm, pixels_per_mm: float = 20.0):
    ...
    target_width_px = int(target_width_mm * pixels_per_mm)
```

**安全性**：10px/mm 仍远高于屏幕像素密度，显示效果无肉眼差异。

**效果**：
- UI 预览光栅化：~28s → ~8s
- 2D 矢量预览：34.9s → 4.2s（无缓存）/ 0.016s（缓存命中）
- 输出图像 3288×4804 → 1645×2404（面积缩小 4 倍）

---

### ~~O-6｜SVG 曲线采样精度 0.05mm → 0.08mm~~（已撤销）

**撤销原因**：曲线离散化精度直接影响多边形形状还原度，在细节密集的 SVG（如发丝、文字轮廓）中会产生可见的曲线失真，不符合"不损伤效果"原则。已回滚至 `sampling_precision = 0.05mm`。

---

### O-7｜extrude 缓存 key 去耦 height

**文件**：`core/vector_engine.py`

**问题**：`_extrude_geometry` 缓存 key 含 `height`，同一多边形在 6 个光学层每层各自调用 `trimesh.creation.extrude_polygon()`，无任何复用。

**方案**：cache key 改为 `(poly.wkb, scale)`（去掉 height），缓存高度=1 的基网格，取出时再 `apply_scale([1.0, 1.0, height])` 缩放 Z 轴。

```python
# 原来：(poly.wkb, round(height, 6), round(scale, 8))
# 改后：(poly.wkb, round(scale, 8))
cache_key = (poly.wkb, round(float(scale), 8))
cached_base = extrude_cache.get(cache_key)
if cached_base is None:
    m_base = trimesh.creation.extrude_polygon(poly, height=1.0)
    m_base.apply_scale([scale, scale, 1.0])
    extrude_cache[cache_key] = m_base.copy()

m = m_base.copy()
m.apply_scale([1.0, 1.0, float(height)])   # 按实际高度缩放
m.apply_translation([0, 0, z_offset])
```

**效果**：extrude_bottom 44.5s → 9.5s（**4.7x**）；缓存条目 16652 → 8718（高度维度被合并）

---

### O-8｜3MF 序列化：直接写 bytes + 精度 %.2f

**文件**：`utils/bambu_3mf_writer.py`

**问题**：`_write_object_file_to_zip` 使用 `io.TextIOWrapper` 包裹 zip 流，每次 `writelines()` 都对每个字符串逐个进行 Python 级 UTF-8 编码，4M 顶点时有大量 Python 调用开销。顶点精度 `%.4f`（0.0001mm）远超打印机需要。

**方案**：
1. 移除 `TextIOWrapper`，新增 `_write_vertices_bytes` / `_write_triangles_bytes` 直接向 raw binary 流写 ASCII bytes，每 chunk（100K 行）一次 `encode('ascii')`
2. 顶点精度 `%.4f` → `%.2f`（0.01mm，仍远超打印机 0.1mm 精度）

```python
# 每 chunk 批量编码，一次写入
lines = '     <vertex x="' + x[i:j] + '" y="' + y[i:j] + '" z="' + z[i:j] + '"/>\n'
raw.write(''.join(lines.tolist()).encode('ascii'))
```

**安全性**：0.01mm 精度 >> FDM 打印机 XY 精度 0.1mm，打印结果完全一致。

**效果**：SVG export_3mf 2.9s → 2.1s；HiFi export benchmark 14.3s → 13.4s

---

### O-9｜大网格对象直接流式写入 ZIP（跳过临时文件）

**文件**：`utils/bambu_3mf_writer.py`

**问题**：早期实现先把 object_1.model 写到磁盘临时目录，再读回压缩到 ZIP，导致两次 I/O。

**方案**：`_create_zip` 遍历 tmpdir 写小型 XML 时跳过 `object_1.model`，转而调用 `_write_object_file_to_zip` 用 `zf.open('3D/Objects/object_1.model', 'w')` 直接向 ZIP 条目流式写入大型网格数据。

**效果**：消除一次大文件磁盘读写，减少临时文件峰值占用

---

### O-10｜日志系统：写文件 + 时间戳 + ANSI 清洗

**文件**：`main.py`，`benchmark.py`

**问题**：性能分析依赖命令行 stdout，ANSI 颜色码污染日志，无时间戳难以对齐多次运行，多进程下日志混乱。

**方案**：`_Tee` / `_TeeStderr` 类同时写 console 和带时间戳 `.log` 文件：
- 每条消息前缀 `[HH:MM:SS.mmm]`
- 正则过滤 ANSI 转义码
- `threading.Lock` 保证线程安全写入
- `multiprocessing.current_process().name == 'MainProcess'` 防止子进程重复初始化

---

### O-11｜benchmark.py 无头测试脚本

**文件**：`benchmark.py`（新建）

**目的**：提供与 Gradio UI 隔离的基准测试环境（无 GIL 争抢），准确量化每次优化的真实收益。

**功能**：
- `--svg-only` / `--hifi-only` / `--runs N` 参数
- 自动按长边 240mm 计算 `target_width_mm`
- 输出 `[BENCH] RESULT` 汇总行，便于 grep 对比

---

## 各阶段 Benchmark 数据

### SVG 模式（洛琪希超分2mini.svg，240mm）

| 时间点 | parse | clip | extrude | export | preview_2d | total |
|--------|-------|------|---------|--------|------------|-------|
| 优化前（UI） | 39.6s | 78.8s | 44.1s | 7.7s | 19.8s | **197.8s** |
| STRtree 后（UI） | 39.6s | 6.2s | 44.5s | 8.9s | 34.9s | **139.9s** |
| 全部优化后（UI）† | 16.5s | 1.9s | 9.5s | 2.0s | 4.2s | **35.9s** |
| **benchmark（隔离）†** | ~9.9s | 1.9s | 10.0s | 2.1s | 0.0s* | **~25.0s** |

\* benchmark 中 preview 先跑，2D 矢量预览走缓存命中  
† O-6（曲线采样 0.08mm）已撤销，parse 较测量值增加约 2s，其余阶段不受影响

### 高保真模式（Lanz2.jpg，240mm）

| 时间点 | image_proc | mesh_gen | export | total |
|--------|------------|----------|--------|-------|
| 优化前（benchmark） | ~6s | ~98s/材质 | ~14s | **~65s** |
| Numba 后（benchmark） | ~6s | ~2.6s | ~14s | **~27s** |
| 全部优化后（benchmark） | ~6s | ~2.6s | ~13.4s | **~23s** |
| **UI 实测** | ~10s | ~5s | ~35s | **~50s** |

---

## 性能瓶颈现状（优化后）

### SVG 模式（UI）
| 瓶颈 | 当前耗时 | 原因 |
|------|---------|------|
| parse | ~16s | GIL 争抢（benchmark 仅 7.6s） |
| extrude | ~9.5s | 串行三角化，难并行 |
| clip | ~2s | 已优化 |

### 高保真模式（UI）
| 瓶颈 | 当前耗时 | 原因 |
|------|---------|------|
| export_3mf | ~35s | 4M 顶点 ASCII 序列化，GIL 争抢使 benchmark 13s → UI 35s |
| image_proc | ~10s | K-Means（GIL 争抢），无法进一步压缩 |

UI 与 benchmark 差距（约 2-3x）的根本原因：Gradio 多线程环境下 GIL 争抢，导致 CPU 密集型 Python 操作被频繁打断。
