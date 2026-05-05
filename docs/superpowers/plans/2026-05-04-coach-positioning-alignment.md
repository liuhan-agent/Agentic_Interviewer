# 面试主链路对齐改造实施计划（v2 校准版）

> **面向 AI 代理的工作者：** 必需子技能：使用 writing-plans、test-driven-development、verification-before-completion。按用户规则，本计划不使用子代理；逐任务串行执行。

> **v2 校准（2026-05-04）：** 用户在阶段 1 + 2 实施完成后明确反馈：
>
> - **面试业务才是核心**——LangGraph 编排的面试主链路 + 评分体系 + 题库 + RAG/RL/语音 是产品含金量所在，不能被弱化；
> - **AI 面试官** 是产品主名 / 主线，不要替换为"AI 面试备战教练"；
> - **不要一直强调"教练"**——教练 / 反馈 / 成长规划是面试主链路的 *配套产出*，不是替代叙事。
>
> 原本 plan 倾向"教练化"叙事过度，已在 v2 同一会话内**反向校准**：报告页保持"面试报告 / 面试质量中心 / 评分维度 / 评分检查项"等核心术语；只剥离明显的招聘官腔（如"综合评估"、"评估候选人"）。详见 §A.7 v2 校准清单。

**目标：** 让 `Agentic_Interviewer / ai-interviewer/` 在保持"AI 面试官"主线产品形态的前提下，剥离明显的 to-B 招聘官腔（如"评估候选人"、"综合评估"），并新增"vs 上一次练习"等增量信号，让 C 端用户在面试主链路完成后**额外**能看到跨场进步。  
**前提认知：** 经过 audit，项目已经做了大量"成长规划"配套（coach prompt / TrainingPlanCard / ProgressChart 进步图 / 专项练习闭环 / 训练回放 / HistoryList 我的练习），完成度约 80%。本计划只做**精确补齐**：删 / 改 / 增的范围尽量小，避免大范围重构既有正常工作的代码。  
**技术栈：** Python（FastAPI / LangGraph）、TypeScript（Next.js）、SQLAlchemy、pytest、Vitest。

## 现状评估摘要（开始任务前必读）

| 模块 | 现状 | 已对齐 | 待对齐 |
|------|------|--------|--------|
| `coach.py` + `coach_task.md` | 完整中文教练 prompt，明禁招聘语言，diagnosis + practice_plan + 30/60/90 完整 | ✅ 已对齐 | 无 |
| `final_report.py` | `_VERDICT_TO_GROWTH_SIGNAL` 已映射为 excellent/target_met/near_target/needs_focus | ✅ 内核已对齐 | 报告字段命名仍带 `verdict` |
| `ReportView.tsx` | `formatVerdict` 完整中文化、TrainingPlanCard 完整、薄弱点专项练习按钮 | ✅ 已对齐 | `QualityCenter` 主体仍展示偏开发者的 yes/partial/no 评分检查项 |
| `SetupForm.tsx` | "目标岗位 + 你是谁 + 面试什么岗位"、`?focus=` 闭环 | ✅ 已对齐 | "通过阈值" 在高级面板裸露 |
| `HistoryList.tsx` + `ProgressChart.tsx` | "我的练习列表 / 进步趋势 / 针对薄弱点专项练习" 完整 | ✅ 已对齐 | 单次报告页缺"vs 上次" |
| `langgraph_workflow.py` | `final_report → training_plan → experience_extractor → END` 已编排 | ✅ 已对齐 | 无 |
| `interview_session.py` | `candidate_name / job_title / job_level` 单次模型，无跨会话用户态 | ⚠️ 半对齐 | 字段语义需文档解释 |
| 项目级文档 (`README.md` / `ai-interviewer/README.md`) | 仍称"AI 面试官 / 候选人画像 / 候选人录入" | ❌ 未对齐 | 需重写定位段 |
| 用户体系 / 成长档案纵向数据 | 无（localStorage 即用户） | ❌ 未对齐 | **重大决策项，独立任务** |

## 文件结构

### 需要修改的生产代码（阶段 1）

- `README.md`、`ai-interviewer/README.md`、`ai-interviewer/backend/README.md`、`ai-interviewer/frontend/README.md`  
  把"AI 面试官 / 候选人画像 / 候选人录入"重写为"面试备战教练 / 成长档案 / 练习入口"。**保留** "候选人字段名兼容性"小节解释为什么 SQL 表字段还叫 `candidate_name`。

- `ai-interviewer/frontend/src/components/interview/ReportView.tsx`  
  `Summary` 卡 description "基于面试全过程的多维度综合评估" 改成 "教练视角的整体反馈和提升方向"；`QualityCenter` 标题 "面试质量中心" + 描述 "先给用户看懂面试是否覆盖充分、题目是否贴合、评分是否有依据" 改成 "练习质量与教练评估依据"；`DimensionScores` 标题 "评分维度" 改成 "维度反馈"。

- `ai-interviewer/frontend/src/components/interview/SetupForm.tsx`  
  `AdvancedPanel` "通过阈值 (0-10)" Label 加副标题 "教练判定达标的目标分数"；`ExpectationBanner` "面试通常包含 5-12 轮问题" 调整为 "练习通常包含 5-12 轮问题，AI 会按你的回答调整难度"。

- `ai-interviewer/frontend/src/components/interview/HistoryList.tsx`  
  `EmptyState` 已经是教练话术，仅微调 `DeleteSessionDialog` 中 "无法查看报告和评估结果" → "无法回看练习反馈"。

