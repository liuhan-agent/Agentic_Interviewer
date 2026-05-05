const assert = require("node:assert/strict");
const test = require("node:test");

const {
  buildLastSessionDelta,
} = require("../src/lib/sessionDelta.ts");

test("buildLastSessionDelta returns null when there is no previous session", () => {
  assert.equal(buildLastSessionDelta({ overallScore: 7.5 }, null), null);
});

test("buildLastSessionDelta returns overall delta when previous has only an overall score", () => {
  const delta = buildLastSessionDelta(
    { overallScore: 7.5 },
    { overallScore: 7.0 },
  );
  assert.ok(delta);
  assert.equal(delta.overall, 0.5);
  assert.deepEqual(delta.dimensions, []);
});

test("buildLastSessionDelta returns dimension deltas sorted by absolute movement", () => {
  const delta = buildLastSessionDelta(
    {
      overallScore: 7.8,
      dimensionScores: {
        technical_depth: 8.2,
        communication: 6.0,
        system_design: 7.0,
      },
    },
    {
      overallScore: 7.0,
      dimensionScores: {
        technical_depth: 7.0,
        communication: 7.5,
        system_design: 7.0,
      },
    },
  );
  assert.ok(delta);
  assert.equal(delta.overall, 0.8);
  // Sorted by absolute movement: |communication=-1.5| > |technical_depth=+1.2|
  // > |system_design=0|, so communication comes first even when it
  // dropped (regressions are part of the signal).
  assert.equal(delta.dimensions[0].dimension, "communication");
  assert.equal(delta.dimensions[0].delta, -1.5);
  assert.equal(delta.dimensions[1].dimension, "technical_depth");
  assert.equal(delta.dimensions[1].delta, 1.2);
});

test("buildLastSessionDelta returns null when there is no overall and no shared dimension", () => {
  const delta = buildLastSessionDelta(
    { dimensionScores: { only_now: 7.0 } },
    { dimensionScores: { only_then: 6.0 } },
  );
  assert.equal(delta, null);
});

test("buildLastSessionDelta omits overall when current overall is missing", () => {
  const delta = buildLastSessionDelta(
    {
      dimensionScores: { technical_depth: 8.0 },
    },
    {
      overallScore: 7.0,
      dimensionScores: { technical_depth: 7.0 },
    },
  );
  assert.ok(delta);
  assert.equal(delta.overall, null);
  assert.equal(delta.dimensions.length, 1);
  assert.equal(delta.dimensions[0].delta, 1.0);
});

test("buildLastSessionDelta caps dimension deltas at 3 entries", () => {
  const dims = (offset) =>
    Object.fromEntries(
      Array.from({ length: 6 }, (_, i) => [
        `dim_${i}`,
        Number((5 + offset + i * 0.4).toFixed(1)),
      ]),
    );
  const delta = buildLastSessionDelta(
    { overallScore: 7.0, dimensionScores: dims(1.0) },
    { overallScore: 6.0, dimensionScores: dims(0) },
  );
  assert.ok(delta);
  assert.equal(delta.dimensions.length, 3);
});
