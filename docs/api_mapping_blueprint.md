# Lumina Studio — Gradio → FastAPI API Mapping Blueprint
# Lumina Studio — Gradio → FastAPI API 映射蓝图

> 本文档是从 Gradio UI 迁移到解耦 FastAPI 后端的权威参考。
> 每个 Gradio 组件均已映射到目标 Pydantic 字段，确保零功能丢失。
>
> 源文件: `ui/layout_new.py`, `core/converter.py`, `config.py`

---

## 目录 / Table of Contents

1. [列定义 / Column Definitions](#列定义)
2. [Converter Tab — 基础参数 / Basic Parameters](#converter-tab--基础参数)
3. [Converter Tab — 高级设置 / Advanced Settings](#converter-tab--高级设置)
4. [Converter Tab — 2.5D 浮雕模式 / Relief Mode](#converter-tab--25d-浮雕模式)
5. [Converter Tab — 描边 / Outline](#converter-tab--描边)
6. [Converter Tab — 掐丝珐琅 / Cloisonné](#converter-tab--掐丝珐琅)
7. [Converter Tab — 涂层 / Coating](#converter-tab--涂层)
8. [Converter Tab — 挂件环 / Keychain Loop](#converter-tab--挂件环)
9. [Converter Tab — 颜色替换 / Color Replacement](#converter-tab--颜色替换)
10. [Converter Tab — 颜色合并 / Color Merging](#converter-tab--颜色合并)
11. [Converter Tab — 操作按钮与切片软件 / Actions & Slicer](#converter-tab--操作按钮与切片软件)
12. [Calibration Tab / 校准板生成](#calibration-tab)
13. [Extractor Tab / 颜色提取](#extractor-tab)
14. [LUT Merge Tab / LUT 合并](#lut-merge-tab)
15. [Advanced Tab / 高级功能](#advanced-tab)
16. [About & Settings Tab / 关于与设置](#about--settings-tab)
17. [输出组件 / Output Components](#输出组件)
18. [Display-Only 组件 / Display-Only Components](#display-only-组件)
19. [Session 状态变量 / Session State Variables](#session-状态变量)
20. [持久化设置 / Persistent Settings (user_settings.json)](#持久化设置)
21. [Pydantic 模型骨架 / Pydantic Model Skeletons](#pydantic-模型骨架)

---

## 列定义

| 列名 Column | 说明 Description |
|---|---|
| Gradio Component | Gradio 组件类型 |
| Variable Name | `components` 字典键名或局部变量名 |
| Data Type | Python 运行时数据类型 |
| Default | 默认值 |
| Range / Choices | 取值范围 (min–max, step) 或可选值列表 |
| Pydantic Field | 目标 Pydantic 字段名 (snake_case) |
| Pydantic Type | Python 类型注解 |
| Converter Param | 后端函数对应参数名 |
| Notes | 条件可见性、联动关系、特殊说明 |

---

## Converter Tab — 基础参数

> API Endpoint: `POST /api/convert/preview`, `POST /api/convert/generate`

| Gradio Component | Variable Name | Data Type | Default | Range / Choices | Pydantic Field | Pydantic Type | Converter Param | Notes |
|---|---|---|---|---|---|---|---|---|
| `gr.Image` | `image_conv_image_label` | `str` (filepath) | `None` | 支持 JPG/PNG/SVG | `image_path` | `UploadFile` | `image_path` | `type="filepath"`, `image_mode=None` (自动检测) |
| `gr.Dropdown` | `dropdown_conv_lut_dropdown` | `str` | 从 `user_settings.json` 读取 `last_lut` | 动态列表 (LUTManager.get_lut_choices()) | `lut_name` | `str` | — | 通过 `on_lut_select()` 回调解析为 `conv_lut_path` State |
| `gr.File` | (conv_lut_upload) | `bytes` | `None` | `.npy` 文件 | `lut_file` | `Optional[UploadFile]` | — | 上传后自动保存并刷新 Dropdown；非 components 字典成员 |
| `gr.Slider` | `slider_conv_width` | `float` | `60` | 10–400, step=1 | `target_width_mm` | `float` | `target_width_mm` | 联动: 修改时自动按比例更新 height |
| `gr.Slider` | `slider_conv_height` | `float` | `60` | 10–400, step=1 | `target_height_mm` | `float` | — | 联动: 修改时自动按比例更新 width；不直接传入 converter，由 width + 图片比例推算 |
| `gr.Slider` | `slider_conv_thickness` | `float` | `1.2` | 0.2–3.5, step=0.08 | `spacer_thick` | `float` | `spacer_thick` | 底板厚度 (mm) |
| `gr.Radio` | `radio_conv_color_mode` | `str` | 从 `user_settings.json` 读取，fallback `"4-Color"` | `"BW (Black & White)"`, `"4-Color"`, `"6-Color (Smart 1296)"`, `"8-Color Max"`, `"Merged"` | `color_mode` | `Literal["BW (Black & White)","4-Color","6-Color (Smart 1296)","8-Color Max","Merged"]` | `color_mode` | `interactive=False`, `visible=False`; 由 LUT 自动检测设置 |
| `gr.Radio` | `radio_conv_structure` | `str` | `"Double-sided"` | `"Double-sided"`, `"Single-sided"` | `structure_mode` | `Literal["Double-sided","Single-sided"]` | `structure_mode` | i18n 显示名不同，内部值固定为英文 |
| `gr.Radio` | `radio_conv_modeling_mode` | `ModelingMode` | 从 `user_settings.json` 读取，fallback `ModelingMode.HIGH_FIDELITY` | `ModelingMode.HIGH_FIDELITY`, `ModelingMode.PIXEL`, `ModelingMode.VECTOR` | `modeling_mode` | `Literal["high-fidelity","pixel","vector"]` | `modeling_mode` | 切换时联动禁用/启用 cleanup、outline、cloisonné |
| `gr.Dropdown` | `radio_conv_bed_size` | `str` | `"256×256 mm"` | `"180×180 mm"`, `"220×220 mm"`, `"256×256 mm"`, `"300×300 mm"`, `"400×400 mm"` | `bed_size` | `Literal["180×180 mm","220×220 mm","256×256 mm","300×300 mm","400×400 mm"]` | — | 仅影响 2D 预览渲染，不传入 converter |
| `gr.Checkbox` | `checkbox_conv_batch_mode` | `bool` | `False` | — | `is_batch` | `bool` | — | 切换单图/批量模式；控制 image_input 和 batch_input 可见性 |
| `gr.File` | `file_conv_batch_input` | `List[str]` | `None` | 多文件, image 类型 | `batch_files` | `Optional[List[UploadFile]]` | `batch_files` | `file_count="multiple"`, 仅 batch_mode=True 时可见 |

---

## Converter Tab — 高级设置

> 位于 Accordion "高级设置" 内

| Gradio Component | Variable Name | Data Type | Default | Range / Choices | Pydantic Field | Pydantic Type | Converter Param | Notes |
|---|---|---|---|---|---|---|---|---|
| `gr.Slider` | `slider_conv_quantize_colors` | `int` | `48` | 8–256, step=8 | `quantize_colors` | `int` | `quantize_colors` | K-Means 色彩细节；可通过 auto_color 按钮自动设置 |
| `gr.Slider` | `slider_conv_tolerance` | `int` | `40` | 0–150, step=1 | `bg_tol` | `int` | `bg_tol` | 背景容差 |
| `gr.Checkbox` | `checkbox_conv_auto_bg` | `bool` | `False` | — | `auto_bg` | `bool` | `auto_bg` | 自动去背景 |
| `gr.Checkbox` | `checkbox_conv_cleanup` | `bool` | `True` | — | `enable_cleanup` | `bool` | `enable_cleanup` | 孤立像素清理；Pixel 模式下强制禁用 |
| `gr.Checkbox` | `checkbox_conv_separate_backing` | `bool` | `False` | — | `separate_backing` | `bool` | `separate_backing` | 底板作为独立对象导出 |
| `gr.Checkbox` | `checkbox_conv_enable_crop` | `bool` | 从 `user_settings.json` 读取 `enable_crop_modal`，fallback `True` | — | — | — | — | UI-only: 控制上传时是否显示裁剪界面；不传入 converter |
| `gr.Button` | `btn_conv_auto_color` | — | — | — | — | — | — | display-only trigger: 调用 `ImagePreprocessor.analyze_recommended_colors()` 自动设置 quantize_colors |

---

## Converter Tab — 2.5D 浮雕模式

> 条件可见: 仅当 `checkbox_conv_relief_mode = True` 时显示相关控件

| Gradio Component | Variable Name | Data Type | Default | Range / Choices | Pydantic Field | Pydantic Type | Converter Param | Notes |
|---|---|---|---|---|---|---|---|---|
| `gr.Checkbox` | `checkbox_conv_relief_mode` | `bool` | `False` | — | `enable_relief` | `bool` | `enable_relief` | 与掐丝珐琅互斥 |
| `gr.Slider` | `slider_conv_relief_height` | `float` | `1.2` | 0.08–20.0, step=0.1 | — | — | — | session-state: 修改时更新 `conv_color_height_map[selected_color]`；仅当 relief=True 且有选中颜色时可见 |
| `gr.Slider` | `slider_conv_auto_height_max` | `float` | `5.0` | 0.08–15.0, step=0.1 | `heightmap_max_height` | `float` | `heightmap_max_height` | 最大浮雕高度；仅 relief=True 时可见 |
| `gr.Radio` | `radio_conv_auto_height_mode` | `str` | `"深色凸起"` | `"深色凸起"`, `"浅色凸起"`, `"根据高度图"` | `auto_height_mode` | `Literal["深色凸起","浅色凸起","根据高度图"]` | — | 控制 `generate_auto_height_map()` 的 mode 参数；选择"根据高度图"时显示 heightmap 上传 |
| `gr.Image` | `image_conv_heightmap` | `str` (filepath) | `None` | PNG/JPG/BMP | `heightmap_path` | `Optional[UploadFile]` | `heightmap_path` | 仅 auto_height_mode="根据高度图" 时可见 |
| `gr.Button` | `btn_conv_auto_height_apply` | — | — | — | — | — | — | display-only trigger: 调用 `generate_auto_height_map()` 填充 `conv_color_height_map` |
| `gr.State` | `conv_color_height_map` | `Dict[str, float]` | `{}` | — | `color_height_map` | `Optional[Dict[str, float]]` | `color_height_map` | 键为 hex 颜色 (#rrggbb)，值为高度 (mm) |

---

## Converter Tab — 描边

| Gradio Component | Variable Name | Data Type | Default | Range / Choices | Pydantic Field | Pydantic Type | Converter Param | Notes |
|---|---|---|---|---|---|---|---|---|
| `gr.Checkbox` | `checkbox_conv_outline_enable` | `bool` | `False` | — | `enable_outline` | `bool` | `enable_outline` | Vector 模式下强制禁用 |
| `gr.Slider` | `slider_conv_outline_width` | `float` | `2.0` | 0.5–10.0, step=0.5 | `outline_width` | `float` | `outline_width` | 描边宽度 (mm)；Vector 模式下 interactive=False |

---

## Converter Tab — 掐丝珐琅

| Gradio Component | Variable Name | Data Type | Default | Range / Choices | Pydantic Field | Pydantic Type | Converter Param | Notes |
|---|---|---|---|---|---|---|---|---|
| `gr.Checkbox` | `checkbox_conv_cloisonne_enable` | `bool` | `False` | — | `enable_cloisonne` | `bool` | `enable_cloisonne` | 与 2.5D 浮雕互斥；Vector 模式下强制禁用 |
| `gr.Slider` | `slider_conv_wire_width` | `float` | `0.4` | 0.2–1.2, step=0.1 | `wire_width_mm` | `float` | `wire_width_mm` | 金属丝宽度 (mm)；Vector 模式下 interactive=False |
| `gr.Slider` | `slider_conv_wire_height` | `float` | `0.4` | 0.04–1.0, step=0.04 | `wire_height_mm` | `float` | `wire_height_mm` | 金属丝高度 (mm)；Vector 模式下 interactive=False |

---

## Converter Tab — 涂层

| Gradio Component | Variable Name | Data Type | Default | Range / Choices | Pydantic Field | Pydantic Type | Converter Param | Notes |
|---|---|---|---|---|---|---|---|---|
| `gr.Checkbox` | `checkbox_conv_coating_enable` | `bool` | `False` | — | `enable_coating` | `bool` | `enable_coating` | 透明涂层 |
| `gr.Slider` | `slider_conv_coating_height` | `float` | `0.08` | 0.04–0.12, step=0.04 | `coating_height_mm` | `float` | `coating_height_mm` | 涂层高度 (mm) |

---

## Converter Tab — 挂件环

> 位于 Group (visible=False) 内，通过预览点击激活

| Gradio Component | Variable Name | Data Type | Default | Range / Choices | Pydantic Field | Pydantic Type | Converter Param | Notes |
|---|---|---|---|---|---|---|---|---|
| `gr.Checkbox` | `checkbox_conv_loop_enable` | `bool` | `False` | — | `add_loop` | `bool` | `add_loop` | 启用挂件环 |
| `gr.Slider` | `slider_conv_loop_width` | `float` | `4.0` | 2–10, step=0.5 | `loop_width` | `float` | `loop_width` | 环宽度 (mm) |
| `gr.Slider` | `slider_conv_loop_length` | `float` | `8.0` | 4–15, step=0.5 | `loop_length` | `float` | `loop_length` | 环长度 (mm) |
| `gr.Slider` | `slider_conv_loop_hole` | `float` | `2.5` | 1–5, step=0.25 | `loop_hole` | `float` | `loop_hole` | 环孔直径 (mm) |
| `gr.Slider` | `slider_conv_loop_angle` | `float` | `0` | -180–180, step=5 | `loop_angle` | `float` | — | 环角度；通过 `update_preview_with_loop()` 计算 `loop_pos` |
| `gr.State` | `conv_loop_pos` | `Optional[Tuple]` | `None` | — | `loop_pos` | `Optional[Tuple[float, float]]` | `loop_pos` | 由预览点击或角度计算得出的 (x, y) 坐标 |

---

## Converter Tab — 颜色替换

> 位于 Accordion "调色板" 内
> API Endpoint: `POST /api/convert/replace-color`

| Gradio Component | Variable Name | Data Type | Default | Range / Choices | Pydantic Field | Pydantic Type | Converter Param | Notes |
|---|---|---|---|---|---|---|---|---|
| `gr.ColorPicker` | `color_conv_picker_search` | `str` | `"#ff0000"` | 任意 hex 颜色 | `search_color` | `Optional[str]` | — | 以色找色: 通过 KDTree 查找最近 LUT 颜色 |
| `gr.State` | `conv_selected_color` | `Optional[str]` | `None` | hex 颜色 | — | — | — | session-state: 用户在预览图上点击选中的原图颜色 |
| `gr.State` | `conv_replacement_color_state` | `Optional[str]` | `None` | hex 颜色 | — | — | — | session-state: 用户从 LUT 网格选中的替换色 |
| `gr.State` | `conv_replacement_regions` | `List[dict]` | `[]` | — | `replacement_regions` | `Optional[List[ColorReplacementItem]]` | `replacement_regions` | 每项: `{quantized, matched, replacement, mask}` |
| `gr.State` | `conv_replacement_history` | `List[dict]` | `[]` | — | — | — | — | session-state: 用于撤销操作的历史栈 |
| `gr.State` | `conv_free_color_set` | `Set[str]` | `set()` | hex 颜色集合 | `free_color_set` | `Optional[Set[str]]` | `free_color_set` | 自由色: 标记为独立对象导出的颜色 |
| `gr.Button` | `btn_conv_palette_apply_btn` | — | — | — | — | — | — | trigger: 调用 `on_apply_color_replacement()` |
| `gr.Button` | `btn_conv_palette_undo_btn` | — | — | — | — | — | — | trigger: 调用 `on_undo_color_replacement()` |
| `gr.Button` | `btn_conv_palette_clear_btn` | — | — | — | — | — | — | trigger: 调用 `on_clear_color_replacements()` |
| `gr.Button` | `btn_conv_free_color` | — | — | — | — | — | — | trigger: 标记/取消自由色 |
| `gr.Button` | `btn_conv_free_color_clear` | — | — | — | — | — | — | trigger: 清除所有自由色 |

---

## Converter Tab — 颜色合并

> 位于 Accordion "颜色合并" 内
> API Endpoint: `POST /api/convert/merge-colors`

| Gradio Component | Variable Name | Data Type | Default | Range / Choices | Pydantic Field | Pydantic Type | Converter Param | Notes |
|---|---|---|---|---|---|---|---|---|
| `gr.Checkbox` | `checkbox_conv_merge_enable` | `bool` | `True` | — | `merge_enable` | `bool` | — | 启用颜色合并 |
| `gr.Slider` | `slider_conv_merge_threshold` | `float` | `0.5` | 0.1–5.0, step=0.1 | `merge_threshold` | `float` | — | CIELAB 色差阈值 |
| `gr.Slider` | `slider_conv_merge_max_distance` | `int` | `20` | 5–50, step=1 | `merge_max_distance` | `int` | — | 最大合并距离 (像素) |
| `gr.State` | `conv_merge_map` | `dict` | `{}` | — | — | — | — | session-state: 合并映射表 |
| `gr.State` | `conv_merge_stats` | `dict` | `{}` | — | — | — | — | session-state: 合并统计信息 |
| `gr.Button` | `btn_conv_merge_preview` | — | — | — | — | — | — | trigger: 预览合并效果 |
| `gr.Button` | `btn_conv_merge_apply` | — | — | — | — | — | — | trigger: 应用合并 |
| `gr.Button` | `btn_conv_merge_revert` | — | — | — | — | — | — | trigger: 撤销合并 |

---

## Converter Tab — 操作按钮与切片软件

| Gradio Component | Variable Name | Data Type | Default | Range / Choices | Pydantic Field | Pydantic Type | Converter Param | Notes |
|---|---|---|---|---|---|---|---|---|
| `gr.Button` | `btn_conv_preview_btn` | — | — | — | — | — | — | trigger: 调用 `generate_preview_cached()` |
| `gr.Button` | `btn_conv_generate_btn` | — | — | — | — | — | — | trigger: 调用 `generate_final_model()` |
| `gr.Button` | `btn_conv_stop` | — | — | — | — | — | — | trigger: 取消 preview/generate 事件 |
| `gr.Dropdown` | `dropdown_conv_slicer` | `str` | 自动检测已安装切片软件 | 动态: 已安装切片软件 + "download" | `slicer_id` | `Optional[str]` | — | UI-only: 控制打开切片软件或下载文件 |
| `gr.Button` | `btn_conv_open_slicer` | — | — | — | — | — | — | trigger: 调用 `open_in_slicer()` 或触发下载 |
| `gr.Button` | `btn_conv_3d_fullscreen` | — | — | — | — | — | — | UI-only: 切换 3D 预览全屏 |

---

## Calibration Tab

> API Endpoint: `POST /api/calibration/generate`
> 函数: `generate_calibration_board()` (4-Color), `generate_smart_board()` (6-Color), `generate_8color_batch_zip()` (8-Color), `generate_bw_calibration_board()` (BW)

| Gradio Component | Variable Name | Data Type | Default | Range / Choices | Pydantic Field | Pydantic Type | Converter Param | Notes |
|---|---|---|---|---|---|---|---|---|
| `gr.Radio` | `radio_cal_color_mode` | `str` | `"4-Color"` | `"BW (Black & White)"`, `"4-Color"`, `"6-Color (Smart 1296)"`, `"8-Color Max"` | `color_mode` | `Literal["BW (Black & White)","4-Color","6-Color (Smart 1296)","8-Color Max"]` | `color_mode` (路由) | 决定调用哪个生成函数 |
| `gr.Slider` | `slider_cal_block_size` | `int` | `5` | 3–10, step=1 | `block_size` | `int` | `block_size` | 色块尺寸 (mm) |
| `gr.Slider` | `slider_cal_gap` | `float` | `0.82` | 0.4–2.0, step=0.02 | `gap` | `float` | `gap` | 色块间距 (mm) |
| `gr.Dropdown` | `dropdown_cal_backing` | `str` | `"White"` | `"White"`, `"Cyan"`, `"Magenta"`, `"Yellow"`, `"Red"`, `"Blue"` | `backing` | `Literal["White","Cyan","Magenta","Yellow","Red","Blue"]` | `backing` | 底板颜色；8-Color 模式下忽略 |

### 函数路由逻辑 / Function Routing

| color_mode | 调用函数 | 参数 |
|---|---|---|
| `"BW (Black & White)"` | `generate_bw_calibration_board(block_size, gap, backing)` | block_size, gap, backing |
| `"4-Color"` | `generate_calibration_board("RYBW", block_size, gap, backing)` | palette="RYBW", block_size, gap, backing |
| `"6-Color (Smart 1296)"` | `generate_smart_board(block_size, gap)` | block_size, gap |
| `"8-Color Max"` | `generate_8color_batch_zip()` | 无参数 |

---

## Extractor Tab

> API Endpoint: `POST /api/extractor/extract`, `POST /api/extractor/manual-fix`
> 函数: `run_extraction()`, `probe_lut_cell()`, `manual_fix_cell()`

| Gradio Component | Variable Name | Data Type | Default | Range / Choices | Pydantic Field | Pydantic Type | Converter Param | Notes |
|---|---|---|---|---|---|---|---|---|
| `gr.Radio` | `radio_ext_color_mode` | `str` | `"4-Color"` | `"BW (Black & White)"`, `"4-Color"`, `"6-Color (Smart 1296)"`, `"8-Color Max"` | `color_mode` | `Literal["BW (Black & White)","4-Color","6-Color (Smart 1296)","8-Color Max"]` | `color_mode` | 切换时重置角点和参考图 |
| `gr.Image` | (ext_img_in) | `ndarray` | `None` | numpy 数组 | `image` | `UploadFile` | `ext_state_img` | `type="numpy"`, `interactive=True`; 非 components 字典成员 |
| `gr.Slider` | `slider_ext_zoom` | `float` | `1.0` | 0.8–1.2, step=0.005 | `zoom` | `float` | `zoom` | 透视校正缩放 |
| `gr.Slider` | `slider_ext_distortion` | `float` | `0.0` | -0.2–0.2, step=0.01 | `distortion` | `float` | `distortion` | 桶形/枕形畸变校正 |
| `gr.Slider` | `slider_ext_offset_x` | `int` | `0` | -30–30, step=1 | `offset_x` | `int` | `offset_x` | X 轴偏移 (像素) |
| `gr.Slider` | `slider_ext_offset_y` | `int` | `0` | -30–30, step=1 | `offset_y` | `int` | `offset_y` | Y 轴偏移 (像素) |
| `gr.Checkbox` | `checkbox_ext_wb` | `bool` | `False` | — | `white_balance` | `bool` | `wb` | 白平衡校正 |
| `gr.Checkbox` | `checkbox_ext_vignette` | `bool` | `False` | — | `vignette_correction` | `bool` | `vignette` | 暗角校正 |
| `gr.Radio` | `radio_ext_page` | `str` | `"Page 1"` | `"Page 1"`, `"Page 2"` | `page` | `Literal["Page 1","Page 2"]` | `page` | 8-Color 专用: 选择第几页 |
| `gr.ColorPicker` | (ext_picker) | `str` | `"#FF0000"` | 任意 hex | `override_color` | `str` | `override_color` | 手动修正: 覆盖指定 LUT 单元格颜色 |
| `gr.State` | `ext_state_img` | `Optional[ndarray]` | `None` | — | — | — | — | session-state: 当前上传的原始图像 |
| `gr.State` | `ext_state_pts` | `List` | `[]` | — | `corner_points` | `List[Tuple[int,int]]` | — | session-state: 用户点击的 4 个角点坐标 |
| `gr.State` | `ext_curr_coord` | `Optional[Tuple]` | `None` | — | `cell_coord` | `Optional[Tuple[int,int]]` | — | session-state: 当前探测的 LUT 单元格坐标 |
| `gr.Button` | `btn_ext_extract_btn` | — | — | — | — | — | — | trigger: 调用 `run_extraction_wrapper()` |
| `gr.Button` | `btn_ext_rotate_btn` | — | — | — | — | — | — | trigger: 旋转图像 90° |
| `gr.Button` | `btn_ext_reset_btn` | — | — | — | — | — | — | trigger: 重置角点 |
| `gr.Button` | `btn_ext_merge_btn` | — | — | — | — | — | — | trigger: 合并 8-Color 两页数据 |
| `gr.Button` | `btn_ext_apply_btn` | — | — | — | — | — | — | trigger: 应用手动修正 `manual_fix_cell()` |

---

## LUT Merge Tab

> API Endpoint: `POST /api/lut/merge`
> 函数: `on_merge_execute()`

| Gradio Component | Variable Name | Data Type | Default | Range / Choices | Pydantic Field | Pydantic Type | Converter Param | Notes |
|---|---|---|---|---|---|---|---|---|
| `gr.Dropdown` | `dd_merge_primary` | `str` | `None` | 动态: LUTManager.get_lut_choices() | `primary_lut` | `str` | `primary` | 主 LUT (必须是 6-Color 或 8-Color) |
| `gr.Dropdown` | `dd_merge_secondary` | `List[str]` | `[]` | 动态: 根据主 LUT 模式过滤 | `secondary_luts` | `List[str]` | `secondary` | 副 LUT (multiselect=True) |
| `gr.Slider` | `slider_dedup_threshold` | `float` | `3.0` | 0–20, step=0.5 | `dedup_threshold` | `float` | `dedup_threshold` | 去重阈值 (CIELAB 色差) |
| `gr.Button` | `btn_merge` | — | — | — | — | — | — | trigger: 执行合并 |

---

## Advanced Tab

> 无后端 API 端点；仅客户端偏好设置

| Gradio Component | Variable Name | Data Type | Default | Range / Choices | Pydantic Field | Pydantic Type | Converter Param | Notes |
|---|---|---|---|---|---|---|---|---|
| `gr.Radio` | `radio_palette_mode` | `str` | 从 `user_settings.json` 读取 `palette_mode`，fallback `"swatch"` | `"swatch"`, `"card"` | — | — | — | UI-only: 调色板显示样式；保存到 user_settings.json |

---

## About & Settings Tab

> API Endpoint: `POST /api/settings/clear-cache`, `POST /api/settings/reset-counters`

| Gradio Component | Variable Name | Data Type | Default | Range / Choices | Pydantic Field | Pydantic Type | Converter Param | Notes |
|---|---|---|---|---|---|---|---|---|
| `gr.Button` | `btn_clear_cache` | — | — | — | — | — | — | trigger: 调用 `Stats.clear_cache()` |
| `gr.Button` | `btn_reset_counters` | — | — | — | — | — | — | trigger: 调用 `Stats.reset_all()` |

---

## 输出组件

> 这些组件为后端函数的返回值，在 FastAPI 中对应 Response 模型

| Gradio Component | Variable Name | Data Type | File Format | Source Function | API Response | Notes |
|---|---|---|---|---|---|---|
| `gr.File` | `file_conv_download_file` | `str` (filepath) | `.3mf` (单图) / `.zip` (批量) | `generate_final_model()` / `process_batch_generation()` | `FileResponse` | 3MF 含 BambuStudio 元数据 |
| `gr.File` | `file_conv_color_recipe` | `str` (filepath) | `.json` | `generate_final_model()` | `FileResponse` | 颜色配方日志 |
| `gr.Model3D` | `conv_3d_preview` | `str` (filepath) | `.glb` | `generate_realtime_glb()` | `FileResponse` | GLB 3D 预览；初始值为空床 |
| `gr.Image` | `conv_preview` (局部变量) | `ndarray` | RGBA numpy array | `render_preview()` | `StreamingResponse` (PNG) | 2D 预览图；含床面背景 |
| `gr.File` | `file_cal_download` | `str` (filepath) | `.3mf` / `.zip` | `generate_calibration_board()` 等 | `FileResponse` | 校准板模型 |
| `gr.File` | `file_ext_download_npy` | `str` (filepath) | `.npy` | `run_extraction()` | `FileResponse` | 提取的 LUT 数据 |
| `gr.Textbox` | `textbox_conv_status` | `str` | — | 各回调函数 | JSON `{"status": str}` | 转换状态文本 |
| `gr.Textbox` | `textbox_cal_status` | `str` | — | 校准回调 | JSON `{"status": str}` | 校准状态文本 |
| `gr.Textbox` | `textbox_ext_status` | `str` | — | 提取回调 | JSON `{"status": str}` | 提取状态文本 |
| `gr.Image` | (ext_warp_view) | `ndarray` | numpy array | `run_extraction()` | `StreamingResponse` (PNG) | 透视校正后的采样视图 |
| `gr.Image` | (ext_lut_view) | `ndarray` | numpy array | `run_extraction()` | `StreamingResponse` (PNG) | LUT 可视化视图 |
| `gr.Image` | (cal_preview) | `ndarray` | numpy array | `generate_calibration_board()` | `StreamingResponse` (PNG) | 校准板预览图 |

---

## Display-Only 组件

> 这些组件不传入后端，仅用于 UI 展示

| Gradio Component | Variable Name | 用途 | 数据来源 |
|---|---|---|---|
| `gr.Markdown` | `md_conv_input_section` | 输入区标题 | i18n |
| `gr.Markdown` | `md_conv_lut_status` | LUT 加载状态 | `on_lut_select()` 回调 |
| `gr.Markdown` | `md_conv_params_section` | 参数区标题 | i18n |
| `gr.Markdown` | `md_conv_preview_section` | 预览区标题 | i18n |
| `gr.Markdown` | `md_conv_outline_section` | 描边区标题 | i18n |
| `gr.Markdown` | `md_conv_cloisonne_section` | 掐丝珐琅区标题 | i18n |
| `gr.Markdown` | `md_conv_coating_section` | 涂层区标题 | i18n |
| `gr.Markdown` | `md_conv_loop_section` | 挂件环区标题 | i18n |
| `gr.Markdown` | `md_conv_palette_step1` | 调色板步骤1提示 | i18n |
| `gr.Markdown` | `md_conv_palette_step2` | 调色板步骤2提示 | i18n |
| `gr.Markdown` | `md_conv_palette_replacements_label` | 替换列表标题 | i18n |
| `gr.Markdown` | `md_conv_merge_status` | 颜色合并状态 | `on_merge_preview()` 回调 |
| `gr.HTML` | `conv_lut_grid_view` | LUT 色块网格 | `generate_lut_grid_html()` |
| `gr.HTML` | `conv_palette_html` (局部) | 调色板替换列表 | `generate_palette_html()` |
| `gr.HTML` | `conv_dual_recommend_html` (局部) | 双基准推荐色 | `_build_dual_recommendations()` |
| `gr.HTML` | `conv_free_color_html` (局部) | 自由色列表 | `_render_free_color_html()` |
| `gr.HTML` | `html_crop_modal` | 裁剪弹窗 HTML | `get_crop_modal_html()` |
| `gr.HTML` | (stats_html) | 统计信息栏 | `Stats.get_all()` |
| `gr.HTML` | (footer_html) | 页脚 | i18n |
| `gr.Markdown` | `md_cal_params` | 校准参数区标题 | i18n |
| `gr.Markdown` | `md_cal_preview` | 校准预览区标题 | i18n |
| `gr.Markdown` | `md_ext_upload_section` | 提取上传区标题 | i18n |
| `gr.Markdown` | `md_ext_correction_section` | 校正参数区标题 | i18n |
| `gr.Markdown` | `md_ext_sampling` | 采样视图标题 | i18n |
| `gr.Markdown` | `md_ext_reference` | 参考图标题 | i18n |
| `gr.Markdown` | `md_ext_result` | 结果区标题 | i18n |
| `gr.Markdown` | `md_ext_manual_fix` | 手动修正区标题 | i18n |
| `gr.HTML` | (ext_probe_html) | LUT 单元格探测信息 | `probe_lut_cell()` |
| `gr.Image` | (ext_ref_view) | 参考校准图 | `get_extractor_reference_image()` |
| `gr.Markdown` | `md_merge_title` | 合并标题 | i18n |
| `gr.Markdown` | `md_merge_desc` | 合并描述 | i18n |
| `gr.Markdown` | `md_merge_mode_primary` | 主 LUT 模式信息 | `on_merge_primary_select()` |
| `gr.Markdown` | `md_merge_secondary_info` | 副 LUT 信息 | `on_merge_secondary_change()` |
| `gr.Markdown` | `md_merge_status` | 合并状态 | `on_merge_execute()` |
| `gr.Markdown` | `md_advanced_title` | 高级功能标题 | 硬编码 |
| `gr.Markdown` | `md_settings_title` | 设置标题 | i18n |
| `gr.Markdown` | `md_cache_size` | 缓存大小 | `Stats.get_cache_size()` |
| `gr.Markdown` | `md_settings_status` | 设置操作状态 | 回调返回 |
| `gr.Markdown` | `md_about_content` | 关于页面内容 | i18n |
| `gr.Textbox` | `textbox_conv_loop_info` | 挂件环信息 | `interactive=False` |

---

## Session 状态变量

> 这些 `gr.State` 变量在 FastAPI 中需要通过 session/cache 机制管理

| Variable Name | Type | Initial Value | 用途 | 生命周期 |
|---|---|---|---|---|
| `conv_preview_cache` | `Optional[dict]` | `None` | 预览缓存 (matched_rgb, material_matrix, mask_solid, color_palette, quantized_image 等) | 每次预览生成时重建 |
| `conv_loop_pos` | `Optional[Tuple]` | `None` | 挂件环位置坐标 | 预览点击时更新 |
| `conv_replacement_regions` | `List[dict]` | `[]` | 颜色替换区域列表，每项含 quantized/matched/replacement/mask | 替换操作时追加 |
| `conv_replacement_history` | `List[dict]` | `[]` | 替换历史栈 (用于撤销) | 替换操作时追加 |
| `conv_selected_color` | `Optional[str]` | `None` | 当前选中的原图颜色 (hex) | 预览点击时更新 |
| `conv_replacement_color_state` | `Optional[str]` | `None` | 当前选中的 LUT 替换色 (hex) | LUT 网格点击时更新 |
| `conv_color_height_map` | `Dict[str, float]` | `{}` | 浮雕模式: hex → 高度 (mm) 映射 | 滑块调整或自动生成时更新 |
| `conv_relief_selected_color` | `Optional[str]` | `None` | 浮雕模式: 当前选中颜色 | 预览点击时更新 |
| `conv_free_color_set` | `Set[str]` | `set()` | 自由色集合 (hex) | 用户标记时更新 |
| `conv_merge_map` | `dict` | `{}` | 颜色合并映射表 | 合并预览时生成 |
| `conv_merge_stats` | `dict` | `{}` | 合并统计信息 | 合并预览时生成 |
| `conv_palette_mode` | `str` | `"swatch"` (从 user_settings.json 读取) | 调色板显示模式 | 用户切换时更新 |
| `conv_lut_path` | `Optional[str]` | `None` | 当前 LUT 文件路径 | LUT 选择时更新 |
| `lang_state` | `str` | `"zh"` | 当前 UI 语言 | 语言按钮切换 |
| `theme_state` | `bool` | `False` | 当前主题 (False=light, True=dark) | 主题按钮切换 |
| `ext_state_img` | `Optional[ndarray]` | `None` | Extractor: 当前上传图像 | 图像上传时更新 |
| `ext_state_pts` | `List` | `[]` | Extractor: 角点坐标列表 | 用户点击时追加 |
| `ext_curr_coord` | `Optional[Tuple]` | `None` | Extractor: 当前探测 LUT 坐标 | LUT 视图点击时更新 |
| `crop_data_state` | `dict` | `{"x":0,"y":0,"w":100,"h":100}` | 裁剪区域数据 | JavaScript 裁剪时更新 |
| `preprocess_processed_path` | `Optional[str]` | `None` | 预处理后的图片路径 | 图片上传时更新 |
| `conv_selected_user_row_id` | `Optional[str]` | `None` | 调色板: 选中的用户替换行 ID | 行点击时更新 |
| `conv_selected_auto_row_id` | `Optional[str]` | `None` | 调色板: 选中的自动匹配行 ID | 行点击时更新 |

---

## 持久化设置

> 存储在 `user_settings.json`，跨 session 保留

| Key | Type | Default | 对应 UI 组件 | 读取函数 | 写入函数 |
|---|---|---|---|---|---|
| `last_lut` | `str` | `None` | `dropdown_conv_lut_dropdown` | `load_last_lut_setting()` | `save_last_lut_setting()` |
| `last_color_mode` | `str` | `"4-Color"` | `radio_conv_color_mode` | `_load_user_settings()` | `save_color_mode()` |
| `last_modeling_mode` | `str` | `"high-fidelity"` | `radio_conv_modeling_mode` | `_load_user_settings()` | `save_modeling_mode()` |
| `palette_mode` | `str` | `"swatch"` | `radio_palette_mode` | `_load_user_settings()` | `_save_user_setting("palette_mode", ...)` |
| `enable_crop_modal` | `bool` | `True` | `checkbox_conv_enable_crop` | `_load_user_settings()` | `_save_user_setting("enable_crop_modal", ...)` |
| `last_slicer` | `str` | 自动检测第一个 | `dropdown_conv_slicer` | `_load_user_settings()` | `_save_user_setting("last_slicer", ...)` |
| `custom_slicers` | `Dict[str, str]` | `{}` | — | `_load_user_settings()` | — | 用户自定义切片软件路径 {slicer_id: exe_path} |

---

## Pydantic 模型骨架

> 以下为建议的 Pydantic v2 模型定义，覆盖所有主要 API 端点

```python
"""
Lumina Studio — FastAPI Pydantic Models
Auto-generated skeleton from API Mapping Blueprint
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Literal, Optional, Set, Tuple

from fastapi import UploadFile
from pydantic import BaseModel, Field


# ========== Enums ==========

class ColorMode(str, Enum):
    BW = "BW (Black & White)"
    FOUR_COLOR = "4-Color"
    SIX_COLOR = "6-Color (Smart 1296)"
    EIGHT_COLOR = "8-Color Max"
    MERGED = "Merged"


class ModelingMode(str, Enum):
    HIGH_FIDELITY = "high-fidelity"
    PIXEL = "pixel"
    VECTOR = "vector"


class StructureMode(str, Enum):
    DOUBLE_SIDED = "Double-sided"
    SINGLE_SIDED = "Single-sided"


class AutoHeightMode(str, Enum):
    DARKER_HIGHER = "深色凸起"
    LIGHTER_HIGHER = "浅色凸起"
    USE_HEIGHTMAP = "根据高度图"


class CalibrationColorMode(str, Enum):
    BW = "BW (Black & White)"
    FOUR_COLOR = "4-Color"
    SIX_COLOR = "6-Color (Smart 1296)"
    EIGHT_COLOR = "8-Color Max"


class BackingColor(str, Enum):
    WHITE = "White"
    CYAN = "Cyan"
    MAGENTA = "Magenta"
    YELLOW = "Yellow"
    RED = "Red"
    BLUE = "Blue"


class ExtractorPage(str, Enum):
    PAGE_1 = "Page 1"
    PAGE_2 = "Page 2"


# ========== Converter Models ==========

class ConvertPreviewRequest(BaseModel):
    """POST /api/convert/preview — 生成 2D 预览"""
    # image: UploadFile  # 通过 Form/File 上传，不在 JSON body 中
    lut_name: str = Field(..., description="LUT 名称 (从 /api/lut/list 获取)")
    target_width_mm: float = Field(60.0, ge=10, le=400, description="目标宽度 (mm)")
    auto_bg: bool = Field(False, description="自动去背景")
    bg_tol: int = Field(40, ge=0, le=150, description="背景容差")
    color_mode: ColorMode = Field(ColorMode.FOUR_COLOR, description="颜色模式")
    modeling_mode: ModelingMode = Field(
        ModelingMode.HIGH_FIDELITY, description="建模模式"
    )
    quantize_colors: int = Field(48, ge=8, le=256, description="K-Means 色彩细节")
    enable_cleanup: bool = Field(True, description="孤立像素清理")


class ColorReplacementItem(BaseModel):
    """单条颜色替换记录"""
    quantized_hex: str = Field(..., description="量化后的原色 (#rrggbb)")
    matched_hex: str = Field(..., description="LUT 匹配色 (#rrggbb)")
    replacement_hex: str = Field(..., description="替换目标色 (#rrggbb)")


class ConvertGenerateRequest(BaseModel):
    """POST /api/convert/generate — 生成 3MF 模型"""
    # image: UploadFile  # 通过 Form/File 上传
    lut_name: str = Field(..., description="LUT 名称")
    target_width_mm: float = Field(60.0, ge=10, le=400)
    spacer_thick: float = Field(1.2, ge=0.2, le=3.5, description="底板厚度 (mm)")
    structure_mode: StructureMode = Field(StructureMode.DOUBLE_SIDED)
    auto_bg: bool = Field(False)
    bg_tol: int = Field(40, ge=0, le=150)
    color_mode: ColorMode = Field(ColorMode.FOUR_COLOR)
    modeling_mode: ModelingMode = Field(ModelingMode.HIGH_FIDELITY)
    quantize_colors: int = Field(48, ge=8, le=256)
    enable_cleanup: bool = Field(True)
    separate_backing: bool = Field(False, description="底板作为独立对象")

    # 挂件环
    add_loop: bool = Field(False, description="启用挂件环")
    loop_width: float = Field(4.0, ge=2, le=10, description="环宽度 (mm)")
    loop_length: float = Field(8.0, ge=4, le=15, description="环长度 (mm)")
    loop_hole: float = Field(2.5, ge=1, le=5, description="环孔直径 (mm)")
    loop_pos: Optional[Tuple[float, float]] = Field(
        None, description="环位置 (x, y)，None 时由角度计算"
    )

    # 2.5D 浮雕
    enable_relief: bool = Field(False, description="启用 2.5D 浮雕模式")
    color_height_map: Optional[Dict[str, float]] = Field(
        None, description="颜色高度映射 {hex: mm}"
    )
    heightmap_max_height: float = Field(
        5.0, ge=0.08, le=15.0, description="最大浮雕高度 (mm)"
    )
    # heightmap: Optional[UploadFile]  # 通过 Form/File 上传

    # 描边
    enable_outline: bool = Field(False)
    outline_width: float = Field(2.0, ge=0.5, le=10.0, description="描边宽度 (mm)")

    # 掐丝珐琅
    enable_cloisonne: bool = Field(False)
    wire_width_mm: float = Field(0.4, ge=0.2, le=1.2, description="金属丝宽度 (mm)")
    wire_height_mm: float = Field(0.4, ge=0.04, le=1.0, description="金属丝高度 (mm)")

    # 涂层
    enable_coating: bool = Field(False)
    coating_height_mm: float = Field(
        0.08, ge=0.04, le=0.12, description="涂层高度 (mm)"
    )

    # 颜色替换
    replacement_regions: Optional[List[ColorReplacementItem]] = Field(
        None, description="颜色替换列表"
    )
    free_color_set: Optional[Set[str]] = Field(
        None, description="自由色集合 (hex)"
    )


class ConvertBatchRequest(BaseModel):
    """POST /api/convert/batch — 批量生成"""
    # files: List[UploadFile]  # 通过 Form/File 上传
    params: ConvertGenerateRequest = Field(
        ..., description="共享参数 (与单图生成相同)"
    )


# ========== Color Operations ==========

class ColorReplaceRequest(BaseModel):
    """POST /api/convert/replace-color — 应用颜色替换"""
    session_id: str = Field(..., description="Session ID (关联 preview_cache)")
    selected_color: str = Field(..., description="选中的原图颜色 (hex)")
    replacement_color: str = Field(..., description="替换目标色 (hex)")


class ColorMergePreviewRequest(BaseModel):
    """POST /api/convert/merge-colors/preview — 预览颜色合并"""
    session_id: str = Field(..., description="Session ID")
    merge_enable: bool = Field(True)
    merge_threshold: float = Field(0.5, ge=0.1, le=5.0, description="CIELAB 色差阈值")
    merge_max_distance: int = Field(20, ge=5, le=50, description="最大合并距离 (px)")


# ========== Calibration ==========

class CalibrationGenerateRequest(BaseModel):
    """POST /api/calibration/generate — 生成校准板"""
    color_mode: CalibrationColorMode = Field(CalibrationColorMode.FOUR_COLOR)
    block_size: int = Field(5, ge=3, le=10, description="色块尺寸 (mm)")
    gap: float = Field(0.82, ge=0.4, le=2.0, description="色块间距 (mm)")
    backing: BackingColor = Field(BackingColor.WHITE, description="底板颜色")


# ========== Extractor ==========

class ExtractorExtractRequest(BaseModel):
    """POST /api/extractor/extract — 提取 LUT"""
    # image: UploadFile  # 通过 Form/File 上传
    color_mode: CalibrationColorMode = Field(CalibrationColorMode.FOUR_COLOR)
    corner_points: List[Tuple[int, int]] = Field(
        ..., min_length=4, max_length=4, description="4 个角点坐标 [(x,y), ...]"
    )
    offset_x: int = Field(0, ge=-30, le=30)
    offset_y: int = Field(0, ge=-30, le=30)
    zoom: float = Field(1.0, ge=0.8, le=1.2, description="透视校正缩放")
    distortion: float = Field(0.0, ge=-0.2, le=0.2, description="畸变校正")
    white_balance: bool = Field(False, description="白平衡校正")
    vignette_correction: bool = Field(False, description="暗角校正")
    page: ExtractorPage = Field(ExtractorPage.PAGE_1, description="8-Color 页码")


class ExtractorManualFixRequest(BaseModel):
    """POST /api/extractor/manual-fix — 手动修正 LUT 单元格"""
    lut_path: str = Field(..., description="LUT 文件路径")
    cell_coord: Tuple[int, int] = Field(..., description="单元格坐标 (row, col)")
    override_color: str = Field(..., description="覆盖颜色 (hex)")


# ========== LUT Merge ==========

class LutMergeRequest(BaseModel):
    """POST /api/lut/merge — 合并 LUT"""
    primary_lut: str = Field(..., description="主 LUT 名称")
    secondary_luts: List[str] = Field(
        ..., min_length=1, description="副 LUT 名称列表"
    )
    dedup_threshold: float = Field(
        3.0, ge=0, le=20, description="去重阈值 (CIELAB 色差)"
    )


# ========== Settings ==========

class UserPreferences(BaseModel):
    """用户偏好设置 (对应 user_settings.json)"""
    last_lut: Optional[str] = None
    last_color_mode: str = "4-Color"
    last_modeling_mode: str = "high-fidelity"
    palette_mode: str = "swatch"
    enable_crop_modal: bool = True
    last_slicer: Optional[str] = None
    custom_slicers: Dict[str, str] = Field(
        default_factory=dict, description="{slicer_id: exe_path}"
    )


# ========== API Endpoint Summary ==========
#
# POST /api/convert/preview          → ConvertPreviewRequest + UploadFile(image)
# POST /api/convert/generate         → ConvertGenerateRequest + UploadFile(image) + Optional[UploadFile(heightmap)]
# POST /api/convert/batch            → ConvertBatchRequest + List[UploadFile(files)]
# POST /api/convert/replace-color    → ColorReplaceRequest
# POST /api/convert/merge-colors     → ColorMergePreviewRequest
# POST /api/calibration/generate     → CalibrationGenerateRequest
# POST /api/extractor/extract        → ExtractorExtractRequest + UploadFile(image)
# POST /api/extractor/manual-fix     → ExtractorManualFixRequest
# POST /api/lut/merge                → LutMergeRequest
# GET  /api/lut/list                 → List[str]
# GET  /api/settings                 → UserPreferences
# PUT  /api/settings                 → UserPreferences
# POST /api/settings/clear-cache     → {"freed_bytes": int}
# POST /api/settings/reset-counters  → {"status": str}
```

---

> **文档生成日期**: 基于 `ui/layout_new.py` (4760 行), `core/converter.py` (3682 行), `config.py` 全量分析
>
> **覆盖统计**:
> - Converter Tab 输入组件: 35+ 项
> - Calibration Tab 输入组件: 4 项
> - Extractor Tab 输入组件: 10+ 项
> - LUT Merge Tab 输入组件: 3 项
> - Session State 变量: 20+ 项
> - 持久化设置键: 7 项
> - 输出组件: 12 项
> - Display-only 组件: 30+ 项
> - Pydantic 模型: 11 个
> - API 端点: 14 个
