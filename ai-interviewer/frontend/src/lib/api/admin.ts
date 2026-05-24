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
  memory_prior_count?: number;
  persisted_prior_count?: number;
  posterior_source?: string;
  top_posteriors?: Array<{
    context_key?: string;
    action_id?: string;
    alpha?: number;
    beta?: number;
    mean_reward?: number | null;
    observation_count?: number;
    last_reward?: number | null;
    last_reward_kind?: string | null;
    last_session_id?: string | null;
    last_turn_idx?: number | null;
    updated_at?: string | null;
  }>;
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
  total_count?: number;
  limit?: number;
  offset?: number;
  filters?: {
    status?: string | null;
    trace_health?: TraceHealth | null;
    has_report?: boolean | null;
    q?: string | null;
    since?: string | null;
  };
  sessions: InterviewSessionHistoryItem[];
}

export interface InterviewSessionHistoryFilters {
  status?: string;
  traceHealth?: string;
  hasReport?: boolean;
  since?: string;
  query?: string;
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
  node_type_counts?: Record<string, number>;
  fallback_trace_count?: number;
  turn_count?: number;
  nodes_offset: number;
  nodes_limit: number;
  nodes_has_more: boolean;
  nodes: TraceExplorerNode[];
}

export interface Strategy {
  id?: string | null;
  slug?: string | null;
  memory_key?: string | null;
  path: string;
  name: string;
  dimensions: string[];
  job_levels: string[];
  description: string;
  source?: string;
  status?: string;
  quality_reason?: string | null;
  promotion_stage?: string;
  confidence?: number;
  support_count?: number;
}

export interface Strategies {
  count: number;
  strategies: Strategy[];
}

export interface SkillPlaybookCard {
  id: string;
  name: string;
  description?: string | null;
  status: string;
  priority: number;
  tags?: Record<string, string[]>;
  direction_tags: string[];
  role_tags: string[];
  dimensions: string[];
  job_levels: string[];
  probe_intents: string[];
  failure_categories: string[];
  generator_moves: string[];
  watch_for: string[];
  avoid: string[];
  evaluator_rubric_hints: string[];
  positive_signals: string[];
  negative_signals: string[];
  score_bias_rules: string[];
  evaluator_visibility: boolean;
  source?: string;
  version?: number;
  content_hash?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  body_preview?: string;
  body_markdown?: string;
}

export interface SkillPlaybooks {
  runtime_backend: string;
  count: number;
  active_count: number;
  status_counts: Record<string, number>;
  skill_playbooks: SkillPlaybookCard[];
}

export interface SkillPlaybookDetail {
  skill_playbook: SkillPlaybookCard;
}

export interface SkillPlaybookImportResult {
  imported: number;
  updated: number;
  unchanged: number;
  archived: number;
  skipped: number;
}

