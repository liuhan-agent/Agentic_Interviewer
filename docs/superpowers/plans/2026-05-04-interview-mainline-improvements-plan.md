# 面试主链路改造实施计划

> **面向 AI 代理的工作者：** 必需子技能：使用 writing-plans、test-driven-development、verification-before-completion。按用户规则，本计划不使用子代理；逐任务串行执行。

**目标：** 把 `docs/superpowers/audits/2026-05-04-interview-mainline-quality-audit.md` 的 Top 5 actionable findings 落地为可执行任务，按"面试 workflow 编排质量 > 评分可信度 > 复盘与成长规划 > 文案体验打磨"主线推进，并参考 Agentic_Content_Optimizer / Hermes / Claude Code 的成熟模式补强若干薄弱点。  
**前提：** v2 文案校准已完成；阶段 1 + 2 改造已交付；本计划只针对 audit 揭示的 5 个 finding + 2 个跨参考补强项。  
**技术栈：** Python（FastAPI / LangGraph）、TypeScript（Next.js）、SQLAlchemy、pytest、Vitest。

## 跨参考对照（指导改造方向）

| 借鉴源 | 模式 | 落地到 ai-interviewer 的位置 |
|--------|------|----------------------------|
| **Agentic_Content_Optimizer** · LangGraph 业务闭环 | runtime_config 翻译 / quality threshold + max_turns 双限 / refinement loop + delayed reward 旁路 | 已基本对齐；本次借鉴其 **「runtime_config 抽象 = 单一控制面」** 的做法把 `MIN_OVERRIDE_CONFIDENCE` 等魔数提取到 `Settings` |
| **Hermes Agent** · 三层知识（program / declarative / episodic）| 主动 + 后台 review 双路径 / skill 渐进加载 / LRU 缓存 | 借鉴其 **「episodic memory + 跨会话进步轨迹」** 思路，但**本计划不引入用户态**（轻量化做法：先把 evaluator fallback 信号显性化，再在前端用既有 localStorage 跨场对比强化"成长画像") |
| **Claude Code** · MEMORY.md 可编辑长期记忆 + 多 agent 边界 | 编辑性记忆 / scoped recall / multi-agent 边界 | 借鉴其 **「source 透明化」** 模式：报告里把 `training_plan_source: llm / fallback` 像"召回的记忆来源"那样标识给用户 |

## 文件结构

### 需要修改的生产代码

**P2 优先（修后端 baseline 红测试）：**

- `ai-interviewer/backend/tests/unit/test_ws_voice_empty_transcript.py`、`tests/unit/test_interview_error_kind_api.py`：补 `_FakeHandle.max_turns` 字段（fixture 与 prod schema 对齐）

**P3 优先（健壮性补强）：**

- `ai-interviewer/backend/app/engine/workflow/nodes/wait_answer.py`：`_RAW_ANSWER_STORE` 增加 5 分钟 TTL 自动 evict（防异常路径泄漏）；或在 `SessionManager._run_segment_blocking` finally 里无差别清理（看哪个改动更小）
- `ai-interviewer/backend/app/services/session_manager.py`：cancel finally 块兜底 `clear_raw_answer_for_state`
- `ai-interviewer/backend/app/engine/workflow/nodes/evaluator.py`：fallback evaluation 时 `_merge_score` 跳过当前 turn（保留旧 dim score）
- `ai-interviewer/backend/app/engine/workflow/routers.py`：`_attempts_for_dimension` 过滤掉 `_is_evaluator_fallback` 的 turn
- `ai-interviewer/backend/app/core/settings.py`：新增 `verifier_min_override_confidence: float = 0.55` 字段
- `ai-interviewer/backend/app/engine/workflow/nodes/verification.py`：`MIN_OVERRIDE_CONFIDENCE` 改读 settings
- `ai-interviewer/frontend/src/lib/sessionDelta.ts` + `frontend/src/components/interview/ProgressChart.tsx` + 新增 `frontend/src/lib/constants/scores.ts`：抽 `WEAK_DIMENSION_THRESHOLD = 7` 共享常量
- `ai-interviewer/frontend/src/components/interview/ReportView.tsx`：`TrainingPlanCard` 顶部加 `AI 教练 / 系统聚合` badge 显示 `training_plan_source`

**跨参考补强（P3 借鉴 Hermes/Claude Code）：**

