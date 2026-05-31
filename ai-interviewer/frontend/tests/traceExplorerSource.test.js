const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("admin api exposes trace explorer client", () => {
  const api = read("src/lib/api/admin.ts");

  assert.match(api, /TraceExplorerResponse/);
  assert.match(api, /TraceExplorerNode/);
  assert.match(api, /getTraceExplorer/);
  assert.match(api, /TraceDiagnostics/);
  assert.match(api, /trace_diagnostics/);
  assert.match(api, /generation_trace_id/);
  assert.match(api, /node_count_total/);
  assert.match(api, /node_type_counts/);
  assert.match(api, /node_type_aliases/);
  assert.match(api, /fallback_trace_count/);
  assert.match(api, /turn_count/);
  assert.match(api, /nodes_has_more/);
  assert.ok(api.includes("/admin/interview-sessions/${encodeURIComponent(sessionId)}/traces"));
});

test("trace explorer page and component expose workflow states", () => {
  const staticPage = read("src/app/admin/trace/page.tsx");
  const page = read("src/app/admin/traces/[sessionId]/page.tsx");
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(staticPage, /searchParams/);
  assert.match(staticPage, /sessionId/);
  assert.match(page, /TraceExplorer/);
  assert.match(component, /trace_health/);
  assert.match(component, /missing/);
  assert.match(component, /partial/);
  assert.match(component, /complete/);
  assert.match(component, /PartialTraceDiagnostics/);
  assert.match(component, /missing_key_nodes/);
  assert.match(component, /generationTraceId/);
  assert.match(component, /nodeName/);
  assert.match(component, /node_count_total/);
  assert.match(component, /nodes_has_more/);
  assert.match(component, /查看原始 Trace Payload/);
  assert.match(component, /轮次时间线/);
  assert.match(component, /route_decision/);
});

test("trace explorer exposes diagnostic workbench layout and URL state", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /TraceCommandCenter/);
  assert.match(component, /TraceWorkbench/);
  assert.match(component, /TraceTurnRail/);
  assert.match(component, /TraceNodeDetail/);
  assert.match(component, /useSearchParams/);
  assert.match(component, /nodeType/);
  assert.match(component, /selectedTraceId/);
  assert.match(component, /aria-pressed/);
  assert.match(component, /focus-visible:ring/);
});

test("trace explorer selection syncs URL without triggering Next navigation", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /replaceExplorerUrl/);
  assert.match(component, /window\.history\.replaceState/);
  assert.match(component, /replaceExplorerUrl\(\{ selectedTraceId: node\.id \}\)/);
  assert.match(component, /replaceExplorerUrl\(\{\s*nodeType:/);
  assert.match(component, /replaceExplorerUrl\(\{ fallback: next \|\| null, selectedTraceId: null \}\)/);
  assert.match(component, /replaceExplorerUrl\(\{ q: value\.trim\(\) \|\| null, selectedTraceId: null \}\)/);
  assert.doesNotMatch(component, /useRouter/);
  assert.doesNotMatch(component, /router\.replace/);
  assert.doesNotMatch(component, /updateExplorerQuery\(\{ selectedTraceId: node\.id \}\)/);
});

test("trace explorer command center renders node type distribution dynamically", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /nodeTypeCounts=\{nodeTypeCounts\}/);
  assert.match(component, /Object\.entries\(nodeTypeCounts\)/);
  assert.match(component, /nodeDistribution\.slice\(0,\s*6\)/);
  assert.match(component, /showAllNodeTypes/);
  assert.match(component, /节点分布/);
  assert.match(component, /最后节点/);
});

test("trace explorer uses Chinese keys with backend workflow terms as values", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /execution trace/);
  assert.match(component, /Trace Health/);
  assert.match(component, /会话状态/);
  assert.match(component, /总分/);
  assert.match(component, /结论/);
  assert.match(component, /轮次/);
  assert.match(component, /节点数/);
  assert.match(component, /最后节点/);
  assert.match(component, /已加载/);
  assert.match(component, /节点分布/);
  assert.match(component, /轮次时间线/);
  assert.match(component, /内容搜索/);
  assert.match(component, /搜索问题、回答摘录、评估理由、context/);
  assert.match(component, /原始 Trace Payload/);
  assert.match(component, /generation_traces/);
  assert.match(component, /node evidence/);
  assert.match(component, /raw payload/);
  assert.doesNotMatch(component, /搜索 node、question、answer、context/);
  assert.doesNotMatch(component, /SummaryTile label="Session Status"/);
  assert.doesNotMatch(component, /SummaryTile label="Last Node"/);
  assert.doesNotMatch(component, />Node Distribution</);
  assert.doesNotMatch(component, />Node Search</);
  assert.doesNotMatch(component, />节点搜索</);
});

test("trace explorer renders structured node evidence and lazy raw payloads", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /answer_excerpt/);
  assert.match(component, /immediate_reward_applied/);
  assert.match(component, /policy_context_keys/);
  assert.match(component, /EvaluationEvidence/);
  assert.match(component, /RawTracePayloadDetails/);
  assert.match(component, /JSON\.stringify\(rawPayload/);
  assert.match(component, /max-h-\[32rem\]/);
  assert.doesNotMatch(component, /max-h-72/);
  assert.match(component, /content-visibility/);
  assert.match(component, /prefers-reduced-motion/);
});

