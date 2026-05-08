const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("report view renders an interview quality center", () => {
  const source = read("src/components/interview/ReportView.tsx");

  assert.match(source, /QualityCenter/);
  assert.match(source, /面试质量中心/);
  assert.match(source, /题目个性化/);
  assert.match(source, /能力覆盖/);
  assert.match(source, /评分可信度/);
});

test("quality center keeps developer trace details collapsed", () => {
  const source = read("src/components/interview/ReportView.tsx");

  assert.match(source, /查看开发者细节/);
  assert.match(source, /latest_selected_action/);
  assert.match(source, /latest_verification/);
  assert.match(source, /policy_ids/);
});

test("quality center guards backend observability links behind admin env flag", () => {
  const source = read("src/components/interview/ReportView.tsx");

  assert.match(source, /查看后台观测/);
  assert.match(source, /NEXT_PUBLIC_ADMIN_NAV_ENABLED/);
  assert.match(source, /showAdminLinks/);
  assert.match(source, /showAdminLinks\s*&&/);
  assert.ok(source.includes("href=\"/admin\""));
});

test("quality center exposes rich report data sections", () => {
  const source = read("src/components/interview/ReportView.tsx");

  assert.match(source, /维度覆盖明细/);
  assert.match(source, /技能覆盖 Top/);
  assert.match(source, /评分检查项/);
  assert.match(source, /策略路径/);
  assert.match(source, /target_skill_coverage/);
  assert.match(source, /checks_no/);
});

test("quality center surfaces evidence traceability", () => {
  const reportSource = read("src/components/interview/ReportView.tsx");
  const typesSource = read("src/lib/api/types.ts");

  assert.match(typesSource, /interface EvidenceSummary/);
  assert.match(typesSource, /evidence_summary\?: EvidenceSummary/);
  assert.match(reportSource, /证据可回溯/);
  assert.match(reportSource, /evidence_summary/);
  assert.match(reportSource, /unmatched_quotes/);
});

test("quality center consumes backend credibility summary contract", () => {
  const reportSource = read("src/components/interview/ReportView.tsx");
  const typesSource = read("src/lib/api/types.ts");

  assert.match(typesSource, /interface ScoringCredibility/);
  assert.match(typesSource, /credibility_summary\?: ScoringCredibility/);
  assert.match(typesSource, /credibility_level\?: "high" \| "medium" \| "low" \| string/);
  assert.match(reportSource, /report\.credibility_summary/);
  assert.match(reportSource, /credibility_level/);
  assert.match(reportSource, /fallback_rate/);
  assert.match(reportSource, /evidence_span_miss_rate/);
  assert.match(reportSource, /contract_no_rate/);
  assert.match(reportSource, /信号充分|部分信号不足|信号不足/);
});
