# LLM Memory Selector —— Claude Code `findRelevantMemories.sideQuery` 同款

> 延续 `PLAN_CONTEXT_BUILDER_PHASE1.md §9 钩子 2` "Slot Registry 规范化" 和
> `README.md §10.5` 对 Claude Code 对齐度差距的识别：目前
> `skill_store.retrieve_skills` 和 `strategy_store.retrieve_strategies` 都是
> **keyword 硬匹配 + 静态 +2/+1 评分**，在 card 数量突破 10+ 后会漏召回
> 真正语义相关的。
>
> 本 plan 抄 Claude Code `src/memdir/findRelevantMemories.ts` 的做法：
> **先 keyword-filter 出候选集，再用一次轻量 sideQuery LLM 调用做语义选择**。
> 与 Claude Code 严格对齐：
>
> - 输入不是 full body，而是 manifest（name + description + tags）
> - 输出是 JSON schema，最多 N 个 filename
> - 失败退回 keyword 结果，永不 block
> - 两种 memory layer（skills + strategy）复用同一个 selector 基础设施

---

## 0. 设计目标

1. **能力升级**：keyword 匹配 → LLM 语义选择，但 **保持兼容**：flag OFF 时
   行为 byte-identical（skill_store / strategy_store API 不变）。
2. **两 layer 共用**：`select_memories_with_llm` 是一个通用 selector，
   接受 `MemoryCandidate[]` + `SelectorContext`，返回选中 filename 列表。
   skill / strategy 两个 store 都挂这个 selector，零代码重复。
3. **Cost 可控**：
   - `max_tokens=256`
   - `temperature=0.3`
   - 不传 tool（不让 selector 再发 function call）
   - `json_mode=True` 强制结构化输出
4. **Fail-safe**：任何 LLM / parsing 异常 → `None` → caller 回退 keyword 结果。
5. **Opt-in**：默认 `enable_llm_memory_selector=False`；要在 flag ON 时
   才真正发 sideQuery。现有 test / demo 不受影响。

**不做**（延后钩子见 §7）：

- **不用 `sideQuery(...)` 专门的模型路由**：Claude Code 有 `default: Sonnet`
  的轻量路由；项目的 `call_chat(agent_role="memory_selector")` 配合
  `llm_model_per_agent` 能达到同等效果，不需要额外基础设施。
- **不做 cache key 规范化**：本版只做单次 select；后续如果调用频繁，
  加 in-memory LRU（`functools.lru_cache`）即可。
- **不做 cross-layer fan-in**（skill + strategy 混合 selector）：两个
  layer 的语义不同，独立 selector 更清晰；未来真有需求再做合并。

---

## 1. 最终状态示意

```
retrieve_skills / retrieve_strategies (keyword + static score)
  │
  │  返回 top-N 候选（keyword 硬过滤后的结果）
  │
  ▼
[opt-in] select_memories_with_llm(candidates, context)
  │
  │  manifest 化 → sideQuery → JSON schema → 选中 filename
  │
  ├─→ 成功：按 filename 过滤 candidates，返回 LLM 选定的子集
  └─→ 失败：None → caller 退回原 keyword top-N（当前行为）

build_skills_block / format_strategies_for_prompt
  (unchanged — 只负责渲染，不管用哪种 selector)
```

**一句话**：现有 retrieve 函数保持不变（它们已经做了 keyword 过滤）；
在其输出后 **opt-in 再过一层 LLM selector** 做语义收敛。等价于
Claude Code 的 `scanMemoryFiles → formatMemoryManifest → sideQuery → selected_memories`
四步链。

---

## 2. 模块清单

