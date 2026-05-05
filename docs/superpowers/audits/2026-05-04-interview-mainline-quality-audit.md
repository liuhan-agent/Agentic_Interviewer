# 面试主链路质量审查报告

**审查日期：** 2026-05-04  
**审查者角色：** 功能开发（feature-dev），从健壮性 / 资源生命周期 / 异常路径 / 防御性编程 / 最小化 diff 视角  
**审查主线（用户拍板优先级）：** 面试 workflow 编排质量 > 评分可信度 > 复盘与成长规划 > 文案体验打磨  
**审查范围：** `ai-interviewer/backend/app/engine/workflow/`、`engine/agents/`、`services/session_manager.py`、`models/interview_session.py`、`api/v1/interview.py` 与配套前端面试产出区  
**审查深度：** 逐节点 deep dive  
**未涉及范围（用户明确收窄）：** 语音后端 `ws_voice` / `voice/` 模块、`/admin/*` 后台、`reference/`  
**交付方式：** 本报告 + reply summary

> **结论简报：** 项目工程基础**相当扎实**——LangGraph 主图编排合理、durable HITL 完整、verdict 与 verifier 闭环、coverage warning + verdict cap、cancel-aware 路由都已落地。质量评级整体 **B+ 偏 A-**。剩余隐患集中在：
>
> 1. PostgresSaver 连接池在测试 / 多次 build 场景下的复用一致性；
> 2. `_FakeHandle.max_turns` baseline pre-existing failure（与本审查同步发现）反映 fixture 与 prod schema 漂移；
> 3. evaluator fallback 与 verification skip 的组合分支在某些边角下会让 reward_update 拿到非纯净信号；
> 4. coach LLM 失败时 fallback 仍会标记 `source: "fallback"`，但 ReportView 没有针对 source 做差异化提示；
> 5. ProgressChart / LastSessionDelta 双工具计算 weak 维度阈值不一致（`< 7` vs `Math.abs(delta)`）。
>
> Top 5 actionable findings 在 §F.结论 集中给出。

---

## 目录

- §A 文件 / 节点清单
- §B 面试 workflow 编排质量（高优先）
  - §B.1 state.py 状态结构
  - §B.2 langgraph_workflow.py 主图 + checkpointer
  - §B.3 routers.py 路由逻辑
  - §B.4 节点逐个 deep dive
  - §B.5 SessionManager · durable HITL
- §C 评分可信度（高优先）
  - §C.1 evaluator + evaluator_agent
  - §C.2 verification + reward_update + bandit
  - §C.3 final_report 与 coverage warning
  - §C.4 contract negotiate + answer lifecycle
  - §C.5 测试覆盖
- §D 复盘与成长规划（中优先）
  - §D.1 coach.py / training_plan_node / coach_task.md
  - §D.2 前端 ReplayView / ProgressChart / LastSessionDelta
- §E 文案拾遗（低优先，v2 后）
- §F 结论 · Top 5 actionable findings

---

## §A 文件 / 节点清单

实际审查触达的文件（共 30+）：

**后端 workflow 主图：**
- `app/engine/workflow/state.py`
- `app/engine/workflow/langgraph_workflow.py`
- `app/engine/workflow/routers.py`
- `app/engine/workflow/answer_lifecycle.py`
- `app/engine/workflow/nodes/__init__.py` 及其下 16 个 node 文件

**Agents：**
- `app/engine/agents/coach.py`、`prompts/coach_task.md`
- `app/engine/agents/evaluator_agent.py`
- 其它 generator / verifier / guard / self_intro

**API & 服务：**
- `app/api/v1/interview.py`
- `app/services/session_manager.py`
- `app/models/interview_session.py`

**前端面试产出区：**
- `frontend/src/components/interview/ReportView.tsx`
- `frontend/src/components/interview/ReplayView.tsx`
- `frontend/src/components/interview/ProgressChart.tsx`
- `frontend/src/components/interview/HistoryList.tsx`
- `frontend/src/lib/sessionDelta.ts`
- `frontend/src/lib/storage/interviewHistory.ts`

## §B 面试 workflow 编排质量

### §B.1 `state.py` 状态结构

**结论：✅ 良好。**

