---
name: i18n-status-bridge
description: 所有面向用户显示的文案（按钮、标签、状态提示、错误提示、占位文本等）需要遵循本技能
allowed-tools: Read, Grep, Edit, Write, Bash, LSP
---

# i18n-status-bridge

## 目标
确保 Lumina Studio 的用户可见文案遵循统一模式：

1. 文案定义在 `core/i18n.py`
2. `core/` 不直接返回最终文案
3. `ui/` 统一解析并展示本地化文本

## 何时必须加载
- 新增或修改按钮/标签/状态提示/错误提示/占位文本
- 修改 `core -> ui` 返回的状态字符串
- 处理批量流程日志或多行状态提示

## 当前代码中的既有模式（必须复用）

### Pattern A: core 层生成 i18n tag（不做翻译）
- 文件：`utils/i18n_help.py`
- API：`make_status_tag(key: str, **kwargs) -> str`
- 格式：`__i18n__:<key>` 或 `__i18n__:<key>|<json>`

示例（来自 `core/extractor.py`）：
```python
if img is None:
    return None, None, None, make_status_tag("msg_no_image")
```

### Pattern B: ui 层统一解析 tag 并展示
- 文件：`utils/i18n_help.py`
- API：`resolve_i18n_text(value, lang)`
- 支持：
  - 单条 tag
  - 带参数 tag（`text.format(**args)`）
  - 多行文本逐行解析

示例（来自 `ui/callbacks.py`）：
```python
return vis, prev, lut_path, resolve_i18n_text(status, lang)
```

### Pattern C: 纯 UI 文案直接 `I18n.get(...)`
- 仅用于 UI 组件 label/value/info 或纯 UI 事件提示
- 不把 `core` 业务状态翻译逻辑放到 `core`

## 强制规则
1. 所有新增用户可见文案 key 必须先加到 `core/i18n.py`。
2. `core/` 返回给前端显示的状态，必须是 `make_status_tag(...)`。
3. `ui/` 接收 `core` 状态后，必须经 `resolve_i18n_text(...)` 再显示。
4. 禁止在 `core/` 里硬编码中文/英文最终文案。
5. 禁止重复实现 tag 解析逻辑（统一走 `utils/i18n_help.py`）。

## 开发步骤（执行顺序）
1. 在 `core/i18n.py` 增加 key（中英文都要有）
2. 在 `core/` 用 `make_status_tag("new_key", **params)` 返回
3. 在 `ui/` 回调出口调用 `resolve_i18n_text(status, lang)`
4. 对纯 UI 静态文案用 `I18n.get("new_key", lang)`

## Do / Don't

### Do
- `core`: `return ..., make_status_tag("conv_xxx", error=str(e))`
- `ui`: `msg = resolve_i18n_text(status, lang)`
- `i18n`: `{ "conv_xxx": {"zh": "...{error}", "en": "...{error}"} }`

### Don't
- `core`: `return ..., I18n.get("conv_xxx", lang)`
- `core`: `return ..., "❌ 处理失败"`
- `ui`: 手写 `if status.startswith("__i18n__:")` 的重复解析

## 提交前检查清单
- [ ] 新文案 key 已加入 `core/i18n.py`（zh/en 完整）
- [ ] `core/` 无新增硬编码可见文案
- [ ] `core/` 返回状态使用 `make_status_tag`
- [ ] `ui/` 展示前调用 `resolve_i18n_text`
- [ ] 相关回调链路跑通（至少单测/核心流程）

## 参考文件
- `core/i18n.py`
- `utils/i18n_help.py`
- `core/converter.py`
- `core/extractor.py`
- `ui/callbacks.py`
- `ui/tabs/converter_tab.py`
