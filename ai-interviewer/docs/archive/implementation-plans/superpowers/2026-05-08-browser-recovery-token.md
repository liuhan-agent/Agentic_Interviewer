# 浏览器恢复凭证实现计划

> **面向 AI 代理的工作者：** 在当前会话内按任务顺序执行；禁止使用子代理。每个任务先写失败测试，再实现最小代码，再运行指定验证。

**目标：** 在无登录产品形态下，允许用户关闭浏览器后用本地浏览器恢复凭证继续面试或查看报告。
**架构：** 短会话 token 继续放 `sessionStorage` 并用于常规 API；恢复凭证放 `localStorage`，只用于 `/recover` 换取新的短会话 token。后端只保存 token 哈希和服务端过期时间，删除会话时撤销恢复凭证。
**技术栈：** FastAPI、SQLAlchemy、Pydantic、Next.js 14、TypeScript、localStorage/sessionStorage、Node test runner、pytest。

## 文件结构

- `backend/app/core/session_auth.py`：扩展匿名会话 token 工具，复用高熵 token 生成和常量时间校验。
- `backend/app/core/settings.py`：新增短会话 token 和恢复 token 的 TTL 配置。
- `backend/app/models/interview_session.py`：新增 token 过期、恢复凭证哈希、恢复凭证过期与撤销字段。
- `backend/app/api/v1/interview.py`：创建会话返回恢复凭证，新增 `/recover`，校验 token 过期，删除时撤销凭证。
- `backend/tests/unit/test_session_recovery_token.py`：覆盖恢复成功、过期、撤销、错误收敛和短 token 过期。
- `frontend/src/lib/api/types.ts`：补充 start/recover 响应类型。
- `frontend/src/lib/api/interview.ts`：新增 `recoverSession()`，并提供带恢复重试的 session API wrapper。
- `frontend/src/lib/storage/interviewHistory.ts`：新增恢复凭证读写、过期清理和撤销清理。
- `frontend/src/components/interview/SetupForm.tsx`：创建会话后保存恢复凭证。
- `frontend/tests/interviewHistory.test.js`、`frontend/tests/interviewApiSource.test.js`：补充恢复凭证与 401 自动恢复源码测试。

## 任务 1：后端 token 模型测试先行

**文件：** `backend/tests/unit/test_session_recovery_token.py`

**步骤：**

1. 新建测试文件，先写这组用例：
   ```python
   from datetime import UTC, datetime, timedelta

   from fastapi.testclient import TestClient

   from app.api.v1.interview import router
   from app.main import create_app

   def test_start_session_returns_recovery_token():
       app = create_app()
       client = TestClient(app)
       resp = client.post("/api/v1/interview/sessions", json=_payload())
       assert resp.status_code == 200
       body = resp.json()
       assert body["session_token"]
       assert body["session_token_expires_at"]
       assert body["recovery_token"]
       assert body["recovery_token_expires_at"]
   ```
2. 补充 `_payload()` helper，使用现有最小 candidate/job_spec shape。
3. 增加用例：
   - recovery token 可换新 session token。
   - recovery token 过期返回 401。
   - recovery token 撤销返回 401。
   - 短 session token 过期后原 API 返回 401。
   - 错误详情统一，不暴露是过期、撤销还是不匹配。

**验证：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
pytest tests/unit/test_session_recovery_token.py -q
```

预期：新增测试先失败，原因是响应字段和 `/recover` 尚不存在。

## 任务 2：后端字段与 token 工具

**文件：** `backend/app/core/settings.py`、`backend/app/models/interview_session.py`、`backend/app/core/session_auth.py`

**步骤：**

1. 在 `Settings` 的 session knobs 附近添加：
   ```python
   session_token_ttl_hours: int = 24
   recovery_token_ttl_days: int = 7
   ```
2. 在 `InterviewSession` 增加：
   ```python
   session_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
   recovery_token_hash: Mapped[str | None] = mapped_column(String(128), index=True)
   recovery_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
   recovery_token_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
   ```
3. 在 `session_auth.py` 添加语义化别名，仍复用现有安全实现：
   ```python
   def new_recovery_token() -> str:
       return new_session_token()

   def hash_recovery_token(token: str) -> str:
       return hash_session_token(token)

   def verify_recovery_token(token: str | None, token_hash: str | None) -> bool:
       return verify_session_token(token, token_hash)
   ```

**验证：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
pytest tests/unit/test_session_recovery_token.py -q
```

预期：字段导入问题解决；接口行为仍失败。

## 任务 3：后端 start/recover/access 实现

**文件：** `backend/app/api/v1/interview.py`

**步骤：**

1. 在 `start_session()` 生成 `session_token` 同时生成 `recovery_token`，计算两个过期时间。
2. 把 `session_token_expires_at`、`recovery_token_hash`、`recovery_token_expires_at` 写入 `InterviewSession`。优先通过现有 persistence 路径扩展，避免在 API 里散落 DB 写逻辑。
3. 响应增加：
   ```python
   "session_token_expires_at": session_token_expires_at.isoformat(),
   "recovery_token": recovery_token,
   "recovery_token_expires_at": recovery_token_expires_at.isoformat(),
   ```
4. 修改 `_require_session_access()`：
   - token hash 缺失时保持现有逻辑。
   - token 过期时返回 401。
   - dev/test 兼容逻辑只在没有 token hash 时放行；有 token hash 且过期时不放行。
5. 新增 Pydantic request/response：
   ```python
   class RecoverSessionRequest(BaseModel):
       recovery_token: str = Field(min_length=16, max_length=256)
   ```
