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
