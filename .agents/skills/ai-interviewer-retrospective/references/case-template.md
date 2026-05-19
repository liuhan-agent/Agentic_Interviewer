# Retrospective Case Template

Use this template for files written under `docs/learning-cases/`.

```markdown
# <问题标题>

> 日期：YYYY-MM-DD
> 状态：draft
> 标签：ai-interviewer, <logic|boundary|llm-runaway|prompt|tooling|debugging>

## 一句话结论

<用一句话说明这次问题的核心教训。>

## 背景

<说明当时在开发、调试或验证 AI 面试官的哪个部分。>

## 现象

### 事实

- <已经确认发生了什么。>

### 推断

- <基于证据推断但尚未完全证明的判断。>

### 未确认假设

- <需要继续验证的假设。>

## 期望行为

<说明理想情况下系统或 Agent 应该如何表现。>

## 复现线索

- 输入/场景：<候选人回答、用户操作、API 输入或测试场景>
- 相关命令：`<command>`
- 相关日志/trace：<路径或摘要>
- 相关文件：<路径列表>

## 根因判断

<区分直接原因、深层原因和触发条件。证据不足时明确写“暂未确认”。>

## 调试过程

1. <第一步观察或实验。>
2. <第二步定位或排除。>
3. <最终确认或当前停留点。>

## 解决方式

<写清已经采取的修复、临时绕过，或者为什么暂时没有修。>

## 验证方式

- <测试、手动验证、日志确认或尚未验证。>

## 可复用教训

- <以后遇到类似问题时，值得优先检查什么。>
- <需要警惕的 LLM 行为、边界条件或工程假设。>

## 未解问题

- <仍需要后续确认的问题。>

## Source Map

- 代码：<file paths>
- 日志/trace：<file paths or summaries>
- 对话/输入：<brief source description>
```
