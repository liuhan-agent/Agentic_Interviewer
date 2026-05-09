"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Camera,
  CameraOff,
  CheckCircle2,
  Keyboard,
  Loader2,
  Mic,
  MicOff,
  Square,
  Volume2,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

import { LLMSettingsDialog } from "@/components/layout/LLMSettingsDialog";
import { CollapsibleAnswerBubble } from "@/components/interview/CollapsibleAnswerBubble";
import { DigitalHumanStage } from "@/components/interview/DigitalHumanStage";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useFaceCapture } from "@/lib/hooks/useFaceCapture";
import { storeVoiceReportCache } from "@/lib/storage/voiceReportCache";
import {
  VoiceClient,
  type VoiceServerQuestion,
} from "@/lib/voice/client";

type QaEntry = {
  turnIdx: number;
  dimension?: string;
  question: string;
  answer: string | null;
};

type Phase =
  | "connecting"
  | "awaiting_question"
  | "playing_question"
  | "ready_to_record"
  | "recording"
  | "uploading"
  | "completed"
  | "error";

const MAX_RECORD_SECONDS = 180;
const RECORD_WARNING_SECONDS = 150;

export function VoiceRoom({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("connecting");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [reauthRequired, setReauthRequired] = useState(false);
  const [recordSecs, setRecordSecs] = useState(0);

  useEffect(() => {
    if (phase !== "recording") {
      setRecordSecs(0);
      return;
    }
    const id = setInterval(() => setRecordSecs((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [phase]);
  const [history, setHistory] = useState<QaEntry[]>([]);
  const [pendingQuestion, setPendingQuestion] =
    useState<VoiceServerQuestion | null>(null);

  const {
    cameraOn,
    videoRef,
    toggleCamera,
    startCapture: startFaceCapture,
    stopCapture: stopFaceCapture,
    cameraError,
    analysisWarning,
  } = useFaceCapture();

  const clientRef = useRef<VoiceClient | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioElRef = useRef<HTMLAudioElement | null>(null);
  const pendingAudioUrlRef = useRef<string | null>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const routerPushTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectingRef = useRef(false);

  useEffect(() => {
    // Pre-request microphone permission to avoid delay when answering the first question
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then((stream) => {
        // Keep it muted until actual recording starts
        stream.getAudioTracks().forEach((t) => t.enabled = false);
        streamRef.current = stream;
      })
      .catch((e) => {
        console.warn("Pre-request microphone permission failed", e);
        setErrorMsg("麦克风权限暂未开启。你可以稍后重新授权，或切换到文本作答。");
      });
  }, []);

  useEffect(() => {
    return () => {
      if (routerPushTimeoutRef.current) {
        clearTimeout(routerPushTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [history.length, phase]);

  // Create the audio element once — Safari is picky about reusing
  // dynamically-created <audio> nodes across route transitions.
  useEffect(() => {
    const el = new Audio();
    el.preload = "auto";
    const handleEnded = () => {
      // Once playback finishes, hand control back to the user so the
      // next record cycle can start.
      setPhase((prev) => (prev === "playing_question" ? "ready_to_record" : prev));
      if (pendingAudioUrlRef.current) {
        URL.revokeObjectURL(pendingAudioUrlRef.current);
        pendingAudioUrlRef.current = null;
      }
    };
    el.addEventListener("ended", handleEnded);
    audioElRef.current = el;
    return () => {
      el.removeEventListener("ended", handleEnded);
      el.pause();
      el.src = "";
      if (pendingAudioUrlRef.current) {
        URL.revokeObjectURL(pendingAudioUrlRef.current);
        pendingAudioUrlRef.current = null;
      }
    };
  }, []);

  // Wire the WebSocket client + its callbacks. The refs below keep
  // the latest pendingQuestion visible to the ``onAudio`` callback
  // without adding it to the effect deps (which would tear down the
  // socket on every question).
  const playAudioBlob = useCallback((blob: Blob) => {
    if (!audioElRef.current) return;
    if (pendingAudioUrlRef.current) {
      URL.revokeObjectURL(pendingAudioUrlRef.current);
    }
    const url = URL.createObjectURL(blob);
    pendingAudioUrlRef.current = url;
    audioElRef.current.src = url;
    audioElRef.current.play().catch((e) => {
      // Autoplay blocked: fall through to ready_to_record so the user
      // can record an answer based on the text question alone.
      console.warn("TTS autoplay blocked", e);
      setPhase((prev) =>
        prev === "playing_question" ? "ready_to_record" : prev,
      );
    });
  }, []);

  const openWs = useCallback(() => {
    if (clientRef.current) return;
    const client = new VoiceClient(sessionId, {
      onOpen: () => setPhase("awaiting_question"),
      onQuestion: (q) => {
        setReauthRequired(false);
        setPendingQuestion(q);
        setHistory((prev) => [
          ...prev,
          {
            turnIdx: q.turn_idx,
            dimension: q.dimension,
            question: q.content,
            answer: null,
          },
        ]);
        setPhase("playing_question");
      },
      onAudio: (blob) => {
        playAudioBlob(blob);
      },
      onTtsEnd: () => {
        if (!pendingAudioUrlRef.current) {
          setPhase((prev) =>
            prev === "playing_question" ? "ready_to_record" : prev,
          );
        }
      },
      onTranscript: (t) => {
        setHistory((prev) => {
          if (prev.length === 0) return prev;
          const next = prev.slice();
          const last = next[next.length - 1];
          if (last.answer === null) {
            next[next.length - 1] = { ...last, answer: t.content };
          }
          return next;
        });
      },
      onError: (e) => {
        // Empty transcription is recoverable: tell the user to try
        // again instead of tearing the interview down.
        if (e.error === "empty_transcription") {
          setErrorMsg(e.message ?? "无法转录该段语音。");
          setPhase("ready_to_record");
          return;
        }
        if (e.error === "reauth_required") {
          setReauthRequired(true);
          setErrorMsg(
            e.message ??
              "需要重新授权模型配置。请打开模型设置更新 Key，然后重新连接继续语音面试。",
          );
          setPhase("error");
          return;
        }
        setErrorMsg(e.message ?? e.error);
        setPhase("error");
      },
      onFinal: (f) => {
        setPhase("completed");
        storeVoiceReportCache(sessionId, f.report);
        routerPushTimeoutRef.current = setTimeout(() => {
          router.push(`/interview/${sessionId}/report`);
        }, 600);
      },
      onClose: () => {
        if (reconnectingRef.current) {
          reconnectingRef.current = false;
          return;
        }
        // Only treat close as an error if we were mid-interview.
        setPhase((prev) =>
          prev === "completed" || prev === "error" ? prev : "error",
        );
        setErrorMsg((prev) => prev ?? "WebSocket 连接意外关闭。");
      },
      onSocketError: () => {
        setErrorMsg((prev) => prev ?? "WebSocket 传输错误。");
        setPhase("error");
      },
    });
    client.connect();
    clientRef.current = client;
  }, [sessionId, playAudioBlob, router]);

  const safeReconnect = useCallback(() => {
    reconnectingRef.current = true;
    clientRef.current?.close();
    clientRef.current = null;
    setErrorMsg(null);
    setReauthRequired(false);
    setPhase("connecting");
    openWs();
  }, [openWs]);

  useEffect(() => {
    openWs();
    return () => {
      clientRef.current?.close();
      clientRef.current = null;
      releaseMicStream();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function releaseMicStream() {
    recorderRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }

  const startRecording = useCallback(async () => {
    if (!clientRef.current) return;
    setErrorMsg(null);
    setReauthRequired(false);
    try {
      let stream = streamRef.current;
      if (!stream) {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        streamRef.current = stream;
      } else {
        stream.getAudioTracks().forEach((t) => t.enabled = true);
      }
      // Prefer webm/opus because backend ASR falls back to ``webm``
      // for any unknown MIME type; on Safari where webm is not
      // available, MediaRecorder will ignore the hint and pick mp4.
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : MediaRecorder.isTypeSupported("audio/webm")
          ? "audio/webm"
          : "";
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      recorderRef.current = recorder;

      const chunks: Blob[] = [];
      recorder.addEventListener("dataavailable", (ev) => {
        if (ev.data.size > 0) chunks.push(ev.data);
      });
      recorder.addEventListener("stop", async () => {
        recorderRef.current = null;
        streamRef.current?.getAudioTracks().forEach((t) => t.enabled = false);
        const videoSigs = stopFaceCapture();
        const full = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        const buf = await full.arrayBuffer();
        const turnIdx = pendingQuestion?.turn_idx;
        if (turnIdx === undefined) {
          setErrorMsg("Question state is not ready. Please refresh and try again.");
          setPhase("ready_to_record");
          return;
        }
        clientRef.current?.sendAudio(buf);
        clientRef.current?.sendStop(
          turnIdx,
          videoSigs as Record<string, unknown> | null,
        );
        setPhase("uploading");
        // After we've uploaded, the server will either produce the
        // next question + TTS frames or close the socket at the end.
        // ``onQuestion`` flips us back to ``playing_question``;
        // ``onFinal`` routes to the report.
      });

      recorder.start();
      setPhase("recording");
      startFaceCapture();
    } catch (e) {
      setErrorMsg(
        e instanceof Error ? e.message : "麦克风权限被拒绝。",
      );
      setPhase("ready_to_record");
    }
  }, [pendingQuestion, startFaceCapture, stopFaceCapture]);

  const stopRecording = useCallback(() => {
    if (!recorderRef.current) return;
    stopFaceCapture();
    if (recorderRef.current.state === "recording") {
      recorderRef.current.stop();
    }
  }, [stopFaceCapture]);

  useEffect(() => {
    if (phase === "recording" && recordSecs >= MAX_RECORD_SECONDS) {
      stopRecording();
    }
  }, [phase, recordSecs, stopRecording]);

  useEffect(() => {
    if (cameraError) setErrorMsg(cameraError);
  }, [cameraError]);

  const phaseRef = useRef(phase);
  phaseRef.current = phase;

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target !== document.body) return;
      if (e.code === "Space") {
        e.preventDefault();
        if (phaseRef.current === "ready_to_record" && !recorderRef.current) {
          startRecording();
        } else if (phaseRef.current === "recording") {
          stopRecording();
        }
      } else if (e.code === "KeyC" && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        toggleCamera();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [toggleCamera, startRecording, stopRecording]);

  return (
    <div className="space-y-6">
      <StatusStrip
        phase={phase}
        sessionId={sessionId}
        turnIdx={pendingQuestion?.turn_idx ?? null}
        maxTurns={pendingQuestion?.max_turns ?? null}
      />

      {reauthRequired && <VoiceReauthRequiredBanner />}

      {errorMsg && phase !== "completed" && (
        <motion.div
          initial={{ opacity: 0, y: -6 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span className="flex-1">{errorMsg}</span>
          {phase === "error" && (
            <Button
              variant="outline"
              size="sm"
              className="shrink-0 gap-1.5 text-xs"
              onClick={() => {
                safeReconnect();
              }}
            >
              <ArrowRight className="h-3 w-3" />
              重新连接
            </Button>
          )}
        </motion.div>
      )}

      <DigitalHumanStage
        phase={phase}
        question={pendingQuestion?.content ?? null}
        cameraOn={cameraOn}
        recordSecs={recordSecs}
        audioElementRef={audioElRef}
      />

      <Card>
        <CardHeader className="flex flex-row items-center justify-between border-b bg-card/50">
          <div className="flex items-center gap-2">
            <Volume2 className="h-4 w-4 text-emerald-400" />
            <CardTitle className="text-base">语音记录</CardTitle>
          </div>
          <Badge variant="outline" className="font-mono text-xs">
            {history.length} 轮
          </Badge>
        </CardHeader>
        <CardContent className="space-y-4 pt-6">
          {history.length === 0 && phase !== "completed" && (
            <div className="space-y-3">
              <Skeleton className="h-4 w-40" />
              <Skeleton className="h-5 w-2/3" />
            </div>
          )}

          <AnimatePresence mode="popLayout">
            {history.map((t, idx) => (
              <motion.div
                key={`turn-${idx}`}
                initial={{ opacity: 0, y: 12 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
              >
                <Bubble entry={t} />
              </motion.div>
            ))}
          </AnimatePresence>

          <div ref={transcriptEndRef} />
        </CardContent>
      </Card>

      <RecorderControls
        phase={phase}
        onStart={startRecording}
        onStop={stopRecording}
        recordSecs={recordSecs}
      />

      {cameraOn && (
        <Card className="overflow-hidden">
          <CardContent className="space-y-3 p-3">
            <div className="grid grid-cols-2 gap-3">
            <div className="relative aspect-video overflow-hidden rounded-lg bg-black">
              <video
                ref={videoRef as any}
                autoPlay
                playsInline
                muted
                className="h-full w-full object-cover mirror"
                style={{ transform: "scaleX(-1)" }}
              />
              <span className="absolute bottom-1.5 left-1.5 rounded bg-black/50 px-1.5 py-0.5 text-[10px] text-white">
                你
              </span>
            </div>
            <DigitalHumanStage
              compact
              phase={phase}
              question={pendingQuestion?.content ?? null}
              cameraOn={cameraOn}
              recordSecs={recordSecs}
              audioElementRef={audioElRef}
            />
            </div>
            {analysisWarning && (
              <p className="rounded-md border border-amber-500/30 bg-amber-500/[0.04] px-3 py-2 text-xs text-amber-200">
                {analysisWarning}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <div className="flex items-center gap-2">
          <Button
            variant={cameraOn ? "default" : "outline"}
            size="sm"
            className="h-8 gap-1.5"
            onClick={toggleCamera}
          >
            {cameraOn ? (
              <Camera className="h-3.5 w-3.5" />
            ) : (
              <CameraOff className="h-3.5 w-3.5" />
            )}
            {cameraOn ? "关闭摄像头" : "开启摄像头"}
            <span className="sr-only">（快捷键：C）</span>
          </Button>
          <CardDescription className="text-[11px]">
            {cameraOn
              ? "仅在本地提取专注度/自信度指标，不上传视频画面"
              : "语音面试模式，关闭摄像头不影响作答"}
          </CardDescription>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="gap-1.5"
          onClick={() => {
            if (
              phase === "recording" &&
              !window.confirm("正在录音中，切换将丢失当前录音，确定切换？")
            ) {
              return;
            }
            router.push(`/interview/${sessionId}`);
          }}
        >
          <Keyboard className="h-3.5 w-3.5" />
          切换到文本
        </Button>
      </div>
    </div>
  );
}

function StatusStrip({
  phase,
  sessionId,
  turnIdx,
  maxTurns,
}: {
  phase: Phase;
  sessionId: string;
  turnIdx: number | null;
  maxTurns: number | null;
}) {
  const label = phaseLabel(phase);
  const color =
    phase === "error"
      ? "text-destructive"
      : phase === "completed"
        ? "text-emerald-400"
        : phase === "recording"
          ? "text-amber-400"
          : "text-muted-foreground";
  const currentTurn = turnIdx !== null ? turnIdx + 1 : 0;
  const progressPercent =
    typeof maxTurns === "number" && maxTurns > 0
      ? Math.min(100, Math.max(0, (currentTurn / maxTurns) * 100))
      : 0;
  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-wrap items-center gap-3 rounded-xl border bg-card/80 backdrop-blur-sm p-3 text-xs"
    >
      <div className="flex items-center gap-1.5 font-mono">
        <Mic className={color + " h-3.5 w-3.5"} />
        <span className="uppercase tracking-wider">{label}</span>
      </div>
      <span className="text-muted-foreground/40">·</span>
      <span className="font-mono text-muted-foreground">
        会话{" "}
        <span className="text-foreground">{truncateId(sessionId)}</span>
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
            {currentTurn}/{maxTurns}
          </span>
        </span>
      )}
    </motion.div>
  );
}

function VoiceReauthRequiredBanner() {
  return (
    <Card className="border-amber-500/40 bg-amber-500/[0.04]">
      <CardContent className="flex flex-col gap-3 pt-5 text-sm sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="font-medium text-amber-300">需要重新授权模型配置</p>
          <p className="text-muted-foreground">
            当前语音会话恢复后缺少本轮 BYOK Key。更新模型设置后，重新连接即可继续。
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

function RecorderControls({
  phase,
  onStart,
  onStop,
  recordSecs,
}: {
  phase: Phase;
  onStart: () => void;
  onStop: () => void;
  recordSecs: number;
}) {
  const disabled =
    phase === "connecting" ||
    phase === "awaiting_question" ||
    phase === "playing_question" ||
    phase === "uploading" ||
    phase === "completed" ||
    phase === "error";

  if (phase === "recording") {
    return (
      <Card className="border-amber-500/30 bg-amber-500/[0.03]">
        <CardContent className="flex flex-col items-center gap-3 pt-6">
          <div className="flex items-center gap-2 text-sm text-amber-400">
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inset-0 animate-ping rounded-full bg-amber-400/60" />
              <span className="relative inline-block h-2.5 w-2.5 rounded-full bg-amber-400" />
            </span>
            <span className="font-mono uppercase tracking-wider">录音中</span>
          </div>
          <div className="flex items-center gap-3">
            <span className="font-mono text-lg tabular-nums text-muted-foreground">
              {String(Math.floor(recordSecs / 60)).padStart(2, "0")}:
              {String(recordSecs % 60).padStart(2, "0")}
            </span>
            <Button
              size="lg"
              onClick={onStop}
              className="gap-2 bg-amber-600 hover:bg-amber-500 text-white"
            >
              <Square className="h-4 w-4" />
              停止并发送
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            每轮建议控制在 3 分钟内；停止后服务器将进行转录。
          </p>
          {recordSecs >= RECORD_WARNING_SECONDS && (
            <p className="text-xs text-amber-300">
              接近单轮录音上限，系统会在 3 分钟时自动发送。
            </p>
          )}
        </CardContent>
      </Card>
    );
  }

  if (phase === "completed") {
    return (
      <Card>
        <CardContent className="flex items-center gap-3 pt-6 text-sm text-muted-foreground">
          <CheckCircle2 className="h-4 w-4 text-emerald-400" />
          面试完成，正在跳转到报告…
          <Loader2 className="h-4 w-4 animate-spin" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className={disabled ? "opacity-60" : ""}>
      <CardContent className="flex flex-col items-center gap-3 pt-6">
        <Button
          size="lg"
          disabled={disabled}
          onClick={onStart}
          className="gap-2 bg-emerald-600 hover:bg-emerald-500 text-white"
        >
          {disabled ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Mic className="h-4 w-4" />
          )}
          {phase === "playing_question"
            ? "播放问题中…"
            : phase === "uploading"
              ? "转录中…"
              : phase === "awaiting_question"
                ? "等待第一个问题…"
                : phase === "ready_to_record"
                  ? "开始录音"
                  : "连接中…"}
          {!disabled && <ArrowRight className="h-4 w-4" />}
        </Button>
        <p className="text-xs text-muted-foreground">
          点击开始说出你的回答；再次点击停止并发送。
        </p>
      </CardContent>
    </Card>
  );
}

function Bubble({ entry }: { entry: QaEntry }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs font-mono text-muted-foreground">
        <span className="flex h-5 w-5 items-center justify-center rounded bg-secondary text-[10px] font-bold">
          {entry.turnIdx + 1}
        </span>
        {entry.dimension && (
          <Badge variant="outline" className="font-mono text-[10px]">
            {entry.dimension}
          </Badge>
        )}
        {entry.answer === null ? (
          <Badge className="gap-1 bg-amber-500/10 text-amber-400 border-amber-500/20">
            等待你的回答
          </Badge>
        ) : (
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
        </div>
        {entry.question}
      </div>

      {entry.answer !== null && (
        <CollapsibleAnswerBubble
          text={entry.answer}
          className="ml-6"
          label="你（转录）"
        />
      )}
    </div>
  );
}

function phaseLabel(p: Phase): string {
  switch (p) {
    case "connecting":
      return "连接中";
    case "awaiting_question":
      return "等待问题";
    case "playing_question":
      return "播放问题";
    case "ready_to_record":
      return "就绪";
    case "recording":
      return "录音中";
    case "uploading":
      return "转录中";
    case "completed":
      return "已完成";
    case "error":
      return "出错";
  }
}

function truncateId(v: string): string {
  if (v.length <= 12) return v;
  return `${v.slice(0, 4)}…${v.slice(-4)}`;
}