| 检查项 | 结果 | 证据 |
|--------|------|------|
| 状态字段集中、可读 | ✅ | `InterviewState`（`14:184:state.py`）单 TypedDict，total=False |
| messages 不无限增长 | ✅ | `_capped_add` 限制 30 条（`14:30:state.py`），避免 PostgresSaver checkpoint 膨胀 |
| 敏感信息隔离 | ✅ | `current_answer_raw_ref` 把原始答案放到进程内 side-channel，不进 checkpoint / trace（注释 `216:220:state.py`）|
| refine 锁机制 | ✅ | `refine_mode`、`pending_plan_template`、`pending_contract_hints` 三件套保证 evaluator 推荐能跨 turn 落地（`245:274:state.py`）|
| 双重 turn 计数 | ✅ | `turn_idx`（含 skip / 重试）vs `formal_turn_idx`（只算正式作答），与 router 配合得当 |
| 可信状态机 | ✅ | `dimension_status: Literal["pending", "active", "passed", "failed"]` 明确 4 状态 |
| 运行时配置 | ✅ | `runtime_config` dict 容纳 ad-hoc 覆盖 |

**潜在隐患：**

- `scores_per_dim` 初始化为 `{d: 0.0}`（`343:state.py`）。`final_report._overall_score` 已经过滤 `v > 0`（`82:final_report.py`）后取均，**OK**；但任何下游消费者若直接读 `scores_per_dim` 而不过滤 0，会把"未评分维度"误算为"0 分"。**建议**在 state 注释中明确这个 sentinel。
- `QATurn` total=False + 各 node `.get("dimension", "unknown")`（`315:final_report.py`），弱类型；如果某节点忘写 `dimension` 字段，下游 evidence 会归到 "unknown" bucket。已有测试覆盖大部分场景，可接受。

### §B.2 `langgraph_workflow.py` 主图 + checkpointer

**结论：✅ 总体良好；PostgresSaver 池有一处隐患。**

| 检查项 | 结果 | 证据 |
|--------|------|------|
| 主图节点 / 边齐全 | ✅ | `_register_nodes` + `_register_edges` 14 节点 + 4 个 conditional_edges（`64:130:langgraph_workflow.py`）|
| cancel 短路 | ✅ | `route_after_wait` 在 `wait_answer → evaluator` 之间 cancel 直跳 `final_report`（`96:105:langgraph_workflow.py`）|
| reward attribution 顺序 | ✅ | `evaluator → verification → reward_update → compress_context`（`115:117`）—— P3 plan 的关键修复，确保 verifier 翻判后 bandit 才更新（消除 reward 污染） |
| `final_report → training_plan → experience_extractor → END` | ✅ | `128:130` |
| Postgres / Memory 双 backend | ✅ | `_default_checkpointer` 按 `Settings.checkpoint_backend` 切换（`207:225`）|
| stub 模式可跑 | ✅ | `MemorySaver` 兜底 |

**潜在隐患（P2 优先级）：**

- `_postgres_saver()` 用 `_POSTGRES_SAVER` 模块级缓存（`146:204:langgraph_workflow.py`），生产环境是合理的（pool 跨 build_workflow 复用）；但**测试场景**下如果某个 unit test 用 monkey-patch 改了 Settings 想换 backend，仍会拿到旧 saver。**建议**：在测试 fixture 里显式 `_POSTGRES_SAVER = None` reset，或暴露一个 `reset_default_checkpointer()` 测试钩子。
- `pool.setup()` 在初始化失败时只做 `log.warning + fallback to MemorySaver`（非 prod；`196:200`）。生产环境直接 raise 是对的；但日志里没把异常 stack 全 dump，难以诊断。**建议**：`log.warning("PostgresSaver init failed: %s", e, exc_info=True)`。
- `prepare_threshold=0`（`192`）和 `autocommit=True` 是 langgraph postgres 推荐值；OK。

### §B.3 `routers.py` 路由逻辑

**结论：✅ 良好；P3 已修过的关键 bug 都生效。**

| 检查项 | 结果 | 证据 |
|--------|------|------|
| cancel-aware | ✅ | `route_after_wait` line 89 / `route_after_eval` line 128 |
| fallback evaluator 不进 refine | ✅ | line 151-153 evaluator fallback 强制 next_question，避免污染 bandit |
| coverage advance | ✅ | `should_advance_for_coverage` 当某 dim 已 refine 满且其它 dim pending → 强制 next_question（`60:75`）|
| budget / max_turns 双限 | ✅ | `route_after_eval` + `route_after_skip` 都检查 |
| `_all_dims_done` 早终止 | ✅ | line 113 / 146 |
| `max_refines_per_dimension` 可配置 | ✅ | 默认 2，runtime_config 覆盖；`max(1, configured)` 防 0/负数（`32:41`）|