| 文件 | 动作 | 变更摘要 |
|---|---|---|
| `app/memory/llm_selector.py` | 新增 | `MemoryCandidate` / `SelectorContext` dataclass + `select_memories_with_llm(...)` + `_build_manifest(...)` + `_parse_selection(...)` |
| `app/engine/agents/prompts/memory_selector.md` | 新增 | Frontmatter + jinja 模板，输入 `candidates_manifest` / `dimension` / `job_level` / `recent_qa_summary` / `top_n`，约束输出 `{"selected": ["filename.md", ...]}` |
| `app/core/settings.py` | 扩展 | +2 字段：`enable_llm_memory_selector: bool = False`、`llm_memory_selector_top_n: int = 5` |
| `app/engine/agents/llm_client.py` | 小改 | `AgentCallRole` Literal 加 `"memory_selector"`（已支持 `llm_model_per_agent` 路由） |
| `app/memory/skill_store.py` | 小改 | `retrieve_skills` 加 `use_llm_selector: bool = False` kwarg；若 True 且 candidates 非空 → 调 `select_memories_with_llm`；LLM 失败则 fallback 原 top-N |
| `app/memory/strategy_store.py` | 小改 | 同 `skill_store`，`retrieve_strategies` 加同款 kwarg |
| `app/engine/workflow/nodes/ask_question.py` | 小改 | `_step_retrieve_strategy` 与 `_step_retrieve_skills` 分别按 `settings.enable_llm_memory_selector` 决定是否开 LLM selector |
| `tests/unit/test_llm_memory_selector.py` | 新增 | 6-8 case：manifest 构造 / JSON parsing / fallback / top_n 截断 / LLM stub 模式 |
| `tests/unit/test_skill_store.py` | 小改 | 加 1 case 测试 `use_llm_selector=True` 路径（stub LLM） |
| `tests/unit/test_strategy_store.py` | 视情况加 | 如果已有，加 1 case；否则本 plan 不新增 |
| `README.md` | 小改 | feature flags 总览表加 `ENABLE_LLM_MEMORY_SELECTOR` + `LLM_MEMORY_SELECTOR_TOP_N` 两行；Harness 演进史提一句 "V6 钩子已落" |

---

## 3. 步骤

### Step 1 · `llm_selector.py` 模块 + prompt

新模块提供两个 dataclass + 一个 pure function：

```python
@dataclass
class MemoryCandidate:
    filename: str
    name: str
    description: str
    dimensions: list[str]
    job_levels: list[str]

@dataclass
class SelectorContext:
    dimension: str
    job_level: str
    recent_qa_summary: str = ""   # 可选：把最近几轮 QA 主题喂给 selector
    purpose: str = "generator"    # "generator" | "evaluator" | "coach" 区分调用方

def select_memories_with_llm(
    candidates: list[MemoryCandidate],
    context: SelectorContext,
    *,
    top_n: int = 5,
) -> list[str] | None:
    """Return the LLM-selected filenames, or ``None`` on failure.
    Caller should fallback to its keyword-filtered top-N list."""
```

关键实现要点：
- 空 candidates → 直接 return []（不调 LLM）
- 构造 manifest（跟 Claude Code `formatMemoryManifest` 同款）：
  ```
  - [skill] senior_backend_ownership_probe.md (dims=leadership, system_design | levels=senior, staff): Probe ownership ...
  - [strategy] deep_probe_senior.md (dims=system_design | levels=senior): Always require one concrete ...
  ```
- `call_chat([System, User(render_prompt("memory_selector.md", ...))], json_mode=True, agent_role="memory_selector")`
- Parse `{"selected": ["filename.md", ...]}`，校验每个 filename 必须在 candidates 里
- Top_n 硬截断
- 任何 exception / parse 失败 → log.debug + return None

**prompt 对标 Claude Code `SELECT_MEMORIES_SYSTEM_PROMPT`**：

```
You are the memory selector for an interview agent. Given the
agent's current ``(dimension, job_level)`` and optionally a
summary of the recent interview, pick at most TOP_N filenames
from the MEMORY_MANIFEST that are MOST relevant to the current
turn.

Rules:
- Only return filenames that appear in MEMORY_MANIFEST.
- Do NOT invent filenames.
- Prefer memories that directly match the dimension; memories
  tagged ``all`` are acceptable but lower priority.
- Respond with a single JSON object: {"selected": ["<filename.md>", ...]}

DIMENSION = {dimension}
JOB_LEVEL = {job_level}
PURPOSE = {purpose}
RECENT_QA_SUMMARY = {recent_qa_summary}
MEMORY_MANIFEST =
{candidates_manifest}
```

