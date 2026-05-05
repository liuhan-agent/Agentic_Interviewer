# P3 面试主链路质量提升实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 writing-plans、test-driven-development、verification-before-completion。按用户规则，本计划不使用子代理；逐任务串行执行。

**目标：** 修复面试主链路中评分放行、Verifier 奖励归因、维度覆盖、异常回答生命周期、问题改写与 contract 同步这五类质量缺口。  
**架构：** 保持现有 LangGraph 节点结构，小步增强 `Evaluator -> Verification -> Routing -> Report` 闭环。优先增加确定性服务端约束，再让 LLM prompt 作为辅助信号，而不是唯一判定来源。  
**技术栈：** Python、LangGraph、pytest、现有 `InterviewState`、`PlanContract`、Thompson bandit、FastAPI 会话管理。

## 文件结构

### 需要修改的生产代码

- `ai-interviewer/backend/app/engine/agents/evaluator_agent.py`  
  负责强制执行服务端 pass invariant，避免 LLM 直接覆盖分数与 must-cover 判定。

- `ai-interviewer/backend/app/engine/workflow/nodes/evaluator.py`  
  移除或停用 verification 前的 bandit 在线更新，只保留评分与 qa_history 写入。

- `ai-interviewer/backend/app/engine/workflow/nodes/reward_update.py`  
  新增节点：在 `verification_node` 之后读取最终 `evaluation`，再执行 `immediate_reward` 与 `bandit.update`。

- `ai-interviewer/backend/app/engine/workflow/langgraph_workflow.py`  
  将图边调整为 `evaluator -> verification -> reward_update -> compress_context`。

- `ai-interviewer/backend/app/engine/workflow/routers.py`  
  增加 coverage-aware routing：同一维度连续失败达到上限且仍有 pending 维度时，不再继续 refine。

- `ai-interviewer/backend/app/engine/workflow/nodes/director_sample.py`  
  在 coverage pressure 下强制选择 switch action，避免 router 放行后 bandit 又抽回同一维度。

- `ai-interviewer/backend/app/engine/workflow/nodes/final_report.py`  
  增加 coverage-aware verdict cap，未覆盖核心维度时限制最高 verdict。

- `ai-interviewer/backend/app/engine/workflow/nodes/wait_answer.py`  
  写入 `current_answer_intent`，区分空答、澄清请求、重复答等非正式评分输入。

- `ai-interviewer/backend/app/engine/workflow/answer_lifecycle.py`  
  新增确定性分类模块，避免把明显无效输入直接送进 Evaluator。

- `ai-interviewer/backend/app/engine/workflow/state.py`  
  增加 `current_answer_intent`、`answer_repair_count` 等轻量状态字段。

- `ai-interviewer/backend/app/engine/workflow/nodes/ask_question.py`  
  问题被 duplicate/language fallback 改写后，同步生成匹配新问题的 fallback contract。

### 需要新增或扩展的测试

- `ai-interviewer/backend/tests/unit/test_evaluator_pass_invariants.py`
- `ai-interviewer/backend/tests/unit/test_reward_after_verification.py`
- `ai-interviewer/backend/tests/unit/test_coverage_routing.py`
- `ai-interviewer/backend/tests/unit/test_answer_lifecycle.py`
- `ai-interviewer/backend/tests/unit/test_question_rewrite_contract_sync.py`
- 扩展 `ai-interviewer/backend/tests/unit/test_final_report_evidence.py`

## 任务 0：建立基线

**文件：** 不修改文件。

**步骤：**

1. 进入后端目录：
   ```powershell
   cd ai-interviewer/backend
   ```
2. 运行主链路相关现有测试：
   ```powershell
   python -m pytest tests/unit/test_plan_contract_p0.py tests/unit/test_refine_lock.py tests/unit/test_target_skills.py tests/unit/test_raw_answer_lifecycle.py tests/unit/test_final_report_evidence.py tests/unit/test_verifier_adaptive_trigger.py
   ```

