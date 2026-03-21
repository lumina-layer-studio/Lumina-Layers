"""TCT 3D打印展会大幅面图像分割工具。
TCT 3D Printing Exhibition Large-Format Image Splitting Tool.

将 3071×4096 的原图补齐为 3072×4096，然后均匀切分为 3×4 共12块 1024×1024 的子图。
Resizes a 3071×4096 source image to 3072×4096, then splits into a 3×4 grid of 12 tiles (1024×1024 each).
"""

import sys
import os
from pathlib import Path
from PIL import Image
import tkinter as tk
from tkinter import filedialog


# ============================================================
# 配置参数
# ============================================================
TARGET_WIDTH = 3072       # 目标宽度（3列 × 1024）
TARGET_HEIGHT = 4096      # 目标高度（4行 × 1024）
COLS = 3                  # 列数
ROWS = 4                  # 行数
TILE_SIZE = 1024          # 每块子图的边长
OUTPUT_DIR_NAME = "tct_export_tiles"  # 输出文件夹名称


def split_image(image_path: str) -> None:
    """Read, resize, and split an image into a 3×4 grid of 1024×1024 tiles.
    读取图像，补齐尺寸后切分为 3×4 网格的 1024×1024 子图。

    Args:
        image_path (str): Path to the source image. (原图路径)

    Raises:
        FileNotFoundError: If the source image does not exist. (原图不存在时抛出)
        ValueError: If the source image dimensions are unexpected. (原图尺寸异常时抛出)
    """
    src = Path(image_path)

    # ----------------------------------------------------------
    # 1. 检查文件是否存在
    # ----------------------------------------------------------
    if not src.is_file():
        raise FileNotFoundError(f"找不到原图: {src}")

    print(f"[1/4] 正在读取原图: {src.name}")
    img = Image.open(src)
    w, h = img.size
    print(f"       原图分辨率: {w} × {h}")

    # ----------------------------------------------------------
    # 2. 尺寸补齐 —— resize 到 3072×4096
    #    1像素的形变对浮雕完全不可见
    # ----------------------------------------------------------
    if w == TARGET_WIDTH and h == TARGET_HEIGHT:
        print("[2/4] 尺寸已符合要求，无需补齐")
    else:
        print(f"[2/4] 正在补齐尺寸: {w}×{h} → {TARGET_WIDTH}×{TARGET_HEIGHT}")
        img = img.resize((TARGET_WIDTH, TARGET_HEIGHT), Image.LANCZOS)

    # ----------------------------------------------------------
    # 3. 创建输出目录（与原图同级）
    # ----------------------------------------------------------
    output_dir = src.parent / OUTPUT_DIR_NAME
    output_dir.mkdir(exist_ok=True)
    print(f"[3/4] 输出目录: {output_dir}")

    # ----------------------------------------------------------
    # 4. 精准切分为 3列 × 4行 = 12 块
    # ----------------------------------------------------------
    print("[4/4] 开始切分...")
    total = ROWS * COLS
    count = 0

    for row in range(ROWS):
        for col in range(COLS):
            count += 1
            # 计算裁剪区域 (left, upper, right, lower)
            left = col * TILE_SIZE
            upper = row * TILE_SIZE
            right = left + TILE_SIZE
            lower = upper + TILE_SIZE

            tile = img.crop((left, upper, right, lower))

            # 命名: tile_R1_C1.png ~ tile_R4_C3.png（行列从1开始）
            filename = f"tile_R{row + 1}_C{col + 1}.png"
            tile_path = output_dir / filename

            tile.save(tile_path)
            print(f"       正在处理: {filename} ({count}/{total})  "
                  f"[区域: ({left},{upper})-({right},{lower})]  ✓")

            # 最终校验：确保每块都是 1024×1024
            assert tile.size == (TILE_SIZE, TILE_SIZE), (
                f"子图尺寸异常: {tile.size}，期望 ({TILE_SIZE}, {TILE_SIZE})"
            )

    print(f"\n全部完成! 共导出 {total} 张 {TILE_SIZE}×{TILE_SIZE} 子图")
    print(f"保存位置: {output_dir.resolve()}")


def select_image() -> str | None:
    """Open a file dialog for the user to select an image.
    弹出文件选择对话框让用户选择图片。

    Returns:
        str | None: Selected file path, or None if cancelled. (选中的文件路径，取消则返回 None)
    """
    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口
    root.attributes("-topmost", True)  # 确保对话框在最前面

    file_path = filedialog.askopenfilename(
        title="选择要分割的图片",
        filetypes=[
            ("图片文件", "*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.webp"),
            ("所有文件", "*.*"),
        ],
    )
    root.destroy()
    return file_path if file_path else None


if __name__ == "__main__":
    # 优先使用命令行参数，否则弹出文件选择对话框
    if len(sys.argv) >= 2:
        path = sys.argv[1]
    else:
        print("请在弹出的对话框中选择图片...")
        path = select_image()
        if not path:
            print("未选择文件，已取消。")
            sys.exit(0)

    split_image(path)
