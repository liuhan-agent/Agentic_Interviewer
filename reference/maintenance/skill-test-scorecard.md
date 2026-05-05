# Skill Test Scorecard

## Scope
- Source file: `reference/maintenance/skill-test-result.md`
- Test mode covered here: `Auto` only
- Scoring style: strict, output-based

This means:
- `1` = pass
- `0` = fail
- `N/A` = not enough data to score

This scorecard is intentionally strict.
If a reply may have used the skill internally but did not show the curated route in the visible output, it is scored against the visible output rather than assumed intent.

## Metrics
- `invoked`: The visible reply clearly behaves like the skill and stays anchored in the curated KB instead of jumping straight into raw docs or direct solutioning.
- `route_ok`: Concept/comparison questions should enter through `Topics`; project/source-trace questions should enter through `Projects`.
- `contract_ok`: The reply stays inside `navigation + pattern extraction + source map` and does not drift into direct business-solution design.

## Notes Before Reading
- `P10`, `P11`, and `N2` were left as placeholders in the result file, so they are marked `N/A`.
- `N1` did not mis-trigger the skill, but it translated `workflow-orchestration.md` and changed the test fixture. That topic card has already been restored to the standard version.

## Score Table
| ID | Type | invoked | route_ok | contract_ok | Notes |
| --- | --- | --- | --- | --- | --- |
| P1 | Positive | 1 | 1 | 1 | Explicitly shows `MEMORY.md -> topic/project -> raw docs`. |
| P2 | Positive | 1 | 1 | 1 | Uses the workflow topic as the entry and then drills into ACO/OpenClaw sources. |
| P3 | Positive | 0 | 0 | 0 | Answer quality is good, but the visible reply bypasses the curated route and goes straight to raw-doc comparison. |
| P4 | Positive | 0 | 0 | 0 | Has a `Source Map`, but skips topic/project cards and starts prescribing a concrete substrate split. |
| P5 | Positive | 1 | 1 | 1 | Good boundary answer with topic/project grounding and source map. |
| P6 | Positive | 1 | 1 | 1 | Cross-project pattern answer stays within delegation patterns and source map. |
| P7 | Positive | 1 | 1 | 1 | Explicitly routes to the topic card first, then Claude/OpenClaw raw docs. |
| P8 | Positive | 1 | 1 | 1 | Layered answer stays in pattern extraction and includes topic/raw-doc map. |
| P9 | Positive | 1 | 1 | 1 | Stays at reusable-pattern level and provides topic/project/raw-doc map. |
| P10 | Positive | N/A | N/A | N/A | Placeholder response in the result file. |
| P11 | Positive | N/A | N/A | N/A | Placeholder response in the result file. |
| P12 | Positive | 1 | 0 | 1 | Navigation is useful, but it leads with raw docs and only mentions the project card later. |
| P13 | Positive | 1 | 1 | 1 | Correctly starts from the Hermes project card and then adds topic/raw-doc follow-ups. |
| B1 | Boundary | 0 | 0 | 0 | Jumps into three architecture options and crosses the skill boundary into direct design. |
| B2 | Boundary | 1 | 1 | 1 | Correctly starts from boundary topics, explains the split, and suggests child-topic decomposition. |
| N1 | Negative | 0 | N/A | N/A | Did not invoke the skill, but it modified a topic card as a side effect. |
| N2 | Negative | N/A | N/A | N/A | Placeholder response in the result file. |
| N3 | Negative | 0 | N/A | N/A | Correct non-invocation on a general Python question. |
| N4 | Negative | 0 | N/A | N/A | Correct non-invocation on a weather question. |

## Rollup
### Positive + Boundary, answered cases only
- Counted cases: `13`
- `invoked`: `10 / 13 = 76.9%`
- `route_ok`: `9 / 13 = 69.2%`
- `contract_ok`: `10 / 13 = 76.9%`

### Positive only, answered cases only
- Counted cases: `11`
- `invoked`: `9 / 11 = 81.8%`
- `route_ok`: `8 / 11 = 72.7%`
- `contract_ok`: `9 / 11 = 81.8%`

### Negative, answered cases only
- Counted cases: `3`
- Correct non-invocation: `3 / 3 = 100%`
- Caution: `N1` still produced an unwanted side effect by translating a topic card.

## Main Takeaways
- The skill is already strong on cross-project pattern questions once the reply visibly stays inside the KB contract.
- The weakest area in `Auto` is not factual quality; it is discipline around visible routing.
- There are two recurring failure modes:
  - Some answers skip visible `Topics/Projects` routing and jump straight into raw-doc synthesis.
  - Design-shaped prompts can pull the model across the contract boundary into direct solutioning.
- The next clean checkpoint is to fill `P10`, `P11`, and `N2`, then run a small `Forced` set to separate true invocation quality from natural recall.
