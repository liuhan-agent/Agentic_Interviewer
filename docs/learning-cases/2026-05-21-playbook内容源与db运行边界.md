# Playbook 内容源与 DB 运行边界

> 日期：2026-05-21
> 状态：draft
> 标签：ai-interviewer, boundary, deployment, playbook

## 一句话结论

把 skills/playbook 从 Markdown 接到 DB，不等于简单迁库；真正要分清的是：Markdown 负责人工维护和审查，DB 负责线上 runtime 和 Admin 观察，strict import 负责显式同步，backend setting 负责回滚。

## 背景

`knowledge/skills/*.md` 最初是本地磁盘上的 Markdown playbook，后来被改造成结构化面试官 playbook：它不再负责出题，只负责“怎么追、盯什么信号、避免什么空泛回答”。随后用户提出一个关键部署问题：如果产品部署成网页应用或容器服务，runtime 是否还能依赖本地 Markdown 目录？

这个问题推动了 `P1.1-skills-db`：新增 `SkillPlaybookCard` 表、strict import CLI、DB backend、Admin 最小观察面和部署说明。但最终方案并不是“把 Markdown 废掉，直接让 DB 成为唯一内容源”，而是采用双层边界：Markdown 仍是内容权威源，DB 是 runtime/observability 存储。

## 现象

### 事实

- `SkillPlaybookCard` 表保存 playbook cards，用于 DB-backed runtime 和 Admin 观察。
- Markdown import 入口是显式命令：
  - `python -m app.scripts.import_skill_playbooks`
  - `python -m app.scripts.import_skill_playbooks --archive-missing`
- `SKILL_PLAYBOOK_BACKEND` 支持：
  - `file`
  - `db`
  - `db_with_file_fallback`
- 默认读源是 `db_with_file_fallback`。
- import service 使用 `source="manual_markdown"` 标识来自 Markdown 的 DB row。
- app startup / `init_db()` 只负责建表或 schema upgrade，不自动导入 Markdown 内容。
- Admin `/admin/skill-playbooks` 展示 DB 中的 playbook 状态，并提供手动 import。
- Admin 不做 playbook CRUD，runtime 不写 playbook 内容。

### 推断

- 用户担心的“网页应用不能依赖本地磁盘”本质上不是文件格式问题，而是部署边界问题：容器启动、内容更新、运行时读取和运维验证不能混在一起。
- 如果直接把 DB 当唯一权威源，会牺牲 Markdown + git diff + code review 的内容治理方式。
- 如果继续只读 Markdown，线上 runtime 状态、Admin 观察、容器部署和内容版本追踪都会变弱。
- 因此 DB 更适合做“运行时副本 / 观察副本”，而不是立刻接管内容编辑权。

### 未确认假设

- 本文不固定写当前 DB 里有多少 playbook cards；数量随 import 状态变化。
- 未来是否要做 Admin CRUD、让 DB 成为唯一权威源，本文不下结论。
- 不同部署方式下，Markdown 是否随镜像打包、是否挂载为 volume，需要另行决定；本文只记录 runtime 不应只能依赖它。

## 期望行为

四个角色要分清：

1. Markdown 内容源：
   - 人工维护。
   - 走 git diff / review。
   - 稳定 ID。
   - 可被 strict import 校验。

2. Strict import：
   - 解析 Markdown frontmatter 和 body。
   - 校验 required fields、list、bool、tags、duplicate id。
   - 计算 `content_hash`。
   - 内容变化时 `version += 1`。
   - 显式 upsert 到 DB。
   - `--archive-missing` 只归档缺失的 manual markdown row，不删除。

3. DB runtime / observability：
   - 线上运行优先读 DB。
   - Admin 展示 DB 当前状态。
   - 支持过滤、详情、hash/version、body preview。
   - 不作为 runtime 自动写内容的地方。

4. Backend setting / rollback：
   - `db_with_file_fallback`：DB 优先，DB 查询异常或没有 active card 时回退文件。
   - `db`：只读 DB，适合验证 DB runtime 是否完整。
   - `file`：回滚到旧文件读取路径。

## 复现线索

- 输入/场景：
  - 用户问：如果部署成网页应用，playbook 还能不能保存在本地磁盘？
  - 用户追问：如果从磁盘移到 DB，没有 Markdown 结构后还能不能正常检索？
  - 讨论后确定：Markdown 仍是权威内容源，DB 是 runtime 存储，strict import 做同步。
- 相关命令：
  - `python -m app.scripts.import_skill_playbooks --archive-missing`
  - `python -m pytest tests/unit/test_skill_playbook_import.py tests/unit/test_skill_store.py tests/unit/test_admin_skill_playbooks.py -q`
  - `rg -n "skill_playbook_backend|import_skill_playbooks|SkillPlaybookCard" ai-interviewer/backend/app ai-interviewer/backend/tests/unit`
- 相关文件：
  - `ai-interviewer/backend/app/models/skill_playbook.py`
  - `ai-interviewer/backend/app/services/skill_playbook_import.py`
  - `ai-interviewer/backend/app/scripts/import_skill_playbooks.py`
  - `ai-interviewer/backend/app/memory/skill_store.py`
  - `ai-interviewer/backend/app/api/v1/admin.py`
  - `ai-interviewer/frontend/src/components/admin/AdminPanel.tsx`
  - `ai-interviewer/backend/README.md`
  - `ai-interviewer/docs/本地开发命令速查.md`

## 根因判断

直接原因：随着 playbook 正式进入 Generator 主链路，继续只依赖本地 Markdown 文件读取，不利于线上部署、Admin 观察和 runtime 状态确认。

深层原因：

