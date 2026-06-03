# 标准/深度面试多简历锚点调度层改造计划

## Summary
- 在现有 `resume_anchor / anchor_key / resume RAG` 底座上补“锚点调度层”，让标准/深度面试在维度覆盖后继续围绕高价值简历锚点展开，而不是所有维度 `passed` 后提前结束。
- `快速练习` 保持轻量：同一 anchor 最多 1 轮，不做维度覆盖后的锚点扩展。
- `标准面试` 和 `深度面试` 都允许同一高价值 `anchor_key` 最多 2 轮；第二轮必须换追问角度，不重复第一轮问题形态。
- 不改 DB schema；继续使用已落库的 `interview_turns.resume_anchor_key/resume_anchor_label/resume_project_id`。

## Key Changes

### API / Frontend
- `StartSessionRequest` 新增 `interview_depth?: "short" | "standard" | "deep"`。
- 前端 `SetupForm` 在用户选择 `快速练习 / 标准面试 / 深度追问` 时，除 `max_turns/turn_budget` 外同步传 `interview_depth`。
- 后端 `request_translator` 把 `interview_depth` 写入 `runtime_config`；缺省按 `standard` 处理，旧客户端兼容。

### Anchor Scheduler
- 在 `resume_plan` 增加锚点调度 helper：
  - 从 `candidate.resume_parsed.focus_areas` 构造候选 anchor，沿用现有 `anchor_key`、维度归一化、project fallback。
  - 统计 `qa_history` 中每个 `anchor_key` 已出现次数。
  - 高价值 anchor 判定：满足任一条件即可二轮展开：`priority <= 2`、命中 JD `required_skills`、命中 `focus_dimensions`、被 self-intro 强调。
  - `short`：`max_turns_per_anchor=1`。
  - `standard/deep`：高价值 anchor `max_turns_per_anchor=2`，普通 anchor 仍最多 1 轮。
  - 选择顺序：未问过的匹配 anchor 优先；没有合适未问 anchor 时，才选择已问 1 次的高价值 anchor 做第二轮。
- `select_resume_anchor` 扩展为支持调度策略，但保留旧调用语义；老测试和无 `interview_depth` 场景继续可用。

### Routing / Director
- `route_after_eval` 和 `route_after_skip` 的结束条件改为：
  - `formal_turn_idx >= max_turns` 或 `turn_budget_remaining <= 0`：结束。
  - 维度未全部完成：继续原有维度覆盖/追问逻辑。
  - 维度已全部完成，但 `standard/deep` 仍存在可展开 anchor slot：继续下一题。
  - 没有可展开 anchor slot：结束。
- `director_sample_node` 在“维度已覆盖但 anchor 仍可展开”时选择该 anchor 对应的维度作为下一轮 `current_dimension`，并在 diagnostics 标记 `anchor_expansion`；不绕开 Thompson arm，只改变下一题落点。
- 保留原有维度覆盖优先级：未覆盖维度永远优先于锚点扩展。

### Ask Question / Prompt Shape
- `ask_question_node` 使用锚点调度结果选择 `resume_anchor`，并把调度信息写入 `selection_artifacts.anchor_scheduler`，包括 `anchor_key`、`anchor_attempt`、`max_anchor_attempts`、`expansion_reason`。
- 第二轮同 anchor 时，自动选择不同 `probe_intent`：
  - 技术/系统类维度优先 `architecture_challenge`、`debugging_probe`、`performance_probe`、`metric_probe` 中未用过的角度。
  - 业务/沟通类维度优先 `case_study_probe`、`stakeholder_pushback_probe`、`process_design_probe`。
- 现有 duplicate rewrite 仍保留，作为最后兜底。

### Report / Replay
- 报告评分模型暂不改：维度总分继续使用现有 `weighted_recent` 聚合。
- 报告 evidence / replay turn 补充安全展示字段：`resume_anchor_label`、`resume_anchor_key`、`resume_project_id`，方便用户看到同一维度来自哪些项目/锚点证据。
- 不把 `resume_anchor` 原始完整对象直接暴露到候选人可见字段里，避免泄露内部调度信息。

## Test Plan
- `request_translator` / API contract：
  - `interview_depth` 进入 `runtime_config`。
  - 旧 payload 不传时默认为 `standard`。
  - 前端 `StartSessionRequest` 类型和 `SetupForm` payload 包含当前 length choice。
- `resume_plan`：
  - `short` 同一 `anchor_key` 最多选择 1 次。
  - `standard/deep` 高价值 anchor 已问 1 次后仍可被选为第二轮。
  - 普通 anchor 已问 1 次后不再复用。
  - 未问 anchor 优先于高价值 anchor 第二轮。
  - 使用 `anchor_key` 计数，兼容旧 `focus_id/project_id` fallback。
- `routers` / `director_sample`：
  - 所有维度 passed 且无 anchor slot 时结束。
  - 所有维度 passed 且 standard/deep 有可展开 anchor slot 时继续。
  - max turns / turn budget 仍优先结束。
  - 未覆盖维度优先于 anchor expansion。
- `ask_question`：
  - 第二轮同 anchor 生成不同 `probe_intent`。
  - `selection_artifacts.anchor_scheduler` 存在且可解释。
  - resume/self_intro RAG 仍接收被调度选中的 `resume_anchor`。
- `report/replay`：
  - turn evidence 暴露 anchor label/key/project id。
  - 维度分聚合结果保持现有策略，不因新增展示字段变化。
- Verification：
  - `python -m pytest tests/unit/test_resume_anchor_baseline.py tests/unit/test_coverage_routing.py tests/unit/test_resume_driven_interview.py tests/unit/test_request_trace_context.py tests/unit/test_session_replay_api.py -q`
  - `python -m ruff check app/engine/resume_plan.py app/engine/workflow/routers.py app/engine/workflow/nodes/director_sample.py app/engine/workflow/nodes/ask_question.py`
  - 前端运行现有 setup/type 相关测试，至少覆盖 `frontend/tests/setupCopy.test.js` 和 TypeScript 检查。

## Assumptions
- “约 8 轮 / 约 12 轮”仍是软目标；没有足够高质量 anchor 时可以提前结束。
- 标准/深度的核心区别主要来自 `max_turns` 和可用预算；二者都允许高价值 anchor 最多 2 轮。
- 第二轮同 anchor 是“换角度追问”，不是重复问同一问题，也不是把维度状态强行重置。
- 本次不改锚点评分聚合、不新增表、不回填历史会话。
