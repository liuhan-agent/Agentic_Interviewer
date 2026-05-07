import { apiUrl } from "@/lib/config";
import type { TraceHealth } from "@/lib/api/types";

export type { TraceHealth };

// ---------------------------------------------------------------------------
// Types mirror the read-only shapes returned by
// ``backend/app/api/v1/admin.py``. They are intentionally permissive
// (most numeric fields are optional) because:
//   - the backend is allowed to add new keys in an additive release;
//   - some fields are ``null`` until the corresponding subsystem has
//     produced at least one sample.
// ---------------------------------------------------------------------------

export interface BanditSnapshot {
  priors: Record<string, { alpha: number; beta: number }>;
  policy_mode?: string;
  exploration_rate?: number;
  decay?: {
    enabled?: boolean;
    factor?: number;
    floor?: number;
    interval_days?: number;
  };
}

export interface DriftPerDimension {
  calls?: number;
  overrides?: number;
  abstains?: number;
  override_rate?: number;
  abstain_rate?: number;
  span_miss_rate?: number;
}

export interface DriftPattern {
  dimension?: string;
  check?: string;
  count?: number;
  sample_evidence?: string[];
  reasons_sample?: string[];
}

export interface VerifierDriftSnapshot {
  enabled?: boolean;
  window_size?: number;
  samples?: number;
  calls?: number;
  overrides?: number;
  abstains?: number;
  override_rate?: number;
  abstain_rate?: number;
  span_miss_rate?: number;
  per_dimension?: Record<string, DriftPerDimension>;
  per_verdict?: Record<string, number>;
  overruled_patterns?: DriftPattern[];
}

export interface AdminSession {
  session_id: string;
  trace_id: string;
  langsmith_run_id?: string | null;
  turn_idx: number;
  asked_turn: number;
  has_question: boolean;
  done: boolean;
  cancelled: boolean;
  created_at: string;
  error: string | null;
}

export interface AdminSessions {
  count: number;
  langsmith?: {
    tracing_enabled?: boolean;
    project?: string;
    web_url?: string;
  };
  sessions: AdminSession[];
}

export interface InterviewSessionHistoryItem {
  session_id: string;
  trace_id?: string | null;
  candidate_name?: string | null;
  job_title?: string | null;
  job_level?: string | null;
  mode?: string | null;
  status: string;
  turn_idx?: number | null;
  asked_turn?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  has_report?: boolean;
  overall_score?: number | null;
  overall_verdict?: string | null;
  trace_count?: number;
  evaluator_trace_count?: number;
  reward_trace_count?: number;
  final_report_trace_count?: number;
  trace_health?: TraceHealth;
  error_kind?: string | null;
  retryable?: boolean;
  cost_summary?: {
    calls?: number;
    stub_calls?: number;
    error_calls?: number;
    prompt_tokens?: number;
    completion_tokens?: number;
    est_usd?: number;
    usage_estimated?: boolean;
  } | null;
}

export interface InterviewSessionHistory {
  count: number;
  sessions: InterviewSessionHistoryItem[];
}

export interface TraceExplorerNode {
  id: number;
  turn_idx?: number | null;
  node: string;
  dimension?: string | null;
  action_id?: string | null;
  policy_id?: string | null;
  context_key?: string | null;
  policy_context_keys?: string[] | null;
  score?: number | null;
  passed?: boolean | null;
  immediate_reward?: number | null;
  immediate_reward_applied?: boolean;
  question?: string | null;
  answer_excerpt?: string | null;
  evaluation?: Record<string, unknown> | null;
  payload?: Record<string, unknown> | null;
  langsmith_run_id?: string | null;
  created_at?: string | null;
}

export interface LangSmithAdminMeta {
  tracing_enabled?: boolean;
  project?: string;
  web_url?: string;
}

export interface TraceDiagnostics {
  health: TraceHealth;
  present_nodes: string[];
  missing_key_nodes: string[];
  last_node?: string | null;
  session_status?: string | null;
}

