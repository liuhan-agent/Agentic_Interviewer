# Video Interview Mainline Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge "video interview" into the real unified interview path so text and voice answers share one workflow, while camera-derived signals remain optional and never block answer submission or LangGraph execution.

**Architecture:** A video-enabled session opens the normal `/interview/{sessionId}` page. When the current question is available, the page attempts to keep the camera available for the whole interview and samples local MediaPipe metrics during each active answer window; users can turn the camera off/on at any point. The current turn's aggregated `video_signals` are submitted through the same `submitAnswer()` path used by both text and voice answers; missing, invalid, disabled, or failed video signals degrade to `None`.

**Tech Stack:** Next.js 14 App Router, React/TypeScript, MediaPipe FaceMesh, FastAPI, Pydantic, LangGraph state, pytest, node:test source tests.

---

## Product Decisions Locked By This Plan

- "Video interview" is not a separate route and does not revive `VoiceRoom`.
- Text answers and voice-transcribed answers use the same `InterviewRoom` submit path.
- When `enable_video_analysis` is true, the normal interview page exposes a camera panel and attempts to keep camera preview/capture available for the whole interview.
- On desktop, the camera preview is a compact floating panel pinned to the upper-right safe area of the interview viewport. It should not live inside the answer card, because the answer card is already the primary writing surface.
- On mobile/narrow viewports, the camera UI collapses into a small non-blocking control near the answer actions or bottom safe area; it must not cover the question text or submit controls.
- The user can turn the camera off or on during the interview.
- Camera off, permission denied, MediaPipe failure, or invalid `video_signals` must never block answer submit, skip, poll, resume, or final report.
- First version does not upload raw video, store frames, replay video, or call a multimodal LLM.
- First version does not support recording-time pause/resume semantics. Pause is still the existing "pause interview rest" control.
- When the user turns camera off, discard the current turn's unsubmitted video buffer. Turning camera on starts a fresh buffer for the current turn.

---

## File Structure

- Modify: `ai-interviewer/frontend/src/lib/video/types.ts`
  - Runtime guard and weighted merge helpers for `AggregatedVideoSignal`.
- Modify: `ai-interviewer/frontend/src/lib/hooks/useFaceCapture.ts`
  - Non-throwing camera start/stop/capture lifecycle suitable for whole-interview use.
- Create: `ai-interviewer/frontend/src/lib/hooks/useTurnVideoCapture.ts`
  - Own turn-scoped camera state, current-turn buffer, pause/camera-off clearing, and final aggregation.
- Modify: `ai-interviewer/frontend/src/components/interview/InterviewRoom.tsx`
  - Pass `enableVideoAnalysis` into `AnswerBox`.
  - Render a desktop floating camera preview from shared `AnswerBox` turn-capture state.
  - Submit optional `videoSignals` with both text and voice-derived answers.
- Modify: `ai-interviewer/frontend/src/components/interview/VoiceAnswerPanel.tsx`
  - Keep it ASR-only. It should not own camera lifecycle or submit video signals.
- Modify: `ai-interviewer/frontend/src/lib/api/types.ts`
  - Add typed video signal interfaces and expose `enable_video_analysis` on start/poll/resume responses.
- Modify: `ai-interviewer/frontend/src/lib/api/interview.ts`
  - Keep `submitAnswer(sessionId, answer, turnIdx, videoSignals?)` optional.
- Modify: frontend source tests under `ai-interviewer/frontend/tests/`
  - Guard that video is wired into the real `InterviewRoom` / `AnswerBox` path, uses a floating desktop preview, and does not revive the old `VoiceRoom`.
- Modify: `ai-interviewer/backend/app/core/video_signals_schema.py`
  - Add soft normalization: valid dict in, normalized dict out; invalid in, `None` out.
- Modify: `ai-interviewer/backend/app/api/v1/interview.py`
  - Soft-drop invalid HTTP video payloads.
  - Surface `enable_video_analysis` in session, poll, and resume payloads.
- Modify: `ai-interviewer/backend/app/api/v1/ws_voice.py`
  - Soft-drop invalid WS video payloads for legacy clients, while preserving stop/transcript frames.
- Modify: `ai-interviewer/backend/app/services/interview_question_response.py`
  - Include `enable_video_analysis` in poll payloads.
- Modify: `ai-interviewer/backend/app/services/session_manager.py`
  - Store `enable_video_analysis` on `SessionHandle`, set it from initial runtime config, and recover it.
- Modify: `ai-interviewer/backend/app/services/session_persistence.py`
  - Persist `enable_video_analysis`.
- Modify: `ai-interviewer/backend/app/models/interview_session.py`
  - Add `enable_video_analysis` boolean column.
- Modify: `ai-interviewer/backend/app/models/base.py`
  - Add SQLite/Postgres schema upgrade entries.
- Modify: `ai-interviewer/backend/app/engine/workflow/state.py`
  - Add optional `video_signals` to `QATurn`.
- Modify: `ai-interviewer/backend/app/engine/workflow/nodes/evaluator.py`
  - Persist current turn video signals into `qa_history`.
- Modify: `ai-interviewer/backend/app/engine/workflow/nodes/final_report.py`
  - Build `video_analysis` from all valid `qa_history[*].video_signals`.

---

### Task 1: Frontend Video Signal Helpers

**Files:**
- Modify: `ai-interviewer/frontend/src/lib/video/types.ts`
- Test: `ai-interviewer/frontend/tests/videoSignalSource.test.js`

- [ ] **Step 1: Write source tests for runtime guard and merge**

Create `ai-interviewer/frontend/tests/videoSignalSource.test.js`:

```js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const videoTypes = fs.readFileSync(
  path.join(__dirname, "..", "src", "lib", "video", "types.ts"),
  "utf8",
);

test("video signal helpers expose runtime guard and weighted merge", () => {
  assert.match(videoTypes, /export function isAggregatedVideoSignal/);
  assert.match(videoTypes, /export function mergeAggregatedVideoSignals/);
  assert.match(videoTypes, /totalSamples/);
  assert.match(videoTypes, /emotionCounts/);
  assert.match(videoTypes, /sample_count/);
});
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
cd ai-interviewer/frontend
node --test tests/videoSignalSource.test.js
```