### 需要修改的生产代码（阶段 2）

- `ai-interviewer/frontend/src/components/interview/ProgressChart.tsx`  
  `buildWeakPracticeHref` 已存在，新增导出函数 `buildLastSessionDelta(history, currentSessionId)` 给 ReportView 使用。

- `ai-interviewer/frontend/src/components/interview/ReportView.tsx`  
  `Summary` 内增加 `LastSessionDelta` 子组件：从 localStorage 读取本次之前已完成的最近一场，显示 "vs 上次：总分 +0.5 / 技术深度 +1.2 / 沟通 -0.3"；至少 1 场历史时才显示。

- `ai-interviewer/frontend/src/lib/storage/interviewHistory.ts`  
  增加 `getCompletedBefore(sessionId)` 工具函数，返回该 sessionId 之前最近一场已完成（status === "done"）的 entry。

- `ai-interviewer/backend/app/engine/agents/prompts/coach_task.md`  
  新增可选变量 `previous_growth_signal`：当 `final_report` 中携带 `previous_session_summary`（来自 frontend 提交）时，prompt 引导 coach 在 `signal_summary` 中写出"对比上一次有何变化"。**保持向下兼容**——变量缺失时不影响现有行为。

### 需要决策（阶段 3，列入但**不在本计划开始动手**）

- 用户系统：是否要把 `candidate_name` 升级为真正的 `user_id` + 跨会话成长档案表？  
  **影响面**：DB schema 迁移、API 增加 `/users/me/growth_profile`、前端登录态、分布式 session 同步。**1-2 周工作量。**  
  **决策建议**：先停留在「浏览器即用户」轻量化形态完成阶段 1+2，跑一段时间收集真实用户反馈，验证 C 端用户活跃度后再判定。

- 题库针对性：`director_sample`（Thompson Sampling）扩展"按用户历史薄弱点偏置"。  
  **依赖**：阶段 3 用户系统的成长档案数据；当前是单次会话内的 bandit。

### 需要新增或扩展的测试

- `ai-interviewer/frontend/tests/reportCoachLanguageSource.test.js`  
  快照式测试：渲染 `Summary / QualityCenter / DimensionScores` 各 1 个节点，断言文案不含 "评分维度 / 候选人 / 综合评估" 等关键词。

- `ai-interviewer/frontend/tests/lastSessionDeltaSource.test.js`  
  - 无历史时不渲染 delta
  - 有 1 场历史时渲染 "+0.5"
  - 跨维度显示 top 3 dimension delta

- `ai-interviewer/backend/tests/unit/test_coach_previous_session.py`  
  - 当 `previous_session_summary` 在 final_report 中时，coach LLM messages 中包含该字段
  - 字段缺失时行为与现状一致（不破坏现有 `test_coach.py` 基线）

- 扩展 `ai-interviewer/frontend/tests/reportQualityCenterSource.test.js`  
  断言 QualityCenter 卡片标题、描述包含 "教练评估依据" 关键字。

## 任务 0：建立基线

**文件：** 不修改文件。

**步骤：**

1. 进入后端目录运行单元测试：
   ```powershell
   cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
   .\.venv\Scripts\Activate.ps1
   python -m pytest tests/unit -q
   ```
2. 进入前端目录运行测试与类型检查：
   ```powershell
   cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
   npm run typecheck
   npm run test
   ```
3. 把通过情况和失败列表（如有）记下来。

**验证：** 后端 `pytest tests/unit -q` 全绿；前端 `npm run test` 全绿、`npm run typecheck` 无新错误。  
**提交：** 不提交。

## 阶段 1：文案与 UI 微调（小步、立竿见影）

> 阶段 1 共 5 个任务（任务 1.1 ~ 1.5），单一原则：**只改文案 + 标题 + 描述**，不改逻辑、不改类型、不改 API。预计 0.5 天。

### 任务 1.1：项目级 README 重写定位段

**文件：**

- `README.md`
- `ai-interviewer/README.md`
- `ai-interviewer/backend/README.md`（仅"产品定位"相关章节）
- `ai-interviewer/frontend/README.md`（仅"产品定位"相关章节）

**步骤：**

1. 在 `README.md` 顶部 `# Agentic Interviewer Workspace` 后增加一段：
   ```markdown
   > **产品定位：** 这是一款 C 端「AI 模拟面试 + 成长规划」工具，类似「面试备战教练」。目标用户：程序员准备跳槽前刷题练手、应届生练面试感、想转行的人测能力差距。**不是** to-B 招聘 SaaS（如 HireVue / 牛客面试官），所以产品语言强调"诊断差距 + 推下一场怎么练"，而非"评判你值不值得被录用"。
   ```
2. `ai-interviewer/README.md` 顶部第一段 "基于 FastAPI + LangGraph + Next.js 的 AI 面试官项目" 重写为 "基于 FastAPI + LangGraph + Next.js 的 **AI 面试备战教练** 项目"，紧跟一段简介："帮用户做模拟面试、给出分维度反馈、生成针对薄弱点的训练计划，并在多场练习后用进步轨迹给出成长画像。"
3. 修复散落的 "候选人" → "练习者 / 用户"（搜索匹配；DB 字段 `candidate_name` 等保留以保兼容，加注释 "DB 字段名为历史命名，语义代表当前练习者"）。
4. backend / frontend README 的产品语言段同步对齐。

**验证：**

