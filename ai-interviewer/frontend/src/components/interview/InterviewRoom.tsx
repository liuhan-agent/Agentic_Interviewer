"use client";

import { useRouter } from "next/navigation";
import React, { useCallback, useEffect, useRef, useState, useMemo } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Camera,
  CameraOff,
  CheckCircle2,
  Loader2,
  Maximize2,
  MessageSquare,
  Mic,
  Minimize2,
  Pause,
  Send,
  SkipForward,
  Lightbulb,
  Play,
  Sparkles,
  Volume2,
  VolumeX,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

import DOMPurify from "dompurify";
import ReactMarkdown from "react-markdown";
import TextareaAutosize from "react-textarea-autosize";

import { LLMSettingsDialog } from "@/components/layout/LLMSettingsDialog";
import { CollapsibleAnswerBubble } from "@/components/interview/CollapsibleAnswerBubble";
import {
  NextQuestionLoader,
  type AnswerInsight,
} from "@/components/interview/NextQuestionLoader";
import { SessionIdTooltip } from "@/components/interview/SessionIdTooltip";
import { VoiceAnswerPanel } from "@/components/interview/VoiceAnswerPanel";
import { PendingNavigationLink } from "@/components/navigation/PendingNavigationLink";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  isReauthRequired,
  listInterviewWaitingTips,
  requestHint,
  retryFailedQuestion,
  skipQuestion,
  synthesizeQuestionAudio,
  submitAnswer,
} from "@/lib/api/interview";
import type {
  LLMErrorKind,
  InterviewWaitingTipsResponse,
  PollQuestion,
  PreviousTurnEvaluation,
  ResumeAnchor,
  ResumeHistoryTurn,
} from "@/lib/api/types";
import { useQuestionPoller } from "@/lib/hooks/useQuestionPoller";
import {
  useTurnVideoCapture,
  type TurnVideoStatus,
} from "@/lib/hooks/useTurnVideoCapture";
import { useToast } from "@/lib/hooks/useToast";
import { cn } from "@/lib/utils";
import { formatDimensionName } from "@/lib/constants/interview";
import {
  loadQuestionSpeechEnabled,
  storeQuestionSpeechEnabled,
} from "@/lib/question-speaker";
import { upsertEntry } from "@/lib/storage/interviewHistory";
import type { AggregatedVideoSignal } from "@/lib/video/types";

const ENCOURAGEMENTS = [
  "已收到回答，正在准备下一题。",
  "回答已提交，AI 面试官正在整理追问。",
  "这一轮已记录，稍等片刻进入下一题。",
  "已保存本轮回答，继续保持节奏。",
  "提交成功，正在生成下一轮问题。",
];
const ANSWER_MAX_LENGTH = 8000;

type QaEntry = {
  turnIdx: number | null;
  formalTurnIdx?: number | null;
  displayTurnIdx?: number | null;
  questionType?: string;
  dimension?: string;
  resumeAnchor?: ResumeAnchor;
  question: string;
  answer: string | null;
  evaluation?: PreviousTurnEvaluation | null;
};
type QuestionSpeechStatus = "idle" | "speaking" | "paused";
type QuestionSpeechState = {
  key: string | null;
  status: QuestionSpeechStatus;
  runId: number | null;
};
type AnswerMode = "text" | "voice";
type AnswerSelection = {
  start: number;
  end: number;
};
type VoiceInsertRecord = {
  start: number;
  end: number;
  text: string;
};

