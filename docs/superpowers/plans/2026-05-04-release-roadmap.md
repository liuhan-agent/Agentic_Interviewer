# Agentic Interviewer · 发布路线图（路径 C · 双轨混合）

> **面向 AI 代理的工作者：** 必需子技能：使用 writing-plans、verification-before-completion。按用户规则，本路线图不使用子代理；任何阶段动手前需用户确认触发条件已成立。

**目标：** 用最克制的工程动作，把项目从「本地 dev 可跑」推进到「Web SaaS 上线 + 可选企业私有化」，同时保持开发期零干扰。  
**前提：** 项目已具备 stub fallback、前端 BYOK 入口、后端 `_llm_override_var` 双轨流转能力。本路线图不引入新业务能力，只规划工程化与运营化时序。  
**技术栈：** Python（FastAPI / LangGraph）、TypeScript（Next.js）、SQLAlchemy、Docker Compose、Redis。  
**适用对象：** 项目维护者本人、未来上线时接手的 functional_dev / devops agent。

## 决策定调

### 为什么是 Web SaaS（不是桌面应用）

| 维度 | Web SaaS | 桌面应用（含 Electron 壳） |
|---|---|---|
| 后端是否要部署 | 要部署一份 | **依然要部署**（除非走纯本地，但纯本地丢失 LLM / RL / 多用户聚合能力） |
| 用户上手 | 浏览器开打就用 | 下载安装包，初配置 |
| LangGraph + RAG + 在线学习 | 集中部署，一份服务多人受益 | 单机 bandit 学不出全用户偏好 |
| 跨设备同步 | 天然 | 需自建同步 |
| 升级链路 | 推一次代码全用户即时生效 | 推安装包，老用户可能不升 |

**结论：** 桌面化对当前项目是退化，不是升级。Web SaaS 是项目当前架构的最优交付形态。

### 为什么是双轨混合（Path C）

| 模式 | 描述 | 取舍 |
|---|---|---|
| 路径 A · 纯 BYOK | 用户填自己的 LLM key | 上手门槛高（C 端用户多数无 key），但平台零成本 |
| 路径 B · 纯平台代付 | 平台 key 兜全用户 | 上手零门槛，但平台 LLM 月费可能失控、易被刷 |
| **路径 C · 双轨混合（采用）** | 平台代付为默认 + BYOK 为高频/高级用户出口 | 兼顾门槛低与成本可控；项目代码已具备双轨能力 |

### 已就位的双轨能力（不需要重做）

```text
[前端 LLMSettingsDialog]
   ↓ obfuscate 存 sessionStorage（默认）/ localStorage（用户主动选「长期保存」），src/lib/llm-config.ts:4-25
[请求 /api/v1/* 时]
   ↓ 带 llm-config 表单（FormData / JSON）
[后端 interview.py]
   ↓ _parse_llm_config_form() 解析 override
   ↓ with temporary_llm_override(override)
[ContextVar _llm_override_var]
   ↓ 会话作用域传递（services/session_manager.py:43-67）
[llm_client.py]
   ↓ _override_for_agent_role(get_llm_override(), agent_role)
   ↓ 有 override 走 BYOK；无 override 走 settings.py 平台默认
```

这意味着：**模式切换只是运营层（额度 / 套餐 / 防刷）变化，不需要再改架构层。**

## 阶段 0 · 现在（开发 / 调试期）

> **铁律：一行代码不动。**

### 维持现状

| 项 | 现状 | 是否动 |
|---|---|---|
| 后端 `LLM_PROVIDER=stub` 默认 | 可用 | 不动 |
| 前端 LLMSettingsDialog | 可用 | 不动 |
| 后端 `.env` 可填真模型 key | 可用 | 不动 |
| Docker compose dev | 可用 | 不动 |
| Docker compose prod | 不存在 | **现在不动**，到阶段 1 才造 |
| 用户系统 | 不存在 | **现在不动**，到阶段 2 才造 |
| 额度中间件 | 不存在 | **现在不动**，到阶段 2 才造 |
| Stripe / 计费 | 不存在 | **现在不动**，到阶段 3 才造 |

### 开发者日常跑通

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
docker compose up -d postgres redis chroma
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000
```

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm run dev
```

- 默认 stub 模式跑通主流程（零 key）
- 试真模型时：前端 LLMSettingsDialog 填一次个人 key，或 backend `.env` 临时写 `OPENAI_API_KEY`

### 退出条件

用户明确说「准备上线 / 上 beta / 内测」时，退出阶段 0，进阶段 1。

## 从现状到可发布 · 工程清单总览