- 视觉检查 README 顶部段落已加入定位说明。
- `rg "候选人" README.md ai-interviewer/*.md` 仅剩 `候选人字段（兼容历史命名）` 这类有解释的留存。

**提交：** 不提交，除非用户要求。

### 任务 1.2：ReportView 教练化文案微调

**文件：** `ai-interviewer/frontend/src/components/interview/ReportView.tsx`

**步骤：**

1. `Summary` 内 `CardTitle` 改为 "练习反馈"（原 "面试报告"）。`CardDescription` 改为 "基于本场练习的整体反馈与下一步提升方向"（原 "基于面试全过程的多维度综合评估"）。
2. `QualityCenter` 内 `CardTitle` 改为 "教练评估依据"（原 "面试质量中心"）。`CardDescription` 改为 "本场练习是否覆盖充分、题目是否贴合你、评分是否有据可查；开发者细节默认折叠"（原 "先给用户看懂..."）。
3. `DimensionScores` 内 `CardTitle` 改为 "维度反馈"（原 "评分维度"）。
4. 任何指向 "返回对话记录" 的按钮文案保留（这是导航不是评分语境）。

**验证：**

- 前端 `npm run typecheck` 无新错误。
- 浏览器打开 `http://localhost:3000/interview/<sid>/report`，看到上述卡片标题已替换。
- 新增前端测试 `reportCoachLanguageSource.test.js`，断言：
  ```js
  expect(source).toContain('"练习反馈"');
  expect(source).toContain('"教练评估依据"');
  expect(source).toContain('"维度反馈"');
  expect(source).not.toContain('"面试报告"');
  ```

**提交：** 不提交。

### 任务 1.3：SetupForm 阈值副标题 + 期望提示句微调

**文件：** `ai-interviewer/frontend/src/components/interview/SetupForm.tsx`

**步骤：**

1. `ExpectationBanner` 第一条 "面试通常包含 5-12 轮问题" 改为 "练习通常包含 5-12 轮问题"。
2. `AdvancedPanel` 中 `Label "通过阈值 (0-10)"` 旁增加描述 `<p className="text-xs text-muted-foreground">教练判定"达标"的目标分数；高于此分会显示"达到目标水平"。</p>`。

**验证：**

- 前端 `npm run typecheck` 无新错误。
- 浏览器打开 `/interview/setup`，顶部条幅 "练习通常..." 已生效；展开高级面板看到副标题。

**提交：** 不提交。

### 任务 1.4：HistoryList 删除对话框文案微调

**文件：** `ai-interviewer/frontend/src/components/interview/HistoryList.tsx`

**步骤：**

1. `DeleteSessionDialog` 列表项 "无法查看报告和评估结果" 改为 "无法回看本场练习反馈"。
2. 顶部提示卡 "会话继续访问凭证仅保存在当前标签页会话中" 保留（功能性提示，不需教练化）。

**验证：**

- 前端 `npm run typecheck` 无新错误。
- 触发删除对话框，"无法回看本场练习反馈" 已生效。

**提交：** 不提交。

### 任务 1.5：阶段 1 整体验证

**步骤：**

1. 后端 `pytest tests/unit -q`：必须全绿（阶段 1 不改后端代码，回归只是防御）。
2. 前端 `npm run test && npm run typecheck && npm run lint`：必须全绿，且新增 `reportCoachLanguageSource.test.js` 通过。
3. 启动后端 + 前端，跑一遍：
   - 进入 `/interview/setup`，确认 ExpectationBanner / AdvancedPanel 文案。
   - 完成一场短面试，跳到 `/interview/<sid>/report`，确认 Summary / QualityCenter / DimensionScores 标题已改。
   - 进入 `/interview/history`，触发删除对话框，确认 "无法回看本场练习反馈"。

**验证：** 上述 3 项全部通过；屏幕截图保留作为交付凭证（可选）。  
**提交：** 不提交。**整阶段 1 视为可独立验收的 milestone。**

## 阶段 2：单次报告"vs 上次"进步对比（增强体验）

> 阶段 2 共 4 个任务（任务 2.1 ~ 2.4），核心是给单次报告页加上"和上一次比"的教练叙事。预计 0.5 ~ 1 天。

### 任务 2.1：interviewHistory 工具函数扩展

**文件：**

- `ai-interviewer/frontend/src/lib/storage/interviewHistory.ts`
- `ai-interviewer/frontend/tests/interviewHistory.test.js`（已存在，扩展用例）

**步骤：**

1. 在 `interviewHistory.ts` 末尾导出函数：
   ```ts
   export function getCompletedBefore(
     sessionId: string,
   ): InterviewHistoryEntry | null {
     const entries = getHistory()
       .filter((e) => e.status === "done" && e.sessionId !== sessionId)
       .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
     const target = getHistory().find((e) => e.sessionId === sessionId);
     if (!target) return entries[0] ?? null;
     return (
       entries.find((e) => e.createdAt < target.createdAt) ?? null
     );
   }
   ```
2. 在 `interviewHistory.test.js` 增加用例：
   - 当列表为空 → 返回 `null`。
   - 当只有当前 session → 返回 `null`。
   - 当有 1 场更早的 done → 返回那场。
   - 当当前 sessionId 不在列表（极端） → 返回最近一场 done 或 null。
3. 函数防御：对 `getHistory` 抛异常的情况返回 `null`，不传染上游。

**验证：**

- `npm run test interviewHistory.test.js` 通过新增 4 条用例。
- 函数使用 `localStorage` 工具，已有 `getHistory` 已经做了 try/catch，新函数遵循同样的边界处理。

