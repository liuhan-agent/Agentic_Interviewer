# Phase 7: Session 与状态管理

## 1. 模块定位

这一层更准确地说，是 OpenClaw 的 `Session` 子系统。

如果借用 phase9 里 `bundle` 的说法，这一层最适合围绕下面这条主线理解：

> `Session` 子系统是 **message bundle 的主要持久化来源、缓存和路由容器，并为 system-side bundle 提供会话侧输入、快照和缓存**。

这句话里要注意三点：

- 它说的是 **`Session` 子系统**，不是狭义的 `SessionEntry` 单个对象
- 它说的是 **message bundle 的主要来源**，以及 **system-side bundle 的会话侧输入**
- 它不是说完整 system-side bundle 会原样存进一个字段，也不是说 `context files`、`tools`、`runtime 约束` 都属于 Session 内核

所以 phase7 的重点不是模型这一轮“最终看到了什么”，而是：

- 一次对话或任务如何被识别
- 这条会话如何被 `sessionKey` 锚定
- 会话状态如何持久化
- transcript 如何记录消息流
- 当前运行时消息工作集如何从持久化状态恢复
- system-side 和 message-side 两类材料如何跨轮次复用
- Session 子系统如何和 Agent / Gateway / Channels 形成闭环

从这个角度看，OpenClaw 的 Session 不是简单聊天记录，而是一套围绕会话状态、消息历史和路由信息组织起来的状态系统。

## 2. 关键源码边界

Session 与状态管理主要由这些目录和文件提供服务：

- 会话数据模型和持久化 API：`src/config/sessions/*`
- 运行时会话解析与状态更新：`src/agents/command/session.ts`、`src/agents/command/session-store.ts`
- transcript 读写：`src/config/sessions/transcript.ts`、`src/sessions/transcript-events.ts`
- session 生命周期事件：`src/sessions/session-lifecycle-events.ts`
- session key 规范与路由：`src/routing/session-key.ts`、`src/sessions/session-key-utils.ts`
- Gateway 侧会话视图和同步：`src/gateway/session-utils.ts`、`src/gateway/session-utils.fs.ts`
- 维护、迁移、预算、缓存：`src/config/sessions/store.ts`、`src/config/sessions/store-maintenance.ts`、`src/config/sessions/store-migrations.ts`、`src/config/sessions/store-cache.ts`、`src/config/sessions/disk-budget.ts`

这也说明了一点：

> `Session` 不是单个文件，也不是单个 JSON 对象，而是一整套 `key -> store -> transcript -> runtime working set -> event -> maintenance` 的状态体系。

## 3. 先修正对 Session 的理解

最容易混淆的，不是一个概念，而是同一个词在不同层级上的指代。

这一章建议先把 4 层东西分开：

- 广义的 `Session` 子系统
- 狭义的 `SessionEntry`
- `Transcript`
- 运行时的 `activeSession.messages`

它们不是同一个东西。

### 3.1 先区分广义 Session 和狭义 SessionEntry

在 OpenClaw 里，`Session` 这个词很容易指代两层：

- **广义 `Session` 子系统**
  - 指整套会话状态体系
  - 包括 `sessionKey`、`SessionEntry`、transcript、运行时 working set、事件和维护模块

- **狭义 `SessionEntry`**
  - 指 `sessions.json` 里那条结构化记录
  - 主要保存状态、路由、配置、缓存、报告和统计

如果不先分开这两层，后面读到“Session 持久化了什么”时，就很容易把 `SessionEntry` 误看成“装下了全部上下文”。

### 3.2 Transcript 不是 Session store，也不是 SessionEntry

Transcript 是消息流和事件日志，通常是 JSONL 文件。  
Session store 是结构化状态库，通常是 `sessions.json` 这类 JSON 存储。

它们的职责不同：

- `SessionEntry` 管结构化状态
- `Transcript` 管消息历史和事件时间线

