"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
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
  const router = useRouter();
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

  const updateExplorerQuery = useCallback(
    (patch: Record<string, string | number | boolean | null>) => {
      const params = new URLSearchParams(searchParams.toString());
      for (const [key, value] of Object.entries(patch)) {
        if (value === null || value === "" || value === false) {
          params.delete(key);
        } else {
          params.set(key, String(value));
        }
      }
      const query = params.toString();
      router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams],
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
    const querySelected = parseOptionalInt(searchParams.get("selectedTraceId"));
    const needsFocusedNode = Boolean(focusNode && !focusedNodeId);
    const needsSelectedNode = Boolean(
      querySelected && !allNodes.some((node) => node.id === querySelected),
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
    searchParams,
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
      updateExplorerQuery({ selectedTraceId: node.id });
    },
    [updateExplorerQuery],
  );

  const handleNodeFilterChange = useCallback(
    (value: string) => {
      setNodeFilter(value);
      setSelectedNodeId(null);
      updateExplorerQuery({
        nodeType: value === "all" ? null : value,
        selectedTraceId: null,
      });
    },
    [updateExplorerQuery],
  );

  const handleFallbackFilterChange = useCallback(() => {
    setFallbackFilter((current) => {
      const next = !current;
      updateExplorerQuery({ fallback: next || null, selectedTraceId: null });
      return next;
    });
    setSelectedNodeId(null);
  }, [updateExplorerQuery]);

  const handleSearchChange = useCallback(
    (value: string) => {
      setSearchText(value);
      setSelectedNodeId(null);
      updateExplorerQuery({ q: value.trim() || null, selectedTraceId: null });
    },
    [updateExplorerQuery],
  );

  return (
    <div className="space-y-6">
      <TraceCommandCenter
        data={initialData}
        diagnostics={diagnostics}
        fallbackTraceCount={fallbackTraceCount}
        loadedCount={allNodes.length}
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
                  <CardTitle className="text-base">按轮次查看节点</CardTitle>
                </div>
                <CardDescription>
                  Timeline 按 `generation_traces` 排序；右侧详情展示可直接排障的结构化证据。
                  {nodeFilter !== "all" && (
                    <span className="ml-2 text-foreground">
                      筛选：{nodeFilter}（{filteredNodes.length} 条）
                    </span>
                  )}
                  {fallbackFilter && (
                    <span className="ml-2 text-amber-300">
                      只看 fallback（{filteredNodes.length} 条）
                    </span>
                  )}
                </CardDescription>
              </div>
              {allNodes.length > 0 && (
                <Badge variant="outline" className="font-mono text-[10px] shrink-0">
                  {filteredNodes.length}/{allNodes.length} 节点
                </Badge>
              )}
            </div>
            <label className="relative block max-w-xl pt-1 text-xs text-muted-foreground">
              节点搜索
              <Search className="pointer-events-none absolute bottom-2.5 left-2.5 h-3.5 w-3.5 text-muted-foreground" />
              <input
                name="trace-node-search"
                type="search"
                autoComplete="off"
                value={searchText}
                onChange={(event) => handleSearchChange(event.target.value)}
                placeholder="搜索节点、问题、回答、context…"
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
                  只看 fallback
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
                当前筛选没有命中节点。可以清空搜索或切换节点类型。
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
                  {loadingMore ? "加载中…" : `加载更多（已展示 ${allNodes.length}/${totalNodeCount}）`}
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
          <p className="font-medium text-amber-300">Trace 覆盖提示</p>
        </div>
        <div className="grid gap-2 text-xs md:grid-cols-3">
          <NodeFact label="health" value={diagnostics.health} />
          <NodeFact label="status" value={diagnostics.session_status ?? "—"} />
          <NodeFact label="last_node" value={diagnostics.last_node ?? "—"} />
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
        text: "会话仍在进行中（status=running），节点 trace 会在面试推进时陆续写入。",
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
          <p className="font-medium text-amber-300">逐轮 trace 缺失 · 诊断</p>
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
          <summary className="cursor-pointer select-none">查看 tracer 健康原始数据</summary>
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
  totalNodeCount,
  turnCount,
}: {
  data: TraceExplorerResponse;
  diagnostics: TraceDiagnostics | null;
  fallbackTraceCount: number;
  loadedCount: number;
  totalNodeCount: number;
  turnCount: number;
}) {
  const healthTone =
    data.trace_health === "complete"
      ? "text-emerald-300"
      : data.trace_health === "partial"
        ? "text-amber-300"
        : "text-destructive";
  const missingNodes = diagnostics?.missing_key_nodes ?? [];

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
              面向工程排障的单场 trace 工作台：先看健康与缺口，再按轮次定位节点证据。
            </CardDescription>
            <p className="mt-2 break-all font-mono text-[11px] text-muted-foreground">
              {data.session_id}
            </p>
          </div>
          <BackLinks sessionId={data.session_id} />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
          <SummaryTile label="状态" value={data.status || "unknown"} />
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
          <SummaryTile label="节点" value={String(totalNodeCount)} />
          <SummaryTile
            label="已加载"
            value={`${loadedCount}/${totalNodeCount}${data.nodes_has_more ? "+" : ""}`}
          />
        </div>
        <div className="flex flex-wrap gap-2 text-xs text-muted-foreground">
          <Badge variant="outline" className="font-mono text-[10px]">
            evaluator {data.evaluator_trace_count}
          </Badge>
          <Badge variant="outline" className="font-mono text-[10px]">
            reward {data.reward_trace_count}
          </Badge>
          <Badge variant="outline" className="font-mono text-[10px]">
            final_report {data.final_report_trace_count}
          </Badge>
          {diagnostics?.last_node && (
            <Badge variant="secondary" className="font-mono text-[10px]">
              last {diagnostics.last_node}
            </Badge>
          )}
        </div>
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
        选择左侧 timeline 里的节点查看详情。
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
          {isFallback && <Badge variant="warn">评分 fallback</Badge>}
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
        <NodeFact label="turn" value={String(node.turn_idx ?? "session")} />
        <NodeFact label="context" value={node.context_key || "—"} />
        <NodeFact label="policy" value={node.policy_id || "—"} />
        <NodeFact label="created" value={formatTs(node.created_at)} />
      </div>
      {node.policy_context_keys && node.policy_context_keys.length > 0 && (
        <NodeFact label="policy_context_keys" value={node.policy_context_keys.join(", ")} />
      )}

      <NodeTimingBar payload={node.payload} />

      {node.answer_excerpt && (
        <section className="mt-3 rounded-md border bg-background/60 p-3 text-xs">
          <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            answer_excerpt
          </p>
          <p className="mt-1 leading-relaxed">{node.answer_excerpt}</p>
        </section>
      )}

      <EvaluationEvidence node={node} />

      {node.node === "ask_question" && (
        <SkillSelectionPanel payload={node.payload} />
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
          EvaluationEvidence
        </span>
        {typeof node.immediate_reward_applied === "boolean" && (
          <Badge
            variant={node.immediate_reward_applied ? "success" : "outline"}
            className="text-[10px]"
          >
            reward {node.immediate_reward_applied ? "applied" : "pending"}
          </Badge>
        )}
      </div>
      {rationale && <p className="mt-2 leading-relaxed">{rationale}</p>}
      {verifierRationale && node.node === "verification" && (
        <p className="mt-2 leading-relaxed text-amber-200">
          Verifier：{verifierRationale}
        </p>
      )}
      {(strengths.length > 0 || weaknesses.length > 0) && (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          <EvidenceList label="strengths" values={strengths} />
          <EvidenceList label="weaknesses" values={weaknesses} />
        </div>
      )}
    </section>
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
        查看原始 trace payload
      </summary>
      {open ? (
        <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px]">
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
          节点 {formatMs(nodeMs)}
        </Badge>
      )}
      {llmMs !== null && (
        <Badge variant="outline" className="font-mono text-[10px] gap-1">
          LLM {formatMs(llmMs)}{llmCalls > 0 ? ` · ${llmCalls}次` : ""}
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
  const name = typeof ref_.name === "string" ? ref_.name : id || "(unnamed)";
  const description = typeof ref_.description === "string" ? ref_.description : "";
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
          <p className="font-medium leading-tight">{name}</p>
          {description && (
            <p className="mt-1 text-[11px] leading-snug text-muted-foreground">
              {description}
            </p>
          )}
          {id && (
            <p className="mt-1 font-mono text-[10px] text-muted-foreground">{id}</p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-1">
          {priority !== null && (
            <Badge variant="outline" className="text-[10px]">
              p{priority}
            </Badge>
          )}
          {matchScore !== null && (
            <Badge variant="outline" className="text-[10px]">
              score {matchScore.toFixed(1)}
            </Badge>
          )}
          {evaluatorVisibility ? (
            <Badge variant="success" className="text-[10px]">
              evaluator-visible
            </Badge>
          ) : (
            <Badge variant="outline" className="text-[10px]">
              generator-only
            </Badge>
          )}
        </div>
      </div>

      {(dimensions.length || jobLevels.length || roleTags.length) > 0 && (
        <div className="mt-2 grid grid-cols-3 gap-1 text-[10px] text-muted-foreground">
          <SkillFact label="dim" values={dimensions} />
          <SkillFact label="lvl" values={jobLevels} />
          <SkillFact label="role" values={roleTags} />
        </div>
      )}

      {matchReasons.length > 0 && (
        <p className="mt-2 font-mono text-[10px] text-muted-foreground">
          why: {matchReasons.join(" · ")}
        </p>
      )}

      {evaluatorPayload && (
        <details className="mt-2 rounded border bg-background/40 p-2 text-[11px]">
          <summary className="cursor-pointer select-none text-muted-foreground">
            Evaluator 可见提示
          </summary>
          <div className="mt-2 flex flex-col gap-1.5">
            <SkillPayloadList
              label="rubric_hints"
              values={stringList(evaluatorPayload.rubric_hints)}
            />
            <SkillPayloadList
              label="positive_signals"
              values={stringList(evaluatorPayload.positive_signals)}
            />
            <SkillPayloadList
              label="negative_signals"
              values={stringList(evaluatorPayload.negative_signals)}
            />
            <SkillPayloadList
              label="score_bias_rules"
              values={stringList(evaluatorPayload.score_bias_rules)}
            />
          </div>
        </details>
      )}
    </li>
  );
}

function SkillFact({ label, values }: { label: string; values: string[] }) {
  return (
    <div>
      <span className="font-mono uppercase tracking-wider">{label}</span>
      <p className="mt-0.5 break-words font-mono">{values.length ? values.join(", ") : "—"}</p>
    </div>
  );
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
  ];
  return fields.some((field) => String(field ?? "").toLowerCase().includes(query));
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
