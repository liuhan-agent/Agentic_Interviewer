/**
 * WebSocket client for ``/ws/voice/{session_id}``.
 *
 * Protocol (mirrors ``backend/app/api/v1/ws_voice.py`` top-of-file):
 *
 *   client → server
 *     - binary frame  : audio bytes appended to the server buffer
 *     - text  {"type":"stop"}     → end-of-utterance; server transcribes
 *                                   and returns an editable draft
 *     - text  {"type":"submit_transcript"} → submit the reviewed answer
 *     - text  {"type":"cancel"}   → ask the server to tear the session down
 *
 *   server → client
 *     - text  {"type":"question", "turn_idx":N, "content":"...", "dimension":"..."}
 *     - binary frame × N         → TTS audio chunks (mp3 from OpenAI TTS)
 *     - text  {"type":"draft_transcript", "turn_idx":N, "content":"..."}
 *     - text  {"type":"transcript", "content":"..."}
 *     - text  {"type":"final_report", "report":{...}}
 *     - text  {"type":"error", "error":"empty_transcription", "message":"..."}
 *
 * Note: the backend does NOT send an explicit "TTS end" frame. We use
 * "the next text frame arrives" as the end marker, flush the byte
 * buffer into a Blob, and hand it off to the ``onAudio`` callback for
 * playback.
 */

import type { FinalReport } from "@/lib/api/types";
import { createVoiceTicket } from "@/lib/api/interview";
import { apiUrl } from "@/lib/config";
import { buildLLMPayload } from "@/lib/llm-config";

export type VoiceServerQuestion = {
  type: "question";
  turn_idx: number;
  max_turns?: number | null;
  content: string;
  dimension?: string;
};

export type VoiceServerTranscript = {
  type: "transcript";
  content: string;
};

export type VoiceServerDraftTranscript = {
  type: "draft_transcript";
  turn_idx: number;
  content: string;
};

export type VoiceServerFinal = {
  type: "final_report";
  report: FinalReport | null;
};

export type VoiceServerTtsEnd = {
  type: "tts_end";
  turn_idx: number;
};

export type VoiceServerError = {
  type: "error";
  error: string;
  message?: string;
};

export type VoiceServerEvent =
  | VoiceServerQuestion
  | VoiceServerDraftTranscript
  | VoiceServerTranscript
  | VoiceServerFinal
  | VoiceServerTtsEnd
  | VoiceServerError;

export type VoiceClientMode = "voice" | "asr_only";

export interface VoiceClientOptions {
  mode?: VoiceClientMode;
}

export interface VoiceClientCallbacks {
  onQuestion(q: VoiceServerQuestion): void;
  onDraftTranscript(t: VoiceServerDraftTranscript): void;
  onTranscript(t: VoiceServerTranscript): void;
  onFinal(r: VoiceServerFinal): void;
  onError(e: VoiceServerError): void;
  /** Fires whenever a TTS stream has finished collecting bytes. */
  onAudio(blob: Blob): void;
  onTtsEnd?(): void;
  onOpen?(): void;
  onClose?(ev: CloseEvent): void;
  onSocketError?(ev: Event): void;
}