**验证：** 命令应全部通过；若失败，先记录失败测试名与原因，不进入实现。  
**提交：** 不提交，除非用户明确要求。

## 任务 1：Evaluator pass invariant 硬约束

**文件：**

- `ai-interviewer/backend/app/engine/agents/evaluator_agent.py`
- `ai-interviewer/backend/tests/unit/test_evaluator_pass_invariants.py`

**步骤：**

1. 先新增失败测试，覆盖模型返回 `passed: true` 但分数低于阈值：
   ```python
   def test_low_score_model_pass_is_forced_false(monkeypatch):
       from app.engine.agents import evaluator_agent as mod

       monkeypatch.setattr(
           mod,
           "call_chat",
           lambda *_a, **_kw: '{"score": 3.0, "passed": true, "strengths": [], "weaknesses": [], "acceptance_check_results": {"c1": {"verdict": "yes", "evidence": ["x"]}}, "rationale": "x"}',
       )

       result = mod.evaluate_answer(
           dimension="system_design",
           question="Q",
           rubric_points=["depth"],
           answer="x",
           quality_threshold=7.0,
           contract={"must_cover": ["depth"], "acceptance_checks": ["c1"]},
       )

       assert result["passed"] is False
   ```
2. 再新增失败测试，覆盖 must_cover 缺失但模型返回 `passed: true`。
3. 修改 `evaluate_answer`：
   ```python
   model_passed = bool(data.get("passed", passed_default))
   passed = model_passed and hit_threshold and must_cover_ok
   ```
4. 保留 `rationale`、`recommended_next` 等模型输出，不额外重写评分文本。

**验证：**

```powershell
python -m pytest tests/unit/test_evaluator_pass_invariants.py tests/unit/test_plan_contract_p0.py
```

预期：新增测试先失败，改实现后全部通过。

## 任务 2：Verifier 后置奖励归因

**文件：**

- `ai-interviewer/backend/app/engine/workflow/nodes/evaluator.py`
- `ai-interviewer/backend/app/engine/workflow/nodes/reward_update.py`
- `ai-interviewer/backend/app/engine/workflow/nodes/__init__.py`
- `ai-interviewer/backend/app/engine/workflow/langgraph_workflow.py`
- `ai-interviewer/backend/tests/unit/test_reward_after_verification.py`

**步骤：**

1. 新增测试：Evaluator 原始通过，Verifier 将 `passed` 改为 false 后，reward 应包含 `verifier_forced_refine` penalty。
2. 从 `evaluator_node` 中移除 `bandit.update` 调用；`trace_evaluator` 的 `immediate_reward_applied` 设为 `False`。
3. 新增 `reward_update_node(state)`：
   ```python
   def reward_update_node(state: InterviewState) -> dict[str, Any]:
       evaluation = state.get("evaluation") or {}
       action = state.get("selected_action") or {}
       action_id = action.get("id")
       if not action_id or evaluation.get("source") == "fallback" or evaluation.get("fallback_reason"):
           return {}
       contract = state.get("current_contract") or (state.get("current_question") or {}).get("contract")
       reward = immediate_reward(evaluation=evaluation, contract=contract)
       keys = state.get("policy_context_keys") or action.get("policy_context_keys") or policy_context_keys(state.get("job_spec") or {}, state.get("current_dimension") or "unknown")
       bandit = get_bandit()
       for key in keys:
           bandit.update(key, action_id, reward)
       alias = ALIAS_MAP.get(action_id)
       if alias and alias != action_id:
           for key in keys:
               bandit.update(key, alias, reward)
       return {"messages": [{"role": "system", "kind": "reward_update", "reward": reward}]}
   ```
4. 在图中注册并连接 `verification -> reward_update -> compress_context`。

**验证：**

```powershell
python -m pytest tests/unit/test_reward_after_verification.py tests/unit/test_workflow_observability.py tests/unit/test_verifier_abstain.py
```

预期：Verifier 改判后的 reward 使用最终 evaluation。

