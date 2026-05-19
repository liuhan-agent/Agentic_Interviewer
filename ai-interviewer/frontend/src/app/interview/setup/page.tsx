import { Suspense } from "react";
import { Settings2 } from "lucide-react";

import { SetupForm } from "@/components/interview/SetupForm";

export const metadata = {
  title: "开始面试 · AI 面试官",
};

export default function SetupPage() {
  return (
    <section className="container max-w-3xl py-12">
      <div className="mb-8">
        <div className="mb-3 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/10">
            <Settings2 className="h-4 w-4 text-emerald-400" />
          </div>
          <p className="font-mono text-xs uppercase tracking-widest text-emerald-400">
            开始之前
          </p>
        </div>
        <h1 className="text-3xl font-semibold tracking-tight">
          告诉 AI 你想练什么
        </h1>
        <p className="mt-2 max-w-xl text-sm leading-relaxed text-muted-foreground">
          填写你的背景和目标岗位，AI 面试官会据此挑选题目和评分维度。
          没有标准答案——按你真实的想法回答即可，结束后会拿到多维度反馈和提升建议。
        </p>
      </div>
      <Suspense
        fallback={
          <div className="rounded-lg border bg-card p-6 text-sm text-muted-foreground">
            正在加载表单...
          </div>
        }
      >
        <SetupForm />
      </Suspense>
    </section>
  );
}
