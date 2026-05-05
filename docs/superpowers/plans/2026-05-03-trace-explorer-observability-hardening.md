# Trace Explorer 可观测性补齐实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 writing-plans、test-driven-development、verification-before-completion。按用户规则，本计划不使用子代理；逐任务串行执行。

**目标：** 修齐 Trace / Trace Explorer 的关键缺口，让单场面试的节点链路、健康度、诊断和人工标注可信可用。  
**架构：** 保持现有 `Tracer -> generation_traces -> admin API -> TraceExplorer` 链路不变，优先修正后端 trace 语义和聚合口径，再做前端诊断增强。所有改动保持旁路可观测性原则：trace 失败不能阻塞面试主流程。  
**技术栈：** Python、FastAPI、SQLAlchemy、pytest、Next.js、React、TypeScript、现有 admin API 与 shadcn/ui 组件。

## 范围

本计划按优先级处理六件事：

1. 修复 `WorkflowChainPanel` 中同一逻辑轮次被拆散的问题。
2. 让单场 Trace Explorer 的 summary 不受 nodes `limit` 截断影响。
3. 增加 `partial` trace 的可读诊断。
4. 让人工标注能精确绑定到某条 `generation_traces` 节点行。
5. 同步“最近 trace”前后端节点白名单。
6. 调整 RAG 评测文案，避免把相关性误读为因果。

不在本计划内：

- 不重构整个 admin 页面。
- 不引入新的观测平台或第三方依赖。
- 不改变候选人侧面试主流程。
- 不改变 trace 写失败时“记录并吞掉”的旁路原则。

## 文件结构

### 生产代码

- `ai-interviewer/backend/app/core/tracer.py`  
  增加逻辑轮次解析工具，让 `trace_node_event()` 可接收或推导“被评价的回答轮次”，避免 verification/reward 落到下一轮。

- `ai-interviewer/backend/app/engine/workflow/nodes/verification.py`  
  调用 `trace_node_event()` 时传入明确的逻辑轮次。

- `ai-interviewer/backend/app/engine/workflow/nodes/reward_update.py`  
  调用 `trace_node_event()` 时传入明确的逻辑轮次。

- `ai-interviewer/backend/app/api/v1/admin.py`  
  拆分 per-session trace 的 summary 聚合和 nodes 分页；增加 partial 诊断字段；annotation 创建校验目标 trace row。

- `ai-interviewer/backend/app/models/trace_annotation.py`  
  增加可空 `generation_trace_id` 和 `node` 字段，用于 node 级标注。

- `ai-interviewer/frontend/src/lib/api/admin.ts`  
  更新 Trace Explorer、diagnostics、annotation 类型。

- `ai-interviewer/frontend/src/components/admin/TraceExplorer.tsx`  
  展示 partial 诊断；传递 node row id 给标注弹窗；兼容分页 summary。

- `ai-interviewer/frontend/src/components/admin/TraceAnnotationDialog.tsx`  
  提交 `generation_trace_id` 和 `node`。

- `ai-interviewer/frontend/src/components/admin/AdminPanel.tsx`  
  同步最近 trace 节点按钮；调整 RAG 文案入口不需要改这里，RAG 卡片在独立文件。

- `ai-interviewer/frontend/src/components/admin/RagEvalPanel.tsx`  
  将“检索对评分的影响”改为“检索相关分数差异”。

### 测试

- `ai-interviewer/backend/tests/unit/test_workflow_chain_turn_alignment.py`
- `ai-interviewer/backend/tests/unit/test_admin_trace_pagination_summary.py`
- `ai-interviewer/backend/tests/unit/test_trace_partial_diagnostics.py`
- `ai-interviewer/backend/tests/unit/test_trace_annotations_node_binding.py`
- 扩展 `ai-interviewer/backend/tests/unit/test_admin_recent_traces.py`
- 扩展 `ai-interviewer/frontend/tests/traceExplorerSource.test.js`

## 任务 0：建立基线

**文件：** 不修改文件。

**步骤：**

1. 进入后端目录：
   ```powershell
   cd ai-interviewer/backend
   ```
