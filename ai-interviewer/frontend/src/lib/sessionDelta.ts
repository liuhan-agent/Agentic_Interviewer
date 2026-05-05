/**
 * Session delta + growth hints helpers — used by the single-report
 * "vs 上一次练习" widget and the cross-session "GrowthHints" widget.
 *
 * Lives in a pure-TS module (no JSX, no @/ aliases, no React imports)
 * so it can be exercised by ``node --test`` without a bundler. Both
 * the report widget and any future analytics consumer can import it.
 *
 * Inspired by Hermes Agent's "episodic memory" pattern (audit
 * cross-reference): instead of letting every dim trend stay implicit,
 * we surface "持续薄弱" / "连续提升" patterns explicitly so the user
 * sees what's persisting across practice sessions, not just the last
 * delta.
 */

import { WEAK_DIMENSION_THRESHOLD } from "./constants/scores.ts";

const DIMENSION_LABELS: Record<string, string> = {
  technical_depth: "技术深度",
  problem_solving: "问题解决",
  communication: "沟通表达",
  system_design: "系统设计",
  coding_quality: "代码质量",
  project_experience: "项目经验",
  product_thinking: "产品思维",
  customer_discovery: "客户发现",
  architecture: "架构能力",
  behavioral: "行为面试",
  leadership: "技术领导力",
};

export type SessionDeltaEntry = {
  dimension: string;
  label: string;
  delta: number;
};

export type SessionDelta = {
  overall: number | null;
  dimensions: SessionDeltaEntry[];
};

export type SessionDeltaInput = {
  overallScore?: number | null;
  dimensionScores?: Record<string, number> | null;
};

/**
 * Compute a "vs 上一次练习" delta for the report page.
 *
 * Returns ``null`` when there is no signal at all (no overall delta and
 * no shared dimension scores) so the caller can skip rendering the
 * widget entirely. The dimensions are sorted by absolute delta so the
 * UI can surface the largest movements first; capped at 3 entries to
 * avoid widget bloat.
 */
export function buildLastSessionDelta(
  current: SessionDeltaInput,
  previous: SessionDeltaInput | null,
): SessionDelta | null {
  if (!previous) return null;
  const overall =
    typeof current.overallScore === "number" &&
    typeof previous.overallScore === "number"
      ? Number((current.overallScore - previous.overallScore).toFixed(1))
      : null;
  const prevDims = previous.dimensionScores ?? {};
  const currDims = current.dimensionScores ?? {};
  const dimensions = Object.keys(currDims)
    .filter(
      (dim) =>
        typeof prevDims[dim] === "number" && typeof currDims[dim] === "number",
    )
    .map((dim) => ({
      dimension: dim,
      label: DIMENSION_LABELS[dim] ?? dim.replaceAll("_", " "),
      delta: Number((currDims[dim] - prevDims[dim]).toFixed(1)),
    }))
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
    .slice(0, 3);
  if (overall === null && dimensions.length === 0) return null;
  return { overall, dimensions };
}

// ---------------------------------------------------------------------------
// GrowthHints — cross-session episodic signals
// ---------------------------------------------------------------------------

const PERSISTENT_WEAK_MIN_SESSIONS = 3;
const CONSECUTIVE_IMPROVE_MIN_SESSIONS = 2;

export type GrowthHints = {
  persistentWeak: SessionDeltaEntry[];
  consecutiveImprove: SessionDeltaEntry[];
};

type HistoryLike = { dimensionScores?: Record<string, number> };

/**
 * Compute cross-session "持续薄弱" + "连续提升" signals.
 *
 * Returns ``null`` when the history is too short (< 3 sessions with
 * any dim score) or when no signal emerges. Both lists are capped at
 * 3 entries; when the same dim qualifies as both weak and improving
 * we **prefer the improving label** to avoid contradictory narrative.
 *
 * @param history Most-recent-first history entries from
 *   ``getHistory()``. Only entries with a ``dimensionScores`` map
 *   participate.
 * @param weakThreshold Override the score threshold (default 7,
 *   matching ``WEAK_DIMENSION_THRESHOLD``).
 */
export function buildGrowthHints(
  history: HistoryLike[],
  weakThreshold: number = WEAK_DIMENSION_THRESHOLD,
): GrowthHints | null {
  const scored = history
    .filter((entry) => entry?.dimensionScores)
    .map((entry) => entry.dimensionScores ?? {});
  if (scored.length < PERSISTENT_WEAK_MIN_SESSIONS) return null;

  const dims = new Set<string>();
  for (const map of scored) {
    for (const key of Object.keys(map)) dims.add(key);
  }

  const persistentWeak: SessionDeltaEntry[] = [];
  const consecutiveImprove: SessionDeltaEntry[] = [];

  for (const dim of dims) {
    const recent = scored
      .map((map) => map[dim])
      .filter((v): v is number => typeof v === "number" && Number.isFinite(v));
    if (recent.length < PERSISTENT_WEAK_MIN_SESSIONS) continue;

    const lastN = recent.slice(0, PERSISTENT_WEAK_MIN_SESSIONS);
    const allWeak = lastN.every((s) => s < weakThreshold);
    const last = recent[0];
    const prev = recent[1];
    const isImproving =
      typeof last === "number" &&
      typeof prev === "number" &&
      last - prev > 0 &&
      recent.length >= CONSECUTIVE_IMPROVE_MIN_SESSIONS;

    if (isImproving) {
      consecutiveImprove.push({
        dimension: dim,
        label: DIMENSION_LABELS[dim] ?? dim.replaceAll("_", " "),
        delta: Number((last - prev).toFixed(1)),
      });
    } else if (allWeak) {
      persistentWeak.push({
        dimension: dim,
        label: DIMENSION_LABELS[dim] ?? dim.replaceAll("_", " "),
        delta: Number(lastN[0].toFixed(1)),
      });
    }
  }

  // Cap each side at 3 entries so the widget stays compact.
  persistentWeak.sort((a, b) => a.delta - b.delta);
  consecutiveImprove.sort((a, b) => b.delta - a.delta);
  const out: GrowthHints = {
    persistentWeak: persistentWeak.slice(0, 3),
    consecutiveImprove: consecutiveImprove.slice(0, 3),
  };
  if (out.persistentWeak.length === 0 && out.consecutiveImprove.length === 0) {
    return null;
  }
  return out;
}
