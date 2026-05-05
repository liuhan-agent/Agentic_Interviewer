const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("buildWeakPracticeHref keeps length=short for the practice loop", () => {
  const source = read("src/components/interview/ReportView.tsx");

  // ``length=short`` is the product calibration for the practice loop —
  // we deliberately do *not* book a full ``deep`` run because the goal
  // is rapid iteration on weak dimensions, not a fresh full interview.
  // Guard against accidental flips during refactor.
  assert.match(source, /function buildWeakPracticeHref/);
  assert.match(source, /params\.set\("length",\s*"short"\)/);
});

test("TrainingPlanCard accepts weakPracticeHref prop and renders gated", () => {
  const source = read("src/components/interview/ReportView.tsx");

  // The training plan card surfaces the CTA inline so candidates do not
  // have to scroll to the page-bottom Actions block to act on the
  // diagnosis they just read.
  assert.match(source, /weakPracticeHref\?:\s*string\s*\|\s*null/);
  // The CTA must be gated on a truthy href; for first-perfect interviews
  // (no weak dimensions) the helper returns ``null`` and the button
  // should disappear instead of pointing to ``/interview/setup`` with no
  // focus query.
  assert.match(source, /weakPracticeHref\s*&&/);
});

test("TrainingPlanCard CTA copy and Link wiring", () => {
  const source = read("src/components/interview/ReportView.tsx");

  // Localised CTA copy ("针对本次弱项再来一场" or close variant) so the
  // user sees the practice intent in their own language.
  assert.match(source, /针对本次弱项/);
  // Use Next.js ``<Link>`` (not raw <a>) for client-side navigation so
  // the app shell + scroll position survive.
  assert.match(source, /<Link\s+href=\{weakPracticeHref\}/);
});

test("Report frame threads weakPracticeHref into TrainingPlanCard once", () => {
  const source = read("src/components/interview/ReportView.tsx");

  // The href is computed once at the report frame and shared between
  // Actions (page bottom) and TrainingPlanCard (in-card CTA). Avoids
  // the maintenance trap of two divergent recomputations.
  assert.match(
    source,
    /<TrainingPlanCard[\s\S]{0,80}?weakPracticeHref=\{/,
  );
});
