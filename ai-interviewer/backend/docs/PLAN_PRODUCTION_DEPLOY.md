# 生产部署清单

> **当前阶段**：dev / test 仍允许低门槛启动；当 `APP_ENV=prod` 时，`app/core/deployment_preflight.py` 会在启动期强制拦截高风险配置。本清单仍作为上线前人工核对入口。

## 自动预检命令

上线前先运行生产 smoke CLI，确保启动期 preflight 与依赖连通性检查在当前环境中可执行：

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
interviewer-prod-smoke --check-deps
```

如果没有安装脚本入口，也可以直接使用模块方式：

```powershell
python -m app.scripts.production_smoke --check-deps
```

CLI 输出只包含脱敏配置摘要和 Postgres / Redis / Chroma 探测状态，不会打印 API token、数据库密码或 Redis 密码。`APP_ENV=prod` 时 preflight 失败或依赖探测失败会返回非零退出码；dev / test 下依赖探测失败只作为预览环境告警。

## 适用范围

仅当 `APP_ENV=prod` 真正部署上线时手工核对下面项目。staging 可以参考 1 / 2 / 4 / 6，按需启用。

## 核对项

### 1. `API_TOKEN` 必须非空

- **所属**：所有 `/admin/*` 与 WebSocket 语音通道的鉴权底座
- **配置位置**：`backend/.env`（或部署系统的 secret manager）
- **校验代码**：`app/api/v1/ws_voice.py` 第 ~141 行 `if get_settings().app_env == "prod":` 分支
- **未配置后果**：管理面（bandit snapshot / drift / metrics）裸奔；语音通道无法识别"是不是合法用户"
- **示例值**：`API_TOKEN=$(openssl rand -hex 32)`

### 2. `ALLOW_OPEN_ADMIN` 必须为 `false`

- **所属**：`/admin/*` 路由级"无 token 直放行"开关
- **设计初衷**：dev 调试免 token 的逃生口；prod 误开启会让 #1 配的 `API_TOKEN` 完全失效
- **未配置后果**：即使 `API_TOKEN` 已配，所有 `/admin/*` 仍可未授权访问
- **建议**：prod env 显式 `ALLOW_OPEN_ADMIN=false`，不依赖默认值
- **#1 / #2 必须同时正确**：单独配 `API_TOKEN` 但漏关 `ALLOW_OPEN_ADMIN` 等于零防御

### 3. 多 worker / 多副本下的共享状态策略

以下 backend 在 `APP_ENV=prod` 下不能继续使用 `memory`：

| 配置 | prod 要求 | 原因 |
|------|-----------|------|
| `RATE_LIMIT_BACKEND` | `redis`，或在应用外配置等价上游限流后才可例外 | `/resume/parse`、`/jd/parse`、`/llm/test` 是高成本端点，memory backend 会被 worker 数放大限额 |
| `VOICE_TICKET_BACKEND` | `redis` | 语音 WebSocket 一次性 ticket 必须能跨 worker 消费且只消费一次 |
| `VERIFIER_DRIFT_BACKEND` | 建议 `redis`；当前 `memory` 只告警不阻断 | drift 观测窗口按进程分裂会影响 admin 诊断可信度，但不阻塞主链面试 |

默认 dev/test 仍可使用 `memory`，避免本地启动强依赖 Redis。生产部署建议显式配置：

```env
RATE_LIMIT_BACKEND=redis
VOICE_TICKET_BACKEND=redis
VERIFIER_DRIFT_BACKEND=redis
```

### 4. CORS 收紧

- **配置项**：`CORS_ORIGINS`
- **dev 默认**：`localhost` 系列
- **prod 必须**：前端真实域名白名单（精确到协议 + 域名 + 端口），**不**写 `*`
- **校验代码**：`app/main.py` `CORSMiddleware` 段
- **遗漏后果**：浏览器侧任意源都能调你的 LLM 计费端点

### 5. LangSmith 路由

仅当 `LANGSMITH_TRACING=true` 时关注：

- **关注项**：`LANGSMITH_PROJECT` 必须与 dev / staging 区分（建议 suffix `-prod` / `-staging` / `-dev`）
- **遗漏后果**：prod 流量与 dev 调试 trace 串台，dashboard 数据被污染、计费方混淆

### 6. 生产 fallback 禁止静默退化

以下配置由启动 preflight 自动校验：

| 配置 | prod 要求 | 原因 |
|------|-----------|------|
| `CHECKPOINT_BACKEND` | 必须为 `postgres` | HITL 会话必须可跨进程恢复 |
| `LLM_PROVIDER` / `use_stub_llm` | 禁止进入 stub mode | 避免生产报告来自 deterministic stub |
| `EMBEDDING_PROVIDER` | 默认禁止 `stub` | 避免 RAG/检索能力静默退化 |
| `ALLOW_STUB_EMBEDDINGS_IN_PROD` | 仅临时降级时显式设 `true` | 让降级成为可审计选择 |
| `RESUME_PARSE_CACHE_BACKEND` | 禁止 `memory` | 多 worker 下 memory cache 行为不一致 |
| `RATE_LIMIT_BACKEND` | 禁止 `memory` | 多 worker 下高成本端点限额会被放大 |
| `VOICE_TICKET_BACKEND` | 禁止 `memory` | 语音 ticket 不能跨 worker 一次性消费 |
| `API_TOKEN` | 必须非空，除非显式 `ALLOW_OPEN_ADMIN=true` | 保护 admin 接口 |

`ENABLE_VERIFIER_DRIFT_MONITOR=true` 且 `VERIFIER_DRIFT_BACKEND=memory` 只告警不阻断；多 worker 部署建议改为 Redis，否则 drift 窗口按进程分裂。

## 6. 已知延后加固触发器（Pending Hardening Triggers）

以下三项在 [PLAN_DEPLOYMENT_HARDENING_AUDIT.md](./PLAN_DEPLOYMENT_HARDENING_AUDIT.md) 中**显式延后**，每次部署变更时按表格列的「触发条件」核对一次；任何一项触发立即把对应「最小落地动作」加入本次发布范围，禁止"再延后一次"。

| ID | 项 | 触发条件 | 最小落地动作 |
|----|----|---------|-------------|
| F1 | Voice-ticket Redis-backed store | 部署 ≥ 2 backend worker 且无 sticky session（cookie / IP-hash） | 已落地 `VoiceTicketStore` 接口与 `RedisVoiceTicketStore`；生产配置 `VOICE_TICKET_BACKEND=redis` |
| F2 | `/resume/parse` per-provider rate limit | 切换到「服务端共享 LLM key」模式（任意一个 `LLM_API_KEY_*` settings 非空且非 BYOK） | 在 `_enforce_setup_rate_limit` 加 `provider:host` 二级桶；与 `effective_llm_fingerprint` 拼 key |
| F3 | Cache 多租户 salt | 引入 org / tenant / workspace 概念，或合规要求消除"已处理简历"侧信道 | 在 `resume_parse_cache_key` 的 `material` 字典加 `org_id`；Redis prefix 按 org 拆分以支持单租户驱逐 |

> 决策依据见 audit 文档；这里仅承担「不让它们被忘掉」的索引职责。每发一次 prod release，本节由发布人（或代发布的 AI agent）至少 review 一遍。

## 与代码层的关系

| 层 | 行为 |
|----|------|
| 启动期校验（`app/main.py` create_app） | dev/test 只告警；`APP_ENV=prod` 对 §6 的高风险项硬失败 |
| `ws_voice` token 校验 | 仅在 `app_env == "prod"` 分支生效（见 §1） |
| `rate_limit.py` | 始终生效，但是进程内（见 §3） |
| CORS | 始终读 `CORS_ORIGINS`（见 §4） |

## 历史

- 早期曾在 `app/main.py` 内有 `_validate_production_settings` 启动期硬校验函数，开发阶段过度防御被回退
- 本文档作为开发与生产之间的"软门槛"——靠人工核对，不靠运行时阻塞
- 真正上线前应当再过一遍 `python -m app.scripts.seed_kb` / 数据库连通性 / chroma 状态等基建检查
