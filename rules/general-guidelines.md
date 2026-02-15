## General Guidelines

- 所有面向用户显示的文案（按钮、标签、状态提示、错误提示、占位文本等）必须先在 `core/i18n.py` 中定义条目，再在代码中通过 `I18n.get(...)` 获取；禁止在 UI/业务逻辑中直接硬编码可见文本。
- `core/` 层禁止直接调用 `I18n.get(...)` 返回最终文案；若返回值会在前端显示，必须返回 i18n 标签（如 `__i18n__:<key>|<json>`），并在 `ui/` 层统一解析后再显示。
- Gradio 单选框（`Radio`）涉及业务枚举值时，`choices` 的 value 必须使用 `Enum.value`；后端入口收到前端参数后必须第一时间转换为对应 `Enum`，后续流程统一用 `Enum` 判断，禁止继续用字符串包含/相等判断。

### Skill Loading (Mandatory)

- 涉及 i18n 文案链路（新增/修改按钮、状态文案、错误提示、core->ui 返回文案）时，必须先加载并遵循：`.agents/skills/i18n-status-bridge/SKILL.md`。
- 未加载该 skill 前，不得改动 `core/` 与 `ui/` 的文案传递逻辑。
- 若当前任务仅为纯算法/纯数据处理且不影响用户可见文本，可不加载该 skill。
