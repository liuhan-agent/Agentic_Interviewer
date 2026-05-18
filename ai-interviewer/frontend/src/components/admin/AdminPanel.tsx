"use client";

import Link from "next/link";
import React, { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  BookMarked,
  Clock,
  ClipboardList,
  Copy,
  Cpu,
  ExternalLink,
  History,
  Key,
  Loader2,
  Play,
  RefreshCw,
  Search,
  Trash2,
  Waypoints,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { CandidateAnchorRagCard } from "@/components/admin/CandidateAnchorRagCard";
import { RagEvalPanel } from "@/components/admin/RagEvalPanel";
import {
  FALLBACK_KIND_DESCRIPTIONS,
  FALLBACK_KIND_LABELS,
  FALLBACK_KIND_ORDER,
  getAdminSessions,
  getBackendHealth,
  getBanditSnapshot,
  getEvidenceRollUp,
  getFallbackRates,
  getInterviewSessionsHistory,
  getQuestionQualityRollUp,
  getQuestionRerankUsages,
  getQuestionReviews,
  getQuestionSeed,
  getQuestionSeeds,
  getQuestionUsages,
  getRecentTracesByNode,
  getSkillPlaybook,
  getSkillPlaybooks,
  getStrategySignals,
  getStrategyStats,
  getStrategyUsages,
  getStrategies,
  getTraceRollUp,
  getVerifierDrift,
  importSkillPlaybooks,
  importQuestionSeeds,
  runQuestionSeedLint,
  loadAdminToken,
  archiveQuestionSeed,
  archiveQuestionVariant,
  archiveStrategy,
  disableQuestionSeed,
  disableQuestionVariant,
  disableStrategy,
  createQuestionReview,
  refreshStrategyStats,
  runStrategyPromotion,
  saveAdminToken,
  type AdminSessions,
  type BackendHealth,
  type BanditSnapshot,
  type EvidenceRollupResponse,
  type FallbackKind,
  type FallbackRatesResponse,
  type InterviewSessionHistory,
  type InterviewSessionHistoryItem,
  type QuestionSeedDetail,
  type QuestionSeeds,
  type QuestionRerankUsages,
  type QuestionReviews,
  type QuestionUsages,
  type QuestionQualityRollupResponse,
  type RecentTracesResponse,
  type SkillPlaybookDetail,
  type SkillPlaybooks,
  type Strategies,
  type StrategySignals,
  type StrategyStats,
  type StrategyUsages,
  type TraceRollupResponse,
  type VerifierDriftSnapshot,
} from "@/lib/api/admin";
import { adminDeleteSession } from "@/lib/api/admin";
import { useToast } from "@/lib/hooks/useToast";
import { cn } from "@/lib/utils";

// Auto-refresh cadence keeps the panel useful as a passive dashboard
// without hammering the backend; 15s strikes the same balance the
// /health dot in the header uses.
const REFRESH_INTERVAL_MS = 15_000;

type Loadable<T> =
  | { phase: "loading" }
  | { phase: "ready"; data: T }
  | { phase: "error"; message: string };

function useAutoFetch<T>(
  fetcher: (signal?: AbortSignal) => Promise<T>,
  refreshKey: number,
): Loadable<T> {
  const [state, setState] = useState<Loadable<T>>({ phase: "loading" });

  useEffect(() => {
    const ctrl = new AbortController();
    setState((prev) =>
      prev.phase === "ready" ? prev : { phase: "loading" },
    );
    fetcher(ctrl.signal)
      .then((data) => {
        if (ctrl.signal.aborted) return;
        setState({ phase: "ready", data });
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setState({
          phase: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      });
    return () => ctrl.abort();
  }, [fetcher, refreshKey]);

  return state;
}

export function AdminPanel() {
  const [tokenInput, setTokenInput] = useState("");
  const [tokenSaved, setTokenSaved] = useState("");
  const [tick, setTick] = useState(0);
  const [recentNode, setRecentNode] = useState<string>("evaluator");

  useEffect(() => {
    const t = loadAdminToken();
    setTokenInput(t);
    setTokenSaved(t);
  }, []);

  useEffect(() => {
    const id = window.setInterval(
      () => setTick((t) => t + 1),
      REFRESH_INTERVAL_MS,
    );
    return () => window.clearInterval(id);
  }, []);

  // ``tokenSaved`` is the value we actually fetch against; editing
  // the input does not refetch until the operator clicks Save. That
  // keeps mid-typing requests from flooding the backend with 403s.
  const healthFetcher = useCallback(
    (signal?: AbortSignal) => getBackendHealth(signal),
    [],
  );
  const banditFetcher = useCallback(
    (signal?: AbortSignal) => getBanditSnapshot(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const driftFetcher = useCallback(
    (signal?: AbortSignal) => getVerifierDrift(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const sessionsFetcher = useCallback(
    (signal?: AbortSignal) => getAdminSessions(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const historyFetcher = useCallback(
    (signal?: AbortSignal) => getInterviewSessionsHistory(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const strategiesFetcher = useCallback(
    (signal?: AbortSignal) => getStrategies(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const skillPlaybooksFetcher = useCallback(
    (signal?: AbortSignal) => getSkillPlaybooks(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const questionSeedsFetcher = useCallback(
    (signal?: AbortSignal) => getQuestionSeeds(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const questionUsagesFetcher = useCallback(
    (signal?: AbortSignal) => getQuestionUsages(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const questionRerankUsagesFetcher = useCallback(
    (signal?: AbortSignal) => getQuestionRerankUsages(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const questionReviewsFetcher = useCallback(
    (signal?: AbortSignal) => getQuestionReviews(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const strategySignalsFetcher = useCallback(
    (signal?: AbortSignal) => getStrategySignals(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const strategyUsagesFetcher = useCallback(
    (signal?: AbortSignal) => getStrategyUsages(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const strategyStatsFetcher = useCallback(
    (signal?: AbortSignal) => getStrategyStats(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const traceRollupFetcher = useCallback(
    (signal?: AbortSignal) => getTraceRollUp({ since: "24h", groupby: "health" }, signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const fallbackRollupFetcher = useCallback(
    (signal?: AbortSignal) => getTraceRollUp({ since: "24h", groupby: "fallback" }, signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const evidenceRollupFetcher = useCallback(
    (signal?: AbortSignal) => getEvidenceRollUp({ since: "24h" }, signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const questionQualityRollupFetcher = useCallback(
    (signal?: AbortSignal) => getQuestionQualityRollUp({ since: "24h" }, signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );
  const recentTracesFetcher = useCallback(
    (signal?: AbortSignal) =>
      getRecentTracesByNode({ node: recentNode, limit: 30 }, signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved, recentNode],
  );
  const fallbackRatesFetcher = useCallback(
    (signal?: AbortSignal) => getFallbackRates(signal),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [tokenSaved],
  );

  const health = useAutoFetch(healthFetcher, tick);
  const bandit = useAutoFetch(banditFetcher, tick);
  const drift = useAutoFetch(driftFetcher, tick);
  const sessions = useAutoFetch(sessionsFetcher, tick);
  const history = useAutoFetch(historyFetcher, tick);
  const strategies = useAutoFetch(strategiesFetcher, tick);
  const skillPlaybooks = useAutoFetch(skillPlaybooksFetcher, tick);
  const questionSeeds = useAutoFetch(questionSeedsFetcher, tick);
  const questionUsages = useAutoFetch(questionUsagesFetcher, tick);
  const questionRerankUsages = useAutoFetch(questionRerankUsagesFetcher, tick);
  const questionReviews = useAutoFetch(questionReviewsFetcher, tick);
  const strategySignals = useAutoFetch(strategySignalsFetcher, tick);
  const strategyUsages = useAutoFetch(strategyUsagesFetcher, tick);
  const strategyStats = useAutoFetch(strategyStatsFetcher, tick);
  const traceRollup = useAutoFetch(traceRollupFetcher, tick);
  const fallbackRollup = useAutoFetch(fallbackRollupFetcher, tick);
  const evidenceRollup = useAutoFetch(evidenceRollupFetcher, tick);
  const questionQualityRollup = useAutoFetch(questionQualityRollupFetcher, tick);
  const recentTraces = useAutoFetch(recentTracesFetcher, tick);
  const fallbackRates = useAutoFetch(fallbackRatesFetcher, tick);

  function handleSaveToken() {
    saveAdminToken(tokenInput);
    setTokenSaved(tokenInput);
    setTick((t) => t + 1);
  }

  return (
    <div className="space-y-6">
      <TokenBar
        tokenInput={tokenInput}
        setTokenInput={setTokenInput}
        onSave={handleSaveToken}
        tokenSaved={tokenSaved}
        onRefresh={() => setTick((t) => t + 1)}
      />

      <SystemOverview
        health={health}
        bandit={bandit}
        drift={drift}
        sessions={sessions}
        strategies={strategies}
      />

      <InterviewQualityOverview
        trace={traceRollup}
        fallback={fallbackRollup}
        evidence={evidenceRollup}
        question={questionQualityRollup}
      />

      <div className="grid gap-6 lg:grid-cols-2 xl:grid-cols-4">
        <TraceHealthRollUp state={traceRollup} />
        <FallbackRollUp state={fallbackRollup} />
        <EvidenceRollUp state={evidenceRollup} />
        <QuestionQualityRollUp state={questionQualityRollup} />
      </div>

      <FallbackKindCounts state={fallbackRates} />

      <div className="grid gap-6 lg:grid-cols-2">
        <BanditCard state={bandit} />
        <DriftCard state={drift} />
      </div>

      <RecentTracesByNode
        state={recentTraces}
        node={recentNode}
        onNodeChange={setRecentNode}
      />

      <SessionsCard state={sessions} />
      <HistoricalSessionsCard state={history} onRefresh={() => setTick((t) => t + 1)} />
      <QuestionBankCard
        state={questionSeeds}
        usages={questionUsages}
        rerankUsages={questionRerankUsages}
        reviews={questionReviews}
        onRefresh={() => setTick((t) => t + 1)}
      />
      <SkillsPlaybookCard
        state={skillPlaybooks}
        onRefresh={() => setTick((t) => t + 1)}
      />
      <StrategiesCard
        state={strategies}
        signals={strategySignals}
        usages={strategyUsages}
        stats={strategyStats}
        onRefresh={() => setTick((t) => t + 1)}
      />
      <RagEvalSection />
    </div>
  );
}

// TraceHealthRollUp pins the answer to "今日有多少场面试 trace 健康 / 部分 / 缺失"
// at the top of the dashboard. The 15s auto-refresh keeps it useful as
// a passive ops indicator; degraded states bubble up via the badge
// colour so the operator does not have to scroll the long sessions
// table to notice.
const HEALTH_LABEL: Record<string, string> = {
  complete: "完整",
  partial: "部分",
  missing: "缺失",
};
const HEALTH_TONE: Record<string, "success" | "warn" | "destructive" | "outline"> = {
  complete: "success",
  partial: "warn",
  missing: "destructive",
};

function InterviewQualityOverview({
  trace,
  fallback,
  evidence,
  question,
}: {
  trace: Loadable<TraceRollupResponse>;
  fallback: Loadable<TraceRollupResponse>;
  evidence: Loadable<EvidenceRollupResponse>;
  question: Loadable<QuestionQualityRollupResponse>;
}) {
  if (
    trace.phase === "loading" ||
    fallback.phase === "loading" ||
    evidence.phase === "loading" ||
    question.phase === "loading"
  ) {
    return <Skeleton className="h-28 w-full" />;
  }
  const errors = [trace, fallback, evidence, question].filter(
    (s): s is { phase: "error"; message: string } => s.phase === "error",
  );
  if (errors.length > 0) {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="space-y-1 pt-6 text-sm">
          <p className="font-medium text-destructive">面试主链路质量总览加载失败</p>
          <p className="text-xs text-muted-foreground">{errors[0].message}</p>
        </CardContent>
      </Card>
    );
  }
  if (
    trace.phase !== "ready" ||
    fallback.phase !== "ready" ||
    evidence.phase !== "ready" ||
    question.phase !== "ready"
  ) {
    return null;
  }

  const traceData = trace.data;
  const fallbackData = fallback.data;
  const evidenceData = evidence.data;
  const questionData = question.data;
  const missingTraceShare = bucketShare(traceData, "missing");
  const partialTraceShare = bucketShare(traceData, "partial");
  const qualityLevel =
    missingTraceShare > 0 ||
    (fallbackData.fallback_rate ?? 0) >= 0.3 ||
    evidenceData.evidence_span_rate < 0.5 ||
    questionData.contract_rate < 0.8
      ? "red"
      : partialTraceShare > 0 ||
          (fallbackData.fallback_rate ?? 0) > 0 ||
          evidenceData.evidence_span_rate < 0.8 ||
          questionData.contract_rate < 0.95
        ? "yellow"
        : "green";
  const tone =
    qualityLevel === "green" ? "success" : qualityLevel === "yellow" ? "warn" : "destructive";
  const label =
    qualityLevel === "green" ? "健康" : qualityLevel === "yellow" ? "关注" : "风险";

  return (
    <Card className={qualityLevel === "red" ? "border-destructive/40 bg-destructive/5" : ""}>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Activity className="h-4 w-4 text-emerald-400" />
              面试主链路质量总览
            </CardTitle>
            <CardDescription className="mt-1">
              汇总 Trace 健康、fallback、评分证据和问题质量支撑，先做运营预警，不替代人工抽查。
            </CardDescription>
          </div>
          <Badge variant={tone} className="font-mono">
            {label}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="grid gap-3 md:grid-cols-4">
        <StatBox label="fallback_rate" value={formatPercent(fallbackData.fallback_rate ?? 0)} />
        <StatBox
          label="evidence_span_rate"
          value={formatPercent(evidenceData.evidence_span_rate)}
        />
        <StatBox label="contract_rate" value={formatPercent(questionData.contract_rate)} />
        <StatBox label="trace_missing" value={formatPercent(missingTraceShare)} />
      </CardContent>
    </Card>
  );
}

function TraceHealthRollUp({ state }: { state: Loadable<TraceRollupResponse> }) {
  if (state.phase === "loading") {
    return <Skeleton className="h-24 w-full" />;
  }
  if (state.phase === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="space-y-1 pt-6 text-sm">
          <p className="font-medium text-destructive">Trace 健康度加载失败</p>
          <p className="text-xs text-muted-foreground">{state.message}</p>
        </CardContent>
      </Card>
    );
  }
  const data = state.data;
  const totalForShare = data.buckets.reduce((sum, b) => sum + b.count, 0) || 1;
  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Activity className="h-4 w-4 text-emerald-400" />
              Trace 健康度（24 小时）
            </CardTitle>
            <CardDescription className="mt-1">
              聚合最近 24 小时的 generation_traces 与 interview_sessions，颜色与 Trace Explorer 一致。
            </CardDescription>
          </div>
          <Badge variant="outline" className="font-mono text-[10px]">
            共 {data.total_sessions} 场
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {data.total_sessions === 0 ? (
          <p className="text-sm text-muted-foreground">
            过去 24 小时还没有面试记录。等一场面试跑完后这里会出现统计。
          </p>
        ) : (
          <div className="grid gap-3 md:grid-cols-3">
            {data.buckets.map((bucket) => (
              <div key={bucket.key} className="rounded-lg border bg-card/50 p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="text-xs text-muted-foreground">
                    {HEALTH_LABEL[bucket.key] ?? bucket.key}
                  </p>
                  <Badge variant={HEALTH_TONE[bucket.key] ?? "outline"}>
                    {Math.round((bucket.count / totalForShare) * 100)}%
                  </Badge>
                </div>
                <p className="text-2xl font-semibold">{bucket.count}</p>
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {bucket.key === "complete"
                    ? "走完整闭环（评分 + 学习节点 + completed）"
                    : bucket.key === "partial"
                      ? "节点缺失或会话未到 completed"
                      : bucket.key === "missing"
                        ? "无任何 generation_traces 行"
                        : "其它"}
                </p>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function bucketShare(data: TraceRollupResponse, key: string): number {
  return data.buckets.find((bucket) => bucket.key === key)?.share ?? 0;
}

function FallbackRollUp({ state }: { state: Loadable<TraceRollupResponse> }) {
  if (state.phase === "loading") {
    return <Skeleton className="h-24 w-full" />;
  }
  if (state.phase === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="space-y-1 pt-6 text-sm">
          <p className="font-medium text-destructive">评分 fallback 加载失败</p>
          <p className="text-xs text-muted-foreground">{state.message}</p>
        </CardContent>
      </Card>
    );
  }
  const data = state.data;
  const fallbackRate = data.fallback_rate ?? 0;
  const affectedSessions = data.affected_sessions ?? 0;
  const fallbackTurns = data.fallback_turns ?? 0;
  const totalTurns = data.total_turns ?? 0;
  return (
    <Card className={fallbackRate >= 0.3 ? "border-amber-500/40 bg-amber-500/[0.04]" : ""}>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-4 w-4 text-amber-300" />
              评分 fallback（24 小时）
            </CardTitle>
            <CardDescription className="mt-1">
              聚合 final_report 的 evaluator_fallback_count，观察评估模型是否持续退化。
            </CardDescription>
          </div>
          <Badge variant={fallbackRate >= 0.3 ? "warn" : "outline"} className="font-mono">
            {formatPercent(fallbackRate)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {data.total_sessions === 0 ? (
          <p className="text-sm text-muted-foreground">
            过去 24 小时还没有可统计的面试报告。
          </p>
        ) : (
          <div className="grid gap-3 md:grid-cols-3">
            <StatBox label="fallback turns" value={`${fallbackTurns}/${totalTurns}`} />
            <StatBox label="affected sessions" value={`${affectedSessions}/${data.total_sessions}`} />
            <StatBox label="fallback_rate" value={formatPercent(fallbackRate)} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// FallbackKindCounts shows the in-process per-kind fallback Counter
// (since process boot). It complements the trace-database
// ``FallbackRollUp`` above, which only counts evaluator turns from
// the last 24h. By breaking the count down per *kind* we let the
// operator answer "which fallback is firing right now?" without
// scraping Prometheus.
//
// Tone is set per-kind so a spike in any single kind stays visible
// at a glance: safety→destructive, language→info-blue,
// duplicate→accent-purple, contract_unsigned→amber,
// evaluator_fallback→warning-yellow.
const FALLBACK_KIND_TONE: Record<FallbackKind, string> = {
  safety: "border-red-500/40 bg-red-500/[0.06]",
  language: "border-sky-500/40 bg-sky-500/[0.06]",
  duplicate: "border-purple-500/40 bg-purple-500/[0.06]",
  contract_unsigned: "border-amber-500/40 bg-amber-500/[0.06]",
  evaluator_fallback: "border-yellow-500/40 bg-yellow-500/[0.06]",
};
const FALLBACK_KIND_TEXT: Record<FallbackKind, string> = {
  safety: "text-red-400",
  language: "text-sky-400",
  duplicate: "text-purple-400",
  contract_unsigned: "text-amber-400",
  evaluator_fallback: "text-yellow-400",
};

function FallbackKindCounts({ state }: { state: Loadable<FallbackRatesResponse> }) {
  if (state.phase === "loading") {
    return <Skeleton className="h-32 w-full" />;
  }
  if (state.phase === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <AlertTriangle className="h-4 w-4 text-destructive" />
            Fallback 详细计数加载失败
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs text-muted-foreground">{state.message}</p>
        </CardContent>
      </Card>
    );
  }
  const counts = state.data.fallback_counts ?? {};
  const knownTotal = FALLBACK_KIND_ORDER.reduce(
    (sum, kind) => sum + (counts[kind] ?? 0),
    0,
  );
  const extraEntries = Object.entries(counts).filter(
    ([kind]) => !(FALLBACK_KIND_ORDER as readonly string[]).includes(kind),
  );
  const extraTotal = extraEntries.reduce((sum, [, n]) => sum + n, 0);
  const grandTotal = knownTotal + extraTotal;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-4 w-4 text-amber-300" />
              Fallback 详细计数（实时）
            </CardTitle>
            <CardDescription className="mt-1">
              进程启动以来按 kind 拆分的兜底计数器，与上方 24 小时 trace
              聚合互补：这里看「当下哪一类 fallback 在涨」，上方看「过去
              24 小时谁受影响」。重启进程会清零，长期趋势请看 Prometheus。
            </CardDescription>
          </div>
          <Badge
            variant={grandTotal > 0 ? "warn" : "outline"}
            className="font-mono text-[10px]"
          >
            合计 {grandTotal}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {grandTotal === 0 ? (
          <p className="text-sm text-muted-foreground">
            自进程启动以来还没有触发任何 fallback。这通常是好事——所有
            generator / evaluator 输出都直通了 happy path。
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            {FALLBACK_KIND_ORDER.map((kind) => {
              const count = counts[kind] ?? 0;
              const share = grandTotal > 0 ? count / grandTotal : 0;
              return (
                <FallbackKindBox
                  key={kind}
                  kind={kind}
                  count={count}
                  share={share}
                />
              );
            })}
          </div>
        )}
        {extraEntries.length > 0 && (
          <div className="mt-3 rounded-lg border border-dashed border-amber-500/40 bg-amber-500/[0.04] p-3">
            <p className="mb-1.5 text-[11px] font-medium text-amber-300">
              发现未知 kind（疑似拼写漂移或新增类别，请确认）
            </p>
            <ul className="flex flex-wrap gap-1.5">
              {extraEntries.map(([kind, count]) => (
                <li key={kind}>
                  <Badge variant="outline" className="font-mono text-[10px]">
                    {kind} · {count}
                  </Badge>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function FallbackKindBox({
  kind,
  count,
  share,
}: {
  kind: FallbackKind;
  count: number;
  share: number;
}) {
  const sharePct = Math.round(share * 100);
  const tone = count > 0 ? FALLBACK_KIND_TONE[kind] : "";
  const textTone = count > 0 ? FALLBACK_KIND_TEXT[kind] : "text-foreground/70";
  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-lg border bg-card/50 p-3 transition-colors",
        tone,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium">{FALLBACK_KIND_LABELS[kind]}</span>
        <Badge variant="outline" className="font-mono text-[10px] tabular-nums">
          {sharePct}%
        </Badge>
      </div>
      <div className={cn("font-mono text-2xl font-semibold tabular-nums", textTone)}>
        {count}
      </div>
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        {FALLBACK_KIND_DESCRIPTIONS[kind]}
      </p>
      <div className="h-1 w-full overflow-hidden rounded-full bg-muted/40">
        <div
          className={cn(
            "h-full rounded-full transition-all",
            count > 0 ? "bg-current opacity-70" : "bg-muted-foreground/30",
            textTone,
          )}
          style={{ width: `${Math.min(100, Math.max(count > 0 ? 6 : 0, sharePct))}%` }}
        />
      </div>
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground/60">
        {kind}
      </span>
    </div>
  );
}

function EvidenceRollUp({ state }: { state: Loadable<EvidenceRollupResponse> }) {
  if (state.phase === "loading") {
    return <Skeleton className="h-24 w-full" />;
  }
  if (state.phase === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="space-y-1 pt-6 text-sm">
          <p className="font-medium text-destructive">评分证据加载失败</p>
          <p className="text-xs text-muted-foreground">{state.message}</p>
        </CardContent>
      </Card>
    );
  }
  const data = state.data;
  return (
    <Card className={data.evidence_span_rate < 0.5 ? "border-amber-500/40 bg-amber-500/[0.04]" : ""}>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <ClipboardList className="h-4 w-4 text-blue-300" />
              评分证据覆盖（24 小时）
            </CardTitle>
            <CardDescription className="mt-1">
              聚合 evaluator / verification trace，检查评分是否有 contract 与证据支撑。
            </CardDescription>
          </div>
          <Badge variant={data.evidence_span_rate < 0.5 ? "warn" : "outline"} className="font-mono">
            {formatPercent(data.evidence_span_rate)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {data.total_evaluator_traces === 0 ? (
          <p className="text-sm text-muted-foreground">
            过去 24 小时还没有 evaluator trace 可统计。
          </p>
        ) : (
          <div className="grid gap-3 md:grid-cols-3">
            <StatBox
              label="acceptance_check_rate"
              value={formatPercent(data.acceptance_check_rate)}
            />
            <StatBox
              label="evidence_span_rate"
              value={formatPercent(data.evidence_span_rate)}
            />
            <StatBox
              label="verification_change_rate"
              value={formatPercent(data.verification_change_rate)}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function QuestionQualityRollUp({
  state,
}: {
  state: Loadable<QuestionQualityRollupResponse>;
}) {
  if (state.phase === "loading") {
    return <Skeleton className="h-24 w-full" />;
  }
  if (state.phase === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="space-y-1 pt-6 text-sm">
          <p className="font-medium text-destructive">问题质量加载失败</p>
          <p className="text-xs text-muted-foreground">{state.message}</p>
        </CardContent>
      </Card>
    );
  }
  const data = state.data;
  return (
    <Card className={data.contract_rate < 0.8 ? "border-amber-500/40 bg-amber-500/[0.04]" : ""}>
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <BookMarked className="h-4 w-4 text-purple-300" />
              问题质量支撑（24 小时）
            </CardTitle>
            <CardDescription className="mt-1">
              聚合 ask_question trace，检查题目是否有 contract、RAG 与技能聚焦支撑。
            </CardDescription>
          </div>
          <Badge variant={data.contract_rate < 0.8 ? "warn" : "outline"} className="font-mono">
            {formatPercent(data.contract_rate)}
          </Badge>
        </div>
      </CardHeader>
      <CardContent>
        {data.total_ask_question_traces === 0 ? (
          <p className="text-sm text-muted-foreground">
            过去 24 小时还没有 ask_question trace 可统计。
          </p>
        ) : (
          <div className="grid gap-3 md:grid-cols-3">
            <StatBox label="contract_rate" value={formatPercent(data.contract_rate)} />
            <StatBox
              label="retrieval_grounding_rate"
              value={formatPercent(data.retrieval_grounding_rate)}
            />
            <StatBox
              label="avg_acceptance_checks"
              value={data.avg_acceptance_checks.toFixed(1)}
            />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// RecentTracesByNode: reverse-lookup card. Lets the operator pivot
// from "node X is misbehaving" to "show me the last N runs of node X
// and let me click into any one's Trace Explorer", instead of having
// to enumerate sessions first.
const RECENT_TRACE_NODES = [
  "evaluator",
  "director_sample",
  "verification",
  "reward_update",
  "route_decision",
  "final_report",
  "ask_question",
  "compress_context",
  "refine_followup",
  "training_plan",
  "experience_extractor",
  "resume_parse",
] as const;

function RecentTracesByNode({
  state,
  node,
  onNodeChange,
}: {
  state: Loadable<RecentTracesResponse>;
  node: string;
  onNodeChange: (next: string) => void;
}) {
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Activity className="h-4 w-4 text-emerald-400" />
              最近 trace（按节点）
            </CardTitle>
            <CardDescription className="mt-1">
              从 generation_traces 反查最近 30 条记录；点行可跳到该会话的 Trace Explorer。
            </CardDescription>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {RECENT_TRACE_NODES.map((candidate) => (
              <Button
                key={candidate}
                size="sm"
                variant={candidate === node ? "default" : "outline"}
                className="h-7 px-2 text-[11px]"
                onClick={() => onNodeChange(candidate)}
              >
                {candidate}
              </Button>
            ))}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {state.phase === "loading" ? (
          <Skeleton className="h-24 w-full" />
        ) : state.phase === "error" ? (
          <p className="text-sm text-destructive">
            加载失败：{state.message}
          </p>
        ) : state.data.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            还没有 {node} 节点的 trace 记录。
          </p>
        ) : (
          <ul className="divide-y text-sm">
            {state.data.items.map((item) => (
              <li
                key={item.id}
                className="flex flex-wrap items-center justify-between gap-2 py-2"
              >
                <div className="min-w-0 space-y-0.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge variant="outline" className="font-mono text-[10px]">
                      {item.node}
                    </Badge>
                    {item.dimension && (
                      <span className="text-xs text-muted-foreground">
                        {item.dimension}
                      </span>
                    )}
                    {typeof item.score === "number" && (
                      <Badge variant={item.passed ? "success" : "warn"}>
                        {item.score.toFixed(1)}
                      </Badge>
                    )}
                  </div>
                  <p className="truncate font-mono text-[11px] text-muted-foreground">
                    {item.session_id}
                    {typeof item.turn_idx === "number" && ` · turn ${item.turn_idx}`}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[11px] text-muted-foreground">
                    {item.created_at
                      ? new Date(item.created_at).toLocaleTimeString()
                      : "—"}
                  </span>
                  <Button asChild size="sm" variant="ghost" className="h-7 px-2 text-xs">
                    <Link
                      href={`/admin/trace?sessionId=${encodeURIComponent(
                        item.session_id,
                      )}&node=${encodeURIComponent(item.node)}${
                        item.dimension
                          ? `&dimension=${encodeURIComponent(item.dimension)}`
                          : ""
                      }`}
                    >
                      Trace
                    </Link>
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function SystemOverview({
  health,
  bandit,
  drift,
  sessions,
  strategies,
}: {
  health: Loadable<BackendHealth>;
  bandit: Loadable<BanditSnapshot>;
  drift: Loadable<VerifierDriftSnapshot>;
  sessions: Loadable<AdminSessions>;
  strategies: Loadable<Strategies>;
}) {
  const apiLabel =
    health.phase === "ready"
      ? `${health.data.status ?? "ok"} · ${health.data.env ?? "dev"}`
      : phaseLabel(health);
  const runtimeLabel =
    health.phase === "ready"
      ? `${health.data.checkpoint_backend ?? "unknown"} · ${
          health.data.llm_provider ?? "llm"
        }${health.data.stub_mode === "True" ? " stub" : ""}`
      : "等待健康检查";
  const armCount =
    bandit.phase === "ready" ? Object.keys(bandit.data.priors || {}).length : null;
  const driftLabel =
    drift.phase === "ready"
      ? drift.data.enabled
        ? `${drift.data.samples ?? 0} 个样本`
        : "已关闭"
      : phaseLabel(drift);
  const sessionCount = sessions.phase === "ready" ? sessions.data.count : null;
  const strategyCount = strategies.phase === "ready" ? strategies.data.count : null;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Activity className="h-4 w-4 text-emerald-400" />
              系统状态总览
            </CardTitle>
            <CardDescription className="mt-1">
              把后台技术指标翻译成可展示的运行状态，便于连接用户侧质量中心和开发者调试视图。
            </CardDescription>
          </div>
          <Button asChild variant="outline" size="sm" className="h-8 gap-1.5 text-xs">
        <Link href="/interview/history">面试质量入口</Link>
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <OverviewTile label="API" value={apiLabel} hint={runtimeLabel} />
          <OverviewTile
            label="策略学习"
            value={armCount === null ? phaseLabel(bandit) : `${armCount} 个臂`}
            hint="Thompson 策略后验"
          />
          <OverviewTile label="评分复核" value={driftLabel} hint="Verifier 漂移窗口" />
          <OverviewTile
            label="活跃会话"
            value={sessionCount === null ? phaseLabel(sessions) : `${sessionCount} 个`}
            hint="跑完一场面试后会出现"
          />
          <OverviewTile
            label="策略记忆"
            value={strategyCount === null ? phaseLabel(strategies) : `${strategyCount} 条`}
            hint="Generator 可复用经验"
          />
        </div>
      </CardContent>
    </Card>
  );
}

function OverviewTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="rounded-lg border bg-card/50 p-3">
      <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 text-sm font-medium">{value}</div>
      <div className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
        {hint}
      </div>
    </div>
  );
}

function phaseLabel(state: Loadable<unknown>): string {
  if (state.phase === "loading") return "加载中";
  if (state.phase === "error") return "连接异常";
  return "已连接";
}

// ---------------------------------------------------------------------------
// Token bar — the server-side check is optional (empty ``api_token``
// means "dev: leave the admin routes open"), so we treat the token as
// a helper, not a blocker.
// ---------------------------------------------------------------------------

function TokenBar({
  tokenInput,
  setTokenInput,
  onSave,
  tokenSaved,
  onRefresh,
}: {
  tokenInput: string;
  setTokenInput: (v: string) => void;
  onSave: () => void;
  tokenSaved: string;
  onRefresh: () => void;
}) {
  return (
    <Card>
      <CardContent className="flex flex-col gap-3 pt-6 sm:flex-row sm:items-center">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Key className="h-3.5 w-3.5" />
          <span>管理员认证令牌</span>
        </div>
        <Input
          type="password"
          placeholder="本地开发可留空"
          value={tokenInput}
          onChange={(e) => setTokenInput(e.target.value)}
          className="sm:max-w-xs"
        />
        <Button
          size="sm"
          variant={tokenInput !== tokenSaved ? "default" : "outline"}
          onClick={onSave}
          className={
            tokenInput !== tokenSaved
              ? "bg-emerald-600 hover:bg-emerald-500 text-white"
              : ""
          }
        >
          保存
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={onRefresh}
          className="gap-1.5"
          aria-label={`每 ${REFRESH_INTERVAL_MS / 1000} 秒自动刷新`}
        >
          <RefreshCw className="h-3.5 w-3.5" />
          刷新
        </Button>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Bandit posteriors
// ---------------------------------------------------------------------------

function BanditCard({ state }: { state: Loadable<BanditSnapshot> }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Cpu className="h-4 w-4 text-emerald-400" />
              策略学习（Thompson）
            </CardTitle>
            <CardDescription className="mt-1">
              系统正在学习不同提问策略在不同岗位和能力维度下的效果。
            </CardDescription>
          </div>
          {state.phase === "ready" && (
            <Badge variant="outline" className="font-mono text-[10px]">
              {Object.keys(state.data.priors || {}).length} 个臂
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {state.phase === "loading" && <LoadingList rows={4} />}
        {state.phase === "error" && <ErrorBox message={state.message} />}
        {state.phase === "ready" && (
          <div className="space-y-3">
            <PolicyMeta snapshot={state.data} />
            <Separator />
            <BanditTable priors={state.data.priors || {}} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PolicyMeta({ snapshot }: { snapshot: BanditSnapshot }) {
  return (
    <div className="flex flex-wrap gap-2 text-xs">
      <MetaPill label="模式" value={snapshot.policy_mode ?? "—"} />
      <MetaPill
        label="探索率"
        value={
          typeof snapshot.exploration_rate === "number"
            ? snapshot.exploration_rate.toFixed(3)
            : "—"
        }
      />
      <MetaPill
        label="衰减"
        value={
          snapshot.decay?.enabled
            ? `factor=${snapshot.decay?.factor ?? "-"} · floor=${
                snapshot.decay?.floor ?? "-"
              } · every ${snapshot.decay?.interval_days ?? "-"}d`
            : "关闭"
        }
      />
    </div>
  );
}

function BanditTable({
  priors,
}: {
  priors: Record<string, { alpha: number; beta: number }>;
}) {
  const rows = Object.entries(priors)
    .map(([key, { alpha, beta }]) => {
      const mean = alpha / (alpha + beta || 1);
      return { key, alpha, beta, mean };
    })
    .sort((a, b) => b.mean - a.mean);

  if (rows.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        暂无后验数据，这不是错误。跑完一场面试后会出现 context::arm 策略学习数据。
      </p>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border">
      <table className="w-full text-xs">
        <thead className="bg-secondary/50 text-[10px] uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-3 py-2 text-left">context::arm</th>
            <th className="px-3 py-2 text-right">α</th>
            <th className="px-3 py-2 text-right">β</th>
            <th className="px-3 py-2 text-right">均值</th>
            <th className="px-3 py-2">后验</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t">
              <td className="px-3 py-2 font-mono text-foreground">{r.key}</td>
              <td className="px-3 py-2 text-right font-mono tabular-nums">
                {r.alpha.toFixed(2)}
              </td>
              <td className="px-3 py-2 text-right font-mono tabular-nums">
                {r.beta.toFixed(2)}
              </td>
              <td className="px-3 py-2 text-right font-mono tabular-nums">
                {r.mean.toFixed(3)}
              </td>
              <td className="px-3 py-2">
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
                  <div
                    className="h-full bg-emerald-400/70"
                    style={{
                      width: `${Math.max(0, Math.min(100, r.mean * 100))}%`,
                    }}
                  />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Verifier drift
// ---------------------------------------------------------------------------

function DriftCard({ state }: { state: Loadable<VerifierDriftSnapshot> }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <AlertTriangle className="h-4 w-4 text-amber-400" />
              评分复核
            </CardTitle>
            <CardDescription className="mt-1">
              评估器和复核器的分歧监控，用来发现评分偏宽、偏严或证据不足。
            </CardDescription>
          </div>
          {state.phase === "ready" && (
            <Badge
              variant={state.data.enabled ? "success" : "outline"}
              className="font-mono text-[10px]"
            >
              {state.data.enabled ? "监控中" : "关闭"}
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {state.phase === "loading" && <LoadingList rows={4} />}
        {state.phase === "error" && <ErrorBox message={state.message} />}
        {state.phase === "ready" && <DriftBody snapshot={state.data} />}
      </CardContent>
    </Card>
  );
}

function DriftBody({ snapshot }: { snapshot: VerifierDriftSnapshot }) {
  const rate = (n?: number) =>
    typeof n === "number" ? `${(n * 100).toFixed(1)}%` : "—";

  if (!snapshot.samples) {
    return (
      <p className="text-xs text-muted-foreground">
        暂无复核样本，这不是错误。跑完一场面试后会出现评分复核窗口数据。
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-2 text-xs">
        <StatBox label="样本数" value={String(snapshot.samples ?? 0)} />
        <StatBox label="推翻率" value={rate(snapshot.override_rate)} />
        <StatBox label="弃权率" value={rate(snapshot.abstain_rate)} />
      </div>
      <div className="flex flex-wrap gap-2 text-xs">
        <MetaPill
          label="窗口"
          value={String(snapshot.window_size ?? "—")}
        />
        <MetaPill
          label="跨度缺失"
          value={rate(snapshot.span_miss_rate)}
        />
      </div>

      {snapshot.per_verdict && Object.keys(snapshot.per_verdict).length > 0 && (
        <div>
          <div className="mb-1.5 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
            按裁定
          </div>
          <div className="flex gap-2 text-xs">
            {Object.entries(snapshot.per_verdict).map(([v, n]) => (
              <MetaPill key={v} label={v} value={String(n)} />
            ))}
          </div>
        </div>
      )}

      {snapshot.per_dimension && Object.keys(snapshot.per_dimension).length > 0 && (
        <div>
          <div className="mb-1.5 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
            按维度
          </div>
          <div className="overflow-x-auto rounded-lg border border-border/60">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border/40 bg-muted/30">
                  <th className="px-2 py-1.5 text-left text-[10px] font-medium text-muted-foreground">维度</th>
                  <th className="px-2 py-1.5 text-right text-[10px] font-medium text-muted-foreground">样本</th>
                  <th className="px-2 py-1.5 text-right text-[10px] font-medium text-muted-foreground">推翻率</th>
                  <th className="px-2 py-1.5 text-right text-[10px] font-medium text-muted-foreground">弃权率</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/30">
                {Object.entries(snapshot.per_dimension)
                  .sort(([, a], [, b]) => (b.override_rate ?? 0) - (a.override_rate ?? 0))
                  .map(([dim, d]) => (
                    <tr key={dim} className="hover:bg-muted/20">
                      <td className="px-2 py-1.5 font-mono text-emerald-400/80">{dim.replaceAll("_", " ")}</td>
                      <td className="px-2 py-1.5 text-right tabular-nums">{d.calls ?? 0}</td>
                      <td className={cn(
                        "px-2 py-1.5 text-right font-mono tabular-nums",
                        (d.override_rate ?? 0) >= 0.25 ? "text-red-400" : (d.override_rate ?? 0) >= 0.1 ? "text-amber-400" : "text-foreground/70",
                      )}>
                        {rate(d.override_rate)}
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono tabular-nums text-foreground/70">{rate(d.abstain_rate)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {snapshot.overruled_patterns && snapshot.overruled_patterns.length > 0 && (
        <div>
          <div className="mb-1.5 text-[10px] font-mono uppercase tracking-wider text-muted-foreground">
            主要推翻模式
          </div>
          <ul className="space-y-1.5 text-xs">
            {snapshot.overruled_patterns.slice(0, 5).map((p, i) => (
              <li
                key={i}
                className="rounded border bg-card/50 px-3 py-2"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-mono text-emerald-400/80">
                    {p.dimension ?? "—"}
                  </span>
                  <span className="font-mono tabular-nums">×{p.count ?? 0}</span>
                </div>
                <div className="mt-0.5 text-muted-foreground">{p.check}</div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Active sessions
// ---------------------------------------------------------------------------

const SessionsCard = React.memo(function SessionsCard({ state }: { state: Loadable<AdminSessions> }) {
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Clock className="h-4 w-4 text-emerald-400" />
              活跃会话
            </CardTitle>
            <CardDescription className="mt-1">
              当前后端持有的面试会话，可从这里定位报告和质量中心。
            </CardDescription>
          </div>
          {state.phase === "ready" && (
            <Badge variant="outline" className="font-mono text-[10px]">
              {state.data.count} 个会话
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {state.phase === "loading" && <LoadingList rows={3} />}
        {state.phase === "error" && <ErrorBox message={state.message} />}
        {state.phase === "ready" && state.data.sessions.length === 0 && (
          <p className="text-xs text-muted-foreground">
            会话管理器中暂无会话，这不是错误。跑完一场面试后会出现可追踪会话。
          </p>
        )}
        {state.phase === "ready" && state.data.sessions.length > 0 && (
          <>
            {/* Desktop Table View */}
            <div className="hidden md:block overflow-x-auto rounded-lg border">
              <table className="min-w-[760px] w-full text-xs">
                <thead className="bg-secondary/50 text-[10px] uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 text-left">会话</th>
                    <th className="px-3 py-2 text-left">追踪</th>
                    <th className="px-3 py-2 text-left">LangSmith</th>
                    <th className="px-3 py-2 text-right">轮次</th>
                    <th className="px-3 py-2">状态</th>
                    <th className="px-3 py-2 text-left">创建时间</th>
                    <th className="px-3 py-2 text-left">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {state.data.sessions.map((session) => (
                    <tr key={session.session_id} className="border-t">
                      <td className="px-3 py-2 font-mono">
                        {truncate(session.session_id)}
                      </td>
                      <td className="px-3 py-2 font-mono text-muted-foreground">
                        {truncate(session.trace_id)}
                      </td>
                      <td className="px-3 py-2">
                        <LangSmithCell
                          session={session}
                          langsmith={state.data.langsmith}
                        />
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums">
                        {session.turn_idx}
                      </td>
                      <td className="px-3 py-2">
                        <SessionStatusBadge session={session} />
                      </td>
                      <td className="px-3 py-2 font-mono text-muted-foreground">
                        <TimeCell iso={session.created_at} />
                      </td>
                      <td className="px-3 py-2">
                        <SessionLinks session={session} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Mobile Card Stack View */}
            <div className="grid gap-3 md:hidden">
              {state.data.sessions.map((session) => (
                <div key={session.session_id} className="flex flex-col gap-2 rounded-lg border bg-card/50 p-3 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-foreground font-medium">{truncate(session.session_id)}</span>
                    <SessionStatusBadge session={session} />
                  </div>
                  <div className="flex items-center justify-between text-muted-foreground">
                    <span>轮次: <span className="font-mono text-foreground">{session.turn_idx}</span></span>
                    <span className="font-mono">{formatDateTime(session.created_at)}</span>
                  </div>
                  <div className="pt-2 border-t mt-1 flex items-center justify-between">
                    <span className="text-[10px] text-muted-foreground">Trace: {truncate(session.trace_id)}</span>
                    <LangSmithCell session={session} langsmith={state.data.langsmith} />
                  </div>
                  <SessionLinks session={session} />
                </div>
              ))}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
});

function SessionLinks({ session }: { session: { session_id: string } }) {
  return (
    <div className="flex items-center justify-end gap-1.5">
      <Button asChild size="sm" variant="outline" className="h-7 gap-1.5 px-3 text-[11px]">
        <Link href={`/interview/${session.session_id}/report`}>
          <ClipboardList className="h-3 w-3" />
          报告
        </Link>
      </Button>
      <Button asChild size="sm" variant="ghost" className="h-7 gap-1 px-2.5 text-[11px] text-muted-foreground hover:text-foreground">
        <Link href={`/interview/${session.session_id}/replay`}>
          <Play className="h-3 w-3" />
          Replay
        </Link>
      </Button>
      <Button asChild size="sm" variant="ghost" className="h-7 gap-1 px-2.5 text-[11px] text-muted-foreground hover:text-foreground">
        <Link href={`/admin/trace?sessionId=${session.session_id}`}>
          <Waypoints className="h-3 w-3" />
          Trace
        </Link>
      </Button>
    </div>
  );
}

const HistoricalSessionsCard = React.memo(function HistoricalSessionsCard({
  state,
  onRefresh,
}: {
  state: Loadable<InterviewSessionHistory>;
  onRefresh: () => void;
}) {
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [searchText, setSearchText] = useState("");

  const { filteredSessions, statusCounts, totalCount } = React.useMemo(() => {
    if (state.phase !== "ready")
      return {
        filteredSessions: [] as InterviewSessionHistory["sessions"],
        statusCounts: {} as Record<string, number>,
        totalCount: 0,
      };
    const counts: Record<string, number> = {};
    for (const s of state.data.sessions) {
      counts[s.status] = (counts[s.status] || 0) + 1;
    }
    let sessions = state.data.sessions;
    if (statusFilter !== "all") {
      sessions = sessions.filter((s) => s.status === statusFilter);
    }
    if (searchText.trim()) {
      const q = searchText.toLowerCase();
      sessions = sessions.filter(
        (s) =>
          s.candidate_name?.toLowerCase().includes(q) ||
          s.job_title?.toLowerCase().includes(q) ||
          s.session_id.toLowerCase().includes(q),
      );
    }
    return {
      filteredSessions: sessions,
      statusCounts: counts,
      totalCount: state.data.sessions.length,
    };
  }, [state, statusFilter, searchText]);

  const filterTabs: { key: string; label: string; count?: number }[] = [
    { key: "all", label: "全部", count: totalCount },
    { key: "completed", label: "已完成", count: statusCounts["completed"] },
    { key: "cancelled", label: "已取消", count: statusCounts["cancelled"] },
    { key: "errored", label: "出错", count: statusCounts["errored"] },
  ];

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/10">
                <History className="h-4 w-4 text-emerald-400" />
              </div>
              历史面试
            </CardTitle>
            <CardDescription className="mt-1">
              数据库持久化记录，后端重启后仍可用于查看报告和回放。
            </CardDescription>
          </div>
          {state.phase === "ready" && (
            <Badge variant="outline" className="font-mono text-xs tabular-nums">
              {state.data.count} 条
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {state.phase === "loading" && <LoadingList rows={4} />}
        {state.phase === "error" && <ErrorBox message={state.message} />}
        {state.phase === "ready" && state.data.sessions.length === 0 && (
          <p className="text-xs text-muted-foreground">
            暂无数据库持久化记录。完成或取消一场面试后会出现在这里。
          </p>
        )}
        {state.phase === "ready" && state.data.sessions.length > 0 && (
          <div className="space-y-3">
            {/* Filter & Search bar */}
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-0.5 rounded-lg bg-muted/50 p-0.5">
                {filterTabs.map((tab) => (
                  <button
                    key={tab.key}
                    type="button"
                    onClick={() => setStatusFilter(tab.key)}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-all duration-200",
                      statusFilter === tab.key
                        ? "bg-background text-foreground shadow-sm scale-[1.02]"
                        : "text-muted-foreground hover:text-foreground hover:bg-background/50",
                    )}
                  >
                    {tab.label}
                    {typeof tab.count === "number" && tab.count > 0 && (
                      <span
                        className={cn(
                          "font-mono text-[10px] tabular-nums",
                          statusFilter === tab.key
                            ? "text-foreground/60"
                            : "text-muted-foreground/50",
                        )}
                      >
                        {tab.count}
                      </span>
                    )}
                  </button>
                ))}
              </div>
              <div className="relative w-full sm:w-56">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  type="text"
                  placeholder="搜索候选人、岗位…"
                  value={searchText}
                  onChange={(e) => setSearchText(e.target.value)}
                  className="h-8 pl-8 text-xs"
                />
              </div>
            </div>

            {filteredSessions.length === 0 ? (
              <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border/60 py-10 text-sm text-muted-foreground">
                <Search className="mb-3 h-8 w-8 text-muted-foreground/20" />
                <p>没有匹配的面试记录</p>
                <p className="mt-1 text-[11px] text-muted-foreground/50">
                  {statusFilter !== "all" && `状态筛选：${filterTabs.find((t) => t.key === statusFilter)?.label}`}
                  {statusFilter !== "all" && searchText && " · "}
                  {searchText && `搜索："${searchText}"`}
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setStatusFilter("all");
                    setSearchText("");
                  }}
                  className="mt-3 rounded-md bg-muted px-3 py-1.5 text-xs text-foreground/70 transition-colors hover:bg-muted/80"
                >
                  清除筛选条件
                </button>
              </div>
            ) : (
              <>
                {/* Desktop Table */}
                <div className="hidden md:block rounded-xl border border-border/60 bg-background/50">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-border/60 bg-muted/40">
                        <th className="whitespace-nowrap px-3 py-3 text-left text-[11px] font-semibold text-muted-foreground">会话</th>
                        <th className="px-3 py-3 text-left text-[11px] font-semibold text-muted-foreground">岗位</th>
                        <th className="whitespace-nowrap px-3 py-3 text-left text-[11px] font-semibold text-muted-foreground">候选人</th>
                        <th className="whitespace-nowrap px-3 py-3 text-center text-[11px] font-semibold text-muted-foreground">分数</th>
                        <th className="whitespace-nowrap px-3 py-3 text-center text-[11px] font-semibold text-muted-foreground">状态 / Trace 状态</th>
                        <th className="whitespace-nowrap px-3 py-3 text-center text-[11px] font-semibold text-muted-foreground">LLM 调用</th>
                        <th className="whitespace-nowrap px-3 py-3 text-left text-[11px] font-semibold text-muted-foreground">时间</th>
                        <th className="whitespace-nowrap px-3 py-3 text-center text-[11px] font-semibold text-muted-foreground">操作</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border/40">
                      {filteredSessions.map((session, idx) => (
                        <tr
                          key={session.session_id}
                          className={cn(
                            "group transition-colors hover:bg-muted/30",
                            session.status === "completed" && session.has_report
                              ? "bg-emerald-500/[0.03]"
                              : idx % 2 === 1 && "bg-muted/10",
                          )}
                        >
                          <td className="whitespace-nowrap px-3 py-2.5">
                            <div className="flex items-center gap-1 overflow-hidden">
                              <code className="rounded bg-muted/50 px-1.5 py-0.5 font-mono text-[11px] text-foreground/80">
                                {truncate(session.session_id)}
                              </code>
                              <Button
                                type="button"
                                size="icon"
                                variant="ghost"
                                className="h-5 w-5 shrink-0 opacity-0 transition-opacity group-hover:opacity-100"
                                aria-label="复制完整 ID"
                                onClick={() => void copyToClipboard(session.session_id)}
                              >
                                <Copy className="h-3 w-3" />
                              </Button>
                            </div>
                          </td>
                          <td className="max-w-[200px] px-3 py-2.5">
                            <CellWithTooltip text={session.job_title || "未填写岗位"}>
                              <div className="overflow-hidden">
                                <div className="truncate font-medium text-foreground/90">
                                  {session.job_title || "未填写岗位"}
                                </div>
                                {session.job_level && (
                                  <div className="mt-0.5 text-[10px] text-muted-foreground/70">
                                    {session.job_level}
                                  </div>
                                )}
                              </div>
                            </CellWithTooltip>
                          </td>
                          <td className="max-w-[100px] px-2 py-2.5">
                            <CellWithTooltip text={session.candidate_name || "未填写"}>
                              <div className="overflow-hidden">
                                <div
                                  className={cn(
                                    "truncate",
                                    session.candidate_name
                                      ? "font-medium text-foreground/90"
                                      : "text-muted-foreground/60 italic",
                                  )}
                                >
                                  {session.candidate_name || "未填写"}
                                </div>
                              </div>
                            </CellWithTooltip>
                          </td>
                          <td className="whitespace-nowrap px-2 py-2.5 text-center">
                            <ScoreCell score={session.overall_score} />
                          </td>
                          <td className="whitespace-nowrap px-3 py-2.5 text-center">
                            <CombinedStatusCell session={session} />
                          </td>
                          <td className="whitespace-nowrap px-2 py-2.5 text-center">
                            <LlmCostCell cost={session.cost_summary} />
                          </td>
                          <td className="whitespace-nowrap px-3 py-2.5">
                            <HistoryTimeCell iso={session.created_at || ""} />
                          </td>
                          <td className="whitespace-nowrap px-3 py-2.5">
                            <HistorySessionActions session={session} onRefresh={onRefresh} />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Mobile Card Stack */}
                <div className="grid gap-3 md:hidden">
                  {filteredSessions.map((session) => (
                    <HistoryMobileCard key={session.session_id} session={session} onRefresh={onRefresh} />
                  ))}
                </div>

                {/* Filtered result count */}
                {(statusFilter !== "all" || searchText) && (
                  <p className="text-[11px] text-muted-foreground">
                    显示 {filteredSessions.length} / {totalCount} 条记录
                  </p>
                )}
              </>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
});

function HistoryMobileCard({
  session,
  onRefresh,
}: {
  session: InterviewSessionHistory["sessions"][number];
  onRefresh: () => void;
}) {
  return (
    <div className="space-y-3 rounded-xl border border-border/60 bg-card/50 p-4">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <code className="truncate rounded bg-muted/50 px-1.5 py-0.5 font-mono text-[10px] text-foreground/70">
            {truncate(session.session_id)}
          </code>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            className="h-5 w-5 shrink-0"
            onClick={() => void copyToClipboard(session.session_id)}
          >
            <Copy className="h-2.5 w-2.5" />
          </Button>
        </div>
        <CombinedStatusCell session={session} />
      </div>

      <div>
        <div className="truncate text-sm font-medium">
          {session.job_title || "未填写岗位"}
        </div>
        <div className="mt-0.5 flex items-center justify-between">
          <span
            className={cn(
              "text-xs",
              session.candidate_name
                ? "text-foreground/70"
                : "italic text-muted-foreground/50",
            )}
          >
            {session.candidate_name || "未填写"}
          </span>
          {session.job_level && (
            <span className="text-[10px] text-muted-foreground/60">
              {session.job_level}
            </span>
          )}
        </div>
      </div>

      <div className="flex items-center justify-between border-t border-border/40 pt-2.5">
        <ScoreCell score={session.overall_score} />
        <LlmCostCell cost={session.cost_summary} />
        <span className="text-[11px] text-muted-foreground">
          {formatRelativeTime(session.created_at || "")}
        </span>
      </div>

      <div className="border-t border-border/40 pt-2.5">
        <HistorySessionActions session={session} onRefresh={onRefresh} />
      </div>
    </div>
  );
}

function HistorySessionActions({
  session,
  onRefresh,
}: {
  session: InterviewSessionHistory["sessions"][number];
  onRefresh: () => void;
}) {
  const [deleting, setDeleting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const { toast } = useToast();

  const handleConfirmDelete = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      const result = await adminDeleteSession(session.session_id);
      setConfirming(false);
      toast({
        title: "删除成功",
        description: `已删除面试记录 ${truncate(session.session_id)}${result.traces_deleted ? ` · ${result.traces_deleted} 条 trace` : ""}`,
      });
      onRefresh();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setDeleteError(msg);
      toast({ title: "删除失败", description: msg, variant: "destructive" });
    } finally {
      setDeleting(false);
    }
  };

  if (confirming) {
    return (
      <div className="flex items-center justify-center gap-2">
        <span className="text-[11px] text-red-400/80">永久删除？</span>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={deleting}
          className="h-6 gap-1 rounded-md border border-red-500/40 bg-red-500/10 px-2.5 text-[11px] text-red-400 hover:bg-red-500/20"
          onClick={() => void handleConfirmDelete()}
        >
          {deleting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Trash2 className="h-3 w-3" />}
          确认
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={deleting}
          className="h-6 px-2.5 text-[11px] text-muted-foreground hover:text-foreground"
          onClick={() => { setConfirming(false); setDeleteError(null); }}
        >
          取消
        </Button>
        {deleteError && (
          <span className="text-[10px] text-destructive" aria-label={deleteError}>失败</span>
        )}
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center gap-1.5">
      <Button
        asChild={!!session.has_report}
        size="sm"
        variant={session.has_report ? "outline" : "ghost"}
        className={cn(
          "h-7 w-[76px] justify-center gap-1 px-2.5 text-[11px]",
          session.has_report
            ? "border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10"
            : "pointer-events-none text-muted-foreground/30",
        )}
      >
        {session.has_report ? (
          <Link href={`/interview/${session.session_id}/report`}>
            <ClipboardList className="h-3 w-3" />
            查看报告
          </Link>
        ) : (
          <span>
            <ClipboardList className="h-3 w-3" />
            查看报告
          </span>
        )}
      </Button>
      <Button
        asChild
        size="sm"
        variant="ghost"
        className="h-7 gap-1 px-2 text-[11px] text-muted-foreground hover:text-foreground"
      >
        <Link href={`/interview/${session.session_id}/replay`}>
          <Play className="h-3 w-3" />
          回放
        </Link>
      </Button>
      <Button
        asChild
        size="sm"
        variant="ghost"
        className="h-7 gap-1 px-2 text-[11px] text-muted-foreground hover:text-foreground"
      >
        <Link href={`/admin/trace?sessionId=${session.session_id}`}>
          <Waypoints className="h-3 w-3" />
          Trace
        </Link>
      </Button>
      <div className="group/del relative">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          className="h-7 px-2 text-[11px] text-muted-foreground/50 hover:text-red-400 hover:bg-red-500/10"
          onClick={() => setConfirming(true)}
        >
          <Trash2 className="h-3 w-3" />
        </Button>
        <div className="pointer-events-none absolute bottom-full left-1/2 z-[100] mb-2 hidden -translate-x-1/2 group-hover/del:block">
          <div className="whitespace-nowrap rounded-lg border border-border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-xl">
            删除此面试记录
          </div>
        </div>
      </div>
    </div>
  );
}

function CombinedStatusCell({
  session,
}: {
  session: InterviewSessionHistory["sessions"][number];
}) {
  return (
    <div className="flex flex-col items-center gap-1">
      <HistoryStatusBadge session={session} />
      {session.status === "completed" && session.trace_health && (
        <TraceStatusBadge health={session.trace_health} />
      )}
    </div>
  );
}

function HistoryTimeCell({ iso }: { iso: string }) {
  const compact = formatCompactDate(iso);
  const full = formatDateTime(iso);
  const relative = formatRelativeTime(iso);
  return (
    <div className="group/time relative">
      <span className="whitespace-nowrap font-mono text-[11px] text-muted-foreground/70">
        {compact}
      </span>
      <div className="pointer-events-none absolute bottom-full left-0 z-[100] mb-2 hidden group-hover/time:block">
        <div className="whitespace-nowrap rounded-lg border border-border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-xl">
          <span className="font-mono">{full}</span>
          <span className="ml-2 text-muted-foreground">{relative}</span>
        </div>
      </div>
    </div>
  );
}

function formatCompactDate(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "\u2014";
    const now = new Date();
    const month = d.getMonth() + 1;
    const day = d.getDate();
    const h = d.getHours().toString().padStart(2, "0");
    const m = d.getMinutes().toString().padStart(2, "0");
    if (d.getFullYear() === now.getFullYear()) {
      return `${month}/${day} ${h}:${m}`;
    }
    return `${d.getFullYear()}/${month}/${day}`;
  } catch {
    return iso;
  }
}

function CellWithTooltip({
  text,
  children,
}: {
  text: string;
  children: React.ReactNode;
}) {
  if (!text || text.length <= 12) return <>{children}</>;
  return (
    <div className="group/tip relative overflow-visible">
      {children}
      <div className="pointer-events-none absolute bottom-full left-0 z-[100] mb-2 hidden group-hover/tip:block">
        <div className="whitespace-nowrap rounded-lg border border-border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow-xl">
          {text}
        </div>
      </div>
    </div>
  );
}

function LlmCostCell({
  cost,
}: {
  cost?: InterviewSessionHistoryItem["cost_summary"];
}) {
  if (!cost || !cost.calls) {
    return <span className="text-[10px] italic text-muted-foreground/25">—</span>;
  }
  const totalTokens = (cost.prompt_tokens ?? 0) + (cost.completion_tokens ?? 0);
  const tokenLabel =
    totalTokens >= 1_000_000
      ? `${(totalTokens / 1_000_000).toFixed(1)}M`
      : totalTokens >= 1_000
        ? `${(totalTokens / 1_000).toFixed(1)}K`
        : String(totalTokens);
  return (
    <span className="inline-flex flex-col items-center gap-0.5">
      <span className="font-mono text-[11px] font-medium tabular-nums text-foreground/80">
        {cost.calls}<span className="text-muted-foreground/50">{" "}次</span>
      </span>
      {totalTokens > 0 && (
        <span className="text-[10px] text-muted-foreground/60">{tokenLabel} tok</span>
      )}
      {typeof cost.est_usd === "number" && cost.est_usd > 0 && (
        <span className="text-[10px] font-mono text-amber-400/80">
          ${cost.est_usd < 0.01 ? "<0.01" : cost.est_usd.toFixed(2)}
        </span>
      )}
    </span>
  );
}

function ScoreCell({ score }: { score?: number | null }) {
  if (typeof score !== "number") {
    return (
      <span className="inline-flex flex-col items-center gap-0.5">
        <span className="text-[10px] italic text-muted-foreground/25">未评分</span>
      </span>
    );
  }
  const pct = Math.min(100, Math.max(0, (score / 10) * 100));
  const barColor =
    score >= 8
      ? "bg-emerald-400"
      : score >= 6
        ? "bg-sky-400"
        : score >= 4
          ? "bg-amber-400"
          : "bg-red-400";
  const textColor =
    score >= 8
      ? "text-emerald-400"
      : score >= 6
        ? "text-sky-400"
        : score >= 4
          ? "text-amber-400"
          : "text-red-400";
  return (
    <span className="inline-flex flex-col items-center gap-1">
      <span className="flex items-baseline gap-0.5 font-mono tabular-nums">
        <span className={`text-sm font-bold ${textColor}`}>{score.toFixed(1)}</span>
        <span className="text-[9px] text-muted-foreground/50">/10</span>
      </span>
      <span className="h-1 w-12 overflow-hidden rounded-full bg-muted/40">
        <span
          className={`block h-full rounded-full ${barColor} transition-all`}
          style={{ width: `${pct}%` }}
        />
      </span>
    </span>
  );
}

function HistoryStatusBadge({
  session,
}: {
  session: InterviewSessionHistory["sessions"][number];
}) {
  const status = formatHistoryStatus(session.status);
  if (status.variant === "success") {
    return (
      <Badge variant="success" className="gap-1 text-[10px]">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400" />
        {status.label}
      </Badge>
    );
  }
  if (status.variant === "warn") {
    return (
      <Badge variant="warn" className="gap-1 text-[10px]">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-400" />
        {status.label}
      </Badge>
    );
  }
  if (status.variant === "destructive" || session.error_kind) {
    return (
      <Badge variant="destructive" className="gap-1 text-[10px]">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-red-400" />
        {status.label}
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="gap-1 text-[10px] text-muted-foreground">
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-muted-foreground/50" />
      {status.label}
    </Badge>
  );
}

function formatHistoryStatus(status: string): {
  label: string;
  variant: "success" | "warn" | "destructive" | "outline";
} {
  switch (status) {
    case "completed":
      return { label: "已完成", variant: "success" };
    case "cancelled":
      return { label: "已取消", variant: "warn" };
    case "errored":
      return { label: "出错", variant: "destructive" };
    case "running":
      return { label: "进行中", variant: "outline" };
    case "interrupted":
      return { label: "可恢复", variant: "outline" };
    default:
      return { label: status || "未知", variant: "outline" };
  }
}

function TraceStatusBadge({
  health,
}: {
  health?: InterviewSessionHistory["sessions"][number]["trace_health"];
}) {
  if (health === "complete") {
    return (
      <Badge variant="success" className="gap-1 text-[10px]">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
        Trace 完整
      </Badge>
    );
  }
  if (health === "partial") {
    return (
      <Badge variant="warn" className="gap-1 text-[10px]">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-400" />
        Trace 部分
      </Badge>
    );
  }
  if (health === "missing") {
    return (
      <Badge variant="destructive" className="gap-1 text-[10px]">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-destructive" />
        Trace 缺失
      </Badge>
    );
  }
  return (
    <span className="text-[10px] text-muted-foreground/30">—</span>
  );
}

function LangSmithCell({
  session,
  langsmith,
}: {
  session: AdminSessions["sessions"][number];
  langsmith: AdminSessions["langsmith"];
}) {
  const webUrl = langsmith?.web_url || "https://smith.langchain.com";
  const runId = session.langsmith_run_id;
  const copyValue = runId || session.trace_id;
  const projectHint = langsmith?.project ? ` (${langsmith.project})` : "";
  const openTitle = runId
    ? `打开 LangSmith${projectHint}，复制 run id 后可定位该运行`
    : `打开 LangSmith${projectHint}，复制 trace id 后可搜索该会话`;

  return (
    <div className="flex min-w-[160px] items-center gap-1.5">
      <Button
        asChild
        size="sm"
        variant={runId ? "outline" : "ghost"}
        className="h-7 gap-1.5 px-2 text-[11px]"
        aria-label={openTitle}
      >
        <a href={webUrl} target="_blank" rel="noreferrer">
          {runId ? (
            <ExternalLink className="h-3.5 w-3.5" />
          ) : (
            <Search className="h-3.5 w-3.5" />
          )}
          <span className="font-mono">{runId ? truncate(runId) : "trace"}</span>
        </a>
      </Button>
      <Button
        type="button"
        size="icon"
        variant="ghost"
        className="h-7 w-7"
        aria-label={runId ? "复制 LangSmith run id" : "复制 trace id"}
        onClick={() => void copyToClipboard(copyValue)}
      >
        <Copy className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

function SessionStatusBadge({ session }: { session: AdminSessions["sessions"][number] }) {
  if (session.cancelled) {
    return <Badge variant="destructive" className="text-[10px]">已取消</Badge>;
  }
  if (session.error) {
    return <Badge variant="destructive" className="text-[10px]">出错</Badge>;
  }
  if (session.done) {
    return <Badge variant="success" className="text-[10px]">已完成</Badge>;
  }
  if (session.has_question) {
    return <Badge variant="warn" className="text-[10px]">等待回答</Badge>;
  }
  return (
    <Badge variant="outline" className="text-[10px]">
      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
      运行中
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Strategies memory
// ---------------------------------------------------------------------------

function QuestionBankCard({
  state,
  usages,
  rerankUsages,
  reviews,
  onRefresh,
}: {
  state: Loadable<QuestionSeeds>;
  usages: Loadable<QuestionUsages>;
  rerankUsages: Loadable<QuestionRerankUsages>;
  reviews: Loadable<QuestionReviews>;
  onRefresh: () => void;
}) {
  const { toast } = useToast();
  const [selectedSeedId, setSelectedSeedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Loadable<QuestionSeedDetail> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (selectedSeedId || state.phase !== "ready") return;
    const first = state.data.question_seeds[0];
    if (first) setSelectedSeedId(first.id);
  }, [selectedSeedId, state]);

  useEffect(() => {
    if (!selectedSeedId) {
      setDetail(null);
      return;
    }
    const ctrl = new AbortController();
    setDetail({ phase: "loading" });
    getQuestionSeed(selectedSeedId, ctrl.signal)
      .then((data) => {
        if (!ctrl.signal.aborted) setDetail({ phase: "ready", data });
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) {
          setDetail({
            phase: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      });
    return () => ctrl.abort();
  }, [selectedSeedId]);

  async function handleImport(archiveMissing: boolean) {
    if (busy) return;
    setBusy(archiveMissing ? "import-archive" : "import");
    try {
      const result = await importQuestionSeeds(archiveMissing);
      toast({
        title: "结构化题库已导入",
        description: `seeds +${result.imported_seeds}/${result.updated_seeds}, variants +${result.imported_variants}/${result.updated_variants}, archived=${result.archived_seeds + result.archived_variants}`,
      });
      onRefresh();
    } catch (err) {
      toast({
        title: "结构化题库导入失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleLint(strictQuality: boolean) {
    if (busy) return;
    setBusy(strictQuality ? "lint-strict" : "lint");
    try {
      const result = await runQuestionSeedLint(strictQuality);
      toast({
        title: result.passed ? "题库质量 lint 通过" : "题库质量 lint 有阻断项",
        description: `warnings=${result.warning_count}, errors=${result.error_count}`,
        variant: result.passed ? undefined : "destructive",
      });
      onRefresh();
    } catch (err) {
      toast({
        title: "题库质量 lint 失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleReviewFromRerank(winner: "rule" | "llm" | "tie" | "neither") {
    if (busy || rerankUsages.phase !== "ready") return;
    const row = rerankUsages.data.rerank_usages[0];
    if (!row) return;
    setBusy(`review:${winner}`);
    try {
      await createQuestionReview({
        question_rerank_usage_id: row.id,
        session_id: row.session_id,
        turn_idx: row.turn_idx,
        trace_id: row.trace_id,
        rule_variant_id: row.rule_top_variant_id,
        llm_variant_id: row.llm_top_variant_id,
        winner,
        reasons: ["admin_pairwise_review"],
        notes: "",
        reviewer: "admin",
        context_summary: {
          dimension: row.dimension,
          probe_intent: row.probe_intent,
          anchor_choice: row.anchor_choice,
        },
      });
      toast({ title: "pairwise review 已记录" });
      onRefresh();
    } catch (err) {
      toast({
        title: "pairwise review 记录失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleSeedAction(seedId: string, action: "disable" | "archive") {
    if (busy) return;
    setBusy(`${action}:${seedId}`);
    try {
      const result =
        action === "disable"
          ? await disableQuestionSeed(seedId)
          : await archiveQuestionSeed(seedId);
      toast({
        title: "题目种子状态已更新",
        description: `${result.id} -> ${result.status}`,
      });
      onRefresh();
      setSelectedSeedId(seedId);
    } catch (err) {
      toast({
        title: "题目种子操作失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleVariantAction(
    variantId: string,
    action: "disable" | "archive",
  ) {
    if (busy) return;
    setBusy(`${action}:${variantId}`);
    try {
      const result =
        action === "disable"
          ? await disableQuestionVariant(variantId)
          : await archiveQuestionVariant(variantId);
      toast({
        title: "题目变体状态已更新",
        description: `${result.id} -> ${result.status}`,
      });
      onRefresh();
      if (selectedSeedId) {
        const refreshed = await getQuestionSeed(selectedSeedId);
        setDetail({ phase: "ready", data: refreshed });
      }
    } catch (err) {
      toast({
        title: "题目变体操作失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <ClipboardList className="h-4 w-4 text-sky-400" />
              结构化题库
            </CardTitle>
            <CardDescription className="mt-1">
              YAML 权威源、结构化 seed/variant 和最近 selector usage。
            </CardDescription>
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            {state.phase === "ready" && (
              <Badge variant="outline" className="font-mono text-[10px]">
                {state.data.count} seeds
              </Badge>
            )}
            {usages.phase === "ready" && (
              <Badge variant="secondary" className="font-mono text-[10px]">
                {usages.data.count} usages
              </Badge>
            )}
            {rerankUsages.phase === "ready" && (
              <Badge variant="outline" className="font-mono text-[10px]">
                {rerankUsages.data.count} reranks
              </Badge>
            )}
            {reviews.phase === "ready" && (
              <Badge variant="outline" className="font-mono text-[10px]">
                {reviews.data.count} reviews
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-secondary/20 p-3">
          <div>
            <p className="text-sm font-medium">YAML 导入</p>
            <p className="text-xs text-muted-foreground">
              内容编辑仍在 knowledge/question_seeds，面板只触发导入和状态切换。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => handleImport(false)}
              disabled={busy !== null}
            >
              {busy === "import" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              导入 YAML
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => handleImport(true)}
              disabled={busy !== null}
            >
              {busy === "import-archive" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              归档缺失
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => handleLint(false)}
              disabled={busy !== null}
            >
              {busy === "lint" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Lint
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => handleLint(true)}
              disabled={busy !== null}
            >
              {busy === "lint-strict" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Strict lint
            </Button>
          </div>
        </div>

        {state.phase === "loading" && <LoadingList rows={3} />}
        {state.phase === "error" && <ErrorBox message={state.message} />}
        {state.phase === "ready" && state.data.question_seeds.length === 0 && (
          <p className="text-xs text-muted-foreground">
            暂无结构化题目种子。先导入 YAML 后再查看 selector usage。
          </p>
        )}
        {state.phase === "ready" && state.data.question_seeds.length > 0 && (
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
            <ul className="space-y-2">
              {state.data.question_seeds.map((seed) => (
                <li
                  key={seed.id}
                  className={cn(
                    "rounded-lg border bg-card/50 p-3 text-sm",
                    selectedSeedId === seed.id && "border-primary/50",
                  )}
                >
                  <button
                    type="button"
                    className="w-full text-left"
                    onClick={() => setSelectedSeedId(seed.id)}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="font-medium">{seed.title}</span>
                      <Badge variant="outline" className="font-mono text-[10px]">
                        {seed.status}
                      </Badge>
                    </div>
                    <div className="mt-1 font-mono text-[10px] text-muted-foreground">
                      {seed.id}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      <Badge variant="secondary" className="font-mono text-[10px]">
                        {seed.dimension}
                      </Badge>
                      {seed.direction_tags.map((tag) => (
                        <Badge key={tag} variant="outline" className="font-mono text-[10px]">
                          {tag}
                        </Badge>
                      ))}
                      {seed.role_tags.map((tag) => (
                        <Badge key={tag} variant="outline" className="font-mono text-[10px]">
                          {tag}
                        </Badge>
                      ))}
                      <Badge variant="outline" className="font-mono text-[10px]">
                        {seed.variant_count ?? 0} variants
                      </Badge>
                      {seed.job_levels.slice(0, 3).map((level) => (
                        <Badge key={level} variant="outline" className="font-mono text-[10px]">
                          {level}
                        </Badge>
                      ))}
                    </div>
                  </button>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => handleSeedAction(seed.id, "disable")}
                      disabled={busy !== null || seed.status !== "active"}
                    >
                      禁用
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => handleSeedAction(seed.id, "archive")}
                      disabled={busy !== null || seed.status === "archived"}
                    >
                      归档
                    </Button>
                  </div>
                </li>
              ))}
            </ul>

            <div className="rounded-lg border bg-card/40 p-3">
              {detail?.phase === "loading" && <LoadingList rows={4} />}
              {detail?.phase === "error" && <ErrorBox message={detail.message} />}
              {detail?.phase === "ready" && (
                <div className="space-y-3">
                  <div>
                    <p className="text-sm font-medium">{detail.data.seed.title}</p>
                    <p className="mt-1 font-mono text-[10px] text-muted-foreground">
                      {detail.data.seed.id}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {detail.data.seed.direction_tags.map((tag) => (
                      <Badge key={tag} variant="outline" className="font-mono text-[10px]">
                        {tag}
                      </Badge>
                    ))}
                    {detail.data.seed.role_tags.map((tag) => (
                      <Badge key={tag} variant="outline" className="font-mono text-[10px]">
                        {tag}
                      </Badge>
                    ))}
                    {detail.data.seed.skill_tags.map((tag) => (
                      <Badge key={tag} variant="secondary" className="font-mono text-[10px]">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                  <Separator />
                  <div className="space-y-2">
                    {detail.data.variants.map((variant) => (
                      <div key={variant.id} className="rounded-md border bg-background/40 p-2 text-xs">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <span className="font-medium">{variant.intent}</span>
                          <div className="flex flex-wrap gap-1">
                            <Badge variant="outline" className="font-mono text-[10px]">
                              {variant.difficulty}
                            </Badge>
                            <Badge variant="outline" className="font-mono text-[10px]">
                              {variant.status}
                            </Badge>
                          </div>
                        </div>
                        <p className="mt-1 text-muted-foreground">{variant.scenario_brief}</p>
                        <p className="mt-1 font-mono text-[10px] text-muted-foreground">
                          {variant.id}
                        </p>
                        <div className="mt-2 flex flex-wrap gap-1">
                          {variant.role_tags.map((tag) => (
                            <Badge key={tag} variant="secondary" className="font-mono text-[10px]">
                              {tag}
                            </Badge>
                          ))}
                          {variant.failure_categories.map((cat) => (
                            <Badge key={cat} variant="outline" className="font-mono text-[10px]">
                              {cat}
                            </Badge>
                          ))}
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2">
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => handleVariantAction(variant.id, "disable")}
                            disabled={busy !== null || variant.status !== "active"}
                          >
                            禁用
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={() => handleVariantAction(variant.id, "archive")}
                            disabled={busy !== null || variant.status === "archived"}
                          >
                            归档
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {usages.phase === "ready" && usages.data.usages.length > 0 && (
          <div className="space-y-2 border-t border-border/40 pt-3">
            <p className="text-xs font-medium text-muted-foreground">最近 question usage</p>
            <ul className="space-y-1.5">
              {usages.data.usages.slice(0, 5).map((usage) => (
                <li key={usage.id} className="rounded-md border bg-card/30 p-2 text-[11px]">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge variant={usage.injected ? "success" : "outline"} className="font-mono text-[10px]">
                      rank {usage.rank}
                    </Badge>
                    <Badge variant="secondary" className="font-mono text-[10px]">
                      {usage.question_selector_mode}
                    </Badge>
                    <span className="font-mono text-muted-foreground">
                      {usage.variant_id}
                    </span>
                    {(usage.role_tags ?? []).map((tag) => (
                      <Badge key={tag} variant="outline" className="font-mono text-[10px]">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-3 text-muted-foreground">
                    <span>score {formatMaybeNumber(usage.match_score)}</span>
                    <span>eval {formatMaybeNumber(usage.score)}</span>
                    <span>reward {formatMaybeNumber(usage.immediate_reward)}</span>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}

        {rerankUsages.phase === "ready" && rerankUsages.data.rerank_usages.length > 0 && (
          <div className="space-y-2 border-t border-border/40 pt-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs font-medium text-muted-foreground">
                shadow reranker pairwise review
              </p>
              <div className="flex flex-wrap gap-1.5">
                {(["rule", "llm", "tie", "neither"] as const).map((winner) => (
                  <Button
                    key={winner}
                    type="button"
                    size="sm"
                    variant={winner === "llm" ? "outline" : "ghost"}
                    onClick={() => handleReviewFromRerank(winner)}
                    disabled={busy !== null}
                  >
                    {winner}
                  </Button>
                ))}
              </div>
            </div>
            <ul className="space-y-1.5">
              {rerankUsages.data.rerank_usages.slice(0, 3).map((row) => (
                <li key={row.id} className="rounded-md border bg-card/30 p-2 text-[11px]">
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant={row.status === "ok" ? "success" : "warn"} className="font-mono text-[10px]">
                      {row.status}
                    </Badge>
                    <Badge variant="secondary" className="font-mono text-[10px]">
                      conf {formatMaybeNumber(row.confidence)}
                    </Badge>
                    <span className="font-mono text-muted-foreground">
                      rule {row.rule_top_variant_id ?? "-"}
                    </span>
                    <span className="font-mono text-muted-foreground">
                      llm {row.llm_top_variant_id ?? "-"}
                    </span>
                  </div>
                  {row.anchor_choice && (
                    <p className="mt-1 text-muted-foreground">anchor {row.anchor_choice}</p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {reviews.phase === "ready" && reviews.data.reviews.length > 0 && (
          <div className="space-y-2 border-t border-border/40 pt-3">
            <p className="text-xs font-medium text-muted-foreground">
              recent question reviews
            </p>
            <ul className="space-y-1.5">
              {reviews.data.reviews.slice(0, 3).map((review) => (
                <li key={review.id} className="rounded-md border bg-card/30 p-2 text-[11px]">
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant="outline" className="font-mono text-[10px]">
                      {review.winner}
                    </Badge>
                    <span className="font-mono text-muted-foreground">
                      {review.rule_variant_id ?? "-"} vs {review.llm_variant_id ?? "-"}
                    </span>
                  </div>
                  {review.reasons.length > 0 && (
                    <p className="mt-1 text-muted-foreground">
                      {review.reasons.slice(0, 2).join(", ")}
                    </p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SkillsPlaybookCard({
  state,
  onRefresh,
}: {
  state: Loadable<SkillPlaybooks>;
  onRefresh: () => void;
}) {
  const { toast } = useToast();
  const [selectedCardId, setSelectedCardId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Loadable<SkillPlaybookDetail> | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (selectedCardId || state.phase !== "ready") return;
    const first = state.data.skill_playbooks[0];
    if (first) setSelectedCardId(first.id);
  }, [selectedCardId, state]);

  useEffect(() => {
    if (!selectedCardId) {
      setDetail(null);
      return;
    }
    const ctrl = new AbortController();
    setDetail({ phase: "loading" });
    getSkillPlaybook(selectedCardId, ctrl.signal)
      .then((data) => {
        if (!ctrl.signal.aborted) setDetail({ phase: "ready", data });
      })
      .catch((err) => {
        if (!ctrl.signal.aborted) {
          setDetail({
            phase: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      });
    return () => ctrl.abort();
  }, [selectedCardId]);

  async function handleImport(archiveMissing: boolean) {
    if (busy) return;
    setBusy(archiveMissing ? "import-archive" : "import");
    try {
      const result = await importSkillPlaybooks(archiveMissing);
      toast({
        title: "Skills playbook imported",
        description: `imported=${result.imported}, updated=${result.updated}, unchanged=${result.unchanged}, archived=${result.archived}, skipped=${result.skipped}`,
      });
      onRefresh();
    } catch (err) {
      toast({
        title: "Skills playbook import failed",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <BookMarked className="h-4 w-4 text-cyan-400" />
              Skills Playbook
            </CardTitle>
            <CardDescription className="mt-1">
              DB-backed interviewer playbook cards imported from knowledge/skills.
            </CardDescription>
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            {state.phase === "ready" && (
              <>
                <Badge variant="outline" className="font-mono text-[10px]">
                  {state.data.count} cards
                </Badge>
                <Badge variant="secondary" className="font-mono text-[10px]">
                  {state.data.active_count} active
                </Badge>
                <Badge variant="outline" className="font-mono text-[10px]">
                  runtime_backend={state.data.runtime_backend}
                </Badge>
              </>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-secondary/20 p-3">
          <div>
            <p className="text-sm font-medium">Markdown import</p>
            <p className="text-xs text-muted-foreground">
              Markdown remains authoritative; this panel only observes DB rows and triggers strict import.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => handleImport(false)}
              disabled={busy !== null}
            >
              {busy === "import" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Import
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => handleImport(true)}
              disabled={busy !== null}
            >
              {busy === "import-archive" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Import + archive missing
            </Button>
          </div>
        </div>

        {state.phase === "loading" && <LoadingList rows={3} />}
        {state.phase === "error" && <ErrorBox message={state.message} />}
        {state.phase === "ready" && (
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
            <div className="space-y-3">
              <div className="rounded-lg border bg-card/40 p-3">
                <p className="text-xs font-medium text-muted-foreground">status distribution</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {Object.entries(state.data.status_counts).map(([status, count]) => (
                    <Badge key={status} variant="outline" className="font-mono text-[10px]">
                      {status}:{count}
                    </Badge>
                  ))}
                </div>
              </div>

              {state.data.skill_playbooks.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  No skill playbook cards in DB. Run import after deploying the schema.
                </p>
              ) : (
                <ul className="space-y-2">
                  {state.data.skill_playbooks.slice(0, 12).map((card) => (
                    <li
                      key={card.id}
                      className={cn(
                        "rounded-lg border bg-card/50 p-3 text-sm",
                        selectedCardId === card.id && "border-primary/50",
                      )}
                    >
                      <button
                        type="button"
                        className="w-full text-left"
                        onClick={() => setSelectedCardId(card.id)}
                      >
                        <div className="flex items-start justify-between gap-2">
                          <span className="font-medium">{card.name || card.id}</span>
                          <Badge variant="outline" className="font-mono text-[10px]">
                            {card.status}
                          </Badge>
                        </div>
                        <div className="mt-1 font-mono text-[10px] text-muted-foreground">
                          {card.id}
                        </div>
                        {card.description && (
                          <p className="mt-1 text-xs text-muted-foreground">
                            {card.description}
                          </p>
                        )}
                        <div className="mt-2 flex flex-wrap gap-1.5">
                          <Badge variant="secondary" className="font-mono text-[10px]">
                            p{card.priority}
                          </Badge>
                          {card.direction_tags.map((tag) => (
                            <Badge key={tag} variant="outline" className="font-mono text-[10px]">
                              {tag}
                            </Badge>
                          ))}
                          {card.role_tags.slice(0, 3).map((tag) => (
                            <Badge key={tag} variant="outline" className="font-mono text-[10px]">
                              {tag}
                            </Badge>
                          ))}
                          {card.dimensions.slice(0, 3).map((dimension) => (
                            <Badge key={dimension} variant="secondary" className="font-mono text-[10px]">
                              {dimension}
                            </Badge>
                          ))}
                        </div>
                        {card.body_preview && (
                          <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
                            {card.body_preview}
                          </p>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="rounded-lg border bg-card/40 p-3">
              {detail?.phase === "loading" && <LoadingList rows={4} />}
              {detail?.phase === "error" && <ErrorBox message={detail.message} />}
              {detail?.phase === "ready" && (
                <div className="space-y-3">
                  <div>
                    <p className="text-sm font-medium">
                      {detail.data.skill_playbook.name}
                    </p>
                    <p className="mt-1 font-mono text-[10px] text-muted-foreground">
                      {detail.data.skill_playbook.id}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant="outline" className="font-mono text-[10px]">
                      {detail.data.skill_playbook.status}
                    </Badge>
                    <Badge variant="secondary" className="font-mono text-[10px]">
                      v{detail.data.skill_playbook.version ?? 1}
                    </Badge>
                    <Badge variant="outline" className="font-mono text-[10px]">
                      {detail.data.skill_playbook.source ?? "unknown"}
                    </Badge>
                    <Badge variant="outline" className="font-mono text-[10px]">
                      hash {truncate(detail.data.skill_playbook.content_hash ?? "")}
                    </Badge>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {detail.data.skill_playbook.direction_tags.map((tag) => (
                      <Badge key={tag} variant="outline" className="font-mono text-[10px]">
                        {tag}
                      </Badge>
                    ))}
                    {detail.data.skill_playbook.role_tags.map((tag) => (
                      <Badge key={tag} variant="outline" className="font-mono text-[10px]">
                        {tag}
                      </Badge>
                    ))}
                    {detail.data.skill_playbook.dimensions.map((dimension) => (
                      <Badge key={dimension} variant="secondary" className="font-mono text-[10px]">
                        {dimension}
                      </Badge>
                    ))}
                    {detail.data.skill_playbook.job_levels.map((level) => (
                      <Badge key={level} variant="outline" className="font-mono text-[10px]">
                        {level}
                      </Badge>
                    ))}
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    updated {formatDateTime(
                      detail.data.skill_playbook.updated_at ||
                        detail.data.skill_playbook.created_at ||
                        "",
                    )}
                  </div>
                  <div className="grid gap-3 md:grid-cols-3">
                    <PlaybookFieldList
                      label="Generator moves"
                      items={detail.data.skill_playbook.generator_moves}
                    />
                    <PlaybookFieldList
                      label="Watch for"
                      items={detail.data.skill_playbook.watch_for}
                    />
                    <PlaybookFieldList
                      label="Avoid"
                      items={detail.data.skill_playbook.avoid}
                    />
                  </div>
                  <div className="rounded-lg border bg-background/60 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-xs font-medium">
                        Evaluator fields are staged for observation only
                      </p>
                      <Badge variant="outline" className="font-mono text-[10px]">
                        evaluator_visibility=
                        {String(detail.data.skill_playbook.evaluator_visibility)}
                      </Badge>
                    </div>
                    <p className="mt-1 text-[11px] text-muted-foreground">
                      These hints are not used by Evaluator runtime.
                    </p>
                    <div className="mt-3 grid gap-3 md:grid-cols-2">
                      <PlaybookFieldList
                        label="Rubric hints"
                        items={detail.data.skill_playbook.evaluator_rubric_hints}
                      />
                      <PlaybookFieldList
                        label="Positive signals"
                        items={detail.data.skill_playbook.positive_signals}
                      />
                      <PlaybookFieldList
                        label="Negative signals"
                        items={detail.data.skill_playbook.negative_signals}
                      />
                      <PlaybookFieldList
                        label="Score bias rules"
                        items={detail.data.skill_playbook.score_bias_rules}
                      />
                    </div>
                  </div>
                  <Separator />
                  <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-background/70 p-3 text-xs leading-relaxed text-foreground/85">
                    {detail.data.skill_playbook.body_markdown || ""}
                  </pre>
                </div>
              )}
              {!detail && (
                <p className="text-xs text-muted-foreground">
                  Select a playbook card to inspect the full body_markdown.
                </p>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PlaybookFieldList({
  label,
  items,
}: {
  label: string;
  items: string[] | undefined;
}) {
  const values = items ?? [];
  return (
    <div className="rounded-lg border bg-background/60 p-3">
      <p className="text-xs font-medium">{label}</p>
      {values.length === 0 ? (
        <p className="mt-2 text-[11px] text-muted-foreground">empty</p>
      ) : (
        <ul className="mt-2 space-y-1.5 text-xs text-muted-foreground">
          {values.map((item) => (
            <li key={item}>- {item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

const StrategiesCard = React.memo(function StrategiesCard({
  state,
  signals,
  usages,
  stats,
  onRefresh,
}: {
  state: Loadable<Strategies>;
  signals: Loadable<StrategySignals>;
  usages: Loadable<StrategyUsages>;
  stats: Loadable<StrategyStats>;
  onRefresh: () => void;
}) {
  const { toast } = useToast();
  const [busy, setBusy] = useState<string | null>(null);

  async function handleStatusAction(
    strategyId: string | null | undefined,
    action: "disable" | "archive",
  ) {
    if (!strategyId || busy) return;
    setBusy(`${action}:${strategyId}`);
    try {
      if (action === "disable") {
        await disableStrategy(strategyId);
      } else {
        await archiveStrategy(strategyId);
      }
      toast({ title: action === "disable" ? "策略已禁用" : "策略已归档" });
      onRefresh();
    } catch (err) {
      toast({
        title: "策略操作失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handlePromotionRun() {
    if (busy) return;
    setBusy("promotion");
    try {
      const result = await runStrategyPromotion();
      toast({
        title: "策略晋升已执行",
        description: `promoted=${result.promoted}, unchanged=${result.unchanged}, skipped=${result.skipped}, disabled=${result.disabled ?? 0}, stabilized=${result.stabilized ?? 0}`,
      });
      onRefresh();
    } catch (err) {
      toast({
        title: "策略晋升失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  async function handleStatsRefresh() {
    if (busy) return;
    setBusy("stats");
    try {
      const result = await refreshStrategyStats();
      toast({
        title: "策略统计已刷新",
        description: `refreshed=${result.refreshed}, deleted=${result.deleted}`,
      });
      onRefresh();
    } catch (err) {
      toast({
        title: "策略统计刷新失败",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setBusy(null);
    }
  }

  const signalCount = signals.phase === "ready" ? signals.data.count : null;
  const usageCount = usages.phase === "ready" ? usages.data.count : null;
  const statCount = stats.phase === "ready" ? stats.data.count : null;
  const globalStatsByStrategy = new Map(
    stats.phase === "ready"
      ? stats.data.stats
          .filter((row) => row.context_key === "__global__")
          .map((row) => [row.strategy_id, row])
      : [],
  );

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <BookMarked className="h-4 w-4 text-emerald-400" />
              策略记忆
            </CardTitle>
            <CardDescription className="mt-1">
              DB-backed 策略记忆、晋升信号和 reward usage 归因。
            </CardDescription>
          </div>
          <div className="flex flex-wrap justify-end gap-2">
            {state.phase === "ready" && (
              <Badge variant="outline" className="font-mono text-[10px]">
                {state.data.count} 策略
              </Badge>
            )}
            {signalCount !== null && (
              <Badge variant="secondary" className="font-mono text-[10px]">
                {signalCount} signals
              </Badge>
            )}
            {usageCount !== null && (
              <Badge variant="secondary" className="font-mono text-[10px]">
                {usageCount} usages
              </Badge>
            )}
            {statCount !== null && (
              <Badge variant="secondary" className="font-mono text-[10px]">
                {statCount} stats
              </Badge>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-secondary/20 p-3">
          <div>
            <p className="text-sm font-medium">自动晋升</p>
            <p className="text-xs text-muted-foreground">
              聚合 observed signals，达标后生成 low-confidence active strategy。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handleStatsRefresh}
              disabled={busy !== null}
            >
              {busy === "stats" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              刷新统计
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={handlePromotionRun}
              disabled={busy !== null}
            >
              {busy === "promotion" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              运行晋升
            </Button>
          </div>
        </div>
        {state.phase === "loading" && <LoadingList rows={3} />}
        {state.phase === "error" && <ErrorBox message={state.message} />}
        {state.phase === "ready" && state.data.strategies.length === 0 && (
          <p className="text-xs text-muted-foreground">
            数据库中暂无 active 策略记忆。可以先导入 seed 或等待 signals 晋升。
          </p>
        )}
        {state.phase === "ready" && state.data.strategies.length > 0 && (
          <ul className="space-y-2">
            {state.data.strategies.map((s) => {
              const strategyStats = s.id ? globalStatsByStrategy.get(s.id) : undefined;
              return (
              <li
                key={s.path}
                className="rounded-lg border bg-card/50 p-3 text-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <span className="font-medium">{s.name || s.path}</span>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {s.source && (
                        <Badge variant="secondary" className="font-mono text-[10px]">
                          {s.source}
                        </Badge>
                      )}
                      {s.status && (
                        <Badge variant="outline" className="font-mono text-[10px]">
                          {s.status}
                        </Badge>
                      )}
                      {s.promotion_stage && (
                        <Badge variant="outline" className="font-mono text-[10px]">
                          {s.promotion_stage}
                        </Badge>
                      )}
                    </div>
                  </div>
                  <span className="font-mono text-[10px] text-muted-foreground">
                    {s.id ?? s.path}
                  </span>
                </div>
                {s.description && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {s.description}
                  </p>
                )}
                {s.quality_reason && (
                  <p className="mt-1 text-xs text-amber-500">
                    quality: {s.quality_reason}
                  </p>
                )}
                <div className="mt-2 flex flex-wrap gap-3 text-[11px] text-muted-foreground">
                  <span>confidence {formatMaybeNumber(s.confidence)}</span>
                  <span>support {s.support_count ?? 0}</span>
                  {strategyStats && (
                    <>
                      <span>uses {strategyStats.uses}</span>
                      <span>
                        blended {formatMaybeNumber(strategyStats.avg_blended_reward)}
                      </span>
                      <span>
                        overrule {formatPercent(strategyStats.overrule_rate ?? 0)}
                      </span>
                      {strategyStats.last_used_at && (
                        <span>last {formatRelativeTime(strategyStats.last_used_at)}</span>
                      )}
                    </>
                  )}
                  {s.memory_key && <span className="font-mono">{s.memory_key}</span>}
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {s.dimensions.map((d) => (
                    <Badge
                      key={d}
                      variant="secondary"
                      className="font-mono text-[10px]"
                    >
                      {d}
                    </Badge>
                  ))}
                  {s.job_levels.map((j) => (
                    <Badge
                      key={j}
                      variant="outline"
                      className="font-mono text-[10px]"
                    >
                      {j}
                    </Badge>
                  ))}
                </div>
                {s.id && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => handleStatusAction(s.id, "disable")}
                      disabled={busy !== null || s.status !== "active"}
                    >
                      禁用
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => handleStatusAction(s.id, "archive")}
                      disabled={busy !== null || s.status === "archived"}
                    >
                      归档
                    </Button>
                  </div>
                )}
              </li>
              );
            })}
          </ul>
        )}
        {signals.phase === "ready" && signals.data.signals.length > 0 && (
          <div className="space-y-2 border-t border-border/40 pt-3">
            <p className="text-xs font-medium text-muted-foreground">
              最近 signals（失败类型 taxonomy 来自 PR1 evaluator 输出）
            </p>
            <ul className="space-y-1.5">
              {signals.data.signals.slice(0, 5).map((sig) => (
                <li
                  key={sig.id}
                  className="rounded-md border bg-card/30 p-2 text-[11px]"
                >
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge variant="outline" className="font-mono text-[10px]">
                      {sig.signal_type}
                    </Badge>
                    <Badge variant="secondary" className="font-mono text-[10px]">
                      {sig.dimension}
                    </Badge>
                    {sig.job_level && (
                      <Badge variant="outline" className="font-mono text-[10px]">
                        {sig.job_level}
                      </Badge>
                    )}
                    <span className="font-mono text-muted-foreground">
                      {sig.group_key}
                    </span>
                  </div>
                  {sig.failure_categories && sig.failure_categories.length > 0 && (
                    <div className="mt-1 flex flex-wrap gap-1">
                      <span className="text-muted-foreground">failure:</span>
                      {sig.failure_categories.map((cat) => (
                        <Badge
                          key={cat}
                          variant="outline"
                          className="font-mono text-[10px] text-amber-500"
                        >
                          {cat}
                        </Badge>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
});

// ---------------------------------------------------------------------------
// Shared primitives
// ---------------------------------------------------------------------------

function LoadingList({ rows }: { rows: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-5 w-full" />
      ))}
    </div>
  );
}

function ErrorBox({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-xs text-destructive">
      <Activity className="mt-0.5 h-3.5 w-3.5" />
      <span>{message}</span>
    </div>
  );
}

function MetaPill({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full border bg-card/50 px-2 py-0.5 text-xs">
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <span className="font-mono tabular-nums">{value}</span>
    </span>
  );
}

function TimeCell({ iso }: { iso: string }) {
  return (
    <span
      aria-label={`完整时间：${formatDateTime(iso)}`}
      className="inline-flex flex-col gap-0.5"
    >
      <span className="text-xs text-foreground/70">{formatRelativeTime(iso)}</span>
      <span className="font-mono text-[10px] text-muted-foreground/60">
        {formatDateTime(iso)}
      </span>
    </span>
  );
}

function StatBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-card/50 p-3">
      <div className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 font-mono text-lg tabular-nums">{value}</div>
    </div>
  );
}

function truncate(v: string): string {
  if (v.length <= 16) return v;
  return `${v.slice(0, 6)}…${v.slice(-6)}`;
}

async function copyToClipboard(value: string): Promise<void> {
  if (!value) return;
  try {
    await navigator.clipboard?.writeText(value);
    return;
  } catch {
    /* fall through to the legacy copy path */
  }

  const el = document.createElement("textarea");
  el.value = value;
  el.setAttribute("readonly", "");
  el.style.position = "fixed";
  el.style.left = "-9999px";
  document.body.appendChild(el);
  el.select();
  try {
    document.execCommand("copy");
  } finally {
    document.body.removeChild(el);
  }
}

function formatRelativeTime(iso: string): string {
  const time = Date.parse(iso);
  if (!Number.isFinite(time)) return "—";
  const diffMs = Date.now() - time;
  const absMs = Math.abs(diffMs);
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;
  if (absMs < minute) return "刚刚";
  if (absMs < hour) return `${Math.floor(absMs / minute)} 分钟前`;
  if (absMs < day) return `${Math.floor(absMs / hour)} 小时前`;
  return `${Math.floor(absMs / day)} 天前`;
}

function formatDateTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return `${d.toLocaleDateString()} ${d.toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    })}`;
  } catch {
    return iso;
  }
}

function formatPercent(value: number): string {
  if (!Number.isFinite(value)) return "0%";
  return `${Math.round(value * 100)}%`;
}

function formatMaybeNumber(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toFixed(2);
}

// ---------------------------------------------------------------------------
// RAG Evaluation Section
// ---------------------------------------------------------------------------

function RagEvalSection() {
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-semibold">RAG 观察</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          知识库 Chroma 与候选人锚点 PgVector 分开观测，避免把两类检索质量混成一个指标。
        </p>
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <RagEvalPanel />
        <CandidateAnchorRagCard />
      </div>
    </section>
  );
}