**提交：** 不提交。

### 任务 2.2：ProgressChart 导出 buildLastSessionDelta

**文件：**

- `ai-interviewer/frontend/src/components/interview/ProgressChart.tsx`
- `ai-interviewer/frontend/tests/lastSessionDeltaSource.test.js`（新建）

**步骤：**

1. 在 `ProgressChart.tsx` 末尾新增并导出：
   ```ts
   export type SessionDelta = {
     overall: number | null;
     dimensions: Array<{
       dimension: string;
       label: string;
       delta: number;
     }>;
   };

   export function buildLastSessionDelta(
     current: { overallScore?: number; dimensionScores?: Record<string, number> },
     previous: { overallScore?: number; dimensionScores?: Record<string, number> } | null,
   ): SessionDelta | null {
     if (!previous) return null;
     const overall =
       typeof current.overallScore === "number" &&
       typeof previous.overallScore === "number"
         ? Number((current.overallScore - previous.overallScore).toFixed(1))
         : null;
     const prevDims = previous.dimensionScores ?? {};
     const currDims = current.dimensionScores ?? {};
     const dimensions = Object.keys(currDims)
       .filter((dim) => typeof prevDims[dim] === "number")
       .map((dim) => ({
         dimension: dim,
         label: DIMENSION_LABELS[dim] ?? dim.replaceAll("_", " "),
         delta: Number((currDims[dim] - prevDims[dim]).toFixed(1)),
       }))
       .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
       .slice(0, 3);
     if (overall === null && dimensions.length === 0) return null;
     return { overall, dimensions };
   }
   ```
2. 新建 `tests/lastSessionDeltaSource.test.js`：覆盖 4 个场景：
   - previous 为 null → 返回 null
   - previous 有 overall 但无 dimensions → 仅返回 overall
   - previous 同时有 overall 和 dimensions → 返回完整
   - 当前 overall 缺失但 dimensions 完整 → overall 为 null，dimensions 正常

**验证：** `npm run test lastSessionDeltaSource.test.js` 通过；既有 `progressChartSource.test.js` 不受影响。  
**提交：** 不提交。

### 任务 2.3：ReportView 集成 LastSessionDelta 子组件

**文件：** `ai-interviewer/frontend/src/components/interview/ReportView.tsx`

**步骤：**

1. import 增加：
   ```ts
   import { getCompletedBefore } from "@/lib/storage/interviewHistory";
   import { buildLastSessionDelta, type SessionDelta } from "@/components/interview/ProgressChart";
   ```
2. 在 `Summary` 组件内，根据 `report.session_id` 计算 `delta`，渲染在 `Summary` 标题下：
   ```tsx
   function LastSessionDelta({ sessionId, report }: { sessionId: string; report: FinalReport }) {
     const [delta, setDelta] = useState<SessionDelta | null>(null);
     useEffect(() => {
       const previous = getCompletedBefore(sessionId);
       if (!previous) return;
       setDelta(
         buildLastSessionDelta(
           {
             overallScore: report.overall_score,
             dimensionScores: compactDimensionScores(report.dimension_scores),
           },
           {
             overallScore: previous.overallScore,
             dimensionScores: previous.dimensionScores,
           },
         ),
       );
     }, [sessionId, report]);
     if (!delta) return null;
     return (
       <div className="mt-3 rounded-lg border bg-emerald-500/[0.04] p-3 text-xs">
         <p className="font-medium text-emerald-300">vs 上一次练习</p>
         <div className="mt-2 flex flex-wrap items-center gap-3 text-muted-foreground">
           {delta.overall !== null && (
             <span className="font-mono">
               总分 {delta.overall > 0 ? "+" : ""}{delta.overall.toFixed(1)}
             </span>
           )}
           {delta.dimensions.map((d) => (
             <span key={d.dimension} className="font-mono">
               {d.label} {d.delta > 0 ? "+" : ""}{d.delta.toFixed(1)}
             </span>
           ))}
         </div>
       </div>
     );
   }
   ```
3. 在 `ReportView` 主流中 `<Summary report={report} />` 改为 `<><Summary report={report} /><LastSessionDelta sessionId={sessionId} report={report} /></>`，或者把 `LastSessionDelta` 渲染在 `Summary` 内 `CardContent` 末尾。

**验证：**

- 已完成至少 2 场练习的浏览器，第二场报告页 Summary 下出现 "vs 上一次练习"。
- 单场练习浏览器（清空 localStorage）报告页不显示该卡片，不抛错。
- 前端 `npm run typecheck` 无新错误。

**提交：** 不提交。

### 任务 2.4：阶段 2 整体验证

**步骤：**

1. `npm run test && npm run typecheck && npm run lint`：必须全绿。
2. E2E：
   - 清空 localStorage，完成两场短面试。
   - 第一场报告页 Summary 下**不**显示 delta（无更早记录）。
   - 第二场报告页 Summary 下**显示** "总分 +x.x / 维度 +y.y"。
3. 注意：localStorage 跨场写入由 `upsertEntry` 完成，已被 `ReportView` 的 `syncReportHistory` 在 `r.final_report` 拉到后调用过——所以第二场加载报告时第一场数据已可被 `getCompletedBefore` 读到。

**验证：** 3 条全部通过；前后端测试无回归。  
**提交：** 不提交。**整阶段 2 视为第二个 milestone。**

## 阶段 3：决策性改造（独立提案，本计划不开始动手）

