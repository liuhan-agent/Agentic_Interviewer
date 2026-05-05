import { apiUrl } from "@/lib/config";

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
      const msg =
        (detailObject && typeof detailObject.error === "string"
          ? detailObject.error
          : detailObject && typeof detailObject.message === "string"
            ? detailObject.message
            : detail
              ? String(detail)
              : typeof parsed === "string"
                ? parsed
                : res.statusText) || `HTTP ${res.status}`;
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