从源码上也能看到这种分工：

- `SessionEntry` 里有 `sessionFile`、`deliveryContext`、`skillsSnapshot`、`systemPromptReport` 等字段，见 `src/config/sessions/types.ts:68-185`
- transcript 以 JSONL 形式保存 `type: "session"` header 和后续 `type: "message"` 记录，见 `src/config/sessions/transcript.ts:67-180`

### 3.3 运行时还有一层 `activeSession.messages`

除了 `SessionEntry` 和 `Transcript`，OpenClaw 运行时还有一层很关键但更容易被忽略的东西：

- `activeSession.messages`

它是当前这轮可直接参与组装 message bundle 的消息工作集。

每次 attempt 前，运行时会从这层消息出发做：

- `sanitizeSessionHistory(...)`
- provider 相关校验
- `limitHistoryTurns(...)`
- tool pairing repair
- `contextEngine.assemble(...)`

对应链路见 `src/agents/pi-embedded-runner/run/attempt.ts:2130-2184`。

所以更准确地说：

- `Transcript` 是消息历史的持久化来源
- `activeSession.messages` 是消息历史的运行时工作集
- `message context bundle` 是在这层基础上再次整理后得到的本轮输入材料

### 3.4 Session 子系统、SystemPrompt、初始上下文不是一回事

这几个概念如果不拆开，很容易把“会话”直接想成“提示词”。

- `Session` 子系统
  - 负责让这条会话可被识别、复用、回写、广播和恢复
  - 是 message bundle 的主要持久化来源、缓存和路由容器
  - 同时为 system-side bundle 提供会话侧状态、快照和缓存
- `SessionEntry`
  - 是结构化状态条目
  - 保存模型选择、路由、统计、技能快照、prompt 报告等
- `Transcript`
  - 是消息历史日志
  - 保存 user / assistant / tool result 等时间线内容
- `SystemPrompt`
  - 是本轮 system-side 文本的一部分
  - 每次 run 重建
- `初始上下文`
  - 是本轮 run 在真正调用模型前已经装配好的材料集合
  - 在 phase9 里更准确地拆成 `system-side bundle + message bundle`

它们不是一回事，因为它们服务的生命周期不同：

- `Session` 子系统跨轮次维护
- `SessionEntry` 跨轮次保存状态
- `Transcript` 记录消息演化
- `SystemPrompt` 每轮重建
- `初始上下文` 是一次 run 的装配结果，不会完整回存为单个对象

### 3.5 为什么教程里的简化模型在 OpenClaw 中不成立

很多教程会把 `Agent Session` 简化成“用户和 Agent 的会话记录”，甚至直接等价成 prompt 的历史部分。这个理解在 OpenClaw 里不够用。

原因是 OpenClaw 的 `Session` 子系统至少同时承担了三类责任：

- **状态责任**
  - 路由和 `deliveryContext`
  - model / provider / auth override
  - thinking / verbose / reasoning / elevated 状态
  - token、cost、compaction 统计
  - subagent 层级和生命周期
  - ACP 元数据
  - `skillsSnapshot`
  - `systemPromptReport`

- **消息责任**
  - transcript 持久化消息时间线
  - 运行时恢复 `activeSession.messages`
  - 让后续轮次继续使用 compaction 后的历史

- **路由责任**
  - 用 `sessionKey` 把 channel / thread / account / group / subagent / ACP 会话绑到同一条线上

所以在 OpenClaw 里，更准确的理解不是“Session = 聊天记录”，而是：

- `Session` 子系统 = 会话级状态系统
- `SessionEntry` = 结构化状态档案
- `Transcript` = 消息日志
- `activeSession.messages` = 当前运行时消息工作集
- `SystemPrompt` = 这一轮的说明书
- `初始上下文` = 这一轮启动时装进模型和 runtime 的材料合集

