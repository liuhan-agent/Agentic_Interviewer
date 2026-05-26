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
  type LangSmithAdminMeta,
  type TraceDiagnostics,
  type TraceExplorerNode,
  type TraceExplorerResponse,
  type TraceHealth,
  type TracerHealthSnapshot,
} from "@/lib/api/admin";

type Fetch =
  | { phase: "loading" }
  | { phase: "ready"; data: TraceExplorerResponse }
  | { phase: "error"; message: string };

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
  const [state, setState] = useState<Fetch>({ phase: "loading" });
  const [retryKey, setRetryKey] = useState(0);

  useEffect(() => {
    const ctrl = new AbortController();
    setState({ phase: "loading" });
    getTraceExplorer(sessionId, ctrl.signal)
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
  }, [sessionId, retryKey]);

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
            <BackLinks sessionId={sessionId} />
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <TraceExplorerBody
      data={state.data}
      sessionId={sessionId}
      focusNode={focusNode}
      focusDimension={focusDimension}
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
  "route_decision",
  "final_report",
  "compress_context",
  "refine_followup",
  "training_plan",
  "experience_extractor",
  "resume_parse",
] as const;

type PromptSlotDefinition = {
  promptLabel: string;
  sourceKey: string;
  title: string;
  description: string;
};

const PROMPT_SLOT_DEFINITIONS: PromptSlotDefinition[] = [
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

function TraceExplorerBody({
  data: initialData,
  sessionId,
  focusNode,
  focusDimension,
}: {
  data: TraceExplorerResponse;
  sessionId: string;
  focusNode?: string;
  focusDimension?: string;
}) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [allNodes, setAllNodes] = useState<TraceExplorerNode[]>(initialData.nodes);
  const [hasMore, setHasMore] = useState(initialData.nodes_has_more);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [nodeFilter, setNodeFilter] = useState<string>(
    searchParams.get("nodeType") || "all",
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
    getTraceExplorer(sessionId, ctrl.signal, { offset: allNodes.length })
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
  }, [sessionId, allNodes.length, hasMore, loadingMore]);

  const filteredNodes = useMemo(() => {
    const q = searchText.trim().toLowerCase();
    return allNodes.filter((node) => {
      if (nodeFilter !== "all" && node.node !== nodeFilter) return false;
      if (fallbackFilter && !isEvaluatorFallbackTrace(node)) return false;
      if (!q) return true;
      return nodeMatchesQuery(node, q);
    });
  }, [allNodes, fallbackFilter, nodeFilter, searchText]);

  const grouped = useMemo(() => groupByTurn(filteredNodes), [filteredNodes]);
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
      setNodeFilter(value);
      setSelectedNodeId(null);
      replaceExplorerUrl({
        nodeType: value === "all" ? null : value,
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
      />

      {initialData.trace_health === "missing" && (
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
                      节点筛选：{nodeFilter}（{filteredNodes.length} 条）
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
                const count = t === "all" ? totalNodeCount : (nodeTypeCounts[t] ?? 0);
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
                    {t === "all" ? "全部" : t}
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

function BackLinks({ sessionId }: { sessionId: string }) {
  return (
    <div className="flex flex-wrap gap-2">
      <Button asChild variant="outline" size="sm" className="gap-1.5">
        <PendingNavigationLink href="/admin">
          <ArrowLeft className="h-3.5 w-3.5" />
          返回后台
        </PendingNavigationLink>
      </Button>
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
  loadedCount,
  nodeTypeCounts,
  totalNodeCount,
  turnCount,
}: {
  data: TraceExplorerResponse;
  diagnostics: TraceDiagnostics | null;
  fallbackTraceCount: number;
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
              <CardTitle className="text-xl">Trace Explorer</CardTitle>
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
          <BackLinks sessionId={data.session_id} />
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
          <SummaryTile label="最后节点" value={diagnostics?.last_node ?? "—"} />
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
              {visibleNodeDistribution.map(([node, count]) => (
                <Badge
                  key={node}
                  variant="outline"
                  translate="no"
                  className="max-w-full gap-1 font-mono text-[10px]"
                >
                  <span className="min-w-0 truncate">{node}</span>
                  <span className="shrink-0 tabular-nums text-muted-foreground">
                    {count}
                  </span>
                </Badge>
              ))}
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
                    <span className="min-w-0 truncate font-mono text-[11px]">
                      {node.node}
                    </span>
                    {typeof node.score === "number" && (
                      <span className="font-mono text-[10px] tabular-nums">
                        {node.score.toFixed(1)}
                      </span>
                    )}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {node.dimension && (
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
  focused,
  prefersReducedMotion,
}: {
  node: TraceExplorerNode | null;
  sessionId: string;
  traceId: string;
  langsmith: LangSmithAdminMeta | null;
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

  const langsmithUrl = buildLangSmithRunUrl(node.langsmith_run_id, langsmith);
  const isFallback = isEvaluatorFallbackTrace(node);
  const rawPayload = {
    payload: node.payload,
    evaluation: node.evaluation,
    policy_context_keys: node.policy_context_keys,
    answer_excerpt: node.answer_excerpt,
  };

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
              {node.node}
            </Badge>
            {node.dimension && (
              <span className="text-xs text-muted-foreground">{node.dimension}</span>
            )}
          </div>
          {node.question && (
            <p className="mt-2 line-clamp-2 text-sm leading-relaxed">
              {node.question}
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          {node.action_id && <Badge variant="secondary">{node.action_id}</Badge>}
          {typeof node.score === "number" && (
            <Badge variant={node.passed ? "success" : "warn"}>
              {node.score.toFixed(1)}
            </Badge>
          )}
          {typeof node.immediate_reward === "number" && (
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
        <NodeFact label="轮次" value={String(node.turn_idx ?? "session")} />
        <NodeFact label="上下文" value={node.context_key || "—"} />
        <NodeFact label="策略" value={node.policy_id || "—"} />
        <NodeFact label="创建时间" value={formatTs(node.created_at)} />
      </div>
      {node.policy_context_keys && node.policy_context_keys.length > 0 && (
        <NodeFact label="策略上下文键" value={node.policy_context_keys.join(", ")} />
      )}

      {node.node === "director_sample" && (
        <StrategyDecisionSummary node={node} />
      )}

      <NodeTimingBar payload={node.payload} />

      {node.node !== "ask_question" && node.answer_excerpt && (
        <section className="mt-3 rounded-md border bg-background/60 p-3 text-xs">
          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            回答摘录
          </p>
          <p className="mt-1 leading-relaxed">{node.answer_excerpt}</p>
        </section>
      )}

      <EvaluationEvidence node={node} />

      {node.node === "ask_question" && (
        <AskQuestionEvidencePanel node={node} />
      )}

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
      {annotating && (
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

function EvaluationEvidence({ node }: { node: TraceExplorerNode }) {
  if (node.node === "director_sample" || node.node === "ask_question") return null;

  const evaluation = recordFromUnknown(node.evaluation);
  const payload = recordFromUnknown(node.payload);
  const verifierRationale =
    typeof payload.rationale === "string"
      ? payload.rationale
      : typeof payload.verifier_rationale === "string"
        ? payload.verifier_rationale
        : "";
  const strengths = stringList(evaluation.strengths);
  const weaknesses = stringList(evaluation.weaknesses);
  const rationale =
    stringValue(evaluation.rationale) ||
    stringValue(evaluation.reasoning) ||
    stringValue(evaluation.feedback) ||
    stringValue(payload.rationale);

  if (
    strengths.length === 0 &&
    weaknesses.length === 0 &&
    !rationale &&
    !verifierRationale &&
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
      {verifierRationale && node.node === "verification" && (
        <p className="mt-2 leading-relaxed text-amber-200">
          校验器（Verifier）：{verifierRationale}
        </p>
      )}
      {(strengths.length > 0 || weaknesses.length > 0) && (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <EvidenceList label="优势" values={strengths} />
          <EvidenceList label="不足" values={weaknesses} />
        </div>
      )}
    </section>
  );
}

function StrategyDecisionSummary({ node }: { node: TraceExplorerNode }) {
  const payload = recordFromUnknown(node.payload);
  const selectedAction = recordFromUnknown(payload.selected_action);
  const diagnostics = recordFromUnknown(payload.diagnostics);
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
  const actionDescription = localizeActionDescription(
    actionId,
    actionLabel,
    stringValue(selectedAction.description),
  );
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
            <p className="font-medium text-emerald-200">策略决策摘要</p>
          </div>
          <p className="mt-1 max-w-3xl text-muted-foreground">
            这条记录说明 Director 出题前如何选择下一步动作，不是候选人答题评分。
            决策用一个 context；reward_update 回填全部 context keys。
          </p>
        </div>
        {actionDescription && (
          <p className="max-w-md rounded-md bg-background/50 px-2 py-1 text-[11px] leading-relaxed text-muted-foreground">
            {actionDescription}
          </p>
        )}
      </div>
      <div className="mt-3 grid gap-2 md:grid-cols-3">
        <NodeFact label="节点类型" value={node.node} />
        <NodeFact label="目标维度" value={targetDimension} />
        <NodeFact
          label="选择动作"
          value={actionLabel ? `${actionId} · ${actionLabel}` : actionId}
        />
        <NodeFact label="决策上下文" value={decisionContext} />
        <NodeFact label="策略算法" value={policy.algorithm} />
        <NodeFact label="策略空间" value={policy.space} />
        <NodeFact
          label="奖励回填上下文"
          value={candidateContexts.length > 0 ? candidateContexts.join(", ") : "—"}
        />
        <NodeFact label="奖励状态" value={rewardStatus} />
      </div>
    </section>
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
              <EvidenceList
                label="acceptance_checks"
                values={contractAcceptanceChecks}
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
            <NodeFact label="项目锚点" value={anchorLabel} />
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
              value={stringValue(candidateAnchorRag.fallback_reason) || "—"}
            />
            <NodeFact
              label="Boost 兜底 boost_fallback_reason"
              value={stringValue(candidateAnchorRag.boost_fallback_reason) || "—"}
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
          summary={`7 prompt slots · ${promptSlots.length} recorded`}
          emptyText="这条旧 trace 没有记录 prompt_slots。"
        >
          <p className="mb-2 text-[11px] leading-relaxed text-muted-foreground">
            按 Generator 最终接收的 7 个槽位展示；前面的版块解释“怎么选出来”，这里说明
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
          {slot?.truncated === true && (
            <Badge variant="warn" className="text-[10px]">
              截断
            </Badge>
          )}
        </div>
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
        {definition.description}
      </p>
      <div className="mt-2 grid gap-2 md:grid-cols-4">
        <NodeFact label="来源字段" value={sourceKey} />
        <NodeFact label="字符数" value={recorded ? formatCountValue(slot?.chars) : "—"} />
        <NodeFact label="已截断" value={recorded ? formatBooleanValue(slot?.truncated) : "—"} />
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
    </div>
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
          <li key={idx}>{value}</li>
        ))}
      </ul>
    </div>
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
    <div className="rounded-md bg-background/60 p-2">
      <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 break-words font-mono text-[11px]">{value}</p>
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
  if (actionId === "plan_switch" || actionLabel === "Plan: Switch") {
    return "切换到下一个待覆盖维度，并用 adaptive 模板出下一题。";
  }
  return description;
}

function recordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter(
        (item): item is Record<string, unknown> =>
          Boolean(item) && typeof item === "object" && !Array.isArray(item),
      )
    : [];
}

function formatCountValue(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? String(value) : "—";
}

function formatScore(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "—";
}

function formatBooleanValue(value: unknown): string {
  if (typeof value !== "boolean") return "—";
  return value ? "是" : "否";
}

function formatStringListValue(value: unknown): string {
  const values = stringList(value);
  return values.length > 0 ? values.join(", ") : "—";
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

function strategyMemoryTraceKey(strategy: Record<string, unknown>): string {
  return (
    stringValue(strategy.memory_key) ||
    stringValue(strategy.id) ||
    stringValue(strategy.slug)
  );
}

function localizeStrategyMemoryName(strategy: Record<string, unknown>): string {
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
  return (
    <EvidenceRow>
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant="outline" className="font-mono text-[10px]">
            rank {formatCountValue(item.rank)}
          </Badge>
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
      </div>
      <Badge variant="outline" className="shrink-0 font-mono text-[10px]">
        match {formatScore(item.match_score)}
      </Badge>
    </EvidenceRow>
  );
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
    counts[node.node] = (counts[node.node] || 0) + 1;
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
  ];
  return fields.some((field) => String(field ?? "").toLowerCase().includes(query));
}

function askQuestionSearchFields(
  payload?: Record<string, unknown> | null,
): string[] {
  const record = recordFromUnknown(payload);
  const artifacts = recordFromUnknown(record.selection_artifacts);
  const fields: string[] = [];
  const add = (value: unknown) => {
    if (typeof value === "string" && value.trim()) fields.push(value);
  };
  const addList = (value: unknown) => {
    for (const item of stringList(value)) fields.push(item);
  };

  add(record.plan_template);
  add(record.probe_intent);
  add(record.dimension);
  add(record.contract_bar_level);
  addList(record.signed_by);

  const contract = recordFromUnknown(record.contract);
  addList(contract.must_cover);
  addList(contract.acceptance_checks);
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
    add(slot.text);
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
  }

  for (const strategy of recordArray(artifacts.strategies)) {
    // strategy id/name
    add(strategy.id);
    add(strategy.name);
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
  }

  const candidateAnchor = recordFromUnknown(artifacts.candidate_anchor);
  add(candidateAnchor.matched_project);
  add(candidateAnchor.project_name);
  add(candidateAnchor.variant_id);

  const candidateAnchorRag = recordFromUnknown(artifacts.candidate_anchor_rag);
  // candidate anchor RAG diagnostics
  add(candidateAnchorRag.status);
  add(candidateAnchorRag.fallback_reason);
  add(candidateAnchorRag.boost_fallback_reason);
  addList(candidateAnchorRag.prompt_block_sources);
  addList(candidateAnchorRag.anchor_terms);
  addList(candidateAnchorRag.boost_terms);
  addList(candidateAnchorRag.constraint_terms);
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

// Defensive ordering: do not rely on Map insertion order to match the
// backend's ``ORDER BY turn_idx`` for the bucket-level sequence. A
// future backend change (or an admin replay endpoint that pages
// non-monotonically) could otherwise yield "Turn 10 above Turn 2"
// because string-keyed maps do not sort numerically. Bucket-internal
// order still mirrors backend ordering.
function groupByTurn(nodes: TraceExplorerNode[]) {
  const buckets = new Map<number | "session", TraceExplorerNode[]>();
  for (const node of nodes) {
    const key = typeof node.turn_idx === "number" ? node.turn_idx : "session";
    const bucket = buckets.get(key);
    if (bucket) {
      bucket.push(node);
    } else {
      buckets.set(key, [node]);
    }
  }
  const groups = Array.from(buckets.entries()).map(([key, items]) => ({
    label: key === "session" ? "Session-level events" : `Turn ${key}`,
    sortKey: key === "session" ? Number.POSITIVE_INFINITY : key,
    nodes: items,
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
  const wantedNode = focusNode.toLowerCase();
  const wantedDim = focusDimension?.toLowerCase();
  const exact = nodes.find(
    (n) =>
      String(n.node ?? "").toLowerCase() === wantedNode &&
      (wantedDim === undefined ||
        String(n.dimension ?? "").toLowerCase() === wantedDim),
  );
  if (exact) return exact.id;
  const nodeOnly = nodes.find(
    (n) => String(n.node ?? "").toLowerCase() === wantedNode,
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
