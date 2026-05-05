const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("avatar state maps voice room phases to digital human states", () => {
  const source = read("src/lib/avatar/state.ts");

  assert.match(source, /export type AvatarState/);
  assert.match(source, /mapVoicePhaseToAvatarState/);
  assert.match(source, /case "playing_question":\s*return "speaking"/);
  assert.match(source, /case "ready_to_record":\s*return "listening"/);
  assert.match(source, /case "recording":\s*return "listening_active"/);
  assert.match(source, /case "uploading":\s*return "thinking"/);
});

test("voice room renders the digital human stage", () => {
  const source = read("src/components/interview/VoiceRoom.tsx");

  assert.match(source, /DigitalHumanStage/);
  assert.match(source, /phase={phase}/);
  assert.ok(source.includes("question={pendingQuestion?.content ?? null}"));
  assert.match(source, /cameraOn={cameraOn}/);
});

test("digital human stage exposes state and lightweight lip sync UI", () => {
  const source = read("src/components/interview/DigitalHumanStage.tsx");

  assert.match(source, /data-avatar-state/);
  assert.match(source, /mapVoicePhaseToAvatarState/);
  assert.match(source, /useLipSync/);
  assert.match(source, /mouthOpen/);
  assert.match(source, /speaking/);
  assert.match(source, /listening_active/);
  assert.match(source, /AI 面试官/);
  assert.match(source, /语音能量/);
});

test("lip sync hook samples the TTS audio element with WebAudio", () => {
  const source = read("src/lib/avatar/useLipSync.ts");

  assert.match(source, /WeakMap<HTMLAudioElement/);
  assert.match(source, /createMediaElementSource/);
  assert.match(source, /createAnalyser/);
  assert.match(source, /getByteFrequencyData/);
  assert.match(source, /requestAnimationFrame/);
});

test("avatar motion profile defines blink nod and gaze behaviour", () => {
  const source = read("src/lib/avatar/motion.ts");

  assert.match(source, /getAvatarMotionProfile/);
  assert.match(source, /blinkIntervalMs/);
  assert.match(source, /nodAmplitude/);
  assert.match(source, /gazeShift/);
});

test("voice room passes its TTS audio element to the digital human stage", () => {
  const source = read("src/components/interview/VoiceRoom.tsx");

  assert.match(source, /audioElementRef={audioElRef}/);
});

test("digital human stage uses blink nod and gaze motion profile", () => {
  const source = read("src/components/interview/DigitalHumanStage.tsx");

  assert.match(source, /getAvatarMotionProfile/);
  assert.match(source, /motionProfile/);
  assert.match(source, /blinkScale/);
  assert.match(source, /gazeShift/);
  assert.match(source, /视线动作/);
});
