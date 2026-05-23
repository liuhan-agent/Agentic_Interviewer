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
  assert.match(page, /内存会话和策略记忆/);
  assert.doesNotMatch(page, /活跃会话和策略记忆/);
});

test("admin panel exposes system overview and productized card copy", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.match(panel, /SystemOverview/);
  assert.match(panel, /运行概览/);
  assert.match(panel, /关键后台状态灯/);
  assert.match(panel, /OverviewStatusLight/);
  assert.doesNotMatch(panel, /系统状态总览/);
  assert.match(panel, /运行模式/);
  assert.match(panel, /Trace 采集/);
  assert.match(panel, /LangSmith：/);
  assert.match(panel, /sm:grid-cols-2 md:grid-cols-3/);
  assert.doesNotMatch(panel, /xl:grid-cols-6/);
  assert.match(panel, /Key 已配置/);
  assert.match(panel, /浏览器 Key 已配置/);
  assert.match(panel, /后端默认/);
  assert.match(panel, /return "持久化"/);
  assert.match(panel, /return "内存"/);
  assert.doesNotMatch(panel, /浏览器 Key 已配置 · 环境/);
  assert.doesNotMatch(panel, /。环境：/);
  assert.doesNotMatch(panel, /健康检查：/);
  assert.doesNotMatch(panel, /Checkpoint：Postgres 持久化/);
  assert.doesNotMatch(panel, /无需 Key/);
  assert.doesNotMatch(panel, /label="API"/);
  assert.match(panel, /策略学习/);
  assert.match(panel, /Verifier 监控/);
  assert.match(panel, /drift 观测开关，不代表 Verifier 未运行/);
  assert.match(panel, /内存会话/);
  assert.match(panel, /当前进程保留的会话句柄；超过 60 分钟无用户会话操作后清理，历史记录不受影响/);
  assert.match(panel, /开始一场面试后会出现可追踪会话/);
  assert.doesNotMatch(panel, /未完成会话空闲约 60 分钟会被清理/);
  assert.doesNotMatch(panel, /已完成会话保留到进程重启或主动删除/);
  assert.doesNotMatch(panel, /默认空闲 60 分钟后清理/);
  assert.doesNotMatch(panel, /短暂保留可追踪会话/);
  assert.doesNotMatch(panel, /运行中会话/);
  assert.doesNotMatch(panel, /当前运行中的面试/);
  assert.match(panel, /已入库策略/);
  assert.match(panel, /面试质量入口/);
  assert.match(panel, /active:scale-\[0\.98\]/);
});

