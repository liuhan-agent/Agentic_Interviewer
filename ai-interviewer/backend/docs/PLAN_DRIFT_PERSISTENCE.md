# Verifier Drift Persistence — Plan & As-Built

> 本文档接续 `PLAN_VERIFIER_DRIFT.md`（监控）和 `PLAN_DRIFT_FEEDBACK.md`
> （L3.5 evaluator prompt 反哺），把 verifier drift 从「滚动窗口 + Redis」
> 升级为「DB 沉淀 + 聚合读模型 + 失败模式 taxonomy 维度可消费」。
>
> 依赖：
> - `app/ml/drift/verifier_drift.py`（in-memory / Redis monitor）
> - `app/models/verifier_drift.py`（本 plan 引入的两张表）
> - `app/services/drift_pattern_aggregation.py` / `drift_event_retention.py`
> - `app/services/drift_feedback_parity.py`（§7 monitor↔DB parity）
> - `app/tasks/drift_pattern_aggregation_tasks.py` / `drift_event_retention_tasks.py` /
>   `drift_maintenance_tasks.py`
> - `app/ml/drift/prompt_feedback.py`（多源切换）
> - `app/api/v1/admin.py` 中 `/admin/drift/*` 路由族

## 0. 设计目标

- **跨重启保留**：drift overrule 事件不再只在进程内存 / Redis 滚动窗口里活，
  落到 `verifier_drift_events` 长留 90 天；聚合到 `verifier_drift_patterns`
  作为 prompt-feedback 的读模型。
- **失败模式细粒度**：聚合主键 = `(dimension, check_name, failure_category)` +
  `(dimension, check_name, "__global__")` 两层，避免 `failure_categories` 为空
  的事件丢失上下文。
- **Shadow rollout 与回退**：`drift_feedback_source` 三档（`monitor` / `db_shadow`
  / `db`），默认 `db_shadow` 仍返回 monitor markdown、同时 log 一条 parity diff；
  `monitor` 是紧急回退档；`db` 是真正切换后的目标态。
- **Best-effort 写入**：`verification_node` 在原 `monitor.record()` 之后 dual-write
  DB，任何 DB 异常只 `log.warning`，不阻塞实时面试。
- **运维可观测**：admin 端有 events / patterns / freshness / 手动 aggregation /
  手动 retention 5 个路由；APScheduler 兜底自动跑聚合与过期清理。
- **零 prompt 字节 diff（升档前）**：PR1-7 + B 全套上线后，候选人看到的问题
  在 `drift_feedback_source="db_shadow"` 下仍与 monitor 路径 byte-identical。

**明确不做**：

- 不替换 `VerifierDriftMonitor` 本体（滚动窗口仍跑，作为低延迟旁路）。
- 不在 P0 期间引入 Celery / Kafka；scheduler 仅用 APScheduler，依赖与
  outcome-sync / dream / privacy-cleanup 保持一致。
- 不在 P0 期间动前端 AdminPanel（留到 P1）。
- 不做 verifier 自身的输出结构升级（taxonomy 在 P1 evaluator 已闭环，verifier 留待后续）。

---

## 1. 最终状态

```
verification_node
  ├─ monitor.record(event)            ← 旧路径，必走
  └─ _persist_drift_event(event)      ← 新增，best-effort
        ├─ idempotent id = sha1(session|turn|dim|check|ts)[:32]
        ├─ INSERT verifier_drift_events
        └─ IntegrityError → 安全忽略（幂等）

APScheduler (enable_drift_maintenance_scheduler=True 时)
  ├─ run_drift_pattern_aggregation_tracked   每 30min
  └─ run_drift_event_retention_tracked       每 24h

或 admin 手动触发
  ├─ POST /admin/drift/aggregation/run
  └─ POST /admin/drift/retention/run

aggregation 服务
  └─ 扫近 30 天 overruled 事件，按 (dim, check, fc) + (dim, check, __global__)
     两层聚合，upsert verifier_drift_patterns

prompt_feedback (drift_feedback_source 决定路径)
  ├─ monitor:    旧路径 byte-identical
  ├─ db_shadow:  返回 monitor markdown + log 一行 parity diff（不影响 prompt）
  └─ db:         读 verifier_drift_patterns，按 fc 过滤，退化到 __global__

admin 观测
  ├─ GET /admin/drift/events?since_hours=24&limit=200&overruled_only=true
  ├─ GET /admin/drift/patterns?dimension=...&failure_category=...&limit=100
  └─ GET /admin/drift/freshness         scheduler 状态 + DB 计数 + 最近 job 结果
```