这也是为什么 Session 里会有一些 prompt 相关缓存，但 `SessionEntry` 本身仍然不等于完整 prompt。

这些缓存会参与 phase9 里说的 bundle 装配，但它们仍然只是运行时材料的一部分。

所以与其把它理解成“聊天记录对象”，不如把它理解成“会话状态机 + 消息日志 + 路由锚点”的组合。

## 4. Session、SystemPrompt 与初始上下文

这里最容易混的是“Session 到底是不是上下文”。更准确的说法是：`Session` 子系统服务于上下文装配，但不等于上下文本身。

如果想先抓住全图，可以先记这一张三层结构：

```text
Session 子系统
= SessionEntry（结构化状态条目）
+ transcript（消息日志）
+ activeSession.messages（当前运行时消息工作集）
```

这三层都属于广义 `Session` 体系，但不是同一个对象。

- `Session` 子系统
  - message bundle 的主要持久化来源、缓存和路由容器
  - 同时为 system-side bundle 提供会话侧状态、快照和缓存
  - 负责记录这条会话是谁、从哪里来、当前怎么跑、消息历史如何续接
- `SessionEntry`
  - `Session` 子系统里的结构化状态条目
  - 保存路由、模型、配置、统计、`skillsSnapshot`、`systemPromptReport`
- `Transcript`
  - `Session` 子系统里的消息日志
  - 保存 user / assistant / tool result / compaction 等时间线记录
- `activeSession.messages`
  - `Session` 子系统在当前 run 里的消息工作集
  - 是后续 assemble message bundle 的直接输入底座
- `SystemPrompt`
  - 本轮运行时生成的提示词文本
  - 负责告诉模型当前有哪些规则、技能和工具摘要
- `初始上下文`
  - 模型这一轮真正拿到的启动包
  - 在 phase9 里更准确地写成 `system-side bundle + message bundle`

### 4.1 Transcript 文件命名与一个 Session 对应几份日志

这里很容易再混一次：`Transcript` 是 `Session` 子系统里的消息日志层，但它也不是“永远只有一个固定文件名”的单体对象。

更准确的理解是：

- `SessionEntry.sessionFile` 指向当前主 transcript 文件，见 `src/config/sessions/types.ts:78`
- 普通 transcript 默认命名为 `<sessionId>.jsonl`，见 `src/config/sessions/paths.ts:235-259`
- topic / thread 变体会命名为 `<sessionId>-topic-<topicId>.jsonl`，见 `src/config/sessions/paths.ts:235-259`
- `/new` 或 `/reset` 之后，旧 transcript 还可能保留为 `.reset.<timestamp>` 形式的轮换副本；`session-memory` hook 里就专门有 fallback 逻辑去找最新的 `.jsonl.reset.*` sibling，见 `src/hooks/bundled/session-memory/handler.ts:97-132`

所以文档里最稳妥的说法不是“一个 Session 永远只对应一个 transcript 文件”，而是：

> 一个逻辑上的 session 分支，通常有一个当前主 transcript 文件；  
> 但在 topic 场景下会派生 `-topic-...` 文件，在 reset 场景下还可能留下 `.reset.*` 轮换副本。

这也解释了为什么 OpenClaw 更常把 `Transcript` 当成“消息日志层”，而不是“某一个固定文件名的聊天记录”。运行时会先根据 `sessionId`、`sessionFile` 和 sessions 目录去解析当前主文件，再在必要时回退到相关变体，见 `src/config/sessions/transcript.ts:96-123` 与 `src/hooks/bundled/session-memory/handler.ts:138-184`。

### 4.2 OpenClaw 的 Session 到底是怎么区分的

最容易先入为主的理解是：`Session` 只是按消息渠道分。  
这在 OpenClaw 里只对了一部分。

更准确地说：

> OpenClaw 先用 `sessionKey` 决定“这条输入应该落到哪个逻辑会话桶”，  
> 再用 `sessionId + sessionFile` 把这个逻辑会话绑定到具体 transcript。  
> 其中消息渠道当然会参与 `sessionKey` 的构造，但它只是其中一维，不是全部。

