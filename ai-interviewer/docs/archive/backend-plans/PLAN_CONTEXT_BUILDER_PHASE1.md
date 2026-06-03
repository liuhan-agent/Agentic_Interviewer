# Context Builder Phase 1 —— 把 slot-based 装配扩展到剩下 5 个 agent

> 本 plan 延续 `engine/context/__init__.py` 文件头注释的承诺：
>
> > Only the Generator role is wired up in Phase 0 and only behind the
> > ``Settings.use_context_builder`` flag. The public surface is designed
> > so follow-up PRs can add Evaluator / Verifier / Guard role adapters
> > without touching the caller side.
>
> Phase 0 接入了 Generator；Phase 0.5 接入了 Evaluator（见 `PLAN_EVIDENCE_SPAN_ALIGNMENT.md` 完工后的清理轮）。
> 本 Phase 1 把剩下 **5 个 agent role** 全部接入同一套 `ContextFrame + renderer` 基座：
> Verifier / Guard / Contract-Negotiator / Session-Summarizer / Coach。
>
> 做完之后 `settings.use_context_builder=True` 才真正"全局一致"：所有 agent 的 prompt 都走
> `static_system(cacheable) + dynamic_system(session-scoped) + payload(per-turn)` 三层装配，
> Anthropic prompt cache 在 7/7 agent 上生效，后续 "slot 注入" 类改造（drift 反哺 / skills 加载 / A/B prompt）只需要扩 `payload` 键，不再污染 agent 代码。

---

## 0. 设计目标

- **Invariant first**：每个被迁移的 agent，新路径（builder+renderer）产出的 `list[ChatMessage]` **必须与 legacy 路径 byte-identical**，由 `test_<role>_equivalence.py` 锁死。现有单测（`test_verifier_abstain` / `test_guard_pii` / `test_plan_contract_p0` / `test_session_summarizer` / 等）保持全绿。
- **Opt-in rollout**：沿用 Phase 0 的 `settings.use_context_builder: bool = False` 单旗。本 Phase 全程不翻这个 flag；翻 flag 单独作为 Step 6 的独立 commit，可回退。
- **Zero new LLM call / Zero schema change**：所有改动都是 prompt 装配层的 refactor，不动 prompt 文本、不动 agent 输出契约、不动 `InterviewState` 字段、不动 DB schema。
- **Additive frame API**：`frame.py` 的 `AgentRole` Literal 已经预留了全部 6 个角色，只需往 `builder.py` / `renderer.py` 增补函数，不改 `ContextFrame` dataclass。

**明确不做**（延后钩子见 §9）：

- **不迁移** `rubric_negotiator`：`generator.negotiate_rubric` 是 legacy 的轻量 stand-in，payload 只有 2 个字段，迁移收益低；保留 inline 或在后续 Plan 里直接与 `contract_negotiator` 合并下线。
- **不为 drift 反哺 / skills 加载预留空 slot**：Phase 1 只搬家，不提前设计。方向 2 / 3 的 plan 各自扩 payload 键。
- **不动 Anthropic cache_control 的策略**：5 个新 agent 默认 `static_system` 置空或极短（这些 agent 没有共享 `system_skeleton.md`），因此 `cache_control="ephemeral"` 默认不加；如果未来发现命中率低再打开。

---

## 1. 最终状态示意

```
app/engine/context/
├── frame.py           # AgentRole Literal 扩展完毕（已包含全 6 角色 — 0 改动）
├── history.py         # 共享 helper — 0 改动
├── builder.py         # +5 个 build_context_frame_for_<role>()
└── renderer.py        # +5 个 frame_to_<role>_messages()

app/engine/agents/
├── generator.py              # 已迁移（Phase 0）            — 0 改动
├── evaluator_agent.py        # 已迁移（Phase 0.5）          — 0 改动
├── verification.py           # +if settings.use_context_builder 双分支
├── guard.py                  # 同上
├── contract.py               # 同上
├── session_summarizer.py     # 同上
└── coach.py                  # 同上

tests/unit/
├── test_generator_equivalence.py     # 已存在 — 0 改动
├── test_evaluator_equivalence.py     # 已存在 — 0 改动
├── test_verifier_equivalence.py      # 新增
├── test_guard_equivalence.py         # 新增
├── test_contract_equivalence.py      # 新增
├── test_summarizer_equivalence.py    # 新增
└── test_coach_equivalence.py         # 新增
```

