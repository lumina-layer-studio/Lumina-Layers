/**
 * Lumina Studio - Translation Dictionary
 * Migrated from core/i18n.py TEXTS dictionary
 * Contains all zh/en translation key-value pairs
 */
export const translations: Record<string, Record<"zh" | "en", string>> = {
  // ==================== Application Title and Header ====================
  app_title: {
    zh: "✨ Lumina Studio",
    en: "✨ Lumina Studio",
  },
  app_subtitle: {
    zh: "多材料3D打印色彩系统 | v1.6.5",
    en: "Multi-Material 3D Print Color System | v1.6.5",
  },
  lang_btn_zh: {
    zh: "🌐 中文",
    en: "🌐 中文",
  },
  lang_btn_en: {
    zh: "🌐 English",
    en: "🌐 English",
  },

  // ==================== Stats Bar ====================
  stats_total: {
    zh: "📊 累计生成",
    en: "📊 Total Generated",
  },
  stats_calibrations: {
    zh: "校准板",
    en: "Calibrations",
  },
  stats_extractions: {
    zh: "颜色提取",
    en: "Extractions",
  },
  stats_conversions: {
    zh: "模型转换",
    en: "Conversions",
  },

  // ==================== Tab Titles ====================
  tab_converter: {
    zh: "💎 图像转换",
    en: "💎 Image Converter",
  },
  tab_calibration: {
    zh: "📐 校准板生成",
    en: "📐 Calibration",
  },
  tab_extractor: {
    zh: "🎨 颜色提取",
    en: "🎨 Color Extractor",
  },
  tab_about: {
    zh: "ℹ️ 关于",
    en: "ℹ️ About",
  },

  // ==================== Converter Tab ====================
  conv_title: {
    zh: "### 第一步：转换图像",
    en: "### Step 1: Convert Image",
  },
  conv_desc: {
    zh: "**两种建模模式**：高保真（RLE无缝拼接）、像素艺术（方块风格）\n\n**流程**: 上传LUT和图像 → 选择建模模式 → 调整色彩细节 → 预览 → 生成",
    en: "**Two Modeling Modes**: High-Fidelity (RLE seamless) and Pixel Art (blocky style)\n\n**Workflow**: Upload LUT & Image → Select Mode → Adjust Color Detail → Preview → Generate",
  },
  conv_input_section: {
    zh: "#### 📁 输入",
    en: "#### 📁 Input",
  },
  conv_lut_title: {
    zh: "**校准数据 (.npy)**",
    en: "**Calibration Data (.npy)**",
  },
  conv_lut_dropdown: {
    zh: "选择预设",
    en: "Select Preset",
  },
  conv_lut_info: {
    zh: "从预设库中选择LUT",
    en: "Select from library",
  },
  conv_lut_status_default: {
    zh: "💡 拖放.npy文件自动添加",
    en: "💡 Drop .npy to add",
  },
  conv_lut_status_selected: {
    zh: "✅ 已选择",
    en: "✅ Selected",
  },
  conv_lut_status_saved: {
    zh: "✅ LUT已保存",
    en: "✅ LUT saved",
  },
  conv_lut_status_error: {
    zh: "❌ 文件不存在",
    en: "❌ File not found",
  },
  conv_image_label: {
    zh: "输入图像",
    en: "Input Image",
  },
  crop_title: {
    zh: "图片裁剪",
    en: "Image Crop",
  },
  crop_original_size: {
    zh: "原图尺寸",
    en: "Original size",
  },
  crop_selection_size: {
    zh: "选区尺寸",
    en: "Selection size",
  },
  crop_x: {
    zh: "X 偏移",
    en: "X Offset",
  },
  crop_y: {
    zh: "Y 偏移",
    en: "Y Offset",
  },
  crop_width: {
    zh: "宽度",
    en: "Width",
  },
  crop_height: {
    zh: "高度",
    en: "Height",
  },
  crop_use_original: {
    zh: "使用原图",
    en: "Use original",
  },
  crop_confirm: {
    zh: "确认裁剪",
    en: "Confirm crop",
  },
  crop_auto_color: {
    zh: "🎨 计算最佳色彩细节",
    en: "🎨 Calculate optimal color detail",
  },
  conv_params_section: {
    zh: "#### ⚙️ 参数",
    en: "#### ⚙️ Parameters",
  },
  conv_color_mode: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  conv_color_mode_cmyw: {
    zh: "CMYW (青/品红/黄)",
    en: "CMYW (Cyan/Magenta/Yellow)",
  },
  conv_color_mode_rybw: {
    zh: "RYBW (红/黄/蓝)",
    en: "RYBW (Red/Yellow/Blue)",
  },
  conv_structure: {
    zh: "结构",
    en: "Structure",
  },
  conv_structure_double: {
    zh: "双面 (钥匙扣)",
    en: "Double-sided (Keychain)",
  },
  conv_structure_single: {
    zh: "单面 (浮雕)",
    en: "Single-sided (Relief)",
  },
  conv_modeling_mode: {
    zh: "🎨 建模模式",
    en: "🎨 Modeling Mode",
  },
  conv_modeling_mode_info: {
    zh: "高保真：RLE无缝拼接，水密模型 | 像素艺术：经典方块美学 | SVG模式：矢量直接转换",
    en: "High-Fidelity: RLE seamless, watertight | Pixel Art: Classic blocky aesthetic | SVG Mode: Direct vector conversion",
  },
  conv_modeling_mode_hifi: {
    zh: "🎨 高保真",
    en: "🎨 High-Fidelity",
  },
  conv_modeling_mode_pixel: {
    zh: "🧱 像素艺术",
    en: "🧱 Pixel Art",
  },
  conv_modeling_mode_vector: {
    zh: "📐 SVG模式",
    en: "📐 SVG Mode",
  },
  conv_quantize_colors: {
    zh: "🎨 色彩细节",
    en: "🎨 Color Detail",
  },
  conv_quantize_info: {
    zh: "颜色数量越多细节越丰富，但生成越慢",
    en: "Higher = More detail, Slower",
  },
  conv_auto_color_btn: {
    zh: "🔍 自动计算",
    en: "🔍 Auto Detect",
  },
  conv_auto_color_calculating: {
    zh: "⏳ 计算中...",
    en: "⏳ Calculating...",
  },
  conv_auto_bg: {
    zh: "🗑️ 移除背景",
    en: "🗑️ Remove Background",
  },
  conv_auto_bg_info: {
    zh: "自动移除图像背景色",
    en: "Auto remove background",
  },
  conv_tolerance: {
    zh: "容差",
    en: "Tolerance",
  },
  conv_tolerance_info: {
    zh: "背景容差值 (0-150)，值越大移除越多",
    en: "Higher = Remove more",
  },
  conv_width: {
    zh: "宽度 (mm)",
    en: "Width (mm)",
  },
  conv_height: {
    zh: "高度 (mm)",
    en: "Height (mm)",
  },
  conv_thickness: {
    zh: "背板 (mm)",
    en: "Backing (mm)",
  },
  conv_backing_color: {
    zh: "底板颜色",
    en: "Backing Color",
  },
  conv_preview_btn: {
    zh: "👁️ 生成预览",
    en: "👁️ Generate Preview",
  },
  conv_preview_section: {
    zh: "#### 🎨 2D预览",
    en: "#### 🎨 2D Preview",
  },
  conv_palette: {
    zh: "🎨 颜色调色板",
    en: "🎨 Color Palette",
  },
  conv_palette_step1: {
    zh: "### 1. 原图颜色（点击预览图）",
    en: "### 1. Original Color (Click Preview)",
  },
  conv_palette_step2: {
    zh: "### 2. 替换为（点击色块）",
    en: "### 2. Replace With (Click Swatch)",
  },
  conv_palette_selected_label: {
    zh: "当前选中",
    en: "Selected",
  },
  conv_palette_replace_label: {
    zh: "将替换为",
    en: "Replace With",
  },
  conv_palette_lut_loading: {
    zh: "⏳ 正在加载 LUT 颜色...",
    en: "⏳ Loading LUT colors...",
  },
  conv_palette_replacements_placeholder: {
    zh: "生成预览后显示替换列表",
    en: "Generate preview to see replacements",
  },
  conv_palette_replacements_label: {
    zh: "已生效的替换",
    en: "Applied Replacements",
  },
  conv_palette_apply_btn: {
    zh: "✅ 确认替换",
    en: "✅ Apply",
  },
  conv_palette_undo_btn: {
    zh: "↩️ 撤销",
    en: "↩️ Undo",
  },
  conv_palette_clear_btn: {
    zh: "🗑️ 清除所有",
    en: "🗑️ Clear",
  },
  conv_palette_user_replacements_title: {
    zh: "用户替换",
    en: "User Replacements",
  },
  conv_palette_auto_pairs_title: {
    zh: "自动配准",
    en: "Auto Pairs",
  },
  conv_palette_delete_selected_btn: {
    zh: "删除选中",
    en: "Delete Selected",
  },
  conv_palette_delete_selected_empty: {
    zh: "❌ 请先选中一项用户替换",
    en: "❌ Select one user replacement first",
  },
  conv_palette_user_empty: {
    zh: "暂无替换",
    en: "No replacements",
  },
  conv_palette_auto_empty: {
    zh: "暂无自动配准",
    en: "No auto pairs",
  },
  lut_grid_invalid: {
    zh: "⚠️ 请先选择一个有效的 LUT 文件",
    en: "⚠️ Please select a valid LUT file",
  },
  lut_grid_header: {
    zh: "🎨 当前 LUT 包含 <b>{count}</b> 种可打印颜色（点击选择）",
    en: "🎨 Current LUT contains <b>{count}</b> printable colors (click to select)",
  },

  // ==================== Loop / Outline / Cloisonne / Coating ====================
  conv_loop_section: {
    zh: "##### 🔗 挂孔设置",
    en: "##### 🔗 Loop Settings",
  },
  conv_loop_enable: {
    zh: "启用挂孔",
    en: "Enable Loop",
  },
  conv_loop_remove: {
    zh: "🗑️ 移除挂孔",
    en: "🗑️ Remove Loop",
  },
  conv_loop_width: {
    zh: "宽度(mm)",
    en: "Width(mm)",
  },
  conv_loop_length: {
    zh: "长度(mm)",
    en: "Length(mm)",
  },
  conv_loop_hole: {
    zh: "孔径(mm)",
    en: "Hole(mm)",
  },
  conv_loop_angle: {
    zh: "旋转角度°",
    en: "Rotation°",
  },
  conv_loop_info: {
    zh: "挂孔位置",
    en: "Loop Position",
  },
  conv_outline_section: {
    zh: "##### 外轮廓设置",
    en: "##### Outline Settings",
  },
  conv_outline_enable: {
    zh: "启用外轮廓",
    en: "Enable Outline",
  },
  conv_outline_width: {
    zh: "轮廓宽度(mm)",
    en: "Outline Width(mm)",
  },
  conv_cloisonne_section: {
    zh: "##### 掐丝珐琅特效",
    en: "##### Cloisonné Effect",
  },
  conv_cloisonne_enable: {
    zh: "启用掐丝珐琅",
    en: "Enable Cloisonné",
  },
  conv_cloisonne_wire_width: {
    zh: "丝线宽度(mm)",
    en: "Wire Width(mm)",
  },
  conv_cloisonne_wire_height: {
    zh: "丝线高度(mm)",
    en: "Wire Height(mm)",
  },
  conv_cloisonne_wire_color: {
    zh: "丝线颜色槽位",
    en: "Wire Color Slot",
  },
  conv_free_color_btn: {
    zh: "🎯 标记为自由色",
    en: "🎯 Mark as Free Color",
  },
  conv_free_color_clear_btn: {
    zh: "清除自由色",
    en: "Clear Free Colors",
  },
  conv_coating_section: {
    zh: "##### 透明镀层",
    en: "##### Transparent Coating",
  },
  conv_coating_enable: {
    zh: "启用透明镀层",
    en: "Enable Coating",
  },
  conv_coating_height: {
    zh: "镀层厚度(mm)",
    en: "Coating Height(mm)",
  },
  conv_status: {
    zh: "状态",
    en: "Status",
  },
  conv_generate_btn: {
    zh: "🚀 生成3MF",
    en: "🚀 Generate 3MF",
  },
  conv_3d_preview: {
    zh: "#### 🎮 3D预览",
    en: "#### 🎮 3D Preview",
  },
  conv_download_section: {
    zh: "#### 📁 下载【务必合并对象后再切片】",
    en: "#### 📁 Download [Merge objects before slicing]",
  },
  conv_download_file: {
    zh: "3MF文件",
    en: "3MF File",
  },

  // ==================== Calibration Tab ====================
  cal_title: {
    zh: "### 第二步：生成校准板",
    en: "### Step 2: Generate Calibration Board",
  },
  cal_desc: {
    zh: "生成1024种颜色的校准板，打印后用于提取打印机的实际色彩数据。",
    en: "Generate a 1024-color calibration board to extract your printer's actual color data.",
  },
  cal_params: {
    zh: "#### ⚙️ 参数",
    en: "#### ⚙️ Parameters",
  },
  cal_color_mode: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  cal_block_size: {
    zh: "色块尺寸 (mm)",
    en: "Block Size (mm)",
  },
  cal_gap: {
    zh: "间隙 (mm)",
    en: "Gap (mm)",
  },
  cal_backing: {
    zh: "底板颜色",
    en: "Backing Color",
  },
  cal_generate_btn: {
    zh: "🚀 生成",
    en: "🚀 Generate",
  },
  cal_status: {
    zh: "状态",
    en: "Status",
  },
  cal_preview: {
    zh: "#### 👁️ 预览",
    en: "#### 👁️ Preview",
  },
  cal_download: {
    zh: "下载 3MF",
    en: "Download 3MF",
  },

  // ==================== Color Extractor Tab ====================
  ext_title: {
    zh: "### 第三步：提取颜色数据",
    en: "### Step 3: Extract Color Data",
  },
  ext_desc: {
    zh: "拍摄打印好的校准板照片，提取真实的色彩数据生成 LUT 文件。",
    en: "Take a photo of your printed calibration board to extract real color data.",
  },
  ext_upload_section: {
    zh: "#### 📸 上传照片",
    en: "#### 📸 Upload Photo",
  },
  ext_color_mode: {
    zh: "🎨 色彩模式",
    en: "🎨 Color Mode",
  },
  ext_photo: {
    zh: "校准板照片",
    en: "Calibration Photo",
  },
  ext_rotate_btn: {
    zh: "↺ 旋转",
    en: "↺ Rotate",
  },
  ext_reset_btn: {
    zh: "🗑️ 重置",
    en: "🗑️ Reset",
  },
  ext_correction_section: {
    zh: "#### 🔧 校正参数",
    en: "#### 🔧 Correction",
  },
  ext_wb: {
    zh: "自动白平衡",
    en: "Auto WB",
  },
  ext_vignette: {
    zh: "暗角校正",
    en: "Vignette",
  },
  ext_zoom: {
    zh: "缩放",
    en: "Zoom",
  },
  ext_distortion: {
    zh: "畸变",
    en: "Distortion",
  },
  ext_offset_x: {
    zh: "X偏移",
    en: "Offset X",
  },
  ext_offset_y: {
    zh: "Y偏移",
    en: "Offset Y",
  },
  ext_extract_btn: {
    zh: "🚀 提取",
    en: "🚀 Extract",
  },
  ext_status: {
    zh: "状态",
    en: "Status",
  },
  ext_hint_white: {
    zh: "#### 👉 点击: **白色色块 (左上角)**",
    en: "#### 👉 Click: **White Block (Top-Left)**",
  },
  ext_marked: {
    zh: "标记图",
    en: "Marked",
  },
  ext_sampling: {
    zh: "#### 📍 采样预览",
    en: "#### 📍 Sampling",
  },
  ext_reference: {
    zh: "#### 🎯 参考",
    en: "#### 🎯 Reference",
  },
  ext_result: {
    zh: "#### 📊 结果 (点击修正)",
    en: "#### 📊 Result (Click to fix)",
  },
  ext_manual_fix: {
    zh: "#### 🛠️ 手动修正",
    en: "#### 🛠️ Manual Fix",
  },
  ext_click_cell: {
    zh: "点击左侧色块查看...",
    en: "Click cell on left...",
  },
  ext_override: {
    zh: "替换颜色",
    en: "Override Color",
  },
  ext_apply_btn: {
    zh: "🔧 应用",
    en: "🔧 Apply",
  },
  ext_download_npy: {
    zh: "下载 .npy",
    en: "Download .npy",
  },

  // ==================== 3D Viewer ====================
  viewer_fullscreen: {
    zh: "全屏",
    en: "Fullscreen",
  },
  viewer_exit_fullscreen: {
    zh: "退出全屏",
    en: "Exit Fullscreen",
  },
  viewer_screenshot: {
    zh: "截图",
    en: "Screenshot",
  },

  // ==================== Footer ====================
  footer_tip: {
    zh: "💡 提示: 使用高质量的PLA/PETG basic材料可获得最佳效果",
    en: "💡 Tip: Use high-quality translucent PLA/PETG basic for best results",
  },

  // ==================== Status Messages ====================
  msg_no_image: {
    zh: "❌ 请上传图片",
    en: "❌ Please upload an image",
  },
  msg_no_lut: {
    zh: "⚠️ 请选择或上传 .npy 校准文件！",
    en: "⚠️ Please upload a .npy calibration file!",
  },
  msg_preview_success: {
    zh: "✅ 预览",
    en: "✅ Preview",
  },
  msg_click_to_place: {
    zh: "点击图片放置挂孔",
    en: "Click to place loop",
  },
  msg_conversion_complete: {
    zh: "✅ 转换完成",
    en: "✅ Conversion complete",
  },
  msg_resolution: {
    zh: "分辨率",
    en: "Resolution",
  },
  msg_loop: {
    zh: "挂孔",
    en: "Loop",
  },
  msg_model_too_large: {
    zh: "⚠️ 模型过大，已禁用3D预览",
    en: "⚠️ Model too large, 3D preview disabled",
  },
  msg_preview_simplified: {
    zh: "ℹ️ 3D预览已简化",
    en: "ℹ️ 3D preview simplified",
  },

  // ==================== Palette / Replacement ====================
  palette_empty: {
    zh: "暂无颜色，请先生成预览。",
    en: "No colors yet. Generate a preview first.",
  },
  palette_count: {
    zh: "共 {count} 种颜色",
    en: "{count} colors in image",
  },
  palette_hint: {
    zh: "点击色块高亮预览",
    en: "Click swatch to highlight in preview",
  },
  palette_tooltip: {
    zh: "点击高亮: {hex} ({pct}%)",
    en: "Click to highlight: {hex} ({pct}%)",
  },
  palette_replaced_with: {
    zh: "替换为 {hex}",
    en: "Replaced with {hex}",
  },
  palette_click_to_select: {
    zh: "点击调色板选择颜色",
    en: "Click palette to select",
  },
  palette_need_preview: {
    zh: "❌ 请先生成预览",
    en: "❌ Please generate preview first",
  },
  palette_need_original: {
    zh: "❌ 请先选择要替换的颜色",
    en: "❌ Select a color to replace",
  },
  palette_need_replacement: {
    zh: "❌ 请先选择替换颜色",
    en: "❌ Select a replacement color",
  },
  palette_replaced: {
    zh: "✅ 已替换 {src} → {dst}",
    en: "✅ Replaced {src} → {dst}",
  },
  palette_cleared: {
    zh: "✅ 已清除所有颜色替换",
    en: "✅ Cleared all replacements",
  },
  palette_undo_empty: {
    zh: "❌ 没有可撤销的操作",
    en: "❌ Nothing to undo",
  },
  palette_undone: {
    zh: "↩️ 已撤销",
    en: "↩️ Undone",
  },

  // ==================== Color Merging ====================
  merge_enable_label: {
    zh: "启用自动颜色合并 Enable Auto Color Merging",
    en: "Enable Auto Color Merging",
  },
  merge_enable_info: {
    zh: "自动合并低使用率颜色到相近颜色",
    en: "Automatically merge low-usage colors to similar colors",
  },
  merge_threshold_label: {
    zh: "使用率阈值 Usage Threshold (%)",
    en: "Usage Threshold (%)",
  },
  merge_threshold_info: {
    zh: "低于此百分比的颜色将被合并",
    en: "Colors below this percentage will be merged",
  },
  merge_max_distance_label: {
    zh: "最大颜色距离 Max Color Distance (Delta-E)",
    en: "Max Color Distance (Delta-E)",
  },
  merge_max_distance_info: {
    zh: "只合并距离小于此值的颜色",
    en: "Only merge colors with distance below this value",
  },
  merge_preview_btn: {
    zh: "🔍 预览合并效果 Preview Merge",
    en: "🔍 Preview Merge",
  },
  merge_apply_btn: {
    zh: "✅ 应用合并 Apply Merge",
    en: "✅ Apply Merge",
  },
  merge_revert_btn: {
    zh: "↩️ 恢复原始 Revert",
    en: "↩️ Revert",
  },
  merge_status_empty: {
    zh: "💡 调整参数后点击预览",
    en: "💡 Adjust parameters and click preview",
  },
  merge_status_preview: {
    zh: "🔍 预览: {merged} 种颜色被合并 (质量: {quality:.1f})",
    en: "🔍 Preview: {merged} colors merged (quality: {quality:.1f})",
  },
  merge_status_applied: {
    zh: "✅ 已应用: {merged} 种颜色被合并",
    en: "✅ Applied: {merged} colors merged",
  },
  merge_status_reverted: {
    zh: "↩️ 已恢复到原始颜色",
    en: "↩️ Reverted to original colors",
  },
  merge_error_empty_palette: {
    zh: "❌ 调色板为空，无法执行颜色合并",
    en: "❌ Empty palette, cannot perform color merging",
  },
  merge_error_single_color: {
    zh: "❌ 图像只包含一种颜色，已禁用颜色合并",
    en: "❌ Image contains only one color, merging disabled",
  },
  merge_error_all_below_threshold: {
    zh: "⚠️ 所有颜色使用率都低于阈值，已禁用颜色合并以防止颜色丢失",
    en: "⚠️ All colors below threshold, merging disabled to prevent color loss",
  },
  merge_warning_no_targets: {
    zh: "⚠️ 部分颜色未找到合适的合并目标，保持原始颜色",
    en: "⚠️ Some colors have no suitable merge targets, keeping original",
  },
  merge_info_low_usage: {
    zh: "💡 检测到 {count} 种低使用率颜色 (<{threshold}%)",
    en: "💡 Detected {count} low-usage colors (<{threshold}%)",
  },
  merge_accordion_title: {
    zh: "🎨 颜色合并 Color Merging",
    en: "🎨 Color Merging",
  },

  // ==================== LUT Grid ====================
  lut_grid_load_hint: {
    zh: "加载 LUT 后显示可用颜色",
    en: "Load LUT to see available colors",
  },
  lut_grid_count: {
    zh: "共 {count} 种可用颜色",
    en: "{count} available colors",
  },
  lut_grid_search_placeholder: {
    zh: "搜索色号 (如 ff0000)",
    en: "Search hex (e.g. ff0000)",
  },
  lut_grid_search_clear: {
    zh: "清除",
    en: "Clear",
  },
  lut_grid_used: {
    zh: "图中已使用 ({count})",
    en: "Used in image ({count})",
  },
  lut_grid_other: {
    zh: "其他可用颜色 ({count})",
    en: "Other colors ({count})",
  },
  lut_grid_tooltip: {
    zh: "点击选择: {hex}",
    en: "Click to select: {hex}",
  },
  lut_grid_picker_label: {
    zh: "🎯 以色找色",
    en: "🎯 Find by Color",
  },
  lut_grid_picker_hint: {
    zh: "选一个颜色，自动匹配 LUT 中最接近的物理色",
    en: "Pick a color to find the closest match in LUT",
  },
  lut_grid_picker_btn: {
    zh: "匹配最近色",
    en: "Find Nearest",
  },
  lut_grid_picker_result: {
    zh: "✅ 最接近: {hex} (距离: {dist:.1f})",
    en: "✅ Nearest: {hex} (distance: {dist:.1f})",
  },
  lut_grid_hue_all: {
    zh: "全部",
    en: "All",
  },
  lut_grid_hue_red: {
    zh: "红色系",
    en: "Red",
  },
  lut_grid_hue_orange: {
    zh: "橙色系",
    en: "Orange",
  },
  lut_grid_hue_yellow: {
    zh: "黄色系",
    en: "Yellow",
  },
  lut_grid_hue_green: {
    zh: "绿色系",
    en: "Green",
  },
  lut_grid_hue_cyan: {
    zh: "青色系",
    en: "Cyan",
  },
  lut_grid_hue_blue: {
    zh: "蓝色系",
    en: "Blue",
  },
  lut_grid_hue_purple: {
    zh: "紫色系",
    en: "Purple",
  },
  lut_grid_hue_neutral: {
    zh: "中性色",
    en: "Neutral",
  },
  lut_grid_hue_fav: {
    zh: "收藏",
    en: "Favorites",
  },
  lut_grid_search_hex_placeholder: {
    zh: "输入 Hex 或 RGB 搜索定位 (如 #FF0000 或 255,0,0)",
    en: "Search by Hex or RGB (e.g. #FF0000 or 255,0,0)",
  },

  // ==================== Settings ====================
  settings_title: {
    zh: "## ⚙️ 设置",
    en: "## ⚙️ Settings",
  },
  settings_clear_cache: {
    zh: "🗑️ 清空缓存",
    en: "🗑️ Clear Cache",
  },
  settings_clear_output: {
    zh: "🗑️ 清空输出",
    en: "🗑️ Clear Output",
  },
  settings_reset_counters: {
    zh: "🔢 使用计数归零",
    en: "🔢 Reset Counters",
  },
  settings_cache_cleared: {
    zh: "✅ 缓存已清空，释放了 {} 空间",
    en: "✅ Cache cleared, freed {} of space",
  },
  settings_output_cleared: {
    zh: "✅ 输出已清空，释放了 {} 空间",
    en: "✅ Output cleared, freed {} of space",
  },
  settings_counters_reset: {
    zh: "✅ 计数器已归零：校准板: {} | 颜色提取: {} | 模型转换: {}",
    en: "✅ Counters reset: Calibrations: {} | Extractions: {} | Conversions: {}",
  },
  settings_cache_size: {
    zh: "📦 缓存大小: {}",
    en: "📦 Cache size: {}",
  },
  settings_output_size: {
    zh: "📦 输出大小: {}",
    en: "📦 Output size: {}",
  },
  theme_toggle_night: {
    zh: "🌙 夜间模式",
    en: "🌙 Night Mode",
  },
  theme_toggle_day: {
    zh: "☀️ 日间模式",
    en: "☀️ Day Mode",
  },

  // ==================== LUT Merge Tab ====================
  tab_merge: {
    zh: "🔀 色卡合并",
    en: "🔀 LUT Merge",
  },
  merge_title: {
    zh: "### 🔀 色卡合并",
    en: "### 🔀 LUT Merge",
  },
  merge_desc: {
    zh: "将不同色彩模式的LUT色卡合并为一个，获得更丰富的色彩。",
    en: "Merge LUT cards from different color modes into one for richer colors.",
  },
  merge_lut_primary_label: {
    zh: "🎯 主色卡（6色或8色）",
    en: "🎯 Primary LUT (6-Color or 8-Color)",
  },
  merge_lut_secondary_label: {
    zh: "➕ 副色卡（可多选）",
    en: "➕ Secondary LUTs (Multi-select)",
  },
  merge_lut_1_label: {
    zh: "选择LUT 1（主色卡）",
    en: "Select LUT 1 (Primary)",
  },
  merge_lut_2_label: {
    zh: "选择LUT 2（合并色卡）",
    en: "Select LUT 2 (Secondary)",
  },
  merge_secondary_modes: {
    zh: "已选副色卡",
    en: "Selected Secondary LUTs",
  },
  merge_secondary_none: {
    zh: "未选择副色卡",
    en: "No secondary LUTs selected",
  },
  merge_primary_hint: {
    zh: "💡 请先选择一个6色或8色的主色卡",
    en: "💡 Please select a 6-Color or 8-Color primary LUT first",
  },
  merge_primary_not_high: {
    zh: "❌ 主色卡必须是6色或8色模式",
    en: "❌ Primary LUT must be 6-Color or 8-Color mode",
  },
  merge_error_no_secondary: {
    zh: "❌ 请至少选择一个副色卡",
    en: "❌ Please select at least one secondary LUT",
  },
  merge_mode_label: {
    zh: "检测到的模式",
    en: "Detected Mode",
  },
  merge_mode_unknown: {
    zh: "未选择",
    en: "Not selected",
  },
  merge_dedup_label: {
    zh: "Delta-E 去重阈值",
    en: "Delta-E Dedup Threshold",
  },
  merge_dedup_info: {
    zh: "值越大去除的相近色越多，0=仅精确去重",
    en: "Higher = remove more similar colors, 0 = exact dedup only",
  },
  merge_btn: {
    zh: "🔀 执行合并",
    en: "🔀 Merge",
  },
  merge_status_ready: {
    zh: "💡 选择两个LUT后点击合并",
    en: "💡 Select two LUTs then click Merge",
  },
  merge_status_running: {
    zh: "⏳ 合并中...",
    en: "⏳ Merging...",
  },
  merge_status_success: {
    zh: "✅ 合并完成！合并前: {before} 色 → 合并后: {after} 色（精确去重: {exact}，相近色去除: {similar}）\n保存至: {path}",
    en: "✅ Merge complete! Before: {before} → After: {after} (exact dupes: {exact}, similar removed: {similar})\nSaved to: {path}",
  },
  merge_error_no_lut: {
    zh: "❌ 请选择至少两个LUT文件",
    en: "❌ Please select at least two LUT files",
  },
  merge_error_same_lut: {
    zh: "❌ 请选择不同的LUT文件",
    en: "❌ Please select different LUT files",
  },
  merge_error_incompatible: {
    zh: "❌ 不兼容的LUT组合: {msg}",
    en: "❌ Incompatible LUT combination: {msg}",
  },
  merge_error_failed: {
    zh: "❌ 合并失败: {msg}",
    en: "❌ Merge failed: {msg}",
  },

  // ==================== About Page Content ====================
  about_content: {
    zh: [
      "## 🌟 Lumina Studio v1.6.5",
      "",
      "**多材料3D打印色彩系统**",
      "",
      "让FDM打印也能拥有精准的色彩还原",
      "",
      "---",
      "",
      "### 📖 使用流程",
      "",
      "1. **生成校准板** → 打印1024色校准网格",
      "2. **提取颜色** → 拍照并提取打印机实际色彩",
      "3. **转换图像** → 将图片转为多层3D模型",
      "",
      "---",
      "",
      "### 🎨 色彩模式定位点顺序",
      "",
      "| 模式 | 左上 | 右上 | 右下 | 左下 |",
      "|------|------|------|------|------|",
      "| **RYBW** | ⬜ 白色 | 🟥 红色 | 🟦 蓝色 | 🟨 黄色 |",
      "| **CMYW** | ⬜ 白色 | 🔵 青色 | 🟣 品红 | 🟨 黄色 |",
      "",
      "---",
      "",
      "### 🔬 技术原理",
      "",
      "- **Beer-Lambert 光学混色**",
      "- **KD-Tree 色彩匹配**",
      "- **RLE 几何生成**",
      "- **K-Means 色彩量化**",
    ].join("\n"),
    en: [
      "## 🌟 Lumina Studio v1.6.5",
      "",
      "**Multi-Material 3D Print Color System**",
      "",
      "Accurate color reproduction for FDM printing",
      "",
      "---",
      "",
      "### 📖 Workflow",
      "",
      "1. **Generate Calibration** → Print 1024-color grid",
      "2. **Extract Colors** → Photo → extract real colors",
      "3. **Convert Image** → Image → multi-layer 3D model",
      "",
      "---",
      "",
      "### 🎨 Color Mode Corner Order",
      "",
      "| Mode | Top-Left | Top-Right | Bottom-Right | Bottom-Left |",
      "|------|----------|-----------|--------------|-------------|",
      "| **RYBW** | ⬜ White | 🟥 Red | 🟦 Blue | 🟨 Yellow |",
      "| **CMYW** | ⬜ White | 🔵 Cyan | 🟣 Magenta | 🟨 Yellow |",
      "",
      "---",
      "",
      "### 🔬 Technology",
      "",
      "- **Beer-Lambert Optical Color Mixing**",
      "- **KD-Tree Color Matching**",
      "- **RLE Geometry Generation**",
      "- **K-Means Color Quantization**",
    ].join("\n"),
  },

  // ==================== Widget Titles ====================
  "widget.converter": {
    zh: "图像转换",
    en: "Converter",
  },
  "widget.calibration": {
    zh: "校准板",
    en: "Calibration",
  },
  "widget.extractor": {
    zh: "颜色提取",
    en: "Extractor",
  },
  "widget.lutManager": {
    zh: "LUT 管理",
    en: "LUT Manager",
  },
  "widget.fiveColor": {
    zh: "配方查询",
    en: "Five-Color",
  },
  "widget.basicSettings": {
    zh: "基础设置",
    en: "Basic Settings",
  },
  "widget.advancedSettings": {
    zh: "高级设置",
    en: "Advanced Settings",
  },
  "widget.reliefSettings": {
    zh: "浮雕设置",
    en: "Relief Settings",
  },
  "widget.palettePanel": {
    zh: "调色板",
    en: "Palette",
  },
  "widget.lutColorGrid": {
    zh: "LUT 颜色网格",
    en: "LUT Color Grid",
  },
  "widget.outlineSettings": {
    zh: "轮廓设置",
    en: "Outline Settings",
  },
  "widget.cloisonneSettings": {
    zh: "掐丝珐琅设置",
    en: "Cloisonné Settings",
  },
  "widget.coatingSettings": {
    zh: "涂层设置",
    en: "Coating Settings",
  },
  "widget.keychainLoop": {
    zh: "挂件环设置",
    en: "Keychain Loop",
  },
  "widget.actionBar": {
    zh: "操作栏",
    en: "Actions",
  },
  "widget.colorWorkstation": {
    zh: "颜色工作站",
    en: "Color Workstation",
  },

  // ==================== TAB Navigation Titles ====================
  "tab.converter": {
    zh: "图像转换",
    en: "Converter",
  },
  "tab.calibration": {
    zh: "校准",
    en: "Calibration",
  },
  "tab.extractor": {
    zh: "提取器",
    en: "Extractor",
  },
  "tab.lutManager": {
    zh: "LUT 管理",
    en: "LUT Manager",
  },
  "tab.fiveColor": {
    zh: "配方查询",
    en: "Five-Color",
  },

  // ==================== App Header ====================
  app_header_title: {
    zh: "Lumina Studio 2.0",
    en: "Lumina Studio 2.0",
  },
  app_checking_backend: {
    zh: "正在检查后端…",
    en: "Checking backend…",
  },
  app_backend_connected: {
    zh: "后端已连接",
    en: "Backend Connected",
  },
  app_backend_unreachable: {
    zh: "后端不可达",
    en: "Backend Unreachable",
  },
  app_reset_layout: {
    zh: "重置布局",
    en: "Reset Layout",
  },
  app_3d_scene_error: {
    zh: "3D 场景加载失败",
    en: "3D scene failed to load",
  },
  app_toggle_language: {
    zh: "切换语言",
    en: "Toggle language",
  },
  app_toggle_theme: {
    zh: "切换主题",
    en: "Toggle theme",
  },

  // ==================== LUT Manager Panel ====================
  lut_manager_title: {
    zh: "LUT 合并工具",
    en: "LUT Merge Tool",
  },
  lut_manager_desc: {
    zh: "将多个 LUT 合并为一个，支持 Delta-E 去重。主 LUT 必须为 6-Color 或 8-Color 模式。",
    en: "Merge multiple LUTs into one with Delta-E dedup. Primary LUT must be 6-Color or 8-Color mode.",
  },
  lut_manager_primary_label: {
    zh: "主 LUT",
    en: "Primary LUT",
  },
  lut_manager_primary_placeholder: {
    zh: "选择主 LUT...",
    en: "Select primary LUT...",
  },
  lut_manager_loading: {
    zh: "加载中...",
    en: "Loading...",
  },
  lut_manager_primary_mode_invalid: {
    zh: "主 LUT 必须为 6-Color 或 8-Color 模式",
    en: "Primary LUT must be 6-Color or 8-Color mode",
  },
  lut_manager_secondary_label: {
    zh: "副 LUT",
    en: "Secondary LUTs",
  },
  lut_manager_no_secondary: {
    zh: "无可用的副 LUT",
    en: "No secondary LUTs available",
  },
  lut_manager_select_primary_first: {
    zh: "请先选择主 LUT",
    en: "Please select a primary LUT first",
  },
  lut_manager_dedup_label: {
    zh: "去重阈值",
    en: "Dedup Threshold",
  },
  lut_manager_dedup_hint: {
    zh: "0 = 仅精确去重，值越大去除越多相近色",
    en: "0 = exact dedup only, higher = remove more similar colors",
  },
  lut_manager_merge_btn: {
    zh: "合并并保存",
    en: "Merge & Save",
  },
  lut_manager_merge_success: {
    zh: "✓ 合并成功！",
    en: "✓ Merge successful!",
  },
  lut_manager_merge_before: {
    zh: "合并前",
    en: "Before",
  },
  lut_manager_merge_after: {
    zh: "合并后",
    en: "After",
  },
  lut_manager_exact_dupes: {
    zh: "精确去重",
    en: "Exact dupes",
  },
  lut_manager_similar_removed: {
    zh: "相近色去除",
    en: "Similar removed",
  },
  lut_manager_file: {
    zh: "文件",
    en: "File",
  },
  lut_manager_close_error: {
    zh: "关闭错误",
    en: "Close error",
  },

  // ==================== About View ====================
  about_title: {
    zh: "Lumina Studio 2.0",
    en: "Lumina Studio 2.0",
  },
  about_desc: {
    zh: "更多信息即将推出",
    en: "More info coming soon",
  },
  about_clear_cache_loading: {
    zh: "清理中...",
    en: "Clearing...",
  },
  about_clear_cache: {
    zh: "清除系统缓存",
    en: "Clear System Cache",
  },
  about_close_notification: {
    zh: "关闭通知",
    en: "Close notification",
  },

  // ==================== Calibration Panel ====================
  cal_color_mode_label: {
    zh: "颜色模式",
    en: "Color Mode",
  },
  cal_block_size_label: {
    zh: "色块尺寸",
    en: "Block Size",
  },
  cal_gap_label: {
    zh: "色块间距",
    en: "Block Gap",
  },
  cal_backing_label: {
    zh: "底板颜色",
    en: "Backing Color",
  },
  cal_generate_btn: {
    zh: "生成校准板",
    en: "Generate Calibration",
  },
  cal_download_3mf: {
    zh: "下载 3MF 文件",
    en: "Download 3MF File",
  },
  cal_preview_alt: {
    zh: "校准板预览",
    en: "Calibration preview",
  },

  // ==================== Extractor Panel ====================
  ext_color_mode_label: {
    zh: "颜色模式",
    en: "Color Mode",
  },
  ext_page_label: {
    zh: "页码",
    en: "Page",
  },
  ext_upload_label: {
    zh: "上传校准板照片",
    en: "Upload Calibration Photo",
  },
  ext_offset_x_label: {
    zh: "水平偏移 (offset_x)",
    en: "Horizontal Offset (offset_x)",
  },
  ext_offset_y_label: {
    zh: "垂直偏移 (offset_y)",
    en: "Vertical Offset (offset_y)",
  },
  ext_zoom_label: {
    zh: "缩放 (zoom)",
    en: "Zoom",
  },
  ext_distortion_label: {
    zh: "畸变校正 (distortion)",
    en: "Distortion Correction",
  },
  ext_wb_label: {
    zh: "白平衡校正",
    en: "White Balance Correction",
  },
  ext_vignette_label: {
    zh: "暗角校正",
    en: "Vignette Correction",
  },
  ext_extract_btn_label: {
    zh: "提取颜色",
    en: "Extract Colors",
  },
  ext_clear_corners: {
    zh: "清除角点",
    en: "Clear Corners",
  },
  ext_merge_5c_title: {
    zh: "5色扩展双页合并",
    en: "5-Color Extended Dual-Page Merge",
  },
  ext_merge_8c_title: {
    zh: "8色双页合并",
    en: "8-Color Dual-Page Merge",
  },
  ext_merge_5c_btn: {
    zh: "合并 5 色 LUT",
    en: "Merge 5-Color LUT",
  },
  ext_merge_8c_btn: {
    zh: "合并 8 色 LUT",
    en: "Merge 8-Color LUT",
  },
  ext_page_extracted: {
    zh: "已提取",
    en: "Extracted",
  },
  ext_page_not_extracted: {
    zh: "未提取",
    en: "Not extracted",
  },
  ext_download_lut: {
    zh: "下载 LUT 文件 (.npy)",
    en: "Download LUT File (.npy)",
  },
  ext_manual_fix_hint: {
    zh: "点击右侧 LUT 预览图中的色块可手动修正颜色",
    en: "Click a cell in the LUT preview to manually fix its color",
  },

  // ==================== Extractor Canvas ====================
  ext_canvas_warp_view: {
    zh: "透视校正",
    en: "Warp View",
  },
  ext_canvas_lut_preview: {
    zh: "LUT 预览 / 点击色块修正颜色",
    en: "LUT Preview / Click cell to fix color",
  },
  ext_canvas_row: {
    zh: "行",
    en: "Row",
  },
  ext_canvas_col: {
    zh: "列",
    en: "Col",
  },
  ext_canvas_fixing: {
    zh: "修正中...",
    en: "Fixing...",
  },
  ext_canvas_confirm_fix: {
    zh: "确认修正",
    en: "Confirm Fix",
  },
  ext_canvas_cancel: {
    zh: "取消",
    en: "Cancel",
  },
  ext_canvas_upload_hint: {
    zh: "请在左侧面板上传校准板照片",
    en: "Upload a calibration board photo from the left panel",
  },
  ext_canvas_upload_hint_en: {
    zh: "上传校准板照片以开始",
    en: "Upload a calibration board photo to begin",
  },
  ext_canvas_positioning_done: {
    zh: "定位完成",
    en: "Positioning Complete",
  },
  ext_canvas_click_corner: {
    zh: "请点击第 {n} 个角点: {label}",
    en: "Click corner {n}: {label}",
  },

  // ==================== Basic Settings ====================
  basic_batch_mode: {
    zh: "批量模式",
    en: "Batch Mode",
  },
  basic_crop_after_upload: {
    zh: "上传后裁剪",
    en: "Crop After Upload",
  },
  basic_lut_label: {
    zh: "LUT",
    en: "LUT",
  },
  basic_lut_placeholder: {
    zh: "选择 LUT...",
    en: "Select LUT...",
  },
  basic_color_mode_label: {
    zh: "色彩模式",
    en: "Color Mode",
  },
  basic_width: {
    zh: "宽度",
    en: "Width",
  },
  basic_height: {
    zh: "高度",
    en: "Height",
  },
  basic_thickness: {
    zh: "厚度",
    en: "Thickness",
  },
  basic_structure_mode: {
    zh: "结构模式",
    en: "Structure Mode",
  },
  basic_modeling_mode: {
    zh: "建模模式",
    en: "Modeling Mode",
  },
  basic_image_format_error: {
    zh: "仅支持 JPG/PNG/SVG 格式",
    en: "Only JPG/PNG/SVG formats are supported",
  },

  // ==================== Structure Mode Options ====================
  "structure_mode.Double-sided": {
    zh: "双面（钥匙扣）",
    en: "Double-sided",
  },
  "structure_mode.Single-sided": {
    zh: "单面（浮雕）",
    en: "Single-sided",
  },

  // ==================== Modeling Mode Options ====================
  "modeling_mode.high-fidelity": {
    zh: "高保真",
    en: "High-Fidelity",
  },
  "modeling_mode.pixel": {
    zh: "像素艺术",
    en: "Pixel Art",
  },
  "modeling_mode.vector": {
    zh: "矢量模式",
    en: "Vector",
  },

  // ==================== Advanced Settings ====================
  adv_quantize_colors: {
    zh: "量化颜色数",
    en: "Quantize Colors",
  },
  adv_bg_tolerance: {
    zh: "背景容差",
    en: "Background Tolerance",
  },
  adv_auto_bg: {
    zh: "自动背景",
    en: "Auto Background",
  },
  adv_enable_cleanup: {
    zh: "启用清理",
    en: "Enable Cleanup",
  },
  adv_separate_backing: {
    zh: "分离底板",
    en: "Separate Backing",
  },
  adv_hue_protection: {
    zh: "色相保护",
    en: "Hue Protection",
  },

  // ==================== Relief Settings ====================
  relief_enable: {
    zh: "启用浮雕",
    en: "Enable Relief",
  },
  relief_max_height: {
    zh: "最大高度",
    en: "Max Height",
  },
  relief_auto_height_mode: {
    zh: "自动高度模式",
    en: "Auto Height Mode",
  },
  relief_darker_higher: {
    zh: "深色凸起",
    en: "Darker Higher",
  },
  relief_lighter_higher: {
    zh: "浅色凸起",
    en: "Lighter Higher",
  },
  relief_use_heightmap: {
    zh: "根据高度图",
    en: "Use Heightmap",
  },
  relief_heightmap_label: {
    zh: "高度图",
    en: "Heightmap",
  },
  relief_file_selected: {
    zh: "已选择",
    en: "Selected",
  },

  // ==================== Outline Settings ====================
  outline_enable: {
    zh: "启用描边",
    en: "Enable Outline",
  },
  outline_width: {
    zh: "描边宽度",
    en: "Outline Width",
  },

  // ==================== Cloisonne Settings ====================
  cloisonne_enable: {
    zh: "启用掐丝珐琅",
    en: "Enable Cloisonné",
  },
  cloisonne_wire_width: {
    zh: "金属丝宽度",
    en: "Wire Width",
  },
  cloisonne_wire_height: {
    zh: "金属丝高度",
    en: "Wire Height",
  },

  // ==================== Coating Settings ====================
  coating_enable: {
    zh: "启用涂层",
    en: "Enable Coating",
  },
  coating_height: {
    zh: "涂层高度",
    en: "Coating Height",
  },

  // ==================== Keychain Loop Settings ====================
  loop_enable: {
    zh: "添加挂件环",
    en: "Add Keychain Loop",
  },
  loop_width: {
    zh: "环宽度",
    en: "Loop Width",
  },
  loop_length: {
    zh: "环长度",
    en: "Loop Length",
  },
  loop_hole_diameter: {
    zh: "环孔直径",
    en: "Loop Hole Diameter",
  },

  // ==================== Action Bar ====================
  action_upload_hint: {
    zh: "请先上传图片并选择 LUT",
    en: "Please upload an image and select a LUT first",
  },
  action_batch_upload_hint: {
    zh: "请先添加图片并选择 LUT",
    en: "Please add images and select a LUT first",
  },
  action_preview: {
    zh: "预览",
    en: "Preview",
  },
  action_generate: {
    zh: "生成",
    en: "Generate",
  },
  action_batch_generate: {
    zh: "批量生成",
    en: "Batch Generate",
  },
  action_preview_alt: {
    zh: "预览结果",
    en: "Preview result",
  },

  // ==================== Bed Size Selector ====================
  bed_size_label: {
    zh: "热床尺寸",
    en: "Bed Size",
  },
  bed_size_loading: {
    zh: "加载中...",
    en: "Loading...",
  },
  bed_size_placeholder: {
    zh: "选择热床尺寸...",
    en: "Select bed size...",
  },

  // ==================== Palette Panel ====================
  palette_no_data: {
    zh: "暂无调色板数据，请先完成预览",
    en: "No palette data. Please generate a preview first.",
  },
  palette_quantized: {
    zh: "量化色",
    en: "Quantized",
  },
  palette_matched: {
    zh: "匹配色",
    en: "Matched",
  },
  palette_replaced: {
    zh: "替换色",
    en: "Replaced",
  },
  palette_undo: {
    zh: "撤销",
    en: "Undo",
  },
  palette_clear_remaps: {
    zh: "清空替换",
    en: "Clear Remaps",
  },
  palette_list_label: {
    zh: "调色板颜色列表",
    en: "Palette color list",
  },

  // ==================== LUT Color Grid ====================
  lut_grid_loading: {
    zh: "加载 LUT 颜色中...",
    en: "Loading LUT colors...",
  },
  lut_grid_select_lut: {
    zh: "请先选择 LUT 以加载可用颜色",
    en: "Select a LUT to load available colors",
  },
  lut_grid_total_colors: {
    zh: "共 {total} 色，显示 {visible} 色",
    en: "{total} colors, showing {visible}",
  },
  lut_grid_selected: {
    zh: "已选中",
    en: "Selected",
  },
  lut_grid_search_placeholder_short: {
    zh: "搜索 HEX / RGB 颜色...",
    en: "Search HEX / RGB...",
  },
  lut_grid_hue_all_short: {
    zh: "全部",
    en: "All",
  },
  lut_grid_hue_fav_short: {
    zh: "收藏",
    en: "Favorites",
  },
  lut_grid_hue_red_short: {
    zh: "红",
    en: "Red",
  },
  lut_grid_hue_orange_short: {
    zh: "橙",
    en: "Orange",
  },
  lut_grid_hue_yellow_short: {
    zh: "黄",
    en: "Yellow",
  },
  lut_grid_hue_green_short: {
    zh: "绿",
    en: "Green",
  },
  lut_grid_hue_cyan_short: {
    zh: "青",
    en: "Cyan",
  },
  lut_grid_hue_blue_short: {
    zh: "蓝",
    en: "Blue",
  },
  lut_grid_hue_purple_short: {
    zh: "紫",
    en: "Purple",
  },
  lut_grid_hue_neutral_short: {
    zh: "中性",
    en: "Neutral",
  },
  lut_grid_recommendations: {
    zh: "推荐替换色",
    en: "Recommended Replacements",
  },
  lut_grid_used_in_image: {
    zh: "图中使用",
    en: "Used in image",
  },
  lut_grid_other_available: {
    zh: "其他可用",
    en: "Other available",
  },
  lut_grid_all_available: {
    zh: "全部可用",
    en: "All available",
  },
  lut_grid_no_match: {
    zh: "无匹配颜色",
    en: "No matching colors",
  },
  lut_grid_color_label: {
    zh: "颜色 {hex}",
    en: "Color {hex}",
  },
  lut_grid_color_fav: {
    zh: "已收藏",
    en: "Favorited",
  },
  lut_grid_dblclick_fav: {
    zh: "双击收藏",
    en: "Double-click to favorite",
  },
  lut_grid_dblclick_unfav: {
    zh: "双击取消收藏",
    en: "Double-click to unfavorite",
  },

  // ==================== Batch File Uploader ====================
  batch_drop_hint: {
    zh: "拖拽图片或点击上传（支持多选）",
    en: "Drag & drop images or click to upload (multi-select)",
  },
  batch_drop_aria: {
    zh: "拖拽图片或点击上传多个文件",
    en: "Drag images or click to upload multiple files",
  },
  batch_file_count: {
    zh: "已选 {count} 个文件",
    en: "{count} files selected",
  },
  batch_file_list_label: {
    zh: "已选文件列表",
    en: "Selected files list",
  },
  batch_delete_file: {
    zh: "删除 {name}",
    en: "Delete {name}",
  },

  // ==================== Image Upload ====================
  upload_drag_hint: {
    zh: "拖拽图片或点击上传",
    en: "Drag & drop image or click to upload",
  },

  // ==================== Zoomable Image ====================
  zoom_reset: {
    zh: "重置缩放",
    en: "Reset Zoom",
  },

  // ==================== Batch Result Summary ====================
  batch_success: {
    zh: "成功",
    en: "Success",
  },
  batch_total: {
    zh: "总计",
    en: "Total",
  },
  batch_failed: {
    zh: "失败",
    en: "Failed",
  },
  batch_download_zip: {
    zh: "下载 ZIP",
    en: "Download ZIP",
  },
  batch_download_zip_aria: {
    zh: "下载 ZIP 文件",
    en: "Download ZIP file",
  },
  batch_failed_files: {
    zh: "失败文件：",
    en: "Failed files:",
  },
  batch_failed_list_label: {
    zh: "失败文件列表",
    en: "Failed files list",
  },

  // ==================== Slicer Selector ====================
  slicer_open_in: {
    zh: "在 {name} 中打开",
    en: "Open in {name}",
  },
  slicer_generate_open_in: {
    zh: "生成并在 {name} 中打开",
    en: "Generate & open in {name}",
  },
  slicer_download_3mf: {
    zh: "下载 3MF",
    en: "Download 3MF",
  },
  slicer_generate_download: {
    zh: "生成并下载",
    en: "Generate & Download",
  },
  slicer_detecting: {
    zh: "正在检测切片软件...",
    en: "Detecting slicers...",
  },
  slicer_not_detected: {
    zh: "未检测到切片软件",
    en: "No slicers detected",
  },
  slicer_toggle_list: {
    zh: "切换切片软件列表",
    en: "Toggle slicer list",
  },

  // ==================== Crop Modal ====================
  crop_modal_title: {
    zh: "裁剪图片",
    en: "Crop Image",
  },
  crop_modal_close: {
    zh: "关闭",
    en: "Close",
  },
  crop_modal_original: {
    zh: "原图",
    en: "Original",
  },
  crop_modal_selection: {
    zh: "选区",
    en: "Selection",
  },
  crop_modal_free: {
    zh: "自由",
    en: "Free",
  },
  crop_modal_use_original: {
    zh: "使用原图",
    en: "Use Original",
  },
  crop_modal_confirm: {
    zh: "确认裁剪",
    en: "Confirm Crop",
  },

  // ==================== Five Color Query Panel ====================
  five_color_lut_label: {
    zh: "LUT 选择",
    en: "LUT Selection",
  },
  five_color_lut_placeholder: {
    zh: "请选择 LUT",
    en: "Select LUT",
  },
  five_color_clear: {
    zh: "清除",
    en: "Clear",
  },
  five_color_undo: {
    zh: "撤销",
    en: "Undo",
  },
  five_color_reverse: {
    zh: "反序",
    en: "Reverse",
  },
  five_color_query: {
    zh: "查询",
    en: "Query",
  },
  five_color_close_error: {
    zh: "关闭错误",
    en: "Close error",
  },
  five_color_result_hex: {
    zh: "Hex",
    en: "Hex",
  },
  five_color_result_rgb: {
    zh: "RGB",
    en: "RGB",
  },
  five_color_result_row: {
    zh: "行号",
    en: "Row",
  },
  five_color_result_color: {
    zh: "结果颜色 {hex}",
    en: "Result color {hex}",
  },
  five_color_not_found: {
    zh: "未找到匹配",
    en: "No match found",
  },
  five_color_selected: {
    zh: "已选颜色 {n}: {name}",
    en: "Selected color {n}: {name}",
  },
  five_color_slot_empty: {
    zh: "颜色槽 {n}: 空",
    en: "Color slot {n}: empty",
  },
  five_color_select_color: {
    zh: "选择颜色 {name} ({hex})",
    en: "Select color {name} ({hex})",
  },
  five_color_no_base_colors: {
    zh: "未加载到基础颜色",
    en: "No base colors loaded",
  },
  five_color_select_lut_first: {
    zh: "请先选择 LUT 以加载基础颜色",
    en: "Select a LUT to load base colors",
  },

  // ==================== Widget Error ====================
  widget_error: {
    zh: "组件出错",
    en: "Widget error",
  },
  widget_retry: {
    zh: "重试",
    en: "Retry",
  },
  widget_expand: {
    zh: "展开",
    en: "Expand",
  },
  widget_collapse: {
    zh: "折叠",
    en: "Collapse",
  },
};
