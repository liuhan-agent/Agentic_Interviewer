export type SetupDraftStatus =
  | "parsing"
  | "ready"
  | "basic_ready"
  | "failed"
  | "expired";

export interface SetupDraft {
  draftId: string;
  jobId: string;
  filename: string;
  status: SetupDraftStatus;
  createdAt: string;
  updatedAt: string;
  expiresAt?: string;
}

type SetupDraftInput = Omit<SetupDraft, "createdAt" | "updatedAt"> &
  Partial<Pick<SetupDraft, "createdAt" | "updatedAt">>;

const SETUP_DRAFTS_KEY = "setupDrafts";

function browserStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage ?? null;
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function isValidDate(value: string | undefined): boolean {
  if (!value) return true;
  return Number.isFinite(Date.parse(value));
}

function isExpired(draft: SetupDraft, now = Date.now()): boolean {
  if (!draft.expiresAt) return false;
  const time = Date.parse(draft.expiresAt);
  return Number.isFinite(time) && time <= now;
}

function normaliseDraft(value: unknown): SetupDraft | null {
  if (!isRecord(value)) return null;
  const draftId = typeof value.draftId === "string" ? value.draftId : "";
  const jobId = typeof value.jobId === "string" ? value.jobId : "";
  const filename = typeof value.filename === "string" ? value.filename : "";
  const status = typeof value.status === "string" ? value.status : "";
  const createdAt = typeof value.createdAt === "string" ? value.createdAt : "";
  const updatedAt = typeof value.updatedAt === "string" ? value.updatedAt : "";
  const expiresAt = typeof value.expiresAt === "string" ? value.expiresAt : undefined;
  if (!draftId || !jobId || !filename || !createdAt || !updatedAt) return null;
  if (!["parsing", "ready", "basic_ready", "failed", "expired"].includes(status)) {
    return null;
  }
  if (!isValidDate(createdAt) || !isValidDate(updatedAt) || !isValidDate(expiresAt)) {
    return null;
  }
  return {
    draftId,
    jobId,
    filename,
    status: status as SetupDraftStatus,
    createdAt,
    updatedAt,
    ...(expiresAt ? { expiresAt } : {}),
  };
}

function readRawDrafts(): SetupDraft[] {
  const storage = browserStorage();
  if (!storage) return [];
  try {
    const raw = storage.getItem(SETUP_DRAFTS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    const values = Array.isArray(parsed)
      ? parsed
      : isRecord(parsed) && Array.isArray(parsed.drafts)
        ? parsed.drafts
        : [];
    return values
      .map(normaliseDraft)
      .filter((draft): draft is SetupDraft => draft !== null);
  } catch {
    return [];
  }
}

function writeDrafts(drafts: SetupDraft[]): void {
  const storage = browserStorage();
  if (!storage) return;
  try {
    storage.setItem(
      SETUP_DRAFTS_KEY,
      JSON.stringify({
        version: 1,
        drafts,
      }),
    );
  } catch {
    /* localStorage may be full or unavailable; setup remains usable. */
  }
}

export function getSetupDrafts(): SetupDraft[] {
  const drafts = readRawDrafts();
  const active = drafts.filter((draft) => !isExpired(draft));
  if (active.length !== drafts.length) {
    writeDrafts(active);
  }
  return active.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
}

export function getSetupDraft(draftId: string): SetupDraft | null {
  return getSetupDrafts().find((draft) => draft.draftId === draftId) ?? null;
}

export function getMostRecentSetupDraft(): SetupDraft | null {
  return getSetupDrafts()[0] ?? null;
}

export function upsertSetupDraft(input: SetupDraftInput): SetupDraft {
  const now = new Date().toISOString();
  const drafts = getSetupDrafts();
  const existing = drafts.find((draft) => draft.draftId === input.draftId);
  const next: SetupDraft = {
    draftId: input.draftId,
    jobId: input.jobId,
    filename: input.filename,
    status: input.status,
    createdAt: input.createdAt ?? existing?.createdAt ?? now,
    updatedAt: input.updatedAt ?? now,
    ...(input.expiresAt ? { expiresAt: input.expiresAt } : {}),
  };
  writeDrafts([
    next,
    ...drafts.filter((draft) => draft.draftId !== input.draftId),
  ]);
  return next;
}

export function removeSetupDraft(draftId: string): void {
  writeDrafts(getSetupDrafts().filter((draft) => draft.draftId !== draftId));
}