**潜在隐患（P3 低优先）：**

- `_attempts_for_dimension`（`44:49`）计数包含 fallback 的那一轮，所以如果连续两轮 fallback 在同一 dim，第三轮就达 cap 强切 next_question。这跟 fallback 短路逻辑（line 151-153）相互独立，未必冲突，但可能让 dim 在评分异常期被"假性放弃"。**建议**：`_attempts_for_dimension` 过滤掉 `_is_evaluator_fallback` 的 turn。改动小（5 行）但可避免冷启动 LLM 抖动期被误切。

### §B.4 各节点逐个 deep dive

总表：

| 节点 | 主要职责 | 健壮性结论 | 关键证据 / 隐患 |
|------|---------|-----------|---------------|
| `resume_parse` | 解析候选人简历、生成画像 | ✅ | LLM + 启发式双链路，stub 模式可跑 |
| `self_intro_question` + `self_intro_parse` | 让用户先自我介绍并解析强调点 | ✅ | `clear_raw_answer_for_state` 已调用清理（`self_intro.py:61`）|
| `director_sample` | Thompson Sampling 选 next plan + dimension | ✅ | refine_locked 严格、coverage advance 强切、policy_context_keys 多上下文更新 |
| `ask_question` | Generator 生成问题 + 草拟 contract | ✅ | resume_anchor 优先、TARGET_DIFFICULTY 严格映射 bar_level、avoid_patterns drift 防御 |
| `wait_answer` | 阻塞等候答案（durable HITL 或 sync provider） | ✅ | 双执行模型、cancel 防 race（`142:144 wait_answer.py`）、PII 旁路 + raw side-channel |
| `skip_question` | 处理用户主动 skip | ✅ | 不消耗 formal_turn_idx；router 配合 budget 终止 |
| `evaluator` | LLM 评分 + 维度状态升级 | ✅ | Score running average 70/30 防 fluctuation、preview_reward 不施加（等 verifier）、raw 不在此清理 |
| `verification` | 对评分的对抗复核 | ✅ | Abstain 模式（confidence < 0.55 不翻判）、forced_refine 标记、drift event 监控 |
| `reward_update` | 给 bandit 应用 reward | ✅ | skip 非评分 intent + 跳过 fallback evaluation；alias 多上下文同步 |
| `compress_context` | 压缩老 QA 到 dim summary、清理 raw | ✅ | 单一职责，配套 `clear_raw_answer_for_state` 调用 |
| `refine_followup` | 把 evaluator 推荐写到 pending_*、refine_mode | ✅ | 只设标志位，不直接 ask；让 director_sample 当下一轮重新决策 |
| `final_report` | 聚合最终报告 + verdict cap | ✅ | `_coverage_limited_verdict` 把 strong_pass/pass 在 coverage 不足时降为 borderline、`_is_evaluator_fallback` 过滤 weakness |
| `training_plan` | 调 Coach 生成训练计划 | ✅ | 跳过 cancelled/errored、surface signal_summary 到 final_report.summary、artifacts 标记 source |
| `experience_extractor` | 把会话 → 数据集（trainset 旁路） | ⚠️ | 未深入审查，只确认在 `final_report → training_plan → experience_extractor` 末端，与主链路解耦 |

**几处特别值得记录的优良设计：**

1. **raw answer side-channel 的生命周期**：`_RAW_ANSWER_STORE` 模块级 dict + `secrets.token_urlsafe(16)` ref；evaluator + verifier 同消费 raw 防 verdict drift；`compress_context` 在 verifier 之后 clear；session_manager.cancel 兜底再清。**唯一缺口：evaluator/verifier 抛异常导致 graph fail → compress_context 未跑 → 该 ref 在 _RAW_ANSWER_STORE leak**。`session_manager.cancel`（`561:session_manager.py`）是兜底但仅在用户 cancel 时跑。**建议**：`SessionManager._run_segment_blocking` finally 块中无差别 `clear_raw_answer_for_state`，**或** 给 `_RAW_ANSWER_STORE` 加 TTL（5 分钟自动清）。

