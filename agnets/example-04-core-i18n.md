# 示例 04：core 层 i18n 规范

```python
# 正确做法：返回 i18n 标签
from utils.i18n_help import make_status_tag

def process_image(image_path: str) -> str:
    try:
        result = _do_process(image_path)
        return make_status_tag(
            "success.process_complete",
            pixels=result.pixel_count,
            duration=result.duration,
        )
    except FileNotFoundError:
        return make_status_tag("error.file_not_found", path=image_path)
    except Exception as e:
        return make_status_tag("error.process_failed", detail=str(e))
```

```python
# 错误做法：直接返回中英文字符串
def process_image(image_path: str) -> str:
    try:
        result = _do_process(image_path)
        return f"处理完成，共 {result.pixel_count} 像素，耗时 {result.duration} 秒"
    except FileNotFoundError:
        return f"文件未找到: {image_path}"
```

```python
# UI 层解析标签
from utils.i18n_help import resolve_i18n_text

def on_process_click(image_path):
    status_tag = process_image(image_path)
    status_text = resolve_i18n_text(status_tag, lang="zh")
    gr.Info(status_text)
```
