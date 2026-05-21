"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";

import type { InterviewWaitingTip } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * Loading indicator shown between answer submission and the next
 * question's arrival. The progress bar is an expectation cue, not an
 * exact percent complete. It follows a slow non-linear rhythm and then
 * caps at 95% so long model runs still feel active without pretending
 * the next question is already done.
 *
 * Cleanup invariant: the interval is torn down on unmount and whenever
 * the effective ETA changes, so the timer never outlives a remount.
 */

const TICK_MS = 100;
const FALLBACK_ETA_MS = 100_000;
const PROGRESS_CAP = 0.95;
const WAITING_TIP_ROTATION_MS = 10000;
const WAITING_PROGRESS_POINTS = [
  { timeMs: 0, progress: 0 },
  { timeMs: 10_000, progress: 0.1 },
  { timeMs: 45_000, progress: 0.52 },
  { timeMs: 80_000, progress: 0.86 },
  { timeMs: 100_000, progress: 0.94 },
  { timeMs: 110_000, progress: PROGRESS_CAP },
] as const;
const FINAL_STAGE_HEADLINES = [
  { thresholdMs: 20_000, text: "正在汇总本场表现" },
  { thresholdMs: 60_000, text: "正在整理多维度反馈" },
  { thresholdMs: 100_000, text: "正在检查总结表达" },
  { thresholdMs: Number.POSITIVE_INFINITY, text: "总结内容较完整，仍在生成中" },
] as const;
const OPENING_STAGE_HEADLINES = [
  { thresholdMs: 12_000, text: "正在整理你的开场介绍" },
  { thresholdMs: 35_000, text: "正在提取经历线索" },
  { thresholdMs: 65_000, text: "正在匹配第一轮考察点" },
  { thresholdMs: 90_000, text: "正在组织第一道问题" },
  { thresholdMs: 110_000, text: "正在检查问题表达" },
  {
    thresholdMs: Number.POSITIVE_INFINITY,
    text: "复杂回答需要多一点时间，仍在生成中",
  },
] as const;
const QUESTION_STAGE_HEADLINES = [
  { thresholdMs: 12_000, text: "正在整理你的回答" },
  { thresholdMs: 35_000, text: "正在梳理关键信息" },
  { thresholdMs: 65_000, text: "正在提炼本轮考察点" },
  { thresholdMs: 90_000, text: "正在组织下一题" },
  { thresholdMs: 110_000, text: "正在检查问题表达" },
  {
    thresholdMs: Number.POSITIVE_INFINITY,
    text: "复杂回答需要多一点时间，仍在生成中",
  },
] as const;
const FALLBACK_WAITING_TIPS: InterviewWaitingTip[] = [
  {
    id: "frontend_fallback_default_001",
    scope: "default",
    text: "回答可以先给结论，再补关键动作和结果，面试官会更容易抓住重点。",
  },
  {
    id: "frontend_fallback_self_intro_001",
    scope: "self_intro",
    text: "开场介绍可以用一条主线串起来：你做过什么、擅长什么、希望面试官重点了解什么。",
  },
  {
    id: "frontend_fallback_final_001",
    scope: "final",
    text: "总结会综合整场表现，不只看最后一题，稳定表达和补充修正也会被纳入观察。",
  },
];

export type AnswerInsight = {
  dimensionId?: string | null;
  dimensionLabel?: string | null;
  isOpeningTurn?: boolean;
};

export interface NextQuestionLoaderProps {
  /** Previous segment wall-clock duration in milliseconds, surfaced as server_latency_ms. */
  etaMs: number | null;
  isFinalTurn?: boolean;
  answerInsight?: AnswerInsight | null;
  waitingTips?: InterviewWaitingTip[] | null;
  tipRotationIntervalMs?: number;
  displayedTipIds?: ReadonlySet<string>;
  onWaitingTipShown?: (tipId: string) => void;
  className?: string;
}

