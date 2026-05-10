import type { Metadata } from "next";
import { Mic } from "lucide-react";

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
    title: `语音面试 ${short} · AI 面试官`,
  };
}

export default function VoiceInterviewPage({ params }: PageProps) {
  return (
    <section className="container max-w-3xl py-10">
      <div className="mb-6">
        <div className="mb-3 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10">
            <Mic className="h-4 w-4 text-emerald-400" />
          </div>
          <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
            语音通道
          </p>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">
          面试进行中
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          语音只作为回答输入方式：先转写成可编辑文本，确认后再提交。
        </p>
      </div>
      <InterviewRoom sessionId={params.sessionId} defaultAnswerMode="voice" />
    </section>
  );
}
