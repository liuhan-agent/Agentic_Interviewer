# ask_question 上下文治理复盘

> 日期：2026-05-31
> 状态：draft
> 标签：ai-interviewer, ask_question, context-governance, prompt-slots, trace-explorer, rag, observability

## 一句话结论

这套上下文治理的核心不是“把内容压缩到模型上下文窗口里”，而是把完整事实源转换成结构化、可控、可诊断的 prompt-facing working set：明确什么内容值得进入 `ask_question` prompt、以什么形态进入、来自哪里、是否被运行时裁剪，以及 Trace 里看到的截断到底是运行时裁剪还是 UI 预览截断。

## 背景

本次复盘发生在 `Trace Explorer / ask_question` 上下文治理改造之后。改造前后，系统经历了几个容易混淆的阶段：

- workflow 节点语义从 `compress_context` 迁移到 `turn_finalize`。
- `qa_history` 从“可能被收尾节点压缩的上下文”重新定义为完整事实源。
- `ask_question` 前引入 `HistoryContextBuilder`，把历史问答投影为 3 个 prompt slots。
- `ask_question` 的实际 prompt 注入内容被拆成 10 个 slots，并在 Trace Explorer 中可见。
- Strategy / Skill 引入基于 generator model context window 的动态预算和 slot 内裁剪诊断。
- Candidate Anchor / Resume RAG / Self Intro RAG 引入运行时裁剪诊断和更细的检索诊断。
- Trace Explorer 区分 `runtime_truncated` 和 `trace_text_truncated`，避免把 UI 预览截断误判为真正 prompt 被裁剪。

用户在复盘中提出了一个关键质疑：既然 `deepseek-v4-flash` 等模型上下文窗口很大，12 轮问答最后一轮也大概率远低于 256K tokens，那么这套上下文裁剪、压缩、预算体系是不是过度工程化。最终讨论把问题重新定位为“Prompt Ledger / Context Governance”，而不是“大上下文模型下的压缩工程”。

## 证据边界

### 已确认的一手或近一手证据

- 当前工作区源码，特别是 `history_context.py`、`prompt_budget.py`、`ask_question.py`、`session_anchor_retriever.py`、`resume_embedding.py` 和 `TraceExplorer.tsx`。
- 当前延续线程中用户提供的完整上下文摘要和多轮验收记录。
- 可读到的相关 Codex 线程：
  - `codex://threads/019e7c64-f9e6-7dd2-8343-887e88416e25`，标题为“优化 ask_question 上下文治理”。
  - `codex://threads/019e7c80-3064-7b20-976d-862cdd5266e5`，标题为“排查上下文治理问题”。
- 用户给出的验收 session：
  - `sess-20260531-015658-6f761c`
  - `sess-20260531-050315-551323`
  - `sess-20260531-073212-4d88b7`
  - `sess-20260531-084534-214e4a`

### 缺失证据

- 用户指定的 `codex://threads/019e5804-9db9-7061-8aeb-916b8314eb2a` 在本次检索中未能读取到。按 thread id 和“上下文治理”关键词检索时，该精确线程没有出现在可访问结果里。
- 因此，本文中关于早期决策来源的内容主要来自当前延续线程的整理、可读到的相关线程，以及源码交叉验证。涉及原始早期会话动机的部分需要标为“基于转述和源码的复原”。

## 现象

### 事实

- 真实 workflow 节点语义已经从 `compress_context` 迁移为 `turn_finalize`。
- `compress_context` 保留为轻量兼容入口，不再承担 LLM 压缩历史上下文的主责。
- `turn_finalize` 属于每轮 `reward_update` 之后、`route_decision` 之前的轮次收尾节点。
- `route_decision` 不是 workflow node，而是 `route_after_eval` 条件边的诊断 trace。
- `qa_history` 保持完整事实源，不由 `turn_finalize` 或 `compress_context` 做 LLM 压缩。
- `ask_question` 前由 `HistoryContextBuilder` 构建历史上下文。
- 历史上下文被拆成 3 个 prompt slots：
  - `INTERVIEW_HISTORY_SUMMARY`
  - `RECENT_QA`
  - `CURRENT_GAPS`
- `ask_question` 的完整 prompt slot 口径为 10 个：
  - 历史上下文 3 槽：`INTERVIEW_HISTORY_SUMMARY`、`RECENT_QA`、`CURRENT_GAPS`
  - 出题资料 7 槽：`RETRIEVED_KNOWLEDGE`、`STRUCTURED_QUESTION_SEED`、`CANDIDATE_ANCHOR`、`CANDIDATE_RESUME_RAG`、`SELF_INTRO_RAG`、`STRATEGY_MEMORY`、`INTERVIEW_SKILLS`
