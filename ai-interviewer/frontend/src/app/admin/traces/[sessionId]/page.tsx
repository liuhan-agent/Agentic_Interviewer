import { AdminAccessGate } from "@/components/admin/AdminAccessGate";
import { TraceExplorer } from "@/components/admin/TraceExplorer";

export const metadata = {
  title: "Trace Explorer · AI 面试官",
};

export default function TraceExplorerPage({
  params,
}: {
  params: { sessionId: string };
}) {
  return (
    <section className="container max-w-6xl py-10">
      <AdminAccessGate>
        <TraceExplorer sessionId={params.sessionId} />
      </AdminAccessGate>
    </section>
  );
}
