# PLAN_SKILL_INJECTION —— 手写业务 skill 并行注入 Generator

> 延续诊断报告"方向 3：Skill 业务化"条目。定位：
> `knowledge/skills/` 是**手写业务 know-how**层，`knowledge/strategy/`
> 是 `strategy_dream` 维护的**reward-driven memory**层；两者并存不
> 合并。Generator prompt 里开辟独立 `INTERVIEW_SKILLS` 槽与原有
> `STRATEGY_MEMORY` 槽并列。

---

## 0. 设计目标

- **手写 vs 自动 分层**：skills 是人写的，strategy 是机器写的；两层
  语义不同、生命周期不同、治理方式不同——**不强制合并**。
- **Zero friction for existing deployments**：默认 `ENABLE_SKILL_INJECTION=false`，
  不存在 skill 文件的部署看不到任何行为变化。
- **Prompt slot 独立**：Generator 的 `generator_task.md` 增加一个 `{skills}`
  变量和 `INTERVIEW_SKILLS = …` 块，与 `STRATEGY_MEMORY` 平行独立。
- **Minimal plan changes**：不加新的 `AskPlanStep`、不改 state schema。
  复用现有 `_step_retrieve_strategy` 的 step，在同一步 opt-in 地拼入
  skills（跟 strategy 一起检索，一起注入）。
- **Frontmatter 对齐**：skill 卡用与 strategy 一致的 `name` /
  `description` / `dimensions` / `job_levels` 字段，降低 cognitive
  switching cost。

**不做**（延后钩子见 §6）：

- **不加 `load_skill` 作为独立 `PlanStepKind`**。现在的最小路径就是在
  `_step_retrieve_strategy` 并联 retrieve；未来如果需要"只加载 skill
  不加载 strategy"的 plan template，再单独升级成独立 step。
- **不做 Tier-1 + Tier-2 分层加载**（Claude Code MEMORY.md 的完整模式）。
  当前 skill 数量少，全量渲染前 3 张卡足够；`build_skills_index` 函数
  已经写好作为未来升级钩子。
- **不把 skill 注入 Evaluator / Coach / Verifier**。当前只注入
  Generator；后续如果发现某些 skill 对评分更有价值，可在
  `build_context_frame_for_evaluator` 里新加 `skills` slot（不破坏
  其他角色）。
- **不把 `strategy_store` 改名为 `skill_store`**。两者的语义差异是
  skill/strategy 这个 plan 存在的理由；改名会丢信息。

---

## 1. 最终状态示意

```
knowledge/
├── skills/                          (hand-authored, curated)
│   ├── SKILL.md                     (Hermes-style index)
│   ├── senior_backend_ownership_probe.md
│   └── system_design_scale_reasoning.md
└── strategy/                        (auto-maintained by strategy_dream)
    ├── MEMORY.md
    └── …

app/memory/
├── skill_store.py                   (NEW)
│   ├── SkillEntry
│   ├── list_skills()
│   ├── retrieve_skills(dim, job_level, limit)
│   ├── build_skills_block(entries)
│   └── build_skills_index()         (Phase 3 hook)
└── strategy_store.py                (unchanged)

ask_question_node
  └─ _step_retrieve_strategy
       ├─ retrieve_strategies + format_strategies_for_prompt   (strategy)
       └─ if settings.enable_skill_injection:
            retrieve_skills + build_skills_block               (skill)

build_context_frame_for_generator
  └─ payload:
       - ...existing keys...
       - "skills": <skill_block>                               (NEW)

generator_task.md
  └─ STRATEGY_MEMORY = {strategy}
     INTERVIEW_SKILLS = {skills}                               (NEW)
```

---

## 2. 模块清单

