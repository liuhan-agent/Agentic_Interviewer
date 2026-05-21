import { Loader2, MessageSquare } from "lucide-react";

export default function InterviewSessionLoading() {
  return (
    <section
      aria-busy="true"
      aria-live="polite"
      className="container max-w-3xl py-10"
    >
      <header className="mb-6">
        <div className="flex flex-col gap-1">
          <div className="mb-2 flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10">
              <MessageSquare className="h-4 w-4 text-emerald-400" />
            </div>
            <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
              进入面试间
            </p>
          </div>
          <h1 className="text-2xl font-semibold tracking-tight">
            正在打开面试页面
          </h1>
          <p className="max-w-xl text-sm leading-relaxed text-muted-foreground">
            正在准备问题区和答题控件，页面加载完成后会自动继续。
          </p>
        </div>
      </header>

      <div className="rounded-lg border bg-card p-5 shadow-sm">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/10">
            <Loader2 className="h-5 w-5 animate-spin text-emerald-400" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="h-4 w-36 rounded bg-muted" />
            <div className="mt-3 space-y-2">
              <div className="h-3 w-full rounded bg-muted/70" />
              <div className="h-3 w-5/6 rounded bg-muted/70" />
              <div className="h-3 w-2/3 rounded bg-muted/70" />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
