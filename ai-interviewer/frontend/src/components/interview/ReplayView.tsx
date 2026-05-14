"use client";

import Link from "next/link";
import { useEffect, useState, type ComponentType } from "react";
import {
  ArrowLeft,
  BriefcaseBusiness,
  CheckCircle2,
  Compass,
  GitBranch,
  FileText,
  Layers3,
  Loader2,
  Play,
  RotateCcw,
  Tags,
  Target,
  UserRound,
  Wrench,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { CollapsibleAnswerBubble } from "@/components/interview/CollapsibleAnswerBubble";
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

type ContextBasisTone = "selfIntro" | "resume" | "job";

const CONTEXT_BASIS_GROUP_META: Record<
  ContextBasisTone,
  {
    Icon: ComponentType<{ className?: string }>;
    panelClassName: string;
    iconClassName: string;
  }
> = {
  selfIntro: {
    Icon: UserRound,
    panelClassName: "border-emerald-500/20 bg-emerald-500/[0.04]",
    iconClassName: "bg-emerald-500/10 text-emerald-300",
  },
  resume: {
    Icon: FileText,
    panelClassName: "border-sky-500/20 bg-sky-500/[0.04]",
    iconClassName: "bg-sky-500/10 text-sky-300",
  },
  job: {
    Icon: BriefcaseBusiness,
    panelClassName: "border-violet-500/20 bg-violet-500/[0.04]",
    iconClassName: "bg-violet-500/10 text-violet-300",
  },
};

const QUESTION_BASIS_SOURCE_CHIPS = new Set([
  "来自自我介绍",
  "来自简历",
  "来自岗位要求",
  "上一轮追问",
]);
const QUESTION_BASIS_DIMENSION_MARKER = "评分维度";
const QUESTION_BASIS_DIMENSION_LABELS = new Set(Object.values(DIMENSION_LABELS));

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
  const practiceHref = buildReplayPracticeHref(replay, sessionId);
  return (
    <div className="space-y-5">
      <SummaryCard replay={replay} />
      <ContextBasisCard basis={replay.context_basis} />
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

function buildReplayPracticeHref(
  replay: ReplayResponse,
  sourceSessionId: string,
): string | null {
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
  params.set("resume_from", sourceSessionId);
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
  const priorityGroups = groupReplayPriorityItems(summary.priority_items);
  const hasPriorityItems =
    priorityGroups.weakness.length > 0 ||
    priorityGroups.coverage_limited.length > 0;
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
        {hasPriorityItems ? (
          <div className="space-y-3 sm:col-span-3">
            <PriorityItemGroup title="薄弱点" items={priorityGroups.weakness} />
            <PriorityItemGroup
              title="补充证据"
              items={priorityGroups.coverage_limited}
            />
          </div>
        ) : (
          (summary.priority_weaknesses ?? []).length > 0 && (
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
          )
        )}
      </CardContent>
    </Card>
  );
}

type ReplayPriorityItem = NonNullable<
  ReplayResponse["summary"]["priority_items"]
>[number];

function groupReplayPriorityItems(
  items: ReplayResponse["summary"]["priority_items"],
): {
  weakness: ReplayPriorityItem[];
  coverage_limited: ReplayPriorityItem[];
} {
  const groups = {
    weakness: [] as ReplayPriorityItem[],
    coverage_limited: [] as ReplayPriorityItem[],
  };
  for (const item of items ?? []) {
    if (item.category === "coverage_limited") {
      groups.coverage_limited.push(item);
    } else {
      groups.weakness.push(item);
    }
  }
  return groups;
}

function PriorityItemGroup({
  title,
  items,
}: {
  title: string;
  items: ReplayPriorityItem[];
}) {
  if (items.length === 0) return null;
  const titleMeta = getPriorityGroupTitleMeta(title);
  const TitleIcon = titleMeta.Icon;
  return (
    <section>
      <p className="mb-2">
        <span
          className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium ${titleMeta.className}`}
        >
          <TitleIcon className="h-3.5 w-3.5" />
          {title}
        </span>
      </p>
      <div className="flex flex-wrap gap-2">
        {items.map((priorityItem) => (
          <Badge
            key={`${priorityItem.category}-${priorityItem.display_text}`}
            variant="secondary"
          >
            {priorityItem.display_text}
          </Badge>
        ))}
      </div>
    </section>
  );
}

function getPriorityGroupTitleMeta(title: string): {
  Icon: ComponentType<{ className?: string }>;
  className: string;
} {
  if (title === "补充证据") {
    return {
      Icon: FileText,
      className:
        "border-sky-500/15 bg-sky-500/[0.06] text-sky-200/80",
    };
  }
  return {
    Icon: Target,
    className:
      "border-emerald-500/15 bg-emerald-500/[0.05] text-emerald-200/75",
  };
}

function SectionLabel({ title }: { title: string }) {
  const meta = getSectionLabelMeta(title);
  const LabelIcon = meta.Icon;
  return (
    <p className="mb-1">
      <span
        className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-medium ${meta.className}`}
      >
        <LabelIcon className="h-3.5 w-3.5" />
        {title}
      </span>
    </p>
  );
}

