# L2：Evidence span alignment —— 让 evidence 引用带上原文 offset

> 本 plan 延续 `PLAN_EVIDENCE_SPANS.md` 的 §8 钩子「L2 Evidence span alignment」。
> 目标：**在不打破现有 `evidence: list[str]` 契约**的前提下，为每条 evidence 补一份 `{"text", "start", "end"}` 结构化对象，供 UI 高亮 / RAG 反哺 / drift 信号使用。
>
> 并行的 L1 Verifier drift signal 单独走 `PLAN_VERIFIER_DRIFT.md`（本仓库的下一份 plan）。

---

## 0. 设计目标

Evaluator 产出的 `acceptance_check_results[<check>]` 从：

```json
{
  "verdict": "yes",
  "evidence": ["we prefer AP for availability"]
}
```

升级为 **additive** 版本：

```json
{
  "verdict": "yes",
  "evidence": ["we prefer AP for availability"],
  "evidence_spans": [
    {
      "text": "we prefer AP for availability",
      "start": 0,
      "end": 29,
      "match": "exact"
    }
  ]
}
```

**关键约束**：
- `evidence` 字段**不变**（所有现有测试 / 下游消费者继续工作）
- `evidence_spans` 是**新增只增字段**（additive），默认关闭（`evidence_span_alignment=False`）
- 开启时 `evidence_spans.length == evidence.length`（一一对应）
- 找不到 offset 时写 `{"text": quote, "start": -1, "end": -1, "match": "none"}`，不报错
- **不新增 LLM 调用**（post-hoc 字符串对齐，stdlib `difflib`）
- **不加外部依赖**（`rapidfuzz` / `spaCy` 全部不引入）

---

## 1. 最终状态示意

```
evaluator_agent.evaluate_answer(..., answer)
   │
   │  LLM 返回 {"verdict": ..., "evidence": ["quote A", "quote B"]}
   ▼
_normalize_check_result(raw, *, answer, enable_spans)
   │  ├─ 规范化 verdict + evidence 字符串列表（不变）
   │  └─ enable_spans=True 时，为每条 quote 调 _align_one_span(quote, answer)
   ▼
 {
   "verdict": "yes",
   "evidence": ["quote A", "quote B"],
   "evidence_spans": [
     {"text": "quote A", "start": 12, "end": 19, "match": "exact"},
     {"text": "quote B", "start": -1, "end": -1, "match": "none"}
   ]
 }
   │
   ▼
verification.verify_answer(evaluator_report=...)
   │   verifier prompt 原封不动 JSON 序列化 —— 自动把 evidence_spans 带进去
   │   (L3 Verifier drift 里会用 evidence_spans.match=="none" 作为 drift 信号)
   │
   ▼
final_report_node._turn_evidence(qa)
   │   acceptance_check_results 整体透传，UI 直接消费 evidence_spans
   │
   ▼
trainset_builder.export_jsonl
       JSON 序列化自动跟进；L3 RAG 反哺可直接读 start/end 切片答案原文
```

**不改 checkpoint schema / 不改 API 契约**（新字段走 JSON 扩展位）。

---

## 2. 模块清单

| 文件 | 动作 | 变更摘要 |
|---|---|---|
| `app/core/settings.py` | 扩展 | +2 字段：`evidence_span_alignment: bool = False` / `evidence_span_fuzzy_threshold: float = 0.6` |
| `app/engine/agents/evaluator_agent.py` | 扩展 | +`_align_one_span(quote, answer, threshold)`；`_normalize_check_result` 增 optional `answer` 参数；`evaluate_answer` 在 settings 开启时把 answer 传进去 |
| `app/engine/agents/verification.py` | 无 | `verify_answer` 已 JSON 透传 `acceptance_check_results`，自动带上 `evidence_spans` |
| `app/engine/workflow/nodes/final_report.py` | 无 | `_turn_evidence` 已整体透传，`_acceptance_counts` 只读 verdict 不碰 evidence |
| `app/engine/workflow/nodes/experience_extractor.py` | 无 | 不依赖 evidence shape |
| `app/data/trainset_builder.py` | 无 | JSON 序列化自动跟进 |
| `tests/unit/test_evaluator_span_alignment.py` | 新增 | 6–8 个 case：exact / fuzzy / 找不到 / 中英混合 / 多 quote / settings off 零 diff |
| `.env.example` | 小改 | 追加 `EVIDENCE_SPAN_ALIGNMENT=false` + 一行注释 |
| `README.md` | 小改 | 在 "RL / Data tuning knobs" 段后加 "Evidence spans"  段 |

