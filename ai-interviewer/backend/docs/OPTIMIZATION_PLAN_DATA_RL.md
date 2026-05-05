# Data 模块 + RL 模块 优化计划（v2 — 基于真实代码盘点）

> 本文取代 v1。v1 是在未完整勘察代码时写的，部分建议（如"加 Critic Agent"、"加 action mask 统一函数"、"4 臂太少"）在当前代码里已经以更高级形态实现。v2 把建议收敛为**对现有成熟架构的打磨和加固**，不引入新子系统。
>
> **当前代码真实状态**（锚点，防止误判）：
> - LangSmith 已在 `main.py:_configure_langsmith` 接入，双份 env 已镜像
> - `GenerationTrace.applied_to_bandit` 幂等位已在
> - `outcome_reward_bridge.backfill_once` 已在，在 `tasks/outcome_sync_tasks` 里被周期调用
> - bandit 已支持 `policy_mode: template | legacy`，5+4 双命名空间 + `ALIAS_MAP`，`rehydrate_from_db` 启动时已调用
> - `action_space._allowed_actions_template/legacy` 已集中 mask 规则
> - `verification.py`（Verifier 三 Agent）/ `coach.py` / `strategy_dream.py`（autoDream）/ `strategy_store.py`（文件型策略记忆）均已实现
> - Ask Plan 可插拔 step 流水线已在，三套 template（simple / adaptive / deep_probe）已在
> - `PlanContract` 由 evaluator 签字流程已在
> - `enable_outcome_sync / rehydrate_bandit_on_start / policy_mode / enable_strategy_dream` 等 knob 已在 `settings.py`

## 0. 设计目标

**打磨**以下 3 层，不碰业务主干：

1. **配置化**：`reward_fn.immediate_reward` 和 `outcome_reward_bridge._delayed_reward` 里的魔数全部上提 `Settings`，让调参不再需要改代码。
2. **正确性**：
   - `backfill_once` 的 DB / bandit 事务边界不严格，Phase 2 失败会导致"DB 没标但 bandit 内存已打" 的不一致（依赖重启 rehydrate 兜底，可以更早消除）。
   - `Thompson.select` 并列最大值时字典序偏差；`get_bandit` 无锁的 lazy init 线程安全。
3. **鲁棒性 / 演化能力**：
   - 非平稳（岗位漂移）下 bandit 无衰减机制，早期奖励永久主导后验 → 加 `decay()` + 定期调度。
   - PII 脱敏只抓 email / phone / 长数字；URL / IPv4 / 中国 18 位身份证会直接入向量库。
   - Chunk 切分按字符硬切，中文句子会被腰斩，影响 RAG 召回。
   - `trainset_builder.export_jsonl` 无增量支持，每日训练数据准备会全量重跑。

**关键不做**（延后到有触发条件再启动）：
- NER 脱敏（M5，延后）
- Gaussian bandit（L1，延后到 evaluator 打分分布分析完成后）
- OPE 离线评估（L2，延后到 trace schema 加 propensity 列之后）
- Redis 中心化 bandit（L3，延后到多进程部署）
- 学习型 reward model（L4，延后到 ≥5k trace）
- DPO / SFT 微调（延后到 ≥2k OutcomeRecord + evaluator rubric 稳定）

---

## 1. 最终状态示意

