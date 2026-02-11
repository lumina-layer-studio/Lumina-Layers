## 2026-02-11 Task 2 测试经验

- `-k "layout_new and (app or tab or structure)"` 对测试命名敏感，新增用例需在函数名里显式包含 `layout_new` 与结构关键词，避免被全部 deselect。
- 在当前环境缺少 `gradio` 时，`create_app()` 运行时结构测试不稳定；用 AST 表征测试可以直接冻结 tab 顺序、`I18n.get()` 标签来源和 click wiring。
- `create_app()` 的事件处理函数定义在函数内部且位于 `with` 语句块内，提取时要用 `ast.walk()`，不能只看 `create_app.body` 的顶层节点。
