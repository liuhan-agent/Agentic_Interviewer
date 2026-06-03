import { apiUrl } from "@/lib/config";

const FASTAPI_FIELD_LABELS: Record<string, string> = {
  email: "邮箱",
  password: "密码",
};

export class ApiError extends Error {
  readonly status: number;
  readonly body?: unknown;
  readonly code?: string;
  readonly action?: string;

  constructor(
    status: number,
    message: string,
    body?: unknown,
    code?: string,
    action?: string,
  ) {
    super(message);
    this.status = status;
    this.body = body;
    this.code = code;
    this.action = action;
    this.name = "ApiError";
  }
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  /**
   * JSON-serialisable body, or a `FormData` instance for multipart
   * uploads. When `FormData` is passed we let the browser set the
   * `Content-Type` header (including the boundary) automatically.
   */
  body?: unknown;
  headers?: HeadersInit;
  signal?: AbortSignal;
  /** Soft ceiling on how long we'll wait.  Default 35s (> server long-poll). */
  timeoutMs?: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function formatValidationLocation(loc: unknown): string | null {
  if (!Array.isArray(loc)) return null;
  const parts = loc
    .filter((part): part is string | number => {
      return typeof part === "string" || typeof part === "number";
    })
    .filter((part) => part !== "body")
    .map((part) => FASTAPI_FIELD_LABELS[String(part)] ?? String(part));
  return parts.length > 0 ? parts.join(".") : null;
}

function formatValidationMessage(message: string): string {
  if (message.includes("invalid email")) return "邮箱格式不正确";
  if (message.includes("at least 8")) return "至少 8 位";
  if (message.includes("at most 128")) return "最多 128 位";
  return message;
}

function formatFastApiValidationDetail(detail: unknown): string | null {
  if (!Array.isArray(detail)) return null;
  const messages = detail
    .map((issue) => {
      if (!isRecord(issue)) return null;
      const rawMessage =
        typeof issue.msg === "string"
          ? issue.msg
          : typeof issue.message === "string"
            ? issue.message
            : null;
      if (!rawMessage) return null;
      const location = formatValidationLocation(issue.loc);
      const message = formatValidationMessage(rawMessage);
      return location ? `${location}: ${message}` : message;
    })
    .filter((message): message is string => Boolean(message));
  return messages.length > 0 ? messages.join("; ") : null;
}

function formatStructuredApiMessage(
  code: string | undefined,
  fallback: string,
): string {
  if (code === "registration_closed") return "当前暂未开放新账号注册。";
  if (code === "rate_limit_exceeded") return "请求过于频繁，请稍后再试。";
  return fallback;
}

export async function request<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { method = "GET", body, headers, signal, timeoutMs = 35_000 } = options;

  const controller = new AbortController();
  const timeoutHandle = window.setTimeout(
    () => controller.abort(new DOMException("timeout", "AbortError")),
    timeoutMs,
  );
  const onExternalAbort = () => controller.abort(signal?.reason);
  // Chain caller-supplied abort signal onto ours so cancellation from
  // hooks (e.g. StrictMode double mount) actually short-circuits.
  if (signal) {
    if (signal.aborted) controller.abort(signal.reason);
    signal.addEventListener("abort", onExternalAbort);
  }

  const isFormData = typeof FormData !== "undefined" && body instanceof FormData;
  const fetchBody: BodyInit | undefined = isFormData
    ? (body as FormData)
    : body
      ? JSON.stringify(body)
      : undefined;
  const fetchHeaders = new Headers(headers);
  if (!isFormData && body) {
    fetchHeaders.set("Content-Type", "application/json");
  }
  const hasHeaders = Array.from(fetchHeaders.keys()).length > 0;

  try {
    const res = await fetch(apiUrl(path), {
      method,
      headers: hasHeaders ? fetchHeaders : undefined,
      body: fetchBody,
      signal: controller.signal,
      cache: "no-store",
      credentials: "include",
    });

    const text = await res.text();
    let parsed: unknown = null;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = text;
      }
    }

    if (!res.ok) {
      const detail =
        parsed && typeof parsed === "object" && "detail" in parsed
          ? (parsed as { detail: unknown }).detail
          : undefined;
      const detailObject =
        detail && typeof detail === "object"
          ? (detail as { code?: unknown; action?: unknown; error?: unknown; message?: unknown })
          : undefined;
      const code = typeof detailObject?.code === "string" ? detailObject.code : undefined;
      const action =
        typeof detailObject?.action === "string" ? detailObject.action : undefined;
      const validationMessage = formatFastApiValidationDetail(detail);
      const fallbackMessage =
        (detailObject && typeof detailObject.error === "string"
          ? detailObject.error
          : detailObject && typeof detailObject.message === "string"
            ? detailObject.message
            : validationMessage
              ? validationMessage
              : detail
              ? String(detail)
              : typeof parsed === "string"
                ? parsed
                : res.statusText) || `HTTP ${res.status}`;
      const msg = formatStructuredApiMessage(code, fallbackMessage);
      throw new ApiError(res.status, msg, parsed, code, action);
    }

    return parsed as T;
  } finally {
    window.clearTimeout(timeoutHandle);
    if (signal) {
      signal.removeEventListener("abort", onExternalAbort);
    }
  }
}
