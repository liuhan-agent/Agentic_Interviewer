"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Camera,
  CheckCircle2,
  Copy,
  FileText,
  Loader2,
  Play,
  Sparkles,
  Target,
  TrendingUp,
} from "lucide-react";
import { motion, useInView } from "framer-motion";
import {
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import type {
  Formatter,
  NameType,
  ValueType,
} from "recharts/types/component/DefaultTooltipContent";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip as UiTooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { InfoTooltip } from "@/components/interview/InfoTooltip";
import { OutcomeFeedback } from "@/components/interview/OutcomeFeedback";
import { TrainingPlanSourceBadge } from "@/components/interview/TrainingPlanSourceBadge";
import { ApiError } from "@/lib/api/client";
import { getReport } from "@/lib/api/interview";
import type {
  FinalReport,
  GetReportResponse,
  LLMErrorKind,
  RubricScore,
  TraceHealth,
  VideoAnalysis,
} from "@/lib/api/types";
import { useToast } from "@/lib/hooks/useToast";
import { inferLLMErrorKind, llmErrorKindLabel } from "@/lib/llm-config";
import {
  formatReportMarkdown,
  formatReportSummary,
} from "@/lib/report-export";
import {
  buildGrowthHints,
  buildLastSessionDelta,
  type GrowthHints as GrowthHintsType,
  type SessionDelta,
} from "@/lib/sessionDelta";
import { formatDimensionName } from "@/lib/constants/interview";
import {
  getCompletedBefore,
  getHistory,
  upsertEntry,
} from "@/lib/storage/interviewHistory";
import {
  clearVoiceReportCache,
  readVoiceReportCache,
} from "@/lib/storage/voiceReportCache";

const scoreTooltipFormatter: Formatter<ValueType, NameType> = (value) => {
  const n = Array.isArray(value) ? Number(value[0]) : Number(value);
  if (Number.isFinite(n)) {
    return [`${n.toFixed(1)} / 10`, "得分"];
  }
  return [`${value ?? "-"}`, "得分"];
};

function isSystemFallbackText(value?: string | null): boolean {
  const text = String(value ?? "").trim();
  if (!text) return false;
  const lower = text.toLowerCase();
  return [
    "evaluator llm unavailable",
    "evaluator llm failed",
    "conservative fallback",
    "评估模型暂时不可用",
    "保守兜底评价",
  ].some((marker) => lower.includes(marker.toLowerCase()));
}

function translateReportText(value?: string | null): string {
  const text = String(value ?? "");
  if (!text) return text;

  const exact: Record<string, string> = {
    "Evaluator LLM failed before returning a score. The interview continues with a conservative fallback rather than dropping the session.":
      "评估模型暂时不可用，已先使用保守评价保留本轮回答。",
    "Evaluator LLM unavailable; using conservative fallback.":
      "评估模型暂时不可用，已使用保守兜底评价。",
    "Evaluator LLM unavailable.":
      "评估模型暂时不可用。",
    "Addresses the most repeated evaluator weakness.":
      "针对本次面试中反复出现的待改进项。",
    "Demonstrate improvement via a mock re-interview.":
      "通过一次模拟复盘面试验证改进效果。",
    "Internalise learnings via a production-grade project.":
      "在一个接近真实生产场景的项目中巩固改进。",
    "Identify the most pressing weak dimension.":
      "先识别当前最需要补强的能力维度。",
  };
  if (exact[text]) return exact[text];

  const flagged = text.match(/^Evaluator flagged this in (\d+) turn\(s\) for (.+)\.$/);
  if (flagged) {
    return `评估器在 ${flagged[1]} 轮「${formatDimensionName(flagged[2])}」中都标记了这个问题。`;
  }

  const drill = text.match(/^Run a targeted drill on '(.+)' in (.+)\.$/);
  if (drill) {
    return `围绕「${translateReportText(drill[1])}」做一次${formatDimensionName(drill[2])}专项练习。`;
  }

  const closeWeakness = text.match(/^Close the top-1 weakness in (.+)$/);
  if (closeWeakness) {
    return `完成「${formatDimensionName(closeWeakness[1])}」中最优先待改进项的补强。`;
  }

  const overall = text.match(/^Overall verdict: ([^@.]+)(?: @ ([^.\s]+))?\.?(?: Focus next on (.+)\.)?$/);
  if (overall) {
    const verdict = formatVerdict(overall[1].trim());
    const scoreValue = overall[2] ? Number(overall[2]) : null;
    const score =
      scoreValue !== null && Number.isFinite(scoreValue)
        ? `，总分 ${scoreValue.toFixed(2)}`
        : "";
    const focus = overall[3]
      ? `。下一阶段优先提升「${formatDimensionName(overall[3])}」。`
      : "。";
    return `综合结论：${verdict}${score}${focus}`;
  }

  return text;
}

type Fetch =
  | { phase: "loading" }
  | {
      phase: "ready";
      report: FinalReport | null;
      traceHealth: TraceHealth | null;
    }
  | { phase: "error"; message: string; errorKind: LLMErrorKind | null }
  | { phase: "running" };

export function ReportView({ sessionId }: { sessionId: string }) {
  const [state, setState] = useState<Fetch>({ phase: "loading" });
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await getReport(sessionId);
        if (cancelled) return;
        if (r.error) {
          upsertEntry({ sessionId, status: "failed" });
          setState({
            phase: "error",
            message: r.error,
            errorKind: r.error_kind ?? inferLLMErrorKind(r.error),
          });
          return;
        }
        setState({
          phase: "ready",
          report: r.final_report,
          traceHealth: r.trace_health ?? null,
        });
        if (r.final_report) {
          syncReportHistory(sessionId, r.final_report, r);
        }
        clearVoiceReportCache(sessionId);
      } catch (err) {
        if (cancelled) return;
        const cached = readVoiceReportCache(sessionId);
        if (cached) {
          syncReportHistory(sessionId, cached);
          setState({ phase: "ready", report: cached, traceHealth: null });
          return;
        }
        const msg = err instanceof Error ? err.message : String(err);
        if (isRunningReportError(err, msg)) {
          setState({ phase: "running" });
        } else {
          setState({
            phase: "error",
            message: msg,
            errorKind: inferLLMErrorKind(err),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, retryKey]);

  if (state.phase === "loading") {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  if (state.phase === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="space-y-3 pt-6 text-sm">
          <p className="font-medium text-destructive">这场面试暂时没能生成报告</p>
          <p className="text-muted-foreground">
            {friendlyReportError(state.errorKind)}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setState({ phase: "loading" });
                setRetryKey((k) => k + 1);
              }}
            >
              重新加载报告
            </Button>
            <Button asChild variant="outline" size="sm">
              <Link href="/interview/setup">重新开始一场</Link>
            </Button>
            <Button asChild variant="ghost" size="sm">
              <Link href={`/interview/${sessionId}`}>返回面试页</Link>
            </Button>
          </div>
          <details className="text-xs text-muted-foreground/70">
            <summary className="cursor-pointer select-none">
              查看技术细节
              {state.errorKind ? `：${llmErrorKindLabel(state.errorKind)}` : ""}
            </summary>
            <pre className="mt-2 whitespace-pre-wrap break-all rounded bg-secondary/30 p-2 font-mono text-[11px]">
              {state.message}
            </pre>
          </details>
        </CardContent>
      </Card>
    );
  }

  if (state.phase === "running") {
    return (
      <Card>
        <CardContent className="pt-6 text-sm text-muted-foreground">
          <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
          面试仍在进行中。返回会话：&nbsp;
          <Button asChild variant="link" className="h-auto px-1">
            <Link href={`/interview/${sessionId}`}>继续面试</Link>
          </Button>
        </CardContent>
      </Card>
    );
  }

  const report = state.report;

  if (!report) {
    return (
      <Card>
        <CardContent className="pt-6 text-sm text-muted-foreground">
          此会话未生成报告。
        </CardContent>
      </Card>
    );
  }

  const weakPracticeHref = buildWeakPracticeHref({
    ...report,
    session_id: report.session_id ?? sessionId,
  });

  return (
    <motion.div
      className="space-y-6"
      initial="hidden"
      animate="visible"
      variants={{ hidden: {}, visible: { transition: { staggerChildren: 0.12 } } }}
    >
      <motion.div variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0 } }}>
        <FallbackVerdictBanner report={report} />
      </motion.div>
      <motion.div variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0 } }}>
        <Summary report={report} />
      </motion.div>
      <motion.div variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0 } }}>
        <LastSessionDelta sessionId={sessionId} report={report} />
      </motion.div>
      <motion.div variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0 } }}>
        <GrowthHints />
      </motion.div>
      <motion.div variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0 } }}>
        <SelfIntroFocus selfIntro={report.self_intro} />
      </motion.div>
      <motion.div variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0 } }}>
        <QualityCenter
          report={report}
          traceHealth={state.traceHealth}
          sessionId={sessionId}
        />
      </motion.div>
      <motion.div variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0 } }}>
        <DimensionRadar scores={report.dimension_scores} />
      </motion.div>
      <motion.div variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0 } }}>
        <DimensionScores scores={report.dimension_scores} />
      </motion.div>
      <motion.div variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0 } }}>
        <TrainingPlanCard
          plan={report.training_plan}
          weakPracticeHref={weakPracticeHref}
          sourceSessionId={report.session_id ?? sessionId}
        />
      </motion.div>
      <motion.div variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0 } }}>
        <OutcomeFeedback sessionId={sessionId} />
      </motion.div>
      <motion.div variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0 } }}>
        <VideoInsightsCard analysis={report.video_analysis} />
      </motion.div>
      <motion.div variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0 } }}>
        <Actions
          sessionId={sessionId}
          report={report}
          weakPracticeHref={weakPracticeHref}
        />
      </motion.div>
    </motion.div>
  );
}

