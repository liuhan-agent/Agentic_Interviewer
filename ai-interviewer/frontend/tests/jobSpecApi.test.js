const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

test("parseJobSpec sends llm_config as backend snake_case payload", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "interview.ts"),
    "utf8",
  );

  assert.match(source, /llmConfig\?: LLMConfigPayload/);
  assert.match(source, /direction\?: string/);
  assert.match(source, /const \{ llmConfig, \.\.\.body \} = args/);
  assert.match(source, /llm_config: llmConfig/);
  assert.match(source, /body: llmConfig \? \{ \.\.\.body, llm_config: llmConfig \} : body/);
});
