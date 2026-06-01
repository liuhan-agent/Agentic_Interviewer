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

test("LLM route summary keeps default fallback and experimental details lightweight", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );

  const summaryBlock = source.match(/function ModelRouteSummary[\s\S]*?function ModelStrategyHint/);
  assert.ok(summaryBlock, "ModelRouteSummary should render before ModelStrategyHint");
  assert.match(summaryBlock[0], /其它 LLM 调用/);
  assert.match(summaryBlock[0], /使用默认配置/);
  assert.match(summaryBlock[0], /没有单独列出的常规调用和后续新增调用/);
  assert.match(summaryBlock[0], /bg-secondary\/10/);
  assert.match(summaryBlock[0], /高级明细/);
  assert.match(summaryBlock[0], /strategy_dream/);
  assert.match(summaryBlock[0], /question_reranker/);
  assert.match(summaryBlock[0], /实验开关关闭时不会产生额外 LLM 调用/);
  assert.doesNotMatch(summaryBlock[0], /<RoleGroupCard/);
});

test("LLM route summary badges only mark explicit frontend overrides", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );

  const summaryBlock = source.match(/function ModelRouteSummary[\s\S]*?function ModelStrategyHint/);
  assert.ok(summaryBlock, "ModelRouteSummary should render before ModelStrategyHint");
  assert.equal(
    (summaryBlock[0].match(/source: configured\?\.enabled \? "单独配置" : "默认配置"/g) ?? [])
      .length,
    2,
  );
  assert.doesNotMatch(
    summaryBlock[0],
    /configured\.apiKey\.trim\(\) \|\| config\.provider === effective\.provider/,
  );
});

test("LLM settings exposes voice ASR and TTS routes", () => {
  const configSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "llm-config.ts"),
    "utf8",
  );
  const dialogSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );

  assert.match(configSource, /voiceOverrides/);
  assert.match(configSource, /voice_overrides/);
  assert.match(configSource, /qwen3-asr-flash-realtime/);
  assert.match(configSource, /qwen3-tts-flash-realtime/);
  assert.match(configSource, /voice: "Cherry"/);
  assert.match(configSource, /provider: "qwen"/);
  assert.match(configSource, /id: "openai"/);
  assert.match(dialogSource, /语音能力/);
  assert.match(dialogSource, /语音识别/);
  assert.match(dialogSource, /语音合成/);
  assert.match(dialogSource, /VoiceRouteCard/);
});

test("LLM settings exposes Xiaomi MiMo as an OpenAI-compatible preset", () => {
  const configSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "llm-config.ts"),
    "utf8",
  );

  const providerBlock = configSource.match(
    /export const PROVIDERS = \[([\s\S]*?)\] as const/,
  )?.[1];

  assert.ok(providerBlock);
  assert.match(providerBlock, /id: "xiaomimimo"/);
  assert.match(providerBlock, /label: "Xiaomi MiMo"/);
  assert.match(providerBlock, /defaultModel: "mimo-v2\.5-pro"/);
  assert.match(providerBlock, /defaultBaseUrl: "https:\/\/api\.xiaomimimo\.com\/v1"/);
});

test("voice route cards match role override card interaction style", () => {
  const dialogSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );

  const voiceBlock = dialogSource.match(/function VoiceRouteCard[\s\S]*?function RoleGroupCard/);
  assert.ok(voiceBlock, "VoiceRouteCard should exist before RoleGroupCard");
  assert.match(voiceBlock[0], /type="checkbox"/);
  assert.match(voiceBlock[0], /单独配置/);
  assert.match(voiceBlock[0], /使用建议配置/);
  assert.match(voiceBlock[0], /当前有效模型/);
  assert.match(voiceBlock[0], /overrideEnabled &&/);
  assert.doesNotMatch(voiceBlock[0], /grid gap-3 sm:grid-cols-2">\s*<VoiceRouteCard/);
});