> 阶段 3 涉及产品/数据/账号体系的重大决策，由用户/主控明确选择后再启动；列在这里只为完整。

### 提案 3.1：用户态升级（User + GrowthProfile）

**问题：** 当前 `interviewHistory` 完全在 localStorage，换设备/清缓存就丢；教练定位下"长期成长档案"需要后端持久化。

**改造范围（粗估）：**

- 后端：新增 `users` 表（id, email/external_id, created_at）；新增 `user_growth_profiles` 表（user_id, target_role, weak_dimensions, recent_sessions, total_practice_minutes）；`interview_sessions` 增加 `user_id` 外键。
- API：增加 `/api/v1/users/me`、`/api/v1/users/me/growth-profile`、`/api/v1/users/me/sessions`。
- 前端：登录态（最简：邮箱 + 验证码 / GitHub OAuth）；切换 `interviewHistory` 双写（localStorage + 远端），登录后以远端为准。
- 隐私：练习日志归用户私有，不再是"候选人档案"。

**预计工时：** 1.5 ~ 2 周（含测试）。  
**先决条件：** 用户体量验证（先靠阶段 1 + 2 跑一段时间，确认 C 端用户活跃度后再启动）。

### 提案 3.2：题库按用户薄弱点偏置出题

**问题：** 当前 `director_sample` 是单次会话内的 Thompson Sampling，跨会话薄弱点不会影响下一场推题。

**依赖：** 提案 3.1（用户态）必须先落地；否则没有"用户历史薄弱点"这个长期变量。

**改造范围（粗估）：**

- `director_sample` 接受新输入 `user_long_term_weakness` （来自 GrowthProfile）。
- bandit 先验偏置：长期薄弱维度的初始 Beta 分布偏向"未掌握"。
- 题库标记同主题难度梯度（`question_metadata.difficulty_track`）。

**预计工时：** 1 周。

## 风险与回滚

| 风险 | 描述 | 缓解 |
|------|------|------|
| 文案改动破坏现有测试 | 既有快照/源码测试断言旧文案 | 阶段 1.5 / 2.4 跑全套测试；如有断言失败，先看是否是 testing 在锁旧文案——是则同步更新断言 |
| `getCompletedBefore` 在 SSR 期间被调用 | Next.js 的 SSR 阶段没有 localStorage | 包在 `useEffect` 内、等价于客户端 only；已设计好 |
| LastSessionDelta 写入时机 | 二场跑完才有第一场数据；理论上第一场 `syncReportHistory` 调用早于第二场 ReportView 加载 | 默认 happy path 即可；为保守，`getCompletedBefore` 异常返回 null 不影响主报告渲染 |
| 阶段 1 + 2 改动均集中在前端 | 不动后端业务逻辑、不动数据库 | 任意时刻可 `git revert` 单 commit 回滚 |
| 阶段 3 用户系统改动 | 涉及 schema 迁移与登录态 | 不在本计划开工；启动前另写独立 plan + ADR |

## 完整验证（计划完成时）

按 verification-before-completion 技能要求，**禁止**只口头声称完成；以下所有命令必须实际跑过且贴出输出片段：

```powershell
# 后端
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
.\.venv\Scripts\Activate.ps1
python -m pytest tests/unit -q

# 前端
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm run test
npm run typecheck
npm run lint
```

人工 E2E：

1. `/interview/setup` → 顶部 "练习通常..."、高级面板"通过阈值"副标题；
2. `/interview/<sid>/report` → "练习反馈 / 教练评估依据 / 维度反馈" 三个卡片标题；
3. 已完成两场练习的浏览器在第二场报告页显示 "vs 上一次练习"；
4. `/interview/history` 删除对话框 "无法回看本场练习反馈"。

## 估算

| 阶段 | 任务数 | 估时 | 优先级 |
|------|--------|------|--------|
| 阶段 1（文案 / UI 微调） | 5 | 0.5 天 | 🟢 高（用户立刻感知） |
| 阶段 2（vs 上次进步） | 4 | 0.5 ~ 1 天 | 🟡 中（增强体验） |
| 阶段 3（用户系统等） | 2 提案 | 1.5 ~ 3 周 | 🟠 决策项，待用户/主控明确 |

**总计阶段 1 + 2：** 1 ~ 1.5 天，一个开发者足够。

---

## 给执行者的备注

- 本计划假设接下来由"功能开发"角色逐任务执行；遵循「先红后绿、再重构」、最小化 diff、不引入新依赖。
- 任何任务前必须：(a) 重新读对应文件最新版（避免计划写完后基线漂移）；(b) 跑该模块的现有测试看红绿。
- 任务做完后回报必须包含：修改清单（文件 + 函数 + 改动摘要）、关键改动逻辑（why）、验证步骤（具体命令 + 预期输出）、残留风险。
- 不修改 SQL schema、不改 API 协议、不改 LangGraph topology——这些都属于阶段 3 的决策范围。

---

## 附录 A：文案黑名单（阶段 1 执行者一靠）

> 用 `rg` 实测扫出的"招聘官腔调"残留点，按文件 + 行号 + 现状 + 建议改法整理。**必改**段落是阶段 1 任务 1.1 ~ 1.5 必须覆盖的；**待定**和**保留**只列出来供执行者判断是否带处理。

### A.1 前端用户可见（必改 · 优先级 🔴 高）

