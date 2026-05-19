const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("candidate verdict labels use growth language and support legacy hire values", () => {
  const constants = read("src/lib/constants/verdicts.ts");
  const report = read("src/components/interview/ReportView.tsx");

  for (const value of ["excellent", "target_met", "near_target", "needs_focus"]) {
    assert.match(constants, new RegExp(value));
    assert.match(report, new RegExp(value));
  }

  assert.match(constants, /strong_hire/);
  assert.match(constants, /no_hire/);
  assert.match(report, /strong_hire/);
  assert.match(report, /no_hire/);

  assert.match(constants, /达到目标水平/);
  assert.match(constants, /重点补齐/);
  assert.match(report, /达到目标水平/);
  assert.match(report, /重点补齐/);

  assert.doesNotMatch(constants, /录用|不推荐/);
  assert.doesNotMatch(report, /录用|不推荐录用/);
});

test("report and history prefer growth_signal before deprecated overall_verdict", () => {
  const report = read("src/components/interview/ReportView.tsx");
  const history = read("src/components/interview/HistoryList.tsx");
  const types = read("src/lib/api/types.ts");

  assert.match(types, /growth_signal\?: string \| null/);
  assert.match(report, /growth_signal/);
  assert.match(report, /growth_signal[\s\S]*overall_verdict/);
  assert.match(history, /growth_signal/);
  assert.match(history, /growth_signal[\s\S]*overall_verdict/);
});

test("report summary displays the score-based verdict with a compact coverage caution", () => {
  const report = read("src/components/interview/ReportView.tsx");

  assert.match(report, /function displayGrowthSignal\(report: FinalReport\)/);
  assert.match(report, /function scoreBasedGrowthSignal\(report: FinalReport\)/);
  assert.match(report, /score >= threshold \+ 0\.5[\s\S]*return "excellent"/);
  assert.match(report, /score >= threshold[\s\S]*return "target_met"/);
  assert.doesNotMatch(report, /<CoverageCautionBanner report=\{report\} \/>/);
  assert.doesNotMatch(report, /function CoverageCautionBanner/);
  assert.match(report, /<CoverageCautionBadge report=\{report\} \/>/);
  assert.match(report, /function CoverageCautionBadge\(\{ report \}: \{ report: FinalReport \}\)/);
  assert.match(report, /部分维度待确认/);
  assert.doesNotMatch(report, /总分仍按已评分维度展示/);
  assert.match(report, /const verdict = displayGrowthSignal\(report\);/);
  assert.match(report, /const growthSignal = displayGrowthSignal\(report\);/);
});

test("quality center metric cards name concrete gaps and skill clues", () => {
  const report = read("src/components/interview/ReportView.tsx");

  assert.match(report, /summarizeCoverageWarnings/);
  assert.match(report, /summarizeSkillRows/);
  assert.match(report, /证据不足：/);
  assert.match(report, /主要追问：/);
  assert.match(report, /流程记录缺失/);
  assert.doesNotMatch(report, /value: traceHealth === "missing" \? "trace 缺失"/);
});

test("quality center uses whole-session clues instead of latest-turn wording", () => {
  const report = read("src/components/interview/ReportView.tsx");

  assert.match(report, /证据还不够的能力/);
  assert.match(report, /formatCoverageWarningStatus/);
  assert.match(report, /尚未追问到足够证据/);
  assert.match(report, /技能覆盖 Top/);
  assert.match(report, /row\.skill/);
  assert.match(report, /row\.count/);
  assert.match(report, /traceHealth !== "missing"/);
  assert.doesNotMatch(report, /本轮题目依据/);
});

test("quality center uses layered report typography instead of flat text", () => {
  const report = read("src/components/interview/ReportView.tsx");

  assert.match(report, /function QualityMetricCard/);
  assert.match(report, /splitMetricDescription/);
  assert.match(report, /qualityMetricTone/);
  assert.match(report, /text-\[11px\] font-semibold uppercase/);
  assert.match(report, /text-foreground\/90/);
  assert.match(report, /text-amber-200/);
  assert.match(report, /font-mono text-\[10px\]/);
});

test("quality center separates coverage summary from dimension detail", () => {
  const report = read("src/components/interview/ReportView.tsx");

  assert.match(report, /维度覆盖明细/);
  assert.match(report, /展示各能力维度的评分结果/);
  assert.match(report, /{dimensionRows.length > 0 && \(\s*<div className="rounded-lg border border-violet-500\/15/);
  assert.match(report, /border-violet-500\/15 bg-violet-500\/\[0\.025\] p-4/);
  assert.match(report, /text-\[11px\] font-semibold uppercase tracking-\[0\.16em\] text-violet-300/);
  assert.match(report, /border-violet-500\/15 bg-background\/45 px-3 py-2/);
  assert.match(report, /dimensionBadgeMeta\(score\)/);
  assert.match(report, /dimensionScoreLabel\(score\)/);
  assert.doesNotMatch(report, /上面是覆盖总览/);
  assert.doesNotMatch(report, /{dimensionRows.length > 0 && \(\s*<div className="grid gap-4 lg:grid-cols-2">/);
  assert.doesNotMatch(report, /row\.passed \? "已通过" : "待加强"/);
});

test("quality center summarizes scoring evidence without expanding evidence lists", () => {
  const report = read("src/components/interview/ReportView.tsx");

  assert.match(report, /const evidenceMetric: QualityMetric =/);
  assert.match(report, /grid gap-3 md:grid-cols-2/);
  assert.match(report, /label: "评分依据"/);
  assert.match(report, /未生成引用/);
  assert.match(report, /尚未生成可回查的评分引用/);
  assert.match(report, /评分所引用的回答片段中/);
  assert.match(report, /可回查到原始问答/);
  assert.doesNotMatch(report, /const evidenceMetric: QualityMetric \| null/);
  assert.doesNotMatch(report, /<div className="grid gap-3 md:grid-cols-4">[\s\S]*qualityMetrics\.map/);
  assert.doesNotMatch(report, /label: "证据可回溯"/);
  assert.doesNotMatch(report, /评分依据中的原文引用可回查到你的回答。/);
});

test("quality center keeps developer-only contract and policy details collapsed", () => {
  const report = read("src/components/interview/ReportView.tsx");

  assert.match(report, /<summary[\s\S]*查看开发者细节[\s\S]*<\/summary>/);
  assert.match(report, /这些信息用于排查报告生成链路/);
  assert.match(report, /DeveloperFact[\s\S]*label="评分检查项"/);
  assert.match(report, /code="contract_checks"/);
  assert.match(report, /DeveloperFact[\s\S]*label="策略路径"/);
  assert.match(report, /code="policy_ids"/);
  assert.match(report, /合同检查项的通过分布/);
  assert.match(report, /本场追问和报告生成命中过的策略/);
  assert.match(report, /text-foreground\/95/);
  assert.match(report, /border-border\/70 bg-black\/20 px-2\.5 py-2/);
  assert.match(report, /leading-relaxed text-muted-foreground/);
  assert.doesNotMatch(report, /<p className="mb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">\s*评分检查项\s*<\/p>/);
  assert.doesNotMatch(report, /<p className="mb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">\s*策略路径\s*<\/p>/);
  assert.doesNotMatch(report, /label="contract_summary"/);
});
