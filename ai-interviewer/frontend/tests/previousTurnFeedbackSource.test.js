const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("PreviousTurnFeedback exposes three-tier verdict and accessibility hooks", () => {
  const source = read("src/components/interview/PreviousTurnFeedback.tsx");

  assert.match(source, /export function PreviousTurnFeedback/);
  // a11y: announce evaluation cards politely so screen readers don't interrupt
  // candidate's answer typing rhythm.
  assert.match(source, /aria-live="polite"/);
  assert.match(source, /role="status"/);

  // The three qualitative verdict tiers must all be wired through; we
  // intentionally avoid leaking the raw numeric score to the in-interview UI
  // (see #9 product spec) and rely on this categorical signal instead.
  assert.match(source, /"passed"/);
  assert.match(source, /"near"/);
  assert.match(source, /"needs_work"/);
});

test("PreviousTurnFeedback derives verdict from passed flag plus score threshold", () => {
  const source = read("src/components/interview/PreviousTurnFeedback.tsx");

  // The threshold (>= 4) draws the line between "near" and "needs_work";
  // change with care — the report layer also uses 4 as the weak-dimension
  // floor, and the in-interview language assumes the same calibration.
  assert.match(source, /evaluation\.passed/);
  assert.match(source, /evaluation\.score\s*>=\s*4/);
});

test("PreviousTurnFeedback never renders the raw numeric score in JSX", () => {
  const source = read("src/components/interview/PreviousTurnFeedback.tsx");

  // The card visualises strengths / weaknesses / verdict but must never
  // surface the raw score — quantifying mid-interview anchors candidates on
  // a number rather than the qualitative growth signal.
  assert.doesNotMatch(source, /\{evaluation\.score\}/);
  assert.doesNotMatch(source, /\{evaluation\.score\.toFixed/);
});

test("PollQuestionResponse types expose PreviousTurnEvaluation contract", () => {
  const types = read("src/lib/api/types.ts");

  assert.match(types, /export interface PreviousTurnEvaluation/);
  // Backend caps strengths / weaknesses to 2 in
  // ``_extract_last_turn_evaluation``; the wire shape stays generic
  // (``string[]``) so future changes to the cap don't ripple into the type.
  assert.match(types, /strengths:\s*string\[\]/);
  assert.match(types, /weaknesses:\s*string\[\]/);
  assert.match(types, /rubric_coverage:\s*Record<string,\s*string>/);
  assert.match(
    types,
    /previous_turn_evaluation\?:\s*PreviousTurnEvaluation\s*\|\s*null/,
  );
});

test("useQuestionPoller pipes previousEvaluation through QUESTION action only", () => {
  const source = read("src/lib/hooks/useQuestionPoller.ts");

  // The state shape carries previousEvaluation so InterviewRoom can render
  // the card alongside the next question without a second round-trip.
  assert.match(source, /previousEvaluation:\s*PreviousTurnEvaluation\s*\|\s*null/);
  // The QUESTION action must thread the field through; SUBMITTING / START /
  // terminal frames intentionally don't, so that the last-shown card stays
  // visible while the next question is being prepared.
  assert.match(source, /res\.previous_turn_evaluation\s*\?\?\s*null/);
});

test("InterviewRoom mounts PreviousTurnFeedback only while waiting for an answer", () => {
  const source = read("src/components/interview/InterviewRoom.tsx");

  assert.match(
    source,
    /import \{ PreviousTurnFeedback \} from "@\/components\/interview\/PreviousTurnFeedback"/,
  );
  // The card is gated on both the waiting phase and a non-null evaluation —
  // showing it on terminal phases (completed / cancelled / error) would
  // confuse candidates because the loop is over.
  assert.match(
    source,
    /state\.phase === "waiting_for_answer" && state\.previousEvaluation/,
  );
  assert.match(source, /<PreviousTurnFeedback/);
});
