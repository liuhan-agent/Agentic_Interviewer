"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { Activity, AlertTriangle, ArrowLeft, ChevronDown, ExternalLink, FileText, GitBranch, Loader2, RefreshCw, Search, Timer } from "lucide-react";

import { TraceAnnotationDialog } from "@/components/admin/TraceAnnotationDialog";
import { PendingNavigationLink } from "@/components/navigation/PendingNavigationLink";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getTraceExplorer,
  getTracerHealth,
  type TracerHealthSnapshot,
} from "@/lib/api/admin";
import { getSessionTrace } from "@/lib/api/interview";
import type {
  LangSmithAdminMeta,
  TraceDiagnostics,
  TraceExplorerNode,
  TraceExplorerResponse,
  TraceHealth,
} from "@/lib/api/trace";

type Fetch =
  | { phase: "loading" }
  | { phase: "ready"; data: TraceExplorerResponse }
  | { phase: "error"; message: string };

type TraceFetcher = (
  sessionId: string,
  signal?: AbortSignal,
  options?: { offset?: number; limit?: number },
) => Promise<TraceExplorerResponse>;

type TraceExplorerAudience = "admin" | "owner";

const healthLabel: Record<TraceHealth, string> = {
  missing: "缺失",
  partial: "部分",
  complete: "完整",
};

export function TraceExplorer({
  sessionId,
  focusNode,
  focusDimension,
}: {
  sessionId: string;
  focusNode?: string;
  focusDimension?: string;
}) {
  return (
    <TraceExplorerLoader
      sessionId={sessionId}
      focusNode={focusNode}
      focusDimension={focusDimension}
      fetchTrace={getTraceExplorer}
      audience="admin"
      showAdminControls={true}
    />
  );
}

export function SessionTraceExplorer({
  sessionId,
  focusNode,
  focusDimension,
}: {
  sessionId: string;
  focusNode?: string;
  focusDimension?: string;
}) {
  return (
    <TraceExplorerLoader
      sessionId={sessionId}
      focusNode={focusNode}
      focusDimension={focusDimension}
      fetchTrace={getSessionTrace}
      audience="owner"
      showAdminControls={false}
    />
  );
}

function TraceExplorerLoader({
  sessionId,
  focusNode,
  focusDimension,
  fetchTrace,
  audience,
  showAdminControls,
}: {
  sessionId: string;
  focusNode?: string;
  focusDimension?: string;
  fetchTrace: TraceFetcher;
  audience: TraceExplorerAudience;
  showAdminControls: boolean;
}) {
  const [state, setState] = useState<Fetch>({ phase: "loading" });
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setState({ phase: "loading" });
    fetchTrace(sessionId, ctrl.signal)
      .then((data) => {
        if (!ctrl.signal.aborted) setState({ phase: "ready", data });
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setState({
          phase: "error",
          message: err instanceof Error ? err.message : String(err),
        });
    });
    return () => ctrl.abort();
  }, [fetchTrace, sessionId, retryKey]);

  if (state.phase === "loading") {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  if (state.phase === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="space-y-3 pt-6 text-sm">
          <p className="font-medium text-destructive">Trace Explorer 加载失败</p>
          <p className="text-muted-foreground">{state.message}</p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => setRetryKey((k) => k + 1)}
            >
              <RefreshCw className="h-3.5 w-3.5" />
              重试
            </Button>
            <BackLinks sessionId={sessionId} audience={audience} />
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <TraceExplorerView
      data={state.data}
      sessionId={sessionId}
      focusNode={focusNode}
      focusDimension={focusDimension}
      fetchTrace={fetchTrace}
      audience={audience}
      showAdminControls={showAdminControls}
    />
  );
}

const NODE_TYPE_FILTERS = [
  "all",
  "director_sample",
  "ask_question",
  "evaluator",
  "verification",
  "reward_update",
  "turn_finalize",
  "route_decision",
  "final_report",
  "refine_followup",
  "training_plan",
  "experience_extractor",
  "resume_parse",
  "self_intro_question",
  "self_intro_parse",
] as const;

const OPENING_NODES = new Set([
  "resume_parse",
  "self_intro_question",
  "self_intro_parse",
]);

const SESSION_CLOSING_NODES = new Set([
  "final_report",
  "training_plan",
  "experience_extractor",
]);

const STRATEGY_POLICY_CONTEXT_NODES = new Set([
  "director_sample",
  "ask_question",
  "evaluator",
  "reward_update",
]);

const TRACE_NODE_WORKFLOW_ORDER = [
  "resume_parse",
  "self_intro_question",
  "self_intro_parse",
  "director_sample",
  "ask_question",
  "evaluator",
  "verification",
  "reward_update",
  "turn_finalize",
  "route_decision",
  "refine_followup",
  "skip_question",
  "final_report",
  "training_plan",
  "experience_extractor",
];

const TRACE_NODE_ALIASES: Record<string, string> = {
  compress_context: "turn_finalize",
};

function traceNodeCanonicalName(node: string | null | undefined): string {
  const raw = String(node || "").trim();
  return TRACE_NODE_ALIASES[raw] || raw;
}

function normalizeTraceNodeFilter(node: string | null | undefined): string {
  if (!node || node === "all") return "all";
  return traceNodeCanonicalName(node);
}

function traceNodeDisplayName(
  node: string | null | undefined,
  payload?: Record<string, unknown> | null,
): string {
  const semanticNode =
    typeof payload?.semantic_node === "string" ? payload.semantic_node : null;
  const canonical = traceNodeCanonicalName(semanticNode || node);
  return canonical || node || "—";
}

function traceNodeDescription(
  node: string | null | undefined,
  payload?: Record<string, unknown> | null,
): string {
  if (typeof payload?.display_name_zh === "string" && payload.display_name_zh.trim()) {
    return payload.display_name_zh;
  }
  const semanticNode =
    typeof payload?.semantic_node === "string" ? payload.semantic_node : null;
  const canonical = traceNodeCanonicalName(semanticNode || node);
  if (canonical === "turn_finalize") return "轮次收尾";
  if (canonical === "route_decision") return "路由决策";
  if (canonical === "refine_followup") return "下一轮准备";
  return "";
}

function isTurnFinalizeNode(node: string | null | undefined): boolean {
  return traceNodeCanonicalName(node) === "turn_finalize";
}

function isVirtualTraceNode(node: string | null | undefined): boolean {
  return node === "route_decision";
}

function isStrategyPolicyContextNode(nodeName: string | null | undefined): boolean {
  const canonical = traceNodeCanonicalName(nodeName);
  return STRATEGY_POLICY_CONTEXT_NODES.has(canonical);
}

function displayStrategyContextKey(node: TraceExplorerNode): string {
  if (!isStrategyPolicyContextNode(node.node)) return "-";
  const contextKey = String(node.context_key || "").trim();
  return contextKey || "-";
}

function strategyPolicyContextKeys(node: TraceExplorerNode): string[] {
  if (!isStrategyPolicyContextNode(node.node)) return [];
  const rawKeys = Array.isArray(node.policy_context_keys)
    ? node.policy_context_keys
    : [];
  const keys: string[] = [];
  const seen = new Set<string>();
  for (const rawKey of rawKeys) {
    const key = String(rawKey || "").trim();
    if (!key || seen.has(key)) continue;
    keys.push(key);
    seen.add(key);
  }
  return keys;
}

function traceNodeRawAlias(
  node: string | null | undefined,
  payload?: Record<string, unknown> | null,
): string {
  const display = traceNodeDisplayName(node, payload);
  return node && display !== node ? `node: ${node}` : "";
}

type PromptSlotDefinition = {
  promptLabel: string;
  sourceKey: string;
  title: string;
  description: string;
};

const PROMPT_SLOT_DEFINITIONS: PromptSlotDefinition[] = [
  {
    promptLabel: "INTERVIEW_HISTORY_SUMMARY",
    sourceKey: "history_summary_projection",
    title: "历史摘要投影",
    description: "HistoryContextBuilder 从完整 qa_history 生成的维度级摘要。",
  },
  {
    promptLabel: "RECENT_QA",
    sourceKey: "recent_qa_prompt_view",
    title: "最近问答",
    description: "实际进入 prompt 的最近 QA 视图；必要时只截断 prompt 文本。",
  },
  {
    promptLabel: "CURRENT_GAPS",
    sourceKey: "current_gaps",
    title: "当前缺口",
    description: "从历史评估中投影出的开放缺口，用于提醒下一轮出题。",
  },
  {
    promptLabel: "RETRIEVED_KNOWLEDGE",
    sourceKey: "retrieval_block",
    title: "通用知识库 Legacy",
    description: "legacy 通用知识库槽位；结构化题库命中时通常为空。",
  },
  {
    promptLabel: "STRUCTURED_QUESTION_SEED",
    sourceKey: "question_seed_block",
    title: "题库问法骨架",
    description: "结构化题库选中的 Seed / Variant，用来定义本轮问什么。",
  },
  {
    promptLabel: "CANDIDATE_ANCHOR",
    sourceKey: "candidate_anchor_block",
    title: "候选人适配提示",
    description: "把题库问法贴合候选人的项目、技能和岗位要求。",
  },
  {
    promptLabel: "CANDIDATE_RESUME_RAG",
    sourceKey: "resume_rag_block",
    title: "简历命中片段",
    description: "候选人锚点 RAG 召回并最终注入的简历证据。",
  },
  {
    promptLabel: "SELF_INTRO_RAG",
    sourceKey: "self_intro_rag_block",
    title: "自我介绍命中片段",
    description: "候选人锚点 RAG 召回并最终注入的自我介绍证据。",
  },
  {
    promptLabel: "STRATEGY_MEMORY",
    sourceKey: "strategy_block",
    title: "出题策略记忆",
    description: "命中的策略记忆，用来影响本轮追问方式。",
  },
  {
    promptLabel: "INTERVIEW_SKILLS",
    sourceKey: "skill_block",
    title: "Skills Playbook",
    description: "命中的 Skills Playbook，用来补充出题侧能力焦点。",
  },
];

const PROMPT_SLOT_PREVIEW_LIMIT = 420;

