# 示例 05：新模块组织规范

```text
core/
  new_feature.py          # 核心业务逻辑
  new_feature_core.py     # 核心算法
ui/
  new_feature_ui.py       # UI辅助函数
  tabs/
    new_feature_tab.py    # Gradio界面
  static/
    css/
      new_feature.css     # 样式（通过文件路径引用）
    libs/
      some_lib/           # 第三方库（通过文件路径引用）
  assets/
    js/
      new_feature.js      # JS代码片段（读取为字符串）
    template/
      new_feature.html    # 模板文件（读取为字符串）
```

```text
# 错误做法：所有代码混在一个文件
# ui/layout_new.py (再增加500行...)
# core/converter.py (再增加300行...)
```