2. 运行 trace/admin 相关现有测试：
   ```powershell
   python -m pytest tests/unit/test_trace_health_service.py tests/unit/test_admin_trace_rollup.py tests/unit/test_admin_recent_traces.py tests/unit/test_final_report_trace.py
   ```
3. 进入前端目录：
   ```powershell
   cd ../frontend
   ```
4. 运行 Trace Explorer 源码哨兵测试：
   ```powershell
   node --test tests/traceExplorerSource.test.js
   ```

**验证：** 所有命令通过；若失败，先记录现有失败，不把它归因到后续改造。  
**提交：** 不提交，除非用户明确要求。

## 任务 1：修复 workflow 轮次对齐

**文件：**

- `ai-interviewer/backend/app/core/tracer.py`
- `ai-interviewer/backend/app/engine/workflow/nodes/verification.py`
- `ai-interviewer/backend/app/engine/workflow/nodes/reward_update.py`
- `ai-interviewer/backend/tests/unit/test_workflow_chain_turn_alignment.py`

**步骤：**

1. 新增失败测试，构造同一轮的 director/evaluator/verification/reward trace，断言 workflow chain 聚合在同一个 turn：
   ```python
   def test_verification_and_reward_use_answer_turn(monkeypatch):
       from app.core.tracer import Tracer

       state = {
           "session_id": "sess-align",
           "trace_id": "trace-align",
           "turn_idx": 1,
           "formal_turn_idx": 1,
           "current_dimension": "system_design",
           "current_question": {"question": "Q", "dimension": "system_design"},
           "current_answer": "A",
           "evaluation": {"score": 8.0, "passed": True},
           "selected_action": {"id": "deep_probe"},
       }

       captured = []
       monkeypatch.setattr(
           "app.core.tracer._write_generation_trace_for_test",
           lambda row: captured.append(row),
           raising=False,
       )

       tracer = Tracer()
       tracer.trace_node_event(state, node="verification", payload={"triggered": False}, logical_turn_idx=0)
       tracer.trace_node_event(state, node="reward_update", payload={"immediate_reward": 0.8}, logical_turn_idx=0)

       assert [row.turn_idx for row in captured] == [0, 0]
   ```
   如果项目没有可替换写入钩子，不添加测试钩子；改为 monkeypatch `get_session()` 捕获 `sess.add()` 的 `GenerationTrace`。

2. 在 `Tracer.trace_node_event()` 增加参数：
   ```python
   logical_turn_idx: int | None = None
   ```

3. 在创建 `GenerationTrace` 时使用：
   ```python
   turn_idx=(
       int(logical_turn_idx)
       if logical_turn_idx is not None
       else state.get("turn_idx", 0)
   )
   ```

4. 在 `verification_node()` 中计算回答轮次：
   ```python
   answer_turn_idx = max(0, int(state.get("turn_idx", 0)) - 1)
   ```
   两个 `trace_node_event(... node="verification")` 调用都传 `logical_turn_idx=answer_turn_idx`。

5. 在 `reward_update_node()` 中用同样规则传 `logical_turn_idx=answer_turn_idx`。

**验证：**

```powershell
python -m pytest tests/unit/test_workflow_chain_turn_alignment.py tests/unit/test_workflow_observability.py tests/unit/test_answer_lifecycle.py
```

预期：新增测试先失败，改实现后通过；既有 workflow observability 测试继续通过。

## 任务 2：summary 全量聚合，nodes 分页

**文件：**

- `ai-interviewer/backend/app/api/v1/admin.py`
- `ai-interviewer/backend/tests/unit/test_admin_trace_pagination_summary.py`
- `ai-interviewer/frontend/src/lib/api/admin.ts`
- `ai-interviewer/frontend/src/components/admin/TraceExplorer.tsx`

**步骤：**

1. 新增后端测试：构造 120 条普通 trace + 末尾 `final_report`，请求 `limit=100` 时，返回 nodes 只有 100 条，但 summary 的 `final_report_trace_count` 和 `trace_health` 仍基于全量。

