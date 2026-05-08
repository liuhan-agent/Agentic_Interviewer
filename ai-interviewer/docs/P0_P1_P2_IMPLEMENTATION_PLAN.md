# P0/P1/P2 改进实施计划

**目标：** 将当前 AI 面试官项目从“可运行 Demo / 本地预览”推进到“可上线预览环境”的工程状态，优先保证会话不丢、配置不误用、评分可信、隐私可控，并逐步补齐复练闭环。

**架构：** 前端继续保持薄 UI；后端以 FastAPI + LangGraph 为主链；Redis、PostgreSQL、Chroma、Trace/Admin 作为运行与观测支撑。所有改动遵循“主链体验优先，旁路增强不阻塞面试”的现有边界。

**技术栈：** Python 3.11、FastAPI、LangGraph、SQLAlchemy、Redis、Chroma、pytest、Next.js 14、TypeScript、Tailwind、shadcn/ui。

## 默认假设

- 计划面向“可上线预览环境”，不是仅本地 Demo。
- 后端可能以多 worker 或多副本方式部署，因此 P0 默认按共享状态设计。
- 先产出计划文档；具体代码实现按任务顺序单独执行。
- 不引入用户系统和多租户，继续沿用匿名 session token 模型。
- 不重构 `interview.py` 和 `session_manager.py` 的大结构，只做小范围增强和测试补强。

## 总体优先级

| 优先级 | 目标 | 主要结果 |
| --- | --- | --- |
| P0 | 上线底线 | 生产配置可验证、多 worker 风险可控、HITL 会话恢复稳定 |
| P1 | 用户信任 | 报告可信度可解释、隐私删除和留存闭环、C 端语言统一 |
| P2 | 增长体验 | 薄弱点专项练习、admin 信息架构优化、后续执行节奏固化 |

## 执行看板

### 建议 PR 批次

| 批次 | 范围 | 目标 | Gate |
| --- | --- | --- | --- |
| PR-1 | P0-1 + P0-3 | 先补预检命令和 HITL 测试护栏 | `pytest tests/unit/test_deployment_preflight.py tests/unit/test_production_smoke.py tests/unit/test_hitl_turn_consistency.py tests/unit/test_session_recovery.py tests/unit/test_ws_voice.py -q` |
| PR-2 | P0-2 | 单独处理 Redis / shared state，避免和 UI 混改 | `pytest tests/unit/test_rate_limit.py tests/unit/test_voice_ticket.py tests/unit/test_verifier_drift.py -q` |
| PR-3 | P1-1 + P1-2 | 提升评分可信度和隐私闭环 | `pytest tests/unit/test_scoring_credibility.py tests/unit/test_final_report_evidence.py tests/unit/test_session_delete_api.py tests/unit/test_privacy_cleanup.py tests/unit/test_privacy_cleanup_tasks.py -q` + frontend typecheck/source tests |
| PR-4 | P1-3 + P2-1 | 统一 C 端语言并打通专项练习入口 | 后端相关 pytest + `npm run typecheck` |
| PR-5 | P2-2 + P2-3 | 整理 admin 信息架构并固化执行流程 | `npm run typecheck && npm run lint` |

### Issue 状态表

