# 生产部署清单

> **当前阶段**：项目仍在开发 / 调试阶段，本清单作为**未来上线前的手工核对清单**，不在启动时强制 enforce；dev 启动不受影响。dev 默认配置（`APP_ENV=dev` / `API_TOKEN=` 空 / `ALLOW_OPEN_ADMIN=true` 等）即可一行 `uvicorn app.main:app --reload` 起服。

## 适用范围

仅当 `APP_ENV=prod` 真正部署上线时手工核对下面 5 项。staging 可以参考 1 / 2 / 4，按需启用。

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

### 3. 多 worker / 多副本下的限流策略

`app/core/rate_limit.py` 是进程内限流，N 个 uvicorn worker 或 N 个 pod 会把限额放大 N 倍。三选一：

| 方案 | 改动 | 优劣 |
|------|------|------|
| A · 静态降配 | 把 `RESUME_PARSE_RATE_LIMIT_PER_MINUTE` / `JD_PARSE_RATE_LIMIT_PER_MINUTE` / `LLM_TEST_RATE_LIMIT_PER_MINUTE` 都除以 worker 数 | 最简单；但每次扩缩容都要重算 |
| B · 上游限流 | nginx `limit_req` 或 ALB rate-based rule | 最贴生产实践；增加运维 L7 配置 |
| C · Redis 共享 | 把 `rate_limit.py` 换成 Redis-backed sliding window，保持 `check_rate_limit` / `RateLimitExceededError` 接口不变 | 弹性最好；增加 Redis 依赖与代码改动 |

**不做任一项的后果**：`/api/v1/resume/parse` 与 `/api/v1/jd/parse` 是 LLM 计费端点，限流被绕过会直接放大账单。

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

## 6. 已知延后加固触发器（Pending Hardening Triggers）

以下三项在 [PLAN_DEPLOYMENT_HARDENING_AUDIT.md](./PLAN_DEPLOYMENT_HARDENING_AUDIT.md) 中**显式延后**，每次部署变更时按表格列的「触发条件」核对一次；任何一项触发立即把对应「最小落地动作」加入本次发布范围，禁止"再延后一次"。

| ID | 项 | 触发条件 | 最小落地动作 |
|----|----|---------|-------------|
| F1 | Voice-ticket Redis-backed store | 部署 ≥ 2 backend worker 且无 sticky session（cookie / IP-hash） | 抽 `VoiceTicketStore` 接口；新增 `RedisVoiceTicketStore`，配 `VOICE_TICKET_BACKEND=redis` |
| F2 | `/resume/parse` per-provider rate limit | 切换到「服务端共享 LLM key」模式（任意一个 `LLM_API_KEY_*` settings 非空且非 BYOK） | 在 `_enforce_setup_rate_limit` 加 `provider:host` 二级桶；与 `effective_llm_fingerprint` 拼 key |
| F3 | Cache 多租户 salt | 引入 org / tenant / workspace 概念，或合规要求消除"已处理简历"侧信道 | 在 `resume_parse_cache_key` 的 `material` 字典加 `org_id`；Redis prefix 按 org 拆分以支持单租户驱逐 |

> 决策依据见 audit 文档；这里仅承担「不让它们被忘掉」的索引职责。每发一次 prod release，本节由发布人（或代发布的 AI agent）至少 review 一遍。

## 与代码层的关系

| 层 | 行为 |
|----|------|
| 启动期校验（`app/main.py` create_app） | **不**做强校验，dev 配置即可启动 |
| `ws_voice` token 校验 | 仅在 `app_env == "prod"` 分支生效（见 §1） |
| `rate_limit.py` | 始终生效，但是进程内（见 §3） |
| CORS | 始终读 `CORS_ORIGINS`（见 §4） |

## 历史

- 早期曾在 `app/main.py` 内有 `_validate_production_settings` 启动期硬校验函数，开发阶段过度防御被回退
- 本文档作为开发与生产之间的"软门槛"——靠人工核对，不靠运行时阻塞
- 真正上线前应当再过一遍 `python -m app.scripts.seed_kb` / 数据库连通性 / chroma 状态等基建检查
