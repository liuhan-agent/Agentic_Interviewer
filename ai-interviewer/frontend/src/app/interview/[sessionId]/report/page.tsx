import type { Metadata } from "next";
import { TrendingUp } from "lucide-react";

import { ReportView } from "@/components/interview/ReportView";

type PageProps = {
  params: { sessionId: string };
};

export function generateMetadata({ params }: PageProps): Metadata {
  const short =
    params.sessionId.length > 10
      ? `${params.sessionId.slice(0, 4)}…${params.sessionId.slice(-4)}`
      : params.sessionId;
  return {
    title: `报告 ${short} · 问镜`,
  };
}

export default function InterviewReportPage({ params }: PageProps) {
  return (
    <section className="container max-w-3xl py-10">
      <header className="mb-8 flex flex-col gap-1">
        <div className="mb-2 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10">
            <TrendingUp className="h-4 w-4 text-emerald-400" />
          </div>
          <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
            最终报告
          </p>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">
          面试报告
        </h1>
        <p className="max-w-xl text-sm leading-relaxed text-muted-foreground">
          问镜从多个维度给出了反馈和提升方向，
          帮你看清当前的强项和差距。
        </p>
      </header>
      <ReportView sessionId={params.sessionId} />
    </section>
  );
}
