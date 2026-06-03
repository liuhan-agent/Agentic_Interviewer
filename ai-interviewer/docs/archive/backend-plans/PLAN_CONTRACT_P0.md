# P0：AskPlan + Contract + Evaluator 签字

> 这是 P0 阶段（最小可行落地）的规划。不动 bandit arm，不引入 verifier，范围受控。

---

## 0. 设计目标

把目前分散在 `ask_question_node` / `generator.generate_question` / `evaluator_agent.evaluate_answer` / `refine_followup_node` 之间的**隐性契约**，升级成一条**显式、可审计的"plan + contract"链条**：

- Generator 起草 question 和 contract；
- Evaluator 在提问前**签字确认 contract**；
- Evaluator 在打分时**严格依据签字后的 contract**（acceptance checks 逐条判定）；
- Evaluator 在给出建议时**直接命名下一轮应采用的 plan template**；
- Refine 不再仅置 flag，而是把 evaluator 的"下一轮 plan"写回 state。

关键**不做**：bandit arm 保持现有 4 个 action；不引入 verification agent；不外挂 LLM planner 作默认（保留为 opt-in）。

---

## 1. 最终状态示意

```
director_sample
      │  (bandit 选 action；若 state 有 pending_plan_template 则优先)
      ▼
ask_question
      ├─ resolve plan template (default 硬编码 or LLM planner)
      ├─ 执行 plan.steps:
      │     retrieve_rag → retrieve_strategy →
      │     draft_question → negotiate_contract (evaluator 签字) →
      │     guardrail_check
      └─ 写 state.current_question / state.current_contract / state.current_ask_plan
      ▼
wait_answer
      ▼
evaluator
      ├─ evaluate_answer(contract=state.current_contract, answer=…)
      ├─ 产出：旧字段 + acceptance_check_results + recommended_next_plan
      └─ 写 state.evaluation
      ▼
route_after_eval
      ├─ refine → refine_followup → pending_plan_template = eval.recommended_next_plan
      ├─ next_question → director_sample (清 pending_plan_template)
      └─ end
```

新增 state 字段只增不删，完全向后兼容。

---

## 2. 模块清单

| 文件 | 动作 | 说明 |
|---|---|---|
| `app/engine/workflow/state.py` | 扩展 | 新增 `PlanContract` / `AskPlanStep` / `AskPlan`；`InterviewState` 增 `current_ask_plan / current_contract / pending_plan_template / pending_contract_hints` |
| `app/engine/workflow/plans/__init__.py` | 新增 | 包入口 |
| `app/engine/workflow/plans/ask_plans.py` | 新增 | 默认三套模板（`simple / adaptive / deep_probe`）+ `resolve_ask_plan(...)` |
| `app/engine/agents/contract.py` | 新增 | `negotiate_contract_via_evaluator(question_draft, ...)` —— evaluator 负责最终签字 |
| `app/engine/agents/generator.py` | 小改 | 产出的 `question_payload` 里增一份 `proposed_contract`；保留 `negotiate_rubric` 作兼容函数（标 deprecated） |
| `app/engine/agents/evaluator_agent.py` | 扩展 | `evaluate_answer` 支持 `contract=...` 参数；输出新增 `acceptance_check_results` / `recommended_next_plan`；保留旧字段 |
| `app/engine/workflow/nodes/ask_question.py` | 重构 | 走 plan-executor 模式；`runtime_config.iterative_contract` 仍兼容（会映射到 `adaptive` 模板） |
| `app/engine/workflow/nodes/evaluator.py` | 小改 | 调用 evaluate_answer 时传入 contract；把 recommended_next_plan 透传进 state 供 refine 消费 |
| `app/engine/workflow/nodes/refine_followup.py` | 小改 | 读 evaluation.recommended_next_plan；写 `pending_plan_template` + `pending_contract_hints`；保留 `refine_mode=True` |
| `app/engine/workflow/nodes/director_sample.py` | 小改 | 若 `state.pending_plan_template` 存在，把它透传进 `selected_action`；**bandit 选择策略不变**（4 个 arm） |
| `tests/unit/test_plan_contract_p0.py` | 新增 | 用 stub LLM 跑全链的最小集成测试 |

---

## 3. 数据结构（state.py）

```python
class PlanContract(TypedDict, total=False):
    must_cover: list[str]
    acceptable_if_missing: list[str]
    acceptance_checks: list[str]
    minimum_bar: str
    review_focus: list[str]
    bar_level: Literal["intro", "standard", "deep_probe"]
    signed_by: list[Literal["generator", "evaluator"]]

class AskPlanStep(TypedDict, total=False):
    step_id: int
    kind: Literal[
        "retrieve_rag", "retrieve_strategy",
        "draft_question", "negotiate_contract",
        "challenge_with_reference", "guardrail_check",
    ]
    goal: str
    success_criteria: str
    produced_keys: list[str]
    dependencies: list[int]
    optional: bool

class AskPlan(TypedDict, total=False):
    plan_id: str
    template: Literal["simple", "adaptive", "deep_probe"]
    complexity: Literal["simple", "medium", "hard"]
    steps: list[AskPlanStep]
    source: Literal["default", "llm"]
```

InterviewState 新增（`total=False` 保证可选）：
- `current_ask_plan: AskPlan | None`
- `current_contract: PlanContract | None`
- `pending_plan_template: Literal["simple", "adaptive", "deep_probe"] | None`
- `pending_contract_hints: dict[str, Any] | None`

---

## 4. 三套默认 plan 模板

