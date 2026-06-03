# Anchor-Aware Dimension Score Aggregation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for code changes and superpowers:verification-before-completion before claiming completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade report dimension scoring from turn-sequence aggregation to anchor-aware aggregation, so repeated follow-ups on one resume anchor do not dominate a dimension that covers multiple resume anchors.

**Architecture:** Keep evaluator/router flow unchanged. Replace the report scoring source with an anchor-aware breakdown built from `qa_history`: first aggregate turns inside each `resume_anchor_key`, then aggregate anchor scores into the dimension score with the approved formula. Preserve existing frontend `dimension_scores[*].score` contract and add optional breakdown metadata for explainability.

**Tech Stack:** Python 3.11, SQLAlchemy-backed workflow state, pytest, Ruff, TypeScript/React report UI.

---

## Approved Policy

- Same anchor aggregation: use existing `weighted_recent` turn aggregation inside each anchor.
- Multi-anchor dimension aggregation: `dimension_score = 0.8 * anchor_average + 0.2 * best_anchor_score`.
- Unanchored turns: group under virtual anchor `unanchored:{dimension}`.
- Single-anchor dimension: dimension score equals that anchor score.
- `dimension_status`: unchanged; keep existing evaluator/router pass/fail semantics.
- Frontend: show a short explanation only; no complex new detail page.
- Compatibility: keep `score`, `score_breakdown.adopted_score`, and `score_breakdown.scoring_policy`; upgrade policy name to `anchor_weighted_recent` for new breakdowns.
- Database schema: no changes.

## File Map

- Modify: `app/engine/workflow/score_aggregation.py`
  - Add anchor identity helpers.
  - Make `build_score_breakdowns_from_qa()` return anchor-aware dimension breakdowns.
  - Keep `update_score_breakdown()` as the same-anchor weighted-recent primitive.

- Modify: `app/engine/workflow/nodes/evaluator.py`
  - When a real scored turn arrives, rebuild current dimension breakdown from `state.qa_history + [qa_turn]`.
  - Continue skipping fallback/skipped turns.
  - Continue writing `scores_per_dim[dimension] = score_breakdown["adopted_score"]`.

- Modify: `app/engine/workflow/nodes/final_report.py`
  - Use anchor-aware rebuilt breakdowns from `qa_history`.
  - Keep output shape compatible.
  - Include `anchor_breakdowns`, `anchor_count`, `anchor_average_score`, and `best_anchor_score` inside `score_breakdown`.

- Modify: `tests/unit/test_score_aggregation.py`
  - Add red tests for same-anchor, multi-anchor, and unanchored behavior.
  - Update existing turn-only expectation to the new anchor-aware policy.

- Modify: `tests/unit/test_final_report_evidence.py`
  - Update multi-turn score breakdown expectations.
  - Add a report-level test proving multi-anchor dimension score and `score_breakdown.anchor_breakdowns` are emitted.

- Modify: `tests/unit/test_evaluator_fallback_isolation.py`
  - Update score breakdown assertions to include anchor-aware fields.
  - Add/adjust a test proving fallback turns are not counted in anchor scores.

- Modify: `frontend/src/lib/api/types.ts`
  - Extend `ScoreBreakdown` with optional anchor-aware fields.

- Modify: `frontend/src/components/interview/ReportView.tsx`
  - Update `dimensionScoreBreakdownLabel()` to mention anchor count when `anchor_count > 1`.
  - Keep single-anchor/legacy wording readable.

- Modify: `frontend/tests/reportScoreStatusSource.test.js`
  - Add a source-level assertion that the report explains anchor-aware aggregation.

## Data Shape

Expected backend `score_breakdown` shape:

```json
{
  "scored_turn_count": 3,
  "latest_score": 7.0,
  "best_score": 9.0,
  "average_score": 7.65,
  "adopted_score": 7.78,
  "scoring_policy": "anchor_weighted_recent",
  "anchor_count": 2,
  "anchor_average_score": 7.65,
  "best_anchor_score": 8.3,
  "anchor_breakdowns": [
    {
      "anchor_key": "focus-payment-consistency",
      "anchor_label": "Payment consistency",
      "resume_project_id": "proj-pay",
      "turn_indices": [0, 1],
      "scored_turn_count": 2,
      "latest_score": 9.0,
      "best_score": 9.0,
      "average_score": 8.5,
      "adopted_score": 8.3,
      "scoring_policy": "weighted_recent"
    },
    {
      "anchor_key": "focus-cache-failover",
      "anchor_label": "Cache failover",
      "resume_project_id": "proj-cache",
      "turn_indices": [2],
      "scored_turn_count": 1,
      "latest_score": 7.0,
      "best_score": 7.0,
      "average_score": 7.0,
      "adopted_score": 7.0,
      "scoring_policy": "weighted_recent"
    }
  ]
}
```