function getSectionLabelMeta(title: string): {
  Icon: ComponentType<{ className?: string }>;
  className: string;
} {
  if (title === "问题") {
    return { Icon: Tags, className: "border-border/70 bg-muted/30 text-muted-foreground/80" };
  }
  if (title === "你的回答") {
    return { Icon: UserRound, className: "border-border/70 bg-muted/30 text-muted-foreground/80" };
  }
  if (title === "评分依据") {
    return { Icon: FileText, className: "border-border/70 bg-muted/30 text-muted-foreground/80" };
  }
  if (title === "亮点") {
    return { Icon: CheckCircle2, className: "border-border/70 bg-muted/30 text-muted-foreground/80" };
  }
  if (title === "可提升") {
    return { Icon: Target, className: "border-border/70 bg-muted/30 text-muted-foreground/80" };
  }
  return { Icon: Tags, className: "border-border/70 bg-muted/30 text-muted-foreground/80" };
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-card/60 p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 font-medium">{value}</p>
    </div>
  );
}

function ContextBasisCard({
  basis,
}: {
  basis?: ReplayResponse["context_basis"];
}) {
  if (!basis) return null;
  const selfIntroRows = [
    { label: "项目线索", values: basis.self_intro?.emphasized_projects ?? [] },
    { label: "技能线索", values: basis.self_intro?.emphasized_skills ?? [] },
    { label: "关注方向", values: basis.self_intro?.preferred_focus ?? [] },
  ];
  const resumeRows = [
    { label: "项目线索", values: basis.resume?.projects ?? [] },
    { label: "重点方向", values: basis.resume?.focus_areas ?? [] },
    { label: "技能线索", values: basis.resume?.skills ?? [] },
  ];
  const dimensionLabel =
    basis.job_spec?.dimension_source_label === "默认评分标准"
      ? "评分维度（默认评分标准）"
      : "评分维度";
  const jobRows = [
    { label: "岗位技能", values: basis.job_spec?.required_skills ?? [] },
    {
      label: dimensionLabel,
      values: (basis.job_spec?.dimensions ?? []).map(formatDimension),
    },
  ];
  return (
    <Card>
      <details className="group">
        <summary className="cursor-pointer list-none px-6 py-4">
          <div className="flex items-center justify-between gap-3">
            <CardTitle className="text-base">{basis.title}</CardTitle>
            <span className="text-xs text-muted-foreground group-open:hidden">
              展开
            </span>
            <span className="hidden text-xs text-muted-foreground group-open:inline">
              收起
            </span>
          </div>
          <ContextBasisOverview basis={basis} />
        </summary>
        <CardContent className="grid gap-4 pt-0 text-sm md:grid-cols-3">
          <ContextBasisGroup title="自我介绍" tone="selfIntro" rows={selfIntroRows} />
          <ContextBasisGroup title="简历" tone="resume" rows={resumeRows} />
          <ContextBasisGroup title="岗位要求" tone="job" rows={jobRows} />
        </CardContent>
      </details>
    </Card>
  );
}

