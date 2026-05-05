# L3.5：Drift → Evaluator prompt 反哺

> 本 plan 延续 `PLAN_VERIFIER_DRIFT.md §11 后续钩子 3`（L3.5）与
> `PLAN_EVIDENCE_SPANS.md §8 后续钩子 L1` 的承诺：
> 把 verifier drift monitor 识别到的 "evaluator 一直被 verifier 翻判的 pattern"
> 抽成 **few-shot 负例**，回写到 Evaluator 的 prompt 作为"反面教材"。
>
> 依赖：
> - Phase 1（Context Builder 全角色迁移）已完成 → Evaluator 走
>   `build_context_frame_for_evaluator`，注入 slot 不再需要改 Agent 代码。
> - L1 Verifier drift monitor 已落（`app/ml/drift/verifier_drift.py`）。
> - L2 Evidence span alignment 已落（提供 evidence quote 信号源）。

## 0. 设计目标

- **Closed loop**：drift 监测不再只是"观察"，而是"观察 → 沉淀 → 反哺"完整一环，对齐 Hermes closed-loop learning 模式。
- **Opt-in**：新 flag `enable_evaluator_prompt_feedback: bool = False` 默认关；关闭时 prompt 字节不变，现有 355 个测试不退步。
- **Zero new LLM call**：聚合 + 拼接都是纯 Python，无额外模型调用；Evaluator 还是原来那次 LLM 调用，只是 prompt 里多了一段 context。
- **Additive frame API**：`build_context_frame_for_evaluator` 新增一个**默认空字符串**的 `drift_negatives` kwarg，空值时 `frame.dynamic_system=""`（即保持现有 Evaluator 的 2-message 结构）；非空时塞进 `dynamic_system`，走 renderer 3-message 结构（与 Generator 同款）。
- **不改 evaluator_task.md prompt 文件**：负例块作为独立 system message 插入，不污染 user task 模板。

**明确不做**（延后钩子见 §9）：

- **不把 negatives 做成"Evaluator 重训练样本"**：那是 L4 / DPO 微调的路径，需要 ≥5k trace，不在本 plan 范围。
- **不做 drift pattern 的 LLM 提炼**：Step 1-2 用纯规则聚合（"top-N overruled acceptance_check + 代表性 evidence quote"），后续如果信号质量不够可再加 LLM 蒸馏（L3.6）。
- **不做 RAG 反哺**（PLAN_EVIDENCE_SPANS §8 的 L3）：这条路径是"被翻判的 evidence 文本入独立 vector store 给 Generator 规避"，与 Evaluator prompt 反哺是平行的两条闭环，本 plan 只做 L3.5。
- **不改 Verifier 的触发阈值**：`should_trigger` 规则保留。

---

## 1. 最终状态示意

```
verifier drift monitor (已在，本 plan 扩展 3 字段)
  │
  │  DriftEvent += {overruled_check_name, evaluator_evidence_quotes, evaluator_verdict}
  │
  ▼
VerifierDriftMonitor.snapshot()
  += "overruled_patterns": [
      {"dimension": ..., "check": ..., "count": 3,
       "sample_evidence": ["token bucket", "Raft catch-up"],
       "reasons_sample": ["buzzword heavy", ...]},
      ...
  ]
  │
  ▼
app/ml/drift/prompt_feedback.py  (新文件)
  └─ build_evaluator_drift_negatives(...) -> str
       读 snapshot().overruled_patterns
       过滤 (count >= min_support) & top-N
       渲染成一段 plain-text 负例块：
         ## Prior Evaluator Drift (negative examples)
         The Verifier recently overruled these evaluator calls on
         ``<dimension>``:
         - Check "<check>" was marked "yes" by the evaluator based on
           evidence like ``token bucket``; the verifier downgraded with
           reasons: buzzword heavy.
         - ...
         Use these as cautionary tales: do NOT repeat the same mistake
         on similar future answers.

evaluator_node  (按 flag 注入)
  └─ if settings.enable_evaluator_prompt_feedback:
        drift_block = build_evaluator_drift_negatives(dimension=...)
        evaluate_answer(..., drift_negatives=drift_block)
     else:
        evaluate_answer(..., drift_negatives="")   # 默认，等价于现在

build_context_frame_for_evaluator(drift_negatives="")
  └─ ContextFrame(
        static_system=system_skeleton,
        dynamic_system=drift_negatives,   # 空 -> 不渲染第二个 system message
        payload=...,
     )

frame_to_evaluator_messages
  └─ renderer._system_messages_from_frame(frame)
     当 drift_negatives 非空时多出一个 system message，
     自然走现有 "static + dynamic + user" 三段式；
     drift_negatives="" 时退化为现有 "static + user" 二段式。
```