---

## 2. 表结构

### `verifier_drift_events`（原始事件 · retention 90d）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str(64) PK | `sha1(session_id|turn_idx|dimension|check_name|created_at)[:32]` 幂等键 |
| `session_id` / `trace_id` / `turn_idx` | 上下文索引 | 与 GenerationTrace 对得上 |
| `dimension` / `job_level` | 检索维度 | |
| `verifier_verdict` / `verifier_confidence` / `verifier_abstained` | verifier 输出 | |
| `evaluator_passed` / `overruled` / `overruled_check_name` | 翻判判定 | `overruled` 字段 index |
| `span_miss_count` / `span_total` | evidence span 对齐质量 | |
| `evaluator_evidence_quotes` / `verifier_reasons` | JSON list（已 _truncate） | |
| `failure_categories` | JSON list | 来自 `state.evaluation.failure_categories`，从 0d1a2ed 起 caller 透传 |
| `created_at` | datetime index | |

### `verifier_drift_patterns`（聚合读模型 · upsert）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str(160) PK | `sha1(dimension|check_name|failure_category)[:32]` |
| `dimension` / `check_name` / `failure_category` | 主键三元组 | `failure_category="__global__"` 表示无 taxonomy 的兜底桶 |
| `uses` / `overruled_count` / `overrule_rate` | 聚合计数 | |
| `sample_evidence` / `reasons_sample` | JSON list（去重，最多各 5 条） | |
| `first_seen_at` / `last_seen_at` / `updated_at` | 生命周期 | |

---

## 3. 配置项与默认值（settings.py 第 460-496 行）

```python
# 持久化主开关
enable_verifier_drift_persistence: bool = True

# 数据生命周期
verifier_drift_event_retention_days: int = 90
drift_pattern_aggregation_window_days: int = 30

# 反馈源（PR7 默认升档到 db_shadow，仍返回 monitor 内容）
drift_feedback_source: Literal["monitor", "db_shadow", "db"] = "db_shadow"

# 维护调度（B 收尾：scheduler + freshness）
enable_drift_maintenance_scheduler: bool = False  # 默认 OFF，CI/本地不跑后台线程
drift_pattern_aggregation_interval_minutes: int = 30
drift_event_retention_interval_hours: int = 24
```

**rollout 顺序**（按 git 提交顺序）：

1. `50e4ef6` PR1 模型 + settings 4 字段
2. `e5c00cb` PR2 dual-write
3. `4aa420c` PR3+4 聚合 + retention
4. `5cc219c` PR5+6 prompt_feedback 多源 + admin 4 路由 + PR7 默认升 db_shadow
5. `0d1a2ed` caller 透传 `failure_categories`（让 (dim, check, fc) 桶真正非空）
6. **B 收尾**：scheduler wrapper（`drift_maintenance_tasks.py`）+ admin freshness

---

## 4. 模块清单