## 任务 3：覆盖感知路由与每维 refine 上限

**文件：**

- `ai-interviewer/backend/app/engine/workflow/routers.py`
- `ai-interviewer/backend/app/engine/workflow/nodes/director_sample.py`
- `ai-interviewer/backend/tests/unit/test_coverage_routing.py`

**步骤：**

1. 新增 helper：
   ```python
   def _attempts_for_dimension(state: InterviewState, dimension: str) -> int:
       return sum(1 for qa in state.get("qa_history", []) if qa.get("dimension") == dimension)
   ```
2. 新增 helper：
   ```python
   def _has_pending_other_dimension(state: InterviewState, current_dim: str) -> bool:
       status = state.get("dimension_status", {})
       return any(dim != current_dim and status.get(dim) in {None, "pending", "active"} for dim in state.get("dimensions", []))
   ```
3. 在 `route_after_eval` 中读取 `runtime_config.max_refines_per_dimension`，默认 `2`。若当前维度未通过、尝试次数达到上限、还有其它 pending 维度，则返回 `next_question`。
4. 在 `director_sample_node` 中增加 coverage pressure 分支：满足同样条件时直接选择 `PLAN_SWITCH`，不让 bandit 抽回同一维。

**验证：**

```powershell
python -m pytest tests/unit/test_coverage_routing.py tests/unit/test_refine_lock.py
```

预期：refine lock 语义仍成立；超过上限时切换维度。

## 任务 4：Final report 覆盖感知 verdict

**文件：**

- `ai-interviewer/backend/app/engine/workflow/nodes/final_report.py`
- `ai-interviewer/backend/tests/unit/test_final_report_evidence.py`

**步骤：**

1. 增加 `_coverage_limited_verdict(verdict, dimension_status, scores_per_dim)`。
2. 规则：
   ```python
   if any(status in {"pending", "active", "failed"} and scores_per_dim.get(dim, 0.0) <= 0 for dim, status in dimension_status.items()):
       return "borderline" if verdict in {"strong_pass", "pass"} else verdict
   ```
3. 在 `final_report_node` 计算内部 verdict 后调用该 helper。
4. 报告增加 `coverage_warnings`，列出未覆盖或未通过维度。

**验证：**

```powershell
python -m pytest tests/unit/test_final_report_evidence.py tests/unit/test_closed_loop_report.py
```

预期：未覆盖维度会限制最高 verdict，但已有 report shape 不破坏。

## 任务 5：Answer lifecycle 分类

**文件：**

- `ai-interviewer/backend/app/engine/workflow/answer_lifecycle.py`
- `ai-interviewer/backend/app/engine/workflow/nodes/wait_answer.py`
- `ai-interviewer/backend/app/engine/workflow/state.py`
- `ai-interviewer/backend/tests/unit/test_answer_lifecycle.py`

**步骤：**

1. 新增分类函数：
   ```python
   AnswerIntent = Literal["normal", "empty", "clarification", "repeat", "too_short"]

   def classify_answer_intent(answer: str, previous_answers: list[str]) -> AnswerIntent:
       text = " ".join((answer or "").strip().split())
       if not text:
           return "empty"
       if len(text) < 12:
           return "too_short"
       if any(text == old for old in previous_answers[-3:]):
           return "repeat"
       if any(marker in text for marker in ("能再解释", "没听懂", "什么意思", "clarify", "repeat the question")):
           return "clarification"
       return "normal"
   ```
2. `wait_answer_node` 写入 `current_answer_intent`。
3. 第一阶段不改图拓扑：Evaluator 仍能处理所有输入，但 `evaluator_agent` prompt 与 report 可以读取 intent；`empty/too_short/clarification` 不更新 bandit reward，由 `reward_update_node` 跳过。
4. 若用户接受第二阶段，再新增 `answer_repair_node` 实现不计分重问。

**验证：**

```powershell
python -m pytest tests/unit/test_answer_lifecycle.py tests/unit/test_raw_answer_lifecycle.py
```

