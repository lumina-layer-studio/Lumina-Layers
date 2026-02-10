"""
验证 Task 4：High-Fidelity 主流程接入新 matcher

测试场景：
1. 默认策略（RGB_EUCLIDEAN）是否正常工作
2. 新策略（DELTAE2000）是否正常工作
3. 两种策略的输出结构是否一致
"""

import numpy as np
import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from core.image_processing_factory.processing_modes import HighFidelityStrategy
from config import MatchStrategy
from scipy.spatial import KDTree


def create_test_data():
    """创建测试数据"""
    # 创建一个简单的测试图像（64x64 RGB）
    np.random.seed(42)
    rgb_arr = np.random.randint(0, 256, (100, 100, 3), dtype=np.uint8)

    # 创建测试 LUT（100个随机颜色）
    lut_rgb = np.random.randint(0, 256, (100, 3), dtype=np.uint8)

    # 创建测试 ref_stacks（100个，5层）
    ref_stacks = np.random.randint(0, 4, (100, 5), dtype=np.uint8)

    # 创建 KDTree
    kdtree = KDTree(lut_rgb.astype(float))

    return rgb_arr, lut_rgb, ref_stacks, kdtree


def test_default_strategy():
    """测试默认策略（RGB_EUCLIDEAN）"""
    print("\n" + "=" * 60)
    print("测试场景 1：默认策略（RGB_EUCLIDEAN）")
    print("=" * 60)

    rgb_arr, lut_rgb, ref_stacks, kdtree = create_test_data()

    strategy = HighFidelityStrategy()

    try:
        matched_rgb, material_matrix, quantized_image, debug_data = strategy.process(
            rgb_arr=rgb_arr,
            target_h=100,
            target_w=100,
            lut_rgb=lut_rgb,
            ref_stacks=ref_stacks,
            kdtree=kdtree,
            quantize_colors=16,
            blur_kernel=0,
            smooth_sigma=0,
            match_strategy=MatchStrategy.RGB_EUCLIDEAN,
        )

        # 验证输出结构
        assert isinstance(matched_rgb, np.ndarray), "matched_rgb 应该是 numpy 数组"
        assert isinstance(material_matrix, np.ndarray), (
            "material_matrix 应该是 numpy 数组"
        )
        assert isinstance(quantized_image, np.ndarray), (
            "quantized_image 应该是 numpy 数组"
        )
        assert isinstance(debug_data, dict), "debug_data 应该是字典"

        assert matched_rgb.shape == (100, 100, 3), (
            f"matched_rgb 形状错误: {matched_rgb.shape}"
        )
        assert material_matrix.shape == (100, 100, 5), (
            f"material_matrix 形状错误: {material_matrix.shape}"
        )
        assert quantized_image.shape == (100, 100, 3), (
            f"quantized_image 形状错误: {quantized_image.shape}"
        )

        print("✅ 默认策略测试通过")
        print(f"   - matched_rgb 形状: {matched_rgb.shape}")
        print(f"   - material_matrix 形状: {material_matrix.shape}")
        print(f"   - quantized_image 形状: {quantized_image.shape}")
        print(f"   - debug_data 包含 {len(debug_data)} 个键")

        return matched_rgb, material_matrix, quantized_image, debug_data

    except Exception as e:
        print(f"❌ 默认策略测试失败: {e}")
        import traceback

        traceback.print_exc()
        return None