可以先用下面这张表抓住主线：

| 层次 | 作用 | 典型内容 | 关键源码 |
| --- | --- | --- | --- |
| `sessionKey` | 逻辑会话桶 / 路由键 | `agent:main:main`、`agent:main:discord:channel:c1`、`agent:main:main:thread:123` | `src/routing/session-key.ts`、`src/routing/resolve-route.ts` |
| `sessionId` | 持久化会话身份 | `sess-...` 这类稳定 id | `src/config/sessions/types.ts`、`src/config/sessions/transcript.ts` |
| `sessionFile` | 当前 transcript 落盘位置 | `<sessionId>.jsonl`、`<sessionId>-topic-<topicId>.jsonl` | `src/config/sessions/paths.ts`、`src/config/sessions/session-file.ts` |
| 派生元数据 | 标记分支关系 | `parentSessionKey`、`spawnedBy`、`spawnDepth`、`forkedFromParent` | `src/config/sessions/types.ts` |

所以真正的区分逻辑不是“只有渠道”，而是：

```text
sessionKey
-> 决定逻辑上是不是同一条会话线

sessionId + sessionFile
-> 决定这条会话线落到哪个 transcript

parent/thread/spawn metadata
-> 决定它是不是某条主线的分支、线程会话或子会话
```

再往下展开，最常见的是下面几类：

| 会话类型 | `sessionKey` 怎么分 | 关键点 |
| --- | --- | --- |
| direct（默认） | 通常收敛到 `agent:<agentId>:main` | 默认 `session.dmScope = "main"` 时，很多私聊会共享主会话，不再继续按渠道/用户拆分，见 `src/routing/session-key.ts:140-166` |
| direct（隔离） | `agent:<agentId>:direct:<peer>` / `agent:<agentId>:<channel>:direct:<peer>` / `agent:<agentId>:<channel>:<accountId>:direct:<peer>` | 取决于 `session.dmScope` 是 `per-peer`、`per-channel-peer` 还是 `per-account-channel-peer`，见 `src/routing/session-key.ts:154-163` |
| group / channel | `agent:<agentId>:<channel>:group:<peerId>` 或 `agent:<agentId>:<channel>:channel:<peerId>` | 这时消息渠道会明确编码进 `sessionKey`，见 `src/routing/session-key.ts:169-173` |
| thread / topic | 在 base key 后再挂 `:thread:<id>` 或 `:topic:<id>` | 这是主会话的线程分支，不是完全无关的新主线，见 `src/routing/session-key.ts:234-252`、`src/config/sessions/delivery-info.ts:8-21` |
| subagent / ACP | 独立 child key，再用 `parentSessionKey` / `spawnedBy` 关联父会话 | 这类会话不仅有自己 key，还保留父子关系元数据，见 `src/config/sessions/types.ts:65-76`、`src/agents/acp-spawn.ts:522-552` |

这也解释了为什么“消息渠道”这个说法既对又不够：

- 对 group / channel 会话来说，渠道通常直接写进 `sessionKey`
- 对 direct 会话来说，是否继续按渠道拆分，要看 `session.dmScope`
- 对 thread/topic、subagent、ACP 这类派生会话来说，还会在渠道之外继续叠加线程或父子维度

如果用一句更稳的架构口径来概括：

> OpenClaw 的 Session 区分核心是 `sessionKey`；  
> `channel` 是 `sessionKey` 的重要组成维度之一，但 direct 会话还会受 `dmScope` 影响，thread / topic / subagent / ACP 则会在此基础上继续派生。

放回你最关心的 Web 控制台或 Web surface 上，也一样成立：

