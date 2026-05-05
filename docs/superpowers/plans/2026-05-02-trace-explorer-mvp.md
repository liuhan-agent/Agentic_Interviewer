# Trace Explorer MVP 实现计划

> **面向 AI 代理的工作者：** 本计划禁止使用子代理。按单线程 TDD 执行：先写失败测试，再实现最小代码，再验证。

**目标：** 为后台观测台增加一版可用的 Trace Explorer，用于查看单场面试的 workflow 节点过程、节点结果和 trace 健康状态。

**架构：** 后端新增只读 admin trace API，直接查询 `InterviewSession` 与 `GenerationTrace`，返回 session 摘要、trace 健康状态和按时间排序的节点列表。前端新增 `/admin/traces/[sessionId]` 页面，从历史面试区跳转进入，按 session summary、turn timeline、node card、raw details 四层展示。

**技术栈：** FastAPI、SQLAlchemy、Postgres、Next.js App Router、React、TypeScript、现有 UI 组件、Node source tests、pytest。

## 范围边界

### 本期做

- 后端新增 `GET /admin/interview-sessions/{session_id}/traces`。
- 后台历史面试表新增 `Trace` 按钮。
- 前端新增 Trace Explorer 页面。
- 支持 `missing / partial / complete` 三种 trace 健康状态。
- 支持无 trace 但有 report 的空状态。
- 支持节点 raw payload 折叠查看。

### 本期不做

- 不做图形化 DAG。
- 不做拖拽、筛选器、搜索器。
- 不做 trace 伪回填。
- 不修改 workflow 编排。
- 不解决历史数据缺 trace 的根因，只展示状态。
- 不接 LangSmith 深链，继续沿用现有 run id 展示。

## 现有 workflow 分析

真实图拓扑来自 `ai-interviewer/backend/app/engine/workflow/langgraph_workflow.py`：

```text
START
  -> resume_parse
  -> self_intro_question
  -> wait_answer
  -> self_intro_parse
  -> director_sample
  -> ask_question
  -> wait_answer
  -> evaluator
  -> verification
  -> reward_update
  -> compress_context
  -> route_after_eval
       -> refine        -> refine_followup -> director_sample
       -> next_question -> director_sample
       -> end           -> final_report -> training_plan -> experience_extractor -> END
```

`route_after_wait` 可能让取消会话跳过 evaluator，直接进入 `final_report`。

`route_after_eval` 可能进入 `refine_followup`、回到 `director_sample`，或结束进入 `final_report`。

因此 Trace Explorer 不能假设固定线性路径；必须按实际 trace rows 展示。

## Trace 数据模型

主要来源：`GenerationTrace`。

关键字段：

| 字段 | 用途 |
|---|---|
| `id` | 节点事件唯一 ID |
| `session_id` | 面试会话 |
| `trace_id` | 运行链路 |
| `turn_idx` | 面试轮次 |
| `node` | workflow 节点名 |
| `dimension` | 能力维度 |
| `action_id` | 策略动作 |
| `policy_id` | 策略标识 |
| `context_key` | bandit context |
| `policy_context_keys` | 多 context 更新键 |
| `score` | evaluator 分数 |
| `passed` | evaluator 是否通过 |
| `immediate_reward` | 即时 reward |
| `immediate_reward_applied` | 是否已应用 |
| `state_snapshot` | 节点状态快照 |
| `question` | 当前问题 |
| `answer` | 当前回答 |
| `evaluation` | 评分结果 |
| `langsmith_run_id` | LangSmith run id |
| `created_at` | 节点记录时间 |

## 后端 API 设计

### Endpoint

```text
GET /admin/interview-sessions/{session_id}/traces
```

仍使用 `require_admin_token` 保护。

### Response

