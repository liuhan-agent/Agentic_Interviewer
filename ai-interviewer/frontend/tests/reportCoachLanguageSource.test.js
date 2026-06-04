const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

// The interview pipeline IS the core product business; "成长规划 / 多维度反馈"
// is the downstream output, not a replacement. These tests guard the report
// surface against招聘官式 (B-end recruiter) phrasing while keeping
// 面试 / 评分 / 报告 as primary terminology.

test("report view keeps interview-first card titles", () => {
  const source = read("src/components/interview/ReportView.tsx");

  assert.match(source, /text-2xl">面试报告</);
  assert.match(source, /text-base">面试质量中心</);
  assert.match(source, /text-base">评分维度</);
  assert.match(source, /复盘训练计划/);
  assert.doesNotMatch(source, /教练培训计划/);
  // The "评分检查项" label appears both in a metric description and as
  // a JSX section title, so we just assert the string is present.
  assert.match(source, /评分检查项/);
});

test("report view drops招聘官式 phrasing while keeping 面试 / 评分 anchors", () => {
  const source = read("src/components/interview/ReportView.tsx");

  // Recruiter / hiring-decision wording must not leak into the report
  // surface. "综合评估" 是一个典型 B 端打分官话术；改成更直接的"反馈"。
  assert.doesNotMatch(source, /多维度综合评估/);
  // "评估候选人" 是 to-B HR SaaS 视角，不应该出现在 C 端文案。
  assert.doesNotMatch(source, /评估候选人/);
});

test("report description leans on multi-dimension feedback rather than hiring verdicts", () => {
  const source = read("src/components/interview/ReportView.tsx");

  assert.match(source, /追问、评分与复盘结果/);
});

test("verdict legacy mapping stays intact for old data", () => {
  // Verdict legacy values must remain mapped — they unblock older
  // database rows that still carry hire-language verdicts. Removing
  // them would render existing reports blank.
  const source = read("src/lib/constants/verdicts.ts");

  assert.match(source, /strong_hire/);
  assert.match(source, /no_hire/);
  assert.match(source, /表现优秀/);
  assert.match(source, /重点补齐/);
});

test("report page header keeps 面试官 + 多维度反馈 phrasing", () => {
  const source = read("src/app/interview/[sessionId]/report/page.tsx");

  // The report page is the canonical "面试报告" entry; we guard the
  // header against creeping back to either招聘官 ("综合评估") or
  // over-coach ("教练反馈").
  assert.match(source, /面试报告/);
  assert.match(source, /问镜/);
  assert.match(source, /多个维度给出了反馈和提升方向/);
  assert.doesNotMatch(source, /综合评估/);
  assert.doesNotMatch(source, /教练反馈/);
});