export function TraceExplorerView({
  data: initialData,
  sessionId,
  focusNode,
  focusDimension,
  fetchTrace,
  audience,
  showAdminControls,
}: {
  data: TraceExplorerResponse;
  sessionId: string;
  focusNode?: string;
  focusDimension?: string;
  fetchTrace: TraceFetcher;
  audience: TraceExplorerAudience;
  showAdminControls: boolean;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [allNodes, setAllNodes] = useState<TraceExplorerNode[]>(initialData.nodes);
  const [hasMore, setHasMore] = useState(initialData.nodes_has_more);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [nodeFilter, setNodeFilter] = useState<string>(
    normalizeTraceNodeFilter(searchParams.get("nodeType") || "all"),
  );
  const [fallbackFilter, setFallbackFilter] = useState(
    searchParams.get("fallback") === "true",
  );
  const [searchText, setSearchText] = useState(searchParams.get("q") ?? "");
  const [selectedNodeId, setSelectedNodeId] = useState<number | null>(() =>
    parseOptionalInt(searchParams.get("selectedTraceId")),
  );
  const prefersReducedMotion = usePrefersReducedMotion();

  const totalNodeCount = initialData.node_count_total ?? initialData.trace_count;
  const diagnostics = initialData.trace_diagnostics ?? null;

  const replaceExplorerUrl = useCallback(
    (patch: Record<string, string | number | boolean | null>) => {
      if (typeof window === "undefined") return;
      const params = new URLSearchParams(window.location.search);
      for (const [key, value] of Object.entries(patch)) {
        if (value === null || value === "" || value === false) {
          params.delete(key);
        } else {
          params.set(key, String(value));
        }
      }
      const query = params.toString();
      const nextUrl = query ? `${pathname}?${query}` : pathname;
      window.history.replaceState(window.history.state, "", nextUrl);
    },
    [pathname],
  );

  const loadMore = useCallback(() => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    setLoadMoreError(null);
    const ctrl = new AbortController();
    fetchTrace(sessionId, ctrl.signal, { offset: allNodes.length })
      .then((resp) => {
        if (ctrl.signal.aborted) return;
        setAllNodes((prev) => [...prev, ...resp.nodes]);
        setHasMore(resp.nodes_has_more);
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setLoadMoreError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setLoadingMore(false));
  }, [fetchTrace, sessionId, allNodes.length, hasMore, loadingMore]);

  const filteredNodes = useMemo(() => {
    const q = searchText.trim().toLowerCase();
    const canonicalNodeFilter = traceNodeCanonicalName(nodeFilter);
    return allNodes.filter((node) => {
      if (
        nodeFilter !== "all" &&
        traceNodeCanonicalName(node.node) !== canonicalNodeFilter
      ) {
        return false;
      }
      if (fallbackFilter && !isEvaluatorFallbackTrace(node)) return false;
      if (!q) return true;
      return nodeMatchesQuery(node, q);
    });
  }, [allNodes, fallbackFilter, nodeFilter, searchText]);

  const grouped = useMemo(
    () => groupByTurn(filteredNodes, allNodes),
    [allNodes, filteredNodes],
  );
  const focusedNodeId = useMemo(
    () => pickFocusedNodeId(allNodes, focusNode, focusDimension),
    [allNodes, focusNode, focusDimension],
  );
  const selectedNode = useMemo(() => {
    const bySelected = selectedNodeId
      ? filteredNodes.find((node) => node.id === selectedNodeId)
      : null;
    if (bySelected) return bySelected;
    const byFocus = focusedNodeId
      ? filteredNodes.find((node) => node.id === focusedNodeId)
      : null;
    return byFocus ?? filteredNodes[0] ?? null;
  }, [filteredNodes, focusedNodeId, selectedNodeId]);

  useEffect(() => {
    if (!selectedNode) return;
    if (selectedNodeId !== selectedNode.id) {
      setSelectedNodeId(selectedNode.id);
    }
  }, [selectedNode, selectedNodeId]);

  useEffect(() => {
    const needsFocusedNode = Boolean(focusNode && !focusedNodeId);
    const needsSelectedNode = Boolean(
      selectedNodeId && !allNodes.some((node) => node.id === selectedNodeId),
    );
    if ((needsFocusedNode || needsSelectedNode) && hasMore && !loadingMore) {
      loadMore();
    }
  }, [
    allNodes,
    focusNode,
    focusedNodeId,
    hasMore,
    loadMore,
    loadingMore,
    selectedNodeId,
  ]);

  const loadedNodeTypeCounts = useMemo(() => countNodeTypes(allNodes), [allNodes]);
  const nodeTypeCounts = initialData.node_type_counts ?? loadedNodeTypeCounts;
  const fallbackTraceCount = useMemo(
    () =>
      initialData.fallback_trace_count ??
      allNodes.filter(isEvaluatorFallbackTrace).length,
    [allNodes, initialData.fallback_trace_count],
  );

  const selectNode = useCallback(
    (node: TraceExplorerNode) => {
      setSelectedNodeId(node.id);
      replaceExplorerUrl({ selectedTraceId: node.id });
    },
    [replaceExplorerUrl],
  );

  const handleNodeFilterChange = useCallback(
    (value: string) => {
      const nextValue = normalizeTraceNodeFilter(value);
      setNodeFilter(nextValue);
      setSelectedNodeId(null);
      replaceExplorerUrl({
        nodeType: nextValue === "all" ? null : nextValue,
        selectedTraceId: null,
      });
    },
    [replaceExplorerUrl],
  );

  const handleFallbackFilterChange = useCallback(() => {
    setFallbackFilter((current) => {
      const next = !current;
      replaceExplorerUrl({ fallback: next || null, selectedTraceId: null });
      return next;
    });
    setSelectedNodeId(null);
  }, [replaceExplorerUrl]);

  const handleSearchChange = useCallback(
    (value: string) => {
      setSearchText(value);
      setSelectedNodeId(null);
      replaceExplorerUrl({ q: value.trim() || null, selectedTraceId: null });
    },
    [replaceExplorerUrl],
  );

  return (
    <div className="space-y-6">
      <TraceCommandCenter
        data={initialData}
        diagnostics={diagnostics}
        fallbackTraceCount={fallbackTraceCount}
        loadedCount={allNodes.length}
        nodeTypeCounts={nodeTypeCounts}
        totalNodeCount={totalNodeCount}
        turnCount={initialData.turn_count ?? countTurns(allNodes)}
        audience={audience}
      />

      {showAdminControls && initialData.trace_health === "missing" && (
        <MissingTraceDiagnostics
          sessionId={initialData.session_id}
          status={initialData.status}
          langsmith={initialData.langsmith ?? null}
        />
      )}

      {initialData.trace_health !== "missing" &&
        diagnostics &&
        diagnostics.missing_key_nodes.length > 0 && (
          <PartialTraceDiagnostics diagnostics={diagnostics} />
        )}

      {initialData.trace_health !== "missing" && (
        <Card>
          <CardHeader>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <Activity className="h-4 w-4 text-emerald-400" />
                  <CardTitle className="text-base">轮次时间线</CardTitle>
                </div>
                <CardDescription>
                  按 `generation_traces` 顺序浏览 node；右侧展示 node evidence、policy context 与 raw payload。
                  {nodeFilter !== "all" && (
                    <span className="ml-2 text-foreground">
                      节点筛选：{traceNodeDisplayName(nodeFilter)}（{filteredNodes.length} 条）
                    </span>
                  )}
                  {fallbackFilter && (
                    <span className="ml-2 text-amber-300">
                      仅看 fallback（{filteredNodes.length} 条）
                    </span>
                  )}
                </CardDescription>
              </div>
              {allNodes.length > 0 && (
                <Badge variant="outline" className="font-mono text-[10px] shrink-0">
                  {filteredNodes.length}/{allNodes.length} 个 node
                </Badge>
              )}
            </div>
            <label className="relative block max-w-xl pt-1 text-xs text-muted-foreground">
              内容搜索
              <Search className="pointer-events-none absolute bottom-2.5 left-2.5 h-3.5 w-3.5 text-muted-foreground" />
              <input
                name="trace-node-search"
                type="search"
                autoComplete="off"
                value={searchText}
                onChange={(event) => handleSearchChange(event.target.value)}
                placeholder="搜索问题、回答摘录、评估理由、context..."
                className="mt-1 h-9 w-full rounded-md border bg-background pl-8 pr-3 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
            </label>
            <div className="flex flex-wrap gap-1.5 pt-1">
              {NODE_TYPE_FILTERS.map((t) => {
                const count =
                  t === "all"
                    ? totalNodeCount
                    : (nodeTypeCounts[traceNodeCanonicalName(t)] ?? 0);
                if (t !== "all" && count === 0) return null;
                return (
                  <button
                    type="button"
                    key={t}
                    aria-pressed={nodeFilter === t}
                    onClick={() => handleNodeFilterChange(t)}
                    className={[
                      "rounded-md border px-2 py-1 text-[11px] font-mono transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                      nodeFilter === t
                        ? "border-primary bg-primary/10 text-primary font-medium"
                        : "border-border text-muted-foreground hover:bg-muted",
                    ].join(" ")}
                  >
                    {t === "all" ? "全部" : traceNodeDisplayName(t)}
                    <span className="ml-1 text-[9px] opacity-60">{count}</span>
                  </button>
                );
              })}
              {fallbackTraceCount > 0 && (
                <button
                  type="button"
                  aria-pressed={fallbackFilter}
                  onClick={handleFallbackFilterChange}
                  className={[
                    "rounded-md border px-2 py-1 text-[11px] font-mono transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    fallbackFilter
                      ? "border-amber-400 bg-amber-500/10 text-amber-200 font-medium"
                      : "border-border text-muted-foreground hover:bg-muted",
                  ].join(" ")}
                >
                  仅看 fallback
                  <span className="ml-1 text-[9px] opacity-60">{fallbackTraceCount}</span>
                </button>
              )}
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <TraceWorkbench
              grouped={grouped}
              selectedNode={selectedNode}
              selectedNodeId={selectedNode?.id ?? selectedNodeId}
              sessionId={initialData.session_id}
              traceId={initialData.trace_id ?? initialData.session_id}
              langsmith={initialData.langsmith ?? null}
              showAdminControls={showAdminControls}
              focusedNodeId={focusedNodeId}
              prefersReducedMotion={prefersReducedMotion}
              onSelectNode={selectNode}
            />

            {filteredNodes.length === 0 && (
              <div className="rounded-md border border-dashed bg-muted/10 px-3 py-6 text-center text-sm text-muted-foreground">
                当前筛选没有命中 node。可以清空 search 或切换 node type。
              </div>
            )}

            {loadMoreError && (
              <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                加载更多失败：{loadMoreError}
              </p>
            )}

            {hasMore && (
              <div className="flex justify-center pt-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="gap-1.5"
                  onClick={loadMore}
                  disabled={loadingMore}
                >
                  {loadingMore ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <ChevronDown className="h-3.5 w-3.5" />
                  )}
                  {loadingMore
                    ? "加载中..."
                    : `加载更多（已展示 ${allNodes.length}/${totalNodeCount} 个 node）`}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function PartialTraceDiagnostics({
  diagnostics,
}: {
  diagnostics: TraceDiagnostics;
}) {
  return (
    <Card className="border-amber-500/40 bg-amber-500/[0.04]">
      <CardContent className="space-y-3 pt-6 text-sm">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-amber-300" />
          <p className="font-medium text-amber-300">链路健康提示（Trace Health）</p>
        </div>
        <div className="grid gap-2 text-xs md:grid-cols-3">
          <NodeFact label="健康状态" value={diagnostics.health} />
          <NodeFact label="会话状态" value={diagnostics.session_status ?? "—"} />
          <NodeFact label="最后节点" value={diagnostics.last_node ?? "—"} />
        </div>
        <div>
          <p className="mb-2 text-xs text-muted-foreground">缺失关键节点</p>
          <div className="flex flex-wrap gap-1.5">
            {diagnostics.missing_key_nodes.map((node) => (
              <Badge key={node} variant="outline" className="font-mono text-[10px]">
                {node}
              </Badge>
            ))}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// MissingTraceDiagnostics replaces the old "Trace 缺失" placeholder.
// We split the three plausible root causes apart so the operator does
// not have to dig into prometheus / DB to figure out *why* this
// session never landed a single generation_traces row.
function MissingTraceDiagnostics({
  sessionId,
  status,
  langsmith,
}: {
  sessionId: string;
  status?: string | null;
  langsmith: LangSmithAdminMeta | null;
}) {
  const [tracer, setTracer] = useState<TracerHealthSnapshot | null>(null);
  const [tracerError, setTracerError] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    getTracerHealth(ctrl.signal)
      .then((snap) => {
        if (!ctrl.signal.aborted) setTracer(snap);
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setTracerError(err instanceof Error ? err.message : String(err));
      });
    return () => ctrl.abort();
  }, []);

  const reasons = useMemo(() => {
    const out: { kind: "running" | "remote-only" | "write-failed" | "unknown"; text: string }[] =
      [];
    if (status === "running") {
      out.push({
        kind: "running",
        text: "会话仍在进行中（status=running），node trace 会在面试推进时陆续写入。",
      });
    }
    if (langsmith?.tracing_enabled && (tracer?.trace_write_success_total ?? 0) === 0) {
      out.push({
        kind: "remote-only",
        text: "看起来本部署仅使用 LangSmith 远端 trace，本地 generation_traces 表不会被写入。请到 LangSmith 项目页查看 run。",
      });
    }
    const failures = tracer?.trace_write_failures_total ?? 0;
    if (failures > 0) {
      out.push({
        kind: "write-failed",
        text: `本机 tracer 写入失败 ${failures} 次（trace_write_failures_total），请检查 DB 连接与磁盘空间。`,
      });
    }
    if (out.length === 0) {
      out.push({
        kind: "unknown",
        text: "已知运行状态正常但 trace 仍为空，建议手动查询 generation_traces 或检查 trace_id 是否在另一个 instance 上。",
      });
    }
    return out;
  }, [status, langsmith, tracer]);

  return (
    <Card className="border-amber-500/40 bg-amber-500/[0.04]">
      <CardContent className="space-y-3 pt-6 text-sm">
        <div className="flex items-center gap-2">
          <FileText className="h-4 w-4 text-amber-300" />
          <p className="font-medium text-amber-300">Trace 缺失 · 诊断</p>
        </div>
        <ul className="space-y-1.5 list-disc pl-5 text-muted-foreground">
          {reasons.map((reason, idx) => (
            <li key={`${reason.kind}-${idx}`}>{reason.text}</li>
          ))}
        </ul>
        {tracerError && (
          <p className="text-xs text-amber-300/80">
            诊断接口暂时不可达：{tracerError}
          </p>
        )}
        <details className="text-xs text-muted-foreground/70">
          <summary className="cursor-pointer select-none">查看 Tracer Health 原始数据</summary>
          <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded bg-secondary/30 p-2 font-mono text-[11px]">
            {tracer ? JSON.stringify(tracer, null, 2) : "loading…"}
          </pre>
        </details>
        <BackLinks sessionId={sessionId} />
      </CardContent>
    </Card>
  );
}

function BackLinks({
  sessionId,
  audience = "admin",
}: {
  sessionId: string;
  audience?: TraceExplorerAudience;
}) {
  return (
    <div className="flex flex-wrap gap-2">
      {audience === "admin" && (
        <Button asChild variant="outline" size="sm" className="gap-1.5">
          <PendingNavigationLink href="/admin">
            <ArrowLeft className="h-3.5 w-3.5" />
            返回后台
          </PendingNavigationLink>
        </Button>
      )}
      <Button asChild variant="ghost" size="sm" className="gap-1.5">
        <PendingNavigationLink href={`/interview/${sessionId}/report`}>
          查看报告
        </PendingNavigationLink>
      </Button>
      <Button asChild variant="ghost" size="sm" className="gap-1.5">
        <PendingNavigationLink href={`/interview/${sessionId}/replay`}>
          Replay
        </PendingNavigationLink>
      </Button>
    </div>
  );
}

function TraceCommandCenter({
  data,
  diagnostics,
  fallbackTraceCount,
  audience,
  loadedCount,
  nodeTypeCounts,
  totalNodeCount,
  turnCount,
}: {
  data: TraceExplorerResponse;
  diagnostics: TraceDiagnostics | null;
  fallbackTraceCount: number;
  audience: TraceExplorerAudience;
  loadedCount: number;
  nodeTypeCounts: Record<string, number>;
  totalNodeCount: number;
  turnCount: number;
}) {
  const [showAllNodeTypes, setShowAllNodeTypes] = useState(false);
  const healthTone =
    data.trace_health === "complete"
      ? "text-emerald-300"
      : data.trace_health === "partial"
        ? "text-amber-300"
        : "text-destructive";
  const missingNodes = diagnostics?.missing_key_nodes ?? [];
  const nodeDistribution = useMemo(
    () =>
      Object.entries(nodeTypeCounts)
        .filter(([, count]) => count > 0)
        .sort(
          ([leftNode, leftCount], [rightNode, rightCount]) =>
            rightCount - leftCount || leftNode.localeCompare(rightNode),
        ),
    [nodeTypeCounts],
  );
  const visibleNodeDistribution = showAllNodeTypes
    ? nodeDistribution
    : nodeDistribution.slice(0, 6);
  const hiddenNodeTypeCount = nodeDistribution.length - visibleNodeDistribution.length;

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <GitBranch className="h-4 w-4 text-emerald-400" />
              <CardTitle className="text-xl">
                {audience === "owner" ? "Session Trace" : "Trace Explorer"}
              </CardTitle>
              <Badge variant="outline" className={`font-mono text-[10px] ${healthTone}`}>
                {healthLabel[data.trace_health]}
              </Badge>
              {fallbackTraceCount > 0 && (
                <Badge variant="warn" className="font-mono text-[10px]">
                  fallback {fallbackTraceCount}
                </Badge>
              )}
            </div>
            <CardDescription className="mt-1">
              查看本次面试的 execution trace：先确认 Trace Health，再按 turn 定位 node evidence。
            </CardDescription>
            <p className="mt-2 break-all font-mono text-[11px] text-muted-foreground">
              {data.session_id}
            </p>
          </div>
          <BackLinks sessionId={data.session_id} audience={audience} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
          <SummaryTile label="会话状态" value={data.status || "unknown"} />
          <SummaryTile
            label="总分"
            value={
              typeof data.overall_score === "number"
                ? data.overall_score.toFixed(2)
                : "—"
            }
          />
          <SummaryTile label="结论" value={data.overall_verdict || "—"} />
          <SummaryTile label="轮次" value={String(turnCount)} />
          <SummaryTile label="节点数" value={String(totalNodeCount)} />
          <SummaryTile
            label="最后节点"
            value={traceNodeDisplayName(diagnostics?.last_node)}
          />
          <SummaryTile
            label="已加载"
            value={`${loadedCount}/${totalNodeCount}${data.nodes_has_more ? "+" : ""}`}
          />
        </div>
        {nodeDistribution.length > 0 && (
          <div className="space-y-2 rounded-lg border bg-muted/10 p-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-xs font-medium text-muted-foreground">节点分布</p>
              {hiddenNodeTypeCount > 0 && (
                <button
                  type="button"
                  aria-expanded={showAllNodeTypes}
                  onClick={() => setShowAllNodeTypes((current) => !current)}
                  className="rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {showAllNodeTypes ? "收起" : `展开全部 +${hiddenNodeTypeCount}`}
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5 text-xs text-muted-foreground">
              {visibleNodeDistribution.map(([node, count]) => {
                const alias = traceNodeRawAlias(node);
                const description = traceNodeDescription(node);
                return (
                  <Badge
                    key={node}
                    variant="outline"
                    translate="no"
                    className="max-w-full gap-1 text-[10px]"
                  >
                    <span className="min-w-0 truncate font-mono">
                      {traceNodeDisplayName(node)}
                    </span>
                    {description && (
                      <span className="min-w-0 truncate text-[9px] text-muted-foreground">
                        {description}
                      </span>
                    )}
                    {alias && (
                      <span className="min-w-0 truncate font-mono text-[9px] text-muted-foreground">
                        {alias}
                      </span>
                    )}
                    <span className="shrink-0 font-mono tabular-nums text-muted-foreground">
                      {count}
                    </span>
                  </Badge>
                );
              })}
            </div>
          </div>
        )}
        {fallbackTraceCount > 0 && (
          <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
            <Badge variant="warn" className="font-mono text-[10px]">
              Evaluator Fallback {fallbackTraceCount}
            </Badge>
          </div>
        )}
        {missingNodes.length > 0 && (
          <div className="rounded-md border border-amber-500/30 bg-amber-500/[0.04] p-3 text-xs">
            <p className="font-medium text-amber-300">缺失关键节点</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {missingNodes.map((node) => (
                <Badge key={node} variant="outline" className="font-mono text-[10px]">
                  {node}
                </Badge>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function SummaryTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border bg-card/50 p-3">
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 break-words text-sm font-medium">{value}</p>
    </div>
  );
}

function TraceWorkbench({
  grouped,
  selectedNode,
  selectedNodeId,
  sessionId,
  traceId,
  langsmith,
  showAdminControls,
  focusedNodeId,
  prefersReducedMotion,
  onSelectNode,
}: {
  grouped: { label: string; nodes: TraceExplorerNode[] }[];
  selectedNode: TraceExplorerNode | null;
  selectedNodeId: number | null;
  sessionId: string;
  traceId: string;
  langsmith: LangSmithAdminMeta | null;
  showAdminControls: boolean;
  focusedNodeId: number | null;
  prefersReducedMotion: boolean;
  onSelectNode: (node: TraceExplorerNode) => void;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(220px,0.8fr)_minmax(0,1.7fr)]">
      <TraceTurnRail
        grouped={grouped}
        selectedNodeId={selectedNodeId}
        focusedNodeId={focusedNodeId}
        onSelectNode={onSelectNode}
      />
      <TraceNodeDetail
        node={selectedNode}
        sessionId={sessionId}
        traceId={traceId}
        langsmith={langsmith}
        showAdminControls={showAdminControls}
        focused={Boolean(selectedNode && focusedNodeId === selectedNode.id)}
        prefersReducedMotion={prefersReducedMotion}
      />
    </div>
  );
}

function TraceTurnRail({
  grouped,
  selectedNodeId,
  focusedNodeId,
  onSelectNode,
}: {
  grouped: { label: string; nodes: TraceExplorerNode[] }[];
  selectedNodeId: number | null;
  focusedNodeId: number | null;
  onSelectNode: (node: TraceExplorerNode) => void;
}) {
  return (
    <aside className="space-y-3 lg:sticky lg:top-4 lg:max-h-[calc(100dvh-2rem)] lg:overflow-auto">
      {grouped.map((group) => (
        <div
          key={group.label}
          className="space-y-2 [contain-intrinsic-size:1px_160px] [content-visibility:auto]"
        >
          <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
            {group.label}
          </p>
          <div className="space-y-1.5">
            {group.nodes.map((node) => {
              const selected = selectedNodeId === node.id;
              const focused = focusedNodeId === node.id;
              const nodeAlias = traceNodeRawAlias(node.node, node.payload);
              const nodeDescription = traceNodeDescription(node.node, node.payload);
              const isOpeningNode = isSessionOpeningNode(node.node);
              const isClosingNode = isSessionClosingNode(node.node);
              return (
                <button
                  key={node.id}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => onSelectNode(node)}
                  className={[
                    "w-full rounded-md border px-2.5 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    selected
                      ? "border-primary bg-primary/10 text-foreground"
                      : "border-border bg-card/40 text-muted-foreground hover:bg-muted hover:text-foreground",
                    focused ? "ring-1 ring-amber-400/70" : "",
                  ].join(" ")}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate font-mono text-[11px] font-medium">
                      {traceNodeDisplayName(node.node, node.payload)}
                    </span>
                    {typeof node.score === "number" && (
                      <span className="font-mono text-[10px] tabular-nums">
                        {node.score.toFixed(1)}
                      </span>
                    )}
                  </div>
                  {(nodeDescription ||
                    nodeAlias ||
                    isVirtualTraceNode(node.node) ||
                    isOpeningNode ||
                    isClosingNode) && (
                    <div className="mt-0.5 flex min-w-0 flex-wrap items-center gap-1 text-[9px] text-muted-foreground">
                      {isOpeningNode && (
                        <span className="truncate">准备/开场阶段</span>
                      )}
                      {isClosingNode && (
                        <span className="truncate">收尾阶段</span>
                      )}
                      {nodeDescription && (
                        <span className="truncate">{nodeDescription}</span>
                      )}
                      {isVirtualTraceNode(node.node) && (
                        <span className="rounded border border-sky-500/25 px-1 font-mono text-[8px] uppercase tracking-wide text-sky-200">
                          route_after_eval
                        </span>
                      )}
                      {nodeAlias && (
                        <span className="truncate font-mono">{nodeAlias}</span>
                      )}
                    </div>
                  )}
                  <div className="mt-1 flex flex-wrap gap-1">
                    {node.dimension && !isOpeningNode && !isClosingNode && (
                      <Badge variant="outline" className="max-w-full truncate text-[9px]">
                        {node.dimension}
                      </Badge>
                    )}
                    {isEvaluatorFallbackTrace(node) && (
                      <Badge variant="warn" className="text-[9px]">
                        fallback
                      </Badge>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      ))}
    </aside>
  );
}

function TraceNodeDetail({
  node,
  sessionId,
  traceId,
  langsmith,
  showAdminControls,
  focused,
  prefersReducedMotion,
}: {
  node: TraceExplorerNode | null;
  sessionId: string;
  traceId: string;
  langsmith: LangSmithAdminMeta | null;
  showAdminControls: boolean;
  focused: boolean;
  prefersReducedMotion: boolean;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [annotating, setAnnotating] = useState(false);
  const openAnnotation = useCallback(() => setAnnotating(true), []);
  const closeAnnotation = useCallback(() => setAnnotating(false), []);

  useEffect(() => {
    if (focused && ref.current) {
      ref.current.scrollIntoView({
        behavior: prefersReducedMotion ? "auto" : "smooth",
        block: "center",
      });
    }
  }, [focused, prefersReducedMotion]);

  if (!node) {
    return (
      <div className="rounded-lg border border-dashed bg-muted/10 p-6 text-sm text-muted-foreground">
        选择左侧 timeline 里的 node 查看详情。
      </div>
    );
  }

  const langsmithUrl = showAdminControls
    ? buildLangSmithRunUrl(node.langsmith_run_id, langsmith)
    : null;
  const isFallback = isEvaluatorFallbackTrace(node);
  const rawPayload = {
    payload: node.payload,
    evaluation: node.evaluation,
    policy_context_keys: node.policy_context_keys,
    answer_excerpt: node.answer_excerpt,
  };
  const isClosingNode = isSessionClosingNode(node.node);
  const isOpeningNode = isSessionOpeningNode(node.node);
  const nodeAlias = traceNodeRawAlias(node.node, node.payload);
  const nodeDescription = traceNodeDescription(node.node, node.payload);
  const strategyContextKeys = strategyPolicyContextKeys(node);

  return (
    <div
      ref={ref}
      className={`rounded-lg border bg-card/50 p-3 text-sm ${
        focused ? "ring-2 ring-amber-400/60" : ""
      }`}
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="font-mono text-[10px]">
              {traceNodeDisplayName(node.node, node.payload)}
            </Badge>
            {nodeDescription && (
              <span className="text-[11px] text-muted-foreground">
                {nodeDescription}
              </span>
            )}
            {isVirtualTraceNode(node.node) && (
              <Badge variant="secondary" className="font-mono text-[9px]">
                route_after_eval
              </Badge>
            )}
            {nodeAlias && (
              <span className="font-mono text-[11px] text-muted-foreground">
                {nodeAlias}
              </span>
            )}
            {node.dimension && !isOpeningNode && !isClosingNode && (
              <span className="text-xs text-muted-foreground">{node.dimension}</span>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {showAdminControls && node.action_id && (
            <Badge variant="secondary">{node.action_id}</Badge>
          )}
          {typeof node.score === "number" && (
            <Badge variant={node.passed ? "success" : "warn"}>
              {node.score.toFixed(1)}
            </Badge>
          )}
          {showAdminControls && typeof node.immediate_reward === "number" && (
            <Badge variant="outline">reward {node.immediate_reward.toFixed(2)}</Badge>
          )}
          {isFallback && <Badge variant="warn">Evaluator fallback</Badge>}
          {langsmithUrl && (
            <a
              href={langsmithUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 rounded-md border bg-background/80 px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider text-muted-foreground hover:text-foreground"
              aria-label="在 LangSmith 中打开此次 run"
            >
              LangSmith
              <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      </div>

      <div className="mt-3 grid gap-2 text-xs md:grid-cols-3">
        <NodeFact label="轮次" value={isOpeningNode ? "准备/开场阶段" : isClosingNode ? "收尾阶段" : String(node.turn_idx ?? "session")} />
        {showAdminControls && (
          <>
            <NodeFact label="策略上下文" value={displayStrategyContextKey(node)} />
            <NodeFact label="策略" value={node.policy_id || "-"} />
          </>
        )}
        <NodeFact label="创建时间" value={formatTs(node.created_at)} />
      </div>
      {showAdminControls && strategyContextKeys.length > 0 && (
        <NodeFact label="策略上下文键" value={strategyContextKeys.join(", ")} />
      )}

      {node.node === "reward_update" ? (
        <RewardQuestionContext value={node.question} />
      ) : !isOpeningNode && !isClosingNode && !isTurnFinalizeNode(node.node) ? (
        <TraceTextExcerpt label="问题" value={node.question} />
      ) : null}

      {node.node === "director_sample" && (
        <StrategyDecisionSummary node={node} />
      )}

      {showAdminControls && <NodeTimingBar payload={node.payload} />}

      <OpeningPreparationPanel node={node} showAdminControls={showAdminControls} />
      <TurnFinalizePanel node={node} />
      <RouteDecisionPanel node={node} />
      <RefineFollowupPanel node={node} />
      <FinalReportPanel node={node} />
      <TrainingPlanPanel node={node} />
      <RewardUpdatePanel node={node} />
      <ExperienceExtractorPanel node={node} />

      {node.node !== "ask_question" &&
        node.node !== "route_decision" &&
        node.node !== "refine_followup" &&
        node.node !== "final_report" &&
        node.node !== "training_plan" &&
        !isTurnFinalizeNode(node.node) &&
        node.node !== "reward_update" &&
        node.node !== "experience_extractor" &&
        !isOpeningNode &&
        node.answer_excerpt && (
        <TraceTextExcerpt label="回答摘录" value={node.answer_excerpt} />
      )}

      <VerificationReviewPanel node={node} />

      <EvaluatorScoringBasis node={node} />

      <EvaluationEvidence node={node} />

      {node.node === "ask_question" && (
        <AskQuestionEvidencePanel node={node} />
      )}

      {showAdminControls && (
        <div className="mt-3 flex items-center gap-2">
          <RawTracePayloadDetails rawPayload={rawPayload} />
          <Button
            variant="ghost"
            size="sm"
            className="shrink-0 gap-1 text-[10px]"
            onClick={openAnnotation}
          >
            <FileText className="h-3 w-3" />
            标注
          </Button>
        </div>
      )}
      {showAdminControls && annotating && (
        <TraceAnnotationDialog
          traceId={traceId}
          sessionId={sessionId}
          turnIdx={node.turn_idx ?? 0}
          generationTraceId={node.id}
          nodeName={node.node}
          onClose={closeAnnotation}
        />
      )}
    </div>
  );
}

function OpeningPreparationPanel({
  node,
  showAdminControls,
}: {
  node: TraceExplorerNode;
  showAdminControls: boolean;
}) {
  if (!isSessionOpeningNode(node.node)) return null;

  const payload = recordFromUnknown(node.payload);
  const canonical = traceNodeCanonicalName(node.node);
  const resumeVectorStatus = recordFromUnknown(payload.resume_vector_status);
  const selfIntroVectorStatus = recordFromUnknown(payload.self_intro_vector_status);
  const dimensionStatusSummary = recordFromUnknown(payload.dimension_status_summary);
  const scoreInitSummary = recordFromUnknown(payload.scores_per_dim_summary);
  const profileSummary = recordFromUnknown(payload.profile_summary);
  const anchorCardsSummary = recordFromUnknown(payload.anchor_cards_summary);
  const resumeAnchors = recordArray(payload.resume_anchors);
  const selfIntroProfileSnapshot = recordFromUnknown(payload.self_intro_profile_snapshot);
  const selfIntroAnchorCards = recordArray(payload.self_intro_anchor_cards);
  const selfIntroCommunication = recordFromUnknown(payload.self_intro_communication);
  const selfIntroDownstreamUsage = recordFromUnknown(payload.self_intro_downstream_usage);
  const displayName =
    traceNodeDescription(node.node, node.payload) ||
    traceNodeDisplayName(node.node, node.payload);
  const railSummary = openingNodeRailSummary(node);

  return (
    <section className="mt-3 rounded-md border border-emerald-500/25 bg-emerald-500/[0.035] p-3 text-xs">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <GitBranch className="h-3.5 w-3.5 text-emerald-300" />
            <p className="font-mono font-medium text-emerald-100">{canonical}</p>
            <span className="text-[11px] text-muted-foreground">{displayName}</span>
            <Badge variant="outline" className="font-mono text-[9px]">
              opening
            </Badge>
          </div>
          <p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-muted-foreground">
            发生在正式提问循环之前，用来锁定面试上下文、完成开场问题与自我介绍解析；这些记录不计入正式 Turn。
          </p>
        </div>
        <Badge variant="secondary" className="text-[10px]">
          准备/开场阶段
        </Badge>
      </div>

      <div className="mt-3 grid gap-2 lg:grid-cols-2">
        <div className="rounded-md border bg-background/50 p-3 lg:col-span-2">
          <p className="font-medium">准备上下文</p>
          <div className="mt-2 grid gap-2 md:grid-cols-3">
            <NodeFact label="节点" value={canonical} />
            <NodeFact label="阶段" value="准备/开场阶段" />
            <NodeFact label="摘要" value={railSummary || "—"} />
          </div>
        </div>

        {canonical === "resume_parse" && (
          <>
            <div className="rounded-md border bg-background/50 p-3 lg:col-span-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium">面试锚点池</p>
                <Badge variant="outline" className="font-mono text-[9px]">
                  {formatCountValue(resumeAnchors.length)}
                </Badge>
              </div>
              <div className="mt-2 grid gap-2">
                <NodeFact label="摘要" value={formatResumeAnchors(payload.resume_anchors)} />
                <ResumeAnchorDetails anchors={resumeAnchors} />
              </div>
            </div>
            <div className="rounded-md border bg-background/50 p-3">
              <p className="font-medium">简历项目锚点</p>
              <div className="mt-2 grid gap-2">
                <NodeFact label="项目数" value={formatCountValue(payload.resume_projects_count)} />
                <NodeFact label="项目列表" value={formatResumeProjects(payload.resume_projects)} />
              </div>
            </div>
            <div className="rounded-md border bg-background/50 p-3">
              <p className="font-medium">面试重点</p>
              <div className="mt-2 grid gap-2">
                <NodeFact label="重点数" value={formatCountValue(payload.resume_focus_areas_count)} />
                <NodeFact label="重点列表" value={formatResumeFocusAreas(payload.resume_focus_areas)} />
              </div>
            </div>
            <div className="rounded-md border bg-background/50 p-3">
              <p className="font-medium">技能信号</p>
              <div className="mt-2 grid gap-2">
                <NodeFact label="简历技能" value={formatDimensionNames(payload.candidate_skills)} />
                <NodeFact label="JD 技能" value={formatDimensionNames(payload.required_skills)} />
                <NodeFact label="交集提示" value={formatSkillSignals(payload.candidate_skills, payload.required_skills)} />
              </div>
            </div>
            <div className="rounded-md border bg-background/50 p-3">
              <p className="font-medium">评估维度</p>
              <div className="mt-2 grid gap-2">
                <NodeFact label="维度列表" value={formatDimensionNames(payload.rubric_dimensions || payload.dimensions)} />
                <NodeFact label="维度数" value={formatCountValue(payload.dimensions_count)} />
                {showAdminControls && (
                  <NodeFact label="初始化" value={`${formatDimensionStatusSummary(dimensionStatusSummary)} · ${formatScoreInitSummary(scoreInitSummary)}`} />
                )}
              </div>
            </div>
            <OpeningStatusCard
              heading="简历向量"
              status={resumeVectorStatus}
              modeLabel="source_type"
              showDetails={showAdminControls}
            />
          </>
        )}

        {canonical === "self_intro_question" && (
          <>
            <div className="rounded-md border bg-background/50 p-3">
              <p className="font-medium">开场问题</p>
              <div className="mt-2 grid gap-2">
                <NodeFact label="问题类型" value={stringValue(payload.question_type) || "—"} />
                <NodeFact label="目标维度" value={stringValue(payload.dimension) || node.dimension || "—"} />
                <NodeFact label="Rubric 点" value={stringList(payload.rubric_points).join(", ") || "—"} />
              </div>
            </div>
            <div className="rounded-md border bg-background/50 p-3">
              <p className="font-medium">流转位置</p>
              <div className="mt-2 grid gap-2">
                <NodeFact label="上游" value="resume_parse" />
                <NodeFact label="下游" value="wait_answer -> self_intro_parse" />
                <NodeFact label="正式轮次" value="未开始" />
              </div>
            </div>
          </>
        )}

        {canonical === "self_intro_parse" && (
          <>
            <div className="rounded-md border bg-background/50 p-3 lg:col-span-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium">开场画像</p>
                <Badge variant="outline" className="font-mono text-[9px]">
                  {stringValue(payload.parse_status) || "—"}
                </Badge>
              </div>
              <div className="mt-2 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                <NodeFact label="项目" value={formatDimensionNames(selfIntroProfileSnapshot.emphasized_projects)} />
                <NodeFact label="技能" value={formatDimensionNames(selfIntroProfileSnapshot.emphasized_skills)} />
                <NodeFact label="关注点" value={formatDimensionNames(selfIntroProfileSnapshot.preferred_focus)} />
                <NodeFact label="待澄清" value={formatDimensionNames(selfIntroProfileSnapshot.clarification_targets)} />
                <NodeFact label="项目数" value={formatCountValue(payload.emphasized_projects_count)} />
                <NodeFact label="技能数" value={formatCountValue(payload.emphasized_skills_count)} />
                <NodeFact label="画像摘要" value={formatSelfIntroProfileSnapshot(payload.self_intro_profile_snapshot)} />
                <NodeFact label="字段覆盖" value={formatProfileFieldsPresent(payload.profile_fields_present)} />
                <NodeFact label="解析信号" value={formatProfileSummary(profileSummary)} />
              </div>
            </div>
            <div className="rounded-md border bg-background/50 p-3 lg:col-span-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium">自我介绍追问锚点</p>
                <Badge variant="outline" className="font-mono text-[9px]">
                  {formatCountValue(selfIntroAnchorCards.length || anchorCardsSummary.total)}
                </Badge>
              </div>
              <div className="mt-2 grid gap-2">
                <NodeFact label="摘要" value={formatSelfIntroAnchorCards(payload.self_intro_anchor_cards)} />
                <NodeFact label="来源" value={formatSelfIntroAnchorSourceSummary(payload.self_intro_anchor_cards)} />
                <SelfIntroAnchorDetails cards={selfIntroAnchorCards} />
              </div>
            </div>
            <div className="rounded-md border bg-background/50 p-3">
              <p className="font-medium">沟通与澄清信号</p>
              <div className="mt-2 grid gap-2">
                <NodeFact label="摘要" value={formatSelfIntroCommunication(payload.self_intro_communication)} />
                <NodeFact label="结构" value={stringValue(selfIntroCommunication.structure) || "—"} />
                <NodeFact label="澄清项" value={formatCountValue(selfIntroCommunication.clarification_targets_count)} />
                <NodeFact label="notes" value={formatCountValue(selfIntroCommunication.notes_count)} />
              </div>
            </div>
            <div className="rounded-md border bg-background/50 p-3">
              <p className="font-medium">下游用途</p>
              <div className="mt-2 grid gap-2">
                <NodeFact label="摘要" value={formatSelfIntroDownstreamUsage(payload.self_intro_downstream_usage)} />
                <NodeFact label="调度信号" value={formatDimensionNames(selfIntroDownstreamUsage.anchor_scheduler_signals)} />
                <NodeFact label="技能选择" value={stringValue(selfIntroDownstreamUsage.skill_focus_signal) || "—"} />
                <NodeFact label="RAG 来源" value={stringValue(selfIntroDownstreamUsage.rag_source) || "—"} />
                <NodeFact label="下游节点" value={formatDimensionNames(selfIntroDownstreamUsage.next_nodes)} />
              </div>
            </div>
            <OpeningStatusCard
              heading="自我介绍向量"
              status={selfIntroVectorStatus}
              modeLabel="mode"
              showDetails={showAdminControls}
            />
          </>
        )}
      </div>

      {canonical === "self_intro_question" && node.question && (
        <div className="mt-3">
          <TraceTextExcerpt label="开场问题文本" value={node.question} />
        </div>
      )}
    </section>
  );
}

function ResumeAnchorDetails({ anchors }: { anchors: Record<string, unknown>[] }) {
  if (anchors.length === 0) {
    return <NodeFact label="Anchor" value="—" />;
  }

  return (
    <details
      aria-label="查看锚点详情，默认折叠"
      className="rounded-md border bg-background/40 p-2"
    >
      <summary className="cursor-pointer select-none font-medium text-muted-foreground">
        查看锚点详情
      </summary>
      <div className="mt-2 grid gap-2">
        {anchors.slice(0, 6).map((anchor, index) => (
          <div
            key={`${stringValue(anchor.label) || "anchor"}-${index}`}
            className="rounded-md border bg-background/50 p-2"
          >
            <div className="anchor-main-row grid min-w-0 gap-2 xl:grid-cols-3">
              <NodeFact label="Anchor" value={stringValue(anchor.label) || "—"} />
              <NodeFact label="项目" value={stringValue(anchor.project_name) || "—"} />
              <NodeFact label="维度" value={formatDimensionNames(anchor.dimensions)} />
            </div>
            <div className="anchor-detail-row mt-2 grid min-w-0 gap-2 xl:grid-cols-3">
              <NodeFact label="技术栈" value={formatDimensionNames(anchor.tech_stack)} />
              <NodeFact label="追问点" value={formatDimensionNames(anchor.question_anchors)} />
              <NodeFact label="技能" value={formatDimensionNames(anchor.skills)} />
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}

function SelfIntroAnchorDetails({ cards }: { cards: Record<string, unknown>[] }) {
  if (cards.length === 0) {
    return <NodeFact label="锚点" value="—" />;
  }

  return (
    <details
      aria-label="查看自我介绍锚点详情，默认折叠"
      className="rounded-md border bg-background/40 p-2"
    >
      <summary className="cursor-pointer select-none font-medium text-muted-foreground">
        查看自我介绍锚点详情
      </summary>
      <div className="mt-2 grid gap-2">
        {cards.slice(0, 6).map((card, index) => (
          <div
            key={`${stringValue(card.title) || "self-intro-card"}-${index}`}
            className="rounded-md border bg-background/50 p-2"
          >
            <div className="grid min-w-0 gap-2 lg:grid-cols-2">
              <NodeFact label="类型" value={selfIntroKindLabel(stringValue(card.kind))} />
              <NodeFact label="来源" value={selfIntroSourceLabel(stringValue(card.source))} />
            </div>
            <div className="mt-2 grid min-w-0 gap-2 lg:grid-cols-2">
              <NodeFact label="标题" value={stringValue(card.title) || "—"} />
              <NodeFact label="关键词" value={formatDimensionNames(card.tech_keywords)} />
            </div>
          </div>
        ))}
      </div>
    </details>
  );
}

function OpeningStatusCard({
  heading,
  status,
  modeLabel,
  showDetails = true,
}: {
  heading: string;
  status: Record<string, unknown>;
  modeLabel: string;
  showDetails?: boolean;
}) {
  return (
    <div className="rounded-md border bg-background/50 p-3">
      <p className="font-medium">{heading}</p>
      <div className="mt-2 grid gap-2">
        <NodeFact label="状态" value={stringValue(status.status) || "—"} />
        {showDetails && (
          <>
            <NodeFact label={modeLabel} value={stringValue(status[modeLabel]) || stringValue(status.source_type) || "—"} />
            <NodeFact label="chunk 数" value={formatCountValue(status.chunk_count)} />
            <NodeFact label="跳过原因" value={stringValue(status.skipped_reason) || "—"} />
          </>
        )}
      </div>
    </div>
  );
}

function TurnFinalizePanel({ node }: { node: TraceExplorerNode }) {
  if (!isTurnFinalizeNode(node.node)) return null;

  const payload = recordFromUnknown(node.payload);
  const rawAnswerCleared =
    payload.raw_answer_cleared ?? payload.cleared_raw_answer;
  const reason = stringValue(payload.reason) || "legacy";
  const reasonLabel =
    reason === "turn_finalize" ? "整理完成" : reason === "legacy" ? "旧 trace" : reason;
  const nextStep = stringValue(payload.next_step) || "route_decision";
  const historyProjectionOwner =
    stringValue(payload.history_projection_owner) || "ask_question";

  return (
    <section className="mt-3 rounded-lg border border-cyan-500/30 bg-cyan-950/10 p-4 text-sm">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <GitBranch className="h-4 w-4 text-cyan-300" />
            <p className="font-mono font-medium text-cyan-100">turn_finalize</p>
            <span className="text-xs text-muted-foreground">轮次收尾</span>
            <Badge variant="outline" className="font-mono text-[10px]">
              real workflow node
            </Badge>
          </div>
          <p className="mt-2 max-w-3xl text-xs leading-relaxed text-muted-foreground">
            本节点发生在 reward_update 后、route_decision 前；负责清理本轮临时状态，不再维护历史摘要。
            它不生成问题、不评分、不决定下一步。
          </p>
          <p className="mt-1 max-w-3xl text-xs leading-relaxed text-muted-foreground">
            历史上下文由下一轮 ask_question 的 HistoryContextBuilder 从完整 qa_history 构建。
          </p>
        </div>
        <Badge variant="secondary" className="self-start whitespace-nowrap text-[10px]">
          {reasonLabel}
        </Badge>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-3">
        <div className="rounded-md border bg-background/50 p-3">
          <p className="font-medium">状态清理</p>
          <div className="mt-2 grid gap-2 text-xs">
            <NodeFact
              label="原始回答已清理"
              value={formatBooleanValue(rawAnswerCleared)}
            />
            <NodeFact label="记录状态" value={reasonLabel} />
          </div>
        </div>
        <div className="rounded-md border bg-background/50 p-3">
          <p className="font-medium">历史上下文归属</p>
          <div className="mt-2 grid gap-2 text-xs">
            <NodeFact
              label="摘要已更新"
              value={formatBooleanValue(payload.summary_updated)}
            />
            <NodeFact
              label="摘要模式 summary_mode"
              value={formatDiagnosticScalar(payload.summary_mode)}
            />
            <NodeFact
              label="历史投影归属"
              value={historyProjectionOwner}
            />
            <NodeFact
              label="旧压缩写入数"
              value={formatCountValue(payload.compressed_turns)}
            />
            <NodeFact
              label="QA 历史数"
              value={formatCountValue(payload.qa_history_count)}
            />
          </div>
        </div>
        <div className="rounded-md border bg-background/50 p-3">
          <p className="font-medium">路由前整理</p>
          <div className="mt-2 grid gap-2 text-xs">
            <NodeFact label="下一步 next_step" value={nextStep} />
            <NodeFact
              label="节点位置"
              value="reward_update -> turn_finalize -> route_decision"
            />
            <NodeFact label="决策责任" value="由 route_after_eval 条件边执行" />
          </div>
        </div>
      </div>
    </section>
  );
}

function RouteDecisionPanel({ node }: { node: TraceExplorerNode }) {
  if (node.node !== "route_decision") return null;

  const payload = recordFromUnknown(node.payload);
  const inputs = recordFromUnknown(payload.decision_inputs);
  const decision = stringValue(payload.decision);
  const nextNode = stringValue(payload.next_node) || routeDecisionNextNode(decision);
  const reason = stringValue(payload.decision_reason);
  const dimension =
    stringValue(payload.dimension) ||
    stringValue(inputs.current_dimension) ||
    node.dimension ||
    "—";
  const formalTurn = payload.formal_turn_idx ?? inputs.formal_turn_idx;
  const maxTurns = payload.max_turns ?? inputs.max_turns;
  const budget =
    payload.turn_budget_remaining ?? inputs.turn_budget_remaining;

  return (
    <section className="mt-3 rounded-md border border-sky-500/25 bg-sky-500/[0.035] p-3 text-xs">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <GitBranch className="h-3.5 w-3.5 text-sky-300" />
            <p className="font-mono font-medium text-sky-100">route_decision</p>
            <span className="text-[11px] text-muted-foreground">路由决策</span>
            <Badge variant="outline" className="font-mono text-[9px]">
              route_after_eval
            </Badge>
            <span className="text-[11px] text-muted-foreground">条件边诊断</span>
          </div>
          <p className="mt-1 max-w-3xl text-[11px] text-muted-foreground">
            这条记录不是真实 workflow node，而是 turn_finalize 后的 route_after_eval 条件边诊断；它诊断出 refine / next_question / end，并把 workflow 路由到对应的真实节点。评分细节请看同一 Turn 的 evaluator / verification。
          </p>
        </div>
        <Badge variant={routeDecisionBadgeVariant(decision)} className="text-[10px]">
          {routeDecisionLabel(decision)}
        </Badge>
      </div>

      {!reason && (
        <p className="mt-3 rounded-md border border-amber-500/25 bg-amber-500/[0.06] p-2 text-[11px] text-amber-200">
          旧 trace 未记录路由原因；这里只能展示已有 decision / recommended_next / passed / budget。
        </p>
      )}

      <div className="mt-3 grid gap-2 md:grid-cols-2 lg:grid-cols-4">
        <NodeFact label="路由结果" value={routeDecisionLabel(decision)} />
        <NodeFact label="下一节点" value={nextNode || "—"} />
        <NodeFact
          label="决策原因"
          value={routeDecisionReasonLabel(reason)}
        />
        <NodeFact label="当前维度" value={dimension} />
        <NodeFact
          label="Evaluator 建议"
          value={stringValue(payload.recommended_next) || "—"}
        />
        <NodeFact
          label="推荐计划"
          value={stringValue(payload.recommended_next_plan) || "—"}
        />
        <NodeFact
          label="追问意图"
          value={stringValue(payload.recommended_probe_intent) || "—"}
        />
        <NodeFact label="是否通过" value={formatBooleanValue(payload.passed)} />
        <NodeFact label="fallback" value={formatBooleanValue(payload.fallback)} />
        <NodeFact
          label="轮次进度"
          value={formatRouteTurnProgress(formalTurn, maxTurns)}
        />
        <NodeFact label="剩余预算" value={formatDiagnosticScalar(budget)} />
        <NodeFact
          label="覆盖推进"
          value={formatBooleanValue(inputs.coverage_advance)}
        />
        <NodeFact
          label="锚点扩展"
          value={formatBooleanValue(inputs.has_anchor_expansion_slot)}
        />
        <NodeFact
          label="当前维度尝试"
          value={formatRouteAttemptValue(
            inputs.current_dimension_attempts,
            inputs.max_refines_per_dimension,
          )}
        />
        <NodeFact
          label="仍有待覆盖维度"
          value={formatBooleanValue(inputs.has_pending_other_dimension)}
        />
        <NodeFact
          label="评估来源"
          value={stringValue(payload.evaluation_source) || "—"}
        />
        <NodeFact
          label="fallback 原因"
          value={stringValue(payload.fallback_reason) || "—"}
        />
      </div>

      <div className="mt-3 rounded-md border bg-background/50 p-2">
        <p className="font-medium">后续影响</p>
        <p className="mt-1 break-words text-[11px] leading-relaxed text-muted-foreground">
          {routeDecisionEffect(decision, nextNode)}
        </p>
      </div>
    </section>
  );
}

function RefineFollowupPanel({ node }: { node: TraceExplorerNode }) {
  if (node.node !== "refine_followup") return null;

  const payload = recordFromUnknown(node.payload);
  const hints = recordFromUnknown(payload.pending_contract_hints);
  const hasHints = Object.keys(hints).length > 0;
  const planTemplate =
    stringValue(payload.pending_plan_template) ||
    stringValue(payload.next_template);
  const mustAddress = stringList(hints.must_address);
  const missingMustCover = stringList(hints.missing_must_cover);
  const failureCategories =
    stringList(payload.failure_categories).length > 0
      ? stringList(payload.failure_categories)
      : stringList(hints.failure_categories);
  const priorSoftWarnings =
    stringList(payload.prior_soft_warnings).length > 0
      ? stringList(payload.prior_soft_warnings)
      : stringList(hints.prior_soft_warnings);
  const probeIntent =
    stringValue(payload.probe_intent) || stringValue(hints.probe_intent);
  const failureReason =
    stringValue(payload.failure_reason) || stringValue(hints.failure_reason);

  return (
    <section className="mt-3 rounded-md border border-amber-500/25 bg-amber-500/[0.035] p-3 text-xs">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <GitBranch className="h-3.5 w-3.5 text-amber-300" />
            <p className="font-medium text-amber-100">追问准备</p>
          </div>
          <p className="mt-1 max-w-3xl text-[11px] text-muted-foreground">
            本节点承接 route_decision=refine，把 evaluator / verification 的评分信号整理成下一轮 ask_question 可用的追问提示。
          </p>
        </div>
        <Badge variant={hasHints ? "warn" : "outline"} className="text-[10px]">
          真实 workflow node
        </Badge>
      </div>

      {!hasHints && !planTemplate && (
        <p className="mt-3 rounded-md border border-amber-500/25 bg-amber-500/[0.06] p-2 text-[11px] text-amber-200">
          旧 trace 未记录追问提示；只能查看 raw payload。
        </p>
      )}

      <div className="mt-3 grid gap-2 md:grid-cols-2 lg:grid-cols-3">
        <NodeFact label="下一轮计划模板" value={planTemplate || "—"} />
        <NodeFact
          label="目标维度"
          value={stringValue(payload.dimension) || node.dimension || "—"}
        />
        <NodeFact label="refine_mode" value={formatBooleanValue(payload.refine_mode)} />
        <NodeFact
          label="必须处理"
          value={formatCountValue(payload.must_address_count ?? mustAddress.length)}
        />
        <NodeFact
          label="缺失覆盖项"
          value={formatCountValue(
            payload.missing_must_cover_count ?? missingMustCover.length,
          )}
        />
        <NodeFact label="probe intent" value={probeIntent || "—"} />
        <NodeFact label="failure reason" value={failureReason || "—"} />
        <NodeFact
          label="failure categories"
          value={failureCategories.length > 0 ? failureCategories.join(", ") : "—"}
        />
        <NodeFact
          label="soft warnings"
          value={priorSoftWarnings.length > 0 ? String(priorSoftWarnings.length) : "—"}
        />
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <EvidenceList label="must_address" values={mustAddress} />
        <EvidenceList label="missing_must_cover" values={missingMustCover} />
        <EvidenceList label="failure_categories" values={failureCategories} />
        <EvidenceList label="prior_soft_warnings" values={priorSoftWarnings} />
      </div>

      {hasHints && (
        <details className="mt-3 rounded-md border bg-background/50 p-2">
          <summary className="cursor-pointer select-none font-medium">
            展开追问提示 <span className="font-mono">pending_contract_hints</span>
          </summary>
          <div className="mt-2 grid gap-2 md:grid-cols-2">
            {Object.entries(hints).map(([key, value]) => (
              <NodeFact
                key={key}
                label={refineHintKeyLabel(key)}
                value={formatDiagnosticScalar(value) || "—"}
              />
            ))}
          </div>
        </details>
      )}
    </section>
  );
}

function FinalReportPanel({ node }: { node: TraceExplorerNode }) {
  if (node.node !== "final_report") return null;

  const payload = recordFromUnknown(node.payload);
  const reportSummary = recordFromUnknown(payload.report_summary);
  const scoringCredibility = recordFromUnknown(payload.scoring_credibility);
  const evidenceSummary = recordFromUnknown(scoringCredibility.evidence_summary);
  const contractSummary = recordFromUnknown(scoringCredibility.contract_summary);
  const closingChain = recordFromUnknown(payload.closing_chain);
  const workflowArtifacts = recordFromUnknown(payload.workflow_artifacts);
  const dimensionResults = recordArray(payload.dimension_results);
  const dimensionEvidence = recordArray(payload.dimension_evidence);
  const status =
    stringValue(reportSummary.report_status) ||
    stringValue(payload.report_status) ||
    stringValue(payload.final_status) ||
    "—";
  const missingSections = stringList(payload.missing_sections);
  const summary = stringValue(payload.summary);
  const riskFlags = stringList(scoringCredibility.risk_flags);
  const coverageWarnings = recordArray(scoringCredibility.coverage_warnings);
  const latestAction = recordFromUnknown(workflowArtifacts.latest_selected_action);
  const latestAskPlan = recordFromUnknown(workflowArtifacts.latest_ask_plan);
  const latestContract = recordFromUnknown(workflowArtifacts.latest_contract);
  const latestVerification = recordFromUnknown(workflowArtifacts.latest_verification);

  return (
    <section className="mt-3 rounded-md border border-emerald-500/25 bg-emerald-500/[0.035] p-3 text-xs">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <FileText className="h-3.5 w-3.5 text-emerald-300" />
            <p className="font-medium text-emerald-100">报告收尾</p>
          </div>
          <p className="mt-1 max-w-3xl text-[11px] text-muted-foreground">
            本节点承接 route_decision=end，汇总面试结果并进入训练计划 / 经验抽取收尾链路。
          </p>
        </div>
        <Badge variant={status === "completed" ? "success" : "outline"} className="text-[10px]">
          真实 workflow node
        </Badge>
      </div>

      <div className="mt-3 rounded-md border bg-background/50 p-2">
        <p className="font-medium">报告总览</p>
        <div className="mt-2 grid gap-2 md:grid-cols-2 lg:grid-cols-4">
          <NodeFact label="报告状态 report_status" value={status} />
          <NodeFact
            label="总分 overall_score"
            value={formatScore(reportSummary.overall_score ?? payload.overall_score)}
          />
          <NodeFact
            label="成长信号 growth_signal"
            value={
              stringValue(reportSummary.growth_signal) ||
              stringValue(payload.conclusion) ||
              stringValue(payload.verdict) ||
              "—"
            }
          />
          <NodeFact
            label="维度数"
            value={formatCountValue(reportSummary.dimension_count ?? payload.dimension_count)}
          />
          <NodeFact
            label="有效评分轮次"
            value={formatCountValue(
              reportSummary.evaluator_turn_count ?? payload.evaluator_turn_count,
            )}
          />
          <NodeFact
            label="fallback 次数"
            value={formatCountValue(reportSummary.fallback_count ?? payload.fallback_count)}
          />
        </div>
      </div>

      {summary && (
        <div className="mt-3 rounded-md border bg-background/50 p-2">
          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            报告摘要
          </p>
          <p className="mt-1 whitespace-pre-wrap break-words leading-relaxed">
            {summary}
          </p>
        </div>
      )}

      <div className="mt-3 rounded-md border bg-background/50 p-2">
        <p className="font-medium">评分可信度</p>
        <div className="mt-2 grid gap-2 md:grid-cols-2 lg:grid-cols-4">
          <NodeFact
            label="credibility_summary"
            value={formatDiagnosticScalar(scoringCredibility.credibility_summary) || "—"}
          />
          <NodeFact
            label="证据覆盖"
            value={formatKeyValueRecord(evidenceSummary)}
          />
          <NodeFact
            label="评分契约"
            value={formatKeyValueRecord(contractSummary)}
          />
          <NodeFact
            label="coverage warnings"
            value={formatCountValue(coverageWarnings.length)}
          />
        </div>
        <EvidenceList label="risk_flags" values={riskFlags} />
      </div>

      {dimensionResults.length > 0 && (
        <div className="mt-3 rounded-md border bg-background/50 p-2">
          <p className="font-medium">维度结果</p>
          <div className="mt-2 space-y-2">
            {dimensionResults.map((item, idx) => (
              <div
                key={`${stringValue(item.dimension) || "dimension"}-${idx}`}
                className="rounded-md bg-background/60 p-2"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium">
                    {stringValue(item.dimension) || `dimension_${idx + 1}`}
                  </p>
                  <Badge variant="outline" className="font-mono text-[10px]">
                    {formatDiagnosticScalar(item.score_status) || "score_status —"}
                  </Badge>
                </div>
                <div className="mt-2 grid gap-2 md:grid-cols-4">
                  <NodeFact label="分数" value={formatScore(item.score)} />
                  <NodeFact label="是否通过" value={formatBooleanValue(item.passed)} />
                  <NodeFact
                    label="覆盖状态"
                    value={formatDiagnosticScalar(item.coverage_status) || "—"}
                  />
                  <NodeFact
                    label="轮次数"
                    value={formatCountValue(item.turn_count)}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {dimensionEvidence.length > 0 && (
        <details className="mt-3 rounded-md border bg-background/50 p-2">
          <summary className="cursor-pointer select-none font-medium">
            展开维度证据摘要
          </summary>
          <div className="mt-2 space-y-2">
            {dimensionEvidence.map((item, idx) => (
              <div
                key={`${stringValue(item.dimension) || "evidence"}-${idx}`}
                className="rounded-md bg-background/60 p-2"
              >
                <p className="font-medium">
                  {stringValue(item.dimension) || `dimension_${idx + 1}`}
                </p>
                <div className="mt-2 grid gap-2 md:grid-cols-4">
                  <NodeFact label="turns" value={formatCountValue(item.turns)} />
                  <NodeFact
                    label="avg_score"
                    value={formatScore(item.avg_score)}
                  />
                  <NodeFact
                    label="strength_count"
                    value={formatCountValue(item.strength_count)}
                  />
                  <NodeFact
                    label="weakness_count"
                    value={formatCountValue(item.weakness_count)}
                  />
                </div>
                <div className="mt-2 grid gap-2 md:grid-cols-2">
                  <EvidenceList label="优势 strengths" values={stringList(item.strengths)} />
                  <EvidenceList label="不足 weaknesses" values={stringList(item.weaknesses)} />
                </div>
                <div className="mt-2 grid gap-2 md:grid-cols-2">
                  <NodeFact
                    label="验收检查"
                    value={formatKeyValueRecord(item.contract_checks)}
                  />
                  <NodeFact
                    label="evidence_count"
                    value={formatCountValue(item.evidence_count)}
                  />
                </div>
                <EvidenceList
                  label="followup_reasons"
                  values={stringList(item.followup_reasons)}
                />
              </div>
            ))}
          </div>
        </details>
      )}

      <div className="mt-3 rounded-md border bg-background/50 p-2">
        <p className="font-medium">收尾链路状态</p>
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          <NodeFact
            label="training_plan_queued"
            value={formatBooleanValue(
              closingChain.training_plan_queued ?? payload.training_plan_queued,
            )}
          />
          <NodeFact
            label="experience_extractor_queued"
            value={formatBooleanValue(
              closingChain.experience_extractor_queued ??
                payload.experience_extractor_queued,
            )}
          />
        </div>
      </div>

      {Object.keys(workflowArtifacts).length > 0 && (
        <details className="mt-3 rounded-md border bg-background/50 p-2">
          <summary className="cursor-pointer select-none font-medium">
            展开 workflow artifacts
          </summary>
          <div className="mt-2 grid gap-2 md:grid-cols-2">
            <NodeFact
              label="latest_ask_plan"
              value={formatDiagnosticScalar(latestAskPlan.template) || "—"}
            />
            <NodeFact
              label="latest_selected_action"
              value={
                stringValue(latestAction.id) ||
                stringValue(latestAction.label) ||
                "—"
              }
            />
            <NodeFact
              label="latest_contract"
              value={formatStringListValue(latestContract.signed_by)}
            />
            <NodeFact
              label="latest_verification"
              value={
                formatDiagnosticScalar(latestVerification.verdict) ||
                formatDiagnosticScalar(latestVerification.confidence) ||
                "—"
              }
            />
            <NodeFact
              label="latest_skill_focus"
              value={formatStringListValue(workflowArtifacts.latest_skill_focus)}
            />
            <NodeFact
              label="target_skill_coverage"
              value={formatKeyValueRecord(workflowArtifacts.target_skill_coverage)}
            />
          </div>
        </details>
      )}

      <EvidenceList label="missing_sections" values={missingSections} />
    </section>
  );
}

function TrainingPlanPanel({ node }: { node: TraceExplorerNode }) {
  if (node.node !== "training_plan") return null;

  const payload = recordFromUnknown(node.payload);
  const planSummary = recordFromUnknown(payload.plan_summary);
  const diagnosis = recordFromUnknown(payload.diagnosis);
  const priorityWeaknesses = recordArray(payload.priority_weaknesses);
  const practicePlan = recordArray(payload.practice_plan);
  const goals = recordFromUnknown(payload.goals_30_60_90);
  const source = stringValue(payload.source) || "—";
  const fallbackReason = stringValue(payload.fallback_reason);
  const reason = stringValue(payload.reason) || "—";

  return (
    <section className="mt-3 rounded-md border border-sky-500/25 bg-sky-500/[0.035] p-3 text-xs">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="flex items-center gap-2">
            <FileText className="h-3.5 w-3.5 text-sky-300" />
            <p className="font-medium text-sky-100">训练计划</p>
          </div>
          <p className="mt-1 max-w-3xl text-[11px] text-muted-foreground">
            本节点承接 final_report，把最终报告转成候选人可执行的训练计划；它不参与评分，只产出报告页展示的后续练习建议。
          </p>
        </div>
        <Badge variant={source === "llm" ? "success" : "outline"} className="text-[10px]">
          {source}
        </Badge>
      </div>

      <div className="mt-3 rounded-md border bg-background/50 p-2">
        <p className="font-medium">训练计划总览</p>
        <div className="mt-2 grid gap-2 md:grid-cols-2 lg:grid-cols-5">
          <NodeFact label="来源 source" value={source} />
          <NodeFact
            label="fallback_reason"
            value={fallbackReason || "—"}
          />
          <NodeFact
            label="优先改进项"
            value={formatCountValue(planSummary.priority_weakness_count)}
          />
          <NodeFact
            label="练习任务"
            value={formatCountValue(planSummary.practice_task_count)}
          />
          <NodeFact
            label="目标阶段"
            value={formatCountValue(planSummary.goals_count)}
          />
        </div>
      </div>

      <div className="mt-3 rounded-md border bg-background/50 p-2">
        <p className="font-medium">能力诊断</p>
        <div className="mt-2 grid gap-2 md:grid-cols-2">
          <NodeFact
            label="overall_readiness"
            value={formatDiagnosticScalar(diagnosis.overall_readiness) || "—"}
          />
          <NodeFact
            label="target_level_gap"
            value={formatDiagnosticScalar(diagnosis.target_level_gap) || "—"}
          />
        </div>
        <EvidenceList label="top_patterns" values={stringList(diagnosis.top_patterns)} />
      </div>

      <div className="mt-3 rounded-md border bg-background/50 p-2">
        <p className="font-medium">优先改进项</p>
        {priorityWeaknesses.length > 0 ? (
          <div className="mt-2 space-y-2">
            {priorityWeaknesses.map((item, idx) => (
              <div key={idx} className="rounded-md bg-background/60 p-2">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium">
                    {stringValue(item.focus) || `weakness_${idx + 1}`}
                  </p>
                  <Badge variant="outline" className="text-[10px]">
                    {stringValue(item.dimension) || "dimension —"}
                  </Badge>
                </div>
                {stringValue(item.why_it_matters) && (
                  <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                    {stringValue(item.why_it_matters)}
                  </p>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-2 rounded-md bg-background/60 p-2 text-[11px] text-muted-foreground">
            未记录优先改进项。
          </p>
        )}
      </div>

      <div className="mt-3 rounded-md border bg-background/50 p-2">
        <p className="font-medium">练习任务</p>
        {practicePlan.length > 0 ? (
          <div className="mt-2 space-y-2">
            {practicePlan.map((item, idx) => (
              <details
                key={idx}
                className="rounded-md border bg-background/45 p-2"
              >
                <summary className="cursor-pointer select-none font-medium">
                  {stringValue(item.task) || `practice_task_${idx + 1}`}
                  {typeof item.estimated_hours === "number" && (
                    <span className="ml-2 text-muted-foreground">
                      {formatScore(item.estimated_hours)}h
                    </span>
                  )}
                </summary>
                {stringValue(item.rationale) && (
                  <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                    {stringValue(item.rationale)}
                  </p>
                )}
                <div className="mt-2 grid gap-2 md:grid-cols-2">
                  <EvidenceList label="steps" values={stringList(item.steps)} />
                  <EvidenceList
                    label="success_criteria"
                    values={stringList(item.success_criteria)}
                  />
                </div>
              </details>
            ))}
          </div>
        ) : (
          <p className="mt-2 rounded-md bg-background/60 p-2 text-[11px] text-muted-foreground">
            未记录练习任务。
          </p>
        )}
      </div>

      <div className="mt-3 rounded-md border bg-background/50 p-2">
        <p className="font-medium">30 / 60 / 90 天目标</p>
        <div className="mt-2 grid gap-2 md:grid-cols-3">
          <EvidenceList label="30_days" values={stringList(goals["30_days"])} />
          <EvidenceList label="60_days" values={stringList(goals["60_days"])} />
          <EvidenceList label="90_days" values={stringList(goals["90_days"])} />
        </div>
      </div>

      <div className="mt-3 rounded-md border bg-background/50 p-2">
        <p className="font-medium">生成诊断</p>
        <div className="mt-2 grid gap-2 md:grid-cols-3">
          <NodeFact label="reason" value={reason} />
          <NodeFact
            label="diagnosis_recorded"
            value={formatBooleanValue(planSummary.diagnosis_recorded)}
          />
          <NodeFact
            label="goals_complete"
            value={formatBooleanValue(planSummary.goals_complete)}
          />
        </div>
      </div>
    </section>
  );
}

function RewardUpdatePanel({ node }: { node: TraceExplorerNode }) {
  if (node.node === "reward_update") {
    const payload = recordFromUnknown(node.payload);
    const rewardSummary = recordFromUnknown(payload.reward_summary);
    const banditUpdate = recordFromUnknown(payload.bandit_update);
    const strategyMemoryAttribution = recordFromUnknown(
      payload.strategy_memory_attribution,
    );
    const questionAttribution = recordFromUnknown(payload.question_attribution);
    const skillAttribution = recordFromUnknown(payload.skill_attribution);
    const persistence = recordFromUnknown(payload.persistence);
    const skippedQuestions = recordArray(questionAttribution.skipped);
    const failures = recordArray(persistence.failed);
    const immediateReward =
      rewardSummary.immediate_reward ??
      payload.immediate_reward ??
      node.immediate_reward;
    const rewardApplied =
      payload.immediate_reward_applied === true ||
      node.immediate_reward_applied === true;
    const banditContextKeys =
      stringList(banditUpdate.context_keys).length > 0
        ? stringList(banditUpdate.context_keys)
        : stringList(node.policy_context_keys);
    const strategyIds = stringList(strategyMemoryAttribution.strategy_ids);
    const strategyContextKeys = stringList(strategyMemoryAttribution.context_keys);
    const selectedVariantIds = stringList(questionAttribution.selected_variant_ids);
    const rewardedVariantIds = stringList(questionAttribution.rewarded_variant_ids);
    const skillIds = stringList(skillAttribution.skill_ids);
    const skillContextKey = stringValue(skillAttribution.skill_context_key);

    return (
      <section className="mt-3 rounded-md border border-emerald-500/25 bg-emerald-500/[0.035] p-3 text-xs">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-2">
              <Activity className="h-3.5 w-3.5 text-emerald-300" />
              <p className="font-medium text-emerald-100">奖励回填</p>
            </div>
            <p className="mt-1 max-w-3xl text-[11px] text-muted-foreground">
              本节点把 verification 后的 immediate reward 写回 Bandit 动作、StrategyMemory、题库和 Skill 使用记录；这里只展示归因与写入诊断，不改变排序逻辑。
            </p>
          </div>
          <Badge variant={rewardApplied ? "success" : "outline"} className="text-[10px]">
            {rewardApplied ? "reward applied" : "reward pending"}
          </Badge>
        </div>

        <div className="mt-3 rounded-md border bg-background/50 p-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-medium">奖励总览</p>
            <span className="text-[11px] text-muted-foreground">
              下面各归因层使用同一个即时奖励回填。
            </span>
          </div>
          <div className="mt-2 grid gap-2 md:grid-cols-2 lg:grid-cols-6">
            <NodeFact label="即时奖励 reward" value={formatScore(immediateReward)} />
            <NodeFact
              label="评分 score"
              value={formatScore(rewardSummary.score ?? node.score)}
            />
            <NodeFact
              label="是否通过"
              value={formatBooleanValue(rewardSummary.passed ?? node.passed)}
            />
            <NodeFact
              label="verification 改写"
              value={formatBooleanValue(rewardSummary.verifier_overruled)}
            />
            <NodeFact
              label="逻辑轮次"
              value={formatCountValue(rewardSummary.logical_turn_idx ?? node.turn_idx)}
            />
            <NodeFact
              label="正式题次"
              value={formatCountValue(rewardSummary.formal_turn_idx)}
            />
          </div>
        </div>

        <div className="mt-3 rounded-md border bg-background/50 p-2">
          <p className="font-medium">Bandit 动作更新</p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            动作层：给本轮 Director 选中的出题动作回填 reward；上下文键决定这次 reward 影响哪个策略桶。
          </p>
          <div className="mt-2 grid gap-2 md:grid-cols-3">
            <NodeFact
              label="动作"
              value={stringValue(banditUpdate.action_id) || node.action_id || "—"}
            />
            <NodeFact
              label="别名"
              value={
                stringValue(banditUpdate.alias) ||
                formatStringListValue(banditUpdate.action_ids)
              }
            />
            <NodeFact
              label="更新上下文数"
              value={formatCountValue(banditContextKeys.length)}
            />
          </div>
          <div className="mt-2 rounded-md bg-background/60 p-2">
            <RewardAttributionList
              label="上下文键"
              values={banditContextKeys}
            />
          </div>
        </div>

        <div className="mt-3 space-y-3">
          <section className="rounded-md border bg-background/50 p-2">
            <p className="font-medium">StrategyMemory 归因</p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              经验内容层：命中的策略记忆会使用上方即时奖励回填；没有命中不代表 reward_update 失败。
            </p>
            <div className="mt-2 grid gap-2 md:grid-cols-2">
              <NodeFact
                label="命中策略数"
                value={formatCountValue(strategyMemoryAttribution.ref_count)}
              />
              <NodeFact
                label="写入次数"
                value={formatCountValue(strategyMemoryAttribution.usage_count)}
              />
            </div>
            {strategyIds.length === 0 && (
              <p className="mt-2 rounded-md bg-background/60 p-2 text-[11px] text-muted-foreground">
                本轮没有命中可回填的策略记忆。
              </p>
            )}
            <div className="mt-2 grid gap-2">
              <RewardAttributionList
                label="策略 ID"
                values={strategyIds}
              />
              <RewardAttributionList
                label="上下文键"
                values={strategyContextKeys}
              />
            </div>
          </section>

          <section className="rounded-md border bg-background/50 p-2">
            <p className="font-medium">题库归因</p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              题库 Variant 层：只给本轮实际注入 Prompt 的 rank-1 结构化题库 Variant 使用上方即时奖励回填；其他候选只保留跳过原因。
            </p>
            <div className="mt-2 grid gap-2 md:grid-cols-2">
              <NodeFact
                label="候选题数"
                value={formatCountValue(questionAttribution.candidate_count)}
              />
              <NodeFact
                label="回填题数"
                value={formatCountValue(questionAttribution.rewarded_count)}
              />
            </div>
            <div className="mt-2 grid gap-2">
              <RewardAttributionList
                label="选中题库 Variant"
                values={selectedVariantIds}
              />
              <RewardAttributionList
                label="已回填 Variant"
                values={rewardedVariantIds}
              />
            </div>
            {skippedQuestions.length > 0 && (
              <details className="mt-2 rounded-md border bg-background/45 p-2">
                <summary className="cursor-pointer select-none font-medium text-muted-foreground">
                  展开未回填候选 skipped
                </summary>
                <ul className="mt-2 space-y-1">
                  {skippedQuestions.map((item, idx) => (
                    <li
                      key={idx}
                      className="overflow-x-auto whitespace-nowrap font-mono text-[11px] text-muted-foreground"
                    >
                      <span>
                        {stringValue(item.variant_id) ||
                          stringValue(item.seed_id) ||
                          `candidate_${idx + 1}`}
                      </span>
                      <span>
                        {" "}
                        · {stringValue(item.reason) || "skipped"}
                      </span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </section>

          <section className="rounded-md border bg-background/50 p-2">
            <p className="font-medium">Skill 归因</p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              Skill card 层：记录本轮注入 Skill card 的使用效果，使用上方即时奖励回填；不会直接改写本轮评分。
            </p>
            <div className="mt-2 grid gap-2 md:grid-cols-2">
              <NodeFact
                label="注入 Skill 数"
                value={formatCountValue(skillAttribution.ref_count)}
              />
              <NodeFact
                label="写入次数"
                value={formatCountValue(skillAttribution.usage_count)}
              />
            </div>
            {skillIds.length === 0 && (
              <p className="mt-2 rounded-md bg-background/60 p-2 text-[11px] text-muted-foreground">
                本轮没有可回填的 Skill card。
              </p>
            )}
            <div className="mt-2 grid gap-2">
              <RewardAttributionList
                label="Skill 上下文 key"
                values={skillContextKey ? [skillContextKey] : []}
              />
              <RewardAttributionList
                label="Skill ID"
                values={skillIds}
              />
            </div>
          </section>
        </div>

        <div className="mt-3 rounded-md border bg-background/50 p-2">
          <p className="font-medium">持久化诊断</p>
          <div className="mt-2 grid gap-2 md:grid-cols-3">
            <NodeFact
              label="DB 写入耗时"
              value={
                typeof persistence.db_write_ms === "number"
                  ? formatMs(persistence.db_write_ms)
                  : "—"
              }
            />
            <NodeFact label="失败数" value={formatCountValue(failures.length)} />
            <NodeFact
              label="写入状态"
              value={failures.length > 0 ? "best-effort warning" : "ok"}
            />
          </div>
          {failures.length > 0 && (
            <details className="mt-2 rounded-md border bg-background/45 p-2">
              <summary className="cursor-pointer select-none font-medium text-muted-foreground">
                展开失败摘要 failed
              </summary>
              <ul className="mt-2 space-y-1">
                {failures.map((failure, idx) => (
                  <li key={idx} className="break-words">
                    <span className="font-mono">
                      {stringValue(failure.target) || `failure_${idx + 1}`}
                    </span>
                    <span className="text-muted-foreground">
                      {" "}
                      · {stringValue(failure.error_type) || "error"}
                    </span>
                    {stringValue(failure.message) && (
                      <span className="ml-1">{stringValue(failure.message)}</span>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </div>
      </section>
    );
  }

  return null;
}

function RewardAttributionList({
  label,
  values,
}: {
  label: string;
  values: string[];
}) {
  if (values.length === 0) return null;

  return (
    <div className="min-w-0 rounded-md bg-background/60 p-2">
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <div className="mt-1 overflow-x-auto">
        <ul className="space-y-1">
          {values.map((value, idx) => (
            <li
              key={idx}
              className="whitespace-nowrap font-mono text-[11px] leading-5 text-muted-foreground"
            >
              {value}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function ExperienceExtractorPanel({ node }: { node: TraceExplorerNode }) {
  if (node.node === "experience_extractor") {
    const payload = recordFromUnknown(node.payload);
    const savedKeys = stringList(payload.saved_keys);
    const skippedKeys = stringList(payload.skipped_keys);
    const failedKeys = stringList(payload.failed_keys);

    return (
      <section className="mt-3 rounded-md border border-violet-500/25 bg-violet-500/[0.035] p-3 text-xs">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-2">
              <FileText className="h-3.5 w-3.5 text-violet-300" />
              <p className="font-medium text-violet-100">经验抽取</p>
            </div>
            <p className="mt-1 max-w-3xl text-[11px] text-muted-foreground">
              本节点在整场面试结束后沉淀 StrategySignal 候选，分为 QA pattern 与 bandit insight；它不参与本场评分，只为后续策略记忆治理提供素材。
            </p>
          </div>
          <Badge variant="outline" className="text-[10px]">
            收尾学习
          </Badge>
        </div>

        <div className="mt-3 grid gap-2 md:grid-cols-2 lg:grid-cols-5">
          <NodeFact label="候选总数" value={formatCountValue(payload.candidates)} />
          <NodeFact label="保存数" value={formatCountValue(payload.saved)} />
          <NodeFact
            label="已存在跳过"
            value={formatCountValue(payload.skipped_existing)}
          />
          <NodeFact label="失败数" value={formatCountValue(payload.failed)} />
          <NodeFact label="抽取状态" value={stringValue(payload.reason) || "completed"} />
        </div>

        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <section className="rounded-md border bg-background/50 p-2">
            <p className="font-medium">QA 模式</p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              从问答表现中抽取可复用的策略信号。
            </p>
            <div className="mt-2 grid gap-2 md:grid-cols-2">
              <NodeFact label="QA 候选数" value={formatCountValue(payload.qa_candidates)} />
              <NodeFact label="QA 保存数" value={formatCountValue(payload.qa_saved)} />
              <NodeFact
                label="QA 已存在跳过"
                value={formatCountValue(payload.qa_skipped_existing)}
              />
              <NodeFact label="QA 失败数" value={formatCountValue(payload.qa_failed)} />
              <NodeFact label="QA 来源" value={formatDiagnosticScalar(payload.qa_source) || "—"} />
            </div>
          </section>

          <section className="rounded-md border bg-background/50 p-2">
            <p className="font-medium">Bandit 洞察</p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              从动作策略的 reward 轨迹中抽取可解释洞察。
            </p>
            <div className="mt-2 grid gap-2 md:grid-cols-2">
              <NodeFact
                label="Bandit 候选数"
                value={formatCountValue(payload.bandit_candidates)}
              />
              <NodeFact
                label="Bandit 保存数"
                value={formatCountValue(payload.bandit_saved)}
              />
              <NodeFact
                label="Bandit 已存在跳过"
                value={formatCountValue(payload.bandit_skipped_existing)}
              />
              <NodeFact
                label="Bandit 失败数"
                value={formatCountValue(payload.bandit_failed)}
              />
              <NodeFact
                label="Bandit 来源"
                value={formatDiagnosticScalar(payload.bandit_source) || "—"}
              />
            </div>
          </section>
        </div>

        {(savedKeys.length > 0 || skippedKeys.length > 0 || failedKeys.length > 0) && (
          <div className="mt-3 rounded-md border bg-background/50 p-2">
            <p className="font-medium">经验 key</p>
            <p className="mt-1 text-[11px] text-muted-foreground">
              本场收尾阶段写入的 StrategySignal 标识；用于后续策略记忆治理，不直接进入本场评分。
            </p>
            <ExperienceSignalKeyLists
              savedKeys={savedKeys}
              skippedKeys={skippedKeys}
              failedKeys={failedKeys}
            />
          </div>
        )}
      </section>
    );
  }

  return null;
}

function ExperienceSignalKeyLists({
  savedKeys,
  skippedKeys,
  failedKeys,
}: {
  savedKeys: string[];
  skippedKeys: string[];
  failedKeys: string[];
}) {
  const allKeys = [...savedKeys, ...skippedKeys, ...failedKeys];
  const sessionPrefix = commonSessionKeyPrefix(allKeys);

  return (
    <div className="mt-3 space-y-3">
      {sessionPrefix && (
        <NodeFact
          label="来源 session"
          value={sessionPrefix.slice(0, -1)}
        />
      )}
      <div className="grid gap-2">
        <ExperienceSignalKeyList
          label="已保存经验 key"
          values={stripCommonPrefix(savedKeys, sessionPrefix)}
        />
        <ExperienceSignalKeyList
          label="已存在经验 key"
          values={stripCommonPrefix(skippedKeys, sessionPrefix)}
        />
        <ExperienceSignalKeyList
          label="保存失败 key"
          values={stripCommonPrefix(failedKeys, sessionPrefix)}
        />
      </div>
    </div>
  );
}

function ExperienceSignalKeyList({
  label,
  values,
}: {
  label: string;
  values: string[];
}) {
  if (values.length === 0) return null;

  return (
    <div className="min-w-0 rounded-md border bg-background/35 p-2">
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <div className="mt-1 max-w-full overflow-x-auto">
        <ul className="space-y-1">
          {values.map((value, idx) => (
            <li
              key={idx}
              className="whitespace-nowrap font-mono text-[11px] leading-5 text-muted-foreground"
            >
              {value}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function VerificationReviewPanel({ node }: { node: TraceExplorerNode }) {
  if (node.node !== "verification") return null;

  const payload = recordFromUnknown(node.payload);
  const evaluation = recordFromUnknown(node.evaluation);
  const verification = recordFromUnknown(payload.verification);
  const status = verificationReviewStatus(payload, evaluation);
  const verdict = stringValue(payload.verdict) || stringValue(verification.verdict);
  const confidence = payload.confidence ?? verification.confidence;
  const forcedRefine =
    payload.forced_refine ?? evaluation.verifier_forced_refine;
  const verifierAbstained =
    payload.verifier_abstained ?? evaluation.verifier_abstained;
  const updatedPassed = payload.updated_passed ?? evaluation.passed;
  const verificationChanges = recordArray(payload.verification_changes);
  const verificationEffect = verificationEffectValue(
    payload,
    evaluation,
    verificationChanges,
  );
  const softWarnings = stringList(evaluation.soft_warnings);
  const reasonsToDoubt = Array.from(
    new Set([
      ...stringList(payload.reasons_to_doubt),
      ...stringList(verification.reasons_to_doubt),
      ...stringList(evaluation.soft_warnings),
    ]),
  );
  const verifierRationale =
    stringValue(payload.rationale) ||
    stringValue(payload.verifier_rationale) ||
    stringValue(verification.rationale);

  return (
    <section className="mt-3 rounded-md border border-amber-500/25 bg-amber-500/[0.035] p-3 text-xs">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium text-amber-100">复核结果</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            Verifier 检查 evaluator 的评分是否站得住；下方“评估证据”是复核后的最终评分解释。
          </p>
        </div>
        <Badge
          variant={verificationReviewBadgeVariant(status)}
          className="text-[10px]"
        >
          {status}
        </Badge>
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-2 lg:grid-cols-4">
        <NodeFact label="是否触发" value={formatBooleanValue(payload.triggered)} />
        <NodeFact label="Verifier 结论" value={verificationVerdictLabel(verdict)} />
        <NodeFact label="置信度" value={formatConfidenceValue(confidence)} />
        <NodeFact
          label="Evaluator 原结论"
          value={formatVerifierPassState(payload.evaluator_passed)}
        />
        <NodeFact
          label="复核后结论"
          value={formatVerifierPassState(updatedPassed)}
        />
        <NodeFact
          label="是否改写"
          value={verificationRewriteLabel(payload.verdict_changed, verificationEffect)}
        />
        <NodeFact label="复核影响" value={verificationEffectLabel(verificationEffect)} />
        <NodeFact label="强制追问" value={formatBooleanValue(forcedRefine)} />
        <NodeFact
          label="低置信保留原判"
          value={formatBooleanValue(verifierAbstained)}
        />
      </div>

      {verificationEffect === "soft_warning_only" && (
        <details className="mt-3 rounded-md border border-amber-500/25 bg-background/50 p-2">
          <summary className="cursor-pointer select-none font-medium">
            展开软警告 <span className="font-mono">soft_warnings</span>
          </summary>
          <div className="mt-2">
            <EvidenceList
              label="软警告"
              values={softWarnings.length > 0 ? softWarnings : reasonsToDoubt}
            />
          </div>
        </details>
      )}

      {verificationEffect !== "soft_warning_only" && verificationChanges.length > 0 && (
        <VerificationChangeList changes={verificationChanges} />
      )}

      {(verifierRationale || reasonsToDoubt.length > 0) && (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          {verifierRationale && (
            <div className="rounded-md border bg-background/50 p-2">
              <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
                Verifier 理由
              </p>
              <p className="mt-1 whitespace-pre-wrap break-words leading-relaxed">
                {verifierRationale}
              </p>
            </div>
          )}
          <EvidenceList label="质疑原因" values={reasonsToDoubt} />
        </div>
      )}
    </section>
  );
}

function VerificationChangeList({
  changes,
}: {
  changes: Record<string, unknown>[];
}) {
  return (
    <details open className="mt-3 rounded-md border border-amber-500/25 bg-background/50 p-2">
      <summary className="cursor-pointer select-none font-medium">
        展开改写明细 <span className="font-mono">verification_changes</span>
      </summary>
      <ul className="mt-2 space-y-2">
        {changes.map((change, idx) => {
          const field = stringValue(change.field);
          const label = stringValue(change.label) || field || "改写项";
          const reason = stringValue(change.reason);
          return (
            <li key={`${field || "change"}-${idx}`} className="rounded border bg-background/40 p-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{label}</span>
                {field && (
                  <Badge variant="outline" className="font-mono text-[10px]">
                    {field}
                  </Badge>
                )}
                {reason && (
                  <Badge variant="warn" className="font-mono text-[10px]">
                    {reason}
                  </Badge>
                )}
              </div>
              <p className="mt-1 break-words font-mono text-[11px]">
                {formatVerificationChangeValue(field, change.before)} {"->"}{" "}
                {formatVerificationChangeValue(field, change.after)}
              </p>
            </li>
          );
        })}
      </ul>
    </details>
  );
}

function EvaluatorScoringBasis({ node }: { node: TraceExplorerNode }) {
  if (node.node !== "evaluator") return null;

  const payload = recordFromUnknown(node.payload);
  const contract = recordFromUnknown(payload.contract);
  const rubricPoints = stringList(payload.rubric_points);
  const mustCover = stringList(contract.must_cover);
  const acceptanceChecks = stringList(contract.acceptance_checks);
  const acceptanceCheckItems = recordArray(contract.acceptance_check_items);
  const reviewFocus = stringList(contract.review_focus);
  const signedBy = stringList(payload.signed_by);
  const contractSignedBy = stringList(contract.signed_by);
  const contractSource = stringValue(payload.contract_source);
  const hasBasis =
    Object.keys(contract).length > 0 ||
    rubricPoints.length > 0 ||
    Boolean(contractSource && contractSource !== "missing");
  const sourceLabel = evaluatorContractSourceLabel(contractSource);
  const signedByValue =
    contractSignedBy.length > 0
      ? contractSignedBy.join(", ")
      : signedBy.length > 0
        ? signedBy.join(", ")
        : "—";
  const barLevel =
    stringValue(payload.contract_bar_level) ||
    stringValue(contract.bar_level) ||
    "—";

  return (
    <section className="mt-3 rounded-md border border-cyan-500/25 bg-cyan-500/[0.035] p-3 text-xs">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium text-cyan-100">评分依据</p>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            evaluator 实际评分时使用的 contract；下方“评估证据”是评分后的结果解释。
          </p>
        </div>
        <Badge variant={hasBasis ? "outline" : "warn"} className="text-[10px]">
          {hasBasis ? sourceLabel : "未记录评分依据"}
        </Badge>
      </div>

      {!hasBasis ? (
        <p className="mt-3 rounded-md border bg-background/50 p-2 text-[11px] text-muted-foreground">
          未记录评分依据。
        </p>
      ) : (
        <>
          <div className="mt-3 grid gap-2 md:grid-cols-2 lg:grid-cols-3">
            <NodeFact label="来源 contract_source" value={sourceLabel} />
            <NodeFact label="签署方" value={signedByValue} />
            <NodeFact label="评分门槛" value={barLevel} />
            <NodeFact
              label="覆盖要求"
              value={formatCountValue(
                payload.contract_must_cover_count ?? mustCover.length,
              )}
            />
            <NodeFact
              label="验收检查"
              value={formatCountValue(
                payload.contract_acceptance_check_count ?? acceptanceChecks.length,
              )}
            />
          </div>

          <details className="mt-3 rounded-md border bg-background/50 p-2">
            <summary className="cursor-pointer select-none font-medium">
              展开评分依据明细
            </summary>
            <div className="mt-2 grid gap-3 xl:grid-cols-2">
              <EvidenceList label="覆盖要求" values={mustCover} />
              <AcceptanceCheckItemsList
                label="验收检查"
                values={acceptanceChecks}
                items={acceptanceCheckItems}
              />
              <EvidenceList
                label="最低门槛"
                values={
                  stringValue(contract.minimum_bar)
                    ? [stringValue(contract.minimum_bar)]
                    : []
                }
              />
              <EvidenceList label="复核重点" values={reviewFocus} />
              <EvidenceList label="旧版评分点" values={rubricPoints} />
            </div>
          </details>
        </>
      )}
    </section>
  );
}

function TraceTextExcerpt({
  label,
  value,
}: {
  label: string;
  value?: string | null;
}) {
  const text = stringValue(value);
  if (!text) return null;

  return (
    <section className="mt-3 rounded-md border bg-background/60 p-3 text-xs">
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 whitespace-pre-wrap break-words leading-relaxed">{text}</p>
    </section>
  );
}

function RewardQuestionContext({ value }: { value?: string | null }) {
  const text = stringValue(value);
  if (!text) return null;

  return (
    <details className="mt-3 rounded-md border bg-background/60 p-3 text-xs">
      <summary className="cursor-pointer select-none font-medium text-muted-foreground">
        展开本轮问题上下文
      </summary>
      <p className="mt-2 whitespace-pre-wrap break-words leading-relaxed">
        {text}
      </p>
    </details>
  );
}

function EvaluationEvidence({ node }: { node: TraceExplorerNode }) {
  if (
    node.node === "director_sample" ||
    node.node === "ask_question" ||
    node.node === "route_decision" ||
    node.node === "refine_followup" ||
    node.node === "final_report" ||
    node.node === "training_plan" ||
    isTurnFinalizeNode(node.node) ||
    node.node === "reward_update" ||
    node.node === "experience_extractor"
  ) {
    return null;
  }

  const evaluation = recordFromUnknown(node.evaluation);
  const payload = recordFromUnknown(node.payload);
  const acceptanceCheckResults = recordWithPayloadFallback(
    evaluation.acceptance_check_results,
    payload.acceptance_check_results,
  );
  const evaluationAcceptanceCheckResultItems = recordArray(
    evaluation.acceptance_check_result_items,
  );
  const payloadAcceptanceCheckResultItems = recordArray(
    payload.acceptance_check_result_items,
  );
  const acceptanceCheckResultItems =
    evaluationAcceptanceCheckResultItems.length > 0
      ? evaluationAcceptanceCheckResultItems
      : payloadAcceptanceCheckResultItems;
  const evaluationContractGateResult = recordFromUnknown(
    evaluation.contract_gate_result,
  );
  const payloadContractGateResult = recordFromUnknown(payload.contract_gate_result);
  const contractGateResult =
    Object.keys(evaluationContractGateResult).length > 0
      ? evaluationContractGateResult
      : payloadContractGateResult;
  const hasContractGateResult = Object.keys(contractGateResult).length > 0;
  const contractGateEnforcement = {
    contract_gate_enforced:
      evaluation.contract_gate_enforced ?? payload.contract_gate_enforced,
    contract_gate_enforcement_reason:
      evaluation.contract_gate_enforcement_reason ??
      payload.contract_gate_enforcement_reason,
    contract_gate_failed_count:
      evaluation.contract_gate_failed_count ?? payload.contract_gate_failed_count,
    contract_gate_failed_check_ids:
      evaluation.contract_gate_failed_check_ids ??
      payload.contract_gate_failed_check_ids,
  };
  const strengths = stringList(evaluation.strengths);
  const weaknesses = stringList(evaluation.weaknesses);
  const rationale =
    stringValue(evaluation.rationale) ||
    stringValue(evaluation.reasoning) ||
    stringValue(evaluation.feedback) ||
    (node.node === "verification" ? "" : stringValue(payload.rationale));

  if (
    strengths.length === 0 &&
    weaknesses.length === 0 &&
    Object.keys(acceptanceCheckResults).length === 0 &&
    acceptanceCheckResultItems.length === 0 &&
    !hasContractGateResult &&
    !rationale &&
    typeof node.immediate_reward_applied !== "boolean"
  ) {
    return null;
  }

  return (
    <section className="mt-3 rounded-md border bg-background/60 p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          评估证据
        </span>
        {typeof node.immediate_reward_applied === "boolean" && (
          <Badge
            variant={node.immediate_reward_applied ? "success" : "outline"}
            className="text-[10px]"
          >
            奖励状态 {node.immediate_reward_applied ? "applied" : "pending"}
          </Badge>
        )}
      </div>
      {rationale && <p className="mt-2 leading-relaxed">{rationale}</p>}
      {(strengths.length > 0 || weaknesses.length > 0) && (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <EvidenceList label="优势" values={strengths} />
          <EvidenceList label="不足" values={weaknesses} />
        </div>
      )}
      {hasContractGateResult && (
        <div className="mt-3">
          <ContractGateResultPanel
            result={contractGateResult}
            enforcement={contractGateEnforcement}
          />
        </div>
      )}
      {(acceptanceCheckResultItems.length > 0 ||
        Object.keys(acceptanceCheckResults).length > 0) && (
        <div className="mt-3">
          <AcceptanceCheckResultItemsList
            items={acceptanceCheckResultItems}
            fallbackResults={acceptanceCheckResults}
          />
        </div>
      )}
    </section>
  );
}

function StrategyDecisionSummary({ node }: { node: TraceExplorerNode }) {
  const payload = recordFromUnknown(node.payload);
  const selectedAction = recordFromUnknown(payload.selected_action);
  const diagnostics = recordFromUnknown(payload.diagnostics);
  const actionGuardrail = actionGuardrailFromPayload(payload);
  const policy = splitPolicyId(node.policy_id);
  const selectedPolicyKeys = Array.isArray(selectedAction.policy_context_keys)
    ? selectedAction.policy_context_keys
        .map((item) => String(item ?? "").trim())
        .filter(Boolean)
    : [];
  const candidateContexts =
    node.policy_context_keys && node.policy_context_keys.length > 0
      ? node.policy_context_keys
      : selectedPolicyKeys;
  const actionId =
    stringValue(selectedAction.id) || node.action_id || stringValue(diagnostics.chosen) || "—";
  const actionLabel = stringValue(selectedAction.label);
  const actionName = localizeActionName(actionId, actionLabel);
  const actionDescription = localizeActionDescription(
    actionId,
    actionLabel,
    stringValue(selectedAction.description),
  );
  const actionBackendLabel =
    actionLabel && actionId !== "—" ? `${actionId} / ${actionLabel}` : actionId;
  const planTemplate = stringValue(selectedAction.plan_template);
  const planTemplateHint = stringValue(selectedAction.plan_template_hint);
  const dimensionEffect = stringValue(selectedAction.dimension_effect);
  const diagnosticMode = stringValue(diagnostics.mode);
  const decisionContext =
    node.context_key ||
    stringValue(selectedAction.policy_context_key) ||
    stringValue(diagnostics.context_key) ||
    policy.context ||
    "—";
  const targetDimension =
    node.dimension ||
    stringValue(diagnostics.target_dimension) ||
    stringValue(selectedAction.target_dimension) ||
    "—";
  const rewardStatus =
    node.immediate_reward_applied === true
      ? "已写入 immediate reward"
      : "待后续 reward_update 回填";

  return (
    <section className="mt-3 rounded-md border border-emerald-500/25 bg-emerald-500/[0.04] p-3 text-xs">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <GitBranch className="h-3.5 w-3.5 text-emerald-300" />
            <p className="font-medium text-emerald-200">出题决策摘要</p>
            <Badge variant="outline" className="text-[10px]">
              真实 workflow node
            </Badge>
          </div>
          <p className="mt-1 max-w-3xl text-muted-foreground">
            本节点承接 route_decision=next_question，只解释进入下一题后 Director 选了什么动作与上下文；
            路由原因请看 route_decision，评分细节请看 evaluator / verification。
          </p>
        </div>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-3">
        <NodeFact label="节点类型" value={node.node} />
        <NodeFact label="目标维度" value={targetDimension} />
        <NodeFact
          label="出题动作"
          value={`${actionName} · ${actionBackendLabel}`}
        />
        <NodeFact label="计划模板" value={localizePlanTemplateName(planTemplate)} />
        <NodeFact
          label="计划模板来源"
          value={planTemplateSourceLabel(selectedAction)}
        />
        <NodeFact
          label="维度变化"
          value={localizeDimensionEffect(dimensionEffect)}
        />
        <NodeFact
          label="出题动作决策原因"
          value={diagnosticModeLabel(diagnosticMode)}
        />
        <NodeFact label="决策上下文" value={decisionContext} />
        <NodeFact label="策略算法" value={policy.algorithm} />
        <NodeFact label="策略空间" value={policy.space} />
        {planTemplateHint && (
          <NodeFact label="计划模板 hint" value={planTemplateHint} />
        )}
        <NodeFact
          label="奖励回填上下文"
          value={candidateContexts.length > 0 ? candidateContexts.join(", ") : "—"}
        />
        <NodeFact label="奖励状态" value={rewardStatus} />
      </div>
      <ActionGuardrailSummary guardrail={actionGuardrail} />
      {actionDescription && (
        <div className="mt-3 rounded-md border bg-background/50 p-2">
          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            动作说明
          </p>
          <p className="mt-1 break-words text-[11px] leading-relaxed">
            {actionDescription}
          </p>
        </div>
      )}
    </section>
  );
}

function ActionGuardrailSummary({
  guardrail,
}: {
  guardrail: Record<string, unknown>;
}) {
  const originalActions = stringList(guardrail.original_allowed_actions);
  const finalActions = stringList(guardrail.final_allowed_actions);
  const disabledActions = recordArray(guardrail.disabled_actions);
  const disabledActionIds = disabledActions
    .map((item) => stringValue(item.action_id))
    .filter(Boolean);
  const reasonCodes = stringList(guardrail.reason_codes);
  const hasData =
    originalActions.length > 0 ||
    finalActions.length > 0 ||
    disabledActions.length > 0 ||
    reasonCodes.length > 0 ||
    Boolean(stringValue(guardrail.mode));

  if (!hasData) return null;

  const enabled = guardrail.enabled === true;
  const reasonLabels = reasonCodes.map(actionGuardrailReasonLabel);

  return (
    <div className="mt-3 rounded-md border bg-background/50 p-2">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-medium">动作候选过滤</p>
          <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
            在 Bandit 抽样前应用质量下限；只收窄候选动作，不直接替 Director 强选动作。
          </p>
        </div>
        <Badge variant={enabled ? "warn" : "outline"} className="w-fit text-[10px]">
          {enabled ? "已过滤" : "未触发"}
        </Badge>
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-3">
        <ActionGuardrailActionList label="原始候选" actions={originalActions} />
        <ActionGuardrailActionList label="最终候选" actions={finalActions} />
        <ActionGuardrailActionList label="禁用动作" actions={disabledActionIds} />
      </div>
      {reasonLabels.length > 0 && (
        <div className="mt-3">
          <EvidenceList label="禁用原因" values={reasonLabels} />
        </div>
      )}
      {disabledActions.length > 0 && (
        <div className="mt-3 space-y-2">
          {disabledActions.map((item, index) => {
            const actionId = stringValue(item.action_id) || `action_${index + 1}`;
            const reasons = stringList(item.reason_codes).map(
              actionGuardrailReasonLabel,
            );
            return (
              <div
                key={`${actionId}-${index}`}
                className="rounded-md border bg-background/40 p-2"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline" className="font-mono text-[10px]">
                    {actionId}
                  </Badge>
                  <span className="text-[11px] text-muted-foreground">禁用动作</span>
                </div>
                {reasons.length > 0 && (
                  <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                    {reasons.join("；")}
                  </p>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ActionGuardrailActionList({
  label,
  actions,
}: {
  label: string;
  actions: string[];
}) {
  return (
    <div className="rounded-md border bg-background/40 p-2">
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {actions.length > 0 ? (
          actions.map((action) => (
            <Badge key={action} variant="outline" className="font-mono text-[10px]">
              {action}
            </Badge>
          ))
        ) : (
          <span className="text-[11px] text-muted-foreground">无</span>
        )}
      </div>
    </div>
  );
}

function AskQuestionEvidencePanel({ node }: { node: TraceExplorerNode }) {
  return <AskQuestionEvidencePanelV2 node={node} />;
}

function AskQuestionEvidencePanelV2({ node }: { node: TraceExplorerNode }) {
  const payload = recordFromUnknown(node.payload);
  const askPlan = recordFromUnknown(payload.ask_plan);
  const planSteps = recordArray(askPlan.steps);
  const resolutionInputs = recordFromUnknown(askPlan.resolution_inputs);
  const promptBudgetDiagnostics = recordFromUnknown(payload.prompt_budget_diagnostics);
  const promptSlots = recordArray(payload.prompt_slots);
  const promptSlotByLabel = (label: string) =>
    promptSlots.find((slot) => stringValue(slot.prompt_label) === label) ?? null;
  const orderedPromptSlots = PROMPT_SLOT_DEFINITIONS.map((definition) => ({
    definition,
    slot: promptSlotByLabel(definition.promptLabel),
  }));
  const artifacts = recordFromUnknown(payload.selection_artifacts);
  const rag = recordFromUnknown(artifacts.rag);
  const strategies = recordArray(artifacts.strategies);
  const questionItems = recordArray(artifacts.question_items);
  const anchorScheduler = recordFromUnknown(artifacts.anchor_scheduler);
  const candidateAnchor = recordFromUnknown(artifacts.candidate_anchor);
  const candidateAnchorRag = recordFromUnknown(artifacts.candidate_anchor_rag);
  const anchorHits = recordArray(candidateAnchorRag.hits);
  const resumeAnchor = recordFromUnknown(
    artifacts.resume_anchor ?? payload.resume_anchor,
  );
  const anchorLabel = resumeAnchorLabel(resumeAnchor, candidateAnchorRag);
  const hitProjectLabel = candidateAnchorHitProjectLabel(anchorHits);
  const questionReranker = recordFromUnknown(artifacts.question_reranker);
  const questionFitProfile = recordFromUnknown(artifacts.question_fit_profile);
  const avoidPatterns = recordFromUnknown(artifacts.avoid_patterns);
  const failureCategories = stringList(artifacts.failure_categories);
  const docRefs = recordArray(rag.doc_refs);
  const skills = recordFromUnknown(artifacts.skills);
  const skillRefs = recordArray(skills.refs);
  const targetSkills = stringList(payload.target_skills);
  const injectedQuestion = questionItems.some((item) => item.injected === true);
  const questionSelectorMode =
    stringValue(artifacts.question_selector_mode) ||
    stringValue(questionReranker.question_selector_mode) ||
    inferQuestionSelectorMode(questionItems, rag);
  const probeIntent =
    stringValue(payload.probe_intent) ||
    stringValue(questionFitProfile.turn_intent) ||
    stringValue(questionItems[0]?.intent);
  const signedBy = stringList(payload.signed_by);
  const contract = recordFromUnknown(payload.contract);
  const contractDiagnostics = recordFromUnknown(payload.contract_diagnostics);
  const contractWarnings = stringList(contractDiagnostics.warnings);
  const contractMustCover = stringList(contract.must_cover);
  const contractAcceptanceChecks = stringList(contract.acceptance_checks);
  const contractAcceptanceCheckItems = recordArray(contract.acceptance_check_items);
  const contractReviewFocus = stringList(contract.review_focus);
  const contractBarLevel =
    stringValue(contractDiagnostics.bar_level) ||
    stringValue(contract.bar_level) ||
    stringValue(payload.contract_bar_level);
  const contractExpectedBarLevel = stringValue(contractDiagnostics.expected_bar_level);
  const contractSignedBy = stringList(contract.signed_by);
  const contractHasDiagnostics = Object.keys(contractDiagnostics).length > 0;
  const contractHasSummary =
    signedBy.length > 0 ||
    Boolean(stringValue(payload.contract_bar_level)) ||
    typeof payload.contract_must_cover_count === "number" ||
    typeof payload.contract_acceptance_check_count === "number";
  const contractHasContent =
    Object.keys(contract).length > 0 ||
    contractHasDiagnostics ||
    contractHasSummary;
  const contractStatus = !contractHasContent
    ? "未命中"
    : contractWarnings.length > 0
      ? "轻量 warning"
      : "已注入";
  const contractDiagnosticState = !contractHasDiagnostics
    ? "未记录诊断"
    : contractWarnings.length > 0
      ? `${contractWarnings.length} warnings`
      : "通过";
  const planTemplate = stringValue(askPlan.template) || stringValue(payload.plan_template);
  const candidateAnchorSlot = promptSlotByLabel("CANDIDATE_ANCHOR");
  const ragStatus = statusLabelForArtifact({
    enabled: stringValue(rag.mode) !== "none",
    empty: rag.empty === true || docRefs.length === 0,
    shadow: injectedQuestion && docRefs.length > 0,
    error: rag.error || rag.error_type,
  });
  const planStatus = statusLabelForArtifact({
    enabled: Boolean(planTemplate || planSteps.length),
    empty: planSteps.length === 0,
    injected: planSteps.length > 0,
    shadow: Boolean(planTemplate) && planSteps.length === 0,
  });
  const questionStatus = statusLabelForArtifact({
    enabled: questionItems.length > 0,
    empty: questionItems.length === 0,
    injected: injectedQuestion,
    shadow: questionItems.length > 0 && !injectedQuestion,
  });
  const strategyStatus = statusLabelForArtifact({
    enabled: true,
    empty: strategies.length === 0,
  });
  const skillStatus = statusLabelForArtifact({
    enabled: skills.enabled === true || skillRefs.length > 0,
    empty: skillRefs.length === 0,
    injected: skills.enabled === true && skillRefs.length > 0,
    shadow: skills.enabled !== true && skillRefs.length > 0,
  });
  const anchorStatus = statusLabelForArtifact({
    enabled: stringValue(candidateAnchorRag.status) !== "off",
    empty:
      anchorHits.length === 0 &&
      Object.keys(resumeAnchor).length === 0,
    shadow: stringValue(candidateAnchorRag.status) === "shadow",
    injected: stringValue(candidateAnchorRag.status) === "primary",
    error: candidateAnchorRag.error || candidateAnchorRag.error_type,
  });
  const candidateAnchorStatus = statusLabelForArtifact({
    enabled:
      candidateAnchorSlot !== null ||
      Object.keys(candidateAnchor).length > 0 ||
      anchorLabel !== "—",
    empty:
      candidateAnchorSlot === null &&
      Object.keys(candidateAnchor).length === 0 &&
      anchorLabel === "—",
    injected: candidateAnchorSlot?.injected === true,
    shadow: candidateAnchorSlot !== null && candidateAnchorSlot.injected !== true,
  });
  const promptStatus = statusLabelForArtifact({
    enabled: promptSlots.length > 0,
    empty: promptSlots.length === 0,
    injected: promptSlots.some((slot) => slot.injected === true),
  });
  const avoidStatus = statusLabelForArtifact({
    enabled: avoidPatterns.enabled === true,
    empty: avoidPatterns.rendered !== true,
  });
  const failureStatus = statusLabelForArtifact({
    enabled: failureCategories.length > 0,
    empty: failureCategories.length === 0,
  });

  return (
    <section className="mt-3 rounded-md border border-sky-500/25 bg-sky-500/[0.035] p-3 text-xs">
      <div className="flex flex-col gap-2">
        <div>
          <div className="flex items-center gap-2">
            <Search className="h-3.5 w-3.5 text-sky-300" />
            <p className="font-medium text-sky-200">本轮出题总览</p>
          </div>
          <p className="mt-1 max-w-3xl text-muted-foreground">
            这条记录说明 ask_question 如何计划、检索、装配上下文并生成问题。
          </p>
          <p className="mt-1 max-w-3xl text-[11px] text-muted-foreground">
            本节点记录出题前证据装配；回答和评分请查看同一 Turn 的 evaluator / verification 节点。
          </p>
        </div>
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-3">
        <NodeFact label="出题方案" value={planTemplate || "—"} />
        <NodeFact label="计划来源" value={stringValue(askPlan.source) || "legacy"} />
        <NodeFact label="目标维度" value={node.dimension || stringValue(payload.dimension) || "—"} />
        <NodeFact label="问题意图" value={probeIntent || "—"} />
        <NodeFact label="题库模式" value={questionSelectorMode || "—"} />
        <NodeFact
          label="评分契约签署方"
          value={signedBy.length > 0 ? signedBy.join(", ") : "—"}
        />
        <NodeFact label="评分门槛" value={contractBarLevel || "—"} />
        <NodeFact
          label="覆盖要求"
          value={formatCountValue(payload.contract_must_cover_count)}
        />
        <NodeFact
          label="验收检查"
          value={formatCountValue(payload.contract_acceptance_check_count)}
        />
        <NodeFact
          label="证据覆盖"
          value={`RAG ${docRefs.length} · 题库 ${questionItems.length} · 策略 ${strategies.length} · Skills ${skillRefs.length} · Prompt ${promptSlots.length}`}
        />
      </div>

      <div
        className="mt-3 space-y-3"
        data-trace-section="ask-question-primary-evidence"
      >
        <EvidenceSourceSection
          heading="本轮执行计划"
          status={planStatus}
          summary={`${planTemplate || "plan_template 未记录"} · ${planSteps.length} steps`}
          emptyText="仅记录模板，未记录 steps。"
        >
          <div className="grid gap-2 md:grid-cols-2">
            <NodeFact label="Plan ID" value={stringValue(askPlan.plan_id) || "—"} />
            <NodeFact label="复杂度" value={stringValue(askPlan.complexity) || "—"} />
            <NodeFact label="选中动作" value={stringValue(resolutionInputs.selected_action_label) || "—"} />
            <NodeFact label="待办模板" value={stringValue(resolutionInputs.pending_plan_template) || "—"} />
          </div>
          {planSteps.length === 0 ? (
            <p className="mt-2 text-[11px] text-muted-foreground">
              仅记录模板，未记录 steps。
            </p>
          ) : (
            <div className="mt-2 max-h-[30rem] overflow-auto divide-y divide-border/70">
              {renderTopItems(planSteps, (step, idx) => {
                const producedKeys = stringList(step.produced_keys);
                return (
                  <EvidenceRow key={`${String(step.step_id ?? "")}-${idx}`}>
                    <div className="min-w-0 space-y-1">
                      <p className="break-words font-medium">
                        {localizeAskPlanStepTitle(step, idx)}
                      </p>
                      <p className="break-words font-mono text-[10px] text-muted-foreground">
                        后端步骤 {stringValue(step.step_id) || `step_${idx + 1}`} · {stringValue(step.kind) || "kind —"}
                      </p>
                      {localizeAskPlanSuccessCriteria(step) && (
                        <p className="text-[11px] text-muted-foreground">
                          成功标准：{localizeAskPlanSuccessCriteria(step)}
                        </p>
                      )}
                      {stringList(step.dependencies).length > 0 && (
                        <p className="break-words font-mono text-[10px] text-muted-foreground">
                          前置依赖：先完成步骤 {stringList(step.dependencies).join("、")}
                        </p>
                      )}
                      {producedKeys.length > 0 && (
                        <p className="break-words font-mono text-[10px] text-muted-foreground">
                          产出字段：{producedKeys.join("、")}
                        </p>
                      )}
                    </div>
                    <Badge variant="outline" className="font-mono text-[10px]">
                      产出字段 {producedKeys.length}
                    </Badge>
                  </EvidenceRow>
                );
              })}
            </div>
          )}
        </EvidenceSourceSection>

        <EvidenceSourceSection
          heading="评分契约"
          status={contractStatus}
          summary={`${contractDiagnostics.source ? stringValue(contractDiagnostics.source) : "legacy"} · ${contractDiagnosticState}`}
          emptyText="旧 trace 没有记录评分契约。"
        >
          <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-3">
            <NodeFact
              label="评分契约签署方"
              value={
                contractSignedBy.length > 0
                  ? contractSignedBy.join(", ")
                  : signedBy.length > 0
                    ? signedBy.join(", ")
                    : "—"
              }
            />
            <NodeFact label="评分门槛" value={contractBarLevel || "—"} />
            <NodeFact
              label="期望门槛"
              value={contractExpectedBarLevel || "—"}
            />
            <NodeFact
              label="覆盖要求"
              value={formatCountValue(
                contractDiagnostics.must_cover_count ??
                  payload.contract_must_cover_count ??
                  contractMustCover.length,
              )}
            />
            <NodeFact
              label="验收检查"
              value={formatCountValue(
                contractDiagnostics.acceptance_check_count ??
                  payload.contract_acceptance_check_count ??
                  contractAcceptanceChecks.length,
              )}
            />
            <NodeFact label="诊断状态" value={contractDiagnosticState} />
            <NodeFact
              label="来源"
              value={stringValue(contractDiagnostics.source) || "—"}
            />
            <NodeFact
              label="签署状态"
              value={stringValue(contractDiagnostics.signed_status) || "—"}
            />
            <NodeFact
              label="门槛匹配"
              value={
                contractDiagnostics.bar_level_match === true
                  ? "一致"
                  : contractDiagnostics.bar_level_match === false
                    ? "不一致"
                    : "—"
              }
            />
          </div>

          <div className="mt-3 rounded-md border bg-background/50 p-2">
            <p className="font-medium">诊断提示</p>
            {!contractHasDiagnostics ? (
              <p className="mt-1 text-[11px] text-muted-foreground">
                未记录诊断。
              </p>
            ) : contractWarnings.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {contractWarnings.map((warning) => (
                  <Badge key={warning} variant="warn" className="text-[10px]">
                    {contractDiagnosticWarningLabel(warning)}
                  </Badge>
                ))}
              </div>
            ) : (
              <p className="mt-1 text-[11px] text-muted-foreground">
                未发现关键 warning。
              </p>
            )}
          </div>

          <details className="mt-3 rounded-md border bg-background/50 p-2">
            <summary className="cursor-pointer select-none font-medium">
              展开评分契约明细
            </summary>
            <div className="mt-2 grid gap-3 xl:grid-cols-2">
              <EvidenceList label="must_cover" values={contractMustCover} />
              <AcceptanceCheckItemsList
                label="acceptance_checks"
                values={contractAcceptanceChecks}
                items={contractAcceptanceCheckItems}
              />
              <EvidenceList
                label="minimum_bar"
                values={
                  stringValue(contract.minimum_bar)
                    ? [stringValue(contract.minimum_bar)]
                    : []
                }
              />
              <EvidenceList label="review_focus" values={contractReviewFocus} />
              <EvidenceList
                label="uncovered_must_cover_items"
                values={stringList(contractDiagnostics.uncovered_must_cover_items)}
              />
              <EvidenceList
                label="generic_items"
                values={stringList(contractDiagnostics.generic_items)}
              />
            </div>
          </details>
        </EvidenceSourceSection>

        <EvidenceSourceSection
          heading="出题策略记忆"
          status={strategyStatus}
          summary={`${strategies.length} strategy refs`}
          emptyText="本轮没有命中策略记忆。"
        >
          <div className="max-h-64 overflow-auto divide-y divide-border/70">
            {renderTopItems(strategies, (strategy, idx) => (
              <EvidenceRow key={`${String(strategy.id ?? strategy.name ?? "")}-${idx}`}>
                <div className="min-w-0">
                  <p className="break-words font-medium">
                    {localizeStrategyMemoryName(strategy)}
                  </p>
                  {strategyMemoryDescription(strategy) && (
                    <p className="mt-1 break-words text-[11px] leading-relaxed text-muted-foreground">
                      {strategyMemoryDescription(strategy)}
                    </p>
                  )}
                  <p className="mt-0.5 break-words font-mono text-[10px] text-muted-foreground">
                    {strategyMemoryTraceKey(strategy) || "strategy id —"}
                  </p>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    支撑样本 {formatCountValue(strategy.support_count)} · 置信度 {formatScore(strategy.confidence)}
                  </p>
                  <StrategyRankingReasonDetails strategy={strategy} />
                </div>
                <Badge variant="outline" className="font-mono text-[10px]">
                  {strategy.ranking_reason ? "ranking_reason" : "rank —"}
                </Badge>
              </EvidenceRow>
            ))}
          </div>
        </EvidenceSourceSection>

        <EvidenceSourceSection
          heading="能力焦点 / SKILLS 命中"
          status={skillStatus}
          summary={`命中 ${skillRefs.length} skill refs · 目标能力 ${targetSkills.length}`}
          emptyText="本轮没有命中可注入的 SKILLS 内容。"
        >
          <div className="grid gap-2 md:grid-cols-2">
            <NodeFact label="目标能力" value={targetSkills.length > 0 ? targetSkills.join(", ") : "—"} />
            <NodeFact label="技能来源" value={stringValue(skills.source) || "—"} />
          </div>
          {skillRefs.length > 0 && (
            <ul className="mt-2 flex flex-col gap-2">
              {skillRefs.slice(0, 3).map((ref, idx) => (
                <SkillSelectionRef key={`${String(ref.id ?? "")}-${idx}`} ref_={ref} />
              ))}
              {skillRefs.length > 3 && (
                <li className="list-none">
                  <details className="rounded-md border bg-card/40 p-2">
                    <summary className="cursor-pointer select-none font-medium">
                      展开全部 {skillRefs.length} 条
                    </summary>
                    <ul className="mt-2 flex flex-col gap-2">
                      {skillRefs.slice(3).map((ref, idx) => (
                        <SkillSelectionRef key={`${String(ref.id ?? "")}-${idx + 3}`} ref_={ref} />
                      ))}
                    </ul>
                  </details>
                </li>
              )}
            </ul>
          )}
        </EvidenceSourceSection>

        <EvidenceSourceSection
          heading="结构化题库"
          status={questionStatus}
          summary={`${questionSelectorMode || "unknown"} · ${questionItems.length} candidates`}
          emptyText="本轮没有结构化题库候选。"
        >
          <div className="max-h-64 overflow-auto divide-y divide-border/70">
            {renderTopItems(questionItems, (item, idx) => (
              <StructuredQuestionCandidate
                key={`${String(item.variant_id ?? "")}-${idx}`}
                item={item}
              />
            ))}
          </div>
        </EvidenceSourceSection>

        <EvidenceSourceSection
          heading="候选人适配提示"
          status={candidateAnchorStatus}
          summary={`${anchorLabel !== "—" ? anchorLabel : "项目锚点未记录"} · CANDIDATE_ANCHOR`}
          emptyText="本轮没有记录候选人适配提示。"
        >
          <p className="mb-2 text-[11px] leading-relaxed text-muted-foreground">
            来源：<span className="font-mono">question_fit_profile</span> + rank 1
            题库候选；作用：生成 <span className="font-mono">CANDIDATE_ANCHOR</span>，
            帮助 Generator 将结构化问法贴合候选人的项目、技能和 JD 要求。
          </p>
          <div className="grid gap-2 md:grid-cols-2">
            <NodeFact
              label="适配层"
              value={stringValue(candidateAnchor.prompt_role) || "candidate_adaptation"}
            />
            <NodeFact
              label="目标维度"
              value={
                stringValue(candidateAnchor.target_dimension) ||
                stringValue(questionFitProfile.dimension) ||
                node.dimension ||
                stringValue(payload.dimension) ||
                "—"
              }
            />
            <NodeFact
              label="题库绑定"
              value={stringValue(candidateAnchor.seed_binding) || "rank 1"}
            />
            <NodeFact label="项目锚点" value={anchorLabel} />
            <NodeFact
              label="项目来源"
              value={stringValue(candidateAnchor.project_anchor_source) || "—"}
            />
            <NodeFact label="命中项目" value={hitProjectLabel} />
            <NodeFact
              label="锚点选择原因"
              value={
                stringValue(candidateAnchor.reason) ||
                localizeAnchorExpansionReason(anchorScheduler.expansion_reason)
              }
            />
            <NodeFact label="Prompt 字符" value={formatCountValue(candidateAnchorSlot?.chars)} />
          </div>
          {stringValue(candidateAnchorSlot?.text) && (
            <details className="mt-2 rounded-md border bg-background/45 p-2 text-[11px]">
              <summary className="cursor-pointer select-none font-medium text-muted-foreground">
                展开注入内容 <span className="font-mono">CANDIDATE_ANCHOR</span>
              </summary>
              <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md bg-background/60 p-2 font-mono text-[11px]">
                {stringValue(candidateAnchorSlot?.text)}
              </pre>
            </details>
          )}
        </EvidenceSourceSection>

        <EvidenceSourceSection
          heading="候选人锚点 RAG"
          status={anchorStatus}
          summary={`status ${stringValue(candidateAnchorRag.status) || "unknown"} · hits ${anchorHits.length} · prompt ${formatBooleanValue(candidateAnchorRag.prompt_injected)}`}
          emptyText="本轮候选人锚点检索关闭或没有命中。"
        >
          <p className="mb-2 text-[11px] leading-relaxed text-muted-foreground">
            观测本轮如何用项目锚点召回候选人简历 / 自我介绍片段；命中不等于最终注入，
            是否进入 Generator prompt 以 <span className="font-mono">prompt_injected</span> 为准。
          </p>
          <div className="grid gap-2 md:grid-cols-3 xl:grid-cols-4">
            <NodeFact label="检索状态" value={stringValue(candidateAnchorRag.status) || "unknown"} />
            <NodeFact
              label="耗时"
              value={
                typeof candidateAnchorRag.latency_ms === "number"
                  ? formatMs(candidateAnchorRag.latency_ms)
                  : "—"
              }
            />
            <NodeFact label="命中片段" value={formatCountValue(anchorHits.length)} />
            <NodeFact
              label="简历命中"
              value={formatCountValue(candidateAnchorRag.resume_hit_count)}
            />
            <NodeFact
              label="自我介绍命中"
              value={formatCountValue(candidateAnchorRag.self_intro_hit_count)}
            />
            <NodeFact
              label="Prompt 注入"
              value={formatBooleanValue(candidateAnchorRag.prompt_injected)}
            />
            <NodeFact
              label="注入来源"
              value={formatStringListValue(candidateAnchorRag.prompt_block_sources)}
            />
            <NodeFact
              label="注入字符"
              value={formatCountValue(candidateAnchorRag.prompt_block_chars)}
            />
            <NodeFact
              label="兜底原因 fallback_reason"
              value={formatCandidateAnchorFallbackReason(candidateAnchorRag.fallback_reason)}
            />
            <NodeFact
              label="Boost 兜底 boost_fallback_reason"
              value={formatCandidateAnchorFallbackReason(candidateAnchorRag.boost_fallback_reason)}
            />
          </div>
          <div className="mt-2 grid gap-2 md:grid-cols-2">
            <NodeFact label="项目锚点" value={anchorLabel} />
            <NodeFact label="尝试次数" value={formatCountValue(anchorScheduler.anchor_attempt)} />
            <NodeFact
              label="锚点选择原因"
              value={localizeAnchorExpansionReason(anchorScheduler.expansion_reason)}
            />
            <NodeFact label="命中项目" value={hitProjectLabel} />
          </div>
          {anchorHits.length > 0 && (
            <div className="mt-3 max-h-[34rem] overflow-auto divide-y divide-border/70">
              {renderTopItems(anchorHits, (hit, idx) => (
                <EvidenceRow key={`${String(hit.id ?? hit.chunk_index ?? "")}-${idx}`}>
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <Badge variant="outline" className="font-mono text-[10px]">
                        rank {idx + 1}
                      </Badge>
                      <Badge variant="outline" className="font-mono text-[10px]">
                        {stringValue(hit.source_type) || "source_type —"}
                      </Badge>
                      <Badge variant="outline" className="font-mono text-[10px]">
                        chunk {formatCountValue(hit.chunk_index)}
                      </Badge>
                    </div>
                    <div>
                      <p className="break-words font-medium">
                        {stringValue(hit.heading) ||
                          stringValue(hit.project_name) ||
                          `chunk ${formatCountValue(hit.chunk_index)}`}
                      </p>
                      {stringValue(hit.project_name) && (
                        <p className="mt-0.5 break-words text-[11px] text-muted-foreground">
                          项目：{stringValue(hit.project_name)}
                        </p>
                      )}
                    </div>
                    <p className="break-words font-mono text-[10px] text-muted-foreground">
                      {stringValue(hit.source_type) || "source_type —"} · chunk {formatCountValue(hit.chunk_index)}
                    </p>
                    {stringValue(hit.excerpt) && (
                      <p className="break-words text-[11px] leading-relaxed text-muted-foreground">
                        {stringValue(hit.excerpt)}
                      </p>
                    )}
                    <CandidateAnchorHitDiagnostics hit={hit} />
                  </div>
                  <Badge variant="outline" className="font-mono text-[10px]">
                    score {formatScore(hit.final_score ?? hit.score)}
                  </Badge>
                </EvidenceRow>
              ))}
            </div>
          )}
          <CandidateAnchorRagDiagnostics
            candidateAnchorRag={candidateAnchorRag}
            anchorScheduler={anchorScheduler}
          />
        </EvidenceSourceSection>

        <EvidenceSourceSection
          heading="实际注入 Prompt 的资料"
          status={promptStatus}
          summary={`${orderedPromptSlots.length} prompt slots · ${promptSlots.length} recorded`}
          emptyText="这条旧 trace 没有记录 prompt_slots。"
        >
          <PromptBudgetDiagnosticsPanel diagnostics={promptBudgetDiagnostics} />
          <p className="mb-2 text-[11px] leading-relaxed text-muted-foreground">
            按 Generator 最终接收的槽位展示；前面的版块解释“怎么选出来”，这里说明
            每个槽位是否注入以及注入了什么文本。
          </p>
          <div className="max-h-[42rem] space-y-3 overflow-auto pr-1">
            {orderedPromptSlots.map(({ definition, slot }) => (
              <PromptSlotCard
                key={definition.promptLabel}
                definition={definition}
                slot={slot}
              />
            ))}
          </div>
        </EvidenceSourceSection>

        <EvidenceSourceSection
          heading="辅助诊断"
          status="已注入"
          summary="legacy 通用知识库 RAG · avoid patterns · failure categories"
          emptyText="没有辅助诊断信息。"
        >
          <div className="space-y-3">
            <div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="font-medium">通用知识库 RAG</p>
                <Badge variant="outline" className="text-[10px]">
                  {ragStatus}
                </Badge>
              </div>
              <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                mode {stringValue(rag.mode) || "—"} · top_k {formatCountValue(rag.top_k)} · hits {docRefs.length}
              </p>
              {docRefs.length > 0 ? (
                <div className="mt-2 max-h-64 overflow-auto divide-y divide-border/70">
                  {renderTopItems(docRefs, (ref, idx) => (
                    <EvidenceRow key={`${String(ref.source ?? "")}-${idx}`}>
                      <div className="min-w-0">
                        <p className="break-words font-mono text-[11px]">
                          {stringValue(ref.source) || "unknown source"}
                        </p>
                        <p className="mt-0.5 text-muted-foreground">
                          chunk {formatCountValue(ref.chunk)} · {stringValue(ref.source_type) || "source_type —"}
                        </p>
                      </div>
                      <Badge variant="outline" className="font-mono text-[10px]">
                        score {formatScore(ref.score)}
                      </Badge>
                    </EvidenceRow>
                  ))}
                </div>
              ) : (
                <p className="mt-2 text-[11px] text-muted-foreground">
                  通用知识库没有命中可注入片段；这是 legacy 诊断，不再作为 ask_question 主叙事。
                </p>
              )}
            </div>

            <div className="grid gap-3 xl:grid-cols-2">
              <div className="rounded-md border bg-background/45 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium">规避模式</p>
                  <Badge variant={avoidStatus === "已注入" ? "success" : "outline"} className="text-[10px]">
                    {avoidStatus}
                  </Badge>
                </div>
                <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                  用于提醒 Generator 避开近期被验证器否定的浅层证据形态。
                </p>
              </div>
              <div className="rounded-md border bg-background/45 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="font-medium">失败类别</p>
                  <Badge variant={failureStatus === "已注入" ? "success" : "outline"} className="text-[10px]">
                    {failureStatus}
                  </Badge>
                </div>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {failureCategories.length > 0 ? (
                    failureCategories.map((category) => (
                      <Badge key={category} variant="outline" className="font-mono text-[10px]">
                        {category}
                      </Badge>
                    ))
                  ) : (
                    <p className="text-[11px] text-muted-foreground">
                      本轮没有从 refine_followup 带入失败类别。
                    </p>
                  )}
                </div>
              </div>
            </div>

          </div>
        </EvidenceSourceSection>
      </div>
    </section>
  );
}

function renderTopItems<T>(
  items: T[],
  renderItem: (item: T, index: number) => ReactNode,
  limit = 3,
) {
  return (
    <ExpandableEvidenceItems
      items={items}
      renderItem={renderItem}
      limit={limit}
    />
  );
}

function ExpandableEvidenceItems<T>({
  items,
  renderItem,
  limit,
}: {
  items: T[];
  renderItem: (item: T, index: number) => ReactNode;
  limit: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const visible = items.slice(0, limit);
  const hidden = items.slice(limit);
  return (
    <>
      {visible.map((item, index) => renderItem(item, index))}
      {hidden.length > 0 && (
        <div className="border-t border-border/70 pt-2">
          {expanded && (
            <div className="divide-y divide-border/70">
              {hidden.map((item, index) => renderItem(item, index + limit))}
            </div>
          )}
          <button
            type="button"
            className="mt-2 text-[11px] font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded ? "收起" : `展开剩余 ${hidden.length} 条`}
          </button>
        </div>
      )}
    </>
  );
}

function LegacyAskQuestionEvidencePanel({ node }: { node: TraceExplorerNode }) {
  const payload = recordFromUnknown(node.payload);
  const artifacts = recordFromUnknown(payload.selection_artifacts);
  const rag = recordFromUnknown(artifacts.rag);
  const strategies = recordArray(artifacts.strategies);
  const questionItems = recordArray(artifacts.question_items);
  const anchorScheduler = recordFromUnknown(artifacts.anchor_scheduler);
  const candidateAnchorRag = recordFromUnknown(artifacts.candidate_anchor_rag);
  const anchorHits = recordArray(candidateAnchorRag.hits);
  const resumeAnchor = recordFromUnknown(
    artifacts.resume_anchor ?? payload.resume_anchor,
  );
  const anchorLabel = resumeAnchorLabel(
    resumeAnchor,
    candidateAnchorRag,
  );
  const hitProjectLabel = candidateAnchorHitProjectLabel(anchorHits);
  const questionReranker = recordFromUnknown(artifacts.question_reranker);
  const questionFitProfile = recordFromUnknown(artifacts.question_fit_profile);
  const avoidPatterns = recordFromUnknown(artifacts.avoid_patterns);
  const failureCategories = stringList(artifacts.failure_categories);
  const docRefs = recordArray(rag.doc_refs);
  const injectedQuestion = questionItems.some((item) => item.injected === true);
  const questionSelectorMode =
    stringValue(artifacts.question_selector_mode) ||
    stringValue(questionReranker.question_selector_mode) ||
    inferQuestionSelectorMode(questionItems, rag);
  const probeIntent =
    stringValue(payload.probe_intent) ||
    stringValue(questionFitProfile.turn_intent) ||
    stringValue(questionItems[0]?.intent);
  const signedBy = stringList(payload.signed_by);
  const ragStatus = statusLabelForArtifact({
    enabled: stringValue(rag.mode) !== "none",
    empty: rag.empty === true || docRefs.length === 0,
    shadow: injectedQuestion && docRefs.length > 0,
    error: rag.error || rag.error_type,
  });
  const questionStatus = statusLabelForArtifact({
    enabled: questionItems.length > 0,
    empty: questionItems.length === 0,
    injected: injectedQuestion,
    shadow: questionItems.length > 0 && !injectedQuestion,
  });
  const strategyStatus = statusLabelForArtifact({
    enabled: true,
    empty: strategies.length === 0,
  });
  const anchorStatus = statusLabelForArtifact({
    enabled: stringValue(candidateAnchorRag.status) !== "off",
    empty:
      anchorHits.length === 0 &&
      Object.keys(resumeAnchor).length === 0,
    shadow: stringValue(candidateAnchorRag.status) === "shadow",
    injected: stringValue(candidateAnchorRag.status) === "primary",
    error: candidateAnchorRag.error || candidateAnchorRag.error_type,
  });
  const avoidStatus = statusLabelForArtifact({
    enabled: avoidPatterns.enabled === true,
    empty: avoidPatterns.rendered !== true,
  });

  return (
    <section className="mt-3 rounded-md border border-sky-500/25 bg-sky-500/[0.035] p-3 text-xs">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <Search className="h-3.5 w-3.5 text-sky-300" />
            <p className="font-medium text-sky-200">出题决策摘要</p>
          </div>
          <p className="mt-1 max-w-3xl text-muted-foreground">
            这条记录说明本轮问题生成前装配了哪些知识、题库、策略和候选人锚点。
          </p>
          <p className="mt-1 max-w-3xl text-[11px] text-muted-foreground">
            本节点记录出题前证据装配；回答和评分请查看同一 Turn 的 evaluator / verification 节点。
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Badge variant="outline" className="text-[10px]">
            RAG {ragStatus}
          </Badge>
          <Badge variant={injectedQuestion ? "success" : "outline"} className="text-[10px]">
            题库 {questionStatus}
          </Badge>
          {stringValue(questionReranker.status) && (
            <Badge variant="outline" className="text-[10px]">
              reranker {statusLabelForArtifact({ enabled: true, shadow: true })}
            </Badge>
          )}
        </div>
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-3">
        <NodeFact label="出题方案" value={stringValue(payload.plan_template) || "—"} />
        <NodeFact label="目标维度" value={node.dimension || stringValue(payload.dimension) || "—"} />
        <NodeFact label="问题意图" value={probeIntent || "—"} />
        <NodeFact label="题库模式" value={questionSelectorMode || "—"} />
        <NodeFact
          label="评分契约签署方"
          value={signedBy.length > 0 ? signedBy.join(", ") : "—"}
        />
        <NodeFact label="评分门槛" value={stringValue(payload.contract_bar_level) || "—"} />
        <NodeFact
          label="覆盖要求"
          value={formatCountValue(payload.contract_must_cover_count)}
        />
        <NodeFact
          label="验收检查"
          value={formatCountValue(payload.contract_acceptance_check_count)}
        />
        <NodeFact label="证据覆盖" value={`RAG ${docRefs.length} · 题库 ${questionItems.length} · 策略 ${strategies.length} · 锚点 ${anchorHits.length}`} />
      </div>

      <div
        className="mt-3 space-y-3"
        data-trace-section="ask-question-primary-evidence"
      >
        <EvidenceSourceSection
          heading="通用知识库 RAG"
          status={ragStatus}
          summary={`mode ${stringValue(rag.mode) || "—"} · top_k ${formatCountValue(rag.top_k)} · hits ${docRefs.length}`}
          emptyText="通用知识库没有命中可注入片段；候选人简历/自我介绍命中见下方候选人锚点 RAG。"
        >
          <div className="max-h-64 overflow-auto divide-y divide-border/70">
            {docRefs.slice(0, 8).map((ref, idx) => (
              <EvidenceRow key={`${String(ref.source ?? "")}-${idx}`}>
                <div className="min-w-0">
                  <p className="break-words font-mono text-[11px]">
                    {stringValue(ref.source) || "unknown source"}
                  </p>
                  <p className="mt-0.5 text-muted-foreground">
                    chunk {formatCountValue(ref.chunk)} · {stringValue(ref.source_type) || "source_type —"}
                  </p>
                </div>
                <Badge variant="outline" className="font-mono text-[10px]">
                  score {formatScore(ref.score)}
                </Badge>
              </EvidenceRow>
            ))}
          </div>
        </EvidenceSourceSection>

        <EvidenceSourceSection
          heading="结构化题库"
          status={questionStatus}
          summary={`${questionSelectorMode || "unknown"} · ${questionItems.length} candidates`}
          emptyText="本轮没有结构化题库候选。"
        >
          <div className="max-h-64 overflow-auto divide-y divide-border/70">
            {questionItems.slice(0, 8).map((item, idx) => (
              <StructuredQuestionCandidate
                key={`${String(item.variant_id ?? "")}-${idx}`}
                item={item}
              />
            ))}
          </div>
        </EvidenceSourceSection>

        <EvidenceSourceSection
          heading="策略记忆"
          status={strategyStatus}
          summary={`${strategies.length} strategy refs`}
          emptyText="本轮没有命中策略记忆。"
        >
          <div className="max-h-64 overflow-auto divide-y divide-border/70">
            {strategies.slice(0, 8).map((strategy, idx) => (
              <EvidenceRow key={`${String(strategy.id ?? strategy.name ?? "")}-${idx}`}>
                <div className="min-w-0">
                  <p className="break-words font-medium">
                    {localizeStrategyMemoryName(strategy)}
                  </p>
                  {strategyMemoryDescription(strategy) && (
                    <p className="mt-1 break-words text-[11px] leading-relaxed text-muted-foreground">
                      {strategyMemoryDescription(strategy)}
                    </p>
                  )}
                  <p className="mt-0.5 break-words font-mono text-[10px] text-muted-foreground">
                    {strategyMemoryTraceKey(strategy) || "strategy id —"}
                  </p>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    支撑样本 {formatCountValue(strategy.support_count)} · 置信度 {formatScore(strategy.confidence)}
                  </p>
                </div>
                <Badge variant="outline" className="font-mono text-[10px]">
                  {strategy.ranking_reason ? "ranking_reason" : "rank —"}
                </Badge>
              </EvidenceRow>
            ))}
          </div>
        </EvidenceSourceSection>

        <EvidenceSourceSection
          heading="候选人锚点 RAG"
          status={anchorStatus}
          summary={`scheduler ${stringValue(anchorScheduler.expansion_reason) || "none"} · rag ${stringValue(candidateAnchorRag.status) || "unknown"} · hits ${anchorHits.length}`}
          emptyText="本轮候选人锚点检索关闭或没有命中。"
        >
          <div className="grid gap-2 md:grid-cols-2">
            <NodeFact label="项目锚点" value={anchorLabel} />
            <NodeFact label="尝试次数" value={formatCountValue(anchorScheduler.anchor_attempt)} />
            <NodeFact
              label="锚点选择原因"
              value={localizeAnchorExpansionReason(anchorScheduler.expansion_reason)}
            />
            <NodeFact label="锚点 ID" value={stringValue(anchorScheduler.anchor_key) || "—"} />
            <NodeFact label="命中片段" value={formatCountValue(anchorHits.length)} />
            <NodeFact
              label="命中项目"
              value={hitProjectLabel}
            />
          </div>
          {anchorHits.length > 0 && (
            <div className="mt-2 max-h-64 overflow-auto divide-y divide-border/70">
              {anchorHits.slice(0, 6).map((hit, idx) => (
                <EvidenceRow key={`${String(hit.id ?? hit.chunk_index ?? "")}-${idx}`}>
                  <div className="min-w-0 space-y-1">
                    <p className="break-words font-medium">
                      {stringValue(hit.heading) ||
                        stringValue(hit.project_name) ||
                        `chunk ${formatCountValue(hit.chunk_index)}`}
                    </p>
                    <p className="break-words font-mono text-[10px] text-muted-foreground">
                      {stringValue(hit.source_type) || "source_type —"} · chunk {formatCountValue(hit.chunk_index)}
                    </p>
                    {stringValue(hit.excerpt) && (
                      <p className="break-words text-[11px] leading-relaxed text-muted-foreground">
                        {stringValue(hit.excerpt)}
                      </p>
                    )}
                  </div>
                  <Badge variant="outline" className="font-mono text-[10px]">
                    score {formatScore(hit.score)}
                  </Badge>
                </EvidenceRow>
              ))}
            </div>
          )}
        </EvidenceSourceSection>
      </div>

      <SkillSelectionPanel payload={node.payload} />

      <div className="mt-3 grid gap-3 xl:grid-cols-2">
        <EvidenceSourceSection
          heading="规避模式"
          status={avoidStatus}
          summary={`top_n ${formatCountValue(avoidPatterns.top_n)} · min_support ${formatCountValue(avoidPatterns.min_support)}`}
          emptyText="本轮没有渲染历史浅层回答规避模式。"
        >
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            用于提醒 Generator 避开近期被验证器否定的浅层证据形态。
          </p>
        </EvidenceSourceSection>
        <EvidenceSourceSection
          heading="失败类别"
          status={failureCategories.length > 0 ? "已注入" : "未命中"}
          summary={`${failureCategories.length} categories`}
          emptyText="本轮没有从 refine_followup 带入失败类别。"
        >
          <div className="flex flex-wrap gap-1.5">
            {failureCategories.map((category) => (
              <Badge key={category} variant="outline" className="font-mono text-[10px]">
                {category}
              </Badge>
            ))}
          </div>
        </EvidenceSourceSection>
      </div>
    </section>
  );
}

void LegacyAskQuestionEvidencePanel;

function EvidenceSourceSection({
  heading,
  status,
  summary,
  emptyText,
  children,
}: {
  heading: string;
  status: string;
  summary: string;
  emptyText: string;
  children: ReactNode;
}) {
  const hasContent = status !== "未命中" && status !== "关闭";
  return (
    <section className="rounded-md border bg-background/45 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="font-medium">{heading}</p>
          <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
            {summary}
          </p>
        </div>
        <Badge variant={status === "已注入" ? "success" : status === "轻量 warning" ? "warn" : "outline"} className="text-[10px]">
          {status}
        </Badge>
      </div>
      {hasContent ? (
        <div className="mt-2">{children}</div>
      ) : (
        <p className="mt-2 text-[11px] text-muted-foreground">{emptyText}</p>
      )}
    </section>
  );
}

function EvidenceRow({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-3 py-2 first:pt-0 last:pb-0">
      {children}
    </div>
  );
}

function CandidateAnchorHitDiagnostics({
  hit,
}: {
  hit: Record<string, unknown>;
}) {
  return (
    <details className="mt-2 rounded-md border bg-background/45 p-2 text-[11px]">
      <summary className="cursor-pointer select-none font-medium text-muted-foreground">
        展开排序诊断 <span className="font-mono">hit</span>
      </summary>
      <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <NodeFact label="锚点相似分" value={formatScore(hit.anchor_score)} />
        <NodeFact label="增强相似分" value={formatScore(hit.boost_score)} />
        <NodeFact label="约束匹配度" value={formatScore(hit.constraint_match)} />
        <NodeFact label="原始分" value={formatScore(hit.raw_score)} />
        <NodeFact label="向量距离" value={formatScore(hit.distance)} />
        <NodeFact label="已去重" value={formatBooleanValue(hit.deduped)} />
        <NodeFact
          label="命中目标技能"
          value={formatStringListValue(hit.matched_target_skills)}
        />
        <NodeFact
          label="命中维度"
          value={formatStringListValue(hit.matched_dimensions)}
        />
        <NodeFact
          label="命中题库词"
          value={formatStringListValue(hit.matched_seed_terms)}
        />
        <NodeFact
          label="去重原因"
          value={stringValue(hit.dedupe_reason) || "—"}
        />
      </div>
    </details>
  );
}

function CandidateAnchorRagDiagnostics({
  candidateAnchorRag,
  anchorScheduler,
}: {
  candidateAnchorRag: Record<string, unknown>;
  anchorScheduler: Record<string, unknown>;
}) {
  const bindValidation = recordFromUnknown(candidateAnchorRag.bind_validation);
  return (
    <details className="mt-3 rounded-md border bg-background/45 p-2 text-[11px]">
      <summary className="cursor-pointer select-none font-medium text-muted-foreground">
        展开检索诊断 <span className="font-mono">candidate_anchor_rag</span>
      </summary>
      <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <NodeFact
          label="锚点 ID"
          value={
            stringValue(candidateAnchorRag.anchor_key) ||
            stringValue(anchorScheduler.anchor_key) ||
            "—"
          }
        />
        <NodeFact
          label="锚点检索词"
          value={formatStringListValue(candidateAnchorRag.anchor_terms)}
        />
        <NodeFact
          label="增强检索词"
          value={formatStringListValue(candidateAnchorRag.boost_terms)}
        />
        <NodeFact
          label="约束检索词"
          value={formatStringListValue(candidateAnchorRag.constraint_terms)}
        />
        <NodeFact
          label="排序权重"
          value={formatKeyValueRecord(candidateAnchorRag.ranking_weights)}
        />
        <NodeFact
          label="注入来源计数"
          value={formatKeyValueRecord(candidateAnchorRag.prompt_source_counts)}
        />
        <NodeFact
          label="fetched_rows_by_source"
          value={formatKeyValueRecord(candidateAnchorRag.fetched_rows_by_source)}
        />
        <NodeFact
          label="scored_rows_by_source"
          value={formatKeyValueRecord(candidateAnchorRag.scored_rows_by_source)}
        />
        <NodeFact
          label="kept_hits_by_source"
          value={formatKeyValueRecord(candidateAnchorRag.kept_hits_by_source)}
        />
        <NodeFact
          label="bind_validation.fallback_reason"
          value={formatCandidateAnchorFallbackReason(bindValidation.fallback_reason)}
        />
        <NodeFact
          label="bind_validation.bound_count"
          value={formatCountValue(bindValidation.bound_count)}
        />
        <NodeFact
          label="bind_validation.resume_bound_count"
          value={formatCountValue(bindValidation.resume_bound_count)}
        />
        <NodeFact
          label="bind_validation.self_intro_bound_count"
          value={formatCountValue(bindValidation.self_intro_bound_count)}
        />
        <NodeFact
          label="bind_validation.rebind_attempted"
          value={formatBooleanValue(bindValidation.rebind_attempted)}
        />
        <NodeFact
          label="bind_validation.rebind_success"
          value={formatBooleanValue(bindValidation.rebind_success)}
        />
        <NodeFact
          label="bind_validation.resume_revision_id"
          value={stringValue(bindValidation.resume_revision_id) || "—"}
        />
        <NodeFact
          label="bind_validation.self_intro_revision_id"
          value={stringValue(bindValidation.self_intro_revision_id) || "—"}
        />
        <NodeFact
          label="bind_validation.embedding_model_version"
          value={stringValue(bindValidation.embedding_model_version) || "—"}
        />
        <NodeFact
          label="bind_validation.source_cache_key"
          value={stringValue(bindValidation.source_cache_key) || "—"}
        />
        <NodeFact label="完整检索文本" value={stringValue(candidateAnchorRag.query_text) || "—"} />
        <NodeFact
          label="锚点检索文本"
          value={stringValue(candidateAnchorRag.anchor_query_text) || "—"}
        />
        <NodeFact
          label="增强检索文本"
          value={stringValue(candidateAnchorRag.boost_query_text) || "—"}
        />
        <NodeFact
          label="约束检索文本"
          value={stringValue(candidateAnchorRag.constraint_query_text) || "—"}
        />
      </div>
    </details>
  );
}

function PromptBudgetDiagnosticsPanel({
  diagnostics,
}: {
  diagnostics: Record<string, unknown>;
}) {
  if (Object.keys(diagnostics).length === 0) return null;
  const protectedSlots = recordArray(diagnostics.protected_slots);
  const fallbackUsed = diagnostics.fallback_used === true;
  const budgetLevel = stringValue(diagnostics.budget_level) || "-";
  const provider = stringValue(diagnostics.provider) || "-";
  const model = stringValue(diagnostics.model) || "-";
  return (
    <div className="mb-3 rounded-md bg-background/45 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-medium">Prompt 预算诊断</p>
          <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
            prompt_budget_diagnostics · {budgetLevel}
          </p>
        </div>
        <Badge variant={fallbackUsed ? "warn" : "outline"} className="text-[10px]">
          {fallbackUsed ? "fallback" : "estimated"}
        </Badge>
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
        只为弹性辅助材料分配运行时预算：StrategyMemory 与 Skills 会根据模型窗口和非弹性槽位占用选择裁剪档位。
      </p>
      <div className="mt-2 grid gap-2 md:grid-cols-2 lg:grid-cols-4">
        <NodeFact label="模型路由" value={`${provider} / ${model}`} />
        <NodeFact label="预算档位 budget_level" value={budgetLevel} />
        <NodeFact
          label="上下文窗口"
          value={formatCountValue(diagnostics.context_window_tokens)}
        />
        <NodeFact
          label="非弹性槽位字符"
          value={formatCountValue(diagnostics.protected_slot_chars)}
        />
        <NodeFact
          label="弹性剩余字符"
          value={formatCountValue(diagnostics.elastic_available_chars)}
        />
        <NodeFact
          label="Strategy 预算"
          value={formatCountValue(diagnostics.strategy_budget_chars)}
        />
        <NodeFact
          label="Skill 预算"
          value={formatCountValue(diagnostics.skill_budget_chars)}
        />
        <NodeFact
          label="回退原因 fallback_reason"
          value={stringValue(diagnostics.fallback_reason) || "-"}
        />
      </div>
      {protectedSlots.length > 0 && (
        <details className="mt-2 text-[11px]">
          <summary className="cursor-pointer select-none font-medium text-muted-foreground">
            展开 protected_slots
          </summary>
          <div className="mt-2 grid gap-2 md:grid-cols-2 lg:grid-cols-4">
            {protectedSlots.map((slot, index) => (
              <NodeFact
                key={`${stringValue(slot.prompt_label) || index}`}
                label={stringValue(slot.prompt_label) || `slot ${index + 1}`}
                value={`${formatCountValue(slot.chars)} chars`}
              />
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function PromptSlotCard({
  definition,
  slot,
}: {
  definition: PromptSlotDefinition;
  slot: Record<string, unknown> | null;
}) {
  const recorded = slot !== null;
  const text = stringValue(slot?.text);
  const preview =
    text.length > PROMPT_SLOT_PREVIEW_LIMIT
      ? `${text.slice(0, PROMPT_SLOT_PREVIEW_LIMIT)}...`
      : text;
  const status = !recorded ? "未记录" : slot?.injected === true ? "已注入" : "未注入";
  const sourceKey = stringValue(slot?.source_key) || definition.sourceKey;
  const emptyReason = stringValue(slot?.empty_reason);
  const hasExplicitPromptTruncation = typeof slot?.prompt_truncated === "boolean";
  const promptTruncated = hasExplicitPromptTruncation
    ? slot?.prompt_truncated === true
    : slot?.truncated === true;
  const traceTextTruncated = slot?.trace_text_truncated === true;
  const runtimeTruncated = slot?.runtime_truncated === true;
  const runtimeItems = recordArray(slot?.runtime_items);
  return (
    <div className="rounded-md border bg-background/45 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="break-words font-medium">{definition.title}</p>
          <p className="mt-0.5 break-words font-mono text-[10px] text-muted-foreground">
            {definition.promptLabel}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge
            variant={slot?.injected === true ? "success" : "outline"}
            className="text-[10px]"
          >
            {status}
          </Badge>
          {promptTruncated && (
            <Badge variant="warn" className="text-[10px]">
              Prompt 截断
            </Badge>
          )}
          {runtimeTruncated && (
            <Badge variant="warn" className="text-[10px]">
              运行时裁剪
            </Badge>
          )}
          {traceTextTruncated && (
            <Badge variant="outline" className="text-[10px]">
              Trace 文本截断
            </Badge>
          )}
        </div>
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
        {definition.description}
      </p>
      <div className="mt-2 grid gap-2 md:grid-cols-2 lg:grid-cols-4">
        <NodeFact label="来源字段" value={sourceKey} />
        <NodeFact label="字符数" value={recorded ? formatCountValue(slot?.chars) : "—"} />
        <NodeFact
          label="Prompt 预算截断"
          value={recorded ? formatBooleanValue(promptTruncated) : "—"}
        />
        <NodeFact
          label="Trace 文本截断"
          value={recorded ? formatBooleanValue(traceTextTruncated) : "—"}
        />
        <NodeFact
          label="运行时裁剪"
          value={recorded ? formatBooleanValue(runtimeTruncated) : "—"}
        />
        <NodeFact
          label="运行时预算"
          value={recorded ? formatCountValue(slot?.runtime_budget_chars) : "—"}
        />
        <NodeFact
          label="预算档位 budget_level"
          value={recorded ? stringValue(slot?.runtime_budget_level) || "—" : "—"}
        />
        <NodeFact
          label="预算来源 budget_source"
          value={recorded ? stringValue(slot?.runtime_budget_source) || "—" : "—"}
        />
        <NodeFact
          label="预算压力 global_budget_pressure"
          value={
            recorded
              ? stringValue(slot?.runtime_global_budget_pressure) || "—"
              : "—"
          }
        />
        <NodeFact
          label="运行时原始字符"
          value={recorded ? formatCountValue(slot?.runtime_original_chars) : "—"}
        />
        <NodeFact
          label="运行时注入字符"
          value={recorded ? formatCountValue(slot?.runtime_injected_chars) : "—"}
        />
        <NodeFact label="空原因" value={emptyReason || "—"} />
      </div>
      {text ? (
        <div className="mt-2">
          <pre className="max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-md border bg-background/60 p-2 font-mono text-[11px]">
            {preview}
          </pre>
          {text.length > PROMPT_SLOT_PREVIEW_LIMIT && (
            <details className="mt-2 rounded-md border bg-background/50 p-2 text-[11px]">
              <summary className="cursor-pointer select-none font-medium text-muted-foreground">
                展开完整内容 <span className="font-mono">{definition.promptLabel}</span>
              </summary>
              <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md bg-background/60 p-2 font-mono text-[11px]">
                {text}
              </pre>
            </details>
          )}
        </div>
      ) : (
        <p className="mt-2 text-[11px] text-muted-foreground">
          {recorded ? "本槽位未注入文本。" : "旧 trace 未记录这个 prompt slot。"}
        </p>
      )}
      {runtimeItems.length > 0 && <PromptRuntimeItemsDetails items={runtimeItems} />}
    </div>
  );
}

const PROMPT_RUNTIME_TRUNCATION_REASON_LABELS: Record<string, string> = {
  field_char_limit: "字段字符限制",
  field_item_limit: "字段数量限制",
  body_budget_exceeded: "正文预算不足",
  slot_budget_omitted_body: "槽位预算省略正文",
};

function promptRuntimeTruncationReasonLabel(value: unknown): string {
  const code = stringValue(value);
  if (!code) return "—";
  const label = PROMPT_RUNTIME_TRUNCATION_REASON_LABELS[code];
  return label ? `${label} · ${code}` : code;
}

function PromptRuntimeItemsDetails({
  items,
}: {
  items: Record<string, unknown>[];
}) {
  return (
    <details className="mt-2 rounded-md border bg-background/50 p-2 text-[11px]">
      <summary className="cursor-pointer select-none font-medium text-muted-foreground">
        展开运行时裁剪明细
      </summary>
      <div className="mt-2 space-y-2">
        {items.map((item, idx) => {
          const name =
            stringValue(item.name) ||
            stringValue(item.project_name) ||
            stringValue(item.heading) ||
            stringValue(item.source_type);
          const id =
            stringValue(item.id) ||
            stringValue(item.skill_id) ||
            stringValue(item.chunk_index);
          return (
            <div key={`${id || idx}`} className="rounded-md border bg-background/60 p-2">
              <div className="mb-2 flex flex-wrap items-center gap-1.5">
                <Badge variant="outline" className="text-[10px]">
                  rank {formatCountValue(item.rank)}
                </Badge>
                {item.runtime_truncated === true && (
                  <Badge variant="warn" className="text-[10px]">
                    运行时裁剪
                  </Badge>
                )}
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <NodeFact label="名称" value={name || "—"} />
                <NodeFact label="ID" value={id || "—"} />
                <NodeFact label="字段" value={stringValue(item.field) || "—"} />
                <NodeFact
                  label="限制类型"
                  value={stringValue(item.limit_type) || "—"}
                />
                <NodeFact
                  label="限制值"
                  value={formatCountValue(item.limit)}
                />
                <NodeFact label="来源类型" value={stringValue(item.source_type) || "—"} />
                <NodeFact label="项目" value={stringValue(item.project_name) || "—"} />
                <NodeFact label="标题" value={stringValue(item.heading) || "—"} />
                <NodeFact
                  label="Chunk"
                  value={formatCountValue(item.chunk_index)}
                />
                <NodeFact label="匹配分" value={formatScore(item.score)} />
                <NodeFact
                  label="Body 预算"
                  value={formatCountValue(item.body_budget_chars)}
                />
                <NodeFact
                  label="原始 Body 字符"
                  value={formatCountValue(item.original_body_chars)}
                />
                <NodeFact
                  label="注入 Body 字符"
                  value={formatCountValue(item.injected_body_chars)}
                />
                <NodeFact
                  label="是否裁剪"
                  value={formatBooleanValue(item.runtime_truncated)}
                />
                <NodeFact
                  label="原因码"
                  value={promptRuntimeTruncationReasonLabel(item.truncation_reason)}
                />
              </div>
            </div>
          );
        })}
      </div>
    </details>
  );
}

function StrategyRankingReasonDetails({
  strategy,
}: {
  strategy: Record<string, unknown>;
}) {
  const reason = recordFromUnknown(strategy.ranking_reason);
  if (Object.keys(reason).length === 0) return null;
  const requestedContextKeys = stringList(reason.requested_context_keys);
  return (
    <details className="mt-2 rounded-md border bg-background/45 p-2 text-[11px]">
      <summary className="cursor-pointer select-none font-medium text-muted-foreground">
        展开 <span className="font-mono">ranking_reason</span>
      </summary>
      <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <NodeFact label="基础匹配分" value={formatCountValue(reason.base_score)} />
        <NodeFact label="策略优先级" value={formatCountValue(reason.priority)} />
        <NodeFact label="历史使用" value={formatCountValue(reason.uses)} />
        <NodeFact
          label="统计作用域"
          value={stringValue(reason.stats_scope) || "none"}
        />
        <NodeFact
          label="统计上下文键"
          value={stringValue(reason.stats_context_key) || "—"}
        />
        <NodeFact label="平均奖励" value={formatScore(reason.avg_blended_reward)} />
        <NodeFact label="推翻率" value={formatScore(reason.overrule_rate)} />
        <NodeFact label="排序名次" value={formatCountValue(strategy.shadow_rank)} />
        <NodeFact label="排序分" value={formatScore(strategy.ranking_score)} />
      </div>
      {requestedContextKeys.length > 0 && (
        <p className="mt-2 break-words font-mono text-[10px] text-muted-foreground">
          requested_context_keys: {requestedContextKeys.join("、")}
        </p>
      )}
    </details>
  );
}

function EvidenceList({ label, values }: { label: string; values: string[] }) {
  if (values.length === 0) return null;
  return (
    <div>
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <ul className="mt-1 list-disc space-y-1 pl-4">
        {values.map((value, idx) => (
          <li key={idx} className="break-all">
            {value}
          </li>
        ))}
      </ul>
    </div>
  );
}

function AcceptanceCheckItemsList({
  label,
  values,
  items,
}: {
  label: string;
  values: string[];
  items: Record<string, unknown>[];
}) {
  const visibleItems = items.filter(
    (item) => stringValue(item.text) || stringValue(item.acceptance_check),
  );
  if (visibleItems.length === 0) {
    return <EvidenceList label={label} values={values} />;
  }

  return (
    <div>
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <div className="mt-1 space-y-2">
        {visibleItems.map((item, idx) => {
          const text = stringValue(item.text) || stringValue(item.acceptance_check);
          const source = stringValue(item.source) || "source -";
          const severity = stringValue(item.severity) || "supporting";
          const checkId = stringValue(item.check_id);
          const sourceText = stringValue(item.source_text);
          const origin = stringValue(item.origin);
          return (
            <div
              key={`${checkId || text}-${idx}`}
              className="rounded-md border bg-background/50 p-2"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <p className="min-w-0 flex-1 break-words font-medium">{text}</p>
                <div className="flex flex-wrap justify-end gap-1">
                  <Badge variant="outline" className="font-mono text-[10px]">
                    {source}
                  </Badge>
                  <Badge variant="outline" className="font-mono text-[10px]">
                    {severity}
                  </Badge>
                </div>
              </div>
              {(checkId || sourceText || origin) && (
                <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[10px] text-muted-foreground">
                  {checkId && <span>check_id: {checkId}</span>}
                  {origin && <span>origin: {origin}</span>}
                  {sourceText && <span>source_text: {sourceText}</span>}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function AcceptanceCheckResults({
  results,
}: {
  results: Record<string, unknown>;
}) {
  const entries = Object.entries(results);
  if (entries.length === 0) return null;

  return (
    <details className="rounded-md border bg-background/45 p-2">
      <summary className="cursor-pointer select-none font-medium">
        展开验收检查 <span className="font-mono">acceptance_check_results</span>
        <span className="ml-1 text-muted-foreground">yes / partial / no</span>
      </summary>
      <div className="mt-2 space-y-2">
        {entries.map(([check, value]) => {
          const item = recordFromUnknown(value);
          const verdict = acceptanceVerdict(value);
          const evidenceQuotes = acceptanceEvidenceQuotes(item);
          return (
            <div key={check} className="rounded-md border bg-background/50 p-2">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <p className="break-words font-medium">{check}</p>
                <Badge
                  variant="outline"
                  className={`font-mono text-[10px] ${acceptanceVerdictBadgeClass(verdict)}`}
                >
                  {verdict || "verdict —"}
                </Badge>
              </div>
              {evidenceQuotes.length > 0 && (
                <details className="mt-2 rounded-md border bg-background/50 p-2">
                  <summary className="cursor-pointer select-none text-muted-foreground">
                    展开 evidence quotes
                  </summary>
                  <ul className="mt-2 list-disc space-y-1 pl-4">
                    {evidenceQuotes.map((quote, idx) => (
                      <li key={idx} className="break-words">
                        {quote}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          );
        })}
      </div>
    </details>
  );
}

function ContractGateResultPanel({
  result,
  enforcement,
}: {
  result: Record<string, unknown>;
  enforcement?: Record<string, unknown>;
}) {
  const status = stringValue(result.status);
  if (!status) return null;
  const failedItems = recordArray(result.failed_items);
  const wouldPass = result.would_pass;
  const enforced = enforcement?.contract_gate_enforced === true;
  const enforcementReason = stringValue(
    enforcement?.contract_gate_enforcement_reason,
  );
  const failedCheckIds = stringList(enforcement?.contract_gate_failed_check_ids);
  const badgeVariant =
    status === "failed" ? "warn" : status === "passed" ? "success" : "outline";

  return (
    <details className="rounded-md border border-amber-500/25 bg-amber-500/[0.035] p-2">
      <summary className="cursor-pointer select-none font-medium">
        Reviewed core gate{" "}
        <span className="font-mono">contract_gate_result</span>
      </summary>
      <div className="mt-2 grid gap-2 md:grid-cols-2 lg:grid-cols-3">
        <NodeFact label="status" value={status} />
        <NodeFact
          label="would_pass"
          value={
            typeof wouldPass === "boolean"
              ? formatBooleanValue(wouldPass)
              : "not_applicable"
          }
        />
        <NodeFact label="mode" value={stringValue(result.mode) || "shadow"} />
        <NodeFact
          label="contract_gate_enforced"
          value={formatBooleanValue(enforced)}
        />
        {enforcementReason && (
          <NodeFact
            label="contract_gate_enforcement_reason"
            value={enforcementReason}
          />
        )}
        <NodeFact
          label="eligible"
          value={formatCountValue(result.eligible_count)}
        />
        <NodeFact
          label="satisfied"
          value={formatCountValue(result.satisfied_count)}
        />
        <NodeFact label="failed" value={formatCountValue(result.failed_count)} />
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        <Badge variant={badgeVariant} className="font-mono text-[10px]">
          {status}
        </Badge>
        <Badge variant="outline" className="font-mono text-[10px]">
          partial {formatCountValue(result.partial_count)}
        </Badge>
        <Badge variant="outline" className="font-mono text-[10px]">
          no {formatCountValue(result.no_count)}
        </Badge>
        <Badge variant="outline" className="font-mono text-[10px]">
          missing {formatCountValue(result.missing_count)}
        </Badge>
        {enforced && (
          <Badge variant="warn" className="font-mono text-[10px]">
            enforced
          </Badge>
        )}
      </div>
      {failedCheckIds.length > 0 && (
        <EvidenceList
          label="contract_gate_failed_check_ids"
          values={failedCheckIds}
        />
      )}
      {failedItems.length > 0 && (
        <div className="mt-2 space-y-2">
          {failedItems.map((item, idx) => (
            <div
              key={`${stringValue(item.check_id) || stringValue(item.text)}-${idx}`}
              className="rounded-md border bg-background/50 p-2"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <p className="min-w-0 flex-1 break-words font-medium">
                  {stringValue(item.text) || "gate item"}
                </p>
                <Badge variant="warn" className="font-mono text-[10px]">
                  {stringValue(item.reason) || "failed"}
                </Badge>
              </div>
              <p className="mt-1 break-words font-mono text-[10px] text-muted-foreground">
                {[
                  stringValue(item.check_id)
                    ? `check_id: ${stringValue(item.check_id)}`
                    : "",
                  stringValue(item.verdict)
                    ? `verdict: ${stringValue(item.verdict)}`
                    : "verdict: missing",
                  `evidence_count: ${formatCountValue(item.evidence_count)}`,
                ]
                  .filter(Boolean)
                  .join(" | ")}
              </p>
            </div>
          ))}
        </div>
      )}
    </details>
  );
}

function AcceptanceCheckResultItemsList({
  items,
  fallbackResults,
}: {
  items: Record<string, unknown>[];
  fallbackResults: Record<string, unknown>;
}) {
  const visibleItems = items.filter((item) => stringValue(item.text));
  if (visibleItems.length === 0) {
    const acceptanceCheckResults = fallbackResults;
    return <AcceptanceCheckResults results={acceptanceCheckResults} />;
  }

  return (
    <details className="rounded-md border bg-background/45 p-2">
      <summary className="cursor-pointer select-none font-medium">
        展开验收检查 <span className="font-mono">acceptance_check_result_items</span>
        <span className="ml-1 text-muted-foreground">yes / partial / no</span>
      </summary>
      <div className="mt-2 space-y-2">
        {visibleItems.map((item, idx) => {
          const text = stringValue(item.text);
          const source = stringValue(item.source) || "source -";
          const severity = stringValue(item.severity) || "supporting";
          const checkId = stringValue(item.check_id);
          const verdict = stringValue(item.verdict);
          const evidenceQuotes = acceptanceEvidenceQuotes(item);
          const missingResult = item.result_present === false;
          return (
            <div
              key={`${checkId || text}-${idx}`}
              className="rounded-md border bg-background/50 p-2"
            >
              <div className="flex flex-wrap items-start justify-between gap-2">
                <p className="min-w-0 flex-1 break-words font-medium">{text}</p>
                <div className="flex flex-wrap justify-end gap-1">
                  <Badge variant="outline" className="font-mono text-[10px]">
                    {source}
                  </Badge>
                  <Badge variant="outline" className="font-mono text-[10px]">
                    {severity}
                  </Badge>
                  <Badge
                    variant="outline"
                    className={`font-mono text-[10px] ${acceptanceVerdictBadgeClass(verdict)}`}
                  >
                    {verdict || (missingResult ? "missing" : "verdict -")}
                  </Badge>
                </div>
              </div>
              {checkId && (
                <p className="mt-1 break-words font-mono text-[10px] text-muted-foreground">
                  check_id: {checkId}
                </p>
              )}
              {evidenceQuotes.length > 0 && (
                <details className="mt-2 rounded-md border bg-background/50 p-2">
                  <summary className="cursor-pointer select-none text-muted-foreground">
                    展开 evidence quotes
                  </summary>
                  <ul className="mt-2 list-disc space-y-1 pl-4">
                    {evidenceQuotes.map((quote, quoteIdx) => (
                      <li key={quoteIdx} className="break-words">
                        {quote}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          );
        })}
      </div>
    </details>
  );
}

function RawTracePayloadDetails({
  rawPayload,
}: {
  rawPayload: Record<string, unknown>;
}) {
  const [open, setOpen] = useState(false);
  const serialized = useMemo(
    () => (open ? JSON.stringify(rawPayload, null, 2) : ""),
    [open, rawPayload],
  );

  return (
    <details
      className="flex-1 rounded-md border bg-background/60 p-2 text-xs"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary className="cursor-pointer select-none text-muted-foreground">
        查看原始 Trace Payload
      </summary>
      {open ? (
        <pre className="mt-2 max-h-[32rem] overflow-auto whitespace-pre-wrap break-all font-mono text-[11px]">
          {serialized}
        </pre>
      ) : (
        <p className="mt-2 text-[11px] text-muted-foreground">
          展开后再渲染 JSON，避免长 trace 首屏做无效 stringify。
        </p>
      )}
    </details>
  );
}

function NodeFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md bg-background/60 p-2">
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 min-w-0 whitespace-pre-wrap break-words font-mono text-[11px]">{value}</p>
    </div>
  );
}

function NodeTimingBar({ payload }: { payload?: Record<string, unknown> | null }) {
  const timing = (payload as Record<string, unknown> | undefined)?.timing as
    | Record<string, unknown>
    | undefined;
  if (!timing) return null;

  const nodeMs = typeof timing.node_elapsed_ms === "number" ? timing.node_elapsed_ms : null;
  const llmMs = typeof timing.llm_total_ms === "number" ? timing.llm_total_ms : null;
  const llmCalls = Array.isArray(timing.llm_calls) ? timing.llm_calls.length : 0;

  if (nodeMs === null && llmMs === null) return null;

  return (
    <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px]">
      <Timer className="h-3 w-3 text-muted-foreground" />
      {nodeMs !== null && (
        <Badge
          variant={nodeMs > 5000 ? "warn" : "outline"}
          className="font-mono text-[10px] gap-1"
        >
          节点耗时 {formatMs(nodeMs)}
        </Badge>
      )}
      {llmMs !== null && (
        <Badge variant="outline" className="font-mono text-[10px] gap-1">
          LLM 耗时 {formatMs(llmMs)}{llmCalls > 0 ? ` · ${llmCalls} calls` : ""}
        </Badge>
      )}
      {nodeMs !== null && llmMs !== null && nodeMs > 0 && (
        <span className="text-muted-foreground">
          LLM 占比 {Math.round((llmMs / nodeMs) * 100)}%
        </span>
      )}
    </div>
  );
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function isEvaluatorFallbackTrace(node: TraceExplorerNode): boolean {
  if (node.node !== "evaluator") return false;
  const evaluation = recordFromUnknown(node.evaluation);
  const payload = recordFromUnknown(node.payload);
  return (
    hasFallbackMarker(evaluation) ||
    hasFallbackMarker(recordFromUnknown(payload.evaluation)) ||
    hasFallbackMarker(payload)
  );
}

function hasFallbackMarker(record: Record<string, unknown>): boolean {
  if (record.source === "fallback") return true;
  if (typeof record.fallback_reason === "string" && record.fallback_reason.trim()) {
    return true;
  }
  const weaknesses = record.weaknesses;
  return Array.isArray(weaknesses)
    ? weaknesses.some((item) => String(item ?? "").toLowerCase().includes("fallback"))
    : false;
}

function recordFromUnknown(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function splitPolicyId(policyId?: string | null): {
  algorithm: string;
  space: string;
  context: string;
} {
  const parts = String(policyId || "")
    .split("::")
    .map((part) => part.trim())
    .filter(Boolean);
  return {
    algorithm: parts[0] || "—",
    space: parts[1] || "—",
    context: parts.slice(2).join("::") || "—",
  };
}

function localizeActionDescription(
  actionId: string,
  actionLabel: string,
  description: string,
): string {
  const labels: Record<string, string> = {
    plan_simple: "轻量首轮探测，不进行评分契约预审。",
    plan_quick_review: "紧凑复核当前维度，快速确认一个信号后继续推进。",
    plan_adaptive: "标准自适应出题，并让 evaluator 预审评分契约。",
    plan_deep_probe: "围绕上一轮弱点深挖，使用更严格的评分契约与挑战场景。",
    plan_hint: "保持当前维度，用更轻的提示式问题帮助候选人展开。",
    plan_switch: "切换到下一个待覆盖维度，并用 adaptive 模板出下一题。",
    deepen_technical: "在当前技术维度继续加深，要求候选人给出具体机制。",
    switch_dimension: "切换到下一个尚未评估的维度。",
    give_hint: "给一个小提示，保持当前维度后重新提问。",
    skip_to_next: "收束当前问题线，进入下一题。",
  };
  return labels[actionId] || localizeActionDescriptionByLabel(actionLabel) || description;
}

function localizeActionDescriptionByLabel(actionLabel: string): string {
  const labels: Record<string, string> = {
    "Plan: Simple": "轻量首轮探测，不进行评分契约预审。",
    "Plan: Quick Review": "紧凑复核当前维度，快速确认一个信号后继续推进。",
    "Plan: Adaptive": "标准自适应出题，并让 evaluator 预审评分契约。",
    "Plan: Deep Probe": "围绕上一轮弱点深挖，使用更严格的评分契约与挑战场景。",
    "Plan: Hint": "保持当前维度，用更轻的提示式问题帮助候选人展开。",
    "Plan: Switch": "切换到下一个待覆盖维度，并用 adaptive 模板出下一题。",
    "Deepen Technical": "在当前技术维度继续加深，要求候选人给出具体机制。",
    "Switch Dimension": "切换到下一个尚未评估的维度。",
    "Give Hint": "给一个小提示，保持当前维度后重新提问。",
    "Skip To Next": "收束当前问题线，进入下一题。",
  };
  return labels[actionLabel] || "";
}

function localizeActionName(actionId: string, actionLabel: string): string {
  const labels: Record<string, string> = {
    plan_simple: "轻量探测",
    plan_quick_review: "快速复核",
    plan_adaptive: "自适应出题",
    plan_deep_probe: "深挖探测",
    plan_hint: "提示式出题",
    plan_switch: "切换维度出题",
    deepen_technical: "技术加深",
    switch_dimension: "切换维度",
    give_hint: "给出提示",
    skip_to_next: "跳到下一题",
  };
  return labels[actionId] || labels[actionLabel] || actionLabel || actionId || "—";
}

function localizePlanTemplateName(template: string): string {
  const labels: Record<string, string> = {
    simple: "轻量模板",
    quick_review: "快速复核模板",
    adaptive: "标准自适应模板",
    deep_probe: "深挖探测模板",
  };
  if (!template) return "—";
  return `${labels[template] || "未识别模板"} · ${template}`;
}

function localizeDimensionEffect(effect: string): string {
  if (effect === "switch") return "切换到下一个待覆盖维度 · dimension_effect=switch";
  if (effect === "none") return "保持当前维度 · dimension_effect=none";
  return effect ? `${effect}` : "—";
}

function planTemplateSourceLabel(selectedAction: Record<string, unknown>): string {
  if (stringValue(selectedAction.plan_template_hint)) {
    return "上游 pending_plan_template 覆盖";
  }
  if (stringValue(selectedAction.plan_template)) {
    return "出题动作默认模板";
  }
  return "未记录";
}

function diagnosticModeLabel(mode: string): string {
  const labels: Record<string, string> = {
    coverage_priority_switch: "覆盖优先，切到未评分维度",
    coverage_force_switch: "当前维度追问次数已到上限，强制推进覆盖",
    anchor_expansion: "所有维度已过，扩展候选人项目锚点",
  };
  if (!mode) return "Thompson Sampling 按当前 context 选择";
  return `${labels[mode] || "后端诊断模式"} · ${mode}`;
}

function actionGuardrailFromPayload(
  payload?: Record<string, unknown> | null,
): Record<string, unknown> {
  const record = recordFromUnknown(payload);
  const diagnostics = recordFromUnknown(record.diagnostics);
  const selectedAction = recordFromUnknown(record.selected_action);
  const selectedDiagnostics = recordFromUnknown(selectedAction.diagnostics);
  const direct = recordFromUnknown(diagnostics.action_guardrail);
  if (Object.keys(direct).length > 0) return direct;
  return recordFromUnknown(selectedDiagnostics.action_guardrail);
}

function actionGuardrailReasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    refine_mode: "追问轮次",
    pending_contract_hints: "存在待处理评分提示",
    pending_plan_template: "存在待处理计划模板",
    target_difficulty_hard: "目标难度为 hard",
    verifier_forced_refine: "verification 强制追问",
    verification_soft_warning: "verification 留下软警告",
    contract_unsigned: "上一轮评分契约未由 evaluator 签署",
    contract_missing_must_cover: "评分契约缺少覆盖要求",
    contract_missing_acceptance_checks: "评分契约缺少验收检查",
    consecutive_low_score: "同维度连续低分或未通过",
    guardrail_fallback_empty_mask: "过滤后候选为空，已回退原候选",
  };
  if (!reason) return "未知原因";
  return `${labels[reason] || "后端 guardrail 原因"} · ${reason}`;
}

function recordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item),
      )
    : [];
}

function recordWithPayloadFallback(
  primary: unknown,
  fallback: unknown,
): Record<string, unknown> {
  const primaryRecord = recordFromUnknown(primary);
  if (Object.keys(primaryRecord).length > 0) return primaryRecord;
  return recordFromUnknown(fallback);
}

function evaluatorContractSourceLabel(source: string): string {
  const labels: Record<string, string> = {
    current_contract: "current_contract",
    "current_question.contract": "current_question.contract",
    legacy_rubric_points: "legacy rubric",
    "ask_question.contract": "ask_question contract",
    missing: "未记录",
  };
  return labels[source] || source || "未记录";
}

function acceptanceVerdict(value: unknown): string {
  if (typeof value === "string") return value.trim();
  const record = recordFromUnknown(value);
  return (
    stringValue(record.verdict) ||
    stringValue(record.status) ||
    stringValue(record.result)
  );
}

function acceptanceVerdictBadgeClass(verdict: string): string {
  if (verdict === "yes") {
    return "border-transparent bg-emerald-500/20 text-emerald-300";
  }
  if (verdict === "partial") {
    return "border-transparent bg-sky-500/20 text-sky-300";
  }
  if (verdict === "no") {
    return "border-transparent bg-rose-500/20 text-rose-300";
  }
  return "";
}

function acceptanceEvidenceQuotes(item: Record<string, unknown>): string[] {
  const quotes = [
    ...stringList(item.evidence),
    ...stringList(item.evidence_quotes),
    ...stringList(item.quotes),
  ];
  for (const span of recordArray(item.evidence_spans)) {
    const quote = stringValue(span.quote) || stringValue(span.text);
    if (quote) quotes.push(quote);
  }
  return Array.from(new Set(quotes));
}

function formatCountValue(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "—";
}

function formatDimensionNames(value: unknown): string {
  const dimensions = stringList(value);
  return dimensions.length > 0 ? dimensions.join(", ") : "—";
}

function formatResumeProjects(value: unknown): string {
  const projects = recordArray(value);
  if (projects.length === 0) return "—";
  return projects
    .slice(0, 5)
    .map((project) => {
      const name = stringValue(project.name);
      const role = stringValue(project.role);
      const techStack = stringList(project.tech_stack).slice(0, 4).join(", ");
      return [name, role, techStack].filter(Boolean).join(" · ");
    })
    .filter(Boolean)
    .join("；") || "—";
}

function formatResumeFocusAreas(value: unknown): string {
  const focusAreas = recordArray(value);
  if (focusAreas.length === 0) return "—";
  return focusAreas
    .slice(0, 6)
    .map((focus) => {
      const label = stringValue(focus.label);
      const dimensions = stringList(focus.dimensions).slice(0, 3).join(", ");
      const skills = stringList(focus.skills).slice(0, 3).join(", ");
      return [label, dimensions, skills].filter(Boolean).join(" · ");
    })
    .filter(Boolean)
    .join("；") || "—";
}

function formatResumeAnchors(value: unknown): string {
  const anchors = recordArray(value);
  if (anchors.length === 0) return "—";
  return anchors
    .slice(0, 6)
    .map((anchor) => {
      const label = stringValue(anchor.label);
      const project = stringValue(anchor.project_name);
      const skills = stringList(anchor.skills).slice(0, 3).join(", ");
      const dimensions = stringList(anchor.dimensions).slice(0, 3).join(", ");
      return [label, project, skills, dimensions].filter(Boolean).join(" · ");
    })
    .filter(Boolean)
    .join("；") || "—";
}

function formatSkillSignals(candidateSkillsValue: unknown, requiredSkillsValue: unknown): string {
  const candidateSkills = stringList(candidateSkillsValue);
  const requiredSkills = stringList(requiredSkillsValue);
  if (candidateSkills.length === 0 || requiredSkills.length === 0) return "—";
  const candidateByLower = new Map(
    candidateSkills.map((skill) => [skill.toLowerCase(), skill]),
  );
  const matched = requiredSkills
    .map((skill) => candidateByLower.get(skill.toLowerCase()))
    .filter((skill): skill is string => Boolean(skill));
  return matched.length > 0 ? matched.join(", ") : "暂无交集";
}

function formatDimensionStatusSummary(value: unknown): string {
  const summary = recordFromUnknown(value);
  if (!Object.keys(summary).length) return "—";
  return [
    `总 ${formatCountValue(summary.total)}`,
    `待覆盖 ${formatCountValue(summary.pending)}`,
    `进行中 ${formatCountValue(summary.active)}`,
    `已通过 ${formatCountValue(summary.passed)}`,
    `未通过 ${formatCountValue(summary.failed)}`,
    `其它 ${formatCountValue(summary.other)}`,
  ].join(" · ");
}

function formatScoreInitSummary(value: unknown): string {
  const summary = recordFromUnknown(value);
  if (!Object.keys(summary).length) return "—";
  return [
    `总 ${formatCountValue(summary.total)}`,
    `已评分 ${formatCountValue(summary.scored)}`,
    `未评分 ${formatCountValue(summary.unscored)}`,
  ].join(" · ");
}

function formatProfileFieldsPresent(value: unknown): string {
  const fields = stringList(value);
  return fields.length > 0 ? fields.join(", ") : "—";
}

function formatProfileSummary(value: unknown): string {
  const summary = recordFromUnknown(value);
  if (!Object.keys(summary).length) return "—";
  return [
    `summary ${formatBooleanValue(summary.has_summary)}`,
    `关注 ${formatCountValue(summary.preferred_focus_count)}`,
    `澄清 ${formatCountValue(summary.clarification_targets_count)}`,
    `结构 ${stringValue(summary.communication_structure) || "—"}`,
    `notes ${formatCountValue(summary.communication_notes_count)}`,
  ].join(" · ");
}

function formatAnchorCardsSummary(value: unknown): string {
  const summary = recordFromUnknown(value);
  if (!Object.keys(summary).length) return "—";
  return [
    `总 ${formatCountValue(summary.total)}`,
    `项目 ${formatCountValue(summary.project)}`,
    `技术 ${formatCountValue(summary.tech)}`,
    `职责 ${formatCountValue(summary.responsibility)}`,
    `难点 ${formatCountValue(summary.difficulty)}`,
    `结果 ${formatCountValue(summary.result)}`,
    `主张 ${formatCountValue(summary.claim)}`,
    `其它 ${formatCountValue(summary.other)}`,
  ].join(" · ");
}

function formatSelfIntroProfileSnapshot(value: unknown): string {
  const snapshot = recordFromUnknown(value);
  if (!Object.keys(snapshot).length) return "—";
  return [
    `项目 ${stringList(snapshot.emphasized_projects).length || "—"}`,
    `技能 ${stringList(snapshot.emphasized_skills).length || "—"}`,
    `关注 ${stringList(snapshot.preferred_focus).length || "—"}`,
    `澄清 ${stringList(snapshot.clarification_targets).length || "—"}`,
  ].join(" · ");
}

function formatSelfIntroAnchorCards(value: unknown): string {
  const cards = recordArray(value);
  if (cards.length === 0) return "—";
  const counts = new Map<string, number>();
  for (const card of cards) {
    const kind = stringValue(card.kind) || "other";
    counts.set(kind, (counts.get(kind) || 0) + 1);
  }
  const parts = [`总 ${cards.length}`];
  for (const [kind, count] of counts.entries()) {
    parts.push(`${selfIntroKindLabel(kind)} ${count}`);
  }
  return parts.join(" · ");
}

function formatSelfIntroAnchorSourceSummary(value: unknown): string {
  const cards = recordArray(value);
  if (cards.length === 0) return "—";
  const sources = new Map<string, number>();
  for (const card of cards) {
    const source = stringValue(card.source) || "unknown";
    sources.set(source, (sources.get(source) || 0) + 1);
  }
  return Array.from(sources.entries())
    .map(([source, count]) => `${selfIntroSourceLabel(source)} ${count}`)
    .join(" · ");
}

function selfIntroKindLabel(value: string): string {
  const labels: Record<string, string> = {
    project: "项目",
    responsibility: "职责",
    tech: "技术",
    difficulty: "难点",
    result: "结果",
    claim: "主张",
    other: "其它",
  };
  return labels[value] || value || "—";
}

function selfIntroSourceLabel(value: string): string {
  const labels: Record<string, string> = {
    llm: "模型抽取",
    fallback: "兜底解析",
    supplement: "补充抽取",
    heuristic: "启发式解析",
    unknown: "未知来源",
  };
  return labels[value] || value || "—";
}

function formatSelfIntroCommunication(value: unknown): string {
  const communication = recordFromUnknown(value);
  if (!Object.keys(communication).length) return "—";
  return [
    `结构 ${stringValue(communication.structure) || "—"}`,
    `澄清 ${formatCountValue(communication.clarification_targets_count)}`,
    `notes ${formatCountValue(communication.notes_count)}`,
  ].join(" · ");
}

function formatSelfIntroDownstreamUsage(value: unknown): string {
  const usage = recordFromUnknown(value);
  if (!Object.keys(usage).length) return "—";
  return [
    `调度 ${formatDimensionNames(usage.anchor_scheduler_signals)}`,
    `技能 ${stringValue(usage.skill_focus_signal) || "—"}`,
    `RAG ${stringValue(usage.rag_source) || "—"}`,
    `节点 ${formatDimensionNames(usage.next_nodes)}`,
  ].join(" · ");
}

function formatScore(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "—";
}

function formatConfidenceValue(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) return value.toFixed(2);
  const raw = stringValue(value);
  if (!raw) return "—";
  const parsed = Number.parseFloat(raw);
  return Number.isFinite(parsed) ? parsed.toFixed(2) : raw;
}

function formatBooleanValue(value: unknown): string {
  if (typeof value !== "boolean") return "—";
  return value ? "是" : "否";
}

function formatVerifierPassState(value: unknown): string {
  if (typeof value !== "boolean") return "—";
  return value ? "通过" : "未通过";
}

function verificationVerdictLabel(value: string): string {
  const labels: Record<string, string> = {
    pass: "pass · 确认",
    partial: "partial · 部分质疑",
    fail: "fail · 未通过",
  };
  return labels[value] || value || "—";
}

function verificationReviewStatus(
  payload: Record<string, unknown>,
  evaluation: Record<string, unknown>,
): string {
  const effect = stringValue(payload.verification_effect);
  if (effect === "not_triggered") return "未触发";
  if (effect === "soft_warning_only") return "低置信保留原判";
  if (effect === "overruled_to_refine") return "已改写";
  if (effect === "no_change") {
    const verdict = stringValue(payload.verdict);
    if (verdict === "pass") return "已确认";
    return "未改写";
  }
  if (payload.triggered === false) return "未触发";
  if (payload.verifier_abstained === true || evaluation.verifier_abstained === true) {
    return "低置信保留原判";
  }
  if (payload.verdict_changed === true) return "已改写";
  if (payload.forced_refine === true || evaluation.verifier_forced_refine === true) {
    return "强制追问";
  }
  const verdict = stringValue(payload.verdict);
  if (verdict === "pass") return "已确认";
  if (verdict === "partial") return "部分质疑";
  if (verdict === "fail") return "复核未通过";
  return "未记录复核";
}

function verificationReviewBadgeVariant(
  status: string,
): "outline" | "success" | "warn" {
  if (status === "已确认") return "success";
  if (status === "未触发" || status === "未记录复核") return "outline";
  return "warn";
}

function verificationEffectValue(
  payload: Record<string, unknown>,
  evaluation: Record<string, unknown>,
  changes: Record<string, unknown>[],
): string {
  const recorded = stringValue(payload.verification_effect);
  if (recorded) return recorded;
  if (payload.triggered === false) return "not_triggered";
  const fields = new Set(changes.map((change) => stringValue(change.field)));
  if (fields.size > 0 && [...fields].every((field) =>
    field === "soft_warnings" || field === "verifier_abstained"
  )) {
    return "soft_warning_only";
  }
  if (changes.length > 0 || payload.verdict_changed === true) {
    if (payload.verifier_abstained === true || evaluation.verifier_abstained === true) {
      return "soft_warning_only";
    }
    return "overruled_to_refine";
  }
  return "no_change";
}

function verificationEffectLabel(effect: string): string {
  const labels: Record<string, string> = {
    not_triggered: "未触发",
    no_change: "未改写",
    soft_warning_only: "低置信保留原判",
    overruled_to_refine: "改写为继续追问",
  };
  return effect ? `${labels[effect] || "未知影响"} · ${effect}` : "—";
}

function verificationRewriteLabel(value: unknown, effect: string): string {
  if (effect === "overruled_to_refine") return "已改写";
  if (effect === "soft_warning_only") return "未改写，仅记录软警告";
  if (effect === "not_triggered" || effect === "no_change") return "否";
  return formatBooleanValue(value);
}

function formatVerificationChangeValue(field: string, value: unknown): string {
  if (field === "passed") return formatVerifierPassState(value);
  if (typeof value === "boolean") return formatBooleanValue(value);
  if (Array.isArray(value)) {
    const values = value.map((item) => String(item ?? "")).filter(Boolean);
    return values.length > 0 ? values.join(", ") : "-";
  }
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function routeDecisionLabel(decision: string): string {
  const labels: Record<string, string> = {
    refine: "继续追问",
    next_question: "进入下一题",
    end: "结束面试",
  };
  return labels[decision] || decision || "—";
}

function routeDecisionBadgeVariant(
  decision: string,
): "outline" | "success" | "warn" {
  if (decision === "refine") return "warn";
  if (decision === "next_question") return "success";
  return "outline";
}

function routeDecisionNextNode(decision: string): string {
  const nodes: Record<string, string> = {
    refine: "refine_followup",
    next_question: "director_sample",
    end: "final_report",
  };
  return nodes[decision] || "";
}

function routeDecisionReasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    session_cancelled: "会话已取消",
    turn_limit_reached: "轮次达到上限",
    budget_exhausted: "剩余预算耗尽",
    all_dimensions_passed: "所有维度已通过",
    anchor_expansion: "进入候选人锚点扩展",
    evaluator_fallback: "Evaluator fallback，跳过追问",
    coverage_advance: "追问次数已到上限，推进覆盖",
    evaluator_recommended_refine: "Evaluator 建议继续追问",
    dimension_passed: "当前维度已通过",
    default_not_passed_refine: "未通过，默认继续追问",
  };
  if (!reason) return "—";
  return `${labels[reason] || "未识别原因"} · ${reason}`;
}

function routeDecisionEffect(decision: string, nextNode: string): string {
  if (decision === "refine") {
    return "下一步进入 refine_followup；它会把 evaluator 的 recommended_next_plan 转成 pending_plan_template / pending_contract_hints，再回到 director_sample 组织下一轮追问。";
  }
  if (decision === "next_question") {
    return "下一步进入 director_sample，跳过 refine_followup，由 Director 重新选择维度和出题策略。";
  }
  if (decision === "end") {
    return "下一步进入 final_report，停止主面试链路并生成最终报告。";
  }
  return nextNode
    ? `下一步进入 ${nextNode}。`
    : "旧 trace 只记录了部分路由字段，无法确定后续节点。";
}

function formatRouteTurnProgress(formalTurn: unknown, maxTurns: unknown): string {
  const current = formatDiagnosticScalar(formalTurn);
  const max = formatDiagnosticScalar(maxTurns);
  if (!current && !max) return "—";
  return `${current || "?"}/${max || "?"}`;
}

function formatRouteAttemptValue(attempts: unknown, maxRefines: unknown): string {
  const current = formatDiagnosticScalar(attempts);
  const max = formatDiagnosticScalar(maxRefines);
  if (!current && !max) return "—";
  return `${current || "?"}/${max || "?"}`;
}

function formatStringListValue(value: unknown): string {
  const values = stringList(value);
  return values.length > 0 ? values.join(", ") : "—";
}

function commonSessionKeyPrefix(keys: string[]): string {
  if (keys.length === 0) return "";
  const prefixes = keys.map((key) => {
    const trimmed = key.trim();
    const separator = trimmed.indexOf(":");
    return separator > 0 ? trimmed.slice(0, separator + 1) : "";
  });
  const first = prefixes[0];
  if (!first) return "";
  return prefixes.every((prefix) => prefix === first) ? first : "";
}

function stripCommonPrefix(values: string[], prefix: string): string[] {
  if (!prefix) return values;
  return values.map((value) =>
    value.startsWith(prefix) ? value.slice(prefix.length) : value,
  );
}

function formatKeyValueRecord(value: unknown): string {
  const entries = Object.entries(recordFromUnknown(value))
    .map(([key, item]) => {
      const rendered = formatDiagnosticScalar(item);
      return rendered ? `${key}:${rendered}` : key;
    })
    .filter((item) => item.length > 0);
  return entries.length > 0 ? entries.join(" · ") : "—";
}

function formatDiagnosticScalar(value: unknown): string {
  if (typeof value === "number" && Number.isFinite(value)) {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  const list = stringList(value);
  if (list.length > 0) return list.join(",");
  return stringValue(value);
}

function refineHintKeyLabel(key: string): string {
  const labels: Record<string, string> = {
    must_address: "必须处理 must_address",
    missing_must_cover: "缺失覆盖项 missing_must_cover",
    failure_categories: "失败类别 failure_categories",
    probe_intent: "追问意图 probe_intent",
    failure_reason: "失败原因 failure_reason",
    prior_soft_warnings: "历史软警告 prior_soft_warnings",
    recommended_next_plan: "推荐计划 recommended_next_plan",
    recommended_next: "推荐动作 recommended_next",
    dimension: "目标维度 dimension",
  };
  return labels[key] || key;
}

function inferQuestionSelectorMode(
  questionItems: Record<string, unknown>[],
  rag: Record<string, unknown>,
): string {
  if (questionItems.some((item) => item.injected === true)) return "structured_primary";
  if (questionItems.length > 0) return "structured_shadow";
  const ragMode = stringValue(rag.mode);
  return ragMode ? `vector/${ragMode}` : "";
}

function resumeAnchorLabel(
  resumeAnchor: Record<string, unknown>,
  candidateAnchorRag: Record<string, unknown>,
): string {
  return (
    readableAnchorValue(resumeAnchor.label, resumeAnchor.project_name) ||
    firstAnchorTerm(candidateAnchorRag.anchor_terms) ||
    "—"
  );
}

function firstAnchorTerm(value: unknown): string {
  return readableAnchorValue(...stringList(value));
}

function readableAnchorValue(...values: unknown[]): string {
  for (const value of values) {
    const text = stringValue(value);
    if (text && !looksLikeInternalAnchorId(text)) return text;
  }
  return "";
}

function looksLikeInternalAnchorId(value: string): boolean {
  return /^(focus|anchor|project)-[\w-]+$/i.test(value);
}

function candidateAnchorHitProjectLabel(anchorHits: Record<string, unknown>[]): string {
  const projectNames = Array.from(
    new Set(
      anchorHits
        .map((hit) => stringValue(hit.project_name) || stringValue(hit.heading))
        .filter((value) => value.length > 0),
    ),
  );
  if (projectNames.length === 0) return "—";
  if (projectNames.length <= 2) return projectNames.join(", ");
  return `${projectNames.slice(0, 2).join(", ")} 等 ${projectNames.length} 项`;
}

function localizeAnchorExpansionReason(value: unknown): string {
  const reason = stringValue(value);
  const labels: Record<string, string> = {
    first_pass_self_intro_match: "自我介绍优先匹配（首次使用）",
    first_pass_dimension_match: "维度匹配（首次使用）",
    first_pass_any_anchor: "可用锚点（首次使用）",
    high_value_second_pass: "高价值锚点（二次追问）",
    self_intro_fallback: "自我介绍兜底锚点",
    project_fallback: "项目兜底锚点",
    none: "无",
  };
  return labels[reason] || reason || "—";
}

function formatCandidateAnchorFallbackReason(value: unknown): string {
  const reason = stringValue(value);
  if (!reason) return "—";
  const labels: Record<string, string> = {
    timeout: "embedding or retrieval timeout",
    query_embedding_timeout: "query embedding timeout",
    no_bound_chunks: "no session anchor chunks",
    session_anchor_bind_missing: "cache hit but session chunks missing",
    embedding_model_version_missing: "embedding model version missing",
    not_ready: "anchor material not ready",
    low_score: "below score threshold",
    empty: "empty retrieval result",
    skipped: "retrieval skipped",
    sampled_out: "sampled out",
    error: "retrieval error",
  };
  const label = labels[reason];
  return label ? `${reason} (${label})` : reason;
}

function strategyMemoryTraceKey(strategy: Record<string, unknown>): string {
  return (
    stringValue(strategy.memory_key) ||
    stringValue(strategy.id) ||
    stringValue(strategy.slug)
  );
}

function localizeStrategyMemoryName(strategy: Record<string, unknown>): string {
  const displayName = stringValue(strategy.display_name_zh);
  if (displayName) return displayName;
  const key = strategyMemoryTraceKey(strategy);
  const name = stringValue(strategy.name);
  const labels: Record<string, string> = {
    feedback_followup_timing: "追问时机",
    "seed:feedback_followup_timing": "追问时机",
    pattern_evasive_answers: "回避型回答模式",
    "seed:pattern_evasive_answers": "回避型回答模式",
    "Follow-up Timing": "追问时机",
    "Evasive Answer Patterns": "回避型回答模式",
  };
  return labels[key] || labels[name] || name || key || "未命名策略";
}

function strategyMemoryDescription(strategy: Record<string, unknown>): string {
  return (
    stringValue(strategy.display_description_zh) || stringValue(strategy.description)
  );
}

function localizeAskPlanStepTitle(
  step: Record<string, unknown>,
  index: number,
): string {
  const kind = stringValue(step.kind);
  const labels: Record<string, string> = {
    retrieve_rag: "检索通用知识库",
    retrieve_strategy: "检索策略记忆",
    retrieve_skills: "检索能力卡片",
    retrieve_candidate_anchors: "检索候选人证据",
    draft_question: "生成问题与契约草案",
    negotiate_contract: "预审评分契约",
    challenge_with_reference: "添加参考挑战场景",
    guardrail_check: "安全合规检查",
  };
  return labels[kind] || stringValue(step.goal) || `执行步骤 ${index + 1}`;
}

function localizeAskPlanSuccessCriteria(
  step: Record<string, unknown>,
): string {
  const kind = stringValue(step.kind);
  const labels: Record<string, string> = {
    retrieve_rag: "已写入 retrieval_block，或明确记录空结果。",
    retrieve_strategy: "已写入 strategy_block，包括未命中占位。",
    retrieve_skills: "已写入 skill_block，包括未命中占位。",
    retrieve_candidate_anchors: "已记录候选人锚点 RAG 状态与可注入资料。",
    draft_question: "已生成 question_payload 和 proposed_contract。",
    negotiate_contract: "已得到 contract；是否由 evaluator 签署由评分契约诊断说明。",
    challenge_with_reference: "已添加 challenge_context，或按可选步骤跳过。",
    guardrail_check: "问题通过安全检查，或已应用 fallback。",
  };
  return labels[kind] || stringValue(step.success_criteria);
}

function contractDiagnosticWarningLabel(code: string): string {
  const labels: Record<string, string> = {
    not_evaluator_signed: "未由 evaluator 签署",
    empty_must_cover: "覆盖要求为空",
    empty_acceptance_checks: "验收检查为空",
    must_cover_without_acceptance_check: "覆盖要求缺少验收检查",
    bar_level_mismatch: "评分门槛与目标难度不一致",
    generic_contract_item: "存在过泛契约项",
    rewrite_fallback: "改写后使用 fallback 契约",
  };
  return `${labels[code] || "未知诊断"} · ${code}`;
}

function statusLabelForArtifact({
  enabled,
  empty,
  injected,
  shadow,
  error,
}: {
  enabled: boolean;
  empty?: boolean;
  injected?: boolean;
  shadow?: boolean;
  error?: unknown;
}): string {
  // 异常状态只显示轻量 warning，不阻断详情页。
  if (error) return "轻量 warning";
  if (!enabled) return "关闭";
  if (injected) return "已注入";
  if (shadow) return "仅观测";
  if (empty) return "未命中";
  return "已注入";
}

function StructuredQuestionCandidate({
  item,
}: {
  item: Record<string, unknown>;
}) {
  const matchReasons = stringList(item.match_reasons);
  const summaryReasons = summarizeQuestionMatchReasons(matchReasons);
  const rewardShadowChanged = item.reward_shadow_rank_changed === true;
  return (
    <EvidenceRow>
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline" className="font-mono text-[10px]">
            rank {formatCountValue(item.rank)}
          </Badge>
          {item.reward_shadow_rank !== null && item.reward_shadow_rank !== undefined && (
            <Badge variant="outline" className="font-mono text-[10px]">
              reward_shadow_rank {formatCountValue(item.reward_shadow_rank)}
            </Badge>
          )}
          {rewardShadowChanged && (
            <Badge variant="warn" className="text-[10px]">
              reward_shadow 会改变 Top K
            </Badge>
          )}
          <Badge
            variant="outline"
            className={
              item.injected === true
                ? "border-sky-400/45 bg-sky-500/20 text-sky-100 shadow-[0_0_0_1px_rgba(56,189,248,0.12)] text-[10px]"
                : "text-[10px]"
            }
          >
            {item.injected === true ? "已注入" : "仅观测"}
          </Badge>
        </div>
        <p className="break-words font-medium">
          {stringValue(item.title) || "未命名题库候选"}
        </p>
        <div className="grid gap-2 md:grid-cols-2">
          <NodeFact
            label="Seed 主题"
            value={stringValue(item.seed_id) || "—"}
          />
          <NodeFact
            label="Variant 问法"
            value={stringValue(item.variant_id) || "—"}
          />
        </div>
        {summaryReasons.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-muted-foreground">关键匹配项</span>
            {summaryReasons.map((reason, idx) => (
              <Badge
                key={`${reason}-${idx}`}
                variant="outline"
                className="max-w-full break-words font-mono text-[10px]"
              >
                {reason}
              </Badge>
            ))}
            {matchReasons.length > summaryReasons.length && (
              <span className="text-[11px] text-muted-foreground">
                +{matchReasons.length - summaryReasons.length}
              </span>
            )}
          </div>
        )}
        <QuestionMatchReasonsDetails reasons={matchReasons} />
        <QuestionRewardShadowDetails item={item} />
      </div>
      <Badge variant="outline" className="shrink-0 font-mono text-[10px]">
        match {formatScore(item.match_score)}
      </Badge>
    </EvidenceRow>
  );
}

function QuestionRewardShadowDetails({ item }: { item: Record<string, unknown> }) {
  const usageStats = recordFromUnknown(item.usage_stats);
  const rewardShadowReason = recordFromUnknown(item.reward_shadow_reason);
  const hasShadow =
    item.reward_shadow_rank !== undefined ||
    item.reward_shadow_score !== undefined ||
    Object.keys(usageStats).length > 0 ||
    Object.keys(rewardShadowReason).length > 0;
  if (!hasShadow) return null;

  return (
    <details className="rounded-md border border-dashed bg-background/45 p-2 text-[11px]">
      <summary className="cursor-pointer select-none font-medium text-muted-foreground">
        展开 <span className="font-mono">reward_shadow_reason</span>
      </summary>
      <p className="mt-2 text-muted-foreground">
        仅观测，不影响当前注入题。
      </p>
      <div className="mt-2 grid gap-2 md:grid-cols-2">
        <NodeFact
          label="当前 rank"
          value={formatCountValue(item.rank)}
        />
        <NodeFact
          label="Shadow 排名 reward_shadow_rank"
          value={formatCountValue(item.reward_shadow_rank)}
        />
        <NodeFact
          label="Shadow 分数 reward_shadow_score"
          value={formatScore(item.reward_shadow_score)}
        />
        <NodeFact
          label="历史使用次数"
          value={formatCountValue(usageStats.uses)}
        />
        <NodeFact
          label="有评分样本数"
          value={formatCountValue(usageStats.rewarded_uses)}
        />
        <NodeFact
          label="平均 reward"
          value={formatScore(usageStats.avg_immediate_reward)}
        />
        <NodeFact
          label="通过率"
          value={formatRatioValue(usageStats.pass_rate)}
        />
      </div>
      {Object.keys(rewardShadowReason).length > 0 && (
        <ul className="mt-2 space-y-1">
          {Object.entries(rewardShadowReason).map(([key, value]) => (
            <li key={key} className="break-words">
              <span className="text-muted-foreground">
                {localizeQuestionRewardShadowReasonKey(key)}{" "}
              </span>
              <span className="font-mono text-muted-foreground">{key}</span>
              <span className="text-muted-foreground">: </span>
              <span className="font-mono">
                {formatQuestionRewardShadowValue(value)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

function localizeQuestionRewardShadowReasonKey(key: string): string {
  const labels: Record<string, string> = {
    status: "状态",
    uses: "历史使用次数",
    injected_uses: "实际注入次数",
    rewarded_uses: "有评分样本数",
    avg_immediate_reward: "平均 reward",
    pass_rate: "通过率",
    sample_confidence: "样本置信度",
    metadata_rank: "metadata rank",
    metadata_score: "metadata score",
  };
  return labels[key] || key;
}

function formatQuestionRewardShadowValue(value: unknown): string {
  if (Array.isArray(value)) return value.map((item) => String(item)).join(", ");
  if (typeof value === "number" && Number.isFinite(value)) return value.toFixed(2);
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value ?? "—");
}

function formatRatioValue(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

function summarizeQuestionMatchReasons(reasons: string[]): string[] {
  const grouped = groupQuestionMatchReasons(reasons);
  const priority = grouped.priority?.[0];
  const difficulty = grouped.difficulty?.[0];
  const directionTags = grouped.direction_tag ?? [];
  const roleTags = grouped.role_tag ?? [];
  return [
    priority ? `优先级 ${priority}` : "",
    difficulty ? `难度 ${difficulty}` : "",
    formatGroupedQuestionReason("锚点关键词命中", grouped.resume_anchor),
    formatGroupedQuestionReason("候选人项目适配", grouped.candidate_project_fit),
    formatGroupedQuestionReason("岗位技能匹配", grouped.job_skill_fit),
    formatGroupedQuestionReason("方向标签", directionTags.slice(0, 2)),
    formatGroupedQuestionReason("角色标签", roleTags.slice(0, 2)),
  ].filter((reason) => reason.length > 0);
}

function groupQuestionMatchReasons(reasons: string[]): Record<string, string[]> {
  const grouped: Record<string, string[]> = {};
  for (const reason of reasons) {
    const separator = reason.indexOf(":");
    const key = separator >= 0 ? reason.slice(0, separator) : reason;
    const value = separator >= 0 ? reason.slice(separator + 1) : "";
    if (!key || !value) continue;
    grouped[key] = grouped[key] ?? [];
    if (!grouped[key].includes(value)) grouped[key].push(value);
  }
  return grouped;
}

function formatGroupedQuestionReason(label: string, values?: string[]): string {
  const normalized = (values ?? []).filter((value) => value.length > 0);
  if (!normalized.length) return "";
  return `${label} ${normalized.join(", ")}`;
}

function QuestionMatchReasonsDetails({ reasons }: { reasons: string[] }) {
  if (reasons.length === 0) return null;
  return (
    <details className="rounded-md border bg-background/45 p-2 text-[11px]">
      <summary className="cursor-pointer select-none font-medium text-muted-foreground">
        展开 <span className="font-mono">match_reasons</span>
      </summary>
      <ul className="mt-2 space-y-1">
        {reasons.map((reason, idx) => (
          <li key={`${reason}-${idx}`} className="break-words">
            <span className="text-muted-foreground">命中原因：</span>
            {localizeQuestionMatchReason(reason)}
            <span className="ml-1 font-mono text-muted-foreground">
              {reason}
            </span>
          </li>
        ))}
      </ul>
    </details>
  );
}

function localizeQuestionMatchReason(reason: string): string {
  const separator = reason.indexOf(":");
  const kind = separator >= 0 ? reason.slice(0, separator) : reason;
  const value = separator >= 0 ? reason.slice(separator + 1) : "";
  const labels: Record<string, string> = {
    priority: "优先级",
    direction_tag: "方向标签",
    role_tag: "角色标签",
    resume_anchor: "锚点关键词命中",
    difficulty: "难度",
    candidate_project_fit: "候选人项目适配",
    job_skill_fit: "岗位技能匹配",
    intent: "问法意图",
    probe_intent: "问题意图",
  };
  const label = labels[kind];
  if (!label) return reason;
  return value ? `${label} ${value}` : label;
}

// Phase A observability of the evaluator skill-injection roadmap.
// ``ask_question`` records ``selection_artifacts.skills`` in its trace
// payload; this panel surfaces every hit with a clear "evaluator could
// see this" indicator, so reviewers can audit which skill rubric hints
// would land on the Evaluator side once shadow injection (Phase B)
// flips on. Cards without ``evaluator_visibility: true`` render only
// the generator-side fields and clearly mark themselves as
// generator-only.
function SkillSelectionPanel({ payload }: { payload?: Record<string, unknown> | null }) {
  const record = recordFromUnknown(payload);
  const artifacts = recordFromUnknown(record.selection_artifacts);
  const skills = recordFromUnknown(artifacts.skills);
  const enabled = skills.enabled === true;
  const refs = Array.isArray(skills.refs) ? (skills.refs as Record<string, unknown>[]) : [];

  if (!enabled && refs.length === 0) {
    return null;
  }

  const evaluatorVisibleCount = refs.filter(
    (ref) => ref.evaluator_visibility === true,
  ).length;

  return (
    <div className="mt-3 rounded-md border bg-background/60 p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          Skills 命中
        </span>
        <Badge variant="outline" className="text-[10px]">
          {refs.length} 张
        </Badge>
        {enabled ? (
          <Badge variant="secondary" className="text-[10px]">
            injection enabled
          </Badge>
        ) : (
          <Badge variant="warn" className="text-[10px]">
            injection disabled
          </Badge>
        )}
        {evaluatorVisibleCount > 0 && (
          <Badge variant="success" className="text-[10px]">
            evaluator-visible {evaluatorVisibleCount}/{refs.length}
          </Badge>
        )}
      </div>

      {refs.length === 0 ? (
        <p className="mt-2 text-muted-foreground">
          本轮启用 skill 注入但没有匹配的卡片。
        </p>
      ) : (
        <ul className="mt-2 flex flex-col gap-2">
          {refs.map((ref, idx) => (
            <SkillSelectionRef key={`${String(ref.id ?? "")}-${idx}`} ref_={ref} />
          ))}
        </ul>
      )}
    </div>
  );
}

function SkillSelectionRef({ ref_ }: { ref_: Record<string, unknown> }) {
  const id = typeof ref_.id === "string" ? ref_.id : "";
  const rawName = typeof ref_.name === "string" ? ref_.name : "";
  const rawDescription = stringValue(ref_.description);
  const displayName =
    stringValue(ref_.display_name_zh) || rawName || id || "未命名 Skill";
  const displayDescription =
    stringValue(ref_.display_description_zh) || rawDescription;
  const priority = typeof ref_.priority === "number" ? ref_.priority : null;
  const matchScore = typeof ref_.match_score === "number" ? ref_.match_score : null;
  const matchReasons = Array.isArray(ref_.match_reasons)
    ? (ref_.match_reasons as unknown[]).map((r) => String(r))
    : [];
  const dimensions = stringList(ref_.dimensions);
  const jobLevels = stringList(ref_.job_levels);
  const roleTags = stringList(ref_.role_tags);
  const evaluatorVisibility = ref_.evaluator_visibility === true;
  const evaluatorPayload = evaluatorVisibility
    ? recordFromUnknown(ref_.evaluator_payload)
    : null;

  return (
    <li className="rounded-md border bg-card/40 p-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium leading-tight">{displayName}</p>
          {rawName && (
            <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
              name:{rawName}
            </p>
          )}
          {displayDescription && (
            <p className="mt-1 break-words text-[11px] leading-snug text-muted-foreground">
              <span className="font-mono">description</span>: {displayDescription}
            </p>
          )}
          {id && (
            <p className="mt-1 font-mono text-[10px] text-muted-foreground">
              skill_id:{id}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1">
          {priority !== null && (
            <Badge variant="outline" className="text-[10px]">
              优先级 {priority}
            </Badge>
          )}
          {matchScore !== null && (
            <Badge variant="outline" className="text-[10px]">
              匹配分 {matchScore.toFixed(1)}
            </Badge>
          )}
          {evaluatorVisibility ? (
            <Badge variant="outline" className="text-[10px]">
              评分器信号（未注入）
            </Badge>
          ) : (
            <Badge variant="outline" className="text-[10px]">
              仅出题侧
            </Badge>
          )}
        </div>
      </div>

      {(dimensions.length || jobLevels.length || roleTags.length) > 0 && (
        <div className="mt-2 grid grid-cols-3 gap-1 text-[10px] text-muted-foreground">
          <SkillFact label="维度 dim" values={dimensions} />
          <SkillFact label="级别 lvl" values={jobLevels} />
          <SkillFact label="角色 role" values={roleTags} />
        </div>
      )}

      {matchReasons.length > 0 && (
        <SkillMatchReasonsDetails reasons={matchReasons} />
      )}
      <SkillRewardShadowDetails item={ref_} />

      {evaluatorPayload && (
        <details className="mt-2 rounded border bg-background/40 p-2 text-[11px]">
          <summary className="cursor-pointer select-none text-muted-foreground">
            展开评分器信号 <span className="font-mono">evaluator_payload</span>
          </summary>
          <div className="mt-2 flex flex-col gap-1.5">
            <SkillPayloadList
              label="评分提示 rubric_hints"
              values={stringList(evaluatorPayload.rubric_hints)}
            />
            <SkillPayloadList
              label="正向信号 positive_signals"
              values={stringList(evaluatorPayload.positive_signals)}
            />
            <SkillPayloadList
              label="负向信号 negative_signals"
              values={stringList(evaluatorPayload.negative_signals)}
            />
            <SkillPayloadList
              label="评分偏置 score_bias_rules"
              values={stringList(evaluatorPayload.score_bias_rules)}
            />
          </div>
        </details>
      )}
    </li>
  );
}

function SkillRewardShadowDetails({ item }: { item: Record<string, unknown> }) {
  const usageStats = recordFromUnknown(item.usage_stats);
  const rewardShadowReason = recordFromUnknown(item.reward_shadow_reason);
  const hasShadow =
    item.reward_shadow_rank !== undefined ||
    item.reward_shadow_score !== undefined ||
    Object.keys(usageStats).length > 0 ||
    Object.keys(rewardShadowReason).length > 0;
  if (!hasShadow) return null;

  return (
    <details className="mt-2 rounded border border-dashed bg-background/40 p-2 text-[11px]">
      <summary className="cursor-pointer select-none text-muted-foreground">
        展开 <span className="font-mono">reward_shadow_reason</span>
      </summary>
      <p className="mt-2 text-muted-foreground">
        仅观测，不影响当前 Skills 注入顺序。
      </p>
      <div className="mt-2 grid gap-2 md:grid-cols-2">
        <NodeFact label="当前 rank" value={formatCountValue(item.rank)} />
        <NodeFact
          label="Shadow 排名 reward_shadow_rank"
          value={formatCountValue(item.reward_shadow_rank)}
        />
        <NodeFact
          label="Shadow 分数 reward_shadow_score"
          value={formatScore(item.reward_shadow_score)}
        />
        <NodeFact
          label="历史使用次数"
          value={formatCountValue(usageStats.uses)}
        />
        <NodeFact
          label="有评分样本数"
          value={formatCountValue(usageStats.rewarded_uses)}
        />
        <NodeFact
          label="平均 reward avg_blended_reward"
          value={formatScore(
            usageStats.avg_blended_reward ?? usageStats.avg_immediate_reward,
          )}
        />
        <NodeFact
          label="通过率"
          value={formatRatioValue(usageStats.pass_rate)}
        />
        <NodeFact
          label="复核否决率 overrule_rate"
          value={formatRatioValue(usageStats.overrule_rate)}
        />
      </div>
      {Object.keys(rewardShadowReason).length > 0 && (
        <ul className="mt-2 space-y-1">
          {Object.entries(rewardShadowReason).map(([key, value]) => (
            <li key={key} className="break-words">
              <span className="text-muted-foreground">
                {localizeSkillRewardShadowReasonKey(key)}{" "}
              </span>
              <span className="font-mono text-muted-foreground">{key}</span>
              <span className="text-muted-foreground">: </span>
              <span className="font-mono">
                {formatQuestionRewardShadowValue(value)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </details>
  );
}

function localizeSkillRewardShadowReasonKey(key: string): string {
  const labels: Record<string, string> = {
    status: "状态",
    skill_context_key: "上下文 key",
    uses: "历史使用次数",
    injected_uses: "实际注入次数",
    rewarded_uses: "有评分样本数",
    avg_blended_reward: "平均 reward",
    avg_immediate_reward: "即时 reward",
    pass_rate: "通过率",
    overrule_rate: "复核否决率",
    sample_confidence: "样本置信度",
    sample_status: "样本状态",
    metadata_rank: "metadata rank",
    metadata_score: "metadata score",
    shadow_rank: "shadow rank",
    reward_shadow_score: "shadow 分数",
  };
  return labels[key] || key;
}

function SkillMatchReasonsDetails({ reasons }: { reasons: string[] }) {
  if (reasons.length === 0) return null;
  return (
    <details className="mt-2 rounded border bg-background/40 p-2 text-[11px]">
      <summary className="cursor-pointer select-none text-muted-foreground">
        展开 <span className="font-mono">match_reasons</span>
      </summary>
      <ul className="mt-2 space-y-1">
        {reasons.map((reason, idx) => (
          <li key={`${reason}-${idx}`} className="break-words">
            <span className="text-muted-foreground">命中原因：</span>
            {localizeSkillMatchReason(reason)}
          </li>
        ))}
      </ul>
    </details>
  );
}

function SkillFact({ label, values }: { label: string; values: string[] }) {
  return (
    <div>
      <span className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <p className="mt-0.5 break-words font-mono">{values.length ? values.join(", ") : "—"}</p>
    </div>
  );
}

function localizeSkillMatchReason(reason: string): string {
  const [kind] = reason.split(":");
  const labels: Record<string, string> = {
    priority: "优先级",
    dimension: "维度",
    job_level: "岗位级别",
    direction_tag: "方向标签",
    role_tag: "角色标签",
    probe_intent: "问题意图",
    failure_category: "失败类别",
  };
  const label = labels[kind];
  if (!label) return reason;
  return `${label} ${reason}`;
}

function SkillPayloadList({ label, values }: { label: string; values: string[] }) {
  if (!values.length) return null;
  return (
    <div>
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <ul className="mt-0.5 list-disc space-y-0.5 pl-4 text-[11px]">
        {values.map((value, idx) => (
          <li key={idx}>{value}</li>
        ))}
      </ul>
    </div>
  );
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item ?? "")).filter((item) => item.length > 0);
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function parseOptionalInt(value: string | null): number | null {
  if (!value) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function countNodeTypes(nodes: TraceExplorerNode[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const node of nodes) {
    const canonical = traceNodeCanonicalName(node.node);
    counts[canonical] = (counts[canonical] || 0) + 1;
  }
  return counts;
}

function countTurns(nodes: TraceExplorerNode[]): number {
  return new Set(nodes.map((node) => node.turn_idx ?? "session")).size;
}

function nodeMatchesQuery(node: TraceExplorerNode, query: string): boolean {
  const evaluation = recordFromUnknown(node.evaluation);
  const fields = [
    node.node,
    traceNodeCanonicalName(node.node),
    traceNodeDisplayName(node.node, node.payload),
    node.dimension,
    node.action_id,
    node.policy_id,
    node.context_key,
    node.question,
    node.answer_excerpt,
    ...stringList(node.policy_context_keys),
    ...stringList(evaluation.strengths),
    ...stringList(evaluation.weaknesses),
    stringValue(evaluation.rationale),
    stringValue(evaluation.feedback),
    ...askQuestionSearchFields(node.payload),
    ...verificationChangeSearchFields(node.payload),
    ...evaluatorScoringSearchFields(node.payload, evaluation),
    ...routeDecisionSearchFields(node.payload),
    ...turnFinalizeSearchFields(node.payload),
    ...successorNodeSearchFields(node.payload),
    ...actionGuardrailSearchFields(node.payload),
    ...rewardUpdateSearchFields(node.payload),
    ...experienceExtractorSearchFields(node.payload),
  ];
  return fields.some((field) => String(field ?? "").toLowerCase().includes(query));
}

function verificationChangeSearchFields(
  payload?: Record<string, unknown> | null,
): string[] {
  const record = recordFromUnknown(payload);
  const fields: string[] = [];
  const add = (value: unknown) => {
    if (typeof value === "string" && value.trim()) fields.push(value);
    else if (typeof value === "number" || typeof value === "boolean") {
      fields.push(formatDiagnosticScalar(value));
    }
  };

  add(record.verification_effect);
  for (const change of recordArray(record.verification_changes)) {
    add(change.field);
    add(change.label);
    add(change.reason);
    add(formatVerificationChangeValue(stringValue(change.field), change.before));
    add(formatVerificationChangeValue(stringValue(change.field), change.after));
  }
  return fields;
}

function addAcceptanceCheckItemSearchFields(
  fields: string[],
  item: Record<string, unknown>,
) {
  const add = (value: unknown) => {
    if (typeof value === "string" && value.trim()) fields.push(value);
    else if (typeof value === "number" || typeof value === "boolean") {
      fields.push(formatDiagnosticScalar(value));
    }
  };

  add(item.text);
  add(item.acceptance_check);
  add(item.source);
  add(item.severity);
  add(item.check_id);
  add(item.source_text);
  add(item.origin);
  add(item.verdict);
  add(item.result_present);
  for (const quote of acceptanceEvidenceQuotes(item)) add(quote);
  const seedRef = recordFromUnknown(item.seed_ref);
  add(seedRef.seed_id);
  add(seedRef.variant_id);
}

function addContractGateResultSearchFields(
  fields: string[],
  resultValue: unknown,
) {
  const result = recordFromUnknown(resultValue);
  if (Object.keys(result).length === 0) return;
  const add = (value: unknown) => {
    if (typeof value === "string" && value.trim()) fields.push(value);
    else if (typeof value === "number" || typeof value === "boolean") {
      fields.push(formatDiagnosticScalar(value));
    }
  };

  add(result.gate_id);
  add(result.mode);
  add(result.status);
  add(result.would_pass);
  for (const warning of stringList(result.warnings)) add(warning);
  add(result.eligible_count);
  add(result.satisfied_count);
  add(result.failed_count);
  add(result.partial_count);
  add(result.no_count);
  add(result.missing_count);
  const scope = recordFromUnknown(result.scope);
  for (const source of stringList(scope.sources)) add(source);
  for (const severity of stringList(scope.severities)) add(severity);
  add(scope.partial_policy);
  for (const item of recordArray(result.failed_items)) {
    addAcceptanceCheckItemSearchFields(fields, item);
    add(item.reason);
    add(item.evidence_count);
  }
}

function evaluatorScoringSearchFields(
  payload?: Record<string, unknown> | null,
  evaluation?: Record<string, unknown> | null,
): string[] {
  const fields: string[] = [];
  const add = (value: unknown) => {
    if (typeof value === "string" && value.trim()) fields.push(value);
    else if (typeof value === "number" || typeof value === "boolean") {
      fields.push(formatDiagnosticScalar(value));
    }
  };
  const addList = (value: unknown) => {
    for (const item of stringList(value)) fields.push(item);
  };
  const addRecord = (value: unknown) => {
    for (const [key, item] of Object.entries(recordFromUnknown(value))) {
      add(key);
      add(formatDiagnosticScalar(item));
      const record = recordFromUnknown(item);
      add(record.verdict);
      add(record.status);
      addList(record.evidence);
      addList(record.evidence_quotes);
      for (const span of recordArray(record.evidence_spans)) {
        add(span.quote);
        add(span.text);
      }
    }
  };

  for (const record of [
    recordFromUnknown(payload),
    recordFromUnknown(evaluation),
  ]) {
    add(record.contract_source);
    add(record.contract_bar_level);
    addList(record.signed_by);
    addList(record.rubric_points);
    addRecord(record.rubric_coverage);
    addRecord(record.acceptance_check_results);
    for (const item of recordArray(record.acceptance_check_result_items)) {
      addAcceptanceCheckItemSearchFields(fields, item);
    }
    addContractGateResultSearchFields(fields, record.contract_gate_result);
    add(record.recommended_next);
    add(record.recommended_next_plan);
    add(record.recommended_probe_intent);
    add(record.failure_reason);
    add(record.contract_gate_enforced);
    add(record.contract_gate_enforcement_reason);
    add(record.contract_gate_failed_count);
    addList(record.contract_gate_failed_check_ids);
    addList(record.failure_categories);
    const contract = recordFromUnknown(record.contract);
    addList(contract.must_cover);
    addList(contract.acceptance_checks);
    for (const item of recordArray(contract.acceptance_check_items)) {
      addAcceptanceCheckItemSearchFields(fields, item);
    }
    add(contract.minimum_bar);
    addList(contract.review_focus);
  }
  return fields;
}

function routeDecisionSearchFields(
  payload?: Record<string, unknown> | null,
): string[] {
  const record = recordFromUnknown(payload);
  const inputs = recordFromUnknown(record.decision_inputs);
  const fields: string[] = [];
  const add = (value: unknown) => {
    if (typeof value === "string" && value.trim()) fields.push(value);
  };

  add(record.router);
  add(record.decision);
  add(record.next_node);
  add(record.decision_reason);
  add(record.dimension);
  add(record.recommended_next);
  add(record.recommended_next_plan);
  add(record.recommended_probe_intent);
  add(record.evaluation_source);
  add(record.fallback_reason);

  for (const [key, value] of Object.entries(inputs)) {
    add(key);
    add(formatDiagnosticScalar(value));
  }

  return fields;
}

function turnFinalizeSearchFields(
  payload?: Record<string, unknown> | null,
): string[] {
  const record = recordFromUnknown(payload);
  const fields: string[] = ["轮次收尾", "turn_finalize", "compress_context"];
  const add = (value: unknown) => {
    if (typeof value === "string" && value.trim()) fields.push(value);
    else if (typeof value === "number" || typeof value === "boolean") {
      fields.push(formatDiagnosticScalar(value));
    }
  };

  add(record.phase);
  add(record.reason);
  add(record.workflow_node);
  add(record.semantic_node);
  add(record.display_name_zh);
  for (const alias of stringList(record.node_aliases)) fields.push(alias);
  add(record.raw_answer_cleared);
  add(record.cleared_raw_answer);
  add(record.summary_updated);
  add(record.summary_mode);
  add(record.history_projection_owner);
  add(record.compressed_turns);
  add(record.qa_history_count);
  add(record.recent_turns_kept);
  add(record.summary_through_turn);
  add(record.next_step);

  return fields;
}

function successorNodeSearchFields(
  payload?: Record<string, unknown> | null,
): string[] {
  const record = recordFromUnknown(payload);
  const fields: string[] = [];
  const add = (value: unknown) => {
    if (typeof value === "string" && value.trim()) fields.push(value);
    else if (typeof value === "number" || typeof value === "boolean") {
      fields.push(formatDiagnosticScalar(value));
    }
  };
  const addList = (value: unknown) => {
    for (const item of stringList(value)) fields.push(item);
  };
  const addRecord = (value: unknown) => {
    for (const [key, item] of Object.entries(recordFromUnknown(value))) {
      add(key);
      add(formatDiagnosticScalar(item));
      addList(item);
    }
  };

  add(record.pending_plan_template);
  add(record.next_template);
  add(record.dimension);
  add(record.probe_intent);
  add(record.failure_reason);
  addList(record.failure_categories);
  addList(record.prior_soft_warnings);
  addRecord(record.pending_contract_hints);

  addRecord(record.selected_action);
  addRecord(record.diagnostics);
  addList(record.policy_context_keys);

  add(record.report_status);
  add(record.final_status);
  add(record.overall_score);
  add(record.conclusion);
  add(record.verdict);
  add(record.summary);
  addList(record.missing_sections);
  add(record.training_plan_queued);
  add(record.experience_extractor_queued);
  add(record.fallback_count);
  add(record.evaluator_turn_count);
  addRecord(record.report_summary);
  addRecord(record.scoring_credibility);
  for (const item of recordArray(record.dimension_results)) addRecord(item);
  for (const item of recordArray(record.dimension_evidence)) addRecord(item);
  addRecord(record.closing_chain);
  addRecord(record.workflow_artifacts);

  add(record.source);
  add(record.fallback_reason);
  addRecord(record.plan_summary);
  addRecord(record.diagnosis);
  for (const item of recordArray(record.priority_weaknesses)) addRecord(item);
  for (const item of recordArray(record.practice_plan)) addRecord(item);
  addRecord(record.goals_30_60_90);

  return fields;
}

function actionGuardrailSearchFields(
  payload?: Record<string, unknown> | null,
): string[] {
  const guardrail = actionGuardrailFromPayload(payload);
  const fields: string[] = [];
  const add = (value: unknown) => {
    if (typeof value === "string" && value.trim()) fields.push(value);
    else if (typeof value === "number" || typeof value === "boolean") {
      fields.push(formatDiagnosticScalar(value));
    }
  };
  const addList = (value: unknown) => {
    for (const item of stringList(value)) fields.push(item);
  };

  add(guardrail.mode);
  add(guardrail.enabled);
  addList(guardrail.original_allowed_actions);
  addList(guardrail.final_allowed_actions);
  for (const reason of stringList(guardrail.reason_codes)) {
    add(reason);
    add(actionGuardrailReasonLabel(reason));
  }
  for (const item of recordArray(guardrail.disabled_actions)) {
    add(item.action_id);
    for (const reason of stringList(item.reason_codes)) {
      add(reason);
      add(actionGuardrailReasonLabel(reason));
    }
  }

  return fields;
}

function rewardUpdateSearchFields(
  payload?: Record<string, unknown> | null,
): string[] {
  const record = recordFromUnknown(payload);
  const fields: string[] = [];
  const add = (value: unknown) => {
    if (typeof value === "string" && value.trim()) fields.push(value);
    else if (typeof value === "number" || typeof value === "boolean") {
      fields.push(formatDiagnosticScalar(value));
    }
  };
  const addList = (value: unknown) => {
    for (const item of stringList(value)) fields.push(item);
  };
  const addRecord = (value: unknown) => {
    for (const [key, item] of Object.entries(recordFromUnknown(value))) {
      add(key);
      add(formatDiagnosticScalar(item));
      addList(item);
      const nested = recordFromUnknown(item);
      add(nested.reason);
      add(nested.variant_id);
      add(nested.seed_id);
      add(nested.target);
      add(nested.error_type);
      add(nested.message);
    }
  };

  add(record.immediate_reward);
  add(record.action_id);
  addList(record.context_keys);

  for (const section of [
    record.reward_summary,
    record.bandit_update,
    record.strategy_memory_attribution,
    record.question_attribution,
    record.skill_attribution,
    record.persistence,
  ]) {
    addRecord(section);
  }

  return fields;
}

function experienceExtractorSearchFields(
  payload?: Record<string, unknown> | null,
): string[] {
  const record = recordFromUnknown(payload);
  const fields: string[] = [];
  const add = (value: unknown) => {
    if (typeof value === "string" && value.trim()) fields.push(value);
    else if (typeof value === "number" || typeof value === "boolean") {
      fields.push(formatDiagnosticScalar(value));
    }
  };
  const addList = (value: unknown) => {
    for (const item of stringList(value)) fields.push(item);
  };

  add(record.reason);
  add(record.qa_source);
  add(record.bandit_source);
  add(record.candidates);
  add(record.saved);
  add(record.skipped_existing);
  add(record.failed);
  add(record.qa_candidates);
  add(record.qa_saved);
  add(record.qa_skipped_existing);
  add(record.qa_failed);
  add(record.bandit_candidates);
  add(record.bandit_saved);
  add(record.bandit_skipped_existing);
  add(record.bandit_failed);
  addList(record.saved_keys);
  addList(record.skipped_keys);
  addList(record.failed_keys);

  return fields;
}

function askQuestionSearchFields(
  payload?: Record<string, unknown> | null,
): string[] {
  const record = recordFromUnknown(payload);
  const artifacts = recordFromUnknown(record.selection_artifacts);
  const fields: string[] = [];
  const add = (value: unknown) => {
    if (typeof value === "string" && value.trim()) fields.push(value);
    else if (typeof value === "number" || typeof value === "boolean") {
      fields.push(formatDiagnosticScalar(value));
    }
  };
  const addList = (value: unknown) => {
    for (const item of stringList(value)) fields.push(item);
  };
  const addRecord = (value: unknown) => {
    for (const [key, item] of Object.entries(recordFromUnknown(value))) {
      add(key);
      add(formatDiagnosticScalar(item));
      addList(item);
      const nested = recordFromUnknown(item);
      for (const [nestedKey, nestedValue] of Object.entries(nested)) {
        add(nestedKey);
        add(formatDiagnosticScalar(nestedValue));
        addList(nestedValue);
      }
    }
  };

  add(record.plan_template);
  add(record.probe_intent);
  add(record.dimension);
  add(record.contract_bar_level);
  addList(record.signed_by);
  addRecord(record.history_context);
  addRecord(record.qa_summary_projection);
  addRecord(record.prompt_budget_diagnostics);
  const promptBudgetDiagnostics = recordFromUnknown(record.prompt_budget_diagnostics);
  for (const slot of recordArray(promptBudgetDiagnostics.protected_slots)) {
    add(slot.prompt_label);
    add(slot.chars);
    add(slot.injected);
  }
  for (const slot of recordArray(record.history_prompt_slots)) {
    add(slot.prompt_label);
    add(slot.source_key);
    add(slot.empty_reason);
    add(slot.runtime_budget_level);
    add(slot.runtime_budget_source);
    add(slot.runtime_global_budget_pressure);
    add(slot.text);
    for (const item of recordArray(slot.runtime_items)) {
      // prompt slot runtime item
      add(item.id);
      add(item.skill_id);
      add(item.name);
      add(item.source_type);
      add(item.project_name);
      add(item.heading);
      add(item.chunk_index);
      add(item.score);
      add(item.field);
      add(item.limit_type);
      add(item.limit);
      add(item.original_count);
      add(item.injected_count);
      add(item.truncation_reason);
    }
  }

  const contract = recordFromUnknown(record.contract);
  addList(contract.must_cover);
  addList(contract.acceptance_checks);
  for (const item of recordArray(contract.acceptance_check_items)) {
    addAcceptanceCheckItemSearchFields(fields, item);
  }
  addList(contract.acceptable_if_missing);
  add(contract.minimum_bar);
  addList(contract.review_focus);
  add(contract.bar_level);
  addList(contract.signed_by);

  const contractDiagnostics = recordFromUnknown(record.contract_diagnostics);
  add(contractDiagnostics.source);
  add(contractDiagnostics.signed_status);
  add(contractDiagnostics.bar_level);
  add(contractDiagnostics.expected_bar_level);
  addList(contractDiagnostics.uncovered_must_cover_items);
  addList(contractDiagnostics.generic_items);
  addList(contractDiagnostics.warnings);

  const askPlan = recordFromUnknown(record.ask_plan);
  add(askPlan.plan_id);
  add(askPlan.template);
  add(askPlan.complexity);
  add(askPlan.source);
  const resolutionInputs = recordFromUnknown(askPlan.resolution_inputs);
  add(resolutionInputs.selected_action_id);
  add(resolutionInputs.selected_action_label);
  add(resolutionInputs.selected_action_plan_template);
  add(resolutionInputs.pending_plan_template);
  add(resolutionInputs.ask_planning);
  for (const step of recordArray(askPlan.steps)) {
    // ask plan step
    add(step.step_id);
    add(step.kind);
    add(step.goal);
    add(step.success_criteria);
    addList(step.produced_keys);
    addList(step.dependencies);
  }

  for (const slot of recordArray(record.prompt_slots)) {
    // prompt slot
    add(slot.prompt_label);
    add(slot.source_key);
    add(slot.empty_reason);
    add(slot.runtime_budget_level);
    add(slot.runtime_budget_source);
    add(slot.runtime_global_budget_pressure);
    add(slot.text);
    for (const item of recordArray(slot.runtime_items)) {
      // prompt slot runtime item
      add(item.id);
      add(item.skill_id);
      add(item.name);
      add(item.source_type);
      add(item.project_name);
      add(item.heading);
      add(item.chunk_index);
      add(item.score);
      add(item.field);
      add(item.limit_type);
      add(item.limit);
      add(item.original_count);
      add(item.injected_count);
      add(item.truncation_reason);
    }
  }

  for (const ref of recordArray(recordFromUnknown(artifacts.rag).doc_refs)) {
    // rag source
    add(ref.source);
    add(ref.source_type);
    add(ref.chunk);
  }

  for (const item of recordArray(artifacts.question_items)) {
    // question seed_id / variant_id / matched_project / match_reasons
    add(item.seed_id);
    add(item.variant_id);
    add(item.title);
    add(item.intent);
    add(item.difficulty);
    add(item.matched_project);
    addList(item.matched_candidate_skills);
    addList(item.matched_job_skills);
    addList(item.match_reasons);
    add(item.reward_shadow_rank);
    add(item.reward_shadow_score);
    add(item.reward_shadow_rank_changed);
    const usageStats = recordFromUnknown(item.usage_stats);
    add(usageStats.uses);
    add(usageStats.rewarded_uses);
    add(usageStats.avg_immediate_reward);
    add(usageStats.pass_rate);
    const rewardShadowReason = recordFromUnknown(item.reward_shadow_reason);
    add(rewardShadowReason.status);
    add(rewardShadowReason.sample_confidence);
    add(rewardShadowReason.metadata_rank);
    add(rewardShadowReason.metadata_score);
  }

  for (const strategy of recordArray(artifacts.strategies)) {
    // strategy id/name
    add(strategy.id);
    add(strategy.name);
    add(strategy.description);
    add(strategy.display_name_zh);
    add(strategy.display_description_zh);
    add(strategy.memory_key);
    add(strategy.slug);
    add(strategy.source);
    const rankingReason = recordFromUnknown(strategy.ranking_reason);
    add(rankingReason.stats_context_key);
    add(rankingReason.stats_scope);
  }

  const skills = recordFromUnknown(artifacts.skills);
  for (const skill of recordArray(skills.refs)) {
    // skill id/name
    add(skill.id);
    add(skill.name);
    add(skill.description);
    add(skill.display_name_zh);
    add(skill.display_description_zh);
    addList(skill.match_reasons);
    addList(skill.dimensions);
    addList(skill.role_tags);
    add(skill.reward_shadow_rank);
    add(skill.reward_shadow_score);
    add(skill.reward_shadow_rank_changed);
    const skillUsageStats = recordFromUnknown(skill.usage_stats);
    add(skillUsageStats.uses);
    add(skillUsageStats.rewarded_uses);
    add(skillUsageStats.avg_blended_reward);
    add(skillUsageStats.avg_immediate_reward);
    add(skillUsageStats.pass_rate);
    add(skillUsageStats.overrule_rate);
    const skillRewardShadowReason = recordFromUnknown(skill.reward_shadow_reason);
    for (const [key, value] of Object.entries(skillRewardShadowReason)) {
      add(key);
      add(value);
    }
  }

  const candidateAnchor = recordFromUnknown(artifacts.candidate_anchor);
  add(candidateAnchor.matched_project);
  add(candidateAnchor.project_name);
  add(candidateAnchor.prompt_role);
  add(candidateAnchor.target_dimension);
  add(candidateAnchor.turn_intent);
  add(candidateAnchor.seed_binding);
  add(candidateAnchor.project_anchor_source);
  add(candidateAnchor.variant_id);

  const candidateAnchorRag = recordFromUnknown(artifacts.candidate_anchor_rag);
  // candidate anchor RAG diagnostics
  add(candidateAnchorRag.status);
  add(candidateAnchorRag.fallback_reason);
  add(candidateAnchorRag.boost_fallback_reason);
  const bindValidation = recordFromUnknown(candidateAnchorRag.bind_validation);
  add("bind_validation");
  add(bindValidation.fallback_reason);
  add(bindValidation.resume_revision_id);
  add(bindValidation.self_intro_revision_id);
  add(bindValidation.embedding_model_version);
  add(bindValidation.source_cache_key);
  add(bindValidation.bound_count);
  add(bindValidation.resume_bound_count);
  add(bindValidation.self_intro_bound_count);
  add(bindValidation.rebind_attempted);
  add(bindValidation.rebind_success);
  addList(candidateAnchorRag.prompt_block_sources);
  addList(candidateAnchorRag.anchor_terms);
  addList(candidateAnchorRag.boost_terms);
  addList(candidateAnchorRag.constraint_terms);
  addRecord(candidateAnchorRag.fetched_rows_by_source);
  addRecord(candidateAnchorRag.scored_rows_by_source);
  addRecord(candidateAnchorRag.kept_hits_by_source);
  add(candidateAnchorRag.query_text);
  add(candidateAnchorRag.anchor_query_text);
  add(candidateAnchorRag.boost_query_text);
  add(candidateAnchorRag.constraint_query_text);
  for (const key of Object.keys(recordFromUnknown(candidateAnchorRag.ranking_weights))) {
    add(key);
  }
  for (const hit of recordArray(candidateAnchorRag.hits)) {
    add(hit.source);
    add(hit.source_type);
    add(hit.project_name);
    add(hit.heading);
    add(hit.excerpt);
    add(hit.anchor_key);
    add(hit.dedupe_reason);
    addList(hit.matched_target_skills);
    addList(hit.matched_dimensions);
    addList(hit.matched_seed_terms);
  }

  const anchorScheduler = recordFromUnknown(artifacts.anchor_scheduler);
  add(anchorScheduler.anchor_key);
  add(anchorScheduler.expansion_reason);

  return fields;
}

function usePrefersReducedMotion(): boolean {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    setPrefersReducedMotion(media.matches);
    const onChange = () => setPrefersReducedMotion(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  return prefersReducedMotion;
}

type TraceTurnGroupKey = "opening" | number | "session" | "closing";

function isSessionClosingNode(nodeName: string | null | undefined): boolean {
  return SESSION_CLOSING_NODES.has(traceNodeCanonicalName(nodeName));
}

function isSessionOpeningNode(nodeName: string | null | undefined): boolean {
  return OPENING_NODES.has(traceNodeCanonicalName(nodeName));
}

function openingNodeRailSummary(node: TraceExplorerNode): string {
  if (!isSessionOpeningNode(node.node)) return "";
  const payload = recordFromUnknown(node.payload);
  const canonical = traceNodeCanonicalName(node.node);
  if (canonical === "resume_parse") {
    const resumeStatus = recordFromUnknown(payload.resume_vector_status);
    const dimensionStatus = recordFromUnknown(payload.dimension_status_summary);
    const scoreSummary = recordFromUnknown(payload.scores_per_dim_summary);
    const anchorCount = recordArray(payload.resume_anchors).length;
    return `锚点 ${anchorCount || "—"} · 维度 ${formatCountValue(payload.dimensions_count)} · 待覆盖 ${formatCountValue(dimensionStatus.pending)} · 未评分 ${formatCountValue(scoreSummary.unscored)} · 简历向量 ${stringValue(resumeStatus.status) || "—"}`;
  }
  if (canonical === "self_intro_question") {
    return `维度 ${stringValue(payload.dimension) || node.dimension || "—"} · Rubric 点 ${stringList(payload.rubric_points).length}`;
  }
  if (canonical === "self_intro_parse") {
    const selfIntroStatus = recordFromUnknown(payload.self_intro_vector_status);
    const anchorCards = recordFromUnknown(payload.anchor_cards_summary);
    return `解析 ${stringValue(payload.parse_status) || "—"} · 技能 ${formatCountValue(payload.emphasized_skills_count)} · Cards ${formatCountValue(anchorCards.total)} · 自我介绍向量 ${stringValue(selfIntroStatus.status) || "—"}`;
  }
  return "";
}

function isAskRoundStartNode(node: TraceExplorerNode): boolean {
  const canonical = traceNodeCanonicalName(node.node);
  return canonical === "director_sample" || canonical === "ask_question";
}

function shouldGroupRefineFollowupWithNextTurn(
  node: TraceExplorerNode,
  contextNodes: TraceExplorerNode[],
): boolean {
  if (traceNodeCanonicalName(node.node) !== "refine_followup") return false;
  if (typeof node.turn_idx !== "number") return false;
  const turnIdx = node.turn_idx;

  const sameTurnHasQuestionStart = contextNodes.some(
    (candidate) =>
      candidate.id !== node.id &&
      candidate.turn_idx === turnIdx &&
      isAskRoundStartNode(candidate),
  );
  if (sameTurnHasQuestionStart) return false;

  // Old traces can stamp refine_followup with the completed answer turn.
  // Visually group it with the next ask round because it prepares the
  // pending hints consumed by director_sample / ask_question.
  const nextTurnHasQuestionStart = contextNodes.some(
    (candidate) =>
      candidate.turn_idx === turnIdx + 1 &&
      isAskRoundStartNode(candidate),
  );
  return nextTurnHasQuestionStart;
}

function effectiveTraceTurnKey(
  node: TraceExplorerNode,
  contextNodes: TraceExplorerNode[] = [],
): TraceTurnGroupKey {
  if (isSessionOpeningNode(node.node)) return "opening";
  if (isSessionClosingNode(node.node)) return "closing";
  if (shouldGroupRefineFollowupWithNextTurn(node, contextNodes)) {
    return typeof node.turn_idx === "number" ? node.turn_idx + 1 : "session";
  }
  if (isTurnFinalizeNode(node.node) && typeof node.turn_idx === "number") {
    if (node.node === "turn_finalize") return node.turn_idx;
    const payload = recordFromUnknown(node.payload);
    if (payload.phase !== "turn_finalize") return Math.max(0, node.turn_idx - 1);
  }
  return typeof node.turn_idx === "number" ? node.turn_idx : "session";
}

function traceNodeWorkflowOrder(
  node: TraceExplorerNode,
  groupNodes: TraceExplorerNode[] = [],
): number {
  const canonical = traceNodeCanonicalName(node.node);
  if (
    canonical === "refine_followup" &&
    groupNodes.some(
      (candidate) =>
        candidate.id !== node.id &&
        (traceNodeCanonicalName(candidate.node) === "director_sample" ||
          traceNodeCanonicalName(candidate.node) === "ask_question"),
    )
  ) {
    return TRACE_NODE_WORKFLOW_ORDER.indexOf("director_sample") - 0.5;
  }
  const index = TRACE_NODE_WORKFLOW_ORDER.indexOf(canonical);
  return index >= 0 ? index : TRACE_NODE_WORKFLOW_ORDER.length;
}

function traceTurnGroupLabel(key: TraceTurnGroupKey): string {
  if (key === "opening") return "准备/开场阶段";
  if (key === "closing") return "收尾阶段";
  if (key === "session") return "Session-level events";
  return `Turn ${key}`;
}

function traceTurnGroupSortKey(key: TraceTurnGroupKey): number {
  if (key === "opening") return Number.MIN_SAFE_INTEGER;
  if (key === "closing") return Number.MAX_SAFE_INTEGER;
  if (key === "session") return Number.POSITIVE_INFINITY;
  return key;
}

// Defensive ordering: normalize nodes whose stored turn does not match
// workflow meaning, then sort by numeric turn and workflow node order.
function groupByTurn(
  nodes: TraceExplorerNode[],
  turnContextNodes: TraceExplorerNode[] = nodes,
) {
  const buckets = new Map<TraceTurnGroupKey, TraceExplorerNode[]>();
  for (const node of nodes) {
    const key = effectiveTraceTurnKey(node, turnContextNodes);
    const bucket = buckets.get(key);
    if (bucket) {
      bucket.push(node);
    } else {
      buckets.set(key, [node]);
    }
  }
  const groups = Array.from(buckets.entries()).map(([key, items]) => ({
    label: traceTurnGroupLabel(key),
    sortKey: traceTurnGroupSortKey(key),
    nodes: [...items].sort((a, b) => {
      const orderDelta =
        traceNodeWorkflowOrder(a, items) - traceNodeWorkflowOrder(b, items);
      if (orderDelta !== 0) return orderDelta;
      return a.id - b.id;
    }),
  }));
  groups.sort((a, b) => a.sortKey - b.sortKey);
  return groups;
}

function formatTs(value?: string | null): string {
  if (!value) return "—";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return value;
  }
}

function truncate(value: string): string {
  if (value.length <= 16) return value;
  return `${value.slice(0, 6)}…${value.slice(-6)}`;
}

// Decide which TraceNodeCard to scroll into view when the QualityCenter
// deep-link arrives with ``?node=evaluator&dimension=system_design``.
// Prefers an exact match (node + dimension); falls back to the first
// matching node, then to ``null`` (no scroll) so the focus indicator
// only fires when the request really hit a real card.
function pickFocusedNodeId(
  nodes: TraceExplorerNode[],
  focusNode: string | undefined,
  focusDimension: string | undefined,
): number | null {
  if (!focusNode) return null;
  const wantedNode = traceNodeCanonicalName(focusNode).toLowerCase();
  const wantedDim = focusDimension?.toLowerCase();
  const exact = nodes.find(
    (n) =>
      traceNodeCanonicalName(n.node).toLowerCase() === wantedNode &&
      (wantedDim === undefined ||
        String(n.dimension ?? "").toLowerCase() === wantedDim),
  );
  if (exact) return exact.id;
  const nodeOnly = nodes.find(
    (n) => traceNodeCanonicalName(n.node).toLowerCase() === wantedNode,
  );
  return nodeOnly?.id ?? null;
}

// Build the LangSmith run URL from the admin meta + the run id stamped
// onto each generation_traces row. Returns ``null`` when LangSmith is
// disabled, the meta lacks a web_url, or the run id was never written
// (the default ``langsmith_tracing=False`` deployment); the caller
// hides the button in that case so we never link to a 404.
function buildLangSmithRunUrl(
  runId: string | null | undefined,
  meta: LangSmithAdminMeta | null,
): string | null {
  if (!runId || !meta || !meta.web_url) return null;
  if (meta.tracing_enabled === false) return null;
  const base = meta.web_url.replace(/\/$/, "");
  const project = meta.project ? encodeURIComponent(meta.project) : null;
  if (project) {
    return `${base}/o/-/projects/p/${project}/r/${encodeURIComponent(runId)}`;
  }
  return `${base}/r/${encodeURIComponent(runId)}`;
}