function ContextBasisOverview({
  basis,
}: {
  basis: NonNullable<ReplayResponse["context_basis"]>;
}) {
  return (
    <div className="mt-3 space-y-3 text-sm">
      {basis.summary && (
        <p className="max-w-[72ch] leading-relaxed text-muted-foreground">
          {basis.summary}
        </p>
      )}
      {basis.chips.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {basis.chips.map((chip) => (
            <Badge key={chip} variant="secondary" className="text-xs">
              {chip}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

function ContextBasisGroup({
  title,
  tone,
  rows,
}: {
  title: string;
  tone: ContextBasisTone;
  rows: Array<{ label: string; values: string[] }>;
}) {
  const visibleRows = rows.filter((row) => row.values.length > 0);
  if (visibleRows.length === 0) return null;
  const meta = CONTEXT_BASIS_GROUP_META[tone];
  const GroupIcon = meta.Icon;
  return (
    <div
      className={`space-y-3 rounded-md border p-3 transition-colors ${meta.panelClassName}`}
    >
      <div className="flex items-center gap-2">
        <span
          className={`grid h-6 w-6 shrink-0 place-items-center rounded-md ${meta.iconClassName}`}
        >
          <GroupIcon className="h-3.5 w-3.5" />
        </span>
        <p className="text-sm font-semibold text-foreground">{title}</p>
      </div>
      {visibleRows.map((row) => (
        <ContextBasisRow key={row.label} label={row.label} values={row.values} />
      ))}
    </div>
  );
}

function ContextBasisRow({
  label,
  values,
}: {
  label: string;
  values: string[];
}) {
  const LabelIcon = getContextBasisRowIcon(label);
  return (
    <div className="space-y-1.5">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <LabelIcon className="h-3.5 w-3.5 text-muted-foreground/80" />
        {label}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {values.map((value) => (
          <Badge
            key={`${label}-${value}`}
            variant="outline"
            className="text-xs transition-colors hover:border-emerald-400/50 hover:bg-emerald-500/5"
          >
            {value}
          </Badge>
        ))}
      </div>
    </div>
  );
}

function getContextBasisRowIcon(label: string) {
  if (label.includes("技能")) return Wrench;
  if (label.includes("方向")) return Compass;
  if (label.includes("维度")) return Layers3;
  return Tags;
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
            <QuestionBasisBlock basis={turn.question_basis} />
            {turn.answer && (
              <div>
                <SectionLabel title="你的回答" />
                <CollapsibleAnswerBubble
                  text={turn.answer}
                  label="你"
                  contentId={`replay-answer-content-${turn.turn_idx ?? index}`}
                />
              </div>
            )}
            <ScoringRationaleBlock
              rationale={turn.rationale}
              followupReason={turn.followup_reason}
            />
            <ListBlock title="亮点" values={turn.strengths ?? []} />
            <ListBlock
              title="可提升"
              values={turn.weaknesses ?? []}
              emptyText="本轮没有明确短板记录，可结合评分依据继续复盘。"
            />
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

function QuestionBasisBlock({
  basis,
}: {
  basis?: ReplayTurn["question_basis"];
}) {
  if (!basis) return null;
  const chipGroups = splitQuestionBasisChips(basis.chips);
  return (
    <div className="rounded-md border border-sky-500/20 bg-sky-500/5 p-3">
      <p className="mb-1 text-xs font-medium text-sky-400">{basis.title}</p>
      <p className="text-muted-foreground">{basis.summary}</p>
      {basis.chips.length > 0 && (
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <QuestionBasisChipGroup label="依据来源" chips={chipGroups.sources} />
          <QuestionBasisChipGroup
            label="匹配维度"
            chips={chipGroups.dimensions}
          />
          <QuestionBasisChipGroup label="具体线索" chips={chipGroups.details} />
        </div>
      )}
    </div>
  );
}

function QuestionBasisChipGroup({
  label,
  chips,
}: {
  label: string;
  chips: string[];
}) {
  if (chips.length === 0) return null;
  const LabelIcon = getQuestionBasisGroupIcon(label);
  return (
    <div className="space-y-1.5">
      <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
        <span className="grid h-5 w-5 shrink-0 place-items-center rounded-md bg-sky-500/10 text-sky-300/80">
          <LabelIcon className="h-3.5 w-3.5" />
        </span>
        {label}
      </p>
      <div className="flex flex-wrap gap-1.5">
        {chips.map((chip) => (
          <Badge key={`${label}-${chip}`} variant="outline" className="text-xs">
            {chip}
          </Badge>
        ))}
      </div>
    </div>
  );
}

function getQuestionBasisGroupIcon(label: string) {
  if (label === "依据来源") return GitBranch;
  if (label === "匹配维度") return Layers3;
  return Tags;
}

function splitQuestionBasisChips(chips: string[]) {
  const groups = {
    sources: [] as string[],
    dimensions: [] as string[],
    details: [] as string[],
  };
  let nextChipIsDimension = false;
  for (const chip of chips) {
    if (QUESTION_BASIS_SOURCE_CHIPS.has(chip)) {
      groups.sources.push(chip);
      nextChipIsDimension = false;
      continue;
    }
    if (chip === QUESTION_BASIS_DIMENSION_MARKER) {
      nextChipIsDimension = true;
      continue;
    }
    if (nextChipIsDimension || QUESTION_BASIS_DIMENSION_LABELS.has(chip)) {
      groups.dimensions.push(chip);
      nextChipIsDimension = false;
      continue;
    }
    groups.details.push(chip);
    nextChipIsDimension = false;
  }
  return groups;
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
          <span>后续练习任务</span>
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
      <SectionLabel title={title} />
      <p className="leading-relaxed">{value}</p>
    </div>
  );
}

function ScoringRationaleBlock({
  rationale,
  followupReason,
}: {
  rationale?: string | null;
  followupReason?: ReplayTurn["followup_reason"];
}) {
  if (!rationale && !followupReason) return null;
  return (
    <div>
      <SectionLabel title="评分依据" />
      <div className="space-y-2">
        {rationale && <p className="leading-relaxed">{rationale}</p>}
        {followupReason && (
          <div className="rounded-md border border-emerald-500/20 bg-emerald-500/5 p-3">
            <p className="mb-1 text-xs font-medium text-emerald-400">
              {followupReason.title}
            </p>
            <p className="text-muted-foreground">{followupReason.summary}</p>
            {followupReason.chips.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {followupReason.chips.map((chip) => (
                  <Badge key={chip} variant="secondary" className="text-xs">
                    {chip}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function ListBlock({
  title,
  values,
  emptyText,
}: {
  title: string;
  values: string[];
  emptyText?: string;
}) {
  if (values.length === 0 && !emptyText) return null;
  return (
    <div>
      <SectionLabel title={title} />
      {values.length === 0 && emptyText ? (
        <p className="text-sm italic text-muted-foreground/70">{emptyText}</p>
      ) : (
        <ul className="list-disc space-y-1 pl-5 text-muted-foreground">
          {values.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      )}
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