- 历史预算从 6000 chars 调整到 8000 chars。
- 最近 QA 默认保留 3 轮。
- 预算不紧张时，最近 QA 的问题和回答尽量不做字段级裁剪。
- 超预算时只能缩 prompt view 或 recent view，不能修改 `qa_history` 原文。
- Strategy / Skill 已有 slot-aware、rank-aware 的运行时裁剪诊断。
- Candidate Resume RAG / Self Intro RAG 已有按 hit 裁剪和 runtime diagnostics。
- Candidate Anchor 已补字段级裁剪诊断。
- `STRUCTURED_QUESTION_SEED` 暂不做复杂裁剪诊断，取 rank 1 注入。
- Trace Explorer 中需要区分：
  - `runtime_truncated`：真实进入 Generator prompt 前发生的裁剪。
  - `trace_text_truncated`：Trace 展示文本的 2000 chars 预览截断。
- `deepseek-v4-flash` 已加入模型上下文窗口 mapping，预期：
  - `context_window_tokens = 1024000`
  - `budget_level = expanded`
  - `fallback_used = false`
  - `strategy_budget_chars = 4800`
  - `skill_budget_chars = 5200`

### 推断

- “上下文治理”一词如果继续被理解成“压缩上下文”，会误导后续设计，因为目前 12 轮面试最后一轮的 generator input 很可能远低于 256K tokens，更不接近 1M tokens。
- 当前工程真正解决的是 prompt 输入的职责划分、优先级、可观察性和故障定位，而不是单纯节省 token。
- Strategy / Skill 的动态预算不是为了在 1M 窗口里尽量塞满，而是为了让小窗口、未知模型、国内模型 mapping、未来 provider 切换时都能保持稳定行为。
- 历史 3 槽不是普通的“slot 内裁剪层”，而是从完整历史事实源到 prompt view 的确定性结构化投影。
- 出题资料 7 槽里的大多数 slot 保持 slot 内裁剪是合理的，因为这些 slot 的价值不只在于 token 控制，还在于噪声控制、证据边界、Trace 诊断和候选材料优先级。

### 未确认假设

- `codex://threads/019e5804-9db9-7061-8aeb-916b8314eb2a` 中可能包含更早的命名、方案反复和错误路径。由于本次无法读取，本文无法完整复原早期讨论细节。
- 12 轮最后一轮 `ask_question` 的真实 token 用量需要用生产 trace 或 generator provider 的 token usage 字段持续确认。当前“远低于 256K”的判断来自 prompt slot chars、输出上限和会话分析的粗估。
- Candidate Anchor RAG 后续如果引入 hard wall-clock timeout 和 lexical fallback，现有诊断字段可能还要再扩展。

## 期望行为

理想状态下，`ask_question` 上下文治理应该做到：

- 完整事实源和 prompt view 分离。`qa_history` 记录事实，不被 prompt 压缩逻辑破坏。
- 每个进入 prompt 的信息都有明确 slot 名、来源、职责和优先级。
- 结构化题库 seed 是出题骨架，应优先保护。
- 候选人相关资料只提供短、准、可追踪的锚点，不把简历或自我介绍整段塞进 prompt。
- Strategy / Skill 是辅助策略信号，应按 rank 和动态预算注入，而不是无限扩张。
- 历史上下文不追求复述所有原文，而是投影出面试已覆盖内容、近期交互和当前缺口。
- Trace Explorer 用英文 workflow / trace key 作为一等公民，中文说明作为辅助。
- Trace Explorer 能回答三个问题：
  - 本轮到底注入了哪些 prompt slots。
  - 哪些内容真的在进入 Generator 前被裁剪了。
  - 哪些内容只是 UI 展示时被截断了。

## 核心治理模型

### 不是“塞进大上下文”

本次复盘中，一个重要转折是承认：在当前 12 轮面试规模下，最后一轮 generator input 大概率也只有数万 tokens 量级，远低于 256K。`deepseek-v4-flash` 的 1M context window 更多是安全边界，而不是当前设计的直接压力来源。

因此，上下文治理不能用“模型装不装得下”来证明价值。更合适的问题是：

