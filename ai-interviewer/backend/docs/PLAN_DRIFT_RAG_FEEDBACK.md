# Drift → Generator 反哺（L3，精简版）

> 延续 `PLAN_EVIDENCE_SPANS.md §8 后续钩子 L3`：
> 把 Verifier 在历史上挑过 bluff 的 evidence 文本变成 Generator 起草
> 下一道题时的"应规避模式"，补齐 Evaluator（L3.5 已做）+ Generator 的
> **双向反哺** 闭环。
>
> **核心简化决策**：不新建独立 Chroma collection；**复用现有 drift
> monitor 的 ``overruled_patterns`` 作为 backing store**。这样：
>
> - 零新基础设施（向量库 / 新 DB schema）
> - 和 `PLAN_DRIFT_FEEDBACK.md`（Evaluator 反哺）共用一个数据源
> - 工时从 8-10h 降到 3-4h
> - 独立 vector store 作为 Phase 4 的 upgrade hook 保留

---

## 0. 设计目标

- **语义对称于 Evaluator 反哺**：
  - 方向 2（已做）`build_evaluator_drift_negatives(...)` → 给 Evaluator 的 `dynamic_system`：
    "这些 evidence 模式已经被 Verifier 翻判过 N 次，打分时要警惕"
  - 方向 4（本 plan）`build_generator_avoid_patterns(...)` → 给 Generator 的 `payload.avoid_patterns`：
    "不要问那种容易被这些 shallow evidence 糊弄过去的问题"
- **同源不同视角**：两者都从 `VerifierDriftMonitor.snapshot().overruled_patterns` 取料，但渲染成不同的 markdown 块给不同 agent 消费。
- **Opt-in 默认关**：`enable_generator_avoid_patterns: bool = False`，默认不污染现有 prompt。
- **额外 LLM 调用 = 0**：纯字符串聚合 + 渲染。

**不做**（延后到 Phase 4 钩子）：

- **独立 Chroma collection + embedding 检索**：目前按 `dimension` 硬匹配已经够用；当 discredited evidence 超过 ~50 条、且跨 dim 的语义相似性变得重要时，再升级到向量检索。
- **单独持久化到 DB**：drift monitor 重启会丢，这和 `PLAN_VERIFIER_DRIFT.md §11 钩子 1` 一起 Phase 3 再做。
- **不改 Evaluator 方向 2 的实现**：两个 feedback 函数独立，互不影响。

---

## 1. 最终状态示意

```
verifier_drift_monitor (已有)
  └─ snapshot().overruled_patterns: list[{dimension, check, count, sample_evidence, reasons_sample}]
        │
        │ (同一个数据源，两个消费者)
        │
        ├──→ build_evaluator_drift_negatives (已做，方向 2)
        │        → Evaluator dynamic_system 系统消息
        │          "grade strictly, these patterns got overruled"
        │
        └──→ build_generator_avoid_patterns (本 plan 新增)
                → Generator payload.avoid_patterns
                   "avoid drafting questions susceptible to these shallow answers"

evaluator_node (已有) + ask_question_node (扩展)
  ├─→ evaluator_node: settings.enable_evaluator_prompt_feedback
  └─→ ask_question_node._step_retrieve_strategy: settings.enable_generator_avoid_patterns
```

---

## 2. 模块清单