- Web 入口当然会影响 `channel`
- 但它不会自动等于“一个 Web 渠道 = 一个 Session”
- 如果它走的是 direct 语义，还要继续看 `dmScope`
- 如果它带 thread/topic 或派生 child session，还会再继续细分

OpenClaw 的 `SessionEntry` 不是完整 prompt，但它会保存一些和 prompt 相关的缓存和报告，例如：

- `skillsSnapshot`
- `systemPromptReport`

这两个字段虽然都和 prompt 装配有关，但职责完全不同：

- `skillsSnapshot`
  - 更像输入侧快照
  - 保存这轮/这条会话解析出来的 skills 及其 prompt 材料
  - 它回答的是“这次拿哪些 skills 去参与装配”

- `systemPromptReport`
  - 更像输出侧报告
  - 不是完整 prompt 本文，而是 prompt 组装结果的统计和审计信息
  - 它回答的是“最后 system prompt 组成了多少、哪些部分占了多少、哪些 workspace files 被注入或截断了”

从类型定义可以直接看到，`systemPromptReport` 里保存的是：

- `systemPrompt.chars`
- `projectContextChars`
- `nonProjectContextChars`
- `injectedWorkspaceFiles`
- `skills.promptChars`
- `tools.listChars`
- `tools.schemaChars`

见 `src/config/sessions/types.ts:339-389`。

它的生成点在：

- `src/agents/pi-embedded-runner/run/attempt.ts:1735-1762`
- `src/agents/system-prompt-report.ts:80-137`

回写到 session store 的位置在：

- `src/agents/command/session-store.ts:82-83`

这也是为什么它更适合理解成：

> `skillsSnapshot` 是“拿什么去拼”，`systemPromptReport` 是“最后拼成了多少、各部分占了多少”。

还要再补一个很关键的边界：

- 完整的 `SystemPrompt` 不会作为正文原样持久化进 `SessionEntry`
- OpenClaw 更常见的做法是：在 `Session` 子系统里分别保存状态、消息和 prompt 相关缓存，再在每轮 run 时根据 `SessionEntry`、transcript、`activeSession.messages`、context files、tools 和 runtime 约束重新生成 system prompt 并重装配 message bundle

所以更准确地说：

- `Session` 子系统负责“长期保存和恢复哪些材料”
- `SystemPrompt` 负责“本轮告诉模型什么”
- 初始上下文负责“本轮真正带上了什么”

这也是为什么你会在源码里看到 `SessionEntry`、transcript、`skillsSnapshot`、`systemPromptReport`、`activeSession.messages` 这些不同形态。

## 5. Session 的数据模型

`src/config/sessions/types.ts` 里的 `SessionEntry` 是狭义 Session 的核心数据模型，但它不是整个 Session 子系统的全部。

为了避免后面混淆，这一章后续默认按下面这组口径来用词：

- `SessionEntry`
  - store 里的结构化条目
- `Transcript`
  - JSONL 消息日志
- `activeSession.messages`
  - 当前运行时消息工作集
- `Session` 子系统
  - 上面三者再加上 `sessionKey`、事件和维护模块

可以把它分成几组来看。

### 5.1 身份与路由字段

这些字段决定“这条状态属于谁、从哪里来、往哪里去”：

- `sessionId`
- `sessionFile`
- `spawnedBy`
- `spawnedWorkspaceDir`
- `parentSessionKey`
- `forkedFromParent`
- `spawnDepth`
- `subagentRole`
- `subagentControlScope`
- `channel`
- `groupId`
- `subject`
- `groupChannel`
- `space`
- `origin`
- `deliveryContext`
- `lastChannel`
- `lastTo`
- `lastAccountId`
- `lastThreadId`

### 5.2 运行态字段

这些字段更像“这条会话当前怎么运行”的状态：