- 这个内容是否值得进入 prompt。
- 它应该以事实原文、摘要投影、检索命中、策略提示还是诊断兼容块的形式进入。
- 它是否会挤压更关键的出题骨架。
- 它的来源和裁剪过程是否可解释。
- 出问题时能不能从 Trace 中定位是召回、排序、裁剪、绑定、网络，还是 UI 展示问题。

### 完整事实源与 prompt-facing working set

`qa_history` 是完整事实源。它的职责是保留每轮问答、评估、维度覆盖和后续分析所需的事实。它不应该被 `turn_finalize`、`compress_context` 或 prompt 裁剪逻辑改写。

`HistoryContextBuilder` 负责生成 prompt-facing working set。这个 working set 可以被预算限制，可以做摘要投影，可以裁剪展示，但不能反向污染事实源。

这个边界是整套治理的基础。如果 prompt view 和 fact source 混在一起，后续会出现两个风险：

- 为了让下一轮 prompt 更短而损坏长期事实。
- Trace 里看到的“摘要”被误认为系统真实保存的历史。

### 10 个 prompt slots 是 Prompt Ledger

10 个 prompt slots 的价值不是 UI 好看，而是把每一类上下文登记成可审计账本：

- `INTERVIEW_HISTORY_SUMMARY`：历史 QA 的结构化摘要投影，关注已问、已覆盖、表现、维度状态。
- `RECENT_QA`：最近几轮问答的 prompt 视图，保留局部对话连续性。
- `CURRENT_GAPS`：当前还没覆盖好的维度、能力缺口和需要追问的方向。
- `RETRIEVED_KNOWLEDGE`：legacy 通用知识库，当前更多是诊断和兼容角色。
- `STRUCTURED_QUESTION_SEED`：结构化题库选中的 seed / variant，是出题骨架。
- `CANDIDATE_ANCHOR`：候选人适配提示，告诉模型如何把题和候选人项目锚点结合。
- `CANDIDATE_RESUME_RAG`：简历 RAG 命中的资料块。
- `SELF_INTRO_RAG`：自我介绍 RAG 命中的资料块。
- `STRATEGY_MEMORY`：策略记忆命中内容。
- `INTERVIEW_SKILLS`：Skill playbook 命中内容。

这些 slot 共同回答“本轮生成问题时，系统到底给了模型什么材料”。

## 历史上下文 3 槽

### `INTERVIEW_HISTORY_SUMMARY`

这是历史 QA 的结构化摘要投影，不是压缩后的原文。它应该表达：

- 哪些维度已经问过。
- 候选人在这些维度上的表现如何。
- 哪些证据被认为有效。
- 哪些维度仍然缺乏覆盖。

它的价值是让模型理解面试进度，而不是重读全部历史。

### `RECENT_QA`

这是最近几轮问答的 prompt view。默认最近 3 轮。它提供短期对话连续性，让模型避免重复刚问过的问题，也能自然承接候选人刚刚提到的项目或细节。

关键边界：

- 默认保留 3 轮。
- 预算不紧张时尽量不裁剪问题和回答字段。
- 超预算时裁剪 prompt view，而不是裁剪 `qa_history` 原文。
- Trace 应能展示最近 QA 的 prompt view 和是否发生过 prompt 侧裁剪。

### `CURRENT_GAPS`

这是从历史评估和覆盖状态中投影出的当前缺口。它告诉生成器下一题应该优先补什么，而不是只基于当前题库 seed 或候选人材料盲目发散。

这也解释了为什么历史 3 槽不是简单 slot 内裁剪。它们是在做状态投影：

- 从事实源到面试进度。
- 从历史回答到维度覆盖。
- 从 evaluator 反馈到后续提问缺口。

## 出题资料 7 槽

### `STRUCTURED_QUESTION_SEED`

这是出题骨架。它决定了本轮题目的维度、题型、候选 seed / variant 和主要考察方向。

当前约定是取 rank 1 注入，暂不引入复杂运行时裁剪诊断。这个选择合理，因为 seed 本身应该短、结构化、优先级最高。对它做复杂裁剪会让系统更难判断题目到底是由哪个 seed 驱动的。

### `CANDIDATE_ANCHOR`

这是候选人适配提示。它不等同于简历全文，也不等同于 RAG hit 原文，而是告诉生成器如何把题目和候选人的项目、经验、技术栈锚定起来。

它适合做字段级裁剪诊断，因为 anchor 往往由多个字段组成，例如项目名、角色、证据、匹配理由、追问建议。字段级诊断可以帮助判断到底是哪一类信息被裁掉。

