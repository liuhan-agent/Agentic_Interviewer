# Adaptive Verifier Trigger —— 根据 drift 统计动态决定是否触发 Verifier

> **Status**: implementation complete, documented retrospectively.
>
> 代码在 `engine/agents/verification.py` 的 `_base_should_trigger` /
> `_adaptive_trigger_override` / `should_trigger` 已落地；Settings
> 字段在 `core/settings.py`；测试在
> `tests/unit/test_verifier_adaptive_trigger.py`（9 case 全绿）。
> 本文档补一张"为什么这样做 / 测试分层图"的 plan 页，便于后续
> 回顾和 Phase 3 的 persistence / cross-process 聚合做参考。

---

## 0. 设计目标

在 `should_trigger` 的纯规则 baseline 之上叠加一层**自适应反馈**：
让 Verifier 的触发密度随着实际 drift 情况动态变化，不再固定地被
`verifier_margin` / `verifier_senior_always` / `verifier_dimensions_bluff_prone`
等超参决定。

具体行为：

- **高 drift 维度**（`override_rate ≥ high_threshold`）→ **强制触发**
  即使 baseline 说跳过。属于"这个维度历史上评分过松，继续抓 bluff"。
- **低 drift 维度**（`override_rate ≤ low_threshold` 且 comfortably-clean pass）
  → **强制跳过** 即使 baseline（例如 `senior_always` / bluff-prone list）
  说触发。属于"这个维度已经赢得 evaluator 的信任，省 LLM 成本"。
- **中间区间**（`low < override_rate < high`）→ 透传 baseline，保持现状。

**门槛**：per-dimension 的 `calls < verifier_adaptive_min_samples`（默认 30）
时不启用 adaptive，防止少样本带来的统计噪声。

**双开关**：`verifier_adaptive_trigger` 和 `enable_verifier_drift_monitor`
都 True 才 engage，任意一方 False 都退回到 baseline。

---

## 1. 最终状态示意

```
evaluator_node.should_trigger(...)
  │
  ├─→ early return False if evaluation.passed is False
  │
  ├─→ _base_should_trigger(...) -> bool
  │     (pure rules: margin / deep_probe / senior_always / partial /
  │      bluff_prone_dim)
  │
  └─→ _adaptive_trigger_override(...) -> bool | None
         │
         ├─→ None  if adaptive OFF / monitor OFF
         │         if dim.calls < min_samples
         │         if override_rate in middle band
         │         if low drift but pass is NOT clean enough
         │
         ├─→ True  if override_rate >= high_threshold
         │
         └─→ False if override_rate <= low_threshold AND
                    score > quality_threshold + verifier_margin
                    (clean pass on a trusted dimension)

final = override if override is not None else base
```

---

## 2. 模块清单

| 文件 | 状态 | 职责 |
|---|---|---|
| `app/core/settings.py` | ✅ 已扩展 | +4 字段：`verifier_adaptive_trigger: bool = False`、`verifier_adaptive_high_threshold: float = 0.25`、`verifier_adaptive_low_threshold: float = 0.05`、`verifier_adaptive_min_samples: int = 30` |
| `app/engine/agents/verification.py` | ✅ 已重构 | `should_trigger` 拆成 `_base_should_trigger` + `_adaptive_trigger_override`；lazy-import drift monitor |
| `app/ml/drift/verifier_drift.py` | ✅ 无改动 | 复用现有 `snapshot().per_dimension[dim].override_rate / calls` |
| `tests/unit/test_verifier_adaptive_trigger.py` | ✅ 已落 | 9 个 case 覆盖所有分支 |

## 3. 9 个测试点对照

