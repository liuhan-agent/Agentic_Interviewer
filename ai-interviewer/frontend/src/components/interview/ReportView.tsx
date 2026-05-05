"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  Camera,
  CheckCircle2,
  Download,
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
import { InfoTooltip } from "@/components/interview/InfoTooltip";
import { TrainingPlanSourceBadge } from "@/components/interview/TrainingPlanSourceBadge";
import { ApiError } from "@/lib/api/client";
import { getReport } from "@/lib/api/interview";
import type {
  FinalReport,
  LLMErrorKind,
  RubricScore,
  TraceHealth,
  VideoAnalysis,
} from "@/lib/api/types";
import { inferLLMErrorKind, llmErrorKindLabel } from "@/lib/llm-config";
import {
  buildGrowthHints,
  buildLastSessionDelta,
  type GrowthHints as GrowthHintsType,
  type SessionDelta,
} from "@/lib/sessionDelta";
import {
  getCompletedBefore,
  getHistory,
  upsertEntry,
} from "@/lib/storage/interviewHistory";
import {
  clearVoiceReportCache,
  readVoiceReportCache,
} from "@/lib/storage/voiceReportCache";

const DIMENSION_LABELS: Record<string, string> = {
  technical_depth: "技术深度",
  problem_solving: "问题解决",
  communication: "沟通表达",
  system_design: "系统设计",
  coding_quality: "代码质量",
  project_experience: "项目经验",
  product_thinking: "产品思维",
  architecture: "架构能力",
  behavioral: "行为面试",
  leadership: "技术领导力",
  user_insight: "用户洞察",
  requirement_analysis: "需求分析",
  prioritization: "优先级判断",
  metrics_thinking: "指标思维",
  stakeholder_management: "协同推进",
  user_growth: "用户增长",
  content_operations: "内容运营",
  data_analysis: "数据分析",
  campaign_execution: "活动执行",
  process_optimization: "流程优化",
  customer_discovery: "客户发现",
  solution_matching: "方案匹配",
  objection_handling: "异议处理",
  negotiation: "商务谈判",
  pipeline_management: "销售漏斗管理",
  market_insight: "市场洞察",
  brand_strategy: "品牌策略",
  campaign_planning: "营销策划",
  channel_growth: "渠道增长",
  content_creativity: "内容创意",
  talent_acquisition: "人才招聘",
  employee_relations: "员工关系",
  organization_development: "组织发展",
  policy_compliance: "制度合规",
  service_orientation: "服务意识",
  customer_empathy: "客户同理心",
  issue_diagnosis: "问题诊断",
  solution_delivery: "方案交付",
  escalation_management: "升级管理",
  retention_growth: "留存增长",
  goal_setting: "目标设定",
  team_leadership: "团队领导",
  decision_making: "决策判断",
  execution_management: "执行管理",
  cross_functional_alignment: "跨部门协同",
};

const scoreTooltipFormatter: Formatter<ValueType, NameType> = (value) => {
  const n = Array.isArray(value) ? Number(value[0]) : Number(value);
  if (Number.isFinite(n)) {
    return [`${n.toFixed(1)} / 10`, "得分"];
  }
  return [`${value ?? "-"}`, "得分"];
};

function formatDimensionName(id: string): string {
  return DIMENSION_LABELS[id] ?? id.replaceAll("_", " ");
}

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
          syncReportHistory(sessionId, r.final_report);
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
        <TrainingPlanCard plan={report.training_plan} />
      </motion.div>
      <motion.div variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0 } }}>
        <VideoInsightsCard analysis={report.video_analysis} />
      </motion.div>
      <motion.div variants={{ hidden: { opacity: 0, y: 16 }, visible: { opacity: 1, y: 0 } }}>
        <Actions sessionId={sessionId} report={report} />
      </motion.div>
    </motion.div>
  );
}

