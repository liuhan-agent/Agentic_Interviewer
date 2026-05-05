# Phase 2: Gateway 与控制平面

## 1. 模块定位

Gateway 是 OpenClaw 的统一控制平面。

如果说 CLI 是本地命令入口，那么 Gateway 更像系统的“长驻调度中心”和“外部接入枢纽”。它的职责不是替代 Agent 推理，而是把外部世界接进来，再把请求送进内部运行时。

从整体架构上看，Gateway 位于：

```text
多入口
 -> Gateway
 -> Agent / Session / Routing
 -> Plugins / Channels / Services
 -> 多出口
```

它尤其负责承接这些入口：

- Web UI
- 移动端 / 桌面端
- ACP
- 长驻运行模式下的外部消息渠道
- 一部分 CLI 命令的远程/长驻访问路径

因此，Gateway 不是“所有入口的唯一必经点”，但它是 OpenClaw 平台化运行时中的统一控制中心。

## 2. 顶层源码边界

从顶层源码结构看，Gateway 模块的主边界如下：

- 模块导出入口：`src/gateway/server.ts`
- 核心装配中心：`src/gateway/server.impl.ts`
- 请求处理器总入口：`src/gateway/server-methods.ts`
- 方法清单与事件清单：`src/gateway/server-methods-list.ts`
- HTTP 服务层：`src/gateway/server-http.ts`
- WebSocket 运行时装配：`src/gateway/server-ws-runtime.ts`
- Control UI 托管：`src/gateway/control-ui.ts`
- Gateway 客户端：`src/gateway/client.ts`

这一组文件共同构成了 Gateway 的“控制平面骨架”。

## 3. Gateway 的核心职责

结合 `src/gateway/server.impl.ts` 和相关模块，Gateway 的职责主要有六类：

1. 启动和装配长驻服务
   - 负责配置、认证、TLS、Control UI、HTTP/WS 服务、sidecars、维护任务等

2. 对外暴露统一接口
   - 通过 WebSocket、HTTP、Control UI、OpenAI/OpenResponses 风格接口、插件 HTTP 路由等对外提供服务

3. 管理控制平面方法
   - 例如 `chat.send`、`sessions.list`、`agents.list`、`config.apply`、`health`、`node.invoke`

4. 维护事件广播与状态同步
   - 向 Web UI、App、节点、订阅者广播 `chat`、`agent`、`sessions.changed`、`presence` 等事件

5. 连接内部运行时
   - 先加载并装配插件、渠道等扩展能力，再把不同类型的请求分发给 Agent、Session、Config、Node、Cron 等业务模块；在需要时，也会调用插件提供的扩展方法和服务

6. 编排插件与渠道
   - 加载 Gateway 相关插件、合并插件扩展方法、启动渠道、管理健康检查和 sidecars

这里需要特别澄清一个容易混淆的点：

- `Agent`
- `Session`
- `Plugin`
- `Channel`
- `Config`
- `Node`
- `Cron`

这些并不都是 Gateway 自己的“职责本体”。

更准确地说，它们是 Gateway 需要连接、编排、调用的下游业务子系统。也就是说：

- Gateway 负责“接入、鉴权、分发、广播、控制”
- 下游模块负责“具体业务处理”

因此，Gateway 更像控制台和总调度台，而不是把所有业务都自己做完的执行器。

## 3.1 Gateway 后面的业务子系统是什么

为了避免后续阅读时抽象化，可以先把这些概念分成两类来看。

### A. Gateway 主要分发到的业务模块

- `Agent`：真正执行智能体推理和工具链的运行单元
- `Session`：一次对话/任务的上下文容器
- `Config`：系统配置和运行规则来源
- `Node`：接入 Gateway 的远端节点或设备
- `Cron`：定时任务和定时触发系统

这一类模块更像“Gateway 收到请求后，真正把业务交给谁处理”。

### B. Gateway 需要先装配并承载的扩展能力

- `Plugin`：为系统增加能力的扩展包
- `Channel`：消息进入和发出的通道

这里需要注意：

