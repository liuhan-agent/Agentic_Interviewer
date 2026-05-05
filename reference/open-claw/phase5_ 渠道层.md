# Phase 5: 渠道层

## 1. 模块定位

渠道层负责把 OpenClaw 接到外部消息世界。

它回答的不是“模型怎么推理”，也不是“Gateway 怎么托管控制面”，而是：

- 消息从哪里来
- 消息要送到哪个 agent / session
- 回复要回到哪个平台、哪个账号、哪个线程
- 不同平台的身份、线程、权限、消息动作如何统一处理

在 OpenClaw 里，渠道层不是单个文件，而是一整套围绕 `ChannelPlugin`、路由、状态、回发和平台适配的子系统。

## 2. 源码边界

### 2.1 渠道抽象与注册

- `src/channels/plugins/types.plugin.ts`
- `src/channels/plugins/types.ts`
- `src/channels/plugins/index.ts`
- `src/channels/plugins/registry.ts`
- `src/channels/plugins/registry-loader.ts`
- `src/channels/plugins/catalog.ts`
- `src/channels/plugins/helpers.ts`
- `src/channels/plugins/status.ts`
- `src/channels/plugins/load.ts`

### 2.2 渠道路由与会话绑定

- `src/routing/resolve-route.ts`
- `src/routing/account-lookup.ts`
- `src/routing/bindings.ts`
- `src/routing/session-key.ts`

### 2.3 Gateway 对渠道的编排

- `src/gateway/server-channels.ts`
- `src/gateway/server-methods/channels.ts`
- `src/gateway/server-methods-list.ts`
- `src/gateway/server.impl.ts`

### 2.4 渠道运行辅助

- `src/channels/command-gating.ts`
- `src/channels/allowlist-match.ts`
- `src/channels/thread-bindings-policy.ts`
- `src/channels/session.ts`
- `src/channels/typing.ts`
- `src/channels/run-state-machine.ts`
- `src/channels/draft-stream-controls.ts`

### 2.5 渠道实现包

当前仓库里，渠道实现主要作为插件包存在于：

- `extensions/*`

例如：

- `extensions/discord`
- `extensions/slack`
- `extensions/telegram`
- `extensions/matrix`
- `extensions/msteams`
- `extensions/voice-call`
- `extensions/zalo`
- `extensions/whatsapp`

这些包通过 `openclaw.plugin.json` 声明渠道能力，再被插件加载器纳入运行时。

## 3. 渠道层的核心抽象

### 3.1 `ChannelPlugin`

渠道层最核心的契约是 `ChannelPlugin`，定义在 `src/channels/plugins/types.plugin.ts`。

它不是一个单一回调，而是一个多面向的适配器集合，包含：

- `config`
- `status`
- `gateway`
- `outbound`
- `mentions`
- `threading`
- `messaging`
- `auth`
- `security`
- `allowlist`
- `pairing`
- `setup`
- `lifecycle`
- `commands`
- `agentPrompt`
- `agentTools`
- `actions`
- `heartbeat`
- `directory`
- `resolver`

这说明渠道插件不是“消息发送器”那么简单，而是一个平台级适配契约。

### 3.2 `ChannelId` 和 `ChannelMeta`

`src/channels/plugins/types.ts` 负责导出渠道抽象的公共类型，包括：

- `ChannelId`
- `ChannelMeta`
- `ChannelCapabilities`
- `ChannelAccountSnapshot`
- `ChannelAgentTool`
- `ChannelThreadingContext`
- `ChannelOutboundTargetMode`

其中：

- `ChannelId` 是渠道标识
- `ChannelMeta` 描述 UI 展示、文档链接、排序、别名等元信息
- `ChannelCapabilities` 描述某个渠道支持哪些能力

### 3.3 核心概念的边界

可以先用最简单的话区分：

- `Channel` 是消息通道和平台适配面
- `Plugin` 是扩展装配单元
- `ChannelPlugin` 是“以插件形式实现的渠道契约”

所以：

> Channel 不是 Plugin 的同义词，ChannelPlugin 只是“渠道通过插件契约被实现”的方式。

## 4. 渠道层怎么加载

### 4.1 插件注册表里的 Channel

`src/plugins/registry.ts` 明确把 `ChannelPlugin` 作为一种插件注册类型：

- `PluginChannelRegistration`
- `PluginChannelSetupRegistration`
- `registry.channels`
- `registry.channelSetups`

这意味着渠道实现不是孤立存在的，而是首先进入 OpenClaw 的插件注册表。

### 4.2 渠道插件的读取入口

`src/channels/plugins/registry-loader.ts` 和 `src/channels/plugins/registry.ts` 负责从当前 active plugin registry 中读取渠道插件。

`src/channels/plugins/index.ts` 提供：

- `listChannelPlugins()`
- `getChannelPlugin(id)`
- `normalizeChannelId(raw)`

