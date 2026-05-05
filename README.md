# Agentic Interviewer Workspace

> 面向 C 端的 **AI 面试官**：以 LangGraph 编排的多智能体面试主链路为核心业务，配套多维度反馈与跨场成长规划，帮用户练得动、看得到、改得了。
>
> **覆盖方向**：互联网研发岗（Java 后端 / 前端 / AI 全栈 / 移动端 / AI Agent / SRE / AI 算法 / 架构师）+ 业务岗（产品 / 运营 / 销售 / 市场 / HR / 客服 / 通用管理）。详见 `ai-interviewer/backend/knowledge/interview_directions.json`。

这个仓库现在分成两层：**可运行项目** 和 **参考知识库**。这样源码、运行文档、参考资料不会混在一起，后续接入 Git 或做 PR 时也更容易看 diff。

## 目录

```text
Agentic_Interviewer/
  ai-interviewer/   # AI 面试官项目源码和运行文档
  reference/        # 参考知识库，不参与项目运行
  .agents/          # Codex / agent 技能与规则
  .cursor/          # Cursor 相关配置
  AGENTS.md         # 仓库级代理说明
  CLAUDE.md         # Claude/Cursor 规则镜像
```

## 运行项目

项目入口在：

- [ai-interviewer/README.md](./ai-interviewer/README.md)
- [ai-interviewer/backend/README.md](./ai-interviewer/backend/README.md)
- [ai-interviewer/frontend/README.md](./ai-interviewer/frontend/README.md)

常用启动路径：

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

## 参考知识库

[reference/MEMORY.md](./reference/MEMORY.md) 是参考知识库的唯一根入口。它用于仓库内的模式借鉴、阅读路径和跨项目比较，例如 Claude Code、Hermes Agent、OpenClaw、Agentic-Content-Optimizer。

参考知识库不作为项目运行依赖，也不应该和 `ai-interviewer/` 下的产品源码混放。

## Git 建议

如果之后初始化 Git，建议把仓库根目录作为 repo root，这样可以同时管理：

- `ai-interviewer/` 的产品源码和项目文档
- `reference/` 的参考资料
- `.agents/` 的代理配置

如果只想发布 AI 面试官项目，可以在发布流程里只包含 `ai-interviewer/`。

## 关于命名与字段兼容

源码层中仍保留了部分历史 / B 端语义的命名以兼容既有数据：表 `interview_sessions`、字段 `candidate_name`、verdict legacy 值 `strong_hire / hire / no_hire`、RL outcome 信号 `hired / rejected`。展示层做了统一映射，把它们投射成对 C 端用户更直接的成长信号（如 `表现优秀 / 达到目标水平 / 接近达标 / 重点补齐`）。**主线产品语言仍然以"面试 / 评分 / 报告"为核心**，"成长规划 / 多维度反馈"是面试主链路的产出，不替代它。