export interface QuestionSeed {
  id: string;
  version: number;
  title: string;
  dimension: string;
  job_levels: string[];
  skill_tags: string[];
  direction_tags: string[];
  role_tags: string[];
  rubric?: Record<string, unknown>;
  priority?: number;
  status?: string;
  source?: string;
  scope?: string;
  org_id?: string | null;
  job_template_id?: string | null;
  language?: string;
  variant_count?: number;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface QuestionVariant {
  id: string;
  seed_id: string;
  version: number;
  intent: string;
  difficulty: string;
  scenario_brief: string;
  question_stem: string;
  prompt_template: string;
  scenario_skill_tags: string[];
  resume_anchor_hints: string[];
  failure_categories: string[];
  rubric_additions: string[];
  expected_signals: string[];
  anti_patterns: string[];
  good_answer_hints: string[];
  role_tags: string[];
  priority?: number;
  status?: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface QuestionSeeds {
  count: number;
  question_seeds: QuestionSeed[];
}

export interface QuestionSeedDetail {
  seed: QuestionSeed;
  variants: QuestionVariant[];
}

export interface QuestionUsageItem {
  id: string;
  session_id: string;
  turn_idx: number;
  trace_id?: string | null;
  seed_id: string;
  variant_id: string;
  seed_version: number;
  variant_version: number;
  rank: number;
  match_score: number;
  match_reasons: string[];
  injected: boolean;
  question_selector_mode: string;
  direction_tags?: string[];
  role_tags?: string[];
  score?: number | null;
  passed?: boolean | null;
  immediate_reward?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface QuestionUsages {
  count: number;
  usages: QuestionUsageItem[];
}

export interface QuestionRerankUsageItem {
  id: string;
  session_id: string;
  turn_idx: number;
  trace_id?: string | null;
  dimension: string;
  probe_intent?: string | null;
  question_selector_mode: string;
  rule_top_seed_id?: string | null;
  rule_top_variant_id?: string | null;
  llm_top_seed_id?: string | null;
  llm_top_variant_id?: string | null;
  candidate_variant_ids: string[];
  ranked_variant_ids: string[];
  fit_scores?: Record<string, number>;
  anchor_choice?: string | null;
  reasons: string[];
  confidence?: number | null;
  model?: string | null;
  latency_ms?: number | null;
  status: string;
  error?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface QuestionRerankUsages {
  count: number;
  rerank_usages: QuestionRerankUsageItem[];
}

export type QuestionReviewWinner = "rule" | "llm" | "tie" | "neither";

export interface QuestionReviewItem {
  id: string;
  session_id: string;
  turn_idx: number;
  trace_id?: string | null;
  question_rerank_usage_id?: string | null;
  rule_variant_id?: string | null;
  llm_variant_id?: string | null;
  winner: QuestionReviewWinner;
  reasons: string[];
  notes?: string;
  reviewer?: string;
  context_summary?: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface QuestionReviews {
  count: number;
  reviews: QuestionReviewItem[];
}

export interface CreateQuestionReviewInput {
  question_rerank_usage_id?: string | null;
  session_id: string;
  turn_idx: number;
  trace_id?: string | null;
  rule_variant_id?: string | null;
  llm_variant_id?: string | null;
  winner: QuestionReviewWinner;
  reasons?: string[];
  notes?: string;
  reviewer?: string;
  context_summary?: Record<string, unknown>;
}

export interface QuestionReviewCreateResponse {
  review: QuestionReviewItem;
}

export interface QuestionSeedLintIssue {
  severity: "warning" | "error";
  code: string;
  seed_id?: string | null;
  variant_id?: string | null;
  message: string;
}

export interface QuestionSeedLintResponse {
  passed: boolean;
  strict: boolean;
  warning_count: number;
  error_count: number;
  issues: QuestionSeedLintIssue[];
}

export interface QuestionSeedImportResult {
  imported_seeds: number;
  updated_seeds: number;
  unchanged_seeds: number;
  imported_variants: number;
  updated_variants: number;
  unchanged_variants: number;
  archived_seeds: number;
  archived_variants: number;
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
  sessions_deleted: number;
  traces_deleted: number;
  outcomes_deleted: number;
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
  options?: {
    offset?: number;
    limit?: number;
    filters?: InterviewSessionHistoryFilters;
  },
): Promise<InterviewSessionHistory> {
  const params = new URLSearchParams();
  if (options?.offset) params.set("offset", String(options.offset));
  if (options?.limit) params.set("limit", String(options.limit));
  if (options?.filters?.status) params.set("status", options.filters.status);
  if (options?.filters?.traceHealth)
    params.set("trace_health", options.filters.traceHealth);
  if (typeof options?.filters?.hasReport === "boolean")
    params.set("has_report", String(options.filters.hasReport));
  if (options?.filters?.since) params.set("since", options.filters.since);
  if (options?.filters?.query) params.set("q", options.filters.query);
  const qs = params.toString();
  return adminGet<InterviewSessionHistory>(
    `/admin/interview-sessions${qs ? `?${qs}` : ""}`,
    signal,
  );
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

export function getSkillPlaybooks(
  signal?: AbortSignal,
  filters?: {
    status?: string;
    directionTag?: string;
    roleTag?: string;
    dimension?: string;
  },
): Promise<SkillPlaybooks> {
  const params = new URLSearchParams();
  if (filters?.status) params.set("status", filters.status);
  if (filters?.directionTag) params.set("direction_tag", filters.directionTag);
  if (filters?.roleTag) params.set("role_tag", filters.roleTag);
  if (filters?.dimension) params.set("dimension", filters.dimension);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return adminGet<SkillPlaybooks>(`/admin/skill-playbooks${suffix}`, signal);
}

export function getSkillPlaybook(
  cardId: string,
  signal?: AbortSignal,
): Promise<SkillPlaybookDetail> {
  return adminGet<SkillPlaybookDetail>(
    `/admin/skill-playbooks/${encodeURIComponent(cardId)}`,
    signal,
  );
}

export function importSkillPlaybooks(
  archiveMissing = false,
): Promise<SkillPlaybookImportResult> {
  const suffix = archiveMissing ? "?archive_missing=true" : "";
  return adminPost<SkillPlaybookImportResult>(
    `/admin/skill-playbooks/import${suffix}`,
    {},
  );
}

export function getQuestionSeeds(
  signal?: AbortSignal,
  filters?: { directionTag?: string; roleTag?: string },
): Promise<QuestionSeeds> {
  const params = new URLSearchParams();
  if (filters?.directionTag) params.set("direction_tag", filters.directionTag);
  if (filters?.roleTag) params.set("role_tag", filters.roleTag);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return adminGet<QuestionSeeds>(`/admin/question-seeds${suffix}`, signal);
}

export function getQuestionSeed(
  seedId: string,
  signal?: AbortSignal,
): Promise<QuestionSeedDetail> {
  return adminGet<QuestionSeedDetail>(
    `/admin/question-seeds/${encodeURIComponent(seedId)}`,
    signal,
  );
}

export function getQuestionUsages(
  signal?: AbortSignal,
  filters?: { directionTag?: string; roleTag?: string },
): Promise<QuestionUsages> {
  const params = new URLSearchParams({ limit: "100" });
  if (filters?.directionTag) params.set("direction_tag", filters.directionTag);
  if (filters?.roleTag) params.set("role_tag", filters.roleTag);
  return adminGet<QuestionUsages>(`/admin/question-usages?${params.toString()}`, signal);
}

export function getQuestionRerankUsages(
  signal?: AbortSignal,
): Promise<QuestionRerankUsages> {
  return adminGet<QuestionRerankUsages>(
    "/admin/question-rerank-usages?limit=100",
    signal,
  );
}

export function getQuestionReviews(
  signal?: AbortSignal,
): Promise<QuestionReviews> {
  return adminGet<QuestionReviews>("/admin/question-reviews?limit=100", signal);
}

export function createQuestionReview(
  payload: CreateQuestionReviewInput,
): Promise<QuestionReviewCreateResponse> {
  return adminPost<QuestionReviewCreateResponse>("/admin/question-reviews", payload);
}

export function runQuestionSeedLint(
  strictQuality = false,
): Promise<QuestionSeedLintResponse> {
  const suffix = strictQuality ? "?strict_quality=true" : "";
  return adminPost<QuestionSeedLintResponse>(
    `/admin/question-seeds/lint${suffix}`,
    {},
  );
}

export function importQuestionSeeds(
  archiveMissing = false,
): Promise<QuestionSeedImportResult> {
  const suffix = archiveMissing ? "?archive_missing=true" : "";
  return adminPost<QuestionSeedImportResult>(
    `/admin/question-seeds/import${suffix}`,
    {},
  );
}

export function disableQuestionSeed(seedId: string): Promise<{ id: string; status: string }> {
  return adminPost<{ id: string; status: string }>(
    `/admin/question-seeds/${encodeURIComponent(seedId)}/disable`,
    {},
  );
}

export function archiveQuestionSeed(seedId: string): Promise<{ id: string; status: string }> {
  return adminPost<{ id: string; status: string }>(
    `/admin/question-seeds/${encodeURIComponent(seedId)}/archive`,
    {},
  );
}

export function disableQuestionVariant(variantId: string): Promise<{ id: string; status: string }> {
  return adminPost<{ id: string; status: string }>(
    `/admin/question-variants/${encodeURIComponent(variantId)}/disable`,
    {},
  );
}

export function archiveQuestionVariant(variantId: string): Promise<{ id: string; status: string }> {
  return adminPost<{ id: string; status: string }>(
    `/admin/question-variants/${encodeURIComponent(variantId)}/archive`,
    {},
  );
}

export interface StrategySignalItem {
  id: string;
  signal_key: string;
  group_key: string;
  session_id: string;
  turn_idx: number;
  dimension: string;
  job_level?: string | null;
  action_id?: string | null;
  plan_template?: string | null;
  probe_intent?: string | null;
  failure_categories?: string[];
  score_after?: number | null;
  score_delta?: number | null;
  immediate_reward?: number | null;
  verifier_overruled?: boolean;
  signal_type: string;
  status: string;
  created_at?: string | null;
}

export interface StrategySignals {
  count: number;
  signals: StrategySignalItem[];
}

export interface StrategyUsageItem {
  id: string;
  strategy_id: string;
  session_id: string;
  turn_idx: number;
  trace_id?: string | null;
  context_key?: string | null;
  action_id?: string | null;
  plan_template?: string | null;
  score?: number | null;
  passed?: boolean | null;
  immediate_reward?: number | null;
  delayed_reward?: number | null;
  verifier_overruled?: boolean;
  helpful_score?: number | null;
  created_at?: string | null;
}

export interface StrategyUsages {
  count: number;
  usages: StrategyUsageItem[];
}

export interface StrategyStatsItem {
  id: string;
  strategy_id: string;
  context_key: string;
  uses: number;
  avg_score?: number | null;
  pass_rate?: number | null;
  avg_immediate_reward?: number | null;
  avg_delayed_reward?: number | null;
  avg_blended_reward?: number | null;
  overrule_rate?: number | null;
  helpful_avg?: number | null;
  last_used_at?: string | null;
  updated_at?: string | null;
}

export interface StrategyStats {
  count: number;
  stats: StrategyStatsItem[];
}

export function getStrategySignals(
  signal?: AbortSignal,
): Promise<StrategySignals> {
  return adminGet<StrategySignals>("/admin/strategy-signals", signal);
}

export function getStrategyUsages(
  signal?: AbortSignal,
): Promise<StrategyUsages> {
  return adminGet<StrategyUsages>("/admin/strategy-usages", signal);
}

export function getStrategyStats(signal?: AbortSignal): Promise<StrategyStats> {
  return adminGet<StrategyStats>("/admin/strategy-stats", signal);
}

export function refreshStrategyStats(): Promise<{ refreshed: number; deleted: number }> {
  return adminPost<{ refreshed: number; deleted: number }>(
    "/admin/strategy-stats/refresh",
    {},
  );
}

export function disableStrategy(strategyId: string): Promise<{ id: string; status: string }> {
  return adminPost<{ id: string; status: string }>(
    `/admin/strategies/${encodeURIComponent(strategyId)}/disable`,
    {},
  );
}

export function archiveStrategy(strategyId: string): Promise<{ id: string; status: string }> {
  return adminPost<{ id: string; status: string }>(
    `/admin/strategies/${encodeURIComponent(strategyId)}/archive`,
    {},
  );
}

export function runStrategyPromotion(): Promise<{
  promoted: number;
  unchanged: number;
  skipped: number;
  disabled?: number;
  stabilized?: number;
}> {
  return adminPost("/admin/strategy-promotion/run", {});
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

export interface SessionAnchorRagCountBucket {
  chunks: number;
  sessions: number;
  avg_chunks_per_session?: number;
}

export interface SessionAnchorRagSummary {
  resume_rag_mode: "off" | "shadow" | "primary" | string;
  total_chunks: number;
  total_sessions: number;
  by_source_type: Record<string, SessionAnchorRagCountBucket>;
  by_mode: Record<string, SessionAnchorRagCountBucket>;
  embedding_model_version?: string | null;
  by_embedding_model_version?: Record<string, SessionAnchorRagCountBucket>;
  recent_sessions?: Array<{
    session_id: string;
    chunks: number;
    last_chunk_at?: string | null;
  }>;
}

export interface SessionAnchorRagMetricBucket {
  total_retrievals: number;
  hit_count: number;
  hit_rate: number;
  fallback_distribution: Record<string, number>;
  latency_ms: {
    p50?: number | null;
    p99?: number | null;
  };
}

export interface SessionAnchorRagMetrics {
  window_hours: number;
  by_source_type: Record<string, SessionAnchorRagMetricBucket>;
  by_mode: Record<string, SessionAnchorRagMetricBucket>;
  by_status?: Record<string, number>;
}

export interface SessionAnchorSessionRow {
  session_id: string;
  candidate_name?: string | null;
  job_title?: string | null;
  session_status: string;
  created_at?: string | null;
  updated_at?: string | null;
  completed_at?: string | null;
  has_resume_chunks: boolean;
  has_self_intro_chunks: boolean;
  total_chunks: number;
  chunks_by_source: Record<string, number>;
  chunker_modes: string[];
  chunker_modes_by_source?: Record<string, string[]>;
  embedding_model_versions: string[];
  retrieval_attempts: number;
  hit_count: number;
  hit_rate: number;
  source_hit_counts: Record<string, number>;
  avg_hits_per_attempt: number;
  fallback_count: number;
  fallback_reasons: Record<string, number>;
  latency_ms: {
    p50?: number | null;
    p95?: number | null;
    p99?: number | null;
  };
  rag_status_distribution: Record<string, number>;
  last_trace_at?: string | null;
}

export interface SessionAnchorSessionsResponse {
  window: string;
  window_hours: number;
  session_count: number;
  summary: {
    indexed_sessions: number;
    indexed_session_rate: number;
    hit_sessions: number;
    hit_session_rate: number;
    fallback_sessions: number;
    fallback_session_rate: number;
  };
  sessions: SessionAnchorSessionRow[];
}

export interface DeleteSessionAnchorDataResponse {
  session_id: string;
  deleted: boolean;
  chunks_deleted: number;
  resume_artifacts_deleted: number;
  resume_artifact_ids?: string[];
  sessions_scrubbed: number;
  traces_scrubbed: number;
}

export function getSessionAnchorRagSummary(
  signal?: AbortSignal,
): Promise<SessionAnchorRagSummary> {
  return adminGet<SessionAnchorRagSummary>(
    "/admin/session-anchors/summary",
    signal,
  );
}

export function getSessionAnchorRagMetrics(
  signal?: AbortSignal,
): Promise<SessionAnchorRagMetrics> {
  return adminGet<SessionAnchorRagMetrics>(
    "/admin/session-anchors/metrics",
    signal,
  );
}

export function getSessionAnchorSessions(
  options?: { since?: string },
  signal?: AbortSignal,
): Promise<SessionAnchorSessionsResponse> {
  const since = options?.since ?? "24h";
  const params = new URLSearchParams({ since });
  return adminGet<SessionAnchorSessionsResponse>(
    `/admin/session-anchors/sessions?${params.toString()}`,
    signal,
  );
}

export function deleteSessionAnchorData(
  sessionId: string,
): Promise<DeleteSessionAnchorDataResponse> {
  return adminDelete<DeleteSessionAnchorDataResponse>(
    `/admin/sessions/${encodeURIComponent(sessionId)}/anchor-data`,
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