test("admin overview status hints render inline without hover-only copy", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.doesNotMatch(panel, /TooltipProvider delayDuration=\{150\}/);
  assert.doesNotMatch(panel, /<TooltipTrigger asChild>/);
  assert.doesNotMatch(panel, /<TooltipContent[\s\S]*?side="bottom"[\s\S]*?align="start"/);
  assert.doesNotMatch(panel, /aria-label=\{`\$\{label\}: \$\{hint\}`\}/);
  assert.doesNotMatch(panel, /type="button"[\s\S]*?aria-label=\{`\$\{label\}: \$\{hint\}`\}/);
  assert.match(panel, /text-\[10px\] font-semibold uppercase tracking-wide/);
  assert.match(panel, /flex min-w-0 flex-wrap items-baseline/);
  assert.match(panel, /min-w-0 break-words font-mono text-sm font-semibold/);
  assert.match(panel, /block break-words text-\[11px\] leading-4 text-muted-foreground/);
  assert.match(panel, /text-\[11px\] leading-4 text-muted-foreground/);
  assert.doesNotMatch(panel, /truncate font-mono text-sm font-semibold/);
  assert.doesNotMatch(panel, /whitespace-nowrap text-\[11px\] leading-4/);
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
  assert.match(api, /total_count\?: number/);
  assert.match(api, /limit\?: number/);
  assert.match(api, /offset\?: number/);
  assert.match(api, /InterviewSessionHistoryFilters/);
  assert.match(api, /status\?: string/);
  assert.match(api, /traceHealth\?: string/);
  assert.match(api, /hasReport\?: boolean/);
  assert.match(api, /since\?: string/);
  assert.match(api, /query\?: string/);
  assert.match(api, /filters\?: InterviewSessionHistoryFilters/);
  assert.match(api, /params\.set\("status", options\.filters\.status\)/);
  assert.match(api, /params\.set\("trace_health", options\.filters\.traceHealth\)/);
  assert.match(api, /params\.set\("has_report", String\(options\.filters\.hasReport\)\)/);
  assert.match(api, /params\.set\("since", options\.filters\.since\)/);
  assert.match(api, /params\.set\("q", options\.filters\.query\)/);
  assert.match(api, /\/admin\/interview-sessions/);
  assert.match(panel, /HistoricalSessionsCard/);
  assert.match(panel, /HISTORY_PAGE_SIZE/);
  assert.match(panel, /HISTORY_SEARCH_DEBOUNCE_MS/);
  assert.match(panel, /historyFilters/);
  assert.match(panel, /debouncedHistoryQuery/);
  assert.match(panel, /useEffect\(\(\) => \{\s*setHistoryPage\(0\);/);
  assert.match(panel, /historyPage/);
  assert.match(panel, /offset: historyPage \* HISTORY_PAGE_SIZE/);
  assert.match(panel, /filters: activeHistoryFilters/);
  assert.match(panel, /onHistoryPageChange/);
  assert.match(panel, /historyPageCount/);
  assert.match(panel, /historyPageStart/);
  assert.match(panel, /ChevronLeft/);
  assert.match(panel, /ChevronRight/);
  assert.match(panel, /历史面试/);
  assert.match(panel, /数据库持久化记录/);
  assert.match(panel, /Trace 状态/);
  assert.match(panel, /报告/);
  assert.match(panel, /时间范围/);
  assert.match(panel, /全量搜索/);
  assert.match(panel, /已筛选/);
  assert.match(panel, /清除筛选条件/);
  assert.match(panel, /has_report/);
  assert.match(panel, /deletedSessionIds/);
  assert.match(panel, /markSessionDeleted/);
  assert.match(panel, /onDeleted\(session\.session_id\)/);
  assert.match(panel, /removeEntry\(session\.session_id\)/);
  assert.match(panel, /@\/lib\/storage\/interviewHistory/);
  assert.match(panel, /historyTotalCount/);
  assert.match(panel, /historyReturnedCount/);
  assert.doesNotMatch(panel, /\{state\.data\.count\} 条/);
  assert.match(panel, /result\.deleted \? "删除成功" : "记录已不存在"/);
  assert.match(panel, /后台没有找到可删除的数据/);
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
  assert.match(panel, /fallbackBadgeLabel/);
  assert.match(panel, /兜底率 \$\{formatPercent\(fallbackRate\)\}/);
  assert.match(panel, /无兜底/);
  assert.match(panel, /兜底率/);
  assert.match(panel, /兜底轮次/);
  assert.match(panel, /影响会话/);
  assert.doesNotMatch(
    panel,
    /<Badge[\s\S]*?>\s*\{formatPercent\(fallbackRate\)\}\s*<\/Badge>/,
  );
  assert.doesNotMatch(panel, /<StatBox label="fallback_rate"/);
  assert.doesNotMatch(panel, /<StatBox label="fallback turns"/);
});

test("admin panel surfaces evaluator evidence coverage observability", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");
  const api = read("src/lib/api/admin.ts");

  assert.match(api, /EvidenceRollupResponse/);
  assert.match(api, /getEvidenceRollUp/);
  assert.ok(api.includes("/admin/evidence-rollup?"));
  assert.match(panel, /EvidenceRollUp/);
  assert.match(panel, /评分证据质量（24 小时）/);
  assert.match(panel, /supportedEvidenceRate/);
  assert.match(panel, /evidenceBadgeLabel/);
  assert.match(panel, /unsupported_yes_rate/);
  assert.match(panel, /评分证据率/);
  assert.match(panel, /无证据通过/);
  assert.match(panel, /评分证据诊断/);
  assert.match(panel, /证据定位率/);
  assert.match(panel, /acceptance_check_rate/);
  assert.match(panel, /evidence_span_rate/);
  assert.match(panel, /verification_change_rate/);
  assert.doesNotMatch(panel, /评分证据覆盖（24 小时）/);
  assert.doesNotMatch(
    panel,
    /<Badge[\s\S]{0,240}\{formatPercent\(data\.evidence_span_rate\)\}[\s\S]{0,240}<\/Badge>/,
  );
});

test("admin panel surfaces question quality grounding observability", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");
  const api = read("src/lib/api/admin.ts");

  assert.match(api, /QuestionQualityRollupResponse/);
  assert.match(api, /getQuestionQualityRollUp/);
  assert.ok(api.includes("/admin/question-quality-rollup?"));
  assert.match(panel, /QuestionQualityRollUp/);
  assert.match(panel, /出题契约质量（24 小时）/);
  assert.match(panel, /出题契约率/);
  assert.doesNotMatch(panel, /问题质量支撑（24 小时）/);
  assert.match(panel, /contract_rate/);
  assert.match(panel, /retrieval_grounding_rate/);
  assert.match(panel, /avg_acceptance_checks/);
});

