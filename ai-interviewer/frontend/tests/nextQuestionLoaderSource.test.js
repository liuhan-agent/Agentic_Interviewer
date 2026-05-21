const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("NextQuestionLoader exposes ARIA progressbar role with aria-valuenow", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  assert.match(source, /role="progressbar"/);
  assert.match(source, /aria-valuemin=\{0\}/);
  assert.match(source, /aria-valuemax=\{100\}/);
  assert.match(source, /aria-valuenow=/);
});

test("NextQuestionLoader caps progress at 95% to avoid the false-completion trap", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  assert.match(source, /0\.95/);
  assert.match(source, /Math\.min\(/);
});

test("NextQuestionLoader cleans up its interval on unmount", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  assert.match(source, /setInterval\(/);
  assert.match(source, /clearInterval\(/);
});

test("NextQuestionLoader uses a 100000ms fallback when etaMs is missing", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  assert.match(source, /const FALLBACK_ETA_MS = 100_000/);
  assert.doesNotMatch(source, /const FALLBACK_ETA_MS = 45000/);
  assert.doesNotMatch(source, /const FALLBACK_ETA_MS = 45_000/);
});

test("NextQuestionLoader maps elapsed time to a non-linear waiting rhythm", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  assert.match(source, /WAITING_PROGRESS_POINTS/);
  assert.match(source, /timeMs: 10_000,\s*progress: 0\.1/);
  assert.match(source, /timeMs: 45_000,\s*progress: 0\.52/);
  assert.match(source, /timeMs: 80_000,\s*progress: 0\.86/);
  assert.match(source, /timeMs: 100_000,\s*progress: 0\.94/);
  assert.match(source, /timeMs: 110_000,\s*progress: PROGRESS_CAP/);
  assert.match(source, /getQuestionPreparationProgress/);
  assert.match(source, /lerpProgress/);
});

test("NextQuestionLoader keeps the waiting headline without a duplicate current-stage row", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  assert.match(source, /QUESTION_STAGE_HEADLINES/);
  assert.match(source, /thresholdMs: 12_000,\s*text: "正在整理你的回答"/);
  assert.match(source, /thresholdMs: 35_000,\s*text: "正在梳理关键信息"/);
  assert.match(source, /thresholdMs: 65_000,\s*text: "正在提炼本轮考察点"/);
  assert.match(source, /thresholdMs: 90_000,\s*text: "正在组织下一题"/);
  assert.match(source, /thresholdMs: 110_000,\s*text: "正在检查问题表达"/);
  assert.match(source, /复杂回答需要多一点时间，仍在生成中/);
  assert.match(source, /getWaitingHeadline/);
  assert.match(source, /正在组织下一题/);
  assert.doesNotMatch(source, /QUESTION_PREPARATION_STAGES/);
  assert.doesNotMatch(source, /当前阶段/);
  assert.doesNotMatch(source, /getWaitingStageLabel/);
});

test("NextQuestionLoader shows stable answer insight without fragile keywords", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  assert.match(source, /answerInsight\?: AnswerInsight \| null/);
  assert.match(source, /answerInsight = null/);
  assert.match(source, /dimensionId\?: string \| null/);
  assert.match(source, /dimensionLabel\?: string \| null/);
  assert.match(source, /isOpeningTurn\?: boolean/);
  assert.doesNotMatch(source, /keywords: string\[\]/);
  assert.doesNotMatch(source, /answerPreview/);
});

test("NextQuestionLoader uses opening-intro copy instead of question-dimension copy", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  assert.match(source, /const isOpeningTurn = Boolean\(answerInsight\?\.isOpeningTurn\)/);
  assert.match(source, /OPENING_STAGE_HEADLINES/);
  assert.match(source, /tipScope = isFinalTurn[\s\S]*"self_intro"/);
});

test("NextQuestionLoader keeps answer insight visible while final summary is generated", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  assert.match(source, /const showAnswerInsight = Boolean\(/);
  assert.doesNotMatch(source, /!isFinalTurn\s*&&\s*Boolean/);
});

test("NextQuestionLoader renders backend waiting tips with a 10s local rotation", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  assert.match(source, /import type \{ InterviewWaitingTip \}/);
  assert.match(source, /waitingTips\?: InterviewWaitingTip\[\] \| null/);
  assert.match(source, /tipRotationIntervalMs\?: number/);
  assert.match(source, /const WAITING_TIP_ROTATION_MS = 10000/);
  assert.match(source, /selectNextWaitingTip/);
  assert.match(source, /displayedTipIds\?: ReadonlySet<string>/);
  assert.match(source, /onWaitingTipShown\?: \(tipId: string\) => void/);
  assert.match(source, /setInterval\(showNextTip, effectiveTipRotationMs\)/);
  assert.match(source, /面试小贴士/);
  assert.doesNotMatch(source, /处理状态/);
});

test("NextQuestionLoader selects tips by scope with default fallback and no pre-exhaustion repeats", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  assert.match(source, /tips\.filter\(\(tip\) => tip\.scope === scope\)/);
  assert.match(source, /tips\.filter\(\(tip\) => tip\.scope === "default"\)/);
  assert.match(source, /\[\.\.\.scoped, \.\.\.defaultTips\]/);
  assert.match(source, /scope === "default"/);
  assert.match(source, /FALLBACK_WAITING_TIPS/);
  assert.match(source, /!displayedTipIds\?\.has\(tip\.id\)/);
  assert.match(source, /unused\.length > 0 \? unused : candidates/);
  assert.match(source, /currentTipId\?: string \| null/);
  assert.match(source, /tip\.id !== currentTipId/);
  assert.match(source, /available\.find\(\(tip\) => tip\.id !== currentTipId\)/);
});

test("InterviewRoom delegates loading state to NextQuestionLoader with etaMs", () => {
  const source = read("src/components/interview/InterviewRoom.tsx");

  assert.match(
    source,
    /NextQuestionLoader[\s\S]*from "@\/components\/interview\/NextQuestionLoader"/,
  );
  assert.match(source, /<NextQuestionLoader\s+etaMs=\{state\.lastServerLatencyMs\}/);
  assert.match(source, /answerInsight=\{latestSubmittedAnswerInsight\}/);
  assert.match(source, /waitingTips=\{waitingTipsResponse\?\.tips \?\? null\}/);
  assert.match(source, /tipRotationIntervalMs=\{waitingTipsResponse\?\.rotation_interval_ms\}/);
});

test("NextQuestionLoader has final-turn copy that does not promise another question", () => {
  const source = read("src/components/interview/NextQuestionLoader.tsx");

  assert.match(source, /FINAL_STAGE_HEADLINES/);
  assert.match(source, /isFinalTurn/);
});
