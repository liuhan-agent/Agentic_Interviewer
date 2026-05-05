# L1：Verifier drift signal —— 让 evaluator 的 drift 变成可观测指标

> 本 plan 延续 `PLAN_EVIDENCE_SPANS.md` 的 §8 钩子「L1 Verifier drift signal」，
> 依赖 `PLAN_EVIDENCE_SPAN_ALIGNMENT.md`（L2）中产出的 `evidence_spans[*].match` 信号。
> 目标：**把 Verifier 翻判 evaluator 的频次 + evidence 对齐失败率**沉淀成进程内滚动窗口监控，
> 通过 `/admin/drift/verifier` 暴露给运维和后续 fine-tune 流水线。

---

## 0. 设计目标

- **纯观测**：不影响路由决策，不改 verdict 语义，不新增 LLM 调用。
- **默认关闭**：`enable_verifier_drift_monitor=False`，零行为差异。
- **进程内滚动窗口**：`collections.deque(maxlen=N)`，默认 `N=200`。
- **线程安全**：与 `ThompsonBandit` 同一套 `threading.Lock` 模式。
- **两级聚合**：全局 + per-dimension 两档。
- **读：admin endpoint**：`/admin/drift/verifier` 返回 snapshot JSON，复用现有 `require_admin_token` 鉴权。

**不做**：
- 不落 DB（进程重启清零；后续如有需要再加 persistence）
- 不起独立 scheduler（snapshot 是拉模式，operator 按需 curl）
- 不做 Redis 中心化（多进程聚合推到 L3 再说）
- 不对接 Prometheus exporter（如果需要，后续 wrap snapshot 即可）

---

## 1. 最终状态示意

```
verification_node (every verified turn)
  │
  │  verify_answer(...) returns {verdict, confidence, ...}
  │  _apply_verification(...) decides soft_warnings / forced_refine
  │
  ▼
  if settings.enable_verifier_drift_monitor:
      monitor = get_verifier_drift_monitor()
      monitor.record(DriftEvent(
          dimension=..., job_level=...,
          evaluator_passed=evaluation["passed"],
          verifier_verdict="pass|partial|fail",
          verifier_confidence=...,
          verifier_abstained=...,
          overruled=updated_eval["passed"] == False and evaluation["passed"] == True,
          span_miss_count=..., span_total=...,
      ))

GET /admin/drift/verifier
  │
  ▼
{
  "window_size": 200,
  "samples": 50,
  "calls": 50,
  "overrides": 6,
  "abstains": 4,
  "override_rate": 0.12,
  "abstain_rate": 0.08,
  "span_miss_rate": 0.15,
  "per_dimension": {
    "system_design": {"calls": 20, "overrides": 4, "override_rate": 0.20, ...},
    ...
  },
  "per_verdict": {"pass": 40, "partial": 4, "fail": 2},
  "enabled": true
}
```

---

## 2. 模块清单

| 文件 | 动作 | 变更摘要 |
|---|---|---|
| `app/core/settings.py` | 扩展 | +2 字段：`enable_verifier_drift_monitor: bool = False` / `verifier_drift_window_size: int = 200` |
| `app/ml/drift/__init__.py` | 新增 | 包入口 |
| `app/ml/drift/verifier_drift.py` | 新增 | `DriftEvent` dataclass + `VerifierDriftMonitor` + `get_verifier_drift_monitor() / reset_for_tests()` |
| `app/engine/workflow/nodes/verification.py` | 小改 | `verification_node` 末尾 opt-in 记录 DriftEvent；提取 span_miss 统计 |
| `app/api/v1/admin.py` | 小改 | 新增 `GET /admin/drift/verifier`（复用 `require_admin_token`） |
| `tests/unit/test_verifier_drift.py` | 新增 | 7–8 个 case：record/snapshot/window/per-dim/集成 |
| `.env.example` | 小改 | 追加 `ENABLE_VERIFIER_DRIFT_MONITOR=false` 注释 |
| `README.md` | 小改 | 在 "Observability" 段补 `/admin/drift/verifier` 端点 |

---

## 3. 数据结构