test("admin scoring tab uses one-column primary diagnostics and lighter secondary sections", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.match(panel, /function AdminScoringSection/);
  assert.match(panel, /aria-label="评分主诊断" className="space-y-6"/);
  assert.match(panel, /<EvidenceRollUp state=\{evidenceRollup\} \/>[\s\S]*<QuestionQualityRollUp state=\{questionQualityRollup\} \/>/);
  assert.doesNotMatch(
    panel,
    /<div className="grid gap-6 lg:grid-cols-2">\s*<EvidenceRollUp[\s\S]*?<QuestionQualityRollUp/,
  );
  assert.match(
    panel,
    /<div className="space-y-6">\s*<DriftCard state=\{drift\} \/>[\s\S]*<RagEvalSection \/>/,
  );
  assert.doesNotMatch(
    panel,
    /<div className="grid gap-6 xl:grid-cols-2">\s*<DriftCard state=\{drift\} \/>[\s\S]*<RagEvalSection \/>/,
  );
  assert.match(panel, /评分二级诊断/);
  assert.match(panel, /复核分歧观测/);
  assert.match(panel, /RAG 观察/);
  assert.match(panel, /观测开启/);
  assert.match(panel, /观测关闭/);
  assert.doesNotMatch(panel, />监控中</);
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
  assert.match(panel, /口径：最近 24h 创建的面试 session/);
  assert.match(panel, /评分兜底来自 final_report/);
  assert.match(panel, /评分证据与出题契约来自 generation_traces/);
  assert.match(panel, /qualityLevel/);
  assert.match(panel, /fallback_rate/);
  assert.match(panel, /evidence_span_rate/);
  assert.match(panel, /contract_rate/);
  assert.match(panel, /评分兜底率/);
  assert.match(panel, /评分证据率/);
  assert.match(panel, /出题契约率/);
  assert.match(panel, /Trace 缺失率/);
  assert.match(panel, /supportedEvidenceRate/);
  assert.match(panel, /evidenceRateValue/);
  assert.match(panel, /unsupported_yes_rate/);
  assert.match(panel, /contractRateValue/);
  assert.match(panel, /无 Trace/);
  assert.match(panel, /无通过项/);
  assert.match(panel, /证据定位率/);
  assert.match(
    panel,
    /function StatBox[\s\S]*font-mono text-\[10px\] tracking-wider text-muted-foreground[\s\S]*\{label\}/,
  );
  assert.doesNotMatch(
    panel,
    /const evidenceRateValue =[\s\S]*formatPercent\(evidenceData\.evidence_span_rate\)/,
  );
  assert.doesNotMatch(
    panel,
    /function StatBox[\s\S]*font-mono text-\[10px\] uppercase tracking-wider text-muted-foreground[\s\S]*\{label\}/,
  );
  assert.doesNotMatch(panel, /<StatBox label="evidence_span_rate"/);
  assert.doesNotMatch(panel, /<StatBox label="contract_rate"/);
  assert.doesNotMatch(panel, /<StatBox label="trace_missing"/);
});

test("admin health tab stacks primary diagnostics and keeps secondary cards lighter", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.match(panel, /<AdminHealthSection[\s\S]*recentTraces=\{recentTraces\}/);
  assert.match(panel, /aria-label="24 小时主链路诊断" className="space-y-6"/);
  assert.doesNotMatch(
    panel,
    /<div className="grid gap-6 lg:grid-cols-2">\s*<TraceHealthRollUp[\s\S]*?<FallbackRollUp/,
  );
  assert.match(panel, /sm:flex-row sm:items-start sm:justify-between/);
  assert.match(panel, /shrink-0 whitespace-nowrap font-mono/);
  assert.match(panel, /grid gap-3 sm:grid-cols-2 xl:grid-cols-3/);
  assert.doesNotMatch(panel, /grid gap-6 lg:grid-cols-2 xl:grid-cols-4/);
  assert.match(panel, /二级诊断/);
  assert.match(panel, /实时 fallback 明细/);
  assert.match(panel, /当前进程暂无 fallback/);
  assert.match(panel, /有新增兜底事件时，这里会按 kind 展开明细/);
  assert.match(panel, /border border-dashed bg-muted\/10 px-3 py-2/);
  assert.doesNotMatch(panel, /自进程启动以来还没有触发 fallback/);
  assert.match(panel, /最近 trace 抽样/);
  assert.match(panel, /RECENT_TRACE_NODE_LABELS/);
  assert.match(panel, /<select/);
  assert.match(panel, /state\.data\.items\.slice\(0, 5\)/);
  assert.doesNotMatch(panel, /RECENT_TRACE_NODES\.map\(\(candidate\)[\s\S]*<Button/);
  assert.doesNotMatch(panel, /sm:grid-cols-2 lg:grid-cols-5/);
});

