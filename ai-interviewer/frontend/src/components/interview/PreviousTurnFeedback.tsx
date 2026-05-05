"use client";

import { useMemo } from "react";
import { AlertTriangle, CheckCircle2, Sparkles } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import type { PreviousTurnEvaluation } from "@/lib/api/types";

/**
 * In-interview feedback card surfaced *above* the next question while the
 * candidate is composing their answer. Reads from
 * ``useQuestionPoller().state.previousEvaluation`` (which the long-poll
 * pipeline echoes from ``handle.last_turn_evaluation``).
 *
 * Product invariants honoured here:
 *
 * - **No raw score is rendered.** We deliberately collapse ``score`` and
 *   ``passed`` into a three-tier qualitative signal so candidates aren't
 *   anchored on a quantitative number mid-loop. The score still rides the
 *   wire in case the report surfaces want it later.
 * - **Strengths and weaknesses are capped at 2 items each upstream**
 *   (``_extract_last_turn_evaluation`` in ``session_manager.py``); we
 *   render whatever arrives without further trimming so the projection
 *   layer is the single source of truth on length.
 * - **Empty / first-turn / fallback evaluator → ``null``.** The hook
 *   already filters those out by setting ``previousEvaluation = null``,
 *   and this component returns ``null`` defensively as a second guard.
 */

type Verdict = "passed" | "near" | "needs_work";

interface VerdictPresentation {
  label: string;
  hint: string;
  icon: typeof CheckCircle2;
  badgeVariant: "success" | "warn" | "secondary";
  accentRing: string;
  iconColor: string;
}

const VERDICT_PRESENTATION: Record<Verdict, VerdictPresentation> = {
  passed: {
    label: "本题通过",
    hint: "保持节奏，继续展开下一题。",
    icon: CheckCircle2,
    badgeVariant: "success",
    accentRing: "ring-emerald-500/30",
    iconColor: "text-emerald-500",
  },
  near: {
    label: "接近通过线",
    hint: "再补一两个细节就稳了。",
    icon: Sparkles,
    badgeVariant: "warn",
    accentRing: "ring-amber-500/30",
    iconColor: "text-amber-500",
  },
  needs_work: {
    label: "可以再补齐",
    hint: "下一题不妨从弱项里找切口。",
    icon: AlertTriangle,
    badgeVariant: "secondary",
    accentRing: "ring-slate-400/30",
    iconColor: "text-slate-500",
  },
};

function deriveVerdict(evaluation: PreviousTurnEvaluation): Verdict {
  if (evaluation.passed) return "passed";
  if (typeof evaluation.score === "number" && evaluation.score >= 4) {
    return "near";
  }
  return "needs_work";
}

export interface PreviousTurnFeedbackProps {
  evaluation: PreviousTurnEvaluation | null | undefined;
  /**
   * Dimension id of the *current* (incoming) question. When non-null and
   * different from the evaluated turn's dimension, we surface a one-line
   * note so candidates aren't surprised by an apparent topic shift.
   */
  currentDimension?: string | null;
  className?: string;
}

export function PreviousTurnFeedback({
  evaluation,
  currentDimension,
  className,
}: PreviousTurnFeedbackProps) {
  const verdict = useMemo(
    () => (evaluation ? deriveVerdict(evaluation) : null),
    [evaluation],
  );

  const dimensionShifted = Boolean(
    evaluation &&
      currentDimension &&
      evaluation.dimension &&
      currentDimension !== evaluation.dimension,
  );

  return (
    <AnimatePresence mode="wait" initial={false}>
      {evaluation && verdict ? (
        <motion.div
          key={`prev-eval-${evaluation.turn_idx}`}
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -4 }}
          transition={{ duration: 0.18, ease: "easeOut" }}
          className={className}
          role="status"
          aria-live="polite"
        >
          <PreviousTurnFeedbackBody
            evaluation={evaluation}
            verdict={verdict}
            dimensionShifted={dimensionShifted}
          />
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

function PreviousTurnFeedbackBody({
  evaluation,
  verdict,
  dimensionShifted,
}: {
  evaluation: PreviousTurnEvaluation;
  verdict: Verdict;
  dimensionShifted: boolean;
}) {
  const preset = VERDICT_PRESENTATION[verdict];
  const Icon = preset.icon;
  const turnLabel =
    typeof evaluation.turn_idx === "number"
      ? `第 ${evaluation.turn_idx + 1} 题反馈`
      : "上一题反馈";

  return (
    <Card
      className={cn(
        "border-muted-foreground/10 ring-1 ring-inset",
        preset.accentRing,
      )}
    >
      <CardContent className="space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <Icon className={cn("h-4 w-4 shrink-0", preset.iconColor)} aria-hidden="true" />
          <span className="text-sm font-semibold tracking-tight">
            {turnLabel}
          </span>
          <Badge variant={preset.badgeVariant} className="text-[11px]">
            {preset.label}
          </Badge>
          {evaluation.dimension ? (
            <Badge variant="outline" className="text-[11px] font-mono">
              {evaluation.dimension}
            </Badge>
          ) : null}
        </div>

        <p className="text-xs text-muted-foreground">{preset.hint}</p>

        {evaluation.strengths.length > 0 ? (
          <FeedbackBulletList
            tone="positive"
            heading="做得好"
            items={evaluation.strengths}
          />
        ) : null}
        {evaluation.weaknesses.length > 0 ? (
          <FeedbackBulletList
            tone="negative"
            heading="可补齐"
            items={evaluation.weaknesses}
          />
        ) : null}

        {dimensionShifted ? (
          <p className="text-[11px] text-muted-foreground">
            下一题切换到了新的考察维度，请整理思路再作答。
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function FeedbackBulletList({
  tone,
  heading,
  items,
}: {
  tone: "positive" | "negative";
  heading: string;
  items: string[];
}) {
  const dotColor =
    tone === "positive" ? "bg-emerald-500" : "bg-amber-500";
  return (
    <div className="space-y-1">
      <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        {heading}
      </p>
      <ul className="space-y-1">
        {items.map((item, idx) => (
          <li
            key={`${tone}-${idx}-${item.slice(0, 16)}`}
            className="flex items-start gap-2 text-xs leading-relaxed"
          >
            <span
              className={cn(
                "mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full",
                dotColor,
              )}
              aria-hidden="true"
            />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