6. 新增 `POST /sessions/{session_id}/recover`：
   - 读取 DB row。
   - 校验 `recovery_token_hash`、`recovery_token_expires_at`、`recovery_token_revoked_at`。
   - 成功后生成新的短 session token，更新 hash 和过期时间。
   - 返回新的短 token 和过期时间。
7. 删除会话时设置 `recovery_token_revoked_at=datetime.now(UTC)`，再执行现有删除路径；如果当前删除是物理删除，确保删除前不需要额外撤销。

**验证：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
pytest tests/unit/test_session_recovery_token.py -q
pytest tests/unit/test_session_replay_api.py tests/unit/test_interview_error_kind_api.py -q
```

预期：新增测试通过，既有 session/report/replay 行为不回退。

## 任务 4：前端类型与存储测试先行

**文件：** `frontend/tests/interviewHistory.test.js`、`frontend/tests/interviewApiSource.test.js`

**步骤：**

1. 在 `interviewHistory.test.js` 增加断言：
   - `upsertEntry()` 接收 `recoveryToken` 后写入 localStorage。
   - 过期 recovery token 被清理。
   - 导出记录不包含恢复凭证。
2. 在 `interviewApiSource.test.js` 增加源码断言：
   - 存在 `recoverSession`。
   - 401 后会调用 recover 再重试一次。
   - 不会把 recovery token 放入 `X-Session-Token`。

**验证：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm test -- interviewHistory.test.js interviewApiSource.test.js
```

预期：测试先失败。

## 任务 5：前端 API 与 storage 实现

**文件：** `frontend/src/lib/api/types.ts`、`frontend/src/lib/storage/interviewHistory.ts`、`frontend/src/lib/api/interview.ts`

**步骤：**

1. 扩展 `StartSessionResponse`：
   ```ts
   session_token_expires_at: string;
   recovery_token: string;
   recovery_token_expires_at: string;
   ```
2. 新增：
   ```ts
   export interface RecoverSessionResponse {
     session_id: string;
     session_token: string;
     session_token_expires_at: string;
   }
   ```
3. 在 `interviewHistory.ts` 新增 `recoveryToken` / `recoveryTokenExpiresAt` 字段与 helper：
   - `getRecoveryToken(sessionId)`
   - `writeRecoveryToken(sessionId, token, expiresAt)`
   - `removeRecoveryToken(sessionId)`
4. `getHistory()` 调用 prune 时同时清理过期 recovery token。
5. `interview.ts` 新增：
   ```ts
   export function recoverSession(sessionId: string, recoveryToken: string) {
     return request<RecoverSessionResponse>(
       `${BASE}/sessions/${encodeURIComponent(sessionId)}/recover`,
       { method: "POST", body: { recovery_token: recoveryToken } },
     );
   }
   ```
6. 给 `resumeSession`、`getReport`、`pollQuestion` 增加统一恢复 wrapper：首次 401 时读取 recovery token，调用 recover，保存新短 token，再重试原请求一次。

**验证：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm test -- interviewHistory.test.js interviewApiSource.test.js
npm run typecheck
```

预期：新增测试和类型检查通过。

## 任务 6：创建会话与历史 UI 接入

**文件：** `frontend/src/components/interview/SetupForm.tsx`、`frontend/src/components/interview/HistoryList.tsx`

**步骤：**

1. 在 `SetupForm.tsx` 的 `upsertEntry` 参数中保存：
   ```ts
   sessionToken: res.session_token,
   sessionTokenExpiresAt: res.session_token_expires_at,
   recoveryToken: res.recovery_token,
   recoveryTokenExpiresAt: res.recovery_token_expires_at,
   ```
2. 更新 `HistoryList` 导出逻辑，删除 `recoveryToken` 和 `recoveryTokenExpiresAt`。
3. 如果恢复失败，保持现有 toast 风格，文案使用：
   `恢复凭证已过期，请重新开始一场面试。`

**验证：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm test -- setupFormSource.test.js historyListSource.test.js interviewHistory.test.js
npm run typecheck
```

预期：源码测试和类型检查通过。

## 任务 7：端到端手工验收

**步骤：**

1. 后端用 `APP_ENV=prod`、`CHECKPOINT_BACKEND=postgres` 启动，确保 token 校验真实启用。
2. 前端创建一场面试，确认 localStorage 有历史和恢复凭证，sessionStorage 有短 token。
3. 清空 sessionStorage，保留 localStorage。
4. 刷新 `/interview/history`，点击继续或查看报告。
5. 确认前端先收到 401，再自动 `/recover`，最后原请求成功。
6. 删除会话，再尝试恢复，确认失败。

**验证命令：**

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\backend
pytest tests/unit/test_session_recovery_token.py tests/unit -q
```

```powershell
cd D:\Agent\Agentic_Interviewer\ai-interviewer\frontend
npm run typecheck
npm run lint
npm test
```

预期：后端单测、前端类型检查、lint、node tests 均通过；手工恢复链路符合预期。

## 自检

- 规格覆盖度：后端 token 生命周期、前端恢复、删除撤销、错误处理、测试均有任务覆盖。
- 占位符扫描：无“待定 / TODO / 类似任务”式占位。
- 类型一致性：统一使用 `session_token_expires_at`、`recovery_token`、`recovery_token_expires_at` 后端 snake_case；前端类型同 API response 保持 snake_case，只在 storage entry 内使用 camelCase。
- 范围控制：不引入登录系统，不处理跨设备恢复，不改 BYOK reauth 机制。
