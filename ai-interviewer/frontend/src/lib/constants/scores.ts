/**
 * Score thresholds shared across the report / progress / setup
 * surfaces (audit finding F5).
 *
 * Previously ``buildWeakPracticeHref`` used a literal ``score >= 7``
 * to filter strong dims while ``buildLastSessionDelta`` ranked dims
 * by ``Math.abs(delta)`` only. Two utilities, two implicit
 * thresholds — easy for the report and the progress chart to drift.
 *
 * Centralising the magic numbers means a single source of truth
 * the report card, history page, and any future "progress-aware"
 * widget can agree on. **Do not inline these numbers anywhere
 * else.**
 */

/**
 * Dim is considered "weak" (recommend practice) below this score.
 * Mirrors the historical ``score >= 7`` filter in ProgressChart.
 */
export const WEAK_DIMENSION_THRESHOLD = 7;

/**
 * Dim is considered "strong" (skip recommendation) at or above this
 * score. Reserved for future "celebrate strong dim" UX (currently
 * unused — kept here so callers don't reinvent another magic number
 * when we surface it).
 */
export const STRONG_DIMENSION_THRESHOLD = 8.5;
