const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const videoTypes = fs.readFileSync(
  path.join(__dirname, "..", "src", "lib", "video", "types.ts"),
  "utf8",
);

test("video signal helpers expose runtime guard and weighted merge", () => {
  assert.match(videoTypes, /export function isAggregatedVideoSignal/);
  assert.match(videoTypes, /export function mergeAggregatedVideoSignals/);
  assert.match(videoTypes, /totalSamples/);
  assert.match(videoTypes, /emotionCounts/);
  assert.match(videoTypes, /sample_count/);
});

test("face capture hook exposes safe whole-interview lifecycle controls", () => {
  const hookSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "hooks", "useFaceCapture.ts"),
    "utf8",
  );

  assert.match(hookSource, /startCamera: \(\) => Promise<boolean>/);
  assert.match(hookSource, /releaseCamera: \(\) => void/);
  assert.match(hookSource, /startCapture: \(\) => void/);
  assert.match(hookSource, /stopCapture: \(\) => AggregatedVideoSignal \| null/);
  assert.match(hookSource, /resetCapture: \(\) => void/);
  assert.match(hookSource, /clearInterval/);
  assert.match(hookSource, /catch/);
  assert.doesNotMatch(hookSource, /throw /);
});

test("turn video capture hook scopes camera signals to the active question", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "hooks", "useTurnVideoCapture.ts"),
    "utf8",
  );

  assert.match(source, /export function useTurnVideoCapture/);
  assert.match(source, /enableVideoAnalysis/);
  assert.match(source, /turnIdx/);
  assert.match(source, /paused/);
  assert.match(source, /startCamera/);
  assert.match(source, /releaseCamera/);
  assert.match(source, /startCapture/);
  assert.match(source, /finishTurnCapture/);
  assert.match(source, /clearTurnCapture/);
  assert.match(source, /resetCapture/);
});
