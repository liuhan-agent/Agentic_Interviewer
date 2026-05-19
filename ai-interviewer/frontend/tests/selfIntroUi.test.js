const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(...segments) {
  return fs.readFileSync(path.join(root, ...segments), "utf8");
}

test("poll question type exposes self-intro metadata", () => {
  const source = read("src", "lib", "api", "types.ts");

  assert.match(source, /question_type\?: "self_intro" \| "technical" \| string/);
  assert.match(source, /formal_turn_idx\?: number/);
  assert.match(source, /question_type\?: "self_intro" \| "technical" \| string/);
  assert.match(source, /export interface SelfIntroProfile/);
  assert.match(source, /self_intro\?: SelfIntroReport/);
});

test("resumed self-intro history renders as opening instead of a numbered question", () => {
  const source = read("src", "components", "interview", "InterviewRoom.tsx");

  assert.match(source, /questionType:\s*turn\.question_type/);
  assert.match(source, /turn\.question_type === "self_intro"/);
});

test("submitted self-intro answer uses the shared collapsible answer bubble", () => {
  const source = read("src", "components", "interview", "InterviewRoom.tsx");

  assert.match(source, /const isSelfIntro = entry\.questionType === "self_intro"/);
  assert.match(source, /entry\.answer !== null && \(\s*<CollapsibleAnswerBubble/);
  assert.doesNotMatch(source, /!isSelfIntro && entry\.answer !== null/);
});

test("interview room renders opening intro differently from technical turns", () => {
  const source = read("src", "components", "interview", "InterviewRoom.tsx");

  assert.match(source, /extractQuestionType/);
  assert.match(source, /extractFormalTurnIdx/);
  assert.match(source, /questionType === "self_intro"/);
  assert.match(source, /开场介绍/);
});

test("opening self-intro still exposes hint and skip controls", () => {
  const source = read("src", "components", "interview", "InterviewRoom.tsx");

  assert.match(source, /求一点思路/);
  assert.match(source, /跳过本题/);
  assert.match(source, /面试官提示/);
  assert.doesNotMatch(source, /!\s*isSelfIntro && \(\s*<Button[\s\S]*?求一点思路/);
  assert.doesNotMatch(source, /!\s*isSelfIntro && \(\s*<Button[\s\S]*?跳过本题/);
  assert.doesNotMatch(source, /!\s*isSelfIntro && \(hintText \|\| hintError \|\| hintLoading\)/);
});

test("report page displays self-intro profile", () => {
  const source = read("src", "components", "interview", "ReportView.tsx");

  assert.match(source, /SelfIntroFocus/);
  assert.match(source, /自我介绍重点/);
  assert.match(source, /强调项目/);
  assert.match(source, /const shouldSpanLastGroup =/);
  assert.match(source, /groups\.length % 2 === 1/);
  assert.match(source, /idx === groups\.length - 1/);
  assert.match(source, /md:col-span-2/);
  assert.doesNotMatch(source, /用于追问参考，不覆盖简历解析。/);
});

test("report page localizes fallback training plan copy", () => {
  const source = read("src", "components", "interview", "ReportView.tsx");

  assert.match(source, /translateReportText/);
  assert.match(source, /评估模型暂时不可用/);
  assert.match(source, /formatDimensionName\(w\.dimension\)/);
  assert.match(source, /translateReportText\(p\.task\)/);
  assert.match(source, /translateReportText\(g\)/);
});

test("report page hides evaluator system fallback from user weaknesses", () => {
  const source = read("src", "components", "interview", "ReportView.tsx");

  assert.match(source, /function isSystemFallbackText/);
  assert.match(source, /priorityWeaknesses/);
  assert.match(source, /practiceItems/);
  assert.match(source, /visibleWeaknesses/);
  assert.match(source, /filter\(\(w\) => !isSystemFallbackText/);
  assert.match(source, /Evaluator LLM unavailable/);
});

test("report page hides NaN score and localizes internal verdicts", () => {
  const source = read("src", "components", "interview", "ReportView.tsx");
  const verdicts = read("src", "lib", "constants", "verdicts.ts");

  assert.match(source, /Number\.isFinite/);
  assert.match(verdicts, /borderline:\s*"接近达标"/);
  assert.match(verdicts, /strong_pass:\s*"表现优秀"/);
  assert.doesNotMatch(source, /Number\(overall\[2\]\)\.toFixed\(2\)/);
});