- `thinkingLevel`
- `fastMode`
- `verboseLevel`
- `reasoningLevel`
- `elevatedLevel`
- `ttsAuto`
- `execHost`
- `execSecurity`
- `execAsk`
- `execNode`
- `responseUsage`
- `providerOverride`
- `modelOverride`
- `authProfileOverride`
- `authProfileOverrideSource`
- `authProfileOverrideCompactionCount`
- `sendPolicy`
- `queueMode`
- `queueDebounceMs`
- `queueCap`
- `queueDrop`
- `inputTokens`
- `outputTokens`
- `totalTokens`
- `totalTokensFresh`
- `estimatedCostUsd`
- `cacheRead`
- `cacheWrite`
- `modelProvider`
- `model`
- `fallbackNoticeSelectedModel`
- `fallbackNoticeActiveModel`
- `fallbackNoticeReason`
- `contextTokens`
- `compactionCount`
- `memoryFlushAt`
- `memoryFlushCompactionCount`

### 5.3 事件与派生字段

这些字段更多用于状态同步、展示和事件驱动：

- `lastHeartbeatText`
- `lastHeartbeatSentAt`
- `abortedLastRun`
- `startedAt`
- `endedAt`
- `runtimeMs`
- `status`
- `systemSent`
- `systemPromptReport`
- `acp`

### 5.4 数据模型的设计思路

这个模型的特点不是“轻”，而是“全”。

它把以下几类信息合并到一条 session 记录里：

- 路由上下文
- 执行参数
- 运行统计
- 模型与认证选择
- 子代理状态
- 通道 delivery 状态
- 提示和技能快照

这也是为什么 Session 能成为 OpenClaw 的状态中枢。

### 5.5 `skillsSnapshot` 和 `systemPromptReport`

这两个字段最容易让人误以为 Session 里存的是完整 prompt，但其实不是。

- `skillsSnapshot` 会保存技能快照，里面有 `prompt`、skills 列表、过滤器和已解析 skills。
- `skillsSnapshot.prompt` 只是 skills 这一部分的 prompt 文本，不是完整 system prompt。
- `systemPromptReport` 记录的是 system prompt 的生成报告，例如字符数、注入了哪些 workspace files、skills 和 tools 各占多少字符。

所以：

- Session 里确实可能缓存 prompt 相关内容
- 但 Session 不等于完整 prompt
- `systemPromptReport` 是报告，不是 prompt 本文

## 6. Session Store

`src/config/sessions/store.ts` 是 session 持久化的核心。

### 6.1 它是什么

Session store 是一份按 `sessionKey -> SessionEntry` 组织的 JSON 状态库。

它负责：

- 从磁盘读取
- LRU 风格缓存
- 并发写入锁
- 迁移旧格式
- 清理过期和异常条目
- 控制磁盘预算

### 6.2 它在哪里

默认路径由 `src/config/sessions/paths.ts` 决定，通常形如：

```text
~/.openclaw/agents/<agentId>/sessions/sessions.json
```

### 6.3 读写策略

`loadSessionStore(...)` 会先查缓存，再读磁盘。  
`updateSessionStore(...)` 会通过写锁和原子写入更新状态。

这说明 session store 的设计目标是：

- 可持久化
- 可并发
- 可恢复
- 可迁移

而不是纯内存对象。

### 6.4 维护能力

和 store 相关的辅助模块包括：

- `store-cache.ts`
- `store-maintenance.ts`
- `store-migrations.ts`
- `disk-budget.ts`
- `reset.ts`
- `metadata.ts`

它们分别负责缓存、维护、迁移、预算控制、重置和元数据派生。

## 7. Session Key 与路由

OpenClaw 的 session 体系非常强调 `sessionKey`。

### 7.1 sessionKey 的作用

`sessionKey` 是会话的路由锚点和持久化锚点。

它用于：

- 找到对应 store entry
- 确定 transcript 文件
- 追踪 channel / thread / account / group 的关系
- 支持 subagent / ACP / cron 等特殊会话形态

### 7.2 关键源码