| # | 用例 | 触发断言 | 实现支撑 |
|---|---|---|---|
| 1 | `test_adaptive_off_by_default_preserves_legacy_behaviour` | flag OFF → 完全等于 baseline | `_adaptive_trigger_override` 第一行 `if not verifier_adaptive_trigger: return None` |
| 2 | `test_adaptive_on_but_drift_monitor_off_skips_adaptive` | 两个 flag 必须都 True | 第二个 guard：`if not enable_verifier_drift_monitor: return None` |
| 3 | `test_adaptive_requires_min_samples_per_dimension` | calls < min_samples → pass-through | `if calls < min_samples: return None` |
| 4 | `test_high_override_rate_forces_trigger_even_when_baseline_skips` | rate ≥ high → force True | `if override_rate >= high: return True` |
| 5 | `test_low_override_rate_allows_skipping_clear_pass_even_on_senior` | rate ≤ low + clean pass → force False | `if override_rate <= low and score > qt + margin: return False` |
| 6 | `test_low_override_rate_still_triggers_on_marginal_pass` | marginal 时 adaptive 不翻转 | "marginal" 的判定：`score <= qt + margin` → `return None`（pass-through） |
| 7 | `test_mid_override_rate_passes_through_to_baseline` | 中间区间 → 完全透传 baseline | fall-through `return None` |
| 8 | `test_adaptive_decision_is_per_dimension` | 两个 dim 同 eval 不同决策 | snapshot 的 `per_dimension[<dim>]` 是天然按维度隔离的；test 用 `VERIFIER_DRIFT_WINDOW_SIZE=1000` 保证两个 dim 事件不互相 evict |
| 9 | `test_failure_short_circuits_regardless_of_drift` | passed=False 立即 False | `should_trigger` 第二行 `if not passed: return False` |

---

## 4. 验收标准（DoD）

- [x] 代码合入（`verification.py` / `settings.py`）
- [x] 9 case 测试全绿（`pytest tests/unit/test_verifier_adaptive_trigger.py`）
- [x] 全量 pytest 通过（395 passed）
- [x] 默认 OFF（`verifier_adaptive_trigger=False`）；现有部署零行为变化
- [ ] `/admin/drift/verifier` 端点保留 `per_dimension[*].override_rate`（已由 `PLAN_VERIFIER_DRIFT.md` 保证）

---

## 5. 历史注解（flake 分析）

本 feature 的 9 个 test 曾在 Phase 2 第一次 full pytest 中**偶发性 1 fail**
（`test_adaptive_decision_is_per_dimension`），原因是：

- 该 case 使用了 `_seed_events(dim="api_design", calls=40)` + 
  `_seed_events(dim="frontend_craft", calls=200)`
- drift monitor 的滚动窗口默认 `window_size=200`
- 当 frontend_craft 的 200 个事件记录完后，api_design 的前 40 个事件
  被 evict，`per_dim[api_design].calls` 降为 0
- 于是 adaptive 对 api_design 返回 None（min_samples 门槛），
  baseline 又不触发，test assertion `True` 失败

修复方案已在 test 文件内落地（第 318 行）：
`monkeypatch.setenv("VERIFIER_DRIFT_WINDOW_SIZE", "1000")` 把窗口
临时放宽到 1000，保证两个 dim 的事件都能容纳。

**经验教训**：涉及 `per_dimension` 统计的单测必须显式设置
`VERIFIER_DRIFT_WINDOW_SIZE`，否则默认 200 会让多 dim 场景互相踩踏。

---

## 6. 后续钩子（延后）

1. **Persistence**：当前 adaptive 决策依赖进程内 `deque` 窗口；重启后
   per-dim 的 override_rate 归零，adaptive 回到默认 None → baseline。
   短期可接受（adaptive 很快就能重新积累），但 24h+ 的 drift 长期趋势
   需要 DB 或 Redis 持久化（见 `PLAN_VERIFIER_DRIFT.md §11 后续钩子 1`）。

2. **Redis 中心化跨 worker**：多 worker 部署时每个 worker 只看到自己
   receive 的 drift events，per-dim override_rate 会分裂。后续改用
   Redis list + LTRIM，或者把 override_rate 聚合下沉到 bandit 的
   `ThompsonBandit` 同款 lock-protected 全局状态。

3. **Cross-check with bandit**：bandit posterior 已经按 `(job_level, dim)`
   分桶，可以把 adaptive_override 看成"bandit 的 quick feedback layer"。
   长期如果 bandit 的 arm-level posterior 稳定下来，可以用 bandit mean
   反过来动态调整 `high_threshold` / `low_threshold`，让两层闭环自洽。

---

## 7. 一页总结

> **把 Verifier 触发策略从硬编码规则升级成自适应策略。**
>
> Drift monitor 观察到的真实 override_rate 直接回馈给 `should_trigger`：
> 高 drift 自动紧、低 drift 自动松、中间照旧。双 flag 默认关，单日可回滚。
> 9 个 test 把 adaptive 和 baseline 的交互点覆盖严实；
> 全量 pytest 395 passed、`/admin/drift/verifier` 端点零 API 变化。