test("voice synthesis route offers preset voices and custom voice input", () => {
  const configSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "llm-config.ts"),
    "utf8",
  );
  const dialogSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );

  assert.match(configSource, /ttsVoices/);
  assert.match(configSource, /"Cherry"/);
  assert.match(configSource, /"Serena"/);
  assert.match(configSource, /"Ethan"/);
  assert.match(configSource, /"Chelsie"/);
  assert.match(dialogSource, /voiceOptions/);
  assert.match(dialogSource, /value=\{selectedPresetVoice\}/);
  assert.match(dialogSource, /自定义音色/);
  assert.match(dialogSource, /customVoiceSelected/);
});

test("voice capability section is independently collapsible", () => {
  const dialogSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );

  const voiceDetails = dialogSource.match(/<details className="group rounded-md border bg-background\/40 p-4">[\s\S]*?VoiceRouteCard[\s\S]*?<\/details>/);
  assert.ok(voiceDetails, "voice capability section should be a details block");
  assert.match(voiceDetails[0], /<summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm font-medium">/);
  assert.match(voiceDetails[0], /语音能力/);
  assert.match(voiceDetails[0], /ChevronDown/);
  assert.match(voiceDetails[0], /group-open:rotate-180/);
});

test("LLM settings exposes session anchor embedding route", () => {
  const configSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "llm-config.ts"),
    "utf8",
  );
  const dialogSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );
  const typeSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "types.ts"),
    "utf8",
  );

  assert.match(configSource, /embeddingOverride/);
  assert.match(configSource, /embedding_override/);
  assert.match(configSource, /text-embedding-v4/);
  assert.match(configSource, /dimensions: 1536/);
  assert.match(configSource, /\| "embedding:session_anchor"/);
  assert.match(configSource, /kind: "embedding"/);
  assert.match(dialogSource, /EmbeddingRouteCard/);
  assert.match(dialogSource, /资料理解能力/);
  assert.match(dialogSource, /简历与自我介绍/);
  assert.doesNotMatch(dialogSource, /Session Anchor RAG/);
  assert.doesNotMatch(dialogSource, /Session Anchor Embedding/);
  assert.doesNotMatch(dialogSource, /PgVector 表/);
  assert.match(typeSource, /embedding_override/);
});

test("embedding route inherits only same-provider default keys", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "llm-config.ts"),
    "utf8",
  );

  assert.match(source, /effectiveEmbeddingConfig/);
  assert.match(source, /sameEmbeddingProvider\(config\.provider, effective\.provider\)/);
  assert.doesNotMatch(source, /config\.provider === "deepseek" \? config\.apiKey/);
});

test("embedding route uses the role override form pattern with qwen-only provider", () => {
  const configSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "llm-config.ts"),
    "utf8",
  );
  const dialogSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );
  const providerBlock = configSource.match(
    /export const EMBEDDING_PROVIDERS = \[([\s\S]*?)\] as const/,
  )?.[1];
  const embeddingCard = dialogSource.match(
    /function EmbeddingRouteCard[\s\S]*?function VoiceRouteCard/,
  )?.[0];

  assert.ok(providerBlock);
  assert.match(providerBlock, /id: "qwen"/);
  assert.doesNotMatch(providerBlock, /id: "openai"/);
  assert.doesNotMatch(providerBlock, /id: "openai_compatible"/);
  assert.match(configSource, /isSupportedEmbeddingProvider/);
  assert.match(configSource, /provider: provider\.id/);
  assert.ok(embeddingCard);
  assert.match(embeddingCard, /使用建议配置/);
  assert.match(embeddingCard, /<Label>服务商<\/Label>/);
  assert.match(embeddingCard, /<option[\s\S]*\{provider\.label\}[\s\S]*<\/option>/);
  assert.doesNotMatch(embeddingCard, /EMBEDDING_PROVIDERS\.map/);
  assert.match(embeddingCard, /<Label>API 密钥（可选）<\/Label>/);
  assert.doesNotMatch(embeddingCard, /<Label>\{provider\.label\} API 密钥/);
  assert.match(embeddingCard, /Base URL（基础地址）/);
});