### `CANDIDATE_RESUME_RAG` 和 `SELF_INTRO_RAG`

这两个 slot 是候选人材料的证据块。治理目标不是“多给模型看材料”，而是给模型提供可控数量、可追踪来源、足够贴题的候选证据。

当前合理的治理方式是按 hit 裁剪：

- 每个 hit 有自己的 body budget。
- slot 总体有 runtime diagnostics。
- Trace 里能看到 hit 的来源、rank、是否注入、是否 runtime truncation。
- Resume 和 Self Intro 应有 source-aware 的 fetch / score / keep 诊断，避免某一类材料在早期 fetch 阶段被另一类材料挤掉。

### `STRATEGY_MEMORY` 和 `INTERVIEW_SKILLS`

这两个 slot 是策略与技巧信号。它们不是题目事实源，也不是候选人证据源，而是帮助生成器选择更好的提问策略、追问方式和评价意识。

因此它们适合动态预算和 rank-aware 裁剪：

- 小窗口或未知模型下收紧。
- 大窗口模型下进入 expanded。
- expanded 只代表更宽松的质量上限，不代表无限注入。
- 排名靠前的条目获得更多 body budget。
- 排名靠后的条目即使入选，也应更短。

### `RETRIEVED_KNOWLEDGE`

这是 legacy 通用知识库 slot。当前它更多承担兼容和诊断角色。在结构化题库 seed 命中正常时，它不应该喧宾夺主。

这个 slot 的存在提醒后续维护者：不能只看 prompt 中有没有“检索知识”，还要看检索知识的来源和职责。如果通用知识库内容开始影响出题骨架，就需要重新审查优先级。

## 动态预算的真实意义

`prompt_budget.py` 中的模型上下文窗口 mapping 和预算估算，表面上看是在解决 token 限制，实际更重要的是稳定行为：

- 未知模型走 fallback，避免误判窗口过大。
- 已知大窗口模型进入 expanded，给 Strategy / Skill 更宽预算。
- 国内模型 provider / model 名称被显式覆盖，减少因为模型别名导致的 fallback。
- protected prompt slots 会先被估算，辅助 slot 在剩余空间里决定预算级别。

会话中重点确认了 `deepseek-v4-flash`：

- 旧 session `sess-20260531-015658-6f761c` 中它仍走 fallback，原因是 mapping 当时还未补。
- 新 session 中应看到 `fallback_used = false`、`budget_level = expanded`。
- expanded 预算下 Strategy / Skill 分别为 4800 chars 和 5200 chars。

这里的“动态”不是每轮都让 slot 逼近模型最大窗口，而是让不同模型、不同 provider 和不同 prompt 压力下的行为可解释。

## Trace Explorer 的诊断边界

Trace Explorer 这次改造最重要的 UI 语义之一，是把真实运行时裁剪和展示预览截断拆开：

- `runtime_truncated`：内容在进入 Generator prompt 前已经被裁剪。这会影响模型看到什么。
- `trace_text_truncated`：Trace Explorer 为了展示，最多预览约 2000 chars。这不会影响模型看到什么。

如果这两个概念混在一起，会出现严重误判：

- 用户看到 Trace 中文本结尾被截断，以为模型没看到完整内容。
- 用户看到 `truncated` 字段，以为是 prompt budget 生效，实际只是 UI 预览限制。
- 后续排查会错误地去调 prompt budget，而不是查看 Trace 展示层。

因此 UI 里节点名和 slot key 应以英文 workflow / trace key 为一等公民，中文说明只做辅助解释。

## Candidate Anchor RAG 插曲

Candidate Anchor RAG 是本次上下文治理中最典型的“上下文质量不是 token 问题”的案例。

### 第一阶段：新 session 发现 Anchor RAG 不生效

在 `sess-20260531-050315-551323` 中，新的上下文治理主体已经通过：

- workflow trace 是 `ask_question -> evaluator -> verification -> turn_finalize -> route_decision`。
- 没有真实 `compress_context` 节点。
- 12/12 轮 `prompt_budget_diagnostics` 显示 `deepseek-v4-flash` 已识别为 expanded。
- 历史上下文正常：`source_qa_count` 随轮次增加，recent QA 默认 3，history budget 8000，没有污染 `qa_history`。
- 10 个 prompt slots 每轮可见。

但 Candidate Anchor RAG 失败：

