# P0-2：Evaluator evidence_spans —— 让 Verifier 的对抗真正"有牙"

> 本 plan 仅做一件事：把 `acceptance_check_results` 从"标签 (yes/partial/no)"升级成"标签 + 原文证据"。
> 这是 Anthropic 三 Agent 对抗体系里 Verifier 能抓 bluff 的**前提**，当前 Verifier 只能看到评分结果、看不到 evaluator 是依据候选人答案哪一段打的分——抓 bluff 的能力被大幅削弱。

---

## 0. 设计目标

Evaluator 输出从：

```json
"acceptance_check_results": {"can describe CAP trade-off": "yes"}
```

升级为：

```json
"acceptance_check_results": {
  "can describe CAP trade-off": {
    "verdict": "yes",
    "evidence": ["在分区时我们选 AP，牺牲一致性", "用 Raft 的 log catch-up 补齐"]
  }
}
```

同时保持对**旧 shape**（纯字符串值）向后兼容，任何当前依赖 `acceptance_check_results.values()` 为字符串的代码都不应被打破。

**不做**：
- 不动 PlanContract schema（契约本身只有 `acceptance_checks: list[str]`，没有 evidence 要求）
- 不强制 evaluator 为每个 check 都给 evidence（允许空列表，见 Rule 3）
- 不改 bandit / outcome 链路
- 不新增 LLM call

---

## 1. 最终状态示意

```
evaluator_agent.evaluate_answer
  └─ 返回 acceptance_check_results: dict[str, CheckResult]
         where CheckResult = {"verdict": "yes|partial|no", "evidence": list[str]}
         或（向后兼容）= "yes|partial|no"   # legacy callers / 老 snapshot

verification_node
  └─ 把 evidence 列表喂给 Verifier prompt
      Verifier 可以在 reasons_to_doubt 里引用具体 evidence 片段
      Verifier rationale 可以反驳某条 evidence 是否真的支持 verdict

final_report (dimension_summaries[dim].evidence[turn].acceptance_checks)
  └─ 保留完整结构，产品层可以渲染"该问题被哪句话支撑"
```

所有字段都**additive**，LangGraph checkpoint schema 不变。

---

## 2. 模块清单

| 文件 | 动作 | 变更摘要 |
|---|---|---|
| `app/engine/agents/prompts/evaluator_task.md` | 小改 | 扩 schema 说明 + 新规则"每条 verdict 必须尝试给 1-3 条 evidence"；`contract` 为空时 evidence=[] |
| `app/engine/agents/evaluator_agent.py` | 小改 | 新增 `_normalize_check_result`：兼容旧字符串 shape 与新 dict shape；保持 `acceptance_check_results` 键不变 |
| `app/engine/agents/prompts/verifier_task.md` | 小改 | Verifier 现在可以在 EVALUATOR_REPORT 中看到 evidence；加规则"针对有 evidence 的 check，如果 evidence 不支撑 verdict 就给 partial/fail" |
| `app/engine/agents/verification.py` | 无 | `verify_answer` 已经把 evaluator_report 整段透传，evidence 自动跟进；不需要改代码 |
| `app/engine/workflow/nodes/verification.py` | 无 | `_apply_verification` 只看 verdict/confidence/reasons，不需要改 |
| `app/engine/workflow/nodes/final_report.py` | 小改 | `_acceptance_counts` 改为能从新 shape 读 `verdict`；`_turn_evidence` 保留完整 `acceptance_check_results` |
| `app/engine/workflow/nodes/experience_extractor.py` | 微改 | 不依赖 acceptance shape，已经安全，仅做 defensive 读 |
| `tests/unit/test_evaluator_evidence.py` | 新增 | 新 shape 单测 + 旧 shape 回退用例 |
| `tests/unit/test_verifier_evidence.py` | 新增 | evidence 被喂进 verifier prompt + verifier 能识别 weak evidence |
| `tests/unit/test_final_report_evidence.py` | 新增 | final_report 里每 turn 的 acceptance_checks 保留完整结构，counts 正确 |

---

## 3. 步骤（落地顺序；每步独立 commit）

### Step 1 · 约定新 shape 与兼容规则（无代码，只约定）