- `ai-interviewer/frontend/src/components/interview/ReportView.tsx`：在 `LastSessionDelta` 旁加一个 `GrowthHints` 组件，从 `interviewHistory` 跨场聚合"持续薄弱"维度（>= 3 场分数 < 7）和"持续提升"维度（>= 2 场连涨）——参考 Hermes 的 episodic memory 模式
- `ai-interviewer/frontend/src/lib/sessionDelta.ts`：新增 `buildGrowthHints(history)` 函数

### 需要新增或扩展的测试

- `ai-interviewer/backend/tests/unit/test_raw_answer_ttl.py`：raw answer TTL 单测（如果选 TTL 方案）
- `ai-interviewer/backend/tests/unit/test_session_manager_cancel_cleanup.py`：cancel finally 兜底清理
- 扩展 `ai-interviewer/backend/tests/unit/test_evaluator_pass_invariants.py`：fallback 不进 dim 平均
- `ai-interviewer/backend/tests/unit/test_routing_attempts_excludes_fallback.py`：router fallback 排除
- `ai-interviewer/backend/tests/unit/test_settings_verifier_threshold.py`：settings 字段读取
- `ai-interviewer/frontend/tests/scoreThresholdSource.test.js`：常量抽离不破坏 `buildWeakPracticeHref` / `buildLastSessionDelta`
- `ai-interviewer/frontend/tests/trainingPlanSourceSource.test.js`：badge 渲染 `AI 教练 / 系统聚合`
- `ai-interviewer/frontend/tests/growthHintsSource.test.js`：buildGrowthHints 单测 4-5 用例

## 任务 0：建立基线

**文件：** 不修改文件。

**步骤：**

1. 后端：
   ```powershell
   cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
   .\.venv\Scripts\Activate.ps1
   python -m pytest tests/unit -q
   ```
   预期：908 passed / 15 failed（pre-existing；任务 1 修复目标）。
2. 前端：
   ```powershell
   cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
   npm run typecheck && npm run lint && npm test
   ```
   预期：126 测试 / 124 通过 / 2 admin pre-existing。

**验证：** baseline 数字与上面一致。  
**提交：** 不提交。

## 阶段 1：P2 — 后端 baseline failure 修复（最高 ROI）

> 目的：让 `pytest tests/unit -q` 全绿，不再被 baseline 红色掩盖后续 PR 信号。

### 任务 1.1：fixture `_FakeHandle.max_turns` 修复

**问题源：** prod 代码 `app/api/v1/ws_voice.py:166` 访问 `handle.max_turns`，但测试 fixture `_FakeHandle` 没有定义这个字段。

**文件：**

- `ai-interviewer/backend/tests/unit/test_ws_voice_empty_transcript.py`
- `ai-interviewer/backend/tests/unit/test_interview_error_kind_api.py`

**步骤：**

1. 找到所有定义 `_FakeHandle` 的测试模块；
2. 给类加 `max_turns: int = 8` 默认字段（与 `state.build_initial_state` 默认值一致）；
3. 如果还有其它 attribute 缺失（schema 漂移多于一处），同步补全。

**验证：**

- `python -m pytest tests/unit/test_ws_voice_empty_transcript.py tests/unit/test_interview_error_kind_api.py -q` 全绿。
- `python -m pytest tests/unit -q` 总数 908+15 = 923 passed / 0 failed。

**提交：** 不提交，等用户拍板。

## 阶段 2：P3 — 评分链路健壮性补强（按 audit Top 5 优先）

> 目的：把 audit 揭示的 4 个 P3 finding 一次性修掉。

### 任务 2.1：`_RAW_ANSWER_STORE` TTL + cancel 兜底（audit F2）

**借鉴：** Claude Code 的 "scoped recall" 模式——记忆有明确生存期，不在不需要时占用。

**文件：**

- `ai-interviewer/backend/app/engine/workflow/nodes/wait_answer.py`
- `ai-interviewer/backend/app/services/session_manager.py`
- `ai-interviewer/backend/tests/unit/test_raw_answer_ttl.py`（新建）
- `ai-interviewer/backend/tests/unit/test_session_manager_cancel_cleanup.py`（新建）

**步骤：**