翻 flag 后（Step 6）：

```
settings.use_context_builder: bool = True   # flip
→ 所有 7 个 agent 走新路径
→ Anthropic ``cache_control=ephemeral`` 在 generator / evaluator 上生效
→ 后续方向 2/3 直接扩 builder payload，不改 agent 代码
```

---

## 2. 模块清单

| 文件 | 动作 | 变更摘要 |
|---|---|---|
| `app/engine/context/builder.py` | 扩展 | +5 个 `build_context_frame_for_<role>` 函数；Generator/Evaluator 两个保持不变 |
| `app/engine/context/renderer.py` | 扩展 | +5 个 `frame_to_<role>_messages` 函数；Generator/Evaluator 两个保持不变 |
| `app/engine/context/__init__.py` | 小改 | 公开新函数 + 更新顶部 docstring（Phase 0 → Phase 1） |
| `app/engine/agents/verification.py` | 小改 | `verify_answer` 改为 `if settings.use_context_builder` 双分支 |
| `app/engine/agents/guard.py` | 小改 | `classify` 改为双分支 |
| `app/engine/agents/contract.py` | 小改 | `negotiate_contract_via_evaluator` 改为双分支 |
| `app/engine/agents/session_summarizer.py` | 小改 | `summarise_session` 改为双分支 |
| `app/engine/agents/coach.py` | 小改 | `build_training_plan` 改为双分支 |
| `app/core/settings.py` | 0 或极小 | Step 6 翻默认值；同时更新 docstring 把 "Phase 0" 改成 "Phase 1" |
| `tests/unit/test_verifier_equivalence.py` | 新增 | 与 `test_generator_equivalence.py` 对等 |
| `tests/unit/test_guard_equivalence.py` | 新增 | 同上 |
| `tests/unit/test_contract_equivalence.py` | 新增 | 同上 |
| `tests/unit/test_summarizer_equivalence.py` | 新增 | 同上 |
| `tests/unit/test_coach_equivalence.py` | 新增 | 同上 |
| `README.md` | 小改 | 在 "Context Engineering" 段把"only Generator" 更新为"all agents";移除 Phase 0 字样 |

---

## 3. 步骤（落地顺序；每步独立 commit，失败可单步回滚）

### Step 1 · Verifier 迁移

**动机**：Verifier 是对抗评审层，下一个方向 2 要给它注入 drift 负例 slot，必须先搬家。

**builder 新函数签名**：
```python
def build_context_frame_for_verifier(
    *,
    dimension: str,
    question: str,
    answer: str,
    contract: dict[str, Any],
    evaluator_report: dict[str, Any],
    turn_idx: int = 0,
) -> ContextFrame:
    ...
```

- `static_system = "You are the Verifier, a strict adversarial reviewer. ..."`（legacy 文本原样搬过来）
- `dynamic_system = ""`（Verifier 不消费 strategy index）
- `payload` 键：`dimension / contract / question / answer / evaluator_report`（匹配 `verifier_task.md` 的 jinja 变量）

**renderer**：
```python
_VERIFIER_PAYLOAD_KEYS = ("dimension", "contract", "question", "answer", "evaluator_report")

def frame_to_verifier_messages(frame: ContextFrame) -> list[ChatMessage]:
    # 与 generator/evaluator 对等：验角色 / 验 payload key / render_prompt("verifier_task.md", ...)
    ...
```

**verification.py 改动**：
```python
if settings.use_context_builder:
    frame = build_context_frame_for_verifier(
        dimension=dimension, question=question, answer=answer,
        contract=contract_payload, evaluator_report=filtered_report,
    )
    messages = frame_to_verifier_messages(frame)
else:
    # legacy branch: 保留原 inline 构造（bit-for-bit 不改）
    messages = [ChatMessage("system", ...), ChatMessage("user", render_prompt(...))]
```

**equivalence test** `tests/unit/test_verifier_equivalence.py`：
- 给 2–3 个典型入参；断言 `frame_to_verifier_messages(frame)` 与 legacy `messages` 的 `(role, content)` 全等
- 断言每个 ChatMessage 的 `cache_control` / `tool_call_id` / `name` 字段与 legacy 一致

