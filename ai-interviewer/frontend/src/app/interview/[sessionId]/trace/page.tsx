import type { Metadata } from "next";
import { GitBranch } from "lucide-react";

import { SessionTraceExplorer } from "@/components/admin/TraceExplorer";

type PageProps = {
  params: { sessionId: string };
};

export function generateMetadata({ params }: PageProps): Metadata {
  const short =
    params.sessionId.length > 10
      ? `${params.sessionId.slice(0, 4)}...${params.sessionId.slice(-4)}`
      : params.sessionId;
  return {
    title: `Trace ${short} · AI 面试官`,
  };
}

export default function InterviewTracePage({ params }: PageProps) {
  return (
    <section className="container max-w-6xl py-10">
      <header className="mb-8 flex flex-col gap-1">
        <div className="mb-2 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10">
            <GitBranch className="h-4 w-4 text-emerald-400" />
          </div>
          <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
            Trace Explorer
          </p>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">
          本场面试 Trace
        </h1>
        <p className="max-w-xl text-sm leading-relaxed text-muted-foreground">
          和报告、训练回放一起复盘本场面试的关键节点、问题依据和评分证据。
        </p>
      </header>
      <SessionTraceExplorer sessionId={params.sessionId} />
    </section>
  );
}