```
Settings（新增 9 个字段）
  ├─ reward_passed_bonus / reward_coverage_bonus
  ├─ outcome_weights (dict JSON) / outcome_perf_blend
  ├─ bandit_decay_factor (default 0.99) / bandit_decay_floor (default 1.0)
  ├─ bandit_decay_interval_days (default 1, 语义锁定)
  ├─ enable_bandit_decay (default False，需显式开启)
  └─ pii_extra_patterns (default True，开启 URL/IP/身份证)

Data 模块
  ├─ clean.py        加 URL / IPv4 / 中国身份证；顺序锁定
  ├─ ingest.py       _split 改"段落→句→长度兜底"
  └─ trainset_builder.py
                     export_jsonl(since: datetime|None)
                     scripts/export_daily_trainset.py（强制传 --days|--since）

RL 模块
  ├─ reward_fn.py    从 settings 读 bonus
  ├─ outcome_reward_bridge.py
  │      backfill_once 两阶段：① DB 事务提交 ② 内存 bandit.update
  └─ thompson.py
         + threading.Lock 保护 get_bandit
         + select 并列最大值用 rng.choice
         + decay(factor, floor)

调度层（复用现有 tasks/outcome_sync_tasks.py）
  └─ 增加 decay 子任务：enable_bandit_decay=True 时，按间隔 N 天调一次 decay()

观测
  └─ GET /admin/bandit/snapshot  只读 endpoint（返回 ThompsonBandit.snapshot()）
```

**增量改动**：所有都是增量，不改 API、不改 schema、不删旧行为。

---

## 2. 模块清单

| 文件 | 动作 | 变更摘要 |
|---|---|---|
| `app/core/settings.py` | 扩展 | +9 字段（全部带默认值，等价于当前硬编码行为）|
| `app/data/clean.py` | 小改 | +URL / +IPv4 / +CHINA_ID；调整匹配顺序；扩展 counts |
| `app/data/ingest.py` | 小改 | `_split` 改"段落→句→兜底"；保留 600/80 作硬上限 |
| `app/data/trainset_builder.py` | 小改 | `export_jsonl` 增 `since: datetime \| None` 参数 |
| `app/scripts/export_daily_trainset.py` | 新增 | 强制 `--days` 或 `--since`，否则拒跑 |
| `app/ml/rl/reward_fn.py` | 小改 | 从 `get_settings()` 读取 bonus，删除魔数常量 |
| `app/ml/rl/outcome_reward_bridge.py` | 重构 | `_delayed_reward` 读 settings；`backfill_once` 两阶段（DB → bandit）|
| `app/ml/rl/thompson.py` | 小改 | `select` 并列修正；`threading.Lock` 保护 singleton；新增 `decay(factor, floor)` |
| `app/tasks/outcome_sync_tasks.py` | 小改 | 新增 `start_decay_scheduler`（按 N 天调一次 decay），由 `enable_bandit_decay` 门控 |
| `app/main.py` | 小改 | 启动时根据 `enable_bandit_decay` 调度 decay；新增 `/admin/bandit/snapshot` 端点 |
| `tests/data/test_clean_extended.py` | 新增 | 顺序敏感 + 新正则覆盖 |
| `tests/data/test_split_sentence.py` | 新增 | 短/长/中英混合/超长句兜底 |
| `tests/data/test_trainset_incremental.py` | 新增 | since 过滤 |
| `tests/ml/rl/test_thompson_extra.py` | 新增 | 并列随机性 / decay / 单例锁 |
| `tests/ml/rl/test_backfill_two_phase.py` | 新增 | 正常 / Phase 2 失败 + rehydrate / 幂等 |
| `tests/conftest.py` | 可能小改 | 确保测试间 `get_settings.cache_clear()` 和 `reset_bandit_for_tests()` 调用 |

---

## 3. 步骤（落地顺序；每步独立 PR）

### Step 1 · 配置化（reward / outcome / decay）

**目标**：把魔数全部挪到 `Settings`，默认值与当前硬编码等价，零功能变化。

**settings.py 增量**（附在现有字段末尾即可）：

```python
reward_passed_bonus: float = 0.10
reward_coverage_bonus: float = 0.10

outcome_weights: dict[str, float] = Field(
    default_factory=lambda: {
        "hired": 1.0, "rejected": 0.0, "withdrew": 0.3, "ghosted": 0.2,
    }
)
outcome_perf_blend: float = 0.5

enable_bandit_decay: bool = False
bandit_decay_factor: float = 0.99
bandit_decay_floor: float = 1.0
bandit_decay_interval_days: int = 1

pii_extra_patterns: bool = True
```

