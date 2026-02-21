# 示例 06：数据类封装参数

```python
from dataclasses import dataclass

@dataclass
class ConversionRequest:
    """统一的转换请求参数"""
    image_path: str
    lut_path: str
    color_mode: ColorMode
    modeling_mode: ModelingMode
    color_detail: int = 64
    blur: float = 0.0
    smooth: float = 0.0

def convert_image_to_3d(request: ConversionRequest):
    """使用数据类作为参数"""
    ...
```