export function NextQuestionLoader({
  etaMs,
  isFinalTurn = false,
  answerInsight = null,
  waitingTips = null,
  tipRotationIntervalMs = WAITING_TIP_ROTATION_MS,
  displayedTipIds,
  onWaitingTipShown,
  className,
}: NextQuestionLoaderProps) {
  const effectiveEta = Math.max(
    etaMs && etaMs > 0 ? etaMs : FALLBACK_ETA_MS,
    FALLBACK_ETA_MS,
  );
  const [elapsedMs, setElapsedMs] = useState(0);

  useEffect(() => {
    const startedAt = Date.now();
    const id = setInterval(() => {
      setElapsedMs(Date.now() - startedAt);
    }, TICK_MS);
    return () => {
      clearInterval(id);
    };
  }, [effectiveEta]);

  const progress = getQuestionPreparationProgress(elapsedMs);
  const isLongWait = elapsedMs >= WAITING_PROGRESS_POINTS.at(-1)!.timeMs;
  const elapsedSeconds = Math.max(1, Math.round(elapsedMs / 1000));
  const isOpeningTurn = Boolean(answerInsight?.isOpeningTurn);
  const tipScope = isFinalTurn
    ? "final"
    : isOpeningTurn
      ? "self_intro"
      : answerInsight?.dimensionId || "default";
  const effectiveTipRotationMs =
    tipRotationIntervalMs > 0 ? tipRotationIntervalMs : WAITING_TIP_ROTATION_MS;
  const activeTips =
    waitingTips && waitingTips.length > 0 ? waitingTips : FALLBACK_WAITING_TIPS;
  const [currentTip, setCurrentTip] = useState<InterviewWaitingTip | null>(null);

  useEffect(() => {
    function showNextTip() {
      setCurrentTip((previousTip) => {
        const nextTip = selectNextWaitingTip(
          activeTips,
          tipScope,
          displayedTipIds,
          previousTip?.id ?? null,
        );
        if (nextTip) {
          onWaitingTipShown?.(nextTip.id);
        }
        return nextTip;
      });
    }

    showNextTip();
    const id = setInterval(showNextTip, effectiveTipRotationMs);
    return () => {
      clearInterval(id);
    };
  }, [
    activeTips,
    displayedTipIds,
    effectiveTipRotationMs,
    onWaitingTipShown,
    tipScope,
  ]);

  const headline = getWaitingHeadline(
    elapsedMs,
    isFinalTurn
      ? FINAL_STAGE_HEADLINES
      : isOpeningTurn
        ? OPENING_STAGE_HEADLINES
        : QUESTION_STAGE_HEADLINES,
  );
  const elapsedLabel = isLongWait
    ? `已用时 ${elapsedSeconds}s · 仍在生成中`
    : `已用时 ${elapsedSeconds}s`;
  const subline = isFinalTurn
    ? `最后一题已提交 · ${elapsedLabel}`
    : elapsedLabel;
  const showAnswerInsight = Boolean(
    currentTip ||
      (answerInsight &&
        (isOpeningTurn || (!isFinalTurn && answerInsight.dimensionLabel))),
  );

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className={cn(
        "space-y-3 rounded-lg border border-dashed bg-secondary/30 p-4 text-sm text-muted-foreground",
        className,
      )}
    >
      <div className="flex items-center gap-3">
        <div className="flex gap-1" aria-hidden="true">
          <span className="h-2 w-2 animate-bounce rounded-full bg-emerald-400 [animation-delay:0ms]" />
          <span className="h-2 w-2 animate-bounce rounded-full bg-emerald-400 [animation-delay:150ms]" />
          <span className="h-2 w-2 animate-bounce rounded-full bg-emerald-400 [animation-delay:300ms]" />
        </div>
        <span className="font-medium text-foreground">{headline}</span>
        <span className="ml-auto text-xs tabular-nums text-muted-foreground/80">
          {subline}
        </span>
      </div>
      {showAnswerInsight && (
        <div className="space-y-1 rounded-md border border-emerald-500/15 bg-emerald-500/[0.04] px-3 py-2 text-xs leading-relaxed text-muted-foreground">
          {!isFinalTurn && isOpeningTurn && (
            <p>
              <span className="text-emerald-200">开场介绍：</span>
              <span>正在据此安排第一道问题</span>
            </p>
          )}
          {!isFinalTurn && !isOpeningTurn && answerInsight?.dimensionLabel && (
            <p>
              <span className="text-emerald-200">本轮考察：</span>
              <span>{answerInsight.dimensionLabel}</span>
            </p>
          )}
          {currentTip && (
            <p>
              <span className="text-emerald-200">面试小贴士：</span>
              <span>{currentTip.text}</span>
            </p>
          )}
        </div>
      )}
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-secondary"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(progress * 100)}
        aria-label={isFinalTurn ? "面试总结整理进度" : "下一题准备进度"}
      >
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-300 ease-out",
            isLongWait
              ? "animate-shimmer bg-shimmer bg-emerald-500/80"
              : "bg-emerald-500",
          )}
          style={{ width: `${progress * 100}%` }}
        />
      </div>
    </motion.div>
  );
}

function getQuestionPreparationProgress(elapsedMs: number): number {
  const safeElapsedMs = Math.max(0, elapsedMs);
  for (let index = 1; index < WAITING_PROGRESS_POINTS.length; index += 1) {
    const previous = WAITING_PROGRESS_POINTS[index - 1];
    const next = WAITING_PROGRESS_POINTS[index];
    if (safeElapsedMs <= next.timeMs) {
      return lerpProgress(safeElapsedMs, previous, next);
    }
  }
  return PROGRESS_CAP;
}

function lerpProgress(
  elapsedMs: number,
  previous: (typeof WAITING_PROGRESS_POINTS)[number],
  next: (typeof WAITING_PROGRESS_POINTS)[number],
): number {
  const segmentDuration = next.timeMs - previous.timeMs;
  if (segmentDuration <= 0) {
    return Math.min(next.progress, PROGRESS_CAP);
  }
  const segmentElapsed = elapsedMs - previous.timeMs;
  const ratio = Math.min(Math.max(segmentElapsed / segmentDuration, 0), 1);
  return Math.min(
    previous.progress + (next.progress - previous.progress) * ratio,
    PROGRESS_CAP,
  );
}

function getWaitingHeadline(
  elapsedMs: number,
  headlines: readonly { thresholdMs: number; text: string }[],
): string {
  return (
    headlines.find((headline) => elapsedMs < headline.thresholdMs)?.text ??
    headlines.at(-1)!.text
  );
}

function selectNextWaitingTip(
  tips: InterviewWaitingTip[],
  scope: string,
  displayedTipIds?: ReadonlySet<string>,
  currentTipId?: string | null,
): InterviewWaitingTip | null {
  const scoped = tips.filter((tip) => tip.scope === scope);
  const defaultTips = tips.filter((tip) => tip.scope === "default");
  const candidates =
    scope === "default"
      ? defaultTips.length > 0
        ? defaultTips
        : FALLBACK_WAITING_TIPS
      : scoped.length > 0
        ? [...scoped, ...defaultTips]
        : defaultTips.length > 0
          ? defaultTips
          : FALLBACK_WAITING_TIPS;
  const unused = candidates.filter((tip) => !displayedTipIds?.has(tip.id));
  const available = unused.length > 0 ? unused : candidates;
  return available.find((tip) => tip.id !== currentTipId) ?? available[0] ?? null;
}