test("trace explorer detail pane uses Chinese keys for backend evidence fields", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /NodeFact label="轮次"/);
  assert.match(component, /NodeFact label="上下文"/);
  assert.match(component, /NodeFact label="策略"/);
  assert.match(component, /NodeFact label="创建时间"/);
  assert.match(component, /NodeFact label="策略上下文键"/);
  assert.match(component, /TraceTextExcerpt/);
  assert.match(component, /label="问题"/);
  assert.match(component, /value=\{node\.question\}/);
  assert.match(component, /回答摘录/);
  assert.match(component, /label="回答摘录"/);
  assert.match(component, /value=\{node\.answer_excerpt\}/);
  assert.match(component, /评估证据/);
  assert.match(component, /EvaluatorScoringBasis/);
  assert.match(component, /评分依据/);
  assert.match(component, /展开评分依据明细/);
  assert.match(component, /EvidenceList label="覆盖要求" values=\{mustCover\}/);
  assert.match(component, /label="验收检查"\s+values=\{acceptanceChecks\}/);
  assert.match(component, /label="最低门槛"/);
  assert.match(component, /EvidenceList label="复核重点" values=\{reviewFocus\}/);
  assert.match(component, /EvidenceList label="旧版评分点" values=\{rubricPoints\}/);
  assert.doesNotMatch(component, /展开评分依据 <span className="font-mono">contract<\/span>/);
  assert.doesNotMatch(component, /EvidenceList label="must_cover" values=\{mustCover\}/);
  assert.doesNotMatch(component, /label="acceptance_checks"\s+values=\{acceptanceChecks\}/);
  assert.doesNotMatch(component, /EvidenceList label="review_focus" values=\{reviewFocus\}/);
  assert.doesNotMatch(component, /EvidenceList label="rubric_points" values=\{rubricPoints\}/);
  assert.match(component, /contract_source/);
  assert.match(component, /current_question\.contract/);
  assert.match(component, /legacy rubric/);
  assert.match(component, /未记录评分依据/);
  assert.doesNotMatch(component, /label="评分覆盖"/);
  assert.doesNotMatch(component, /EvidenceList label="rubric_coverage"/);
  assert.match(component, /acceptance_check_results/);
  assert.match(component, /AcceptanceCheckResults/);
  assert.match(component, /<AcceptanceCheckResults results=\{acceptanceCheckResults\} \/>/);
  assert.match(component, /yes \/ partial \/ no/);
  assert.match(component, /acceptanceVerdictBadgeClass/);
  assert.match(component, /verdict === "yes"/);
  assert.match(component, /verdict === "partial"/);
  assert.match(component, /verdict === "no"/);
  assert.match(component, /VerificationReviewPanel/);
  assert.match(component, /<VerificationReviewPanel node=\{node\} \/>/);
  assert.match(component, /复核结果/);
  assert.match(component, /Verifier 检查 evaluator 的评分是否站得住/);
  assert.match(component, /NodeFact label="是否触发"/);
  assert.match(component, /NodeFact label="Verifier 结论"/);
  assert.match(component, /NodeFact label="置信度"/);
  assert.match(component, /label="Evaluator 原结论"/);
  assert.match(component, /label="复核后结论"/);
  assert.match(component, /label="是否改写"/);
  assert.match(component, /NodeFact label="复核影响"/);
  assert.match(component, /改写明细/);
  assert.match(component, /展开改写明细/);
  assert.match(component, /verification_changes/);
  assert.match(component, /verification_effect/);
  assert.match(component, /展开软警告/);
  assert.match(component, /未改写/);
  assert.match(component, /改写为继续追问/);
  assert.match(component, /NodeFact label="强制追问"/);
  assert.match(component, /label="低置信保留原判"/);
  assert.match(component, /EvidenceList label="质疑原因"/);
  assert.match(component, /VerificationChangeList/);
  assert.match(component, /verificationEffectLabel/);
  assert.match(component, /verificationRewriteLabel/);
  assert.match(component, /formatVerificationChangeValue/);
  assert.match(component, /verificationReviewStatus/);
  assert.match(component, /verificationVerdictLabel/);
  assert.match(component, /formatVerifierPassState/);
  assert.doesNotMatch(component, /校验器（Verifier）：/);
  assert.match(component, /优势/);
  assert.match(component, /不足/);
  assert.match(component, /奖励状态/);
  assert.doesNotMatch(component, /line-clamp-2 text-sm leading-relaxed/);
  assert.doesNotMatch(component, /NodeFact label="turn"/);
  assert.doesNotMatch(component, /NodeFact label="context"/);
  assert.doesNotMatch(component, /NodeFact label="policy"/);
  assert.doesNotMatch(component, /NodeFact label="created"/);
  assert.doesNotMatch(component, />EvaluationEvidence</);
});

