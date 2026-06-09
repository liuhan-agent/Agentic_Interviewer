const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

test("job template autofill does not automatically parse JD", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );
  const loadJobTemplateBody = source.match(
    /async function loadJobTemplate\(directionId: DirectionId\) \{(?<body>[\s\S]*?)\n  \}/,
  )?.groups?.body;

  assert.ok(loadJobTemplateBody, "loadJobTemplate body should be present");
  assert.doesNotMatch(loadJobTemplateBody, /scheduleJdParse\(template\)/);
});

test("resume draft uses sessionStorage instead of localStorage", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );

  assert.match(source, /const RESUME_DRAFT_KEY = "resume_draft"/);
  assert.match(source, /safeSessionGetItem\(RESUME_DRAFT_KEY\)/);
  assert.match(source, /safeSessionSetItem\(RESUME_DRAFT_KEY/);
  assert.match(source, /safeSessionRemoveItem\(RESUME_DRAFT_KEY\)/);
  assert.doesNotMatch(source, /sessionStorage\.(getItem|setItem|removeItem)\("resume_draft"/);
  assert.doesNotMatch(source, /localStorage\.(getItem|setItem|removeItem)\("resume_draft"/);
});

test("resume upload ignores stale parse responses", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );

  assert.match(source, /uploadRequestRef/);
  assert.match(source, /const requestId = \+\+uploadRequestRef\.current/);
  assert.match(source, /requestId !== uploadRequestRef\.current/);
});

test("resume parsing state lets users continue setup instead of waiting blindly", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );

  assert.match(source, /AI 解析中/);
  assert.match(source, /可以离开当前页面/);
  assert.match(source, /首页“接着练”或“我的面试”继续回来/);
  assert.match(source, /取消解析/);
  assert.match(source, /解析可能需要几分钟/);
  assert.doesNotMatch(source, /可以先填写或编辑下面的信息/);
});

test("setup form restores async resume parse drafts by draft id", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );

  assert.match(source, /searchParams\.get\("draft_id"\)/);
  assert.match(source, /getSetupDraft/);
  assert.match(source, /getResumeParseJob/);
  assert.match(source, /upsertSetupDraft/);
  assert.match(source, /removeSetupDraft/);
  assert.match(source, /resumeFieldsLocked/);
});

test("setup form restores resume snapshot for report practice links", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );

  assert.match(source, /getResumeSetupSnapshot/);
  assert.match(source, /getSessionSetupSnapshot/);
  assert.match(source, /searchParams\.get\("resume_from"\)/);
  assert.match(source, /applyResumeSetupSnapshot/);
  assert.match(
    source,
    /getResumeSetupSnapshot\(sourceSessionId\)[\s\S]*getSessionSetupSnapshot\(sourceSessionId\)/,
  );
  assert.match(source, /已沿用上一场简历解析结果/);
});

test("setup form carries resume parse audit into session payload", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );

  assert.match(source, /ResumeParseAudit/);
  assert.match(source, /useState<ResumeParseAudit\s*\|\s*null>\(null\)/);
  assert.match(source, /setResumeParseAudit\(result\.resume_parse_audit\s*\?\?\s*null\)/);
  assert.match(source, /resume_parse_audit:\s*resumeParseAudit/);
});

test("setup form does not show the legacy resume polish draft prompt", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );

  assert.doesNotMatch(source, /检测到你有未提交的简历精修草稿/);
});

test("setup form exposes actionable JD and upload error copy", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );

  assert.match(source, /friendlySetupError/);
  assert.match(source, /仍可继续使用默认考察维度/);
  assert.match(source, /清除解析结果/);
  assert.doesNotMatch(source, /移除文件/);
  assert.doesNotMatch(source, /移除文件状态/);
  assert.doesNotMatch(source, />清除</);
});

test("setup form error summary announces validation failures", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );

  assert.match(source, /role="alert"/);
  assert.match(source, /aria-live="assertive"/);
});

test("resume editor exposes field budgets", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );

  assert.match(source, /CANDIDATE_SUMMARY_MAX_LENGTH = 1200/);
  assert.match(source, /CANDIDATE_SKILLS_MAX_COUNT = 40/);
  assert.match(source, /CANDIDATE_HIGHLIGHTS_MAX_COUNT = 20/);
  assert.match(source, /RESUME_PROJECTS_MAX_COUNT = 12/);
  assert.match(source, /RESUME_FOCUS_AREAS_MAX_COUNT = 20/);
  assert.match(source, /maxLength=\{CANDIDATE_SUMMARY_MAX_LENGTH\}/);
  assert.match(source, /最多 12 个项目/);
  assert.match(source, /最多 20 个重点/);
});

