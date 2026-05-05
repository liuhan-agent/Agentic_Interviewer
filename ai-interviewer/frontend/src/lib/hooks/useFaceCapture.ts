"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { analyzeFrame, preloadFaceMesh } from "@/lib/video/faceAnalyzer";
import {
  aggregateSignals,
  type AggregatedVideoSignal,
  type VideoSignal,
} from "@/lib/video/types";

const CAPTURE_INTERVAL_MS = 3000;

export interface UseFaceCaptureReturn {
  cameraOn: boolean;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  toggleCamera: () => Promise<void>;
  startCapture: () => void;
  stopCapture: () => AggregatedVideoSignal | null;
  cameraError: string | null;
  analysisWarning: string | null;
}

export function useFaceCapture(): UseFaceCaptureReturn {
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [analysisWarning, setAnalysisWarning] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const signalBufferRef = useRef<VideoSignal[]>([]);
  const captureIntervalRef = useRef<ReturnType<typeof setInterval> | null>(
    null,
  );

  const startCapture = useCallback(() => {
    if (!videoRef.current) return;
    signalBufferRef.current = [];
    captureIntervalRef.current = setInterval(async () => {
      if (!videoRef.current) return;
      const result = await analyzeFrame(videoRef.current);
      if (result.ok) signalBufferRef.current.push(result.signal);
    }, CAPTURE_INTERVAL_MS);
  }, []);

  const stopCapture = useCallback((): AggregatedVideoSignal | null => {
    if (captureIntervalRef.current) {
      clearInterval(captureIntervalRef.current);
      captureIntervalRef.current = null;
    }
    return aggregateSignals(signalBufferRef.current);
  }, []);

  const toggleCamera = useCallback(async () => {
    if (cameraOn && streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
      setCameraOn(false);
      setCameraError(null);
      setAnalysisWarning(null);
      return;
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
          : "摄像头可用，但本地表情分析暂未加载。你仍可正常作答。",
      );
    } catch {
      setCameraError("摄像头权限被拒绝或设备不可用。");
      setAnalysisWarning(null);
    }
  }, [cameraOn]);

  useEffect(() => {
    if (videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [cameraOn]);

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
      if (captureIntervalRef.current) {
        clearInterval(captureIntervalRef.current);
      }
    };
  }, []);

  return {
    cameraOn,
    videoRef,
    toggleCamera,
    startCapture,
    stopCapture,
    cameraError,
    analysisWarning,
  };
}