---

## 3. 数据结构

### 3.1 单条 span

```python
class EvidenceSpan(TypedDict):
    text: str      # LLM 返回的 quote 原样，始终存在
    start: int     # 在 answer 中的 0-indexed 起点；找不到时为 -1
    end: int       # exclusive；找不到时为 -1
    match: Literal["exact", "fuzzy", "none"]
```

不用 `dataclass` / `pydantic` ：保持 dict 形态，与现有 `acceptance_check_results` 一致，JSON 序列化零摩擦。

### 3.2 新约定

`evidence_spans` 长度必须等于 `evidence`；顺序与 `evidence` 一一对应。缺位用 `{"text": "", "start": -1, "end": -1, "match": "none"}` 兜底（理论上不会出现）。

---

## 4. `_align_one_span` 算法（post-hoc fuzzy match）

```python
import difflib


def _align_one_span(
    quote: str,
    answer: str,
    *,
    fuzzy_threshold: float = 0.6,
) -> dict[str, Any]:
    """Locate ``quote`` inside ``answer`` and return an offset span.

    Strategy, in order:

    1. **Exact**: ``answer.find(quote)`` — cheap, succeeds when the
       evaluator actually obeyed the "verbatim" prompt instruction.
    2. **Fuzzy**: ``difflib.SequenceMatcher`` on the best matching
       block. Accepts if
       ``overlap_len / max(len(quote), 1) >= fuzzy_threshold``.
    3. **None**: give up, return ``{"text": quote, "start": -1,
       "end": -1, "match": "none"}``.

    Never raises. Returns immediately on empty inputs.
    """
    if not quote or not answer:
        return {"text": quote, "start": -1, "end": -1, "match": "none"}

    exact = answer.find(quote)
    if exact >= 0:
        return {
            "text": quote,
            "start": exact,
            "end": exact + len(quote),
            "match": "exact",
        }

    # difflib 在短引述上足够快（O(m*n) 但 m,n 都是几十到几百量级）。
    matcher = difflib.SequenceMatcher(a=answer, b=quote, autojunk=False)
    block = matcher.find_longest_match(0, len(answer), 0, len(quote))
    overlap_ratio = block.size / max(len(quote), 1)
    if overlap_ratio >= fuzzy_threshold:
        return {
            "text": quote,
            "start": block.a,
            "end": block.a + block.size,
            "match": "fuzzy",
        }

    return {"text": quote, "start": -1, "end": -1, "match": "none"}
```

**复杂度**：`SequenceMatcher.find_longest_match` 是 O(m*n)，在 answer 数千字符 × quote 几十字符的量级下单次 <1ms。每个 acceptance check 最多 3 条 evidence × 若干 check，整体一次 evaluation 对齐在个位数 ms 量级，可以忽略。

**`autojunk=False`**：关掉 difflib 对"高频字符"的自动裁剪。中文文本里标点 / 常见字都会被误判为 junk，导致匹配率虚高。

---

## 5. `_normalize_check_result` 扩展

**当前签名**：

```python
def _normalize_check_result(raw: Any) -> dict[str, Any]: ...
```

**扩展签名**（默认参数全部保留当前行为）：

```python
def _normalize_check_result(
    raw: Any,
    *,
    answer: str | None = None,
    enable_spans: bool = False,
    fuzzy_threshold: float = 0.6,
) -> dict[str, Any]:
    """..."""
    # ...现有 verdict + evidence 规范化逻辑保持不动...
    result = {"verdict": verdict, "evidence": evidence}
    if enable_spans and answer is not None:
        result["evidence_spans"] = [
            _align_one_span(q, answer, fuzzy_threshold=fuzzy_threshold)
            for q in evidence
        ]
    return result
```

