import type { Metadata } from "next";
import { RotateCcw } from "lucide-react";

import { ReplayView } from "@/components/interview/ReplayView";

type PageProps = {
  params: { sessionId: string };
};

export function generateMetadata({ params }: PageProps): Metadata {
  const short =
    params.sessionId.length > 10
      ? `${params.sessionId.slice(0, 4)}…${params.sessionId.slice(-4)}`
      : params.sessionId;
  return {
    title: `训练回放 ${short} · 问镜`,
  };
}

export default function InterviewReplayPage({ params }: PageProps) {
  return (
    <section className="container max-w-3xl py-10">
      <header className="mb-8 flex flex-col gap-1">
        <div className="mb-2 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10">
            <RotateCcw className="h-4 w-4 text-emerald-400" />
          </div>
          <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
            训练回放
          </p>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">
          复盘这场面试
        </h1>
        <p className="max-w-xl text-sm leading-relaxed text-muted-foreground">
          按轮次回看问题、回答、评分依据和后续练习建议，把一次面试变成下一次提升的路线图。
        </p>
      </header>
      <ReplayView sessionId={params.sessionId} />
    </section>
  );
}
