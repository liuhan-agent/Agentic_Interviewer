import type { Metadata } from "next";
import { Mic } from "lucide-react";

import { VoiceRoom } from "@/components/interview/VoiceRoom";

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
          与面试官语音对话
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          用语音直接回答面试问题，AI 面试官会自动识别你的回答内容，
          并语音播放下一个问题。
        </p>
      </div>
      <VoiceRoom sessionId={params.sessionId} />
    </section>
  );
}
