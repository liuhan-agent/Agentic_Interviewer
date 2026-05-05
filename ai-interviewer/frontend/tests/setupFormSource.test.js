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

test("setup form exposes actionable JD and upload error copy", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "SetupForm.tsx"),
    "utf8",
  );

  assert.match(source, /friendlySetupError/);
  assert.match(source, /仍可继续使用默认考察维度/);
  assert.match(source, /移除文件状态/);
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
  assert.match(source, /当前标签页会话/);
});
