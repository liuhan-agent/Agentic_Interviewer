const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

test("voice client uses one-time ticket auth and flushes on tts_end", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "voice", "client.ts"),
    "utf8",
  );

  assert.match(source, /createVoiceTicket/);
  assert.match(source, /type: "auth"/);
  assert.match(source, /ticket:/);
  assert.doesNotMatch(source, /session_token/);
  assert.match(source, /case "tts_end":/);
  assert.match(source, /turn_idx: turnIdx/);
});

test("voice and text rooms expose reauth-required model settings entry", () => {
  const voiceRoom = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "VoiceRoom.tsx"),
    "utf8",
  );
  const interviewRoom = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "InterviewRoom.tsx"),
    "utf8",
  );

  assert.match(voiceRoom, /reauth_required/);
  assert.match(voiceRoom, /LLMSettingsDialog/);
  assert.match(interviewRoom, /isReauthRequired/);
  assert.match(interviewRoom, /LLMSettingsDialog/);
});

test("voice client drains blob reads before flushing audio", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "voice", "client.ts"),
    "utf8",
  );

  assert.match(source, /pendingBlobReads/);
  assert.match(source, /drainPendingBlobReads/);
  assert.match(source, /await this\.drainPendingBlobReads\(\)/);
});

test("voice room guards reconnects and recording length", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "VoiceRoom.tsx"),
    "utf8",
  );

  assert.match(source, /MAX_RECORD_SECONDS/);
  assert.match(source, /RECORD_WARNING_SECONDS/);
  assert.match(source, /safeReconnect/);
  assert.match(source, /clientRef\.current\?\.close\(\)/);
  assert.match(source, /仅在本地提取/);
});
