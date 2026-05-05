"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useEffect, useRef, useState, useMemo } from "react";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Loader2,
  MessageSquare,
  Mic,
  Pause,
  Send,
  SkipForward,
  Lightbulb,
  Sparkles,
  Volume2,
  VolumeX,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

import DOMPurify from "dompurify";
import ReactMarkdown from "react-markdown";
import TextareaAutosize from "react-textarea-autosize";

import { LLMSettingsDialog } from "@/components/layout/LLMSettingsDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import {
  isReauthRequired,
  requestHint,
  retryFailedQuestion,
  skipQuestion,
  submitAnswer,
} from "@/lib/api/interview";
import type { LLMErrorKind, PollQuestion, ResumeAnchor } from "@/lib/api/types";
import { useQuestionPoller } from "@/lib/hooks/useQuestionPoller";
import { useToast } from "@/lib/hooks/useToast";
import {
  canSpeakQuestions,
  loadQuestionSpeechEnabled,
  speakQuestion,
  stopQuestionSpeech,
  storeQuestionSpeechEnabled,
} from "@/lib/question-speaker";
import { upsertEntry } from "@/lib/storage/interviewHistory";

const ENCOURAGEMENTS = [
  "已收到回答，正在准备下一题。",
  "回答已提交，AI 面试官正在整理追问。",
  "这一轮已记录，稍等片刻进入下一题。",
  "已保存本轮回答，继续保持节奏。",
  "提交成功，正在生成下一轮问题。",
];
const ANSWER_MAX_LENGTH = 50000;

type QaEntry = {
  turnIdx: number | null;
  formalTurnIdx?: number | null;
  questionType?: string;
  dimension?: string;
  resumeAnchor?: ResumeAnchor;
  question: string;
  answer: string | null;
};