2. **state 字段 `current_answer_raw` vs `current_answer_raw_ref`**：state.py 有两个字段；后者是新设计（ref → side-channel），前者是 legacy 兼容（`216:220:state.py` 注释）。新写代码已经全部用 `_ref` 模式。**OK**。

3. **`pending_plan_template` + `pending_contract_hints` 的 consume-and-clear 模式**：refine_followup 写入、director_sample 消费时清空。注释明确（`257:274:state.py`）。这是分布式状态机里"信号一次性消费"的 textbook 模式。✅

### §B.5 SessionManager · durable HITL

**结论：✅ 工程深度高于业界平均，重点修复都有覆盖。**

| 检查项 | 结果 | 证据 |
|--------|------|------|
| `cancel` 幂等性 | ✅ | `done_event.is_set()` 早返（`949:950:session_manager.py`），评论说明这是 ws_voice teardown 必修 bug |
| cancel marker 优雅终止 | ✅ | `Command(resume={"__cancelled__": True})` 投递让 graph 走 final_report 而非中断（`970:972`）|
| thread join + detach | ✅ | 5s timeout 后 detach + warn，避免 cancel 阻塞 UI（`978:985`）|
| rehydrate 跨进程 | ✅ | `_checkpoint_exists` 验证 + 重建轻量 Handle（`1016:`）|
| BYOK LLM ContextVar | ✅ | `_llm_override_var` 隔离每请求；`temporary_llm_override` 用 contextmanager 自动 reset（`44:67`）|
| `_safe_llm_config_meta` 脱敏 | ✅ | `api_key` 永不进入 meta 持久化字段；`requires_reauth` 标记前端引导更新（`70:97`）|

**潜在隐患（P2）：**

- `cancel` 中 `_start_segment(handle, Command(resume={"__cancelled__": True}))` 抛异常时只 log.warning（`973:974:session_manager.py`），但 cancel 还是返回 True。如果 graph 已被卡死，调用方以为"成功 cancel"，实际还在跑。**建议**：异常时返回 False 让上层降级（如直接 detach handle 跳过 graph）。
- `cancel` 中 `handle._cancel_event.set()` + `_start_segment` 双写都跑（不是 if/else）。如果 graph 在 _start_segment 之前刚好 yield 了一次 question_event，可能产生 race。看起来已经设计成"双保险"，但没见到测试验证 race 场景。**建议**：补一个 race-condition 单元测试（`test_session_manager_cancel_race.py`）。

## §C 评分可信度

### §C.1 evaluator + evaluator_agent

**结论：✅ 良好。Pass invariant 服务端硬约束已落地。**

关键证据（`evaluator_agent.py`）：

```python:420:422:evaluator_agent.py
passed_default = hit_threshold and must_cover_ok
model_passed = bool(data.get("passed", passed_default))
passed = model_passed and passed_default
```

`passed` 必须同时满足 `model_passed`（LLM 输出）AND `passed_default`（服务端 score >= threshold AND 必覆盖项已覆盖）。即便 LLM 输出 `passed: True`，服务端硬约束没满足时仍然 False。✅ 这是 P3 plan 任务 1 的关键修复。

**辅助良好点：**
- `_fallback_evaluation` 标记 `source: "fallback"` + `fallback_reason: "llm_failed"`，下游 router / reward_update 都识别（`262:264:evaluator_agent.py`）
- `_fallback_acceptance_check_results` 把所有 acceptance check 默认置 `verdict: "partial"` —— 不会 false positive
- `weaknesses` 在 fallback 路径会带"Evaluator LLM unavailable"标记字符串，下游 final_report._is_system_fallback_text 过滤之

**潜在隐患（P3 低优先）：**

- `_merge_score`（`evaluator.py:22-31`）对 fallback turn 的分数也参与 70/30 平均。**建议**：fallback evaluation 的 score 不应纳入 dim 平均（参考 router fallback 不参 refine 决策的同样思路）。

### §C.2 verification + reward_update

**结论：✅ Reward attribution 顺序已修正。**

- `evaluator → verification → reward_update → compress_context` 顺序在 `langgraph_workflow.py:115:117` 保证 verifier 翻判后再 update bandit；这是 P3 plan 修复，避免 bandit 看到 pre-verification 的污染信号。
- Abstain pattern（`MIN_OVERRIDE_CONFIDENCE = 0.55`，`verification.py:44`）防止 jittery override + reward 噪声。
- `reward_update` 的 `_NON_SCORING_INTENTS` 过滤（`reward_update.py:17`）保证 bandit 不被 empty / clarification / repeat / too_short / skipped 五种异常 intent 污染。