test("trace explorer explains director strategy decisions as user-facing evidence", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /StrategyDecisionSummary/);
  assert.match(component, /node\.node === "director_sample"/);
  assert.match(component, /出题决策摘要/);
  assert.match(component, /本节点承接 route_decision=next_question/);
  assert.match(component, /只解释进入下一题后 Director 选了什么动作与上下文/);
  assert.match(component, /节点类型/);
  assert.match(component, /目标维度/);
  assert.match(component, /出题动作/);
  assert.match(component, /计划模板/);
  assert.match(component, /计划模板来源/);
  assert.match(component, /动作说明/);
  assert.match(component, /维度变化/);
  assert.match(component, /出题动作决策原因/);
  assert.match(component, /决策上下文/);
  assert.match(component, /策略算法/);
  assert.match(component, /策略空间/);
  assert.match(component, /奖励回填上下文/);
  assert.match(component, /路由原因请看 route_decision/);
  assert.match(component, /localizeActionName/);
  assert.match(component, /localizeActionDescription/);
  assert.match(component, /localizePlanTemplateName/);
  assert.match(component, /localizeDimensionEffect/);
  assert.match(component, /planTemplateSourceLabel/);
  assert.match(component, /diagnosticModeLabel/);
  assert.match(component, /轻量探测/);
  assert.match(component, /轻量模板/);
  assert.match(component, /plan_simple/);
  assert.match(component, /deep_probe/);
  assert.match(component, /plan_deep_probe/);
  assert.match(component, /切换到下一个待覆盖维度，并用 adaptive 模板出下一题。/);
  assert.match(component, /Plan: Switch/);
  assert.match(component, /待后续 reward_update 回填/);
  assert.match(component, /splitPolicyId/);
  assert.match(component, /selected_action/);
  assert.doesNotMatch(component, /追问\/计划模板/);
  assert.doesNotMatch(component, /Lightweight first-turn probe; skip contract negotiation\./);
  assert.doesNotMatch(
    component,
    /Adaptive plan but move on to the next pending dimension/,
  );
  assert.doesNotMatch(component, /候选上下文/);
  assert.doesNotMatch(component, /StrategyDecisionSummary\(\{ node \}: \{ node: never/);
});

test("trace explorer surfaces director action guardrail diagnostics", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /ActionGuardrailSummary/);
  assert.match(component, /动作候选过滤/);
  assert.match(component, /原始候选/);
  assert.match(component, /最终候选/);
  assert.match(component, /禁用动作/);
  assert.match(component, /禁用原因/);
  assert.match(component, /action_guardrail/);
  assert.match(component, /actionGuardrailReasonLabel/);
  assert.match(component, /actionGuardrailSearchFields/);
  assert.match(component, /\.\.\.actionGuardrailSearchFields\(node\.payload\)/);
  assert.match(component, /contract_unsigned/);
  assert.match(component, /verification_soft_warning/);
});

test("trace explorer explains route decisions without generic evaluation evidence", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /RouteDecisionPanel/);
  assert.match(component, /node\.node === "route_decision"/);
  assert.match(component, /route_decision/);
  assert.match(component, /路由决策/);
  assert.match(component, /route_after_eval/);
  assert.match(component, /条件边诊断/);
  assert.match(component, /不是真实 workflow node/);
  assert.match(component, /route_after_eval 条件边诊断/);
  assert.match(component, /refine \/ next_question \/ end/);
  assert.match(component, /路由到对应的真实节点/);
  assert.match(component, /决策原因/);
  assert.match(component, /下一节点/);
  assert.match(component, /后续影响/);
  assert.match(component, /旧 trace 未记录路由原因/);
  assert.match(component, /继续追问/);
  assert.match(component, /进入下一题/);
  assert.match(component, /结束面试/);
  assert.match(component, /refine_followup/);
  assert.match(component, /pending_plan_template \/ pending_contract_hints/);
  assert.match(component, /decision_reason/);
  assert.match(component, /next_node/);
  assert.match(component, /decision_inputs/);
  assert.match(component, /recommended_next_plan/);
  assert.match(component, /fallback_reason/);
  assert.match(component, /routeDecisionSearchFields/);
  assert.match(component, /\.\.\.routeDecisionSearchFields\(node\.payload\)/);
});

test("trace explorer explains turn finalize housekeeping nodes", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /TurnFinalizePanel/);
  assert.match(component, /isTurnFinalizeNode/);
  assert.match(component, /traceNodeDisplayName/);
  assert.match(component, /traceNodeRawAlias/);
  assert.match(component, /traceNodeCanonicalName/);
  assert.match(component, /normalizeTraceNodeFilter/);
  assert.match(component, /payload\.display_name_zh/);
  assert.match(component, /payload\.semantic_node/);
  assert.match(component, /traceNodeDescription/);
  assert.match(component, /turn_finalize/);
  assert.match(component, /轮次收尾/);
  assert.match(component, /real workflow node/);
  assert.doesNotMatch(component, /turn_finalize · compress_context/);
  assert.match(component, /状态清理/);
  assert.match(component, /记录状态/);
  assert.match(component, /整理完成/);
  assert.match(component, /历史上下文归属/);
  assert.match(component, /路由前整理/);
  assert.match(component, /reward_update 后、route_decision 前/);
  assert.match(component, /不生成问题、不评分、不决定下一步/);
  assert.doesNotMatch(component, /上下文压缩/);
  assert.match(component, /raw_answer_cleared/);
  assert.match(component, /summary_updated/);
  assert.match(component, /summary_mode/);
  assert.match(component, /history_projection_owner/);
  assert.match(component, /HistoryContextBuilder/);
  assert.match(component, /turnFinalizeSearchFields/);
  assert.match(component, /\.\.\.turnFinalizeSearchFields\(node\.payload\)/);

  const evidenceStart = component.indexOf("function EvaluationEvidence");
  const evidenceEnd = component.indexOf("function StrategyDecisionSummary");
  const evidenceBody = component.slice(evidenceStart, evidenceEnd);
  assert.match(evidenceBody, /isTurnFinalizeNode\(node\.node\)/);

  const detailStart = component.indexOf("function TraceNodeDetail");
  const detailEnd = component.indexOf("function RouteDecisionPanel");
  const detailBody = component.slice(detailStart, detailEnd);
  assert.match(detailBody, /!isTurnFinalizeNode\(node\.node\)/);
});

