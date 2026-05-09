const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

test("resume/JD/opening parsing role group applies to resume, JD, and self intro parsers", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "llm-config.ts"),
    "utf8",
  );

  assert.match(source, /\| "jd_parser"/);
  assert.match(source, /\| "self_intro_parser"/);
  assert.match(source, /label: "简历 \/ JD \/ 开场解析"/);
  assert.match(source, /roles: \["resume_parser", "jd_parser", "self_intro_parser"\]/);
  assert.doesNotMatch(source, /label: "简历解析"/);
});

test("evaluation role recommendation favours fast structured scoring models", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "llm-config.ts"),
    "utf8",
  );

  const evaluationBlock = source.match(/id: "evaluation",[\s\S]*?id: "verification",/);
  assert.ok(evaluationBlock, "evaluation role group should exist");
  assert.match(evaluationBlock[0], /稳定、响应快、能输出结构化评分/);
  assert.match(evaluationBlock[0], /model: "qwen3\.6-flash"/);
  assert.match(evaluationBlock[0], /model: "deepseek-v4-flash"/);
  assert.doesNotMatch(evaluationBlock[0], /model: "qwen3\.6-plus"/);
  assert.doesNotMatch(evaluationBlock[0], /model: "deepseek-v4-pro"/);
});

test("LLM settings dialog shows the effective model route summary", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );

  assert.match(source, /function ModelRouteSummary/);
  assert.match(source, /本场实际模型路由/);
  assert.match(source, /modelRouteSummary\(config\)/);
});

test("LLM credentials default to session-only browser storage", () => {
  const configSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "llm-config.ts"),
    "utf8",
  );
  const dialogSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );

  assert.match(configSource, /storageMode: "session"/);
  assert.match(dialogSource, /value=\{config\.storageMode \?\? "session"\}/);
  assert.match(dialogSource, /默认仅保留到当前浏览器会话/);
  assert.match(dialogSource, /密钥会留在这台设备上/);
  assert.match(dialogSource, /<option value="local">本机长期保存（公共设备勿选）<\/option>/);
  assert.match(dialogSource, /混淆不是加密/);
  assert.doesNotMatch(dialogSource, /localStorage/);
});

test("LLM test failure copy points users to failed items", () => {
  const dialogSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );

  assert.match(dialogSource, /部分配置测试未通过。请根据下方结果检查失败项的密钥、模型和 Base URL。/);
  assert.doesNotMatch(dialogSource, /下面会标出具体是哪一项/);
});

test("LLM test result rows style passing targets separately from failed targets", () => {
  const dialogSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );

  const rowsBlock = dialogSource.match(/results\.map\(\(result\) => \([\s\S]*?<\/div>\s*\)\)\}/);
  assert.ok(rowsBlock, "connection result rows should be rendered from per-target results");
  assert.match(rowsBlock[0], /className=\{cn\(/);
  assert.match(rowsBlock[0], /result\.ok\s*\?/);
  assert.match(rowsBlock[0], /border-emerald-400\/30 bg-emerald-400\/10 text-emerald-200/);
  assert.match(rowsBlock[0], /border-destructive\/30 bg-destructive\/10 text-destructive/);
});

test("package exposes frontend source test script", () => {
  const pkg = JSON.parse(
    fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"),
  );

  assert.equal(pkg.scripts.test, "node --test tests/*.test.js");
});