`listChannelPlugins()` 会把注册表里的渠道插件做去重和排序，再返回给上层。

### 4.3 目录和 catalog

`src/channels/plugins/catalog.ts` 负责把渠道插件整理成 UI catalog 和安装 catalog。

这层很重要，因为它说明渠道不仅是运行时能力，也是一种可发现、可展示、可安装的产品能力。

### 4.4 插件 manifest 声明渠道

在 `extensions/*/openclaw.plugin.json` 里，渠道包会声明 `channels` 字段。

例如：

- `extensions/discord/openclaw.plugin.json`
- `extensions/slack/openclaw.plugin.json`
- `extensions/telegram/openclaw.plugin.json`
- `extensions/voice-call/openclaw.plugin.json`

这表示：

- 插件包是发布单元
- `channels` 是这个插件包向 OpenClaw 暴露的渠道类型

## 5. 核心渠道和扩展渠道

### 5.1 当前仓库的实际组织方式

从当前源码看，渠道实现主要通过 `extensions/*` 包装，而不是散落在单独的 `src/telegram`、`src/discord` 目录里。

也就是说，当前的核心结构是：

```text
OpenClaw core
 -> src/channels/*
 -> src/routing/*
 -> src/gateway/*

Channel implementations
 -> extensions/*
```

### 5.2 核心渠道的角色

所谓“核心渠道”，更准确地说是：

- OpenClaw 运行时内建支持的渠道抽象
- 以及在官方仓库中常用、优先集成的渠道包

这些渠道通常会作为插件包提供，但会被视为第一梯队能力。

### 5.3 扩展渠道的角色

扩展渠道是通过同一套 `ChannelPlugin` 契约接入的插件包。

它们的特点是：

- 以 `extensions/*` 的 workspace package 形式存在
- 通过 `openclaw.plugin.json` 声明渠道能力
- 通过插件加载器进入 registry
- 复用同一套 Gateway / 路由 / session / outbound / status 运行时

因此，OpenClaw 的渠道层是“统一契约，分包实现”的结构。

## 6. 路由关系

渠道层真正有价值的地方，不是“收到消息”本身，而是“消息如何被路由到正确的 agent/session”。

### 6.1 路由入口

`src/routing/resolve-route.ts` 是消息路由的核心入口之一。

它会根据：

- `channel`
- `accountId`
- `peer`
- `guildId`
- `teamId`
- `memberRoleIds`

等上下文，计算出一个 `ResolvedAgentRoute`。

### 6.2 路由结果

`ResolvedAgentRoute` 会产出：

- `agentId`
- `channel`
- `accountId`
- `sessionKey`
- `mainSessionKey`
- `lastRoutePolicy`
- `matchedBy`

这说明路由的结果不是简单的“发给某个 bot”，而是：

- 选定 agent
- 选定 session
- 选定持久化 key
- 选定 last-route 策略

### 6.3 session key 和路由绑定

`src/routing/session-key.ts` 和 `src/routing/bindings.ts` 负责把 channel / peer / account / group 等信息编码成可持久化、可复用的 session key。

这也是 OpenClaw 很重要的一点：

> 渠道路由最终是 session-first 的，而不是 message-first 的。

### 6.4 常见绑定关系

源码里能看到几类关键绑定：

- channel binding
- account binding
- peer binding
- guild / team binding
- role-based binding

这些绑定让同一个渠道里的不同消息，能落到不同 agent 或不同 session。

## 7. Gateway 和 Channel 的关系

这是最容易混淆的点之一。

### 7.1 Gateway 不是 Channel 本身

Gateway 是控制平面，不是渠道实现。

它负责：

- 启动和维护渠道 runtime
- 暴露 `channels.status` / `channels.logout` 这类控制面方法
- 编排渠道健康状态
- 将渠道状态广播给 UI / 客户端

### 7.2 Channel 也不是 Gateway 的附属壳

ChannelPlugin 是一套完整的渠道适配契约。

它可以定义：

- 入口消息怎么解析
- 回复怎么回发
- 线程怎么绑定
- 账号怎么登录和登出
- 哪些消息动作可用
- 哪些 allowlist / security policy 生效

### 7.3 真实关系

最准确的关系是：

```text
Gateway = 调度和控制中心
ChannelPlugin = 平台适配和消息运输能力
Route = 把消息分给正确的 agent/session
```

因此：

- Gateway 管理渠道的生命周期
- ChannelPlugin 负责具体平台语义
- Routing 负责把消息接到正确的运行上下文

## 8. Gateway 怎么编排渠道

### 8.1 `createChannelManager`

`src/gateway/server-channels.ts` 中的 `createChannelManager(...)` 是渠道运行编排核心。

它负责：

- 启动渠道账号
- 停止渠道账号
- 记录 runtime snapshot
- 跟踪 restart attempts
- 处理 health monitor
- 维护 manual stop 状态