| 文件 | 动作 | 摘要 |
|---|---|---|
| `app/models/verifier_drift.py` | 新增（PR1） | 两张表的 SQLAlchemy 模型 |
| `app/engine/workflow/nodes/verification.py` | 改（PR2） | `_compose_drift_event` + `_persist_drift_event`（独立 session、IntegrityError 幂等） |
| `app/services/drift_pattern_aggregation.py` | 新增（PR3） | 两层聚合 + stale 清理 |
| `app/services/drift_event_retention.py` | 新增（PR4） | 按 `retention_days` 删除过期事件 |
| `app/tasks/drift_pattern_aggregation_tasks.py` | 新增（PR3） | 一键 wrapper `run_drift_pattern_aggregation_now()` |
| `app/tasks/drift_event_retention_tasks.py` | 新增（PR4） | 一键 wrapper `run_drift_event_retention_now()` |
| `app/ml/drift/prompt_feedback.py` | 改（PR5） | `_load_db_patterns` / `_load_monitor_patterns` / `_load_overruled_patterns` 三源切换 + `_pattern_keys` helper 写 shadow diff |
| `app/api/v1/admin.py` | 改（PR6+B） | 4 个 drift 路由 + freshness 路由；手动 run 路由切到 tracked wrapper |
| `app/engine/workflow/nodes/evaluator.py` | 改（0d1a2ed） | `build_evaluator_drift_negatives` caller 透传 fc |
| `app/engine/workflow/nodes/ask_question.py` | 改（0d1a2ed） | `build_generator_avoid_patterns` caller 透传 fc |
| `app/tasks/drift_maintenance_tasks.py` | 新增（B） | APScheduler wrapper + in-process status tracker（`reset` / `get_status` / `_run_tracked`） |
| `app/main.py` | 改（B） | startup 按开关注册 scheduler、shutdown 清理 |
| `app/core/settings.py` | 改（PR1+PR7+B） | 7 个 drift 字段总和 |

---

