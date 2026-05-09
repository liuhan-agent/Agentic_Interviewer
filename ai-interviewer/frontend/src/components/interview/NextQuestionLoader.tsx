"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";

import { cn } from "@/lib/utils";

/**
 * Loading indicator shown between answer submission and the next
 * question's arrival. Uses the previous segment's wall-clock latency
 * (#11) as an ETA so the progress bar animates linearly toward 95%
 * over the expected window. When the server runs longer than the ETA
 * the bar deliberately caps at 95% — finishing the bar before the
 * question actually arrives looks broken — and the copy switches to a
 * "this turn is heavier" reassurance.
 *
 * Cleanup invariant: the interval is torn down on unmount **and**
 * whenever ``etaMs`` changes so the timer never outlives a remount
 * (e.g. user skips a question and the loader re-enters with a fresh
 * ETA). This prevents the well-known "phantom interval" bug that
 * keeps firing setState on a stale component.
 */

const TICK_MS = 100;
const FALLBACK_ETA_MS = 7000;
const PROGRESS_CAP = 0.95;

export interface NextQuestionLoaderProps {
  /** Previous segment's wall-clock duration in milliseconds, surfaced
   *  by ``GET /question`` as ``server_latency_ms``. ``null`` on the very
   *  first turn (no prior segment to learn from). */
  etaMs: number | null;
  isFinalTurn?: boolean;
  className?: string;
}

export function NextQuestionLoader({
  etaMs,
  isFinalTurn = false,
  className,
}: NextQuestionLoaderProps) {
  const effectiveEta = etaMs && etaMs > 0 ? etaMs : FALLBACK_ETA_MS;
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
  const etaSeconds = Math.max(1, Math.round(effectiveEta / 1000));

  const headline = isFinalTurn
    ? overrun
      ? "正在整理本场面试总结，内容比单题更完整"
      : "正在整理本场面试总结"
    : overrun
      ? "AI 还在思考，这一题重点多"
      : "AI 正在出下一题";
  const subline =
    etaMs && etaMs > 0
      ? isFinalTurn
        ? overrun
          ? `最后一题已提交 · 已用时 ${elapsedSeconds}s`
          : `最后一题已提交 · 预计 ≈ ${etaSeconds}s`
        : overrun
          ? `已用时 ${elapsedSeconds}s · 上一轮 ${etaSeconds}s`
          : `预计 ≈ ${etaSeconds}s · 已用时 ${elapsedSeconds}s`
      : `已用时 ${elapsedSeconds}s`;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className={cn(
        "space-y-2 rounded-lg border border-dashed bg-secondary/30 p-4 text-sm text-muted-foreground",
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
