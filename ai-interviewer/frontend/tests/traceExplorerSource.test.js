const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");

function read(relPath) {
  return fs.readFileSync(path.join(root, relPath), "utf8");
}

test("admin api exposes trace explorer client", () => {
  const api = read("src/lib/api/admin.ts");

  assert.match(api, /TraceExplorerResponse/);
  assert.match(api, /TraceExplorerNode/);
  assert.match(api, /getTraceExplorer/);
  assert.match(api, /TraceDiagnostics/);
  assert.match(api, /trace_diagnostics/);
  assert.match(api, /generation_trace_id/);
  assert.match(api, /node_count_total/);
  assert.match(api, /node_type_counts/);
  assert.match(api, /fallback_trace_count/);
  assert.match(api, /turn_count/);
  assert.match(api, /nodes_has_more/);
  assert.ok(api.includes("/admin/interview-sessions/${encodeURIComponent(sessionId)}/traces"));
});

test("trace explorer page and component expose workflow states", () => {
  const staticPage = read("src/app/admin/trace/page.tsx");
  const page = read("src/app/admin/traces/[sessionId]/page.tsx");
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(staticPage, /searchParams/);
  assert.match(staticPage, /sessionId/);
  assert.match(page, /TraceExplorer/);
  assert.match(component, /trace_health/);
  assert.match(component, /missing/);
  assert.match(component, /partial/);
  assert.match(component, /complete/);
  assert.match(component, /PartialTraceDiagnostics/);
  assert.match(component, /missing_key_nodes/);
  assert.match(component, /generationTraceId/);
  assert.match(component, /nodeName/);
  assert.match(component, /node_count_total/);
  assert.match(component, /nodes_has_more/);
  assert.match(component, /查看原始 trace payload/);
  assert.match(component, /按轮次查看节点/);
  assert.match(component, /route_decision/);
});

test("trace explorer exposes diagnostic workbench layout and URL state", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /TraceCommandCenter/);
  assert.match(component, /TraceWorkbench/);
  assert.match(component, /TraceTurnRail/);
  assert.match(component, /TraceNodeDetail/);
  assert.match(component, /useSearchParams/);
  assert.match(component, /nodeType/);
  assert.match(component, /selectedTraceId/);
  assert.match(component, /aria-pressed/);
  assert.match(component, /focus-visible:ring/);
});

test("trace explorer renders structured node evidence and lazy raw payloads", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /answer_excerpt/);
  assert.match(component, /immediate_reward_applied/);
  assert.match(component, /policy_context_keys/);
  assert.match(component, /EvaluationEvidence/);
  assert.match(component, /RawTracePayloadDetails/);
  assert.match(component, /JSON\.stringify\(rawPayload/);
  assert.match(component, /content-visibility/);
  assert.match(component, /prefers-reduced-motion/);
});

test("admin sessions expose Trace link", () => {
  const panel = read("src/components/admin/AdminPanel.tsx");

  assert.match(panel, /Trace/);
  assert.match(panel, /training_plan/);
  assert.match(panel, /experience_extractor/);
  assert.match(panel, /resume_parse/);
  assert.match(panel, /route_decision/);
  assert.ok(panel.includes("`/admin/trace?sessionId=${session.session_id}`"));
});

test("trace explorer groupByTurn defends against non-monotonic ordering", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  // Sentinel: numeric-aware key + explicit session-level token must
  // both be present so the bucket index can be sorted numerically and
  // the catch-all bucket can be pinned to the bottom.
  assert.match(component, /buckets\s*=\s*new\s+Map<number\s*\|\s*"session"/);
  assert.match(component, /Number\.POSITIVE_INFINITY/);

  // Sentinel: there is an explicit numeric sort over the produced
  // groups (without this we would silently rely on Map insertion
  // order, which is what the original bug was about).
  assert.match(component, /groups\.sort\(\s*\(a,\s*b\)\s*=>\s*a\.sortKey\s*-\s*b\.sortKey\s*\)/);
});

test("trace explorer can filter and mark evaluator fallback traces", () => {
  const component = read("src/components/admin/TraceExplorer.tsx");

  assert.match(component, /isEvaluatorFallbackTrace/);
  assert.match(component, /fallbackFilter/);
  assert.match(component, /只看 fallback/);
  assert.match(component, /评分 fallback/);
  assert.match(component, /fallbackTraceCount/);
});

test("rag eval copy frames score delta as correlation", () => {
  const component = read("src/components/admin/RagEvalPanel.tsx");

  assert.match(component, /相关性观察/);
  assert.match(component, /检索相关分数差异/);
  assert.match(component, /不代表单独的因果归因/);
});