1. `wait_answer.py`：
   - `_RAW_ANSWER_STORE` 改成 `dict[str, tuple[str, float]]`：值是 `(answer, expires_at_monotonic)`；
   - `_store_raw_answer` 写入 `time.monotonic() + 300`；
   - `get_raw_answer_for_state` 读取时检查 `expires_at`，过期则 pop 并返回空字符串；
   - 暴露 `_evict_expired() -> int`（test hook + cron 触发可选）。
2. `session_manager.py`：
   - `cancel` 的 try/finally 末尾无差别 `clear_raw_answer_for_state(state)`；
   - 同时在 `_run_segment_blocking` 异常捕获 finally 块清理。
3. 新单测：
   - TTL：写入后 mock `monotonic` 推进 301s，断言 get 返回空 + ref 已被 pop；
   - cancel cleanup：模拟 evaluator 抛异常，触发 cancel，断言 `_RAW_ANSWER_STORE` 为空。

**验证：** 新单测通过；`tests/unit/test_session_manager_resume_race.py` 等既有测试无回归。  
**提交：** 不提交。

### 任务 2.2：fallback evaluation 不进 dim 平均（audit F3）

**借鉴：** ACO 的 "trace 与 reward 旁路" 思路——pollutant 信号不进主决策路径。

**文件：**

- `ai-interviewer/backend/app/engine/workflow/nodes/evaluator.py`
- `ai-interviewer/backend/tests/unit/test_evaluator_pass_invariants.py`（扩展）

**步骤：**

1. `evaluator.py` 引入 `_is_evaluator_fallback`（从 `final_report.py` 复用 / 抽到共享 helper）；
2. `evaluator_node` 在 `_merge_score` 调用前判断：
   ```python
   if _is_evaluator_fallback(evaluation):
       scores = dict(state.get("scores_per_dim", {}))  # 不更新该 dim
   else:
       scores[dimension] = _merge_score(...)
   ```
3. 同步：fallback 时 `dimension_status` 也保持原值（不升 active）；
4. 单测扩展：fallback evaluation 提交后 dim score 不变 + status 不变。

**验证：** 新断言通过；`test_evaluator_pass_invariants.py` 既有用例无回归。  
**提交：** 不提交。

### 任务 2.3：router `_attempts_for_dimension` 过滤 fallback（audit F4）

**文件：**

- `ai-interviewer/backend/app/engine/workflow/routers.py`
- `ai-interviewer/backend/tests/unit/test_routing_attempts_excludes_fallback.py`（新建）

**步骤：**

1. `_attempts_for_dimension` 加过滤：
   ```python
   def _attempts_for_dimension(state, dimension):
       return sum(
           1
           for qa in state.get("qa_history", [])
           if qa.get("dimension") == dimension
           and not _is_evaluator_fallback(qa.get("evaluation") or {})
       )
   ```
2. 把 `_is_evaluator_fallback` helper 抽到 `app/engine/workflow/eval_helpers.py`（或 reuse 现有 `final_report.py` 内函数）；
3. 新单测：
   - 同 dim 三轮，其中 2 轮 fallback，第 3 轮真实 evaluation；attempts 应为 1；
   - `route_after_eval` 在该场景下不会触发 coverage_advance 强切。

**验证：** 新单测通过；`test_coverage_routing.py` 无回归。  
**提交：** 不提交。

### 任务 2.4：`MIN_OVERRIDE_CONFIDENCE` 接入 settings（audit P3）

**借鉴：** ACO 把 `quality_threshold` / `max_turns` 等阈值集中在 runtime_config 的做法。

**文件：**

- `ai-interviewer/backend/app/core/settings.py`
- `ai-interviewer/backend/app/engine/workflow/nodes/verification.py`
- `ai-interviewer/backend/tests/unit/test_settings_verifier_threshold.py`（新建）

**步骤：**

1. `settings.py` 增加 `verifier_min_override_confidence: float = 0.55`；
2. `verification.py` 顶部 `MIN_OVERRIDE_CONFIDENCE` 改成函数 `_min_override_confidence()` 内 `get_settings().verifier_min_override_confidence`；
3. 单测：
   - 默认值是 0.55；
   - 设置 env `VERIFIER_MIN_OVERRIDE_CONFIDENCE=0.7` 后读取为 0.7；
   - `_apply_verification` 在 confidence 0.6、threshold 0.7 时走 abstain；threshold 0.5 时走翻判。