test("trace explorer treats compress_context as a turn_finalize filter alias", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /TRACE_NODE_ALIASES/);
  assert.match(component, /compress_context:\s*"turn_finalize"/);
  assert.match(component, /traceNodeCanonicalName\(nodeFilter\)/);
  assert.match(component, /traceNodeCanonicalName\(node\.node\)/);
  assert.match(component, /nodeTypeCounts\[traceNodeCanonicalName\(t\)\]/);
  assert.match(component, /traceNodeCanonicalName\(focusNode\)/);
  assert.doesNotMatch(component, /node\.node !== nodeFilter/);
  assert.doesNotMatch(
    component,
    /String\(n\.node \?\? ""\)\.toLowerCase\(\) === wantedNode/,
  );
});

test("trace explorer explains successor workflow nodes with dedicated panels", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /RefineFollowupPanel/);
  assert.match(component, /node\.node === "refine_followup"/);
  assert.match(component, /追问准备/);
  assert.match(component, /本节点承接 route_decision=refine/);
  assert.match(component, /下一轮计划模板/);
  assert.match(component, /pending_contract_hints/);
  assert.match(component, /must_address/);
  assert.match(component, /missing_must_cover/);
  assert.match(component, /failure_categories/);
  assert.match(component, /prior_soft_warnings/);
  assert.match(component, /旧 trace 未记录追问提示/);

  assert.match(component, /FinalReportPanel/);
  assert.match(component, /node\.node === "final_report"/);
  assert.match(component, /报告收尾/);
  assert.match(component, /本节点承接 route_decision=end/);
  assert.match(component, /报告总览/);
  assert.match(component, /评分可信度/);
  assert.match(component, /维度结果/);
  assert.match(component, /维度证据摘要/);
  assert.match(component, /收尾链路状态/);
  assert.match(component, /workflow artifacts/);
  assert.match(component, /report_summary/);
  assert.match(component, /scoring_credibility/);
  assert.match(component, /dimension_results/);
  assert.match(component, /dimension_evidence/);
  assert.match(component, /training_plan_queued/);
  assert.match(component, /experience_extractor_queued/);
  assert.match(component, /missing_sections/);

  assert.match(component, /TrainingPlanPanel/);
  assert.match(component, /node\.node === "training_plan"/);
  assert.match(component, /训练计划/);
  assert.match(component, /训练计划总览/);
  assert.match(component, /能力诊断/);
  assert.match(component, /优先改进项/);
  assert.match(component, /练习任务/);
  assert.match(component, /30 \/ 60 \/ 90 天目标/);
  assert.match(component, /生成诊断/);
  assert.match(component, /plan_summary/);
  assert.match(component, /priority_weaknesses/);
  assert.match(component, /practice_plan/);
  assert.match(component, /goals_30_60_90/);

  assert.match(component, /承接 route_decision=next_question/);
  assert.match(component, /真实 workflow node/);
  const routePanelStart = component.indexOf("function RouteDecisionPanel");
  const routePanelEnd = component.indexOf("function RefineFollowupPanel");
  const routePanelBody = component.slice(routePanelStart, routePanelEnd);
  assert.doesNotMatch(routePanelBody, /RefineFollowupPanel|FinalReportPanel/);
});

test("trace explorer explains reward and experience learning nodes", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /RewardUpdatePanel/);
  assert.match(component, /RewardQuestionContext/);
  assert.match(component, /node\.node === "reward_update"/);
  assert.match(component, /node\.node !== "reward_update"/);
  assert.match(component, /奖励回填/);
  assert.match(component, /奖励总览/);
  assert.match(component, /即时奖励 reward/);
  assert.match(component, /verification 改写/);
  assert.match(component, /逻辑轮次/);
  assert.match(component, /正式题次/);
  assert.match(component, /Bandit 动作更新/);
  assert.match(component, /动作层/);
  assert.match(component, /更新上下文数/);
  assert.match(component, /StrategyMemory 归因/);
  assert.match(component, /经验内容层/);
  assert.match(component, /本轮没有命中可回填的策略记忆/);
  assert.match(component, /题库归因/);
  assert.match(component, /题库 Variant 层/);
  assert.match(component, /使用上方即时奖励回填/);
  assert.match(component, /Skill 归因/);
  assert.match(component, /Skill card 层/);
  assert.match(component, /本轮没有可回填的 Skill card/);
  assert.match(component, /RewardAttributionList/);
  assert.match(component, /reward_summary/);
  assert.match(component, /bandit_update/);
  assert.match(component, /strategy_memory_attribution/);
  assert.match(component, /question_attribution/);
  assert.match(component, /skill_attribution/);

  assert.match(component, /ExperienceExtractorPanel/);
  assert.match(component, /node\.node === "experience_extractor"/);
  assert.match(component, /node\.node !== "experience_extractor"/);
  assert.match(component, /经验抽取/);
  assert.match(component, /QA 模式/);
  assert.match(component, /Bandit 洞察/);
  assert.match(component, /saved_keys/);
  assert.match(component, /qa_candidates/);
  assert.match(component, /bandit_candidates/);
  assert.match(component, /ExperienceSignalKeyLists/);
  assert.match(component, /ExperienceSignalKeyList/);
  assert.match(component, /来源 session/);
  assert.match(component, /已保存经验 key/);
  assert.match(component, /StrategySignal 标识/);
  assert.match(component, /overflow-x-auto/);
  assert.match(component, /whitespace-nowrap/);
  assert.match(component, /commonSessionKeyPrefix/);
  assert.match(component, /stripCommonPrefix/);

  const evidenceStart = component.indexOf("function EvaluationEvidence");
  const evidenceEnd = component.indexOf("function StrategyDecisionSummary");
  const evidenceBody = component.slice(evidenceStart, evidenceEnd);
  assert.match(evidenceBody, /node\.node === "reward_update"/);
  assert.match(evidenceBody, /node\.node === "experience_extractor"/);

  assert.match(component, /rewardUpdateSearchFields/);
  assert.match(component, /\.\.\.rewardUpdateSearchFields\(node\.payload\)/);
  assert.match(component, /experienceExtractorSearchFields/);
  assert.match(component, /\.\.\.experienceExtractorSearchFields\(node\.payload\)/);
});

