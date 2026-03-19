"""Top-level worker functions for vectorizer CPU tasks.
Vectorizer CPU 任务的顶层工作函数。

These functions run in separate processes via ProcessPoolExecutor.
All arguments must be picklable (file paths, scalars, dicts of scalars).
这些函数通过 ProcessPoolExecutor 在独立进程中运行。
所有参数必须可序列化（文件路径、标量、标量字典）。

Design rules:
- Top-level functions only (no methods) — must be picklable.
- Accept only file paths (str) and scalar parameters.
- Large results (SVG content) are written to temp files; paths are returned.
- All imports of neroued_vectorizer are lazy (inside function body).
"""


def worker_vectorize(image_path: str, params: dict) -> dict:
    """Execute image vectorization in a worker process.
    在工作进程中执行图像矢量化。

    Calls ``neroued_vectorizer.vectorize()`` with the supplied parameters,
    writes the SVG output to a temporary file, and returns a dict of
    results including file path and statistics.

    Args:
        image_path (str): Path to the input image file. (输入图像文件路径)
        params (dict): Dict of scalar parameters matching VectorizerConfig
            attributes (e.g. num_colors, smoothness, detail_level, etc.).
            (标量参数字典，对应 VectorizerConfig 属性)

    Returns:
        dict: Result dictionary with keys: (结果字典，包含以下键)
            - svg_path (str): Path to the generated SVG file.
            - width (int): Source image width in pixels.
            - height (int): Source image height in pixels.
            - num_shapes (int): Number of shapes in the SVG.
            - num_colors (int): Number of resolved colors.
            - palette (list[str]): Hex color strings of the palette.
    """
    import os
    import tempfile

    import neroued_vectorizer as nv

    config = nv.VectorizerConfig()
    for key, value in params.items():
        if hasattr(config, key):
            setattr(config, key, value)

    print(f"[Worker vectorize] image={image_path}, params={params}")

    result = nv.vectorize(image_path, config)

    fd, svg_path = tempfile.mkstemp(suffix=".svg")
    os.close(fd)
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(result.svg_content)

    palette_hex = []
    for rgb in result.palette:
        r, g, b = rgb.to_rgb255()
        palette_hex.append(f"#{r:02x}{g:02x}{b:02x}")

    return {
        "svg_path": svg_path,
        "width": result.width,
        "height": result.height,
        "num_shapes": result.num_shapes,
        "num_colors": result.resolved_num_colors,
        "palette": palette_hex,
    }