**验证：** 新单测通过。  
**提交：** 不提交。

### 任务 2.5：阶段 2 整体验证

**步骤：**

1. 后端：`python -m pytest tests/unit -q` 必须全绿（923+ passed）；
2. 前端：保持原状（阶段 2 不动前端）。

**验证：** 全绿。  
**提交：** 不提交。**整阶段 2 视为可独立验收的 milestone。**

## 阶段 3：P3 — 前端阈值统一 + training_plan source badge（audit F5 + Hermes 风格）

### 任务 3.1：`WEAK_DIMENSION_THRESHOLD` 共享常量

**借鉴：** Claude Code 的 `MEMORY.md` 可编辑长期记忆 + 单一来源原则。

**文件：**

- `ai-interviewer/frontend/src/lib/constants/scores.ts`（新建）
- `ai-interviewer/frontend/src/lib/sessionDelta.ts`
- `ai-interviewer/frontend/src/components/interview/ProgressChart.tsx`
- `ai-interviewer/frontend/tests/scoreThresholdSource.test.js`（新建）

**步骤：**

1. `lib/constants/scores.ts` 内容：
   ```ts
   export const WEAK_DIMENSION_THRESHOLD = 7;
   export const STRONG_DIMENSION_THRESHOLD = 8.5;
   ```
2. `sessionDelta.ts` import 并在文档说明：`buildLastSessionDelta` 的 delta 是**变化量**，与 `WEAK_DIMENSION_THRESHOLD` 是不同维度（一个是 trend、一个是 absolute）；
3. `ProgressChart.tsx` 的 `buildWeakPracticeHref` 把 `score >= 7` 替换成 `score >= WEAK_DIMENSION_THRESHOLD`；
4. 测试断言两个工具都从同一常量读取。

**验证：** typecheck / lint / test 全绿；`progressChartSource.test.js` 不挂。  
**提交：** 不提交。

### 任务 3.2：TrainingPlanCard 加 source badge

**借鉴：** Claude Code 把"召回的记忆来源"显式化的模式——用户能区分 LLM 推断 vs 系统聚合。

**文件：**

- `ai-interviewer/frontend/src/components/interview/ReportView.tsx`
- `ai-interviewer/frontend/tests/trainingPlanSourceSource.test.js`（新建）

**步骤：**

1. `TrainingPlanCard` 顶部接收 `plan.source: "llm" | "fallback" | undefined`；
2. 渲染：
   - `llm` → 绿色 badge `AI 教练`，tooltip "由教练智能体（Coach Agent）从你的回答中提炼"；
   - `fallback` → 琥珀 badge `系统聚合`，tooltip "教练智能体暂不可用，已根据评分聚合生成"；
3. 测试：
   - llm 源时含 "AI 教练"；
   - fallback 源时含 "系统聚合" 不含 "AI 教练"；
   - source 缺失时不渲染 badge。

**验证：** 新测试通过；`reportCoachLanguageSource.test.js` 不挂。  
**提交：** 不提交。

### 任务 3.3：跨场 GrowthHints（Hermes episodic 风格）

**借鉴：** Hermes 的 episodic memory 模式——把"过去发生过什么"显式化给用户，而不是隐式聚合。

**文件：**

- `ai-interviewer/frontend/src/lib/sessionDelta.ts`（扩展导出 `buildGrowthHints`）
- `ai-interviewer/frontend/src/components/interview/ReportView.tsx`（新增 `GrowthHints` 子组件）
- `ai-interviewer/frontend/tests/growthHintsSource.test.js`（新建）

**步骤：**

1. `sessionDelta.ts` 增加：
   ```ts
   export type GrowthHints = {
     persistentWeak: SessionDeltaEntry[];   // ≥3 场分数 < WEAK 的维度
     consecutiveImprove: SessionDeltaEntry[];  // 连续 ≥2 场上涨
   };
   export function buildGrowthHints(
     history: { dimensionScores?: Record<string, number> }[],
   ): GrowthHints | null;
   ```
2. `ReportView.tsx` 新增 `GrowthHints` 组件：
   - useEffect 读取 `getHistory()` + `buildGrowthHints`；
   - 渲染两个小段："连续薄弱" 维度提示用户"集中突破"，"持续提升" 维度告诉用户"保持节奏"；
   - 数据不足（<3 场）不渲染；
