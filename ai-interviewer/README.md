# Agentic Interviewer · AI 面试官

基于 **FastAPI + LangGraph + Next.js** 的 **AI 面试官** 项目。**核心业务是面试主链路**：用 LangGraph 编排多智能体问答工作流，做简历解析 → 自我介绍 → Director 抽样 → 出题 → 等待回答 → Evaluator 评分 → 追问 / 切换 → 最终报告，内置 Thompson Sampling bandit、Verifier drift、RAG 题库与 trace / outcome / reward 旁路闭环。

面试主链路完成后，配套产出**多维度反馈 + 训练计划 + 跨场进步轨迹**，让用户能看到强项、差距和下一场怎么练。这部分是面试主链路的"业务产出"，不替代面试本身。

这个目录是项目可运行入口，采用前后端分离结构：

- `backend/`：FastAPI、LangGraph、多 Agent、RAG、RL、语音接口、管理接口。
- `frontend/`：Next.js 14 App Router、TypeScript、Tailwind、shadcn/ui。
- `docs/`：项目级设计文档和后端工程 Plan。
- `../reference/`：仓库参考知识库，不参与项目运行。

> **历史命名说明：** 数据库表 / 部分字段（如 `candidate_name`、`overall_verdict: hire / no_hire`、RL outcome 的 `hired / rejected`）保留了招聘语境的命名以兼容既有数据，展示层已统一映射成对 C 端更直接的成长信号（"表现优秀 / 达到目标水平 / 接近达标 / 重点补齐"）。开发者请保留这一边界：**字段名为历史命名，对外文案以面试 + 评分 + 报告为主轴**。

## 快速判断你要看哪里

如果你只是想本地跑起来：

1. 先看本文的“本地启动”。
2. 常用启动、关闭和排查命令看 [本地开发命令速查](<./docs/本地开发命令速查.md>)。
3. 后端细节看 [backend/README.md](./backend/README.md)。
4. 前端细节看 [frontend/README.md](./frontend/README.md)。

如果你想理解架构：

1. 看本文的“核心流程”。
2. 看 [AI 面试官 Agentic Workflow 后端工程 Plan.md](<./docs/AI 面试官 Agentic Workflow 后端工程 Plan.md>)。
3. 看 [reference/MEMORY.md](../reference/MEMORY.md)，它是参考知识库的唯一根入口。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 API | Python 3.11+、FastAPI、Uvicorn |
| Agent 编排 | LangGraph 1.x、LangChain 1.x |
| LLM | OpenAI、Anthropic、DeepSeek、stub 本地假响应 |
| RAG | Chroma、BM25、OpenAI embeddings 或 stub embeddings |
| 状态与数据 | PostgreSQL、Redis、SQLAlchemy、LangGraph checkpointer |
| 在线学习 | Thompson Sampling bandit、trace/outcome/reward 回流 |
| 语音 | WebSocket、Whisper 风格 ASR、TTS 流式返回 |
| 前端 | Next.js 14、React 18、TypeScript、Tailwind、shadcn/ui |

## 本地环境

建议先准备：

- Python 3.11+
- Node.js 18.17+ 或 20 LTS
- npm
- Docker Desktop
- OpenAI API Key，可选；没有 key 也可以用 `stub` 模式跑通流程

本项目默认端口：

| 服务 | 端口 |
| --- | --- |
| Backend API | `8000` |
| Frontend | `3000` |
| PostgreSQL | `5433` |
| Redis | `6380` |
| Chroma | `8100` |

## 本地启动

### 1. 启动基础服务

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
docker compose up -d postgres redis chroma
```

MVP 文本 demo 可以不启 Docker，把 `CHECKPOINT_BACKEND=memory`、`LLM_PROVIDER=stub`、`EMBEDDING_PROVIDER=stub` 配好即可。完整 Web 流程建议启动三项服务。

### 2. 安装并启动后端

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,voice]"
copy .env.example .env
```

如果要调用真实模型，在 `backend\.env` 里填写：

```env
OPENAI_API_KEY=你的 OpenAI API Key
```

如果只想本地无 key 跑通，把这些值改成 stub：

```env
LLM_PROVIDER=stub
EMBEDDING_PROVIDER=stub
ASR_PROVIDER=stub
TTS_PROVIDER=stub
CHECKPOINT_BACKEND=memory
```

然后初始化知识库并启动 API：

```powershell
python -m app.scripts.seed_kb
uvicorn app.main:app --reload --port 8000
```

也可以先跑一个命令行文本 demo：

```powershell
python -m app.scripts.run_demo
```