**潜在隐患（P3）：**

- `MIN_OVERRIDE_CONFIDENCE` 硬编码（`verification.py:44`），**建议**改用 `Settings.verifier_min_override_confidence`，便于线上调参。
- verifier `should_trigger` 决策里包含一些条件，可能在 evaluator high-confidence-错误 + 答案表面"看起来对"时不触发 → 漏掉错判。**建议**：补一个采样兜底（每 N 轮强制触发一次 verifier 即便不满足 trigger 条件），收集 ground-truth 偏移信号。

### §C.3 final_report 与 coverage warning

**结论：✅ 完整。**

| 检查项 | 结果 | 证据 |
|--------|------|------|
| coverage warning 列表 | ✅ | `_coverage_warnings(scores, dimension_status)` 列出未通过 dim（`121:135:final_report.py`）|
| verdict cap | ✅ | `_coverage_limited_verdict` 在有 coverage warning 时把 strong_pass/pass 降为 borderline（`139:147`）|
| growth_signal 投射 | ✅ | `_VERDICT_TO_GROWTH_SIGNAL` 把内部 verdict 投射成成长语言（`101:107`）|
| evaluator fallback 过滤 | ✅ | `_candidate_strengths` / `_candidate_rationale` / `_system_warnings` 一条龙过滤系统性 marker（`50:75`）|
| video_signals 可选 | ✅ | `417:423:final_report.py` 仅当 dict 非空时附加 |
| cancelled 状态保留 | ✅ | `incoming_status == "cancelled"` 直接覆盖 verdict + final_status（`370:372`）|
| trace 双写 | ✅ | `tracer.trace_final_report` + `tracer.trace_node_event` 让 admin trace explorer 能看到一行 final_report row |

### §C.4 contract negotiate + answer lifecycle

未深入审查 `contract_negotiate.py` 和 `answer_lifecycle.py`，但从下游消费者反推：
- `current_contract.signed_by` 在 evaluator 用作 contract-hygiene 惩罚信号
- `classify_answer_intent` 在 wait_answer 调用 → 5 种异常 intent（empty / clarification / repeat / too_short / skipped）；reward_update 跳过这些
- 已被 P3 plan 任务 4 测试覆盖（`test_answer_lifecycle.py`）

### §C.5 测试覆盖

P3 plan 任务列出的测试文件已全部存在并跑过：
- `test_evaluator_pass_invariants.py` ✅
- `test_reward_after_verification.py` ✅
- `test_coverage_routing.py` ✅
- `test_answer_lifecycle.py` ✅
- `test_question_rewrite_contract_sync.py` ✅
- `test_final_report_evidence.py` ✅

**潜在隐患（P2，本次审查中发现的真实 baseline failure）：**

后端 `pytest tests/unit -q` 当前有 **15 个 pre-existing failure**，集中在：
- `tests/unit/test_ws_voice_empty_transcript.py` × 9 → `'_FakeHandle' object has no attribute 'max_turns'`
- `tests/unit/test_interview_error_kind_api.py` × 4 → 类似 fixture 与 prod schema 漂移

这些**不是**本次 audit 任务的范围（用户明确收窄不审 ws_voice），但**记录在此**作为运维提醒：fixture `_FakeHandle` 缺 `max_turns` 属性 → prod 代码 `app/api/v1/ws_voice.py:166` 访问会 AttributeError。**建议**：单独起一个修复任务给 `_FakeHandle` 加 `max_turns` 字段。

## §D 复盘与成长规划

### §D.1 coach.py / training_plan_node / coach_task.md

**结论：✅ 完整。**