- `Plugin` 不只是被 Gateway 调用的下游模块，它还是 Gateway 启动时需要加载和装配进来的扩展面
- `Channel` 有些是核心内建能力，有些则通过插件提供，因此它既是消息通道能力，也是 Gateway 统一编排的一部分

所以更准确的理解是：

```text
Gateway
 -> 先装配 Plugin / Channel 等扩展能力
 -> 再把请求分发给 Agent / Session / Config / Node / Cron 等业务模块
```

例如，一个 Web UI 聊天请求通常会是：

```text
Gateway
 -> Session
 -> Agent
 -> Plugins / Tools / Memory
 -> Session 持久化
 -> Gateway 广播结果
```

而一个 `config.get` 请求则更可能是：

```text
Gateway
 -> Config
 -> 返回结果
```

所以 Gateway 不会对所有请求都走同一条链。

## 4. Gateway 的主启动链

Gateway 的启动入口很简单：

```text
src/gateway/server.ts
 -> src/gateway/server.impl.ts
 -> startGatewayServer(...)
```

其中：

- `src/gateway/server.ts` 只是薄导出层
- 真正的核心在 `src/gateway/server.impl.ts` 的 `startGatewayServer(...)`

这说明 Gateway 的设计不是分散式拼装，而是以 `server.impl.ts` 作为统一装配中心。

## 5. `startGatewayServer(...)` 在启动时做了什么

`src/gateway/server.impl.ts` 里的 `startGatewayServer(...)` 是整个 Gateway 模块最关键的总装配函数。

从源码看，它在启动时依次做了这些事情：

### 5.1 配置与启动前校验

- 读取配置快照：`readConfigFileSnapshot()`
- 做 legacy 配置迁移：`migrateLegacyConfig(...)`
- 执行配置合法性校验
- 自动启用插件：`applyPluginAutoEnable(...)`

也就是说，Gateway 启动不是“直接起服务”，而是先确保配置面是可用的。

### 5.2 认证与密钥运行时准备

- 预备 secrets runtime snapshot
- 执行 startup auth：`ensureGatewayStartupAuth(...)`
- 处理 token 缺失时的生成逻辑
- 合并 auth / tailscale 相关启动覆盖

这一层说明 Gateway 同时也是安全边界，不只是通信边界。

### 5.3 解析运行时配置

通过 `resolveGatewayRuntimeConfig(...)` 统一解析：

- bind/host/port
- control UI 开关
- OpenAI / OpenResponses HTTP 接口开关
- auth 配置
- tailscale 配置
- hooks 配置
- canvas host 配置

这一步的意义是：把磁盘配置和 CLI 启动参数合并成“最终运行态配置”。

### 5.4 加载插件与 Gateway 方法

通过：

- `loadGatewayPlugins(...)`
- `listGatewayMethods()`

Gateway 会把：

- 核心方法
- 插件追加方法
- 渠道插件 Gateway 方法

合并成最终的 Gateway methods 列表。

这说明 Gateway 不是一个固定 RPC 服务器，而是一个可扩展控制平面。

### 5.5 创建运行时状态

通过 `createGatewayRuntimeState(...)` 创建 Gateway 的核心运行时容器，包括：

- HTTP server / HTTP servers
- WebSocket server
- 客户端连接集合
- 广播器
- chat run 状态
- dedupe 状态
- abort 控制器
- tool event recipient 跟踪
- canvas host

这一步非常关键，因为它把 Gateway 从“配置对象”变成了“真正在线运行的状态机”。

### 5.6 启动侧车和维护服务

`startGatewayServer(...)` 后续还会装配：

- 渠道管理器：`createChannelManager(...)`
- readiness checker
- node registry
- node subscriptions
- cron service
- discovery 服务
- 维护定时器
- heartbeat
- transcript / lifecycle 事件订阅
- sidecars：`startGatewaySidecars(...)`

因此 Gateway 本质上是一个长驻 orchestrator，而不仅仅是一个 API 入口。

## 6. Gateway 的对外接口面

Gateway 对外不是单一接口，而是多种接口并存。

### 6.1 WebSocket 接口

相关文件：

- `src/gateway/server-ws-runtime.ts`
- `src/gateway/server/ws-connection.ts`
- `src/gateway/client.ts`