- 12/12 轮 `status = primary` 但 `fallback_reason = timeout`。
- 每轮 latency 约 19.6s 到 22s。
- 没有 hits，也没有注入候选锚点资料。
- Resume vector state 显示 ready / cache hit / chunk_count 24，但当前 session 没有绑定 chunks。
- Self intro vector 侧出现 SSL EOF。

当时的判断是两层问题：

- 查询 embedding timeout 是 Qwen `text-embedding-v4` 的网络或服务问题，不是 DeepSeek generator 调用问题。
- cache-hit 后当前 session 无 chunks 是另一个数据一致性问题，不能完全甩给网络。

### 第二阶段：绑定校验和 timeout 诊断修复

后续修复方向：

- 在 `ask_question.py` 中，RAG 前先验证 session anchor binding。
- 如果 cache-hit / ready 但当前 session 缺少 chunks，先尝试 rebind。
- 如果 rebind 失败，返回 `session_anchor_bind_missing`，不要继续调用 embedding。
- 在 `session_anchor_retriever.py` 中，先查 DB rows，再做 query embedding。
- 没有 rows 时返回 `no_bound_chunks`。
- rows 存在但 query embedding 超时时返回 `query_embedding_timeout`。
- Query hot path 中 `embed_query` 不做多次重试，避免每轮卡 20 秒。
- Trace Explorer 显示 `bind_validation.*` 和 fallback reason。

这次修复后的目标不是让网络一定成功，而是让失败原因变得可诊断，并避免无意义的热路径等待。

### 第三阶段：self-intro chunks 没进 top hits

在 `sess-20260531-073212-4d88b7` 中，Candidate Anchor RAG 基本恢复：

- 5 轮 ask_question 都是 `status = primary`。
- fallback 为 null。
- `bind_validation` 为 true。
- `bound_count = 29`，其中 resume 24、self_intro 5。
- 没有 `query_embedding_timeout`、`session_anchor_bind_missing` 或 `no_bound_chunks`。

但问题变成：self-intro 有 5 个 chunks，却没有进入 top hits。

基于源码和诊断，推断根因不是最终 top-k 只偏向 resume，而是更早的 `_fetch_rows` 阶段使用混合 source 的全局 limit，且缺少 source quota。由于 resume chunks 插入较早且数量更多，fetch 阶段可能只拿到 resume rows，self_intro 根本没有进入 scoring。

修复方向：

- resume rows 按 `top_k_resume + buffer` 获取。
- self_intro rows 按 `top_k_self_intro + buffer` 获取。
- 增加 `fetched_rows_by_source`、`scored_rows_by_source`、`kept_hits_by_source` 诊断。
- Trace Explorer 展示这些 source-aware diagnostics。
- 添加回归测试，覆盖 resume rows 支配时 self_intro 仍能进入 scoring 的场景。

### 第四阶段：source quota 修复后验收

在 `sess-20260531-084534-214e4a` 中：

- Candidate Anchor RAG 每轮 `status = primary`。
- fallback 为 null。
- 没有 no bound、session anchor bind、query timeout 问题。
- `bind_validation` 显示 total 29、resume 24、self_intro 5。
- 每轮 `fetched_rows_by_source = {resume: 10, self_intro: 5}`。
- 每轮 `kept_hits_by_source = {resume: 2, self_intro: 1}`。
- `CANDIDATE_RESUME_RAG` 和 `SELF_INTRO_RAG` 都 5/5 注入。

这说明 Candidate Anchor RAG 的“召回资料是否进入 prompt”已经恢复。

残留问题是 latency：

- 每轮 Candidate Anchor RAG latency 仍约 10.5s 到 11.3s。
- 默认 query timeout 仍是 3s，但当前观察说明这个 timeout 不是严格 wall-clock。
- 主要慢点大概率在 Qwen query embedding，可能包括 anchor query 和 boost query。
- DB fetch / scoring 本身数据量很小，不像主要耗时来源。

该问题当时决定暂缓，不继续改造。后续如果处理，优先方向不应是让每轮都完全降级，而是：

- 保持 `ask_question` 热路径有硬超时。
- Trace 中把 `query_embedding_timeout` 单独标出来。
- 已有 query embedding cache 命中时优先用 cache。
- 超时后可退到 local lexical / source quota fallback，而不是让 Candidate Anchor RAG 完全失效。
- 可考虑一次短重试，但不能让每轮都卡 20 秒。

## Prompt cache 的判断