**reward_fn.py**：

```python
from app.core.settings import get_settings

def immediate_reward(*, evaluation: dict[str, Any]) -> float:
    s = get_settings()
    score = float(evaluation.get("score", 0.0))
    base = max(0.0, min(1.0, score / MAX_SCORE))
    if evaluation.get("passed"):
        base = min(1.0, base + s.reward_passed_bonus)
    coverage = evaluation.get("rubric_coverage") or {}
    if coverage:
        covered = sum(1 for v in coverage.values() if v in {"covered", "partial"})
        base = min(1.0, base + (covered / len(coverage)) * s.reward_coverage_bonus)
    return base
```

**outcome_reward_bridge.py**：`_delayed_reward` 读 settings；保留 `OUTCOME_WEIGHTS` 模块常量作 fallback（settings 配置缺 key 时用）。

**验收**：
- 全量 pytest 通过（默认值等价，测试结果不变）
- `Settings().reward_passed_bonus == 0.10` / `outcome_weights["hired"] == 1.0`

---

### Step 2 · backfill_once 两阶段（正确性）

**目标**：消除"DB 未提交但 bandit 内存已打"的不一致风险。

**改动**：把 `backfill_once` 拆成 Phase 1（DB 侧采集 + commit）→ Phase 2（commit 后驱动内存 bandit）：

```python
def backfill_once() -> dict[str, int]:
    counters = {"sessions": 0, "traces": 0}
    applied: list[tuple[str, str, float]] = []

    # Phase 1: DB 事务（退出 with 自动 commit）
    with get_session() as sess:
        outcomes = list(sess.scalars(select(OutcomeRecord)))
        if not outcomes:
            return counters
        ids = [o.session_id for o in outcomes]
        traces = _pending_traces(sess, ids)
        outcome_by_sid = {o.session_id: o for o in outcomes}
        for t in traces:
            outcome = outcome_by_sid.get(t.session_id)
            if outcome is None or not (t.context_key and t.action_id):
                continue
            r = _delayed_reward(outcome)
            t.delayed_reward = r
            t.applied_to_bandit = True
            applied.append((t.context_key, t.action_id, r))
        counters["traces"] = len(applied)
        counters["sessions"] = len({t.session_id for t in traces})

    # Phase 2: commit 成功后才驱动内存 bandit
    bandit = get_bandit()
    for ctx, aid, r in applied:
        bandit.update(ctx, aid, r)

    log.info(
        "delayed-reward backfill: DB applied=%d sessions=%d; bandit updates=%d",
        counters["traces"], counters["sessions"], len(applied),
    )
    return counters
```

**关键语义不变点**：
- 失败场景：Phase 2 崩溃 → DB 已标记 `applied_to_bandit=True`；下次进程重启，`rehydrate_bandit_on_start=True` 会从这些 flag 重放，bandit 状态最终一致。
- 幂等保留：Phase 1 的 `_pending_traces` 过滤 `applied_to_bandit=False`，连跑两次第二次为空。

**验收（单测）**：
1. 正常路径：counters 正确，bandit priors 正确更新
2. Phase 2 失败模拟：用 `mock.patch('...ThompsonBandit.update', side_effect=Exception)`，断言 DB 侧已标记；调用 `reset_bandit_for_tests()` + `rehydrate_from_db()` 后 bandit 状态等价于正常路径
3. 幂等：连跑 2 次 `backfill_once()`，第二次 counters 全 0

---

### Step 3 · 脱敏扩充（URL / IPv4 / 中国身份证）

**目标**：防止 GitHub 链接、内部 IP、身份证号入向量库。

**clean.py 增量**（注意顺序）：