Expected: FAIL because the helpers do not exist.

- [ ] **Step 3: Implement helpers**

Append to `ai-interviewer/frontend/src/lib/video/types.ts`:

```ts
const VIDEO_EMOTIONS = new Set(["neutral", "positive", "nervous", "confused"]);

function isFiniteUnitScore(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}

export function isAggregatedVideoSignal(
  value: unknown,
): value is AggregatedVideoSignal {
  if (!value || typeof value !== "object") return false;
  const signal = value as Partial<AggregatedVideoSignal>;
  return (
    isFiniteUnitScore(signal.confidence) &&
    isFiniteUnitScore(signal.engagement) &&
    typeof signal.dominant_emotion === "string" &&
    VIDEO_EMOTIONS.has(signal.dominant_emotion) &&
    Number.isInteger(signal.sample_count) &&
    signal.sample_count >= 1 &&
    signal.sample_count <= 1000
  );
}

export function mergeAggregatedVideoSignals(
  signals: Array<AggregatedVideoSignal | null | undefined>,
): AggregatedVideoSignal | null {
  const valid = signals.filter(isAggregatedVideoSignal);
  if (valid.length === 0) return null;

  const totalSamples = valid.reduce((sum, signal) => sum + signal.sample_count, 0);
  if (totalSamples <= 0) return null;

  const confidence =
    valid.reduce((sum, signal) => sum + signal.confidence * signal.sample_count, 0) /
    totalSamples;
  const engagement =
    valid.reduce((sum, signal) => sum + signal.engagement * signal.sample_count, 0) /
    totalSamples;

  const emotionCounts = new Map<string, number>();
  for (const signal of valid) {
    emotionCounts.set(
      signal.dominant_emotion,
      (emotionCounts.get(signal.dominant_emotion) ?? 0) + signal.sample_count,
    );
  }

  let dominantEmotion = "neutral";
  let strongestCount = -1;
  for (const [emotion, count] of emotionCounts) {
    if (count > strongestCount) {
      dominantEmotion = emotion;
      strongestCount = count;
    }
  }

  return {
    confidence: Math.round(confidence * 100) / 100,
    engagement: Math.round(engagement * 100) / 100,
    dominant_emotion: dominantEmotion,
    sample_count: Math.min(1000, totalSamples),
  };
}
```

- [ ] **Step 4: Run the test**

Run:

```bash
cd ai-interviewer/frontend
node --test tests/videoSignalSource.test.js
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ai-interviewer/frontend/src/lib/video/types.ts ai-interviewer/frontend/tests/videoSignalSource.test.js
git commit -m "feat: add video signal merge helpers"
```

---

### Task 2: Safe Low-Level Face Capture Hook

**Files:**
- Modify: `ai-interviewer/frontend/src/lib/hooks/useFaceCapture.ts`
- Test: `ai-interviewer/frontend/tests/videoSignalSource.test.js`

- [ ] **Step 1: Add source tests for safe lifecycle controls**

Append to `ai-interviewer/frontend/tests/videoSignalSource.test.js`:

```js
test("face capture hook exposes safe whole-interview lifecycle controls", () => {
  const hookSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "hooks", "useFaceCapture.ts"),
    "utf8",
  );

  assert.match(hookSource, /startCamera: \(\) => Promise<boolean>/);
  assert.match(hookSource, /releaseCamera: \(\) => void/);
  assert.match(hookSource, /startCapture: \(\) => void/);
  assert.match(hookSource, /stopCapture: \(\) => AggregatedVideoSignal \| null/);
  assert.match(hookSource, /resetCapture: \(\) => void/);
  assert.match(hookSource, /clearInterval/);
  assert.match(hookSource, /catch/);
  assert.doesNotMatch(hookSource, /throw /);
});
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
cd ai-interviewer/frontend
node --test tests/videoSignalSource.test.js
```

Expected: FAIL because `startCamera`, `releaseCamera`, and `resetCapture` are not exposed.

- [ ] **Step 3: Update hook return type**

In `ai-interviewer/frontend/src/lib/hooks/useFaceCapture.ts`, change `UseFaceCaptureReturn` to:

```ts
export interface UseFaceCaptureReturn {
  cameraOn: boolean;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  startCamera: () => Promise<boolean>;
  releaseCamera: () => void;
  toggleCamera: () => Promise<void>;
  startCapture: () => void;
  stopCapture: () => AggregatedVideoSignal | null;
  resetCapture: () => void;
  cameraError: string | null;
  analysisWarning: string | null;
}
```

- [ ] **Step 4: Implement non-throwing camera and capture methods**

Inside the hook, add:

```ts
  const clearCaptureInterval = useCallback(() => {
    if (captureIntervalRef.current) {
      clearInterval(captureIntervalRef.current);
      captureIntervalRef.current = null;
    }
  }, []);

  const resetCapture = useCallback(() => {
    clearCaptureInterval();
    signalBufferRef.current = [];
  }, [clearCaptureInterval]);

  const releaseCamera = useCallback(() => {
    resetCapture();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setCameraOn(false);
  }, [resetCapture]);

  const startCamera = useCallback(async (): Promise<boolean> => {
    if (streamRef.current) {
      setCameraOn(true);
      if (videoRef.current) videoRef.current.srcObject = streamRef.current;
      return true;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      streamRef.current = stream;
      setCameraOn(true);
      setCameraError(null);
      if (videoRef.current) videoRef.current.srcObject = stream;
      const canAnalyze = await preloadFaceMesh();
      setAnalysisWarning(
        canAnalyze
          ? null
          : "Video analysis is unavailable. The interview can continue without it.",
      );
      return true;
    } catch {
      setCameraError("Camera permission was denied or the device is unavailable.");
      setAnalysisWarning(null);
      releaseCamera();
      return false;
    }
  }, [releaseCamera]);
```

