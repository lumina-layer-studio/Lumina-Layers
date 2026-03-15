"""Top-level worker functions for converter CPU tasks.
Converter CPU 任务的顶层工作函数。

These functions run in separate processes via ProcessPoolExecutor.
All arguments must be picklable (file paths, scalars, dicts of scalars).
这些函数通过 ProcessPoolExecutor 在独立进程中运行。
所有参数必须可序列化（文件路径、标量、标量字典）。

Design rules:
- Top-level functions only (no methods) — must be picklable.
- Accept only file paths (str) and scalar parameters (int, float, bool, str, dict).
- NEVER accept numpy arrays, PIL Images, or complex objects.
- Large results (images, cache data) are written to temp files; paths are returned.
- All imports of core modules are lazy (inside function body).
"""


def worker_generate_preview(
    image_path: str,
    lut_path: str,
    target_width_mm: float,
    auto_bg: bool,
    bg_tol: int,
    color_mode: str,
    modeling_mode: str,
    quantize_colors: int,
    enable_cleanup: bool,
    is_dark: bool = True,
    hue_weight: float = 0.0,
    chroma_gate: float = 15.0,
) -> dict:
    """Execute preview generation in a worker process.
    在工作进程中执行预览生成。

    Calls ``core.converter.generate_preview_cached`` with the supplied
    scalar parameters, serialises the resulting preview image and cache
    data to temporary files, and returns a dict of file paths.

    Args:
        image_path (str): Path to the input image file. (输入图像文件路径)
        lut_path (str): Path to the LUT calibration file (.npy/.npz). (LUT 校准文件路径)
        target_width_mm (float): Target physical width in mm. (目标物理宽度，毫米)
        auto_bg (bool): Enable automatic background removal. (启用自动背景移除)
        bg_tol (int): Background tolerance value. (背景容差值)
        color_mode (str): Color system mode, e.g. "CMYW". (色彩系统模式)
        modeling_mode (str): Modeling mode string value, e.g. "high-fidelity". (建模模式字符串)
        quantize_colors (int): Number of K-Means quantization colors. (K-Means 量化颜色数)
        enable_cleanup (bool): Enable isolated-pixel cleanup. (启用孤立像素清理)
        is_dark (bool): Dark theme flag for 2D preview bed colors. (深色主题标志)

    Returns:
        dict: Result dictionary with keys: (结果字典，包含以下键)
            - preview_png_path (str | None): Path to saved preview PNG.
            - cache_data_path (str | None): Path to pickled cache data.
            - status_msg (str): Status message from the converter.
    """
    # Lazy imports — executed inside the worker process
    import os
    import pickle
    import tempfile

    import numpy as np
    from PIL import Image

    from config import ModelingMode
    from core.converter import generate_preview_cached

    # Convert string modeling_mode to enum
    mode_enum = ModelingMode(modeling_mode)

    print(f"[Worker preview] hue_weight={hue_weight}, chroma_gate={chroma_gate}, lut_path={lut_path}")
    preview_img, cache_data, status_msg = generate_preview_cached(
        image_path=image_path,
        lut_path=lut_path,
        target_width_mm=target_width_mm,
        auto_bg=auto_bg,
        bg_tol=bg_tol,
        color_mode=color_mode,
        modeling_mode=mode_enum,
        quantize_colors=quantize_colors,
        enable_cleanup=enable_cleanup,
        is_dark=is_dark,
        hue_weight=hue_weight,
        chroma_gate=chroma_gate,
    )

    result: dict = {
        "status_msg": status_msg,
        "preview_png_path": None,
        "cache_data_path": None,
    }

    # Write preview image to a temp PNG file
    if preview_img is not None:
        fd, png_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        if isinstance(preview_img, np.ndarray):
            Image.fromarray(preview_img).save(png_path)
        else:
            preview_img.save(png_path)
        result["preview_png_path"] = png_path

    # Pickle cache data to a temp file
    if cache_data is not None:
        fd, cache_path = tempfile.mkstemp(suffix=".pkl")
        os.close(fd)
        with open(cache_path, "wb") as f:
            pickle.dump(cache_data, f)
        result["cache_data_path"] = cache_path

    return result


