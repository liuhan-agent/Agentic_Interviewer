import type { Metadata } from "next";
import { MessageSquare } from "lucide-react";

import { InterviewRoom } from "@/components/interview/InterviewRoom";

type PageProps = {
  params: { sessionId: string };
};

export function generateMetadata({ params }: PageProps): Metadata {
  const short =
    params.sessionId.length > 10
      ? `${params.sessionId.slice(0, 4)}…${params.sessionId.slice(-4)}`
      : params.sessionId;
  return {
    title: `面试 ${short} · AI 面试官`,
  };
}

export default function InterviewSessionPage({ params }: PageProps) {
  return (
    <section className="container max-w-3xl py-10">
      <header className="mb-6">
        <div className="flex flex-col gap-1">
          <div className="mb-2 flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10">
              <MessageSquare className="h-4 w-4 text-emerald-400" />
            </div>
            <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
              进行中
            </p>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">
            面试进行中
          </h1>
          <p className="max-w-xl text-sm leading-relaxed text-muted-foreground">
            按自己的节奏认真回答每个问题。进度会自动保存，
            关闭页面后可以随时回来继续。
          </p>
        </div>
      </header>
      <InterviewRoom sessionId={params.sessionId} />
    </section>
  );
}
