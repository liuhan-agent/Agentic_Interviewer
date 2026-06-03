import { request } from "./client";
import type {
  AccountCreditPolicy,
  AccountCreditRequestsResponse,
  AccountCreditsResponse,
  AccountInterviewSessionsResponse,
  CreateAccountCreditRequestResponse,
} from "./types";

const BASE = "/api/v1/account";

export function getAccountInterviewSessions(
  params: { limit?: number; offset?: number } = {},
): Promise<AccountInterviewSessionsResponse> {
  const search = new URLSearchParams();
  if (typeof params.limit === "number") {
    search.set("limit", String(params.limit));
  }
  if (typeof params.offset === "number") {
    search.set("offset", String(params.offset));
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return request(`${BASE}/interview-sessions${suffix}`);
}

export function getAccountCreditPolicy(): Promise<AccountCreditPolicy> {
  return request(`${BASE}/credit-policy`);
}

export function getAccountCredits(): Promise<AccountCreditsResponse> {
  return request(`${BASE}/credits`);
}

export function getAccountCreditRequests(
  params: { limit?: number; offset?: number } = {},
): Promise<AccountCreditRequestsResponse> {
  const search = new URLSearchParams();
  if (typeof params.limit === "number") {
    search.set("limit", String(params.limit));
  }
  if (typeof params.offset === "number") {
    search.set("offset", String(params.offset));
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return request(`${BASE}/credit-requests${suffix}`);
}

export function createAccountCreditRequest(input: {
  requested_amount: number;
  reason: string;
}): Promise<CreateAccountCreditRequestResponse> {
  return request(`${BASE}/credit-requests`, {
    method: "POST",
    body: input,
  });
}
