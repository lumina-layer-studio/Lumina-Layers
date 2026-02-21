# 示例 07：提取重复逻辑

```python
# 错误做法：重复代码
def func_a():
    if not os.path.exists(path):
        return make_status_tag("error.file_not_found", path=path)
    ...

def func_b():
    if not os.path.exists(path):
        return make_status_tag("error.file_not_found", path=path)
    ...
```

```python
# 正确做法：提取公共逻辑
def _ensure_file_exists(path: str):
    if not os.path.exists(path):
        return make_status_tag("error.file_not_found", path=path)
    return None

def func_a():
    error = _ensure_file_exists(path)
    if error:
        return error
    ...

def func_b():
    error = _ensure_file_exists(path)
    if error:
        return error
    ...
```
