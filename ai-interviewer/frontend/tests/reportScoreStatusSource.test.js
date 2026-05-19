const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("ReportView dimension scores render backend score status semantics", () => {
  const report = read("src/components/interview/ReportView.tsx");

  assert.match(report, /function dimensionScoreLabel/);
  assert.match(report, /function dimensionBadgeMeta/);
  assert.match(report, /score_status === "skipped"[\s\S]*已跳过/);
  assert.match(report, /score_status === "evaluator_unavailable"[\s\S]*评估失败/);
  assert.match(report, /score_status === "not_evaluated"[\s\S]*未评分/);
  assert.match(report, /coverage_status === "coverage_limited"[\s\S]*覆盖不足/);
  assert.match(report, /coverage_status === "below_threshold"[\s\S]*待提升/);
  assert.doesNotMatch(report, /typeof s\.score === "number" \? s\.score\.toFixed\(1\) : "-"\} \/ 10/);
});

test("ReportView explains multi-turn dimension score breakdowns", () => {
  const report = read("src/components/interview/ReportView.tsx");

  assert.match(report, /function dimensionScoreBreakdownLabel/);
  assert.match(report, /score\.score_breakdown/);
  assert.match(report, /scored_turn_count > 1/);
  assert.match(report, /latest_score[\s\S]*best_score[\s\S]*average_score[\s\S]*adopted_score/);
  assert.match(report, /breakdownLabel[\s\S]*text-\[11px\][\s\S]*text-muted-foreground\/60/);
});

test("ReportView treats legacy numeric dimensions with evidence as scored", () => {
  const report = read("src/components/interview/ReportView.tsx");

  assert.match(report, /function hasDisplayableDimensionScore/);
  assert.match(report, /if \(score\.score_status\) return false;[\s\S]*return score\.score > 0/);
  assert.match(report, /function hasDimensionScoreEvidence/);
  assert.match(report, /score\.rationale[\s\S]*score\.weaknesses/);
  assert.match(report, /function dimensionScoreLabel[\s\S]*hasDisplayableDimensionScore\(score\)[\s\S]*toFixed\(1\)/);
  assert.match(report, /function dimensionBadgeMeta[\s\S]*hasDisplayableDimensionScore\(score\)[\s\S]*coverage_limited/);
});

test("ReportView radar excludes unscored dimensions instead of drawing them as zero", () => {
  const report = read("src/components/interview/ReportView.tsx");

  assert.match(report, /const scoredEntries = Object\.entries\(scores\)\.filter/);
  assert.match(report, /hasDisplayableDimensionScore\(entry\[1\]\)/);
  assert.match(report, /scoredEntries\.length < 3/);
  assert.match(report, /const excludedEntries = Object\.entries\(scores\)/);
  assert.match(report, /未纳入雷达/);
  assert.match(report, /暂无有效评分，详见下方评分维度/);
  assert.match(report, /excludedEntries\.slice\(0, 3\)/);
  assert.doesNotMatch(report, /score: typeof s\.score === "number" \? s\.score : 0/);
});

test("ReportView radar keeps excluded dimensions as a quiet hint", () => {
  const report = read("src/components/interview/ReportView.tsx");

  assert.match(report, /text-center text-xs leading-relaxed text-muted-foreground\/70/);
  assert.match(report, /excludedPreview\.map\(\(entry\) => entry\.label\)\.join\("、"\)/);
  assert.doesNotMatch(report, /\{entry\.label\}：\{entry\.reason\}/);
  assert.doesNotMatch(report, /function radarExclusionReason/);
});

test("ReportView radar keeps labels clean and shows the outer contour", () => {
  const report = read("src/components/interview/ReportView.tsx");

  assert.match(report, /function renderRadarAngleTick/);
  assert.match(report, /tick=\{renderRadarAngleTick\}/);
  assert.match(report, /gridType="polygon"/);
  assert.match(report, /strokeOpacity=\{0\.34\}[\s\S]*radialLines/);
  assert.match(report, /dataKey="score"[\s\S]*dataKey="fullMark"/);
  assert.match(report, /dataKey="fullMark"[\s\S]*strokeOpacity=\{0\.42\}/);
  assert.match(report, /dataKey="fullMark"[\s\S]*tooltipType="none"/);
  assert.match(report, /tick=\{false\}/);
  assert.match(report, /outerRadius="76%"/);
  assert.match(report, /margin=\{\{ top: 36, right: 32, bottom: 36, left: 32 \}\}/);
  assert.doesNotMatch(report, /tick=\{\{ fill: "hsl\(var\(--muted-foreground\)\)", fontSize: 10 \}\}/);
});