用户曾考虑为 `ask_question` 做 prompt cache。复盘后的判断是：自建 prompt cache 对当前 `ask_question` 的价值有限。

原因：

- 每轮出题维度会变。
- 结构化题库 seed / variant 会变。
- Candidate Anchor 会跟随本轮 seed、dimension、query profile 变化。
- Resume RAG / Self Intro RAG top hits 会变。
- `INTERVIEW_HISTORY_SUMMARY`、`RECENT_QA`、`CURRENT_GAPS` 每轮都会变化。
- Strategy / Skill 命中也可能随维度和上下文变化。

真正稳定的主要是系统提示词、格式要求和部分 JSON schema。如果 provider 自动做 prefix cache，可以顺手受益；但不值得优先做复杂的应用层 prompt cache。

更值得优化的方向是：

- embedding 查询延迟。
- evaluator fallback / provider routing。
- Candidate Anchor RAG 超时后的本地降级策略。
- Trace 诊断精度。
- 问题质量和覆盖调度。

## 与 evaluator fallback 的边界

会话中还出现过“评分仅供参考，本场约 83% 的回答走了保守评分路径”的现象。复盘中需要明确：这不是上下文治理本身导致的。

相关线程显示：

- 出题与追问使用 DeepSeek `deepseek-v4-flash` 成功。
- 反馈与提升计划使用 DeepSeek 成功。
- evaluator 曾因 role override 或 provider route 问题走到默认 Qwen `qwen3.6-flash`。
- Qwen 网络或服务错误导致 evaluator fallback。
- Self-intro parser / embedding 侧也出现过 Qwen 或 DashScope 网络相关错误。

这些问题会影响维度覆盖判断和后续调度。例如 evaluator fallback 证据不够可靠时，系统可能保守地重复覆盖某些维度，导致 5 轮面试没有覆盖完所有目标维度。但这属于 evaluator/provider routing 和可靠性问题，不应混同为 prompt slot 治理失败。

## 调试过程复原

1. 先确认 workflow / trace 节点语义，避免继续把 `compress_context` 当作真实工作流节点。
2. 确认 `turn_finalize` 是轮次收尾节点，位置在 `reward_update` 后、`route_decision` 前。
3. 把 `qa_history` 固定为完整事实源，不再由上下文收尾节点做 LLM 压缩。
4. 引入 `HistoryContextBuilder`，把历史上下文投影为 3 个 prompt slots。
5. 把 `ask_question` 实际注入资料统一为 10 个 prompt slots。
6. 给 Strategy / Skill 增加动态预算、rank-aware 裁剪和 runtime diagnostics。
7. 给 Candidate Resume RAG / Self Intro RAG 增加按 hit 裁剪诊断。
8. 给 Candidate Anchor 增加字段级裁剪诊断。
9. 在 Trace Explorer 中拆分 `runtime_truncated` 和 `trace_text_truncated`。
10. 新跑 `sess-20260531-050315-551323`，确认 DeepSeek expanded 生效，同时发现 Candidate Anchor RAG timeout 和 session chunk binding 不一致。
11. 修复 binding validation、query timeout fallback reason 和 Trace 展示。
12. 新跑 `sess-20260531-073212-4d88b7`，确认 binding 恢复，同时发现 self-intro chunks 被 resume rows 挤出 fetch 阶段。
13. 修复 source quota fetch 和 source-aware diagnostics。
14. 新跑 `sess-20260531-084534-214e4a`，确认 resume/self-intro 都进入 hits 和 prompt slots。
15. 识别 Candidate Anchor RAG latency 仍高，但暂缓处理。
16. 最后回到“上下文治理是否过度工程化”的概念复盘，重新定义其价值边界。

## 解决方式

已完成或已确认完成的方向：

- workflow / trace 语义重命名和 UI 口径调整。
- `qa_history` 与 prompt view 分离。
- 历史 3 槽：summary、recent QA、current gaps。
- ask_question 10 prompt slots 展示。
- Strategy / Skill 动态预算和 expanded model mapping。
- 国内主流模型 / provider context window mapping，包括 DeepSeek、Qwen / DashScope、Moonshot / Kimi、Zhipu / GLM、Volcengine / Doubao、Baichuan、MiniMax、Hunyuan、StepFun、01AI / Yi、Baidu ERNIE、iFlytek Spark、SenseNova / SenseChat。
- runtime truncation 与 trace preview truncation 拆分。
- Candidate Anchor RAG binding validation。
- `no_bound_chunks`、`session_anchor_bind_missing`、`query_embedding_timeout` 等 fallback reason 拆分。
- Resume / Self Intro source-aware fetch quota。
- Candidate Anchor RAG source diagnostics：fetch、score、keep 分 source 统计。
- Trace Explorer 中 prompt budget、prompt slots、Candidate Anchor RAG diagnostics 的展示和搜索。

