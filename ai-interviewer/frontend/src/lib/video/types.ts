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
    confidence: Math.round(avgConfidence * 100) / 100,
    engagement: Math.round(avgEngagement * 100) / 100,
    dominant_emotion: dominantEmotion,
    sample_count: signals.length,
  };
}
