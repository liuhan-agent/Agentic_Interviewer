"use client";

import { useEffect, useState } from "react";
import { Database, TrendingUp } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { getRagEval, type RagEvalResponse } from "@/lib/api/admin";

type Phase =
  | { kind: "loading" }
  | { kind: "ready"; data: RagEvalResponse }
  | { kind: "error"; message: string };

const WINDOWS = ["24h", "7d", "30d"] as const;

export function RagEvalPanel() {
  const [window, setWindow] = useState<string>("7d");
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });

  useEffect(() => {
    const ctrl = new AbortController();
    setPhase({ kind: "loading" });
    getRagEval({ since: window }, ctrl.signal)
      .then((data) => {
        if (!ctrl.signal.aborted) setPhase({ kind: "ready", data });
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setPhase({ kind: "error", message: err instanceof Error ? err.message : String(err) });
      });
    return () => ctrl.abort();
  }, [window]);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-sky-400" />
            <CardTitle className="text-base">知识 RAG 评测</CardTitle>
          </div>
          <div className="flex gap-1">
            {WINDOWS.map((w) => (
              <button
                key={w}
                onClick={() => setWindow(w)}
                className={[
                  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors",
                  window === w
                    ? "bg-primary text-primary-foreground"
                    : "bg-muted text-muted-foreground hover:bg-muted/80",
                ].join(" ")}
              >
                {w}
              </button>
            ))}
          </div>
        </div>
        <CardDescription>
          对比有/无 RAG 检索信号时的评分分布，作为检索质量的相关性观察。
        </CardDescription>
      </CardHeader>
      <CardContent>
        {phase.kind === "loading" && (
          <div className="space-y-3">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-24 w-full" />
          </div>
        )}

        {phase.kind === "error" && (
          <p className="text-sm text-destructive">{phase.message}</p>
        )}

        {phase.kind === "ready" && <RagEvalBody data={phase.data} />}
      </CardContent>
    </Card>
  );
}

function RagEvalBody({ data }: { data: RagEvalResponse }) {
  if (data.total_evaluator_traces === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        所选时间窗口内无 evaluator trace 数据。
      </p>
    );
  }

  const dims = Object.entries(data.per_dimension).sort(
    ([, a], [, b]) => (b.with + b.without) - (a.with + a.without),
  );

  return (
    <div className="space-y-4">
      <div className="grid gap-3 md:grid-cols-4">
        <MetricTile label="总评估轮次" value={String(data.total_evaluator_traces)} />
        <MetricTile
          label="检索命中率"
          value={`${(data.retrieval_rate * 100).toFixed(1)}%`}
          hint={`${data.with_retrieval} / ${data.total_evaluator_traces}`}
        />
        <MetricTile
          label="有检索均分"
          value={data.avg_score_with_retrieval.toFixed(2)}
          hint={`${data.with_retrieval} 轮`}
        />
        <MetricTile
          label="无检索均分"
          value={data.avg_score_without_retrieval.toFixed(2)}
          hint={`${data.without_retrieval} 轮`}
        />
      </div>

      <div className="flex items-center gap-2 rounded-md border bg-card/50 p-3">
        <TrendingUp className={`h-4 w-4 ${data.score_delta >= 0 ? "text-emerald-400" : "text-red-400"}`} />
        <div className="text-sm">
          <span>
            检索相关分数差异：
            <span className={`ml-1 font-mono font-bold ${data.score_delta >= 0 ? "text-emerald-400" : "text-red-400"}`}>
              {data.score_delta >= 0 ? "+" : ""}{data.score_delta.toFixed(2)}
            </span>
          </span>
          <p className="mt-0.5 text-[11px] text-muted-foreground">
            这是相关性指标，不代表单独的因果归因。
          </p>
        </div>
      </div>

      {dims.length > 0 && (
        <div>
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            按维度分布
          </p>
          <div className="space-y-1.5">
            {dims.map(([dim, counts]) => {
              const total = counts.with + counts.without;
              const rate = total > 0 ? counts.with / total : 0;
              return (
                <div key={dim} className="flex items-center gap-3 text-xs">
                  <span className="w-32 truncate font-mono">{dim}</span>
                  <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full rounded-full bg-sky-400"
                      style={{ width: `${rate * 100}%` }}
                    />
                  </div>
                  <span className="w-16 text-right text-muted-foreground">
                    {(rate * 100).toFixed(0)}%
                  </span>
                  <Badge variant="outline" className="text-[10px]">
                    {counts.with}/{total}
                  </Badge>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function MetricTile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <div className="rounded-md border bg-card/50 p-3">
      <p className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="mt-1 font-mono text-lg font-bold">{value}</p>
      {hint && <p className="text-[10px] text-muted-foreground">{hint}</p>}
    </div>
  );
}