| ID | 阶段 | Issue | 类型 | 建议批次 | Blocked by | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| P0-1.1 | P0 | Production smoke CLI 最小可运行 | AFK | PR-1 | None | Ready |
| P0-1.2 | P0 | P0 生产失败契约测试 | AFK | PR-1 | P0-1.1 | Ready |
| P0-1.3 | P0 | 依赖连通性 probe | AFK | PR-1 | P0-1.1 | Ready |
| P0-1.4 | P0 | 脚本入口与文档接入 | AFK | PR-1 | P0-1.1 | Ready |
| P0-1.5 | P0 | probe 严格度决策 | HITL | PR-1 | P0-1.3 | Needs decision |
| P0-2.1 | P0 | 共享状态 backend 配置契约 | AFK | PR-2 | None | Ready |
| P0-2.2 | P0 | RateLimiter 接口与 memory parity | AFK | PR-2 | P0-2.1 | Ready |
| P0-2.3 | P0 | Redis-backed rate limit | AFK | PR-2 | P0-2.2 | Ready |
| P0-2.4 | P0 | VoiceTicketStore 抽象与 Redis store | AFK | PR-2 | P0-2.1 | Ready |
| P0-2.5 | P0 | Verifier drift Redis backend | AFK | PR-2 | P0-2.1 | Ready |
| P0-2.6 | P0 | 生产 preflight 与部署文档接入 | HITL | PR-2 | P0-2.3、P0-2.4、P0-2.5 | Needs decision |
| P0-3.1 | P0 | `turn_idx` 防重复提交回归 | AFK | PR-1 | None | Ready |
| P0-3.2 | P0 | skip / submit 交叉路径回归 | AFK | PR-1 | P0-3.1 | Ready |
| P0-3.3 | P0 | cancel 终态保护回归 | AFK | PR-1 | None | Ready |
| P0-3.4 | P0 | rehydrate 冷启动恢复回归 | AFK | PR-1 | P0-3.1、P0-3.2 | Ready |
| P0-3.5 | P0 | voice disconnect / text resume 回归 | AFK | PR-1 | P0-3.3 | Ready |
| P0-3.6 | P0 | 暴露问题后的最小修复 | HITL | PR-1 | P0-3.1 - P0-3.5 | Conditional |
| P1-1.1 | P1 | `final_report` 可信度字段契约 | AFK | PR-3 | None | Ready |
| P1-1.2 | P1 | 后端可信度规则回归 | AFK | PR-3 | P1-1.1 | Ready |
| P1-1.3 | P1 | 前端类型与兼容处理 | AFK | PR-3 | P1-1.1 | Ready |
| P1-1.4 | P1 | `ReportView` 可信度卡片 | AFK | PR-3 | P1-1.3 | Ready |
| P1-1.5 | P1 | 用户文案口径确认 | HITL | PR-3 | P1-1.4 | Needs decision |
| P1-2.1 | P1 | privacy cleanup 调度器 | AFK | PR-3 | None | Done |
| P1-2.2 | P1 | `main.py` startup/shutdown 接入 | AFK | PR-3 | P1-2.1 | Done |
| P1-2.3 | P1 | 删除结果 API 契约加固 | AFK | PR-3 | None | Done |
| P1-2.4 | P1 | 前端历史页删除语义区分 | AFK | PR-3 | P1-2.3 | Done |
| P1-2.5 | P1 | 默认留存策略确认 | HITL | PR-3 | P1-2.1、P1-2.2 | Done |
| P1-3.1 | P1 | 外显招聘语义审计 | AFK | PR-4 | None | Done |
| P1-3.2 | P1 | verdict 展示映射统一 | AFK | PR-4 | P1-3.1 | Done |
| P1-3.3 | P1 | 报告页与历史页文案替换 | AFK | PR-4 | P1-3.2 | Done |
| P1-3.4 | P1 | 产品边界文档补强 | AFK | PR-4 | P1-3.1 | Done |
| P1-3.5 | P1 | 产品词表确认 | HITL | PR-4 | P1-3.2、P1-3.3 | Done |
| P2-1.1 | P2 | 弱项专项练习入口 URL | AFK | PR-4 | None | Ready |
| P2-1.2 | P2 | `SetupForm` 读取 focus 并预填 | AFK | PR-4 | P2-1.1 | Ready |
| P2-1.3 | P2 | start session 请求契约扩展 | AFK | PR-4 | P2-1.2 | Ready |
| P2-1.4 | P2 | 后端 focus 维度校验与状态落位 | AFK | PR-4 | P2-1.3 | Ready |
| P2-1.5 | P2 | Director 优先调度 focus 维度 | AFK | PR-4 | P2-1.4 | Ready |
| P2-1.6 | P2 | 非法 focus 策略确认 | HITL | PR-4 | P2-1.4 | Needs decision |
| P2-2.1 | P2 | Admin 信息架构骨架 | AFK | PR-5 | None | Done |
| P2-2.2 | P2 | 运行健康区域迁移 | AFK | PR-5 | P2-2.1 | Done |
| P2-2.3 | P2 | 评分质量区域迁移 | AFK | PR-5 | P2-2.1 | Done |
| P2-2.4 | P2 | 策略学习区域迁移 | AFK | PR-5 | P2-2.1 | Done |
| P2-2.5 | P2 | `AdminPanel` 组件拆分清理 | AFK | PR-5 | P2-2.2、P2-2.3、P2-2.4 | Done |
| P2-2.6 | P2 | admin 默认视角确认 | HITL | PR-5 | P2-2.1 | Done |
| P2-3.1 | P2 | P0/P1/P2 执行看板文档 | AFK | PR-5 | 当前 issue 拆分完成 | Done |
| P2-3.2 | P2 | 验证命令矩阵 | AFK | PR-5 | P2-3.1 | Ready |
| P2-3.3 | P2 | PR 切分规则 | AFK | PR-5 | P2-3.1 | Ready |
| P2-3.4 | P2 | HITL 决策清单 | HITL | PR-5 | P2-3.1 | Needs decision |
| P2-3.5 | P2 | 完成定义与 release gate | AFK | PR-5 | P2-3.2、P2-3.3、P2-3.4 | Ready |
| P2-3.6 | P2 | 是否发布到 GitHub Issues | HITL | PR-5 | P2-3.1 - P2-3.5 | Needs decision |

### 验证命令矩阵