export function InterviewRoom({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const { state, afterAnswerSubmitted, afterQuestionRetryRequested } =
    useQuestionPoller(sessionId);
  const { toast } = useToast();
  const [history, setHistory] = useState<QaEntry[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const [paused, setPaused] = useState(false);
  const [retryingQuestion, setRetryingQuestion] = useState(false);
  const [lastSubmittedTurn, setLastSubmittedTurn] = useState<number | null>(
    null,
  );
  const [readQuestions, setReadQuestions] = useState(false);
  const [questionSpeechSupported, setQuestionSpeechSupported] = useState(false);
  const [reauthRequired, setReauthRequired] = useState(false);
  const transcriptEnd = useRef<HTMLDivElement>(null);
  const lastSpokenQuestionRef = useRef<string | null>(null);
  const currentQuestionType =
    state.phase === "waiting_for_answer" && state.question
      ? extractQuestionType(state.question)
      : undefined;

  useEffect(() => {
    setQuestionSpeechSupported(canSpeakQuestions());
    setReadQuestions(loadQuestionSpeechEnabled());
    return () => stopQuestionSpeech();
  }, []);

  useEffect(() => {
    if (state.phase !== "waiting_for_answer" || !state.question) return;
    const q = state.question;
    const turnIdx = state.turnIdx;
    setHistory((prev) => {
      const lastOpen = prev[prev.length - 1];
      const qText = extractQuestion(q);
      if (
        lastOpen &&
        lastOpen.answer === null &&
        lastOpen.turnIdx === turnIdx
      ) {
        return prev;
      }
      return [
        ...prev,
        {
          turnIdx,
          formalTurnIdx: extractFormalTurnIdx(q),
          questionType: extractQuestionType(q),
          dimension: typeof q.dimension === "string" ? q.dimension : undefined,
          resumeAnchor: extractResumeAnchor(q),
          question: qText,
          answer: null,
        },
      ];
    });
  }, [state.phase, state.question, state.turnIdx]);

  useEffect(() => {
    setPaused(false);
  }, [state.turnIdx]);

  useEffect(() => {
    transcriptEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [history.length]);

  useEffect(() => {
    if (state.phase === "completed") {
      router.push(`/interview/${sessionId}/report`);
    }
  }, [state.phase, router, sessionId]);

  // Keep the local history index in sync so /interview/history is accurate
  // even if the user lands here via a deep link (no setup form).
  useEffect(() => {
    upsertEntry({ sessionId, status: "running" });
  }, [sessionId]);

  useEffect(() => {
    if (state.phase === "cancelled") {
      upsertEntry({ sessionId, status: "cancelled" });
    }
    if (state.phase === "error") {
      upsertEntry({ sessionId, status: "failed" });
    }
  }, [state.phase, sessionId]);

  useEffect(() => {
    if (!readQuestions || paused || state.phase !== "waiting_for_answer" || !state.question) {
      return;
    }
    const qText = extractQuestion(state.question);
    const speechKey = `${state.turnIdx ?? "intro"}:${qText}`;
    if (lastSpokenQuestionRef.current === speechKey) return;
    lastSpokenQuestionRef.current = speechKey;
    speakQuestion(qText);
  }, [paused, readQuestions, state.phase, state.question, state.turnIdx]);

  function notifySpeechUnavailable() {
    toast({
      title: "当前浏览器不支持朗读问题",
      description: "可以继续手动查看题目，或换一个支持语音合成的浏览器。",
    });
  }

  function handleSpeakQuestion(text: string) {
    if (!questionSpeechSupported || !speakQuestion(text)) {
      notifySpeechUnavailable();
    }
  }

  function handleToggleQuestionSpeech() {
    if (!questionSpeechSupported) {
      notifySpeechUnavailable();
      return;
    }
    const next = !readQuestions;
    setReadQuestions(next);
    storeQuestionSpeechEnabled(next);
    if (!next) {
      stopQuestionSpeech();
      return;
    }
    if (state.phase === "waiting_for_answer" && state.question) {
      const qText = extractQuestion(state.question);
      lastSpokenQuestionRef.current = `${state.turnIdx ?? "intro"}:${qText}`;
      handleSpeakQuestion(qText);
    }
  }

  async function handleSubmit(text: string) {
    if (!text || submitting) return false;
    if (state.turnIdx === null) {
      toast({
        title: "Question state is not ready",
        description: "Please wait for the current question to finish loading.",
      });
      return false;
    }
    setSubmitting(true);
    try {
      await submitAnswer(sessionId, text, state.turnIdx);
      setReauthRequired(false);
      setPaused(false);
      setHistory((prev) => {
        if (prev.length === 0) return prev;
        const next = prev.slice();
        next[next.length - 1] = { ...next[next.length - 1], answer: text };
        return next;
      });
      setLastSubmittedTurn(state.turnIdx ?? null);
      afterAnswerSubmitted();
      // Lightweight encouragement so users feel acknowledged between turns.
      toast({
        title: ENCOURAGEMENTS[Math.floor(Math.random() * ENCOURAGEMENTS.length)],
      });
      return true;
    } catch (err) {
      if (isReauthRequired(err)) {
        setReauthRequired(true);
        toast({
          title: "需要重新授权模型配置",
          description: "请打开模型设置更新 Key，然后再次提交当前回答。",
        });
        return false;
      }
      const msg = err instanceof Error ? err.message : String(err);
      toast({
        title: "提交时出了点问题",
        description: friendlyAnswerError(msg),
      });
      return false;
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSkipCurrentQuestion() {
    if (skipping || state.turnIdx === null) return false;
    setSkipping(true);
    try {
      await skipQuestion(sessionId, state.turnIdx, "candidate_skip");
      setHistory((prev) => {
        if (prev.length === 0) return prev;
        const next = prev.slice();
        next[next.length - 1] = {
          ...next[next.length - 1],
          answer: "已跳过本题",
        };
        return next;
      });
      setPaused(false);
      setLastSubmittedTurn(state.turnIdx ?? null);
      afterAnswerSubmitted();
      toast({ title: "已跳过本题，继续下一轮练习。" });
      return true;
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast({
        title: "暂时没能跳过本题",
        description: friendlyAnswerError(msg),
      });
      return false;
    } finally {
      setSkipping(false);
    }
  }

  async function handleRetryQuestionGeneration() {
    if (retryingQuestion) return;
    setRetryingQuestion(true);
    try {
      await retryFailedQuestion(sessionId);
      upsertEntry({ sessionId, status: "running" });
      setHistory((prev) => prev.filter((entry) => entry.answer !== null));
      setLastSubmittedTurn(null);
      afterQuestionRetryRequested();
      toast({ title: "正在继续处理" });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast({
        title: "重试失败",
        description: friendlyAnswerError(msg),
      });
    } finally {
      setRetryingQuestion(false);
    }
  }

  return (
    <div className="space-y-6">
      <StatusBar state={state} sessionId={sessionId} />

      {reauthRequired && <ReauthRequiredBanner />}

      <Card className="overflow-hidden">
        <CardHeader className="flex flex-row items-center justify-between border-b bg-card/50">
          <div className="flex items-center gap-2">
            <MessageSquare className="h-4 w-4 text-emerald-400" />
            <CardTitle className="text-base">对话记录</CardTitle>
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant={readQuestions ? "default" : "outline"}
              size="sm"
              aria-pressed={readQuestions}
              onClick={handleToggleQuestionSpeech}
              aria-label={
                readQuestions
                  ? "关闭新问题自动读题"
                  : "开启后，新问题出现时会自动读出"
              }
              className={
                readQuestions
                  ? "h-8 gap-1.5 bg-emerald-600 px-2.5 text-xs text-white hover:bg-emerald-500"
                  : "h-8 gap-1.5 px-2.5 text-xs"
              }
            >
              {readQuestions ? (
                <Volume2 className="h-3.5 w-3.5" />
              ) : (
                <VolumeX className="h-3.5 w-3.5" />
              )}
              <span className="hidden sm:inline">自动读题</span>
            </Button>
            <Badge variant="outline" className="font-mono text-xs">
              {history.length} 轮
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="space-y-4 pt-6">
          {history.length === 0 && state.phase !== "waiting_for_answer" && (
            <div className="space-y-3">
              <Skeleton className="h-4 w-32" />
              <Skeleton className="h-6 w-3/4" />
              <Skeleton className="h-4 w-5/6" />
            </div>
          )}

          <AnimatePresence mode="popLayout">
            {history.map((t, idx) => (
              <motion.div
                key={`turn-${idx}`}
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.35, ease: "easeOut" }}
              >
                <QaBubble
                  entry={t}
                  isCurrent={
                    idx === history.length - 1 &&
                    state.phase === "waiting_for_answer"
                  }
                  onSpeak={handleSpeakQuestion}
                />
              </motion.div>
            ))}
          </AnimatePresence>

          {state.phase === "loading" && lastSubmittedTurn !== null && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex items-center gap-3 rounded-lg border border-dashed bg-secondary/30 p-4 text-sm text-muted-foreground"
            >
              <div className="flex gap-1">
                <span className="h-2 w-2 animate-bounce rounded-full bg-emerald-400 [animation-delay:0ms]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-emerald-400 [animation-delay:150ms]" />
                <span className="h-2 w-2 animate-bounce rounded-full bg-emerald-400 [animation-delay:300ms]" />
              </div>
              <span>
                AI 正在出下一题
                <span className="ml-1 text-xs text-muted-foreground/70">
                  · 通常需要 5–10 秒
                </span>
              </span>
            </motion.div>
          )}

          <div ref={transcriptEnd} />
        </CardContent>
      </Card>

      <AnimatePresence>
        {state.phase === "waiting_for_answer" && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={{ duration: 0.3 }}
          >
            <AnswerBox
              sessionId={sessionId}
              turnIdx={state.turnIdx}
              onSubmit={handleSubmit}
              onSkip={handleSkipCurrentQuestion}
              paused={paused}
              onPause={() => {
                stopQuestionSpeech();
                setPaused(true);
              }}
              onResume={() => setPaused(false)}
              submitting={submitting}
              skipping={skipping}
              questionType={currentQuestionType}
            />
          </motion.div>
        )}
      </AnimatePresence>

      {state.phase === "error" && (
        <motion.div initial={{ opacity: 0, scale: 0.95 }} animate={{ opacity: 1, scale: 1 }}>
          <Card className="border-destructive/40 bg-destructive/5">
            <CardContent className="space-y-3 pt-6 text-sm">
              <p className="font-medium text-destructive">
                嗯，连接出了点问题
              </p>
              <p className="text-muted-foreground">
                {friendlyConnectionMessage(state.errorKind, state.error)}
              </p>
              <details className="text-xs text-muted-foreground/70">
                <summary className="cursor-pointer select-none">
                  查看技术细节
                </summary>
                <pre className="mt-2 whitespace-pre-wrap break-all rounded bg-secondary/30 p-2 font-mono text-[11px]">
                  {state.error}
                </pre>
              </details>
              <div className="flex flex-wrap gap-2">
                {state.retryable && (
                  <Button
                    size="sm"
                    onClick={handleRetryQuestionGeneration}
                    disabled={retryingQuestion}
                    className="gap-2 bg-emerald-600 text-white hover:bg-emerald-500"
                  >
                    {retryingQuestion && (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    )}
                    继续处理
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => router.refresh()}
                >
                  重试连接
                </Button>
              </div>
            </CardContent>
          </Card>
        </motion.div>
      )}

      {state.phase === "cancelled" && (
        <Card>
          <CardContent className="pt-6 text-sm text-muted-foreground">
            此会话已取消。{" "}
            <Link
              href="/interview/setup"
              className="text-primary underline-offset-4 hover:underline"
            >
              开始新面试
            </Link>
            。
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function StatusBar({
  state,
  sessionId,
}: {
  state: ReturnType<typeof useQuestionPoller>["state"];
  sessionId: string;
}) {
  const label = phaseLabel(state.phase);
  const isActive = state.phase === "waiting_for_answer";
  const isError = state.phase === "error";
  const questionType =
    state.phase === "waiting_for_answer" && state.question
      ? extractQuestionType(state.question)
      : undefined;
  const formalTurnIdx =
    state.phase === "waiting_for_answer" && state.question
      ? extractFormalTurnIdx(state.question)
      : null;
  const turnLabel =
    questionType === "self_intro"
      ? "开场"
      : `第 ${
          formalTurnIdx !== null
            ? formalTurnIdx + 1
            : state.turnIdx !== null
              ? state.turnIdx + 1
              : "-"
        } 题`;
  const maxTurns = state.maxTurns;
  const currentFormalTurn =
    questionType === "self_intro"
      ? 0
      : formalTurnIdx !== null
        ? formalTurnIdx + 1
        : state.turnIdx !== null
          ? state.turnIdx + 1
          : 0;
  const progressPercent =
    typeof maxTurns === "number" && maxTurns > 0
      ? Math.min(100, Math.max(0, (currentFormalTurn / maxTurns) * 100))
      : 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-wrap items-center gap-3 rounded-xl border bg-card/80 backdrop-blur-sm p-3 text-xs"
    >
      <div className="flex items-center gap-1.5 font-mono">
        <div className="relative">
          <Activity
            className={
              isActive
                ? "h-3.5 w-3.5 text-emerald-400"
                : isError
                  ? "h-3.5 w-3.5 text-destructive"
                  : "h-3.5 w-3.5 animate-pulse text-amber-400"
            }
          />
          {isActive && (
            <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-emerald-400 animate-ping" />
          )}
        </div>
        <span className="uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
      </div>
      <span className="text-muted-foreground/40">·</span>
      <span className="font-mono text-muted-foreground">
        会话{" "}
        <span className="text-foreground">{truncateSession(sessionId)}</span>
      </span>
      <span className="text-muted-foreground/40">·</span>
      <span className="font-mono text-muted-foreground">
        <span className="text-foreground">{turnLabel}</span>
        {typeof maxTurns === "number" && maxTurns > 0 && questionType !== "self_intro" && (
          <span className="ml-1 text-muted-foreground">
            / {maxTurns}
          </span>
        )}
      </span>
      {typeof maxTurns === "number" && maxTurns > 0 && (
        <span className="flex min-w-[120px] items-center gap-2 text-muted-foreground">
          <span className="h-1.5 w-24 overflow-hidden rounded-full bg-secondary">
            <span
              className="block h-full rounded-full bg-emerald-400 transition-all"
              style={{ width: `${progressPercent}%` }}
            />
          </span>
          <span className="font-mono">
            {questionType === "self_intro" ? "0" : currentFormalTurn}/{maxTurns}
          </span>
        </span>
      )}
      <span className="ml-auto flex items-center gap-1.5 text-muted-foreground">
        <Sparkles className="h-3 w-3 text-emerald-400/60" />
        <span className="hidden sm:inline">AI 面试官追问中</span>
      </span>
    </motion.div>
  );
}

function ReauthRequiredBanner() {
  return (
    <Card className="border-amber-500/40 bg-amber-500/[0.04]">
      <CardContent className="flex flex-col gap-3 pt-5 text-sm sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="font-medium text-amber-300">需要重新授权模型配置</p>
          <p className="text-muted-foreground">
            当前面试恢复后缺少本轮 BYOK Key。打开模型设置更新后，再提交当前回答即可继续。
          </p>
        </div>
        <LLMSettingsDialog>
          <Button
            type="button"
            size="sm"
            className="shrink-0 bg-amber-600 text-white hover:bg-amber-500"
          >
            打开模型设置
          </Button>
        </LLMSettingsDialog>
      </CardContent>
    </Card>
  );
}

function AnswerBox({
  sessionId,
  turnIdx,
  onSubmit,
  onSkip,
  paused,
  onPause,
  onResume,
  submitting,
  skipping,
  questionType,
}: {
  sessionId: string;
  turnIdx: number | null;
  onSubmit: (text: string) => Promise<boolean>;
  onSkip: () => Promise<boolean>;
  paused: boolean;
  onPause: () => void;
  onResume: () => void;
  submitting: boolean;
  skipping: boolean;
  questionType?: string;
}) {
  const [draft, setDraft] = useState("");
  const [hintText, setHintText] = useState<string | null>(null);
  const [hintSource, setHintSource] = useState<string | null>(null);
  const [hintError, setHintError] = useState<string | null>(null);
  const [hintLoading, setHintLoading] = useState(false);
  const isSelfIntro = questionType === "self_intro";
  const trimmedLength = draft.trim().length;
  const nearLimit = draft.length >= ANSWER_MAX_LENGTH * 0.9;
  const draftKey = answerDraftKey(sessionId, turnIdx);

  useEffect(() => {
    try {
      setDraft(window.sessionStorage.getItem(draftKey) ?? "");
    } catch {
      setDraft("");
    }
  }, [draftKey]);

  useEffect(() => {
    try {
      if (draft) {
        window.sessionStorage.setItem(draftKey, draft);
      } else {
        window.sessionStorage.removeItem(draftKey);
      }
    } catch {
      /* ignore */
    }
  }, [draft, draftKey]);

  useEffect(() => {
    setHintText(null);
    setHintSource(null);
    setHintError(null);
    setHintLoading(false);
  }, [draftKey]);

  async function handleLocalSubmit() {
    const text = draft.trim();
    if (!text || submitting) return;
    const success = await onSubmit(text);
    if (success) {
      clearAnswerDraft(draftKey);
      setDraft("");
    }
  }

  async function handleLocalSkip() {
    if (submitting || skipping) return;
    const success = await onSkip();
    if (success) {
      clearAnswerDraft(draftKey);
      setDraft("");
    }
  }

  async function handleLocalHint() {
    if (hintLoading || turnIdx === null) return;
    setHintLoading(true);
    setHintError(null);
    try {
      const res = await requestHint(sessionId, turnIdx);
      setHintText(res.hint);
      setHintSource(res.source);
    } catch (err) {
      setHintError(err instanceof Error ? err.message : "暂时没能拿到提示");
    } finally {
      setHintLoading(false);
    }
  }

  return (
    <Card className="glow-emerald-sm border-emerald-500/20">
      <CardHeader className="flex flex-row items-center justify-between gap-3 pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <Send className="h-4 w-4 text-emerald-400" />
          你的回答
        </CardTitle>
        <Button
          asChild
          variant="outline"
          size="sm"
          className="h-8 gap-1.5"
        >
          <Link href={`/interview/${sessionId}/voice`}>
            <Mic className="h-3.5 w-3.5" />
            用语音回答
          </Link>
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {paused ? (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/[0.04] p-4 text-sm text-muted-foreground">
            <p className="font-medium text-amber-200">已暂停休息</p>
            <p className="mt-1">
              当前草稿已经保留，准备好后可以继续作答。
            </p>
          </div>
        ) : (
          <TextareaAutosize
            minRows={3}
            maxRows={15}
            maxLength={ANSWER_MAX_LENGTH}
            aria-label="输入你的回答"
            placeholder={
              isSelfIntro
                ? "可以从背景、代表项目、想重点展开的能力方向开始。按 Ctrl/Cmd+Enter 提交。"
                : "在此输入你的回答… 按 Ctrl/Cmd+Enter 提交。"
            }
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !submitting) {
                e.preventDefault();
                void handleLocalSubmit();
              }
            }}
            className="flex w-full rounded-md border border-input px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 resize-none border-border/50 bg-secondary/30 focus:border-emerald-500/30"
          />
        )}
        <div className="flex items-center justify-between">
          <span
            className={
              nearLimit
                ? "text-xs text-amber-400"
                : "text-xs text-muted-foreground"
            }
          >
            {draft.length > 0 &&
              `${trimmedLength} / ${ANSWER_MAX_LENGTH} 字${
                draft.length >= ANSWER_MAX_LENGTH ? "，已达上限" : ""
              }`}
          </span>
          <Button
            onClick={() => void handleLocalSubmit()}
            disabled={paused || submitting || !draft.trim()}
            className="gap-2 bg-emerald-600 hover:bg-emerald-500 text-white"
          >
            {submitting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ArrowRight className="h-4 w-4" />
            )}
            提交回答
          </Button>
        </div>
        <div className="flex flex-wrap gap-2">
          {paused ? (
            <Button type="button" variant="outline" size="sm" onClick={onResume}>
              继续作答
            </Button>
          ) : (
            <Button type="button" variant="ghost" size="sm" className="gap-1.5" onClick={onPause}>
              <Pause className="h-3.5 w-3.5" />
              暂停休息
            </Button>
          )}
          {!isSelfIntro && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="gap-1.5 text-muted-foreground"
              onClick={() => void handleLocalHint()}
              disabled={hintLoading || turnIdx === null}
            >
              {hintLoading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Lightbulb className="h-3.5 w-3.5" />
              )}
              求一点思路
            </Button>
          )}
          {!isSelfIntro && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="gap-1.5 text-muted-foreground"
              onClick={() => void handleLocalSkip()}
              disabled={submitting || skipping}
            >
              {skipping ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <SkipForward className="h-3.5 w-3.5" />
              )}
              跳过本题
            </Button>
          )}
        </div>
        {!isSelfIntro && (hintText || hintError || hintLoading) && (
          <div className="rounded-lg border border-emerald-500/25 bg-emerald-500/[0.04] p-3 text-sm">
            <div className="mb-1 flex items-center gap-2 font-medium text-emerald-200">
              {hintLoading ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Lightbulb className="h-3.5 w-3.5" />
              )}
              面试官提示
              {hintSource && (
                <span className="text-[11px] font-normal text-muted-foreground">
                  {hintSource}
                </span>
              )}
            </div>
            {hintLoading ? (
              <p className="text-muted-foreground">正在整理一点切入角度…</p>
            ) : hintError ? (
              <div className="space-y-2">
                <p className="text-amber-200">{hintError}</p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void handleLocalHint()}
                >
                  重试
                </Button>
              </div>
            ) : (
              <p className="text-muted-foreground">{hintText}</p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function answerDraftKey(sessionId: string, turnIdx: number | null): string {
  return `interviewAnswerDraft:${sessionId}:${turnIdx ?? "pending"}`;
}

function clearAnswerDraft(key: string): void {
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    /* ignore */
  }
}

const QaBubble = React.memo(function QaBubble({
  entry,
  isCurrent,
  onSpeak,
}: {
  entry: QaEntry;
  isCurrent: boolean;
  onSpeak: (question: string) => void;
}) {
  const isSelfIntro = entry.questionType === "self_intro";
  const turnLabel = isSelfIntro
    ? "开场"
    : entry.formalTurnIdx !== null && entry.formalTurnIdx !== undefined
      ? String(entry.formalTurnIdx + 1)
      : entry.turnIdx !== null
        ? String(entry.turnIdx + 1)
        : "?";

  const safeQuestion = useMemo(() => {
    return DOMPurify.sanitize(entry.question);
  }, [entry.question]);
  // Defense-in-depth: ReactMarkdown is configured *without* `rehype-raw`
  // so user-supplied raw HTML is dropped at parse time today and the
  // sanitizer is structurally redundant. The wrapper stays in place so a
  // future addition of `rehype-raw` (or a switch to `dangerouslySetInnerHTML`
  // for emoji shortcodes / KaTeX) does not silently open an XSS sink. If
  // the sanitizer is ever removed, also remove the `dompurify` dependency
  // from package.json to reclaim the bundle weight.

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs font-mono text-muted-foreground">
        <span
          className={`flex h-5 items-center justify-center rounded bg-secondary text-[10px] font-bold ${
            isSelfIntro ? "w-10" : "w-5"
          }`}
        >
          {turnLabel}
        </span>
        {isSelfIntro && (
          <Badge
            variant="outline"
            className="border-emerald-500/30 bg-emerald-500/5 text-[10px] text-emerald-300"
          >
            开场介绍
          </Badge>
        )}
        {!isSelfIntro && entry.dimension && (
          <Badge variant="outline" className="font-mono text-[10px]">
            {entry.dimension}
          </Badge>
        )}
        {resumeAnchorLabel(entry.resumeAnchor) && (
          <Badge
            variant="outline"
            className="border-emerald-500/30 bg-emerald-500/5 text-[10px] text-emerald-300"
          >
            本题围绕：{resumeAnchorLabel(entry.resumeAnchor)}
          </Badge>
        )}
        {isCurrent && entry.answer === null && (
          <Badge className="gap-1 bg-amber-500/10 text-amber-400 border-amber-500/20">
            等待你的回答
          </Badge>
        )}
        {entry.answer !== null && (
          <CheckCircle2 className="h-3 w-3 text-emerald-400" />
        )}
      </div>

      <div className="rounded-lg border bg-secondary/30 p-4 text-sm leading-relaxed">
        <div className="mb-1.5 flex items-center gap-1.5">
          <span className="flex h-5 w-5 items-center justify-center rounded bg-emerald-500/10 font-mono text-[10px] font-bold text-emerald-400">
            Q
          </span>
          <span className="font-mono text-[10px] text-muted-foreground">
            面试官
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="重播本题"
            onClick={() => onSpeak(entry.question)}
            className="ml-auto h-7 gap-1 px-2 text-xs text-muted-foreground hover:text-emerald-300"
          >
            <Volume2 className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">重播</span>
          </Button>
        </div>
        <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none">
          <ReactMarkdown>
            {safeQuestion}
          </ReactMarkdown>
        </div>
      </div>

      {entry.answer !== null && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          className="ml-6 rounded-lg border border-primary/10 bg-primary/[0.03] p-4 text-sm leading-relaxed"
        >
          <div className="mb-1.5 flex items-center gap-1.5">
            <span className="flex h-5 w-5 items-center justify-center rounded bg-primary/10 font-mono text-[10px] font-bold text-primary">
              A
            </span>
            <span className="font-mono text-[10px] text-muted-foreground">
              你
            </span>
          </div>
          <div className="whitespace-pre-wrap">
            {entry.answer}
          </div>
        </motion.div>
      )}
    </div>
  );
});

