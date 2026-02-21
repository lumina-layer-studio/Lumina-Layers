# 示例 01：新增功能时使用枚举

```python
# 定义枚举
class ExportFormat(str, Enum):
    STL = "stl"
    OBJ = "obj"
    THREE_MF = "3mf"

# Gradio组件使用枚举
format_radio = gr.Radio(
    choices=[ExportFormat.STL, ExportFormat.OBJ, ExportFormat.THREE_MF],
    value=ExportFormat.THREE_MF,
    label="导出格式"
)

# 后端入口转换
def export_handler(format_str: str, model_data):
    export_format = ExportFormat(format_str)  # 字符串->枚举
    if export_format == ExportFormat.THREE_MF:
        return export_to_3mf(model_data)
    ...
```

```python
# 错误做法：字符串判断
def export_handler(format_str: str, model_data):
    if format_str == "3mf":
        ...
    if "3mf" in format_str:
        ...
```
