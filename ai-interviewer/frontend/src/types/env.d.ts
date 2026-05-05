declare namespace NodeJS {
  interface ProcessEnv {
    /**
     * Base URL of the FastAPI backend.  Leave empty for same-origin
     * deployments (dev uses ``next.config.mjs`` rewrites to proxy to
     * http://localhost:8000).
     */
    NEXT_PUBLIC_API_BASE?: string;
  }
}