> 本节是给未来发布执行者看的入口清单。现在仍处于阶段 0，**不要提前动手**；等用户明确说「准备上线 / 上 beta / 内测」后，再按下面顺序拆成实施 plan。

### 阶段 0 冻结清单（现在）

- [ ] 保持本地开发形态：后端 `uvicorn` + 前端 `npm run dev` + dev `docker-compose.yml`。
- [ ] 保持默认 stub / BYOK 调试路径，不引入登录、额度、计费或生产 compose。
- [ ] 继续把产品语言锁定为「AI 面试官 / 面试 / 评分 / 报告」，不要改成桌面应用或泛教练叙事。
- [ ] 阶段 0 的任何发布想法只追加到本路线图或新 plan，不直接改生产配置。

### 阶段 1 发布前置清单（准备 beta 时先做）

- [ ] 先跑并清理测试基线：后端 `python -m pytest tests/unit -q`，前端 `npm run typecheck && npm run lint && npm test`。
- [ ] 若测试红，先单独修复红测试；不要把「发布工程」和「业务 bug 修复」混在同一个 PR。
- [ ] 冻结最小可发布产品范围：文本面试、简历/JD 解析、报告、训练计划、BYOK / 平台默认 key、基础 admin 观测。
- [ ] 明确 beta 运营策略：小范围访问、可人工关停平台 key、出现异常费用时切回 stub 或要求 BYOK。

### 阶段 1 工程交付清单（Web SaaS beta）

- [ ] 新增 `ai-interviewer/backend/Dockerfile`，只负责后端 API 镜像。
- [ ] 新增 `ai-interviewer/frontend/Dockerfile`，只负责 Next.js 前端镜像。
- [ ] 新增根目录 `docker-compose.prod.yml`，包含 `postgres` / `redis` / `chroma` / `backend` / `frontend` 五类服务。
- [ ] 新增 `ai-interviewer/backend/.env.production.example`，覆盖 `APP_ENV=prod`、数据库、Redis、Chroma、LLM、CORS、admin token、LangSmith 等生产变量。
- [ ] 新增 `ai-interviewer/frontend/.env.production.example`，覆盖 `NEXT_PUBLIC_API_BASE`。
- [ ] 新增 `ai-interviewer/docs/部署指南.md`，写清楚服务器准备、环境变量、启动、健康检查、升级、回滚。
- [ ] 配置反向代理和 TLS：HTTPS 访问前端，`/api/v1/*`、`/health`、`/admin/*`、`/ws/voice/*` 正确转发到后端；语音路径必须支持 WSS。
- [ ] 配置域名与 DNS：beta 域名先走小范围访问，不要直接公开投放。
- [ ] 配置持久化卷：Postgres、Chroma 必须落持久化 volume；Redis 可按缓存/运行时状态策略决定是否持久化。
- [ ] 初始化知识库：部署后运行 `python -m app.scripts.seed_kb`，确认 Chroma 可检索。
- [ ] 配置备份：至少给 Postgres 做每日备份；Chroma 若题库可重建，可记录重建命令，否则也要备份 volume。

### 阶段 1 安全与成本清单

- [ ] 按 `ai-interviewer/backend/docs/PLAN_PRODUCTION_DEPLOY.md` 手工核对生产配置。
- [ ] `APP_ENV=prod`。
- [ ] `API_TOKEN` 必须非空，并且不提交到 Git。
- [ ] `ALLOW_OPEN_ADMIN=false`。
- [ ] `CORS_ORIGINS` 只允许真实前端域名，不使用 `*`。
- [ ] 平台 fallback key 只放在部署环境或 secret manager，不写进 `.env.production.example`。
- [ ] 多 worker / 多副本部署时处理限流放大问题：静态降配、上游限流、Redis 共享限流三选一。
- [ ] 给高成本接口保留防刷入口：`/resume/parse`、`/jd/parse`、`/llm/test`、创建会话、提交回答。
- [ ] 准备一键降级手段：平台 key 被刷时能快速切 `LLM_PROVIDER=stub` 或关停公网入口。

### 阶段 1 观测与验收清单

- [ ] `GET /health` 返回正常。
- [ ] 前端打开 beta 域名能进入 `/interview/setup`。
- [ ] stub 模式可完成一场短文本面试并生成报告。
- [ ] BYOK 模式可完成一场短文本面试并生成报告。
- [ ] admin token 生效：未带 token 不能访问 `/admin/*`，带 token 才能访问。
- [ ] 日志不打印 API key、BYOK key、原始简历敏感内容。
- [ ] 若开启 LangSmith，`LANGSMITH_PROJECT` 必须区分 dev / staging / prod。
- [ ] 验证升级路径：重新 build / pull / restart 后旧 session 不被误删。
- [ ] 验证回滚路径：上一版镜像和数据库备份可恢复。