| 批次 | 最小验证 | 全量验证 | 基础设施依赖 |
| --- | --- | --- | --- |
| PR-1 | `pytest tests/unit/test_deployment_preflight.py tests/unit/test_production_smoke.py tests/unit/test_hitl_turn_consistency.py tests/unit/test_session_recovery.py tests/unit/test_ws_voice.py -q` | `pytest tests/unit -q` | 单测应默认 mock 外部依赖；真实 smoke 可选依赖 Postgres / Redis / Chroma |
| PR-2 | `pytest tests/unit/test_rate_limit.py tests/unit/test_voice_ticket.py tests/unit/test_verifier_drift.py -q` | `pytest tests/unit -q` | Redis backend 单测必须使用 fake Redis / monkeypatch；真实集成验证需要 Redis |
| PR-3 | `pytest tests/unit/test_scoring_credibility.py tests/unit/test_final_report_evidence.py tests/unit/test_session_delete_api.py tests/unit/test_privacy_cleanup.py tests/unit/test_privacy_cleanup_tasks.py -q` + `node --test tests/historyListSource.test.js tests/setupCopy.test.js` | `pytest tests/unit -q && cd ..\frontend && npm run typecheck` | 隐私清理单测不应删除真实数据；调度测试使用 mock scheduler |
| PR-4 | `pytest tests/unit/test_request_translator.py tests/unit/test_director_sample.py -q && cd ..\frontend && npm run typecheck` | `pytest tests/unit -q && cd ..\frontend && npm run typecheck && npm run lint && npm run build` | 专项练习后端单测无需真实模型；前端 build 需要 Node/npm 依赖完整 |
| PR-5 | `cd frontend && npm run typecheck && npm run lint` | `cd backend && pytest tests/unit -q && cd ..\frontend && npm run typecheck && npm run lint && npm run build` | 仅 admin 前端整理不应要求后端服务运行；手工验收 `/admin` 需要 backend |

**全仓最终 gate：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
pytest tests/unit -q
cd ..\frontend
npm run typecheck
npm run lint
npm run build
```

**真实预览 smoke：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
docker compose up -d postgres redis chroma
interviewer-prod-smoke
```

真实预览 smoke 依赖 Postgres、Redis、Chroma 可达；普通单元测试不得依赖这些服务。

## P0：上线底线

### P0-1 生产 smoke/preflight 命令

**目的：** 把 `backend/docs/PLAN_PRODUCTION_DEPLOY.md` 中的人工检查固化成可执行命令，避免生产环境用开发默认值启动。

**涉及文件：**

| 文件 | 职责 |
| --- | --- |
| `backend/app/scripts/production_smoke.py` | 新增生产预检 CLI |
| `backend/pyproject.toml` | 暴露脚本入口 |
| `backend/tests/unit/test_production_smoke.py` | 覆盖 CLI 行为 |
| `backend/docs/PLAN_PRODUCTION_DEPLOY.md` | 追加命令说明 |

**实施步骤：**

1. 新增 `production_smoke.py`，复用 `app.core.deployment_preflight.run_preflight()`。
2. 输出 sanitized config summary，只展示布尔值、枚举、host/port，不输出 token / key。
3. 增加可选连通性检查：Postgres、Redis、Chroma heartbeat。
4. 在 `pyproject.toml` 增加脚本入口：`interviewer-prod-smoke = "app.scripts.production_smoke:main"`。
5. 单测覆盖 prod 缺 token、memory checkpoint、stub LLM、valid config、密钥不泄露。