function phaseLabel(p: string): string {
  switch (p) {
    case "waiting_for_answer":
      return "等待回答";
    case "loading":
      return "思考中";
    case "completed":
      return "已完成";
    case "error":
      return "出错";
    case "cancelled":
      return "已取消";
    default:
      return "空闲";
  }
}

function extractQuestion(q: PollQuestion): string {
  if (typeof q.question === "string") return q.question;
  const inner = (q as Record<string, unknown>).current_question;
  if (
    inner &&
    typeof inner === "object" &&
    "question" in (inner as Record<string, unknown>)
  ) {
    const v = (inner as Record<string, unknown>).question;
    if (typeof v === "string") return v;
  }
  return JSON.stringify(q);
}

function extractResumeAnchor(q: PollQuestion): ResumeAnchor | undefined {
  if (q.resume_anchor && typeof q.resume_anchor === "object") {
    return q.resume_anchor;
  }
  const inner = (q as Record<string, unknown>).current_question;
  if (inner && typeof inner === "object") {
    const v = (inner as Record<string, unknown>).resume_anchor;
    if (v && typeof v === "object") return v as ResumeAnchor;
  }
  return undefined;
}

function extractQuestionType(q: PollQuestion): string | undefined {
  if (typeof q.question_type === "string") return q.question_type;
  const inner = (q as Record<string, unknown>).current_question;
  if (inner && typeof inner === "object") {
    const v = (inner as Record<string, unknown>).question_type;
    if (typeof v === "string") return v;
  }
  return undefined;
}

