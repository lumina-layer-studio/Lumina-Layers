# 基本设定
- 使用中文作为交互语言
- 对文件修改要最小化 不要修改不必要的部分 不要进行格式化
- 如果你测试运行中发生编码错误，你要通过调整执行环境的编码来解决而不是去修改代码

# python设定
- 已经安装了uv工具
# 控制台设定
- 使用utf8控制台编码

## General Guidelines
- Gradio 单选框（`Radio`）涉及业务枚举值时，`choices` 的 value 必须使用 `Enum.value`；后端入口收到前端参数后必须第一时间转换为对应 `Enum`，后续流程统一用 `Enum` 判断，禁止继续用字符串包含/相等判断。
- 在修改代码后运行测试
- 在ui上添加按钮后添加相关测试

### Skill Loading (Mandatory)

- 涉及 i18n 文案链路（新增/修改按钮、状态文案、错误提示、core->ui 返回文案）时，必须先加载并遵循：`.claude/skills/i18n-text/SKILL.md`。
- 未加载该 skill 前，不得改动 `core/` 与 `ui/` 的文案传递逻辑。
- 若当前任务仅为纯算法/纯数据处理且不影响用户可见文本，可不加载该 skill。
- 涉及测试相关工作（编写测试、修改测试、运行测试、调试测试失败）时，必须先加载并遵循：`.claude/skills/testing-framework/SKILL.md`。
 