**验证：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
pytest tests/unit/test_deployment_preflight.py tests/unit/test_production_smoke.py -q
```

**完成标准：**

- `APP_ENV=prod` 下高风险配置会失败。
- valid config 输出成功摘要。
- 测试确认输出中不包含 API key / token 原文。

#### P0-1 Issue 拆分

| Issue | 类型 | Blocked by | 目标 |
| --- | --- | --- | --- |
| Production smoke CLI 最小可运行 | AFK | None | 新增 `backend/app/scripts/production_smoke.py`，调用 `run_preflight()`，输出 sanitized summary，并用退出码表达成功/失败 |
| P0 生产失败契约测试 | AFK | Production smoke CLI 最小可运行 | 覆盖 prod 下 memory checkpoint、空 token、stub LLM、stub embedding、memory resume cache 等失败契约 |
| 依赖连通性 probe | AFK | Production smoke CLI 最小可运行 | 给 CLI 增加 Postgres、Redis、Chroma 可选连通性检查，测试中可 monkeypatch |
| 脚本入口与文档接入 | AFK | Production smoke CLI 最小可运行 | 在 `pyproject.toml` 暴露 `interviewer-prod-smoke`，并更新生产部署清单 |
| probe 严格度决策 | HITL | 依赖连通性 probe | 决定 preview/staging 中 Redis / Chroma 不可达时 hard fail 还是 warning；默认建议 prod hard fail，preview/staging/dev warning |

**Issue 发布前检查：**

- 每个 issue 都能独立验证。
- blocker 顺序为 1 -> 2/3/4 -> 5。
- 不把 P0-2 的 Redis 共享状态实现混入 P0-1，只在 P0-1 中检查依赖可达性。

### P0-2 共享状态后端

**目的：** 解决多 worker / 多副本下进程内状态分裂问题。

**涉及文件：**

| 文件 | 职责 |
| --- | --- |
| `backend/app/core/rate_limit.py` | 抽象并实现 rate limiter backend |
| `backend/app/core/voice_ticket.py` | 抽象并实现 voice ticket store |
| `backend/app/ml/drift/verifier_drift.py` | 支持 Redis drift backend |
| `backend/app/core/settings.py` | 新增 backend 配置项 |
| `backend/tests/unit/test_rate_limit.py` | 限流回归 |
| `backend/tests/unit/test_voice_ticket.py` | 语音票据回归 |
| `backend/tests/unit/test_verifier_drift.py` | drift backend 回归 |

**实施步骤：**

1. 给 rate limit 抽 `RateLimiter` 接口，保留当前 in-memory 实现。
2. 新增 Redis-backed sliding window，key 包含 endpoint + client fingerprint。
3. 给 voice ticket 抽 `VoiceTicketStore`，新增 Redis store，保留 memory store 给 dev。
4. 给 verifier drift monitor 增加 Redis backend，memory backend 仅用于 dev / test。
5. settings 增加 `RATE_LIMIT_BACKEND`、`VOICE_TICKET_BACKEND`、`VERIFIER_DRIFT_BACKEND`。
6. prod preflight 中对多 worker 相关 memory backend 给出硬失败或强告警。

**验证：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
pytest tests/unit/test_rate_limit.py tests/unit/test_voice_ticket.py tests/unit/test_verifier_drift.py -q
```

**完成标准：**

- memory backend 保持 dev 可用。
- Redis backend 可通过 fake Redis / monkeypatch 测试。
- 多 worker 风险不再只停留在文档提醒。

#### P0-2 Issue 拆分

| Issue | 类型 | Blocked by | 目标 |
| --- | --- | --- | --- |
| 共享状态 backend 配置契约 | AFK | None | 在 `settings.py` 明确 `RATE_LIMIT_BACKEND`、`VOICE_TICKET_BACKEND`、`VERIFIER_DRIFT_BACKEND`，并让 preflight summary 展示当前 backend |
| RateLimiter 接口与 memory parity | AFK | 共享状态 backend 配置契约 | 将 `rate_limit.py` 现有进程内实现包装成 `MemoryRateLimiter`，保留 `check_rate_limit()` 外部调用签名 |
| Redis-backed rate limit | AFK | RateLimiter 接口与 memory parity | 新增 Redis sliding-window limiter，key 包含 endpoint + client fingerprint，超限仍抛 `RateLimitExceededError` |
| VoiceTicketStore 抽象与 Redis store | AFK | 共享状态 backend 配置契约 | 给 `voice_ticket.py` 抽 store 接口，Redis store 支持多 worker 一次性消费和 TTL |
| Verifier drift Redis backend | AFK | 共享状态 backend 配置契约 | 给 verifier drift monitor 增加 Redis-backed rolling window，保持 admin drift snapshot API shape 不变 |
| 生产 preflight 与部署文档接入 | HITL | Redis-backed rate limit、VoiceTicketStore 抽象与 Redis store、Verifier drift Redis backend | 决定 prod 中 memory backend hard fail / warning 策略；默认建议 rate limit 和 voice ticket hard fail，drift memory warning |

**Issue 发布前检查：**

- P0-2 不和 P0-1 的 smoke CLI 混在一个改动中。
- Redis 相关实现必须可在无真实 Redis 的单测中验证。
- dev/test 默认 memory backend 继续可用，避免破坏本地启动。
- prod/preflight 对多 worker 不安全组合必须给出明确诊断。

### P0-3 HITL 会话恢复回归矩阵

**目的：** 保护 `session_manager.py` 中最容易出事故的 interrupt/resume 状态机。

**涉及文件：**

| 文件 | 职责 |
| --- | --- |
| `backend/tests/unit/test_hitl_turn_consistency.py` | turn 一致性 |
| `backend/tests/unit/test_session_recovery.py` | 恢复路径 |
| `backend/tests/unit/test_ws_voice.py` | 语音断开 / 完成态 |
| `backend/app/services/session_manager.py` | 仅在测试暴露 bug 时小修 |

**实施步骤：**

1. 增加重复提交同一 turn 的测试，期望第二次提交失败且不推进。
2. 增加 skip 后 submit 的测试，期望旧 turn answer 被拒绝。
3. 增加 cancel after done 的测试，期望已完成会话不被覆盖成 cancelled。
4. 增加 rehydrate 后 `turn_idx` / `asked_turn` / `current_question` 一致性测试。
5. 增加 voice disconnect 后文本页 resume 不误报 cancelled 的测试。