Update `toggleCamera` to call `releaseCamera()` when on and `startCamera()` when off.

Update `startCapture` to never throw:

```ts
  const startCapture = useCallback(() => {
    if (!videoRef.current || !streamRef.current) return;
    clearCaptureInterval();
    signalBufferRef.current = [];
    captureIntervalRef.current = setInterval(async () => {
      try {
        if (!videoRef.current) return;
        const result = await analyzeFrame(videoRef.current);
        if (result.ok) signalBufferRef.current.push(result.signal);
      } catch {
        setAnalysisWarning("Video analysis is temporarily unavailable. The interview can continue without it.");
      }
    }, CAPTURE_INTERVAL_MS);
  }, [clearCaptureInterval]);
```

Update cleanup effect to call `releaseCamera()`.

- [ ] **Step 5: Return new methods**

Return:

```ts
    startCamera,
    releaseCamera,
    toggleCamera,
    startCapture,
    stopCapture,
    resetCapture,
```

- [ ] **Step 6: Run the test**

Run:

```bash
cd ai-interviewer/frontend
node --test tests/videoSignalSource.test.js
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ai-interviewer/frontend/src/lib/hooks/useFaceCapture.ts ai-interviewer/frontend/tests/videoSignalSource.test.js
git commit -m "feat: harden face capture lifecycle"
```

---

### Task 3: Turn-Scoped Video Capture Hook

**Files:**
- Create: `ai-interviewer/frontend/src/lib/hooks/useTurnVideoCapture.ts`
- Test: `ai-interviewer/frontend/tests/videoSignalSource.test.js`

- [ ] **Step 1: Add source tests for turn-scoped behavior**

Append to `ai-interviewer/frontend/tests/videoSignalSource.test.js`:

```js
test("turn video capture hook scopes camera signals to the active question", () => {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "lib", "hooks", "useTurnVideoCapture.ts"),
    "utf8",
  );

  assert.match(source, /export function useTurnVideoCapture/);
  assert.match(source, /enableVideoAnalysis/);
  assert.match(source, /turnIdx/);
  assert.match(source, /paused/);
  assert.match(source, /startCamera/);
  assert.match(source, /releaseCamera/);
  assert.match(source, /startCapture/);
  assert.match(source, /finishTurnCapture/);
  assert.match(source, /clearTurnCapture/);
  assert.match(source, /resetCapture/);
});
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
cd ai-interviewer/frontend
node --test tests/videoSignalSource.test.js
```

Expected: FAIL because `useTurnVideoCapture.ts` does not exist.

- [ ] **Step 3: Create the hook**

Create `ai-interviewer/frontend/src/lib/hooks/useTurnVideoCapture.ts`:

```ts
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useFaceCapture } from "@/lib/hooks/useFaceCapture";
import type { AggregatedVideoSignal } from "@/lib/video/types";

export type VideoCaptureStatus =
  | "disabled"
  | "camera_off"
  | "starting"
  | "capturing"
  | "paused"
  | "unavailable";

export interface UseTurnVideoCaptureOptions {
  enableVideoAnalysis: boolean;
  turnIdx: number | null;
  paused: boolean;
}

export interface UseTurnVideoCaptureReturn {
  cameraOn: boolean;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  status: VideoCaptureStatus;
  warning: string | null;
  toggleCamera: () => Promise<void>;
  finishTurnCapture: () => AggregatedVideoSignal | null;
  clearTurnCapture: () => void;
}

export function useTurnVideoCapture({
  enableVideoAnalysis,
  turnIdx,
  paused,
}: UseTurnVideoCaptureOptions): UseTurnVideoCaptureReturn {
  const [status, setStatus] = useState<VideoCaptureStatus>(
    enableVideoAnalysis ? "camera_off" : "disabled",
  );
  const activeTurnRef = useRef<number | null>(null);
  const cameraRequestedRef = useRef(false);
  const {
    cameraOn,
    videoRef,
    startCamera,
    releaseCamera,
    toggleCamera: toggleRawCamera,
    startCapture,
    stopCapture,
    resetCapture,
    cameraError,
    analysisWarning,
  } = useFaceCapture();

  const clearTurnCapture = useCallback(() => {
    stopCapture();
    resetCapture();
  }, [resetCapture, stopCapture]);

  const finishTurnCapture = useCallback((): AggregatedVideoSignal | null => {
    if (!enableVideoAnalysis || !cameraOn || turnIdx === null) {
      clearTurnCapture();
      return null;
    }
    const signal = stopCapture();
    resetCapture();
    return signal;
  }, [
    cameraOn,
    clearTurnCapture,
    enableVideoAnalysis,
    resetCapture,
    stopCapture,
    turnIdx,
  ]);

  const toggleCamera = useCallback(async () => {
    if (!enableVideoAnalysis) return;
    if (cameraOn) {
      releaseCamera();
      clearTurnCapture();
      setStatus("camera_off");
      return;
    }
    setStatus("starting");
    await toggleRawCamera();
  }, [cameraOn, clearTurnCapture, enableVideoAnalysis, releaseCamera, toggleRawCamera]);

  useEffect(() => {
    if (!enableVideoAnalysis) {
      releaseCamera();
      clearTurnCapture();
      setStatus("disabled");
      return;
    }
    if (turnIdx === null) {
      clearTurnCapture();
      setStatus(cameraOn ? "camera_off" : "camera_off");
      return;
    }
    if (activeTurnRef.current !== turnIdx) {
      activeTurnRef.current = turnIdx;
      clearTurnCapture();
    }
    if (!cameraRequestedRef.current) {
      cameraRequestedRef.current = true;
      setStatus("starting");
      void startCamera().then((ok) => {
        setStatus(ok ? "capturing" : "unavailable");
      });
      return;
    }
    if (!cameraOn) {
      setStatus("camera_off");
      return;
    }
    if (paused) {
      clearTurnCapture();
      setStatus("paused");
      return;
    }
    startCapture();
    setStatus("capturing");
  }, [
    cameraOn,
    clearTurnCapture,
    enableVideoAnalysis,
    paused,
    releaseCamera,
    startCamera,
    startCapture,
    turnIdx,
  ]);

  useEffect(() => {
    return () => {
      releaseCamera();
    };
  }, [releaseCamera]);

  return {
    cameraOn,
    videoRef,
    status,
    warning: cameraError ?? analysisWarning,
    toggleCamera,
    finishTurnCapture,
    clearTurnCapture,
  };
}
```

