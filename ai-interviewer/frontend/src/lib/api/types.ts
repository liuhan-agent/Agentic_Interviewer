export interface ResumeProject {
  id: string;
  name: string;
  role?: string;
  tech_stack?: string[];
  responsibilities?: string[];
  achievements?: string[];
  question_anchors?: string[];
}

export interface ResumeFocusArea {
  id: string;
  label: string;
  project_id?: string | null;
  dimensions?: string[];
  skills?: string[];
  priority?: number;
}

export interface ResumeCandidateProfile {
  education_level?: string;
  school?: string;
  major?: string;
  experience_years?: number;
  current_or_target_role?: string;
  birth_year?: number;
  age?: number;
  graduation_year?: number;
  fresh_graduate?: boolean;
  suggested_job_title?: string;
  suggested_job_level?: JobSpec["level"];
  suggested_job_level_basis?: string[];
}

export interface ResumeAnchor {
  focus_id?: string | null;
  label?: string;
  project_id?: string | null;
  project_name?: string;
  role?: string;
  tech_stack?: string[];
  skills?: string[];
  dimensions?: string[];
  question_anchors?: string[];
  achievements?: string[];
  knowledge_source?: "local" | "web" | string;
}

export interface SelfIntroCommunicationSignal {
  structure?: "clear" | "average" | "unclear";
  notes?: string[];
}

export interface SelfIntroProfile {
  summary?: string;
  emphasized_projects?: string[];
  emphasized_skills?: string[];
  preferred_focus?: string[];
  clarification_targets?: string[];
  communication_signal?: SelfIntroCommunicationSignal;
  parse_status?: "llm" | "heuristic" | "fallback" | string;
}

export interface SelfIntroReport {
  answer?: string;
  profile?: SelfIntroProfile;
}

export interface Candidate {
  name: string;
  email_hash?: string;
  resume_parsed: {
    summary?: string;
    skills?: string[];
    highlights?: string[];
    projects?: ResumeProject[];
    focus_areas?: ResumeFocusArea[];
    concerns?: string[];
    candidate_profile?: ResumeCandidateProfile;
  };
}

export type LLMErrorKind =
  | "auth"
  | "quota"
  | "rate_limit"
  | "timeout"
  | "network"
  | "misconfig"
  | "unknown";

export interface JobSpec {
  title: string;
  level: "junior" | "mid" | "senior" | "staff" | "principal";
  required_skills: string[];
  rubric_dimensions: string[];
  rubric?: Record<string, string>;
  interview_industry?: string;
  interview_direction?: string;
  interview_direction_label?: string;
}

export interface LLMConfigPayload {
  provider?: string;
  api_key?: string;
  model?: string;
  temperature?: number;
  base_url?: string;
  role_overrides?: Record<
    string,
    {
      provider?: string;
      api_key?: string;
      model?: string;
      base_url?: string;
    }
  >;
  voice_overrides?: {
    asr?: {
      provider?: "qwen" | "openai";
      api_key?: string;
      model?: string;
      base_url?: string;
    };
    tts?: {
      provider?: "qwen" | "openai";
      api_key?: string;
      model?: string;
      voice?: string;
      base_url?: string;
    };
  };
}

export interface StartSessionRequest {
  candidate: Candidate;
  job_spec: JobSpec;
  max_turns?: number;
  quality_threshold?: number;
  turn_budget?: number;
  /**
   * Interview style understood by the backend. ``tech`` and
   * ``behavioral`` focus the rubric; ``mixed`` combines both.
   * ``text`` / ``voice`` are accepted as aliases of ``mixed`` and
   * describe the client channel, not the question topic.
   */
  mode?: "mixed" | "tech" | "behavioral" | "text" | "voice";
  enable_video_analysis?: boolean;
  llm_config?: LLMConfigPayload;
}

export interface StartSessionResponse {
  session_id: string;
  session_token: string;
  session_token_expires_at: string;
  recovery_token: string;
  recovery_token_expires_at: string;
  trace_id: string;
  status: string;
  created_at: string;
  updated_at: string;
  max_turns?: number | null;
  enable_video_analysis?: boolean;
}

export interface RecoverSessionResponse {
  session_id: string;
  session_token: string;
  session_token_expires_at: string;
}

export interface VoiceTicketResponse {
  ticket: string;
  expires_in_seconds: number;
}

/** Pending / waiting for answer / completed. */
export type PollStatus =
  | "pending"
  | "waiting_for_answer"
  | "completed"
  | "running"
  | "cancelled"
  | "error";