---

## 2. 模块清单

| 文件 | 动作 | 变更摘要 |
|---|---|---|
| `app/ml/drift/verifier_drift.py` | 扩展 | `DriftEvent` +3 字段（默认值保持 backward-compat）；`snapshot()` 输出多一个 `overruled_patterns` 键（空列表时不影响现有消费者） |
| `app/engine/workflow/nodes/verification.py` | 小改 | `_record_drift_event` 提取被 verifier 翻判的 check 名与 evaluator 引用的 evidence quotes（只在 `overruled=True` 时填；否则 None / ()） |
| `app/ml/drift/prompt_feedback.py` | 新增 | `build_evaluator_drift_negatives()`：从 snapshot 聚合 top-N pattern，渲染 markdown 负例块；空样本返回 `""` |
| `app/engine/context/builder.py` | 小改 | `build_context_frame_for_evaluator` 加 `drift_negatives: str = ""` kwarg；空时 `frame.dynamic_system=""`；非空时 `frame.dynamic_system=drift_negatives` |
| `app/engine/agents/evaluator_agent.py` | 小改 | `evaluate_answer` 加 `drift_negatives: str = ""` kwarg；传给 builder；legacy 分支不使用（保持 Phase 1 双路径的对称性） |
| `app/engine/workflow/nodes/evaluator.py` | 小改 | 按 flag 在 evaluate_answer 前调用 `build_evaluator_drift_negatives`，传进去 |
| `app/core/settings.py` | 扩展 | +2 字段：`enable_evaluator_prompt_feedback: bool = False`；`drift_feedback_top_n: int = 3` |
| `tests/unit/test_drift_overruled_patterns.py` | 新增 | 6-8 case：pattern 聚合正确 / top-N 截断 / min_support 过滤 / 空窗口返回空列表 |
| `tests/unit/test_evaluator_drift_feedback.py` | 新增 | `build_evaluator_drift_negatives` 空窗口返回 `""`；非空时渲染格式稳定；top-N 顺序 |
| `tests/unit/test_evaluator_drift_injection.py` | 新增 | 集成：flag ON + 注入 event → `evaluator_node` 产出的 messages 包含负例段；flag OFF → messages 与 Phase 1 完全一致 |
| `tests/unit/test_evaluator_equivalence.py` | 小改 | 现有 case 显式传 `drift_negatives=""` 保持绿（零字节 diff） |
| `README.md` | 小改 | "Context engineering" 段追加"drift → evaluator prompt feedback"一行 |

---

## 3. 步骤（每步独立 commit，失败可单步回滚）

### Step 1 · DriftEvent 扩展 + snapshot 聚合

**DriftEvent 新字段**（全部带默认值，现有 call-site 零改动）：

```python
@dataclass(frozen=True)
class DriftEvent:
    # ...existing fields...
    # Phase 2 additions (default values = backward-compat zero):
    overruled_check_name: str | None = None
    evaluator_evidence_quotes: tuple[str, ...] = ()
    verifier_reasons: tuple[str, ...] = ()
```

**snapshot 聚合**：沿着 `events` 过一遍，`if e.overruled and e.overruled_check_name` → 按 `(dimension, check_name)` 累加 count + 收集 evidence / reasons 样本。top-N 按 count 降序；min_support 过滤低于阈值的项。

聚合输出形如：

```python
{
    ...existing keys...,
    "overruled_patterns": [
        {
            "dimension": "system_design",
            "check": "explains isolation per user",
            "count": 3,
            "sample_evidence": ["token bucket", "Raft catch-up"],
            "reasons_sample": ["buzzword heavy", "missing mechanism"],
        },
        ...
    ],
}
```

**验收**：
- `test_drift_overruled_patterns.py` 覆盖：空事件返回空列表；counts 正确；top-N 截断；相同 dim+check 合并；evidence / reasons 去重保留前 5 条
- 现有 `test_verifier_drift.py` 全部保持绿（新字段默认值无侵入）

**预估**：**1.5h**

---

### Step 2 · prompt_feedback 模块

**新文件 `app/ml/drift/prompt_feedback.py`**：