**规则**：
1. Evaluator 产出的 `acceptance_check_results[check]` 优先是 `{"verdict": "yes|partial|no", "evidence": [str, ...]}`。
2. 允许 evaluator 偶尔返回纯字符串（provider/模型变动时 fallback），下游**必须**把字符串视为 `{"verdict": s, "evidence": []}`。
3. 老的 snapshot（DB 里已经写过的 trace）不会被改写；只有新 session 走新 shape。
4. Verdict 归一化不变：non-{yes,partial,no} 一律视为 `"no"`。

**验收**：本 step 无代码变更，只在 `evaluator_agent.py` 文件头加一段 docstring 描述 shape 契约。

---

### Step 2 · Evaluator prompt + agent 代码

**evaluator_task.md 增量**：

```diff
 Reply with a single JSON object:
 
 {{
   "score": number (0-10),
   "passed": boolean,
   "strengths": ["..."],
   "weaknesses": ["..."],
   "rubric_coverage": {{"<rubric_point>": "covered|partial|missing"}},
-  "acceptance_check_results": {{"<acceptance_check>": "yes|partial|no"}},
+  "acceptance_check_results": {{
+    "<acceptance_check>": {{
+      "verdict": "yes|partial|no",
+      "evidence": ["verbatim quote from CANDIDATE_ANSWER", "..."]
+    }}
+  }},
   "recommended_next": "refine|advance|skip",
   "recommended_next_plan": "simple|adaptive|deep_probe|null",
   "rationale": "2-3 sentences"
 }}
```

新规则段（放 "How to populate" 下面）：

```
How to populate ``evidence``:
- Each verdict should be backed by 1-3 **short verbatim quotes** from
  CANDIDATE_ANSWER that justify it.
- Quotes MUST be substrings of the answer; do NOT paraphrase.
- If the answer does not contain anything supporting a "yes" (common
  for "no" verdicts), return ``"evidence": []``.
- Prefer the shortest quote that makes the decision unambiguous.
- If CONTRACT is empty or CANDIDATE_ANSWER is empty, return a single
  object ``{"verdict": "no", "evidence": []}`` per acceptance check.
```

**evaluator_agent.py 增量**：

新工具函数：

```python
def _normalize_check_result(
    raw: Any,
) -> dict[str, Any]:
    """Coerce one ``acceptance_check_results[key]`` value into the canonical
    ``{"verdict": "yes|partial|no", "evidence": list[str]}`` shape.

    Accepts three incoming shapes:

    - ``"yes"`` / ``"partial"`` / ``"no"``           (legacy string)
    - ``{"verdict": "..."}``                         (dict without evidence)
    - ``{"verdict": "...", "evidence": [str, ...]}`` (full new shape)

    Invalid verdicts default to ``"no"``; non-list evidence is dropped.
    """
    if isinstance(raw, str):
        verdict_raw = raw.strip().lower()
        verdict = verdict_raw if verdict_raw in {"yes", "partial", "no"} else "no"
        return {"verdict": verdict, "evidence": []}
    if isinstance(raw, dict):
        verdict_raw = str(raw.get("verdict", "")).strip().lower()
        verdict = verdict_raw if verdict_raw in {"yes", "partial", "no"} else "no"
        evidence_raw = raw.get("evidence") or []
        if not isinstance(evidence_raw, list):
            evidence_raw = []
        evidence = [str(e) for e in evidence_raw if e]
        return {"verdict": verdict, "evidence": evidence}
    return {"verdict": "no", "evidence": []}
```

替换当前解析（原 `raw_acceptance` 分支）：

```python
raw_acceptance = data.get("acceptance_check_results")
acceptance_checks_out: dict[str, dict[str, Any]] = {}
if isinstance(raw_acceptance, dict):
    for k, v in raw_acceptance.items():
        if not isinstance(k, str):
            continue
        acceptance_checks_out[k] = _normalize_check_result(v)
```

**向后兼容点**：
- `_derive_rubric_coverage` 内部读 `acceptance_check_results[k]` 来判 "yes/partial/no"，改一行：

```python
check_value = (
    acceptance_check_results[k].get("verdict")
    if isinstance(acceptance_check_results[k], dict)
    else acceptance_check_results[k]
)
```

- `passed` 条件里出现的 must_cover 是否被"至少 partial"判定——走的是 `coverage_out`，不直接读 `acceptance_check_results`，所以不需改。

**验收**：
- `test_evaluator_evidence.py::test_new_shape_parsed` 新 shape 被保留
- `test_evaluator_evidence.py::test_legacy_string_fallback` "yes" 字符串变 `{"verdict":"yes","evidence":[]}`
- `test_evaluator_evidence.py::test_invalid_verdict_coerced_to_no` 非法值归一
- 现有 `tests/unit/test_plan_contract_p0.py` 不应因此打破（向后兼容）