export interface PollQuestion {
  question?: string;
  question_type?: "self_intro" | "technical" | string;
  dimension?: string;
  target_skills?: string[];
  turn_idx?: number;
  formal_turn_idx?: number;
  contract?: unknown;
  resume_anchor?: ResumeAnchor;
  [key: string]: unknown;
}

/**
 * Compact projection of the candidate's most recently evaluated turn,
 * surfaced by the backend (`_extract_last_turn_evaluation` in
 * `session_manager.py`) so the InterviewRoom can render an
 * "above-the-fold" feedback card while the candidate composes the next
 * answer. The backend keeps the feedback arrays intact; UI surfaces decide
 * how many items to preview and whether to offer an expanded view. The type
 * leaves them as plain `string[]` so the component never has to defend
 * against null.
 *
 * Returned as `null` for first turn / non-scoring intents / explicitly
 * skipped turns. Evaluator fallback turns are surfaced with
 * `source` / `fallback_reason` so the UI can explain the system state
 * without presenting it as candidate-quality feedback.
 */
export interface PreviousTurnEvaluation {
  turn_idx?: number | null;
  dimension?: string | null;
  score?: number | null;
  passed: boolean;
  strengths: string[];
  weaknesses: string[];
  source?: string | null;
  fallback_reason?: string | null;
  system_warnings?: string[];
  rubric_coverage?: Record<string, unknown>;
}

export interface PollQuestionResponse {
  session_id: string;
  status: PollStatus;
  turn_idx?: number | null;
  question: PollQuestion | null;
  max_turns?: number | null;
  enable_video_analysis?: boolean;
  final_report?: FinalReport | null;
  error?: string | null;
  error_kind?: LLMErrorKind | null;
  retryable?: boolean;
  /**
   * Mirrors `handle.last_turn_evaluation`. `null` when no displayable
   * feedback exists this turn (see `PreviousTurnEvaluation` doc).
   */
  previous_turn_evaluation?: PreviousTurnEvaluation | null;
  /**
   * Wall-clock duration of the most recent server-side segment, in
   * milliseconds. `null` until the first segment finishes. Used by
   * the UI to render an ETA hint on the next loading state.
   */
  server_latency_ms?: number | null;
}

export interface AnswerRequest {
  answer: string;
  turn_idx: number;
  video_signals?: Record<string, unknown>;
  llm_config?: LLMConfigPayload;
}

export interface SkipQuestionRequest {
  turn_idx: number;
  reason?: string;
}

export interface SkipQuestionResponse {
  session_id: string;
  accepted: boolean;
  status: "skipped";
}

export interface HintRequest {
  turn_idx: number;
  llm_config?: LLMConfigPayload;
}

export interface QuestionAudioRequest {
  turn_idx: number;
  llm_config?: LLMConfigPayload;
}

export interface HintResponse {
  session_id: string;
  turn_idx: number;
  hint: string;
  source: "contract" | "target_skills" | "resume_anchor" | "fallback" | "llm";
}

export interface InterviewWaitingTip {
  id: string;
  scope: string;
  text: string;
}

export interface InterviewWaitingTipsResponse {
  version: string;
  rotation_interval_ms: number;
  tips: InterviewWaitingTip[];
}

export type RubricScoreStatus =
  | "scored"
  | "not_evaluated"
  | "skipped"
  | "evaluator_unavailable";

export type RubricCoverageStatus =
  | "passed"
  | "below_threshold"
  | "coverage_limited"
  | "not_applicable";

export interface ScoreSummary {
  scored_dimension_count: number;
  excluded_dimension_count: number;
  total_dimension_count: number;
}

export interface ScoreBreakdown {
  scored_turn_count: number;
  latest_score: number;
  best_score: number;
  average_score: number;
  adopted_score: number;
  scoring_policy: "weighted_recent" | string;
}

export interface RubricScore {
  score: number | null;
  score_status: RubricScoreStatus;
  excluded_from_overall: boolean;
  exclusion_reason: Exclude<RubricScoreStatus, "scored"> | null;
  coverage_status: RubricCoverageStatus;
  score_breakdown?: ScoreBreakdown;
  passed?: boolean;
  rationale?: string;
  weaknesses?: string[];
}

export interface TrainingPlanStep {
  task: string;
  rationale?: string;
  estimated_hours?: number;
}

export type TrainingPlanFallbackReason =
  | "llm_call_failed"
  | "json_parse_failed"
  | "invalid_structure"
  | "empty_output"
  | string;

