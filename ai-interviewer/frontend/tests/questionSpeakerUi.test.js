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

function readInterviewRoom() {
  return fs.readFileSync(interviewRoomPath, "utf8");
}

function readTextInterviewPage() {
  return fs.readFileSync(textInterviewPagePath, "utf8");
}

test("text interview page exposes browser-side question reading controls", () => {
  const source = readInterviewRoom();

  assert.match(source, /loadQuestionSpeechEnabled/);
  assert.match(source, /storeQuestionSpeechEnabled/);
  assert.match(source, /speakQuestion/);
  assert.match(source, /stopQuestionSpeech/);
  assert.match(source, /自动读题/);
  assert.match(source, /aria-label="重播本题"/);
});

test("text interview page auto reads each new question only after opt-in", () => {
  const source = readInterviewRoom();

  assert.match(source, /readQuestions/);
  assert.match(source, /lastSpokenQuestionRef/);
  assert.match(source, /state\.phase !== "waiting_for_answer"/);
  assert.match(source, /speakQuestion\(qText\)/);
});

test("voice answer entry lives near the answer input", () => {
  const pageSource = readTextInterviewPage();
  const roomSource = readInterviewRoom();

  assert.doesNotMatch(pageSource, /切换到语音/);
  assert.match(roomSource, /用语音回答/);
  assert.ok(roomSource.includes("href={`/interview/${sessionId}/voice`}"));
});
