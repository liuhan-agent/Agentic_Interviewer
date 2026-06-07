const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const replaySource = fs.readFileSync(
  path.join(__dirname, "..", "src", "components", "interview", "ReplayView.tsx"),
  "utf8",
);
const apiTypesSource = fs.readFileSync(
  path.join(__dirname, "..", "src", "lib", "api", "types.ts"),
  "utf8",
);

test("Replay API types expose context and question basis", () => {
  assert.match(apiTypesSource, /export interface ReplayContextBasis/);
  assert.match(apiTypesSource, /export interface ReplayQuestionBasis/);
  assert.match(apiTypesSource, /export interface ReplayQuestionDecisionBasis/);
  assert.match(apiTypesSource, /export interface ReplayAnchorFollowup/);
  assert.match(apiTypesSource, /dimension_source_label\?:\s*string/);
  assert.match(apiTypesSource, /context_basis\?:\s*ReplayContextBasis\s*\|\s*null/);
  assert.match(apiTypesSource, /question_basis\?:\s*ReplayQuestionBasis\s*\|\s*null/);
  assert.match(apiTypesSource, /question_decision_basis\?:\s*ReplayQuestionDecisionBasis\s*\|\s*null/);
  assert.match(apiTypesSource, /anchor_followup\?:\s*ReplayAnchorFollowup\s*\|\s*null/);
  assert.match(apiTypesSource, /resume_anchor_label\?:\s*string\s*\|\s*null/);
});

test("Replay API types expose grouped priority items", () => {
  assert.match(apiTypesSource, /export interface ReplayPriorityItem/);
  assert.match(apiTypesSource, /category:\s*"weakness"\s*\|\s*"coverage_limited"/);
  assert.match(apiTypesSource, /label:\s*"薄弱点"\s*\|\s*"补充证据"/);
  assert.match(apiTypesSource, /display_text:\s*string/);
  assert.match(apiTypesSource, /priority_items\?:\s*ReplayPriorityItem\[\]/);
});

test("API types expose resume parse audit as candidate sidecar", () => {
  assert.match(apiTypesSource, /export interface ResumeParseAudit/);
  assert.match(apiTypesSource, /resume_parse_audit\?:\s*ResumeParseAudit/);
  assert.match(apiTypesSource, /field_sources:\s*Record<string,\s*string>/);
  assert.match(apiTypesSource, /skills_summary:\s*Record<string,\s*unknown>/);
  assert.match(apiTypesSource, /merge_summary:\s*Record<string,\s*unknown>/);
});