def worker_batch_convert_item(
    image_path: str,
    lut_path: str,
    target_width_mm: float,
    spacer_thick: float,
    structure_mode: str,
    auto_bg: bool,
    bg_tol: int,
    color_mode: str,
    modeling_mode_value: str,
    quantize_colors: int,
    enable_cleanup: bool,
    hue_weight: float = 0.0,
    chroma_gate: float = 15.0,
) -> dict:
    """Execute a single batch conversion item in a worker process.
    在工作进程中执行单个批量转换项。

    Calls ``core.converter.convert_image_to_3d`` with the supplied
    scalar parameters and returns a dict containing the output file path
    and status message.

    Args:
        image_path (str): Path to the input image file. (输入图像文件路径)
        lut_path (str): Path to the LUT calibration file. (LUT 校准文件路径)
        target_width_mm (float): Target physical width in mm. (目标物理宽度，毫米)
        spacer_thick (float): Backing plate thickness in mm. (底板厚度，毫米)
        structure_mode (str): Print structure mode, e.g. "Double-sided". (打印结构模式)
        auto_bg (bool): Enable automatic background removal. (启用自动背景移除)
        bg_tol (int): Background tolerance value. (背景容差值)
        color_mode (str): Color system mode, e.g. "4-Color". (色彩系统模式)
        modeling_mode_value (str): Modeling mode string, e.g. "high-fidelity". (建模模式字符串)
        quantize_colors (int): Number of K-Means quantization colors. (K-Means 量化颜色数)
        enable_cleanup (bool): Enable isolated-pixel cleanup. (启用孤立像素清理)

    Returns:
        dict: Result dictionary with keys: (结果字典，包含以下键)
            - threemf_path (str | None): Path to the generated .3mf file.
            - status_msg (str): Status message from the converter.
    """
    # Lazy imports — executed inside the worker process
    from config import ModelingMode
    from core.converter import convert_image_to_3d

    core_modeling_mode = ModelingMode(modeling_mode_value)

    threemf_path, _glb_path, _preview_img, status_msg = convert_image_to_3d(
        image_path=image_path,
        lut_path=lut_path,
        target_width_mm=target_width_mm,
        spacer_thick=spacer_thick,
        structure_mode=structure_mode,
        auto_bg=auto_bg,
        bg_tol=bg_tol,
        color_mode=color_mode,
        add_loop=False,
        loop_width=4.0,
        loop_length=8.0,
        loop_hole=2.5,
        loop_pos=None,
        modeling_mode=core_modeling_mode,
        quantize_colors=quantize_colors,
        enable_cleanup=enable_cleanup,
        hue_weight=hue_weight,
        chroma_gate=chroma_gate,
    )

    return {
        "threemf_path": threemf_path,
        "status_msg": status_msg,
    }


def worker_generate_model(
    image_path: str,
    lut_path: str,
    params: dict,
) -> dict:
    """Execute 3MF model generation in a worker process.
    在工作进程中执行 3MF 模型生成。

    Calls ``core.converter.generate_final_model`` with the supplied
    parameters and returns a dict containing the output file paths.

    Args:
        image_path (str): Path to the input image file. (输入图像文件路径)
        lut_path (str): Path to the LUT calibration file (.npy/.npz). (LUT 校准文件路径)
        params (dict): Dict of scalar parameters forwarded to
            ``generate_final_model`` via **kwargs. Keys must match the
            function signature (e.g. target_width_mm, spacer_thick,
            color_mode, modeling_mode, etc.). (标量参数字典，通过 **kwargs
            转发给 generate_final_model)

    Returns:
        dict: Result dictionary with keys: (结果字典，包含以下键)
            - threemf_path (str | None): Path to the generated .3mf file.
            - glb_path (str | None): Path to the generated .glb preview file.
            - status_msg (str): Status message from the converter.
    """
    # Lazy imports — executed inside the worker process
    from core.converter import generate_final_model

    result_tuple = generate_final_model(
        image_path=image_path,
        lut_path=lut_path,
        **params,
    )

    # generate_final_model returns:
    # (3mf_path, glb_path, preview_image, status_message, recipe)
    threemf_path, glb_path, _preview, status_msg, _recipe = result_tuple

    return {
        "threemf_path": threemf_path,
        "glb_path": glb_path,
        "status_msg": status_msg,
    }