### 阶段 2 运营化清单（手工管不住时）

- [ ] 邮箱 magic link 登录。
- [ ] `users` 表 + `interview_sessions.user_id` 外键，老匿名 session 保持兼容。
- [ ] Redis 每日额度中间件，至少覆盖创建面试、resume/JD 解析、LLM test、高成本报告再生成。
- [ ] BYOK 请求不计入平台额度。
- [ ] 前端展示额度状态和超额引导：填 BYOK、等待次日、升级会员三种路径。
- [ ] Cloudflare Turnstile 或等价防刷机制。
- [ ] 多设备历史同步：把当前 localStorage 历史逐步迁到用户维度服务端数据。
- [ ] 为登录态和额度新增 e2e bypass token，避免 CI 被真实登录流程卡住。

### 阶段 3 商业化清单（确认变现后）

- [ ] 先确定 SKU：按场次、按月、按报告深度或按语音能力计费。
- [ ] 再选择支付：Stripe、微信支付、支付宝按目标市场决定。
- [ ] 增加会员中心、订单记录、发票/退款策略。
- [ ] 成本看板接入：按用户、provider、agent role、会话统计 LLM 成本。
- [ ] 明确免费额度、BYOK 豁免、滥用封禁和人工客服流程。
- [ ] 任何商业化实现必须另写独立 plan，不直接塞进阶段 1 beta 工程。

## 阶段 1 · 准备内测 / 小范围公测

> **触发条件：** 用户说「该上 beta 测一测」。

### 工作清单（6 项工程配置，零业务改动）

| # | 文件 | 动法 | 影响 |
|---|---|---|---|
| 1 | `ai-interviewer/backend/Dockerfile` | 新增 | 不影响本地 dev |
| 2 | `ai-interviewer/frontend/Dockerfile` | 新增 | 不影响本地 dev |
| 3 | 根目录 `docker-compose.prod.yml` | 新增（5 个 service：postgres / redis / chroma / backend / frontend） | 不影响 dev compose |
| 4 | `ai-interviewer/backend/.env.production.example` | 新增 | 范本 |
| 5 | `ai-interviewer/frontend/.env.production.example` | 新增 | 范本 |
| 6 | `ai-interviewer/docs/部署指南.md` | 新增 | 文档 |

可选轻量动作：

- 前端首页或 `/interview/setup` 顶部加 1 行轻量 hint：「未填 LLM key 将走 stub 演示模式，体验有限」
- 启动 Cloudflare（免费档）做基础防刷
- 域名 + Let's Encrypt（语音 WebSocket 必须 WSS）

### 不做

- 用户体系
- 额度中间件
- 套餐 / 计费

### 此阶段产品形态定调

「开放 BYOK demo」——平台 fallback key 仅供试玩，额度通过后端 `.env` 手工开关；被刷就拉黑名单。**这一阶段适合验证 PMF，不适合做大流量。**

### 验证

阶段 1 工作清单全部交付后：

```powershell
docker compose -f docker-compose.prod.yml up --build -d
curl http://localhost:8000/health
curl http://localhost:3000
```

预期：3 个基础服务 + backend + frontend 全绿，前端能访问 `/interview/setup` 走完一场短面试。

### 退出条件

用户说「DAU 起来了 / 平台 LLM 费用控不住 / 出现明显刷子」之一，退出阶段 1，进阶段 2。

## 阶段 2 · 手工管不住了

> **触发条件（任一成立）：**
> - DAU 过 100
> - 平台方 LLM 月费控制不住
> - 出现明显被刷迹象
> - 用户开始要求多设备 / 跨场历史同步

### 工作清单（6 项业务层）

| # | 项 | 是否能跳过 |
|---|---|---|
| 1 | 邮箱 magic link 注册（最轻量身份） | 不能 |
| 2 | `users` 表 + `interview_sessions.user_id` 外键 | 不能 |
| 3 | 每日额度 Redis 计数中间件 | 不能 |
| 4 | BYOK key 填了额度不计 | 能（1 行代码） |
| 5 | 超额 graceful degradation（引导去 BYOK 或加会员） | 不能 |
| 6 | Cloudflare Turnstile 验证（拦自动化刷子） | 能 |

### 工时

约 1-2 周（一个开发者）。

### 关键代码资产路径

阶段 2 上手时直接看：