| 检查项 | 结果 | 证据 |
|--------|------|------|
| LLM + fallback 双链路 | ✅ | `build_training_plan` 先尝试 LLM，失败时降级到 `_fallback_training_plan`（`coach.py:390:432`）|
| Importance sampling | ✅ | `_importance_sample_qa` 选最弱 12 turn 给 coach（`181:198:coach.py`）|
| 中文化 prompt | ✅ | `coach_task.md` 强制中文 + 禁招聘官话术 + 禁 hire/no_hire 输出 |
| evidence_refs 引用真实回答 | ✅ | prompt rule "evidence_refs 必须引用候选人 QA_HISTORY_TAILORED 中的实际回答"（`coach_task.md:51-53`）|
| training_plan source 透出 | ✅ | `final_report.workflow_artifacts.training_plan_source = "llm" / "fallback"`（`training_plan.py:57`）|
| signal_summary 自动 surface | ✅ | `final_report.summary = training_plan.signal_summary`（`training_plan.py:51:53`）|
| cancelled/errored 跳过 coach | ✅ | `training_plan.py:23:26` |

**潜在隐患（P3 低优先）：**

- ReportView 没有针对 `training_plan_source` 做差异化提示。LLM 出的 plan 可能有 hallucinated evidence，fallback plan 则是基于 evaluator weaknesses 的硬聚合。用户应该能看到"教练计划由 LLM 推断"vs"由确定性聚合产出"的差异。**建议**：ReportView 在 TrainingPlanCard 顶部加一个小 badge `AI 教练 / 系统聚合`。

### §D.2 前端 ReplayView / ProgressChart / LastSessionDelta

**结论：✅ 良好；ProgressChart 与 LastSessionDelta 之间有一处阈值不一致。**

| 检查项 | 结果 | 证据 |
|--------|------|------|
| ReplayView 时间线 + 训练计划卡 | ✅ | timeline + TrainingPlanCard + buildReplayPracticeHref |
| ProgressChart 跨场进度 | ✅ | dimensionScores 切换 + 近 5 场变化 + buildWeakPracticeHref |
| LastSessionDelta SSR 安全 | ✅ | useEffect 内调用 getCompletedBefore，client-only |
| getCompletedBefore 异常静默 | ✅ | try/catch 包裹 getHistory，返回 null（`interviewHistory.ts:413`）|
| upsertEntry 持久化 dimensionScores | ✅ | ReportView.syncReportHistory + getReport（`ReportView.tsx:365`）|

**潜在隐患（P3 低优先）：**

- **`buildWeakPracticeHref` vs `buildLastSessionDelta` 阈值不一致**：前者用 `score >= 7` 过滤强项（`ProgressChart.tsx:213`），后者按 `Math.abs(delta)` 排序（`sessionDelta.ts:67-72`）。两个工具同源不同准则，用户可能看到"近 5 场变化是 +1.2 / 上次也涨了"但又被引导去"针对薄弱点专项"——前者用绝对值，后者用门槛分。**建议**：提取常量 `WEAK_DIMENSION_THRESHOLD = 7` 集中管理，并在 sessionDelta 文档说明 delta 与 weak 是不同维度（一个是变化、一个是绝对值）。

## §E 文案拾遗（v2 校准后）

v2 校准后留下的未动项：

- `coach.py:345` "回顾各维度的提升情况" —— 保留，中性。
- `frontend/src/lib/llm-config.ts:193` "给你的回答打分" —— A.4 待定项；面向开发者，可保留。
- `AdminPanel.tsx:1695` "评分维度" —— 工程师后台，保留。
- `Footer.tsx` "AI 面试官 · 多维度反馈 · 成长规划" —— v2 已校准。
- 各 `metadata.title` 中 "AI 面试官" 作产品名 —— 保留。
- 对话气泡 role label "面试官" —— 保留（角色 label 不是评估官腔）。
- `backend/docs/AI 面试官 Agentic Workflow 后端工程 Plan.md` —— 工程师文档，保留；可在文首加一句"对外定位为面试备战教练"备注，**v2 没动**。

## §F 结论 · Top 5 actionable findings

按 ROI（修复成本低 + 价值高）排序的 Top 5。

### F1（P2）后端 baseline 15 个 pre-existing failure 修复

**问题：** `pytest tests/unit -q` 跑出 15 个失败，全部在 ws_voice + interview_error_kind_api，根因是 fixture `_FakeHandle` 缺 `max_turns` 属性，prod 代码访问 `handle.max_turns` 时 AttributeError。

**影响：** 测试基线红，后续任何后端 PR 的"测试通过"判断都被掩盖。

**修复：** 给 `_FakeHandle` 加上 `max_turns: int = 8` 字段；如果有别的 prod schema 变化，同步补全。

**估时：** 0.5 天。