WebSocket 是 Gateway 最核心的交互通道之一，主要承担：

- 客户端连接
- request / response
- 事件推送
- hello / auth / connect 协议
- 长连接状态维持

Web UI 和很多控制面能力都主要建立在这层之上。

### 6.2 HTTP 接口

相关文件：

- `src/gateway/server-http.ts`

HTTP 层承担的职责包括：

- probe / health / ready
- Control UI 静态资源与辅助资源
- session history / kill
- tools invoke
- webhook / hook 分发
- OpenAI 风格接口：`/v1/chat/completions`
- OpenResponses 风格接口：`/v1/responses`
- 插件 HTTP 路由

这说明 Gateway 不只是 WS 控制面，也承担了 HTTP 网关职责。

### 6.3 Control UI 托管

相关文件：

- `src/gateway/control-ui.ts`
- `ui/src/ui/app-gateway.ts`

Gateway 会直接托管 Control UI 静态资源，并向浏览器端暴露 Gateway 连接接口。

也就是说：

```text
Browser UI
 -> GatewayBrowserClient
 -> Gateway WS/HTTP
```

Web UI 不是独立后端，它是直接挂在 Gateway 上的控制面前端。

### 6.4 Gateway 客户端协议面

相关文件：

- `src/gateway/client.ts`
- `src/acp/server.ts`
- `src/cli/gateway-cli/call.ts`

Gateway 不仅有 server，也有统一 client。

这套 client 被这些模块复用：

- Web UI 浏览器端客户端
- ACP server
- 一部分 CLI 的 gateway call / health / status / probe 路径

这说明 Gateway 的设计不是“只有服务端”，而是“定义了一套可复用的控制面协议”。

## 7. Gateway Methods：控制平面 RPC 层

Gateway 的请求方法由两层组成：

- 方法列表：`src/gateway/server-methods-list.ts`
- 方法处理器：`src/gateway/server-methods.ts`

### 7.1 方法列表的作用

`src/gateway/server-methods-list.ts` 维护基础 methods 和 events，例如：

- `health`
- `chat.send`
- `chat.abort`
- `sessions.list`
- `sessions.send`
- `agents.list`
- `config.apply`
- `node.invoke`
- `cron.run`
- `send`
- `agent`

同时它还会合并渠道插件扩展出来的 `gatewayMethods`。

这说明 Gateway method 表面上像 RPC，但实际上是可扩展的方法注册表。

### 7.2 处理器总入口的作用

`src/gateway/server-methods.ts` 的 `handleGatewayRequest(...)` 负责：

- 校验调用角色和 scope
- 控制部分写操作的速率限制
- 根据 method 名找到对应 handler
- 把请求放进 Gateway request scope
- 调用实际处理器

处理器来源包括：

- `server-methods/chat.ts`
- `server-methods/sessions.ts`
- `server-methods/agents.ts`
- `server-methods/config.ts`
- `server-methods/nodes.ts`
- `server-methods/usage.ts`
- `server-methods/skills.ts`
- `server-methods/tools-catalog.ts`

因此，Gateway methods 是 Gateway 控制平面的业务入口层。

## 8. 一个典型流转：`chat.send`

最能体现 Gateway 控制平面作用的例子，是 Web UI 聊天消息。

主链路可以概括为：

```text
ui/src/ui/app-gateway.ts
 -> GatewayBrowserClient
 -> Gateway WS
 -> src/gateway/server-methods.ts
 -> src/gateway/server-methods/chat.ts
 -> dispatchInboundMessage(...)
 -> Agent / Session / Reply pipeline
 -> Gateway 事件广播
 -> UI 收到 chat / agent / session.message 事件
```

这里 `src/gateway/server-methods/chat.ts` 的关键职责是：

- 校验输入
- 解析 session / delivery / provenance
- 把用户消息转成内部 inbound message
- 调用 `dispatchInboundMessage(...)`
- 处理 abort、history、transcript 注入等控制面能力

这个链路说明：

- Gateway 自己不做模型推理
- 但它负责把前端请求翻译成内部 Agent 流程
- 并把执行结果再广播给前端

## 8.1 Gateway 之后的“下一步”并不总是 Agent

