const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const setupFormPath = path.join(
  __dirname,
  "..",
  "src",
  "components",
  "interview",
  "SetupForm.tsx",
);
const interviewRoomPath = path.join(
  __dirname,
  "..",
  "src",
  "components",
  "interview",
  "InterviewRoom.tsx",
);
const questionPollerPath = path.join(
  __dirname,
  "..",
  "src",
  "lib",
  "hooks",
  "useQuestionPoller.ts",
);
const reportViewPath = path.join(
  __dirname,
  "..",
  "src",
  "components",
  "interview",
  "ReportView.tsx",
);
const historyListPath = path.join(
  __dirname,
  "..",
  "src",
  "components",
  "interview",
  "HistoryList.tsx",
);
const interviewApiPath = path.join(
  __dirname,
  "..",
  "src",
  "lib",
  "api",
  "interview.ts",
);
const apiTypesPath = path.join(
  __dirname,
  "..",
  "src",
  "lib",
  "api",
  "types.ts",
);
const interviewConstantsPath = path.join(
  __dirname,
  "..",
  "src",
  "lib",
  "constants",
  "interview.ts",
);

function readSetupForm() {
  return fs.readFileSync(setupFormPath, "utf8");
}

function readInterviewRoom() {
  return fs.readFileSync(interviewRoomPath, "utf8");
}

function readQuestionPoller() {
  return fs.readFileSync(questionPollerPath, "utf8");
}

function readReportView() {
  return fs.readFileSync(reportViewPath, "utf8");
}

function readHistoryList() {
  return fs.readFileSync(historyListPath, "utf8");
}

function readInterviewApi() {
  return fs.readFileSync(interviewApiPath, "utf8");
}

function readApiTypes() {
  return fs.readFileSync(apiTypesPath, "utf8");
}

function readInterviewConstants() {
  return fs.readFileSync(interviewConstantsPath, "utf8");
}

test("setup uses interview depth copy instead of strict duration copy", () => {
  const source = readSetupForm();

  assert.match(source, /面试深度/);
  assert.match(source, /快速练习/);
  assert.match(source, /标准面试/);
  assert.match(source, /深度追问/);
  assert.match(source, /目标 5 轮 · 快速校准/);
  assert.match(source, /目标 8 轮 · 核心覆盖/);
  assert.match(source, /目标 12 轮 · 压力追问/);
  assert.match(source, /控制最多提问轮数和追问空间/);

  assert.doesNotMatch(source, /面试时长/);
  assert.doesNotMatch(source, /15-25 分钟/);
  assert.doesNotMatch(source, /10 分钟/);
  assert.doesNotMatch(source, /20 分钟/);
  assert.doesNotMatch(source, /30 分钟/);
});

test("resume upload cached result copy stays user-facing", () => {
  const source = readSetupForm();

  assert.match(source, /已使用上次解析结果，可继续检查和微调/);
  assert.doesNotMatch(source, /Redis 缓存命中/);
});

test("setup stores a local interview history entry after session creation", () => {
  const source = readSetupForm();

  assert.match(source, /upsertEntry/);
  assert.match(source, /sessionId:\s*res\.session_id/);
  assert.match(source, /jdTitle:\s*values\.job_title/);
  assert.match(source, /candidateName:\s*values\.candidate_name/);
  assert.match(source, /jobLevel:\s*values\.job_level/);
  assert.match(source, /rubricDimensions:\s*selectedDims\.map\(\(d\)\s*=>\s*d\.id\)/);
  assert.match(source, /status:\s*"running"/);
  assert.match(source, /maxTurns:\s*res\.max_turns\s*\?\?\s*max_turns/);
});

