"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Loader2,
  Mic,
  Square,
  Undo2,
} from "lucide-react";

import { LLMSettingsDialog } from "@/components/layout/LLMSettingsDialog";
import { Button } from "@/components/ui/button";
import { useToast } from "@/lib/hooks/useToast";
import { cn } from "@/lib/utils";
import { VoiceClient } from "@/lib/voice/client";

type VoiceAnswerPhase =
  | "connecting"
  | "ready"
  | "recording"
  | "uploading"
  | "reviewing"
  | "error";

const MAX_RECORD_SECONDS = 180;
const RECORD_WARNING_SECONDS = 150;

export function VoiceAnswerPanel({
  sessionId,
  turnIdx,
  disabled,
  submitting,
  maxLength,
  onTranscript,
  canUndoTranscript,
  onUndoTranscript,
}: {
  sessionId: string;
  turnIdx: number | null;
  disabled: boolean;
  submitting: boolean;
  maxLength: number;
  onTranscript: (text: string) => void;
  canUndoTranscript: boolean;
  onUndoTranscript: () => void;
}) {
  const { toast } = useToast();
  const [phase, setPhase] = useState<VoiceAnswerPhase>("connecting");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [noticeMsg, setNoticeMsg] = useState<string | null>(null);
  const [reauthRequired, setReauthRequired] = useState(false);
  const [recordSecs, setRecordSecs] = useState(0);
  const [lastTranscript, setLastTranscript] = useState("");
  const [draftTurnIdx, setDraftTurnIdx] = useState<number | null>(null);

  const clientRef = useRef<VoiceClient | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const connectionRunRef = useRef(0);

  useEffect(() => {
    if (phase !== "recording") {
      setRecordSecs(0);
      return;
    }
    const id = window.setInterval(() => setRecordSecs((value) => value + 1), 1000);
    return () => window.clearInterval(id);
  }, [phase]);

  useEffect(() => {
    const runId = connectionRunRef.current + 1;
    connectionRunRef.current = runId;
    let client: VoiceClient | null = null;
    const connectTimer = window.setTimeout(() => {
      if (!isCurrentConnection(runId)) return;
      client = new VoiceClient(
        sessionId,
        {
          onOpen: () => {
            if (!isCurrentConnection(runId)) return;
            setPhase("ready");
          },
          onQuestion: () => undefined,
          onAudio: () => undefined,
          onTtsEnd: () => undefined,
          onTranscript: () => undefined,
          onFinal: () => undefined,
          onDraftTranscript: (draft) => {
            if (!isCurrentConnection(runId)) return;
            setReauthRequired(false);
            onTranscript(draft.content.slice(0, maxLength));
            setLastTranscript(draft.content.trim());
            setDraftTurnIdx(draft.turn_idx);
            setErrorMsg(null);
            setNoticeMsg(null);
            setPhase("reviewing");
            toast({ title: "已追加到草稿，可继续编辑" });
          },
          onError: (event) => {
            if (!isCurrentConnection(runId)) return;
            if (event.error === "empty_transcription") {
              setErrorMsg(null);
              setNoticeMsg("这段没有识别到文字，可以再录一次。");
              setPhase("ready");
              return;
            }
            if (event.error === "reauth_required") {
              setReauthRequired(true);
              setErrorMsg(
                event.message ??
                  "语音识别需要重新授权模型配置，请更新 Key 后再试。",
              );
              setPhase("error");
              return;
            }
            setNoticeMsg(null);
            setErrorMsg(event.message ?? event.error);
            setPhase("error");
          },
          onClose: () => {
            if (!isCurrentConnection(runId)) return;
            setPhase((current) =>
              current === "reviewing" || current === "ready" ? current : "error",
            );
            setErrorMsg((current) => current ?? "语音识别连接已关闭，请重新打开语音模式。");
          },
          onSocketError: () => {
            if (!isCurrentConnection(runId)) return;
            setErrorMsg((current) => current ?? "语音识别连接出现网络错误。");
            setPhase("error");
          },
        },
        { mode: "asr_only" },
      );
      client.connect();
      clientRef.current = client;
    }, 0);
    return () => {
      connectionRunRef.current += 1;
      window.clearTimeout(connectTimer);
      client?.close();
      if (clientRef.current === client) {
        clientRef.current = null;
      }
      releaseMicStream();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  function isCurrentConnection(runId: number): boolean {
    return connectionRunRef.current === runId;
  }

  useEffect(() => {
    setLastTranscript("");
    setDraftTurnIdx(null);
    setErrorMsg(null);
    setNoticeMsg(null);
    setPhase((current) =>
      current === "reviewing" || current === "uploading" ? "ready" : current,
    );
  }, [turnIdx]);

  const stopRecording = useCallback(() => {
    if (!recorderRef.current) return;
    if (recorderRef.current.state === "recording") {
      recorderRef.current.stop();
    }
  }, []);

  useEffect(() => {
    if (phase === "recording" && recordSecs >= MAX_RECORD_SECONDS) {
      stopRecording();
    }
  }, [phase, recordSecs, stopRecording]);

  function releaseMicStream() {
    recorderRef.current = null;
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  async function startRecording() {
    if (disabled || submitting || !clientRef.current) return;
    if (turnIdx === null) {
      setErrorMsg("当前题目状态还没准备好，请稍等一下再录音。");
      setNoticeMsg(null);
      return;
    }
    setErrorMsg(null);
    setNoticeMsg(null);
    setReauthRequired(false);
    try {
      let stream = streamRef.current;
      if (!stream) {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        streamRef.current = stream;
      } else {
        stream.getAudioTracks().forEach((track) => {
          track.enabled = true;
        });
      }

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
      recorder.addEventListener("dataavailable", (event) => {
        if (event.data.size > 0) chunks.push(event.data);
      });
      recorder.addEventListener("stop", () => {
        void sendRecording(chunks, recorder);
      });

      recorder.start();
      setPhase("recording");
    } catch (error) {
      setErrorMsg(error instanceof Error ? error.message : "麦克风权限被拒绝。");
      setNoticeMsg(null);
      setPhase("ready");
    }
  }

  async function sendRecording(chunks: Blob[], recorder: MediaRecorder) {
    recorderRef.current = null;
    streamRef.current?.getAudioTracks().forEach((track) => {
      track.enabled = false;
    });
    if (turnIdx === null) {
      setErrorMsg("当前题目状态还没准备好，请稍等一下再录音。");
      setNoticeMsg(null);
      setPhase("ready");
      return;
    }
    try {
      const full = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
      const normalized = await normalizeRecordingForASR(full);
      const buf = await normalized.blob.arrayBuffer();
      const recordingMimeType = normalized.mimeType || full.type || recorder.mimeType;
      clientRef.current?.sendAudio(buf);
      clientRef.current?.sendStop(turnIdx, null, recordingMimeType);
      setPhase("uploading");
    } catch (error) {
      setErrorMsg(error instanceof Error ? error.message : "录音发送失败，请重试。");
      setNoticeMsg(null);
      setPhase("ready");
    }
  }

  function handleRerecordTranscript() {
    setLastTranscript("");
    setDraftTurnIdx(null);
    setErrorMsg(null);
    setNoticeMsg(null);
    setPhase("ready");
  }

  const canRecord =
    !disabled &&
    !submitting &&
    turnIdx !== null &&
    (phase === "ready" || phase === "reviewing");

  return (
    <div className="space-y-3 rounded-lg border border-emerald-500/20 bg-emerald-500/[0.03] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-medium text-emerald-200">语音回答</p>
        <VoicePhaseBadge phase={phase} recordSecs={recordSecs} />
      </div>

      {reauthRequired && (
        <div className="flex flex-col gap-3 rounded-md border border-amber-500/35 bg-amber-500/[0.05] p-3 text-sm sm:flex-row sm:items-center sm:justify-between">
          <span className="text-amber-200">
            语音识别需要重新授权模型配置。
          </span>
          <LLMSettingsDialog>
            <Button type="button" variant="outline" size="sm">
              打开模型设置
            </Button>
          </LLMSettingsDialog>
        </div>
      )}

      {errorMsg && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/35 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{errorMsg}</span>
        </div>
      )}

      {noticeMsg && (
        <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/[0.06] p-3 text-sm text-amber-200">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>{noticeMsg}</span>
        </div>
      )}

      {phase === "recording" ? (
        <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2 text-sm text-amber-300">
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inset-0 animate-ping rounded-full bg-amber-400/60" />
              <span className="relative inline-block h-2.5 w-2.5 rounded-full bg-amber-400" />
            </span>
            <span className="font-mono tabular-nums">
              {formatRecordTime(recordSecs)}
            </span>
          </div>
          <Button
            type="button"
            onClick={stopRecording}
            className="gap-2 bg-amber-600 text-white hover:bg-amber-500"
          >
            <Square className="h-4 w-4" />
            停止并转写
          </Button>
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            onClick={() => void startRecording()}
            disabled={!canRecord}
            className="gap-2 bg-emerald-600 text-white hover:bg-emerald-500"
          >
            {phase === "connecting" || phase === "uploading" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Mic className="h-4 w-4" />
            )}
            {phase === "uploading"
              ? "转写中…"
              : "开始语音回答"}
          </Button>
          {canUndoTranscript && (
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                onUndoTranscript();
                handleRerecordTranscript();
              }}
              disabled={submitting || phase === "uploading"}
              className="gap-2"
            >
              <Undo2 className="h-4 w-4" />
              撤回上次语音
            </Button>
          )}
        </div>
      )}

      {recordSecs >= RECORD_WARNING_SECONDS && phase === "recording" && (
        <p className="text-xs text-amber-300">
          接近单轮录音上限，系统会在 3 分钟时自动停止并转写。
        </p>
      )}

      {lastTranscript && (
        <div className="rounded-md border border-emerald-500/15 bg-background/40 p-3 text-xs text-muted-foreground">
          <span>已追加到草稿，可继续编辑。</span>
        </div>
      )}
    </div>
  );
}