```python
_URL_RE = re.compile(r"https?://[^\s<>\"']+")
_CHINA_ID_RE = re.compile(r"\b\d{17}[\dXx]\b")
_IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
# email / phone / long_digit 沿用旧的

def redact_pii(text: str) -> RedactionResult:
    s = get_settings()
    counts = {
        "email": 0, "phone": 0, "long_digit": 0,
        "url": 0, "china_id": 0, "ip": 0,
    }
    # ... _sub 定义 ...
    t = _sub(_EMAIL_RE, "email", "[email redacted]", text or "")
    if s.pii_extra_patterns:
        t = _sub(_URL_RE, "url", "[url redacted]", t)
    t = _sub(_PHONE_RE, "phone", "[phone redacted]", t)
    if s.pii_extra_patterns:
        t = _sub(_CHINA_ID_RE, "china_id", "[id redacted]", t)
        t = _sub(_IPV4_RE, "ip", "[ip redacted]", t)
    t = _sub(_LONG_DIGITS_RE, "long_digit", "[id redacted]", t)
    return RedactionResult(cleaned=t, redactions=counts)
```

**顺序原则**：
- 身份证 **必须**早于 long_digit（否则 17 位被先吞，X 落单）
- IPv4 **必须**早于 long_digit（`192.168.1.100` 去点后是 10 位数字）
- URL 早于 email（极少数 URL 里嵌了 @ 字符）

**验收（单测）**：
- 6 类 PII 单独匹配 + 计数正确
- 联合字符串（含所有 6 类）脱敏顺序不互相干扰
- `pii_extra_patterns=False` 时新加的 3 类不生效，退回旧行为

---

### Step 4 · ingest._split 改按句切分

**目标**：RAG 召回的 chunk 尊重中文句边界，避免"这个项目我负责架构" 被切成 "这个项目我负" + "责架构"。

**改动**（不加依赖，正则即可）：

```python
import re

_PARA_RE = re.compile(r"\n{2,}")
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?.\n])")

def _split(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []

    chunks: list[str] = []
    buf = ""

    def flush() -> None:
        nonlocal buf
        if buf:
            chunks.append(buf)
            buf = ""

    for para in _PARA_RE.split(text):
        for sent in _SENT_SPLIT_RE.split(para):
            sent = sent.strip("\n")
            if not sent:
                continue
            # 超长句兜底：退化为字符硬切
            if len(sent) > CHUNK_SIZE:
                flush()
                for i in range(0, len(sent), CHUNK_SIZE - CHUNK_OVERLAP):
                    piece = sent[i : i + CHUNK_SIZE]
                    chunks.append(piece)
                continue
            if len(buf) + len(sent) <= CHUNK_SIZE:
                buf += sent
            else:
                flush()
                # 保留 overlap
                if CHUNK_OVERLAP > 0 and chunks:
                    buf = chunks[-1][-CHUNK_OVERLAP:] + sent
                else:
                    buf = sent
        flush()

    return chunks
```

**验收（单测）**：
- 短文本（<CHUNK_SIZE）不变
- 多段落文本：chunk 都以句尾标点结束
- 超长单句（>CHUNK_SIZE 无标点的情况，如代码片段）：退化为字符硬切，每块长度 ≤CHUNK_SIZE
- 中英混合正常工作

---

### Step 5 · trainset 增量导出

**目标**：支持每日增量训练数据集，避免每次全量重扫。

**trainset_builder.py**：

```python
from datetime import datetime

def export_jsonl(
    path: Path,
    *,
    session_ids: Iterable[str] | None = None,
    since: datetime | None = None,
) -> int:
    # ...
    with get_session() as sess:
        stmt = select(GenerationTrace)
        if session_ids is not None:
            stmt = stmt.where(GenerationTrace.session_id.in_(list(session_ids)))
        if since is not None:
            stmt = stmt.where(GenerationTrace.created_at >= since)
        # ...
```

**新脚本 `app/scripts/export_daily_trainset.py`**（强制限制时间窗口）：