test("trace explorer explains ask_question evidence as grouped user-facing sections", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /AskQuestionEvidencePanel/);
  assert.match(component, /node\.node === "ask_question"/);
  assert.match(component, /本轮出题总览/);
  assert.match(component, /这条记录说明 ask_question 如何计划、检索、装配上下文并生成问题。/);
  assert.match(component, /本节点记录出题前证据装配；回答和评分请查看同一 Turn 的 evaluator \/ verification 节点。/);
  assert.match(component, /出题方案/);
  assert.match(component, /问题意图/);
  assert.match(component, /题库模式/);
  assert.match(component, /评分契约签署方/);
  assert.match(component, /本轮执行计划/);
  assert.match(component, /localizeAskPlanStepTitle/);
  assert.match(component, /localizeAskPlanSuccessCriteria/);
  assert.match(component, /检索通用知识库/);
  assert.match(component, /检索策略记忆/);
  assert.match(component, /预审评分契约/);
  assert.match(component, /后端步骤/);
  assert.match(component, /前置依赖：先完成步骤/);
  assert.match(component, /产出字段：/);
  assert.match(component, /产出字段 \{producedKeys\.length\}/);
  assert.match(component, /已写入 retrieval_block/);
  assert.match(component, /评分契约/);
  assert.match(component, /诊断提示/);
  assert.match(component, /contract_diagnostics/);
  assert.match(component, /未记录诊断/);
  assert.match(component, /not_evaluator_signed/);
  assert.match(component, /must_cover/);
  assert.match(component, /acceptance_checks/);
  assert.match(component, /minimum_bar/);
  assert.match(component, /review_focus/);
  assert.match(component, /仅记录模板，未记录 steps/);
  assert.match(component, /produced_keys/);
  assert.match(component, /出题策略记忆/);
  assert.match(component, /localizeStrategyMemoryName/);
  assert.match(component, /strategyMemoryDescription/);
  assert.match(component, /strategyMemoryTraceKey/);
  assert.match(component, /stringValue\(strategy\.display_name_zh\)/);
  assert.match(component, /stringValue\(strategy\.display_description_zh\) \|\| stringValue\(strategy\.description\)/);
  assert.match(component, /追问时机/);
  assert.match(component, /回避型回答模式/);
  assert.match(component, /支撑样本/);
  assert.match(component, /置信度/);
  assert.match(component, /StrategyRankingReasonDetails/);
  assert.match(component, /展开 <span className="font-mono">ranking_reason<\/span>/);
  assert.doesNotMatch(component, /展开排序原因/);
  assert.match(component, /基础匹配分/);
  assert.match(component, /策略优先级/);
  assert.match(component, /requested_context_keys/);
  assert.match(component, /能力焦点 \/ SKILLS 命中/);
  assert.match(component, /命中 \$\{skillRefs\.length\} skill refs/);
  assert.match(component, /localizeSkillMatchReason/);
  assert.match(component, /SkillMatchReasonsDetails/);
  assert.match(component, /SkillRewardShadowDetails/);
  assert.match(component, /display_name_zh/);
  assert.match(component, /display_description_zh/);
  assert.match(component, /stringValue\(ref_\.display_name_zh\) \|\| rawName/);
  assert.match(component, /stringValue\(ref_\.display_description_zh\) \|\| rawDescription/);
  assert.doesNotMatch(component, /localizeSkillCard/);
  assert.doesNotMatch(component, /skillNameTranslation/);
  assert.doesNotMatch(component, /数据管道追问卡/);
  assert.doesNotMatch(component, /调试根因追问卡/);
  assert.match(component, /name:\{rawName\}/);
  assert.match(component, /<span className="font-mono">description<\/span>:/);
  assert.doesNotMatch(component, /中文说明：/);
  assert.match(component, /skill_id:/);
  assert.match(component, /优先级/);
  assert.match(component, /匹配分/);
  assert.match(component, /评分器信号（未注入）/);
  assert.match(component, /仅出题侧/);
  assert.match(component, /展开评分器信号 <span className="font-mono">evaluator_payload<\/span>/);
  assert.doesNotMatch(component, /Evaluator 可见/);
  assert.match(component, /展开 <span className="font-mono">match_reasons<\/span>/);
  assert.match(component, /命中原因：/);
  assert.match(component, /评分提示 rubric_hints/);
  assert.match(component, /正向信号 positive_signals/);
  assert.match(component, /负向信号 negative_signals/);
  assert.match(component, /评分偏置 score_bias_rules/);
  assert.match(component, /结构化题库/);
  assert.match(component, /Seed 主题/);
  assert.match(component, /Variant 问法/);
  assert.match(component, /StructuredQuestionCandidate/);
  assert.match(component, /QuestionMatchReasonsDetails/);
  assert.match(component, /QuestionRewardShadowDetails/);
  assert.match(component, /reward_shadow_rank/);
  assert.match(component, /reward_shadow_score/);
  assert.match(component, /reward_shadow_reason/);
  assert.match(component, /avg_blended_reward/);
  assert.match(component, /overrule_rate/);
  assert.match(component, /Skills/);
  assert.match(component, /仅观测，不影响当前注入题/);
  assert.match(component, /历史使用次数/);
  assert.match(component, /有评分样本数/);
  assert.match(component, /平均 reward/);
  assert.match(component, /通过率/);
  assert.match(component, /关键匹配项/);
  assert.match(component, /groupQuestionMatchReasons/);
  assert.match(component, /formatGroupedQuestionReason/);
  assert.match(component, /border-sky-400\/45 bg-sky-500\/20 text-sky-100/);
  assert.match(component, /localizeQuestionMatchReason/);
  assert.match(component, /锚点关键词命中/);
  assert.match(component, /候选人项目适配/);
  assert.doesNotMatch(component, /命中摘要/);
  assert.doesNotMatch(component, /简历锚点/);
  assert.doesNotMatch(component, /match_reasons: \{stringList\(item\.match_reasons\)\.join/);
  assert.match(component, /候选人适配提示/);
  assert.match(component, /question_fit_profile/);
  assert.match(component, /适配层/);
  assert.match(component, /题库绑定/);
  assert.match(component, /项目来源/);
  assert.match(component, /target_dimension/);
  assert.match(component, /seed_binding/);
  assert.match(component, /project_anchor_source/);
  assert.match(component, /candidate_adaptation/);
  assert.match(component, /rank 1/);
  assert.match(component, /展开注入内容 <span className="font-mono">CANDIDATE_ANCHOR<\/span>/);
  assert.match(component, /候选人锚点 RAG/);
  assert.match(component, /实际注入 Prompt 的资料/);
  assert.match(component, /prompt_slots/);
  assert.match(component, /PROMPT_SLOT_DEFINITIONS/);
  assert.match(component, /PromptSlotCard/);
  assert.match(component, /\$\{orderedPromptSlots\.length\} prompt slots/);
  assert.match(component, /prompt_truncated/);
  assert.match(component, /trace_text_truncated/);
  assert.match(component, /runtime_truncated/);
  assert.match(component, /runtime_items/);
  assert.match(component, /运行时裁剪/);
  assert.match(component, /展开运行时裁剪明细/);
  assert.match(component, /source_type/);
  assert.match(component, /project_name/);
  assert.match(component, /chunk_index/);
  assert.match(component, /score/);
  assert.match(component, /来源类型/);
  assert.match(component, /字段/);
  assert.match(component, /限制类型/);
  assert.match(component, /限制值/);
  assert.match(component, /field_item_limit/);
  assert.match(component, /field_char_limit/);
  assert.match(component, /项目/);
  assert.match(component, /标题/);
  assert.match(component, /Chunk/);
  assert.match(component, /匹配分/);
  assert.match(component, /Prompt 预算截断/);
  assert.match(component, /Trace 文本截断/);
  assert.doesNotMatch(component, /label="已截断"/);
  assert.doesNotMatch(component, /7 prompt slots/);
  assert.match(component, /INTERVIEW_HISTORY_SUMMARY/);
  assert.match(component, /history_summary_projection/);
  assert.match(component, /RECENT_QA/);
  assert.match(component, /recent_qa_prompt_view/);
  assert.match(component, /CURRENT_GAPS/);
  assert.match(component, /current_gaps/);
  assert.match(component, /题库问法骨架/);
  assert.match(component, /候选人适配提示/);
  assert.match(component, /简历命中片段/);
  assert.match(component, /自我介绍命中片段/);
  assert.match(component, /Skills Playbook/);
  assert.match(component, /未记录/);
  assert.match(component, /展开完整内容/);
  assert.match(component, /CANDIDATE_RESUME_RAG/);
  assert.match(component, /辅助诊断/);
  assert.match(component, /summary="legacy 通用知识库 RAG · avoid patterns · failure categories"/);
  assert.doesNotMatch(component, /summary="legacy 通用知识库 RAG · avoid patterns · failure categories · raw payload"/);
  assert.match(component, /通用知识库 RAG/);
  assert.match(component, /规避模式/);
  assert.match(component, /失败类别/);
  assert.match(component, /ask_plan/);
  assert.match(component, /selection_artifacts/);
  assert.match(component, /question_items/);
  assert.match(component, /candidate_anchor_rag/);
  assert.match(component, /anchor_scheduler/);
  assert.match(component, /question_reranker/);
  assert.match(component, /statusLabelForArtifact/);
  assert.match(component, /已注入/);
  assert.match(component, /仅观测/);
  assert.match(component, /未命中/);
  assert.match(component, /关闭/);
  assert.match(component, /轻量 warning/);
  assert.match(component, /max-h-64/);
  assert.match(component, /max-h-\[30rem\]/);
  assert.match(component, /renderTopItems/);
  assert.match(component, /ExpandableEvidenceItems/);
  assert.match(component, /展开剩余/);
  assert.match(component, /setExpanded/);
  assert.match(component, /type="button"/);
  assert.doesNotMatch(component, /JSON\.stringify\(payload/);
});

