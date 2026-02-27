"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║                    K/S ENGINE - K/S PARAMETER CALCULATION                     ║
║                      K/S 引擎 - K/S 参数计算                                   ║
╚═══════════════════════════════════════════════════════════════════════════════╝

This module provides K/S parameter calculation from calibration photos.

Adapted from ChromaStack project:
https://github.com/borealis-zhe/ChromaStack

Key Features:
- Interactive corner point selection (Gradio-based)
- Automatic white balance
- Color sampling from step card
- K-M parameter fitting using scipy
- Visualization of fitting results
"""

import os
from typing import List, Tuple, Dict, Optional
import numpy as np
import cv2
import pandas as pd
from scipy.optimize import minimize
import matplotlib
matplotlib.use('Agg')  # 非交互式后端
import matplotlib.pyplot as plt


# ========== 标准 sRGB 转换（与 physics.py 完全一致） ==========

def srgb_to_linear(srgb_normalized: np.ndarray) -> np.ndarray:
    """
    标准 sRGB → 线性 RGB（反伽马校正）
    与 physics.py 的 linear_to_srgb_bytes 互逆
    
    Args:
        srgb_normalized: sRGB 值，范围 [0, 1]
    
    Returns:
        线性 RGB 值，范围 [0, 1]
    """
    srgb_normalized = np.clip(srgb_normalized, 0, 1)
    return np.where(
        srgb_normalized <= 0.04045,
        srgb_normalized / 12.92,
        ((srgb_normalized + 0.055) / 1.055) ** 2.4
    )


def linear_to_srgb(linear: np.ndarray) -> np.ndarray:
    """
    线性 RGB → 标准 sRGB
    与 physics.py 的 linear_to_srgb_bytes 一致（但返回 [0,1] 浮点）
    
    Args:
        linear: 线性 RGB 值，范围 [0, 1]
    
    Returns:
        sRGB 值，范围 [0, 1]
    """
    linear = np.clip(linear, 0, 1)
    return np.where(
        linear <= 0.0031308,
        12.92 * linear,
        1.055 * (linear ** (1.0 / 2.4)) - 0.055
    )


# ========== 图像处理工具 ==========

def apply_perspective_transform(
    img: np.ndarray,
    src_pts: np.ndarray,
    dst_w: int,
    dst_h: int
) -> np.ndarray:
    """
    透视变换矫正
    
    Args:
        img: 输入图像
        src_pts: 源四个角点 [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
        dst_w: 目标宽度
        dst_h: 目标高度
    
    Returns:
        矫正后的图像
    """
    dst_pts = np.float32([[0, 0], [dst_w, 0], [dst_w, dst_h], [0, dst_h]])
    M = cv2.getPerspectiveTransform(src_pts, dst_pts)
    return cv2.warpPerspective(img, M, (dst_w, dst_h))


def auto_white_balance_by_paper(
    img_a4: np.ndarray,
    enable_wb: bool = True,
    target_white: float = 240.0
) -> np.ndarray:
    """
    基于 A4 纸边缘区域进行白平衡
    
    K/S 提取需要准确的绝对反射率，因此使用强白平衡：
    将纸张白色区域归一化到 target_white（默认 240）。
    
    Args:
        img_a4: A4 纸校正后的图像
        enable_wb: 是否启用白平衡（默认 True）
        target_white: 目标白点亮度（默认 240，对应反射率 ~0.94）
    
    Returns:
        白平衡后的图像
    """
    if not enable_wb:
        return img_a4
    
    h, w = img_a4.shape[:2]
    margin_h, margin_w = int(h * 0.1), int(w * 0.1)
    
    # 创建掩膜，只取边缘部分（认为是纯白纸区域）
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.rectangle(mask, (0, 0), (w, margin_h), 255, -1)
    cv2.rectangle(mask, (0, h-margin_h), (w, h), 255, -1)
    cv2.rectangle(mask, (0, 0), (margin_w, h), 255, -1)
    cv2.rectangle(mask, (w-margin_w, 0), (w, h), 255, -1)
    
    mean_bg_bgr = cv2.mean(img_a4, mask=mask)[:3]
    
    # 强白平衡：将纸张白色归一化到 target_white
    # 这确保了 sRGB 240 ≈ 线性 0.87（接近白纸实际反射率）
    gains = target_white / (np.array(mean_bg_bgr) + 1e-5)
    
    # 限制增益范围，避免极端校正
    gains = np.clip(gains, 0.5, 3.0)
    
    print(f"[WB] Background BGR: {np.array(mean_bg_bgr).astype(int)}, "
          f"Target: {target_white}, Gains: {gains.round(3)}")
    
    # 应用增益
    result = np.clip(cv2.multiply(img_a4.astype(float), gains), 0, 255).astype(np.uint8)
    
    return result


def sample_step_card_colors(
    img_chip: np.ndarray,
    num_steps: int = 5,
    patch_size: int = 20
) -> pd.DataFrame:
    """
    从阶梯卡图像中采样颜色
    
    Args:
        img_chip: 阶梯卡校正后的图像
        num_steps: 阶梯数量
        patch_size: 采样区域大小
    
    Returns:
        DataFrame 包含每层的反射率数据
    """
    h, w = img_chip.shape[:2]
    rows = num_steps
    cols = 2
    dy = h // rows
    dx = w // cols
    
    data = []
    debug_view = img_chip.copy()
    
    for r in range(rows):
        # 几何计算
        x_left = int(0.5 * dx)   # 黑底中心
        x_right = int(1.5 * dx)  # 白底中心
        y_center = int((r + 0.5) * dy)
        
        # 提取颜色区域
        roi_0 = img_chip[
            y_center-patch_size:y_center+patch_size,
            x_left-patch_size:x_left+patch_size
        ]
        rgb_0 = np.mean(roi_0, axis=(0,1))[::-1]  # BGR转RGB
        
        roi_w = img_chip[
            y_center-patch_size:y_center+patch_size,
            x_right-patch_size:x_right+patch_size
        ]
        rgb_w = np.mean(roi_w, axis=(0,1))[::-1]
        
        # Linear Reflectance (标准 sRGB 反伽马校正，与 physics.py 一致)
        R0_linear = srgb_to_linear(rgb_0 / 255.0)
        Rw_linear = srgb_to_linear(rgb_w / 255.0)
        
        # 层数映射: r=0 (图片最上方) -> 实物第 num_steps 层 (最厚)
        layer_idx = num_steps - r
        
        data.append({
            'Layer_Index': layer_idx,
            'R0_r': R0_linear[0], 'R0_g': R0_linear[1], 'R0_b': R0_linear[2],
            'Rw_r': Rw_linear[0], 'Rw_g': Rw_linear[1], 'Rw_b': Rw_linear[2]
        })
        
        # 绘制采样点
        cv2.circle(debug_view, (x_left, y_center), 5, (0, 255, 0), -1)
        cv2.circle(debug_view, (x_right, y_center), 5, (0, 0, 255), -1)
        cv2.putText(
            debug_view, f"L{layer_idx}",
            (x_left - 20, y_center - 10),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2
        )
    
    # 保存调试图
    os.makedirs("output/ks_engine/debug", exist_ok=True)
    cv2.imwrite("output/ks_engine/debug/sampling_points.jpg", debug_view)
    
    # 排序并生成 DataFrame
    df = pd.DataFrame(data).sort_values('Layer_Index')
    
    return df


# ========== K-M 理论拟合 ==========

def km_reflectance(K: float, S: float, h: np.ndarray, Rg: float) -> np.ndarray:
    """
    Kubelka-Munk 理论反射率公式
    
    Args:
        K: 吸收系数
        S: 散射系数
        h: 厚度 (mm)
        Rg: 底材反射率
    
    Returns:
        反射率
    """
    S = max(S, 1e-6)  # 避免除零
    
    a = 1 + (K / S)
    b = np.sqrt(a**2 - 1)
    
    bSh = b * S * h
    sinh_bSh = np.sinh(bSh)
    cosh_bSh = np.cosh(bSh)
    
    numerator = sinh_bSh * (1 - Rg * a) + Rg * b * cosh_bSh
    denominator = sinh_bSh * (a - Rg) + b * cosh_bSh
    
    R = numerator / denominator
    return R


def fit_km_parameters(
    thicknesses: np.ndarray,
    R0_measured: np.ndarray,
    Rw_measured: np.ndarray,
    backing_reflectance_white: float = 0.94,
    backing_reflectance_black: float = 0.00
) -> Tuple[Tuple[float, float], float]:
    """
    针对单个颜色通道拟合 K 和 S（多重启动，避免局部最优）
    
    Args:
        thicknesses: 厚度数组
        R0_measured: 黑底测量反射率
        Rw_measured: 白底测量反射率
        backing_reflectance_white: 白底反射率
        backing_reflectance_black: 黑底反射率
    
    Returns:
        ((K, S), error)
    """
    bounds = [(1e-5, 100), (1e-5, 100)]
    
    def loss_function(params):
        K_val, S_val = params
        R0_pred = km_reflectance(K_val, S_val, thicknesses, backing_reflectance_black)
        Rw_pred = km_reflectance(K_val, S_val, thicknesses, backing_reflectance_white)
        error_0 = np.mean((R0_pred - R0_measured) ** 2)
        error_w = np.mean((Rw_pred - Rw_measured) ** 2)
        return error_0 + error_w
    
    # 多重启动：覆盖不同量级的 K/S 组合
    # 白色(K小S大)、深色(K大S小)、中间色、高散射、低散射
    initial_guesses = [
        [0.1, 1.0],     # 默认
        [0.001, 5.0],   # 白色/浅色（K极小，S大）
        [1.0, 3.0],     # 中等吸收
        [10.0, 2.0],    # 深色（K大）
        [0.5, 0.5],     # 低散射
        [30.0, 3.0],    # 极深色
        [0.01, 10.0],   # 高散射浅色
    ]
    
    best_x = None
    best_error = float('inf')
    
    for x0 in initial_guesses:
        try:
            result = minimize(loss_function, x0, bounds=bounds, method='L-BFGS-B',
                            options={'maxiter': 5000, 'ftol': 1e-15})
            if result.fun < best_error:
                best_error = result.fun
                best_x = result.x
        except Exception:
            continue
    
    if best_x is None:
        # 兜底：用默认初始值
        result = minimize(loss_function, [0.1, 1.0], bounds=bounds, method='L-BFGS-B')
        best_x = result.x
        best_error = result.fun
    
    return best_x, best_error


def calculate_and_plot_km(
    df: pd.DataFrame,
    layer_height: float = 0.08,
    backing_reflectance_white: float = 0.94,
    backing_reflectance_black: float = 0.00,
    output_dir: str = "output/ks_engine"
) -> Tuple[Dict, str, str]:
    """
    计算 K-M 参数并生成拟合曲线图
    
    Args:
        df: 采样数据 DataFrame
        layer_height: 层高 (mm)
        backing_reflectance_white: 白底反射率
        backing_reflectance_black: 黑底反射率
        output_dir: 输出目录
    
    Returns:
        (ks_params, fitting_plot_path, status_message)
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # 准备数据
    thicknesses = df['Layer_Index'].values * layer_height
    
    results = {}
    channels = ['r', 'g', 'b']
    
    # 创建可视化图表
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    
    status_lines = []
    status_lines.append("🚀 Kubelka-Munk 参数拟合")
    status_lines.append(f"   厚度范围: {thicknesses[0]:.2f}mm - {thicknesses[-1]:.2f}mm")
    status_lines.append("")
    
    for i, ch in enumerate(channels):
        R0_meas = df[f'R0_{ch}'].values
        Rw_meas = df[f'Rw_{ch}'].values
        
        # 拟合
        (best_K, best_S), error = fit_km_parameters(
            thicknesses, R0_meas, Rw_meas,
            backing_reflectance_white, backing_reflectance_black
        )
        results[ch] = {'K': best_K, 'S': best_S}
        
        status_lines.append(f"🎨 {ch.upper()} 通道: K={best_K:.4f}, S={best_S:.4f} (误差: {error:.5f})")
        
        # 绘图
        ax = axes[i]
        ax.scatter(thicknesses, R0_meas, color='black', label='Measured (Black Base)', s=50)
        ax.scatter(thicknesses, Rw_meas, color='gray', marker='s', label='Measured (White Base)', s=50)
        
        # 拟合曲线
        h_smooth = np.linspace(0, thicknesses[-1] + 0.2, 50)
        R0_smooth = km_reflectance(best_K, best_S, h_smooth, backing_reflectance_black)
        Rw_smooth = km_reflectance(best_K, best_S, h_smooth, backing_reflectance_white)
        
        plot_color = 'red' if ch=='r' else 'green' if ch=='g' else 'blue'
        ax.plot(h_smooth, R0_smooth, linestyle='--', color=plot_color, label='K-M Model (Black)', linewidth=2)
        ax.plot(h_smooth, Rw_smooth, linestyle='-', color=plot_color, alpha=0.5, label='K-M Model (White)', linewidth=2)
        
        ax.set_title(f"Channel {ch.upper()}\nK={best_K:.3f}, S={best_S:.3f}", fontsize=12, fontweight='bold')
        ax.set_xlabel("Thickness (mm)", fontsize=10)
        ax.set_ylabel("Reflectance", fontsize=10)
        ax.grid(True, alpha=0.3)
        if i == 0:
            ax.legend(fontsize=8)
    
    plt.tight_layout()
    plot_path = os.path.join(output_dir, "km_fitting_result.png")
    plt.savefig(plot_path, dpi=150)
    plt.close()
    
    # 构建 K/S 参数字典
    ks_params = {
        'K': [results['r']['K'], results['g']['K'], results['b']['K']],
        'S': [results['r']['S'], results['g']['S'], results['b']['S']]
    }
    
    status_lines.append("")
    status_lines.append("📋 JSON 参数 (可直接填入 my_filament.json):")
    status_lines.append(f'  "FILAMENT_K": [{ks_params["K"][0]:.4f}, {ks_params["K"][1]:.4f}, {ks_params["K"][2]:.4f}]')
    status_lines.append(f'  "FILAMENT_S": [{ks_params["S"][0]:.4f}, {ks_params["S"][1]:.4f}, {ks_params["S"][2]:.4f}]')
    
    # 物理意义解读
    avg_S = np.mean(ks_params['S'])
    avg_K = np.mean(ks_params['K'])
    
    status_lines.append("")
    status_lines.append("💡 材料特性:")
    if avg_S > 10:
        status_lines.append("   [高遮盖力] 类似牛奶或浓缩颜料")
    elif avg_S < 1:
        status_lines.append("   [低遮盖力] 类似清漆或彩色玻璃")
    else:
        status_lines.append("   [半透明] 类似玉石或雾状塑料")
    
    if avg_K > 2:
        status_lines.append("   [深色] 吸光能力强")
    elif avg_K < 0.1:
        status_lines.append("   [浅色/透明] 吸光能力弱")
    
    status_message = "\n".join(status_lines)
    
    return ks_params, plot_path, status_message


# ========== 主处理流程 ==========

def process_calibration_image(
    image_path: str,
    a4_corners: List[List[float]],
    chip_corners: List[List[float]],
    layer_height: float = 0.08,
    num_steps: int = 5,
    a4_width: int = 1414,
    a4_height: int = 1000,
    chip_width: int = 400,
    chip_height: int = 500,
    enable_white_balance: bool = False
) -> Tuple[Dict, str, str, str]:
    """
    处理校准图像并计算 K/S 参数
    
    ⚠️ 重要：chip_corners 应该是相对于校正后的 A4 图像的坐标，而不是原始图像！
    
    Args:
        image_path: 图像路径
        a4_corners: A4 纸四个角点 [[x1,y1], [x2,y2], [x3,y3], [x4,y4]] (相对于原始图像)
        chip_corners: 阶梯卡四个角点 (相对于校正后的 A4 图像)
        layer_height: 层高 (mm)
        num_steps: 阶梯数量
        a4_width: A4 纸校正后宽度
        a4_height: A4 纸校正后高度
        chip_width: 阶梯卡校正后宽度
        chip_height: 阶梯卡校正后高度
        enable_white_balance: 是否启用白平衡（默认 False）
    
    Returns:
        (ks_params, fitting_plot_path, detection_image_path, status_message)
    """
    try:
        # 读取图像
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"无法读取图像: {image_path}")
        
        # 1. A4 纸校正
        a4_pts = np.float32(a4_corners)
        img_a4 = apply_perspective_transform(img, a4_pts, a4_width, a4_height)
        
        # 保存中间结果用于调试
        os.makedirs("output/ks_engine/debug", exist_ok=True)
        cv2.imwrite("output/ks_engine/debug/01_a4_corrected.jpg", img_a4)
        
        # 白平衡（可选）
        if enable_white_balance:
            img_calibrated = auto_white_balance_by_paper(img_a4, enable_wb=True)
            cv2.imwrite("output/ks_engine/debug/02_white_balanced.jpg", img_calibrated)
        else:
            img_calibrated = img_a4
            print("[WB] White balance disabled, using original A4 corrected image")
        
        # 2. 阶梯卡提取（chip_corners 是相对于 img_calibrated 的坐标）
        chip_pts = np.float32(chip_corners)
        img_chip = apply_perspective_transform(img_calibrated, chip_pts, chip_width, chip_height)
        cv2.imwrite("output/ks_engine/debug/03_chip_extracted.jpg", img_chip)
        
        # 保存检测结果图（在原始图像上绘制 A4 边界）
        detection_img = img.copy()
        cv2.polylines(detection_img, [a4_pts.astype(int)], True, (0, 255, 0), 3)
        
        # 在 A4 校正后的图像上绘制阶梯卡轮廓
        chip_on_a4 = img_calibrated.copy()
        cv2.polylines(chip_on_a4, [chip_pts.astype(int)], True, (0, 0, 255), 3)
        cv2.imwrite("output/ks_engine/debug/04_chip_on_a4.jpg", chip_on_a4)
        
        detection_path = "output/ks_engine/debug/detection_result.jpg"
        cv2.imwrite(detection_path, detection_img)
        
        # 3. 采样颜色
        df = sample_step_card_colors(img_chip, num_steps)
        
        # 4. 计算 K/S 参数
        ks_params, fitting_plot_path, status_message = calculate_and_plot_km(
            df, layer_height
        )
        
        return ks_params, fitting_plot_path, detection_path, status_message
        
    except Exception as e:
        import traceback
        error_msg = f"❌ 处理失败: {str(e)}\n\n"
        error_msg += traceback.format_exc()
        return {}, "", "", error_msg


if __name__ == "__main__":
    # 测试代码
    print("=== K/S Parameter Calculation Module Test ===\n")
    print("此模块需要通过 Gradio UI 使用，提供交互式角点选择功能")