export interface TrainingPlan {
  priority_weaknesses?: Array<{
    dimension: string;
    focus: string;
    why_it_matters?: string;
  }>;
  practice_plan?: TrainingPlanStep[];
  goals_30_60_90?: {
    "30_days"?: string[];
    "60_days"?: string[];
    "90_days"?: string[];
  };
  /**
   * "llm" — Coach LLM produced the plan from the QA history.
   * "fallback" — deterministic aggregation kicked in (LLM unavailable).
   * Surfaced to the report / replay UI so users can tell apart
   * intelligent inference from deterministic summary.
   */
  source?: "llm" | "fallback" | string;
  fallback_reason?: TrainingPlanFallbackReason;
}

export interface ReplayPriorityItem {
  category: "weakness" | "coverage_limited";
  label: "薄弱点" | "补充证据";
  dimension?: string | null;
  focus: string;
  display_text: string;
}

export interface ReplaySummary {
  job_title?: string | null;
  job_level?: JobSpec["level"] | string | null;
  overall_score?: number | null;
  growth_signal?: string | null;
  overall_verdict?: string | null;
  total_turns?: number | null;
  priority_weaknesses?: string[];
  priority_items?: ReplayPriorityItem[];
}

export interface ReplayFollowupReason {
  title: string;
  summary: string;
  chips: string[];
  source: "evaluator";
}

export interface ReplayContextBasis {
  title: string;
  summary?: string;
  chips: string[];
  self_intro?: {
    summary?: string;
    emphasized_projects: string[];
    emphasized_skills: string[];
    preferred_focus: string[];
  };
  resume?: {
    projects: string[];
    focus_areas: string[];
    skills: string[];
  };
  job_spec?: {
    title?: string | null;
    level?: string | null;
    required_skills: string[];
    dimensions: string[];
    dimension_source_label?: string;
  };
}

export interface ReplayQuestionBasis {
  title: string;
  summary: string;
  chips: string[];
}

export interface ReplayTurn {
  turn_idx: number;
  dimension?: string | null;
  question?: string | null;
  answer?: string | null;
  score?: number | null;
  passed?: boolean | null;
  rationale?: string;
  strengths?: string[];
  weaknesses?: string[];
  next_step?: string;
  followup_reason?: ReplayFollowupReason | null;
  question_basis?: ReplayQuestionBasis | null;
}

export interface ResumeHistoryTurn extends Omit<ReplayTurn, "turn_idx"> {
  turn_idx?: number | null;
  question_type?: "self_intro" | "technical" | string;
}

export interface ReplayResponse {
  session_id: string;
  status: PollStatus | "completed" | string;
  created_at?: string | null;
  updated_at?: string | null;
  summary: ReplaySummary;
  context_basis?: ReplayContextBasis | null;
  timeline: ReplayTurn[];
  training_plan?: TrainingPlan;
}

export interface VideoAnalysis {
  avg_engagement?: number;
  avg_confidence?: number;
  dominant_emotion?: string;
  per_turn_signals?: Array<{
    turn_idx: number;
    engagement: number;
    confidence: number;
    emotion: string;
  }>;
}

export interface EvidenceSummary {
  total_quotes?: number;
  matched_quotes?: number;
  unmatched_quotes?: number;
  exact_matches?: number;
  fuzzy_matches?: number;
  match_rate?: number;
}

/**
 * LLM cost accounting for one interview session, populated by the
 * backend ``final_report_node``. ``est_usd`` is a coarse estimate
 * derived from a static price table and may differ from the actual
 * provider invoice; flag ``usage_estimated`` when at least one
 * provider response did not include a real ``usage`` block.
 */
export interface CostSummary {
  calls: number;
  stub_calls?: number;
  error_calls?: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  est_usd: number;
  usage_estimated?: boolean;
  model_for_pricing?: string;
}

export interface FinalReport {
  session_id?: string;
  overall_score?: number | null;
  growth_signal?: string | null;
  /** Deprecated: use growth_signal for candidate-facing UI. */
  overall_verdict?: string | null;
  dimension_scores?: Record<string, RubricScore>;
  score_summary?: ScoreSummary;
  self_intro?: SelfIntroReport;
  summary?: string;
  training_plan?: TrainingPlan;
  video_analysis?: VideoAnalysis;
  evidence_summary?: EvidenceSummary;
  /**
   * How many of ``total_turns`` were scored by the conservative
   * fallback path (LLM unavailable). When the ratio is high, the
   * report UI shows a banner so the user knows the score is
   * "indicative" rather than fully calibrated.
   */
  evaluator_fallback_count?: number;
  total_turns?: number;
  cost_summary?: CostSummary | null;
  [key: string]: unknown;
}