**验证：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
pytest tests/unit/test_hitl_turn_consistency.py tests/unit/test_session_recovery.py tests/unit/test_ws_voice.py -q
```

**完成标准：**

- 所有 HITL 边界测试稳定通过。
- 如果必须改 `session_manager.py`，只做针对性修复，不做结构重构。

#### P0-3 Issue 拆分

| Issue | 类型 | Blocked by | 目标 |
| --- | --- | --- | --- |
| `turn_idx` 防重复提交回归 | AFK | None | 在 `test_hitl_turn_consistency.py` 覆盖同一 `turn_idx` 重复 submit、旧 turn submit、未等待问题时 submit |
| skip / submit 交叉路径回归 | AFK | `turn_idx` 防重复提交回归 | 覆盖 skip 当前题后旧 answer 再提交、重复 skip、skip 后下一题轮次递增一致 |
| cancel 终态保护回归 | AFK | None | 覆盖 running cancel、interrupted cancel、completed cancel，尤其保护完成态不被覆盖成 cancelled |
| rehydrate 冷启动恢复回归 | AFK | `turn_idx` 防重复提交回归、skip / submit 交叉路径回归 | 模拟 DB interrupted row，恢复后可 poll 当前问题、提交答案并继续 |
| voice disconnect / text resume 回归 | AFK | cancel 终态保护回归 | 覆盖语音 WebSocket 正常结束、异常断开、完成后 finally cancel，确保文本页 resume 不误报 cancelled |
| 暴露问题后的最小修复 | HITL | 前 5 个测试 issue | 新增测试暴露 `session_manager.py` bug 时只做针对性修复；如需结构重构必须先回到 HITL 确认 |

**Issue 发布前检查：**

- P0-3 以测试先行为主，不主动重构 `session_manager.py`。
- 每个 issue 都能独立失败 / 独立通过。
- 修复类 issue 只有在测试暴露真实 bug 后才启动。
- voice 相关测试要覆盖正常完成和异常断开两类 teardown。

## P1：用户信任

### P1-1 报告可信度展示产品化

**目的：** 让用户知道本次评分信号是否可靠，而不是只看到一个看似精确的分数。

**涉及文件：**

| 文件 | 职责 |
| --- | --- |
| `backend/app/services/scoring_credibility.py` | 可信度规则 |
| `backend/app/engine/workflow/nodes/final_report.py` | 写入 final_report |
| `frontend/src/lib/api/types.ts` | 类型定义 |
| `frontend/src/components/interview/ReportView.tsx` | 展示可信度卡片 |
| `backend/tests/unit/test_scoring_credibility.py` | 后端规则测试 |
| `backend/tests/unit/test_final_report_evidence.py` | report 接入测试 |

**实施步骤：**

1. 确认 final report 输出 `scoring_credibility`。
2. 字段包含 `level`、`fallback_rate`、`evidence_span_miss_rate`、`contract_no_rate`、`warnings`。
3. 前端类型补齐该字段。
4. `ReportView` 顶部展示“评分可信度：高 / 中 / 低”。
5. 中低可信度时展示用户友好提示，不暴露内部异常或模型供应商细节。

**验证：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
pytest tests/unit/test_scoring_credibility.py tests/unit/test_final_report_evidence.py -q
cd ..\frontend
npm run typecheck
```

**完成标准：**

- 用户能看到可信度等级和原因。
- fallback 场景不会被包装成高可信评分。

#### P1-1 Issue 拆分

| Issue | 类型 | Blocked by | 目标 |
| --- | --- | --- | --- |
| `final_report` 可信度字段契约 | AFK | None | 明确 `final_report.scoring_credibility` 稳定字段：`level`、`fallback_rate`、`evidence_span_miss_rate`、`contract_no_rate`、`warnings` |
| 后端可信度规则回归 | AFK | `final_report` 可信度字段契约 | 补齐 fallback、span miss、contract no、forced refine、zero-turn 等规则测试 |
| 前端类型与兼容处理 | AFK | `final_report` 可信度字段契约 | 在 `frontend/src/lib/api/types.ts` 增加 `ScoringCredibility` 类型，并让旧报告缺字段时优雅降级 |
| `ReportView` 可信度卡片 | AFK | 前端类型与兼容处理 | 在报告顶部展示“评分可信度：高 / 中 / 低”，解释影响因素，不暴露内部异常文本 |
| 用户文案口径确认 | HITL | `ReportView` 可信度卡片 | 决定低可信度时建议“重新练习一场”还是“继续查看但谨慎参考”；默认建议后者 |

**Issue 发布前检查：**

