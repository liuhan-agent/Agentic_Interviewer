# Agentic Interviewer 前端

前端是 **AI 面试官** 的 Web 界面，基于 **Next.js 14 App Router + TypeScript + Tailwind + shadcn/ui**。它是后端 FastAPI 的薄 UI 壳：页面负责收集输入、展示问题、提交答案、轮询状态、播放语音、展示面试报告与多维度反馈，核心面试主链路逻辑都在 `../backend`。

## 环境要求

- Node.js 18.17+ 或 20 LTS
- npm
- 后端服务运行在 `http://localhost:8000`

## 快速启动

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm install
copy .env.local.example .env.local
npm run dev
```

打开：

```text
http://localhost:3000
```

开发服务器会通过 `next.config.mjs` 代理这些请求到后端：

- `/api/v1/*`
- `/ws/voice/*`
- `/health`
- `/admin/*`

所以本地开发不需要单独配置 CORS。

## 环境变量

默认 `.env.local.example`：

```env
NEXT_PUBLIC_API_BASE=http://localhost:8000
```

如果前端和后端同源部署，可以不改。若前端部署到另一个域名，把它改为后端地址：

```env
NEXT_PUBLIC_API_BASE=https://your-backend.example.com
```

## 脚本

| 命令 | 说明 |
| --- | --- |
| `npm run dev` | 启动开发服务器，默认 `:3000` |
| `npm run build` | 生产构建 |
| `npm run start` | 启动生产构建结果 |
| `npm run lint` | 运行 Next.js ESLint |
| `npm run typecheck` | 运行 TypeScript 类型检查 |

发布前建议执行：

```powershell
npm run typecheck
npm run lint
npm run build
```

## 页面路由

| 路由 | 说明 | 后端接口 |
| --- | --- | --- |
| `/` | 首页和继续上次面试入口 | `GET /health` |
| `/interview/setup` | 候选人与岗位信息表单 | `POST /api/v1/interview/sessions` |
| `/interview/[sessionId]` | 文本面试问答页 | `GET .../question`、`POST .../answer`、`GET .../resume` |
| `/interview/[sessionId]/report` | 面试报告 | `GET .../report` |
| `/interview/[sessionId]/voice` | 语音面试 | `WS /ws/voice/{sessionId}`、`POST .../answer` |
| `/admin` | Bandit 和 verifier drift 管理面板 | `GET /admin/bandit/snapshot`、`GET /admin/drift/verifier` |

`sessionId` 会保存在 URL 中，也会写入 `localStorage.lastSessionId`，用于首页继续上次面试。

## 目录结构

```text
frontend/
  README.md
  docs/
    FRONTEND_PLAN.md
  next.config.mjs          # 本地代理到后端 :8000
  tailwind.config.ts
  components.json          # shadcn/ui 配置
  src/
    app/
      layout.tsx           # 全局布局和主题
      page.tsx             # 首页
      globals.css
      not-found.tsx
      admin/page.tsx       # 管理面板
      interview/
        setup/page.tsx
        [sessionId]/
          page.tsx         # 文本面试
          report/page.tsx  # 报告
          voice/page.tsx   # 语音面试
    components/
      ui/                  # shadcn 基础组件
      layout/              # AppShell、Footer
      landing/             # 首页组件
      interview/           # SetupForm、InterviewRoom、ReportView、VoiceRoom
    lib/
      api/                 # API client 和类型化接口
      hooks/               # useQuestionPoller
      voice/               # WebSocket voice client
      config.ts            # API base URL
      utils.ts
    types/
      env.d.ts
```

## 长轮询如何工作

文本面试页由 `src/lib/hooks/useQuestionPoller.ts` 管理轮询：

1. 页面挂载后先调用 `GET /resume`。
2. 如果已有待回答问题，直接展示。
3. 否则进入长轮询，调用 `GET /question?timeout=30`。
4. 返回 `waiting_for_answer` 时展示问题。
5. 用户提交答案后，中断当前请求并重新开始轮询。
6. 返回 `completed` 时跳转或展示报告。

这样页面刷新后仍可恢复，前提是后端使用 `CHECKPOINT_BACKEND=postgres`。

## 语音面试

语音页位于：

```text
/interview/[sessionId]/voice
```

前端使用浏览器 `MediaRecorder` 采集音频，通过 WebSocket 发给后端：

```text
WS /ws/voice/{sessionId}
```

后端返回 TTS 音频 bytes，前端收集后播放。相关文件：

- `src/components/interview/VoiceRoom.tsx`
- `src/lib/voice/client.ts`

## UI 约定

- 默认暗色主题。
- 使用 Tailwind 和 shadcn/ui 的 CSS variables 做主题。
- 组件不直接调用 `fetch()`，统一走 `src/lib/api/*`。
- `sessionId`、turn index、trace id 等标识符使用 monospace。
- 页面结构尽量保持“薄 UI”，业务状态由后端返回。

## 已实现功能

- 首页和继续上次面试
- 候选人与岗位信息表单
- 文本面试长轮询
- 面试报告页
- 语音面试 WebSocket 客户端
- `/admin` 管理面板
- 页面过渡动画

## 暂未覆盖或后续可扩展

- Transcript 中的 LangSmith 深链 badge
- i18n 多语言框架
- 前端侧更完整的 admin 鉴权体验
- `/admin` 实时刷新

## 常见问题

| 问题 | 处理方式 |
| --- | --- |
| `/interview/setup` 提交后失败或空白 | 确认后端已在 `:8000` 启动 |
| 长轮询返回 `404 session not found` | 后端可能用 `memory` checkpoint 并重启过；新建会话或切到 `postgres` |
| 报告页出现 `409 interview still running` | 面试还在运行，回到问答页等待完成 |
| Tailwind 样式不生效 | 重新 `npm install`，确认 `tailwindcss` 版本满足 `^3.4.13` |
| 语音页无响应 | 确认浏览器允许麦克风权限，后端 WebSocket 已启动 |

## License

与父仓库保持一致。