function syncReportHistory(
  sessionId: string,
  report: FinalReport,
  metadata?: Pick<GetReportResponse, "created_at" | "updated_at">,
): void {
  // Sync local history index so /interview/history reflects status & score.
  // upsertEntry is a no-op merge if the row was created by SetupForm.
  const growthSignal = displayGrowthSignal(report);
  upsertEntry({
    sessionId,
    createdAt: metadata?.created_at ?? undefined,
    updatedAt: metadata?.updated_at ?? undefined,
    status: "done",
    overallScore:
      typeof report.overall_score === "number"
        ? report.overall_score
        : undefined,
    dimensionScores: compactDimensionScores(report.dimension_scores),
    growthSignal,
    overallVerdict:
      typeof report.overall_verdict === "string"
        ? report.overall_verdict
        : undefined,
  });
}

function isRunningReportError(err: unknown, message: string): boolean {
  return (
    (err instanceof ApiError && err.status === 409) ||
    message.startsWith("409")
  );
}

function friendlyReportError(kind: LLMErrorKind | null): string {
  switch (kind) {
    case "auth":
      return "保存的模型密钥可能已过期、被撤销，或没有当前模型权限。更新密钥后再开始一场即可。";
    case "quota":
      return "当前模型配置的额度不足或余额耗尽。可以换一个 Key，或到厂商控制台检查余额。";
    case "rate_limit":
      return "模型服务暂时被限流了。稍后再试，或换一个额度更充足的 Key。";
    case "timeout":
    case "network":
      return "网络或模型服务暂时不稳定。这通常不是你的回答问题，稍后重试就好。";
    case "misconfig":
      return "模型名称、服务商或 Base URL 可能不匹配。检查 API 设置后再试。";
    default:
      return "面试过程中模型调用失败了。你可以查看技术细节，或调整 API 设置后重新开始。";
  }
}

function displayGrowthSignal(report: FinalReport): string | undefined {
  const scoreSignal = scoreBasedGrowthSignal(report);
  return scoreSignal ?? reportGrowthSignal(report);
}

function scoreBasedGrowthSignal(report: FinalReport): string | undefined {
  const existingSignal = reportGrowthSignal(report);
  if (existingSignal === "cancelled" || report.cancelled === true) {
    return "cancelled";
  }

  const score = asNumber(report.overall_score);
  if (score === null) return undefined;

  const threshold = asNumber(report.quality_threshold) ?? 7.5;
  if (score >= threshold + 0.5) return "excellent";
  if (score >= threshold) return "target_met";
  if (score >= threshold - 1.5) return "near_target";
  return "needs_focus";
}

function AnimatedScore({ score, max = 10 }: { score: number; max?: number }) {
  const [displayed, setDisplayed] = useState(0);
  const ref = useRef<HTMLSpanElement>(null);
  const inView = useInView(ref, { once: true });

  useEffect(() => {
    if (!inView) return;
    const duration = 800;
    const start = performance.now();
    function tick(now: number) {
      const elapsed = now - start;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplayed(score * eased);
      if (progress < 1) requestAnimationFrame(tick);
    }
    requestAnimationFrame(tick);
  }, [inView, score]);

  return (
    <span ref={ref} className="tabular-nums">
      {displayed.toFixed(1)}
      <span className="ml-1 text-base font-normal text-muted-foreground">
        /{max}
      </span>
    </span>
  );
}

function Summary({ report }: { report: FinalReport }) {
  const verdict = displayGrowthSignal(report);
  const variant = verdictVariant(verdict);

  return (
    <Card className="overflow-hidden">
      <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/[0.02] via-transparent to-transparent pointer-events-none" />
      <CardHeader className="relative">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="mb-2 flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10">
                <TrendingUp className="h-4 w-4 text-emerald-400" />
              </div>
              <CardTitle className="text-2xl">面试报告</CardTitle>
            </div>
            <CardDescription>
              基于面试全过程的追问、评分与复盘结果。
            </CardDescription>
          </div>
          <div className="flex flex-col items-end gap-2">
            <div className="flex flex-wrap justify-end gap-2">
              {verdict && (
                <Badge variant={variant} className="px-3 py-1 text-sm">
                  {formatVerdict(verdict)}
                </Badge>
              )}
              <CoverageCautionBadge report={report} />
            </div>
            {typeof report.overall_score === "number" && (
              <span className="text-4xl font-mono font-bold">
                <AnimatedScore score={report.overall_score} />
              </span>
            )}
          </div>
        </div>
      </CardHeader>
      {report.summary && (
        <CardContent>
          <Separator className="mb-4" />
          <p className="text-sm leading-relaxed text-muted-foreground">
            {translateReportText(report.summary)}
          </p>
        </CardContent>
      )}
    </Card>
  );
}

function CoverageCautionBadge({ report }: { report: FinalReport }) {
  const warnings = asArray(report.coverage_warnings);
  if (warnings.length === 0) return null;

  return (
    <Badge
      variant="outline"
      className="gap-1.5 border-amber-500/35 bg-amber-500/10 px-2.5 py-1 text-xs text-amber-200"
    >
      <AlertTriangle className="h-3.5 w-3.5" />
      <span>部分维度待确认</span>
      <InfoTooltip label="说明部分维度待确认">
        部分维度尚未完全通过或证据不足，详情见下方评分维度。
      </InfoTooltip>
    </Badge>
  );
}

// Banner that warns users the report is "indicative" when a high
// share of turns were scored by the conservative fallback path
// (audit follow-up B3). Threshold 30% picks up the obvious "LLM was
// flaky for this whole session" case while staying quiet for the
// occasional one-turn hiccup.
const FALLBACK_BANNER_THRESHOLD = 0.3;