test("ReplayView renders the two-layer basis UI", () => {
  assert.match(replaySource, /<ContextBasisCard basis=\{replay\.context_basis\}/);
  assert.match(replaySource, /function ContextBasisCard/);
  assert.match(replaySource, /<details/);
  assert.match(
    replaySource,
    /<QuestionBasisBlock\s+basis=\{turn\.question_basis\}\s+decisionBasis=\{turn\.question_decision_basis\}\s+resumeAnchorLabel=\{turn\.resume_anchor_label\}/,
  );
  assert.match(
    replaySource,
    /<AnchorFollowupNotice\s+followup=\{turn\.anchor_followup\}\s+resumeAnchorLabel=\{turn\.resume_anchor_label\}/,
  );
  assert.match(replaySource, /function QuestionBasisBlock/);
  assert.match(replaySource, /decisionBasis\?:\s*ReplayTurn\["question_decision_basis"\]/);
  assert.match(replaySource, /function QuestionDecisionBasisDetails/);
  assert.match(replaySource, /decisionBasis\.sources/);
  assert.match(replaySource, /decisionBasis\.target_skills/);
  assert.match(replaySource, /decisionBasis\.reason_codes/);
  assert.match(replaySource, /<QuestionDecisionBasisDetails basis=\{decisionBasis\}/);
  assert.match(replaySource, /resumeAnchorLabel\?:\s*ReplayTurn\["resume_anchor_label"\]/);
  assert.match(replaySource, /<QuestionBasisChipGroup label="关联经历" chips=\{anchorChips\}/);
  assert.match(replaySource, /function AnchorFollowupNotice/);
  assert.match(replaySource, /resumeAnchorLabel\?:\s*ReplayTurn\["resume_anchor_label"\]/);
  assert.match(replaySource, /简历锚点「\$\{anchorLabel\}」第 \$\{followup\.attempt\}\/\$\{followup\.max_attempts\} 轮追问/);
  assert.match(replaySource, /当前简历锚点第 \$\{followup\.attempt\}\/\$\{followup\.max_attempts\} 轮追问/);
  assert.match(replaySource, /function splitQuestionBasisChips/);
  assert.match(replaySource, /function getQuestionBasisGroupIcon/);
  assert.match(replaySource, /依据来源/);
  assert.match(replaySource, /关联经历/);
  assert.match(replaySource, /匹配维度/);
  assert.match(replaySource, /具体线索/);
  assert.match(replaySource, /LabelIcon className="h-3\.5 w-3\.5/);
  assert.match(replaySource, /text-muted-foreground/);
  assert.match(replaySource, /basis\.summary/);
  assert.match(replaySource, /basis\.chips\.map/);
  assert.match(replaySource, /basis\.self_intro\?\.emphasized_projects/);
  assert.match(replaySource, /basis\.resume\?\.focus_areas/);
  assert.match(replaySource, /basis\.job_spec\?\.required_skills/);
  assert.match(replaySource, /UserRound/);
  assert.match(replaySource, /FileText/);
  assert.match(replaySource, /BriefcaseBusiness/);
  assert.match(replaySource, /function getContextBasisRowIcon/);
  assert.match(replaySource, /title="自我介绍"/);
  assert.match(replaySource, /title="简历"/);
  assert.match(replaySource, /title="岗位要求"/);
  assert.doesNotMatch(replaySource, /title="来自自我介绍"|title="来自简历"|title="来自岗位要求"/);
  assert.doesNotMatch(replaySource, /border-l/);
  assert.match(replaySource, /项目线索/);
  assert.match(replaySource, /技能线索/);
  assert.match(replaySource, /岗位技能/);
  assert.match(replaySource, /评分维度（默认评分标准）/);
});

test("ReplayView groups priority items and keeps legacy fallback", () => {
  assert.match(replaySource, /summary\.priority_items/);
  assert.match(replaySource, /function groupReplayPriorityItems/);
  assert.match(replaySource, /priorityGroups\.weakness/);
  assert.match(replaySource, /priorityGroups\.coverage_limited/);
  assert.match(replaySource, /薄弱点/);
  assert.match(replaySource, /补充证据/);
  assert.match(replaySource, /priorityItem\.display_text/);
  assert.match(replaySource, /function getPriorityGroupTitleMeta/);
  assert.match(replaySource, /title === "补充证据"/);
  assert.match(replaySource, /<TitleIcon className="h-3\.5 w-3\.5/);
  assert.match(replaySource, /bg-sky-500\/\[0\.06\]/);
  assert.match(replaySource, /text-sky-200\/80/);
  assert.match(replaySource, /summary\.priority_weaknesses/);
  assert.match(replaySource, /优先补强/);
});

test("ReplayView renders a visually distinct fallback for empty weaknesses", () => {
  assert.match(replaySource, /emptyText="本轮没有明确短板记录，可结合评分依据继续复盘。"/);
  assert.match(replaySource, /emptyText\?:\s*string/);
  assert.match(replaySource, /values\.length === 0 && emptyText/);
  assert.match(replaySource, /italic/);
  assert.match(replaySource, /text-muted-foreground\/70/);
});

test("ReplayView gives turn section labels a light icon treatment", () => {
  assert.match(replaySource, /function SectionLabel/);
  assert.match(replaySource, /function getSectionLabelMeta/);
  assert.match(replaySource, /title === "问题"/);
  assert.match(replaySource, /title === "你的回答"/);
  assert.match(replaySource, /title === "评分依据"/);
  assert.match(replaySource, /title === "亮点"/);
  assert.match(replaySource, /title === "可提升"/);
  assert.match(replaySource, /<SectionLabel title=\{title\}/);
  assert.match(replaySource, /<SectionLabel title="你的回答"/);
  assert.match(replaySource, /<SectionLabel title="评分依据"/);
  assert.match(replaySource, /inline-flex items-center gap-1\.5 rounded-md/);
  assert.match(replaySource, /text-muted-foreground\/80/);
});

test("ReplayView does not expose internal basis fields", () => {
  assert.doesNotMatch(replaySource, /basis\.self_intro\?\.summary/);
  assert.doesNotMatch(replaySource, /\bresume_anchor\b/);
  assert.doesNotMatch(
    replaySource,
    /skill_focus|focus_source|pending_contract_hints|recommended_probe_intent/,
  );
});