- P1-1 不改变评分算法本身，只改变可信度计算和展示。
- 历史报告缺少 `scoring_credibility` 时前端不能崩溃。
- 低可信度文案应降低误导，不制造恐慌。
- UI 不复述 provider 错误、内部异常或敏感配置。

### P1-2 隐私删除与留存调度闭环

**目的：** 让简历、回答、trace、outcome 有可执行的删除和过期清理路径。

**涉及文件：**

| 文件 | 职责 |
| --- | --- |
| `backend/app/services/privacy_cleanup.py` | 删除和过期清理 |
| `backend/app/tasks/privacy_cleanup_tasks.py` | 新增调度器 |
| `backend/app/main.py` | startup/shutdown 接入 |
| `frontend/src/components/interview/HistoryList.tsx` | 删除语义展示 |
| `backend/tests/unit/test_privacy_cleanup.py` | 服务测试 |
| `backend/tests/unit/test_privacy_cleanup_tasks.py` | 调度测试 |

**实施步骤：**

1. 新增 cleanup scheduler，按 settings 间隔执行 `cleanup_expired_data(dry_run=False)`。
2. `main.py` startup 按开关启动，shutdown 统一关闭。
3. 前端历史页区分“仅从本机列表移除”和“删除服务端面试数据”。
4. 删除完成提示展示 session / trace / outcome 删除结果。

**验证：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
pytest tests/unit/test_privacy_cleanup.py tests/unit/test_privacy_cleanup_tasks.py -q
```

**完成标准：**

- 删除动作可审计。
- 过期清理有调度入口，不只停留在手工脚本。

#### P1-2 Issue 拆分

| Issue | 类型 | Blocked by | 目标 |
| --- | --- | --- | --- |
| privacy cleanup 调度器 | AFK | None | 新增 `backend/app/tasks/privacy_cleanup_tasks.py`，按 settings 间隔调用 `cleanup_expired_data(dry_run=False)` |
| `main.py` startup/shutdown 接入 | AFK | privacy cleanup 调度器 | 在 FastAPI 生命周期中按开关启动 cleanup scheduler，并在 shutdown 统一关闭 |
| 删除结果 API 契约加固 | AFK | None | 稳定返回 session / trace / outcome 删除数量，删除不存在 session 时返回 `deleted=false` |
| 前端历史页删除语义区分 | AFK | 删除结果 API 契约加固 | 在 `HistoryList` 中区分“仅从本机列表移除”和“删除服务端面试数据”，并展示服务端删除结果 |
| 默认留存策略确认 | HITL | privacy cleanup 调度器、`main.py` startup/shutdown 接入 | 决定默认 retention 天数是否沿用 settings；默认建议沿用 settings，preview 通过 `.env` 显式缩短 |

**Issue 发布前检查：**

- dev/test 默认不得意外删除数据。
- 删除接口不返回用户回答、简历正文或 trace payload。
- 调度器失败不得阻断主服务启动。
- 前端必须让用户明确区分“本地列表移除”和“服务端数据删除”。

### P1-3 C 端产品语言统一

**目的：** 避免产品被历史招聘字段带偏，保持“练习 / 反馈 / 成长”定位。

**涉及文件：**

| 文件 | 职责 |
| --- | --- |
| `frontend/src/lib/constants/verdicts.ts` | verdict 展示映射 |
| `frontend/src/components/interview/ReportView.tsx` | 报告文案 |
| `frontend/src/components/interview/HistoryList.tsx` | 历史文案 |
| `README.md`、`ai-interviewer/README.md` | 产品边界说明 |

**实施步骤：**

1. 搜索 `hire`、`no_hire`、`录用`、`淘汰`、`candidate` 等外显文案。
2. 内部兼容字段保留；面向用户展示统一映射为成长信号。
3. README 保留“历史命名兼容”说明，避免开发者误删字段。

**验证：**

```powershell
cd D:\Agent\Agentic_Interviewer
rg "录用|淘汰|hire|no_hire" ai-interviewer/frontend/src README.md ai-interviewer/README.md
```

**完成标准：**

- 外显文案不出现招聘决策导向。
- 内部兼容字段有明确说明。

#### P1-3 Issue 拆分

| Issue | 类型 | Blocked by | 目标 |
| --- | --- | --- | --- |
| 外显招聘语义审计 | AFK | None | 搜索 `hire/no_hire/strong_hire/录用/淘汰/candidate` 等关键词，区分内部字段、兼容说明和用户可见文案 |
| verdict 展示映射统一 | AFK | 外显招聘语义审计 | 在 `frontend/src/lib/constants/verdicts.ts` 统一 verdict / growth signal 展示映射，避免页面各自翻译 |
| 报告页与历史页文案替换 | AFK | verdict 展示映射统一 | 更新 `ReportView`、`HistoryList` 等用户可见页面，把招聘判断替换为训练反馈语义 |
| 产品边界文档补强 | AFK | 外显招聘语义审计 | 更新 `README.md`、`ai-interviewer/README.md`，明确内部字段是历史兼容，对外是 C 端成长反馈 |
| 产品词表确认 | HITL | verdict 展示映射统一、报告页与历史页文案替换 | 确认默认词表：`表现优秀 / 达到目标水平 / 接近达标 / 重点补齐 / 已取消 / 暂无结论` |

**Issue 发布前检查：**

- 内部字段不因文案统一被误删。
- 用户可见页面不出现招聘决策导向。
- verdict label 统一从常量层读取，不在多个组件中散落翻译。
- README 中保留历史命名兼容说明，避免后续开发者误判。

## P2：增长体验

### P2-1 薄弱点专项练习闭环

**目的：** 把报告里的“下一场训练建议”变成可点击、可启动的新练习。

**涉及文件：**

| 文件 | 职责 |
| --- | --- |
| `frontend/src/components/interview/ProgressChart.tsx` | 生成弱项练习入口 |
| `frontend/src/components/interview/ReportView.tsx` | 报告页训练入口 |
| `frontend/src/components/interview/SetupForm.tsx` | 读取 focus query 并预填 |
| `frontend/src/lib/sessionDelta.ts` | 弱项维度计算 |
| `backend/app/core/request_translator.py` | 接收 focus dimensions |
| `backend/app/engine/workflow/state.py` | 初始状态保存 focus |
| `backend/app/engine/workflow/nodes/director_sample.py` | 提高 focus 维度优先级 |

**实施步骤：**

1. 前端跳转时携带 query：`/interview/setup?focus=system_design,communication`。
2. `SetupForm` 读取 `focus`，预选维度并展示“本场专项练习聚焦”。
3. start session 请求携带 `focus_dimensions`。
4. 后端 translator 校验 focus dimensions 必须属于当前 rubric dimensions。
5. director 优先选择 focus 维度，但不破坏 max_turns / turn_budget。

**验证：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm run typecheck
cd ..\backend
pytest tests/unit/test_request_translator.py tests/unit/test_director_sample.py -q
```