test("trace explorer hides stale answer and evaluation on ask_question rows", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /node\.node !== "ask_question"/);
  assert.match(component, /node\.node !== "route_decision"/);
  assert.match(component, /node\.answer_excerpt &&/);
  assert.match(
    component,
    /node\.node === "route_decision"/,
  );
  assert.match(component, /answer_excerpt/);
  assert.match(component, /EvaluationEvidence/);
});

test("trace explorer separates generic RAG from candidate anchor RAG hits", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /const anchorHits = recordArray\(candidateAnchorRag\.hits\)/);
  assert.match(component, /renderTopItems\(anchorHits/);
  assert.match(component, /stringValue\(hit\.excerpt\)/);
  assert.match(component, /stringValue\(hit\.source_type\)/);
  assert.match(component, /锚点 \$\{anchorHits\.length\}/);
  assert.match(component, /通用知识库 RAG/);
  assert.match(component, /候选人锚点 RAG/);
});

test("trace explorer surfaces candidate anchor RAG diagnostics", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /候选人锚点 RAG/);
  assert.match(component, /检索状态/);
  assert.match(component, /耗时/);
  assert.match(component, /Prompt 注入/);
  assert.match(component, /注入字符/);
  assert.match(component, /fallback_reason/);
  assert.match(component, /boost_fallback_reason/);
  assert.match(component, /bind_validation/);
  assert.match(component, /bound_count/);
  assert.match(component, /rebind_attempted/);
  assert.match(component, /rebind_success/);
  assert.match(component, /session_anchor_bind_missing/);
  assert.match(component, /query_embedding_timeout/);
  assert.match(component, /no_bound_chunks/);
  assert.match(component, /fetched_rows_by_source/);
  assert.match(component, /scored_rows_by_source/);
  assert.match(component, /kept_hits_by_source/);
  assert.match(component, /展开检索诊断 <span className="font-mono">candidate_anchor_rag<\/span>/);
  assert.match(component, /CandidateAnchorHitDiagnostics/);
  assert.match(component, /CandidateAnchorRagDiagnostics/);
  assert.match(component, /锚点相似分/);
  assert.match(component, /增强相似分/);
  assert.match(component, /约束匹配度/);
  assert.match(component, /命中目标技能/);
  assert.match(component, /命中维度/);
  assert.match(component, /命中题库词/);
  assert.match(component, /锚点检索词/);
  assert.match(component, /增强检索词/);
  assert.match(component, /约束检索词/);
  assert.match(component, /完整检索文本/);
  assert.match(component, /锚点检索文本/);
  assert.match(component, /增强检索文本/);
  assert.match(component, /约束检索文本/);
  assert.match(component, /hit\.anchor_score/);
  assert.match(component, /hit\.boost_score/);
  assert.match(component, /hit\.constraint_match/);
  assert.match(component, /hit\.matched_target_skills/);
  assert.match(component, /candidateAnchorRag\.query_text/);
  assert.match(component, /candidateAnchorRag\.anchor_query_text/);
  assert.match(component, /candidateAnchorRag\.boost_query_text/);
  assert.match(component, /candidateAnchorRag\.constraint_query_text/);
});

