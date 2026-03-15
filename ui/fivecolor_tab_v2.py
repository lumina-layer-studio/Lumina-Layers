#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
5色组合查询标签页 - V2 版本（使用隐藏按钮）
"""

import json
import gradio as gr


def create_5color_tab_v2(lang="zh"):
    """创建 5 色组合查询标签页 V2"""
    
    with gr.Row():
        # 左侧控制
        with gr.Column(scale=1):
            gr.Markdown("### 📁 选择 LUT")
            
            lut_dropdown = gr.Dropdown(
                label="LUT 文件",
                choices=_get_8color_luts(),
                value=None
            )
            
            status_text = gr.Textbox(
                label="状态",
                value="💡 请选择 LUT 文件",
                interactive=False,
                lines=2
            )
            
            sequence_text = gr.Textbox(
                label="选择序列",
                value="",
                interactive=False,
                lines=2
            )
            
            with gr.Row():
                clear_btn = gr.Button("🗑️ 清除", size="sm")
                undo_btn = gr.Button("↩️ 撤销", size="sm")
                reverse_btn = gr.Button("🔄 反序", size="sm")
            
            query_btn = gr.Button("🔍 查询结果", variant="primary", size="lg")
        
        # 右侧颜色选择
        with gr.Column(scale=2):
            gr.Markdown("### 🎨 基础颜色")
            gr.Markdown("点击色块进行选择（可重复，最多 5 次）")
            
            # 使用 HTML 显示颜色色块
            colors_html = gr.HTML(value=_empty_colors_html(), elem_id="colors-html-5color")
            
            # 创建最多 10 个隐藏按钮（支持更多颜色）
            color_btns = []
            for i in range(10):
                btn = gr.Button(f"Color {i}", visible=True, elem_id=f"color-btn-{i}-5color", elem_classes=["hidden-5color-btn"])
                color_btns.append(btn)
            
            gr.Markdown("### 查询结果")
            result_html = gr.HTML(value=_empty_result())
    
    # 隐藏状态
    lut_path_state = gr.Textbox(value="", visible=False)
    selected_state = gr.Textbox(value="[]", visible=False)
    color_count_state = gr.Textbox(value="0", visible=False)  # 存储颜色数量
    color_names_state = gr.Textbox(value="[]", visible=False)  # 存储颜色名称
    
    # 事件处理
    def on_load(lut_path):
        if not lut_path:
            return ("💡 请选择 LUT 文件", "", _empty_colors_html(), _empty_result(), "", "[]", "0", "[]")
        
        try:
            from core.five_color_combination import (
                StackLUTLoader, ColorQueryEngine, 
                ColorCountDetector, StackFileManager
            )
            
            # 检查是否是 NPZ 文件
            if lut_path.endswith('.npz'):
                # NPZ 文件包含 rgb 和 stacks
                s1, m1, stack_data, rgb_data = StackLUTLoader.load_npz_file(lut_path)
                if not s1:
                    return (f"❌ 加载失败: {m1}", "", _empty_colors_html(), _empty_result(), "", "[]", "0", "[]")
            else:
                # NPY 文件，需要加载 RGB 数据
                s2, m2, rgb_data = StackLUTLoader.load_lut_rgb(lut_path)
                
                if not s2:
                    return (f"❌ 加载失败: {m2}", "", _empty_colors_html(), _empty_result(), "", "[]", "0", "[]")
                
                # 检测颜色数量
                color_count, combo_count = ColorCountDetector.detect_color_count(rgb_data)
                
                if color_count == 0:
                    return (f"❌ 无法识别的 LUT 格式（{combo_count} 个组合）", "", _empty_colors_html(), _empty_result(), "", "[]", "0", "[]")
                
                # 查找对应的 stack 文件
                stack_path = StackFileManager.find_stack_file(color_count)
                
                if stack_path:
                    s1, m1, stack_data = StackLUTLoader.load_stack_lut(stack_path)
                    if not s1:
                        # Stack 文件加载失败，使用动态查询
                        stack_data = None
                else:
                    # 没有 stack 文件，使用动态查询
                    stack_data = None
            
            # 创建查询引擎
            engine = ColorQueryEngine(stack_data, rgb_data)
            base_colors = engine.get_base_colors()
            color_names = engine.get_color_names()
            color_count = len(base_colors)
            
            # 生成颜色 HTML
            colors_html_content = _generate_colors_html_v2(base_colors, color_count, color_names)
            
            mode = "快速查询" if stack_data is not None else "动态查询"
            status = f"✅ 已加载 {len(rgb_data)} 个组合（{color_count} 色，{mode}）"
            
            return (status, "", colors_html_content, _empty_result(), lut_path, "[]", str(color_count), json.dumps(color_names))
        except Exception as e:
            import traceback
            traceback.print_exc()
            return (f"❌ 错误: {str(e)}", "", _empty_colors_html(), _empty_result(), "", "[]", "0", "[]")
    
    def on_color_select(color_idx, lut_path, selected_json, color_names_json):
        """处理颜色选择"""
        if not lut_path:
            return (selected_json, "", _empty_result())
        
        selected = json.loads(selected_json) if selected_json else []
        color_names = json.loads(color_names_json) if color_names_json else []
        
        if len(selected) >= 5:
            return (selected_json, _format_seq(selected, color_names), _error_result("已选择 5 个颜色"))
        
        selected.append(color_idx)
        return (json.dumps(selected), _format_seq(selected, color_names), _empty_result())
    
    def on_clear():
        return ("[]", "", _empty_result())
    
    def on_undo(selected_json, color_names_json):
        selected = json.loads(selected_json) if selected_json else []
        color_names = json.loads(color_names_json) if color_names_json else []
        if selected:
            selected.pop()
        return (json.dumps(selected), _format_seq(selected, color_names), _empty_result())
    
    def on_reverse(selected_json, color_names_json):
        selected = json.loads(selected_json) if selected_json else []
        color_names = json.loads(color_names_json) if color_names_json else []
        if len(selected) == 5:
            selected.reverse()
        return (json.dumps(selected), _format_seq(selected, color_names))
    
    def on_query(lut_path, selected_json):
        if not lut_path:
            return _error_result("请先加载 LUT 文件")
        
        selected = json.loads(selected_json) if selected_json else []
        if len(selected) != 5:
            return _error_result(f"请选择 5 次颜色（当前: {len(selected)}/5）")
        
        try:
            from core.five_color_combination import (
                StackLUTLoader, ColorQueryEngine,
                ColorCountDetector, StackFileManager
            )
            
            # 检查是否是 NPZ 文件
            if lut_path.endswith('.npz'):
                # NPZ 文件包含 rgb 和 stacks
                _, _, stack_data, rgb_data = StackLUTLoader.load_npz_file(lut_path)
                # 尝试从同名 JSON 加载 source 信息
                sources = StackLUTLoader.load_sources_from_json(lut_path)
            else:
                # NPY 文件，需要加载 RGB 数据
                _, _, rgb_data = StackLUTLoader.load_lut_rgb(lut_path)
                sources = StackLUTLoader.load_sources_from_json(lut_path)
                
                # 检测颜色数量
                color_count, _ = ColorCountDetector.detect_color_count(rgb_data)
                
                # 查找对应的 stack 文件
                stack_path = StackFileManager.find_stack_file(color_count)
                
                if stack_path:
                    _, _, stack_data = StackLUTLoader.load_stack_lut(stack_path)
                else:
                    stack_data = None
            
            engine = ColorQueryEngine(stack_data, rgb_data, sources=sources)
            result = engine.query(selected)
            
            return _result_html(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return _error_result(f"错误: {str(e)}")
    
    # 绑定事件
    lut_dropdown.change(
        fn=on_load,
        inputs=[lut_dropdown],
        outputs=[status_text, sequence_text, colors_html, result_html, lut_path_state, selected_state, color_count_state, color_names_state]
    )
    
    # 为每个颜色按钮绑定事件
    for i, btn in enumerate(color_btns):
        btn.click(
            fn=lambda lut, sel, names, idx=i: on_color_select(idx, lut, sel, names),
            inputs=[lut_path_state, selected_state, color_names_state],
            outputs=[selected_state, sequence_text, result_html]
        )
    
    clear_btn.click(fn=on_clear, outputs=[selected_state, sequence_text, result_html])
    undo_btn.click(fn=on_undo, inputs=[selected_state, color_names_state], outputs=[selected_state, sequence_text, result_html])
    reverse_btn.click(fn=on_reverse, inputs=[selected_state, color_names_state], outputs=[selected_state, sequence_text])
    query_btn.click(fn=on_query, inputs=[lut_path_state, selected_state], outputs=[result_html])


def _get_8color_luts():
    """获取所有 LUT 文件列表（支持所有颜色数量）"""
    import os
    import numpy as np
    
    luts = []
    # 扫描所有 LUT 目录
    base_dirs = ["lut-npy预设"]
    
    for base_dir in base_dirs:
        if not os.path.exists(base_dir):
            continue
        
        # 递归扫描所有子目录
        for root, dirs, files in os.walk(base_dir):
            for f in files:
                path = os.path.join(root, f)
                try:
                    if f.endswith('.npy'):
                        data = np.load(path)
                        # 检查是否可以 reshape 为 (N, 3) 格式
                        reshaped = data.reshape(-1, 3)
                        # 接受所有有效的 LUT 文件（不再限制为 2738）
                        if reshaped.shape[0] > 0 and reshaped.shape[1] == 3:
                            luts.append(path)
                    elif f.endswith('.npz'):
                        # 支持 NPZ 文件（包含 rgb 和 stacks）
                        data = np.load(path)
                        if 'rgb' in data and 'stacks' in data:
                            luts.append(path)
                except:
                    pass
    
    return sorted(luts) if luts else ["(未找到)"]


def _format_seq(selected, color_names=None):
    if not selected:
        return ""
    
    if color_names:
        parts = []
        for i in selected:
            if i < len(color_names):
                parts.append(f"{color_names[i]}({i})")
            else:
                parts.append(f"颜色{i}")
        return f"[{len(selected)}/5] " + " → ".join(parts)
    else:
        return f"[{len(selected)}/5] " + " → ".join([f"颜色{i}" for i in selected])


def _empty_colors_html():
    return '<div style="padding:20px;text-align:center;color:#666;border:2px dashed #ddd;border-radius:8px;min-height:200px;display:flex;align-items:center;justify-content:center;">请先选择 LUT 文件</div>'


def _generate_colors_html_v2(base_colors, color_count=None, color_names=None):
    """生成基础颜色的 HTML - V2 版本（使用 data 属性）
    
    Args:
        base_colors: 基础颜色列表
        color_count: 颜色数量（用于确定网格列数）
        color_names: 颜色名称列表（可选）
    """
    from core.five_color_combination import rgb_to_hex
    
    if color_count is None:
        color_count = len(base_colors)
    
    # 根据颜色数量确定网格列数
    if color_count <= 4:
        columns = 2
    elif color_count <= 6:
        columns = 3
    else:
        columns = 4
    
    html = f'''
    <style>
    .color-grid-v2 {{
        display: grid;
        grid-template-columns: repeat({columns}, 1fr);
        gap: 15px;
        padding: 15px;
        background: #f9fafb;
        border-radius: 8px;
    }}
    .color-box-v2 {{
        aspect-ratio: 1;
        border-radius: 12px;
        cursor: pointer;
        transition: all 0.2s;
        border: 3px solid #e5e7eb;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        position: relative;
        overflow: hidden;
    }}
    .color-box-v2:hover {{
        transform: translateY(-5px);
        box-shadow: 0 8px 16px rgba(0,0,0,0.2);
        border-color: #667eea;
    }}
    .color-box-v2:active {{
        transform: translateY(-2px);
    }}
    .color-label-v2 {{
        position: absolute;
        bottom: 0;
        left: 0;
        right: 0;
        background: rgba(0,0,0,0.75);
        color: white !important;
        padding: 6px 4px;
        font-size: 12px;
        text-align: center;
        font-family: monospace;
        font-weight: 600;
        text-shadow: 0 1px 2px rgba(0,0,0,0.5);
    }}
    .color-name-v2 {{
        position: absolute;
        top: 8px;
        left: 8px;
        right: 8px;
        background: rgba(255,255,255,0.9);
        color: #333;
        padding: 4px 6px;
        font-size: 14px;
        text-align: center;
        font-weight: 700;
        border-radius: 4px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.2);
    }}
    </style>
    <div class="color-grid-v2" id="color-grid-5color-v2">
    '''
    
    for idx, rgb in enumerate(base_colors):
        hex_color = rgb_to_hex(rgb)
        color_name = color_names[idx] if color_names and idx < len(color_names) else f"色{idx}"
        html += f'''
        <div class="color-box-v2" style="background-color: {hex_color};" data-color-idx="{idx}" title="{color_name}({idx}): {hex_color}">
            <div class="color-name-v2">{color_name}({idx})</div>
            <div class="color-label-v2">{hex_color}</div>
        </div>
        '''
    
    html += '</div>'
    
    return html


def _empty_result():
    return '<div style="padding:20px;text-align:center;color:#666;border:2px dashed #ddd;border-radius:8px;">选择 5 次颜色后点击查询</div>'


def _error_result(msg):
    return f'<div style="padding:20px;text-align:center;color:#dc2626;border:2px solid #fecaca;background:#fef2f2;border-radius:8px;">❌ {msg}</div>'


def _result_html(result):
    from core.five_color_combination import rgb_to_hex
    
    if not result.found:
        return _error_result(result.message)
    
    hex_color = rgb_to_hex(result.result_rgb)
    r, g, b = result.result_rgb
    
    # 从消息中提取是否使用动态查询
    mode_text = "（动态查询）" if "动态查询" in result.message else ""
    
    # 来源信息
    source_html = ""
    if result.source:
        source_html = f'<div style="font-size:14px;color:#6b7280;margin-top:4px;">来源: {result.source}</div>'
    
    return f'''
    <div style="padding:20px;border:2px solid #10b981;background:#f0fdf4;border-radius:8px;">
        <div style="text-align:center;margin-bottom:15px;">
            <div style="font-size:18px;font-weight:600;color:#065f46;">✅ 查询成功{mode_text}</div>
            <div style="font-size:14px;color:#047857;">行索引: {result.row_index}</div>
        </div>
        <div style="display:flex;align-items:center;gap:20px;justify-content:center;">
            <div style="width:100px;height:100px;background-color:{hex_color};border-radius:12px;border:2px solid rgba(0,0,0,0.1);box-shadow:0 4px 8px rgba(0,0,0,0.15);"></div>
            <div style="text-align:left;">
                <div style="font-size:16px;font-family:monospace;font-weight:600;color:#374151;">{hex_color}</div>
                <div style="font-size:14px;color:#6b7280;">RGB({r}, {g}, {b})</div>
                {source_html}
            </div>
        </div>
    </div>
    '''