test("setup accepts weak-focus query prefill", () => {
  const source = readSetupForm();
  const types = readApiTypes();

  assert.match(source, /useSearchParams/);
  assert.match(source, /focus/);
  assert.match(source, /length/);
  assert.match(source, /job_title/);
  assert.match(source, /applyPracticeFocusQuery/);
  assert.match(source, /practiceFocusDims/);
  assert.match(source, /setSelectedDims\(resolvedFocus\.slice\(0,\s*5\)\)/);
  assert.match(source, /focus_dimensions:\s*practiceFocusDims\.map\(\(d\)\s*=>\s*d\.id\)/);
  assert.match(source, /setValue\("length",\s*queryLength/);
  assert.match(types, /focus_dimensions\?: string\[\]/);
});

test("setup sends the selected interview depth to the backend", () => {
  const source = readSetupForm();
  const types = readApiTypes();

  assert.match(types, /interview_depth\?: "short" \| "standard" \| "deep"/);
  assert.match(source, /interview_depth:\s*lengthChoice\.id/);
});

test("api types expose optional depth followup metadata", () => {
  const types = readApiTypes();

  assert.match(types, /export interface DepthFollowupMetadata/);
  assert.match(types, /phase\?: "depth_followup" \| string \| null/);
  assert.match(types, /depth_followup\?: DepthFollowupMetadata \| null/);
});

test("interview room creates a fallback local history entry on deep links", () => {
  const source = readInterviewRoom();

  assert.match(source, /upsertEntry\(\{\s*sessionId,\s*status:\s*"running"\s*\}\)/);
  assert.doesNotMatch(source, /touchVisited\(sessionId\)/);
  assert.doesNotMatch(source, /import\s*\{\s*touchVisited/);
});

test("interview room explains stale sessions instead of generic connection copy", () => {
  const source = readInterviewRoom();

  assert.match(source, /session not found/);
  assert.match(source, /重新开始一场面试/);
  assert.match(source, /后端重启/);
});

test("interview room offers retry when a backend segment failed", () => {
  const source = readInterviewRoom();

  assert.match(source, /retryFailedQuestion/);
  assert.match(source, /afterQuestionRetryRequested/);
  assert.match(source, /继续处理/);
  assert.match(source, /retryable/);
});

test("retrying a failed question resends saved LLM config", () => {
  const source = readInterviewApi();

  assert.match(source, /const llmConfig = buildLLMPayload\(\)/);
  assert.match(source, /llm_config: llmConfig/);
});

test("interview room does not redirect completed sessions without a report", () => {
  const source = readQuestionPoller();

  assert.match(source, /completedWithoutReportMessage/);
  assert.match(source, /r\.status === "completed" && r\.final_report/);
  assert.match(source, /res\.status === "completed"/);
  assert.match(source, /r\.final_report/);
});

test("report page keeps dimension names user-facing", () => {
  const source = readReportView();
  const constants = readInterviewConstants();

  assert.match(source, /formatDimensionName/);
  assert.match(constants, /project_experience:\s*"项目经验"/);
  assert.match(constants, /coding_quality:\s*"代码质量"/);
  assert.match(constants, /product_thinking:\s*"产品思维"/);
  assert.match(constants, /customer_discovery:\s*"客户发现"/);
});

test("report page avoids recruitment-facing candidate copy", () => {
  const source = readReportView();

  assert.doesNotMatch(source, /候选人回答/);
  assert.match(source, /你的回答/);
});

test("report page localizes evaluator fallback rationale", () => {
  const source = readReportView();

  assert.match(
    source,
    /Evaluator LLM failed before returning a score\. The interview continues with a conservative fallback rather than dropping the session\./,
  );
  assert.match(source, /评估模型暂时不可用，已先使用保守评价保留本轮回答。/);
});

test("interview API exposes confirmed hard-delete session call", () => {
  const api = readInterviewApi();
  const types = readApiTypes();

  assert.match(types, /export interface DeleteSessionResponse/);
  assert.match(types, /sessions_deleted:\s*number/);
  assert.match(api, /export function deleteSession/);
  assert.match(api, /method:\s*"DELETE"/);
  assert.match(api, /confirm_session_id=\$\{encodeURIComponent\(sessionId\)\}/);
});

test("report and replay expose weak-focused practice links", () => {
  const report = readReportView();
  const replay = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "ReplayView.tsx"),
    "utf8",
  );

  assert.match(report, /buildWeakPracticeHref/);
  assert.match(report, /priority_weaknesses/);
  assert.match(report, /coverage_warnings/);
  assert.match(report, /length",\s*"short"/);
  assert.match(report, /针对薄弱点专项练习/);
  assert.match(replay, /buildReplayPracticeHref/);
  assert.match(replay, /priority_weaknesses/);
  assert.match(replay, /针对薄弱点专项练习/);
});

test("interview room exposes progress pause skip and draft persistence", () => {
  const source = readInterviewRoom();

  assert.match(source, /maxTurns/);
  assert.match(source, /progressPercent/);
  assert.match(source, /暂停休息/);
  assert.match(source, /继续作答/);
  assert.match(source, /跳过本题/);
  assert.match(source, /skipQuestion/);
  assert.match(source, /answerDraftKey/);
  assert.match(source, /sessionStorage/);
  assert.doesNotMatch(source, /将丢失/);
});

test("interview room clamps visible progress turn to configured max turns", () => {
  const source = readInterviewRoom();

  assert.match(source, /function clampVisibleFormalTurn\(/);
  assert.match(source, /Math\.min\(maxTurns,\s*Math\.max\(0,\s*turn\)\)/);
  assert.match(source, /const currentFormalTurn =\s*clampVisibleFormalTurn\(/);
  assert.match(
    source,
    /\{questionType === "self_intro" \? "0" : currentFormalTurn\}\/\{maxTurns\}/,
  );
});

test("interview room keeps answer length aligned with backend validation", () => {
  const source = readInterviewRoom();

  assert.match(source, /const ANSWER_MAX_LENGTH = 8000;/);
  assert.match(source, /maxLength=\{ANSWER_MAX_LENGTH\}/);
  assert.match(source, /<VoiceAnswerPanel[\s\S]*maxLength=\{ANSWER_MAX_LENGTH\}/);
  assert.doesNotMatch(source, /const ANSWER_MAX_LENGTH = 50000;/);
});

test("interview room exposes directional hint without submitting or clearing draft", () => {
  const source = readInterviewRoom();
  const hintHandler = source.match(
    /async function handleLocalHint\(\) \{[\s\S]*?\n  \}/,
  )?.[0] ?? "";

  assert.match(source, /求一点思路/);
  assert.match(source, /requestHint/);
  assert.match(source, /hintLoading/);
  assert.match(source, /hintError/);
  assert.match(source, /hintText/);
  assert.match(source, /面试官提示/);
  assert.doesNotMatch(source, /教练提示/);
  assert.doesNotMatch(source, /由 AI 教练驱动/);
  assert.match(source, /setHintText\(null\)/);
  assert.match(hintHandler, /requestHint/);
  assert.doesNotMatch(hintHandler, /clearAnswerDraft/);
  assert.doesNotMatch(hintHandler, /onSubmit/);
  assert.doesNotMatch(hintHandler, /onSkip/);
});

test("history page separates local removal from deleting backend data", () => {
  const source = readHistoryList();

  assert.match(source, /deleteSession/);
  assert.match(source, /handleRemoveLocal/);
  assert.match(source, /handleDeleteData/);
  assert.match(source, /从列表移除/);
  assert.match(source, /删除数据/);
  assert.match(source, /无法继续面试/);
  // Dialog warns the user about losing the report; we keep "面试" as
  // primary noun and add "反馈" so we cover both report + feedback.
  assert.match(source, /无法回看本场面试报告与反馈/);
  assert.match(source, /deletingSessionId/);
  assert.match(source, /DeleteSessionDialog/);
  assert.match(source, /永久删除数据/);
  assert.match(source, /取消，保留数据/);
  assert.doesNotMatch(source, /确认删除这场面试的数据吗[\s\S]*window\.confirm/);
});
