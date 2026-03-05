"""
测试色相感知匹配器集成

验证 HueAwareColorMatcher 是否正确集成到 LuminaImageProcessor
"""

import numpy as np
from core.image_processing import LuminaImageProcessor

def test_hue_matching_integration():
    """测试色相匹配集成"""
    
    print("="*60)
    print("色相感知匹配器集成测试")
    print("="*60)
    
    # 创建一个简单的测试 LUT
    test_lut = np.array([
        [255, 255, 255],  # 白色
        [255, 0, 0],      # 红色
        [0, 255, 0],      # 绿色
        [0, 0, 255],      # 蓝色
        [255, 255, 0],    # 黄色
        [255, 0, 255],    # 品红
        [0, 255, 255],    # 青色
        [0, 0, 0],        # 黑色
    ], dtype=np.uint8)
    
    # 保存测试 LUT
    test_lut_path = "test_lut_8colors.npy"
    np.save(test_lut_path, test_lut.reshape(2, 4, 3))
    
    print(f"\n✅ 创建测试 LUT: {test_lut_path}")
    print(f"   包含 {len(test_lut)} 种颜色")
    
    # 测试不同的 hue_weight 值
    test_cases = [
        (0.0, "纯 CIELAB 模式"),
        (0.3, "平衡模式（推荐）"),
        (0.7, "强调同色系"),
    ]
    
    for hue_weight, description in test_cases:
        print(f"\n{'='*60}")
        print(f"测试 hue_weight={hue_weight} ({description})")
        print(f"{'='*60}")
        
        try:
            # 初始化处理器
            processor = LuminaImageProcessor(
                lut_path=test_lut_path,
                color_mode="8-Color",
                hue_weight=hue_weight
            )
            
            # 检查匹配器是否正确初始化
            if hue_weight > 0:
                assert processor.hue_matcher is not None, "色相匹配器应该被初始化"
                assert processor.hue_matcher.hue_weight == hue_weight, "hue_weight 不匹配"
                print(f"✅ 色相匹配器已启用")
            else:
                assert processor.hue_matcher is None, "hue_weight=0 时不应初始化匹配器"
                print(f"✅ 使用纯 CIELAB 匹配")
            
            # 测试颜色匹配
            test_colors = np.array([
                [255, 200, 200],  # 浅红色
                [200, 255, 200],  # 浅绿色
                [200, 200, 255],  # 浅蓝色
            ], dtype=np.uint8)
            
            print(f"\n测试颜色匹配:")
            for i, color in enumerate(test_colors):
                if processor.hue_matcher is not None:
                    idx = processor.hue_matcher.match_color(color)
                else:
                    color_lab = processor._rgb_to_lab(color.reshape(1, 3))
                    _, idx = processor.kdtree.query(color_lab)
                    idx = idx[0]
                
                matched = processor.lut_rgb[idx]
                print(f"  输入: RGB{tuple(color)} → 匹配: RGB{tuple(matched)}")
            
            print(f"\n✅ hue_weight={hue_weight} 测试通过")
            
        except Exception as e:
            print(f"\n❌ hue_weight={hue_weight} 测试失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    print(f"\n{'='*60}")
    print("✅ 所有测试通过！色相感知匹配器集成成功！")
    print(f"{'='*60}")
    
    # 清理测试文件
    import os
    os.remove(test_lut_path)
    print(f"\n🧹 清理测试文件: {test_lut_path}")
    
    return True


if __name__ == '__main__':
    success = test_hue_matching_integration()
    exit(0 if success else 1)