**DoD**：`pytest tests/unit/test_verifier_abstain.py tests/unit/test_verifier_evidence.py tests/unit/test_verifier_equivalence.py` 全绿（9 + 5 + N ≈ 17 case），全量 pytest 不退步。

**预估**：0.8h 代码 + 0.5h 测试 = **1.3h**

---

### Step 2 · Guard 迁移

**builder 新函数签名**：
```python
def build_context_frame_for_guard(
    *,
    target_kind: Literal["question", "answer"],
    text: str,
    turn_idx: int = 0,
) -> ContextFrame:
    ...
```

- `static_system = "You are the compliance guard. Respond only with JSON."`
- `dynamic_system = ""`
- `payload`: `target_kind / text`

**renderer**：同上模式，`render_prompt("guard_check.md", ...)`。

**guard.py 改动**：`classify` 函数加双分支。

**equivalence test**：3 个 case（question / answer / empty text）。

**DoD**：`pytest tests/unit/test_guard_pii.py tests/unit/test_injection_patterns.py tests/unit/test_guard_equivalence.py` 全绿。

**预估**：**0.8h**

---

### Step 3 · Contract Negotiator 迁移

**builder**：
```python
def build_context_frame_for_contract_negotiator(
    *,
    dimension: str,
    job_level: str,
    question: str,
    proposed_contract: dict[str, Any],
    contract_hints: dict[str, Any] | None,
    turn_idx: int = 0,
) -> ContextFrame:
    ...
```

- `static_system = "You co-design interview rubrics with another agent. Your role is the strict Evaluator. Respond only with JSON."`
- `payload`: `dimension / job_level / question / proposed_contract / contract_hints`

**contract.py 改动**：`negotiate_contract_via_evaluator` 加双分支。

**equivalence test**：2 个 case（有 hints / 无 hints）。

**DoD**：`pytest tests/unit/test_plan_contract_p0.py tests/unit/test_contract_equivalence.py` 全绿。

**预估**：**0.8h**

---

### Step 4 · Session Summarizer 迁移

**builder**：
```python
def build_context_frame_for_session_summarizer(
    *,
    job_title: str,
    job_level: str,
    new_turns: list[dict[str, Any]],
    existing_summary: str,
    turn_idx: int = 0,
) -> ContextFrame:
    ...
```

- `static_system = "You are a precise interview session summariser. Your output is consumed by another LLM agent as context. Respond with JSON only."`
- `payload`: `job_title / job_level / existing_summary / new_turns`（new_turns 保留 `_sanitise_turn` 输出后的紧凑版）

**session_summarizer.py 改动**：`summarise_session` 加双分支；`_sanitise_turn` 不动。

**equivalence test**：2 个 case（空 existing_summary / 带 existing_summary）。

**DoD**：`pytest tests/unit/test_session_summarizer.py tests/unit/test_summarizer_equivalence.py` 全绿。

**预估**：**0.8h**

---

### Step 5 · Coach 迁移

**builder**：
```python
def build_context_frame_for_coach(
    *,
    job_spec: dict[str, Any],
    candidate: dict[str, Any],
    final_report: dict[str, Any],
    qa_history: list[dict[str, Any]],
    turn_idx: int = 0,
) -> ContextFrame:
    ...
```

- `static_system = "You are the Coach. You produce concrete, actionable growth plans. Respond only with JSON."`
- 内部复用 `_tail_qa_for_coach`（legacy 已有 helper，直接 import）
- `payload`: `job_spec / candidate / final_report / qa_tailored`

**特殊点**：Coach 的 user prompt 是 inline f-string 而非独立的 `.md` 文件。**决策点** A：

- **A.1（推荐）** 把 `_COACH_TASK` 模板拆成 `app/engine/agents/prompts/coach_task.md`（前置 frontmatter / 使用 `render_prompt`），让 Coach 与其他 agent 架构一致。
- **A.2** 保留 inline f-string，renderer 里直接对字符串做 `.format(...)`。

我建议 A.1，同一个 PR 里做；多出的工作量约 +0.2h，换来 "所有 agent 的 user prompt 都在 `prompts/` 里" 的一致性，未来 prompt tuning 可以纯文本 review。

