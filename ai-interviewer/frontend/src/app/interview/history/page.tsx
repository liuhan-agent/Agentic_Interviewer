import { History } from "lucide-react";

import { HistoryList } from "@/components/interview/HistoryList";

export const metadata = {
  title: "我的面试 · 问镜",
};

export default function InterviewHistoryPage() {
  return (
    <section className="container max-w-4xl py-10">
      <div className="mb-8">
        <div className="mb-3 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10">
            <History className="h-4 w-4 text-emerald-400" />
          </div>
          <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
            练习记录
          </p>
        </div>
        <h1 className="text-3xl font-semibold tracking-tight">我的面试</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
          这里是你做过的所有 AI 模拟面试。
          还没答完的可以接着练；已经完成的可以再看一次评分和反馈，比较自己每一次的进步。
        </p>
        <p className="mt-2 max-w-2xl text-xs text-muted-foreground/70">
          记录保存在当前浏览器中，换设备或清除缓存后将不再显示。
        </p>
      </div>
      <HistoryList />
    </section>
  );
}
