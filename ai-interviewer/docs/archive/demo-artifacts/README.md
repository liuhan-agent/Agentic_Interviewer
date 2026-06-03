# Demo Artifacts — LangSmith 作品集素材

本目录沉淀 `Agentic Interviewer` 端到端面试流水线的**可复现快照**，便于：

1. 作为 **LangSmith / 简历作品集的静态 snapshot**（不依赖任何外部 API key）
2. 部署回归时的 **before/after 对照基准**
3. 新成员快速理解 `evidence_spans → verifier → drift → adaptive-trigger` 闭环的实际输出形状

所有产物均由确定性 **stub LLM**（`LLM_PROVIDER=stub`）驱动，`openai_api_key` 留空即自动切入。

---

## 文件清单

| 文件 | 来源命令 | 展示内容 |
|---|---|---|
| `smoke_evidence_drift.log` | `python -m app.scripts.smoke_evidence_drift`（L1+L2 开） | L1 Verifier drift + L2 evidence-span alignment 两条线全链路观测：`EVIDENCE_SPAN_ALIGNMENT` 在 Evaluator 输出里注入 `evidence_spans[*].match ∈ {exact, fuzzy, none}`；`ENABLE_VERIFIER_DRIFT_MONITOR` 在 `verification_node` 出口记 `DriftEvent`；HTTP `/admin/drift/verifier` 端点返回滚动窗口 snapshot。 |
| `smoke_after_with_adaptive.log` | 同上 + `VERIFIER_ADAPTIVE_TRIGGER=true` | 新增 **adaptive trigger 反馈闭环**。本轮样本 <30 所以 adaptive 不启动；showcase 该 knob 已正确接线，等待样本充足后自动放大/缩小 verifier 触发率。 |
| `smoke_phase5_full_stack.log` | 同上 **所有 Phase 5 + V6 flag 全开**（`ENABLE_EVALUATOR_PROMPT_FEEDBACK` · `ENABLE_GENERATOR_AVOID_PATTERNS` · `ENABLE_SKILL_INJECTION` · `ENABLE_LLM_MEMORY_SELECTOR` 一并 true） | 证明 Harness 治理整套组件链路互通：drift 监视 → adaptive verifier → drift → evaluator/generator 双向反哺 → skill 注入 → LLM memory selector，端到端一个 snapshot 采全。 |
| `run_demo_stub.log` | `python -m app.scripts.run_demo --turns 6 --threshold 7.0 --budget 10`（Phase 4 基线） | 6 轮完整面试的 stub trace：每轮 Q/A/score/strengths/weaknesses + Thompson sampling diagnostics + final_report JSON + closed-loop summary。 |
| `run_demo_with_adaptive.log` | 同上 + adaptive 开关 ON | 同结构，附 adaptive trigger 已开启的 run 对照；本轮 sample 不足所以行为等价于 baseline。 |
| `../../run_demo_memory.log` | 同 `run_demo_stub.log` 但 Phase 5 + V6 所有 flag 全开（仓库根） | 作为根目录可复现证据，证明 Phase 5 Harness 全套打开时 `run_demo` 依然 6 轮 `strong_pass`、`closed_loop_ready=true`；供简历审阅者不进子目录直接查看。 |

---

## 关键 snapshot 节选

### Evidence span 对齐（L2）

Evaluator 现在为每条 `acceptance_check_results[*].evidence` 附带一个定位 span，可直接驱动前端高亮：

```json
{
  "Names an invalidation strategy.": {
    "verdict": "yes",
    "evidence": ["invalidate on write"],
    "evidence_spans": [
      { "text": "invalidate on write", "start": 51, "end": 70, "match": "exact" }
    ]
  },
  "Discusses consistency trade-off.": {
    "verdict": "partial",
    "evidence": ["this quote is not in the answer"],
    "evidence_spans": [
      { "text": "this quote is not in the answer", "start": -1, "end": -1, "match": "none" }
    ]
  }
}
```

`match=none` 即 Verifier 可据此直接挑 bluff：Evaluator 引用了一段根本不在候选人答案里的"证据"。

### Verifier drift（L1）

```json
{
  "window_size": 20,
  "samples": 1,
  "calls": 1,
  "overrides": 1,
  "override_rate": 1.0,
  "span_miss_rate": 0.333,
  "per_dimension": {
    "system_design": {
      "calls": 1, "overrides": 1, "span_miss_rate": 0.333
    }
  },
  "overruled_patterns": [{
    "dimension": "system_design",
    "check": "Names an invalidation strategy.",
    "reasons_sample": ["consistency quote does not actually appear in the answer"]
  }]
}
```

### Adaptive trigger（新增闭环）

`should_trigger()` 现在在 baseline 规则之上叠加 drift 反馈层：

```
per_dim.override_rate >= 0.25 (HIGH) & calls >= 30 → 强制触发 verifier
per_dim.override_rate <= 0.05 (LOW)  & score > threshold+margin → 跳过 verifier
其他区间 → 走 baseline 规则
```

即：**高漂移维度自动加大 verifier 采样率**（抓更多 bluff），**低漂移维度经过 30+ 次样本积累后赢得信任，省掉 LLM call**。完整决策树见 `app/engine/agents/verification.py::_adaptive_trigger_override`，配置见 `.env.example`。

---

## 复现方法

```bash
cd backend
./.venv/Scripts/Activate.ps1          # Windows PowerShell
# 1. L1+L2 smoke
$env:EVIDENCE_SPAN_ALIGNMENT='true'
$env:ENABLE_VERIFIER_DRIFT_MONITOR='true'
$env:LLM_PROVIDER='stub'
python -m app.scripts.smoke_evidence_drift

# 2. 带 adaptive 开关的 smoke
$env:VERIFIER_ADAPTIVE_TRIGGER='true'
$env:VERIFIER_ADAPTIVE_MIN_SAMPLES='30'
python -m app.scripts.smoke_evidence_drift

# 3. 全流程 demo（6 轮）
python -m app.scripts.run_demo --turns 6 --threshold 7.0 --budget 10
```

---

## 对接 LangSmith（可选）

若要生成真正的 LangSmith trace 链接，在 `.env` 中填入：

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_xxx
LANGSMITH_PROJECT=agentic-interviewer
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-xxx
```

然后重跑同样的 `run_demo` / `smoke_evidence_drift` 即可在 LangSmith UI 看到每一跳：`resume_parse → director_sample → ask_question (Generator + RAG) → wait_answer → evaluator (Evaluator agent) → verification_node (Verifier agent) → refine/end`。stub 版本与 LangSmith 版本结构完全一致，只是 LLM 输出来自真实模型。
