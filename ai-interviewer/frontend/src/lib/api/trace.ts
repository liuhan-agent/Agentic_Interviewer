import type { TraceHealth } from "@/lib/api/types";

export type { TraceHealth };

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
  node_type_aliases?: Record<string, string[]>;
  fallback_trace_count?: number;
  turn_count?: number;
  nodes_offset: number;
  nodes_limit: number;
  nodes_has_more: boolean;
  nodes: TraceExplorerNode[];
}