| # | 文件 | 行号 | 现状 | 建议改法 | 已在 plan 哪个任务 |
|---|------|------|------|----------|------------------|
| 1 | `frontend/src/components/interview/ReportView.tsx` | 453 | `<CardTitle>面试报告</CardTitle>` | `练习反馈` | 任务 1.2 |
| 2 | `frontend/src/components/interview/ReportView.tsx` | 456 | `基于面试全过程的多维度综合评估。` | `基于本场练习的整体反馈与下一步提升方向。` | 任务 1.2 |
| 3 | `frontend/src/components/interview/ReportView.tsx` | 711 | `<CardTitle>面试质量中心</CardTitle>` | `教练评估依据` | 任务 1.2 |
| 4 | `frontend/src/components/interview/ReportView.tsx` | 695 | `评分检查项已有 yes / partial / no 归因，便于解释结论。` | `教练评估检查项已有 yes / partial / no 归因，便于解释结论。` | **plan 漏列**，并入任务 1.2 |
| 5 | `frontend/src/components/interview/ReportView.tsx` | 868 | `评分检查项` （内部 section 标题） | `教练评估检查项` 或 `评估检查项` | **plan 漏列**，并入任务 1.2 |
| 6 | `frontend/src/components/interview/ReportView.tsx` | 1006 | `各评分维度的得分分布，满分 10 分。` | `各能力维度的得分分布，满分 10 分。` | **plan 漏列**，并入任务 1.2 |
| 7 | `frontend/src/components/interview/ReportView.tsx` | 1071 | `<CardTitle>评分维度</CardTitle>` | `维度反馈` | 任务 1.2 |
| 8 | `frontend/src/app/interview/[sessionId]/report/page.tsx` | 36-37 | `基于你在面试中的表现，AI 面试官从多个维度对你进行了综合评估，并为你生成了个性化的成长建议。` | `这是你这场练习的教练反馈：从多个维度看你当前的强项和差距，并给出针对性的提升建议。` | **plan 漏列**，需新增任务 1.6 |
| 9 | `frontend/src/app/interview/setup/page.tsx` | 25-26 | `填写你的背景和目标岗位，AI 会据此挑选合适的题目和评分维度。没有标准答案——按你真实的想法回答即可，结束后会拿到详细评分和提升建议。` | `填写你的背景和目标岗位，AI 教练会据此选题、按多维度看你的表现。没有标准答案——按你真实的想法回答即可，结束后会拿到分维度反馈和针对性提升建议。` | **plan 漏列**，需新增任务 1.7 |
| 10 | `frontend/src/components/layout/Footer.tsx` | 10 | `AI 面试官 · 智能评估 · 成长规划` | `AI 面试官 · 教练反馈 · 成长规划`（保留 "AI 面试官" 作产品名） | **plan 漏列**，需新增任务 1.8 |

### A.2 项目级文档（必改 · 优先级 🔴 高）

| # | 文件 | 范围 | 现状 | 建议改法 | 已在 plan 哪个任务 |
|---|------|------|------|----------|------------------|
| 11 | `README.md` | 顶部 | 无产品定位段 | 加 quote block 写明 "C 端面试备战教练，不是 to-B HR SaaS" | 任务 1.1 |
| 12 | `ai-interviewer/README.md` | line 1 | `基于 FastAPI + LangGraph + Next.js 的 AI 面试官项目。` | `基于 FastAPI + LangGraph + Next.js 的 **AI 面试备战教练** 项目。` + 一句简介 | 任务 1.1 |
| 13 | `ai-interviewer/backend/README.md` | line 3 | `它负责创建面试会话、编排多智能体问答流程、生成问题、接收回答、评估候选人、输出报告...` | `... 接收回答、给出多维度教练反馈、生成训练计划、输出整合报告...`（关键：评估候选人 → 给出多维度教练反馈） | 任务 1.1 |
| 14 | `ai-interviewer/frontend/README.md` 的 "面试报告" 等小节 | 散布 | "面试报告"等表述 | 改 "练习反馈"，但**保留** "面试" 二字作为练习场景的统称 | 任务 1.1 |

### A.3 后端 fallback 文案（必改 · 优先级 🟡 中）

| # | 文件 | 行号 | 现状 | 建议改法 | 备注 |
|---|------|------|------|----------|------|
| 15 | `backend/app/engine/agents/coach.py` | 345 | `"进行一次完整的模拟面试，综合评估各维度提升。"` | `"进行一次完整的模拟面试，回顾各维度的提升情况。"` | fallback `goals_30_60_90["90_days"]` 的最后一条；用户可见。**plan 漏列**，需新增任务 1.9 |

### A.4 待定 / 微调（💬 执行者自决，可在 PR comment 与 reviewer 讨论）

