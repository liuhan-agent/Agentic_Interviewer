# AI 面试官 Agentic Workflow 后端工程 Plan

这份文档是后端工程的结构化说明，目标是解释 AI 面试官如何用 LangGraph 编排多智能体面试流程，并如何把 RAG、在线策略学习、语音交互、trace 和反馈闭环组合在一起。

## 1. 设计目标

AI 面试官不是开放聊天机器人，而是一个有明确阶段的业务工作流。核心目标：

- 用确定性的 LangGraph 状态机控制面试阶段。
- 用专门的 Agent 处理非确定性任务，例如出题、评分、校验和总结。
- 用 RAG 注入岗位题库、候选人简历和企业知识。
- 用 Thompson Sampling 选择每轮面试策略。
- 用 trace / outcome / reward 旁路闭环支持后续策略学习。
- 通过 REST 和 WebSocket 同时支持文本面试和语音面试。

## 2. 总体架构

```text
Frontend
  -> FastAPI API / WebSocket
  -> Request Translator
  -> InterviewState
  -> LangGraph Workflow
  -> Agent Layer
  -> RAG / Memory / RL / Drift
  -> PostgreSQL / Redis / Chroma
```

主链负责当前面试体验，旁路负责观测、回灌和学习：

```text
主链：Resume Parse -> Director -> Ask -> Listen -> Evaluate -> Refine | Next | Report
旁路：Trace -> Outcome -> Reward -> Bandit Update
```

## 3. 核心工作流

LangGraph 节点：

| 节点 | 作用 |
| --- | --- |
| `resume_parse` | 解析候选人信息、岗位描述和面试目标 |
| `director_sample` | 从策略空间里选择下一轮动作 |
| `ask_question` | 结合 RAG 和策略生成问题 |
| `wait_answer` | 等待候选人文本或语音回答 |
| `evaluator` | 根据 rubric 对答案评分 |
| `refine_followup` | 针对薄弱点追问 |
| `final_report` | 汇总评分、证据、建议和最终报告 |

关键代码位置：

- [state.py](../backend/app/engine/workflow/state.py)
- [graph.py](../backend/app/engine/workflow/graph.py)
- [routers.py](../backend/app/engine/workflow/routers.py)
- [nodes/](../backend/app/engine/workflow/nodes/)
- [session_manager.py](../backend/app/engine/workflow/session_manager.py)

## 4. InterviewState

`InterviewState` 是整个图共享的状态黑板。它包含：

- 候选人信息：`candidate`
- 岗位信息：`job_spec`
- 面试模式：`mode`
- 当前轮次：`turn_idx`
- 当前问题和回答：`current_question`、`current_answer`
- 历史问答：`qa_history`
- 评分维度和结果：`rubric`、`evaluation`、`scores_per_dim`
- 策略选择：`selected_action`、`policy_id`
- 运行配置：`runtime_config`
- trace 信息：`trace_id`
- 最终报告：`final_report`

状态机的原则是：主链状态只保存当前面试所需信息，学习和分析数据通过 trace 旁路持久化，避免污染当前生成链路。

## 5. Agent 层

后端把不同职责拆成多个 Agent：

| Agent | 作用 |
| --- | --- |
| Generator | 根据候选人、JD、RAG 和策略生成问题 |
| Evaluator | 按 rubric 评分，输出优点、问题、追问建议 |
| Verifier | 对 Evaluator 的结论做二次校验 |
| Guard | 处理合规、安全和隐私保护 |
| Contract / Rubric Negotiator | 生成或协商评分标准 |
| Session Summarizer | 总结当前面试上下文 |
| Coach | 生成候选人反馈和训练建议 |

相关代码：

- [agents/](../backend/app/engine/agents/)
- [prompts/](../backend/app/engine/agents/prompts/)
- [context/](../backend/app/engine/context/)

## 6. RAG 知识库

知识库用于支撑面试问题和评分依据，数据位于：

