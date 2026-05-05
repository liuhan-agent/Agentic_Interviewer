const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

test("session APIs send token header and answer turn index", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );

  assert.match(source, /"X-Session-Token"/);
  assert.match(source, /turn_idx: turnIdx/);
  assert.match(source, /getSessionToken\(sessionId\)/);
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

test("interview API exposes reauth-required detection", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );

  assert.match(source, /export function isReauthRequired/);
  assert.match(source, /reauth_required/);
  assert.match(source, /err instanceof ApiError/);
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