| 文件 | 动作 | 变更摘要 |
|---|---|---|
| `app/memory/skill_store.py` | 新增 | `SkillEntry` + `list_skills` + `retrieve_skills` + `build_skills_block` + `build_skills_index`（后者目前未消费，作为 Phase 3 hook 保留） |
| `knowledge/skills/SKILL.md` | 新增 | Hermes-style index，列出两张示例卡 |
| `knowledge/skills/senior_backend_ownership_probe.md` | 新增 | 示例 skill：高级后端岗位的 ownership 追问 |
| `knowledge/skills/system_design_scale_reasoning.md` | 新增 | 示例 skill：system_design 维度必须给出失败模式 + 量化缩放论证 |
| `app/core/settings.py` | 扩展 | +2 字段：`enable_skill_injection: bool = False`、`skill_retrieval_limit: int = 3` |
| `app/engine/agents/prompts/generator_task.md` | 小改 | frontmatter 加 `skills` 变量；正文加 `INTERVIEW_SKILLS = {skills}` 块 |
| `app/engine/context/builder.py` | 小改 | `build_context_frame_for_generator` 加 `skill_block: str = "(no relevant interview skills)"` kwarg；payload 加 `skills` key |
| `app/engine/context/renderer.py` | 小改 | `_GENERATOR_PAYLOAD_KEYS` 加 `"skills"` |
| `app/engine/agents/generator.py` | 小改 | `generate_question` 加 `skill_block` kwarg，透传给 builder |
| `app/engine/workflow/nodes/ask_question.py` | 小改 | `_step_retrieve_strategy` 在 strategy retrieval 后按 flag 调 `retrieve_skills` + `build_skills_block`；`_step_draft_question` 透传 `skill_block`；`ctx` 初始化新增占位符 |
| `tests/unit/test_skill_store.py` | 新增 | 11 case：list / retrieve / build / index |
| `tests/unit/test_ask_question_skill_injection.py` | 新增 | 4 case：flag OFF / flag ON 空目录 / flag ON 匹配 skill / flag ON 尊重 limit |
| `tests/unit/test_context_builder.py` | 小改 | 在 payload 断言里加 `skills` 默认占位符 |
| `tests/unit/test_context_renderer.py` | 小改 | `_full_payload` fixture 加 `skills` 键；payload keys 校验列表加 `skills` |
| `tests/unit/test_prompt_loader.py` | 小改 | `test_render_generator_task_end_to_end` 加 `skills` kwarg + `INTERVIEW_SKILLS` 断言 |
| `README.md` | 小改 | "Skill injection (opt-in)" 小节说明 flags + 作者指南 |
| `docs/PLAN_SKILL_INJECTION.md` | 新增 | 本文件 |

---

## 3. 步骤（回顾）

### Step 1 · skill_store 模块

复用 `strategy_store` 的 frontmatter 解析思路，但独立实现以免后续
skill 模型演化时被迫动到 strategy 那边。`SkillEntry` dataclass + 4
个顶层函数（`list_skills` / `retrieve_skills` /
`build_skills_block` / `build_skills_index`）。

**验收**：`test_skill_store.py` 11 case 全绿（包含 tmp_path 沙箱，
零接触真实 knowledge 目录）。

### Step 2 · 三张种子文件

- `SKILL.md`：Hermes 风格入口，列两张卡 + 跟 strategy 层的关系说明。
- `senior_backend_ownership_probe.md`：ownership 深挖 + 量化影响逼问。
- `system_design_scale_reasoning.md`：强制要求失败模式 + 缩放论证。

Frontmatter 字段严格跟 `strategy_store` 对齐。

### Step 3 · Settings + prompt + builder

- `ENABLE_SKILL_INJECTION=false` / `SKILL_RETRIEVAL_LIMIT=3` 入 Settings。
- `generator_task.md` frontmatter 和正文加 `skills` 变量 + 块。
- `build_context_frame_for_generator` 加 `skill_block` kwarg，payload
  新增 `skills` key。
- `_GENERATOR_PAYLOAD_KEYS` 跟上。
- `generate_question` 加 `skill_block` kwarg，透传到 builder。

### Step 4 · ask_question 节点接入

在 `_step_retrieve_strategy` 里 strategy retrieval 之后 opt-in 做
skill retrieval。用 `getattr(settings, "enable_skill_injection", False)`
读 flag 保持对 stub settings 的容忍（与 evidence-span / drift-feedback
同款）。`_step_draft_question` 接上 `skill_block`；`ctx` 初始化时
seed 占位符 `"(no relevant interview skills)"`。

### Step 5 · 测试 + 文档

- 15 个新 test case（11 store + 4 injection）。
- 3 个现有 test 小幅更新（builder / renderer / prompt_loader）以反映新 payload key。
- README 加 "Skill injection (opt-in)" 小节。
- PLAN 文件（本文件）。

---

## 4. 风险与回滚

