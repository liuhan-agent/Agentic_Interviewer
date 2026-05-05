import { ApiError, request } from "./client";
import type {
  AnswerRequest,
  DeleteSessionResponse,
  GetReportResponse,
  HintRequest,
  HintResponse,
  JobTemplateResponse,
  ListDirectionsResponse,
  ListDimensionsResponse,
  LLMConfigPayload,
  ParseJobSpecResponse,
  ParseResumeResponse,
  PollQuestionResponse,
  ReplayResponse,
  RetryQuestionResponse,
  ResumeResponse,
  SkipQuestionRequest,
  SkipQuestionResponse,
  StartSessionRequest,
  StartSessionResponse,
  SubmitFeedbackRequest,
  SubmitFeedbackResponse,
  VoiceTicketResponse,
} from "./types";
import { jobTemplateRequestPath } from "@/lib/job-template";
import { buildLLMPayload } from "@/lib/llm-config";
import { getSessionToken } from "@/lib/storage/interviewHistory";

const BASE = "/api/v1/interview";

function sessionHeaders(sessionId: string): HeadersInit | undefined {
  const token = getSessionToken(sessionId);
  return token ? { "X-Session-Token": token } : undefined;
}

export function isReauthRequired(err: unknown): boolean {
  if (!(err instanceof ApiError)) return false;
  if (err.status !== 409) return false;
  const body = err.body;
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail?: unknown }).detail;
    if (detail && typeof detail === "object" && "error" in detail) {
      return (detail as { error?: unknown }).error === "reauth_required";
    }
    if (typeof detail === "string") {
      return detail.includes("reauth_required");
    }
  }
  return err.message.includes("reauth_required");
}

export function startSession(
  req: StartSessionRequest,
): Promise<StartSessionResponse> {
  return request(`${BASE}/sessions`, { method: "POST", body: req });
}

/**
 * Upload a PDF / DOCX / TXT resume and receive the parsed
 * structured resume shape back. The frontend uses this to pre-fill
 * the SetupForm; the user can still edit every field.
 *
 * Server cap is 5 MB; the LLM-side extraction may take a while on
 * stronger models, so we extend the soft timeout above the default 35s. Optional
 * `llmConfig` is sent as a JSON multipart field; API keys are not
 * stored by the backend.
 */
export function parseResume(
  file: File,
  llmConfig?: LLMConfigPayload,
): Promise<ParseResumeResponse> {
  const fd = new FormData();
  fd.append("file", file, file.name);
  if (llmConfig) {
    fd.append("llm_config", JSON.stringify(llmConfig));
  }
  return request(`${BASE}/resume/parse`, {
    method: "POST",
    body: fd,
    timeoutMs: 90_000,
  });
}

/**
 * Send a free-text job description (plus optional title/level) and
 * receive the inferred required skills + rubric dimensions back.
 * This lets the SetupForm hide engineering jargon from job-seekers
 * while still feeding the LangGraph workflow a usable rubric.
 */
export function parseJobSpec(args: {
  text: string;
  direction?: string;
  title?: string;
  level?: string;
  llmConfig?: LLMConfigPayload;
}): Promise<ParseJobSpecResponse> {
  const { llmConfig, ...body } = args;
  return request(`${BASE}/jd/parse`, {
    method: "POST",
    body: llmConfig ? { ...body, llm_config: llmConfig } : body,
    timeoutMs: 60_000,
  });
}

/** Editable generic JD template for the selected setup direction. */
export function getJobTemplate(args: {
  direction: string;
  level?: string;
}): Promise<JobTemplateResponse> {
  return request(jobTemplateRequestPath(args));
}

/** Static catalog used by the dimension picker. */
export function listDimensions(): Promise<ListDimensionsResponse> {
  return request(`${BASE}/dimensions`);
}

/** Static direction catalog used by the setup flow. */
export function listDirections(): Promise<ListDirectionsResponse> {
  return request(`${BASE}/directions`);
}