export interface TraceExplorerResponse {
  session_id: string;
  trace_id?: string | null;
  status?: string | null;
  has_report: boolean;
  overall_score?: number | null;
  langsmith?: LangSmithAdminMeta | null;
  overall_verdict?: string | null;
  trace_count: number;
  evaluator_trace_count: number;
  reward_trace_count: number;
  final_report_trace_count: number;
  trace_health: TraceHealth;
  trace_diagnostics?: TraceDiagnostics | null;
  node_count_total: number;
  nodes_offset: number;
  nodes_limit: number;
  nodes_has_more: boolean;
  nodes: TraceExplorerNode[];
}

export interface Strategy {
  path: string;
  name: string;
  dimensions: string[];
  job_levels: string[];
  description: string;
}

export interface Strategies {
  count: number;
  strategies: Strategy[];
}

export interface BackendHealth {
  status?: string;
  version?: string;
  env?: string;
  llm_provider?: string;
  stub_mode?: string;
  checkpoint_backend?: string;
  langsmith_tracing?: string;
}

// ---------------------------------------------------------------------------
// Token handling
// ---------------------------------------------------------------------------

const ADMIN_TOKEN_KEY = "admin-token";

export function loadAdminToken(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.sessionStorage.getItem(ADMIN_TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function saveAdminToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(ADMIN_TOKEN_KEY, token);
  } catch {
    /* ignore */
  }
}

// ---------------------------------------------------------------------------
// Fetch helpers — narrow wrapper so 401/403 messages read sensibly
// when the operator forgot to configure ``API_TOKEN`` in .env.
// ---------------------------------------------------------------------------

async function adminGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const token = loadAdminToken();
  const res = await fetch(apiUrl(path), {
    signal,
    cache: "no-store",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (res.status === 401) {
    throw new Error(
      "Admin token required. Set it in the panel header; the server rejects unauthenticated reads.",
    );
  }
  if (res.status === 403) {
    throw new Error("Admin token rejected by the server.");
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body || res.statusText}`);
  }
  return (await res.json()) as T;
}

async function publicGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(apiUrl(path), {
    signal,
    cache: "no-store",
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body || res.statusText}`);
  }
  return (await res.json()) as T;
}

