const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("scores constants module exports the weak / strong thresholds", () => {
  const constants = read("src/lib/constants/scores.ts");

  assert.match(constants, /export const WEAK_DIMENSION_THRESHOLD = 7;/);
  assert.match(constants, /export const STRONG_DIMENSION_THRESHOLD = 8\.5;/);
});

test("ProgressChart pulls the threshold from the shared constants module", () => {
  const source = read("src/components/interview/ProgressChart.tsx");

  assert.match(
    source,
    /import \{ WEAK_DIMENSION_THRESHOLD \} from "@\/lib\/constants\/scores";/,
  );
  // The legacy literal must not coexist with the import — that's the
  // whole point of audit F5 (single source of truth).
  assert.doesNotMatch(source, /score >= 7/);
  assert.match(source, /score >= WEAK_DIMENSION_THRESHOLD/);
});

test("ProgressChart still uses Math.abs(delta) for trend ranking", () => {
  // Trend ranking is a *different* signal from absolute weakness;
  // this test guards against future refactors collapsing them.
  const sessionDelta = read("src/lib/sessionDelta.ts");
  assert.match(sessionDelta, /Math\.abs\(b\.delta\) - Math\.abs\(a\.delta\)/);
});

test("sessionDelta imports the weak threshold instead of redefining it", () => {
  const sessionDelta = read("src/lib/sessionDelta.ts");

  assert.match(
    sessionDelta,
    /import \{ WEAK_DIMENSION_THRESHOLD \} from "\.\/constants\/scores\.ts";/,
  );
  assert.doesNotMatch(sessionDelta, /WEAK_THRESHOLD_DEFAULT\s*=\s*7/);
  assert.match(
    sessionDelta,
    /weakThreshold: number = WEAK_DIMENSION_THRESHOLD/,
  );
});