预期：分类字段写入状态，PII raw-answer 清理不回退。

## 任务 6：问题改写后同步 contract

**文件：**

- `ai-interviewer/backend/app/engine/workflow/nodes/ask_question.py`
- `ai-interviewer/backend/tests/unit/test_question_rewrite_contract_sync.py`

**步骤：**

1. 新增 helper：
   ```python
   def _fallback_contract_for_rewritten_question(dimension: str, question: str, target_skills: list[str], target_difficulty: str) -> PlanContract:
       focus = "、".join(target_skills[:3]) if target_skills else _display_dimension(dimension)
       return {
           "must_cover": [focus, "具体例子", "方案取舍"],
           "acceptable_if_missing": [],
           "acceptance_checks": [
               f"回答围绕{focus}展开。",
               "回答包含候选人亲身经历中的具体场景。",
               "回答说明至少一个方案取舍或失败处理。",
           ],
           "minimum_bar": "至少给出一个真实项目场景，并说明做法与取舍。",
           "review_focus": ["真实经历", "取舍清晰度", "结果或复盘"],
           "bar_level": difficulty_to_bar_level(target_difficulty),
           "signed_by": ["generator"],
       }
   ```
2. 在 `_rewrite_duplicate_question` 或 `_rewrite_non_chinese_question` 标记出现后，用新 helper 覆盖 `contract`。
3. 测试断言新问题与 `acceptance_checks` 同时包含相同 focus。

**验证：**

```powershell
python -m pytest tests/unit/test_question_rewrite_contract_sync.py tests/unit/test_target_skills.py tests/unit/test_plan_contract_p0.py
```

预期：fallback 问题不再沿用旧 contract。

## 任务 7：整体验证

**文件：** 不新增生产代码。

**步骤：**

1. 运行主链路单测：
   ```powershell
   python -m pytest tests/unit/test_evaluator_pass_invariants.py tests/unit/test_reward_after_verification.py tests/unit/test_coverage_routing.py tests/unit/test_answer_lifecycle.py tests/unit/test_question_rewrite_contract_sync.py
   ```
2. 运行既有回归套件：
   ```powershell
   python -m pytest tests/unit/test_plan_contract_p0.py tests/unit/test_refine_lock.py tests/unit/test_target_skills.py tests/unit/test_raw_answer_lifecycle.py tests/unit/test_final_report_evidence.py tests/unit/test_closed_loop_report.py tests/unit/test_verifier_adaptive_trigger.py
   ```
3. 读取编辑文件 lint：
   ```text
   使用 ReadLints 检查上述修改文件。
   ```

**验证：** 所有 pytest 通过，ReadLints 无新增错误。  
**提交：** 只有用户明确要求时才 commit。

## 风险与取舍

- `reward_update_node` 改变 reward 写入位置，需确认 tracer / rehydrate 是否依赖 `trace_evaluator.immediate_reward_applied=True`。如果依赖强，优先在 tracer 中新增 reward_update 事件，而不是复用 evaluator 事件。
- `coverage-aware routing` 可能减少深挖强度，所以默认 refine 上限先设为 2，并允许 `runtime_config.max_refines_per_dimension` 调整。
- `answer_lifecycle` 第一阶段只分类与跳过 reward，不立即改成重问流程，避免一次改动触碰太多图拓扑。
- `question rewrite contract` 使用 generator-only contract，牺牲 evaluator co-sign，但比旧问题 contract 评分新问题更可靠。

## 完成标准

- 低分或 must-cover 缺失时，模型返回 `passed: true` 也不能通过。
- Verifier 打回的回合不会奖励原错误策略。
- 未覆盖维度会影响最终 verdict 或产生明确 coverage warning。
- 连续 refine 不会无限吞掉其它维度预算。
- 空答、澄清、重复答能被识别，不进入正常 reward 信号。
- 改写后的中文/去重问题与 contract 保持一致。