| # | 文件 | 行号 | 现状 | 讨论点 |
|---|------|------|------|--------|
| 16 | `frontend/src/lib/llm-config.ts` | 193 | `"给你的回答打分，直接影响报告可信度..."` | "打分"在教练定位下偏官话；可改"由教练给出评分"。但这是 LLM 配置面板的开发者向描述，受众偏向技术用户，**改不改皆可**。 |
| 17 | `frontend/src/components/admin/AdminPanel.tsx` | 1695 | `策略存储中保存的战术，按评分维度和职级索引。` | `/admin/*` 是工程师后台，"评分维度"作为内部技术术语**可保留**；如要统一可改"考察维度"。 |
| 18 | `frontend/src/app/page.tsx` | 89 | `一个会自我进化的 AI 面试官` | 首页主标题；"AI 面试官" 作产品名保留，但**可在副标题加一句** "面试备战教练"，强化定位。 |
| 19 | `frontend/src/components/layout/AppShell.tsx` | 177 | `<span>AI 面试官</span>` (导航栏 Logo) | 同上，作产品名保留；如要更准确可改 "AI 面试备战" 但有损品牌一致性。 |
| 20 | `frontend/src/components/interview/InterviewRoom.tsx` 945、`VoiceRoom.tsx` 763 | - | 对话气泡 role label `"面试官"` | 这是模拟面试场景中的对话角色 label，保留无问题；强迫症可改 "AI 教练" 但影响沉浸感。 |
| 21 | `ai-interviewer/docs/AI 面试官 Agentic Workflow 后端工程 Plan.md` | 全文 | 标题与正文使用"AI 面试官"作为系统名 | 工程师设计文档；保留没问题。**可在文档顶部加一句"产品对外名为'AI 面试备战教练'，本设计文档保留'AI 面试官'作为内部系统代号"。** |
| 22 | `frontend/src/lib/avatar/state.ts` | 51 | `description: "准备面试官语音与会话状态"` | 启动状态描述，受众偏开发者，**可保留**；强求一致可改 "教练语音"。 |
| 23 | `frontend/src/components/interview/DigitalHumanStage.tsx` | 168 | `AI 面试官` (数字人头部 label) | 数字人卡片头部 role tag，作为练习场景中的 role label 保留 OK。 |
| 24 | `frontend/src/components/layout/LLMSettingsDialog.tsx` | 258 | `配置你的 API Key，以便 AI 面试官可以代你调用 LLM。` | "AI 面试官"是产品代称，保留 OK；执行者可酌情改 "AI 教练 / 系统"。 |

### A.5 保留（必须不改 · 兼容/技术内部）

| # | 类别 | 文件示例 | 字符串 | 保留理由 |
|---|------|----------|--------|---------|
| 25 | Verdict legacy 映射 | `coach.py:54-58` / `verdicts.ts:18-22` / `ReportView.tsx:1484-1488` | `strong_hire / hire / lean_hire / lean_no_hire / no_hire` | **必须保留**：老 DB 数据可能仍带这些 verdict，映射表已把它们投射成中文成长语言；删除会导致老数据展示空白。 |
| 26 | RL outcome 内部字段 | `outcome_record.py:21,23` / `outcome_reward_bridge.py:5,34` / `settings.py:242` / `test_*` 多处 | `hired / rejected / withdrew / ghosted` | **必须保留**：RL 旁路闭环用 hired 等作 outcome 信号，是后端内部技术语义，永不展示给 C 端用户。**可在 docstring 加一行说明 "internal RL signal, not user-facing"**。 |
| 27 | LLM Prompt 输入变量名 | `coach_task.md:7,73` / `generator_task.md` 多处 / `evaluator_task.md` / `system_skeleton.md` / `memory_selector.md` / `contract_negotiate.md` / `guard_check.md` / `session_summary.md` | `candidate / CANDIDATE` 等 | **必须保留**：LLM Prompt 的 anchor 词；改成"练习者/user"会破坏 LLM 推理稳定性，且这些字符串不向用户展示。 |
| 28 | DB 表 / Python 模型字段名 | `interview_session.py` `candidate_name` / `services/resume_parser.py` 等 | 字段名带 candidate | **必须保留**：改字段名 = schema 迁移，不在阶段 1 范围；保留并在 README 加注 "字段名为历史命名" 即可。 |
| 29 | C 端用户练习的 HR 岗位维度 | `interview_directions.json` `hr_function / talent_acquisition` | 招聘 / 人才招聘 | **必须保留**：C 端用户可能就在练习"应聘 HR 岗"或"招聘官岗"，这个语境下"招聘"是用户**目标岗位**而非 AI 角色，必须保留。 |
| 30 | 测试 fixture 的兼容性数据 | `tests/unit/test_admin_*.py` `test_session_replay_api.py` `test_report_trace_health.py` 等 | `overall_verdict: "hire"` / `outcome="hired"` | **必须保留**：这些是兼容性回归测试，测的是"老数据进来时系统行为不变"。 |
| 31 | 后端工程 plan 文档 | `backend/docs/PLAN_*.md` 等 | "打分"、"评分"、"评估" | **保留**：内部工程师设计文档，受众工程师；保留技术语义反而清晰。 |

### A.6 黑名单使用方法

阶段 1 执行者可按以下顺序操作：

1. **先做 A.1 + A.2 中所有 "必改" 项**：这些覆盖了 plan 任务 1.1 ~ 1.5 的全部 + 漏列的 4 项（任务 1.6 ~ 1.9）。
2. **跑完 A.1 后**，用 `rg "面试报告|面试质量中心|评分维度|评分检查项|综合评估|评估候选" ai-interviewer/frontend/src ai-interviewer/backend/README.md` 应**只剩** A.4 / A.5 的项。
3. **A.3** 改完后跑 `pytest tests/unit/test_coach.py -q`，确认 fallback 测试不挂。
4. **A.4 待定项**：每条单独留 PR comment 等 reviewer 拍板，不要默认改。
5. **A.5 保留项**：执行者**不要碰**；如果 reviewer 建议改 A.5 中的任何一项，先讨论再动。

### A.7 plan 文件本身需要追加的任务（编号续接）

> 由于 audit 时漏了几项（黑名单 #4 #5 #6 #8 #9 #10 #15），按 plan 一致性，建议在阶段 1 末尾追加：

