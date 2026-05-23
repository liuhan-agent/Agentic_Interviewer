"use client";

import { useEffect, useState } from "react";
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
  getSessionAnchorSessions,
  type DeleteSessionAnchorDataResponse,
  type SessionAnchorSessionRow,
  type SessionAnchorSessionsResponse,
} from "@/lib/api/admin";
import { cn } from "@/lib/utils";

type Phase =
  | { kind: "loading" }
  | { kind: "ready"; data: SessionAnchorSessionsResponse }
  | { kind: "error"; message: string };

const SOURCE_LABELS: Record<string, string> = {
  resume: "简历",
  self_intro: "自我介绍",
};

const MODE_LABELS: Record<string, string> = {
  A: "简历：项目结构切片",
  B: "简历：章节切片",
  C: "简历：轻量切片",
  D: "简历：过短跳过",
  SI: "自我介绍卡片",
  unknown: "未知策略",
};

const STATUS_LABELS: Record<string, string> = {
  primary: "primary",
  shadow: "shadow",
  off: "off",
  sampled_out: "sampled_out",
  unknown: "unknown",
};

const FALLBACK_LABELS: Record<string, string> = {
  low_score: "低分",
  timeout: "超时",
  empty: "空结果",
  not_ready: "未就绪",
  skipped: "跳过",
  sampled_out: "采样跳过",
  error: "异常",
};