Rounding rule:

- Round calculated aggregate fields to 3 decimals, matching the current score aggregation style.
- Existing one-turn values may remain as plain floats like `8.0`.

Anchor identity rule:

```python
anchor_key = (
    qa.get("resume_anchor", {}).get("anchor_key")
    or qa.get("resume_anchor_key")
    or f"unanchored:{dimension}"
)
```

Anchor label rule:

```python
anchor_label = (
    qa.get("resume_anchor", {}).get("label")
    or qa.get("resume_anchor", {}).get("project_name")
    or qa.get("resume_anchor_label")
    or "未关联简历锚点"
)
```

## Tasks

### Task 1: Add Anchor-Aware Aggregation Tests

**Files:**
- Modify: `tests/unit/test_score_aggregation.py`

- [ ] **Step 1: Add failing test for same-anchor weighted recent**

Add a test where two turns in the same dimension share `resume_anchor.anchor_key = "focus-a"` with scores `8.0` and `9.0`.

Expected:

```python
breakdowns["technical_depth"]["adopted_score"] == 8.3
breakdowns["technical_depth"]["anchor_count"] == 1
breakdowns["technical_depth"]["scoring_policy"] == "anchor_weighted_recent"
breakdowns["technical_depth"]["anchor_breakdowns"][0]["adopted_score"] == 8.3
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
python -m pytest tests/unit/test_score_aggregation.py::test_anchor_aware_breakdown_keeps_same_anchor_weighted_recent -q
```

Expected: fail because `anchor_count` / `anchor_breakdowns` are missing and `scoring_policy` is still `weighted_recent`.

- [ ] **Step 3: Add failing test for multi-anchor dimension aggregation**

Use three turns:

- Anchor A scores: `8.0`, `9.0`, producing anchor score `8.3`.
- Anchor B score: `7.0`, producing anchor score `7.0`.

Expected dimension score:

```python
anchor_average = (8.3 + 7.0) / 2
dimension_score = round((0.8 * anchor_average) + (0.2 * 8.3), 3)  # 7.78
```

Assertions:

```python
breakdowns["technical_depth"]["adopted_score"] == 7.78
breakdowns["technical_depth"]["anchor_average_score"] == 7.65
breakdowns["technical_depth"]["best_anchor_score"] == 8.3
breakdowns["technical_depth"]["anchor_count"] == 2
```

- [ ] **Step 4: Add failing test for unanchored virtual anchor**

Use a turn without `resume_anchor` and assert:

```python
anchor = breakdowns["coding_quality"]["anchor_breakdowns"][0]
assert anchor["anchor_key"] == "unanchored:coding_quality"
assert anchor["anchor_label"] == "未关联简历锚点"
```

### Task 2: Implement Anchor-Aware Aggregation

**Files:**
- Modify: `app/engine/workflow/score_aggregation.py`

- [ ] **Step 1: Add helper functions**

Add private helpers:

```python
def _anchor_key_for_turn(qa: dict[str, Any], dimension: str) -> str:
    anchor = qa.get("resume_anchor") if isinstance(qa.get("resume_anchor"), dict) else {}
    key = str(anchor.get("anchor_key") or qa.get("resume_anchor_key") or "").strip()
    return key or f"unanchored:{dimension}"


def _anchor_label_for_turn(qa: dict[str, Any]) -> str:
    anchor = qa.get("resume_anchor") if isinstance(qa.get("resume_anchor"), dict) else {}
    label = str(
        anchor.get("label")
        or anchor.get("project_name")
        or qa.get("resume_anchor_label")
        or ""
    ).strip()
    return label or "未关联简历锚点"


def _anchor_project_id_for_turn(qa: dict[str, Any]) -> str | None:
    anchor = qa.get("resume_anchor") if isinstance(qa.get("resume_anchor"), dict) else {}
    project_id = str(anchor.get("project_id") or qa.get("resume_project_id") or "").strip()
    return project_id or None
```

- [ ] **Step 2: Build per-anchor breakdowns**

