"""
Lumina Studio - Internationalization Module
Internationalization module - Complete Chinese-English translation dictionary
"""


class I18n:
    """
    Internationalization management class
    Provides Chinese-English translation and language switching functionality
    """
    
    # Complete translation dictionary
    TEXTS = {
        # ==================== Application Title and Header ====================
        'app_title': {
            'zh': '✨ Lumina Studio',
            'en': '✨ Lumina Studio'
        },
        'app_subtitle': {
            'zh': '多材料3D打印色彩系统 | v1.6.0',
            'en': 'Multi-Material 3D Print Color System | v1.6.0'
        },
        'lang_btn_zh': {
            'zh': '🌐 中文',
            'en': '🌐 中文'
        },
        'lang_btn_en': {
            'zh': '🌐 English',
            'en': '🌐 English'
        },
        
        # ==================== Stats Bar ====================
        'stats_total': {
            'zh': '📊 累计生成',
            'en': '📊 Total Generated'
        },
        'stats_calibrations': {
            'zh': '校准板',
            'en': 'Calibrations'
        },
        'stats_extractions': {
            'zh': '颜色提取',
            'en': 'Extractions'
        },
        'stats_conversions': {
            'zh': '模型转换',
            'en': 'Conversions'
        },
        
        # ==================== Tab Titles ====================
        'tab_converter': {
            'zh': '💎 图像转换',
            'en': '💎 Image Converter'
        },
        'tab_calibration': {
            'zh': '📐 校准板生成',
            'en': '📐 Calibration'
        },
        'tab_extractor': {
            'zh': '🎨 颜色提取',
            'en': '🎨 Color Extractor'
        },
        'tab_about': {
            'zh': 'ℹ️ 关于',
            'en': 'ℹ️ About'
        },
        
        # ==================== Converter Tab ====================
        'conv_title': {
            'zh': '### 第一步：转换图像',
            'en': '### Step 1: Convert Image'
        },
        'conv_desc': {
            'zh': '**两种建模模式**：高保真（RLE无缝拼接）、像素艺术（方块风格）\n\n**流程**: 上传LUT和图像 → 选择建模模式 → 调整色彩细节 → 预览 → 生成',
            'en': '**Two Modeling Modes**: High-Fidelity (RLE seamless) and Pixel Art (blocky style)\n\n**Workflow**: Upload LUT & Image → Select Mode → Adjust Color Detail → Preview → Generate'
        },
        'conv_input_section': {
            'zh': '#### 📁 输入',
            'en': '#### 📁 Input'
        },
        'conv_lut_title': {
            'zh': '**校准数据 (.npy)**',
            'en': '**Calibration Data (.npy)**'
        },
        'conv_lut_dropdown': {
            'zh': '选择预设',
            'en': 'Select Preset'
        },
        'conv_lut_info': {
            'zh': '从预设库中选择LUT',
            'en': 'Select from library'
        },
        'conv_lut_status_default': {
            'zh': '💡 拖放.npy文件自动添加',
            'en': '💡 Drop .npy to add'
        },
        'conv_lut_status_selected': {
            'zh': '✅ 已选择',
            'en': '✅ Selected'
        },
        'conv_lut_status_saved': {
            'zh': '✅ LUT已保存',
            'en': '✅ LUT saved'
        },
        'conv_lut_status_error': {
            'zh': '❌ 文件不存在',
            'en': '❌ File not found'
        },
        'conv_image_label': {
            'zh': '输入图像',
            'en': 'Input Image'
        },

        'crop_title': {
            'zh': '图片裁剪',
            'en': 'Image Crop'
        },
        'crop_original_size': {
            'zh': '原图尺寸',
            'en': 'Original size'
        },
        'crop_selection_size': {
            'zh': '选区尺寸',
            'en': 'Selection size'
        },
        'crop_x': {
            'zh': 'X 偏移',
            'en': 'X Offset'
        },
        'crop_y': {
            'zh': 'Y 偏移',
            'en': 'Y Offset'
        },
        'crop_width': {
            'zh': '宽度',
            'en': 'Width'
        },
        'crop_height': {
            'zh': '高度',
            'en': 'Height'
        },
        'crop_use_original': {
            'zh': '使用原图',
            'en': 'Use original'
        },
        'crop_confirm': {
            'zh': '确认裁剪',
            'en': 'Confirm crop'
        },
        'crop_auto_color': {
            'zh': '🎨 计算最佳色彩细节',
            'en': '🎨 Calculate optimal color detail'
        },
        'conv_params_section': {
            'zh': '#### ⚙️ 参数',
            'en': '#### ⚙️ Parameters'
        },
        'conv_color_mode': {
            'zh': '色彩模式',
            'en': 'Color Mode'
        },
        'conv_color_mode_cmyw': {
            'zh': 'CMYW (青/品红/黄)',
            'en': 'CMYW (Cyan/Magenta/Yellow)'
        },
        'conv_color_mode_rybw': {
            'zh': 'RYBW (红/黄/蓝)',
            'en': 'RYBW (Red/Yellow/Blue)'
        },
        'conv_structure': {
            'zh': '结构',
            'en': 'Structure'
        },
        'conv_structure_double': {
            'zh': '双面 (钥匙扣)',
            'en': 'Double-sided (Keychain)'
        },
        'conv_structure_single': {
            'zh': '单面 (浮雕)',
            'en': 'Single-sided (Relief)'
        },
        'conv_modeling_mode': {
            'zh': '🎨 建模模式',
            'en': '🎨 Modeling Mode'
        },
        'conv_modeling_mode_info': {
            'zh': '高保真：RLE无缝拼接，水密模型 | 像素艺术：经典方块美学 | SVG模式：矢量直接转换',
            'en': 'High-Fidelity: RLE seamless, watertight | Pixel Art: Classic blocky aesthetic | SVG Mode: Direct vector conversion'
        },
        'conv_modeling_mode_hifi': {
            'zh': '🎨 高保真',
            'en': '🎨 High-Fidelity'
        },
        'conv_modeling_mode_pixel': {
            'zh': '🧱 像素艺术',
            'en': '🧱 Pixel Art'
        },
        'conv_modeling_mode_vector': {
            'zh': '📐 SVG模式',
            'en': '📐 SVG Mode'
        },
        'conv_quantize_colors': {
            'zh': '🎨 色彩细节',
            'en': '🎨 Color Detail'
        },
        'conv_quantize_info': {
            'zh': '颜色数量越多细节越丰富，但生成越慢',
            'en': 'Higher = More detail, Slower'
        },
        'conv_auto_color_btn': {
            'zh': '🔍 自动计算',
            'en': '🔍 Auto Detect'
        },
        'conv_auto_color_calculating': {
            'zh': '⏳ 计算中...',
            'en': '⏳ Calculating...'
        },
        'conv_auto_bg': {
            'zh': '🗑️ 移除背景',
            'en': '🗑️ Remove Background'
        },
        'conv_auto_bg_info': {
            'zh': '自动移除图像背景色',
            'en': 'Auto remove background'
        },
        'conv_tolerance': {
            'zh': '容差',
            'en': 'Tolerance'
        },
        'conv_tolerance_info': {
            'zh': '背景容差值 (0-150)，值越大移除越多',
            'en': 'Higher = Remove more'
        },
        'conv_width': {
            'zh': '宽度 (mm)',
            'en': 'Width (mm)'
        },
        'conv_height': {
            'zh': '高度 (mm)',
            'en': 'Height (mm)'
        },
        'conv_thickness': {
            'zh': '背板 (mm)',
            'en': 'Backing (mm)'
        },
        'conv_backing_color': {
            'zh': '底板颜色',
            'en': 'Backing Color'
        },
        'conv_preview_btn': {
            'zh': '👁️ 生成预览',
            'en': '👁️ Generate Preview'
        },
        'conv_preview_section': {
            'zh': '#### 🎨 2D预览',
            'en': '#### 🎨 2D Preview'
        },
        'conv_palette': {
            'zh': '🎨 颜色调色板',
            'en': '🎨 Color Palette'
        },
        'conv_palette_step1': {
            'zh': '### 1. 原图颜色（点击预览图）',
            'en': '### 1. Original Color (Click Preview)'
        },
        'conv_palette_step2': {
            'zh': '### 2. 替换为（点击色块）',
            'en': '### 2. Replace With (Click Swatch)'
        },
        'conv_palette_selected_label': {
            'zh': '当前选中',
            'en': 'Selected'
        },
        'conv_palette_replace_label': {
            'zh': '将替换为',
            'en': 'Replace With'
        },
        'conv_palette_lut_loading': {
            'zh': '⏳ 正在加载 LUT 颜色...',
            'en': '⏳ Loading LUT colors...'
        },
        'conv_palette_replacements_placeholder': {
            'zh': '生成预览后显示替换列表',
            'en': 'Generate preview to see replacements'
        },
        'conv_palette_replacements_label': {
            'zh': '已生效的替换',
            'en': 'Applied Replacements'
        },
        'conv_palette_apply_btn': {
            'zh': '✅ 确认替换',
            'en': '✅ Apply'
        },
        'conv_palette_undo_btn': {
            'zh': '↩️ 撤销',
            'en': '↩️ Undo'
        },
        'conv_palette_clear_btn': {
            'zh': '🗑️ 清除所有',
            'en': '🗑️ Clear'
        },
        'conv_palette_user_replacements_title': {
            'zh': '用户替换',
            'en': 'User Replacements'
        },
        'conv_palette_auto_pairs_title': {
            'zh': '自动配准',
            'en': 'Auto Pairs'
        },
        'conv_palette_delete_selected_btn': {
            'zh': '删除选中',
            'en': 'Delete Selected'
        },
        'conv_palette_delete_selected_empty': {
            'zh': '❌ 请先选中一项用户替换',
            'en': '❌ Select one user replacement first'
        },
        'conv_palette_user_empty': {
            'zh': '暂无替换',
            'en': 'No replacements'
        },
        'conv_palette_auto_empty': {
            'zh': '暂无自动配准',
            'en': 'No auto pairs'
        },
        'lut_grid_invalid': {
            'zh': '⚠️ 请先选择一个有效的 LUT 文件',
            'en': '⚠️ Please select a valid LUT file'
        },
        'lut_grid_header': {
            'zh': '🎨 当前 LUT 包含 <b>{count}</b> 种可打印颜色（点击选择）',
            'en': '🎨 Current LUT contains <b>{count}</b> printable colors (click to select)'
        },
        'conv_loop_section': {
            'zh': '##### 🔗 挂孔设置',
            'en': '##### 🔗 Loop Settings'
        },
        'conv_loop_enable': {
            'zh': '启用挂孔',
            'en': 'Enable Loop'
        },
        'conv_loop_remove': {
            'zh': '🗑️ 移除挂孔',
            'en': '🗑️ Remove Loop'
        },
        'conv_loop_width': {
            'zh': '宽度(mm)',
            'en': 'Width(mm)'
        },
        'conv_loop_length': {
            'zh': '长度(mm)',
            'en': 'Length(mm)'
        },
        'conv_loop_hole': {
            'zh': '孔径(mm)',
            'en': 'Hole(mm)'
        },
        'conv_loop_angle': {
            'zh': '旋转角度°',
            'en': 'Rotation°'
        },
        'conv_loop_info': {
            'zh': '挂孔位置',
            'en': 'Loop Position'
        },
        'conv_outline_section': {
            'zh': '##### 外轮廓设置',
            'en': '##### Outline Settings'
        },
        'conv_outline_enable': {
            'zh': '启用外轮廓',
            'en': 'Enable Outline'
        },
        'conv_outline_width': {
            'zh': '轮廓宽度(mm)',
            'en': 'Outline Width(mm)'
        },
        'conv_cloisonne_section': {
            'zh': '##### 掐丝珐琅特效',
            'en': '##### Cloisonné Effect'
        },
        'conv_cloisonne_enable': {
            'zh': '启用掐丝珐琅',
            'en': 'Enable Cloisonné'
        },
        'conv_cloisonne_wire_width': {
            'zh': '丝线宽度(mm)',
            'en': 'Wire Width(mm)'
        },
        'conv_cloisonne_wire_height': {
            'zh': '丝线高度(mm)',
            'en': 'Wire Height(mm)'
        },
        'conv_cloisonne_wire_color': {
            'zh': '丝线颜色槽位',
            'en': 'Wire Color Slot'
        },
        'conv_free_color_btn': {
            'zh': '🎯 标记为自由色',
            'en': '🎯 Mark as Free Color'
        },
        'conv_free_color_clear_btn': {
            'zh': '清除自由色',
            'en': 'Clear Free Colors'
        },
        'conv_coating_section': {
            'zh': '##### 透明镀层',
            'en': '##### Transparent Coating'
        },
        'conv_coating_enable': {
            'zh': '启用透明镀层',
            'en': 'Enable Coating'
        },
        'conv_coating_height': {
            'zh': '镀层厚度(mm)',
            'en': 'Coating Height(mm)'
        },
        'conv_status': {
            'zh': '状态',
            'en': 'Status'
        },
        'conv_generate_btn': {
            'zh': '🚀 生成3MF',
            'en': '🚀 Generate 3MF'
        },
        'conv_3d_preview': {
            'zh': '#### 🎮 3D预览',
            'en': '#### 🎮 3D Preview'
        },
        'conv_download_section': {
            'zh': '#### 📁 下载【务必合并对象后再切片】',
            'en': '#### 📁 Download [Merge objects before slicing]'
        },
        'conv_download_file': {
            'zh': '3MF文件',
            'en': '3MF File'
        },
        
        # ==================== Calibration Tab ====================
        'cal_title': {
            'zh': '### 第二步：生成校准板',
            'en': '### Step 2: Generate Calibration Board'
        },
        'cal_desc': {
            'zh': '生成1024种颜色的校准板，打印后用于提取打印机的实际色彩数据。',
            'en': 'Generate a 1024-color calibration board to extract your printer\'s actual color data.'
        },
        'cal_params': {
            'zh': '#### ⚙️ 参数',
            'en': '#### ⚙️ Parameters'
        },
        'cal_color_mode': {
            'zh': '色彩模式',
            'en': 'Color Mode'
        },
        'cal_block_size': {
            'zh': '色块尺寸 (mm)',
            'en': 'Block Size (mm)'
        },
        'cal_gap': {
            'zh': '间隙 (mm)',
            'en': 'Gap (mm)'
        },
        'cal_backing': {
            'zh': '底板颜色',
            'en': 'Backing Color'
        },
        'cal_generate_btn': {
            'zh': '🚀 生成',
            'en': '🚀 Generate'
        },
        'cal_status': {
            'zh': '状态',
            'en': 'Status'
        },
        'cal_preview': {
            'zh': '#### 👁️ 预览',
            'en': '#### 👁️ Preview'
        },
        'cal_download': {
            'zh': '下载 3MF',
            'en': 'Download 3MF'
        },
        
        # ==================== Color Extractor Tab ====================
        'ext_title': {
            'zh': '### 第三步：提取颜色数据',
            'en': '### Step 3: Extract Color Data'
        },
        'ext_desc': {
            'zh': '拍摄打印好的校准板照片，提取真实的色彩数据生成 LUT 文件。',
            'en': 'Take a photo of your printed calibration board to extract real color data.'
        },
        'ext_upload_section': {
            'zh': '#### 📸 上传照片',
            'en': '#### 📸 Upload Photo'
        },
        'ext_color_mode': {
            'zh': '🎨 色彩模式',
            'en': '🎨 Color Mode'
        },
        'ext_photo': {
            'zh': '校准板照片',
            'en': 'Calibration Photo'
        },
        'ext_rotate_btn': {
            'zh': '↺ 旋转',
            'en': '↺ Rotate'
        },
        'ext_reset_btn': {
            'zh': '🗑️ 重置',
            'en': '🗑️ Reset'
        },
        'ext_correction_section': {
            'zh': '#### 🔧 校正参数',
            'en': '#### 🔧 Correction'
        },
        'ext_wb': {
            'zh': '自动白平衡',
            'en': 'Auto WB'
        },
        'ext_vignette': {
            'zh': '暗角校正',
            'en': 'Vignette'
        },
        'ext_zoom': {
            'zh': '缩放',
            'en': 'Zoom'
        },
        'ext_distortion': {
            'zh': '畸变',
            'en': 'Distortion'
        },
        'ext_offset_x': {
            'zh': 'X偏移',
            'en': 'Offset X'
        },
        'ext_offset_y': {
            'zh': 'Y偏移',
            'en': 'Offset Y'
        },
        'ext_extract_btn': {
            'zh': '🚀 提取',
            'en': '🚀 Extract'
        },
        'ext_status': {
            'zh': '状态',
            'en': 'Status'
        },
        'ext_hint_white': {
            'zh': '#### 👉 点击: **白色色块 (左上角)**',
            'en': '#### 👉 Click: **White Block (Top-Left)**'
        },
        'ext_marked': {
            'zh': '标记图',
            'en': 'Marked'
        },
        'ext_sampling': {
            'zh': '#### 📍 采样预览',
            'en': '#### 📍 Sampling'
        },
        'ext_reference': {
            'zh': '#### 🎯 参考',
            'en': '#### 🎯 Reference'
        },
        'ext_result': {
            'zh': '#### 📊 结果 (点击修正)',
            'en': '#### 📊 Result (Click to fix)'
        },
        'ext_manual_fix': {
            'zh': '#### 🛠️ 手动修正',
            'en': '#### 🛠️ Manual Fix'
        },
        'ext_click_cell': {
            'zh': '点击左侧色块查看...',
            'en': 'Click cell on left...'
        },
        'ext_override': {
            'zh': '替换颜色',
            'en': 'Override Color'
        },
        'ext_apply_btn': {
            'zh': '🔧 应用',
            'en': '🔧 Apply'
        },
        'ext_download_npy': {
            'zh': '下载 .npy',
            'en': 'Download .npy'
        },
        
        # ==================== Footer ====================
        'footer_tip': {
            'zh': '💡 提示: 使用高质量的PLA/PETG basic材料可获得最佳效果',
            'en': '💡 Tip: Use high-quality translucent PLA/PETG basic for best results'
        },
        
        # ==================== Status Messages ====================
        'msg_no_image': {
            'zh': '❌ 请上传图片',
            'en': '❌ Please upload an image'
        },
        'msg_no_lut': {
            'zh': '⚠️ 请选择或上传 .npy 校准文件！',
            'en': '⚠️ Please upload a .npy calibration file!'
        },
        'msg_preview_success': {
            'zh': '✅ 预览',
            'en': '✅ Preview'
        },
        'msg_click_to_place': {
            'zh': '点击图片放置挂孔',
            'en': 'Click to place loop'
        },
        'msg_conversion_complete': {
            'zh': '✅ 转换完成',
            'en': '✅ Conversion complete'
        },
        'msg_resolution': {
            'zh': '分辨率',
            'en': 'Resolution'
        },
        'msg_loop': {
            'zh': '挂孔',
            'en': 'Loop'
        },
        'msg_model_too_large': {
            'zh': '⚠️ 模型过大，已禁用3D预览',
            'en': '⚠️ Model too large, 3D preview disabled'
        },
        'msg_preview_simplified': {
            'zh': 'ℹ️ 3D预览已简化',
            'en': 'ℹ️ 3D preview simplified'
        },

        # ==================== Palette / Replacement ====================
        'palette_empty': {
            'zh': '暂无颜色，请先生成预览。',
            'en': 'No colors yet. Generate a preview first.'
        },
        'palette_count': {
            'zh': '共 {count} 种颜色',
            'en': '{count} colors in image'
        },
        'palette_hint': {
            'zh': '点击色块高亮预览',
            'en': 'Click swatch to highlight in preview'
        },
        'palette_tooltip': {
            'zh': '点击高亮: {hex} ({pct}%)',
            'en': 'Click to highlight: {hex} ({pct}%)'
        },
        'palette_replaced_with': {
            'zh': '替换为 {hex}',
            'en': 'Replaced with {hex}'
        },
        'palette_click_to_select': {
            'zh': '点击调色板选择颜色',
            'en': 'Click palette to select'
        },
        'palette_need_preview': {
            'zh': '❌ 请先生成预览',
            'en': '❌ Please generate preview first'
        },
        'palette_need_original': {
            'zh': '❌ 请先选择要替换的颜色',
            'en': '❌ Select a color to replace'
        },
        'palette_need_replacement': {
            'zh': '❌ 请先选择替换颜色',
            'en': '❌ Select a replacement color'
        },
        'palette_replaced': {
            'zh': '✅ 已替换 {src} → {dst}',
            'en': '✅ Replaced {src} → {dst}'
        },
        'palette_cleared': {
            'zh': '✅ 已清除所有颜色替换',
            'en': '✅ Cleared all replacements'
        },
        'palette_undo_empty': {
            'zh': '❌ 没有可撤销的操作',
            'en': '❌ Nothing to undo'
        },
        'palette_undone': {
            'zh': '↩️ 已撤销',
            'en': '↩️ Undone'
        },
        
        # ==================== Color Merging ====================
        'merge_enable_label': {
            'zh': '启用自动颜色合并 Enable Auto Color Merging',
            'en': 'Enable Auto Color Merging'
        },
        'merge_enable_info': {
            'zh': '自动合并低使用率颜色到相近颜色',
            'en': 'Automatically merge low-usage colors to similar colors'
        },
        'merge_threshold_label': {
            'zh': '使用率阈值 Usage Threshold (%)',
            'en': 'Usage Threshold (%)'
        },
        'merge_threshold_info': {
            'zh': '低于此百分比的颜色将被合并',
            'en': 'Colors below this percentage will be merged'
        },
        'merge_max_distance_label': {
            'zh': '最大颜色距离 Max Color Distance (Delta-E)',
            'en': 'Max Color Distance (Delta-E)'
        },
        'merge_max_distance_info': {
            'zh': '只合并距离小于此值的颜色',
            'en': 'Only merge colors with distance below this value'
        },
        'merge_preview_btn': {
            'zh': '🔍 预览合并效果 Preview Merge',
            'en': '🔍 Preview Merge'
        },
        'merge_apply_btn': {
            'zh': '✅ 应用合并 Apply Merge',
            'en': '✅ Apply Merge'
        },
        'merge_revert_btn': {
            'zh': '↩️ 恢复原始 Revert',
            'en': '↩️ Revert'
        },
        'merge_status_empty': {
            'zh': '💡 调整参数后点击预览',
            'en': '💡 Adjust parameters and click preview'
        },
        'merge_status_preview': {
            'zh': '🔍 预览: {merged} 种颜色被合并 (质量: {quality:.1f})',
            'en': '🔍 Preview: {merged} colors merged (quality: {quality:.1f})'
        },
        'merge_status_applied': {
            'zh': '✅ 已应用: {merged} 种颜色被合并',
            'en': '✅ Applied: {merged} colors merged'
        },
        'merge_status_reverted': {
            'zh': '↩️ 已恢复到原始颜色',
            'en': '↩️ Reverted to original colors'
        },
        'merge_error_empty_palette': {
            'zh': '❌ 调色板为空，无法执行颜色合并',
            'en': '❌ Empty palette, cannot perform color merging'
        },
        'merge_error_single_color': {
            'zh': '❌ 图像只包含一种颜色，已禁用颜色合并',
            'en': '❌ Image contains only one color, merging disabled'
        },
        'merge_error_all_below_threshold': {
            'zh': '⚠️ 所有颜色使用率都低于阈值，已禁用颜色合并以防止颜色丢失',
            'en': '⚠️ All colors below threshold, merging disabled to prevent color loss'
        },
        'merge_warning_no_targets': {
            'zh': '⚠️ 部分颜色未找到合适的合并目标，保持原始颜色',
            'en': '⚠️ Some colors have no suitable merge targets, keeping original'
        },
        'merge_info_low_usage': {
            'zh': '💡 检测到 {count} 种低使用率颜色 (<{threshold}%)',
            'en': '💡 Detected {count} low-usage colors (<{threshold}%)'
        },
        'merge_accordion_title': {
            'zh': '🎨 颜色合并 Color Merging',
            'en': '🎨 Color Merging'
        },
        
        'lut_grid_load_hint': {
            'zh': '加载 LUT 后显示可用颜色',
            'en': 'Load LUT to see available colors'
        },
        'lut_grid_count': {
            'zh': '共 {count} 种可用颜色',
            'en': '{count} available colors'
        },
        'lut_grid_search_placeholder': {
            'zh': '搜索色号 (如 ff0000)',
            'en': 'Search hex (e.g. ff0000)'
        },
        'lut_grid_search_clear': {
            'zh': '清除',
            'en': 'Clear'
        },
        'lut_grid_used': {
            'zh': '图中已使用 ({count})',
            'en': 'Used in image ({count})'
        },
        'lut_grid_other': {
            'zh': '其他可用颜色 ({count})',
            'en': 'Other colors ({count})'
        },
        'lut_grid_tooltip': {
            'zh': '点击选择: {hex}',
            'en': 'Click to select: {hex}'
        },
        'lut_grid_picker_label': {
            'zh': '🎯 以色找色',
            'en': '🎯 Find by Color'
        },
        'lut_grid_picker_hint': {
            'zh': '选一个颜色，自动匹配 LUT 中最接近的物理色',
            'en': 'Pick a color to find the closest match in LUT'
        },
        'lut_grid_picker_btn': {
            'zh': '匹配最近色',
            'en': 'Find Nearest'
        },
        'lut_grid_picker_result': {
            'zh': '✅ 最接近: {hex} (距离: {dist:.1f})',
            'en': '✅ Nearest: {hex} (distance: {dist:.1f})'
        },
        'lut_grid_hue_all': {
            'zh': '全部',
            'en': 'All'
        },
        'lut_grid_hue_red': {
            'zh': '红色系',
            'en': 'Red'
        },
        'lut_grid_hue_orange': {
            'zh': '橙色系',
            'en': 'Orange'
        },
        'lut_grid_hue_yellow': {
            'zh': '黄色系',
            'en': 'Yellow'
        },
        'lut_grid_hue_green': {
            'zh': '绿色系',
            'en': 'Green'
        },
        'lut_grid_hue_cyan': {
            'zh': '青色系',
            'en': 'Cyan'
        },
        'lut_grid_hue_blue': {
            'zh': '蓝色系',
            'en': 'Blue'
        },
        'lut_grid_hue_purple': {
            'zh': '紫色系',
            'en': 'Purple'
        },
        'lut_grid_hue_neutral': {
            'zh': '中性色',
            'en': 'Neutral'
        },
        'lut_grid_hue_fav': {
            'zh': '收藏',
            'en': 'Favorites'
        },
        'lut_grid_search_hex_placeholder': {
            'zh': '输入 Hex 或 RGB 搜索定位 (如 #FF0000 或 255,0,0)',
            'en': 'Search by Hex or RGB (e.g. #FF0000 or 255,0,0)'
        },

        # ==================== Settings ====================
        'settings_title': {
            'zh': '## ⚙️ 设置',
            'en': '## ⚙️ Settings'
        },
        'settings_clear_cache': {
            'zh': '🗑️ 清空缓存',
            'en': '🗑️ Clear Cache'
        },
        'settings_clear_output': {
            'zh': '🗑️ 清空输出',
            'en': '🗑️ Clear Output'
        },
        'settings_reset_counters': {
            'zh': '🔢 使用计数归零',
            'en': '🔢 Reset Counters'
        },
        'settings_cache_cleared': {
            'zh': '✅ 缓存已清空，释放了 {} 空间',
            'en': '✅ Cache cleared, freed {} of space'
        },
        'settings_output_cleared': {
            'zh': '✅ 输出已清空，释放了 {} 空间',
            'en': '✅ Output cleared, freed {} of space'
        },
        'settings_counters_reset': {
            'zh': '✅ 计数器已归零：校准板: {} | 颜色提取: {} | 模型转换: {}',
            'en': '✅ Counters reset: Calibrations: {} | Extractions: {} | Conversions: {}'
        },
        'settings_cache_size': {
            'zh': '📦 缓存大小: {}',
            'en': '📦 Cache size: {}'
        },
        'settings_output_size': {
            'zh': '📦 输出大小: {}',
            'en': '📦 Output size: {}'
        },

        'theme_toggle_night': {
            'zh': '🌙 夜间模式',
            'en': '🌙 Night Mode'
        },
        'theme_toggle_day': {
            'zh': '☀️ 日间模式',
            'en': '☀️ Day Mode'
        },
        
        # ==================== LUT Merge Tab ====================
        'tab_merge': {
            'zh': '🔀 色卡合并',
            'en': '🔀 LUT Merge'
        },
        'merge_title': {
            'zh': '### 🔀 色卡合并',
            'en': '### 🔀 LUT Merge'
        },
        'merge_desc': {
            'zh': '将不同色彩模式的LUT色卡合并为一个，获得更丰富的色彩。',
            'en': 'Merge LUT cards from different color modes into one for richer colors.'
        },
        'merge_lut_primary_label': {
            'zh': '🎯 主色卡（6色或8色）',
            'en': '🎯 Primary LUT (6-Color or 8-Color)'
        },
        'merge_lut_secondary_label': {
            'zh': '➕ 副色卡（可多选）',
            'en': '➕ Secondary LUTs (Multi-select)'
        },
        'merge_lut_1_label': {
            'zh': '选择LUT 1（主色卡）',
            'en': 'Select LUT 1 (Primary)'
        },
        'merge_lut_2_label': {
            'zh': '选择LUT 2（合并色卡）',
            'en': 'Select LUT 2 (Secondary)'
        },
        'merge_secondary_modes': {
            'zh': '已选副色卡',
            'en': 'Selected Secondary LUTs'
        },
        'merge_secondary_none': {
            'zh': '未选择副色卡',
            'en': 'No secondary LUTs selected'
        },
        'merge_primary_hint': {
            'zh': '💡 请先选择一个6色或8色的主色卡',
            'en': '💡 Please select a 6-Color or 8-Color primary LUT first'
        },
        'merge_primary_not_high': {
            'zh': '❌ 主色卡必须是6色或8色模式',
            'en': '❌ Primary LUT must be 6-Color or 8-Color mode'
        },
        'merge_error_no_secondary': {
            'zh': '❌ 请至少选择一个副色卡',
            'en': '❌ Please select at least one secondary LUT'
        },
        'merge_mode_label': {
            'zh': '检测到的模式',
            'en': 'Detected Mode'
        },
        'merge_mode_unknown': {
            'zh': '未选择',
            'en': 'Not selected'
        },
        'merge_dedup_label': {
            'zh': 'Delta-E 去重阈值',
            'en': 'Delta-E Dedup Threshold'
        },
        'merge_dedup_info': {
            'zh': '值越大去除的相近色越多，0=仅精确去重',
            'en': 'Higher = remove more similar colors, 0 = exact dedup only'
        },
        'merge_btn': {
            'zh': '🔀 执行合并',
            'en': '🔀 Merge'
        },
        'merge_status_ready': {
            'zh': '💡 选择两个LUT后点击合并',
            'en': '💡 Select two LUTs then click Merge'
        },
        'merge_status_running': {
            'zh': '⏳ 合并中...',
            'en': '⏳ Merging...'
        },
        'merge_status_success': {
            'zh': '✅ 合并完成！合并前: {before} 色 → 合并后: {after} 色（精确去重: {exact}，相近色去除: {similar}）\n保存至: {path}',
            'en': '✅ Merge complete! Before: {before} → After: {after} (exact dupes: {exact}, similar removed: {similar})\nSaved to: {path}'
        },
        'merge_error_no_lut': {
            'zh': '❌ 请选择至少两个LUT文件',
            'en': '❌ Please select at least two LUT files'
        },
        'merge_error_same_lut': {
            'zh': '❌ 请选择不同的LUT文件',
            'en': '❌ Please select different LUT files'
        },
        'merge_error_incompatible': {
            'zh': '❌ 不兼容的LUT组合: {msg}',
            'en': '❌ Incompatible LUT combination: {msg}'
        },
        'merge_error_failed': {
            'zh': '❌ 合并失败: {msg}',
            'en': '❌ Merge failed: {msg}'
        },
        
        # ==================== About Page Content ====================
        'about_content': {
            'zh': """## 🌟 Lumina Studio v1.6.0

**多材料3D打印色彩系统**

让FDM打印也能拥有精准的色彩还原

---

### 📖 使用流程

1. **生成校准板** → 打印1024色校准网格
2. **提取颜色** → 拍照并提取打印机实际色彩
3. **转换图像** → 将图片转为多层3D模型

---

### 🎨 色彩模式定位点顺序

| 模式 | 左上 | 右上 | 右下 | 左下 |
|------|------|------|------|------|
| **RYBW** | ⬜ 白色 | 🟥 红色 | 🟦 蓝色 | 🟨 黄色 |
| **CMYW** | ⬜ 白色 | 🔵 青色 | 🟣 品红 | 🟨 黄色 |

---

### 🔬 技术原理

- **Beer-Lambert 光学混色**
- **KD-Tree 色彩匹配**
- **RLE 几何生成**
- **K-Means 色彩量化**

---

### 📝 v1.6.0 更新日志

#### 🧹 孤立像素清理
- 新增孤立像素清理功能（高保真模式自动启用）
- 智能检测并合并孤立色块，提升打印质量

#### 🔧 代码质量改进
- 替换所有裸异常捕获为 `except Exception`
- 新增 Aliz PLA & PETG 4/6/8色 npy 预设

---

### 📝 v1.5.8 更新日志

#### 🧹 代码清理
- 移除融合LUT功能（简化用户体验）
- 保留BW黑白模式功能
- 清理.npz文件格式支持

---

### 📝 v1.5.7 更新日志

#### 🔧 8色模式叠色效果修复
- **核心修复**：修复8色模式图像转换时堆叠顺序错误导致的叠色效果不正确
- **数据一致性**：确保8色模式ref_stacks格式与4色、6色保持一致 [顶...底]
- **观赏面修复**：修复观赏面(Z=0)和背面颠倒的问题

#### 🎨 完整8色图像转换支持
- **UI增强**：图像转换TAB新增8色模式支持
- **自动检测**：8色LUT自动检测(2600-2800色范围)
- **完整工作流**：校准板生成 → 颜色提取 → 图像转换

#### 🐳 Docker支持
- **容器化部署**：添加Dockerfile支持
- **简化安装**：无需手动配置系统依赖
- **跨平台**：统一的部署体验

---

### 📝 v1.5.5 更新日志 (历史)

#### 🎨 8色校准版算法优化
- **算法升级**：8色校准版采用与6色一致的智能筛选算法
- **黑色优化**：Black TD从0.2mm调整至0.6mm，实现自然筛选
- **质量提升**：移除强制黑色约束，改用RGB距离>8的贪心算法
- **数据修复**：修正材料ID映射，确保与config.py完全一致
- **统计修正**：修复黑色统计代码，使用正确的材料ID

---

### 📝 v1.5.4 更新日志 (历史)

#### 🐛 矢量模式改进
- 改进矢量模式的布尔运算逻辑
- 优化SVG颜色顺序处理
- 添加微Z偏移以保持细节独立性
- 增强小特征保护机制

---

### 📝 v1.5.0 更新日志

#### 🎨 代码标准化
- **注释统一为英文**：所有代码注释翻译为英文，提升国际化协作能力
- **文档规范化**：统一使用 Google-style docstrings
- **代码清理**：移除冗余注释，保留关键算法说明

---

### 📝 v1.4.1 更新日志

#### 🚀 建模模式整合
- **高保真模式取代矢量和版画模式**：统一为两种模式（高保真/像素艺术）
- **语言切换功能**：点击右上角按钮即可切换中英文界面

#### 📝 v1.4 更新日志

#### 🚀 核心功能

- ✅ **高保真模式** - RLE算法，无缝拼接，水密模型（10 px/mm）
- ✅ **像素艺术模式** - 经典方块美学，像素艺术风格

#### 🔧 架构重构

- 合并Vector和Woodblock为统一的High-Fidelity模式
- RLE（Run-Length Encoding）几何生成引擎
- 零间隙、完美边缘对齐（shrink=0.0）
- 性能优化：支持100k+面片即时生成

#### 🎨 色彩量化架构

- K-Means聚类（8-256色可调，默认64色）
- "先聚类，后匹配"（速度提升1000×）
- 双边滤波 + 中值滤波（消除碎片化区域）

---

### 🚧 开发路线图

- [✅] 4色基础模式
- [✅] 两种建模模式（高保真/像素艺术）
- [✅] RLE几何引擎
- [✅] 钥匙扣挂孔
- [🚧] 漫画模式（Ben-Day dots模拟）
- [ ] 6色扩展模式
- [ ] 8色专业模式

---

### 📄 许可证

**GNU GPL v3.0** 开源协议

GPL 协议允许并鼓励商业使用。我们特别支持大家通过劳动获取收益，你无需获得额外授权即可：

使用本软件生成模型或辅助生产；

销售物理打印成品（如挂件、浮雕、3D 打印件等）；

在夜市、市集、展会或个人网店销售。

---

### 🙏 致谢

特别感谢：
- **HueForge** - 在FDM打印中开创光学混色技术
- **AutoForge** - 让多色工作流民主化
- **3D打印社区** - 持续创新

---

<div style="text-align:center; color:#888; margin-top:20px;">
    Made with ❤️ by Lumina Studio Contributors<br>
    v1.6.0 | 2025
</div>
""",
            'en': """## 🌟 Lumina Studio v1.6.0

**Multi-Material 3D Print Color System**

Accurate color reproduction for FDM printing

---

### 📖 Workflow

1. **Generate Calibration** → Print 1024-color grid
2. **Extract Colors** → Photo → extract real colors
3. **Convert Image** → Image → multi-layer 3D model

---

### 🎨 Color Mode Corner Order

| Mode | Top-Left | Top-Right | Bottom-Right | Bottom-Left |
|------|----------|-----------|--------------|-------------|
| **RYBW** | ⬜ White | 🟥 Red | 🟦 Blue | 🟨 Yellow |
| **CMYW** | ⬜ White | 🔵 Cyan | 🟣 Magenta | 🟨 Yellow |

---

### 🔬 Technology

- **Beer-Lambert Optical Color Mixing**
- **KD-Tree Color Matching**
- **RLE Geometry Generation**
- **K-Means Color Quantization**

---

### 📝 v1.6.0 Changelog

#### 🧹 Isolated Pixel Cleanup
- Added isolated pixel cleanup feature (auto-enabled in High-Fidelity mode)
- Smart detection and merging of isolated color blocks for better print quality

#### 🔧 Code Quality Improvements
- Replaced all bare except clauses with `except Exception`
- Added Aliz PLA & PETG 4/6/8 color npy presets

---

### 📝 v1.5.8 Changelog

#### 🧹 Code Cleanup
- Removed merged LUT feature (simplified UX)
- Kept BW black & white mode
- Cleaned up .npz format support

---

### 📝 v1.5.7 Changelog

#### 🔧 8-Color Mode Stacking Fix
- **Core Fix**: Fixed incorrect stacking order in 8-color image conversion causing wrong color layering
- **Data Consistency**: Ensured 8-color ref_stacks format matches 4-color and 6-color [Top...Bottom]
- **Viewing Surface Fix**: Fixed reversed viewing surface (Z=0) and back surface

#### 🎨 Complete 8-Color Image Conversion Support
- **UI Enhancement**: Added 8-color mode to Image Converter tab
- **Auto Detection**: 8-color LUT auto-detection (2600-2800 color range)
- **Complete Workflow**: Calibration → Color Extraction → Image Conversion

#### 🐳 Docker Support
- **Containerization**: Added Dockerfile support
- **Simplified Installation**: No manual system dependency configuration needed
- **Cross-Platform**: Unified deployment experience

---

### 📝 v1.5.5 Changelog (History)

#### 🎨 8-Color Calibration Algorithm Optimization
- **Algorithm Upgrade**: 8-color calibration now uses the same intelligent selection algorithm as 6-color
- **Black Optimization**: Black TD adjusted from 0.2mm to 0.6mm for natural selection
- **Quality Improvement**: Removed forced black constraints, using RGB distance > 8 greedy algorithm
- **Data Fix**: Corrected material ID mapping to match config.py
- **Statistics Fix**: Fixed black color statistics to use correct material ID

---

### 📝 v1.5.4 Changelog (History)

#### 🐛 Vector Mode Improvements
- Improved Boolean operation logic in vector mode
- Optimized SVG color order processing
- Added micro Z-offset to maintain detail independence
- Enhanced small feature protection mechanism

---

### 📝 v1.5.0 Changelog

#### 🎨 Code Standardization
- **English-only Comments**: All code comments translated to English for better international collaboration
- **Documentation Standards**: Unified Google-style docstrings across codebase
- **Code Cleanup**: Removed redundant comments, kept essential algorithm explanations

---

### 📝 v1.4.1 Changelog

#### 🚀 Modeling Mode Consolidation
- **High-Fidelity Mode Replaces Vector & Woodblock**: Unified into two modes (High-Fidelity/Pixel Art)
- **Language Switching**: Click the button in the top-right corner to switch between Chinese and English

#### 📝 v1.4 Changelog

#### 🚀 Core Features

- ✅ **High-Fidelity Mode** - RLE algorithm, seamless, watertight (10 px/mm)
- ✅ **Pixel Art Mode** - Classic blocky aesthetic

#### 🔧 Architecture Refactor

- Merged Vector and Woodblock into unified High-Fidelity mode
- RLE (Run-Length Encoding) geometry engine
- Zero gaps, perfect edge alignment (shrink=0.0)
- Performance: 100k+ faces instant generation

#### 🎨 Color Quantization

- K-Means clustering (8-256 colors, default 64)
- "Cluster First, Match Second" (1000× speedup)
- Bilateral + Median filtering (eliminate fragmentation)

---

### 🚧 Roadmap

- [✅] 4-color base mode
- [✅] Two modeling modes (High-Fidelity/Pixel Art)
- [✅] RLE geometry engine
- [✅] Keychain loop
- [🚧] Manga mode (Ben-Day dots simulation)
- [ ] 6-color extended mode
- [ ] 8-color professional mode

---

### 📄 License

**GNU GPL v3.0** Open Source License

**Commercial Use & "Street Vendor" Support Statement**: GPL permits and encourages commercial use. We specifically support individual creators, street vendors, and small businesses to earn a living through their craft. You may freely use this software to generate models and sell physical prints without additional permission.

---

### 🙏 Acknowledgments

Special thanks to:
- **HueForge** - Pioneering optical color mixing in FDM
- **AutoForge** - Democratizing multi-color workflows
- **3D printing community** - Continuous innovation

---

<div style="text-align:center; color:#888; margin-top:20px;">
    Made with ❤️ by Lumina Studio Contributors<br>
    v1.6.0 | 2025
</div>
"""
        },
    }
    
    @staticmethod
    def get(key: str, lang: str = 'zh') -> str:
        """
        Get text in specified language
        
        Args:
            key: Text key name
            lang: Language code ('zh' or 'en')
        
        Returns:
            str: Translated text, returns key itself if key doesn't exist
        """
        if key in I18n.TEXTS:
            return I18n.TEXTS[key].get(lang, I18n.TEXTS[key].get('zh', key))
        return key
    
    @staticmethod
    def get_all(lang: str = 'zh') -> dict:
        """
        Get all texts in specified language version
        
        Args:
            lang: Language code ('zh' or 'en')
        
        Returns:
            dict: {key: translated_text}
        """
        return {key: I18n.get(key, lang) for key in I18n.TEXTS.keys()}
