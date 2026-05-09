"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  CheckCircle2,
  Loader2,
  Play,
  RotateCcw,
  Target,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { TrainingPlanSourceBadge } from "@/components/interview/TrainingPlanSourceBadge";
import { ApiError } from "@/lib/api/client";
import { getReplay } from "@/lib/api/interview";
import type { ReplayResponse, ReplayTurn, TrainingPlanStep } from "@/lib/api/types";
import { upsertEntry } from "@/lib/storage/interviewHistory";

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
};

type Fetch =
  | { phase: "loading" }
  | { phase: "ready"; replay: ReplayResponse }
  | { phase: "error"; message: string };

export function ReplayView({ sessionId }: { sessionId: string }) {
  const [state, setState] = useState<Fetch>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const replay = await getReplay(sessionId);
        if (!cancelled) {
          syncReplayHistory(sessionId, replay);
          setState({ phase: "ready", replay });
        }
      } catch (err) {
        if (cancelled) return;
        setState({
          phase: "error",
          message: friendlyReplayError(err),
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  if (state.phase === "loading") {
    return (
      <div className="space-y-4">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (state.phase === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="space-y-3 pt-6 text-sm">
          <p className="font-medium text-destructive">暂时无法打开训练回放</p>
          <p className="text-muted-foreground">{state.message}</p>
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href={`/interview/${sessionId}/report`}>返回报告</Link>
            </Button>
            <Button asChild variant="ghost" size="sm">
              <Link href={`/interview/${sessionId}`}>返回面试页</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  const { replay } = state;
  const practiceHref = buildReplayPracticeHref(replay);
  return (
    <div className="space-y-5">
      <SummaryCard replay={replay} />
      <TimelineCard turns={replay.timeline} />
      <TrainingPlanCard
        steps={replay.training_plan?.practice_plan ?? []}
        source={
          typeof replay.training_plan?.source === "string"
            ? replay.training_plan.source
            : undefined
        }
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button asChild variant="outline" className="gap-2">
          <Link href={`/interview/${sessionId}/report`}>
            <ArrowLeft className="h-4 w-4" />
            返回报告
          </Link>
        </Button>
        <Button asChild className="gap-2 bg-emerald-600 hover:bg-emerald-500 text-white">
          <Link href="/interview/setup">
            <Play className="h-4 w-4" />
            再练一场
          </Link>
        </Button>
        {practiceHref && (
          <Button asChild className="gap-2 bg-emerald-600 hover:bg-emerald-500 text-white">
            <Link href={practiceHref}>
              <Target className="h-4 w-4" />
              针对薄弱点专项练习
            </Link>
          </Button>
        )}
      </div>
    </div>
  );
}

function buildReplayPracticeHref(replay: ReplayResponse): string | null {
  const focus: string[] = [];
  const add = (dimension: unknown) => {
    if (typeof dimension !== "string" || !dimension.trim()) return;
    if (!focus.includes(dimension)) focus.push(dimension);
  };
  for (const weakness of replay.summary.priority_weaknesses ?? []) {
    add(weakness);
  }
  for (const turn of replay.timeline ?? []) {
    if (
      typeof turn.dimension === "string" &&
      (turn.passed === false || (typeof turn.score === "number" && turn.score < 7))
    ) {
      add(turn.dimension);
    }
  }
  if (focus.length === 0) return null;
  const params = new URLSearchParams();
  params.set("focus", focus.slice(0, 5).join(","));
  params.set("length", "short");
  if (replay.summary.job_title) params.set("job_title", replay.summary.job_title);
  if (replay.summary.job_level) params.set("job_level", String(replay.summary.job_level));
  return `/interview/setup?${params.toString()}`;
}

function syncReplayHistory(sessionId: string, replay: ReplayResponse): void {
  upsertEntry({
    sessionId,
    createdAt: replay.created_at ?? undefined,
    updatedAt: replay.updated_at ?? undefined,
    status: "done",
    overallScore:
      typeof replay.summary.overall_score === "number"
        ? replay.summary.overall_score
        : undefined,
    growthSignal:
      typeof replay.summary.growth_signal === "string"
        ? replay.summary.growth_signal
        : undefined,
    overallVerdict:
      typeof replay.summary.overall_verdict === "string"
        ? replay.summary.overall_verdict
        : undefined,
  });
}

function SummaryCard({ replay }: { replay: ReplayResponse }) {
  const summary = replay.summary;
  return (
    <Card className="border-emerald-500/20 bg-emerald-500/5">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <RotateCcw className="h-4 w-4 text-emerald-400" />
          本场训练回放
        </CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 text-sm sm:grid-cols-3">
        <Metric label="岗位" value={summary.job_title || "未填写"} />
        <Metric label="轮次" value={`${summary.total_turns ?? replay.timeline.length} 轮`} />
        <Metric
          label="总分"
          value={
            typeof summary.overall_score === "number"
              ? summary.overall_score.toFixed(1)
              : "-"
          }
        />
        {(summary.priority_weaknesses ?? []).length > 0 && (
          <div className="sm:col-span-3">
            <p className="mb-2 text-xs text-muted-foreground">优先补强</p>
            <div className="flex flex-wrap gap-2">
              {summary.priority_weaknesses?.map((item) => (
                <Badge key={item} variant="secondary">
                  {item}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-card/60 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-medium">{value}</p>
    </div>
  );
}

function TimelineCard({ turns }: { turns: ReplayTurn[] }) {
  if (turns.length === 0) {
    return (
      <Card>
        <CardContent className="py-8 text-sm text-muted-foreground">
          这场面试还没有可展示的逐轮记录，但最终报告仍可用于复盘。
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {turns.map((turn, index) => (
        <Card key={`${turn.turn_idx}-${index}`}>
          <CardHeader>
            <CardTitle className="flex flex-wrap items-center gap-2 text-base">
              <span>第 {index + 1} 轮</span>
              {turn.dimension && (
                <Badge variant="outline">{formatDimension(turn.dimension)}</Badge>
              )}
              {typeof turn.score === "number" && (
                <Badge variant="secondary">{turn.score.toFixed(1)} 分</Badge>
              )}
              {turn.passed && <CheckCircle2 className="h-4 w-4 text-emerald-400" />}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 text-sm">
            <Block title="问题" value={turn.question} />
            <Block title="你的回答" value={turn.answer} />
            <Block title="评分依据" value={turn.rationale} />
            <ListBlock title="亮点" values={turn.strengths ?? []} />
            <ListBlock title="可提升" values={turn.weaknesses ?? []} />
            {turn.next_step && (
              <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3">
                <p className="mb-1 flex items-center gap-1.5 text-xs font-medium text-emerald-400">
                  <Target className="h-3.5 w-3.5" />
                  下一步练习
                </p>
                <p className="text-muted-foreground">{turn.next_step}</p>
              </div>
            )}
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

function TrainingPlanCard({
  steps,
  source,
}: {
  steps: TrainingPlanStep[];
  source: string | undefined;
}) {
  if (steps.length === 0) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <span>后续训练建议</span>
          <TrainingPlanSourceBadge source={source} />
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ol className="space-y-2 text-sm">
          {steps.map((step, index) => (
            <li key={`${step.task}-${index}`} className="rounded-lg border bg-card/60 p-3">
              <p className="font-medium">{step.task}</p>
              {step.rationale && (
                <p className="mt-1 text-muted-foreground">{step.rationale}</p>
              )}
            </li>
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

function Block({ title, value }: { title: string; value?: string | null }) {
  if (!value) return null;
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted-foreground">{title}</p>
      <p className="leading-relaxed">{value}</p>
    </div>
  );
}

function ListBlock({ title, values }: { title: string; values: string[] }) {
  if (values.length === 0) return null;
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-muted-foreground">{title}</p>
      <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
        {values.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function formatDimension(id: string): string {
  return DIMENSION_LABELS[id] ?? id.replaceAll("_", " ");
}

function friendlyReplayError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 409) {
      return "训练回放会在面试完成后生成。可以先回到面试页继续答题。";
    }
    if (err.status === 401 || err.status === 403) {
      return "当前浏览器缺少这场面试的访问凭证。请从“我的面试”列表重新进入，或重新开始一场面试。";
    }
    if (err.status === 404) {
      return "没有找到这场面试的回放数据，可能已被删除或只保存在其他浏览器。";
    }
  }
  return err instanceof Error ? err.message : String(err);
}