```python
"""Export daily incremental trace training set.

Usage:
    python -m app.scripts.export_daily_trainset --days 1 --out ./data/YYYYMMDD.jsonl
    python -m app.scripts.export_daily_trainset --since 2026-04-22T00:00:00 --out ...
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app.data.trainset_builder import export_jsonl


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--since", type=str, default=None)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    if args.days is None and args.since is None:
        raise SystemExit("ERROR: must pass either --days or --since")

    if args.since:
        since = datetime.fromisoformat(args.since)
    else:
        since = datetime.now(timezone.utc) - timedelta(days=args.days)

    n = export_jsonl(Path(args.out), since=since)
    print(f"exported {n} rows since {since.isoformat()} to {args.out}")


if __name__ == "__main__":
    main()
```

**验收（单测）**：
- 写入 3 天跨度的 trace，分别测 `since=None`（全量）和 `since=今天`（部分）的行数
- 手动 `python -m app.scripts.export_daily_trainset --days 1 --out ./tmp.jsonl` 能跑通
- 不传 `--days` 和 `--since` 时脚本退出码非 0

---

### Step 6 · Thompson 三合一（并列 + 锁 + decay）

**目标**：一次修掉 3 个小但紧密耦合的正确性 / 演化能力问题。

**thompson.py 改动**：

```python
import threading

_singleton: ThompsonBandit | None = None
_lock = threading.Lock()


def get_bandit() -> ThompsonBandit:
    global _singleton
    if _singleton is None:
        with _lock:
            if _singleton is None:
                from app.core.settings import get_settings
                _singleton = ThompsonBandit(
                    exploration_rate=get_settings().thompson_exploration_rate
                )
    return _singleton
```

**select 并列修正**（在 `samples` 字典构造之后）：

```python
max_val = max(samples.values())
top = [aid for aid, v in samples.items() if v == max_val]
chosen_id = self.rng.choice(top) if len(top) > 1 else top[0]
```

**新增 `decay`**：

```python
def decay(self, factor: float = 0.99, floor: float = 1.0) -> None:
    """Geometric decay toward prior. Call periodically for non-stationarity.

    factor should be in (0, 1]; smaller = forget faster.
    floor prevents posterior collapsing below the Jeffreys-like prior.
    """
    if factor >= 1.0:
        return
    for p in self.priors.values():
        p.alpha = max(floor, p.alpha * factor)
        p.beta = max(floor, p.beta * factor)
    log.info("bandit decay applied (factor=%.3f floor=%.2f, %d arms)",
             factor, floor, len(self.priors))
```

**验收（单测）**：
1. `select` 并列：给两个臂注入相同 `alpha/beta`，多次运行选择比例应接近 50/50（±10%）
2. `decay(0.5, 1.0)`：α=10, β=5 的臂 decay 后 α=5, β=2.5，不小于 1
3. `decay(1.0)`：early return，不变
4. 多线程并发 `get_bandit()` 返回同一实例

---

### Step 7 · 观测端点（微调 #4）

**目标**：让 decay 和 bandit 状态肉眼可见。

**main.py 增加**：

```python
from fastapi import Depends
from app.core.settings import get_settings as _gs

@app.get("/admin/bandit/snapshot", include_in_schema=False)
async def bandit_snapshot() -> dict:
    from app.ml.rl.thompson import get_bandit
    return {
        "priors": get_bandit().snapshot(),
        "policy_mode": _gs().policy_mode,
        "exploration_rate": _gs().thompson_exploration_rate,
    }
```

**验收**：
- 手动 `curl localhost:8000/admin/bandit/snapshot` 返回有效 JSON
- decay 之前调一次、之后调一次，肉眼能看到 alpha/beta 变化
- **注意**：默认不需要鉴权，但**写一行注释**提醒生产部署要加 auth（不阻塞本次 PR）

---

### Step 8 · decay 调度（可选）

**目标**：把 decay 自动化；默认关闭（`enable_bandit_decay=False`）。

**outcome_sync_tasks.py 补充**：