3. 在 `LastSessionDelta` 之后渲染。
4. 测试 4-5 用例：
   - history < 3 场返回 null；
   - 持续薄弱 dim 正确识别（连续 3 场 < 7）；
   - 连续提升 dim 正确识别（前后 2 场连涨）；
   - 同一 dim 既是薄弱又是提升 → 优先归 "提升"（避免负面叙事冲突）；
   - SSR 安全（useEffect-only）。

**验证：** 新测试通过；E2E 完成 3-4 场练习后，第 4 场报告页可见两个 GrowthHints 段。  
**提交：** 不提交。**阶段 3 milestone：**完成 LangGraph 主链路质量补强 + 前端跨场显式记忆。

## 完整验证（计划完成时）

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
.\.venv\Scripts\Activate.ps1
python -m pytest tests/unit -q
# 期望：923+ passed / 0 failed

cd ..\frontend
npm run typecheck    # 0 errors
npm run lint         # 0 warnings
npm test             # 全绿（含 8-10 个新增用例）
```

人工 E2E：

1. `/interview/setup` → 启动一场练习；
2. 故意触发 evaluator fallback（如配置无效 LLM key），观察日志：
   - 该 turn 不应改 dim score（任务 2.2）
   - 该 turn 不计入 attempts（任务 2.3）
3. 完成 3-4 场练习；最后一场报告页：
   - Summary 下显示 `vs 上一次练习` 卡片（已有功能）
   - LastSessionDelta 旁显示 `GrowthHints`（任务 3.3）
   - TrainingPlanCard 顶部显示 `AI 教练` 或 `系统聚合` badge（任务 3.2）
4. 主动触发 cancel：浏览器关 tab 或调 cancel API → 进程内 `_RAW_ANSWER_STORE` 立即清理（任务 2.1）。

## 风险与回滚

| 风险 | 说明 | 缓解 |
|------|------|------|
| 任务 1.1 修 fixture 后又暴露其它 schema 漂移 | 一处修了发现别处还缺 | 优先修当前 15 个失败；其它新发现单独起任务 |
| 任务 2.1 TTL 选错导致正常路径被 evict | 5 分钟够用吗？语音长答可能超时 | 默认 5 分钟，做成 settings 字段 `raw_answer_ttl_seconds=300` 可调；evaluator/verifier 同进程同会话最多 ~1 分钟，余量充裕 |
| 任务 2.2 fallback 不进平均 → 全 fallback 的 dim 一直保持 0 分 | 是 | OK：0 分是 sentinel，下游已过滤；这其实是更正确的语义 |
| 任务 3.3 GrowthHints 数据来源 localStorage → 跨设备不一致 | 已知设计取舍 | 在文档说明用户跨设备查看会有差异；阶段 3 用户系统改造时再统一 |
| 阶段 2 后端改动可能影响 verifier drift monitor | low：drift monitor 是 opt-in feature flag | 默认关闭即不影响 |

## 估算

| 阶段 | 任务数 | 估时 | 优先级 |
|------|--------|------|--------|
| 任务 0：baseline | 1 | 0.1 天 | - |
| 阶段 1：后端 baseline 修复 | 1 | 0.5 天 | 🔴 P2 最高 |
| 阶段 2：评分链路 + 配置化 | 5 | 2 天 | 🟡 P3 |
| 阶段 3：前端常量 + badge + GrowthHints | 3 | 1.5 天 | 🟢 P3（用户体感增强） |

**总计：** 4 天，单开发者完成。

## 给执行者的备注

- 本计划的所有任务都是**独立可验收**的 milestone；如果某阶段卡住，可以只交付完成的部分。
- 每个任务结束后必须跑该模块单测 + 整体回归（`pytest tests/unit -q` 或 `npm test`）确认不破坏既有绿测。
- 跨参考的借鉴只是"思路指引"，**不**复制粘贴 ACO/Hermes/Claude Code 的代码——保持 ai-interviewer 的代码风格一致。
- 不修改 SQL schema、不改 API 协议、不改 LangGraph topology——这些超出本计划范围。
- 任务做完后回报必须包含：修改清单（文件 + 函数 + 改动摘要）、关键改动逻辑（why）、验证步骤（具体命令 + 预期输出）、残留风险。
