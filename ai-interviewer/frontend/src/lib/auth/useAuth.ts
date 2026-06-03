"use client";

import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import * as authApi from "@/lib/api/auth";
import type { AuthState } from "@/lib/api/types";

const ANON_STATE: AuthState = { authenticated: false, user: null };
const AUTH_STATE_CACHE_KEY = "aiInterviewerAuthState";
const AUTH_STATE_CACHE_TTL_MS = 14 * 24 * 60 * 60 * 1000;

interface CachedAuthState {
  cachedAt: number;
  state: AuthState;
}

export interface AuthContextValue extends AuthState {
  loading: boolean;
  pending: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  login: (email: string, password: string) => Promise<AuthState>;
  register: (email: string, password: string) => Promise<AuthState>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function canUseLocalStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function isValidCachedAuthState(value: unknown): value is CachedAuthState {
  if (!value || typeof value !== "object") return false;
  const cached = value as CachedAuthState;
  const user = cached.state?.user;
  return (
    typeof cached.cachedAt === "number" &&
    Number.isFinite(cached.cachedAt) &&
    cached.state?.authenticated === true &&
    user !== null &&
    typeof user === "object" &&
    typeof user.id === "number" &&
    typeof user.email === "string" &&
    typeof user.role === "string" &&
    typeof user.status === "string" &&
    typeof user.email_verified === "boolean"
  );
}

function readCachedAuthState(now = Date.now()): AuthState | null {
  if (!canUseLocalStorage()) return null;
  try {
    const raw = window.localStorage.getItem(AUTH_STATE_CACHE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (!isValidCachedAuthState(parsed)) {
      window.localStorage.removeItem(AUTH_STATE_CACHE_KEY);
      return null;
    }
    if (now - parsed.cachedAt > AUTH_STATE_CACHE_TTL_MS) {
      window.localStorage.removeItem(AUTH_STATE_CACHE_KEY);
      return null;
    }
    return parsed.state;
  } catch {
    return null;
  }
}

function writeCachedAuthState(state: AuthState): void {
  if (!canUseLocalStorage()) return;
  try {
    if (!state.authenticated || !state.user) {
      clearCachedAuthState();
      return;
    }
    window.localStorage.setItem(
      AUTH_STATE_CACHE_KEY,
      JSON.stringify({ cachedAt: Date.now(), state }),
    );
  } catch {
    // UI cache only; auth authority remains the HttpOnly cookie.
  }
}

function clearCachedAuthState(): void {
  if (!canUseLocalStorage()) return;
  try {
    window.localStorage.removeItem(AUTH_STATE_CACHE_KEY);
  } catch {
    /* ignore */
  }
}

function useAuthState(): AuthContextValue {
  const [state, setState] = useState<AuthState>(ANON_STATE);
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const next = await authApi.getMe();
      setState(next);
      if (next.authenticated) {
        writeCachedAuthState(next);
      } else {
        clearCachedAuthState();
      }
      setError(null);
    } catch (err) {
      setState(ANON_STATE);
      clearCachedAuthState();
      setError(err instanceof Error ? err.message : "账号状态读取失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const cached = readCachedAuthState();
    if (cached) setState(cached);
    void refresh();
  }, [refresh]);

  const login = useCallback(async (email: string, password: string) => {
    setPending(true);
    try {
      const next = await authApi.login({ email, password });
      setState(next);
      writeCachedAuthState(next);
      setError(null);
      return next;
    } catch (err) {
      const message = err instanceof Error ? err.message : "登录失败";
      setError(message);
      throw err;
    } finally {
      setPending(false);
    }
  }, []);

  const register = useCallback(async (email: string, password: string) => {
    setPending(true);
    try {
      const next = await authApi.register({ email, password });
      setState(next);
      writeCachedAuthState(next);
      setError(null);
      return next;
    } catch (err) {
      const message = err instanceof Error ? err.message : "注册失败";
      setError(message);
      throw err;
    } finally {
      setPending(false);
    }
  }, []);

  const logout = useCallback(async () => {
    setPending(true);
    try {
      await authApi.logout();
      setState(ANON_STATE);
      clearCachedAuthState();
      setError(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : "退出失败";
      setError(message);
      throw err;
    } finally {
      setPending(false);
    }
  }, []);

  return useMemo(
    () => ({
      ...state,
      loading,
      pending,
      error,
      refresh,
      login,
      register,
      logout,
    }),
    [state, loading, pending, error, refresh, login, register, logout],
  );
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const value = useAuthState();
  return createElement(AuthContext.Provider, { value }, children);
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
}