function syncReportHistory(sessionId: string, report: FinalReport): void {
  // Sync local history index so /interview/history reflects status & score.
  // upsertEntry is a no-op merge if the row was created by SetupForm.
  const growthSignal = reportGrowthSignal(report);
  upsertEntry({
    sessionId,
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
  const verdict = reportGrowthSignal(report);
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
            {verdict && (
              <Badge variant={variant} className="px-3 py-1 text-sm">
                {formatVerdict(verdict)}
              </Badge>
            )}
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
    { title: "强调项目", items: profile.emphasized_projects },
    { title: "强调技能", items: profile.emphasized_skills },
    { title: "希望展开", items: profile.preferred_focus },
    { title: "需要澄清", items: profile.clarification_targets },
  ]
    .map((group) => ({
      ...group,
      items: Array.isArray(group.items)
        ? group.items.filter((item): item is string => typeof item === "string" && item.trim().length > 0)
        : [],
    }))
    .filter((group) => group.items.length > 0);

  if (!summary && groups.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-emerald-400" />
          <CardTitle className="text-base">自我介绍重点</CardTitle>
        </div>
        <CardDescription>
          系统会把你开场主动强调的经历作为后续追问参考，不会覆盖简历解析。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {summary && (
          <p className="text-sm leading-relaxed text-muted-foreground">
            {summary}
          </p>
        )}
        {groups.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2">
            {groups.map((group) => (
              <div key={group.title} className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  {group.title}
                </p>
                <div className="flex flex-wrap gap-2">
                  {group.items.map((item) => (
                    <Badge
                      key={`${group.title}-${item}`}
                      variant="outline"
                      className="border-emerald-500/25 bg-emerald-500/5 text-emerald-300"
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

// Build the deep link the QualityCenter "查看该 trace" button uses.
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
      score: asNumber(score?.score),
      passed: Boolean(score?.passed),
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
        ? "仍有维度证据不足，报告已按覆盖情况保守处理。"
        : "本场面试覆盖的能力维度已形成可读结论。",
    variant: coverageWarnings.length > 0 ? "warn" : "success",
  };

  const personalizationMetric: QualityMetric = {
    label: "题目个性化",
    value: skillCount > 0 ? `${skillCount} 个技能点` : "基础个性化",
    description:
      skillCount > 0
        ? "问题围绕目标技能和候选人回答动态调整。"
        : "当前报告未暴露详细技能覆盖，仍保留基础题目与评分证据。",
    variant: skillCount > 0 ? "success" : "outline",
  };

  const trustMetric: QualityMetric = (() => {
    // ``trace_health`` is the same coverage signal Trace Explorer uses;
    // when the engineer surface says ``partial``/``missing`` the
    // candidate-facing card must not pretend the interview ran cleanly.
    if (traceHealth === "partial" || traceHealth === "missing") {
      return {
        label: "评分可信度",
        value: traceHealth === "missing" ? "trace 缺失" : "未走完整",
        description:
          "本场面试未走完整闭环（评分或学习节点缺失），评分仅供参考。",
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
  const evidenceMetric: QualityMetric | null =
    evidenceTotal > 0
      ? {
          label: "证据可回溯",
          value: `${evidenceMatched}/${evidenceTotal}`,
          description:
            evidenceUnmatched > 0
              ? "部分评分依据未能匹配到原回答，相关评分仅供参考。"
              : "评分依据中的原文引用可回查到你的回答。",
          variant: evidenceUnmatched > 0 ? "warn" : "success",
        }
      : null;
  const qualityMetrics = evidenceMetric
    ? [coverageMetric, personalizationMetric, trustMetric, evidenceMetric]
    : [coverageMetric, personalizationMetric, trustMetric];

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
              本场面试是否覆盖充分、题目是否贴合你、评分是否有据可查；开发者细节默认折叠。
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
        <div className={`grid gap-3 ${evidenceMetric ? "md:grid-cols-4" : "md:grid-cols-3"}`}>
          {qualityMetrics.map((metric) => (
            <div key={metric.label} className="rounded-lg border bg-card/50 p-3">
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="text-xs text-muted-foreground">{metric.label}</p>
                <Badge variant={metric.variant}>{metric.value}</Badge>
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">
                {metric.description}
              </p>
            </div>
          ))}
        </div>

        {(coverageWarnings.length > 0 || latestTargetSkills.length > 0) && (
          <div className="grid gap-4 md:grid-cols-2">
            {coverageWarnings.length > 0 && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/[0.04] p-3">
                <p className="mb-2 text-xs font-medium uppercase tracking-wider text-amber-300">
                  待补证据
                </p>
                <ul className="space-y-1.5 text-xs leading-relaxed text-muted-foreground">
                  {coverageWarnings.slice(0, 4).map((item, idx) => {
                    const warning = asRecord(item);
                    const dimension = String(warning.dimension ?? `dim-${idx}`);
                    const showDeepLink =
                      showAdminLinks &&
                      sessionId &&
                      (traceHealth === "partial" || traceHealth === "missing");
                    return (
                      <li
                        key={`${dimension}-${idx}`}
                        className="flex items-center justify-between gap-2"
                      >
                        <span>
                          {formatDimensionName(dimension)}：
                          {String(warning.status ?? "未通过")}
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
                            查看该 trace
                          </Link>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            )}
            {latestTargetSkills.length > 0 && (
              <div className="rounded-lg border bg-card/50 p-3">
                <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  本轮题目依据
                </p>
                <div className="flex flex-wrap gap-2">
                  {latestTargetSkills.map((skill) => (
                    <Badge key={skill} variant="outline">
                      {skill}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {(dimensionRows.length > 0 || skillRows.length > 0) && (
          <div className="grid gap-4 lg:grid-cols-2">
            {dimensionRows.length > 0 && (
              <div className="rounded-lg border bg-card/50 p-3">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    维度覆盖明细
                  </p>
                  <Badge variant="outline" className="font-mono text-[10px]">
                    {passedDimensions}/{totalDimensions}
                  </Badge>
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  {dimensionRows.map((row) => (
                    <div
                      key={row.dimension}
                      className="rounded-md border bg-background/60 p-2"
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-xs font-medium">
                          {row.label}
                        </span>
                        <Badge
                          variant={row.passed ? "success" : "warn"}
                          className="shrink-0 text-[10px]"
                        >
                          {row.passed ? "已通过" : "待加强"}
                        </Badge>
                      </div>
                      <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                        {row.score === null ? "未评分" : `${row.score.toFixed(1)} / 10`}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {skillRows.length > 0 && (
              <div className="rounded-lg border bg-card/50 p-3">
                <div className="mb-3 flex items-center justify-between gap-2">
                  <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                    技能覆盖 Top
                  </p>
                  <Badge variant="outline" className="font-mono text-[10px]">
                    target_skill_coverage
                  </Badge>
                </div>
                <div className="flex flex-wrap gap-2">
                  {skillRows.map((row) => (
                    <Badge
                      key={row.skill}
                      variant="secondary"
                      className="gap-1.5 font-mono text-[10px]"
                    >
                      {row.skill}
                      <span className="text-muted-foreground">×{row.count}</span>
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {(contractTotal > 0 || policyIds.length > 0) && (
          <div className="grid gap-4 lg:grid-cols-2">
            {contractTotal > 0 && (
              <div className="rounded-lg border bg-card/50 p-3">
                <p className="mb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  评分检查项
                </p>
                <div className="grid grid-cols-4 gap-2 text-center text-xs">
                  <StatPill label="总数" value={String(contractTotal)} />
                  <StatPill label="Yes" value={String(contractYes)} />
                  <StatPill label="Partial" value={String(contractPartial)} />
                  <StatPill label="No" value={String(contractNo)} />
                </div>
              </div>
            )}

            {policyIds.length > 0 && (
              <div className="rounded-lg border bg-card/50 p-3">
                <p className="mb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
                  策略路径
                </p>
                <div className="flex flex-wrap gap-2">
                  {policyIds.map((policy) => (
                    <Badge key={policy} variant="outline" className="font-mono text-[10px]">
                      {policy}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <details className="rounded-lg border bg-secondary/20 p-3 text-xs">
          <summary className="cursor-pointer select-none font-medium text-muted-foreground">
            查看开发者细节
          </summary>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <DeveloperFact
              label="latest_selected_action"
              value={String(latestAction.id ?? "未记录")}
            />
            <DeveloperFact
              label="latest_verification"
              value={summarizeVerification(latestVerification)}
            />
            <DeveloperFact
              label="policy_ids"
              value={policyIds.length > 0 ? policyIds.join(", ") : "未记录"}
            />
            <DeveloperFact
              label="contract_summary"
              value={
                contractTotal > 0
                  ? `yes=${contractYes}, partial=${contractPartial}, total=${contractTotal}`
                  : "未记录"
              }
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

function DeveloperFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-background/70 p-2">
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 break-words font-mono text-[11px] text-foreground/80">
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

function DimensionRadar({
  scores,
}: {
  scores?: Record<string, RubricScore>;
}) {
  if (!scores || Object.keys(scores).length < 3) return null;

  const data = Object.entries(scores).map(([dim, s]) => ({
    dimension: formatDimensionName(dim),
    score: typeof s.score === "number" ? s.score : 0,
    fullMark: 10,
  }));

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <Target className="h-4 w-4 text-emerald-400" />
          <CardTitle className="text-base">能力雷达</CardTitle>
        </div>
        <CardDescription>
          各评分维度的得分分布，满分 10 分。
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="mx-auto h-[320px] w-full max-w-[480px]">
          <ResponsiveContainer width="100%" height="100%">
            <RadarChart cx="50%" cy="50%" outerRadius="75%" data={data}>
              <PolarGrid
                stroke="hsl(var(--border))"
                strokeOpacity={0.5}
              />
              <PolarAngleAxis
                dataKey="dimension"
                tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 12 }}
              />
              <PolarRadiusAxis
                angle={90}
                domain={[0, 10]}
                tick={{ fill: "hsl(var(--muted-foreground))", fontSize: 10 }}
                tickCount={6}
              />
              <Radar
                dataKey="score"
                stroke="rgb(52 211 153)"
                fill="rgb(52 211 153)"
                fillOpacity={0.2}
                strokeWidth={2}
                dot={{
                  r: 4,
                  fill: "rgb(52 211 153)",
                  strokeWidth: 0,
                }}
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

          return (
            <div key={dim} className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">
                    {formatDimensionName(dim)}
                  </span>
                  {s.passed ? (
                    <Badge className="gap-1 bg-emerald-500/10 text-emerald-400 border-emerald-500/20 text-xs">
                      <CheckCircle2 className="h-3 w-3" />
                      通过
                    </Badge>
                  ) : (
                    <Badge className="gap-1 bg-amber-500/10 text-amber-400 border-amber-500/20 text-xs">
                      <AlertTriangle className="h-3 w-3" />
                      待提升
                    </Badge>
                  )}
                </div>
                <span className="font-mono text-sm tabular-nums">
                  {typeof s.score === "number" ? s.score.toFixed(1) : "-"} / 10
                </span>
              </div>
              {typeof s.score === "number" && (
                <AnimatedBar score={s.score} passed={s.passed} delay={i * 0.1} />
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

function TrainingPlanCard({
  plan,
}: {
  plan?: FinalReport["training_plan"];
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
        {diagnosis && (diagnosis.overall_readiness || diagnosis.target_level_gap) && (
          <section className="rounded-lg border bg-gradient-to-br from-blue-500/5 to-transparent p-4">
            <h4 className="mb-2 flex items-center gap-2 text-sm font-medium">
              <Sparkles className="h-3.5 w-3.5 text-blue-400" />
              能力诊断
            </h4>
            {diagnosis.overall_readiness && (
              <p className="text-sm font-medium">{diagnosis.overall_readiness}</p>
            )}
            {diagnosis.target_level_gap && (
              <p className="mt-1 text-xs text-muted-foreground">{diagnosis.target_level_gap}</p>
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
                  <p key={i} className="border-l-2 border-blue-500/20 pl-3 text-xs text-muted-foreground italic">
                    {ref}
                  </p>
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
              {priorityWeaknesses.map((w, i) => (
                <li
                  key={i}
                  className="rounded-lg border bg-card/50 p-3 text-sm transition-colors hover:bg-secondary/40"
                >
                  <div className="font-mono text-xs text-emerald-400/80">
                    {formatDimensionName(w.dimension)}
                  </div>
                  <div className="mt-1 font-medium">
                    {translateReportText(w.focus)}
                  </div>
                  {w.why_it_matters && (
                    <div className="mt-1 text-xs text-muted-foreground">
                      {translateReportText(w.why_it_matters)}
                    </div>
                  )}
                  {(w as any).evidence && (
                    <div className="mt-1 border-l-2 border-amber-500/20 pl-2 text-xs text-muted-foreground italic">
                      {(w as any).evidence}
                    </div>
                  )}
                </li>
              ))}
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
                  className="flex gap-3 rounded-lg border bg-card/50 p-3 transition-colors hover:bg-secondary/40"
                >
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-secondary font-mono text-xs font-bold">
                    {i + 1}
                  </span>
                  <div className="flex-1 space-y-2">
                    <div>
                      <span className="font-medium">
                        {translateReportText(p.task)}
                      </span>
                      {p.rationale && (
                        <span className="block text-xs text-muted-foreground">
                          {translateReportText(p.rationale)}
                        </span>
                      )}
                      {typeof p.estimated_hours === "number" && (
                        <span className="ml-1 text-xs text-muted-foreground">
                          (~{p.estimated_hours}h)
                        </span>
                      )}
                    </div>
                    {Array.isArray((p as any).steps) && (p as any).steps.length > 0 && (
                      <ol className="list-decimal pl-4 text-xs text-muted-foreground space-y-0.5">
                        {(p as any).steps.map((s: string, j: number) => (
                          <li key={j}>{s}</li>
                        ))}
                      </ol>
                    )}
                    {Array.isArray((p as any).success_criteria) && (p as any).success_criteria.length > 0 && (
                      <div className="rounded bg-emerald-500/5 px-2 py-1.5">
                        <span className="text-[10px] font-medium uppercase tracking-wider text-emerald-400/80">验收标准</span>
                        <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                          {(p as any).success_criteria.map((c: string, j: number) => (
                            <li key={j} className="flex items-start gap-1.5">
                              <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400/60" />
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

        {plan.goals_30_60_90 && (
          <section>
            <h4 className="mb-3 flex items-center gap-2 text-sm font-medium">
              <TrendingUp className="h-3.5 w-3.5 text-emerald-400" />
              里程碑
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
      <ul className="space-y-1.5 text-xs leading-relaxed">
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
}: {
  sessionId: string;
  report: FinalReport | null;
}) {
  const weakPracticeHref = report ? buildWeakPracticeHref(report) : null;

  function handleExport() {
    if (!report) return;
    const payload = JSON.stringify(report, null, 2);
    const blob = new Blob([payload], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `interview-report-${sessionId.slice(0, 8)}.json`;
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
      <Button
        variant="ghost"
        size="icon"
        aria-label="导出报告为 JSON"
        disabled={!report}
        onClick={handleExport}
      >
        <Download className="h-4 w-4" />
      </Button>
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
    if (typeof score?.score === "number" && Number.isFinite(score.score)) {
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
      (score.passed === false ||
        (typeof score.score === "number" && score.score < 7))
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
