"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, ArrowRight, CheckCircle2, GitBranch, Loader2, XCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getWorkflowChain,
  type WorkflowChainResponse,
  type WorkflowTurn,
} from "@/lib/api/admin";

type Phase =
  | { kind: "loading" }
  | { kind: "ready"; data: WorkflowChainResponse }
  | { kind: "error"; message: string };

export function WorkflowChainPanel({ sessionId }: { sessionId: string }) {
  const [phase, setPhase] = useState<Phase>({ kind: "loading" });

  useEffect(() => {
    const ctrl = new AbortController();
    setPhase({ kind: "loading" });
    getWorkflowChain(sessionId, ctrl.signal)
      .then((data) => {
        if (!ctrl.signal.aborted) setPhase({ kind: "ready", data });
      })
      .catch((err) => {
        if (ctrl.signal.aborted) return;
        setPhase({ kind: "error", message: err instanceof Error ? err.message : String(err) });
      });
    return () => ctrl.abort();
  }, [sessionId]);

  if (phase.kind === "loading") {
    return (
      <div className="space-y-3">
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (phase.kind === "error") {
    return (
      <Card className="border-destructive/40 bg-destructive/5">
        <CardContent className="pt-6 text-sm text-destructive">
          <p className="font-medium">Workflow 决策链加载失败</p>
          <p className="text-muted-foreground">{phase.message}</p>
        </CardContent>
      </Card>
    );
  }

  const { data } = phase;

  if (data.turn_count === 0) {
    return (
      <Card>
        <CardContent className="pt-6 text-sm text-muted-foreground">
          暂无决策链数据。面试可能仍在进行中，或尚未生成 trace。
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <GitBranch className="h-4 w-4 text-emerald-400" />
          <CardTitle className="text-base">Workflow 决策链</CardTitle>
        </div>
        <CardDescription>
          每轮面试的完整决策流程：Director 选择 → Evaluator 评分 → Reward 计算 → Verifier 复核
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {data.turns.map((turn) => (
          <TurnChainCard key={turn.turn_idx} turn={turn} />
        ))}
      </CardContent>
    </Card>
  );
}

function TurnChainCard({ turn }: { turn: WorkflowTurn }) {
  return (
    <div className="rounded-lg border bg-card/50 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="font-mono text-xs">
          Turn {turn.turn_idx}
        </Badge>
        {turn.dimension && (
          <Badge variant="secondary" className="text-xs">
            {turn.dimension}
          </Badge>
        )}
      </div>

      <div className="grid gap-2 md:grid-cols-4">
        <StepTile
          label="Director"
          icon={<GitBranch className="h-3 w-3" />}
          available={!!turn.director}
        >
          {turn.director ? (
            <>
              <p className="font-mono text-xs">{turn.director.action_label ?? "—"}</p>
              {turn.director.exploration && (
                <p className="text-[10px] text-muted-foreground">
                  探索: {turn.director.exploration}
                </p>
              )}
              {turn.director.target_difficulty && (
                <p className="text-[10px] text-muted-foreground">
                  难度: {turn.director.target_difficulty}
                </p>
              )}
            </>
          ) : (
            <p className="text-[10px] text-muted-foreground">无数据</p>
          )}
        </StepTile>

        <StepTile
          label="Evaluator"
          icon={<CheckCircle2 className="h-3 w-3" />}
          available={!!turn.evaluator}
        >
          {turn.evaluator ? (
            <>
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-bold">
                  {turn.evaluator.score?.toFixed(1) ?? "—"}
                </span>
                {turn.evaluator.passed != null && (
                  turn.evaluator.passed
                    ? <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                    : <XCircle className="h-3 w-3 text-red-400" />
                )}
              </div>
              {turn.evaluator.immediate_reward != null && (
                <p className="text-[10px] text-muted-foreground">
                  即时 reward: {turn.evaluator.immediate_reward.toFixed(3)}
                </p>
              )}
            </>
          ) : (
            <p className="text-[10px] text-muted-foreground">无数据</p>
          )}
        </StepTile>

        <StepTile
          label="Reward"
          icon={<ArrowRight className="h-3 w-3" />}
          available={!!turn.reward}
        >
          {turn.reward ? (
            turn.reward.skipped ? (
              <p className="text-[10px] text-amber-400">
                跳过: {turn.reward.skip_reason ?? "—"}
              </p>
            ) : (
              <p className="font-mono text-xs">
                {turn.reward.reward_value?.toFixed(3) ?? "—"}
              </p>
            )
          ) : (
            <p className="text-[10px] text-muted-foreground">无数据</p>
          )}
        </StepTile>

        <StepTile
          label="Verifier"
          icon={<AlertTriangle className="h-3 w-3" />}
          available={!!turn.verifier}
        >
          {turn.verifier ? (
            <>
              {turn.verifier.overruled ? (
                <Badge variant="destructive" className="text-[10px]">已纠偏</Badge>
              ) : (
                <Badge variant="outline" className="text-[10px]">一致</Badge>
              )}
              {turn.verifier.confidence != null && (
                <p className="text-[10px] text-muted-foreground">
                  置信度: {(turn.verifier.confidence * 100).toFixed(0)}%
                </p>
              )}
            </>
          ) : (
            <p className="text-[10px] text-muted-foreground">无数据</p>
          )}
        </StepTile>
      </div>
    </div>
  );
}

function StepTile({
  label,
  icon,
  available,
  children,
}: {
  label: string;
  icon: React.ReactNode;
  available: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={[
        "rounded-md border p-2 space-y-1",
        available ? "bg-card" : "bg-muted/30 opacity-60",
      ].join(" ")}
    >
      <div className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {icon}
        {label}
      </div>
      {children}
    </div>
  );
}