| 文件 | 动作 | 变更摘要 |
|---|---|---|
| `app/ml/drift/prompt_feedback.py` | 扩展 | +`build_generator_avoid_patterns(dimension, top_n, min_support) -> str` —— 同源不同渲染 |
| `app/core/settings.py` | 扩展 | +1 字段：`enable_generator_avoid_patterns: bool = False`；`drift_feedback_top_n` 和 `drift_feedback_min_support` 两个字段复用（两个 feedback 函数共用这两个阈值） |
| `app/engine/context/builder.py` | 小改 | `build_context_frame_for_generator` 加 `avoid_patterns: str = "(no historical shallow patterns on this dimension)"` kwarg；payload +`avoid_patterns` key |
| `app/engine/context/renderer.py` | 小改 | `_GENERATOR_PAYLOAD_KEYS` +`avoid_patterns` |
| `app/engine/agents/prompts/generator_task.md` | 小改 | frontmatter +`avoid_patterns` 变量；正文加 `AVOID_PATTERNS = {avoid_patterns}` 块 |
| `app/engine/agents/generator.py` | 小改 | `generate_question` 加 `avoid_patterns: str` kwarg，透传 |
| `app/engine/workflow/nodes/ask_question.py` | 小改 | `_step_retrieve_strategy` 按 flag 调 `build_generator_avoid_patterns`；`_step_draft_question` 透传 `avoid_patterns`；ctx 初始化 seed 占位符 |
| `tests/unit/test_generator_avoid_patterns.py` | 新增 | 3-5 case：空 drift / 阈值过滤 / 渲染格式 / dim 过滤 |
| `tests/unit/test_prompt_loader.py` | 小改 | `test_render_generator_task_end_to_end` 加 `avoid_patterns` kwarg |
| `tests/unit/test_context_builder.py` | 小改 | payload 断言加 `avoid_patterns` 默认占位符 |
| `tests/unit/test_context_renderer.py` | 小改 | `_full_payload` fixture 加 `avoid_patterns` 键 |
| `tests/unit/test_ask_question_skill_injection.py` | 小改 | 修 fixture stub settings 加 `enable_generator_avoid_patterns=False`（防副作用） |
| `backend/README.md` | 小改 | "Drift feedback (bidirectional)" 小节说明 + flag |
| `backend/docs/PLAN_DRIFT_RAG_FEEDBACK.md` | 新增 | 本文件 |

---

## 3. 步骤

### Step 1 · `build_generator_avoid_patterns` 函数

新函数加到 `app/ml/drift/prompt_feedback.py`，跟 `build_evaluator_drift_negatives` 并列：

```python
def build_generator_avoid_patterns(
    *,
    dimension: str | None = None,
    top_n: int = 3,
    min_support: int = 2,
) -> str:
    """Render a Markdown block telling the Generator which answer
    patterns it should draft questions AWAY from.
    ...
    """
```

**签名**与 `build_evaluator_drift_negatives` 完全对等，`dimension` / `top_n` / `min_support` 默认一致。但**渲染内容不同**：

- Evaluator 反哺渲染："grade strictly, do NOT accept similar evidence"
- Generator 反哺渲染："AVOID drafting questions that can be answered with shallow evidence like ..."

具体示例：

```markdown
## Avoid Patterns (historical verifier signal)

Prior evaluator "pass" verdicts on dimension `system_design` were
later overruled by the Verifier because the answer relied on
shallow framings. When drafting THIS question, aim to require
depth beyond:

- Check "explains isolation per user" was gamed 3 time(s) with
  evidence like `"token bucket"`, `"Raft catch-up"`; reframe the
  question so these quotes alone CANNOT satisfy it.
- ...
```

### Step 2 · Settings + builder / renderer / prompt / generator

- `enable_generator_avoid_patterns: bool = False`
- `generator_task.md` frontmatter +`avoid_patterns` 变量 + 块
- `build_context_frame_for_generator` 加 `avoid_patterns` kwarg
- `_GENERATOR_PAYLOAD_KEYS` +`avoid_patterns`
- `generate_question` 加 `avoid_patterns` kwarg

### Step 3 · ask_question_node 接入

在 `_step_retrieve_strategy` 里 skill 逻辑后面再追加：

```python
if getattr(settings, "enable_generator_avoid_patterns", False):
    try:
        from app.ml.drift.prompt_feedback import build_generator_avoid_patterns
        ctx["avoid_patterns"] = build_generator_avoid_patterns(
            dimension=ctx["dimension"],
            top_n=int(getattr(settings, "drift_feedback_top_n", 3)),
            min_support=int(getattr(settings, "drift_feedback_min_support", 2)),
        ) or ctx["avoid_patterns"]
    except Exception as e:  # pragma: no cover - feedback is non-critical
        log.debug("generator avoid-patterns render failed: %s", e)
```

注意：空 return 回退到 default 占位符，保持 prompt 稳定。

`_step_draft_question` 里加 `avoid_patterns=ctx.get("avoid_patterns", "...")`。

### Step 4 · 测试

- `test_generator_avoid_patterns.py`：空 monitor / 阈值未到 / 阈值过了 / top_n 截断 / dimension 过滤 / 长 evidence truncate
- 现有三个 test 文件小补丁（context builder / renderer / prompt_loader / ask_question_skill_injection）

### Step 5 · 文档