| 风险 | 位置 | 缓解 | 回滚 |
|---|---|---|---|
| 现有部署 prompt 结构悄然变长 | generator_task.md | flag OFF 时 `{skills}` 被占位符字符串替换，长度固定；token 增量 < 80 chars | 关 flag |
| skill retrieval 读盘失败打断图 | ask_question node | `retrieve_skills` 在 store 层对 OSError 做 skip；`build_skills_block` 对空输入返回占位符 | 无需回滚；flag 关掉即可 |
| 与 strategy 混淆造成 Generator 误用 | generator_task | prompt 两个块分别命名 `STRATEGY_MEMORY` / `INTERVIEW_SKILLS`，语义由名称区分 | 人工审 prompt |
| 将来 `strategy_store` 接入新的 frontmatter 字段，两边 schema drift | both | 两个 store 模块各自独立解析，drift 是局部的；新字段只需要在相关模块加解析 | 同步升级两边 |
| skill cards 数目超过 `skill_retrieval_limit` 时遗漏重要 skill | retrieve_skills | `limit=3` 默认够 MVP；后续有 tier-1 index 作为补救 | 调大 limit |

---

## 5. 验收标准（DoD）

- [x] 代码合入（skill_store / settings / prompt / builder / renderer / generator / ask_question）
- [x] 种子文件（SKILL.md + 2 张卡）到位
- [x] 新测试 15 case 全绿（`pytest tests/unit/test_skill_store.py tests/unit/test_ask_question_skill_injection.py`）
- [x] 全量 pytest 通过（410 passed）
- [x] `ReadLints` 无新增错误
- [x] 手动：`ENABLE_SKILL_INJECTION=true` + `python -m app.scripts.run_demo` 端到端跑通，KPI 与 Phase 2 基线一致
- [x] README 补 "Skill injection" 小节
- [x] 本 plan 文件

---

## 6. 后续钩子（本 plan 不做）

1. **`load_skill` 独立 PlanStep**：当不同 plan template 想各自决定
   是否加载 skills（例如 `simple` 跳过 / `deep_probe` 强制加载）时，
   把 retrieval 逻辑从 `_step_retrieve_strategy` 拆到新的
   `_step_retrieve_skills` + 新 `PlanStepKind="retrieve_skills"`。
2. **Tier-1 index 进 dynamic_system**：`build_skills_index` 已经写
   好；当 skill 数量 > 10 张时，把 index（只有 name+description）常
   驻 `dynamic_system`，full body 只在 top-N 命中时进 `skills` 槽。
3. **Evaluator / Coach 也消费 skills**：`build_context_frame_for_evaluator`
   / `build_context_frame_for_coach` 加 `skill_block` slot；需要先把
   `skill_store.retrieve_skills` 扩一个 `scope` frontmatter 字段来
   过滤"哪些 skill 只给 evaluator"。
4. **Skill edit CLI / admin UI**：`strategy_dream` 已经有 forked-agent
   级别的写回能力；人写的 skill 目前只靠 git 手工编辑。如果团队规
   模大，可考虑一个 `admin/skills/*` API。
5. **Versioning + rollback**：skills 目前是 plain files，没有变更
   审计。长期可加 frontmatter 里 `version` / `author` / `reviewed_at`
   字段和独立 `ChangeLog.md`。

---

## 7. 预估工作量

| Step | 代码 | 测试 | 文档 | 合计 |
|---|---|---|---|---|
| 1 skill_store 模块 | 1.0h | 0.8h | 0 | 1.8h |
| 2 种子文件 | 0.3h | 0 | 0.1h | 0.4h |
| 3 settings + prompt + builder | 0.5h | 0.3h | 0 | 0.8h |
| 4 ask_question 节点接入 | 0.4h | 0.6h | 0 | 1.0h |
| 5 文档收尾 | 0 | 0 | 0.5h | 0.5h |

**合计 ≈ 4.5 人时**。单日可落完。

---

## 8. 一页总结

> **把 Generator 的 prompt 从"RAG + Strategy"两层升级成"RAG +
> Strategy + Skill"三层，skill 层可由人直接 git-commit 维护。**
>
> 4.5 人时 / 单日落地 / feature flag 默认 OFF / 15 个新 test。做完
> 之后：
> - Claude Code / Hermes 的 `MEMORY.md + topic files + relevant recall`
>   模式在 `knowledge/skills/` 完整复刻；
> - 与 strategy 层的"自动 dream 记忆"并行，构成 Harness 的
>   "手写 + 自动"双路径 memory；
> - 后续 Evaluator / Coach 扩展只是 builder 加一个 slot 的工作量，
>   不用再动 agent runtime。