## 5. Admin 路由速查

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/admin/drift/events` | 列原始事件，含 `since_hours` / `limit` / `overruled_only` |
| GET | `/admin/drift/patterns` | 列聚合 pattern，含 `dimension` / `failure_category` / `limit` |
| GET | `/admin/drift/freshness` | scheduler 状态、interval、event/pattern 计数、最近 job 结果与错误 |
| GET | `/admin/drift/shadow-parity` | monitor↔DB 重合率（§7） |
| POST | `/admin/drift/aggregation/run` | 手动触发聚合（tracked，状态会写到 freshness） |
| POST | `/admin/drift/retention/run` | 手动触发过期清理（tracked） |

全部路由挂 `require_admin_token`；DB 异常返空 + `db_error` 字段，绝不 500。

---

## 6. 验收与下一步

### 已验证（截至本文档落地）

- 全后端测试 1450 passed, 1 skipped
- 6 个目标测试 16 passed（drift_maintenance_tasks 3 + admin_drift_persistence freshness 3 + 原 10）
- 9+4+9=22 邻近测试全绿
- `ReadLints`：0 错误

### 仍 OPEN 的下一阶段任务

1. ~~**db_shadow parity 真正可观测**~~：✅ 已实现，see §7。
2. **从 `db_shadow` flip 到 `db`**：当 §7 的 admin parity 持续 ≥ 0.9 后，把
   `drift_feedback_source` 默认改为 `"db"`，让 prompt 真正消费 DB 聚合。
3. **failure taxonomy 升档决策**：观察 `/admin/failure-category-stats` 4 桶分布，
   决定 refine_followup 是否切到「LLM 主、normalize fallback」。
4. **接 Verifier 自身输出 failure_categories**：当前 fc 全部来自 evaluator；
   verifier 也输出后，drift event 的 fc 维度可以双源校验。
5. **前端 AdminPanel**：把 freshness / patterns / events / shadow-parity 四个表面接
   进 AdminPanel 的 drift tab。
6. **历史 parity 表**：如果一周观察不够（例如 jaccard 持续在 0.7-0.9 摆动），
   加一张 `drift_feedback_shadow_snapshots(captured_at, dimension, monitor_count,
   db_count, jaccard)` + cron 每小时跑一次，让 §7 的瞬时 snapshot 变成可绘趋势的
   时序数据。

---

## 7. db_shadow parity admin 接口

### 7.1 用途

`drift_feedback_source="db_shadow"` 让 prompt 仍走 monitor 路径（byte-identical
保护候选人），同时 DB 路径被并行查询并写出一行 `log.info` 形式的 parity diff。
但 log 只对值班工程师有用，运营无法快速回答「这一周 monitor 与 DB 在哪些 dim
上对得上、对不上」。本接口把这个问题做成结构化报告：

| 维度 | 含义 |
|---|---|
| `monitor_count` / `db_count` | 各自当前在 ``(dim, check)`` 维度的桶数 |
| `intersection` | 两边都返回的 ``(dim, check)`` 对（升序） |
| `monitor_only` / `db_only` | 只在一边出现的 ``(dim, check)`` 对 |
| `jaccard_similarity` | `\|∩\| / \|∪\|`；两边均空时为 `null` |

### 7.2 请求

```
GET /admin/drift/shadow-parity?top_n=5&min_support=2[&dimensions=a,b,c]
```

- `top_n`（默认 5，clamp 1-50）：每边每个 dim 输出的最大 pattern 数，与
  `build_evaluator_drift_negatives` / `build_generator_avoid_patterns` 的
  rollout 默认对齐。
- `min_support`（默认 2，clamp 1-1000）：低于此 count 的 pattern 不计入比较。
- `dimensions`（可选，逗号分隔）：缺省时自动扫
  `monitor.snapshot()["per_dimension"].keys()` ∪
  `SELECT DISTINCT dimension FROM verifier_drift_patterns`，并去重排序。

### 7.3 响应体

```json
{
  "top_n": 5,
  "min_support": 2,
  "feedback_source": "db_shadow",
  "monitor_backend": "memory",
  "per_dimension": [
    {
      "dimension": "system_design",
      "monitor_count": 3,
      "db_count": 4,
      "intersection": [["system_design", "Mentions concrete failure modes"]],
      "monitor_only": [["system_design", "Quantifies blast radius"]],
      "db_only": [["system_design", "Picks a consistency model"]],
      "jaccard_similarity": 0.2
    }
  ],
  "summary": {
    "dimensions_checked": 1,
    "avg_jaccard": 0.2,
    "min_jaccard": 0.2,
    "max_jaccard": 0.2
  }
}
```

DB 异常时仍返 200，附加 `"db_error": "<msg>"` 字段，`per_dimension` 退化为空。

### 7.4 Flip 决策线

- 连续 7 天 `summary.avg_jaccard ≥ 0.9` 且 `min_jaccard ≥ 0.7` → 可把
  `Settings.drift_feedback_source` 默认升档到 `"db"`，让 prompt 真正消费 DB 聚合。
- 若 `monitor_count` 大幅高于 `db_count` → 大概率是 aggregation 没跑（看
  `/admin/drift/freshness` 的 `maintenance.aggregation.last_finished_at`）或
  `enable_drift_maintenance_scheduler=False`。
- 若 `db_count` 大幅高于 `monitor_count` → monitor 窗口（`verifier_drift_window_size`）
  太小，把历史高频 pattern 滚出了内存；db 反而是更稳定的真值。可考虑直接 flip
  而不再观察。

### 7.5 已知限制

- §7 不写历史表（OPEN #6 计划补）。当前是瞬时 snapshot；如果跑得太频繁，
  monitor / db 都可能在采样间隙内发生变化，差异不一定来源于路径分歧本身。
- `__global__` 维度回退：DB 端 `failure_categories=None` 时只查 ``__global__`` 桶；
  Caller 透传 fc 走 (dim, check, fc) 细桶的 parity 暂不纳入此接口，等
  evaluator → ask_question → generator 的 fc 透传链稳定后再扩。
