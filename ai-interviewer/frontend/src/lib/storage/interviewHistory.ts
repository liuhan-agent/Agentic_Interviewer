/**
 * 本地面试历史索引（A+ 方案，纯前端 localStorage）。
 *
 * 设计要点：
 * - SSR-safe：所有读写都先判断 `typeof window`。
 * - 静默容错：localStorage 不可用 / JSON 损坏 → 视为空，绝不抛错。
 * - 包一层 `{ version, entries }` 便于将来无痛迁移。
 * - 与已有 `lastSessionId` 共存：每次 upsert 也写一份，旧 ResumeHero 不会回退。
 */

const STORAGE_KEY = "interviewHistory";
const LEGACY_LAST_KEY = "lastSessionId";
const SESSION_TOKEN_KEY_PREFIX = "interviewSessionToken:";
const SCHEMA_VERSION = 1;
export const SESSION_TOKEN_TTL_DAYS = 7;
const SESSION_TOKEN_TTL_MS = SESSION_TOKEN_TTL_DAYS * 24 * 60 * 60 * 1000;
const MAX_TEXT_FIELD_LENGTH = 256;
const MAX_DIMENSION_COUNT = 20;
const MAX_DIMENSION_LENGTH = 80;
const MAX_RESUME_TEXT_LENGTH = 20_000;
const MAX_RESUME_ARRAY_LENGTH = 40;

export type InterviewHistoryStatus = "running" | "done" | "cancelled" | "failed";

export interface InterviewHistoryEntry {
  sessionId: string;
  sessionToken?: string;
  sessionTokenExpiresAt?: string;
  recoveryToken?: string;
  recoveryTokenExpiresAt?: string;
  ownerUserId?: number;
  ownerClaimedAt?: string;
  jdTitle: string;
  candidateName?: string;
  jobLevel?: string;
  rubricDimensions?: string[];
  createdAt: string;
  lastVisitedAt: string;
  updatedAt?: string;
  status: InterviewHistoryStatus;
  overallScore?: number;
  dimensionScores?: Record<string, number>;
  maxTurns?: number;
  growthSignal?: string;
  overallVerdict?: string;
  feedbackSubmitted?: boolean;
  resumeSetupSnapshot?: ResumeSetupSnapshot;
}

export interface ResumeSetupSnapshot {
  candidate_name?: string;
  candidate_summary?: string;
  candidate_skills?: string;
  candidate_highlights?: string;
  resumeProjects?: Record<string, unknown>[];
  resumeFocusAreas?: Record<string, unknown>[];
  resumeConcerns?: string[];
  resumeCandidateProfile?: Record<string, unknown>;
}

interface StoredShape {
  version: number;
  entries: InterviewHistoryEntry[];
}

function isBrowser(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function canUseSessionStorage(): boolean {
  return typeof window !== "undefined" && typeof window.sessionStorage !== "undefined";
}

function sessionTokenKey(sessionId: string): string {
  return `${SESSION_TOKEN_KEY_PREFIX}${sessionId}`;
}

export function writeSessionToken(
  sessionId: string,
  token: string,
  expiresAt: string,
): void {
  if (!canUseSessionStorage()) return;
  try {
    window.sessionStorage.setItem(
      sessionTokenKey(sessionId),
      JSON.stringify({ token, expiresAt }),
    );
  } catch {
    /* ignore */
  }
}

function removeSessionToken(sessionId: string): void {
  if (!canUseSessionStorage()) return;
  try {
    window.sessionStorage.removeItem(sessionTokenKey(sessionId));
  } catch {
    /* ignore */
  }
}

function clearAllSessionTokens(): void {
  if (!canUseSessionStorage()) return;
  try {
    const keys: string[] = [];
    for (let i = 0; i < window.sessionStorage.length; i += 1) {
      const key = window.sessionStorage.key(i);
      if (key?.startsWith(SESSION_TOKEN_KEY_PREFIX)) {
        keys.push(key);
      }
    }
    for (const key of keys) {
      window.sessionStorage.removeItem(key);
    }
  } catch {
    /* ignore */
  }
}

function readSessionToken(sessionId: string, now = Date.now()): string | undefined {
  if (!canUseSessionStorage()) return undefined;
  try {
    const raw = window.sessionStorage.getItem(sessionTokenKey(sessionId));
    if (!raw) return undefined;
    const parsed = JSON.parse(raw) as { token?: unknown; expiresAt?: unknown };
    if (typeof parsed.token !== "string" || typeof parsed.expiresAt !== "string") {
      removeSessionToken(sessionId);
      return undefined;
    }
    const expiresAt = Date.parse(parsed.expiresAt);
    if (!Number.isFinite(expiresAt) || expiresAt <= now) {
      removeSessionToken(sessionId);
      return undefined;
    }
    return parsed.token;
  } catch {
    removeSessionToken(sessionId);
    return undefined;
  }
}

function readRaw(): StoredShape {
  if (!isBrowser()) return { version: SCHEMA_VERSION, entries: [] };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { version: SCHEMA_VERSION, entries: [] };
    const parsed = JSON.parse(raw) as unknown;
    if (
      parsed &&
      typeof parsed === "object" &&
      "entries" in parsed &&
      Array.isArray((parsed as StoredShape).entries)
    ) {
      const shape = parsed as StoredShape;
      // Filter out malformed entries; never throw on partial data.
      const entries = shape.entries.filter(isValidEntry);
      return { version: SCHEMA_VERSION, entries };
    }
    return { version: SCHEMA_VERSION, entries: [] };
  } catch {
    return { version: SCHEMA_VERSION, entries: [] };
  }
}

