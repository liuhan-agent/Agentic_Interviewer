# Agentic Interviewer 后端

后端是 **AI 面试官** 的主工程，基于 **FastAPI + LangGraph** 实现。它的核心责任是面试主链路：创建面试会话、编排多智能体问答工作流（resume_parse → self_intro → director_sample → ask_question → wait_answer → evaluator → verification → reward_update → refine/next_question/end → final_report → training_plan），生成问题、接收回答、给出多维度评分与反馈、产出最终报告与训练计划，并维护 trace / outcome / reward 的旁路学习闭环。

> **命名兼容：** 表 `interview_sessions`、字段 `candidate_name`、verdict 中的 `hire / no_hire`、RL outcome 的 `hired / rejected` 均为历史命名，仅用于内部数据 / RL 信号；面向 C 端的展示文案统一映射为成长信号（"表现优秀 / 重点补齐"等），主线产品语言仍然以"面试 / 评分 / 报告"为核心。

## 你可以用它做什么

- 启动 REST API，供前端页面调用。
- 跑命令行文本 demo，快速验证 LangGraph 面试流程。
- 使用本地 Chroma 知识库做 RAG 检索。
- 使用 PostgreSQL 持久化会话、trace、报告和 LangGraph checkpoint。
- 使用 Redis 做缓存或部分运行时共享状态。
- 通过 WebSocket 支持浏览器语音面试。
- 通过 `/admin/*` 查看 bandit 和 verifier drift 状态。

## 环境要求

- Python 3.11+
- Docker Desktop，可选但建议安装
- OpenAI API Key，可选；没有 key 可使用 `stub` 模式

Docker compose 会启动：

| 服务 | 本地端口 | 说明 |
| --- | --- | --- |
| PostgreSQL | `5433` | 会话、trace、报告、checkpoint |
| Redis | `6380` | session / prompt cache / drift 后端 |
| Chroma | `8100` | 向量知识库 |

## 快速启动

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,voice]"

copy .env.example .env
docker compose up -d postgres redis chroma

python -m app.scripts.seed_kb
uvicorn app.main:app --reload --port 8000
```

API 启动后访问：

```text
http://localhost:8000/health
```

## 无 API Key 本地跑通

如果只是验证项目是否能跑，不想调用真实模型，可以在 `.env` 里设置：

```env
LLM_PROVIDER=stub
EMBEDDING_PROVIDER=stub
ASR_PROVIDER=stub
TTS_PROVIDER=stub
CHECKPOINT_BACKEND=memory
```

然后运行：

```powershell
python -m app.scripts.run_demo
```

`stub` 模式会返回确定性的本地假响应，不需要网络模型调用，适合 CI、调试和第一次启动。

## 使用真实模型

在 `.env` 里设置：

```env
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=你的 key

EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL=text-embedding-3-small
```

也支持 Anthropic 和 DeepSeek：

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=你的 key
```

```env
LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=你的 key
```

具体模型路由由 `app/engine/agents/llm_client.py` 和 `app/core/settings.py` 控制。

## 目录结构

```text
backend/
  app/
    api/v1/
      interview.py          # 文本面试 REST API
      ws_voice.py           # 语音面试 WebSocket
      admin.py              # 管理接口
    core/
      settings.py           # 环境变量和运行配置
      logging.py            # 日志
      tracer.py             # trace 写入
      request_translator.py # 请求转换
    engine/
      workflow/             # LangGraph state、nodes、routers、session manager
      agents/               # Generator、Evaluator、Verifier、Guard 等 agent
      context/              # slot-based ContextBuilder
      rag/                  # Chroma、BM25、检索器
    memory/                 # strategy_store、skill_store、llm_selector
    ml/
      rl/                   # Thompson Sampling、reward、outcome bridge
      drift/                # verifier drift monitor、prompt feedback
    data/                   # 数据清洗、入库、训练集导出
    voice/                  # ASR、TTS、音频流处理
    scripts/                # seed、demo、导出脚本
    main.py                 # FastAPI 应用入口
  docs/                     # 后端设计计划
  knowledge/                # 题库、示例简历、技能卡、策略记忆
  tests/unit/               # 单元测试
  docker-compose.yml
  pyproject.toml
  .env.example
```

## 核心流程