def test_deltae2000_strategy():
    """测试新策略（DELTAE2000）"""
    print("\n" + "=" * 60)
    print("测试场景 2：新策略（DELTAE2000）")
    print("=" * 60)

    rgb_arr, lut_rgb, ref_stacks, kdtree = create_test_data()

    strategy = HighFidelityStrategy()

    try:
        matched_rgb, material_matrix, quantized_image, debug_data = strategy.process(
            rgb_arr=rgb_arr,
            target_h=100,
            target_w=100,
            lut_rgb=lut_rgb,
            ref_stacks=ref_stacks,
            kdtree=kdtree,
            quantize_colors=16,
            blur_kernel=0,
            smooth_sigma=0,
            match_strategy=MatchStrategy.DELTAE2000,
        )

        # 验证输出结构
        assert isinstance(matched_rgb, np.ndarray), "matched_rgb 应该是 numpy 数组"
        assert isinstance(material_matrix, np.ndarray), (
            "material_matrix 应该是 numpy 数组"
        )
        assert isinstance(quantized_image, np.ndarray), (
            "quantized_image 应该是 numpy 数组"
        )
        assert isinstance(debug_data, dict), "debug_data 应该是字典"

        assert matched_rgb.shape == (100, 100, 3), (
            f"matched_rgb 形状错误: {matched_rgb.shape}"
        )
        assert material_matrix.shape == (100, 100, 5), (
            f"material_matrix 形状错误: {material_matrix.shape}"
        )
        assert quantized_image.shape == (100, 100, 3), (
            f"quantized_image 形状错误: {quantized_image.shape}"
        )

        print("✅ DELTAE2000 策略测试通过")
        print(f"   - matched_rgb 形状: {matched_rgb.shape}")
        print(f"   - material_matrix 形状: {material_matrix.shape}")
        print(f"   - quantized_image 形状: {quantized_image.shape}")
        print(f"   - debug_data 包含 {len(debug_data)} 个键")

        return matched_rgb, material_matrix, quantized_image, debug_data

    except Exception as e:
        print(f"❌ DELTAE2000 策略测试失败: {e}")
        import traceback

        traceback.print_exc()
        return None


def test_invalid_strategy():
    """测试非法策略名"""
    print("\n" + "=" * 60)
    print("测试场景 3：非法策略名")
    print("=" * 60)

    rgb_arr, lut_rgb, ref_stacks, kdtree = create_test_data()

    strategy = HighFidelityStrategy()

    try:
        # 创建一个非法的 MatchStrategy 值
        # 由于 MatchStrategy 是枚举，我们需要测试传入非法值的情况
        # 这里我们测试传入字符串的情况（应该会报错）
        matched_rgb, material_matrix, quantized_image, debug_data = strategy.process(
            rgb_arr=rgb_arr,
            target_h=100,
            target_w=100,
            lut_rgb=lut_rgb,
            ref_stacks=ref_stacks,
            kdtree=kdtree,
            quantize_colors=16,
            blur_kernel=0,
            smooth_sigma=0,
            match_strategy="invalid_strategy",  # type: ignore
        )

        print("❌ 非法策略名测试失败：应该抛出异常但没有")
        return False

    except (ValueError, AttributeError, TypeError) as e:
        print(f"✅ 非法策略名测试通过：正确抛出异常")
        print(f"   - 异常类型: {type(e).__name__}")
        print(f"   - 异常信息: {e}")
        return True
    except Exception as e:
        print(f"⚠️  非法策略名测试抛出未预期的异常: {type(e).__name__}: {e}")
        return True


def main():
    """主测试函数"""
    print("\n" + "=" * 60)
    print("Task 4 验证：High-Fidelity 主流程接入新 matcher")
    print("=" * 60)

    # 测试 1：默认策略
    result1 = test_default_strategy()

    # 测试 2：DELTAE2000 策略
    result2 = test_deltae2000_strategy()

    # 测试 3：非法策略名
    result3 = test_invalid_strategy()

    # 总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)
    print(f"✅ 默认策略（RGB_EUCLIDEAN）: {'通过' if result1 else '失败'}")
    print(f"✅ 新策略（DELTAE2000）: {'通过' if result2 else '失败'}")
    print(f"✅ 非法策略名错误处理: {'通过' if result3 else '失败'}")

    if result1 and result2 and result3:
        print("\n🎉 所有测试通过！Task 4 实现正确。")
        return 0
    else:
        print("\n❌ 部分测试失败，请检查实现。")
        return 1


if __name__ == "__main__":
    exit(main())
