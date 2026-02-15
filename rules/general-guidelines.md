## General Guidelines

- Gradio 单选框（`Radio`）涉及业务枚举值时，`choices` 的 value 必须使用 `Enum.value`；后端入口收到前端参数后必须第一时间转换为对应 `Enum`，后续流程统一用 `Enum` 判断，禁止继续用字符串包含/相等判断。

### Skill Loading (Mandatory)

- 涉及 i18n 文案链路（新增/修改按钮、状态文案、错误提示、core->ui 返回文案）时，必须先加载并遵循：`.agents/skills/i18n-status-bridge/SKILL.md`。
- 未加载该 skill 前，不得改动 `core/` 与 `ui/` 的文案传递逻辑。
- 若当前任务仅为纯算法/纯数据处理且不影响用户可见文本，可不加载该 skill。