**关键兼容点**：
1. 现有所有对 `_normalize_check_result(raw)` 的调用（不传 `answer`）继续返回 `{"verdict", "evidence"}`，零 diff。
2. `evaluate_answer` 从 `get_settings().evidence_span_alignment` 决定是否传 `enable_spans=True`。
3. 调用点只有两处（`evaluate_answer` 主循环 + fallback synthesise）——fallback 路径 `evidence=[]` 时 `evidence_spans` 也是 `[]`，长度依然对齐。

---

## 6. 步骤（落地顺序；每步独立 commit）

### Step A · settings + helper（零功能变化）

- [ ] `settings.py` 加 2 字段
- [ ] `evaluator_agent.py` 加 `_align_one_span`（独立函数，暂不被调用）
- [ ] `tests/unit/test_evaluator_span_alignment.py` 新增，只覆盖 `_align_one_span`（exact / fuzzy / none / 空输入 / 中英混合）

**验收**：新测试全绿 + 现有 205 个测试不退步。

---

### Step B · 通路接入

- [ ] `_normalize_check_result` 加 `answer / enable_spans / fuzzy_threshold` 参数
- [ ] `evaluate_answer` 主循环 + synthesise fallback 分支，根据 settings 传参
- [ ] `tests/unit/test_evaluator_span_alignment.py` 补端到端 case：stub LLM 返回 canonical shape + `evidence_span_alignment=True`，断言 `evidence_spans` 存在且 offset 正确

**验收**：
- 新 case 全绿
- `test_evaluator_evidence.py` 里所有断言 `evidence == [...]` 继续通过（默认 settings 关闭时 `evidence_spans` 字段不存在）
- 手动测试：`evidence_span_alignment=True` 时 evaluator 输出 JSON 可见 `evidence_spans` 字段

---

### Step C · 下游防御性扫描

- [ ] `rg "acceptance_check_results" backend/app backend/tests` 扫一遍，确认没有地方在做 `for v in checks.values(): assert isinstance(v["evidence"], list[str])` 这种严格类型检查
- [ ] `final_report._turn_evidence` 透传——不改
- [ ] `trainset_builder` JSON 序列化——不改

**验收**：
- 全量 pytest 通过
- 手工 `python -m app.scripts.run_demo` 看日志里 `evidence_spans` 结构正确

---

### Step D · 文档

- [ ] `.env.example` 追加注释段
- [ ] `README.md` 在 "RL / Data tuning knobs" 表末加一小节 "Evidence span alignment" 说明 knob 作用 + 前端消费建议

**验收**：文档 lint 不坏。

---

## 7. 测试策略

**新增单测** `tests/unit/test_evaluator_span_alignment.py`（8 个 case）：

| 用例 | 断言 |
|---|---|
| `test_align_exact_match` | `answer.find(quote)` 命中，`match == "exact"` |
| `test_align_fuzzy_match_above_threshold` | 一两个字符差异（whitespace / 标点变体），`match == "fuzzy"`，overlap ≥ 0.6 |
| `test_align_no_match_below_threshold` | 完全无关 quote，`start/end == -1, match == "none"` |
| `test_align_empty_inputs` | `quote=""` 或 `answer=""` 时返回 none-span |
| `test_align_chinese_mixed` | 中英混合 answer + 中文 quote，autojunk=False 下能命中 |
| `test_normalize_no_answer_no_spans` | 不传 answer，返回 `{"verdict","evidence"}`（无 spans 字段） |
| `test_evaluate_answer_emits_spans_when_enabled` | settings 开启 + stub LLM 返回 canonical，端到端断言 `evidence_spans` 存在且长度匹配 |
| `test_evaluate_answer_silent_when_disabled` | settings 关闭时，输出与当前行为 byte-identical（无 `evidence_spans`） |