LangGraph 主流程：

```text
Resume Parse
  -> Director (Thompson Sampling)
  -> Ask
  -> Listen
  -> Evaluate
  -> Refine | Next | Report
```

对应代码大致分布：

| 模块 | 说明 |
| --- | --- |
| `app/engine/workflow/state.py` | `InterviewState` 状态黑板 |
| `app/engine/workflow/nodes/` | 各节点实现 |
| `app/engine/workflow/routers.py` | 条件路由 |
| `app/engine/workflow/graph.py` | LangGraph 图构建 |
| `app/engine/workflow/session_manager.py` | 会话运行与恢复 |

旁路学习闭环：

```text
generation_traces -> outcome_records -> reward -> ThompsonBandit
```

主链负责当前面试体验，旁路负责策略学习和后续分析。

## 常用命令

安装依赖：

```powershell
pip install -e ".[dev,voice]"
```

启动基础设施：

```powershell
docker compose up -d postgres redis chroma
```

初始化小型知识库：

```powershell
python -m app.scripts.seed_kb
```

运行文本 demo：

```powershell
python -m app.scripts.run_demo
```

启动 API：

```powershell
uvicorn app.main:app --reload --port 8000
```

运行测试：

```powershell
pytest tests/unit -q
```

导出最近一天 trace 训练集：

```powershell
python -m app.scripts.export_daily_trainset --days 1 --out ./data/trainset/latest.jsonl
```

## Checkpoint 与持久化

默认 `.env.example` 使用 PostgreSQL：

```env
CHECKPOINT_BACKEND=postgres
DATABASE_URL=postgresql+psycopg2://interviewer:interviewer@localhost:5433/interviewer
```

这种模式下，长时间运行的 HITL 面试可以跨进程恢复。`build_workflow()` 首次启动时会调用 `PostgresSaver.setup()` 自动创建 checkpoint 表。

如果只是本地 demo，可以改成内存：

```env
CHECKPOINT_BACKEND=memory
```

内存模式更轻，但后端进程重启后会话状态会丢失。

## 关键环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `APP_ENV` | `dev` | 运行环境 |
| `APP_PORT` | `8000` | API 端口 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `LOG_FORMAT` | `auto` | dev 控制台格式，prod JSON 格式 |
| `DATABASE_URL` | `localhost:5433` | PostgreSQL DSN |
| `REDIS_URL` | `localhost:6380` | Redis DSN |
| `CHROMA_HOST` | `localhost` | Chroma host |
| `CHROMA_PORT` | `8100` | Chroma port |
| `LLM_PROVIDER` | `openai` | `openai`、`anthropic`、`deepseek`、`stub` |
| `LLM_MODEL` | `gpt-4o-mini` | 默认模型 |
| `GENERATOR_LLM_TIMEOUT_SECONDS` | `45` | 面试题生成 LLM 调用超时时间 |
| `EVALUATOR_LLM_TIMEOUT_SECONDS` | `45` | 候选人回答评分 LLM 调用超时时间 |
| `RESUME_PARSER_LLM_TIMEOUT_SECONDS` | `60` | 简历上传时等待 LLM 精修的秒数 |
| `OPENAI_API_KEY` | 空 | OpenAI key |
| `ANTHROPIC_API_KEY` | 空 | Anthropic key |
| `EMBEDDING_PROVIDER` | `openai` | `openai` 或 `stub` |
| `ASR_PROVIDER` | `openai` | `openai`、`deepgram`、`stub` |
| `TTS_PROVIDER` | `openai` | `openai` 或 `stub` |
| `CHECKPOINT_BACKEND` | `postgres` | `postgres` 或 `memory` |
| `LANGSMITH_TRACING` | `false` | 是否启用 LangSmith |
| `API_TOKEN` | 空 | 设置后保护 `/admin/*` |

更多开关在 `app/core/settings.py`。

## RAG 知识库

知识文件位于 `knowledge/`：

```text
knowledge/
  tech_questions/       # 技术题库
  behavioral_questions/ # 行为题库
  sample_resumes/       # 示例简历
  skills/               # 人工维护的面试技能卡
  strategy/             # reward-driven 策略记忆
```

初始化命令：

```powershell
python -m app.scripts.seed_kb
```

检索逻辑位于：

