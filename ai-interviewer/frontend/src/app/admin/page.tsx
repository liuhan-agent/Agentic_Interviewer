import { Activity } from "lucide-react";

import { AdminAccessGate } from "@/components/admin/AdminAccessGate";

export const metadata = {
  title: "后台观测台 · 问镜",
};

export default function AdminPage() {
  return (
    <section className="container max-w-6xl py-10">
      <div className="mb-8">
        <div className="mb-3 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10">
            <Activity className="h-4 w-4 text-emerald-400" />
          </div>
          <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
            可观测性
          </p>
        </div>
        <h1 className="text-3xl font-semibold tracking-tight">后台观测台</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
          连接用户侧质量中心和后端 Agentic Workflow：查看策略学习、评分复核、
          内存会话和策略记忆。面板每 15 秒自动刷新。
        </p>
      </div>
      <AdminAccessGate />
    </section>
  );
}
