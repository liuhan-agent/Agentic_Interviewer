import { History, Loader2 } from "lucide-react";

export default function InterviewHistoryLoading() {
  return (
    <section
      aria-busy="true"
      aria-live="polite"
      className="container max-w-4xl py-10"
    >
      <div className="mb-8">
        <div className="mb-3 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10">
            <History className="h-4 w-4 text-emerald-400" />
          </div>
          <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
            练习记录
          </p>
        </div>
        <h1 className="text-3xl font-semibold tracking-tight">
          正在打开面试历史
        </h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
          正在加载你的练习记录和最近一次面试状态。
        </p>
      </div>

      <div className="rounded-lg border bg-card p-5 shadow-sm">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10">
            <Loader2 className="h-5 w-5 animate-spin text-emerald-400" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="h-4 w-40 rounded bg-muted" />
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="h-24 rounded-lg border bg-background" />
              <div className="h-24 rounded-lg border bg-background" />
            </div>
            <div className="mt-4 h-28 rounded-lg border bg-background" />
          </div>
        </div>
      </div>
    </section>
  );
}
