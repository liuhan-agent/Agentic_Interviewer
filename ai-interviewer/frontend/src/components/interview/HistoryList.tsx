"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ClipboardList,
  Loader2,
  Play,
  RefreshCcw,
  RotateCcw,
  Sparkles,
  Trash2,
  XCircle,
  AlertCircle,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ProgressChart } from "@/components/interview/ProgressChart";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { deleteSession, resumeSession, getReport } from "@/lib/api/interview";
import type { DeleteSessionResponse } from "@/lib/api/types";
import {
  DEFAULT_SORT,
  jobLevelShortLabel,
  mapPollStatusToLocal,
  SORT_OPTIONS,
  STATUS_FILTER_OPTIONS,
  verdictShortLabel,
  type SortOption,
  type StatusFilterOption,
} from "@/lib/constants";
import { useToast } from "@/lib/hooks/useToast";
import {
  clearAll,
  getHistory,
  removeEntry,
  upsertEntry,
  type InterviewHistoryEntry,
  type InterviewHistoryStatus,
} from "@/lib/storage/interviewHistory";

export function HistoryList() {
  const [entries, setEntries] = useState<InterviewHistoryEntry[] | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [deletingSessionId, setDeletingSessionId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] =
    useState<InterviewHistoryEntry | null>(null);
  const [activeFilter, setActiveFilter] = useState<StatusFilterOption["id"]>("all");
  const [activeSort, setActiveSort] = useState<SortOption>(DEFAULT_SORT);
  const { toast } = useToast();

  const reload = useCallback(() => {
    setEntries(getHistory());
  }, []);

  useEffect(() => {
    reload();
    let timeoutId: ReturnType<typeof setTimeout> | null = null;
    const onStorage = (e: StorageEvent) => {
      if (e.key === "interviewHistory" || e.key === null) {
        if (timeoutId) clearTimeout(timeoutId);
        timeoutId = setTimeout(() => reload(), 500);
      }
    };
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("storage", onStorage);
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [reload]);

  const runningCount = useMemo(
    () => (entries ?? []).filter((e) => e.status === "running").length,
    [entries],
  );

  const filteredAndSorted = useMemo(() => {
    let list = entries ?? [];
    if (activeFilter !== "all") {
      list = list.filter((e) => e.status === activeFilter);
    }
    const { field, direction } = activeSort;
    const dir = direction === "asc" ? 1 : -1;
    return [...list].sort((a, b) => {
      switch (field) {
        case "overallScore":
          return compareScoreEntries(a, b, direction);
        case "lastVisitedAt":
          return dir * a.lastVisitedAt.localeCompare(b.lastVisitedAt);
        case "status":
          return dir * a.status.localeCompare(b.status);
        case "createdAt":
        default:
          return dir * a.createdAt.localeCompare(b.createdAt);
      }
    });
  }, [entries, activeFilter, activeSort]);

  const handleRemoveLocal = useCallback(
    (sessionId: string) => {
      removeEntry(sessionId);
      reload();
      toast({ title: "已从我的列表中移除" });
    },
    [reload, toast],
  );

  const handleDeleteData = useCallback(
    async () => {
      if (!deleteTarget) return;
      const sessionId = deleteTarget.sessionId;
      setDeletingSessionId(sessionId);
      try {
        const result = await deleteSession(sessionId);
        removeEntry(sessionId);
        setDeleteTarget(null);
        reload();
        toast({
          title: result.deleted ? "面试数据已删除" : "服务端数据未找到",
          description: describeDeleteSessionResult(result),
        });
      } catch (err) {
        const message = err instanceof Error ? err.message : "请稍后再试";
        toast({
          title: "删除数据失败",
          description: message,
        });
      } finally {
        setDeletingSessionId(null);
      }
    },
    [deleteTarget, reload, toast],
  );

  const handleClearAll = useCallback(() => {
    if (!entries || entries.length === 0) return;
    if (
      !window.confirm(
        `确认清空全部 ${entries.length} 条记录吗？\n\n仅会清空当前浏览器看到的列表，已完成面试的评分数据不会丢失。`,
      )
    ) {
      return;
    }
    clearAll();
    reload();
    toast({ title: "列表已清空" });
  }, [entries, reload, toast]);

  const handleRefresh = useCallback(async () => {
    if (!entries) return;
    const targets = entries.filter((e) => e.status === "running");
    if (targets.length === 0) {
      toast({ title: "当前没有进行中的面试" });
      return;
    }

    setRefreshing(true);
    let updated = 0;
    let failed = 0;
    await Promise.all(
      targets.map(async (entry) => {
        try {
          const r = await resumeSession(entry.sessionId);
          const next = mapBackendStatusToLocal(r.status);
          if (next === "done") {
            // Pull the report so we can persist the score for the card.
            try {
              const rep = await getReport(entry.sessionId);
              upsertEntry({
                sessionId: entry.sessionId,
                status: "done",
                overallScore:
                  typeof rep.final_report?.overall_score === "number"
                    ? rep.final_report.overall_score
                    : undefined,
                growthSignal:
                  typeof rep.final_report?.growth_signal === "string"
                    ? rep.final_report.growth_signal
                    : undefined,
                dimensionScores: compactDimensionScores(
                  rep.final_report?.dimension_scores,
                ),
                maxTurns:
                  typeof r.max_turns === "number" ? r.max_turns : undefined,
                overallVerdict:
                  typeof rep.final_report?.overall_verdict === "string"
                    ? rep.final_report.overall_verdict
                    : undefined,
              });
            } catch {
              upsertEntry({ sessionId: entry.sessionId, status: "done" });
            }
            updated += 1;
          } else if (next === "cancelled") {
            upsertEntry({ sessionId: entry.sessionId, status: "cancelled" });
            updated += 1;
          } else {
            upsertEntry({
              sessionId: entry.sessionId,
              maxTurns: typeof r.max_turns === "number" ? r.max_turns : undefined,
            });
          }
        } catch {
          failed += 1;
        }
      }),
    );
    reload();
    setRefreshing(false);
    if (failed === 0) {
      toast({
        title: "状态已更新",
        description: updated > 0 ? `刷新了 ${updated} 条记录。` : "暂无变化。",
      });
    } else {
      toast({
        title: "已尝试更新",
        description: `成功 ${updated} 条，${failed} 条暂时无法获取，可稍后再试。`,
      });
    }
  }, [entries, reload, toast]);

  if (entries === null) {
    return <SkeletonList />;
  }

  if (entries.length === 0) {
    return <EmptyState />;
  }

  return (
    <div className="space-y-4">
      <DeleteSessionDialog
        entry={deleteTarget}
        deleting={
          deleteTarget !== null && deletingSessionId === deleteTarget.sessionId
        }
        onOpenChange={(open) => {
          if (!open && deletingSessionId === null) {
            setDeleteTarget(null);
          }
        }}
        onConfirm={handleDeleteData}
      />

      <div className="space-y-3">
        <ProgressChart entries={entries} />

        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            共 {entries.length} 场面试
            {runningCount > 0 && (
              <>
                {" · "}
                <span className="text-amber-400">{runningCount} 场进行中</span>
              </>
            )}
            {activeFilter !== "all" && (
              <>
                {" · "}
                <span className="text-foreground/70">
                  筛选后 {filteredAndSorted.length} 条
                </span>
              </>
            )}
          </p>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              disabled={refreshing || runningCount === 0}
              className="gap-1.5"
              aria-label={
                runningCount === 0
                  ? "当前没有进行中的面试"
                  : "同步进行中面试的最新状态"
              }
            >
              {refreshing ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCcw className="h-3.5 w-3.5" />
              )}
              刷新状态
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={handleClearAll}
              className="gap-1.5 text-muted-foreground hover:text-destructive"
            >
              <Trash2 className="h-3.5 w-3.5" />
              清空
            </Button>
          </div>
        </div>

        <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/[0.04] p-3 text-xs text-muted-foreground">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
          <p>
            会话继续访问凭证仅保存在当前标签页会话中；导出历史不会包含 token。
          </p>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex gap-1 rounded-lg bg-secondary/30 p-0.5">
            {STATUS_FILTER_OPTIONS.map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => setActiveFilter(opt.id)}
                className={`rounded-md px-3 py-1.5 text-xs transition-colors ${
                  activeFilter === opt.id
                    ? "bg-background text-foreground shadow-sm"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>

          <select
            value={`${activeSort.field}:${activeSort.direction}`}
            onChange={(e) => {
              const found = SORT_OPTIONS.find(
                (o) => `${o.field}:${o.direction}` === e.target.value,
              );
              if (found) setActiveSort(found);
            }}
            className="h-8 rounded-md border border-input bg-background px-2 text-xs text-foreground shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            aria-label="排序方式"
          >
            {SORT_OPTIONS.map((opt) => (
              <option
                key={`${opt.field}:${opt.direction}`}
                value={`${opt.field}:${opt.direction}`}
                className="bg-background text-foreground"
              >
                {opt.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {filteredAndSorted.length === 0 && activeFilter !== "all" ? (
        <FilteredEmptyState onClear={() => setActiveFilter("all")} />
      ) : (
        <ul className="space-y-3">
          <AnimatePresence initial={false}>
            {filteredAndSorted.map((entry, idx) => (
              <motion.li
                key={entry.sessionId}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: -16 }}
                transition={{ duration: 0.25, delay: idx * 0.03 }}
              >
                <ContextMenu>
                  <ContextMenuTrigger>
                    <HistoryCard
                      entry={entry}
                      deleting={deletingSessionId === entry.sessionId}
                      onRemoveLocal={handleRemoveLocal}
                      onDeleteData={setDeleteTarget}
                    />
                  </ContextMenuTrigger>
                  <ContextMenuContent>
                    <ContextMenuItem
                      onClick={() => {
                        navigator.clipboard?.writeText(entry.sessionId);
                        toast({ title: "已复制 Session ID" });
                      }}
                    >
                      复制会话 ID
                    </ContextMenuItem>
                    <ContextMenuItem
                      onClick={() => {
                        const safeEntry = { ...entry };
                        delete safeEntry.sessionToken;
                        delete safeEntry.sessionTokenExpiresAt;
                        const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(safeEntry, null, 2));
                        const dlAnchorElem = document.createElement("a");
                        dlAnchorElem.setAttribute("href", dataStr);
                        dlAnchorElem.setAttribute("download", `interview_${entry.sessionId}.json`);
                        dlAnchorElem.click();
                      }}
                    >
                      导出这条记录（不含凭证）
                    </ContextMenuItem>
                  </ContextMenuContent>
                </ContextMenu>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </div>
  );
}

function compareScoreEntries(
  a: InterviewHistoryEntry,
  b: InterviewHistoryEntry,
  direction: "asc" | "desc",
): number {
  const hasAScore = typeof a.overallScore === "number";
  const hasBScore = typeof b.overallScore === "number";
  if (hasAScore !== hasBScore) return hasAScore ? -1 : 1;
  if (hasAScore && hasBScore && a.overallScore !== b.overallScore) {
    return direction === "asc"
      ? a.overallScore! - b.overallScore!
      : b.overallScore! - a.overallScore!;
  }
  return b.createdAt.localeCompare(a.createdAt);
}

function describeDeleteSessionResult(result: DeleteSessionResponse): string {
  const sessionsDeleted = result.sessions_deleted;
  const tracesDeleted = result.traces_deleted;
  const outcomesDeleted = result.outcomes_deleted;
  if (!result.deleted) {
    return result.checkpoint_deleted
      ? "服务端没有找到可删除的数据；已清理运行恢复状态，并从本机列表移除。"
      : "服务端没有找到可删除的数据；已从本机列表移除。";
  }

  const checkpointText =
    result.checkpoint_deleted === false
      ? "运行恢复状态暂未清理。"
      : result.checkpoint_deleted
        ? "运行恢复状态已清理。"
        : "";
  return `服务端已删除：会话 ${sessionsDeleted} 条、Trace ${tracesDeleted} 条、结果 ${outcomesDeleted} 条。${checkpointText}`;
}

function FilteredEmptyState({ onClear }: { onClear: () => void }) {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center gap-3 py-8 text-center text-sm">
        <p className="font-medium">当前筛选下没有面试记录</p>
        <p className="max-w-sm text-muted-foreground">
          可以切回“全部”查看其它状态的面试，或先开始一场新的练习。
        </p>
        <Button type="button" variant="outline" size="sm" onClick={onClear}>
          查看全部
        </Button>
      </CardContent>
    </Card>
  );
}

function HistoryCard({
  entry,
  deleting,
  onRemoveLocal,
  onDeleteData,
}: {
  entry: InterviewHistoryEntry;
  deleting: boolean;
  onRemoveLocal: (sessionId: string) => void;
  onDeleteData: (entry: InterviewHistoryEntry) => void;
}) {
  const primaryHref =
    entry.status === "done"
      ? `/interview/${entry.sessionId}/report`
      : `/interview/${entry.sessionId}`;
  const primaryLabel =
    entry.status === "done"
      ? "查看报告"
      : entry.status === "cancelled"
        ? "查看记录"
        : entry.status === "failed"
          ? "查看原因"
        : "继续面试";

  return (
    <Card className="card-hover group transition-all">
      <CardHeader className="flex flex-row items-start justify-between gap-3 space-y-0 pb-3">
        <div className="min-w-0 flex-1">
          <CardTitle className="flex items-center gap-2 text-base">
            <span className="truncate">{entry.jdTitle}</span>
            <StatusBadge status={entry.status} />
          </CardTitle>
          <p className="mt-1 truncate text-xs text-muted-foreground">
            {entry.candidateName ? (
              <>
                <span className="text-foreground/70">{entry.candidateName}</span>
                {entry.jobLevel && (
                  <span className="ml-1.5 text-muted-foreground/70">
                    · {jobLevelLabel(entry.jobLevel)}
                  </span>
                )}
                {" · "}
              </>
            ) : null}
            <span className="font-mono">{shortId(entry.sessionId)}</span>
            <span className="mx-1 text-muted-foreground/40">·</span>
            <span aria-label={new Date(entry.createdAt).toLocaleString()}>
              {formatRelative(entry.createdAt)}
            </span>
          </p>
        </div>

        {typeof entry.overallScore === "number" && (
          <div className="flex shrink-0 flex-col items-end">
            <span className="font-mono text-2xl font-bold tabular-nums">
              {entry.overallScore.toFixed(1)}
              <span className="ml-0.5 text-xs font-normal text-muted-foreground">
                /10
              </span>
            </span>
            {(entry.growthSignal || entry.overallVerdict) && (
              <span className="mt-0.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                {formatVerdictShort(entry.growthSignal ?? entry.overallVerdict ?? "")}
              </span>
            )}
          </div>
        )}
      </CardHeader>

      <CardContent className="flex flex-wrap items-center justify-between gap-3 pt-0">
        <div className="flex flex-wrap gap-1">
          {(entry.rubricDimensions ?? []).slice(0, 4).map((dim) => (
            <Badge key={dim} variant="outline" className="font-mono text-[10px]">
              {dim}
            </Badge>
          ))}
        </div>

        <div className="flex items-center gap-1.5">
          <Button
            asChild
            size="sm"
            variant={entry.status === "running" ? "default" : "outline"}
            className={
              entry.status === "running"
                ? "gap-1 bg-emerald-600 hover:bg-emerald-500 text-white"
                : "gap-1"
            }
          >
            <Link href={primaryHref}>
              {entry.status === "done" ? (
                <ClipboardList className="h-3.5 w-3.5" />
              ) : entry.status === "failed" ? (
                <AlertCircle className="h-3.5 w-3.5" />
              ) : (
                <Play className="h-3.5 w-3.5" />
              )}
              {primaryLabel}
              <ArrowRight className="h-3 w-3 transition-transform group-hover:translate-x-0.5" />
            </Link>
          </Button>
          {entry.status === "done" && (
            <Button asChild size="sm" variant="secondary" className="gap-1">
              <Link href={`/interview/${entry.sessionId}/replay`}>
                <RotateCcw className="h-3.5 w-3.5" />
                训练回放
              </Link>
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="gap-1 text-muted-foreground"
            onClick={() => onRemoveLocal(entry.sessionId)}
            aria-label="只从当前浏览器列表中移除，不删除后端数据"
          >
            <XCircle className="h-3.5 w-3.5" />
            从列表移除
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="gap-1 text-muted-foreground hover:text-destructive"
            onClick={() => onDeleteData(entry)}
            disabled={deleting}
            aria-label="删除后端保存的面试数据"
          >
            {deleting ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Trash2 className="h-3.5 w-3.5" />
            )}
            删除数据
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function DeleteSessionDialog({
  entry,
  deleting,
  onOpenChange,
  onConfirm,
}: {
  entry: InterviewHistoryEntry | null;
  deleting: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog open={entry !== null} onOpenChange={onOpenChange}>
      <DialogContent className="border-red-500/30 sm:max-w-[520px]">
        <DialogHeader className="space-y-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-red-500/10 text-red-300">
            <AlertTriangle className="h-5 w-5" />
          </div>
          <DialogTitle>删除这场面试的数据？</DialogTitle>
          <DialogDescription>
            这不是从列表里隐藏记录，而是删除后端保存的面试数据。
          </DialogDescription>
        </DialogHeader>

        {entry && (
          <div className="space-y-4">
            <div className="rounded-lg border border-border/80 bg-muted/30 p-4">
              <p className="truncate text-sm font-semibold text-foreground">
                {entry.jdTitle || "未命名面试"}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                {entry.candidateName ? `${entry.candidateName} · ` : ""}
                {entry.jobLevel ? `${jobLevelLabel(entry.jobLevel)} · ` : ""}
                <span className="font-mono">{shortId(entry.sessionId)}</span>
                <span className="mx-1 text-muted-foreground/40">·</span>
                {formatRelative(entry.createdAt)}
              </p>
            </div>

            <div className="rounded-lg border border-red-500/20 bg-red-500/5 p-4 text-sm">
              <p className="font-medium text-red-200">删除后会发生：</p>
              <ul className="mt-2 space-y-1.5 text-muted-foreground">
                <li>无法继续面试</li>
                <li>无法回看本场面试报告与反馈</li>
                <li>本地“我的面试”列表也会移除这条记录</li>
              </ul>
              <p className="mt-3 text-xs text-muted-foreground">
                简历解析缓存不会被删除，它会按当前 24 小时缓存策略自动过期。
              </p>
            </div>
          </div>
        )}

        <DialogFooter className="gap-2 sm:gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={deleting}
          >
            取消，保留数据
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={onConfirm}
            disabled={deleting || entry === null}
            className="gap-1.5"
          >
            {deleting ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Trash2 className="h-4 w-4" />
            )}
            永久删除数据
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function StatusBadge({ status }: { status: InterviewHistoryStatus }) {
  if (status === "running") {
    return (
      <Badge variant="warn" className="gap-1">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-60" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-400" />
        </span>
        进行中
      </Badge>
    );
  }
  if (status === "done") {
    return (
      <Badge variant="success" className="gap-1">
        <CheckCircle2 className="h-3 w-3" />
        已完成
      </Badge>
    );
  }
  if (status === "failed") {
    return (
      <Badge variant="destructive" className="gap-1">
        <AlertCircle className="h-3 w-3" />
        需处理
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" className="gap-1 text-muted-foreground">
      <XCircle className="h-3 w-3" />
      已取消
    </Badge>
  );
}

function EmptyState() {
  return (
    <Card className="border-dashed">
      <CardContent className="flex flex-col items-center gap-4 py-16 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-500/10">
          <Sparkles className="h-6 w-6 text-emerald-400" />
        </div>
        <div>
          <h3 className="text-base font-semibold">还没有练习记录</h3>
          <p className="mt-1 max-w-sm text-sm text-muted-foreground">
            来一场 AI 模拟面试吧。完成后可以随时回到这里查看评分与反馈，
            对比自己每一次的进步。
          </p>
        </div>
        <Button asChild className="gap-2 bg-emerald-600 hover:bg-emerald-500 text-white">
          <Link href="/interview/setup">
            开始第一场面试
            <ArrowRight className="h-4 w-4" />
          </Link>
        </Button>
      </CardContent>
    </Card>
  );
}

function SkeletonList() {
  return (
    <div className="space-y-3">
      {[0, 1, 2].map((i) => (
        <Card key={i}>
          <CardContent className="h-24 animate-pulse" />
        </Card>
      ))}
    </div>
  );
}

function shortId(id: string): string {
  if (id.length <= 12) return id;
  return `${id.slice(0, 4)}…${id.slice(-4)}`;
}

const jobLevelLabel = jobLevelShortLabel;

function compactDimensionScores(
  scores: unknown,
): Record<string, number> | undefined {
  if (!scores || typeof scores !== "object" || Array.isArray(scores)) {
    return undefined;
  }
  const out: Record<string, number> = {};
  for (const [dimension, value] of Object.entries(scores)) {
    if (!value || typeof value !== "object" || Array.isArray(value)) continue;
    const score = (value as { score?: unknown }).score;
    if (typeof score === "number" && Number.isFinite(score)) {
      out[dimension] = score;
    }
  }
  return Object.keys(out).length > 0 ? out : undefined;
}

function formatRelative(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "未知时间";
  const diffMs = Date.now() - d.getTime();
  const sec = Math.round(diffMs / 1000);
  if (sec < 60) return "刚刚";
  const min = Math.round(sec / 60);
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.round(hr / 24);
  if (day < 30) return `${day} 天前`;
  return d.toLocaleDateString();
}

const formatVerdictShort = verdictShortLabel;
const mapBackendStatusToLocal = mapPollStatusToLocal;