export function pollQuestion(
  sessionId: string,
  opts: { timeout?: number; signal?: AbortSignal } = {},
): Promise<PollQuestionResponse> {
  const timeout = opts.timeout ?? 30;
  return request(
    `${BASE}/sessions/${encodeURIComponent(sessionId)}/question?timeout=${timeout}`,
    // Server will block up to ``timeout`` seconds; give the client a
    // margin above that so AbortController does not fire first.
    {
      headers: sessionHeaders(sessionId),
      signal: opts.signal,
      timeoutMs: (timeout + 5) * 1000,
    },
  );
}

export function submitAnswer(
  sessionId: string,
  answer: string,
  turnIdx: number,
  videoSignals?: Record<string, unknown>,
): Promise<{ session_id: string; accepted: boolean }> {
  const llmConfig = buildLLMPayload();
  const body: AnswerRequest = { answer, turn_idx: turnIdx };
  if (videoSignals) body.video_signals = videoSignals;
  if (llmConfig) body.llm_config = llmConfig;
  return request(`${BASE}/sessions/${encodeURIComponent(sessionId)}/answer`, {
    method: "POST",
    headers: sessionHeaders(sessionId),
    body,
  });
}

export function skipQuestion(
  sessionId: string,
  turnIdx: number,
  reason?: string,
): Promise<SkipQuestionResponse> {
  const body: SkipQuestionRequest = { turn_idx: turnIdx };
  if (reason) body.reason = reason;
  return request(`${BASE}/sessions/${encodeURIComponent(sessionId)}/skip-question`, {
    method: "POST",
    headers: sessionHeaders(sessionId),
    body,
  });
}

export function requestHint(
  sessionId: string,
  turnIdx: number,
  llmConfig?: LLMConfigPayload,
): Promise<HintResponse> {
  const effectiveLLMConfig = llmConfig ?? buildLLMPayload();
  const body: HintRequest = { turn_idx: turnIdx };
  if (effectiveLLMConfig) body.llm_config = effectiveLLMConfig;
  return request(`${BASE}/sessions/${encodeURIComponent(sessionId)}/hint`, {
    method: "POST",
    headers: sessionHeaders(sessionId),
    body,
  });
}

export function createVoiceTicket(sessionId: string): Promise<VoiceTicketResponse> {
  return request(
    `${BASE}/sessions/${encodeURIComponent(sessionId)}/voice-ticket`,
    { method: "POST", headers: sessionHeaders(sessionId) },
  );
}

export function retryFailedQuestion(
  sessionId: string,
): Promise<RetryQuestionResponse> {
  return request(
    `${BASE}/sessions/${encodeURIComponent(sessionId)}/retry-question`,
    { method: "POST", headers: sessionHeaders(sessionId) },
  );
}

export function deleteSession(sessionId: string): Promise<DeleteSessionResponse> {
  const encoded = encodeURIComponent(sessionId);
  return request(
    `${BASE}/sessions/${encoded}?confirm_session_id=${encodeURIComponent(sessionId)}`,
    { method: "DELETE", headers: sessionHeaders(sessionId) },
  );
}

export function getReport(sessionId: string): Promise<GetReportResponse> {
  return request(`${BASE}/sessions/${encodeURIComponent(sessionId)}/report`, {
    headers: sessionHeaders(sessionId),
  });
}

export function getReplay(sessionId: string): Promise<ReplayResponse> {
  return request(`${BASE}/sessions/${encodeURIComponent(sessionId)}/replay`, {
    headers: sessionHeaders(sessionId),
  });
}

export function resumeSession(sessionId: string): Promise<ResumeResponse> {
  return request(`${BASE}/sessions/${encodeURIComponent(sessionId)}/resume`, {
    headers: sessionHeaders(sessionId),
  });
}

export function submitFeedback(
  sessionId: string,
  body: SubmitFeedbackRequest,
): Promise<SubmitFeedbackResponse> {
  return request(
    `${BASE}/sessions/${encodeURIComponent(sessionId)}/feedback`,
    { method: "POST", headers: sessionHeaders(sessionId), body },
  );
}