export type TraceHealth = "missing" | "partial" | "complete";

export interface GetReportResponse {
  session_id: string;
  created_at?: string | null;
  updated_at?: string | null;
  final_report: FinalReport | null;
  trace_health?: TraceHealth | null;
  error?: string | null;
  error_kind?: LLMErrorKind | null;
}

export interface SessionMetadataResponse {
  session_id: string;
  status: PollStatus | "completed" | string;
  created_at: string;
  updated_at: string;
  job_title?: string | null;
  candidate_name?: string | null;
  job_level?: string | null;
  overall_score?: number | null;
  growth_signal?: string | null;
  overall_verdict?: string | null;
  dimension_scores?: Record<string, number>;
}

export interface SessionSetupSnapshotResponse {
  session_id: string;
  candidate: Candidate;
  job_spec: JobSpec;
}

export interface ResumeResponse {
  session_id: string;
  status: PollStatus;
  created_at?: string | null;
  updated_at?: string | null;
  turn_idx?: number;
  question?: PollQuestion | null;
  max_turns?: number | null;
  enable_video_analysis?: boolean;
  history?: ResumeHistoryTurn[];
  previous_turn_evaluation?: PreviousTurnEvaluation | null;
  final_report?: FinalReport | null;
  error?: string | null;
  error_kind?: LLMErrorKind | null;
  retryable?: boolean;
}

export interface RetryQuestionResponse {
  session_id: string;
  status: "retrying";
}

export interface DeleteSessionResponse {
  session_id: string;
  deleted: boolean;
  traces_deleted: number;
  outcome_deleted: boolean;
  checkpoint_deleted?: boolean;
}

/**
 * Server response shape for `POST /api/v1/interview/resume/parse`.
 * Designed to drop straight into `Candidate.resume_parsed`, with
 * `raw_text_preview` available purely for UI debugging.
 */
export interface ParseResumeResponse {
  candidate_name?: string;
  candidate_profile?: ResumeCandidateProfile;
  summary: string;
  skills: string[];
  highlights: string[];
  projects?: ResumeProject[];
  focus_areas?: ResumeFocusArea[];
  concerns?: string[];
  raw_text_preview: string;
  parse_status?: ParseResumeStatus;
}

export interface ParseResumeStatus {
  mode: "ai_refined" | "basic";
  reason:
    | "ai_completed"
    | "heuristic"
    | "stub_mode"
    | "timeout"
    | "llm_failed"
    | "disabled";
  message: string;
  elapsed_ms?: number;
  text_chars?: number;
  cached?: boolean;
  cache_age_ms?: number;
}

export type ResumeParseJobStatus =
  | "running"
  | "completed"
  | "failed"
  | "expired";

export interface ResumeParseJobResponse {
  job_id: string;
  status: ResumeParseJobStatus;
  filename?: string | null;
  result?: ParseResumeResponse;
  error?: string | null;
  expires_at?: string;
}

/** Canonical dimension id paired with its UI-friendly label. */
export interface DimensionOption {
  id: string;
  label: string;
}

export interface DimensionCatalogItem extends DimensionOption {
  description?: string;
}

export interface InterviewDirection {
  industry: string;
  direction: string;
  label: string;
  default_title: string;
  default_level: JobSpec["level"];
  skills: string[];
  dimension_catalog: DimensionCatalogItem[];
  rubric_dimensions: string[];
}

export interface ListDirectionsResponse {
  directions: InterviewDirection[];
}

/** Server response shape for `POST /api/v1/interview/jd/parse`. */
export interface ParseJobSpecResponse {
  required_skills: string[];
  rubric_dimensions: string[];
  rubric_dimension_labels: DimensionOption[];
  suggested_level: "junior" | "mid" | "senior" | "staff" | "principal" | null;
  rationale: string;
  unmapped_requirements?: string[];
}

/** Editable generic JD template for a setup direction. */
export interface JobTemplateResponse {
  direction: string;
  level?: JobSpec["level"] | null;
  title: string;
  template: string;
  skills: string[];
  rubric_dimensions: string[];
}

export interface ListDimensionsResponse {
  dimensions: DimensionOption[];
}

export type FeedbackOutcome =
  | "got_offer"
  | "no_offer"
  | "still_preparing"
  | "withdrew";

export interface SubmitFeedbackRequest {
  outcome: FeedbackOutcome;
  helpful_score?: number;
  notes?: string;
}

export interface SubmitFeedbackResponse {
  session_id: string;
  accepted: boolean;
}
