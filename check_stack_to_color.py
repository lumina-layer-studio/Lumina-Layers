#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
反向查询工具：从配方查询对应的颜色
"""
import numpy as np
import sys

def load_npz(npz_path):
    """加载 .npz 文件"""
    data = np.load(npz_path)
    rgb = data['rgb']  # RGB 颜色数组
    stacks = data['stacks']  # 配方数组
    return rgb, stacks

def find_color_by_stack(rgb, stacks, target_stack):
    """根据配方查找对应的颜色"""
    target_stack = np.array(target_stack)
    
    # 查找完全匹配的配方
    for i in range(len(stacks)):
        if np.array_equal(stacks[i], target_stack):
            return i, rgb[i]
    
    return None, None

def main():
    # LUT 文件路径
    npz_path = "lut-npy预设/Custom/Merged_8-Color+4-Color+4-Color+6-Color+6-Color_20260303_134745.npz"
    
    # 目标配方: 黑-> 白-> 绿-> 绿 -> 品红
    # 根据 8 色模式的槽位映射:
    # 0=Red, 1=Magenta, 2=Cyan, 3=Deep Blue, 4=Yellow, 5=White, 6=Green, 7=Black
    # 黑=7, 白=5, 绿=6, 绿=6, 品红=1
    target_stack = [7, 5, 6, 6, 1]
    
    print(f"加载 LUT: {npz_path}")
    print()
    
    try:
        rgb, stacks = load_npz(npz_path)
        print(f"✅ LUT 加载成功")
        print(f"包含 {len(rgb)} 个颜色")
        print(f"每个配方有 {stacks.shape[1]} 层")
        print()
        
        # 材料槽位名称映射
        slot_names = {
            0: "红 (Red)",
            1: "品红 (Magenta)", 
            2: "青 (Cyan)",
            3: "深蓝 (Deep Blue)",
            4: "黄 (Yellow)",
            5: "白 (White)",
            6: "绿 (Green)",
            7: "黑 (Black)"
        }
        
        print("查询配方:")
        for i, mat_id in enumerate(target_stack):
            mat_name = slot_names.get(mat_id, f"Unknown (ID={mat_id})")
            print(f"  Layer {i+1}: {mat_name}")
        print()
        
        # 查找颜色
        idx, color = find_color_by_stack(rgb, stacks, target_stack)
        
        if idx is not None:
            r, g, b = color
            hex_color = f"#{r:02x}{g:02x}{b:02x}"
            print(f"✅ 找到匹配!")
            print(f"索引: {idx}")
            print(f"RGB: ({r}, {g}, {b})")
            print(f"十六进制: {hex_color}")
        else:
            print(f"❌ 未找到匹配的配方")
            print()
            print("可能的原因:")
            print("1. 配方顺序不正确")
            print("2. 该 LUT 不包含此配方")
            print("3. 配方层数不匹配")
            
    except FileNotFoundError:
        print(f"❌ 文件不存在: {npz_path}")
        sys.exit(1)
    except KeyError as e:
        print(f"❌ LUT 文件格式错误,缺少键: {e}")
        print("该文件可能不是有效的 Merged LUT (.npz)")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 错误: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