export function CandidateAnchorRagCard() {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });
  const [refreshKey, setRefreshKey] = useState(0);
  const [selectedSession, setSelectedSession] =
    useState<SessionAnchorSessionRow | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmText, setConfirmText] = useState("");
  const [deleteResult, setDeleteResult] =
    useState<DeleteSessionAnchorDataResponse | null>(null);
  const [deleteError, setDeleteError] = useState("");
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const ctrl = new AbortController();
    setPhase((prev) => (prev.kind === "ready" ? prev : { kind: "loading" }));
    getSessionAnchorSessions({ since: "24h" }, ctrl.signal)
      .then((data) => {
        if (!ctrl.signal.aborted) {
          setPhase({ kind: "ready", data });
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

  const selectedSessionId = selectedSession?.session_id ?? "";
  const canDelete = selectedSessionId.length > 0 && confirmText === selectedSessionId;

  async function handleDelete() {
    if (!canDelete || !selectedSession) return;
    setDeleting(true);
    setDeleteError("");
    try {
      const result = await deleteSessionAnchorData(selectedSession.session_id);
      setDeleteResult(result);
      setConfirmOpen(false);
      setConfirmText("");
      setSelectedSession(null);
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
                候选人资料召回（24 小时）
              </CardTitle>
              <CardDescription className="mt-1">
                观察简历与自我介绍的切片、向量化和召回命中。一行是一场最近 24 小时创建的面试 session；资料覆盖来自 session_anchor_chunks，召回表现来自 ask_question trace。
              </CardDescription>
            </div>
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="font-mono">
                24h
              </Badge>
              <Button
                size="icon"
                variant="outline"
                aria-label="刷新候选人资料召回"
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
              <Skeleton className="h-64 w-full" />
            </div>
          )}

          {phase.kind === "error" && (
            <p className="text-sm text-destructive">{phase.message}</p>
          )}

          {phase.kind === "ready" && (
            <CandidateAnchorSessionsBody
              data={phase.data}
              onDeleteSession={(session) => {
                setSelectedSession(session);
                setConfirmText("");
                setDeleteError("");
                setConfirmOpen(true);
              }}
            />
          )}

          {deleteResult && (
            <p className="border-t border-border/50 pt-3 text-xs text-muted-foreground">
              已处理 {deleteResult.session_id}：切片 {deleteResult.chunks_deleted}，
              artifact {deleteResult.resume_artifacts_deleted}，trace {deleteResult.traces_scrubbed}。
            </p>
          )}
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
              <span className="ml-1 break-all font-mono text-foreground">{selectedSessionId}</span>
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

function CandidateAnchorSessionsBody({
  data,
  onDeleteSession,
}: {
  data: SessionAnchorSessionsResponse;
  onDeleteSession: (session: SessionAnchorSessionRow) => void;
}) {
  const summary = data.summary;
  const denominator = Math.max(1, data.session_count);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <MetricTile label="最近 24h session" value={String(data.session_count)} />
        <MetricTile
          label="有资料切片"
          value={`${summary.indexed_sessions}/${denominator}`}
          detail={formatPercent(summary.indexed_session_rate)}
        />
        <MetricTile
          label="有召回命中"
          value={`${summary.hit_sessions}/${denominator}`}
          detail={formatPercent(summary.hit_session_rate)}
        />
        <MetricTile
          label="有召回兜底"
          value={`${summary.fallback_sessions}/${denominator}`}
          detail={formatPercent(summary.fallback_session_rate)}
        />
      </div>

      {data.sessions.length === 0 ? (
        <p className="rounded-md border bg-muted/10 p-4 text-sm text-muted-foreground">
          最近 24 小时暂无面试 session。开始一场面试后会出现可追踪的资料召回记录。
        </p>
      ) : (
        <div className="overflow-x-auto rounded-md border">
          <table className="w-full min-w-[1280px] text-left text-xs">
            <thead className="bg-muted/60 text-muted-foreground">
              <tr>
                <th className="px-3 py-2 font-medium">Session</th>
                <th className="px-3 py-2 font-medium">候选人 / 岗位</th>
                <th className="px-3 py-2 font-medium">资料覆盖</th>
                <th className="px-3 py-2 font-medium">切片策略</th>
                <th className="px-3 py-2 font-medium">切片数</th>
                <th className="px-3 py-2 font-medium">召回尝试</th>
                <th className="px-3 py-2 font-medium">命中次数</th>
                <th className="px-3 py-2 font-medium">召回命中</th>
                <th className="px-3 py-2 font-medium">延迟 p50 / p99</th>
                <th className="px-3 py-2 font-medium">兜底原因</th>
                <th className="px-3 py-2 font-medium">状态</th>
                <th className="px-3 py-2 font-medium">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {data.sessions.map((session) => (
                <SessionAnchorRow
                  key={session.session_id}
                  session={session}
                  onDeleteSession={onDeleteSession}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function SessionAnchorRow({
  session,
  onDeleteSession,
}: {
  session: SessionAnchorSessionRow;
  onDeleteSession: (session: SessionAnchorSessionRow) => void;
}) {
  return (
    <tr className="align-top">
      <td className="max-w-[180px] px-3 py-3">
        <div className="break-all font-mono text-[11px] text-foreground">
          {session.session_id}
        </div>
        <div className="mt-1 text-[10px] text-muted-foreground">
          {formatDate(session.created_at)}
        </div>
      </td>
      <td className="px-3 py-3">
        <div className="max-w-[160px] font-medium text-foreground">
          {session.candidate_name || "未记录候选人"}
        </div>
        <div className="mt-1 max-w-[160px] text-muted-foreground">
          {session.job_title || "未记录岗位"}
        </div>
      </td>
      <td className="px-3 py-3">
        <div className="flex flex-wrap gap-1.5">
          {session.has_resume_chunks && <SourceChip label="简历" />}
          {session.has_self_intro_chunks && <SourceChip label="自我介绍" />}
          {!session.has_resume_chunks && !session.has_self_intro_chunks && (
            <SourceChip label="无资料" muted />
          )}
        </div>
      </td>
      <td className="px-3 py-3">
        <div className="flex max-w-[220px] flex-wrap gap-1.5">
          {session.chunker_modes.length > 0 ? (
            session.chunker_modes.map((mode) => (
              <MiniPill key={mode}>{formatMode(mode)}</MiniPill>
            ))
          ) : (
            <MiniPill muted>无</MiniPill>
          )}
        </div>
        {session.embedding_model_versions.length > 0 && (
          <div className="mt-1 max-w-[220px] break-all font-mono text-[10px] text-muted-foreground">
            {session.embedding_model_versions.join(" / ")}
          </div>
        )}
      </td>
      <td className="px-3 py-3 font-mono">{session.total_chunks}</td>
      <td className="px-3 py-3 font-mono">{session.retrieval_attempts}</td>
      <td className="px-3 py-3 font-mono">{session.hit_count}</td>
      <td className="px-3 py-3 font-mono">
        {formatPercent(session.hit_rate)}
        <div className="mt-1 text-[10px] text-muted-foreground">
          {formatSourceHits(session.source_hit_counts)}
        </div>
      </td>
      <td className="px-3 py-3 font-mono text-muted-foreground">
        {formatLatency(session.latency_ms)}
      </td>
      <td className="px-3 py-3">
        <div className="flex max-w-[180px] flex-wrap gap-1.5">
          {formatFallbacks(session.fallback_reasons)}
        </div>
      </td>
      <td className="px-3 py-3">
        <div className="flex max-w-[180px] flex-wrap gap-1.5">
          <MiniPill>{session.session_status || "unknown"}</MiniPill>
          {Object.entries(session.rag_status_distribution || {}).map(([status, count]) => (
            <MiniPill key={status} muted={status === "off" || status === "sampled_out"}>
              {STATUS_LABELS[status] ?? status} {count}
            </MiniPill>
          ))}
        </div>
        {session.last_trace_at && (
          <div className="mt-1 text-[10px] text-muted-foreground">
            trace {formatDate(session.last_trace_at)}
          </div>
        )}
      </td>
      <td className="px-3 py-3">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 px-2 text-xs text-destructive hover:text-destructive"
          aria-label="行级删除资料数据"
          onClick={() => onDeleteSession(session)}
        >
          <Trash2 className="h-3.5 w-3.5" />
          删除资料数据
        </Button>
      </td>
    </tr>
  );
}

function SourceChip({ label, muted = false }: { label: string; muted?: boolean }) {
  return (
    <span
      className={cn(
        "rounded-full border px-2 py-0.5 text-[11px]",
        muted
          ? "border-border/60 text-muted-foreground"
          : "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
      )}
    >
      {label}
    </span>
  );
}

function MiniPill({
  children,
  muted = false,
}: {
  children: React.ReactNode;
  muted?: boolean;
}) {
  return (
    <span
      className={cn(
        "rounded-md border px-1.5 py-0.5 text-[10px]",
        muted
          ? "border-border/60 text-muted-foreground"
          : "border-border bg-muted/20 text-foreground",
      )}
    >
      {children}
    </span>
  );
}

function MetricTile({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="rounded-md border bg-card/50 p-3">
      <p className="text-[10px] font-medium text-muted-foreground">{label}</p>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="font-mono text-lg font-bold">{value}</span>
        {detail && (
          <span className="font-mono text-xs text-muted-foreground">{detail}</span>
        )}
      </div>
    </div>
  );
}

function formatMode(mode: string): string {
  return MODE_LABELS[mode] ?? mode;
}

function formatPercent(value: number): string {
  if (!Number.isFinite(value)) return "0%";
  return `${Math.round(value * 100)}%`;
}

function formatDate(value?: string | null): string {
  if (!value) return "无时间";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatLatency(latency: SessionAnchorSessionRow["latency_ms"]): string {
  const p50 = latency?.p50 ?? null;
  const p99 = latency?.p99 ?? null;
  if (p50 === null && p99 === null) return "无";
  return `${p50 ?? "无"} / ${p99 ?? "无"} ms`;
}

function formatSourceHits(sourceHits: Record<string, number>): string {
  const entries = Object.entries(sourceHits || {}).filter(([, count]) => count > 0);
  if (entries.length === 0) return "无来源命中";
  return entries
    .sort((a, b) => b[1] - a[1])
    .map(([source, count]) => `${SOURCE_LABELS[source] ?? source} ${count}`)
    .join(" / ");
}

function formatFallbacks(reasons: Record<string, number>): React.ReactNode {
  const entries = Object.entries(reasons || {}).filter(([, count]) => count > 0);
  if (entries.length === 0) return <MiniPill muted>无兜底</MiniPill>;
  return entries
    .sort((a, b) => b[1] - a[1])
    .map(([reason, count]) => (
      <MiniPill key={reason} muted={reason === "sampled_out"}>
        {FALLBACK_LABELS[reason] ?? reason} {count}
      </MiniPill>
    ));
}