- [knowledge/tech_questions/](../backend/knowledge/tech_questions/)
- [knowledge/behavioral_questions/](../backend/knowledge/behavioral_questions/)
- [knowledge/sample_resumes/](../backend/knowledge/sample_resumes/)
- [knowledge/skills/](../backend/knowledge/skills/)
- [knowledge/strategy/](../backend/knowledge/strategy/)

RAG 相关代码：

- [ingest.py](../backend/app/data/ingest.py)
- [vectorstore.py](../backend/app/engine/rag/vectorstore.py)
- [retriever.py](../backend/app/engine/rag/retriever.py)

初始化命令：

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
python -m app.scripts.seed_kb
```

## 7. 在线策略学习

策略学习采用 Thompson Sampling，而不是 PPO 这类重型 RL。原因是面试场景里每轮决策相对独立，反馈稀疏，bandit 更容易解释、实现和调试。

相关模块：

- [action_space.py](../backend/app/ml/rl/action_space.py)
- [thompson.py](../backend/app/ml/rl/thompson.py)
- [reward_fn.py](../backend/app/ml/rl/reward_fn.py)
- [outcome_reward_bridge.py](../backend/app/ml/rl/outcome_reward_bridge.py)

策略流：

```text
director_sample
  -> ThompsonBandit.sample()
  -> selected_action / policy_id
  -> ask_question
  -> evaluator
  -> immediate_reward
  -> delayed outcome backfill
```

## 8. Trace 与观测

每个关键节点会写入 `generation_traces`，用于：

- 排查某次面试为什么生成某个问题。
- 复盘某轮评分是否合理。
- 生成训练集。
- 回灌 bandit。
- 计算 verifier drift。

相关代码：

- [tracer.py](../backend/app/core/tracer.py)
- [base.py](../backend/app/models/base.py)
- [admin.py](../backend/app/api/v1/admin.py)

常用管理接口：

| 接口 | 说明 |
| --- | --- |
| `GET /admin/bandit/snapshot` | 查看当前 bandit posterior |
| `GET /admin/drift/verifier` | 查看 verifier drift |
| `GET /admin/metrics` | Prometheus 指标 |
| `GET /admin/tracer/health` | trace 写入健康状态 |

## 9. 语音面试

语音链路：

```text
Browser MediaRecorder
  -> WS /ws/voice/{session_id}
  -> ASR
  -> wait_answer resume
  -> next question
  -> TTS bytes
  -> browser playback
```

相关代码：

- [ws_voice.py](../backend/app/api/v1/ws_voice.py)
- [asr.py](../backend/app/voice/asr.py)
- [tts.py](../backend/app/voice/tts.py)

本地无 key 时可使用：

```env
ASR_PROVIDER=stub
TTS_PROVIDER=stub
```

## 10. 持久化与本地运行

默认完整运行依赖：

- PostgreSQL：会话、报告、trace、checkpoint
- Redis：缓存和共享运行状态
- Chroma：向量知识库

启动命令：

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
docker compose up -d postgres redis chroma
```

API 启动：

```powershell
uvicorn app.main:app --reload --port 8000
```

如果只跑本地 demo，可以使用：

```env
LLM_PROVIDER=stub
EMBEDDING_PROVIDER=stub
CHECKPOINT_BACKEND=memory
```

## 11. 阶段状态

当前工程已经覆盖：

- Phase 0：基础骨架和 Docker compose
- Phase 1：7 节点文本面试 MVP
- Phase 2：Thompson Sampling、trace、reward 回流
- Phase 3：语音 WebSocket 和 Next.js 前端
- Phase 4：RAG、迭代评分、安全校验、训练集导出基础
- Phase 5：ContextBuilder、drift feedback、adaptive verifier、skill injection
- V6：LLM memory selector

后续可扩展方向：

- 更完整的生产鉴权和多租户。
- 更细粒度的成本观测。
- Redis 持久化 drift window。
- 更强的端到端测试。
- 更成熟的语音低延迟体验。

## 12. 相关文档

- [项目 README](../README.md)
- [后端 README](../backend/README.md)
- [前端 README](../frontend/README.md)
