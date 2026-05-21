import { PendingNavigationLink } from "@/components/navigation/PendingNavigationLink";
import { TraceExplorer } from "@/components/admin/TraceExplorer";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

export default function TraceExplorerSearchPage({
  searchParams,
}: {
  searchParams?: { sessionId?: string; node?: string; dimension?: string };
}) {
  const sessionId = searchParams?.sessionId?.trim() ?? "";
  const focusNode = searchParams?.node?.trim() || undefined;
  const focusDimension = searchParams?.dimension?.trim() || undefined;

  if (!sessionId) {
    return (
      <section className="container max-w-6xl py-10">
        <Card>
          <CardContent className="space-y-3 pt-6 text-sm text-muted-foreground">
            <p className="font-medium text-foreground">缺少 sessionId</p>
            <p>请从后台观测台的历史面试列表进入 Trace Explorer。</p>
            <Button asChild variant="outline" size="sm">
              <PendingNavigationLink href="/admin">返回后台观测台</PendingNavigationLink>
            </Button>
          </CardContent>
        </Card>
      </section>
    );
  }

  return (
    <section className="container max-w-6xl py-10">
      <TraceExplorer
        sessionId={sessionId}
        focusNode={focusNode}
        focusDimension={focusDimension}
      />
    </section>
  );
}