- 内容治理和 runtime 读取是两个不同问题。Markdown 对人工维护友好，DB 对服务运行和观察友好。
- 如果启动时自动导入内容，部署会产生隐式写库副作用；失败时难以判断是启动失败、内容失败还是 DB 写入失败。
- 如果 runtime 直接写 playbook 内容，会破坏“人工维护 + review + strict import”的内容链路。
- 如果 Admin 展示文件系统内容而 runtime 读 DB，观察面又会和运行状态脱节。

## 调试过程

1. 先把 `skills/*` 从 RAG 语料改造成结构化 playbook Markdown。
2. 用户提出部署问题：网页应用不能长期依赖本地磁盘。
3. 规划拆成多个小任务：
   - Task 1：DB model + schema 初始化。
   - Task 2：Markdown 到 DB 的 strict import。
   - Task 3：`skill_store` DB backend。
   - Task 4：Admin 最小观察面。
   - Task 5：workflow 回归 + 部署说明。
4. 实施后默认 runtime backend 变为 `db_with_file_fallback`。
5. 后续 playbook quality 批次继续扩展 DB 字段，但仍保持 Evaluator 不消费、runtime 不写内容的边界。

## 解决方式

已采取的方案：

- 新增 `SkillPlaybookCard` 表。
- 新增 strict import service 和 CLI。
- `skill_store` 支持 `file` / `db` / `db_with_file_fallback`。
- `ask_question_node` 按 settings 传入 playbook backend。
- Admin API 支持 list/detail/import。
- AdminPanel 展示 runtime backend、状态分布、列表、详情、import 按钮。
- 部署文档明确：
  - 首次部署和内容更新需要显式运行 import。
  - app startup 不自动导入内容。
  - 可通过 backend setting 回滚。

## 验证方式

已有验证方向：

- Model/schema：
  - `SkillPlaybookCard` round-trip。
  - SQLite fallback 和 Postgres DDL shape。
  - schema upgrade 可为已有表加列。
- Import：
  - bundled `knowledge/skills` strict import 通过。
  - 缺 frontmatter、缺 required field、空 body、invalid status、非法 tag、重复 id、重复 list 项会整批失败并回滚。
  - 连续 import idempotent。
  - body/frontmatter 变化时 `version += 1`。
  - `archive_missing` 只归档 manual markdown 缺失 row。
- Runtime：
  - DB backend 能映射为 `SkillEntry`。
  - DB 空或异常时 `db_with_file_fallback` 回退文件。
  - DB 有 active cards 但当前 query 无匹配时不回退文件，避免掩盖 selector 缺口。
- Admin/frontend：
  - list/detail/import 可用。
  - AdminPanel 展示 DB-backed playbook 状态。
- Docs：
  - README / 本地命令速查包含 import 命令、backend setting 和“不自动导入”说明。

## 可复用教训

- “迁到 DB”不是一个完整设计；必须同时说明谁是内容权威源、谁是 runtime 读源、谁负责同步、失败如何回滚。
- 对人工维护内容，Markdown + git review 仍然是很强的治理方式，不应因为部署需要就急着让 DB 变成编辑源。
- app startup 不应该悄悄写内容数据；内容初始化应显式、可观察、可重跑、可失败。
- Admin 应观察 runtime 实际使用的数据源，而不是另一个旁路文件系统状态。
- `db_with_file_fallback` 适合平滑迁移，但验收 DB 完整性时要用 `db` 模式，否则 fallback 会掩盖问题。
- `archive_missing` 应显式选择，默认 upsert 更安全。

## 未解决问题

- 未来是否需要 Admin CRUD？如果做，Markdown 是否仍是权威源，还是 DB 成为新权威源？
- 是否需要为 playbook import 增加部署前 preflight 阻断，例如 active card 数为 0 时阻止上线？
- DB row 被手动修改后，下一次 Markdown import 会覆盖；是否需要显式显示“DB manual drift”？
- 是否需要把 playbook card 的 content_hash/version 展示到 trace 或 session artifact，方便追踪某轮面试用的是哪个内容版本？
- 容器部署中 Markdown 是否打包进镜像还是通过 release artifact 管理，需要单独定。

## Source Map

- 代码：
  - `ai-interviewer/backend/app/models/skill_playbook.py`
  - `ai-interviewer/backend/app/services/skill_playbook_import.py`
  - `ai-interviewer/backend/app/scripts/import_skill_playbooks.py`
  - `ai-interviewer/backend/app/memory/skill_store.py`
  - `ai-interviewer/backend/app/api/v1/admin.py`
  - `ai-interviewer/backend/app/engine/workflow/nodes/ask_question.py`
  - `ai-interviewer/frontend/src/components/admin/AdminPanel.tsx`
- 文档：
  - `ai-interviewer/backend/README.md`
  - `ai-interviewer/docs/本地开发命令速查.md`
- 测试：
  - `ai-interviewer/backend/tests/unit/test_skill_playbook_models.py`
  - `ai-interviewer/backend/tests/unit/test_skill_playbook_import.py`
  - `ai-interviewer/backend/tests/unit/test_skill_store.py`
  - `ai-interviewer/backend/tests/unit/test_admin_skill_playbooks.py`
  - `ai-interviewer/backend/tests/unit/test_ask_question_skill_injection.py`
  - `ai-interviewer/backend/tests/unit/test_skills_db_deployment_docs.py`
- 提交线索：
  - `95bd24c feat: structure interviewer skills playbook`
  - `ae67429 feat: add db-backed skills playbooks`
  - `7d7b545 feat: improve skill playbook quality fields`
- 对话/输入：
  - 用户问题：“如果部署成网页应用，就不能保存在本地磁盘了吧。”
  - 用户问题：“如果从磁盘移到 DB，那还 skills/*.md 能正常被检索嘛，没有 markdown 的结构了呀。”
  - 用户判断：“那这样其实很多逻辑都要跟着改呀。”
