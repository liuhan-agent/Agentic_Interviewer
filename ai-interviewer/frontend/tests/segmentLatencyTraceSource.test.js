const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("PollQuestionResponse exposes optional server_latency_ms (#11)", () => {
  const types = read("src/lib/api/types.ts");

  // The wire shape is optional + nullable so the frontend never has to
  // special-case its absence on older server builds. Backend tests
  // (test_segment_latency_api.py) assert the key is always present
  // once a session exists.
  assert.match(types, /server_latency_ms\?:\s*number\s*\|\s*null/);
});

test("useQuestionPoller threads server_latency_ms through QUESTION action only", () => {
  const source = read("src/lib/hooks/useQuestionPoller.ts");

  // ``lastServerLatencyMs`` lives on PollerState and is updated only on
  // a fresh QUESTION arrival. Terminal frames (completed / cancelled /
  // error) and the SUBMITTING transition deliberately preserve the
  // last-seen value so the InterviewRoom loading state can render the
  // ETA hint without flickering.
  assert.match(
    source,
    /lastServerLatencyMs:\s*number\s*\|\s*null/,
  );
  assert.match(source, /serverLatencyMs:\s*number\s*\|\s*null/);
  assert.match(source, /res\.server_latency_ms\s*\?\?\s*null/);
});

test("Initial poller state seeds lastServerLatencyMs as null", () => {
  const source = read("src/lib/hooks/useQuestionPoller.ts");

  // Defensive: the InterviewRoom must be safe to render before the
  // first poll returns. ``null`` lets the component skip the ETA hint
  // entirely on a brand-new session.
  assert.match(source, /lastServerLatencyMs:\s*null/);
});