test("trace explorer gives heavy ask_question evidence sections full-width rows", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /data-trace-section="ask-question-primary-evidence"/);
  assert.match(component, /className="mt-3 space-y-3"/);
  assert.match(
    component,
    /heading="本轮执行计划"[\s\S]*heading="评分契约"[\s\S]*heading="出题策略记忆"[\s\S]*heading="能力焦点 \/ SKILLS 命中"[\s\S]*heading="结构化题库"[\s\S]*heading="候选人适配提示"[\s\S]*heading="候选人锚点 RAG"[\s\S]*heading="实际注入 Prompt 的资料"/,
  );
  assert.doesNotMatch(
    component,
    /<div className="mt-3 grid gap-3 xl:grid-cols-2">[\s\S]*heading="结构化题库"[\s\S]*heading="候选人锚点 RAG"/,
  );
});

test("trace explorer shows candidate anchor as user-facing project signal", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /const resumeAnchor = recordFromUnknown\(\s*artifacts\.resume_anchor \?\? payload\.resume_anchor,\s*\)/);
  assert.match(component, /const anchorLabel = resumeAnchorLabel\(\s*resumeAnchor,\s*candidateAnchorRag,\s*\)/);
  assert.match(component, /const hitProjectLabel = candidateAnchorHitProjectLabel\(anchorHits\)/);
  assert.match(component, /function resumeAnchorLabel/);
  assert.match(component, /function firstAnchorTerm/);
  assert.match(component, /function readableAnchorValue/);
  assert.match(component, /function candidateAnchorHitProjectLabel/);
  assert.match(component, /localizeAnchorExpansionReason/);
  assert.match(component, /label="项目锚点"/);
  assert.match(component, /label="锚点选择原因"/);
  assert.match(component, /label="锚点 ID"/);
  assert.match(component, /CandidateAnchorRagDiagnostics/);
  assert.match(component, /自我介绍优先匹配（首次使用）/);
  assert.match(component, /维度匹配（首次使用）/);
  assert.match(component, /value=\{hitProjectLabel\}/);
  assert.match(component, /looksLikeInternalAnchorId/);
  assert.doesNotMatch(component, /candidateAnchorLabel\([^)]*anchorHits/);
  assert.doesNotMatch(component, /NodeFact label="锚点键"/);
  assert.doesNotMatch(component, /NodeFact label="扩展原因"/);

  const anchorLabelFunction =
    component.match(/function resumeAnchorLabel[\s\S]*?\n}\n\nfunction candidateAnchorHitProjectLabel/)?.[0] ?? "";
  assert.match(anchorLabelFunction, /firstAnchorTerm\(candidateAnchorRag\.anchor_terms\)/);
  assert.doesNotMatch(anchorLabelFunction, /anchorScheduler\.anchor_key/);
  assert.doesNotMatch(anchorLabelFunction, /anchor_query_text/);
});

