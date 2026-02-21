# 示例 02：函数单一职责

```python
# 拆分为小函数
def export_model(request: ExportRequest):
    """导出协调函数"""
    _validate_export_request(request)
    if request.format == ExportFormat.THREE_MF:
        return _export_to_3mf(request)
    return _export_to_mesh_format(request)

def _export_to_3mf(request: ExportRequest):
    """3MF格式专用导出"""
    mesh = _generate_mesh(request)
    metadata = _build_metadata(request)
    return _write_3mf(mesh, metadata)

def _export_to_mesh_format(request: ExportRequest):
    """STL/OBJ格式导出"""
    mesh = _generate_mesh(request)
    if request.format == ExportFormat.STL:
        return _write_stl(mesh)
    return _write_obj(mesh)
```

```python
# 错误做法：所有逻辑混在一个函数
def export_model(format_str, model_data, quality, ...):
    if format_str == "3mf":
        ...
    elif format_str == "stl":
        ...
    ...
```
