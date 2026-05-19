"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, AlertTriangle, ArrowLeft, ChevronDown, ExternalLink, FileText, GitBranch, Loader2, RefreshCw, Timer } from "lucide-react";

import { TraceAnnotationDialog } from "@/components/admin/TraceAnnotationDialog";
import { WorkflowChainPanel } from "@/components/admin/WorkflowChainPanel";

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
  const [allNodes, setAllNodes] = useState<TraceExplorerNode[]>(initialData.nodes);
  const [hasMore, setHasMore] = useState(initialData.nodes_has_more);
  const [loadingMore, setLoadingMore] = useState(false);
  const [nodeFilter, setNodeFilter] = useState<string>("all");
  const [fallbackFilter, setFallbackFilter] = useState(false);

  const totalNodeCount = initialData.node_count_total ?? initialData.trace_count;
  const diagnostics = initialData.trace_diagnostics ?? null;

  const loadMore = useCallback(() => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    const ctrl = new AbortController();
    getTraceExplorer(sessionId, ctrl.signal, { offset: allNodes.length })
      .then((resp) => {
        if (ctrl.signal.aborted) return;
        setAllNodes((prev) => [...prev, ...resp.nodes]);
        setHasMore(resp.nodes_has_more);
      })
      .catch(() => {})
      .finally(() => setLoadingMore(false));
  }, [sessionId, allNodes.length, hasMore, loadingMore]);

  const filteredNodes = useMemo(() => {
    const byNode = nodeFilter === "all" ? allNodes : allNodes.filter((n) => n.node === nodeFilter);
    return fallbackFilter ? byNode.filter(isEvaluatorFallbackTrace) : byNode;
  }, [allNodes, fallbackFilter, nodeFilter]);

  const grouped = useMemo(() => groupByTurn(filteredNodes), [filteredNodes]);
  const focusedNodeId = useMemo(
    () => pickFocusedNodeId(allNodes, focusNode, focusDimension),
    [allNodes, focusNode, focusDimension],
  );

  const nodeTypeCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const node of allNodes) {
      counts[node.node] = (counts[node.node] || 0) + 1;
    }
    return counts;
  }, [allNodes]);
  const fallbackTraceCount = useMemo(
    () => allNodes.filter(isEvaluatorFallbackTrace).length,
    [allNodes],
  );

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <GitBranch className="h-4 w-4 text-emerald-400" />
                <CardTitle className="text-xl">Trace Explorer</CardTitle>
              </div>
              <CardDescription className="mt-1">
                按 workflow 节点查看这一场面试的内部过程和结果。
              </CardDescription>
            </div>
            <BackLinks sessionId={initialData.session_id} />
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-4 lg:grid-cols-7">
            <SummaryTile label="Session" value={truncate(initialData.session_id)} />
            <SummaryTile label="状态" value={initialData.status || "unknown"} />
            <SummaryTile label="Trace" value={healthLabel[initialData.trace_health]} />
            <SummaryTile label="节点数" value={String(initialData.trace_count)} />
            <SummaryTile
              label="已加载"
              value={`${allNodes.length}/${totalNodeCount}${hasMore ? "+" : ""}`}
            />
            <SummaryTile label="评分节点" value={String(initialData.evaluator_trace_count)} />
            <SummaryTile
              label="总分"
              value={
                typeof initialData.overall_score === "number"
                  ? initialData.overall_score.toFixed(2)
                  : "—"
              }
            />
          </div>
        </CardContent>
      </Card>

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
        <WorkflowChainPanel sessionId={initialData.session_id} />
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
                  节点顺序来自后端 `generation_traces`，不是前端猜测的固定流程。
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
            <div className="flex flex-wrap gap-1.5 pt-1">
              {NODE_TYPE_FILTERS.map((t) => {
                const count = t === "all" ? allNodes.length : (nodeTypeCounts[t] ?? 0);
                if (t !== "all" && count === 0) return null;
                return (
                  <button
                    key={t}
                    onClick={() => setNodeFilter(t)}
                    className={[
                      "rounded-md border px-2 py-1 text-[11px] font-mono transition-colors",
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
                  onClick={() => setFallbackFilter((v) => !v)}
                  className={[
                    "rounded-md border px-2 py-1 text-[11px] font-mono transition-colors",
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
            {grouped.map((group) => (
              <div key={group.label} className="space-y-2">
                <p className="font-mono text-xs uppercase tracking-wider text-muted-foreground">
                  {group.label}
                </p>
                <div className="space-y-2">
                  {group.nodes.map((node) => (
                    <TraceNodeCard
                      key={node.id}
                      node={node}
                      sessionId={initialData.session_id}
                      traceId={initialData.trace_id ?? initialData.session_id}
                      langsmith={initialData.langsmith ?? null}
                      focused={focusedNodeId === node.id}
                    />
                  ))}
                </div>
              </div>
            ))}

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
        <Link href="/admin">
          <ArrowLeft className="h-3.5 w-3.5" />
          返回后台
        </Link>
      </Button>
      <Button asChild variant="ghost" size="sm" className="gap-1.5">
        <Link href={`/interview/${sessionId}/report`}>查看报告</Link>
      </Button>
      <Button asChild variant="ghost" size="sm" className="gap-1.5">
        <Link href={`/interview/${sessionId}/replay`}>Replay</Link>
      </Button>
    </div>
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

function TraceNodeCard({
  node,
  sessionId,
  traceId,
  langsmith,
  focused = false,
}: {
  node: TraceExplorerNode;
  sessionId: string;
  traceId: string;
  langsmith: LangSmithAdminMeta | null;
  focused?: boolean;
}) {
  const langsmithUrl = buildLangSmithRunUrl(node.langsmith_run_id, langsmith);
  const isFallback = isEvaluatorFallbackTrace(node);
  const ref = useRef<HTMLDivElement | null>(null);
  const [annotating, setAnnotating] = useState(false);
  const openAnnotation = useCallback(() => setAnnotating(true), []);
  const closeAnnotation = useCallback(() => setAnnotating(false), []);

  useEffect(() => {
    if (focused && ref.current) {
      ref.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [focused]);

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
        <NodeFact label="context" value={node.context_key || "—"} />
        <NodeFact label="policy" value={node.policy_id || "—"} />
        <NodeFact label="created" value={formatTs(node.created_at)} />
      </div>

      <NodeTimingBar payload={node.payload} />

      {node.node === "ask_question" && (
        <SkillSelectionPanel payload={node.payload} />
      )}

      <div className="mt-3 flex items-center gap-2">
        <details className="flex-1 rounded-md border bg-background/60 p-2 text-xs">
          <summary className="cursor-pointer select-none text-muted-foreground">
            查看原始 trace payload
          </summary>
          <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px]">
            {JSON.stringify(
              {
                payload: node.payload,
                evaluation: node.evaluation,
                policy_context_keys: node.policy_context_keys,
                answer_excerpt: node.answer_excerpt,
              },
              null,
              2,
            )}
          </pre>
        </details>
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