- `app/engine/rag/vectorstore.py`
- `app/engine/rag/retriever.py`
- `app/data/ingest.py`

## 语音面试

语音入口：

- WebSocket：`/ws/voice/{session_id}`
- 前端页面：`/interview/[sessionId]/voice`

相关代码：

- `app/api/v1/ws_voice.py`
- `app/voice/asr.py`
- `app/voice/tts.py`

真实语音能力需要配置 ASR/TTS provider 和对应 key。`stub` 模式下会返回固定转写和文本形式的 TTS bytes，适合先验证链路。

## 管理与观测

常用接口：

| 接口 | 说明 |
| --- | --- |
| `GET /health` | 健康检查 |
| `GET /admin/bandit/snapshot` | 查看 Thompson bandit posterior |
| `GET /admin/drift/verifier` | 查看 verifier drift 统计 |
| `GET /admin/metrics` | Prometheus 指标 |
| `GET /admin/tracer/health` | 本地 trace 写入健康状态 |

如果设置了：

```env
API_TOKEN=your-token
```

则 `/admin/*` 需要 bearer token。

## 生产部署清单

未来上线前的手工核对清单单独成档：[`docs/PLAN_PRODUCTION_DEPLOY.md`](docs/PLAN_PRODUCTION_DEPLOY.md)。开发 / 调试阶段不在启动时强制 enforce，dev 启动不受影响。

## LangSmith

LangSmith 默认关闭。开启方式：

```env
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=agentic-interviewer
```

应用启动时会同时映射 `LANGSMITH_*` 和 `LANGCHAIN_*` 环境变量，方便 LangChain / LangGraph SDK 自动拾取。

## Feature flags

常用开关：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ENABLE_VERIFIER_DRIFT_MONITOR` | `false` | 记录 verifier drift 滚动窗口 |
| `VERIFIER_ADAPTIVE_TRIGGER` | `false` | 根据 drift 自动调节 verifier 调用率 |
| `ENABLE_EVALUATOR_PROMPT_FEEDBACK` | `false` | 给 Evaluator 注入历史负例 |
| `ENABLE_GENERATOR_AVOID_PATTERNS` | `false` | 给 Generator 注入需规避的浅层回答模式 |
| `ENABLE_SKILL_INJECTION` | `false` | 注入 `knowledge/skills/*.md` 技能卡 |
| `ENABLE_LLM_MEMORY_SELECTOR` | `false` | 用轻量 LLM side query 精选 skill / strategy memory |
| `EVIDENCE_SPAN_ALIGNMENT` | `false` | 为 evidence quote 增加文本位置对齐信息 |
| `ENABLE_BANDIT_DECAY` | `false` | 开启 bandit 非平稳衰减 |
| `ENABLE_OUTCOME_SYNC` | `false` | 周期性回填 delayed reward |

打开一组 Phase 5 相关能力的示例：

```powershell
$env:ENABLE_VERIFIER_DRIFT_MONITOR="true"
$env:ENABLE_EVALUATOR_PROMPT_FEEDBACK="true"
$env:ENABLE_GENERATOR_AVOID_PATTERNS="true"
$env:ENABLE_SKILL_INJECTION="true"
$env:VERIFIER_ADAPTIVE_TRIGGER="true"
python -m app.scripts.run_demo
```

## 常见问题

| 问题 | 处理方式 |
| --- | --- |
| `ModuleNotFoundError: app` | 确认在 `backend/` 目录下，并已执行 `pip install -e ".[dev,voice]"` |
| 后端启动后会话丢失 | 如果是 `CHECKPOINT_BACKEND=memory`，重启会丢失；改用 `postgres` |
| Chroma 连接失败 | 确认 `docker compose up -d chroma` 已启动，端口为 `8100` |
| OpenAI 鉴权失败 | 检查 `.env` 中的 `OPENAI_API_KEY`，或切到 `LLM_PROVIDER=stub` |
| 语音没有真实音频 | 检查 `ASR_PROVIDER`、`TTS_PROVIDER` 和对应 API key；stub 模式只用于链路验证 |

## 测试基线

历史说明中记录过 `pytest tests/unit -q` 全量通过。由于本地依赖、配置和代码状态会变化，提交或发布前请以你当前机器上的测试输出为准。
