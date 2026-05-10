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

test("voice client can authenticate in asr-only mode", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "voice", "client.ts"),
    "utf8",
  );

  assert.match(source, /VoiceClientMode/);
  assert.match(source, /mode\?: VoiceClientMode/);
  assert.match(source, /auth\.mode = this\.options\.mode/);
  assert.match(source, /"asr_only"/);
});

test("InterviewRoom voice answer panel uses ASR-only client and appends into the shared draft", () => {
  const roomSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "InterviewRoom.tsx"),
    "utf8",
  );
  const panelSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "VoiceAnswerPanel.tsx"),
    "utf8",
  );

  assert.match(roomSource, /<VoiceAnswerPanel/);
  assert.match(roomSource, /handleVoiceTranscript/);
  assert.match(roomSource, /answerInputRef/);
  assert.match(roomSource, /answerSelectionRef/);
  assert.match(roomSource, /updateAnswerSelection/);
  assert.match(roomSource, /insertTranscriptAtSelection/);
  assert.match(roomSource, /lastVoiceInsertRef/);
  assert.match(roomSource, /handleUndoVoiceTranscript/);
  assert.match(roomSource, /removeLastVoiceInsert/);
  assert.match(roomSource, /setSelectionRange/);
  assert.match(roomSource, /setDraft\(\(current\)/);
  assert.doesNotMatch(roomSource, />\s*文本\s*</);
  assert.match(panelSource, /function VoiceAnswerPanel/);
  assert.match(panelSource, /new VoiceClient\([\s\S]*mode: "asr_only"/);
  assert.match(panelSource, /onTranscript\(draft\.content/);
  assert.match(panelSource, /已追加到草稿，可继续编辑/);
  assert.match(panelSource, /语音回答/);
  assert.match(panelSource, /撤回上次语音/);
  assert.match(panelSource, /onUndoTranscript/);
  assert.doesNotMatch(panelSource, /语音补充/);
  assert.doesNotMatch(panelSource, /重新录制/);
  assert.doesNotMatch(panelSource, /继续回答\/录音/);
  assert.doesNotMatch(panelSource, /handleContinueRecording/);
  assert.doesNotMatch(panelSource, /确认并提交回答/);
  assert.doesNotMatch(panelSource, /await onSubmit\(content\)/);
  assert.doesNotMatch(panelSource, /submitTranscript\(/);
});

test("voice answer panel ignores stale websocket callbacks from StrictMode cleanup", () => {
  const panelSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "VoiceAnswerPanel.tsx"),
    "utf8",
  );

  assert.match(panelSource, /connectionRunRef/);
  assert.match(panelSource, /window\.setTimeout/);
  assert.match(panelSource, /if \(!isCurrentConnection\(runId\)\) return/);
  assert.match(panelSource, /window\.clearTimeout\(connectTimer\)/);
});

test("voice answer panel treats empty transcription as retryable notice", () => {
  const panelSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "VoiceAnswerPanel.tsx"),
    "utf8",
  );

  const emptyBranch =
    panelSource.match(/if \(event\.error === "empty_transcription"\) \{[\s\S]*?return;\n            \}/)?.[0] ?? "";

  assert.match(emptyBranch, /setNoticeMsg/);
  assert.match(emptyBranch, /这段没有识别到文字/);
  assert.match(emptyBranch, /setPhase\("ready"\)/);
  assert.doesNotMatch(emptyBranch, /setErrorMsg\(event\.message/);
  assert.doesNotMatch(emptyBranch, /setPhase\("error"\)/);
  assert.doesNotMatch(emptyBranch, /event\.message/);
  assert.match(panelSource, /border-amber-500\/30/);
  assert.match(panelSource, /text-amber-200/);
});

test("voice stop frame carries recorder MIME type for backend ASR routing", () => {
  const roomSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "VoiceRoom.tsx"),
    "utf8",
  );
  const clientSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "voice", "client.ts"),
    "utf8",
  );

  assert.match(clientSource, /mimeType\?: string/);
  assert.match(clientSource, /payload\.mime_type = mimeType/);
  assert.match(roomSource, /full\.type \|\| recorder\.mimeType/);
  assert.match(roomSource, /sendStop\([\s\S]*recordingMimeType/);
});

test("voice room normalizes browser recording to wav before upload when possible", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "VoiceRoom.tsx"),
    "utf8",
  );

  assert.match(source, /normalizeRecordingForASR/);
  assert.match(source, /AudioContext/);
  assert.match(source, /audio\/wav/);
  assert.match(source, /encodeWav/);
});

test("voice room reviews editable transcript before submitting", () => {
  const roomSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "VoiceRoom.tsx"),
    "utf8",
  );
  const clientSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "voice", "client.ts"),
    "utf8",
  );

  assert.match(clientSource, /type: "draft_transcript"/);
  assert.match(clientSource, /submitTranscript/);
  assert.match(roomSource, /reviewing_transcript/);
  assert.match(roomSource, /transcriptDraft/);
  assert.match(roomSource, /setTranscriptDraft/);
  assert.match(roomSource, /handleConfirmTranscript/);
  assert.match(roomSource, /handleRerecordTranscript/);
  assert.match(roomSource, /确认提交/);
  assert.match(roomSource, /重新录制/);
});

test("voice room can continue recording and append transcript drafts", () => {
  const roomSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "VoiceRoom.tsx"),
    "utf8",
  );

  assert.match(roomSource, /handleContinueRecording/);
  assert.match(roomSource, /setTranscriptDraft\(\(prev\)/);
  assert.match(roomSource, /prev\.trim\(\)/);
  assert.match(roomSource, /onContinueRecording/);
  assert.match(roomSource, /继续/);
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
