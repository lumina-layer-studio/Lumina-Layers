"""
查询堆叠配方对应的颜色
"""
import numpy as np
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.image_processing import LuminaImageProcessor

def query_stack_color():
    """查询堆叠 [7 5 6 6 1] 对应的颜色"""
    
    # 加载 LUT 文件
    lut_path = r"lut-npy预设/Aliz/PETG/8色/Aliz&PETG&8色模式&大红-品红-青-克莱因蓝-黄-白-柠檬绿-黑.npy"
    
    print("=" * 80)
    print("查询堆叠配方对应的颜色")
    print("=" * 80)
    
    try:
        # 使用 LuminaImageProcessor 加载 LUT
        processor = LuminaImageProcessor(lut_path, "8-Color Max")
        
        print(f"\n✅ LUT 加载成功")
        print(f"LUT RGB 数组形状: {processor.lut_rgb.shape}")
        print(f"LUT 堆叠数组形状: {processor.ref_stacks.shape}")
        print(f"总颜色数: {len(processor.lut_rgb)}")
        
        # 目标堆叠: [7 5 6 6 1] (top-to-bottom)
        target_stack = np.array([7, 5, 6, 6, 1])
        
        print(f"\n目标堆叠 (top-to-bottom): {target_stack.tolist()}")
        print(f"  Layer 1 (顶层): ID=7 (Black)")
        print(f"  Layer 2: ID=5 (White)")
        print(f"  Layer 3: ID=6 (Green)")
        print(f"  Layer 4: ID=6 (Green)")
        print(f"  Layer 5 (底层): ID=1 (Magenta)")
        
        # 在 ref_stacks 中查找匹配的堆叠
        print(f"\n正在查找匹配的堆叠...")
        
        matches = []
        for idx, stack in enumerate(processor.ref_stacks):
            if np.array_equal(stack, target_stack):
                matches.append(idx)
        
        if matches:
            print(f"✅ 找到 {len(matches)} 个匹配的堆叠")
            
            # 取第一个匹配
            match_idx = matches[0]
            rgb = processor.lut_rgb[match_idx]
            
            r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
            hex_color = f"#{r:02x}{g:02x}{b:02x}"
            
            print(f"\n" + "=" * 80)
            print(f"查询结果")
            print(f"=" * 80)
            print(f"LUT 索引: {match_idx}")
            print(f"RGB: ({r}, {g}, {b})")
            print(f"HEX: {hex_color}")
            print(f"=" * 80)
            
            # 显示颜色块 (使用 ANSI 转义码)
            print(f"\n颜色预览 (近似):")
            print(f"\033[48;2;{r};{g};{b}m                    \033[0m  {hex_color}")
            
            return hex_color, (r, g, b)
        else:
            print(f"\n❌ 未找到匹配的堆叠")
            print(f"这个堆叠组合可能不在 LUT 中")
            return None, None
        
        r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        
        print(f"\n" + "=" * 80)
        print(f"查询结果")
        print(f"=" * 80)
        print(f"RGB: ({r}, {g}, {b})")
        print(f"HEX: {hex_color}")
        print(f"=" * 80)
        
        # 显示颜色块 (使用 ANSI 转义码)
        print(f"\n颜色预览 (近似):")
        print(f"\033[48;2;{r};{g};{b}m                    \033[0m  {hex_color}")
        
        return hex_color, (r, g, b)
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return None, None

if __name__ == "__main__":
    query_stack_color()
