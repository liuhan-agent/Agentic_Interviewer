"use client";

import { useEffect, useMemo, useState } from "react";
import { Database, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  deleteSessionAnchorData,
  getSessionAnchorRagMetrics,
  getSessionAnchorRagSummary,
  type DeleteSessionAnchorDataResponse,
  type SessionAnchorRagMetricBucket,
  type SessionAnchorRagMetrics,
  type SessionAnchorRagSummary,
} from "@/lib/api/admin";
import { cn } from "@/lib/utils";

type Phase =
  | { kind: "loading" }
  | { kind: "ready"; summary: SessionAnchorRagSummary; metrics: SessionAnchorRagMetrics }
  | { kind: "error"; message: string };

const SOURCE_LABELS: Record<string, string> = {
  resume: "简历",
  self_intro: "自我介绍",
};

const MODE_ORDER = ["A", "B", "C", "D", "SI", "unknown"] as const;
const FALLBACK_ORDER = ["low_score", "timeout", "empty", "not_ready", "skipped", "error"];
const FALLBACK_TONE: Record<string, string> = {
  low_score: "bg-amber-400",
  timeout: "bg-red-400",
  empty: "bg-slate-400",
  not_ready: "bg-sky-400",
  skipped: "bg-zinc-400",
  error: "bg-rose-500",
};

