import { Activity } from "lucide-react";

export function Footer() {
  return (
    <footer className="border-t bg-card/30">
      <div className="container flex flex-col items-center justify-between gap-3 py-6 text-xs text-muted-foreground sm:flex-row sm:py-4">
        <div className="flex items-center gap-2">
          <Activity className="h-3.5 w-3.5 text-emerald-400/60" />
          <span className="font-mono">
            问镜 · 追问评分 · 复盘训练
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span>为求职者打造</span>
        </div>
      </div>
    </footer>
  );
}