- `src/routing/session-key.ts`
- `src/sessions/session-key-utils.ts`
- `src/agents/command/session.ts`

### 7.3 session key 的设计特点

它不是单纯随机 id，而是带有语义结构的：

- `agent:<agentId>:<scope>`
- `direct` / `group` / `channel`
- `thread` / `topic`
- `cron`
- `acp`
- `subagent`

这让 session 可以从路由直接推导出归属、渠道和上下文。

## 8. transcript：消息与事件日志

Transcript 是会话状态的另一半。

### 8.1 transcript 的角色

如果 session store 是“状态表”，那么 transcript 就是“消息日志”。

它在 Session 子系统里的定位，不是可有可无的附属物，而是 message bundle 的持久化来源。

它记录的是：

- user / assistant 消息
- tool result 消息和相关时间线内容
- compaction 事件
- idempotency 信息
- message meta

### 8.2 关键源码

- `src/config/sessions/transcript.ts`
- `src/config/sessions/session-file.ts`
- `src/sessions/transcript-events.ts`
- `src/gateway/session-utils.fs.ts`

### 8.3 transcript 文件格式

OpenClaw 的 transcript 通常是 JSONL：

- 每一行一个记录
- `type: "session"` 作为头部
- `message` 记录保存对话内容
- `type: "compaction"` 记录压缩事件

### 8.4 transcript 的落盘和追加

`appendAssistantMessageToSessionTranscript(...)` 会：

- 根据 `sessionKey` 找到对应 `sessionFile`
- 确保 transcript header 存在
- 追加 assistant 消息
- 发出 transcript update 事件

这说明 transcript 不是被动日志，而是会被运行时主动写入的状态流。

## 9. 生命周期与事件

Session 的变化不是只靠读写文件，还是事件驱动的。

### 9.1 会话生命周期事件

`src/sessions/session-lifecycle-events.ts` 提供：

- `onSessionLifecycleEvent(...)`
- `emitSessionLifecycleEvent(...)`

它用于广播：

- 创建
- 结束
- 删除
- 重置
- 子会话变化

### 9.2 transcript 更新事件

`src/sessions/transcript-events.ts` 提供：

- `onSessionTranscriptUpdate(...)`
- `emitSessionTranscriptUpdate(...)`

这使得 transcript 变化可以驱动：

- Gateway 广播
- UI 刷新
- session preview 更新
- 实时消息同步

### 9.3 为什么要分成两个事件面

因为 session 生命周期和 transcript 内容不是同一类变化：

- 生命周期事件关注“会话结构和状态”
- transcript 事件关注“消息内容和时间线”

这两个面分开，系统更容易维护。

## 10. Session 的典型状态流转

最典型的状态流转可以概括成这条链。

```text
输入进入
 -> resolveSessionKeyForRequest(...)
 -> loadSessionStore(...)
 -> resolveSession(...)
 -> resolveSessionTranscriptFile(...)
 -> Agent 执行
 -> updateSessionStoreAfterAgentRun(...)
 -> appendAssistantMessageToSessionTranscript(...)
 -> emitSessionTranscriptUpdate(...)
 -> emitSessionLifecycleEvent(...) / Gateway 广播
```

### 10.1 新会话

当没有可复用的 `sessionKey` 或 `sessionId` 时：

- 生成新的 `sessionId`
- 选择新的 `sessionKey`
- 创建新的 store entry
- 初始化 transcript 文件

### 10.2 复用会话

当 session 已存在时：

- 直接加载已有 entry
- 恢复 thinking / verbose / model override 等字段
- 继续追加 transcript

### 10.3 压缩和回滚

当上下文太长或需要维护时：

- 可能触发 compaction
- `compactionCount` 增加
- `totalTokensFresh` 可能被刷新
- `memoryFlushAt` 等字段也可能更新

### 10.4 删除和重置

删除或重置时：