Inside `build_score_breakdowns_from_qa()`, group valid scored turns by `(dimension, anchor_key)`. For each anchor group, call `update_score_breakdown()` in turn order and add metadata:

```python
anchor_breakdown.update(
    {
        "anchor_key": anchor_key,
        "anchor_label": anchor_label,
        "resume_project_id": resume_project_id,
        "turn_indices": turn_indices,
    }
)
```

- [ ] **Step 3: Aggregate anchor scores into dimension score**

For each dimension:

```python
anchor_scores = [anchor["adopted_score"] for anchor in anchors]
anchor_average = round(sum(anchor_scores) / len(anchor_scores), 3)
best_anchor = max(anchor_scores)
adopted = anchor_scores[0] if len(anchor_scores) == 1 else round((0.8 * anchor_average) + (0.2 * best_anchor), 3)
```

Dimension-level fields:

```python
{
    "scored_turn_count": total_scored_turns,
    "latest_score": latest_turn_score,
    "best_score": max(anchor_scores),
    "average_score": anchor_average,
    "adopted_score": adopted,
    "scoring_policy": "anchor_weighted_recent",
    "anchor_count": len(anchors),
    "anchor_average_score": anchor_average,
    "best_anchor_score": best_anchor,
    "anchor_breakdowns": anchors,
}
```

- [ ] **Step 4: Run score aggregation tests**

Run:

```bash
python -m pytest tests/unit/test_score_aggregation.py -q
```

Expected: all tests pass after updating old expectations to the new policy where appropriate.

### Task 3: Update Evaluator Runtime Scoring

**Files:**
- Modify: `app/engine/workflow/nodes/evaluator.py`
- Modify: `tests/unit/test_evaluator_fallback_isolation.py`

- [ ] **Step 1: Add/adjust evaluator test**

Add or update a test proving evaluator state output writes:

```python
update["score_breakdowns"]["technical_depth"]["scoring_policy"] == "anchor_weighted_recent"
update["score_breakdowns"]["technical_depth"]["anchor_count"] >= 1
```

- [ ] **Step 2: Verify evaluator test fails**

Run:

```bash
python -m pytest tests/unit/test_evaluator_fallback_isolation.py -q
```

Expected: fail until evaluator uses anchor-aware breakdowns.

- [ ] **Step 3: Rebuild current dimension breakdown from full history**

In `evaluator_node`, after `qa_turn` is built and `new_score is not None`, replace direct `update_score_breakdown(existing_breakdown, new_score)` usage with:

```python
rebuilt = build_score_breakdowns_from_qa(
    list(state.get("qa_history") or []) + [qa_turn]
)
next_breakdown = rebuilt.get(dimension)
if next_breakdown is not None:
    score_breakdowns[dimension] = next_breakdown
    scores[dimension] = next_breakdown["adopted_score"]
    score_breakdowns_changed = True
```

Keep the existing fallback guard so evaluator fallback turns do not update scores.

- [ ] **Step 4: Run evaluator tests**

Run:

```bash
python -m pytest tests/unit/test_evaluator_fallback_isolation.py -q
```

Expected: pass.

### Task 4: Update Final Report Expectations

**Files:**
- Modify: `app/engine/workflow/nodes/final_report.py` if needed
- Modify: `tests/unit/test_final_report_evidence.py`

- [ ] **Step 1: Add report test for multi-anchor dimension score**

Create `qa_history` with two anchors in `technical_depth` and assert:

```python
report["dimension_scores"]["technical_depth"]["score"] == 7.78
breakdown = report["dimension_scores"]["technical_depth"]["score_breakdown"]
assert breakdown["anchor_count"] == 2
assert breakdown["scoring_policy"] == "anchor_weighted_recent"
assert [a["anchor_key"] for a in breakdown["anchor_breakdowns"]] == [
    "focus-a",
    "focus-b",
]
```

- [ ] **Step 2: Update existing multi-turn expectation**

For a same-anchor or unanchored five-turn sequence `[9, 9, 9, 9, 8]`, expected `adopted_score` remains `8.7`, but the breakdown now includes:

```python
"scoring_policy": "anchor_weighted_recent"
"anchor_count": 1
"anchor_breakdowns": [...]
```

- [ ] **Step 3: Run final report tests**

Run:

```bash
python -m pytest tests/unit/test_final_report_evidence.py -q
```

Expected: pass.

### Task 5: Update Frontend Types and Report Explanation