---

### Step 3 · Verifier prompt 消费 evidence

**verifier_task.md 增量**（只加一段 + 一条 Guidelines）：

```diff
 Guidelines:
 - Use "pass" only if the answer genuinely holds up AND every
   must_cover item in CONTRACT has at least partial coverage.
+- The EVALUATOR_REPORT now includes ``acceptance_check_results[*].evidence``
+  (short verbatim quotes from CANDIDATE_ANSWER). Inspect them:
+    * If an evidence quote does not actually support its "yes" verdict
+      (e.g. the quote is buzzword-heavy or the evaluator misread it),
+      downgrade to "partial" or "fail" and cite the quote in
+      ``reasons_to_doubt``.
+    * If a "yes" verdict has ``evidence=[]`` AND the contract check
+      was non-trivial (not "answer is non-empty"), treat it as a
+      contract inconsistency and downgrade.
 - Use "partial" if the evaluator accepted an answer that is
   handwavy, missing concrete examples, or leans on buzzwords.
```

`agents/verification.py` **不需要代码改动**：`verify_answer` 已经 `json.dumps(evaluator_report)` 整段透传，`acceptance_check_results` 只要 shape 是 JSON 可序列化就自动跟进去。

**验收**：
- `test_verifier_evidence.py::test_evidence_included_in_prompt` 用 snapshot/子串断言 render 后的 prompt 包含 `"evidence"` 且包含具体引用片段
- `test_verifier_evidence.py::test_existing_stub_path_unchanged` stub provider 返回的裁决流程没变

---

### Step 4 · final_report 保留 evidence

`_acceptance_counts` 需要从新 shape 抽 verdict：

```python
def _acceptance_counts(checks: dict[str, Any]) -> dict[str, int]:
    counts = {"yes": 0, "partial": 0, "no": 0, "total": 0}
    for raw in checks.values():
        if isinstance(raw, dict):
            value = str(raw.get("verdict", "")).strip().lower()
        else:
            value = str(raw).strip().lower()
        if value not in {"yes", "partial", "no"}:
            value = "no"
        counts[value] += 1
        counts["total"] += 1
    return counts
```

`_merge_contract_checks` 同理：用 `_normalize_check_result` 统一入 merged 字典（这样 `contract_summary.checks_*` 的计数继续正确）。

`_turn_evidence` 不需要改——它已经把 `acceptance_check_results` 整体塞进 `evidence[turn]`，新 shape 自然被带出来，产品前端/Data 管道可以直接消费。

**验收**：
- `test_final_report_evidence.py::test_acceptance_counts_dict_shape` 新 shape 下 counts 正确
- `test_final_report_evidence.py::test_acceptance_counts_mixed_shape` 半新半旧（混在 qa_history 里）也正确
- 现有 `tests/unit/test_closed_loop_report.py` 通过

---

### Step 5 · trace/trainset 防御性读（可选）

`app/data/trainset_builder.py` 如果拿 evaluation 直接导出，可能 acceptance_check_results 的值类型改变。

**排查**：

```bash
rg "acceptance_check_results" backend/app/data backend/app/scripts
```

如果有位置硬依赖字符串值，把读取改为 `verdict = v["verdict"] if isinstance(v, dict) else v`。

**验收**：
- 跑一次 `python -m app.scripts.export_daily_trainset --days 1 --out /tmp/t.jsonl`，jsonl 字段可被 json.loads 正常读回，且每行的 `acceptance_check_results` 保留 dict 结构（新 session）或字符串（老 session）。

---

## 4. 风险与回滚

| 风险 | 发生位置 | 缓解 | 回滚 |
|---|---|---|---|
| LLM 返回新 shape 不稳（evidence 列表时而缺失） | Step 2 | `_normalize_check_result` 始终产出 `{"verdict","evidence"}` + 允许 evidence=[]，不 raise | 只回滚 prompt 变更即可，agent 代码对旧 shape 兼容 |
| Verifier 过度因 "evidence=[]" 降级，误伤 trivial "yes" | Step 3 | prompt 明确写 "non-trivial check 才降级"；+ existing abstain 路径兜底 | 回滚 verifier_task.md |
| final_report 产品端直接 `v.lower()` 已打旧 snapshot | Step 4 | `_acceptance_counts` 新增 isinstance(dict) 分支，前端需要看 `v.verdict if dict else v` | 前端单独处理；后端已兼容两侧 |
| trainset 下游读 `v.strip()` 炸 | Step 5 | 用 ripgrep 扫一遍；加一个 `_verdict_of(v)` 小工具函数 | 加 helper 即可 |
| Evaluator 把 evidence 当 paraphrase（不是 substring） | Step 2 | prompt 明确"verbatim quote"；不做程序校验，仅留给 Verifier 判 | 无需回滚 |