### Step 2 · skill_store / strategy_store 接入

`skill_store.retrieve_skills` 增强：

```python
def retrieve_skills(
    *,
    dimension: str,
    job_level: str = "mid",
    limit: int = 3,
    use_llm_selector: bool = False,
    recent_qa_summary: str = "",
) -> list[SkillEntry]:
    # 原 keyword + 静态评分逻辑不变
    keyword_filtered = ... # 现有实现
    if not use_llm_selector or not keyword_filtered:
        return keyword_filtered[:limit]
    
    # LLM selector pass
    from app.memory.llm_selector import (
        MemoryCandidate, SelectorContext, select_memories_with_llm,
    )
    candidates = [
        MemoryCandidate(filename=e.path.name, name=e.name, ...)
        for e in keyword_filtered
    ]
    context = SelectorContext(
        dimension=dimension, job_level=job_level,
        recent_qa_summary=recent_qa_summary, purpose="generator",
    )
    selected = select_memories_with_llm(candidates, context, top_n=limit)
    if selected is None:
        # LLM failed → fallback to keyword top-N
        return keyword_filtered[:limit]
    
    # 按 selected 顺序过滤
    by_name = {e.path.name: e for e in keyword_filtered}
    return [by_name[f] for f in selected if f in by_name]
```

`strategy_store.retrieve_strategies` 同样接入；共用同一 selector。

### Step 3 · Settings + ask_question 节点

Settings 加 2 字段：

```python
enable_llm_memory_selector: bool = False
llm_memory_selector_top_n: int = 5
```

`ask_question_node._step_retrieve_strategy` 与独立的
`_step_retrieve_skills` 分别按 flag 调用：

```python
settings = get_settings()
use_llm = bool(getattr(settings, "enable_llm_memory_selector", False))

strategies = retrieve_strategies(
    dimension=ctx["dimension"],
    job_level=job_level,
    use_llm_selector=use_llm,
    recent_qa_summary="",  # 后续可从 state.qa_summary 提
)

skills = retrieve_skills(
    dimension=ctx["dimension"],
    job_level=job_level,
    use_llm_selector=use_llm,
    recent_qa_summary="",
)

```

### Step 4 · Tests

**新 `test_llm_memory_selector.py`**（6-8 case）：

| 用例 | 断言 |
|---|---|
| `test_empty_candidates_returns_empty_list_no_llm_call` | 空输入直接 `[]`，不调 call_chat |
| `test_manifest_format_matches_claude_code_shape` | `_build_manifest` 输出含 `[skill]` 前缀、dim/level 标签、description |
| `test_select_parses_valid_json_schema` | LLM 返回 `{"selected":[...]}` → 正确 filename list |
| `test_select_rejects_filenames_not_in_candidates` | LLM 幻觉 filename → 过滤掉 |
| `test_select_respects_top_n_cap` | LLM 返回过多项 → 硬截断 |
| `test_select_fallback_on_invalid_json` | LLM 返回乱文本 → return None |
| `test_select_fallback_on_llm_exception` | `call_chat` 抛异常 → return None |

**`test_skill_store.py` 加 1 case**：

```python
def test_retrieve_skills_with_llm_selector_filters_keyword_set(
    skills_root, monkeypatch
):
    """LLM selector 应该基于 manifest 裁剪，不是重新扫 disk."""
    # seed 3 skill cards 都匹配 dimension
    # monkeypatch select_memories_with_llm 返回 subset
    # assert 最终返回的是 LLM 选中的那几个
```

### Step 5 · 文档 + README + Demo