- [ ] **Step 4: Run the test**

Run:

```bash
cd ai-interviewer/frontend
node --test tests/videoSignalSource.test.js
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ai-interviewer/frontend/src/lib/hooks/useTurnVideoCapture.ts ai-interviewer/frontend/tests/videoSignalSource.test.js
git commit -m "feat: add turn-scoped video capture hook"
```

---

### Task 4: Wire Video Capture Into Unified AnswerBox With Floating Preview

**Files:**
- Modify: `ai-interviewer/frontend/src/components/interview/InterviewRoom.tsx`
- Modify: `ai-interviewer/frontend/src/components/interview/VoiceAnswerPanel.tsx`
- Modify: `ai-interviewer/frontend/tests/interviewRoomUxSource.test.js`
- Modify: `ai-interviewer/frontend/tests/voiceClientSource.test.js`

- [ ] **Step 1: Add source tests for unified path wiring**

Append to `ai-interviewer/frontend/tests/interviewRoomUxSource.test.js`:

```js
test("video interview is wired into the unified answer path", () => {
  assert.match(source, /useTurnVideoCapture/);
  assert.match(source, /enableVideoAnalysis=\{state\.enableVideoAnalysis\}/);
  assert.match(source, /finishTurnCapture\(\)/);
  assert.match(source, /clearTurnCapture\(\)/);
  assert.match(source, /submitAnswer\(sessionId, text, state\.turnIdx, videoSignals/);
  assert.match(source, /videoRef/);
  assert.match(source, /toggleCamera/);
  assert.match(source, /VideoPreviewPanel/);
  assert.match(source, /fixed right-6 top-20/);
  assert.match(source, /hidden xl:block/);
  assert.match(source, /xl:hidden/);
  assert.doesNotMatch(source, /<VoiceRoom/);
});
```

Append to `ai-interviewer/frontend/tests/voiceClientSource.test.js`:

```js
test("voice answer panel remains ASR-only and does not own video capture", () => {
  const panelSource = fs.readFileSync(
    path.join(__dirname, "..", "src", "components", "interview", "VoiceAnswerPanel.tsx"),
    "utf8",
  );

  assert.doesNotMatch(panelSource, /useFaceCapture/);
  assert.doesNotMatch(panelSource, /useTurnVideoCapture/);
  assert.match(panelSource, /sendStop\(turnIdx, null, recordingMimeType\)/);
});
```

- [ ] **Step 2: Run failing source tests**

Run:

```bash
cd ai-interviewer/frontend
node --test tests/interviewRoomUxSource.test.js tests/voiceClientSource.test.js
```

Expected: FAIL because `InterviewRoom` does not use `useTurnVideoCapture`.

- [ ] **Step 3: Import hook and type**

In `ai-interviewer/frontend/src/components/interview/InterviewRoom.tsx`, add:

```ts
import { useTurnVideoCapture } from "@/lib/hooks/useTurnVideoCapture";
import type { AggregatedVideoSignal } from "@/lib/video/types";
```

- [ ] **Step 4: Extend submit signatures**

Change `handleSubmit`:

```ts
  async function handleSubmit(
    text: string,
    videoSignals?: AggregatedVideoSignal | null,
  ) {
```

Change API call:

```ts
      await submitAnswer(sessionId, text, state.turnIdx, videoSignals ?? undefined);
```

Change `AnswerBox` prop type:

```ts
  onSubmit: (
    text: string,
    videoSignals?: AggregatedVideoSignal | null,
  ) => Promise<boolean>;
  enableVideoAnalysis: boolean;
```

Pass the capability:

```tsx
              enableVideoAnalysis={state.enableVideoAnalysis}
```

- [ ] **Step 5: Use turn video capture in `AnswerBox`**

Inside `AnswerBox`, add:

```ts
  const {
    cameraOn,
    videoRef,
    status: videoStatus,
    warning: videoWarning,
    toggleCamera,
    finishTurnCapture,
    clearTurnCapture,
  } = useTurnVideoCapture({
    enableVideoAnalysis,
    turnIdx,
    paused,
  });
```

- [ ] **Step 6: Submit current turn video for both text and voice answers**

In `handleLocalSubmit`, before calling `onSubmit`:

```ts
    const videoSignals = finishTurnCapture();
```

Call:

```ts
    const success = await onSubmit(text, videoSignals);
```

If submit fails, do not throw. The answer draft remains. The video buffer has been consumed; the next camera samples will refill it while the user retries. This keeps video weak and prevents stale analysis from blocking reauth flows.

- [ ] **Step 7: Clear video on skip, pause, and turn changes**

In the `draftKey` reset effect, add:

```ts
    clearTurnCapture();
```

In `handleLocalSkip`, before or after successful skip:

```ts
      clearTurnCapture();
```

Add:

```ts
  useEffect(() => {
    if (paused) {
      clearTurnCapture();
    }
  }, [clearTurnCapture, paused]);
```

- [ ] **Step 8: Render a floating desktop preview and compact mobile control**

Inside `AnswerBox`, render only the compact mobile fallback above the textarea:

