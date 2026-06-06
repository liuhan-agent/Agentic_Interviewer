const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

function extractFunctionBlock(source, name) {
  const match = source.match(
    new RegExp(`export function ${name}[\\s\\S]*?(?=\\nexport function |\\nexport async function |\\nfunction |$)`),
  );
  assert.ok(match, `expected ${name} to exist`);
  return match[0];
}

test("session APIs send token header and answer turn index", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );

  assert.match(source, /"X-Session-Token"/);
  assert.match(source, /turn_idx: turnIdx/);
  assert.match(source, /getSessionToken\(sessionId\)/);
});

test("answer submission uses browser recovery and an idempotency key", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );
  const block = extractFunctionBlock(source, "submitAnswer");

  assert.match(block, /return withSessionRecovery\(sessionId/);
  assert.match(block, /"Idempotency-Key": idempotencyKey/);
  assert.match(source, /function answerIdempotencyKey/);
});

test("interview API exposes voice ticket creation", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );

  assert.match(source, /export function createVoiceTicket/);
  assert.match(source, /voice-ticket/);
  assert.match(source, /VoiceTicketResponse/);
});

test("resume parsing keeps a larger browser timeout than the backend LLM budget", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );

  assert.match(
    source,
    /export function parseResume[\s\S]*timeoutMs:\s*180_000/,
  );
});

test("interview API exposes async resume parse job calls", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );
  const types = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "types.ts"),
    "utf8",
  );

  assert.match(types, /export interface ResumeParseJobResponse/);
  assert.match(source, /export function createResumeParseJob/);
  assert.match(source, /export function getResumeParseJob/);
  assert.match(source, /\/resume\/parse-jobs/);
  assert.match(source, /timeoutMs:\s*45_000/);
});

test("interview API exposes question audio synthesis", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );
  const types = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "types.ts"),
    "utf8",
  );

  assert.match(types, /export interface QuestionAudioRequest/);
  assert.match(source, /export async function synthesizeQuestionAudio/);
  assert.match(source, /question-audio/);
  assert.match(source, /turn_idx: turnIdx/);
  assert.match(source, /buildLLMPayload\(\)/);
  assert.match(source, /res\.blob\(\)/);
});

test("interview API exposes skip question call", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );
  const types = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "types.ts"),
    "utf8",
  );

  assert.match(types, /export interface SkipQuestionRequest/);
  assert.match(types, /export interface SkipQuestionResponse/);
  assert.match(source, /export function skipQuestion/);
  assert.match(source, /skip-question/);
  assert.match(source, /turn_idx: turnIdx/);
});

test("interview API exposes coach hint call", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );
  const types = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "types.ts"),
    "utf8",
  );

  assert.match(types, /export interface HintRequest/);
  assert.match(types, /export interface HintResponse/);
  assert.match(types, /source:\s*"contract"\s*\|\s*"target_skills"\s*\|\s*"resume_anchor"\s*\|\s*"fallback"\s*\|\s*"llm"/);
  assert.match(source, /export function requestHint/);
  assert.match(source, /\/hint/);
  assert.match(source, /turn_idx: turnIdx/);
  assert.match(source, /llm_config: llmConfig/);
});

test("interview API exposes waiting tips catalog", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );
  const types = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "types.ts"),
    "utf8",
  );

  assert.match(types, /export interface InterviewWaitingTip/);
  assert.match(types, /scope: string/);
  assert.match(types, /export interface InterviewWaitingTipsResponse/);
  assert.match(types, /rotation_interval_ms: number/);
  assert.match(source, /export function listInterviewWaitingTips/);
  assert.match(source, /\/waiting-tips/);
});

test("interview API exposes reauth-required detection", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );

  assert.match(source, /export function isReauthRequired/);
  assert.match(source, /reauth_required/);
  assert.match(source, /err instanceof ApiError/);
});

test("interview API exposes browser recovery flow", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );
  const types = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "types.ts"),
    "utf8",
  );

  assert.match(types, /export interface RecoverSessionResponse/);
  assert.match(types, /recovery_token/);
  assert.match(source, /export function recoverSession/);
  assert.match(source, /\/recover/);
  assert.match(source, /getRecoveryToken\(sessionId\)/);
  assert.match(source, /isRecoverableSessionAuthError\(err\)/);
  assert.match(source, /writeSessionToken\(sessionId/);
});

test("delete session uses browser recovery before giving up", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );

  assert.match(source, /function isRecoverableSessionAuthError/);
  assert.match(source, /err\.status === 401/);
  assert.match(source, /err\.status !== 403/);
  assert.match(source, /invalid session token/);
  assert.match(
    source,
    /export function deleteSession[\s\S]*return withSessionRecovery\(sessionId/,
  );
});

