"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";

import type { InterviewWaitingTip } from "@/lib/api/types";
import { cn } from "@/lib/utils";

/**
 * Loading indicator shown between answer submission and the next
 * question's arrival. The progress bar uses a conservative window so
 * slower models do not look stuck after a few seconds. When the server
 * runs longer than the window the bar deliberately caps at 95% because
 * finishing before the next question arrives feels broken.
 *
 * Cleanup invariant: the interval is torn down on unmount and whenever
 * the effective ETA changes, so the timer never outlives a remount.
 */

const TICK_MS = 100;
const FALLBACK_ETA_MS = 45000;
const PROGRESS_CAP = 0.95;
const WAITING_TIP_ROTATION_MS = 10000;
const FINAL_STAGE_HEADLINES = {
  normal: "正在整理本场面试总结",
  slow: "正在整理本场面试总结，内容比单题更完整",
};
const OPENING_STAGE_HEADLINES = {
  early: "正在梳理你的开场介绍",
  middle: "正在提取经历线索",
  late: "正在组织第一道问题",
  slow: "模型响应偏慢，仍在生成中",
};
const QUESTION_STAGE_HEADLINES = {
  early: "AI 正在理解你的回答",
  middle: "正在匹配简历项目和考察重点",
  late: "正在组织下一题",
  slow: "模型响应偏慢，仍在生成中",
};
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

  const progress = Math.min(elapsedMs / effectiveEta, PROGRESS_CAP);
  const overrun = elapsedMs > effectiveEta;
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

  const headline = isFinalTurn
    ? overrun
      ? FINAL_STAGE_HEADLINES.slow
      : FINAL_STAGE_HEADLINES.normal
    : isOpeningTurn
      ? elapsedMs < 10_000
        ? OPENING_STAGE_HEADLINES.early
        : elapsedMs < 30_000
          ? OPENING_STAGE_HEADLINES.middle
          : elapsedMs < 60_000
            ? OPENING_STAGE_HEADLINES.late
            : OPENING_STAGE_HEADLINES.slow
    : elapsedMs < 10_000
      ? QUESTION_STAGE_HEADLINES.early
      : elapsedMs < 30_000
        ? QUESTION_STAGE_HEADLINES.middle
        : elapsedMs < 60_000
          ? QUESTION_STAGE_HEADLINES.late
          : QUESTION_STAGE_HEADLINES.slow;
  const elapsedLabel = overrun
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
            "h-full rounded-full transition-[width] duration-200",
            overrun ? "bg-amber-500" : "bg-emerald-500",
          )}
          style={{ width: `${progress * 100}%` }}
        />
      </div>
    </motion.div>
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
    scoped.length > 0
      ? scoped
      : defaultTips.length > 0
        ? defaultTips
        : FALLBACK_WAITING_TIPS;
  const unused = candidates.filter((tip) => !displayedTipIds?.has(tip.id));
  const available = unused.length > 0 ? unused : candidates;
  return available.find((tip) => tip.id !== currentTipId) ?? available[0] ?? null;
}