function FallbackVerdictBanner({ report }: { report: FinalReport }) {
  const total =
    typeof report.total_turns === "number" ? report.total_turns : 0;
  const fallbackCount =
    typeof report.evaluator_fallback_count === "number"
      ? report.evaluator_fallback_count
      : 0;
  if (total <= 0 || fallbackCount <= 0) return null;
  const ratio = fallbackCount / total;
  if (ratio < FALLBACK_BANNER_THRESHOLD) return null;

  const percent = Math.round(ratio * 100);
  return (
    <Card className="border-amber-500/30 bg-amber-500/[0.06]">
      <CardContent className="flex items-start gap-3 py-3 text-sm">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
        <div>
          <p className="font-medium text-amber-200">
            评分仅供参考 · 本场约 {percent}% 的回答走了保守评分路径
          </p>
          <p className="text-xs leading-relaxed text-muted-foreground">
            评估模型当时不稳定，{fallbackCount} / {total}{" "}
            轮使用了兜底评分。整体分数可能偏保守，建议稍后重新练习一场以获得更准确的反馈。
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

// Cross-session "vs 上一次练习" widget. Reads localStorage history via
// ``getCompletedBefore`` inside an effect (so SSR doesn't crash) and
// renders nothing when there is no signal — keeping the report page
// quiet for first-time users instead of showing an empty placeholder.
function LastSessionDelta({
  sessionId,
  report,
}: {
  sessionId: string;
  report: FinalReport;
}) {
  const [delta, setDelta] = useState<SessionDelta | null>(null);

  useEffect(() => {
    const previous = getCompletedBefore(sessionId);
    if (!previous) {
      setDelta(null);
      return;
    }
    setDelta(
      buildLastSessionDelta(
        {
          overallScore: report.overall_score,
          dimensionScores: compactDimensionScores(report.dimension_scores),
        },
        {
          overallScore: previous.overallScore,
          dimensionScores: previous.dimensionScores,
        },
      ),
    );
  }, [sessionId, report]);

  if (!delta) return null;

  return (
    <Card className="border-emerald-500/20 bg-emerald-500/[0.04]">
      <CardContent className="space-y-2 py-4 text-sm">
        <div className="flex items-center gap-2 text-emerald-300">
          <TrendingUp className="h-3.5 w-3.5" />
          <span className="text-xs font-medium uppercase tracking-wider">
            vs 上一次练习
          </span>
          <InfoTooltip label="说明 vs 上一次练习">
            只基于当前浏览器保存的历史记录，比较本场和上一场完成面试的总分与维度分变化。
          </InfoTooltip>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
          {delta.overall !== null && (
            <span className="font-mono">
              总分{" "}
              <span
                className={
                  delta.overall > 0
                    ? "text-emerald-300"
                    : delta.overall < 0
                      ? "text-amber-300"
                      : ""
                }
              >
                {delta.overall > 0 ? "+" : ""}
                {delta.overall.toFixed(1)}
              </span>
            </span>
          )}
          {delta.dimensions.map((d) => (
            <span key={d.dimension} className="font-mono">
              {d.label}{" "}
              <span
                className={
                  d.delta > 0
                    ? "text-emerald-300"
                    : d.delta < 0
                      ? "text-amber-300"
                      : ""
                }
              >
                {d.delta > 0 ? "+" : ""}
                {d.delta.toFixed(1)}
              </span>
            </span>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// Cross-session "持续薄弱 / 连续提升" widget. Renders nothing when
// the local history is too short (<3 scored sessions) or no signal
// emerges, so first-time and casual users don't see empty state.
// Inspired by Hermes Agent's episodic-memory pattern (audit
// cross-reference): make trends across sessions explicit instead of
// hoping users do the math from the line chart.
function GrowthHints() {
  const [hints, setHints] = useState<GrowthHintsType | null>(null);

  useEffect(() => {
    try {
      const history = getHistory();
      setHints(buildGrowthHints(history));
    } catch {
      setHints(null);
    }
  }, []);

  if (!hints) return null;
  const hasWeak = hints.persistentWeak.length > 0;
  const hasImprove = hints.consecutiveImprove.length > 0;
  if (!hasWeak && !hasImprove) return null;

  return (
    <Card>
      <CardContent className="space-y-3 py-4 text-sm">
        <div className="flex items-center gap-2 text-muted-foreground">
          <Sparkles className="h-3.5 w-3.5 text-emerald-400" />
          <span className="text-xs font-medium uppercase tracking-wider">
            跨场练习信号
          </span>
          <InfoTooltip label="说明跨场练习信号">
            只基于当前浏览器保存的历史记录，识别最近三场里的持续薄弱项和连续提升项。
          </InfoTooltip>
        </div>
        <div className="grid gap-3 md:grid-cols-2">
          {hasImprove && (
            <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/[0.04] p-3">
              <p className="mb-2 text-xs font-medium text-emerald-300">
                连续提升 · 保持节奏
              </p>
              <ul className="space-y-1.5 text-xs leading-relaxed text-muted-foreground">
                {hints.consecutiveImprove.map((d) => (
                  <li key={d.dimension} className="flex items-center gap-2">
                    <span className="font-mono text-emerald-300">
                      +{d.delta.toFixed(1)}
                    </span>
                    <span>{d.label}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {hasWeak && (
            <div className="rounded-lg border border-amber-500/20 bg-amber-500/[0.04] p-3">
              <p className="mb-2 text-xs font-medium text-amber-300">
                持续薄弱 · 集中突破
              </p>
              <ul className="space-y-1.5 text-xs leading-relaxed text-muted-foreground">
                {hints.persistentWeak.map((d) => (
                  <li key={d.dimension} className="flex items-center gap-2">
                    <span className="font-mono text-amber-300">
                      {d.delta.toFixed(1)}
                    </span>
                    <span>{d.label}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function SelfIntroFocus({
  selfIntro,
}: {
  selfIntro?: FinalReport["self_intro"];
}) {
  const profile = selfIntro?.profile;
  if (!profile || typeof profile !== "object") return null;

  const summary =
    typeof profile.summary === "string" && profile.summary.trim()
      ? profile.summary.trim()
      : "";
  const groups = [
    {
      title: "强调项目",
      caption: "后续追问优先贴近这些经历",
      items: profile.emphasized_projects,
      Icon: Target,
      headingClassName: "text-sky-300",
      badgeClassName: "border-sky-500/25 bg-sky-500/10 text-sky-200",
    },
    {
      title: "强调技能",
      caption: "候选人主动抛出的技术关键词",
      items: profile.emphasized_skills,
      Icon: CheckCircle2,
      headingClassName: "text-emerald-300",
      badgeClassName: "border-emerald-500/25 bg-emerald-500/10 text-emerald-200",
    },
    {
      title: "希望展开",
      caption: "适合继续深挖的能力方向",
      items: profile.preferred_focus,
      Icon: TrendingUp,
      headingClassName: "text-violet-300",
      badgeClassName: "border-violet-500/25 bg-violet-500/10 text-violet-200",
    },
    {
      title: "需要澄清",
      caption: "开场信息不足或需核对的点",
      items: profile.clarification_targets,
      Icon: AlertTriangle,
      headingClassName: "text-amber-300",
      badgeClassName: "border-amber-500/30 bg-amber-500/10 text-amber-200",
    },
  ]
    .map((group) => ({
      ...group,
      items: Array.isArray(group.items)
        ? group.items.filter(
            (item): item is string =>
              typeof item === "string" && item.trim().length > 0,
          )
        : [],
    }))
    .filter((group) => group.items.length > 0);

  if (!summary && groups.length === 0) return null;
  const shouldSpanLastGroup = groups.length % 2 === 1;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-emerald-400" />
          <CardTitle className="text-base">自我介绍重点</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {summary && (
          <div className="rounded-lg border border-border/70 bg-muted/25 px-4 py-3">
            <p className="mb-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              开场摘要
            </p>
            <p className="max-w-[72ch] text-sm leading-7 text-foreground/90">
              {summary}
            </p>
          </div>
        )}
        {groups.length > 0 && (
          <div className="grid gap-3 md:grid-cols-2">
            {groups.map(({ Icon, ...group }, idx) => (
              <div
                key={group.title}
                className={`rounded-lg border border-border/60 bg-background/35 p-3 ${
                  shouldSpanLastGroup && idx === groups.length - 1
                    ? "md:col-span-2"
                    : ""
                }`}
              >
                <div className="mb-3 flex items-start gap-2">
                  <Icon
                    aria-hidden="true"
                    className={`mt-0.5 h-3.5 w-3.5 ${group.headingClassName}`}
                  />
                  <div className="min-w-0">
                    <p className={`text-xs font-semibold ${group.headingClassName}`}>
                      {group.title}
                    </p>
                    <p className="mt-0.5 text-[11px] leading-snug text-muted-foreground">
                      {group.caption}
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {group.items.map((item) => (
                    <Badge
                      key={`${group.title}-${item}`}
                      variant="outline"
                      className={`max-w-full break-words px-2.5 py-1 text-xs ${group.badgeClassName}`}
                    >
                      {item}
                    </Badge>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

type QualityMetric = {
  label: string;
  value: string;
  description: string;
  variant: "success" | "warn" | "outline";
};

type QualityMetricTone = {
  cardClassName: string;
  labelClassName: string;
  valueClassName: string;
  highlightClassName: string;
};

function qualityMetricTone(variant: QualityMetric["variant"]): QualityMetricTone {
  if (variant === "success") {
    return {
      cardClassName: "border-emerald-500/20 bg-emerald-500/[0.035]",
      labelClassName: "text-emerald-300",
      valueClassName:
        "border-emerald-500/25 bg-emerald-500/10 text-emerald-200",
      highlightClassName: "text-emerald-200",
    };
  }
  if (variant === "warn") {
    return {
      cardClassName: "border-amber-500/25 bg-amber-500/[0.045]",
      labelClassName: "text-amber-300",
      valueClassName: "border-amber-500/30 bg-amber-500/10 text-amber-200",
      highlightClassName: "text-amber-200",
    };
  }
  return {
    cardClassName: "border-border/70 bg-background/35",
    labelClassName: "text-muted-foreground",
    valueClassName: "border-border bg-secondary/40 text-foreground/80",
    highlightClassName: "text-sky-200",
  };
}

function splitMetricDescription(description: string): {
  lead: string;
  rest: string;
} {
  const colonIndex = description.indexOf("：");
  if (colonIndex < 0) {
    return { lead: "", rest: description };
  }
  return {
    lead: description.slice(0, colonIndex + 1),
    rest: description.slice(colonIndex + 1),
  };
}

function QualityMetricCard({ metric }: { metric: QualityMetric }) {
  const tone = qualityMetricTone(metric.variant);
  const description = splitMetricDescription(metric.description);

  return (
    <div className={`rounded-lg border p-4 ${tone.cardClassName}`}>
      <div className="mb-3 flex items-start justify-between gap-3">
        <p
          className={`text-[11px] font-semibold uppercase tracking-[0.16em] ${tone.labelClassName}`}
        >
          {metric.label}
        </p>
        <Badge
          variant="outline"
          className={`shrink-0 font-mono text-[10px] tabular-nums ${tone.valueClassName}`}
        >
          {metric.value}
        </Badge>
      </div>
      <p className="text-sm leading-7 text-foreground/90">
        {description.lead && (
          <span className={`font-medium ${tone.highlightClassName}`}>
            {description.lead}
          </span>
        )}
        <span className="text-muted-foreground">{description.rest}</span>
      </p>
    </div>
  );
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function asStringArray(value: unknown): string[] {
  return asArray(value)
    .map((item) => String(item ?? "").trim())
    .filter(Boolean);
}

function asNumber(value: unknown): number | null {
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function summarizeCoverageWarnings(coverageWarnings: unknown[]): string {
  const dimensions = coverageWarnings
    .map((item) => formatDimensionName(String(asRecord(item).dimension ?? "")))
    .filter((dimension) => dimension.trim().length > 0);
  if (dimensions.length === 0) {
    return "本场面试覆盖的能力维度已形成可读结论。";
  }
  const visible = dimensions.slice(0, 3);
  const suffix = dimensions.length > visible.length ? `等 ${dimensions.length} 项` : "";
  return `证据不足：${visible.join("、")}${suffix}。报告已按覆盖情况保守处理。`;
}

function summarizeSkillRows(
  skillRows: Array<{ skill: string; count: number }>,
  latestTargetSkills: string[],
): string {
  const skills = skillRows.length > 0
    ? skillRows.map((row) => row.skill)
    : latestTargetSkills;
  if (skills.length === 0) {
    return "当前报告未暴露详细技能覆盖，仍保留基础题目与评分证据。";
  }
  const visible = skills.slice(0, 4);
  const suffix = skills.length > visible.length ? `等 ${skills.length} 个技能点` : "";
  return `主要追问：${visible.join("、")}${suffix}。`;
}

function formatCoverageWarningStatus(status: unknown): string {
  const value = String(status ?? "").trim();
  if (value === "pending") return "尚未追问到足够证据";
  if (value === "active") return "已追问，仍需要更多证据";
  if (value === "not_evaluated") return "尚未形成评分";
  if (value === "skipped") return "本轮已跳过";
  if (value === "evaluator_unavailable") return "评分暂时不可用";
  return value || "证据不足";
}

// Build the deep link the QualityCenter admin-only "查看记录" link uses.
// The Trace Explorer page picks up ``node`` and ``dimension`` from the
// query string and pre-scrolls to the matching card so a candidate or
// engineer can jump from a flagged dimension to the failing trace
// without manually scanning the timeline.
function buildTraceDeepLink({
  sessionId,
  dimension,
  node,
}: {
  sessionId: string;
  dimension: string;
  node: string;
}): string {
  const params = new URLSearchParams({
    sessionId,
    node,
    dimension,
  });
  return `/admin/trace?${params.toString()}`;
}

function QualityCenter({
  report,
  traceHealth,
  sessionId,
}: {
  report: FinalReport;
  traceHealth?: TraceHealth | null;
  sessionId?: string;
}) {
  const showAdminLinks = process.env.NEXT_PUBLIC_ADMIN_NAV_ENABLED === "true";
  const workflow = asRecord(report.workflow_artifacts);
  const contract = asRecord(report.contract_summary);
  const evidenceSummary = asRecord(report.evidence_summary);
  const coverageWarnings = asArray(report.coverage_warnings);
  const skillCoverage = asRecord(workflow.target_skill_coverage);
  const latestAction = asRecord(workflow.latest_selected_action);
  const latestVerification = asRecord(workflow.latest_verification);
  const policyIds = asStringArray(report.policy_ids);

  const dimensions = Object.values(report.dimension_scores ?? {});
  const passedDimensions = dimensions.filter((score) => score?.passed).length;
  const totalDimensions = dimensions.length;
  const contractTotal = asNumber(contract.total_checks) ?? 0;
  const contractYes = asNumber(contract.checks_yes) ?? 0;
  const contractPartial = asNumber(contract.checks_partial) ?? 0;
  const contractNo = asNumber(contract.checks_no) ?? 0;
  const evidenceTotal = asNumber(evidenceSummary.total_quotes) ?? 0;
  const evidenceMatched = asNumber(evidenceSummary.matched_quotes) ?? 0;
  const evidenceUnmatched = asNumber(evidenceSummary.unmatched_quotes) ?? 0;
  const skillCount = Object.keys(skillCoverage).length;
  const latestTargetSkills = asStringArray(workflow.latest_target_skills).slice(0, 6);
  const dimensionRows = Object.entries(report.dimension_scores ?? {}).map(
    ([dimension, score]) => ({
      dimension,
      label: formatDimensionName(dimension),
      score,
      badge: dimensionBadgeMeta(score),
      scoreLabel: dimensionScoreLabel(score),
    }),
  );
  const skillRows = Object.entries(skillCoverage)
    .map(([skill, count]) => ({ skill, count: asNumber(count) ?? 0 }))
    .sort((a, b) => b.count - a.count || a.skill.localeCompare(b.skill))
    .slice(0, 8);

  const coverageMetric: QualityMetric = {
    label: "能力覆盖",
    value:
      totalDimensions > 0
        ? `${passedDimensions}/${totalDimensions}`
        : coverageWarnings.length > 0
          ? `${coverageWarnings.length} 项待补`
          : "已记录",
    description:
      coverageWarnings.length > 0
        ? summarizeCoverageWarnings(coverageWarnings)
        : summarizeCoverageWarnings([]),
    variant: coverageWarnings.length > 0 ? "warn" : "success",
  };

  const personalizationMetric: QualityMetric = {
    label: "题目个性化",
    value: skillCount > 0 ? `${skillCount} 个技能点` : "基础个性化",
    description: summarizeSkillRows(skillRows, latestTargetSkills),
    variant: skillCount > 0 ? "success" : "outline",
  };

  const trustMetric: QualityMetric = (() => {
    // ``trace_health`` is the same coverage signal Trace Explorer uses;
    // when the engineer surface says ``partial``/``missing`` the
    // candidate-facing card must not pretend the interview ran cleanly.
    if (traceHealth === "partial" || traceHealth === "missing") {
      return {
        label: "评分可信度",
        value: traceHealth === "missing" ? "记录缺失" : "流程未完整",
        description:
          traceHealth === "missing"
            ? "流程记录缺失，无法核验评分或学习节点；评分仅供参考。"
            : "流程记录未完整闭环，评分或学习节点存在缺口；评分仅供参考。",
        variant: "warn",
      };
    }
    return {
      label: "评分可信度",
      value:
        contractTotal > 0
          ? `${contractYes + contractPartial}/${contractTotal}`
          : Object.keys(latestVerification).length > 0
            ? "已复核"
            : "基础评分",
      description:
        contractTotal > 0
          ? "评分检查项已有 yes / partial / no 归因，便于解释结论。"
          : "报告包含评分结果；更细的合同检查项需要后端继续补充。",
      variant:
        contractTotal > 0 && contractYes + contractPartial < contractTotal
          ? "warn"
          : "success",
    };
  })();
  const evidenceMetric: QualityMetric =
    evidenceTotal > 0
      ? {
          label: "评分依据",
          value: `${evidenceMatched}/${evidenceTotal}`,
          description:
            evidenceUnmatched > 0
              ? `评分所引用的回答片段中，${evidenceMatched} 条可回查到原始问答，${evidenceUnmatched} 条暂未匹配；评分仅供参考。`
              : `评分所引用的回答片段中，${evidenceMatched} 条可回查到原始问答。`,
          variant: evidenceUnmatched > 0 ? "warn" : "success",
        }
      : {
          label: "评分依据",
          value: "未生成引用",
          description:
            "本场报告尚未生成可回查的评分引用；分数仍会展示，建议结合问答记录一起判断。",
          variant: "warn",
        };
  const qualityMetrics = [
    coverageMetric,
    personalizationMetric,
    trustMetric,
    evidenceMetric,
  ];

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-4 w-4 text-emerald-400" />
              <CardTitle className="text-base">面试质量中心</CardTitle>
            </div>
            <CardDescription className="mt-1">
              检查本场面试的能力覆盖、技能覆盖 Top、评分依据、证据可回溯与流程记录完整性。
            </CardDescription>
          </div>
          {showAdminLinks && (
            <Button asChild variant="outline" size="sm" className="shrink-0 gap-1.5 text-xs">
              <Link href="/admin">查看后台观测</Link>
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid gap-3 md:grid-cols-2">
          {qualityMetrics.map((metric) => (
            <QualityMetricCard key={metric.label} metric={metric} />
          ))}
        </div>

        {(coverageWarnings.length > 0 || skillRows.length > 0) && (
          <div className="grid gap-4 md:grid-cols-2">
            {coverageWarnings.length > 0 && (
              <div className="rounded-lg border border-amber-500/25 bg-amber-500/[0.035] p-4">
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-amber-300">
                  证据还不够的能力
                </p>
                <p className="mb-4 text-xs leading-relaxed text-amber-100/70">
                  这些能力维度还没有足够回答证据，报告会更保守地看待相关结论。
                </p>
                <ul className="space-y-2 text-xs leading-relaxed">
                  {coverageWarnings.slice(0, 4).map((item, idx) => {
                    const warning = asRecord(item);
                    const dimension = String(warning.dimension ?? `dim-${idx}`);
                    const showDeepLink =
                      showAdminLinks &&
                      sessionId &&
                      traceHealth !== "missing";
                    return (
                      <li
                        key={`${dimension}-${idx}`}
                        className="flex items-center justify-between gap-3 rounded-md border border-amber-500/15 bg-background/45 px-3 py-2"
                      >
                        <span className="text-muted-foreground">
                          {formatDimensionName(dimension)}：
                          {formatCoverageWarningStatus(warning.status)}
                        </span>
                        {showDeepLink && (
                          <Link
                            href={buildTraceDeepLink({
                              sessionId,
                              dimension,
                              node: "evaluator",
                            })}
                            className="shrink-0 text-[11px] text-amber-300 underline-offset-2 hover:underline"
                          >
                            查看记录
                          </Link>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
            {skillRows.length > 0 && (
              <div className="rounded-lg border border-sky-500/15 bg-sky-500/[0.025] p-4">
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-sky-300">
                  技能覆盖 Top
                </p>
                <div className="flex flex-wrap gap-2">
                  {skillRows.slice(0, 6).map((row) => (
                    <Badge
                      key={row.skill}
                      variant="outline"
                      className="gap-1.5 border-sky-500/20 bg-background/45 px-2.5 py-1 text-foreground/90"
                    >
                      {row.skill}
                      <span className="font-mono text-[10px] text-sky-200">×{row.count}</span>
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {dimensionRows.length > 0 && (
          <div className="rounded-lg border border-violet-500/15 bg-violet-500/[0.025] p-4">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-violet-300">
                维度覆盖明细
              </p>
              <Badge
                variant="outline"
                className="border-violet-500/20 bg-background/45 font-mono text-[10px] text-violet-200"
              >
                {totalDimensions} 个维度
              </Badge>
            </div>
            <p className="mb-4 text-xs leading-relaxed text-violet-100/65">
              展示各能力维度的评分结果，以及结论是否已有足够回答证据支撑。
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              {dimensionRows.map((row) => (
                <div
                  key={row.dimension}
                  className="rounded-md border border-violet-500/15 bg-background/45 px-3 py-2"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium text-foreground/90">
                      {row.label}
                    </span>
                    <Badge
                      variant="outline"
                      className={`shrink-0 ${dimensionBadgeClass(row.badge.tone)}`}
                    >
                      {row.badge.label}
                    </Badge>
                  </div>
                  <p className="mt-2 font-mono text-[11px] text-violet-100/75">
                    {row.scoreLabel}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        <details className="rounded-lg border bg-secondary/20 p-3 text-xs">
          <summary className="cursor-pointer select-none font-medium text-muted-foreground">
            查看开发者细节
          </summary>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            这些信息用于排查报告生成链路，包括评分合同检查、策略命中和最近一次流程动作。
          </p>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <DeveloperFact
              label="评分检查项"
              code="contract_checks"
              description="合同检查项的通过分布，用来判断评分结论是否满足内部验收规则。"
              value={
                contractTotal > 0
                  ? `yes=${contractYes}, partial=${contractPartial}, no=${contractNo}, total=${contractTotal}`
                  : "未记录"
              }
            />
            <DeveloperFact
              label="策略路径"
              code="policy_ids"
              description="本场追问和报告生成命中过的策略，用来复盘系统为什么这样选题。"
              value={policyIds.length > 0 ? policyIds.join(", ") : "未记录"}
            />
            <DeveloperFact
              label="最近策略动作"
              code="latest_selected_action"
              description="题目规划器最近一次选择的动作，常用于检查追问是否按预期切换。"
              value={String(latestAction.id ?? "未记录")}
            />
            <DeveloperFact
              label="最近流程校验"
              code="latest_verification"
              description="最近一次流程校验摘要，用来定位评分、学习节点或 trace 是否缺失。"
              value={summarizeVerification(latestVerification)}
            />
          </div>
        </details>
      </CardContent>
    </Card>
  );
}

function StatPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-background/60 p-2">
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 font-mono text-sm tabular-nums">{value}</p>
    </div>
  );
}

function DeveloperFact({
  label,
  code,
  description,
  value,
}: {
  label: string;
  code: string;
  description: string;
  value: string;
}) {
  return (
    <div className="rounded-md border border-border/50 bg-background/55 p-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <p className="text-sm font-semibold text-foreground/95">{label}</p>
        <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          {code}
        </p>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
        {description}
      </p>
      <p className="mt-3 rounded-md border border-border/70 bg-black/20 px-2.5 py-2 font-mono text-[11px] leading-relaxed text-foreground/90">
        {value}
      </p>
    </div>
  );
}

function summarizeVerification(verification: Record<string, unknown>): string {
  if (Object.keys(verification).length === 0) return "未记录";
  const verdict = verification.verdict ?? verification.result ?? "unknown";
  const confidence = asNumber(verification.confidence);
  return confidence === null
    ? String(verdict)
    : `${String(verdict)} · confidence=${confidence.toFixed(2)}`;
}

function AnimatedBar({
  score,
  passed,
  delay = 0,
}: {
  score: number;
  passed?: boolean;
  delay?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true });

  return (
    <div ref={ref} className="h-2 w-full overflow-hidden rounded-full bg-secondary">
      <motion.div
        initial={{ width: 0 }}
        animate={inView ? { width: `${Math.max(0, Math.min(100, score * 10))}%` } : {}}
        transition={{ duration: 0.7, delay, ease: "easeOut" }}
        className={passed ? "h-full bg-emerald-400/80" : "h-full bg-amber-400/80"}
      />
    </div>
  );
}

const DEFAULT_DIMENSION_QUALITY_THRESHOLD = 7.5;

function hasDimensionScoreEvidence(score: RubricScore): boolean {
  const hasRationale =
    typeof score.rationale === "string" && score.rationale.trim().length > 0;
  const hasWeakness =
    Array.isArray(score.weaknesses) &&
    score.weaknesses.some((item) => String(item ?? "").trim().length > 0);
  return hasRationale || hasWeakness;
}

function hasDisplayableDimensionScore(
  score: RubricScore,
): score is RubricScore & { score: number } {
  if (typeof score.score !== "number" || !Number.isFinite(score.score)) {
    return false;
  }
  if (score.score_status === "scored") return true;
  if (score.score_status) return false;
  return score.score > 0 || hasDimensionScoreEvidence(score);
}

function isDimensionScored(
  score: RubricScore,
): score is RubricScore & { score: number } {
  return hasDisplayableDimensionScore(score);
}

function dimensionScoreLabel(score: RubricScore): string {
  if (hasDisplayableDimensionScore(score)) {
    return `${score.score.toFixed(1)} / 10`;
  }
  if (score.score_status === "skipped") return "已跳过";
  if (score.score_status === "evaluator_unavailable") return "评估失败";
  if (score.score_status === "not_evaluated") return "未评分";
  return "未评分";
}

function dimensionScoreBreakdownLabel(score: RubricScore): string | null {
  const breakdown = score.score_breakdown;
  if (!breakdown || !(breakdown.scored_turn_count > 1)) return null;
  const values = [
    breakdown.latest_score,
    breakdown.best_score,
    breakdown.average_score,
    breakdown.adopted_score,
  ];
  if (!values.every((value) => Number.isFinite(value))) return null;
  return `本维度共评估 ${breakdown.scored_turn_count} 轮，最近 ${breakdown.latest_score.toFixed(1)}，最高 ${breakdown.best_score.toFixed(1)}，均值 ${breakdown.average_score.toFixed(1)}；综合分 ${breakdown.adopted_score.toFixed(1)}。`;
}

function dimensionBadgeMeta(score: RubricScore): {
  label: string;
  tone: "success" | "warning" | "muted";
} {
  if (hasDisplayableDimensionScore(score)) {
    if (score.coverage_status === "passed" || score.passed) {
      return { label: "通过", tone: "success" };
    }
    if (score.coverage_status === "coverage_limited") {
      return { label: "覆盖不足", tone: "warning" };
    }
    if (
      score.coverage_status === "below_threshold" ||
      score.score < DEFAULT_DIMENSION_QUALITY_THRESHOLD
    ) {
      return { label: "待提升", tone: "warning" };
    }
    return { label: "覆盖不足", tone: "warning" };
  }
  if (score.score_status === "skipped") {
    return { label: "已跳过", tone: "muted" };
  }
  if (score.score_status === "evaluator_unavailable") {
    return { label: "评估失败", tone: "warning" };
  }
  return { label: "未评分", tone: "muted" };
}

function dimensionBadgeClass(tone: "success" | "warning" | "muted"): string {
  if (tone === "success") {
    return "gap-1 bg-emerald-500/10 text-emerald-400 border-emerald-500/20 text-xs";
  }
  if (tone === "warning") {
    return "gap-1 bg-amber-500/10 text-amber-400 border-amber-500/20 text-xs";
  }
  return "gap-1 bg-secondary text-muted-foreground border-border text-xs";
}

type RadarAngleTickProps = {
  x?: number | string;
  y?: number | string;
  cx?: number | string;
  cy?: number | string;
  payload?: { value?: string | number };
};

function radarTickCoordinate(value: number | string | undefined, fallback = 0) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function renderRadarAngleTick(props: RadarAngleTickProps) {
  const { payload } = props;
  if (payload?.value === undefined) return null;

  const x = radarTickCoordinate(props.x);
  const y = radarTickCoordinate(props.y);
  const cx = radarTickCoordinate(props.cx, x);
  const cy = radarTickCoordinate(props.cy, y);
  const dx = x - cx;
  const dy = y - cy;
  const distance = Math.hypot(dx, dy) || 1;
  const labelX = x + (dx / distance) * 18;
  const labelY = y + (dy / distance) * 18 + (dy < 0 ? -6 : dy > 0 ? 6 : 0);
  const textAnchor = Math.abs(dx) < 8 ? "middle" : dx > 0 ? "start" : "end";

  return (
    <text
      x={labelX}
      y={labelY}
      textAnchor={textAnchor}
      dominantBaseline="central"
      fill="hsl(var(--muted-foreground))"
      fontSize={12}
      fontWeight={500}
    >
      {payload.value}
    </text>
  );
}

function DimensionRadar({
  scores,
}: {
  scores?: Record<string, RubricScore>;
}) {
  if (!scores) return null;

  const scoredEntries = Object.entries(scores).filter(
    (entry): entry is [string, RubricScore & { score: number }] =>
      hasDisplayableDimensionScore(entry[1]),
  );
  if (scoredEntries.length < 3) return null;

  const data = scoredEntries.map(([dim, s]) => ({
    dimension: formatDimensionName(dim),
    score: s.score,
    fullMark: 10,
  }));
  const excludedEntries = Object.entries(scores)
    .filter((entry) => !hasDisplayableDimensionScore(entry[1]))
    .map(([dimension]) => ({
      dimension,
      label: formatDimensionName(dimension),
    }));
  const excludedPreview = excludedEntries.slice(0, 3);
  const excludedSuffix =
    excludedEntries.length > excludedPreview.length
      ? `等 ${excludedEntries.length} 项`
      : "";

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Target className="h-4 w-4 text-emerald-400" />
          <CardTitle className="text-base">能力雷达</CardTitle>
        </div>
        <CardDescription>
          只展示已完成有效评分的维度，满分 10 分。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="mx-auto h-[360px] w-full max-w-[560px] px-2 sm:px-6">
          <ResponsiveContainer
            width="100%"
            height="100%"
            minWidth={0}
            minHeight={0}
          >
            <RadarChart
              cx="50%"
              cy="52%"
              outerRadius="76%"
              data={data}
              margin={{ top: 36, right: 32, bottom: 36, left: 32 }}
            >
              <PolarGrid
                gridType="polygon"
                stroke="hsl(var(--border))"
                strokeOpacity={0.34}
                radialLines
              />
              <PolarAngleAxis
                dataKey="dimension"
                tick={renderRadarAngleTick}
                tickLine={false}
              />
              <PolarRadiusAxis
                domain={[0, 10]}
                tickCount={6}
                tick={false}
                axisLine={false}
                tickLine={false}
              />
              <Radar
                dataKey="score"
                stroke="rgb(52 211 153)"
                fill="rgb(52 211 153)"
                fillOpacity={0.24}
                strokeWidth={3}
                dot={{
                  r: 4,
                  fill: "rgb(52 211 153)",
                  stroke: "hsl(var(--background))",
                  strokeWidth: 2,
                }}
                activeDot={{
                  r: 5,
                  fill: "rgb(52 211 153)",
                  stroke: "hsl(var(--background))",
                  strokeWidth: 2,
                }}
              />
              <Radar
                dataKey="fullMark"
                stroke="hsl(var(--foreground))"
                strokeOpacity={0.42}
                strokeWidth={1.25}
                fill="transparent"
                fillOpacity={0}
                dot={false}
                activeDot={false}
                isAnimationActive={false}
                legendType="none"
                tooltipType="none"
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: "8px",
                  fontSize: "12px",
                }}
                formatter={scoreTooltipFormatter}
                labelStyle={{ color: "hsl(var(--foreground))", fontWeight: 600 }}
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>
        {excludedEntries.length > 0 && (
          <p className="mt-3 text-center text-xs leading-relaxed text-muted-foreground/70">
            <span className="text-muted-foreground">未纳入雷达：</span>
            {excludedPreview.map((entry) => entry.label).join("、")}
            {excludedSuffix}
            <span>（暂无有效评分，详见下方评分维度）</span>
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function DimensionScores({
  scores,
}: {
  scores?: Record<string, RubricScore>;
}) {
  if (!scores || Object.keys(scores).length === 0) return null;

  const entries = Object.entries(scores);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-emerald-400" />
          <CardTitle className="text-base">评分维度</CardTitle>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {entries.map(([dim, s], i) => {
          const visibleWeaknesses = (s.weaknesses || []).filter((w) => !isSystemFallbackText(w));
          const rationale = isSystemFallbackText(s.rationale)
            ? ""
            : translateReportText(s.rationale);
          const badge = dimensionBadgeMeta(s);
          const scored = isDimensionScored(s);
          const breakdownLabel = dimensionScoreBreakdownLabel(s);

          return (
            <div key={dim} className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">
                    {formatDimensionName(dim)}
                  </span>
                  <Badge className={dimensionBadgeClass(badge.tone)}>
                    {badge.tone === "success" ? (
                      <CheckCircle2 className="h-3 w-3" />
                    ) : (
                      <AlertTriangle className="h-3 w-3" />
                    )}
                    {badge.label}
                  </Badge>
                </div>
                <span className="font-mono text-sm tabular-nums">
                  {dimensionScoreLabel(s)}
                </span>
              </div>
              {scored ? (
                <AnimatedBar score={s.score} passed={s.passed} delay={i * 0.1} />
              ) : (
                <div className="h-2 w-full rounded-full bg-secondary" />
              )}
              {breakdownLabel && (
                <p className="text-[11px] leading-relaxed text-muted-foreground/60">
                  {breakdownLabel}
                </p>
              )}
              {rationale && (
                <p className="text-xs leading-relaxed text-muted-foreground">
                  {rationale}
                </p>
              )}
              {visibleWeaknesses.length > 0 && (
                <ul className="list-disc pl-5 text-xs leading-relaxed text-muted-foreground">
                  {visibleWeaknesses.map((w, j) => (
                    <li key={j}>{translateReportText(w)}</li>
                  ))}
                </ul>
              )}
              {i < entries.length - 1 && <Separator className="mt-3" />}
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

const TRAINING_PLAN_TEXT_STYLES = {
  body: "text-[13px] font-medium leading-5 text-foreground/80",
  analysisWrap:
    "mt-2 rounded-md bg-secondary/20 px-3 py-2",
  analysisBadge:
    "mb-1 inline-flex rounded-full border border-blue-500/25 bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-blue-300/85",
  analysis:
    "text-xs leading-relaxed text-muted-foreground/70",
  weaknessTitle:
    "min-w-0 text-sm font-medium leading-5 text-foreground/85",
  diagnosisBadge:
    "mb-1 mt-2 inline-flex rounded-full border border-blue-500/25 bg-blue-500/10 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-blue-300/85",
  description:
    "mt-1 text-xs leading-relaxed text-muted-foreground/70",
  meta:
    "mt-1 inline-flex rounded-full border border-border/50 bg-secondary/20 px-2 py-0.5 text-[11px] leading-relaxed text-muted-foreground/70",
  steps:
    "rounded-md border border-border/50 bg-secondary/15 px-3 py-2 text-xs leading-5 text-foreground/60",
  evidenceWrap:
    "mt-2 rounded-md border-l-2 border-amber-500/25 bg-amber-500/[0.04] py-2 pl-3 pr-3",
  evidenceLabel:
    "mb-1 block text-[10px] font-semibold uppercase tracking-wider text-amber-300/85",
  evidence:
    "text-xs leading-relaxed text-amber-100/70 italic",
  success:
    "mt-2 rounded-md border border-emerald-500/15 bg-emerald-500/[0.04] px-3 py-2",
  successLabel:
    "text-[11px] font-semibold uppercase tracking-wider text-emerald-300/85",
  successItem:
    "text-xs leading-5 text-emerald-50/70",
} as const;

function TrainingPlanEvidence({ text }: { text: unknown }) {
  const content = String(text ?? "").trim();
  if (!content) return null;
  return (
    <div className={TRAINING_PLAN_TEXT_STYLES.evidenceWrap}>
      <span className={TRAINING_PLAN_TEXT_STYLES.evidenceLabel}>
        回答证据
      </span>
      <p className={TRAINING_PLAN_TEXT_STYLES.evidence}>{content}</p>
    </div>
  );
}

function TrainingPlanWeaknessAnalysis({ text }: { text: unknown }) {
  const content = translateReportText(String(text ?? "").trim());
  if (!content) return null;
  return (
    <div className={TRAINING_PLAN_TEXT_STYLES.analysisWrap}>
      <span className={TRAINING_PLAN_TEXT_STYLES.analysisBadge}>
        不足分析
      </span>
      <p className={TRAINING_PLAN_TEXT_STYLES.analysis}>{content}</p>
    </div>
  );
}

function TrainingPlanCard({
  plan,
  weakPracticeHref,
  sourceSessionId,
}: {
  plan?: FinalReport["training_plan"];
  weakPracticeHref?: string | null;
  sourceSessionId?: string | null;
}) {
  if (!plan) return null;
  const priorityWeaknesses = (plan.priority_weaknesses || []).filter(
    (w) =>
      !isSystemFallbackText(w.focus) && !isSystemFallbackText(w.why_it_matters),
  );
  const practiceItems = (plan.practice_plan || []).filter(
    (p) => !isSystemFallbackText(p.task) && !isSystemFallbackText(p.rationale),
  );

  const diagnosis = (plan as any).diagnosis as
    | { overall_readiness?: string; target_level_gap?: string; top_patterns?: string[]; evidence_refs?: string[] }
    | undefined;

  const planSource =
    typeof (plan as { source?: unknown }).source === "string"
      ? ((plan as { source?: string }).source as string)
      : undefined;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-emerald-500/10">
            <Target className="h-4 w-4 text-emerald-400" />
          </div>
          <span>复盘训练计划</span>
          <TrainingPlanSourceBadge source={planSource} />
        </CardTitle>
        <CardDescription>
          基于追问、评分与复盘结果，安排下一场针对性练习。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {weakPracticeHref && (
          <Button asChild className="gap-2 bg-emerald-600 hover:bg-emerald-500 text-white">
            <Link href={weakPracticeHref}>
              <Target className="h-4 w-4" />
              针对本次弱项再来一场
            </Link>
          </Button>
        )}

        {diagnosis && (diagnosis.overall_readiness || diagnosis.target_level_gap) && (
          <section className="rounded-lg border bg-gradient-to-br from-blue-500/5 to-transparent p-4">
            <h4 className="mb-2 flex items-center gap-2 text-sm font-medium">
              <Sparkles className="h-3.5 w-3.5 text-blue-400" />
              能力诊断
            </h4>
            {diagnosis.overall_readiness && (
              <p className={TRAINING_PLAN_TEXT_STYLES.body}>{diagnosis.overall_readiness}</p>
            )}
            {diagnosis.target_level_gap && (
              <div>
                <span className={TRAINING_PLAN_TEXT_STYLES.diagnosisBadge}>
                  目标差距
                </span>
                <p className={TRAINING_PLAN_TEXT_STYLES.description}>{diagnosis.target_level_gap}</p>
              </div>
            )}
            {diagnosis.top_patterns && diagnosis.top_patterns.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {diagnosis.top_patterns.map((p, i) => (
                  <Badge key={i} variant="outline" className="border-blue-500/25 bg-blue-500/5 text-blue-300 text-xs">
                    {p}
                  </Badge>
                ))}
              </div>
            )}
            {diagnosis.evidence_refs && diagnosis.evidence_refs.length > 0 && (
              <div className="mt-3 space-y-1">
                {diagnosis.evidence_refs.map((ref, i) => (
                  <TrainingPlanEvidence key={i} text={ref} />
                ))}
              </div>
            )}
          </section>
        )}

        {priorityWeaknesses.length > 0 && (
          <section>
            <h4 className="mb-3 flex items-center gap-2 text-sm font-medium">
              <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
              优先改进项
            </h4>
            <ul className="space-y-2">
              {priorityWeaknesses.map((w, i) => {
                const focusParams = new URLSearchParams({
                  focus: w.dimension,
                  length: "deep",
                });
                if (sourceSessionId) {
                  focusParams.set("resume_from", sourceSessionId);
                }
                const focusHref = w.dimension
                  ? `/interview/setup?${focusParams.toString()}`
                  : null;
                return (
                  <li
                    key={i}
                    className="rounded-lg border bg-card/50 p-3 text-sm transition-colors hover:bg-secondary/40"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="font-mono text-xs text-emerald-400/80">
                          {formatDimensionName(w.dimension)}
                        </p>
                        <p className={TRAINING_PLAN_TEXT_STYLES.weaknessTitle}>
                          {translateReportText(w.focus)}
                        </p>
                      </div>
                      {focusHref && (
                        <Button asChild variant="ghost" size="sm" className="h-6 shrink-0 gap-1 px-2 text-[11px] text-emerald-400 hover:text-emerald-300">
                          <Link href={focusHref}>
                            <Play className="h-3 w-3" />
                            练这个
                          </Link>
                        </Button>
                      )}
                    </div>
                    <TrainingPlanWeaknessAnalysis text={w.why_it_matters} />
                    {(w as any).evidence && (
                      <TrainingPlanEvidence text={(w as any).evidence} />
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {practiceItems.length > 0 && (
          <section>
            <h4 className="mb-3 flex items-center gap-2 text-sm font-medium">
              <Play className="h-3.5 w-3.5 text-blue-400" />
              练习计划
            </h4>
            <ol className="space-y-2 text-sm">
              {practiceItems.map((p, i) => (
                <li
                  key={i}
                  className="flex gap-3 rounded-lg border bg-card/45 p-3.5 transition-colors hover:bg-secondary/25"
                >
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-secondary/80 font-mono text-xs font-semibold text-foreground/90">
                    {i + 1}
                  </span>
                  <div className="min-w-0 flex-1 space-y-2.5">
                    <div className="space-y-1">
                      <p className={TRAINING_PLAN_TEXT_STYLES.body}>
                        {translateReportText(p.task)}
                      </p>
                      {p.rationale && (
                        <p className={TRAINING_PLAN_TEXT_STYLES.description}>
                          {translateReportText(p.rationale)}
                        </p>
                      )}
                      {typeof p.estimated_hours === "number" && (
                        <span className={TRAINING_PLAN_TEXT_STYLES.meta}>
                          (~{p.estimated_hours}h)
                        </span>
                      )}
                    </div>
                    {Array.isArray((p as any).steps) && (p as any).steps.length > 0 && (
                      <ol className={`list-decimal space-y-1 pl-5 ${TRAINING_PLAN_TEXT_STYLES.steps}`}>
                        {(p as any).steps.map((s: string, j: number) => (
                          <li key={j}>{s}</li>
                        ))}
                      </ol>
                    )}
                    {Array.isArray((p as any).success_criteria) && (p as any).success_criteria.length > 0 && (
                      <div className={TRAINING_PLAN_TEXT_STYLES.success}>
                        <span className={TRAINING_PLAN_TEXT_STYLES.successLabel}>验收标准</span>
                        <ul className="mt-2 space-y-1">
                          {(p as any).success_criteria.map((c: string, j: number) => (
                            <li
                              key={j}
                              className={`flex items-start gap-2 ${TRAINING_PLAN_TEXT_STYLES.successItem}`}
                            >
                              <CheckCircle2 className="mt-1 h-3.5 w-3.5 shrink-0 text-emerald-300/80" />
                              {c}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        )}

        {weakPracticeHref && (
          <Button
            asChild
            className="gap-2 bg-emerald-600 text-white hover:bg-emerald-500"
          >
            <Link href={weakPracticeHref}>
              <Target className="h-4 w-4" />
              针对本次弱项再来一场
            </Link>
          </Button>
        )}

        {plan.goals_30_60_90 && (
          <section>
            <h4 className="mb-3 flex items-center gap-2 text-sm font-medium">
              <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
              30/60/90 天训练目标
            </h4>
            <div className="grid gap-3 md:grid-cols-3">
              <GoalColumn
                label="30 天"
                items={plan.goals_30_60_90["30_days"]}
                color="emerald"
              />
              <GoalColumn
                label="60 天"
                items={plan.goals_30_60_90["60_days"]}
                color="blue"
              />
              <GoalColumn
                label="90 天"
                items={plan.goals_30_60_90["90_days"]}
                color="purple"
              />
            </div>
          </section>
        )}
      </CardContent>
    </Card>
  );
}

function GoalColumn({
  label,
  items,
  color,
}: {
  label: string;
  items?: string[];
  color: "emerald" | "blue" | "purple";
}) {
  const visibleItems = (items || []).filter((g) => !isSystemFallbackText(g));
  if (visibleItems.length === 0) return null;
  const colorMap = {
    emerald: "bg-emerald-500/10 text-emerald-400",
    blue: "bg-blue-500/10 text-blue-400",
    purple: "bg-purple-500/10 text-purple-400",
  };

  return (
    <div className="rounded-lg border bg-card/50 p-3">
      <div
        className={`mb-2 inline-block rounded-full px-2.5 py-0.5 font-mono text-[10px] uppercase tracking-wider ${colorMap[color]}`}
      >
        {label}
      </div>
      <ul className={`space-y-1.5 ${TRAINING_PLAN_TEXT_STYLES.description}`}>
        {visibleItems.map((g, i) => (
          <li key={i} className="flex gap-1.5">
            <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/40" />
            {translateReportText(g)}
          </li>
        ))}
      </ul>
    </div>
  );
}

const EMOTION_LABELS: Record<string, string> = {
  neutral: "平静",
  positive: "积极",
  nervous: "紧张",
  confused: "困惑",
};

function VideoInsightsCard({ analysis }: { analysis?: VideoAnalysis }) {
  if (!analysis) return null;
  const hasData =
    analysis.avg_engagement != null || analysis.avg_confidence != null;
  if (!hasData) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-500/10">
            <Camera className="h-4 w-4 text-violet-400" />
          </div>
          视频信号分析
        </CardTitle>
        <CardDescription>
          面试过程中通过摄像头采集的非语言特征摘要。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid gap-4 sm:grid-cols-3">
          {analysis.avg_engagement != null && (
            <div className="rounded-lg border bg-card/50 p-3 text-center">
              <p className="text-xs text-muted-foreground">平均参与度</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">
                {Math.round(analysis.avg_engagement * 100)}%
              </p>
            </div>
          )}
          {analysis.avg_confidence != null && (
            <div className="rounded-lg border bg-card/50 p-3 text-center">
              <p className="text-xs text-muted-foreground">平均自信度</p>
              <p className="mt-1 text-2xl font-semibold tabular-nums">
                {Math.round(analysis.avg_confidence * 100)}%
              </p>
            </div>
          )}
          {analysis.dominant_emotion && (
            <div className="rounded-lg border bg-card/50 p-3 text-center">
              <p className="text-xs text-muted-foreground">主导情绪</p>
              <p className="mt-1 text-2xl font-semibold">
                {EMOTION_LABELS[analysis.dominant_emotion] ??
                  analysis.dominant_emotion}
              </p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function Actions({
  sessionId,
  report,
  weakPracticeHref,
}: {
  sessionId: string;
  report: FinalReport | null;
  weakPracticeHref?: string | null;
}) {
  const { toast } = useToast();

  async function handleCopySummary() {
    if (!report) return;
    try {
      await navigator.clipboard.writeText(
        formatReportSummary(report, { sessionId }),
      );
      toast({ title: "已复制报告摘要" });
    } catch {
      toast({
        title: "复制失败，可以改用 Markdown 导出",
        variant: "destructive",
      });
    }
  }

  function handleExportMarkdown() {
    if (!report) return;
    const payload = formatReportMarkdown(report, { sessionId });
    const blob = new Blob([payload], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `interview-report-${sessionId.slice(0, 8)}.md`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button asChild variant="outline" className="gap-2">
        <Link href={`/interview/${sessionId}`}>
          <ArrowLeft className="h-4 w-4" />
          返回对话记录
        </Link>
      </Button>
      <Button asChild className="gap-2 bg-emerald-600 hover:bg-emerald-500 text-white">
        <Link href="/interview/setup">
          <Play className="h-4 w-4" />
          开始新面试
        </Link>
      </Button>
      {weakPracticeHref && (
        <Button asChild className="gap-2 bg-emerald-600 hover:bg-emerald-500 text-white">
          <Link href={weakPracticeHref}>
            <Target className="h-4 w-4" />
            针对薄弱点专项练习
          </Link>
        </Button>
      )}
      <Button asChild variant="secondary" className="gap-2">
        <Link href={`/interview/${sessionId}/replay`}>
          <Sparkles className="h-4 w-4" />
          查看训练回放
        </Link>
      </Button>
      <TooltipProvider delayDuration={150}>
        <UiTooltip>
          <TooltipTrigger asChild>
            <Button
              variant="outline"
              size="icon"
              aria-label="复制报告摘要"
              disabled={!report}
              onClick={() => void handleCopySummary()}
            >
              <Copy className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>复制报告摘要</p>
          </TooltipContent>
        </UiTooltip>
        <UiTooltip>
          <TooltipTrigger asChild>
            <Button
              variant="ghost"
              size="icon"
              aria-label="导出 Markdown"
              disabled={!report}
              onClick={handleExportMarkdown}
            >
              <FileText className="h-4 w-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>
            <p>导出 Markdown</p>
          </TooltipContent>
        </UiTooltip>
      </TooltipProvider>
    </div>
  );
}

function formatVerdict(v: string): string {
  const map: Record<string, string> = {
    strong_pass: "表现优秀",
    pass: "达到目标水平",
    borderline: "接近达标",
    fail: "重点补齐",
    excellent: "表现优秀",
    target_met: "达到目标水平",
    near_target: "接近达标",
    needs_focus: "重点补齐",
    strong_hire: "表现优秀",
    hire: "达到目标水平",
    lean_hire: "接近达标",
    lean_no_hire: "重点补齐",
    no_hire: "重点补齐",
    cancelled: "已取消",
  };
  return map[v.toLowerCase()] ?? v.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function reportGrowthSignal(report: FinalReport): string | undefined {
  const growthSignal =
    typeof report.growth_signal === "string" ? report.growth_signal : undefined;
  const overallVerdict =
    typeof report.overall_verdict === "string" ? report.overall_verdict : undefined;
  const internalVerdict =
    typeof report.verdict === "string" ? report.verdict : undefined;
  return growthSignal ?? overallVerdict ?? internalVerdict;
}

function compactDimensionScores(
  scores: FinalReport["dimension_scores"],
): Record<string, number> | undefined {
  const out: Record<string, number> = {};
  for (const [dimension, score] of Object.entries(scores ?? {})) {
    if (score && hasDisplayableDimensionScore(score)) {
      out[dimension] = score.score;
    }
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

function buildWeakPracticeHref(report: FinalReport): string | null {
  const focus: string[] = [];
  const add = (dimension: unknown) => {
    if (typeof dimension !== "string" || !dimension.trim()) return;
    if (!focus.includes(dimension)) focus.push(dimension);
  };

  for (const weakness of report.training_plan?.priority_weaknesses ?? []) {
    add(weakness.dimension);
  }
  for (const [dimension, score] of Object.entries(report.dimension_scores ?? {})) {
    if (
      score &&
      hasDisplayableDimensionScore(score) &&
      (score.passed === false || score.score < 7)
    ) {
      add(dimension);
    }
  }
  for (const item of Array.isArray(report.coverage_warnings)
    ? report.coverage_warnings
    : []) {
    if (item && typeof item === "object") {
      add((item as { dimension?: unknown }).dimension);
    }
  }

  if (focus.length === 0) return null;
  const params = new URLSearchParams();
  params.set("focus", focus.slice(0, 5).join(","));
  params.set("length", "short");
  const jobTitle = typeof report.job_title === "string" ? report.job_title : "";
  const jobLevel = typeof report.job_level === "string" ? report.job_level : "";
  if (jobTitle) params.set("job_title", jobTitle);
  if (jobLevel) params.set("job_level", jobLevel);
  if (typeof report.session_id === "string" && report.session_id) {
    params.set("resume_from", report.session_id);
  }
  return `/interview/setup?${params.toString()}`;
}

function verdictVariant(
  v?: string,
): "success" | "warn" | "destructive" | "outline" {
  if (!v) return "outline";
  const s = v.toLowerCase();
  if (
    s === "excellent" ||
    s === "target_met" ||
    s === "strong_pass" ||
    s === "pass" ||
    s === "strong_hire" ||
    s === "hire"
  ) {
    return "success";
  }
  if (s === "near_target" || s === "borderline" || s.includes("lean")) return "warn";
  if (
    s === "needs_focus" ||
    s === "fail" ||
    s.includes("no_hire") ||
    s.includes("no-hire")
  ) {
    return "destructive";
  }
  return "outline";
}