这是理解控制平面时非常关键的一点。

Gateway 收到请求后，并不是固定都进入 Agent，更不是固定只剩下所谓的 ReAct 工作。真正的下一步，取决于请求的类型。

### 聊天/消息类请求

例如：

- `chat.send`
- `sessions.send`
- `agent`

通常会走：

```text
Gateway
 -> Session / Routing
 -> Agent runtime
 -> Model / Tools / Plugins / Memory
 -> Session 更新
 -> Gateway 广播 / Channel 回发
```

这一类请求里，Agent 是主角。

### 配置类请求

例如：

- `config.get`
- `config.set`
- `config.apply`
- `config.patch`

通常会走：

```text
Gateway
 -> Config 模块
 -> 返回结果
```

这类请求根本不需要进入 Agent。

### 会话管理类请求

例如：

- `sessions.list`
- `sessions.preview`
- `chat.history`
- `sessions.patch`

通常会走：

```text
Gateway
 -> Session 模块
 -> 返回结果或更新状态
```

这类请求更偏控制和数据访问，也不一定需要 Agent。

### 节点与设备类请求

例如：

- `node.invoke`
- `node.describe`
- `device.pair.approve`

通常会走：

```text
Gateway
 -> Node / Device 模块
 -> 远端节点或设备
```

### 定时任务类请求

例如：

- `cron.add`
- `cron.update`
- `cron.run`

通常会走：

```text
Gateway
 -> Cron 模块
 -> 到时再触发 Session / Agent / Send
```

因此，最准确的理解是：

> Gateway 负责把请求送到正确的业务子系统，而不是所有请求都直接落到 Agent。

## 8.2 Agent 执行也不等于“只剩 ReAct”

即使某条请求确实进入了 Agent，后续也不应该简单理解成“只剩 ReAct 工作”。

在 OpenClaw 中，Agent runtime 后面通常还包含这些环节：

- Session 上下文装配
- 模型选择
- 工具调用
- 记忆 / 检索
- 子代理
- 审批 / sandbox
- 输出持久化
- 事件回传

因此，更完整的链路应该写成：

```text
Gateway
 -> Session / Routing
 -> Agent runtime
 -> 上下文构造
 -> 模型推理 / 工具调用 / 子代理
 -> 持久化
 -> Gateway 广播 / Channel 回发
```

其中 ReAct 只是 Agent 执行阶段里可能采用的一种工作范式，不等于 Gateway 后的全部流程。

## 9. Gateway 与事件系统的关系

Gateway 不只是 request/response 服务器，它还是事件分发中心。

`src/gateway/server-methods-list.ts` 中定义的事件包括：

- `agent`
- `chat`
- `session.message`
- `sessions.changed`
- `presence`
- `heartbeat`
- `cron`
- `exec.approval.requested`
- `exec.approval.resolved`
- `voicewake.changed`

在 `src/gateway/server.impl.ts` 中，Gateway 会订阅：

- agent events
- transcript update
- session lifecycle event
- heartbeat event

然后通过 `broadcast(...)` / `broadcastToConnIds(...)` 推送给 UI、节点、订阅者。

这说明 Gateway 是控制平面的“状态同步总线”。

## 10. Gateway 与 Agent 的关系

Gateway 不是 Agent 本身，但它是 Agent 的重要入口编排层。

两者关系可以概括为：

- Gateway 负责接请求
- Agent 负责执行推理与工具链
- Session / Routing 决定消息落到哪个上下文
- Gateway 再把结果回推给客户端或渠道

所以：

```text
Gateway = 控制与接入
Agent = 执行与推理
```

这也是为什么说 Gateway 很关键，但它不是系统唯一核心。

换句话说：

- Gateway 决定“请求去哪”
- Agent 决定“需要智能处理的请求怎么做”

二者是上下游关系，而不是谁替代谁。

## 11. Gateway 与插件系统的关系

Gateway 和插件系统是强耦合但边界清晰的关系。

### 11.1 Gateway 依赖插件扩展能力

在启动阶段，Gateway 会调用：

- `loadGatewayPlugins(...)`

用来装入：

