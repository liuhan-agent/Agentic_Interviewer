/**
 * Runtime configuration.  When ``NEXT_PUBLIC_API_BASE`` is set (either
 * in ``.env.local`` or via the deployment env), all API calls go
 * directly to that origin.  When it is unset we keep the default
 * same-origin setup, which makes the Next.js ``rewrites`` in
 * ``next.config.mjs`` proxy the requests to the FastAPI backend on
 * ``:8000`` during development.
 */
export const API_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_API_BASE) || "";

export function apiUrl(path: string): string {
  if (!path.startsWith("/")) path = "/" + path;
  if (!API_BASE) return path;
  return `${API_BASE}${path}`;
}
