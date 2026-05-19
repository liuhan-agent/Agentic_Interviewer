export interface VideoSignal {
  confidence: number;
  engagement: number;
  emotion: "neutral" | "positive" | "nervous" | "confused";
  timestamp: number;
}

export interface AggregatedVideoSignal {
  confidence: number;
  engagement: number;
  dominant_emotion: string;
  sample_count: number;
}

const VIDEO_EMOTIONS = new Set(["neutral", "positive", "nervous", "confused"]);

function isUnitScore(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
}

function roundSignalScore(value: number): number {
  return Math.round(value * 100) / 100;
}

export function isAggregatedVideoSignal(
  value: unknown,
): value is AggregatedVideoSignal {
  if (!value || typeof value !== "object") return false;
  const signal = value as Partial<AggregatedVideoSignal>;

  return (
    isUnitScore(signal.confidence) &&
    isUnitScore(signal.engagement) &&
    typeof signal.dominant_emotion === "string" &&
    VIDEO_EMOTIONS.has(signal.dominant_emotion) &&
    Number.isInteger(signal.sample_count) &&
    Number(signal.sample_count) > 0
  );
}

export function mergeAggregatedVideoSignals(
  signals: Array<AggregatedVideoSignal | null | undefined>,
): AggregatedVideoSignal | null {
  const validSignals = signals.filter(isAggregatedVideoSignal);
  const totalSamples = validSignals.reduce(
    (sum, signal) => sum + signal.sample_count,
    0,
  );

  if (totalSamples <= 0) return null;

  const weightedConfidence =
    validSignals.reduce(
      (sum, signal) => sum + signal.confidence * signal.sample_count,
      0,
    ) / totalSamples;
  const weightedEngagement =
    validSignals.reduce(
      (sum, signal) => sum + signal.engagement * signal.sample_count,
      0,
    ) / totalSamples;

  const emotionCounts = new Map<string, number>();
  for (const signal of validSignals) {
    emotionCounts.set(
      signal.dominant_emotion,
      (emotionCounts.get(signal.dominant_emotion) ?? 0) + signal.sample_count,
    );
  }

  let dominantEmotion = "neutral";
  let maxCount = 0;
  for (const [emotion, count] of emotionCounts) {
    if (count > maxCount) {
      maxCount = count;
      dominantEmotion = emotion;
    }
  }

  return {
    confidence: roundSignalScore(weightedConfidence),
    engagement: roundSignalScore(weightedEngagement),
    dominant_emotion: dominantEmotion,
    sample_count: totalSamples,
  };
}

export function aggregateSignals(
  signals: VideoSignal[],
): AggregatedVideoSignal | null {
  if (signals.length === 0) return null;

  const avgConfidence =
    signals.reduce((sum, s) => sum + s.confidence, 0) / signals.length;
  const avgEngagement =
    signals.reduce((sum, s) => sum + s.engagement, 0) / signals.length;

  const emotionCounts = new Map<string, number>();
  for (const s of signals) {
    emotionCounts.set(s.emotion, (emotionCounts.get(s.emotion) ?? 0) + 1);
  }
  let dominantEmotion = "neutral";
  let maxCount = 0;
  for (const [emotion, count] of emotionCounts) {
    if (count > maxCount) {
      maxCount = count;
      dominantEmotion = emotion;
    }
  }

  return {
    confidence: roundSignalScore(avgConfidence),
    engagement: roundSignalScore(avgEngagement),
    dominant_emotion: dominantEmotion,
    sample_count: signals.length,
  };
}