test("trace explorer search covers structured ask_question evidence fields", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /askQuestionSearchFields/);
  assert.match(component, /skill id\/name/);
  assert.match(component, /rag source/);
  assert.match(component, /question seed_id/);
  assert.match(component, /variant_id/);
  assert.match(component, /strategy id\/name/);
  assert.match(component, /ask plan step/);
  assert.match(component, /prompt slot/);
  assert.match(component, /prompt slot runtime item/);
  assert.match(component, /PromptBudgetDiagnosticsPanel/);
  assert.match(component, /Prompt 预算诊断/);
  assert.match(component, /record\.prompt_budget_diagnostics/);
  assert.match(component, /budget_level/);
  assert.match(component, /runtime_budget_level/);
  assert.match(component, /runtime_budget_source/);
  assert.match(component, /runtime_global_budget_pressure/);
  assert.match(component, /protected_slots/);
  assert.match(component, /fallback_reason/);
  assert.match(component, /record\.ask_plan/);
  assert.match(component, /record\.prompt_slots/);
  assert.match(component, /record\.contract_diagnostics/);
  assert.match(component, /record\.contract/);
  assert.match(component, /acceptance_checks/);
  assert.match(component, /review_focus/);
  assert.match(component, /candidate anchor RAG diagnostics/);
  assert.match(component, /candidateAnchorRag\.anchor_terms/);
  assert.match(component, /candidateAnchorRag\.boost_terms/);
  assert.match(component, /candidateAnchorRag\.constraint_terms/);
  assert.match(component, /matched_target_skills/);
  assert.match(component, /matched_project/);
  assert.match(component, /match_reasons/);
  assert.match(component, /reward_shadow_rank/);
  assert.match(component, /reward_shadow_score/);
  assert.match(component, /reward_shadow_reason/);
  assert.match(component, /usage_stats/);
  assert.match(component, /sample_confidence/);
  assert.match(component, /metadata_rank/);
  assert.match(component, /\.\.\.askQuestionSearchFields\(node\.payload\)/);
  assert.match(component, /successorNodeSearchFields/);
  assert.match(component, /\.\.\.successorNodeSearchFields\(node\.payload\)/);
  assert.match(component, /verificationChangeSearchFields/);
  assert.match(component, /\.\.\.verificationChangeSearchFields\(node\.payload\)/);
  assert.match(component, /record\.verification_changes/);
  assert.match(component, /record\.verification_effect/);
  assert.match(component, /record\.pending_contract_hints/);
  assert.match(component, /record\.missing_sections/);
  assert.match(component, /record\.report_status/);
  assert.match(component, /record\.selected_action/);
  assert.match(component, /record\.diagnostics/);
  assert.doesNotMatch(component, /JSON\.stringify\(node\.payload\)/);
});

test("admin sessions expose Trace link", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.match(panel, /Trace/);
  assert.match(panel, /training_plan/);
  assert.match(panel, /experience_extractor/);
  assert.match(panel, /resume_parse/);
  assert.match(panel, /route_decision/);
  assert.ok(panel.includes("`/admin/trace?sessionId=${session.session_id}`"));
});

test("trace explorer groupByTurn defends against non-monotonic ordering", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  // Sentinel: numeric-aware key + explicit session-level token must
  // both be present so the bucket index can be sorted numerically and
  // the catch-all bucket can be pinned to the bottom.
  assert.match(component, /buckets\s*=\s*new\s+Map<TraceTurnGroupKey/);
  assert.match(component, /Number\.POSITIVE_INFINITY/);

  // Sentinel: there is an explicit numeric sort over the produced
  // groups (without this we would silently rely on Map insertion
  // order, which is what the original bug was about).
  assert.match(component, /groups\.sort\(\s*\(a,\s*b\)\s*=>\s*a\.sortKey\s*-\s*b\.sortKey\s*\)/);
  assert.match(component, /effectiveTraceTurnKey/);
  assert.match(component, /groupByTurn\(filteredNodes,\s*allNodes\)/);
  assert.match(component, /SESSION_CLOSING_NODES/);
  assert.match(component, /收尾阶段/);
  assert.match(component, /isTurnFinalizeNode\(node\.node\)/);
  assert.match(component, /payload\.phase !== "turn_finalize"/);
  assert.match(component, /Math\.max\(0,\s*node\.turn_idx - 1\)/);
  assert.match(component, /shouldGroupRefineFollowupWithNextTurn/);
  assert.match(component, /sameTurnHasQuestionStart/);
  assert.match(component, /nextTurnHasQuestionStart/);
  assert.match(component, /isAskRoundStartNode/);
  assert.match(component, /下一轮准备/);
  assert.match(component, /traceNodeWorkflowOrder\(a,\s*items\)/);
  assert.match(component, /traceNodeWorkflowOrder/);
  assert.match(component, /reward_update/);
  assert.match(component, /turn_finalize/);
  assert.match(component, /route_decision/);
});

test("trace explorer can filter and mark evaluator fallback traces", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /isEvaluatorFallbackTrace/);
  assert.match(component, /fallbackFilter/);
  assert.match(component, /仅看 fallback/);
  assert.match(component, /Evaluator fallback/);
  assert.match(component, /fallbackTraceCount/);
});

test("rag eval copy frames score delta as correlation", () => {
  const component = read("src/components/admin/RagEvalPanel.tsx");

  assert.match(component, /相关性观察/);
  assert.match(component, /检索相关分数差异/);
  assert.match(component, /不代表单独的因果归因/);
});