每步独立 commit，revert 成本为单文件级。

---

## 5. 测试策略

**加**（3 个新测试文件，约 8-12 个 case）：

| 测试文件 | 覆盖 |
|---|---|
| `tests/unit/test_evaluator_evidence.py` | `_normalize_check_result` 的三种 shape；mock LLM 产出新 shape 的端到端；invalid verdict 归一；evidence=[] 保留 |
| `tests/unit/test_verifier_evidence.py` | verifier prompt 中能看到 evidence 字段；stub provider 流程不变；`_apply_verification` 对新旧 shape 都正确 |
| `tests/unit/test_final_report_evidence.py` | `_acceptance_counts` 对字典/字符串/混合 shape 正确；`contract_summary` 数字正确；`dimension_summaries[*].evidence[*].acceptance_checks` 保留原始 dict 结构 |

**不加**：
- Evaluator LLM 真实调用测试（跟现有策略一致，mock）
- Verifier LLM 真实调用测试
- final_report 的其余字段（已由 `test_closed_loop_report.py` 覆盖）

**关键测试基础设施**：
- 复用现有 stub LLM provider；新 shape 直接在 stub return 里构造
- 向后兼容测试：用 legacy 字符串 shape 走现有 `test_plan_contract_p0.py` 不动

---

## 6. 验收标准（DoD）

- [ ] Step 2/3/4 合入 main；Step 5 扫描完成
- [ ] 全量 pytest 通过，**特别是** `tests/unit/test_plan_contract_p0.py` 和 `tests/unit/test_verifier_abstain.py` 不变色
- [ ] 新增 3 个测试文件全绿
- [ ] 手动 `python -m app.scripts.run_demo`：  
  - state 日志里 `evaluation.acceptance_check_results.<check>.evidence` 非空（至少一个 turn）  
  - `final_report.dimension_summaries.<dim>.evidence[*].acceptance_checks` 结构是新 dict 而非字符串
- [ ] `curl localhost:8000/api/sessions/<id>/report`（如果有这路由）返回的 JSON 里 evidence 字段可用
- [ ] README 的 "Iterative Contract" 或 "Three-Agent Adversary" 段追加一条"evaluator now emits short verbatim evidence per acceptance check"

---

## 7. 预估工作量

| Step | 代码 | 测试 | 文档 | 合计 |
|---|---|---|---|---|
| 1 约定 shape | 0.1h | 0 | 0.1h | 0.2h |
| 2 evaluator prompt + agent | 0.6h | 0.7h | 0 | 1.3h |
| 3 verifier prompt + guidelines | 0.3h | 0.5h | 0 | 0.8h |
| 4 final_report 抽 verdict | 0.4h | 0.5h | 0 | 0.9h |
| 5 trainset 防御性扫描 | 0.3h | 0.2h | 0 | 0.5h |
| 文档收尾 | 0 | 0 | 0.3h | 0.3h |

**合计 ≈ 4.0 人时**（不含 review）。单日可落。

---

## 8. 后续钩子（本 plan 不做，记录）

- L1（P1）：**Evidence → verifier drift signal**：verifier 如果频繁基于同一类 "weak evidence" 翻判，统计到 `verifier_drift_monitor` 里，反向作为 evaluator prompt 的 few-shot 负例。属于 P1 的"verifier 自己被审计"。
- L2（P1）：**Evidence span alignment**：在 evidence 里存 `{"text": ..., "start": idx, "end": idx}` 而不仅是字符串，UI 可以高亮；LLM 给 offset 不稳，需 post-hoc fuzzy match。
- L3（P2）：**Evidence → RAG 反哺**：被 verifier 挑过 bluff 的 evidence 文本入一个独立 vector store，下一次 generator 起草同维度问题时可以**规避**这些"被识破的空话模式"，提升题目信噪比。
