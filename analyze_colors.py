import numpy as np


# ==========================================
# 🚑 紧急修复: 给 colormath 库打补丁
# ==========================================
def patch_asscalar(a):
    return a.item()


setattr(np, "asscalar", patch_asscalar)

# 补丁打完后再引入 colormath
from colormath.color_objects import sRGBColor, LabColor
from colormath.color_conversions import convert_color
from colormath.color_diff import delta_e_cie2000
import itertools
import os

# ================= 配置区域 =================

# 打印参数
LAYER_HEIGHT = 0.08  # 层高
LAYERS = 5  # 混色层数
BACKING_COLOR = np.array([255, 255, 255])  # 底板颜色 (白色)

# 耗材定义 (必须和 config.py 的 EIGHT_COLOR 顺序一致！)
FILAMENTS = {
    0: {"name": "White (Jade)", "rgb": [255, 255, 255], "td": 5.0},  # Slot 1
    1: {"name": "Cyan", "rgb": [0, 134, 214], "td": 3.5},  # Slot 2
    2: {"name": "Magenta", "rgb": [236, 0, 140], "td": 3.0},  # Slot 3
    3: {"name": "Yellow", "rgb": [244, 238, 42], "td": 6.0},  # Slot 4
    4: {"name": "Black", "rgb": [0, 0, 0], "td": 0.6},  # Slot 5 (黑色)
    5: {"name": "Red", "rgb": [193, 46, 31], "td": 4.0},  # Slot 6
    6: {"name": "Deep Blue", "rgb": [10, 41, 137], "td": 2.3},  # Slot 7
    7: {"name": "Green", "rgb": [0, 174, 66], "td": 2.0},  # Slot 8
}

# RGB距离阈值 (和6色算法一致)
RGB_DISTANCE_THRESHOLD = 8

# ===========================================


def calculate_alpha(td_value, layer_height):
    """计算单层透明度 (和6色算法一致)"""
    blending_distance = td_value / 10.0
    if blending_distance <= 0:
        return 1.0
    alpha = layer_height / blending_distance
    return min(max(alpha, 0.0), 1.0)


def mix_colors(stack):
    """
    颜色混合模拟 (和6色算法一致)
    stack: [底层 ... 顶层]
    """
    current_rgb = BACKING_COLOR.astype(float)
    for fid in stack:
        fil = FILAMENTS[fid]
        f_rgb = np.array(fil["rgb"])
        f_alpha = calculate_alpha(fil["td"], LAYER_HEIGHT)
        current_rgb = f_rgb * f_alpha + current_rgb * (1.0 - f_alpha)
    return current_rgb.astype(np.uint8)


def rgb_to_lab(rgb):
    """RGB转Lab (用于可选的色差分析)"""
    rgb_obj = sRGBColor(rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0)
    return convert_color(rgb_obj, LabColor)