```json
{
  "session_id": "sess-xxx",
  "trace_id": "trace-xxx",
  "status": "completed",
  "has_report": true,
  "overall_score": 7.66,
  "overall_verdict": "strong_hire",
  "trace_count": 12,
  "evaluator_trace_count": 5,
  "reward_trace_count": 5,
  "final_report_trace_count": 1,
  "trace_health": "complete",
  "nodes": [
    {
      "id": 1,
      "turn_idx": 0,
      "node": "director_sample",
      "dimension": "technical_depth",
      "action_id": "plan_deep_probe",
      "policy_id": "thompson_v1::template::java_backend:junior:technical_depth",
      "context_key": "java_backend:junior:technical_depth",
      "policy_context_keys": ["java_backend:junior:technical_depth"],
      "score": null,
      "passed": null,
      "immediate_reward": null,
      "immediate_reward_applied": false,
      "question": null,
      "answer_excerpt": null,
      "evaluation": null,
      "payload": {
        "diagnostics": {},
        "selected_action": {}
      },
      "langsmith_run_id": null,
      "created_at": "2026-05-02T12:00:00+00:00"
    }
  ]
}
```

### trace_health 规则

| trace_health | 条件 |
|---|---|
| `missing` | `trace_count === 0` |
| `partial` | 有 trace，但缺 evaluator 或缺 final_report/reward_update |
| `complete` | 有 evaluator，且有 final_report 或 reward_update |

## 后端文件结构

### `backend/app/api/v1/admin.py`

新增：

- `_trace_health(nodes: list[dict[str, Any]]) -> str`
- `_trace_node_payload(trace: GenerationTrace) -> dict[str, Any]`
- `_interview_session_trace_payload(session_id: str) -> dict[str, Any]`
- `get_interview_session_traces(session_id: str) -> dict[str, Any]`

约束：

- 查询不到 session 返回 404。
- 查询到 session 但无 trace 返回 `trace_health: "missing"` 和空 `nodes`。
- `answer` 只返回摘要，避免长文本撑爆页面。
- `state_snapshot` 不全量返回，只返回 `payload` 所需摘要。

### `backend/tests/unit/test_admin_auth.py`

新增测试：

1. `test_admin_interview_session_traces_returns_nodes`
2. `test_admin_interview_session_traces_reports_missing_when_no_rows`
3. `test_admin_interview_session_traces_404_for_unknown_session`

## 前端 API 设计

### `frontend/src/lib/api/admin.ts`

新增类型：

```ts
export type TraceHealth = "missing" | "partial" | "complete";

export interface TraceExplorerNode {
  id: number;
  turn_idx?: number | null;
  node: string;
  dimension?: string | null;
  action_id?: string | null;
  policy_id?: string | null;
  context_key?: string | null;
  policy_context_keys?: string[] | null;
  score?: number | null;
  passed?: boolean | null;
  immediate_reward?: number | null;
  immediate_reward_applied?: boolean;
  question?: string | null;
  answer_excerpt?: string | null;
  evaluation?: Record<string, unknown> | null;
  payload?: Record<string, unknown> | null;
  langsmith_run_id?: string | null;
  created_at?: string | null;
}

export interface TraceExplorerResponse {
  session_id: string;
  trace_id?: string | null;
  status?: string | null;
  has_report: boolean;
  overall_score?: number | null;
  overall_verdict?: string | null;
  trace_count: number;
  evaluator_trace_count: number;
  reward_trace_count: number;
  final_report_trace_count: number;
  trace_health: TraceHealth;
  nodes: TraceExplorerNode[];
}
```

新增函数：

```ts
export function getTraceExplorer(
  sessionId: string,
  signal?: AbortSignal,
): Promise<TraceExplorerResponse>
```

## 前端页面结构

### `frontend/src/app/admin/traces/[sessionId]/page.tsx`

职责：

- 读取 `params.sessionId`。
- 渲染 `TraceExplorer`。
- 设置 metadata title。

### `frontend/src/components/admin/TraceExplorer.tsx`

职责：

- 拉取 trace response。
- 展示 loading / error / empty / ready 四种状态。
- 将 nodes 按 turn 分组。
- 渲染 summary cards。
- 渲染 timeline node cards。
- 渲染 raw payload details。

### `frontend/src/components/admin/AdminPanel.tsx`

在 `HistoricalSessionsCard` / `SessionLinks` 增加：

```text
Trace
```

链接：

```text
/admin/traces/{sessionId}
```

