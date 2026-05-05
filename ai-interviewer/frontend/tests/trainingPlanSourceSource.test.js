const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("shared TrainingPlanSourceBadge component exists with both variants", () => {
  const badge = read("src/components/interview/TrainingPlanSourceBadge.tsx");

  assert.match(badge, /export function TrainingPlanSourceBadge/);
  assert.match(badge, /AI 复盘/);
  assert.doesNotMatch(badge, /AI 教练/);
  assert.match(badge, /系统聚合/);
  assert.match(badge, /source === "llm"/);
  assert.match(badge, /source === "fallback"/);
  // Returns null when source is unknown so the call site keeps shape.
  assert.match(badge, /return null;/);
});

test("ReportView TrainingPlanCard renders the shared badge", () => {
  const source = read("src/components/interview/ReportView.tsx");

  assert.match(source, /import \{ TrainingPlanSourceBadge \}/);
  assert.match(source, /<TrainingPlanSourceBadge source=\{planSource\} \/>/);
  // The legacy inline badge JSX should be gone (refactored to shared).
  assert.doesNotMatch(source, /planSource === "llm" &&[\s\S]*?<Badge/);
});

test("ReplayView TrainingPlanCard renders the shared badge", () => {
  const source = read("src/components/interview/ReplayView.tsx");

  assert.match(source, /import \{ TrainingPlanSourceBadge \}/);
  assert.match(source, /<TrainingPlanSourceBadge source=\{source\} \/>/);
  // ReplayView passes the source down from ReplayResponse.training_plan
  assert.match(
    source,
    /source=\{[\s\S]*?replay\.training_plan\?\.source[\s\S]*?\}/,
  );
});

test("TrainingPlan API type exposes the source field", () => {
  const types = read("src/lib/api/types.ts");

  assert.match(types, /source\?: "llm" \| "fallback" \| string/);
});