这说明 Gateway 对渠道的管理是“账号级”的，而不是只在插件级做一次性初始化。

### 8.2 `channels.status`

`src/gateway/server-methods/channels.ts` 里的 `channels.status` 会：

- 读取所有渠道插件
- 读取各个账号的配置
- 计算默认账号
- 生成 channel summary
- 可选 probe / audit

这说明渠道状态是从 plugin config、runtime snapshot 和实际探测结果综合得出的。

### 8.3 `channels.logout`

`channels.logout` 会：

- 解析渠道与账号
- 调用 `stopChannel(...)`
- 再调用插件的 `gateway.logoutAccount`
- 必要时标记 account 已登出

这体现出 Gateway 和 ChannelPlugin 的协作关系：

- Gateway 管生命周期
- ChannelPlugin 管平台动作

## 9. 渠道消息流转

一个典型的消息流转可以概括成：

```text
外部平台消息
 -> ChannelPlugin 入口
 -> 解析 channel / account / peer / thread
 -> resolve-route
 -> sessionKey / agentId
 -> Gateway / Agent runtime
 -> 回复生成
 -> ChannelPlugin outbound / threading / messaging
 -> 发回外部平台
```

### 9.1 输入侧

输入侧主要在渠道插件中处理：

- webhook
- socket mode
- SDK event
- long-poll / REST
- bridge / adapter

### 9.2 路由侧

进入 OpenClaw 后，消息会进入 `src/routing/resolve-route.ts`，计算路由和 session key。

### 9.3 执行侧

然后会进入 Gateway / Agent runtime，实际做推理和工具调用。

### 9.4 输出侧

最后通过 channel 的 `outbound` / `messaging` / `threading` / `actions` 适配器，把结果回发到平台。

## 10. 渠道层的运行语义

### 10.1 Channel 是消息通道，不是 agent

渠道负责运输和平台语义，不负责模型推理。

### 10.2 Channel 也不是 Session

Session 是上下文容器，记录谁在和谁说、历史是什么、状态是什么。

Channel 只是决定消息从哪来、发到哪去。

### 10.3 Channel 也不是 Agent

Agent 是执行体，决定如何理解输入、调用工具、生成输出。

Channel 只负责把输入和输出安全地送达。

### 10.4 Channel 可以影响 Agent 行为，但不等于 Agent

通过 `agentPrompt`、`agentTools`、`threading`、`allowlist`、`security`、`commands` 等适配器，渠道可以影响 Agent 的上下文和可用工具。

但这仍然是“渠道参与编排”，不是“渠道变成 Agent”。

## 11. 典型的插件契约面

`src/channels/plugins/types.plugin.ts` 定义的契约非常能说明 OpenClaw 的设计思路。

### 11.1 配置与 UI

- `config`
- `configSchema`
- `defaults`
- `setupWizard`

### 11.2 生命周期与接入

- `setup`
- `pairing`
- `auth`
- `gateway`
- `lifecycle`
- `heartbeat`

### 11.3 消息与线程

- `outbound`
- `threading`
- `messaging`
- `mentions`
- `actions`

### 11.4 安全与权限

- `security`
- `allowlist`
- `execApprovals`
- `elevated`

### 11.5 与 Agent / Gateway 的交叉

- `gatewayMethods`
- `agentPrompt`
- `agentTools`
- `directory`
- `resolver`

这说明 ChannelPlugin 不是一个“收消息回消息”的轻量接口，而是 OpenClaw 平台语义的完整适配层。

## 12. 常见误解修正

### 12.1 Channel 和 Plugin 是不是一回事

不是。

- `Plugin` 是扩展装配单元
- `Channel` 是平台消息通道
- `ChannelPlugin` 是“以插件契约实现的渠道能力”

### 12.2 Channel 和 Session 是不是一回事

不是。

- `Channel` 决定消息经过哪个平台
- `Session` 决定消息进入哪个上下文

### 12.3 Channel 和 Agent 是不是一回事

不是。

- `Agent` 负责推理和行动
- `Channel` 负责消息运输和平台语义

### 12.4 Channel 层是不是只负责入口

也不是。

它还负责：

- outbound 回复
- thread binding
- mention / command gating
- account status
- pairing / auth
- health monitoring
- message actions

## 13. 小结

渠道层可以概括成一句话：

> OpenClaw 的渠道层是一个通过 `ChannelPlugin` 契约统一接入外部平台消息、再通过 routing 把消息导向 session / agent、并把输出安全回发到平台的编排系统。

如果再压缩一点，它的主干是：

```text
ChannelPlugin
 -> Gateway 编排
 -> routing 解析
 -> session / agent 执行
 -> outbound 回发
```

这也是为什么渠道层在 OpenClaw 里不是外围附件，而是平台化能力的关键入口。