- `README.md §12.5` feature flags 表加 2 行（`ENABLE_LLM_MEMORY_SELECTOR` + `LLM_MEMORY_SELECTOR_TOP_N`）
- `README.md §10.5` Harness 演进史追加一句："V6 钩子 #1 LLM selector 已落"
- 手动 demo：`ENABLE_LLM_MEMORY_SELECTOR=true` + `ENABLE_SKILL_INJECTION=true` 跑 `run_demo`，在 LLM log 里能看到一次 `agent_role=memory_selector` 的调用

---

## 4. 风险与回滚

| 风险 | 位置 | 缓解 | 回滚 |
|---|---|---|---|
| LLM selector 延迟高，拖慢 `ask_question_node` | Step 2 | max_tokens=256 + 仅 1 轮对话，延迟 < 500ms；大多数 LLM 快于 retrieval I/O | 关 flag |
| LLM 幻觉 filename，返回不存在的卡 | Step 1 | Parser 严格过滤 `filename in {c.filename for c in candidates}` | 已在实现里 |
| JSON parsing 失败 → 整个 retrieve 炸 | Step 1 | try/except 全包 + `return None` → caller fallback | 回滚到 keyword |
| 多个 agent_role 共用一个 selector 模型导致 `llm_model_per_agent` 配置冲突 | Step 1 | 专门加 `memory_selector` role，让操作员按需配置 | 不配 map 时走全局 `LLM_MODEL` |
| Stub LLM 模式下 selector 返回 fixture → 测试意外通过 | Step 4 | 新 test 专门 patch `call_chat` 验证真实路径 | 测试层覆盖 |

---

## 5. 验收标准（DoD）

- [ ] Step 1-5 全部合入
- [ ] 新 6-8 case `test_llm_memory_selector.py` 全绿
- [ ] `test_skill_store.py` / `test_strategy_store.py` 新增 1-2 case 全绿
- [ ] 全量 pytest 通过（429 → ≥ 435）
- [ ] `ReadLints` 无新增错误
- [ ] 手动：`ENABLE_LLM_MEMORY_SELECTOR=true` + `ENABLE_SKILL_INJECTION=true` 跑 `run_demo`（stub 模式即可），skill 召回路径跑通
- [ ] README 更新完

---

## 6. 预估工作量

| Step | 代码 | 测试 | 文档 | 合计 |
|---|---|---|---|---|
| 1 llm_selector + prompt | 1.0h | 0.8h | 0 | 1.8h |
| 2 skill/strategy store 接入 | 0.6h | 0.5h | 0 | 1.1h |
| 3 settings + ask_question node | 0.3h | 0.3h | 0 | 0.6h |
| 4 测试 | 0 | 0.6h | 0 | 0.6h |
| 5 文档 + demo | 0 | 0 | 0.4h | 0.4h |

**合计 ≈ 4.5 人时**。单日可落完。

---

## 7. 后续钩子（本 plan 不做）

1. **Manifest caching + recent_qa_summary 真正喂进去**：当前 caller 都传
   `recent_qa_summary=""`，未来可从 `state.qa_summary`（方向 2 的 compression）接过来，selector 能看到"候选人这轮偏弱的方向"。
2. **Cross-layer selector**：skill 和 strategy 合并做一次 selector，让
   LLM 在混合集里选 top-N。当前两路独立，future 如需优化成本可合并。
3. **Selector 本身的 A/B 度量**：用 bandit 跟踪"哪些 selector 模型 +
   top_n 配置下，后续 Evaluator 打分更高"，把 selector 本身纳入 RL 闭环。
4. **Hybrid RAG（Chroma）升级**：当 skill / strategy 卡超过 50 张，用
   embedding 先做向量 retrieve（候选池变大），再丢给 LLM selector 精选。

---

## 8. 一页总结

> **Claude Code `findRelevantMemories.sideQuery` 的等价实现——skill 和
> strategy 两个 memory layer 共用一个 LLM selector 模块，keyword 硬匹配
> 作为前滤，LLM sideQuery 作为精选**。
>
> 4.5 人时 / 默认 OFF / 失败 fallback 回 keyword / 共用基础设施不冗余。
> 做完之后 Harness 对齐度从 85% → 90%，V6 钩子 #1 落地完成。