```tsx
        {enableVideoAnalysis && (
          <div className="xl:hidden rounded-lg border border-violet-500/20 bg-violet-500/[0.03] p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <p className="text-sm font-medium text-violet-200">
                  视频面试
                </p>
                <p className="text-xs text-muted-foreground">
                  摄像头仅在本地提取专注度/自信度指标，不上传视频画面。
                </p>
              </div>
              <Button
                type="button"
                variant={cameraOn ? "default" : "outline"}
                size="sm"
                onClick={() => void toggleCamera()}
                disabled={submitting}
                className="gap-1.5"
              >
                {cameraOn ? "关闭摄像头" : "开启摄像头"}
              </Button>
            </div>
            {cameraOn && (
              <div className="relative aspect-video overflow-hidden rounded-md bg-black">
                <video
                  ref={videoRef as React.RefObject<HTMLVideoElement>}
                  autoPlay
                  playsInline
                  muted
                  className="h-full w-full object-cover"
                  style={{ transform: "scaleX(-1)" }}
                />
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              状态：{videoStatus}
            </p>
            {videoWarning && (
              <p className="rounded-md border border-amber-500/30 bg-amber-500/[0.05] px-3 py-2 text-xs text-amber-200">
                {videoWarning}
              </p>
            )}
          </div>
        )}
```

Render the desktop preview as a floating panel near the end of `AnswerBox`'s returned JSX:

```tsx
      {enableVideoAnalysis && (
        <VideoPreviewPanel
          cameraOn={cameraOn}
          videoRef={videoRef}
          videoStatus={videoStatus}
          videoWarning={videoWarning}
          submitting={submitting}
          onToggleCamera={toggleCamera}
        />
      )}
```

Add this local component below `AnswerBox`:

```tsx
function VideoPreviewPanel({
  cameraOn,
  videoRef,
  videoStatus,
  videoWarning,
  submitting,
  onToggleCamera,
}: {
  cameraOn: boolean;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  videoStatus: string;
  videoWarning: string | null;
  submitting: boolean;
  onToggleCamera: () => Promise<void>;
}) {
  return (
    <aside
      aria-label="视频面试预览"
      className="pointer-events-auto fixed right-6 top-20 z-30 hidden w-64 overflow-hidden rounded-lg border border-violet-500/20 bg-background/90 shadow-lg backdrop-blur-xl xl:block"
    >
      <div className="flex items-center justify-between border-b border-border/60 px-3 py-2">
        <div>
          <p className="text-xs font-medium text-violet-200">视频面试</p>
          <p className="text-[11px] text-muted-foreground">{videoStatus}</p>
        </div>
        <Button
          type="button"
          variant={cameraOn ? "default" : "outline"}
          size="sm"
          onClick={() => void onToggleCamera()}
          disabled={submitting}
          className="h-7 px-2 text-[11px]"
        >
          {cameraOn ? "关闭" : "开启"}
        </Button>
      </div>
      {cameraOn ? (
        <video
          ref={videoRef as React.RefObject<HTMLVideoElement>}
          autoPlay
          playsInline
          muted
          className="aspect-video w-full bg-black object-cover"
          style={{ transform: "scaleX(-1)" }}
        />
      ) : (
        <div className="flex aspect-video items-center justify-center bg-secondary/50 text-xs text-muted-foreground">
          摄像头已关闭
        </div>
      )}
      {videoWarning && (
        <p className="border-t border-amber-500/20 px-3 py-2 text-[11px] leading-relaxed text-amber-200">
          {videoWarning}
        </p>
      )}
    </aside>
  );
}
```

The desktop panel is intentionally fixed and compact (`w-64`) so it uses the right-side empty space visible in the current interview layout. It stays outside the answer card to preserve writing focus.

- [ ] **Step 9: Keep `VoiceAnswerPanel` ASR-only**

Do not import camera hooks in `VoiceAnswerPanel`. Keep:

```ts
clientRef.current?.sendStop(turnIdx, null, recordingMimeType);
```

Voice output still inserts transcript into the same draft. The eventual `handleLocalSubmit()` handles video for the unified answer.

- [ ] **Step 10: Run focused frontend tests**

Run:

```bash
cd ai-interviewer/frontend
node --test tests/videoSignalSource.test.js tests/interviewRoomUxSource.test.js tests/voiceClientSource.test.js
```

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add ai-interviewer/frontend/src/components/interview/InterviewRoom.tsx ai-interviewer/frontend/src/components/interview/VoiceAnswerPanel.tsx ai-interviewer/frontend/tests/interviewRoomUxSource.test.js ai-interviewer/frontend/tests/voiceClientSource.test.js
git commit -m "feat: wire floating video preview into interview path"
```

---

### Task 5: Backend Soft Validation for Video Signals

**Files:**
- Modify: `ai-interviewer/backend/app/core/video_signals_schema.py`
- Modify: `ai-interviewer/backend/app/api/v1/interview.py`
- Modify: `ai-interviewer/backend/app/api/v1/ws_voice.py`
- Modify: `ai-interviewer/backend/tests/unit/test_session_auth_api.py`
- Modify: `ai-interviewer/backend/tests/unit/test_ws_voice_empty_transcript.py`

- [ ] **Step 1: Change tests from hard reject to soft drop**

In `ai-interviewer/backend/tests/unit/test_session_auth_api.py`, replace the invalid-video test with:

```py
@pytest.mark.parametrize(
    "video_signals",
    [
        {"confidence": 0.5, "engagement": 0.5, "dominant_emotion": "neutral"},
        {
            "confidence": 1.5,
            "engagement": 0.5,
            "dominant_emotion": "neutral",
            "sample_count": 5,
        },
        {
            "confidence": 0.5,
            "engagement": 0.5,
            "dominant_emotion": "angry",
            "sample_count": 5,
        },
    ],
)
def test_submit_answer_drops_invalid_video_signals(
    client: tuple[TestClient, _Manager],
    video_signals: dict[str, Any],
) -> None:
    http, manager = client

    resp = http.post(
        "/api/v1/interview/sessions/sess-auth/answer",
        headers={"X-Session-Token": "session-secret"},
        json={
            "answer": "ok",
            "turn_idx": 2,
            "video_signals": video_signals,
        },
    )

    assert resp.status_code == 200
    assert manager.submitted[-1]["answer"] == "ok"
    assert manager.submitted[-1]["video_signals"] is None
