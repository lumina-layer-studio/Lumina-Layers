## 2026-02-11 Task 5: layout_new.py 小步结构化重构

- 决策：仅做结构清晰化（区域注释与分组），不调整函数顺序依赖关系，不改动业务逻辑。
- 决策：保留 `create_app()` 内部回调函数在原作用域位置，仅通过分区注释显式标注“语言主题”“设置统计”等回调区域，避免闭包变量绑定风险。
- 决策：为 `with gr.TabItem(...)` 每个 Tab 增加统一分隔注释，明确 tab 顺序与职责，降低后续维护时的定位成本。
- 决策：在事件绑定入口增加 `Global Event Bindings` 区域注释，保留既有 wiring 顺序，确保 AST 结构测试稳定通过。
- 决策：helper 区域按 LUT 设置与图像尺寸两类分组；`HEADER_CSS`、`LUT_GRID_CSS`、`PREVIEW_ZOOM_CSS`、`LUT_GRID_JS`、`PREVIEW_ZOOM_JS` 继续保持模块顶部可见性。

## 2026-02-11 Task 6: 最小联动依赖校准与回归收口

- 决策：为满足 API 契约验证命令 `from ui import main, layout_new`，在 `ui/__init__.py` 增加最小导出联动（暴露 `layout_new` 与 `main`），不触碰 `ui/layout_new.py` 业务实现。
- 决策：保留既有 `create_app` 直出能力，同时将 `__all__` 扩展为 `create_app/layout_new/main`，仅修复导入可见性，不改变运行行为。
- 结论：unit/integration/e2e 三条门禁均通过；保留现有 Gradio 相关 warnings 作为已知非阻塞项记录在收口日志。
