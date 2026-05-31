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
  const questionBankCard = panel.slice(
    panel.indexOf("function QuestionBankCard"),
    panel.indexOf("function QuestionBankFilters"),
  );

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
  assert.match(panel, /QuestionBankFilters/);
  assert.match(panel, /题库筛选/);
  assert.match(questionBankCard, /结构化出题资产/);
  assert.match(questionBankCard, /候选题匹配、题干生成和评分约束/);
  assert.match(questionBankCard, /一个 seed 是一个题目主题/);
  assert.match(questionBankCard, /一个 variant 是该主题下的一种问法\/追问角度/);
  assert.match(questionBankCard, /题目主题/);
  assert.match(questionBankCard, /题目变体/);
  assert.match(questionBankCard, /题库资产概览/);
  assert.match(questionBankCard, /useState\("active"\)/);
  assert.match(questionBankCard, /seedDirection/);
  assert.match(questionBankCard, /seedRole/);
  assert.match(questionBankCard, /questionDirections/);
  assert.match(questionBankCard, /questionRoles/);
  assert.match(questionBankCard, /matchesDirection/);
  assert.match(questionBankCard, /matchesRole/);
  assert.match(panel, /全部方向/);
  assert.match(panel, /全部角色/);
  assert.match(panel, /aria-label="按方向筛选题目主题"/);
  assert.match(panel, /aria-label="按角色筛选题目主题"/);
  assert.match(questionBankCard, /sort\(compareQuestionSeedRows\)/);
  assert.match(questionBankCard, /filteredQuestionSeeds\[0\]/);
  assert.match(questionBankCard, /formatQuestionAssetStatus\(seed\.status\)/);
  assert.match(questionBankCard, /问法：/);
  assert.match(questionBankCard, /难度：/);
  assert.match(questionBankCard, /状态：\{formatQuestionAssetStatus\(variant\.status\)\}/);
  assert.match(questionBankCard, /出题内容/);
  assert.match(questionBankCard, /评分与诊断配置/);
  assert.match(questionBankCard, /选题诊断/);
  assert.match(questionBankCard, /重排分歧观察/);
  assert.match(questionBankCard, /旁路观察/);
  assert.match(questionBankCard, /规则首选/);
  assert.match(questionBankCard, /模型首选/);
  assert.match(questionBankCard, /人工评审样本/);
  assert.match(questionBankCard, /规则更好/);
  assert.match(questionBankCard, /模型更好/);
  assert.match(questionBankCard, /formatQuestionRerankStatus/);
  assert.match(questionBankCard, /formatQuestionRerankDecision/);
  assert.match(questionBankCard, /formatQuestionReviewWinner/);
  assert.match(questionBankCard, /严格检查/);
  assert.match(questionBankCard, /结构化题库/);
  assert.match(questionBankCard, /YAML 导入/);
  assert.match(questionBankCard, /导入 YAML/);
  assert.match(questionBankCard, /归档缺失/);
  assert.match(questionBankCard, /检查/);
  assert.match(questionBankCard, /最近选题记录/);
  assert.match(questionBankCard, /最近出题事件/);
  assert.match(questionBankCard, /displayedQuestionUsageEvents/);
  assert.match(questionBankCard, /groupQuestionUsageEvents/);
  assert.match(questionBankCard, /session_id.*turn_idx.*question_selector_mode/);
  assert.match(panel, /from "@\/components\/interview\/SessionIdTooltip"/);
  assert.match(questionBankCard, /<SessionIdTooltip sessionId=\{event\.session_id\} side="top" \/>/);
  assert.match(questionBankCard, /aria-label="出题事件元信息"/);
  assert.match(questionBankCard, /Session：/);
  assert.match(questionBankCard, /候选 Top/);
  assert.match(questionBankCard, /未采用，不回填/);
  assert.match(questionBankCard, /实际出题/);
  assert.match(questionBankCard, /候选第/);
  assert.match(questionBankCard, /匹配分/);
  assert.match(questionBankCard, /开发详情/);
  assert.match(questionBankCard, /formatQuestionUsageSelectionLabel/);
  assert.match(questionBankCard, /formatQuestionUsageTitle/);
  assert.match(questionBankCard, /groupQuestionUsageEvents\(usages\.data\.usages\)\.slice\(0, 5\)/);
  assert.match(questionBankCard, /sort\(compareQuestionUsageEvents\)/);
  assert.match(
    questionBankCard,
    /questionUsageCreatedAtMs\(b\) - questionUsageCreatedAtMs\(a\)[\s\S]*b\.turn_idx - a\.turn_idx/,
  );
  assert.match(
    questionBankCard,
    /questionRerankCreatedAtMs\(b\) - questionRerankCreatedAtMs\(a\)[\s\S]*b\.turn_idx - a\.turn_idx/,
  );
  assert.match(
    questionBankCard,
    /questionReviewCreatedAtMs\(b\) - questionReviewCreatedAtMs\(a\)[\s\S]*b\.turn_idx - a\.turn_idx/,
  );
  assert.match(questionBankCard, /当前暂无选题调用、重排或评审样本/);
  assert.match(questionBankCard, /完成几轮面试后会出现选题诊断数据/);
  assert.match(questionBankCard, /max-h-\[1440px\] space-y-2 overflow-y-auto/);
  assert.doesNotMatch(questionBankCard, /max-h-\[1680px\] space-y-2 overflow-y-auto/);
  assert.doesNotMatch(questionBankCard, /max-h-\[560px\] space-y-2 overflow-y-auto/);
  assert.doesNotMatch(questionBankCard, /\{variant\.status\}\s*<\/Badge>/);
  assert.doesNotMatch(panel, /最近 question usage/);
  assert.doesNotMatch(questionBankCard, /rank \{usage\.rank\}/);
  assert.doesNotMatch(questionBankCard, /score \{formatMaybeNumber\(usage\.match_score\)\}/);
  assert.doesNotMatch(questionBankCard, /eval \{formatMaybeNumber\(usage\.score\)\}/);
  assert.doesNotMatch(panel, /shadow reranker pairwise review/);
  assert.doesNotMatch(panel, /recent question reviews/);
  assert.doesNotMatch(questionBankCard, /rule \{row\.rule_top_variant_id/);
  assert.doesNotMatch(questionBankCard, /llm \{row\.llm_top_variant_id/);
  assert.doesNotMatch(questionBankCard, /\{review\.winner\}\s*<\/Badge>/);
  assert.doesNotMatch(questionBankCard, /二级诊断/);
  assert.doesNotMatch(questionBankCard, /题目种子/);
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

  const playbookCard = panel.slice(
    panel.indexOf("function SkillsPlaybookCard"),
    panel.indexOf("const StrategiesCard"),
  );

  assert.match(panel, /SkillsPlaybookCard/);
  assert.match(panel, /技能打法库/);
  assert.match(panel, /Markdown 导入/);
  assert.match(panel, /导入并归档缺失/);
  assert.match(playbookCard, /playbookSearch/);
  assert.match(playbookCard, /playbookStatus/);
  assert.match(playbookCard, /playbookDirection/);
  assert.match(playbookCard, /playbookRole/);
  assert.match(playbookCard, /playbookDimension/);
  assert.match(playbookCard, /filteredSkillPlaybooks/);
  assert.match(playbookCard, /SkillPlaybookFilters/);
  assert.match(playbookCard, /打法筛选/);
  assert.match(playbookCard, /打法目录/);
  assert.match(playbookCard, /max-h-\[1040px\]/);
  assert.match(playbookCard, /flex-nowrap gap-1\.5 overflow-hidden/);
  assert.match(playbookCard, /max-w-\[9rem\][^"]*truncate/);
  assert.match(playbookCard, /适用范围/);
  assert.match(playbookCard, /出题指导/);
  assert.doesNotMatch(playbookCard, /出题打法/);
  assert.match(playbookCard, /评分观察/);
  assert.match(playbookCard, /开发详情/);
  assert.match(playbookCard, /正文补充/);
  assert.match(playbookCard, /frontmatter 是运行时读取的主体/);
  assert.match(playbookCard, /formatSkillPlaybookStatus/);
  assert.match(playbookCard, /formatSkillPlaybookBackend/);
  assert.doesNotMatch(playbookCard, /生成器提示/);
  assert.doesNotMatch(playbookCard, /观察字段/);
  assert.doesNotMatch(playbookCard, /全部打法卡/);
  assert.doesNotMatch(playbookCard, /Markdown 原文/);
  assert.doesNotMatch(playbookCard, /PlaybookDetailTab/);
  assert.doesNotMatch(playbookCard, /PlaybookTabButton/);
  assert.doesNotMatch(panel, /Skills Playbook/);
  assert.doesNotMatch(panel, /runtime_backend=/);
  assert.doesNotMatch(panel, /Import \+ archive missing/);
  assert.doesNotMatch(panel, /full body_markdown/);
  assert.doesNotMatch(panel, /Generator moves/);
  assert.doesNotMatch(panel, /Evaluator fields are staged for observation only/);
  assert.doesNotMatch(panel, /slice\(0, 12\)/);
  assert.match(panel, /<QuestionBankCard[\s\S]*<SkillsPlaybookCard[\s\S]*<StrategiesCard/);
  assert.doesNotMatch(panel, /disableSkillPlaybook/);
  assert.doesNotMatch(panel, /archiveSkillPlaybook/);
});

test("admin panel surfaces skill reward shadow readiness", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");
  const api = read("src/lib/api/admin.ts");

  assert.match(api, /SkillUsageStatsItem/);
  assert.match(api, /SkillUsageStatsResponse/);
  assert.match(api, /SkillRewardReadiness/);
  assert.match(api, /getSkillUsageStats/);
  assert.match(api, /refreshSkillUsageStats/);
  assert.match(api, /getSkillRewardReadiness/);
  assert.match(api, /setSkillRewardRollout/);
  assert.ok(api.includes("/admin/skill-usage-stats"));
  assert.ok(api.includes("/admin/skill-usage-stats/refresh"));
  assert.ok(api.includes("/admin/skill-reward-readiness"));
  assert.ok(api.includes("/admin/skill-reward-rollouts/"));

  assert.match(panel, /SkillRewardRolloutPanel/);
  assert.match(panel, /SkillRewardShadowDiagnosticsPanel/);
  assert.doesNotMatch(panel, /function SkillRewardShadowPanel/);
  assert.match(panel, /skillUsageStats/);
  assert.match(panel, /skillRewardReadiness/);
  assert.match(panel, /getSkillUsageStats\(true, \{/);
  assert.match(panel, /offset: skillUsageStatsPage \* SKILL_USAGE_STATS_PAGE_SIZE/);
  assert.match(panel, /getSkillRewardReadiness\(true, signal\)/);
  assert.match(panel, /refreshSkillUsageStats/);
  assert.match(panel, /Skill Reward 排序灰度/);
  assert.match(panel, /Skill Shadow 模拟诊断/);
  assert.match(panel, /Skill Reward 排序模拟/);
  assert.match(panel, /历史 SkillUsage 中出现过、当前仍启用的 Skill 卡片/);
  assert.match(panel, /不改变 retrieve_skills\(\) 的真实返回顺序/);
  assert.match(panel, /匹配规则 Top K/);
  assert.match(panel, /priority、role\/job_level\/dimension\/probe_intent 匹配分/);
  assert.match(panel, /reward 模拟 Top K/);
  assert.match(panel, /样本置信度、使用次数和否决惩罚/);
  assert.match(panel, /Context 级灰度候选/);
  assert.match(panel, /role \/ level \/ dimension \/ probe_intent/);
  assert.match(panel, /默认优先展示已开启、可灰度或排序变化的 context/);
  assert.match(panel, /compareSkillRewardContextReadiness/);
  assert.match(panel, /skillRewardContextPriority/);
  assert.match(panel, /已按灰度价值展示前/);
  assert.match(panel, /单轮实际命中仍以 Trace Explorer 的 ask_question \/ SKILLS 命中为准/);
  assert.match(panel, /开启 reward/);
  assert.match(panel, /回退 shadow/);
  assert.match(panel, /setSkillRewardRollout/);
  assert.match(panel, /SKILL_USAGE_STATS_PAGE_SIZE/);
  assert.match(panel, /SkillUsageStatsList/);
  assert.match(panel, /metadata_top_skill_ids/);
  assert.match(panel, /reward_top_skill_ids/);
  assert.match(panel, /模拟 reward 后 Top K 会变化/);
  assert.match(panel, /reward_shadow/);
});

test("admin strategy tab is a one-column governance console", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");
  const api = read("src/lib/api/admin.ts");
  const banditTable = panel.slice(
    panel.indexOf("function BanditTable"),
    panel.indexOf("function parseBanditStrategyKey"),
  );

  assert.match(panel, /AdminStrategySection/);
  assert.match(panel, /StrategyLearningOverview/);
  assert.match(panel, /策略学习总览/);
  assert.match(panel, /Bandit 后验/);
  assert.match(panel, /题库资产/);
  assert.match(panel, /技能打法/);
  assert.match(panel, /策略记忆/);
  assert.match(panel, /Top 后验策略/);
  assert.match(panel, /上下文 key/);
  assert.match(panel, /策略动作/);
  assert.match(panel, /粒度/);
  assert.match(panel, /后验权重/);
  assert.match(panel, /formatBanditContextLabel/);
  assert.match(panel, /formatBanditActionLabel/);
  assert.match(panel, /getBanditContextGranularity/);
  assert.match(panel, /方向级/);
  assert.match(panel, /全局级/);
  assert.match(panel, /切换维度/);
  assert.match(panel, /深挖追问/);
  assert.match(panel, /开发详情/);
  assert.match(panel, /原始后验参数/);
  assert.match(panel, /策略记忆资产/);
  assert.match(panel, /最近策略使用归因/);
  assert.match(panel, /晋升候选/);
  assert.match(panel, /维护操作/);
  assert.match(api, /importStrategySeeds/);
  assert.ok(api.includes("/admin/strategies/import-seeds"));
  assert.match(panel, /handleSeedImport/);
  assert.match(panel, /导入种子策略/);
  assert.match(panel, /导入种子策略后会刷新策略资产和 Reward 排序就绪度/);
  assert.match(panel, /getStrategyStats\(true, signal\)/);
  assert.match(api, /StrategyRewardReadiness/);
  assert.match(api, /getStrategyRewardReadiness/);
  assert.match(api, /setStrategyRewardRollout/);
  assert.ok(api.includes("/admin/strategy-reward-readiness"));
  assert.ok(api.includes("/admin/strategy-reward-rollouts"));
  assert.match(panel, /StrategyRewardReadinessPanel/);
  assert.match(panel, /Reward 排序就绪度/);
  assert.match(panel, /reward_shadow 只诊断不改线上排序/);
  assert.match(panel, /开启 reward 灰度/);
  assert.match(panel, /回退 shadow/);
  assert.match(panel, /rollout_mode/);
  assert.match(panel, /formatStrategyRewardRolloutMode/);
  assert.match(panel, /metadata_top_strategy_ids/);
  assert.match(panel, /reward_top_strategy_ids/);
  assert.match(panel, /formatStrategyRewardReadiness/);
  assert.match(api, /failure_categories\?: string\[\]/);
  assert.match(api, /body_markdown\?: string/);
  assert.match(api, /display_name_zh\?: string \| null/);
  assert.match(api, /display_description_zh\?: string \| null/);
  assert.match(panel, /strategyDisplayName/);
  assert.match(panel, /strategyDisplayDescription/);
  assert.match(panel, /isPromotedStrategyMemory/);
  assert.match(panel, /strategyOriginBadgeVariant/);
  assert.match(panel, /strategyPromotionStageTone/);
  assert.match(panel, /来源：自动晋升/);
  assert.match(panel, /阶段：低置信晋升/);
  assert.match(panel, /阶段：稳定策略/);
  assert.match(panel, /由 StrategySignal 聚合晋升/);
  assert.match(panel, /启用策略/);
  assert.match(panel, /最近 24h 召回/);
  assert.match(panel, /待晋升信号组/);
  assert.match(panel, /排序模式/);
  assert.match(panel, /统计更新时间/);
  assert.match(panel, /打开模块时会自动补齐过期统计/);
  assert.match(panel, /手动刷新只用于立即同步最新 usage/);
  assert.match(panel, /不会运行晋升/);
  assert.match(panel, /适用范围/);
  assert.match(panel, /StrategyMemoryScopeSummary/);
  assert.match(panel, /StrategyMemoryContextStatsRow/);
  assert.match(panel, /parseStrategyContextKey/);
  assert.match(panel, /key \{row\.context_key\}/);
  assert.match(panel, /推荐动作/);
  assert.match(panel, /证据/);
  assert.match(panel, /策略正文/);
  assert.match(panel, /whitespace-pre-wrap/);
  assert.match(panel, /s\.failure_categories/);
  assert.match(panel, /s\.body_markdown/);
  assert.match(panel, /暂无策略正文/);
  assert.match(panel, /暂无策略使用归因/);
  assert.match(panel, /暂无晋升候选/);
  assert.match(panel, /formatBanditStrategyLabel/);
  assert.match(panel, /buildCanonicalBanditRows/);
  assert.match(panel, /canonicalBanditActionId/);
  assert.match(panel, /按 canonical plan_\* 动作归并/);
  assert.match(panel, /优先展示 plan_\* 后验/);
  assert.match(panel, /key = context_key::action_id/);
  assert.match(panel, /context_key 由方向、级别、维度组成/);
  assert.match(panel, /BANDIT_RAW_DETAILS_PAGE_SIZE = 50/);
  assert.match(panel, /BANDIT_RAW_DETAILS_FILTER_OPTIONS/);
  assert.match(panel, /全部字段/);
  assert.match(panel, /context_key/);
  assert.match(panel, /action_id/);
  assert.match(panel, /canonical_action/);
  assert.match(panel, /原始键（context_key::action_id）/);
  assert.match(panel, /输入关键词/);
  assert.match(panel, /banditRawDetailsSearchValues/);
  assert.match(panel, /显示 \{visibleRawRows\.length\} \/ 共 \{filteredRawRows\.length\} 条/);
  assert.match(panel, /显示更多/);
  assert.match(banditTable, /filteredRawRows = rows\.filter/);
  assert.match(banditTable, /rawDetailsFilterField/);
  assert.match(banditTable, /选择原始后验筛选字段/);
  assert.match(banditTable, /visibleRawRows = filteredRawRows\.slice/);
  assert.match(banditTable, /\{r\.contextKey\}/);
  assert.match(banditTable, /font-mono[\s\S]*\{r\.contextKey\}/);
  assert.match(banditTable, /\{r\.canonicalActionId\}/);
  assert.match(banditTable, /font-mono[\s\S]*\{r\.canonicalActionId\}/);
  assert.match(panel, /启用 \/ 总数/);
  assert.match(panel, /题目 \/ 变体/);
  assert.match(panel, /策略记忆 \/ 归因/);
  assert.match(panel, /严格检查/);
  assert.match(panel, /置信度/);
  assert.match(panel, /支持样本/);
  assert.match(panel, /即时奖励/);
  assert.doesNotMatch(
    panel,
    /<AdminTabPanel theme=\{ADMIN_TAB_THEMES\.strategy\}>\s*<BanditCard/,
  );
  assert.doesNotMatch(banditTable, />上下文<\/th>/);
  assert.doesNotMatch(panel, />context::action<\/th>/);
  assert.doesNotMatch(banditTable, />策略<\/th>/);
  assert.doesNotMatch(banditTable, />样本<\/th>/);
  assert.doesNotMatch(panel, />α<\/th>/);
  assert.doesNotMatch(panel, />β<\/th>/);
  assert.doesNotMatch(
    panel,
    /mt-0\.5 min-w-0 truncate font-mono text-\[10px\] text-muted-foreground">\s*\{r\.key\}/,
  );
  assert.doesNotMatch(panel, /active \/ total/);
  assert.doesNotMatch(panel, /seed \/ variant/);
  assert.doesNotMatch(panel, /策略记忆 \/ usage/);
  assert.doesNotMatch(panel, /当前策略/);
  assert.doesNotMatch(panel, /信号与使用归因/);
  assert.doesNotMatch(panel, /晋升控制/);
  assert.doesNotMatch(panel, /暂无晋升信号/);
  assert.doesNotMatch(panel, /Strict lint/);
  assert.doesNotMatch(panel, /confidence \{formatMaybeNumber/);
  assert.doesNotMatch(panel, /support \{s\.support_count/);
  assert.doesNotMatch(panel, /quality: \{s\.quality_reason\}/);
  assert.doesNotMatch(panel, /failure:<\/span>/);
  assert.doesNotMatch(banditTable, /formatBanditActionLabel\(actionId \|\| key\)/);
  assert.doesNotMatch(panel, /display_label/);
  assert.doesNotMatch(panel, /中文说明/);
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
  assert.match(anchorCard, /把资料库覆盖、ask_question 召回、实际注入 Prompt 分开看/);
  assert.match(anchorCard, /具体知识块请进 Trace Explorer/);
  assert.match(anchorCard, /getSessionAnchorSessions/);
  assert.match(anchorCard, /切片数来自 setup_snapshot/);
  assert.match(anchorCard, /召回表现来自 ask_question trace/);
  assert.doesNotMatch(anchorCard, /资料覆盖来自 session_anchor_chunks/);
  assert.match(anchorCard, /资料库覆盖/);
  assert.match(anchorCard, /最近 24h ask_question 召回/);
  assert.match(anchorCard, /实际注入 Prompt/);
  assert.match(anchorCard, /xl:min-h-\[5\.25rem\]/);
  assert.match(anchorCard, /最近 session 样本/);
  assert.match(anchorCard, /最近 24h session/);
  assert.match(anchorCard, /有资料切片/);
  assert.match(anchorCard, /有召回命中/);
  assert.match(anchorCard, /有召回兜底/);
  assert.match(anchorCard, /注入轮次/);
  assert.match(anchorCard, /命中未注入/);
  assert.match(anchorCard, /注入来源/);
  assert.match(anchorCard, /Session/);
  assert.match(anchorCard, /候选人 \/ 岗位/);
  assert.match(anchorCard, /资料准备/);
  assert.match(anchorCard, /召回表现/);
  assert.match(anchorCard, /Prompt 注入/);
  assert.match(anchorCard, /简历切片/);
  assert.match(anchorCard, /自介切片/);
  assert.match(anchorCard, /命中片段：/);
  assert.match(anchorCard, /注入片段：/);
  assert.match(anchorCard, /buildSessionAnchorRollup/);
  assert.match(anchorCard, /prompt_injected_turns/);
  assert.match(anchorCard, /retrieved_not_injected_turns/);
  assert.match(anchorCard, /prompt_source_counts/);
  assert.match(anchorCard, /query_embedding_timeout/);
  assert.match(anchorCard, /session_anchor_bind_missing/);
  assert.match(anchorCard, /no_bound_chunks/);
  assert.match(anchorCard, /resume: "简历"/);
  assert.match(anchorCard, /self_intro: "自我介绍"/);
  assert.match(anchorCard, /function formatSourceHits[\s\S]*return "无";/);
  assert.doesNotMatch(anchorCard, /简历命中/);
  assert.doesNotMatch(anchorCard, /自介命中/);
  assert.match(anchorCard, /行级删除资料数据/);
  assert.match(anchorCard, /SessionIdTooltip/);
  assert.match(anchorCard, /简历：项目结构切片/);
  assert.match(anchorCard, /自我介绍卡片/);
  assert.match(anchorCard, /deleteSessionAnchorData\(selectedSession\.session_id\)/);
  assert.doesNotMatch(anchorCard, /复制 session id/);
  assert.doesNotMatch(anchorCard, /handleCopySessionId/);
  assert.doesNotMatch(anchorCard, /navigator\.clipboard/);
  assert.doesNotMatch(anchorCard, /<th className="px-3 py-2 font-medium">资料覆盖<\/th>/);
  assert.doesNotMatch(anchorCard, /<th className="px-3 py-2 font-medium">切片策略<\/th>/);
  assert.doesNotMatch(anchorCard, /<th className="px-3 py-2 font-medium">切片数<\/th>/);
  assert.doesNotMatch(anchorCard, /<th className="px-3 py-2 font-medium">召回轮次<\/th>/);
  assert.doesNotMatch(anchorCard, /<th className="px-3 py-2 font-medium">命中轮次<\/th>/);
  assert.doesNotMatch(anchorCard, /<th className="px-3 py-2 font-medium">轮次命中率<\/th>/);
  assert.doesNotMatch(anchorCard, /<th className="px-3 py-2 font-medium">延迟 p50 \/ p99<\/th>/);
  assert.doesNotMatch(anchorCard, /<th className="px-3 py-2 font-medium">兜底原因<\/th>/);
  assert.doesNotMatch(anchorCard, /TableGroupRow/);
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

test("admin panel surfaces question reward shadow readiness", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");
  const api = read("src/lib/api/admin.ts");

  assert.match(api, /QuestionUsageStatsItem/);
  assert.match(api, /QuestionUsageStatsResponse/);
  assert.match(api, /QuestionRewardReadiness/);
  assert.match(api, /QuestionRewardRollout/);
  assert.match(api, /QuestionRewardReadinessGroup/);
  assert.match(api, /getQuestionUsageStats/);
  assert.match(api, /refreshQuestionUsageStats/);
  assert.match(api, /getQuestionRewardReadiness/);
  assert.match(api, /setQuestionRewardRollout/);
  assert.ok(api.includes("/admin/question-usage-stats"));
  assert.ok(api.includes("/admin/question-usage-stats/refresh"));
  assert.ok(api.includes("/admin/question-reward-readiness"));
  assert.ok(api.includes("/admin/question-reward-rollouts/"));

  assert.match(panel, /QuestionRewardRolloutPanel/);
  assert.match(panel, /QuestionRewardShadowDiagnosticsPanel/);
  assert.match(panel, /questionUsageStats/);
  assert.match(panel, /questionRewardReadiness/);
  assert.match(panel, /QUESTION_USAGE_STATS_PAGE_SIZE/);
  assert.match(panel, /questionUsageStatsPage/);
  assert.match(panel, /setQuestionUsageStatsPage/);
  assert.match(panel, /getQuestionUsageStats\(true, \{/);
  assert.match(panel, /offset: questionUsageStatsPage \* QUESTION_USAGE_STATS_PAGE_SIZE/);
  assert.match(panel, /getQuestionRewardReadiness\(true, signal\)/);
  assert.match(panel, /refreshQuestionUsageStats/);
  assert.match(panel, /题库 Reward 排序灰度/);
  assert.match(panel, /全局总览/);
  assert.match(panel, /全局题库排序模拟/);
  assert.match(panel, /范围：全局/);
  assert.match(panel, /不直接开启 live 排序/);
  assert.match(panel, /backendKey="scope"/);
  assert.match(panel, /不切换 structured_primary/);
  assert.match(panel, /历史 QuestionUsage 中出现过、当前仍启用的题目变体/);
  assert.match(panel, /Context 级灰度候选/);
  assert.match(panel, /范围：direction \/ role \/ level \/ dimension/);
  assert.match(panel, /这里才是 context 级 reward 灰度开关/);
  assert.match(panel, /静态优先级 Top K/);
  assert.match(panel, /按 seed\.priority \+ variant\.priority 排序/);
  assert.match(panel, /reward 模拟 Top K/);
  assert.match(panel, /叠加历史 reward、样本置信度和使用次数/);
  assert.match(panel, /metadata_top_variant_ids/);
  assert.match(panel, /reward_top_variant_ids/);
  assert.match(panel, /selector_rollout_mode/);
  assert.match(panel, /reward_ranking_mode/);
  assert.match(panel, /QuestionRewardTopKList/);
  assert.doesNotMatch(panel, /modes\.map/);
  assert.doesNotMatch(panel, /mode\.metadata_top_variant_ids/);
  assert.doesNotMatch(panel, /mode\.reward_top_variant_ids/);
  assert.match(panel, /readinessData\.metadata_top_variant_ids/);
  assert.match(panel, /readinessData\.reward_top_variant_ids/);
  assert.match(panel, /QuestionUsageStatsList/);
  assert.match(
    panel,
    /<summary className="cursor-pointer text-xs font-medium text-muted-foreground">\s*question_usage_stats\s*<\/summary>/,
  );
  assert.match(panel, /第 \{currentPage\} \/ \{totalPages\} 页 · 已加载/);
  assert.match(panel, /上一页/);
  assert.match(panel, /下一页/);
  assert.match(api, /limit\?: number/);
  assert.match(api, /offset\?: number/);
  assert.match(panel, /row\.variant_id/);
  assert.match(panel, /row\.injected_uses/);
  assert.match(panel, /row\.avg_score/);
  assert.match(panel, /row\.last_used_at/);
  assert.match(panel, /context 只按历史 usage 分组/);
  assert.match(panel, /不重放单轮 resume anchor \/ skills \/ qa_history 等动态匹配条件/);
  assert.match(panel, /row\.question_selector_mode/);
  assert.match(panel, /QuestionRewardContextReadinessList/);
  assert.match(panel, /Context 级灰度候选/);
  assert.match(panel, /reward 排序灰度/);
  assert.match(panel, /开启 reward/);
  assert.match(panel, /回退 shadow/);
  assert.match(panel, /seedReadinessById/);
  assert.match(panel, /QuestionSeedRewardReadinessPanel/);
  assert.match(panel, /Seed 内 Variant 灰度/);
  assert.match(panel, /范围：当前 Seed/);
  assert.match(panel, /不按 context 分组/);
  assert.match(panel, /active variants/);
  assert.match(panel, /onQuestionRewardRollout/);
  assert.match(panel, /setQuestionRewardRollout/);
  assert.match(panel, /scope === "context"/);
  assert.match(panel, /scope === "seed"/);
  assert.match(
    panel,
    /<QuestionRewardRolloutPanel[\s\S]*<QuestionRewardShadowDiagnosticsPanel/,
  );
});

test("admin tabs own every module below the tab switcher", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.equal(nearestActiveTabBefore(panel, "<RecentTracesByNode"), "health");
  assert.equal(nearestActiveTabBefore(panel, "<AdminStrategySection"), "strategy");
  assert.match(panel, /function AdminStrategySection[\s\S]*<QuestionBankCard/);
  assert.match(panel, /function AdminStrategySection[\s\S]*<SkillsPlaybookCard/);
  assert.match(panel, /function AdminStrategySection[\s\S]*<StrategiesCard/);
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

test("admin tabs persist the last selected section across reloads", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.match(panel, /ADMIN_ACTIVE_TAB_STORAGE_KEY/);
  assert.match(panel, /agentic-interviewer:admin-active-tab/);
  assert.match(panel, /function isAdminTabId/);
  assert.match(panel, /function loadStoredAdminTab/);
  assert.match(panel, /window\.localStorage\.getItem\(ADMIN_ACTIVE_TAB_STORAGE_KEY\)/);
  assert.match(panel, /useState<AdminTabId>\("health"\)/);
  assert.match(panel, /const storedTab = loadStoredAdminTab\(\)/);
  assert.match(panel, /setActiveTab\(storedTab\)/);
  assert.match(panel, /function handleTabChange\(tab: AdminTabId\)/);
  assert.match(panel, /window\.localStorage\.setItem\(ADMIN_ACTIVE_TAB_STORAGE_KEY, tab\)/);
  assert.match(panel, /onClick=\{\(\) => handleTabChange\(theme\.id\)\}/);
  assert.doesNotMatch(panel, /onClick=\{\(\) => setActiveTab\(theme\.id\)\}/);
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
