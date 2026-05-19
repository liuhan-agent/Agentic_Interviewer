const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const replaySource = fs.readFileSync(
  path.join(__dirname, "..", "src", "components", "interview", "ReplayView.tsx"),
  "utf8",
);
const apiTypesSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "lib", "api", "types.ts"),
  "utf8",
);

test("Replay API types expose display followup reason on replay turns", () => {
  assert.match(apiTypesSource, /export interface ReplayFollowupReason/);
  assert.match(apiTypesSource, /title:\s*string/);
  assert.match(apiTypesSource, /summary:\s*string/);
  assert.match(apiTypesSource, /chips:\s*string\[\]/);
  assert.match(apiTypesSource, /source:\s*"evaluator"/);
  assert.match(
    apiTypesSource,
    /followup_reason\?:\s*ReplayFollowupReason\s*\|\s*null/,
  );
});

test("ReplayView renders followup reason inside the scoring rationale block", () => {
  assert.match(replaySource, /function ScoringRationaleBlock/);
  assert.match(
    replaySource,
    /<ScoringRationaleBlock\s+rationale=\{turn\.rationale\}\s+followupReason=\{turn\.followup_reason\}/,
  );
  assert.match(replaySource, /followupReason\.title/);
  assert.match(replaySource, /followupReason\.summary/);
  assert.match(replaySource, /followupReason\.chips\.map/);
});

test("ReplayView does not expose internal evaluator followup fields", () => {
  assert.doesNotMatch(
    replaySource,
    /recommended_next_plan|recommended_probe_intent|failure_reason/,
  );
});