test("admin rag section labels knowledge and session-anchor panels distinctly", () => {
  const ragEval = read("src/components/admin/RagEvalPanel.tsx");
  const adminPanel = read("src/components/admin/AdminPanel.tsx");
  const anchorCard = read("src/components/admin/CandidateAnchorRagCard.tsx");
  const api = read("src/lib/api/admin.ts");

  assert.match(ragEval, /知识 RAG 评测/);
  assert.match(ragEval, /useState<string>\("24h"\)/);
  assert.match(ragEval, /知识 RAG 评测（\{windowLabel\}）/);
  assert.match(ragEval, /type="button"/);
  assert.match(ragEval, /aria-pressed=\{window === w\}/);
  assert.match(ragEval, /focus-visible:ring-2/);
  assert.doesNotMatch(ragEval, /useState<string>\("7d"\)/);
  assert.doesNotMatch(ragEval, /RAG 检索评测/);
  assert.match(anchorCard, /候选人资料召回（24 小时）/);
  assert.match(anchorCard, /观察简历与自我介绍的切片、向量化和召回命中/);
  assert.match(anchorCard, /getSessionAnchorSessions/);
  assert.match(anchorCard, /一行是一场最近 24 小时创建的面试 session/);
  assert.match(anchorCard, /资料覆盖来自 session_anchor_chunks/);
  assert.match(anchorCard, /召回表现来自 ask_question trace/);
  assert.match(anchorCard, /最近 24h session/);
  assert.match(anchorCard, /有资料切片/);
  assert.match(anchorCard, /有召回命中/);
  assert.match(anchorCard, /有召回兜底/);
  assert.match(anchorCard, /Session/);
  assert.match(anchorCard, /候选人 \/ 岗位/);
  assert.match(anchorCard, /资料覆盖/);
  assert.match(anchorCard, /切片策略/);
  assert.match(anchorCard, /切片数/);
  assert.match(anchorCard, /召回尝试/);
  assert.match(anchorCard, /命中次数/);
  assert.match(anchorCard, /召回命中/);
  assert.match(anchorCard, /延迟 p50 \/ p99/);
  assert.match(anchorCard, /兜底原因/);
  assert.match(anchorCard, /行级删除资料数据/);
  assert.match(anchorCard, /简历：项目结构切片/);
  assert.match(anchorCard, /自我介绍卡片/);
  assert.match(anchorCard, /deleteSessionAnchorData\(selectedSession\.session_id\)/);
  assert.doesNotMatch(anchorCard, /TableGroupRow/);
  assert.doesNotMatch(anchorCard, /资料库覆盖/);
  assert.doesNotMatch(anchorCard, /最近 24h 召回表现/);
  assert.doesNotMatch(anchorCard, /按切片策略（来源内拆分）/);
  assert.doesNotMatch(anchorCard, /资料理解 RAG/);
  assert.doesNotMatch(anchorCard, /PgVector/);
  assert.doesNotMatch(anchorCard, /getSessionAnchorRagSummary/);
  assert.doesNotMatch(anchorCard, /getSessionAnchorRagMetrics/);
  assert.match(anchorCard, /deleteSessionAnchorData/);
  assert.match(api, /SessionAnchorSessionsResponse/);
  assert.match(api, /getSessionAnchorSessions/);
  assert.match(adminPanel, /RagEvalPanel/);
  assert.match(adminPanel, /CandidateAnchorRagCard/);
  assert.match(adminPanel, /RAG 观察/);
  assert.match(
    adminPanel,
    /<div className="space-y-6">\s*<RagEvalPanel \/>[\s\S]*<CandidateAnchorRagCard \/>/,
  );
  assert.doesNotMatch(
    adminPanel,
    /<div className="grid gap-6 xl:grid-cols-2">\s*<RagEvalPanel \/>[\s\S]*<CandidateAnchorRagCard \/>/,
  );
  assert.ok(api.includes("/admin/session-anchors/summary"));
  assert.ok(api.includes("/admin/session-anchors/metrics"));
  assert.ok(api.includes("/admin/session-anchors/sessions?"));
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
