const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

function countMatches(source, pattern) {
  return Array.from(source.matchAll(pattern)).length;
}

function nearestActiveTabBefore(source, token) {
  const tokenIndex = source.indexOf(token);
  assert.notEqual(tokenIndex, -1, `${token} should be present`);
  const candidates = ["health", "scoring", "strategy"].map((tab) => ({
    tab,
    index: source.lastIndexOf(`activeTab === "${tab}"`, tokenIndex),
  }));
  return candidates.sort((a, b) => b.index - a.index)[0].tab;
}

test("admin page is framed as an agent observability console", () => {
  const page = read("src/app/admin/page.tsx");

  assert.match(page, /后台观测台/);
  assert.match(page, /Agentic Workflow/);
  assert.match(page, /用户侧质量中心/);
});

test("admin panel exposes system overview and productized card copy", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.match(panel, /SystemOverview/);
  assert.match(panel, /运行概览/);
  assert.match(panel, /关键后台状态灯/);
  assert.match(panel, /OverviewStatusLight/);
  assert.doesNotMatch(panel, /系统状态总览/);
  assert.match(panel, /策略学习/);
  assert.match(panel, /Verifier 监控/);
  assert.match(panel, /drift 观测开关，不代表 Verifier 未运行/);
  assert.match(panel, /运行中会话/);
  assert.match(panel, /已入库策略/);
  assert.match(panel, /面试质量入口/);
  assert.match(panel, /active:scale-\[0\.98\]/);
});

test("admin overview status hints reveal full copy with clear hierarchy", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.match(panel, /TooltipProvider delayDuration=\{150\}/);
  assert.match(panel, /<TooltipTrigger asChild>/);
  assert.match(panel, /<TooltipContent[\s\S]*?side="bottom"[\s\S]*?align="start"/);
  assert.match(panel, /aria-label=\{`\$\{label\}: \$\{hint\}`\}/);
  assert.match(panel, /text-\[10px\] font-semibold uppercase tracking-wide/);
  assert.match(panel, /font-mono text-sm font-semibold/);
  assert.match(panel, /text-\[11px\] leading-4 text-muted-foreground/);
  assert.doesNotMatch(
    panel,
    /truncate text-\[11px\] text-muted-foreground">\{hint\}/,
  );
});

test("admin overview uses DB-backed bandit posterior counts", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");
  const api = read("src/lib/api/admin.ts");

  assert.match(api, /persisted_prior_count\?: number/);
  assert.match(api, /top_posteriors\?: Array/);
  assert.match(panel, /persistedPriorCount/);
  assert.match(panel, /bandit_posteriors/);
  assert.match(panel, /个策略状态/);
  assert.doesNotMatch(panel, /armCount/);
});

test("admin active sessions link back to report and replay pages", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.match(panel, /查看报告/);
  assert.match(panel, /Replay/);
  assert.ok(panel.includes("`/interview/${session.session_id}/report`"));
  assert.ok(panel.includes("`/interview/${session.session_id}/replay`"));
});

test("admin panel exposes persisted interview history", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");
  const api = read("src/lib/api/admin.ts");

  assert.match(api, /InterviewSessionHistory/);
  assert.match(api, /getInterviewSessionsHistory/);
  assert.ok(api.includes("\"/admin/interview-sessions\""));
  assert.match(panel, /HistoricalSessionsCard/);
  assert.match(panel, /历史面试/);
  assert.match(panel, /数据库持久化记录/);
  assert.match(panel, /has_report/);
});

test("admin history uses full date time display", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.match(panel, /formatDateTime/);
  assert.match(panel, /toLocaleDateString/);
  assert.match(panel, /toLocaleTimeString/);
  assert.match(panel, /完整时间/);
});

test("admin history translates database fields into readable UI", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");
  const api = read("src/lib/api/admin.ts");

  assert.match(api, /trace_health/);
  assert.match(panel, /Trace 状态/);
  assert.match(panel, /formatHistoryStatus/);
  assert.match(panel, /Trace 缺失/);
  assert.match(panel, /copyToClipboard\(session.session_id\)/);
  assert.match(panel, /完整 ID/);
}
);

test("admin api client reuses the existing health endpoint", () => {
  const api = read("src/lib/api/admin.ts");

  assert.match(api, /BackendHealth/);
  assert.match(api, /getBackendHealth/);
  assert.ok(api.includes("\"/health\""));
});