暂未完成或明确暂缓的方向：

- Candidate Anchor RAG 的严格 hard wall-clock timeout。
- query embedding timeout 后的 lexical fallback。
- query embedding cache hit 在 Trace 中的显式展示。
- evaluator provider route / Qwen 网络 fallback 的根治。
- 应用层 prompt cache。

## 验证方式

### 会话验收

- `sess-20260531-050315-551323`：
  - DeepSeek `deepseek-v4-flash` prompt budget mapping 生效。
  - 10 prompt slots 每轮可见。
  - 历史上下文 source count、recent QA、history budget 行为正常。
  - 暴露 Candidate Anchor RAG timeout 和 binding consistency 问题。
- `sess-20260531-073212-4d88b7`：
  - Candidate Anchor RAG binding 修复生效。
  - 发现 self-intro chunks 未进入 top hits。
- `sess-20260531-084534-214e4a`：
  - Resume / Self Intro source quota 修复生效。
  - 每轮 resume/self-intro 都有 fetch、score、keep 诊断。
  - `CANDIDATE_RESUME_RAG` 和 `SELF_INTRO_RAG` 都注入。
  - 暴露 Candidate Anchor RAG latency 仍高。

### 测试命令

会话记录中多次使用或建议的验证命令：

```bash
pytest tests/unit/test_prompt_budget.py tests/unit/test_ask_question_selection_artifacts.py -q
pytest tests/unit/test_history_context.py tests/unit/test_workflow_observability.py -q
pytest tests/unit/test_session_anchor_retriever.py tests/unit/test_ask_question_selection_artifacts.py -q
npm run test -- traceExplorerSource
npm run typecheck
npm run lint
git diff --check
```

本文落盘时没有重新运行完整测试套件。上述命令记录为改造期间的验收口径和后续回归入口。

## 可复用教训

- 先定义事实源，再定义 prompt view。不要让 prompt 裁剪逻辑反向污染事实源。
- “上下文治理”不要默认等同于“上下文压缩”。在大上下文模型下，更重要的是内容选择、结构化投影、优先级和诊断。
- Prompt slots 应被当成 ledger，而不是展示装饰。每个 slot 都应该能解释来源、职责、预算和注入状态。
- 历史上下文最好做确定性结构化投影。LLM 压缩历史容易引入不可复现的信息损失和事实漂移。
- 对 Strategy / Skill 这类辅助信号，动态预算的意义是行为稳定和迁移安全，不是尽量塞满模型窗口。
- 对候选人材料 RAG，问题常常不在“模型装不下”，而在绑定、召回、source quota、排序和网络延迟。
- Trace 中必须区分运行时裁剪和展示截断，否则排查方向会错。
- “cache hit” 不等于当前 session 可用。跨 session 或重启后的缓存状态必须和 session-bound chunks 一起验证。
- source-aware diagnostics 很重要。只看最终 top hits 会错过“某个 source 在 fetch 阶段就被挤掉”的问题。
- Prompt cache 不能因为“prompt 很长”就默认值得做。要先看稳定 prefix 占比和每轮变化幅度。
- evaluator fallback 可能影响覆盖调度，但这和 ask_question prompt slot 治理是两条问题线。

## 未解决问题

- 无法读取 `codex://threads/019e5804-9db9-7061-8aeb-916b8314eb2a`，早期上下文治理讨论的细节仍可能缺失。
- Candidate Anchor RAG latency 仍偏高，后续需要单独诊断 query embedding、boost embedding、provider timeout 和 fallback mode。
- 当前 `resume_rag_query_embedding_timeout_ms = 3000` 不等于严格 3s wall-clock，是否要实现硬超时尚未定案。
- Query embedding cache 是进程内、短 TTL、按 query profile 命中的缓存。正常每轮 seed / dimension / query profile 不同，实际命中价值有限，Trace 中也缺少显式 cache-hit 诊断。
- `RETRIEVED_KNOWLEDGE` 的长期定位仍偏 legacy / compatibility，后续如果它再次承担主要知识注入，需要重新审查优先级。
- 历史预算 8000 chars 当前合理，但是否要调整到 10000 或 12000 应基于真实 traces，而不是因为模型窗口大就放宽。
- 如果未来面试轮次显著增加，或者引入更长的多模态 / 文档材料，当前治理模型需要重新压测。