**完成标准：**

- 从报告或历史弱项入口能启动专项练习。
- 后端不会接受不存在的维度。

#### P2-1 Issue 拆分

| Issue | 类型 | Blocked by | 目标 |
| --- | --- | --- | --- |
| 弱项专项练习入口 URL | AFK | None | 在 `ProgressChart` / `ReportView` 中生成 `/interview/setup?focus=dim1,dim2` 入口，复用 `sessionDelta` 的弱项计算 |
| `SetupForm` 读取 focus 并预填 | AFK | 弱项专项练习入口 URL | 读取 query focus，预选 rubric dimensions，并展示“本场专项练习聚焦” |
| start session 请求契约扩展 | AFK | `SetupForm` 读取 focus 并预填 | 前后端类型增加 `focus_dimensions`，由 setup 提交给后端 |
| 后端 focus 维度校验与状态落位 | AFK | start session 请求契约扩展 | `request_translator.py` 校验 focus 必须属于当前 rubric dimensions，并写入初始 state / runtime_config |
| Director 优先调度 focus 维度 | AFK | 后端 focus 维度校验与状态落位 | `director_sample.py` 优先选择 focus dimensions，但不破坏 max_turns、turn_budget、已 passed 维度 |
| 非法 focus 策略确认 | HITL | 后端 focus 维度校验与状态落位 | 决定 URL 中非法维度时 silently ignore 还是 toast 提示；默认建议前端轻提示、后端防御性过滤 |

**Issue 发布前检查：**

- focus 参数不应破坏无 focus 的原始开始面试流程。
- 维度校验必须以后端为准，前端只做体验层过滤。
- focus 维度通过后仍受 `max_turns`、`turn_budget`、`dimension_status` 约束。
- 专项练习入口只在有足够弱项信号时展示。

### P2-2 admin 面板信息架构拆分

**目的：** 把当前工程型 admin 面板整理成更容易复盘的三个视角。

**涉及文件：**

| 文件 | 职责 |
| --- | --- |
| `frontend/src/components/admin/AdminPanel.tsx` | 页面编排 |
| `frontend/src/components/admin/RagEvalPanel.tsx` | RAG/评分质量 |
| `frontend/src/components/admin/TraceExplorer.tsx` | 单场 trace |
| `frontend/src/lib/api/admin.ts` | 保持现有 API client |

**实施步骤：**

1. 不改后端 API，先做前端信息架构。
2. 拆出三个区域：运行健康、评分质量、策略学习。
3. 运行健康展示 health、trace rollup、fallback rates。
4. 评分质量展示 evidence rollup、question quality、verifier drift。
5. 策略学习展示 bandit snapshot、strategy memory、recent traces。