function writeRaw(shape: StoredShape): void {
  if (!isBrowser()) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(shape));
  } catch {
    // Quota exceeded / private mode → silently drop. We never block the UI.
  }
}

function isValidEntry(x: unknown): x is InterviewHistoryEntry {
  if (!x || typeof x !== "object") return false;
  const e = x as Record<string, unknown>;
  return (
    typeof e.sessionId === "string" &&
    (e.sessionToken === undefined || typeof e.sessionToken === "string") &&
    (e.sessionTokenExpiresAt === undefined ||
      typeof e.sessionTokenExpiresAt === "string") &&
    (e.recoveryToken === undefined || typeof e.recoveryToken === "string") &&
    (e.recoveryTokenExpiresAt === undefined ||
      typeof e.recoveryTokenExpiresAt === "string") &&
    isValidOwnerUserId(e.ownerUserId) &&
    (e.ownerClaimedAt === undefined || isValidIsoDate(e.ownerClaimedAt)) &&
    isTextField(e.jdTitle) &&
    (e.candidateName === undefined || isTextField(e.candidateName)) &&
    (e.jobLevel === undefined || isTextField(e.jobLevel)) &&
    (e.growthSignal === undefined || isTextField(e.growthSignal)) &&
    (e.overallVerdict === undefined || isTextField(e.overallVerdict)) &&
    isValidIsoDate(e.createdAt) &&
    isValidIsoDate(e.lastVisitedAt) &&
    (e.updatedAt === undefined || isValidIsoDate(e.updatedAt)) &&
    isValidScore(e.overallScore) &&
    isDimensionScoreMap(e.dimensionScores) &&
    isValidPositiveInt(e.maxTurns) &&
    isStringList(e.rubricDimensions) &&
    isResumeSetupSnapshot(e.resumeSetupSnapshot) &&
    (e.status === "running" ||
      e.status === "done" ||
      e.status === "cancelled" ||
      e.status === "failed") &&
    (e.feedbackSubmitted === undefined || typeof e.feedbackSubmitted === "boolean")
  );
}

function isTextField(value: unknown): value is string {
  return typeof value === "string" && value.length <= MAX_TEXT_FIELD_LENGTH;
}

function isValidIsoDate(value: unknown): value is string {
  if (typeof value !== "string") return false;
  return Number.isFinite(Date.parse(value));
}

function isoOrUndefined(value: unknown): string | undefined {
  return isValidIsoDate(value) ? value : undefined;
}

function isValidScore(value: unknown): value is number | undefined {
  if (value === undefined) return true;
  return (
    typeof value === "number" &&
    Number.isFinite(value) &&
    value >= 0 &&
    value <= 10
  );
}

function isValidPositiveInt(value: unknown): value is number | undefined {
  if (value === undefined) return true;
  return typeof value === "number" && Number.isInteger(value) && value > 0 && value <= 30;
}

function isValidOwnerUserId(value: unknown): value is number | undefined {
  if (value === undefined) return true;
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function isDimensionScoreMap(
  value: unknown,
): value is Record<string, number> | undefined {
  if (value === undefined) return true;
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length > MAX_DIMENSION_COUNT) return false;
  return entries.every(
    ([key, score]) =>
      key.length <= MAX_DIMENSION_LENGTH && isValidScore(score),
  );
}

function isStringList(value: unknown): value is string[] | undefined {
  if (value === undefined) return true;
  if (!Array.isArray(value) || value.length > MAX_DIMENSION_COUNT) return false;
  return value.every(
    (item) => typeof item === "string" && item.length <= MAX_DIMENSION_LENGTH,
  );
}