```text
[backend]
  app/services/session_manager.py:43-67
    _llm_override_var 与 temporary_llm_override
    阶段 2 加额度时在这之后加中间件
  app/api/v1/interview.py:1160 附近
    _parse_llm_config_form
    额度检查应加在这之后
  app/engine/agents/llm_client.py:817
    _override_for_agent_role 这里不动
  app/core/settings.py
    阶段 1 加 production env 样本时参考
[frontend]
  src/lib/llm-config.ts:4-25
    STORAGE_KEY / obfuscate 阶段 1 不动这里
  src/components/layout/LLMSettingsDialog.tsx
    阶段 1 不动；阶段 2 加一个额度状态面板
```

### 验证

阶段 2 完成后：

- 未注册访问 `/api/v1/interview/...` 应被拦
- 注册后每日 N 场免费额度生效
- 超额时引导填 BYOK 或加会员
- BYOK key 填后请求不计入额度

### 退出条件

DAU 过千且确认要变现，进阶段 3。

## 阶段 3 · 商业化

> **触发条件：** 用户明确说「要做付费会员 / 要做 SKU」。

### 业务决策项（不在本路线图范围）

- Stripe / 微信支付 / 支付宝
- 套餐 SKU 设计（按场次 / 按月 / 按维度）
- 会员中心页
- 发票 / 退款流程
- 多语言（如要出海）

阶段 3 的全部决定都属于「业务总部」职责，**功能开发会等用户拍板后再开工。**

## 安全核对（开发期检查表）

| 场景 | 应该能跑 | 跑不了时该怎么办 |
|---|---|---|
| 未填 key 啥都不初始化 | `LLM_PROVIDER=stub` 跑面试主流程 | 检查 `.env`、检查 stub adapter |
| 跑真模型 | `OPENAI_API_KEY` 在 backend `.env` | 临时填上 |
| 个别跑试外部供应商 | 前端 LLMSettingsDialog 按 provider 填 | obfuscate 默认存 sessionStorage（关闭浏览器清空），可手动切到 localStorage 长期保存 |
| 开发多个模型对比 | 前端 LLMSettingsDialog 高级面板按 role 覆盖 | `LLMRoleOverrideConfig` 已预留 |

## 风险与回滚

| 风险 | 描述 | 缓解 |
|---|---|---|
| 阶段 1 prod compose 与 dev compose 端口冲突 | dev 用 5433/6380/8100，prod 用 5432/6379/8000 默认 | prod compose 挑无冲突端口；docs 写明对照 |
| 阶段 1 平台 fallback key 被刷 | 公开访问 + 平台代付，理论可被脚本刷 | Cloudflare 免费档 + 后端 `.env` 随时切 stub fallback |
| 阶段 2 引入 user_id 影响老 session | 阶段 0/1 累计的 sessions 没有 user_id | 给老 sessions 标 `user_id = NULL`，前端检测 NULL 时按"匿名场次"渲染 |
| 阶段 2 引入用户系统破坏 e2e 测试 | 现有 e2e 假设无登录 | 加一个 testing bypass token；CI 走 bypass |
| 阶段 3 商业化动业务总部决策 | 不在功能开发职责内 | 严格等用户拍板 |

## 给下一个执行者的备注

- 本路线图**只**列时序与决策点，**不**含可执行任务清单。每个阶段开工前需要用户确认触发条件成立。
- 阶段 1 开工时新建 `2026-XX-XX-stage-1-saas-rollout-plan.md`，按 `2026-05-04-coach-positioning-alignment.md` 的写法把每项配置拆为可串行执行的任务。
- 阶段 2 同理。
- 阶段 3 全部决策项需要用户级澄清，不要 AI 自行设计 SKU。
- 任何阶段都要保持 v2 校准定调：「面试 / 评分 / 报告」是产品主轴，「成长规划」是配套产出，工程化不能改这条产品语言定位。
- 路线图写完即冻结。新需求若涉及阶段提前推进，应新建 plan 文件，不在本文件继续累加。

## 估算总览

| 阶段 | 工作量 | 触发后耗时 |
|---|---|---|
| 阶段 0（现在） | 0 | 持续 |
| 阶段 1（SaaS 内测） | 6 项工程配置 | 1-2 天 |
| 阶段 2（运营层） | 6 项业务层 | 1-2 周 |
| 阶段 3（商业化） | 待用户拍板 | 待估 |

---

## 附录 · 与 v2 校准的对齐

本路线图遵循 `2026-05-04-coach-positioning-alignment.md` v2 校准定调：

- 不替换「AI 面试官」主名
- 不弱化「面试 / 评分 / 报告」核心术语
- 「成长规划 / 多维度反馈」作为面试主链路的配套产出
- 历史命名（`candidate_name` / `interview_sessions` / verdict legacy / RL outcome）在阶段 2 引入用户系统时仍保留兼容，不做 schema rename