```python
def build_evaluator_drift_negatives(
    *,
    dimension: str | None = None,
    top_n: int = 3,
    min_support: int = 2,
) -> str:
    """Render a markdown negative-examples block from the drift monitor.

    Returns an empty string when there are no patterns meeting
    ``min_support`` so callers can unconditionally pass the result
    into the builder: ``drift_negatives=""`` collapses the dynamic
    system layer back to the pre-feedback state (see Phase 1
    ``ContextFrame.dynamic_system`` semantics).
    """
```

**输出示例**（非空分支）：

```markdown
## Prior Evaluator Drift (negative examples)

The Verifier has recently overruled evaluator "pass" calls. When
grading the current answer, treat these as cautionary patterns:

- On dimension `system_design`, the check "explains isolation per
  user" was marked yes 3 time(s) based on evidence like `"token
  bucket"`, `"Raft catch-up"`; the Verifier downgraded with reasons:
  "buzzword heavy"; "missing mechanism".
- ...

Do NOT repeat the same mistake if the current answer exhibits
similar shallow evidence.
```

**设计要点**：
- 接受可选 `dimension` 参数——当 evaluator 只想看当前维度的负例时（大多数调用点），过滤 patterns；`dimension=None` 返回全维度。
- 空时返回 `""`，不抛异常。
- Markdown 不 render 复杂表格，用 `-` bullet + `` `code` `` 短 quote，方便 LLM 读。

**验收**：
- `test_evaluator_drift_feedback.py`：零 pattern 返回 `""`；≥1 pattern 渲染出包含"Prior Evaluator Drift"前缀的字符串；top-N 尊重
- 不触发 LLM 调用（纯字符串拼接）

**预估**：**1.5h**

---

### Step 3 · evaluator builder 支持 drift_negatives

**改 `build_context_frame_for_evaluator`**：

```python
def build_context_frame_for_evaluator(
    *,
    # ...existing kwargs...,
    drift_negatives: str = "",
    turn_idx: int = 0,
) -> ContextFrame:
    # ...
    return ContextFrame(
        agent_role="evaluator",
        turn_idx=turn_idx,
        static_system=static_system,
        dynamic_system=drift_negatives,  # "" == Phase 1 behaviour
        payload=payload,
    )
```

**`evaluate_answer` 同步加 kwarg** + 传递给 builder；legacy 分支不改（保留 byte-identical 测试）。

**验收**：
- `test_evaluator_equivalence.py` 全部保持绿（显式传 `drift_negatives=""`）
- 新增 case：传 `drift_negatives="NEGATIVES"` 时，messages 列表多一个 `system` 消息，content 等于 "NEGATIVES"

**预估**：**0.5h**

---

### Step 4 · evaluator_node 按 flag 注入

**改 `evaluator_node`**：

```python
def evaluator_node(state: InterviewState) -> dict[str, Any]:
    # ...existing code...
    drift_negatives = ""
    if get_settings().enable_evaluator_prompt_feedback:
        try:
            drift_negatives = build_evaluator_drift_negatives(
                dimension=dimension,
                top_n=get_settings().drift_feedback_top_n,
            )
        except Exception as e:  # pragma: no cover - feedback must not break eval
            log.debug("drift feedback failed: %s", e)

    evaluation = evaluate_answer(
        # ...
        drift_negatives=drift_negatives,
    )
    # ...
