"use client";

import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import { analyzeFrame, preloadFaceMesh } from "@/lib/video/faceAnalyzer";
import {
  aggregateSignals,
  type AggregatedVideoSignal,
  type VideoSignal,
} from "@/lib/video/types";

const CAPTURE_INTERVAL_MS = 3000;

export interface UseFaceCaptureReturn {
  cameraOn: boolean;
  videoRef: RefObject<HTMLVideoElement>;
  startCamera: () => Promise<boolean>;
  releaseCamera: () => void;
  toggleCamera: () => Promise<void>;
  startCapture: () => void;
  stopCapture: () => AggregatedVideoSignal | null;
  resetCapture: () => void;
  cameraError: string | null;
  analysisWarning: string | null;
}

export function useFaceCapture(): UseFaceCaptureReturn {
  const [cameraOn, setCameraOn] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [analysisWarning, setAnalysisWarning] = useState<string | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const signalBufferRef = useRef<VideoSignal[]>([]);
  const captureIntervalRef = useRef<ReturnType<typeof setInterval> | null>(
    null,
  );

  const clearCaptureInterval = useCallback(() => {
    if (!captureIntervalRef.current) return;
    clearInterval(captureIntervalRef.current);
    captureIntervalRef.current = null;
  }, []);

  const resetCapture = useCallback(() => {
    signalBufferRef.current = [];
  }, []);

  const startCamera = useCallback(async (): Promise<boolean> => {
    if (streamRef.current) {
      if (videoRef.current) videoRef.current.srcObject = streamRef.current;
      setCameraOn(true);
      setCameraError(null);
      return true;
    }

    if (typeof navigator === "undefined" || !navigator.mediaDevices) {
      setCameraOn(false);
      setCameraError("摄像头不可用，不影响继续面试。");
      setAnalysisWarning(null);
      return false;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) videoRef.current.srcObject = stream;
      setCameraOn(true);
      setCameraError(null);

      const canAnalyze = await preloadFaceMesh();
      setAnalysisWarning(
        canAnalyze ? null : "摄像头可用，本地表情分析暂不可用。",
      );
      return true;
    } catch {
      setCameraOn(false);
      setCameraError("摄像头权限被拒绝或设备不可用，不影响继续面试。");
      setAnalysisWarning(null);
      return false;
    }
  }, []);

  const releaseCamera = useCallback(() => {
    clearCaptureInterval();
    resetCapture();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setCameraOn(false);
    setCameraError(null);
    setAnalysisWarning(null);
  }, [clearCaptureInterval, resetCapture]);

  const startCapture = useCallback(() => {
    if (!videoRef.current || !streamRef.current) return;
    clearCaptureInterval();
    resetCapture();
    captureIntervalRef.current = setInterval(async () => {
      if (!videoRef.current) return;
      try {
        const result = await analyzeFrame(videoRef.current);
        if (result.ok) signalBufferRef.current.push(result.signal);
      } catch {
        setAnalysisWarning("视频分析暂不可用，不影响继续面试。");
      }
    }, CAPTURE_INTERVAL_MS);
  }, [clearCaptureInterval, resetCapture]);

  const stopCapture = useCallback((): AggregatedVideoSignal | null => {
    clearCaptureInterval();
    return aggregateSignals(signalBufferRef.current);
  }, [clearCaptureInterval]);

  const toggleCamera = useCallback(async () => {
    if (cameraOn) {
      releaseCamera();
      return;
    }
    await startCamera();
  }, [cameraOn, releaseCamera, startCamera]);

  useEffect(() => {
    if (videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
    }
  }, [cameraOn]);

  useEffect(() => {
    return () => {
      clearCaptureInterval();
      signalBufferRef.current = [];
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    };
  }, [clearCaptureInterval]);

  return {
    cameraOn,
    videoRef,
    startCamera,
    releaseCamera,
    toggleCamera,
    startCapture,
    stopCapture,
    resetCapture,
    cameraError,
    analysisWarning,
  };
}
