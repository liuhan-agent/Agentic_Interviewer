# AI 面试官前端：Next.js 14 版交付计划

> 本计划取代 `backend/webdemo/` 的 vanilla HTML 演示页，在 `frontend/`
> 下建设一套面向作品集 + 实际可用的现代前端。默认范围是 **MVP
> 跑通**（P0）+ 为 P1 语音、P2 admin 面板留接口，不一次吃下全部。

---

## 0. 设计目标

1. **能走通完整面试流程**：设置 → 提问 → 答题 → 报告，业务闭环可演示。
2. **UI 专业、深色、技术感**：对标 Linear / Vercel Dashboard，和
   LangGraph/Thompson Sampling 这类后端调性一致；**首屏就能让人知
   道这是个严肃的 Agent 产品**。
3. **类型严格 + 可组合**：TypeScript 全覆盖 + shadcn/ui（Radix 底
   层，可深改），方便以后加语音、admin 模块时不推翻重来。
4. **与后端零侵入**：不改后端任何代码，仅通过 `/api/v1/interview/*`
   消费现有 REST + 预留 `ws/voice/{id}` 通道。
5. **部署灵活**：
   - 开发：`localhost:3000` 通过 Next.js `rewrites` 代理到
     `localhost:8000` 的后端；无需 CORS 配置。
   - 生产可选：同域部署（`next build && next export` 后静态托管，
     或 Node 运行时 + 反向代理），也支持独立域（`NEXT_PUBLIC_API_BASE`
     显式指向后端地址）。

---

## 1. 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| 框架 | **Next.js 14**（App Router）| 目前社区主流；作品集展示面最好；App Router 的 Server Component / Streaming 后期若加"AI 思考过程实时流"有优势 |
| 语言 | TypeScript | 类型驱动的 API 契约，避免裸 JSON 出错；面试加分 |
| 样式 | **Tailwind CSS v3** | 不管怎么设计都最快；和 shadcn/ui 天然搭配 |
| 组件库 | **shadcn/ui** | 源码拷贝模式，可深度改 Radix；不被锁死 |
| 图标 | **lucide-react** | shadcn/ui 官方搭配 |
| 状态 | 先用 React 本地 + URL params；如需全局再引 Zustand | 不盲目上 Redux / TanStack Query |
| 轮询 | 内置 fetch + AbortController + 手写 `useQuestionPoller` hook | 后端支持 `?timeout=30s` 的长轮询，客户端不用复杂状态库 |
| 表单 | `react-hook-form` + `zod` | 前端直接校验 candidate / job_spec 结构，等后端 422 回来再处理太迟 |
| 主题 | `next-themes` | 深色优先，留浅色切换口 |
| 字体 | Inter（UI）+ JetBrains Mono（代码 / session_id / trace 区域）| 深色 + 技术感标配 |

**暂不引入**：React Query、NextAuth、Radix Primitives 直接用（shadcn 已封装）、Framer Motion（MVP 不上动画，P1 再加）。

---

## 2. 目录结构

```
frontend/
├── README.md
├── docs/
│   └── FRONTEND_PLAN.md      ← 本文件
├── package.json
├── tsconfig.json
├── next.config.mjs
├── tailwind.config.ts
├── postcss.config.mjs
├── .env.local.example
├── .gitignore
├── components.json           ← shadcn/ui 配置
├── src/
│   ├── app/
│   │   ├── layout.tsx        ← 全局字体 / theme provider / toast
│   │   ├── globals.css       ← Tailwind + CSS 变量（shadcn 主题）
│   │   ├── page.tsx          ← 首页 / landing
│   │   ├── interview/
│   │   │   ├── setup/page.tsx            ← P0.1 设置页
│   │   │   ├── [sessionId]/page.tsx      ← P0.2 进行页
│   │   │   └── [sessionId]/report/page.tsx  ← P0.3 报告页
│   │   └── not-found.tsx
│   ├── lib/
│   │   ├── api/
│   │   │   ├── client.ts     ← fetch 封装（timeout / error / trace id）
│   │   │   ├── interview.ts  ← sessions/question/answer/report/resume
│   │   │   └── types.ts      ← StartSessionRequest / Question / Report 类型
│   │   ├── config.ts         ← NEXT_PUBLIC_API_BASE 解析
│   │   ├── hooks/
│   │   │   └── useQuestionPoller.ts
│   │   └── utils.ts          ← cn / formatTurn / etc
│   ├── components/
│   │   ├── ui/               ← shadcn 生成的 button / card / input / ... (原样保留)
│   │   ├── interview/
│   │   │   ├── SetupForm.tsx
│   │   │   ├── QaTimeline.tsx
│   │   │   ├── AnswerBox.tsx
│   │   │   ├── StatusBar.tsx
│   │   │   └── ReportCard.tsx
│   │   ├── landing/
│   │   │   └── HeroPanel.tsx
│   │   └── layout/
│   │       ├── AppShell.tsx
│   │       └── Footer.tsx
│   └── types/
│       └── env.d.ts
└── public/
    └── favicon.ico
```

