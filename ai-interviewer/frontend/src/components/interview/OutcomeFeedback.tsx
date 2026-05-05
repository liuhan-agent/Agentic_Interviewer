"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Award,
  CheckCircle2,
  Frown,
  Loader2,
  Pause,
  Star,
  XCircle,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { submitFeedback } from "@/lib/api/interview";
import type { FeedbackOutcome } from "@/lib/api/types";
import { upsertEntry } from "@/lib/storage/interviewHistory";

const STORAGE_PREFIX = "feedback:";

const OUTCOME_OPTIONS: ReadonlyArray<{
  id: FeedbackOutcome;
  label: string;
  icon: React.ReactNode;
}> = [
  {
    id: "got_offer",
    label: "拿到 Offer",
    icon: <Award className="h-4 w-4" />,
  },
  {
    id: "no_offer",
    label: "没有通过",
    icon: <XCircle className="h-4 w-4" />,
  },
  {
    id: "still_preparing",
    label: "还在准备",
    icon: <Pause className="h-4 w-4" />,
  },
  {
    id: "withdrew",
    label: "决定不面了",
    icon: <Frown className="h-4 w-4" />,
  },
];

function readSubmitted(sessionId: string): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(STORAGE_PREFIX + sessionId) === "1";
  } catch {
    return false;
  }
}

function markSubmitted(sessionId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_PREFIX + sessionId, "1");
  } catch {
    /* quota / private mode */
  }
}

export function OutcomeFeedback({ sessionId }: { sessionId: string }) {
  const [submitted, setSubmitted] = useState(() => readSubmitted(sessionId));
  const [selected, setSelected] = useState<FeedbackOutcome | null>(null);
  const [helpful, setHelpful] = useState<number | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSubmitted(readSubmitted(sessionId));
  }, [sessionId]);

  const handleSubmit = useCallback(async () => {
    if (!selected || sending) return;
    setSending(true);
    setError(null);
    try {
      await submitFeedback(sessionId, {
        outcome: selected,
        helpful_score: helpful ?? undefined,
      });
      markSubmitted(sessionId);
      setSubmitted(true);
      try {
        upsertEntry({ sessionId, feedbackSubmitted: true });
      } catch {
        /* non-critical */
      }
    } catch {
      setError("提交失败，请稍后重试");
    } finally {
      setSending(false);
    }
  }, [selected, helpful, sending, sessionId]);

  if (submitted) {
    return (
      <Card className="border-emerald-500/20 bg-emerald-500/5">
        <CardContent className="flex items-center gap-3 py-6">
          <CheckCircle2 className="h-5 w-5 text-emerald-400" />
          <p className="text-sm text-emerald-300">
            感谢你的反馈，它会帮助我们更好地优化出题策略。
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">面试结果反馈</CardTitle>
        <CardDescription>
          告诉我们这场练习之后的真实面试结果（可选），帮助 AI
          持续优化出题和评估策略。
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {OUTCOME_OPTIONS.map((opt) => {
            const active = selected === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                onClick={() => setSelected(opt.id)}
                className={[
                  "flex flex-col items-center gap-1.5 rounded-lg border px-3 py-3 text-sm transition-all",
                  active
                    ? "border-emerald-500/60 bg-emerald-500/10 text-emerald-300"
                    : "border-border hover:border-emerald-500/30 hover:bg-emerald-500/5",
                ].join(" ")}
              >
                <span className={active ? "text-emerald-400" : "text-muted-foreground"}>
                  {opt.icon}
                </span>
                <span className="font-medium">{opt.label}</span>
              </button>
            );
          })}
        </div>

        {selected && (
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              这场练习对你有帮助吗？（可选）
            </p>
            <div className="flex items-center gap-1">
              {[1, 2, 3, 4, 5].map((v) => (
                <button
                  key={v}
                  type="button"
                  onClick={() => setHelpful(helpful === v ? null : v)}
                  className="rounded p-1 transition-colors hover:bg-emerald-500/10"
                  aria-label={`${v} 星`}
                >
                  <Star
                    className={[
                      "h-5 w-5 transition-colors",
                      helpful !== null && v <= helpful
                        ? "fill-emerald-400 text-emerald-400"
                        : "text-muted-foreground/40",
                    ].join(" ")}
                  />
                </button>
              ))}
              {helpful !== null && (
                <span className="ml-2 text-xs text-muted-foreground">
                  {helpful}/5
                </span>
              )}
            </div>
          </div>
        )}

        {error && (
          <p className="text-xs text-destructive">{error}</p>
        )}

        <div className="flex justify-end">
          <Button
            type="button"
            size="sm"
            disabled={!selected || sending}
            onClick={handleSubmit}
            className="gap-2 bg-emerald-600 text-white hover:bg-emerald-500"
          >
            {sending && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            提交反馈
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