function toWsUrl(path: string): string {
  // ``apiUrl`` returns either "/..." (same-origin, goes through
  // Next.js ``rewrites``) or "http(s)://host/...". We need the ws(s)
  // equivalent in both cases.
  const httpUrl = apiUrl(path);
  if (httpUrl.startsWith("http://") || httpUrl.startsWith("https://")) {
    return httpUrl.replace(/^http/, "ws");
  }
  if (typeof window === "undefined") return httpUrl;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${httpUrl}`;
}

export class VoiceClient {
  private ws: WebSocket | null = null;
  // The TTS bytes for the current question arrive as a run of binary
  // frames followed by the next text frame, so we keep a mutable
  // buffer and flush it whenever we see a text frame.
  private audioChunks: ArrayBuffer[] = [];
  private pendingBlobReads: Promise<void>[] = [];

  constructor(
    private readonly sessionId: string,
    private readonly cb: VoiceClientCallbacks,
    private readonly options: VoiceClientOptions = {},
  ) {}

  connect(): void {
    if (this.ws) return;
    const url = toWsUrl(`/ws/voice/${encodeURIComponent(this.sessionId)}`);
    const ws = new WebSocket(url);
    ws.binaryType = "arraybuffer";
    this.ws = ws;

    ws.addEventListener("open", () => {
      void createVoiceTicket(this.sessionId)
        .then(({ ticket }) => {
          if (ws.readyState !== WebSocket.OPEN) return;
          const auth: Record<string, unknown> = {
            type: "auth",
                ticket: ticket,
          };
          if (this.options.mode) auth.mode = this.options.mode;
          const llmConfig = buildLLMPayload();
          if (llmConfig) auth.llm_config = llmConfig;
          ws.send(JSON.stringify(auth));
          this.cb.onOpen?.();
        })
        .catch((err) => {
          const message =
            err instanceof Error ? err.message : "Failed to create voice ticket.";
          this.cb.onError({
            type: "error",
            error: "voice_ticket_failed",
            message,
          });
          ws.close();
        });
    });

    ws.addEventListener("message", (ev) => {
      void this.handleMessage(ev);
    });

    ws.addEventListener("close", (ev) => {
      void this.handleClose(ev);
    });

    ws.addEventListener("error", (ev) => {
      this.cb.onSocketError?.(ev);
    });
  }

  sendAudio(data: ArrayBuffer | Blob): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(data);
  }

  sendStop(
    turnIdx: number,
    videoSignals?: Record<string, unknown> | null,
    mimeType?: string,
  ): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    const payload: Record<string, unknown> = { type: "stop", turn_idx: turnIdx };
    if (videoSignals) payload.video_signals = videoSignals;
    if (mimeType) payload.mime_type = mimeType;
    this.ws.send(JSON.stringify(payload));
  }

  submitTranscript(
    turnIdx: number,
    content: string,
    videoSignals?: Record<string, unknown> | null,
  ): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    const payload: Record<string, unknown> = {
      type: "submit_transcript",
      turn_idx: turnIdx,
      content,
    };
    if (videoSignals) payload.video_signals = videoSignals;
    const llmConfig = buildLLMPayload();
    if (llmConfig) payload.llm_config = llmConfig;
    this.ws.send(JSON.stringify(payload));
  }

  sendCancel(): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.ws.send(JSON.stringify({ type: "cancel" }));
  }

  close(): void {
    if (!this.ws) return;
    try {
      this.ws.close();
    } catch {
      /* ignore */
    }
    this.ws = null;
  }

  private async handleMessage(ev: MessageEvent): Promise<void> {
    if (typeof ev.data === "string") {
      await this.drainPendingBlobReads();
      this.flushAudio();
      await this.handleText(ev.data);
      return;
    }
    if (ev.data instanceof ArrayBuffer) {
      this.audioChunks.push(ev.data);
    } else if (ev.data instanceof Blob) {
      // Some browsers deliver Blob even when binaryType=arraybuffer.
      // Keep conversion ordered before the next text-frame flush.
      const read = ev.data.arrayBuffer().then((buf) => {
        this.audioChunks.push(buf);
      });
      this.pendingBlobReads.push(read);
      read.finally(() => {
        this.pendingBlobReads = this.pendingBlobReads.filter((p) => p !== read);
      });
    }
  }

  private async handleClose(ev: CloseEvent): Promise<void> {
    // Flush any pending TTS before tearing down: a server that hung
    // up right after the last question should still play audio.
    await this.drainPendingBlobReads();
    this.flushAudio();
    this.cb.onClose?.(ev);
    this.ws = null;
  }

  private async handleText(raw: string): Promise<void> {
    let parsed: VoiceServerEvent | null = null;
    try {
      parsed = JSON.parse(raw) as VoiceServerEvent;
    } catch {
      return;
    }
    if (!parsed || typeof parsed !== "object") return;
    switch (parsed.type) {
      case "question":
        this.cb.onQuestion(parsed);
        return;
      case "draft_transcript":
        this.cb.onDraftTranscript(parsed);
        return;
      case "transcript":
        this.cb.onTranscript(parsed);
        return;
      case "final_report":
        this.cb.onFinal(parsed);
        return;
      case "tts_end":
        await this.drainPendingBlobReads();
        this.flushAudio();
        this.cb.onTtsEnd?.();
        return;
      case "error":
        this.cb.onError(parsed);
        return;
    }
  }

  private flushAudio(): void {
    if (this.audioChunks.length === 0) return;
    // MIME guess: OpenAI TTS defaults to mp3. Browsers decode mp3
    // universally; ``audio/mpeg`` is the correct type here.
    const blob = new Blob(this.audioChunks, { type: "audio/mpeg" });
    this.audioChunks = [];
    this.cb.onAudio(blob);
  }

  private async drainPendingBlobReads(): Promise<void> {
    if (this.pendingBlobReads.length === 0) return;
    await Promise.allSettled(this.pendingBlobReads);
  }
}
