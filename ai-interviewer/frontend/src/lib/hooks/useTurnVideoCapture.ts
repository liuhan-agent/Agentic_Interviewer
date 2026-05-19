"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";

import { useFaceCapture } from "@/lib/hooks/useFaceCapture";
import type { AggregatedVideoSignal } from "@/lib/video/types";

export type TurnVideoStatus =
  | "disabled"
  | "idle"
  | "starting"
  | "capturing"
  | "paused"
  | "camera_off"
  | "unavailable";

export interface UseTurnVideoCaptureOptions {
  enableVideoAnalysis: boolean;
  turnIdx: number | null;
  paused: boolean;
}

export interface UseTurnVideoCaptureReturn {
  cameraOn: boolean;
  videoRef: RefObject<HTMLVideoElement>;
  status: TurnVideoStatus;
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
  const {
    cameraOn,
    videoRef,
    startCamera,
    releaseCamera,
    startCapture,
    stopCapture,
    resetCapture,
    cameraError,
    analysisWarning,
  } = useFaceCapture();
  const [status, setStatus] = useState<TurnVideoStatus>(
    enableVideoAnalysis ? "idle" : "disabled",
  );
  const activeTurnRef = useRef<number | null>(null);
  const startInFlightRef = useRef(false);
  const userDisabledCameraRef = useRef(false);

  const warning = useMemo(
    () => cameraError ?? analysisWarning,
    [analysisWarning, cameraError],
  );

  const clearTurnCapture = useCallback(() => {
    stopCapture();
    resetCapture();
  }, [resetCapture, stopCapture]);

  const finishTurnCapture = useCallback((): AggregatedVideoSignal | null => {
    if (!enableVideoAnalysis || turnIdx === null || !cameraOn) {
      clearTurnCapture();
      return null;
    }

    const videoSignal = stopCapture();
    resetCapture();
    return videoSignal;
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
      userDisabledCameraRef.current = true;
      releaseCamera();
      clearTurnCapture();
      setStatus("camera_off");
      return;
    }

    userDisabledCameraRef.current = false;
    setStatus("starting");
    const started = await startCamera();
    if (!started) {
      userDisabledCameraRef.current = true;
      clearTurnCapture();
      setStatus("unavailable");
      return;
    }

    if (paused || turnIdx === null) {
      clearTurnCapture();
      setStatus(paused ? "paused" : "idle");
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
    if (!enableVideoAnalysis) {
      userDisabledCameraRef.current = false;
      activeTurnRef.current = null;
      releaseCamera();
      clearTurnCapture();
      setStatus("disabled");
    }
  }, [clearTurnCapture, enableVideoAnalysis, releaseCamera]);

  useEffect(() => {
    if (!enableVideoAnalysis) return;

    if (turnIdx === null) {
      clearTurnCapture();
      setStatus(cameraOn ? "idle" : "camera_off");
      return;
    }

    if (activeTurnRef.current !== turnIdx) {
      activeTurnRef.current = turnIdx;
      clearTurnCapture();
    }

    if (userDisabledCameraRef.current) {
      setStatus("camera_off");
      return;
    }

    if (!cameraOn) {
      if (startInFlightRef.current) return;
      startInFlightRef.current = true;
      setStatus("starting");
      void startCamera().then((started) => {
        startInFlightRef.current = false;
        if (!started) {
          userDisabledCameraRef.current = true;
          clearTurnCapture();
          setStatus("unavailable");
          return;
        }

        if (paused) {
          clearTurnCapture();
          setStatus("paused");
          return;
        }

        startCapture();
        setStatus("capturing");
      });
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
    startCamera,
    startCapture,
    turnIdx,
  ]);

  return {
    cameraOn,
    videoRef,
    status,
    warning,
    toggleCamera,
    finishTurnCapture,
    clearTurnCapture,
  };
}