async function adminDelete<T>(path: string): Promise<T> {
  const token = loadAdminToken();
  const res = await fetch(apiUrl(path), {
    method: "DELETE",
    headers: token ? { Authorization: `Bearer ${token}` } : undefined,
  });
  if (res.status === 401) {
    throw new Error("Admin token required.");
  }
  if (res.status === 403) {
    throw new Error("Admin token rejected by the server.");
  }
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body || res.statusText}`);
  }
  return (await res.json()) as T;
}

export interface AdminDeleteSessionResponse {
  session_id: string;
  deleted: boolean;
  traces_deleted: number;
  outcome_deleted: boolean;
  checkpoint_deleted?: boolean;
}

export function adminDeleteSession(
  sessionId: string,
): Promise<AdminDeleteSessionResponse> {
  return adminDelete<AdminDeleteSessionResponse>(
    `/admin/interview-sessions/${encodeURIComponent(sessionId)}`,
  );
}

export function getBackendHealth(signal?: AbortSignal): Promise<BackendHealth> {
  return publicGet<BackendHealth>("/health", signal);
}

export function getBanditSnapshot(
  signal?: AbortSignal,
): Promise<BanditSnapshot> {
  return adminGet<BanditSnapshot>("/admin/bandit/snapshot", signal);
}

export function getVerifierDrift(
  signal?: AbortSignal,
): Promise<VerifierDriftSnapshot> {
  return adminGet<VerifierDriftSnapshot>("/admin/drift/verifier", signal);
}

export function getAdminSessions(
  signal?: AbortSignal,
): Promise<AdminSessions> {
  return adminGet<AdminSessions>("/admin/sessions", signal);
}

export function getInterviewSessionsHistory(
  signal?: AbortSignal,
): Promise<InterviewSessionHistory> {
  return adminGet<InterviewSessionHistory>("/admin/interview-sessions", signal);
}

export function getTraceExplorer(
  sessionId: string,
  signal?: AbortSignal,
  options?: { offset?: number; limit?: number },
): Promise<TraceExplorerResponse> {
  const params = new URLSearchParams();
  if (options?.offset) params.set("offset", String(options.offset));
  if (options?.limit) params.set("limit", String(options.limit));
  const qs = params.toString();
  return adminGet<TraceExplorerResponse>(
    `/admin/interview-sessions/${encodeURIComponent(sessionId)}/traces${qs ? `?${qs}` : ""}`,
    signal,
  );
}

export interface TracerHealthSnapshot {
  status: "ok" | "degraded";
  trace_write_success_total: number;
  trace_write_failures_total: number;
  operations: Record<string, { success: number; failures: number }>;
}

export function getTracerHealth(
  signal?: AbortSignal,
): Promise<TracerHealthSnapshot> {
  return adminGet<TracerHealthSnapshot>("/admin/tracer/health", signal);
}

// ---------------------------------------------------------------------------
// Per-kind question/evaluator fallback counters (in-process, since boot).
// Complements the trace-rollup ``FallbackRollUp`` which aggregates the
// last 24h of evaluator fallbacks across sessions: this endpoint is the
// live counter view broken down by *which kind of fallback* fired
// (language rewrite vs. duplicate rewrite vs. safety guardrail vs.
// contract not signed by evaluator vs. evaluator conservative path).
// ---------------------------------------------------------------------------

export type FallbackKind =
  | "language"
  | "duplicate"
  | "safety"
  | "contract_unsigned"
  | "evaluator_fallback";

export const FALLBACK_KIND_ORDER: readonly FallbackKind[] = [
  "safety",
  "language",
  "duplicate",
  "contract_unsigned",
  "evaluator_fallback",
] as const;

export const FALLBACK_KIND_LABELS: Record<FallbackKind, string> = {
  safety: "安全兜底",
  language: "语言兜底",
  duplicate: "重复兜底",
  contract_unsigned: "契约未签",
  evaluator_fallback: "评分兜底",
};

export const FALLBACK_KIND_DESCRIPTIONS: Record<FallbackKind, string> = {
  safety: "guardrail 拦截题面，触发安全兜底重写",
  language: "generator 出英文题被中文兜底重写",
  duplicate: "题面与已问内容相似度过高，被去重重写",
  contract_unsigned: "最终 contract 没拿到 evaluator 签名",
  evaluator_fallback: "evaluator 走保守路径返回兜底评分",
};

export interface FallbackRatesResponse {
  fallback_counts: Record<string, number>;
}

export function getFallbackRates(
  signal?: AbortSignal,
): Promise<FallbackRatesResponse> {
  return adminGet<FallbackRatesResponse>("/admin/fallback-rates", signal);
}

export interface RecentTraceItem {
  id: number;
  session_id: string;
  node: string;
  dimension?: string | null;
  turn_idx?: number | null;
  score?: number | null;
  passed?: boolean | null;
  immediate_reward?: number | null;
  action_id?: string | null;
  context_key?: string | null;
  langsmith_run_id?: string | null;
  created_at?: string | null;
}

export interface RecentTracesResponse {
  node: string;
  limit: number;
  items: RecentTraceItem[];
}

export function getRecentTracesByNode(
  options: { node: string; limit?: number },
  signal?: AbortSignal,
): Promise<RecentTracesResponse> {
  const params = new URLSearchParams({
    node: options.node,
    limit: String(options.limit ?? 50),
  });
  return adminGet<RecentTracesResponse>(
    `/admin/recent-traces?${params.toString()}`,
    signal,
  );
}

export type TraceRollupSince = "1h" | "24h" | "7d" | "30d";
export type TraceRollupGroupBy = "health" | "node" | "verdict" | "fallback";

export interface TraceRollupBucket {
  key: string;
  count: number;
  share: number;
}

export interface TraceRollupResponse {
  since: TraceRollupSince;
  now: string;
  total_sessions: number;
  groupby: TraceRollupGroupBy;
  buckets: TraceRollupBucket[];
  affected_sessions?: number;
  fallback_turns?: number;
  total_turns?: number;
  fallback_rate?: number;
}

export interface EvidenceRollupResponse {
  since: TraceRollupSince;
  now: string;
  total_evaluator_traces: number;
  with_acceptance_checks: number;
  with_evidence_spans: number;
  fallback_traces: number;
  acceptance_check_rate: number;
  evidence_span_rate: number;
  fallback_rate: number;
  total_acceptance_checks: number;
  yes_checks: number;
  unsupported_yes_checks: number;
  unsupported_yes_rate: number;
  evidence_span_total: number;
  evidence_span_none_count: number;
  evidence_span_none_rate: number;
  evidence_quote_total: number;
  avg_evidence_quotes_per_check: number;
  verification_traces: number;
  verification_triggered: number;
  verification_changed: number;
  verification_trigger_rate: number;
  verification_change_rate: number;
}

export interface QuestionQualityRollupResponse {
  since: TraceRollupSince;
  now: string;
  total_ask_question_traces: number;
  with_acceptance_contract: number;
  with_evaluator_signed_contract: number;
  with_retrieval_context: number;
  with_target_skills: number;
  with_skill_focus: number;
  deep_probe_questions: number;
  contract_rate: number;
  evaluator_signed_rate: number;
  retrieval_grounding_rate: number;
  target_skill_rate: number;
  skill_focus_rate: number;
  deep_probe_rate: number;
  avg_acceptance_checks: number;
}

export function getTraceRollUp(
  options?: { since?: TraceRollupSince; groupby?: TraceRollupGroupBy },
  signal?: AbortSignal,
): Promise<TraceRollupResponse> {
  const since = options?.since ?? "24h";
  const groupby = options?.groupby ?? "health";
  const params = new URLSearchParams({ since, groupby });
  return adminGet<TraceRollupResponse>(
    `/admin/trace-rollup?${params.toString()}`,
    signal,
  );
}

export function getEvidenceRollUp(
  options?: { since?: TraceRollupSince },
  signal?: AbortSignal,
): Promise<EvidenceRollupResponse> {
  const since = options?.since ?? "24h";
  const params = new URLSearchParams({ since });
  return adminGet<EvidenceRollupResponse>(
    `/admin/evidence-rollup?${params.toString()}`,
    signal,
  );
}

export function getQuestionQualityRollUp(
  options?: { since?: TraceRollupSince },
  signal?: AbortSignal,
): Promise<QuestionQualityRollupResponse> {
  const since = options?.since ?? "24h";
  const params = new URLSearchParams({ since });
  return adminGet<QuestionQualityRollupResponse>(
    `/admin/question-quality-rollup?${params.toString()}`,
    signal,
  );
}

export function getStrategies(signal?: AbortSignal): Promise<Strategies> {
  return adminGet<Strategies>("/admin/strategies", signal);
}

// ---------------------------------------------------------------------------
// Workflow Decision Chain
// ---------------------------------------------------------------------------

export interface WorkflowDirector {
  action_id?: string | null;
  action_label?: string | null;
  context_key?: string | null;
  exploration?: string | null;
  allowed_arms?: string[] | null;
  posterior_mean?: Record<string, number> | null;
  runner_up?: string | null;
  target_difficulty?: string | null;
}

export interface WorkflowEvaluator {
  score?: number | null;
  passed?: boolean | null;
  immediate_reward?: number | null;
  strengths?: string[] | null;
  weaknesses?: string[] | null;
  question?: string | null;
  answer_excerpt?: string | null;
}

export interface WorkflowReward {
  reward_value?: number | null;
  reward_source?: string | null;
  skipped?: boolean | null;
  skip_reason?: string | null;
}

export interface WorkflowVerifier {
  original_passed?: boolean | null;
  final_passed?: boolean | null;
  overruled?: boolean;
  confidence?: number | null;
  rationale?: string | null;
}

export interface WorkflowTurn {
  turn_idx: number;
  dimension?: string | null;
  director?: WorkflowDirector | null;
  evaluator?: WorkflowEvaluator | null;
  reward?: WorkflowReward | null;
  verifier?: WorkflowVerifier | null;
}

export interface WorkflowChainResponse {
  session_id: string;
  status?: string | null;
  turn_count: number;
  turns: WorkflowTurn[];
}

export function getWorkflowChain(
  sessionId: string,
  signal?: AbortSignal,
): Promise<WorkflowChainResponse> {
  return adminGet<WorkflowChainResponse>(
    `/admin/interview-sessions/${encodeURIComponent(sessionId)}/workflow-chain`,
    signal,
  );
}

// ---------------------------------------------------------------------------
// RAG Evaluation
// ---------------------------------------------------------------------------

export interface RagEvalResponse {
  window: string;
  total_evaluator_traces: number;
  with_retrieval: number;
  without_retrieval: number;
  retrieval_rate: number;
  avg_score_with_retrieval: number;
  avg_score_without_retrieval: number;
  score_delta: number;
  per_dimension: Record<string, { with: number; without: number }>;
}

export function getRagEval(
  options?: { since?: string },
  signal?: AbortSignal,
): Promise<RagEvalResponse> {
  const since = options?.since ?? "7d";
  const params = new URLSearchParams({ since });
  return adminGet<RagEvalResponse>(
    `/admin/rag/eval?${params.toString()}`,
    signal,
  );
}

// ---------------------------------------------------------------------------
// Trace Annotations (Human Review)
// ---------------------------------------------------------------------------

export type AnnotationType = "bad_question" | "wrong_score" | "rag_miss" | "verifier_error" | "other";
export type AnnotationVerdict = "flagged" | "approved" | "corrected";

export interface TraceAnnotationItem {
  id: number;
  trace_id: string;
  session_id: string;
  turn_idx: number;
  generation_trace_id?: number | null;
  node?: string | null;
  annotation_type: AnnotationType;
  verdict: AnnotationVerdict;
  notes?: string | null;
  reviewer?: string | null;
  created_at?: string | null;
}

export interface AnnotationsListResponse {
  count: number;
  annotations: TraceAnnotationItem[];
}

export interface AnnotationStatsResponse {
  total: number;
  by_type: Record<string, number>;
  by_verdict: Record<string, number>;
}

export interface CreateAnnotationInput {
  trace_id: string;
  session_id: string;
  turn_idx: number;
  generation_trace_id?: number;
  node?: string;
  annotation_type: AnnotationType;
  verdict?: AnnotationVerdict;
  notes?: string;
  reviewer?: string;
}

async function adminPost<T>(path: string, body: unknown): Promise<T> {
  const token = loadAdminToken();
  const res = await fetch(apiUrl(path), {
    method: "POST",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
  });
  if (res.status === 401) {
    throw new Error("Admin token required.");
  }
  if (res.status === 403) {
    throw new Error("Admin token rejected.");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text || res.statusText}`);
  }
  return (await res.json()) as T;
}

export function createAnnotation(input: CreateAnnotationInput): Promise<{ id: number; ok: boolean }> {
  return adminPost<{ id: number; ok: boolean }>("/admin/annotations", input);
}

export function getAnnotations(
  options?: { session_id?: string; annotation_type?: string; limit?: number },
  signal?: AbortSignal,
): Promise<AnnotationsListResponse> {
  const params = new URLSearchParams();
  if (options?.session_id) params.set("session_id", options.session_id);
  if (options?.annotation_type) params.set("annotation_type", options.annotation_type);
  if (options?.limit) params.set("limit", String(options.limit));
  return adminGet<AnnotationsListResponse>(
    `/admin/annotations?${params.toString()}`,
    signal,
  );
}

export function getAnnotationStats(signal?: AbortSignal): Promise<AnnotationStatsResponse> {
  return adminGet<AnnotationStatsResponse>("/admin/annotations/stats", signal);
}