```

In `ai-interviewer/backend/tests/unit/test_ws_voice_empty_transcript.py`, replace the invalid-video parser test with:

```py
def test_parse_text_drops_invalid_video_signals() -> None:
    payload = {
        "type": "stop",
        "turn_idx": 0,
        "video_signals": {
            "confidence": 2,
            "engagement": 0.5,
            "dominant_emotion": "neutral",
            "sample_count": 3,
        },
    }

    assert ws_voice_module._parse_text(json.dumps(payload)) == {
        "type": "stop",
        "turn_idx": 0,
        "video_signals": None,
        "mime_type": None,
    }
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd ai-interviewer/backend
python -m pytest tests/unit/test_session_auth_api.py::test_submit_answer_drops_invalid_video_signals tests/unit/test_ws_voice_empty_transcript.py::test_parse_text_drops_invalid_video_signals -q
```

Expected: FAIL because invalid video currently rejects.

- [ ] **Step 3: Add soft normalization helper**

In `ai-interviewer/backend/app/core/video_signals_schema.py`, append:

```py
from typing import Any


def normalize_video_signals(value: Any) -> dict[str, Any] | None:
    """Return validated video signals or None.

    Video is an optional enhancement signal. Invalid payloads must not
    block answer submission or LangGraph resume.
    """
    if value is None:
        return None
    if isinstance(value, VideoSignalsInput):
        return value.model_dump(exclude_none=False)
    if not isinstance(value, dict):
        return None
    try:
        return VideoSignalsInput.model_validate(value).model_dump(exclude_none=False)
    except Exception:
        return None
```

- [ ] **Step 4: Make HTTP answer request accept raw video dicts**

In `ai-interviewer/backend/app/api/v1/interview.py`, change `AnswerRequest.video_signals`:

```py
    video_signals: dict[str, Any] | None = None
```

Import `normalize_video_signals` and replace payload construction:

```py
    video_signals_payload = normalize_video_signals(body.video_signals)
```

- [ ] **Step 5: Make WS parser soft-drop invalid video**

In `ai-interviewer/backend/app/api/v1/ws_voice.py`, import `normalize_video_signals`. In `_parse_text`, replace hard video validation with:

```py
        video_signals = normalize_video_signals(data.get("video_signals"))
```

Keep unknown frame types, missing `turn_idx`, oversized frames, and invalid transcript content as hard invalid frames. Only video validation becomes soft.

- [ ] **Step 6: Run focused backend tests**

Run:

```bash
cd ai-interviewer/backend
python -m pytest tests/unit/test_session_auth_api.py::test_submit_answer_accepts_valid_video_signals tests/unit/test_session_auth_api.py::test_submit_answer_drops_invalid_video_signals tests/unit/test_ws_voice_empty_transcript.py::test_parse_text_drops_invalid_video_signals -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ai-interviewer/backend/app/core/video_signals_schema.py ai-interviewer/backend/app/api/v1/interview.py ai-interviewer/backend/app/api/v1/ws_voice.py ai-interviewer/backend/tests/unit/test_session_auth_api.py ai-interviewer/backend/tests/unit/test_ws_voice_empty_transcript.py
git commit -m "feat: treat invalid video signals as optional"
```

---

### Task 6: Persist Session Video Capability

**Files:**
- Modify: `ai-interviewer/backend/app/models/interview_session.py`
- Modify: `ai-interviewer/backend/app/models/base.py`
- Modify: `ai-interviewer/backend/app/services/session_manager.py`
- Modify: `ai-interviewer/backend/app/services/session_persistence.py`
- Modify: `ai-interviewer/backend/app/api/v1/interview.py`
- Modify: `ai-interviewer/backend/app/services/interview_question_response.py`
- Modify: `ai-interviewer/frontend/src/lib/api/types.ts`
- Modify: `ai-interviewer/frontend/src/lib/hooks/useQuestionPoller.ts`
- Test: `ai-interviewer/backend/tests/unit/test_interview_setup_api_contract.py`
- Test: `ai-interviewer/backend/tests/unit/test_interview_runtime_api_contract.py`
- Test: `ai-interviewer/backend/tests/unit/test_schema_upgrade.py`

- [ ] **Step 1: Add backend tests for capability echo**

In `ai-interviewer/backend/tests/unit/test_interview_setup_api_contract.py`, add a test that starts a session with `enable_video_analysis=True` and asserts:

```py
assert resp.json()["enable_video_analysis"] is True
```

In `ai-interviewer/backend/tests/unit/test_interview_runtime_api_contract.py`, extend poll and resume contract tests to assert:

```py
assert body["enable_video_analysis"] is True
```

Set the fake manager handle's `enable_video_analysis = True`.

In `ai-interviewer/backend/tests/unit/test_schema_upgrade.py`, add `"enable_video_analysis"` to the expected `interview_sessions` upgrade list.

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd ai-interviewer/backend
python -m pytest tests/unit/test_interview_setup_api_contract.py tests/unit/test_interview_runtime_api_contract.py tests/unit/test_schema_upgrade.py -q
```

Expected: FAIL because the capability is not persisted or echoed.

- [ ] **Step 3: Add DB/model field**

In `ai-interviewer/backend/app/models/interview_session.py`, add:

```py
    enable_video_analysis: Mapped[bool] = mapped_column(Boolean, default=False)
```

In `ai-interviewer/backend/app/models/base.py`, add SQLite upgrade:

```py
        "enable_video_analysis": "BOOLEAN DEFAULT 0",
```

and Postgres upgrade:

```py
        "enable_video_analysis": "BOOLEAN DEFAULT FALSE",
```

- [ ] **Step 4: Add handle field and set it at start**

In `SessionHandle`, add:

```py
    enable_video_analysis: bool = False
```

In `SessionManager.start`, compute:

```py
        enable_video_analysis = bool(runtime_cfg.get("enable_video_analysis"))
```

Pass it into each `SessionHandle(...)` constructor:

```py
                enable_video_analysis=enable_video_analysis,
```

- [ ] **Step 5: Persist and recover capability**

In `SessionPersistence.persist_interrupt` and `persist_completed`, assign:

```py
                row.enable_video_analysis = bool(getattr(handle, "enable_video_analysis", False))
```

In persistence load methods that return row data, include:

```py
                    "enable_video_analysis": bool(row.enable_video_analysis),
```

In session-manager recovery paths that rebuild `SessionHandle`, pass:

```py
            enable_video_analysis=bool(data.get("enable_video_analysis")),
```

- [ ] **Step 6: Echo capability through APIs**

In `start_session`, return:

```py
            "enable_video_analysis": bool(getattr(handle, "enable_video_analysis", False)),
```

In `build_question_poll_payload`, add parameter:

```py
    enable_video_analysis: bool = False,
```

Add this key to every return dict:

```py
        "enable_video_analysis": bool(enable_video_analysis),
```

In `poll_question`, pass:

```py
        enable_video_analysis=bool(getattr(handle, "enable_video_analysis", False)),
```

In `resume_session`, include:

```py
            "enable_video_analysis": bool(getattr(handle, "enable_video_analysis", False)),
```

in cancelled, completed, and waiting/running responses.

- [ ] **Step 7: Update frontend API types and poller**

In `ai-interviewer/frontend/src/lib/api/types.ts`, add to `StartSessionResponse`, `PollQuestionResponse`, and `ResumeResponse`:

```ts
  enable_video_analysis?: boolean;
```

In `ai-interviewer/frontend/src/lib/hooks/useQuestionPoller.ts`, add:

```ts
  enableVideoAnalysis: boolean;
```

to `PollerState`, initialize as `false`, and populate from:

```ts
Boolean(r.enable_video_analysis)
Boolean(res.enable_video_analysis)
```

for resume and poll transitions.

- [ ] **Step 8: Run capability tests**

Run:

```bash
cd ai-interviewer/backend
python -m pytest tests/unit/test_interview_setup_api_contract.py tests/unit/test_interview_runtime_api_contract.py tests/unit/test_schema_upgrade.py -q
cd ../frontend
node --test tests/interviewRoomUxSource.test.js
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add ai-interviewer/backend/app/models/interview_session.py ai-interviewer/backend/app/models/base.py ai-interviewer/backend/app/services/session_manager.py ai-interviewer/backend/app/services/session_persistence.py ai-interviewer/backend/app/api/v1/interview.py ai-interviewer/backend/app/services/interview_question_response.py ai-interviewer/frontend/src/lib/api/types.ts ai-interviewer/frontend/src/lib/hooks/useQuestionPoller.ts ai-interviewer/backend/tests/unit/test_interview_setup_api_contract.py ai-interviewer/backend/tests/unit/test_interview_runtime_api_contract.py ai-interviewer/backend/tests/unit/test_schema_upgrade.py
git commit -m "feat: persist video interview capability"
```

---

### Task 7: Per-Turn Video Persistence and Report Aggregation

**Files:**
- Modify: `ai-interviewer/backend/app/engine/workflow/state.py`
- Modify: `ai-interviewer/backend/app/engine/workflow/nodes/evaluator.py`
- Modify: `ai-interviewer/backend/app/engine/workflow/nodes/final_report.py`
- Modify: `ai-interviewer/frontend/src/lib/api/types.ts`
- Test: `ai-interviewer/backend/tests/unit/test_video_signals_report.py`

- [ ] **Step 1: Add report aggregation tests**

Create `ai-interviewer/backend/tests/unit/test_video_signals_report.py`:

```py
from app.engine.workflow.nodes.final_report import final_report_node


def test_final_report_aggregates_video_signals_from_qa_history() -> None:
    state = {
        "qa_history": [
            {
                "turn_idx": 0,
                "dimension": "communication",
                "question": "q1",
                "answer": "a1",
                "evaluation": {"score": 8, "passed": True},
                "video_signals": {
                    "confidence": 0.8,
                    "engagement": 0.6,
                    "dominant_emotion": "neutral",
                    "sample_count": 10,
                },
            },
            {
                "turn_idx": 1,
                "dimension": "communication",
                "question": "q2",
                "answer": "a2",
                "evaluation": {"score": 7,
                "passed": True},
                "video_signals": {
                    "confidence": 0.4,
                    "engagement": 0.9,
                    "dominant_emotion": "positive",
                    "sample_count": 30,
                },
            },
        ],
        "scores_per_dim": {"communication": 7.5},
        "dimension_status": {"communication": "passed"},
        "quality_threshold": 7.5,
        "status": "running",
    }

    report = final_report_node(state)["final_report"]

    assert report["video_analysis"] == {
        "avg_engagement": 0.82,
        "avg_confidence": 0.5,
        "dominant_emotion": "positive",
        "sample_count": 40,
        "turn_count": 2,
    }


def test_final_report_omits_video_analysis_without_valid_signals() -> None:
    state = {
        "qa_history": [
            {
                "turn_idx": 0,
                "dimension": "communication",
                "question": "q1",
                "answer": "a1",
                "evaluation": {"score": 8, "passed": True},
            }
        ],
        "scores_per_dim": {"communication": 8},
        "dimension_status": {"communication": "passed"},
        "quality_threshold": 7.5,
        "status": "running",
    }

    report = final_report_node(state)["final_report"]

    assert "video_analysis" not in report
```

- [ ] **Step 2: Run failing tests**

Run:

```bash
cd ai-interviewer/backend
python -m pytest tests/unit/test_video_signals_report.py -q
```

Expected: FAIL because final report still reads the last state-level `video_signals`.

- [ ] **Step 3: Persist video on `QATurn`**

In `ai-interviewer/backend/app/engine/workflow/state.py`, add to `QATurn`:

```py
    video_signals: dict[str, Any] | None
```

In `ai-interviewer/backend/app/engine/workflow/nodes/evaluator.py`, add to `qa_turn`:

```py
        "video_signals": state.get("video_signals"),
```

- [ ] **Step 4: Aggregate report from `qa_history`**

In `ai-interviewer/backend/app/engine/workflow/nodes/final_report.py`, add:

```py
def _video_analysis_summary(qa_history: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid: list[dict[str, Any]] = []
    for qa in qa_history:
        sig = qa.get("video_signals")
        if not isinstance(sig, dict):
            continue
        confidence = sig.get("confidence")
        engagement = sig.get("engagement")
        emotion = sig.get("dominant_emotion")
        samples = sig.get("sample_count")
        if not isinstance(confidence, (int, float)):
            continue
        if not isinstance(engagement, (int, float)):
            continue
        if not isinstance(emotion, str):
            continue
        if not isinstance(samples, int) or samples <= 0:
            continue
        valid.append(
            {
                "confidence": max(0.0, min(1.0, float(confidence))),
                "engagement": max(0.0, min(1.0, float(engagement))),
                "dominant_emotion": emotion,
                "sample_count": samples,
            }
        )
    if not valid:
        return None

    total_samples = sum(item["sample_count"] for item in valid)
    avg_confidence = sum(
        item["confidence"] * item["sample_count"] for item in valid
    ) / total_samples
    avg_engagement = sum(
        item["engagement"] * item["sample_count"] for item in valid
    ) / total_samples

    emotion_counts: dict[str, int] = {}
    for item in valid:
        emotion = str(item["dominant_emotion"])
        emotion_counts[emotion] = emotion_counts.get(emotion, 0) + int(item["sample_count"])
    dominant_emotion = max(emotion_counts.items(), key=lambda item: item[1])[0]

    return {
        "avg_engagement": round(avg_engagement, 2),
        "avg_confidence": round(avg_confidence, 2),
        "dominant_emotion": dominant_emotion,
        "sample_count": total_samples,
        "turn_count": len(valid),
    }
```

Replace the old final-report block that reads `state.get("video_signals")` with:

```py
    video_summary = _video_analysis_summary(qa_history)
    if video_summary is not None:
        report["video_analysis"] = video_summary
```

- [ ] **Step 5: Update frontend report type**

In `ai-interviewer/frontend/src/lib/api/types.ts`, ensure `VideoAnalysis` supports:

```ts
export interface VideoAnalysis {
  avg_engagement?: number | null;
  avg_confidence?: number | null;
  dominant_emotion?: string | null;
  sample_count?: number | null;
  turn_count?: number | null;
}
```

- [ ] **Step 6: Run report tests**

Run:

```bash
cd ai-interviewer/backend
python -m pytest tests/unit/test_video_signals_report.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ai-interviewer/backend/app/engine/workflow/state.py ai-interviewer/backend/app/engine/workflow/nodes/evaluator.py ai-interviewer/backend/app/engine/workflow/nodes/final_report.py ai-interviewer/frontend/src/lib/api/types.ts ai-interviewer/backend/tests/unit/test_video_signals_report.py
git commit -m "feat: aggregate video signals per turn"
```

---

### Task 8: Regression Sweep and Manual Smoke

**Files:**
- No source changes expected unless tests reveal defects.

- [ ] **Step 1: Run focused frontend tests**

Run:

```bash
cd ai-interviewer/frontend
node --test tests/videoSignalSource.test.js tests/interviewRoomUxSource.test.js tests/voiceClientSource.test.js tests/digitalHumanSource.test.js
```

Expected: PASS.

- [ ] **Step 2: Run focused backend tests**

Run:

```bash
cd ai-interviewer/backend
python -m pytest tests/unit/test_session_auth_api.py tests/unit/test_interview_runtime_api_contract.py tests/unit/test_interview_setup_api_contract.py tests/unit/test_ws_voice_empty_transcript.py tests/unit/test_video_signals_report.py tests/unit/test_schema_upgrade.py -q
```

Expected: PASS.

- [ ] **Step 3: Run prompt/context guard tests**

Run:

```bash
cd ai-interviewer/backend
python -m pytest tests/unit/test_context_renderer.py tests/unit/test_prompt_loader.py -q
```

Expected: PASS.

- [ ] **Step 4: Manual browser smoke test**

Start the backend and frontend with the repository's normal local commands. Then verify:

1. Create a session with video analysis enabled.
2. Confirm the app opens the normal `/interview/{sessionId}` page.
3. Confirm the camera preview appears as a compact floating panel in the desktop upper-right safe area.
4. Confirm the camera attempts to start for the video-enabled interview.
5. Turn camera off; confirm the interview stays usable and current turn video buffer is cleared.
6. Turn camera on; answer by typing text; submit; confirm `/answer` succeeds.
7. Answer another question using voice tools; submit the same shared draft path; confirm `/answer` succeeds.
8. Pause during a question; confirm draft text remains and camera sampling stops/clears.
9. Continue; confirm the next submission still works even if the camera remains off.
10. Resize to a mobile-width viewport; confirm the camera UI becomes compact and does not cover question text, answer input, or submit controls.
11. Finish the interview; confirm report includes `video_analysis` only when valid samples were captured.

Expected: Any camera, permission, or MediaPipe issue produces only a warning. Text answer, voice transcript, skip, pause, polling, resume, and final report remain functional.

- [ ] **Step 5: Commit fixes if needed**

If Task 8 required code changes:

```bash
git add ai-interviewer
git commit -m "fix: stabilize video interview mainline integration"
```

If no code changes were needed, do not create an empty commit.

---

## Self-Review

- Spec coverage: The plan now covers whole-interview camera availability, desktop upper-right floating preview, mobile compact fallback, user camera toggle, unified text/voice answer submission, weak video failure semantics, pause/skip/turn-change cleanup, per-turn backend persistence, and final report aggregation.
- Placeholder scan: No intentionally unresolved `TBD`, `TODO`, or "implement later" placeholders are present.
- Type consistency: Frontend uses `AggregatedVideoSignal`; backend normalizes to `dict[str, Any] | None`; report exposes `avg_engagement`, `avg_confidence`, `dominant_emotion`, `sample_count`, and `turn_count`.
- Scope check: Raw video upload, video replay, multimodal LLM calls, old `VoiceRoom` resurrection, and recording-time pause/resume segmentation are deliberately out of scope.