2. 在 `_interview_session_trace_payload()` 中把查询拆成两段：
   ```python
   summary_rows = (
       sess.query(GenerationTrace.node, func.count(GenerationTrace.id))
       .filter(GenerationTrace.session_id == session_id)
       .group_by(GenerationTrace.node)
       .all()
   )
   traces = (
       sess.query(GenerationTrace)
       .filter(GenerationTrace.session_id == session_id)
       .order_by(GenerationTrace.turn_idx.asc(), GenerationTrace.id.asc())
       .offset(offset)
       .limit(capped_limit)
       .all()
   )
   ```

3. 给 endpoint 增加 `offset: int = 0`，限制 `0 <= offset <= 10000`，`limit` 保持最多 300。

4. 响应增加：
   ```python
   "node_count_total": total_trace_count,
   "nodes_offset": safe_offset,
   "nodes_limit": capped_limit,
   "nodes_has_more": safe_offset + len(nodes) < total_trace_count,
   ```

5. 前端类型增加这些字段；Trace Explorer 顶部显示“当前展示 X / 全部 Y 条”。本任务只展示状态，不实现“加载更多”按钮，避免扩大范围。

**验证：**

```powershell
python -m pytest tests/unit/test_admin_trace_pagination_summary.py tests/unit/test_admin_auth.py
node --test tests/traceExplorerSource.test.js
```

预期：健康度不再受节点分页影响，前端源码哨兵通过。

## 任务 3：增加 partial trace 诊断

**文件：**

- `ai-interviewer/backend/app/services/trace_health.py`
- `ai-interviewer/backend/app/api/v1/admin.py`
- `ai-interviewer/backend/tests/unit/test_trace_partial_diagnostics.py`
- `ai-interviewer/frontend/src/lib/api/admin.ts`
- `ai-interviewer/frontend/src/components/admin/TraceExplorer.tsx`

**步骤：**

1. 新增服务函数：
   ```python
   def trace_diagnostics(nodes: list[dict[str, Any]], *, session_status: str | None = None) -> dict[str, Any]:
       node_names = [str(node.get("node") or "") for node in nodes]
       present = set(node_names)
       expected = ["director_sample", "ask_question", "evaluator", "verification", "reward_update", "final_report"]
       missing = [node for node in expected if node not in present]
       return {
           "health": classify_trace_health(nodes, session_status=session_status),
           "present_nodes": sorted(present),
           "missing_key_nodes": missing,
           "last_node": node_names[-1] if node_names else None,
           "session_status": session_status,
       }
   ```

2. 在 per-session trace payload 中返回：
   ```python
   "trace_diagnostics": trace_diagnostics(summary_nodes, session_status=row.status)
   ```

3. 新增测试覆盖：
   - 只有 `evaluator` 时 missing 包含 `reward_update` / `final_report`。
   - completed 但无 `director_sample` 时 health 可以仍按旧规则 complete，但 diagnostics 明确列出缺失节点。
   - running 时 last_node 返回最近节点。

4. 前端增加 `PartialTraceDiagnostics` 卡片：当 `trace_health === "partial"` 或 diagnostics 有 `missing_key_nodes` 时展示。

**验证：**

```powershell
python -m pytest tests/unit/test_trace_partial_diagnostics.py tests/unit/test_trace_health_service.py
node --test tests/traceExplorerSource.test.js
```

预期：partial 页面能直接说明缺哪个节点，不需要用户手工读 payload。

## 任务 4：人工标注绑定到 node row

**文件：**

- `ai-interviewer/backend/app/models/trace_annotation.py`
- `ai-interviewer/backend/app/api/v1/admin.py`
- `ai-interviewer/backend/tests/unit/test_trace_annotations_node_binding.py`
- `ai-interviewer/frontend/src/lib/api/admin.ts`
- `ai-interviewer/frontend/src/components/admin/TraceExplorer.tsx`
- `ai-interviewer/frontend/src/components/admin/TraceAnnotationDialog.tsx`

**步骤：**

1. 模型增加字段：
   ```python
   generation_trace_id: Mapped[int | None] = mapped_column(Integer, index=True)
   node: Mapped[str | None] = mapped_column(String(64), index=True)
   ```

2. `CreateAnnotationInput` 增加：
   ```ts
   generation_trace_id?: number;
   node?: string;
   ```

3. `TraceNodeCard` 打开标注弹窗时传：
   ```tsx
   generationTraceId={node.id}
   nodeName={node.node}
   ```

