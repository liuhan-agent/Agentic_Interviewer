import { Loader2, RotateCcw } from "lucide-react";

export default function InterviewReplayLoading() {
  return (
    <section
      aria-busy="true"
      aria-live="polite"
      className="container max-w-3xl py-10"
    >
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
          正在打开复盘页面
        </h1>
        <p className="max-w-xl text-sm leading-relaxed text-muted-foreground">
          正在加载每轮问题、回答、评分依据和后续练习建议。
        </p>
      </header>

      <div className="rounded-lg border bg-card p-5 shadow-sm">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10">
            <Loader2 className="h-5 w-5 animate-spin text-emerald-400" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="h-4 w-40 rounded bg-muted" />
            <div className="mt-4 space-y-3">
              <div className="h-24 rounded-lg border bg-background" />
              <div className="h-24 rounded-lg border bg-background" />
              <div className="h-24 rounded-lg border bg-background" />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