- 插件追加 methods
- 插件服务
- 渠道相关能力
- 插件 HTTP 路由

这说明 Gateway 是插件能力的承载平面。

### 11.2 插件并不直接替代 Gateway

插件负责提供可扩展能力，Gateway 负责把这些能力纳入统一控制平面。

所以它们关系不是“谁替代谁”，而是：

```text
Plugins 提供扩展能力
Gateway 提供统一承载与对外暴露
```

## 12. Gateway 与渠道系统的关系

Gateway 和渠道系统的关系也很关键。

在 `src/gateway/server.impl.ts` 中，Gateway 会创建：

- `createChannelManager(...)`

并负责：

- 启动渠道
- 单独启动某个渠道
- 停止渠道
- 维护渠道健康状态

同时，Gateway 的方法和事件里也包含了渠道相关控制面能力，例如：

- `channels.status`
- `channels.logout`

因此，在长驻运行模式下，外部消息渠道通常是挂在 Gateway 下面统一编排的。

## 13. Gateway 与 ACP / CLI / Web UI 的关系

Gateway 作为控制平面，被多个入口复用。

### 13.1 Web UI

- `ui/src/ui/app-gateway.ts`
- 通过浏览器 Gateway client 连入 Gateway

### 13.2 ACP

- `src/acp/server.ts`
- 通过 `GatewayClient` 连入 Gateway
- 把 ACP 协议请求翻译成 Gateway 调用

### 13.3 CLI

CLI 和 Gateway 的关系，可以先用下面这组总结来理解：

```text
CLI 是本地入口层
有些 CLI 命令直接调用本地业务模块
有些 CLI 命令直接启动 Gateway
有些 CLI 命令把 Gateway 当成远程控制面来调用
```

对应到源码，可以这样理解：

- “直接调用本地业务模块”对应很多本地命令路径，例如 `status`、`config`、`sandbox` 一类命令，会直接进入 `src/commands/*`、`src/config/*`、`src/agents/sandbox/*` 等本地模块，不一定先经过 Gateway
- “直接启动 Gateway”对应 `openclaw gateway run` 这类命令，会进入 `src/cli/gateway-cli.ts`、`src/cli/gateway-cli/register.ts`，然后进入 `src/gateway/server.ts`
- “把 Gateway 当成远程控制面来调用”对应 `src/cli/gateway-cli/call.ts` 这类路径，CLI 会通过 `callGateway(...)` 走 Gateway client 协议，此时 CLI 实际上充当的是 Gateway 的一个客户端

因此，CLI 不等于 Gateway，但它和 Gateway 有明确交集；最关键的区别是：

- CLI 是本地入口层
- Gateway 是长驻控制平面

因此，Gateway 不是只服务 UI，它也是 CLI 和 ACP 的共享控制面后端。

## 14. 为什么说 Gateway 是“控制平面”

从源码结构上看，Gateway 之所以是“控制平面”，主要因为它集中负责了这些横向能力：

- 连接管理
- 认证与鉴权
- 方法分发
- 事件广播
- 状态同步
- 节点与设备编排
- 渠道启动与健康检查
- 配置变更
- 控制 UI 托管
- sidecars 与维护任务

这些能力本质上都不是“Agent 推理本身”，而是“平台运行与操作控制”。

这正是控制平面的典型特征。

## 15. 小结

Gateway 模块可以概括为：

> OpenClaw 的统一控制平面与长驻调度中心。

如果压缩成一条主干结构，可以写成：

```text
Gateway server
 -> 配置 / 认证 / 插件 / 运行时装配
 -> WS / HTTP / Control UI / Gateway methods
 -> Agent / Sessions / Channels / Nodes / Cron / Plugins
 -> 事件广播与状态同步
```

所以在 OpenClaw 的系统架构里：

- CLI 负责本地命令入口
- Gateway 负责统一控制平面
- Agent 负责执行内核
- 插件负责扩展能力

这四者共同构成了 OpenClaw 平台化运行时的主骨架。

再进一步压缩成一句最重要的话：

> Gateway 不是“所有业务都自己做”，而是“把不同类型的请求分发给正确的业务子系统，并统一管理连接、控制、状态和事件”。