function VoicePhaseBadge({
  phase,
  recordSecs,
}: {
  phase: VoiceAnswerPhase;
  recordSecs: number;
}) {
  const label =
    phase === "connecting"
      ? "连接中"
      : phase === "recording"
        ? `录音中 ${formatRecordTime(recordSecs)}`
        : phase === "uploading"
          ? "转写中"
          : phase === "reviewing"
            ? "待确认"
            : phase === "error"
              ? "需处理"
              : "就绪";
  return (
    <span
      className={cn(
        "rounded-md border px-2.5 py-1 text-xs font-medium",
        phase === "error"
          ? "border-destructive/35 text-destructive"
          : phase === "recording"
            ? "border-amber-500/35 text-amber-300"
            : "border-emerald-500/25 text-emerald-300",
      )}
    >
      {label}
    </span>
  );
}

function formatRecordTime(seconds: number): string {
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(
    seconds % 60,
  ).padStart(2, "0")}`;
}

async function normalizeRecordingForASR(
  blob: Blob,
): Promise<{ blob: Blob; mimeType: string }> {
  if (typeof window === "undefined") {
    return { blob, mimeType: blob.type || "audio/webm" };
  }
  const AudioContextCtor =
    window.AudioContext ||
    (window as typeof window & { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext;
  if (!AudioContextCtor) {
    return { blob, mimeType: blob.type || "audio/webm" };
  }
  let context: AudioContext | null = null;
  try {
    context = new AudioContextCtor({ sampleRate: 16000 });
    const decoded = await context.decodeAudioData(await blob.arrayBuffer());
    const wav = encodeWav(decoded, 16000);
    return { blob: new Blob([wav], { type: "audio/wav" }), mimeType: "audio/wav" };
  } catch (error) {
    console.warn("Audio normalization failed; sending original recording", error);
    return { blob, mimeType: blob.type || "audio/webm" };
  } finally {
    await context?.close().catch(() => undefined);
  }
}

function encodeWav(buffer: AudioBuffer, sampleRate: number): ArrayBuffer {
  const samples = downmixToMono(buffer, sampleRate);
  const out = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(out);

  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeAscii(view, 36, "data");
  view.setUint32(40, samples.length * 2, true);

  let offset = 44;
  for (const sample of samples) {
    const clamped = Math.max(-1, Math.min(1, sample));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
    offset += 2;
  }
  return out;
}

function downmixToMono(buffer: AudioBuffer, targetSampleRate: number): Float32Array {
  const sourceRate = buffer.sampleRate;
  const outputLength = Math.max(1, Math.round((buffer.duration || 0) * targetSampleRate));
  const output = new Float32Array(outputLength);
  const channels = Math.max(1, buffer.numberOfChannels);

  for (let i = 0; i < outputLength; i += 1) {
    const sourceIndex = Math.min(
      buffer.length - 1,
      Math.floor((i * sourceRate) / targetSampleRate),
    );
    let sum = 0;
    for (let channel = 0; channel < channels; channel += 1) {
      sum += buffer.getChannelData(channel)[sourceIndex] ?? 0;
    }
    output[i] = sum / channels;
  }
  return output;
}

function writeAscii(view: DataView, offset: number, text: string): void {
  for (let i = 0; i < text.length; i += 1) {
    view.setUint8(offset + i, text.charCodeAt(i));
  }
}
