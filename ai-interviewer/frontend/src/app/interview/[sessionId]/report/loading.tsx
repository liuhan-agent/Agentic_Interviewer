import { Loader2, TrendingUp } from "lucide-react";

export default function InterviewReportLoading() {
  return (
    <section
      aria-busy="true"
      aria-live="polite"
      className="container max-w-3xl py-10"
    >
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
          正在打开面试报告
        </h1>
        <p className="max-w-xl text-sm leading-relaxed text-muted-foreground">
          正在准备评分摘要、维度趋势和训练建议。
        </p>
      </header>

      <div className="rounded-lg border bg-card p-5 shadow-sm">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10">
            <Loader2 className="h-5 w-5 animate-spin text-emerald-400" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="h-4 w-36 rounded bg-muted" />
            <div className="mt-4 h-32 rounded-lg border bg-background" />
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <div className="h-20 rounded-lg border bg-background" />
              <div className="h-20 rounded-lg border bg-background" />
              <div className="h-20 rounded-lg border bg-background" />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
