import { request } from "./client";
import type { AuthRequest, AuthState } from "./types";

const BASE = "/api/v1/auth";

export function getMe(): Promise<AuthState> {
  return request(`${BASE}/me`);
}

export function register(input: AuthRequest): Promise<AuthState> {
  return request(`${BASE}/register`, {
    method: "POST",
    body: input,
  });
}

export function login(input: AuthRequest): Promise<AuthState> {
  return request(`${BASE}/login`, {
    method: "POST",
    body: input,
  });
}

export function logout(): Promise<{ ok: boolean }> {
  return request(`${BASE}/logout`, {
    method: "POST",
  });
}
