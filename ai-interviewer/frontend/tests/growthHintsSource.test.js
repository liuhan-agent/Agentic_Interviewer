const assert = require("node:assert/strict");
const test = require("node:test");

const {
  buildGrowthHints,
} = require("../src/lib/sessionDelta.ts");

function entry(scores) {
  return { dimensionScores: scores };
}

test("buildGrowthHints returns null when history < 3 scored entries", () => {
  assert.equal(buildGrowthHints([], 7), null);
  assert.equal(
    buildGrowthHints([entry({ technical_depth: 6 })], 7),
    null,
  );
  assert.equal(
    buildGrowthHints(
      [entry({ technical_depth: 6 }), entry({ technical_depth: 5 })],
      7,
    ),
    null,
  );
});

test("buildGrowthHints surfaces persistently weak dim", () => {
  // History is most-recent-first; technical_depth is <7 in all three
  // sessions and not improving on the latest pair → persistent weak.
  // communication is at 8.2 most recently and rising, so it should
  // appear under consecutiveImprove (positive narrative wins).
  const out = buildGrowthHints(
    [
      entry({ technical_depth: 5.5, communication: 8.2 }),
      entry({ technical_depth: 6.0, communication: 7.5 }),
      entry({ technical_depth: 5.0, communication: 7.0 }),
    ],
    7,
  );
  assert.ok(out);
  const weakDims = out.persistentWeak.map((d) => d.dimension);
  assert.deepEqual(weakDims, ["technical_depth"]);
  const improveDims = out.consecutiveImprove.map((d) => d.dimension);
  assert.deepEqual(improveDims, ["communication"]);
});

test("buildGrowthHints surfaces consecutive improving dim", () => {
  const out = buildGrowthHints(
    [
      entry({ system_design: 8.0 }),
      entry({ system_design: 7.0 }),
      entry({ system_design: 6.0 }),
    ],
    7,
  );
  assert.ok(out);
  assert.equal(out.consecutiveImprove.length, 1);
  assert.equal(out.consecutiveImprove[0].dimension, "system_design");
  assert.equal(out.consecutiveImprove[0].delta, 1);
});

test("improving dim wins over persistent-weak when both qualify", () => {
  // Three entries, all <7, but the most recent two are climbing →
  // categorise as improving (positive narrative wins).
  const out = buildGrowthHints(
    [
      entry({ communication: 6.5 }),
      entry({ communication: 5.8 }),
      entry({ communication: 5.0 }),
    ],
    7,
  );
  assert.ok(out);
  assert.equal(out.consecutiveImprove.length, 1);
  assert.equal(out.consecutiveImprove[0].dimension, "communication");
  // Should NOT also list it as persistent weak — avoid contradictory tags.
  assert.equal(
    out.persistentWeak.find((d) => d.dimension === "communication"),
    undefined,
  );
});

test("buildGrowthHints caps each list at 3 entries", () => {
  const dims = ["a", "b", "c", "d", "e"];
  const make = (offset) =>
    entry(Object.fromEntries(dims.map((d) => [d, 5 + offset])));
  // History is most-recent-first; recent[0]=5, recent[1]=5.5, recent[2]=6
  // → not improving (last < prev), all <7 → persistent weak.
  const out = buildGrowthHints(
    [make(0), make(0.5), make(1.0)],
    7,
  );
  assert.ok(out);
  // All five dims qualify as persistent weak; cap should kick in.
  assert.ok(out.persistentWeak.length <= 3);
});
