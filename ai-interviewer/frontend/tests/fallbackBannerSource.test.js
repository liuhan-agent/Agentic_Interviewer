const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("ReportView mounts a fallback verdict banner above Summary", () => {
  const source = read("src/components/interview/ReportView.tsx");

  assert.match(source, /function FallbackVerdictBanner/);
  assert.match(source, /<FallbackVerdictBanner report=\{report\}/);
  assert.match(source, /FALLBACK_BANNER_THRESHOLD/);
  assert.match(source, /评分仅供参考/);
});

test("FallbackVerdictBanner stays quiet for low fallback ratios", () => {
  const source = read("src/components/interview/ReportView.tsx");

  // Threshold 0.3 mirrors plan B3: "≥30% of turns went conservative"
  assert.match(source, /FALLBACK_BANNER_THRESHOLD = 0\.3/);
  // Both guards: zero turns AND zero fallback => return null
  assert.match(source, /if \(total <= 0 \|\| fallbackCount <= 0\) return null/);
});

test("FinalReport API type exposes evaluator_fallback_count + total_turns", () => {
  const types = read("src/lib/api/types.ts");

  assert.match(types, /evaluator_fallback_count\?: number/);
  assert.match(types, /total_turns\?: number/);
});

test("ReportView ProgressChart shows the weak threshold reference line", () => {
  const source = read("src/components/interview/ProgressChart.tsx");

  assert.match(source, /import \{[\s\S]*?ReferenceLine[\s\S]*?\} from "recharts"/);
  assert.match(source, /<ReferenceLine[\s\S]*?y=\{WEAK_DIMENSION_THRESHOLD\}/);
  assert.match(source, /达标线/);
});

test("TrainingPlanSourceBadge surfaces a11y label and tabIndex", () => {
  const source = read("src/components/interview/TrainingPlanSourceBadge.tsx");

  assert.match(source, /aria-label=/);
  assert.match(source, /tabIndex=\{0\}/);
});
