# Skill Test Checklist

## 目的
这份文档用于手动测试 `agentic-workflow-reference` 的调用率和准确率。

建议做法：
- 先重启 Codex，确保新安装的 skill 已被发现。
- 尽量每条测试都在新线程里跑，减少上下文污染。
- 正样本和边界样本各跑两遍：
  - `Auto`：不提 skill 名，观察是否自然触发。
  - `Forced`：在开头加一句 `Use agentic-workflow-reference.`，观察 skill 本身的路由和输出质量。
- 负样本只跑 `Auto`，看是否误触发。

## 评分维度
- `invoked`：是否明显走了这套 skill，而不是直接跳去业务方案或 raw docs。
- `first_hop`：第一跳是否先从 `reference/MEMORY.md` 开始，再进入 `Topics` 或 `Projects`。
- `route_ok`：概念类问题是否先进 `Topics`，项目溯源类问题是否先进 `Projects`。
- `minimal_load`：是否只读了 1-3 张卡才继续，不是一上来就扫很多原文。
- `source_map_ok`：如果回到 raw docs，是否能对应到卡片里的 `Source Map`。
- `contract_ok`：输出是否仍然是 `navigation + pattern extraction + source map`，而不是直接变成业务设计方案。

## 最简粘贴模板
每测一条，就按下面格式贴给我：

```md
## Test ID
P1

## Mode
Auto

## Prompt
对比 Claude Code 和 Hermes 的 Harness Engineering，可复用到我自己的控制底座里的模式有哪些？

## Response
<把 Codex 的完整回复贴这里>

## Skill Signal
unknown
```

`Skill Signal` 不强求。
如果你看得到，就填：
- `explicitly mentioned agentic-workflow-reference`
- `mentioned MEMORY.md`
- `mentioned topics/projects`
- `unknown`

## 正样本
这些用来测调用率和准确率。

| ID | 中文 Prompt | 预期第一张卡 |
| --- | --- | --- |
| P1 | 对比 Claude Code 和 Hermes 的 Harness Engineering，可复用到我自己的控制底座里的模式有哪些？ | `reference/topics/harness-engineering.md` |
| P2 | 对比 Agentic-Content-Optimizer 和 OpenClaw 的 workflow orchestration，尤其是状态机、quality gates 和 refinement loop。 | `reference/topics/workflow-orchestration.md` |
| P3 | Claude Code 和 OpenClaw 在 context engineering 上最大的差别是什么？ | `reference/topics/context-engineering.md` |
| P4 | 跨 Claude Code、Hermes、OpenClaw 看，memory 和 retrieval 应该怎么分层？ | `reference/topics/memory-and-retrieval.md` |
| P5 | 我自己的系统里 control plane、runtime、business workflow 的边界怎么划？先从参考资料里提炼可复用模式。 | `reference/topics/control-plane-and-runtime-boundaries.md` |
| P6 | Claude Code 的 subagent 和 Hermes 的协作方式对比一下，多 agent delegation 怎么设计更稳？ | `reference/topics/multi-agent-and-delegation.md` |
| P7 | Tools、Skills、MCP、Plugins 这一层应该怎么分工？请结合 Claude Code 和 OpenClaw。 | `reference/topics/tools-skills-and-mcp.md` |
| P8 | 从这些项目里总结一下 safety、permission、constraint 应该放在哪些层。 | `reference/topics/safety-and-constraints.md` |
| P9 | Hermes 的 closed-loop learning 有哪些值得借鉴的地方？先停留在可复用模式层。 | `reference/topics/closed-loop-learning.md` |
| P10 | 如果我想看 Claude Code 的 memory system，在这个知识库里应该先读哪里？ | `reference/projects/claude-code.md` |
| P11 | OpenClaw 的 gateway 和 control plane 具体对应哪些文档？先给我正确阅读路径。 | `reference/projects/open-claw.md` |
| P12 | ACO 里 business loop 和 three-loop boundary 分别在哪几篇？先给我导航。 | `reference/projects/agentic-content-optimizer.md` |
| P13 | Hermes 里 session search 和 experience replay 相关内容，应该先看哪几篇？ | `reference/projects/hermes-agent.md` |

## 边界样本
这些用来测“会不会轻微越界”。

| ID | 中文 Prompt | 预期行为 |
| --- | --- | --- |
| B1 | 我想设计一个 Agentic Workflow 控制底座，你先给我三种可选架构。 | 可以调用 skill 做参考，但输出应停留在参考模式层，不能把知识库本身伪装成直接业务方案。 |
| B2 | 我想知道 agent loop runtime 和 workflow orchestration 的边界；如果 topic 太宽，也请告诉我该怎么拆。 | 应先进父主题，再提到 `agent-loop-runtime` 是优先二级拆分候选。 |

## 负样本
这些用来测误触发率。

| ID | 中文 Prompt | 预期行为 |
| --- | --- | --- |
| N1 | 把 `reference/topics/workflow-orchestration.md` 翻译成中文。 | 不该触发这个 skill；这是翻译任务。 |
| N2 | 帮我写一个 PowerShell 脚本，扫描重复文件。 | 不该触发这个 skill；这是脚本任务。 |
| N3 | 解释一下 Python 里的 `dataclass`。 | 不该触发这个 skill；这是通用编程问题。 |
| N4 | 今天北京天气怎么样？ | 不该触发这个 skill；这和知识库无关。 |

## 建议通过线
- 正样本 `Auto` 调用率：`>= 70%`
- 负样本 `Auto` 误触发率：`<= 10%`
- 正样本 `Forced` 的 `route_ok`：`>= 90%`
- 正样本 `Forced` 的 `minimal_load`：`>= 85%`
- 正样本 `Forced` 的 `source_map_ok`：`>= 90%`
- 正样本和边界样本 `Forced` 的 `contract_ok`：`>= 85%`

## 结果记录表
手动记录时，用 `1` 表示通过，`0` 表示不通过。

| ID | Mode | invoked | first_hop | route_ok | minimal_load | source_map_ok | contract_ok | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1-P13 | Auto |  |  |  |  |  |  |  |
| P1-P13 | Forced |  |  |  |  |  |  |  |
| B1-B2 | Auto |  |  |  |  |  |  |  |
| B1-B2 | Forced |  |  |  |  |  |  |  |
| N1-N4 | Auto |  |  |  |  |  |  |  |