```python
from app.ml.rl.thompson import get_bandit

def start_decay_scheduler(
    interval_days: int, factor: float, floor: float,
) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        lambda: get_bandit().decay(factor=factor, floor=floor),
        "interval",
        days=interval_days,
        id="bandit_decay",
        replace_existing=True,
    )
    scheduler.start()
    log.info(
        "bandit decay scheduler started (every %d day(s), factor=%.3f, floor=%.2f)",
        interval_days, factor, floor,
    )
    return scheduler
```

**main.py 在 startup 补一段**：

```python
if settings.enable_bandit_decay:
    try:
        from app.tasks.outcome_sync_tasks import start_decay_scheduler
        app.state.decay_scheduler = start_decay_scheduler(
            interval_days=settings.bandit_decay_interval_days,
            factor=settings.bandit_decay_factor,
            floor=settings.bandit_decay_floor,
        )
    except Exception as e:
        log.warning("decay scheduler startup failed: %s", e)
```

在 shutdown 的 for 循环里把 `"decay_scheduler"` 也加进去。

**验收**：
- `enable_bandit_decay=True` 时 startup 日志出现 "bandit decay scheduler started"
- `enable_bandit_decay=False` 时无任何变化（默认行为）

---

## 4. 微调清单（v1 -> v2 演进）

| v1 微调项 | v2 吸收位置 |
|---|---|
| 微调 #1 Step 顺序（backfill 上提） | v2 把 backfill 设为 Step 2，紧跟 Step 1 配置化，符合"先修正确性" |
| 微调 #2 decay factor 默认 0.99 | v2 settings 默认 `bandit_decay_factor=0.99, interval_days=1`，半衰期 ≈ 69 天 |
| 微调 #3 export_daily 强制 --days / --since | v2 Step 5 脚本已强制 |
| 微调 #4 /admin/bandit/snapshot 端点 | v2 Step 7 已单列 |

---

## 5. 风险与回滚

| 风险 | 发生步骤 | 缓解 | 回滚 |
|---|---|---|---|
| `outcome_weights` pydantic 解析 env 失败 | Step 1 | 使用 `Field(default_factory=...)` + 允许 JSON 字符串 env | 保留 `OUTCOME_WEIGHTS` 模块常量作 fallback |
| 按句切分后某些文档 chunk 变多（更碎） | Step 4 | CHUNK_SIZE 硬上限保留；单测覆盖 | 改回 `_split_v1`（保留该函数，仅重命名） |
| 脱敏顺序错导致身份证漏 | Step 3 | 单测专门覆盖顺序 | 调整 `_sub` 调用顺序 |
| Step 2 Phase 2 语义变化破坏现有 backfill 测试 | Step 2 | 跑全量 pytest；counters 字段签名不变 | revert PR |
| decay 系数激进导致 bandit 几天忘光 | Step 6/8 | 默认 `factor=0.99, interval=1 day`；`enable_bandit_decay=False` 默认关 | `enable_bandit_decay=False` |
| `/admin/bandit/snapshot` 信息泄露 | Step 7 | 代码内注释提醒加 auth；默认 `include_in_schema=False` 不入 OpenAPI | 删除该路由 |

每步独立 PR、独立 commit，revert 成本为单文件级。

---

## 6. 测试策略

**加**（5 个新测试文件，约 15–20 个 case）：

| 测试文件 | 覆盖 |
|---|---|
| `tests/data/test_clean_extended.py` | URL / IPv4 / 中国身份证匹配；6 类联合；顺序敏感用例；`pii_extra_patterns=False` 回退 |
| `tests/data/test_split_sentence.py` | 短文本 / 多段落 / 中英混合 / 超长句兜底 |
| `tests/data/test_trainset_incremental.py` | `since=None` vs `since=今天` 的行数差异 |
| `tests/ml/rl/test_thompson_extra.py` | 并列随机性 / decay / threading.Lock |
| `tests/ml/rl/test_backfill_two_phase.py` | 正常 / Phase 2 失败 + rehydrate / 幂等 |