function isResumeText(value: unknown): value is string | undefined {
  return (
    value === undefined ||
    (typeof value === "string" && value.length <= MAX_RESUME_TEXT_LENGTH)
  );
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isRecordList(value: unknown): value is Record<string, unknown>[] | undefined {
  if (value === undefined) return true;
  return (
    Array.isArray(value) &&
    value.length <= MAX_RESUME_ARRAY_LENGTH &&
    value.every(isPlainObject)
  );
}

function isResumeConcernList(value: unknown): value is string[] | undefined {
  if (value === undefined) return true;
  return (
    Array.isArray(value) &&
    value.length <= MAX_RESUME_ARRAY_LENGTH &&
    value.every(
      (item) =>
        typeof item === "string" && item.length <= MAX_RESUME_TEXT_LENGTH,
    )
  );
}

function isResumeSetupSnapshot(
  value: unknown,
): value is ResumeSetupSnapshot | undefined {
  if (value === undefined) return true;
  if (!isPlainObject(value)) return false;
  return (
    isResumeText(value.candidate_summary) &&
    isResumeText(value.candidate_name) &&
    isResumeText(value.candidate_skills) &&
    isResumeText(value.candidate_highlights) &&
    isRecordList(value.resumeProjects) &&
    isRecordList(value.resumeFocusAreas) &&
    isResumeConcernList(value.resumeConcerns) &&
    (value.resumeCandidateProfile === undefined ||
      isPlainObject(value.resumeCandidateProfile))
  );
}

function sortByCreatedAtDesc(entries: InterviewHistoryEntry[]): InterviewHistoryEntry[] {
  return [...entries].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

function isExpiredToken(entry: InterviewHistoryEntry, now = Date.now()): boolean {
  if (!entry.sessionToken || !entry.sessionTokenExpiresAt) return false;
  const expiresAt = Date.parse(entry.sessionTokenExpiresAt);
  return !Number.isFinite(expiresAt) || expiresAt <= now;
}

function isExpiredRecoveryToken(entry: InterviewHistoryEntry, now = Date.now()): boolean {
  if (!entry.recoveryToken || !entry.recoveryTokenExpiresAt) return false;
  const expiresAt = Date.parse(entry.recoveryTokenExpiresAt);
  return !Number.isFinite(expiresAt) || expiresAt <= now;
}

function withoutSessionToken(entry: InterviewHistoryEntry): InterviewHistoryEntry {
  const next = { ...entry };
  delete next.sessionToken;
  delete next.sessionTokenExpiresAt;
  return next;
}

function withoutRecoveryToken(entry: InterviewHistoryEntry): InterviewHistoryEntry {
  const next = { ...entry };
  delete next.recoveryToken;
  delete next.recoveryTokenExpiresAt;
  return next;
}

function pruneExpiredSessionTokens(shape: StoredShape): StoredShape {
  let changed = false;
  const now = Date.now();
  const entries = shape.entries.map((entry) => {
    let next = entry;
    if (next.sessionToken) {
      if (!isExpiredToken(next, now)) {
        const expiresAt =
          next.sessionTokenExpiresAt ??
          new Date(now + SESSION_TOKEN_TTL_MS).toISOString();
        writeSessionToken(next.sessionId, next.sessionToken, expiresAt);
      } else {
        removeSessionToken(next.sessionId);
      }
      changed = true;
      next = withoutSessionToken(next);
    }
    if (next.recoveryToken && isExpiredRecoveryToken(next, now)) {
      changed = true;
      next = withoutRecoveryToken(next);
    }
    return next;
  });
  const next = changed ? { version: SCHEMA_VERSION, entries } : shape;
  if (changed) writeRaw(next);
  return next;
}

export function getHistory(): InterviewHistoryEntry[] {
  return sortByCreatedAtDesc(pruneExpiredSessionTokens(readRaw()).entries);
}

export function getEntry(sessionId: string): InterviewHistoryEntry | null {
  return pruneExpiredSessionTokens(readRaw()).entries.find(
    (e) => e.sessionId === sessionId,
  ) ?? null;
}

export function getSessionToken(sessionId: string): string | undefined {
  pruneExpiredSessionTokens(readRaw());
  return readSessionToken(sessionId);
}

export function getRecoveryToken(sessionId: string): string | undefined {
  const entry = getEntry(sessionId);
  if (!entry?.recoveryToken || isExpiredRecoveryToken(entry)) {
    return undefined;
  }
  return entry.recoveryToken;
}

export function getResumeSetupSnapshot(
  sessionId: string,
): ResumeSetupSnapshot | null {
  return getEntry(sessionId)?.resumeSetupSnapshot ?? null;
}

export interface UpsertInput {
  sessionId: string;
  sessionToken?: string;
  sessionTokenExpiresAt?: string;
  recoveryToken?: string;
  recoveryTokenExpiresAt?: string;
  ownerUserId?: number;
  ownerClaimedAt?: string;
  jdTitle?: string;
  candidateName?: string;
  jobLevel?: string;
  rubricDimensions?: string[];
  createdAt?: string;
  updatedAt?: string;
  status?: InterviewHistoryStatus;
  overallScore?: number;
  dimensionScores?: Record<string, number>;
  maxTurns?: number;
  growthSignal?: string;
  overallVerdict?: string;
  feedbackSubmitted?: boolean;
  resumeSetupSnapshot?: ResumeSetupSnapshot;
}

/**
 * Insert if missing, otherwise shallow-merge non-undefined fields. Always
 * refreshes `lastVisitedAt`. Returns the resulting entry.
 */
export function upsertEntry(input: UpsertInput): InterviewHistoryEntry {
  const now = new Date().toISOString();
  const shape = pruneExpiredSessionTokens(readRaw());
  const existingIdx = shape.entries.findIndex((e) => e.sessionId === input.sessionId);
  const sessionTokenExpiresAt = input.sessionToken
    ? input.sessionTokenExpiresAt ?? new Date(Date.now() + SESSION_TOKEN_TTL_MS).toISOString()
    : undefined;
  if (input.sessionToken && sessionTokenExpiresAt) {
    writeSessionToken(input.sessionId, input.sessionToken, sessionTokenExpiresAt);
  }

  let next: InterviewHistoryEntry;
  if (existingIdx >= 0) {
    const prev = shape.entries[existingIdx];
    next = {
      ...prev,
      ...stripUndefined({
        jdTitle: input.jdTitle,
        candidateName: input.candidateName,
        jobLevel: input.jobLevel,
        rubricDimensions: input.rubricDimensions,
        createdAt: isoOrUndefined(input.createdAt),
        updatedAt: isoOrUndefined(input.updatedAt),
        recoveryToken: input.recoveryToken,
        recoveryTokenExpiresAt: input.recoveryTokenExpiresAt,
        ownerUserId: input.ownerUserId,
        ownerClaimedAt: isoOrUndefined(input.ownerClaimedAt),
        status: input.status,
        overallScore: input.overallScore,
        dimensionScores: input.dimensionScores,
        maxTurns: input.maxTurns,
        growthSignal: input.growthSignal,
        overallVerdict: input.overallVerdict,
        feedbackSubmitted: input.feedbackSubmitted,
        resumeSetupSnapshot: input.resumeSetupSnapshot,
      }),
      lastVisitedAt: now,
    };
    shape.entries[existingIdx] = next;
  } else {
    next = {
      sessionId: input.sessionId,
      jdTitle: input.jdTitle ?? "未命名面试",
      candidateName: input.candidateName,
      jobLevel: input.jobLevel,
      rubricDimensions: input.rubricDimensions,
      recoveryToken: input.recoveryToken,
      recoveryTokenExpiresAt: input.recoveryTokenExpiresAt,
      ownerUserId: input.ownerUserId,
      ownerClaimedAt: isoOrUndefined(input.ownerClaimedAt),
      createdAt: isoOrUndefined(input.createdAt) ?? now,
      updatedAt: isoOrUndefined(input.updatedAt),
      lastVisitedAt: now,
      status: input.status ?? "running",
      overallScore: input.overallScore,
      dimensionScores: input.dimensionScores,
      maxTurns: input.maxTurns,
      growthSignal: input.growthSignal,
      overallVerdict: input.overallVerdict,
      resumeSetupSnapshot: input.resumeSetupSnapshot,
    };
    shape.entries.push(next);
  }

  writeRaw({ version: SCHEMA_VERSION, entries: shape.entries });

  // Keep the legacy single-session pointer in sync so older code paths still work.
  if (isBrowser()) {
    try {
      window.localStorage.setItem(LEGACY_LAST_KEY, input.sessionId);
    } catch {
      /* ignore */
    }
  }

  return next;
}

export interface ServerEntryMetadataInput {
  sessionId: string;
  createdAt?: string;
  updatedAt?: string;
  jdTitle?: string | null;
  candidateName?: string | null;
  jobLevel?: string | null;
  status?: InterviewHistoryStatus;
  overallScore?: number | null;
  dimensionScores?: Record<string, number>;
  growthSignal?: string | null;
  overallVerdict?: string | null;
  ownerUserId?: number | null;
  ownerClaimedAt?: string | null;
}

export function mergeServerEntryMetadata(
  input: ServerEntryMetadataInput,
): InterviewHistoryEntry | null {
  const shape = pruneExpiredSessionTokens(readRaw());
  const idx = shape.entries.findIndex((e) => e.sessionId === input.sessionId);
  if (idx < 0) return null;

  const prev = shape.entries[idx];
  const next: InterviewHistoryEntry = {
    ...prev,
    ...stripUndefined({
      createdAt: isoOrUndefined(input.createdAt),
      updatedAt: isoOrUndefined(input.updatedAt),
      jdTitle: normaliseTextInput(input.jdTitle),
      candidateName: normaliseTextInput(input.candidateName),
      jobLevel: normaliseTextInput(input.jobLevel),
      status: input.status,
      overallScore:
        typeof input.overallScore === "number" ? input.overallScore : undefined,
      dimensionScores: input.dimensionScores,
      growthSignal: normaliseTextInput(input.growthSignal),
      overallVerdict: normaliseTextInput(input.overallVerdict),
      ownerUserId:
        typeof input.ownerUserId === "number" ? input.ownerUserId : undefined,
      ownerClaimedAt: isoOrUndefined(input.ownerClaimedAt),
    }),
  };
  shape.entries[idx] = next;
  writeRaw(shape);
  return next;
}

export function touchVisited(sessionId: string): void {
  const shape = pruneExpiredSessionTokens(readRaw());
  const idx = shape.entries.findIndex((e) => e.sessionId === sessionId);
  if (idx < 0) return;
  shape.entries[idx] = {
    ...shape.entries[idx],
    lastVisitedAt: new Date().toISOString(),
  };
  writeRaw(shape);
}

export function removeEntry(sessionId: string): void {
  const shape = pruneExpiredSessionTokens(readRaw());
  const next = shape.entries.filter((e) => e.sessionId !== sessionId);
  writeRaw({ version: SCHEMA_VERSION, entries: next });
  removeSessionToken(sessionId);

  if (!isBrowser()) return;
  try {
    if (window.localStorage.getItem(LEGACY_LAST_KEY) === sessionId) {
      window.localStorage.removeItem(LEGACY_LAST_KEY);
    }
  } catch {
    /* ignore */
  }
}

export function clearAll(): void {
  clearAllSessionTokens();
  writeRaw({ version: SCHEMA_VERSION, entries: [] });
  if (!isBrowser()) return;
  try {
    window.localStorage.removeItem(LEGACY_LAST_KEY);
  } catch {
    /* ignore */
  }
}

/**
 * Find the most recent `running` entry (used by ResumeHero). Returns the most
 * recently visited if multiple are running.
 */
export function getMostRecentRunning(): InterviewHistoryEntry | null {
  const running = pruneExpiredSessionTokens(readRaw()).entries.filter(
    (e) => e.status === "running",
  );
  if (running.length === 0) return null;
  running.sort((a, b) => b.lastVisitedAt.localeCompare(a.lastVisitedAt));
  return running[0];
}

/**
 * Return the most recent ``done`` entry strictly older than ``sessionId``.
 *
 * Used by the report page to render a "vs 上一次练习" delta without
 * requiring a backend round-trip. Falls back to ``null`` when:
 * - localStorage is unavailable / corrupted (handled by ``getHistory``)
 * - no other completed session exists
 * - ``sessionId`` is unknown locally; then we degrade to "no previous"
 *   rather than picking an arbitrary done entry, which would lie about
 *   the chronology in the user's other-tab history.
 */
export function getCompletedBefore(
  sessionId: string,
): InterviewHistoryEntry | null {
  let history: InterviewHistoryEntry[] = [];
  try {
    history = getHistory();
  } catch {
    return null;
  }
  const target = history.find((e) => e.sessionId === sessionId);
  const candidates = history.filter(
    (e) => e.status === "done" && e.sessionId !== sessionId,
  );
  if (candidates.length === 0) return null;
  candidates.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  if (!target) return null;
  return (
    candidates.find((e) => e.createdAt < target.createdAt) ?? null
  );
}

function stripUndefined<T extends Record<string, unknown>>(obj: T): Partial<T> {
  const out: Partial<T> = {};
  for (const [k, v] of Object.entries(obj)) {
    if (v !== undefined) (out as Record<string, unknown>)[k] = v;
  }
  return out;
}

function normaliseTextInput(value: string | null | undefined): string | undefined {
  if (typeof value !== "string") return undefined;
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}
