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
  assert.match(types, /source\?:\s*string\s*\|\s*null/);
  assert.match(types, /fallback_reason\?:\s*string\s*\|\s*null/);
  assert.match(types, /system_warnings\?:\s*string\[\]/);
  assert.match(types, /rubric_coverage\?:\s*Record<string,\s*unknown>/);
  assert.match(
    types,
    /previous_turn_evaluation\?:\s*PreviousTurnEvaluation\s*\|\s*null/,
  );
});

test("ResumeResponse exposes prior turns so continue interview can restore context", () => {
  const types = read("src/lib/api/types.ts");

  assert.match(types, /export interface ResumeHistoryTurn/);
  assert.match(types, /history\?:\s*ResumeHistoryTurn\[\]/);
  assert.match(
    types,
    /previous_turn_evaluation\?:\s*PreviousTurnEvaluation\s*\|\s*null/,
  );
});

test("useQuestionPoller clears previousEvaluation while a submitted answer is loading", () => {
  const source = read("src/lib/hooks/useQuestionPoller.ts");

  // The state shape carries previousEvaluation so InterviewRoom can render
  // the card alongside the next question without a second round-trip.
  assert.match(source, /previousEvaluation:\s*PreviousTurnEvaluation\s*\|\s*null/);
  // The QUESTION action must thread the field through; SUBMITTING must clear
  // stale feedback so the previous turn's card cannot stick to the answer
  // that was just submitted while the next question is being prepared.
  assert.match(source, /res\.previous_turn_evaluation\s*\?\?\s*null/);
  assert.match(source, /case "SUBMITTING":[\s\S]*previousEvaluation:\s*null/);
  assert.doesNotMatch(source, /last-shown card stays[\s\S]*visible while the next question/);
});

test("useQuestionPoller restores prior turns from resume response", () => {
  const source = read("src/lib/hooks/useQuestionPoller.ts");

  assert.match(source, /restoredHistory:\s*ResumeHistoryTurn\[\]/);
  assert.match(source, /history:\s*r\.history\s*\?\?\s*\[\]/);
});

test("InterviewRoom attaches previous turn feedback to the matching answered bubble only", () => {
  const source = read("src/components/interview/InterviewRoom.tsx");

  assert.doesNotMatch(source, /<PreviousTurnFeedback/);
  // The card is gated on both the waiting phase and a non-null evaluation —
  // showing it on terminal phases (completed / cancelled / error) would
  // confuse candidates because the loop is over.
  assert.match(source, /qaEntryMatchesEvaluation\(entry, evaluation\)/);
  assert.match(source, /entry\.answer === null/);
  assert.match(source, /!evaluation\.dimension\s*\|\|\s*!entry\.dimension/);
  assert.match(source, /evaluation\.dimension[\s\S]*entry\.dimension/);
  assert.match(source, /evaluation\.dimension !== entry\.dimension/);
  assert.match(source, /function hasDisplayableTurnFeedback/);
  assert.match(source, /hasDisplayableTurnFeedback\(entry\.evaluation\)/);
  assert.match(source, /<TurnFeedbackSummary evaluation=\{entry\.evaluation\}/);
});

test("InterviewRoom renders evaluator fallback as a system notice", () => {
  const source = read("src/components/interview/InterviewRoom.tsx");

  assert.match(source, /function isFallbackTurnEvaluation/);
  assert.match(source, /fallback_reason/);
  assert.match(source, /评估暂不可用/);
  assert.match(source, /本轮回答已保存/);
  assert.match(source, /不作为能力短板判断/);
});

test("InterviewRoom clears stale feedback when marking the current answer submitted", () => {
  const source = read("src/components/interview/InterviewRoom.tsx");

  assert.match(source, /next\[next\.length - 1\]\s*=\s*\{[\s\S]*answer:\s*text[\s\S]*evaluation:\s*undefined/);
});

test("InterviewRoom hides latest answer feedback while next question is loading", () => {
  const source = read("src/components/interview/InterviewRoom.tsx");

  assert.match(
    source,
    /showTurnFeedback=\{\s*!\(\s*state\.phase === "loading" &&\s*idx === history\.length - 1\s*\)\s*\}/,
  );
  assert.match(source, /showTurnFeedback:\s*boolean/);
  assert.match(
    source,
    /showTurnFeedback\s*&&\s*entry\.answer !== null\s*&&\s*hasDisplayableTurnFeedback\(entry\.evaluation\)/,
  );
});

test("InterviewRoom renders restored QA history with per-turn feedback", () => {
  const source = read("src/components/interview/InterviewRoom.tsx");

  assert.match(source, /state\.restoredHistory/);
  assert.match(source, /restoredTurnToQaEntry/);
  assert.match(source, /entry\.evaluation/);
  assert.match(source, /function TurnFeedbackSummary/);
});

test("InterviewRoom treats resumed current-question numbering as canonical", () => {
  const source = read("src/components/interview/InterviewRoom.tsx");

  assert.match(source, /displayTurnIdx\?:\s*number\s*\|\s*null/);
  assert.match(
    source,
    /filterRestoredHistoryForCurrentQuestion\(\s*restored,\s*currentTurnIdxForDisplay,\s*\)/,
  );
  assert.match(source, /entryTurnIdx\s*<\s*currentTurnIdxForDisplay/);
  assert.match(source, /displayTurnIdx:\s*currentTurnIdxForDisplay/);
  assert.doesNotMatch(source, /resolveCurrentDisplayTurnIdx/);
  assert.doesNotMatch(source, /Math\.min\(nextDisplayTurnIdx,\s*maxTurns - 1\)/);
  assert.match(source, /entry\.displayTurnIdx/);
});

test("InterviewRoom shows prominent turn labels and user-facing dimension labels", () => {
  const source = read("src/components/interview/InterviewRoom.tsx");

  assert.match(source, /formatDimensionName\(entry\.dimension\)/);
  assert.match(source, /formatDimensionName.*@\/lib\/constants\/interview/s);
  assert.match(source, /第 \$\{turnLabel\} 题/);
  assert.match(source, /min-w-\[4\.5rem\]/);
  assert.match(source, /text-emerald-200/);
});