**coach.py 改动**：`build_training_plan` 加双分支；若选 A.1，`_COACH_TASK` 删除，换成 `render_prompt("coach_task.md", ...)`。

**equivalence test**：2 个 case（正常 / 空 qa_history）。

**DoD**：`pytest tests/unit/test_closed_loop_report.py tests/unit/test_coach_equivalence.py` 全绿。

**预估**：**1.0h**（含模板外提）

---

### Step 6 · Flip `use_context_builder=True` 为默认

**改动**：
- `app/core/settings.py`：`use_context_builder: bool = Field(default=True, ...)`；同时把 "Phase 0 feature flag" 注释改成 "Phase 1 complete"。
- `README.md` 的 "Context Engineering" 段说明所有 agent 已走统一 builder。

**不改**：5 个 agent 的双分支暂时保留，提供两个 release 周期的安全网；下个迭代清一次 legacy 分支后彻底移除（见 §9 的"后续钩子 1"）。

**验收**：
- 全量 pytest 通过（`use_context_builder=True` 下跑完所有 equivalence 测试 + 所有 agent 的现有单测）
- 手动 `python -m app.scripts.run_demo` 端到端面试跑完，输出结构与 `run_demo_memory.log` 基线一致（`verdict / overall_score / scores_per_dim / policy_ids` 等 KPI 字段 diff 为 0）

**预估**：**0.3h**

---

## 4. 风险与回滚

| 风险 | 发生步骤 | 缓解 | 回滚 |
|---|---|---|---|
| `frame_to_<role>_messages` 的 cache_control 与 legacy 不一致 | Step 1–5 | equivalence test 断言 `cache_control` 字段；默认 5 个新 role 不加 ephemeral 标记 | 单 PR revert 对应 agent 改动 |
| Coach 模板外提破坏现有 prompt 内容 | Step 5 | `test_coach_equivalence` 断言渲染后字节相等；diff 逐行对齐 | 放弃 A.1，回到 A.2（inline） |
| payload key 命名与 `prompts/*.md` 的 jinja 变量不一致 | Step 1–5 | renderer `_<ROLE>_PAYLOAD_KEYS` 白名单 + `KeyError` 眼前暴露 | 修 key；不影响语义 |
| `use_context_builder=True` 后 LLM 计费上升（cache miss） | Step 6 | 5 个新 role 默认不标 `cache_control`，不改 Anthropic 行为 | 翻回 False |
| 并发：5 个 Step 在同一分支合并时冲突 | 全程 | 每步改动范围严格不重叠（agent 独立 + builder/renderer 追加函数）；按 Step 顺序 rebase | git checkpoint |
| 某个 agent 的 legacy path 其实并非 pure function（有副作用） | Step 1–5 | equivalence test 只比 `messages` 列表；副作用（log / metrics）由独立 integration 测试守 | 单 agent revert |

---

## 5. 测试策略

**新增**（5 个新测试文件，共 10–15 个 case）：

| 测试文件 | 覆盖 |
|---|---|
| `tests/unit/test_verifier_equivalence.py` | 3 个入参 fixture × (legacy messages == frame_to_verifier_messages)；cache_control 字段对等 |
| `tests/unit/test_guard_equivalence.py` | question / answer / empty 3 case |
| `tests/unit/test_contract_equivalence.py` | 有 hints / 无 hints 2 case |
| `tests/unit/test_summarizer_equivalence.py` | 空 summary / 有 summary 2 case |
| `tests/unit/test_coach_equivalence.py` | 正常 / 空 qa 2 case；Step 5 选 A.1 时加 "外提模板不破坏字节" 1 case |

**通用 fixture**（写成 `tests/unit/_equivalence_utils.py`）：
```python
def assert_messages_equal(a: list[ChatMessage], b: list[ChatMessage]) -> None:
    assert len(a) == len(b)
    for x, y in zip(a, b):
        assert x.role == y.role
        assert x.content == y.content
        assert x.cache_control == y.cache_control
        assert x.tool_call_id == y.tool_call_id
        assert x.name == y.name
```

**不新增**（已有覆盖够用）：
- agent 的业务逻辑测试（retry / JSON 解析 / 降级路径）
- integration 级的 end-to-end demo

**CI 基线**：Phase 1 完工后 pytest 目标 `≥ 260 case`（当前 ~235 → +10~15 equivalence case）。

