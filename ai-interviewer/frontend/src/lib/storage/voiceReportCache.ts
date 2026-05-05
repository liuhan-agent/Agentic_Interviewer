import type { FinalReport } from "@/lib/api/types";

const VOICE_REPORT_PREFIX = "voice-report:";

type VoiceReportStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function voiceReportCacheKey(sessionId: string): string {
  return `${VOICE_REPORT_PREFIX}${sessionId}`;
}

export function storeVoiceReportCache(
  sessionId: string,
  report: FinalReport | null,
  storage: VoiceReportStorage | null = getSessionStorage(),
): void {
  if (!storage || !report) return;
  try {
    storage.setItem(voiceReportCacheKey(sessionId), JSON.stringify(report));
  } catch {
    /* ignore storage failures */
  }
}

export function readVoiceReportCache(
  sessionId: string,
  storage: VoiceReportStorage | null = getSessionStorage(),
): FinalReport | null {
  if (!storage) return null;
  const key = voiceReportCacheKey(sessionId);
  try {
    const raw = storage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (isFinalReportForSession(parsed, sessionId)) {
      return parsed;
    }
    storage.removeItem(key);
    return null;
  } catch {
    try {
      storage.removeItem(key);
    } catch {
      /* ignore cleanup failures */
    }
    return null;
  }
}

export function clearVoiceReportCache(
  sessionId: string,
  storage: VoiceReportStorage | null = getSessionStorage(),
): void {
  if (!storage) return;
  try {
    storage.removeItem(voiceReportCacheKey(sessionId));
  } catch {
    /* ignore cleanup failures */
  }
}

function getSessionStorage(): VoiceReportStorage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

function isFinalReportForSession(
  value: unknown,
  sessionId: string,
): value is FinalReport {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return false;
  }
  const reportSessionId = (value as { session_id?: unknown }).session_id;
  return reportSessionId === undefined || reportSessionId === sessionId;
}