```

**验收**：
- flag OFF 时 `drift_negatives=""` → 与 Phase 1 行为完全一致
- flag ON + drift monitor 有数据时 → prompt 里能看到负例段

**预估**：**0.8h**

---

### Step 5 · Settings + 集成测试

**Settings 新字段**（默认值 = 关闭）：

```python
enable_evaluator_prompt_feedback: bool = False
drift_feedback_top_n: int = 3
drift_feedback_min_support: int = 2
```

**新测试 `test_evaluator_drift_injection.py`**（集成级别）：

1. flag OFF + drift monitor 注入 5 个 DriftEvent → `evaluator_node` 产出的内部 messages 与 Phase 1 一致
2. flag ON + drift monitor 注入 5 个 DriftEvent（3 个 overruled+命中阈值）→ messages 多一个 system 消息，内容含 "Prior Evaluator Drift"
3. flag ON + drift monitor 为空 → 退化为 OFF 等价（空 drift_negatives）

**验收**：
- 全量 pytest 通过（≥355 → ≥365 case）
- `ReadLints` 无新增错误
- 手动：`ENABLE_EVALUATOR_PROMPT_FEEDBACK=true` + `python -m app.scripts.run_demo`，evaluator 调用前后 `curl /admin/drift/verifier` 能看到新增 `overruled_patterns` 键

**预估**：**1.0h**

---

## 4. 风险与回滚

| 风险 | 发生步骤 | 缓解 | 回滚 |
|---|---|---|---|
| snapshot 增加 `overruled_patterns` 键破坏现有 admin 端点消费者 | Step 1 | 键是 additive；现有消费者按已知键读取，不影响 | 删除该键即可 |
| `build_evaluator_drift_negatives` 拼字符串时误把 evidence quote 里的 `{}` 当成 format placeholder | Step 2 | `render_prompt` 只作用在 evaluator_task.md，drift block 是独立 system message 不走 format | 单字符串转义 |
| drift block 太长挤掉 prompt token budget | Step 2 | 硬上限：top_n=3 + 每 pattern evidence 前 5 条 + truncate 至 80 chars；整段 ≤ 600 chars | 调小 top_n |
| flag ON 时 LLM 计费上升（prompt 变长 + cache miss） | Step 4 | 默认 OFF；ON 时 dynamic_system 不 cache（本来就不 cache）；Evaluator 调用次数不变 | 关 flag |
| drift monitor 单进程内存窗口，重启丢失 | 全局 | 已在 PLAN_VERIFIER_DRIFT §11 记录 persistence follow-up；本 plan 沿用进程内行为，够 "demo + 单 worker 生产" | 无；未来 persistence plan 解决 |
| build 失败导致 evaluator 崩溃 | Step 4 | try/except + log.debug；空负例就等于没启用 | 关 flag 或删 node 里的调用 |

---

## 5. 验收标准（DoD）

- [ ] Step 1-5 全部合入主干
- [ ] 全量 pytest 通过；新增 20+ case 全绿
- [ ] `ReadLints` 无新增错误
- [ ] 手动：
  - [ ] flag OFF 跑 `run_demo` → 输出 KPI 与 Phase 1 基线一致
  - [ ] flag ON 先跑一次建立 drift 数据，再跑第二轮 → 第二轮 evaluator prompt 里能看到 `## Prior Evaluator Drift` 段
  - [ ] `/admin/drift/verifier` 返回的 JSON 多出 `overruled_patterns` 键
- [ ] README 更新
- [ ] `PLAN_CONTEXT_BUILDER_PHASE1.md §9 钩子 2 "Slot Registry 规范化"` 依赖的 payload key 不冲突（本 plan 只用 `dynamic_system`，不抢 payload 命名空间）

---

## 6. 预估工作量

| Step | 代码 | 测试 | 文档 | 合计 |
|---|---|---|---|---|
| 1 DriftEvent 扩展 + aggregation | 0.8h | 0.7h | 0 | 1.5h |
| 2 prompt_feedback 模块 | 0.8h | 0.7h | 0 | 1.5h |
| 3 Evaluator builder slot | 0.3h | 0.2h | 0 | 0.5h |
| 4 evaluator_node 注入 | 0.4h | 0.4h | 0 | 0.8h |
| 5 Settings + 集成测试 + README | 0.3h | 0.5h | 0.2h | 1.0h |

**合计 ≈ 5.3 人时**（不含 review），单日可落完。

---

## 7. 后续钩子（本 plan 不做）

1. **Persistence to DB / Redis**（PLAN_VERIFIER_DRIFT §11 后续钩子 1）：drift window 跨进程/重启保留；结合 feedback 变成真正的"长期评估纠偏"。
2. **LLM-distilled pattern summary**（L3.6）：把 top-N pattern 再喂给一个 cheap LLM 做"抽象共性 + 生成更自然的负例描述"，替代纯规则聚合。触发条件：当前规则渲染出的负例在 A/B 测试中 Evaluator 行为改进不显著。
3. **Generator RAG 反哺**（PLAN_EVIDENCE_SPANS §8 L3）：平行路径，被 verifier 挑过 bluff 的 evidence 文本入独立 vector store，下次 generator 起草同维度问题时规避。
4. **Alerting + Grafana dashboard**（PLAN_VERIFIER_DRIFT §11 后续钩子 2）：`override_rate` / `overruled_patterns.count` 过阈值时 Slack 告警。

---

## 8. 一页总结

> **把 drift 监测从"观察"升级成"observe → consolidate → feed-back"的闭环。**
>
> 5.3 人时 / 单日落地 / 新增字段全部带默认值 / feature flag OFF 默认保 byte-identical。做完之后：
> - Evaluator prompt 里首次出现**可自动更新的反面教材**；
> - 对齐 Hermes "learning as runtime capability"；
> - 与后续"RAG 反哺 Generator"形成左右双翼，支撑 Phase 3 "closed-loop" 叙事。