**不加**：
- `reward_fn` / `outcome_reward_bridge` 单纯读配置的路径（行为不变，现有 unit 已覆盖）
- `export_daily_trainset.py` 脚本（手工验证一次即可）
- `/admin/bandit/snapshot` 端点（smoke test 即可）
- decay 调度器本身（APScheduler 行为不适合单测；手工验证 startup 日志）

**关键测试基础设施**：
- `get_settings` 用了 `@lru_cache`，测试改 settings 时需要 `get_settings.cache_clear()`
- `thompson._singleton` 需要 `reset_bandit_for_tests()` 清除

---

## 7. 验收标准（DoD）

- [ ] Step 1–7 合入主干；Step 8 可选
- [ ] 全量 pytest 通过，覆盖率不低于当前基线
- [ ] `curl localhost:8000/admin/bandit/snapshot` 能返回有效 JSON
- [ ] 手动：
  - 跑 `python -m app.scripts.export_daily_trainset --days 1 --out /tmp/t.jsonl` 成功
  - 跑 `backfill_once()` 两次，第二次 counters 全零（幂等确认）
  - `enable_bandit_decay=True` 启动后日志出现 "bandit decay scheduler started"
- [ ] 新魔数项默认值与历史行为等价（差分测试：全量 pytest 在 v1 / v2 行为一致）
- [ ] README 或 docs/ 追加一段 "RL 调参入口" 列出所有 settings 字段的含义

---

## 8. 预估工作量

| Step | 代码 | 测试 | 文档 | 合计 |
|---|---|---|---|---|
| 1 配置化 | 0.5h | 0.1h | 0.1h | 0.7h |
| 2 backfill 两阶段 | 0.8h | 1.2h | 0.1h | 2.1h |
| 3 脱敏扩充 | 0.5h | 0.5h | 0 | 1.0h |
| 4 按句切分 | 1.0h | 0.8h | 0 | 1.8h |
| 5 增量导出 | 0.6h | 0.4h | 0.2h | 1.2h |
| 6 Thompson 三合一 | 0.8h | 0.8h | 0.1h | 1.7h |
| 7 snapshot 端点 | 0.2h | 0 | 0.1h | 0.3h |
| 8 decay 调度（可选） | 0.4h | 0 | 0.2h | 0.6h |
| 文档收尾 | 0 | 0 | 0.5h | 0.5h |

**合计 ≈ 9.9 人时**（不含 review），分布在 2–3 个工作日内合理。

---

## 9. 延后项（记录在案，不做）

| 项 | 触发条件 |
|---|---|
| M2 聚合 `rehydrate_from_db`（SQL GROUP BY 而非逐条重放） | trace > 10 万行时 |
| M4 扩展 `action_space.allowed_actions` 统一函数 | 新增第 6 / 7 个动作 |
| M5 NER 脱敏（spaCy zh_core_web_sm） | 合规要求升级或客户投诉 |
| L1 Gaussian bandit | evaluator 分布诊断完成，确认 Beta fractional 偏差显著 |
| L2 OPE（IPS / Doubly Robust） | trace schema 加 `propensity` 列 |
| L3 Redis 中心化 bandit 状态 | 部署形态变为多 worker / 多进程 |
| L4 学习型 reward model | trace > 5k + OutcomeRecord > 2k |
| DPO / SFT 微调 | OutcomeRecord ≥ 2000 + evaluator rubric 稳定 3 个月 |
| Verifier 触发策略进入 bandit | 当前 rule-based `should_trigger` 的数据显示触发率 / 效果有优化空间 |
| LangSmith 作品集页面 | 非代码项：开启 tracing + 截 screen / 导 trace 片段即可 |

---

## 10. 执行触发

本 plan 确认后，可按两种方式推进：

- **A. 按 Step N 出 diff**（推荐）：我按 1 → 8 逐步出 PR 级 diff，每一步完成后等你 review 再继续
- **B. 一次性全部实现 Step 1–7**：我连续执行，最后汇报改动清单；测试失败时自动回滚该步

默认走 A。
