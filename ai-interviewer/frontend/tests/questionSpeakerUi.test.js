const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const interviewRoomPath = path.join(
  __dirname,
  "..",
  "src",
  "components",
  "interview",
  "InterviewRoom.tsx",
);
const textInterviewPagePath = path.join(
  __dirname,
  "..",
  "src",
  "app",
  "interview",
  "[sessionId]",
  "page.tsx",
);
const voiceInterviewPagePath = path.join(
  __dirname,
  "..",
  "src",
  "app",
  "interview",
  "[sessionId]",
  "voice",
  "page.tsx",
);

function readInterviewRoom() {
  return fs.readFileSync(interviewRoomPath, "utf8");
}

function readTextInterviewPage() {
  return fs.readFileSync(textInterviewPagePath, "utf8");
}

function readVoiceInterviewPage() {
  return fs.readFileSync(voiceInterviewPagePath, "utf8");
}

test("text interview page exposes server-side question reading controls", () => {
  const source = readInterviewRoom();

  assert.match(source, /loadQuestionSpeechEnabled/);
  assert.match(source, /storeQuestionSpeechEnabled/);
  assert.match(source, /synthesizeQuestionAudio/);
  assert.match(source, /playQuestionAudio/);
  assert.match(source, /markQuestionAudioUnavailable/);
  assert.doesNotMatch(source, /fallbackToBrowserSpeech/);
  assert.doesNotMatch(source, /speakQuestion/);
  assert.doesNotMatch(source, /stopQuestionSpeech/);
  assert.doesNotMatch(source, /pauseQuestionSpeech/);
  assert.doesNotMatch(source, /resumeQuestionSpeech/);
  assert.match(source, /自动读题/);
  assert.match(source, /aria-label=\{questionSpeechLabel\.ariaLabel\}/);
});

test("question replay button supports replay pause and resume states", () => {
  const source = readInterviewRoom();

  assert.match(source, /questionSpeechState/);
  assert.match(source, /aria-label=\{questionSpeechLabel\.ariaLabel\}/);
  assert.match(source, /questionSpeechLabel\.text/);
  assert.match(source, /onPauseSpeaking/);
  assert.match(source, /onResumeSpeaking/);
  assert.match(source, /status === "paused"/);
  assert.match(source, /ariaLabel: "继续读题"/);
  assert.match(source, /text: "继续"/);
});

test("text interview page auto reads each new question only after opt-in", () => {
  const source = readInterviewRoom();

  assert.match(source, /readQuestions/);
  assert.match(source, /lastSpokenQuestionRef/);
  assert.match(source, /state\.phase !== "waiting_for_answer"/);
  assert.match(source, /void handleSpeakQuestion\(qText/);
  assert.match(source, /synthesizeQuestionAudio\(sessionId, text, turnIdx/);
});

test("server-side question audio is not blocked by browser speech support", () => {
  const source = readInterviewRoom();

  assert.doesNotMatch(
    source,
    /function handleToggleQuestionSpeech\(\) \{\s*if \(!questionSpeechSupported\)/s,
  );
  assert.match(source, /synthesizeQuestionAudio\(sessionId, text, turnIdx/);
});

test("current question replay uses poller turn index even when bubble history has none", () => {
  const source = readInterviewRoom();

  assert.match(source, /effectiveTurnIdx=/);
  assert.match(source, /\? state\.turnIdx\s*: t\.turnIdx/);
  assert.match(source, /onSpeak\(entry\.question, effectiveTurnIdx\)/);
});

test("failed server-side question audio clears stale audio before fallback", () => {
  const source = readInterviewRoom();

  assert.match(
    source,
    /audio\.onerror = \(\) => \{\s*if \(questionSpeechRunRef\.current === runId\) \{\s*markQuestionAudioUnavailable\(runId,/,
  );
  assert.match(source, /catch \{\s*stopQuestionAudio\(\);\s*return false;\s*\}/);
  assert.doesNotMatch(source, /fallbackToBrowserSpeech/);
});

test("voice answer entry lives near the answer input", () => {
  const pageSource = readTextInterviewPage();
  const roomSource = readInterviewRoom();

  assert.doesNotMatch(pageSource, /切换到语音/);
  assert.match(roomSource, /用语音回答/);
  assert.doesNotMatch(roomSource, /href=\{`\/interview\/\$\{sessionId\}\/voice`\}/);
  assert.match(roomSource, /setVoiceToolsOpen/);
  assert.match(roomSource, /<VoiceAnswerPanel/);
});

test("legacy voice route renders InterviewRoom in voice input mode", () => {
  const source = readVoiceInterviewPage();

  assert.match(source, /import \{ InterviewRoom \}/);
  assert.match(source, /defaultAnswerMode="voice"/);
  assert.doesNotMatch(source, /import \{ VoiceRoom \}/);
  assert.doesNotMatch(source, /DigitalHumanStage/);
});

test("in-progress interview pages expose full session id with shared tooltip", () => {
  const roomSource = readInterviewRoom();
  const voiceSource = fs.readFileSync(
    path.join(
      __dirname,
      "..",
      "src",
      "components",
      "interview",
      "VoiceRoom.tsx",
    ),
    "utf8",
  );

  assert.match(roomSource, /import \{ SessionIdTooltip \}/);
  assert.match(roomSource, /<SessionIdTooltip sessionId=\{sessionId\} \/>/);
  assert.match(voiceSource, /import \{ SessionIdTooltip \}/);
  assert.match(voiceSource, /<SessionIdTooltip sessionId=\{sessionId\} \/>/);
});