test("admin panel surfaces 24h evaluator fallback observability", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");
  const api = read("src/lib/api/admin.ts");

  assert.match(api, /TraceRollupGroupBy = "health" \| "node" \| "verdict" \| "fallback"/);
  assert.match(api, /fallback_rate\?: number/);
  assert.match(api, /affected_sessions\?: number/);
  assert.match(panel, /FallbackRollUp/);
  assert.match(panel, /groupby: "fallback"/);
  assert.match(panel, /评分 fallback（24 小时）/);
  assert.match(panel, /fallback_rate/);
});

test("admin panel surfaces evaluator evidence coverage observability", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");
  const api = read("src/lib/api/admin.ts");

  assert.match(api, /EvidenceRollupResponse/);
  assert.match(api, /getEvidenceRollUp/);
  assert.ok(api.includes("/admin/evidence-rollup?"));
  assert.match(panel, /EvidenceRollUp/);
  assert.match(panel, /评分证据覆盖（24 小时）/);
  assert.match(panel, /acceptance_check_rate/);
  assert.match(panel, /evidence_span_rate/);
  assert.match(panel, /verification_change_rate/);
});

test("admin panel surfaces question quality grounding observability", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");
  const api = read("src/lib/api/admin.ts");

  assert.match(api, /QuestionQualityRollupResponse/);
  assert.match(api, /getQuestionQualityRollUp/);
  assert.ok(api.includes("/admin/question-quality-rollup?"));
  assert.match(panel, /QuestionQualityRollUp/);
  assert.match(panel, /问题质量支撑（24 小时）/);
  assert.match(panel, /contract_rate/);
  assert.match(panel, /retrieval_grounding_rate/);
  assert.match(panel, /avg_acceptance_checks/);
});

test("admin panel surfaces structured question bank controls", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");
  const api = read("src/lib/api/admin.ts");

  assert.match(api, /QuestionSeed/);
  assert.match(api, /direction_tags/);
  assert.match(api, /role_tags/);
  assert.match(api, /QuestionVariant/);
  assert.match(api, /QuestionUsageItem/);
  assert.match(api, /QuestionRerankUsageItem/);
  assert.match(api, /QuestionReviewItem/);
  assert.match(api, /QuestionSeedLintResponse/);
  assert.match(api, /getQuestionSeeds/);
  assert.match(api, /getQuestionSeed/);
  assert.match(api, /getQuestionUsages/);
  assert.match(api, /getQuestionRerankUsages/);
  assert.match(api, /getQuestionReviews/);
  assert.match(api, /createQuestionReview/);
  assert.match(api, /runQuestionSeedLint/);
  assert.match(api, /importQuestionSeeds/);
  assert.match(api, /disableQuestionVariant/);
  assert.ok(api.includes("/admin/question-seeds"));
  assert.ok(api.includes("direction_tag"));
  assert.ok(api.includes("role_tag"));
  assert.ok(api.includes("/admin/question-usages?"));
  assert.ok(api.includes("/admin/question-rerank-usages?limit=100"));
  assert.ok(api.includes("/admin/question-reviews?limit=100"));
  assert.ok(api.includes("/admin/question-seeds/lint"));

  assert.match(panel, /QuestionBankCard/);
  assert.match(panel, /shadow reranker pairwise review/);
  assert.match(panel, /recent question reviews/);
  assert.match(panel, /Strict lint/);
  assert.match(panel, /结构化题库/);
  assert.match(panel, /YAML 导入/);
  assert.match(panel, /最近 question usage/);
  assert.match(panel, /disableQuestionSeed/);
  assert.match(panel, /archiveQuestionVariant/);
});

test("admin panel surfaces DB-backed skills playbook observability only", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");
  const api = read("src/lib/api/admin.ts");

  assert.match(api, /SkillPlaybookCard/);
  assert.match(api, /SkillPlaybooks/);
  assert.match(api, /SkillPlaybookDetail/);
  assert.match(api, /SkillPlaybookImportResult/);
  assert.match(api, /generator_moves: string\[\]/);
  assert.match(api, /evaluator_rubric_hints: string\[\]/);
  assert.match(api, /evaluator_visibility: boolean/);
  assert.match(api, /getSkillPlaybooks/);
  assert.match(api, /getSkillPlaybook/);
  assert.match(api, /importSkillPlaybooks/);
  assert.ok(api.includes("/admin/skill-playbooks"));
  assert.ok(api.includes("direction_tag"));
  assert.ok(api.includes("role_tag"));
  assert.ok(api.includes("dimension"));
  assert.ok(api.includes("archive_missing=true"));

  assert.match(panel, /SkillsPlaybookCard/);
  assert.match(panel, /Skills Playbook/);
  assert.match(panel, /runtime_backend/);
  assert.match(panel, /Import \+ archive missing/);
  assert.match(panel, /body_markdown/);
  assert.match(panel, /Generator moves/);
  assert.match(panel, /Evaluator fields are staged for observation only/);
  assert.match(panel, /<QuestionBankCard[\s\S]*<SkillsPlaybookCard[\s\S]*<StrategiesCard/);
  assert.doesNotMatch(panel, /disableSkillPlaybook/);
  assert.doesNotMatch(panel, /archiveSkillPlaybook/);
});

