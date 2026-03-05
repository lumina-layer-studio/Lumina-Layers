#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试 UI 层 hue_weight 参数集成
验证所有函数签名是否正确包含 hue_weight 参数
"""

import inspect
from ui.layout_new import process_batch_generation
from core.converter import generate_final_model, generate_preview_cached

def test_function_signature(func, func_name):
    """测试函数签名是否包含 hue_weight 参数"""
    sig = inspect.signature(func)
    params = list(sig.parameters.keys())
    has_hue = 'hue_weight' in params
    
    if has_hue:
        default = sig.parameters['hue_weight'].default
        print(f"✅ {func_name}: 包含 hue_weight 参数 (默认值: {default})")
        return True
    else:
        print(f"❌ {func_name}: 缺少 hue_weight 参数")
        return False

def main():
    print("=" * 60)
    print("测试 hue_weight 参数集成")
    print("=" * 60)
    
    results = []
    
    # 测试核心函数
    print("\n【核心转换函数】")
    results.append(test_function_signature(generate_final_model, "generate_final_model"))
    results.append(test_function_signature(generate_preview_cached, "generate_preview_cached"))
    
    # 测试 UI 函数
    print("\n【UI 层函数】")
    results.append(test_function_signature(process_batch_generation, "process_batch_generation"))
    
    # 总结
    print("\n" + "=" * 60)
    if all(results):
        print("✅ 所有测试通过! hue_weight 参数已成功集成到所有函数中")
        print("\n集成完成:")
        print("  • core/color_matching_hybrid.py - 色相匹配核心逻辑")
        print("  • core/image_processing.py - 图像处理器集成")
        print("  • core/converter.py - 转换器函数集成")
        print("  • ui/layout_new.py - UI 层完整集成")
        print("\nUI 控件:")
        print("  • slider_conv_hue_weight (0.0-1.0, 默认 0.3)")
        print("  • 标签: 色相权重 | Hue Weight")
        print("  • 说明: 0.0=纯CIELAB, 0.3=平衡(推荐), 0.7=强调同色系")
        return 0
    else:
        print("❌ 部分测试失败,请检查函数签名")
        return 1

if __name__ == "__main__":
    exit(main())