### 4.1 `simple`（第一轮、基础维度）
```
1. retrieve_rag          goal=为 draft_question 准备参考
2. draft_question        goal=出一个清晰、开放的问题；产出 proposed_contract 草稿
3. guardrail_check       goal=合规扫描
```
不走 negotiate_contract（用 generator 的 proposed_contract 直接签名）。

### 4.2 `adaptive`（默认、mid 级别）
```
1. retrieve_rag
2. retrieve_strategy
3. draft_question
4. negotiate_contract    goal=evaluator 确认 contract（must_cover / acceptance_checks / minimum_bar）
5. guardrail_check
```

### 4.3 `deep_probe`（refine 或 senior）
```
1. retrieve_rag
2. retrieve_strategy
3. draft_question (bias=challenge)        goal=基于上一轮 weaknesses 出更深的追问
4. negotiate_contract (bar_level=deep_probe)
5. challenge_with_reference               optional=true，失败则跳过
6. guardrail_check
```

---

## 5. Plan 模板 → selected_action 的映射

不改 bandit，但建立一张**单调映射**：

| selected_action.id | refine_mode | 默认 plan |
|---|---|---|
| `give_hint` | * | `simple` |
| `deepen_technical` | False | `adaptive` |
| `deepen_technical` | True | `deep_probe` |
| `switch_dimension` | * | `adaptive` |
| `skip_to_next` | * | `simple` |

同时，若 `state.pending_plan_template` 存在，**强制覆盖**上表。这让 refine 的建议优先级高于 bandit。

---

## 6. Evaluator 输出向后兼容矩阵

| 字段 | 旧 | 新 |
|---|---|---|
| `score` | 有 | 保留 |
| `passed` | 有 | 保留 |
| `strengths` | 有 | 保留 |
| `weaknesses` | 有 | 保留 |
| `rubric_coverage` | 有 | 保留（由 acceptance_check_results 映射得出） |
| `recommended_next` | 有 `refine/advance/skip` | 保留 |
| `rationale` | 有 | 保留 |
| `acceptance_check_results` | — | **新增**：`{check: "yes"|"partial"|"no"}` |
| `recommended_next_plan` | — | **新增**：`simple / adaptive / deep_probe / None` |

所有新字段默认 `None` / 空，旧路由逻辑不受影响。

---

## 7. Refine 语义升级对比

| 环节 | 旧 | 新 |
|---|---|---|
| refine_followup_node 产出 | `refine_mode=True` | `refine_mode=True` + `pending_plan_template=<eval.recommended_next_plan or "deep_probe">` + `pending_contract_hints={must_address: weaknesses}` |
| director_sample_node 消费 | 用 action mask 锁维度 | 读 pending_plan_template 作为提示（不影响 bandit 选 arm，只影响 ask_question 决定用哪套 plan） |
| ask_question_node 消费 | 读 action.id 手工拼 prompt | 若 `pending_plan_template` 存在，直接用；否则按 §5 的映射表 |

---

## 8. 测试策略

新增 `tests/unit/test_plan_contract_p0.py`，用 stub LLM 覆盖：

1. `test_ask_plan_default_templates_exist`：三套模板结构校验；
2. `test_ask_question_produces_plan_and_contract`：默认场景下 state 写入了 `current_ask_plan` / `current_contract`；
3. `test_evaluator_reads_contract_and_emits_acceptance_checks`：evaluator 拿到 contract 后输出 acceptance_check_results；
4. `test_refine_writes_pending_plan_template`：evaluator 给 deep_probe 建议时，refine_followup 把它写进 state；
5. `test_director_consumes_pending_plan_template`：director 在 selected_action 上挂出 `plan_template` 字段；
6. `test_backward_compat_no_contract`：`runtime_config.iterative_contract=False` 时，旧字段 `rubric_points` 仍可用、旧 `recommended_next` 不变。

---

## 9. 风险与回退

| 风险 | 缓解 |
|---|---|
| evaluator 签字多一次 LLM 调用 | 仅在 `negotiate_contract` step 被编排时调用；`simple` 模板默认跳过；stub 模式零成本 |
| LLM 返回的 acceptance_checks 字段格式不稳 | `parse_json_response` 已 permissive；提供 `_default_contract(...)` 兜底 |
| 旧调用方仍期望 `rubric_points` | 保留字段，evaluator 内部把 `must_cover` 也写进 `rubric_points` 做反向兼容 |
| LangGraph checkpoint schema 膨胀 | 新增字段都是 `total=False`；checkpointer 会按 JSON 序列化，不需要迁移 |
| router 逻辑破坏 | `route_after_eval` 完全不动；新语义都挂在 node 内部 |

回退：把 `ask_question_node` 的 plan-executor 分支用一个 feature flag `runtime_config.use_plan_executor=True` 包住（默认 True），一行切回旧代码路径。

---

## 10. 非目标（P0 明确不做）

- bandit arm 升级为 plan_template；
- verification_agent / 三 Agent 对抗；
- coach_agent / candidate simulator；
- LangGraph 外层 4 阶段子图；
- rubric 长期 memory；
- 合规双层守门员。

以上都在之前的 backend 整体优化清单里，P1/P2 再做。

---

## 11. 里程碑验收

P0 验收 = 以下同时成立：

- `pytest tests/unit/test_plan_contract_p0.py` 全绿；
- `pytest tests/unit/test_refine_lock.py` 仍全绿（向后兼容保证）；
- `python -m app.scripts.run_demo` 在 stub 模式下跑通，state 日志里能看到 `current_ask_plan` / `current_contract` / `pending_plan_template`；
- `ReadLints` 无新增错误。