- **任务 1.6**：`report/page.tsx` 头部描述段（黑名单 #8）—— 1 处文案改写。
- **任务 1.7**：`setup/page.tsx` 头部描述段（黑名单 #9）—— 1 处文案改写。
- **任务 1.8**：`Footer.tsx` 第一行（黑名单 #10）—— 1 处文案改写。
- **任务 1.9**：`coach.py` `_fallback_training_plan` 90 天里程碑文案（黑名单 #15）—— 1 处后端文案改写，伴随更新 `tests/unit/test_coach.py` 中如有断言"综合评估"的话改成"回顾"。
- **任务 1.10**：扩展任务 1.5 的整体验证，把 1.6 ~ 1.9 也跑一遍。

阶段 1 任务数从 5 → 9（+4 个任务），估时 0.5 天 → 0.7 天。仍是小步可独立验收的 milestone。

---

## v2 校准清单（2026-05-04 · 实施后用户反馈反向校准）

阶段 1 + 2 实施完成后用户反馈：**"面试业务核心 + 不要一直强调教练"**。在同一会话内对前一波改动按下表反向校准，**保留**"面试报告 / 面试质量中心 / 评分维度"等核心术语，只剥离真正招聘官腔。

| # | 文件 / 位置 | 实施稿（已撤） | v2 校准定稿 |
|---|------------|---------------|-------------|
| A | `ReportView.tsx` Summary CardTitle | 练习反馈 | **面试报告**（原状拼还） |
| B | Summary CardDescription | 基于本场练习的整体反馈与下一步提升方向 | **基于面试全过程的多维度反馈与提升方向**（保面试 + 去"综合评估"招聘官腔） |
| C | QualityCenter CardTitle | 教练评估依据 | **面试质量中心**（原状拼还） |
| D | QualityCenter CardDescription | 本场练习是否覆盖充分... | **本场面试是否覆盖充分...** |
| E | DimensionScores CardTitle | 维度反馈 | **评分维度**（原状拼还） |
| F | QualityCenter 内"评分检查项"字符串 + 描述 | 教练评估检查项 / 反馈包含分维度评分 | **评分检查项 / 报告包含评分结果**（原状拼还） |
| G | DimensionRadar CardDescription | 各能力维度的得分分布 | **各评分维度的得分分布**（原状拼还） |
| H | `report/page.tsx` h1 | 这场练习的教练反馈 | **面试报告** |
| I | `report/page.tsx` 描述句 | 这是你这场练习的教练反馈 | **AI 面试官从多个维度给出了反馈和提升方向** |
| J | `report/page.tsx` 顶标 | 练习反馈 | **最终报告** |
| K | `setup/page.tsx` 描述句 | AI 教练会据此选题 | **AI 面试官会据此挑选题目和评分维度...拿到多维度反馈和提升建议** |
| L | `SetupForm.tsx` ExpectationBanner | 练习通常包含 5-12 轮问题 | **面试通常包含 5-12 轮问题** |
| M | `SetupForm.tsx` 阈值副标题 | 教练判定"达标"的目标分数 | **判定本场面试"达标"的目标分数** |
| N | `HistoryList.tsx` DeleteSessionDialog | 无法回看本场练习反馈 | **无法回看本场面试报告与反馈** |
| O | `Footer.tsx` | AI 面试官 · 教练反馈 · 成长规划 | **AI 面试官 · 多维度反馈 · 成长规划** |

### 校准后保留的改动（v2 没动）

- `coach.py` fallback 90 天里程碑文案"回顾各维度的提升情况"——保留（不算招聘官腔，且 fallback 中性更好）
- `backend/README.md` "评估候选人 → 多维度评分与反馈"——保留（去 to-B 招聘官腔合理）
- README + ai-interviewer/README + frontend/README 顶部——**重写为"以面试主链路为核心、配套多维度反馈与成长规划"** 的语义
- LastSessionDelta 组件 + getCompletedBefore + buildLastSessionDelta + sessionDelta.ts——保留（这是阶段 2 增量功能，不是叙事问题）
- TrainingPlanCard "教练培训计划" 卡片标题——保留（这是 *面试后产物* 的卡片标题，不喧宾夺主）
- coach_task.md 禁招聘语言 prompt 防御——保留（防御逻辑不动）
- verdict legacy mapping (strong_hire / no_hire → 中文成长信号)——保留

### 测试反向联动

- `reportCoachLanguageSource.test.js`：**重写**为"keep interview-first card titles + drop招聘官式 phrasing"双向断言，保 verdict legacy + 报告页头部
- `reportQualityCenterSource.test.js`：断言改回"面试质量中心" / "评分检查项"
- `setupCopy.test.js`：断言改为"无法回看本场面试报告与反馈"

### v2 校准后验证

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm run typecheck   # 0 错误
npm run lint        # 0 警告
npm test            # 126 个 / 124 通过 / 2 个 admin pre-existing baseline failure
cd ..\backend
.\.venv\Scripts\Activate.ps1
python -m pytest tests/unit/test_coach.py -q   # 29 passed
```

### v2 教训

- **产品语言要小步试，不要一次性激进改造**：阶段 1 应该只动招聘官腔最严重的 2-3 处试探，等用户反馈后再扩散。
- **"产品定位 quote block"在 README 顶部容易过度承诺**：副标题应保持产品本名，定位说明放在更克制的位置。
- **测试 grep 锁定旧文案是双刃剑**：既保证回归覆盖，也提示当代码先于测试改时要同步联动。本次每改一波文案都有相应测试同步更新。