function extractFormalTurnIdx(q: PollQuestion): number | null {
  if (typeof q.formal_turn_idx === "number") return q.formal_turn_idx;
  const inner = (q as Record<string, unknown>).current_question;
  if (inner && typeof inner === "object") {
    const v = (inner as Record<string, unknown>).formal_turn_idx;
    if (typeof v === "number") return v;
  }
  return null;
}

function resumeAnchorLabel(anchor?: ResumeAnchor): string {
  return anchor?.project_name || anchor?.label || "";
}

function truncateSession(id: string): string {
  if (id.length <= 12) return id;
  return `${id.slice(0, 4)}…${id.slice(-4)}`;
}

function friendlyConnectionMessage(
  kind: LLMErrorKind | null,
  raw: string | null,
): string {
  switch (kind) {
    case "auth":
      return "保存的密钥可能已经失效、被撤销，或者没有当前模型的权限。去设置里更新一下 Key 再试。";
    case "quota":
      return "当前配置的额度不足或余额耗尽。换一个 Key，或者到厂商控制台检查余额。";
    case "rate_limit":
      return "请求太频繁了，稍后再试会更稳。";
    case "timeout":
      return "请求超时了，通常重试一下就好。";
    case "network":
      return "网络或服务暂时不稳定，检查一下网络后再点重试。";
    case "misconfig":
      return "有一项配置不完整或不匹配，请检查模型名称、服务商和 Base URL。";
    default:
      break;
  }
  if (!raw) return "稍等一下再试一次。";
  const lower = raw.toLowerCase();
  if (
    lower.includes("session not found") ||
    raw.includes("无法继续") ||
    raw.includes("重新开始一场面试")
  ) {
    return (
      "这场面试已经不在后端运行中，可能是后端重启、会话已结束，"
      + "或上一轮出题失败。请回到首页重新开始一场面试。"
    );
  }
  if (lower.includes("network") || lower.includes("fetch") || lower.includes("failed to fetch")) {
    return "网络好像不太稳定。检查一下网络后再点重试。";
  }
  if (lower.startsWith("5") || lower.includes("500") || lower.includes("502") || lower.includes("503")) {
    return "服务暂时有点忙不过来。稍等几秒再试一次就好。";
  }
  if (lower.includes("timeout")) {
    return "请求超时了。可以点重试再来一次。";
  }
  return "稍等一下再试一次。如果一直不行，记一下当前面试编号联系我们。";
}

function friendlyAnswerError(raw: string): string {
  const lower = raw.toLowerCase();
  if (lower.includes("network") || lower.includes("fetch")) {
    return "网络似乎中断了，刚才的回答还没保存。检查网络后再提交一次试试。";
  }
  if (lower.includes("timeout")) {
    return "提交超时了。再来一次通常就能成功。";
  }
  return "刚才的回答没能成功提交，再试一次试试。";
}