def main():
    COLOR_COUNT = 8
    TARGET_COUNT = 2738  # 37x37×2 = 2738

    print("=" * 60)
    print(f"🎨 8色智能筛选算法 (仿6色优雅版)")
    print("=" * 60)
    print(
        f"🔄 开始模拟 {COLOR_COUNT}色 {LAYERS}层 全排列 ({COLOR_COUNT**LAYERS} 种组合)..."
    )
    print(f"📏 RGB距离阈值: {RGB_DISTANCE_THRESHOLD} (和6色算法一致)")
    print(f"🎯 目标数量: {TARGET_COUNT} 个颜色")
    print(f"🧱 黑色TD: {FILAMENTS[4]['td']}mm (和6色一致，自然筛选)")
    print()

    # ==================== 阶段1: 模拟所有组合 ====================
    print("[阶段1] 模拟所有颜色组合...")
    candidates = []

    for stack in itertools.product(range(COLOR_COUNT), repeat=LAYERS):
        final_rgb = mix_colors(stack)

        # 转换到Lab用于可选分析
        lab = rgb_to_lab(final_rgb)

        candidates.append({"stack": stack, "rgb": final_rgb, "lab": lab})

    print(f"✅ 模拟完成: {len(candidates)} 个组合")
    print()

    # ==================== 阶段2: 智能筛选 (仿6色算法) ====================
    print("[阶段2] 智能筛选 (贪心算法 + RGB距离)")

    selected = []

    # Step 1: 预选种子颜色 (8个纯色)
    print("  → 预选种子颜色 (8个纯色)...")
    for i in range(COLOR_COUNT):
        stack = (i,) * LAYERS
        for c in candidates:
            if c["stack"] == stack:
                selected.append(c)
                print(f"     种子 {i}: {FILAMENTS[i]['name']} - RGB{tuple(c['rgb'])}")
                break

    print(f"  ✓ 种子颜色: {len(selected)} 个")
    print()

    # Step 2: 高质量筛选 (RGB距离 > 8)
    print(f"  → 高质量筛选 (RGB距离 > {RGB_DISTANCE_THRESHOLD})...")
    round1_start = len(selected)

    for c in candidates:
        if len(selected) >= TARGET_COUNT:
            break

        # 跳过已选中的
        if any(c["stack"] == s["stack"] for s in selected):
            continue

        # 检查RGB距离
        is_distinct = True
        for s in selected:
            rgb_dist = np.linalg.norm(c["rgb"].astype(int) - s["rgb"].astype(int))
            if rgb_dist < RGB_DISTANCE_THRESHOLD:
                is_distinct = False
                break

        if is_distinct:
            selected.append(c)

        # 进度显示
        if len(selected) % 500 == 0:
            print(f"     进度: {len(selected)}/{TARGET_COUNT}")

    round1_count = len(selected) - round1_start
    print(f"  ✓ 高质量筛选: 新增 {round1_count} 个颜色")
    print()

    # Step 3: 填充剩余 (降低阈值)
    if len(selected) < TARGET_COUNT:
        print(f"  → 填充剩余 {TARGET_COUNT - len(selected)} 个位置...")
        for c in candidates:
            if len(selected) >= TARGET_COUNT:
                break
            if any(c["stack"] == s["stack"] for s in selected):
                continue
            selected.append(c)

        print(f"  ✓ 填充完成: 总计 {len(selected)} 个颜色")

    print()
    print("=" * 60)
    print(f"🎉 筛选完成!")
    print(f"   总组合数: {len(candidates)}")
    print(f"   最终选择: {len(selected)}")
    print(f"   筛选率: {len(selected) / len(candidates) * 100:.2f}%")
    print("=" * 60)
    print()

    # ==================== 阶段3: 保存结果 ====================
    output_dir = "assets"

    print(f"💾 保存到 '{output_dir}/'...")

    # 确保数量正确
    final_selection = selected[:TARGET_COUNT]

    # 如果不足，用白色填充
    if len(final_selection) < TARGET_COUNT:
        print(f"⚠️  不足 {TARGET_COUNT} 个，用白色填充...")
        dummy_stack = (0,) * LAYERS  # 白色
        while len(final_selection) < TARGET_COUNT:
            final_selection.append({"stack": dummy_stack})

    stacks_data = [item["stack"] for item in final_selection]
    stacks_array = np.array(stacks_data, dtype=np.uint8)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    save_path = os.path.join(output_dir, "smart_8color_stacks.npy")
    np.save(save_path, stacks_array)

    print(f"✅ 已保存到 '{save_path}'")
    print(f"   数组形状: {stacks_array.shape}")
    print(f"   数据类型: {stacks_array.dtype}")
    print()

    # ==================== 统计分析 ====================
    print("=" * 60)
    print("📊 统计分析")
    print("=" * 60)

    # 统计黑色使用情况 (修正：黑色现在的 ID 是 4)
    BLACK_ID = 4
    black_count = sum(1 for s in final_selection if BLACK_ID in s["stack"])
    black_surface = sum(1 for s in final_selection if s["stack"][4] == BLACK_ID)

    print(f"黑色使用统计 (ID={BLACK_ID}):")
    print(
        f"  包含黑色的组合: {black_count}/{len(final_selection)} ({black_count / len(final_selection) * 100:.1f}%)"
    )
    print(
        f"  表面层是黑色: {black_surface}/{len(final_selection)} ({black_surface / len(final_selection) * 100:.1f}%)"
    )
    print()

    # RGB分布统计
    all_rgb = np.array([s["rgb"] for s in final_selection])
    print(f"RGB分布:")
    print(
        f"  R: min={all_rgb[:, 0].min()}, max={all_rgb[:, 0].max()}, avg={all_rgb[:, 0].mean():.1f}"
    )
    print(
        f"  G: min={all_rgb[:, 1].min()}, max={all_rgb[:, 1].max()}, avg={all_rgb[:, 1].mean():.1f}"
    )
    print(
        f"  B: min={all_rgb[:, 2].min()}, max={all_rgb[:, 2].max()}, avg={all_rgb[:, 2].mean():.1f}"
    )
    print()

    print("✅ 完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