test("admin panel summarizes interview main-chain quality", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.match(panel, /InterviewQualityOverview/);
  assert.match(panel, /面试主链路质量总览/);
  assert.match(panel, /qualityLevel/);
  assert.match(panel, /fallback_rate/);
  assert.match(panel, /evidence_span_rate/);
  assert.match(panel, /contract_rate/);
});

test("admin rag section labels knowledge and session-anchor panels distinctly", () => {
  const ragEval = read("src/components/admin/RagEvalPanel.tsx");
  const adminPanel = read("src/components/admin/AdminPanel.tsx");
  const anchorCard = read("src/components/admin/CandidateAnchorRagCard.tsx");
  const api = read("src/lib/api/admin.ts");

  assert.match(ragEval, /知识 RAG 评测/);
  assert.doesNotMatch(ragEval, /RAG 检索评测/);
  assert.match(anchorCard, /资料理解 RAG/);
  assert.doesNotMatch(anchorCard, /PgVector/);
  assert.match(anchorCard, /getSessionAnchorRagSummary/);
  assert.match(anchorCard, /getSessionAnchorRagMetrics/);
  assert.match(anchorCard, /deleteSessionAnchorData/);
  assert.match(adminPanel, /RagEvalPanel/);
  assert.match(adminPanel, /CandidateAnchorRagCard/);
  assert.match(adminPanel, /RAG 观察/);
  assert.ok(api.includes("/admin/session-anchors/summary"));
  assert.ok(api.includes("/admin/session-anchors/metrics"));
  assert.ok(api.includes("/admin/sessions/${encodeURIComponent(sessionId)}/anchor-data"));
  assert.match(api, /SessionAnchorRagSummary/);
  assert.match(api, /SessionAnchorRagMetrics/);
});

test("admin panel mounts tab-scoped observability cards only once", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.equal(countMatches(panel, /<SessionsCard\b/g), 1);
  assert.equal(countMatches(panel, /<HistoricalSessionsCard\b/g), 1);
  assert.equal(countMatches(panel, /<RagEvalSection\b/g), 1);
});

test("admin tabs own every module below the tab switcher", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.equal(nearestActiveTabBefore(panel, "<RecentTracesByNode"), "health");
  assert.equal(nearestActiveTabBefore(panel, "<QuestionBankCard"), "strategy");
  assert.equal(nearestActiveTabBefore(panel, "<SkillsPlaybookCard"), "strategy");
  assert.equal(nearestActiveTabBefore(panel, "<StrategiesCard"), "strategy");
});

test("admin tabs carry distinct theme colors into their content panels", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.match(panel, /ADMIN_TAB_THEMES/);
  assert.match(panel, /emerald/);
  assert.match(panel, /sky/);
  assert.match(panel, /amber/);
  assert.match(panel, /AdminTabPanel/);
  assert.match(panel, /--admin-tab-border/);
  assert.match(panel, /--admin-tab-bg/);
  assert.match(panel, /--admin-tab-rail/);
  assert.match(panel, /theme\.tabActive/);
  assert.match(panel, /theme\.iconActive/);
});

test("admin token controls are folded into settings with helper copy", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.match(panel, /settingsOpen/);
  assert.match(panel, /setSettingsOpen/);
  assert.match(panel, /后台设置 \/ 权限/);
  assert.match(panel, /用于访问受保护的后台观测接口，本地开发可留空。/);
  assert.match(panel, /管理员认证令牌/);
  assert.match(panel, /令牌已保存/);
});

test("admin refresh button gives immediate pending feedback", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.match(panel, /refreshing/);
  assert.match(panel, /setRefreshing/);
  assert.match(panel, /刷新中/);
  assert.match(panel, /aria-busy=\{refreshing\}/);
  assert.match(panel, /animate-spin/);
  assert.match(panel, /min-w-\[/);
});