test("voice overrides only inherit the default key from same-provider configs", async () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "llm-config.ts"),
    "utf8",
  );

  assert.match(source, /effectiveVoiceConfig/);
  assert.match(source, /sameVoiceProvider\(config\.provider, effective\.provider\)/);
  assert.match(source, /voiceOverrides\.asr/);
  assert.match(source, /voiceOverrides\.tts/);
  assert.doesNotMatch(source, /config\.provider === "deepseek" \? config\.apiKey/);
});

test("voice payload serializes qwen defaults and keeps OpenAI explicit", () => {
  const configSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "llm-config.ts"),
    "utf8",
  );
  const typeSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "api", "types.ts"),
    "utf8",
  );

  assert.match(configSource, /provider: asrVoice\.provider/);
  assert.match(configSource, /provider: ttsVoice\.provider/);
  assert.match(configSource, /model: asrVoice\.model \|\| voiceProviderInfo\(asrVoice\.provider\)\.asrModel/);
  assert.match(configSource, /voice: ttsVoice\.voice \|\| voiceProviderInfo\(ttsVoice\.provider\)\.ttsVoice/);
  assert.match(typeSource, /provider\?: "qwen" \| "openai"/);
});

test("LLM connection tests include voice ASR and TTS routes", () => {
  const configSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "llm-config.ts"),
    "utf8",
  );
  const dialogSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );

  assert.match(configSource, /\| `voice:\$\{LLMVoiceRouteId\}`/);
  assert.match(configSource, /kind: "asr"/);
  assert.match(configSource, /kind: "tts"/);
  assert.match(configSource, /effectiveVoiceConfig\(config, "asr"\)/);
  assert.match(configSource, /effectiveVoiceConfig\(config, "tts"\)/);
  assert.match(configSource, /kind: target\.kind/);
  assert.match(dialogSource, /routeProviderLabel\(result\.provider, result\.kind\)/);
});

test("LLM connection tests include session anchor embedding route", () => {
  const configSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "llm-config.ts"),
    "utf8",
  );
  const dialogSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );

  assert.match(configSource, /id: "embedding:session_anchor"/);
  assert.match(configSource, /label: "资料理解能力"/);
  assert.match(configSource, /dimensions: embedding\.dimensions/);
  assert.match(dialogSource, /target\.kind === "embedding"/);
});

test("LLM test result provider labels distinguish chat and voice providers", () => {
  const dialogSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );

  assert.match(
    dialogSource,
    /function routeProviderLabel\(provider: string, kind\?: LLMTestTargetKind\): string/,
  );
  assert.match(dialogSource, /kind === "asr" \|\| kind === "tts"/);
  assert.doesNotMatch(
    dialogSource,
    /return voiceProviderInfo\(provider\)\.label \|\| providerInfo\(provider\)\.label/,
  );
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

test("LLM test result rows render failed provider error details", () => {
  const dialogSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );

  const rowsBlock = dialogSource.match(/results\.map\(\(result\) => \([\s\S]*?<\/div>\s*\)\)\}/);
  assert.ok(rowsBlock, "connection result rows should be rendered from per-target results");
  assert.match(rowsBlock[0], /result\.error \? \(/);
  assert.match(rowsBlock[0], /break-words/);
  assert.match(rowsBlock[0], /result\.error/);
});

test("LLM test transient rows explain route impact without implying bad config", () => {
  const dialogSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "layout", "LLMSettingsDialog.tsx"),
    "utf8",
  );

  assert.match(dialogSource, /function connectionImpactMessage/);
  assert.match(dialogSource, /result\.errorKind === "network"/);
  assert.match(dialogSource, /result\.errorKind === "timeout"/);
  assert.match(dialogSource, /临时不可用/);
  assert.match(dialogSource, /回答评分/);
  assert.match(dialogSource, /兜底评分/);
  assert.doesNotMatch(dialogSource, /配置一定有误/);
});

test("package exposes frontend source test script", () => {
  const pkg = JSON.parse(
    fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"),
  );

  assert.equal(pkg.scripts.test, "node --test tests/*.test.js");
});
