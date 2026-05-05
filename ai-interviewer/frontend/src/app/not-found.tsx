import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { Button } from "@/components/ui/button";

export default function NotFound() {
  return (
    <section className="container flex max-w-md flex-col items-center py-32 text-center">
      <div className="mb-4 font-mono text-6xl font-bold text-muted-foreground/30">
        404
      </div>
      <h1 className="mb-2 text-xl font-semibold">页面未找到</h1>
      <p className="mb-8 text-sm text-muted-foreground">
        未找到该页面。会话 ID 较长，请检查 URL 是否正确。
      </p>
      <Button asChild variant="outline" className="gap-2">
        <Link href="/">
          <ArrowLeft className="h-4 w-4" />
          返回首页
        </Link>
      </Button>
    </section>
  );
}