- session store entry 被清理或重建
- transcript 可能归档到 `*.reset.*` / `*.deleted.*`
- 相关事件被广播给 Gateway/UI

## 11. 与 Agent 的关系

Session 是 Agent 运行的锚点，但不是 Agent 本身。

### 11.1 Agent 如何使用 Session

`src/agents/agent-command.ts` 会先：

- `resolveSession(...)`
- `ensureAgentWorkspace(...)`
- `buildWorkspaceSkillSnapshot(...)`
- `loadModelCatalog(...)`

然后才进入 `runEmbeddedPiAgent(...)`。

### 11.2 Agent 如何回写 Session

运行结束后会调用：

- `src/agents/command/session-store.ts`

把以下内容写回 session store：

- 模型和 provider
- token 统计
- cost 统计
- compaction 次数
- `systemPromptReport`
- `abortedLastRun`
- CLI session id

所以 Agent 和 Session 的关系是：

- Agent 消耗 session
- Agent 也更新 session

这就是 session-first orchestration。

## 12. 与 Gateway 的关系

Gateway 是 session 的控制面观察者和分发者。

### 12.1 Gateway 会读取 session 状态

`src/gateway/session-utils.ts` 会把 session store 和 transcript 转成 Gateway 视图：

- `GatewaySessionRow`
- `GatewayAgentRow`
- `SessionsListResult`

用于 UI、probe、status、history 等功能。

### 12.2 Gateway 会广播 session 变化

Gateway 订阅：

- transcript 更新
- session lifecycle 变化
- agent events

再通过 WebSocket 广播到浏览器、控制面和订阅节点。

所以 Gateway 是 session 状态的实时同步层。

## 13. 与 Channels 的关系

Channels 决定消息从哪里进入，session 决定这些消息最终落到哪里。

### 13.1 Channel 影响 session key

session key 经常会从：

- channel
- accountId
- threadId
- peerId

推导出来。

### 13.2 Channel 影响 deliveryContext

`SessionEntry.deliveryContext` 会保存消息回发所需的信息，例如：

- 目标 channel
- `to`
- accountId
- threadId

这让系统能把回复发回原渠道，而不是只停留在内部。

### 13.3 Channel 影响会话重置和作用域

不同渠道会影响：

- session scope
- reset policy
- channel specific thread binding

所以 session 不是脱离渠道存在的，它和渠道绑定得很紧。

## 14. 这层的设计思路

可以把 Session 与状态管理的设计总结成几条。

### 14.1 文件优先

核心状态先落盘，再做 runtime 包装。

### 14.2 结构化状态和消息日志分离

store 管状态，transcript 管内容。

### 14.3 sessionKey 是路由和持久化的共同锚点

它让 session 能跨入口复用。

### 14.4 生命周期和内容更新分成两个事件面

更清晰，也更适合 UI 同步。

### 14.5 Session 是 Agent、Gateway、Channel 的交汇点

- Agent 读写它
- Gateway 展示和广播它
- Channel 用它来定位消息和回发目标

## 15. 小结

如果把这一层压缩成一句话：

> OpenClaw 的 `Session` 子系统，是一个文件化、可持久化、事件驱动的会话状态系统，主要承载 message bundle 的持久化、缓存和路由，并为 system-side bundle 提供会话侧输入与缓存。

更适合记忆的结构化结论是：

- `Session` 子系统 = 会话级状态系统
- `SessionEntry` = 状态库里的结构化条目
- `Transcript` = 消息日志
- `activeSession.messages` = 当前运行时消息工作集
- `SystemPrompt` = 本轮说明书
- `初始上下文` = 本轮启动包
- `sessionKey` = 路由锚点
- `Lifecycle events` 负责状态变化广播
- `Gateway` 负责展示和同步
- `Agent` 负责消费和回写
- `Channels` 负责进出消息与 delivery context

这也是为什么 Session 是 OpenClaw 平台里非常关键的一层，而不只是聊天历史。