**不新增**：
- Verifier prompt 能否看到 spans 的 case（`evidence_spans` 走 JSON 透传；走 L3 drift plan 时专门测）
- final_report 透传 spans 的 case（`_turn_evidence` 已有 "preserve verbatim" 测试，零改动天然覆盖）

**现有测试零改动**：
- `test_evaluator_evidence.py` 全部用默认 settings（`evidence_span_alignment=False`），输出无 `evidence_spans` 字段，继续通过
- `test_verifier_evidence.py` / `test_final_report_evidence.py` 同理

**测试基础设施**：
- `get_settings` 用了 `@lru_cache`，新测试需要 `get_settings.cache_clear() + monkeypatch.setenv`
- 或直接 `monkeypatch.setattr(settings_module, "_settings", None)` 强制重取

---

## 8. 风险与回滚

| 风险 | 发生步骤 | 缓解 | 回滚 |
|---|---|---|---|
| difflib 对中文 autojunk 误裁导致 fuzzy 匹配率虚高/虚低 | Step A | `autojunk=False` + 单测专覆盖中英混合场景 | 调高 `evidence_span_fuzzy_threshold`（默认 0.6 → 0.75） |
| 大 answer（>5KB）多 quote 拖慢 evaluator | Step B | quote 短（几十字符）+ check 数量有限（≤10），实测 <10ms；且路径 opt-in | 关 knob 即可 |
| 现有测试因 settings cache 污染跨用例 | Step B | 测试里用 `monkeypatch` + 显式 cache_clear | revert 该 PR |
| 前端拿到 `evidence_spans=[]` 时渲染异常 | Step C 文档 | README 明确写 "start=-1 表示未定位到 offset，按纯文本渲染" | 前端单独处理 |
| `evaluate_answer` synthesise 分支缺 `evidence_spans` 键 | Step B | synthesise 分支 evidence=[]，对齐后 evidence_spans 也=[]，长度依然对齐 | 补默认空列表 |

每步独立 commit，revert 成本为单文件级。

---

## 9. 验收标准（DoD）

- [ ] Step A / B / C / D 全部合入主干
- [ ] 全量 pytest 通过（基线 205 → ≥ 213 with 新测试，无红）
- [ ] `ReadLints` 无新增错误
- [ ] 手动：
  - `EVIDENCE_SPAN_ALIGNMENT=true python -m app.scripts.run_demo` 日志里能看到 `evidence_spans` 字段，start/end 落在 candidate answer 合法范围
  - `EVIDENCE_SPAN_ALIGNMENT=false`（默认）时日志里无 `evidence_spans` 字段
- [ ] README 新段落解释 knob + 前端消费示例

---

## 10. 预估工作量

| Step | 代码 | 测试 | 文档 | 合计 |
|---|---|---|---|---|
| A settings + helper | 0.4h | 0.5h | 0 | 0.9h |
| B 通路接入 | 0.5h | 0.7h | 0 | 1.2h |
| C 下游扫描 | 0.2h | 0 | 0 | 0.2h |
| D 文档 | 0 | 0 | 0.3h | 0.3h |

**合计 ≈ 2.6 人时**（不含 review），半日内可落。

---

## 11. 后续钩子（本 plan 不做，记录）

- **L3 Evidence → Verifier drift signal**：`evidence_spans[*].match == "none"` 是一个天然的 drift 告警——evaluator 声称"verbatim quote"但对不上原文。单独走 `PLAN_VERIFIER_DRIFT.md`。
- **L4 Evidence → RAG 反哺**：被 Verifier 挑过 bluff 的 span（有精确 start/end）切片入独立 vector store，下一次 generator 规避这些"被识破空话模式"。依赖 L3 drift monitor 产出的标注。
- **前端高亮渲染**：数据层已经 ready，后续 frontend PR 在 candidate answer 底下用 `evidence_spans` 画 `<mark>` 或彩条。

---

## 12. 执行触发

本 plan 确认后按 Step A → D 依次出 diff，每步独立 commit。默认行为等价（knob off），可安全随时 revert 任意单步。
