"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                    K/S ENGINE - GRADIO UI COMPONENTS                          ║
║                      K/S 引擎 Gradio UI 组件                                   ║
╚═══════════════════════════════════════════════════════════════════════════════╝

This module provides Gradio UI components for the K/S workflow:
1. Step card generation
2. K/S parameter calculation
3. Dynamic image conversion
4. Filament database management
"""

import gradio as gr
import json
import os
from typing import Dict, List, Tuple


# ========== Helper Functions ==========

def get_a4_hint(pts_count):
    """Get A4 corner point hint"""
    labels = ["左上角 / Top-Left", "右上角 / Top-Right", "右下角 / Bottom-Right", "左下角 / Bottom-Left"]
    if pts_count >= 4:
        return "#### ✅ A4纸/背景板角点选择完成！请在下方选择阶梯卡角点"
    return f"#### 👉 点击 Click: **{labels[pts_count]}**"


def get_chip_hint(pts_count):
    """Get chip corner point hint"""
    labels = ["左上角 / Top-Left", "右上角 / Top-Right", "右下角 / Bottom-Right", "左下角 / Bottom-Left"]
    if pts_count >= 4:
        return "#### ✅ 阶梯卡角点选择完成！可以开始计算"
    return f"#### 👉 点击 Click: **{labels[pts_count]}**"


def draw_ks_corner_points(img_path, pts, mode='a4'):
    """Draw corner points on image"""
    import cv2
    import numpy as np
    
    img = cv2.imread(img_path)
    if img is None:
        return img_path
    
    colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]  # 蓝、绿、红、黄
    labels = ["1", "2", "3", "4"]
    
    for i, (x, y) in enumerate(pts):
        color = colors[i % 4]
        # 绘制十字准星
        marker_size = 30 if mode == 'a4' else 20
        cv2.drawMarker(img, (x, y), color, cv2.MARKER_CROSS, marker_size, 3)
        # 绘制圆圈
        circle_size = 15 if mode == 'a4' else 10
        cv2.circle(img, (x, y), circle_size, color, 3)
        # 绘制标签
        font_scale = 1.2 if mode == 'a4' else 0.8
        cv2.putText(
            img, labels[i], 
            (x + 20, y - 10), 
            cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, 3
        )
    
    # 如果选够4个点，绘制连线
    if len(pts) == 4:
        pts_array = np.array(pts, dtype=np.int32)
        cv2.polylines(img, [pts_array], True, (0, 255, 255), 3)
    
    # 保存标注图片
    temp_dir = "output/ks_engine/debug"
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"{mode}_annotated.jpg")
    cv2.imwrite(temp_path, img)
    
    return temp_path


# ========== Tab Creation Functions ==========

def create_ks_calibration_tab() -> Dict:
    """
    创建 K/S 阶梯色卡生成 Tab
    
    对应 ChromaStack 的 generate_cali_stl.py 功能
    
    Returns:
        组件字典
    """
    components = {}
    
    gr.Markdown(
        """
        ## 📏 K/S Step Card Generator
        ### 阶梯色卡生成器
        
        生成用于 K/S 参数校准的阶梯测试卡。
        
        **使用流程：**
        1. 设置打印参数（层高、阶梯数量）
        2. 点击生成按钮
        3. 下载 3 个 STL 文件（黑底、白底、测试色）
        4. 在切片软件中合并为单一对象
        5. 打印并拍照用于下一步校准
        
        💡 **推荐：** 搭配校色背景板使用效果更佳，MakerWorld 搜索 **2192593** 即可下载打印。
        """
    )
    
    with gr.Row():
        with gr.Column():
            components['layer_height'] = gr.Slider(
                minimum=0.04,
                maximum=0.20,
                value=0.08,
                step=0.01,
                label="Layer Height | 层高 (mm)",
                info="Must match your actual print settings"
            )
            
            components['num_steps'] = gr.Slider(
                minimum=3,
                maximum=10,
                value=5,
                step=1,
                label="Number of Steps | 阶梯数量",
                info="Test 1 to N layers"
            )
            
            components['base_thickness'] = gr.Slider(
                minimum=0.4,
                maximum=1.2,
                value=0.6,
                step=0.1,
                label="Base Thickness | 底座厚度 (mm)",
                info="Black/White backing thickness"
            )
            
            components['generate_btn'] = gr.Button(
                "🎯 Generate Step Card | 生成阶梯卡",
                variant="primary"
            )
        
        with gr.Column():
            components['preview_3d'] = gr.Model3D(
                label="3D Preview | 3D 预览",
                height=400
            )
            
            components['download_files'] = gr.File(
                label="📦 Download STL Files | 下载 STL 文件",
                file_count="multiple"
            )
    
    components['status'] = gr.Textbox(
        label="Status | 状态",
        interactive=False
    )
    
    # 绑定事件
    components['generate_btn'].click(
        fn=generate_step_card_handler,
        inputs=[
            components['layer_height'],
            components['num_steps'],
            components['base_thickness']
        ],
        outputs=[
            components['preview_3d'],
            components['download_files'],
            components['status']
        ]
    )
    
    return components


def create_ks_calculator_tab() -> Dict:
    """
    创建 K/S 拍照测算仪 Tab - 使用点击选点交互
    
    Returns:
        组件字典
    """
    components = {}
    
    gr.Markdown(
        """
        ## 📸 K/S Parameter Calculator
        ### K/S 参数测算器
        
        通过拍照分析打印好的阶梯卡，自动计算耗材的 K/S 参数。
        
        💡 **推荐：** 将阶梯卡放在校色背景板上拍照，校色更准确。MakerWorld 搜索 **2192593** 即可下载打印。
        """
    )
    
    # 状态存储
    components['a4_coords_state'] = gr.State([])
    components['chip_coords_state'] = gr.State([])
    
    # Step 1: Select A4 corners
    gr.Markdown("### 📄 Step 1: Select Board Corners | 步骤 1: 选择 <span title='推荐使用白色校色背景板（MakerWorld 搜索 2192593），比 A4 纸更白更均匀，校色更准确' style='border-bottom:1px dashed #888;cursor:help;'>A4纸/校色背景板</span> 角点")
    
    with gr.Row():
        components['a4_hint'] = gr.Markdown(
            "#### 👉 点击 Click: **左上角 / Top-Left**"
        )
    
    with gr.Row():
        with gr.Column():
            components['calibration_image'] = gr.Image(
                label="📷 Upload & Click Corners | 上传照片并点击角点",
                type="filepath",
                height=500
            )
        
        with gr.Column():
            components['a4_coords_display'] = gr.JSON(
                label="Board Corners | 背景板角点坐标",
                value=[]
            )
            
            with gr.Row():
                components['clear_a4_btn'] = gr.Button(
                    "🔄 Clear | 清除角点",
                    variant="secondary",
                    size="sm"
                )
    
    # Step 2: Select chip corners
    gr.Markdown("---")
    gr.Markdown("### 📐 Step 2: Select Step Card Corners | 步骤 2: 选择阶梯卡角点")
    gr.Markdown(
        """
        ⚠️ **重要提示：**
        - 确保上方是厚端 (5层)
        - 确保下方是薄端 (1层)
        - 黑底在左，白底在右
        """
    )
    
    with gr.Row():
        components['chip_hint'] = gr.Markdown(
            "#### 请先完成 A4纸/背景板角点选择"
        )
    
    with gr.Row():
        with gr.Column():
            components['chip_image'] = gr.Image(
                label="📐 Click Step Card Corners | 点击阶梯卡角点",
                type="filepath",
                height=500
            )
        
        with gr.Column():
            components['chip_coords_display'] = gr.JSON(
                label="Chip Corners | 阶梯卡角点坐标",
                value=[]
            )
            
            with gr.Row():
                components['clear_chip_btn'] = gr.Button(
                    "🔄 Clear Chip | 清除阶梯卡角点",
                    variant="secondary",
                    size="sm"
                )
    
    # Step 3: Calculate
    gr.Markdown("---")
    gr.Markdown("### 🔬 Step 3: Calculate K/S Parameters | 步骤 3: 计算 K/S 参数")
    
    with gr.Row():
        with gr.Column():
            components['layer_height_calc'] = gr.Number(
                value=0.08,
                label="Layer Height | 层高 (mm)",
                info="Must match the printed card"
            )
            
            components['num_steps_calc'] = gr.Slider(
                minimum=3,
                maximum=10,
                value=5,
                step=1,
                label="Number of Steps | 阶梯数量"
            )
        
        with gr.Column():
            components['calculate_btn'] = gr.Button(
                "🔬 Calculate K/S Parameters | 计算 K/S 参数",
                variant="primary",
                size="lg"
            )
    
    # Results display
    with gr.Row():
        with gr.Column():
            components['fitting_plot'] = gr.Image(
                label="📊 Fitting Result | 拟合结果",
                height=400
            )
        
        with gr.Column():
            components['detection_image'] = gr.Image(
                label="🔍 Detection Result | 检测结果",
                height=400
            )
    
    components['ks_results'] = gr.JSON(
        label="📋 K/S Parameters | K/S 参数"
    )
    
    components['calc_status'] = gr.Textbox(
        label="Status | 状态",
        interactive=False,
        lines=10
    )
    
    # Save to database section
    gr.Markdown("---")
    gr.Markdown("### 💾 Save to Filament Database | 保存到耗材数据库")
    
    with gr.Row():
        components['filament_name'] = gr.Textbox(
            label="Filament Name | 耗材名称",
            placeholder="e.g., Bambu Lab PLA Cyan"
        )
        
        components['filament_color'] = gr.ColorPicker(
            label="Display Color | 显示颜色",
            value="#00FFFF"
        )
        
        components['save_to_db_btn'] = gr.Button(
            "💾 Save to Database | 保存到数据库",
            variant="secondary"
        )
    
    # ========== Event Bindings ==========
    
    # When image is uploaded
    components['calibration_image'].upload(
        fn=on_ks_upload,
        inputs=[components['calibration_image']],
        outputs=[
            components['calibration_image'],
            components['calibration_image'],
            components['a4_coords_state'],
            components['chip_image'],
            components['a4_hint']
        ]
    )
    
    # When A4 image is clicked
    components['calibration_image'].select(
        fn=on_a4_click,
        inputs=[
            components['calibration_image'],
            components['a4_coords_state']
        ],
        outputs=[
            components['calibration_image'],
            components['a4_coords_state'],
            components['a4_hint'],
            components['a4_coords_display'],
            components['chip_image'],
            components['chip_hint']
        ]
    )
    
    # Clear A4 corners
    components['clear_a4_btn'].click(
        fn=on_a4_clear,
        inputs=[components['calibration_image']],
        outputs=[
            components['calibration_image'],
            components['a4_coords_state'],
            components['a4_hint'],
            components['a4_coords_display'],
            components['chip_image'],
            components['chip_coords_state'],
            components['chip_hint'],
            components['chip_coords_display']
        ]
    )
    
    # When chip image is clicked
    components['chip_image'].select(
        fn=on_chip_click,
        inputs=[
            components['chip_image'],
            components['chip_coords_state']
        ],
        outputs=[
            components['chip_image'],
            components['chip_coords_state'],
            components['chip_hint'],
            components['chip_coords_display']
        ]
    )
    
    # Clear chip corners
    components['clear_chip_btn'].click(
        fn=on_chip_clear,
        inputs=[
            components['calibration_image'],
            components['a4_coords_state']
        ],
        outputs=[
            components['chip_image'],
            components['chip_coords_state'],
            components['chip_hint'],
            components['chip_coords_display']
        ]
    )
    
    # Calculate K/S parameters
    components['calculate_btn'].click(
        fn=calculate_ks_handler,
        inputs=[
            components['calibration_image'],
            components['a4_coords_state'],
            components['chip_coords_state'],
            components['layer_height_calc'],
            components['num_steps_calc']
        ],
        outputs=[
            components['fitting_plot'],
            components['detection_image'],
            components['ks_results'],
            components['calc_status']
        ]
    )
    
    # Save to database
    components['save_to_db_btn'].click(
        fn=save_filament_to_db_handler,
        inputs=[
            components['filament_name'],
            components['filament_color'],
            components['ks_results']
        ],
        outputs=[components['calc_status']]
    )
    
    return components



def create_ks_converter_tab() -> Dict:
    """
    创建动态转换器 Tab
    
    对应 ChromaStack 的 ChromaStackStudio.py 主程序功能
    
    Returns:
        组件字典
    """
    components = {}
    
    gr.Markdown(
        """
        ## 🎨 Dynamic K/S Converter
        ### 动态 K/S 转换器
        
        使用 K-M 物理模型实时计算最佳颜色匹配。
        
        **特点：**
        - 🔬 基于物理光学模型
        - 🎯 更高的颜色准确度
        - 🔄 支持任意耗材组合
        - 📊 实时动态计算色域
        """
    )
    
    with gr.Row():
        with gr.Column():
            components['input_image'] = gr.Image(
                label="📤 Upload Image | 上传图片",
                type="filepath",
                height=300
            )
            
            components['target_width'] = gr.Slider(
                minimum=30,
                maximum=200,
                value=80,
                step=5,
                label="Target Width | 目标宽度 (mm)"
            )
            
            components['max_filaments'] = gr.Slider(
                minimum=2,
                maximum=8,
                value=4,
                step=1,
                label="Max Filaments | 最大耗材数",
                info="Number of filament slots to use"
            )
            
            components['auto_select'] = gr.Checkbox(
                label="🤖 Auto Select Filaments | 自动选择耗材",
                value=True,
                info="Automatically choose best filament combination"
            )
            
            components['selected_filaments'] = gr.Dropdown(
                label="Selected Filaments | 选择的耗材",
                choices=[],
                multiselect=True,
                interactive=True
            )
            
            components['convert_btn'] = gr.Button(
                "🚀 Convert to 3D | 转换为 3D",
                variant="primary"
            )
        
        with gr.Column():
            components['preview_image'] = gr.Image(
                label="🖼️ Color Preview | 颜色预览",
                height=300
            )
            
            components['gamut_plot'] = gr.Image(
                label="📊 Color Gamut | 色域分析",
                height=300
            )
    
    components['output_3mf'] = gr.File(
        label="📦 Download 3MF | 下载 3MF"
    )
    
    components['conv_status'] = gr.Textbox(
        label="Status | 状态",
        interactive=False
    )
    
    # 绑定事件
    components['convert_btn'].click(
        fn=convert_image_ks_handler,
        inputs=[
            components['input_image'],
            components['target_width'],
            components['max_filaments'],
            components['auto_select'],
            components['selected_filaments']
        ],
        outputs=[
            components['preview_image'],
            components['gamut_plot'],
            components['output_3mf'],
            components['conv_status']
        ]
    )
    
    return components


def create_ks_filament_db_tab() -> Dict:
    """
    创建耗材数据库管理 Tab
    
    Returns:
        组件字典
    """
    components = {}
    
    gr.Markdown(
        """
        ## 💾 Filament Database
        ### 耗材数据库
        
        管理所有已校准的耗材 K/S 参数。
        """
    )
    
    components['filament_table'] = gr.Dataframe(
        headers=["Name", "K (R,G,B)", "S (R,G,B)", "Color"],
        datatype=["str", "str", "str", "str"],
        label="📋 Filament Library | 耗材库",
        interactive=True
    )
    
    with gr.Row():
        components['refresh_btn'] = gr.Button("🔄 Refresh | 刷新")
        components['export_btn'] = gr.Button("📤 Export JSON | 导出 JSON")
        components['import_btn'] = gr.Button("📥 Import JSON | 导入 JSON")
    
    components['db_file'] = gr.File(
        label="JSON File | JSON 文件",
        file_types=[".json"]
    )
    
    # 绑定事件
    components['refresh_btn'].click(
        fn=load_filament_db_handler,
        outputs=[components['filament_table']]
    )
    
    return components


# ========== Event Handler Functions ==========

def on_ks_upload(img):
    """Handle K/S calibration image upload"""
    hint = get_a4_hint(0)
    return img, img, [], None, hint


def on_a4_click(img, pts, evt: gr.SelectData):
    """Handle A4 corner point click"""
    import cv2
    import numpy as np
    
    if len(pts) >= 4:
        return img, pts, get_a4_hint(4), pts, None, "A4纸/背景板角点已选完"
    
    new_pts = pts + [[evt.index[0], evt.index[1]]]
    vis = draw_ks_corner_points(img, new_pts, 'a4')
    hint = get_a4_hint(len(new_pts))
    
    # 如果选够4个点，生成校正后的图像
    chip_image = None
    chip_hint = "请先完成 A4纸/背景板角点选择"
    
    if len(new_pts) == 4:
        try:
            from core.ks_engine.calibration_ks import apply_perspective_transform, auto_white_balance_by_paper
            
            img_raw = cv2.imread(img)
            pts_a4 = np.float32(new_pts)
            img_a4 = apply_perspective_transform(img_raw, pts_a4, 1414, 1000)
            img_calibrated = auto_white_balance_by_paper(img_a4)
            
            chip_preview_path = "output/ks_engine/debug/chip_preview.jpg"
            os.makedirs(os.path.dirname(chip_preview_path), exist_ok=True)
            cv2.imwrite(chip_preview_path, img_calibrated)
            chip_image = chip_preview_path
            chip_hint = get_chip_hint(0)
        except Exception as e:
            print(f"Error generating chip preview: {e}")
    
    return vis, new_pts, hint, new_pts, chip_image, chip_hint


def on_a4_clear(img):
    """Clear A4 corner points"""
    hint = get_a4_hint(0)
    return img, [], hint, [], None, [], "请先完成 A4纸/背景板角点选择", []


def on_chip_click(img, pts, evt: gr.SelectData):
    """Handle chip corner point click"""
    if len(pts) >= 4:
        return img, pts, get_chip_hint(4), pts
    
    new_pts = pts + [[evt.index[0], evt.index[1]]]
    vis = draw_ks_corner_points(img, new_pts, 'chip')
    hint = get_chip_hint(len(new_pts))
    
    return vis, new_pts, hint, new_pts


def on_chip_clear(img, a4_pts):
    """Clear chip corner points"""
    import cv2
    import numpy as np
    
    if not img or len(a4_pts) != 4:
        return None, [], "请先完成 A4纸/背景板角点选择", []
    
    try:
        from core.ks_engine.calibration_ks import apply_perspective_transform, auto_white_balance_by_paper
        
        img_raw = cv2.imread(img)
        pts_a4 = np.float32(a4_pts)
        img_a4 = apply_perspective_transform(img_raw, pts_a4, 1414, 1000)
        img_calibrated = auto_white_balance_by_paper(img_a4)
        
        chip_preview_path = "output/ks_engine/debug/chip_preview.jpg"
        os.makedirs(os.path.dirname(chip_preview_path), exist_ok=True)
        cv2.imwrite(chip_preview_path, img_calibrated)
        
        hint = get_chip_hint(0)
        return chip_preview_path, [], hint, []
    except Exception as e:
        print(f"Error resetting chip: {e}")
        return None, [], "请先完成 A4纸/背景板角点选择", []


def generate_step_card_handler(
    layer_height: float,
    num_steps: int,
    base_thickness: float
) -> tuple:
    """
    生成阶梯卡事件处理函数
    
    Args:
        layer_height: 层高 (mm)
        num_steps: 阶梯数量
        base_thickness: 底座厚度 (mm)
    
    Returns:
        (preview_3d, download_files, status_message)
    """
    try:
        from core.ks_engine.calibration import generate_step_card
        
        # 生成阶梯卡
        file_paths, status_message = generate_step_card(
            layer_height=layer_height,
            num_steps=int(num_steps),
            base_thickness=base_thickness,
            output_dir="output/ks_engine/calibration"
        )
        
        # 返回第一个文件作为 3D 预览 (黑色底座)
        preview_file = file_paths[0] if file_paths else None
        
        return preview_file, file_paths, status_message
        
    except Exception as e:
        import traceback
        error_msg = f"❌ 生成失败: {str(e)}\n\n"
        error_msg += traceback.format_exc()
        return None, [], error_msg


def calculate_ks_handler(
    original_image: str,
    a4_coords: List,
    chip_coords: List,
    layer_height: float,
    num_steps: int
) -> tuple:
    """
    计算 K/S 参数事件处理函数
    
    Args:
        original_image: 原始图片路径
        a4_coords: A4 纸角点
        chip_coords: 阶梯卡角点
        layer_height: 层高 (mm)
        num_steps: 阶梯数量
    
    Returns:
        (fitting_plot, detection_image, ks_results, status_message)
    """
    try:
        # 验证输入
        if not original_image:
            return None, None, {}, "❌ 请先上传校准照片"
        
        if not a4_coords or len(a4_coords) != 4:
            return None, None, {}, "❌ 请先选择 A4纸/背景板的四个角点"
        
        if not chip_coords or len(chip_coords) != 4:
            return None, None, {}, "❌ 请先选择阶梯卡的四个角点"
        
        # 调用核心处理函数
        from core.ks_engine.calibration_ks import process_calibration_image
        
        ks_params, fitting_plot_path, detection_path, status_message = process_calibration_image(
            image_path=original_image,
            a4_corners=a4_coords,
            chip_corners=chip_coords,
            layer_height=layer_height,
            num_steps=int(num_steps)
        )
        
        return fitting_plot_path, detection_path, ks_params, status_message
        
    except Exception as e:
        import traceback
        error_msg = f"❌ K/S 参数计算失败: {str(e)}\n\n"
        error_msg += traceback.format_exc()
        return None, None, {}, error_msg


def save_filament_to_db_handler(name: str, color: str, ks_params: Dict) -> str:
    """
    保存耗材到数据库
    
    Args:
        name: 耗材名称
        color: 显示颜色
        ks_params: K/S 参数字典
    
    Returns:
        状态消息
    """
    try:
        if not name:
            return "❌ 请输入耗材名称"
        
        if not ks_params or 'K' not in ks_params or 'S' not in ks_params:
            return "❌ 请先计算 K/S 参数"
        
        # 读取现有数据库
        db_path = "my_filament.json"
        if os.path.exists(db_path):
            with open(db_path, 'r', encoding='utf-8') as f:
                db = json.load(f)
        else:
            db = {"filaments": []}
        
        # 添加新耗材
        new_filament = {
            "name": name,
            "color": color,
            "K": ks_params['K'],
            "S": ks_params['S']
        }
        
        # 检查是否已存在
        existing_idx = None
        for i, fil in enumerate(db.get("filaments", [])):
            if fil.get("name") == name:
                existing_idx = i
                break
        
        if existing_idx is not None:
            db["filaments"][existing_idx] = new_filament
            action = "更新"
        else:
            if "filaments" not in db:
                db["filaments"] = []
            db["filaments"].append(new_filament)
            action = "添加"
        
        # 保存数据库
        with open(db_path, 'w', encoding='utf-8') as f:
            json.dump(db, f, indent=2, ensure_ascii=False)
        
        return f"✅ 成功{action}耗材: {name}\n💾 已保存到 {db_path}"
        
    except Exception as e:
        import traceback
        error_msg = f"❌ 保存失败: {str(e)}\n\n"
        error_msg += traceback.format_exc()
        return error_msg


def convert_image_ks_handler(image, width, max_filaments, auto_select, selected):
    """K/S 图像转换"""
    # TODO: 实现实际逻辑
    return None, None, None, "⚠️ Function not implemented yet"


def load_filament_db_handler():
    """加载耗材数据库"""
    try:
        db_path = "my_filament.json"
        if not os.path.exists(db_path):
            return []
        
        with open(db_path, 'r', encoding='utf-8') as f:
            db = json.load(f)
        
        # 转换为表格格式
        rows = []
        for fil in db.get("filaments", []):
            K_str = f"[{fil['K'][0]:.3f}, {fil['K'][1]:.3f}, {fil['K'][2]:.3f}]"
            S_str = f"[{fil['S'][0]:.3f}, {fil['S'][1]:.3f}, {fil['S'][2]:.3f}]"
            rows.append([
                fil.get("name", "Unknown"),
                K_str,
                S_str,
                fil.get("color", "#FFFFFF")
            ])
        
        return rows
        
    except Exception as e:
        print(f"❌ 加载数据库失败: {e}")
        return []
