/**
 * Runtime configuration.  Non-local deployments can set
 * ``NEXT_PUBLIC_API_BASE`` to call a separate API origin directly.
 * In local browser sessions we prefer the same-origin Next.js rewrite
 * for HTTP APIs even when the env var points at another loopback host.
 * This keeps auth cookies tied to the currently opened frontend host
 * (``localhost`` vs ``127.0.0.1``) and avoids refresh-time login loss.
 */
export const API_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_BASE) || "";

function isLoopbackHost(hostname: string): boolean {
  return (
    hostname === "localhost" ||
    hostname === "127.0.0.1" ||
    hostname === "::1" ||
    hostname === "[::1]"
  );
}

function shouldUseSameOriginProxy(base: string): boolean {
  if (!base || typeof window === "undefined") return false;
  try {
    const target = new URL(base);
    return (
      isLoopbackHost(window.location.hostname) &&
      isLoopbackHost(target.hostname)
    );
  } catch {
    return false;
  }
}

export function apiUrl(path: string): string {
  if (!path.startsWith("/")) path = "/" + path;
  if (path.startsWith("/ws/")) {
    return API_BASE ? `${API_BASE}${path}` : path;
  }
  if (shouldUseSameOriginProxy(API_BASE)) return path;
  if (!API_BASE) return path;
  return `${API_BASE}${path}`;
}