**Files:**
- Modify: `frontend/src/lib/api/types.ts`
- Modify: `frontend/src/components/interview/ReportView.tsx`
- Modify: `frontend/tests/reportScoreStatusSource.test.js`

- [ ] **Step 1: Extend TypeScript types**

Add optional fields to `ScoreBreakdown`:

```ts
anchor_count?: number;
anchor_average_score?: number;
best_anchor_score?: number;
anchor_breakdowns?: Array<{
  anchor_key: string;
  anchor_label?: string;
  resume_project_id?: string | null;
  turn_indices?: number[];
  scored_turn_count: number;
  latest_score: number;
  best_score: number;
  average_score: number;
  adopted_score: number;
  scoring_policy: string;
}>;
```

- [ ] **Step 2: Update report label helper**

In `dimensionScoreBreakdownLabel(score)`, when `breakdown.anchor_count && breakdown.anchor_count > 1`, return wording like:

```ts
return `本维度综合了 ${breakdown.anchor_count} 个简历锚点，锚点均值 ${breakdown.anchor_average_score.toFixed(1)}，最佳锚点 ${breakdown.best_anchor_score.toFixed(1)}；综合分 ${breakdown.adopted_score.toFixed(1)}。`;
```

For legacy/single-anchor data, keep the existing turn-count wording.

- [ ] **Step 3: Add source test**

In `frontend/tests/reportScoreStatusSource.test.js`, assert `ReportView.tsx` contains:

```js
assert.match(report, /简历锚点/);
assert.match(report, /anchor_count/);
```

- [ ] **Step 4: Run frontend source tests**

Run from `ai-interviewer/frontend`:

```bash
npm test -- reportScoreStatusSource.test.js
```

Expected: pass.

If this repo uses a different frontend test command locally, inspect `frontend/package.json` and run the matching test script for that file.

### Task 6: Focused Verification

**Files:**
- No code changes.

- [ ] **Step 1: Run backend focused tests**

Run from `ai-interviewer/backend`:

```bash
python -m pytest tests/unit/test_score_aggregation.py tests/unit/test_evaluator_fallback_isolation.py tests/unit/test_final_report_evidence.py -q
```

Expected: all pass.

- [ ] **Step 2: Run backend Ruff**

Run:

```bash
python -m ruff check app/engine/workflow/score_aggregation.py app/engine/workflow/nodes/evaluator.py app/engine/workflow/nodes/final_report.py tests/unit/test_score_aggregation.py tests/unit/test_evaluator_fallback_isolation.py tests/unit/test_final_report_evidence.py
```

Expected: `All checks passed!`

- [ ] **Step 3: Run relevant frontend checks**

Run from `ai-interviewer/frontend`:

```bash
npm test -- reportScoreStatusSource.test.js
```

Then run the project's typecheck command if available in `package.json`.

- [ ] **Step 4: Optional broader backend unit pass**

If focused tests pass and time allows, run:

```bash
python -m pytest tests/unit
```

Expected: no new failures. If unrelated pre-existing failures appear, document them with failing test names and continue only if the anchor scoring focused tests remain green.

## Acceptance Criteria

- `build_score_breakdowns_from_qa()` produces `anchor_weighted_recent` breakdowns.
- Same-anchor follow-ups still use weighted-recent turn aggregation.
- Multi-anchor dimensions use `0.8 * anchor_average + 0.2 * best_anchor_score`.
- Unanchored turns are counted under `unanchored:{dimension}`.
- `dimension_status` behavior is unchanged.
- Existing `dimension_scores[*].score` remains the frontend-facing score.
- `score_breakdown.anchor_breakdowns` is present for new reports.
- Frontend report explains multi-anchor score aggregation in compact wording.
- No DB schema change.

## Goal Mode Prompt

```text
Use Goal mode to implement D:\Agent\Agentic_Interviewer\ai-interviewer\backend\docs\PLAN_ANCHOR_SCORE_AGGREGATION.md.

Implement one checkpoint at a time. Use TDD: write/adjust the failing test first, run it to confirm the expected failure, then implement the minimal code, then rerun the focused tests. Preserve the approved scoring policy exactly:
- same anchor: weighted_recent
- multi-anchor dimension: 0.8 * anchor_average + 0.2 * best_anchor_score
- unanchored turns: unanchored:{dimension}
- dimension_status unchanged
- no database schema changes

After each checkpoint, report changed files and validation results. Stop if tests fail in a way you cannot diagnose after two fix attempts. Do not broaden the scope beyond this plan unless required to keep existing contracts working.
```