- README 加 "Drift feedback (bidirectional)" 小节，强调 L3/L3.5 同源不同视角
- 本 PLAN 文件
- 更新 `PLAN_DRIFT_FEEDBACK.md` 的 §6 后续钩子 4，标记为 "done"

---

## 4. 风险与回滚

| 风险 | 位置 | 缓解 | 回滚 |
|---|---|---|---|
| `avoid_patterns` 与 `strategy` / `skills` 槽位语义重叠，Generator 混淆 | generator_task.md | prompt 里三块分别命名 `STRATEGY_MEMORY` / `INTERVIEW_SKILLS` / `AVOID_PATTERNS`，语义由标题区分 | 人工审 prompt；flag 关掉 |
| drift 数据是历史低质量 evidence，让 Generator 过度回避常用概念 | build_generator_avoid_patterns | 默认 `min_support=2` 过滤 one-off；占位符在空时不注入 | 调大 `min_support` / 关 flag |
| 渲染 evidence 字符串里有 `{...}` 破坏 `.format` 替换 | prompt_feedback.py | 复用 `build_evaluator_drift_negatives` 同样的 `_truncate` 封装（已处理换行）；evidence 作为 literal 插入不会参与 format | 添加 escape 处理（目前 quote 来自 evaluator 提取，风险低） |
| Generator 受到 Evaluator 反哺 + Generator 反哺双重 bias，过度保守 | 全链 | 两个 flag 独立，可单独开关；A/B test 验证 | 只开其中一个 |

---

## 5. 验收标准（DoD）

- [ ] Step 1-5 全部合入
- [ ] 新 test 全绿（3-5 case）
- [ ] 全量 pytest 通过（当前 420 → ≥ 423）
- [ ] `ReadLints` 无新增错误
- [ ] 手动：`ENABLE_VERIFIER_DRIFT_MONITOR=true` + `ENABLE_GENERATOR_AVOID_PATTERNS=true` 跑 `run_demo`，Generator prompt 里能看到 `AVOID_PATTERNS = ...` 块
- [ ] README 加 "Drift feedback (bidirectional)" 小节
- [ ] `PLAN_EVIDENCE_SPANS.md §8 L3` 标记 done

---

## 6. 预估工作量

| Step | 代码 | 测试 | 文档 | 合计 |
|---|---|---|---|---|
| 1 build_generator_avoid_patterns | 0.5h | 0.4h | 0 | 0.9h |
| 2 settings + prompt + builder | 0.5h | 0.3h | 0 | 0.8h |
| 3 ask_question_node 接入 | 0.3h | 0.4h | 0 | 0.7h |
| 4 现有 test 小补丁 | 0.1h | 0.2h | 0 | 0.3h |
| 5 文档 | 0 | 0 | 0.5h | 0.5h |

**合计 ≈ 3.2 人时**。单日可落完。

---

## 7. 后续钩子（本 plan 不做）

1. **独立 Chroma collection + embedding 检索**（PLAN_EVIDENCE_SPANS §8 L3 的完整版）：
   当 discredited evidence 数量超过 ~50 条、语义相似性（而非 dim 精确匹配）变得重要时，新建 `drift_evidence_blocklist` collection，写入 `{text: quote, metadata: {dim, check, overruled_count, verifier_reasons}}`；Generator 起草问题前用 question text embedding 做 top-k 检索。
2. **Drift → Generator 的 A/B 效果实验**：给 runtime_config 加 `avoid_patterns_mode: "off" | "soft" | "strict"`，分别对应"完全不注入"/"只说 AVOID"/"AVOID + 强制重写"，用 bandit 数据对比 question quality。
3. **Drift → RAG knowledge base 反向污染防御**：如果同一 evidence quote 在 `interviewer_kb` 里也被标为"reference answer"，需要 cross-check 防止 Generator 引用 KB 时照样被 Verifier 翻判。

---

## 8. 一页总结

> **把方向 2（Evaluator 反哺）的 backing store 翻一面，给 Generator
> 开一个 "avoid shallow patterns" 的 slot**。同一个 drift monitor 同
> 时给 Evaluator 和 Generator 两个 agent 提供反馈信号；Evaluator 用
> 它更严、Generator 用它更深。
>
> 3.2 人时 / 零新基础设施 / feature flag 默认 OFF。做完之后
> "Observation (L1) → Consolidation (existing) → Feedback (L3 + L3.5)"
> 三环在 Evaluator 和 Generator 上都收口。