---

## 3. 与后端的契约（**只读**，不改后端）

基于 `backend/app/api/v1/interview.py` 和 `ws_voice.py`：

| Method | Path | 用途 | 前端页面 |
|---|---|---|---|
| `POST` | `/api/v1/interview/sessions` | 创建 session | setup 页 |
| `GET`  | `/api/v1/interview/sessions/{id}/question?timeout=30` | 长轮询下一题 | 进行页 |
| `POST` | `/api/v1/interview/sessions/{id}/answer` | 提交答案 | 进行页 |
| `GET`  | `/api/v1/interview/sessions/{id}/report` | 拉最终报告 | 报告页 |
| `GET`  | `/api/v1/interview/sessions/{id}/resume` | 断线重连 | 进行页（引导恢复） |
| `WS`   | `/ws/voice/{id}` | 语音（P1 留口） | 进行页 voice 区（P1） |
| `GET`  | `/health` | 健康检查 | 首页右上角 status 指示灯 |
| `GET`  | `/admin/bandit/snapshot` | bandit 观测（P2）| admin 面板（P2） |

**响应形状已稳定**，前端类型直接对照 pydantic 的 `StartSessionRequest` / `poll_question` 返回、`get_report` 返回即可。

---

## 4. 路由与页面流

```
/                         landing（一段 hero + "Start interview" CTA）
/interview/setup          候选人/岗位配置（表单，不再裸 JSON）
/interview/:sessionId     面试进行页（长轮询 + 答题）
/interview/:sessionId/report   最终报告
```

状态保存策略：
- `sessionId` 仅通过 URL 携带（刷新不丢），`localStorage.lastSessionId` 兜底。
- 首页右上角显示 "Resume last session" 链接，若 `localStorage` 有值 +
  后端 `/resume` 可达。

---

## 5. 交付阶段

### P0（本次一次性交付 MVP）

- [ ] **脚手架**：Next.js 14 + TS + Tailwind + shadcn/ui
- [ ] **API client**：`lib/api/*`，错误码统一收敛
- [ ] **landing 页**：hero + CTA，体现 "LangGraph + Thompson + Coach + Verifier" 几个卖点
- [ ] **setup 页**：候选人（name / resume_summary / skills / highlights）+ 岗位（title / level / rubric_dimensions + rubric 简述）友好表单
- [ ] **进行页**：长轮询拉问题 → 答题 → QA timeline
- [ ] **报告页**：解析 `final_report`，渲染 rubric 维度分、pass/fail、weaknesses、coach `training_plan`
- [ ] **resume 体验**：有 `localStorage.lastSessionId` 时首页有 "Continue interview" 按钮；走 `/resume` 接口判断状态
- [ ] **样式**：深色主题默认、loading skeleton、错误 toast、响应式（手机/平板/桌面）
- [ ] **README**：运行指南

### P1（下一批；本次不做）

- [ ] 语音模式集成（`ws/voice/{id}` + MediaRecorder + 音频回放）
- [ ] 问题流式展示（后端若加 SSE 再做）
- [ ] 更多动画（Framer Motion 进场/切换）
- [ ] 多语言 i18n 骨架（至少中英）

### P2（作品集高光）

- [ ] `/admin` 面板：bandit snapshot 可视化（每个 context_key × action 的 α/β 热力/柱状）
- [ ] trace 浏览器：按 session 看每一轮的 director 选择、evaluator verdict、verifier 意见
- [ ] LangSmith 嵌入链接（深度跳转到后端已打通的 tracing 项目）

---

## 6. 验收标准（P0 DoD）

- [ ] `cd frontend && npm install && npm run dev` 成功启动到 `http://localhost:3000`
- [ ] 后端跑在 `:8000` 时，设置 → 提问 → 答题 → 报告完整走通
- [ ] 刷新页面不丢 session（URL + localStorage 双重持久化）
- [ ] TypeScript `npm run typecheck` 0 error
- [ ] Lint `npm run lint` 0 error
- [ ] Lighthouse 首屏：Performance / Accessibility ≥ 80
- [ ] 在 1440px / 768px / 390px 三个断点下页面不破版

---

## 7. 风险与回滚

| 风险 | 缓解 |
|---|---|
| shadcn/ui `init` 失败（某些版本对 pnpm / npm 敏感）| 先用 npm，给出 fallback 命令；组件可以手抄 |
| 后端在生产不同域时 fetch 失败 | 用 `NEXT_PUBLIC_API_BASE` + 本地 `next.config.mjs` rewrites 双保险 |
| Next.js 15 / 14 breaking 差异 | 固定 `"next": "14.2.x"`，避免自动升级 |
| 长轮询的浏览器 tab 掉线 | `AbortController` + 可见性 API 自动重试 |

---

## 8. 下一步

按 Plan 自动执行。我会在每个关键节点（脚手架建好、API client 好、第一个页面渲染成功、MVP 跑通）同步进度。