test("setup schema trims required text and handles empty advanced numbers", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );

  assert.match(source, /requiredTrimmedString\("请填写称呼"\)/);
  assert.match(source, /requiredTrimmedString\("请填写岗位名称"\)/);
  assert.match(source, /emptyStringToUndefined/);
  assert.match(source, /optionalIntegerNumber\(1,\s*20,\s*"请输入 1-20 的整数"\)/);
  assert.match(source, /optionalIntegerNumber\(1,\s*30,\s*"请输入 1-30 的整数"\)/);
  assert.match(source, /numberWithEmptyDefault\(7,\s*0,\s*10,\s*"请输入 0-10 的数字"\)/);
});

test("history export and copy explain session token privacy", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "HistoryList.tsx"),
    "utf8",
  );

  assert.match(source, /sessionTokenExpiresAt/);
  assert.match(source, /delete safeEntry\.sessionToken/);
  assert.match(source, /delete safeEntry\.sessionTokenExpiresAt/);
  assert.match(source, /导出历史只包含面试记录/);
  assert.match(source, /不会包含继续访问会话的临时凭证/);
});

test("setup form stores browser recovery credential from start response", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );

  assert.match(source, /recoveryToken: res\.recovery_token/);
  assert.match(source, /recoveryTokenExpiresAt: res\.recovery_token_expires_at/);
});

test("setup form surfaces platform credit state before starting hosted interviews", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );

  assert.match(source, /getAccountCreditPolicy/);
  assert.match(source, /getAccountCredits/);
  assert.match(source, /useAuth/);
  assert.match(source, /isUsingByokConfig/);
  assert.match(source, /platformCreditNotice/);
  assert.match(source, /登录领取免费次数/);
  assert.match(source, /剩余 \{creditBalance\} 次/);
  assert.match(source, /次数不足/);
  assert.match(source, /creditBalance:\s*res\.credit_balance/);
});

test("setup form reads browser LLM config only after hydration", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );

  assert.match(source, /useState<StartSessionRequest\["llm_config"\]>\(undefined\)/);
  assert.match(source, /setCurrentLlmPayload\(buildLLMPayload\(\)\)/);
  assert.doesNotMatch(source, /const currentLlmPayload = buildLLMPayload\(\)/);
});

test("setup form centralizes platform credit gate and disables unsafe starts", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );
  const creditHelper = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "credits.ts"),
    "utf8",
  );

  assert.match(source, /getCreditStartGateState/);
  assert.match(source, /startGate\.disabled/);
  assert.match(source, /startGate\.notice/);
  assert.match(creditHelper, /本次将消耗 1 次平台面试次数/);
  assert.match(creditHelper, /正在同步账号额度/);
  assert.match(creditHelper, /不扣平台次数/);
  assert.match(creditHelper, /自己的模型服务额度/);
  assert.match(source, /disabled=\{isStartingInterview \|\| resumeFieldsLocked \|\| startGate\.disabled\}/);
  assert.match(source, /login_required_for_platform_credits/);
  assert.match(source, /platform_credits_exhausted/);
  assert.match(source, /已扣 1 次/);
});

test("setup form locks the start action while creating the interview session", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );

  assert.match(source, /isInterviewStartPending/);
  assert.match(source, /setInterviewStartPending\(true\)/);
  assert.match(source, /const isStartingInterview = isSubmitting \|\| isInterviewStartPending/);
  assert.match(source, /aria-busy=\{isStartingInterview\}/);
  assert.match(source, /document\.body\.style\.overflow = "hidden"/);
  assert.match(source, /正在创建面试环境/);
  assert.match(source, /min-h-40/);
  assert.match(source, /items-center gap-4/);
  assert.doesNotMatch(source, /animate-shimmer bg-shimmer/);
  assert.doesNotMatch(source, /w-2\/3/);
  assert.doesNotMatch(source, /animate=\{\{ width: \[/);
  assert.doesNotMatch(source, /repeat: Number\.POSITIVE_INFINITY/);
  assert.match(source, /disabled=\{isStartingInterview \|\| resumeFieldsLocked \|\| startGate\.disabled\}/);
});

test("setup preloads the interview route and the interview page has a loading skeleton", () => {
  const setupSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );
  const loadingPath = path.join(
    __dirname,
    "..",
    "src",
    "app",
    "interview",
    "[sessionId]",
    "loading.tsx",
  );

  assert.match(setupSource, /START_INTERVIEW_PREFETCH_SESSION_ID/);
  assert.match(setupSource, /router\.prefetch\(`\/interview\/\$\{START_INTERVIEW_PREFETCH_SESSION_ID\}`\)/);
  assert.match(setupSource, /step === STEPS\.length - 1/);
  assert.equal(fs.existsSync(loadingPath), true);

  const loadingSource = fs.readFileSync(loadingPath, "utf8");
  assert.match(loadingSource, /function InterviewSessionLoading/);
  assert.match(loadingSource, /aria-busy="true"/);
  assert.match(loadingSource, /正在打开面试页面/);
});