4. 后端 `create_annotation()` 中，如果传了 `generation_trace_id`，查询 `GenerationTrace` 并校验 `session_id` 一致；不存在则 404。

5. 保存 annotation 时写入 `generation_trace_id` 和 `node`。

6. list annotations 响应带回这两个字段。

**验证：**

```powershell
python -m pytest tests/unit/test_trace_annotations_node_binding.py
node --test tests/traceExplorerSource.test.js
```

预期：同一 turn 的 evaluator 和 verifier 可以分别标注，错误的 row id 会被拒绝。

## 任务 5：同步最近 trace 节点列表

**文件：**

- `ai-interviewer/frontend/src/components/admin/AdminPanel.tsx`
- `ai-interviewer/backend/tests/unit/test_admin_recent_traces.py`
- `ai-interviewer/frontend/tests/traceExplorerSource.test.js`

**步骤：**

1. 将前端 `RECENT_TRACE_NODES` 增加：
   ```ts
   "training_plan",
   "experience_extractor",
   "resume_parse",
   ```

2. 扩展前端源码测试，断言这些节点按钮存在。

3. 扩展后端 recent-traces 测试，确保 `training_plan` 是可查询节点。

**验证：**

```powershell
python -m pytest tests/unit/test_admin_recent_traces.py
node --test tests/traceExplorerSource.test.js
```

预期：后端允许的节点在前端都有入口。

## 任务 6：调整 RAG 评测文案

**文件：**

- `ai-interviewer/frontend/src/components/admin/RagEvalPanel.tsx`
- `ai-interviewer/frontend/tests/traceExplorerSource.test.js`

**步骤：**

1. 将描述从“评估检索对面试质量的贡献”改为：
   ```tsx
   对比有/无 RAG 检索信号时的评分分布，作为检索质量的相关性观察。
   ```

2. 将“检索对评分的影响”改为：
   ```tsx
   检索相关分数差异：
   ```

3. 增加一行小字：
   ```tsx
   这是相关性指标，不代表单独的因果归因。
   ```

**验证：**

```powershell
node --test tests/traceExplorerSource.test.js
```

预期：用户不会把 `score_delta` 误读成严格因果效果。

## 最终验证

**后端：**

```powershell
cd ai-interviewer/backend
python -m pytest tests/unit/test_workflow_chain_turn_alignment.py tests/unit/test_admin_trace_pagination_summary.py tests/unit/test_trace_partial_diagnostics.py tests/unit/test_trace_annotations_node_binding.py tests/unit/test_admin_recent_traces.py tests/unit/test_trace_health_service.py tests/unit/test_admin_trace_rollup.py tests/unit/test_admin_auth.py tests/unit/test_workflow_observability.py
```

**前端：**

```powershell
cd ai-interviewer/frontend
node --test tests/traceExplorerSource.test.js
npm run type-check
```

如果 `npm run type-check` 不存在，改跑项目已有类型/构建命令，例如：

```powershell
npm run lint
```

## 验收标准

- 同一轮回答的 `director_sample/evaluator/verification/reward_update` 在 Workflow 决策链里聚合到同一个 Turn。
- 长会话即使 nodes 页面只展示前 100 条，顶部 `trace_health` 和 `final_report_trace_count` 仍基于全量 trace。
- `partial` Trace Explorer 能显示缺失关键节点和最后写入节点。
- 人工标注能绑定具体 `generation_traces.id`，不会把同一 turn 的多个节点混在一起。
- “最近 trace”前端按钮覆盖后端白名单中的节点。
- RAG 评测文案明确是相关性观察，不暗示因果。

## 风险与回滚

- **风险：旧数据没有 `generation_trace_id` 标注。** 字段设计为可空，旧标注继续可读。
- **风险：改变 `turn_idx` 写入会影响历史数据。** 不迁移历史 trace；新 trace 修齐。若需要历史修复，单独做离线迁移计划。
- **风险：summary 全量聚合增加查询。** 使用 `group_by node`，只扫单个 session 的 indexed `session_id`，预期成本可控。
- **风险：health 规则争议。** 本计划先不改变 `complete` 判定，只新增 diagnostics；避免破坏现有前台质量中心口径。