## 前端测试

### `frontend/tests/traceExplorerSource.test.js`

新增 source tests：

1. 页面存在 `/admin/traces/[sessionId]/page.tsx`。
2. `TraceExplorer.tsx` 包含 `trace_health`、`missing`、`partial`、`complete`。
3. `TraceExplorer.tsx` 按 `turn_idx` 分组。
4. `TraceExplorer.tsx` 有 `查看原始 trace payload`。
5. `AdminPanel.tsx` 历史面试区包含 `Trace` 链接。

## 实现任务

### 任务 1：后端 Trace API 测试

文件：

- `backend/tests/unit/test_admin_auth.py`

步骤：

1. 写 `test_admin_interview_session_traces_returns_nodes`。
2. mock `_interview_session_trace_payload` 或使用 isolated session 构造返回。
3. 运行：

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m pytest tests/unit/test_admin_auth.py -q
```

预期：新增测试失败，因为 route 不存在。

### 任务 2：后端 Trace API 实现

文件：

- `backend/app/api/v1/admin.py`

步骤：

1. 新增 trace payload helpers。
2. 新增 route。
3. 限制 answer 摘要长度，例如 220 字符。
4. 保持 admin token 保护。

验证：

```powershell
python -m pytest tests/unit/test_admin_auth.py -q
```

预期：通过。

### 任务 3：前端 API 类型与 source test

文件：

- `frontend/src/lib/api/admin.ts`
- `frontend/tests/traceExplorerSource.test.js`

步骤：

1. 先写 source test。
2. 新增类型和 `getTraceExplorer()`。

验证：

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm test -- tests/traceExplorerSource.test.js
```

预期：先失败，后通过。

### 任务 4：Trace Explorer 页面

文件：

- `frontend/src/app/admin/traces/[sessionId]/page.tsx`
- `frontend/src/components/admin/TraceExplorer.tsx`

步骤：

1. 新建页面。
2. 实现 summary card。
3. 实现 missing / partial / complete 状态。
4. 实现 timeline 分组。
5. 实现 node card。
6. 实现 raw details。

验证：

```powershell
npm test -- tests/traceExplorerSource.test.js
npm run typecheck
npm run lint
```

### 任务 5：后台入口串联

文件：

- `frontend/src/components/admin/AdminPanel.tsx`
- `frontend/tests/adminObservabilitySource.test.js`

步骤：

1. 历史面试操作区新增 `Trace` 按钮。
2. 链接到 `/admin/traces/${session.session_id}`。
3. 跑 source test。

验证：

```powershell
npm test -- tests/adminObservabilitySource.test.js tests/traceExplorerSource.test.js
```

### 任务 6：真实接口 smoke 验证

步骤：

1. 确认后端运行。
2. 调用：

```powershell
.\.venv\Scripts\python.exe -c "import urllib.request,json; sid='sess-8b19987d99'; print(json.loads(urllib.request.urlopen(f'http://127.0.0.1:8000/admin/interview-sessions/{sid}/traces').read()))"
```

预期：

- 旧会话返回 `trace_health: "missing"` 或 `partial`。
- 页面能显示空状态和跳转按钮。

## 最终验证清单

后端：

```powershell
python -m pytest tests/unit/test_admin_auth.py -q
```

前端：

```powershell
npm test -- tests/adminObservabilitySource.test.js tests/traceExplorerSource.test.js
npm run typecheck
npm run lint
```

IDE：

```text
ReadLints: 改动文件无新增 linter errors
```

手工：

```text
/admin -> 历史面试 -> Trace
/admin/traces/sess-8b19987d99 -> 显示 trace missing/partial 空状态
/interview/sess-8b19987d99/replay -> 仍显示 fallback timeline
```

## 风险与取舍

- 旧会话 trace 缺失不是本计划解决对象，本计划只展示状态。
- `state_snapshot` 可能很大，第一版只返回摘要与 payload，不返回完整 JSON。
- Trace Explorer 是开发者视图，不放进用户报告页主路径。
- 如果后续要做完整 DAG，可在本 API 基础上扩展，不需要推翻本期设计。