export function CandidateAnchorRagCard() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [refreshKey, setRefreshKey] = useState(0);
  const [sessionId, setSessionId] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [deleteResult, setDeleteResult] =
    useState<DeleteSessionAnchorDataResponse | null>(null);
  const [deleteError, setDeleteError] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    setPhase((prev) => (prev.kind === "ready" ? prev : { kind: "loading" }));
    Promise.all([
      getSessionAnchorRagSummary(ctrl.signal),
      getSessionAnchorRagMetrics(ctrl.signal),
    ])
      .then(([summary, metrics]) => {
        if (!ctrl.signal.aborted) {
          setPhase({ kind: "ready", summary, metrics });
        }
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setPhase({
          kind: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      });
    return () => ctrl.abort();
  }, [refreshKey]);

  const modeBadge = phase.kind === "ready" ? phase.summary.resume_rag_mode : "loading";
  const trimmedSessionId = sessionId.trim();
  const canDelete = trimmedSessionId.length > 0 && confirmText === trimmedSessionId;

  async function handleDelete() {
    if (!canDelete) return;
    setDeleting(true);
    setDeleteError("");
    try {
      const result = await deleteSessionAnchorData(trimmedSessionId);
      setDeleteResult(result);
      setConfirmOpen(false);
      setConfirmText("");
      setRefreshKey((v) => v + 1);
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : String(err));
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <Database className="h-4 w-4 text-emerald-400" />
                资料理解 RAG
              </CardTitle>
              <CardDescription className="mt-1">
                观察简历与自我介绍资料召回，不与知识 RAG 合并。
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant={modeBadge === "primary" ? "success" : "outline"} className="font-mono">
                {modeBadge}
              </Badge>
              <Button
                size="icon"
                variant="outline"
                aria-label="刷新资料理解 RAG"
                onClick={() => setRefreshKey((v) => v + 1)}
              >
                <RefreshCw className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          {phase.kind === "loading" && (
            <div className="space-y-3">
              <Skeleton className="h-16 w-full" />
              <Skeleton className="h-36 w-full" />
            </div>
          )}

          {phase.kind === "error" && (
            <p className="text-sm text-destructive">{phase.message}</p>
          )}

          {phase.kind === "ready" && (
            <CandidateAnchorRagBody
              summary={phase.summary}
              metrics={phase.metrics}
            />
          )}

          <div className="rounded-md border border-dashed bg-card/50 p-3">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <div className="min-w-0 flex-1">
                <label className="text-xs font-medium text-muted-foreground">
                  Session ID
                </label>
                <Input
                  value={sessionId}
                  onChange={(event) => setSessionId(event.target.value)}
                  placeholder="输入 session_id 后删除该场锚点数据"
                  className="mt-1 font-mono text-xs"
                />
              </div>
              <Button
                variant="destructive"
                disabled={!trimmedSessionId}
                onClick={() => {
                  setConfirmText("");
                  setDeleteError("");
                  setConfirmOpen(true);
                }}
              >
                <Trash2 className="h-4 w-4" />
                删除资料数据
              </Button>
            </div>
            {deleteResult && (
              <p className="mt-2 text-xs text-muted-foreground">
                已处理 {deleteResult.session_id}：chunks {deleteResult.chunks_deleted}，
                artifacts {deleteResult.resume_artifacts_deleted}，traces {deleteResult.traces_scrubbed}。
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent className="border-red-500/30 sm:max-w-[520px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 text-red-400" />
              删除候选人资料数据？
            </DialogTitle>
            <DialogDescription>
              这会删除该 session 的简历 / 自我介绍检索资料、关联解析 artifact，并清理持久化 trace 中的相关片段。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <p className="text-xs text-muted-foreground">
              输入完整 session_id 以确认：
              <span className="ml-1 font-mono text-foreground">{trimmedSessionId}</span>
            </p>
            <Input
              value={confirmText}
              onChange={(event) => setConfirmText(event.target.value)}
              className="font-mono text-xs"
            />
            {deleteError && (
              <p className="text-xs text-destructive">{deleteError}</p>
            )}
          </div>
          <DialogFooter className="gap-2 sm:gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => setConfirmOpen(false)}
            >
              取消
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={!canDelete || deleting}
              onClick={handleDelete}
            >
              {deleting ? "删除中" : "确认删除"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function CandidateAnchorRagBody({
  summary,
  metrics,
}: {
  summary: SessionAnchorRagSummary;
  metrics: SessionAnchorRagMetrics;
}) {
  const sourceRows = useMemo(
    () =>
      Object.keys(summary.by_source_type || {})
        .sort()
        .map((source) => ({
          source,
          counts: summary.by_source_type[source],
          metrics: metrics.by_source_type[source],
        })),
    [summary.by_source_type, metrics.by_source_type],
  );
  const modeRows = MODE_ORDER.map((mode) => ({
    mode,
    counts: summary.by_mode[mode],
    metrics: metrics.by_mode[mode],
  })).filter((row) => row.counts || row.metrics);
  const storedEmbeddingVersions = Object.entries(
    summary.by_embedding_model_version || {},
  )
    .sort((a, b) => (b[1]?.chunks || 0) - (a[1]?.chunks || 0))
    .map(([version, bucket]) => `${version} (${bucket.chunks})`)
    .join(" / ");

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-3">
        <MetricTile label="chunks" value={String(summary.total_chunks)} />
        <MetricTile label="sessions" value={String(summary.total_sessions)} />
        <MetricTile
          label="embedding"
          value={storedEmbeddingVersions || summary.embedding_model_version || "unknown"}
          compact
        />
      </div>

      <div className="overflow-x-auto rounded-md border">
        <table className="w-full min-w-[680px] text-left text-xs">
          <thead className="bg-muted/60 text-muted-foreground">
            <tr>
              <th className="px-3 py-2 font-medium">source / mode</th>
              <th className="px-3 py-2 font-medium">chunks</th>
              <th className="px-3 py-2 font-medium">sessions</th>
              <th className="px-3 py-2 font-medium">hit-rate</th>
              <th className="px-3 py-2 font-medium">p50 / p99</th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {sourceRows.map((row) => (
              <MetricRow
                key={`source-${row.source}`}
                label={SOURCE_LABELS[row.source] ?? row.source}
                chunks={row.counts?.chunks}
                sessions={row.counts?.sessions}
                metric={row.metrics}
              />
            ))}
            {modeRows.map((row) => (
              <MetricRow
                key={`mode-${row.mode}`}
                label={`Mode ${row.mode}`}
                chunks={row.counts?.chunks}
                sessions={row.counts?.sessions}
                metric={row.metrics}
              />
            ))}
          </tbody>
        </table>
      </div>

      <div className="space-y-2">
        <p className="text-xs font-medium uppercase text-muted-foreground">
          fallback reasons by mode
        </p>
        {modeRows.map((row) => (
          <FallbackBar key={row.mode} mode={row.mode} metric={row.metrics} />
        ))}
      </div>
    </div>
  );
}

function MetricRow({
  label,
  chunks,
  sessions,
  metric,
}: {
  label: string;
  chunks?: number;
  sessions?: number;
  metric?: SessionAnchorRagMetricBucket;
}) {
  return (
    <tr>
      <td className="px-3 py-2 font-medium">{label}</td>
      <td className="px-3 py-2 font-mono">{chunks ?? 0}</td>
      <td className="px-3 py-2 font-mono">{sessions ?? 0}</td>
      <td className="px-3 py-2 font-mono">
        {metric ? `${(metric.hit_rate * 100).toFixed(1)}%` : "0.0%"}
      </td>
      <td className="px-3 py-2 font-mono text-muted-foreground">
        {metric ? `${metric.latency_ms.p50 ?? "—"} / ${metric.latency_ms.p99 ?? "—"} ms` : "—"}
      </td>
    </tr>
  );
}

function FallbackBar({
  mode,
  metric,
}: {
  mode: string;
  metric?: SessionAnchorRagMetricBucket;
}) {
  const distribution = metric?.fallback_distribution ?? {};
  const total = Object.values(distribution).reduce((sum, value) => sum + value, 0);
  return (
    <div className="grid gap-2 sm:grid-cols-[72px_1fr_96px] sm:items-center">
      <span className="font-mono text-xs text-muted-foreground">{mode}</span>
      <div className="flex h-2 overflow-hidden rounded-full bg-muted">
        {total === 0 ? (
          <div className="h-full w-full bg-emerald-400/70" />
        ) : (
          FALLBACK_ORDER.map((reason) => {
            const count = distribution[reason] ?? 0;
            if (count === 0) return null;
            return (
              <div
                key={reason}
                className={cn("h-full", FALLBACK_TONE[reason] ?? "bg-muted-foreground")}
                style={{ width: `${Math.max(4, (count / total) * 100)}%` }}
                aria-label={`${mode} ${reason} ${count}`}
              />
            );
          })
        )}
      </div>
      <span className="font-mono text-[11px] text-muted-foreground">
        {total === 0 ? "no fallback" : `${total} fallback`}
      </span>
    </div>
  );
}

function MetricTile({
  label,
  value,
  compact = false,
}: {
  label: string;
  value: string;
  compact?: boolean;
}) {
  return (
    <div className="rounded-md border bg-card/50 p-3">
      <p className="text-[10px] font-medium uppercase text-muted-foreground">
        {label}
      </p>
      <p
        className={cn(
          "mt-1 font-mono font-bold",
          compact ? "break-all text-xs" : "text-lg",
        )}
      >
        {value}
      </p>
    </div>
  );
}
