"use client";

import { type RefObject, useEffect, useState } from "react";

type AudioGraph = {
  context: AudioContext;
  source: MediaElementAudioSourceNode;
  analyser: AnalyserNode;
  data: Uint8Array<ArrayBuffer>;
};

type AudioContextWindow = Window &
  typeof globalThis & {
    webkitAudioContext?: typeof AudioContext;
  };

const graphs = new WeakMap<HTMLAudioElement, AudioGraph>();

function getAudioContextConstructor() {
  if (typeof window === "undefined") return null;
  return window.AudioContext ?? (window as AudioContextWindow).webkitAudioContext ?? null;
}

function getAudioGraph(audio: HTMLAudioElement): AudioGraph | null {
  const existing = graphs.get(audio);
  if (existing) return existing;

  const AudioContextCtor = getAudioContextConstructor();
  if (!AudioContextCtor) return null;

  try {
    const context = new AudioContextCtor();
    const source = context.createMediaElementSource(audio);
    const analyser = context.createAnalyser();
    analyser.fftSize = 128;
    source.connect(analyser);
    analyser.connect(context.destination);
    const graph = {
      context,
      source,
      analyser,
      data: new Uint8Array(new ArrayBuffer(analyser.frequencyBinCount)),
    };
    graphs.set(audio, graph);
    return graph;
  } catch {
    return null;
  }
}

export function useLipSync(
  audioElementRef: RefObject<HTMLAudioElement | null> | undefined,
  active: boolean,
) {
  const [mouthOpen, setMouthOpen] = useState(0);
  const [available, setAvailable] = useState(false);

  useEffect(() => {
    if (!active) {
      setMouthOpen(0);
      setAvailable(false);
      return;
    }

    const audio = audioElementRef?.current;
    if (!audio) {
      setMouthOpen(0.35);
      setAvailable(false);
      return;
    }

    const graph = getAudioGraph(audio);
    if (!graph) {
      setMouthOpen(0.35);
      setAvailable(false);
      return;
    }

    let frame = 0;
    let stopped = false;
    setAvailable(true);

    if (graph.context.state === "suspended") {
      graph.context.resume().catch(() => undefined);
    }

    const tick = () => {
      if (stopped) return;
      graph.analyser.getByteFrequencyData(graph.data);
      const total = graph.data.reduce((sum, value) => sum + value, 0);
      const average = total / Math.max(1, graph.data.length);
      setMouthOpen(Math.max(0.08, Math.min(1, average / 96)));
      frame = requestAnimationFrame(tick);
    };

    frame = requestAnimationFrame(tick);
    return () => {
      stopped = true;
      cancelAnimationFrame(frame);
    };
  }, [active, audioElementRef]);

  return { mouthOpen, available };
}