**验证：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm run typecheck
npm run lint
```

**完成标准：**

- `/admin` 保持现有功能。
- token 保存、刷新、错误态不回归。

#### P2-2 Issue 拆分

| Issue | 类型 | Blocked by | 目标 |
| --- | --- | --- | --- |
| Admin 信息架构骨架 | AFK | None | 在 `AdminPanel.tsx` 中建立“运行健康 / 评分质量 / 策略学习”三个区域或 Tab 的编排骨架，现有 fetcher 暂不改 |
| 运行健康区域迁移 | AFK | Admin 信息架构骨架 | 将 health、trace rollup、fallback rates、sessions 状态放入“运行健康”区域 |
| 评分质量区域迁移 | AFK | Admin 信息架构骨架 | 将 evidence rollup、question quality、verifier drift、RAG eval 放入“评分质量”区域 |
| 策略学习区域迁移 | AFK | Admin 信息架构骨架 | 将 bandit snapshot、strategy memory、recent traces 放入“策略学习”区域 |
| `AdminPanel` 组件拆分清理 | AFK | 运行健康区域迁移、评分质量区域迁移、策略学习区域迁移 | 拆出 `AdminHealthSection`、`ScoringQualitySection`、`StrategyLearningSection` 等局部组件，让 `AdminPanel.tsx` 只保留数据加载和高层编排 |
| admin 默认视角确认 | HITL | Admin 信息架构骨架 | 决定默认打开哪个视角；默认建议“运行健康”，因为 admin 首屏应先回答系统是否正常 |

**Issue 发布前检查：**

- P2-2 不改后端 API，只整理前端信息架构。
- token 保存、刷新、错误态、自动刷新不回归。
- 每个区域都要能独立展示 loading / error / ready。
- 拆组件时不引入新的数据 fetching 方式，先沿用现有 `useAutoFetch` 模式。

### P2-3 执行节奏固化

**目的：** 降低大计划一次性改动的风险。

**推荐顺序：**

1. 第一轮：P0-1 + P0-3，先补测试和预检命令。
2. 第二轮：P0-2，单独处理 Redis/shared state。
3. 第三轮：P1-1 + P1-2，处理可信度和隐私闭环。
4. 第四轮：P1-3 + P2-1，收束产品语言并打通复练。
5. 第五轮：P2-2，整理 admin 面板。

**总体验证命令：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
pytest tests/unit -q
cd ..\frontend
npm run typecheck
npm run lint
npm run build
```

#### P2-3 Issue 拆分

| Issue | 类型 | Blocked by | 目标 |
| --- | --- | --- | --- |
| P0/P1/P2 执行看板文档 | AFK | 当前 issue 拆分完成 | 在计划文档中增加执行看板：每个 issue 的阶段、优先级、依赖、建议 PR 批次 |
| 验证命令矩阵 | AFK | P0/P1/P2 执行看板文档 | 为每个 PR 批次列出必须执行的验证命令，包括后端 pytest、前端 typecheck/lint/build |
| PR 切分规则 | AFK | P0/P1/P2 执行看板文档 | 固化 PR 切分原则：运行时、测试矩阵、UI 文案、admin 信息架构、专项练习分别独立 |
| HITL 决策清单 | HITL | P0/P1/P2 执行看板文档 | 汇总 probe 严格度、memory backend 策略、可信度文案、retention、产品词表、focus 非法策略、admin 默认视角等决策 |
| 完成定义与 release gate | AFK | 验证命令矩阵、PR 切分规则、HITL 决策清单 | 明确 P0/P1/P2 的 Done Definition 和 release gate |
| 是否发布到 GitHub Issues | HITL | 前 5 个 P2-3 issue | 决定是否把文档中的 issue 草案发布到 GitHub Issues；默认建议先保留在文档中，P0-1 开始实现前再发布 P0 issue |

**Issue 发布前检查：**

- 执行看板不替代具体 issue，只负责排序和状态。
- 验证命令矩阵必须区分最小验证与全量验证。
- HITL 决策未确认前，不进入对应实现 issue。
- PR 切分规则必须阻止 P0 运行时改动和 P2 UI 改动混在一起。

## 风险与回滚

| 风险 | 应对 |
| --- | --- |
| Redis 抽象影响 dev 启动 | memory backend 保持默认 dev 可用 |
| P0-2 改动面过大 | 单独 PR，不和 UI / 文案混合 |
| 可信度文案吓退用户 | 使用“信号充分/部分信号不足”而非错误化语言 |
| 隐私删除误删 | 先 dry-run 测试，再启用实际删除 |
| 专项练习维度不合法 | 后端强校验 focus dimensions |

## 完成定义

- P0 完成：预检命令、共享状态方案、HITL 回归矩阵均可运行。
- P1 完成：报告可信度可见，隐私删除/留存有闭环，外显文案无招聘决策导向。
- P2 完成：用户能从弱项进入专项练习，admin 面板能按运行/质量/策略三个视角查看系统状态。