```python
@dataclass(frozen=True)
class DriftEvent:
    """One verifier invocation observation.

    Stored only when ``enable_verifier_drift_monitor=True`` so normal
    deployments pay zero memory cost. All fields are plain primitives
    so JSON serialisation in the admin endpoint is trivial.
    """
    dimension: str
    job_level: str
    evaluator_passed: bool
    verifier_verdict: Literal["pass", "partial", "fail"]
    verifier_confidence: float
    verifier_abstained: bool       # confidence < MIN_OVERRIDE_CONFIDENCE
    overruled: bool                # verifier forced refine (evaluator had passed=True)
    span_miss_count: int           # acceptance_check_results 中 match=="none" 的数
    span_total: int                # 总 evidence_spans 数
    timestamp: datetime
```

---

## 4. `VerifierDriftMonitor` 骨架

```python
class VerifierDriftMonitor:
    def __init__(self, *, window_size: int = 200) -> None:
        self._events: deque[DriftEvent] = deque(maxlen=window_size)
        self._lock = threading.Lock()
        self._window_size = window_size

    def record(self, event: DriftEvent) -> None:
        with self._lock:
            self._events.append(event)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            events = list(self._events)

        total = len(events)
        overrides = sum(1 for e in events if e.overruled)
        abstains = sum(1 for e in events if e.verifier_abstained)
        span_miss_total = sum(e.span_miss_count for e in events)
        span_total = sum(e.span_total for e in events)

        per_dim: dict[str, dict[str, Any]] = {}
        per_verdict: dict[str, int] = {"pass": 0, "partial": 0, "fail": 0}
        for e in events:
            d = per_dim.setdefault(
                e.dimension,
                {"calls": 0, "overrides": 0, "abstains": 0, "span_miss": 0, "span_total": 0},
            )
            d["calls"] += 1
            d["overrides"] += int(e.overruled)
            d["abstains"] += int(e.verifier_abstained)
            d["span_miss"] += e.span_miss_count
            d["span_total"] += e.span_total
            per_verdict[e.verifier_verdict] = per_verdict.get(e.verifier_verdict, 0) + 1

        for d in per_dim.values():
            d["override_rate"] = d["overrides"] / d["calls"] if d["calls"] else 0.0
            d["abstain_rate"] = d["abstains"] / d["calls"] if d["calls"] else 0.0
            d["span_miss_rate"] = (
                d["span_miss"] / d["span_total"] if d["span_total"] else 0.0
            )

        return {
            "window_size": self._window_size,
            "samples": total,
            "calls": total,
            "overrides": overrides,
            "abstains": abstains,
            "override_rate": overrides / total if total else 0.0,
            "abstain_rate": abstains / total if total else 0.0,
            "span_miss_rate": span_miss_total / span_total if span_total else 0.0,
            "per_dimension": per_dim,
            "per_verdict": per_verdict,
        }

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
```

单例模式复用 `ThompsonBandit.get_bandit` 的 double-checked-locking 样板。

---

## 5. verification_node 接入

**位置**：`app/engine/workflow/nodes/verification.py` 的 `verification_node`，在 `verify_answer` 返回且 `_apply_verification` 计算完 `updated_evaluation` 之后，return 之前插入一段。

**关键提取**：
- `span_miss_count / span_total` 来自 `evaluation.acceptance_check_results[*].evidence_spans`（L2 产出）。
- `overruled = bool(evaluation.get("passed")) and not bool(updated_evaluation.get("passed"))`

**完整接入代码**：

```python
if get_settings().enable_verifier_drift_monitor:
    try:
        _record_drift_event(
            evaluation=evaluation,
            updated_evaluation=updated_evaluation,
            verification=verification,
            dimension=dimension,
            job_level=job_level,
        )
    except Exception as e:  # pragma: no cover - monitor is non-critical
        log.debug("drift monitor record failed: %s", e)
```

`_record_drift_event` 私有 helper 处理 event 构造 + 拿 monitor 单例。所有失败 log-and-swallow：drift monitor 是辅助观测，不能拖垮主流程。

---

## 6. Admin endpoint