## Source Map

### 源码

- `ai-interviewer/backend/app/engine/context/history_context.py`
  - 定义 `DEFAULT_RECENT_QA_WINDOW = 3` 和 `DEFAULT_HISTORY_BUDGET_CHARS = 8000`。
  - 构建 `INTERVIEW_HISTORY_SUMMARY`、`RECENT_QA`、`CURRENT_GAPS`。
  - 维护 `recent_qa_prompt_view` 和 `history_budget_exceeded` 等诊断。
- `ai-interviewer/backend/app/engine/context/prompt_budget.py`
  - 定义 Strategy / Skill 默认、normal、expanded budgets。
  - 定义 `KNOWN_MODEL_CONTEXT_WINDOWS`，包含 `deepseek-v4-flash = 1_024_000`。
  - 计算 `prompt_budget_diagnostics`、budget level、fallback 状态。
- `ai-interviewer/backend/app/engine/workflow/nodes/ask_question.py`
  - 组装 prompt slots。
  - 应用辅助 prompt budget。
  - 区分 `runtime_truncated` 和 `trace_text_truncated`。
  - 写入 `history_context`、`history_prompt_slots`、`prompt_budget_diagnostics`、`prompt_slots`。
  - 校验 Candidate Anchor binding。
- `ai-interviewer/backend/app/services/session_anchor_retriever.py`
  - Candidate Anchor RAG 检索、source-aware fetch、hit-level trimming。
  - 返回 `no_bound_chunks`、`query_embedding_timeout` 等 fallback reason。
  - 暴露 `fetched_rows_by_source`、`scored_rows_by_source`、`kept_hits_by_source`。
- `ai-interviewer/backend/app/services/resume_embedding.py`
  - Query embedding cache。
  - `embed_query` 优先查 cache。
  - 查询 embedding 热路径 max retries 为 0。
  - 默认 query timeout 设置为 3000ms。
- `ai-interviewer/frontend/src/components/admin/TraceExplorer.tsx`
  - 定义 10 个 prompt slot 的 UI 展示。
  - 显示 Prompt Budget Diagnostics。
  - 显示 Candidate Anchor RAG diagnostics。
  - 区分 runtime truncation 与 trace preview truncation。
- `ai-interviewer/frontend/tests/traceExplorerSource.test.js`
  - 覆盖 Trace Explorer prompt slots、truncation label、Candidate Anchor RAG diagnostics 搜索与展示。
- `tests/unit/test_history_context.py`
  - 覆盖历史 3 槽、recent QA window、prompt / trace truncation 等。
- `tests/unit/test_prompt_budget.py`
  - 覆盖模型 context window mapping、fallback、expanded budgets 等。
- `tests/unit/test_session_anchor_retriever.py`
  - 覆盖 Candidate Anchor RAG source-aware fetch 和 timeout / no-bound diagnostics。
- `tests/unit/test_ask_question_selection_artifacts.py`
  - 覆盖 ask_question selection artifacts 和 prompt slot diagnostics。

### 会话和 Trace

- `sess-20260531-015658-6f761c`
  - 旧 deepseek-v4-flash fallback 现象，用于说明 mapping 未补时的行为。
- `sess-20260531-050315-551323`
  - 新上下文治理主体通过，但 Candidate Anchor RAG timeout / binding inconsistency 暴露。
- `sess-20260531-073212-4d88b7`
  - Candidate Anchor binding 修复后验收，暴露 self-intro source 被 fetch 阶段挤出。
- `sess-20260531-084534-214e4a`
  - Source quota 修复后验收，resume/self-intro 都进入 RAG hits 和 prompt slots，残留 latency 问题。

### 对话来源

- 当前线程中用户提供的上下文治理总结和后续多轮追问。
- `codex://threads/019e7c64-f9e6-7dd2-8343-887e88416e25`
  - “优化 ask_question 上下文治理”。
- `codex://threads/019e7c80-3064-7b20-976d-862cdd5266e5`
  - “排查上下文治理问题”。
- `codex://threads/019e5804-9db9-7061-8aeb-916b8314eb2a`
  - 用户指定的目标线程，但本次未能读取，需保留为缺失证据。