---

## 6. 验收标准（DoD）

- [ ] Step 1–6 全部合入主干
- [ ] 全量 pytest 通过（绿）；equivalence test 全部通过
- [ ] `ReadLints backend/app/engine/context backend/app/engine/agents` 无新增错误
- [ ] 手动：
  - [ ] `use_context_builder=False` 跑 `python -m app.scripts.run_demo` → 输出基线不变
  - [ ] `use_context_builder=True` 跑同一命令 → 输出与 False 基线字节相等（或仅因 LLM 非确定性产生语义等价 diff）
  - [ ] `/admin/bandit/snapshot` 前后数字对比 0 变化（确认没污染 bandit 状态）
- [ ] README "Context Engineering" 段更新完毕；`engine/context/__init__.py` docstring 更新
- [ ] `.agents/skills/agentic-workflow-reference/SKILL.md` **可选** 补回一个最简 SKILL.md（用于方向 3 的铺路），本 Plan 内不强制

---

## 7. 预估工作量

| Step | 代码 | 测试 | 文档 | 合计 |
|---|---|---|---|---|
| 1 Verifier 迁移 | 0.8h | 0.5h | 0 | 1.3h |
| 2 Guard 迁移 | 0.5h | 0.3h | 0 | 0.8h |
| 3 Contract 迁移 | 0.5h | 0.3h | 0 | 0.8h |
| 4 Summarizer 迁移 | 0.5h | 0.3h | 0 | 0.8h |
| 5 Coach 迁移（含模板外提 A.1） | 0.6h | 0.3h | 0.1h | 1.0h |
| 6 Flip flag + 文档 | 0.2h | 0 | 0.3h | 0.5h |

**合计 ≈ 5.2 人时**（不含 review）。单日可落完。

---

## 8. 执行触发

三种方式任选：

- **A（推荐）**：按 Step 1 → 6 逐步出 diff，每步完成后等 review 再继续。
- **B**：一次性实现 Step 1–5，Step 6 单独出 PR。
- **C**：一口气全做，最后汇总改动清单。

默认走 A。如果你希望加速，可以改 B（Step 1–5 合在一次性落完，因为每步都在独立 agent 文件上，没有跨 Step 的合并冲突风险）。

---

## 9. 后续钩子（本 Plan 不做，记录在案）

1. **Phase 2: Legacy path 彻底下线** —— Phase 1 完工 2 个迭代周期之后，5 个 agent 的 `if settings.use_context_builder` 分支的 else 删除，`settings.use_context_builder` 字段本身从 `Settings` 移除。届时 `engine/agents/` 的 code 量进一步缩小，所有 prompt 装配逻辑单一入口。
2. **Slot Registry 规范化** —— 为方向 2（drift 反哺）和方向 3（skills 加载）铺路，在 `engine/context/` 下增加 `slots.py` 集中管理 payload key 命名空间，防止后续新 slot 互相 shadow。
3. **`rubric_negotiator` 下线** —— `generator.negotiate_rubric` 与 `contract.negotiate_contract_via_evaluator` 语义重复；Phase 1 完工后出独立小 PR 下线 `rubric_negotiator`，两个 agent role 合并为 `contract_negotiator`。
4. **Anthropic cache_control 策略统一** —— 目前仅 Generator（并通过 Evaluator 复用的 `system_skeleton.md`）在 static 层打 `ephemeral`。其他 5 个 agent 的 static_system 各自独立短文；下个迭代可以引入一个 shared "role instruction skeleton" 机制，把 Verifier/Guard/Coach 的 system 首段也 cacheable 化，进一步压 Anthropic token 成本。

---

## 10. 一页总结

> **这步做完，`use_context_builder=True` 才是真正的默认值。**
>
> 5 个 agent 从 "inline 拼字符串" 迁到 "ContextFrame + Renderer" 统一装配；prompt cache 命中率从 `2/7 agent` 升到 `7/7 agent`；下一步不论是给 Evaluator 注入 drift 负例（方向 2），还是给 Generator 注入 skill 卡（方向 3），都只要在 builder 里加一个 payload key，不再需要动 agent 代码。
>
> **5.2 人时 / 单日可落 / 每步独立 commit / 零业务 API 变化**。