```python
@router.get("/drift/verifier", dependencies=[Depends(require_admin_token)])
def verifier_drift_snapshot() -> dict[str, Any]:
    from app.ml.drift.verifier_drift import get_verifier_drift_monitor

    s = get_settings()
    snap = get_verifier_drift_monitor().snapshot()
    snap["enabled"] = s.enable_verifier_drift_monitor
    return snap
```

---

## 7. 测试策略

**新增单测** `tests/unit/test_verifier_drift.py`（8 个 case）：

| 用例 | 断言 |
|---|---|
| `test_monitor_starts_empty` | 初始 snapshot 全零 |
| `test_record_single_event` | record 后 calls=1，per-dimension 正确分桶 |
| `test_snapshot_override_rate` | 10 events，其中 3 overruled → override_rate≈0.3 |
| `test_window_truncation` | 超 window_size 会丢弃旧 events |
| `test_span_miss_rate_aggregation` | 跨 events 累加 span_miss / span_total |
| `test_verification_node_records_when_enabled` | 集成测：settings ON + should_trigger 命中 + monitor 收到 event |
| `test_verification_node_silent_when_disabled` | 默认 settings，monitor events 为空 |
| `test_drift_monitor_is_thread_safe` | 多线程并发 record + snapshot 无异常 |

**测试基础设施**：
- `reset_verifier_drift_monitor_for_tests()` 每个测试前调用
- `get_settings.cache_clear()` 切换 knob 时调用

**不打破现有测试**：`test_verifier_abstain.py` 已有的 verifier 集成测继续用默认 settings，零事件记录。

---

## 8. 风险与回滚

| 风险 | 发生步骤 | 缓解 | 回滚 |
|---|---|---|---|
| verification_node record 失败冒泡打断主流程 | Step 5 | try/except 全包住，只 `log.debug` | 关 knob |
| deque 内存增长（并发 record 未持锁） | Step 4 | `deque(maxlen=N)` 配合 `threading.Lock` | 调小 window_size |
| admin endpoint 泄露 per-dimension 统计 | Step 6 | 复用 `require_admin_token` + `include_in_schema=False` | 撤端点 |
| 单例跨测试泄漏状态 | Step 7 | `reset_verifier_drift_monitor_for_tests()` + autouse fixture | N/A |

---

## 9. 验收标准（DoD）

- [ ] 新模块 + settings + admin endpoint 合入
- [ ] `pytest tests/unit/test_verifier_drift.py` 全绿
- [ ] 全量 pytest 不退步（222 → ≥230）
- [ ] `ReadLints` 无新增错误
- [ ] 手动：
  - `ENABLE_VERIFIER_DRIFT_MONITOR=true` + 跑 `python -m app.scripts.run_demo`
  - `curl localhost:8000/admin/drift/verifier` 返回非零 `samples`
- [ ] README 补 "Verifier drift monitor" 段说明 knob + endpoint

---

## 10. 预估工作量

| Step | 代码 | 测试 | 文档 | 合计 |
|---|---|---|---|---|
| 1 plan | 0 | 0 | 0.3h | 0.3h |
| 2 settings + monitor | 0.8h | 0.8h | 0 | 1.6h |
| 3 verification_node 接入 | 0.3h | 0.3h | 0 | 0.6h |
| 4 admin endpoint | 0.1h | 0.1h | 0 | 0.2h |
| 5 文档收尾 | 0 | 0 | 0.3h | 0.3h |

**合计 ≈ 3.0 人时**。

---

## 11. 后续钩子（本 plan 不做）

- **Persistence 到 DB**：当窗口需要跨重启保留（比如 ≥24h 的 drift 告警）时，新建 `drift_events` 表 + 背景 flush。
- **Alerting**：当 `override_rate > 阈值` 或 `span_miss_rate > 阈值` 时发告警（Slack / email）。
- **Evaluator prompt 反哺（L3.5）**：drift monitor 识别到 "一直被 verifier 翻判的 evaluator pattern"，抽成 few-shot 负例回写 evaluator prompt。
- **Redis 中心化**：多 worker 聚合需要共享窗口，改用 Redis list + LTRIM。
