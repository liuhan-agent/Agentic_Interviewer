const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("TrainingPlanCard separates body copy from explanatory copy", () => {
  const source = read("src/components/interview/ReportView.tsx");

  assert.match(source, /const TRAINING_PLAN_TEXT_STYLES = \{/);
  assert.match(source, /body:[\s\S]*text-\[13px\][\s\S]*text-foreground\/80/);
  assert.match(source, /analysisBadge:[\s\S]*inline-flex/);
  assert.match(
    source,
    /analysisBadge:\s*"[^"]*border-blue-500\/25[^"]*bg-blue-500\/10[^"]*text-blue-300\/85/,
  );
  assert.match(source, /diagnosisBadge:[\s\S]*inline-flex/);
  assert.match(source, /analysis:[\s\S]*text-xs[\s\S]*text-muted-foreground\/70/);
  assert.match(source, /weaknessTitle:[\s\S]*text-sm[\s\S]*font-medium[\s\S]*text-foreground\/85/);
  assert.doesNotMatch(source, /analysisLabel:/);
  assert.match(source, /description:[\s\S]*text-muted-foreground\/70/);
  assert.match(source, /meta:[\s\S]*text-muted-foreground\/70/);
  assert.match(source, /steps:[\s\S]*text-xs[\s\S]*text-foreground\/60/);
  assert.match(source, /evidenceWrap:[\s\S]*bg-amber-500/);
  assert.match(source, /evidenceLabel:[\s\S]*text-amber-300/);
  assert.match(source, /evidence:[\s\S]*italic/);
  assert.match(source, /success:[\s\S]*bg-emerald-500/);
  assert.match(source, /successItem:[\s\S]*text-xs[\s\S]*text-emerald-50\/70/);
  assert.match(source, /className=\{TRAINING_PLAN_TEXT_STYLES\.body\}/);
  assert.match(source, /目标差距/);
  assert.match(source, /className=\{TRAINING_PLAN_TEXT_STYLES\.diagnosisBadge\}/);
  assert.match(
    source,
    /<span className=\{TRAINING_PLAN_TEXT_STYLES\.diagnosisBadge\}>[\s\S]*目标差距[\s\S]*<\/span>[\s\S]*<p className=\{TRAINING_PLAN_TEXT_STYLES\.description\}>[\s\S]*\{diagnosis\.target_level_gap\}/,
  );
  assert.match(source, /className=\{TRAINING_PLAN_TEXT_STYLES\.description\}/);
  assert.match(source, /className=\{TRAINING_PLAN_TEXT_STYLES\.meta\}/);
  assert.match(source, /TRAINING_PLAN_TEXT_STYLES\.steps/);
  assert.match(source, /function TrainingPlanEvidence/);
  assert.match(source, /回答证据/);
  assert.match(source, /className=\{TRAINING_PLAN_TEXT_STYLES\.evidence\}/);
  assert.match(source, /<TrainingPlanEvidence key=\{i\} text=\{ref\} \/>/);
  assert.match(source, /<TrainingPlanEvidence text=\{\(w as any\)\.evidence\} \/>/);
  assert.match(source, /function TrainingPlanWeaknessAnalysis/);
  assert.match(source, /不足分析/);
  assert.match(source, /className=\{TRAINING_PLAN_TEXT_STYLES\.weaknessTitle\}/);
  assert.match(source, /\{translateReportText\(w\.focus\)\}/);
  assert.match(source, /<TrainingPlanWeaknessAnalysis text=\{w\.why_it_matters\} \/>/);
  assert.match(
    source,
    /<p className=\{TRAINING_PLAN_TEXT_STYLES\.weaknessTitle\}>[\s\S]*\{translateReportText\(w\.focus\)\}[\s\S]*<\/p>[\s\S]*<TrainingPlanWeaknessAnalysis text=\{w\.why_it_matters\} \/>/,
  );
  assert.match(source, /className=\{TRAINING_PLAN_TEXT_STYLES\.analysisBadge\}/);
  assert.match(
    source,
    /<div className=\{TRAINING_PLAN_TEXT_STYLES\.analysisWrap\}>[\s\S]*<span className=\{TRAINING_PLAN_TEXT_STYLES\.analysisBadge\}>[\s\S]*<\/span>[\s\S]*<p className=\{TRAINING_PLAN_TEXT_STYLES\.analysis\}>/,
  );
  assert.match(source, /TRAINING_PLAN_TEXT_STYLES\.successItem/);
});

test("TrainingPlanCard names 30/60/90 goals as training goals", () => {
  const source = read("src/components/interview/ReportView.tsx");

  assert.match(source, /30\/60\/90 \u5929\u8bad\u7ec3\u76ee\u6807/);
  assert.doesNotMatch(source, /\u91cc\u7a0b\u7891/);
});