test("replay uses browser recovery before giving up", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );
  const block = extractFunctionBlock(source, "getReplay");

  assert.match(block, /\/replay/);
  assert.match(block, /return withSessionRecovery\(sessionId/);
});

test("interview API exposes session metadata for history backfill", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );
  const types = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "types.ts"),
    "utf8",
  );

  assert.match(types, /export interface SessionMetadataResponse/);
  assert.match(types, /created_at: string/);
  assert.match(types, /updated_at: string/);
  assert.match(source, /export function getSessionMetadata/);
  assert.match(source, /\/metadata/);
  assert.match(
    source,
    /export function getSessionMetadata[\s\S]*withSessionRecovery\(sessionId/,
  );
});

test("interview API exposes setup snapshot with session recovery", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );
  const types = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "types.ts"),
    "utf8",
  );

  assert.match(types, /export interface SessionSetupSnapshotResponse/);
  assert.match(types, /candidate: Candidate/);
  assert.match(types, /job_spec: JobSpec/);
  assert.match(source, /export function getSessionSetupSnapshot/);
  assert.match(source, /\/setup-snapshot/);
  assert.match(
    source,
    /export function getSessionSetupSnapshot[\s\S]*withSessionRecovery\(sessionId/,
  );
}
);

test("final report score types expose nullable scores and score status", () => {
  const types = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "types.ts"),
    "utf8",
  );

  assert.match(types, /export type RubricScoreStatus/);
  assert.match(types, /"scored"\s*\|\s*"not_evaluated"\s*\|\s*"skipped"\s*\|\s*"evaluator_unavailable"/);
  assert.match(types, /export type RubricCoverageStatus/);
  assert.match(types, /"passed"\s*\|\s*"below_threshold"\s*\|\s*"coverage_limited"\s*\|\s*"not_applicable"/);
  assert.match(types, /score:\s*number\s*\|\s*null/);
  assert.match(types, /score_status:\s*RubricScoreStatus/);
  assert.match(types, /excluded_from_overall:\s*boolean/);
  assert.match(types, /export interface ScoreBreakdown/);
  assert.match(types, /score_breakdown\?:\s*ScoreBreakdown/);
  assert.match(types, /overall_score\?: number \| null/);
  assert.match(types, /score_summary\?: ScoreSummary/);
});

test("interview API and poller carry video capability to the room", () => {
  const types = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "types.ts"),
    "utf8",
  );
  const poller = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "hooks", "useQuestionPoller.ts"),
    "utf8",
  );

  assert.match(types, /export interface StartSessionResponse[\s\S]*enable_video_analysis\?: boolean/);
  assert.match(types, /export interface PollQuestionResponse[\s\S]*enable_video_analysis\?: boolean/);
  assert.match(types, /export interface ResumeResponse[\s\S]*enable_video_analysis\?: boolean/);
  assert.match(poller, /enableVideoAnalysis: boolean/);
  assert.match(poller, /enableVideoAnalysis: Boolean\(res\.enable_video_analysis\)/);
  assert.match(poller, /enableVideoAnalysis: Boolean\(r\.enable_video_analysis\)/);
}
);

test("poller keeps resume history while waiting for the next question", () => {
  const poller = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "hooks", "useQuestionPoller.ts"),
    "utf8",
  );

  assert.match(
    poller,
    /dispatch\(\{\s*type: "RESUMED",[\s\S]*question: r\.question \?\? null[\s\S]*history: r\.history \?\? \[\]/,
  );
  assert.match(poller, /if \(r\.question\) \{\s*return;\s*\}/);
});

test("poller treats browser long-poll timeout as pending work", () => {
  const poller = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "hooks", "useQuestionPoller.ts"),
    "utf8",
  );

  assert.match(poller, /function isLongPollTimeoutError\(err: unknown\): boolean/);
  assert.match(
    poller,
    /if \(isLongPollTimeoutError\(err\)\) \{\s*await new Promise\(\(r\) => setTimeout\(r, 250\)\);\s*continue;\s*\}/,
  );
});

test("poller keeps waiting through transient question poll failures", () => {
  const poller = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "hooks", "useQuestionPoller.ts"),
    "utf8",
  );

  assert.match(poller, /function isTransientPollError\(err: unknown\): boolean/);
  assert.match(poller, /err instanceof ApiError[\s\S]*err\.status >= 500/);
  assert.match(
    poller,
    /if \(isTransientPollError\(err\)\) \{\s*await new Promise\(\(r\) => setTimeout\(r, 250\)\);\s*continue;\s*\}/,
  );
});

test("api client preserves structured error code and action", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "client.ts"),
    "utf8",
  );

  assert.match(source, /readonly code\?: string/);
  assert.match(source, /readonly action\?: string/);
  assert.match(source, /code\?: string/);
  assert.match(source, /action\?: string/);
});