export function InterviewRoom({
  sessionId,
  defaultAnswerMode = "text",
}: {
  sessionId: string;
  defaultAnswerMode?: AnswerMode;
}) {
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
  const [finalTurnSubmitted, setFinalTurnSubmitted] = useState(false);
  const [readQuestions, setReadQuestions] = useState(false);
  const [waitingTipsResponse, setWaitingTipsResponse] =
    useState<InterviewWaitingTipsResponse | null>(null);
  const [questionSpeechState, setQuestionSpeechState] =
    useState<QuestionSpeechState>({ key: null, status: "idle", runId: null });
  const [reauthRequired, setReauthRequired] = useState(false);
  const transcriptEnd = useRef<HTMLDivElement>(null);
  const lastSpokenQuestionRef = useRef<string | null>(null);
  const displayedWaitingTipIdsRef = useRef<Set<string>>(new Set());
  const questionSpeechRunRef = useRef(0);
  const questionAudioRef = useRef<HTMLAudioElement | null>(null);
  const questionAudioUrlRef = useRef<string | null>(null);
  const currentQuestionType =
    state.phase === "waiting_for_answer" && state.question
      ? extractQuestionType(state.question)
      : undefined;
  const currentDisplayTurnIdx =
    state.phase === "waiting_for_answer" && history.length > 0
      ? visibleTurnIdx(history[history.length - 1])
      : null;
  const latestSubmittedAnswerInsight = useMemo(
    () => answerInsightFromHistory(history),
    [history],
  );
  const videoTurnIdx =
    state.phase === "waiting_for_answer" ? state.turnIdx : null;
  const videoCapture = useTurnVideoCapture({
    enableVideoAnalysis: state.enableVideoAnalysis,
    turnIdx: videoTurnIdx,
    paused,
  });

  const stopQuestionAudio = useCallback(() => {
    const audio = questionAudioRef.current;
    if (audio) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
    }
    if (questionAudioUrlRef.current) {
      URL.revokeObjectURL(questionAudioUrlRef.current);
      questionAudioUrlRef.current = null;
    }
  }, []);

  const nextQuestionSpeechRunId = useCallback(() => {
    questionSpeechRunRef.current += 1;
    return questionSpeechRunRef.current;
  }, []);

  const resetQuestionSpeechState = useCallback((runId: number) => {
    setQuestionSpeechState((current) =>
      current.runId === runId
        ? { key: null, status: "idle", runId: null }
        : current,
    );
  }, []);

  const markQuestionAudioUnavailable = useCallback(
    (runId: number, message?: string) => {
      if (questionSpeechRunRef.current !== runId) return;
      stopQuestionAudio();
      setQuestionSpeechState({ key: null, status: "idle", runId: null });
      toast({
        title: "题目语音合成不可用",
        description:
          message ??
          "没有收到可播放的后端 TTS 音频。请检查语音合成 Key、模型和 Base URL。",
      });
    },
    [stopQuestionAudio, toast],
  );

  const playQuestionAudio = useCallback(
    async (blob: Blob, text: string, runId: number): Promise<boolean> => {
      if (questionAudioUrlRef.current) {
        URL.revokeObjectURL(questionAudioUrlRef.current);
        questionAudioUrlRef.current = null;
      }
      const audio = questionAudioRef.current ?? new Audio();
      questionAudioRef.current = audio;
      const url = URL.createObjectURL(blob);
      questionAudioUrlRef.current = url;
      audio.onended = () => {
        if (questionSpeechRunRef.current === runId) {
          resetQuestionSpeechState(runId);
        }
      };
      audio.onerror = () => {
        if (questionSpeechRunRef.current === runId) {
          markQuestionAudioUnavailable(runId, "题目音频加载失败，无法播放。");
        }
      };
      audio.dataset.questionText = text;
      audio.src = url;
      try {
        await audio.play();
        return true;
      } catch {
        stopQuestionAudio();
        return false;
      }
    },
    [markQuestionAudioUnavailable, resetQuestionSpeechState, stopQuestionAudio],
  );

  const handleSpeakQuestion = useCallback(
    async (text: string, turnIdx?: number | null) => {
      const speechKey = questionSpeechKey(text);
      const runId = nextQuestionSpeechRunId();
      setQuestionSpeechState({ key: speechKey, status: "speaking", runId });
      stopQuestionAudio();
      if (turnIdx === null || turnIdx === undefined) {
        markQuestionAudioUnavailable(runId, "当前题目状态还没准备好，暂时无法合成语音。");
        return;
      }
      try {
        const blob = await synthesizeQuestionAudio(sessionId, text, turnIdx);
        if (questionSpeechRunRef.current !== runId) return;
        if (blob.size > 0 && (await playQuestionAudio(blob, text, runId))) {
          return;
        }
        markQuestionAudioUnavailable(runId, "后端返回的题目音频为空或无法播放。");
      } catch (error) {
        const message =
          error instanceof Error
            ? `后端题目语音接口失败：${error.message}`
            : "后端题目语音接口失败。";
        markQuestionAudioUnavailable(runId, message);
      }
    },
    [
      markQuestionAudioUnavailable,
      nextQuestionSpeechRunId,
      playQuestionAudio,
      sessionId,
      stopQuestionAudio,
    ],
  );

  useEffect(() => {
    setReadQuestions(loadQuestionSpeechEnabled());
    return () => {
      stopQuestionAudio();
    };
  }, [stopQuestionAudio]);

  useEffect(() => {
    let active = true;
    listInterviewWaitingTips()
      .then((payload) => {
        if (active) {
          setWaitingTipsResponse(payload);
        }
      })
      .catch(() => {
        if (active) {
          setWaitingTipsResponse(null);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const restored = state.restoredHistory
      .map(restoredTurnToQaEntry)
      .filter((entry): entry is QaEntry => Boolean(entry));
    if (restored.length === 0) return;
    const currentTurnIdxForDisplay =
      state.phase === "waiting_for_answer" && state.question
        ? extractFormalTurnIdx(state.question) ?? state.turnIdx
        : null;
    const priorRestored = filterRestoredHistoryForCurrentQuestion(
      restored,
      currentTurnIdxForDisplay,
    );
    setHistory((prev) => {
      const openEntry = prev.find((entry) => entry.answer === null);
      const answered = prev.filter((entry) => entry.answer !== null);
      const alreadyRestored =
        answered.length === priorRestored.length &&
        answered.every((entry, index) => sameQaEntry(entry, priorRestored[index]));
      if (alreadyRestored) return prev;
      return openEntry ? [...priorRestored, openEntry] : priorRestored;
    });
  }, [state.phase, state.question, state.restoredHistory, state.turnIdx]);

  useEffect(() => {
    if (state.phase !== "waiting_for_answer" || !state.question) return;
    const q = state.question;
    const turnIdx = state.turnIdx;
    setHistory((prev) => {
      const lastOpen = prev[prev.length - 1];
      const qText = extractQuestion(q);
      const formalTurnIdx = extractFormalTurnIdx(q);
      const currentTurnIdxForDisplay = formalTurnIdx ?? turnIdx;
      if (
        lastOpen &&
        lastOpen.answer === null &&
        (lastOpen.turnIdx === turnIdx ||
          visibleTurnIdx(lastOpen) === currentTurnIdxForDisplay)
      ) {
        return prev;
      }
      return [
        ...prev,
        {
          turnIdx,
          formalTurnIdx,
          displayTurnIdx: currentTurnIdxForDisplay,
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
    const evaluation = state.previousEvaluation;
    if (!evaluation) return;
    setHistory((prev) =>
      prev.map((entry) =>
        qaEntryMatchesEvaluation(entry, evaluation)
          ? { ...entry, evaluation }
          : entry,
      ),
    );
  }, [state.previousEvaluation]);

  useEffect(() => {
    setPaused(false);
    setFinalTurnSubmitted(false);
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
    if (
      !readQuestions ||
      paused ||
      state.phase !== "waiting_for_answer" ||
      !state.question
    ) {
      return;
    }
    const qText = extractQuestion(state.question);
    const lastSpokenKey = `${state.turnIdx ?? "intro"}:${qText}`;
    if (lastSpokenQuestionRef.current === lastSpokenKey) return;
    lastSpokenQuestionRef.current = lastSpokenKey;
    void handleSpeakQuestion(qText, state.turnIdx);
  }, [
    paused,
    readQuestions,
    state.phase,
    state.question,
    state.turnIdx,
    handleSpeakQuestion,
  ]);

  function handleWaitingTipShown(tipId: string) {
    displayedWaitingTipIdsRef.current.add(tipId);
  }

  function handleStopQuestionSpeech() {
    stopQuestionAudio();
    setQuestionSpeechState({ key: null, status: "idle", runId: null });
  }

  function handlePauseQuestionSpeech() {
    if (questionAudioRef.current && !questionAudioRef.current.paused) {
      questionAudioRef.current.pause();
      setQuestionSpeechState((current) => ({
        key: current.key,
        status: current.key ? "paused" : "idle",
        runId: current.runId,
      }));
      return;
    }
    setQuestionSpeechState((current) => ({
      key: current.key,
      status: current.key ? "paused" : "idle",
      runId: current.runId,
    }));
  }

  function handleResumeQuestionSpeech() {
    const audio = questionAudioRef.current;
    if (audio && audio.paused && audio.src) {
      audio
        .play()
        .catch(() =>
          markQuestionAudioUnavailable(
            questionSpeechRunRef.current,
            "题目音频继续播放失败。",
          ),
        );
      setQuestionSpeechState((current) => ({
        key: current.key,
        status: current.key ? "speaking" : "idle",
        runId: current.runId,
      }));
      return;
    }
    setQuestionSpeechState((current) => ({
      key: current.key,
      status: current.key ? "speaking" : "idle",
      runId: current.runId,
    }));
  }

  function handleToggleQuestionSpeech() {
    const next = !readQuestions;
    setReadQuestions(next);
    storeQuestionSpeechEnabled(next);
    if (!next) {
      handleStopQuestionSpeech();
      return;
    }
    if (state.phase === "waiting_for_answer" && state.question) {
      const qText = extractQuestion(state.question);
      lastSpokenQuestionRef.current = `${state.turnIdx ?? "intro"}:${qText}`;
      void handleSpeakQuestion(qText, state.turnIdx);
    }
  }

  async function handleSubmit(
    text: string,
    videoSignals?: AggregatedVideoSignal | null,
  ) {
    if (!text || submitting) return false;
    if (state.turnIdx === null) {
      toast({
        title: "Question state is not ready",
        description: "Please wait for the current question to finish loading.",
      });
      return false;
    }
    setSubmitting(true);
    const submittedWasFinal = isFinalFormalTurn({
      question: state.question,
      turnIdx: state.turnIdx,
      maxTurns: state.maxTurns,
    });
    try {
      await submitAnswer(sessionId, text, state.turnIdx, videoSignals ?? undefined);
      setReauthRequired(false);
      setPaused(false);
      setHistory((prev) => {
        if (prev.length === 0) return prev;
        const next = prev.slice();
        next[next.length - 1] = {
          ...next[next.length - 1],
          answer: text,
          evaluation: undefined,
        };
        return next;
      });
      setLastSubmittedTurn(state.turnIdx ?? null);
      setFinalTurnSubmitted(submittedWasFinal);
      afterAnswerSubmitted();
      // Lightweight encouragement so users feel acknowledged between turns.
      toast({
        title: submittedWasFinal
          ? "最后一题已提交，正在整理本场面试总结。"
          : ENCOURAGEMENTS[Math.floor(Math.random() * ENCOURAGEMENTS.length)],
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
    const skippedWasFinal = isFinalFormalTurn({
      question: state.question,
      turnIdx: state.turnIdx,
      maxTurns: state.maxTurns,
    });
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
      setFinalTurnSubmitted(skippedWasFinal);
      afterAnswerSubmitted();
      toast({
        title: skippedWasFinal
          ? "已跳过最后一题，正在整理本场面试总结。"
          : "已跳过本题，继续下一轮练习。",
      });
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
      setFinalTurnSubmitted(false);
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
      <StatusBar
        state={state}
        sessionId={sessionId}
        currentDisplayTurnIdx={currentDisplayTurnIdx}
      />

      {state.enableVideoAnalysis && (
        <>
          <VideoMobileControl
            cameraOn={videoCapture.cameraOn}
            status={videoCapture.status}
            onToggleCamera={videoCapture.toggleCamera}
          />
          <VideoPreviewPanel
            cameraOn={videoCapture.cameraOn}
            videoRef={videoCapture.videoRef}
            status={videoCapture.status}
            warning={videoCapture.warning}
            onToggleCamera={videoCapture.toggleCamera}
            className="hidden xl:block"
          />
        </>
      )}

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
                  effectiveTurnIdx={
                    idx === history.length - 1 &&
                    state.phase === "waiting_for_answer"
                      ? state.turnIdx
                      : t.turnIdx
                  }
                  questionSpeechState={questionSpeechState}
                  showTurnFeedback={
                    !(state.phase === "loading" && idx === history.length - 1)
                  }
                  onSpeak={(question, turnIdx) =>
                    void handleSpeakQuestion(question, turnIdx)
                  }
                  onPauseSpeaking={handlePauseQuestionSpeech}
                  onResumeSpeaking={handleResumeQuestionSpeech}
                />
              </motion.div>
            ))}
          </AnimatePresence>

          {state.phase === "loading" && lastSubmittedTurn !== null && (
            <NextQuestionLoader
              etaMs={state.lastServerLatencyMs}
              isFinalTurn={finalTurnSubmitted}
              answerInsight={latestSubmittedAnswerInsight}
              waitingTips={waitingTipsResponse?.tips ?? null}
              tipRotationIntervalMs={waitingTipsResponse?.rotation_interval_ms}
              displayedTipIds={displayedWaitingTipIdsRef.current}
              onWaitingTipShown={handleWaitingTipShown}
            />
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
                handleStopQuestionSpeech();
                setPaused(true);
              }}
              onResume={() => setPaused(false)}
              submitting={submitting}
              skipping={skipping}
              questionType={currentQuestionType}
              defaultMode={defaultAnswerMode}
              finishTurnCapture={videoCapture.finishTurnCapture}
              clearTurnCapture={videoCapture.clearTurnCapture}
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
            <PendingNavigationLink
              href="/interview/setup"
              pendingLabel="打开中..."
              className="text-primary underline-offset-4 hover:underline"
            >
              开始新面试
            </PendingNavigationLink>
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
  currentDisplayTurnIdx,
}: {
  state: ReturnType<typeof useQuestionPoller>["state"];
  sessionId: string;
  currentDisplayTurnIdx?: number | null;
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
          currentDisplayTurnIdx !== null && currentDisplayTurnIdx !== undefined
            ? currentDisplayTurnIdx + 1
            : formalTurnIdx !== null
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
        <span className="text-foreground">
          <SessionIdTooltip sessionId={sessionId} />
        </span>
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
  defaultMode,
  finishTurnCapture,
  clearTurnCapture,
}: {
  sessionId: string;
  turnIdx: number | null;
  onSubmit: (text: string, videoSignals?: AggregatedVideoSignal | null) => Promise<boolean>;
  onSkip: () => Promise<boolean>;
  paused: boolean;
  onPause: () => void;
  onResume: () => void;
  submitting: boolean;
  skipping: boolean;
  questionType?: string;
  defaultMode: AnswerMode;
  finishTurnCapture: () => AggregatedVideoSignal | null;
  clearTurnCapture: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [voiceToolsOpen, setVoiceToolsOpen] = useState(defaultMode === "voice");
  const [hintText, setHintText] = useState<string | null>(null);
  const [hintSource, setHintSource] = useState<string | null>(null);
  const [hintError, setHintError] = useState<string | null>(null);
  const [hintLoading, setHintLoading] = useState(false);
  const [answerExpanded, setAnswerExpanded] = useState(false);
  const answerInputRef = useRef<HTMLTextAreaElement | null>(null);
  const answerSelectionRef = useRef<AnswerSelection | null>(null);
  const pendingSelectionRef = useRef<number | null>(null);
  const lastVoiceInsertRef = useRef<VoiceInsertRecord | null>(null);
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
    setAnswerExpanded(false);
    answerSelectionRef.current = null;
    pendingSelectionRef.current = null;
    lastVoiceInsertRef.current = null;
    clearTurnCapture();
  }, [clearTurnCapture, draftKey]);

  useEffect(() => {
    if (paused) clearTurnCapture();
  }, [clearTurnCapture, paused]);

  useEffect(() => {
    const position = pendingSelectionRef.current;
    if (position === null) return;
    pendingSelectionRef.current = null;
    const input = answerInputRef.current;
    if (!input) return;
    input.focus();
    input.setSelectionRange(position, position);
    updateAnswerSelection(input);
  }, [draft]);

  async function handleLocalSubmit() {
    const text = draft.trim();
    if (!text || submitting) return;
    const videoSignals = finishTurnCapture();
    const success = await onSubmit(text, videoSignals);
    if (success) {
      clearTurnCapture();
      clearAnswerDraft(draftKey);
      setDraft("");
    }
  }

  function handleVoiceTranscript(text: string) {
    setDraft((current) => {
      const result = insertTranscriptAtSelection(
        current,
        text,
        answerSelectionRef.current,
        ANSWER_MAX_LENGTH,
      );
      pendingSelectionRef.current = result.cursor;
      lastVoiceInsertRef.current = result.inserted;
      return result.value;
    });
  }

  function handleUndoVoiceTranscript() {
    setDraft((current) => {
      const result = removeLastVoiceInsert(current, lastVoiceInsertRef.current);
      pendingSelectionRef.current = result.cursor;
      lastVoiceInsertRef.current = null;
      return result.value;
    });
  }

  function updateAnswerSelection(input = answerInputRef.current) {
    if (!input) return;
    answerSelectionRef.current = {
      start: input.selectionStart,
      end: input.selectionEnd,
    };
  }

  async function handleLocalSkip() {
    if (submitting || skipping) return;
    const success = await onSkip();
    if (success) {
      clearTurnCapture();
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
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-expanded={answerExpanded}
            aria-controls="answer-draft-input"
            onClick={() => setAnswerExpanded((value) => !value)}
            className="h-8 gap-1.5 text-muted-foreground"
          >
            {answerExpanded ? (
              <Minimize2 className="h-3.5 w-3.5" />
            ) : (
              <Maximize2 className="h-3.5 w-3.5" />
            )}
            {answerExpanded ? "收起" : "展开"}
          </Button>
          <Button
            type="button"
            variant={voiceToolsOpen ? "outline" : "ghost"}
            size="sm"
            aria-expanded={voiceToolsOpen}
            onClick={() => setVoiceToolsOpen((value) => !value)}
            className="h-8 gap-1.5"
          >
            <Mic className="h-3.5 w-3.5" />
            用语音回答
          </Button>
        </div>
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
            ref={answerInputRef}
            id="answer-draft-input"
            minRows={answerExpanded ? 10 : 3}
            maxRows={answerExpanded ? 24 : 8}
            maxLength={ANSWER_MAX_LENGTH}
            aria-label="输入你的回答"
            placeholder={
              isSelfIntro
                ? "可以从背景、代表项目、想重点展开的能力方向开始。按 Ctrl/Cmd+Enter 提交。"
                : "在此输入你的回答… 按 Ctrl/Cmd+Enter 提交。"
            }
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              updateAnswerSelection(e.currentTarget);
            }}
            onClick={(e) => updateAnswerSelection(e.currentTarget)}
            onKeyUp={(e) => updateAnswerSelection(e.currentTarget)}
            onSelect={(e) => updateAnswerSelection(e.currentTarget)}
            onFocus={(e) => updateAnswerSelection(e.currentTarget)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !submitting) {
                e.preventDefault();
                void handleLocalSubmit();
              }
            }}
            className={cn(
              "flex w-full resize-none overflow-y-auto rounded-md border border-input border-border/50 bg-secondary/30 px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus:border-emerald-500/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
              answerExpanded ? "min-h-[18rem]" : "",
            )}
          />
        )}
        {voiceToolsOpen && (
          <VoiceAnswerPanel
            sessionId={sessionId}
            turnIdx={turnIdx}
            disabled={paused || draft.trim().length >= ANSWER_MAX_LENGTH}
            submitting={submitting}
            maxLength={ANSWER_MAX_LENGTH}
            onTranscript={handleVoiceTranscript}
            canUndoTranscript={lastVoiceInsertRef.current !== null}
            onUndoTranscript={handleUndoVoiceTranscript}
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
        </div>
        {(hintText || hintError || hintLoading) && (
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

function VideoMobileControl({
  cameraOn,
  status,
  onToggleCamera,
}: {
  cameraOn: boolean;
  status: TurnVideoStatus;
  onToggleCamera: () => Promise<void>;
}) {
  return (
    <div className="xl:hidden flex items-center justify-between rounded-lg border border-emerald-500/20 bg-emerald-500/[0.04] px-3 py-2 text-sm">
      <div className="flex min-w-0 items-center gap-2 text-muted-foreground">
        {cameraOn ? (
          <Camera className="h-4 w-4 shrink-0 text-emerald-300" />
        ) : (
          <CameraOff className="h-4 w-4 shrink-0 text-muted-foreground" />
        )}
        <span className="truncate">{videoStatusLabel(status, cameraOn)}</span>
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => void onToggleCamera()}
        className="h-8 shrink-0 gap-1.5"
      >
        {cameraOn ? (
          <CameraOff className="h-3.5 w-3.5" />
        ) : (
          <Camera className="h-3.5 w-3.5" />
        )}
        {cameraOn ? "关闭" : "开启"}
      </Button>
    </div>
  );
}

function VideoPreviewPanel({
  cameraOn,
  videoRef,
  status,
  warning,
  onToggleCamera,
  className,
}: {
  cameraOn: boolean;
  videoRef: React.RefObject<HTMLVideoElement>;
  status: TurnVideoStatus;
  warning: string | null;
  onToggleCamera: () => Promise<void>;
  className?: string;
}) {
  return (
    <aside
      aria-label="视频面试预览"
      className={cn(
        "fixed right-6 top-20 z-40 w-64 overflow-hidden rounded-lg border border-emerald-500/20 bg-background/95 shadow-2xl shadow-black/30 backdrop-blur",
        className,
      )}
    >
      <div className="relative aspect-video bg-black/80">
        <video
          ref={videoRef}
          autoPlay
          muted
          playsInline
          className={cn(
            "h-full w-full scale-x-[-1] object-cover",
            !cameraOn && "opacity-20",
          )}
        />
        {!cameraOn && (
          <div className="absolute inset-0 flex items-center justify-center text-muted-foreground">
            <CameraOff className="h-7 w-7" />
          </div>
        )}
      </div>
      <div className="space-y-2 p-3">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="truncate text-xs font-medium">
              {videoStatusLabel(status, cameraOn)}
            </p>
            {warning && (
              <p className="mt-1 line-clamp-2 text-[11px] text-amber-200/80">
                {warning}
              </p>
            )}
          </div>
          <TooltipProvider delayDuration={150}>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  type="button"
                  variant={cameraOn ? "outline" : "default"}
                  size="icon"
                  aria-label={cameraOn ? "关闭摄像头" : "开启摄像头"}
                  onClick={() => void onToggleCamera()}
                  className="h-8 w-8 shrink-0"
                >
                  {cameraOn ? (
                    <CameraOff className="h-4 w-4" />
                  ) : (
                    <Camera className="h-4 w-4" />
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="bottom" align="end" className="max-w-56 text-xs leading-relaxed">
                {cameraOn
                  ? "关闭摄像头会清空当前题已采集的视频信号，不影响继续作答。"
                  : "开启摄像头后，本题会尝试采集本地视频信号作为辅助反馈。"}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </div>
    </aside>
  );
}

function videoStatusLabel(status: TurnVideoStatus, cameraOn: boolean): string {
  if (status === "disabled") return "未开启视频面试";
  if (status === "starting") return "正在开启摄像头";
  if (status === "capturing") return "摄像头已开启";
  if (status === "paused") return "已暂停采集";
  if (status === "unavailable") return "摄像头不可用";
  if (!cameraOn || status === "camera_off") return "摄像头已关闭";
  return "摄像头待命";
}

function answerDraftKey(sessionId: string, turnIdx: number | null): string {
  return `interviewAnswerDraft:${sessionId}:${turnIdx ?? "pending"}`;
}

function appendTranscriptToDraft(current: string, transcript: string): {
  value: string;
  cursor: number;
  inserted: VoiceInsertRecord | null;
} {
  const addition = transcript.trim();
  if (!addition) return { value: current, cursor: current.length, inserted: null };
  const base = current.trimEnd();
  if (!base) {
    return {
      value: addition,
      cursor: addition.length,
      inserted: { start: 0, end: addition.length, text: addition },
    };
  }
  const value = `${base}\n${addition}`;
  return {
    value,
    cursor: value.length,
    inserted: { start: base.length + 1, end: value.length, text: addition },
  };
}

function insertTranscriptAtSelection(
  current: string,
  transcript: string,
  selection: AnswerSelection | null,
  maxLength: number,
): { value: string; cursor: number; inserted: VoiceInsertRecord | null } {
  const addition = transcript.trim();
  if (!addition) {
    const cursor = selection?.end ?? current.length;
    return { value: current, cursor, inserted: null };
  }
  if (!selection) {
    return appendTranscriptToDraft(current, addition);
  }
  const start = Math.max(0, Math.min(selection.start, current.length));
  const end = Math.max(start, Math.min(selection.end, current.length));
  const prefix = current.slice(0, start);
  const suffix = current.slice(end);
  const needsLeadingSpace = prefix.length > 0 && !/\s$/.test(prefix);
  const needsTrailingSpace = suffix.length > 0 && !/^\s/.test(suffix);
  const inserted = `${needsLeadingSpace ? " " : ""}${addition}${
    needsTrailingSpace ? " " : ""
  }`;
  const value = `${prefix}${inserted}${suffix}`.slice(0, maxLength);
  const startIndex = prefix.length + (needsLeadingSpace ? 1 : 0);
  const endIndex = Math.min(startIndex + addition.length, value.length);
  return {
    value,
    cursor: Math.min(prefix.length + inserted.length, value.length),
    inserted:
      endIndex > startIndex
        ? { start: startIndex, end: endIndex, text: value.slice(startIndex, endIndex) }
        : null,
  };
}

function removeLastVoiceInsert(
  current: string,
  record: VoiceInsertRecord | null,
): { value: string; cursor: number } {
  if (!record) return { value: current, cursor: current.length };
  const actual = current.slice(record.start, record.end);
  if (actual !== record.text) return { value: current, cursor: current.length };
  return {
    value: `${current.slice(0, record.start)}${current.slice(record.end)}`,
    cursor: record.start,
  };
}

function questionSpeechKey(question: string): string {
  return question;
}

function getQuestionSpeechLabel(status: QuestionSpeechStatus): {
  ariaLabel: string;
  icon: "replay" | "pause" | "resume";
  text: string;
} {
  if (status === "speaking") {
    return { ariaLabel: "暂停读题", icon: "pause", text: "暂停" };
  }
  if (status === "paused") {
    return { ariaLabel: "继续读题", icon: "resume", text: "继续" };
  }
  return { ariaLabel: "重播本题", icon: "replay", text: "重播" };
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
  effectiveTurnIdx,
  questionSpeechState,
  showTurnFeedback,
  onSpeak,
  onPauseSpeaking,
  onResumeSpeaking,
}: {
  entry: QaEntry;
  isCurrent: boolean;
  effectiveTurnIdx: number | null;
  questionSpeechState: QuestionSpeechState;
  showTurnFeedback: boolean;
  onSpeak: (question: string, turnIdx: number | null) => void;
  onPauseSpeaking: () => void;
  onResumeSpeaking: () => void;
}) {
  const isSelfIntro = entry.questionType === "self_intro";
  const isCurrentSpeech =
    questionSpeechState.key === questionSpeechKey(entry.question);
  const questionSpeechLabel = getQuestionSpeechLabel(
    isCurrentSpeech ? questionSpeechState.status : "idle",
  );
  const displayTurnIdx =
    entry.displayTurnIdx ?? entry.formalTurnIdx ?? entry.turnIdx;
  const turnLabel = isSelfIntro
    ? "开场"
    : displayTurnIdx !== null && displayTurnIdx !== undefined
      ? String(displayTurnIdx + 1)
      : "?";
  const turnBadgeText = isSelfIntro ? turnLabel : `第 ${turnLabel} 题`;
  const answerContentId = `answer-content-${entry.turnIdx ?? "intro"}`;

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
          className={cn(
            "flex h-8 min-w-[4.5rem] items-center justify-center rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-3 text-sm font-black text-emerald-200 shadow-sm",
            isSelfIntro ? "min-w-[4rem]" : "",
          )}
        >
          {turnBadgeText}
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
          <Badge
            variant="outline"
            aria-label={`维度：${formatDimensionName(entry.dimension)}`}
            className="h-6 gap-1.5 rounded-md border-border/70 bg-secondary/30 px-2.5 text-[11px] font-medium text-muted-foreground shadow-none"
          >
            <span
              aria-hidden="true"
              className="h-1.5 w-1.5 rounded-full bg-emerald-400/70"
            />
            {formatDimensionName(entry.dimension)}
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
            aria-label={questionSpeechLabel.ariaLabel}
            onClick={() => {
              if (!isCurrentSpeech || questionSpeechState.status === "idle") {
                onSpeak(entry.question, effectiveTurnIdx);
              } else if (questionSpeechState.status === "speaking") {
                onPauseSpeaking();
              } else {
                onResumeSpeaking();
              }
            }}
            className="ml-auto h-7 gap-1 px-2 text-xs text-muted-foreground hover:text-emerald-300"
          >
            {questionSpeechLabel.icon === "pause" ? (
              <Pause className="h-3.5 w-3.5" />
            ) : questionSpeechLabel.icon === "resume" ? (
              <Play className="h-3.5 w-3.5" />
            ) : (
              <Volume2 className="h-3.5 w-3.5" />
            )}
            <span className="hidden sm:inline">
              {questionSpeechLabel.text}
            </span>
          </Button>
        </div>
        <div className="prose prose-sm prose-neutral dark:prose-invert max-w-none">
          <ReactMarkdown>
            {safeQuestion}
          </ReactMarkdown>
        </div>
      </div>

      {entry.answer !== null && (
        <CollapsibleAnswerBubble
          text={entry.answer}
          contentId={answerContentId}
          className="ml-6"
        />
      )}
      {showTurnFeedback &&
        entry.answer !== null &&
        hasDisplayableTurnFeedback(entry.evaluation) && (
          <TurnFeedbackSummary evaluation={entry.evaluation} />
        )}
    </div>
  );
});

function TurnFeedbackSummary({
  evaluation,
}: {
  evaluation: PreviousTurnEvaluation;
}) {
  const verdict = getTurnFeedbackVerdict(evaluation);
  const VerdictIcon = verdict.icon;

  return (
    <div
      className={cn(
        "ml-6 rounded-lg border p-3 text-xs shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]",
        verdict.containerClass,
      )}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <VerdictIcon className={cn("h-3.5 w-3.5", verdict.iconClass)} />
        <span className="font-medium text-emerald-200">本题反馈</span>
        <Badge
          variant={verdict.badgeVariant}
          className={cn("text-[10px]", verdict.badgeClass)}
        >
          {verdict.label}
        </Badge>
      </div>
      {isFallbackTurnEvaluation(evaluation) ? (
        <TurnFeedbackFallbackNotice evaluation={evaluation} />
      ) : (
        <div className="grid gap-2 sm:grid-cols-2">
          <TurnFeedbackList
            tone="positive"
            heading="做得好"
            items={evaluation.strengths}
            emptyText="这题暂未提炼出明确亮点，可以继续保持作答节奏。"
          />
          <TurnFeedbackList
            tone="negative"
            heading="可补齐"
            items={evaluation.weaknesses}
            emptyText={verdict.emptyWeaknessText}
          />
        </div>
      )}
    </div>
  );
}

type TurnFeedbackVerdict = {
  label: string;
  icon: typeof CheckCircle2;
  badgeVariant: "success" | "warn" | "secondary";
  containerClass: string;
  iconClass: string;
  badgeClass: string;
  emptyWeaknessText: string;
};

function getTurnFeedbackVerdict(
  evaluation: PreviousTurnEvaluation,
): TurnFeedbackVerdict {
  if (isFallbackTurnEvaluation(evaluation)) {
    return {
      label: "评估暂不可用",
      icon: AlertTriangle,
      badgeVariant: "secondary",
      containerClass: "border-slate-500/20 bg-slate-500/[0.045]",
      iconClass: "text-slate-300",
      badgeClass: "border-slate-400/20 text-slate-200",
      emptyWeaknessText:
        "评估模型暂时不可用，本轮回答已保存；这次不作为能力短板判断。",
    };
  }
  if (evaluation.passed) {
    return {
      label: "本题通过",
      icon: CheckCircle2,
      badgeVariant: "success",
      containerClass: "border-emerald-500/20 bg-emerald-500/[0.045]",
      iconClass: "text-emerald-300",
      badgeClass: "border-emerald-400/20",
      emptyWeaknessText:
        "这题完成度不错，暂时没有明显短板。下一题继续保持这样的展开力度。",
    };
  }
  if (typeof evaluation.score === "number" && evaluation.score >= 4) {
    return {
      label: "接近通过线",
      icon: Sparkles,
      badgeVariant: "warn",
      containerClass: "border-amber-500/20 bg-amber-500/[0.045]",
      iconClass: "text-amber-300",
      badgeClass: "border-amber-400/20",
      emptyWeaknessText:
        "整体已经接近要求，下一题可以继续补充关键细节，把证据链再压实一点。",
    };
  }
  return {
    label: "可以再补齐",
    icon: Lightbulb,
    badgeVariant: "secondary",
    containerClass: "border-slate-500/20 bg-slate-500/[0.045]",
    iconClass: "text-slate-300",
    badgeClass: "border-slate-400/20 text-slate-200",
    emptyWeaknessText:
      "本题还需要更多信息支撑，下一题优先把背景、动作和结果讲完整。",
  };
}

function isFallbackTurnEvaluation(evaluation: PreviousTurnEvaluation): boolean {
  return Boolean(evaluation.source === "fallback" || evaluation.fallback_reason);
}

function TurnFeedbackFallbackNotice({
  evaluation,
}: {
  evaluation: PreviousTurnEvaluation;
}) {
  const warning = evaluation.system_warnings?.find((item) => item.trim());
  return (
    <div className="rounded-md border border-slate-500/15 bg-background/20 px-3 py-2 leading-relaxed text-slate-300">
      <p>
        本轮回答已保存，但评估模型暂时不可用。这次不会作为能力短板判断，
        可以继续下一题，稍后在报告里查看整体反馈。
      </p>
      {warning ? (
        <p className="mt-1.5 text-[11px] text-slate-400">{warning}</p>
      ) : null}
    </div>
  );
}

const TURN_FEEDBACK_PREVIEW_LIMIT = 2;

function TurnFeedbackList({
  tone,
  heading,
  items,
  emptyText,
}: {
  tone: "positive" | "negative";
  heading: string;
  items: string[];
  emptyText: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasOverflow = items.length > TURN_FEEDBACK_PREVIEW_LIMIT;
  const visibleItems = expanded
    ? items
    : items.slice(0, TURN_FEEDBACK_PREVIEW_LIMIT);
  const toneClass =
    tone === "positive"
      ? {
          panel: "border-emerald-500/15 bg-emerald-500/[0.035]",
          marker: "bg-emerald-300",
          heading: "text-emerald-200",
          item: "border-emerald-500/10 bg-background/20 text-slate-300",
          empty: "border-emerald-500/10 bg-background/10 text-emerald-100/70",
          action: "text-emerald-100/80 hover:text-emerald-100",
        }
      : {
          panel: "border-amber-500/15 bg-amber-500/[0.035]",
          marker: "bg-amber-300",
          heading: "text-amber-200",
          item: "border-amber-500/10 bg-background/20 text-slate-300",
          empty: "border-amber-500/10 bg-background/10 text-amber-100/70",
          action: "text-amber-100/80 hover:text-amber-100",
        };

  return (
    <section className={cn("rounded-md border p-2.5", toneClass.panel)}>
      <div className="mb-2 flex items-center gap-2">
        <span
          aria-hidden="true"
          className={cn("h-1.5 w-1.5 rounded-full", toneClass.marker)}
        />
        <p className={cn("text-[11px] font-semibold", toneClass.heading)}>
          {heading}
        </p>
      </div>
      {items.length > 0 ? (
        <>
          <ul className="space-y-1.5">
            {visibleItems.map((item, index) => (
              <li
                key={`${tone}-${index}-${item.slice(0, 12)}`}
                className={cn(
                  "rounded-md border px-2 py-1.5 leading-relaxed",
                  toneClass.item,
                )}
              >
                {item}
              </li>
            ))}
          </ul>
          {hasOverflow ? (
            <button
              type="button"
              aria-expanded={expanded}
              onClick={() => setExpanded((value) => !value)}
              className={cn(
                "mt-2 inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11px] font-medium transition-colors active:scale-[0.98]",
                toneClass.action,
              )}
            >
              {expanded ? (
                <>
                  <Minimize2 className="h-3 w-3" />
                  收起
                </>
              ) : (
                <>
                  <Maximize2 className="h-3 w-3" />
                  展开全部 {items.length} 条
                </>
              )}
            </button>
          ) : null}
        </>
      ) : (
        <p
          className={cn(
            "rounded-md border px-2 py-1.5 leading-relaxed",
            toneClass.empty,
          )}
        >
          {emptyText}
        </p>
      )}
    </section>
  );
}

function hasDisplayableTurnFeedback(
  evaluation: PreviousTurnEvaluation | null | undefined,
): evaluation is PreviousTurnEvaluation {
  return Boolean(
    evaluation &&
      (isFallbackTurnEvaluation(evaluation) ||
        evaluation.strengths.length > 0 ||
        evaluation.weaknesses.length > 0),
  );
}

function restoredTurnToQaEntry(turn: ResumeHistoryTurn): QaEntry | null {
  if (!turn.question && !turn.answer) return null;
  const isSelfIntro = turn.question_type === "self_intro";
  const turnIdx = typeof turn.turn_idx === "number" ? turn.turn_idx : null;
  return {
    turnIdx: isSelfIntro ? null : turnIdx,
    formalTurnIdx: isSelfIntro ? null : turnIdx,
    displayTurnIdx: isSelfIntro ? null : turnIdx,
    questionType: turn.question_type,
    dimension: turn.dimension ?? undefined,
    question: turn.question ?? "",
    answer: turn.answer ?? "",
    evaluation: resumeTurnEvaluation(turn),
  };
}

function resumeTurnEvaluation(
  turn: ResumeHistoryTurn,
): PreviousTurnEvaluation | null {
  const strengths = listStrings(turn.strengths);
  const weaknesses = listStrings(turn.weaknesses);
  const hasFeedback =
    typeof turn.score === "number" ||
    typeof turn.passed === "boolean" ||
    strengths.length > 0 ||
    weaknesses.length > 0;
  if (!hasFeedback) return null;
  return {
    turn_idx: turn.turn_idx,
    dimension: turn.dimension ?? null,
    score: typeof turn.score === "number" ? turn.score : null,
    passed: Boolean(turn.passed),
    strengths,
    weaknesses,
  };
}

function listStrings(value: string[] | undefined): string[] {
  return Array.isArray(value)
    ? value.filter((item) => typeof item === "string" && item.trim())
    : [];
}

function visibleTurnIdx(entry: QaEntry): number | null {
  if (typeof entry.displayTurnIdx === "number") return entry.displayTurnIdx;
  if (typeof entry.formalTurnIdx === "number") return entry.formalTurnIdx;
  return typeof entry.turnIdx === "number" ? entry.turnIdx : null;
}

function answerInsightFromHistory(history: QaEntry[]): AnswerInsight | null {
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const entry = history[index];
    const answer = entry.answer;
    if (!answer || answer === "已跳过本题") continue;
    const isOpeningTurn = entry.questionType === "self_intro";
    const dimensionId = isOpeningTurn ? null : entry.dimension;
    const dimensionLabel = isOpeningTurn
      ? null
      : entry.dimension
        ? formatDimensionName(entry.dimension)
        : null;
    if (isOpeningTurn || dimensionLabel) {
      return {
        dimensionId,
        dimensionLabel,
        isOpeningTurn,
      };
    }
  }
  return null;
}

function filterRestoredHistoryForCurrentQuestion(
  entries: QaEntry[],
  currentTurnIdxForDisplay: number | null,
): QaEntry[] {
  if (typeof currentTurnIdxForDisplay !== "number") return entries;
  return entries.filter((entry) => {
    const entryTurnIdx = visibleTurnIdx(entry);
    return (
      typeof entryTurnIdx !== "number" ||
      entryTurnIdx < currentTurnIdxForDisplay
    );
  });
}

function sameQaEntry(left: QaEntry, right: QaEntry): boolean {
  return (
    left.turnIdx === right.turnIdx &&
    left.question === right.question &&
    left.answer === right.answer
  );
}

function qaEntryMatchesEvaluation(
  entry: QaEntry,
  evaluation: PreviousTurnEvaluation,
): boolean {
  if (entry.answer === null) return false;
  if (typeof evaluation.turn_idx !== "number") return false;
  if (!evaluation.dimension || !entry.dimension) return false;
  if (evaluation.dimension !== entry.dimension) {
    return false;
  }
  return (
    entry.formalTurnIdx === evaluation.turn_idx ||
    entry.turnIdx === evaluation.turn_idx
  );
}

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

function isFinalFormalTurn({
  question,
  turnIdx,
  maxTurns,
}: {
  question: PollQuestion | null;
  turnIdx: number | null;
  maxTurns: number | null;
}): boolean {
  if (!question || typeof maxTurns !== "number" || maxTurns <= 0) return false;
  if (extractQuestionType(question) === "self_intro") return false;
  const formalTurnIdx = extractFormalTurnIdx(question);
  const currentTurn =
    formalTurnIdx !== null
      ? formalTurnIdx + 1
      : turnIdx !== null
        ? turnIdx + 1
        : 0;
  return currentTurn >= maxTurns;
}

function resumeAnchorLabel(anchor?: ResumeAnchor): string {
  return anchor?.project_name || anchor?.label || "";
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