### 3. 安装并启动前端

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm install
copy .env.local.example .env.local
npm run dev
```

浏览器打开：

```text
http://localhost:3000
```

前端开发服务器会把 `/api/v1/*`、`/ws/voice/*`、`/health`、`/admin/*` 代理到 `http://localhost:8000`，本地开发不需要额外配置 CORS。

## 核心流程

面试主流程由 LangGraph 状态机驱动：

```text
resume_parse
  -> director_sample
  -> ask_question
  -> wait_answer
  -> evaluator
  -> refine_followup | director_sample | final_report
```

关键节点：

| 节点 | 作用 |
| --- | --- |
| `resume_parse` | 解析候选人信息和 JD，生成候选人画像、岗位要求和评分维度 |
| `director_sample` | 用 Thompson Sampling 选择下一步面试策略 |
| `ask_question` | Generator Agent 结合 RAG 生成问题 |
| `wait_answer` | 等待候选人文本或语音回答 |
| `evaluator` | Evaluator Agent 按 rubric 评分 |
| `refine_followup` | 针对薄弱点追问 |
| `final_report` | 汇总报告并持久化 |

系统还有一条旁路闭环：

```text
Trace -> Outcome -> Reward -> Bandit update
```

这条旁路用于在线学习和策略优化，不直接污染主问答状态。

## 目录结构

```text
ai-interviewer/
  backend/
    app/
      api/v1/              # REST、WebSocket、admin 路由
      core/                # settings、logging、tracer、request translator
      engine/
        workflow/          # LangGraph state、nodes、routers
        agents/            # Generator、Evaluator、Verifier、Guard 等
        context/           # slot-based ContextBuilder
        rag/               # ingestion、retriever、vectorstore
      memory/              # strategy_store、skill_store、llm_selector
      ml/                  # rl、drift
      data/                # ingest、clean、trainset builder
      voice/               # ASR、TTS、stream buffer
      main.py
    docs/                  # 后端设计和阶段计划
    knowledge/             # 题库、示例简历、skills、strategy memory
    tests/unit/            # 单元测试
    docker-compose.yml
    pyproject.toml
    .env.example
    README.md
  frontend/
    src/app/               # Next.js App Router 页面
    src/components/        # UI、layout、interview 组件
    src/lib/               # API client、hooks、config、utils
    docs/
    package.json
    .env.local.example
    README.md
  docs/                    # 项目级设计文档
  README.md
```

## 主要页面

| 路由 | 说明 |
| --- | --- |
| `/` | 首页和继续上次面试入口 |
| `/interview/setup` | 候选人与岗位信息表单（支持上传简历自动回填） |
| `/interview/[sessionId]` | 文本面试问答页 |
| `/interview/[sessionId]/report` | 面试报告 |
| `/interview/[sessionId]/voice` | 语音面试 |
| `/admin` | Bandit 与 verifier drift 管理面板 |

`/interview/setup` 第一步可以拖拽或选择本地简历（PDF / DOCX / TXT / Markdown，≤5 MB），后端 `POST /api/v1/interview/resume/parse` 会先做字典规则抽取，再可选地用配置的 LLM 进一步润色，把 `summary / skills / highlights` 回填到表单，用户可继续编辑后再开始面试。stub 模式下走纯启发式抽取，无需 API key。

## 常用命令

完整的 Docker Desktop、基础服务、前端、后端启动和关闭命令见：

- [docs/本地开发命令速查.md](<./docs/本地开发命令速查.md>)

后端：

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
.\.venv\Scripts\Activate.ps1
python -m app.scripts.seed_kb
python -m app.scripts.run_demo
uvicorn app.main:app --reload --port 8000
pytest tests/unit -q
```

前端：

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm run dev
npm run typecheck
npm run lint
npm run build
```

## 关键环境变量

后端变量在 `backend/.env`：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `LLM_PROVIDER` | `openai` | 可选 `openai`、`anthropic`、`deepseek`、`stub` |
| `OPENAI_API_KEY` | 空 | OpenAI key |
| `ANTHROPIC_API_KEY` | 空 | Anthropic key |
| `EMBEDDING_PROVIDER` | `openai` | 可选 `openai`、`stub` |
| `CHECKPOINT_BACKEND` | `postgres` | 可选 `postgres`、`memory` |
| `DATABASE_URL` | 指向 `localhost:5433` | PostgreSQL 连接 |
| `REDIS_URL` | 指向 `localhost:6380` | Redis 连接 |
| `CHROMA_HOST` | `localhost` | Chroma host |
| `CHROMA_PORT` | `8100` | Chroma port |
| `API_TOKEN` | 空 | 设置后保护 `/admin/*` 接口 |

前端变量在 `frontend/.env.local`：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE` | `http://localhost:8000` | 后端 API 地址 |

## 参考知识库使用约定

本仓库的参考知识库从 [reference/MEMORY.md](../reference/MEMORY.md) 进入。它用于项目内的模式借鉴、阅读路径和跨项目比较，例如 Claude Code、Hermes Agent、OpenClaw、Agentic-Content-Optimizer 的对比。

不要把它当作官方定义或最新外部观点来源；需要官方或最新信息时，应优先查官方资料或 Web，再回到本仓库做模式对照。

## 状态

当前工程已经包含：

- LangGraph 7 节点面试主流程
- 文本面试与 Web API
- Next.js 前端页面
- WebSocket 语音面试
- Chroma RAG
- Thompson Sampling bandit
- Trace / Outcome / Reward 回流
- Verifier drift 监控与反馈
- Skill injection 与 LLM memory selector

历史测试基线见后端 README 和 `backend/tests/unit`。运行前请以本地最新测试结果为准。