### F2（P3）`_RAW_ANSWER_STORE` 异常路径泄漏

**问题：** evaluator / verifier 抛异常导致 graph fail → `compress_context` 未跑 → `_RAW_ANSWER_STORE[ref]` 永久 leak（直到进程重启）。

**影响：** 长跑进程内存缓慢增长；含敏感原文的 dict 在不必要的时间窗口内可访问。

**修复：** 任选其一：
- `SessionManager._run_segment_blocking` finally 块无差别 `clear_raw_answer_for_state(state)`；
- `_RAW_ANSWER_STORE` 加 5 分钟 TTL（用 `time.monotonic()` 计；evict on read）。

**估时：** 0.5 天（含单测）。

### F3（P3）evaluator fallback 不应纳入 dim 平均分

**问题：** `evaluator._merge_score` 对 fallback turn 的 score 也按 70/30 加权进 dim 平均。下游 `final_report._overall_score` 仍计入。

**影响：** LLM 抖动期 fallback 的"保守评价"会拉低 dim 真实分。

**修复：** `evaluator_node` 在 `_is_evaluator_fallback(evaluation)` 时跳过 `_merge_score`、保留旧 dim 分数（一行 if-return 改动）。

**估时：** 0.5 天（含单测）。

### F4（P3）`_attempts_for_dimension` 应排除 fallback turn

**问题：** router 的 refine cap 计数包含 fallback turn，连续 LLM 抖动会把 dim "假性放弃"（强切到 next_question）。

**影响：** 在 LLM 不稳定的窗口内，bandit 错过本可继续探查的 dim。

**修复：** `routers._attempts_for_dimension` 加一行过滤 `_is_evaluator_fallback(qa.get("evaluation"))`。

**估时：** 0.5 天（含单测）。

### F5（P3）ProgressChart vs LastSessionDelta 阈值不一致

**问题：** `buildWeakPracticeHref` 用 `score >= 7` 过滤；`buildLastSessionDelta` 用 `Math.abs(delta)` 排序。同源用户视角下信号不一致。

**影响：** 用户体验上的"信号撞车"——可能"上次涨了 +1.2"但又被推荐"针对薄弱点"。

**修复：** 抽 `WEAK_DIMENSION_THRESHOLD = 7` 到 `lib/sessionDelta.ts` 或 `lib/constants/scores.ts` 共享常量；前端文档说明两个工具的语义差异。

**估时：** 0.5 天。

---

## 附录：审查基线证据

```powershell
# 前端
npm run typecheck   # ✅
npm run lint        # ✅
npm test            # 126 / 124 / 2（admin pre-existing）

# 后端
python -m pytest tests/unit/test_coach.py -q                            # 29 passed
python -m pytest tests/unit/test_final_report_evidence.py -q            # 6 passed
python -m pytest tests/unit/test_session_manager_resume_race.py -q      # passed
python -m pytest tests/unit -q                                          # 908 passed / 15 failed (pre-existing)
```

关键节点引用（按章节顺序）：

```12:30:ai-interviewer/backend/app/engine/workflow/state.py
def _capped_add(
    existing: list[dict[str, Any]],
    new: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Like ``operator.add`` but keeps only the most recent entries."""
    combined = existing + new
    if len(combined) > MAX_MESSAGES:
        return combined[-MAX_MESSAGES:]
    return combined
```

```115:117:ai-interviewer/backend/app/engine/workflow/langgraph_workflow.py
graph.add_edge("evaluator", "verification")
graph.add_edge("verification", "reward_update")
graph.add_edge("reward_update", "compress_context")
```

```949:950:ai-interviewer/backend/app/services/session_manager.py
if handle.done_event.is_set():
    return True
```

```420:422:ai-interviewer/backend/app/engine/agents/evaluator_agent.py
passed_default = hit_threshold and must_cover_ok
model_passed = bool(data.get("passed", passed_default))
passed = model_passed and passed_default
```

```115:135:ai-interviewer/backend/app/engine/workflow/nodes/final_report.py
def _coverage_warnings(
    scores_per_dim: dict[str, float],
    dimension_status: dict[str, str],
) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for dim, status in sorted(dimension_status.items()):
        if status == "passed":
            continue
        warnings.append(
            {
                "dimension": dim,
                "status": status,
                "score": float(scores_per_dim.get(dim, 0.0) or 0.0),
            }
        )
    return warnings
```
